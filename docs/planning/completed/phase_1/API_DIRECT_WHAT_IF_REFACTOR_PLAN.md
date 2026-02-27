# API Direct What-If Refactoring Plan

## Executive Summary

This document outlines the phase-by-phase refactoring plan for the **api_direct_what_if** endpoint to adopt Result Objects architecture, following the proven patterns established in RESULT_OBJECTS_ARCHITECTURE.md.

**🔒 CRITICAL CONSTRAINTS:**
- **ZERO FUNCTIONAL CHANGES** - All CLI outputs must remain identical
- **ZERO DATA LOSS** - Every field, metric, and calculation preserved exactly
- **ZERO BREAKING CHANGES** - All existing APIs maintain backward compatibility
- **PURE REFACTORING** - Only internal architecture changes, no user-visible changes

## Current Architecture Analysis

### 📍 **Current Flow (Fragmented)**
```
analyze_scenario() → Raw Dicts → Factory Methods → WhatIfResult → Output Formatters
     ↑                  ↑            ↑               ↑                ↑
Business Logic    Structure 1   Structure 2   Structure 3    Multiple Views
```

**Problems:**
- **Three sources of truth** - raw dicts, result objects, and API responses can drift
- **Complex dual-mode logic** - 110+ lines of formatting code in `run_what_if()`
- **Manual field mapping** - error-prone factory methods like `from_analyze_scenario_output()`
- **Inconsistent outputs** - CLI and API can show different data

### ✅ **Target Architecture (Unified)**
```
analyze_scenario() → WhatIfResult → Output Adapters
     ↑                  ↑                ↓
Business Logic   Single Source    ┌─────┼─────┐
Functions        of Truth         ↓     ↓     ↓
                                API   CLI  Storage
```

**Benefits:**
- **Single source of truth** - all data flows through result objects
- **Guaranteed consistency** - CLI and API derive from same objects
- **Simple dual-mode** - ~10 lines instead of 110+
- **Easy maintenance** - add field once, works everywhere

## Architecture Mapping

### **Core Components**
- **Core function**: `core/scenario_analysis.py::analyze_scenario()` (lines 32-210)
- **Service method**: None (Direct API call)
- **CLI wrapper function**: `run_risk.py::run_what_if()` (lines 310-420)
- **API route path**: `/api/direct/what-if` (file: `routes/api.py`, lines 1045-1198)
- **Target ResultObject**: `WhatIfResult` (in `core/result_objects.py`, lines 1225-1580)

### **Current Data Flow Analysis**

#### **API Route Current Implementation** (`routes/api.py:1045-1198`)
1. **Input Processing** (lines 1095-1102): Creates PortfolioData object from inline JSON
2. **Temp File Creation** (lines 1108-1144): Converts to YAML files for legacy compatibility
3. **Core Function Call** (lines 1154-1159): Calls `run_what_if(return_data=True)`
4. **Result Wrapping** (lines 1172-1175): Uses `WhatIfResult.from_analyze_scenario_output()`
5. **Response Generation** (lines 1180-1186): Calls `result_obj.to_api_response()`

#### **Core Function Current Implementation** (`core/scenario_analysis.py:32-210`)
- **Input**: filepath, scenario_yaml, delta string
- **Output**: Dict with raw_tables, scenario_summary, risk_analysis, etc.
- **Business Logic**: Complete scenario analysis with comparison tables

#### **CLI Wrapper Current Implementation** (`run_risk.py:310-420`)
- **Dual-Mode Logic**: Different output based on return_data flag
- **CLI Mode**: Calls print_what_if_report() with extracted tables
- **API Mode**: Returns dict with formatted_report added

## Detailed Phase-by-Phase Implementation Plan

### **Phase 1A: Enhanced WhatIfResult Object (Week 1)**

#### **1A.1 Add CLI Formatting to WhatIfResult**
**File:** `core/result_objects.py` (around line 1580)
**Target:** Add `to_cli_report()` method to replace current dual-mode complexity
**🔒 CONSTRAINT:** CLI output must be IDENTICAL to current `run_what_if()` output

