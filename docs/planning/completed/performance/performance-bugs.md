# Performance — Known Bugs & Issues

Catalog of open issues discovered during performance analysis (hypothetical and realized).

Last updated: 2026-02-15

---

## P-001: 12-month calendar window fails `min_months=12` gate in hypothetical performance

**Severity:** HIGH
**Status:** Fixed (2026-02-14)
**Impact:** Hypothetical performance returns `insufficient data` even for normal Jan-Dec windows.

**Root cause:** Two gates applied sequentially with inconsistent thresholds:
1. `_filter_tickers_by_data_availability()` — pre-filter gate
2. `get_returns_dataframe()` — returns-building gate (hardcoded `min_observations=12`)

The first gate was fixed to be window-aware (`min_obs = min(default, requested_return_observations)`), but the window-aware value was not passed to the second gate, which re-applied the stricter default and excluded all tickers.

**Resolution:**
1. `calculate_portfolio_performance_metrics()` computes window-aware `min_obs` (e.g., 11 for a 12-month calendar window) and passes it to both `_filter_tickers_by_data_availability(min_months=min_obs)` and `get_returns_dataframe(min_observations=min_obs)`.
2. Threshold centralized in `DATA_QUALITY_THRESHOLDS["min_observations_for_expected_returns"]`.

**Verified (MCP, 2026-02-14):**
- `get_performance(mode="hypothetical", start_date="2024-01-01", end_date="2024-12-31")` → +24.23%, Sharpe 1.37
- `get_performance(mode="hypothetical", start_date="2025-01-01")` → +17.50%, Sharpe 1.62

**Files:**
- `portfolio_risk.py` (`_filter_tickers_by_data_availability`, `get_returns_dataframe`, `calculate_portfolio_performance_metrics`)

---

## P-002: 20 unpriceable symbols in realized run distort NAV and confidence

**Severity:** HIGH
**Status:** Fixed (2026-02-15) — 20 → 4 unpriceable (80% reduction)
**Impact:** Previously, symbols valued at `0` in NAV path reduced metric fidelity. Now most are resolved.

**Description:**
In realized performance for `hc@henrychien.com`, the engine originally reported `20` unpriceable symbols. Through the IBKR Market Data Client implementation (Phases 0-8), this was reduced to 4.

**Resolution (IBKR Market Data Client — `docs/planning/IBKR_MARKET_DATA_CLIENT_PLAN.md`):**

1. **Instrument metadata pipeline** — `instrument_type` + `contract_identity` threaded from transaction ingestion through position timeline to pricing loop (`trading_analysis/instrument_meta.py`, side dict approach).
2. **Symbol filtering** — FX artifacts (`GBP.HKD`, `USD.HKD`) and unresolvable symbols (`Unknown_C2_230406`) filtered at `build_position_timeline()` based on `instrument_type`, not hardcoded names. (-3 symbols)
3. **FIFO terminal pricing for expired options** — Uses trade-time close price as terminal value instead of fetching from market data. Resolved 11 expired IBKR options and 2 Plaid options. (-13 symbols)
4. **IBKR Market Data Client** (`services/ibkr_data/`) — First-class client with instrument profiles, contract resolution, disk cache, and fallback chains for futures/FX/bonds/options.
5. **Futures via IBKR Gateway** — `MGC`, `ZF` priced via `reqHistoricalData()` when Gateway is running. (-2 symbols when Gateway up)

**Verified (live test, 2026-02-15 with TWS running):**
- Unpriceable: 20 → 4 (with IBKR Gateway) / 20 → 6 (without Gateway)
- Volatility: 80.21% → 46.01% (zero-valued options no longer drag NAV)
- Futures tested: ES, GC, NQ, SI, CL, MGC, ZF — all returning monthly bars
- FX tested: EURUSD, GBPUSD, USDJPY, GBPHKD, AUDUSD, USDCAD, EURGBP, USDCHF, NZDUSD, USDHKD — all working

**Remaining unpriceable (4, with Gateway running):**

| # | Symbol | Type | Reason |
|---|--------|------|--------|
| 1 | `US Treasury Bill - 5.35% 08/08/2024 USD 100` | Bond (Plaid name) | No conId from Plaid; ISIN/CUSIP resolution deferred |
| 2 | `US Treasury Note - 4.25% 15/10/2025 USD 100` | Bond (Plaid name) | No conId from Plaid; ISIN/CUSIP resolution deferred |
| 3 | `MGC` | Futures | Only when IBKR Gateway not running |
| 4 | `ZF` | Futures | Only when IBKR Gateway not running |

**Files:**
- `trading_analysis/instrument_meta.py` — InstrumentType enum, InstrumentMeta, coerce_instrument_type()
- `services/ibkr_data/` — Market data client package (client, profiles, contracts, cache, exceptions, compat)
- `core/realized_performance_analysis.py` — Pricing loop routing by instrument_type, FIFO terminal pricing
- `trading_analysis/analyzer.py` — Instrument tagging for Plaid/SnapTrade/IBKR Flex sources

---

## P-003: Alpha/beta default to 0/1 for windows under 24 months (misleading)

**Severity:** MEDIUM
**Status:** Fixed (2026-02-14)
**Impact:** Custom date windows < 24 months show `alpha=0.00, beta=1.000, r_squared=0.000` instead of `None`, falsely implying perfect benchmark tracking.

**Resolution:**
1. CAPM fallback now returns `None` for `alpha_annual`, `beta`, and `r_squared` when regression is skipped or fails (no more misleading `0/1/0` defaults).
2. CAPM minimum observation threshold lowered from 24 to `12` months (configurable via `DATA_QUALITY_THRESHOLDS["min_observations_for_capm_regression"]`).
3. `compute_performance_metrics()` emits an explicit warning when CAPM is skipped due to insufficient observations.
4. Engine self-sources threshold from settings when caller doesn't specify (`min_capm_observations=None` default).
5. Downstream formatting paths hardened to handle `None` CAPM fields safely (`result_objects.py`, `run_portfolio_risk.py`, `mcp_tools/performance.py`).

**Verified (MCP, 2026-02-14):**
- 2024 (12mo): alpha=-9.42, beta=0.869 (real regression, was 0/1 before)
- H2 2025 (6mo): alpha=None, beta=None (correctly skipped, < 12 months)
- Full inception (41mo): alpha=-28.63, beta=1.325 (unchanged)

**Files:**
- `core/performance_metrics_engine.py` (None fallback, warning, settings import)
- `portfolio_risk.py` (warning merging)
- `settings.py` (`DATA_QUALITY_THRESHOLDS`)
- `core/result_objects.py` (None guards in `_categorize_performance`, `_generate_key_insights`)
- `run_portfolio_risk.py` (None guards)
