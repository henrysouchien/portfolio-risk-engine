# Unify Income Pipeline in Realized Performance Engine

## Context
The realized performance engine has two independent income pipelines producing overlapping data for the output `income` dict:

1. **`_summarize_income_usd(income_with_currency, fx_cache)`** in `backfill.py:323` — iterates the filtered `income_with_currency` list, converts to USD via FX, produces `total`, `dividends`, `interest`, `by_institution`, `current_monthly_rate`, `projected_annual`. Already computes `by_month_usd` internally (line 328) but doesn't return it.

2. **`analyzer.analyze_income()`** in `trading_analysis/analyzer.py:819` — iterates the **unfiltered** `analyzer.income_events`, produces `by_month`, `by_symbol`. No FX conversion.

This causes two bugs:
- **Filter leak**: `by_month`/`by_symbol` bypass institution, account, AND segment filters (equity dividends appear in futures segment output)
- **Currency inconsistency**: `total`/`dividends`/`interest` are USD-converted, but `by_month`/`by_symbol` are in raw original currencies — they don't sum correctly for foreign-currency income

A temporary hack was added (mutate `analyzer.income_events` before calling `analyze_income()`, then restore) — fragile and not thread-safe.

## Approach
Extend `_summarize_income_usd` to also return `by_month` and `by_symbol` (both USD-converted), then remove `analyzer.analyze_income()` from the engine entirely. Single pipeline, single source of truth, always filtered, always USD.

## Files to Modify

### 1. `core/realized_performance/backfill.py` — `_summarize_income_usd()`
- Add `by_symbol_usd: Dict[str, float] = defaultdict(float)` accumulator alongside existing `by_month_usd` (line 328)
- Inside the existing loop (line 333), derive symbol: `symbol = str(event.get("symbol") or "").strip() or "UNKNOWN"` (handles whitespace-only → "UNKNOWN"), then `by_symbol_usd[symbol] += amount_usd`
- Add to the returned dict:
  ```python
  "by_month": {k: round(v, 2) for k, v in sorted(by_month_usd.items())},
  "by_symbol": {k: round(v, 2) for k, v in sorted(by_symbol_usd.items())},
  ```
- Note: `by_month_usd` already exists at line 328, just not returned currently

### 2. `core/realized_performance/engine.py` — `_analyze_realized_performance_single_scope()`
- **Remove** the temporary mutation block (~line 2310):
  ```python
  # DELETE:
  if segment != "all" and segment_keep_symbols:
      original_income_events = analyzer.income_events
      analyzer.income_events = [...]
      income_analysis = analyzer.analyze_income()
      analyzer.income_events = original_income_events
  else:
      income_analysis = analyzer.analyze_income()
  ```
- **Replace** references in the output dict (~line 2587-2588):
  - `income_analysis.by_month` → `income_summary_usd.get("by_month", {})`
  - `income_analysis.by_symbol` → `income_summary_usd.get("by_symbol", {})`
- The `income_analysis` variable is no longer needed — remove entirely

### 3. `tests/core/test_realized_performance_segment.py`
- Update `_fake_summarize_income_usd` helper to also compute and return `"by_month"` and `"by_symbol"` keys from the input rows
- Simplify `test_segment_income_analysis_by_symbol_filtered` — no longer needs FakeAnalyzerWithIncome or income event mutation capture. Instead verify that `income.by_symbol` in the result only contains segment-matching symbols (now guaranteed by `income_with_currency` filtering → `_summarize_income_usd`)

### 4. `tests/core/test_realized_performance_analysis.py`
- Check for any `_fake_summarize_income_usd` stubs — add `by_month`/`by_symbol` keys if missing
- In the existing GBP foreign-currency income test (~line 2341), add assertions that `income.by_month` and `income.by_symbol` are USD-denominated and approximately reconcile to `income.total` (regression test for the currency-consistency bug)

## What NOT to Change
- `analyzer.analyze_income()` in `trading_analysis/analyzer.py` — still used by the trading analysis tool independently
- `_income_with_currency()` in `nav.py` — unchanged, still builds the filtered list
- Income filtering logic in engine (institution/account/segment filters on `income_with_currency`) — unchanged, already correct
- No signature changes to any public API

## Verification
1. `pytest tests/core/test_realized_performance_analysis.py -x` — existing tests pass
2. `pytest tests/core/test_realized_performance_segment.py -x` — segment tests pass
3. `pytest tests/mcp_tools/test_performance.py -x` — MCP tests pass
4. Live: `get_performance(mode="realized")` — `income.by_month` and `income.by_symbol` present, USD-denominated, consistent with `income.total`
