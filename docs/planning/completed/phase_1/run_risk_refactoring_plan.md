# Run Risk Refactoring Plan

## Overview

This document outlines the step-by-step plan to refactor `run_risk.py` (1164 lines, 47KB) into a clean, modular architecture that separates business logic from interface concerns.

## 🚨 Implementation Notes for Implementing Claude

### Critical Success Factors
- **PRESERVE DUAL-MODE BEHAVIOR**: All functions must maintain both CLI and API modes
- **TEST AFTER EVERY STEP**: Run `python3 test_service_layer.py` after each extraction
- **MAINTAIN EXACT SAME OUTPUT**: CLI formatting must be identical to current behavior
- **EXTRACTION MARKERS**: Follow the extraction markers in `run_risk.py` exactly

### Key Dependencies to Preserve
- All imports from existing modules must be maintained
- Service layer depends on these function signatures remaining unchanged
- API endpoints expect exact same return data structures
- CLI users expect identical printed output

### Extraction Boundaries (Marked in Code)
The `run_risk.py` file now contains clear extraction markers:
- `# EXTRACTION MARKER: utils/serialization.py` - Utility functions
- `# EXTRACTION MARKER: core/portfolio_analysis.py` - Portfolio business logic
- `# EXTRACTION MARKER: core/optimization.py` - Optimization functions
- `# EXTRACTION MARKER: core/stock_analysis.py` - Stock analysis logic
- `# EXTRACTION MARKER: core/performance.py` - Performance calculations
- `# EXTRACTION MARKER: core/scenarios.py` - What-if scenarios
- `# EXTRACTION MARKER: core/interpretation.py` - AI interpretation

### Testing Requirements
- **After each extraction**: Run `python3 test_service_layer.py` (must show 9/9 PASSED)
- **Specific metrics to verify**:
  - Portfolio volatility: 19.80%
  - Performance returns: 25.98%
  - Sharpe ratio: 1.180
  - Risk score: 100 (Excellent)
- **API endpoints**: Must return same structured JSON
- **CLI output**: Must be identical to current behavior

## Current State Analysis

### System Status ✅
- **Service Layer Tests**: 9/9 PASSED (100%)
- **Portfolio Analysis**: 19.80% volatility working correctly
- **Performance Analysis**: 25.98% returns, 1.180 Sharpe ratio
- **API Endpoints**: Responding with structured JSON
- **Dual-Mode Functions**: CLI and API modes both working
- **Caching**: Cache hit/miss functioning correctly

### Problem Statement
Current `run_risk.py` mixes business logic with interface concerns using "hacky" dual-mode functions with `return_data` parameters and `redirect_stdout` to capture print output.

### Target Architecture
```
Core Functions (Pure business logic) → Structured objects
↓  
Formatting Layer (Data → formatted reports) → Human & AI readable
↓
Interface Layer (CLI, API) → Serves all 3 audiences  
```

## File Structure Plan

### Current Structure
```
core/
├── __init__.py                 # Existing - module initialization
├── data_objects.py            # Existing - PortfolioData, data structures (348 lines)
├── result_objects.py          # Existing - RiskAnalysisResult, PerformanceResult, etc. (1138 lines)
└── exceptions.py              # Existing - Custom exceptions (110 lines)
```

### Target Structure
```
core/
├── __init__.py                 # Existing - module initialization
├── data_objects.py            # Existing - PortfolioData, data structures (348 lines)
├── result_objects.py          # Existing - RiskAnalysisResult, PerformanceResult, etc. (1138 lines)
├── exceptions.py              # Existing - Custom exceptions (110 lines)
├── portfolio_analysis.py      # New - Core portfolio risk analysis logic (~250 lines)
├── stock_analysis.py          # New - Individual stock analysis logic (~150 lines)
├── optimization.py            # New - Min/max portfolio optimization logic (~200 lines)
├── performance.py             # New - Performance calculations logic (~150 lines)
├── scenarios.py               # New - What-if scenario logic (~170 lines)
└── interpretation.py          # New - AI interpretation logic (~100 lines)

utils/
├── __init__.py                # New - utilities module initialization
├── serialization.py           # New - JSON/output formatting (~100 lines)
└── data_helpers.py            # New - Data manipulation utilities (~50 lines)

run_risk.py                    # Refactored - thin orchestration layer (~200 lines)
```

