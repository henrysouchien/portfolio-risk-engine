# Fix: FX Monitor Currency Labeling + Performance Analysis FX Gap

## Context

Two FX threading gaps identified during post-implementation review of the FX Currency Conversion plan (by GPT and Claude):

1. **Monitor currency mislabeling (High)**: `_calculate_market_values()` converts equity values to USD but keeps original `currency` column. The monitor (`_build_monitor_payload`) groups by `currency` and sums values — so GBP positions show USD values bucketed under "GBP". Misleading for the consumer (Claude/user).

2. **Performance analysis missing FX (Medium)**: `calculate_portfolio_performance_metrics()` doesn't accept `currency_map`, so `get_returns_dataframe()` is called without it. Performance metrics (Sharpe, alpha, drawdown, etc.) are computed on local-currency returns for non-USD tickers.

### Other findings (not addressed here)

| # | Sev | Issue | Status |
|---|-----|-------|--------|
| 3 | Medium | MCP tools drop all cash including margin debt, understating leverage | Separate plan: `CASH_PROXY_MAPPING_PLAN.md` |
| 4 | Low | `get_returns_dataframe()` FMP profile fallback adds API call per ticker when `currency_map` absent | Optimization, not a bug — fallback only triggers for YAML-without-currency-map edge case |
| 5 | Low | Redundant `price_fetcher` construction in `analyze_portfolio()` (dead code for PortfolioData path) | Cosmetic, `portfolio_analysis.py:124-136` |
| 6 | Low | FX pairs in `exchange_mappings.yaml` (e.g. `CADUSD`) need runtime verification for FMP availability | Verify during next live test; graceful fallback to 1.0 already handles this |
| 7 | Low | Double stdout redirect (mcp_server global + per-tool) | Harmless, `mcp_server.py:20` + `mcp_tools/risk.py:136` |

---

## Fix 1: Monitor Currency Labeling

**Problem**: `_calculate_market_values()` converts all position values to USD. Cash positions get `currency="USD"` (to prevent double-FX in the risk pipeline). Equity positions keep their original currency (e.g., `"GBP"`) because the risk pipeline re-prices independently via `latest_price()`. The monitor groups by `currency` and sums values — so GBP equities show USD values bucketed under "GBP".

**Strategy**: Add `original_currency` column to preserve the pre-conversion currency for all positions. The monitor groups by `original_currency` and annotates that all values are USD. The `currency` column remains unchanged (still `"USD"` for cash, original for equity) — no impact on the risk pipeline.

### Step 1.1 — Add `original_currency` column in `_calculate_market_values()` (`services/position_service.py`) ✅

Add one line before the conversion loop (after line 521, before line 522). Use a conditional to avoid stomping any pre-existing column from upstream or cached data:
```python
if "original_currency" not in df.columns:
    df["original_currency"] = df.get("currency", "USD")
```

This preserves the pre-conversion currency for all positions. The existing behavior stays unchanged:
- Cash path (`line 528-536`): `currency` set to `"USD"` (prevents double-FX in risk pipeline via `to_portfolio_data()`). `original_currency` retains the original (e.g., `"CAD"`).
- Equity path (`line 538-556`): `currency` stays as original (risk pipeline re-prices independently via `latest_price()`). `original_currency` = `currency` for equities.

### Step 1.2 — Add `original_currency` to `_ensure_cached_columns()` (`services/position_service.py`) ✅

Cached positions that predate this change won't have `original_currency`. Add a fallback:
```python
if "original_currency" not in df.columns:
    df["original_currency"] = df.get("currency", "USD")
```

Add after the existing `currency` column check (around line 567 area, where other column defaults are set).

### Step 1.3 — Update monitor grouping in `_build_monitor_payload()` (`core/result_objects.py`) ✅

**Line 615**: Change grouping key from `currency` to `original_currency`:
```python
currency = position.get("original_currency") or position.get("currency")
```

This ensures:
- GBP equities group under `"GBP"` (from `original_currency`)
- USD positions group under `"USD"` (unchanged)

**Note on cash**: `_build_monitor_payload()` explicitly excludes cash positions from the monitor view (`line 604-605`). Cash is separated into `cash_positions` and not included in `monitor_positions`. So the `original_currency` change only affects equity/non-cash positions in the monitor grouping. Cash is reported separately in `"cash_positions_excluded"` count.

**Lines 755-768**: Add `values_currency` to the top-level payload (not just summary) so it's unambiguous at every level:
```python
payload = {
    "status": "success",
    "module": "positions",
    "view": "monitor",
    "values_currency": "USD",  # NEW — all monetary values are USD-converted
    "timestamp": timestamp,
    "summary": {
        "by_currency": summary_by_currency,
        ...
    },
    ...
}
```

Placing `values_currency` at the top level (not nested inside `summary`) makes it clear that ALL monetary values throughout the payload — both summary-level and per-position — are in USD. This tells the consumer (Claude) that values in `by_currency` are USD-denominated regardless of grouping key, and that per-position `price`, `value`, `net_exposure` etc. are also USD. For example:
```json
{
  "values_currency": "USD",
  "summary": {
    "by_currency": {
      "GBP": {"net_exposure": 1565.0, ...},
      "USD": {"net_exposure": 50000.0, ...}
    }
  }
}
```
Claude interprets: "Your GBP-denominated positions have $1,565 USD exposure; your USD positions have $50,000 exposure."

---

## Fix 2: Performance Analysis FX Threading

