# Factor Intelligence Engine - Design Document

> **Status:** ✅ Backend fully implemented — core engine, service, API, DB, admin tooling all complete.
> Frontend integration and Phase 3 advanced features (regime analysis, multi-objective optimization) not started.
>
> Implementation files: `core/factor_intelligence.py`, `services/factor_intelligence_service.py`, `routes/factor_intelligence.py`, `models/factor_intelligence_models.py`, `core/result_objects.py` (FactorCorrelationResult, FactorPerformanceResult, OffsetRecommendationResult)

## Problem Statement

Our risk analysis system effectively identifies portfolio overexposures (e.g., "too much real estate exposure") and can simulate what-if scenarios, but lacks the market intelligence needed to make sophisticated offset recommendations.

### Current State
- ✅ Portfolio risk analysis identifies specific overexposures
- ✅ Generic AI recommendations for "risk-reducing" assets
- ✅ Individual stock risk lookup functionality  
- ✅ What-if simulation capabilities for testing replacements

### The Gap
We're missing a **market-wide factor intelligence layer** that provides:
- Overall view of industry factors and their relationships
- Correlation patterns between factors
- Risk/return profiles of different factors
- Market context for intelligent offset recommendations

### Current Problem Example
**Scenario**: Risk analysis identifies excessive real estate exposure
**Current Response**: AI suggests generic "low-risk" assets like XLU (utilities) and XLP (consumer staples)
**Problem**: These are generic risk-reduction suggestions, not targeted offsets that specifically hedge against real estate risk

## High-Level Solution: Factor Intelligence Engine

### Vision
Build a **Factor Intelligence Engine** that serves as the foundational market context layer, enabling:

1. **Algorithmic Offset Recommendations**
   - Direct computational suggestions based on correlation patterns
   - Factor relationship analysis for targeted hedging

2. **AI-Enhanced Recommendations** 
   - Rich market context for Claude integration
   - Sophisticated reasoning about market relationships vs. generic risk reduction

### Transformation Goal
**From**: "You have too much real estate exposure" → "Here are some low-risk assets"

**To**: "You have too much real estate exposure" → "Based on current market correlations, utilities and consumer staples have -0.3 correlation with real estate, while tech has +0.1 correlation during market stress periods. Consider rebalancing toward defensive sectors that historically hedge real estate downturns."

## Current System Assessment

### Existing Factor Infrastructure ✅
Your system already has significant factor intelligence components:

**1. Factor Universe Mapping (EXISTING)**
- **Market Factors**: Exchange-based proxies (SPY, ACWX, EEM, etc.) via `exchange_etf_proxies.yaml`
- **Style Factors**: Momentum (MTUM, IMTM, etc.) and Value (IWD, EFV, etc.) per exchange
- **Industry Factors**: ~16 industry-to-ETF mappings via `industry_to_etf.yaml`
- **Sub-industry Factors**: Peer ticker groups for granular analysis
- **Database Storage**: `factor_proxies` table with per-portfolio factor assignments

**2. Correlation Calculation (EXISTING)**
- **Portfolio-level**: Position-to-position correlation matrix in risk analysis
- **Factor Regression**: Multi-factor beta calculations per stock
- **Performance Module**: Correlation analysis capabilities

**3. Risk/Return Analysis (EXISTING)**
- **Performance Analysis**: Returns, volatility, drawdown, Sharpe ratios
- **Stock Risk Profiles**: Individual ticker risk characteristics
- **Factor Exposures**: Beta coefficients for market/momentum/value/industry factors

### What's Missing - The Intelligence Gap

**1. Factor-to-Factor Relationships**
- No correlation matrix between **factors themselves** (only between positions)
- Missing cross-factor correlation patterns (e.g., how does real estate correlate with utilities?)
- No factor regime analysis (how correlations change during market stress)

**2. Market-Wide Factor Intelligence**
- No centralized "factor universe view" for offset recommendations
- Missing factor risk/return profiles at the **factor level** (vs. individual stock level)
- No factor-based hedging intelligence

**3. Offset Recommendation Engine**
- Current AI gets generic suggestions, not factor-intelligent recommendations
- No systematic way to find factors that offset specific overexposures

## Enhanced Core Components Needed

### 1. Factor Correlation Matrix Engine
- **Factor-to-Factor Correlations**: Build correlation matrix between all factor proxies
- **Dynamic Correlation Tracking**: How factor relationships change over time/regimes
- **Correlation-Based Offset Logic**: Identify negative/low correlation factors for hedging

### 2. Factor Intelligence Database
- **Factor Performance Profiles**: Risk/return characteristics of each factor proxy
- **Factor Relationship Mapping**: Which factors hedge vs. amplify each other
- **Market Regime Analysis**: How factor relationships change during different market conditions

### 3. Intelligent Offset Recommendation System
- **Correlation-Based Suggestions**: "Real estate overexposed? Consider utilities (-0.3 correlation)"
- **AI Context Enhancement**: Provide factor intelligence to Claude for sophisticated reasoning
- **Dynamic Rebalancing Logic**: Algorithmic suggestions based on current factor relationships

### 4. Core Data Processing Functions

#### `fetch_factor_universe() -> Dict[str, List[str]]`

**Purpose**: Load complete ETF universe from multiple data sources with database-first pattern.

**Implementation**:
```python
@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)
def fetch_factor_universe() -> Dict[str, List[str]]:
    """
    Fetch complete factor ETF universe categorized by asset class.

    Returns:
        Dict mapping asset class to ETF list:
        {
            "industry": ["XLK", "XLV", "XLF", "XLY", "XLP", ...],
            "style": ["MTUM", "IWD", "IMTM", "EFV", ...],
            "market": ["SPY", "ACWX", "EEM", "VTI", ...],
            "fixed_income": ["AGG", "TLT", "SHY", "IEI", ...],
            "commodity": ["GLD", "SLV", "DBC", "USO", ...],
            "crypto": ["BITO", "GBTC", ...],
            "cash": ["BIL", "SGOV", "SHV", ...]
        }
    """
    universe = {}

    # 1. Load from database (primary source)
    with get_db_session() as conn:
        db_client = DatabaseClient(conn)

        # Industry ETFs from industry_proxies table (DB-first)
        industry_map = db_client.get_industry_mappings()
        universe["industry"] = list(set(industry_map.values()))

        # Exchange-based ETFs (market/style) from exchange_proxies
        exchange_map = db_client.get_exchange_mappings()
        style_etfs = []
        market_etfs = []
        for exchange_data in exchange_map.values():
            # DB rows are stored by factor_type keys (e.g., 'market','momentum','value')
            market_etfs.extend([exchange_data.get("market")])
            style_etfs.extend([exchange_data.get("momentum"), exchange_data.get("value")])
        universe["market"] = [etf for etf in set(market_etfs) if etf]
        universe["style"] = [etf for etf in set(style_etfs) if etf]

        # Asset ETFs from asset_etf_proxies table (fixed_income, commodity, crypto)
        asset_proxies = db_client.get_asset_etf_proxies()
        for asset_class, proxy_mapping in asset_proxies.items():
            universe[asset_class] = list(proxy_mapping.values())

    # 2. YAML fallback for missing categories or empty DB results
    if not universe.get("industry"):
        industry_yaml = load_industry_etf_map()  # from proxy_builder.py
        universe["industry"] = list(set(industry_yaml.values()))

    if not universe.get("market") or not universe.get("style"):
        exchange_yaml = load_exchange_proxy_map()  # from proxy_builder.py
        if not universe.get("market"):
            universe["market"] = [data["market"] for data in exchange_yaml.values() if "market" in data]
        if not universe.get("style"):
            style_etfs = []
            for data in exchange_yaml.values():
                style_etfs.extend([data.get("momentum"), data.get("value")])
            universe["style"] = [etf for etf in set(style_etfs) if etf]

    # 3. Cash proxies via DB-first loader, YAML fallback, then minimal set
    cash_etfs = []
    try:
        if 'db_client' in locals() and hasattr(db_client, 'get_cash_mappings'):
            cash_mappings = db_client.get_cash_mappings() or {}
            cash_etfs = list(set(cash_mappings.get("proxy_by_currency", {}).values()))
    except Exception:
        cash_etfs = []
    if not cash_etfs:
        try:
            import yaml
            from pathlib import Path
            cash_yaml = Path("cash_map.yaml")
            if cash_yaml.exists():
                with open(cash_yaml, 'r') as f:
                    cash_data = yaml.safe_load(f)
                if isinstance(cash_data, dict):
                    for mapping in cash_data.values():
                        if isinstance(mapping, str):
                            cash_etfs.append(mapping)
                        elif isinstance(mapping, dict) and 'ticker' in mapping:
                            cash_etfs.append(mapping['ticker'])
        except Exception:
            pass
    if not cash_etfs:
        cash_etfs = ["SGOV", "BIL", "SHV"]
    universe["cash"] = sorted(list(set(cash_etfs)))

    # 4. Apply SecurityTypeService enrichment and validation
    all_etfs = [etf for etf_list in universe.values() for etf in etf_list]
    asset_class_mappings = SecurityTypeService.get_asset_classes(all_etfs, None)

    # 5. Clean and deduplicate per category
    for category in list(universe.keys()):
        tickers = universe.get(category, []) or []
        universe[category] = sorted(list(set(etf for etf in tickers if etf and str(etf).strip())))

    # 6. Minimal fallbacks for non-equity asset classes if empty
    if not universe.get("fixed_income"):
        universe["fixed_income"] = ["SHY", "TLT"]
    if not universe.get("commodity"):
        universe["commodity"] = ["GLD", "DBC"]
    if not universe.get("crypto"):
        universe["crypto"] = ["IBIT"]

    return universe
```

#### `build_factor_returns_panel(etf_universe_hash: str, start_date: str, end_date: str, total_return: bool = True) -> pd.DataFrame`

**Purpose**: Build aligned monthly returns matrix for entire ETF universe with parallel loading.

**Implementation**:
```python
@lru_cache(maxsize=DATA_LOADER_LRU_SIZE)
def build_factor_returns_panel(etf_universe_hash: str, start_date: str, end_date: str, total_return: bool = True) -> pd.DataFrame:
    """
    Build aligned monthly returns panel for all ETFs in universe.

    Args:
        etf_universe_hash: Hash of ETF universe dict (for caching)
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        total_return: Use dividend-adjusted prices if True

    Returns:
        DataFrame with ETFs as columns, month-end dates as index
        Returns are decimal (0.05 = 5% return)
    """
    import concurrent.futures
    from functools import partial
    import pandas as pd
    from data_loader import fetch_monthly_total_return_price, fetch_monthly_close
    from settings import DATA_QUALITY_THRESHOLDS
    from factor_utils import calc_monthly_returns

    # Reconstruct ETF universe from hash (passed separately to maintain cache compatibility)
    etf_universe = fetch_factor_universe()
    all_etfs = []
    for category, etf_list in etf_universe.items():
        all_etfs.extend(etf_list)
    all_etfs = sorted(list(set(all_etfs)))  # Deterministic ordering

    # Configure data fetcher based on total_return preference
    data_fetcher = fetch_monthly_total_return_price if total_return else fetch_monthly_close
    fetch_func = partial(data_fetcher, start_date=start_date, end_date=end_date)

    # Parallel loading with ThreadPoolExecutor
    returns_series = {}
    failed_etfs = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all ETF fetch tasks
        future_to_etf = {executor.submit(fetch_func, etf): etf for etf in all_etfs}

        for future in concurrent.futures.as_completed(future_to_etf):
            etf = future_to_etf[future]
            try:
                prices = future.result()
                if len(prices) > 0:
                    # Calculate monthly returns (prefer shared helper)
                    returns = calc_monthly_returns(prices)
                    if len(returns) >= DATA_QUALITY_THRESHOLDS.get("min_observations_for_returns_calculation", 12):
                        returns_series[etf] = returns
                    else:
                        failed_etfs.append(f"{etf}:insufficient_data")
                else:
                    failed_etfs.append(f"{etf}:no_data")
            except Exception as e:
                # Graceful fallback for individual ETF failures
                if total_return:
                    try:
                        # Fallback to close prices
                        prices = fetch_monthly_close(etf, start_date, end_date)
                        returns = calc_monthly_returns(prices)
                        if len(returns) >= DATA_QUALITY_THRESHOLDS.get("min_observations_for_returns_calculation", 12):
                            returns_series[etf] = returns
                        else:
                            failed_etfs.append(f"{etf}:fallback_insufficient")
                    except:
                        failed_etfs.append(f"{etf}:fallback_failed")
                else:
                    failed_etfs.append(f"{etf}:fetch_error:{str(e)[:50]}")

    # Build aligned DataFrame
    if not returns_series:
        raise ValueError("No ETF data could be loaded for the specified date range")

    returns_panel = pd.DataFrame(returns_series)

    # Optional: forward-fill small gaps (up to 2 periods) to stabilize corr
    returns_panel = returns_panel.fillna(method='ffill', limit=2)

    # Drop ETFs with too many missing values (centralized threshold)
    min_coverage = 0.7  # default; can be lifted to a setting later
    coverage_threshold = int(len(returns_panel) * min_coverage)
    returns_panel = returns_panel.dropna(axis=1, thresh=coverage_threshold)

    # Log data quality metrics
    if failed_etfs:
        portfolio_logger.warning(f"⚠️  Failed to load {len(failed_etfs)} ETFs: {failed_etfs[:5]}{'...' if len(failed_etfs) > 5 else ''}")

    portfolio_logger.info(f"✅ Built returns panel: {len(returns_panel)} periods × {len(returns_panel.columns)} ETFs")

    return returns_panel

def generate_universe_hash(etf_universe: Dict[str, List[str]]) -> str:
    """Generate deterministic hash for ETF universe for caching."""
    import hashlib
    import json

    # Sort everything for deterministic hashing
    sorted_universe = {}
    for category in sorted(etf_universe.keys()):
        sorted_universe[category] = sorted(etf_universe[category])

    universe_str = json.dumps(sorted_universe, sort_keys=True)
    return hashlib.md5(universe_str.encode()).hexdigest()[:12]
```

**Integration Notes**:
- Both functions use `@lru_cache` for global cross-user caching
- `fetch_factor_universe()` integrates with existing database and YAML infrastructure
- `build_factor_returns_panel()` leverages existing `data_loader.py` functions
- Error handling provides graceful degradation for missing ETF data
- Functions emit performance and data quality metrics for monitoring

