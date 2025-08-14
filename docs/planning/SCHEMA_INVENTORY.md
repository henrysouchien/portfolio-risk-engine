# Schema Inventory: Risk Module API Objects

This document provides a comprehensive inventory of all fields, types, and structures observed in the risk_module's API responses and CLI outputs, organized by result object type.

**Sources Analyzed:**
- CLI formatted reports: `/docs/schema_samples/cli/*.txt`
- API JSON payloads: `/docs/schema_samples/api/*.json`

---

## PerformanceResult

### High-Level Structure
- **Root keys**: `benchmark`, `formatted_report`, `performance_metrics`, `portfolio_metadata`, `success`, `summary`
- **CLI representation**: Human-readable performance analysis with emojis and formatted tables
- **Primary data container**: `performance_metrics` object

### Raw Keys Inventory

| Key | Example Value | Type | Required? | Notes |
|-----|---------------|------|-----------|-------|
| **Root Level** |
| `benchmark` | `"SPY"` | string | ✓ | Benchmark ticker symbol |
| `formatted_report` | `"📊 PORTFOLIO PERFORMANCE ANALYSIS..."` | string | ✓ | Complete CLI-formatted text output |
| `performance_metrics` | `{...}` | object | ✓ | Main data container |
| `portfolio_metadata` | `{...}` | object | ✓ | Portfolio identification info |
| `success` | `true` | boolean | ✓ | Operation success flag |
| `summary` | `{...}` | object | ✓ | Key metrics summary |
| **Performance Metrics** |
| `analysis_date` | `"2025-08-06T16:02:43.603755"` | string (ISO datetime) | ✓ | Timestamp of analysis |
| `analysis_period` | `{...}` | object | ✓ | Date range and duration |
| `analysis_period.start_date` | `"2019-01-31"` | string (YYYY-MM-DD) | ✓ | Analysis start date |
| `analysis_period.end_date` | `"2025-06-27"` | string (YYYY-MM-DD) | ✓ | Analysis end date |
| `analysis_period.total_months` | `61` | integer | ✓ | Number of months analyzed |
| `analysis_period.years` | `5.08` | number | ✓ | Years as decimal |
| `benchmark_analysis` | `{...}` | object | ✓ | Benchmark comparison metrics |
| `benchmark_analysis.alpha_annual` | `8.47` | number | ✓ | Annual alpha vs benchmark (%) |
| `benchmark_analysis.beta` | `1.119` | number | ✓ | Market beta |
| `benchmark_analysis.excess_return` | `11.03` | number | ✓ | Excess return vs benchmark (%) |
| `benchmark_analysis.r_squared` | `0.822` | number | ✓ | Correlation coefficient squared |
| `benchmark_analysis.benchmark_ticker` | `"SPY"` | string | ✓ | Benchmark identifier |
| `benchmark_comparison` | `{...}` | object | ✓ | Side-by-side comparison |
| `benchmark_comparison.portfolio_return` | `25.87` | number | ✓ | Portfolio annualized return (%) |
| `benchmark_comparison.benchmark_return` | `14.84` | number | ✓ | Benchmark annualized return (%) |
| `benchmark_comparison.portfolio_volatility` | `20.06` | number | ✓ | Portfolio volatility (%) |
| `benchmark_comparison.benchmark_volatility` | `16.26` | number | ✓ | Benchmark volatility (%) |
| `benchmark_comparison.portfolio_sharpe` | `1.157` | number | ✓ | Portfolio Sharpe ratio |
| `benchmark_comparison.benchmark_sharpe` | `0.749` | number | ✓ | Benchmark Sharpe ratio |
| `returns` | `{...}` | object | ✓ | Return metrics |
| `returns.total_return` | `222.06` | number | ✓ | Total cumulative return (%) |
| `returns.annualized_return` | `25.87` | number | ✓ | Annualized return (%) |
| `returns.best_month` | `17.77` | number | ✓ | Best monthly return (%) |
| `returns.worst_month` | `-10.35` | number | ✓ | Worst monthly return (%) |
| `returns.win_rate` | `63.9` | number | ✓ | Percentage of positive months |
| `returns.positive_months` | `39` | integer | ✓ | Count of positive months |
| `returns.negative_months` | `22` | integer | ✓ | Count of negative months |
| `risk_metrics` | `{...}` | object | ✓ | Risk measurements |
| `risk_metrics.volatility` | `20.06` | number | ✓ | Annualized volatility (%) |
| `risk_metrics.maximum_drawdown` | `-22.67` | number | ✓ | Maximum drawdown (%) |
| `risk_metrics.downside_deviation` | `17.61` | number | ✓ | Downside deviation (%) |
| `risk_metrics.tracking_error` | `8.67` | number | ✓ | Tracking error vs benchmark (%) |
| `risk_adjusted_returns` | `{...}` | object | ✓ | Risk-adjusted metrics |
| `risk_adjusted_returns.sharpe_ratio` | `1.157` | number | ✓ | Sharpe ratio |
| `risk_adjusted_returns.sortino_ratio` | `1.318` | number | ✓ | Sortino ratio |
| `risk_adjusted_returns.information_ratio` | `1.271` | number | ✓ | Information ratio |
| `risk_adjusted_returns.calmar_ratio` | `1.141` | number | ✓ | Calmar ratio |
| `monthly_stats` | `{...}` | object | ✓ | Monthly statistics |
| `monthly_stats.average_monthly_return` | `2.1` | number | ✓ | Average monthly return (%) |
| `monthly_stats.average_win` | `5.6` | number | ✓ | Average winning month (%) |
| `monthly_stats.average_loss` | `-4.12` | number | ✓ | Average losing month (%) |
| `monthly_stats.win_loss_ratio` | `1.36` | number | ✓ | Win/loss ratio |
| `monthly_returns` | `{...}` | object | ✓ | Monthly return time series |
| `monthly_returns["2020-06-30"]` | `0.0249` | number | ✓ | Monthly return (decimal) |
| `risk_free_rate` | `2.65` | number | ✓ | Risk-free rate used (%) |
| `performance_category` | `"good"` | string | ✓ | Performance classification |
| `portfolio_file` | `"CURRENT_PORTFOLIO.yaml"` | string | ✓ | Source portfolio file |
| `portfolio_name` | `"CURRENT_PORTFOLIO"` | string | ✓ | Portfolio name |
| `position_count` | `14` | integer | ✓ | Number of positions |
| `display_formatting` | `{...}` | object | ✓ | UI formatting metadata |
| `display_formatting.performance_category_emoji` | `"🟡"` | string | ✓ | Emoji for performance level |
| `display_formatting.performance_category_formatted` | `"🟡 GOOD: Solid performance..."` | string | ✓ | Formatted category text |
| `display_formatting.section_headers` | `["📈 RETURN METRICS", ...]` | array[string] | ✓ | CLI section headers |
| `enhanced_key_insights` | `["• Outperforming benchmark...", ...]` | array[string] | ✓ | Bullet-point insights |
| `key_insights` | `["• Strong alpha generation...", ...]` | array[string] | ✓ | Key insights |
| **Portfolio Metadata** |
| `analyzed_at` | `"2025-08-06T20:02:43.604727+00:00"` | string (ISO datetime) | ✓ | Analysis timestamp |
| `name` | `"CURRENT_PORTFOLIO"` | string | ✓ | Portfolio name |
| `source` | `"database"` | string | ✓ | Data source |
| `user_id` | `1` | integer | ✓ | User identifier |
| **Summary** |
| `analysis_years` | `5.08` | number | ✓ | Analysis period in years |
| `annualized_return` | `25.87` | number | ✓ | Key return metric |
| `max_drawdown` | `-22.67` | number | ✓ | Key risk metric |
| `sharpe_ratio` | `1.157` | number | ✓ | Key risk-adjusted metric |
| `total_return` | `222.06` | number | ✓ | Total return |
| `volatility` | `20.06` | number | ✓ | Volatility |
| `win_rate` | `63.9` | number | ✓ | Win rate |

