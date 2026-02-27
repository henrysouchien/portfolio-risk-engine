# Position Module - MCP & Modular CLI Implementation Spec

> **Status:** ✅ COMPLETE (2026-01-30)
> **Extensions:** See [MCP Extensions Plan](./MCP_EXTENSIONS_PLAN.md) for future enhancements

## Overview

Implementation specification for the Position Module with three consumption modes:
1. **MCP Tool** - AI invokes directly ("what positions do I have?")
2. **CLI Module** - Shell/AI invokes with standard interface, chainable output
3. **FastAPI** - Frontend consumption (existing pattern)

All three modes call the same service layer and use the same Result Object for consistent output.

---

## Current State (as of 2026-01-29)

The Position Module is **~80% implemented**. This section documents what exists and what needs to be added.

### Context from Phase 1 Implementation

Key architectural decisions established in Phase 1 that inform this spec:

| Decision | Details |
|----------|---------|
| **Read-Only Service** | `PositionService` does NOT save to DB. DB persistence is handled by routes (`routes/plaid.py`, `routes/snaptrade.py`) which save unconsolidated positions per-provider. |
| **Consolidation Strategy** | Groups by (ticker, currency) to preserve multi-currency positions as separate rows. |
| **Consolidation Timing** | DB stores unconsolidated data; consolidation happens at analysis time via `PortfolioManager._consolidate_positions()`. |
| **Error Handling** | Fail-fast principle - provider errors raise immediately (no partial results). |
| **Currency Defaults** | Loaders already default currency to "USD" if missing from provider data. |
| **`to_portfolio_data()`** | Exists in `PositionService` for direct-to-risk analysis path (CLI `--to-risk`). |

### ✅ Already Implemented (Updated 2026-01-29)

| Component | File | Status | Notes |
|-----------|------|--------|-------|
| **PositionService** | `services/position_service.py` | ✅ Complete | `get_all_positions()` returns `PositionResult` |
| **PositionResult** | `core/result_objects.py` | ✅ Complete | `to_api_response()`, `to_cli_report()`, `to_portfolio_data()` |
| **PositionsData** | `core/data_objects.py` | ✅ Complete | Underlying data object wrapped by PositionResult |
| **CLI entry point** | `run_positions.py` | ✅ Complete | Has `--source`, `--consolidated`, `--output`, `--to-risk`, `--format` |
| **Column normalization** | `position_service.py` | ✅ Complete | Handles Plaid/SnapTrade differences |
| **Cross-provider consolidation** | `position_service.py` | ✅ Complete | Groups by (ticker, currency) |
| **JSON envelope output** | `PositionResult.to_api_response()` | ✅ Complete | Standard `{module, version, status, metadata, data, chain}` format |

### ❌ Gaps to Fill (Updated 2026-01-29)

| Gap | Current Behavior | Needed for MCP/Modular CLI |
|-----|------------------|---------------------------|
| ~~**PositionResult**~~ | ✅ Implemented in `core/result_objects.py` | Done - has `to_api_response()`, `to_cli_report()`, `to_portfolio_data()` |
| ~~**`--format` flag**~~ | ✅ Implemented in `run_positions.py` | Done - supports `json`/`cli` |
| ~~**JSON envelope**~~ | ✅ `to_api_response()` returns standard envelope | Done |
| ~~**Route simplification**~~ | Future cleanup | Not blocking for MCP |
| **`--input` flag** | Not available | Read from cached JSON (enables CLI chaining) |
| **`get_default_user()`** | Not implemented | Read `RISK_MODULE_USER_EMAIL` env var (set in MCP server config) |
| **`mcp_tools/`** | Doesn't exist | MCP tool wrapper |

### Current Output Format ✅ IMPLEMENTED

The standard envelope format is now implemented via `PositionResult.to_api_response()`:

```python
# run_positions.py now uses:
result = service.get_all_positions(consolidate=consolidated)
print(json.dumps(result.to_api_response(), indent=2))

# Output:
{
    "module": "positions",
    "version": "1.0",
    "timestamp": "2026-01-29T10:30:00Z",
    "status": "success",
    "metadata": {
        "user_email": "henry@example.com",
        "sources": ["plaid", "snaptrade"],
        "position_count": 25,
        "total_value": 156432.50
    },
    "data": {
        "positions": [...],
        "summary": {...}
    },
    "chain": {
        "can_chain_to": ["run_analyze", "run_score"],
        "portfolio_data_compatible": True
    }
}
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CONSUMERS                                      │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  "Hey Claude, what positions do I have?"                                │
│         │                                                                │
│         ▼                                                                │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                  │
│  │  MCP Tool   │    │  CLI Module │    │  FastAPI    │                  │
│  │ (AI invoke) │    │ (shell/AI)  │    │  (frontend) │                  │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘                  │
│         │                  │                  │                          │
│         └──────────────────┼──────────────────┘                          │
│                            │                                             │
│                            ▼                                             │
├─────────────────────────────────────────────────────────────────────────┤
│                       SERVICE LAYER                                      │
│                                                                          │
│  PositionService                                                         │
│    ├── get_all_positions(source, consolidate) → PositionResult          │
│    ├── get_plaid_positions() → PositionResult                           │
│    ├── get_snaptrade_positions() → PositionResult                       │
│    └── to_portfolio_data() → PortfolioData (for chaining)               │
│                                                                          │
├─────────────────────────────────────────────────────────────────────────┤
│                       TWO-LAYER DATA OBJECTS                             │
│                                                                          │
│  PositionsData (core/data_objects.py) - Input/chaining container        │
│    ├── positions: List[Dict]                                            │
│    ├── user_email, sources, consolidated, as_of                         │
│    └── .to_portfolio_data() → PortfolioData (owns conversion logic)     │
│                                                                          │
│  PositionResult (core/result_objects.py) - Transport/serialization      │
│    ├── data: PositionsData  (wraps the data layer)                      │
│    ├── .to_api_response()   → JSON dict (MCP/CLI/API)                   │
│    ├── .to_cli_report()     → Formatted string (human)                  │
│    ├── .to_portfolio_data() → Delegates to data.to_portfolio_data()     │
│    ├── .to_json_file(path)  → Save to cache (AI working memory)         │
│    └── .from_json_file(path)→ Load from cache (class method)            │
│                                                                          │
├─────────────────────────────────────────────────────────────────────────┤
│                       DATA LAYER                                         │
│                                                                          │
│  plaid_loader.py          │  snaptrade_loader.py                        │
│  (existing functions)     │  (existing functions)                       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow: PositionResult → PortfolioData

This diagram shows how `PositionResult` and `PortfolioData` work together:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         DATA OBJECT FLOW                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  Plaid API              SnapTrade API                                   │
│      │                       │                                          │
│      └───────────┬───────────┘                                          │
│                  │                                                       │
│                  ▼                                                       │
│         ┌─────────────────┐                                             │
│         │ PositionService │                                             │
│         │ (orchestration) │                                             │
│         └────────┬────────┘                                             │
│                  │                                                       │
│                  ▼                                                       │
│  ┌───────────────────────────────┐                                      │
│  │        PositionResult         │  ← OUTPUT from fetch                 │
│  │       (data_objects.py)       │    (typed, validated)                │
│  │                               │                                      │
│  │  • positions: List[Dict]      │                                      │
│  │  • user_email, sources        │                                      │
│  │  • total_value, summaries     │                                      │
│  └───────────────┬───────────────┘                                      │
│                  │                                                       │
│        ┌─────────┴─────────┐                                            │
│        │                   │                                             │
│        ▼                   ▼                                             │
│  .to_api_response()   .to_portfolio_data()                              │
│        │                   │                                             │
│        ▼                   ▼                                             │
│  ┌───────────┐    ┌───────────────────────────────┐                     │
│  │   JSON    │    │        PortfolioData          │  ← INPUT to analysis│
│  │ Response  │    │       (data_objects.py)       │    (typed, validated)│
│  │           │    │                               │                      │
│  │ Frontend  │    │  • holdings: Dict[ticker]     │                      │
│  │ MCP Tool  │    │  • start_date, end_date       │                      │
│  │ CLI JSON  │    │  • user_id                    │                      │
│  └───────────┘    └───────────────┬───────────────┘                     │
│                                   │                                      │
│                                   ▼                                      │
│                          ┌─────────────────┐                            │
│                          │  Risk Analysis  │                            │
│                          │  Optimization   │                            │
│                          │  Performance    │                            │
│                          └─────────────────┘                            │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Insight: Replacing Hand-Built Dicts

Currently, `routes/snaptrade.py` and `routes/plaid.py` manually build response dicts:

```python
# CURRENT: Hand-built dict (duplicated in both route files)
holdings_list = []
for _, row in holdings_df.iterrows():
    holdings_list.append({
        "ticker": row.get('ticker', ''),
        "shares": float(row.get('quantity', 0)),
        "market_value": float(row.get('value', 0)),
        ...
    })

