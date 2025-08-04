# Complete Risk Module Codebase Map

## Overview
This document provides a comprehensive map of the entire risk_module codebase, including all directories (even those in .gitignore). Last updated on 2025-08-04 to reflect current codebase state and frontend architecture improvements.

## Directory Structure with Python File Counts

### Root Level Files (22 Python files)
- `ai_function_registry.py` - Registry for AI/Claude function definitions
- `app.py` - Main Flask application entry point
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
- `run_migration.py` - Database migration runner
- `settings.py` - Application settings
- `test_logging.py` - Logging test utilities
- `check_user_data.py` - Database content verification utility
- `db_pool.py` - Database connection pooling
- `db_session.py` - Database session management

### Core Application Layers (CRITICAL - Gitignored)

#### `/services/` (17 Python files) - Business Logic Layer
Service layer implementing core business logic:
- `service_manager.py` - Service lifecycle management
- `portfolio_service.py` - Portfolio management service
- `stock_service.py` - Stock analysis service
- `optimization_service.py` - Portfolio optimization service
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
- Plus additional service files (17 total including subdirectories and __init__.py files)

#### `/routes/` (7 Python files) - API Endpoints Layer
Flask route definitions:
- `api.py` - Main API endpoints
- `auth.py` - Authentication routes
- `admin.py` - Admin panel routes
- `claude.py` - Claude AI integration routes
- `plaid.py` - Plaid integration routes
- `frontend_logging.py` - Frontend logging routes

#### `/utils/` (8 Python files) - Utility Layer
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
- `risk_config.py` - Risk configuration management
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
  - `package.json` - Frontend dependencies and scripts
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
    - `/chat/` - AI chat integration
    - `/dashboard/` - Dashboard views and containers
    - `/plaid/` - Plaid integration components
    - `/portfolio/` - Portfolio management components
    - `/shared/` - Reusable UI components
  - **`/features/`** - Feature-organized hooks and logic
    - `/analysis/` - Factor analysis and performance hooks (with formatters)
    - `/auth/` - Authentication flow hooks
    - `/external/` - Plaid and AI chat hooks
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

#### `/tests/` (Basic testing framework)
Basic test setup with core functionality:

**Core Test Files**:
- `ai_test_orchestrator.py` - AI-powered test orchestration
- `conftest.py` - Pytest configuration
- `test_factor_proxies.py` - Factor proxy tests
- `auth.setup.js` - Authentication setup for E2E tests
- Documentation: `AI_TEST_GUIDE.md`, `README.md`, `TESTING_COMMANDS.md`

**Scripts and Configuration**:
- Various shell scripts for E2E testing (`run-e2e-tests.sh`, `run-e2e-tests-ai.sh`)
- `setup-e2e-tests.sh` - E2E test environment setup
- `setup-test-auth.sh` - Test authentication setup
- `setup-authentication.js` - Authentication setup for frontend testing
- `playwright.config.js` - Playwright configuration for E2E tests
- `jest.config.js` - Jest configuration for unit tests

**Test Results Storage**:
- `/test-results/` - Test execution results
- `/coverage/` - Code coverage reports (clover.xml, coverage-final.json, lcov.info)

**Note**: The comprehensive multi-layer testing framework mentioned in previous documentation appears to be primarily located in the `/risk_module_secrets/` directory, which contains extensive E2E tests, integration tests, and various test scenarios.

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
- **`/interfaces/`** - Interface documentation
- **`/planning/`** - Planning documents

#### `/completed/`
Completed feature documentation and plans

#### `/admin/` (2 Python files)
- `manage_reference_data.py` - Reference data management tool
- `migrate_reference_data.py` - Reference data migration tool

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

#### `/database/`
Database-related files and migrations

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
- `playwright.config.js` - E2E testing configuration
- `jest.config.js` - Jest testing configuration
- `tsconfig.json` - TypeScript configuration (frontend)
- Various shell scripts for testing, deployment, and utilities:
  - `backup_system.sh` - System backup script
  - `secrets_helper.sh` - Secrets management
  - `update_secrets.sh` - Secret update utility
  - `sync-to-public.sh` - Public repository sync
- Database schema: `db_schema.sql`
- Jupyter notebook: `risk_runner.ipynb`

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
- Total Python files: 558 (as of 2025-08-04)
- Core application: ~71 files (22 root + 17 services + 7 routes + 8 utils + 7 inputs + 10 core)
- Tests: ~5 files (basic test setup, extensive tests in secrets directory)
- Archive/Backup: Extensive files across multiple directories
- Prototype: 17+ files (Python + Jupyter notebooks)
- Tools: 9 files
- Frontend: Full React application (0 Python files, comprehensive TypeScript architecture)
- Admin tools: 2 files

## Architecture Changes Since Last Update (2025-08-04)
### Frontend Architecture Maturation (Recent Changes):
1. **Chassis Pattern Implementation**: Complete service layer infrastructure with managers and navigation
2. **Component Architecture**: Well-organized feature-based component structure with apps, auth, dashboard, and shared components
3. **Hook-Based Data Layer**: Feature-organized hooks for analysis, auth, external integrations, portfolio, risk, and utilities
4. **State Management**: Comprehensive Zustand stores for auth, portfolio, and UI state
5. **Service Layer**: Production-ready services including APIService, AuthService, ClaudeService, and PlaidService

### Backend Service Layer Stability:
1. **Service Count Accuracy**: Confirmed 17 service files including subdirectories and initialization files
2. **Proxy Service Maturation**: Established `factor_proxy_service.py` for centralized proxy management
3. **Cache Management**: Stable `cache_mixin.py` for service-level caching utilities
4. **Function Registry**: Enhanced `ai_function_registry.py` for AI/Claude function definitions

### Documentation and Development Tools:
1. **Security Audit**: New comprehensive security audit report (SECURITY_AUDIT_REPORT.md)
2. **Prompts Documentation**: Multiple prompt files including PROMPTS_INTERFACE.md, PROMPTS_DEV.md, and PROMPTS_WORKING.md
3. **E2E Testing**: New E2E_TESTING_GUIDE.md for comprehensive testing documentation
4. **Living Code Map**: Dynamic code mapping tools for real-time codebase analysis

## Key Integration Points
1. Database: PostgreSQL via `database_client.py`
2. External APIs: Plaid, Claude AI
3. Frontend: React with TypeScript
4. Authentication: Google OAuth integration
5. Real-time: WebSocket support for chat