---

## RiskScoreResult

### High-Level Structure
- **Root keys**: `analysis_date`, `formatted_report`, `limits_analysis`, `portfolio_analysis`, `portfolio_metadata`, `risk_score`, `success`, `summary`
- **CLI representation**: Risk score with component breakdown and limit violations
- **Primary data container**: `risk_score` and `portfolio_analysis` objects

### Raw Keys Inventory

| Key | Example Value | Type | Required? | Notes |
|-----|---------------|------|-----------|-------|
| **Root Level** |
| `analysis_date` | `"2025-08-06T16:02:43"` | string (ISO datetime) | ✓ | Analysis timestamp |
| `formatted_report` | `"📊 PORTFOLIO RISK SCORE..."` | string | ✓ | CLI formatted output |
| `limits_analysis` | `{...}` | object | ✓ | Risk limit violations analysis |
| `portfolio_analysis` | `{...}` | object | ✓ | Detailed portfolio risk analysis |
| `portfolio_metadata` | `{...}` | object | ✓ | Portfolio metadata |
| `risk_score` | `{...}` | object | ✓ | Risk scoring results |
| `success` | `true` | boolean | ✓ | Operation success flag |
| `summary` | `{...}` | object | ✓ | Summary metrics |
| **Risk Score** |
| `score` | `87.5` | number | ✓ | Overall risk score (0-100) |
| `category` | `"Good"` | string | ✓ | Risk category |
| `component_scores` | `{...}` | object | ✓ | Individual risk component scores |
| `component_scores.factor_risk` | `100` | integer | ✓ | Factor exposure risk score |
| `component_scores.concentration_risk` | `75` | integer | ✓ | Concentration risk score |
| `component_scores.volatility_risk` | `75` | integer | ✓ | Volatility risk score |
| `component_scores.sector_risk` | `100` | integer | ✓ | Sector concentration score |
| `potential_losses` | `{...}` | object | ✓ | Potential loss estimates |
| `potential_losses.max_loss_limit` | `0.25` | number | ✓ | Maximum loss tolerance |
| `potential_losses.factor_risk` | `0.15367923` | number | ✓ | Factor-related potential loss |
| `potential_losses.concentration_risk` | `0.20387414` | number | ✓ | Concentration-related loss |
| `potential_losses.volatility_risk` | `0.20062137` | number | ✓ | Volatility-related loss |
| `potential_losses.sector_risk` | `0.09790105` | number | ✓ | Sector-related loss |
| `details` | `{...}` | object | ✓ | Additional scoring details |
| `details.leverage_ratio` | `1.0` | number | ✓ | Portfolio leverage |
| `details.max_loss_limit` | `0.25` | number | ✓ | Loss tolerance setting |
| `details.excess_ratios` | `{...}` | object | ✓ | Risk excess ratios |
| `interpretation` | `{...}` | object | ✓ | Human-readable interpretation |
| `interpretation.summary` | `"Portfolio has acceptable disruption risk"` | string | ✓ | Summary text |
| `interpretation.details` | `["Most potential losses...", ...]` | array[string] | ✓ | Detailed interpretations |
| `recommendations` | `[]` | array[string] | ✓ | Action recommendations |
| `risk_factors` | `[]` | array[string] | ✓ | Identified risk factors |
| **Limits Analysis** |
| `limit_violations` | `{...}` | object | ✓ | Violation counts by category |
| `limit_violations.total` | `4` | integer | ✓ | Total violations |
| `limit_violations.factor_betas` | `2` | integer | ✓ | Factor beta violations |
| `limit_violations.concentration` | `1` | integer | ✓ | Concentration violations |
| `limit_violations.volatility` | `0` | integer | ✓ | Volatility violations |
| `limit_violations.variance_contributions` | `1` | integer | ✓ | Variance contribution violations |
| `limit_violations.leverage` | `0` | integer | ✓ | Leverage violations |
| `risk_factors` | `["High market exposure: β=1.18...", ...]` | array[string] | ✓ | Risk factor descriptions |
| `recommendations` | `["Reduce market exposure...", ...]` | array[string] | ✓ | Specific recommendations |
| **Portfolio Analysis** |
| `allocations` | `[{...}, ...]` | array[object] | ✓ | Position allocation data |
| `allocations[0].Portfolio Weight` | `0.25484267` | number | ✓ | Portfolio weight (decimal) |
| `allocations[0].Equal Weight` | `0.07142857` | number | ✓ | Equal weight reference |
| `allocations[0].Eq Diff` | `0.1834141` | number | ✓ | Difference from equal weight |
| `portfolio_factor_betas` | `{...}` | object | ✓ | Portfolio-level factor exposures |
| `portfolio_factor_betas.market` | `1.18226461` | number | ✓ | Market beta |
| `portfolio_factor_betas.momentum` | `-0.32776906` | number | ✓ | Momentum beta |
| `portfolio_factor_betas.value` | `0.13249038` | number | ✓ | Value beta |
| `portfolio_factor_betas.industry` | `0.90826978` | number | ✓ | Industry beta |
| `portfolio_factor_betas.subindustry` | `0.7971948` | number | ✓ | Sub-industry beta |
| `volatility_annual` | `0.20062137` | number | ✓ | Annual volatility (decimal) |
| `volatility_monthly` | `0.0579144` | number | ✓ | Monthly volatility (decimal) |
| `herfindahl` | `0.19542678` | number | ✓ | Herfindahl concentration index |
| `risk_contributions` | `{...}` | object | ✓ | Risk contribution by asset |
| `risk_contributions.DSU` | `0.00686898` | number | ✓ | Asset risk contribution |
| `euler_variance_pct` | `{...}` | object | ✓ | Variance contribution percentages |
| `euler_variance_pct.DSU` | `0.11860572` | number | ✓ | Percentage of total variance |
| `variance_decomposition` | `{...}` | object | ✓ | Risk decomposition |
| `variance_decomposition.portfolio_variance` | `0.01154914` | number | ✓ | Total portfolio variance |
| `variance_decomposition.factor_variance` | `0.00719193` | number | ✓ | Factor-driven variance |
| `variance_decomposition.idiosyncratic_variance` | `0.00435721` | number | ✓ | Stock-specific variance |
| `variance_decomposition.factor_pct` | `0.62272411` | number | ✓ | Factor variance percentage |
| `variance_decomposition.idiosyncratic_pct` | `0.37727589` | number | ✓ | Idiosyncratic percentage |
| `correlation_matrix` | `[{...}, ...]` | array[object] | ✓ | Asset correlation matrix |
| `covariance_matrix` | `[{...}, ...]` | array[object] | ✓ | Asset covariance matrix |
| `industry_variance` | `{...}` | object | ✓ | Industry risk analysis |
| `industry_variance.absolute` | `{...}` | object | ✓ | Absolute industry variances |
| `industry_variance.percent_of_portfolio` | `{...}` | object | ✓ | Industry variance percentages |
| `industry_variance.per_industry_group_beta` | `{...}` | object | ✓ | Industry group exposures |

