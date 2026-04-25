# Vendor Plaid Loader Split — V1 (plaid slice)

**Parent:** `docs/TODO.md` V1 · Vendor SDK Boundary Refactor Lane 2
**Sibling plan:** `IBKR_CONTRACT_SPEC_BOUNDARY_PLAN.md` (V5, shipped 2026-04-24) established the pattern
**Date:** 2026-04-24
**Status:** Draft (v4 — addresses Codex R3 FAIL: fake module needs `get_investments_transactions`, log-source labels `log_error("plaid_loader", ...)` in `brokerage/plaid/client.py` are operational and intentionally preserved)

---

## 1. Problem

`providers/plaid_loader.py` (1,075 LoC, 14 functions) is labeled a "transitional boundary file" in the Rule A/B lint system (`tests/api_budget/_lint.py`). The original $342-unexpected-Plaid-bill incident (2026-04-16) traced to `load_all_user_holdings` here calling `/accounts/balance/get` redundantly — that specific bug was fixed in `fa44224d`, but the structural problem (business logic entangled with SDK orchestration in a boundary file) remains.

The `brokerage/plaid/` package (899 LoC across 4 files) was already extracted in the vendor-SDK boundary refactor (PR #7, `3dbc0774`) and owns all pure SDK concerns:
- `client.py` — link tokens, holdings fetch, balances fetch, institution/item info, transactions
- `connections.py` — remove connection/institution
- `secrets.py` — AWS Secrets Manager
- `__init__.py` — public exports (re-exports 4 business-logic functions from `plaid_loader`)

What remains in `providers/plaid_loader.py` is **pure business logic** (DataFrame normalization, cash-gap detection, type mapping, YAML conversion) plus **one orchestrator** (`load_all_user_holdings`) and **one export pipeline** (`convert_plaid_holdings_to_portfolio_data`). None of this belongs in a "boundary file." All of it belongs in `services/`.

Today's violations the split eliminates:
- `providers.plaid_loader` appears as a boundary package in 6 different `_lint.py` data structures (BOUNDARY_PACKAGE_PATHS, TRANSITIONAL_BOUNDARY_PATHS, BOUNDARY_BANNED_NAMES, _BOUNDARY_EXPORT_SOURCES, _BOUNDARY_INTERNAL_RULES, plus 4 VENDOR_BOUNDARY_ALLOWLIST entries for plaid vendor packages)
- `brokerage/plaid/__init__.py:22-27` re-exports 4 business-logic functions from the loader — a transport boundary importing from a business layer (wrong dependency direction)
- Direct loader callers (3 files): `routes/provider_routing.py:452, 504`; `providers/plaid_positions.py:30`
- **Indirect callers via `brokerage.plaid` re-exports (3 more, caught by Codex R1)**: `routes/plaid.py:135` (`convert_plaid_df_to_yaml_input`), `services/position_service.py:1617` (`consolidate_holdings`), `tests/providers/test_plaid_loader.py:7` (`calc_cash_gap`, `patch_cash_gap_from_balance`)
- **Pre-existing circular import**: `providers.plaid_loader` → `brokerage.plaid.client` → `brokerage.plaid.__init__` → `providers.plaid_loader` (back-reference via the 4 re-exports). Module load today only succeeds because Python handles partial-init imports gracefully for the top-level function-reference pattern. This split eliminates that cycle.

---

## 2. Goal

Move all business logic out of `providers/plaid_loader.py` into `services/` and delete the loader file. `brokerage/plaid/` stops re-exporting business logic. Lint boundary entries for `providers.plaid_loader` go away entirely.

Target outcome:
- `providers/plaid_loader.py` deleted
- `services/plaid_holdings_service.py` (new) owns normalization + cash-gap + type mapping (pure logic, no SDK imports)
- `services/plaid_portfolio_loader.py` (new) owns orchestrator + export pipeline (imports from `brokerage.plaid` for SDK work)
- `brokerage/plaid/__init__.py` removes its 4 back-compat re-exports; `brokerage/plaid/` becomes purely SDK
- All callers import from `services.plaid_*` directly
- 6+ entries removed from `_lint.py`
- Rule A vendor allowlist entries for plaid/plaid.api/plaid.model/plaid_api drop `providers/plaid_loader.py` (4 entries; `providers/plaid_positions.py` stays — it still imports `plaid` for the `fetch_positions` adapter path until a future slice)

---

## 3. Non-Goals

This plan does **not**:
- Refactor `brokerage/plaid/` internals (SDK wrappers stay as-is)
- Refactor `providers/plaid_positions.py` internals (still imports plaid SDK for its fetch_positions adapter; switch targets change only)
- Touch `providers/snaptrade_loader.py` — that's a separate plan (V1 snaptrade slice)
- Change function signatures of the moved business logic (byte-identical behavior preserved)
- Change `BOUNDARY_BANNED_NAMES` for `brokerage.plaid` (Rule A protection for `client` / `create_client` stays)
- Implement the missing `get_user_plaid_holdings` / `get_user_plaid_accounts` functions — see Phase 3 sub-step for how we handle the stale-import path cleanly (replace body with `raise NotImplementedError` so the reachable-but-broken path fails explicitly instead of `ImportError`-ing)

---

## 4. Target architecture

### 4.1 File layout after split

```
services/
  plaid_holdings_service.py     (NEW — pure DataFrame logic, no SDK imports)
  plaid_portfolio_loader.py     (NEW — orchestrator + pipeline, imports brokerage.plaid)

brokerage/plaid/                (UNCHANGED — SDK-only, business-logic re-exports removed from __init__)
  __init__.py                   (MODIFIED — drop 4 providers.plaid_loader re-exports)
  client.py                     (UNCHANGED)
  connections.py                (UNCHANGED)
  secrets.py                    (UNCHANGED)

providers/
  plaid_loader.py               (DELETED)
  plaid_positions.py            (MODIFIED — update one import)

routes/
  plaid.py                      (MODIFIED — swap brokerage.plaid import to services.plaid_portfolio_loader)
  provider_routing.py           (MODIFIED — fix stale imports at :452, :504 to explicit NotImplementedError)

services/
  position_service.py           (MODIFIED — swap brokerage.plaid import to services.plaid_portfolio_loader)

tests/
  providers/test_plaid_loader.py → tests/services/test_plaid_holdings_service.py (RENAMED + imports updated)
```

### 4.2 Function placement

**`services/plaid_holdings_service.py`** — pure logic, no SDK:
- `normalize_plaid_holdings(holdings: list, securities: list) -> pd.DataFrame`
- `_as_finite_float` (private helper)
- `calc_cash_gap(df_acct, balances, tol)`
- `append_cash_gap(df_acct, gap, balances)`
- `should_skip_cash_patch(df_acct)`
- `patch_cash_gap_from_balance(df, balances, institution, verbose)`
- `_load_maps` (private)
- `map_cash_to_proxy(df, yaml_path)`
- `_map_plaid_type_to_internal` (private)
- `get_enhanced_security_type(ticker, original_type)`

**`services/plaid_portfolio_loader.py`** — orchestrator + export, imports `brokerage.plaid`:
- `load_all_user_holdings(user_id, region_name)` — the $342-bill original lived here; now clearly in the services layer
- `consolidate_holdings(df)`
- `convert_plaid_df_to_yaml_input(...)`
- `convert_plaid_holdings_to_portfolio_data(holdings_df, user_email, portfolio_name)`

### 4.3 Dependency direction after split

```
brokerage/plaid/                           (SDK boundary — pure)
     ↑
services/plaid_portfolio_loader.py         (orchestrator)
     ↑       ↖
services/plaid_holdings_service.py  (pure logic, standalone)
     ↑
callers: routes/, providers/plaid_positions.py
```

`brokerage/` stops depending on `providers/`. `services/` depends on `brokerage/` (correct direction). Pure-logic service has no upward deps.

---

## 5. Phased plan

### Phase 1: Create `services/plaid_holdings_service.py` (pure logic)

1. Copy the 10 pure-logic functions from `providers/plaid_loader.py` into the new file:
   - `normalize_plaid_holdings`, `_as_finite_float`, `calc_cash_gap`, `append_cash_gap`, `should_skip_cash_patch`, `patch_cash_gap_from_balance`, `_load_maps`, `map_cash_to_proxy`, `_map_plaid_type_to_internal`, `get_enhanced_security_type`
2. Preserve all imports they need (`pandas`, `core.cash_helpers`, `services.security_type_service`, `brokerage._logging`, yaml lib). NO plaid SDK imports should appear.
3. Preserve `SecurityTypeService` lazy-import fallback pattern (the `try: from services.security_type_service import SecurityTypeService / except ImportError: SecurityTypeService = None` block).
4. **No shim, atomic PR** (Codex R1 decision): do NOT ship a temporary re-export shim in `providers/plaid_loader.py`. All phases land atomically in a single commit — services files created, callers updated, loader deleted, lint entries removed, all in one logical PR. Rationale (from R1): any shim must preserve the full public surface (including SDK re-exports `create_hosted_link_token`, `list_user_tokens`, `AWS_REGION`, etc.) or partial-shim PRs silently break consumers. Atomic is safer.

**Exit criteria**: new service module imports cleanly (`python3 -c "from services.plaid_holdings_service import calc_cash_gap"`); the file has zero imports from `plaid`, `plaid_api`, `plaid.api`, `plaid.model`.

### Phase 2: Create `services/plaid_portfolio_loader.py` (orchestrator + pipeline)

1. Copy 4 functions from `providers/plaid_loader.py`:
   - `load_all_user_holdings`, `consolidate_holdings`, `convert_plaid_df_to_yaml_input`, `convert_plaid_holdings_to_portfolio_data`
2. Update imports in the new file:
   - `from brokerage.plaid import fetch_plaid_holdings, get_plaid_token, list_user_tokens` (replaces the in-file imports)
   - `from services.plaid_holdings_service import normalize_plaid_holdings, patch_cash_gap_from_balance, consolidate_holdings, convert_plaid_df_to_yaml_input, get_enhanced_security_type`
   - Wait — `consolidate_holdings` and `convert_plaid_df_to_yaml_input` live in portfolio_loader, not holdings_service, per §4.2. Adjust: import only cross-module helpers (`normalize_plaid_holdings`, `patch_cash_gap_from_balance`, `get_enhanced_security_type`) from holdings_service.
3. Atomic PR (no shim, per Phase 1 decision) — phases 2-5 land together in one commit.

**Exit criteria**: new portfolio loader imports cleanly; `load_all_user_holdings` still returns the same DataFrame shape on a test invocation (spot-check with any connected Plaid user if available, else structural smoke via import graph).

### Phase 3: Update all callers (6 files — Codex R1 expanded the inventory)

**Direct loader callers (3 files):**

1. **`providers/plaid_positions.py:30`** — change:
   ```python
   from providers.plaid_loader import load_all_user_holdings
   ```
   to:
   ```python
   from services.plaid_portfolio_loader import load_all_user_holdings
   ```

2. **`routes/provider_routing.py:452`** — fix the stale import path cleanly (Codex R1 Critical 2: do NOT leave `get_user_plaid_holdings` as a ghost import — it's reachable via `get_holdings_with_fallback()`). Replace the whole `_fetch_plaid_holdings` body with an explicit `raise NotImplementedError(...)` so invocation fails explicitly rather than `ImportError`-ing on a nonexistent function:
   ```python
   async def _fetch_plaid_holdings(user_id: int, portfolio_name: str) -> PortfolioData:
       """Plaid holdings fallback — see V1b for implementation or removal decision."""
       raise NotImplementedError(
           "Plaid holdings fallback is not implemented. "
           "The previous stub referenced a nonexistent get_user_plaid_holdings function. "
           "Track V1b in docs/TODO.md for disposition (implement vs remove)."
       )
   ```
   Remove both `from providers.plaid_loader import ...` lines (they're no longer needed). Same treatment for `_fetch_plaid_connections` at `:502-520`.
   **Net behavior change**: zero — today the path ImportErrors at invocation; after this PR it NotImplementedErrors. Both are runtime failures, but the new error is explicit and no longer pretends to have a real implementation.

**Indirect callers via `brokerage.plaid` re-exports (3 files — Codex R1 Critical 1):**

3. **`routes/plaid.py:135`** — update the `from brokerage.plaid import (...)` block: move `convert_plaid_df_to_yaml_input` to a separate import line:
   ```python
   from services.plaid_portfolio_loader import convert_plaid_df_to_yaml_input
   ```
4. **`services/position_service.py:1617`** — change `from brokerage.plaid import consolidate_holdings` to:
   ```python
   from services.plaid_portfolio_loader import consolidate_holdings
   ```
5. **`tests/providers/test_plaid_loader.py`** — **RENAME** to `tests/services/test_plaid_holdings_service.py` and update import:
   ```python
   # from brokerage.plaid import calc_cash_gap, patch_cash_gap_from_balance
   from services.plaid_holdings_service import calc_cash_gap, patch_cash_gap_from_balance
   ```
   Keep test cases intact — pure-logic tests don't need to change.

6. **`tests/trading_analysis/test_provider_routing.py:104`** (Codex R2 Critical 1) — the test injects a fake module via `monkeypatch.setitem(sys.modules, "providers.plaid_loader", plaid_loader)`. After loader deletion this mock target is gone. The code under test (`trading_analysis/data_fetcher.py:405`) actually imports `get_investments_transactions`, `get_plaid_token`, `list_user_tokens` from `brokerage.plaid`, so the mock target was already incorrect. Fix by changing the injection target AND expanding the fake module's surface (Codex R3 caught the incomplete shape):
   ```python
   # Before:
   monkeypatch.setitem(sys.modules, "providers.plaid_loader", plaid_loader)
   # After:
   monkeypatch.setitem(sys.modules, "brokerage.plaid", plaid_loader)
   ```
   And ensure `plaid_loader` (the fake module object) exposes **all three** names that `data_fetcher.py:405` imports:
   - `get_investments_transactions` (NEW — the existing fake only had `get_plaid_token` + `list_user_tokens`)
   - `get_plaid_token`
   - `list_user_tokens`
   The fake's `get_investments_transactions` should mirror the public-wrapper shape in `brokerage/plaid/client.py:488`.

**`brokerage/plaid/__init__.py`** — drop these 4 lines + their entries from `__all__`:
```python
from providers.plaid_loader import (
    calc_cash_gap,
    consolidate_holdings,
    convert_plaid_df_to_yaml_input,
    patch_cash_gap_from_balance,
)
```
After step 3-5 above land, these have zero in-repo consumers (verified twice — once by grep, once by Codex R1 re-sweep). `brokerage/plaid/` becomes purely SDK after the removal.

**Exit criteria (import-focused grep — Codex R2 Critical 2 noted comments/log-labels still reference `plaid_loader` in several files; those are cosmetic and not in V1 scope)**:
- `grep -RIn "from providers\.plaid_loader\|import providers\.plaid_loader\|sys\.modules.*providers\.plaid_loader" --include="*.py" .` returns zero Python hits (no import-level references)
- `grep -RIn "from brokerage\.plaid import" --include="*.py" .` → no remaining hits for the 4 business-logic names (`calc_cash_gap`, `consolidate_holdings`, `convert_plaid_df_to_yaml_input`, `patch_cash_gap_from_balance`)
- `pytest tests/services/test_plaid_holdings_service.py` passes (renamed file imports from new location)
- `pytest tests/services/test_plaid_portfolio_loader.py` passes (new orchestrator tests)
- `pytest tests/trading_analysis/test_provider_routing.py` passes (sys.modules injection re-targeted to `brokerage.plaid`)
- Comments/docstrings mentioning `plaid_loader` in `routes/plaid.py`, `services/position_service.py`, `services/security_type_service.py`, `utils/security_type_mappings.py` are **NOT** required to change in V1 — cosmetic-only references, file as V1b cleanup.
- **Operational log-source labels `log_error("plaid_loader", ...)` at `brokerage/plaid/client.py:328` and `:416` are intentionally preserved** (Codex R3 Critical 3). These are operational log tags that may be referenced by ops runbooks, dashboards, or log-search queries; changing them silently would break those downstream consumers. V1b may re-label these if renamed in tandem with a runbook update, but not this PR.

### Phase 4: Delete `providers/plaid_loader.py`

1. `rm providers/plaid_loader.py`
2. Verify: `grep -rn "providers.plaid_loader\|providers/plaid_loader" <repo>` → only docs + `_lint.py` + `rule_b_baseline.json` should remain.

**Exit criteria**: loader file gone; no ImportError anywhere; affected tests still green.

### Phase 5: Lint allowlist cleanup

Remove `providers.plaid_loader` / `providers/plaid_loader.py` from all 6 `_lint.py` data structures:

1. **`BOUNDARY_PACKAGE_PATHS`** (line 193) — remove `"providers.plaid_loader"`
2. **`TRANSITIONAL_BOUNDARY_PATHS`** (line 199) — remove `"providers.plaid_loader"`
3. **`BOUNDARY_BANNED_NAMES`** (line 211) — remove full `"providers.plaid_loader": frozenset({"client", "create_client"})` entry
4. **`_BOUNDARY_EXPORT_SOURCES`** (line 223) — remove full `"providers.plaid_loader": REPO_ROOT / "providers" / "plaid_loader.py"` entry
5. **`_BOUNDARY_INTERNAL_RULES["brokerage.plaid"]["files"]`** (line 229) — remove `"providers/plaid_loader.py"` (keep `"providers/plaid_positions.py"`)
6. **`_BOUNDARY_INTERNAL_RULES["providers.plaid_loader"]`** (lines 261-264) — remove entire entry

Remove `providers/plaid_loader.py` from 4 `VENDOR_BOUNDARY_ALLOWLIST` entries (Rule A):

7. **`VENDOR_BOUNDARY_ALLOWLIST["plaid"]`** (line 34)
8. **`VENDOR_BOUNDARY_ALLOWLIST["plaid.api"]`** (line 43)
9. **`VENDOR_BOUNDARY_ALLOWLIST["plaid.model"]`** (line 52)
10. **`VENDOR_BOUNDARY_ALLOWLIST["plaid_api"]`** (line 61)

Then regenerate Rule B baseline: `scripts/generate_rule_b_baseline.py`.

**Exit criteria**:
- 10 total allowlist removals applied
- `pytest tests/api_budget/` — Rule A + Rule B tests pass
- Rule B baseline **may be unchanged** (loader had no baseline entries since it was itself a TRANSITIONAL boundary; baseline-checked imports were from external files TO the loader, and those external files' imports all got migrated to services/ in Phase 3). Document in commit message.
- Reintroducing `from providers.plaid_loader import anything` anywhere in the repo now fails with ImportError (file gone) + any attempt to recreate the file and import plaid SDK there fails Rule A lint (allowlist entries removed).

---

## 6. Test strategy

### Test migration
- **`tests/providers/test_plaid_loader.py`** exists (verified by Codex R1) → **RENAME** to `tests/services/test_plaid_holdings_service.py` and update `from brokerage.plaid import ...` at line 7 to `from services.plaid_holdings_service import ...`. All existing test cases preserved.

### New tests
- `tests/services/test_plaid_portfolio_loader.py` — orchestrator happy path with mocked `fetch_plaid_holdings` + `list_user_tokens` + `get_plaid_token` (from `brokerage.plaid`). Validates `load_all_user_holdings` return shape + per-account loop + `patch_cash_gap_from_balance` delegation.

### Regression guards
- Any existing integration test that hits `load_all_user_holdings` end-to-end (via mocked Plaid client) should still pass unchanged — the signature + return shape are preserved.

### Validation commands per phase
```bash
# Phase 1 smoke
python3 -c "from services.plaid_holdings_service import calc_cash_gap; print('OK')"

# Phase 2 smoke
python3 -c "from services.plaid_portfolio_loader import load_all_user_holdings; print('OK')"

# Phase 3 grep sweep
grep -rn "from providers.plaid_loader" --include="*.py" .

# Phase 4+5 full
pytest tests/ -x
pytest tests/api_budget/
```

---

## 7. Rule A / Rule B allowlist interactions

| Change | Line(s) | Effect |
|---|---|---|
| Remove `providers.plaid_loader` from `BOUNDARY_PACKAGE_PATHS` | 193 | Rule B no longer treats loader as a valid import source |
| Remove from `TRANSITIONAL_BOUNDARY_PATHS` | 199 | Loader drops transitional exemption |
| Remove from `BOUNDARY_BANNED_NAMES` | 211 | `client` / `create_client` no longer need banning here (file gone) |
| Remove from `_BOUNDARY_EXPORT_SOURCES` | 223 | Expected-exports check no longer runs for this package |
| Remove `providers/plaid_loader.py` from `_BOUNDARY_INTERNAL_RULES["brokerage.plaid"]["files"]` | 229 | `brokerage.plaid` internal-module imports no longer legal from loader (file doesn't exist anyway) |
| Remove `_BOUNDARY_INTERNAL_RULES["providers.plaid_loader"]` entirely | 261-264 | Whole package-rule block gone |
| Remove `providers/plaid_loader.py` from 4 `VENDOR_BOUNDARY_ALLOWLIST` entries | 34, 43, 52, 61 | Reintroducing the file with plaid SDK imports now fails Rule A |

**Baseline expectation**: no shrink. The loader was itself a boundary package, not a baselined violator.

---

## 8. Rollout order + reviewer checkpoints

**Single PR** covering Phases 1-5. Reviewer checkpoints:

1. After Phase 1: "does `services/plaid_holdings_service.py` import without needing any `plaid.*` SDK?"
2. After Phase 2: "does `services/plaid_portfolio_loader.py` import `fetch_plaid_holdings` etc. from `brokerage.plaid` public boundary (not from internal modules)?"
3. After Phase 3: three grep sweeps return zero Python hits — direct imports (`from providers.plaid_loader`), indirect business-logic imports (`from brokerage.plaid import` of the 4 names), AND `sys.modules` injection (`sys\.modules.*providers\.plaid_loader`). Verify `routes/provider_routing.py` `_fetch_plaid_holdings` + `_fetch_plaid_connections` bodies raise `NotImplementedError` with no remaining import of the stale names. Verify `tests/trading_analysis/test_provider_routing.py` `monkeypatch.setitem` target is `brokerage.plaid` (not `providers.plaid_loader`).
4. After Phase 4: `providers/plaid_loader.py` file gone from git + tree
5. After Phase 5: all 10 `_lint.py` removals applied; regenerated Rule B baseline in commit; Rule A lint rejects reintroduced plaid SDK imports into a recreated loader file

**All five phases land in a single atomic PR** — per Codex R1 decision (Answer to Q1). No shim. No PR B. Rationale: any shim needs to preserve the full public surface including SDK re-exports; partial shim silently breaks. Atomic is safer for a refactor where the existing file has a pre-existing circular import.

---

## 9. Risk and mitigation

| Risk | Mitigation |
|---|---|
| Breaking a caller I missed during grep | Codex R1 caught 3 indirect callers via `brokerage.plaid` re-exports (Critical 1) — §5 Phase 3 now covers 6 files total. Exit-criteria greps cover both direct (`from providers.plaid_loader`) AND indirect (`from brokerage.plaid import <business_func>`) patterns. |
| SecurityTypeService circular import | Lazy-import pattern preserved in new file (same try/except idiom as loader) |
| YAML config path `cash_map.yaml` breaks on cwd change | `_load_maps` accepts path arg with default — new location shouldn't change cwd semantics, but verify by running `map_cash_to_proxy` with default arg from a test that runs from repo root |
| `brokerage/plaid/__init__.py` consumers outside this repo break | Cross-repo search verified this repo is source of truth; `brokerage.plaid` is PyPI-synced but the 4 re-exports were only ever used internally per grep. Document in commit message as potential breaking change for downstream consumers. |
| Stale `get_user_plaid_holdings` / `get_user_plaid_accounts` imports are reachable via `get_holdings_with_fallback()` and `get_connections_with_fallback()` (Codex R1 Critical 2) | Phase 3 replaces bodies of `_fetch_plaid_holdings` + `_fetch_plaid_connections` with explicit `raise NotImplementedError(...)` — same runtime behavior (both were broken), but failure is now explicit. File V1b to decide implement-vs-remove. |
| Rule B baseline test fails at Phase 5 | Regenerate via `scripts/generate_rule_b_baseline.py` and diff; strict-equality assertion will show any unexpected entries |

---

## 10. Decisions (resolved in Codex R1)

1. **Shim strategy** → **Atomic PR, no shim**. Rationale: any shim must preserve full public surface (including SDK re-exports `create_hosted_link_function`, `list_user_tokens`, `AWS_REGION`); partial shim silently breaks. The pre-existing circular import in `providers.plaid_loader` also means "loader imports cleanly" is not a reliable Phase 1 checkpoint.
2. **Two services files** → **Keep two** (`plaid_holdings_service.py` pure-logic + `plaid_portfolio_loader.py` orchestrator). One file couples orchestration and pure transformation unnecessarily; three files over-fragments for this slice.
3. **`brokerage.plaid` back-compat re-exports** → **Remove** (preserves right dependency direction; `brokerage/` stops importing from `providers/`). First update all internal consumers (Phase 3 covers all 3 indirect callers Codex R1 caught).
4. **Stale routing imports** → **Fix in V1** by replacing bodies with `raise NotImplementedError(...)`. Zero runtime behavior change (both states fail at invocation), but the new failure is explicit. Avoids leaving a reachable-but-broken path.
5. **V1b scope** → Cleanup of the Plaid fallback routing handlers in `routes/provider_routing.py:438-540`. Either implement `get_user_plaid_holdings` / `get_user_plaid_accounts` properly or remove the fallback branch from `get_holdings_with_fallback` / `get_connections_with_fallback`. Separate plan after V1 lands.

---

## 11. Size estimate (revised per Codex R1 — more callers, no shim)

- Phase 1 (holdings_service): ~320 LoC moved (10 pure-logic functions + imports)
- Phase 2 (portfolio_loader): ~350 LoC moved (4 orchestrator/pipeline functions + imports)
- Phase 3 (callers): ~45 LoC net across 7 files — `providers/plaid_positions.py` (1 import), `routes/provider_routing.py` (2 function-body rewrites to NotImplementedError + 2 import removals), `routes/plaid.py` (1 import split), `services/position_service.py` (1 import swap), `tests/providers/test_plaid_loader.py` → `tests/services/test_plaid_holdings_service.py` (rename + 1 import swap), `tests/trading_analysis/test_provider_routing.py` (1 sys.modules target swap), `brokerage/plaid/__init__.py` (4 import + __all__ entries removed)
- Phase 4 (delete loader): ~1,075 LoC deleted (file)
- Phase 5 (lint cleanup): ~15 LoC removed from `_lint.py`
- New tests: ~80-120 LoC (`test_plaid_portfolio_loader.py` orchestrator coverage)

**Total**: ~700 LoC moved net (1,075 loader LoC ↔ ~700 services LoC; diff shows as +700/-1075 with lint changes). Single atomic PR. ~4-6 hour implementation, 1-2 Codex review rounds expected.