## Step-by-Step Implementation Plan

### Step 1: Extract Portfolio Analysis Logic
**Target:** `core/portfolio_analysis.py` (lines 241-423 from `run_risk.py`)

**🚨 CRITICAL IMPLEMENTATION NOTES:**
- Look for the `# EXTRACTION MARKER: core/portfolio_analysis.py` comment in `run_risk.py`
- Extract ONLY the business logic between `# ─── BUSINESS LOGIC START` and `# ─── BUSINESS LOGIC END`
- Do NOT extract the dual-mode logic (CLI/API formatting)
- Preserve all import statements and function signatures

**Implementation:**
```python
# core/portfolio_analysis.py
from typing import Dict, Any
import yaml
from datetime import datetime
from run_portfolio_risk import (
    load_portfolio_config,
    standardize_portfolio_input,
    evaluate_portfolio_beta_limits,
    evaluate_portfolio_risk_limits,
    latest_price
)
from portfolio_risk import build_portfolio_view
from risk_helpers import calc_max_factor_betas
from settings import PORTFOLIO_DEFAULTS

def analyze_portfolio_core(filepath: str) -> Dict[str, Any]:
    """
    Pure portfolio risk calculation logic.
    
    Parameters
    ----------
    filepath : str
        Path to portfolio configuration file
        
    Returns
    -------
    Dict[str, Any]
        Structured analysis data with:
        - config: Portfolio configuration
        - weights: Standardized portfolio weights
        - summary: Portfolio view from build_portfolio_view
        - risk_config: Risk limits configuration
        - df_risk: Risk limit evaluation results
        - df_beta: Beta limit evaluation results
        - max_betas: Calculated maximum beta limits
        - max_betas_by_proxy: Maximum beta limits by proxy
        - lookback_years: Analysis lookback period
    """
    # Extract the business logic from run_portfolio() here
    # This is the core calculation logic between the marked boundaries
    
    # Load configuration
    config = load_portfolio_config(filepath)
    
    with open("risk_limits.yaml", "r") as f:
        risk_config = yaml.safe_load(f)

    weights = standardize_portfolio_input(config["portfolio_input"], latest_price)["weights"]
    
    # Build portfolio view
    summary = build_portfolio_view(
        weights,
        config["start_date"],
        config["end_date"],
        config.get("expected_returns"),
        config.get("stock_factor_proxies")
    )
    
    # Calculate beta limits
    lookback_years = PORTFOLIO_DEFAULTS.get('worst_case_lookback_years', 10)
    max_betas, max_betas_by_proxy = calc_max_factor_betas(
        portfolio_yaml=filepath,
        risk_yaml="risk_limits.yaml",
        lookback_years=lookback_years,
        echo=False
    )
    
    # Run risk checks
    df_risk = evaluate_portfolio_risk_limits(
        summary,
        risk_config["portfolio_limits"],
        risk_config["concentration_limits"],
        risk_config["variance_limits"]
    )
    
    df_beta = evaluate_portfolio_beta_limits(
        portfolio_factor_betas=summary["portfolio_factor_betas"],
        max_betas=max_betas,
        proxy_betas=summary["industry_variance"].get("per_industry_group_beta"),
        max_proxy_betas=max_betas_by_proxy
    )
    
    # Return structured data
    return {
        "config": config,
        "weights": weights,
        "summary": summary,
        "risk_config": risk_config,
        "df_risk": df_risk,
        "df_beta": df_beta,
        "max_betas": max_betas,
        "max_betas_by_proxy": max_betas_by_proxy,
        "lookback_years": lookback_years
    }
```