---

## RiskAnalysisResult

### High-Level Structure
- **Root keys**: `portfolio_metadata`, `risk_results`, `success`
- **CLI representation**: Comprehensive risk analysis with position allocations, factor betas, and risk decomposition
- **Primary data container**: `risk_results` object containing all risk analytics

### Raw Keys Inventory

| Key | Example Value | Type | Required? | Notes |
|-----|---------------|------|-----------|-------|
| **Root Level** |
| `portfolio_metadata` | `{...}` | object | ✓ | Portfolio identification |
| `risk_results` | `{...}` | object | ✓ | Main risk analysis container |
| `success` | `true` | boolean | ✓ | Operation success flag |
| **Risk Results** |
| `analysis_date` | `"2025-08-06T16:02:43.357139"` | string (ISO datetime) | ✓ | Analysis timestamp |
| `allocations` | `{...}` | object | ✓ | Position allocation breakdown |
| `allocations.Portfolio Weight` | `{...}` | object | ✓ | Current portfolio weights |
| `allocations.Equal Weight` | `{...}` | object | ✓ | Equal weight reference |
| `allocations.Eq Diff` | `{...}` | object | ✓ | Difference from equal weight |
| `allocations.Portfolio Weight.DSU` | `0.2548426706290927` | number | ✓ | Asset weight (decimal) |
| `df_stock_betas` | `{...}` | object | ✓ | Individual stock factor betas |
| `df_stock_betas.market` | `{...}` | object | ✓ | Market betas by asset |
| `df_stock_betas.momentum` | `{...}` | object | ✓ | Momentum betas by asset |
| `df_stock_betas.value` | `{...}` | object | ✓ | Value betas by asset |
| `df_stock_betas.industry` | `{...}` | object | ✓ | Industry betas by asset |
| `df_stock_betas.subindustry` | `{...}` | object | ✓ | Sub-industry betas by asset |
| `df_stock_betas.market.DSU` | `0.6536579235547335` | number | ✓ | Asset's market beta |
| `factor_proxies` | `{...}` | object | ✓ | Factor proxy mappings |
| `factor_proxies.DSU` | `{...}` | object | ✓ | Asset's factor proxies |
| `factor_proxies.DSU.market` | `"SPY"` | string | ✓ | Market proxy ticker |
| `factor_proxies.DSU.momentum` | `"MTUM"` | string | ✓ | Momentum proxy ticker |
| `factor_proxies.DSU.value` | `"IWD"` | string | ✓ | Value proxy ticker |
| `factor_proxies.DSU.industry` | `"DSU"` | string | ✓ | Industry proxy ticker |
| `factor_proxies.DSU.subindustry` | `[]` | array[string] | ✓ | Sub-industry proxy tickers |
| `correlation_matrix` | `{...}` | object | ✓ | Asset correlation matrix |
| `covariance_matrix` | `{...}` | object | ✓ | Asset covariance matrix |
| `asset_vol_summary` | `{...}` | object | ✓ | Asset volatility decomposition |
| `asset_vol_summary.Vol A` | `{...}` | object | ✓ | Total asset volatilities |
| `asset_vol_summary.Idio Vol A` | `{...}` | object | ✓ | Idiosyncratic volatilities |
| `asset_vol_summary.Weighted Vol A` | `{...}` | object | ✓ | Weight-adjusted volatilities |
| `asset_vol_summary.Weighted Idio Vol A` | `{...}` | object | ✓ | Weight-adjusted idiosyncratic vol |
| `asset_vol_summary.Weighted Idio Var` | `{...}` | object | ✓ | Weight-adjusted idiosyncratic variance |
| `beta_checks` | `[{...}, ...]` | array[object] | ✓ | Factor beta limit checks |
| `beta_checks[0].factor` | `"market"` | string | ✓ | Factor name |
| `beta_checks[0].portfolio_beta` | `1.18226461` | number | ✓ | Portfolio beta value |
| `beta_checks[0].max_allowed_beta` | `0.76930667` | number | ✓ | Beta limit |
| `beta_checks[0].buffer` | `-0.41295793` | number | ✓ | Buffer to limit |
| `beta_checks[0].pass` | `false` | boolean | ✓ | Limit compliance |
| `beta_exposure_checks_table` | `[{...}, ...]` | array[object] | ✓ | Formatted beta check table |
| `beta_exposure_checks_table[0].factor` | `"Market"` | string | ✓ | Display factor name |
| `beta_exposure_checks_table[0].portfolio_beta` | `1.182` | number | ✓ | Rounded beta value |
| `beta_exposure_checks_table[0].max_allowed` | `0.769` | number | ✓ | Rounded limit |
| `beta_exposure_checks_table[0].buffer` | `-0.413` | number | ✓ | Rounded buffer |
| `beta_exposure_checks_table[0].pass` | `false` | boolean | ✓ | Pass/fail status |
| `beta_exposure_checks_table[0].status` | `"FAIL"` | string | ✓ | Status text |
| `expected_returns` | `null` | null | ○ | Expected returns (optional) |

