# Schwab Account-Level Fix Plan

Date: 2026-02-28
Owner: Codex recommendation draft
Primary target: Fix A (per-account execution + aggregation)

## Decision
Implement Fix A in `core/realized_performance_analysis.py` as a core-level wrapper around the existing single-scope pipeline, then aggregate per-account monthly NAV/flow series and recompute combined returns/metrics.

Do **not** put the loop in `mcp_tools/performance.py`.

## 1) Exact files/functions to modify (with current line anchors)

### Primary implementation files

1. `core/realized_performance_analysis.py`
- `analyze_realized_performance(...)` at `2810`
- `_build_current_positions(...)` at `490` (read-only for trace; optional helper reuse)
- `build_position_timeline(...)` at `1089` (Fix B changes here)
- `compute_monthly_returns(...)` at `1845` (reuse for aggregated returns)
- `_postfilter` payload builder in `realized_metadata` at `4616-4651` (add weighted-flow series)

2. `services/portfolio_service.py`
- `analyze_realized_performance(...)` at `599`
- cache key construction at `652-656` (add cache schema/version token to avoid stale pre-fix cache collisions)

### Optional/validation files

3. `tests/core/test_realized_performance_analysis.py`
- synthetic placement tests currently asserting global-inception behavior:
  - `test_build_position_timeline_adds_synthetic_for_current_without_opening_history` at `318`
  - `test_synthetic_current_position_always_uses_global_inception` at `5598`
  - `test_zero_history_symbol_falls_back_to_global_inception` at `5640`
- add new account-aggregation tests near other `analyze_realized_performance` pipeline tests (`~1650+` section)

No entry-point changes are required in:
- `mcp_tools/performance.py` (`_run_realized_with_service` at `365-393`)

## 2) What the change looks like (implementation sketch)

### A. Split single-scope logic and add Schwab account-aggregation wrapper

In `core/realized_performance_analysis.py`:

```python
# new private helper: current body of analyze_realized_performance
# (existing logic from ~2846 onward moves here with minimal edits)
def _analyze_realized_performance_single_scope(..., *, _disable_account_aggregation: bool = False):
    ...


def analyze_realized_performance(...):
    source = source.lower().strip()
    institution = (institution or "").strip() or None
    account = (account or "").strip() or None

    should_account_aggregate = (
        not account
        and source in {"all", "schwab"}
        and (
            (institution is not None and match_institution(institution, "schwab"))
            or source == "schwab"
        )
    )

    if should_account_aggregate:
        return _analyze_realized_performance_account_aggregated(
            positions=positions,
            user_email=user_email,
            benchmark_ticker=benchmark_ticker,
            source=source,
            institution=institution,
            include_series=include_series,
            backfill_path=backfill_path,
            price_registry=price_registry,
        )

    return _analyze_realized_performance_single_scope(...)
```

### B. New account-aggregated execution helper

```python
def _analyze_realized_performance_account_aggregated(...):
    account_ids = _discover_schwab_account_ids(...)

    if len(account_ids) <= 1:
        # back-compat fast path
        single_account = account_ids[0] if len(account_ids) == 1 else None
        return _analyze_realized_performance_single_scope(..., account=single_account)

    per_account_results = {}
    for acct in account_ids:
        child = _analyze_realized_performance_single_scope(
            ...,
            account=acct,
            include_series=False,
            _disable_account_aggregation=True,
        )
        per_account_results[acct] = _to_analysis_dict(child)

    agg_nav, agg_net, agg_tw = _sum_account_monthly_series(per_account_results)
    agg_monthly_returns, agg_return_warnings = compute_monthly_returns(
        monthly_nav=agg_nav,
        net_flows=agg_net,
        time_weighted_flows=agg_tw,
    )

    # recompute benchmark alignment and top-level metrics with compute_performance_metrics
    # then build realized_metadata by additive/union composition + account_aggregation block
    return _build_aggregated_result_dict(...)
```

### C. Add weighted flow series to `_postfilter` (required for mathematically correct aggregation)

At `core/realized_performance_analysis.py:4616-4651`, add:

```python
"time_weighted_flows": {
    ts.date().isoformat(): float(val)
    for ts, val in tw_flows.items()
},
```

Without this, account-level aggregation cannot apply exact Modified Dietz math.

### D. Cache-key version bump

In `services/portfolio_service.py:652-656`, add a version token (e.g. `realized_v2_account_agg`) in `cache_key`.

## 3) Account ID flow trace (where IDs exist vs where dropped)

### Where account IDs are available

1. Schwab transaction ingestion
- `providers/schwab_transactions.py:268-270` adds `_account_hash`, `_account_number`, `_institution`
- `providers/schwab_transactions.py:280-286` writes account metadata in fetch metadata

2. Schwab position ingestion
- `providers/schwab_positions.py:108-111` writes `account_id/account_name` on cash rows
- `providers/schwab_positions.py:140-143` writes `account_id/account_name` on security rows

3. Fetch routing preserves provider payload + metadata
- `trading_analysis/data_fetcher.py:848-908` returns transaction payload and `fetch_metadata` without dropping account fields

4. Schwab normalizer -> FIFO + income
- `providers/normalizers/schwab.py:662-663` reads `_account_hash`/`_account_number`
- FIFO rows carry account fields at `781-783` and `910-912`
- Income rows carry account fields at `702-703` and `815-816`

5. Provider flow extraction
- `providers/flows/schwab.py:195-197` puts `account_id`, `account_name`, `provider_account_ref` on each flow event

6. Core pipeline keeps account-aware filtering available
- account match helper: `core/realized_performance_analysis.py:599-607`
- transaction account filter: `2982-2990`
- income account filter: `3043-3048`
- provider-flow account filter: `3075-3085`
- provider authority checks use account IDs: `3098-3105`

