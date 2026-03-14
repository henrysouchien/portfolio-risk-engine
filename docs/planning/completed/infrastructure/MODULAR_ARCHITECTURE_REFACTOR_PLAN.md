# Modular Architecture Vision

## Purpose

This document defines the **conceptual architecture** of the risk module as a set of modular, composable domains. It maps existing files to these conceptual modules WITHOUT requiring file moves or renames.

The goal is to provide a mental model for understanding and extending the codebase, and to enable AI-friendly orchestration through clear module boundaries and interfaces.

**Related Documents:**
- [MODULAR_CLI_ARCHITECTURE_PLAN.md](./MODULAR_CLI_ARCHITECTURE_PLAN.md) - CLI extraction details
- [FMP Layer Design](../fmp_layer_design.md) - FMP data abstraction layer (fits in Loaders layer)

---

## Part 1: Conceptual Architecture

### The Modules

The system is organized into **seven domain modules**, each defined by what output it produces:

| Module | Question it Answers | Output |
|--------|---------------------|--------|
| **Positions** | "What do I own?" | Holdings, values, allocations by account/asset class |
| **Risk** | "What's my risk?" | Volatility, VaR, factor exposures, betas, risk score |
| **Optimizer** | "How should I rebalance?" | Recommended weights (min-variance, max-return) |
| **Performance** | "How did I do?" | Returns, drawdowns, Sharpe ratio, attribution |
| **Factors** | "What drives my returns?" | Factor correlations, factor performance, offset recommendations |
| **Scenarios** | "What if I change X?" | Before/after comparison, impact analysis |
| **Trading** | "How did my trades perform?" | Trade analysis, P&L attribution, FIFO matching |

### Supporting Layers

Beyond the domain modules, the system has four supporting layers:

| Layer | Purpose |
|-------|---------|
| **Contracts** | Shared data types (inputs and outputs) used across all modules |
| **Loaders** | External data sources (Plaid, SnapTrade, market data APIs) |
| **Persistence** | Database operations, caching, reference data, portfolio CRUD |
| **Orchestrator** | MCP tools, API endpoints, CLI commands, service coordination, classification (enrichment), interpretation (AI presentation) |

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              ORCHESTRATOR                                    │
│                                                                              │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                     │
│   │     MCP     │    │     API     │    │     CLI     │                     │
│   │   Tools     │    │   Routes    │    │  Commands   │                     │
│   └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                     │
│          │                  │                  │                             │
│          └──────────────────┼──────────────────┘                             │
│                             │                                                │
│                    ┌────────▼────────┐                                       │
│                    │    Services     │  (coordinates modules + data)         │
│                    │  + Classification│  (enriches data before modules)       │
│                    │  + Interpretation│  (AI presentation of results)         │
│                    └────────┬────────┘                                       │
└─────────────────────────────┼───────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│    LOADERS    │    │    MODULES    │    │  PERSISTENCE  │
│               │    │               │    │               │
│ • Plaid       │    │ • Positions   │    │ • Database    │
│ • SnapTrade   │    │ • Risk        │    │ • Cache       │
│ • Market Data │    │ • Optimizer   │    │ • Portfolio   │
│               │    │ • Performance │    │ • Reference   │
│               │    │ • Factors     │    │               │
│               │    │ • Scenarios   │    │               │
│               │    │ • Trading     │    │               │
└───────┬───────┘    └───────┬───────┘    └───────┬───────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
                    ┌────────▼────────┐
                    │    CONTRACTS    │
                    │                 │
                    │ • Data Objects  │
                    │ • Result Objects│
                    │ • Enums/Types   │
                    └─────────────────┘
```

### Data Flow Principles

1. **Module core logic is pure**: Core analysis functions receive contract types as input and return contract types as output. Services within modules may add caching/validation but delegate to pure core functions.
2. **Modules don't access persistence directly**: Data is passed in via orchestrator, not fetched from DB within module code
3. **Modules don't import each other**: Only the orchestrator coordinates between modules
4. **Loaders fetch, modules transform, persistence stores**: Clear separation of concerns (exception: Positions module calls brokerage loaders directly as its core purpose)

**Clarification on "pure":** Each module contains:
- **Core functions** (pure): `analyze_risk()`, `optimize_portfolio()` - no I/O, just computation
- **Services** (may have I/O): Caching, validation wrappers that call core functions
- **CLI** (I/O): Entry points that parse args, call services/core, format output

The "pure" constraint applies to core analysis logic, not the entire module directory.

```
Orchestrator (coordinates everything)
    │
    ├──1──▶ Loaders (fetch raw data)
    │           │
    │           ▼
    │       raw data returned to orchestrator
    │
    ├──2──▶ Module (transform/analyze) ←── receives data as input
    │           │
    │           ▼
    │       result returned to orchestrator
    │
    └──3──▶ Output decision
                ├──▶ Return to API caller
                ├──▶ Save to database
                ├──▶ Write to JSON file (for AI chaining)
                └──▶ Pass to next module

