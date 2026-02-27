# Plan: Fix Realized Performance P&L / Return Discrepancy

## Context

`get_performance(mode="realized")` shows +90.5% total return but -$33k dollar P&L. Root causes: missing transaction history (71% coverage), IBKR ticker mismatches creating incomplete trades, and a month-1 return formula bug. Following Codex's recommended order: fix data first, then math, then presentation.

---

## Step 1: Normalize IBKR Flex Symbols at Provider Ingestion (quickest win)

**Problem:** IBKR Flex reports `AT.` but positions show `AT.L`. The FIFO matcher can't match exits to entries because the tuple keys differ.

**Fix:** Normalize symbols at the **provider ingestion layer** in `services/ibkr_flex_client.py` (lines 153-176), after extracting the symbol. **Only apply to equities** — skip options and futures, which have their own symbol conventions handled by existing paths at lines 150 and 166.

- `resolve_fmp_ticker()` already exists in `utils/ticker_resolver.py:173-274`
- `exchange_mappings.yaml` already maps `XLON → ".L"`, `XPAR → ".PA"`, etc.
- IBKR Flex trades include an `exchange` field — extract it and map to MIC code
- **Do NOT apply `fmp_ticker_map` in `build_position_timeline()`** — `fmp_ticker_map` is currently `del`'d at line 173 and should stay that way. Normalization belongs at the provider ingestion layer so all downstream code (FIFO, timeline, price cache) sees consistent symbols. The price-fetch layer already handles FMP symbol resolution internally via `fetch_monthly_close()` → `select_fmp_symbol()`.

**Critical: trailing-dot handling.** IBKR stores some symbols with a trailing dot (e.g., `AT.` for Ashtead Group). Before applying any suffix, **strip the trailing dot** from the base symbol. Without this, `resolve_fmp_ticker()` would produce `AT..L` (double-dot) because it checks `ticker.endswith(suffix)` at line 215 — `"AT."` doesn't end with `".L"`, so it appends, giving `"AT..L"`. The fix:
```python
# In ibkr_flex_client.py, after extracting symbol:
base_symbol = symbol.rstrip(".")  # "AT." → "AT"
# Then apply suffix: "AT" + ".L" → "AT.L"
```

**Scope guard:** Only apply exchange-suffix normalization when:
1. The trade's `assetCategory == "STK"` (IBKR's code for stocks/equities). Use a **whitelist approach** — only `"STK"` triggers normalization. All other categories (`"OPT"`, `"FUT"`, `"CASH"`, `"WAR"`, `"BOND"`, etc.) are left unchanged. This avoids accidental normalization of non-equity instruments.
2. The IBKR exchange code maps to a known MIC in `ibkr_exchange_to_mic`
3. The symbol doesn't already have a recognized suffix (use the `endswith` check already in `resolve_fmp_ticker`)
If any condition fails, leave the symbol unchanged.

**IBKR exchange code mapping strategy:** Add an `ibkr_exchange_to_mic` section to `exchange_mappings.yaml`. IBKR uses non-standard exchange codes (e.g., `LSEETF` for London ETFs, `AEB` for Amsterdam). The mapping should cover known IBKR exchange codes encountered in our Flex reports. Start with the codes present in current data, expand as needed. Use the IBKR `exchange` field from trade objects, not `listingExchange`.

**Files to modify:**
- `services/ibkr_flex_client.py` — add trailing-dot stripping + suffix resolution after symbol extraction, guarded to equities only
- `exchange_mappings.yaml` — add `ibkr_exchange_to_mic` mapping section

