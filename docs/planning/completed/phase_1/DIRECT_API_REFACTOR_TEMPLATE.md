# Direct API Refactor Template

## Overview

This document serves as a template for refactoring direct API endpoints to use Result Objects as the single source of truth. It's based on the successful refactor of `api_direct_what_if` and establishes architectural patterns and implementation guidelines for future similar refactors.

## Architecture Principles

### 1. Layered Architecture with Clear Separation

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Direct API    │    │  Service Layer  │    │  Core Business  │
│   Endpoints     │    │   Endpoints     │    │     Logic       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       │
         v                       v                       │
┌─────────────────┐    ┌─────────────────┐              │
│   run_what_if   │    │ ScenarioService │              │
│   (CLI Entry)   │    │   (Caching)     │              │
└─────────────────┘    └─────────────────┘              │
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
                                 v
                      ┌─────────────────┐
                      │ analyze_scenario│
                      │ (Core Function) │
                      └─────────────────┘
```

### 2. Direct vs Service-Based Endpoints

**Direct API Endpoints:**
- Call core functions directly (`run_what_if`, `analyze_scenario`)
- Minimal abstraction layers
- Optimized for performance and simplicity
- Example: `api_direct_what_if`

**Service-Based API Endpoints:**
- Go through service layer (`ScenarioService`, `PortfolioService`)
- Include caching, validation, and business logic
- More complex workflows
- Example: Standard portfolio analysis endpoints

### 3. Result Objects as Single Source of Truth

All business logic functions should return structured Result Objects that:
- Contain all analysis data
- Provide consistent serialization methods
- Support both CLI and API output formats
- Eliminate duplicate data structures

## Implementation Pattern

### Step 1: Core Function Refactor

**Before:**
```python
def analyze_scenario(filepath, scenario_yaml=None, delta=None):
    # ... business logic ...
    return (portfolio_view, scenario_view, risk_comparison, factor_comparison, formatted_report)
```

**After:**
```python
def analyze_scenario(filepath, risk_limits_yaml, scenario_yaml=None, delta=None):
    # ... business logic ...
    return WhatIfResult.from_core_scenario(
        scenario_result={
            'portfolio_view': portfolio_view,
            'scenario_view': scenario_view,
            'risk_comparison': risk_comparison,
            'factor_comparison': factor_comparison
        },
        scenario_name=scenario_name
    )
```

**Key Changes:**
1. Return Result Object instead of tuple
2. Remove hardcoded file paths, make them parameters
3. Ensure consistent parameter ordering

### Step 2: CLI Function Update

**Before:**
```python
def run_what_if(filepath, scenario_yaml=None, delta=None, return_data=False):
    if return_data:
        # Return tuple for API
        return (portfolio_view, scenario_view, risk_comparison, factor_comparison, formatted_report)
    else:
        # Print for CLI
        print(formatted_report)
```

**After:**
```python
def run_what_if(filepath, scenario_yaml=None, delta=None, return_data=False, risk_limits_yaml="risk_limits.yaml"):
    result = analyze_scenario(filepath, risk_limits_yaml, scenario_yaml, delta)
    
    if return_data:
        # Return API response format
        return result.to_api_response()
    else:
        # Print CLI format
        print(result.to_cli_report())
```

**Key Changes:**
1. Single call to core function
2. Result Object handles both CLI and API formatting
3. Eliminate dual-mode complexity

### Step 3: Direct API Endpoint

**Before:**
```python
@app.route('/api/direct/what-if', methods=['POST'])
def api_direct_what_if():
    # ... setup temp files ...
    
    # Call service layer
    scenario_service = ScenarioService()
    result = scenario_service.analyze_delta_scenario(...)
    
    return jsonify({
        'success': True,
        'data': result.to_api_response(),
        'summary': result.get_summary()
    })
```

**After:**
```python
@app.route('/api/direct/what-if', methods=['POST'])
def api_direct_what_if():
    # ... setup temp files ...
    
    # Call run_what_if directly for "direct" endpoint
    result_data = run_what_if(
        filepath=temp_portfolio_yaml,
        scenario_yaml=temp_scenario_yaml_path,
        delta=delta_string,
        return_data=True,
        risk_limits_yaml=temp_risk_yaml
    )
    
    return jsonify({
        'success': True,
        'data': result_data,  # Already in correct format
        'summary': f"Analysis completed with {len(result_data.get('deltas', []))} changes"
    })
