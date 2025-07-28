# Complete Risk Module Codebase Map

## Overview
This document provides a comprehensive map of the entire risk_module codebase, including all directories (even those in .gitignore). Last updated on 2025-07-27 to reflect major frontend and testing refactoring.

## Directory Structure with Python File Counts

### Root Level Files (18 Python files)
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
- `proxy_builder.py` - Proxy ETF builder
- `risk_helpers.py` - Risk calculation helpers
- `risk_summary.py` - Risk summary generation
- `run_portfolio_risk.py` - Portfolio risk runner script
- `run_risk.py` - Main risk calculation runner
- `settings.py` - Application settings
- `test_logging.py` - Logging test utilities

### Core Application Layers (CRITICAL - Gitignored)

#### `/services/` (16 Python files) - Business Logic Layer
Service layer implementing core business logic:
- `service_layer.py` - Main service orchestration
- `service_manager.py` - Service lifecycle management
- `portfolio_service.py` - Portfolio management service
- `stock_service.py` - Stock analysis service
- `optimization_service.py` - Portfolio optimization service
- `scenario_service.py` - Scenario analysis service
- `validation_service.py` - Data validation service
- `async_service.py` - Asynchronous service utilities
- `auth_service.py` - Authentication service
- `usage_examples.py` - Service usage examples
- **`/claude/`** subdirectory:
  - `chat_service.py` - Claude chat integration
  - `function_executor.py` - Function execution for Claude
- **`/portfolio/`** subdirectory:
  - `context_service.py` - Portfolio context management

#### `/routes/` (7 Python files) - API Endpoints Layer
Flask route definitions:
- `api.py` - Main API endpoints
- `auth.py` - Authentication routes
- `admin.py` - Admin panel routes
- `claude.py` - Claude AI integration routes
- `plaid.py` - Plaid integration routes
- `frontend_logging.py` - Frontend logging routes

#### `/utils/` (9 Python files) - Utility Layer
Shared utilities:
- `auth.py` - Authentication utilities
- `config.py` - Configuration management
- `logging.py` - Logging infrastructure
- `serialization.py` - Data serialization utilities
- `errors.py` - Error handling utilities
- `etf_mappings.py` - ETF mapping utilities
- `json_logging.py` - JSON logging utilities
- `portfolio_context.py` - Portfolio context utilities

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
Modern React frontend with TypeScript (refactored architecture):
- **`/src/`** - Source code
  - **`/chassis/`** - Core frontend architecture (clean architecture pattern)
    - `/hooks/` - Custom React hooks (useAuth, useChat, usePortfolio, etc.)
    - `/managers/` - State management (AuthManager, ChatManager, etc.)
    - `/navigation/` - Navigation intent system
    - `/schemas/` - TypeScript schemas and API definitions
    - `/services/` - API service layer (APIService, ClaudeService, etc.)
    - `/types/` - TypeScript type definitions
    - `/viewModels/` - View model pattern implementation
  - **`/adapters/`** - Data adapters for API integration
  - **`/components/`** - UI components (organized by feature)
    - `/auth/` - Authentication components (GoogleSignInButton, LandingPage)
    - `/chat/` - Chat/AI interface (RiskAnalysisChat)
    - `/dashboard/` - Dashboard components with nested structure:
      - `/layout/` - Dashboard layout components
      - `/shared/` - Shared dashboard components (charts, UI elements)
      - `/views/` - Feature-specific views (Risk, Holdings, Performance)
    - `/layouts/` - Application layout components
    - `/plaid/` - Plaid integration UI
    - `/portfolio/` - Portfolio management UI
    - `/shared/` - Shared components across features
  - **`/config/`** - Environment configuration
  - **`/hooks/`** - Application-level custom hooks
  - **`/pages/`** - Page components
  - **`/router/`** - Application routing
  - **`/services/`** - Additional services (SecureStorage, logging)
  - **`/store/`** - Application state stores
  - **`/utils/`** - Utility functions and formatters
- **`/examples/`** - Usage examples and documentation
- **`/public/`** - Static assets
- **`/build/`** - Production build output
- Configuration files: package.json, tsconfig.json, jest.config.js, babel.config.js

### Testing Infrastructure (Comprehensive Multi-Layer Testing)

#### `/tests/` (Expanded testing framework)
Comprehensive test suite with multiple layers:

**Core Python API Tests** (`/api/` subdirectory):
- `test_api_endpoints.py` - API endpoint tests
- `test_auth_system.py` - Authentication tests
- `test_full_workflow.py` - Full workflow tests
- `test_logging.py` - Logging test utilities
- `test_portfolio_api_crud.py` - Portfolio API CRUD tests
- `test_portfolio_crud.py` - Portfolio CRUD tests
- `test_services.py` - Service layer tests

