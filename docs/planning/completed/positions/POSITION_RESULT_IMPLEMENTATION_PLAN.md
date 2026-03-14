# PositionResult Implementation Plan

## Overview

Implement a two-layer design for position data:
1. **`PositionsData`** (data_objects.py) - Lightweight input container with chaining support
2. **`PositionResult`** (result_objects.py) - Transport/serialization layer for API/CLI/MCP

This separation keeps concerns clean: data layer handles data + chaining, result layer handles transport + formatting.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         TWO-LAYER DESIGN                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  data_objects.py                     result_objects.py                  │
│  ┌─────────────────────┐            ┌─────────────────────┐            │
│  │   PositionsData     │            │   PositionResult    │            │
│  │   (input semantics) │◄───────────│   (transport layer) │            │
│  │                     │  wraps     │                     │            │
│  │ • positions: List   │            │ • data: PositionsData│           │
│  │ • user_email        │            │ • to_api_response() │            │
│  │ • sources           │            │ • to_cli_report()   │            │
│  │ • to_portfolio_data()│           │ • to_summary()      │            │
│  └─────────────────────┘            └─────────────────────┘            │
│           │                                                             │
│           ▼                                                             │
│  ┌─────────────────────┐                                               │
│  │   PortfolioData     │  ← for chaining to risk analysis              │
│  └─────────────────────┘                                               │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

```
PositionService                    PositionResult                     Consumers
┌──────────────────┐              ┌──────────────────┐              ┌──────────────┐
│ get_all_positions│─────────────▶│ data: PositionsData│────────────▶│ Routes       │
│ ()               │              │                    │             │ CLI          │
│                  │              │ to_api_response() │             │ MCP          │
│ Returns          │              │ to_cli_report()   │             │              │
│ PositionResult   │              │ to_summary()      │             │              │
│ directly         │              │                    │             │              │
│                  │              │ data.to_portfolio_│             │              │
│                  │              │ data() for chain  │             │              │
└──────────────────┘              └──────────────────┘              └──────────────┘
```

---

## Phase 1a: PositionsData (Data Layer)

**File:** `core/data_objects.py`

Lightweight input container - holds raw positions with minimal metadata.

### Fields

```python
@dataclass
class PositionsData:
    """
    Lightweight container for position data.

    This is the "input" side - holds raw positions and provides
    conversion to PortfolioData for chaining to analysis.
    """

    # Core data (internal field names from PositionService)
    positions: List[Dict[str, Any]]

    # Metadata
    user_email: str
    sources: List[str]  # ["plaid", "snaptrade"]
    consolidated: bool = True
    as_of: datetime = field(default_factory=datetime.now)

    # Cache metadata (for when cache refactor lands)
    from_cache: bool = False
    cache_age_hours: Optional[float] = None

    # Caching
    _cache_key: Optional[str] = None
```

### Methods

| Method | Purpose |
|--------|---------|
| `__post_init__()` | Validate positions, generate cache key |
| `from_dataframe(df, user_email, sources=None)` | Class method to create from DataFrame. If `sources` is None, auto-derives from `position_source` column. |
| `to_portfolio_data(start_date=None, end_date=None, portfolio_name="CURRENT_PORTFOLIO")` | Convert to PortfolioData for chaining (uses PORTFOLIO_DEFAULTS when None) |
| `get_cache_key()` | MD5 hash for caching |
| `get_tickers()` | List of unique tickers |
| `get_total_value()` | Sum of position values |

### Converter Location

**Decision:** The `to_portfolio_data()` conversion logic lives on `PositionsData`.

- `PositionsData.to_portfolio_data()` - owns the conversion logic (migrated from `PositionService`)
- `PositionService.to_portfolio_data()` - delegates to `PositionsData.to_portfolio_data()` for backwards compatibility
- `PositionResult.to_portfolio_data()` - delegates to `self.data.to_portfolio_data()`

This follows the pattern where data objects own their transformations (like `PortfolioData.from_holdings()`).

### Position Dict Schema (internal)

```python
{
    "ticker": str,           # "AAPL" or "CUR:USD"
    "name": str,             # "Apple Inc."
    "quantity": float,       # 100.5
    "value": float,          # 15000.75
    "currency": str,         # "USD"
    "type": str,             # "equity", "cash", etc.
    "position_source": str,  # "plaid", "snaptrade" (column name from PositionService)
    "account_id": str,       # Optional
    "cost_basis": float,     # Optional
}
```

