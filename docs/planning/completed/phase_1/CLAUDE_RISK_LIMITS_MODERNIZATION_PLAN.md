# Claude Function Executor - Risk Limits Modernization Plan

## Overview
Several Claude functions in `services/claude/function_executor.py` still use the old file-based risk limits pattern instead of the modern `RiskLimitsManager` approach. This document identifies the functions that need updating and provides a plan for modernization.

## Current State Analysis

### ✅ Already Modernized Functions
These functions correctly use `RiskLimitsManager`:
- `_execute_view_risk_limits()` (line 1278)
- `_execute_update_risk_limits()` (line 1342) 
- `_execute_reset_risk_limits()` (line 1400)

### ❌ Functions Needing Updates

#### 1. `_execute_risk_score()` (lines 315-371)
**Current Issue:**
```python
# Line 315-316: Accepts risk_file parameter
- risk_file (str, optional): Path to risk limits YAML file.
  Defaults to "risk_limits.yaml"

# Line 337: Gets risk file from parameters
risk_file = parameters.get("risk_file", "risk_limits.yaml")

# Line 371: Passes file path to service
result = self.portfolio_service.analyze_risk_score(portfolio_data, risk_file)
```

**Problem:** 
- Uses file path instead of `RiskLimitsData` object
- `PortfolioService.analyze_risk_score()` expects `RiskLimitsData`, not file path
- Not user-specific (uses global risk_limits.yaml)

#### 2. `_execute_create_scenario()` (lines 946-1002)
**Current Issue:**
```python
# Line 948: Creates risk limits YAML file
risk_file = create_risk_limits_yaml(custom_risk_limits, f"{user_prefix}{scenario_name}")

# Lines 963-977: Complex file backup/restore logic
if risk_file:
    backup_file = f"{user_prefix}risk_limits_backup.yaml"
    if os.path.exists("risk_limits.yaml"):
        shutil.copy("risk_limits.yaml", backup_file)
    shutil.copy(risk_file, "risk_limits.yaml")
    # ... run analysis ...
    # ... restore backup ...
```

**Problems:**
- Creates temporary YAML files instead of using data objects
- Complex file backup/restore logic prone to errors
- File system manipulation during analysis
- Not using user-specific risk limits database

#### 3. Import Dependencies (line 48)
**Current Issue:**
```python
create_risk_limits_yaml,  # Line 48 - deprecated function import
```

**Problem:**
- Still imports deprecated `create_risk_limits_yaml` function

## Modernization Plan

### Phase 1: Update `_execute_risk_score()`

#### Before:
```python
def _execute_risk_score(self, parameters):
    risk_file = parameters.get("risk_file", "risk_limits.yaml")
    result = self.portfolio_service.analyze_risk_score(portfolio_data, risk_file)
```

#### After:
```python
def _execute_risk_score(self, parameters):
    # Remove risk_file parameter from docstring
    # Use RiskLimitsManager for user-specific risk limits
    from inputs.risk_limits_manager import RiskLimitsManager
    risk_manager = RiskLimitsManager(use_database=True, user_id=self.user['user_id'])
    
    portfolio_name = parameters.get("portfolio_name") or self.active_portfolio_name
    risk_limits_data = risk_manager.load_risk_limits(portfolio_name)
    
    result = self.portfolio_service.analyze_risk_score(portfolio_data, risk_limits_data)
```

**Benefits:**
- User-specific risk limits from database
- Consistent with other Claude functions
- Matches service layer expectations
- No file system dependencies

### Phase 2: Update `_execute_create_scenario()`

#### Before:
```python
def _execute_create_scenario(self, parameters):
    # Complex file creation and backup logic
    risk_file = None
    if custom_risk_limits:
        risk_file = create_risk_limits_yaml(custom_risk_limits, f"{user_prefix}{scenario_name}")
    
    # File backup/restore during analysis
    if risk_file:
        backup_file = f"{user_prefix}risk_limits_backup.yaml"
        # ... complex file manipulation ...
```

#### After:
```python
def _execute_create_scenario(self, parameters):
    # Use RiskLimitsManager for clean risk limits handling
    from inputs.risk_limits_manager import RiskLimitsManager
    risk_manager = RiskLimitsManager(use_database=True, user_id=self.user['user_id'])
    
    # Handle custom risk limits via data objects, not files
    if custom_risk_limits:
        # Create RiskLimitsData object from custom limits
        from core.data_objects import RiskLimitsData
        custom_risk_data = RiskLimitsData.from_dict(custom_risk_limits, name=f"Custom_{scenario_name}")
        
        # Use temporary risk limits for this scenario
        # (Implementation depends on how PortfolioService should handle custom limits)
        # Could pass custom_risk_data directly to analysis functions
    else:
        # Use user's default risk limits
        portfolio_name = self.active_portfolio_name or "CURRENT_PORTFOLIO"
        risk_limits_data = risk_manager.load_risk_limits(portfolio_name)
    
    # No file manipulation needed - work with data objects
```

**Benefits:**
- Eliminates complex file backup/restore logic
- No temporary file creation/cleanup
- Uses data objects throughout
- More robust and maintainable

### Phase 3: Clean Up Imports

#### Before:
```python
from inputs import (
    create_what_if_yaml,
    create_portfolio_yaml,
    view_current_risk_limits,
    update_risk_limits,
    reset_risk_limits,
    create_risk_limits_yaml,  # ← Remove this
    # ... other imports
)
```

#### After:
```python
from inputs import (
    create_what_if_yaml,
    create_portfolio_yaml,
    view_current_risk_limits,
    update_risk_limits,
    reset_risk_limits,
    # create_risk_limits_yaml removed - no longer needed
    # ... other imports
)
```

## Implementation Steps

### Step 1: Validate Service Layer Compatibility
- Confirm `PortfolioService.analyze_risk_score()` expects `RiskLimitsData` object
- Verify how custom risk limits should be handled in scenario creation
- Test user-specific risk limits loading

### Step 2: Update `_execute_risk_score()`
- Remove `risk_file` parameter from function signature and docstring
- Implement `RiskLimitsManager` pattern
- Test with Claude AI integration

### Step 3: Update `_execute_create_scenario()`
- Replace file-based risk limits with data objects
- Simplify scenario creation logic
- Remove file backup/restore complexity
- Test scenario creation with custom risk limits

### Step 4: Clean Up Dependencies
- Remove `create_risk_limits_yaml` import
- Update any remaining references to deprecated functions

### Step 5: Integration Testing
- Test all Claude functions that use risk limits
- Verify user-specific risk limits work correctly
- Ensure no breaking changes to Claude AI responses

## Expected Outcomes

### Benefits
- ✅ **Consistency**: All Claude functions use `RiskLimitsManager`
- ✅ **User-Specific**: Risk limits are per-user from database
- ✅ **Maintainability**: Eliminates complex file manipulation logic
- ✅ **Robustness**: No temporary file creation/cleanup issues
- ✅ **Modern Architecture**: Uses data objects throughout

### Risk Mitigation
- **Backward Compatibility**: Ensure Claude AI responses remain unchanged
- **Error Handling**: Proper fallbacks if risk limits loading fails
- **Testing**: Comprehensive testing of all affected Claude functions

## Notes
- This modernization aligns Claude's risk limits handling with the rest of the system
- The changes are internal to the function executor and shouldn't affect Claude AI responses
- This complements the recent Result Objects refactoring by completing the data objects modernization
