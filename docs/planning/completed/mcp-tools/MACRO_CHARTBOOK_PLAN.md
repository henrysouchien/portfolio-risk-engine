# Macro Review Chart Book Generator

## Context

Repeatable, deterministic macro review workflow — no LLM in the loop. Pull market/economic data from existing FMP tools, generate interactive charts with plotly, output an HTML file with plotly CDN reference. Run on demand via CLI script.

## Architecture

```
scripts/macro_chartbook.py          # CLI entry point
scripts/chartbook/
  __init__.py
  data_fetcher.py                   # Parallel FMP data fetching
  charts_market.py                  # Section 1: Index + sector bars
  charts_economic.py                # Section 2: 6 indicator line charts
  charts_sectors.py                 # Section 3: Sector perf + P/E bars
  charts_technical.py               # Section 4: Price+MA / RSI / MACD per symbol
  charts_movers.py                  # Section 5: Gainers/losers HTML tables
  charts_events.py                  # Section 6: Upcoming events HTML table
  html_template.py                  # HTML shell + CSS + section composer
```

Output: `logs/chartbook/macro_review_YYYY-MM-DD.html`

## Data Sources (all existing, direct Python imports)

| Function | Import from | Data used |
|----------|------------|-----------|
| `get_market_context(format="full")` | `fmp.tools.market` | `response["indices"]` = `[{symbol, name, price, change_pct}]` (^GSPC/^DJI/^IXIC/^RUT), `response["sectors"]`, `response["gainers/losers/actives"]` |
| `get_economic_data(mode="indicator", indicator_name=X, format="full")` | `fmp.tools.market` | `response["data"]` = `[{date, value}, ...]` for 6 indicators |
| `get_economic_data(mode="calendar", format="full")` | `fmp.tools.market` | `response["data"]` = `[{date, event, country, estimate, actual, impact}]` |
| `get_sector_overview(format="summary")` | `fmp.tools.market` | `response["sectors"]` = `[{sector, change_pct, pe_ratio}]` |
| `get_technical_analysis(symbol=X, format="full")` | `fmp.tools.technical` | `response["time_series"]` dict (sma_20/50/200, rsi_14, macd, bollinger), `response["composite_signal"]` |
| `get_events_calendar(event_type="earnings", format="summary")` | `fmp.tools.news_events` | `response["events"]` = `[{symbol, date, eps_estimated, eps_actual}]` (summary mode provides parsed fields) |

**Note on index symbols:** `get_market_context` returns index tickers (^GSPC, ^DJI, ^IXIC, ^RUT), not ETF tickers. Section 1 displays these with their friendly names (S&P 500, Dow Jones, etc.).

**Note on events:** `get_market_context` events section has a known bug (`_normalize_events` drops `country` before filtering). Use `get_economic_data(mode="calendar")` directly for economic events, and `get_events_calendar(event_type="earnings")` for earnings.

## Chart Book Sections

### 1. Market Snapshot
- Horizontal bar: index returns (S&P 500, Dow, Nasdaq, Russell 2000 from ^GSPC/^DJI/^IXIC/^RUT) — green/red by sign
- Horizontal bar: sector daily change — green/red gradient

### 2. Economic Dashboard
- 2×3 subplot grid of line charts for: GDP, CPI, inflationRate, federalFunds, unemploymentRate, consumerSentiment
- Each shows historical time series from `get_economic_data`

### 3. Sector Analysis
- Horizontal bar: sector performance sorted by change_pct
- Horizontal bar: sector P/E ratios

### 4. Technical Analysis (per symbol: SPY, QQQ, IWM, DIA)
- 3-row subplot per symbol (shared x-axis):
  - Row 1 (60%): Close price + SMA 20/50/200 overlay + Bollinger bands
  - Row 2 (20%): RSI(14) with 70/30 lines
  - Row 3 (20%): MACD line + signal + histogram
- Composite signal badge annotation (strong_buy → strong_sell)

### 5. Market Movers
- HTML tables (no plotly): top gainers, losers, most active — color-coded

### 6. Upcoming Events
- HTML table: economic calendar from `get_economic_data(mode="calendar")`, sorted by date, impact color-coded
- HTML table: upcoming earnings from `get_events_calendar(event_type="earnings")` with EPS estimates

## Key Implementation Details

**Data fetching** (`data_fetcher.py`):
- `ThreadPoolExecutor(max_workers=4)` to parallelize 6 economic indicators + 1 calendar + 1 earnings calendar = 8 calls
- Technical analysis calls run **sequentially** (each internally fans out to ~8 FMP indicator endpoints via its own thread pool — nesting would over-parallelize and risk rate limits)
- `get_market_context` and `get_sector_overview` run sequentially (fast, 1-2s each)
- Each call wrapped in `_safe_call()` → returns `None` on failure
- Total: ~13 top-level calls but ~45 actual FMP API hits (4×8 from technicals + ~13 direct). Target runtime <60s.

**Chart generation**:
- Each `charts_*.py` module: takes data dict → returns HTML fragment via `plotly.io.to_html(fig, full_html=False, include_plotlyjs=False)`
- Table sections return raw styled HTML (no plotly needed)
- Missing data → placeholder `<p class="warning">Section unavailable</p>`

**HTML template** (`html_template.py`):
- `compose_html(sections: list[tuple[str, str]], date_str: str) -> str`
- HTML with plotly CDN in `<head>` (requires internet to view; keeps file size small), dark theme CSS, nav sidebar with anchor links
- Each section wrapped in `<div class="section" id="{anchor}">`

**CLI** (`scripts/macro_chartbook.py`):
- `sys.path.insert` + `load_dotenv()` (same pattern as `scripts/ibkr_nav_breakdown.py`)
- Args: `--date` (default today), `--output` (path override)
- Prints timing to stderr

## Files to Create/Modify

| File | Action |
|------|--------|
| `scripts/chartbook/__init__.py` | NEW — empty |
| `scripts/chartbook/data_fetcher.py` | NEW — parallel fetch orchestration |
| `scripts/chartbook/charts_market.py` | NEW — index + sector bars |
| `scripts/chartbook/charts_economic.py` | NEW — 6 indicator subplots |
| `scripts/chartbook/charts_sectors.py` | NEW — sector perf + P/E |
| `scripts/chartbook/charts_technical.py` | NEW — price/RSI/MACD per symbol |
| `scripts/chartbook/charts_movers.py` | NEW — HTML tables |
| `scripts/chartbook/charts_events.py` | NEW — HTML table |
| `scripts/chartbook/html_template.py` | NEW — HTML shell + composer |
| `scripts/macro_chartbook.py` | NEW — CLI entry point |
| `requirements.txt` | EDIT — add `plotly>=5.21.0` |

## Error Handling

- **Fetch level**: `_safe_call()` catches exceptions + status=="error", returns `None`, logs to stderr
- **Chart level**: Each builder checks for `None`/empty data, returns placeholder HTML
- **Compose level**: Always writes HTML even if some sections are empty
- Script never crashes on API failures

## Verification

1. `pip install plotly>=5.21.0`
2. `python scripts/macro_chartbook.py` — should complete in <60s
3. Open `logs/chartbook/macro_review_YYYY-MM-DD.html` in browser
4. Verify: all 6 sections render, charts are interactive (hover tooltips), technical subplots aligned
5. Failure test: invalid FMP key → script completes, HTML has placeholders