```

**Key Changes:**
1. Direct call to `run_what_if()` instead of service layer
2. No wrapper classes or unnecessary abstractions
3. Data already in correct API format

## Result Object Design Pattern

### Core Structure

```python
@dataclass
class WhatIfResult:
    scenario_name: str
    deltas: List[Dict]
    position_changes: Dict
    # ... other fields ...
    
    def to_cli_report(self) -> str:
        """Generate human-readable CLI output"""
        # Format for terminal display
        
    def to_api_response(self) -> Dict[str, Any]:
        """Generate API response format"""
        # Structure for JSON API
        
    @classmethod
    def from_core_scenario(cls, scenario_result: Dict, scenario_name: str):
        """Build from core analysis output"""
        # Factory method for consistent construction
```

### Key Methods

1. **`to_cli_report()`**: Human-readable format for CLI
2. **`to_api_response()`**: Structured format for API
3. **`from_core_scenario()`**: Factory method for construction
4. **`get_summary()`**: Brief description for logging/API

## Parameter Flow Pattern

### File Path Parameterization

**Problem:** Hardcoded file paths throughout the call chain
```python
def analyze_scenario():
    with open("risk_limits.yaml", "r") as f:  # Hardcoded!
```

**Solution:** Parameter flow from API to core
```python
# API Level
temp_risk_yaml = create_temp_file(risk_limits_data)

# CLI Level  
run_what_if(filepath, risk_limits_yaml="risk_limits.yaml")

# Core Level
def analyze_scenario(filepath, risk_limits_yaml, ...):
    with open(risk_limits_yaml, "r") as f:  # Parameterized!
```

### Parameter Ordering

**Required parameters first, optional parameters last:**
```python
def analyze_scenario(
    filepath: str,                    # Required
    risk_limits_yaml: str,           # Required  
    scenario_yaml: Optional[str] = None,  # Optional
    delta: Optional[str] = None      # Optional
):
```

## Testing and Validation

### Schema Collection Test

```bash
python3 scripts/collect_all_schemas.py | grep -E "direct/what-if|Overall:"
```

**Success Criteria:**
- API endpoint returns 200 status
- Schema is collected successfully
- Response format matches expected structure

### CLI Test

```bash
python3 run_risk.py --whatif --portfolio portfolio.yaml --delta "AAPL:+100bp"
```

**Success Criteria:**
- CLI output displays correctly
- No errors in execution
- Consistent results with API

### Integration Test

```bash
# Test both modes return consistent data
python3 -c "
from run_risk import run_what_if
cli_result = run_what_if('portfolio.yaml', delta='AAPL:+100bp', return_data=False)
api_result = run_what_if('portfolio.yaml', delta='AAPL:+100bp', return_data=True)
print('CLI executed successfully')
print('API data keys:', list(api_result.keys()))
"
```

## Common Pitfalls and Solutions

### 1. Return Type Mismatches

**Problem:** Function returns different types in different modes
```python
def run_what_if(..., return_data=False):
    if return_data:
        return some_dict  # Dict
    else:
        return None       # None
```

**Solution:** Update type annotations to reflect reality
```python
def run_what_if(..., return_data=False) -> Union[None, Dict[str, Any]]:
```

### 2. Hardcoded File Paths

**Problem:** Files hardcoded deep in call chain
```python
def deep_function():
    with open("hardcoded.yaml") as f:  # Bad!
```

**Solution:** Parameter flow from entry points
```python
def entry_point(config_file="default.yaml"):
    return deep_function(config_file)

def deep_function(config_file):
    with open(config_file) as f:  # Good!
```

### 3. Duplicate Data Conversion

**Problem:** Multiple places converting same data
```python
# In API
result_dict = convert_to_dict(result)

# In Service  
api_data = result.to_api_format()

# In Core
formatted = format_for_api(data)
```

**Solution:** Single conversion method in Result Object
```python
class WhatIfResult:
    def to_api_response(self) -> Dict[str, Any]:
        # Single source of truth for API format
```

### 4. Unnecessary Wrapper Classes

**Problem:** Creating wrapper classes for simple data
```python
class APIWrapper:
    def __init__(self, data):
        self.data = data
    def to_api_response(self):
        return self.data
