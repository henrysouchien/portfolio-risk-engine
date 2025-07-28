# 🧠 Risk Module Architecture Documentation

This document provides a comprehensive overview of the Risk Module's architecture, design principles, and technical implementation details for the **complete integrated system** with production-ready React dashboard interface.

## 📋 Table of Contents

- [System Overview](#system-overview)
- [Dual-Mode Interface Pattern](#dual-mode-interface-pattern)
- [Architecture Layers](#architecture-layers)
- [Data Flow](#data-flow)
- [Component Details](#component-details)
- [Configuration Management](#configuration-management)
- [Caching Strategy](#caching-strategy)
- [Risk Calculation Framework](#risk-calculation-framework)
- [API Integration](#api-integration)
- [Performance Considerations](#performance-considerations)
- [Testing Strategy](#testing-strategy)
- [Future Enhancements](#future-enhancements)

## 🎯 System Overview

The Risk Module is a comprehensive full-stack application combining a modular Python backend with a production-ready React frontend. It provides multi-factor regression diagnostics, risk decomposition, and portfolio optimization capabilities through a **clean 3-layer architecture** with **multi-user database support** and **integrated dashboard interface** that promotes maintainability, testability, and extensibility.

### Architecture Transformation

**BEFORE**: Monolithic `run_risk.py` (1217 lines) mixing CLI, business logic, and formatting
**AFTER**: Clean layered architecture with extracted business logic and single source of truth

### Data Quality Assurance

The system includes robust data quality validation to prevent unstable factor calculations. A key improvement addresses the issue where insufficient peer data could cause extreme factor betas (e.g., -58.22 momentum beta) by limiting regression windows to only 2 observations instead of the full available data.

**Problem Solved**: The `filter_valid_tickers()` function now ensures that subindustry peers have ≥ target ticker's observations, preventing regression window limitations and ensuring stable factor betas.

### Core Design Principles

- **Single Source of Truth**: All interfaces (CLI, API, AI) use the same core business logic
- **Dual-Mode Architecture**: Every function supports both CLI and API modes seamlessly
- **Dual-Storage Architecture**: Seamless switching between file-based and database storage
- **Clean Separation**: Routes handle UI, Core handles business logic, Data handles persistence
- **100% Backward Compatibility**: Existing code works identically
- **Enterprise-Ready**: Professional architecture suitable for production deployment

### Database Architecture

**Multi-User Database Support:**
The Risk Module implements a comprehensive multi-user database system with PostgreSQL backend:

**Database Components:**
- **Database Client** (`inputs/database_client.py`): Connection pooling, query execution, transaction management
- **Multi-Currency Support** (`inputs/database_client.py`): Currency extraction and position mapping
- **User Management** (`services/auth_service.py`): Authentication, session handling, user isolation
- **Portfolio Manager** (`inputs/portfolio_manager.py`): Dual-mode portfolio operations (file/database)
- **Exception Handling** (`inputs/exceptions.py`): Database-specific error handling and recovery

**Performance Characteristics:**
- **Query Performance**: 9.4ms average response time (10x faster than 100ms target)
- **Connection Pooling**: 2-5 connections with automatic scaling
- **Concurrent Users**: 100% success rate with 10+ simultaneous users
- **Memory Efficiency**: 0.0MB per user memory overhead
- **Cache Integration**: 78,000x speedup for repeated queries

**Security Features:**
- **User Isolation**: Complete data separation between users
- **Session Management**: Secure session tokens with expiration
- **Data Validation**: Input sanitization and SQL injection prevention
- **Fallback Mechanisms**: Automatic fallback to file mode when database unavailable

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

-- Factor proxies table - Factor model configuration
-- 
-- Risk analysis uses factor models to decompose stock returns into systematic factors.
-- Each stock gets assigned proxy ETFs for different factor exposures for factor regression:
-- Stock_Return = α + β₁*Market + β₂*Momentum + β₃*Value + β₄*Industry + ε
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

**Database Client Features:**
- **Connection Pooling**: Automatic connection management with 2-5 connections
- **Transaction Safety**: ACID compliance with rollback on failure
- **Currency Extraction**: Automatic currency detection from ticker format (CUR:USD → USD)
- **Multi-Source Support**: Same ticker from different sources (Plaid + manual entry)
- **Data Validation**: Input sanitization and constraint enforcement

### Interface Layer

For web interface, REST API, and Claude AI chat integration, see:
- **[Interface README](docs/interfaces/INTERFACE_README.md)** - User guide for REST API, Claude chat, and web interface
- **[Interface Architecture](docs/interfaces/INTERFACE_ARCHITECTURE.md)** - Technical architecture of the interface layer

## 🔄 Dual-Mode Interface Pattern

A critical architectural pattern that enables **multiple consumer types** (CLI, API, Claude AI) to access the same core business logic with **guaranteed output consistency**.

### The Challenge

The system must support three fundamentally different consumption patterns:
- **CLI Users**: `python run_risk.py --portfolio portfolio.yaml` → formatted text output
- **API Clients**: `POST /api/portfolio-analysis` → structured JSON data
- **Claude AI**: `run_portfolio_analysis()` → human-readable formatted reports

### The Solution: Dual-Mode Functions

All primary analysis functions in `run_risk.py` support both **CLI mode** (default) and **API mode** (`return_data=True`):

```python
def run_portfolio(filepath: str, *, return_data: bool = False):
    """Portfolio analysis with dual-mode support.
    
    CLI Mode (default):
        Prints formatted analysis to stdout for terminal users
        
    API Mode (return_data=True):
        Returns structured data + formatted report for programmatic use
    """
    # Single source of truth for business logic
    portfolio_summary = build_portfolio_view(...)
    risk_checks = analyze_risk_limits(...)
    
    if return_data:
        # API/Service Layer: Return structured data + formatted report
        return {
            "portfolio_summary": portfolio_summary,
            "risk_analysis": risk_checks,
            "formatted_report": formatted_output,  # Same text as CLI
            "analysis_metadata": metadata
        }
    else:
        # CLI: Print formatted output directly
        print(formatted_output)
```

### Benefits

1. **Consistency Guarantee**: CLI and API use identical business logic and formatting
2. **Single Maintenance Point**: One function serves all consumers
3. **Performance**: No JSON parsing overhead for CLI users
4. **Type Safety**: Service layer gets structured data for programmatic use

### Usage Patterns

**CLI Usage:**
```bash
python run_risk.py --portfolio portfolio.yaml
# Prints formatted analysis to terminal
```

**Service Layer Usage:**
```python
from run_risk import run_portfolio

# Get structured data + formatted report
result = run_portfolio("portfolio.yaml", return_data=True)
portfolio_vol = result["portfolio_summary"]["volatility_annual"]
human_report = result["formatted_report"]
```

**Claude AI Usage:**
```python
# Claude Function Executor calls service layer
result = portfolio_service.analyze_portfolio(portfolio_data)
claude_sees = result.to_formatted_report()  # Same text as CLI
```

### Dual-Mode Functions

All major analysis functions follow this pattern:
- `run_portfolio()` - Portfolio risk analysis
- `run_what_if()` - Scenario analysis  
- `run_min_variance()` / `run_max_return()` - Portfolio optimization
- `run_stock()` - Individual stock analysis
- `run_portfolio_performance()` - Performance metrics

## 🏗️ Architecture Layers

The system follows a **clean 3-layer architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────┐
│                    LAYER 1: ROUTES LAYER                     │
│                    (User Interface)                          │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ CLI Interface   │  │ API Interface   │  │ AI Interface │ │
│  │ run_risk.py     │  │ routes/api.py   │  │ routes/      │ │
│  │ (CLI Commands)  │  │ (REST API)      │  │ claude.py    │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ Services Layer  │  │ Web Frontend    │  │ Admin Tools  │ │
│  │ services/       │  │ frontend/       │  │ routes/      │ │
│  │ (Orchestration) │  │ (React SPA)     │  │ admin.py     │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│                    LAYER 2: CORE LAYER                      │
│                 (Pure Business Logic)                       │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ Portfolio       │  │ Stock Analysis  │  │ Optimization │ │
│  │ Analysis        │  │ core/stock_     │  │ core/        │ │
│  │ core/portfolio_ │  │ analysis.py     │  │ optimization.│ │
│  │ analysis.py     │  │                 │  │ py           │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ Scenario        │  │ Performance     │  │ Interpretation│ │
│  │ Analysis        │  │ Analysis        │  │ core/        │ │
│  │ core/scenario_  │  │ core/performance│  │ interpretation│ │
│  │ analysis.py     │  │ _analysis.py    │  │ .py          │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────┐
│                    LAYER 3: DATA LAYER                      │
│                 (Data Access & Storage)                     │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ Risk Engine     │  │ Portfolio       │  │ Data Loading │ │
│  │ portfolio_risk. │  │ Optimization    │  │ data_loader. │ │
│  │ py              │  │ portfolio_      │  │ py           │ │
│  │ (Factor Models) │  │ optimizer.py    │  │ (FMP API)    │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ Stock Profiler  │  │ Factor Utils    │  │ Utilities    │ │
│  │ risk_summary.py │  │ factor_utils.py │  │ utils/       │ │
│  │ (Stock Analysis)│  │ (Math/Stats)    │  │ serialization│ │
│  │                 │  │                 │  │ .py          │ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

### Key Architectural Benefits

1. **Single Source of Truth**: All interfaces call the same core business logic
2. **Dual-Mode Support**: Every function works in both CLI and API modes
3. **Clean Separation**: Routes handle UI, Core handles logic, Data handles persistence
4. **Perfect Compatibility**: Existing code works identically
5. **Enterprise Architecture**: Professional structure suitable for production

## 🔄 Data Flow Architecture

### User Request Flow
```
1. User Input
   ├── CLI: "python run_risk.py --portfolio portfolio.yaml"
   ├── API: "POST /api/analyze"
   └── AI: "Analyze my portfolio risk"
   
2. Routes Layer
   ├── run_portfolio() in run_risk.py
   ├── api_analyze_portfolio() in routes/api.py
   └── claude_chat() in routes/claude.py
   
3. Core Layer (Business Logic)
   ├── analyze_portfolio() in core/portfolio_analysis.py
   ├── analyze_scenario() in core/scenario_analysis.py
   └── analyze_stock() in core/stock_analysis.py
   
4. Data Layer
   ├── build_portfolio_view() in portfolio_risk.py
   ├── run_what_if_scenario() in portfolio_optimizer.py
   └── get_stock_risk_profile() in risk_summary.py
   
5. Response
   ├── CLI: Formatted console output
   ├── API: JSON structured data
   └── AI: Natural language interpretation
```

### Dual-Mode Architecture Pattern

Every function in the system supports both CLI and API modes:

```python
def run_portfolio(filepath: str, *, return_data: bool = False):
    """
    Dual-mode portfolio analysis function.
    
    CLI Mode (return_data=False):
    - Prints formatted output to console
    - Returns simple values for CLI use
    
    API Mode (return_data=True):
    - Returns structured JSON-serializable data
    - Suitable for API consumption
    """
    # Call extracted core business logic
    analysis_result = analyze_portfolio(filepath)
    
    # Dual-mode response handling
    if return_data:
        # API Mode: Return structured data
        return analysis_result
    else:
        # CLI Mode: Print formatted output
        print_portfolio_summary(analysis_result)
        return None
```

## 📂 File Structure

### Complete Architecture Directory Structure

```
risk_module/
├── 📄 Readme.md                    # Main project documentation
├── 📄 architecture.md              # Technical architecture (this file)
├── ⚙️ settings.py                  # Default configuration settings
├── 🔧 app.py                       # Flask web application
├── 🔒 update_secrets.sh            # Secrets synchronization script
├── 📋 requirements.txt             # Python dependencies
├── 📜 LICENSE                      # MIT License
│
├── 📊 LAYER 1: ROUTES LAYER (User Interface)
│   ├── 🖥️ run_risk.py                  # CLI interface (832 lines)
│   ├── 📁 routes/                      # API interfaces
│   │   ├── api.py                      # REST API endpoints (669 lines)
│   │   ├── claude.py                   # Claude AI chat interface (128 lines)
│   │   ├── plaid.py                    # Plaid integration (254 lines)
│   │   ├── auth.py                     # Authentication (124 lines)
│   │   └── admin.py                    # Admin interface (134 lines)
│   ├── 📁 services/                    # Service orchestration
│   │   ├── portfolio_service.py        # Portfolio analysis service (382 lines)
│   │   ├── stock_service.py            # Stock analysis service (130 lines)
│   │   ├── scenario_service.py         # Scenario analysis service (270 lines)
│   │   └── optimization_service.py     # Optimization service (194 lines)
│   └── 📁 frontend/                    # Web frontend
│       └── src/App.js                  # React SPA (1,477 lines)
│
├── 📊 LAYER 2: CORE LAYER (Pure Business Logic)
│   ├── 📁 core/                        # Extracted business logic
│   │   ├── portfolio_analysis.py       # Portfolio analysis logic (116 lines)
│   │   ├── stock_analysis.py           # Stock analysis logic (133 lines)
│   │   ├── scenario_analysis.py        # Scenario analysis logic (157 lines)
│   │   ├── optimization.py             # Optimization logic (180 lines)
│   │   ├── performance_analysis.py     # Performance analysis logic (115 lines)
│   │   └── interpretation.py           # AI interpretation logic (109 lines)
│   └── 📁 utils/                       # Utility functions
│       └── serialization.py            # JSON serialization utilities
│
├── 📊 LAYER 3: DATA LAYER (Data Access & Storage)
│   ├── 💼 portfolio_risk.py            # Portfolio risk calculations (32KB)
│   ├── 📈 portfolio_risk_score.py      # Risk scoring system (53KB)
│   ├── 📊 factor_utils.py              # Factor analysis utilities (8KB)
│   ├── 📋 risk_summary.py              # Single-stock risk profiling (4KB)
│   ├── ⚡ portfolio_optimizer.py        # Portfolio optimization (36KB)
│   ├── 🔌 data_loader.py               # Data fetching and caching (8KB)
│   ├── 🗃️ database_client.py           # PostgreSQL client with connection pooling
│   ├── 🤖 gpt_helpers.py               # GPT integration (4KB)
│   ├── 🔧 proxy_builder.py             # Factor proxy generation (19KB)
│   ├── 🏦 plaid_loader.py              # Plaid brokerage integration (29KB)
│   └── 🛠️ risk_helpers.py              # Risk calculation helpers (8KB)
│
├── 📁 Configuration Files
│   ├── ⚙️ portfolio.yaml              # Portfolio configuration
│   ├── ⚙️ risk_limits.yaml            # Risk limit definitions
│   ├── 🗃️ db_schema.sql               # Database schema with reference data tables
│   ├── 🛠️ admin/                      # Reference data management tools
│   │   ├── manage_reference_data.py   # CLI tool for managing mappings
│   │   └── README.md                  # Reference data management guide
│   ├── 🗺️ cash_map.yaml               # Cash position mapping (YAML fallback)
│   ├── 🏭 industry_to_etf.yaml        # Industry classification mapping (YAML fallback)
│   ├── 📊 exchange_etf_proxies.yaml   # Exchange-specific proxies (YAML fallback)
│   └── 🔧 what_if_portfolio.yaml      # What-if scenarios
│
├── 📁 docs/ (Documentation)
│   ├── interfaces/
│   │   ├── INTERFACE_README.md         # Interface documentation
│   │   └── INTERFACE_ARCHITECTURE.md   # Interface architecture
│   ├── API_REFERENCE.md               # API documentation
│   ├── WEB_APP.md                     # Web application guide
│   └── README.md                      # Documentation index
│
├── 📁 tests/ (Testing)
│   ├── test_service_layer.py          # Service layer tests
│   ├── test_dual_mode.py              # Dual-mode functionality tests
│   └── test_core_extraction.py        # Core business logic tests
│
└── 📁 tools/ (Utilities)
    ├── view_alignment.py              # Terminal alignment viewer
    ├── check_dependencies.py          # Dependency impact analysis
    └── test_all_interfaces.py         # Interface testing suite
```

## 🎯 Core Business Logic Extraction

### Before: Monolithic Structure
```python
# run_risk.py (1217 lines)
def run_portfolio(filepath):
    # Load configuration (20 lines)
    # Build portfolio view (30 lines)
    # Calculate risk metrics (40 lines)
    # Check limits (25 lines)
    # Format output (30 lines)
    # Print results (20 lines)
    # Handle dual-mode (10 lines)
```

### After: Clean Layered Structure
```python
# run_risk.py (Routes Layer)
def run_portfolio(filepath, *, return_data=False):
    # Call extracted core business logic
    analysis_result = analyze_portfolio(filepath)
    
    # Dual-mode response handling
    if return_data:
        return analysis_result  # API mode
    else:
        print_portfolio_summary(analysis_result)  # CLI mode
        return None

# core/portfolio_analysis.py (Core Layer)
def analyze_portfolio(filepath):
    # Pure business logic - no UI concerns
    # 1. Load configuration
    # 2. Build portfolio view
    # 3. Calculate risk metrics
    # 4. Check limits
    # 5. Return structured data
    return structured_results
```

## 🔄 Technical Implementation Details

### Dual-Mode Pattern Implementation

Every function maintains dual-mode behavior:

```python
def run_portfolio(filepath: str, *, return_data: bool = False):
    """
    Dual-mode portfolio analysis function.
    
    Parameters
    ----------
    filepath : str
        Path to portfolio YAML file
    return_data : bool, default False
        If True, returns structured data instead of printing
        If False, prints formatted output to stdout
    
    Returns
    -------
    None or Dict[str, Any]
        If return_data=False: Returns None, prints formatted output
        If return_data=True: Returns structured data dictionary
    """
    # Business logic: Call extracted core function
    analysis_result = analyze_portfolio(filepath)
    
    # Dual-mode logic
    if return_data:
        # API Mode: Return structured data
        return analysis_result
    else:
        # CLI Mode: Print formatted output
        print_portfolio_summary(analysis_result)
        return None
```

### Data Handling Strategy

- **Structured Data**: JSON-safe for API consumption
- **Raw Objects**: Preserved for CLI compatibility
- **Formatted Reports**: Generated for user-friendly output

### Business Logic Extraction

All core business logic has been extracted to dedicated modules:

| Original Function | Extracted Module | Purpose |
|-------------------|------------------|---------|
| `run_portfolio()` | `core/portfolio_analysis.py` | Portfolio risk analysis |
| `run_what_if()` | `core/scenario_analysis.py` | What-if scenario analysis |
| `run_min_variance()` | `core/optimization.py` | Minimum variance optimization |
| `run_max_return()` | `core/optimization.py` | Maximum return optimization |
| `run_stock()` | `core/stock_analysis.py` | Individual stock analysis |
| `run_portfolio_performance()` | `core/performance_analysis.py` | Performance metrics |
| `run_and_interpret()` | `core/interpretation.py` | AI interpretation services |

## 🔧 Component Details

### 1. Data Layer (`data_loader.py`)

**Purpose**: Efficient data retrieval with intelligent caching

**Key Functions**:
- `fetch_monthly_close()`: FMP API integration with caching
- `cache_read()`: Multi-level caching (RAM → Disk → Network)
- `cache_write()`: Force cache updates

**Features**:
- Automatic cache invalidation
- Compressed parquet storage
- MD5-based cache keys
- Error handling and retry logic
- Treasury rate integration for risk-free rates

**Caching Strategy**:
```
RAM Cache (LRU) → Disk Cache (Parquet) → Network (FMP API)
```

**Treasury Rate Integration**:
The system now uses professional-grade risk-free rates from the FMP Treasury API instead of ETF price movements:
- `get_treasury_rate_from_fmp()`: Core function to fetch 3-month Treasury rates from FMP API
- `fetch_monthly_treasury_rates()`: Retrieves historical Treasury yields with date filtering
- Proper date range filtering for historical analysis aligned with portfolio periods
- Cache-enabled for performance with monthly resampling
- Eliminates contamination from bond price fluctuations in rate calculations
- Integrated into `calculate_portfolio_performance_metrics()` for accurate Sharpe ratio calculations

### 2. Factor Analysis (`factor_utils.py`)

**Purpose**: Multi-factor regression and risk calculations

**Key Functions**:
- `compute_volatility()`: Rolling volatility calculations
- `compute_regression_metrics()`: Single-factor regression
- `compute_factor_metrics()`: Multi-factor regression
- `compute_stock_factor_betas()`: Factor exposure calculation
- `calc_factor_vols()`: Factor volatility estimation
- `calc_weighted_factor_variance()`: Portfolio factor variance

**Statistical Methods**:
- Ordinary Least Squares (OLS) regression
- Rolling window calculations
- Robust error handling
- R-squared and significance testing

### 3. Portfolio Risk Engine (`portfolio_risk.py`)

**Purpose**: Portfolio-level risk decomposition and analysis

**Key Functions**:
- `normalize_weights()`: Weight standardization (used only in optimization functions)
- `compute_portfolio_returns()`: Portfolio return calculation
- `compute_covariance_matrix()`: Risk matrix construction
- `compute_portfolio_volatility()`: Portfolio volatility
- `compute_risk_contributions()`: Risk attribution
- `calculate_portfolio_performance_metrics()`: Comprehensive performance analysis

**Weight Normalization Behavior**:
- **Default**: `normalize_weights = False` in `PORTFOLIO_DEFAULTS` (raw weights represent true economic exposure)
- **Risk Analysis**: Uses raw weights to calculate true portfolio risk exposure without leverage double-counting
- **Optimization**: Always normalizes weights internally for mathematical stability
- **Display**: Shows "Raw Weights" vs "Normalized Weights" based on setting

### 4. Portfolio Performance Engine (`portfolio_risk.py`)

**Purpose**: Portfolio performance metrics and risk-adjusted return analysis

**Key Functions**:
- `calculate_portfolio_performance_metrics()`: Calculate returns, Sharpe ratio, alpha, beta, max drawdown
- `get_treasury_rate_from_fmp()`: Fetch 3-month Treasury rates from FMP API with error handling
- `fetch_monthly_treasury_rates()`: Retrieve historical Treasury rates with caching and date filtering

**Features**:
- Historical return analysis with proper compounding
- Risk-adjusted performance metrics (Sharpe, Sortino, Information ratios)
- Benchmark comparison (alpha, beta, tracking error)
- Drawdown analysis and recovery periods
- Professional risk-free rate integration using Treasury yields
- Comprehensive display formatting with automated insights
- Win rate and best/worst month analysis

**Performance Metrics Calculated**:
- Total and annualized returns
- Volatility (annual standard deviation)
- Maximum drawdown and recovery analysis
- Sharpe ratio (excess return per unit of risk)
- Sortino ratio (downside risk-adjusted returns)
- Information ratio (tracking error-adjusted alpha)
- Alpha and beta vs benchmark (SPY)
- Tracking error and correlation analysis
- `compute_herfindahl()`: Concentration analysis
- `build_portfolio_view()`: Comprehensive risk summary

**Risk Metrics**:
- Portfolio volatility
- Factor exposures
- Risk contributions
- Variance decomposition
- Concentration measures

### 4. Single Stock Profiler (`risk_summary.py`)

**Purpose**: Individual stock risk analysis and factor profiling

**Key Functions**:
- `get_stock_risk_profile()`: Basic risk metrics
- `get_detailed_stock_factor_profile()`: Comprehensive analysis
- Factor regression diagnostics
- Peer comparison analysis

**Analysis Components**:
- Multi-factor regression
- Factor beta calculation
- Idiosyncratic risk estimation
- Factor contribution analysis

### 5. Data Quality Validation (`proxy_builder.py`)

**Purpose**: Ensures data quality and prevents unstable factor calculations

**Key Functions**:
- `filter_valid_tickers()`: Validates ticker data quality and peer group consistency
- `get_subindustry_peers_from_ticker()`: GPT-generated peer selection with validation
- `inject_subindustry_peers_into_yaml()`: Peer injection with quality checks

**Validation Criteria**:
- **Individual Ticker**: ≥3 price observations for returns calculation
- **Peer Group**: Each peer must have ≥ target ticker's observations
- **Regression Stability**: Prevents extreme factor betas from insufficient data
- **Automatic Filtering**: Removes problematic peers during proxy generation

**Benefits**:
- Prevents regression window limitations
- Ensures stable factor betas
- Maintains data consistency across factors
- Automatic quality control for GPT-generated peers

### 5. AI Services Layer (`services/`)

**Purpose**: AI-powered portfolio analysis and conversational interface

#### Claude Function Executor (`services/claude/function_executor.py`)
**1367 lines of sophisticated AI function integration**

**Portfolio Analysis Functions (4)**:
- `create_portfolio_scenario()`: Create new portfolio configurations
- `run_portfolio_analysis()`: Complete portfolio risk analysis with database-first architecture
- `setup_new_portfolio()`: Generate factor proxies for user's portfolio
- `calculate_portfolio_performance()`: Performance metrics and benchmarking

**Risk Analysis Functions (1)**:
- `get_risk_score()`: Portfolio risk scoring with detailed breakdown

**Optimization Functions (2)**:
- `optimize_minimum_variance()`: Minimum variance optimization
- `optimize_maximum_return()`: Maximum return optimization

**Scenario Analysis Functions (1)**:
- `run_what_if_scenario()`: Portfolio modification testing

**Stock Analysis Functions (1)**:
- `analyze_stock()`: Single stock analysis with factor decomposition

**Returns Management Functions (2)**:
- `estimate_expected_returns()`: Estimate returns for user's stock universe
- `set_expected_returns()`: Set returns for user's portfolio

**Risk Management Functions (3)**:
- `view_current_risk_limits()`: Show risk limits for user
- `update_risk_limits()`: Update user's risk limit settings
- `reset_risk_limits()`: Reset risk limits to default values
- `save_portfolio_yaml()`: Portfolio configuration persistence
- `load_portfolio_yaml()`: Portfolio configuration loading
- `update_portfolio_weights()`: Weight modification
- `validate_portfolio_config()`: Configuration validation

**Returns Management Functions (3)**:
- `estimate_expected_returns()`: Historical returns estimation
- `set_expected_returns()`: Manual returns configuration
- `update_portfolio_expected_returns()`: Returns persistence

**Risk Management Functions (5)**:
- `view_current_risk_limits()`: Risk limits inspection
- `update_risk_limits()`: Risk tolerance modification
- `reset_risk_limits()`: Risk limits reset to defaults
- `validate_risk_limits()`: Risk configuration validation
- `get_risk_score()`: Comprehensive risk assessment

**File Management Functions (4)**:
- `list_portfolios()`: Portfolio file listing
- `backup_portfolio()`: Portfolio backup creation
- `restore_portfolio()`: Portfolio restoration
- `delete_portfolio()`: Portfolio file deletion

**Features**:
- Natural language interface for all risk analysis functions
- Automatic parameter validation and error handling
- GPT-powered interpretation of results
- Seamless integration with core risk engine
- Context-aware responses based on portfolio state

#### Portfolio Context Service (`services/portfolio/context_service.py`)
**374 lines of portfolio caching and context management**

**Key Functions**:
- `cache_portfolio_context()`: Portfolio state caching
- `get_portfolio_context()`: Context retrieval for conversations
- `update_portfolio_context()`: Context updates after modifications
- `clear_portfolio_context()`: Context cleanup

**Features**:
- Redis-based portfolio state caching
- Context persistence across conversations
- Automatic context updates after portfolio modifications
- Performance optimization for repeated analysis

### 6. Data Management Layer (`inputs/`)

**Purpose**: Specialized modules for data operations and configuration management (Layer 2)

The inputs layer provides a clean abstraction for all data management operations, serving as the foundation for the entire system.

#### Portfolio Manager (`inputs/portfolio_manager.py`)
**Portfolio configuration and operations**

**Key Functions**:
- `create_portfolio_yaml()`: Create new portfolio configurations
- `load_yaml_config()`: Load and validate portfolio configurations
- `save_yaml_config()`: Persist portfolio configurations
- `update_portfolio_weights()`: Modify portfolio positions
- `create_what_if_yaml()`: Generate scenario configurations
- `validate_portfolio_config()`: Portfolio validation and error checking

**Features**:
- YAML configuration management
- Portfolio weight normalization (optional, default: False)
- Data validation and error handling
- Scenario generation for what-if analysis
- Backup and versioning support

#### Risk Configuration Manager (`inputs/risk_config.py`)
**Risk limits and tolerance management**

**Key Functions**:
- `view_current_risk_limits()`: Display current risk tolerance settings
- `update_risk_limits()`: Modify risk tolerance parameters
- `reset_risk_limits()`: Reset to default risk settings
- `validate_risk_limits()`: Risk configuration validation
- `calculate_risk_metrics()`: Risk calculation utilities

**Features**:
- Risk limit validation and enforcement
- Default risk tolerance management
- Risk metric calculation support
- Configuration backup and recovery
- Integration with risk scoring system

#### Returns Calculator (`inputs/returns_calculator.py`)
**Expected returns estimation and management**

**Key Functions**:
- `estimate_historical_returns()`: Calculate historical expected returns
- `update_portfolio_expected_returns()`: Update portfolio return expectations
- `set_expected_returns()`: Manual return specification
- `validate_return_assumptions()`: Return validation and reasonableness checks
- `calculate_risk_adjusted_returns()`: Risk-adjusted return calculations

**Features**:
- Historical return analysis
- Return assumption validation
- Risk-adjusted return calculations
- Integration with portfolio optimization
- Return forecasting utilities

#### File Manager (`inputs/file_manager.py`)
**File operations and data persistence**

**Key Functions**:
- `load_yaml_config()`: Universal YAML configuration loader
- `save_yaml_config()`: Universal YAML configuration saver
- `backup_portfolio()`: Portfolio backup creation
- `restore_portfolio()`: Portfolio restoration from backup
- `list_portfolios()`: Portfolio file discovery
- `delete_portfolio()`: Safe portfolio deletion

**Features**:
- Universal configuration file handling
- Backup and recovery operations
- File validation and error handling
- Directory management and organization
- Integration with all system components

#### Layer 2 Architecture Benefits

**1. Data Abstraction**:
- Clean separation between data operations and business logic
- Consistent data access patterns across all interfaces
- Centralized data validation and error handling

**2. Configuration Management**:
- Unified approach to YAML configuration handling
- Validation and error checking for all data inputs
- Backup and recovery capabilities

**3. Interface Foundation**:
- Provides consistent data operations for all 4 interfaces
- Ensures data integrity across CLI, API, Claude, and Frontend
- Enables rapid interface development through reusable components

**4. System Integration**:
- Seamless integration with Core Risk Engine (Layer 1)
- Supports AI Services (Layer 3) with clean data access
- Enables Web Interface (Layer 4) and Frontend (Layer 5)

### 7. Execution Layer

**Portfolio Runner** (`run_portfolio_risk.py`):
- End-to-end portfolio analysis
- Configuration validation
- Error handling and reporting
- Output formatting

**Single Stock Runner** (`run_single_stock_profile.py`):
- Individual stock diagnostics
- Factor model validation
- Detailed regression analysis

**Risk Runner** (`run_risk.py`):
- Flexible risk analysis entry point
- What-if scenario testing
- Batch processing capabilities

## ⚙️ Configuration Management

### Default Settings (`settings.py`)

**Purpose**: Centralized default configuration management

**Structure**:
```python
PORTFOLIO_DEFAULTS = {
    "start_date": "2019-01-31",
    "end_date": "2025-06-27",
    "normalize_weights": False,  # Global default for portfolio weight normalization
    "worst_case_lookback_years": 10  # Historical lookback period for worst-case scenario analysis
}
```

**Usage**:
- Provides sensible defaults for portfolio analysis
- Used when specific dates aren't provided in YAML configurations
- Centralizes configuration to avoid hardcoded values throughout the codebase
- Easy to modify for different analysis periods

**Integration**:
```python
from settings import PORTFOLIO_DEFAULTS

# Use defaults when not specified
start_date = config.get('start_date', PORTFOLIO_DEFAULTS['start_date'])
end_date = config.get('end_date', PORTFOLIO_DEFAULTS['end_date'])
normalize_weights = config.get('normalize_weights', PORTFOLIO_DEFAULTS['normalize_weights'])
```

### Date Logic and Calculation Windows

**System Architecture**:
The risk module implements a three-tier date system for different calculation purposes:

**1. Primary Portfolio System**:
```python
# Source: portfolio.yaml
config = load_portfolio_config("portfolio.yaml")
start_date = config["start_date"]  # e.g., "2019-05-31"
end_date = config["end_date"]      # e.g., "2024-03-31"

# Usage: All portfolio calculations
summary = build_portfolio_view(weights, start_date, end_date, ...)
```

**2. Fallback System**:
```python
# Source: settings.py PORTFOLIO_DEFAULTS
from settings import PORTFOLIO_DEFAULTS

# Used when portfolio dates not specified
start = start or PORTFOLIO_DEFAULTS["start_date"]
end = end or PORTFOLIO_DEFAULTS["end_date"]
normalize_weights = normalize_weights or PORTFOLIO_DEFAULTS["normalize_weights"]
```

**3. Independent Analysis System**:
```python
# Single stock analysis (flexible dates)
today = pd.Timestamp.today().normalize()
start = start or today - pd.DateOffset(years=5)
end = end or today

# Historical worst-case analysis (configurable lookback)
from settings import PORTFOLIO_DEFAULTS
lookback_years = PORTFOLIO_DEFAULTS.get('worst_case_lookback_years', 10)
end_dt = datetime.today()
start_dt = end_dt - pd.DateOffset(years=lookback_years)
```

**Calculation Consistency**:
- **Factor Regressions**: All use same date window for stable betas
- **Peer Validation**: Subindustry peers validated over same period as target
- **Data Quality**: Minimum observation requirements prevent regression window limitations
- **Optimization**: All portfolio optimizations use consistent date windows

**Data Flow**:
```
portfolio.yaml → load_portfolio_config() → build_portfolio_view() → factor calculations
     ↓
PORTFOLIO_DEFAULTS (fallback) → proxy generation → peer validation
     ↓
Independent functions → flexible date logic for specific use cases
```

### Portfolio Configuration (`portfolio.yaml`)

**Structure**:
```yaml
# Date Range
start_date: "2019-05-31"
end_date: "2024-03-31"

# Portfolio Positions
portfolio_input:
  TICKER: {weight: 0.XX}

# Expected Returns
expected_returns:
  TICKER: 0.XX

# Factor Proxies
stock_factor_proxies:
  TICKER:
    market: MARKET_PROXY
    momentum: MOMENTUM_PROXY
    value: VALUE_PROXY
    industry: INDUSTRY_PROXY
    subindustry: [PEER1, PEER2, PEER3]
```

**Validation Rules**:
- Weights must sum to 1.0
- All tickers must have factor proxies
- Date ranges must be valid
- Expected returns must be reasonable

### Risk Limits (`risk_limits.yaml`)

**Structure**:
```yaml
# Portfolio-Level Limits
portfolio_limits:
  max_volatility: 0.40
  max_loss: -0.25

# Concentration Limits
concentration_limits:
  max_single_stock_weight: 0.40

# Variance Attribution Limits
variance_limits:
  max_factor_contribution: 0.30
  max_market_contribution: 0.30
  max_industry_contribution: 0.30

# Factor Risk Limits
max_single_factor_loss: -0.10
```

## 💾 Caching Strategy

### Multi-Level Caching

1. **RAM Cache** (LRU):
   - Function-level caching with `@lru_cache`
   - Fastest access for frequently used data
   - Configurable cache size

2. **Disk Cache** (Parquet):
   - Compressed parquet files
   - Persistent across sessions
   - MD5-based cache keys
   - Automatic cleanup of corrupt files

3. **Network Cache** (FMP API):
   - Last resort for data retrieval
   - Rate limiting and error handling
   - Automatic retry logic

### Cache Key Strategy

```python
# Cache key components
key = [ticker, start_date, end_date, factor_type]
fname = f"{prefix}_{hash(key)}.parquet"
```

### Cache Invalidation

- Automatic invalidation on file corruption
- Manual invalidation through cache clearing
- Version-based invalidation for API changes

## 📊 Risk Calculation Framework

### Factor Model Structure

**Standard Factors**:
- Market Factor (SPY, ACWX)
- Momentum Factor (MTUM, IMTM)
- Value Factor (IWD, IVLU)
- Industry Factor (KCE, SOXX, XSW)
- Sub-industry Factor (Peer group)

**Factor Construction**:
1. Proxy selection based on stock characteristics
2. Return calculation and normalization
3. Factor correlation analysis
4. Beta calculation through regression

### Risk Decomposition

**Variance Attribution**:
```
Total Variance = Market Variance + Factor Variance + Idiosyncratic Variance
```

**Risk Contributions**:
```
Position Risk Contribution = Weight × Marginal Risk Contribution
```

**Concentration Measures**:
```
Herfindahl Index = Σ(Weight²)
```

## 📐 Mathematical Framework

The risk module implements a comprehensive mathematical framework for portfolio risk analysis. For detailed mathematical formulas and their implementations, see the **Mathematical Reference** section in the README.md file.

**Key Mathematical Components**:
- **Portfolio Volatility**: `σ_p = √(w^T Σ w)`
- **Factor Betas**: `β_i,f = Cov(r_i, r_f) / Var(r_f)`
- **Risk Contributions**: `RC_i = w_i × (Σw)_i / σ_p`
- **Variance Decomposition**: Total = Factor + Idiosyncratic
- **Euler Variance**: Marginal variance contributions

**Implementation Functions**:
- `compute_portfolio_volatility()`: Portfolio risk calculation
- `compute_stock_factor_betas()`: Factor exposure analysis
- `compute_risk_contributions()`: Risk attribution
- `compute_portfolio_variance_breakdown()`: Variance decomposition
- `compute_euler_variance_percent()`: Marginal contributions

## 🌐 Web Application Architecture  

The Risk Module provides a complete full-stack web application with a production-ready Flask backend and a sophisticated React frontend dashboard.

### Flask Web App (`app.py`)

**Production-Ready Features** (3,156 lines):
- **Google OAuth Authentication**: Secure user management and session handling
- **Multi-Tier Access Control**: Public/Registered/Paid user tiers with rate limiting
- **Plaid Integration**: Real-time portfolio import from brokerage accounts
- **Claude AI Chat**: Interactive risk analysis assistance and natural language queries
- **RESTful API**: Multiple endpoints for portfolio analysis and risk scoring
- **Portfolio Configuration Interface**: Web-based YAML editor and management
- **Risk Analysis Execution**: Server-side portfolio analysis with export functionality
- **Admin Dashboard**: Usage tracking, cache management, and system monitoring
- **API Key Management**: Secure key generation, validation, and Kartra integration

**Rate Limiting Strategy**:
```python
# Tiered rate limits
limits = {
    "public": "5 per day",
    "registered": "15 per day", 
    "paid": "30 per day"
}
```

**Security Features**:
- API key validation
- Rate limiting by user tier
- Error logging and monitoring
- Secure token storage

### React Dashboard Frontend Architecture

**Production-Ready Single Page Application** with complete risk analysis interface:

#### Core Dashboard Structure (`frontend/src/components/dashboard/DashboardApp.jsx`)

**580 lines of sophisticated React architecture** providing:

**1. Dashboard Views (6 comprehensive views)**:
- **Risk Score View**: Portfolio risk scoring with detailed breakdown and recommendations
- **Holdings View**: Portfolio composition with weight analysis and risk attribution
- **Factor Analysis View**: Multi-factor exposure analysis with sector/style breakdowns
- **Performance Analytics View**: Historical performance metrics with benchmarking
- **Analysis Report View**: Comprehensive risk reports with export functionality (PDF/CSV)
- **Risk Settings View**: Risk tolerance configuration and limit management

**2. Hybrid Loading Strategy (Performance-Optimized)**:
```javascript
// Critical tabs: Instant loading (no lazy loading)
import RiskScoreViewContainer from './views/RiskScoreViewContainer';
import HoldingsViewContainer from './views/HoldingsViewContainer';

// Secondary tabs: Lazy loaded but preloaded in background
const FactorAnalysisViewContainer = lazy(() => import('./views/FactorAnalysisViewContainer'));
const PerformanceAnalyticsViewContainer = lazy(() => import('./views/PerformanceAnalyticsViewContainer'));

// On-demand tabs: Lazy loaded when accessed
const AnalysisReportView = lazy(() => import('./views/AnalysisReportView'));
const RiskSettingsView = lazy(() => import('./views/RiskSettingsView'));
```

**Loading Performance Strategy**:
- **Critical Views**: Instant access (0ms loading) for Risk Score and Holdings
- **Secondary Views**: Background preloading after 2 seconds for Factor Analysis and Performance
- **On-demand Views**: Lazy loading for Reports and Settings to optimize initial bundle size

**3. Real Data Integration (Hook → Adapter → Manager → API Pattern)**:
```javascript
// Real data connections using production hooks
const portfolioSummaryHook = usePortfolioSummary();
const { currentPortfolio } = useAppContext();

// Portfolio summary with real data fallback
const portfolioSummary = useMemo(() => {
  const realData = portfolioSummaryHook.data;
  return {
    totalValue: currentPortfolio.total_portfolio_value || 0,
    riskScore: realData?.riskScore || 87.5,
    volatilityAnnual: realData?.volatilityAnnual || 20.11,
    lastUpdated: currentPortfolio.statement_date || new Date().toISOString()
  };
}, [currentPortfolio, portfolioSummaryHook.data]);
```

**4. Claude AI Chat Integration (Context-Aware)**:
```javascript
// Chat with visual context integration
const handleSendMessage = async (message) => {
  const chatMessage = {
    content: message,
    context: {
      currentView: activeView,
      portfolioValue: portfolioSummary?.totalValue || 0,
      riskScore: portfolioSummary?.riskScore || 0,
      hasData: currentViewState.data !== null
    }
  };
  
  // Real Claude API call (backend integration)
  const response = await apiService.claudeChat(message, chatMessages, currentPortfolio?.portfolio_name);
};
```

**Chat Features**:
- **Context-Aware Responses**: Claude receives current view data and portfolio state
- **Function Calling**: Chat can trigger view changes and data refreshes
- **Real API Integration**: Connects to backend Claude API with portfolio context
- **Visual Integration**: Assistant can navigate between dashboard views based on conversation

**5. Comprehensive State Management (Zustand + Context)**:
```javascript
// Zustand store for dashboard state
const actions = useDashboardActions();
const activeView = useActiveView();
const currentViewState = useViewState(activeView);
const chatMessages = useChatMessages();

// App context for portfolio state
const { currentPortfolio } = useAppContext();
```

**State Architecture**:
- **Dashboard State**: View management, loading states, chat history (Zustand)
- **Portfolio State**: Current portfolio data, user context (React Context)
- **View State**: Per-view data caching and loading management
- **Chat State**: Message history and context preservation

**6. Production Logging and Performance Monitoring**:
```javascript
// Comprehensive logging throughout the application
frontendLogger.logComponent('DashboardApp', 'Component initialized with portfolio', {
  portfolioValue: context.currentPortfolio.total_portfolio_value || 0,
  hasRealRiskData: portfolioSummaryHook.hasData,
  isLoadingRiskData: portfolioSummaryHook.loading
});

// Performance monitoring for view switching
const switchTime = performance.now() - startTime;
frontendLogger.logPerformance('DashboardApp', 'View switch completed', {
  viewId,
  switchTime: `${switchTime.toFixed(2)}ms`
});
```

**7. Real Portfolio Operations**:
```javascript
// Portfolio risk analysis with real backend integration
const handleAnalyzeRisk = async () => {
  try {
    // 1. Trigger full portfolio analysis (/api/analyze)
    const analysisResult = await portfolioManager.analyzePortfolioRisk(currentPortfolio);
    
    // 2. Calculate risk score (/api/risk-score)  
    const riskScoreResult = await portfolioManager.calculateRiskScore();
    
    // NOTE: Dashboard views automatically refresh via hooks
    // useRiskAnalysis(), useRiskScore(), etc. detect new data
  } catch (error) {
    frontendLogger.logError('DashboardApp', 'Risk analysis failed', error);
  }
};
```

#### Dashboard Data Flow Architecture

**Complete Integrated Data Flow**:
```
User Action → React Component → Service Layer → Flask API → Core Engine → Database
     ↓
React State ← Component Update ← Structured Response ← Business Logic ← Analysis Results
```

**Hook → Adapter → Manager → API Pattern**:
```javascript
// 1. React Hook (frontend/src/chassis/hooks/usePortfolioSummary.js)
const portfolioHook = usePortfolioSummary(); // Manages component state

// 2. Service Adapter (frontend/src/chassis/services/APIService.js)  
const apiService = new APIService(); // Handles HTTP communication

// 3. Portfolio Manager (frontend/src/chassis/managers/PortfolioManager.js)
const portfolioManager = new PortfolioManager(apiService, claudeService); // Business logic

// 4. Backend API (routes/api.py)
POST /api/analyze → Core Risk Engine → Structured Response
```

**View-Specific Data Loading**:
- **Risk Score View**: `useRiskAnalysis()` hook → `/api/analyze` → Real-time portfolio risk metrics
- **Holdings View**: `usePortfolioSummary()` hook → `/api/risk-score` → Holdings breakdown with risk attribution
- **Factor Analysis**: `useFactorAnalysis()` hook → `/api/analyze` → Multi-factor exposure data
- **Performance View**: `usePerformanceAnalysis()` hook → `/api/performance` → Historical performance metrics
- **Reports View**: Export functionality → `/api/analyze` → PDF/CSV generation
- **Settings View**: `useRiskSettings()` hook → Risk limits configuration and validation

#### Frontend Architecture Components

**Component Architecture**:
```
frontend/src/
├── components/dashboard/
│   ├── DashboardApp.jsx           # Main dashboard orchestrator (580 lines)
│   ├── layout/
│   │   └── DashboardLayout.jsx    # Layout wrapper with navigation
│   ├── views/                     # Dashboard view containers
│   │   ├── RiskScoreViewContainer.jsx      # Risk scoring (critical - instant load)
│   │   ├── HoldingsViewContainer.jsx       # Portfolio holdings (critical - instant load)
│   │   ├── FactorAnalysisViewContainer.jsx # Factor analysis (secondary - preloaded)
│   │   ├── PerformanceAnalyticsViewContainer.jsx # Performance (secondary - preloaded)
│   │   ├── AnalysisReportView.jsx         # Reports (on-demand - lazy loaded)
│   │   └── RiskSettingsView.jsx           # Settings (on-demand - lazy loaded)
│   └── shared/
│       └── LoadingView.jsx        # Loading states and progress indicators
├── chassis/                       # Core infrastructure
│   ├── context/
│   │   └── AppContext.jsx         # Global application state
│   ├── hooks/
│   │   ├── usePortfolioSummary.js # Portfolio data hook
│   │   ├── useRiskAnalysis.js     # Risk analysis hook
│   │   └── usePerformanceAnalysis.js # Performance metrics hook
│   ├── services/
│   │   ├── APIService.js          # HTTP service layer
│   │   ├── ClaudeService.js       # Claude AI integration
│   │   └── frontendLogger.js      # Logging service
│   └── managers/
│       └── PortfolioManager.js    # Portfolio business logic
├── store/
│   └── dashboardStore.js          # Zustand state management
└── data/
    └── mockPortfolioData.js       # Fallback data for development
```

**Key Architecture Benefits**:

1. **Performance-First Design**: 
   - Critical views load instantly with no Suspense overhead
   - Secondary views preload in background for fast access
   - On-demand views lazy load to optimize bundle size

2. **Real Data Integration**:
   - Production hooks connect to actual backend APIs
   - Fallback to mock data for development/offline use
   - Comprehensive error handling and loading states

3. **Context-Aware AI**:
   - Claude chat receives full dashboard context
   - AI can navigate between views and trigger actions
   - Visual-chat integration for seamless user experience

4. **Production Monitoring**:
   - Comprehensive logging at component, performance, and user levels
   - Performance metrics tracking for optimization
   - Error tracking and reporting

5. **Scalable Architecture**:
   - Clean separation between UI, business logic, and data layers
   - Modular component design for easy extension
   - Type-safe interfaces and error boundaries

### Route Documentation (`routes/`)

The web interface is organized into 5 specialized route modules for clean separation of concerns:

#### Core API Routes (`routes/api.py`)
**Primary risk analysis endpoints**

| Endpoint | Method | Purpose | Returns |
|----------|--------|---------|---------|
| `/api/analyze` | POST | Portfolio risk analysis | Structured data + CLI-style formatted report |
| `/api/risk-score` | POST | Risk scoring analysis | Structured data + CLI-style formatted report |
| `/api/performance` | POST | Performance metrics | Structured data + CLI-style formatted report |
| `/api/what-if` | POST | Scenario analysis | Structured data + raw analysis output |
| `/api/optimize` | POST | Portfolio optimization | Structured data + optimization results |

**Response Format**:
```json
{
  "success": true,
  "performance_metrics": {
    "returns": {"annualized_return": 25.98, ...},
    "risk_metrics": {"volatility": 19.80, ...},
    "risk_adjusted_returns": {"sharpe_ratio": 1.18, ...},
    ...
  },
  "formatted_report": "📊 PORTFOLIO PERFORMANCE ANALYSIS\n============...",
  "summary": {"key_metrics": "..."},
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Features**:
- **Dual Output Format**: Both structured JSON data AND human-readable formatted reports
- Rate limiting by user tier
- Input validation and sanitization
- Comprehensive error handling
- Export functionality for analysis results

#### Claude AI Chat Routes (`routes/claude.py`)
**AI-powered conversational analysis**

| Endpoint | Method | Purpose | Parameters |
|----------|--------|---------|------------|
| `/api/claude_chat` | POST | Interactive AI analysis | `user_message`, `chat_history`, `portfolio_name` |

**Features**:
- Integration with 14 Claude functions across 6 categories
- Database-first architecture with user isolation
- Authentication required for all functions
- Function calling and parameter validation
- Natural language result interpretation
- Session-based user authentication

#### Plaid Integration Routes (`routes/plaid.py`)
**Brokerage account integration**

| Endpoint | Method | Purpose | Parameters |
|----------|--------|---------|------------|
| `/plaid/link` | POST | Create Plaid link token | `user_id` |
| `/plaid/exchange` | POST | Exchange public token | `public_token`, `user_id` |
| `/plaid/accounts` | GET | List connected accounts | `user_id` |
| `/plaid/holdings` | GET | Get account holdings | `user_id`, `account_id` |
| `/plaid/import` | POST | Import portfolio data | `user_id`, `account_id` |

**Features**:
- Multi-institution support
- Real-time holdings import
- Cash position mapping
- Portfolio YAML generation
- AWS Secrets Manager integration

#### Authentication Routes (`routes/auth.py`)
**User management and security**

| Endpoint | Method | Purpose | Parameters |
|----------|--------|---------|------------|
| `/auth/login` | POST | User login | `email`, `password` |
| `/auth/logout` | POST | User logout | - |
| `/auth/register` | POST | User registration | `email`, `password`, `tier` |
| `/auth/profile` | GET | Get user profile | - |
| `/auth/api-key` | POST | Generate API key | `user_id` |

**Features**:
- Google OAuth integration
- Multi-tier user management (public/registered/paid)
- Secure session handling
- API key generation and validation
- Rate limiting enforcement

#### Admin Routes (`routes/admin.py`)
**System administration and monitoring**

| Endpoint | Method | Purpose | Parameters |
|----------|--------|---------|------------|
| `/admin/usage` | GET | Usage statistics | `date_range` |
| `/admin/cache` | DELETE | Clear system cache | `cache_type` |
| `/admin/users` | GET | User management | `filters` |
| `/admin/logs` | GET | System logs | `level`, `date_range` |
| `/admin/health` | GET | System health check | - |

**Features**:
- Usage tracking and analytics
- Cache management
- User administration
- System monitoring
- Error log analysis

### API Response Format

**Service Layer Endpoints** provide dual output format:

```json
{
  "success": true,
  "risk_results": {
    // Structured data with all metrics
    "volatility_annual": 0.198,
    "factor_exposures": {...},
    // ... comprehensive structured data
  },
  "formatted_report": "📊 PORTFOLIO RISK ANALYSIS\n============...",
  "summary": {
    // Key metrics summary
    "overall_risk": "Medium",
    "key_recommendations": [...]
  },
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Direct Endpoints** return raw function output:

```json
{
  "success": true,
  "data": {
    // Raw function output
  },
  "endpoint": "direct/portfolio",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### Error Handling

- **Rate Limiting**: HTTP 429 with retry-after header
- **Authentication**: HTTP 401 for invalid credentials
- **Authorization**: HTTP 403 for insufficient permissions
- **Validation**: HTTP 400 with detailed error messages
- **Server Error**: HTTP 500 with error tracking ID

### Frontend Architecture (`frontend/`)

The frontend is a modern React Single Page Application (SPA) that provides an intuitive interface for portfolio risk analysis.

#### React Application (`frontend/src/App.js`)
**1,477 lines of sophisticated React components**

**Core Features**:
- **Portfolio Management**: Upload, edit, and manage portfolio configurations
- **Risk Analysis Dashboard**: Interactive risk metrics and visualizations
- **Claude AI Chat**: Conversational interface for portfolio analysis
- **Plaid Integration**: Connect and import brokerage accounts
- **Performance Tracking**: Historical performance analysis and benchmarking
- **Risk Scoring**: Visual risk score breakdown and recommendations
- **What-If Analysis**: Interactive scenario testing

**Component Structure**:
```
frontend/src/
├── App.js                     # Main application (1,477 lines)
├── components/
│   ├── Dashboard/             # Risk analysis dashboard
│   ├── Portfolio/             # Portfolio management
│   ├── Chat/                  # Claude AI chat interface
│   ├── Plaid/                 # Brokerage integration
│   ├── Analysis/              # Risk analysis components
│   ├── Performance/           # Performance tracking
│   └── Common/                # Shared components
├── services/
│   ├── api.js                 # API service layer
│   ├── claude.js              # Claude chat service
│   └── plaid.js               # Plaid integration service
├── utils/
│   ├── helpers.js             # Utility functions
│   ├── validation.js          # Input validation
│   └── formatting.js          # Data formatting
└── styles/
    ├── components/            # Component-specific styles
    └── global/                # Global styles
```

**Key Components**:

1. **Portfolio Dashboard**:
   - Real-time risk metrics display
   - Interactive charts and visualizations
   - Portfolio composition breakdown
   - Risk limit monitoring

2. **Claude Chat Interface**:
   - Natural language query processing
   - Context-aware conversations
   - Function calling integration
   - Result visualization

3. **Plaid Integration**:
   - Account linking workflow
   - Holdings import interface
   - Multi-institution support
   - Cash position mapping

4. **Risk Analysis Tools**:
   - Factor exposure analysis
   - Risk decomposition charts
   - Concentration analysis
   - Historical performance tracking

5. **What-If Scenarios**:
   - Interactive portfolio modification
   - Scenario comparison
   - Risk impact analysis
   - Optimization suggestions

**State Management**:
- React hooks for local state
- Context API for global state
- Redux for complex state management
- Local storage for persistence

**API Integration**:
- Axios for HTTP requests
- Error handling and retry logic
- Rate limiting compliance
- Real-time updates

**User Experience Features**:
- Responsive design for mobile/desktop
- Loading states and progress indicators
- Error boundaries for graceful failures
- Accessibility compliance
- Dark/light mode support

#### Frontend Build Process

**Development Setup**:
```bash
cd frontend/
npm install
npm start                    # Development server
npm run build               # Production build
npm test                    # Run tests
```

**Production Build**:
- Webpack bundling and optimization
- CSS/JS minification
- Asset optimization
- Environment variable injection

**Deployment**:
- Served through Flask static files
- CDN integration for assets
- Service worker for offline support
- Progressive Web App (PWA) capabilities

### Frontend-Backend Integration

**Data Flow**:
```
User Input → React Component → API Service → Flask Route → Core Engine → Database
     ↓
React State ← Component Update ← API Response ← Flask Response ← Analysis Results
```

**Real-time Features**:
- WebSocket connections for live updates
- Server-sent events for analysis progress
- Polling for portfolio updates
- Push notifications for risk alerts

**Security**:
- JWT token authentication
- CSRF protection
- Input sanitization
- XSS prevention
- Content Security Policy

### Interface Alignment System (`tools/`)

The system includes sophisticated tools for managing the complexity of the 4-interface architecture and ensuring consistency across all user touchpoints.

#### Interface Alignment Analysis

**Problem**: The risk module provides the same functionality through 4 different interfaces (CLI, API, Claude, Inputs), but maintaining consistency across all interfaces is challenging.

**Solution**: A comprehensive alignment tracking system that maps all functions across interfaces and identifies gaps.

#### Alignment Tools

**1. Interface Alignment Table (`docs/interfaces/alignment_table.md`)**
- **Purpose**: Complete mapping of 39 functions across 4 interfaces
- **Categories**: 9 functional categories (Core Analysis, Portfolio Management, etc.)
- **Status Tracking**: Alignment percentages and gap identification
- **Priority Analysis**: Identifies which missing functions would provide maximum impact

**Current Status**:
- **Overall Alignment**: 21% (8/39 functions fully aligned)
- **Biggest Gap**: Missing 9 CLI functions (would increase alignment to 44%)
- **Best Coverage**: Inputs layer (100%), API layer (85%)
- **Development Priority**: Add CLI wrappers for existing functions

**2. Terminal Alignment Viewer (`tools/view_alignment.py`)**
- **Purpose**: Quick terminal-friendly view of alignment status
- **Features**: Clean formatting, file location reference, priority recommendations
- **Usage**: `python tools/view_alignment.py`

**Output Example**:
```
🔍 CORE ANALYSIS FUNCTIONS
📋 Portfolio Analysis
  CLI:    ✅ run_portfolio()
  API:    ✅ /api/analyze + /api/claude_chat
  Claude: ✅ run_portfolio_analysis()
  Inputs: ✅ load_yaml_config()
  Status: ✅ FULLY ALIGNED
```

**3. Dependency Checker (`tools/check_dependencies.py`)**
- **Purpose**: Impact analysis for function modifications
- **Features**: Dependency mapping, testing chains, impact assessment
- **Usage**: `python tools/check_dependencies.py create_portfolio_yaml`

**Output Example**:
```
🔍 DEPENDENCY CHECK: create_portfolio_yaml
📁 Source File: inputs/portfolio_manager.py
🔗 Used By:
  • Claude: create_portfolio_scenario() → services/claude/function_executor.py
  • API: /api/claude_chat → routes/claude.py
  • CLI: ❌ Missing run_create_portfolio_scenario()
🧪 Testing Chain:
  1. Test inputs/portfolio_manager.py → create_portfolio_yaml()
  2. Test services/claude/function_executor.py → create_portfolio_scenario()
  3. Test /api/claude_chat endpoint → routes/claude.py
  4. Test frontend Claude chat integration
```

**4. Interface Testing Suite (`tools/test_all_interfaces.py`)**
- **Purpose**: Comprehensive testing across all interfaces
- **Features**: End-to-end testing, interface consistency validation
- **Coverage**: All 39 functions across 4 interfaces

#### Interface Architecture Benefits

**1. Consistency Tracking**:
- Ensures all interfaces provide equivalent functionality
- Prevents feature drift between interfaces
- Maintains user experience consistency

**2. Gap Analysis**:
- Identifies missing functions that would improve user experience
- Prioritizes development based on impact
- Tracks alignment progress over time

**3. Development Planning**:
- Guides feature development priorities
- Ensures comprehensive interface coverage
- Supports systematic interface expansion

**4. Quality Assurance**:
- Validates function behavior across interfaces
- Ensures consistent parameter handling
- Maintains interface compatibility

#### Interface Alignment Metrics

**Function Categories & Alignment**:
- **Core Analysis**: 60% aligned (3/5 functions) - Good coverage
- **Scenario & Optimization**: 75% aligned (3/4 functions) - Excellent coverage
- **Portfolio Management**: 17% aligned (1/6 functions) - Needs improvement
- **Returns Management**: 0% aligned (0/3 functions) - Missing CLI functions
- **Risk Limits**: 0% aligned (0/5 functions) - Missing CLI functions
- **Plaid Integration**: 0% aligned (0/5 functions) - Missing CLI functions
- **File Management**: 0% aligned (0/4 functions) - Missing CLI functions
- **Auth & Admin**: 0% aligned (0/4 functions) - Missing CLI functions
- **AI Orchestration**: 0% aligned (0/3 functions) - Missing CLI functions

**Development Impact**:
Adding the 9 missing CLI functions would:
- Increase overall alignment from 21% to 44%
- Provide complete CLI workflow coverage
- Enable consistent behavior across all interfaces
- Support power users who prefer command-line operations

## 🔗 External Integrations

### Plaid Financial Data Integration (`plaid_loader.py`)

**Automated Portfolio Import**:
- **Multi-Institution Support**: Connect to multiple brokerage accounts
- **Real-Time Holdings**: Fetch current positions and balances
- **Cash Position Mapping**: Convert cash to appropriate ETF proxies
- **AWS Secrets Management**: Secure storage of access tokens
- **Portfolio YAML Generation**: Automatic conversion to risk module format

**Data Flow**:
```
Plaid API → Holdings Data → Cash Mapping → Portfolio YAML → Risk Analysis
```

**Supported Features**:
- Interactive Brokers integration
- Multi-currency support
- Automatic cash gap detection
- Portfolio consolidation

### **Database-First Architecture**

The system has been upgraded to use a **database-first approach with YAML fallback** for both user configurations and reference data management:

**Database Schema:**
```sql
-- User management and authentication
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    tier VARCHAR(50) DEFAULT 'public',
    auth_provider VARCHAR(50) NOT NULL DEFAULT 'google',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- User portfolios with date ranges
CREATE TABLE portfolios (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, name)
);

-- Portfolio positions with multi-currency support
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(100) NOT NULL,
    quantity DECIMAL(20,8) NOT NULL,
    currency VARCHAR(10) NOT NULL,
    type VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- User-specific risk limits
CREATE TABLE risk_limits (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    portfolio_id INT REFERENCES portfolios(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    max_volatility DECIMAL(5,4),
    max_loss DECIMAL(5,4),
    max_single_stock_weight DECIMAL(5,4),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Reference Data Tables:

-- Cash currency to ETF proxy mappings
CREATE TABLE cash_proxies (
    currency VARCHAR(3) PRIMARY KEY,
    proxy_etf VARCHAR(10) NOT NULL
);

-- Cash broker aliases to currency mappings
CREATE TABLE cash_aliases (
    broker_alias VARCHAR(50) PRIMARY KEY,
    currency VARCHAR(3) NOT NULL
);

-- Exchange to factor proxy mappings
CREATE TABLE exchange_proxies (
    exchange VARCHAR(10) NOT NULL,
    factor_type VARCHAR(20) NOT NULL,  -- 'market', 'momentum', 'value'
    proxy_etf VARCHAR(10) NOT NULL,
    PRIMARY KEY (exchange, factor_type)
);

-- Industry to ETF proxy mappings
CREATE TABLE industry_proxies (
    industry VARCHAR(100) PRIMARY KEY,
    proxy_etf VARCHAR(10) NOT NULL
);
```

**Architecture Pattern:**
```
Database (Primary) → YAML Fallback → Hard-coded Defaults
```

**Code Integration:**
```python
# Cash mappings (in portfolio_manager.py)
cash_map = self.db_client.get_cash_mappings()
# Auto-fallback to cash_map.yaml if database unavailable

# Exchange mappings (in proxy_builder.py)
exchange_map = load_exchange_proxy_map()
# Auto-fallback to exchange_etf_proxies.yaml if database unavailable

# Industry mappings (in proxy_builder.py)
industry_map = load_industry_etf_map()
# Auto-fallback to industry_to_etf.yaml if database unavailable
```

**Benefits:**
- **Operational Flexibility**: Add new brokerages without code deployment
- **Reliability**: Automatic fallback ensures system availability
- **Auditability**: Database tracks all changes with timestamps
- **Consistency**: Single source of truth for all reference data
- **Scalability**: Database handles concurrent access and transactions

**Admin Tools:**
- `admin/manage_reference_data.py` - CLI tool for managing all mappings
- `admin/README.md` - Complete reference data management guide
- Database migration scripts for existing YAML data

**YAML Files (Development & Fallback):**
- `portfolio.yaml` - Local portfolio configuration (development/testing)
- `risk_limits.yaml` - Local risk limits configuration (development/testing)
- `cash_map.yaml` - Cash position mapping (database fallback)
- `industry_to_etf.yaml` - Industry classification mapping (database fallback)
- `exchange_etf_proxies.yaml` - Exchange-specific factor proxies (database fallback)
- `what_if_portfolio.yaml` - What-if scenario configurations

## 🔌 API Integration

### Financial Modeling Prep (FMP)

**Endpoints Used**:
- `/historical-price-eod/full`: End-of-day price data
- `/treasury`: 3-month Treasury yields for risk-free rate calculations
- Parameters: symbol, from, to, apikey, serietype

**Data Processing**:
- Monthly resampling to month-end
- Return calculation and normalization
- Missing data handling
- Outlier detection and treatment

**Error Handling**:
- Rate limiting compliance
- Network timeout handling
- API error response parsing
- Automatic retry with exponential backoff

## 🧪 Database Testing Framework

### Comprehensive Test Suite

The Risk Module includes a production-ready database testing framework with 95% test coverage:

**Test Suite Components:**

**1. Performance Benchmarks** (`tests/test_performance_benchmarks.py`):
- **Database Query Performance**: Target <100ms, actual 9.4ms average
- **Connection Pool Efficiency**: 2-5 connections with automatic scaling
- **Concurrent User Handling**: 100% success rate with 10+ simultaneous users
- **Memory Usage Monitoring**: 0.0MB per user memory overhead
- **Cache Integration**: 78,000x speedup validation
- **Batch Operations**: 1000+ positions processing performance

**2. User Isolation Tests** (`tests/test_user_isolation.py`):
- **Portfolio Access Control**: User A cannot access User B's portfolios
- **Database Query Filtering**: SQL injection prevention and parameter validation
- **Session Isolation**: Secure session token management
- **Data Leakage Prevention**: Cross-user data contamination prevention

**3. Fallback Mechanisms** (`tests/test_fallback_mechanisms.py`):
- **Database Unavailable Scenarios**: Automatic fallback to file mode
- **Connection Timeout Handling**: Retry logic and graceful degradation
- **Transaction Rollback**: Error recovery and data consistency
- **Fallback Data Consistency**: Seamless mode switching validation

**4. Cash Mapping Validation** (`tests/test_cash_mapping_validation.py`):
- **Basic Cash Mapping**: Total dollar preservation across currency conversions
- **Dynamic Configuration**: `cash_map.yaml` loading and validation
- **Database Storage**: Analysis-time mapping with database persistence
- **Edge Cases**: Currency conversion error handling

**5. Comprehensive Migration Testing** (`tests/test_comprehensive_migration.py`):
- **Master Test Runner**: Orchestrates all test modules
- **Production Readiness Assessment**: Performance, security, reliability metrics
- **Detailed Reporting**: JSON results with pass/fail status
- **Performance Metrics**: Database query times, memory usage, concurrent handling

### Test Execution Commands

```bash
# Run full comprehensive test suite
cd tests && python3 test_comprehensive_migration.py

# Run specific test categories
cd tests && python3 test_performance_benchmarks.py    # Performance validation
cd tests && python3 test_user_isolation.py           # Security testing
cd tests && python3 test_fallback_mechanisms.py      # Fallback validation
cd tests && python3 test_cash_mapping_validation.py  # Cash mapping tests

# Performance-only testing
cd tests && python3 test_comprehensive_migration.py --performance-only
```

### Test Coverage Metrics

**Before Database Implementation**: 60% coverage
**After Database Implementation**: 95% coverage

**Coverage Breakdown:**
- **Database Connectivity**: 100% coverage
- **User Authentication**: 90% coverage
- **Performance Benchmarks**: 100% coverage
- **Security & Isolation**: 100% coverage
- **Fallback Mechanisms**: 100% coverage
- **Cash Mapping**: 100% coverage

## ⚡ Performance Considerations

### Optimization Strategies

1. **Caching**:
   - Multi-level caching reduces API calls
   - Compressed storage reduces disk usage
   - LRU cache optimizes memory usage

2. **Vectorization**:
   - NumPy operations for bulk calculations
   - Pandas vectorized operations
   - Efficient matrix operations

3. **Parallel Processing**:
   - Concurrent API calls where possible
   - Batch processing for multiple securities
   - Async/await for I/O operations

### Memory Management

- Lazy loading of large datasets
- Garbage collection optimization
- Memory-efficient data structures
- Streaming for large files

## 🧪 Testing Strategy

### Test Entry Points

1. **Portfolio Analysis**:
   ```bash
   python run_portfolio_risk.py
   ```

2. **Single Stock Profile**:
   ```bash
   python run_single_stock_profile.py
   ```

3. **Risk Runner**:
   ```bash
   python run_risk.py
   ```

### Validation Checks

- **Data Quality**: Missing data detection
- **Statistical Validity**: Regression diagnostics
- **Risk Limits**: Automated limit checking
- **Configuration**: YAML validation
- **Performance**: Execution time monitoring

### Error Handling

- Graceful degradation on API failures
- Comprehensive error messages
- Fallback strategies for missing data
- Logging for debugging and monitoring

## 🚀 Future Enhancements

### Planned Features

1. **Streamlit Dashboard**:
   - Interactive risk visualization
   - Real-time portfolio monitoring
   - Dynamic configuration updates

2. **Advanced GPT Integration**:
   - Automated peer suggestion ✅ **Implemented**
   - Natural language risk reports ✅ **Implemented**
   - Intelligent factor selection

3. **Advanced Risk Models**:
   - Conditional Value at Risk (CVaR)
   - Expected Shortfall
   - Tail risk measures

4. **Real-time Monitoring**:
   - Live data feeds
   - Alert system
   - Automated rebalancing

5. **Backtesting Framework**:
   - Historical performance analysis
   - Strategy comparison
   - Risk-adjusted returns

### Technical Improvements

1. **Performance**:
   - GPU acceleration for large portfolios
   - Distributed computing support
   - Real-time data streaming

2. **Extensibility**:
   - Plugin architecture
   - Custom factor models
   - Alternative data sources

3. **User Experience**:
   - Web-based interface 🔄 **In Development** - Figma UI design in progress
   - Mobile app support
   - API endpoints for integration ✅ **Implemented**

## 📈 Status by Module

| Layer | File/Function | Status | Notes |
|-------|---------------|--------|-------|
| Data Fetch | `fetch_monthly_close` | ✅ Working | FMP API integration complete |
| Return Calc | `calc_monthly_returns` | ✅ Complete | Merged into factor_utils |
| Volatility | `compute_volatility` | ✅ Complete | Rolling window implementation |
| Single-Factor Regression | `compute_regression_metrics` | ✅ Complete | OLS with diagnostics |
| Multi-Factor Betas | `compute_factor_metrics` | ✅ Working | Multi-factor regression |
| Factor Variance | `calc_factor_vols` | ✅ Complete | Factor volatility calculation |
| Portfolio Diagnostics | `build_portfolio_view` | ✅ Working | Comprehensive risk summary |
| Portfolio Input Parsing | `standardize_portfolio_input` | ✅ Working | YAML configuration support |
| Single Stock Profile | `get_detailed_stock_factor_profile` | ✅ Working | Individual stock analysis |
| YAML Config Support | `portfolio.yaml` | ✅ In Use | Flexible configuration |
| Risk Limits | `risk_limits.yaml` | ✅ Complete | Automated limit checking |
| Caching System | `data_loader.py` | ✅ Complete | Multi-level caching |
| Display Utils | `helpers_display.py` | ✅ Working | Formatted output |
| Input Utils | `helpers_input.py` | ✅ Working | Configuration parsing |
| Portfolio Optimization | `portfolio_optimizer.py` | ✅ Working | Min variance and max return |
| GPT Integration | `gpt_helpers.py` | ✅ Working | Peer generation and interpretation |
| Proxy Builder | `proxy_builder.py` | ✅ Working | Factor proxy generation |
| Web Application | `app.py` | 🔄 In Development | Flask web interface - Figma UI design in progress |
| Plaid Integration | `plaid_loader.py` | ✅ Working | Financial data import |
| Risk Helpers | `risk_helpers.py` | ✅ Working | Risk calculation utilities |

## 📦 Dependencies

### Core Dependencies

- **pandas**: Data manipulation and analysis
- **numpy**: Numerical computing
- **statsmodels**: Statistical modeling and regression
- **requests**: HTTP library for API calls
- **python-dotenv**: Environment variable management
- **pyarrow**: Parquet file handling for caching

### Web Application Dependencies

- **flask**: Web application framework
- **flask-limiter**: Rate limiting for web API
- **redis**: Caching and session management
- **streamlit**: Web dashboard framework (future)

### External API Dependencies

- **plaid**: Financial data integration
- **openai**: GPT integration for peer generation
- **boto3**: AWS Secrets Manager integration

### Configuration Dependencies

- **pyyaml**: YAML configuration file handling

## 🛠️ Helper Utilities

### Display Utilities (`helpers_display.py`)

**Functions**:
- `_drop_factors()`: Remove presentation-only factor rows
- `_print_single_portfolio()`: Pretty-print risk and beta tables
- `compare_risk_tables()`: Side-by-side risk table comparison
- `compare_beta_tables()`: Factor beta table comparison

**Usage**:
```python
from helpers_display import compare_risk_tables

# Compare before/after risk metrics
comparison = compare_risk_tables(old_risk_df, new_risk_df)
```

### Input Processing (`helpers_input.py`)

**Functions**:
- `parse_delta()`: Parse what-if scenario changes
- `_parse_shift()`: Convert human-friendly shift strings to decimals

**Supported Formats**:
- `"+200bp"` → `0.02`
- `"-75bps"` → `-0.0075`
- `"1.5%"` → `0.015`
- `"-0.01"` → `-0.01`

**Precedence Rules**:
1. YAML `new_weights:` → full replacement
2. YAML `delta:` + literal shifts → merged changes
3. Literal shifts only → fallback option

### GPT Integration (`gpt_helpers.py`)

**Functions**:
- `interpret_portfolio_risk()`: GPT-based risk interpretation
- `generate_subindustry_peers()`: GPT-powered peer generation

**Features**:
- Professional risk analysis interpretation
- Automated peer group generation
- Error handling and validation
- Configurable model parameters

## 📚 Additional Resources

- [README.md](./README.md): Project overview and usage guide
- [portfolio.yaml](./portfolio.yaml): Example portfolio configuration
- [risk_limits.yaml](./risk_limits.yaml): Risk limit definitions
- [Financial Modeling Prep API](https://financialmodelingprep.com/developer/docs/): API documentation

---

**Architecture Version**: 1.0  
**Last Updated**: 2024  
**Maintainer**: Henry Souchien