return HoldingsResponse(
    success=True,
    holdings={"portfolio_data": {...}, "portfolio_metadata": {...}},
    ...
)
```

With `PositionResult` + Pydantic, routes become simpler:

```python
# FUTURE: Typed data object + Pydantic schema
result = position_service.get_positions_result(consolidate=True)

return HoldingsResponse(
    success=True,
    holdings=result.to_api_response(),  # Data object provides structure
    portfolio_name="CURRENT_PORTFOLIO",
    message="Holdings retrieved"
)
# Pydantic handles field mapping (name→security_name, etc.) and validation
```

### Why Two Data Objects?

| Object | Purpose | Direction |
|--------|---------|-----------|
| `PositionResult` | Raw positions from providers | **Output** from fetch |
| `PortfolioData` | Holdings formatted for analysis | **Input** to analysis |

The `to_portfolio_data()` method bridges them, enabling:
```bash
# CLI chaining
python run_positions.py --user-email x@y.com -o positions.json
python run_analyze.py --input positions.json  # Converts to PortfolioData internally
```

---

## Input Format Strategy: YAML + JSON

The system supports **two input formats** serving different purposes:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         INPUT FORMATS                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  YAML (human-authored)               JSON (machine-generated)           │
│  ┌─────────────────────────┐         ┌─────────────────────────┐        │
│  │ portfolios/             │         │ ~/.risk_module/cache/   │        │
│  │   my_portfolio.yaml     │         │   positions.json        │        │
│  │                         │         │                         │        │
│  │ holdings:               │         │ {                       │        │
│  │   AAPL: {shares: 50}    │         │   "module": "positions",│        │
│  │   MSFT: {shares: 30}    │         │   "data": {...}         │        │
│  │ start_date: 2024-01-01  │         │ }                       │        │
│  └───────────┬─────────────┘         └───────────┬─────────────┘        │
│              │                                   │                       │
│              │    ┌─────────────────────────┐    │                       │
│              └───►│     PortfolioData       │◄───┘                       │
│                   │   (common interface)    │                            │
│                   └───────────┬─────────────┘                            │
│                               │                                          │
│                               ▼                                          │
│                   ┌─────────────────────────┐                            │
│                   │   Service Layer         │                            │
│                   │ (doesn't know/care      │                            │
│                   │  about source format)   │                            │
│                   └─────────────────────────┘                            │
└─────────────────────────────────────────────────────────────────────────┘
```

### Format Comparison

| Aspect | YAML | JSON |
|--------|------|------|
| **Purpose** | Static portfolio definitions | Dynamic output, chaining |
| **Created by** | Human (hand-crafted) | Machine (CLI, API, MCP) |
| **Edited by** | Human (version controlled) | Machine (overwritten) |
| **Location** | `portfolios/*.yaml` | `~/.risk_module/cache/*.json` |
| **Use case** | "Analyze my saved portfolio" | "Chain positions → analysis" |

### CLI Supports Both

```bash
# From YAML (human-authored portfolio)
python run_analyze.py --portfolio portfolios/my_portfolio.yaml --format cli

# From JSON (machine output from previous step)
python run_analyze.py --input ~/.risk_module/cache/positions.json --format cli

# From live fetch (no file, direct from brokerage)
python run_analyze.py --user-email henry@example.com --format json
```

### How Downstream Modules Handle Both

Each CLI module that accepts input should support both formats:

