# CSV Import Collision Guard

## Context

When a user CSV-imports positions for an institution that already has an active API connection (Plaid, SnapTrade, Schwab, IBKR), duplicate positions appear in CURRENT_PORTFOLIO. There's no cross-source collision detection. The fix: detect active API connections at CSV import time and block unless the user explicitly overrides.

## Codex Review History

**v1 → FAIL (4):** data_sources.status unreliable after disconnect; onboarding routes not covered; tests insufficient; `provider != 'csv'` too broad.

**v2 → FAIL (4):** SnapTrade deactivate missing `authorization_id`; full-provider delete flows not patched; no route-level tests; should reuse `POSITION_PROVIDERS`.

**v3 → FAIL (3):** Registry queries don't filter by status; missing `/import-csv-full` route test; Plaid full-delete doesn't clean `provider_items` (pre-existing, out of scope).

**v4 → FAIL (2):** Frontend CSV UI has no collision warning / force retry. Deferred to F16 in TODO.

**v5 → FAIL (2):** `link_accounts_to_data_source()` reconnect regression test missing; disconnect route wiring untested.

**v6 → FAIL (4):** Schwab/IBKR data_source rows only created on first refresh (false negatives); Plaid disconnect without `item_id` would nuke all rows; full-delete deactivation untested; test count inconsistency.

**v7 → FAIL (2):** Accounts-table fallback produces false collisions after disconnect (accounts remain active); SnapTrade full-delete test missing. Accounts fallback removed — wrong abstraction.

All findings addressed in v8 below.

## Approach

Two-part fix:
1. **Step 0**: Fix disconnect/delete flows to deactivate `data_sources` rows. Make registry queries status-aware.
2. **Steps 1-8**: Add collision guard in `import_portfolio()` using `data_sources.status = 'active'` as the single signal.

**Known limitation**: Schwab/IBKR data_source rows are only created on first successful refresh (`routes/onboarding.py:623,672`), not at connection time. There's a narrow false-negative window between connecting and first refresh. In practice this window is tiny (refresh happens during onboarding). If it becomes a real issue, the proper fix is to create data_source rows at connection time — not to use unrelated tables as a proxy signal.

## Files to Modify

| File | Change |
|------|--------|
| `inputs/database_client.py` | Add `deactivate_data_sources()` method |
| `services/account_registry.py` | Add `deactivate_data_source()` wrapper; add `AND status = 'active'` to `_get_unique_data_source_id()` (line 628) and `link_accounts_to_data_source()` (line 181) |
| `routes/plaid.py` | Call deactivate in single-item disconnect (~line 1592, guarded by `if item_id:`) and full delete (~line 1704) |
| `routes/snaptrade.py` | Call deactivate in single-connection remove (~line 1093, by `authorization_id`) and full delete (~line 1180) |
| `mcp_tools/import_portfolio.py` | Add `force` param, `_check_api_collision()`, collision logic |
| `mcp_server.py` | Add `force` param to MCP wrapper (line 419) |
| `routes/onboarding.py` | Thread collision/force through web CSV routes (lines 696, 734, 771); `force: bool = Form(False)` for multipart endpoints |
| `tests/mcp_tools/test_import_portfolio.py` | 9 collision test cases |
| `tests/routes/test_onboarding_csv_collision.py` | 5 route-level test cases |
| `tests/services/test_account_registry.py` | 4 service-level tests |
| `tests/routes/test_disconnect_deactivation.py` | 5 disconnect/delete route tests |

## Implementation

### Step 0: Fix disconnect flows (prerequisite)

#### 0a. Add `deactivate_data_sources()` to `inputs/database_client.py`

```python
def deactivate_data_sources(
    self,
    user_id: int,
    provider: str,
    provider_item_id: str | None = None,
) -> int:
    """Set data_source status to 'inactive'. Returns rows updated.
    
    If provider_item_id is given, deactivates only that specific row.
    If None, deactivates all rows for the provider (for full-delete flows).
    """
    with self.get_connection() as conn:
        cursor = conn.cursor()
        if provider_item_id:
            cursor.execute(
                """
                UPDATE data_sources
                SET status = 'inactive', updated_at = NOW()
                WHERE user_id = %s AND provider = %s AND provider_item_id = %s
                """,
                (user_id, provider, provider_item_id),
            )
        else:
            cursor.execute(
                """
                UPDATE data_sources
                SET status = 'inactive', updated_at = NOW()
                WHERE user_id = %s AND provider = %s
                """,
                (user_id, provider),
            )
        conn.commit()
        return cursor.rowcount
```

#### 0b. Add wrapper to `services/account_registry.py`

```python
def deactivate_data_source(self, provider: str, provider_item_id: str | None = None) -> int:
    """Deactivate data_source(s). Targeted if provider_item_id given, else provider-wide."""
    if not is_db_available():
        return 0
    with get_db_session() as conn:
        db_client = DatabaseClient(conn)
        return db_client.deactivate_data_sources(self.user_id, provider, provider_item_id)
```