**Update run_risk.py:**
```python
# run_risk.py
from core.portfolio_analysis import analyze_portfolio_core
from utils.serialization import make_json_safe

def run_portfolio(filepath: str, *, return_data: bool = False):
    """Orchestrator - delegates to core function"""
    # Call pure core function
    core_data = analyze_portfolio_core(filepath)
    
    # Extract variables for compatibility
    config = core_data["config"]
    summary = core_data["summary"]
    df_risk = core_data["df_risk"]
    df_beta = core_data["df_beta"]
    max_betas = core_data["max_betas"]
    max_betas_by_proxy = core_data["max_betas_by_proxy"]
    weights = core_data["weights"]
    lookback_years = core_data["lookback_years"]
    risk_config = core_data["risk_config"]
    
    # Continue with existing dual-mode logic (unchanged)
    if return_data:
        # API MODE: Return structured data (EXISTING LOGIC)
        # ... keep all existing return logic ...
    else:
        # CLI MODE: Print formatted output (EXISTING LOGIC)
        # ... keep all existing print logic ...
```

**🚨 CRITICAL GOTCHAS:**
- The dual-mode logic must remain in `run_risk.py` - do NOT extract it
- All variable names must match exactly for compatibility
- The `make_json_safe()` function is used in dual-mode logic
- Import statements must be preserved exactly

**Test:** Run `python3 test_service_layer.py` to verify portfolio analysis still works

### Step 2: Update run_portfolio() to Use Core Function
**Target:** Update `run_risk.py` to call `core/portfolio_analysis.py`

**Test:** Run dual-mode function test to verify both CLI and API modes work

### Step 3: Extract Utilities to utils/serialization.py
**Target:** `utils/serialization.py` (utilities like `make_json_safe`)

**🚨 CRITICAL IMPLEMENTATION NOTES:**
- Create the `utils/` directory if it doesn't exist
- Extract all functions marked with `# EXTRACTION MARKER: utils/serialization.py`
- Update all imports across the codebase to use `from utils.serialization import ...`

**Implementation:**
```python
# utils/__init__.py
# Empty file to make utils a package

# utils/serialization.py
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any

def make_json_safe(obj):
    """Recursively convert any object to JSON-serializable format."""
    # Move the exact logic from run_risk.py here
    if isinstance(obj, dict):
        # ... exact existing logic ...
    # ... rest of function unchanged ...

def format_portfolio_output_as_text(portfolio_output: Dict[str, Any]) -> str:
    """
    Convert structured portfolio output back to formatted text.
    
    This enables AI interpretation of cached portfolio analysis results
    without needing to re-run the full analysis.
    """
    # Move the exact logic from _format_portfolio_output_as_text here
    if "formatted_report" in portfolio_output:
        return portfolio_output["formatted_report"]
    # ... rest of function unchanged ...
```

**Update imports in run_risk.py:**
```python
# run_risk.py
from utils.serialization import make_json_safe, format_portfolio_output_as_text
```

**🚨 CRITICAL GOTCHAS:**
- Must update imports in ALL files that use these functions
- Service layer may also import these functions
- Function signatures must remain identical
- All existing behavior must be preserved

**Test:** Run API endpoint tests to verify JSON serialization works

### Step 4: Extract Optimization Logic
**Target:** `core/optimization.py` (min_variance + max_return functions)

**🚨 CRITICAL IMPLEMENTATION NOTES:**
- Extract both `run_min_variance()` and `run_max_return()` functions
- Both functions have dual-mode behavior that must be preserved
- Look for `# EXTRACTION MARKER: core/optimization.py` comments

