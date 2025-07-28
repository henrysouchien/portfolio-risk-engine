# Asset Class Integration Architecture

**Status**: Design document - asset class logic is NOT IMPLEMENTED. Current system treats all assets as equities.

## Current System Data Flow

```
portfolio.yaml → load_portfolio_config() → standardize_portfolio_input() → 
build_portfolio_view() → risk calculations → optimization → reporting
```

## Key Integration Points

### 1. **Configuration Loading** (`helpers_input.py`)
**Current**: All assets get identical factor proxy structure
```yaml
SGOV:
  market: SPY
  momentum: MTUM
  value: IWD
  industry: SGOV  # ← PROBLEM: Bonds treated as equity
  subindustry: []
```

**Proposed**: Asset-class-aware configuration
```yaml
SGOV:
  asset_class: "government_bonds"  # ← NEW FIELD
  duration: "short"
  credit_quality: "treasury"
  # No industry/subindustry for bonds
  
NVDA:
  asset_class: "equity"  # ← NEW FIELD
  market: SPY
  momentum: MTUM
  value: IWD
  industry: SOXX
  subindustry: [...]
```

### 2. **Factor Computation** (`factor_utils.py`, `portfolio_risk.py`)
**Current**: `build_portfolio_view()` applies same factor model to all assets
```python
# Current: One-size-fits-all approach
for ticker in weights:
    betas = compute_stock_factor_betas(stock_ret, factor_dict)
    # Always computes market, momentum, value, industry betas
```

**Proposed**: Asset-class-specific factor computation
```python
# New: Asset-class-aware factor computation
for ticker in weights:
    asset_class = get_asset_class(ticker, proxies)
    if asset_class == "equity":
        betas = compute_equity_factor_betas(stock_ret, factor_dict)
    elif asset_class == "government_bonds":
        betas = compute_bond_factor_betas(stock_ret, factor_dict)
    elif asset_class == "commodities":
        betas = compute_commodity_factor_betas(stock_ret, factor_dict)
```

### 3. **Risk Constraint Logic** (`portfolio_optimizer.py`, `risk_helpers.py`)
**Current**: All assets subject to industry beta constraints
```python
# Current: Applies industry beta to ALL assets (including bonds!)
for fac, max_b in max_betas.items():
    if fac == 'industry':
        cons += [cp.abs(beta_mat[fac].values @ w) <= max_b]
```

**Proposed**: Asset-class-specific constraints
```python
# New: Only apply industry constraints to equities
equity_indices = [i for i, ticker in enumerate(tickers) 
                 if get_asset_class(ticker, proxies) == "equity"]
if equity_indices and fac == 'industry':
    equity_betas = beta_mat[fac].values[equity_indices]
    equity_weights = w[equity_indices]
    cons += [cp.abs(equity_betas @ equity_weights) <= max_b]
```

### 4. **Beta Limit Calculation** (`risk_helpers.py`)
**Current**: `compute_max_betas()` treats all industry proxies identically
```python
# Current: All industry proxies contribute to same limit
industry_proxies = set()
for proxy_map in proxies.values():
    proxy = proxy_map.get("industry")
    if proxy:
        industry_proxies.add(proxy)
```

**Proposed**: Asset-class-specific beta limits
```python
# New: Separate limits by asset class
def compute_asset_class_beta_limits(proxies, start_date, end_date, loss_limits):
    equity_proxies = get_proxies_by_asset_class(proxies, "equity")
    bond_proxies = get_proxies_by_asset_class(proxies, "government_bonds")
    
    return {
        "equity": compute_max_betas(equity_proxies, loss_limits["equity"]),
        "government_bonds": compute_max_betas(bond_proxies, loss_limits["bonds"]),
        # etc.
    }
```

## Modified Component Architecture

### 1. **Configuration Schema** (`portfolio.yaml`)
```yaml
# New schema with asset classes
stock_factor_proxies:
  SGOV:
    asset_class: "government_bonds"
    duration_proxy: "IEF"        # 7-10 year Treasury ETF
    credit_proxy: null           # No credit risk for treasuries
    
  NVDA:
    asset_class: "equity"
    market: SPY
    momentum: MTUM
    value: IWD
    industry: SOXX
    subindustry: [AMD, INTC, AVGO, ...]
    
  SLV:
    asset_class: "commodities"
    commodity_type: "precious_metals"
    commodity_proxy: "GLD"       # Gold as precious metals proxy
```

