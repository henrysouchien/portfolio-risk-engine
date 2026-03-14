# 🗺️ SERVICE LAYER CONNECTION MAP

## 🚨 CURRENT STATUS: BROKEN CONNECTIONS

### 1. **MISSING CORE MODULES** ❌
The service layer is trying to import from `core/` modules that don't fully exist:

```python
# In services/portfolio_service.py:
from core.data_objects import PortfolioData  ✅ EXISTS
from core.result_objects import RiskAnalysisResult, RiskScoreResult, PerformanceResult  ✅ EXISTS
from core.exceptions import PortfolioAnalysisError, PortfolioValidationError  ✅ EXISTS

# In routes/api.py:
from core.portfolio_analysis import analyze_portfolio  ✅ EXISTS (but incomplete)
```

### 2. **SERVICE LAYER ARCHITECTURE** 

```
FRONTEND (React)
    ↓ HTTP Request
ROUTES (api.py, claude.py, etc.)
    ↓ Calls service methods
SERVICES (portfolio_service.py, etc.)
    ↓ Should call core business logic
CORE (portfolio_analysis.py, etc.)  ⚠️ PARTIALLY IMPLEMENTED
    ↓ Calls your original functions
YOUR CODE (run_risk.py, portfolio_risk.py, etc.)
```

### 3. **ACTUAL CONNECTIONS FOUND**

#### API Route → Service Layer:
```python
# routes/api.py line 202:
result = portfolio_service.analyze_portfolio(portfolio_data)
```

#### Service Layer → Core (SHOULD BE):
```python
# services/portfolio_service.py SHOULD call:
from core.portfolio_analysis import analyze_portfolio
# But instead it's calling run_risk.py directly!
```

#### Core → Your Original Code:
```python
# core/portfolio_analysis.py line 13-22:
from run_portfolio_risk import (
    load_portfolio_config,
    standardize_portfolio_input,
    latest_price,
    evaluate_portfolio_risk_limits,
    evaluate_portfolio_beta_limits,
)
from portfolio_risk import build_portfolio_view
```

### 4. **WHAT'S ACTUALLY HAPPENING**

The service layer is **BYPASSING** the core layer and calling your functions directly:

```python
# services/portfolio_service.py line 33:
from run_risk import run_portfolio, run_and_interpret  # DIRECT CALL!
```

### 5. **DATA FLOW PROBLEMS**

1. **PortfolioData Object**: Created but not consistently used
2. **Result Objects**: Created but services return different formats
3. **Validation**: Service validates but core doesn't use validated data
4. **Caching**: Mentioned but not implemented

### 6. **KEY BROKEN CONNECTIONS**

| Layer | Should Call | Actually Calls | Status |
|-------|-------------|----------------|--------|
| API | portfolio_service.analyze_portfolio() | ✅ Correct | Working |
| Service | core.portfolio_analysis.analyze_portfolio() | run_risk.run_portfolio() | ❌ BYPASSED |
| Core | Your original functions | ✅ Correct | Working |

### 7. **MISSING IMPLEMENTATIONS**

- [ ] Service layer caching (mentioned but not implemented)
- [ ] Result object conversions (to_dict(), to_formatted_report())
- [ ] Proper error handling chain
- [ ] Consistent data flow through layers

### 8. **QUICK FIX NEEDED**

The service layer should:
1. Call core functions (not run_risk.py directly)
2. Use PortfolioData objects consistently
3. Return proper Result objects
4. Implement promised caching

### 9. **FRONTEND CONNECTIONS**

```javascript
// frontend/src/services/api.js (presumably):
fetch('/api/analyze', {
    method: 'POST',
    body: JSON.stringify(portfolioData)
})
```

### 10. **DATABASE CONNECTIONS**

```python
# inputs/portfolio_manager.py:
# Handles both YAML files and database
# But service layer doesn't use it consistently
```

## 🔧 RECOMMENDED FIXES

1. **Complete core layer implementation** - Make analyze_portfolio() actually work
2. **Fix service layer calls** - Stop bypassing core layer
3. **Implement result objects properly** - Add missing to_dict() methods
4. **Add caching where promised** - Redis or in-memory cache
5. **Consistent data flow** - PortfolioData → Analysis → Result

## 🎯 CRITICAL PATH TO FIX

1. Fix `core/portfolio_analysis.py` to properly wrap your functions
2. Update `services/portfolio_service.py` to call core (not run_risk)
3. Implement proper result object methods
4. Test end-to-end flow: Frontend → API → Service → Core → Your Code