**Implementation:**
```python
# core/optimization.py
from typing import Dict, Any
import yaml
from datetime import datetime
from run_portfolio_risk import (
    load_portfolio_config,
    standardize_portfolio_input,
    latest_price
)
from portfolio_optimizer import (
    run_min_var,
    run_max_return_portfolio,
    print_min_var_report,
    print_max_return_report,
)

def optimize_min_variance_core(filepath: str) -> Dict[str, Any]:
    """
    Pure minimum variance optimization logic.
    
    Returns
    -------
    Dict[str, Any]
        Structured optimization data with:
        - config: Portfolio configuration
        - risk_config: Risk limits configuration
        - weights: Original portfolio weights
        - optimized_weights: Optimized weights (w)
        - risk_table: Risk evaluation table (r)
        - beta_table: Beta evaluation table (b)
    """
    # Extract the business logic from run_min_variance() here
    config = load_portfolio_config(filepath)
    with open("risk_limits.yaml", "r") as f:
        risk_config = yaml.safe_load(f)

    weights = standardize_portfolio_input(config["portfolio_input"], latest_price)["weights"]

    # Run the optimization
    w, r, b = run_min_var(
        base_weights=weights,
        config=config,
        risk_config=risk_config,
        proxies=config["stock_factor_proxies"],
    )
    
    return {
        "config": config,
        "risk_config": risk_config,
        "weights": weights,
        "optimized_weights": w,
        "risk_table": r,
        "beta_table": b
    }

def optimize_max_return_core(filepath: str) -> Dict[str, Any]:
    """
    Pure maximum return optimization logic.
    
    Returns
    -------
    Dict[str, Any]
        Structured optimization data with:
        - config: Portfolio configuration
        - risk_config: Risk limits configuration
        - weights: Original portfolio weights
        - optimized_weights: Optimized weights (w)
        - portfolio_summary: Portfolio view of optimized weights
        - risk_table: Risk evaluation table (r)
        - factor_beta_table: Factor beta evaluation table (f_b)
        - proxy_beta_table: Proxy beta evaluation table (p_b)
    """
    # Extract the business logic from run_max_return() here
    config = load_portfolio_config(filepath)
    with open("risk_limits.yaml", "r") as f:
        risk_config = yaml.safe_load(f)

    weights = standardize_portfolio_input(config["portfolio_input"], latest_price)["weights"]
    
    # Run the optimization
    w, summary, r, f_b, p_b = run_max_return_portfolio(
        weights=weights,
        config=config,
        risk_config=risk_config,
        proxies=config["stock_factor_proxies"],
    )
    
    return {
        "config": config,
        "risk_config": risk_config,
        "weights": weights,
        "optimized_weights": w,
        "portfolio_summary": summary,
        "risk_table": r,
        "factor_beta_table": f_b,
        "proxy_beta_table": p_b
    }
```

**🚨 CRITICAL GOTCHAS:**
- The optimization functions call external modules like `portfolio_optimizer`
- Return data structures must match exactly what the dual-mode logic expects
- Print functions (`print_min_var_report`, `print_max_return_report`) remain in CLI mode
- All imports must be preserved

**Test:** Run optimization tests to verify both functions work

### Step 5: Extract Stock Analysis Logic
**Target:** `core/stock_analysis.py` (lines 860-991)

**🚨 CRITICAL IMPLEMENTATION NOTES:**
- This function has complex parameter handling with defaults
- Factor proxy injection logic must be preserved
- Look for `# EXTRACTION MARKER: core/stock_analysis.py` comment

**Implementation:**
```python
# core/stock_analysis.py
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from risk_summary import (
    get_detailed_stock_factor_profile,
    get_stock_risk_profile
)
from proxy_builder import inject_all_proxies
from helpers_display import format_stock_metrics

def analyze_stock_core(ticker: str, start: Optional[str] = None, 
                      end: Optional[str] = None,
                      factor_proxies: Optional[Dict[str, Union[str, List[str]]]] = None,
                      yaml_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Pure stock analysis logic.
    
    Returns
    -------
    Dict[str, Any]
        Structured stock analysis data with:
        - ticker: Stock ticker symbol
        - analysis_period: Start and end dates
        - factor_proxies: Factor proxy configuration
        - risk_profile: Basic risk metrics
        - detailed_profile: Detailed factor analysis
        - risk_metrics: Formatted risk metrics
    """
    # Extract the business logic from run_stock() here
    # Handle date defaults
    if start is None:
        start = "2020-01-01"
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    
    # Handle factor proxies
    if factor_proxies is None:
        if yaml_path is not None:
            import yaml
            with open(yaml_path, 'r') as f:
                config = yaml.safe_load(f)
            factor_proxies = config.get("stock_factor_proxies", {})
        else:
            factor_proxies = {}
    
    # Inject proxies
    factor_proxies = inject_all_proxies(factor_proxies)
    
    # Get risk profiles
    risk_profile = get_stock_risk_profile(ticker, start, end, factor_proxies)
    detailed_profile = get_detailed_stock_factor_profile(ticker, start, end, factor_proxies)
    
    # Format metrics
    risk_metrics = {}
    if risk_profile and "regression_results" in risk_profile:
        risk_metrics = format_stock_metrics(risk_profile["regression_results"], f"Market Regression ({ticker})")
    
    return {
        "ticker": ticker,
        "analysis_period": {
            "start": start,
            "end": end
        },
        "factor_proxies": factor_proxies,
        "risk_profile": risk_profile,
        "detailed_profile": detailed_profile,
        "risk_metrics": risk_metrics
    }
```

