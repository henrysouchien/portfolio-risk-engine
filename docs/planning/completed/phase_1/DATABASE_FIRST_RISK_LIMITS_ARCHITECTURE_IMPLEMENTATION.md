# Database-First Risk Limits Architecture

## Overview
This document outlines the systematic process for refactoring API routes to use user-specific `RiskLimitsData` objects from the database instead of hardcoded `risk_limits.yaml` files. This ensures multi-user safety, proper data isolation, and clean architectural separation.

## Template: Refactoring API Routes to Database-First Risk Limits

### ✅ Completed Example: `/api/risk-score`
We successfully refactored the `api_risk_score` route using this process. Use this as a reference template.

### 🎯 Target for Refactoring: `/api/analyze`
The `/analyze` API route currently uses hardcoded `risk_limits.yaml` and needs the same refactoring.

---

## Step-by-Step Refactoring Process

### **Phase 1: Understand Current Architecture**

#### 1.1 Identify Current Risk Limits Usage
```bash
# Find how risk limits are currently used in the target route
grep -r "risk_limits" routes/api.py
grep -r "risk_limits.yaml" routes/api.py
```

#### 1.2 Trace Service Layer Dependencies
```bash
# Find which service methods the API route calls
grep -A 20 -B 5 "def api_analyze" routes/api.py
```

#### 1.3 Document Current Flow
Document the current data flow:
```
Current: API → Service → Hardcoded risk_limits.yaml
Target:  API → RiskLimitsManager → Service → RiskLimitsData
```

### **Phase 2: Update Service Layer First**

#### 2.1 Modify Service Method Signature
**Location**: `services/portfolio_service.py` (or relevant service file)

**Before**:
```python
def analyze_portfolio(self, portfolio_data: PortfolioData, risk_file: str = "risk_limits.yaml"):
```

**After**:
```python
def analyze_portfolio(self, portfolio_data: PortfolioData, risk_limits_data: RiskLimitsData):
```

#### 2.2 Remove Internal Risk Limits Loading
**Remove these patterns from service methods**:
```python
# Remove these lines:
portfolio_manager = PortfolioManager(use_database=True, user_id=user_id)
risk_limits_manager = RiskLimitsManager(use_database=True, user_id=user_id)
risk_limits = risk_limits_manager.load_risk_limits(portfolio_name)

# Remove fallback logic:
if not os.path.exists(risk_file):
    risk_file = "risk_limits.yaml"
```

#### 2.3 Add Validation for Required Risk Limits
```python
def analyze_portfolio(self, portfolio_data: PortfolioData, risk_limits_data: RiskLimitsData):
    """
    Service method expects valid RiskLimitsData - no fallbacks at service layer.
    """
    if not risk_limits_data or risk_limits_data.is_empty():
        raise ValueError(
            "No valid risk limits provided. Risk limits must be provided by the caller "
            "(typically from RiskConfigManager). Service layer does not handle fallbacks."
        )
```

#### 2.4 Update Temporary File Creation
**Replace**:
```python
# Old pattern:
temp_risk_file = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
# ... write risk_limits dict to file ...
```

**With**:
```python
# New pattern:
temp_risk_file = portfolio_data.create_risk_limits_temp_file(risk_limits_data)
```

#### 2.5 Update Cache Key Generation
**Replace**:
```python
# Old pattern:
cache_key = f"analysis_{portfolio_data.get_cache_key()}_default"
```

**With**:
```python
# New pattern:
risk_cache_key = risk_limits_data.get_cache_key()
cache_key = f"analysis_{portfolio_data.get_cache_key()}_{risk_cache_key}"
```

### **Phase 3: Update API Layer**

#### 3.1 Import Required Components
```python
# Add to imports in routes/api.py
from inputs.risk_limits_manager import RiskLimitsManager
from utils.logging import portfolio_logger  # Ensure consistent logging
```

#### 3.2 Add Risk Limits Orchestration
**Insert this block after portfolio data loading**:
```python
# Get user-specific risk limits using RiskLimitsManager
risk_limits_manager = RiskLimitsManager(use_database=True, user_id=user['user_id'])

try:
    # Always provide a valid RiskLimitsData to the service (no service-level fallbacks)
    risk_limits_data = risk_limits_manager.load_risk_limits(portfolio_name)
    result = portfolio_service.analyze_portfolio(portfolio_data, risk_limits_data)
except Exception as e:
    # Database load failed – gracefully fall back to file mode, still passing RiskLimitsData
    portfolio_logger.warning(f"Risk limits loading failed for user {user['user_id']}: {e}")
    fallback_manager = RiskLimitsManager(use_database=False)
    fallback_limits = fallback_manager.load_risk_limits()
    result = portfolio_service.analyze_portfolio(portfolio_data, fallback_limits)
```

