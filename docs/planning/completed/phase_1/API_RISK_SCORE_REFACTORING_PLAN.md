# API Risk Score Refactoring Plan: Implementation Guide

## Executive Summary

This document provides a **phase-by-phase implementation plan** for refactoring the `api_risk_score` flow to use Result Objects, following the architecture and implementation described in `RESULT_OBJECTS_ARCHITECTURE.md`.

**🔒 CRITICAL CONSTRAINTS:**
- **ZERO FUNCTIONAL CHANGES** - All CLI outputs must remain identical
- **ZERO DATA LOSS** - Every field, metric, and calculation preserved exactly
- **ZERO BREAKING CHANGES** - All existing APIs maintain backward compatibility
- **PURE REFACTORING** - Only internal architecture changes, no user-visible changes

## Current Architecture Analysis

### Current Flow Components
```
API Route (routes/api.py::api_risk_score)
    ↓
Service Layer (services/portfolio_service.py::PortfolioService.analyze_risk_score)  
    ↓
Core Function (portfolio_risk_score.py::run_risk_score_analysis)
    ↓
Result Object (core/result_objects.py::RiskScoreResult)
```

### Current Implementation Status
- **Core function**: `portfolio_risk_score.py::run_risk_score_analysis(...)` - Lines 1328-1571
- **Service method**: `services/portfolio_service.py::PortfolioService.analyze_risk_score(...)` - Lines 366-466
- **CLI wrapper**: No dedicated dual-mode wrapper yet (will be created in Phase 3)
- **API route**: `routes/api.py::api_risk_score()` - Lines 327-495
- **Target ResultObject**: `core/result_objects.py::RiskScoreResult` - Line 2397+

## Phase-by-Phase Implementation Plan

### Phase 1A: Enhanced Result Objects (Week 1)

#### 1.1 Add CLI Formatting to RiskScoreResult
**File:** `core/result_objects.py` (around line 2397)
**Target:** Replace current dual-mode duplication with result object methods
**🔒 CONSTRAINT:** CLI output must be IDENTICAL to current `portfolio_risk_score.py` output

**Files & Line Ranges to Change:**
- `core/result_objects.py:2397+` - Add `to_cli_report()` method to `RiskScoreResult` class

**New Builder Method Names:**
- `RiskScoreResult.to_cli_report()` - Generate complete CLI formatted report

**Which Prints Move to to_cli_report():**
- Lines 1503-1556 from `portfolio_risk_score.py::run_risk_score_analysis()` (CLI display logic)
- `display_portfolio_risk_score()` function calls - Lines 1504, 1268
- `display_suggested_risk_limits()` function calls - Lines 1556, 1315  
- Detailed risk limits analysis display - Lines 1511-1553

**Implementation:**
```python
class RiskScoreResult:
    def to_cli_report(self) -> str:
        """Generate complete CLI formatted report - IDENTICAL to current output"""
        sections = []
        sections.append(self._format_risk_score_display())
        sections.append(self._format_detailed_risk_analysis())
        sections.append(self._format_suggested_risk_limits())
        return "\n\n".join(sections)
    
    def _format_risk_score_display(self) -> str:
        """Format risk score display - EXACT copy of display_portfolio_risk_score()"""
        # CRITICAL: Must produce identical output to current implementation
        # Copy exact formatting logic from portfolio_risk_score.py:1064-1216
        
    def _format_detailed_risk_analysis(self) -> str:
        """Format detailed risk limits analysis - EXACT copy of lines 1511-1553"""
        # CRITICAL: Must produce identical output to current implementation
        
    def _format_suggested_risk_limits(self) -> str:
        """Format suggested limits - EXACT copy of display_suggested_risk_limits()"""
        # CRITICAL: Must produce identical output to current implementation
```

**Validation Commands:**
```bash
# Before changes - capture baseline
python portfolio_risk_score.py > baseline_cli_output.txt

# After changes - verify identical output  
python portfolio_risk_score.py > new_cli_output.txt
diff baseline_cli_output.txt new_cli_output.txt
# Must show zero differences
```