**🚨 CRITICAL GOTCHAS:**
- Default parameter handling is complex and must be preserved exactly
- The `inject_all_proxies()` function modifies the factor_proxies dict
- YAML loading logic must be preserved if yaml_path is provided
- The function returns complex nested dictionaries

**Test:** Run stock analysis test to verify SGOV analysis works

### Step 6: Extract Performance Analysis Logic
**Target:** `core/performance.py` (lines 991-END)

**🚨 CRITICAL IMPLEMENTATION NOTES:**
- This function calculates portfolio performance metrics
- Must preserve exact calculation logic for returns and Sharpe ratio
- Look for `# EXTRACTION MARKER: core/performance.py` comment

**Implementation:**
```python
# core/performance.py
from typing import Dict, Any

def calculate_portfolio_performance_core(filepath: str) -> Dict[str, Any]:
    """
    Pure performance calculation logic.
    
    Returns
    -------
    Dict[str, Any]
        Structured performance data with:
        - returns_analysis: Total returns, annualized returns
        - risk_metrics: Sharpe ratio, volatility, max drawdown
        - benchmark_comparison: Performance vs benchmarks
        - attribution_analysis: Factor contribution to returns
    """
    # Move performance calculation logic here
```

**Test:** Run performance tests to verify 25.98% returns, 1.180 Sharpe

### Step 7: Extract What-If Scenario Logic
**Target:** `core/scenarios.py` (lines 423-592)

**🚨 CRITICAL IMPLEMENTATION NOTES:**
- This function handles scenario analysis with complex delta parsing
- Must preserve exact scenario application logic
- Look for `# EXTRACTION MARKER: core/scenarios.py` comment

**Implementation:**
```python
# core/scenarios.py
from typing import Dict, Any, Optional

def run_what_if_scenario_core(filepath: str, scenario_yaml: Optional[str] = None,
                             delta: Optional[str] = None) -> Dict[str, Any]:
    """
    Pure what-if scenario logic.
    
    Returns
    -------
    Dict[str, Any]
        Structured scenario analysis data with:
        - base_portfolio: Original portfolio metrics
        - scenario_portfolio: Modified portfolio metrics
        - impact_analysis: Changes in risk/return
        - recommendations: Scenario-specific insights
    """
    # Move what-if scenario logic here
```

**Test:** Run what-if scenario test to verify functionality

### Step 8: Extract AI Interpretation Logic
**Target:** `core/interpretation.py`

**🚨 CRITICAL IMPLEMENTATION NOTES:**
- Functions that call GPT for analysis interpretation
- Must preserve exact GPT integration logic
- Look for `# EXTRACTION MARKER: core/interpretation.py` comments

**Implementation:**
```python
# core/interpretation.py
from typing import Dict, Any

def interpret_analysis_core(analysis_data: Dict[str, Any], 
                           analysis_type: str = "portfolio") -> Dict[str, Any]:
    """
    Pure AI interpretation logic.
    
    Returns
    -------
    Dict[str, Any]
        Structured interpretation data with:
        - ai_interpretation: GPT analysis summary
        - key_insights: Bullet-point highlights
        - recommendations: Actionable suggestions
        - risk_alerts: Important warnings
    """
    # Move AI interpretation logic here
```

