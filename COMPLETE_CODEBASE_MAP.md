# Complete Risk Module Codebase Map

## Overview
This document provides a comprehensive map of the entire risk_module codebase, including all directories (even those in .gitignore). Last updated on 2025-08-21 to reflect current codebase state, FastAPI migration completion, database structure reorganization, recent API refactoring initiatives, and the integration of Vercel AI SDK for enhanced chat functionality.

## Directory Structure with Python File Counts

### Root Level Files (19 Python files)
Core application files and utilities:
- `ai_function_registry.py` - Registry for AI/Claude function definitions
- `app.py` - Main FastAPI application entry point (migrated from Flask)
- `comprehensive_endpoint_testing.py` - Comprehensive API endpoint testing utility
- `data_loader.py` - Data loading utilities
- `factor_utils.py` - Factor analysis utilities
- `gpt_helpers.py` - GPT/AI integration helpers
- `helpers_display.py` - Display formatting utilities
- `helpers_input.py` - Input processing utilities
- `plaid_loader.py` - Plaid API integration
- `portfolio_optimizer.py` - Portfolio optimization algorithms
- `portfolio_risk.py` - Portfolio risk calculations
- `portfolio_risk_score.py` - Risk scoring system
- `position_metadata.py` - Position metadata utilities
- `proxy_builder.py` - Proxy ETF builder
- `risk_helpers.py` - Risk calculation helpers
- `risk_summary.py` - Risk summary generation
- `run_portfolio_risk.py` - Portfolio risk runner script
- `run_risk.py` - Main risk calculation runner
- `settings.py` - Application settings

**Note**: Schema and testing files have been relocated to appropriate directories (`/docs/planning/`, `/backup/`, etc.) to improve repository organization.

### Core Application Layers

#### `/models/` (23 Python files) - Pydantic Response Models
FastAPI response validation models for API endpoints:
- Auto-generated Pydantic models for all API responses
- Type-safe response validation and documentation
- Comprehensive model coverage for all result objects
- `response_models.py` - Core response model definitions
- Individual model files for each endpoint type (e.g., `analyzeresponse.py`, `performanceresponse.py`)
- `usage_example.py` - Model usage examples

### Core Application Layers (CRITICAL - Gitignored)

#### `/services/` (18 Python files) - Business Logic Layer
Service layer implementing core business logic:
- `service_manager.py` - Service lifecycle management
- `portfolio_service.py` - Portfolio management service
- `stock_service.py` - Stock analysis service
- `optimization_service.py` - Portfolio optimization service
- `returns_service.py` - Returns calculation service
- `scenario_service.py` - Scenario analysis service
- `validation_service.py` - Data validation service
- `async_service.py` - Asynchronous service utilities
- `auth_service.py` - Authentication service
- `usage_examples.py` - Service usage examples
- `cache_mixin.py` - Cache management utilities
- `factor_proxy_service.py` - Factor proxy management service
- **`/claude/`** subdirectory (3 Python files):
  - `__init__.py` - Claude module initialization
  - `chat_service.py` - Claude chat integration
  - `function_executor.py` - Function execution for Claude
- **`/portfolio/`** subdirectory (2 Python files):
  - `__init__.py` - Portfolio module initialization
  - `context_service.py` - Portfolio context management

#### `/routes/` (6 Python files) - API Endpoints Layer
FastAPI route definitions:
- `auth.py` - Authentication routes
- `admin.py` - Admin panel routes
- `claude.py` - Claude AI integration routes
- `plaid.py` - Plaid integration routes
- `frontend_logging.py` - Frontend logging routes

**Note**: Main API routes have been migrated directly into `app.py` as part of the FastAPI migration

#### `/utils/` (10 Python files) - Utility Layer
Shared utilities:
- `auth.py` - Authentication utilities
- `config.py` - Configuration management
- `logging.py` - Logging infrastructure
- `serialization.py` - Data serialization utilities
- `errors.py` - Error handling utilities
- `etf_mappings.py` - ETF mapping utilities
- `json_logging.py` - JSON logging utilities

**Note**: `portfolio_context.py` has been removed as part of recent refactoring

#### `/inputs/` (7 Python files) - Data Access Layer
Data input and management:
- `database_client.py` - PostgreSQL database client
- `file_manager.py` - File system management
- `portfolio_manager.py` - Portfolio data management
- `returns_calculator.py` - Returns calculation
- `risk_limits_manager.py` - Risk limits configuration management (renamed from risk_config.py)
- `exceptions.py` - Custom exception definitions