**Note:** The service uses `position_source` as the column name (not `source`). The `by_source` summary in PositionResult computes from this field.

### Data Contract (PositionsData)

**Required fields (every position dict):**
- `ticker` (str, non-empty)
- `quantity` (number, finite)
- `value` (number, finite)
- `type` (str, non-empty)
- `position_source` (str, non-empty; may be comma-delimited after consolidation)
- `currency` (str, non-empty)

**Validation rules (fail-fast):**
- Missing/None/empty required fields raise immediately.
- `quantity` and `value` must be numeric and finite (no NaN/inf).
- `position_source` must be a non-empty string; for consolidated rows it may be a comma-delimited list.
- Mixed currencies for the same ticker are rejected in `PositionsData.to_portfolio_data()`.

**Optional fields (pass-through for display/transport):**
- `name`, `price`, `cost_basis`, `account_id`, `account_name`, `brokerage_name`

---

## Phase 1b: PositionResult (Transport Layer)

**File:** `core/result_objects.py`

Wraps PositionsData and adds serialization/formatting for API/CLI/MCP.

### Fields

```python
@dataclass
class PositionResult:
    """
    Transport/serialization layer for position data.

    Wraps PositionsData and adds:
    - to_api_response() for API/MCP envelope
    - to_cli_report() for terminal display
    - to_summary() for quick responses
    - Computed summaries (total_value, by_type, etc.)
    """

    # Wrapped data object
    data: PositionsData

    # Error handling
    status: str = "success"  # "success" or "error"
    error_message: Optional[str] = None

    # Computed summaries (set in __post_init__)
    total_value: float = 0.0
    position_count: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    by_source: Dict[str, int] = field(default_factory=dict)
```

### Methods

| Method | Purpose |
|--------|---------|
| `__post_init__()` | Compute summaries from data.positions |
| `from_dataframe(df, user_email, sources=None)` | Class method - creates PositionsData internally. If `sources` is None, auto-derives from `position_source` column. |
| `from_error(error_msg, user_email)` | Class method for error cases (used by API/MCP boundary, not service layer) |
| `to_api_response()` | JSON dict with standard envelope |
| `to_cli_report()` | Formatted string for terminal |
| `to_summary()` | One-line summary |
| `to_portfolio_data(...)` | Delegates to `self.data.to_portfolio_data()` |

---

## Phase 2: PositionService Integration

**File:** `services/position_service.py`

### Change Return Type

Change `get_all_positions()` to return `PositionResult` directly (no wrapper method):

```python
def get_all_positions(
    self,
    consolidate: bool = False
) -> PositionResult:
    """
    Get positions from all providers.

    Returns PositionResult which wraps PositionsData.
    Use result.data.to_portfolio_data() for chaining to analysis.
    """
```

**Note:** Source selection (plaid/snaptrade/all) is handled at the CLI level by calling the appropriate service method (`fetch_plaid_positions()`, `fetch_snaptrade_positions()`, or `get_all_positions()`). The service methods don't have a `source` parameter.

### Implementation

1. Fetch from providers (existing logic)
2. Normalize and consolidate (existing logic)
3. Wrap in `PositionResult.from_dataframe(df, user_email)` - sources auto-derived from `position_source` column
4. Return PositionResult

### Backwards Compatibility

Update `PositionService.to_portfolio_data()` to delegate:

```python
def to_portfolio_data(self, df: Optional[pd.DataFrame] = None, ...) -> PortfolioData:
    """Backwards-compatible method - delegates to PositionsData."""
    if df is None:
        result = self.get_all_positions()  # Returns PositionResult now
        return result.data.to_portfolio_data(start_date, end_date, portfolio_name)

    # For direct DataFrame input, wrap in PositionsData first
    positions_data = PositionsData.from_dataframe(df, self.config.user_email, ["unknown"])
    return positions_data.to_portfolio_data(start_date, end_date, portfolio_name)
```

### Error Policy Decision

**Option A: Keep fail-fast (recommended for now)**
- Service layer raises exceptions on provider errors
- API routes and MCP tools catch exceptions and use `PositionResult.from_error()` to return structured error responses
- Matches existing behavior

**Option B: Return error result from service**
- Service returns `PositionResult.from_error(msg, user_email)` instead of raising
- More control but changes existing contract

