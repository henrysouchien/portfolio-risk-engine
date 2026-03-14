# Thread `instrument_types` Through MCP → Core Analysis Chain

*Created: 2026-02-19 | Status: Completed*

---

## Context

The international futures implementation (commit `5b3bc41c`) added `instrument_types` support to `portfolio_risk.py` (`build_portfolio_view` → cache → `get_returns_dataframe`). However, the MCP tools don't pass `instrument_types` yet — so non-USD futures (HSI, NIY, FESX, Z) won't auto-detect their settlement currency when called via MCP. Users currently need to put explicit entries in `currency_map` as a workaround.

This plan wires `instrument_types` through the full chain: YAML config / live positions → `PortfolioData` → `config_adapters` → `analyze_portfolio()` → `build_portfolio_view()`. It also adds auto-detection from live positions so futures held in IBKR are automatically tagged without manual config.

### Data Flow (current vs proposed)

**Current:** MCP → `to_portfolio_data()` → `PortfolioData(currency_map=...)` → `config_from_portfolio_data()` → `analyze_portfolio()` → `build_portfolio_view(currency_map=..., instrument_types=None)`

**Proposed:** MCP → `to_portfolio_data()` → `PortfolioData(currency_map=..., instrument_types=...)` → `config_from_portfolio_data()` → `analyze_portfolio()` → `build_portfolio_view(currency_map=..., instrument_types=...)`

---

## Changes

### Step 1. Add `instrument_types` field to `PortfolioData` — `core/data_objects.py`

**a) Add field** after `currency_map` (line 661):
```python
instrument_types: Optional[Dict[str, str]] = None
```

**b) Add parameter** to `from_holdings()` (line 884) and pass through to constructor (line 910), mirroring how `currency_map` is already handled.

**c) Add to `_generate_cache_key()`** (line 829) — include `instrument_types` in the cache key dict alongside `currency_map`:
```python
"instrument_types": self.instrument_types,
```

**d) Add to `from_yaml()`** (line 873) — read from YAML config:
```python
instrument_types=config.get("instrument_types"),
```

**e) Add to `to_yaml()`** (line 929) — persist when present:
```python
if self.instrument_types:
    config["instrument_types"] = self.instrument_types
```

### Step 2. Auto-detect futures in `to_portfolio_data()` — `core/data_objects.py`

In `PositionsData.to_portfolio_data()` (after the `currency_map` loop at line 566), add futures auto-detection by cross-referencing tickers against the IBKR futures YAML.