#### `/core/` (10 Python files) - Core Business Objects
Core data structures and algorithms:
- `data_objects.py` - Core data object definitions
- `result_objects.py` - Result data structures
- `exceptions.py` - Core exception definitions
- `interpretation.py` - Result interpretation logic
- `optimization.py` - Optimization algorithms
- `performance_analysis.py` - Performance analytics
- `portfolio_analysis.py` - Portfolio analysis logic
- `scenario_analysis.py` - Scenario analysis logic
- `stock_analysis.py` - Stock analysis algorithms

### Frontend Application (React/TypeScript)

#### `/frontend/` (0 Python files + full React app)
Production-ready React frontend application with comprehensive architecture:
- **`/node_modules/`** - Complete npm dependencies (extensive)
- Configuration files:
  - `package.json` - Frontend dependencies and scripts (includes Vercel AI SDK)
  - `package-lock.json` - Dependency lock file
  - `tsconfig.json` - TypeScript configuration
- Documentation:
  - `README.md` - Frontend documentation
  - `FRONTEND_DATA_FLOW_GUIDE.md` - Data flow guide
- Build and development logs:
  - `build-final.log` - Final build log
  - `build-test.log` - Test build log
  - `eslint-check.log` - ESLint validation log
  - `typescript-check.log` - TypeScript validation log
- **`/src/`** - Complete React application with clean architecture:
  - `ARCHITECTURE.md` - Frontend architecture documentation
  - **`/chassis/`** - Service layer infrastructure
    - `/managers/` - AuthManager, PlaidManager, PortfolioManager
    - `/navigation/` - NavigationIntents, NavigationResolver
    - `/schemas/` - API schemas and validation
    - `/services/` - APIService, AuthService, ClaudeService, PlaidService
    - `/types/` - TypeScript type definitions
  - **`/components/`** - UI components organized by feature
    - `/apps/` - Complete app experiences (LandingApp, DashboardApp)
    - `/auth/` - Authentication components
    - `/chat/` - AI chat integration with streaming capabilities
      - `AIChat.tsx` - Modal chat interface
      - `ChatContext.tsx` - Shared chat state management
      - `ChatCore.tsx` - Core chat functionality and UI
      - `RiskAnalysisChat.tsx` - Specialized risk analysis chat
      - `CHAT_ARCHITECTURE.md` - Chat system documentation
      - `/shared/` - Shared chat components
    - `/dashboard/` - Dashboard views and containers
    - `/layout/` - Layout components including ChatInterface
    - `/plaid/` - Plaid integration components
    - `/portfolio/` - Portfolio management components
    - `/shared/` - Reusable UI components
  - **`/features/`** - Feature-organized hooks and logic
    - `/analysis/` - Factor analysis and performance hooks (with formatters)
    - `/auth/` - Authentication flow hooks
    - `/external/` - Plaid and AI chat hooks
      - `useChat.ts` - Chat functionality hook
      - `usePortfolioChat.ts` - Portfolio-specific chat integration
      - `usePlaid.ts` - Plaid integration hook
    - `/portfolio/` - Portfolio data and operations hooks (with formatters)
    - `/riskScore/` - Risk score calculations and hooks (with formatters)
    - `/optimize/` - Portfolio optimization hooks
    - `/scenario/` - Scenario analysis hooks
    - `/utils/` - Request cancellation and polling hooks
  - **`/stores/`** - Zustand state management
  - **`/providers/`** - React context providers
  - **`/router/`** - App orchestration
  - **`/utils/`** - Utilities and adapters
- Testing infrastructure:
  - `/coverage/` - Code coverage reports
  - `/examples/` - Usage examples
- Additional files:
  - `cookies.txt` - Session data
  - `package-update.json` - Package update tracking

### Testing Infrastructure (Basic Test Setup)

#### `/tests/` (Comprehensive testing framework)
Robust testing infrastructure with extensive coverage:

**Core Test Files**:
- `ai_test_orchestrator.py` - AI-powered test orchestration
- `conftest.py` - Pytest configuration
- `test_factor_proxies.py` - Factor proxy tests
- `test_claude_functions.py` - Claude AI function testing utility
- `auth.setup.js` - Authentication setup for E2E tests
- Documentation: `AI_TEST_GUIDE.md`, `README.md`, `TESTING_COMMANDS.md`

**Subdirectories**:
- **`/api/`** - API endpoint tests (7 Python files)
- **`/e2e/`** - End-to-end testing with Playwright
- **`/integration/`** - Integration tests for complex workflows
- **`/frontend/`** - React component and integration tests
- **`/utils/`** - Testing utilities including `show_api_output.py`
- **`/performance/`** - Performance benchmarking tests
- **`/debug/`** - Debugging and diagnostic test specs

