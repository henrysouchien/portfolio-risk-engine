# Test Organization Plan - ACTIVE DEVELOPMENT TESTS ONLY

## Current State: Active Tests Need Organization
- Tests scattered between `/tests/` (root) and `/frontend/tests/`
- Mix of E2E, API, and frontend tests in root folder
- No clear separation between test types
- Focus: Only tests actually used in development (ignoring archive/backup)

## Proposed Clean Structure

```
/risk_module/
├── tests/                                    # Full-stack integration tests
│   ├── integration/                         # API + Frontend integration  
│   │   ├── analyze-risk-workflow.spec.js   # End-to-end risk analysis
│   │   ├── authenticated-dashboard.spec.js  # Dashboard integration
│   │   ├── factor-analysis-authenticated.spec.js
│   │   ├── final-comprehensive-workflow.spec.js
│   │   └── production-ready-test.spec.js
│   ├── api/                                # Backend API tests
│   │   ├── test_api_endpoints.py
│   │   ├── test_auth_system.py
│   │   ├── test_portfolio_crud.py
│   │   ├── test_portfolio_api_crud.py
│   │   ├── test_services.py
│   │   └── test_logging.py
│   ├── e2e/                                # End-to-end user journeys
│   │   ├── user-journeys/
│   │   │   ├── complete-user-journey.spec.js
│   │   │   └── quick-check.spec.js
│   │   ├── component-tests/
│   │   │   ├── claude-integration-debug.spec.js
│   │   │   └── portfolio-components.spec.js
│   │   ├── helpers/
│   │   │   ├── ai-test-reporter.js
│   │   │   └── test-utils.js
│   │   ├── fixtures/
│   │   │   ├── test-portfolio.yaml
│   │   │   └── invalid-portfolio.yaml
│   │   └── config/
│   │       └── playwright.config.js
│   ├── debug/                              # Debugging tests
│   │   ├── advanced-debugging.spec.js
│   │   ├── dashboard-stability-check.spec.js
│   │   ├── debug-dashboard.spec.js
│   │   └── visual-assessment.spec.js
│   ├── performance/                        # Performance tests
│   │   └── test_performance_benchmarks.py
│   ├── fixtures/                           # Shared test data
│   │   ├── test_risk_limits.yaml
│   │   └── simple_portfolio.yaml
│   └── utils/                              # Test utilities
│       └── test_all_interfaces.py
├── frontend/tests/                         # Frontend-only tests
│   ├── unit/                              # Component unit tests
│   │   ├── components/
│   │   │   ├── auth/
│   │   │   ├── dashboard/
│   │   │   └── shared/
│   │   ├── stores/                        # Zustand store tests
│   │   │   ├── AppStore.test.js
│   │   │   └── dashboardStore.test.js
│   │   ├── hooks/                         # Custom hook tests
│   │   │   ├── useAuthFlow.test.js
│   │   │   └── usePortfolioFlow.test.js
│   │   └── services/                      # Service layer tests
│   │       └── frontendLogger.test.js
│   ├── integration/                       # Frontend integration tests
│   │   ├── auth-flow.test.js
│   │   ├── portfolio-management.test.js
│   │   └── dashboard-navigation.test.js
│   ├── architecture/                      # Architecture validation
│   │   └── refactoring-validation.test.js (existing, updated)
│   ├── mocks/                            # Test mocks
│   │   ├── handlers.js
│   │   └── server.js
│   ├── setup/                            # Test configuration
│   │   └── setup.js
│   └── test-runner.js                    # Enhanced test runner
└── backend/tests/                         # Backend-only tests (future)
    ├── unit/                             # Unit tests for core logic
    ├── integration/                      # Database integration tests
    └── fixtures/                         # Backend test data
```

## Migration Strategy

### Phase 1: Organize Active Tests Only
**Focus on current development tests:**
- `/tests/` (root) - Full-stack integration tests
- `/frontend/tests/` - Frontend architecture tests  
- **IGNORE**: archive, backup, secrets, snapshots folders

### Phase 2: Categorize Active Tests
**Move from root `/tests/` to organized structure:**

**Integration Tests → `/tests/integration/`:**
- `analyze-risk-workflow.spec.js`
- `authenticated-dashboard.spec.js` 
- `factor-analysis-authenticated.spec.js`
- `final-comprehensive-workflow.spec.js`
- `production-ready-test.spec.js`

**API Tests → `/tests/api/` (already there):**
- Keep existing API tests in place

**E2E Tests → `/tests/e2e/`:**
- Move existing e2e structure
- Organize by user-journeys vs component-tests

**Debug Tests → `/tests/debug/`:**
- `advanced-debugging.spec.js`
- `debug-dashboard.spec.js`
- `visual-assessment.spec.js`

### Phase 3: Enhance Frontend Tests
**In `/frontend/tests/`:**
- Expand unit tests for components
- Add store testing
- Add hook testing
- Keep architecture validation

### Phase 4: Update Test Runners
**Unified test execution:**
```bash
# Full-stack integration
npm run test:integration

# Frontend only  
cd frontend && npm test

# Backend only
pytest

# E2E tests
npm run test:e2e

# All tests
npm run test:all
```

## Benefits of This Organization

### ✅ **Clear Separation:**
- Full-stack tests vs frontend vs backend
- Integration vs unit vs e2e
- Debug vs production tests

### ✅ **No Duplication:**
- Single source of truth for each test
- No more confusion about which test to run

### ✅ **Scalable:**
- Easy to add new tests in right category
- Clear ownership (frontend team vs backend team)

### ✅ **Performance:**
- Run only relevant tests during development
- Parallel execution possible

### ✅ **Professional:**
- Industry standard structure
- Easy for new developers to understand

## File Count - Active Tests Only
- **Current Active**: ~30 test files in development use
- **After organization**: Same ~30 files, but properly organized
- **Focus**: Organization, not deletion

## Next Steps
1. **Approve this structure**
2. **Move active tests** to organized structure  
3. **Update test runners** for new paths
4. **Create missing test categories** (unit tests, etc.)
5. **Leave archive/backup folders untouched** (not part of this organization)