---

## StockAnalysisResult (DirectStockResult)

### High-Level Structure
- **Root keys**: `data`, `endpoint`, `success`, `summary`
- **CLI representation**: Simple stock analysis with volatility and market regression metrics
- **Primary data container**: `data` object

### Raw Keys Inventory

| Key | Example Value | Type | Required? | Notes |
|-----|---------------|------|-----------|-------|
| **Root Level** |
| `data` | `{...}` | object | ✓ | Main data container |
| `endpoint` | `"direct/stock"` | string | ✓ | API endpoint identifier |
| `success` | `true` | boolean | ✓ | Operation success flag |
| `summary` | `{...}` | object | ✓ | Summary information |
| **Data** |
| `analysis_metadata` | `{...}` | object | ✓ | Analysis metadata |
| `analysis_metadata.analysis_date` | `"2025-08-06 16:03:43"` | string (YYYY-MM-DD HH:MM:SS) | ✓ | Analysis timestamp |
| `analysis_metadata.has_factor_analysis` | `false` | boolean | ✓ | Factor analysis availability |
| `analysis_metadata.num_factors` | `0` | integer | ✓ | Number of factors analyzed |
| `analysis_period` | `{...}` | object | ✓ | Analysis time period |
| `analysis_period.start_date` | `"2023-01-01"` | string (YYYY-MM-DD) | ✓ | Start date |
| `analysis_period.end_date` | `"2023-12-31"` | string (YYYY-MM-DD) | ✓ | End date |
| `analysis_type` | `"simple_market_regression"` | string | ✓ | Type of analysis performed |
| `benchmark` | `"SPY"` | string | ✓ | Benchmark ticker |
| `ticker` | `"AAPL"` | string | ✓ | Stock ticker analyzed |
| `formatted_report` | `"Stock Analysis Report: AAPL..."` | string | ✓ | CLI formatted output |
| `volatility_metrics` | `{...}` | object | ✓ | Volatility measurements |
| `volatility_metrics.monthly_vol` | `0.06337752` | number | ✓ | Monthly volatility (decimal) |
| `volatility_metrics.annual_vol` | `0.21954617` | number | ✓ | Annual volatility (decimal) |
| `risk_metrics` | `{...}` | object | ✓ | Risk measurements |
| `risk_metrics.alpha` | `0.0098693` | number | ✓ | Monthly alpha |
| `risk_metrics.beta` | `1.2237561` | number | ✓ | Market beta |
| `risk_metrics.r_squared` | `0.65787653` | number | ✓ | R-squared |
| `risk_metrics.idio_vol_m` | `0.03707035` | number | ✓ | Idiosyncratic volatility (monthly) |
| `raw_data` | `{...}` | object | ✓ | Raw computation results |
| `raw_data.result` | `{...}` | object | ✓ | Nested result object |
| **Summary** |
| `analysis_type` | `"stock"` | string | ✓ | Analysis type |
| `data_quality` | `"direct_access"` | string | ✓ | Data quality indicator |
| `endpoint` | `"direct/stock"` | string | ✓ | Endpoint used |