### Step 9: Comprehensive Module Testing
**Target:** Test all extracted modules work together

**🚨 CRITICAL TESTING REQUIREMENTS:**
- **MUST PASS**: `python3 test_service_layer.py` (all 9 tests)
- **MUST VERIFY**: Exact same metrics as before refactoring
- **MUST CHECK**: API endpoints return identical JSON structures
- **MUST CONFIRM**: CLI output is identical to before refactoring

**Testing Checklist:**
- [ ] Run `python3 test_service_layer.py` (all 9 tests should pass)
- [ ] Run `python3 comprehensive_test.py` (cross-path consistency)
- [ ] Run dual-mode function tests
- [ ] Run API endpoint tests
- [ ] Verify specific metrics:
  - Portfolio analysis: 19.80% volatility ✅
  - Performance: 25.98% returns, 1.180 Sharpe ✅
  - Risk score: Score 100 (Excellent) ✅
  - API endpoints: Structured JSON responses ✅

### Step 10: Update Service Layer
**Target:** Make services call core modules directly

**🚨 CRITICAL IMPLEMENTATION NOTES:**
- Services currently call `run_risk.py` dual-mode functions
- Must update to call core modules directly
- Must preserve exact return data structures for service layer

**Implementation:**
```python
# services/portfolio_service.py
from core.portfolio_analysis import analyze_portfolio_core
from core.optimization import optimize_min_variance_core, optimize_max_return_core
from core.performance import calculate_portfolio_performance_core
from core.stock_analysis import analyze_stock_core
from core.scenarios import run_what_if_scenario_core

class PortfolioService:
    def analyze_portfolio(self, portfolio_data):
        # Direct call to core (bypass run_risk.py)
        analysis_data = analyze_portfolio_core(temp_file)
        return RiskAnalysisResult.from_dict(analysis_data)
        
    def optimize_portfolio(self, portfolio_data, objective="min_variance"):
        if objective == "min_variance":
            return optimize_min_variance_core(temp_file)
        elif objective == "max_return":
            return optimize_max_return_core(temp_file)
```

**Test:** Run service layer tests to verify direct core calls work

### Step 11: Final Cleanup and Validation
**Target:** Clean up imports, verify all functionality

**🚨 FINAL VALIDATION REQUIREMENTS:**
- All tests must pass (9/9 service layer tests)
- CLI behavior must be identical to before refactoring
- API endpoints must return identical JSON structures
- Performance metrics must be identical
- No regressions in any functionality

**Implementation:**
- Remove unused imports from `run_risk.py`
- Update `core/__init__.py` to export new functions:
  ```python
  # core/__init__.py
  from .portfolio_analysis import analyze_portfolio_core
  from .stock_analysis import analyze_stock_core
  from .optimization import optimize_min_variance_core, optimize_max_return_core
  from .performance import calculate_portfolio_performance_core
  from .scenarios import run_what_if_scenario_core
  from .interpretation import interpret_analysis_core
  ```
- Update `utils/__init__.py` to export utilities:
  ```python
  # utils/__init__.py
  from .serialization import make_json_safe, format_portfolio_for_cli, format_stock_for_cli
  ```

**Test:** Run all tests to ensure 100% functionality preservation

## Testing Strategy

### After Each Step:
1. **Run specific test**: Target the functionality you just extracted
2. **Run regression test**: `python3 test_service_layer.py` (9 tests must pass)
3. **Test dual modes**: Verify both CLI and API modes work
4. **Quick API check**: Test one endpoint to verify JSON serialization

### Critical Success Metrics:
- Service layer tests: 9/9 PASSED
- Portfolio analysis: 19.80% volatility ✅
- Performance: 25.98% returns, 1.180 Sharpe ✅
- Risk score: Score 100 (Excellent) ✅
- API endpoints: Returning structured JSON ✅

### Test Files Available:
1. `test_service_layer.py` - Service layer vs direct function comparison
2. `comprehensive_test.py` - Cross-path consistency validation
3. `test_api_endpoints.py` - API endpoint validation
4. `backup_functions_for_testing.py` - Backup function validation