**Recommendation:** Keep fail-fast for Phase 2. The `from_error()` method exists for API/MCP boundary use only - the service layer continues to raise exceptions.

---

## Phase 2b: Cache Refactor (Dependency)

**Note:** The cache refactor (moving 24-hour cache from routes into PositionService) should ideally happen before or alongside Phase 2. Otherwise PositionResult is built on the no-cache pipeline.

**Options:**
- **A) Cache first:** Refactor cache into PositionService, then add PositionResult
- **B) PositionResult first:** Add PositionResult now, cache refactor later (result will gain cache metadata)
- **C) Together:** Do both in same phase

**Current recommendation:** Option B - add PositionResult first, then cache refactor adds `from_cache` and `cache_age_hours` to PositionsData.

---

## Phase 3: Route Refactor (Future)

**Files:** `routes/plaid.py`, `routes/snaptrade.py`

After Phase 1 & 2:
- Replace hand-built dicts with `result.to_api_response()`
- Move 24-hour cache logic into PositionService
- Routes become thin auth + delegation layer

---

## Phase 4: Pydantic Models (Future)

**Files:** `routes/plaid.py`, `routes/snaptrade.py` (or shared models file)

- Add `PositionModel` with field aliases for frontend mapping
- Update `HoldingsResponse` to validate structure

---

## Implementation Checklist

### Phase 1a: PositionsData (data_objects.py)
- [x] Add `PositionsData` class to `core/data_objects.py`
- [x] Implement `__post_init__()` with validation
- [x] Implement `from_dataframe(df, user_email, sources=None)` class method (auto-derive `sources` from `position_source` when None)
- [x] Implement `to_portfolio_data(start_date, end_date, portfolio_name)` - owns conversion logic (defaults to `settings.PORTFOLIO_DEFAULTS` when args are None)
- [x] Implement `get_cache_key()`
- [x] Add cache metadata fields (`from_cache`, `cache_age_hours`)
- [x] Add unit tests

### Phase 1b: PositionResult (result_objects.py)
- [x] Add `PositionResult` class to `core/result_objects.py`
- [x] Implement `__post_init__()` with summary computation
- [x] Implement `from_dataframe()` class method (creates PositionsData internally)
- [x] Implement `from_error()` class method for error cases
- [x] Implement `to_api_response()` with standard envelope
- [x] Implement `to_cli_report()` for terminal output
- [x] Implement `to_summary()` one-liner
- [x] Delegate `to_portfolio_data()` to `self.data.to_portfolio_data()`
- [x] Add unit tests

### Phase 2: PositionService Integration
- [x] Import PositionResult in position_service.py
- [x] Change `get_all_positions()` return type to PositionResult
- [x] Update internal logic to wrap DataFrame in PositionResult
- [x] Update `to_portfolio_data()` to delegate to `PositionsData.to_portfolio_data()`
- [x] Update callers (inventory below)
- [x] Run `rg get_all_positions` and update any remaining call sites that expect a DataFrame
- [x] Add integration tests (`tests/unit/test_position_chain.py`)

**Callers to update:**
| File | Usage | Update Required |
|------|-------|-----------------|
| `run_positions.py` | `service.get_all_positions()` returns DataFrame | Use `result.to_api_response()` / `result.to_cli_report()` for output; return `PositionResult` when `return_data=True` |
| `inputs/portfolio_manager.py` | Imports PositionService but doesn't call `get_all_positions()` | No change needed |
| Tests | No tests currently use PositionService | Add new tests |

**run_positions.py changes:**
```python
def run_positions(..., return_data: bool = False) -> Optional[PositionResult]:
    service = PositionService(user_email=user_email)
    result = service.get_all_positions(consolidate=consolidated)  # Returns PositionResult

    if output_path:
        # Write JSON envelope to file
        with open(output_path, "w") as f:
            json.dump(result.to_api_response(), f, indent=2)

    if to_risk:
        # Chain to risk analysis via PositionsData
        portfolio_data = result.data.to_portfolio_data()
        # ... existing risk analysis logic ...

    if return_data:
        return result  # Returns PositionResult (not DataFrame)

    # CLI output based on --format flag
    if format == "json":
        print(json.dumps(result.to_api_response(), indent=2))
    else:
        print(result.to_cli_report())
```

### Phase 3: Route Refactor
**Moved to:** [POSITION_SERVICE_REFACTOR_PLAN.md](./POSITION_SERVICE_REFACTOR_PLAN.md)

