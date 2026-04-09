# data_sources Lifecycle Fix (F17)

## Context

The `data_sources.status` column is a ghost — set to 'active' on creation, never read, never updated, never filtered. All sync paths re-upsert as 'active' unconditionally. All disconnect/delete/recovery paths ignore it. Rows accumulate as orphans indefinitely. This must be fixed before building a CSV import collision guard (F16) that depends on `status='active'` as a reliable signal.

The `accounts` table already has a working pattern for this: a `user_deactivated` boolean flag with a CASE guard in the ON CONFLICT clause that prevents sync cycles from re-activating user-deactivated rows. We replicate this exact pattern for `data_sources`.

## Codex Review History

**v1 → FAIL (4):** Migration backfill unsafe (valid Plaid rows deactivated if provider_items not yet populated); missing MCP Plaid reconnect path at `connections.py:531`; sync reconciliation unreachable due to early return on empty live set; test gaps (no MCP tests, no empty-set/already-deactivated edge cases).

**v2 → FAIL (2):** Plaid empty-set reconciliation still unsafe — `list_provider_items_for_user()` returns [] on transient failures/missing table, not just when all items are gone. Empty set is not authoritative for Plaid. Also: existing test dummies in `test_connections.py` need `force_reactivate` kwarg added to avoid TypeError.

**v3 → FAIL (3):** SnapTrade empty set also non-authoritative — `list_snaptrade_connections()` returns [] on missing secret (credential loss), not just no connections. Pre-existing Plaid stale rows never cleaned up (reconciliation skips empty sets). Plaid single-disconnect deactivation is best-effort but placed after provider_items delete — if deactivation fails, the cleanup signal is lost.

**v4 → FAIL (3):** Plaid single-disconnect: if deactivation fails but provider_items survives, reconciliation treats item as "live" — recovery claim is wrong. Cleanup script has same non-authoritative-set problem. Files table contradicts v4 rule on early returns.

**v5 → FAIL (2):** Full-delete and recovery deactivation still best-effort — stale rows persist with no repair path. Phase 1 text inconsistency with Phase 7.

**v6 → FAIL (3):** Plaid full-delete provider_items cleanup uses raw SQL on optional table (should use guarded helper, best-effort). Tier 2 recovery doesn't auto-create new data_source rows (user must reconnect). Test count inconsistency (23 vs 18).

**v7 → FAIL (2):** `delete_provider_items_for_user()` doesn't exist — plan referenced non-existent helper. Files table says recovery deactivation "after line 157" but Phase 5e says before line 143.

**v8 → FAIL (1):** Pattern A (deactivate-first) creates sticky false-negatives if remote API call fails after local deactivation. Upsert guard prevents self-healing.

All findings addressed in v9 below. Switched to Pattern B universally — deactivate AFTER remote operation succeeds, propagate deactivation failure. False-positive risk (local DB write failing after remote success) is near-zero; CRITICAL log + admin cleanup script is the documented repair path.

## Files to Modify

| File | Change |
|------|--------|
| `database/migrations/20260408_data_source_lifecycle.sql` | New migration: add `user_deactivated` column (no backfill) |
| `database/schema.sql` | Add `user_deactivated` column to data_sources definition |
| `inputs/database_client.py` | Guard upsert ON CONFLICT (lines 1042, 1078); add `deactivate_data_sources_by_provider()` and `reactivate_data_source()` methods |
| `services/account_registry.py` | Add `deactivate_data_source()` and `deactivate_all_provider_data_sources()` wrappers; add `force_reactivate` param to `ensure_data_source()`; add `AND status = 'active'` to `_get_unique_data_source_id()` (line 628) and `link_accounts_to_data_source()` (lines 165, 181) |
| `routes/plaid.py` | Deactivate after remote ops in single-disconnect (~line 1588) and full-delete (after line 1697); reconcile stale rows in `_sync_plaid_data_sources()` (after loop, only on non-empty set); clean up provider_items in full-delete; pass `force_reactivate=True` in `exchange_token_callback()` (line 936) |
| `routes/snaptrade.py` | Deactivate after remote ops in single-disconnect (after line 1083) and full-delete (after line 1202); reconcile stale rows in `_sync_snaptrade_data_sources()` (after loop, only on non-empty set) |
| `brokerage/snaptrade/recovery.py` | Deactivate in Tier 2 recovery (after line 157, before re-registration) |
| `mcp_tools/connections.py` | Pass `force_reactivate=True` in both SnapTrade completion (line 425) AND Plaid completion (line 531) |
| `scripts/cleanup_stale_data_sources.py` | New: one-time admin script for pre-existing stale row cleanup |