```python
# In run_analyze.py (or any downstream module)

def load_portfolio_data(args) -> PortfolioData:
    """Load portfolio from any supported source."""

    if args.portfolio:
        # YAML path - human-authored portfolio definition
        return PortfolioData.from_yaml(args.portfolio)

    elif args.input:
        # JSON path - machine output from previous module
        # Detect format by checking for module envelope
        data = json.loads(Path(args.input).read_text())

        if 'module' in data:
            # It's a Result Object JSON (e.g., from run_positions.py)
            if data['module'] == 'positions':
                result = PositionResult.from_json_file(args.input)
                return result.to_portfolio_data()
            elif data['module'] == 'analysis':
                # Already analyzed - extract portfolio data
                return PortfolioData.from_dict(data['data']['portfolio'])
        else:
            # Plain holdings JSON
            return PortfolioData.from_dict(data)

    elif args.user_email:
        # Live fetch from brokerages
        service = PositionService(args.user_email)
        result = service.get_all_positions()
        return result.to_portfolio_data()

    else:
        raise ValueError("Must specify --portfolio, --input, or --user-email")
```

### Standard Input Flag Pattern

All CLI modules should support these input flags:

```python
# Standard input arguments for any module
input_group = parser.add_mutually_exclusive_group(required=True)

input_group.add_argument(
    '--portfolio', '-p',
    help='Load from YAML portfolio file (human-authored)'
)
input_group.add_argument(
    '--input', '-i',
    help='Load from JSON file (machine output from previous module)'
)
input_group.add_argument(
    '--user-email',
    help='Fetch live data for this user'
)
```

### Workflow Examples

**Human workflow (YAML):**
```bash
# You maintain portfolio definitions in version control
cat portfolios/retirement.yaml
# holdings:
#   VTI: {shares: 100}
#   BND: {shares: 50}
# start_date: 2020-01-01

# Run analysis on your saved portfolio
python run_analyze.py --portfolio portfolios/retirement.yaml --format cli
```

**AI workflow (JSON chaining):**
```bash
# Step 1: AI fetches current positions
python run_positions.py --user-email henry@example.com \
    -o ~/.risk_module/cache/positions.json

# Step 2: AI analyzes (reads JSON from step 1)
python run_analyze.py --input ~/.risk_module/cache/positions.json \
    -o ~/.risk_module/cache/analysis.json

# Step 3: AI gets risk score (reads JSON from step 2)
python run_score.py --input ~/.risk_module/cache/analysis.json --format cli
```

**Mixed workflow:**
```bash
# Compare your saved portfolio to current brokerage positions
python run_analyze.py --portfolio portfolios/target.yaml -o /tmp/target.json
python run_positions.py --user-email henry@example.com -o /tmp/current.json

# AI can now compare the two JSON outputs
```

### Module Input Compatibility Matrix

| Module | `--portfolio` (YAML) | `--input` (JSON) | `--user-email` (live) | Notes |
|--------|---------------------|------------------|----------------------|-------|
| `run_positions.py` | ❌ | ✅ (reload) | ✅ | Source module - fetches from brokerages |
| `run_analyze.py` | ✅ | ✅ | ✅ | Accepts any portfolio source |
| `run_score.py` | ✅ | ✅ | ✅ | Accepts any portfolio source |
| `run_optimize.py` | ✅ | ✅ | ✅ | Accepts any portfolio source |
| `run_performance.py` | ✅ | ✅ | ✅ | Accepts any portfolio source |
| `run_whatif.py` | ✅ | ✅ | ✅ | Accepts any portfolio source |
| `run_stock.py` | ❌ | ❌ | ❌ | Takes `--ticker` instead |

**Key insight:** `run_positions.py` is a **source module** (produces data), while the others are **consumer modules** (consume data from YAML, JSON, or live fetch).

---

## File Structure

```
risk_module/
├── services/
│   └── position_service.py      # Service layer (returns PositionResult)
│
├── core/
│   ├── data_objects.py          # Add PositionsData class (input container)
│   └── result_objects.py        # Add PositionResult class (transport layer)
│
├── settings.py                  # Add get_default_user() (reads RISK_MODULE_DEFAULT_USER env)
│
├── utils/
│   └── input_loader.py          # Dual-format input loading (YAML + JSON)
│
├── run_positions.py             # CLI module (standard interface)
│
├── mcp_tools/                   # NEW: MCP tool definitions
│   ├── __init__.py
│   └── positions.py             # MCP wrapper for PositionService
│
├── portfolios/                  # Human-authored YAML portfolios
│   └── *.yaml                   # e.g., my_portfolio.yaml
│
└── ~/.risk_module/              # User home directory
    ├── config.yaml              # Default user config
    └── cache/                   # AI working memory (JSON outputs)
        └── *.json               # e.g., positions.json, analysis.json
```

---

## 1. Two-Layer Design: PositionsData + PositionResult

### 1a. PositionsData (Input Container)

Add to `core/data_objects.py` (alongside `PortfolioData`):

```python
@dataclass
class PositionsData:
    """
    Lightweight container for position data (input semantics).

    This is the data layer - holds raw positions and provides
    conversion to PortfolioData for chaining to analysis.
    """

    positions: List[Dict[str, Any]]  # Raw position dicts
    user_email: str
    sources: List[str]  # ["plaid", "snaptrade"]
    consolidated: bool = True
    as_of: datetime = field(default_factory=datetime.now)

    # Cache metadata (populated when cache refactor lands)
    from_cache: bool = False
    cache_age_hours: Optional[float] = None

    def to_portfolio_data(self, start_date: str = None, end_date: str = None) -> 'PortfolioData':
        """Convert to PortfolioData for chaining to risk analysis."""
        # Use shared converter logic (don't duplicate PositionService.to_portfolio_data)
        ...

    def get_cache_key(self) -> str:
        """MD5 hash for caching."""
        ...
```

### 1b. PositionResult (Transport Layer)

Add to `core/result_objects.py`:

```python
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from datetime import datetime
import json
from pathlib import Path

@dataclass
class PositionResult:
    """
    Transport/serialization layer for position data.

    Wraps PositionsData and adds:
    - to_api_response(): JSON for MCP/CLI/API consumption
    - to_cli_report(): Human-readable formatted output
    - Computed summaries (total_value, by_type, etc.)

    Delegates to_portfolio_data() to self.data for chaining.
    """

    # Wrapped data object (contains positions, user_email, sources, etc.)
    data: 'PositionsData'

    # Error handling
    status: str = "success"  # "success" or "error"
    error_message: Optional[str] = None

    # Computed summaries (set in __post_init__)
    total_value: float = 0.0
    position_count: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    by_source: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        """Compute summary statistics from wrapped data."""
        self.position_count = len(self.data.positions)
        self.total_value = sum(p.get('value', 0) or 0 for p in self.data.positions)

        # Count by type
        self.by_type = {}
        for p in self.data.positions:
            t = p.get('type', 'unknown')
            self.by_type[t] = self.by_type.get(t, 0) + 1

        # Count by source
        self.by_source = {}
        for p in self.data.positions:
            s = p.get('source', 'unknown')
            for src in s.split(','):
                src = src.strip()
                self.by_source[src] = self.by_source.get(src, 0) + 1

    def to_api_response(self) -> Dict[str, Any]:
        """
        JSON response for MCP tools, CLI --format json, and API endpoints.

        Uses standard envelope format for AI consumption.
        """
        # Handle error case
        if self.status == "error":
            return {
                "module": "positions",
                "version": "1.0",
                "timestamp": self.data.as_of.isoformat(),
                "status": "error",
                "error": self.error_message,
                "metadata": {
                    "user_email": self.data.user_email,
                    "sources": self.data.sources
                }
            }

        # Success case
        return {
            "module": "positions",
            "version": "1.0",
            "timestamp": self.data.as_of.isoformat(),
            "status": "success",
            "metadata": {
                "user_email": self.data.user_email,
                "sources": self.data.sources,
                "position_count": self.position_count,
                "total_value": round(self.total_value, 2),
                "consolidated": self.data.consolidated,
                "from_cache": self.data.from_cache,
                "cache_age_hours": self.data.cache_age_hours,
                "as_of": self.data.as_of.isoformat()
            },
            "data": {
                "positions": self.data.positions,  # Raw data; Pydantic models handle field mapping
                "summary": {
                    "total_positions": self.position_count,
                    "total_value": round(self.total_value, 2),
                    "by_type": self.by_type,
                    "by_source": self.by_source
                }
            },
            "chain": {
                "can_chain_to": ["run_analyze", "run_score", "run_optimize", "run_performance"],
                "portfolio_data_compatible": True
            }
        }

    def to_portfolio_data(self, start_date: str = None, end_date: str = None) -> 'PortfolioData':
        """Delegate to wrapped PositionsData."""
        return self.data.to_portfolio_data(start_date, end_date)

    def to_cli_report(self) -> str:
        """Human-readable formatted output for terminal display."""
        lines = []
        lines.append("=" * 70)
        lines.append(f"  PORTFOLIO POSITIONS - {self.data.user_email}")
        lines.append(f"  As of: {self.data.as_of.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"  Sources: {', '.join(self.data.sources)}")
        lines.append("=" * 70)
        lines.append("")

        # Group by type
        by_type_positions = {}
        for p in self.data.positions:
            t = p.get('type', 'other')
            if t not in by_type_positions:
                by_type_positions[t] = []
            by_type_positions[t].append(p)

        # Display order
        type_order = ['equity', 'etf', 'mutual_fund', 'bond', 'option', 'cash', 'other']
        type_labels = {
            'equity': 'EQUITIES',
            'etf': 'ETFs',
            'mutual_fund': 'MUTUAL FUNDS',
            'bond': 'BONDS',
            'option': 'OPTIONS',
            'cash': 'CASH',
            'other': 'OTHER'
        }

        for t in type_order:
            if t in by_type_positions:
                positions = by_type_positions[t]
                lines.append(f"{type_labels.get(t, t.upper())} ({len(positions)} positions)")
                lines.append("-" * 70)
                lines.append(f"{'Ticker':<10} {'Quantity':>12} {'Value':>14} {'Source':<20}")
                lines.append("-" * 70)

                for p in sorted(positions, key=lambda x: x.get('value', 0) or 0, reverse=True):
                    ticker = p.get('ticker', 'N/A')[:10]
                    qty = p.get('quantity', 0)
                    value = p.get('value', 0) or 0
                    source = p.get('source', 'unknown')[:20]

                    qty_str = f"{qty:,.2f}" if qty else "N/A"
                    value_str = f"${value:,.2f}" if value else "N/A"

                    lines.append(f"{ticker:<10} {qty_str:>12} {value_str:>14} {source:<20}")

                lines.append("")

        # Summary
        lines.append("=" * 70)
        lines.append("SUMMARY")
        lines.append("-" * 70)
        lines.append(f"Total Positions:  {self.position_count}")
        lines.append(f"Total Value:      ${self.total_value:,.2f}")
        lines.append(f"By Type:          {self.by_type}")
        lines.append(f"By Source:        {self.by_source}")
        lines.append("=" * 70)

        return "\n".join(lines)

    def to_json_file(self, path: str) -> None:
        """Save to JSON file for caching / AI working memory."""
        Path(path).write_text(
            json.dumps(self.to_api_response(), indent=2, default=str)
        )

    @classmethod
    def from_json_file(cls, path: str) -> 'PositionResult':
        """Load from cached JSON file."""
        from core.data_objects import PositionsData

        data = json.loads(Path(path).read_text())

        # Extract from envelope
        metadata = data.get('metadata', {})
        positions = data.get('data', {}).get('positions', [])

        # Create PositionsData first, then wrap in PositionResult
        positions_data = PositionsData(
            positions=positions,
            user_email=metadata.get('user_email', 'unknown'),
            sources=metadata.get('sources', []),
            consolidated=metadata.get('consolidated', True),
            as_of=datetime.fromisoformat(metadata.get('as_of', datetime.now().isoformat())),
            from_cache=metadata.get('from_cache', True),  # Loaded from file = cached
            cache_age_hours=metadata.get('cache_age_hours')
        )

        return cls(data=positions_data)

    def to_summary(self) -> str:
        """One-line summary for quick AI responses."""
        return (
            f"{self.position_count} positions worth ${self.total_value:,.0f} "
            f"({self.by_type.get('equity', 0)} equities, "
            f"{self.by_type.get('etf', 0)} ETFs, "
            f"{self.by_type.get('cash', 0)} cash positions)"
        )
```

---

## 1b. API Schema: Pydantic Models

Field mapping from internal names to frontend-expected names happens at the API layer via Pydantic models.

### Position Model (for individual positions)

```python
# Add to routes/snaptrade.py and routes/plaid.py (or shared models file)

from pydantic import BaseModel, Field
from typing import Optional

class PositionModel(BaseModel):
    """Single position with frontend-friendly field names."""
    ticker: str
    security_name: str = Field(alias='name')        # Maps internal 'name' → 'security_name'
    shares: float = Field(alias='quantity')          # Maps internal 'quantity' → 'shares'
    market_value: float = Field(alias='value')       # Maps internal 'value' → 'market_value'
    currency: str = "USD"
    type: str = "equity"
    source: Optional[str] = None
    account_id: Optional[str] = None
    cost_basis: Optional[float] = None

    class Config:
        populate_by_name = True  # Allow both alias and field name
```

