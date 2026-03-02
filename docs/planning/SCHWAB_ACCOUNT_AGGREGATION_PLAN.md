# Per-Account Realized Performance Aggregation for Schwab

## Context

The system merges 3 Schwab accounts (165, 013, 252) into one return stream, creating a **39pp gap** (+30.69% system vs -8.29% broker for account 165). When account 165 is run in isolation via `account="87656165"`, it returns -8.37% — matching broker within 0.1pp. The problem is purely architectural: cross-account mixing + global synthetic backdating.

**Gap decomposition:**
- Pre-2025 synthetic period (May-Dec 2024): +23.3pp — account 165/013 positions backdated to account 252's inception
- 2025 account-scope difference: +14.5pp — pooling account 252 (+10.65%) with account 165 (-8.29%)
- 2026 spillover: -0.2pp

**Reference docs:**
- Investigation: `docs/planning/SCHWAB_RETURN_GAP_INVESTIGATION.md`
- Codex fix recommendations: `docs/planning/SCHWAB_ACCOUNT_LEVEL_FIX_PLAN.md`

## Approach

Run realized analysis per-account for Schwab, then aggregate monthly NAV/flow series and recompute combined Modified Dietz returns. Gate: fires when Schwab-scoped (via `source="schwab"` or `institution` matching Schwab) + no explicit `account` + >1 discovered account. All other paths unchanged.

Also fix per-symbol synthetic backdating (Fix B) — even within one account, symbols get backdated to global inception when they should use their earliest transaction date.

## Files to Modify

| File | Changes |
|------|---------|
| `core/realized_performance_analysis.py` | Phases 1-4: expose tw_flows, extract single-scope helper, add aggregation wrapper, Fix B |
| `core/result_objects/realized_performance.py` | Add `account_aggregation` field to `RealizedMetadata` + wire `to_dict`/`from_dict` |
| `services/portfolio_service.py` | Phase 5: cache key version bump (line 652) |
| `tests/core/test_realized_performance_analysis.py` | Update 3 existing tests, add ~9 new tests |

## Implementation

### Phase 1: Expose `tw_flows` in `_postfilter`

**File:** `core/realized_performance_analysis.py`

At line 4648 (after `observed_only_net_flows` block in `_postfilter` dict), add:

```python
"time_weighted_flows": {
    ts.date().isoformat(): float(val)
    for ts, val in tw_flows.items()
},
```

Variables `tw_flows` (line 4010) and `observed_tw_flows` (line 4038) already exist. Only `tw_flows` is needed for aggregation.

### Phase 2: Extract single-scope helper

**File:** `core/realized_performance_analysis.py`

Move the body of `analyze_realized_performance()` (lines 2844-4706) into `_analyze_realized_performance_single_scope()` with identical signature. The public function becomes a thin dispatcher:

```python
def analyze_realized_performance(
    positions, user_email, benchmark_ticker="SPY", source="all",
    institution=None, account=None, include_series=False,
    backfill_path=None, price_registry=None,
):
    source = (source or "all").lower().strip()
    institution = (institution or "").strip() or None
    account = (account or "").strip() or None

    should_aggregate = (
        not account
        and (
            (institution is not None and match_institution(institution, "schwab"))
            or source == "schwab"
        )
    )

    if should_aggregate:
        return _analyze_realized_performance_account_aggregated(
            positions=positions, user_email=user_email,
            benchmark_ticker=benchmark_ticker, source=source,
            institution=institution, include_series=include_series,
            backfill_path=backfill_path, price_registry=price_registry,
        )

    return _analyze_realized_performance_single_scope(
        positions=positions, user_email=user_email,
        benchmark_ticker=benchmark_ticker, source=source,
        institution=institution, account=account,
        include_series=include_series, backfill_path=backfill_path,
        price_registry=price_registry,
    )
```

Gate fires when: (a) no explicit `account`, AND (b) either `institution` matches Schwab OR `source="schwab"`. `source="all"` without `institution` won't aggregate (combined-all-sources path stays as-is). `source="schwab"` without `institution` WILL aggregate (this is the `source` shortcut path).