## Implementation

### Phase 1: Schema Migration

**New file:** `database/migrations/20260408_data_source_lifecycle.sql`

```sql
ALTER TABLE data_sources
    ADD COLUMN IF NOT EXISTS user_deactivated BOOLEAN NOT NULL DEFAULT FALSE;
```

No automatic backfill in the migration. Pre-existing stale rows are handled by:
1. **Disconnect paths** (Phase 5) — going forward, all disconnects deactivate correctly.
2. **Sync reconciliation** (Phase 6) — opportunistic cleanup when live set is non-empty.
3. **One-time manual cleanup script** (Phase 7) — `scripts/cleanup_stale_data_sources.py` for admin to run post-deploy. Lists all active data_source rows for manual review and selective deactivation. Not automated — requires human judgment.

Also update `database/schema.sql` data_sources definition to include `user_deactivated BOOLEAN NOT NULL DEFAULT FALSE`.

### Phase 2: Guard the Upsert

**`inputs/database_client.py`** — both ON CONFLICT branches of `upsert_data_source()`.

At lines 1042 and 1078, replace:
```sql
status = EXCLUDED.status,
```
With:
```sql
status = CASE WHEN data_sources.user_deactivated THEN data_sources.status ELSE EXCLUDED.status END,
user_deactivated = data_sources.user_deactivated,
```

Replicates the exact pattern from `upsert_account()` at lines 1152-1156.

### Phase 3: Deactivation + Reactivation Methods

**`inputs/database_client.py`** — add after `upsert_data_source()`:

- `deactivate_data_sources_by_provider(user_id, provider, provider_item_id=None)` — sets `status='disconnected', user_deactivated=TRUE`. If `provider_item_id` given, targets that row only. If None, targets all rows for the provider. Skips already-deactivated rows (`WHERE user_deactivated = FALSE`).
- `reactivate_data_source(user_id, data_source_id)` — sets `status='active', user_deactivated=FALSE`.

**`services/account_registry.py`** — add wrappers:

- `deactivate_data_source(provider, provider_item_id=None)` — calls `db_client.deactivate_data_sources_by_provider()`.
- `deactivate_all_provider_data_sources(provider)` — calls same with `provider_item_id=None`.

### Phase 4: Reactivation in `ensure_data_source()`

**`services/account_registry.py`** — add `force_reactivate: bool = False` kwarg to `ensure_data_source()`.

After the upsert, if `force_reactivate=True` and the returned row has `user_deactivated=True`, call `db_client.reactivate_data_source()`.