#### 1.2 Create Core-Layer Builder Method  
**File:** `core/result_objects.py` (before updating run_risk_score_analysis())
**Target:** Add `from_risk_score_analysis()` method to replace current usage

**🔒 CRITICAL API RESPONSE GUARANTEE:**
The existing `RiskScoreResult.to_api_response()` method is designed to preserve API responses exactly. The new builder method must populate the same fields that `to_api_response()` expects.

**Implementation:**
```python
class RiskScoreResult:
    @classmethod  
    def from_risk_score_analysis(cls, 
                               risk_score: Dict[str, Any],
                               limits_analysis: Dict[str, Any], 
                               portfolio_analysis: Dict[str, Any],
                               suggested_limits: Dict[str, Any],
                               analysis_metadata: Dict[str, Any]) -> 'RiskScoreResult':
        """
        🔒 CRITICAL: This must preserve exact same field mappings as current usage
        AND ensure to_api_response() produces identical output to current API responses.
        """
        return cls(
            risk_score=risk_score,
            limits_analysis=limits_analysis,
            portfolio_analysis=portfolio_analysis,
            suggested_limits=suggested_limits,
            analysis_metadata=analysis_metadata,
            analysis_date=datetime.now(UTC),
            portfolio_name=analysis_metadata.get("portfolio_name", "portfolio")
        )
```

#### 1.3 Update run_risk_score_analysis() to Return Result Objects
**File:** `portfolio_risk_score.py`  
**Current:** Lines 1488-1500 return Dict[str, Any]
**Target:** Return RiskScoreResult directly
**🔒 CRITICAL**: Must update all imports and callers simultaneously

**Files & Line Ranges to Change:**
- `portfolio_risk_score.py:1488-1500` - Change return statement to create and return RiskScoreResult
- `portfolio_risk_score.py:1559-1564` - Update final return for CLI mode

**Implementation:**
```python
# BEFORE (lines 1488-1500)
return make_json_safe({
    "risk_score": risk_score,
    "limits_analysis": limits_analysis,
    "portfolio_analysis": summary,
    "suggested_limits": suggestions,
    "analysis_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
    "portfolio_file": portfolio_yaml,
    "risk_limits_file": risk_yaml,
    "formatted_report": _format_risk_score_output(risk_score, limits_analysis, suggestions, max_loss)
})

# AFTER - Core function builds result object using new builder
result = RiskScoreResult.from_risk_score_analysis(
    risk_score=risk_score,
    limits_analysis=limits_analysis,
    portfolio_analysis=summary,
    suggested_limits=suggestions,
    analysis_metadata={
        "analysis_date": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "portfolio_file": portfolio_yaml,
        "risk_limits_file": risk_yaml,
        "portfolio_name": os.path.basename(portfolio_yaml).replace('.yaml', '')
    }
)

if return_data:
    return result.to_api_response()
else:
    print(result.to_cli_report())
    return result  # For programmatic access
```

**Required Import Updates:**
```python
# File: portfolio_risk_score.py - Add import
from core.result_objects import RiskScoreResult
```

#### 1.4 Simplify run_risk_score_analysis() Dual-Mode Logic
**File:** `portfolio_risk_score.py`
**Current:** Lines 1501-1556 (~55 lines of dual-mode complexity)  
**Target:** ~10 lines of simple dispatching

**Files & Line Ranges to Change:**
- `portfolio_risk_score.py:1501-1556` - Replace complex CLI display logic with simple result.to_cli_report()

**Implementation:**
```python
# BEFORE: Lines 1501-1556 (55 lines of complex dual-mode logic)
else:
    # CLI mode - print formatted output
    display_portfolio_risk_score(risk_score)
    
    print("\n" + "═" * 80)
    print("📋 DETAILED RISK LIMITS ANALYSIS")
    print("═" * 80)
    
    # ... 40+ lines of display logic ...
    
    display_suggested_risk_limits(suggestions, max_loss)

# AFTER: ~5 lines of simple dispatching  
else:
    # CLI mode - print formatted output
    print(result.to_cli_report())
```

**Validation Commands:**
```bash
# Test both CLI and API modes produce identical output to baseline
python portfolio_risk_score.py  # CLI mode
python -c "from portfolio_risk_score import run_risk_score_analysis; print(run_risk_score_analysis(return_data=True))"  # API mode
```

