# New MCP Tools Research — Gap Analysis & FMP Endpoint Mapping

**Date:** 2026-02-07
**Status:** Tier 1 + Tier 2 complete (22 tools across 2 servers). Tier 3 in progress.

## Current State

### Registered FMP Endpoints (15)
| Name | Path | Category |
|------|------|----------|
| `historical_price_eod` | `/stable/historical-price-eod/full` | prices |
| `historical_price_adjusted` | `/stable/historical-price-eod/dividend-adjusted` | prices |
| `treasury_rates` | `/stable/treasury-rates` | treasury |
| `dividends` | `/stable/dividends` | dividends |
| `search` | `/v3/search` | search |
| `profile` | `/v3/profile/{symbol}` | search |
| `income_statement` | `/stable/income-statement` | fundamentals |
| `balance_sheet` | `/stable/balance-sheet-statement` | fundamentals |
| `cash_flow` | `/stable/cash-flow-statement` | fundamentals |
| `key_metrics` | `/stable/key-metrics` | fundamentals |
| `analyst_estimates` | `/stable/analyst-estimates` | analyst |
| `price_target` | `/stable/price-target-summary` | analyst |
| `price_target_consensus` | `/stable/price-target-consensus` | analyst |
| `earnings_transcript` | `/v3/earning_call_transcript/{symbol}` | transcripts |
| `sec_filings` | `/v3/sec_filings/{symbol}` | filings |

### Current MCP Tools (22 across 2 servers)

**portfolio-mcp** (10 tools — require user/portfolio context):
1. `get_positions` — current holdings with weights
2. `get_risk_score` — 0-100 risk score
3. `get_risk_analysis` — detailed risk breakdown (9 sections, 39 keys)
4. `get_performance` — hypothetical + realized returns
5. `analyze_stock` — single stock analysis
6. `run_optimization` — min variance / max return
7. `run_whatif` — scenario analysis
8. `get_factor_analysis` — factor correlations, performance & returns (3 modes + section filtering)
9. `get_factor_recommendations` — factor offset suggestions
10. `get_income_projection` — dividend/income forecasting

**fmp-mcp** (12 tools — standalone FMP data, no user context):
1. `fmp_fetch` — fetch from any registered FMP endpoint
2. `fmp_search` — company search by name/ticker
3. `fmp_profile` — detailed company profile
4. `fmp_list_endpoints` — discover available endpoints
5. `fmp_describe` — endpoint parameter documentation
6. `screen_stocks` — company screener with fundamental filters
7. `get_news` — stock/general/press release news
8. `get_events_calendar` — earnings/dividends/splits/IPOs calendar
9. `get_technical_analysis` — composite technical signals (SMA/EMA/RSI/ADX/MACD/Bollinger)
10. `compare_peers` — peer comparison on TTM ratios
11. `get_economic_data` — macro indicators (GDP/CPI/unemployment/rates)
12. `get_sector_overview` — sector performance + P/E snapshots

---

## Gap 1: Screening & Idea Generation

### FMP Endpoints Available

**Stock Screener**
- Path: `/stable/company-screener`
- Params: marketCapMoreThan/LowerThan, sector, industry, betaMoreThan/LowerThan, priceMoreThan/LowerThan, dividendMoreThan/LowerThan, volumeMoreThan/LowerThan, exchange, country, isEtf, isFund, isActivelyTrading, limit
- Returns: symbol, companyName, marketCap, sector, industry, beta, price, lastAnnualDividend, volume, exchange, country

**Stock Peers**
- Path: `/stable/stock-peers?symbol=AAPL`
- Returns: list of peer tickers (same exchange + sector + similar market cap)

**Peers Bulk**
- Path: `/stable/peers-bulk`
- Returns: all peer relationships in one call

**Reference Lists**
- `/stable/available-sectors` — all sector names
- `/stable/available-industries` — all industry names
- `/stable/available-exchanges` — all exchanges
- `/stable/available-countries` — all countries

**ETF Analysis**
- `/stable/etf/holdings?symbol=SPY` — ETF constituent breakdown
- `/stable/etf/info?symbol=SPY` — expense ratio, AUM, strategy
- `/stable/etf/sector-weightings?symbol=SPY` — sector allocation
- `/stable/etf/country-weightings?symbol=SPY` — geographic allocation
- `/stable/etf/asset-exposure?symbol=AAPL` — reverse: which ETFs hold this stock?

### Proposed MCP Tool: `screen_stocks`
- Wraps `company-screener` with all filter params
- Could also support `isEtf=true` for ETF screening
- Summary format: top N results with key metrics
- Full format: raw screener response

### Proposed MCP Tool: `compare_peers`
- Wraps `stock-peers` + `ratios` for side-by-side comparison
- Input: ticker or list of tickers
- Output: comparative table (P/E, ROE, margins, growth, beta)

---

## Gap 2: Macro & Market Context

### FMP Endpoints Available

