Audit Results: Missing Endpoints in apiRegistry.ts

  After comparing your backend codebase against the apiRegistry.ts file, I found several missing endpoints that need to be
  added:

  ✅ Already in Registry (15 endpoints)

  These are correctly documented:
  - /api/risk-score (POST)
  - /api/analyze (POST)
  - /api/portfolio-analysis (POST)
  - /api/performance (POST)
  - /api/health (GET)
  - /api/interpret (POST)
  - /api/portfolios (GET, POST)
  - /api/portfolios/:portfolio_name (GET, PUT, PATCH, DELETE)
  - /api/portfolio/refresh-prices (POST)
  - /api/risk-settings (GET, POST) - Note: Backend has both methods on same route
  - All /api/direct/* endpoints (7 endpoints)

  ❌ Missing from Registry (19+ endpoints)

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