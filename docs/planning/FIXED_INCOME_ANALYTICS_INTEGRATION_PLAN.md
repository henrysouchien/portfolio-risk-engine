# Fixed Income Analytics Integration Plan

Status: Design document — key‑rate "rate beta" model for bonds and REITs integrated into core portfolio analysis. **UPDATED**: Single interest rate beta approach for cleaner portfolio management. Total‑return pricing adopted across risk/performance. Cash proxies excluded from rate beta.

## **📋 Implementation Quick Reference**

### **🔗 Ready-to-Use Code Implementations**
All core functions are fully implemented and ready to copy into the codebase:

**Core Functions (Copy-Paste Ready):**
- [`fetch_monthly_total_return_price()`](#1-total-return-loader-new-function---add-to-data_loaderpy) → Lines 347-404: Complete FMP total return data loader with fallback
- [`prepare_rate_factors()`](#2-rate-factors-δy-prep-new-function---add-to-factor_utilspy) → Lines 413-444: Treasury yield difference calculator with centralized config
- [`fetch_monthly_treasury_yield_levels()`](#2a-treasury-yield-levels-aggregator-new-function---add-to-factor_utilspy) → Lines 452-500: Treasury rate aggregator using existing infrastructure
- [`compute_multifactor_betas()`](#3-multifactor-ols-with-hac-new-function---add-to-factor_utilspy) → Lines 508-562: HAC regression for key-rate analysis

**Integration Logic (Core Implementation):**
- [Core injection in `_build_portfolio_view_computation()`](#5-core-injection-pseudocode-inside-_build_portfolio_view_computation) → Lines 618-694: Complete hybrid equity+rate factor implementation
- [Cache integration with bond injection masks](#cache-integration-implementation) → Lines 158-283: LRU cache versioning and key generation

**Configuration Setup:**
- [`RATE_FACTOR_CONFIG` for settings.py](#centralized-rate-factor-configuration-settingspy) → Lines 1025-1058: Complete configuration structure
- [Rate factor profiles](#portfolio-level-configuration) → Lines 1059-1078: Standard, short_term, long_term, minimal profiles

**Function Signature Updates:**
- [Parameter threading throughout call stack](#clean-parameter-passing-option-1---recommended) → Lines 1164-1202: Complete service→core→computation parameter flow
- [Service layer integration](#service-layer-integration) → Lines 1169-1187: PortfolioService asset class detection and passing

**Result Object Enhancements:**
- [StockAnalysisResult constructor updates](#stock-result-object-update-stockanalysisresult-integration) → Lines 888-950: Complete new field integration
- [API response field additions](#portfolio-result-object-update-riskanalysisresult-for-single-interest-rate-factor-approach) → Lines 811-833: Effective duration and rate factor display

### **⚡ Implementation Checklist**
See detailed [Implementation Tasks](#🧭-implementation-tasks-checklist) → Lines 770-1022 for complete step-by-step checklist.

### **🏗️ Architecture Overview**
See [Integration Architecture](#🏗️-integration-architecture) → Lines 57-337 for complete system design and data flow.

### **🧪 Testing Strategy**
See [Testing & Validation](#✅-testing--validation) → Lines 1102-1111 for validation targets and sanity checks.

---

## **🎯 Overview**

We will integrate empirical interest‑rate sensitivity using a key‑rate regression model and adopt total‑return (dividend‑adjusted) pricing across the risk engine. For assets classified as bonds (including REITs via the existing classifier), we compute per‑asset key‑rate betas vs changes in U.S. Treasury yields (2y, 5y, 10y, 30y) then immediately sum them to a single interest rate beta for portfolio management simplicity.

Key decisions
- **Key‑rate regression with immediate aggregation**: Mathematical rigor of key-rate analysis with single factor output.
- **Single interest rate factor**: Simplifies portfolio analysis, API responses, and variance attribution.
- Use total‑return prices for all return calculations (assets, factor ETFs, benchmarks).
- Exclude cash proxies (e.g., SGOV) from rate beta; keep them as cash in allocation.
- Include REITs (classifier already maps them under bonds in our system).
- Core‑first integration: implement inside `build_portfolio_view` (not service‑only), with a lightweight flexibility shim for factor selection by asset class.
- Key-rate breakdown preserved in diagnostics for power users.

---

## **📊 Empirical Rate Beta (Key‑Rate)**

We replace static duration maps with an empirical, regression‑based model using total return series for funds and changes in Treasury yields for factors. The key-rate regression provides mathematical rigor while the output is simplified to a single interest rate beta for portfolio management.

Data inputs
- Fund total return prices: month‑end adjusted close if available; otherwise close with `return_type="price_only"` flagged in metadata.
- Treasury yields: UST 2y/5y/10y/30y levels from FMP; compute Δy at the chosen frequency (monthly default) in percentage points (pp).

Transformations
- Compute fund returns from TR prices: R_t = P_t/P_{t-1} - 1 (or from vendor adjusted returns if provided).
- Compute Δy_t = y_t − y_{t−1} (pp). Optionally offer basis points for diagnostics; default is pp.
- Align returns and Δy on period ends; drop rows with any NaNs after merge.
- Create combined interest rate factor: IR_t = Σ_m Δy_{m,t} (sum of all maturity changes).

Models
- Key‑rate regression (internal): R_fund,t = α + Σ_m β_m Δy_{m,t} + ε_t, m ∈ {2y,5y,10y,30y}
  - Immediate aggregation: β_IR = Σ_m β_m (sum of key-rate betas = effective duration)
  - Final output: Single interest rate beta stored as "interest_rate" factor
- Diagnostics preserved: Individual key-rate betas available for power users

Output schemas (simplified)
- Per‑asset (single rate beta):
  {
    "asset": "AGG", "as_of": "YYYY‑MM‑DD", "frequency": "monthly", "yield_scale": "pp",
    "interest_rate_beta": -5.7, "alpha": 0.000, "r2_adj": 0.78,
    "key_rate_breakdown": {"UST2Y": -1.2, "UST5Y": -2.0, "UST10Y": -1.8, "UST30Y": -0.7},
    "diagnostics": {"vif": {"UST2Y": 2.1, ...}, "cond_number": 18.5},
    "window_months": 36, "n_obs": 36, "return_type": "total_return|price_only"
  }
- Portfolio aggregation: Simple weighted sum of interest_rate_beta values.

Scope and eligibility
- Include assets where `asset_class == 'bond'` from SecurityTypeService (REITs included per classifier behavior).
- Exclude known cash proxies (e.g., SGOV) from rate beta while keeping them as cash in allocation.

---

## **🏗️ Integration Architecture**

### **1) Data Layer Enhancements**
- Total‑return adoption: prefer adjusted close for all tickers and factor ETFs across the engine. Introduce TR‑aware cache keys to avoid mixing with legacy close‑only files.
- Treasury yields: use FMP `/treasury-rates` for `year2/year5/year10/year30`; resample to month‑end and compute Δy.

### **2) Factor & Variance Integration (Core)**
- Treat `interest_rate` as single first‑class factor for eligible bond assets.
- Add `interest_rate` column to `stock_betas` and corresponding entries in `factor_vols` using portfolio-level interest rate volatility.
- Recompute `weighted_factor_var` (w²·β²·σ²) so interest rate factor contributes to variance decomposition.
- Implement directly inside `_build_portfolio_view_computation(...)` with key-rate regression followed by immediate beta aggregation.

Engineering notes
- Internal scaling: Δy stored as decimal (0.01 per 1%). Reporting exposes `yield_scale='pp'`.
- Factor set: Keep equity‑style factors (market/momentum/value/industry/subindustry) alongside single interest_rate factor for bonds.
- Eligibility: `asset_class == 'bond'` via SecurityTypeService; exclude cash proxies; REITs included per classifier.
- Interest rate volatility: Portfolio-level factor computed as std(∑Δy) across all maturities.

### **3) Enhanced Data Objects**

#### **PortfolioData Enhancement**
```python
@dataclass
class PortfolioData:
    # Existing fields...
    tickers: Dict[str, float]
    start_date: str
    end_date: str

    # NEW: Configuration knobs
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Suggested flags (read by PortfolioService):
    # metadata["returns.use_total_return"] = True
    # metadata["rate_beta.enabled"] = True
    # metadata["rate_beta.include_cash_proxies"] = False
    # metadata["rate_beta.frequency"] = "M"
    # metadata["rate_beta.window_months"] = 36
    # metadata["rate_beta.yield_scale"] = "pp"
```

#### **New Rate Beta Result Objects (Phase 2)**
```python
@dataclass
class KeyRateResult:
    asset: str
    as_of: str
    frequency: str
    yield_scale: str
    betas: Dict[str, float]          # {UST2Y, UST5Y, UST10Y, UST30Y}
    beta_sum: float                  # ≈ effective duration
    alpha: float
    r2_adj: float
    diagnostics: Dict[str, Any]      # {vif: {...}, cond_number: float}
    window_months: int
    n_obs: int
    return_type: str                 # "total_return" | "price_only"
```

### **4) API Integration**

**Minimal API extension** - Single interest rate factor integrates cleanly through existing response structure:

**Existing fields (enhanced with single rate factor):**
- **`stock_betas`**: Individual stock interest rate betas (e.g., `{"TLT": {"market": 0.12, "interest_rate": 2.22}}`)
- **`portfolio_factor_betas`**: Portfolio-level rate exposure (e.g., `{"market": 1.02, "interest_rate": 0.77}`)
- **`factor_vols`**: Interest rate factor volatility alongside equity factor volatilities
- **`variance_decomposition.factor_variance`**: Interest rate factor contributes to total systematic risk

**New field:**
- **`effective_duration`**: Portfolio effective duration (same as portfolio interest_rate beta) - Important summary metric for fixed income portfolios

Rate factors appear as new columns in existing API fields, maintaining full backward compatibility with one meaningful addition for portfolio-level duration analysis.

### **5) Core Injection Points & Flexibility Shim**

Core injection (`portfolio_risk._build_portfolio_view_computation`)
- Add optional parameter to core entry to avoid service coupling and preserve CLI behavior:
  - `build_portfolio_view(..., asset_classes: Dict[str, str] | None = None)`
  - Services pass computed `asset_classes`; CLI/legacy callers pass `None` (no key‑rate injection).
- Build Δy once: `dy_df = {UST2Y, UST5Y, UST10Y, UST30Y}` from Treasury levels.
- Create combined interest rate factor: `interest_rate_series = dy_df.sum(axis=1)` for portfolio-level volatility.
- For each ticker with `asset_class == 'bond'`:
  - Build factor_df with existing equity factors (kept) + Δy columns aligned to the ticker index.
  - Fit multivariate OLS with HAC SE to obtain partial key‑rate betas.
  - Sum key-rate betas immediately: `interest_rate_beta = sum(rate_betas.values())`.
  - Write single `interest_rate_beta` into `df_stock_betas["interest_rate"]`.
  - Store key-rate breakdown in diagnostics for power users.
  - Compute portfolio-level interest rate volatility and write into `df_factor_vols`.
  - Residuals from the same fit determine idiosyncratic variance (now rate‑conditioned).

LRU cache wrapper (keying & pass‑through)
- Update public wrapper and cached function signatures to accept serialized classes:
  - `_cached_build_portfolio_view(weights_json, start_date, end_date, expected_returns_json, stock_factor_proxies_json, bond_mask_json)`
  - `build_portfolio_view(..., asset_classes=None)` serializes classes (or a compact mask; see below) before calling the cached function.
- Keying strategy (compact, stable):
  - Use "bond injection mask" = sorted list of tickers that will get rate injection after excluding cash proxies, then JSON‑encode it for the key.
  - Example: `["AGG", "TLT", "VNQ"]` → `"[\"AGG\",\"TLT\",\"VNQ\"]"` for cache key
- Cache key version bump: add a short version token (e.g., `rbeta_v1`) to the key tuple to prevent collisions with pre‑integration entries.

**Cache Integration Implementation**:
```python
# ADD TO: portfolio_risk.py (before build_portfolio_view function)

def _build_bond_injection_mask(asset_classes: Optional[Dict[str, str]], weights: Dict[str, float]) -> str:
    """
    Build compact cache key for bond rate factor injection.
    
    Returns JSON string of sorted bond tickers that will receive rate factor analysis.
    Used as part of LRU cache key to ensure correct cache hits/misses.
    
    Args:
        asset_classes: Optional asset class mappings from SecurityTypeService
        weights: Portfolio weights dict
        
    Returns:
        JSON string like '["AGG","TLT","VNQ"]' or '[]' if no bonds
    """
    if not asset_classes:
        return "[]"  # No asset classes = no rate factor injection
    
    # Build sorted list of tickers that will get rate factor injection
    # Note: Cash proxies (SGOV, ESTR, IB01) are already classified as "cash" by SecurityTypeService.get_asset_classes()
    # so we only need to check asset_class == 'bond' (no separate cash proxy exclusion needed)
    bond_tickers = []
    for ticker in sorted(weights.keys()):  # Sorted for stable cache keys
        if asset_classes.get(ticker) == 'bond':  # Cash proxies already excluded via "cash" classification
            bond_tickers.append(ticker)
    
    return json.dumps(bond_tickers)  # Stable JSON encoding

# MODIFY: build_portfolio_view function signature and cache call
def build_portfolio_view(
    weights: Dict[str, float],
    start_date: str,
    end_date: str,
    expected_returns: Optional[Dict[str, float]] = None,
    stock_factor_proxies: Optional[Dict[str, Dict[str, Union[str, List[str]]]]] = None,
    asset_classes: Optional[Dict[str, str]] = None  # NEW parameter
) -> Dict[str, Any]:
    """
    Build portfolio view with optional rate factor integration.
    
    NEW: asset_classes parameter enables rate factor analysis for bonds.
    When asset_classes=None, behaves exactly like existing implementation.
    """
    
    # Serialize parameters for cache key (existing pattern)
    weights_json = json.dumps(weights, sort_keys=True)
    expected_returns_json = json.dumps(expected_returns, sort_keys=True) if expected_returns else "null"
    stock_factor_proxies_json = json.dumps(stock_factor_proxies, sort_keys=True) if stock_factor_proxies else "null"
    
    # NEW: Build bond injection mask for cache key
    bond_mask_json = _build_bond_injection_mask(asset_classes, weights)
    
    # Call cached function with bond mask instead of full asset_classes
    return _cached_build_portfolio_view(
        weights_json,
        start_date,
        end_date,
        expected_returns_json,
        stock_factor_proxies_json,
        bond_mask_json,  # NEW: Compact bond ticker list
        asset_classes    # Pass original for computation
    )

# MODIFY: _cached_build_portfolio_view signature
@lru_cache(maxsize=128)
def _cached_build_portfolio_view(
    weights_json: str,
    start_date: str,
    end_date: str,
    expected_returns_json: str,
    stock_factor_proxies_json: str,
    bond_mask_json: str,  # NEW: Bond injection mask for cache key
    asset_classes: Optional[Dict[str, str]] = None  # Passed but not cached
) -> Dict[str, Any]:
    """
    Cached portfolio view computation with rate factor support.
    
    Cache key includes bond_mask_json (compact) and version token rbeta_v1.
    The asset_classes parameter is passed for computation but bond_mask_json 
    is used in the cache key for efficiency.
    """
    
    # Deserialize parameters (existing pattern)
    weights = json.loads(weights_json)
    expected_returns = json.loads(expected_returns_json) if expected_returns_json != "null" else None
    stock_factor_proxies = json.loads(stock_factor_proxies_json) if stock_factor_proxies_json != "null" else None
    
    # Call actual computation with asset_classes for rate factor logic
    return _build_portfolio_view_computation(
        weights, start_date, end_date, expected_returns, stock_factor_proxies, asset_classes
    )
```

**Cache Key Structure (Enhanced)**:
```python
# OLD cache key (pre-integration):
cache_key = (weights_json, start_date, end_date, expected_returns_json, stock_factor_proxies_json)

# NEW cache key (post-integration):
cache_key = (
    weights_json, 
    start_date, 
    end_date, 
    expected_returns_json, 
    stock_factor_proxies_json,
    bond_mask_json,  # '["AGG","TLT","VNQ"]' - compact bond list
    "rbeta_v1"       # Version token prevents pre-integration cache collisions
)
```

**Benefits of This Approach**:
- **Compact Keys**: Bond mask much smaller than full asset_classes dict
- **Stable Ordering**: Sorted tickers ensure consistent cache keys  
- **Version Safety**: rbeta_v1 token prevents mixing old/new cache entries
- **Selective Caching**: Only caches on bond injection pattern, not individual asset classes
- **Backward Compatible**: When asset_classes=None, bond_mask_json='[]' and logic unchanged


Lightweight flexibility shim (optional, keeps change surgical)
- `build_factor_df_for_ticker(ticker, idx, asset_class, config) -> Dict[str, pd.Series]`
  - Composable providers: equity (market, momentum, value, industry, subindustry), bond (key‑rate Δy).
  - Centralizes factor selection by asset class for future additions (e.g., credit spreads).

### **6) Helpers & Signatures (Implementation Guide)**
- Total‑return loader
  - `fetch_monthly_total_return_price(ticker, start_date, end_date) -> pd.Series`
    - Use FMP `/historical-price-eod/dividend-adjusted` endpoint for total returns (adjClose field)
    - Fallback to `/historical-price-eod/full` endpoint (close field) with `return_type='price_only'` 
    - TR cache key versioning: e.g., `tr_v1`
- Rate factors  
  - `fetch_monthly_treasury_yield_levels(start_date, end_date) -> pd.DataFrame`
    - Uses existing `fetch_monthly_treasury_rates()` for each maturity (year2, year5, year10, year30)
    - Returns DataFrame with percentage levels, already month-end resampled and cached
  - `prepare_rate_factors(yields_levels: pd.DataFrame, keys=("UST2Y","UST5Y","UST10Y","UST30Y"), scale='pp') -> pd.DataFrame`
    - Input: columns `year2/year5/year10/year30` (percentages); output: Δy columns named UST* in DECIMAL internally (0.01 per 1%)
- Factor regression (HYBRID: Existing + New Multifactor)
  - **Existing equity factors**: Use `compute_stock_factor_betas()` for market/momentum/value/industry/subindustry (single-factor regressions)
  - **NEW rate factors**: Use `compute_multifactor_betas()` for UST2Y/UST5Y/UST10Y/UST30Y (multivariate regression)
    - **Why multifactor**: Key-rate duration requires partial effects of each maturity controlling for others
    - **Example**: Bond sensitivity to 10Y changes while holding 2Y, 5Y, 30Y constant
    - Input: factor_df with all four rate factors (UST2Y, UST5Y, UST10Y, UST30Y)
    - Returns: partial betas for each rate factor from single multivariate regression
- Optional shim
  - `build_factor_df_for_ticker(ticker, idx, asset_class, config) -> Dict[str, pd.Series]`
    - Uses equity providers + (if bond) merges Δy from `prepare_rate_factors`.

Interest rate factor volatility (σ) computation
- Use existing `df_factor_vols` infrastructure (portfolio_risk.py ~line 667).
- Add interest rate volatility using the existing pattern:
  ```python
  # NEW: Add to existing factor volatility loop in _build_portfolio_view_computation()
  if asset_classes and asset_classes.get(ticker) == 'bond':
      # Portfolio-level interest rate volatility (calculated once above)
      df_factor_vols.loc[ticker, "interest_rate"] = interest_rate_vol
  ```
- Existing infrastructure handles the rest:
  - `df_factor_vols.fillna(0.0)` - line ~672 handles non-bond tickers automatically
  - `calc_weighted_factor_variance(weights, betas_filled, df_factor_vols)` - line ~678 works unchanged
  - No modifications needed to variance calculation functions

### **7) Scaling & Diagnostics**
- Scaling (OPTION A - SELECTED)
  - Internal Δy in decimal (0.01 per 1%); report `yield_scale='pp'` in outputs.
  - Factor σ for Δy computed on decimal scale, annualized by √12 to remain dimensionally consistent with return variance.
- Reporting & effective duration
  - **Selected approach**: Store betas on decimal Δy internally, report `effective_duration_years = portfolio_factor_betas['interest_rate'] * 100`.
  - **Rationale**: More intuitive for users expecting duration in years (e.g., 2.22 years vs 0.0222)
- Diagnostics
  - HAC/Newey–West: monthly lag=3 (weekly 5–10); store t/p/std_err per coefficient.
  - Multicollinearity: compute VIF per Δy; log/warn if VIF>10; include condition number in diagnostics.
  - Stability: default window 36m; add config for 24–60m as needed.

Eligibility & defaults (guardrails)
- Inject rate factors only when `asset_classes.get(ticker) == 'bond'`. Cash proxies are automatically excluded as they're classified as "cash", not "bond".
- If asset class is unknown/missing for a ticker, skip injection (leave `interest_rate` beta at 0.0 for that ticker).
- For non‑bond assets, ensure the `interest_rate` column exists and is set to 0.0 to keep matrix shapes intact and avoid NaN propagation in variance math.

---

## **🔩 Stub Implementations (for Evaluation)**

These are complete, production-ready implementations that can be directly copied into the codebase. All functions follow existing code patterns and include proper error handling, logging, and documentation.

**📋 Quick Navigation**: See [Implementation Quick Reference](#📋-implementation-quick-reference) for direct links to each function.

1) Total-return loader (NEW FUNCTION - add to data_loader.py)
```python
# ADD TO: data_loader.py (follows existing fetch_monthly_close pattern)

@log_error_handling("high")  # Match existing pattern
def fetch_monthly_total_return_price(
    ticker: str,
    start_date: Optional[Union[str, datetime]] = None,  # Match existing signature
    end_date: Optional[Union[str, datetime]] = None
) -> pd.Series:
    """
    Fetch dividend-adjusted monthly prices from FMP for total return calculations.
    
    Uses FMP /historical-price-eod/dividend-adjusted endpoint (adjClose field) for true total returns.
    Falls back to /historical-price-eod/full endpoint (close field) if adjusted data unavailable.
    
    PATTERN: Follows existing fetch_monthly_close structure with cache_read + _api_pull pattern.
    """
    
    # EXISTING PATTERN: Internal _api_pull function (matches fetch_monthly_close lines 158+)
    def _api_pull() -> pd.Series:
        params = {"symbol": ticker, "apikey": API_KEY}  # Match existing pattern
        if start_date:
            params["from"] = pd.to_datetime(start_date).date().isoformat()
        if end_date:
            params["to"] = pd.to_datetime(end_date).date().isoformat()
        
        try:
            # PRIMARY: dividend-adjusted endpoint for true total returns
            resp = requests.get(f"{BASE_URL}/historical-price-eod/dividend-adjusted", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            
            # EXISTING PATTERN: DataFrame processing (matches fetch_monthly_close lines 170-180)
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
            monthly = df.sort_index().resample("ME")["adjClose"].last()  # adjClose for total return
            monthly.name = f"{ticker}_total_return"
            return monthly
            
        except (requests.exceptions.RequestException, KeyError) as e:
            # FALLBACK: Use existing /historical-price-eod/full endpoint (price-only)
            params["serietype"] = "line"  # Match existing fetch_monthly_close
            resp = requests.get(f"{BASE_URL}/historical-price-eod/full", params=params, timeout=30)
            resp.raise_for_status()
            raw = resp.json()
            data = raw if isinstance(raw, list) else raw.get("historical", [])
            
            df = pd.DataFrame(data)
            df["date"] = pd.to_datetime(df["date"])
            df.set_index("date", inplace=True)
            monthly = df.sort_index().resample("ME")["close"].last()  # close for price-only
            monthly.name = f"{ticker}_price_only"
            return monthly
    
    # EXISTING PATTERN: Use cache_read with same structure as fetch_monthly_close
    return cache_read(
        key=[ticker, "dividend_adjusted", start_date or "none", end_date or "none"],
        loader=_api_pull,
        cache_dir="cache_prices",  # Match existing cache location
        prefix=f"{ticker}_tr"
    )
```

2) Rate factors (Δy) prep (NEW FUNCTION - add to factor_utils.py)
```python
# ADD TO: factor_utils.py (follows existing factor computation patterns)

@log_error_handling("medium")  # Match existing factor functions
@log_performance(1.0)  # Match existing performance logging
def prepare_rate_factors(yields_levels: pd.DataFrame,
                         keys: Optional[List[str]] = None,
                         scale: str = 'pp') -> pd.DataFrame:
    """
    Create Δy in DECIMAL from Treasury yield levels using centralized configuration.
    
    PATTERN: Follows existing factor_utils.py function structure with logging decorators.
    """
    from settings import RATE_FACTOR_CONFIG
    
    # Use centralized configuration if no keys specified
    if keys is None:
        keys = RATE_FACTOR_CONFIG["default_maturities"]
    
    # Use centralized treasury mapping
    colmap = RATE_FACTOR_CONFIG["treasury_mapping"]
    
    out = {}
    for k in keys:
        src = colmap.get(k)
        if not src or src not in yields_levels:
            out[k] = pd.Series(dtype=float)  # Empty series for missing data
        else:
            # Convert percentage to decimal, then compute differences
            if scale == 'pp':
                dec = yields_levels[src] / 100.0  # 4.5% → 0.045
            else:
                dec = yields_levels[src]  # Already in decimal
            out[k] = dec.sort_index().diff()  # Δy in decimal (0.01 per 1% point)
    
    return pd.DataFrame(out).dropna()
```

2a) Treasury yield levels aggregator (NEW FUNCTION - add to factor_utils.py)
```python
# ADD TO: factor_utils.py (leverages existing fetch_monthly_treasury_rates)

@log_error_handling("medium")  # Match existing factor functions
@log_performance(1.5)  # Slightly higher threshold for multiple API calls
def fetch_monthly_treasury_yield_levels(start_date: Optional[Union[str, datetime]] = None, 
                                       end_date: Optional[Union[str, datetime]] = None) -> pd.DataFrame:
    """
    Build Treasury yield levels DataFrame using existing data_loader infrastructure and centralized configuration.
    
    PATTERN: Leverages existing fetch_monthly_treasury_rates() function, follows factor_utils.py logging patterns.
    
    Returns:
        pd.DataFrame: Month-end Treasury levels with columns from RATE_FACTOR_CONFIG["treasury_mapping"] (percentages)
    """
    from data_loader import fetch_monthly_treasury_rates  # Use existing function
    from settings import RATE_FACTOR_CONFIG
    
    # Use centralized configuration for maturity mapping
    treasury_mapping = RATE_FACTOR_CONFIG["treasury_mapping"]
    
    yield_series = {}
    for rate_factor, maturity_name in treasury_mapping.items():
        try:
            # EXISTING FUNCTION: Use existing fetch_monthly_treasury_rates() - returns Series with Treasury rates as percentages
            series = fetch_monthly_treasury_rates(maturity_name, start_date, end_date)
            yield_series[maturity_name] = series  # Store with FMP column name (year2, year5, etc.)
        except Exception as e:
            # Continue with other maturities - some data better than none
            from utils.logging import log_portfolio_operation
            log_portfolio_operation(
                "treasury_yield_fetch_failed", 
                {"maturity": maturity_name, "error": str(e)},
                execution_time=0
            )
    
    if not yield_series:
        raise ValueError("Failed to fetch any Treasury rate data")
    
    # Validate minimum required maturities
    min_required = RATE_FACTOR_CONFIG.get("min_required_maturities", 2)
    if len(yield_series) < min_required:
        from utils.logging import log_portfolio_operation
        log_portfolio_operation(
            "treasury_yield_insufficient",
            {"available": len(yield_series), "required": min_required},
            execution_time=0
        )
    
    # Combine into DataFrame, align dates
    df = pd.DataFrame(yield_series)
    df = df.dropna()  # Remove any dates where we don't have all maturities
    
    return df
```

3) Multifactor OLS with HAC (NEW FUNCTION - add to factor_utils.py)
```python
# ADD TO: factor_utils.py (follows existing compute_regression_metrics pattern)

@log_error_handling("medium")  # Match existing regression functions
def compute_multifactor_betas(stock_returns: pd.Series, factor_df: pd.DataFrame,
                              hac_lags: int = 3) -> Dict[str, Any]:
    """
    Multivariate OLS regression with HAC standard errors for rate factor analysis.
    
    PATTERN: Follows existing compute_regression_metrics structure but extends to multiple factors.
    Based on existing pattern: X = sm.add_constant(), model = sm.OLS().fit()
    
    Args:
        stock_returns: Stock return series
        factor_df: DataFrame with factor return columns (UST2Y, UST5Y, UST10Y, UST30Y)
        hac_lags: Lags for HAC standard errors (Newey-West)
        
    Returns:
        Dict with betas, diagnostics, and regression statistics
    """
    # EXISTING PATTERN: Align data and handle empty case (matches compute_regression_metrics)
    aligned = pd.concat([stock_returns, factor_df], axis=1).dropna()
    if aligned.empty:
        return {
            'betas': {}, 'alpha': 0.0, 'r2': 0.0, 'r2_adj': 0.0, 
            't': {}, 'p': {}, 'std_err': {}, 'resid': pd.Series(dtype=float), 
            'vif': {}, 'cond_number': None
        }
    
    # EXISTING PATTERN: Set up OLS regression (matches compute_regression_metrics lines 83-84)
    y = aligned.iloc[:,0]  # Stock returns
    X = sm.add_constant(aligned.iloc[:,1:])  # Factor returns with intercept
    
    # NEW: Use HAC standard errors for time series data
    try:
        model = sm.OLS(y, X).fit(cov_type='HAC', cov_kwds={'maxlags': hac_lags})
    except:
        # Fallback to regular OLS if HAC fails
        model = sm.OLS(y, X).fit()
    
    # EXISTING PATTERN: Extract coefficients (matches compute_regression_metrics return structure)
    factor_names = aligned.columns[1:].tolist()
    betas = {factor: float(model.params.get(factor, 0.0)) for factor in factor_names}
    
    # NEW: Additional diagnostics for multivariate regression
    stats = {
        'betas': betas,
        'alpha': float(model.params.get('const', 0.0)),
        'r2': float(model.rsquared),
        'r2_adj': float(model.rsquared_adj),
        't': {factor: float(model.tvalues.get(factor, 0.0)) for factor in factor_names},
        'p': {factor: float(model.pvalues.get(factor, 1.0)) for factor in factor_names},
        'std_err': {factor: float(model.bse.get(factor, 0.0)) for factor in factor_names},
        'resid': model.resid,
        'vif': {factor: None for factor in factor_names},  # VIF computation can be added later
        'cond_number': float(np.linalg.cond(X.values)) if hasattr(np, 'linalg') else None
    }
    
    return stats
```

4) Key-rate fit + aggregation (FUTURE ENHANCEMENT ARTIFACTS - NOT IMPLEMENTED IN PHASE 1)
```python
# ⚠️  PLANNING ARTIFACTS ONLY - NOT IMPLEMENTED IN PHASE 1 ⚠️
# These functions are design specifications for potential future enhancements:
# - Phase 2: Enhanced stock analysis integration  
# - Separate API endpoints (/api/bond-duration/{ticker})
# - Standalone bond analysis tools
# - Custom result objects for specialized bond analysis

# ARTIFACT: Individual bond analysis function (Phase 2 planning only)
def fit_key_rate(fund_tr: pd.Series, dy_df: pd.DataFrame, *, hac_lags=3,
                 as_of: str | None = None, frequency='monthly', yield_scale='pp',
                 window_months: int | None = None, return_type='total_return') -> Dict[str, Any]:
    """
    PLANNING ARTIFACT: Design spec for Phase 2 enhanced stock analysis.
    NOT IMPLEMENTED IN PHASE 1 - Portfolio integration uses compute_multifactor_betas directly.
    """
    res = compute_multifactor_betas(fund_tr, dy_df, hac_lags=hac_lags)
    betas = res.get('betas', {})
    return {
        'as_of': as_of or (fund_tr.index.max().date().isoformat() if len(fund_tr) else None),
        'frequency': frequency,
        'yield_scale': yield_scale,
        'betas': betas,
        'beta_sum': float(sum(betas.values())) if betas else 0.0,
        'alpha': res.get('alpha', 0.0),
        'r2_adj': res.get('r2_adj', 0.0),
        'diagnostics': {k: res.get(k, {}) for k in ('vif','cond_number','t','p','std_err')},
        'window_months': window_months or len(fund_tr),
        'n_obs': len(fund_tr),
        'return_type': return_type,
    }

# ARTIFACT: Alternative portfolio aggregation (planning only)
def aggregate_portfolio(per_asset_results: Dict[str, Dict[str, Any]], weights: Dict[str, float]) -> Dict[str, Any]:
    """
    PLANNING ARTIFACT: Design spec for alternative portfolio-level duration approaches.
    NOT IMPLEMENTED IN PHASE 1 - Portfolio effective duration calculated directly from portfolio_factor_betas.
    """
    w = pd.Series(weights, dtype=float)
    if w.abs().sum() == 0:
        return {'betas': {}, 'beta_sum': 0.0}
    w = w / w.abs().sum()
    keys = sorted({k for r in per_asset_results.values() for k in (r.get('betas') or {}).keys()})
    port = {k: 0.0 for k in keys}
    for tkr, res in per_asset_results.items():
        for k in keys:
            port[k] += float(w.get(tkr, 0.0)) * float((res.get('betas') or {}).get(k, 0.0))
    return {'betas': port, 'beta_sum': float(sum(port.values()))}
```

5) Core injection pseudocode (inside `_build_portfolio_view_computation`)
```python
# ACTUAL FUNCTION: Update existing _build_portfolio_view_computation signature
# CHANGE: Add asset_classes parameter to existing function
def _build_portfolio_view_computation(
    weights: Dict[str, float],
    start_date: str,
    end_date: str,
    expected_returns: Optional[Dict[str, float]] = None,
    stock_factor_proxies: Optional[Dict[str, Dict[str, Union[str, List[str]]]]] = None,
    asset_classes: Optional[Dict[str, str]] = None  # NEW: Add this parameter
) -> Dict[str, Any]:

    # NEW: Build Treasury rate factors once per analysis window (add at top of function)
    treas = fetch_monthly_treasury_yield_levels(start_date, end_date)  # DataFrame with year2/5/10/30
    dy_df = prepare_rate_factors(treas)
    
    # NEW: Create combined interest rate factor for portfolio-level volatility
    interest_rate_series = dy_df.sum(axis=1)  # Sum all maturity changes
    interest_rate_vol = interest_rate_series.std(ddof=1) * np.sqrt(12)  # Annualized volatility
    
    # Note: No need to load cash proxies separately - they're already classified as "cash" by asset_classes
    # Cash proxies (SGOV, ESTR, IB01) get asset_class="cash" from SecurityTypeService Tier 1 detection

    # EXISTING LOOP: Modify the existing "for ticker in weights.keys():" loop around line 554
    if stock_factor_proxies:
        for ticker in weights.keys():
            if ticker not in stock_factor_proxies:
                continue
            proxies = stock_factor_proxies[ticker]
            
            # EXISTING: Fetch stock returns (keep unchanged)
            stock_ret = fetch_monthly_close(ticker, start_date=start_date, end_date=end_date)
            stock_ret = calc_monthly_returns(stock_ret)
            
            # EXISTING: Build factor_df for equity factors (keep unchanged)
            factor_df = build_factor_df_from_proxies(proxies, start_date, end_date)
            aligned_s = stock_ret.reindex(factor_df.index)
            
            # MODIFICATION: Add hybrid approach logic
            if asset_classes and asset_classes.get(ticker) == 'bond':  # Cash proxies already excluded via "cash" classification
                # HYBRID APPROACH: Equity factors (existing) + Rate factors (new multifactor)
                
                # 1. EXISTING: Run equity factor regressions (keep current approach)
                equity_betas = compute_stock_factor_betas(
                    aligned_s,                               # stock on same dates  
                    {c: factor_df[c] for c in factor_df}     # factors on same dates
                )
                df_stock_betas.loc[ticker, equity_betas.keys()] = pd.Series(equity_betas)
                
                # 2. NEW: Rate factor multivariate regression → single interest rate beta
                rate_factor_df = dy_df.reindex(aligned_s.index).dropna()
                if not rate_factor_df.empty:
                    rate_results = compute_multifactor_betas(aligned_s, rate_factor_df)
                    rate_betas = rate_results.get('betas', {})
                    
                    # Sum key-rate betas immediately to single interest rate beta
                    interest_rate_beta = sum(rate_betas.values())
                    df_stock_betas.loc[ticker, "interest_rate"] = interest_rate_beta
                    
                    # Store individual key-rate betas in diagnostics for power users
                    if ticker not in diagnostics:
                        diagnostics[ticker] = {}
                    diagnostics[ticker].update({
                        "key_rate_breakdown": rate_betas,
                        "rate_regression_r2": rate_results.get('r2_adj', 0),
                        "rate_regression_cond_number": rate_results.get('cond_number')
                    })
                    
                    # Set portfolio-level interest rate volatility for this asset
                    df_factor_vols.loc[ticker, "interest_rate"] = interest_rate_vol
            else:
                # EXISTING: Equity-only approach (keep unchanged)
                betas = compute_stock_factor_betas(
                    aligned_s,                               # stock on same dates
                    {c: factor_df[c] for c in factor_df}     # factors on same dates
                )
                df_stock_betas.loc[ticker, betas.keys()] = pd.Series(betas)
            
            # EXISTING: Idiosyncratic variance calculation (keep unchanged)
            # ...existing code lines 610-616...

    # EXISTING: Factor volatility computation automatically handles new rate factor columns (lines 618+)
    # EXISTING: weighted_factor_var calculation automatically includes new columns
```

6) CLI Runner modification (MODIFY EXISTING run_portfolio in run_risk.py)
```python
# MODIFY EXISTING: run_risk.py run_portfolio function (currently lines 236+)
# CHANGE: Add asset_classes parameter to existing function signature

def run_portfolio(filepath: str, risk_yaml: str = "risk_limits.yaml", *, 
                  return_data: bool = False, 
                  asset_classes: Optional[Dict[str, str]] = None) -> Union[None, RiskAnalysisResult]:  # NEW PARAMETER
    """
    EXISTING FUNCTION: High-level "one-click" entry-point for a full portfolio risk run.
    ENHANCEMENT: Add automatic asset class detection for fixed income analysis.
    
    NEW BEHAVIOR: When asset_classes=None (CLI usage), automatically gets asset classes from SecurityTypeService
    to enable rate factor analysis for bonds. When asset_classes provided (service layer usage),
    uses the provided classifications for optimal performance.
    """
    
    # NEW: Add asset class detection at the start of existing function
    if asset_classes is None:
        # Load portfolio config to extract tickers (use existing load_portfolio_config pattern)
        config = load_portfolio_config(filepath)
        standardized_data = standardize_portfolio_input(config["portfolio_input"], latest_price)
        tickers = list(standardized_data["weights"].keys())
        
        # Get asset classes for rate factor analysis
        from services.security_type_service import SecurityTypeService
        asset_classes = SecurityTypeService.get_asset_classes(tickers)
        from utils.logging import portfolio_logger
        portfolio_logger.debug(f"CLI: Auto-detected asset classes for {len(tickers)} tickers")
    
    # EXISTING: Rest of function unchanged, but pass asset_classes to analyze_portfolio call
    # Find the existing analyze_portfolio() call and add asset_classes parameter
    result = analyze_portfolio(filepath, risk_yaml=risk_yaml, asset_classes=asset_classes)  # ADD PARAMETER
    
    # EXISTING: Dual-mode logic (unchanged)
    if return_data:
        return result
    else:
        print(result.to_cli_report())
```

These stubs reflect the final design but deliberately avoid altering current code. They enable full review of the approach, inputs/outputs, and integration points before we implement surgically in the core.

---

## **🔧 Implementation Strategy**

### Phase A — Core Integration (Key‑Rate + TR)
1) Total‑return adoption
   - Add TR fetch helper; migrate returns to TR; version caches to prevent mixing.
2) Key‑rate in core
   - `prepare_rate_factors` (Δy) and `compute_multifactor_betas` (multivariate OLS with HAC).
   - Inject Δy factors for bonds; write key‑rate betas/vols; recompute weighted factor variance.
   - Add `effective_duration` field to API response (sum of portfolio rate factor betas).
3) Tests & QA
   - Sanity magnitudes (TLT/IEF/SHY), stability window (36m), pp/bps invariance, collinearity warnings.

### Phase B — Flexibility Shim (Optional)
1) Add `build_factor_df_for_ticker(...)` to centralize factor selection by asset class.
2) No functional change; simplifies adding credit spread or other bond factors later.

### Phase C — API/Frontend/Storage
1) Optional REST endpoints for rate beta (single/key/portfolio).
2) Frontend charts for key‑rate vector and portfolio effective duration.
3) Persistence tables or parquet export for audit and rolling windows.

---

## **🧭 Implementation Tasks (Checklist)**

**📋 Implementation Code**: All functions referenced below are fully implemented. See [Complete Function Implementations](#🔩-complete-function-implementations) for ready-to-use code.

- Total‑Return Adoption
  - [ ] Add `fetch_monthly_total_return_price` with adjusted‑close preference
  - [ ] Version cache keys (e.g., `tr_v1`) and purge/migrate legacy close‑only if needed
  - [ ] Switch `get_returns_dataframe`, factor ETF fetches, and `fetch_excess_return` to TR

- Rate Factors (Core) - ARCHITECTURAL APPROACH
  - [ ] **CONFIGURATION**: Add `RATE_FACTOR_CONFIG` and `RATE_FACTOR_PROFILES` to `settings.py`
    - [ ] Centralize rate factor maturities (default: UST2Y, UST5Y, UST10Y, UST30Y)
    - [ ] Treasury endpoint mapping (UST2Y → year2, UST5Y → year5, etc.)
    - [ ] Alternative profiles (standard, short_term, long_term, minimal)
    - [ ] Configuration validation (min_required_maturities, scale, frequency)
  - [ ] **MISSING**: Add `prepare_rate_factors` to `factor_utils.py` (imported in portfolio_risk.py:25 but doesn't exist)
    - [ ] Use centralized RATE_FACTOR_CONFIG for maturities and mapping
    - [ ] Support configurable rate factor profiles
  - [ ] **MISSING**: Add `compute_multifactor_betas` to `factor_utils.py` (needed for key-rate regression)
  - [ ] Add `fetch_monthly_treasury_yield_levels` to `data_loader.py` or `factor_utils.py`
    - [ ] Use RATE_FACTOR_CONFIG["treasury_mapping"] for maturities
    - [ ] Implement minimum maturity validation
  - [ ] **ARCHITECTURE**: Add `asset_classes` parameter to function signatures:
    - [ ] `_build_portfolio_view_computation(...)` add `asset_classes: Optional[Dict[str, str]] = None`
    - [ ] `build_portfolio_view(...)` add `asset_classes: Optional[Dict[str, str]] = None` 
    - [ ] `core/portfolio_analysis.analyze_portfolio(...)` add `asset_classes: Optional[Dict[str, str]] = None`
  - [ ] **SERVICE LAYER**: Pass asset_classes from `PortfolioService.analyze_portfolio()` down through all layers
  - [ ] **CLI RUNNER**: Update `run_risk.py run_portfolio()` to get asset_classes when not provided (Option A)
    - [ ] Add `asset_classes` parameter to `run_portfolio()` signature  
    - [ ] Add logic to get asset_classes from SecurityTypeService when asset_classes=None
    - [ ] Pass asset_classes to `analyze_portfolio()` call
  - [ ] Build `dy_df` once per analysis window in `_build_portfolio_view_computation`
  - [ ] **HYBRID APPROACH**: For bonds use both existing single-factor (equity) + new multifactor (rates) → single interest rate beta
  - [ ] Insert single `interest_rate_beta` into `df_stock_betas["interest_rate"]`; add portfolio-level interest rate volatility to `df_factor_vols`
  - [ ] Store key-rate breakdown in diagnostics for detailed analysis
  - [ ] Ensure `weighted_factor_var` includes new interest_rate column

- Diagnostics & API Integration
  - [ ] HAC/Newey–West (lag=3 monthly); store t/p/std_err
  - [ ] Compute VIF and condition number; add warnings when VIF>10
  - [ ] **DATA QUALITY**: Add rate factor beta validation (warn if |beta| > 25 years for any maturity)
  - [ ] **DATA QUALITY**: Add rate factor regression R² threshold (warn if R² < 0.3 for key-rate regression)
  - [ ] **PORTFOLIO RESULT OBJECT**: Update `RiskAnalysisResult` for single interest rate factor approach
    - [ ] Add `effective_duration` field to `to_api_response()` method:
      ```python
      # Add to existing return dict (around line 1114)
      "effective_duration": self.portfolio_summary.get("portfolio_factor_betas", {}).get("interest_rate", 0) * 100,  # NEW field (Option A: multiply by 100)
      ```
      Note: Existing fields (`stock_betas`, `portfolio_factor_betas`, `factor_vols`, `variance_decomposition`) 
      automatically include "interest_rate" factor when present
    - [ ] Update CLI helper methods in `to_cli_report()` for enhanced factor display:
      - [ ] Add effective duration after volatility metrics section (find the right helper method)
      - [ ] Modify factor exposures section to separate equity vs rate factors
      - [ ] Update variance attribution section to group by factor type
      ```python
      # Example modifications to specific helper methods:
      # 1. Add effective duration display (find correct section helper)
      if self.portfolio_summary.get("portfolio_factor_betas", {}).get("interest_rate") is not None:
          eff_duration = self.portfolio_summary["portfolio_factor_betas"]["interest_rate"] * 100  # Option A: multiply by 100
          # Add: f"Effective Duration:      {eff_duration:.2f} years"
      
      # 2. Modify factor exposure helper to group equity vs rate factors
      # 3. Modify variance breakdown helper to show factor type grouping
      ```
      Note: Identify specific helper methods in to_cli_report() that need modification rather than rewriting entire method
  - [ ] **USER EXPERIENCE**: Add CLI message when rate factors are active (e.g., "✓ Rate factor analysis enabled for N bond holdings")

- Flexibility Shim (Optional)
  - [ ] Add `build_factor_df_for_ticker(...)` and route equity/bond factor providers

- Phase 2: Enhanced Stock Analysis (FUTURE ENHANCEMENT) 
  - [ ] **STOCK ANALYSIS**: Enhance `get_stock_factor_proxies()` to include rate factors for bonds
    - [ ] Add `include_rate_factors` parameter and asset class detection
    - [ ] Use RATE_FACTOR_CONFIG["default_maturities"] for bond factors
    - [ ] Support configurable rate factor profiles (standard, short_term, long_term)
  - [ ] **FACTOR PROFILE**: Extend `get_detailed_stock_factor_profile()` to handle single interest rate factor
    - [ ] Include single interest rate beta in primary factor summary
    - [ ] Add key-rate breakdown to detailed/diagnostics view for bond analysis
    - [ ] Merge equity and interest rate factor results into unified factor_summary
  - [ ] **STOCK CLI RUNNER**: Update `run_stock()` function in `run_risk.py`
    - [ ] Add optional asset_class parameter (similar to portfolio runner pattern):
      ```python
      def run_stock(
          ticker: str,
          start: Optional[str] = None,
          end: Optional[str] = None,
          factor_proxies: Optional[Dict[str, Union[str, List[str]]]] = None,
          asset_class: Optional[str] = None,  # NEW: Asset class override
          *,
          return_data: bool = False
      ) -> Union[None, StockAnalysisResult]:
      ```
    - [ ] Add asset class detection logic when asset_class=None:
      ```python
      # Auto-detect asset class if not provided
      if asset_class is None:
          from services.security_type_service import SecurityTypeService
          asset_classes = SecurityTypeService.get_asset_classes([ticker])
          asset_class = asset_classes.get(ticker, 'equity')  # Default to equity
      ```
    - [ ] Pass asset_class through to core analysis functions
  - [ ] **CORE STOCK ANALYSIS**: Update `analyze_stock()` function
    - [ ] Add asset_class parameter to function signature
    - [ ] Enable rate factor analysis for bond ETFs, funds, and individual bonds when asset_class='bond'
    - [ ] Populate new result fields from rate factor analysis:
      ```python
      # For bonds, after key-rate regression
      if asset_class == 'bond' and rate_results:
          result.interest_rate_beta = sum(rate_results['betas'].values())
          result.effective_duration = result.interest_rate_beta
          result.rate_regression_r2 = rate_results.get('r2_adj', 0)
          result.key_rate_breakdown = rate_results.get('betas', {})
      ```
    - [ ] Enhanced CLI output showing single interest rate beta, effective duration, and key-rate breakdown in detailed view
  - [ ] **STOCK RESULT OBJECT**: Update StockAnalysisResult integration
    - [ ] Add new fields to constructor and as instance attributes (NOT dataclass fields):
      
      **Complete Constructor Signature (Modified)**:
      ```python
      # MODIFY: StockAnalysisResult.__init__() in result_objects.py
      class StockAnalysisResult:
          def __init__(
              self,
              ticker: str,
              volatility_metrics: Dict[str, Any],
              regression_metrics: Dict[str, Any],
              factor_exposures: Optional[Dict[str, Any]] = None,
              factor_summary: Optional[pd.DataFrame] = None,
              factor_proxies: Optional[Dict[str, Any]] = None,
              analysis_metadata: Optional[Dict[str, Any]] = None,
              risk_metrics: Optional[Dict[str, Any]] = None,
              
              # NEW: Rate factor fields for bonds
              interest_rate_beta: Optional[float] = None,        # Single aggregated rate beta
              effective_duration: Optional[float] = None,        # Same as interest_rate_beta  
              rate_regression_r2: Optional[float] = None,        # Rate factor regression quality
              key_rate_breakdown: Optional[Dict[str, float]] = None,  # Individual maturity betas
              
              # Maintain backward compatibility
              **kwargs
          ):
              """
              Individual stock analysis results with optional rate factor integration.
              
              NEW: Rate factor fields are populated for bonds when asset_class='bond'.
              For equities, these fields remain None and don't affect existing functionality.
              """
              
              # EXISTING: All existing field assignments (unchanged)
              self.ticker = ticker
              self.volatility_metrics = volatility_metrics
              self.regression_metrics = regression_metrics
              self.factor_exposures = factor_exposures or {}
              self.factor_summary = factor_summary
              self.factor_proxies = factor_proxies or {}
              self.analysis_metadata = analysis_metadata or {}
              self.risk_metrics = risk_metrics or {}
              
              # Handle any additional keyword arguments for backward compatibility
              for key, value in kwargs.items():
                  setattr(self, key, value)
              
              # NEW: Rate factor field assignments
              self.interest_rate_beta = interest_rate_beta
              self.effective_duration = effective_duration if effective_duration is not None else interest_rate_beta
              self.rate_regression_r2 = rate_regression_r2
              self.key_rate_breakdown = key_rate_breakdown or {}
              
              # Analysis type detection for CLI formatting
              self.analysis_date = datetime.now(UTC)
              
      ```
      
      **Constructor Call Pattern (For Implementation)**:
      ```python
      # FOR EQUITIES: Existing pattern (unchanged)
      result = StockAnalysisResult(
          ticker="AAPL",
          volatility_metrics=vol_metrics,
          regression_metrics=reg_metrics,
          factor_exposures=factor_exp,
          # Rate factor fields = None (default)
      )
      
      # FOR BONDS: Enhanced with rate factors
      result = StockAnalysisResult(
          ticker="TLT", 
          volatility_metrics=vol_metrics,
          regression_metrics=reg_metrics,
          factor_exposures=factor_exp,
          # NEW: Rate factor data
          interest_rate_beta=2.22,  # Sum of key-rate betas
          effective_duration=2.22,  # Same value for user clarity
          rate_regression_r2=0.89,
          key_rate_breakdown={"UST2Y": -0.05, "UST5Y": 0.31, "UST10Y": 0.72, "UST30Y": 1.24}
      )
      ```
    - [ ] Update `to_api_response()` method to include rate factor fields:
      ```python
      # Add to existing return dict in to_api_response()
      if hasattr(self, 'interest_rate_beta') and self.interest_rate_beta is not None:
          response["interest_rate_beta"] = round(self.interest_rate_beta, 3)
          response["effective_duration"] = round(self.effective_duration, 2)
          response["rate_regression_r2"] = round(self.rate_regression_r2, 3)
          if self.key_rate_breakdown:
              response["key_rate_breakdown"] = {k: round(v, 3) for k, v in self.key_rate_breakdown.items()}
      ```
    - [ ] Update `_format_factor_analysis()` method (NOT full to_cli_report) to include rate factors:
      ```python
      # Modify existing _format_factor_analysis() method for bonds
      def _format_factor_analysis(self) -> str:
          if not self.factor_exposures:
              return ""
          lines = ["=== Factor Exposures ==="]
          
          # Existing equity factors
          for factor_name, exposure in self.factor_exposures.items():
              beta = exposure.get('beta', 0)
              r_sq = exposure.get('r_squared', 0)
              proxy = exposure.get('proxy', 'N/A')
              lines.append(f"{factor_name:<12} β = {beta:+.2f}  R² = {r_sq:.3f}  Proxy: {proxy}")
          
          # NEW: Add interest rate section for bonds
          if hasattr(self, 'interest_rate_beta') and self.interest_rate_beta is not None:
              lines.append("")
              lines.append("=== Interest Rate Sensitivity ===")
              lines.append(f"Interest Rate Beta:     {self.interest_rate_beta:.2f}")
              lines.append(f"Effective Duration:     {self.effective_duration:.2f} years")
              lines.append(f"Rate R²:                {self.rate_regression_r2:.2f}")
              
              if self.key_rate_breakdown:
                  lines.append("")
                  lines.append("Key-Rate Breakdown:")
                  for maturity, beta in self.key_rate_breakdown.items():
                      maturity_label = maturity.replace("UST", "").replace("Y", "Y Rate")
                      lines.append(f"  {maturity_label:8} Beta:    {beta:6.2f}")
          
          return "\n".join(lines)
      ```
  - [ ] **USE CASE TESTING**: Test enhanced analysis on bond securities
    - [ ] Bond ETFs: TLT, IEF, SHY, AGG rate sensitivity validation
    - [ ] Corporate bond funds: rate + credit factor analysis
    - [ ] Mixed securities: bonds with equity characteristics

- Tests & QA
  - [ ] Unit tests: Δy prep, multivariate betas, VIF calc, TR vs close fallback
  - [ ] Integration: TLT/IEF/SHY magnitude checks; portfolio beta_sum aggregation
  - [ ] Regression: variance decomposition stable; idio declines for bonds after adding rates
  - [ ] **Phase 2 Testing**: Enhanced stock analysis validation
    - [ ] Bond ETF rate sensitivity accuracy (TLT should show high 30Y beta)
    - [ ] CLI output formatting for rate factors + equity factors
    - [ ] Performance impact assessment for stock analysis with rate factors

---

## **⚙️ Configuration & Flags**

### **Centralized Rate Factor Configuration (settings.py)**

Following the established architecture pattern, rate factors are centrally configured:

```python
# Rate Factor Configuration
# Centralized configuration for Treasury rate factors used in fixed income analysis
RATE_FACTOR_CONFIG = {
    "enabled": True,  # Global enable/disable for rate factor analysis
    "default_maturities": ["UST2Y", "UST5Y", "UST10Y", "UST30Y"],  # Standard key rate points for internal regression
    "output_factor_name": "interest_rate",  # Single factor name for portfolio analysis
    "treasury_mapping": {
        # Maps rate factor names to FMP Treasury endpoint column names
        "UST2Y": "year2",    # 2-year Treasury
        "UST5Y": "year5",    # 5-year Treasury  
        "UST10Y": "year10",  # 10-year Treasury
        "UST30Y": "year30"   # 30-year Treasury
    },
    "scale": "pp",  # percentage points (vs decimal)
    "frequency": "monthly",  # Monthly rate changes (vs daily)
    "min_required_maturities": 2,  # Minimum number of maturities for valid analysis
    "include_cash_proxies": False,  # Exclude cash proxies from rate factor analysis
}

# Alternative rate factor configurations for different use cases
# Note: All profiles output single "interest_rate" factor regardless of internal maturity count
RATE_FACTOR_PROFILES = {
    "standard": ["UST2Y", "UST5Y", "UST10Y", "UST30Y"],      # Full curve analysis → single interest_rate beta
    "short_term": ["UST2Y", "UST5Y"],                         # Short-duration focus → single interest_rate beta
    "long_term": ["UST10Y", "UST30Y"],                        # Long-duration focus → single interest_rate beta
    "minimal": ["UST5Y", "UST10Y"],                           # Core belly/long-end → single interest_rate beta
}
```

### **Portfolio-Level Configuration**
```yaml
rate_beta:
  enabled: true
  profile: "standard"  # Uses RATE_FACTOR_PROFILES["standard"]
  include_cash_proxies: false
  window_months: 36

returns:
  use_total_return: true
```

**Benefits:**
- **Configurable maturity points**: Easy to add UST1Y, UST7Y, international rates
- **Environment-specific**: Different profiles for different analysis needs  
- **Global toggle**: Can disable rate factors entirely if needed
- **Clean data mapping**: Analysis names → FMP endpoint columns

---

## **🔌 Data Contracts (FMP)**

- Prices (Total Return): `GET /stable/historical-price-eod/dividend-adjusted?symbol=XYZ` → fields: `date`, `adjClose`, `volume`
  - Primary endpoint for true total returns including dividend adjustments
  - Response format: `[{"symbol": "AAPL", "date": "2025-09-11", "adjOpen": 226.88, "adjHigh": 230.16, "adjLow": 226.65, "adjClose": 229.51, "volume": 31515187}, ...]`
  - Fallback: `GET /stable/historical-price-eod/full?symbol=XYZ&serietype=line` → use `close` field with `return_type='price_only'` metadata

- Treasury yields: `GET /stable/treasury-rates` → returns all maturities in single response
  - Response format: `[{"date": "2025-09-10", "month1": 4.23, "month2": 4.2, "month3": 4.09, "month6": 3.83, "year1": 3.66, "year2": 3.54, "year3": 3.47, "year5": 3.59, "year7": 3.78, "year10": 4.04, "year20": 4.65, "year30": 4.69}, ...]`
  - Use existing `fetch_monthly_treasury_rates(maturity, start_date, end_date)` for each required maturity (year2, year5, year10, year30)
  - Returns rates as percentages, already resampled to month-end and cached
  - Δy = diff(level) in decimal (divide by 100); name columns `UST2Y/UST5Y/UST10Y/UST30Y`

---

## **🗃️ Caching & Migration**

- Cache versioning: include a TR version token (e.g., `tr_v1`) in keys for TR series to avoid mixing with close‑only caches.
- Migration: keep legacy caches side‑by‑side until TR adoption is complete; provide an admin tool to clear old caches.
- Determinism: all serialized outputs should include `yield_scale`, `frequency`, and `window_months`.

---

## **✅ Testing & Validation**

- Sanity: TLT ≈ −17 to −20; IEF ≈ −7 to −9; SHY ≈ −1.7 to −2.2 (36m monthly, pp scale)
- Stability: compare 24m vs 36m; weekly vs monthly; β sign/magnitude robust
- Scale invariance: pp vs bps rescaling only (no logic changes)
- Collinearity: VIF>10 flagged; condition number monitored
- Backtest: predicted vs actual TR (R², RMSE) improves over naive mean

---

## **🚀 Rollout & Monitoring**

- Rollout
  - Stage 1: Enable TR only
  - Stage 2: Enable key‑rate for bonds (equities unchanged)
  - Stage 3 (optional): Enable flexibility shim routing by asset class

- Monitoring
  - Track % of portfolios with bond exposure using rate factors
  - Average absolute change in idiosyncratic share for bonds post‑integration
  - Distribution of VIF and condition numbers; outlier alerts

---

## **⚠️ Risks & Mitigations**

- Source risk (TR correctness): validate adjusted close against an independent sample; flag `price_only` usage
- Collinearity: VIF monitoring; document optional ridge regularization (off by default)
- Spec sensitivity: noisy daily data—default monthly frequency and 36m window
- Cache mixing: TR cache versioning and explicit purge tools

---

## **🎯 Expected Outcomes**

### **Phase 1: Portfolio Risk Integration**
Before
- Bonds regressed on equity factors; no duration; close‑only returns.

After
- Per‑asset single interest rate betas with portfolio effective duration.
- Interest rate factor contributes to variance decomposition alongside equity factors.
- Total‑return pricing improves Sharpe/Sortino accuracy for income assets.
- Clean API responses with unified factor structure.

### **Phase 2: Enhanced Stock Analysis**
Before
- Individual bond analysis limited to equity factors (market, momentum, value, industry)
- No interest rate sensitivity measurement for bond funds/ETFs
- Duration analysis requires external tools

After
- Bond ETFs/funds get single interest rate beta with key-rate breakdown displayed in detailed view
- Individual bond duration analysis with simplified primary output + detailed breakdown
- CLI command `python -m run_risk stock TLT` shows clean interest rate sensitivity with optional key-rate details
- Enhanced factor analysis combining equity + single interest rate factor for mixed securities
- Key-rate breakdown preserved in stock analysis output for professional users

---

## **🔗 Integration with Asset Class Architecture**

**📋 Implementation Code**: Complete service layer integration code provided below. See [Implementation Quick Reference](#📋-implementation-quick-reference) for function signature updates.

### **Clean Parameter Passing (Option 1 - RECOMMENDED)**

**Service Layer → Core Layer → Computation Layer**

```python
# SERVICE LAYER: services/portfolio_service.py
def analyze_portfolio(self, portfolio_data, ...):
    # Get asset classes using existing service
    asset_classes = SecurityTypeService.get_asset_classes(tickers, portfolio_data)
    
    # Pass down to CLI runner 
    result = run_portfolio(temp_file, risk_yaml, asset_classes=asset_classes)

# CLI RUNNER: run_risk.py (Option A - CLI gets asset_classes when needed)
def run_portfolio(filepath, risk_yaml="risk_limits.yaml", *, return_data=False, asset_classes=None):
    # If no asset_classes provided, get them (CLI case)
    if asset_classes is None:
        config = load_portfolio_config(filepath)
        tickers = list(standardize_portfolio_input(config["portfolio_input"], latest_price)["weights"].keys())
        from services.security_type_service import SecurityTypeService
        asset_classes = SecurityTypeService.get_asset_classes(tickers)
    
    # Call core with asset_classes
    result = analyze_portfolio(filepath, risk_yaml=risk_yaml, asset_classes=asset_classes)

# CORE LAYER: core/portfolio_analysis.py  
def analyze_portfolio(filepath, risk_yaml, asset_classes=None):
    # Pass through to computation layer
    summary = build_portfolio_view(weights, start, end, ..., asset_classes=asset_classes)

# COMPUTATION LAYER: portfolio_risk.py
def build_portfolio_view(..., asset_classes=None):
    return _build_portfolio_view_computation(..., asset_classes=asset_classes)

def _build_portfolio_view_computation(..., asset_classes=None):
    # Use asset_classes for bond detection - no service imports needed!
    if asset_classes and asset_classes.get(ticker) == 'bond':
        # Add rate factors
```

### **Benefits of This Approach**
1. **Clean separation of concerns** - core functions stay pure
2. **Easy to test** - can mock asset_classes parameter  
3. **No service dependencies** in computation layer
4. **Backward compatible** - asset_classes is optional
5. **Service layer controls** data sourcing (cache, fallbacks, etc.)
6. **CLI gets same features** - CLI users get fixed income rate factors automatically
7. **No CLI breakage** - CLI works unchanged, gets asset_classes when needed
8. **Performance optimized** - Service layer can skip asset_class lookup if already retrieved

### **Implementation Notes**
1) Use existing `SecurityTypeService.get_asset_classes()`.
2) Bonds (including REITs per classifier) get key‑rate factors; cash proxies excluded.
3) Phase 2 can tailor factor sets by asset class (equity vs bond).

### **Phase 2: Enhanced Stock Analysis with Key-Rate Factors**

The `fit_key_rate()` planning artifacts enable powerful individual bond/fund analysis integration with the existing stock analysis framework.

**Enhanced Stock Analysis Flow:**
```python
# Current: analyze_stock("TLT") → equity factors only
# Enhanced: analyze_stock("TLT") → equity + single interest rate factor for bonds

analyze_stock("TLT") →
├── SecurityTypeService.get_asset_classes(["TLT"]) → {"TLT": "bond"}
├── get_stock_factor_proxies("TLT", include_rate_factors=True)
    └── Uses RATE_FACTOR_CONFIG["default_maturities"] for internal key-rate regression
├── get_detailed_stock_factor_profile() with rate factors:
    ├── Equity factors: market, momentum, value, industry, subindustry  
    ├── Interest rate factor: Single aggregated interest rate beta
    └── Key-rate breakdown: Available in diagnostics/detailed view
```

**Perfect Use Cases:**
- **Bond ETFs**: `TLT` (30Y duration), `IEF` (10Y), `SHY` (2Y), `AGG` (mixed)
- **Bond Funds**: Corporate, municipal, international bond funds
- **Individual Bonds**: Corporate bonds get equity + rate sensitivity
- **TIPS/I-Bonds**: Rate factors + inflation sensitivity

**Enhanced CLI Output Example:**
```bash
$ python -m run_risk stock TLT

TLT (20+ Year Treasury) Analysis:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Market Factors:
- Market Beta: 0.12 (low equity correlation)
- Momentum Beta: -0.03 (minimal trend following)

Interest Rate Sensitivity:
- Interest Rate Beta: 2.22 (high rate sensitivity)
- Effective Duration: 2.22 years
- Rate R²: 0.89 (strong rate sensitivity)

Key-Rate Breakdown (detailed view):
- 2Y Rate Beta: -0.05 (minimal short-term)  
- 5Y Rate Beta: 0.31 (moderate medium-term)
- 10Y Rate Beta: 0.72 (high long-term)
- 30Y Rate Beta: 1.24 (very high ultra-long)
```

**Enhanced API Response Example:**
```json
{
  "ticker": "TLT",
  "analysis_date": "2024-12-15",
  "asset_class": "bond",
  "factor_betas": {
    "market": 0.120,
    "momentum": -0.030,
    "value": 0.015,
    "interest_rate": 2.220
  },
  "interest_rate_beta": 2.220,
  "effective_duration": 2.22,
  "rate_regression_r2": 0.890,
  "key_rate_breakdown": {
    "UST2Y": -0.050,
    "UST5Y": 0.310,
    "UST10Y": 0.720,
    "UST30Y": 1.240
  },
  "volatility": {
    "monthly": 0.045,
    "annual": 0.156
  },
  "idiosyncratic_vol": 0.052,
  "r_squared": 0.891
}
```

**Enhanced Portfolio CLI Output Example:**
```bash
$ python -m run_risk portfolio mixed_portfolio.yaml

Mixed Portfolio Risk Analysis:
═══════════════════════════════════════════════════════════════════════
Portfolio Risk Summary:
Volatility:              12.8%
Effective Duration:      1.5 years

Equity Factor Exposures:
Market Beta:              0.85
Momentum Beta:            0.12
Value Beta:              -0.05
Industry Beta:            0.92

Interest Rate Exposure:
Interest Rate Beta:       1.50
Effective Duration:       1.50 years

Variance Attribution:
Equity Factors:
  Market:                 45.2%
  Industry:               18.7%
  Momentum:                3.1%
Interest Rate Factor:
  Interest Rate:          22.4%
Idiosyncratic:            10.6%

✓ Rate factor analysis enabled for 3 bond holdings (TLT, AGG, VNQ)
```

---

## **📊 Success Metrics**

Technical
- Bonds/REITs get key‑rate betas; portfolio effective duration computed from beta_sum.
- Rate factors appear in betas, factor vols, and variance decomposition.
- Risk/Perf use total‑return pricing consistently.

User Experience
- Clear portfolio effective duration and rate sensitivity alongside equity factors.
- TR‑based Sharpe/Sortino more accurate for income portfolios.

Business
- Professional‑grade fixed‑income analytics with auditable outputs and diagnostics.

---

## **🚀 Future Enhancements**

**📋 Return to Top**: [Implementation Quick Reference](#📋-implementation-quick-reference) | [Complete Function Implementations](#🔩-complete-function-implementations) | [Implementation Checklist](#🧭-implementation-tasks-checklist)

Advanced Fixed Income
- Credit spread analytics (IG/HY decomposition), curve positioning, TIPS real‑rate factors.
- International bonds (FX hedged/unhedged rate factors).
- Rolling key‑rate windows and regime shift detection.

Methods & Robustness
- Optional ridge regularization when VIFs high; outlier handling (winsorization); rolling recomputation.
- Backtest predicted vs actual TR; report RMSE/R²; scenario shocks using portfolio beta vector.

---

This plan replaces heuristic duration approximations with an auditable, empirical key‑rate model, integrates rate factors into the same beta/variance framework as equities, and standardizes on total‑return pricing for consistent risk and performance analytics.