Exception: Positions module calls brokerage loaders directly (step 1+2 combined)
```

---

## Part 2: Current File Mapping

This section maps **existing files** to the conceptual modules. No files need to be moved or renamed.

### Contracts (Shared Data Types)

These files define the shared language used across all modules:

| File | Purpose |
|------|---------|
| `core/data_objects.py` | Input types: `StockData`, `PortfolioData`, `PositionsData` |
| `core/result_objects.py` | Output types: All `*Result` classes with `to_api_response()` and `to_cli_report()` |
| `core/constants.py` | Shared constants: asset class colors, display names |
| `core/exceptions.py` | Custom exception types |

**Result Objects Available:**
- `PositionResult`
- `RiskAnalysisResult`
- `RiskScoreResult`
- `OptimizationResult`
- `PerformanceResult`
- `WhatIfResult`
- `StockAnalysisResult`
- `InterpretationResult`
- `FactorCorrelationResult`
- `FactorPerformanceResult`
- `OffsetRecommendationResult`
- `PortfolioOffsetRecommendationResult`

---

### Module: Positions

**Purpose:** Fetch and consolidate holdings from brokerage accounts

| File | Role in Module |
|------|----------------|
| `run_positions.py` | CLI entry point, main `run_positions()` function |
| `services/position_service.py` | Service layer with caching, coordinates loaders |

**Key Functions:**
- `run_positions()` in `run_positions.py` - Main entry point (dual-mode)
- `PositionService.fetch_plaid_positions()` - Fetch from Plaid with caching
- `PositionService.fetch_snaptrade_positions()` - Fetch from SnapTrade with caching
- `PositionService.get_all_positions()` - Consolidated view

**Input:** User email, source filter, consolidation options
**Output:** `PositionResult`

**Note on loader calls:** Positions module is an exception to the "orchestrator calls loaders" rule. Its core purpose IS to coordinate brokerage data fetching, so PositionService calls loaders directly. Other modules (Risk, Optimizer, Performance, etc.) receive data as input and don't call loaders.

---

### Module: Risk

**Purpose:** Analyze portfolio risk - volatility, factor exposures, betas, VaR, risk score

| File | Role in Module |
|------|----------------|
| `run_risk.py` | CLI entry point, contains `run_portfolio()`, `run_risk_score()` |
| `run_portfolio_risk.py` | Core calculation functions |
| `portfolio_risk.py` | Risk calculations: covariance, volatility, betas |
| `portfolio_risk_score.py` | Risk scoring system (0-100) |
| `risk_helpers.py` | Helper functions for risk analysis |
| `risk_summary.py` | Risk summary generation |
| `core/portfolio_analysis.py` | Pure analysis wrapper |
| `services/portfolio_service.py` | Service layer with caching |

**Key Functions:**
- `run_portfolio()` in `run_risk.py` - Full risk analysis (dual-mode)
- `run_risk_score()` in `run_risk.py` - Risk scoring (dual-mode)
- `build_portfolio_view()` in `portfolio_risk.py` - Core calculation
- `calculate_risk_score()` in `portfolio_risk_score.py` - Scoring logic

**Input:** Portfolio data (positions + config)
**Output:** `RiskAnalysisResult`, `RiskScoreResult`

---

### Module: Optimizer

**Purpose:** Calculate optimal portfolio weights (min-variance, max-return)

| File | Role in Module |
|------|----------------|
| `run_risk.py` | Contains `run_min_variance()`, `run_max_return()` |
| `portfolio_optimizer.py` | Optimization algorithms |
| `core/optimization.py` | Pure optimization logic |
| `services/optimization_service.py` | Service layer with caching |

**Key Functions:**
- `run_min_variance()` in `run_risk.py` - Min-variance optimization (dual-mode)
- `run_max_return()` in `run_risk.py` - Max-return optimization (dual-mode)
- `run_min_var()` in `portfolio_optimizer.py` - Core algorithm
- `run_max_return_portfolio()` in `portfolio_optimizer.py` - Core algorithm

**Input:** Portfolio data, constraints
**Output:** `OptimizationResult`

---

### Module: Performance

**Purpose:** Calculate portfolio performance - returns, drawdowns, Sharpe ratio

| File | Role in Module |
|------|----------------|
| `run_risk.py` | Contains `run_portfolio_performance()` |
| `core/performance_analysis.py` | Performance calculation logic |
| `core/asset_class_performance.py` | Asset class breakdown |
| `services/returns_service.py` | Returns calculation service |

**Key Functions:**
- `run_portfolio_performance()` in `run_risk.py` - Performance analysis (dual-mode)

**Input:** Portfolio data, date range
**Output:** `PerformanceResult`

---

### Module: Factors

**Purpose:** Factor analysis - correlations, performance attribution, offset recommendations

| File | Role in Module |
|------|----------------|
| `run_factor_intelligence.py` | CLI entry point, main functions |
| `factor_utils.py` | Factor calculation utilities |
| `proxy_builder.py` | ETF proxy construction |
| `core/factor_intelligence.py` | Factor universe building |
| `services/factor_intelligence_service.py` | Service layer |
| `services/factor_proxy_service.py` | Proxy loading service |

**Key Functions:**
- `run_factor_correlations()` in `run_factor_intelligence.py` - Correlation analysis
- `run_factor_performance()` in `run_factor_intelligence.py` - Factor performance
- `run_offset_recommendations()` in `run_factor_intelligence.py` - Find hedges
- `run_portfolio_offset_recommendations()` in `run_factor_intelligence.py` - Portfolio hedges

**Input:** Date range, factor categories, universe config
**Output:** `FactorCorrelationResult`, `FactorPerformanceResult`, `OffsetRecommendationResult`

---

### Module: Scenarios

**Purpose:** What-if analysis - impact of adding/removing positions

| File | Role in Module |
|------|----------------|
| `run_risk.py` | Contains `run_what_if()` |
| `core/scenario_analysis.py` | Scenario calculation logic |
| `services/scenario_service.py` | Service layer |

**Key Functions:**
- `run_what_if()` in `run_risk.py` - What-if analysis (dual-mode)

**Input:** Current portfolio, proposed changes
**Output:** `WhatIfResult`

---

### Layer: Persistence

**Purpose:** Portfolio CRUD, database operations, caching, reference data (not a domain module - a supporting layer)

| File | Role in Module |
|------|----------------|
| `inputs/portfolio_manager.py` | Portfolio CRUD (DB + file modes) |
| `inputs/database_client.py` | Database queries |
| `inputs/risk_limits_manager.py` | Risk limits management |
| `inputs/provider_settings_manager.py` | Provider config |
| `database/session.py` | Connection pooling |
| `database/pool.py` | Pool management |

**Key Functions:**
- `PortfolioManager.create_portfolio()` - Create portfolio
- `PortfolioManager.load_portfolio()` - Load portfolio
- `DatabaseClient.save_positions_from_dataframe()` - Save positions
- `DatabaseClient.get_positions()` - Load positions

**Input:** Portfolio name, user ID, data
**Output:** Portfolio configs, positions data

---

### Loaders (External Data Sources)

| File | Purpose |
|------|---------|
| `plaid_loader.py` | Plaid API integration - fetch holdings |
| `snaptrade_loader.py` | SnapTrade API integration - fetch holdings |
| `data_loader.py` | Market data - prices, returns, dividends |

**Key Functions:**
- `fetch_plaid_holdings()` in `plaid_loader.py`
- `fetch_snaptrade_holdings()` in `snaptrade_loader.py`
- `fetch_monthly_close()`, `latest_price()` in `data_loader.py`

---

### Orchestrator

#### MCP Tools
| File | Purpose |
|------|---------|
| `mcp_server.py` | FastMCP server entry point |
| `mcp_tools/positions.py` | `get_positions` MCP tool |
| `mcp_tools/__init__.py` | Tool exports |

#### API Routes
| File | Purpose |
|------|---------|
| `app.py` | FastAPI application |
| `routes/plaid.py` | Plaid endpoints |
| `routes/snaptrade.py` | SnapTrade endpoints |
| `routes/claude.py` | Claude AI endpoints |
| `routes/auth.py` | Authentication |
| `routes/admin.py` | Admin/monitoring |
| `routes/factor_intelligence.py` | Factor analysis endpoints |

#### Services (Current Location - Will Be Distributed)

**Note:** Domain-specific services will move to their respective modules. Only cross-cutting services stay in orchestrator.

| File | Current Purpose | Moves To |
|------|-----------------|----------|
| `services/position_service.py` | Coordinates position fetching | `modules/positions/` |
| `services/portfolio_service.py` | Coordinates risk analysis | `modules/risk/` |
| `services/stock_service.py` | Coordinates stock analysis | `modules/risk/` |
| `services/optimization_service.py` | Coordinates optimization | `modules/optimizer/` |
| `services/scenario_service.py` | Coordinates scenarios | `modules/scenarios/` |
| `services/factor_intelligence_service.py` | Coordinates factor analysis | `modules/factors/` |
| `services/auth_service.py` | Authentication | `orchestrator/services/` (cross-cutting) |
| `services/validation_service.py` | Input validation | `orchestrator/services/` (cross-cutting) |

---

### Shared Utilities

| File | Purpose |
|------|---------|
| `settings.py` | Global configuration |
| `utils/config.py` | Configuration helpers |
| `utils/logging.py` | Logging setup and decorators |
| `utils/serialization.py` | JSON serialization |
| `utils/auth.py` | Auth utilities |
| `utils/errors.py` | Error handling |

---

## Part 3: Module Interfaces

Each module has a defined interface (input types → output types). This is the "contract" that allows modules to be composed.

### Positions Module Interface

```
Input:
  - user_email: str
  - source: "all" | "plaid" | "snaptrade"
  - consolidate: bool
  - use_cache: bool