### Phase 3: Account discovery + aggregation wrapper

#### 3a. `_discover_schwab_account_ids(positions, fifo_transactions, institution)`

Discover accounts from **both** positions and transactions. Positions catch accounts with current holdings; transactions catch accounts that may have been fully closed (no current positions but have historical activity). This ensures closed-out accounts are included in aggregation.

**Canonical ID:** `account_name` (the human-readable account number like `"87656165"`). This is what users pass to `account=` and what `_match_account()` matches against. Do NOT use `account_id` (which is a SHA-256 hash of the account number, used internally for dedup/privacy).

Field mapping:
- Positions: `account_id` = hash, `account_name` = number, `brokerage_name` = "Charles Schwab" (from `schwab_positions.py:108-110,140-142`)
- Normalized transactions: `account_id` = hash, `account_name` = number, `_institution` = "charles_schwab" (from `normalizers/schwab.py:662-663,781-783`)
- Position filtering uses `brokerage_name`; transaction filtering uses `_institution` (matching existing filter at `realized_performance_analysis.py:2977`)

```python
def _discover_schwab_account_ids(positions, fifo_transactions, institution):
    """Discover Schwab account IDs from positions AND transactions.

    Uses account_name (human-readable number) as canonical ID.
    Positions provide accounts with current holdings.
    Transactions provide accounts that may have been fully closed.
    Union ensures no account is missed.
    """
    seen = set()
    # From positions — use account_name (number), filter by brokerage_name
    for pos in (getattr(positions.data, "positions", None) or []):
        brokerage = str(pos.get("brokerage_name") or "")
        if not match_institution(brokerage, "schwab"):
            continue
        acct = str(pos.get("account_name") or "").strip()
        if acct:
            seen.add(acct)
    # From normalized transactions — use account_name, filter by _institution
    # (FIFO rows carry `_institution` from normalizer, e.g. "charles_schwab" — see schwab.py:783)
    for txn in (fifo_transactions or []):
        inst = str(txn.get("_institution") or "")
        if not match_institution(inst, "schwab"):
            continue
        acct = str(txn.get("account_name") or "").strip()
        if acct:
            seen.add(acct)
    return sorted(seen)
```

Note: Using `match_institution(brokerage, "schwab")` on both positions and transactions ensures consistent filtering regardless of `source` setting. This works even in `source="all"` mode because the `brokerage_name` / `institution` field is set on each row by the normalizer, independent of the source routing.

#### 3b. `_analyze_realized_performance_account_aggregated(...)`

1. Discover account IDs (from positions + transactions). If ≤1, delegate to single-scope with that account (fast path).
2. Run `_analyze_realized_performance_single_scope()` per account with `include_series=False`.
3. Skip accounts that return error dicts or have malformed/empty `_postfilter`; log in `per_account_errors`.
4. If all accounts fail or no valid results remain, fall back to single-scope (no account filter) with a warning.
5. Extract `_postfilter` from each result's `realized_metadata._postfilter`: `monthly_nav`, `net_flows`, `time_weighted_flows`.
6. Sum across accounts via `_sum_account_monthly_series()` (union index, ffill NAV, fillna(0) flows).
7. Call `compute_monthly_returns()` on aggregated series.
8. Fetch benchmark, align, call `compute_performance_metrics()`.
9. Build combined `realized_metadata` via `_merge_realized_metadata()` + add `account_aggregation` diagnostics.
10. Return `RealizedPerformanceResult`.