**Implementation:**
```python
class WhatIfResult:
    def to_cli_report(self) -> str:
        """Generate complete CLI formatted report - IDENTICAL to current output"""
        # If we have stored formatted report from print_what_if_report, use it
        if hasattr(self, '_formatted_report') and self._formatted_report:
            return self._formatted_report
            
        # Otherwise generate equivalent report sections
        sections = []
        sections.append(self._format_scenario_header())
        sections.append(self._format_position_changes())
        sections.append(self._format_new_portfolio_risk_checks())
        sections.append(self._format_new_portfolio_factor_checks())
        sections.append(self._format_risk_comparison())
        sections.append(self._format_factor_comparison())
        return "\n\n".join(sections)
    
    def _format_scenario_header(self) -> str:
        """Format scenario header - EXACT copy of print_what_if_report logic"""
        return f"=== What-If Scenario Analysis: {self.scenario_name} ==="
    
    def _format_position_changes(self) -> str:
        """Format position changes table - EXACT copy of CLI output"""
        # Extract from stored metadata and format identically
        lines = ["=== Portfolio Weights — Before vs After ==="]
        position_changes = self.get_position_changes_table()
        for change in position_changes:
            lines.append(f"{change['position']:<10} {change['before']} → {change['after']} {change['change']}")
        return "\n".join(lines)
    
    # Additional formatting methods for each section...
```

**Validation Commands:**
```bash
# Test CLI output identity
python run_risk.py --what-if portfolio.yaml scenario.yaml > baseline_cli.txt
# After implementation: 
result = analyze_scenario('portfolio.yaml', 'scenario.yaml')
whatif_result = WhatIfResult.from_core_scenario(result)
new_cli = whatif_result.to_cli_report()
# Compare: must be character-identical
```

#### **1A.2 Create Core-Layer Builder Method**
**File:** `core/result_objects.py` (before updating analyze_scenario())
**Target:** Add `from_core_scenario()` method to replace factory method

**🔒 CRITICAL API RESPONSE GUARANTEE:**
The existing `WhatIfResult.to_api_response()` method must produce identical JSON to current API responses.

**Implementation:**
```python
class WhatIfResult:
    @classmethod
    def from_core_scenario(cls,
                          scenario_result: Dict[str, Any],
                          scenario_name: str = "What-If Scenario") -> 'WhatIfResult':
        """
        Create WhatIfResult from core analyze_scenario() output.
        
        🔒 CRITICAL: This must preserve exact same field mappings as 
        from_analyze_scenario_output() AND ensure to_api_response() produces 
        identical output to current API responses.
        
        The existing to_api_response() method expects these fields:
        - current_metrics, scenario_metrics (RiskAnalysisResult objects)
        - risk_comparison, beta_comparison (DataFrames)
        - All CLI tables via get_*_table() methods
        """
        # Extract components from analyze_scenario result
        raw_tables = scenario_result["raw_tables"]
        
        # Create RiskAnalysisResult objects using proven from_build_portfolio_view
        current_metrics = RiskAnalysisResult.from_build_portfolio_view(
            raw_tables["summary_base"], portfolio_name="Current Portfolio"
        )
        scenario_metrics = RiskAnalysisResult.from_build_portfolio_view(
            raw_tables["summary"], portfolio_name=scenario_name
        )
        
        # Create WhatIfResult with identical data structure
        result = cls(
            current_metrics=current_metrics,
            scenario_metrics=scenario_metrics,
            scenario_name=scenario_name,
            risk_comparison=raw_tables["cmp_risk"],
            beta_comparison=raw_tables["cmp_beta"]
        )
        
        # Store CLI data exactly as factory method does
        result._new_portfolio_risk_checks = raw_tables["risk_new"]
        result._new_portfolio_factor_checks = raw_tables["beta_f_new"]
        result._new_portfolio_industry_checks = raw_tables["beta_p_new"]
        result._scenario_metadata = scenario_result.get("scenario_metadata", {})
        
        return result
```

**API Response Validation:**
After creating this method, verify `result.to_api_response()` produces identical JSON to current responses.

#### **1A.3 Update analyze_scenario() to Return Result Objects**
**File:** `core/scenario_analysis.py`
**Current:** Lines 151-210 return Dict[str, Any]
**Target:** Return WhatIfResult directly
**🔒 CRITICAL**: Must update all imports and callers simultaneously

**Implementation:**
```python
# BEFORE (lines 151-210)
return {
    "scenario_summary": summary,
    "risk_analysis": {...},
    "beta_analysis": {...},
    "comparison_analysis": {...},
    "scenario_metadata": {...},
    "raw_tables": {...}
}

# AFTER - Core function builds result object using new builder
from core.result_objects import WhatIfResult

return WhatIfResult.from_core_scenario(
    scenario_result={
        "scenario_summary": summary,
        "risk_analysis": {
            "risk_checks": risk_new.to_dict('records'),
            "risk_passes": bool(risk_new['Pass'].all()) if not risk_new.empty else True,
            # ... preserve all existing fields
        },
        "beta_analysis": {
            "factor_beta_checks": beta_f_new.to_dict('records'),
            # ... preserve all existing fields
        },
        "comparison_analysis": {
            "risk_comparison": cmp_risk.to_dict('records'),
            "beta_comparison": cmp_beta.to_dict('records'),
        },
        "scenario_metadata": {
            "scenario_yaml": scenario_yaml,
            "delta_string": delta,
            "analysis_date": datetime.now(UTC).isoformat(),
            "portfolio_file": filepath,
            "base_weights": weights
        },
        "raw_tables": {
            "summary": summary,
            "summary_base": summary_base,
            "risk_new": risk_new,
            "beta_f_new": beta_f_new,
            "beta_p_new": beta_p_new,
            "cmp_risk": cmp_risk,
            "cmp_beta": cmp_beta
        }
    },
    scenario_name="What-If Scenario"
)
```