**Economic Indicators**
- Path: `/stable/economic-indicators?name=GDP`
- Available indicators: GDP, realGDP, CPI, inflationRate, federalFunds, unemploymentRate, totalNonfarmPayroll, initialClaims, consumerSentiment, retailSales, durableGoods, industrialProductionTotalIndex, housingStarts, totalVehicleSales, smoothedUSRecessionProbabilities, 30YearFixedRateMortgageAverage, tradeBalanceGoodsAndServices
- Params: name (required), from, to

**Economic Calendar**
- Path: `/stable/economic-calendar`
- Params: from, to (max 90-day window)
- Returns: upcoming economic events with prior/forecast/actual values

**Market Risk Premium**
- Path: `/stable/market-risk-premium`
- Returns: equity risk premium for CAPM

**Sector/Industry Performance**
- `/stable/sector-performance-snapshot?date=YYYY-MM-DD` — daily sector % change
- `/stable/industry-performance-snapshot?date=YYYY-MM-DD` — daily industry % change
- `/stable/historical-sector-performance?sector=Energy&from=...&to=...` — time series
- `/stable/historical-industry-performance?industry=Biotechnology&from=...&to=...`

**Sector/Industry Valuation**
- `/stable/sector-pe-snapshot?date=YYYY-MM-DD` — sector P/E ratios
- `/stable/industry-pe-snapshot?date=YYYY-MM-DD` — industry P/E ratios
- `/stable/historical-sector-pe?sector=Energy&from=...&to=...` — P/E time series
- `/stable/historical-industry-pe?industry=Biotechnology&from=...&to=...`

**Market Movers**
- `/stable/biggest-gainers` — top gainers
- `/stable/biggest-losers` — top losers
- `/stable/most-actives` — highest volume
- `/stable/batch-index-quotes` — index quotes (S&P, DJIA, Nasdaq, Russell)

**Sentiment & Positioning**
- `/stable/commitment-of-traders-list` — available COT symbols
- `/stable/commitment-of-traders-report?symbol=...` — futures positioning
- `/stable/commitment-of-traders-analysis?symbol=...` — COT analysis
- `/api/v4/stock-news-sentiments-rss-feed` — news with sentiment scores
- `/api/v4/historical/social-sentiment?symbol=...` — social media sentiment

**Not available in FMP:** VIX (fetchable as ticker), put/call ratios, fund flows (partial via 13F)

### Proposed MCP Tool: `get_economic_data`
- Wraps `economic-indicators` + `economic-calendar`
- Params: indicator name or "calendar" mode
- Summary: latest value + trend direction + upcoming events

### Proposed MCP Tool: `get_sector_overview`
- Combines sector performance + P/E snapshots + portfolio exposure overlay
- Params: date (optional), sector (optional)
- Summary: sector heatmap with portfolio weight context

---

## Gap 3: Valuation

### FMP Endpoints Available

- `/stable/discounted-cash-flow?symbol=AAPL` — intrinsic value via DCF
- `/stable/ratios?symbol=AAPL&period=annual` — full ratio suite (P/E, ROE, margins, leverage)
- `/stable/ratios-ttm?symbol=AAPL` — trailing twelve month ratios
- `/stable/key-metrics-ttm?symbol=AAPL` — TTM key metrics
- `/stable/enterprise-values?symbol=AAPL` — EV components (market cap, debt, cash)
- `/stable/financial-scores?symbol=AAPL` — Altman Z-Score + Piotroski F-Score
- `/stable/owner-earnings?symbol=AAPL` — Buffett-style cash generation
- `/stable/ratings-snapshot?symbol=AAPL` — multi-factor quality rating
- `/stable/ratings-historical?symbol=AAPL` — rating time series
- `/stable/financial-growth?symbol=AAPL` — consolidated growth metrics

**Note:** Full DCF modeling handled in AI-excel-addin repo. Quick DCF + comps buildable here.

---

## Gap 4: News & Catalysts

### FMP Endpoints Available

**News**
- `/stable/news/stock?symbols=AAPL` — per-symbol news (from, to, page, limit)
- `/stable/news/general-latest` — broad market news
- `/stable/news/press-releases?symbols=AAPL` — official company press releases
- `/api/v4/stock-news-sentiments-rss-feed` — news with sentiment scores

**Event Calendars**
- `/stable/earnings-calendar?from=...&to=...` — upcoming earnings (90-day max)
- `/stable/earnings?symbol=AAPL` — earnings beat/miss history
- `/stable/dividends-calendar?from=...&to=...` — ex-dividend dates
- `/stable/ipos-calendar?from=...&to=...` — upcoming IPOs
- `/stable/splits-calendar?from=...&to=...` — stock splits

**Not available in FMP:** FDA calendar, custom event tracking

### Proposed MCP Tool: `get_news`
- Wraps `news/stock` + `news/general-latest`
- Params: symbols (optional), mode (stock/general), limit
- Portfolio mode: auto-fetch news for current holdings

