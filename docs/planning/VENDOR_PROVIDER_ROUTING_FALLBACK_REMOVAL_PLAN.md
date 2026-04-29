# Vendor Provider Routing Fallback Removal — V1b

**Parent:** `docs/TODO.md` V1b — "Plaid fallback handlers in `routes/provider_routing.py` — implement or remove"
**Sibling plans:** V1 plaid (`VENDOR_PLAID_LOADER_SPLIT_PLAN.md`, shipped 2026-04-24) + V1 snaptrade (`VENDOR_SNAPTRADE_LOADER_SPLIT_PLAN.md`, shipped 2026-04-25). V1b is the cleanup that surfaced from V1 plaid R1.
**Date:** 2026-04-25
**Status:** Draft v3 (Codex R2 FAIL → §2/§3 wording fixed for consistency with the v2 tighter cut + new test edit; no scope change)

---

## 1. Problem

`routes/provider_routing.py` contains a generic "try provider A, fall back to provider B" routing chain that **was superseded by per-provider routing** (`providers/routing_config.py` + `services/position_service.py`) and never wired up. Specifically:

- The two public entry points — `get_holdings_with_fallback` (line 362) + `get_connections_with_fallback` (line 390) — have **zero callers across the entire codebase** (verified via grep across all `*.py`; only their own definitions match).
- The four provider wrappers they call — `_fetch_snaptrade_holdings` (:418), `_fetch_plaid_holdings` (:450), `_fetch_snaptrade_connections` (:459), `_fetch_plaid_connections` (:481) — are only reachable through those dead entry points.
- The `ProviderRouter.route_request()` method (:184) and its helpers `get_provider_priority_order` (:149) and `_update_provider_health` (:279) only support those dead entry points.
- The two Plaid wrappers currently `raise NotImplementedError` because V1 plaid (Codex R1) replaced their broken `ImportError`-ing bodies with explicit failures and deferred the real disposition decision to V1b.

The TODO note frames this as Plaid-only ("implement OR delete the Plaid branches"). Investigation shows the SnapTrade branches and the entire fallback machinery are equally dead — same superseded design. User confirmed (this session): "we decided to use proper routing rather than fallbacks."

What is **live** in `routes/provider_routing.py`:
- `provider_router` singleton (instance of `ProviderRouter`)
- `get_routing_status()` module-level helper — reads `provider_router.get_provider_status()`
- Both back `GET /api/provider-routing/status` (`routes/provider_routing_api.py:422`, registered in `app.py:7644`)

What is **dead** (Codex R1 confirmed via `rg`):
- The whole fallback machinery (entry points, wrappers, helpers, dataclasses) — see §4.2.
- `update_provider_configuration()` module-level wrapper at line 507 — zero Python callers.
- `ProviderRouter.update_provider_config()` instance method at line 323 — only called by the unused module-level wrapper above. Codex R1 recommended dropping both; this revision accepts that cut.

---

## 2. Goal

Delete the entire fallback machinery from `routes/provider_routing.py` in one pass. Keep only what backs the live status endpoint.

Target outcome:
- File shrinks from 525 LoC to ~165 LoC (rough estimate).
- `provider_router` singleton + `get_routing_status()` survive unchanged in observable behavior.
- `routes/provider_routing_api.py` is unaffected (no edits, no signature changes). `tests/routes/test_provider_routing_api.py` gains one new TestClient test for `/status` (per §5/§6) but pre-existing tests are untouched.
- No new lint baseline entries; no allowlist changes (this file is not in any vendor boundary allowlist — verified `tests/api_budget/_lint.py` has no `provider_routing` references).
- TODO V1b marked SHIPPED.

---

## 3. Non-Goals

This plan does **not**:
- Modify any other file's behavior. The only changes outside `routes/provider_routing.py` are: (a) the TODO marker in `docs/TODO.md`, and (b) one appended TestClient test in `tests/routes/test_provider_routing_api.py` covering the kept `/status` endpoint (§5, §6 step 2).
- Implement Plaid fallback (option (a) in the V1b TODO) — explicitly rejected.
- Touch `providers/routing_config.py`, `services/position_service.py`, or any code that does the live per-provider routing.
- Change the singleton interface used by the admin endpoint — `provider_router.get_provider_status()` keeps its current shape (the `/status` endpoint is the only consumer). `update_provider_config()` is dropped per §4.3 (no admin write endpoint exists).
- ~~Remove `update_provider_configuration()` (module-level) vs. `ProviderRouter.update_provider_config()` (instance method)~~ — both are now in scope for removal per Codex R1; see §4.3.
- Bump or modify any `_lint.py` baseline (Rule A/B vendor boundary linter has no entries for this file).
- Touch `frontend/openapi-schema.json` or `frontend/packages/chassis/src/types/api-generated.ts`. These reference `/api/provider-routing/*` routes only, not the dead Python symbols.