#### 3.3 Update API Docstring
Update the API endpoint docstring to document the new flow:
```python
def api_analyze():
    """
    API endpoint for portfolio analysis with database-first risk limits.
    
    Flow:
    1. Authenticate user and validate request
    2. Load portfolio data from database (PortfolioManager.load_portfolio_data)
3. Load user-specific risk limits from database (RiskLimitsManager.load_risk_limits)
       - Retrieves user-specific risk configuration
       - Handles fallbacks: database → file → defaults
       - Ensures user isolation (no global fallbacks)
    4. Execute analysis with user-specific risk limits (PortfolioService.analyze_portfolio)
       - Service expects valid RiskLimitsData (no fallbacks at service layer)
    5. Return analysis results
    
    Implementation Notes:
        - API layer orchestrates risk limits retrieval (RiskLimitsManager) and passes to service
        - Service layer expects valid risk limits, no fallbacks at service level
        - Multi-user safe with proper data isolation
    """
```

### **Phase 4: Testing and Validation**

#### 4.1 Test Database Integration
```bash
# Test the API route with database risk limits
python3 tests/utils/show_api_output.py analyze

# Verify it uses database risk limits
python3 tests/utils/show_api_output.py analyze | grep -E "(success|Using provided|risk_limits)"
```

#### 4.2 Test User Isolation
```bash
# Test with different users to ensure isolation
python3 tests/utils/show_db_data.py risk-limits --user-id 1
python3 tests/utils/show_db_data.py risk-limits --user-id 2
```

#### 4.3 Test Fallback Scenarios
- Test with user who has no database risk limits
- Test with database connection failure
- Verify graceful fallback to default file

### **Phase 5: Clean Up Legacy Code**

#### 5.1 Remove Hardcoded File References
```bash
# Find any remaining hardcoded references
grep -r "risk_limits.yaml" services/
grep -r "risk_file" services/
```

#### 5.2 Update Related Service Methods
Apply the same pattern to any other service methods that use risk limits:
- `analyze_performance()`
- `optimize_portfolio()`
- Any other methods with `risk_file` parameters

---

## Architecture Principles

### **Service Layer Responsibilities**
- ✅ **Stateless**: No user context, no database access
- ✅ **Expects Valid Data**: Requires `RiskLimitsData` objects
- ✅ **No Fallbacks**: Raises `ValueError` if invalid data provided
- ✅ **Type Safety**: Uses typed dataclasses throughout

### **API Layer Responsibilities**
- ✅ **Data Orchestration**: Coordinates data retrieval from multiple sources
- ✅ **User Context**: Manages user authentication and authorization
- ✅ **Fallback Logic**: Handles database failures gracefully
- ✅ **Error Handling**: Provides appropriate HTTP responses

### **RiskLimitsManager Responsibilities**
- ✅ **Database-First**: Primary source for risk limits
- ✅ **Fallback Chain**: database → file → built-in defaults
- ✅ **User Isolation**: Returns user-specific configurations
- ✅ **Type Conversion**: Returns `RiskLimitsData` objects

---

## Success Criteria

### ✅ **Functional Requirements**
- [ ] API route loads risk limits from database for authenticated users
- [ ] Falls back gracefully when database fails or user has no limits
- [ ] Maintains backward compatibility with existing functionality
- [ ] All existing tests pass

### ✅ **Technical Requirements**
- [ ] Service layer is stateless and user-agnostic
- [ ] Proper separation of concerns between API/Service/Manager layers
- [ ] Type safety with `RiskLimitsData` objects throughout
- [ ] Multi-user cache isolation
- [ ] Consistent logging using established infrastructure

### ✅ **Quality Requirements**
- [ ] No hardcoded file paths in service layer
- [ ] Robust error handling and cleanup
- [ ] Comprehensive docstring updates
- [ ] Updated CLI-API alignment documentation

---

## Reference Implementation

See the completed `api_risk_score` refactor in:
- **API Layer**: `routes/api.py` (lines ~408-454)
- **Service Layer**: `services/portfolio_service.py` (`analyze_risk_score` method)
- **Data Objects**: `core/data_objects.py` (`RiskLimitsData` class)
- **Risk Manager**: `inputs/risk_limits_manager.py` (`RiskLimitsManager` class)

---

## Next Steps After `/api/analyze` Refactor

1. **Apply Same Pattern to Other Routes**:
   - `/api/optimize` 
   - `/api/scenario`
   - Any other routes using `risk_limits.yaml`

2. **RiskLimitsManager usage**:
   - Ensure all methods are updated to use `RiskLimitsData`
   - Ensure all dependencies import and use `RiskLimitsManager`

3. **Remove Legacy Files**:
   - Phase out hardcoded `risk_limits.yaml` references
   - Clean up unused fallback code

This architecture provides a solid foundation for scalable, multi-user risk management across all API endpoints.