#### 0c. Plaid single-item disconnect (`routes/plaid.py`, after line 1592)

Guard with `if item_id:` consistent with existing cleanup pattern at line 1588. A legacy secret without `item_id` must not nuke all Plaid data_source rows.

```python
if item_id:
    try:
        registry = AccountRegistry(user["user_id"])
        registry.deactivate_data_source("plaid", provider_item_id=item_id)
    except Exception as ds_error:
        portfolio_logger.warning(
            "Could not deactivate Plaid data source for item_id=%s: %s", item_id, ds_error
        )
```

#### 0d. Plaid full delete (`routes/plaid.py`, ~line 1704, inside the existing registry try/except block)

Provider-wide — all Plaid rows. Correct here because the full delete removes ALL Plaid connections.

```python
registry.deactivate_data_source("plaid")
```

#### 0e. SnapTrade single-connection remove (`routes/snaptrade.py`, ~line 1093)

SnapTrade creates data_source rows with `provider_item_id=authorization_id` (see `_sync_snaptrade_data_sources` at line 325). Deactivate by the specific `authorization_id` from the route parameter.

```python
try:
    registry = AccountRegistry(user["user_id"])
    registry.deactivate_data_source("snaptrade", provider_item_id=authorization_id)
except Exception as ds_error:
    portfolio_logger.warning(
        "Could not deactivate SnapTrade data source for authorization_id=%s: %s",
        authorization_id, ds_error,
    )
```

#### 0f. SnapTrade full delete (`routes/snaptrade.py`, ~line 1180)

Provider-wide — all SnapTrade rows.

```python
try:
    from services.account_registry import AccountRegistry
    registry = AccountRegistry(user["user_id"])
    registry.deactivate_data_source("snaptrade")
except Exception as ds_error:
    portfolio_logger.warning("Could not deactivate SnapTrade data sources: %s", ds_error)
```

#### 0g. Make `_get_unique_data_source_id()` status-aware (`account_registry.py:628`)

Add `AND status = 'active'` to the WHERE clause. Prevents inactive+active row ambiguity after disconnect+reconnect.

#### 0h. Make `link_accounts_to_data_source()` COUNT query status-aware (`account_registry.py:181`)

Add `AND status = 'active'` to the COUNT query. Same rationale as 0g.

### Step 1: Add `_check_api_collision()` helper (`import_portfolio.py`, after line 71)

Single-tier check against `data_sources` only. No fallback to other tables.

```python
from providers.routing import normalize_institution_slug, POSITION_PROVIDERS

def _check_api_collision(
    institution_slug: str,
    user_email: str,
) -> list[dict[str, Any]] | None:
    """Return active API data sources for this institution, or None."""
    if not is_db_available():
        return None
    try:
        with get_db_session() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE email = %s", (user_email,))
            row = cursor.fetchone()
            if not row:
                return None
            cursor.execute(
                """
                SELECT id, provider, institution_slug, institution_display_name
                FROM data_sources
                WHERE user_id = %s
                  AND institution_slug = %s
                  AND provider = ANY(%s)
                  AND status = 'active'
                """,
                (row["id"], institution_slug, list(POSITION_PROVIDERS)),
            )
            results = cursor.fetchall()
            return [dict(r) for r in results] if results else None
    except Exception:
        return None  # best-effort; don't break imports if query fails
```

### Step 2: Add `force` param to `import_portfolio()` (line 260)

Add `force: bool = False` to the function signature.

### Step 3: Insert collision check (after line 314, before `if dry_run`)

```python
institution_slug = normalize_institution_slug(result.brokerage_name)
colliding_sources = _check_api_collision(institution_slug, resolved_user_email)
collision = None
if colliding_sources:
    collision = {
        "institution_slug": institution_slug,
        "active_api_connections": [
            {"provider": s["provider"], "institution": s.get("institution_display_name") or institution_slug}
            for s in colliding_sources
        ],
    }
```

### Step 4: Modify dry_run branch (line 316)

If collision and not force: set `can_import = False`, update message to warn about duplicate risk. Always add `"collision": collision` to the response dict (None when no collision).

### Step 5: Add collision block before actual import (after line 345)

```python
if collision and not force:
    providers_str = ", ".join(s["provider"] for s in colliding_sources)
    return {
        "status": "collision_blocked",
        "action": "import",
        "dry_run": False,
        "brokerage_name": result.brokerage_name,
        "source_key": computed_source_key,
        "collision": collision,
        "message": (
            f"Import blocked: {result.brokerage_name} already has active API connection(s) "
            f"via {providers_str}. Importing CSV would create duplicate positions. "
            "Pass force=true to override."
        ),
    }
```

### Step 6: Annotate success response (line 359)

Add `"collision_override": bool(colliding_sources)` to the success dict.

### Step 7: Update MCP wrapper (`mcp_server.py:419`)

Add `force: bool = False` to wrapper signature and pass through.

### Step 8: Thread through onboarding routes (`routes/onboarding.py`)