**Pre-step:** Before implementing, run this diagnostic to build the exchange mapping. `fetch_ibkr_flex_trades()` returns normalized dicts that don't include raw `exchange` or `assetCategory`. To get these fields, **temporarily add passthrough fields** to `normalize_flex_trades()` in `services/ibkr_flex_client.py` during development:
```python
# Temporary addition to each normalized trade dict in normalize_flex_trades():
normalized['_raw_exchange'] = str(_get_attr(trade, "exchange", default=""))
normalized['_raw_asset_category'] = str(_get_attr(trade, "assetCategory", default=""))
```
Then run:
```python
from services.ibkr_flex_client import fetch_ibkr_flex_trades
trades = fetch_ibkr_flex_trades()
exchanges = set((t.get('_raw_exchange', ''), t.get('symbol', ''), t.get('_raw_asset_category', '')) for t in trades)
for exch, sym, cat in sorted(exchanges):
    print(f"{exch:15s} {sym:15s} {cat}")
```
Remove the temporary passthrough fields before merging. Use the output to populate the `ibkr_exchange_to_mic` section in `exchange_mappings.yaml`.

**Cross-provider dedup safety:** After IBKR symbols are normalized, IBKR's `AT.L` will now match positions/Plaid's `AT.L`. Plaid transactions for IBKR institutions are already filtered by `should_skip_plaid_institution()` in `data_fetcher.py:16-44`, so no new cross-provider duplicates are introduced. Add a regression test confirming that an IBKR-normalized symbol + Plaid-filtered institution doesn't produce duplicate transactions in the combined `fifo_transactions` list.

**Verification:** Run the FIFO matcher and confirm `AT.` becomes `AT.L` (not `AT..L`), incomplete trades for `AT.` drop to zero. Also verify that options/futures symbols are unchanged.

---

## Step 2: Export & Backfill Incomplete Trades

**Problem:** 18 incomplete trades (sells with no matching buy) corrupt the realized P&L.

**Fix:** Use the existing backfill pipeline, but integrate it properly into the position timeline and cash-flow reconstruction (not just closed_trades):

1. Run `export_incomplete_trades_for_backfill(result.incomplete_trades, path)` to generate JSON
2. For trades that are genuinely missing history (NMM, SE, VBNK, CUBI, etc.) — user fills in `manual_entry_price` and `manual_entry_date` from broker statements
3. For trades fixed by symbol normalization (AT.) — these should auto-resolve after Step 1, no backfill needed
4. **Inject backfilled entries as BUY (for LONG) or SHORT (for SHORT direction) transactions into `fifo_transactions` BEFORE inception date derivation AND FIFO matching.** Current code computes `inception_date` at `core/realized_performance_analysis.py:725-730` from the earliest transaction, then builds the month range at line 764. If backfill entries have earlier `manual_entry_date` than existing transactions, they must be present before inception-date is computed — otherwise the analysis window excludes their early history, distorting monthly returns and CAGR. **Injection point: immediately after `fifo_transactions` is built (after `TradingAnalyzer` normalization) but before `inception_date` derivation.** This is critical — injection must happen upstream of both inception-date and the matcher so that:
   - FIFO matcher can pair the backfilled entry (BUY for LONG, SHORT for short-direction) with the existing exit → produces correct closed trades
   - Incomplete trade count drops naturally
   - Position timeline includes the entry event
   - Cash-flow logic accounts for the original purchase
   - Coverage metric improves (scans `fifo_transactions` for opening keys)
