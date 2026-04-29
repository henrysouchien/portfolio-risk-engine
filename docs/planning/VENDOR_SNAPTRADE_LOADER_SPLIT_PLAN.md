# Vendor SnapTrade Loader Split — V1 (snaptrade slice)

**Parent:** `docs/TODO.md` V1 · Vendor SDK Boundary Refactor Lane 2
**Sibling plan:** `VENDOR_PLAID_LOADER_SPLIT_PLAN.md` (under Codex review — same pattern, plaid slice)
**Predecessor:** main vendor SDK boundary refactor (PR #7, merged `3dbc0774`, 2026-04-23)
**Date:** 2026-04-24
**Status:** Draft v8 (addresses Codex R7 PASS-WITH-CHANGES — 1 finding: stale `_lint.py` line numbers refreshed to current post-Plaid-migration positions; `TRANSITIONAL_BOUNDARY_PATHS` note updated since Plaid migration on 2026-04-24 already removed `providers.plaid_loader` from that set). All R1–R6 resolutions still hold.

---

## 1. Problem

`providers/snaptrade_loader.py` (2,110 LoC) is labeled a "transitional boundary file" in the Rule A/B lint system (`tests/api_budget/_lint.py`). The original $342-unexpected-Plaid-bill incident (2026-04-16) drove the master vendor-SDK boundary plan; SnapTrade's analog risk is the same shape — business logic entangled with SDK orchestration in a boundary file.

The `brokerage/snaptrade/` package was already extracted in PR #7 (8 modules: `_shared`, `adapter`, `client`, `connections`, `recovery`, `secrets`, `trading`, `users`). What remains in `providers/snaptrade_loader.py`:

**Dead code (rebound at lines 2057–2110 to extracted `brokerage/snaptrade/*` versions):**
- Lines 98–789 (excluding `_map_snaptrade_code_to_internal` at 789): 14 SDK-wrapper functions (`get_snaptrade_client`, `store_snaptrade_app_credentials`, `get_snaptrade_app_credentials`, `store_snaptrade_user_secret`, `get_snaptrade_user_secret`, `delete_snaptrade_user_secret`, `get_snaptrade_user_id_from_email`, `register_snaptrade_user`, `delete_snaptrade_user`, `create_snaptrade_connection_url`, `upgrade_snaptrade_connection_to_trade`, `list_snaptrade_connections`, `check_snaptrade_connection_health`, `remove_snaptrade_connection`)
- Lines 1536–1924: 7 more shadowed defs (`handle_snaptrade_api_exception`, `with_snaptrade_retry`, `search_snaptrade_symbol`, `preview_snaptrade_order`, `place_snaptrade_checked_order`, `get_snaptrade_orders`, `cancel_snaptrade_order`)

**Live business logic that must move to `services/`** (Codex R1 finding #3 — `_map_snaptrade_code_to_internal` is LIVE, called at line 993 by `fetch_snaptrade_holdings`):
- Pure logic (no SDK calls): `_map_snaptrade_code_to_internal` (line 789), `normalize_snaptrade_holdings` (line 1096), `consolidate_snaptrade_holdings` (line 1148), `get_enhanced_security_type` (line 1266)
- Orchestrator + pipeline: `_budget_kwargs` (line 850), `fetch_snaptrade_holdings` (line 856), `convert_snaptrade_holdings_to_portfolio_data` (line 1332), `load_all_user_snaptrade_holdings` (line 1926)

**The wrong-direction loop the split eliminates:**
- `brokerage/snaptrade/__init__.py:53,65,71,82,101` — five lazy-import wrappers (`fetch_snaptrade_holdings`, `normalize_snaptrade_holdings`, `consolidate_snaptrade_holdings`, `convert_snaptrade_holdings_to_portfolio_data`, `load_all_user_snaptrade_holdings`) that delegate back to `providers.snaptrade_loader`. Five business-logic functions surfaced through `__all__` (lines 113–145) but their bodies live in the loader. Transport-layer boundary depending on a business-logic layer.

**The orchestrator's private-helper dependency (Codex R1 finding #1 — locks §4.4 below):**
- `providers/snaptrade_loader.py:904` calls `_list_user_accounts_with_retry`
- `providers/snaptrade_loader.py:953` calls `_get_user_account_positions_with_retry`
- `providers/snaptrade_loader.py:1048` calls `_get_user_account_balance_with_retry`
- These resolve to `brokerage/snaptrade/client.py:211, 233, ...` (private — not in `__all__`). The public `list_user_accounts` exists, but no public `get_user_account_positions` / `get_user_account_balance` wrappers exist. Plus secret-rotation flow at lines 911–931 uses `_get_rotation_lock` (private).

**Today's lint state for `providers.snaptrade_loader` (9 logical changes across 10 literal occurrences in `tests/api_budget/_lint.py`; line numbers verified against current `_lint.py` post-Plaid-migration):**
- Lines 71, 84, 97: `providers/snaptrade_loader.py` in 3 `VENDOR_BOUNDARY_ALLOWLIST` entries (`snaptrade_client`, `snaptrade_client.api_client`, `snaptrade_client.exceptions`)
- Line 189: `providers.snaptrade_loader` in `BOUNDARY_PACKAGE_PATHS`
- Line 194: `providers.snaptrade_loader` in `TRANSITIONAL_BOUNDARY_PATHS` — currently the ONLY entry (Plaid migration on 2026-04-24 already removed `providers.plaid_loader`); after this PR the set becomes empty (or the variable can be removed entirely if no other code references it — verify during impl)
- Line 206: `providers.snaptrade_loader` in `BOUNDARY_BANNED_NAMES` (`get_snaptrade_client`)
- Line 217: `providers.snaptrade_loader` in `_BOUNDARY_EXPORT_SOURCES`
- Line 236: `providers/snaptrade_loader.py` in `_BOUNDARY_INTERNAL_RULES["brokerage.snaptrade"]["files"]` — **REPLACED by `services/snaptrade_portfolio_loader.py`** (see §4.4 below)
- Lines 254–257: `_BOUNDARY_INTERNAL_RULES["providers.snaptrade_loader"]` entire entry

**Rule B baseline:** `tests/api_budget/rule_b_baseline.json` has zero snaptrade entries (verified). Split should not change baseline state.

---

## 2. Goal

Move all live business logic out of `providers/snaptrade_loader.py` into `services/`, delete the loader (including its 1,800+ lines of dead code), strip the 5 lazy-import wrappers from `brokerage/snaptrade/__init__.py` so the boundary stops re-exporting business logic, and apply 9 logical changes to `_lint.py` (8 removals + 1 transfer; the boundary-internal allowlist entry is transferred from the loader to `services/snaptrade_portfolio_loader.py` rather than removed outright).

Target outcome:
- `providers/snaptrade_loader.py` deleted (~2,110 LoC removed, of which ~1,800 are dead code we just stop carrying)
- `services/snaptrade_holdings_service.py` (new) — pure-logic functions, no SDK imports
- `services/snaptrade_portfolio_loader.py` (new) — orchestrator + pipeline, imports from `brokerage.snaptrade` (public) plus `brokerage.snaptrade.client` (private retry helpers, allowlisted as boundary-internal per §4.4)
- `brokerage/snaptrade/__init__.py` — 5 lazy-import wrappers + 5 `__all__` entries removed; package `__init__.py` becomes purely SDK re-exports
- 4 caller files updated to import business logic from `services.snaptrade_portfolio_loader` / `services.snaptrade_holdings_service`
- 6 test files migrated off `providers.snaptrade_loader` (Codex R1 finding #4 added `tests/providers/test_snaptrade_positions.py`)
- 9 logical changes in `_lint.py` (8 removals + 1 transfer)
- 2 active doc guides updated (`docs/guides/BROKERAGE_ADMIN.md`, `docs/deployment/AWS_SECRETS_MANAGER_MIGRATION_GUIDE.md`)
- 1 CI workflow updated (`.github/workflows/sync-to-public.yml`)

---

## 3. Non-Goals

This plan does **not**:
- Refactor `brokerage/snaptrade/` internal modules (already factored in PR #7; SDK wrappers stay as-is)
- Touch `brokerage/snaptrade/adapter.py` self-violation — covered separately by V3 (already verified 2026-04-23 per TODO.md)
- Add new public boundary functions for `get_user_account_positions` / `get_user_account_balance` — see §4.4 trade-off (deferred to a future API-surface cleanup PR; tracked as V1c)
- Refactor `providers/snaptrade_positions.py` internals — only its import target changes (this file does not currently import any vendor SDK; it imports through `brokerage.snaptrade`)
- Touch `providers/plaid_loader.py` — that's the sibling V1 plaid slice
- Modify `BOUNDARY_BANNED_NAMES["brokerage.snaptrade"]` — Rule A protection for `get_snaptrade_client` / `snaptrade_client` stays in place
- Re-architect secret-rotation behavior — preserve byte-identical flow

---

## 4. Target architecture

### 4.1 File layout after split

```
services/
  snaptrade_holdings_service.py     (NEW — pure DataFrame logic, no SDK imports)
  snaptrade_portfolio_loader.py     (NEW — orchestrator + pipeline; allowlisted as boundary-internal for brokerage.snaptrade)

brokerage/snaptrade/                (UNCHANGED — SDK-only after lazy wrappers removed)
  __init__.py                       (MODIFIED — drop 5 lazy-import wrappers + __all__ entries)
  _shared.py, adapter.py, client.py, connections.py,
  recovery.py, secrets.py, trading.py, users.py     (UNCHANGED)

providers/
  snaptrade_loader.py               (DELETED)
  snaptrade_positions.py            (MODIFIED — swap brokerage.snaptrade import to services.snaptrade_portfolio_loader)

routes/
  snaptrade.py                      (MODIFIED — split brokerage.snaptrade import; route business-logic names to services)
  provider_routing.py               (MODIFIED — same import split at :420–423)

services/
  position_service.py               (MODIFIED — swap brokerage.snaptrade import at :1621 to services.snaptrade_holdings_service)

tests/
  providers/test_snaptrade_loader_rebind.py        (DELETED)
  brokerage/test_snaptrade_client.py               (MODIFIED — patch target rewired)
  providers/test_snaptrade_positions.py            (MODIFIED — patch targets rewired) [Codex R1 finding #4]
  snaptrade/test_snaptrade_recovery.py             (MODIFIED — importlib retargeted)
  snaptrade/test_snaptrade_integration.py          (MODIFIED — importlib retargeted; verify @pytest.mark.real_provider)
  api/test_snaptrade_integration.py                (MODIFIED — importlib + 15 patch strings retargeted)

docs/
  guides/BROKERAGE_ADMIN.md                        (MODIFIED — 3 doc snippets retargeted)
  deployment/AWS_SECRETS_MANAGER_MIGRATION_GUIDE.md (MODIFIED — 1 doc snippet retargeted)

.github/
  workflows/sync-to-public.yml                     (MODIFIED — drop 2 references to providers/snaptrade_loader.py)
```

### 4.2 Function placement

**`services/snaptrade_holdings_service.py`** — pure logic, no SDK:
- `_map_snaptrade_code_to_internal(snaptrade_code)` (private — Codex R1 finding #3 confirms live; called from `fetch_snaptrade_holdings` at loader line 993)
- `normalize_snaptrade_holdings(holdings: list) -> pd.DataFrame`
- `consolidate_snaptrade_holdings(holdings_df: pd.DataFrame) -> pd.DataFrame`
- `get_enhanced_security_type(ticker: str, original_type: str) -> str`

**`services/snaptrade_portfolio_loader.py`** — orchestrator + pipeline:
- `_budget_kwargs(budget_user_id)` (private helper)
- `fetch_snaptrade_holdings(user_email, region_name='us-east-1', *, client=None, budget_user_id=None) -> List[Dict]` — see §4.3 for signature lock
- `convert_snaptrade_holdings_to_portfolio_data(holdings_df, user_email, portfolio_name, **kwargs)`
- `load_all_user_snaptrade_holdings(user_email, region_name='us-east-1', *, client=None, budget_user_id=None)`

### 4.3 `fetch_snaptrade_holdings` signature lock (Codex R1 finding #2)

Today there are **two** `fetch_snaptrade_holdings` shapes:
- Bare loader at `providers/snaptrade_loader.py:856`: `fetch_snaptrade_holdings(user_email, client, *, budget_user_id=None)` — caller MUST provide `client`
- Brokerage wrapper at `brokerage/snaptrade/__init__.py:45`: `fetch_snaptrade_holdings(user_email, region_name='us-east-1', *, client=None, budget_user_id=None)` — resolves client via `_require_snaptrade_client()` if not provided, then delegates to bare loader

`providers/snaptrade_positions.py:38-42` invokes the **wrapper signature** with `region_name=region, client=client, budget_user_id=budget_user_id`. If we move the bare loader signature to services as-is, that caller will `TypeError`.

**Decision**: the new services function adopts the **wrapper signature**. The wrapper's "resolve client if None" logic (calling `_require_snaptrade_client()` from `brokerage.snaptrade.client`) gets absorbed into the services orchestrator. The bare loader function signature is gone after the split. No external caller ever passes a positional `client` (verified — all callers go through the wrapper).

Concrete services implementation:
```python
# services/snaptrade_portfolio_loader.py
from brokerage.snaptrade.client import _require_snaptrade_client  # private helper, allowlisted via §4.4

def fetch_snaptrade_holdings(
    user_email: str,
    region_name: str = "us-east-1",
    *,
    client=None,
    budget_user_id: int | None = None,
) -> List[Dict]:
    del region_name  # accepted for backward compat with caller; SDK client doesn't use it
    resolved_client = client if client is not None else _require_snaptrade_client()
    # ... rest of the body (currently loader lines 856–1095)
```

`load_all_user_snaptrade_holdings` already has the wrapper-shape signature on the loader side (line 1926). **HOWEVER** (Codex R2 finding #1) — its **body** at loader line 1960 currently calls `fetch_snaptrade_holdings(user_email, client, budget_user_id=budget_user_id)` with positional `client`. After §4.3 makes arg 2 = `region_name`, this becomes a **TypeError**. The body must convert to keyword: `fetch_snaptrade_holdings(user_email, client=client, budget_user_id=budget_user_id)`. Additionally, line 1954 calls `get_snaptrade_client(region_name)` — Phase 2 must import `get_snaptrade_client` from `brokerage.snaptrade.client` (boundary-internal allowlist permits this; banned-name rule applies only to the package `__init__` re-export, not to the submodule).

### 4.4 Boundary-internal allowlist transfer (Codex R1 finding #1 — locked)

`fetch_snaptrade_holdings` directly invokes private retry helpers from `brokerage/snaptrade/client.py`:
- `_list_user_accounts_with_retry` (loader line 904 → client.py)
- `_get_user_account_positions_with_retry` (loader line 953 → client.py:211)
- `_get_user_account_balance_with_retry` (loader line 1048 → client.py:233)
- `_require_snaptrade_client` (used in §4.3 for client resolution → client.py)

Plus secret-rotation private helpers from `brokerage/snaptrade/recovery.py`:
- `_get_rotation_lock` (loader lines 911, 920)

These have no public boundary equivalents today (only `list_user_accounts` is public; positions/balance retry helpers are private-only).

**Two candidate solutions per Codex:**
- **Option B**: add public wrappers `get_user_account_positions(user_email, account_id, *, budget_user_id=None)` + `get_user_account_balance(user_email, account_id, *, budget_user_id=None)` to `brokerage/snaptrade/client.py` + `__all__`. Cleaner architecture, but expands public API surface and each wrapper must carefully preserve injected-client + secret-rotation semantics.
- **Option C**: **transfer** the boundary-internal allowlist entry from `providers/snaptrade_loader.py` to `services/snaptrade_portfolio_loader.py` in `_BOUNDARY_INTERNAL_RULES["brokerage.snaptrade"]["files"]` (line 236 of `_lint.py`). The services file is allowed to reach into private retry helpers; the rest of the world cannot.

**Decision (per Codex R1): Option C** — transfer the allowlist entry. Rationale:
- Preserves byte-identical behavior (no API surface expansion in this PR)
- Smaller, more mechanical split — easier to review, easier to revert
- `services/snaptrade_portfolio_loader.py` is the natural successor to the loader as the "boundary-adjacent" file allowed to use private SDK helpers
- A future API-surface cleanup PR (V1c) can promote private→public retry wrappers and remove the allowlist entry once the public surface is expanded

**Architectural trade-off (documented for future cleanup):**
After this split, `brokerage/snaptrade/` is *not* "purely SDK with no boundary-internal friendlies" — `services/snaptrade_portfolio_loader.py` is the single allowlisted external file. The semantic reality: this is one targeted exemption that mirrors the current `providers/snaptrade_loader.py` exemption, just at the new file. Lint-wise, the same number of files (1) reach into private brokerage internals.

**Concrete `_lint.py` change at line 236:**
```python
# Before:
"brokerage.snaptrade": {
    "prefixes": ("brokerage/snaptrade/",),
    "files": frozenset({"providers/snaptrade_loader.py"}),
},

# After:
"brokerage.snaptrade": {
    "prefixes": ("brokerage/snaptrade/",),
    "files": frozenset({"services/snaptrade_portfolio_loader.py"}),
},
```

### 4.5 Dependency direction after split

```
brokerage/snaptrade/                            (SDK boundary)
     ↑
services/snaptrade_portfolio_loader.py          (orchestrator, allowlisted boundary-adjacent)
     ↑       ↖
services/snaptrade_holdings_service.py   (pure logic, standalone)
     ↑
callers: routes/, providers/snaptrade_positions.py, services/position_service.py
```

`brokerage/` stops depending on `providers/`. `services/` depends on `brokerage/` (correct direction). Pure-logic service has no upward deps.

### 4.6 `__all__` change in `brokerage/snaptrade/__init__.py`

Five entries to remove from `__all__` (current lines 118, 119, 122, 135, 136):
- `consolidate_snaptrade_holdings`
- `convert_snaptrade_holdings_to_portfolio_data`
- `fetch_snaptrade_holdings`
- `load_all_user_snaptrade_holdings`
- `normalize_snaptrade_holdings`

Five lazy-import wrapper functions to delete (current lines 45–110): `fetch_snaptrade_holdings`, `normalize_snaptrade_holdings`, `consolidate_snaptrade_holdings`, `convert_snaptrade_holdings_to_portfolio_data`, `load_all_user_snaptrade_holdings`.

After the change, `brokerage/snaptrade/__init__.py` re-exports only SDK-shaped boundary functions + the adapter class + the exception alias. Lint expects this exact `__all__` (sourced via `_BOUNDARY_EXPORT_SOURCES`).

---

## 5. Phased plan — single atomic PR (locked)

### Phase 1: Create `services/snaptrade_holdings_service.py` (pure logic)

1. Copy 4 functions from `providers/snaptrade_loader.py` into the new file:
   - `_map_snaptrade_code_to_internal` (line 789) — Codex R1 confirmed live
   - `normalize_snaptrade_holdings` (line 1096)
   - `consolidate_snaptrade_holdings` (line 1148)
   - `get_enhanced_security_type` (line 1266)
2. Preserve all imports they need (`pandas`, `core.cash_helpers`, `services.security_type_service`, `utils.logging`). NO snaptrade SDK imports.
3. Preserve `SecurityTypeService` lazy-import fallback if applicable (loader lines 84–89). Verify whether any of the 4 functions actually depend on the fallback path; if so, replicate the try/except idiom.

**Exit criteria:** `python3 -c "from services.snaptrade_holdings_service import normalize_snaptrade_holdings, _map_snaptrade_code_to_internal"` succeeds; the file has zero imports from `snaptrade_client`, `snaptrade_client.*`.

### Phase 2: Create `services/snaptrade_portfolio_loader.py` (orchestrator + pipeline)

1. Copy 4 functions: `_budget_kwargs` (line 850), `fetch_snaptrade_holdings` (line 856), `convert_snaptrade_holdings_to_portfolio_data` (line 1332), `load_all_user_snaptrade_holdings` (line 1926).
2. Apply §4.3 signature lock to `fetch_snaptrade_holdings` (adopt wrapper signature; absorb `_require_snaptrade_client()` resolution).
3. Set up imports per §4.4 Option C:
   - Public boundary: `from brokerage.snaptrade import (get_snaptrade_user_id_from_email, get_snaptrade_user_secret, is_snaptrade_secret_error, recover_snaptrade_auth, rotate_snaptrade_user_secret, get_snaptrade_rotation_lock, list_user_accounts, SnapTradeApiException)`
   - Boundary-internal (per §4.4 Option C; allowlisted via `services/snaptrade_portfolio_loader.py` entry on `_lint.py:236`):
     - `from brokerage.snaptrade.client import (get_snaptrade_client, _require_snaptrade_client, _list_user_accounts_with_retry, _get_user_account_positions_with_retry, _get_user_account_balance_with_retry)` — Codex R2 finding #1 added `get_snaptrade_client` because `load_all_user_snaptrade_holdings` body uses it
     - `from brokerage.snaptrade.recovery import _get_rotation_lock`
   - Pure-logic helpers: `from services.snaptrade_holdings_service import normalize_snaptrade_holdings, consolidate_snaptrade_holdings, get_enhanced_security_type, _map_snaptrade_code_to_internal` — Codex R2 finding #1 added `consolidate_snaptrade_holdings` because `load_all_user_snaptrade_holdings` body calls it at loader line 1973
4. Verify ticker-resolver lazy import preserved (`from utils.ticker_resolver import resolve_ticker_from_exchange` at loader line 891) — keep inside function body.
5. **Convert positional `client` to keyword in `load_all_user_snaptrade_holdings` body** (Codex R2 finding #1): change loader line 1960 from `fetch_snaptrade_holdings(user_email, client, budget_user_id=budget_user_id)` to `fetch_snaptrade_holdings(user_email, client=client, budget_user_id=budget_user_id)`. Without this change, the post-migration call hits §4.3's wrapper signature and binds the SnapTrade client object to `region_name` → TypeError at runtime.
6. Preserve secret-rotation flow byte-identically (loader lines 911–931 → orchestrator equivalent). All private helpers come from explicitly-allowlisted imports above.

**Exit criteria:** `python3 -c "from services.snaptrade_portfolio_loader import load_all_user_snaptrade_holdings, fetch_snaptrade_holdings"` succeeds; smoke-test via mocked `_list_user_accounts_with_retry` returns expected DataFrame shape.

### Phase 3: Update production callers (4 files) + delete brokerage init wrappers

**Indirect callers via `brokerage.snaptrade` business-logic re-exports:**

1. **`services/position_service.py:1621`** — change:
   ```python
   from brokerage.snaptrade import consolidate_snaptrade_holdings
   ```
   to:
   ```python
   from services.snaptrade_holdings_service import consolidate_snaptrade_holdings
   ```

2. **`routes/snaptrade.py:143–159`** — split the multi-line `from brokerage.snaptrade import (...)` block:
   ```python
   from brokerage.snaptrade import (
       create_snaptrade_connection_url,
       delete_snaptrade_user,
       get_snaptrade_rotation_lock as _get_rotation_lock,
       get_snaptrade_user_id_from_email,
       get_snaptrade_user_secret,
       is_snaptrade_secret_error,
       list_snaptrade_connections,
       recover_snaptrade_auth,
       register_snaptrade_user,
       remove_snaptrade_connection,
       rotate_snaptrade_user_secret,
       SnapTradeApiException,
   )
   from services.snaptrade_portfolio_loader import (
       convert_snaptrade_holdings_to_portfolio_data,
       load_all_user_snaptrade_holdings,
   )
   from services.snaptrade_holdings_service import consolidate_snaptrade_holdings
   ```

3. **`routes/provider_routing.py:420–423`** — change:
   ```python
   from brokerage.snaptrade import (
       convert_snaptrade_holdings_to_portfolio_data,
       load_all_user_snaptrade_holdings,
   )
   ```
   to:
   ```python
   from services.snaptrade_portfolio_loader import (
       convert_snaptrade_holdings_to_portfolio_data,
       load_all_user_snaptrade_holdings,
   )
   ```

4. **`providers/snaptrade_positions.py:30–33`** — change:
   ```python
   from brokerage.snaptrade import (
       fetch_snaptrade_holdings,
       normalize_snaptrade_holdings,
   )
   ```
   to:
   ```python
   from services.snaptrade_portfolio_loader import fetch_snaptrade_holdings
   from services.snaptrade_holdings_service import normalize_snaptrade_holdings
   ```
   The new `fetch_snaptrade_holdings` carries the wrapper signature (§4.3) so the existing call site at `:38-42` (`region_name=region, client=client, budget_user_id=budget_user_id`) works unchanged.

**`brokerage/snaptrade/__init__.py`** — delete the 5 lazy-import wrapper function defs (current lines 45–110) and the 5 corresponding `__all__` entries (current lines 118, 119, 122, 135, 136). After this, `brokerage/snaptrade/__init__.py` is purely SDK re-exports.

**Exit criteria** (Codex R1 finding #5 + R2 finding #5 — broader + multiline-aware grep):
- `grep -rEn "providers\.snaptrade_loader|providers/snaptrade_loader" --include="*.py" .` returns zero hits in non-doc, non-CI paths
- **Multiline-aware** (Codex R2 finding #5 — the v2 single-line grep would miss multi-line `from brokerage.snaptrade import (...)` blocks like `routes/snaptrade.py:143` where the module is on one line and names span the next 16 lines): use `rg -nU` with multiline DOTALL flag, OR run an AST verification script. Recommended AST approach:
  ```bash
  python3 -c "
  import ast, pathlib
  BANNED = {'fetch_snaptrade_holdings','normalize_snaptrade_holdings','consolidate_snaptrade_holdings','convert_snaptrade_holdings_to_portfolio_data','load_all_user_snaptrade_holdings'}
  hits = []
  for p in pathlib.Path('.').rglob('*.py'):
      if any(s in p.parts for s in ('.git','venv','node_modules','__pycache__','.venv')): continue
      try: tree = ast.parse(p.read_text())
      except Exception: continue
      for node in ast.walk(tree):
          if isinstance(node, ast.ImportFrom) and node.module == 'brokerage.snaptrade':
              for alias in node.names:
                  if alias.name in BANNED:
                      hits.append(f'{p}:{node.lineno}: from brokerage.snaptrade import {alias.name}')
  print('\n'.join(hits) or 'OK — zero business-logic imports from brokerage.snaptrade')
  "
  ```
- `grep -rEn "snaptrade_loader = importlib" --include="*.py" .` returns zero hits in production paths (test files retain importlib for SDK-introspection per §6 above; verify each match is in a test file)
- `grep -rEn "patch\(['\"]providers\.snaptrade_loader" --include="*.py" .` returns zero hits

### Phase 4: Migrate test files (6 files)

Six test files reference `providers.snaptrade_loader` today (Codex R1 finding #4 added file #6):

**1. `tests/providers/test_snaptrade_loader_rebind.py`** — DELETE entirely. Verifies the rebind block at loader line 2057+; the rebind goes away with the file.

**2. `tests/brokerage/test_snaptrade_client.py:70`** — change patch target from `providers.snaptrade_loader.fetch_snaptrade_holdings` to `services.snaptrade_portfolio_loader.fetch_snaptrade_holdings`.

**3. `tests/providers/test_snaptrade_positions.py:27, 30`** (Codex R1 finding #4 — was missing from v1) — change patch targets:
   - Line 27: `brokerage.snaptrade.fetch_snaptrade_holdings` → `services.snaptrade_portfolio_loader.fetch_snaptrade_holdings`
   - Line 30: `brokerage.snaptrade.normalize_snaptrade_holdings` → `services.snaptrade_holdings_service.normalize_snaptrade_holdings`
   The fake `_fetch_snaptrade_holdings` already uses the wrapper signature (`user_email, region_name="us-east-1", *, client=None, budget_user_id=None` at lines 13–18), so no shape change needed — this matches §4.3 signature lock.

**Lint-exemption mechanism note (Codex R2 finding #2):** `@pytest.mark.real_provider` does NOT exempt Rule B lint. The marker only governs the runtime autouse fixture (`_block_real_provider_calls` in `tests/conftest.py`) that monkeypatches vendor SDK objects to raise `RuntimeError`. Rule B is a static AST check on imports; it does not consult markers. Tests that need to access banned names (e.g., `get_snaptrade_client`) or boundary-internal modules (`brokerage.snaptrade.client`) must use **`importlib.import_module(...)`** to bypass the static AST walker. The current SnapTrade integration tests already use this pattern; v3 preserves it. After migration, `importlib.import_module("providers.snaptrade_loader")` becomes per-name retargeted imports — some via static `from brokerage.snaptrade import ...` (legal public surface), some via `importlib.import_module("brokerage.snaptrade.client")` (legal because importlib bypasses static check). `@pytest.mark.real_provider` is still added separately for the runtime fixture exemption.

**Patch-where-it-is-used rule (Codex R2 findings #3, #4):** Python's `unittest.mock.patch` retargets the **bound name in the module under test**, not the defining module. After deletion of `providers/snaptrade_loader.py`, each patch string must point to the NAME-AT-USE-SITE, not at the original definition's home. Several v2 retargets violated this — corrected in the v3 table below.

**4. `tests/snaptrade/test_snaptrade_recovery.py:21`** — replace `snaptrade_loader = importlib.import_module("providers.snaptrade_loader")` with explicit imports (legal):
   - `fetch_snaptrade_holdings` from `services.snaptrade_portfolio_loader`
   - `get_snaptrade_user_id_from_email`, `get_snaptrade_user_secret`, `rotate_snaptrade_user_secret` from `brokerage.snaptrade`

   For private `_get_rotation_lock`, use `importlib.import_module("brokerage.snaptrade.recovery")` then access via attribute — this bypasses the static AST check (Codex R2 finding #2 — markers don't help; importlib does). Update `patch.object(snaptrade_loader, ...)` calls per the patch-where-used rule. Patches mocking names that `fetch_snaptrade_holdings` looks up internally use `services.snaptrade_portfolio_loader.<name>` (the orchestrator's bound names — `_list_user_accounts_with_retry`, `_get_rotation_lock`, `rotate_snaptrade_user_secret`, `get_snaptrade_user_id_from_email`, `get_snaptrade_user_secret`).

   **Call-site signature fix (Codex R3 finding #5):** lines 401 and 417 currently call `fetch_snaptrade_holdings("user@example.com", client)` with positional `client`. After §4.3 wrapper signature, arg 2 is `region_name`, so this binds the SnapTrade client to `region_name` and triggers TypeError (or worse — silent bug). Change both to `fetch_snaptrade_holdings("user@example.com", client=client)`.

   Add file-level `@pytest.mark.real_provider` if missing (runtime fixture exemption — separate concern from lint).

**5. `tests/snaptrade/test_snaptrade_integration.py`** — replace importlib at line 64. Drop the v1 "use is_snaptrade_available()" suggestion (Codex R1 finding #6); v2's "real_provider exempts lint" claim is also wrong (Codex R2 finding #2). Correct migration:
   - `fetch_snaptrade_holdings` → static `from services.snaptrade_portfolio_loader import fetch_snaptrade_holdings` (legal — services file is allowlisted)
   - `normalize_snaptrade_holdings`, `consolidate_snaptrade_holdings` → static `from services.snaptrade_holdings_service import ...` (legal — services file is plain Python, not a boundary)
   - `get_snaptrade_client`, `get_snaptrade_app_credentials` → use `importlib.import_module("brokerage.snaptrade.client")` then attribute access (bypasses static AST check; legitimate for SDK-introspection tests)
   - Add file-level `@pytest.mark.real_provider` for runtime block-real-calls exemption (separate from lint).
   - Verify lines 175 (raw client storage), 184 (`get_snaptrade_app_credentials()` access), 196–198 (`api_status` check) work via the importlib-fetched module: `client_module = importlib.import_module("brokerage.snaptrade.client"); client = client_module.get_snaptrade_client(); creds = client_module.get_snaptrade_app_credentials()`.

**6. `tests/api/test_snaptrade_integration.py`** — most extensive changes. Line 31 importlib retarget split per name as in #5. **15 `patch()` strings** to retarget (Codex R2 finding #5 corrected v2's count of 13; lines 458–460 are stacked decorators on a single test method but each is a separate patch):

   For each entry, the **patch target is the bound name at the use site**, not at the definition's home (Codex R2 findings #3, #4). For decorator stacks (lines 448, 457, 458, 459, 460), the test under test is a method that exercises a specific function; patch where THAT function looks up the name.

   | Line | Current | New | Why (verified by reading test bodies + extracted module imports) |
   |---|---|---|---|
   | 82 | `'providers.snaptrade_loader.get_snaptrade_app_credentials'` | `'brokerage.snaptrade.client.get_snaptrade_app_credentials'` | Test under `test_initialize_snaptrade_client_*` — calls `get_snaptrade_client()`, which is in `brokerage.snaptrade.client` and binds `get_snaptrade_app_credentials` at `brokerage/snaptrade/client.py:18` |
   | 86 | `'providers.snaptrade_loader.SnapTrade'` | `'brokerage.snaptrade.client.SnapTrade'` | SDK class imported into client.py at `:25`; `get_snaptrade_client()` constructs `SnapTrade(...)` there |
   | 105 | `'providers.snaptrade_loader.SnapTrade'` | `'brokerage.snaptrade.client.SnapTrade'` | Same as :86 |
   | 120 | `'providers.snaptrade_loader.SnapTrade'` | `'brokerage.snaptrade.client.SnapTrade'` | Same as :86 (testing SnapTrade=None disabled path) |
   | 142 | `'providers.snaptrade_loader.store_snaptrade_user_secret'` | `'brokerage.snaptrade.users.store_snaptrade_user_secret'` | Test under `test_register_user_*` — exercises `register_snaptrade_user()` which lives in `brokerage.snaptrade.users` and binds `store_snaptrade_user_secret` at `brokerage/snaptrade/users.py:14-18` |
   | 159 | `'providers.snaptrade_loader.get_snaptrade_user_secret'` | `'brokerage.snaptrade.users.get_snaptrade_user_secret'` | Test (line 160) calls `register_snaptrade_user('test@example.com', mock_client)` — `register_snaptrade_user` lives in `brokerage.snaptrade.users` which binds `get_snaptrade_user_secret` at `brokerage/snaptrade/users.py:14-18` |
   | 170 | `'providers.snaptrade_loader.get_snaptrade_user_secret'` | `'brokerage.snaptrade.users.get_snaptrade_user_secret'` | Test (line 171) calls `create_snaptrade_connection_url('test@example.com', mock_client)`. That function lives at `brokerage/snaptrade/connections.py:43` and calls `register_snaptrade_user` internally (Codex R4 finding #1 corrected v4's claim about `_call_with_secret_rotation`). `register_snaptrade_user` lives in `brokerage.snaptrade.users` and binds `get_snaptrade_user_secret` at `brokerage/snaptrade/users.py:14-18` — same patch target as line 159. |
   | 423 | `'providers.snaptrade_loader.get_snaptrade_user_secret'` | `'brokerage.snaptrade.connections._call_with_secret_rotation'` | Test (line 424) calls `remove_snaptrade_connection('test@example.com', 'auth_123', mock_client)`. That function lives at `brokerage.snaptrade.connections` and uses `_call_with_secret_rotation` at line 341 (Codex R4 finding #2). The bound name is imported into connections.py at `:15`, so patch `brokerage.snaptrade.connections._call_with_secret_rotation` — this redirects the helper at the use site. **REQUIRED ASSERTION REWRITE (Codex R5 finding #1):** mocking `_call_with_secret_rotation` short-circuits the callback into `mock_client.connections.remove_brokerage_authorization`, so the existing assertion at test lines 426–430 will NOT hold. Rewrite to assert against the mock's `call_args` (e.g., `mock_call_with_rotation.assert_called_once()` and verify the closure passed in receives `mock_client` + `auth_123`). Test intent shifts from "verify the SDK method is called with right args" to "verify the rotation orchestrator is invoked correctly" — call out in PR description. |
   | 434 | `'providers.snaptrade_loader.get_snaptrade_user_secret'` | `'brokerage.snaptrade.users.get_snaptrade_user_secret'` | Test (line 436) calls `delete_snaptrade_user('test@example.com', mock_client)` — lives in `brokerage.snaptrade.users`, same bound-name location as :159 |
   | 435 | `'providers.snaptrade_loader.delete_snaptrade_user_secret'` | `'brokerage.snaptrade.users.delete_snaptrade_user_secret'` | Used by `delete_snaptrade_user()` (in users.py); imported into users at `brokerage/snaptrade/users.py:14-18` (Codex R2 finding #4) |
   | 448 | `@patch('providers.snaptrade_loader.get_snaptrade_client')` | `@patch('services.snaptrade_portfolio_loader.get_snaptrade_client')` | Codex R3 finding #1: test (lines 449–455) calls `load_all_user_snaptrade_holdings('test@example.com')` which now lives in `services.snaptrade_portfolio_loader` and binds `get_snaptrade_client` there (per Phase 2 step 3 imports) |
   | 457 | `@patch('providers.snaptrade_loader.get_snaptrade_client')` | `@patch('services.snaptrade_portfolio_loader.get_snaptrade_client')` | Codex R3 finding #2: same test method (`test_load_all_user_holdings_complete_flow` at line 461) calls into `load_all_user_snaptrade_holdings` |
   | 458 | `@patch('providers.snaptrade_loader.fetch_snaptrade_holdings')` | `@patch('services.snaptrade_portfolio_loader.fetch_snaptrade_holdings')` | Codex R3 finding #2: orchestrator looks up `fetch_snaptrade_holdings` by bare name from its own module |
   | 459 | `@patch('providers.snaptrade_loader.normalize_snaptrade_holdings')` | `@patch('services.snaptrade_portfolio_loader.normalize_snaptrade_holdings')` | Codex R3 finding #2: orchestrator imports `normalize_snaptrade_holdings` from `services.snaptrade_holdings_service` (per Phase 2 step 3) and binds it locally — patch where it's bound at the use site, NOT at the definition module |
   | 460 | `@patch('providers.snaptrade_loader.consolidate_snaptrade_holdings')` | `@patch('services.snaptrade_portfolio_loader.consolidate_snaptrade_holdings')` | Codex R3 finding #2: same as :459 |

   **Assertion update at line 484** (Codex R3 finding #3): current `mock_fetch.assert_called_once_with('test@example.com', mock_client)` (positional) must become `mock_fetch.assert_called_once_with('test@example.com', client=mock_client)` because §4.3's wrapper signature makes arg 2 = `region_name`, and `load_all_user_snaptrade_holdings` body calls `fetch_snaptrade_holdings(user_email, client=client, ...)` (per Phase 2 step 5 keyword conversion).

   Add file-level `@pytest.mark.real_provider` marker if missing (runtime fixture).

**Exit criteria:** `pytest tests/snaptrade/ tests/api/test_snaptrade_integration.py tests/brokerage/test_snaptrade_client.py tests/providers/test_snaptrade_positions.py -v` all pass; `tests/providers/test_snaptrade_loader_rebind.py` no longer exists; broader Phase 3 grep returns zero hits.

### Phase 5: Delete `providers/snaptrade_loader.py` + update docs + CI workflow

1. `rm providers/snaptrade_loader.py`
2. **Update active doc guides (Codex R1 finding #8):**
   - `docs/guides/BROKERAGE_ADMIN.md:92` — change `from providers.snaptrade_loader import create_snaptrade_connection_url, get_snaptrade_client` to import from `brokerage.snaptrade` (public API only — drop `get_snaptrade_client` if the snippet doesn't strictly need raw client access; if it does, document the integration-test pattern). Use Edit, surgical.
   - `docs/guides/BROKERAGE_ADMIN.md:130` — `from providers.snaptrade_loader import upgrade_snaptrade_connection_to_trade, get_snaptrade_client` → `from brokerage.snaptrade import upgrade_snaptrade_connection_to_trade` + drop client.
   - `docs/guides/BROKERAGE_ADMIN.md:144` — `from providers.snaptrade_loader import check_snaptrade_connection_health, get_snaptrade_client` → `from brokerage.snaptrade import check_snaptrade_connection_health` + drop client.
   - `docs/deployment/AWS_SECRETS_MANAGER_MIGRATION_GUIDE.md:97` — `from providers.snaptrade_loader import store_snaptrade_app_credentials` → `from brokerage.snaptrade.secrets import store_snaptrade_app_credentials` (this is admin/setup code; submodule import is acceptable as it's not a runtime caller).
3. **Update 3 active stale references** (Codex R2 finding #6):
   - `utils/security_type_mappings.py:18` — module-docstring "INTEGRATION POINTS" line: `providers/snaptrade_loader.py: _map_snaptrade_code_to_internal() function` → update to `services/snaptrade_holdings_service.py: _map_snaptrade_code_to_internal() function` (function moved per Phase 1).
   - `docs/reference/DATA_SCHEMAS.md:2673` — "Service Integration Points" line: `**SnapTrade Enhanced**: \`providers/snaptrade_loader.py\`` → update to `**SnapTrade Enhanced**: \`services/snaptrade_portfolio_loader.py\` + \`services/snaptrade_holdings_service.py\``.
   - `docs/TODO.md:249` — V1 (snaptrade) row description currently says "providers/snaptrade_loader.py (~2,000 lines) — bigger structural slice than plaid". This is the description of THIS work item; it's accurate as-is (describes the work being done). Update post-ship when marking SHIPPED, NOT in this PR.
4. **Leave archived references untouched:** `docs/planning/completed/CODEBASE_BUGS_FIX_PLAN.md`, `CHANGELOG.md` (historical record). For `frontend/packages/ui/src/ARCHITECTURE.md:645` ("Full SnapTrade SDK integration in backend (`providers/snaptrade_loader.py`)") — update to point to `brokerage/snaptrade/` + `services/snaptrade_*` (frontend architecture doc; current line reflects pre-extraction reality and is now doubly stale).
5. **Update CI workflow (Codex R1 finding #5 surfaced this):**
   - `.github/workflows/sync-to-public.yml:17` — drop `'providers/snaptrade_loader.py'` from the path-trigger list.
   - `.github/workflows/sync-to-public.yml:81` — drop the `cp providers/snaptrade_loader.py public-repo/providers/` line.
6. Verify: `grep -rEn "providers\.snaptrade_loader|providers/snaptrade_loader" --include="*.py" --include="*.md" --include="*.yml" .` returns hits only in (a) `CHANGELOG.md` historical entries, (b) `docs/planning/completed/`, (c) `tests/TESTING_COMMANDS.md` (operator doc — update if scope permits, else file follow-up), (d) `docs/TODO.md:249` (this work item's description, valid until ship).

**Exit criteria:** loader file gone; active docs accurate; CI workflow clean; no `ImportError` in any production path.

### Phase 6: Lint allowlist cleanup

Apply 9 logical changes in `tests/api_budget/_lint.py` (8 removals + 1 transfer):

1. **`VENDOR_BOUNDARY_ALLOWLIST["snaptrade_client"]`** (line 71) — drop `"providers/snaptrade_loader.py"`
2. **`VENDOR_BOUNDARY_ALLOWLIST["snaptrade_client.api_client"]`** (line 84) — drop `"providers/snaptrade_loader.py"`
3. **`VENDOR_BOUNDARY_ALLOWLIST["snaptrade_client.exceptions"]`** (line 97) — drop `"providers/snaptrade_loader.py"`
4. **`BOUNDARY_PACKAGE_PATHS`** (line 189) — drop `"providers.snaptrade_loader"`
5. **`TRANSITIONAL_BOUNDARY_PATHS`** (line 194) — drop `"providers.snaptrade_loader"` (currently the only entry; the set becomes empty after this PR — Plaid migration already removed `providers.plaid_loader` on 2026-04-24)
6. **`BOUNDARY_BANNED_NAMES`** (line 206) — drop `"providers.snaptrade_loader"` entry
7. **`_BOUNDARY_EXPORT_SOURCES`** (line 217) — drop `"providers.snaptrade_loader"` entry
8. **`_BOUNDARY_INTERNAL_RULES["brokerage.snaptrade"]["files"]`** (line 236) — **TRANSFER** entry from `"providers/snaptrade_loader.py"` to `"services/snaptrade_portfolio_loader.py"` (per §4.4 Option C lock)
9. **`_BOUNDARY_INTERNAL_RULES["providers.snaptrade_loader"]`** (lines 254–257) — drop entire entry

Then regenerate Rule B baseline: `python scripts/generate_rule_b_baseline.py`.

**Exit criteria:**
- 9 logical `_lint.py` changes applied (8 removals + 1 transfer at line 236; touches 10 literal occurrences total since #9 is a multi-line block)
- `pytest tests/api_budget/` — Rule A + Rule B tests pass
- Rule B baseline expected unchanged (snaptrade_loader had zero baseline entries since it was itself a TRANSITIONAL boundary). Document in commit message.
- Reintroducing `from providers.snaptrade_loader import anything` fails with `ImportError` (file gone) + recreating the file with snaptrade SDK imports fails Rule A lint.

---

## 6. Test strategy

### Test migration (6 files — see Phase 4)

Concrete per-file changes documented above. All file-level `@pytest.mark.real_provider` markers must be present on integration-shaped tests (5, 6); add if missing.

### New tests
- `tests/services/test_snaptrade_holdings_service.py` — pure-logic coverage for the 4 functions. Cover cash-position handling, type-mapping fallback, FMP enhancement path. ~60 LoC.
- `tests/services/test_snaptrade_portfolio_loader.py` — orchestrator coverage with mocked `_list_user_accounts_with_retry` + `_get_user_account_positions_with_retry` + `_get_user_account_balance_with_retry`. Validate: (a) happy path returns expected DataFrame shape, (b) secret-rotation flow on first 401 succeeds on retry, (c) `client=None` → `_require_snaptrade_client()` resolution path, (d) `client=<provided>` → bypass resolution path, (e) `convert_snaptrade_holdings_to_portfolio_data` output shape. ~120 LoC.

### Regression guards
- After Phase 4, all 6 migrated test files pass without behavioral change.
- `pytest tests/api_budget/` proves the lint transfer (line 236) works end-to-end: services file can reach into private retry helpers; no other external file can.

### Validation commands per phase

```bash
# Phase 1 smoke
python3 -c "from services.snaptrade_holdings_service import normalize_snaptrade_holdings, consolidate_snaptrade_holdings, get_enhanced_security_type, _map_snaptrade_code_to_internal; print('OK')"

# Phase 2 smoke
python3 -c "from services.snaptrade_portfolio_loader import load_all_user_snaptrade_holdings, fetch_snaptrade_holdings, convert_snaptrade_holdings_to_portfolio_data; print('OK')"

# Phase 3 grep sweep — broader patterns + AST verifier (Codex R1 finding #5 + R2 finding #5 + R4 finding #3)
grep -rEn "providers\.snaptrade_loader|providers/snaptrade_loader" --include="*.py" .
grep -rEn "snaptrade_loader = importlib" --include="*.py" .
grep -rEn "patch\(['\"]providers\.snaptrade_loader" --include="*.py" .
# CRITICAL: single-line grep cannot catch multiline `from brokerage.snaptrade import (` blocks; use the AST verifier from Phase 3 exit criteria instead — replicated here so the validation block is multiline-safe end-to-end:
python3 -c "
import ast, pathlib
BANNED = {'fetch_snaptrade_holdings','normalize_snaptrade_holdings','consolidate_snaptrade_holdings','convert_snaptrade_holdings_to_portfolio_data','load_all_user_snaptrade_holdings'}
hits = []
for p in pathlib.Path('.').rglob('*.py'):
    if any(s in p.parts for s in ('.git','venv','node_modules','__pycache__','.venv')): continue
    try: tree = ast.parse(p.read_text())
    except Exception: continue
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == 'brokerage.snaptrade':
            for alias in node.names:
                if alias.name in BANNED:
                    hits.append(f'{p}:{node.lineno}: from brokerage.snaptrade import {alias.name}')
print('\n'.join(hits) or 'OK — zero business-logic imports from brokerage.snaptrade')
"

# Phase 4 verification — test files migrated
pytest tests/snaptrade/ tests/api/test_snaptrade_integration.py tests/brokerage/test_snaptrade_client.py tests/providers/test_snaptrade_positions.py -v

# Phase 5+6 full
pytest tests/ -x
pytest tests/api_budget/
```

---

## 7. Rule A / Rule B allowlist interactions

| Change | Line(s) | Effect |
|---|---|---|
| Remove `"providers/snaptrade_loader.py"` from `VENDOR_BOUNDARY_ALLOWLIST["snaptrade_client"]` | 71 | Recreating the file with `import snaptrade_client` now fails Rule A |
| Same for `snaptrade_client.api_client` | 84 | Same |
| Same for `snaptrade_client.exceptions` | 97 | Same |
| Remove `"providers.snaptrade_loader"` from `BOUNDARY_PACKAGE_PATHS` | 189 | Rule B no longer treats loader as a valid import source |
| Remove from `TRANSITIONAL_BOUNDARY_PATHS` | 194 | Loader drops transitional exemption (set becomes empty after this PR — Plaid migration already removed `providers.plaid_loader`) |
| Remove `BOUNDARY_BANNED_NAMES["providers.snaptrade_loader"]` | 206 | Stale; file gone |
| Remove `_BOUNDARY_EXPORT_SOURCES["providers.snaptrade_loader"]` | 217 | Expected-exports check no longer runs |
| **TRANSFER** `_BOUNDARY_INTERNAL_RULES["brokerage.snaptrade"]["files"]` from loader to services | 236 | `services/snaptrade_portfolio_loader.py` is the new (and only) external file allowed to import private brokerage internals |
| Remove `_BOUNDARY_INTERNAL_RULES["providers.snaptrade_loader"]` entirely | 254–257 | Whole package-rule block gone |

**Baseline expectation:** no shrink. The loader was itself a boundary package, not a baselined violator.

---

## 8. Rollout order + reviewer checkpoints

**Single atomic PR** covering Phases 1–6 (Codex R1 finding #7 confirmed atomic is correct; PR0 dead-code-rebind removal would break live functions because the rebind block makes them resolve correctly).

Reviewer checkpoints:
1. Phase 1: `services/snaptrade_holdings_service.py` imports cleanly; zero SDK imports; includes `_map_snaptrade_code_to_internal` (per Codex R1 finding #3).
2. Phase 2: `services/snaptrade_portfolio_loader.py` carries the wrapper signature for `fetch_snaptrade_holdings` (§4.3); imports private retry helpers via explicit `brokerage.snaptrade.client` paths (§4.4); secret-rotation flow byte-identical.
3. Phase 3: 4 production callers updated; `brokerage/snaptrade/__init__.py` `__all__` shrunk by 5; broader grep sweep (3 single-line patterns + 1 AST verifier script in §6 validation block) returns zero hits — AST verifier is required because single-line grep cannot catch multiline `from brokerage.snaptrade import (...)` blocks (Codex R4 finding #3).
4. Phase 4: 6 test files migrated; per-line patch-string retargeting matches the table in Phase 4 step 6; integration tests have `@pytest.mark.real_provider`.
5. Phase 5: `providers/snaptrade_loader.py` deleted; 4 doc-snippet edits applied to active guides; CI workflow trimmed; archived docs left alone.
6. Phase 6: 9 `_lint.py` changes applied including the line-236 TRANSFER (§4.4 Option C); regenerated Rule B baseline (expected unchanged).

---

## 9. Risk and mitigation

| Risk | Mitigation |
|---|---|
| Breaking a caller I missed | Codex R1 broader grep found no production callers beyond the 4 listed. Phase 3 exit criteria run 3 single-line grep patterns + 1 AST verifier script (the AST verifier catches multiline imports the single-line grep would miss — Codex R4 finding #3). |
| §4.4 Option C creates a "boundary-adjacent" services file (architectural compromise) | Documented explicitly; future V1c PR can promote private→public retry wrappers and remove the allowlist transfer. Net change in this PR: same number of external files (1) reach into private brokerage internals, just at a new location. |
| `fetch_snaptrade_holdings` signature mismatch causes TypeError on `providers/snaptrade_positions.py:38-42` | §4.3 signature lock — services version adopts wrapper signature. Caller works unchanged. Same applies to test #3 (`tests/providers/test_snaptrade_positions.py`) which uses identical wrapper signature in its fake. |
| `_map_snaptrade_code_to_internal` left behind in loader → `fetch_snaptrade_holdings` AttributeError after move | Phase 1 step 1 explicitly includes it; Phase 2 step 3 imports it from holdings_service. Codex R1 finding #3 prevented this miss. |
| Test #6 (`tests/api/test_snaptrade_integration.py`) has 15 patch-string retargets — error-prone | Per-line table in Phase 4 step 6 with explicit reasoning per row + 2 assertion rewrites (line 423 because `_call_with_secret_rotation` short-circuits the callback per Codex R5 finding #1; line 484 keyword-form). Reviewer can diff line-by-line. |
| `tests/snaptrade/test_snaptrade_integration.py` SDK-introspection patterns can't be replaced | Drop v1's "use is_snaptrade_available()" suggestion (Codex R1 finding #6). Retarget patches via `importlib.import_module("brokerage.snaptrade.client")` for static-AST bypass (the `@pytest.mark.real_provider` marker is a separate runtime-fixture exemption, NOT a lint exemption — Codex R2 finding #2 + R3 finding #6). |
| Patching `brokerage.snaptrade.client.get_snaptrade_client` (banned name on package init) at runtime — does lint flag? | The banned-name rule applies to imports (`from brokerage.snaptrade import get_snaptrade_client`), not to runtime patch strings. Submodule attribute access (`brokerage.snaptrade.client.get_snaptrade_client`) bypasses the ban. Verify Rule B handling during Phase 4; if lint flags, mark the test file as exempt. |
| Pre-existing partial circular import (`brokerage/snaptrade/__init__.py` ⇄ `providers/snaptrade_loader.py`) | Removing the lazy wrappers (Phase 3) + deleting the loader (Phase 5) eliminates the cycle entirely. Document in commit message. |
| Doc updates (Phase 5 step 2) miss snippets | 4 specific lines listed; use Edit not Write per memory rule. CHANGELOG.md and `docs/planning/completed/*` are explicitly excluded as historical. |
| CI workflow drop (Phase 5 step 4) silently breaks public-mirror sync | Workflow currently copies `providers/snaptrade_loader.py` to a public mirror. After deletion, the `cp ... 2>/dev/null || true` line fails benign (`||true`). Cleaning lines 17 + 81 is hygiene — verify no dependent path. |
| Adapter (`brokerage/snaptrade/adapter.py`) self-violation reintroduces during this work | Out of scope; V3 already verified clean (TODO.md V3 row, 2026-04-23). Phase 3 changes don't touch adapter. |
| `load_all_user_snaptrade_holdings` body silently keeps positional `client` arg → TypeError after migration (Codex R2 finding #1) | Phase 2 step 5 explicitly converts to keyword. Reviewer checklist + AST grep at Phase 3 exit covers regression; new test `test_snaptrade_portfolio_loader.py` test (c) and (d) exercises both `client=None` and `client=<provided>` paths. |
| Test `patch()` strings retargeted at the wrong module → mocks don't take effect → tests pass spuriously or fail mysteriously (Codex R2 findings #3, #4) | Phase 4 step 6 table cites the specific bound-name location in each consuming module (e.g., `brokerage/snaptrade/users.py:14` for `store_snaptrade_user_secret`). Lines 159/170/423/434 marked "VERIFY DURING IMPL" because the test method's body must be read to determine which orchestrator's bound name applies. |
| Lint exemption mechanism misunderstood — assuming `@pytest.mark.real_provider` exempts Rule B (Codex R2 finding #2) | Documented in Phase 4 lint-exemption note: `importlib.import_module(...)` bypasses static AST; the marker is for the runtime fixture only. Both are independent. |
| Multiline `from brokerage.snaptrade import (...)` block missed by single-line grep (Codex R2 finding #5) | Phase 3 exit criteria includes AST verification script; reviewer can run it locally. |
| Stale doc/comment references in `utils/security_type_mappings.py:18`, `docs/reference/DATA_SCHEMAS.md:2673`, `frontend/packages/ui/src/ARCHITECTURE.md:645` (Codex R2 finding #6) | Phase 5 step 3+4 explicitly updates each. `docs/TODO.md:249` deliberately left as-is (it's the description of THIS work item, valid until ship marks it done). |
| Patch-where-it's-used misses on `load_all_user_snaptrade_holdings` test stack — orchestrator binds names locally, so all 5 decorators (lines 448, 457–460) target `services.snaptrade_portfolio_loader.*` not the definition modules (Codex R3 findings #1, #2). Plus `mock_fetch.assert_called_once_with` at line 484 must use `client=mock_client` keyword form (Codex R3 finding #3) | Phase 4 step 6 table now locks each target with explicit reasoning; assertion update called out separately. |
| Line 423 mocks `get_snaptrade_user_secret` for `remove_snaptrade_connection` but the extracted code uses `_call_with_secret_rotation` (Codex R3 finding #4 + R4 finding #2 + R5 finding #1; line 170's `create_snaptrade_connection_url` is a different code path that uses `register_snaptrade_user`, resolved separately) | Phase 4 step 6 table line 423 retargets to `brokerage.snaptrade.connections._call_with_secret_rotation` AND requires rewriting the assertion at test lines 426–430 (the existing `mock_client.connections.remove_brokerage_authorization.assert_called_once_with(...)` will not hold once the rotation helper is mocked). Line 170 retargets to `brokerage.snaptrade.users.get_snaptrade_user_secret` (where `register_snaptrade_user` looks it up) — same target as line 159, no assertion change needed. |
| `tests/snaptrade/test_snaptrade_recovery.py:401, 417` use positional `client` arg in `fetch_snaptrade_holdings(...)` calls — silent breakage after §4.3 wrapper signature (Codex R3 finding #5) | Phase 4 step 4 explicit edit required: convert both call sites to `client=client` keyword form. |

---

## 10. Decisions (locked per Codex R1)

1. **Atomic PR vs shim** → **Atomic, no shim** (Codex R1 finding #7 confirms). The loader is overwhelmingly dead code; a shim has no value. PR0 dead-code-rebind removal would break live functions because the rebind block is what makes them resolve correctly today.
2. **Two services files vs one** → **Two** (`snaptrade_holdings_service.py` pure-logic + `snaptrade_portfolio_loader.py` orchestrator).
3. **`brokerage.snaptrade` lazy-import wrappers + business-logic `__all__` exports** → **Remove** (preserves right dependency direction).
4. **§4.4 retry-helper dilemma** → **Option C** (transfer boundary-internal allowlist entry from loader to services). Codex R1 recommended this as "the safer mechanical split"; defer Option B (public wrapper expansion) to a future V1c PR.
5. **`fetch_snaptrade_holdings` signature** → **Wrapper signature** (`user_email, region_name='us-east-1', *, client=None, budget_user_id=None`), absorbing the wrapper's `_require_snaptrade_client()` resolution into the services orchestrator. Bare loader signature is gone.
6. **`_map_snaptrade_code_to_internal` placement** → **Move to `services/snaptrade_holdings_service.py`** (Codex R1 finding #3 confirmed live, called at loader line 993).
7. **`tests/snaptrade/test_snaptrade_integration.py` migration** → Drop v1's "use `is_snaptrade_available()`" (Codex R1 finding #6) AND v2's "real_provider exempts lint" claim (Codex R2 finding #2). Correct mechanism: **`importlib.import_module(...)`** for static-AST bypass + `@pytest.mark.real_provider` for runtime fixture exemption. Both are independent.
8. **Patch-where-it-is-used** (Codex R2 findings #3, #4) → all `patch()` strings retargeted at the BOUND NAME in the consuming module, not at the defining module. Concrete table in Phase 4 step 6.
9. **Multiline-aware grep** (Codex R2 finding #5) → AST verification script in Phase 3 exit criteria; single-line `grep -E` insufficient.
10. **Doc updates** → **In same PR** for active guides (`BROKERAGE_ADMIN.md`, `AWS_SECRETS_MANAGER_MIGRATION_GUIDE.md`) + 3 stale references (Codex R2 finding #6: `utils/security_type_mappings.py:18`, `docs/reference/DATA_SCHEMAS.md:2673`, `frontend/packages/ui/src/ARCHITECTURE.md:645`). Archived docs (`docs/planning/completed/`, `CHANGELOG.md`, `docs/TODO.md:249` work-item row) left alone. CI workflow cleaned.

---

## 11. Size estimate

- Phase 1 (holdings_service): ~280 LoC moved (4 pure-logic functions + imports)
- Phase 2 (portfolio_loader): ~600 LoC moved (4 orchestrator/pipeline functions + imports + signature absorption per §4.3)
- Phase 3 (production callers + brokerage init): ~30 LoC net across 4 files + ~80 LoC removed from `brokerage/snaptrade/__init__.py`
- Phase 4 (test migration): ~70 LoC net across 6 test files (1 deleted, 5 modified — including 15 patch-string retargets + 2 assertion rewrites in test #6 (line 423 + line 484), plus 2 positional→keyword call-site fixes in `test_snaptrade_recovery.py`)
- Phase 5 (delete loader + docs + CI): ~2,110 LoC deleted + ~12 LoC across 2 doc files + 2 CI-workflow lines
- Phase 6 (lint cleanup): ~15 LoC removed + 1 line transferred in `_lint.py`
- New tests: ~180 LoC (`test_snaptrade_holdings_service.py` ~60 + `test_snaptrade_portfolio_loader.py` ~120)

**Total**: ~870 LoC moved net (2,110 loader LoC ↔ ~870 services LoC; diff shows roughly +870/-2,180 with lint + test + doc + CI changes). Single atomic PR. ~6–8 hour implementation, expect 1 more Codex review round.
