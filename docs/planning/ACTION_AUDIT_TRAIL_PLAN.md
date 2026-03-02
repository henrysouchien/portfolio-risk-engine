# Action Audit Trail

## Context

WORKFLOW_DESIGN.md (line 1319, 1388) identifies a gap: "No action tracking / audit trail. No persistence of which recommendations were accepted/rejected/executed." Today, when the agent surfaces a recommendation (e.g., "reduce AAPL to 15%", "hedge with GLD"), there's no record of whether the user accepted, rejected, or executed it. The only context is the ephemeral conversation. This matters for compliance audit, workflow continuity across sessions, and understanding which recommendations actually get acted on.

**Design principle**: Agent-called, not auto-capture. The agent explicitly calls `record_workflow_action()` when surfacing a recommendation that the user should act on. Status updates happen when the user decides (accept/reject) and when execution completes. This avoids noisy auto-logging of every tool call.

---

## Changes

### 1. Migration: `database/migrations/20260302_add_workflow_actions.sql`

```sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS workflow_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    portfolio_name VARCHAR(255) NOT NULL,

    -- Source context
    workflow_name VARCHAR(100) NOT NULL,      -- "hedging", "scenario_analysis", "strategy_design", "risk_review"
    source_tool VARCHAR(100),                 -- MCP tool that generated the recommendation
    source_flag VARCHAR(100),                 -- flag type that triggered it (optional)
    flag_severity VARCHAR(20),                -- "error", "warning", "info"

    -- Recommendation
    recommendation_type VARCHAR(50) NOT NULL,  -- "trade", "rebalance", "hedge", "reduce_position", "add_position", "custom"
    recommendation_text TEXT NOT NULL,          -- Human-readable: "Reduce AAPL from 25% to 15%"
    recommendation_data JSONB,                 -- Structured: {"ticker": "AAPL", "from_weight": 0.25, "to_weight": 0.15}
    portfolio_snapshot_id VARCHAR(255),         -- Optional reference to a cached snapshot

    -- Status lifecycle
    action_status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (action_status IN ('pending', 'accepted', 'rejected', 'executed', 'expired')),
    status_reason TEXT,                        -- Why rejected/expired: "user preferred TLT hedge instead"

    -- Execution linkage
    execution_result JSONB,                    -- After execution: {"trade_id": "...", "fill_price": 142.50}
    linked_trade_ids UUID[],                   -- Array of trade_order UUIDs

    -- Timestamps
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    decided_at TIMESTAMP,                      -- When user accepted/rejected
    executed_at TIMESTAMP,                     -- When trade(s) actually filled
    expired_at TIMESTAMP                       -- When action was expired
);

-- Immutable status transition log for full audit history
CREATE TABLE IF NOT EXISTS workflow_action_events (
    id SERIAL PRIMARY KEY,
    action_id UUID NOT NULL REFERENCES workflow_actions(id) ON DELETE CASCADE,
    from_status VARCHAR(20),                   -- NULL for initial creation
    to_status VARCHAR(20) NOT NULL,
    reason TEXT,
    changed_by INTEGER REFERENCES users(id),   -- user_id who triggered the change
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflow_actions_user_portfolio
    ON workflow_actions(user_id, portfolio_name);
CREATE INDEX IF NOT EXISTS idx_workflow_actions_user_status
    ON workflow_actions(user_id, action_status);
CREATE INDEX IF NOT EXISTS idx_workflow_actions_user_created
    ON workflow_actions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_workflow_action_events_action
    ON workflow_action_events(action_id);

DROP TRIGGER IF EXISTS update_workflow_actions_updated_at ON workflow_actions;
CREATE TRIGGER update_workflow_actions_updated_at
    BEFORE UPDATE ON workflow_actions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
```

### 2. DatabaseClient: 3 new methods in `inputs/database_client.py`

Follow existing patterns: `@log_operation`, `@log_timing(1.0)`, `@handle_database_error`. Each method includes graceful pre-migration fallback (catch `"workflow_actions" ... "does not exist"` → return empty/False, matching `get_target_allocations` pattern at `database_client.py:905`).

