# Plan: Account Activate/Deactivate MCP Tools

## Context

Two IBKR accounts (SnapTrade + Flex) point to the same brokerage account, causing duplicate positions in the combined portfolio (61 positions, should be ~40). Need `account_deactivate` and `account_activate` MCP tools with proper cascade logic that survives sync cycles.

## Codex Review Issues (v3, all addressed)

1. **VIRTUAL_ALL bypass** — Position filtering in `get_all_positions()` using composite `(institution_key, account_id_external)` matching
2. **Sync reactivation** — `user_deactivated` column + 5 guard points (upsert_account, _resolve_current_portfolio_account_ids, discover_accounts_from_positions, ensure_single_account_portfolios, link_csv_accounts_to_combined)
3. **Internal commits break atomicity** — Cascade methods use raw cursor SQL directly (not existing helpers that commit internally) within a single connection; explicit commit at end, rollback on error
4. **CSV relink path** — `link_csv_accounts_to_combined()` filters out user_deactivated account IDs before adding
5. **Weak matcher** — Position filter uses composite `(institution_key, account_id_external)` tuples, matching the accounts table unique constraint
6. **list_portfolios count** — Informational only; real filtering in `get_all_positions()`. Consistent throughout plan.

## Files to Modify

| File | Action |
|------|--------|
| `database/migrations/20260315_account_user_deactivated.sql` | New: add `user_deactivated` column |
| `database/schema.sql` | Add `user_deactivated` column to accounts table |
| `inputs/database_client.py` | Add 3 new methods; modify `upsert_account()` ON CONFLICT |
| `services/account_registry.py` | Add 2 cascade methods; modify 4 existing methods for sync durability |
| `services/position_service.py` | Add inactive account filtering in `get_all_positions()` |
| `mcp_tools/portfolio_management.py` | Add 4 functions (2 data + 2 tool) |
| `mcp_server.py` | Register 2 new tools |
| `tests/mcp_tools/test_account_activate_deactivate.py` | New: ~18 tests |

## Step 0: Migration + Schema

**Migration:** `database/migrations/20260315_account_user_deactivated.sql`
```sql
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS user_deactivated BOOLEAN NOT NULL DEFAULT FALSE;
```

**Schema:** Update `database/schema.sql` accounts table to include `user_deactivated BOOLEAN NOT NULL DEFAULT FALSE`.

Semantics:
- `user_deactivated=true` → user explicitly deactivated; all sync paths preserve `is_active=false`
- `user_deactivated=false` → normal; sync controls `is_active` freely

## Step 1: Database Layer (`inputs/database_client.py`)

### New: `set_account_active(user_id, account_id, is_active, user_deactivated) -> Optional[dict]`
Standalone method using `self.get_connection()`. Does NOT commit internally — caller controls transaction.
```sql
UPDATE accounts SET is_active = %s, user_deactivated = %s, updated_at = NOW()
WHERE id = %s AND user_id = %s
RETURNING *
```

### New: `get_portfolios_for_account(user_id, account_id) -> list[dict]`
Read-only query, safe to use existing connection pattern.
```sql
SELECT p.id, p.name, p.portfolio_type, p.auto_managed, p.is_active,
       (SELECT COUNT(*) FROM portfolio_accounts pa2 WHERE pa2.portfolio_id = p.id) AS account_count
FROM portfolios p
JOIN portfolio_accounts pa ON pa.portfolio_id = p.id
WHERE p.user_id = %s AND pa.account_id = %s
```

### New: `remove_account_from_portfolio(user_id, portfolio_name, account_id) -> bool`
Does NOT commit internally — caller controls transaction.
```sql
DELETE FROM portfolio_accounts
WHERE portfolio_id = (SELECT id FROM portfolios WHERE user_id = %s AND name = %s)
  AND account_id = %s
```

### Modify: `upsert_account()` — respect `user_deactivated` (line 1152)
Change ON CONFLICT `is_active` assignment:
```sql
is_active = CASE
    WHEN accounts.user_deactivated THEN accounts.is_active
    ELSE EXCLUDED.is_active
END,
user_deactivated = accounts.user_deactivated  -- never overwrite from sync
```

## Step 2: Sync Durability — 5 Guard Points (`services/account_registry.py`)

### Guard 1: `_resolve_current_portfolio_account_ids(conn)` (line 421)
Currently uses `active_only=False`, linking ALL accounts with positions. Filter out user-deactivated:
```python
accounts = db_client.get_user_accounts(self.user_id, active_only=False)
account_lookup = {
    _account_identity_key(...): int(a["id"])
    for a in accounts
    if a.get("id") is not None and not a.get("user_deactivated")
}
```

### Guard 2: `ensure_single_account_portfolios()` (line 306)
Add skip for user-deactivated accounts in the iteration loop:
```python
for account in current_accounts:
    if account.get("user_deactivated"):
        continue
```