### Updated HoldingsResponse

```python
class HoldingsResponse(BaseModel):
    """Response model for holdings endpoint - uses PositionResult internally."""
    success: bool
    holdings: Optional[Dict[str, Any]] = None  # From PositionResult.to_api_response()
    portfolio_name: Optional[str] = None
    message: Optional[str] = None
```

### Route Usage

```python
# In routes/snaptrade.py or routes/plaid.py

@router.get("/holdings", response_model=HoldingsResponse)
async def get_holdings(request: Request):
    # ... authentication ...

    # Get typed result from service
    result = position_service.get_positions_result(consolidate=True)

    # Pydantic handles field mapping when serializing
    return HoldingsResponse(
        success=True,
        holdings=result.to_api_response(),
        portfolio_name="CURRENT_PORTFOLIO",
        message="Holdings retrieved successfully"
    )
```

### Why Pydantic for Field Mapping?

| Approach | Pros | Cons |
|----------|------|------|
| **Data object maps fields** | Simple | Mixes concerns; data object knows about API |
| **Pydantic models (chosen)** | Clean separation; validation; OpenAPI docs | Extra model layer |

The Pydantic approach:
1. Keeps `PositionResult` focused on data, not presentation
2. Generates accurate OpenAPI/Swagger docs automatically
3. Validates response structure
4. Follows existing pattern in codebase (routes already use Pydantic)

---

## 2. Service Layer: PositionService (Delta Changes)

The existing `services/position_service.py` is well-implemented. Only minor changes needed:

### What's Already There (Keep As-Is)
- `__init__()` with user_email, clients, region ✅
- `fetch_plaid_positions()` ✅
- `fetch_snaptrade_positions()` ✅
- `_normalize_columns()` ✅
- `_consolidate_cross_provider()` ✅
- `to_portfolio_data()` ✅

### Changes Needed

**Option A: Add wrapper method (non-breaking)**

Add a new method that wraps existing `get_all_positions()` and returns `PositionResult`:

```python
# Add to services/position_service.py

from core.data_objects import PositionResult

class PositionService:
    # ... existing methods unchanged ...

    def get_positions_result(
        self,
        source: str = "all",
        consolidate: bool = True
    ) -> PositionResult:
        """
        Get positions wrapped in a PositionResult for MCP/CLI consumption.

        This is the preferred method for AI/MCP tools. Use get_all_positions()
        for internal DataFrame operations.

        NOTE: This method handles the source parameter routing that get_all_positions()
        doesn't support. The existing methods are:
        - fetch_plaid_positions() - Plaid only
        - fetch_snaptrade_positions() - SnapTrade only
        - get_all_positions() - Both providers (no source param)
        """
        # Track which sources we're fetching from
        sources_used = []

        try:
            if source == "plaid":
                df = self.fetch_plaid_positions(consolidate=consolidate)
                sources_used = ["plaid"] if not df.empty else []
            elif source == "snaptrade":
                df = self.fetch_snaptrade_positions(consolidate=consolidate)
                sources_used = ["snaptrade"] if not df.empty else []
            else:
                df = self.get_all_positions(consolidate=consolidate)
                # Infer sources from position_source column
                if not df.empty and 'position_source' in df.columns:
                    sources_used = list(df['position_source'].unique())
        except Exception as e:
            # Return error result instead of raising
            return PositionResult(
                positions=[],
                user_email=self.config.user_email,
                sources=[source] if source != "all" else ["plaid", "snaptrade"],
                consolidated=consolidate,
                status="error",
                error_message=str(e)
            )

        # Rename column for consistency with PositionResult
        if 'position_source' in df.columns:
            df = df.rename(columns={'position_source': 'source'})

        return PositionResult(
            positions=df.to_dict('records') if not df.empty else [],
            user_email=self.config.user_email,
            sources=sources_used,
            consolidated=consolidate
        )
```

**Option B: Modify existing method (breaking change)**

Change `get_all_positions()` to return `PositionResult` instead of DataFrame. This requires updating all callers.

**Recommendation:** Use Option A for backward compatibility. Existing code using `get_all_positions()` continues to work.

---

## 3. CLI Module: run_positions.py (Delta Changes)

The existing `run_positions.py` is functional. Here are the specific changes needed:

### Current Flags (Keep)
- `--user-email` ✅
- `--source` ✅
- `--consolidated` / `--detail` ✅
- `--output` ✅
- `--to-risk` ✅

### New Flags to Add

```python
# Add to _parse_args():

# NEW: Input from cached JSON (for chaining)
parser.add_argument(
    '--input', '-i',
    help='Read positions from JSON file (cached/chained input)'
)

# NEW: Output format selection
parser.add_argument(
    '--format', '-f',
    choices=['json', 'cli', 'summary'],
    default='cli',  # Keep CLI as default for backward compat
    help='Output format: json (machine), cli (human), summary (one-line)'
)
```

### Updated run_positions() Function

```python
def run_positions(
    *,
    user_email: str = None,      # Now optional (can use --input instead)
    input_path: str = None,      # NEW: Load from cached JSON
    source: str = "all",
    consolidated: bool = False,
    detail: bool = False,
    output_path: Optional[str] = None,
    output_format: str = "cli",  # NEW: json/cli/summary
    to_risk: bool = False,
    return_data: bool = False,
) -> Optional[dict]:
    """Updated to support PositionResult and chaining."""

    # Import PositionResult
    from core.data_objects import PositionResult

    service = PositionService(user_email=user_email) if user_email else None

    # --- Load from input file OR fetch fresh ---
    if input_path:
        # Load from cached JSON (enables chaining)
        result = PositionResult.from_json_file(input_path)
        df = pd.DataFrame(result.positions)
    else:
        if not user_email:
            # Try default user from config
            from settings import get_default_user
            user_email = get_default_user()
            if not user_email:
                raise ValueError("Must specify --user-email or --input")
            service = PositionService(user_email=user_email)

        if detail:
            consolidated = False

        if source == "plaid":
            df = service.fetch_plaid_positions(consolidate=consolidated)
        elif source == "snaptrade":
            df = service.fetch_snaptrade_positions(consolidate=consolidated)
        else:
            df = service.get_all_positions(consolidate=consolidated)

        # Wrap in PositionResult
        sources = list(df['position_source'].unique()) if 'position_source' in df.columns else [source]
        result = PositionResult(
            positions=df.to_dict('records'),
            user_email=user_email,
            sources=sources,
            consolidated=consolidated
        )

    # --- Handle output ---
    if output_path:
        # Use PositionResult.to_json_file() for standard envelope
        result.to_json_file(output_path)
        portfolio_logger.info(f"✅ Wrote positions to {output_path}")

    if to_risk:
        # Existing --to-risk behavior unchanged
        portfolio_data = service.to_portfolio_data(df)
        # ... rest of to_risk logic ...

    if return_data:
        return {"positions": df, "result": result}

    # --- Format output based on --format flag ---
    if output_format == 'json':
        print(json.dumps(result.to_api_response(), indent=2, default=str))
    elif output_format == 'summary':
        print(result.to_summary())
    else:  # 'cli' (default)
        print(_format_positions_table(df))

    return None
```

