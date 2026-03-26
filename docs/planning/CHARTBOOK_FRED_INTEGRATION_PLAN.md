# Track F — Chart Book FRED Integration Plan

## Context

The macro chart book (`scripts/chartbook/`, 11 sections, Plotly dark theme) generates HTML market review reports using FMP-only data. FRED (Federal Reserve Economic Data) provides authoritative, higher-quality macro data for many of the same indicators. The FRED client at `/Users/henrychien/Documents/Jupyter/investment_tools/fred/` is production-ready with 38 curated series, parquet caching, rate limiting, and retry logic.

**Goal**: Enrich the chart book with FRED data (steps F1-F4 from TODO).

## Codex Review — Round 1 FAIL → Fixes Applied

| # | Finding | Fix |
|---|---------|-----|
| 1 | GDP semantic break: FMP `GDP` is level (~$31K), plan mapped to growth rate (~0.7%) | Use FRED `GDP` (nominal, ~$31K) — matches FMP. **Must** add `GDP` to `investment_tools/fred/registry.py` with quarterly frequency for correct cache TTL |
| 2 | CPI/inflation mapping inconsistent: `inflationRate` left on FMP when FRED has `T10YIE` | Map `inflationRate` → `T10YIE` (breakeven inflation, daily, matches FMP) |
| 3 | `sys.path` insert at position 0 could shadow local packages | Append to end: `sys.path.append(...)` instead of `insert(0, ...)` |
| 4 | FRED failure isolation too coarse: `get_multiple()` all-or-nothing | Fetch per-series individually with per-series try/except |
| 5 | 2-year CPI lookback yields only ~1yr visible after YoY transform | Use 3-year lookback for economic series |

### Round 2 Findings (2 remaining → fixed)

| # | Finding | Fix |
|---|---------|-----|
| 1 | GDPC1 is real GDP (chained 2017$, ~$24K) ≠ FMP GDP (nominal, ~$31K). FRED `GDP` series matches FMP but isn't in registry (cache defaults to daily for quarterly data) | Use FRED `GDP` series. **Must** add `GDP` entry to `investment_tools/fred/registry.py` (quarterly, billions_usd) — required for correct cache TTL |
| 2 | CPI fallback unit mismatch: FRED YoY% (~2.7%) vs FMP raw index (~327) on same panel | For CPI subplot specifically, do NOT fall back to raw FMP. If FRED CPI unavailable, skip the panel (show warning) rather than silently switching units. Update subplot label to "CPI YoY %" when FRED active |

## Design Decisions

1. **Economic dashboard: FRED primary, FMP fallback.** FRED is the authoritative source for macro indicators (FMP's economic data is itself sourced from FRED). Use FRED data when available; fall back to FMP when FRED is unavailable. Avoids confusing dual-line visual noise.

2. **Yield curve: keep FMP curve + add FRED yield spread time series.** The existing FMP treasury curve (current + historical overlay) works well with multi-maturity data. Rather than rebuilding a FRED-sourced curve from individual DGS series (near-identical to FMP), add a new yield spread time series chart (T10Y2Y + T10Y3M) that shows inversion dynamics — the highest value-add from FRED.

3. **Consumer sentiment: skip FRED, keep FMP.** UMCSENT is not in the FRED registry. Adding it is a cross-repo change to investment_tools. FMP already provides consumer sentiment. Defer.

---

## F1 — Wire FRED Client into Data Fetcher

**Files**: `scripts/macro_chartbook.py`, `scripts/chartbook/data_fetcher.py`

### macro_chartbook.py — Add Jupyter parent to sys.path

Add one line after existing sys.path setup (line 12):

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))        # existing: risk_module/

_jupyter_root = str(Path(__file__).resolve().parent.parent.parent)     # Jupyter/ for investment_tools
if _jupyter_root not in sys.path:
    sys.path.append(_jupyter_root)                                      # append (not insert) to avoid shadowing
```

### data_fetcher.py — FRED import + fetch pipeline

**Import block** (top of file, after existing imports):

```python
try:
    from investment_tools.fred import FredClient
    _FRED_AVAILABLE = True
except ImportError:
    _FRED_AVAILABLE = False