```python
def _analyze_realized_performance_account_aggregated(
    positions, user_email, benchmark_ticker="SPY", source="all",
    institution=None, include_series=False,
    backfill_path=None, price_registry=None,
):
    # Step 1: Get transactions for account discovery
    # (reuse the same fetch that single-scope would do — transactions are
    # fetched once and passed to discovery, not re-fetched per account)
    # Note: fifo_transactions are available after the initial fetch in
    # single-scope. For discovery, we need to do a lightweight pre-fetch.
    # The per-account single-scope calls will re-fetch with account filter.

    # Build fmp_ticker_map from positions (same as single-scope at line 2869/2874)
    _, fmp_ticker_map, _ = _build_current_positions(positions, institution=institution)

    account_ids = _discover_schwab_account_ids(positions, _prefetch_fifo_transactions(positions, user_email, source, institution), institution)

    if len(account_ids) <= 1:
        single_account = account_ids[0] if account_ids else None
        return _analyze_realized_performance_single_scope(
            positions=positions, user_email=user_email,
            benchmark_ticker=benchmark_ticker, source=source,
            institution=institution, account=single_account,
            include_series=include_series, backfill_path=backfill_path,
            price_registry=price_registry,
        )

    per_account = {}
    per_account_errors = {}
    for acct in account_ids:
        try:
            result = _analyze_realized_performance_single_scope(
                positions=positions, user_email=user_email,
                benchmark_ticker=benchmark_ticker, source=source,
                institution=institution, account=acct,
                include_series=False, backfill_path=backfill_path,
                price_registry=price_registry,
            )
            if isinstance(result, dict) and result.get("status") == "error":
                per_account_errors[acct] = result.get("message", "unknown error")
                continue
            # Validate _postfilter has all required series for aggregation
            pf = getattr(getattr(result, "realized_metadata", None), "_postfilter", None) or {}
            missing_keys = [k for k in ("monthly_nav", "net_flows", "time_weighted_flows") if not pf.get(k)]
            if missing_keys:
                per_account_errors[acct] = f"missing _postfilter keys: {missing_keys}"
                continue
            per_account[acct] = result
        except Exception as e:
            per_account_errors[acct] = str(e)

    if not per_account:
        # All accounts failed — fall back to legacy single-scope
        logger.warning("Account aggregation: all %d accounts failed, falling back to single-scope", len(account_ids))
        return _analyze_realized_performance_single_scope(
            positions=positions, user_email=user_email,
            benchmark_ticker=benchmark_ticker, source=source,
            institution=institution, account=None,
            include_series=include_series, backfill_path=backfill_path,
            price_registry=price_registry,
        )

    return _build_aggregated_result(
        per_account=per_account,
        per_account_errors=per_account_errors,
        benchmark_ticker=benchmark_ticker,
        include_series=include_series,
        price_registry=price_registry,
        fmp_ticker_map=fmp_ticker_map,
    )
```

#### 3c. `_sum_account_monthly_series(per_account)` → `(nav, net, tw)` pd.Series

```python
def _dict_to_series(d):
    """Convert {date_str: float} dict to pd.Series with DatetimeIndex."""
    if not d:
        return pd.Series(dtype=float)
    return pd.Series(d, dtype=float).pipe(
        lambda s: s.set_axis(pd.to_datetime(s.index))
    )

def _sum_account_monthly_series(per_account):
    all_navs, all_nets, all_tws = [], [], []
    for result in per_account.values():
        pf = result.realized_metadata._postfilter or {}
        all_navs.append(_dict_to_series(pf.get("monthly_nav", {})))
        all_nets.append(_dict_to_series(pf.get("net_flows", {})))
        all_tws.append(_dict_to_series(pf.get("time_weighted_flows", {})))

    if not any(not s.empty for s in all_navs):
        return pd.Series(dtype=float), pd.Series(dtype=float), pd.Series(dtype=float)

    union_idx = pd.DatetimeIndex(sorted(
        set().union(*(s.index for s in all_navs if not s.empty))
    ))
    combined_nav = sum(s.reindex(union_idx).ffill().fillna(0.0) for s in all_navs)
    combined_net = sum(s.reindex(union_idx).fillna(0.0) for s in all_nets)
    combined_tw = sum(s.reindex(union_idx).fillna(0.0) for s in all_tws)
    return combined_nav, combined_net, combined_tw
```