```python
@log_operation("workflow_action_save")
@log_timing(1.0)
@handle_database_error
def save_workflow_action(self, user_id, portfolio_name, workflow_name,
                         recommendation_type, recommendation_text,
                         recommendation_data=None, source_tool=None,
                         source_flag=None, flag_severity=None,
                         portfolio_snapshot_id=None) -> str:
    """INSERT a new workflow action + initial event. Returns UUID."""
    # INSERT into workflow_actions, RETURNING id
    # INSERT into workflow_action_events (from_status=NULL, to_status='pending', changed_by=user_id)
    # Graceful fallback: table not exist → return None (caller treats as no-op)

@log_operation("workflow_action_status_update")
@log_timing(1.0)
@handle_database_error
def update_workflow_action_status(self, action_id, user_id, new_status,
                                   status_reason=None, execution_result=None,
                                   linked_trade_ids=None) -> bool:
    """UPDATE status + timestamps. Returns True if row found.

    User-scoped: WHERE id = action_id AND user_id = user_id (prevents cross-user updates).
    """
    # SELECT current action_status WHERE id = action_id AND user_id = user_id
    # Validate transition: VALID_TRANSITIONS = {
    #   "pending": {"accepted", "rejected", "expired"},
    #   "accepted": {"executed", "expired"},
    # }
    # UPDATE workflow_actions SET action_status, decided_at/executed_at/expired_at
    # INSERT into workflow_action_events (from_status, to_status, reason, changed_by)
    # Graceful fallback: table not exist → return False

@log_operation("workflow_actions_retrieval")
@log_timing(1.0)
@handle_database_error
def get_workflow_actions(self, user_id, portfolio_name=None,
                         status_filter=None, workflow_filter=None,
                         limit=50, offset=0) -> list[dict]:
    """SELECT with optional filters, ordered by created_at DESC.

    Validates limit (1-200) and offset (>=0). Returns list of dicts.
    """
    # Graceful fallback: table not exist → return []
```

### 3. MCP tools: `mcp_tools/audit.py`

Three tools following `mcp_tools/allocation.py` pattern (`@handle_mcp_errors`, user resolution via `resolve_user_email`).

**Tool 1: `record_workflow_action`**
```python
@handle_mcp_errors
def record_workflow_action(
    workflow_name: str,                    # "hedging", "scenario_analysis", "strategy_design", "risk_review"
    recommendation_type: str,             # "trade", "rebalance", "hedge", "reduce_position", "add_position", "custom"
    recommendation_text: str,             # "Reduce AAPL from 25% to 15%"
    recommendation_data: dict | None = None,
    source_tool: str | None = None,       # "run_whatif", "get_risk_analysis", etc.
    source_flag: str | None = None,       # "concentration_violation", etc.
    flag_severity: str | None = None,
    portfolio_name: str = "CURRENT_PORTFOLIO",
) -> dict:
    """Record a recommendation the agent is surfacing to the user."""
    # Validates workflow_name against allowlist
    # Validates recommendation_type against allowlist
    # Resolves user via resolve_user_email()
    # Delegates to DatabaseClient.save_workflow_action()
    # Returns: {"status": "success", "action_id": "uuid", "action_status": "pending", ...}
```

**Tool 2: `update_action_status`**
```python
@handle_mcp_errors
def update_action_status(
    action_id: str,                       # UUID from record_workflow_action
    new_status: str,                      # "accepted", "rejected", "executed", "expired"
    status_reason: str | None = None,     # Why rejected/expired
    execution_result: dict | None = None, # Trade fill details
    linked_trade_ids: list[str] | None = None,
) -> dict:
    """Update the status of a previously recorded action."""
    # Resolves user via resolve_user_email() — required for user-scoped DB update
    # Validates: action_id is valid UUID format
    # Validates: new_status in allowed set
    # Delegates to DatabaseClient.update_workflow_action_status(action_id, user_id, ...)
    #   — user_id in WHERE clause prevents cross-user updates
    # Returns: {"status": "success", "action_id": "...", "new_status": "..."}
```