### Guard 3: `discover_accounts_from_positions()` (line 87)
Before building the payload, check if account was user-deactivated. The `upsert_account()` ON CONFLICT change (Step 1) handles this at SQL level, but add a Python-level guard too for clarity:
```python
payload["is_active"] = True  # default
# upsert_account() SQL CASE will preserve is_active=False when user_deactivated=True
```
No Python change needed — the SQL guard in `upsert_account()` is sufficient.

### Guard 4: `link_csv_accounts_to_combined()` (line 357)
Filter out user-deactivated accounts before linking:
```python
def link_csv_accounts_to_combined(self, account_ids: list[int]) -> int:
    ...
    # Filter out user-deactivated accounts
    with get_db_session() as conn:
        db_client = DatabaseClient(conn)
        all_accounts = db_client.get_user_accounts(self.user_id, active_only=False)
        deactivated_ids = {int(a["id"]) for a in all_accounts if a.get("user_deactivated")}
        normalized_ids = [aid for aid in normalized_ids if aid not in deactivated_ids]
        if not normalized_ids:
            return 0
        inserted = db_client.add_portfolio_accounts(...)
    return inserted
```

### Guard 5: `upsert_account()` SQL (Step 1)
The ON CONFLICT CASE statement prevents sync from overwriting `is_active` when `user_deactivated=true`.

## Step 3: Position Filtering (`services/position_service.py`)

Reuse `filter_positions_to_accounts()` and `_position_matches()` from `portfolio_scope.py` directly — no reimplementation. Build `AccountFilter` tuples for inactive accounts and use the existing negative-match logic.

### Modify: `get_all_positions()` (line 341, after concat, before institution/account filtering)
```python
if not combined.empty:
    inactive_filters = self._get_inactive_account_filters()
    if inactive_filters:
        from services.portfolio_scope import filter_positions_to_accounts
        # filter_positions_to_accounts returns MATCHING rows — we want the inverse
        position_dicts = combined.to_dict("records")
        inactive_positions = set(id(p) for p in filter_positions_to_accounts(position_dicts, inactive_filters))
        keep_mask = [id(p) not in inactive_positions for p in position_dicts]
        combined = combined[keep_mask].reset_index(drop=True)
```

### New: `_get_inactive_account_filters() -> list[tuple[str, str, str]]`
Returns `AccountFilter` tuples `(institution_key, account_id_external, account_name)` for inactive accounts. Uses `_get_user_id()` (the existing PositionService accessor). These feed directly into `_build_filter_sets()` → `_position_matches()`, getting the full matching behavior (ID match + name fallback + ambiguous name suppression):
```python
def _get_inactive_account_filters(self) -> list[tuple[str, str, str]]:
    if not is_db_available():
        return []
    try:
        user_id = self._get_user_id()
    except Exception:
        return []
    with get_db_session() as conn:
        db_client = DatabaseClient(conn)
        accounts = db_client.get_user_accounts(user_id, active_only=False)
        return [
            (a.get("institution_key", ""), a.get("account_id_external", ""), a.get("account_name", ""))
            for a in accounts
            if not a.get("is_active")
        ]
```

This fully reuses `portfolio_scope` matching — ID match, name fallback, ambiguous name suppression, `_unknown_` handling — with zero reimplementation.

## Step 4: Cascade Methods (`services/account_registry.py`)

### New: `deactivate_account(account_id: int) -> dict`

Uses raw cursor SQL for mutations to avoid helper-level commits. Single connection, explicit commit/rollback:
```python
def deactivate_account(self, account_id: int) -> dict:
    with get_db_session() as conn:
        try:
            db_client = DatabaseClient(conn)
            cursor = conn.cursor()

            # Read: all accounts (including inactive)
            accounts = db_client.get_user_accounts(self.user_id, active_only=False)
            target = next((a for a in accounts if int(a["id"]) == account_id), None)
            if not target:
                raise ValueError(f"Account {account_id} not found")
            if not target.get("is_active") and target.get("user_deactivated"):
                return {"no_op": True, "account": _serialize_account(target), "message": "..."}

            active_count = sum(1 for a in accounts if a.get("is_active") and int(a["id"]) != account_id)
            if active_count == 0:
                raise ValueError("Cannot deactivate the last active account")

            # Mutate 1: deactivate account (raw SQL, no commit)
            cursor.execute(
                "UPDATE accounts SET is_active = FALSE, user_deactivated = TRUE, updated_at = NOW() WHERE id = %s AND user_id = %s",
                (account_id, self.user_id)
            )

            # Read: find linked portfolios
            portfolios = db_client.get_portfolios_for_account(self.user_id, account_id)

            # Mutate 2: deactivate _auto_* portfolio (raw SQL)
            auto_name = None
            for p in portfolios:
                if p["portfolio_type"] == "single_account":
                    auto_name = p["name"]
                    cursor.execute(
                        "UPDATE portfolios SET is_active = FALSE, updated_at = NOW() WHERE id = %s",
                        (p["id"],)
                    )
                    break

            # Mutate 3: remove from all linked portfolios (raw SQL)
            removed_from = []
            for p in portfolios:
                cursor.execute(
                    "DELETE FROM portfolio_accounts WHERE portfolio_id = %s AND account_id = %s",
                    (p["id"], account_id)
                )
                removed_from.append(p["name"])

            conn.commit()
            return {
                "account": _serialize_account({**target, "is_active": False, "user_deactivated": True}),
                "auto_portfolio_deactivated": auto_name,
                "removed_from_portfolios": removed_from,
                "message": f"Account {account_id} deactivated. Removed from {len(removed_from)} portfolio(s).",
            }
        except Exception:
            conn.rollback()
            raise
```