### Backward Compatibility

| Old Command | Still Works? |
|-------------|--------------|
| `python run_positions.py --user-email x@y.com` | ✅ Yes (outputs table) |
| `python run_positions.py --user-email x@y.com --output pos.json` | ✅ Yes (now with envelope) |
| `python run_positions.py --user-email x@y.com --to-risk` | ✅ Yes |
| `python run_positions.py --user-email x@y.com --source plaid` | ✅ Yes |

### New Commands Enabled

```bash
# Output JSON with standard envelope
python run_positions.py --user-email x@y.com --format json

# Load from cached positions (chaining)
python run_positions.py --input /tmp/positions.json --format cli

# One-line summary
python run_positions.py --user-email x@y.com --format summary
```

---

## 4. MCP Tool: mcp_tools/positions.py

```python
"""
MCP Tool: get_positions

Exposes PositionService as an MCP tool for AI invocation.

Usage (from Claude):
    "What positions do I have?"
    "Show me my Plaid positions"
    "Get my portfolio holdings"
"""

import os
from typing import Optional, Literal
from services.position_service import PositionService


def get_positions(
    user_email: Optional[str] = None,
    source: Literal["all", "plaid", "snaptrade"] = "all",
    consolidate: bool = True,
    format: Literal["full", "summary", "list"] = "full"
) -> dict:
    """
    Get current portfolio positions from brokerage accounts.

    Fetches positions from Plaid and/or SnapTrade, consolidates same tickers,
    and returns structured data suitable for analysis or display.

    Args:
        user_email: User to fetch positions for. If not provided, uses default user.
        source: Which brokerage(s) to fetch from: "all", "plaid", or "snaptrade"
        consolidate: Whether to merge same tickers across providers (default: True)
        format: Output format:
            - "full": Complete position data with all fields
            - "summary": High-level summary stats only
            - "list": Simple list of tickers and values

    Returns:
        dict: Position data with metadata, suitable for chaining to other tools

    Examples:
        # Get all positions
        get_positions()

        # Get just Plaid positions
        get_positions(source="plaid")

        # Quick summary
        get_positions(format="summary")
    """
    # Resolve user from arg or MCP server config (env var)
    user = user_email or os.environ.get('RISK_MODULE_USER_EMAIL')
    if not user:
        return {
            "status": "error",
            "error": "No user specified and no default user configured"
        }

    # Fetch positions using the new wrapper method
    # NOTE: get_all_positions() doesn't take a source param - use get_positions_result() instead
    service = PositionService(user)
    result = service.get_positions_result(source=source, consolidate=consolidate)

    # Format response based on requested format
    if format == "summary":
        return {
            "status": "success",
            "summary": result.to_summary(),
            "total_value": result.total_value,
            "position_count": result.position_count,
            "by_type": result.by_type
        }

    elif format == "list":
        return {
            "status": "success",
            "positions": [
                {"ticker": p["ticker"], "value": p.get("value", 0)}
                for p in result.positions
            ],
            "total_value": result.total_value
        }

    else:  # full
        return result.to_api_response()


# MCP Tool registration metadata
TOOL_METADATA = {
    "name": "get_positions",
    "description": "Get current portfolio positions from brokerage accounts (Plaid, SnapTrade)",
    "parameters": {
        "type": "object",
        "properties": {
            "user_email": {
                "type": "string",
                "description": "User email (optional, uses default if not provided)"
            },
            "source": {
                "type": "string",
                "enum": ["all", "plaid", "snaptrade"],
                "default": "all",
                "description": "Which brokerage source(s) to fetch from"
            },
            "consolidate": {
                "type": "boolean",
                "default": True,
                "description": "Whether to merge same tickers across providers"
            },
            "format": {
                "type": "string",
                "enum": ["full", "summary", "list"],
                "default": "full",
                "description": "Output format: full data, summary stats, or simple list"
            }
        }
    }
}
```

### MCP Server Setup for Claude Code

This MCP server is designed for **Claude Code** (the CLI tool), not Claude Desktop.

#### Step 1: Create MCP Server

Create `mcp_server.py` in project root using FastMCP:

```python
# mcp_server.py
import os
from fastmcp import FastMCP
from services.position_service import PositionService

mcp = FastMCP("Risk Module")

@mcp.tool()
def get_positions(
    source: str = "all",
    consolidate: bool = True,
    format: str = "full"
) -> dict:
    """
    Get current portfolio positions from brokerage accounts.

    Args:
        source: Which brokerage(s) to fetch from: "all", "plaid", or "snaptrade"
        consolidate: Whether to merge same tickers across providers
        format: Output format: "full", "summary", or "list"
    """
    user_email = os.environ.get('RISK_MODULE_USER_EMAIL')
    if not user_email:
        return {"status": "error", "error": "RISK_MODULE_USER_EMAIL not configured"}

    service = PositionService(user_email)
    result = service.get_all_positions(consolidate=consolidate)

    if format == "summary":
        return {
            "status": "success",
            "summary": f"{result.position_count} positions worth ${result.total_value:,.2f}",
            "by_type": result.by_type
        }
    elif format == "list":
        return {
            "status": "success",
            "positions": [{"ticker": p["ticker"], "value": p.get("value")} for p in result.data.positions]
        }
    else:
        return result.to_api_response()

if __name__ == "__main__":
    mcp.run()
```

#### Step 2: Register with Claude Code

```bash
cd /Users/henrychien/Documents/Jupyter/risk_module

# Add the MCP server
claude mcp add --transport stdio risk-module \
  --env RISK_MODULE_USER_EMAIL=henry@example.com \
  -- python mcp_server.py
```

