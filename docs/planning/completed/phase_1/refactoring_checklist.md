# Refactoring Implementation Checklist

## 🚨 CRITICAL SUCCESS CRITERIA
- [ ] Service layer tests: 9/9 PASSED after each step
- [ ] Portfolio volatility: 19.80% (unchanged)
- [ ] Performance returns: 25.98% (unchanged)  
- [ ] Sharpe ratio: 1.180 (unchanged)
- [ ] CLI output: Identical to before refactoring
- [ ] API endpoints: Return identical JSON structures

## Step-by-Step Progress

### Step 1: Extract Portfolio Analysis Logic ✅
- [ ] Create `core/portfolio_analysis.py`
- [ ] Extract business logic from `run_portfolio()` (between marked boundaries)
- [ ] Update `run_portfolio()` to call core function
- [ ] **TEST**: Run `python3 test_service_layer.py` - must show 9/9 PASSED
- [ ] **VALIDATE**: Portfolio volatility still 19.80%

### Step 2: Extract Utilities ✅
- [ ] Create `utils/` directory and `__init__.py`
- [ ] Create `utils/serialization.py`
- [ ] Move `make_json_safe()` function
- [ ] Move `_format_portfolio_output_as_text()` function
- [ ] Update imports in `run_risk.py`
- [ ] **TEST**: API endpoints still work correctly

### Step 3: Extract Optimization Logic ✅
- [ ] Create `core/optimization.py`
- [ ] Extract `run_min_variance()` business logic
- [ ] Extract `run_max_return()` business logic
- [ ] Update dual-mode wrappers in `run_risk.py`
- [ ] **TEST**: Run optimization tests - min variance must work

### Step 4: Extract Stock Analysis Logic ✅
- [ ] Create `core/stock_analysis.py`
- [ ] Extract `run_stock()` business logic
- [ ] Preserve complex parameter handling
- [ ] Update dual-mode wrapper in `run_risk.py`
- [ ] **TEST**: SGOV analysis must complete successfully

### Step 5: Extract Performance Analysis Logic ✅
- [ ] Create `core/performance.py`
- [ ] Extract `run_portfolio_performance()` business logic
- [ ] Update dual-mode wrapper in `run_risk.py`
- [ ] **TEST**: Performance must show 25.98% returns, 1.180 Sharpe

### Step 6: Extract What-If Scenario Logic ✅
- [ ] Create `core/scenarios.py`
- [ ] Extract `run_what_if()` business logic
- [ ] Preserve scenario delta parsing logic
- [ ] Update dual-mode wrapper in `run_risk.py`
- [ ] **TEST**: What-if scenarios must work correctly

### Step 7: Extract AI Interpretation Logic ✅
- [ ] Create `core/interpretation.py`
- [ ] Extract `run_and_interpret()` function
- [ ] Extract `interpret_portfolio_output()` function
- [ ] Update imports in `run_risk.py`
- [ ] **TEST**: AI interpretation must be ~5,265 characters

### Step 8: Comprehensive Module Testing ✅
- [ ] Run `python3 test_service_layer.py` (all 9 tests must pass)
- [ ] Run `python3 comprehensive_test.py` (cross-path consistency)
- [ ] Run dual-mode function tests
- [ ] Run API endpoint tests
- [ ] **VALIDATE**: All critical metrics unchanged

### Step 9: Update Service Layer ✅
- [ ] Update `services/portfolio_service.py` to call core modules
- [ ] Update other service classes as needed
- [ ] Remove dependencies on `run_risk.py` dual-mode functions
- [ ] **TEST**: Service layer tests must still pass

### Step 10: Final Cleanup ✅
- [ ] Update `core/__init__.py` to export new functions
- [ ] Update `utils/__init__.py` to export utilities
- [ ] Remove unused imports from `run_risk.py`
- [ ] **FINAL TEST**: All tests must pass, all metrics unchanged

## 🚨 Emergency Procedures

### If a Test Fails
1. **STOP immediately** - do not continue to next step
2. **Revert the current step** - restore to previous working state
3. **Check extraction markers** - ensure boundaries were followed exactly
4. **Verify imports** - missing imports cause most failures
5. **Test dual-mode behavior** - both CLI and API modes must work
6. **Fix the issue** before proceeding

### If Metrics Change
1. **REVERT immediately** - the extraction broke something
2. **Check variable names** - must match exactly in dual-mode logic
3. **Verify business logic** - ensure no calculation logic was lost
4. **Test with original portfolio** - use same test data

### If Service Layer Breaks
1. **Check imports** - service layer may need updated imports
2. **Verify return structures** - must match exactly what services expect
3. **Test with service endpoints** - ensure API still works

## Success Validation ✅

### Technical Validation
- [ ] Service layer tests: 9/9 PASSED
- [ ] CLI functions work identically
- [ ] API endpoints return same JSON
- [ ] Performance metrics consistent
- [ ] No regressions in any functionality

### Code Quality Validation
- [ ] `run_risk.py` reduced from 1164 to ~200 lines
- [ ] Business logic in focused core modules
- [ ] Clean imports, no circular dependencies
- [ ] Comprehensive documentation
- [ ] Type hints for all core functions

### Integration Validation
- [ ] Claude can call core functions directly
- [ ] Service layer bypasses run_risk.py
- [ ] New output formats easy to add
- [ ] Caching works at core level

**🎉 REFACTORING COMPLETE!**
The codebase is now a clean, modular architecture serving CLI, API, and AI integration equally well. 