## Integration Points
- **Portfolio Risk Analyzer**: Leverage factor intelligence for offset recommendations
- **AI Integration**: Provide market context for sophisticated reasoning
- **What-If Engine**: Enhanced scenario analysis with factor-aware suggestions

## Development Approach

### Phase 1: Core Analytical Components ✅ COMPLETE
Design the fundamental analytical engines before infrastructure concerns:

1. **Factor Correlation Matrix Engine** ✅
   - Calculate correlations between all factor proxies (ETFs)
   - Handle both industry factors and style factors
   - Support time-based correlation analysis

2. **Factor Performance Profiles Engine** ✅
   - Risk/return characteristics for each factor proxy
   - Performance metrics (volatility, Sharpe ratio, max drawdown)
   - Market regime analysis capabilities

3. **Offset Recommendation Logic** ✅
   - Use correlation data to identify hedging opportunities
   - Algorithmic suggestions for overexposure mitigation
   - Context generation for AI-enhanced recommendations

### Phase 2: Infrastructure Integration ✅ COMPLETE
Once core logic is designed, integrate into existing system:
- ✅ Service layer architecture and caching
- ✅ Database schema and storage strategy
- ✅ API endpoints
- ❌ Frontend integration (not started)
- ✅ Integration with existing portfolio analysis workflow

## Detailed Component Design

### 1. Factor Correlation Matrix Engine

**Purpose**: Calculate and maintain correlations between all factor proxies to enable intelligent offset recommendations.

**Input Data Sources**:
- Industry factors from `industry_to_etf.yaml` (~16 ETFs)
- Style factors from `exchange_etf_proxies.yaml` (momentum, value)
- Market factors from `exchange_etf_proxies.yaml` (SPY, ACWX, EEM, etc.)
- Rate (Interest Rate) factors via `fetch_monthly_treasury_yield_levels()` and `prepare_rate_factors()` (Δy series)
- Additional asset‑class factors (ETF proxies) via database‑first loader with YAML fallback:
  canonical ETF proxies for fixed_income (duration sleeves), commodity (GLD, SLV, DBC), and crypto (spot BTC/ETH ETFs)
  to provide total‑return series for cross‑asset analysis.
  Loader order: Database (asset_etf_proxies table) → YAML (`asset_etf_proxies.yaml`) → hardcoded minimal set.
- Cash asset proxies via existing cash mapping system (DB → YAML → hardcoded): `cash_map.yaml` and
  `cash` tables/APIs already used by the platform (e.g., SGOV/BIL/SHV). These provide investable, total‑return
  proxies for the cash asset class.

Canonical asset class names:
- Use the canonical set from `core/constants.py` (e.g., `real_estate`, not `reit`). All tagging and
  documentation should follow these names for consistency across the platform.

**Core Functionality (Segmented by Category)**:

```python
class FactorCorrelationEngine:
    def calculate_factor_correlations(
        self, 
        start_date: str, 
        end_date: str,
        correlation_window: str = "monthly"
    ) -> Dict[str, Dict[str, float]]:
        """
        Calculate correlation matrix between all factor proxies.
        
        Returns:
            {
                "IYR": {"XLU": -0.32, "XLK": 0.15, "XLF": 0.45, ...},
                "XLU": {"IYR": -0.32, "XLK": -0.18, "XLF": 0.22, ...},
                ...
            }
        """
        
    def get_offset_candidates(
        self, 
        overexposed_factor: str, 
        correlation_threshold: float = -0.2
    ) -> List[Dict[str, Any]]:
        """
        Find factors that could offset overexposure.
        
        Args:
            overexposed_factor: Factor with too much exposure (e.g., "IYR")
            correlation_threshold: Max correlation for offset candidates
            
        Returns:
            [
                {"factor": "XLU", "correlation": -0.32, "name": "Utilities"},
                {"factor": "XLP", "correlation": -0.28, "name": "Consumer Staples"},
                ...
            ]
        """
        
    def get_factor_relationships(
        self, 
        factor: str
    ) -> Dict[str, List[str]]:
        """
        Categorize relationships for a given factor.
        
        Returns:
            {
                "hedges": ["XLU", "XLP"],        # Negative correlation
                "complements": ["XLRE", "VNQ"],  # Low positive correlation  
                "amplifiers": ["XLF", "KBE"]     # High positive correlation
            }
        """
```

**Key Design Decisions**:

1. **Factor Universe Construction**:
   - Extract all unique ETFs from existing YAML files
   - Group by category (industry, style, market, fixed_income, cash, commodity, crypto) for analysis (extensible)
   - Handle overlapping factors (e.g., multiple real estate ETFs)
   - Tag each factor ETF with an `asset_class` using the centralized SecurityTypeService
     (database → YAML → hardcoded) to enable filtering (e.g., exclude `cash`, `unknown`) and
     portfolio‑aware recommendations
   - Industry bucketing: Support multiple levels of industry granularity for Factor Intelligence views:
     • group (default): major sectors explicitly provided via an optional `group` field in industry mappings  
     • industry: standard industry names  
     • subindustry: most granular (may be large/noisy)  
     Group is sourced DB‑first from `industry_proxies.sector_group`, with YAML (`industry_to_etf.yaml`) fallback via an
     optional `group:` field in the extended mapping. If `group` is not provided for an industry, we fall back to the
     `industry` level for that entry. This avoids inferring sectors from ETFs and keeps the mapping explicit.