### Where account IDs are dropped

1. Current holdings collapse by ticker
- `_build_current_positions` merges rows by ticker only at `535-543`, stores single `current_positions[ticker]` at `559-566`

2. Position timeline key omits account dimension
- `build_position_timeline` key type is `(symbol, currency, direction)` at `1096`
- key assignment at `1164-1170`

3. Cash replay events are portfolio-global
- `derive_cash_and_external_flows` event objects at `1542-1551` omit account fields
- provider-flow replay event object at `1589-1595` also omits account fields

4. NAV valuation remains account-collapsed
- `compute_monthly_nav` consumes `(symbol, currency, direction)` keys (`1752`, `1804-1808`)

## 4) Aggregation math (combined Modified Dietz)

For each account `a` and month `t`, from per-account `_postfilter`:
- `V_{a,t}` = monthly NAV
- `F_{a,t}` = monthly net external flow
- `W_{a,t}` = monthly time-weighted external flow

Aggregate monthly series:
- `V_t = Σ_a V_{a,t}`
- `F_t = Σ_a F_{a,t}`
- `W_t = Σ_a W_{a,t}`

Then compute combined monthly return `r_t` using the **same** `compute_monthly_returns(...)` logic (`1845-1890`):

- If `|V_{t-1}| < eps`:
  - denominator = `F_t`
  - if denominator `<= 0`, set `r_t = 0`
  - else `r_t = (V_t - F_t) / F_t`

- Else:
  - denominator = `V_{t-1} + W_t`
  - if denominator `<= 0`, set `r_t = 0`
  - else `r_t = (V_t - V_{t-1} - F_t) / (V_{t-1} + W_t)`

Total return remains chain-linked:
- `R_total = Π_t (1 + r_t) - 1`

Important: Do **not** average per-account returns. Aggregate NAV/flows first, then compute return.

## 5) Edge cases

1. Same symbol in multiple accounts
- Solved by per-account execution: symbol overlap never co-mingles before NAV/flow construction.

2. Provider flows spanning accounts
- Per-account filter (`3075-3085`) isolates account legs.
- Internal transfers (`is_external_flow=False`) should net correctly when account series are summed.
- If any Schwab rows lack account identity, do not silently drop them: log warning and fallback to legacy single-scope path for that request.

3. Institutions with only one account (e.g., IBKR)
- Aggregation gate should only run for Schwab + no explicit account + more than one discovered account.
- Single-account or non-Schwab institutions stay on existing path unchanged.

4. Missing months across accounts
- Reindex on union month-end index.
- NAV: `ffill().fillna(0.0)` per account before summation.
- Flows: `fillna(0.0)` before summation.

## 6) Entry point and control flow

Recommended location of per-account loop: **core analyzer** (`analyze_realized_performance`), not MCP.

Current call chain:
- `mcp_tools/performance.py:766-777` -> `_run_realized_with_service`
- `mcp_tools/performance.py:365-393` -> `PortfolioService.analyze_realized_performance`
- `services/portfolio_service.py:666-675` -> `core.analyze_realized_performance`

Proposed chain:
- same until core entry
- core wrapper decides:
  - Schwab multi-account: run per-account subcalls + aggregate
  - otherwise: existing single-scope logic

Why here:
- one fix point for all callers (MCP/API/tests/service)
- avoids divergent behavior between entry points
- keeps external API contract stable

## 7) Backward compatibility plan

1. Keep existing single-account behavior as default path.
2. Gate new logic strictly:
- no explicit `account`
- Schwab scope (`source == "schwab"` or `institution ~ Schwab`)
- discovered account count > 1
3. Preserve response schema:
- keep current top-level fields and `realized_metadata` shape
- add optional `realized_metadata.account_aggregation` diagnostics block (non-breaking)
4. Add cache key version token in service to prevent stale pre-fix cache reuse.

---

## Fix B: Stop global synthetic backdating (still needed after Fix A)

### Is this still a problem within one account?
Yes.

Even in a single account, global inception can still backdate a symbol with missing opening history far earlier than that symbol’s first observed activity in that account, distorting early NAV/returns.

### Exact code changes

1. `core/realized_performance_analysis.py` in `build_position_timeline(...)`
- Current global backdating for current positions: `1236-1241`
- Current global backdating for incomplete trades: `1279-1284`

2. Replace synthetic date anchors:

```python
# current-position synthetic
symbol_inception = earliest_txn_by_symbol.get(ticker, inception_date)
synthetic_date = symbol_inception - timedelta(seconds=1)

# incomplete-trade synthetic
symbol_anchor = earliest_txn_by_symbol.get(symbol)
if symbol_anchor is not None:
    synthetic_date = min(symbol_anchor, sell_date) - timedelta(seconds=1)
else:
    synthetic_date = sell_date - timedelta(seconds=1)
```

3. Keep futures incomplete-trade filter logic (`1303-1314`) unchanged.

### Test updates for Fix B

Update tests that currently assert global-inception behavior:
- `tests/core/test_realized_performance_analysis.py:318-358`
- `tests/core/test_realized_performance_analysis.py:5598-5670`

Expected new behavior:
- synthetic current-position entries are anchored to symbol-level earliest observed date (fallback as above), not always global inception.
- incomplete-trade synthetic entries are no longer globally backdated.

---

## Recommended implementation order

1. Add weighted-flow series to `_postfilter` (`4616-4651`).
2. Extract single-scope analyzer helper from current `analyze_realized_performance` body.
3. Add Schwab account-aggregation wrapper + aggregation builder.
4. Apply Fix B synthetic-date anchor changes.
5. Add/adjust tests, then regression-check Schwab 165/013/252 and IBKR single-account paths.
