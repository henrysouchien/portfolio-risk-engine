# 🧠 Risk Module Architecture Documentation

This document provides a comprehensive overview of the Risk Module's architecture, design principles, and technical implementation details for the **complete integrated system** with production-ready React dashboard interface.

## 📋 Table of Contents

- [System Overview](#system-overview)
- [FMP Data Abstraction Layer](#fmp-data-abstraction-layer)
- [International Ticker Resolution](#international-ticker-resolution)
- [Service Architecture Layer](#service-architecture-layer)
- [Dual-Mode Interface Pattern](#dual-mode-interface-pattern)
- [Architecture Layers](#architecture-layers)
- [Data Flow](#data-flow)
- [Frontend Architecture Patterns](#frontend-architecture-patterns)
- [Component Details](#component-details)
- [Configuration Management](#configuration-management)
- [Caching Strategy](#caching-strategy)
- [Risk Calculation Framework](#risk-calculation-framework)
- [API Integration](#api-integration)
- [Comprehensive Logging & Monitoring Architecture](#comprehensive-logging--monitoring-architecture)
- [Performance Considerations](#performance-considerations)
- [Testing Strategy](#testing-strategy)
- [Future Enhancements](#future-enhancements)

## 🎯 System Overview

The Risk Module is a comprehensive full-stack application combining a modular Python FastAPI backend with a production-ready React frontend. It provides multi-factor regression diagnostics, risk decomposition, and portfolio optimization capabilities through a **clean 3-layer architecture** with **multi-user database support**, **Result Objects architecture**, **Pydantic response validation**, and **integrated dashboard interface** that promotes maintainability, testability, and extensibility.

### Architecture Evolution

**BEFORE**: Monolithic `run_risk.py` (896 lines) mixing CLI, business logic, and formatting
**AFTER**: Enterprise-grade multi-user system with FastAPI backend, production-ready React dashboard, comprehensive service architecture with dependency injection, Pydantic response models for type safety, multi-user database architecture with PostgreSQL, and sophisticated testing infrastructure

### Data Quality Assurance

The system includes robust data quality validation to prevent unstable factor calculations. A key improvement addresses the issue where insufficient peer data could cause extreme factor betas (e.g., -58.22 momentum beta) by limiting regression windows to only 2 observations instead of the full available data.

**Problem Solved**: The `filter_valid_tickers()` function now ensures that subindustry peers have ≥ target ticker's observations, preventing regression window limitations and ensuring stable factor betas.

### Core Design Principles

- **Single Source of Truth**: All interfaces (CLI, API, AI) use the same core business logic with Result Objects
- **Result Objects Architecture**: Unified data structures ensuring perfect CLI/API alignment
- **Dual-Mode Architecture**: Every function supports both CLI and API modes seamlessly
- **Dual-Storage Architecture**: Seamless switching between file-based and database storage
- **Clean Separation**: Routes handle UI, Core handles business logic, Data handles persistence
- **100% Backward Compatibility**: Existing code works identically
- **Enterprise-Ready**: Professional architecture suitable for production deployment

### Database Architecture

**Multi-User Database Support:**
The Risk Module implements a comprehensive multi-user database system with PostgreSQL backend:

**Database Components:**
- **Database Session Management** (`database/session.py`): Request-scoped session management
- **Database Connection Pooling** (`database/pool.py`): PostgreSQL connection pool management
- **Database Schema** (`database/schema.sql`): Complete database schema (831 lines) with 50+ optimized indexes
- **Database Client** (`inputs/database_client.py`): Per-request PostgreSQL helper with no singleton pattern
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
    position_source VARCHAR(50),                 -- Data source: "plaid", "snaptrade", "manual", "csv_import", "api"
    position_status VARCHAR(20) DEFAULT 'active', -- Status: "active", "closed", "pending"
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Same ticker allowed from different sources (Plaid + SnapTrade + manual entry)
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
- **Position Source Tracking**: Supports multiple data sources per ticker (Plaid + SnapTrade + manual entry)
- **Dynamic Proxy Mapping**: Cash-to-ETF mapping applied at analysis time, not storage time
- **Fallback Logic**: Automatic currency extraction from ticker format when currency field missing

**Database Architecture Features:**
- **Connection Pooling** (`database/pool.py`): Database connection pool with 2-5 connections
- **Session Management** (`database/session.py`): Request-scoped session helpers
- **Per-Request Clients** (`inputs/database_client.py`): No singleton pattern, injection-based design
- **Transaction Safety**: ACID compliance with rollback on failure
- **Currency Extraction**: Automatic currency detection from ticker format (CUR:USD → USD)
- **Multi-Source Support**: Same ticker from different sources (Plaid + SnapTrade + manual entry)
- **Data Validation**: Input sanitization and constraint enforcement

### Interface Layer

For web interface, REST API, and Claude AI chat integration, see:
- **[API Reference](docs/API_REFERENCE.md)** - REST API documentation and endpoints
- **[Database Reference](docs/DATABASE_REFERENCE.md)** - Database schema documentation
- **[Data Schemas](docs/DATA_SCHEMAS.md)** - Data schema definitions

## 🔌 FMP Data Abstraction Layer

The Risk Module implements a unified **FMP Data Abstraction Layer** (`fmp/`) for all Financial Modeling Prep API interactions. This module provides discoverable endpoints, two-tier caching, structured error handling, and backward-compatible wrappers.

### FMP Module Architecture

**Module Structure** (`fmp/`):
```
fmp/
├── __init__.py           # Module exports and quick-start documentation
├── client.py             # FMPClient: unified fetch interface with caching
├── registry.py           # Endpoint registry with full metadata (30+ endpoints)
├── cache.py              # Disk-based caching (Parquet + Zstandard)
├── compat.py             # Backward-compatible wrappers for data_loader.py
├── fx.py                 # FX conversion utilities (currency pair resolution, monthly FX rates)
└── exceptions.py         # Structured exception hierarchy
```

### FMPClient Usage

```python
from fmp import FMPClient, fetch

# Create client instance
fmp = FMPClient()

# Fetch data with automatic caching
prices = fmp.fetch("historical_price_adjusted", symbol="AAPL", **{"from": "2020-01-01"})
income = fmp.fetch("income_statement", symbol="AAPL", period="quarter")

# Discover endpoints (works without API key)
fmp.list_endpoints()                    # All endpoints
fmp.list_endpoints(category="analyst")  # Filter by category
fmp.describe("income_statement")        # Full documentation

# Convenience function using shared client
prices = fetch("historical_price_adjusted", symbol="AAPL")
```

### Registered Endpoints

| Category | Endpoint | Description |
|----------|----------|-------------|
| **prices** | `historical_price_eod` | End-of-day prices (OHLCV) |
| **prices** | `historical_price_adjusted` | Dividend-adjusted prices (total return) |
| **treasury** | `treasury_rates` | US Treasury rates (multiple maturities) |
| **dividends** | `dividends` | Dividend history (payment dates, amounts) |
| **search** | `search` | Company search by name/ticker |
| **search** | `profile` | Company profile (sector, industry, currency) |
| **fundamentals** | `income_statement` | Income statement data |
| **fundamentals** | `balance_sheet` | Balance sheet data |
| **fundamentals** | `cash_flow` | Cash flow statement data |
| **fundamentals** | `key_metrics` | Key financial metrics (P/E, ROE, etc.) |
| **fundamentals** | `ratios_ttm` | Trailing twelve-month financial ratios |
| **analyst** | `analyst_estimates` | Analyst EPS/revenue forecasts |
| **analyst** | `price_target` | Analyst price target summary |
| **analyst** | `price_target_consensus` | Price target consensus |
| **transcripts** | `earnings_transcript` | Earnings call transcripts |
| **screener** | `company_screener` | Screen stocks by fundamental criteria |
| **filings** | `sec_filings` | SEC filing history |
| **news** | `news_stock` | Stock-specific news articles |
| **news** | `news_general` | General market news |
| **news** | `news_press_releases` | Company press releases |
| **calendar** | `earnings_calendar` | Upcoming earnings dates |
| **calendar** | `dividends_calendar` | Upcoming dividend dates |
| **calendar** | `splits_calendar` | Upcoming stock splits |
| **calendar** | `ipos_calendar` | Upcoming IPOs |
| **peers** | `stock_peers` | Peer company lists |
| **market** | `biggest_gainers` | Top daily gainers |
| **market** | `biggest_losers` | Top daily losers |
| **market** | `most_actives` | Most actively traded stocks |
| **market** | `batch_index_quotes` | Batch index price quotes |
| **market** | `sector_performance_snapshot` | Sector performance data |
| **market** | `industry_performance_snapshot` | Industry performance data |
| **market** | `sector_pe_snapshot` | Sector P/E ratios |
| **market** | `industry_pe_snapshot` | Industry P/E ratios |
| **economic** | `economic_indicators` | Economic indicator time series |
| **economic** | `economic_calendar` | Economic event calendar |

### Exception Hierarchy

```python
from fmp import (
    FMPError,                 # Base exception
    FMPAPIError,              # API request failures
    FMPRateLimitError,        # HTTP 429 rate limit exceeded
    FMPAuthenticationError,   # Invalid/missing API key
    FMPEndpointError,         # Unknown endpoint name
    FMPValidationError,       # Parameter validation failures
    FMPEmptyResponseError,    # Empty API response
)
```

### Caching Architecture

**Two-Tier Caching**:
- **Disk Cache**: Parquet files with Zstandard compression for persistence
- **Monthly Staleness Protection**: Cache keys include month token for "latest" data requests

**Cache TTL Configuration**:
- `search`: Disabled (real-time results)
- `profile`: 168 hours (1 week)
- `analyst_estimates`, `price_target`: 24 hours
- Historical prices/fundamentals: Monthly refresh (no explicit TTL)

### Backward Compatibility Layer (`fmp/compat.py`)

The `compat.py` module provides drop-in replacements for legacy `data_loader.py` functions:

```python
from fmp.compat import (
    fetch_monthly_close,              # Month-end close prices
    fetch_monthly_total_return_price, # Dividend-adjusted prices
    fetch_monthly_treasury_rates,     # Treasury rates
    fetch_dividend_history,           # Dividend events
)
```

**International Ticker Resolution**:
All compat functions support the `fmp_ticker` and `fmp_ticker_map` parameters for international ticker resolution via `utils/ticker_resolver.py`.

### Adding New Endpoints

```python
from fmp.registry import register_endpoint, FMPEndpoint, EndpointParam, ParamType

register_endpoint(
    FMPEndpoint(
        name="new_endpoint",
        path="/new-endpoint",
        description="Description for discovery",
        category="category_name",
        params=[
            EndpointParam("symbol", ParamType.STRING, required=True),
            EndpointParam("period", ParamType.ENUM, enum_values=["annual", "quarter"]),
        ],
        cache_dir="cache_dir_name",
        cache_ttl_hours=24,  # Optional TTL
    )
)
```

## 🌍 International Ticker Resolution

The Risk Module implements international ticker resolution for Financial Modeling Prep API compatibility.

### Ticker Resolver (`utils/ticker_resolver.py`)

**Purpose**: Resolves provider-specific tickers (Plaid, SnapTrade) to FMP-compatible symbols for international securities.

**Resolution Strategy**:
1. If `exchange_mic` indicates US exchange, return ticker as-is
2. If `exchange_mic` maps to known suffix, append suffix (e.g., XLON → `.L`)
3. If MIC is missing/unknown, search FMP by company name + currency
4. Cache results to avoid repeated API calls (7-day TTL for resolved, 1-day for no-match)

**Key Functions**:
```python
from utils.ticker_resolver import (
    resolve_fmp_ticker,       # Full resolution with search fallback
    select_fmp_symbol,        # Simple selection (fmp_ticker > map > ticker)
    normalize_currency,       # Currency normalization (GBp → GBP)
    normalize_fmp_price,      # Minor currency conversion (pence → pounds)
    fmp_search,               # FMP company search
)
```

**Usage Example**:
```python
from utils.ticker_resolver import resolve_fmp_ticker

# Resolve UK stock
fmp_ticker = resolve_fmp_ticker(
    ticker="AZN",
    company_name="AstraZeneca PLC",
    currency="GBP",
    exchange_mic="XLON"
)
# Returns: "AZN.L"
```

### Exchange Mappings Configuration (`exchange_mappings.yaml`)

**Purpose**: Maps ISO-10383 MIC codes to FMP ticker suffixes, currency normalization rules, IBKR futures symbol mappings, and IBKR exchange routing.

**Structure**:
```yaml
# MIC to FMP suffix mappings
mic_to_fmp_suffix:
  XLON: ".L"    # London Stock Exchange
  XPAR: ".PA"   # Euronext Paris
  XTSE: ".TO"   # Toronto Stock Exchange
  XHKG: ".HK"   # Hong Kong Stock Exchange
  # ... additional exchanges

# US exchanges (skip resolution)
us_exchange_mics:
  - XNYS  # NYSE
  - XNAS  # NASDAQ
  - XASE  # NYSE American
  # ... additional US exchanges

# Minor currency conversion
minor_currencies:
  GBp:
    base_currency: GBP
    divisor: 100
  GBX:
    base_currency: GBP
    divisor: 100
  ZAc:
    base_currency: ZAR
    divisor: 100
  ILA:
    base_currency: ILS
    divisor: 100

# Currency normalization for matching
currency_aliases:
  GBX: GBP
  ZAC: ZAR
  ILA: ILS

# IBKR futures root symbol -> FMP commodity symbol
ibkr_futures_to_fmp:
  ES: ESUSD      # E-Mini S&P 500
  MES: ESUSD     # Micro E-Mini S&P 500
  GC: GCUSD      # Gold
  SI: SIUSD      # Silver
  CL: CLUSD      # Crude Oil
  ZN: ZNUSD      # 10Y Treasury Note
  # ... additional futures (see file for full list)

# IBKR exchange routing for ContFuture qualification
# Used by services/ibkr_historical_data.py
ibkr_futures_exchanges:
  ES:  { exchange: CME,   currency: USD }
  GC:  { exchange: COMEX, currency: USD }
  SI:  { exchange: COMEX, currency: USD }
  CL:  { exchange: NYMEX, currency: USD }
  ZN:  { exchange: CBOT,  currency: USD }
  # ... 19 futures root symbols total
```

### Database Integration

**Migration** (`database/migrations/20260201_add_fmp_ticker.sql`):
- Adds `fmp_ticker` column to `positions` table
- Auto-backfills US positions based on `exchange_mic`
- Preserves original ticker for provider reconciliation

**Backfill Script** (`scripts/backfill_fmp_tickers.py`):
```bash
# Backfill fmp_ticker for existing positions
python scripts/backfill_fmp_tickers.py --limit 100 --batch-size 50
```

## 🏗️ Service Architecture Layer

The Risk Module implements a sophisticated service architecture that provides enterprise-level capabilities with comprehensive caching, validation, and integration patterns.

### Service Layer Components

**Core Services** (`services/`):
- **`portfolio_service.py`** - Portfolio analysis and risk calculations with caching
- **`optimization_service.py`** - Portfolio optimization (min variance, max return) with solver management
- **`scenario_service.py`** - What-if analysis and scenario modeling with proxy injection
- **`stock_service.py`** - Individual stock analysis with factor decomposition
- **`returns_service.py`** - Expected returns management with auto-generation capabilities
- **`auth_service.py`** - Multi-provider authentication (Google, GitHub, Apple)
- **`service_manager.py`** - Central service orchestration and dependency injection

**Specialized Services**:
- **`async_service.py`** - Non-blocking portfolio operations for web interface
- **`factor_proxy_service.py`** - Dynamic factor proxy assignment and validation
- **`security_type_service.py`** - Security type classification with intelligent caching and FMP integration
- **`validation_service.py`** - Data validation and schema compliance checking
- **`cache_mixin.py`** - ServiceCacheMixin for intelligent caching with TTL
- **`position_service.py`** - Unified position orchestration across providers (Plaid, SnapTrade)
- **`trade_execution_service.py`** - Trade preview/execution via SnapTrade with confirm-then-execute flow
- **`ibkr_flex_client.py`** - IBKR Flex Query trade download, normalization, option symbol construction
- **`ibkr_historical_data.py`** - IBKR Gateway historical price fallback for futures (two-layer caching, thread-safe)
- **`ibkr_broker_adapter.py`** - IBKR broker adapter using ib_async for live trading
- **`ibkr_connection_manager.py`** - IBKR gateway connection lifecycle management
- **`snaptrade_broker_adapter.py`** - SnapTrade broker adapter for trade execution
- **`claude/`** - Claude AI integration services
  - **`chat_service.py`** - AI chat and conversation management
  - **`function_executor.py`** - Claude function execution engine
- **`portfolio/`** - Portfolio-specific services
  - **`context_service.py`** - Portfolio context management

**Service Capabilities**:
- **ServiceCacheMixin** - Intelligent caching with TTL and invalidation
- **Performance Monitoring** - Sub-100ms response times with resource tracking
- **Error Handling** - Graceful degradation with fallback mechanisms
- **Multi-User Support** - Complete data isolation between users

### Position Service & CLI

**Unified Position Orchestration Layer**:
The Risk Module includes a comprehensive position service and CLI for fetching and managing positions across brokerage providers.

**Position Service** (`services/position_service.py`):
- **Multi-Provider Support**: Unified interface for Plaid and SnapTrade positions
- **Fail-Fast Architecture**: Errors raised immediately (no partial results)
- **Column Normalization**: Standardizes provider columns into single schema
- **Consolidation Logic**: Consolidates by (ticker, currency) preserving multi-currency positions
- **Cash Preservation**: Cash stays as CUR:XXX; proxy mapping deferred to analysis-time

**Position Service Usage**:
```python
from services.position_service import PositionService
from core.result_objects import PositionResult

# Initialize service for user
service = PositionService(user_email="user@example.com")

# Fetch from specific provider
plaid_df = service.fetch_plaid_positions(consolidate=True)
snaptrade_df = service.fetch_snaptrade_positions(consolidate=True)

# Fetch all positions (returns PositionResult)
result: PositionResult = service.get_all_positions(consolidate=True)
```

**Positions CLI** (`run_positions.py`):
```bash
# Basic usage - show all positions
python run_positions.py --user-email user@example.com

# Plaid only with consolidation
python run_positions.py --user-email user@example.com --source plaid --consolidated

# Export to JSON
python run_positions.py --user-email user@example.com --format json --output positions.json

# Chain to risk analysis
python run_positions.py --user-email user@example.com --consolidated --to-risk
```

**CLI Parameters**:
| Parameter | Options | Description |
|-----------|---------|-------------|
| `--user-email` | (required) | User email for provider access |
| `--source` | `all`, `plaid`, `snaptrade` | Which brokerage source(s) to fetch |
| `--consolidated` | flag | Consolidate positions by ticker |
| `--detail` | flag | Show account-level detail (no consolidation) |
| `--format` | `json`, `cli` | Output format |
| `--output` | filepath | Write positions to JSON file |
| `--to-risk` | flag | Convert to PortfolioData and run risk analysis |

**PositionResult Object**:
```python
# PositionResult provides dual output formats
result = service.get_all_positions(consolidate=True)

# CLI output
print(result.to_cli_report())

# API response
json_data = result.to_api_response()

# Summary statistics
summary = result.to_summary()
print(f"Total Value: ${result.total_value:,.2f}")
print(f"Position Count: {result.position_count}")

# Monitor view with exposure and P&L metrics (excludes cash)
monitor_data = result.to_monitor_view(by_account=False)
monitor_cli = result.to_monitor_cli(by_account=True)
```

**Monitor View Features**:
- Excludes cash positions (no entry price concept)
- Computes provider-agnostic P&L using `(price - entry_price) * quantity`
- Groups summary totals by currency to avoid cross-currency aggregation
- Handles missing/invalid cost basis, price, or quantity gracefully

### MCP Server Integration (Claude Code)

**Model Context Protocol Server for Claude Code**:
The Risk Module includes a FastMCP server that exposes portfolio analysis tools directly to Claude Code for AI-assisted portfolio management.

**MCP Server** (`mcp_server.py`):
- **FastMCP Framework**: Lightweight MCP server using the `fastmcp` library
- **Tool Registration**: Exposes tools to Claude Code via `@mcp.tool()` decorator
- **User Resolution**: Uses `RISK_MODULE_USER_EMAIL` environment variable for default user
- **Server Name**: `portfolio-mcp` with portfolio analysis instructions

**MCP Server Setup**:
```bash
# Register with Claude Code (with default user email)
cd /Users/henrychien/Documents/Jupyter/risk_module
claude mcp add portfolio-mcp -e RISK_MODULE_USER_EMAIL=you@example.com -- python mcp_server.py

# Run standalone for testing
python mcp_server.py
```

**Available MCP Tools** (portfolio-mcp, 16 tools):

| Tool | Key Parameters | Description |
|------|------------|-------------|
| `get_positions` | `consolidate`, `format`, `brokerage`, `by_account`, `refresh_provider` | Fetch portfolio positions from brokerage accounts |
| `get_risk_score` | `portfolio_name`, `format` | 0-100 risk score with compliance status |
| `get_risk_analysis` | `portfolio_name`, `format`, `include` | Comprehensive risk analysis (30+ metrics) |
| `get_performance` | `portfolio_name`, `benchmark_ticker`, `mode`, `source`, `format` | Performance metrics and benchmark comparison (hypothetical or realized) |
| `analyze_stock` | `ticker`, `start_date`, `end_date`, `format` | Single stock/ETF volatility, beta, factor analysis |
| `run_optimization` | `optimization_type`, `portfolio_name`, `format` | Portfolio weight optimization (min_variance or max_return) |
| `run_whatif` | `target_weights`, `delta_changes`, `scenario_name`, `format` | What-if scenario risk impact analysis |
| `get_factor_analysis` | `analysis_type`, `categories`, `include_rate_sensitivity`, `format` | Factor correlations, performance, and returns analysis |
| `get_factor_recommendations` | `mode`, `overexposed_factor`, `correlation_threshold`, `format` | Factor-based hedge/offset recommendations |
| `get_income_projection` | `projection_months`, `format` | Dividend income projection from current holdings |
| `suggest_tax_loss_harvest` | `min_loss`, `sort_by`, `include_wash_sale_check`, `source`, `format` | FIFO tax-lot analysis for loss harvesting |
| `preview_trade` | `ticker`, `quantity`, `side`, `order_type`, `limit_price` | Preview a trade (confirm-then-execute flow) |
| `execute_trade` | `preview_id` | Execute a previously-previewed trade |
| `get_orders` | `account_id`, `state`, `days`, `format` | Order history and brokerage-reconciled statuses |
| `cancel_order` | `account_id`, `order_id` | Cancel an open brokerage order |
| `check_exit_signals` | `ticker`, `shares`, `account_id`, `format` | Evaluate exit signals (momentum, regime rules) for a position |

**FMP MCP Server** (`fmp_mcp_server.py`, 14 tools):

| Tool | Key Parameters | Description |
|------|------------|-------------|
| `fmp_fetch` | `endpoint`, `symbol`, `period`, `limit` | Fetch data from any registered FMP endpoint |
| `fmp_search` | `query`, `limit`, `exchange` | Search for companies by name |
| `fmp_profile` | `symbol` | Get company profile details |
| `fmp_list_endpoints` | `category` | Discover available FMP endpoints |
| `fmp_describe` | `endpoint` | Get endpoint parameter documentation |
| `screen_stocks` | criteria dict | Screen stocks by fundamental criteria |
| `compare_peers` | `ticker`, metrics | Compare a stock against its peers |
| `get_technical_analysis` | `ticker` | Composite technical analysis (trend, momentum, volatility) |
| `get_economic_data` | `indicator`, `country` | Economic indicators and calendar events |
| `get_sector_overview` | (none required) | Sector/industry performance and P/E overview |
| `get_market_context` | (none required) | Market snapshot: indices, sectors, movers, events |
| `get_news` | `tickers`, `type`, `limit` | News articles for stocks or broad market |
| `get_events_calendar` | `type`, `from_date`, `to_date` | Corporate event calendars (earnings, dividends, splits, IPOs) |
| `get_earnings_transcript` | `ticker`, `year`, `quarter` | Earnings call transcript parsing (remarks, Q&A, per-speaker) |

**FMP MCP Server Setup**:
```bash
claude mcp add fmp-mcp -- python3 fmp_mcp_server.py
```

**Tool Implementation Pattern** (`mcp_tools/`):
```python
# mcp_tools/positions.py - Tool implementation
def get_positions(
    user_email: Optional[str] = None,
    consolidate: bool = True,
    format: Literal["full", "summary", "list", "by_account"] = "full",
    brokerage: Optional[str] = None,
    use_cache: bool = True,
    force_refresh: bool = False
) -> dict:
    """Returns position data with status field for Claude consumption"""
    user = user_email or get_default_user()
    service = PositionService(user)
    result = service.get_all_positions(
        use_cache=use_cache,
        force_refresh=force_refresh,
        consolidate=consolidate
    )
    return result.to_api_response()
```

**Tool Response Format**:
```python
# Success response
{"status": "success", "data": {...}, "total_value": 150000.00, "position_count": 25}

# Error response
{"status": "error", "error": "No user configured"}
```

**Default User Configuration** (`settings.py`):
```python
def get_default_user() -> str | None:
    """Get default user email for MCP tools and CLI commands.

    Reads from RISK_MODULE_USER_EMAIL environment variable, set in:
    - .mcp.json for Claude Code MCP server
    - Shell environment for CLI usage
    - .env for local development
    """
    return os.getenv('RISK_MODULE_USER_EMAIL')
```

### Claude AI Integration

**Enhanced AI-Powered Analytics with Vercel AI SDK Integration**:
The Risk Module includes sophisticated Claude AI integration for conversational portfolio analysis, now enhanced with Vercel AI SDK-compatible streaming capabilities and modern React components.

**Frontend Architecture Components**:
```typescript
// Enhanced chat component structure
frontend/src/components/
├── chat/
│   ├── AIChat.tsx              # Modal chat interface (550x750px)
│   ├── ChatContext.tsx         # Shared chat state management
│   ├── shared/
│   │   └── ChatCore.tsx        # Centralized chat logic (~640 lines)
└── layout/
    └── ChatInterface.tsx       # Full-screen chat interface

// Enhanced streaming hook
frontend/src/features/external/hooks/
└── usePortfolioChat.ts         # Vercel AI SDK-compatible streaming
```

**Key Features**:
- **Streaming API Integration**: Token-by-token delivery with enhanced status tracking
- **Context-Aware Responses**: AI maintains portfolio context throughout conversations
- **SharedChat Architecture**: Zero code duplication between modal and full-screen interfaces
- **Enhanced UI Components**: AIChat modal and ChatInterface for seamless user experience
- **Message Management**: Edit, delete, retry, regenerate functionality
- **File Upload Support**: Multi-modal message support (implementation in progress)

**AI Function Registry** (`ai_function_registry.py`):
- **Centralized Function Definitions** - Single source of truth for 16 Claude functions
- **Dynamic Routing** - Eliminates hardcoded function dispatch logic
- **Schema Validation** - JSON schema validation for Claude API parameters
- **Function Executor** (`services/claude/function_executor.py`) - Modernized Claude function execution

**Available Claude Functions** (16 total):
```python
# Portfolio Analysis Functions
- run_portfolio_analysis() - Complete risk analysis with factor decomposition
- get_risk_score() - Credit-score style risk rating (1-100)
- calculate_portfolio_performance() - Performance metrics and benchmarking

# Optimization Functions (with automatic expected returns)
- optimize_minimum_variance() - Minimum risk portfolio optimization
- optimize_maximum_return() - Maximum return with risk constraints, auto-handles missing returns
- estimate_expected_returns() - Auto-generate returns using 10-year industry ETF methodology
- set_expected_returns() - Custom return assumptions override system estimates

# Scenario & Stock Analysis
- run_what_if_scenario() - Scenario modeling with automatic proxy injection for new tickers
- analyze_stock() - Individual stock factor analysis with auto-generated proxies

# Portfolio Management
- create_portfolio_scenario() - Create new portfolio from positions data
- setup_new_portfolio() - Generate factor proxies for user's portfolio
- list_portfolios() - Multi-user portfolio listing with authentication
- switch_portfolio() - Switch active portfolio context

# Risk Management
- view_current_risk_limits() - Show risk limits for user
- update_risk_limits() - Update user's risk limit settings
- reset_risk_limits() - Reset risk limits to default values
```

**Claude Function Improvements**:
- **Automatic Expected Returns**: `optimize_max_return()` now auto-generates missing returns using industry ETF methodology and Treasury rates for cash proxies
- **Intelligent Cash Handling**: Cash positions (SGOV, etc.) use Treasury rates instead of industry ETF data
- **Enhanced What-If Analysis**: Automatic ticker detection and proxy assignment for new securities in scenarios
- **10-Year Lookback**: Extended from 5-year to 10-year default lookback period for more stable estimates

### Security Type Service & Admin Tools Architecture

**Enhanced Security Classification System**:
The Risk Module implements a sophisticated Security Type Service that addresses the critical issue where DSU and other mutual funds were incorrectly treated as individual stocks (80% crash scenarios) instead of mutual funds (40% crash scenarios).

**Security Type Service** (`services/security_type_service.py`):
- **Intelligent Classification**: Automatic security type detection using Financial Modeling Prep API
- **PostgreSQL Caching**: Database-backed caching with 90-day TTL for performance optimization
- **Fallback Logic**: Graceful degradation when API is unavailable
- **Health Monitoring**: Comprehensive health checks and cache statistics
- **Force Refresh**: Manual refresh capabilities for problematic tickers

**Admin Tools Module** (`admin/manage_security_types.py`):
- **Cache Management**: Monitor security type cache performance and health
- **Bulk Operations**: Refresh stale entries older than specified threshold
- **Data Export/Import**: Backup and restore security type classifications
- **Operational Tools**: Command-line interface for system administrators

**Administrative Commands**:
```bash
# Monitor cache performance
python admin/manage_security_types.py stats

# Health check
python admin/manage_security_types.py health

# List cached security types
python admin/manage_security_types.py list --limit 50

# Force refresh specific ticker
python admin/manage_security_types.py refresh DSU

# Bulk refresh stale entries
python admin/manage_security_types.py bulk-refresh --days 90

# Export/Import for backup
python admin/manage_security_types.py export security_types.json
python admin/manage_security_types.py import security_types.json
```

**Database Schema Enhancement**:
```sql
-- Security types table with intelligent caching
CREATE TABLE security_types (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(100) UNIQUE NOT NULL,
    security_type VARCHAR(50) NOT NULL,  -- 'equity', 'etf', 'mutual_fund', 'cash'
    fmp_data JSONB,                     -- Raw FMP API response
    last_updated TIMESTAMP DEFAULT NOW(),
    created_at TIMESTAMP DEFAULT NOW(),
    
    INDEX idx_security_types_ticker (ticker),
    INDEX idx_security_types_updated (last_updated),
    INDEX idx_security_types_type (security_type)
);
```

**Business Impact**:
- **Correct Risk Scenarios**: DSU now properly classified as mutual fund with 40% crash scenario
- **Data Quality**: Prevents incorrect extreme risk calculations due to misclassification
- **Operational Monitoring**: Admin tools provide visibility into classification accuracy
- **Performance**: 90-day caching reduces API calls while ensuring data freshness

### Cache Management Utilities

**Enhanced Cache Administration**:
The portfolio risk analysis system uses extensive caching for both price data and dividend calculations. The Risk Module includes specialized utilities for managing and maintaining these caches.

**Price Cache Management** (`admin/clear_price_cache.py`):
- **Selective Clearing**: Clear cache by ticker (AAPL, MSFT) or data type (close, total return, treasury)
- **Pattern Matching**: Intelligent file pattern recognition for different cache types
- **Interactive Confirmation**: Safe deletion with user confirmation prompts
- **Comprehensive Reporting**: Detailed feedback on cache operations and file counts

**Cache File Patterns**:
- Close prices: `TICKER_hash.parquet` (e.g., `AAPL_abc12345.parquet`)
- Total return: `TICKER_tr_v1_hash.parquet` (e.g., `AAPL_tr_v1_abc12345.parquet`)
- Treasury rates: `TREASURY_hash.parquet`, `DGS*_hash.parquet`

**Dividend Cache Management** (`admin/clear_dividend_cache.py`):
- **Version Management**: Clear cache by version (v1, v2) or specific ticker
- **Selective Operations**: Target specific dividend data for cache cleanup
- **Safe Deletion**: Interactive prompts prevent accidental data loss

**Administrative Commands**:
```bash
# Price cache management
python3 admin/clear_price_cache.py --all                    # Clear all price cache
python3 admin/clear_price_cache.py --ticker AAPL           # Clear only AAPL cache
python3 admin/clear_price_cache.py --data-type close       # Clear close prices
python3 admin/clear_price_cache.py --data-type treasury    # Clear treasury data

# Dividend cache management
python3 admin/clear_dividend_cache.py --all                # Clear all dividend cache
python3 admin/clear_dividend_cache.py --version v2         # Clear v2 cache files
python3 admin/clear_dividend_cache.py --ticker DSU         # Clear DSU dividend data
```

**Use Cases**:
- **Data Quality Issues**: Fresh data retrieval after pricing discrepancies

### Reference Data Management & Factor Intelligence Admin Tools

**Enhanced Reference Data Administration**:
The Risk Module includes comprehensive tools for managing the reference data mappings used throughout the system, with enhanced **Factor Intelligence** support for advanced correlation analysis and performance profiling.

**Reference Data Manager** (`admin/manage_reference_data.py`):
- **Multi-Type Support**: Manages cash proxies, exchange factors, industry mappings, asset class proxies
- **Database Synchronization**: Bulk sync operations from YAML configuration files
- **ETF Proxy Validation**: Real-time validation of ETF proxy coverage and data quality
- **Cache Integration**: Automatic service cache clearing after reference data updates
- **Dry-Run Support**: Preview changes before applying database updates

**Key Reference Data Types**:
- **Cash Proxies**: Currency → ETF mappings for cash position analysis (`USD` → `SGOV`)
- **Industry Mappings**: Industry → sector ETF mappings with sector group support (`Technology` → `XLK`)
- **Exchange Factors**: Exchange → style factor mappings (`NASDAQ` → `{market: SPY, momentum: MTUM, value: IWD}`)
- **Asset Class Proxies**: ✨ **NEW** - Asset class → ETF mappings (`bond` → `{UST10Y: IEF, corporate: LQD}`)

**Enhanced Features**:
- **Sector Group Support**: Industry mappings now include sector groups (defensive, cyclical, etc.)
- **Asset Class Integration**: Comprehensive asset class proxy system for bonds, commodities, crypto
- **Exchange Factor Management**: Style and market factor mappings by exchange
- **Bulk Sync Operations**: YAML-to-database synchronization with validation
- **Coverage Validation**: ETF proxy data quality and coverage analysis

**Administrative Commands**:
```bash
# List current mappings
python3 admin/manage_reference_data.py cash list
python3 admin/manage_reference_data.py industry list
python3 admin/manage_reference_data.py exchange list
python3 admin/manage_reference_data.py asset-proxy list

# Add/update mappings
python3 admin/manage_reference_data.py industry add "Technology" XLK --asset-class equity --group growth
python3 admin/manage_reference_data.py asset-proxy add bond UST10Y IEF --desc "10-Year Treasury ETF"
python3 admin/manage_reference_data.py exchange add NASDAQ market SPY

# Bulk sync from YAML files
python3 admin/manage_reference_data.py cash sync-from-yaml --dry-run
python3 admin/manage_reference_data.py cash sync-from-yaml
python3 admin/manage_reference_data.py exchange sync-from-yaml exchange_etf_proxies.yaml
python3 admin/manage_reference_data.py asset-proxy sync-from-yaml asset_etf_proxies.yaml

# Delete mappings
python3 admin/manage_reference_data.py industry delete "Old Industry" --force
python3 admin/manage_reference_data.py asset-proxy clear-class crypto --force
```

**ETF Proxy Validation Tool** (`admin/verify_proxies.py`):
- **Coverage Analysis**: Validates ETF proxy data availability and quality
- **Factor Intelligence Compatible**: Uses same validation logic as factor intelligence correlations
- **Priority Classification**: Categorizes issues by urgency (HIGH, MEDIUM, LOW priority)
- **Date Range Validation**: Analyzes coverage gaps relative to analysis periods
- **Bulk Validation**: Validates all proxy types (Asset, Industry, Exchange, Cash)

**Proxy Validation Commands**:
```bash
# Basic validation (default)
python3 admin/verify_proxies.py
python3 admin/verify_proxies.py --min-months 24

# Detailed coverage analysis (Factor Intelligence compatible)
python3 admin/verify_proxies.py --detailed
python3 admin/verify_proxies.py --detailed --start 2022-01-01 --end 2024-12-31

# Quick subset validation
python3 admin/verify_proxies.py --detailed --limit 20
```

**Validation Output**:
- **🔴 High Priority**: Likely delisted ETFs (data ends >24 months ago) - Replace immediately
- **🟡 Medium Priority**: Limited lifespan ETFs (gaps at both start and end) - Evaluate replacement
- **🔵 Low Priority**: New ETFs (data starts late) - Monitor for future analysis
- **✅ Sufficient**: ETFs with adequate coverage for the analysis period

**Database Schema Enhancements**:
```sql
-- Asset class ETF proxies table
CREATE TABLE asset_etf_proxies (
    id SERIAL PRIMARY KEY,
    asset_class VARCHAR(50) NOT NULL,    -- 'bond', 'commodity', 'crypto', etc.
    proxy_key VARCHAR(100) NOT NULL,     -- 'UST10Y', 'gold', 'BTC', etc.
    etf_ticker VARCHAR(20) NOT NULL,     -- 'IEF', 'GLD', 'IBIT', etc.
    is_alternate BOOLEAN DEFAULT FALSE,  -- Primary vs alternate proxies
    priority INTEGER DEFAULT 100,       -- Lower number = higher priority
    description TEXT,                    -- Optional description
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(asset_class, proxy_key, etf_ticker),
    INDEX idx_asset_proxies_class (asset_class),
    INDEX idx_asset_proxies_key (proxy_key),
    INDEX idx_asset_proxies_ticker (etf_ticker)
);

-- Enhanced industry proxies with sector groups
ALTER TABLE industry_proxies ADD COLUMN sector_group VARCHAR(50);
ALTER TABLE industry_proxies ADD COLUMN asset_class VARCHAR(50);
CREATE INDEX idx_industry_sector_group ON industry_proxies (sector_group);
```

**Business Impact**:
- **Factor Intelligence Support**: Enhanced proxy system enables advanced correlation analysis
- **Sector Preference System**: Sector grouping enables preference-based analysis ordering
- **Asset Class Integration**: Comprehensive asset class coverage for macro analysis
- **Data Quality Assurance**: Validation tools ensure reliable factor intelligence calculations
- **Operational Efficiency**: Bulk sync operations streamline reference data maintenance
- **Algorithm Changes**: Cache cleanup when calculation methods are updated
- **Storage Management**: Regular maintenance to prevent disk space issues
- **Troubleshooting**: Cache clearing for debugging stale data problems

## 🚀 FastAPI & Response Validation

The Risk Module has migrated from Flask to **FastAPI 0.116.0** for enhanced performance, automatic documentation, and type safety.

### FastAPI Implementation

**Core Benefits**:
- **High Performance**: Async/await support for non-blocking request handling with uvicorn
- **Automatic Documentation**: Interactive API docs at `/docs` with OpenAPI 3.0 schema  
- **Type Safety**: Python type hints for request/response validation
- **Async Operations**: Support for concurrent database and API operations
- **Modern Architecture**: Replaces Flask with FastAPI for better performance and developer experience

**Migration Architecture**:
```python
# FastAPI app with middleware
app = FastAPI(title="Risk Module API", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"])
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

# Rate limiting with SlowAPI (FastAPI-compatible)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
```

### Pydantic Response Models

**Comprehensive Response Validation** (`models/` directory):

**Direct API Models** (Stateless analysis):
- `DirectPortfolioResponse` (`directportfolioresponse.py`) - Direct portfolio analysis
- `DirectStockResponse` (`directstockresponse.py`) - Individual stock analysis  
- `DirectPerformanceResponse` (`directperformanceresponse.py`) - Performance measurement
- `DirectOptimizeMinVarResponse` (`directoptimizeminvarresponse.py`) - Minimum variance optimization
- `DirectOptimizeMaxRetResponse` (`directoptimizemaxretresponse.py`) - Maximum return optimization
- `DirectWhatIfResponse` (`directwhatifresponse.py`) - Scenario analysis
- `DirectInterpretResponse` (`directinterpretresponse.py`) - AI interpretation

**Database API Models** (Stateful with user sessions):
- `AnalyzeResponse` (`analyzeresponse.py`) - Portfolio risk analysis results
- `PerformanceResponse` (`performanceresponse.py`) - Performance metrics and benchmarking
- `RiskScoreResponse` (`riskscoreresponse.py`) - Credit-style risk scoring
- `InterpretResponse` (`interpretresponse.py`) - AI-powered portfolio insights
- `MinVarianceResponse` (`minvarianceresponse.py`) - Portfolio optimization results
- `MaxReturnResponse` (`maxreturnresponse.py`) - Return optimization with constraints
- `WhatIfResponse` (`whatifresponse.py`) - Scenario modeling results

**System Models**:
- `HealthResponse` (`healthresponse.py`) - API health check status
- `RiskSettingsResponse` (`risksettingsresponse.py`) - Risk configuration management
- `PortfoliosListResponse` (`portfolioslistresponse.py`) - User portfolio management
- `CurrentPortfolioResponse` (`currentportfolioresponse.py`) - Active portfolio details
- `PortfolioAnalysisResponse` (`portfolioanalysisresponse.py`) - Comprehensive analysis results

**Modular Response Architecture**:
```python
# Each response model is a separate file for maintainability
# models/analyzeresponse.py
class AnalyzeResponse(BaseModel):
    """Portfolio analysis response model"""
    risk_results: Dict[str, Any]
    portfolio_metadata: Dict[str, Any]
    analysis_metadata: Dict[str, Any]
    # ... additional fields

# models/response_models.py - Central registry
from .analyzeresponse import AnalyzeResponse
from .performanceresponse import PerformanceResponse
# ... imports for all response models
```

**Response Validation Toggle**:
```python
# Environment-based validation control
DISABLE_PYDANTIC_VALIDATION = os.getenv('DISABLE_PYDANTIC_VALIDATION', '0')

def get_response_model(model_class):
    """Conditionally return response model for gradual migration"""
    if DISABLE_PYDANTIC_VALIDATION.lower() in ('1', 'true', 'yes'):
        return None  # Disable validation during migration
    return model_class
```

**Endpoint Implementation**:
```python
@app.post("/api/analyze", response_model=get_response_model(AnalyzeResponse))
async def analyze_portfolio(request: Request):
    """Portfolio risk analysis with Pydantic validation"""
    result = portfolio_service.analyze_portfolio(user_key, portfolio_name)
    return result.to_api_response()  # Auto-validated against Pydantic model
```

### FastAPI Application Startup

**Development Mode**:
```bash
# Start FastAPI with hot reloading
uvicorn app:app --host 0.0.0.0 --port 5001 --reload

# Alternative: Direct Python execution
python app.py
```

**Production Mode**:
```bash
# Production server with Gunicorn
gunicorn app:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:5001
```

**Interactive Documentation**:
- **Swagger UI**: http://localhost:5001/docs
- **ReDoc**: http://localhost:5001/redoc
- **OpenAPI Schema**: http://localhost:5001/openapi.json

## 🔄 Dual-Mode Interface Pattern

A critical architectural pattern that enables **multiple consumer types** (CLI, API, React Frontend, Claude AI) to access the same core business logic with **guaranteed output consistency**.

### The Challenge

The system must support four fundamentally different consumption patterns:
- **CLI Users**: `python run_risk.py --portfolio portfolio.yaml` → formatted text output
- **API Clients**: `POST /api/analyze` → structured JSON data
- **React Frontend**: Component-based dashboard with real-time updates
- **Claude AI**: `analyze_portfolio()` → human-readable formatted reports

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

### Result Objects Functions

All major analysis functions now return Result Objects with complete CLI/API alignment:
- `run_portfolio()` → `RiskAnalysisResult` - Portfolio risk analysis
- `run_what_if()` → `WhatIfResult` - Scenario analysis  
- `run_min_variance()` / `run_max_return()` → `OptimizationResult` - Portfolio optimization
- `run_stock()` → `StockAnalysisResult` - Individual stock analysis
- `run_portfolio_performance()` → `PerformanceResult` - Performance metrics
- `run_and_interpret()` → `InterpretationResult` - AI interpretation services
- `run_risk_score()` → `RiskScoreResult` - Risk scoring analysis

**Result Objects Architecture Complete**: All functions use the single source of truth pattern with dual serialization methods (`to_cli_report()` and `to_api_response()`)

## 🏗️ Architecture Layers

The system follows a **clean 3-layer architecture** with clear separation of concerns:

```
┌─────────────────────────────────────────────────────────────┐
│                    LAYER 1: ROUTES LAYER                     │
│                    (User Interface)                          │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ CLI Interface   │  │ API Interface   │  │ AI Interface │ │
│  │ run_risk.py     │  │ routes/         │  │ routes/      │ │
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
│  │ Scenario        │  │ Performance     │  │ Asset Class  │ │
│  │ Analysis        │  │ Analysis        │  │ Performance  │ │
│  │ core/scenario_  │  │ core/performance│  │ core/asset_  │ │
│  │ analysis.py     │  │ _analysis.py    │  │ class_perf.py│ │
│  └─────────────────┘  └─────────────────┘  └──────────────┘ │
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐ │
│  │ Interpretation  │  │ Constants &     │  │ Data Objects │ │
│  │ core/           │  │ Validation      │  │ core/data_   │ │
│  │ interpretation  │  │ core/constants. │  │ objects.py   │ │
│  │ .py             │  │ py              │  │              │ │
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

## 🌐 React Frontend Architecture

The Risk Module includes a production-ready React frontend with sophisticated component architecture, real-time data flow, and enterprise-grade user experience.

### Frontend Architecture Overview

**Technology Stack:**
- **React 19.1.0** with TypeScript for type-safe component development
- **React Query (TanStack Query 5.83.0)** for server state management and caching
- **React Router 6.30.1** for navigation and route management
- **Tailwind CSS 3.4.17** for utility-first styling with Shadcn/ui and Radix UI components  
- **Recharts** for financial data visualization
- **Zustand 4.5.0** for client-side state management
- **AI SDK 5.0.19** for streaming AI responses and chat integration
- **Jest + React Testing Library** for comprehensive testing

### Component Architecture (`frontend/src/`)

**Application Layer:**
- **`App.tsx`** - Root application component with routing
- **`AppOrchestrator.tsx`** - Main application orchestrator
- **`apps/DashboardApp.tsx`** - Primary dashboard application
- **`apps/LandingApp.tsx`** - Authentication and landing experience

**Service Layer (`chassis/services/`):**
- **`APIService.ts`** - Centralized API communication with error handling
- **`AuthService.ts`** - Multi-provider authentication (Google OAuth)
- **`RiskAnalysisService.ts`** - Risk analysis data fetching and caching
- **`PlaidService.ts`** - Plaid integration for brokerage account data
- **`ServiceContainer.ts`** - Dependency injection container for services

**Data Adapters (`adapters/`):**
- **`RiskAnalysisAdapter.ts`** - Transforms API responses for risk analysis views
- **`PerformanceAdapter.ts`** - Transforms performance data for charts and metrics
- **`PortfolioSummaryAdapter.ts`** - Transforms portfolio data for summary views
- **`RiskScoreAdapter.ts`** - Transforms risk score data for visualization

**Dashboard Architecture (`components/dashboard/`):**
```
components/dashboard/
├── shared/                              # Shared dashboard components
│   └── charts/                          # Chart components
└── views/
    └── modern/                          # Modern view containers
        ├── AssetAllocationContainer.tsx     # Asset allocation analysis
        ├── HoldingsViewModernContainer.tsx  # Portfolio holdings view
        ├── PerformanceViewContainer.tsx     # Performance analytics
        ├── PortfolioOverviewContainer.tsx   # Portfolio overview
        ├── RiskAnalysisModernContainer.tsx  # Factor analysis + risk decomposition
        ├── RiskSettingsContainer.tsx        # Risk settings management
        ├── ScenarioAnalysisContainer.tsx    # What-if scenario modeling
        ├── StockLookupContainer.tsx         # Individual stock research
        └── StrategyBuilderContainer.tsx     # Strategy builder
```

**Chart Components (`components/dashboard/shared/charts/`):**
- **`RiskContributionChart.tsx`** - Interactive risk contribution visualization
- **`PerformanceLineChart.tsx`** - Time series performance charts
- **`RiskRadarChart.tsx`** - Multi-dimensional risk radar visualization
- **`VarianceBarChart.tsx`** - Factor variance decomposition charts

**Data Flow Architecture:**
```
User Interaction → Component → Custom Hook → React Query → API Service → Backend
                                      ↓
                              Cache Management → Re-render → Updated UI
```

### Key Frontend Features

**Real-Time Data Management:**
- **React Query Integration** - Automatic caching, background updates, optimistic updates
- **Smart Invalidation** - Intelligent cache invalidation on portfolio changes
- **Error Boundaries** - Graceful error handling with user-friendly messages
- **Loading States** - Sophisticated loading indicators for async operations
- **Enhanced Cache Architecture** - Complete resolution of cache conflicts between legacy and modern UI patterns
- **Performance Data Isolation** - Separate cache keys prevent data format collisions (`['performance-raw']` vs `['performance']`)
- **Provider-Scoped Cleanup** - Enhanced connection management with proper database cleanup

**Authentication Flow:**
```typescript
// Multi-provider authentication with session management
const { user, login, logout } = useAuthFlow();

// Google OAuth integration
<GoogleSignInButton onSuccess={handleGoogleAuth} />
```

**Portfolio Integration:**
```typescript
// Real-time portfolio analysis
const { data: analysis, isLoading } = useRiskAnalysis(portfolioId);
const { data: performance } = usePerformance(portfolioId);
const { data: holdings } = usePortfolioSummary(portfolioId);
```

**Chart Integration:**
```typescript
// Dynamic chart rendering with live data
<RiskContributionChart 
  data={analysis.risk_contributions}
  onSliceClick={handleDrillDown}
/>
```

## 🎯 Result Objects Architecture

### Architecture Evolution: From Raw Dicts to Result Objects

The system has undergone a major refactoring to implement **Result Objects as the Single Source of Truth**. This addresses previous issues with data duplication, inconsistent outputs, and complex dual-mode logic.

#### Before: Factory Method Pattern (Deprecated)
```python
# Old pattern - factory methods create result objects from raw data
raw_data = build_portfolio_view(filepath)
result = RiskAnalysisResult.from_build_portfolio_view(raw_data, metadata)
```

#### After: Direct Result Object Creation
```python
# New pattern - core functions create and return result objects directly
def analyze_portfolio(filepath) -> RiskAnalysisResult:
    # Load data using data layer
    portfolio_data = build_portfolio_view(filepath)
    
    # Perform analysis
    risk_analysis = calculate_risk_metrics(portfolio_data)
    
    # Create and return Result Object with all data
    return RiskAnalysisResult(
        portfolio_summary=portfolio_data,
        risk_analysis=risk_analysis,
        formatted_output=generate_cli_report(...)
    )
```

### Result Objects Features

Each Result Object provides multiple output formats:

```python
class RiskAnalysisResult:
    """Structured result object for portfolio risk analysis."""
    
    def to_api_response(self) -> Dict[str, Any]:
        """Return JSON-safe dictionary for API responses."""
        return {
            "portfolio_summary": self.portfolio_summary,
            "risk_analysis": self.risk_analysis,
            "metadata": self.analysis_metadata
        }
    
    def to_cli_report(self) -> str:
        """Return formatted text report for CLI display."""
        return self.formatted_output
    
    def get_summary(self) -> Dict[str, str]:
        """Return key metrics as simple dictionary."""
        return {
            "total_value": f"${self.portfolio_summary['total_value']:,.2f}",
            "volatility": f"{self.risk_analysis['volatility_annual']:.2%}",
            "risk_score": str(self.risk_analysis['risk_score'])
        }
```

### Available Result Objects

All analysis functions return typed Result Objects (13 classes):

| Result Object | Source Module | Purpose |
|---------------|---------------|---------|
| `PositionResult` | `core.result_objects` | Position data with monitor view and P&L metrics |
| `RiskAnalysisResult` | `core.result_objects` | Portfolio risk analysis results |
| `WhatIfResult` | `core.result_objects` | Scenario analysis results |
| `OptimizationResult` | `core.result_objects` | Portfolio optimization results |
| `StockAnalysisResult` | `core.result_objects` | Individual stock analysis results |
| `PerformanceResult` | `core.result_objects` | Performance metrics and benchmarking |
| `InterpretationResult` | `core.result_objects` | AI interpretation and insights |
| `RiskScoreResult` | `core.result_objects` | Risk scoring and assessment |
| `FactorCorrelationResult` | `core.result_objects` | Factor correlation matrices and sensitivity overlays |
| `FactorPerformanceResult` | `core.result_objects` | Factor risk/return profiles |
| `FactorReturnsResult` | `core.result_objects` | Trailing-window factor returns snapshots |
| `OffsetRecommendationResult` | `core.result_objects` | Single-factor hedge/offset recommendations |
| `PortfolioOffsetRecommendationResult` | `core.result_objects` | Portfolio-level offset recommendations |

### Benefits of Result Objects Architecture

1. **Single Source of Truth**: All output formats derive from the same data
2. **Guaranteed Consistency**: CLI and API cannot show different results
3. **Simplified Dual-Mode**: Reduced from ~100 lines to ~10 lines per function
4. **Rich Business Logic**: Computed properties, validation, and formatting
5. **Type Safety**: Structured objects with clear interfaces

### Recent Architecture Enhancements

**New Ticker Detection and Auto-Proxy Assignment**:
- **What-If Scenarios**: Automatic detection of new tickers in scenario changes (e.g., `"AAPL:+500bp,SPY:-200bp"`)
- **Proxy Auto-Assignment**: New tickers automatically receive factor proxy assignments
- **Seamless Integration**: New securities seamlessly integrated into existing portfolio analysis
- **Risk Impact Analysis**: Before/after risk comparison with detailed factor exposure changes

**Claude Function Executor Modernization**:
- **RiskLimitsData Integration**: Modernized to use `RiskLimitsData` objects instead of file-based risk limits
- **Object-Oriented Risk Management**: Enhanced type safety and validation for risk limit operations
- **Database Integration**: Full integration with database-backed risk limits management

**Expected Returns Auto-Generation**:
- **Automatic Coverage**: Max return optimization now automatically handles missing expected returns
- **10-Year Lookback**: Default analysis period increased from 5 to 10 years for stability
- **Industry ETF Methodology**: Uses industry ETF CAGR for equity expected returns
- **Treasury Rate Integration**: Cash proxies (SGOV) use Treasury rates for expected returns
- **No Manual Intervention**: Eliminated need for manual expected returns setup before optimization
6. **Easy Maintenance**: Add field once, works across all outputs

### Key Architectural Benefits

1. **Single Source of Truth**: All interfaces call the same core business logic
2. **Dual-Mode Support**: Every function works in both CLI and API modes
3. **Clean Separation**: Routes handle UI, Core handles logic, Data handles persistence
4. **Perfect Compatibility**: Existing code works identically
5. **Enterprise Architecture**: Professional structure suitable for production

## 🔄 Data Flow Architecture

### Current Direct API Architecture

The system implements **Direct API Endpoints** that bypass database operations and call CLI functions directly with Result Objects:

#### Available Direct API Endpoints

All endpoints use Result Objects architecture for consistent CLI/API alignment:

```
POST /api/direct/portfolio           # Portfolio risk analysis → RiskAnalysisResult
POST /api/direct/stock              # Individual stock analysis → StockAnalysisResult
POST /api/direct/what-if            # Scenario analysis → WhatIfResult
POST /api/direct/optimize/min-variance   # Minimum variance optimization → OptimizationResult
POST /api/direct/optimize/max-return     # Maximum return optimization → OptimizationResult
POST /api/direct/performance        # Performance analysis → PerformanceResult
POST /api/direct/interpret          # AI interpretation → InterpretationResult
```

### User Request Flow with Result Objects
```
1. User Input
   ├── CLI: "python run_risk.py --portfolio portfolio.yaml"
   ├── Direct API: "POST /api/direct/portfolio"
   └── AI: "Analyze my portfolio risk"
   
2. Routes Layer (Returns Result Objects)
   ├── run_portfolio() → RiskAnalysisResult in run_risk.py
   ├── api endpoints in routes/ → calls service layer and returns Result Objects
   └── claude_chat() → calls service layer in routes/claude.py
   
3. Core Layer (Business Logic - Creates Result Objects)
   ├── analyze_portfolio() → RiskAnalysisResult in core/portfolio_analysis.py
   ├── analyze_scenario() → WhatIfResult in core/scenario_analysis.py
   ├── analyze_stock() → StockAnalysisResult in core/stock_analysis.py
   ├── analyze_performance() → PerformanceResult in core/performance_analysis.py
   ├── optimize_min_variance() / optimize_max_return() → OptimizationResult in core/optimization.py
   └── analyze_and_interpret() → InterpretationResult in core/interpretation.py
   
4. Data Layer (Supporting Functions)
   ├── build_portfolio_view() in portfolio_risk.py
   ├── run_what_if_scenario() in portfolio_optimizer.py
   └── get_stock_risk_profile() in risk_summary.py
   
5. Response (Result Object Methods)
   ├── CLI: result.to_cli_report() → Formatted console output
   ├── API: result.to_api_response() → JSON structured data
   └── AI: result.to_cli_report() → Natural language interpretation
```

### Direct API Pattern

Direct API endpoints follow a consistent pattern:

```python
@app.post("/api/direct/portfolio")
async def api_direct_portfolio(request: Request):
    """Direct portfolio analysis bypassing database operations."""

    # Extract portfolio data from request
    body = await request.json()
    portfolio_data = body.get("portfolio", {})

    # Create temporary YAML files
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(portfolio_data, f)
        temp_portfolio_path = f.name

    try:
        # Call CLI function with return_data=True to get Result Object
        result = run_portfolio(temp_portfolio_path, return_data=True)

        # Return Result Object's API response (unified CLI/API data)
        return {
            "success": True,
            "data": result.to_api_response(),
            "formatted_report": result.to_cli_report()  # Same text as CLI
        }
    finally:
        # Clean up temporary files
        os.unlink(temp_portfolio_path)
```

## 🎨 Frontend Architecture Patterns

### Container-View Pattern

The frontend implements a consistent **Container-View Pattern** across all dashboard features for clean separation of concerns and maintainability.

#### Established Pattern Architecture

**Container Responsibilities:**
- **Hook Integration**: Calls feature-specific hooks (e.g., `useRiskScore()`, `useWhatIfAnalysis()`, `usePerformance()`)
- **State Management**: Handles loading, error, hasData, hasPortfolio states
- **Early Returns**: Loading/Error/NoPortfolio states handled in container
- **Data Passing**: Passes transformed data to view
- **Action Handlers**: Wraps hook actions with logging
- **No UI Logic**: Pure state management and data flow

**View Responsibilities:**
- **Pure Presentation**: Only handles UI rendering
- **No State Management**: No hooks or complex state
- **Data Display**: Renders data passed from container
- **No Data Fallback**: Shows placeholder when no data
- **DOM Props Filtering**: Filters non-DOM props properly

#### Implementation Examples

**Risk Score Feature:**
```typescript
// RiskScoreViewContainer.tsx - Container Layer
const RiskScoreViewContainer: React.FC = () => {
  const { data, loading, error, hasData, hasPortfolio, refreshRiskScore, clearError } = useRiskScore();
  
  // Early returns for loading/error states
  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorMessage error={error} onRetry={refreshRiskScore} />;
  if (!hasPortfolio) return <NoPortfolioMessage />;
  
  // Pass all data and handlers to view
  return (
    <RiskScoreView
      riskScoreData={data}
      hasData={hasData}
      onRefresh={refreshRiskScore}
      onClearError={clearError}
    />
  );
};

// RiskScoreView.tsx - View Layer
const RiskScoreView: React.FC<RiskScoreViewProps> = (props) => {
  const { riskScoreData, hasData, onRefresh, onClearError, ...domProps } = props;
  
  return (
    <div {...domProps}>
      {hasData ? (
        <RiskScoreDisplay score={riskScoreData.risk_score} />
      ) : (
        <NoDataPlaceholder />
      )}
    </div>
  );
};
```

**What-If Analysis Feature:**
```typescript
// WhatIfAnalysisViewContainer.tsx - Container Layer
const WhatIfAnalysisViewContainer: React.FC = () => {
  const {
    data, loading, error, hasData, hasPortfolio,
    // Input management state and functions from hook
    inputMode, weightInputs, deltaInputs,
    addAssetInput, removeAssetInput, updateAssetName, updateAssetValue,
    runScenarioFromInputs, refreshWhatIfAnalysis, clearError
  } = useWhatIfAnalysis();
  
  // Early returns
  if (loading) return <LoadingSpinner />;
  if (error) return <ErrorMessage error={error} onRetry={refreshWhatIfAnalysis} />;
  
  // Action handlers with logging
  const handleRunScenario = useCallback(() => {
    frontendLogger.user.logUserAction('WhatIfAnalysisViewContainer', 'runWhatIfScenario');
    runScenarioFromInputs();
  }, [runScenarioFromInputs]);
  
  return (
    <WhatIfAnalysisView
      whatIfData={data}
      hasData={hasData}
      hasPortfolio={hasPortfolio}
      // Input management props
      inputMode={inputMode}
      weightInputs={weightInputs}
      deltaInputs={deltaInputs}
      addAssetInput={addAssetInput}
      removeAssetInput={removeAssetInput}
      updateAssetName={updateAssetName}
      updateAssetValue={updateAssetValue}
      onRunScenario={handleRunScenario}
      onRefresh={refreshWhatIfAnalysis}
      onClearError={clearError}
    />
  );
};
```

### Frontend Data Flow Architecture

**Frontend Data Flow:**
```
1. User Interaction
   ├── View Component (UI Event)
   └── Container Component (Event Handler)

2. Container Layer
   ├── Calls Hook Function
   ├── Logs User Action
   └── Updates Loading State

3. Hook Layer (Business Logic)
   ├── Validates Input
   ├── Calls Service/Manager
   ├── Handles TanStack Query
   └── Returns Transformed Data

4. Service Layer
   ├── APIService (HTTP Requests)
   ├── PortfolioCacheService (Caching)
   └── Adapter (Data Transformation)

5. Backend API
   ├── FastAPI Route Handler
   ├── Service Layer
   ├── Core Business Logic
   └── Result Object Response

6. Response Flow
   ├── Adapter Transforms Data
   ├── Hook Updates State
   ├── Container Receives Data
   └── View Renders UI
```

### Hook Architecture Patterns

**Feature-Organized Hooks:**
```
features/
├── riskScore/hooks/useRiskScore.ts
├── analysis/hooks/useRiskAnalysis.ts
├── analysis/hooks/usePerformance.ts
├── whatIf/hooks/useWhatIfAnalysis.ts
├── optimize/hooks/usePortfolioOptimization.ts
└── portfolio/hooks/usePortfolioSummary.ts
```

**Hook Responsibilities:**
- **Data Fetching**: TanStack Query integration
- **State Management**: Local hook state for UI interactions
- **Business Logic**: Input validation, scenario creation
- **Error Handling**: Comprehensive error states
- **Caching**: Scenario-specific cache keys
- **Logging**: Detailed operation logging

**Hook Return Interface Pattern:**
```typescript
// Standard hook return interface
interface HookReturn {
  // Data
  data: TransformedData | null;
  
  // States
  loading: boolean;
  error: Error | null;
  hasData: boolean;
  hasPortfolio: boolean;
  
  // Actions
  refresh: () => void;
  clearError: () => void;
  
  // Feature-specific actions and state
  [featureSpecificProps]: any;
}
```

### Adapter Pattern Implementation

**Direct Pass-Through Approach:**
```typescript
// WhatIfAnalysisAdapter.ts - Direct API Response Pass-Through
export class WhatIfAnalysisAdapter {
  static transform(apiResponse: any): WhatIfAnalysisData {
    // Direct pass-through of backend API response
    return {
      scenario_results: apiResponse.scenario_results,
      summary: apiResponse.summary,
      portfolio_metadata: apiResponse.portfolio_metadata,
      risk_limits_metadata: apiResponse.risk_limits_metadata
    };
  }
}
```

**Transformation Approach:**
```typescript
// PerformanceAdapter.ts - Data Transformation
export class PerformanceAdapter {
  static transform(apiResponse: any): PerformanceData {
    return {
      period: this.transformPeriod(apiResponse.performance_metrics.analysis_period),
      returns: this.transformReturns(apiResponse.performance_metrics.returns),
      benchmark: this.transformBenchmark(apiResponse.performance_metrics),
      // ... other transformations
    };
  }
}
```

### Caching Strategy

**Scenario-Specific Cache Keys:**
```typescript
// PortfolioCacheService.ts
private generateScenarioHash(scenarioParams: any): string {
  const scenario = scenarioParams?.scenario || scenarioParams?.apiScenario || scenarioParams;
  const scenarioString = JSON.stringify(scenario, Object.keys(scenario).sort());
  // Generate hash for unique cache key
  return Math.abs(hash).toString(36).substring(0, 8);
}

async getWhatIfAnalysis(portfolioId: string, scenarioParams: any): Promise<any> {
  const scenarioHash = this.generateScenarioHash(scenarioParams);
  const operation = `whatIfAnalysis_${scenarioHash}`;
  
  return this.getOrFetch(portfolioId, operation, async () => {
    return this.apiService.getWhatIfAnalysis(portfolioId, scenarioParams);
  });
}
```

---

## 📂 File Structure

### Complete Architecture Directory Structure

```
risk_module/
├── 📄 readme.md                       # Main project documentation
├── 📄 architecture.md                 # Technical architecture (this file)
├── 📄 CHANGELOG.md                    # Release changelog
├── ⚙️ settings.py                     # Default configuration settings
├── 🔧 app.py                          # FastAPI application entry point
├── 🔧 ai_function_registry.py         # Claude AI function registry (16 functions)
├── 🔧 database/                       # Database infrastructure module
│   ├── __init__.py                     # Module exports and backward compatibility
│   ├── session.py                      # Request-scoped database session management
│   ├── pool.py                         # Database connection pooling
│   ├── schema.sql                      # Database schema definitions
│   ├── run_migration.py                # Migration runner
│   └── migrations/                     # SQL schema migrations
├── 🔧 check_user_data.py              # Database inspection utility
├── 🔒 update_secrets.sh               # Secrets synchronization script
├── 📋 requirements.txt                # Python dependencies
├── 📜 LICENSE                         # MIT License
│
├── 📊 MCP SERVER LAYER (Claude Code Integration)
│   ├── 🤖 mcp_server.py                    # portfolio-mcp FastMCP server (16 tools)
│   ├── 🤖 fmp_mcp_server.py                # fmp-mcp FastMCP server (14 tools)
│   ├── 📁 mcp_tools/                       # MCP tool implementations
│   │   ├── __init__.py                      # Module exports
│   │   ├── positions.py                     # get_positions tool wrapping PositionService
│   │   ├── risk.py                          # get_risk_score, get_risk_analysis tools
│   │   ├── performance.py                   # get_performance tool (hypothetical + realized)
│   │   ├── stock.py                         # analyze_stock tool
│   │   ├── optimization.py                  # run_optimization tool
│   │   ├── whatif.py                        # run_whatif tool
│   │   ├── factor_intelligence.py           # get_factor_analysis, get_factor_recommendations
│   │   ├── income.py                        # get_income_projection tool
│   │   ├── tax_harvest.py                   # suggest_tax_loss_harvest tool
│   │   ├── trading.py                       # preview_trade, execute_trade, get_orders, cancel_order
│   │   ├── signals.py                       # check_exit_signals tool
│   │   ├── fmp.py                           # fmp_fetch, fmp_search, fmp_profile, fmp_list_endpoints, fmp_describe
│   │   ├── screening.py                     # screen_stocks tool
│   │   ├── peers.py                         # compare_peers tool
│   │   ├── market.py                        # get_economic_data, get_sector_overview, get_market_context
│   │   ├── news_events.py                   # get_news, get_events_calendar
│   │   ├── technical.py                     # get_technical_analysis tool
│   │   ├── transcripts.py                   # get_earnings_transcript tool
│   │   └── README.md                        # Tool development guide
│
├── 📊 LAYER 1: ROUTES LAYER (User Interface)
│   ├── 🖥️ run_risk.py                     # CLI interface with Result Objects support
│   ├── 🖥️ run_portfolio_risk.py           # Portfolio risk analysis CLI
│   ├── 🖥️ run_positions.py                # Positions CLI for brokerage data
│   ├── 🖥️ run_trading_analysis.py         # Trading analysis CLI (Plaid/SnapTrade/IBKR Flex)
│   ├── 🖥️ run_factor_intelligence.py      # Factor intelligence CLI
│   ├── 📁 routes/                         # Modular API route structure
│   │   ├── auth.py                        # Authentication routes with OAuth
│   │   ├── claude.py                      # Claude AI chat integration
│   │   ├── plaid.py                       # Plaid brokerage integration
│   │   ├── snaptrade.py                   # SnapTrade brokerage integration
│   │   ├── positions.py                   # Position management routes
│   │   ├── provider_routing_api.py        # Provider routing and institution support
│   │   ├── provider_routing.py            # Provider routing logic
│   │   ├── admin.py                       # Admin dashboard routes
│   │   ├── frontend_logging.py            # Frontend logging routes
│   │   └── factor_intelligence.py         # Factor correlation and beta sensitivity routes
│   ├── 📁 services/                       # Service orchestration
│   │   ├── portfolio_service.py           # Portfolio analysis service with caching
│   │   ├── stock_service.py               # Stock analysis service
│   │   ├── scenario_service.py            # Scenario analysis service
│   │   ├── optimization_service.py        # Optimization service
│   │   ├── auth_service.py                # Authentication service with session management
│   │   ├── security_type_service.py       # Security type classification with FMP integration
│   │   ├── factor_proxy_service.py        # Factor proxy management
│   │   ├── returns_service.py             # Expected returns service
│   │   ├── async_service.py               # Non-blocking portfolio operations
│   │   ├── validation_service.py          # Data validation service
│   │   ├── cache_mixin.py                 # ServiceCacheMixin for intelligent caching
│   │   ├── service_manager.py             # Central service orchestration and dependency injection
│   │   ├── position_service.py            # Position orchestration across providers (Plaid, SnapTrade)
│   │   ├── factor_intelligence_service.py # Factor correlation and beta sensitivity service
│   │   ├── trade_execution_service.py     # Trade preview/execution service (SnapTrade)
│   │   ├── ibkr_flex_client.py            # IBKR Flex Query download + normalization
│   │   ├── ibkr_historical_data.py       # IBKR Gateway historical price fallback for futures
│   │   ├── ibkr_broker_adapter.py         # IBKR broker adapter (ib_async)
│   │   ├── ibkr_connection_manager.py     # IBKR gateway connection management
│   │   ├── snaptrade_broker_adapter.py    # SnapTrade broker adapter for trading
│   │   ├── claude/                        # Claude AI services
│   │   │   ├── function_executor.py       # Claude function execution
│   │   │   └── chat_service.py            # Claude chat interface
│   │   └── portfolio/                     # Portfolio-specific services
│   │       └── context_service.py         # Portfolio context management
│   └── 📁 frontend/                       # Production-Ready React Frontend
│       ├── src/ARCHITECTURE.md            # Frontend architecture documentation
│       ├── src/components/                # UI components and views
│       ├── src/chassis/                   # Service layer architecture
│       ├── src/hooks/                     # Data access React hooks
│       ├── src/stores/                    # Zustand state management
│       ├── src/providers/                 # React context providers
│       └── src/utils/                     # Utilities and adapters
│
├── 📊 LAYER 2: CORE LAYER (Pure Business Logic)
│   ├── 📁 core/                           # Result Objects architecture (18 modules)
│   │   ├── portfolio_analysis.py          # Portfolio analysis with RiskAnalysisResult
│   │   ├── stock_analysis.py              # Stock analysis with StockAnalysisResult
│   │   ├── scenario_analysis.py           # Scenario analysis with WhatIfResult
│   │   ├── optimization.py                # Optimization with OptimizationResult
│   │   ├── performance_analysis.py        # Performance with PerformanceResult
│   │   ├── performance_metrics_engine.py  # Pure math engine for performance metrics
│   │   ├── realized_performance_analysis.py # Transaction-based realized performance
│   │   ├── interpretation.py              # AI interpretation with InterpretationResult
│   │   ├── result_objects.py              # Unified Result Objects with dual serialization (13 result classes)
│   │   ├── data_objects.py                # Input data structures and validation (PortfolioData, currency_map)
│   │   ├── trade_objects.py               # Trading data models and schemas
│   │   ├── broker_adapter.py              # Abstract broker adapter interface
│   │   ├── constants.py                   # Centralized asset class constants and business logic
│   │   ├── exceptions.py                  # Core exception handling
│   │   ├── exit_signals.py                # Exit signal engine (momentum, regime rules)
│   │   ├── income_projection.py           # Pure dividend projection engine
│   │   ├── factor_intelligence.py         # Factor correlation and beta sensitivity analysis
│   │   └── asset_class_performance.py     # Asset class performance calculations
│   └── 📁 utils/                          # Utility functions
│       ├── serialization.py               # JSON serialization utilities
│       ├── security_type_mappings.py      # Centralized security type mapping with 3-tier fallback
│       ├── sector_config.py               # Sector preference and label mapping utilities
│       ├── ticker_validation.py           # Ticker validation and data quality utilities
│       ├── ticker_resolver.py             # International ticker resolution for FMP
│       ├── logging.py                     # Multi-level logging infrastructure
│       ├── json_logging.py                # JSON-structured logging utilities
│       ├── config.py                      # Configuration utilities
│       ├── errors.py                      # Error handling utilities
│       ├── etf_mappings.py                # ETF mapping utilities
│       ├── auth.py                        # Authentication utilities
│       ├── date_utils.py                  # Date parsing and normalization helpers
│       ├── pydantic_helpers.py            # Pydantic model utilities
│       └── pydantic_codegen.py            # Pydantic code generation tools
│
├── 📊 LAYER 3: DATA LAYER (Data Access & Storage)
│   ├── 💼 portfolio_risk.py               # Legacy portfolio risk calculations
│   ├── 📈 portfolio_risk_score.py         # Legacy risk scoring system
│   ├── 📊 factor_utils.py                 # Factor analysis utilities
│   ├── 📋 risk_summary.py                 # Legacy single-stock risk profiling
│   ├── ⚡ portfolio_optimizer.py           # Legacy portfolio optimization
│   ├── 🔌 data_loader.py                  # Data fetching and caching (uses fmp/compat.py)
│   ├── 📁 fmp/                            # FMP Data Abstraction Layer
│   │   ├── __init__.py                     # Module exports and quick-start docs
│   │   ├── client.py                       # FMPClient: unified fetch with caching
│   │   ├── registry.py                     # Endpoint registry with metadata (30+ endpoints)
│   │   ├── cache.py                        # Disk caching (Parquet + Zstandard)
│   │   ├── compat.py                       # Backward-compatible wrappers
│   │   ├── fx.py                           # FX conversion utilities
│   │   └── exceptions.py                   # Structured exception hierarchy
│   ├── 📁 inputs/                         # Input management layer
│   │   ├── portfolio_manager.py           # Portfolio configuration management
│   │   ├── risk_limits_manager.py         # Risk limits management with dual storage
│   │   ├── database_client.py             # Per-request PostgreSQL client
│   │   ├── returns_calculator.py          # Expected returns estimation
│   │   ├── file_manager.py                # File operations and persistence
│   │   └── exceptions.py                  # Input-specific error handling
│   ├── 🤖 gpt_helpers.py                  # GPT integration utilities
│   ├── 🔧 proxy_builder.py                # Factor proxy generation
│   ├── 🏦 plaid_loader.py                 # Plaid brokerage integration
│   ├── 💼 snaptrade_loader.py             # SnapTrade brokerage integration
│   └── 🛠️ risk_helpers.py                 # Risk calculation helpers
│
├── 📁 Database & Infrastructure
│   ├── 🗃️ database/                       # Centralized database infrastructure
│   │   ├── __init__.py                     # Database module exports
│   │   ├── session.py                      # Request-scoped session management
│   │   ├── pool.py                         # Connection pooling
│   │   ├── schema.sql                      # Database schema definitions
│   │   ├── run_migration.py                # Migration runner
│   │   └── migrations/                     # SQL schema migrations
│   │       ├── 20250801_add_subindustry_peers.sql
│   │       ├── 20250831_cleanup_subindustry_peers.sql
│   │       ├── 20250901_add_asset_etf_proxies.sql
│   │       ├── 20250902_alter_industry_proxies_add_sector_group.sql
│   │       ├── 20250903_add_factor_intelligence.sql
│   │       ├── 2025-09-asset-class.sql
│   │       ├── 20260130_add_positions_metadata.sql
│   │       ├── 20260130_update_positions_unique_constraint.sql
│   │       ├── 20260201_add_fmp_ticker.sql     # International ticker resolution
│   │       ├── 20260209_add_trade_tables.sql   # Trade execution tables
│   │       └── 20260210_add_broker_provider.sql # Broker provider metadata
│   ├── 📄 templates/dashboard.html        # Web application templates
│   └── 🛠️ admin/                          # Reference data management and monitoring
│       ├── manage_reference_data.py       # CLI tool for managing mappings
│       ├── README.md                      # Reference data management guide
│       └── error_logs/                    # Production monitoring and alerts
│
├── 📁 Configuration Files
│   ├── ⚙️ portfolio.yaml                 # Portfolio configuration
│   ├── ⚙️ risk_limits.yaml               # Risk limit definitions
│   ├── 🗺️ cash_map.yaml                  # Cash position mapping (YAML fallback)
│   ├── 🏭 industry_to_etf.yaml           # Industry classification mapping (YAML fallback)
│   ├── 📊 exchange_etf_proxies.yaml      # Exchange-specific proxies (YAML fallback)
│   ├── 📊 asset_etf_proxies.yaml         # Asset class ETF proxies (bond, commodity, crypto)
│   ├── 🌍 exchange_mappings.yaml         # MIC→FMP suffix, IBKR futures→FMP symbols, IBKR exchange routing
│   ├── 🔒 security_type_mappings.yaml    # Security type to crash scenario mappings
│   ├── 🔧 what_if_portfolio.yaml         # What-if scenarios
│   ├── ⚙️ .env                           # Environment variables (IBKR_FLEX_TOKEN, TRADING_ENABLED, etc.)
│   ├── ⚙️ playwright.config.js           # E2E testing configuration
│   ├── ⚙️ jest.config.js                 # Frontend testing configuration
│   └── 🔧 package.json                   # Frontend dependencies and scripts
│
├── 📁 bugs/ (Bug Tracking)
│   ├── completed/                               # Resolved bug reports
│   └── *.md                                     # Active bug investigations
│
├── 📁 docs/ (Documentation)
│   ├── API_REFERENCE.md                        # REST API documentation
│   ├── DATABASE_REFERENCE.md                   # Database schema documentation
│   ├── DATA_SCHEMAS.md                         # Data schema definitions
│   ├── DEVELOPER_ONBOARDING.md                 # Developer onboarding guide
│   ├── ENVIRONMENT_SETUP.md                    # Environment setup instructions
│   ├── guides/                                 # Operational guides
│   ├── ideas/                                  # Architecture ideas and concepts
│   ├── planning/                               # Development planning documents
│   │   └── completed/                          # Completed implementation plans
│   ├── specs/                                  # Feature specifications
│   └── schemas/                                # API and CLI output samples
│
├── 📁 tests/ (Comprehensive Testing Suite)
│   ├── conftest.py                        # Pytest configuration and fixtures
│   ├── ai_test_orchestrator.py            # AI-powered test orchestration
│   ├── unit/                              # Unit tests (position chain, positions data, results)
│   ├── api/                               # API tests (auth, logging, portfolio CRUD, services)
│   ├── core/                              # Core module tests (asset class perf, exit signals, realized perf, performance metrics)
│   ├── integration/                       # E2E integration tests (dashboard, auth, Claude AI)
│   ├── snaptrade/                         # SnapTrade integration tests (7 test files)
│   ├── factor_intelligence/               # Factor intelligence tests (API, core, offsets, service)
│   ├── services/                          # Service layer tests (IBKR flex client, IBKR historical data, portfolio service, proxies)
│   ├── mcp_tools/                         # MCP tool tests (income, market, news, peers, performance, screening, technical)
│   ├── trading_analysis/                  # Trading analysis tests (provider routing)
│   ├── performance/                       # Performance benchmark tests
│   ├── e2e/                               # End-to-end testing with Playwright
│   └── utils/                             # Test utilities and helpers
│
├── 📁 trading_analysis/ (Trading Decision Analysis)
│   ├── __init__.py                        # Package exports
│   ├── analyzer.py                        # Main TradingAnalyzer class (Plaid + SnapTrade + IBKR Flex)
│   ├── models.py                          # Data models and schemas
│   ├── metrics.py                         # Core metric calculations (Win Score, P&L)
│   ├── fifo_matcher.py                    # FIFO lot matching for cost basis (SHORT inference, option expiration)
│   ├── data_fetcher.py                    # fetch_all_transactions(), fetch_transactions_for_source(), should_skip_plaid_institution()
│   ├── symbol_utils.py                    # normalize_strike() for cross-source consistency
│   ├── main.py                            # CLI runner script
│   ├── interpretation_guide.md            # LLM interpretation guidelines
│   └── analyzers/                         # Analysis modules (trades, income, behavioral, timing)
│
├── 📁 scripts/ (Operational Scripts)
│   ├── update_secrets.sh                  # Secrets synchronization script
│   ├── backup_system.sh                   # System backup utilities
│   ├── run-e2e-tests.sh                   # E2E test runner
│   ├── backfill_fmp_tickers.py            # Backfill positions.fmp_ticker column
│   ├── fetch_ibkr_trades.py              # Fetch IBKR Flex Query trades
│   └── explore_transactions.py            # Transaction data exploration utility
│
└── 📁 tools/ (Development Tools)
    ├── view_alignment.py                  # Terminal alignment viewer
    ├── check_dependencies.py              # Dependency impact analysis
    ├── test_all_interfaces.py             # Interface testing suite
    ├── living_code_map.py                 # Dynamic codebase visualization
    ├── code_tracer.py                     # Code tracing and flow analysis
    ├── fullstack_code_tracer.py           # Full-stack dependency tracing
    └── backfill_subindustry_peers.py      # Backfill subindustry peer data
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

### After: Result Objects Architecture
```python
# run_risk.py (Routes Layer)
def run_portfolio(filepath, *, return_data=False) -> Union[None, RiskAnalysisResult]:
    # Call core business logic that returns Result Object
    result = analyze_portfolio(filepath)  # Returns RiskAnalysisResult
    
    # Dual-mode response handling using Result Object methods
    if return_data:
        return result  # API mode - return Result Object
    else:
        print(result.to_cli_report())  # CLI mode - use Result Object formatter
        return None

# core/portfolio_analysis.py (Core Layer)
def analyze_portfolio(filepath) -> RiskAnalysisResult:
    # Pure business logic - no UI concerns
    # 1. Load configuration
    # 2. Build portfolio view using data layer
    portfolio_data = build_portfolio_view(filepath)
    # 3. Calculate risk metrics
    # 4. Check limits
    # 5. Return Result Object with all data and formatting methods
    return RiskAnalysisResult.from_portfolio_analysis(
        portfolio_data, risk_metrics, limit_checks
    )
```

## 🔄 Technical Implementation Details

### Dual-Mode Pattern Implementation

Every function maintains dual-mode behavior:

```python
def run_portfolio(filepath: str, risk_yaml: str = "risk_limits.yaml", *, return_data: bool = False) -> Union[None, RiskAnalysisResult]:
    """
    Dual-mode portfolio analysis function using Result Objects architecture.
    
    Parameters
    ----------
    filepath : str
        Path to portfolio YAML file
    risk_yaml : str, default "risk_limits.yaml"
        Path to risk limits YAML file
    return_data : bool, default False
        If True, returns RiskAnalysisResult object
        If False, prints formatted output to stdout
    
    Returns
    -------
    None or RiskAnalysisResult
        If return_data=False: Returns None, prints formatted CLI output
        If return_data=True: Returns RiskAnalysisResult object with to_api_response() method
    """
    # Business logic: Call core function that returns Result Object
    result = analyze_portfolio(filepath, risk_yaml)
    
    # Dual-mode logic using Result Object methods
    if return_data:
        # API Mode: Return Result Object
        return result
    else:
        # CLI Mode: Use Result Object's CLI formatter
        print(result.to_cli_report())
        return None
```

### Data Handling Strategy

- **Structured Data**: JSON-safe for API consumption
- **Raw Objects**: Preserved for CLI compatibility
- **Formatted Reports**: Generated for user-friendly output

### Business Logic Extraction

All core business logic has been extracted to dedicated modules:

| CLI Function | Core Function | Result Object | Purpose |
|---------------|---------------|---------------|---------|
| `run_portfolio()` | `analyze_portfolio()` | `RiskAnalysisResult` | Portfolio risk analysis |
| `run_what_if()` | `analyze_scenario()` | `WhatIfResult` | What-if scenario analysis |
| `run_min_variance()` | `optimize_min_variance()` | `OptimizationResult` | Minimum variance optimization |
| `run_max_return()` | `optimize_max_return()` | `OptimizationResult` | Maximum return optimization |
| `run_stock()` | `analyze_stock()` | `StockAnalysisResult` | Individual stock analysis |
| `run_portfolio_performance()` | `analyze_performance()` | `PerformanceResult` | Performance metrics |
| `run_and_interpret()` | `analyze_and_interpret()` | `InterpretationResult` | AI interpretation services |
| `run_risk_score()` | `analyze_risk_score()` | `RiskScoreResult` | Risk scoring analysis |

## 🔧 Component Details

### 1. Data Layer (`data_loader.py`)

**Purpose**: Efficient data retrieval with intelligent caching

**Architecture**: Uses `fmp/compat.py` for backward-compatible FMP API access with the new FMP Data Abstraction Layer. The compat layer provides international ticker resolution via `fmp_ticker` and `fmp_ticker_map` parameters.

**Key Functions**:
- `fetch_monthly_close()`: FMP API integration with caching and international ticker support
- `fetch_monthly_total_return_price()`: Dividend-adjusted prices with ticker resolution
- `fetch_monthly_treasury_rates()`: Treasury rate data
- `fetch_dividend_history()`: Dividend events with frequency-based TTM calculation

**Features**:
- Automatic cache invalidation
- Compressed parquet storage (via `fmp/cache.py`)
- MD5-based cache keys
- Error handling and retry logic
- Treasury rate integration for risk-free rates
- International ticker resolution via `utils/ticker_resolver.py`

**Caching Strategy**:
```
RAM Cache (LRU) → Disk Cache (Parquet via fmp/cache.py) → Network (FMP API via fmp/client.py)
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

#### Claude Service Integration (`chassis/services/ClaudeService.ts`)
**TypeScript-based AI function integration with modern React architecture**

**Portfolio Analysis Functions (4)**:
- `create_portfolio_scenario()`: Create new portfolio configurations
- `run_portfolio_analysis()`: Complete portfolio risk analysis with database-first architecture
- `setup_new_portfolio()`: Generate factor proxies for user's portfolio
- `calculate_portfolio_performance()`: Performance metrics and benchmarking

**Risk Analysis Functions (1)**:
- `get_risk_score()`: Portfolio risk scoring with detailed breakdown

**Optimization Functions (2)**:
- `optimize_minimum_variance()`: Minimum variance optimization
- `optimize_maximum_return()`: Maximum return optimization with automatic expected returns generation

**Scenario Analysis Functions (1)**:
- `run_what_if_scenario()`: Portfolio modification testing

**Stock Analysis Functions (1)**:
- `analyze_stock()`: Single stock analysis with factor decomposition

**Returns Management Functions (2)**:
- `estimate_expected_returns()`: Generate expected returns using industry ETF methodology (10-year lookback default)
- `set_expected_returns()`: Set returns for user's portfolio

**Risk Management Functions (3)**:
- `view_current_risk_limits()`: Show risk limits for user
- `update_risk_limits()`: Update user's risk limit settings
- `reset_risk_limits()`: Reset risk limits to default values
- `save_portfolio_yaml()`: Portfolio configuration persistence
- `load_portfolio_yaml()`: Portfolio configuration loading
- `update_portfolio_weights()`: Weight modification
- `validate_portfolio_config()`: Configuration validation

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
**Portfolio caching and context management with user isolation**

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

#### Returns Service (`services/returns_service.py`)
**Enterprise-level expected returns management with validation and auto-generation**

**Key Functions**:
- `validate_returns_coverage()`: Validate expected returns coverage for portfolio tickers
- `generate_missing_returns()`: Auto-generate missing returns using industry ETF methodology
- `get_expected_returns()`: Retrieve expected returns with fallback logic
- `save_expected_returns()`: Persist expected returns to database or files
- `estimate_returns_for_portfolio()`: Portfolio-level returns estimation with coverage validation

**Features**:
- **Coverage validation** for portfolio tickers with structured warnings
- **Auto-generation** using industry ETF historical performance (10-year lookback default)
- **Intelligent cash proxy handling** using Treasury rates for cash equivalents
- **Database and file-based** returns storage patterns
- **Integration** with optimization workflows to prevent 0% return defaults
- **Structured reporting** for missing data and coverage gaps

**Architecture Position**: Service Layer → ReturnsCalculator → Data Sources (Files/Database)

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

#### Risk Limits Manager (`inputs/risk_limits_manager.py`)
**Type-safe risk limits management with dual-mode storage**

**Key Functions**:
- `load_risk_limits()`: Load risk limits as RiskLimitsData objects
- `save_risk_limits()`: Save validated RiskLimitsData objects
- `view_current_risk_limits()`: Display current risk tolerance settings
- `update_risk_limits()`: Modify risk tolerance parameters with change tracking
- `reset_risk_limits()`: Reset to system default values
- `create_risk_limits_yaml()`: Create scenario-specific risk limit files

**Features**:
- **Type Safety**: All operations use RiskLimitsData objects from core/data_objects.py
- **Dual-Mode Storage**: PostgreSQL database + YAML file fallback
- **User Isolation**: Multi-tenant support with user-specific risk limits
- **Automatic Fallback**: Database → file → defaults fallback chain
- **Change Tracking**: Audit trails for all risk limit modifications
- **Validation**: Built-in validation through RiskLimitsData objects

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

**Single Stock Runner** (`run_risk.py --stock`):
- Individual stock diagnostics via `run_stock()` function
- Factor model validation
- Detailed regression analysis

**Risk Runner** (`run_risk.py`):
- Flexible risk analysis entry point
- What-if scenario testing
- Batch processing capabilities

**Trading Analysis Runner** (`run_trading_analysis.py`):
- Transaction-based trading analysis (Plaid, SnapTrade, IBKR Flex)
- FIFO lot matching and P&L computation
- Win rate, behavioral, and timing analysis

**Factor Intelligence Runner** (`run_factor_intelligence.py`):
- Factor correlation matrices and sensitivity overlays
- Factor performance profiling
- Beta sensitivity analysis

## ⚙️ Configuration Management

### Default Settings (`settings.py`)

**Purpose**: Centralized default configuration management

**Structure**:
```python
PORTFOLIO_DEFAULTS = {
    "start_date": "2019-01-31",
    "end_date": "2026-01-29",
    "normalize_weights": False,  # Global default for portfolio weight normalization
    "worst_case_lookback_years": 10,  # Historical lookback period for worst-case scenario analysis
    "expected_returns_lookback_years": 10,  # Default years for expected returns estimation
    "expected_returns_fallback_default": 0.06,  # Default fallback return (6%)
    "cash_proxy_fallback_return": 0.02  # Conservative fallback return (2%) for cash proxies
}
```

**Trading Configuration** (`settings.py`):
```python
TRADING_ENABLED = os.getenv("TRADING_ENABLED", "false").lower() == "true"

TRADING_DEFAULTS = {
    "max_order_value": float(os.getenv("MAX_ORDER_VALUE", "100000")),
    "max_single_stock_weight_post_trade": 0.25,
    "preview_expiry_seconds": 300,  # 5 min
    "default_time_in_force": "Day",
    "default_order_type": "Market",
    "log_all_previews": True,
    "log_all_executions": True,
}

# IBKR Configuration
IBKR_ENABLED = os.getenv("IBKR_ENABLED", "false").lower() == "true"
IBKR_GATEWAY_HOST = os.getenv("IBKR_GATEWAY_HOST", "127.0.0.1")
IBKR_GATEWAY_PORT = int(os.getenv("IBKR_GATEWAY_PORT", "4001"))  # 4001=live, 4002=paper
IBKR_CLIENT_ID = int(os.getenv("IBKR_CLIENT_ID", "1"))
IBKR_TIMEOUT = int(os.getenv("IBKR_TIMEOUT", "10"))
IBKR_READONLY = os.getenv("IBKR_READONLY", "false").lower() == "true"
IBKR_FLEX_TOKEN = os.getenv("IBKR_FLEX_TOKEN", "")
IBKR_FLEX_QUERY_ID = os.getenv("IBKR_FLEX_QUERY_ID", "")
```

**Transaction Provider Routing** (`settings.py`):
```python
# Controls which provider supplies TRANSACTIONS for each institution.
# When an institution is listed here with a canonical transaction provider,
# Plaid transactions tagged with that institution's name are SKIPPED.
TRANSACTION_ROUTING = {
    "interactive_brokers": "ibkr_flex",
}

INSTITUTION_SLUG_ALIASES = {
    "interactive brokers": "interactive_brokers",
    "ibkr": "interactive_brokers",
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

### Enhanced ETF Proxy Configuration System

**Comprehensive Reference Data Architecture**:
The Risk Module implements a sophisticated 3-tier ETF proxy system that manages exchange factors, industry mappings, and asset class proxies through database-first architecture with YAML configuration backup.

**Architecture Pattern**:
1. **Database (Primary)**: PostgreSQL tables with live production data
2. **YAML (Source of Truth)**: Configuration files for management and development
3. **Hardcoded (Ultimate Fallback)**: Built-in mappings for system resilience

**Exchange ETF Proxies** (`exchange_etf_proxies.yaml`):
- **Purpose**: Maps stock exchanges to representative factor ETFs for risk modeling
- **Primary Usage**: Exchange-based factor proxy mappings for geographic diversification analysis
- **Integration**: Factor Intelligence correlation analysis and beta sensitivity calculations

**Exchange Mapping Structure**:
```yaml
# US Markets
NASDAQ:
  market: SPY        # S&P 500 market proxy
  momentum: MTUM     # Momentum factor ETF
  value: IWD         # Value factor ETF

NYSE:
  market: SPY        # S&P 500 market proxy
  momentum: MTUM     # Momentum factor ETF
  value: IWD         # Value factor ETF

# International Markets
TSX:                 # Toronto Stock Exchange
  market: ACWX       # All-Country World ex-US
  momentum: IMTM     # International momentum
  value: EFV         # International value

HKEX:                # Hong Kong Stock Exchange
  market: EEM        # Emerging markets
  momentum: EEMO     # Emerging markets momentum
  value: EMVL.L      # Emerging markets value (London-listed)

DEFAULT:             # Fallback for unmapped exchanges
  market: ACWX       # Global ex-US market
  momentum: IMTM     # International momentum
  value: EFV         # International value
```

**Industry ETF Proxies** (`industry_to_etf.yaml`):
- **Purpose**: Maps company industries to representative sector ETFs for risk modeling
- **Enhanced Features**: Includes asset class override and sector group support
- **Integration**: Tier 3 of the 5-tier asset class classification system

**Industry Mapping Structure**:
```yaml
# Core Sector ETFs (matches database bootstrap)
Technology:
  etf: XLK
  asset_class: equity
  sector_group: growth

Healthcare:
  etf: XLV
  asset_class: equity
  sector_group: defensive

Financial Services:
  etf: XLF
  asset_class: equity
  sector_group: cyclical

# Specialized Industries with Asset Class Overrides
Real Estate:
  etf: VNQ
  asset_class: real_estate
  sector_group: interest_sensitive

Gold Mining:
  etf: GLD
  asset_class: commodity
  sector_group: alternative

Municipal Utilities:
  etf: XLU
  asset_class: equity
  sector_group: defensive
```

**Asset Class ETF Proxies** (`asset_etf_proxies.yaml`):
- **Purpose**: ✨ **NEW** - Canonical asset class to ETF mappings for macro analysis
- **Enhanced Features**: Support for canonical vs alternate proxies with priority ordering
- **Integration**: Factor Intelligence macro composite analysis and asset class performance

**Asset Class Mapping Structure**:
```yaml
asset_classes:
  bond:
    canonical:
      UST2Y: SHY           # 1-3Y Treasuries
      UST5Y: IEI           # 3-7Y Treasuries
      UST10Y: IEF          # 7-10Y Treasuries
      UST30Y: TLT          # 20+Y Treasuries
      aggregate: AGG       # US Aggregate Bond
      investment_grade_corp: LQD  # Investment Grade Corporates
      high_yield: HYG      # High Yield Corporates

  commodity:
    canonical:
      broad: DBC           # Broad commodities
      gold: GLD            # Gold
      silver: SLV          # Silver
      oil: USO             # Oil

  crypto:
    canonical:
      BTC: IBIT            # Bitcoin spot ETF
      ETH: ETHA            # Ethereum spot ETF
```

**Database Integration Architecture**:

**Exchange Proxies Table**:
```sql
CREATE TABLE exchange_proxies (
    id SERIAL PRIMARY KEY,
    exchange VARCHAR(100) NOT NULL,
    factor_type VARCHAR(50) NOT NULL,  -- 'market', 'momentum', 'value'
    proxy_etf VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(exchange, factor_type),
    INDEX idx_exchange_proxies_exchange (exchange),
    INDEX idx_exchange_proxies_factor (factor_type)
);
```

**Enhanced Industry Proxies Table**:
```sql
CREATE TABLE industry_proxies (
    id SERIAL PRIMARY KEY,
    industry VARCHAR(255) NOT NULL UNIQUE,
    proxy_etf VARCHAR(20) NOT NULL,
    asset_class VARCHAR(50),           -- NEW: Asset class override
    sector_group VARCHAR(50),          -- NEW: Sector group classification
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    INDEX idx_industry_proxies_industry (industry),
    INDEX idx_industry_proxies_etf (proxy_etf),
    INDEX idx_industry_sector_group (sector_group)  -- NEW: Sector group index
);
```

**Asset ETF Proxies Table**:
```sql
CREATE TABLE asset_etf_proxies (
    id SERIAL PRIMARY KEY,
    asset_class VARCHAR(50) NOT NULL,
    proxy_key VARCHAR(100) NOT NULL,
    etf_ticker VARCHAR(20) NOT NULL,
    is_alternate BOOLEAN DEFAULT FALSE,
    priority INTEGER DEFAULT 100,
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),

    UNIQUE(asset_class, proxy_key, etf_ticker),
    INDEX idx_asset_proxies_class (asset_class),
    INDEX idx_asset_proxies_key (proxy_key)
);
```

**Integration with Factor Intelligence**:
- **Exchange Factors**: Enable geographic style factor analysis across global markets
- **Industry Grouping**: Support for both individual industry and sector group aggregation
- **Asset Class Macros**: Enable macro composite correlation matrices across asset classes
- **Sector Preferences**: Advanced sector ordering using core sector ETF preferences
- **Beta Sensitivity**: Enhanced rate and market sensitivity analysis with proper ETF mapping

**Administrative Integration**:
- **Bulk Sync**: YAML to database synchronization via `manage_reference_data.py`
- **Validation**: ETF proxy coverage validation via `verify_proxies.py`
- **Cache Management**: Automatic service cache clearing after updates
- **Health Monitoring**: Real-time validation of ETF proxy data quality and coverage

**Business Impact**:
- **Global Coverage**: Comprehensive exchange factor coverage for international portfolios
- **Sector Intelligence**: Enhanced sector analysis with group-based aggregation
- **Macro Analysis**: Asset class correlation analysis for strategic allocation
- **Data Quality**: Systematic ETF proxy validation ensures reliable factor calculations
- **Operational Efficiency**: Database-first architecture with YAML backup for resilience

### Enhanced Beta Sensitivity Analysis

**Advanced Beta Sensitivity Tables**:
The Risk Module includes comprehensive beta sensitivity analysis that calculates and displays rate and market sensitivity for ETFs with enhanced sector preference ordering and intelligent labeling.

**Core Features**:
- **Rate Beta Analysis**: Multi-maturity Treasury rate exposure (2Y, 5Y, 10Y, 30Y) with beta calculation against yield changes
- **Market Beta Analysis**: Market sensitivity analysis against multiple benchmarks (SPY, QQQ, IWM, etc.)
- **Sector Preference Ordering**: Advanced sector grouping and preference ordering using core sector ETFs
- **Enhanced Display Formatting**: Improved table formatting with proper alignment and label mapping
- **Factor Intelligence Integration**: Seamless integration with Factor Intelligence correlation analysis

**Rate Sensitivity Analysis**:
```
RATE BETA (ETF vs Δy)
                          UST2Y    UST5Y   UST10Y   UST30Y
Technology                +0.15    +0.25    +0.35    +0.20
Healthcare               -0.05    +0.10    +0.15    +0.05
Financial Services       +0.45    +0.65    +0.75    +0.40
Real Estate              +0.20    +0.40    +0.60    +0.80
```

**Market Sensitivity Analysis**:
```
MARKET BETA (ETF vs benchmarks)
                            SPY     QQQ     IWM
Technology                +1.15   +1.35   +0.85
Healthcare               +0.85   +0.75   +0.95
Financial Services       +1.25   +0.90   +1.45
Consumer Discretionary   +1.10   +1.05   +1.20
```

**Sector Preference System**:
The system uses a sophisticated sector preference ordering based on the core sector ETFs defined in `FACTOR_INTELLIGENCE_DEFAULTS`:

**Core Sector ETFs** (in preference order):
1. **XLK** - Technology
2. **XLV** - Healthcare
3. **XLF** - Financial Services
4. **XLY** - Consumer Discretionary
5. **XLP** - Consumer Staples
6. **XLE** - Energy
7. **XLI** - Industrials
8. **XLB** - Materials
9. **XLRE** - Real Estate
10. **XLU** - Utilities
11. **XLC** - Communication Services

**Technical Implementation**:
- **Sector Configuration Utils** (`utils/sector_config.py`): Manages sector preference resolution and label mapping
- **Enhanced Result Objects**: `FactorCorrelationResult` includes beta sensitivity table formatting with sector ordering
- **Intelligent Label Mapping**: Automatic resolution of ETF tickers to human-readable sector names
- **Fallback Strategies**: Robust fallback mechanisms for missing sector mappings

**Configuration Integration**:
```python
# settings.py - Factor Intelligence Defaults
FACTOR_INTELLIGENCE_DEFAULTS = {
    "core_sector_tickers": [
        "XLK", "XLV", "XLF", "XLY", "XLP", "XLE",
        "XLI", "XLB", "XLRE", "XLU", "XLC"
    ],
    "core_sector_labels": [
        "Technology", "Healthcare", "Financial Services",
        "Consumer Discretionary", "Consumer Staples", "Energy",
        "Industrials", "Materials", "Real Estate",
        "Utilities", "Communication Services"
    ]
}
```

**Display Enhancement Features**:
- **Preferred Ticker Ordering**: Tables display sector ETFs in preference order
- **Enhanced Formatting**: Improved column widths and alignment for better readability
- **Label Resolution**: Automatic mapping of ETF tickers to sector names
- **Consistent Styling**: Uniform formatting across rate and market sensitivity tables
- **Integration with Factor Intelligence**: Beta tables use same ordering and labeling as correlation matrices

**Business Impact**:
- **Improved Readability**: Sector preference ordering makes tables easier to interpret
- **Consistent Analysis**: Unified labeling across all factor intelligence features
- **Professional Output**: Enhanced formatting suitable for client presentations
- **Operational Efficiency**: Automated sector ordering reduces manual analysis time

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
- Interest Rate Factor (Key-rate duration exposure)

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

### Interest Rate Exposure Framework

**Key-Rate Duration Analysis**:
The Risk Module implements comprehensive interest rate risk analysis using empirical key-rate regression methodology for assets sensitive to interest rate movements (bonds, REITs).

**Key-Rate Changes (monthly)**:
```
Δy_{m,t} = (y_{m,t} − y_{m,t−1}) / 100
```
where yields `y_{m,t}` are percentages for Treasury maturities m ∈ {2y, 5y, 10y, 30y}; we divide by 100 to obtain decimal units (0.01 per 1%).

**Key-Rate Regression (per asset)**:
```
R_{i,t} = α_i + Σ_m β_{i,m} · Δy_{m,t} + ε_{i,t}
```
Fitted via multivariate OLS with HAC (Newey–West) standard errors. We use total-return prices for asset returns to incorporate distributions.

**Interest Rate Beta (aggregated)**:
```
β_{i,IR} = Σ_m β_{i,m}
```
This sum corresponds (up to sign) to effective duration in years for asset i.

**Effective Duration (reported)**:
```
Duration_i = |β_{i,IR}|   (years)
```
We report the magnitude as a positive value (years) for clarity, while the signed β_{i,IR} is still available for analysis (negative for long-duration assets).

**Portfolio Exposure**:
```
β_{p,IR} = Σ_i w_i · β_{i,IR}
Duration_p = |β_{p,IR}|   (years)
```
Aggregated through portfolio weights, exactly like other factors.

**Interest Rate Factor Volatility**:
```
σ_{IR} = std_t( Σ_m Δy_{m,t} ) × √12
```
Used for variance attribution alongside other factor volatilities.

**Diagnostics (logged)**:
- Adjusted R² per regression
- VIF per key-rate factor to flag multicollinearity
- Condition number of the design matrix

**Asset Eligibility**:
- Applied to assets classified as 'bond' and 'real_estate' (REITs)
- Cash proxies (e.g., SGOV) excluded from rate beta calculation
- Equities and other asset classes have interest_rate beta = 0

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

The Risk Module provides a complete full-stack web application with a production-ready FastAPI backend and a sophisticated React frontend dashboard.

### FastAPI Web App (`app.py`)

**Production-Ready FastAPI Backend** (4,687 lines):
- **FastAPI Framework**: High-performance async web framework with automatic API documentation
- **Pydantic Models**: Type-safe request/response validation with automatic schema generation
- **Multi-Provider OAuth**: Google, GitHub, Apple authentication with database sessions
- **Multi-Tier Access Control**: Public/Registered/Paid user tiers with sophisticated rate limiting (SlowAPI)
- **Async Architecture**: Non-blocking I/O for high-performance concurrent request handling
- **Automatic Documentation**: Interactive API docs at `/docs` with OpenAPI 3.0 schema
- **Plaid Integration**: Real-time portfolio import from 1000+ financial institutions
- **SnapTrade Integration**: Extended broker coverage for Fidelity, Schwab, and additional brokers
- **Provider Routing**: Intelligent routing between Plaid and SnapTrade with dynamic fallback
- **Claude AI Chat**: Interactive risk analysis with 16 portfolio analysis functions
- **RESTful API**: Comprehensive endpoints for portfolio analysis, risk scoring, and optimization
- **Database-First Architecture**: PostgreSQL with migration system and connection pooling
- **Admin Dashboard**: Usage tracking, error monitoring, performance metrics, and cache management
- **API Key Management**: Secure key generation, validation, and programmatic access

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

**Enterprise-Grade Single Page Application** with sophisticated multi-user architecture and enhanced streaming AI integration:

#### Multi-User State-Driven Architecture (`frontend/src/ARCHITECTURE.md`)

**Complete enterprise architecture** providing:

**1. Multi-Layer Architecture**:
- **App Orchestration Layer**: AppOrchestrator state machine with LandingApp/DashboardApp experiences
- **Provider Layer**: QueryProvider, AuthProvider, SessionServicesProvider for user isolation
- **State Management Layer**: Zustand stores (auth, portfolio, UI) + React Query server state
- **Service Layer**: 20+ service classes with dependency injection via ServiceContainer
- **Hook Layer**: Data access hooks with user-scoped caching and cancellation
- **Component Layer**: 6 dashboard views with intelligent loading strategies

**2. Dashboard Views (9 comprehensive views in `views/modern/`)**:
- **Portfolio Overview View**: High-level portfolio summary and key metrics
- **Holdings View**: Portfolio composition with weight analysis and risk attribution
- **Asset Allocation View**: Asset class allocation and breakdown analysis
- **Risk Analysis View**: Multi-factor exposure analysis with sector/style breakdowns
- **Performance Analytics View**: Historical performance metrics with benchmarking
- **Scenario Analysis View**: What-if scenario modeling and impact analysis
- **Stock Lookup View**: Individual stock research and factor analysis
- **Strategy Builder View**: Portfolio strategy construction and optimization
- **Risk Settings View**: Risk tolerance configuration and limit management

**3. Multi-User Security Architecture**:
```typescript
// User isolation via SessionServicesProvider
SessionServicesProvider creates per-user ServiceContainer:
├─ APIService (HTTP client with user auth tokens)
├─ PortfolioManager (User-scoped portfolio operations)
├─ PortfolioCacheService (User-specific data caching)
├─ ClaudeService (AI analysis with user context)
└─ ServiceContainer (Dependency injection with cleanup)

// Cache isolation with user-scoped keys
queryKey: ['portfolioSummary', userId, portfolioId]
queryKey: ['riskAnalysis', userId, portfolioId]
```

**4. Hybrid Loading Strategy (Performance-Optimized)**:
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

**5. Real Data Integration (Hook → Adapter → Manager → API Pattern)**:
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

**6. Enhanced Claude AI Chat Integration (Streaming + Context-Aware)**:
```typescript
// Enhanced streaming chat with Vercel AI SDK compatibility
const { 
  messages, 
  sendMessage, 
  status,           // submitted, streaming, ready, error, tool-executing
  stop, 
  regenerate, 
  reload 
} = usePortfolioChat();

// Chat with visual context integration and streaming
const handleSendMessage = async (message: string) => {
  const chatMessage = {
    content: message,
    context: {
      currentView: activeView,
      portfolioValue: portfolioSummary?.totalValue || 0,
      riskScore: portfolioSummary?.riskScore || 0,
      hasData: currentViewState.data !== null
    }
  };
  
  // Enhanced streaming API call with status tracking
  await sendMessage(message, { context: chatMessage.context });
};
```

**Enhanced Chat Features**:
- **Streaming Responses**: Token-by-token delivery with real-time status updates
- **Context-Aware Responses**: Claude receives current view data and portfolio state
- **Function Calling**: Chat can trigger view changes and data refreshes
- **Message Management**: Edit, delete, retry, regenerate functionality
- **Dual Interface**: Modal (AIChat) and full-screen (ChatInterface) options
- **Shared Logic**: Centralized in ChatCore component for consistency
- **Multi-modal Support**: File upload capabilities (in progress)
- **Real API Integration**: Connects to backend Claude API with portfolio context
- **Visual Integration**: Assistant can navigate between dashboard views based on conversation

**7. Comprehensive State Management (Zustand + Context)**:
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

**8. Production Logging and Performance Monitoring**:
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

**9. Real Portfolio Operations**:
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
User Action → React Component → Service Layer → FastAPI → Core Engine → Database
     ↓
React State ← Component Update ← Pydantic Response ← Business Logic ← Analysis Results
```

**Hook → Adapter → Manager → API Pattern**:
```javascript
// 1. React Hook (frontend/src/features/portfolio/hooks/usePortfolioSummary.ts)
const portfolioHook = usePortfolioSummary(); // Manages component state

// 2. Service Adapter (frontend/src/chassis/services/APIService.ts)  
const apiService = new APIService(); // Handles HTTP communication

// 3. Portfolio Manager (frontend/src/chassis/managers/PortfolioManager.ts)
const portfolioManager = new PortfolioManager(apiService, claudeService); // Business logic

// 4. Backend API (app.py)
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
├── App.tsx                        # Root component with provider hierarchy
├── router/
│   └── AppOrchestrator.tsx        # State machine for app experiences
├── components/
│   ├── apps/                      # Complete app experiences
│   │   ├── DashboardApp.tsx       # Authenticated user experience
│   │   └── LandingApp.tsx         # Authentication experience
│   ├── dashboard/                 # Dashboard components
│   │   ├── DashboardContainer.tsx # Dashboard state container
│   │   ├── DashboardRouter.tsx    # Dashboard navigation routing
│   │   ├── NavigationErrorBoundary.tsx # Error boundary for navigation
│   │   ├── ViewRenderer.tsx       # View rendering logic
│   │   ├── layout/                # Dashboard layout components
│   │   │   ├── DashboardLayout.tsx # Layout wrapper with navigation
│   │   │   ├── HeaderBar.tsx      # Dashboard header
│   │   │   ├── Sidebar.tsx        # Navigation sidebar
│   │   │   ├── SummaryBar.tsx     # Portfolio summary bar
│   │   ├── views/modern/          # Modern dashboard view containers
│   │   │   ├── PortfolioOverviewContainer.tsx    # Portfolio overview
│   │   │   ├── HoldingsViewModernContainer.tsx   # Portfolio holdings
│   │   │   ├── AssetAllocationContainer.tsx      # Asset allocation
│   │   │   ├── RiskAnalysisModernContainer.tsx   # Factor analysis + risk
│   │   │   ├── PerformanceViewContainer.tsx      # Performance analytics
│   │   │   ├── ScenarioAnalysisContainer.tsx     # What-if scenarios
│   │   │   ├── StockLookupContainer.tsx          # Stock research
│   │   │   ├── StrategyBuilderContainer.tsx      # Strategy builder
│   │   │   └── RiskSettingsContainer.tsx         # Risk settings
│   │   └── shared/                # Shared dashboard components
│   │       ├── ErrorBoundary.tsx  # Error handling
│   │       ├── charts/            # Chart components
│   │       │   ├── PerformanceLineChart.tsx
│   │       │   ├── RiskContributionChart.tsx
│   │       │   ├── RiskRadarChart.tsx
│   │       │   └── VarianceBarChart.tsx
│   │       └── ui/                # UI components
│   │           ├── LoadingView.tsx
│   │           ├── MetricsCard.tsx
│   │           ├── RiskScoreDisplay.tsx
│   │           └── StatusIndicator.tsx
│   ├── auth/                      # Authentication components
│   │   ├── GoogleSignInButton.tsx
│   │   └── LandingPage.tsx
│   ├── portfolio/                 # Portfolio management components
│   │   ├── PortfolioHoldings.tsx
│   │   ├── PlaidPortfolioHoldings.tsx
│   │   ├── RiskScoreDisplay.tsx
│   │   └── TabbedPortfolioAnalysis.tsx
│   ├── plaid/                     # Plaid integration components
│   │   ├── PlaidLinkButton.tsx
│   │   └── ConnectedAccounts.tsx
│   ├── chat/                      # Enhanced AI chat components
│   │   ├── AIChat.tsx             # Modal chat interface
│   │   ├── ChatContext.tsx        # Shared chat state
│   │   ├── RiskAnalysisChat.tsx   # Legacy component
│   │   ├── shared/
│   │   │   └── ChatCore.tsx       # Centralized chat logic
│   │   └── index.ts
│   ├── layouts/                   # Page layout components  
│   │   ├── DashboardLayout.tsx    # Main dashboard layout
│   │   └── ChatInterface.tsx      # Full-screen chat layout
│   ├── shared/                    # Reusable UI components
│   │   ├── ConditionalStates.tsx
│   │   ├── ErrorDisplay.tsx
│   │   ├── LoadingSpinner.tsx
│   │   └── StatusDisplay.tsx
│   └── transitions/               # Loading and transition components
│       └── AuthTransition.tsx
├── providers/                     # React context providers
│   ├── QueryProvider.tsx         # React Query provider
│   ├── AuthProvider.tsx          # Authentication context
│   └── SessionServicesProvider.tsx # User-scoped services
├── stores/                        # Zustand state management
│   ├── authStore.ts              # Authentication state
│   ├── portfolioStore.ts         # Portfolio data state
│   └── uiStore.ts                # UI state
├── features/                      # Feature-organized hooks and logic
│   ├── analysis/                  # Analysis feature
│   │   ├── hooks/                 # Analysis hooks (useFactorAnalysis, usePerformance)
│   │   └── formatters/            # Data formatters
│   ├── auth/hooks/                # Authentication hooks
│   ├── external/hooks/            # External service hooks (usePlaid, useSnapTrade, usePortfolioChat)
│   ├── portfolio/                 # Portfolio feature
│   │   ├── hooks/                 # Portfolio hooks (usePortfolio, usePortfolioSummary)
│   │   └── formatters/            # Portfolio data formatters
│   ├── risk/                      # Risk feature
│   │   ├── hooks/                 # Risk analysis hooks (useRiskAnalysis, useRiskScore)
│   │   └── formatters/            # Risk data formatters
│   ├── utils/hooks/               # Utility hooks (useCancelableRequest, useCancellablePolling)
│   ├── optimize/hooks/            # Portfolio optimization hooks
│   └── scenario/hooks/            # Scenario analysis hooks
├── adapters/                      # Data transformation layer
│   ├── FactorAnalysisAdapter.ts   # Factor analysis data transformation
│   ├── PerformanceAdapter.ts      # Performance data transformation
│   ├── PortfolioSummaryAdapter.ts # Portfolio summary transformation
│   ├── RiskAnalysisAdapter.ts     # Risk analysis transformation
│   ├── RiskDashboardAdapter.ts    # Dashboard data transformation
│   └── RiskScoreAdapter.ts        # Risk score data transformation
├── chassis/                       # Core infrastructure
│   ├── services/                  # API services and business logic
│   │   ├── APIService.ts          # HTTP client and authentication
│   │   ├── AuthService.ts         # Authentication operations
│   │   ├── ClaudeService.ts       # AI analysis integration
│   │   ├── PlaidService.ts        # Plaid integration
│   │   ├── PortfolioCacheService.ts # Data caching service
│   │   ├── RiskAnalysisService.ts # Risk analysis operations
│   │   └── ServiceContainer.ts    # Dependency injection container
│   ├── managers/                  # Business logic managers
│   │   ├── AuthManager.ts         # Authentication business logic
│   │   ├── PlaidManager.ts        # Plaid business logic
│   │   └── PortfolioManager.ts    # Portfolio business logic
│   ├── navigation/                # Navigation system
│   │   ├── NavigationIntents.ts   # Navigation intent system
│   │   └── NavigationResolver.ts  # Navigation resolution logic
│   ├── schemas/                   # API and data schemas
│   │   └── api-schemas.ts         # API request/response schemas
│   └── types/                     # TypeScript type definitions
├── utils/                         # Utilities and helpers
│   ├── AdapterRegistry.ts         # Adapter instance management
│   ├── ArchitecturalLogger.ts     # Architecture flow logging
│   ├── ErrorAdapter.ts            # Error standardization
│   ├── NavigationIntents.ts       # Navigation intent system
│   ├── broadcastLogout.ts         # Cross-tab logout synchronization
│   ├── sessionCleanup.ts          # Session cleanup utilities
│   └── loadRuntimeConfig.ts       # Runtime configuration loading
├── repository/                    # Data access layer
│   └── PortfolioRepository.ts     # Portfolio data operations
├── services/                      # Frontend utilities
│   ├── SecureStorage.ts           # Secure token storage
│   └── frontendLogger.ts          # Frontend logging service
├── config/                        # Configuration
│   ├── environment.ts             # Environment configuration
│   ├── portfolio.ts               # Portfolio configuration
│   └── queryConfig.ts             # React Query configuration
├── pages/                         # Page components
│   ├── InstantTryPage.tsx         # Instant try experience
│   └── LandingPage.tsx            # Landing page
├── data/                          # Data-related utilities
│   └── index.ts                   # Data exports
├── apiRegistry.ts                 # API endpoint registry
├── queryKeys.ts                   # React Query key management
├── index.js                       # Application entry point
├── App.css                        # Global styles
└── index.css                      # CSS entry point
```

**Key Architecture Benefits**:

1. **Multi-User Security**: 
   - Complete data isolation between users via SessionServicesProvider
   - User-scoped service instances prevent data bleeding
   - Secure cross-tab synchronization with auth state

2. **State-Driven Architecture**:
   - AppOrchestrator manages app state transitions as a state machine
   - Clear separation between authentication (LandingApp) and dashboard (DashboardApp) experiences
   - Timing-safe service initialization prevents race conditions

3. **Performance Optimization**:
   - Intelligent caching with React Query and user-scoped cache keys
   - Selective state subscriptions prevent unnecessary re-renders
   - Request deduplication and background synchronization
   - AdapterRegistry prevents adapter recreation across hook calls

4. **Production Monitoring**:
   - Comprehensive logging throughout the application with ArchitecturalLogger
   - Error boundaries for graceful failure handling
   - Performance tracking and optimization metrics

5. **Scalable Architecture**:
   - Clean separation of concerns across all layers (App/Provider/Store/Service/Hook/Component)
   - Easy to add new app experiences (AdminApp, OnboardingApp, MaintenanceApp)
   - Modular service and component design with dependency injection

**Recent Phase 3 Refactor Improvements:**
- **ServiceContainer**: Dependency injection container for per-user service instances
- **AdapterRegistry**: Parameterized caching for stable adapter instances with cleanup
- **useCancelableRequest**: Shared request cancellation logic across all hooks
- **ErrorAdapter**: Standardized error envelope format for consistent error handling
- **loadRuntimeConfig**: Zod-validated runtime configuration loading
- **NavigationIntents**: Intent-based navigation system for decoupled routing

### Route Documentation (`routes/`)

The web interface is organized into 5 specialized route modules for clean separation of concerns:

#### Core API Routes (`app.py`)
**Primary risk analysis endpoints (defined in main FastAPI application)**

| Endpoint | Method | Purpose | Returns |
|----------|--------|---------|---------|
| `/api/analyze` | POST | Portfolio risk analysis with asset class performance | Structured data + CLI-style formatted report + asset class performance metrics |
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

**Enhanced Parameters**:
- **performance_period**: Optional string parameter for asset class performance analysis
  - Supported values: "1M", "3M", "6M", "1Y", "YTD"
  - Default: "1M" if not specified
  - Enables real-time asset class performance calculation across time periods

**Request Example**:
```json
{
  "portfolio_name": "My Portfolio",
  "portfolio_data": {...},
  "performance_period": "3M"
}
```

**Features**:
- **Dual Output Format**: Both structured JSON data AND human-readable formatted reports
- **Asset Class Performance**: Real-time performance metrics by asset class over selected time periods
- **Time Period Flexibility**: Support for multiple analysis periods (1M, 3M, 6M, 1Y, YTD)
- Rate limiting by user tier
- Input validation and sanitization
- Comprehensive error handling
- Export functionality for analysis results

#### Claude AI Chat Routes (`routes/claude.py`)
**AI-powered conversational analysis with streaming capabilities**

| Endpoint | Method | Purpose | Parameters |
|----------|--------|---------|------------|
| `/api/claude_chat` | POST | Interactive AI analysis with streaming | `user_message`, `chat_history`, `portfolio_name` |

**Enhanced Features**:
- **Streaming Responses**: Token-by-token streaming compatible with Vercel AI SDK
- **Enhanced Status Tracking**: submitted, streaming, ready, error, tool-executing states
- Integration with 16 Claude functions across 6 categories
- Database-first architecture with user isolation
- Authentication required for all functions
- **Message Management**: Support for edit, delete, retry, regenerate operations
- **Multi-modal Support**: File upload capability (implementation in progress)
- Function calling and parameter validation
- Natural language result interpretation
- Session-based user authentication

#### Factor Intelligence Routes (`routes/factor_intelligence.py`)
**Advanced factor correlation analysis and macro sensitivity tools**

| Endpoint | Method | Purpose | Returns |
|----------|--------|---------|---------|
| `/api/factor-intelligence/correlations` | POST | Factor correlation matrix analysis | Correlation matrices by category (industry, style, market, rate, macro) |
| `/api/factor-intelligence/performance` | POST | Factor performance profiling | Performance metrics with rolling analysis and regime detection |
| `/api/factor-intelligence/recommendations/offset` | POST | Single offset recommendations | Market/rate offset suggestions for individual tickers |
| `/api/factor-intelligence/recommendations/portfolio-offset` | POST | Portfolio-level offset recommendations | Aggregate offset analysis for entire portfolios |

**Core Features**:
- **Multi-Category Analysis**: Industry (with sector groupings), Style factors (momentum, value), Market proxies, Rate sensitivity, Macro composites
- **Enhanced Industry Analysis**: Support for both individual industry mappings and sector group aggregation (defensive, cyclical, etc.)
- **Beta Sensitivity Tables**: Comprehensive rate and market sensitivity analysis with sector preference ordering
- **Asset Class Integration**: Seamless integration with asset ETF proxy system (bonds, commodities, crypto)
- **Exchange-Specific Factors**: Style and market factor analysis by exchange with geographic coverage
- **Rate Sensitivity Analysis**: Multi-maturity Treasury rate exposure (2Y, 5Y, 10Y, 30Y) with beta calculation
- **Market Sensitivity Analysis**: Market beta analysis against multiple benchmarks (SPY, QQQ, IWM, etc.)
- **Macro Composite Analysis**: Aggregate factor exposure across asset classes and regions
- **Performance Profiling**: Rolling correlation analysis with regime detection and volatility profiling

**Request Parameters**:
```json
{
  "start_date": "2010-01-31",
  "end_date": "2024-12-31",
  "factor_universe": "comprehensive",
  "max_factors": 50,
  "correlation_threshold": 0.7,
  "asset_class_filters": ["industry", "style", "market"],
  "industry_granularity": "group",
  "include_rate_sensitivity": true,
  "rate_maturities": ["UST2Y", "UST5Y", "UST10Y", "UST30Y"],
  "include_market_sensitivity": true,
  "market_benchmarks": ["SPY", "QQQ", "IWM"],
  "include_macro_composite": true,
  "sections": ["correlations", "performance"],
  "format": "detailed"
}
```

**Response Format**:
```json
{
  "success": true,
  "correlation_matrices": {
    "industry": {"matrix": {...}, "labels": [...], "sector_groups": {...}},
    "style": {"matrix": {...}, "exchange_breakdowns": {...}},
    "rate_sensitivity": {"betas": {...}, "r_squared": {...}},
    "market_sensitivity": {"betas": {...}, "benchmarks": [...]}
  },
  "performance_profiles": {
    "rolling_correlations": {...},
    "volatility_metrics": {...},
    "regime_analysis": {...}
  },
  "metadata": {
    "analysis_window": "2010-01-31 to 2024-12-31",
    "total_factors": 45,
    "coverage_stats": {...}
  },
  "formatted_report": "📊 FACTOR INTELLIGENCE ANALYSIS\n============..."
}
```

**Enhanced Architecture**:
- **Database-First Design**: Asset proxies, industry mappings, and exchange factors stored in PostgreSQL with caching
- **Service Layer Integration**: Leverages FactorIntelligenceService with comprehensive caching and error handling
- **Admin Tools Integration**: Seamless integration with enhanced admin tools for proxy management and validation
- **ETF Proxy Validation**: Real-time validation of ETF proxy coverage and data quality
- **Sector Preference System**: Advanced sector grouping and preference ordering for analysis

#### Plaid Integration Routes (`routes/plaid.py`)
**Brokerage account integration with connection management**

| Endpoint | Method | Purpose | Parameters |
|----------|--------|---------|------------|
| `/plaid/link` | POST | Create Plaid link token | `user_id` |
| `/plaid/exchange` | POST | Exchange public token | `public_token`, `user_id` |
| `/plaid/accounts` | GET | List connected accounts | `user_id` |
| `/plaid/holdings` | GET | Get account holdings | `user_id`, `account_id` |
| `/plaid/import` | POST | Import portfolio data | `user_id`, `account_id` |
| `/plaid/connections` | GET | List user's Plaid connections with management identifiers | - |
| `/plaid/connections/{institution_slug}` | DELETE | Disconnect specific Plaid institution connection | `institution_slug` |

**Enhanced Features**:
- **Multi-institution support** with connection management
- **Real-time holdings import** with data validation
- **Cash position mapping** with currency preservation
- **Portfolio YAML generation** with multi-source consolidation
- **AWS Secrets Manager integration** with secure credential storage
- **Complete connection lifecycle management**:
  - Connection listing with institution identification
  - Granular disconnection by institution slug (chase, fidelity, robinhood)
  - Complete cleanup including Plaid API removal, AWS secret deletion, database position cleanup
  - Provider-scoped position deletion to maintain data integrity
- **Enhanced authentication** with session-based user lookup
- **Comprehensive error handling** with detailed logging and user feedback

#### SnapTrade Integration Routes (`routes/snaptrade.py`)
**Brokerage account integration for Fidelity, Schwab, and other brokers**

| Endpoint | Method | Purpose | Parameters |
|----------|--------|---------|------------|
| `/snaptrade/register` | POST | Register user with SnapTrade | `user_id` |
| `/snaptrade/create-connection-url` | POST | Create connection URL for account linking | `user_id` |
| `/snaptrade/connections` | GET | List user's SnapTrade connections | - |
| `/snaptrade/holdings` | GET | Retrieve and store portfolio holdings | - |
| `/snaptrade/webhook` | POST | Handle SnapTrade webhook notifications | `webhook_data` |
| `/snaptrade/connections/{authorizationId}` | DELETE | Remove specific connection | `authorizationId` |
| `/snaptrade/user` | DELETE | Delete SnapTrade user and cleanup | - |

**Features**:
- Fidelity, Schwab, and extended broker support (supplements Plaid)
- Three-layer type mapping system preserving SnapTrade metadata
- Hybrid cash + securities fetching with unified holdings
- Provider-specific position management with multi-source consolidation
- AWS Secrets Manager integration for secure credential storage
- Always enabled in production (`ENABLE_SNAPTRADE = True` in `settings.py`)
- Session-based authentication with user isolation
- Comprehensive error handling and retry logic

#### Provider Routing Routes (`routes/provider_routing_api.py`)
**Dynamic provider routing and institution support management**

| Endpoint | Method | Purpose | Parameters |
|----------|--------|---------|------------|
| `/api/provider-routing/institution-support/{institution_slug}` | GET | Check provider support for institution | `institution_slug` |
| `/api/provider-routing/supported-institutions` | GET | List all supported institutions | - |
| `/api/provider-routing/status` | GET | Get provider health and routing status | - |
| `/api/provider-routing/metrics` | GET | Get routing analytics and metrics | - |

**Features**:
- Institution support checking across Plaid and SnapTrade
- Dynamic provider routing with intelligent fallback
- Real-time provider health monitoring
- Institution mapping and support discovery
- Routing analytics and performance metrics
- Public API (no authentication required)
- Caching for performance optimization

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

#### React Application (`frontend/src/App.tsx`)
**TypeScript-based React application with sophisticated component architecture**

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
├── App.tsx                    # Root application component with routing
├── router/
│   └── AppOrchestrator.tsx    # State machine for app experiences
├── components/
│   ├── apps/                  # Complete app experiences (DashboardApp, LandingApp)
│   ├── dashboard/             # Dashboard components and views
│   │   ├── views/modern/      # Modern view containers (10 TypeScript files)
│   │   ├── layout/            # Dashboard layout components
│   │   ├── shared/            # Shared dashboard components and charts
│   │   └── legacy/            # Legacy UI components for backward compatibility
│   ├── auth/                  # Authentication components
│   ├── chat/                  # Enhanced AI chat components
│   └── portfolio/             # Portfolio management components
├── chassis/                   # Core infrastructure
│   ├── services/              # API services (APIService, ClaudeService, etc.)
│   └── managers/              # Business logic managers
├── features/                  # Feature-organized hooks and logic
├── adapters/                  # Data transformation layer
├── providers/                 # React context providers
├── stores/                    # Zustand state management
└── utils/                     # Utilities and helpers
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
- Context API for global state (portfolio, auth)
- Zustand for complex client-side state (dashboard, UI)
- React Query (TanStack Query) for server state management
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
- Served through FastAPI static files
- CDN integration for assets
- Service worker for offline support
- Progressive Web App (PWA) capabilities

### Frontend-Backend Integration

**Data Flow**:
```
User Input → React Component → API Service → FastAPI Route → Core Engine → Database
     ↓
React State ← Component Update ← API Response ← Pydantic Response ← Analysis Results
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

**1. Interface Alignment Table (`docs/interface_alignment_table.md`)**
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
- **SnapTrade Integration**: 0% aligned (0/7 functions) - Missing CLI functions
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

### SnapTrade Financial Data Integration (`snaptrade_loader.py`)

**Extended Broker Coverage**:
- **Fidelity, Schwab & More**: Coverage for brokers not supported by Plaid
- **Three-Layer Type Mapping**: Preserves SnapTrade metadata while mapping to internal types
- **Hybrid Data Fetching**: Combined securities (positions) and cash (balances) retrieval
- **Provider-Specific Management**: Multi-source consolidation with provider tracking
- **AWS Secrets Management**: Secure storage of user credentials and connection data

**Data Flow**:
```
SnapTrade API → Holdings + Cash → Type Mapping → Normalization → Portfolio YAML → Risk Analysis
```

**Key Features**:
- SDK-based integration (snaptrade-python-sdk)
- Multi-account consolidation with type preservation
- Always enabled in production (`ENABLE_SNAPTRADE = True` in `settings.py`)
- Comprehensive error handling and retry logic
- Support for shorts and fractional shares
- Derivatives mapping to internal 'derivative' type

**Type Mapping System**:
1. **Raw SnapTrade**: Preserves API codes ("cs") + descriptions ("Common Stock")
2. **Internal Mapping**: Maps codes to standard types ("cs" → "equity")  
3. **System Usage**: Uses internal types for risk analysis and storage

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

## 🧪 Comprehensive Testing Framework

### Enterprise-Grade Testing Infrastructure

The Risk Module includes a production-ready testing framework with 95% test coverage and AI-powered orchestration:

**Test Suite Components:**

**0. Comprehensive Test Report** (`COMPREHENSIVE_TEST_REPORT.md`):
- **Full System Validation**: Complete test coverage across CLI, API, Claude functions, and database
- **Performance Benchmarks**: All 20+ test scenarios passed with excellent performance metrics
- **Production Readiness Assessment**: Comprehensive success report demonstrating enterprise-grade reliability
- **Real-World Testing**: Includes actual portfolio analysis, optimization, and scenario testing with live data

**1. AI Test Orchestration** (`tests/ai_test_orchestrator.py`):
- **Intelligent Test Execution**: AI-powered test selection and prioritization
- **Dynamic Test Generation**: Context-aware test case creation
- **Performance Regression Detection**: Automated performance baseline validation
- **Test Result Analysis**: AI-driven root cause analysis for failures

**2. End-to-End Testing** (`tests/e2e/`):
- **Playwright Integration**: Full browser testing with visual regression
- **Multi-User Scenarios**: Concurrent user testing with data isolation validation
- **Cross-Browser Compatibility**: Chrome, Firefox, Safari testing
- **Mobile Responsiveness**: Touch and mobile interaction testing

**3. Performance Benchmarks** (`tests/test_performance_benchmarks.py`):
- **Database Query Performance**: Target <100ms, actual 9.4ms average
- **Frontend Load Times**: <2 seconds to authenticated dashboard
- **Connection Pool Efficiency**: 2-5 connections with automatic scaling
- **Concurrent User Handling**: 100% success rate with 10+ simultaneous users
- **Memory Usage Monitoring**: 0.0MB per user memory overhead
- **Cache Integration**: 78,000x speedup validation

**4. Security & Isolation Tests** (`tests/test_user_isolation.py`):
- **Multi-User Data Isolation**: Complete separation between user sessions
- **Cross-Tab Security**: Secure logout synchronization testing
- **API Authentication**: Token validation and refresh mechanisms
- **SQL Injection Prevention**: Parameterized query validation
- **Session Security**: Session token management and expiration

**5. Fallback & Resilience** (`tests/test_fallback_mechanisms.py`):
- **Database Unavailable Scenarios**: Automatic fallback to file mode
- **Service Degradation**: Graceful handling of external API failures
- **Connection Timeout Handling**: Retry logic and circuit breaker patterns
- **Transaction Rollback**: ACID compliance and error recovery
- **Cache Invalidation**: Multi-tier cache consistency validation

**6. Integration Testing** (`tests/test_comprehensive_migration.py`):
- **Master Test Runner**: Orchestrates all test modules with dependency tracking
- **Database Migration Validation**: Schema evolution and data integrity
- **Production Readiness Assessment**: Comprehensive system health checks
- **Service Integration**: End-to-end workflow validation across all layers
- **Performance Regression**: Automated detection of performance degradation

**7. SnapTrade Integration Testing** (`tests/snaptrade/`):
- **Comprehensive Test Suite**: 7 specialized test files for complete SnapTrade API coverage
- **Authentication Testing**: Multi-stage authentication flow validation
- **Endpoint Coverage**: Complete API endpoint testing with real and simulated data
- **User Registration**: New user onboarding and existing user handling
- **Holdings Integration**: Portfolio data import and normalization validation
- **Error Handling**: Graceful degradation and fallback mechanism testing
- **Connection Management**: Session handling and token refresh validation

### Test Execution Commands

```bash
# AI-Powered Test Orchestration
cd tests && python3 ai_test_orchestrator.py          # Intelligent test execution
cd tests && python3 ai_test_orchestrator.py --focus=performance  # Performance focus

# End-to-End Testing
npm run test:e2e                                      # Full E2E suite with Playwright
npm run test:e2e:headed                               # Visual E2E testing

# Comprehensive Test Suite
cd tests && python3 test_comprehensive_migration.py  # Master test runner
cd tests && python3 test_performance_benchmarks.py   # Performance validation
cd tests && python3 test_user_isolation.py           # Security testing
cd tests && python3 test_fallback_mechanisms.py      # Fallback validation

# SnapTrade Integration Tests
cd tests/snaptrade && python3 test_snaptrade_integration.py      # Complete integration test
cd tests/snaptrade && python3 test_snaptrade_authenticated.py    # Authenticated user flows
cd tests/snaptrade && python3 test_snaptrade_endpoints.py        # API endpoint coverage
cd tests/snaptrade && python3 test_snaptrade_registration.py     # User registration flows

# Frontend Testing
npm test                                              # Jest unit tests
npm run test:coverage                                 # Coverage report
```

### Test Coverage Metrics

**Before Database Implementation**: 60% coverage
**After Database Implementation**: 95% coverage

**Coverage Breakdown:**
- **Backend Core Logic**: 95% coverage
- **Database Layer**: 100% coverage
- **Frontend Components**: 90% coverage
- **API Endpoints**: 95% coverage
- **User Authentication**: 90% coverage
- **Performance Benchmarks**: 100% coverage
- **Security & Isolation**: 100% coverage
- **Fallback Mechanisms**: 100% coverage
- **E2E User Workflows**: 85% coverage

## 📊 Comprehensive Logging & Monitoring Architecture

The Risk Module implements a sophisticated multi-layered logging architecture that provides real-time monitoring, debugging capabilities, and production-grade observability.

### Enhanced Logging Infrastructure

**Environment-Based Configuration** (`utils/logging.py`):
```python
# Production-optimized log levels (reduced verbosity)
PRODUCTION_LEVELS = {
    "database": logging.ERROR,      # Only log database errors
    "api": logging.WARNING,         # Log API errors and slow requests
    "claude": logging.INFO,         # Track AI usage (cost monitoring)
    "performance": logging.WARNING, # Only log slow operations (>1s)
    "frontend": logging.WARNING     # Only log frontend errors
}

# Development log levels (comprehensive debugging)  
DEVELOPMENT_LEVELS = {
    "database": logging.DEBUG,      # All database operations
    "api": logging.INFO,           # All API requests
    "claude": logging.DEBUG,        # Full AI interaction tracking
    "performance": logging.INFO,    # All performance metrics
    "frontend": logging.DEBUG       # All frontend operations
}
```

### API Request/Response Logging

**Enhanced Request Logging Decorators**:
```python
from utils.logging import log_api_request, log_api_health

@log_api_health("PortfolioAPI", "analyze")
@app.post("/api/analyze")
async def api_analyze_portfolio(request: Request):
    """
    Automatic logging of:
    - Raw request body for debugging Pydantic validation
    - User identification and authentication status
    - Request/response data structure analysis
    - Performance metrics and timing
    - Full error tracking with architectural context
    """
```

**Pydantic Validation Error Logging**:
```python
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Enhanced validation error handling with:
    - Raw request body logging for frontend/backend debugging
    - Detailed field-by-field validation error breakdown
    - Field name mapping analysis for API alignment issues
    - Request headers and method logging
    """
    return JSONResponse(
        status_code=422,
        content={
            "detail": exc.errors(),
            "message": "Request validation failed - check field names and structure",
            "validation_details": validation_details,
            "raw_body_logged": True
        }
    )
```

### Architectural Context Logging

**Real-Time Architectural Guidance**:
```python
class ArchitecturalContextFormatter(logging.Formatter):
    """Custom formatter that includes architectural context in log output"""
    
    def format(self, record):
        # Add architectural layer information
        if hasattr(record, 'architectural_context'):
            layer = record.architectural_context.get('layer', 'unknown')
            ai_guidance = record.architectural_context.get('ai_guidance', '')
            violations = record.architectural_context.get('violations', [])
            
            formatted_message += f"\n🏗️  Layer: {layer}"
            if ai_guidance:
                formatted_message += f"\n🤖 AI Guidance: {ai_guidance}"
            if violations:
                formatted_message += f"\n⚠️  Issues: {'; '.join(violations)}"
```

### Performance Monitoring

**API Health Monitoring** (`@log_api_health` decorator):
- **Response Time Tracking**: Sub-100ms performance monitoring
- **User Activity Tracking**: Per-user API usage analytics  
- **Endpoint Performance**: Individual endpoint performance metrics
- **Resource Usage**: Memory and CPU utilization tracking
- **Error Rate Monitoring**: Real-time error detection and alerting

**Frontend-Backend Alignment Logging**:
```python
# API Response debugging for frontend integration
api_logger.info(f"🔍 API Response /api/analyze - Status: 200")
api_logger.info(f"🔍 Response keys: {list(response_data.keys())}")
api_logger.info(f"🔍 Data keys: {list(response_data['data'].keys())}")
api_logger.info(f"🔍 Response size: ~{len(str(response_data))} chars")
```

### Multi-Level Logging Strategy

**Structured Log Categories**:
1. **Database Logger** (`database.log`) - All database operations and connection pooling
2. **API Logger** (`api.log`) - Request/response cycles, authentication, validation
3. **Performance Logger** (`performance.log`) - Timing metrics, slow operations, resource usage
4. **Claude Logger** (`claude.log`) - AI interaction tracking, cost monitoring, function execution
5. **Frontend Logger** (`frontend.log`) - Client-side error tracking, component lifecycle, state management
6. **Schema Logger** (`schema.log`) - Data validation, Pydantic model compliance, type checking

**Production Safety Features**:
- **Sensitive Data Redaction**: Automatic <TOKEN> replacement for secrets
- **Log Rotation**: Time-based and size-based log rotation
- **Performance Thresholds**: Only log operations >1s in production
- **Memory-Efficient**: Streaming logs to prevent memory buildup
- **Real-Time Streaming**: Live log monitoring capabilities

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

4. **Enhanced Logging Performance**:
   - Environment-based log level optimization
   - Asynchronous log writing to prevent I/O blocking
   - Intelligent log buffering and batching
   - Performance threshold filtering (>1s operations only in production)

### Memory Management

- Lazy loading of large datasets
- Garbage collection optimization
- Memory-efficient data structures
- Streaming for large files
- Log rotation and cleanup to prevent disk space issues

## 🧪 Testing Strategy

### Test Entry Points

1. **Portfolio Analysis**:
   ```bash
   python run_portfolio_risk.py
   ```

2. **Single Stock Profile**:
   ```bash
   python run_risk.py --stock AAPL
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

1. **Advanced AI Integration**:
   - ✅ **Implemented**: Claude AI with 16+ portfolio analysis functions
   - ✅ **Implemented**: Natural language risk reports and peer generation
   - ✅ **Implemented**: Automatic ticker detection and proxy assignment in what-if scenarios
   - ✅ **Implemented**: Auto-generation of expected returns using industry ETF methodology
   - ✅ **Implemented**: MCP servers for Claude Code (portfolio-mcp: 16 tools, fmp-mcp: 14 tools)
   - ✅ **Implemented**: Exit signal engine with momentum/regime rules
   - ✅ **Implemented**: Tax-loss harvesting with FIFO lot analysis and wash sale detection
   - ✅ **Implemented**: Dividend income projection engine
   - 🔄 **In Progress**: Intelligent factor selection and market regime detection
   - 📋 **Planned**: Automated portfolio rebalancing recommendations

2. **Enhanced Risk Models**:
   - 📋 **Planned**: Conditional Value at Risk (CVaR) and Expected Shortfall
   - 📋 **Planned**: Tail risk measures and extreme value theory
   - 📋 **Planned**: Dynamic factor models with regime switching
   - 📋 **Planned**: ESG risk integration and climate risk modeling

3. **Real-time Capabilities**:
   - ✅ **Implemented**: Real-time Plaid portfolio imports
   - ✅ **Implemented**: SnapTrade integration for extended broker coverage (Fidelity, Schwab)
   - ✅ **Implemented**: Trade execution via SnapTrade (preview-then-execute flow)
   - ✅ **Implemented**: IBKR Flex Query historical trade download (up to 365 days)
   - ✅ **Implemented**: IBKR gateway integration via ib_async
   - 📋 **Planned**: Live market data feeds and intraday risk monitoring
   - 📋 **Planned**: Alert system for risk limit breaches
   - 📋 **Planned**: Automated rebalancing with optimization

4. **Advanced Analytics**:
   - 📋 **Planned**: Backtesting framework with historical performance analysis
   - 📋 **Planned**: Strategy comparison and attribution analysis
   - 📋 **Planned**: Alternative data integration (sentiment, options flow)
   - 📋 **Planned**: Advanced portfolio construction with transaction costs

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
   - ✅ **Implemented**: Enterprise-grade React dashboard with multi-user architecture
   - ✅ **Implemented**: Comprehensive API endpoints with rate limiting and authentication
   - 📋 **Planned**: Mobile app support with React Native
   - 📋 **Planned**: Progressive Web App (PWA) capabilities with offline support

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
| Web Application | `app.py` | ✅ Production Ready | FastAPI backend + React dashboard with multi-user architecture |
| Frontend Dashboard | `frontend/` | ✅ Production Ready | Enterprise-grade React SPA with state management |
| MCP Server | `mcp_server.py` | ✅ Working | portfolio-mcp: 16 tools for Claude Code |
| FMP MCP Server | `fmp_mcp_server.py` | ✅ Working | fmp-mcp: 14 tools for financial data |
| Position Service | `position_service.py` | ✅ Working | Multi-provider position orchestration |
| Positions CLI | `run_positions.py` | ✅ Working | CLI for brokerage position data |
| Trading Analysis | `trading_analysis/` | ✅ Working | FIFO matcher, Plaid/SnapTrade/IBKR Flex normalization |
| Trading Execution | `services/trade_execution_service.py` | ✅ Working | Trade preview/execute via SnapTrade |
| IBKR Flex Client | `services/ibkr_flex_client.py` | ✅ Working | IBKR Flex Query trade download |
| IBKR Historical Data | `services/ibkr_historical_data.py` | ✅ Working | IBKR Gateway historical price fallback for futures |
| Income Projection | `core/income_projection.py` | ✅ Working | Dividend income projection engine |
| Exit Signals | `core/exit_signals.py` | ✅ Working | Momentum/regime exit signal engine |
| Tax Loss Harvest | `mcp_tools/tax_harvest.py` | ✅ Working | FIFO lot analysis, wash sale detection |
| Performance Engine | `core/performance_metrics_engine.py` | ✅ Working | Pure math performance computation |
| Realized Performance | `core/realized_performance_analysis.py` | ✅ Working | Transaction-based realized P&L |
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

- **fastapi**: High-performance async web framework (backend)
- **slowapi**: Rate limiting for FastAPI
- **psycopg2**: PostgreSQL database adapter
- **redis**: Caching and session management
- **uvicorn**: ASGI HTTP server for production

### Frontend Dependencies

- **react**: Frontend UI framework
- **typescript**: Type-safe JavaScript development
- **zustand**: State management
- **@tanstack/react-query**: Server state management
- **playwright**: End-to-end testing framework

### External API Dependencies

- **plaid**: Financial data integration
- **openai**: GPT integration for peer generation
- **anthropic**: Claude AI integration for portfolio analysis
- **fastmcp**: MCP server for Claude Code integration (portfolio-mcp and fmp-mcp)
- **boto3**: AWS Secrets Manager integration
- **snaptrade-python-sdk**: SnapTrade brokerage integration
- **ib_async**: Interactive Brokers gateway connection, Flex Query report download (FlexReport), historical data fallback
- **nest_asyncio**: Required for ib_async inside FastMCP's asyncio event loop

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

- [Readme.md](./readme.md): Project overview and usage guide
- [portfolio.yaml](./portfolio.yaml): Example portfolio configuration
- [risk_limits.yaml](./risk_limits.yaml): Risk limit definitions
- [admin/manage_reference_data.py](./admin/manage_reference_data.py): Database administration utilities
- [mcp_tools/README.md](./mcp_tools/README.md): MCP tool development guide
- [docs/API_REFERENCE.md](./docs/API_REFERENCE.md): REST API documentation
- [docs/DATABASE_REFERENCE.md](./docs/DATABASE_REFERENCE.md): Database schema documentation
- [docs/DEVELOPER_ONBOARDING.md](./docs/DEVELOPER_ONBOARDING.md): Developer onboarding guide
- [tests/TESTING_COMMANDS.md](./tests/TESTING_COMMANDS.md): Test execution commands
- [Financial Modeling Prep API](https://financialmodelingprep.com/developer/docs/): API documentation

---

**Architecture Version**: 1.2
**Last Updated**: 2026-02-12
**Maintainer**: Henry Souchien