**Scripts and Configuration**:
- Various shell scripts for E2E testing (`run-e2e-tests.sh`, `run-e2e-tests-ai.sh`)
- `setup-e2e-tests.sh` - E2E test environment setup
- `setup-test-auth.sh` - Test authentication setup
- `setup-authentication.js` - Authentication setup for frontend testing
- `playwright.config.js` - Playwright configuration for E2E tests
- `jest.config.js` - Jest configuration for unit tests

**Test Results Storage**:
- `/reports/` - AI test execution reports with timestamps
- `/fixtures/` - Test data files and configurations
- `/cache_prices/` - Test-specific cached price data

### Development & Archive

#### `/archive/` (Extensive Python files and frontend components)
Historical development files and backups including:
- Legacy frontend components
- Backend service archives
- Development prototypes
- Historical configuration files

#### `/backup/` (Extensive Python files)
System backups including full copies of core files and documentation

#### `/prototype/` (17 Python files + notebooks)
Jupyter notebook prototypes converted to Python:
- `data_loader.py` - Data loading prototype
- `plaid_loader_dev_2025-07-10.py` - Plaid integration development
- `proxy_builder_dev_2025-07-10.py` - Proxy builder development
- `risk_module_dev_2025-07-10.py` - Risk module development
- `run_risk_summary_to_gpt_dev.py` - GPT integration development
- Various Jupyter notebooks (.ipynb files)

#### `/tools/` (9 Python files)
Development tools:
- `check_dependencies.py` - Dependency checker
- `test_all_interfaces.py` - Interface testing
- `view_alignment.py` - Code alignment viewer
- `check_parameter_alignment.py` - Parameter alignment checker
- `living_code_map.py` - Dynamic code mapping
- `living_code_map_clean.py` - Clean code mapping
- `watch_and_update.py` - File watching utility
- `backfill_subindustry_peers.py` - Data backfill utility

### Documentation

#### `/docs/`
- `API_REFERENCE.md` - API documentation
- `DATA_SCHEMAS.md` - Data schema documentation
- `VERCEL_AI_SDK_FULL_INTEGRATION_GUIDE.md` - Comprehensive Vercel AI SDK integration guide
- **`/interfaces/`** - Interface documentation
- **`/planning/`** - Planning documents

#### `/completed/` 
Completed feature documentation and plans including:
- `API_DIRECT_INTERPRET_REFACTOR_PLAN.md` - API direct interpret endpoint refactor plan
- `API_DIRECT_PERFORMANCE_REFACTOR_PLAN.md` - API direct performance endpoint refactor plan  
- `API_DIRECT_WHAT_IF_REFACTOR_PLAN.md` - API direct what-if endpoint refactor plan
- `API_PERFORMANCE_ANALYSIS_REFACTOR_PLAN.md` - API performance analysis refactor plan
- `API_RISK_SCORE_REFACTORING_PLAN.md` - API risk score refactor plan
- `DIRECT_API_REFACTOR_TEMPLATE.md` - Template for direct API refactoring
- `MIN_VARIANCE_REFACTORING_PLAN.md` - Minimum variance optimization refactor plan
- `STOCK_ANALYSIS_REFACTOR_PLAN.md` - Stock analysis refactor plan
- `api_direct_max_return_refactor_plan.md` - Maximum return optimization refactor plan
- `RISK_LIMITS_MANAGER_REFACTOR_HANDOFF.md` - Risk limits manager refactor documentation
- Various phase implementation reports and architectural plans
- Frontend refactoring completion reports
- Multi-user implementation documentation

#### `/admin/` (2 Python files)
- `manage_reference_data.py` - Reference data management tool
- `migrate_reference_data.py` - Reference data migration tool

### Database Infrastructure

#### `/database/`
Centralized database infrastructure:
- `__init__.py` - Database module exports and backward compatibility
- `session.py` - Request-scoped database session management (moved from db_session.py)
- `pool.py` - Database connection pooling (moved from db_pool.py)
- `run_migration.py` - Database migration execution script
- `schema.sql` - Database schema definitions
- **`/migrations/`** - Database migrations:
  - `20250801_add_subindustry_peers.sql` - Subindustry peers migration
  - `20250831_cleanup_subindustry_peers.sql` - Subindustry cleanup migration

### Data & Cache

#### `/cache_prices/`
Price data cache (Parquet files) - Over 1000+ cached price files for various tickers

#### `/cache_test/`
Test cache directory with test key files