```

**Constants**:

```python
FRED_ECONOMIC_SERIES = {
    "GDP": "GDP",                           # Nominal GDP (billions, quarterly) — matches FMP GDP (~$31K)
    "CPI": "CPIAUCSL",                    # CPI All Urban (monthly index → YoY% in builder)
    "inflationRate": "T10YIE",            # 10Y Breakeven Inflation (daily, %) — matches FMP inflationRate
    "unemploymentRate": "UNRATE",          # Unemployment Rate (monthly, already %)
    "federalFunds": "FEDFUNDS",           # Federal Funds Rate (monthly, already %)
}
FRED_YIELD_SPREAD_SERIES = ["T10Y2Y", "T10Y3M"]
FRED_CREDIT_SERIES = ["BAA10Y", "BAMLH0A0HYM2"]
```

Key: dict keys match INDICATOR_SPECS keys in charts_economic.py for direct lookup.

**New function**: `_fetch_fred_data(econ_start: str, daily_start: str, end: str) -> dict[str, pd.Series]`
- Accepts two start dates: **3-year lookback** for economic series (CPI needs 12 months for YoY transform + ~2 years visible), 1-year for daily series
- Instantiates `FredClient()` — fails gracefully if no API key
- Fetches **per-series individually** with per-series try/except (not `get_multiple` which is all-or-nothing). One bad series doesn't blank the bundle.
- Returns `{series_id: pd.Series}` dict; individual failures logged and skipped
- All rate limiting/caching handled by FredClient internally (~4s cold, ~0s warm via parquet cache)

**Integration into `fetch_chartbook_data()`**:
- Compute `three_years_ago_str` alongside existing `one_year_ago_str`
- Submit `_fetch_fred_data()` to a single-thread executor at the start (runs in parallel with FMP)
- Collect result at the end (no timeout — let FredClient's own retry limits bound it; executor.shutdown handles cleanup)
- Add `bundle["fred"] = {...}` key (partial results on individual failures)

---

## F2 — Enrich Economic Dashboard

**File**: `scripts/chartbook/charts_economic.py`

### Signature change

```python
def build_economic_section(
    indicators: dict[str, Optional[dict[str, Any]]],
    fred_data: Optional[dict[str, pd.Series]] = None,
) -> str:
```

### FRED-to-indicator mapping

```python
FRED_INDICATOR_MAP: dict[str, tuple[str, Callable | None] | None] = {
    "GDP": ("GDP", None),                  # Nominal GDP (billions) — matches FMP GDP
    "CPI": ("CPIAUCSL", _yoy_pct_change),# CPI index → YoY% (NO FMP fallback — units differ)
    "inflationRate": ("T10YIE", None),    # 10Y breakeven inflation (daily, %) — matches FMP
    "federalFunds": ("FEDFUNDS", None),
    "unemploymentRate": ("UNRATE", None),
    "consumerSentiment": None,            # FMP-only (UMCSENT not in FRED registry)
}
```

### New helper

```python
def _yoy_pct_change(series: pd.Series) -> pd.Series:
    """Monthly index → YoY percent change."""
    return (series.pct_change(periods=12) * 100).dropna()