---

## 4. Target architecture

### 4.1 What survives in `routes/provider_routing.py`

```python
# Imports — pruned per §4.4
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
from utils.logging import portfolio_logger

# Enums + dataclass — kept (used by ProviderRouter.providers + .get_provider_status())
class ProviderStatus(Enum): ...
class ProviderPriority(Enum): ...
@dataclass
class ProviderConfig: ...

# Slimmed router class — only the status-read path
class ProviderRouter:
    def __init__(self): ...
    def _initialize_default_providers(self): ...
    def get_provider_status(self) -> Dict[str, Dict[str, Any]]: ...

provider_router = ProviderRouter()

# Module-level helper — consumed by provider_routing_api.py
def get_routing_status() -> Dict[str, Any]: ...
```

### 4.2 What gets deleted

| Symbol | Lines | Reason |
|---|---|---|
| `RoutingContext` dataclass | 84–93 | Only constructed by the dead `*_with_fallback` functions. |
| `ProviderResponse` dataclass | 96–104 | Only returned by dead `route_request` and the dead `*_with_fallback` functions. |
| `ProviderRouter.get_provider_priority_order` | 149–182 | Only called by `route_request`. |
| `ProviderRouter.route_request` | 184–277 | Only called by the two `*_with_fallback` entry points. |
| `ProviderRouter._update_provider_health` | 279–307 | Only called by `route_request`. |
| `get_holdings_with_fallback` | 362–387 | Zero callers. |
| `get_connections_with_fallback` | 390–411 | Zero callers. |
| `_fetch_snaptrade_holdings` | 418–447 | Only called by `get_holdings_with_fallback`. |
| `_fetch_plaid_holdings` (`NotImplementedError` stub from V1) | 450–456 | Only called by `get_holdings_with_fallback`. |
| `_fetch_snaptrade_connections` | 459–478 | Only called by `get_connections_with_fallback`. |
| `_fetch_plaid_connections` (`NotImplementedError` stub from V1) | 481–487 | Only called by `get_connections_with_fallback`. |
| `ProviderRouter.update_provider_config` | 323–351 | Zero callers after dropping the module-level wrapper below. (Codex R1 acceptance.) |
| `update_provider_configuration` (module-level) | 507–525 | Zero callers in any `*.py`. (Codex R1 acceptance.) |

### 4.3 `update_provider_configuration` + `update_provider_config` — DROP BOTH

Codex R1 finding (accepted): both are dead and should be removed.

- **`update_provider_configuration()` (module-level, line 507)** — zero callers in any `*.py`. The plan's original "keep for symmetry with `get_routing_status()`" rationale doesn't hold: `get_routing_status()` is on the read path that backs the live endpoint, this wrapper is on a write path that no endpoint exposes.
- **`ProviderRouter.update_provider_config()` (instance method, line 323)** — only called by the module-level wrapper above. With the wrapper gone, the instance method becomes orphaned.

Both go in §4.2. If/when an admin mutation API is added in the future (e.g. an admin tile per TODO V4), it would design its own write path against current code rather than restore this dead one.

### 4.4 Imports pruned from the file

After deletion:
- `asyncio`, `time`, `timedelta`, `Tuple`, `Union`, `List` (only `Dict`, `Any`, `Optional` remain in use)
- `fastapi.Request` (only used by `RoutingContext`)
- `portfolio_risk_engine.data_objects.PortfolioData` (only used by deleted `_fetch_*_holdings`)
- `database.get_db_session` (only used by deleted `_fetch_snaptrade_holdings` + `_fetch_snaptrade_connections`)
- `inputs.database_client.DatabaseClient` (same)
- `utils.logging.log_alert` (only used by deleted `route_request`)
- `dataclasses.field` (only used by deleted `RoutingContext` + `ProviderResponse`); `dataclass` itself stays for `ProviderConfig`
- `logging` import becomes unused (only `portfolio_logger` is referenced)

