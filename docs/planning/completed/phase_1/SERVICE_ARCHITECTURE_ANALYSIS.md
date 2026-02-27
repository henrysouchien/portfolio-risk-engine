# SERVICE LAYER ARCHITECTURE ANALYSIS

## CURRENT STATE ANALYSIS

### 1. **ARCHITECTURAL INTENT**

The system was designed with a 3-layer architecture:

```
LAYER 1: ROUTES (User Interface)
    - API endpoints (routes/api.py)
    - Web routes (app.py)
    - Claude AI routes (routes/claude.py)
    
LAYER 2: SERVICES (Business Orchestration)
    - Portfolio Service (services/portfolio_service.py)
    - Stock Service (services/stock_service.py)
    - Scenario Service (services/scenario_service.py)
    - Optimization Service (services/optimization_service.py)
    
LAYER 3: CORE (Pure Business Logic)
    - Portfolio Analysis (core/portfolio_analysis.py)
    - Stock Analysis (core/stock_analysis.py)
    - Scenario Analysis (core/scenario_analysis.py)
    - Optimization (core/optimization.py)
    
LAYER 4: DATA (Your Original Functions)
    - portfolio_risk.py (build_portfolio_view)
    - run_risk.py (run_portfolio, run_stock, etc.)
    - portfolio_optimizer.py (optimization functions)
```

### 2. **ACTUAL IMPLEMENTATION ISSUES**

#### Issue 1: Services Bypass Core Layer

**PROBLEM**: Services are importing run_risk.py directly instead of using core layer

```python
# services/portfolio_service.py line 33:
from run_risk import run_portfolio, run_and_interpret  # WRONG - bypasses core!

# SHOULD BE:
from core.portfolio_analysis import analyze_portfolio
```

#### Issue 2: Core Layer Incomplete

**PROBLEM**: core/portfolio_analysis.py exists but doesn't wrap run_portfolio properly

```python
# Current core/portfolio_analysis.py:
def analyze_portfolio(filepath: str) -> Dict[str, Any]:
    # Calls individual functions but not run_portfolio
    # Missing the formatted_report generation
    # Not using dual-mode interface
```

#### Issue 3: Data Flow Inconsistency

**PROBLEM**: Different layers expect different data formats

```python
# Service expects: PortfolioData object
# Core expects: filepath string
# run_portfolio expects: filepath string with return_data=True
```

### 3. **PROPER CONNECTION MAPPING**

| Service Method | Should Call | Currently Calls | Status |
|----------------|-------------|-----------------|--------|
| **PortfolioService** |
| analyze_portfolio() | core.portfolio_analysis.analyze_portfolio() | run_risk.run_portfolio() | ❌ BYPASSED |
| analyze_and_interpret() | core.interpretation.analyze_and_interpret() | run_risk.run_and_interpret() | ❌ BYPASSED |
| analyze_risk_score() | core.portfolio_analysis.analyze_risk_score() | portfolio_risk_score.run_risk_score_analysis() | ❌ BYPASSED |
| analyze_performance() | core.performance_analysis.analyze_performance() | run_risk.run_portfolio_performance() | ❌ BYPASSED |
| **StockService** |
| analyze_stock() | core.stock_analysis.analyze_stock() | run_risk.run_stock() | ❌ BYPASSED |
| **ScenarioService** |
| analyze_scenario() | core.scenario_analysis.analyze_scenario() | run_risk.run_what_if() | ❌ MISSING |
| **OptimizationService** |
| optimize_min_variance() | core.optimization.optimize_min_variance() | run_risk.run_min_variance() | ❌ MISSING |
| optimize_max_return() | core.optimization.optimize_max_return() | run_risk.run_max_return() | ❌ MISSING |

### 4. **REQUIRED CORE FUNCTIONS**

Each core function needs to:
1. Accept structured data (not just file paths)
2. Call the appropriate run_risk.py function with return_data=True
3. Return structured data that services can convert to result objects
4. Include formatted_report in the output

### 5. **DATA OBJECT FLOW**

```
API Request (JSON)
    ↓
Route converts to PortfolioData
    ↓
Service validates PortfolioData
    ↓
Service creates temp YAML file
    ↓
Core function receives filepath
    ↓
Core calls run_risk function with return_data=True
    ↓
Core returns structured Dict
    ↓
Service converts to Result object
    ↓
Route returns JSON response
```

### 6. **CRITICAL IMPLEMENTATION TASKS**

1. **Update all core functions** to properly wrap run_risk functions
2. **Update all services** to call core functions instead of run_risk
3. **Ensure data consistency** through all layers
4. **Add formatted_report** to all core function outputs
5. **Test each connection** individually

### 7. **VALIDATION CHECKLIST**

For each service → core connection:
- [ ] Core function exists and is complete
- [ ] Core function calls run_risk with return_data=True
- [ ] Core function returns all needed data including formatted_report
- [ ] Service calls core function (not run_risk directly)
- [ ] Service properly converts core output to result object
- [ ] Result object has all required methods (to_dict, to_formatted_report)
- [ ] End-to-end test passes from API to core to data layer