**Codex review fix — Z ticker collision (HIGH #1):** Ticker-only matching would misclassify `Z` (Zillow equity) as FTSE futures. To prevent this, require **both** conditions: ticker is in the YAML **and** the position's `type` is `"derivative"`. Options are also `"derivative"` but their tickers have strike/expiry suffixes (`Z_C100_260320`), so bare root symbols with type `"derivative"` are unambiguously futures.

```python
# Auto-detect futures from IBKR exchange mappings
# Requires BOTH: ticker in YAML AND position type is "derivative"
# to avoid equity ticker collisions (e.g. Z = Zillow vs Z = FTSE futures)
instrument_types: Dict[str, str] = {}
try:
    from ibkr.compat import get_ibkr_futures_exchanges
    known_futures = get_ibkr_futures_exchanges()
    # Build set of derivative tickers from positions
    derivative_tickers = {
        p["ticker"] for p in self.positions if p.get("type") == "derivative"
    }
    for ticker in holdings_dict:
        if ticker in known_futures and ticker in derivative_tickers:
            instrument_types[ticker] = "futures"
except Exception:
    logger.warning("Failed to auto-detect futures instrument types", exc_info=True)
```

Pass `instrument_types=instrument_types or None` to `from_holdings()`.

This is safe because `get_ibkr_futures_exchanges()` reads from a `@lru_cache(maxsize=1)` YAML file — no network call, no IBKR connection needed. The `except` block logs a warning instead of silently passing (Codex LOW #1).

### Step 3. Thread through `config_from_portfolio_data()` — `core/config_adapters.py`

Add to the config dict at line 38:
```python
"instrument_types": portfolio_data.instrument_types,
```

No other changes needed — `load_portfolio_config()` already returns raw YAML keys via `cfg = dict(cfg_raw)`, so an `instrument_types` key in YAML config files flows through automatically.

### Step 4. Extract and pass in `analyze_portfolio()` — `core/portfolio_analysis.py`

After line 94 (`currency_map = config.get("currency_map")`), add:
```python
instrument_types = config.get("instrument_types")
```

Pass to `build_portfolio_view()` at line 134:
```python
instrument_types=instrument_types,
```

### Step 5. No changes needed downstream

- **`run_risk.py`** — `run_portfolio()` calls `analyze_portfolio()` which reads `instrument_types` from the config dict internally. No parameter change needed.
- **`mcp_tools/risk.py`** — `_load_portfolio_for_analysis()` calls `to_portfolio_data()` which will now auto-detect futures and populate `instrument_types` on `PortfolioData`. Flows automatically through `PortfolioService` → `run_portfolio()` → `analyze_portfolio()` → `build_portfolio_view()`.
- **`services/portfolio_service.py`** — passes `portfolio_data` through unchanged.

---

## Files Modified

| File | Change |
|------|--------|
| `core/data_objects.py` | Add `instrument_types` field to `PortfolioData`, param to `from_holdings()`, add to `_generate_cache_key()` / `from_yaml()` / `to_yaml()`, auto-detection with derivative guard in `to_portfolio_data()` |
| `core/config_adapters.py` | Add `instrument_types` to config dict in `config_from_portfolio_data()` (1 line) |
| `core/portfolio_analysis.py` | Extract `instrument_types` from config, pass to `build_portfolio_view()` (2 lines) |

**3 files, ~25 lines of code.** No breaking changes — all new parameters are optional with `None` defaults.

---

## Verification

1. **Unit tests pass**: `python3 -m pytest tests/core/test_portfolio_risk.py -v`
2. **Auto-detection works (futures tagged)**:
   ```python
   from core.data_objects import PositionsData
   pd = PositionsData(positions=[
       {"ticker": "NKD", "quantity": 1, "value": 195000, "type": "derivative",
        "position_source": "ibkr", "currency": "USD"},
       {"ticker": "AAPL", "quantity": 100, "value": 22000, "type": "equity",
        "position_source": "schwab", "currency": "USD"},
   ])
   portfolio_data = pd.to_portfolio_data()
   print(portfolio_data.instrument_types)  # → {"NKD": "futures"}
   ```
3. **Z collision guard (equity not tagged)**:
   ```python
   pd = PositionsData(positions=[
       {"ticker": "Z", "quantity": 100, "value": 5000, "type": "equity",
        "position_source": "schwab", "currency": "USD"},
   ])
   portfolio_data = pd.to_portfolio_data()
   print(portfolio_data.instrument_types)  # → None (Z equity not misclassified)
   ```
4. **YAML config path**: An `instrument_types: {"HSI": "futures"}` key in a portfolio YAML flows through `load_portfolio_config()` → `analyze_portfolio()` → `build_portfolio_view()` automatically.
5. **Cache key includes instrument_types**: Verify different `instrument_types` produce different cache keys.
6. **Full test suite**: `python3 -m pytest tests/core/ tests/ibkr/ -v`

## Codex Review Round 1 — Findings Addressed

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| H1 | HIGH | Z ticker collision — ticker-only matching misclassifies equities | Added `derivative` type guard: requires both YAML match AND `type == "derivative"` |
| H2 | HIGH | Cache/YAML serialization gaps | Added `instrument_types` to `_generate_cache_key()`, `from_yaml()`, `to_yaml()` |
| M1 | MEDIUM | Symbol matching brittle (FESX vs ESTX50) | Codex was correct: YAML uses IBKR symbols (`ESTX50`, `DAX`) not Eurex product codes (`FESX`, `FDAX`). Auto-detection matches against YAML keys so it will work correctly. The parent plan's YAML entries should be corrected as a separate follow-up (explains why FESX/FDAX failed in live IBKR testing). |
| M2 | MEDIUM | No YAML input validation | Acceptable: same pattern as `currency_map` — no validation on that either. Consistent behavior. |
| M3 | MEDIUM | `test_data_objects.py` doesn't exist | Fixed: removed from verification section. Using existing test files. |
| L1 | LOW | Silent `except Exception: pass` | Changed to `logger.warning()` with `exc_info=True` |