**Tool 3: `get_action_history`**
```python
@handle_mcp_errors
def get_action_history(
    portfolio_name: str = "CURRENT_PORTFOLIO",
    status_filter: str | None = None,     # "pending", "accepted", etc.
    workflow_filter: str | None = None,    # "hedging", etc.
    limit: int = 50,
    include_flags: bool = True,           # Whether to generate audit flags
) -> dict:
    """Retrieve action history with optional audit flags."""
    # Resolves user, fetches from DB
    # If include_flags: generates audit flags from action list + summary stats
    # Returns: {"status": "success", "actions": [...], "summary": {...}, "flags": [...]}
```

### 4. Audit flags: `core/audit_flags.py`

```python
def generate_audit_flags(snapshot: dict) -> list[dict]:
```

5 flag types, following `core/income_projection_flags.py` pattern:

| Flag | Severity | Condition |
|------|----------|-----------|
| `stale_pending_actions` | warning | Any pending actions older than 7 days |
| `high_rejection_rate` | info | >50% of recent actions rejected (min 5 actions) |
| `low_execution_rate` | info | <25% of accepted actions actually executed (min 5 accepted) |
| `unresolved_violations` | warning | Pending actions linked to error-severity source flags |
| `no_history` | info | No actions recorded for this portfolio |

### 5. Register in `mcp_server.py`

Add imports + `@mcp.tool()` wrappers for all 3 tools. Docstrings:
- `record_workflow_action`: "Record a recommendation being surfaced to the user for action tracking."
- `update_action_status`: "Update the status of a previously recorded recommendation (accept/reject/execute)."
- `get_action_history`: "Retrieve action history and audit summary for a portfolio."

---

## Files Changed

| File | Change |
|------|--------|
| `database/migrations/20260302_add_workflow_actions.sql` | NEW — `workflow_actions` + `workflow_action_events` tables, indexes, trigger |
| `inputs/database_client.py` | ADD 3 methods (~120 lines) |
| `mcp_tools/audit.py` | NEW — 3 MCP tools |
| `core/audit_flags.py` | NEW — `generate_audit_flags()` (5 flag types) |
| `mcp_server.py` | Register 3 tools |
| `tests/mcp_tools/test_audit.py` | NEW — MCP tool tests |
| `tests/inputs/test_workflow_actions.py` | NEW — DatabaseClient method tests |
| `tests/core/test_audit_flags.py` | NEW — flag tests |

No changes to existing tools — `record_workflow_action` is called by the agent alongside existing tools, not wired into them.

---

## Key Design Decisions

1. **Agent-called, not auto-capture** — The agent decides when to record an action. No automatic logging of every MCP call. This keeps the audit trail meaningful and avoids noise.
2. **UUID primary key** — Matches `trade_previews`/`trade_orders` pattern (see `database/migrations/20260209_add_trade_tables.sql`). Agent can reference action_id across tool calls.
3. **JSONB for flexible data, UUID[] for trade links** — `recommendation_data` and `execution_result` are JSONB (variable structure). `linked_trade_ids` is `UUID[]` for type safety and potential join efficiency with `trade_orders.id`.
4. **Immutable event log** — `workflow_action_events` table captures every status transition with timestamp, from/to status, reason, and who triggered it. The main `workflow_actions` table has current status for fast reads; events table provides full audit history.
5. **User-scoped mutations** — All write operations include `user_id` in the WHERE clause, preventing cross-user updates even if a UUID leaks. Matches `trade_execution_service.py` pattern.
6. **Status lifecycle** — `pending → accepted/rejected/expired` and `accepted → executed/expired`. Terminal states: `rejected`, `executed`, `expired` (no further transitions allowed). Enforced in `update_workflow_action_status()` application logic (not DB constraint — allows flexibility). Invalid transitions return error. Repeated updates to terminal states are idempotent no-ops (return success, no new event).
7. **No auto-expiry** — Stale actions flagged but not auto-expired. Agent or user explicitly expires them.
8. **Flags on `get_action_history` only** — Audit flags computed when history is retrieved, not on record/update. Keeps write path fast.
9. **`portfolio_snapshot_id` is a string reference** — Not a full snapshot copy. Links to whatever caching mechanism exists (or is added later). Optional field.
10. **Follows existing CRUD patterns exactly** — Migration naming (`YYYYMMDD_*.sql`), DatabaseClient decorators (`@log_operation`, `@log_timing(1.0)`, `@handle_database_error`), graceful pre-migration fallback, `_db_client` context manager, MCP `@handle_mcp_errors` + `resolve_user_email` on all 3 tools (matches `mcp_tools/allocation.py`).