---

## OptimizationResult (DirectOptimizationResult)

### High-Level Structure
- **Root keys**: `data`, `endpoint`, `success`, `summary`
- **CLI representation**: Optimization results with weights and risk checks
- **Primary data container**: `data` object

### Raw Keys Inventory

| Key | Example Value | Type | Required? | Notes |
|-----|---------------|------|-----------|-------|
| **Root Level** |
| `data` | `{...}` | object | ✓ | Main data container |
| `endpoint` | `"direct/optimize/min-variance"` | string | ✓ | API endpoint |
| `success` | `true` | boolean | ✓ | Operation success flag |
| `summary` | `{...}` | object | ✓ | Summary information |
| **Data** |
| `analysis_type` | `"min_variance"` | string | ✓ | Optimization type |
| `formatted_report` | `"Optimization Results: min_variance - 22 positions"` | string | ✓ | CLI output |
| `optimization_metadata` | `{...}` | object | ✓ | Optimization metadata |
| `optimization_metadata.analysis_date` | `"2025-08-06 16:03:44"` | string (YYYY-MM-DD HH:MM:SS) | ✓ | Analysis timestamp |
| `optimization_metadata.optimization_type` | `"minimum_variance"` | string | ✓ | Optimization type |
| `optimization_metadata.total_positions` | `22` | integer | ✓ | Total available positions |
| `optimization_metadata.active_positions` | `10` | integer | ✓ | Positions with non-zero weights |
| `optimization_metadata.portfolio_file` | `"portfolio.yaml"` | string | ✓ | Source portfolio file |
| `optimization_metadata.original_weights` | `{...}` | object | ✓ | Original portfolio weights |
| `optimized_weights` | `{...}` | object | ✓ | Optimized position weights |
| `optimized_weights.SGOV` | `0.39999999` | number | ✓ | Optimal weight (decimal) |
| `optimized_weights.GLD` | `0.16465565` | number | ✓ | Optimal weight (decimal) |
| `optimized_weights.COIN` | `1e-08` | number | ✓ | Near-zero weight |
| `optimal_weights` | `null` | null | ○ | Alternative weights field |
| `optimization_metrics` | `null` | null | ○ | Optimization performance metrics |
| `risk_analysis` | `{...}` | object | ✓ | Risk constraint analysis |
| `risk_analysis.risk_passes` | `false` | boolean | ✓ | Overall risk compliance |
| `risk_analysis.risk_checks` | `[{...}, ...]` | array[object] | ✓ | Individual risk checks |
| `risk_analysis.risk_checks[0].Metric` | `"Volatility"` | string | ✓ | Risk metric name |
| `risk_analysis.risk_checks[0].Actual` | `0.02374506` | number | ✓ | Actual value |
| `risk_analysis.risk_checks[0].Limit` | `0.4` | number | ✓ | Limit value |
| `risk_analysis.risk_checks[0].Pass` | `true` | boolean | ✓ | Pass/fail status |
| `risk_analysis.risk_violations` | `[{...}, ...]` | array[object] | ✓ | Failed constraints |
| `risk_analysis.risk_limits` | `{...}` | object | ✓ | Risk limit definitions |
| `risk_analysis.risk_limits.portfolio_limits` | `{...}` | object | ✓ | Portfolio-level limits |
| `risk_analysis.risk_limits.concentration_limits` | `{...}` | object | ✓ | Concentration limits |
| `risk_analysis.risk_limits.variance_limits` | `{...}` | object | ✓ | Variance contribution limits |
| `beta_analysis` | `{...}` | object | ✓ | Factor beta analysis |
| `beta_analysis.beta_passes` | `false` | boolean | ✓ | Overall beta compliance |
| `beta_analysis.beta_checks` | `[{...}, ...]` | array[object] | ✓ | Beta limit checks |
| `beta_analysis.beta_checks[0].portfolio_beta` | `0.20445358` | number | ✓ | Portfolio beta |
| `beta_analysis.beta_checks[0].max_allowed_beta` | `0.6678733` | number | ✓ | Beta limit |
| `beta_analysis.beta_checks[0].buffer` | `0.46341973` | number | ✓ | Buffer to limit |
| `beta_analysis.beta_checks[0].pass` | `true` | boolean | ✓ | Pass/fail |
| `beta_analysis.beta_violations` | `[{...}, ...]` | array[object] | ✓ | Beta violations |
| `raw_tables` | `{...}` | object | ✓ | Tabular result data |
| `raw_tables.weights` | `{...}` | object | ✓ | Weight table |
| `raw_tables.risk_table` | `{...}` | object | ✓ | Risk metrics table |
| `raw_tables.beta_table` | `{...}` | object | ✓ | Beta analysis table |
| **Summary** |
| `analysis_type` | `"min_variance"` | string | ✓ | Analysis type |
| `data_quality` | `"direct_access"` | string | ✓ | Data quality |
| `endpoint` | `"direct/optimization"` | string | ✓ | Endpoint category |