This creates `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "risk-module": {
      "type": "stdio",
      "command": "python",
      "args": ["mcp_server.py"],
      "env": {
        "RISK_MODULE_USER_EMAIL": "henry@example.com"
      }
    }
  }
}
```

#### Step 3: Verify

```bash
# List configured servers
claude mcp list

# Or inside Claude Code
/mcp
```

#### Managing the Server

```bash
# Update environment variable
claude mcp remove risk-module
claude mcp add --transport stdio risk-module \
  --env RISK_MODULE_USER_EMAIL=new@email.com \
  -- python mcp_server.py

# Check server details
claude mcp get risk-module
```

---

## 5. User Configuration (Simplified)

For Claude Code, user configuration is handled via the MCP server config (`.mcp.json`), not a separate config file.

The user email is passed as an environment variable when registering the server:

```bash
claude mcp add --transport stdio risk-module \
  --env RISK_MODULE_USER_EMAIL=henry@example.com \
  -- python mcp_server.py
```

The MCP tool reads it at runtime:

```python
user_email = os.environ.get('RISK_MODULE_USER_EMAIL')
```

This is simpler than config files because:
1. User is set once in `.mcp.json`, not in multiple places
2. No file I/O or YAML parsing needed
3. Follows Claude Code MCP convention

---

## 6. Input Loader Utility: utils/input_loader.py

Shared utility for loading portfolio data from any supported source:

```python
"""
Input loader utility for CLI modules.

Handles loading portfolio data from:
- YAML files (human-authored portfolio definitions)
- JSON files (machine-generated output from other modules)
- Live fetch (from brokerages via PositionService)
"""

import json
from pathlib import Path
from typing import Optional, Union
import argparse

import yaml

from core.data_objects import PortfolioData, PositionResult
from services.position_service import PositionService
from settings import get_default_user


def add_input_arguments(parser: argparse.ArgumentParser, required: bool = True):
    """
    Add standard input arguments to an argument parser.

    Usage:
        parser = argparse.ArgumentParser()
        add_input_arguments(parser)
        args = parser.parse_args()
        portfolio_data = load_portfolio_data(args)
    """
    input_group = parser.add_mutually_exclusive_group(required=required)

    input_group.add_argument(
        '--portfolio', '-p',
        help='Load from YAML portfolio file (human-authored, e.g., portfolios/my_portfolio.yaml)'
    )
    input_group.add_argument(
        '--input', '-i',
        help='Load from JSON file (machine output from previous module)'
    )
    input_group.add_argument(
        '--user-email',
        help='Fetch live positions from brokerages for this user'
    )

    # Optional date overrides (for analysis modules)
    parser.add_argument(
        '--start-date',
        help='Override start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        help='Override end date (YYYY-MM-DD)'
    )


def load_portfolio_data(
    args: argparse.Namespace,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> PortfolioData:
    """
    Load portfolio data from the source specified in args.

    Supports:
    - YAML files (--portfolio): Human-authored portfolio definitions
    - JSON files (--input): Machine output from run_positions.py or other modules
    - Live fetch (--user-email): Fetches from Plaid/SnapTrade

    Args:
        args: Parsed command-line arguments with portfolio/input/user-email
        start_date: Override start date (or uses args.start_date or default)
        end_date: Override end date (or uses args.end_date or default)

    Returns:
        PortfolioData ready for use with services
    """
    # Resolve dates
    start = start_date or getattr(args, 'start_date', None)
    end = end_date or getattr(args, 'end_date', None)

    if hasattr(args, 'portfolio') and args.portfolio:
        return _load_from_yaml(args.portfolio, start, end)

    elif hasattr(args, 'input') and args.input:
        return _load_from_json(args.input, start, end)

    elif hasattr(args, 'user_email') and args.user_email:
        return _load_from_live(args.user_email, start, end)

    else:
        # Try default user
        default_user = get_default_user()
        if default_user:
            return _load_from_live(default_user, start, end)

        raise ValueError(
            "Must specify --portfolio (YAML), --input (JSON), or --user-email, "
            "or configure a default user"
        )


def _load_from_yaml(path: str, start_date: str = None, end_date: str = None) -> PortfolioData:
    """Load from human-authored YAML portfolio file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Portfolio file not found: {path}")

    data = yaml.safe_load(path.read_text())

    # YAML can specify dates, but args can override
    if start_date:
        data['start_date'] = start_date
    if end_date:
        data['end_date'] = end_date

    return PortfolioData.from_dict(data)


def _load_from_json(path: str, start_date: str = None, end_date: str = None) -> PortfolioData:
    """Load from machine-generated JSON file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    data = json.loads(path.read_text())

    # Check if it's a module envelope (from run_positions.py, etc.)
    if 'module' in data:
        module = data['module']

        if module == 'positions':
            # Load as PositionResult, convert to PortfolioData
            result = PositionResult.from_json_file(str(path))
            return result.to_portfolio_data(start_date, end_date)

        elif module == 'analysis':
            # Extract portfolio data from analysis result
            portfolio_dict = data.get('data', {}).get('portfolio_input', {})
            return PortfolioData.from_dict(portfolio_dict)

        else:
            # Unknown module - try to extract data
            inner_data = data.get('data', data)
            return PortfolioData.from_dict(inner_data)

    else:
        # Plain JSON (not an envelope) - assume it's portfolio format
        if start_date:
            data['start_date'] = start_date
        if end_date:
            data['end_date'] = end_date
        return PortfolioData.from_dict(data)


def _load_from_live(user_email: str, start_date: str = None, end_date: str = None) -> PortfolioData:
    """Fetch live positions from brokerages."""
    service = PositionService(user_email)
    result = service.get_positions_result(consolidate=True)  # Returns PositionResult (not DataFrame)
    return result.to_portfolio_data(start_date, end_date)
```

### Usage in Downstream Modules

```python
# run_analyze.py (or any downstream module)

from utils.input_loader import add_input_arguments, load_portfolio_data

def main():
    parser = argparse.ArgumentParser(description='Analyze portfolio risk')

    # Add standard input arguments (--portfolio, --input, --user-email)
    add_input_arguments(parser)

    # Add module-specific arguments
    parser.add_argument('--output', '-o', help='Output file')
    parser.add_argument('--format', '-f', choices=['json', 'cli'], default='json')

    args = parser.parse_args()

    # Load portfolio from whatever source was specified
    portfolio_data = load_portfolio_data(args)

    # Now use portfolio_data with services
    service = PortfolioService()
    result = service.analyze(portfolio_data)

    # Output...
```