#### 3d. `_build_aggregated_result(per_account, per_account_errors, benchmark_ticker, include_series, price_registry, fmp_ticker_map)`

Reuses existing patterns from `analyze_realized_performance`. Full field-by-field merge spec:

**Step 1: Aggregate monthly series + compute returns**
```python
agg_nav, agg_net, agg_tw = _sum_account_monthly_series(per_account)
agg_monthly_returns, agg_return_warnings = compute_monthly_returns(
    monthly_nav=agg_nav,
    net_flows=agg_net,
    time_weighted_flows=agg_tw,
)
```

**Step 2: Benchmark fetch + alignment + metrics**
Same pattern as lines 4241-4248, 4252-4257, 4471, 4478:
```python
inception_date = min(r.realized_metadata.inception_date for r in per_account.values())
end_date = max of per-account end dates (or date.today())

inception_date = min(str(r.realized_metadata.inception_date) for r in per_account.values())
end_date = date.today()
# fmp_ticker_map: thread through from caller (same as single-scope at line 3014/4245)
benchmark_prices = fetch_monthly_close(
    benchmark_ticker,
    start_date=inception_date,
    end_date=end_date,
    fmp_ticker_map=fmp_ticker_map,
)
benchmark_returns = calc_monthly_returns(benchmark_prices)
benchmark_returns = _series_from_cache(benchmark_returns)
agg_monthly_returns = _normalize_monthly_index(agg_monthly_returns)
benchmark_returns = _normalize_monthly_index(benchmark_returns)

aligned = pd.DataFrame({"portfolio": agg_monthly_returns, "benchmark": benchmark_returns}).dropna()
if aligned.empty:
    # Mirror single-scope guard at line 4259 — return error dict
    return {"status": "error", "message": "No overlapping benchmark data for aggregated returns."}
risk_free_rate = _safe_treasury_rate(inception_date, end_date)
start_iso = aligned.index.min().date().isoformat()
end_iso = aligned.index.max().date().isoformat()
perf_metrics = compute_performance_metrics(
    portfolio_returns=aligned["portfolio"],
    benchmark_returns=aligned["benchmark"],
    risk_free_rate=risk_free_rate,
    benchmark_ticker=benchmark_ticker,
    start_date=start_iso,
    end_date=end_iso,
)
```

**Step 3: Merge metadata — field-by-field spec**