### 2. **Risk Limits Schema** (`risk_limits.yaml`)
```yaml
# Asset-class-specific limits
asset_class_limits:
  equity:
    max_single_factor_loss: -0.10
    max_industry_beta: 0.80
    max_concentration: 0.40
    
  government_bonds:
    max_duration_risk: 0.05
    max_concentration: 0.50
    # No industry beta limits
    
  commodities:
    max_commodity_exposure: 0.20
    max_concentration: 0.30
```

### 3. **Factor Computation Functions** (`factor_utils.py`)
```python
# New asset-class-specific functions
def compute_equity_factor_betas(stock_ret, factor_dict):
    """Standard equity factor model: market, momentum, value, industry"""
    return compute_factor_metrics(stock_ret, factor_dict)

def compute_bond_factor_betas(stock_ret, factor_dict):
    """Bond factor model: duration, credit, interest rate"""
    bond_factors = {k: v for k, v in factor_dict.items() 
                   if k in ["duration", "credit", "interest_rate"]}
    return compute_factor_metrics(stock_ret, bond_factors)

def compute_commodity_factor_betas(stock_ret, factor_dict):
    """Commodity factor model: commodity-specific factors"""
    commodity_factors = {k: v for k, v in factor_dict.items() 
                        if k in ["commodity", "inflation", "dollar"]}
    return compute_factor_metrics(stock_ret, commodity_factors)
```

### 4. **Asset Class Utilities** (`asset_class_utils.py` - NEW FILE)
```python
# New utility functions for asset class handling
def get_asset_class(ticker: str, proxies: Dict) -> str:
    """Get asset class for a ticker"""
    return proxies.get(ticker, {}).get("asset_class", "equity")  # Default to equity

def get_assets_by_class(tickers: List[str], proxies: Dict) -> Dict[str, List[str]]:
    """Group tickers by asset class"""
    classes = {}
    for ticker in tickers:
        asset_class = get_asset_class(ticker, proxies)
        if asset_class not in classes:
            classes[asset_class] = []
        classes[asset_class].append(ticker)
    return classes

def get_asset_class_constraints(asset_class: str, risk_config: Dict) -> Dict:
    """Get constraints for specific asset class"""
    return risk_config.get("asset_class_limits", {}).get(asset_class, {})
```

## Implementation Strategy

### Phase 1: Core Infrastructure
1. **Add asset class utilities** (`asset_class_utils.py`)
2. **Update configuration loading** to handle asset classes
3. **Maintain backward compatibility** with existing configs

### Phase 2: Factor Computation
1. **Modify `build_portfolio_view()`** to be asset-class-aware
2. **Add asset-class-specific factor functions**
3. **Update risk calculations** to handle different factor models

### Phase 3: Constraint Logic
1. **Update optimization functions** to apply appropriate constraints
2. **Modify beta limit calculations** to be asset-class-specific
3. **Add asset-class-specific validation**

### Phase 4: Risk Reporting
1. **Update display functions** to show asset-class-specific metrics
2. **Add asset class diversification reporting**
3. **Update risk summaries** to be asset-class-aware

## Backward Compatibility Strategy

### Migration Path
1. **Existing configs work unchanged** (default to `asset_class: "equity"`)
2. **Gradual opt-in** to new asset class features
3. **Validation warnings** for configs that would benefit from asset classes
4. **Migration utility** to help update existing configs

### Default Behavior
```python
# If no asset_class specified, infer from industry proxy
def infer_asset_class(proxies_dict):
    industry = proxies_dict.get("industry")
    if industry in ["SGOV", "SHY", "IEF", "TLT"]:
        return "government_bonds"
    elif industry in ["SLV", "GLD", "USO"]:
        return "commodities"
    else:
        return "equity"
```

## Benefits of This Architecture

1. **Eliminates Current Bugs**: No more impossible industry beta constraints for bonds
2. **Proper Risk Management**: Each asset class gets appropriate risk treatment
3. **Maintains Compatibility**: Existing portfolios continue to work
4. **Extensible**: Easy to add new asset classes
5. **Industry Standard**: Aligns with institutional risk management practices
6. **Clean Separation**: Clear boundaries between asset class logic

## Testing Strategy

1. **Unit Tests**: Test each asset class function independently
2. **Integration Tests**: Test mixed portfolios with multiple asset classes
3. **Backward Compatibility Tests**: Ensure existing configs still work
4. **Performance Tests**: Ensure no significant performance degradation
5. **Migration Tests**: Test migration from old to new schema 