#### `/error_logs/`
Comprehensive application error logs including:
- API request logs (daily files from 2025-07-16 to 2025-07-30)
- Authentication event logs
- Claude integration logs
- Critical alerts
- Database operation logs
- Frontend error logs
- Performance metrics
- Portfolio operation logs
- Resource usage logs
- Service health logs
- SQL query logs
- Usage statistics
- Workflow state logs

#### `/exports/`
Data export directory

#### `/user_data/`
User-specific data storage

#### `/temp/`
Temporary file storage


### Configuration Files
- Various YAML files for:
  - Portfolio configurations (`portfolio.yaml`, various scenario files)
  - Risk limits (`risk_limits.yaml`, `risk_limits_adjusted.yaml`)
  - Industry/exchange mappings (`industry_to_etf.yaml`, `exchange_etf_proxies.yaml`)
  - Cash mappings (`cash_map.yaml`)
  - Pipeline test configurations (`pipeline_test.yaml`)
- `package.json` - Node.js dependencies for frontend
- `package.json.backup` - Backup of frontend dependencies
- `requirements.txt` - Python dependencies
- `requirements-dev.txt` - Development Python dependencies
- `playwright.config.js` - E2E testing configuration
- `jest.config.js` - Jest testing configuration
- `tsconfig.json` - TypeScript configuration (frontend)
- Various shell scripts for testing, deployment, and utilities:
  - `backup_system.sh` - System backup script
  - `secrets_helper.sh` - Secrets management
  - `update_secrets.sh` - Secret update utility
  - `sync-to-public.sh` - Public repository sync
  - `run-e2e-tests.sh` - E2E test execution
  - `run-e2e-tests-ai.sh` - AI-enhanced E2E tests
- Database schema: `database/schema.sql` (moved from root db_schema.sql)
- Jupyter notebook: `risk_runner.ipynb`

### Root Level Documentation & Planning
Active planning and development documentation:
- `CLAUDE_RISK_LIMITS_MODERNIZATION_PLAN.md` - Risk limits modernization plan (moved from /completed/)
- `CLI_API_ALIGNMENT_WORKFLOW.md` - CLI and API alignment workflow
- `COMPLETE_CODEBASE_MAP.md` - This comprehensive codebase map
- `E2E_TESTING_GUIDE.md` - End-to-end testing guide
- `PROMPTS_DEV.md` - Development prompts
- `PROMPTS_INTERFACE.md` - Interface prompts
- `PROMPTS_WORKING.md` - Working prompts
- `REFACTORING_TOOLKIT.md` - Refactoring toolkit documentation
- `RESULT_OBJECTS_ARCHITECTURE.md` - Result objects architecture guide
- `SCENARIO_ANALYSIS_CLEANUP_PLAN.md` - Scenario analysis cleanup plan
- `SCHEMA_INVENTORY.md` - Schema inventory documentation

### Additional Directories

#### `/scripts/`
Development and validation scripts:
- `ai-create-snapshot.sh` - AI snapshot creation
- `ai-test-baseline.sh` - Baseline testing
- `ai-validate-repo.sh` - Repository validation
- Various validation scripts for different phases

#### `/templates/`
Template files:
- `dashboard.html` - Dashboard HTML template

#### `/src/`
Legacy source files:
- `App.test.js` - Legacy application test

### Security & Secrets

#### `/risk_module_secrets/` (Extensive files)
**CRITICAL**: Contains duplicated application code, documentation, and configuration
- Full backup/mirror of the application with extensive test files
- Contains development scripts and historical data
- Includes comprehensive test suites and E2E testing files
- Contains various YAML configuration files and scenarios
- Migration test results and performance benchmarks

**Security Considerations**:
- `/risk_module_secrets/` contains sensitive configuration data
- Multiple backup directories with potential secrets
- Contains API keys and authentication tokens (redacted in documentation)
- Database connection strings and configuration files

## File Count Summary
- Total Python files: 712 (as of 2025-08-16)
- Core application: ~76 files (19 root + 18 services + 6 routes + 10 utils + 7 inputs + 10 core + 23 models + database)
- Tests: Comprehensive suite with 50+ test files across multiple directories
- Archive/Backup: Extensive files across multiple directories
- Prototype: 17+ files (Python + Jupyter notebooks)
- Tools: 9 files
- Frontend: Full React application (0 Python files, comprehensive TypeScript architecture)
- Admin tools: 2 files
- Database: Centralized infrastructure with migration support

## Architecture Changes Since Last Update (2025-08-21)