---

## InterpretationResult (GPT Analysis)

### High-Level Structure
- **Root keys**: Same as RiskAnalysisResult but with additional GPT interpretation
- **CLI representation**: Natural language analysis and recommendations with full diagnostic data
- **Primary data container**: Full risk analysis plus human-readable interpretation

### Additional Keys Beyond RiskAnalysisResult

| Key | Example Value | Type | Required? | Notes |
|-----|---------------|------|-----------|-------|
| **Additional Interpretation Content** |
| `formatted_report` | `"=== GPT Portfolio Interpretation ===..."` | string | ✓ | Natural language analysis |
| (Contains full RiskAnalysisResult structure plus interpretation text) |

---

## DirectPerformanceResult

### High-Level Structure
- **Root keys**: `data`, `endpoint`, `risk_limits_metadata`, `success`, `summary`
- **CLI representation**: Similar to PerformanceResult but in direct API format
- **Primary data container**: `data` object with enhanced formatting

### Key Differences from PerformanceResult

| Key | Example Value | Type | Required? | Notes |
|-----|---------------|------|-----------|-------|
| **Root Level** |
| `endpoint` | `"direct/performance"` | string | ✓ | API endpoint identifier |
| `risk_limits_metadata` | `null` | null | * | Risk limits configuration |
| **Enhanced Data Fields** |
| `data.display_formatting` | `{...}` | object | ✓ | **→ DisplayFormattingSchema** |
| `data.enhanced_key_insights` | `["• Outperforming benchmark...", ...]` | array[string] | ✓ | Enhanced insights with bullets |
| `data.display_formatting.performance_category_description` | `"Solid performance with reasonable risk"` | string | ✓ | Category description |
| `data.display_formatting.performance_category_emoji` | `"🟡"` | string | ✓ | Performance emoji |
| `data.display_formatting.performance_category_formatted` | `"🟡 GOOD: Solid performance..."` | string | ✓ | Formatted display text |
| `data.display_formatting.section_headers` | `["📈 RETURN METRICS", ...]` | array[string] | ✓ | CLI section headers with emojis |
| `data.display_formatting.table_structure` | `{...}` | object | ✓ | **→ TableStructureSchema** |
| `data.display_formatting.table_structure.comparison_table` | `{...}` | object | ✓ | Table layout definition |
| `data.display_formatting.table_structure.comparison_table.columns` | `["Metric", "Portfolio", "Benchmark"]` | array[string] | ✓ | Table column headers |
| `data.display_formatting.table_structure.comparison_table.rows` | `["Return", "Volatility", "Sharpe Ratio"]` | array[string] | ✓ | Table row headers |

