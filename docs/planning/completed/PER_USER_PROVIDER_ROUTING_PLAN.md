# Fix: Per-user provider awareness in routing layer (fixes silent Schwab row loss, multi-user safe)

## Context

**Symptom (from `docs/TODO.md:1278-1313`, logged 2026-04-10):** A user with direct Schwab OAuth has a healthy provider — `SchwabPositionProvider().fetch_positions(...)` returns 17 live rows. But `PositionService.refresh_provider_positions('schwab')` returns an empty DataFrame. The 17 rows are fetched successfully and then silently filtered away by `partition_positions(df, 'schwab')` at `services/position_service.py:2242`.

**Root cause — two layers, both need fixing:**

**Layer 1 — stale config value.** `config/routing.yaml` says `positions.charles_schwab: snaptrade`. This reflects a past setup where Charles Schwab positions flowed through SnapTrade. The user is now on direct Schwab OAuth but the yaml was never updated. Note: the split-routing design (one provider for positions/reads, another for trades/writes) is a deliberate, supported pattern — only the specific value for `positions.charles_schwab` is out of date.

**Layer 2 — routing layer is globally-scoped instead of user-scoped.** `providers/routing.py:is_provider_available(provider)` at line 302 checks only host-level env vars and a single global `~/.schwab_token.json` file at line 321. `SchwabPositionProvider.fetch_positions()` at `providers/schwab_positions.py:68` explicitly ignores `user_email` (`del user_email, kwargs` at line 74). So once a Schwab token exists on the host, every user on that host is considered to "have" Schwab from routing's perspective — which is incorrect for multi-user.

**Why just flipping the yaml isn't safe (Codex review FAILed the previous plan):** A global `charles_schwab: snaptrade → schwab` flip makes `institution_belongs_to_provider("Charles Schwab", "snaptrade", "positions")` return False for *every* user on the host (because `is_provider_available("schwab")` returns True globally). A SnapTrade-only Schwab user's SnapTrade-aggregated Charles Schwab rows would then get silently filtered out on every read partition path, and `get_all_positions()` would try to fetch from direct Schwab even for users who never connected it. One user's config choice would break every other user's reads.

**Scope of the bug today.** `partition_positions` is called on **every code path** that loads Schwab positions (8 callsites in `services/position_service.py`: lines 610, 1084, 1114, 1133, 1149, 1178, 1207, 1250, 2242). So the reported `refresh_provider_positions('schwab')` symptom is just the tip — `get_positions('schwab', force_refresh=True)`, `POST /refresh-schwab-holdings` (at `routes/onboarding.py:635`), `get_all_positions()` fanout, Celery Beat auto-sync (`workers/tasks/positions.py:46`), and `get_cached_positions` are all affected. A correct fix needs to cover them uniformly, not just the one site named in the TODO.

**Infrastructure already in place for the fix:**
- `services/position_service.py:970-1042` — `_get_scoped_position_providers()` already queries per-user connected providers via `db_client.get_user_accounts(user_id)` (which joins `accounts` ↔ `data_sources`). It returns `{"snaptrade"}` for a SnapTrade-only user, `{"schwab"}` for a direct-Schwab user, etc. This is the exact signal the routing layer needs — it just isn't threaded into `is_provider_available` or `institution_belongs_to_provider` yet.
- `database/schema.sql:92-105` — `data_sources` table has `(user_id, provider, status, user_deactivated)` columns. `inputs/database_client.py:1365-1392` exposes `get_user_accounts(user_id, active_only=True)` which joins through and yields `data_source_provider` per account. We can reuse this directly.
- `providers/routing_config.py:244-248` — `_POSITION_ROUTING_DEFAULTS = {"charles_schwab": "schwab", "interactive_brokers": "ibkr"}`. The hard-coded default is already correct; `routing.yaml` is just overriding it to the stale value.

**Desired outcome (all three user shapes behave correctly):**
1. **Direct-Schwab user:** `get_positions('schwab')` returns the 17 rows. No silent drop. Fanout via `get_all_positions()` includes Schwab direct rows and dedupes any SnapTrade-aggregated Charles Schwab rows against them.
2. **SnapTrade-only Schwab user:** SnapTrade fetch returns Charles Schwab rows, they survive partition (because this user has no direct Schwab connection in `data_sources`, so `is_provider_available("schwab", user_id=X)` returns False, and routing falls back to defaults → snaptrade kept).
3. **Dual-connection user** (has both direct Schwab AND SnapTrade with Charles Schwab): direct Schwab rows kept, SnapTrade's Charles Schwab rows dropped at partition (correct dedup — direct wins per the routing config).

---

## Approach — Option C: Thread per-user provider awareness through the routing layer

**Six phases, in order.** Phases 1-5 ship as one commit; Phase 6 is a separate followup.

**Key design decision (from Codex round 2 review, Finding 1):** Do NOT overload `is_provider_available` with user semantics. Keep `is_provider_available(provider)` pure (global runtime: creds + token exist). Add a NEW composite helper `is_provider_routable_for_user(provider, user_id)` = `is_provider_available(provider) AND is_user_connected_to_provider(user_id, provider)`. Routing-decision code uses the composite; provider registration keeps using the pure global check. This avoids the bug where a user with an active `data_sources` row but a missing host token would see SnapTrade Schwab rows dropped while Schwab direct isn't even registered to fetch.