| Field | Merge strategy |
|-------|---------------|
| `realized_pnl` | Sum across accounts |
| `unrealized_pnl` | Sum across accounts |
| `net_contributions` | Sum across accounts |
| `nav_pnl_usd` | Sum across accounts |
| `nav_pnl_synthetic_enhanced_usd` | Sum across accounts |
| `nav_pnl_observed_only_usd` | Sum across accounts |
| `nav_pnl_synthetic_impact_usd` | Sum across accounts |
| `lot_pnl_usd` | Sum across accounts |
| `reconciliation_gap_usd` | Sum across accounts |
| `pnl_basis` | Take from first account (all same) |
| `nav_metrics_estimated` | `any()` across accounts |
| `high_confidence_realized` | `all()` across accounts |
| `income` | Sum `total`/`dividends`/`interest`; merge `by_month`/`by_symbol`/`by_institution` (sum values per key); recompute `current_monthly_rate` = latest 3-month avg of summed by_month, `projected_annual` = rate×12, `yield_on_cost` = projected_annual / sum(total_cost_basis_usd) × 100, `yield_on_value` = projected_annual / sum(current_portfolio_value) × 100 (matching existing formula at line 4331-4339) |
| `data_coverage` | Weighted average by transaction count |
| `inception_date` | `min()` across accounts |
| `synthetic_positions` | Union (deduplicated by ticker/currency/direction) |
| `synthetic_entry_count` | Sum |
| `synthetic_current_position_count` | Sum |
| `synthetic_current_position_tickers` | Union |
| `synthetic_current_market_value` | Sum |
| `synthetic_incomplete_trade_count` | Sum |
| `first_transaction_exit_count` | Sum |
| `first_transaction_exit_details` | Concatenate |
| `extreme_return_months` | Recompute from aggregated returns |
| `data_quality_flags` | Union (deduplicate by code) |
| `unpriceable_symbol_count` | Recount from union |
| `unpriceable_symbols` | Union |
| `unpriceable_reason_counts` | Sum per reason |
| `unpriceable_reasons` | Merge dicts |
| `ibkr_pricing_coverage` | Take from first (all same for Schwab — zeroes) |
| `source_breakdown` | Sum per source |
| `reliable` | `all()` across accounts |
| `reliability_reasons` | Union |
| `holdings_scope` | Take from first account result (respects source vs institution scoping logic at line 592/677) |
| `source_holding_symbols` | Union |
| `source_holding_count` | Recount from union |
| `source_transaction_count` | Sum |
| `cross_source_holding_leakage_symbols` | Union |
| `reliability_reason_codes` | Union |
| `fetch_errors` | Merge dicts |
| `flow_source_breakdown` | Sum per key |
| `inferred_flow_diagnostics` | Merge: sum `total_inferred_event_count`/`total_inferred_net_usd`; `by_provider` keyed by provider name (e.g. "schwab") — sum nested counts across accounts (`slice_count`, `transaction_count`, `income_count`, `inferred_event_count`, `inferred_net_usd`); `by_slice` keyed by slice_key (includes account hash, no collision) — plain union; min/max event window; `mode`/`fallback_slices_present`/`replayed_fallback_provider_activity` take from first (all same) |
| `provider_flow_coverage` | Merge dicts (provider keys are per-account, no collision) |
| `flow_fallback_reasons` | Union |
| `dedup_diagnostics` | Sum `input_count`/`output_count`, merge dropped dicts |
| `external_net_flows_usd` | Sum |
| `net_contributions_definition` | Take from first (all same) |
| `data_warnings` | Union + add aggregation summary warning |
| `futures_cash_policy` | Take from first (string, all same for Schwab: "fee_only") |
| `futures_txn_count_replayed` through `futures_missing_fx_count` | Sum (all zero for Schwab) |
| `income_flow_overlap_*` fields | Sum counts/amounts, merge dicts |
| `monthly_nav` | From aggregated series (if `include_series`) |
| `growth_of_dollar` | Recompute from aggregated returns (if `include_series`) |
| `_postfilter` | Build fresh from aggregated series (full parity with single-scope) |
| `account_aggregation` | NEW — diagnostics block (see below) |

**Step 4: Build `_postfilter` for the aggregated result**

The aggregated `_postfilter` must have full parity with single-scope `_postfilter` (lines 4616-4651). Exact key contract matching current single-scope shape:

```python
"_postfilter": {
    # Returns (from aggregated + aligned series)
    "portfolio_monthly_returns": {date_str: float for aligned portfolio returns},
    "benchmark_monthly_returns": {date_str: float for aligned benchmark returns},
    "selected_portfolio_monthly_returns": same as portfolio_monthly_returns (no date selection in aggregated mode),
    "selected_benchmark_monthly_returns": same as benchmark_monthly_returns,
    # NAV series (from aggregated)
    "monthly_nav": {date_str: float for aggregated NAV},
    "observed_only_monthly_nav": sum of per-account observed_only_monthly_nav from their _postfilters,
    # Flow series (from aggregated)
    "net_flows": {date_str: float for aggregated net flows},
    "observed_only_net_flows": sum of per-account observed_only_net_flows from their _postfilters,
    "time_weighted_flows": {date_str: float for aggregated tw flows},
    # Scalars
    "risk_free_rate": float (from _safe_treasury_rate(inception_date, end_date)),
    "benchmark_ticker": str,
}
```

**Step 5: Build `account_aggregation` diagnostics**