5. **Do NOT also call `load_and_merge_backfill()`** — that would double-count. Choose one path only: inject into `fifo_transactions` before matching. The existing `load_and_merge_backfill()` function is not used.
6. Add a `backfill_path` parameter to `analyze_realized_performance()`, threaded through `PortfolioService.analyze_realized_performance()` (`services/portfolio_service.py:609`) and MCP wrapper (`mcp_tools/performance.py:322`). Default: auto-discover from `settings.py` config key `BACKFILL_FILE_PATH`.
7. Handle missing backfill file gracefully (skip, don't hard-fail)

**Idempotency (critical):** Backfill injection MUST be idempotent — repeated runs with the same backfill file must not produce duplicates:
- Assign **deterministic `transaction_id`** to each backfill entry, **namespaced by source** to avoid cross-provider collision: `backfill_{source}_entry_for_{exit_transaction_id}` (e.g., `backfill_ibkr_flex_entry_for_12345`). Provider IDs are not globally unique (Plaid/SnapTrade use different ID schemes than IBKR), so the `source` prefix is required. Note: same-source ID collisions are theoretically possible in multi-account scenarios but are extremely unlikely given that exit `transaction_id` is provider-assigned and unique per execution row. If the exit `transaction_id` is missing, fall back to `backfill_{source}_{symbol}_{date}_{direction}_{qty}_{price}_{seq}` where `{seq}` is a 0-based index within the backfill file for entries sharing the same tuple. This disambiguates identical same-day fills.
- **Transaction ID dedup:** Before prepending backfill entries to `fifo_transactions`, collect all existing `transaction_id` values into a set. Skip any backfill entry whose `transaction_id` already exists. This prevents exact duplicate injection.
- **Provider-overlap is handled manually, not automatically.** Automatic overlap detection (quantity pools, date windows, etc.) is fragile and prone to false positives that suppress valid backfills. Instead, after FIFO matching, emit **two diagnostic warnings** to catch overlap from either direction:
  1. **Stale backfill warning:** Scan `open_lots` (from FIFO result) for any lot whose `transaction_id` starts with `backfill_`. If found, it means the backfill entry wasn't matched to any exit — likely because a provider-sourced entry was matched to the exit first (FIFO is date-ordered, so an older provider entry gets priority). Warn: "Backfill entry for {symbol} is unmatched open lot — provider may have supplied the original entry. Remove from backfill file."
  2. **Redundant backfill warning:** If a backfill entry was successfully paired (appears in `closed_trades` as `entry_transaction_id`) AND there are also provider-sourced **open lots** for the same symbol/direction **with entry dates within ±3 days of the backfill entry date**, warn about possible redundancy. The date constraint prevents false positives from normal later-cycle open lots that are unrelated to the backfill.
  3. **Wide-window duplicate hint (non-blocking):** As a secondary diagnostic, scan for provider-sourced entries matching `(symbol, direction, quantity ±5%, price ±10%)` over a **±14 calendar day** window. If found, emit a lower-severity info-level hint (not a warning): "Possible duplicate: backfill {symbol} matches provider entry on {date}. Verify and remove backfill if redundant." This catches cases where settlement date variance or provider lag pushes the native entry outside the ±3 day warning window.
  The user is responsible for removing backfill entries when providers catch up. This is safe because all three diagnostics surface overlap, and the reconciliation gap makes any double-counting visible.
- **Source tagging:** Each backfill entry must include a `source` field matching the original provider (e.g., `"ibkr_flex"`, `"snaptrade"`). This is already in the exported JSON (`fifo_matcher.py:953`). When the analysis runs with a `source` filter (e.g., `source="plaid"`), only inject backfill entries whose `source` matches the filter. This prevents cross-source contamination.
- The `fifo_transactions` list is rebuilt fresh each run by `TradingAnalyzer._normalize_data()` (line 372), so backfill entries won't accumulate from previous runs.

**Backfill scope:** The backfill JSON file is **global** (not per user_email or portfolio). This is a single-user system with one portfolio. If multi-user support is added later, the backfill path config should be parameterized per portfolio, but that's out of scope for now.

**Entry fees:** The backfill JSON export contains a `fee` field which is the **exit leg's fee** (from `fifo_matcher.py:952`). When creating the synthetic entry transaction (BUY/SHORT), use a **separate `manual_entry_fee` field** in the backfill JSON (default `0.0`). Do NOT copy the exit `fee` to the entry transaction — that would double-charge the exit fee. The injected entry transaction dict should set `'fee': backfill_entry.get('manual_entry_fee', 0.0)` (matching the transaction dict key at `fifo_matcher.py:414`, with safe default for backward compatibility with existing backfill files that lack this field). The FIFO matcher reads `txn.get('fee', 0)` and assigns it to `entry_fee` for BUY or `exit_fee` for SELL. `ClosedTrade` stores fees as `entry_fee` and `exit_fee` (not `fees`). Also update `export_incomplete_trades_for_backfill()` to include `manual_entry_fee: null` in the template (alongside existing `manual_entry_price: null` and `manual_entry_date: null`).

**Files to modify:**
- `core/realized_performance_analysis.py` — load backfill JSON, convert to entry transactions (BUY for LONG, SHORT for short-direction), assign deterministic `transaction_id`, dedup against existing `fifo_transactions`, prepend before FIFO matching (line ~737)
- `services/portfolio_service.py` — thread `backfill_path` through service call (line 609, 652); update cache key at line 640 to include `backfill_path` + deterministic freshness token (file mtime + size) so stale cached results don't ignore backfill changes
- `mcp_tools/performance.py` — thread `backfill_path` through MCP wrapper (line 322)
- `settings.py` — add `BACKFILL_FILE_PATH` config key
- Create/update backfill JSON file in `user_data/`

**Existing functions for reference (export only, not used for import in this flow):**
- `fifo_matcher.py:export_incomplete_trades_for_backfill()` (line 926) — used to generate the initial JSON template

**Verification:** Run backfill summary — `filled` count should increase, `incomplete_trades` should drop, `data_coverage` should improve. Run twice to confirm idempotency (same result both times).

---

## Step 3: Fix Month-1 Return Formula

**Problem:** When `v_start = 0` (first month), denominator uses `flow_weighted` instead of `flow_net`, inflating returns when capital arrives late in the month.

**Fix:** One-line change in `core/realized_performance_analysis.py` line 554:

```python
# BEFORE:
denom = flow_weighted if flow_weighted > 0 else flow_net

# AFTER:
denom = flow_net
```

**Edge cases handled:**
- `flow_net = 0`: already returns 0.0 with warning (no change)
- `flow_net < 0`: returns 0.0 with warning (same guard exists)
- Subsequent months: unchanged (uses standard Modified Dietz with `v_start + flow_weighted`)

**Tests to add** in `tests/core/test_realized_performance_analysis.py`:
- Test where `flow_weighted ≠ flow_net` in month 1 (e.g., late-month flow where flow_weighted ≈ 3.23 but flow_net = 100)
- Verify month-1 return uses `flow_net` as denominator
- Existing test (`test_compute_monthly_returns_handles_vstart_zero_and_standard_month`) masks the bug because `flow_weighted == flow_net`

**Verification:** Re-run realized performance — total return % should decrease from the inflated 90.5%.

---

## Step 4: Fix FX Normalization in Lot P&L and Exposed Fields

**Problem:** `lot_pnl_usd` aggregation is inconsistent: `realized_pnl` sums `ClosedTrade.pnl_dollars` without FX conversion (`core/realized_performance_analysis.py:1050`), income is also unconverted (`core/realized_performance_analysis.py:1077`), but unrealized P&L is FX-converted (`core/realized_performance_analysis.py:589`). For GBP/EUR trades, reconciliation gap will show false differences.

Additionally, the **individual exposed fields** (`realized_pnl`, `unrealized_pnl`, `income_total`) in the result dict are mixed-currency — they sum local-currency values across positions. These fields are surfaced in MCP output and must also be USD-normalized.

**Fix:** Normalize all P&L components to USD using proper per-leg FX conversion:

**Long positions:**
- `entry_cost_usd = entry_price × quantity × fx_rate(entry_date, currency)`
- `exit_proceeds_usd = exit_price × quantity × fx_rate(exit_date, currency)`
- `realized_pnl_usd = exit_proceeds_usd - entry_cost_usd - entry_fee_usd - exit_fee_usd`
- Where `entry_fee_usd = entry_fee × fx_rate(entry_date, currency)`, `exit_fee_usd = exit_fee × fx_rate(exit_date, currency)`

**Short positions (entry is SHORT, exit is COVER):**
- `entry_proceeds_usd = entry_price × quantity × fx_rate(entry_date, currency)` (received at short open)
- `exit_cost_usd = exit_price × quantity × fx_rate(exit_date, currency)` (paid at cover)
- `realized_pnl_usd = entry_proceeds_usd - exit_cost_usd - entry_fee_usd - exit_fee_usd`

**Income:**
- Convert at income event date FX: `income_usd = income_amount × fx_rate(income_date, currency)`

**General:**
- Use existing `fx_cache` already available in the function
- This matches how unrealized P&L is already handled (`_compute_unrealized_pnl_usd` at line 589)
- **Also update the individual exposed fields** (`realized_pnl`, `unrealized_pnl`, `income_total`) in `realized_metadata` to use USD-converted values. Currently `realized_pnl` at line 1050 and `income_total` at line 1077 sum local-currency amounts. After this fix, all three components and the aggregate `lot_pnl_usd` should be consistently in USD.
- Keep the existing local-currency breakdowns available in per-position detail if needed, but the top-level summary fields must be USD.
- **Income subfields:** Also FX-normalize `income.dividends`, `income.interest`, and `income.projected_annual` (lines 1082, 1109 in `core/realized_performance_analysis.py`). These are surfaced in MCP summary (`mcp_tools/performance.py:367`). Yield fields (`dividend_yield`, `yield_on_cost`, etc.) should be computed from the USD-normalized income and USD-normalized denominators. For `yield_on_cost` denominator: `_build_current_positions()` at line 119-141 currently collapses `cost_basis_usd` and `cost_basis` into a single `cost_basis` field, losing provenance. **Implementation must add a `cost_basis_is_usd: bool` flag** to each entry in `current_positions` during `_build_current_positions()`. Set it to `True` when the upstream position object provided a `cost_basis_usd` field or when `currency == "USD"`. Set it to `False` when only a local-currency `cost_basis` was available. Then at the yield computation point, convert only when `cost_basis_is_usd is False`: `cost_basis_usd = cost_basis * fx_rate(today, currency)`. This provenance-based approach eliminates any ambiguity about whether the value was already USD-normalized upstream.
- USD-denominated positions (the majority) have `fx_rate = 1.0` so the conversion is a no-op.

**Files to modify:**
- `core/realized_performance_analysis.py` — FX-convert realized P&L and income when computing both `lot_pnl_usd` and the individual exposed fields

**Verification:** Check that `lot_pnl_usd` for AT.L (GBP) trades is properly converted to USD. Also verify that `realized_pnl` + `unrealized_pnl` + `income_total` = `lot_pnl_usd` (all in USD).

---

## Step 5: Verify Dual-Track P&L (confirmed fully implemented)

**Status:** Dual-track fields are **fully implemented, surfaced, and tested** in the current codebase:
- **Computation:** `official_pnl_usd` (lines 1071-1075, NAV-flow basis), `lot_pnl_usd` (line 1079, FIFO lot basis), `reconciliation_gap_usd` (line 1080, difference)
- **Metadata:** All three fields packaged in `realized_metadata` with 2-decimal rounding (lines 1100-1102)
- **MCP surface:** Report format (lines 194-196) and API response (lines 373-375) in `mcp_tools/performance.py`
- **Tests:** Assertions at `test_realized_performance_analysis.py:1411-1415` verify all three values, `official_metrics_estimated`, and `pnl_basis`

**Action:** Validation only — no new code needed. After Steps 1-4 fix the underlying data and math, re-run and confirm:
1. Dual-track fields are populated with non-zero values
2. `reconciliation_gap_usd` is reasonable (within a few % of NAV)
3. `official_pnl_usd` sign matches return direction

**No baseline commit concern:** The dual-track implementation is in the main codebase with passing tests, not a dirty-workspace artifact.

---

## Step 6: Add Acceptance Checks with Config

**Fix:** Add configurable validation thresholds to flag unreliable results:

- Add to `settings.py`:
  - `REALIZED_COVERAGE_TARGET = 95.0` (%)
  - `REALIZED_MAX_INCOMPLETE_TRADES = 0`
  - `REALIZED_MAX_RECONCILIATION_GAP_PCT = 2.0` (% of NAV, denominator = `max(abs(nav_end), 1000.0)` to avoid instability when NAV is near zero)
- Compute `high_confidence_realized: bool` based on **all five checks**:
  1. Coverage ≥ target
  2. Incomplete trades ≤ max
  3. Reconciliation gap ≤ max %
  4. `official_metrics_estimated` is `False` (existing flag at `core/realized_performance_analysis.py:1090-1094` — set when synthetics exist)
  5. No high-severity unpriceable warnings (existing flags at `core/realized_performance_analysis.py:818-834`)
- If any check fails, `high_confidence_realized = False`
- Emit specific gating reasons in existing `data_warnings` list (not a new field — use the existing key at `core/realized_performance_analysis.py:1131`)

**Files to modify:**
- `settings.py` — add threshold config keys
- `core/realized_performance_analysis.py` — add checks after P&L computation
- `mcp_tools/performance.py` — surface `high_confidence_realized` and warnings in report

**Verification:** With current data, `high_confidence_realized` should be `false` with clear reasons.

---

## Execution Order

| Step | Effort | Impact |
|------|--------|--------|
| 1. Symbol normalization | Small (1-2 files) | Fixes AT.L + reduces incomplete trades |
| 2. Backfill pipeline | Medium (integration + manual data entry) | Fixes remaining incomplete trades + improves coverage |
| 3. Month-1 formula | Small (1 line + tests) | Fixes inflated return % |
| 4. FX normalization | Small-Medium (1 file) | Fixes false reconciliation gaps for non-USD trades |
| 5. Dual-track verification | Small (validation only) | Confirms existing implementation works |
| 6. Acceptance checks | Small (2-3 files) | Gates confidence on results |

## Key Files

| File | Changes |
|------|---------|
| `services/ibkr_flex_client.py` | Step 1: symbol suffix resolution |
| `exchange_mappings.yaml` | Step 1: possibly add IBKR exchange → MIC mapping |
| `utils/ticker_resolver.py` | Step 1: reuse `resolve_fmp_ticker()` |
| `core/realized_performance_analysis.py` | Steps 2-6: backfill injection, month-1 fix, FX normalization, checks |
| `mcp_tools/performance.py` | Step 6: surface confidence flag and warnings |
| `settings.py` | Steps 2, 6: backfill path config, threshold config |
| `tests/core/test_realized_performance_analysis.py` | Steps 2-6: backfill injection, month-1, FX, gating tests |

## Verification

After all steps:
1. Run `get_performance(mode="realized", format="report")` — return % should be lower and more realistic
2. Check `data_coverage` — should improve above 70.83%
3. Check `incomplete_trades` count — should be near zero (from 18)
4. `official_pnl_usd` sign should match return direction
5. `reconciliation_gap_usd` should be small and not inflated by FX gaps
6. `high_confidence_realized` should reflect actual data quality
7. `realized_pnl` + `unrealized_pnl` + `income_total` = `lot_pnl_usd` (all in USD)
8. Run realized performance TWICE with same backfill to confirm idempotency (same result both times)
9. Run existing tests + new tests:
   - **Step 1 — Symbol normalization** (in `tests/services/test_ibkr_flex_client.py`):
     - Trailing-dot symbol: `AT.` + LSEETF exchange → `AT.L` (not `AT..L`)
     - Already-suffixed symbol: `AT.L` + LSEETF → `AT.L` (no change)
     - Unknown exchange code: symbol unchanged
     - Option/future trade: symbol unchanged (scope guard)
     - US equity: no suffix appended
     - **No `_raw_*` keys in production output:** assert that normalized trade dicts contain no keys starting with `_raw_` (guards against leftover debug passthrough fields from pre-step diagnostic)
   - **Step 2 — Backfill injection** (in `tests/core/test_realized_performance_analysis.py`):
     - LONG direction: backfill entry is BUY type
     - SHORT direction: backfill entry is SHORT type
     - Idempotency: inject same backfill twice, verify no duplicates in FIFO output
     - No double-counting: inject-only path, `load_and_merge_backfill()` not called
     - Missing backfill file: graceful skip, no error
   - **Step 2 — Cache invalidation** (in `tests/services/test_portfolio_service.py`):
     - Changing backfill file produces new cache key (different mtime/size)
     - Same backfill file hits cache
   - **Step 3 — Month-1 formula**: `flow_weighted ≠ flow_net` regression
   - **Step 4 — FX conversion**: per-leg entry/exit FX for GBP closed trade (long and short); verify `realized_pnl` + `unrealized_pnl` + `income_total` = `lot_pnl_usd` (all USD)
   - **Step 6 — Acceptance checks**: `high_confidence_realized` gating with specific warning reasons

## Codex Review History

- **Review 1 (2026-02-13):** 3 HIGH, 4 MED, 1 LOW findings. Key issues: backfill integration doesn't inject into timeline/cash-flow (HIGH), lot P&L not FX-normalized (HIGH), backfill path under-specified (HIGH), dual-track already partially exists (MED). All addressed in revision 2.
- **Review 2 (2026-02-13):** 2 HIGH, 3 MED, 1 LOW findings. Key issues: backfill must inject BEFORE FIFO matching not after (HIGH), double-counting risk if both injection and merge are used (HIGH), FX should convert per-leg not just at exit (MED), backfill_path must thread through service/MCP layers (MED), use existing `data_warnings` key not new field (MED), NAV denominator needs floor (LOW). All addressed in revision 3.
- **Review 3 (2026-02-13):** 1 HIGH, 2 MED. Backfill injection must use SHORT type for short-direction trades (HIGH), cache key must include backfill_path/freshness (MED), test plan too narrow (MED). All addressed in revision 4.
- **Review 4 (2026-02-13):** 2 LOW (wording cleanup). Approved.
- **Independent Reviewer (2026-02-13):** 2 HIGH, 2 MED, 3 open questions. Findings: backfill injection not idempotent (HIGH — addressed: deterministic transaction IDs + dedup guard), dual-track baseline assumption (HIGH — addressed: verified fully implemented with tests), `fmp_ticker_map` wrong layer (MED — addressed: normalize at provider ingestion, leave `fmp_ticker_map` deleted in timeline builder), FX fix incomplete for exposed fields (MED — addressed: Step 4 now covers individual exposed fields). Open questions resolved: backfill scope is global (single-user), entry fees default to 0.0, IBKR exchange mapping via new `ibkr_exchange_to_mic` section in `exchange_mappings.yaml`. All addressed in revision 5.
- **Review 5 (2026-02-13):** 3 HIGH, 3 MED, 1 LOW. `AT.` → `AT..L` double-dot from blind suffix append (HIGH — addressed: strip trailing dot before suffix, added explicit code example), backfill fee field name wrong `fees` vs `fee` (HIGH — addressed: corrected to `fee` singular with field reference), idempotency key collision risk (HIGH — addressed: use exit `transaction_id` as primary key), Step 1 scope can regress options/futures (MED — addressed: scope guard to equities only), FX formulas incomplete for shorts/fees (MED — addressed: explicit long/short/fee formulas), missing Step 1 edge-case tests (MED — addressed: 5 test cases added), pre-step not actionable (LOW — addressed: diagnostic script provided). All addressed in revision 6.
- **Review 6 (2026-02-13):** 2 HIGH, 1 MED. Provider-overlap double counting when provider later supplies missing entry (HIGH — addressed: two-layer dedup with composite key `(symbol, direction, qty, date±1d)` check), backfill fee double-charging exit fee on entry (HIGH — addressed: separate `manual_entry_fee` field, do not copy exit `fee`), cross-provider dedup after IBKR normalization (MED — addressed: `should_skip_plaid_institution()` already filters, add regression test). All addressed in revision 7.
- **Review 7 (2026-02-13):** 1 HIGH, 2 MED. Split fills bypass exact-quantity dedup (HIGH — addressed: aggregate provider quantities within date window, 5% tolerance), diagnostic script uses normalized output missing exchange/assetCategory (MED — addressed: run against raw Flex XML), income subfields and yields remain mixed-currency (MED — addressed: FX-normalize dividends/interest/projected_annual and compute yields from USD values). All addressed in revision 8.
- **Review 8 (2026-02-13):** 2 HIGH, 2 MED. Backfill injection after inception_date leaves analysis window stale (HIGH — addressed: inject before inception-date derivation, explicit insertion point specified), partial provider overlap still injects full backfill (HIGH — addressed: three-tier logic: skip if full overlap, skip+warn if partial, inject if none), diagnostic references non-existent functions (MED — addressed: temporary passthrough fields approach), confidence gating ignores existing quality flags (MED — addressed: include `official_metrics_estimated` and unpriceable warnings in 5-check gating). All addressed in revision 9.
- **Review 9 (2026-02-13):** 1 HIGH, 2 MED. ±1 day window too narrow for settlement date variance (HIGH — addressed: widened to ±3 calendar days), equity-only scope guard ambiguous for non-standard asset categories (MED — addressed: whitelist `assetCategory == "STK"` only), yield `cost_basis` denominator not FX-normalized (MED — addressed: FX-normalize cost basis before computing yields). All addressed in revision 10.
- **Review 10 (2026-02-13):** 1 HIGH, 2 MED. Same provider entry counted against multiple backfill rows (HIGH — addressed: quantity-consuming allocation pool), fallback ID collision for identical same-day fills (MED — addressed: add `{seq}` index suffix), `yield_on_cost` denominator ambiguous when only local cost_basis available (MED — addressed: use `cost_basis_usd` when available, otherwise `cost_basis * fx_rate` from fx_cache). All addressed in revision 11.
- **Review 11 (2026-02-13):** 1 HIGH, 3 MED. Automatic overlap dedup still fragile with false positives (HIGH — **redesigned: removed automatic overlap detection entirely, replaced with manual maintenance + diagnostic warning**), backfill scope conflicts with source filter (MED — addressed: source-tag backfill entries, filter on injection), `manual_entry_fee` missing from export template (MED — addressed: `.get()` default + template update), cost_basis provenance unclear (MED — addressed: check position currency, convert only if non-USD). All addressed in revision 12.
- **Review 12 (2026-02-13):** 1 HIGH, 2 MED. Diagnostic warning is one-sided, misses stale backfill open lots (HIGH — addressed: added two-directional warnings: stale backfill in open_lots + redundant backfill in closed_trades), transaction_id collision across providers (MED — addressed: namespace with source prefix), cost_basis double-conversion risk (MED — addressed: use `cost_basis_usd` as authoritative, fallback only). All addressed in revision 13.
- **Review 13 (2026-02-13):** 0 HIGH, 3 MED. **APPROVED.** Redundant warning too broad (MED — addressed: date constraint ±3d on open lots), same-source ID collision edge case (MED — noted as extremely unlikely, accepted), cost_basis provenance lost at aggregation (MED — addressed: preserve `currency` field, gate FX conversion on it). All addressed in revision 14.
- **Independent Reviewer 2 (2026-02-13):** 0 HIGH, 2 P2, 1 P3. `cost_basis` conversion contradiction between currency-gating and `cost_basis_usd` authoritative (P2 — addressed: explicit `cost_basis_is_usd` provenance flag), manual overlap can miss duplicates outside ±3d (P2 — addressed: added ±14d wide-window info-level hint as secondary diagnostic), `_raw_*` debug fields not enforced absent (P3 — addressed: regression test asserting no `_raw_*` keys in production output). All addressed in revision 15.
- **Final Review (2026-02-13):** **APPROVED — no blocking findings.** Residual risks noted: backfill requires operator discipline (by design), global scope needs refactor for multi-portfolio, wide-window hint thresholds are heuristic and may need tuning after live runs.
