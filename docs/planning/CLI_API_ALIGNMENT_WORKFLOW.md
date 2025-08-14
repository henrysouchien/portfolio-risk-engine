# CLI-to-API Data Field Alignment Workflow

## 🎯 OBJECTIVE
Systematically align backend data output with result objects for API consumption, ensuring 100% field coverage between CLI and API interfaces.

## 📋 WORKFLOW STEPS

### Phase 1: Assessment & Discovery
1. **Identify the target CLI function/class** that needs API alignment
2. **Run comprehensive field mapping test** to establish baseline coverage
3. **Analyze current gaps** between CLI output sections and API response fields
4. **Document missing fields** and structural differences

### Phase 2: Backend Data Flow Analysis  
1. **Trace data generation** from source functions (e.g., `standardize_portfolio_input`, `build_portfolio_view`)
2. **Identify where metrics are calculated** but not passed through to result objects
3. **Map data flow**: Backend Function → Result Object → API Response
4. **Find surgical intervention points** where data can be passed through

### Phase 3: Systematic Field Addition
1. **Verify result object dataclass** has all necessary fields with proper typing
2. **Check constructor methods** (e.g., `from_risk_score_analysis`) capture all backend data
3. **Ensure `to_api_response` method** includes all fields with proper serialization
4. **Fix API routes** to use `result.to_api_response()` instead of manual construction
5. **Make surgical backend changes** to pass calculated values through (if needed)

### Phase 4: Field Naming Cleanup
1. **Review field names** for consistency and clarity
2. **Remove technical prefixes** (e.g., `df_` for DataFrames) 
3. **Use clean, descriptive names** for API fields
4. **Update all references** across dataclass, extraction, and API response

### Phase 5: Validation & Testing
1. **Regenerate schema samples** to capture changes
2. **Run field mapping test** to verify 100% coverage
3. **Test API output** to ensure new fields appear correctly
4. **Validate field naming consistency**

## 🔧 TOOLS & SCRIPTS NEEDED

### 1. Schema Collection (Generate CLI & API Outputs)
```bash
# Generates both CLI text outputs and API JSON responses
python3 scripts/collect_all_schemas.py

# Output locations:
# docs/schema_samples/cli/[function]_result.txt
# docs/schema_samples/api/[endpoint].json
```

### 2. **NEW: API Testing Utility** 🆕
```bash
# Quick API endpoint testing with formatted output
python3 tests/utils/show_api_output.py [endpoint-name]

# Examples:
python3 tests/utils/show_api_output.py risk-score
python3 tests/utils/show_api_output.py optimization
python3 tests/utils/show_api_output.py whatif

# Features:
# - Sends realistic test data to API endpoints
# - Shows formatted JSON responses
# - Useful for quick verification during alignment work
# - Grep-friendly output for specific fields
```

### 3. **NEW: Database Inspection Utility** 🆕
```bash
# Comprehensive database data inspection
python3 tests/utils/show_db_data.py [data-type] [optional-filter]

# Examples:
python3 tests/utils/show_db_data.py risk-limits           # Show all risk limits
python3 tests/utils/show_db_data.py risk-limits portfolio1  # Specific portfolio
python3 tests/utils/show_db_data.py holdings              # Portfolio holdings
python3 tests/utils/show_db_data.py portfolios            # All portfolios

# Features:
# - Inspects database state for user-specific data
# - Useful for understanding data flow from DB → API
# - Validates that user-specific configurations are working
# - Helps debug data conversion issues
```