**Required Import Updates (Same Day):**
```python
# File: core/scenario_analysis.py - Add import
from core.result_objects import WhatIfResult

# File: run_risk.py - Update type hint
def run_what_if(...) -> Union[None, WhatIfResult]:  # When return_data=True
```

#### **1A.4 Simplify run_what_if() Dual-Mode Logic**
**File:** `run_risk.py`
**Current:** Lines 310-420 (~110 lines of dual-mode complexity)
**Target:** ~15 lines of simple dispatching

**Implementation:**
```python
# BEFORE: Lines 310-420 (110 lines of complex extraction and dual-mode logic)
def run_what_if(filepath, scenario_yaml=None, delta=None, *, return_data=False):
    scenario_result = analyze_scenario(filepath, scenario_yaml, delta)
    
    # Extract components for compatibility with dual-mode logic
    summary = scenario_result["raw_tables"]["summary"]
    summary_base = scenario_result["raw_tables"]["summary_base"]
    risk_new = scenario_result["raw_tables"]["risk_new"]
    # ... 50+ lines of extraction
    
    if return_data:
        # Create formatted report by capturing print output
        report_buffer = StringIO()
        with redirect_stdout(report_buffer):
            print_what_if_report(...)
        # ... more complexity
    else:
        print_what_if_report(...)

# AFTER: ~15 lines of simple dispatching
def run_what_if(filepath, scenario_yaml=None, delta=None, *, return_data=False):
    result = analyze_scenario(filepath, scenario_yaml, delta)  # Returns WhatIfResult
    
    if return_data:
        # For API compatibility, return dict structure
        api_dict = result.to_api_response()
        # Add formatted_report for backward compatibility
        api_dict["formatted_report"] = result.to_cli_report()
        return api_dict
    else:
        print(result.to_cli_report())
```

### **Phase 1B: API Route Updates (Week 2)**

#### **1B.1 Update API Route to Remove Factory Method**
**File:** `routes/api.py`
**Target:** Lines 1172-1175 - Remove factory method usage
**🔒 CRITICAL**: API response must be character-identical to before refactor

**Current Implementation:**
```python
# Use dual-mode run_what_if function directly
result = run_what_if(
    filepath=temp_portfolio_yaml,
    scenario_yaml=temp_scenario_yaml_path,
    delta=delta_string,
    return_data=True
)

# Wrap in result object for consistent serialization
result_obj = WhatIfResult.from_analyze_scenario_output(
    analyze_scenario_result=result,
    scenario_name="What-If Scenario"
)
```

**New Implementation:**
```python
# Use dual-mode run_what_if function directly  
result_obj = run_what_if(
    filepath=temp_portfolio_yaml,
    scenario_yaml=temp_scenario_yaml_path,
    delta=delta_string,
    return_data=True
)  # Now returns WhatIfResult directly
```

**Note:** Keep all temp YAML file creation exactly as-is. Only remove the factory method wrapping step since `run_what_if(return_data=True)` will now return `WhatIfResult` directly.

### **Phase 2: Testing and Validation (Week 2-3)**

#### **2.1 Comprehensive Validation**
**Using Existing Tools:**

**Baseline Capture:**
```bash
# CLI output baseline
python run_risk.py --what-if portfolio.yaml scenario.yaml > whatif_cli_baseline.txt

# API schema baseline using existing tools
python scripts/collect_all_schemas.py
cp -r docs/schema_samples docs/whatif_refactor_baseline
```

**Post-Refactor Validation:**
```bash
# CLI must be identical
python run_risk.py --what-if portfolio.yaml scenario.yaml > whatif_cli_new.txt
diff whatif_cli_baseline.txt whatif_cli_new.txt  # Must be zero differences

# API JSON must be identical (except analysis_metadata)
python scripts/collect_all_schemas.py
diff -r docs/whatif_refactor_baseline docs/schema_samples
```

### **Phase 3: Cleanup (Week 3)**

#### **3.1 Remove Deprecated Factory Method**
**After validation passes:**

```bash
# Find remaining usage
grep -r "from_analyze_scenario_output" --include="*.py" .

# Remove factory method after confirming no usage
```

## Implementation Timeline