- `/preview-csv` (line 696): Forward `collision` from `import_portfolio()` response into preview payload.
- `/import-csv` (line 734): Accept `force: bool = Form(False)` (multipart form field). Pass to `import_portfolio()`. If `collision_blocked` returned, return 409 with collision details.
- `/import-csv-full` (line 771): Same — `force: bool = Form(False)`.
- `_shape_csv_error()` (line 158): Handle `collision_blocked` status, include collision dict in shaped response.

### Step 9: Tests

#### Tool-level tests (`tests/mcp_tools/test_import_portfolio.py`) — 9 tests

| Test | Scenario |
|------|----------|
| `test_dry_run_collision_warns_and_blocks` | Mock collision → `can_import=False`, collision dict present |
| `test_dry_run_collision_with_force_allows` | Mock collision + `force=True` → `can_import=True`, collision still present |
| `test_import_blocked_by_collision` | `dry_run=False`, no force → `status="collision_blocked"`, no save |
| `test_import_with_force_overrides_collision` | `dry_run=False`, `force=True` → saves, `collision_override=True` |
| `test_no_collision_when_db_unavailable` | DB down → import proceeds, `collision` absent |
| `test_no_collision_for_unknown_institution` | No matching data_source → `collision` absent |
| `test_collision_matches_slug_aliases` | CSV `brokerage="IBKR"` → `normalize_institution_slug` → `interactive_brokers` matches data_source |
| `test_no_collision_after_disconnect` | data_source with `status='inactive'` → no collision |
| `test_collision_with_multiple_providers` | Two active sources (plaid+snaptrade) → both listed |

#### Route-level tests (`tests/routes/test_onboarding_csv_collision.py`) — 5 tests

| Test | Scenario |
|------|----------|
| `test_preview_csv_includes_collision_warning` | POST `/preview-csv` with collision → response includes collision dict |
| `test_import_csv_blocked_returns_409` | POST `/import-csv` multipart with collision, no force → 409 |
| `test_import_csv_force_overrides_collision` | POST `/import-csv` multipart with `data={"force": "true"}` → 200 |
| `test_import_csv_full_blocked_returns_409` | POST `/import-csv-full` multipart with collision, no force → 409 |
| `test_import_csv_full_force_overrides` | POST `/import-csv-full` multipart with `data={"force": "true"}` → 200 |

#### Deactivation & reconnect tests (`tests/services/test_account_registry.py`) — 4 tests

| Test | Scenario |
|------|----------|
| `test_deactivate_data_source_targeted` | Deactivate by provider+item_id → only that row inactive |
| `test_deactivate_data_source_provider_wide` | Deactivate by provider only → all rows for provider inactive |
| `test_get_unique_data_source_ignores_inactive` | Inactive+active rows for same provider/institution → returns active row's ID |
| `test_link_accounts_ignores_inactive_duplicates` | Inactive+active rows → count=1, accounts linked to active row |

#### Disconnect/delete route tests (`tests/routes/test_disconnect_deactivation.py`) — 5 tests

| Test | Scenario |
|------|----------|
| `test_plaid_disconnect_deactivates_data_source` | Single-item disconnect with valid `item_id` → matching data_source set to inactive |
| `test_plaid_disconnect_without_item_id_skips` | Missing `item_id` in secret → no data_source rows affected |
| `test_plaid_full_delete_deactivates_all` | Full Plaid delete → all Plaid data_source rows inactive |
| `test_snaptrade_remove_deactivates_data_source` | Single-connection remove → matching `authorization_id` data_source inactive |
| `test_snaptrade_full_delete_deactivates_all` | Full SnapTrade delete → all SnapTrade data_source rows inactive |

**Total: 23 new tests.**

## Out of Scope

- **Frontend collision UI** (F16 in TODO): `CsvImportStep.tsx`, `CsvImportCard.tsx` don't send `force` or display collision warnings. Backend returns 409 with structured info; frontend shows as plain error until F16.
- **Plaid `provider_items` cleanup on full delete**: Pre-existing gap, not introduced by this change.
- **Schwab/IBKR data_source creation at connection time**: data_source rows are only created on first refresh, not at connection time. Narrow false-negative window. Proper fix if needed: create rows in the OAuth/gateway connection handlers.

## Verification

1. Run existing tests: `pytest tests/mcp_tools/test_import_portfolio.py tests/services/test_account_registry.py -v`
2. Run all 23 new tests
3. Manual MCP: `import_portfolio(file_path=..., brokerage="schwab", dry_run=True)` → collision warning
4. Manual MCP: same with `force=True, dry_run=False` → success with `collision_override=True`
5. Verify disconnect: after Plaid single-item disconnect, data_source status is 'inactive', CSV import not blocked
6. Verify full delete: after `DELETE /plaid/user`, all Plaid data_source rows inactive
7. Verify reconnect: after disconnect+reconnect, `_get_unique_data_source_id` returns the new active row (not ambiguous)