### 4. Field Mapping Test Script Template
```python
#!/usr/bin/env python3
"""
CLI vs API Field Mapping Test for [FUNCTION_NAME]
Maps CLI section headers to API JSON field names to check coverage
"""

def get_cli_sections(cli_file: str) -> List[str]:
    """Extract all CLI section headers"""
    # Parse CLI output for section headers, data blocks, etc.
    pass

def get_api_fields(api_file: str) -> List[str]:
    """Extract all API field names including nested fields"""
    # Parse JSON structure for all available fields
    pass

def create_field_mapping() -> List[Tuple[str, str, str]]:
    """Create mapping between CLI sections and API fields
    Returns: [(cli_section, api_field, status)]
    """
    mapping = [
        # Core sections
        ("CLI_SECTION_NAME", "api_field_name", "✅"),
        ("CLI_SECTION_NAME", "nested.field_name", "✅"),
        # Missing fields
        ("CLI_SECTION_NAME", "missing_field", "❌ - Missing from API"),
    ]
    return mapping

def test_field_coverage(cli_file: str, api_file: str) -> bool:
    # Compare CLI sections with API fields using mapping
    # Return True if 100% coverage achieved
    pass

# Usage: python3 field_mapping_test.py cli/output.txt api/output.json
```

### 5. Quick API Testing
```bash
# Test specific endpoint outputs
python3 tests/utils/show_api_output.py [ENDPOINT_NAME]

# Verify API route returns expected data
curl -X POST http://localhost:5000/api/[endpoint] -H "Content-Type: application/json"
```

### 4. Common Issue Detection
```bash
# Check if API routes use manual construction vs to_api_response()
grep -n "return jsonify({" routes/api.py

# Find result objects missing to_api_response method
grep -L "to_api_response" core/result_objects.py
```

## 📝 CLAUDE PROMPT TEMPLATE

Use this prompt for the next CLI function alignment:

---

**SYSTEM CONTEXT:**
You are helping align backend data output with API result objects for a financial risk analysis system. The goal is to ensure 100% field coverage between CLI text output and structured API JSON responses.

**TASK:**
Align the `[CLI_FUNCTION_NAME]` CLI function with its corresponding `[RESULT_OBJECT_NAME]` API result object using the systematic workflow below.

**CURRENT STATE:**
- CLI Function: `[CLI_FUNCTION_PATH]`
- Result Object: `[RESULT_OBJECT_PATH]`  
- API Endpoint: `[API_ENDPOINT_NAME]`
- Backend Functions: `[KEY_BACKEND_FUNCTIONS]`

**WORKFLOW TO FOLLOW:**

1. **ASSESSMENT**: Run field mapping test to establish baseline coverage between CLI and API
2. **ANALYSIS**: Trace data flow from backend functions to result object to identify missing fields
3. **IMPLEMENTATION**: Systematically add missing fields using surgical backend changes
4. **CLEANUP**: Ensure clean, consistent field naming (remove technical prefixes)
5. **VALIDATION**: Verify 100% field coverage with updated schema samples

**KEY PRINCIPLES:**
- Make surgical, minimal changes to backend - only add data pass-through
- Don't modify core business logic - just ensure calculated data reaches API
- Use clean, descriptive field names in API responses
- Maintain 100% field coverage between CLI sections and API fields
- Test thoroughly with schema regeneration

**SUCCESS CRITERIA:**
- Field mapping test shows 100% coverage
- All CLI data sections have corresponding API JSON fields
- Clean, consistent field naming throughout
- No breaking changes to existing functionality

**FILES TO POTENTIALLY MODIFY:**
- `[RESULT_OBJECT_PATH]` - Add fields, update constructors, update API response
- `[BACKEND_FUNCTION_PATHS]` - Add data pass-through for missing metrics
- Field mapping test script - Create or update for this function
- Schema samples - Regenerate after changes

Please follow this systematic approach to achieve perfect CLI-API alignment.

---

## 🎯 EXAMPLE USAGE

**For next function alignment, replace placeholders:**
- `[CLI_FUNCTION_NAME]` → "Portfolio Optimization" 
- `[RESULT_OBJECT_NAME]` → "OptimizationResult"
- `[CLI_FUNCTION_PATH]` → "run_optimization.py"
- `[RESULT_OBJECT_PATH]` → "core/optimization_objects.py"
- `[API_ENDPOINT_NAME]` → "optimize"
- `[KEY_BACKEND_FUNCTIONS]` → "solve_min_variance, solve_max_return"