**Problem**: `calculate_portfolio_performance_metrics()` doesn't accept `currency_map`, so its internal call to `get_returns_dataframe()` at line 1334 passes no currency information. Non-USD ticker returns (e.g., AT in GBP) are NOT FX-adjusted. All performance metrics (Sharpe, Sortino, alpha, beta, max drawdown, etc.) are computed on local-currency returns — inconsistent with how `analyze_portfolio()` handles FX.

**Fix**: Add `currency_map` parameter to `calculate_portfolio_performance_metrics()` and pass it through to `get_returns_dataframe()`. Thread from `analyze_performance()`.

### Step 2.1 — Add `currency_map` to `calculate_portfolio_performance_metrics()` (`portfolio_risk.py`) ✅

**Line 1274**: Add parameter:
```python
def calculate_portfolio_performance_metrics(
    weights: Dict[str, float],
    start_date: str,
    end_date: str,
    benchmark_ticker: str = "SPY",
    risk_free_rate: float = None,
    total_value: Optional[float] = None,
    fmp_ticker_map: Optional[Dict[str, str]] = None,
    currency_map: Optional[Dict[str, str]] = None,  # NEW
) -> Dict[str, Any]:
```

**Line 1334**: Pass to `get_returns_dataframe()`:
```python
df_ret = get_returns_dataframe(
    filtered_weights, start_date, end_date,
    fmp_ticker_map=fmp_ticker_map,
    currency_map=currency_map,
)
```

Backward-compatible: `currency_map` defaults to `None`, all existing callers continue to work.

### Step 2.2 — Pass `currency_map` from `analyze_performance()` (`core/performance_analysis.py`) ✅

**Lines 102-109**: Add `currency_map` to the call:
```python
performance_metrics = calculate_portfolio_performance_metrics(
    weights=weights,
    start_date=config["start_date"],
    end_date=config["end_date"],
    benchmark_ticker=benchmark_ticker,
    total_value=total_value,
    fmp_ticker_map=fmp_ticker_map,
    currency_map=currency_map,  # NEW
)
```

`currency_map` is already extracted from `config` at line 80 — no new extraction needed.

---

## Files Modified

| File | Fix | Changes | Status |
|------|-----|---------|--------|
| `services/position_service.py` | 1 | Add `original_currency` column in `_calculate_market_values()`, add to `_ensure_cached_columns()` | ✅ |
| `core/result_objects.py` | 1 | Group by `original_currency` in `_build_monitor_payload()`, add `values_currency: "USD"` to top-level payload | ✅ |
| `portfolio_risk.py` | 2 | Add `currency_map` param to `calculate_portfolio_performance_metrics()`, pass to `get_returns_dataframe()` | ✅ |
| `core/performance_analysis.py` | 2 | Pass `currency_map` to `calculate_portfolio_performance_metrics()` | ✅ |

## Edge Cases

- **Cached positions without `original_currency`**: `_ensure_cached_columns()` backfills from `currency`. Since old cached positions have `currency` intact (only `_calculate_market_values()` overwrites it, and that hasn't run yet for stale caches), the backfill is correct.
- **Pre-existing `original_currency` column**: Both `_calculate_market_values()` and `_ensure_cached_columns()` use `if "original_currency" not in df.columns` guard — upstream-supplied values are never overwritten.
- **Live (non-cached) positions**: Positions from live brokerage fetch don't go through `_calculate_market_values()`. Their `currency` is the original currency from the provider. If `original_currency` column doesn't exist, the monitor fallback `position.get("original_currency") or position.get("currency")` handles this correctly.
- **Cash in monitor**: Cash positions are excluded from the monitor view by `_build_monitor_payload()` (line 604-605). The `original_currency` column exists on cash positions but is not used by the monitor — it only affects the equity/non-cash grouping.
- **USD-only portfolios**: `original_currency` = `"USD"` for all positions. Monitor groups under `"USD"`. No regression.
- **Risk pipeline**: The `currency` column is unchanged for equities. `to_portfolio_data()` reads `currency` to build `currency_map` — unaffected. Cash `currency` stays `"USD"` — no double-FX.
- **Performance analysis backward compatibility**: `currency_map=None` default means all callers outside `analyze_performance()` (e.g., any direct calls to `calculate_portfolio_performance_metrics()`) continue to work without changes.

## Verification

1. ✅ **Monitor**: `python3 tests/utils/show_api_output.py monitor` — AT groups under "GBP" with USD value $1,718.97, `values_currency: "USD"` at top level
2. ✅ **Performance**: `python3 tests/utils/show_api_output.py performance` — runs clean, non-USD returns FX-adjusted
3. ✅ **Risk pipeline**: `python3 tests/utils/show_api_output.py analyze` — no regression, no double-FX
4. ✅ **MCP tools**: Restart Claude Code, test `get_risk_analysis()` — no regression

## Review Fixes Applied

| # | Source | Severity | Finding | Resolution |
|---|--------|----------|---------|------------|
| 1 | Codex | P2 | `_build_monitor_payload` excludes cash — plan incorrectly claimed cash would show under original currency | Updated plan: cash is excluded from monitor; `original_currency` only affects equity grouping. Removed incorrect verification claim. |
| 2 | Codex | P2 | `original_currency` set unconditionally could stomp pre-existing column | Changed to `if "original_currency" not in df.columns` guard in both `_calculate_market_values()` and `_ensure_cached_columns()` |
| 3 | Codex | P3 | `values_currency: "USD"` only in summary — per-position values also USD but unlabeled | Moved `values_currency` to top-level payload (covers both summary and per-position values) |

---

*Document created: 2026-02-06*
*Updated: 2026-02-06 — 3 review fixes from Codex*
*Status: ✅ Complete — All changes implemented and fully verified (uncommitted).*