---

## WhatIfResult (DirectWhatIfResult)

### High-Level Structure
- **Root keys**: `data`, `endpoint`, `success`, `summary`  
- **CLI representation**: Before/after comparison of portfolio changes
- **Primary data container**: `data` object with change analysis

### Raw Keys Inventory

| Key | Example Value | Type | Required? | Notes |
|-----|---------------|------|-----------|-------|
| **Root Level** |
| `data` | `{...}` | object | ✓ | Main data container |
| `endpoint` | `"direct/what-if"` | string | ✓ | API endpoint |
| `success` | `true` | boolean | ✓ | Operation success flag |
| `summary` | `{...}` | object | ✓ | Summary information |
| **Data** |
| `formatted_report` | `"📊 Portfolio Weights — Before vs After..."` | string | ✓ | CLI output with changes |
| (Contains before/after risk analysis comparison) |

---

## Component Schema Suggestions

Based on the analysis, the following reusable component schemas are recommended:

### 1. **AnalysisPeriodSchema** 
Used in: PerformanceResult, StockAnalysisResult
```python
class AnalysisPeriodSchema(Schema):
    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True) 
    total_months = fields.Integer(required=True)
    years = fields.Float(required=True)
```

### 2. **PortfolioMetadataSchema**
Used in: PerformanceResult, RiskScoreResult, RiskAnalysisResult
```python
class PortfolioMetadataSchema(Schema):
    analyzed_at = fields.DateTime(required=True)
    name = fields.String(required=True)
    source = fields.String(required=True)
    user_id = fields.Integer(required=True)
```

