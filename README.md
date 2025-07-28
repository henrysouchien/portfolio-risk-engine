# Risk Module 🧠

**Purpose**: To help people make better investment decisions by making portfolio risk understandable and actionable through AI-powered analysis and guidance.

A comprehensive portfolio and single-stock risk analysis system that provides multi-factor regression diagnostics, risk decomposition, and portfolio optimization capabilities through a **clean 3-layer architecture** with **production-ready React dashboard interface**.

## 🚀 Features

### **🖥️ React Dashboard Interface (NEW)**
- **Interactive Risk Dashboard**: Modern React SPA with real-time portfolio analysis and visualization
- **Multiple Dashboard Views**: Risk Score, Factor Analysis, Performance Analytics, Holdings, Reports, and Settings
- **Live Data Integration**: Real-time connections to backend APIs with working data adapters
- **Responsive Design**: Mobile-friendly interface with Tailwind CSS styling
- **Chat Integration**: Built-in Claude AI assistant for conversational portfolio analysis

### **🏗️ Core Risk Analysis**
- **Multi-User Database Support**: PostgreSQL-based multi-user system with secure user isolation and session management
- **Multi-Currency Support**: Native support for USD, EUR, GBP, JPY portfolios with currency preservation
- **Multi-Factor Risk Analysis**: Understand how market forces affect your portfolio to make better allocation decisions
- **Portfolio Risk Decomposition**: See which positions drive your risk to know where to focus your risk management
- **Comprehensive Risk Scoring**: Credit-score-like rating (0-100) with detailed component analysis and historical stress testing
- **Portfolio Performance Analysis**: Calculate comprehensive performance metrics including returns, Sharpe ratio, alpha, beta, and maximum drawdown
- **Single-Stock Risk Profiles**: Analyze individual stocks to make informed buy/sell decisions
- **Risk Limit Monitoring**: Get alerts when your portfolio exceeds your risk tolerance with suggested limits

### **⚙️ System Architecture**
- **Dual-Mode Operations**: Seamless switching between file-based and database storage modes
- **Data Caching**: Fast, reliable data access for consistent analysis with 78,000x speedup
- **YAML Configuration**: Easy portfolio setup and risk limit management (portfolio.yaml, risk_limits.yaml)
- **Centralized Settings**: Consistent analysis across different portfolios

## 🏗️ Architecture Overview

### **Multi-User Database Architecture**

The Risk Module supports both file-based and database-based operations through a dual-mode architecture:

**Database Mode Features:**
- **PostgreSQL Backend**: Production-ready multi-user database with connection pooling
- **User Isolation**: Complete data separation between users with secure session management
- **Multi-Currency Support**: Native support for USD, EUR, GBP, JPY, and other currencies
- **Performance Optimization**: 9.4ms average query response time with connection pooling
- **Database-First Reference Data**: Cash, exchange, and industry mappings stored in database with YAML fallback
- **Fallback Mechanisms**: Automatic fallback to file mode when database is unavailable
- **Cash Position Mapping**: Dynamic cash position mapping with preserved currency identifiers
- **Comprehensive Testing**: 95% test coverage with performance, security, and reliability validation

**Database Schema:**
```sql
-- Users table - Multi-provider authentication support
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    tier VARCHAR(50) DEFAULT 'public',           -- 'public', 'registered', 'paid'
    
    -- Multi-provider auth support
    google_user_id VARCHAR(255) UNIQUE,          -- Google 'sub' field
    github_user_id VARCHAR(255) UNIQUE,          -- GitHub user ID
    apple_user_id VARCHAR(255) UNIQUE,           -- Apple Sign-In user ID
    auth_provider VARCHAR(50) NOT NULL DEFAULT 'google',
    
    -- API access support
    api_key_hash VARCHAR(255) UNIQUE,            -- For programmatic access
    api_key_expires_at TIMESTAMP,                -- API key expiration
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Portfolios table - Portfolio configurations with date ranges
CREATE TABLE portfolios (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    start_date DATE NOT NULL,                    -- From portfolio.yaml
    end_date DATE NOT NULL,                      -- From portfolio.yaml
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, name)
);

-- Positions table - Multi-currency position storage
-- 
-- Multi-currency design:
-- - Each position maintains its own currency (USD, EUR, GBP, etc.)
-- - Cash positions use standardized ticker format: CUR:USD, CUR:EUR, etc.
-- - No currency consolidation - each currency stored as separate position
-- - Database client extracts currency from ticker if missing (CUR:USD → USD)
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(100) NOT NULL,                -- Stock symbol or cash identifier (CUR:USD, CUR:EUR)
    quantity DECIMAL(20,8) NOT NULL,             -- Shares for stocks/ETFs, cash amount for cash positions
    currency VARCHAR(10) NOT NULL,               -- Position currency (USD, EUR, GBP, JPY, etc.)
    type VARCHAR(20),                            -- Position type: "cash", "equity", "etf", "crypto", "bond"
    
    -- Cost basis and tax tracking
    cost_basis DECIMAL(20,8),                    -- Average cost per share (NULL for cash positions)
    purchase_date DATE,                          -- For tax lot tracking
    
    -- Position metadata
    account_id VARCHAR(100),                     -- Broker account identifier
    position_source VARCHAR(50),                 -- Data source: "plaid", "manual", "csv_import", "api"
    position_status VARCHAR(20) DEFAULT 'active', -- Status: "active", "closed", "pending"
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Same ticker allowed from different sources (Plaid + manual entry)
    UNIQUE(portfolio_id, ticker, position_source)
);

-- Risk limits table - Risk tolerance configuration
CREATE TABLE risk_limits (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    portfolio_id INT REFERENCES portfolios(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,                  -- "Conservative", "Aggressive", "Custom_2024"
    
    -- Portfolio limits
    max_volatility DECIMAL(5,4),                -- portfolio_limits.max_volatility
    max_loss DECIMAL(5,4),                      -- portfolio_limits.max_loss
    
    -- Concentration limits
    max_single_stock_weight DECIMAL(5,4),       -- concentration_limits.max_single_stock_weight
    
    -- Variance limits
    max_factor_contribution DECIMAL(5,4),       -- variance_limits.max_factor_contribution
    max_market_contribution DECIMAL(5,4),       -- variance_limits.max_market_contribution
    max_industry_contribution DECIMAL(5,4),     -- variance_limits.max_industry_contribution
    
    -- Factor limits
    max_single_factor_loss DECIMAL(5,4),        -- max_single_factor_loss
    
    -- Additional settings (flexible storage)
    additional_settings JSONB,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(user_id, portfolio_id, name)
);

-- Factor proxies table - Factor model configuration
-- 
-- Risk analysis uses factor models to decompose stock returns into systematic factors.
-- Each stock gets assigned proxy ETFs for different factor exposures:
-- - market_proxy: Broad market exposure (SPY, ACWX)
-- - momentum_proxy: Momentum factor exposure (MTUM, IMTM)  
-- - value_proxy: Value factor exposure (VTV, VLUE)
-- - industry_proxy: Industry-specific exposure (XLK, XLV, etc.)
-- - subindustry_peers: Array of similar companies for peer analysis
CREATE TABLE factor_proxies (
    id SERIAL PRIMARY KEY,
    portfolio_id INT REFERENCES portfolios(id) ON DELETE CASCADE,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(100) NOT NULL,               -- Stock ticker this proxy set applies to
    market_proxy VARCHAR(20),                   -- Market factor proxy (SPY, ACWX)
    momentum_proxy VARCHAR(20),                 -- Momentum factor proxy (MTUM, IMTM)
    value_proxy VARCHAR(20),                    -- Value factor proxy (VTV, VLUE)
    industry_proxy VARCHAR(20),                 -- Industry factor proxy (XLK, XLV, XLF)
    subindustry_peers JSONB,                    -- Array of peer tickers for sub-industry analysis
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(portfolio_id, ticker)               -- One proxy set per stock per portfolio
);

-- Expected returns table - Portfolio optimization data (insert-only versioning)
-- 
-- Stores expected return forecasts for portfolio optimization.
-- Uses insert-only versioning to preserve historical expectations for backtesting.
CREATE TABLE expected_returns (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(100) NOT NULL,               -- Stock ticker
    expected_return DECIMAL(8,4) NOT NULL,      -- Annual return as decimal (0.12 = 12%)
    effective_date DATE NOT NULL,               -- When this expectation was set (for versioning)
    data_source VARCHAR(50) DEFAULT 'calculated', -- Source: 'user_input', 'calculated', 'market_data'
    confidence_level DECIMAL(3,2),             -- Confidence in forecast (0.0-1.0)
    created_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(ticker, effective_date)              -- One expectation per ticker per date
);

-- User sessions table - Session management
CREATE TABLE user_sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    last_accessed TIMESTAMP DEFAULT NOW()
);
```

**Multi-Currency Architecture:**
- **Currency Preservation**: Original cash identifiers (CUR:USD, CUR:EUR) preserved in database
- **No Consolidation**: Each currency stored as separate position, no automatic conversion
- **Position Source Tracking**: Supports multiple data sources per ticker (Plaid + manual entry)
- **Dynamic Proxy Mapping**: Cash-to-ETF mapping applied at analysis time, not storage time
- **Fallback Logic**: Automatic currency extraction from ticker format when currency field missing

**Environment Configuration:**
```bash
# Database mode (default: file mode)
USE_DATABASE=true
STRICT_DATABASE_MODE=false  # Allow fallback to file mode

# Database connection
DATABASE_URL=postgresql://user:password@localhost:5432/risk_module_db
```