Final imports (verified by reading what's left after deletion):

```python
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

from utils.logging import portfolio_logger
```

---

## 5. Scope (what the diff touches)

| Path | Change |
|---|---|
| `routes/provider_routing.py` | **Modified** — delete 13 symbols listed in §4.2, prune imports per §4.4. ~395 LoC removed. |
| `tests/routes/test_provider_routing_api.py` | **Modified** — add one TestClient test for `GET /api/provider-routing/status` to give automated regression coverage of the kept surface (per Codex R1 finding 2). |
| `docs/TODO.md` | **Modified** — flip V1b row to `~~V1b~~` strikethrough with `✅ SHIPPED 2026-04-25` marker following the V1/V2/V3/V5 pattern. |
| Everything else | **Unchanged.** |

Files explicitly verified as unaffected (re-grep before commit per §11):
- `routes/provider_routing_api.py` — imports `provider_router` + `get_routing_status` (both kept).
- `app.py:7616, :7644` — imports `provider_routing_router` from `provider_routing_api`, not from `provider_routing`.
- `tests/routes/test_provider_routing_api.py` — only monkeypatches `get_routing_status` (kept).
- `tests/api_budget/_lint.py` — zero `provider_routing` references; nothing to update.
- `frontend/openapi-schema.json`, `frontend/packages/chassis/src/types/api-generated.ts` — reference `/api/provider-routing/*` URL paths, not Python symbols.
- `brokerage/plaid/client.py` — has its own `_fetch_plaid_holdings` (different function, vendor SDK boundary, namespace-isolated). Not touched.
- `tests/providers/test_snaptrade_positions.py`, `tests/services/test_snaptrade_portfolio_loader.py` — define local `_fetch_snaptrade_holdings` test fixtures with the same name (different namespace). Not touched.

---

## 6. Steps (locked to §5 scope)

1. **Edit `routes/provider_routing.py`**:
   - Delete the 13 symbols listed in §4.2 (`RoutingContext`, `ProviderResponse`, the three dead `ProviderRouter` instance methods on the fallback path, both `update_provider_config*` symbols per §4.3, the two `*_with_fallback` functions, the four `_fetch_*` wrappers).
   - Prune imports per §4.4 to the final 6 lines.
   - Keep `ProviderStatus`, `ProviderPriority`, `ProviderConfig`, `ProviderRouter.__init__`, `ProviderRouter._initialize_default_providers`, `ProviderRouter.get_provider_status`, `provider_router` singleton, `get_routing_status`.
2. **Edit `tests/routes/test_provider_routing_api.py`** — append one new test:

   ```python
   def test_provider_routing_status_returns_default_health_shape():
       client = _build_client()
       response = client.get("/api/provider-routing/status")
       assert response.status_code == 200
       payload = response.json()
       for provider in ("snaptrade", "plaid"):
           assert provider in payload
           assert "healthy" in payload[provider]
           assert "enabled" in payload[provider]
           assert "error_rate" in payload[provider]
           assert "avg_response_time" in payload[provider]
       assert "routing_enabled" in payload
   ```

   No mocks needed — `provider_router` is initialized at module import and `get_routing_status()` reads `ProviderConfig` defaults synchronously. This test gives automated regression coverage of the live endpoint after deletion (addresses Codex R1 finding 2).
3. **Update `docs/TODO.md`** V1b row: strikethrough name + status, replace status with `✅ SHIPPED 2026-04-25 — commit <SHA>`, append disposition note in the Notes column referencing this plan doc.

§5↔§6 lock check: §5 lists exactly three file modifications. §6 has exactly three implementation steps (one per file). ✅

---

## 7. Verification

Codex implements via `mcp__codex__codex` with `sandbox: "workspace-write"` per CLAUDE.md. After implementation, verify all four:

1. **Grep sweep** — these patterns must yield zero non-doc/non-completed-plan hits across `*.py`:
   ```
   RoutingContext
   ProviderResponse
   route_request
   get_provider_priority_order
   _update_provider_health
   get_holdings_with_fallback
   get_connections_with_fallback
   ```
   Plus these patterns must yield zero hits inside `routes/provider_routing.py` specifically (the SDK-namespaced versions in `brokerage/plaid/client.py` etc. are kept):
   ```
   _fetch_snaptrade_holdings
   _fetch_plaid_holdings
   _fetch_snaptrade_connections
   _fetch_plaid_connections
   ```
2. **Test suite** — `pytest tests/routes/test_provider_routing_api.py -v` passes. After §6 step 2, the file has **3 tests**: 2 pre-existing tests covering `/institution-support/...` (do not depend on the dead code) + 1 new test covering `/api/provider-routing/status` (covers the kept surface). Pre-revision plan claimed "3 tests" with status coverage; that was wrong — Codex R1 finding 2 caught it (file was 2 tests, neither hit `/status`).
3. **Import smoke** — `python -c "from routes.provider_routing import provider_router, get_routing_status; print(provider_router.get_provider_status())"` returns the two-provider dict without error.
4. **Live endpoint** — backend running on `:5001`, hit `GET /api/provider-routing/status` with dev cookie (per CLAUDE.md curl recipe). Response shape unchanged; `snaptrade.healthy`, `plaid.healthy`, `routing_enabled` fields all populated.

---

## 8. Risks

| Risk | Mitigation |
|---|---|
| Hidden caller of `get_holdings_with_fallback` / `get_connections_with_fallback` not caught by grep (e.g. dynamic dispatch, string-based import) | Grep was run across `*.py` for both function names AND for `from routes.provider_routing import` — only the two definitions matched. Dynamic-dispatch search not exhaustive but the file's pattern is direct calls only. Step 7.3 import smoke catches accidental top-level breakage. |
| `provider_routing_api.py` consumes a field from the status payload populated only by the dead `_update_provider_health` (e.g. `error_rate`, `avg_response_time_ms`) | Today those fields are already 0/0/None at runtime because `route_request` is never called. Removing `_update_provider_health` doesn't change the observable status — the values were always defaults. Step 7.4 confirms the live endpoint serializes correctly. |
| Future admin UI (TODO V4) will need a working `route_request`-style fallback | If/when fallback is wanted, it would need to be redesigned anyway — the per-provider-routing model superseded this pattern. Adding it back later is a clean greenfield, not a "restore-this-deleted-machinery" job. |
| ~~Codex argues for tighter cut~~ | Resolved in v2: Codex R1 recommended the tighter cut, plan accepted, both `update_provider_config*` symbols moved to §4.2 deletion list. |

---

## 9. Phasing

Single PR. No staged rollout — this is pure dead-code deletion with zero behavior change at the live endpoint. Verification §7 is the gate.

---

## 10. Cross-references

- V1 plaid plan: `docs/planning/VENDOR_PLAID_LOADER_SPLIT_PLAN.md` (Codex R1 surfaced V1b)
- V1 snaptrade plan: `docs/planning/VENDOR_SNAPTRADE_LOADER_SPLIT_PLAN.md`
- Live per-provider routing (the design that superseded the fallback chain): `providers/routing_config.py`, `services/position_service.py`, `mcp_tools/connections.py`
- TODO row: `docs/TODO.md` V1b (line 251 at draft time)
- Live admin endpoint (consumer): `routes/provider_routing_api.py:176`, registered at `app.py:7644`

---

## 11. Pre-commit grep sweep (per memory: `feedback_plan_grep_sweep_before_commit.md`)

Before committing the implementation, grep every Codex-named term + variants:

```
RoutingContext
ProviderResponse
route_request
get_provider_priority_order
_update_provider_health
get_holdings_with_fallback
get_connections_with_fallback
update_provider_configuration
update_provider_config
```

Plus the file-scoped `_fetch_*` patterns from §7.1.

Expected post-implementation hits:
- Doc references in `docs/TODO.md` V1 plaid row (Notes column) — leave as historical record.
- `docs/planning/VENDOR_PLAID_LOADER_SPLIT_PLAN.md` (completed plan) — leave as historical record.
- `docs/planning/VENDOR_PROVIDER_ROUTING_FALLBACK_REMOVAL_PLAN.md` (this plan) — expected.
- `CHANGELOG.md` — only if Codex chooses to add an entry; not required.

Anything else is a missed caller and blocks the commit.

---

## 12. Codex review brief

Reviewer: please execute locally per `feedback_codex_review_encourage_local_execution.md`. Specifically:

1. Run the §7.1 grep sweep yourself in a fresh checkout — verify the dead-code claim independently.
2. Run `pytest tests/routes/test_provider_routing_api.py -v` after applying the patch — confirm the kept surface still passes.
3. Sanity-check §4.3 (keep `update_provider_configuration` module-level vs. drop it). If you disagree, propose the tighter cut and I'll revise.
4. Sanity-check the import-pruning list in §4.4. If anything I propose to drop is still referenced after the deletions, flag it.
5. Confirm there's no live caller I missed by greping for the symbols listed in §7.1 across the whole repo (not just `*.py` — also check `*.ipynb`, JS callers via OpenAPI bindings if any).

PASS criteria: §4.2 deletions are correct, §4.3 disposition is acceptable, §4.4 import prune is complete, §7 verifications are sufficient, and no live caller was missed.