Update call sites that represent user-initiated actions to pass `force_reactivate=True`:
- `routes/plaid.py:936` — `exchange_token_callback()` (user actively linking a new Plaid item via HTTP)
- `mcp_tools/connections.py:425` — SnapTrade connection completion (user completing a new SnapTrade connection via MCP)
- `mcp_tools/connections.py:531` — `_best_effort_finalize_plaid_connection()` (user completing a Plaid connection via MCP)
- `routes/onboarding.py:389` — `_sync_single_provider_data_source()` (user-initiated refresh for Schwab/IBKR — if they're refreshing, the connection is live)

Background sync path `_sync_plaid_data_sources` does NOT pass `force_reactivate` — driven by local `provider_items`, not an authoritative live source.

`_sync_snaptrade_data_sources()` is called from both automated fetches (snaptrade.py:907) and explicit user-initiated refresh (snaptrade.py:978). Add a `force_reactivate: bool = False` parameter to the function. Call sites:
- `snaptrade.py:907` (automated/passive fetch): `force_reactivate=False`
- `snaptrade.py:978` (explicit `POST /snaptrade/holdings/refresh`): `force_reactivate=True`

The function threads this through to each `ensure_data_source()` call in its loop.

CSV import (`import_portfolio.py:182`) does NOT pass `force_reactivate` — CSV data_sources are managed separately and don't correspond to API connections.

**Critical ordering:** Phase 4 must ship together with Phase 2. Without it, reconnecting a previously disconnected source would leave it stuck as 'disconnected'.

### Phase 5: Inject Deactivation into Disconnect/Delete/Recovery

All paths use **deactivate-after**: deactivate AFTER the remote/destructive operation succeeds. Deactivation failure propagates (raises) — it must NOT be swallowed by existing inner try/except blocks.

**Critical implementation rule:** Each deactivation call must be placed OUTSIDE any existing best-effort try/except blocks in the handler. The existing disconnect handlers have inner try/except blocks for non-fatal cleanup (provider_items, position deletion). Deactivation must not land inside these. If the handler's structure requires it, extract the deactivation into a separate block at the same level as the main success path.

**Why deactivate-after universally:** The alternative (deactivate-first) creates sticky false-negatives if the remote call fails afterward — the upsert guard (Phase 2) prevents self-healing, so the data_source stays 'disconnected' even though the upstream connection is still alive. Deactivate-after avoids this: the most common failure mode (remote API failure) leaves state consistent. The rare failure mode (local DB write after remote success) gets CRITICAL log + admin repair (Phase 7).

**5a.** Plaid single-item disconnect (`plaid.py`, inside existing `if item_id:` block at line 1588, BEFORE `delete_provider_item()`):

Remote disconnect (line 1575) and token deletion (line 1578) already succeeded. Deactivate, then delete provider_items:

```python
registry = AccountRegistry(user["user_id"])
registry.deactivate_data_source("plaid", provider_item_id=item_id)
db_client.delete_provider_item(user["user_id"], "plaid", item_id)
```

**5b.** Plaid full delete (`plaid.py`, AFTER `delete_plaid_user_tokens()` at line 1689 and `delete_provider_positions()` at line 1697):

Tokens and positions already deleted. Deactivate all Plaid data_sources:

```python
registry = AccountRegistry(user["user_id"])
registry.deactivate_all_provider_data_sources("plaid")
```

Provider_items cleanup — new best-effort block after deactivation. Uses existing guarded `delete_provider_item()` (database_client.py:1371) in a loop:
```python
try:
    with get_db_session() as conn:
        db_client = DatabaseClient(conn)
        items = db_client.list_provider_items_for_user(user["user_id"], "plaid")
        for item in items:
            item_id = str(item.get("item_id") or "").strip()
            if item_id:
                db_client.delete_provider_item(user["user_id"], "plaid", item_id)
except Exception as pi_error:
    portfolio_logger.warning("Plaid provider_items cleanup failed (non-fatal): %s", pi_error)
```

**5c.** SnapTrade single-connection remove (`snaptrade.py`, AFTER `remove_snaptrade_connection()` at line 1083):

API removal succeeded. Deactivate:

```python
registry = AccountRegistry(user["user_id"])
registry.deactivate_data_source("snaptrade", provider_item_id=authorization_id)
```

**5d.** SnapTrade full delete (`snaptrade.py`, AFTER `delete_snaptrade_user()` and `delete_provider_positions()` at line ~1202):

API deletion and position cleanup succeeded. Deactivate all:

```python
registry = AccountRegistry(user["user_id"])
registry.deactivate_all_provider_data_sources("snaptrade")
```

**5e.** SnapTrade Tier 2 recovery (`recovery.py`, AFTER `_delete_snap_trade_user_with_retry()` at line 143 and `delete_provider_positions()` at line 157):

API deletion and position cleanup succeeded. Deactivate all before re-registration:

```python
from services.account_registry import AccountRegistry
registry = AccountRegistry(user_id)
registry.deactivate_all_provider_data_sources("snaptrade")
```

After Tier 2 recovery completes, there are zero active SnapTrade data_sources (`connections_preserved=False`). New data_source rows are only created when the user later reconnects a brokerage via SnapTrade.

### Phase 6: Stale Row Reconciliation in Sync Functions

Opportunistic cleanup: deactivate data_source rows whose `provider_item_id` is not in the live set. **Only runs when the live set is non-empty** — neither provider's empty result is authoritative:

- **Plaid**: `list_provider_items_for_user()` returns [] on transient failures, missing table, or lazy backfill not yet run.
- **SnapTrade**: `list_snaptrade_connections()` returns [] when the local secret is missing (credential loss), not just when no connections exist.

Empty-set deactivation is handled by the disconnect/delete paths (Phase 5), not by reconciliation.

**6a.** `_sync_plaid_data_sources()` (`plaid.py`, after the for loop ~line 353):

Only runs when `provider_items` is non-empty (early return at line 332 skips this). Build `live_item_ids` set, then:
```sql
UPDATE data_sources SET status='disconnected', user_deactivated=TRUE, updated_at=NOW()
WHERE user_id=%s AND provider='plaid' AND provider_item_id IS NOT NULL
  AND user_deactivated=FALSE AND provider_item_id != ALL(%s)
```

**6b.** `_sync_snaptrade_data_sources()` (`snaptrade.py`, after the for loop ~line 335):

Only runs when `connections` is non-empty (early return at line 314 skips this). Build `live_auth_ids` set, then:
```sql
UPDATE data_sources SET status='disconnected', user_deactivated=TRUE, updated_at=NOW()
WHERE user_id=%s AND provider='snaptrade' AND provider_item_id IS NOT NULL
  AND user_deactivated=FALSE AND provider_item_id != ALL(%s)
```

### Phase 7: One-Time Stale Row Cleanup Script

**New file:** `scripts/cleanup_stale_data_sources.py`

Admin-reviewed script for post-deploy cleanup of pre-existing orphaned data_source rows. Does NOT automate staleness detection (neither `provider_items` nor `list_snaptrade_connections()` is authoritative — both return [] on transient failures). Instead:

1. Lists all active data_source rows with `user_id`, `provider`, `provider_item_id`, `institution_slug`, `last_sync_at`, `created_at`.
2. Admin reviews and provides a list of data_source IDs to deactivate.
3. `--deactivate 1,2,3` flag to apply.

The script is a diagnostic tool, not an automated fixer. The admin uses context (which users have active connections, which providers are configured) to decide what's stale.

### Phase 8: Status-Aware Registry Queries

**`services/account_registry.py`:**

- `_get_unique_data_source_id()` (line 628): add `AND status = 'active'` to WHERE clause
- `link_accounts_to_data_source()` (line 165): add `AND status = 'active'` to the data_source lookup query
- `link_accounts_to_data_source()` (line 181): add `AND status = 'active'` to the COUNT query

## Tests

| Test | File | What it proves |
|------|------|---------------|
| `test_upsert_guard_preserves_deactivated_status` | `tests/inputs/test_database_client.py` | ON CONFLICT doesn't overwrite status when user_deactivated=TRUE |
| `test_upsert_overwrites_status_when_not_deactivated` | same | ON CONFLICT sets status normally when user_deactivated=FALSE |
| `test_deactivate_by_provider_item_id` | same | Targeted deactivation by provider+item_id |
| `test_deactivate_provider_wide` | same | Provider-wide deactivation (no item_id) |
| `test_deactivate_skips_already_deactivated` | same | Idempotent — doesn't re-deactivate |
| `test_reactivate_clears_flag` | same | Reactivation sets status='active', user_deactivated=FALSE |
| `test_ensure_data_source_force_reactivate` | `tests/services/test_account_registry.py` | force_reactivate=True triggers reactivation on deactivated row |
| `test_ensure_data_source_no_reactivate_without_flag` | same | Default behavior doesn't reactivate |
| `test_get_unique_data_source_ignores_inactive` | same | Returns active row when inactive+active coexist |
| `test_link_accounts_ignores_inactive` | same | COUNT=1 when inactive+active coexist |
| `test_plaid_disconnect_deactivates` | `tests/routes/test_plaid_disconnect.py` | Single-item disconnect sets user_deactivated=TRUE |
| `test_plaid_full_delete_deactivates_all` | same | Full delete deactivates all Plaid data_sources + cleans provider_items |
| `test_snaptrade_remove_deactivates` | `tests/routes/test_snaptrade_disconnect.py` | Single-connection remove deactivates by authorization_id |
| `test_snaptrade_full_delete_deactivates_all` | same | Full delete deactivates all SnapTrade data_sources |
| `test_snaptrade_recovery_tier2_deactivates` | `tests/brokerage/test_snaptrade_recovery.py` | Tier 2 recovery deactivates before re-registration |
| `test_plaid_sync_reconciles_stale_rows` | `tests/routes/test_plaid_sync.py` | Sync deactivates rows not in provider_items |
| `test_snaptrade_sync_reconciles_stale_rows` | `tests/routes/test_snaptrade_sync.py` | Sync deactivates rows not in API connections |
| `test_plaid_reconnect_reactivates` | `tests/routes/test_plaid_reconnect.py` | exchange_token_callback with force_reactivate clears user_deactivated |
| `test_mcp_plaid_completion_reactivates` | `tests/mcp_tools/test_connections.py` | `_best_effort_finalize_plaid_connection` passes force_reactivate=True |
| `test_mcp_snaptrade_completion_reactivates` | `tests/mcp_tools/test_connections.py` | SnapTrade completion passes force_reactivate=True |
| `test_plaid_sync_no_reconcile_on_empty_set` | `tests/routes/test_plaid_sync.py` | Empty provider_items → no deactivation (non-authoritative) |
| `test_snaptrade_sync_no_reconcile_on_empty_set` | `tests/routes/test_snaptrade_sync.py` | Empty connections → no deactivation (non-authoritative, could be credential loss) |
| `test_reconciliation_skips_already_deactivated` | `tests/routes/test_plaid_sync.py` | Rows with user_deactivated=TRUE are not re-deactivated |
| `test_snaptrade_passive_fetch_no_reactivate` | `tests/routes/test_snaptrade_sync.py` | Passive GET holdings passes force_reactivate=False to _sync_snaptrade_data_sources |
| `test_snaptrade_explicit_refresh_reactivates` | `tests/routes/test_snaptrade_sync.py` | Explicit POST refresh passes force_reactivate=True to _sync_snaptrade_data_sources |

Also update existing test dummies in `tests/mcp_tools/test_connections.py` (lines 478, 589): add `force_reactivate=False` kwarg to `_DummyRegistry.ensure_data_source()` to match the new signature.

**Total: 25 new tests + 2 existing test fixture updates.**

## Verification

1. Run migration against local DB
2. Run all existing tests — no regressions (the guard is backward-compatible: `user_deactivated=FALSE` on all existing rows means CASE falls through to EXCLUDED.status, same as before)
3. Run all 25 new tests
4. Manual: connect Plaid → verify data_source created with status='active'
5. Manual: disconnect Plaid → verify data_source status='disconnected', user_deactivated=TRUE
6. Manual: reconnect same Plaid item → verify status='active', user_deactivated=FALSE
7. Manual: passive holdings fetch (GET) → verify deactivated row is NOT re-activated
8. Manual: explicit holdings refresh (POST) → verify deactivated row IS re-activated (force_reactivate=True)
8. After this ships, F16 (CSV collision guard) can be built on top — single-tier check against `data_sources WHERE status='active'`