### 3. **ReturnsSchema**
Used in: PerformanceResult
```python
class ReturnsSchema(Schema):
    total_return = fields.Float(required=True)
    annualized_return = fields.Float(required=True)
    best_month = fields.Float(required=True)
    worst_month = fields.Float(required=True)
    win_rate = fields.Float(required=True)
    positive_months = fields.Integer(required=True)
    negative_months = fields.Integer(required=True)
```

### 4. **RiskMetricsSchema**
Used in: PerformanceResult, StockAnalysisResult
```python
class RiskMetricsSchema(Schema):
    volatility = fields.Float(required=True)
    maximum_drawdown = fields.Float(required=True) 
    downside_deviation = fields.Float(required=True)
    tracking_error = fields.Float(required=True)
```

### 5. **BenchmarkAnalysisSchema**
Used in: PerformanceResult
```python
class BenchmarkAnalysisSchema(Schema):
    alpha_annual = fields.Float(required=True)
    benchmark_ticker = fields.String(required=True)
    beta = fields.Float(required=True)
    excess_return = fields.Float(required=True)
    r_squared = fields.Float(required=True)
```

### 6. **FactorBetasSchema**
Used in: RiskScoreResult, RiskAnalysisResult
```python
class FactorBetasSchema(Schema):
    market = fields.Float(required=True)
    momentum = fields.Float(required=True) 
    value = fields.Float(required=True)
    industry = fields.Float(required=True)
    subindustry = fields.Float(required=True)
```

### 7. **RiskCheckSchema**
Used in: OptimizationResult, RiskScoreResult  
```python
class RiskCheckSchema(Schema):
    metric = fields.String(required=True)
    actual = fields.Float(required=True)
    limit = fields.Float(required=True)
    pass_check = fields.Boolean(required=True, data_key="Pass")
```

### 8. **BetaCheckSchema**
Used in: RiskAnalysisResult, OptimizationResult
```python
class BetaCheckSchema(Schema):
    factor = fields.String(required=True)
    portfolio_beta = fields.Float(required=True)
    max_allowed_beta = fields.Float(required=True)
    buffer = fields.Float(required=True)
    pass_check = fields.Boolean(required=True, data_key="pass")
```