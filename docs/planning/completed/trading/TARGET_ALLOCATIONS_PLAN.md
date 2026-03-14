# Target Allocations: DB Migration + MCP Set/Get Tools

## Context

The drift detection infrastructure is fully built end-to-end but has no data:
- **Schema**: `target_allocations` table defined in `database/schema.sql` (user_id, portfolio_name, asset_class, target_pct) — but table likely not migrated to the live DB
- **Read path**: `database_client.get_target_allocations()` → `portfolio_repository` → `portfolio_manager` → `PortfolioData.target_allocation` → `analyze_portfolio()` → `RiskAnalysisResult.analysis_metadata["target_allocation"]` → `compute_allocation_drift()` → `_build_asset_allocation_breakdown()` with drift rows → API response `asset_allocation` field → frontend
- **Drift compute**: `allocation_drift.py` — thresholds at 2% (on_target) and 5% (warning), tested
- **Write path**: **Does not exist**. No `save_target_allocations()`, no MCP tool, no API endpoint

The entire pipeline works — it just needs the table created and a way to populate it.

## Implementation

### 1. DB Migration — Create `target_allocations` table

Run the CREATE TABLE + indexes + trigger from `database/schema.sql` lines 257-266, 396-399, 461-462 against the live DB. Can be done via a migration script or direct SQL.

```sql
CREATE TABLE IF NOT EXISTS target_allocations (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    portfolio_name VARCHAR(255) NOT NULL,
    asset_class VARCHAR(100) NOT NULL,
    target_pct DECIMAL(6,2) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, portfolio_name, asset_class)
);

CREATE INDEX IF NOT EXISTS idx_target_allocations_user_portfolio
    ON target_allocations(user_id, portfolio_name);

-- Idempotent trigger creation
DROP TRIGGER IF EXISTS update_target_allocations_updated_at ON target_allocations;
CREATE TRIGGER update_target_allocations_updated_at
    BEFORE UPDATE ON target_allocations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

Create `database/migrations/003_target_allocations.sql` for this. Migration is fully idempotent (IF NOT EXISTS on table/index, DROP+CREATE on trigger).

### 2. Add `save_target_allocations()` to `inputs/database_client.py`

Follow the `save_expected_returns()` pattern (line 988). Upsert per asset class:

```python
def save_target_allocations(self, user_id: int, portfolio_name: str, allocations: Dict[str, float]) -> None:
```

- UPSERT (ON CONFLICT ... DO UPDATE) on `(user_id, portfolio_name, asset_class)`
- Delete asset classes not in the new dict (full replace semantics — the MCP tool always sends the complete allocation, never partial updates)
- Single transaction
- Graceful missing-table handling matching `get_target_allocations()` pattern (line 904-908 in database_client.py)

### 3. Add `save_target_allocations()` to `inputs/portfolio_repository.py`

Thin wrapper following the `save_expected_returns()` pattern (line 89).

### 4. Add MCP tool: `set_target_allocation()` on portfolio-mcp

New tool in `mcp_tools/allocation.py`:

```python
def set_target_allocation(
    allocations: dict,          # {"equity": 60.0, "bond": 25.0, "real_estate": 10.0, "cash": 5.0}
    portfolio_name: str = "CURRENT_PORTFOLIO",
) -> dict:
```

- Validate: all values are numeric, sum to ~100% (allow 0.5% tolerance)
- Validate asset classes using `is_valid_asset_class()` from `portfolio_risk_engine/constants.py`
- This is a full-replace operation: the entire allocation must be provided each call (not partial updates)
- Call `repository.save_target_allocations()`
- Return confirmation with saved allocations

### 5. Add MCP tool: `get_target_allocation()` on portfolio-mcp

```python
def get_target_allocation(
    portfolio_name: str = "CURRENT_PORTFOLIO",
) -> dict:
```

- Call `repository.get_target_allocations()`
- If empty, return `{status: "not_set", message: "No target allocations configured"}`
- If set, return the allocations dict (no drift computation — drift is already computed and returned by `get_risk_analysis()` via `_build_asset_allocation_breakdown()` whenever targets exist)

### 6. Load target allocations in MCP risk path (`mcp_tools/risk.py`)

`_load_portfolio_for_analysis()` (line 408) builds `PortfolioData` from live positions but never loads `target_allocation` from the DB. The API path loads it via `PortfolioManager.load_portfolio_config()`, but the MCP path skips this. Add after factor proxy loading (~line 467):

```python
# 4. Load target allocations from DB
from inputs.portfolio_repository import PortfolioRepository
repo = PortfolioRepository()
portfolio_data.target_allocation = repo.get_target_allocations(user_id, portfolio_name)
```

Without this, `get_risk_analysis()` via MCP will never show drift even when targets are saved.

### 7. Wire tools in `mcp_server.py`

Register both new tools.

## Valid Asset Classes

Canonical set from `VALID_ASSET_CLASSES` in `portfolio_risk_engine/constants.py`:
- `equity`, `bond`, `real_estate`, `commodity`, `crypto`, `cash`, `mixed`, `unknown`

Use `is_valid_asset_class()` from the same file for validation. The `unknown` class should probably be excluded from target allocations (it's a fallback for unclassifiable securities, not a target).

## Files Modified

| File | Change |
|------|--------|
| `database/migrations/003_target_allocations.sql` | **New**: CREATE TABLE + indexes + trigger |
| `inputs/database_client.py` | Add `save_target_allocations()` (~30 lines) |
| `inputs/portfolio_repository.py` | Add `save_target_allocations()` wrapper (~3 lines) |
| `mcp_tools/allocation.py` | **New**: `set_target_allocation()` + `get_target_allocation()` |
| `mcp_tools/risk.py` | Add `target_allocation` DB load in `_load_portfolio_for_analysis()` (~3 lines) |
| `mcp_server.py` | Register 2 new tools |

## What Already Works (No Changes Needed)

- `get_target_allocations()` read path (database_client → repository → portfolio_manager → PortfolioData)
- `compute_allocation_drift()` in `portfolio_risk_engine/allocation_drift.py`
- `_build_asset_allocation_breakdown()` in `core/result_objects/risk.py` (includes drift rows)
- `get_risk_analysis()` already returns drift in `asset_allocation` field (via `portfolio_service.py` lines 242-244 and 274 which thread `target_allocation` from `PortfolioData` into `analysis_metadata`)
- Frontend `AssetAllocationContainer` already renders drift data
- Tests in `tests/core/test_allocation_drift.py`

## Verification

1. Run migration script against live DB
2. `set_target_allocation(allocations={"equity": 60, "bond": 25, "real_estate": 10, "cash": 5})` via MCP
3. `get_target_allocation()` via MCP — should return saved allocations
4. `get_risk_analysis(format="agent")` — check `asset_allocation` section shows drift vs targets
5. Unit tests for save/get in `tests/inputs/test_target_allocations.py`
6. Verify frontend asset allocation view shows drift indicators