```

### Plot logic

For each subplot: check FRED map → if available, apply transform, plot FRED trace, set `fred_plotted = True`. If not plotted from FRED, fall back to existing FMP `_extract_points()` logic — **except** for CPI, where FMP fallback is suppressed (FMP CPI is raw index ~327 vs FRED YoY% ~2.7%; show `_warning()` instead to avoid silent unit switch). Update CPI subplot title to "CPI YoY %" when FRED data is used.

**FRED `GDP` registry prerequisite**: The FRED series `GDP` (nominal) is not in the investment_tools registry. **Before implementing F2**, add a `GDP` entry to `/Users/henrychien/Documents/Jupyter/investment_tools/fred/registry.py` with `frequency="quarterly"`, `units="billions_usd"`. Without this, `FredClient` defaults to daily cache TTL (1 day) for quarterly data that only updates every 3 months.

### Call site update in macro_chartbook.py

```python
fred_data = data.get("fred") or {}
("Economic Dashboard", build_economic_section(data.get("economic_indicators") or {}, fred_data=fred_data)),
```

---

## F3 — Enrich Yield Curve with Spread Time Series

**File**: `scripts/chartbook/charts_yield_curve.py`

### Signature change

```python
def build_yield_curve_section(
    treasury_df: Optional[pd.DataFrame],
    fred_data: Optional[dict[str, pd.Series]] = None,
) -> str:
```

### New function: `_build_yield_spread_chart(fred_data) -> str`

- Plots T10Y2Y (10Y-2Y spread, blue) and T10Y3M (10Y-3M spread, green) as overlaid lines
- Adds zero hline with "Inversion" annotation (red dashed) — the key signal
- Plotly dark theme, 420px height, responsive
- Returns empty string if no data (graceful degrade)

### Updated `build_yield_curve_section()`

Appends the spread chart as a third subsection below existing "Current Curve" and "Today vs History":

```
<div class="subsection"><h3>Current Curve</h3>...</div>        ← existing
<div class="subsection"><h3>Today vs History</h3>...</div>     ← existing
<div class="subsection"><h3>Yield Spread History</h3>...</div> ← NEW (from FRED)
```

### Call site update

```python
("Yield Curve", build_yield_curve_section(data.get("treasury_rates"), fred_data=fred_data)),
```

---

## F4 — New Credit Spreads Section

**New file**: `scripts/chartbook/charts_credit.py`

### `build_credit_section(fred_data) -> str`

Follows the exact pattern of existing section builders:
- Plots BAA10Y (investment-grade spread, amber) and BAMLH0A0HYM2 (HY OAS, red)
- Three regime reference hlines: 2% (tight/green), 5% (elevated/yellow), 8% (distressed/red)
- Plotly dark theme, 460px height, horizontal legend, responsive
- Returns `_warning()` if no FRED data

### Section ordering in macro_chartbook.py

Insert after Yield Curve, before Volatility (fixed-income flow: curve → credit → vol):

```python
from scripts.chartbook.charts_credit import build_credit_section
...
("Yield Curve", ...),
("Credit Spreads", build_credit_section(fred_data=fred_data)),  # NEW
("Volatility", ...),
```

---

## Files Changed

| File | Action | ~Lines |
|------|--------|--------|
| `scripts/macro_chartbook.py` | Modify: sys.path, import, section list, fred_data threading | +12 |
| `scripts/chartbook/data_fetcher.py` | Modify: FRED import, constants, `_fetch_fred_data()`, parallel integration | +65 |
| `scripts/chartbook/charts_economic.py` | Modify: FRED map, YoY transform, updated signature + plot logic | +40 |
| `scripts/chartbook/charts_yield_curve.py` | Modify: spread chart builder, updated signature | +50 |
| `scripts/chartbook/charts_credit.py` | **New**: credit spreads section builder | ~75 |
| `investment_tools/fred/registry.py` | Modify (external repo): add `GDP` entry (quarterly, billions_usd) | +8 |

**Total**: ~250 lines across 6 files (1 new, 5 modified — 1 in external repo).

## Verification

1. **Smoke test**: `python scripts/macro_chartbook.py` — generates HTML report, opens in browser
2. **FRED availability**: Verify `bundle["fred"]` has expected series keys (GDP, CPIAUCSL, T10YIE, UNRATE, FEDFUNDS, T10Y2Y, T10Y3M, BAA10Y, BAMLH0A0HYM2)
6. **Unit consistency**: Verify CPI subplot shows YoY% (~2-3%) when FRED active, and shows warning (not raw index ~327) when FRED unavailable. GDP subplot should show nominal values (~$31K) matching FMP.
3. **Fallback**: Temporarily rename `investment_tools/` → verify chart book still generates with FMP-only data, no errors
4. **Visual check**: Economic dashboard shows GDP/CPI/unemployment/fed_funds from FRED (same data quality, authoritative source). Yield curve section has new spread chart with inversion zero-line. Credit Spreads section appears with two spread lines and regime hlines.
5. **Sidebar nav**: Verify "Credit Spreads" appears in sidebar between Yield Curve and Volatility