### Phase 1B: Service Layer Updates (Week 2)

#### 1B.1 Update Portfolio Service  
**File:** `services/portfolio_service.py`
**Target:** Lines 435-442 - Update to work with new result object return

**Files & Line Ranges to Change:**
- `services/portfolio_service.py:435-442` - Update service method to handle RiskScoreResult return
- `services/portfolio_service.py:418-419` - Update core function call

**Implementation:**
```python
# BEFORE: Lines 418-419  
risk_analysis_result = run_risk_score_analysis(temp_portfolio_file, effective_risk_file, return_data=True)

# AFTER: Direct result object usage
result = run_risk_score_analysis(temp_portfolio_file, effective_risk_file, return_data=True)  # Returns RiskScoreResult directly

# Update lines 435-442
if result is None:
    # Handle analysis failure - return a default result
    result = RiskScoreResult(
        risk_score={"score": 0, "category": "Analysis Failed", "component_scores": {}},
        limits_analysis={"risk_factors": ["Analysis failed"], "recommendations": [], "limit_violations": {}},
        portfolio_analysis={},
        analysis_date=datetime.now(UTC),
        portfolio_name=portfolio_data.portfolio_name
    )

# Remove old conversion logic (lines 435-442)
# Service now returns RiskScoreResult directly
return result
```

#### 1B.2 Update API Routes 
**File:** `routes/api.py`
**Target:** Lines 446-474 - Direct result object usage while preserving exact API response structure

**Files & Line Ranges to Change:**
- `routes/api.py:446` - Update service call handling
- `routes/api.py:452` - Remove redundant result.to_api_response() call
- `routes/api.py:458` - Update API response construction

**Implementation:**
```python
# BEFORE: Lines 446-452
result = portfolio_service.analyze_risk_score(portfolio_data, risk_limits_data)
# ... exception handling ...  
result_dict = result.to_api_response()

# AFTER: Service returns result object, API converts once
result = portfolio_service.analyze_risk_score(portfolio_data, risk_limits_data)  # Returns RiskScoreResult

# BEFORE: Lines 458-474  
api_response = result.to_api_response()

# AFTER: Use result object directly (no double conversion)
api_response = result.to_api_response()  # Single conversion to dict

# 🔒 CRITICAL: API response must be character-identical to before refactor
```

**API Contract Validation Required:**
- Capture baseline API responses before refactor
- Verify identical JSON structure after refactor  
- Test POST /api/risk-score endpoint
- Validate nested field structures preserved

**Validation Commands:**
```bash
# Test API endpoint produces identical response to baseline
cd tests/utils && python show_api_output.py risk-score portfolio.yaml
# Compare JSON output to baseline - must be identical
```

### Phase 2: CLI Wrapper Creation (Week 2-3)

#### 2.1 Create Dedicated CLI Wrapper Function
**File:** `run_risk.py`
**Target:** Add `run_risk_score(...)` function with dual-mode pattern
**Impact:** Provides consistent interface matching other CLI functions

**Files & Line Ranges to Change:**
- `run_risk.py` - Add new function `run_risk_score()` (new lines at end of file)

**New Builder Method Names:**
- `run_risk_score(portfolio_yaml, risk_yaml, *, return_data=False)` - CLI wrapper with dual-mode

**Implementation:**
```python
def run_risk_score(portfolio_yaml: str = "portfolio.yaml", risk_yaml: str = "risk_limits.yaml", *, return_data: bool = False):
    """
    CLI wrapper for portfolio risk score analysis with dual-mode support.
    
    Args:
        portfolio_yaml: Path to portfolio configuration file
        risk_yaml: Path to risk limits configuration file  
        return_data: If True, return data instead of printing
        
    Returns:
        RiskScoreResult when return_data=True, None when printing
    """
    result = run_risk_score_analysis(portfolio_yaml, risk_yaml, return_data=True)
    
    if return_data:
        return result
    else:
        print(result.to_cli_report())
        return None
```

### Phase 3: Validation and Testing (Week 3)