---

## Verification

### Flag tests (`tests/core/test_audit_flags.py`)
- `stale_pending_actions` fires when pending action > 7 days old
- `stale_pending_actions` does NOT fire for recent pending actions
- `high_rejection_rate` fires at >50% rejection with min 5 actions
- `high_rejection_rate` does NOT fire below minimum threshold
- `low_execution_rate` fires at <25% execution of accepted, min 5 accepted
- `unresolved_violations` fires for pending + error-severity source flag
- `no_history` fires for empty action list
- Flag severity ordering (warning before info)

### DatabaseClient tests (`tests/inputs/test_workflow_actions.py`)
Following `tests/inputs/test_target_allocations.py` pattern (fake cursor/connection).
- `save_workflow_action` — returns UUID string
- `save_workflow_action` — inserts event row (from_status=NULL, to_status='pending')
- `update_workflow_action_status` — valid transition updates row + inserts event
- `update_workflow_action_status` — user_id scoping (wrong user_id → returns False)
- `update_workflow_action_status` — invalid transition (rejected → executed) raises error
- `update_workflow_action_status` — sets decided_at on accept/reject, executed_at on execute, expired_at on expire
- `get_workflow_actions` — returns list of dicts ordered by created_at DESC
- `get_workflow_actions` — status_filter/workflow_filter applied correctly
- `get_workflow_actions` — limit/offset bounds (limit clamped 1-200, offset >= 0)
- All 3 methods — graceful fallback when table doesn't exist (pre-migration)

### Tool tests (`tests/mcp_tools/test_audit.py`)
- `record_workflow_action` — valid input returns UUID + pending status
- `record_workflow_action` — invalid workflow_name returns error
- `record_workflow_action` — invalid recommendation_type returns error
- `record_workflow_action` — empty recommendation_text returns error
- `record_workflow_action` — resolves user via resolve_user_email
- `update_action_status` — resolves user via resolve_user_email (user-scoped)
- `update_action_status` — valid transition (pending → accepted) succeeds
- `update_action_status` — valid transition (accepted → executed) succeeds
- `update_action_status` — invalid transition (rejected → executed) returns error
- `update_action_status` — nonexistent action_id returns error
- `update_action_status` — execution_result and linked_trade_ids stored correctly
- `get_action_history` — returns actions in created_at DESC order
- `get_action_history` — status_filter works
- `get_action_history` — workflow_filter works
- `get_action_history` — include_flags=True generates audit flags
- `get_action_history` — empty history returns `no_history` flag
- `get_action_history` — summary counts (total, by status, by workflow)
- `get_action_history` — limit/offset pagination

### MCP registration test
- Verify all 3 tools registered in `mcp_server.py` (import check, matching `tests/unit/test_mcp_server_contracts.py` pattern)

### Integration test (manual)
1. Run migration against local DB
2. `/mcp` reconnect
3. Call `record_workflow_action` with a hedging recommendation
4. Call `get_action_history` — see the pending action + `no_history` flag absent
5. Call `update_action_status` to accept it
6. Call `get_action_history` — see accepted status, `decided_at` populated