### **Clean 3-Layer Architecture**

The Risk Module has been refactored from a monolithic structure into a clean, professional architecture:

```
┌─────────────────────────────────────────────────────┐
│                ROUTES LAYER                         │
│           (User Interface)                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │
│  │ CLI         │ │ API         │ │ AI Chat     │   │
│  │ run_risk.py │ │ routes/api  │ │ routes/claude│   │
│  └─────────────┘ └─────────────┘ └─────────────┘   │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│                CORE LAYER                           │
│         (Pure Business Logic)                       │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │
│  │ Portfolio   │ │ Stock       │ │ Optimization│   │
│  │ Analysis    │ │ Analysis    │ │ & Scenarios │   │
│  │ core/       │ │ core/       │ │ core/       │   │
│  └─────────────┘ └─────────────┘ └─────────────┘   │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│                DATA LAYER                           │
│         (Data Access & Storage)                     │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │
│  │ Database    │ │ Risk Engine │ │ Data        │   │
│  │ Client      │ │ portfolio_  │ │ Loading     │   │
│  │ PostgreSQL  │ │ risk.py     │ │ data_loader │   │
│  └─────────────┘ └─────────────┘ └─────────────┘   │
│                                                     │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐   │
│  │ File System │ │ Factor      │ │ Cache       │   │
│  │ YAML        │ │ Calculations│ │ Management  │   │
│  │ Storage     │ │ factor_utils│ │ 78,000x     │   │
│  └─────────────┘ └─────────────┘ └─────────────┘   │
└─────────────────────────────────────────────────────┘
```

## 🌐 Complete Interface Ecosystem

**✅ Full-Stack Integration**: Complete ecosystem with React dashboard, REST API, and AI chat integration:

### **🖥️ React Dashboard Interface**
| Dashboard View | Component | Data Source | Purpose |
|---------------|-----------|-------------|---------|
| **Risk Score** | `RiskScoreViewContainer` | `useRiskScore` hook | Interactive risk scoring with visual breakdown |
| **Factor Analysis** | `FactorAnalysisViewContainer` | `useFactorAnalysis` hook | Comprehensive factor exposure analysis |
| **Performance Analytics** | `PerformanceAnalyticsViewContainer` | `usePerformance` hook | Historical performance and benchmark comparison |
| **Holdings View** | `HoldingsViewContainer` | `usePortfolio` hook | Portfolio composition and position analysis |
| **Analysis Report** | `AnalysisReportView` | Combined data | AI-generated portfolio insights |
| **Risk Settings** | `RiskSettingsView` | Risk limits API | Risk tolerance configuration |

### **🔌 API Integration Layer**
| Analysis Type | CLI Command | API Endpoint | Dashboard Integration |
|---------------|-------------|--------------|----------------------|
| **Portfolio Risk** | `run_risk.py --portfolio` | `POST /api/analyze` | ✅ RiskScoreView |
| **Risk Score** | `portfolio_risk_score.py` | `POST /api/risk-score` | ✅ RiskScoreView |
| **Performance** | `run_risk.py --performance` | `POST /api/performance` | ✅ PerformanceAnalyticsView |
| **Factor Analysis** | Custom endpoint | `POST /api/factor-analysis` | ✅ FactorAnalysisView |
| **Holdings Data** | Portfolio data | `POST /api/portfolio-data` | ✅ HoldingsView |
| **Stock Analysis** | `run_risk.py --stock` | `POST /api/stock` | ✅ Individual stock analysis |
| **What-If Scenarios** | `run_risk.py --what-if` | `POST /api/what-if` | ✅ Scenario testing |
| **AI Interpretation** | Claude integration | `POST /api/claude_chat` | ✅ Chat panel integration |

### **🔄 Integrated Data Flow Architecture**

The system uses a unified **Hook → Adapter → Manager → API** pattern for seamless frontend-backend integration:

```
React Component → Hook → Adapter → PortfolioManager → API Endpoint → Core Business Logic
     ↓              ↓        ↓          ↓              ↓             ↓
AppContext     Data      Format    API Calls      Flask Route   Core Functions
State        Transform  Transform  Management     Response      Analysis Results
```

**Frontend Data Pipeline:**
```javascript
// React Hook Pattern
const { data, loading, error } = useRiskScore();

// Data Adapter Transformation  
const adaptedData = RiskScoreAdapter.transform(apiResponse);

// Component Integration
<RiskScoreView data={adaptedData} loading={loading} />
```

**Dual-Mode CLI/API Support:**
```python
# CLI Mode - prints formatted output
result = run_portfolio("portfolio.yaml")

# API Mode - returns structured data
result = run_portfolio("portfolio.yaml", return_data=True)
```

**Getting Started:**
```bash
# 1. Start Backend API server
python3 app.py

# 2. Start React Dashboard (in separate terminal)
cd frontend
npm install
npm start

# 3. Access Dashboard
# Open http://localhost:3000 in browser
# Login with Google OAuth
# Upload portfolio or connect Plaid account

# 4. Test API endpoints directly
python3 show_api_output.py analyze      # Complete portfolio analysis  
python3 show_api_output.py risk-score   # Risk score analysis
python3 show_api_output.py performance  # Performance metrics
python3 show_api_output.py health       # API health check

# 5. Database testing
cd tests && python3 test_comprehensive_migration.py  # Full test suite
cd tests && python3 test_performance_benchmarks.py   # Performance tests
cd tests && python3 test_user_isolation.py          # Security tests
cd tests && python3 test_fallback_mechanisms.py     # Fallback tests
```

### **Database Implementation Status**

**Production-Ready Database Migration:**
- **Core Database Engine**: PostgreSQL with connection pooling (2-5 connections)
- **User Management**: Complete user isolation with secure session handling
- **Performance Validated**: 9.4ms average query response time (10x faster than 100ms target)
- **Security Tested**: Multi-user isolation prevents cross-user data access
- **Fallback Systems**: Automatic fallback to file mode when database unavailable
- **Cash Mapping**: Dynamic cash position mapping with database storage
- **Comprehensive Testing**: 95% test coverage across performance, security, and reliability

**Database Test Suite:**
- **Performance Tests**: Database query benchmarks, connection pool efficiency, concurrent user handling
- **Security Tests**: User isolation validation, session management, data leakage prevention
- **Reliability Tests**: Fallback mechanisms, error recovery, transaction rollback
- **Integration Tests**: Cash mapping validation, batch operations, memory usage monitoring
- **Multi-Currency Tests**: Currency preservation pipeline, Plaid API → Database alignment, edge case handling

### **Architecture Documentation**

📚 **For Developers**: Detailed documentation on the dual-mode pattern and architecture:

- **[architecture.md](architecture.md)** - Complete architectural documentation  
- **[run_risk.py](run_risk.py)** - See module docstring for dual-mode pattern details

## 📊 Production Logging Infrastructure

**Comprehensive monitoring and observability system with zero-impact decorator-based logging**

### **Environment-Based Configuration**

The logging system automatically adapts to your environment:

```python
# Production (performance-optimized)
PRODUCTION_LEVELS = {
    "database": logging.ERROR,      # Only log database errors
    "portfolio": logging.WARNING,   # Only log portfolio issues
    "performance": logging.WARNING  # Only log slow operations (>1s)
}

# Development (verbose logging)
DEVELOPMENT_LEVELS = {
    "database": logging.DEBUG,      # All database operations
    "portfolio": logging.INFO,      # All portfolio operations  
    "performance": logging.INFO     # All performance metrics
}
```

Set environment with: `export ENVIRONMENT=production` or `export ENVIRONMENT=development`

### **Six Specialized Loggers**

**1. Database Logger** (`database.log`)
- SQL queries with parameters and timing
- Connection pool health monitoring
- Transaction rollback tracking
- User isolation validation

**2. Portfolio Logger** (`portfolio.log`)
- Portfolio operations and analysis timing
- Risk calculation workflow tracking
- User portfolio access patterns
- Cache hit/miss analysis

**3. API Logger** (`api.log`)
- HTTP request/response timing
- Rate limiting and authentication events
- External service health monitoring (FMP API, Plaid)
- Error categorization with severity levels

**4. Performance Logger** (`performance.log`)
- Function execution timing with thresholds
- Memory and CPU usage monitoring
- Slow operation detection and alerting
- Resource usage trend analysis

**5. Claude Logger** (`claude.log`)
- AI integration calls and token usage
- GPT response timing and success rates
- Conversation context and workflow tracking
- AI function execution monitoring

**6. Schema Logger** (`schema.log`)
- Database schema validation results
- Migration success/failure tracking
- Data integrity checks
- Reference data synchronization

### **Decorator-Based Logging System**

**Zero-impact logging** that wraps existing functions without changing business logic:

```python
# Portfolio business operations (67 usages across codebase)
@log_portfolio_operation_decorator("risk_calculation")
@log_performance(2.0)  # Log if takes longer than 2 seconds  
@log_error_handling("high")
def calculate_portfolio_risk(portfolio_data):
    # ... original function code unchanged ...
    pass

# API endpoint monitoring
@log_portfolio_operation_decorator("api_portfolio_analysis")
@log_performance(5.0)
@log_error_handling("high")
def api_analyze_portfolio():
    # ... original function code unchanged ...
    pass

# Advanced monitoring with resource tracking
@log_workflow_state_decorator("portfolio_optimization")
@log_resource_usage_decorator(monitor_memory=True, monitor_cpu=True)
@log_performance(10.0)
def optimize_portfolio(constraints):
    # ... original function code unchanged ...
    pass
```