```

**Solution:** Use data directly if already in correct format
```python
# If run_what_if already returns API format, use it directly
result_data = run_what_if(..., return_data=True)
return jsonify({'data': result_data})
```

## Step-by-Step Implementation Phases

### Phase 1A: Core Layer Foundation
**Goal:** Establish Result Objects and update core business logic

**Steps:**
1. **Create/Update Result Object Class**
   ```bash
   # Edit core/result_objects.py
   # Add to_cli_report() method
   # Add to_api_response() method
   # Add from_core_scenario() factory method
   ```

2. **Update Core Business Function**
   ```bash
   # Edit core/scenario_analysis.py (or equivalent)
   # Change return type from tuple to Result Object
   # Add risk_limits_yaml parameter
   # Remove hardcoded file paths
   ```

3. **Validate Core Changes**
   ```bash
   python3 -c "
   from core.scenario_analysis import analyze_scenario
   result = analyze_scenario('portfolio.yaml', 'risk_limits.yaml', delta='AAPL:+100bp')
   print('Type:', type(result))
   print('Has to_cli_report:', hasattr(result, 'to_cli_report'))
   print('Has to_api_response:', hasattr(result, 'to_api_response'))
   "
   ```

**Success Criteria:**
- [ ] Core function returns Result Object
- [ ] Result Object has required methods
- [ ] No hardcoded file paths in core function
- [ ] All parameters flow correctly

### Phase 1B: CLI Layer Updates
**Goal:** Update CLI entry point to use Result Objects

**Steps:**
1. **Update CLI Function Signature**
   ```bash
   # Edit run_risk.py (or equivalent CLI file)
   # Add risk_limits_yaml parameter with default
   # Update return type annotation
   ```

2. **Simplify Dual-Mode Logic**
   ```bash
   # Replace complex if/else with single core call
   # Use Result Object methods for formatting
   ```

3. **Validate CLI Changes**
   ```bash
   # Test CLI mode
   python3 run_risk.py --whatif --portfolio portfolio.yaml --delta "AAPL:+100bp"
   
   # Test API mode
   python3 -c "
   from run_risk import run_what_if
   result = run_what_if('portfolio.yaml', delta='AAPL:+100bp', return_data=True)
   print('Keys:', list(result.keys()))
   "
   ```

**Success Criteria:**
- [ ] CLI output displays correctly
- [ ] API mode returns correct data structure
- [ ] Both modes use same core function
- [ ] No duplicate formatting logic

### Phase 1C: Engine Layer Parameter Flow
**Goal:** Remove hardcoded paths from engine functions

**Steps:**
1. **Update Engine Function Signatures**
   ```bash
   # Edit portfolio_optimizer.py (or equivalent engine file)
   # Add portfolio_yaml_path and risk_yaml_path parameters
   # Remove hardcoded defaults
   ```

2. **Fix Variable Naming**
   ```bash
   # Replace _ placeholders with actual variable names
   # Example: _, max_betas, _ = func() → max_betas, max_betas_by_proxy, historical_analysis = func()
   ```

3. **Validate Parameter Flow**
   ```bash
   python3 -c "
   from portfolio_optimizer import run_what_if_scenario
   import inspect
   sig = inspect.signature(run_what_if_scenario)
   print('Parameters:', list(sig.parameters.keys()))
   "
   ```

**Success Criteria:**
- [ ] No hardcoded file paths in engine functions
- [ ] All required parameters are explicit
- [ ] Variable names are meaningful
- [ ] Parameter flow is traceable

### Phase 2A: API Layer Refactor
**Goal:** Update API endpoint to use new architecture

**Steps:**
1. **Choose Architecture Pattern**
   ```bash
   # For direct endpoints: Call run_what_if() directly
   # For service endpoints: Use service layer
   ```

2. **Update API Endpoint**
   ```bash
   # Edit routes/api.py
   # Remove service layer calls (for direct endpoints)
   # Call run_what_if() directly
   # Pass temp file paths as parameters
   ```

3. **Simplify Response Handling**
   ```bash
   # Remove wrapper classes
   # Use data directly if already in API format
   # Update return statement
   ```

4. **Validate API Changes**
   ```bash
   python3 scripts/collect_all_schemas.py | grep -E "your-endpoint|Overall:"
   ```

**Success Criteria:**
- [ ] API endpoint returns 200 status
- [ ] Response format is correct
- [ ] No unnecessary wrapper classes
- [ ] Schema collection succeeds

### Phase 2B: Service Layer Updates (if applicable)
**Goal:** Update service layer for consistency

**Steps:**
1. **Update Service Methods**
   ```bash
   # Edit services/scenario_service.py
   # Add risk_limits_yaml parameter
   # Ensure consistent parameter passing
   ```

2. **Remove Redundant Conversions**
   ```bash
   # Remove _convert_to_what_if_result() methods
   # Use Result Objects directly
   ```

3. **Validate Service Changes**
   ```bash
   python3 -c "
   from services.scenario_service import ScenarioService
   service = ScenarioService()
   # Test service methods work correctly
   "
   ```

**Success Criteria:**
- [ ] Service methods accept new parameters
- [ ] No redundant data conversion
- [ ] Service layer works with Result Objects

### Phase 3: Integration Testing
**Goal:** Ensure all layers work together

**Steps:**
1. **End-to-End CLI Test**
   ```bash
   python3 run_risk.py --whatif --portfolio portfolio.yaml --delta "AAPL:+100bp" 2>/dev/null | tail -5
   ```

2. **End-to-End API Test**
   ```bash
   python3 scripts/collect_all_schemas.py | grep -E "your-endpoint|Overall:"
   ```

3. **Cross-Mode Consistency Test**
   ```bash
   python3 -c "
   from run_risk import run_what_if
   
   # Test CLI mode (should not error)
   run_what_if('portfolio.yaml', delta='AAPL:+100bp', return_data=False)
   print('CLI mode: OK')
   
   # Test API mode
   api_result = run_what_if('portfolio.yaml', delta='AAPL:+100bp', return_data=True)
   print('API mode keys:', list(api_result.keys()))
   "
   ```

4. **Linter Validation**
   ```bash
   # Check for any syntax errors
   python3 -m py_compile core/scenario_analysis.py
   python3 -m py_compile run_risk.py
   python3 -m py_compile routes/api.py
   ```

**Success Criteria:**
- [ ] CLI works without errors
- [ ] API returns correct responses
- [ ] Both modes return consistent data
- [ ] No linter errors

### Phase 4: Cleanup and Documentation
**Goal:** Remove deprecated code and update documentation

**Steps:**
1. **Remove Deprecated Methods**
   ```bash
   # Remove old factory methods (e.g., from_analyze_scenario_output)
   # Remove old formatting methods (e.g., to_formatted_report)
   # Remove temporary wrapper classes
   ```

2. **Update Type Annotations**
   ```bash
   # Fix return type annotations to match actual behavior
   # Add proper parameter type hints
   ```

3. **Update Documentation**
   ```bash
   # Update function docstrings
   # Update API endpoint documentation
   # Update inline comments
   ```

4. **Final Validation**
   ```bash
   python3 scripts/collect_all_schemas.py | grep "Overall:"
   ```

**Success Criteria:**
- [ ] No deprecated methods remain
- [ ] Type annotations are correct
- [ ] Documentation is updated
- [ ] All tests pass

## Phase Validation Commands

### Quick Health Check (run after each phase)
```bash
# Test core function
python3 -c "from core.scenario_analysis import analyze_scenario; print('Core: OK')"