### FastAPI Migration Completion (August 2025):
1. **Framework Migration**: Complete migration from Flask to FastAPI
2. **Pydantic Integration**: Full Pydantic model validation for all API responses
3. **Auto Documentation**: Interactive API docs at `/docs` with comprehensive examples
4. **Type Safety**: Enhanced type safety with Pydantic models and FastAPI dependency injection
5. **Performance**: Async request handling and improved performance characteristics
6. **Rate Limiting**: Migrated from Flask-Limiter to SlowAPI for FastAPI compatibility
7. **Session Management**: Updated session handling for FastAPI middleware
8. **Error Handling**: Standardized error response format maintained across migration

### Risk Limits Manager Refactor (August 2025):
1. **File Rename**: `risk_config.py` → `risk_limits_manager.py` for better semantic clarity
2. **Class Rename**: `RiskConfigManager` → `RiskLimitsManager` with enhanced type safety
3. **Data Objects Integration**: Full integration with `RiskLimitsData` dataclass from `core/data_objects.py`
4. **Architecture Improvement**: Clean separation between API layer orchestration and service layer business logic
5. **User Isolation**: Enhanced user-specific risk limits with database-backed storage

### Database Infrastructure Reorganization (August 2025):
1. **Database Module Creation**: New `/database/` directory with centralized infrastructure
2. **File Moves**: `db_session.py` → `database/session.py`, `db_pool.py` → `database/pool.py`
3. **Migration Management**: Structured `/database/migrations/` with SQL migration files
4. **Import Compatibility**: Backward-compatible imports via `database/__init__.py`
5. **Schema Centralization**: `database/schema.sql` for centralized schema management
### Frontend Architecture Maturation (Recent Changes):
1. **Chassis Pattern Implementation**: Complete service layer infrastructure with managers and navigation
2. **Component Architecture**: Well-organized feature-based component structure with apps, auth, dashboard, and shared components
3. **Hook-Based Data Layer**: Feature-organized hooks for analysis, auth, external integrations, portfolio, risk, and utilities
4. **State Management**: Comprehensive Zustand stores for auth, portfolio, and UI state
5. **Service Layer**: Production-ready services including APIService, AuthService, ClaudeService, and PlaidService
6. **AI Chat Integration**: Comprehensive chat system with streaming capabilities
   - Modal and full-screen chat interfaces
   - Shared conversation state via ChatContext
   - Integration with Vercel AI SDK for enhanced UX
   - File upload support and message management
   - Real-time streaming responses with Claude AI

### Backend Service Layer Enhancements:
1. **Returns Service Addition**: New `returns_service.py` for centralized return calculation logic
2. **Service Count Update**: Confirmed 18 service files (including subdirectories and initialization files)
3. **Enhanced Function Registry**: Updated `ai_function_registry.py` with improved expected returns handling
4. **Proxy Service Maturation**: Established `factor_proxy_service.py` for centralized proxy management
5. **Cache Management**: Stable `cache_mixin.py` for service-level caching utilities

### API Refactoring Initiative (August 2025):
1. **Direct API Refactoring**: Comprehensive refactoring plans for direct API endpoints
2. **Result Objects Architecture**: Unified result objects architecture across CLI and API
3. **Schema Management**: Enhanced schema inventory and validation systems
4. **Template-Based Refactoring**: Standardized refactoring templates for consistency

### Chat System Enhancement (August 2025):
1. **Vercel AI SDK Integration**: Added `@ai-sdk/react` and `@ai-sdk/anthropic` packages for enhanced chat functionality
2. **Streaming Implementation**: Real-time token-by-token streaming for improved user experience
3. **Unified Chat Architecture**: Modal and full-screen interfaces sharing conversation state
4. **Advanced Chat Features**: Message editing, regeneration, file uploads, and smart actions
5. **Context-Aware AI**: Portfolio-specific AI responses with integrated analysis tools
6. **Documentation**: Comprehensive chat architecture documentation including integration guides

### Testing Infrastructure Expansion:
1. **Comprehensive Test Report**: New COMPREHENSIVE_TEST_REPORT.md documenting full system validation
2. **Claude Function Testing**: Enhanced `test_claude_functions.py` utility for local AI function testing
3. **API Testing Suite**: Expanded `/tests/api/` directory with comprehensive endpoint coverage
4. **E2E Testing Framework**: Mature Playwright-based testing with extensive user journey coverage
5. **Performance Benchmarking**: Dedicated performance testing infrastructure
6. **Debug Tools**: Specialized debugging specs for complex workflow analysis

## Key Integration Points
1. Database: PostgreSQL via `database_client.py`
2. External APIs: Plaid, Claude AI
3. Frontend: React with TypeScript
4. Authentication: Google OAuth integration
5. Real-time: WebSocket support for chat