### **Available Decorators**

| Decorator | Purpose | Usage Count | Example |
|-----------|---------|-------------|---------|
| `@log_portfolio_operation_decorator()` | Business operations | 67 | `@log_portfolio_operation_decorator("risk_calculation")` |
| `@log_performance()` | Execution timing | 57 | `@log_performance(2.0)` |
| `@log_error_handling()` | Error tracking | 81 | `@log_error_handling("high")` |
| `@log_api_health()` | External API monitoring | - | `@log_api_health("FMP_API", "stock_prices")` |
| `@log_cache_operations()` | Cache hit/miss tracking | - | `@log_cache_operations("stock_data")` |
| `@log_workflow_state_decorator()` | Multi-step workflows | - | `@log_workflow_state_decorator("optimization")` |
| `@log_resource_usage_decorator()` | Memory/CPU monitoring | - | `@log_resource_usage_decorator(monitor_memory=True)` |

### **Dual Output Format**

**Human-Readable Console Logs:**
```
2025-07-18 10:51:29,760 - api - INFO - GET stock_prices - 200 (64.9ms)
2025-07-18 10:51:29,760 - api - INFO - 🟢 FMP_API: healthy (64.9ms)
2025-07-18 10:47:53,546 - api - WARNING - ⚠️  MEDIUM ALERT: cache_operation_failed
2025-07-18 10:47:53,548 - api - ERROR - ⚠️  HIGH ALERT: function_error
```

**Structured JSON Logs:**
```json
{
  "timestamp": "2025-07-18T10:41:59.190223+00:00",
  "operation": "portfolio_analysis",
  "user_id": 123,
  "execution_time_ms": 2450.5,
  "portfolio_details": {
    "positions": 8,
    "total_value": 125000,
    "file_path": "portfolio.yaml",
    "analysis_type": "risk_calculation",
    "function_file": "run_risk.py"
  }
}
```

### **Log File Organization**

**Text Logs** (Human-readable):
```
error_logs/
├── api.log              # API requests and responses
├── portfolio.log        # Portfolio operations  
├── performance.log      # Performance metrics
├── database.log         # Database operations
├── claude.log           # AI integration
└── schema.log           # Schema validation
```

**JSON Logs** (Structured data):
```
error_logs/
├── portfolio_operations_2025-07-18.json    # Daily portfolio logs
├── performance_metrics_2025-07-18.json     # Daily performance logs
├── api_requests_2025-07-18.json            # Daily API logs
├── service_health_2025-07-18.json          # Daily service health
├── critical_alerts_2025-07-18.json         # Daily alerts
├── auth_events_2025-07-18.json             # Daily auth events
├── sql_queries_2025-07-18.json             # Daily database queries
└── resource_usage_2025-07-18.json          # Daily resource usage
```

### **Key Features**

**Production-Ready:**
- **Performance Thresholds**: Only logs slow operations in production
- **Privacy Protection**: User emails never logged (uses anonymous user IDs)
- **Automatic File Rotation**: Daily log files with date-based naming
- **Error Categorization**: Critical/High/Medium/Low severity levels

**Comprehensive Monitoring:**
- **Real-time Performance Tracking**: Function execution timing
- **External Service Health**: FMP API, Plaid, database monitoring
- **Resource Usage**: Memory and CPU monitoring
- **Multi-step Workflows**: Complete audit trail
- **Cache Analysis**: Hit/miss ratios and performance

**Developer-Friendly:**
- **Zero Code Changes**: Decorator-based with no business logic modification
- **Automatic Context**: Function names, file paths, arguments extracted
- **Stack Traces**: Full error context with recovery suggestions
- **Visual Indicators**: Emojis and status indicators for quick scanning

### **Usage Examples**

**Basic Function Logging:**
```python
from utils.logging import log_portfolio_operation_decorator, log_performance

@log_portfolio_operation_decorator("risk_calculation")
@log_performance(2.0)
def calculate_risk(portfolio_data):
    # Your existing code unchanged
    return risk_metrics
```

**Advanced Monitoring:**
```python
from utils.logging import (
    log_portfolio_operation_decorator, 
    log_performance, 
    log_error_handling,
    log_resource_usage_decorator
)

@log_error_handling("high")
@log_resource_usage_decorator(monitor_memory=True, monitor_cpu=True)
@log_performance(10.0)
def expensive_optimization(constraints):
    # Your existing code unchanged
    return optimized_portfolio
```

**API Health Monitoring:**
```python
from utils.logging import log_api_health, log_cache_operations

@log_api_health("FMP_API", "stock_prices")
@log_cache_operations("stock_data")
def fetch_stock_data(ticker):
    # Your existing code unchanged
    return stock_data
```

### **Benefits for Operations**

**Debugging & Troubleshooting:**
- Complete audit trail of all operations
- Performance bottleneck identification
- Error pattern analysis with full context
- User flow tracking for issue reproduction

**Performance Optimization:**
- Automatic slow operation detection
- Resource usage trend analysis
- Cache efficiency monitoring
- Database query performance tracking

**Production Monitoring:**
- Service health dashboards
- Alert system for critical issues
- User behavior analytics
- System resource planning

## 🌐 Frontend-to-Backend API Mapping

**React Frontend Components → Backend API Endpoints**

This comprehensive mapping shows how each frontend component connects to specific backend API endpoints:

### **Authentication Flow**
| Frontend Component | Backend API Endpoint | HTTP Method | Purpose |
|-------------------|---------------------|-------------|---------|
| `GoogleSignInButton` | `/auth/google` | POST | Google OAuth authentication |
| `LandingPage` | `/auth/status` | GET | Check authentication status |
| App component | `/auth/logout` | POST | User logout |

### **Portfolio Management**
| Frontend Component | Backend API Endpoint | HTTP Method | Purpose |
|-------------------|---------------------|-------------|---------|
| `PortfolioHoldings` | `/api/analyze` | POST | Portfolio upload and analysis |
| `RiskScoreDisplay` | `/api/risk-score` | POST | Risk score calculation and display |
| `TabbedPortfolioAnalysis` | `/api/portfolio-analysis` | POST | Comprehensive portfolio analysis |

### **Plaid Integration**
| Frontend Component | Backend API Endpoint | HTTP Method | Purpose |
|-------------------|---------------------|-------------|---------|
| `PlaidLinkButton` | `/plaid/create_link_token` | POST | Create Plaid link token |
| `PlaidLinkButton` | `/plaid/exchange_public_token` | POST | Exchange public token |
| `ConnectedAccounts` | `/plaid/connections` | GET | List connected accounts |
| `PlaidPortfolioHoldings` | `/plaid/holdings` | GET | Retrieve portfolio holdings |

### **AI Chat Integration**
| Frontend Component | Backend API Endpoint | HTTP Method | Purpose |
|-------------------|---------------------|-------------|---------|
| `chat/ChatInterface` | `/api/claude_chat` | POST | Claude AI conversations |
| `chat/ChatInterface` | `/api/claude_context` | GET | Get chat context |

### **Core API Service Layer**
The `APIService` class in `frontend/src/chassis/services/APIService.ts` provides centralized API access with these key methods:

```typescript
// Authentication APIs
checkAuthStatus(): GET /auth/status
googleAuth(token): POST /auth/google
logout(): POST /auth/logout

// Portfolio Analysis APIs
analyzePortfolio(data): POST /api/analyze
getRiskScore(): POST /api/risk-score
getPortfolioAnalysis(): POST /api/portfolio-analysis

// Plaid Integration APIs
getConnections(): GET /plaid/connections
createLinkToken(userId): POST /plaid/create_link_token
exchangePublicToken(token): POST /plaid/exchange_public_token
getPlaidHoldings(): GET /plaid/holdings

// AI Chat APIs
claudeChat(message, history): POST /api/claude_chat
```

### **Data Flow Architecture**

**Frontend → Backend Request Flow:**
```
React Component → APIService → Flask Route → Core Business Logic → Database/Files
```

**Backend → Frontend Response Flow:**
```
Database/Files → Core Business Logic → Flask Route → APIService → React Component
```

### **Response Format Standards**