This phase (making routes thin, moving cache logic to PositionService) is covered in the
Position Service Refactor Plan which provides detailed implementation guidance.

---

## Files Modified

| Phase | File | Change |
|-------|------|--------|
| 1a | `core/data_objects.py` | Add PositionsData class (~80 lines) |
| 1b | `core/result_objects.py` | Add PositionResult class (~120 lines) |
| 2 | `services/position_service.py` | Change return type to PositionResult (~20 lines) |
| 2 | `run_positions.py` | Use PositionResult methods, add `--format json\|cli` flag, return PositionResult |

---

## Verification

### Phase 1a Tests (PositionsData)
```bash
# Unit tests for PositionsData
python -m pytest tests/unit/test_data_objects.py -k "PositionsData" -v

# Test to_portfolio_data conversion (defaults to settings.PORTFOLIO_DEFAULTS when args omitted)
python -c "
from core.data_objects import PositionsData
data = PositionsData(
    positions=[{'ticker': 'AAPL', 'quantity': 100, 'value': 15000}],
    user_email='test@example.com',
    sources=['plaid']
)
portfolio = data.to_portfolio_data()
print(portfolio.get_tickers())
"
```

### Phase 1b Tests (PositionResult)
```bash
# Unit tests for PositionResult
python -m pytest tests/unit/test_result_objects.py -k "PositionResult" -v

# Test serialization
python -c "
import pandas as pd
from core.result_objects import PositionResult

# Create test DataFrame
df = pd.DataFrame([
    {'ticker': 'AAPL', 'name': 'Apple Inc.', 'quantity': 100, 'value': 15000, 'currency': 'USD', 'type': 'equity', 'position_source': 'plaid'},
    {'ticker': 'CUR:USD', 'name': 'US Dollar', 'quantity': 5000, 'value': 5000, 'currency': 'USD', 'type': 'cash', 'position_source': 'plaid'},
])

result = PositionResult.from_dataframe(df, 'test@example.com', ['plaid'])
print(result.to_api_response())
print(result.to_cli_report())
"
```

### Phase 2 Tests (Integration)
```bash
# Integration test - CLI with new return type
python run_positions.py --user-email test@example.com --format json

# Verify output has standard envelope
# Note: PositionService accepts optional plaid_client, snaptrade_client, region params
# but user_email alone is sufficient - clients are lazy-loaded
python -c "
import json
from services.position_service import PositionService
svc = PositionService('test@example.com')
result = svc.get_all_positions()  # Now returns PositionResult
print(json.dumps(result.to_api_response(), indent=2))
"
```

### Chain Integration Test

**File:** `tests/unit/test_position_chain.py`

This test verifies the full positions → risk chain stays connected during refactoring:

```bash
# Run chain integration tests
python -m pytest tests/unit/test_position_chain.py -v
```

**Tests included:**
- `test_position_to_portfolio_chain` - Full chain: PositionResult → PortfolioData → temp YAML
- `test_position_chain_with_consolidation` - Comma-delimited sources split correctly
- `test_position_chain_error_on_missing_data` - Fails fast on None/NaN values
- `test_position_chain_error_on_mixed_currencies` - Rejects mixed currencies per ticker

**What it verifies:**
1. Equities use `shares` format in PortfolioData
2. Cash uses `dollars` format in PortfolioData
3. Temp YAML has correct structure for risk engine
4. Comma-delimited sources (from consolidation) split into separate sources
5. Validation catches missing data and mixed currencies

### Manual Verification
1. Check `to_api_response()` output matches expected envelope format
2. Check `data.to_portfolio_data()` produces valid PortfolioData (uses `settings.PORTFOLIO_DEFAULTS` when args are omitted)
3. Check `to_cli_report()` displays nicely in terminal
4. Verify chaining: positions → PortfolioData → risk analysis works

---

## Related Documents

- [Position Module MCP Spec](./POSITION_MODULE_MCP_SPEC.md) - Full MCP integration spec
- [Position Module Plan](./POSITION_MODULE_PLAN.md) - Original module design
- [Modular CLI Architecture](./MODULAR_CLI_ARCHITECTURE_PLAN.md) - CLI patterns

---

*Document created: 2026-01-29*
*Status: ✅ COMPLETE - Phases 1-2 implemented. Phase 3 moved to POSITION_SERVICE_REFACTOR_PLAN.md*
