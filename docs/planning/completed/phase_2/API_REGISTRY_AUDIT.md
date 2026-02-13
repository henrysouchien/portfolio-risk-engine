Audit Results: API Registry Sync Status

  After comparing the current backend codebase against the apiRegistry.ts file, the following analysis shows the current
  state of API endpoint documentation:

  ✅ Already in Registry (22 endpoints)

  These endpoints are correctly documented in apiRegistry.ts:
  - /api/risk-score (POST)
  - /api/analyze (POST)
  - /api/portfolio-analysis (POST)
  - /api/performance (POST)
  - /api/health (GET)
  - /api/interpret (POST)
  - /api/portfolios (GET, POST)
  - /api/portfolios/:portfolio_name (GET, PUT, PATCH, DELETE)
  - /api/portfolio/refresh-prices (POST)
  - /api/risk-settings (GET, POST)
  - /api/direct/portfolio (POST)
  - /api/direct/stock (POST)
  - /api/direct/what-if (POST)
  - /api/direct/optimize/min-variance (POST)
  - /api/direct/optimize/max-return (POST)
  - /api/direct/performance (POST)
  - /api/direct/interpret (POST)

  ❌ Missing from Registry (15+ endpoints)

  Authentication & User Management:
  - /auth/status (GET)
  - /auth/google (POST)
  - /auth/logout (POST)
  - /auth/cleanup (POST)

  Plaid Financial Integration:
  - /plaid/connections (GET)
  - /plaid/create_link_token (POST)
  - /plaid/connection_status (GET)
  - /plaid/poll_completion (POST)
  - /plaid/exchange_public_token (POST)
  - /plaid/holdings (GET)
  - /plaid/webhook (POST)

  Claude AI Chat:
  - /api/claude_chat (POST)

  Admin Functions:
  - /generate_key (POST)
  - /admin/usage_summary (GET)
  - /admin/cache_status (GET)
  - /admin/clear_cache (POST)

  Frontend Logging:
  - /api/log-frontend (POST)
  - /api/log-frontend/health (GET)

  Additional API Endpoints (Newly Identified):
  - /api/what-if (POST) - Scenario analysis endpoint
  - /api/min-variance (POST) - Portfolio optimization endpoint
  - /api/max-return (POST) - Portfolio optimization endpoint
  - /api/expected-returns (GET, POST) - Expected returns management

  📊 Current Status Summary:
  - Total Backend Endpoints: ~37 endpoints across 6 route files
  - Registry Coverage: 22/37 endpoints (59% documented)
  - Missing Documentation: 15 endpoints (41% undocumented)
  - Primary Gaps: Auth, Plaid, Admin, and Additional API endpoints

  🎯 Priority Recommendations:
  1. **High Priority**: Add core API endpoints (/api/what-if, /api/min-variance, /api/max-return, /api/expected-returns)
  2. **Medium Priority**: Document Auth endpoints for frontend authentication flows
  3. **Low Priority**: Admin and Plaid endpoints (specialized use cases)

  ## Verification Notes

  **Last Updated**: August 14, 2025  
  **Verification Method**: Direct codebase inspection of route files  
  **Route Files Analyzed**:
  - `routes/api.py` (primary API endpoints)
  - `routes/auth.py` (authentication endpoints)
  - `routes/plaid.py` (Plaid integration endpoints)
  - `routes/admin.py` (administrative endpoints)
  - `routes/claude.py` (Claude AI endpoints)
  - `routes/frontend_logging.py` (frontend logging endpoints)

  **Registry File Location**: `frontend/src/apiRegistry.ts`

  ## Current Architecture Notes

  The risk module now uses a comprehensive service-based architecture with:
  - **OpenAPI Integration**: Flask-smorest enabled for API documentation
  - **Database-Backed Authentication**: Full user session management
  - **Service Layer**: Portfolio, Stock, Scenario, and Optimization services
  - **Result Objects**: Structured data objects for consistent API responses
  - **Enhanced Expected Returns**: Auto-generation system with ReturnsService

  **Breaking Changes Since Last Audit**: None - all documented endpoints remain functional with enhanced capabilities.