**All API endpoints return consistent JSON format:**
```json
{
  "success": true,
  "data": {
    // Structured analysis data
  },
  "formatted_report": "Human-readable formatted output",
  "summary": {
    // Key metrics summary
  },
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Error Response Format:**
```json
{
  "success": false,
  "error": "Error message",
  "error_type": "validation_error|server_error|auth_error",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### **Frontend State Management**

**React Hooks for API Integration:**
- `useAuth()` - Authentication state and API calls
- `usePortfolio()` - Portfolio analysis and risk scoring
- `usePlaid()` - Plaid integration and holdings management
- `useChat()` - Claude AI chat functionality

**Key State Patterns:**
- Loading states for all API calls
- Error handling with user-friendly messages
- Automatic retry logic for failed requests
- Optimistic updates for better UX

### **Rate Limiting & Authentication**

**API Key Tiers:**
- **Public**: Limited access (5 requests/day)
- **Registered**: Enhanced access (15 requests/day) 
- **Paid**: Full access (30 requests/day)

**Frontend Authentication Flow:**
1. User signs in with Google OAuth
2. Frontend receives JWT token
3. Token included in all API requests
4. Backend validates token and applies rate limits

## 🌐 Interface Layer

For web interface, REST API, and Claude AI chat integration, see:
- **[Interface README](docs/interfaces/INTERFACE_README.md)** - User guide for REST API, Claude chat, and web interface
- **[Interface Architecture](docs/interfaces/INTERFACE_ARCHITECTURE.md)** - Technical architecture of the interface layer

## 🤖 AI Assistant Guidelines

**For AI assistants helping users with this risk module:**

**Key Functions to Know:**
- `inject_all_proxies()` - Set up factor proxies for new portfolios (required before analysis)
- `run_portfolio()` - Full portfolio analysis with risk decomposition
- `run_portfolio_performance()` - Calculate comprehensive performance metrics (returns, Sharpe ratio, alpha, beta, max drawdown)
- `run_stock()` - Single stock analysis and factor exposure
- `run_what_if()` - Scenario testing for portfolio changes
- `run_min_variance()` - Lowest risk portfolio optimization
- `run_max_return()` - Maximum return portfolio optimization
- `run_risk_score_analysis()` - Complete risk score analysis with detailed reporting

**Common User Requests:**
- "Set up a new portfolio" → Use `inject_all_proxies()` first, then `run_portfolio()`
- "Analyze my portfolio risk" → Use `run_portfolio()` function
- "Calculate portfolio performance" → Use `run_portfolio_performance()` function
- "What's my portfolio's historical return?" → Use `run_portfolio_performance()` function
- "Show me Sharpe ratio and alpha" → Use `run_portfolio_performance()` function
- "Analyze a single stock" → Use `run_stock()` function
- "What if I reduce position X?" → Use `run_what_if()` function
- "Optimize for minimum risk" → Use `run_min_variance()` function
- "Optimize for maximum return" → Use `run_max_return()` function
- "What's my risk score?" → Use `run_risk_score_analysis()` for complete analysis
- "Why is my risk score low?" → Check component breakdown in risk score analysis
- "How do I improve my portfolio?" → Review risk score recommendations and suggested limits
- "What are my risk limits?" → Use `run_risk_score_analysis()` for suggested limits

**Key Configuration Files:**
- `portfolio.yaml` - Portfolio weights and factor proxies
- `risk_limits.yaml` - Risk tolerance settings
- `settings.py` - Default parameters

**Risk Score Interpretation:**
The risk score measures "disruption risk" - how likely your portfolio is to exceed your maximum acceptable loss in various failure scenarios.

- **90-100 (Excellent)**: Very low disruption risk - all potential losses well within limits
- **80-89 (Good)**: Acceptable disruption risk - minor risk management improvements recommended
- **70-79 (Fair)**: Moderate disruption risk - some potential losses exceed limits, improvements needed
- **60-69 (Poor)**: High disruption risk - multiple losses exceed limits, significant action required
- **0-59 (Very Poor)**: Portfolio needs immediate restructuring to avoid unacceptable losses

**Component Scores:**
- **Factor Risk (35%)**: Market/value/momentum exposure vs. historical worst losses
- **Concentration Risk (30%)**: Position sizes and diversification vs. single-stock failure scenarios
- **Volatility Risk (20%)**: Portfolio volatility level vs. maximum reasonable volatility
- **Sector Risk (15%)**: Sector concentration vs. historical sector crashes

**Common Issues:**
- NaN values → Insufficient data for peer analysis
- High systematic risk → Factor variance > 30% limit
- Low risk score → Check concentration and factor exposures
- Optimization infeasible → Risk limits too restrictive

**Function Parameters:**
- `run_portfolio(filepath)` - Full portfolio analysis from YAML file
- `run_portfolio_performance(filepath)` - Calculate performance metrics from YAML file
- `run_stock(ticker, start=None, end=None, factor_proxies=None, yaml_path=None)` - Analyze single stock
- `run_what_if(filepath, scenario_yaml=None, delta=None)` - Test portfolio modifications
- `run_min_variance(filepath)` - Optimize for minimum risk from YAML file
- `run_max_return(filepath)` - Optimize for maximum return from YAML file
- `run_risk_score_analysis(portfolio_yaml="portfolio.yaml", risk_yaml="risk_limits.yaml")` - Complete risk analysis score
- `inject_all_proxies(yaml_path="portfolio.yaml", use_gpt_subindustry=False)` - Set up factor proxies

## 📊 What It Does

This risk module helps you make better investment decisions by:

1. **Portfolio Analysis**: Understanding your overall risk profile to make informed allocation decisions
2. **Portfolio Performance Analysis**: Evaluating your historical returns, risk-adjusted performance, and alpha generation
3. **Single-Stock Diagnostics**: Evaluating individual stocks to make better buy/sell choices
4. **Risk Monitoring**: Staying within your risk tolerance to avoid unpleasant surprises
5. **Data Management**: Ensuring reliable, consistent analysis for confident decision-making
6. **Configuration Management**: Maintaining consistent risk parameters across your portfolios

## 🏗️ Core Business Logic

The system's business logic has been extracted into dedicated core modules:

### **Core Modules**

- **Portfolio Analysis** (`core/portfolio_analysis.py`): Pure portfolio risk analysis logic
- **Stock Analysis** (`core/stock_analysis.py`): Individual stock factor exposure and risk analysis
- **Scenario Analysis** (`core/scenario_analysis.py`): What-if scenario testing logic
- **Optimization** (`core/optimization.py`): Portfolio optimization algorithms
- **Performance Analysis** (`core/performance_analysis.py`): Performance metrics calculation
- **Interpretation** (`core/interpretation.py`): AI-powered analysis interpretation
- **Utilities** (`utils/serialization.py`): Data serialization and formatting

### **Data Processing Components**

- **Risk Analysis Engine** (`portfolio_risk.py`): Portfolio risk calculations, performance metrics, and factor decomposition
- **Risk Scoring System** (`portfolio_risk_score.py`): Comprehensive 0-100 risk scoring with historical stress testing and disruption risk analysis
- **Factor Analytics** (`factor_utils.py`): Multi-factor regression, volatility calculations, and factor exposure analysis
- **Portfolio Optimizer** (`portfolio_optimizer.py`): Minimum variance and maximum return optimization with risk constraints
- **Stock Profiler** (`risk_summary.py`): Individual stock factor exposure and risk analysis
- **Data Integration** (`data_loader.py`): FMP API integration with intelligent caching and Treasury rate data
- **Plaid Integration** (`plaid_loader.py`): Automatic portfolio import from brokerage accounts
- **Proxy Builder** (`proxy_builder.py`): Automated factor proxy generation with GPT-powered peer analysis
- **Web Application** (`app.py`): Production Flask app with OAuth, API endpoints, and AI chat integration

## 🛠️ Installation

### Prerequisites

- Python 3.8+
- Financial Modeling Prep API key

### Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/henrysouchien/risk_module.git
   cd risk_module
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

   Or install manually:
   ```bash
   pip install pandas numpy statsmodels requests python-dotenv pyarrow streamlit pyyaml flask flask-limiter redis
   ```

3. **Configure API key**:
   Create a `.env` file in the project root:
   ```bash
   FMP_API_KEY=your_fmp_api_key_here
   ```

4. **Database Setup (Optional)**:
   For multi-user database functionality:
   ```bash
   # Install PostgreSQL
   # macOS: brew install postgresql
   # Ubuntu: sudo apt-get install postgresql
   
   # Create database
   createdb risk_module
   
   # Run schema setup
   psql risk_module < db_schema.sql
   
   # Configure environment variables
   echo "USE_DATABASE=true" >> .env
   echo "DATABASE_URL=postgresql://user:password@localhost:5432/risk_module" >> .env
   ```

## 📖 Usage

### Quick Start

1. **Set up a new portfolio**:
   ```python
   from proxy_builder import inject_all_proxies
   from run_risk import run_portfolio
   
   # Set up factor proxies for new portfolio
   inject_all_proxies("portfolio.yaml", use_gpt_subindustry=True)
   
   # Run full portfolio analysis
   run_portfolio("portfolio.yaml")
   ```

2. **Analyze existing portfolio**:
   ```python
   from run_risk import run_portfolio
   
   # Run analysis on existing portfolio.yaml
   run_portfolio("portfolio.yaml")
   ```

3. **Calculate portfolio performance**:
   ```python
   from run_risk import run_portfolio_performance
   
   # Calculate comprehensive performance metrics
   run_portfolio_performance("portfolio.yaml")
   ```

4. **API Mode - Get structured data**:
   ```python
   from run_risk import run_portfolio
   
   # Get structured data for API consumption
   result = run_portfolio("portfolio.yaml", return_data=True)
   
   # Access specific metrics
   portfolio_risk = result["portfolio_summary"]["volatility_annual"]
   factor_betas = result["portfolio_summary"]["portfolio_factor_betas"]
   ```

### Command-Line Interface

The system provides a unified command-line interface for all analysis types:

```bash
# Portfolio risk analysis
python run_risk.py --portfolio portfolio.yaml

# Portfolio performance analysis
python run_risk.py --portfolio portfolio.yaml --performance

# Comprehensive risk score analysis (0-100 with detailed reporting)
python -c "from portfolio_risk_score import run_risk_score_analysis; run_risk_score_analysis()"

# Single stock analysis
python run_risk.py --stock AAPL

# What-if scenario analysis
python run_risk.py --portfolio portfolio.yaml --whatif

# Portfolio optimization
python run_risk.py --portfolio portfolio.yaml --minvar    # Minimum variance
python run_risk.py --portfolio portfolio.yaml --maxreturn # Maximum return
```

### Portfolio Analysis

Run a complete portfolio risk analysis:

```python
from run_risk import run_portfolio

# Full portfolio analysis with risk decomposition
run_portfolio("portfolio.yaml")
```

This will:
- Load portfolio configuration from `portfolio.yaml`
- Fetch market data for all securities
- Perform multi-factor regression analysis
- Calculate portfolio risk metrics
- Generate comprehensive risk report

### Comprehensive Risk Score Analysis

Get a credit-score-like rating (0-100) for your portfolio with detailed analysis:

```python
from portfolio_risk_score import run_risk_score_analysis

# Complete risk score analysis with detailed reporting
results = run_risk_score_analysis("portfolio.yaml", "risk_limits.yaml")

# The analysis provides:
# - Overall risk score (0-100) with category (Excellent/Good/Fair/Poor/Very Poor)
# - Component scores for factor, concentration, volatility, and sector risks
# - Detailed risk limit violations and specific recommendations
# - Suggested risk limits based on your loss tolerance
# - Historical worst-case scenario analysis
```

This comprehensive analysis will:
- Calculate your portfolio's disruption risk vs. your maximum acceptable loss
- Break down risk into four components: factor (35%), concentration (30%), volatility (20%), sector (15%)
- Identify specific risk limit violations with actionable recommendations
- Suggest appropriate risk limits based on your risk tolerance
- Use historical worst-case scenarios for realistic stress testing
- Provide color-coded, credit-score-like reporting for easy interpretation

### Portfolio Performance Analysis

Calculate comprehensive performance metrics:

```python
from run_risk import run_portfolio_performance

# Calculate performance metrics (returns, Sharpe ratio, alpha, beta, max drawdown)
run_portfolio_performance("portfolio.yaml")
```

This will:
- Load portfolio configuration from the YAML file
- Calculate historical returns and volatility
- Compute risk-adjusted performance metrics (Sharpe ratio, Sortino ratio)
- Analyze performance vs benchmark (alpha, beta, tracking error)
- Display professional performance report with insights

### Single Stock Analysis

Analyze individual stock risk profile:

```python
from run_risk import run_stock

# Single stock analysis
run_stock("AAPL")  # Analyze Apple stock
```

### New Portfolio Setup

For new portfolios, set up factor proxies first:

```python
from proxy_builder import inject_all_proxies

# Set up factor proxies (required for new portfolios)
inject_all_proxies(use_gpt_subindustry=True)
```

### Configuration

#### Default Settings (`settings.py`)

Centralized default configuration for the risk module:

```python
PORTFOLIO_DEFAULTS = {
    "start_date": "2019-01-31",
    "end_date": "2025-06-27",
    "normalize_weights": False,  # Global default for portfolio weight normalization
    "worst_case_lookback_years": 10  # Historical lookback period for worst-case scenario analysis
}
```

These defaults are used when specific dates aren't provided in portfolio configurations.

### Weight Normalization Behavior

**Default**: `normalize_weights = False` (Raw weights represent true economic exposure)

**Key Behavior**:
- **Risk Analysis**: Uses raw weights to calculate true portfolio risk exposure
- **Portfolio Display**: Shows "Raw Weights" when `False`, "Normalized Weights" when `True`
- **Leverage Calculation**: No double-counting of leverage when using raw weights
- **Optimization Functions**: Always normalize weights internally for mathematical stability

**When to Use Each Setting**:
- **`normalize_weights = False`** (Default): When portfolio weights represent actual dollar exposures, including leverage and short positions
- **`normalize_weights = True`**: When portfolio weights need to be normalized to sum to 1.0 for display or analysis purposes

**Example**:
```python
# Raw weights (default) - represents true economic exposure
portfolio = {
    "NVDA": 0.50,   # 50% long position
    "SGOV": -0.08,  # 8% short position (creates leverage)
    "SPY": 0.30     # 30% long position
}
# Net: 72%, Gross: 88%, Leverage: 1.22x

# Risk calculations use these raw weights directly
# No leverage double-counting in risk calculations
```

#### Date Logic and Calculation Windows

The risk module uses a consistent date system across all calculations:

**Primary Portfolio System:**
- **Source**: Dates are read from `portfolio.yaml` (`start_date` and `end_date`)
- **Usage**: All portfolio risk calculations, factor regressions, and optimizations use this window
- **Consistency**: Ensures all calculations use the same historical period for accurate comparisons

**Fallback System:**
- **Default**: `PORTFOLIO_DEFAULTS` from `settings.py` when portfolio dates aren't specified
- **Proxy Generation**: GPT peer generation and validation use portfolio dates for consistency
- **Data Quality**: Peer filtering ensures all tickers have sufficient observations within the date window

**Independent Analysis:**
- **Single Stock**: `run_stock()` uses flexible dates (5-year default or explicit parameters)
- **Historical Analysis**: `calc_max_factor_betas()` uses `worst_case_lookback_years` (default: 10 years) for worst-case scenarios
- **Purpose**: These functions serve different use cases and appropriately use different date logic

**Historical Worst-Case Analysis:**
- **Lookback Period**: Uses `worst_case_lookback_years` setting (default: 10 years) ending today
- **Purpose**: Calculates maximum allowable risk exposure based on historical worst-case factor performance
- **Independence**: This analysis window is separate from portfolio analysis dates to ensure consistent risk benchmarks

**Calculation Alignment:**
- All factor calculations (market, momentum, value, industry) use the same date window
- Peer median returns are calculated over the same period as the target ticker
- Regression windows are consistent across all securities in the portfolio
- Data quality validation ensures stable factor betas by preventing insufficient observation windows

#### Portfolio Configuration (`portfolio.yaml`)

```yaml
start_date: "2019-05-31"
end_date: "2024-03-31"

portfolio_input:
  TW:   {weight: 0.15}
  MSCI: {weight: 0.15}
  NVDA: {weight: 0.17}
  # ... more positions

expected_returns:
  TW: 0.15
  MSCI: 0.16
  # ... expected returns for each position

stock_factor_proxies:
  TW:
    market: SPY
    momentum: MTUM
    value: IWD
    industry: KCE
    subindustry: [TW, MSCI, NVDA]
  # ... factor proxies for each position
```

#### Risk Limits (`risk_limits.yaml`)

```yaml
portfolio_limits:
  max_volatility: 0.40
  max_loss: -0.25

concentration_limits:
  max_single_stock_weight: 0.40

variance_limits:
  max_factor_contribution: 0.30
  max_market_contribution: 0.30
  max_industry_contribution: 0.30
```

## 📈 Output Examples

### Comprehensive Risk Score Report

The comprehensive risk score analysis provides a credit-score-like report with:

- **Overall Risk Score (0-100)**: Single number measuring disruption risk with clear category (Excellent/Good/Fair/Poor/Very Poor)
- **Component Breakdown**: Detailed scores for factor risk (35%), concentration risk (30%), volatility risk (20%), and sector risk (15%)
- **Risk Interpretation**: Color-coded assessment with specific explanations of what each score means
- **Actionable Recommendations**: Specific suggestions for improving your portfolio risk profile
- **Limit Violations**: Detailed analysis of which risk limits are being exceeded and by how much
- **Suggested Risk Limits**: Backwards-calculated appropriate limits based on your maximum acceptable loss
- **Historical Context**: Stress testing based on actual historical worst-case scenarios

### Portfolio Risk Summary

The system generates actionable risk insights including:

- **Volatility Analysis**: Understand your portfolio's risk level to make informed allocation decisions
- **Factor Exposures**: See your market bets to decide if you want to hedge or adjust exposures
- **Risk Decomposition**: Identify what's driving your risk to focus your management efforts
- **Concentration Analysis**: Check your diversification to decide if you need more positions
- **Risk Limit Monitoring**: Stay within your comfort zone to avoid unpleasant surprises

### Portfolio Performance Summary

The system generates comprehensive performance metrics to help you evaluate your investment strategy:

- **Return Analysis**: Total returns, annualized returns, and monthly performance tracking
- **Risk-Adjusted Metrics**: Sharpe ratio, Sortino ratio, and Information ratio for risk-adjusted performance evaluation
- **Benchmark Comparison**: Alpha, beta, and tracking error analysis vs SPY benchmark
- **Drawdown Analysis**: Maximum drawdown, recovery periods, and downside risk assessment
- **Win Rate Analysis**: Percentage of positive months and best/worst performance periods
- **Professional Insights**: Automated performance quality assessment and recommendations

### Single Stock Profile

Individual stock analysis helps you make better buy/sell decisions by providing:

- **Factor Regression**: Understand how market forces affect this stock to make informed decisions
- **Risk Metrics**: See the stock's risk profile to decide if it fits your portfolio
- **Factor Contributions**: Identify what's driving the stock's performance to assess its role
- **Peer Comparison**: Compare against similar stocks to make better relative value decisions

## 🔧 Advanced Usage

### Custom Factor Models

You can customize factor models by modifying the `stock_factor_proxies` section in `portfolio.yaml`:

```yaml
stock_factor_proxies:
  YOUR_STOCK:
    market: SPY          # Market factor proxy
    momentum: MTUM       # Momentum factor proxy
    value: IWD          # Value factor proxy
    industry: KCE       # Industry factor proxy
    subindustry: [PEER1, PEER2, PEER3]  # Sub-industry peers
```

### Data Quality Validation

The system includes robust data quality validation to ensure you get reliable insights for confident decision-making:

- **Individual Ticker Validation**: Ensures each stock has enough data for accurate risk assessment
- **Peer Group Validation**: Prevents unreliable comparisons that could lead to bad decisions
- **Automatic Filtering**: Removes problematic data so you can trust the analysis
- **Stable Factor Betas**: Ensures risk metrics are reliable for making allocation decisions

This validation ensures that your risk analysis is trustworthy, so you can make decisions with confidence.

### Risk Limit Customization

Set your risk tolerance in `risk_limits.yaml` to get alerts when your portfolio exceeds your comfort zone:

```yaml
portfolio_limits:
  max_volatility: 0.35    # Maximum portfolio volatility you're comfortable with
  max_loss: -0.20         # Maximum loss you can tolerate

concentration_limits:
  max_single_stock_weight: 0.25  # Maximum single position size for diversification
```

## 🛡️ Risk Management Framework

### Risk Limits Framework

The risk management system uses a comprehensive framework of limits designed to control portfolio risk across multiple dimensions. These limits are based on fundamental risk management principles and protect against various types of portfolio losses.

#### Core Risk Limit Categories

**1. Overall Portfolio Risk Limits**

- **Volatility Limit (40%)**: Control total portfolio risk and align with risk tolerance
- **Loss Limit (-25%)**: Set maximum acceptable portfolio loss and define risk budget

**2. Concentration Risk Limits**

- **Single-Stock Weight Limit (40%)**: "Limit risk from errors" - prevent single-stock blowups
- **Herfindahl Index Monitoring**: Measure portfolio concentration (target: < 0.15)

**3. Factor Risk Exposure Limits**

- **Factor Variance Contribution (30%)**: Control systematic risk exposure
- **Market Variance Contribution (50%)**: Control market beta exposure
- **Industry Variance Contribution (30%)**: Prevent sector concentration

**4. Factor Beta Limits**

- **Market Beta Limit (0.77)**: Derived from loss limit ÷ worst market loss
- **Momentum Beta Limit (0.79)**: Control momentum factor exposure
- **Value Beta Limit (0.55)**: Control value factor exposure
- **Industry Beta Limits (Varies)**: Each industry has different volatility characteristics

#### Risk Limit Setting Process

1. **Define Risk Tolerance**: Set maximum acceptable portfolio loss and volatility tolerance
2. **Calculate Factor Limits**: Analyze historical factor performance and derive beta limits
3. **Set Variance Limits**: Determine acceptable systematic risk exposure
4. **Monitor and Adjust**: Regularly review limit breaches and adjust as needed

#### Interpreting Limit Breaches

- **PASS**: Portfolio meets risk limit
- **FAIL**: Portfolio exceeds risk limit, action required
- **Risk Score Impact**: Limit breaches reduce overall risk score
- **Action Recommendations**: Specific guidance for each type of breach

### Risk Scoring Framework

The portfolio risk score provides a comprehensive 0-100 rating that evaluates portfolio risk across multiple dimensions. Similar to a credit score, it combines various risk metrics into a single actionable number with clear categories and recommendations.

#### Risk Score Components

The risk score is calculated using four main components:

1. **Portfolio Volatility (30% weight)**: Based on actual volatility vs. limit
2. **Concentration Risk (20% weight)**: Based on max weight and Herfindahl Index
3. **Factor Exposure Risk (25% weight)**: Average score across all factor betas
4. **Systematic Risk (25% weight)**: Based on factor variance contribution vs. limit

#### Risk Score Categories

| Score Range | Category | Description | Action Required |
|-------------|----------|-------------|-----------------|
| **90-100** | **Excellent** | Very low risk portfolio | Monitor and maintain |
| **80-89** | **Good** | Low risk portfolio | Minor adjustments may be needed |
| **70-79** | **Fair** | Moderate risk portfolio | Consider risk reduction |
| **60-69** | **Poor** | High risk portfolio | Significant action recommended |
| **0-59** | **Very Poor** | Very high risk portfolio | Immediate action required |

#### Scoring Methodology

**Portfolio Volatility Score (30%)**
- Score 100: Volatility ≤ 50% of limit (very low risk)
- Score 80: Volatility ≤ 75% of limit (low risk)
- Score 60: Volatility ≤ 90% of limit (moderate risk)
- Score 40: Volatility ≤ 100% of limit (high risk)
- Score 0: Volatility > limit (over limit)

**Concentration Risk Score (20%)**
- **Max Weight Component**: Based on largest position vs. limit
- **Herfindahl Index Component**: Score = max(0, 100 - (HHI × 100))
- **Combined Score**: Weighted average with bonus for good concentration

**Factor Exposure Risk Score (25%)**
- **Calculation**: Average score across all factor betas
- **Factors Evaluated**: Market, momentum, value, and industry betas
- **Scoring**: Based on beta vs. respective limits

**Systematic Risk Score (25%)**
- **Calculation**: Based on factor variance contribution vs. limit
- **Linear Penalty**: For exceeding limits using formula: `max(0, 40 - 80 × (factor_var_ratio - 1.0))`

#### Action Recommendations

**For Poor/Very Poor Scores (0-69)**
- Identify primary risk factors from score breakdown
- Reduce largest positions if concentration is high
- Add defensive positions if volatility is high
- Diversify sectors if systematic risk is high
- Consider portfolio optimization (min variance or max return)

**For Fair Scores (70-79)**
- Target specific weaknesses from component scores
- Gradual position adjustments (don't make dramatic changes)
- Add diversification with new positions in different sectors
- Review risk tolerance to ensure limits match strategy

**For Good/Excellent Scores (80-100)**
- Regular monitoring and monthly reviews
- Rebalancing to maintain target weights
- Risk limit review to ensure limits remain appropriate
- Performance tracking to ensure risk-adjusted returns

#### Integration with Portfolio Management

- **Risk Score Updates**: Monthly or after significant changes
- **Decision Making**: Use risk score to guide new positions, sizing, and rebalancing
- **Reporting**: Include risk score and breakdown in client reports and management reviews
- **Customization**: Adjust component weights and thresholds for different strategies

## 📐 Mathematical Reference

### Portfolio Volatility & Risk

**Portfolio Volatility**
```
σ_p = √(w^T Σ w)
```
*Function: `compute_portfolio_volatility()`*
**Purpose**: Measures how much your portfolio can swing up or down, helping you understand if the risk level matches your comfort zone and timeline.

**Risk Contributions**
```
RC_i = w_i × (Σw)_i / σ_p
```
*Function: `compute_risk_contributions()`*
**Purpose**: Shows which positions are driving your portfolio's risk, helping you decide which stocks to reduce if you need to lower overall risk.

**Herfindahl Index (Concentration)**
```
H = Σ(w_i²)
```
*Function: `compute_herfindahl()`*
**Purpose**: Measures how diversified your portfolio is, helping you decide if you're over-concentrated in too few positions and need to add more holdings.

### Factor Analysis

**Factor Beta**
```
β_i,f = Cov(r_i, r_f) / Var(r_f)
```
*Function: `compute_stock_factor_betas()`*
**Purpose**: Shows how sensitive your stocks are to market forces (like tech sector moves or value vs growth trends), helping you understand if you're taking unintended bets.

**Portfolio Factor Beta**
```
β_p,f = Σ(w_i × β_i,f)
```
*Function: `build_portfolio_view()`*
**Purpose**: Shows your overall exposure to market factors, helping you decide if you want to hedge certain exposures or if you're comfortable with your current market bets.

**Excess Return**
```
r_excess = r_etf - r_market
```
*Function: `fetch_excess_return()`*
**Purpose**: Measures how much a factor (like momentum or value) moves independently of the market, helping you understand if you're getting compensated for taking factor-specific risk.

### Variance Decomposition

**Total Portfolio Variance**
```
σ²_p = σ²_factor + σ²_idiosyncratic
```
**Purpose**: Breaks down your portfolio's risk into what you can control (stock selection) vs. what you can't (market factors), helping you focus your risk management efforts.

**Factor Variance**
```
σ²_factor = Σ(w_i² × β_i,f² × σ_f²)
```
*Function: `compute_portfolio_variance_breakdown()`*
**Purpose**: Shows how much of your risk comes from market factors you can't control, helping you decide if you need to hedge or if you're comfortable with systematic risk exposure.

**Idiosyncratic Variance**
```
σ²_idio = Σ(w_i² × σ²_idio,i)
```
**Purpose**: Shows how much of your risk comes from individual stock choices, helping you decide if you need more diversification or if your stock selection is adding value.

**Euler Variance Contribution**
```
VC_i = w_i × (Σw)_i / Σ(w_i × (Σw)_i)
```
*Function: `compute_euler_variance_percent()`*
**Purpose**: Shows which positions contribute most to your portfolio's ups and downs, helping you identify where to focus your risk management efforts.

### Volatility Calculations

**Annualized Volatility**
```
σ_annual = σ_monthly × √12
```
*Function: `compute_volatility()`*
Monthly volatility scaled to annual basis using square root of time rule.

**Monthly Returns**
```
r_t = (P_t - P_{t-1}) / P_{t-1}
```
*Function: `calc_monthly_returns()`*
Percentage change in price from one month-end to the next.

### Optimization Constraints

**Portfolio Variance Constraint**
```
w^T Σ w ≤ σ_max²
```
Maximum allowable portfolio volatility constraint for risk management.

**Factor Beta Constraint**
```
|Σ(w_i × β_i,f)| ≤ β_max,f
```
**Purpose**: Limits your exposure to market factors to prevent taking too much systematic risk.

**Weight Constraint**
```
0 ≤ w_i ≤ w_max
```
**Purpose**: Prevents over-concentration in single positions to maintain proper diversification.

## 🌐 Complete Web Application Stack

### React Dashboard Frontend (`frontend/`)

**Modern React SPA with Professional UI/UX:**
- **Interactive Dashboard**: Six comprehensive views (Risk Score, Factor Analysis, Performance, Holdings, Reports, Settings)
- **Real-Time Data**: Live API integration with working data adapters and error handling
- **Responsive Design**: Mobile-friendly interface built with Tailwind CSS
- **Performance Optimized**: Hybrid loading strategy with lazy loading and background preloading
- **Chat Integration**: Built-in Claude AI assistant panel for conversational analysis
- **State Management**: Zustand store with AppContext integration

### Flask Backend API (`app.py`)

**Production-Ready Flask Application (3,000+ lines):**
- **Google OAuth Authentication**: Secure user management and session handling
- **Plaid Integration**: Automatic portfolio import from brokerage accounts
- **Claude AI Chat**: Interactive risk analysis assistance and natural language queries
- **RESTful API**: Multiple endpoints for portfolio analysis and risk scoring
- **Rate Limiting**: Tiered access control with fair usage policies
- **Admin Dashboard**: Usage tracking, cache management, and system monitoring
- **Export Functionality**: Download analysis results and portfolio reports

**Access Tiers:**
- **Public**: Limited daily usage (5 analyses/day)
- **Registered**: Enhanced limits (15 analyses/day) + Google OAuth access
- **Paid**: Full access (30 analyses/day) + priority support

**API Endpoints:**

| Endpoint | Returns | Purpose |
|----------|---------|---------|
| `POST /api/analyze` | Structured data + formatted report | Complete portfolio risk analysis |
| `POST /api/risk-score` | Structured data + formatted report | Risk score calculation (0-100) |
| `POST /api/performance` | Structured data + formatted report | Performance metrics (returns, Sharpe, alpha, beta) |
| `POST /api/portfolio-analysis` | GPT interpretation + analysis | AI-powered portfolio analysis |
| `POST /api/claude_chat` | AI conversation | Interactive risk analysis assistant |
| `GET /plaid/holdings` | Portfolio data | Import from brokerage accounts |
| `GET /api/health` | System status | API health check |

**Key Features:**
- **Dual Output Format**: Every analysis endpoint returns both structured JSON data AND human-readable formatted reports
- **Complete Parity**: API provides same analysis as CLI with identical output
- **Real-time Analysis**: Fresh analysis with current market data

**Usage:**
```bash
# Start the web server
python app.py

# Test API endpoints with structured data + formatted reports
python3 show_api_output.py analyze        # Complete portfolio analysis
python3 show_api_output.py risk-score     # Risk score analysis  
python3 show_api_output.py performance    # Performance metrics

# API usage example
curl -X POST http://localhost:5001/api/performance?key=paid_key_789 \
  -H "Content-Type: application/json" \
  -d '{}'
```

## 🔗 Additional Integrations

### Plaid Financial Data Integration (`plaid_loader.py`)

Automatically import your portfolio data from your brokerage accounts to save time and ensure accuracy:

**Features:**
- **Multi-Institution Support**: Connect all your brokerage accounts in one place
- **Automatic Holdings Import**: Get your current positions without manual entry
- **Cash Position Mapping**: Properly account for cash positions in your risk analysis
- **AWS Secrets Management**: Keep your financial data secure and private
- **Portfolio YAML Generation**: Convert your holdings to the right format automatically

**Supported Institutions:**
- Interactive Brokers
- Other Plaid-supported brokerages

**Usage:**
```python
from plaid_loader import convert_plaid_df_to_yaml_input

# Convert Plaid holdings to portfolio.yaml
convert_plaid_df_to_yaml_input(
    holdings_df,
    output_path="portfolio.yaml",
    dates={"start_date": "2020-01-01", "end_date": "2024-12-31"}
)
```

### **Database-First Architecture**

The system now uses a **database-first approach with YAML fallback** for both user configurations and reference data:

**User Configuration Tables:**
- `users` - User management and multi-provider authentication
- `portfolios` - User portfolios with date ranges and metadata
- `positions` - Portfolio positions with multi-currency support
- `risk_limits` - User-specific risk tolerance settings
- `factor_proxies` - Factor model configurations per portfolio
- `scenarios` - What-if scenarios and portfolio alternatives
- `user_sessions` - Secure session management
- `user_preferences` - User settings and AI context

**Reference Data Tables:**
- `cash_proxies` - Currency to ETF proxy mappings (USD → SGOV)
- `cash_aliases` - Broker-specific cash identifiers (CUR:USD → USD)
- `exchange_proxies` - Exchange to factor proxy mappings (NASDAQ → SPY/MTUM/IWD)
- `industry_proxies` - Industry to ETF mappings (Technology → XLK)

**Architecture:**
```
Database (Primary) → YAML Fallback → Hard-coded Defaults
```

**Benefits:**
- **Multi-User Support**: Complete user isolation with secure session management
- **Operational Flexibility**: Add new brokerages and configurations without code deployment
- **Reliability**: Automatic fallback to YAML files if database unavailable
- **Auditability**: Database tracks all changes with timestamps and user attribution
- **Scalability**: Handles concurrent access and transactions (10/10 users successful)
- **Performance**: 9.4ms average query time with connection pooling

**Management:**
```bash
# Reference data management
python admin/manage_reference_data.py cash add EUR ESTR
python admin/manage_reference_data.py cash-alias add "CUR:EUR" EUR
python admin/manage_reference_data.py exchange add LSE market EFA
python admin/manage_reference_data.py industry add "Financial Services" XLF

# User configuration management (via database)
# - User portfolios stored in database with complete isolation
# - Risk limits managed per user/portfolio
# - Scenarios and preferences tracked per user
# - Session management handles multi-user concurrent access

# List current mappings
python admin/manage_reference_data.py cash list
python admin/manage_reference_data.py exchange list
python admin/manage_reference_data.py industry list
```

**Code Integration:**
```python
# System automatically loads from database with YAML fallback
from inputs.database_client import DatabaseClient
from inputs.portfolio_manager import PortfolioManager

# Multi-user portfolio management
portfolio_manager = PortfolioManager(use_database=True, user_id="user_123")
portfolio_data = portfolio_manager.load_portfolio_data("main_portfolio")

# Reference data with fallback
db_client = DatabaseClient()
cash_map = db_client.get_cash_mappings()        # Falls back to cash_map.yaml
exchange_map = db_client.get_exchange_mappings()  # Falls back to exchange_etf_proxies.yaml
industry_map = db_client.get_industry_mappings()  # Falls back to industry_to_etf.yaml

# User-specific risk limits
risk_limits = db_client.get_risk_limits(user_id="user_123", portfolio_id=1)
```

**YAML Files (Development & Fallback):**
- `portfolio.yaml` - Local portfolio configuration (development/testing)
- `risk_limits.yaml` - Local risk limits configuration (development/testing)
- `cash_map.yaml` - Cash position mapping (database fallback)
- `industry_to_etf.yaml` - Industry classification mapping (database fallback)
- `exchange_etf_proxies.yaml` - Exchange-specific factor proxies (database fallback)
- `what_if_portfolio.yaml` - What-if scenario configurations

## 🧪 Testing

The system includes several ways to test your portfolio analysis:

```python
from run_risk import run_portfolio, run_portfolio_performance, run_stock, run_what_if, run_min_variance, run_max_return
from portfolio_risk_score import run_risk_score_analysis

# 1. Full portfolio analysis
run_portfolio("portfolio.yaml")

# 2. Portfolio performance analysis
run_portfolio_performance("portfolio.yaml")

# 3. Single stock analysis
run_stock("AAPL", start="2020-01-01", end="2024-12-31")

# 4. What-if scenario testing
run_what_if("portfolio.yaml", delta="AAPL:-500bp,SGOV:+500bp")

# 5. Portfolio optimization
run_min_variance("portfolio.yaml")  # Minimum risk portfolio
run_max_return("portfolio.yaml")    # Maximum return portfolio

# 6. Risk scoring
results = run_risk_score_analysis("portfolio.yaml", "risk_limits.yaml")
```

### **Multi-Currency Pipeline Testing**

The system includes comprehensive multi-currency validation:

**Pipeline Validation:**
- **Currency Preservation**: Verifies original cash identifiers (CUR:USD, CUR:EUR) are preserved in database
- **No Consolidation**: Confirms each currency is stored as separate position without automatic conversion
- **Edge Case Handling**: Tests fallback logic for missing currency data with appropriate warnings
- **Multi-Source Support**: Validates multiple data sources per ticker (Plaid + manual entry)
- **Database Alignment**: Ensures Plaid API → Database pipeline maintains currency integrity

**Test Scenarios:**
- **Multi-Currency Portfolios**: AAPL (USD), ASML (EUR), CUR:USD, CUR:EUR, CUR:GBP, CUR:JPY
- **Currency Extraction**: Automatic currency detection from ticker format (CUR:USD → USD)
- **Fallback Logic**: Warning system for edge cases like 'CASH_EUR', 'GBPCASH' formats
- **Database Persistence**: Validates currency preservation across database save/load cycles

Each provides actionable insights to help you make better investment decisions.

## 📁 Complete Project Structure

### Core Analysis Engine
```
risk_module/
├── portfolio_risk.py           # Portfolio risk calculations and performance metrics
├── portfolio_risk_score.py     # 0-100 risk scoring with detailed analysis
├── factor_utils.py             # Multi-factor regression and volatility calculations
├── risk_summary.py             # Single-stock risk profiling
├── portfolio_optimizer.py      # Portfolio optimization algorithms
└── risk_helpers.py             # Risk calculation utilities
```

### Database Infrastructure
```
├── inputs/
│   ├── database_client.py      # PostgreSQL client with connection pooling and multi-currency support
│   ├── portfolio_manager.py    # Dual-mode portfolio operations (file/database)
│   ├── exceptions.py           # Database-specific exceptions and error handling
│   └── auth_service.py         # User authentication and session management
├── db_schema.sql               # Comprehensive database schema with multi-currency support
└── migrations/                 # Database migration scripts
```

### Data & Integration Layer
```
├── data_loader.py              # API integration with intelligent caching
├── plaid_loader.py             # Plaid brokerage integration (29KB)
├── proxy_builder.py            # Factor proxy generation and GPT peer integration
└── gpt_helpers.py              # AI assistant integration
```

### Entry Points & Runners
```
├── run_risk.py                 # Main command-line interface and entry points
├── run_portfolio_risk.py       # Portfolio analysis runner with display utilities
└── run_risk_summary_to_gpt_dev.py # GPT interpretation runner
```

### Web Application
```
├── app.py                      # Flask web application (3,156 lines)
│                               # • Google OAuth authentication
│                               # • Plaid integration endpoints
│                               # • Claude AI chat interface
│                               # • RESTful API with rate limiting
│                               # • Admin dashboard and monitoring
└── frontend/                   # Frontend assets (if applicable)
```

### Configuration Files
```
├── portfolio.yaml              # Portfolio positions and factor proxies
├── risk_limits.yaml            # Risk tolerance and limit settings
├── settings.py                 # Default system configuration
├── db_schema.sql               # Database schema with reference data tables
├── admin/                      # Reference data management tools
│   ├── manage_reference_data.py # CLI tool for managing cash, exchange, industry mappings
│   └── README.md               # Reference data management guide
├── cash_map.yaml               # Cash position mapping (YAML fallback)
├── industry_to_etf.yaml        # Industry classification mapping (YAML fallback)
├── exchange_etf_proxies.yaml   # Exchange-specific factor proxies (YAML fallback)
└── what_if_portfolio.yaml      # What-if scenario configurations
```

### Utilities & Helpers
```
├── helpers_display.py          # Output formatting and display utilities
├── helpers_input.py            # Input processing and validation utilities
└── update_secrets.sh           # Secrets synchronization script
```

### Integrated Frontend-Backend Architecture
```
├── 📊 Core Risk Engine (Backend Data Layer)
│   ├── portfolio_risk.py              # Portfolio risk calculations (32KB)
│   ├── portfolio_risk_score.py        # Risk scoring system (53KB)
│   ├── factor_utils.py                # Factor analysis utilities (8KB)
│   ├── risk_summary.py                # Single-stock risk profiling (4KB)
│   ├── portfolio_optimizer.py         # Portfolio optimization (36KB)
│   ├── data_loader.py                 # Data fetching and caching (8KB)
│   ├── proxy_builder.py               # Factor proxy generation (19KB)
│   ├── plaid_loader.py                # Plaid brokerage integration (29KB)
│   ├── gpt_helpers.py                 # GPT integration (4KB)
│   └── risk_helpers.py                # Risk calculation helpers (8KB)
│
├── 📁 inputs/ (Backend Data Management)
│   ├── portfolio_manager.py           # Portfolio operations
│   ├── risk_config.py                 # Risk limits management
│   ├── returns_calculator.py          # Returns estimation
│   └── file_manager.py                # File operations
│
├── 📁 services/ (Backend AI Services)
│   ├── claude/
│   │   ├── function_executor.py       # 14 Claude functions (618 lines)
│   │   └── chat_service.py            # Claude conversation orchestration
│   └── portfolio/
│       └── context_service.py         # Portfolio caching (374 lines)
│
├── 📁 routes/ (Backend API Layer)
│   ├── api.py                         # Core API endpoints
│   ├── claude.py                      # Claude chat endpoint
│   ├── plaid.py                       # Plaid integration endpoints
│   ├── auth.py                        # Authentication endpoints
│   └── admin.py                       # Admin endpoints
│
├── 📁 frontend/ (React Dashboard Frontend)
│   ├── src/
│   │   ├── components/
│   │   │   ├── dashboard/             # Main dashboard components
│   │   │   │   ├── DashboardApp.jsx   # Main dashboard orchestrator
│   │   │   │   ├── layout/            # Layout components (Header, Sidebar, Chat)
│   │   │   │   ├── views/             # Dashboard views (Risk, Factor, Performance, etc.)
│   │   │   │   └── shared/            # Shared UI components and charts
│   │   │   ├── auth/                  # Authentication components
│   │   │   ├── chat/                  # Claude AI chat integration
│   │   │   └── plaid/                 # Plaid integration components
│   │   ├── chassis/                   # Frontend infrastructure
│   │   │   ├── hooks/                 # React hooks (useRiskScore, useFactorAnalysis, etc.)
│   │   │   ├── services/              # API services (APIService, frontendLogger)
│   │   │   ├── managers/              # Frontend managers (PortfolioManager, AuthManager)
│   │   │   └── context/               # React context (AppContext)
│   │   ├── adapters/                  # Data transformation adapters
│   │   │   ├── RiskScoreAdapter.ts    # Risk score data transformation
│   │   │   ├── FactorAnalysisAdapter.ts # Factor analysis data transformation
│   │   │   └── PerformanceAdapter.ts  # Performance data transformation
│   │   └── store/                     # State management (Zustand)
│   └── package.json                   # Frontend dependencies
```

### Documentation & Development Tools
```
├── README.md                   # Main project documentation (this file)
├── architecture.md             # Detailed technical architecture (1,000+ lines)
├── docs/                       # Comprehensive documentation
│   ├── interfaces/             # Interface alignment documentation
│   ├── planning/               # Architecture and planning docs
│   ├── WEB_APP.md             # Web application API reference
│   └── API_REFERENCE.md       # Detailed API documentation
├── tools/                      # Development utilities
│   ├── view_alignment.py       # Interface alignment viewer
│   ├── check_dependencies.py   # Dependency impact analysis
│   └── test_all_interfaces.py  # Interface testing suite
├── requirements.txt            # Python dependencies
├── LICENSE                     # MIT License
└── .env                       # Environment variables (API keys, secrets)
```

### Testing Infrastructure
```
├── tests/
│   ├── test_comprehensive_migration.py  # Master test suite runner
│   ├── test_performance_benchmarks.py   # Database performance validation
│   ├── test_user_isolation.py          # Multi-user security testing
│   ├── test_fallback_mechanisms.py     # Database fallback validation
│   ├── test_cash_mapping_validation.py # Cash position mapping tests
│   ├── test_database_connections.py    # Database connectivity tests
│   └── test_results/                   # Test results and reports
```

### Data & Cache Directories
```
├── cache_prices/              # Cached price data (gitignored)
├── exports/                   # Analysis export files
├── error_logs/                # System error logs
├── templates/                 # Web application templates
└── Archive/                   # Historical files and backups
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🔗 Dependencies

- **pandas**: Data manipulation and analysis
- **numpy**: Numerical computing
- **statsmodels**: Statistical modeling and regression
- **requests**: HTTP library for API calls
- **python-dotenv**: Environment variable management
- **pyarrow**: Parquet file handling for caching
- **streamlit**: Web dashboard framework
- **pyyaml**: YAML configuration file handling
- **flask**: Web application framework
- **flask-limiter**: Rate limiting for web API
- **redis**: Caching and session management
- **psycopg2**: PostgreSQL database adapter
- **SQLAlchemy**: Database ORM and connection pooling
- **pytest**: Testing framework for database validation

## 🆘 Support

For questions or issues:

1. Check the `architecture.md` file for detailed technical documentation
2. Review the example configurations in `portfolio.yaml` and `risk_limits.yaml`
3. Open an issue on GitHub with detailed error information

## 🚀 Completed Integration & Future Enhancements

### **✅ Completed Features**
- [X] **React Dashboard Interface** ✅ **COMPLETED** - Full production-ready dashboard with 6 comprehensive views
- [X] **Frontend-Backend Integration** ✅ **COMPLETED** - Working data adapters, hooks, and real-time API connections
- [X] **AI-powered conversational interface** ✅ **COMPLETED** - Claude AI chat integration with dashboard context
- [X] **GPT-powered peer suggestion system** ✅ **COMPLETED**
- [X] **Support for cash exposure and short positions** ✅ **COMPLETED**
- [X] **Web dashboard interface** ✅ **COMPLETED** - Modern React SPA with professional UI/UX
- [X] **Plaid financial data integration** ✅ **COMPLETED**
- [X] **Interactive risk attribution visualization** ✅ **COMPLETED** - Comprehensive charts and visual components
- [X] **AI-powered portfolio recommendations** ✅ **COMPLETED** - Integrated chat assistant with portfolio analysis

### **🚀 Future Enhancements**
- [ ] Real-time risk monitoring and alerts based on volatility
- [ ] Additional factor models (quality, size, etc.) for more comprehensive analysis
- [ ] Backtesting capabilities to validate investment decisions
- [ ] Portfolio comparison tools (current vs. suggested vs. historical)
- [ ] Advanced portfolio optimization with multiple objectives
- [ ] Mobile app for iOS/Android
- [ ] Advanced charting and technical analysis
- [ ] Social features for portfolio sharing and comparison

---

**Built with ❤️ for quantitative risk analysis**