Output:
  - PositionResult
    - positions: List[Position]
    - summary: dict (total_value, by_asset_class, by_account)
    - metadata: dict (timestamp, source, cache_status)

Methods:
  - to_api_response() → dict
  - to_cli_report() → str
```

### Risk Module Interface

```
Input:
  - positions: PositionsData | dict | DataFrame
  - config: RiskConfig (optional)
  - include_factors: bool

Output:
  - RiskAnalysisResult
    - portfolio_volatility: float
    - var_95: float
    - factor_exposures: dict
    - betas: dict
    - risk_contributions: dict
    - ...

Methods:
  - to_api_response() → dict
  - to_cli_report() → str
```

### Optimizer Module Interface

```
Input:
  - positions: PositionsData
  - mode: "min-variance" | "max-return"
  - constraints: OptimizationConstraints (optional)

Output:
  - OptimizationResult
    - current_weights: dict
    - optimal_weights: dict
    - expected_return: float
    - expected_volatility: float
    - trades: List[Trade]

Methods:
  - to_api_response() → dict
  - to_cli_report() → str
```

### Performance Module Interface

```
Input:
  - positions: PositionsData
  - start_date: date
  - end_date: date

Output:
  - PerformanceResult
    - total_return: float
    - annualized_return: float
    - volatility: float
    - sharpe_ratio: float
    - max_drawdown: float
    - by_asset_class: dict

Methods:
  - to_api_response() → dict
  - to_cli_report() → str
```

### Factors Module Interface

```
Input:
  - start_date: date
  - end_date: date
  - factor_categories: List[str]
  - industry_granularity: "group" | "industry"