## 🏆 SUCCESS METRICS
- **100% Field Coverage**: All CLI sections mapped to API fields
- **Clean Naming**: No technical prefixes, descriptive field names
- **Surgical Changes**: Minimal backend modifications, no business logic changes
- **Validated Output**: Schema samples updated, tests passing

## 📋 **NEW: TESTING WORKFLOW WITH NEW TOOLS** 🆕

### Practical Example: Testing Risk Score Alignment
```bash
# 1. Quick API test to see current state
python3 tests/utils/show_api_output.py risk-score

# 2. Check database state for user-specific data
python3 tests/utils/show_db_data.py risk-limits
python3 tests/utils/show_db_data.py holdings

# 3. Compare specific fields
python3 tests/utils/show_api_output.py risk-score | grep -E "(total_value|risk_limits_file)"

# 4. Validate user-specific behavior
python3 tests/utils/show_api_output.py risk-score | grep "Using provided risk limits"

# 5. Inspect data flow issues
python3 tests/utils/show_db_data.py risk-limits portfolio1
```

### Debugging Data Conversion Issues
```bash
# API shows wrong data? Check database source:
python3 tests/utils/show_api_output.py [endpoint] | jq '.field_name'
python3 tests/utils/show_db_data.py [data-type] | grep "field_name"

# Missing fields? Compare CLI vs API side-by-side:
python3 scripts/collect_all_schemas.py  # Generate samples
python3 field_mapping_test.py cli/[function].txt api/[endpoint].json
```

## 🔄 SUCCESSFUL IMPLEMENTATIONS

### RiskScoreResult ✅ COMPLETED  
- **Coverage**: 26/26 CLI sections mapped (100%)
- **Added Fields**: `total_value`, `net_exposure`, `gross_exposure`, `leverage`
- **Cleaned Names**: `df_stock_betas` → `stock_betas`
- **Fix**: Surgical backend change in `portfolio_analysis.py`
- **Architecture**: Clean separation - API orchestrates, Service layer pure  
- **User Isolation**: User-specific risk limits from database
- **Tools Used**: `show_api_output.py`, `show_db_data.py` for validation
- **Key Fix**: Resolved `KeyError: 'max_loss'` database conversion issue
- **Method**: Used `result.to_api_response()` instead of manual API construction
- **Issue Found**: API route used manual response construction instead of `to_api_response()`
- **Fix**: Single-line change in `routes/api.py` to use `result.to_api_response()`
- **Data Added**: 
  - `suggested_limits.factor_limits` (Factor Beta Limits)
  - `suggested_limits.concentration_limit` (Position Size Limit)
  - `suggested_limits.volatility_limit` (Volatility Limit) 
  - `suggested_limits.sector_limit` (Sector Concentration Limit)
  - `priority_actions` (Priority Actions)

## 🎯 COMMON PATTERNS DISCOVERED

### Issue Type 1: Missing Data Fields
- **Symptom**: CLI sections present but no corresponding API fields
- **Root Cause**: Backend generates data but result object doesn't capture it
- **Solution**: Update constructor methods to extract all backend data

### Issue Type 2: Manual API Response Construction
- **Symptom**: API has some fields but missing key sections
- **Root Cause**: API route manually constructs response instead of using `to_api_response()`
- **Solution**: Replace manual `jsonify({...})` with `result.to_api_response()`

### Issue Type 3: Field Naming Mismatches
- **Symptom**: Data exists but field names don't match CLI sections
- **Root Cause**: Technical naming conventions vs. user-friendly names
- **Solution**: Update field mapping test to reflect actual API structure

## 📈 ALIGNMENT METRICS
- **RiskAnalysisResult**: ✅ 100% (26/26 fields)
- **RiskScoreResult**: ✅ 100% (25/25 fields)
- **Next Targets**: OptimizationResult, PerformanceResult, DirectWhatIfResult