### New: `activate_account(account_id: int) -> dict`
Same pattern — raw cursor SQL, single connection, clears `user_deactivated`, re-links to CURRENT_PORTFOLIO via raw INSERT, reactivates `_auto_*` portfolio.

## Step 5: MCP Layer + Registration

Thin wrappers in `mcp_tools/portfolio_management.py` using `_serialize_account()` for response shape. Register in `mcp_server.py` with `@mcp.tool()`.

```python
@handle_mcp_errors
@require_db
def account_deactivate(user_email=None, account_id=0) -> dict

@handle_mcp_errors
@require_db
def account_activate(user_email=None, account_id=0) -> dict
```

## Step 6: Tests (`tests/mcp_tools/test_account_activate_deactivate.py`)

**Deactivate tests:**
1. Happy path — full cascade (account, auto portfolio, removed from all linked portfolios)
2. Already inactive + user_deactivated — idempotent no-op with account in response
3. Last active account — rejected with error
4. Unknown account ID — rejected
5. Removes from multiple custom portfolios
6. Empty custom portfolio after removal — allowed (no error)

**Activate tests:**
7. Happy path — sets active, clears user_deactivated, reactivates auto portfolio, re-links to CURRENT_PORTFOLIO
8. Already active — idempotent no-op with account in response
9. Unknown account ID — rejected

**Sync durability tests:**
10. `upsert_account()` does NOT overwrite is_active when user_deactivated=True
11. `_resolve_current_portfolio_account_ids()` excludes user_deactivated accounts from linking
12. `ensure_single_account_portfolios()` skips user_deactivated accounts
13. `link_csv_accounts_to_combined()` filters out user_deactivated account IDs

**Position filtering tests:**
14. `get_all_positions()` excludes inactive account positions (composite key match)
15. `get_all_positions()` includes active account positions
16. Composite matcher handles institution normalization correctly

**Atomicity tests:**
17. Mid-cascade failure rolls back all changes (account stays active)
18. Idempotent: deactivating account already absent from CURRENT_PORTFOLIO succeeds

## Return Shapes

Uses `_serialize_account()` for `account` field (matches existing `list_accounts` response).

Deactivate:
```json
{
  "status": "success",
  "account": {"id": 4, "institution_key": "interactive_brokers", "account_name": "...", "is_active": false},
  "auto_portfolio_deactivated": "_auto_interactive_brokers_...",
  "removed_from_portfolios": ["CURRENT_PORTFOLIO"],
  "message": "Account 4 deactivated. Removed from 1 portfolio(s)."
}
```

No-op:
```json
{"status": "success", "no_op": true, "account": {"id": 4, ...}, "message": "Account 4 is already inactive."}
```

## Safety
- Cannot deactivate the last active account
- Idempotent (deactivating already-deactivated = no-op with account in response)
- `user_deactivated` flag survives sync cycles (5 guard points)
- Raw cursor SQL for mutations avoids helper-level commits; single connection with explicit commit/rollback
- Positions retained in DB (logical deactivation, not destructive)
- Ownership guard (user_id) on all operations
- `list_portfolios` position count is informational; real filtering in `get_all_positions()`

## Verification
1. `python3 -m pytest tests/mcp_tools/test_account_activate_deactivate.py -v`
2. `python3 -m pytest tests/ -x --timeout=30` (full backend suite)
3. Live MCP test:
   - `list_accounts(active_only=false)` → see account 4 (SnapTrade IBKR)
   - `account_deactivate(account_id=4)` → verify cascade summary
   - `list_accounts()` → account 4 gone
   - `list_portfolios()` → auto portfolio gone
   - `get_positions()` → ~40 positions (not ~61)
   - `account_activate(account_id=4)` → verify reverse
4. Frontend: reload → dropdown has 7 portfolios (not 8), combined shows ~40 holdings
