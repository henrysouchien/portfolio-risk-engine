# Result Object Factory Method Reference

**Last Updated**: 2025-08-05  
**Purpose**: Quick reference for correct factory method names and usage

---

## Core Function → Result Object Factory Method Mappings

### 1. Risk Score Analysis
**Core Function**: `run_risk_score_analysis()` in `portfolio_risk_score.py`  
**Factory Method**: `RiskScoreResult.from_risk_score_analysis()`

```python
from core.result_objects import RiskScoreResult

# Usage
risk_data = run_risk_score_analysis("portfolio.yaml", "risk_limits.yaml", return_data=True)
result = RiskScoreResult.from_risk_score_analysis(risk_data)
```

### 2. Portfolio Risk Analysis
**Core Function**: `build_portfolio_view()` in `portfolio_risk.py`  
**Factory Method**: `RiskAnalysisResult.from_build_portfolio_view()`

```python
from core.result_objects import RiskAnalysisResult

# Usage
portfolio_view = build_portfolio_view(weights, start_date, end_date, expected_returns, proxies)
result = RiskAnalysisResult.from_build_portfolio_view(portfolio_view, portfolio_name="My Portfolio")
```

### 3. Performance Analysis
**Core Function**: `calculate_portfolio_performance_metrics()` in `portfolio_risk.py`  
**Factory Method**: `PerformanceResult.from_performance_metrics()`

```python
from core.result_objects import PerformanceResult

# Usage
perf_metrics = calculate_portfolio_performance_metrics(weights, start_date, end_date)
result = PerformanceResult.from_performance_metrics(perf_metrics, portfolio_name="My Portfolio")
```

### 4. What-If Scenario Analysis
**Core Function**: `run_what_if()` in `run_risk.py`  
**Factory Method**: `WhatIfResult.from_what_if_output()`

```python
from core.result_objects import WhatIfResult

# Usage - Note: Uses from_what_if_output(), not from_what_if_analysis()
current_summary = build_portfolio_view(current_weights, ...)
scenario_summary = build_portfolio_view(scenario_weights, ...)
result = WhatIfResult.from_what_if_output(
    current_summary=current_summary,
    scenario_summary=scenario_summary,
    scenario_name="Reduce AAPL by 5%"
)
```

### 5. Portfolio Optimization
**Core Functions**: `run_min_variance()` and `run_max_return()` in `run_risk.py`  
**Factory Methods**: 
- `OptimizationResult.from_min_variance_output()` 
- `OptimizationResult.from_max_return_output()`

```python
from core.result_objects import OptimizationResult

# Min Variance Optimization
weights, risk_table, beta_table = run_min_var(...)
result = OptimizationResult.from_min_variance_output(weights, risk_table, beta_table)

# Max Return Optimization  
weights, summary, risk_table, factor_table, proxy_table = run_max_return_portfolio(...)
result = OptimizationResult.from_max_return_output(
    weights, summary, risk_table, factor_table, proxy_table
)
```

---

## Notes on Method Naming

### Historical Context
Some early planning documents may reference these **outdated method names**:
- ❌ `WhatIfResult.from_what_if_analysis()` → ✅ `WhatIfResult.from_what_if_output()`
- ❌ `OptimizationResult.from_optimization()` → ✅ `OptimizationResult.from_min_variance_output()` / `from_max_return_output()`
- ❌ `RiskAnalysisResult.from_portfolio_analysis()` → ✅ `RiskAnalysisResult.from_build_portfolio_view()`
- ❌ `PerformanceResult.from_performance_analysis()` → ✅ `PerformanceResult.from_performance_metrics()`

### Design Rationale
The current method names are more descriptive and provide better type safety:
- `from_what_if_output()` clearly indicates it processes output from what-if functions
- Separate `from_min_variance_output()` and `from_max_return_output()` methods handle different optimization return types
- `from_build_portfolio_view()` explicitly matches the core function name
- `from_performance_metrics()` clearly indicates it processes performance metrics data

---

## Service Layer Usage

These factory methods are primarily used in the service layer:

**PortfolioService** (`services/portfolio_service.py`):
- Uses `RiskAnalysisResult.from_build_portfolio_view()`
- Uses `PerformanceResult.from_performance_metrics()`
- Uses `RiskScoreResult.from_risk_score_analysis()`

**ScenarioService** (`services/scenario_service.py`):
- Uses `WhatIfResult.from_what_if_output()`

**OptimizationService** (`services/optimization_service.py`):
- Uses `OptimizationResult.from_min_variance_output()`
- Uses `OptimizationResult.from_max_return_output()`

---

## OpenAPI Integration

All factory methods are fully compatible with OpenAPI schema generation:
✅ Complete data capture  
✅ Type-safe interfaces  
✅ Proper serialization support  
✅ No data loss concerns