### **Week 1: Enhanced Result Objects (Phase 1A)**
- **Day 1-2**: Add `to_cli_report()` method to WhatIfResult + `from_core_scenario()` builder
- **Day 3-4**: Update `analyze_scenario()` return type + import updates
- **Day 5**: Update `run_what_if()` dual-mode logic (~110 lines → ~15 lines)

### **Week 2: API Integration (Phase 1B)**  
- **Day 1**: Update API route to remove factory method usage
- **Day 2-3**: Integration testing and validation

### **Week 3: Cleanup (Phase 3)**
- **Day 1-2**: Comprehensive validation using existing tools  
- **Day 3**: Remove deprecated factory method

## Critical Validation Framework

### **Definition of Done Criteria**

**CLI Output Completeness:**
- **Required Sections**: All original what-if sections must be preserved:
  - Scenario header and description
  - Portfolio weights before/after table
  - New portfolio risk limit checks
  - New portfolio factor exposure checks  
  - Risk limits comparison (before vs after)
  - Factor betas comparison (before vs after)
- **Line Count Test**: `wc -l` must be within 5% of original
- **Section Count Test**: `grep "=== " -c` must match original

**API Response Completeness:**
- **Required Fields**: All critical scenario data:
  - `current_metrics`, `scenario_metrics` (complete portfolio analyses)
  - `deltas` (volatility, concentration, factor changes)
  - `position_changes`, `risk_comparison`, `factor_comparison` tables
  - `new_portfolio_*_checks` tables for compliance validation
- **No None Values**: All computed properties must return valid data
- **Serialization Test**: `json.dumps(api_response)` must succeed

### **Validation Scripts**

**CLI Validation:**
```python
def validate_whatif_cli_output(output_file):
    """Ensure what-if CLI output has all required sections"""
    with open(output_file) as f:
        content = f.read()
    
    required_sections = [
        "=== What-If Scenario Analysis",
        "=== Portfolio Weights — Before vs After ===",
        "=== NEW Portfolio – Risk Checks ===",
        "=== NEW Aggregate Factor Exposures ===",
        "=== Risk Limits — Before vs After ===",
        "=== Factor Betas — Before vs After ==="
    ]
    
    missing_sections = [s for s in required_sections if s not in content]
    assert len(missing_sections) == 0, f"Missing sections: {missing_sections}"
    
    section_count = content.count("=== ")
    assert section_count >= 6, f"Only {section_count} sections, need 6+"
```

**API Validation:**
```python
def validate_whatif_api_response(api_response):
    """Ensure API response has all required what-if fields"""
    required_fields = [
        'scenario_name', 'deltas', 'position_changes',
        'new_portfolio_risk_checks', 'new_portfolio_factor_checks',
        'risk_comparison', 'factor_comparison'
    ]
    
    for field in required_fields:
        assert field in api_response, f"Missing field: {field}"
    
    # Test critical sub-structures
    assert 'volatility_delta' in api_response['deltas']
    assert len(api_response['position_changes']) > 0
    assert len(api_response['risk_comparison']) > 0
```

## Risk Mitigation

### **Rollback Procedures**
**Before each phase:**
```bash
git checkout -b "backup-whatif-phase-1A"
git add -A && git commit -m "Backup before what-if Phase 1A refactor"
```

**If validation fails:**
```bash
git checkout backup-whatif-phase-1A
git checkout -b "main-whatif-restored"
# Fix issues, then retry phase
```

### **Dependency Verification**
**Files that call analyze_scenario() or run_what_if():**
```bash
grep -r "analyze_scenario" --include="*.py" .
grep -r "run_what_if" --include="*.py" .
grep -r "from.*scenario_analysis.*import" --include="*.py" .
```

## Success Metrics

### **Technical Metrics**
- **Lines of code reduction** in dual-mode functions (target: 85%+ reduction)
  - `run_what_if()`: 110 lines → ~15 lines
- **Factory method elimination** (target: remove `from_analyze_scenario_output()`)
- **API/CLI consistency** (target: 100% field alignment via shared result object)

## Conclusion

This refactoring follows the proven Result Objects pattern established in RESULT_OBJECTS_ARCHITECTURE.md, applied specifically to the what-if analysis flow. The implementation maintains perfect backward compatibility while establishing single source of truth architecture.

**Key Benefits:**
1. **Simplified dual-mode logic** - Clean separation of concerns (~110 lines → ~15 lines)
2. **Enhanced maintainability** - Single source of truth via WhatIfResult
3. **Guaranteed consistency** - CLI and API derive from same result object
4. **Easy feature addition** - Add field once in result object, works everywhere

The plan targets specific files and line ranges with minimal scope changes, following the exact same patterns used successfully in the portfolio analysis refactor.