```python
"account_aggregation": {
    "mode": "per_account_modified_dietz",
    "account_count": len(per_account),
    "accounts": {
        acct: {
            "total_return_pct": result.returns.get("total_return"),
            "inception_date": str(result.realized_metadata.inception_date),
            "nav_pnl_usd": result.realized_metadata.nav_pnl_usd,
            "external_net_flows_usd": result.realized_metadata.external_net_flows_usd,
        }
        for acct, result in per_account.items()
    },
    "failed_accounts": per_account_errors,
}
```

**Step 6: Build `RealizedPerformanceResult`**

Construct `returns` dict from `perf_metrics` (same pattern as lines 4560-4600), construct `RealizedMetadata` with merged fields, return `RealizedPerformanceResult(returns=returns, realized_metadata=metadata, analysis_period=..., risk_metrics=..., ...)`.

### Phase 3e: `RealizedMetadata` dataclass update

**File:** `core/result_objects/realized_performance.py`

Add `account_aggregation` field to `RealizedMetadata`:

```python
# After line 158 (_postfilter field):
account_aggregation: Optional[Dict[str, Any]] = None
```

Wire in `to_dict()` — add after the `_postfilter` block (after line 228):
```python
if self.account_aggregation is not None:
    d["account_aggregation"] = self.account_aggregation
```

Wire in `from_dict()` — add to constructor call (after line 308):
```python
account_aggregation=d.get("account_aggregation"),
```

The field is optional and only populated when account aggregation fires. It is NOT stripped from API responses (unlike `_postfilter`) — it provides useful diagnostics to callers.

### Phase 4: Fix B — per-symbol synthetic backdating

**File:** `core/realized_performance_analysis.py`

Note: `earliest_txn_by_symbol` (lines 1196-1202) is keyed by symbol string only (not by direction). This is intentional and conservative — for the rare case of long+short on the same symbol, we use the earliest date across all directions. The comment at lines 1193-1195 documents this choice. No change needed to the key structure.

#### Current positions (line 1240):
```python
# Before: symbol_inception = inception_date
# After:
symbol_inception = earliest_txn_by_symbol.get(ticker, inception_date)
```

`earliest_txn_by_symbol` is already computed at lines 1196-1202. Fallback to `inception_date` when no transactions exist for the symbol (zero-history case).

#### Incomplete trades (line 1283):
```python
# Before: synthetic_date = inception_date - timedelta(seconds=1)
# After:
symbol_anchor = earliest_txn_by_symbol.get(symbol)
if symbol_anchor is not None:
    synthetic_date = min(symbol_anchor, sell_date) - timedelta(seconds=1)
else:
    synthetic_date = sell_date - timedelta(seconds=1)
```

### Phase 5: Cache key version bump

**File:** `services/portfolio_service.py` line 652

Change prefix from `"realized_performance_"` to `"realized_performance_v2_"`.

## Implementation Order

1. **Phase 1** (tw_flows) — no dependencies, prerequisite for Phase 3
2. **Phase 2** (extract helper) — pure refactor, no behavior change
3. **Phase 3** (aggregation wrapper + metadata field) — depends on Phases 1+2
4. **Phase 4** (Fix B) — independent, can be done in parallel with 1-3
5. **Phase 5** (cache bump) — last, after all functional changes

## Tests

**Update existing** (Fix B):
- `test_build_position_timeline_adds_synthetic_for_current_without_opening_history` (line 318): update expected synthetic date from global inception to symbol's earliest txn
- `test_synthetic_current_position_always_uses_global_inception` (line 5598): rename to `..._uses_per_symbol_inception`, update expected date
- `test_zero_history_symbol_falls_back_to_global_inception` (line 5640): should still pass unchanged (fallback preserved)