**Frontend Testing** (`/frontend/` subdirectory):
- **`/unit/`** - Unit tests organized by feature:
  - `/adapters/` - Data adapter tests
  - `/components/` - Component tests (auth, dashboard, plaid, portfolio, shared)
  - `/hooks/` - Custom hook tests
  - `/services/` - Service tests
  - `/stores/` - State store tests
- **`/integration/`** - Frontend integration tests
- **`/mocks/`** - Mock implementations and test utilities
- Configuration: `jest.config.js`, test setup files

**End-to-End Testing** (`/e2e/` subdirectory):
- **`/component-tests/`** - Component-level E2E tests
- **`/user-journeys/`** - Complete user workflow tests
- **`/fixtures/`** - Test data and configurations
- **`/helpers/`** - E2E test utilities and AI test reporting
- **`/config/`** - Playwright configuration
- **`/reports/`** - Test execution reports

**Integration Testing** (`/integration/` subdirectory):
- Authentication flow tests
- Claude AI integration tests
- Dashboard functionality tests
- Data flow analysis tests
- Production-ready workflow tests

**Performance & Debug Testing**:
- **`/performance/`** - Performance benchmarks
- **`/debug/`** - Debug-specific test scenarios
- **`/reports/`** - AI-generated test reports

**Utility Tests** (`/utils/` subdirectory):
- `test_basic_functionality.py` - Basic functionality tests
- `test_cli.py` - CLI interface tests
- `test_final_status.py` - Integration tests
- `test_parameter_alignment.py` - Parameter alignment tests
- `run_portfolio_crud_tests.py` - Portfolio CRUD test runner
- `show_api_output.py` - API output debugging

**Test Infrastructure**:
- `ai_test_orchestrator.py` - AI-powered test orchestration
- **`/fixtures/`** - Test data files and configurations
- **`/cache_prices/`** - Test price data cache
- **`/error_logs/`** - Error logs and debugging output
- Documentation: `AI_TEST_GUIDE.md`, `README.md`, `TESTING_COMMANDS.md`

### Development & Archive

#### `/archive/` (101 Python files)
Historical development files and backups

#### `/backup/` (201 Python files)
System backups including full copies of core files

#### `/prototype/` (5 Python files + notebooks)
Jupyter notebook prototypes converted to Python

#### `/tools/` (3 Python files)
Development tools:
- `check_dependencies.py` - Dependency checker
- `test_all_interfaces.py` - Interface testing
- `view_alignment.py` - Code alignment viewer

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
Price data cache (Parquet files)

#### `/error_logs/`
Application error logs

### Configuration Files
- Various YAML files for:
  - Portfolio configurations
  - Risk limits
  - Industry/exchange mappings
  - Cash mappings
- `package.json` - Node.js dependencies for frontend
- `requirements.txt` - Python dependencies
- `playwright.config.js` - E2E testing configuration
- Various shell scripts for testing and deployment

### Security & Secrets

#### `/risk_module_secrets/` (163 Python files)
**CRITICAL**: Contains duplicated application code and secrets
- Appears to be a full backup/mirror of the application
- Contains sensitive configuration

6. **Security Concerns**:
   - `/risk_module_secrets/` contains sensitive data
   - Multiple backup directories with potential secrets

## File Count Summary
- Total Python files: ~560+
- Core application: ~61 files (18 root + 12 services + 9 routes + 9 utils + 7 inputs + 10 core)
- Tests: ~50+ files (expanded multi-layer testing framework)
- Archive/Backup: ~300+ files
- Frontend: Full React application (0 Python files, significantly refactored with clean architecture)
- Admin tools: 2 files

## Architecture Changes Since Last Update
### Frontend Refactoring (Major Changes):
1. **Clean Architecture Implementation**: Introduction of chassis pattern with clear separation of concerns
2. **Adapter Pattern**: New `/adapters/` directory for API data transformation
3. **View Model Pattern**: Added `/viewModels/` for presentation logic
4. **Navigation System**: New intent-based navigation system
5. **Dashboard Restructuring**: Hierarchical organization with layout, shared components, and views
6. **Enhanced State Management**: Improved store architecture and hook patterns

### Testing Framework Expansion (Major Changes):
1. **Multi-Layer Testing**: Comprehensive testing strategy across unit, integration, and E2E levels
2. **Frontend Testing Suite**: Dedicated frontend testing with Jest and React Testing Library
3. **AI-Powered Testing**: AI test orchestration and reporting system
4. **Debug Testing**: Specialized debug test scenarios
5. **Performance Testing**: Dedicated performance benchmarking
6. **User Journey Testing**: Complete end-to-end user workflow validation

## Key Integration Points
1. Database: PostgreSQL via `database_client.py`
2. External APIs: Plaid, Claude AI
3. Frontend: React with TypeScript
4. Authentication: Google OAuth integration
5. Real-time: WebSocket support for chat