---

Example config file `~/.risk_module/config.yaml`:

```yaml
# Risk Module Configuration

# Default user for MCP tools and CLI (when --user-email not specified)
default_user: henry@example.com

# AWS region for secrets manager
aws_region: us-east-1

# Cache settings
cache:
  directory: ~/.risk_module/cache
  ttl_minutes: 60
```

---

## 7. Chaining Example

How AI chains position data to risk analysis:

```bash
# Step 1: AI fetches positions and saves to cache
python run_positions.py --user-email henry@example.com \
    --format json \
    --output ~/.risk_module/cache/positions.json

# Step 2: AI runs risk analysis using cached positions
python run_analyze.py --input ~/.risk_module/cache/positions.json \
    --format json \
    --output ~/.risk_module/cache/analysis.json

# Step 3: AI calculates risk score from analysis
python run_score.py --input ~/.risk_module/cache/analysis.json \
    --format cli
```

Or in a single MCP conversation:

```
User: "What's my portfolio risk?"

Claude: [calls get_positions(format="full")]
        [saves result to working memory]
        [calls run_risk_analysis(input=positions)]
        [calls get_risk_score(input=analysis)]

Claude: "Your portfolio has 25 positions worth $156k with a risk score
        of 72/100 (Moderate-High). The main risk factors are:
        - 45% concentration in tech sector
        - High correlation to market (beta 1.3)
        - Limited fixed income allocation (5%)

        Want me to suggest some optimizations?"
```

---

## 8. Testing Commands

Add to `tests/TESTING_COMMANDS.md`:

```markdown
## Position Module Testing

### CLI - Fetch Fresh
# All sources, JSON output
python run_positions.py --user-email test@example.com --format json

# Plaid only, human-readable
python run_positions.py --user-email test@example.com --source plaid --format cli

# Save to cache
python run_positions.py --user-email test@example.com -o /tmp/positions.json

### CLI - Load from Cache
# Load and display
python run_positions.py --input /tmp/positions.json --format cli

# One-line summary
python run_positions.py --input /tmp/positions.json --format summary

### CLI - Chaining
# Positions → Risk Analysis
python run_positions.py --user-email test@example.com -o /tmp/pos.json
python run_analyze.py --input /tmp/pos.json --format cli

### MCP Tool Testing
# Direct Python invocation
python -c "
from mcp_tools.positions import get_positions
result = get_positions(format='summary')
print(result)
"
```

---

## 9. Implementation Checklist (Updated 2026-01-29)

Legend: ✅ = Done | ➕ = Needs implementation

### Phase 1: Data Objects ✅ COMPLETE
- ✅ `PositionsData` in `core/data_objects.py` - `from_dataframe()`, `to_portfolio_data()`
- ✅ `PositionResult` in `core/result_objects.py` - wraps PositionsData
- ✅ `to_api_response()` with standard envelope
- ✅ `to_cli_report()` for human-readable output
- ✅ `from_dataframe()` and `from_error()` factory methods

### Phase 2: Service Layer ✅ COMPLETE
- ✅ `PositionService.get_all_positions()` - returns `PositionResult` (not DataFrame)
- ✅ `fetch_plaid_positions()` / `fetch_snaptrade_positions()`
- ✅ `_normalize_columns()` / `_consolidate_cross_provider()`

### Phase 3: CLI Module ✅ COMPLETE
- ✅ `--user-email`, `--source`, `--consolidated`, `--detail` flags
- ✅ `--output` flag - uses `result.to_api_response()` for JSON envelope
- ✅ `--format` flag - `json`/`cli` output modes
- ✅ `--to-risk` flag - converts to PortfolioData and runs risk analysis
- ➕ `--input` flag for loading cached JSON (optional for CLI chaining)

### Phase 4: MCP Implementation ✅ COMPLETE
- ✅ Created `mcp_server.py` with FastMCP and `get_positions()` tool
- ✅ Reads `RISK_MODULE_USER_EMAIL` from env (set via `claude mcp add --env`)
- ✅ Created `mcp_tools/positions.py` wrapper with format options
- ✅ Created `mcp_tools/README.md` with guidelines for adding new tools
- ✅ Registered as `portfolio-mcp` with Claude Code

**Future enhancement (after Position Service Refactor):**
Add cache control parameters to MCP tool:
```python
def get_positions(
    source: str = "all",
    consolidate: bool = True,
    format: str = "full",
    use_cache: bool = True,      # After refactor
    force_refresh: bool = False  # After refactor
) -> dict:
```

### Phase 5: Input Loader (Future - for downstream modules)
- ➕ Create `utils/input_loader.py` with `load_portfolio_data()`
- ➕ Update downstream modules to support `--input` flag
- ➕ Add JSON envelope detection (check for `module` field)

---

## Effort Estimate (Updated 2026-01-30)

| Phase | Status | Remaining Work |
|-------|--------|----------------|
| Phase 1: Data Objects | ✅ Done | - |
| Phase 2: Service Layer | ✅ Done | - |
| Phase 3: CLI Module | ✅ Done | ~20 lines for `--input` flag (optional) |
| Phase 4: MCP Tool | ✅ Done | - |
| Phase 5: Input Loader | ➕ Future | ~80 lines |

**MCP Implementation Complete.** Next step is Position Service Refactor (cache integration).

---

## Related Documents

- [MCP Extensions Plan](../MCP_EXTENSIONS_PLAN.md) - Future enhancements (new tools, cache params)
- [Position Module Plan](./POSITION_MODULE_PLAN.md) - Original design and Phase 1 implementation
- [Position Service Refactor Plan](../POSITION_SERVICE_REFACTOR_PLAN.md) - Phase 2: Move cache logic into PositionService
- [Modular CLI Architecture](../MODULAR_CLI_ARCHITECTURE_PLAN.md) - CLI pattern reference
- [Trade Tracking Plan](../TRADE_TRACKING_PLAN.md) - Future transaction support
- [Testing Commands](../../../tests/TESTING_COMMANDS.md) - CLI testing reference
- [MCP Tools README](../../../mcp_tools/README.md) - Adding new MCP tools

---

*Document created: 2026-01-29*
*Completed: 2026-01-30*
*Status: ✅ COMPLETE - Core MCP implementation done*