2. **Correlation Calculation**:
   - Use monthly returns for stability (consistent with existing system)
   - Prefer dividend‑adjusted total‑return prices via `fetch_monthly_total_return_price()` with
     safe fallback to `fetch_monthly_close()` to align with the platform’s total‑return methodology
   - Support configurable time windows (1Y, 3Y, 5Y); default windows are centralized in settings (e.g.,
     `PORTFOLIO_DEFAULTS` or a dedicated `INTELLIGENCE_WINDOWS`), ensuring consistent analysis across sections
   - Handle missing data gracefully
   - Compute matrices per category (industry/style/market/fixed_income/cash/commodity/crypto) and optionally a small
     cross‑category matrix by correlating category composite returns (e.g., average of
     factors within category)
     • When `industry_granularity='group'`, build a group‑level correlation matrix from group composite return series
       (equal‑weight of member industries' ETF returns by default). No canonical group ETF is required.
   - Compute a separate Rate Sensitivity matrix: corr(ETF return series, Δy columns)
     using maturities from `RATE_FACTOR_CONFIG` (e.g., UST2Y/5Y/10Y/30Y)
   - Compute a separate Market Sensitivity overlay: corr(ETF return series, market benchmarks) using
     total‑return benchmark ETFs (e.g., SPY, ACWX, EEM) or a category equity composite; this remains
     an overlay (correlations only) and does not replace per‑ETF beta reported in performance profiles
   - Rolling windows (optional): Provide rolling 12/24/36‑month correlation snapshots (or a stability score) to
     improve robustness and detect regime shifts; controlled by request flags and centralized defaults
   - Regime toggles (future): When a clean regime classifier is available (e.g., stress/calm/normal), add optional
     regime filters to compute correlations on subsets (e.g., high‑vol periods); until then, keep this disabled by default
   - Recommended defaults:
     • market_sensitivity: apply to ['industry','style'] by default; exclude 'market' category and any ETF used
       as a benchmark (e.g., SPY). Default benchmarks = ['SPY'] with optional ACWX/EEM.
     • rate_sensitivity: apply to ['fixed_income','industry','market','cash'] by default. Default maturities come
       from RATE_FACTOR_CONFIG (e.g., ['UST2Y','UST5Y','UST10Y','UST30Y']).
   - Provide Macro Views (cross‑asset):
     • Macro Composite Matrix: small, square matrix of composites for major asset groups
       (equity, fixed_income, cash, commodity, crypto). Highest readability for “stocks vs bonds vs cash”.
     • Macro ETF Matrix: single square matrix including a curated set of ETFs from those groups (e.g., top N per group),
       with optional de‑duplication (drop |corr| above threshold within a group). Heavier but more granular.
     • Do not include rate (Δy) in macro matrices; rate_sensitivity remains a separate overlay.
     • Data quality enforcement: For macro matrices, drop series that fail minimum coverage thresholds and
       deduplicate near‑identical ETFs within a group. Reuse centralized thresholds from
       `settings.DATA_QUALITY_THRESHOLDS` (e.g., `min_observations_for_returns_calculation`,
       `min_observations_for_regression`) and the request’s `macro_deduplicate_threshold` (default guided by
       settings). Emit data_quality notes for dropped/merged tickers.

3. **Offset Logic**:
   - Negative correlation candidates for hedging
   - Low correlation candidates for diversification
   - Exclude highly correlated factors (would amplify risk)
   - Incorporate `asset_class` tags and optional dividend yield preferences to preserve
     portfolio income while hedging risk
   - Include cash as a first‑class asset via cash ETF proxies (SGOV/BIL/SHV) from the cash mapping system
     for total‑return based analytics; still exclude raw currency tickers (e.g., CUR:USD) and any
     zero‑variance placeholders that would break correlation math

4. **Rate (Interest Rate) Category**:
   - Treat interest rates as their own category (`rate`) because they are macro drivers with
     Δy units, not ETF returns. Do not mix into ETF→ETF matrices.
   - Build a dedicated Rate Sensitivity matrix: corr(ETF monthly returns, Δy) for maturities from
     `RATE_FACTOR_CONFIG` (e.g., UST2Y/5Y/10Y/30Y) prepared via `fetch_monthly_treasury_yield_levels()`
     and `prepare_rate_factors()`.
   - Do not compute betas in Factor Intelligence (betas are part of the portfolio risk engine). Factor Intelligence
     only reports correlations, including ETF↔Δy correlations when requested.
   - Recommendations remain correlation‑based; the rate category can be included in correlation views and
     cross‑category correlations, but no betas are produced here.
   - Cash remains included via its ETF proxies in other matrices; raw currency tickers are excluded

5. **Cross‑Asset Intelligence View**:
   - Preserve segmented infra (industry/style/market/fixed_income/commodity/crypto/...), but expose
     explicit cross‑asset relationships for intuition (e.g., stocks vs bonds vs commodities vs crypto).
   - Cross‑Asset Correlation Matrix (ETF↔ETF): configurable submatrix across selected asset‑class groups
     (e.g., equities rows × fixed_income columns; or a square matrix across multiple groups). Uses total‑return monthly
     series for all ETFs and centralized data‑quality thresholds.
   - Category Composites: produce equal‑weight (or cap‑weight) composite monthly series per asset‑class group and return a
     compact cross‑category matrix (e.g., corr(equity_composite, fixed_income_composite, commodity_composite, crypto_composite)).
   - Rate Overlay remains separate (ETF↔Δy) for clarity and unit safety.

6. **Additional Asset‑Class Proxies (Required for Inclusion)**:
   - To include non‑equity asset classes in Factor Intelligence, provide ETF proxies to obtain total‑return series.
   - Single mapping file: `asset_etf_proxies.yaml` with sections for `fixed_income`, `commodity`, and `crypto`.
   - Database‑first loading: prefer `asset_etf_proxies` table, fall back to YAML, then hardcoded minimal set.
   - Load alongside industry/style/market maps; tag with `asset_class` via SecurityTypeService and assign a `category`
     such as `fixed_income`, `commodity`, or `crypto` for segmented matrices.

**Example Usage**:
```python
# User has overexposure to real estate
engine = FactorCorrelationEngine()
correlations = engine.calculate_factor_correlations("2019-01-01", "2024-01-01")

# Find offset candidates
offsets = engine.get_offset_candidates("IYR")  # Real estate ETF
# Returns: [{"factor": "XLU", "correlation": -0.32}, ...]

# Get full relationship map
relationships = engine.get_factor_relationships("IYR")
# Returns: {"hedges": ["XLU", "XLP"], "complements": [...], "amplifiers": [...]}

# Rate Sensitivity (Δy) Example Output Shape
# correlations["rate_sensitivity"] might look like:
# {
#   "XLU":  {"UST2Y": -0.35, "UST5Y": -0.42, "UST10Y": -0.48, "UST30Y": -0.41},
#   "XLRE": {"UST2Y": -0.22, "UST5Y": -0.29, "UST10Y": -0.36, "UST30Y": -0.33}
# }

# Macro views replace the old cross-asset overlays and tiny composites.
```

### 2. Factor Performance Profiles Engine

**Purpose**: Maintain risk/return characteristics for each factor proxy to inform offset recommendations.

**Core Functionality**:

```python
class FactorPerformanceEngine:
    def calculate_factor_profiles(
        self,
        start_date: str,
        end_date: str,
        factor_categories: Optional[List[str]] = None
    ) -> Dict[str, Dict[str, Dict[str, float]]]:
        """
        Calculate performance metrics for all factor proxies, segmented by category.
        
        Returns:
            {
              "industry": {
                "IYR": { "annual_return": ..., "volatility": ..., "sharpe_ratio": ..., "max_drawdown": ..., "beta_to_market": ..., "dividend_yield": ... },
                ...
              },
              "style": { ... },
              "market": { ... }
            }
        """

    # (Note: Betas are not computed in Factor Intelligence; correlations only.)
    
    # Composite Performance (Macro + Category)
    # In addition to per‑ETF profiles, compute composite performance tables:
    #  - Macro composites across equity/fixed_income/cash/commodity/crypto
    #  - Per‑category composites (industry/style/market buckets)
    # Metrics: annualized_return, volatility, sharpe_ratio, max_drawdown, dividend_yield
    # Weighting: equal‑weight by default; cap‑weight/custom optionally
    # These composites provide quick comparative context for broad sleeves and factor buckets.
        
    def rank_factors_by_metric(
        self,
        metric: str,
        ascending: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Rank factors by performance metric.
        
        Args:
            metric: "sharpe_ratio", "volatility", "max_drawdown", etc.
            ascending: True for lower-is-better metrics (volatility, drawdown)
        """
        
    def get_factor_summary(self, factor: str) -> Dict[str, Any]:
        """
        Get comprehensive summary for a factor.
        
        Returns:
            {
                "ticker": "XLU",
                "name": "Utilities Select Sector SPDR Fund",
                "category": "industry",
                "performance": {...},
                "risk_characteristics": "Low volatility, defensive",
                "typical_use_case": "Portfolio stabilization, inflation hedge"
            }
        """
```

### 3. Offset Recommendation Logic (Within vs Cross Category)

**Purpose**: Combine correlation and performance data to generate intelligent offset suggestions.

```python
class OffsetRecommendationEngine:
    def __init__(self, correlation_engine, performance_engine):
        self.correlation_engine = correlation_engine
        self.performance_engine = performance_engine
        
    def generate_offset_recommendations(
        self,
        overexposed_factor: str,
        target_allocation_reduction: float,
        risk_tolerance: str = "moderate",
        asset_class_filters: Optional[Dict[str, List[str]]] = None,
        factor_categories: Optional[List[str]] = None,
        prefer_income: bool = False,
        min_dividend_yield: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        """
        Generate ranked offset recommendations.
        
        Args:
            overexposed_factor: Factor to reduce (e.g., "IYR")
            target_allocation_reduction: How much to reduce (e.g., 0.10 = 10%)
            risk_tolerance: "conservative", "moderate", "aggressive"
            
        Returns:
            {
              "within_category": [ ... ],   # candidates in same category as overexposed factor
              "cross_category":  [ ... ]    # diversified candidates from other categories
            }
        """

    # Scoring Note:
    # Final rank combines correlation strength (more negative better), Sharpe (higher better),
    # and dividend_yield (when prefer_income/min_dividend_yield set). Liquidity/fee penalties can
    # be applied in later phases. Rate category data is available via correlations only and is not
    # used as betas in this module. Dividend yield is only considered for asset classes where it is
    # meaningful (equity, fixed_income, cash). Commodity/crypto ETF yields are typically zero and are
    # ignored by default for income ranking unless explicitly whitelisted.
        
    def generate_ai_context(
        self,
        overexposed_factor: str
    ) -> Dict[str, Any]:
        """
        Generate rich context for AI recommendations.
        
        Returns structured data that Claude can use to make
        sophisticated, factor-aware recommendations.
        """
```

## Revised Design - Leveraging Existing Functions

### **Existing Functions to Reuse ✅**

**1. Correlation & Covariance**:
- `compute_correlation_matrix(returns: pd.DataFrame)` - Perfect for factor-to-factor correlations
- `compute_covariance_matrix(returns: pd.DataFrame)` - For risk calculations

**2. Performance Analysis**:
- `calculate_portfolio_performance_metrics()` - Complete performance analysis
- `PerformanceResult` class - Structured performance data with all metrics we need

**3. Data Loading**:
- `fetch_monthly_close()` and `calc_monthly_returns()` - Data fetching
- `fetch_excess_return()` - Style factor calculations

**4. Factor Analysis**:
- `compute_factor_metrics()` - Beta calculations and factor regressions

### **Simplified Factor Intelligence Engine**

```python
class FactorIntelligenceEngine:
    def __init__(self, use_database: bool = True, user_id: Optional[int] = None):
        # Load factor universe using existing database-first pattern
        self.use_database = use_database
        self.user_id = user_id  # Store for multi-user isolation
        self.industry_factors = self._load_industry_factors()  # Database → YAML fallback
        self.style_factors = self._load_style_factors()        # Database → YAML fallback
        self.all_factors = {**self.industry_factors, **self.style_factors}

    def _load_industry_factors(self) -> Dict[str, str]:
        """Load industry factors using existing database-first pattern."""
        if self.use_database:
            # Note: Need to verify load_industry_etf_map() supports database-first mode
            return load_industry_etf_map()  # Uses DatabaseClient.get_industry_mappings()
        else:
            return load_industry_etf_map("industry_to_etf.yaml")  # YAML fallback

    def _load_style_factors(self) -> Dict[str, str]:
        """Load style factors using existing database-first pattern."""
        if self.use_database:
            # Note: Need to verify load_exchange_proxy_map() supports database-first mode
            exchange_map = load_exchange_proxy_map()  # Uses DatabaseClient.get_exchange_mappings()
        else:
            exchange_map = load_exchange_proxy_map("exchange_etf_proxies.yaml")

        # Extract unique style factors from all exchanges
        style_factors = {}
        for exchange, proxies in exchange_map.items():
            if exchange != "DEFAULT":
                style_factors[f"{exchange}_market"] = proxies.get("market")
                style_factors[f"{exchange}_momentum"] = proxies.get("momentum")
                style_factors[f"{exchange}_value"] = proxies.get("value")
        return {k: v for k, v in style_factors.items() if v}

    def calculate_factor_correlations(
        self,
        analysis_data: 'FactorAnalysisData'
    ) -> 'FactorCorrelationResult':
        """
        Calculate factor-to-factor correlation matrix using existing functions.

        Args:
            analysis_data: Factor analysis configuration with date range and settings

        Returns:
            FactorCorrelationResult with correlation matrix and metadata
        """
        # 1. Fetch returns for all factors (prefer total‑return series)
        factor_returns = {}
        excluded_factors = []

        for factor_name, etf_ticker in self.all_factors.items():
            try:
                price_series = fetch_monthly_total_return_price(etf_ticker, analysis_data.start_date, analysis_data.end_date)
            except Exception:
                try:
                    price_series = fetch_monthly_close(etf_ticker, analysis_data.start_date, analysis_data.end_date)
                except Exception as e:
                    excluded_factors.append(f"{factor_name} ({etf_ticker}): {str(e)}")
                    continue

            returns = calc_monthly_returns(price_series)
            if returns is not None and len(returns) > 0:
                factor_returns[factor_name] = returns
            else:
                excluded_factors.append(f"{factor_name} ({etf_ticker}): No valid returns")

        # 2. Align all return series to common dates
        returns_df = pd.DataFrame(factor_returns).dropna()

        # 3. Use existing correlation function
        correlation_matrix = compute_correlation_matrix(returns_df)

        # 4. Build analysis metadata
        analysis_metadata = {
            "start_date": analysis_data.start_date,
            "end_date": analysis_data.end_date,
            "analysis_date": datetime.now().isoformat(),
            "user_id": self.user_id,
            "factors_analyzed": len(factor_returns)
        }

        # 5. Return Result Object following existing pattern
        return FactorCorrelationResult(
            correlation_matrix=correlation_matrix,
            analysis_metadata=analysis_metadata
        )
        
    def _format_correlation_matrix_table(
        self, 
        correlation_matrix: pd.DataFrame, 
        start_date: str, 
        end_date: str,
        max_factors: int = 15
    ) -> str:
        """
        Format correlation matrix as readable table.
        
        Args:
            correlation_matrix: Pandas correlation matrix
            max_factors: Maximum number of factors to show (for readability)
            
        Returns:
            Formatted correlation matrix table string
        """
        # Limit to most important factors for readability
        factors_to_show = correlation_matrix.index[:max_factors]
        limited_matrix = correlation_matrix.loc[factors_to_show, factors_to_show]
        
        table_lines = []
        table_lines.append("FACTOR CORRELATION MATRIX")
        table_lines.append("=" * 120)
        table_lines.append(f"Period: {start_date} to {end_date}")
        table_lines.append(f"Showing top {len(factors_to_show)} factors")
        table_lines.append("")
        
        # Header row with factor abbreviations
        header = f"{'Factor':<20}"
        factor_abbrevs = {}
        for i, factor in enumerate(factors_to_show):
            abbrev = f"F{i+1:02d}"
            factor_abbrevs[factor] = abbrev
            header += f"{abbrev:>6}"
        table_lines.append(header)
        table_lines.append("-" * 120)
        
        # Data rows
        for factor in factors_to_show:
            row = f"{factor:<20}"
            for other_factor in factors_to_show:
                corr_val = limited_matrix.loc[factor, other_factor]
                if factor == other_factor:
                    row += f"{'1.00':>6}"
                else:
                    row += f"{corr_val:>6.2f}"
            table_lines.append(row)
            
        # Legend
        table_lines.append("")
        table_lines.append("FACTOR LEGEND:")
        table_lines.append("-" * 60)
        for factor, abbrev in factor_abbrevs.items():
            etf_ticker = self.all_factors.get(factor, "N/A")
            table_lines.append(f"{abbrev}: {factor} ({etf_ticker})")
            
        table_lines.append("")
        table_lines.append("Reading: Values show correlation between row and column factors")
        table_lines.append("Range: -1.00 (perfect negative) to +1.00 (perfect positive)")
        
        return "\n".join(table_lines)
        
    def calculate_factor_performance_profiles(
        self,
        analysis_data: 'FactorAnalysisData'
    ) -> 'FactorPerformanceResult':
        """
        Calculate performance metrics for each factor using existing performance functions.

        Args:
            start_date: Analysis start date
            end_date: Analysis end date
            benchmark_ticker: Benchmark for performance comparison

        Returns:
            FactorPerformanceResult with performance profiles and metadata
        """
        factor_profiles = {}
        excluded_factors = []

        for factor_name, etf_ticker in self.all_factors.items():
            try:
                # Create mini "portfolio" with 100% allocation to this factor
                weights = {etf_ticker: 1.0}

                # Use existing performance analysis with complete signature
                performance_metrics = calculate_portfolio_performance_metrics(
                    weights=weights,
                    start_date=start_date,
                    end_date=end_date,
                    benchmark_ticker=benchmark_ticker,
                    risk_free_rate=None,  # Use default
                    total_value=None      # Use default
                )

                # Extract key metrics
                factor_profiles[factor_name] = {
                    "annual_return": performance_metrics["returns"]["annualized_return"],
                    "volatility": performance_metrics["risk_metrics"]["volatility"],
                    "sharpe_ratio": performance_metrics["risk_adjusted_returns"]["sharpe_ratio"],
                    "max_drawdown": performance_metrics["risk_metrics"]["maximum_drawdown"],
                    "beta_to_market": performance_metrics.get("benchmark_analysis", {}).get("beta", 1.0),
                    "dividend_yield": performance_metrics.get("dividend_metrics", {}).get("portfolio_dividend_yield", 0.0)
                }

            except Exception as e:
                excluded_factors.append(f"{factor_name} ({etf_ticker}): {str(e)}")
                continue

        # Build analysis metadata
        analysis_metadata = {
            "start_date": start_date,
            "end_date": end_date,
            "benchmark_ticker": benchmark_ticker,
            "analysis_date": datetime.now().isoformat(),
            "user_id": self.user_id,
            "factors_analyzed": len(factor_profiles)
        }

        # Return Result Object following existing pattern
        return FactorPerformanceResult(
            performance_profiles=factor_profiles,
            analysis_metadata=analysis_metadata
        )
        
    def _format_performance_profiles_table(
        self,
        performance_profiles: Dict[str, Dict[str, float]],
        start_date: str,
        end_date: str,
        sort_by: str = "sharpe_ratio"
    ) -> str:
        """
        Format performance profiles as readable table.
        
        Args:
            performance_profiles: Dict of factor performance data
            sort_by: Metric to sort by ('sharpe_ratio', 'annual_return', 'volatility')
            
        Returns:
            Formatted performance profiles table string
        """
        table_lines = []
        table_lines.append("FACTOR PERFORMANCE PROFILES")
        table_lines.append("=" * 120)
        table_lines.append(f"Period: {start_date} to {end_date}")
        table_lines.append(f"Sorted by: {sort_by} (descending)")
        table_lines.append("")
        table_lines.append(f"{'Factor':<25} {'ETF':<8} {'Ann Return':<10} {'Volatility':<10} {'Sharpe':<8} {'Max DD':<8} {'Beta':<8} {'Yield':<8}")
        table_lines.append("-" * 120)
        
        # Sort factors by specified metric
        sorted_factors = sorted(
            performance_profiles.items(),
            key=lambda x: x[1].get(sort_by, 0),
            reverse=(sort_by != 'volatility')  # Lower volatility is better
        )
        
        for factor_name, perf in sorted_factors:
            etf_ticker = self.all_factors.get(factor_name, "N/A")
            table_lines.append(
                f"{factor_name:<25} "
                f"{etf_ticker:<8} "
                f"{perf.get('annual_return', 0):>8.1%} "
                f"{perf.get('volatility', 0):>8.1%} "
                f"{perf.get('sharpe_ratio', 0):>6.2f} "
                f"{perf.get('max_drawdown', 0):>6.1%} "
                f"{perf.get('beta_to_market', 0):>6.2f} "
                f"{perf.get('dividend_yield', 0):>6.2%}"
            )
            
        table_lines.append("")
        table_lines.append("PERFORMANCE SUMMARY:")
        table_lines.append("-" * 60)
        
        # Calculate summary statistics
        returns = [p.get('annual_return', 0) for p in performance_profiles.values()]
        sharpes = [p.get('sharpe_ratio', 0) for p in performance_profiles.values()]
        vols = [p.get('volatility', 0) for p in performance_profiles.values()]
        
        if returns:
            table_lines.append(f"Average Annual Return: {sum(returns)/len(returns):>8.1%}")
            table_lines.append(f"Average Sharpe Ratio:  {sum(sharpes)/len(sharpes):>8.2f}")
            table_lines.append(f"Average Volatility:    {sum(vols)/len(vols):>8.1%}")
            table_lines.append(f"Best Performer:        {sorted_factors[0][0]} (Sharpe: {sorted_factors[0][1].get('sharpe_ratio', 0):.2f})")
            
        table_lines.append("")
        table_lines.append("Legend: Ann Return=Annualized Return, Max DD=Maximum Drawdown, Beta=Market Beta")
        
        return "\n".join(table_lines)
        
    def generate_offset_recommendations(
        self,
        overexposed_factor: str,
        start_date: str,
        end_date: str,
        correlation_threshold: float = -0.2,
        max_recommendations: int = 10
    ) -> 'OffsetRecommendationResult':
        """
        Generate offset recommendations using correlation and performance data.

        Args:
            overexposed_factor: Factor that needs hedging/offset
            start_date: Analysis period start
            end_date: Analysis period end
            correlation_threshold: Maximum correlation for offset candidates
            max_recommendations: Maximum number of recommendations to return

        Returns:
            OffsetRecommendationResult with ranked recommendations and metadata
        """
        # Get correlations and performance profiles using Result Objects
        correlation_result = self.calculate_factor_correlations(start_date, end_date)
        performance_result = self.calculate_factor_performance_profiles(start_date, end_date)

        # Find factors with low/negative correlation to overexposed factor
        correlation_matrix = correlation_result.correlation_matrix
        if overexposed_factor not in correlation_matrix.index:
            return OffsetRecommendationResult(
                overexposed_factor=overexposed_factor,
                recommendations=[],
                analysis_metadata={
                    "error": f"Factor '{overexposed_factor}' not found in correlation matrix",
                    "user_id": self.user_id
                }
            )

        factor_corrs = correlation_matrix.loc[overexposed_factor]
        offset_candidates = factor_corrs[factor_corrs <= correlation_threshold].sort_values()

        # Combine with performance data
        recommendations = []
        performance_profiles = performance_result.performance_profiles

        for factor, correlation in offset_candidates.items():
            if factor == overexposed_factor:
                continue

            perf = performance_profiles.get(factor, {})
            if not perf:  # Skip factors without performance data
                continue

            recommendations.append({
                "factor": factor,
                "etf_ticker": self.all_factors.get(factor, "Unknown"),
                "correlation": float(correlation),
                "sharpe_ratio": perf.get("sharpe_ratio", 0.0),
                "volatility": perf.get("volatility", 0.0),
                "annual_return": perf.get("annual_return", 0.0),
                "max_drawdown": perf.get("max_drawdown", 0.0),
                "dividend_yield": perf.get("dividend_yield", 0.0),
                "rationale": f"Negative correlation ({correlation:.2f}) with {overexposed_factor}, Sharpe: {perf.get('sharpe_ratio', 0):.2f}"
            })

        # Sort by combination of correlation (more negative better) and Sharpe ratio (higher better)
        recommendations.sort(key=lambda x: (x["correlation"], -x["sharpe_ratio"]))

        # Limit to max_recommendations
        recommendations = recommendations[:max_recommendations]

        # Build analysis metadata
        analysis_metadata = {
            "overexposed_factor": overexposed_factor,
            "start_date": start_date,
            "end_date": end_date,
            "correlation_threshold": correlation_threshold,
            "analysis_date": datetime.now().isoformat(),
            "user_id": self.user_id,
            "recommendations_found": len(recommendations)
        }

        return OffsetRecommendationResult(
            overexposed_factor=overexposed_factor,
            recommendations=recommendations,
            analysis_metadata=analysis_metadata
        )
```

### **Key Benefits of This Approach**:

1. **Reuses Proven Functions**: Leverages your battle-tested correlation and performance functions
2. **Minimal New Code**: Just orchestration logic, not reimplementing calculations
3. **Consistent Results**: Same calculation methods as your existing system
4. **Easy Integration**: Uses same data sources and date handling

### **Example Usage**:
```python
# Initialize engine
engine = FactorIntelligenceEngine()

# User has real estate overexposure
recommendations = engine.generate_offset_recommendations("Real Estate")

# Output:
# [
#   {
#     "factor": "Utilities", 
#     "etf_ticker": "XLU",
#     "correlation": -0.32,
#     "sharpe_ratio": 0.41,
#     "rationale": "Negative correlation (-0.32) with Real Estate, Sharpe: 0.41"
#   },
#   ...
# ]
```

This approach transforms your AI recommendations from generic to factor-intelligent while reusing all your existing, proven calculation infrastructure!

## Design Review - Potential Gaps & Enhancements

### **1. Factor Universe Completeness**
**Current**: Industry + Style factors  
**Consider Adding**:
- **Geographic factors**: Country/region ETFs (EWJ, VGK, EEM, etc.)
- **Factor hierarchy**: Broad sectors (XLK) vs. narrow industries (SOXX)
- **Alternative factors**: Commodities (GLD, SLV), currencies, volatility (VIX)

### **2. Data Quality & Robustness**
**Current**: Basic data loading  
**Missing**:
- **Missing data handling**: ETFs with limited history, data gaps
- **Data quality validation**: Outlier detection, correlation sanity checks
- **Factor lifecycle management**: Delisted ETFs, ticker changes, mergers

### **3. Market Regime Intelligence**
**Current**: Single correlation over time period  
**Enhancement Opportunities**:
- **Regime-dependent correlations**: Bear vs. bull market relationships
- **Rolling correlations**: How factor relationships evolve over time
- **Volatility regime awareness**: High vs. low volatility periods

### **4. Recommendation Sophistication**
**Current**: Correlation threshold + Sharpe ratio  
**Could Enhance**:
- **Portfolio-aware recommendations**: Consider existing factor exposures
- **Risk budgeting logic**: Suggest allocation amounts, not just factors
- **Liquidity & tradability**: Filter by volume, bid-ask spreads
- **Multi-objective optimization**: Balance correlation, performance, liquidity

### **5. Performance & Scalability**
**Current**: Recalculates on each call  
**Production Considerations**:
- **Caching strategy**: Store correlation matrices, performance profiles in database
- **Incremental updates**: Only recalculate when new data available
- **Batch processing**: Optimize for large factor universes (200+ ETFs)

### **6. Integration Architecture**
**Current**: Standalone engine  
**Missing Integration Points**:
- **Portfolio context**: How to connect with existing portfolio risk analysis
- **AI context generation**: Structured data format for Claude integration
- **What-if scenarios**: Test offset recommendations before implementation
- **Real-time updates**: How to keep factor intelligence current

### **Prioritization Framework**

**Phase 1 (MVP)**: Core functionality with existing infrastructure ✅
- ✅ Basic factor correlation matrix
- ✅ Simple offset recommendations
- ✅ Database integration

**Phase 2 (Production)**: Robustness and performance ✅
- ✅ Caching and incremental updates (ServiceCacheMixin + LRU)
- ✅ Data quality validation (per-category quality tracking)
- ✅ Portfolio-aware recommendations (`recommend_portfolio_offsets()`)

**Phase 3 (Advanced)**: Market intelligence 📋
- 📋 Regime-dependent analysis
- 📋 Multi-objective optimization
- 📋 Real-time factor monitoring

### **Design Decisions Made ✅**

1. **Factor Universe Scope**: ✅ Industry + style factors (existing universe)
   - Industry factors more specific than broad sectors (better granularity)
   - Leverage existing factor mappings and infrastructure

2. **Caching Strategy**: ✅ Simple caching approach
   - Price data already cached by existing system
   - Cache correlation matrices and performance profiles in-memory or simple database tables

3. **Portfolio Integration**: ✅ Standalone but portfolio-aware
   - Independent engine that can be called from various contexts
   - Takes current portfolio exposures as input for intelligent recommendations

4. **AI Integration**: ✅ Formatted CLI tables → data objects pattern
   - Follow existing pattern: structured data → formatted tables → Claude context
   - Consistent with other functions in the system

## Redesigned Factor Intelligence Engine - Following Established Patterns

### **Architecture Overview**

Following your established patterns, the Factor Intelligence Engine is split into:

1. **Core Functions** (`/core/factor_intelligence.py`) - Pure business logic
2. **Result Objects** (`/core/result_objects.py`) - Structured results with factory methods
3. **Data Objects** (`/core/data_objects.py`) - Input validation and caching
4. **Service Layer** (`/services/factor_intelligence_service.py`) - Caching and error handling

### **Key Architecture Decision: Table Generation in Result Objects**

**✅ All table formatting logic is implemented in result object methods:**

- **Core Functions**: Focus purely on business logic and data analysis
- **Result Objects**: Handle ALL presentation logic via `to_formatted_table()` methods
- **Service Layer**: Orchestrates core functions and returns result objects
- **Claude Integration**: Calls `result.to_formatted_table()` for formatted context

**Benefits:**
- **Separation of Concerns**: Analysis logic separate from presentation logic
- **Reusability**: Any consumer (API, CLI, Claude) can format results consistently
- **Testability**: Table formatting can be unit tested independently
- **Maintainability**: Presentation changes don't affect core business logic

### **Core Functions Module**

```python
# /core/factor_intelligence.py
"""
Core factor intelligence business logic.
Pure functions for factor correlation analysis, performance profiling, and offset recommendations.
"""

import pandas as pd
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
import functools

from data_loader import fetch_monthly_close
from factor_utils import calc_monthly_returns
from portfolio_risk import compute_correlation_matrix, calculate_portfolio_performance_metrics
from proxy_builder import load_industry_etf_map, load_exchange_proxy_map
from core.result_objects import FactorCorrelationResult, FactorPerformanceResult, OffsetRecommendationResult
from core.data_objects import FactorAnalysisData
from settings import PORTFOLIO_DEFAULTS
from utils.config import DATA_LOADER_LRU_SIZE
from utils.logging import portfolio_logger

# Import logging decorators
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling
)

def _load_factor_universe_with_fallback(use_database: bool = True) -> Dict[str, str]:
    """
    Load factor universe with comprehensive fallback strategy.
    
    Args:
        use_database: Whether to try database first (default: True)
        
    Returns:
        Dict mapping factor names to ETF tickers
    """
    try:
        if use_database:
            # Try database first
            industry_factors = load_industry_etf_map()
            exchange_map = load_exchange_proxy_map()
            
            # Build style factors from exchange mappings
            style_factors = {}
            for exchange, proxies in exchange_map.items():
                if exchange != "DEFAULT":
                    for factor_type in ["market", "momentum", "value"]:
                        if proxies.get(factor_type):
                            style_factors[f"{exchange}_{factor_type}"] = proxies[factor_type]
            
            if industry_factors and style_factors:
                log_service_health("factor_universe_database", "healthy", 0.1)
                return {**industry_factors, **style_factors}
            else:
                log_service_health("factor_universe_database", "degraded", None, 
                                 {"error": "Empty result set"})
                
    except Exception as e:
        log_service_health("factor_universe_database", "down", None, 
                         {"error": str(e), "fallback": "yaml"})
    
    # YAML fallback
    try:
        industry_factors = load_industry_etf_map("industry_to_etf.yaml")
        exchange_map = load_exchange_proxy_map("exchange_etf_proxies.yaml")
        
        style_factors = {}
        for exchange, proxies in exchange_map.items():
            if exchange != "DEFAULT":
                for factor_type in ["market", "momentum", "value"]:
                    if proxies.get(factor_type):
                        style_factors[f"{exchange}_{factor_type}"] = proxies[factor_type]
        
        log_service_health("factor_universe_yaml", "healthy", 0.05, 
                         {"fallback_used": True})
        return {**industry_factors, **style_factors}
        
    except Exception as e:
        log_service_health("factor_universe_yaml", "down", None, {"error": str(e)})
        
        # Final fallback: minimal factor set
        log_service_health("factor_universe_minimal", "degraded", None, {
            "fallback_to_minimal": True,
            "error": "All factor universe sources failed"
        })
        
        return {
            "Technology": "XLK",
            "Healthcare": "XLV", 
            "Financials": "XLF",
            "Consumer Discretionary": "XLY",
            "Utilities": "XLU",
            "Real Estate": "XLRE",
            "Materials": "XLB",
            "Energy": "XLE",
            "Industrials": "XLI",
            "Consumer Staples": "XLP",
            "Communication Services": "XLC"
        }

@functools.lru_cache(maxsize=DATA_LOADER_LRU_SIZE)  # Global cache for shared market data
def _fetch_factor_returns_with_fallback(ticker: str, start_date: str, end_date: str):
    """
    Fetch factor returns with multiple fallback strategies.
    
    Args:
        ticker: ETF ticker symbol
        start_date: Start date for data fetch
        end_date: End date for data fetch
        
    Returns:
        Monthly returns series or None if all sources fail
    """
    errors = []
    
    # Primary: Use existing cached data
    try:
        monthly_close = fetch_monthly_close(ticker, start_date, end_date)
        if monthly_close is not None and len(monthly_close) > 0:
            returns = calc_monthly_returns(monthly_close)
            if returns is not None:
                log_service_health("factor_data_cache", "healthy", 0.2)
                return returns
    except Exception as e:
        errors.append(f"Cache error for {ticker}: {e}")
        log_service_health("factor_data_cache", "degraded", None, {"error": str(e), "ticker": ticker})
    
    # Fallback 1: Direct yfinance fetch (if available)
    try:
        import yfinance as yf
        stock = yf.Ticker(ticker)
        hist = stock.history(start=start_date, end=end_date, interval="1mo")
        if not hist.empty:
            returns = hist['Close'].pct_change().dropna()
            log_service_health("factor_data_yfinance", "healthy", 2.0, {"ticker": ticker})
            return returns
    except Exception as e:
        errors.append(f"yfinance error for {ticker}: {e}")
        log_service_health("factor_data_yfinance", "down", None, {"error": str(e), "ticker": ticker})
    
    # Fallback 2: FMP API (if available)
    try:
        if os.getenv('FMP_API_KEY'):
            # Use FMP historical data endpoint
            fmp_data = fetch_fmp_historical_data(ticker, start_date, end_date)
            if fmp_data is not None and len(fmp_data) > 0:
                returns = fmp_data.pct_change().dropna()
                log_service_health("factor_data_fmp", "healthy", 3.0, {"ticker": ticker})
                return returns
    except Exception as e:
        errors.append(f"FMP error for {ticker}: {e}")
        log_service_health("factor_data_fmp", "down", None, {"error": str(e), "ticker": ticker})
    
    # All fallbacks failed
    log_service_health("factor_data_all_failed", "unhealthy", None, {
        "ticker": ticker,
        "errors": errors,
        "fallback_attempts": ["cache", "yfinance", "fmp"]
    })
    
    return None

def _load_factor_universe(use_database: bool = True) -> Dict[str, str]:
    """Legacy function - use _load_factor_universe_with_fallback instead."""
    return _load_factor_universe_with_fallback(use_database)

@log_error_handling("high")
@log_portfolio_operation_decorator("factor_correlation_analysis")
@log_performance(5.0)
def analyze_factor_correlations(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    factor_universe: Optional[Dict[str, str]] = None,
    use_database: bool = True
) -> FactorCorrelationResult:
    """
    Calculate factor-to-factor correlation matrix using existing functions.
    
    Args:
        start_date: Analysis start date (YYYY-MM-DD). Defaults to PORTFOLIO_DEFAULTS["start_date"]
        end_date: Analysis end date (YYYY-MM-DD). Defaults to PORTFOLIO_DEFAULTS["end_date"]
        factor_universe: Optional custom factor universe (defaults to full universe)
        use_database: Whether to use database-first loading pattern
        
    Returns:
        FactorCorrelationResult: Structured correlation analysis results
    """
    # Use centralized date defaults (following existing pattern)
    start_date = start_date or PORTFOLIO_DEFAULTS["start_date"]
    end_date = end_date or PORTFOLIO_DEFAULTS["end_date"]
    
    # Load factor universe with fallback strategy
    if factor_universe is None:
        factor_universe = _load_factor_universe_with_fallback(use_database)
    
    # Fetch returns for all factors with graceful degradation
    factor_returns = {}
    excluded_factors = []
    data_quality_warnings = []
    min_observations = 24  # 2 years of monthly data (following existing pattern)
    
    for factor_name, etf_ticker in factor_universe.items():
        try:
            # Try multiple data sources with fallback
            returns = _fetch_factor_returns_with_fallback(etf_ticker, start_date, end_date)
            
            # Apply minimum data requirements (following existing pattern)
            if returns is not None and len(returns) >= min_observations:
                factor_returns[factor_name] = returns
            else:
                excluded_factors.append(factor_name)
                observations = len(returns) if returns is not None else 0
                data_quality_warnings.append(
                        f"Excluded {factor_name} ({etf_ticker}): only {observations} observations (need {min_observations})"
                    )
                    
            except Exception as e:
                excluded_factors.append(factor_name)
                data_quality_warnings.append(f"Excluded {factor_name} ({etf_ticker}): data fetch failed ({str(e)[:50]}...)")
                continue
    
    # Align all return series to common dates
    returns_df = pd.DataFrame(factor_returns).dropna()
    
    # Use existing correlation function
    correlation_matrix = compute_correlation_matrix(returns_df)
    
            # Create result object using factory method with comprehensive data quality info
        return FactorCorrelationResult.from_core_analysis(
            correlation_matrix=correlation_matrix,
            factor_universe=factor_universe,
            analysis_period={"start_date": start_date, "end_date": end_date},
            data_quality={
                "factors_analyzed": len(returns_df.columns),
                "factors_excluded": len(excluded_factors),
                "excluded_factor_list": excluded_factors,
                "observations": len(returns_df),
                "min_observations_required": min_observations,
                "data_quality_warnings": data_quality_warnings,
                "data_coverage_pct": len(factor_returns) / len(factor_universe) * 100 if factor_universe else 0
            }
        )

@log_error_handling("high")
@log_portfolio_operation_decorator("factor_performance_analysis")
@log_performance(10.0)
def analyze_factor_performance(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    factor_universe: Optional[Dict[str, str]] = None,
    use_database: bool = True,
    benchmark_ticker: str = "SPY"
) -> FactorPerformanceResult:
    """
    Calculate performance metrics for each factor using existing performance functions.
    
    Args:
        start_date: Analysis start date (YYYY-MM-DD). Defaults to PORTFOLIO_DEFAULTS["start_date"]
        end_date: Analysis end date (YYYY-MM-DD). Defaults to PORTFOLIO_DEFAULTS["end_date"]
        factor_universe: Optional custom factor universe (defaults to full universe)
        use_database: Whether to use database-first loading pattern
        benchmark_ticker: Benchmark for beta calculations
        
    Returns:
        FactorPerformanceResult: Structured performance analysis results
    """
    # Use centralized date defaults (following existing pattern)
    start_date = start_date or PORTFOLIO_DEFAULTS["start_date"]
    end_date = end_date or PORTFOLIO_DEFAULTS["end_date"]
    
    # Load factor universe if not provided
    if factor_universe is None:
        factor_universe = _load_factor_universe(use_database)
    
    factor_profiles = {}
    excluded_factors = []
    data_quality_warnings = []
    min_observations = 24  # 2 years of monthly data (following existing pattern)
    
    for factor_name, etf_ticker in factor_universe.items():
        try:
            # Check data availability first (following existing pattern)
            try:
                _prices = fetch_monthly_total_return_price(etf_ticker, start_date, end_date)
            except Exception:
                _prices = fetch_monthly_close(etf_ticker, start_date, end_date)
            returns = calc_monthly_returns(_prices)
            
            if returns is None or len(returns) < min_observations:
                excluded_factors.append(factor_name)
                observations = len(returns) if returns is not None else 0
                data_quality_warnings.append(
                    f"Excluded {factor_name} ({etf_ticker}): only {observations} observations (need {min_observations})"
                )
                continue
            
            # Create mini "portfolio" with 100% allocation to this factor
            weights = {etf_ticker: 1.0}
            
            # Use existing performance analysis
            performance_metrics = calculate_portfolio_performance_metrics(
                weights, start_date, end_date, benchmark_ticker=benchmark_ticker
            )
            
            # Check for calculation errors (following existing pattern)
            if "error" in performance_metrics:
                excluded_factors.append(factor_name)
                data_quality_warnings.append(f"Excluded {factor_name} ({etf_ticker}): performance calculation failed")
                continue
            
            # Extract key metrics
            factor_profiles[factor_name] = {
                "annual_return": performance_metrics["returns"]["annualized_return"],
                "volatility": performance_metrics["risk_metrics"]["volatility"],
                "sharpe_ratio": performance_metrics["risk_adjusted_returns"]["sharpe_ratio"],
                "max_drawdown": performance_metrics["risk_metrics"]["maximum_drawdown"],
                "beta_to_market": performance_metrics.get("benchmark_analysis", {}).get("beta", 1.0),
                "etf_ticker": etf_ticker,
                "data_observations": len(returns)
            }
        except Exception as e:
            excluded_factors.append(factor_name)
            data_quality_warnings.append(f"Excluded {factor_name} ({etf_ticker}): {str(e)[:50]}...")
            continue
    
    # Create result object using factory method with comprehensive data quality info
    return FactorPerformanceResult.from_core_analysis(
        performance_profiles=factor_profiles,
        analysis_period={"start_date": start_date, "end_date": end_date},
        benchmark_ticker=benchmark_ticker,
        data_quality={
            "factors_analyzed": len(factor_profiles),
            "factors_excluded": len(excluded_factors),
            "excluded_factor_list": excluded_factors,
            "min_observations_required": min_observations,
            "data_quality_warnings": data_quality_warnings,
            "data_coverage_pct": len(factor_profiles) / len(factor_universe) * 100 if factor_universe else 0
        }
    )

@log_error_handling("medium")
@log_portfolio_operation_decorator("offset_recommendation_generation")
@log_performance(2.0)
def generate_offset_recommendations(
    overexposed_factor: str,
    portfolio_data: PortfolioData,
    correlation_data: FactorCorrelationResult,
    performance_data: FactorPerformanceResult,
    target_allocation_reduction: float = 0.10,
    correlation_threshold: float = -0.2
) -> OffsetRecommendationResult:
    """
    Generate portfolio-aware offset recommendations using correlation and performance data.
    
    Args:
        overexposed_factor: Factor to reduce exposure to
        portfolio_data: PortfolioData object with current portfolio configuration
        correlation_data: Factor correlation analysis results
        performance_data: Factor performance analysis results
        target_allocation_reduction: How much to reduce overexposed factor
        correlation_threshold: Maximum correlation for offset candidates
        
    Returns:
        OffsetRecommendationResult: Structured offset recommendations
    """
    
    # Get current portfolio factor exposures using existing portfolio analysis
    from core.portfolio_analysis import analyze_portfolio
    
    # Create temporary portfolio file for analysis
    temp_portfolio_file = portfolio_data.to_temp_file()
    
    try:
        # Run portfolio analysis to get current factor exposures
        portfolio_analysis_result = analyze_portfolio(temp_portfolio_file)
        current_portfolio_exposures = portfolio_analysis_result.get_factor_exposures()
    finally:
        # Clean up temporary file
        import os
        if os.path.exists(temp_portfolio_file):
            os.unlink(temp_portfolio_file)
    correlations = correlation_data.correlation_matrix
    performance_profiles = performance_data.performance_profiles
    
    # Find factors with negative correlation to overexposed factor
    if overexposed_factor not in correlations.index:
        return OffsetRecommendationResult.from_core_analysis(
            recommendations=[],
            overexposed_factor=overexposed_factor,
            analysis_metadata={"error": f"Factor {overexposed_factor} not found in correlation data"}
        )
    
    factor_corrs = correlations.loc[overexposed_factor]
    offset_candidates = factor_corrs[factor_corrs <= correlation_threshold].sort_values()
    
    # Generate portfolio-aware recommendations
    recommendations = []
    for factor, correlation in offset_candidates.items():
        if factor == overexposed_factor:
            continue
            
        # Check current exposure to this factor
        current_exposure = current_portfolio_exposures.get(factor, 0.0)
        
        # Skip if already highly exposed (> 20%)
        if current_exposure > 0.20:
            continue
            
        perf = performance_profiles.get(factor, {})
        
        # Calculate suggested allocation (considering current exposure)
        max_suggested = min(target_allocation_reduction, 0.15 - current_exposure)
        if max_suggested <= 0:
            continue
            
        recommendations.append({
            "factor": factor,
            "etf_ticker": perf.get("etf_ticker", "N/A"),
            "correlation_to_overexposed": correlation,
            "current_portfolio_exposure": current_exposure,
            "suggested_additional_allocation": max_suggested,
            "sharpe_ratio": perf.get("sharpe_ratio", 0),
            "volatility": perf.get("volatility", 0),
            "rationale": f"Hedges {overexposed_factor} (corr: {correlation:.2f}), "
                       f"current exposure: {current_exposure:.1%}, "
                       f"suggest +{max_suggested:.1%}"
        })
    
    # Sort by combination of correlation and opportunity
    recommendations.sort(
        key=lambda x: (x["correlation_to_overexposed"], x["current_portfolio_exposure"])
    )
    
            # Create result object using factory method
        return OffsetRecommendationResult.from_core_analysis(
            recommendations=recommendations,
            overexposed_factor=overexposed_factor,
            current_portfolio_exposures=current_portfolio_exposures,
            analysis_metadata={
                "target_reduction": target_allocation_reduction,
                "correlation_threshold": correlation_threshold,
                "recommendations_found": len(recommendations),
                "portfolio_name": portfolio_data.portfolio_name,
                "user_id": portfolio_data.user_id
            }
        )
```

### **Result Objects**

```python
# /core/result_objects.py (additions)

@dataclass
class FactorCorrelationResult:
    """
    Factor correlation analysis results following established result object pattern.
    
    Contains correlation matrix between factors with formatted reporting capabilities.
    Provides both structured data access and CLI-formatted output for Claude integration.
    """
    
    # Core correlation data
    correlation_matrix: pd.DataFrame
    factor_universe: Dict[str, str]
    analysis_period: Dict[str, str]
    data_quality: Dict[str, Any]
    
    # Analysis metadata
    analysis_date: Optional[str] = None
    
    @classmethod
    def from_core_analysis(cls,
                          correlation_matrix: pd.DataFrame,
                          factor_universe: Dict[str, str],
                          analysis_period: Dict[str, str],
                          data_quality: Dict[str, Any]) -> 'FactorCorrelationResult':
        """
        Create FactorCorrelationResult from core analysis function data.
        
        Following established pattern for result object factory methods.
        """
        return cls(
            correlation_matrix=correlation_matrix,
            factor_universe=factor_universe,
            analysis_period=analysis_period,
            data_quality=data_quality,
            analysis_date=datetime.now(UTC).isoformat()
        )
    
    def to_formatted_table(self, max_factors: int = 15) -> str:
        """
        Generate formatted correlation matrix table for Claude context.
        
        This method contains all the table formatting logic that was previously
        in the core functions. Result objects handle all presentation logic
        while core functions focus purely on business logic.
        
        Returns:
            Formatted CLI table string ready for Claude integration
        """
        # TODO: Implement full correlation matrix table formatting
        # - Header with analysis period and data quality info
        # - Correlation matrix with factor names and values
        # - Highlight strongest hedges/amplifiers
        # - Format: Fixed-width columns, aligned decimals
        pass
        
    def get_factor_relationships(self, focus_factor: str) -> Dict[str, List[str]]:
        """Get hedges, complements, and amplifiers for a specific factor."""
        if focus_factor not in self.correlation_matrix.index:
            return {"hedges": [], "complements": [], "amplifiers": []}
            
        factor_corrs = self.correlation_matrix.loc[focus_factor]
        
        return {
            "hedges": factor_corrs[factor_corrs < -0.1].index.tolist(),
            "complements": factor_corrs[(factor_corrs >= -0.1) & (factor_corrs <= 0.3)].index.tolist(),
            "amplifiers": factor_corrs[factor_corrs > 0.3].index.tolist()
        }
    
    def to_api_response(self) -> Dict[str, Any]:
        """Convert to API-compatible response format."""
        return {
            "correlation_matrix": self.correlation_matrix.to_dict(),
            "factor_universe": self.factor_universe,
            "analysis_period": self.analysis_period,
            "data_quality": self.data_quality,
            "analysis_date": self.analysis_date
        }

@dataclass
class FactorPerformanceResult:
    """
    Factor performance analysis results following established result object pattern.
    
    Contains performance metrics for each factor with formatted reporting capabilities.
    """
    
    # Core performance data
    performance_profiles: Dict[str, Dict[str, float]]
    analysis_period: Dict[str, str]
    benchmark_ticker: str
    data_quality: Dict[str, Any]
    
    # Analysis metadata
    analysis_date: Optional[str] = None
    
    @classmethod
    def from_core_analysis(cls,
                          performance_profiles: Dict[str, Dict[str, float]],
                          analysis_period: Dict[str, str],
                          benchmark_ticker: str,
                          data_quality: Dict[str, Any]) -> 'FactorPerformanceResult':
        """Create FactorPerformanceResult from core analysis function data."""
        return cls(
            performance_profiles=performance_profiles,
            analysis_period=analysis_period,
            benchmark_ticker=benchmark_ticker,
            data_quality=data_quality,
            analysis_date=datetime.now(UTC).isoformat()
        )
    
    def to_formatted_table(self, sort_by: str = "sharpe_ratio", top_n: int = 15) -> str:
        """
        Generate formatted performance profiles table for Claude context.
        
        This method contains all the table formatting logic for factor performance data.
        Result objects handle all presentation logic while core functions focus purely 
        on business logic.
        
        Args:
            sort_by: Metric to sort factors by (sharpe_ratio, annual_return, volatility)
            top_n: Number of top factors to display
            
        Returns:
            Formatted CLI table string ready for Claude integration
        """
        # TODO: Implement full performance profiles table formatting
        # - Header with analysis period and benchmark info
        # - Performance metrics table with factor names, returns, risk metrics
        # - Sort by specified metric, highlight top/bottom performers
        # - Format: Fixed-width columns, aligned decimals, percentage formatting
        pass
        
    def get_top_performers(self, metric: str = "sharpe_ratio", n: int = 5) -> List[Dict[str, Any]]:
        """Get top N performing factors by specified metric."""
        sorted_factors = sorted(
            self.performance_profiles.items(),
            key=lambda x: x[1].get(metric, 0),
            reverse=(metric != 'volatility')
        )
        return [{"factor": f, **perf} for f, perf in sorted_factors[:n]]
    
    def to_api_response(self) -> Dict[str, Any]:
        """Convert to API-compatible response format."""
        return {
            "performance_profiles": self.performance_profiles,
            "analysis_period": self.analysis_period,
            "benchmark_ticker": self.benchmark_ticker,
            "data_quality": self.data_quality,
            "analysis_date": self.analysis_date
        }

@dataclass
class OffsetRecommendationResult:
    """
    Offset recommendation results following established result object pattern.
    
    Contains portfolio-aware offset recommendations with formatted reporting capabilities.
    """
    
    # Core recommendation data
    recommendations: List[Dict[str, Any]]
    overexposed_factor: str
    current_portfolio_exposures: Dict[str, float]
    analysis_metadata: Dict[str, Any]
    
    # Analysis metadata
    analysis_date: Optional[str] = None
    
    @classmethod
    def from_core_analysis(cls,
                          recommendations: List[Dict[str, Any]],
                          overexposed_factor: str,
                          current_portfolio_exposures: Dict[str, float],
                          analysis_metadata: Dict[str, Any]) -> 'OffsetRecommendationResult':
        """Create OffsetRecommendationResult from core analysis function data."""
        return cls(
            recommendations=recommendations,
            overexposed_factor=overexposed_factor,
            current_portfolio_exposures=current_portfolio_exposures,
            portfolio_context={
                "portfolio_name": analysis_metadata.get("portfolio_name"),
                "user_id": analysis_metadata.get("user_id"),
                "total_positions": len(current_portfolio_exposures)
            },
            analysis_metadata=analysis_metadata,
            analysis_date=datetime.now(UTC).isoformat()
        )
    
    def to_formatted_table(self) -> str:
        """
        Generate formatted offset recommendations table for Claude context.
        
        This method contains all the table formatting logic for portfolio-aware
        offset recommendations. Result objects handle all presentation logic
        while core functions focus purely on business logic.
        
        Returns:
            Formatted CLI table string ready for Claude integration
        """
        # TODO: Implement full offset recommendations table formatting
        # - Header with overexposed factor and analysis metadata
        # - Recommendations table with factor names, correlations, allocations
        # - Current vs suggested exposure comparison
        # - Rationale for each recommendation
        # - Format: Fixed-width columns, aligned decimals, percentage formatting
        pass
        
    def get_top_recommendations(self, n: int = 3) -> List[Dict[str, Any]]:
        """Get top N offset recommendations."""
        return self.recommendations[:n]
    
    def to_api_response(self) -> Dict[str, Any]:
        """Convert to API-compatible response format."""
        return {
            "recommendations": self.recommendations,
            "overexposed_factor": self.overexposed_factor,
            "current_portfolio_exposures": self.current_portfolio_exposures,
            "analysis_metadata": self.analysis_metadata,
            "analysis_date": self.analysis_date
        }
```

### **Data Objects**

```python
# /core/data_objects.py (additions)

@dataclass
class FactorAnalysisData:
    """
    Factor analysis configuration with input validation and caching.
    
    Following established data object pattern for input validation and caching.
    """
    
    # Analysis parameters (use PORTFOLIO_DEFAULTS if not provided)
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    factor_universe: Optional[Dict[str, str]] = None
    use_database: bool = True
    
    # Analysis configuration
    correlation_threshold: float = -0.2
    target_allocation_reduction: float = 0.10
    benchmark_ticker: str = "SPY"
    
    # Caching and metadata
    _cache_key: Optional[str] = None
    _last_updated: Optional[datetime] = None
    
    def __post_init__(self):
        """Validate inputs and generate cache key."""
        # Import here to avoid circular imports
        from settings import PORTFOLIO_DEFAULTS
        
        # Use centralized date defaults (following existing pattern)
        self.start_date = self.start_date or PORTFOLIO_DEFAULTS["start_date"]
        self.end_date = self.end_date or PORTFOLIO_DEFAULTS["end_date"]
        
        # Validate date format
        try:
            datetime.strptime(self.start_date, "%Y-%m-%d")
            datetime.strptime(self.end_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Dates must be in YYYY-MM-DD format")
            
        # Generate cache key
        self._cache_key = self._generate_cache_key()
        self._last_updated = datetime.now(UTC)
    
    def _generate_cache_key(self) -> str:
        """Generate cache key for factor analysis configuration."""
        key_data = {
            "start_date": self.start_date,
            "end_date": self.end_date,
            "use_database": self.use_database,
            "benchmark_ticker": self.benchmark_ticker
        }
        return hashlib.md5(json.dumps(key_data, sort_keys=True).encode()).hexdigest()
    
    @classmethod
    def from_dates(cls, start_date: Optional[str] = None, end_date: Optional[str] = None, **kwargs) -> 'FactorAnalysisData':
        """Create FactorAnalysisData from date range. Uses PORTFOLIO_DEFAULTS if dates not provided."""
        return cls(start_date=start_date, end_date=end_date, **kwargs)
    
    @classmethod
    def from_defaults(cls, **kwargs) -> 'FactorAnalysisData':
        """Create FactorAnalysisData using PORTFOLIO_DEFAULTS for dates."""
        return cls(start_date=None, end_date=None, **kwargs)
    
    def get_cache_key(self) -> str:
        """Get cache key for this analysis configuration."""
        return self._cache_key
```

### **Service Layer**

```python
# /services/factor_intelligence_service.py
"""
Factor Intelligence Service Module

High-level service layer for factor correlation analysis, performance profiling, and offset recommendations.
Follows established service pattern with caching, error handling, and structured results.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime

from services.cache_mixin import ServiceCacheMixin
from core.factor_intelligence import (
    analyze_factor_correlations,
    analyze_factor_performance, 
    generate_offset_recommendations
)
from core.data_objects import FactorAnalysisData, PortfolioData
from core.result_objects import (
    FactorCorrelationResult,
    FactorPerformanceResult,
    OffsetRecommendationResult
)
from core.exceptions import ServiceError

# Import logging decorators
from utils.logging import (
    log_portfolio_operation_decorator,
    log_performance,
    log_error_handling,
    log_cache_operations
)


class FactorIntelligenceService(ServiceCacheMixin):
    """
    High-level service for factor intelligence analysis with caching and structured results.
    
    This service provides cached, structured factor analysis capabilities for market intelligence
    and portfolio offset recommendations. It follows the established service pattern with
    automatic caching, error handling, and result object management.
    
    Key Features:
    - **Factor Correlation Analysis**: Market-wide factor correlation matrices
    - **Factor Performance Profiling**: Risk/return characteristics for all factors
    - **Portfolio-Aware Offset Recommendations**: Intelligent hedging suggestions
    - **Automatic Caching**: Analysis results cached for performance optimization (TTL: 30min, MaxSize: 500)
    - **Structured Results**: Returns typed result objects with formatted reporting
    - **Database Integration**: Follows database-first → YAML fallback pattern
    
    Performance: 
    - First analysis ~5-10 seconds (calculates 200+ factor correlations)
    - Cached results ~10-50ms (100-500x faster)
    - Cache hit rate typically >80% for repeated factor analysis
    
    Architecture:
        Consumer (Claude/API) → FactorIntelligenceService → Core Factor Analysis → Market Data
    
    Caching Strategy:
    - **Factor Correlations**: Cached by date range and factor universe
    - **Factor Performance**: Cached by date range and benchmark
    - **Offset Recommendations**: Not cached (portfolio-specific, changes frequently)
    
    Example:
        ```python
        service = FactorIntelligenceService(cache_results=True)
        analysis_data = FactorAnalysisData.from_defaults()
        
        # First call: ~8 seconds (calculates correlations)
        correlations = service.analyze_factor_correlations(analysis_data)
        
        # Second call: ~20ms (cache hit)
        correlations = service.analyze_factor_correlations(analysis_data)
        
        # Portfolio-aware recommendations (uses cached correlations)
        recommendations = service.generate_portfolio_aware_recommendations(
            overexposed_factor="real_estate",
            portfolio_data=portfolio_data,
            analysis_data=analysis_data
        )
        ```
    """
    
    def __init__(self, cache_results: bool = True, user_id: Optional[int] = None):
        """
        Initialize the factor intelligence service.

        Args:
            cache_results: Whether to cache analysis results (default: True)
                          Uses SERVICE_CACHE_MAXSIZE=500, SERVICE_CACHE_TTL=1800 (30min)
            user_id: User ID for multi-user isolation and logging
        """
        self.cache_results = cache_results
        self.user_id = user_id
        if cache_results:
            self._init_service_cache()  # Creates TTLCache with maxsize=500, ttl=1800
    
    @log_error_handling("high")
    @log_portfolio_operation_decorator("service_factor_correlation_analysis")
    @log_cache_operations("factor_correlation")
    @log_performance(5.0)
    def analyze_factor_correlations(self, analysis_data: FactorAnalysisData) -> FactorCorrelationResult:
        """
        Analyze factor correlations with automatic caching.
        
        This method calculates correlations between all factor proxies (~200 factors).
        Results are cached for 30 minutes to avoid expensive recalculation.
        
        Performance:
        - First call: ~5-8 seconds (calculates 200+ factor correlations)
        - Cached calls: ~10-20ms (cache hit)
        
        Args:
            analysis_data: Factor analysis configuration with date range and settings
            
        Returns:
            FactorCorrelationResult: Structured correlation analysis results with:
                - correlation_matrix: Factor-to-factor correlation matrix
                - data_quality: Information about excluded factors and data coverage
                - to_formatted_table(): CLI table for Claude integration
        """
        try:
            # Create cache key (following existing service pattern)
            cache_key = f"factor_correlations_{analysis_data.get_cache_key()}"
            
            # Check cache (thread-safe)
            with self._lock:
                if self.cache_results and cache_key in self._cache:
                    return self._cache[cache_key]
            
            # Call core function
            result = analyze_factor_correlations(
                start_date=analysis_data.start_date,
                end_date=analysis_data.end_date,
                factor_universe=analysis_data.factor_universe,
                use_database=analysis_data.use_database
            )
            
            # Cache results (thread-safe)
            if self.cache_results:
                with self._lock:
                    self._cache[cache_key] = result
                
            return result
            
        except Exception as e:
            raise ServiceError(f"Factor correlation analysis failed: {str(e)}") from e
    
    @log_error_handling("high")
    @log_portfolio_operation_decorator("service_factor_performance_analysis")
    @log_cache_operations("factor_performance")
    @log_performance(10.0)
    def analyze_factor_performance(self, analysis_data: FactorAnalysisData) -> FactorPerformanceResult:
        """
        Analyze factor performance with automatic caching.
        
        This method calculates performance metrics for all factor proxies (~200 factors).
        Results are cached for 30 minutes to avoid expensive recalculation.
        
        Performance:
        - First call: ~8-12 seconds (calculates 200+ factor performance metrics)
        - Cached calls: ~10-20ms (cache hit)
        
        Args:
            analysis_data: Factor analysis configuration with date range and benchmark
            
        Returns:
            FactorPerformanceResult: Structured performance analysis results with:
                - performance_profiles: Risk/return metrics for each factor
                - data_quality: Information about excluded factors and data coverage
                - to_formatted_table(): CLI table for Claude integration
        """
        try:
            # Create cache key (following existing service pattern)
            cache_key = f"factor_performance_{analysis_data.get_cache_key()}"
            
            # Check cache (thread-safe)
            with self._lock:
                if self.cache_results and cache_key in self._cache:
                    return self._cache[cache_key]
            
            # Call core function
            result = analyze_factor_performance(
                start_date=analysis_data.start_date,
                end_date=analysis_data.end_date,
                factor_universe=analysis_data.factor_universe,
                use_database=analysis_data.use_database,
                benchmark_ticker=analysis_data.benchmark_ticker
            )
            
            # Cache results (thread-safe)
            if self.cache_results:
                with self._lock:
                    self._cache[cache_key] = result
                
            return result
            
        except Exception as e:
            raise ServiceError(f"Factor performance analysis failed: {str(e)}") from e
    
    @log_error_handling("medium")
    @log_portfolio_operation_decorator("service_offset_recommendations")
    @log_performance(3.0)
    def generate_portfolio_aware_recommendations(
        self,
        overexposed_factor: str,
        portfolio_data: PortfolioData,
        analysis_data: FactorAnalysisData
    ) -> OffsetRecommendationResult:
        """
        Generate portfolio-aware offset recommendations.
        
        Args:
            overexposed_factor: Factor to reduce exposure to
            portfolio_data: PortfolioData object with current portfolio configuration
            analysis_data: Factor analysis configuration
            
        Returns:
            OffsetRecommendationResult: Structured offset recommendations
        """
        # Get correlation and performance data (cached)
        correlation_result = self.analyze_factor_correlations(analysis_data)
        performance_result = self.analyze_factor_performance(analysis_data)
        
        # Generate recommendations using core function
        return generate_offset_recommendations(
            overexposed_factor=overexposed_factor,
            portfolio_data=portfolio_data,
            correlation_data=correlation_result,
            performance_data=performance_result,
            target_allocation_reduction=analysis_data.target_allocation_reduction,
            correlation_threshold=analysis_data.correlation_threshold
        )
    
    def generate_comprehensive_analysis(
        self,
        overexposed_factors: List[str],
        portfolio_data: PortfolioData,
        analysis_data: FactorAnalysisData
    ) -> Dict[str, Any]:
        """
        Generate comprehensive factor intelligence analysis for multiple overexposed factors.
        
        Returns:
            Dict with correlation analysis, performance profiles, and recommendations for each factor
        """
        # Get base analysis (cached)
        correlation_result = self.analyze_factor_correlations(analysis_data)
        performance_result = self.analyze_factor_performance(analysis_data)
        
        # Generate recommendations for each overexposed factor
        recommendations = {}
        for factor in overexposed_factors:
            recommendations[factor] = self.generate_portfolio_aware_recommendations(
                overexposed_factor=factor,
                portfolio_data=portfolio_data,
                analysis_data=analysis_data
            )
        
        return {
            "correlation_analysis": correlation_result,
            "performance_analysis": performance_result,
            "offset_recommendations": recommendations,
            "formatted_tables": {
                "correlation_matrix": correlation_result.to_formatted_table(),
                "performance_profiles": performance_result.to_formatted_table(),
                "recommendations": {
                    factor: rec.to_formatted_table() 
                    for factor, rec in recommendations.items()
                }
            }
        }

        
    def generate_portfolio_aware_recommendations(
        self,
        overexposed_factor: str,
        current_portfolio_exposures: Dict[str, float],
        target_allocation_reduction: float = 0.10,
        correlation_threshold: float = -0.2
    ) -> List[Dict[str, Any]]:
        """
        Generate offset recommendations considering current portfolio exposures.
        
        Args:
            overexposed_factor: Factor to reduce (e.g., "Real Estate")
            current_portfolio_exposures: Current factor exposures from portfolio analysis
                e.g., {"Real Estate": 0.35, "Technology": 0.25, "Utilities": 0.05, ...}
            target_allocation_reduction: How much to reduce overexposed factor
            correlation_threshold: Max correlation for offset candidates
            
        Returns:
            Portfolio-aware recommendations that avoid double-exposure
        """
        # Get basic offset candidates
        correlations = self._get_cached_correlations()
        performance_profiles = self._get_cached_performance()
        
        # Find factors with negative correlation to overexposed factor
        if overexposed_factor not in correlations.index:
            return []
            
        factor_corrs = correlations.loc[overexposed_factor]
        offset_candidates = factor_corrs[factor_corrs <= correlation_threshold].sort_values()
        
        # Filter out factors already overexposed in current portfolio
        portfolio_aware_candidates = []
        for factor, correlation in offset_candidates.items():
            if factor == overexposed_factor:
                continue
                
            # Check current exposure to this factor
            current_exposure = current_portfolio_exposures.get(factor, 0.0)
            
            # Skip if already highly exposed (e.g., > 20%)
            if current_exposure > 0.20:
                continue
                
            perf = performance_profiles.get(factor, {})
            
            # Calculate suggested allocation (considering current exposure)
            max_suggested = min(target_allocation_reduction, 0.15 - current_exposure)
            if max_suggested <= 0:
                continue
                
            portfolio_aware_candidates.append({
                "factor": factor,
                "etf_ticker": self.all_factors[factor],
                "correlation_to_overexposed": correlation,
                "current_portfolio_exposure": current_exposure,
                "suggested_additional_allocation": max_suggested,
                "sharpe_ratio": perf.get("sharpe_ratio", 0),
                "volatility": perf.get("volatility", 0),
                "rationale": f"Hedges {overexposed_factor} (corr: {correlation:.2f}), "
                           f"current exposure: {current_exposure:.1%}, "
                           f"suggest +{max_suggested:.1%}"
            })
            
        # Sort by combination of correlation and opportunity (low current exposure)
        portfolio_aware_candidates.sort(
            key=lambda x: (x["correlation_to_overexposed"], x["current_portfolio_exposure"])
        )
        return portfolio_aware_candidates
        
    def generate_ai_context_tables(
        self,
        recommendations: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """
        Generate formatted CLI tables for Claude context (following existing pattern).
        
        Returns:
            Dict with formatted table strings that Claude can read and interpret
        """
        if not recommendations:
            return {"offset_recommendations": "No suitable offset factors found."}
            
        # Format as CLI table (similar to existing risk analysis tables)
        table_lines = []
        table_lines.append("FACTOR OFFSET RECOMMENDATIONS")
        table_lines.append("=" * 80)
        table_lines.append(f"{'Factor':<20} {'ETF':<8} {'Correlation':<12} {'Current Exp':<12} {'Suggested':<12} {'Sharpe':<8}")
        table_lines.append("-" * 80)
        
        for rec in recommendations[:5]:  # Top 5 recommendations
            table_lines.append(
                f"{rec['factor']:<20} "
                f"{rec['etf_ticker']:<8} "
                f"{rec['correlation_to_overexposed']:>10.2f} "
                f"{rec['current_portfolio_exposure']:>10.1%} "
                f"{rec['suggested_additional_allocation']:>10.1%} "
                f"{rec['sharpe_ratio']:>6.2f}"
            )
            
        table_lines.append("")
        table_lines.append("RATIONALE:")
        for i, rec in enumerate(recommendations[:3], 1):
            table_lines.append(f"{i}. {rec['rationale']}")
            
        return {
            "offset_recommendations": "\n".join(table_lines),
            "summary": f"Found {len(recommendations)} portfolio-aware offset opportunities"
        }
        
    def generate_correlation_matrix_table(
        self,
        focus_factors: List[str] = None,
        start_date: str = "2019-01-01", 
        end_date: str = "2024-01-01"
    ) -> str:
        """
        Generate formatted correlation matrix table for Claude context.
        
        Args:
            focus_factors: Specific factors to highlight (e.g., overexposed factors)
            
        Returns:
            Formatted correlation matrix table string
        """
        correlations = self._get_cached_correlations(start_date, end_date)
        
        if focus_factors:
            # Show correlations for focus factors vs. all other factors
            table_lines = []
            table_lines.append("FACTOR CORRELATION MATRIX")
            table_lines.append("=" * 100)
            table_lines.append(f"Period: {start_date} to {end_date}")
            table_lines.append("")
            
            for focus_factor in focus_factors:
                if focus_factor not in correlations.index:
                    continue
                    
                table_lines.append(f"CORRELATIONS WITH {focus_factor.upper()}:")
                table_lines.append("-" * 60)
                
                factor_corrs = correlations.loc[focus_factor].sort_values()
                
                # Show strongest negative correlations (hedges)
                negative_corrs = factor_corrs[factor_corrs < -0.1].head(5)
                if len(negative_corrs) > 0:
                    table_lines.append("Strongest Hedges (Negative Correlation):")
                    for factor, corr in negative_corrs.items():
                        if factor != focus_factor:
                            etf = self.all_factors.get(factor, "N/A")
                            table_lines.append(f"  {factor:<25} ({etf:<6}): {corr:>6.2f}")
                
                table_lines.append("")
                
                # Show strongest positive correlations (amplifiers to avoid)
                positive_corrs = factor_corrs[factor_corrs > 0.3].tail(5)
                if len(positive_corrs) > 0:
                    table_lines.append("Strongest Amplifiers (Positive Correlation - Avoid):")
                    for factor, corr in positive_corrs.items():
                        if factor != focus_factor:
                            etf = self.all_factors.get(factor, "N/A")
                            table_lines.append(f"  {factor:<25} ({etf:<6}): {corr:>6.2f}")
                
                table_lines.append("")
                
        else:
            # Show summary correlation statistics
            table_lines = []
            table_lines.append("FACTOR CORRELATION SUMMARY")
            table_lines.append("=" * 80)
            table_lines.append(f"Period: {start_date} to {end_date}")
            table_lines.append(f"Factors analyzed: {len(correlations)}")
            table_lines.append("")
            
            # Calculate correlation statistics
            corr_values = correlations.values[correlations.values != 1.0]  # Exclude diagonal
            avg_corr = corr_values.mean()
            max_corr = corr_values.max()
            min_corr = corr_values.min()
            
            table_lines.append(f"Average correlation: {avg_corr:>8.2f}")
            table_lines.append(f"Highest correlation: {max_corr:>7.2f}")
            table_lines.append(f"Lowest correlation:  {min_corr:>7.2f}")
            
        return "\n".join(table_lines)
        
    def generate_performance_profiles_table(
        self,
        top_n: int = 10,
        sort_by: str = "sharpe_ratio",
        start_date: str = "2019-01-01",
        end_date: str = "2024-01-01"
    ) -> str:
        """
        Generate formatted performance profiles table for Claude context.
        
        Args:
            top_n: Number of top factors to show
            sort_by: Metric to sort by ('sharpe_ratio', 'annual_return', 'volatility')
            
        Returns:
            Formatted performance table string
        """
        performance_profiles = self._get_cached_performance(start_date, end_date)
        
        table_lines = []
        table_lines.append("FACTOR PERFORMANCE PROFILES")
        table_lines.append("=" * 100)
        table_lines.append(f"Period: {start_date} to {end_date} | Sorted by: {sort_by}")
        table_lines.append("")
        table_lines.append(f"{'Factor':<25} {'ETF':<8} {'Return':<8} {'Vol':<8} {'Sharpe':<8} {'MaxDD':<8} {'Beta':<8}")
        table_lines.append("-" * 100)
        
        # Sort factors by specified metric
        sorted_factors = sorted(
            performance_profiles.items(),
            key=lambda x: x[1].get(sort_by, 0),
            reverse=(sort_by != 'volatility')  # Lower volatility is better
        )
        
        for factor, perf in sorted_factors[:top_n]:
            etf_ticker = self.all_factors.get(factor, "N/A")
            table_lines.append(
                f"{factor:<25} "
                f"{etf_ticker:<8} "
                f"{perf.get('annual_return', 0):>6.1%} "
                f"{perf.get('volatility', 0):>6.1%} "
                f"{perf.get('sharpe_ratio', 0):>6.2f} "
                f"{perf.get('max_drawdown', 0):>6.1%} "
                f"{perf.get('beta_to_market', 0):>6.2f}"
            )
            
        table_lines.append("")
        table_lines.append("Legend: Return=Annual Return, Vol=Volatility, Sharpe=Sharpe Ratio, MaxDD=Max Drawdown, Beta=Market Beta")
        
        return "\n".join(table_lines)
        
    def generate_comprehensive_analysis_tables(
        self,
        overexposed_factors: List[str],
        current_portfolio_exposures: Dict[str, float]
    ) -> Dict[str, str]:
        """
        Generate complete set of formatted tables for comprehensive factor analysis.
        
        Returns:
            Dict with all formatted tables for Claude context
        """
        tables = {}
        
        # 1. Performance profiles table
        tables["performance_profiles"] = self.generate_performance_profiles_table(
            top_n=15, sort_by="sharpe_ratio"
        )
        
        # 2. Correlation matrix focused on overexposed factors
        if overexposed_factors:
            tables["correlation_analysis"] = self.generate_correlation_matrix_table(
                focus_factors=overexposed_factors
            )
        else:
            tables["correlation_analysis"] = self.generate_correlation_matrix_table()
            
        # 3. Current portfolio factor exposure summary
        exposure_lines = []
        exposure_lines.append("CURRENT PORTFOLIO FACTOR EXPOSURES")
        exposure_lines.append("=" * 60)
        
        sorted_exposures = sorted(
            current_portfolio_exposures.items(), 
            key=lambda x: x[1], 
            reverse=True
        )
        
        for factor, exposure in sorted_exposures[:10]:
            etf_ticker = self.all_factors.get(factor, "N/A")
            status = "⚠️ HIGH" if exposure > 0.25 else "✅ OK" if exposure > 0.15 else "📊 LOW"
            exposure_lines.append(f"{factor:<25} ({etf_ticker:<6}): {exposure:>6.1%} {status}")
            
        tables["current_exposures"] = "\n".join(exposure_lines)
        
        return tables
        
    def _get_cached_correlations(self, start_date: str = "2019-01-01", end_date: str = "2024-01-01") -> pd.DataFrame:
        """Get correlation matrix with simple caching."""
        cache_key = f"{start_date}_{end_date}"
        if cache_key not in self._correlation_cache:
            self._correlation_cache[cache_key] = self.calculate_factor_correlations(start_date, end_date)
        return self._correlation_cache[cache_key]
        
    def _get_cached_performance(self, start_date: str = "2019-01-01", end_date: str = "2024-01-01") -> Dict[str, Dict[str, float]]:
        """Get performance profiles with simple caching."""
        cache_key = f"{start_date}_{end_date}"
        if cache_key not in self._performance_cache:
            self._performance_cache[cache_key] = self.calculate_factor_performance_profiles(start_date, end_date)
        return self._performance_cache[cache_key]
```

### **Integration Pattern (Following Your Existing Architecture)**

```python
# Usage in existing risk analysis workflow
def enhanced_risk_analysis_with_offsets(portfolio_data, risk_limits):
    # 1. Run existing portfolio risk analysis
    risk_result = analyze_portfolio(portfolio_data, risk_limits)
    
    # 2. Extract current factor exposures from risk analysis
    current_exposures = risk_result.get_factor_exposures()  # {"Real Estate": 0.35, ...}
    
    # 3. Identify overexposures from risk checks
    overexposed_factors = []
    for factor, exposure in current_exposures.items():
        if exposure > risk_limits.get(f"max_{factor}_exposure", 0.25):
            overexposed_factors.append(factor)
    
    # 4. Generate offset recommendations for each overexposure
    factor_engine = FactorIntelligenceEngine()
    offset_recommendations = {}
    
    for factor in overexposed_factors:
        recommendations = factor_engine.generate_portfolio_aware_recommendations(
            overexposed_factor=factor,
            current_portfolio_exposures=current_exposures,
            target_allocation_reduction=0.10
        )
        
        # 5. Generate AI-readable context tables
        ai_context = factor_engine.generate_ai_context_tables(recommendations)
        offset_recommendations[factor] = ai_context
    
    # 6. Add to existing risk result for Claude consumption
    risk_result.offset_recommendations = offset_recommendations
    return risk_result
```

## **Manual Review Process for AI Context Optimization**

### **Approach for Formatted Report Refinement**

Once the Factor Intelligence Engine is implemented, we'll follow this iterative process to optimize the AI context outputs:

**1. Initial Testing Phase**:
- Generate actual factor correlation matrices, performance profiles, and offset recommendations
- Review the `to_formatted_table()` outputs from each result object
- Test with real portfolio data to see actual recommendations

**2. Manual Review Criteria**:
- **Readability**: Are the tables easy to scan and understand at a glance?
- **Relevance**: Do the tables highlight the most important information for decision-making?
- **Completeness**: Is there missing context that would help Claude make better recommendations?
- **Conciseness**: Are the tables too verbose or could they be more focused?

**3. Iterative Refinement Process**:
```python
# Example refinement cycle:
# 1. Run factor analysis
result = service.analyze_factor_correlations(analysis_data)

# 2. Generate current formatted output
current_table = result.to_formatted_table()

# 3. Manual review questions:
# - Does this table help ME understand factor relationships?
# - What would I want to see if I were making offset recommendations?
# - Is the most important information prominently displayed?

# 4. Adjust table format based on findings
# 5. Test with Claude to see if recommendations improve
# 6. Repeat until satisfied
```

**4. Key Areas for Manual Review**:
- **Correlation Matrix**: Focus on strongest negative correlations for offset candidates
- **Performance Profiles**: Highlight risk-adjusted returns (Sharpe ratios) and drawdown characteristics  
- **Offset Recommendations**: Ensure portfolio context is clear and actionable
- **Data Quality Warnings**: Make exclusions and data gaps visible but not overwhelming

**5. Success Metrics**:
- Claude generates more specific, actionable offset recommendations
- Recommendations consider portfolio context appropriately
- Tables are useful for human review as well as AI consumption
- Reduced need for follow-up questions about factor relationships

This manual review approach ensures the formatted outputs serve both human analysts and AI integration effectively.

## **User-Defined Factor Groups Extension**

### **Enhanced Factor Index Creation with Market-Cap Weighting**

Building on the existing portfolio creation patterns, we'll add support for user-defined factor groups that can be treated as custom factor proxies in the Factor Intelligence Engine.

#### **Database Schema Extension**

```sql
-- New table for user-defined factor groups
CREATE TABLE user_factor_groups (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    group_name VARCHAR(100) NOT NULL,           -- e.g., "My Tech Basket", "ESG Leaders"
    description TEXT,                           -- Optional description
    tickers JSONB NOT NULL,                     -- Array of tickers: ["AAPL", "MSFT", "GOOGL"]
    weights JSONB,                              -- Optional custom weights: {"AAPL": 0.4, "MSFT": 0.35, "GOOGL": 0.25}
    weighting_method VARCHAR(20) DEFAULT 'equal', -- 'equal', 'market_cap', 'custom'
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(user_id, group_name)                 -- Prevent duplicate names per user
);

CREATE INDEX idx_user_factor_groups_user_id ON user_factor_groups(user_id);
```

#### **Factor Index Calculation Engine**

```python
# /core/factor_index.py
from typing import Dict, List, Optional, Tuple
import pandas as pd
import yfinance as yf
from data_loader import fetch_monthly_close
from utils.logging import log_error_handling, log_performance

@log_error_handling("high")
@log_performance(3.0)
def get_market_cap_weights(
    tickers: List[str],
    reference_date: Optional[str] = None
) -> Dict[str, float]:
    """
    Calculate market-cap based weights for a group of tickers.
    
    Args:
        tickers: List of stock tickers
        reference_date: Date for market cap calculation (defaults to most recent)
        
    Returns:
        Dict mapping tickers to normalized weights (sum = 1.0)
    """
    market_caps = {}
    
    for ticker in tickers:
        try:
            # Get market cap data using yfinance
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # Try multiple market cap fields (different providers use different names)
            market_cap = (
                info.get('marketCap') or 
                info.get('market_cap') or 
                info.get('sharesOutstanding', 0) * info.get('currentPrice', 0)
            )
            
            if market_cap and market_cap > 0:
                market_caps[ticker] = float(market_cap)
            else:
                # Fallback: use shares outstanding * current price
                shares = info.get('sharesOutstanding', 0)
                price = info.get('currentPrice', 0)
                if shares and price:
                    market_caps[ticker] = float(shares * price)
                    
        except Exception as e:
            # Log warning but continue with other tickers
            portfolio_logger.warning(f"Warning: Could not get market cap for {ticker}: {e}")
            continue
    
    if not market_caps:
        raise ValueError("Could not determine market cap for any tickers")
    
    # Normalize weights to sum to 1.0
    total_market_cap = sum(market_caps.values())
    weights = {ticker: cap / total_market_cap for ticker, cap in market_caps.items()}
    
    return weights

@log_error_handling("high") 
@log_performance(5.0)
def calculate_factor_index_returns(
    tickers: List[str],
    start_date: str,
    end_date: str,
    weights: Optional[Dict[str, float]] = None,
    weighting_method: str = 'equal'
) -> Tuple[pd.Series, Dict[str, any]]:
    """
    Calculate returns for a custom factor index from a group of stocks.
    
    This creates a synthetic "ETF" from the stock group that can be used
    as a factor proxy in correlation and performance analysis.
    
    Args:
        tickers: List of stock tickers to include in the index
        start_date: Start date for return calculation
        end_date: End date for return calculation  
        weights: Custom weights dict (only used if weighting_method='custom')
        weighting_method: 'equal', 'market_cap', or 'custom'
        
    Returns:
        Tuple of (index_returns_series, metadata_dict)
    """
    # Fetch price data for all tickers
    price_data = {}
    excluded_tickers = []
    
    for ticker in tickers:
        try:
            prices = fetch_monthly_close(ticker, start_date, end_date)
            if len(prices) >= 24:  # Minimum data requirement (following existing pattern)
                price_data[ticker] = prices
            else:
                excluded_tickers.append(f"{ticker} (insufficient data: {len(prices)} months)")
        except Exception as e:
            excluded_tickers.append(f"{ticker} (data error: {str(e)})")
            continue
    
    if not price_data:
        raise ValueError("No valid price data found for any tickers in the group")
    
    # Align all price series to common dates
    price_df = pd.DataFrame(price_data)
    price_df = price_df.dropna()  # Remove dates where any stock is missing
    
    if len(price_df) < 24:
        raise ValueError(f"Insufficient overlapping data: only {len(price_df)} months available")
    
    # Calculate individual stock returns
    returns_df = price_df.pct_change().dropna()
    
    # Determine weights based on method
    final_weights = {}
    weight_metadata = {}
    
    if weighting_method == 'equal':
        final_weights = {ticker: 1.0 / len(returns_df.columns) for ticker in returns_df.columns}
        weight_metadata = {
            "method": "equal",
            "description": "Equal weighting across all stocks"
        }
        
    elif weighting_method == 'market_cap':
        try:
            market_cap_weights = get_market_cap_weights(list(returns_df.columns))
            # Only include tickers that have both price data AND market cap data
            final_weights = {
                ticker: market_cap_weights[ticker] 
                for ticker in returns_df.columns 
                if ticker in market_cap_weights
            }
            
            if not final_weights:
                raise ValueError("No market cap data available for any tickers")
                
            # Renormalize in case some tickers were excluded
            total_weight = sum(final_weights.values())
            final_weights = {ticker: weight / total_weight for ticker, weight in final_weights.items()}
            
            weight_metadata = {
                "method": "market_cap",
                "description": "Market capitalization weighted",
                "market_caps": {ticker: f"${market_cap_weights.get(ticker, 0):,.0f}" 
                              for ticker in final_weights.keys()}
            }
            
        except Exception as e:
            # Fallback to equal weighting if market cap fails
            final_weights = {ticker: 1.0 / len(returns_df.columns) for ticker in returns_df.columns}
            weight_metadata = {
                "method": "equal (market_cap_fallback)",
                "description": f"Equal weighting (market cap failed: {str(e)})"
            }
            excluded_tickers.append(f"Market cap weighting failed: {str(e)}")
            
    elif weighting_method == 'custom' and weights:
        # Normalize custom weights to sum to 1, only for tickers with data
        available_tickers = set(returns_df.columns)
        custom_weights = {ticker: weight for ticker, weight in weights.items() 
                         if ticker in available_tickers}
        
        if not custom_weights:
            raise ValueError("None of the custom weighted tickers have sufficient price data")
            
        total_weight = sum(custom_weights.values())
        final_weights = {ticker: weight / total_weight for ticker, weight in custom_weights.items()}
        
        weight_metadata = {
            "method": "custom",
            "description": "User-defined custom weights",
            "original_weights": weights,
            "normalized_weights": final_weights
        }
        
    else:
        raise ValueError(f"Invalid weighting method: {weighting_method}")
    
    # Calculate weighted index returns
    index_returns = pd.Series(0.0, index=returns_df.index)
    for ticker in final_weights.keys():
        if ticker in returns_df.columns:
            weight = final_weights[ticker]
            index_returns += returns_df[ticker] * weight
    
    # Prepare metadata
    metadata = {
        "tickers_included": list(final_weights.keys()),
        "tickers_excluded": excluded_tickers,
        "final_weights": final_weights,
        "weight_metadata": weight_metadata,
        "data_points": len(index_returns),
        "date_range": f"{index_returns.index[0].strftime('%Y-%m-%d')} to {index_returns.index[-1].strftime('%Y-%m-%d')}"
    }
    
    return index_returns, metadata

@log_error_handling("medium")
def create_factor_proxy_from_group(
    group_name: str,
    tickers: List[str],
    start_date: str,
    end_date: str,
    weights: Optional[Dict[str, float]] = None,
    weighting_method: str = 'equal'
) -> Tuple[str, Dict]:
    """
    Create and validate a factor proxy identifier for a user-defined group.
    
    Returns:
        Tuple of (proxy_identifier, validation_metadata)
        proxy_identifier: Like "USER:My_Tech_Basket" 
        validation_metadata: Details about data quality and composition
    """
    try:
        returns, metadata = calculate_factor_index_returns(
            tickers, start_date, end_date, weights, weighting_method
        )
        
        if len(returns) < 24:
            raise ValueError(f"Insufficient data for group '{group_name}': only {len(returns)} observations")
        
        # Return standardized proxy identifier
        safe_name = group_name.replace(' ', '_').replace('-', '_')
        proxy_id = f"USER:{safe_name}"
        
        return proxy_id, metadata
        
    except Exception as e:
        raise ValueError(f"Cannot create factor proxy for group '{group_name}': {str(e)}")
```

#### **Integration with Factor Intelligence Engine**

```python
# Enhanced integration in /core/factor_intelligence.py

def fetch_factor_returns_with_user_groups(
    factor_proxy: str,
    start_date: str,
    end_date: str,
    user_id: Optional[int] = None
) -> pd.Series:
    """
    Fetch returns for any factor proxy, including user-defined groups.
    Supports both ETF proxies and user-defined factor indices.
    """
    if factor_proxy.startswith("USER:"):
        # Handle user-defined factor group
        if not user_id:
            raise ValueError("user_id required for user-defined factor groups")
        
        group_name = factor_proxy.replace("USER:", "").replace("_", " ")
        
        # Get group definition from database
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            group_data = db_client.get_user_factor_group(user_id, group_name)
        
        if not group_data:
            raise ValueError(f"User-defined factor group '{group_name}' not found")
        
        # Calculate index returns with proper weighting
        returns, metadata = calculate_factor_index_returns(
            tickers=group_data['tickers'],
            start_date=start_date,
            end_date=end_date,
            weights=group_data.get('weights'),
            weighting_method=group_data.get('weighting_method', 'equal')
        )
        
        return returns
    else:
        # Handle standard ETF proxy (existing logic)
        return fetch_monthly_close(factor_proxy, start_date, end_date).pct_change().dropna()
```

#### **Weighting Method Examples**

**Equal Weighting:**
- Each stock gets 1/N weight regardless of size
- Good for: Small portfolios, equal exposure strategies
- Example: AAPL=25%, MSFT=25%, GOOGL=25%, TSLA=25%

**Market-Cap Weighting:**
- Weights based on current market capitalization
- Good for: Market-representative indices, large-cap focus
- Example: AAPL=45%, MSFT=30%, GOOGL=20%, TSLA=5% (based on actual market caps)

**Custom Weighting:**
- User-defined weights for specific allocation strategies
- Good for: Strategic tilts, risk budgeting
- Example: User sets AAPL=40%, MSFT=35%, GOOGL=15%, TSLA=10%

This enhanced approach gives you the flexibility to create realistic factor indices that can be weighted like actual market indices or customized for specific investment strategies!

## **Future Enhancement Opportunities**

### **Performance & Scalability Enhancements**

1. **Async Factor Intelligence Service**:
   - Async wrapper for factor correlation analysis (5-10 second operations)
   - Concurrent processing of multiple factor groups
   - Background factor universe updates

2. **Batch Operations**:
   - Batch validation of multiple user-defined factor groups
   - Concurrent factor group creation and testing
   - Bulk factor analysis across different time periods

3. **Progress Tracking**:
   - Real-time progress callbacks for long-running factor analysis
   - UI progress bars for factor correlation calculations
   - Status updates for factor group validation

### **Advanced Factor Intelligence Features**

4. **Factor Universe Versioning**:
   - Track changes to factor mappings over time
   - Handle deprecated factors gracefully
   - Migration paths for factor universe updates

5. **Factor Analysis Presets**:
   - Pre-configured analysis templates (equity-only, multi-asset, etc.)
   - Industry-specific factor universes (tech, healthcare, etc.)
   - Risk-based factor groupings (low-vol, momentum, value)

6. **Real-time Factor Monitoring**:
   - Detect correlation regime changes
   - Alert on significant factor relationship shifts
   - Historical correlation stability analysis

### **User Experience Enhancements**

7. **Factor Group Templates**:
   - Common factor group templates (FAANG, Dividend Aristocrats, etc.)
   - Industry-based templates with automatic stock selection
   - ESG-focused factor group builders

8. **Advanced Weighting Methods**:
   - Volatility-adjusted weighting
   - Risk parity weighting within factor groups
   - Dynamic rebalancing for factor groups

9. **Factor Performance Attribution**:
   - Decompose portfolio returns by factor contributions
   - Factor timing analysis (when factors performed well/poorly)
   - Factor momentum and mean reversion indicators

*Note: These enhancements can be implemented incrementally based on user feedback and usage patterns. The core Factor Intelligence Engine design is complete and production-ready.*
# Market Sensitivity Example Output Shape
# correlations["market_sensitivity"] might look like:
# {
#   "XLU":  {"SPY": 0.62, "ACWX": 0.55},
#   "XLRE": {"SPY": 0.74, "ACWX": 0.60},
#   "IEF":  {"SPY": -0.28, "ACWX": -0.22}
# }
# Macro Composite Matrix Example
# correlations["macro_composite_matrix"] might look like:
# {
#   "groups": ["equity","fixed_income","cash","commodity","crypto"],
#   "matrix": {
#     "equity_composite":      {"fixed_income_composite": -0.36, "cash_composite": -0.05, "commodity_composite": 0.08, "crypto_composite": 0.21},
#     "fixed_income_composite": {"equity_composite": -0.36, ...}
#   }
# }

# Macro ETF Matrix Example (curated ETFs from macro groups)
# correlations["macro_etf_matrix"] might look like:
# {
#   "groups": {"equity": ["SPY","XLK"], "fixed_income": ["IEF","TLT"], "cash": ["SGOV"], "commodity": ["GLD"], "crypto": ["BTC_SPOT_ETF"]},
#   "matrix": {
#     "SPY": {"XLK": 0.89, "IEF": -0.32, "TLT": -0.41, "SGOV": -0.06, "GLD": 0.05, "BTC_SPOT_ETF": 0.28},
#     "XLK": {"IEF": -0.27, ...}
#   }
# }