### Proposed MCP Tool: `get_events_calendar`
- Wraps earnings + dividends + splits + IPO calendars
- Params: event_type (earnings/dividends/splits/ipos/all), from, to
- Portfolio mode: filter to holdings only

---

## Gap 5: Technical Analysis

### FMP Endpoints Available

**Technical Indicators** (all support symbol, periodLength, timeframe)
- `/stable/technical-indicators/sma` — Simple Moving Average
- `/stable/technical-indicators/ema` — Exponential Moving Average
- `/stable/technical-indicators/rsi` — Relative Strength Index (0-100)
- `/stable/technical-indicators/adx` — Average Directional Index
- `/stable/technical-indicators/williams` — Williams %R (-100 to 0)
- `/stable/technical-indicators/wma` — Weighted Moving Average
- `/stable/technical-indicators/dema` — Double EMA
- `/stable/technical-indicators/tema` — Triple EMA
- `/stable/technical-indicators/standarddeviation` — Volatility

Timeframes: 1min, 5min, 15min, 30min, 1hour, 4hour, 1day

**Not in FMP but computable:**
- MACD = EMA(12) - EMA(26) with signal EMA(9)
- Bollinger Bands = SMA ± 2×StdDev

**Price Data**
- `/stable/historical-chart/{1min,5min,15min,30min,1hour,4hour}` — intraday OHLCV
- `/stable/stock-price-change?symbol=AAPL` — multi-period % changes (1D→10Y)

### Proposed MCP Tool: `get_technical_analysis`
- Composite view: SMA(20,50,200), EMA(12,26), RSI(14), ADX(14)
- Params: symbol, timeframe (default 1day), indicators (optional subset)
- Summary: trend direction, overbought/oversold, trend strength
- Derived: MACD from EMA endpoints, Bollinger from SMA+StdDev

---

## Gap 6: Transaction / Tax

### Existing Infrastructure (no new FMP endpoints needed)

- `trading_analysis/fifo_matcher.py` — FIFO lot matching, LONG/SHORT tracking
- `trading_analysis/analyzer.py` — realized P&L per lot
- `core/realized_performance_analysis.py` — NAV, position timeline, FIFO integration
- `PositionService` — current positions with cost basis

### Proposed MCP Tool: `suggest_tax_loss_harvest`
- Uses FIFO lots + current prices to identify unrealized loss candidates
- Params: min_loss_threshold (optional), wash_sale_check (bool)
- Output: list of lots with unrealized loss, days held, wash sale risk

---

## Gap 7: Income Analysis

### FMP Endpoints Available
- `/stable/dividends-calendar?from=...&to=...` — forward dividend schedule
- `/stable/dividends?symbol=AAPL` — per-stock payment history (already registered)

### Existing Infrastructure
- `data_loader.fetch_dividend_history()` — dividend events via FMP
- `data_loader.fetch_current_dividend_yield()` — TTM yield
- Performance report shows aggregate yield

### Proposed MCP Tool: `get_income_projection`
- Combines positions + dividend history + forward calendar
- Output: projected monthly/quarterly income, ex-dividend dates for holdings
- Annualized yield, income by position, payment calendar

---

## Gap 8: Insider & Institutional (Bonus)

### FMP Endpoints Available
- `/stable/insider-trading/search?symbol=AAPL` — per-symbol insider activity
- `/stable/insider-trading/statistics?symbol=AAPL` — aggregate buy/sell sentiment
- `/stable/insider-trading/latest` — market-wide insider activity
- `/stable/senate-trades?symbol=AAPL` — congressional trading
- `/stable/institutional-ownership/latest` — 13F filings
- `/stable/institutional-ownership/holder-industry-breakdown` — holder sector allocation

---

## Prioritized Build Order

### Tier 1 — Quick Wins (single FMP endpoint → MCP tool) ✅ COMPLETE
1. **`screen_stocks`** — wraps `company-screener` (18+ filters) ✅
2. **`get_news`** — wraps `news/stock` + `news/general-latest` ✅
3. **`get_events_calendar`** — wraps earnings/dividends/splits/IPO calendars ✅
4. **`get_economic_data`** — wraps `economic-indicators` + `economic-calendar` ✅

### Tier 2 — Moderate (combine data sources) ✅ COMPLETE
5. **`get_technical_analysis`** — wraps TA endpoints with composite view ✅
6. **`get_income_projection`** — positions + dividend history + forward calendar ✅
7. **`compare_peers`** — `stock-peers` + `ratios` for comparative analysis ✅
8. **`get_sector_overview`** — sector perf + P/E + portfolio exposure overlay ✅

### Tier 3 — More Complex (new analysis logic)
9. **`suggest_tax_loss_harvest`** — FIFO data + current prices → loss candidates (plan ready)
10. **`get_market_context`** — macro indicators + sector rotation + movers → narrative

### Out of Scope (handled elsewhere)
- Full DCF modeling → AI-excel-addin repo
- Custom valuation models → AI-excel-addin repo