**Add new** (aggregation):
- `test_discover_schwab_account_ids_from_positions` — mock positions with 3 Schwab + 1 IBKR account → returns 3 sorted IDs
- `test_discover_schwab_account_ids_from_transactions` — mock transactions with account that has no current positions → still discovered
- `test_discover_schwab_account_ids_deduplicates` — same account in positions and transactions → appears once
- `test_sum_account_monthly_series_alignment` — verify union index, NAV sums, flow sums with overlapping/non-overlapping months
- `test_sum_account_monthly_series_empty_input` — empty per_account dict → returns empty series (no crash)
- `test_account_aggregation_two_accounts` — integration: known _postfilter data → verify combined Modified Dietz return
- `test_account_aggregation_single_account_fast_path` — ≤1 account → delegates to single-scope
- `test_account_aggregation_gate_only_schwab` — non-Schwab or explicit `account=` bypasses aggregation
- `test_account_aggregation_gate_source_schwab` — `source="schwab"` without `institution` still aggregates
- `test_account_aggregation_partial_failure` — one account errors → remaining still produce valid result + error logged
- `test_account_aggregation_all_fail_fallback` — all accounts error → falls back to legacy single-scope path
- `test_aggregated_postfilter_has_all_keys` — verify aggregated `_postfilter` contains same keys as single-scope
- `test_realized_metadata_account_aggregation_roundtrip` — verify `account_aggregation` survives `to_dict()`/`from_dict()` roundtrip (None when absent, dict when present)

## Verification

```bash
# Run tests
python3 -m pytest tests/core/test_realized_performance_analysis.py -x -q

# Live check — Schwab combined should now be close to asset-weighted broker average (~low single digits)
python3 -c "
from mcp_tools.performance import get_performance
for inst in ['charles_schwab', 'interactive_brokers']:
    r = get_performance(mode='realized', institution=inst, format='agent', use_cache=False)
    s = r['snapshot']
    print(f'{inst}: {s[\"returns\"][\"total_return_pct\"]}%')
"

# IBKR should be unchanged (-71.67%)
# Schwab account 165 in isolation should still be ~-8.37%
python3 -c "
from mcp_tools.performance import get_performance
r = get_performance(mode='realized', institution='charles_schwab', account='87656165', format='agent', use_cache=False)
print(f'Schwab 165: {r[\"snapshot\"][\"returns\"][\"total_return_pct\"]}%')
"
```

## Acceptance Gates

- Schwab combined: gap vs asset-weighted broker average ≤ 5pp (from 39pp)
- IBKR: no change (gate doesn't fire)
- Schwab account 165 in isolation: unchanged (~-8.37%)
- All existing tests pass (with Fix B updates)
- Response schema backward-compatible (new `account_aggregation` block is additive)
- Aggregated `_postfilter` has same keys as single-scope `_postfilter`

## Implementation Status (2026-02-28)

**Commit:** `8ce1a340`

### Phases completed
- ✅ Phase 1: `time_weighted_flows` added to `_postfilter`
- ✅ Phase 2: Single-scope helper extracted, dispatcher added
- ✅ Phase 3: Account discovery + aggregation wrapper + metadata field
- ❌ Phase 4 (Fix B): **Reverted** — caused IBKR regression (+261% from inception date shift). Global inception backdating needed for single-account paths.
- ✅ Phase 5: Cache key bumped to `realized_performance_v2_`

### Results

| Path | Before | After | Broker ref |
|------|--------|-------|------------|
| Schwab combined | +30.69% | **+18.45%** | ~0% to +11% |
| Schwab 165 isolated | -8.37% | **-7.97%** | -8.29% |
| IBKR | -71.66% | **-71.66%** | unchanged |

### Per-account diagnostics
- Account 252: +2046.57% (broker +10.65%) — $21 start + $45K flows → extreme Modified Dietz
- Account 013: +41.13% (broker -14.69%) — $134 start + $5K flows → same issue
- Account 165: -7.97% (broker -8.29%) — $21K balance, $0 flows → excellent match

### Remaining gap (~7-18pp above broker average)
Root cause: accounts 252 and 013 have tiny starting balances with large subsequent contributions. Modified Dietz on near-zero V_start with synthetic positions produces extreme returns that inflate the combined aggregation. This is a per-account data quality issue, not a cross-account mixing problem.

### Tests
- 140 tests pass (13 new aggregation tests added)
- Fix B tests reverted to global inception expectations