## Benefits of This Refactoring

### Immediate Benefits:
- **Clearer Responsibility**: Each module has one job
- **Easier Testing**: Test business logic separately from formatting
- **Better Imports**: No circular dependencies
- **Simpler Service Layer**: Direct calls to core functions

### Long-term Benefits:
- **Performance Optimization**: Easier to profile and optimize specific calculations
- **New Output Formats**: JSON, Excel, PDF formatters become trivial
- **Better Caching**: Cache at the core function level
- **Team Development**: Multiple developers can work on different modules
- **Claude Integration**: Clean core functions for AI interpretation

### Architecture Improvements:
- **Separation of Concerns**: Business logic separated from interface
- **Testability**: Each module can be tested independently
- **Maintainability**: Changes to business logic don't affect interface
- **Extensibility**: Easy to add new analysis types or output formats

## Risk Mitigation

### Safety Measures:
- **Comprehensive Test Suite**: Validates current functionality
- **Step-by-Step Approach**: Each extraction is independently testable
- **Backup System**: Multiple backup layers protect against data loss
- **Service Layer Safety Net**: Existing service layer provides fallback

### Rollback Plan:
- Each step can be reverted independently
- Git commits at each step provide rollback points
- Existing functionality preserved until final switchover

## Success Criteria

### Technical Criteria:
- [ ] All existing tests pass (9/9 service layer tests)
- [ ] CLI functions work identically to before
- [ ] API endpoints return same structured data
- [ ] Performance metrics remain consistent
- [ ] Service layer calls core functions directly

### Code Quality Criteria:
- [ ] `run_risk.py` reduced from 1164 to ~200 lines
- [ ] Business logic separated into focused modules
- [ ] Clean imports with no circular dependencies
- [ ] Comprehensive documentation for each module
- [ ] Type hints for all core functions

### Integration Criteria:
- [ ] Claude can call core functions directly
- [ ] Service layer no longer depends on run_risk.py dual-mode
- [ ] New output formats can be added easily
- [ ] Caching can be implemented at core level

## Next Steps

1. **Start with Step 1**: Extract portfolio analysis logic to `core/portfolio_analysis.py`
2. **Test Immediately**: Run service layer tests after each extraction
3. **Document Changes**: Update this plan as implementation progresses
4. **Validate Benefits**: Confirm each benefit is realized
5. **Plan Next Phase**: Consider further architectural improvements

This refactoring will transform the codebase from a monolithic CLI-focused system to a clean, modular architecture that serves CLI, API, and AI integration equally well. 

## 🚨 Critical Implementation Gotchas

### Import Management
- Many functions have complex import dependencies
- Service layer imports must be updated carefully
- Circular import issues may arise - test thoroughly

### Dual-Mode Behavior
- **NEVER extract dual-mode logic** - keep in `run_risk.py`
- CLI formatting must remain identical
- API return structures must be preserved exactly

### Data Structure Compatibility
- Service layer expects exact data structures
- Variable names in dual-mode logic must match core function returns
- JSON serialization must work identically

### Function Signatures
- All existing function signatures must be preserved
- Parameter defaults must remain identical
- Return types must match exactly

### Testing Requirements
- Test after EVERY extraction step
- Verify specific metrics haven't changed
- Check both CLI and API modes work

## Risk Mitigation for Implementation

### If Something Goes Wrong
1. **Revert the specific step** - each extraction is independent
2. **Check the extraction markers** - follow them exactly
3. **Verify imports** - missing imports cause most issues
4. **Test dual-mode behavior** - CLI and API modes must both work
5. **Check service layer** - may need import updates

### Success Validation
- Service layer tests: 9/9 PASSED ✅
- Portfolio volatility: 19.80% (unchanged) ✅
- Performance returns: 25.98% (unchanged) ✅
- Sharpe ratio: 1.180 (unchanged) ✅
- API endpoints: Return identical JSON ✅
- CLI output: Identical to before refactoring ✅

This refactoring will transform the codebase from a monolithic CLI-focused system to a clean, modular architecture that serves CLI, API, and AI integration equally well. 