### Phase 1 — Add per-user primitives (DatabaseClient + routing helper)

**Files:** `inputs/database_client.py`, `providers/routing.py`

**1a. New helper `DatabaseClient.is_user_connected_to_provider(user_id, provider) -> bool`** in `inputs/database_client.py`:
- Single lightweight query: `SELECT 1 FROM data_sources WHERE user_id = %s AND provider = %s AND status = 'active' AND COALESCE(user_deactivated, FALSE) = FALSE LIMIT 1`
- Predicate standardized to match existing usage in `routes/_sync_helpers.py:43` and `services/sync_status_service.py:176` (per Codex Finding 3).
- Returns `True` iff a row exists; `False` otherwise.

**1b. New helper `is_provider_routable_for_user(provider, user_id)` in `providers/routing.py`:**
- If `user_id is None` → return `is_provider_available(provider)` (backward-compat fallthrough).
- If `is_db_available()` is False → return `is_provider_available(provider)` (no-DB mode inherits global semantics; documented).
- Otherwise: return `is_provider_available(provider) AND db_client.is_user_connected_to_provider(user_id, provider)`.
- **Wrap the DB query in try/except** (Codex round-3 Finding 2): if the `is_user_connected_to_provider` query raises (transient DB error, connection drop), catch the exception, log a warning, and fall back to `is_provider_available(provider)`. Do NOT let a transient DB blip fail partitioning on every row of a position fetch.
- **Do NOT modify `is_provider_available`** — it keeps its current pure-global meaning, which is what `services/position_service.py:170-205` provider-registration gates need.

### Phase 2 — Thread `user_id` into routing-decision functions

**Files:** `providers/routing.py`

Add optional `user_id=None` parameter to the four routing *decision* functions and have them use `is_provider_routable_for_user` instead of `is_provider_available` where the decision depends on the user's connection state:

- **`institution_belongs_to_provider(institution_name, provider, data_type, user_id=None)`** at line 403: replace the `is_provider_available(canonical)` check at line 434 with `is_provider_routable_for_user(canonical, user_id)`. All other branches unchanged.
- **`partition_positions(df, provider, user_id=None)`** at line 441: thread `user_id` into `institution_belongs_to_provider` inside the `.apply` lambda. Pre-compute once before the apply (don't re-query per row).
- **`get_required_providers(data_type, user_id=None)`** at line 362: replace **all** `is_provider_available` calls inside this function with `is_provider_routable_for_user(..., user_id)` — including the canonical-provider loop branch, the defaults loop, and the fail-open fallback at line 399 (Codex round-3 non-blocking recommendation: don't miss any branch). This prevents `get_all_positions()` from auto-adding direct `schwab` to `providers_to_fetch` for users who don't have it.
- **`resolve_providers_for_institution(institution, data_type, user_id=None)`** at line 183: replace the three `is_provider_available` calls (lines 197, 206, 216) with `is_provider_routable_for_user(..., user_id)`. This is the fix for Codex Finding 2 — the scope-narrowing callers in filtered views all eventually route through this function.

**Still do NOT change** `_enabled_capable_providers`, `_validated_default_providers`, or the registration gate at `services/position_service.py:170-205`. Those remain global (correctly).

### Phase 3 — Update `services/position_service.py` callsites

**Files:** `services/position_service.py`

**Pattern:** add `user_id=self._get_user_id()` to all 8 `partition_positions` callsites and the 1 `get_required_providers` callsite. Wrap each `self._get_user_id()` call in a try/except that falls back to `user_id=None` (global) on lookup failure — don't regress no-DB mode or user-not-found edge cases.

**Specific lines to edit:**
- Line 610 (`get_cached_positions`): `partition_positions(df, provider, user_id=self._get_user_id())`
- Line 656: `get_required_providers("positions", user_id=self._get_user_id())`
- Lines 1084, 1114, 1133, 1149, 1178, 1207 (all within `_get_positions_df`): same pattern
- Line 1250 (`_load_store_positions`): same pattern
- Line 2242 (`refresh_provider_positions`): **delete this line entirely** — this is the Option B safety net (see Phase 5). The explicit-refresh contract doesn't need partition.

**Add per-user availability cache** — to avoid re-querying `data_sources` on every partition operation during a single `get_all_positions()` fanout — add an instance attribute to `PositionService.__init__`:

```python
self._provider_routable_cache: dict[tuple[int, str], bool] = {}
```

Pass it down via a small wrapper (e.g., `self._partition(df, provider)`) that resolves user_id once, consults the cache, and calls the underlying `partition_positions(df, provider, user_id=...)`. The routing layer itself stays cache-agnostic; the cache lives at the service layer where request lifecycle is well-defined (fresh PositionService instance per request/task — confirmed in Codex round-2 review against `workers/tasks/positions.py:45`, `mcp_tools/positions.py:568`, `routes/positions.py:385`, `services/position_snapshot_cache.py:89`).

**Phase 3b — Explicit-provider access guard (Codex round-3 Finding 1)**

The routing-layer fix above makes `get_all_positions()` fanout user-safe, but three explicit-provider entry points still accept a hardcoded provider name and return whatever the global provider implementation fetches — independent of per-user routing. Because `SchwabPositionProvider.fetch_positions()` at `providers/schwab_positions.py:68-74` explicitly ignores `user_email`, a user who calls `get_positions("schwab")` but has no Schwab `data_sources` row would receive the host operator's Schwab data. With Phase 6's `canonical == provider` short-circuit in `partition_positions`, the row-level partition check also *keeps* these rows for the wrong user. This is a cross-user data leak.

Add a private gate method to `PositionService`:

```python
def _require_provider_routable_for_user(self, provider: str) -> None:
    """Raise ProviderNotConnectedError if this user isn't connected to `provider`.
    No-op in backward-compat cases (user_id unresolvable, DB unavailable)."""
    if provider == "csv":
        return
    try:
        user_id = self._get_user_id()
    except Exception:
        return  # backward compat: no user context → preserve current behavior
    from database import is_db_available
    if not is_db_available():
        return  # no-DB mode → fall through
    from providers.routing import is_provider_routable_for_user
    if not is_provider_routable_for_user(provider, user_id=user_id):
        raise ProviderNotConnectedError(
            f"User {user_id} is not connected to provider '{provider}'"
        )
```

Add `ProviderNotConnectedError` exception class at top of `services/position_service.py`.

Call the guard at the start of all four explicit-provider methods:
- `get_positions(provider, ...)` at line 527 — just after `provider = provider.lower().strip()`
- `get_cached_positions(provider, ...)` at line 582 — same position
- `refresh_provider_positions(provider)` at line 2219 — same position
- `fetch_schwab_positions()` at line 513 — hardcodes `"schwab"` and bypasses the other three entry points. Either delegate through `get_positions("schwab", ...)` (preferred — removes duplication) or call `self._require_provider_routable_for_user("schwab")` before `_invoke_get_positions_df(...)`. No in-repo callers today (per Codex round-4 audit), so this is cleanup for completeness.

**CSV exemption note** (Codex round-4 recommendation): the guard skips `provider == "csv"` because `CSVPositionProvider` at `providers/csv_positions.py:20,98` ignores `user_email` and reads a host-global `positions.json`. Exempting csv preserves current single-user/global CSV semantics — it does NOT make CSV multi-user safe. That's a separate followup; the plan is explicit about not addressing it here.

**IBKR implication**: `providers/ibkr_positions.py:118` also ignores `user_email` (same shape as Schwab). The generic guard automatically protects IBKR too — any call to `get_positions("ibkr")` from a user without an IBKR `data_sources` row will raise `ProviderNotConnectedError`. Phase 7's per-user token migration work will need to cover both Schwab and IBKR.

**Also update the three upstream callers** that hardcode `"schwab"` and would now receive a `ProviderNotConnectedError` for non-Schwab users. Each should catch the exception and handle it gracefully (empty result for UI surfaces, skip for workers):

- `mcp_tools/positions.py:82` (`_refresh_and_load_positions`) — catch `ProviderNotConnectedError` and return the current `get_all_positions()` result without the refresh step. Same pattern at `mcp_tools/positions.py:600` if it also calls `refresh_provider_positions`.
- `routes/onboarding.py:635` (`POST /refresh-schwab-holdings`) — catch the error and return a 409 `{status: "not_connected", provider: "schwab"}` JSON body. Clients can then hide or grey-out the Schwab refresh button.
- `workers/tasks/positions.py:46` (`sync_positions` Celery task) — catch the error and return `{skipped: True, reason: 'not_connected'}` from the task. **Do NOT call `record_failure` or any sync_status helper** — per Codex round-4 Finding 2, the current sync-status API only has `record_success()` and `record_failure()` (`services/sync_status_service.py:127, 185`), and `FreshnessPolicy` at `services/freshness_policy.py:68` keys off `ok`/`degraded`/`offline`/`unknown`. Adding a new status would require auditing every freshness consumer. Leave `sync_status` untouched for the skipped case; rely on the job-state `skipped` and the per-user `data_sources` row (which is already the source of truth). If a future need arises, add a dedicated `record_skipped()` helper in a separate change. Do NOT open the circuit; the task didn't fail, the user just isn't enrolled.
- `services/sync_runner.py:235` — `_store_payload()` currently logs warnings on non-success returns. Handle `skipped`/`not_connected` specially so they don't log as warnings (Codex round-4 non-blocking recommendation).

**Replace `routes/onboarding.py:_schwab_token_exists()`** at line 52 with a user-scoped helper:

```python
def _schwab_connected_for_user(user_id: int) -> bool:
    """Return True iff this user has both a routable Schwab connection AND
    the host-level Schwab token. Replaces the global _schwab_token_exists."""
    from database import is_db_available
    from providers.routing import is_provider_routable_for_user
    if not is_db_available():
        return _schwab_token_exists_global()  # fallback to old behavior in degraded mode
    return is_provider_routable_for_user("schwab", user_id=user_id)
```

Keep the old `_schwab_token_exists` as `_schwab_token_exists_global()` internal for the no-DB fallback, or inline the `os.path.exists(...)` check. Update the two call sites (lines 419, 475) to pass `user["user_id"]`. Update the two test monkeypatches in `tests/routes/test_onboarding.py:952, 1125` to mock the new helper.

**Also audit `mcp_tools/connection_status.py`** (Codex round-4 non-blocking recommendation): it currently uses global Schwab token-file semantics for connection reporting. If we want all Schwab connection reporting to become per-user at the same time, update this tool to use `is_provider_routable_for_user` too. Optional for this plan — if not done here, file as an explicit followup.

### Phase 4 — Fix user-aware scope narrowing in filtered views (Codex round-2 Finding 2)

**Files:** `services/portfolio_scope.py` (new shared helper), `routes/positions.py`, `services/performance_helpers.py`, `actions/income_projection.py`, `mcp_tools/metric_insights.py`

Four callsites currently narrow to a single provider *before* `PositionService` partitions — they use identical `_resolve_scope_provider(scope)` helper duplicates that call `get_canonical_provider` + `resolve_provider_token` from global routing, then pass the narrowed provider into `get_position_result_snapshot(provider=...)`. A SnapTrade-only user with Charles Schwab via SnapTrade would miss those views because the narrowing happens upstream of the partition layer Phase 2+3 fixes.

**Add a shared user-aware helper** `resolve_scope_provider_for_user(scope, user_id) -> str | None` in `services/portfolio_scope.py` (next to the existing `resolve_portfolio_scope`, which this module already owns):

```python
def resolve_scope_provider_for_user(scope, user_id: int | None) -> str | None:
    """
    Return the single provider that should serve all accounts in `scope`,
    or None if the narrowing is unsafe (multiple providers, or the canonical
    provider isn't routable for this user — in which case the caller should
    fall back to the broader fanout path).
    """
```

Inside the helper: do the same slug → canonical lookup as today, but:
1. For each resolved canonical provider, call `is_provider_routable_for_user(canonical, user_id)`. If False, return None (force fanout fallback).
2. Only return a narrowed provider name if (a) the scope collapses to exactly one provider AND (b) that provider is routable for the user.

**Replace** the four duplicated `_resolve_scope_provider` inline helpers with calls to this shared helper, passing the user_id already in scope at each callsite:

- **`routes/positions.py:359-380`** — refactor the inline provider-narrowing loop inside `_load_filtered_accounts_positions` (or whatever it's named) to call `resolve_scope_provider_for_user(scope, user["user_id"])`. The existing fallback-to-fanout path stays intact for the `None` return case.
- **`services/performance_helpers.py:24-36`** — replace `_resolve_scope_provider` with a thin call to the shared helper. User_id is already in scope at line 72 (`resolve_user_id(user)`); pass it down to `_resolve_scope_provider(scope, user_id)` at line 98, or delete the local helper entirely.
- **`actions/income_projection.py:67-79`** — same pattern. User_id is in scope at line 105 (`context.user_id`).
- **`mcp_tools/metric_insights.py:129-141`** — same pattern. User_id is in scope at line 147.
- **`mcp_tools/income.py:37-38`** — this is a *shim* that re-exports `actions.income_projection._resolve_scope_provider`. Update the shim to thread user_id through to the new shared helper, OR redirect it to call `services.portfolio_scope.resolve_scope_provider_for_user` directly. Do not leave the shim pointing at a stale function.

In each case, when the shared helper returns None, the caller passes `provider=None` to `get_position_result_snapshot` (as it does today for the `len(provider_names) != 1` case) and the broader fanout handles the read correctly.

### Phase 5 — Remove `partition_positions` from `refresh_provider_positions` (safety net)

**Files:** `services/position_service.py` line 2242

```python
def refresh_provider_positions(self, provider: str) -> pd.DataFrame:
    ...
    df = self._fetch_fresh_positions(provider)
    df = partition_positions(df, provider)   # ← DELETE this line
    df = self._resolve_missing_ticker_aliases(df)
    self._save_positions_to_db(df, provider)
    return df
```

Replace with a one-line comment:

```python
# Explicit single-provider refresh: trust the caller's provider name and save
# whatever this provider returned. Fanout/consolidation still partitions in
# _get_positions_df, so SnapTrade-side dedup is unaffected.
```

**Why keep this on top of the Phase 2+3 user-aware routing:** Phase 2+3 makes partition correct *when it runs*. Phase 5 makes the explicit-refresh contract explicit — the named caller should never have its rows second-guessed, regardless of future routing config drift. Defense-in-depth.

### Phase 6 — Flip `config/routing.yaml`: `positions.charles_schwab: snaptrade` → `schwab`

**Execution:** Use the `manage_brokerage_routing` MCP tool (`mcp_tools/brokerage_routing.py:124`):

```python
manage_brokerage_routing(
    action="set",
    data_type="positions",
    institution="charles_schwab",
    provider="schwab",
)
```

**Why this is now safe:** With user-aware routing from Phase 1+2+3+4, `institution_belongs_to_provider("Charles Schwab", "snaptrade", "positions", user_id=snaptrade_user)` traces as:
- canonical = "schwab"
- canonical != provider ("snaptrade")
- `is_provider_routable_for_user("schwab", user_id=snaptrade_user)` → checks `is_provider_available("schwab")` (True — global token exists) AND `is_user_connected_to_provider(snaptrade_user, "schwab")` (False — no row) → returns False
- → `return provider in defaults` → "snaptrade" in `{"snaptrade", "plaid"}` → True → **row kept**

And for the direct-Schwab user:
- canonical = "schwab" == provider → True → **row kept** (no routable check needed; short-circuits on equality)

And for the dual-connection user, SnapTrade Charles Schwab rows:
- canonical = "schwab" != provider ("snaptrade")
- `is_provider_routable_for_user("schwab", user_id=dual_user)` → global available AND user connected → True
- → return False → **row dropped** (correct dedup)

All three shapes work.

### Phase 7 (deferred, separate plan) — Migrate Schwab OAuth tokens from global file to per-user storage

**Out of scope for this plan.** The current `~/.schwab_token.json` single-file model is a pre-existing limitation that this fix does not introduce or depend on. With Phases 1-6, the routing layer is multi-user-safe *even though the token storage is still global*, because `is_provider_routable_for_user("schwab", user_id=X)` only returns True when X has both (a) a global Schwab token and (b) an explicit `data_sources` row for schwab — and for now, only the operator user creates that row.

**When to do Phase 7:** Before enabling direct Schwab for a second user. Until then, only one user on the host can have an active Schwab `data_sources` row, so the global token file is effectively single-user.

**Phase 7 scope preview (do not implement in this plan):**
- Move token from `~/.schwab_token.json` to `~/.schwab_tokens/<user_id>.json` or the `user_credentials` DB table
- Thread user_id into `brokerage/schwab/client.py:_token_path()` (line 93) and `_client_from_token_file()` (line 184)
- Make `SchwabPositionProvider.fetch_positions()` (`providers/schwab_positions.py:68-74`) actually use `user_email` instead of discarding it
- Update OAuth callback in `scripts/run_schwab.py` to associate the token with the authenticated user

Track as a TODO entry after this plan ships.

---

## Files to modify

| File | Change |
|---|---|
| `inputs/database_client.py` | Phase 1a: add `is_user_connected_to_provider(user_id, provider) -> bool` helper. |
| `providers/routing.py` | Phase 1b: add `is_provider_routable_for_user(provider, user_id)` composite helper. Phase 2: add optional `user_id` param to `institution_belongs_to_provider`, `partition_positions`, `get_required_providers`, `resolve_providers_for_institution`. `is_provider_available` stays unchanged (pure global). |
| `services/position_service.py` | Phase 3: thread `user_id` into 8 `partition_positions` callsites + 1 `get_required_providers` call. Add `_provider_routable_cache` attribute + small `_partition(df, provider)` wrapper. Phase 3b: add `ProviderNotConnectedError` exception + `_require_provider_routable_for_user` gate, called from `get_positions`, `get_cached_positions`, `refresh_provider_positions`. Phase 5: delete line 2242 partition call in `refresh_provider_positions`, replace with comment. Provider registration gate at lines 170-205 **stays unchanged** (still uses global `is_provider_available`). |
| `mcp_tools/positions.py` | Phase 3b: catch `ProviderNotConnectedError` in `_refresh_and_load_positions` at line 82 (and line 600 if relevant). On catch, fall through to cached `get_all_positions()` path without re-raising. |
| `routes/onboarding.py` | Phase 3b: replace global `_schwab_token_exists()` at line 52 with per-user `_schwab_connected_for_user(user_id)`. Update callsites at lines 419, 475. In `POST /refresh-schwab-holdings` at line 607-635, catch `ProviderNotConnectedError` and return a 409 `{status: "not_connected", provider: "schwab"}` response. |
| `workers/tasks/positions.py` | Phase 3b: catch `ProviderNotConnectedError` around `refresh_provider_positions(provider_key)` at line 46. Record sync-status as `skipped`/`not_connected`. Do not open the circuit. |
| `services/portfolio_scope.py` | Phase 4: add new shared helper `resolve_scope_provider_for_user(scope, user_id)`. |
| `routes/positions.py` | Phase 4: refactor inline provider-narrowing loop at lines 359-380 to use the new shared helper, passing `user["user_id"]`. |
| `services/performance_helpers.py` | Phase 4: replace local `_resolve_scope_provider` at lines 24-36 with shared helper; thread user_id through to the call at line 98. |
| `actions/income_projection.py` | Phase 4: replace local `_resolve_scope_provider` at lines 67-79 with shared helper; thread `context.user_id` through to the calls at lines 115 and 218. |
| `mcp_tools/metric_insights.py` | Phase 4: replace local `_resolve_scope_provider` at lines 129-141 with shared helper; thread `user_id` through to the call at line 169. |
| `mcp_tools/income.py` | Phase 4: update the shim at line 37 — either thread user_id through or redirect to `services.portfolio_scope.resolve_scope_provider_for_user` directly. |
| `tests/routes/test_onboarding.py` | Update monkeypatches at lines 952, 1125 to mock the new `_schwab_connected_for_user` helper instead of `_schwab_token_exists`. |
| `config/routing.yaml` | Phase 6: line 2 `charles_schwab: snaptrade` → `charles_schwab: schwab` (via `manage_brokerage_routing` tool, not manual edit). |
| `tests/services/test_position_service_provider_registry.py` | Update `test_refresh_provider_positions_applies_partition_routing` (rename + invert assertion to expect both rows saved). Update `test_get_positions_partitions_before_consolidation` at line 241 to monkeypatch routing + availability deterministically (Codex round 1 finding 2). Add new regression tests — see below. |
| `tests/providers/test_routing.py` (create if missing) | Unit tests for `is_provider_routable_for_user` + the new `user_id` parameter on `institution_belongs_to_provider`, `partition_positions`, `resolve_providers_for_institution`. Cover the three user shapes (direct-only, snaptrade-only, dual). |
| `tests/services/test_portfolio_scope.py` (create if missing) | Unit tests for the new `resolve_scope_provider_for_user` helper — cover all three user shapes + None fallback. |
| Filtered-view regression tests (Codex round 2 finding 2) | New tests in `tests/routes/test_positions_filtered.py` (or similar), `tests/services/test_performance_helpers.py`, `tests/actions/test_income_projection.py`, `tests/mcp_tools/test_metric_insights.py` — assert a SnapTrade-only-Charles-Schwab user can read filtered views without the row-drop bug. |
| `docs/TODO.md` | Mark bug entry at line 1278 as `DONE` with commit SHA. Add a follow-up entry for Phase 7 (per-user Schwab token migration). |

**Files referenced but NOT modified:**
- `brokerage/schwab/client.py`, `providers/schwab_positions.py` — Phase 7 territory, not touched in this plan
- `trading_analysis/data_fetcher.py:160, 722-729` — also calls `is_provider_available` from user-scoped *transaction* contexts. Same refactor pattern applies; deferred to a followup to keep this plan scoped to positions.
- `providers/routing_config.py` — `_POSITION_ROUTING_DEFAULTS` already has the right value
- `routes/onboarding.py`, `routes/plaid.py`, `routes/snaptrade.py`, `workers/tasks/positions.py`, `mcp_tools/positions.py` — fixed transitively by Phase 2+3+4+6

---

## Existing functions/utilities reused

| Name | Location | Purpose |
|---|---|---|
| `db_client.get_user_accounts` | `inputs/database_client.py:1365` | Reference for data_sources join pattern. Phase 1a's new helper uses a lighter-weight LIMIT 1 query. |
| `_get_scoped_position_providers` | `services/position_service.py:970` | Reference implementation showing the data_sources query pattern. Not called directly, but the approach is mirrored by the new composite helper. |
| `is_db_available` | `database/__init__.py` | Degraded-mode gate. Phase 1b uses this to decide between per-user DB query and global fallback. |
| `manage_brokerage_routing` | `mcp_tools/brokerage_routing.py:124` | Atomic yaml rewrite + cache install for Phase 6. |
| `_install_routing_cache`, `invalidate_routing_cache` | `providers/routing_config.py:377,384` | Test teardown hooks for routing-cache monkeypatching. |
| `partition_positions` | `providers/routing.py:441` | Same function, now with optional `user_id` parameter. |
| `resolve_portfolio_scope` | `services/portfolio_scope.py` | Existing module that `resolve_scope_provider_for_user` joins. |
| `PROVIDER_SCOPE_UNSET` sentinel and `_scoped_provider_filter` cache | `services/position_service.py` | Pattern to copy for `_provider_routable_cache`. |

---

## Verification (step-by-step)

1. **Pre-flight — confirm current broken state for direct-Schwab user:**
   ```python
   from services.position_service import PositionService
   from providers.schwab_positions import SchwabPositionProvider
   from providers.routing import partition_positions

   raw = SchwabPositionProvider().fetch_positions("henry.souchien@gmail.com")
   print(raw.shape)  # expected: (17, 13)
   print(partition_positions(raw, "schwab").shape)  # expected: (0, 13) ← current bug
   ```

2. **Apply Phases 1+2+3+4+5 code changes.**

3. **Verify with user_id threaded — direct-Schwab user:**
   ```python
   print(partition_positions(raw, "schwab", user_id=<henry_user_id>).shape)
   # expected: (17, 13) — user-aware check finds schwab in data_sources → canonical==provider → kept
   ```

4. **Simulate a SnapTrade-only user:**
   ```python
   # Use a different user_id that has only SnapTrade in data_sources
   snaptrade_rows_with_schwab = <mock df with brokerage_name='Charles Schwab' from snaptrade>
   print(partition_positions(snaptrade_rows_with_schwab, "snaptrade", user_id=<snaptrade_only_user_id>).shape)
   # expected: all rows kept — is_provider_routable_for_user("schwab", user_id=snaptrade_only) returns False → falls to defaults → snaptrade kept
   ```

5. **Apply Phase 6 (yaml flip):**
   ```python
   manage_brokerage_routing(action="set", data_type="positions", institution="charles_schwab", provider="schwab")
   ```

6. **Re-verify direct-Schwab user post-flip:**
   ```python
   invalidate_routing_cache()
   print(partition_positions(raw, "schwab", user_id=<henry_user_id>).shape)
   # expected: (17, 13)
   ```

7. **Verify the four filtered-view callsites (Phase 4).** For each of the four callsites, manually exercise a filtered view for both a direct-Schwab user and a SnapTrade-only user with Charles Schwab:
   - `routes/positions.py` — call the filtered-accounts endpoint with `account_filter=("Charles Schwab",)`
   - `services/performance_helpers.py` — trigger realized/hypothetical performance with a Schwab-filtered scope
   - `actions/income_projection.py` — run income projection with a Schwab-filtered portfolio
   - `mcp_tools/metric_insights.py` — run metric insights with a Schwab-filtered scope

   Both user shapes should see their Charles Schwab positions in each view.

8. **Run the targeted test suites:**
   ```bash
   pytest tests/providers/test_routing.py -v
   pytest tests/services/test_portfolio_scope.py -v
   pytest tests/services/test_position_service_provider_registry.py -v
   pytest tests/services/test_performance_helpers.py -v
   pytest tests/actions/test_income_projection.py -v
   pytest tests/mcp_tools/test_metric_insights.py -v
   pytest tests/routes/test_positions_filtered.py -v
   pytest tests/workers/test_positions_task.py -v
   pytest tests/routes/test_plaid_disconnect.py tests/routes/test_snaptrade_disconnect.py -v
   ```

9. **Live end-to-end via MCP tools:**
   ```python
   # Explicit refresh path (exercises Phase 5)
   service = PositionService(user_email="henry.souchien@gmail.com", user_id=<id>)
   df = service.refresh_provider_positions("schwab")
   assert len(df) == 17

   # Fanout path (exercises Phases 2+3+6)
   get_positions(institution="charles_schwab", force_refresh=True)
   # → should report 17 positions / ~$86k total, matching the Lane D 2026-04-09 live verification

   # Cached path (exercises Phase 3 callsite at line 610)
   get_positions(institution="charles_schwab", use_cache=True)
   # → same 17 rows from DB
   ```

10. **Celery worker smoke test** (this is what originally exposed the bug per TODO line 1294):
    - Trigger `workers.tasks.positions.sync_positions(user_id, "schwab")` via a one-off task or wait for next Beat tick
    - Confirm `refresh_provider_positions('schwab')` inside the task writes 17 rows to the DB (was 0 before the fix)
    - Check `schedule_logs` for success markers

11. **Update `docs/TODO.md`:** Mark the bug entry at line 1278 `DONE`. Add a new TODO for Phase 7 (per-user Schwab token migration) under an infrastructure section.

---

## New regression tests

**Routing layer (`tests/providers/test_routing.py`):**

1. **`test_is_provider_routable_for_user_needs_both_global_and_user`**:
   - Mock `is_provider_available("schwab")` True + `is_user_connected_to_provider(1, "schwab")` True → returns True
   - Mock global True + user False → returns False (Codex Finding 1: critical case)
   - Mock global False + user True → returns False
   - Mock with `user_id=None` → returns `is_provider_available` result (backward compat)

2. **`test_partition_positions_user_scoped_direct_schwab_only`**:
   - Monkeypatch routing yaml to `charles_schwab: schwab`
   - Mock `is_user_connected_to_provider(user_id=1, "schwab")` → True
   - Call `partition_positions(df, "schwab", user_id=1)` on Charles Schwab rows
   - Assert all rows kept

3. **`test_partition_positions_user_scoped_snaptrade_only_with_schwab_rows`**:
   - Monkeypatch routing yaml to `charles_schwab: schwab`
   - Mock `is_user_connected_to_provider(user_id=2, "schwab")` → False, `(2, "snaptrade")` → True
   - Call `partition_positions(df, "snaptrade", user_id=2)` on Charles Schwab rows from SnapTrade
   - Assert all rows kept (fallback to defaults)

4. **`test_partition_positions_user_scoped_dual_connection_dedups`**:
   - Monkeypatch routing yaml to `charles_schwab: schwab`
   - Mock `is_user_connected_to_provider(3, "schwab")` → True, `(3, "snaptrade")` → True
   - Call `partition_positions(df, "snaptrade", user_id=3)` on Charles Schwab rows from SnapTrade → assert dropped
   - Call `partition_positions(df, "schwab", user_id=3)` on Charles Schwab rows from direct Schwab → assert kept

5. **`test_partition_positions_no_user_falls_back_to_global`**:
   - Call `partition_positions(df, "schwab")` without `user_id`
   - Assert behavior matches pre-refactor global semantics (backward compat)

6. **`test_resolve_providers_for_institution_user_aware`**:
   - Monkeypatch routing yaml to `charles_schwab: schwab`
   - Mock a SnapTrade-only user
   - `resolve_providers_for_institution("Charles Schwab", "positions", user_id=2)` should return the SnapTrade fallback, NOT `["schwab"]` (Codex Finding 2: the upstream narrowing)

**Position service (`tests/services/test_position_service_provider_registry.py`):**

7. **`test_refresh_provider_positions_trusts_caller_provider`** (rename of existing test at line 275):
   - Assert that `refresh_provider_positions("snaptrade")` with mixed rows saves **all** rows, not just Merrill ones — proves the Phase 5 contract change.

8. **`test_get_positions_partitions_before_consolidation_deterministic`** (rewrite of existing test at line 241, per Codex round 1 finding 2):
   - Monkeypatch `providers.routing.get_position_routing` and `providers.routing.is_provider_routable_for_user` directly so the test doesn't depend on CI env state.

**Portfolio scope helper (`tests/services/test_portfolio_scope.py`):**

9. **`test_resolve_scope_provider_for_user_direct_only`**: single-account Schwab scope + direct-Schwab user → returns `"schwab"`.

10. **`test_resolve_scope_provider_for_user_snaptrade_only_returns_none`**: single-account Schwab scope + SnapTrade-only user → returns `None` (forces fanout fallback).

11. **`test_resolve_scope_provider_for_user_dual_connection`**: single-account Schwab scope + dual-connection user → returns `"schwab"` (direct wins).

12. **`test_resolve_scope_provider_for_user_multi_account_returns_none`**: multi-account scope (Schwab + Merrill) → always returns `None`.

**Filtered-view regression tests (Codex round-2 Finding 2):**

13. **`test_positions_filtered_snaptrade_only_user_charles_schwab`** — SnapTrade-only user with Charles Schwab via SnapTrade should get their rows through the filtered route at `routes/positions.py`. **Data-dependent (Codex round-3 recommendation):** wire the test so `provider="schwab"` would return empty/wrong data and `provider=None` returns the user's actual SnapTrade Charles Schwab rows. The test must prove the fallback matters, not just that the argument is None.

14. **`test_performance_helpers_snaptrade_only_user_charles_schwab`** — same shape for `services/performance_helpers.py`. Same data-dependent assertion.

15. **`test_income_projection_snaptrade_only_user_charles_schwab`** — same shape for `actions/income_projection.py`.

16. **`test_metric_insights_snaptrade_only_user_charles_schwab`** — same shape for `mcp_tools/metric_insights.py`.

17. **`test_resolve_scope_provider_for_user_dual_same_institution_edge`** (Codex round-3 non-blocking recommendation) — edge case: a dual-connection user with a filtered scope whose single institution slug (Charles Schwab) has accounts under BOTH the direct and aggregator provider. Confirm the helper behaves consistently: either it returns a narrowed provider and the downstream partition dedups correctly, or it returns None and the fanout handles it. Flag during implementation whether account-level provider provenance is needed (if it is, the helper signature will need to take the account → data_source mapping, not just the institution slug).

**Explicit-provider guard tests (Phase 3b):**

18. **`test_get_positions_rejects_unconnected_provider`** — PositionService for a SnapTrade-only user calls `get_positions("schwab")` → raises `ProviderNotConnectedError`. Confirms no cross-user data access.

19. **`test_refresh_provider_positions_rejects_unconnected_provider`** — same, for `refresh_provider_positions("schwab")`.

20. **`test_explicit_provider_guard_noop_when_no_user_id`** — backward compat: guard does not raise when `self._get_user_id()` fails (no DB, missing user, etc.).

21. **`test_mcp_refresh_gracefully_handles_unconnected`** — the `mcp_tools/positions.py:82` caller catches `ProviderNotConnectedError` and falls through to the cached `get_all_positions()` path without raising upstream.

22. **`test_schwab_refresh_route_returns_409_for_unconnected`** — the `/refresh-schwab-holdings` route returns the 409 `{status: "not_connected"}` body for a user who isn't connected, instead of leaking the operator's data.

23. **`test_celery_sync_schwab_skipped_for_unconnected_user`** — the `workers/tasks/positions.py:46` task catches the error, records `status='skipped', reason='not_connected'`, and doesn't open the circuit.

---

## Risks / Open questions

- **Semantic separation enforced.** `is_provider_available` stays pure (global runtime: token/creds exist). `is_provider_routable_for_user` is the composite that routing decisions use. Provider registration at `services/position_service.py:170-205` keeps using the pure global check. This avoids the Codex round-2 Finding 1 mismatch (active user row but missing host token). If someone adds a new routing-decision callsite in the future, they must use the composite — add a unit test guarding this.

- **Degraded no-DB mode.** When `is_db_available()` returns False, `is_provider_routable_for_user(provider, user_id)` falls back to the pure `is_provider_available(provider)` check. This preserves current no-DB-mode behavior but means no-DB-mode inherits the pre-fix host-level semantics. Acceptable — no-DB mode is a degraded mode, not production.

- **Cache coherency.** The new `_provider_routable_cache` on PositionService is per-instance. Instances are short-lived (one per request on routes, one per Celery task — confirmed in Codex round 2 review against `workers/tasks/positions.py:45`, `mcp_tools/positions.py:568`, `routes/positions.py:385`, `services/position_snapshot_cache.py:89`). No cross-request cache invalidation needed.

- **Transaction path deferred.** `is_provider_available` callers at `trading_analysis/data_fetcher.py:160, 722-729` are still global-scoped. Same refactor pattern applies but is deferred to a followup to keep this plan focused on positions.

- **`manage_brokerage_routing` is idempotent** (confirmed in Codex round 1 review) — safe to re-run. Cross-process cache staleness is bounded to ~2s by the mtime TTL at `routing_config.py:331`; Celery workers do NOT need a restart, but a task started inside that TTL could see stale routing. Acceptable.

- **Phase 7 (token migration) blocks onboarding a second direct-Schwab user.** Not blocked by this plan; just flagged as a followup. Creating a `data_sources` row for `(user_id=2, provider='schwab')` while the token is still at `~/.schwab_token.json` would give that user access to user_id=1's Schwab account — obviously wrong. The plan does NOT enable multi-user direct Schwab; it just makes the routing layer safe for the day when we do.

- **Scope-helper deduplication.** The four identical `_resolve_scope_provider` helpers being replaced with one shared helper in Phase 4 is a small bonus refactor. Verify during implementation that the four callers all share the same exact semantics — if any has drifted (edge-case behavior not captured in my read of the code), the shared helper needs to accommodate it or the caller keeps a thin wrapper.

---

## Out of scope

- Phase 7 (Schwab token per-user migration) — separate plan, explicitly deferred
- Threading user_id into transaction-path callers of `is_provider_available` (`trading_analysis/data_fetcher.py`) — same pattern, different bug surface
- Refactoring `_get_positions_df` to have a "named single-provider mode" vs "fanout mode" distinction (bigger change, not needed once Phases 2+3 fix routing)
- Auditing or refactoring the `_POSITION_ROUTING_DEFAULTS` vs `routing.yaml` split (separate hygiene concern)
- Adding a startup/CI check that `config/routing.yaml` matches `_POSITION_ROUTING_DEFAULTS` — nice-to-have, separate ticket