Output:
  - FactorCorrelationResult
    - correlation_matrix: DataFrame
    - factor_returns: DataFrame
    - overlays: dict (rate_sensitivity, market_sensitivity)

Methods:
  - to_api_response() → dict
  - to_cli_report() → str
```

### Scenarios Module Interface

```
Input:
  - current_positions: PositionsData
  - changes: List[PositionChange]  # {ticker, action, amount}

Output:
  - WhatIfResult
    - before: RiskAnalysisResult
    - after: RiskAnalysisResult
    - delta: dict (risk changes)

Methods:
  - to_api_response() → dict
  - to_cli_report() → str
```

---

## Part 4: How Modules Connect (Data Flow)

### Example: Full Risk Analysis Flow

```
User: "What's my risk?"

1. Orchestrator receives request (API/CLI/MCP)

2. Orchestrator calls Positions Module:
   run_positions(user_email, source="all")
   → PositionResult
   (Positions module internally calls loaders - it's the exception)

3. Orchestrator calls Risk Module:
   run_portfolio(positions_data, return_data=True)
   → RiskAnalysisResult

4. Orchestrator decides what to do:
   - API: return result.to_api_response()
   - CLI: print result.to_cli_report()
   - MCP: return structured dict
   - Save to DB (optional)
```

### Example: AI Chaining via JSON Files

```bash
# Step 1: Positions module outputs JSON
python run_positions.py --user-email user@example.com \
  --format json --output /tmp/positions.json

# Step 2: Risk module reads JSON, outputs JSON
python run_risk.py --input /tmp/positions.json \
  --format json --output /tmp/risk.json

# Step 3: Optimizer reads risk output
python run_risk.py optimize --input /tmp/risk.json \
  --mode min-variance --format json --output /tmp/optimized.json
```

Each module is independent. The orchestrator (or AI) chains them via JSON files.

---

## Part 5: Extending the Architecture

### Adding a New Module

1. **Define the output** - What question does it answer?
2. **Create Result Object** in `contracts/result_objects.py` with `to_api_response()` and `to_cli_report()`
3. **Create core logic** in `modules/<module_name>/` (use `run_<name>.py` to match existing convention, or `core.py` for new style)
4. **Add CLI entry point** following dual-mode pattern (existing modules use `run_*.py` which serves as both core and CLI)
5. **Add Service** in module if caching/validation needed
6. **Add MCP tool** in `orchestrator/mcp/tools/` if AI access needed
7. **Add API route** in `orchestrator/api/routes/` if web access needed

**Naming convention:** Existing modules use `run_*.py` for combined core+CLI. New modules can follow this pattern for consistency, or use separate `core.py`/`cli.py` if cleaner separation is preferred.

### Adding a New Loader

1. **Create loader file** in `loaders/<provider>/`
2. **Implement fetch function** that returns normalized data
3. **Wire loader** to calling code (see below)

**Who calls loaders:**
- **Positions module** calls brokerage loaders directly (Plaid, SnapTrade) - this is its core purpose
- **Orchestrator** calls market data loaders when needed before passing to analysis modules
- **Analysis modules** (Risk, Optimizer, Performance, etc.) receive data as input, don't call loaders

### Adding a New MCP Tool

1. **Create tool file** in `orchestrator/mcp/tools/`
2. **Import from appropriate module** (e.g., `from modules.risk import run_portfolio`)
3. **Register with FastMCP** in `orchestrator/mcp/server.py`
4. **Document in `orchestrator/mcp/tools/README.md`**

---

## Part 6: Proposed Folder Structure

This section defines the **target folder structure** if we choose to reorganize files. Each current file is mapped to its proposed new location.

### Target Structure

```
risk_module/
│
├── contracts/                      # Shared data types
│   ├── __init__.py
│   ├── data_objects.py             # ← from core/data_objects.py
│   ├── result_objects.py           # ← from core/result_objects.py
│   ├── constants.py                # ← from core/constants.py
│   ├── exceptions.py               # ← from core/exceptions.py
│   └── models/                     # Pure types only (no FastAPI deps)
│       ├── __init__.py
│       └── ...                     # ← from models/ (pure types after classification)
│
├── modules/
│   ├── positions/                  # Positions module
│   │   ├── __init__.py
│   │   ├── run_positions.py        # ← from run_positions.py
│   │   └── position_service.py     # ← from services/position_service.py
│   │
│   ├── risk/                       # Risk analysis module
│   │   ├── __init__.py
│   │   ├── run_risk.py             # ← from run_risk.py
│   │   ├── run_portfolio_risk.py   # ← from run_portfolio_risk.py
│   │   ├── portfolio_risk.py       # ← from portfolio_risk.py
│   │   ├── portfolio_risk_score.py # ← from portfolio_risk_score.py
│   │   ├── risk_helpers.py         # ← from risk_helpers.py
│   │   ├── risk_summary.py         # ← from risk_summary.py
│   │   ├── portfolio_analysis.py   # ← from core/portfolio_analysis.py
│   │   ├── stock_analysis.py       # ← from core/stock_analysis.py
│   │   ├── portfolio_service.py    # ← from services/portfolio_service.py
│   │   └── stock_service.py        # ← from services/stock_service.py
│   │
│   ├── optimizer/                  # Optimization module
│   │   ├── __init__.py
│   │   ├── portfolio_optimizer.py  # ← from portfolio_optimizer.py
│   │   ├── optimization.py         # ← from core/optimization.py
│   │   └── optimization_service.py # ← from services/optimization_service.py
│   │
│   ├── performance/                # Performance module
│   │   ├── __init__.py
│   │   ├── performance_analysis.py # ← from core/performance_analysis.py
│   │   ├── asset_class_performance.py # ← from core/asset_class_performance.py
│   │   └── returns_service.py      # ← from services/returns_service.py
│   │
│   ├── factors/                    # Factor intelligence module
│   │   ├── __init__.py
│   │   ├── run_factor_intelligence.py # ← from run_factor_intelligence.py
│   │   ├── factor_utils.py         # ← from factor_utils.py
│   │   ├── proxy_builder.py        # ← from proxy_builder.py
│   │   ├── factor_intelligence.py  # ← from core/factor_intelligence.py
│   │   ├── factor_intelligence_service.py # ← from services/factor_intelligence_service.py
│   │   └── factor_proxy_service.py # ← from services/factor_proxy_service.py
│   │
│   ├── scenarios/                  # Scenarios module
│   │   ├── __init__.py
│   │   ├── scenario_analysis.py    # ← from core/scenario_analysis.py
│   │   └── scenario_service.py     # ← from services/scenario_service.py
│   │
│   └── trading/                    # Trading analysis module
│       ├── __init__.py
│       └── ...                     # ← from trading_analysis/*
│
├── persistence/                    # Database & storage
│   ├── __init__.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── pool.py                 # ← from database/pool.py
│   │   ├── session.py              # ← from database/session.py
│   │   └── client.py               # ← from inputs/database_client.py
│   ├── portfolio/
│   │   ├── __init__.py
│   │   ├── portfolio_manager.py    # ← from inputs/portfolio_manager.py
│   │   ├── risk_limits_manager.py  # ← from inputs/risk_limits_manager.py
│   │   └── provider_settings_manager.py # ← from inputs/provider_settings_manager.py
│   └── reference/
│       ├── __init__.py
│       └── (YAML files stay at root or move here)
│
├── loaders/                        # External data sources
│   ├── __init__.py
│   ├── plaid/
│   │   ├── __init__.py
│   │   └── plaid_loader.py         # ← from plaid_loader.py
│   ├── snaptrade/
│   │   ├── __init__.py
│   │   └── snaptrade_loader.py     # ← from snaptrade_loader.py
│   └── financial_data/             # Financial data APIs (see fmp_layer_design.md)
│       ├── __init__.py
│       ├── fmp/                    # FMP abstraction layer
│       │   ├── __init__.py
│       │   ├── client.py
│       │   ├── registry.py
│       │   ├── cache.py
│       │   └── compat.py
│       └── data_loader.py          # ← from data_loader.py (uses fmp/ internally)
│
├── orchestrator/                   # API, MCP, CLI coordination
│   ├── __init__.py
│   ├── mcp/
│   │   ├── __init__.py
│   │   ├── server.py               # ← from mcp_server.py
│   │   └── tools/                  # ← from mcp_tools/
│   │       ├── __init__.py
│   │       └── positions.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py                  # ← from app.py
│   │   ├── routes/                 # ← from routes/
│   │   │   ├── __init__.py
│   │   │   ├── plaid.py
│   │   │   ├── snaptrade.py
│   │   │   ├── auth.py
│   │   │   └── ...
│   │   └── models/                 # API-specific models (FastAPI/Pydantic)
│   │       ├── __init__.py
│   │       └── ...                 # ← from models/ (API response models only)
│   └── services/                   # Coordination services
│       ├── __init__.py
│       ├── auth_service.py         # ← from services/auth_service.py
│       ├── validation_service.py   # ← from services/validation_service.py
│       ├── security_type_service.py # ← from services/security_type_service.py (classification)
│       ├── interpretation.py       # ← from core/interpretation.py
│       ├── gpt_helpers.py          # ← from gpt_helpers.py
│       ├── mappings/               # Classification config files
│       │   ├── industry_to_etf.yaml
│       │   ├── exchange_etf_proxies.yaml
│       │   ├── asset_etf_proxies.yaml
│       │   ├── cash_map.yaml
│       │   └── security_type_mappings.yaml
│       └── ...
│
├── shared/                         # Cross-cutting utilities
│   ├── __init__.py
│   ├── settings.py                 # ← from settings.py
│   ├── config.py                   # ← from utils/config.py
│   ├── logging.py                  # ← from utils/logging.py
│   ├── serialization.py            # ← from utils/serialization.py
│   ├── auth.py                     # ← from utils/auth.py
│   └── errors.py                   # ← from utils/errors.py
│
├── frontend/                       # React app (unchanged)
│   └── ...
│
├── tests/                          # Tests (unchanged, update imports)
│   └── ...
│
└── docs/                           # Documentation (unchanged)
    └── ...
```

### File Movement Summary

#### Contracts (4 files)
| Current Location | New Location |
|------------------|--------------|
| `core/data_objects.py` | `contracts/data_objects.py` |
| `core/result_objects.py` | `contracts/result_objects.py` |
| `core/constants.py` | `contracts/constants.py` |
| `core/exceptions.py` | `contracts/exceptions.py` |

#### Positions Module (2 files)
| Current Location | New Location |
|------------------|--------------|
| `run_positions.py` | `modules/positions/run_positions.py` |
| `services/position_service.py` | `modules/positions/position_service.py` |

#### Risk Module (10 files)
| Current Location | New Location |
|------------------|--------------|
| `run_risk.py` | `modules/risk/run_risk.py` |
| `run_portfolio_risk.py` | `modules/risk/run_portfolio_risk.py` |
| `portfolio_risk.py` | `modules/risk/portfolio_risk.py` |
| `portfolio_risk_score.py` | `modules/risk/portfolio_risk_score.py` |
| `risk_helpers.py` | `modules/risk/risk_helpers.py` |
| `risk_summary.py` | `modules/risk/risk_summary.py` |
| `core/portfolio_analysis.py` | `modules/risk/portfolio_analysis.py` |
| `core/stock_analysis.py` | `modules/risk/stock_analysis.py` |
| `services/portfolio_service.py` | `modules/risk/portfolio_service.py` |
| `services/stock_service.py` | `modules/risk/stock_service.py` |

#### Optimizer Module (3 files)
| Current Location | New Location |
|------------------|--------------|
| `portfolio_optimizer.py` | `modules/optimizer/portfolio_optimizer.py` |
| `core/optimization.py` | `modules/optimizer/optimization.py` |
| `services/optimization_service.py` | `modules/optimizer/optimization_service.py` |

#### Performance Module (3 files)
| Current Location | New Location |
|------------------|--------------|
| `core/performance_analysis.py` | `modules/performance/performance_analysis.py` |
| `core/asset_class_performance.py` | `modules/performance/asset_class_performance.py` |
| `services/returns_service.py` | `modules/performance/returns_service.py` |

#### Factors Module (6 files)
| Current Location | New Location |
|------------------|--------------|
| `run_factor_intelligence.py` | `modules/factors/run_factor_intelligence.py` |
| `factor_utils.py` | `modules/factors/factor_utils.py` |
| `proxy_builder.py` | `modules/factors/proxy_builder.py` |
| `core/factor_intelligence.py` | `modules/factors/factor_intelligence.py` |
| `services/factor_intelligence_service.py` | `modules/factors/factor_intelligence_service.py` |
| `services/factor_proxy_service.py` | `modules/factors/factor_proxy_service.py` |

#### Scenarios Module (2 files)
| Current Location | New Location |
|------------------|--------------|
| `core/scenario_analysis.py` | `modules/scenarios/scenario_analysis.py` |
| `services/scenario_service.py` | `modules/scenarios/scenario_service.py` |

#### Persistence (7 files)
| Current Location | New Location |
|------------------|--------------|
| `database/pool.py` | `persistence/database/pool.py` |
| `database/session.py` | `persistence/database/session.py` |
| `inputs/database_client.py` | `persistence/database/client.py` |
| `inputs/portfolio_manager.py` | `persistence/portfolio/portfolio_manager.py` |
| `inputs/risk_limits_manager.py` | `persistence/portfolio/risk_limits_manager.py` |
| `inputs/provider_settings_manager.py` | `persistence/portfolio/provider_settings_manager.py` |
| `inputs/file_manager.py` | `persistence/portfolio/file_manager.py` |

#### Loaders (3 files to move + 1 implemented)
| Current Location | New Location | Status |
|------------------|--------------|--------|
| `plaid_loader.py` | `loaders/plaid/plaid_loader.py` | Pending |
| `snaptrade_loader.py` | `loaders/snaptrade/snaptrade_loader.py` | Pending |
| `data_loader.py` | `loaders/financial_data/data_loader.py` | Pending |
| `fmp/` (root) | `loaders/financial_data/fmp/` | ✅ **Implemented** (needs move) |

**FMP Layer Status:** The FMP abstraction layer is **fully implemented** at `fmp/` (root level). During migration, it will be moved to `loaders/financial_data/fmp/`. The implementation includes:
- `fmp/client.py` - FMPClient with fetch(), list_endpoints(), describe()
- `fmp/registry.py` - Declarative endpoint definitions
- `fmp/cache.py` - Two-tier caching (LRU + disk)
- `fmp/compat.py` - Backward-compatible wrappers for existing code
- `fmp/exceptions.py` - Structured exception hierarchy
- `tests/test_fmp_client.py` - Test coverage

See [FMP Layer Design](../fmp_layer_design.md) for full documentation.

#### Orchestrator - MCP (2+ files)
| Current Location | New Location |
|------------------|--------------|
| `mcp_server.py` | `orchestrator/mcp/server.py` |
| `mcp_tools/*` | `orchestrator/mcp/tools/*` |

#### Orchestrator - API (10+ files)
| Current Location | New Location |
|------------------|--------------|
| `app.py` | `orchestrator/api/app.py` |
| `routes/*` | `orchestrator/api/routes/*` |

#### Orchestrator - Services (coordination + cross-cutting)
| Current Location | New Location |
|------------------|--------------|
| `services/auth_service.py` | `orchestrator/services/auth_service.py` |
| `services/validation_service.py` | `orchestrator/services/validation_service.py` |
| `services/cache_mixin.py` | `orchestrator/services/cache_mixin.py` |
| `services/async_service.py` | `orchestrator/services/async_service.py` |
| `services/service_manager.py` | `orchestrator/services/service_manager.py` |
| `services/security_type_service.py` | `orchestrator/services/security_type_service.py` |
| `core/interpretation.py` | `orchestrator/services/interpretation.py` |
| `gpt_helpers.py` | `orchestrator/services/gpt_helpers.py` |

#### Shared Utilities (6+ files)
| Current Location | New Location |
|------------------|--------------|
| `settings.py` | `shared/settings.py` |
| `utils/config.py` | `shared/config.py` |
| `utils/logging.py` | `shared/logging.py` |
| `utils/serialization.py` | `shared/serialization.py` |
| `utils/auth.py` | `shared/auth.py` |
| `utils/errors.py` | `shared/errors.py` |

### YAML Configuration Files
| Current Location | New Location | Rationale |
|------------------|--------------|-----------|
| `industry_to_etf.yaml` | `orchestrator/services/mappings/` | Used by classification/SecurityTypeService |
| `exchange_etf_proxies.yaml` | `orchestrator/services/mappings/` | Used by classification |
| `asset_etf_proxies.yaml` | `orchestrator/services/mappings/` | Used by classification |
| `cash_map.yaml` | `orchestrator/services/mappings/` | Used by classification |
| `security_type_mappings.yaml` | `orchestrator/services/mappings/` | Used by classification |
| `risk_limits.yaml` | `persistence/portfolio/` | Portfolio/input configuration |
| `portfolio.yaml` | `persistence/portfolio/` | Sample portfolio (or stay at root as example) |

### Models Directory (Pydantic) - SPLIT REQUIRED
The `models/` directory contains BOTH pure types and API-specific models. These must be split:

| Current Location | New Location | Criteria |
|------------------|--------------|----------|
| Pure data types | `contracts/models/` | No `from fastapi import`, used by core module logic |
| API response models | `orchestrator/api/models/` | Imports FastAPI, used in route `response_model=`, HTTP-specific concerns |

**Classification criteria:**
- Check imports: `from fastapi import` → API model
- Check usage: used in `@app.get(..., response_model=X)` → API model
- Check content: HTTP status codes, OpenAPI descriptions → API model
- Everything else → pure type (even if it uses `Field()` for validation)

**Action:** Review each file in `models/` and classify before moving. Most response models will go to `orchestrator/api/models/`.

### Stock Analysis (Decided: Keep in Risk)
**Decision:** Keep stock analysis in `modules/risk/`. It's "risk analysis for a single stock" - same domain, shares significant code.

| File | Location |
|------|----------|
| `core/stock_analysis.py` | `modules/risk/stock_analysis.py` |
| `services/stock_service.py` | `modules/risk/stock_service.py` |

### Trading Analysis Module
| Current Location | New Location |
|------------------|--------------|
| `trading_analysis/*` | `modules/trading/` |

Trading analysis is its own domain - trade performance analysis, FIFO matching, etc.

### Files That Stay at Root
- `requirements.txt`, `requirements-dev.txt`
- `Makefile`
- `README.md`, `architecture.md`
- `.env`, `.env.example`
- `.gitignore`
- `admin/` directory
- `scripts/` directory
- `tools/` directory
- `cache_prices/` directory
- `cache_dividends/` directory
- `tests/` directory (organized internally by module)

### Entry Points (Decided)
**Decision:** Keep wrapper scripts at root for backward compatibility.

**After migration, entry points remain the same:**
```bash
python app.py                    # Start API server (wrapper → orchestrator.api.app)
python run_risk.py              # CLI risk analysis (wrapper → modules.risk.run_risk)
python run_positions.py         # CLI positions (wrapper → modules.positions.run_positions)
python mcp_server.py            # Start MCP server (wrapper → orchestrator.mcp.server)
```

Each wrapper is a thin redirect:
```python
# run_risk.py (at root)
"""Backward compatibility wrapper."""
import sys
from modules.risk.run_risk import main

if __name__ == "__main__":
    sys.exit(main())
```

### Additional File Placements (Reviewed)

| Current Location | New Location | Rationale |
|------------------|--------------|-----------|
| `helpers_display.py` | `shared/helpers_display.py` | Cross-cutting display/formatting utility used by multiple modules |
| `helpers_input.py` | `modules/scenarios/helpers_input.py` | Specifically parses what-if/scenario inputs (+200bp, YAML deltas) |
| `ai_function_registry.py` | `orchestrator/services/ai_function_registry.py` | Centralized Claude function definitions for AI chat orchestration |
| `position_metadata.py` | `modules/positions/position_metadata.py` | Position labeling and cash detection utilities |
| `inputs/returns_calculator.py` | `modules/performance/returns_calculator.py` | Expected returns calculation belongs in performance domain |

---

## Part 7: Migration Safety Rules

When moving files, follow these rules to avoid breaking the codebase:

### Rule 0: NO FILE RENAMING
**CRITICAL:** This migration is ONLY about moving files into folders. Do NOT rename any files. Keep all filenames exactly as they are. Renaming happens later (if ever) as a separate step.

```
CORRECT:   run_risk.py → modules/risk/run_risk.py
WRONG:     run_risk.py → modules/risk/cli.py
```

### Rule 1: One Module at a Time
Move files for ONE module, update imports, run tests, commit. Then next module.

### Rule 2: Use git mv
```bash
git mv old_path new_path
```
This preserves git history.

### Rule 3: Create __init__.py Files First
Before moving files, create the folder structure with `__init__.py` files.

### Rule 4: Backward Compatibility Redirects
After moving a file, leave a thin wrapper at the old location:
```python
# OLD: run_positions.py (root level)
"""Backward compatibility wrapper. Remove after migration complete."""
import sys
from modules.positions.run_positions import main

if __name__ == "__main__":
    sys.exit(main())
```

**Note:** Use explicit `main()` calls, not star imports. Star imports can cause unexpected side effects and don't preserve CLI behavior correctly.

### Rule 5: Run Tests After Each Move
```bash
pytest tests/
python -c "from modules.positions import run_positions"
```

### Rule 6: Update Imports Systematically
Use IDE refactoring or careful find-replace:
```bash
# Find all imports of the moved file
grep -r "from run_positions import" .
grep -r "import run_positions" .
```

### Rule 7: Don't Rename Files During Move
Move first (same filename), rename later (if needed). One change at a time.

---

## Part 8: Architectural Decisions (Finalized)

These decisions are **finalized** and should be followed during migration.

### Import Strategy
**Decision:** Flat top-level exports with `__init__.py` re-exports.

```python
# modules/risk/__init__.py
from .run_risk import run_portfolio, run_risk_score
from .portfolio_risk import build_portfolio_view

# Usage anywhere:
from modules.risk import run_portfolio
```

### Dependency Direction
**Rule:** Dependencies flow ONE direction only.

```
orchestrator → modules → contracts
     ↓             ↓          ↑
     └─────────────┴──────────┘
```

- Modules NEVER import from orchestrator
- Orchestrator imports from modules
- Everyone imports from contracts

### Contracts vs API Models
**Decision:** Keep contracts pure.

- `contracts/` = Pure data structures (data_objects, result_objects, enums)
- `orchestrator/api/models/` = FastAPI/Pydantic response models
- Modules only import from `contracts/`, never from `orchestrator/api/models/`

### FMP Namespace
**Decision:** After moving FMP contents, create a stub package at root for backward compatibility.

**Migration steps:**
1. Move `fmp/*.py` contents → `loaders/financial_data/fmp/`
2. Delete the original `fmp/` directory
3. Create NEW stub `fmp/__init__.py` at root:

```python
# fmp/__init__.py (NEW stub package at root)
"""Backward compatibility - re-exports from new location."""
from loaders.financial_data.fmp import *
from loaders.financial_data.fmp import FMPClient, fetch, get_client
```

**Note:** You cannot "keep" the original `fmp/__init__.py` while moving the directory. You must delete and re-create a stub package.

### Stock Analysis
**Decision:** Keep in Risk module. It's "risk analysis for a single stock" - same domain.

### Entry Points
**Decision:** Option B - Wrapper scripts at root for backward compatibility.

Keep thin wrappers at root that import from new locations:
```python
# run_risk.py (at root - KEEP)
"""Backward compatibility wrapper."""
import sys
from modules.risk.run_risk import main

if __name__ == "__main__":
    sys.exit(main())
```

---

## Part 9: Pre-Migration Tasks

Complete these BEFORE moving any files:

- [ ] **Create `shared/paths.py`** - Centralize YAML/config path resolution
- [ ] **Audit dependency violations** - Check for cross-layer imports that violate dependency direction:
  ```bash
  # Modules importing from orchestrator (BAD)
  grep -r "from routes" core/ services/
  grep -r "from app import" core/ services/
  grep -r "import app" core/ services/

  # Core importing from services (check if needed)
  grep -r "from services" core/
  ```
  Fix any violations before moving files.
- [ ] **Create folder structure** - All directories with `__init__.py` files
- [ ] **Set up `__init__.py` exports** - Define public API for each module
- [ ] **Review models/ directory** - Classify each file as pure type vs API model

---

## Summary

This document provides:

1. **Conceptual architecture** - Seven domain modules + four supporting layers
   - Modules: Positions, Risk, Optimizer, Performance, Factors, Scenarios, Trading
   - Layers: Contracts, Loaders, Persistence, Orchestrator
   - Potential future: Stock (if split from Risk)
2. **File mapping** - Which existing files belong to which module/layer
3. **Proposed folder structure** - Target directory layout with explicit file mappings
4. **Interfaces** - Input/output contracts for each module
5. **Data flow** - How modules connect through the orchestrator
6. **Migration safety rules** - How to safely move files without breaking the codebase

**Key design decisions:**
- Classification (SecurityTypeService) → Orchestrator (enriches data before modules)
- Interpretation (AI/GPT helpers) → Orchestrator (presents results after modules)
- Persistence is a layer, not a module (handles portfolio CRUD, DB, caching)
- Modules are pure: receive data, transform, return data (no DB access)

---

## Implementation Status

Track what's been implemented vs pending:

| Component | Status | Notes |
|-----------|--------|-------|
| **Contracts** | 🔲 Pending | Existing files, need to move to `contracts/` |
| **Modules** | | |
| ├─ Positions | 🔲 Pending | Files exist, need to move |
| ├─ Risk | 🔲 Pending | Files exist, need to move |
| ├─ Optimizer | 🔲 Pending | Files exist, need to move |
| ├─ Performance | 🔲 Pending | Files exist, need to move |
| ├─ Factors | 🔲 Pending | Files exist, need to move |
| ├─ Scenarios | 🔲 Pending | Files exist, need to move |
| └─ Trading | 🔲 Pending | Files exist, need to move |
| **Loaders** | | |
| ├─ Plaid | 🔲 Pending | File exists, need to move |
| ├─ SnapTrade | 🔲 Pending | File exists, need to move |
| └─ FMP | ✅ **Implemented** | At `fmp/` root, move to `loaders/financial_data/fmp/` |
| **Persistence** | 🔲 Pending | Files exist, need to move |
| **Orchestrator** | 🔲 Pending | Files exist, need to move |
| **Shared** | 🔲 Pending | Files exist, need to move |

**Legend:** ✅ Implemented | 🔲 Pending | 🚧 In Progress

---

*Document created: 2026-01-31*
*Status: Active*
*Author: Claude (with Henry)*