#### 3.1 Comprehensive Testing Strategy
**Testing using existing tools from RESULT_OBJECTS_ARCHITECTURE.md:**

**Files to Test:**
- `portfolio.yaml` - Standard test portfolio
- `what_if_portfolio.yaml` - Alternative test case
- Any other portfolio files in test directory

**Validation Commands:**
```bash
# 1. COMPREHENSIVE validation using existing tools
python scripts/collect_all_schemas.py
cp -r docs/schema_samples docs/risk_score_baseline

# 2. Test CLI output preservation
python portfolio_risk_score.py > baseline_cli.txt
# After refactor:
python portfolio_risk_score.py > new_cli.txt  
diff baseline_cli.txt new_cli.txt  # Must be identical

# 3. Test API response preservation  
cd tests/utils && python show_api_output.py risk-score portfolio.yaml > baseline_api.json
# After refactor:
cd tests/utils && python show_api_output.py risk-score portfolio.yaml > new_api.json
diff baseline_api.json new_api.json  # Must be identical

# 4. Test dual-mode consistency
python -c "
from portfolio_risk_score import run_risk_score_analysis
result = run_risk_score_analysis('portfolio.yaml', return_data=True)
print('API Response Keys:', list(result.to_api_response().keys()))
print('CLI Report Length:', len(result.to_cli_report()))
"
```

#### 3.2 Performance Validation
**No performance regression expected** - Result objects should be faster by eliminating data conversion overhead.

**Validation:**
```bash
# Measure before/after performance 
time python portfolio_risk_score.py
# Should be same or faster after refactor
```

## Implementation Timeline

### Week 1: Foundation (Phase 1A) 
- **Day 1-2**: Add CLI formatting to RiskScoreResult (`to_cli_report()` method)
- **Day 3-4**: Create core-layer builder method (`from_risk_score_analysis()`)  
- **Day 5**: Update `run_risk_score_analysis()` return type and test in isolation
- **Day 6-7**: Simplify dual-mode logic and end-to-end testing

### Week 2: Service Integration (Phase 1B)
- **Day 1-2**: Update service layer to use direct result objects
- **Day 3-4**: Update API routes and test consistency  
- **Day 5**: Create CLI wrapper function in `run_risk.py`

### Week 3: Validation (Phase 3)
- **Day 1-3**: Comprehensive testing using existing validation tools
- **Day 4-5**: Performance testing and final bug fixes

## Success Metrics

### Technical Metrics
- **CLI output preservation**: 100% character-identical to baseline
- **API response preservation**: 100% field-identical to baseline  
- **Lines of code reduction**: ~50 lines reduced in dual-mode logic
- **Performance**: Same or better execution time

### Developer Experience  
- **Consistent interface**: CLI and API use same underlying result objects
- **Easier maintenance**: Single source of formatting logic
- **Better testing**: Test business logic in isolation from display logic

## Critical Success Factors

### 🔒 Zero Functional Change Validation
1. **Character-by-character CLI validation**: Every print statement must be identical
2. **Field-by-field API validation**: Every JSON key/value must be preserved  
3. **Baseline capture**: Save current outputs before any changes
4. **Incremental validation**: Test after every single change

### Risk Mitigation
- **Rollback plan**: Maintain working backup at each phase
- **Atomic updates**: Complete each phase fully before starting next
- **Existing tool usage**: Leverage `scripts/collect_all_schemas.py` and `tests/utils/show_api_output.py`

## Ready-to-Implement File Targets

### Phase 1A Priority Files:
1. `core/result_objects.py:2397+` - Add `to_cli_report()` to `RiskScoreResult`
2. `portfolio_risk_score.py:1488-1500` - Return `RiskScoreResult` directly  
3. `portfolio_risk_score.py:1501-1556` - Replace 55 lines with ~5 lines of dispatching

### Phase 1B Priority Files:
1. `services/portfolio_service.py:435-442` - Update service method
2. `routes/api.py:446-474` - Update API endpoint to use direct result objects

### Phase 2 Files:
1. `run_risk.py` - Add `run_risk_score()` CLI wrapper function

This refactoring follows the exact same successful pattern used for the portfolio analysis endpoint, ensuring a proven approach for consistent and reliable implementation.