# Test CLI function  
python3 -c "from run_risk import run_what_if; print('CLI: OK')"

# Test API endpoint (if applicable)
python3 scripts/collect_all_schemas.py | grep -E "your-endpoint|Overall:"
```

### Comprehensive Validation (run before moving to next phase)
```bash
# Test parameter flow
python3 -c "
from run_risk import run_what_if
result = run_what_if(
    filepath='portfolio.yaml',
    risk_limits_yaml='risk_limits.yaml', 
    delta='AAPL:+100bp',
    return_data=True
)
print('Parameter flow: OK')
print('Result keys:', list(result.keys()))
"

# Test both output modes
python3 run_risk.py --whatif --portfolio portfolio.yaml --delta "AAPL:+100bp" 2>/dev/null | tail -1
echo "CLI output: OK"
```

## Rollback Strategy

### If Phase 1A Fails
```bash
# Revert core function changes
git checkout HEAD -- core/scenario_analysis.py core/result_objects.py
```

### If Phase 1B Fails  
```bash
# Revert CLI changes, keep core changes
git checkout HEAD -- run_risk.py
```

### If Phase 2A Fails
```bash
# Revert API changes, keep CLI and core changes
git checkout HEAD -- routes/api.py
```

### Emergency Rollback
```bash
# Revert entire refactor
git checkout HEAD -- core/ run_risk.py routes/api.py services/
```

## Phase Success Metrics

| Phase | Success Metric | Validation Command |
|-------|---------------|-------------------|
| 1A | Core returns Result Object | `python3 -c "from core.scenario_analysis import analyze_scenario; print(type(analyze_scenario('portfolio.yaml', 'risk_limits.yaml')))"` |
| 1B | CLI works with Result Object | `python3 run_risk.py --whatif --portfolio portfolio.yaml --delta "AAPL:+100bp"` |
| 1C | No hardcoded paths | `grep -r "portfolio\.yaml\|risk_limits\.yaml" core/ portfolio_optimizer.py` |
| 2A | API endpoint works | `python3 scripts/collect_all_schemas.py \| grep your-endpoint` |
| 2B | Service layer consistent | Service-specific tests |
| 3 | Integration complete | All validation commands pass |
| 4 | Cleanup complete | No deprecated methods found |

## Refactor Checklist

### Pre-Refactor Analysis
- [ ] Identify current data flow and return types
- [ ] Map all hardcoded file paths
- [ ] Document existing API response format
- [ ] Identify duplicate data conversion logic

### Core Function Refactor
- [ ] Create/update Result Object class
- [ ] Add `to_cli_report()` method
- [ ] Add `to_api_response()` method  
- [ ] Add factory method (`from_core_scenario()`)
- [ ] Update core function to return Result Object
- [ ] Parameterize all hardcoded file paths
- [ ] Fix parameter ordering (required first)

### CLI Function Update
- [ ] Update to call core function once
- [ ] Use Result Object for both CLI and API output
- [ ] Update return type annotations
- [ ] Add new parameters with sensible defaults

### API Endpoint Refactor
- [ ] For direct endpoints: call CLI function directly
- [ ] For service endpoints: use service layer
- [ ] Remove unnecessary wrapper classes
- [ ] Update response format to use Result Object
- [ ] Pass all required parameters through chain

### Testing and Validation
- [ ] Run schema collection test
- [ ] Test CLI functionality
- [ ] Test API endpoint
- [ ] Verify parameter flow works correctly
- [ ] Check linter errors and fix
- [ ] Validate response format consistency

### Cleanup
- [ ] Remove deprecated methods
- [ ] Remove unused imports
- [ ] Remove temporary files/classes
- [ ] Update documentation
- [ ] Update type annotations

## Benefits of This Architecture

### 1. Single Source of Truth
- Result Objects contain all analysis data
- Eliminates duplicate data structures
- Consistent serialization across CLI and API

### 2. Clear Separation of Concerns
- Direct APIs → Direct calls to core functions
- Service APIs → Service layer with caching/validation
- Core functions → Pure business logic

### 3. Maintainability
- Changes to output format only need updates in Result Object
- Parameter flow is explicit and traceable
- No hardcoded dependencies

### 4. Testability
- Each layer can be tested independently
- Result Objects provide consistent test interfaces
- Parameter injection enables easy mocking

### 5. Performance
- Direct APIs avoid unnecessary abstraction layers
- Result Objects eliminate redundant data conversion
- Parameterized functions reduce file I/O overhead

## Future Considerations

### 1. Additional Direct Endpoints
This pattern can be applied to:
- `api_direct_portfolio_analysis`
- `api_direct_risk_check`  
- `api_direct_factor_analysis`

### 2. Result Object Extensions
- Add caching capabilities
- Include metadata (execution time, data sources)
- Support different output formats (CSV, Excel)

### 3. Parameter Validation
- Add parameter validation in Result Object constructors
- Include parameter schemas for API documentation
- Implement parameter type checking

This template provides a proven pattern for creating maintainable, performant direct API endpoints that serve as a single source of truth for analysis data.
