# Portfolio Manager Refactor Implementation Plan

Date: 2026-02-17  
Status: In Progress (Phase 1 complete; partial progress in Phases 0/2/4)  
Scope Type: Incremental refactor (no big-bang rewrite)

## Related Documents

- `docs/planning/PORTFOLIO_MANAGER_COMPLEXITY_AUDIT.md`
- `docs/planning/TODO.md`

## Problem Statement

`inputs/portfolio_manager.py` currently mixes multiple concerns:

1. Identity/bootstrap (`user_id` resolution, DB init)
2. Persistence (DB and file CRUD)
3. Portfolio assembly (filter/consolidate/cash mapping/build `PortfolioData`)
4. Side-effect orchestration (factor proxy generation)
5. Legacy scenario/file helpers (`create_portfolio_yaml`, `create_what_if_yaml`)
6. Legacy wrappers and global singleton paths

This increases maintenance cost, hides behavior (implicit fallback/side effects), and makes call-site expectations less explicit.

## Goals

1. Preserve production behavior for authenticated API and Claude workflows during migration.
2. Split responsibilities into focused components with clear contracts.
3. Remove implicit DB->file fallback in DB-first authenticated flows.
4. Move legacy scenario/file helpers into a dedicated legacy module.
5. Make side effects explicit at orchestration layer (callers decide when to run them).

## Non-Goals

1. Rewriting risk/performance/optimization engines.
2. Changing MCP live-position architecture (`mcp_tools/risk.py` and related flows).
3. Renaming business APIs exposed to frontend or external clients.
4. Large schema/database redesign in this refactor.

## Current State Summary

1. `PortfolioManager` is 1222 lines and highly coupled (`inputs/portfolio_manager.py`).
2. API routes and Claude executor instantiate DB mode extensively (`app.py`, `services/claude/function_executor.py`).
3. CLI risk flows mostly bypass `PortfolioManager` and use `load_portfolio_config` directly.
4. MCP risk/perf/optimization build `PortfolioData` from `PositionService`, not `PortfolioManager`.
5. `ReturnsService` currently stores a `portfolio_manager` dependency and calls `get_portfolio_tickers()` + `get_expected_returns()`, so it is a key integration seam during extraction.
6. Legacy utility tests (for example `tests/utils/test_final_status.py`) may use stale signatures; treat these as explicit migration targets or isolate them from hard phase gates.

## Target Architecture

Introduce explicit components while keeping a temporary facade for compatibility.

1. `PortfolioRepository` (data access)
- DB/file load/save/list/delete
- Expected returns CRUD
- No transformation logic

2. `PortfolioAssembler` (domain transformation)
- Filter unsupported positions
- Consolidate positions
- Apply cash mapping
- Build `PortfolioData` from normalized inputs

3. `LegacyPortfolioFileService` (legacy helpers)
- `create_portfolio_yaml`
- `create_what_if_yaml`
- legacy format conversion helpers

4. `PortfolioManager` (transitional facade)
- Delegates to repository + assembler
- Maintains old method signatures during migration window

## Proposed File Layout (Incremental)

1. Add:
- `inputs/portfolio_repository.py`
- `inputs/portfolio_assembler.py`
- `inputs/legacy_portfolio_file_service.py`

2. Refactor:
- `inputs/portfolio_manager.py` (thin facade during migration)

3. Update call sites:
- `app.py`
- `services/claude/function_executor.py`
- `services/returns_service.py`
- `services/portfolio/context_service.py`

4. Tests:
- `tests/api/test_portfolio_crud.py`
- `tests/api/test_portfolio_api_crud.py`
- Add focused tests for new components under `tests/inputs/` (new)

## Migration Strategy

Use phased rollout with strict validation gates and rollback points per phase.

## Progress Update (2026-02-17)

- [x] Critical pre-work blocker fixed: wrapper contract mismatch for `update_portfolio_expected_returns`
- [x] Phase 1 core extraction implemented (`PortfolioRepository` + `PortfolioAssembler`, facade retained)
- [x] Legacy helper extraction implemented (`LegacyPortfolioFileService`)
- [x] Explicit proxy orchestration added in API create/update portfolio routes
- [x] File-mode expected returns updated to per-portfolio behavior with legacy fallback compatibility
- [x] Targeted unit tests added for repository/assembler/legacy service and CRUD regressions
- [x] Targeted smoke tests executed (manager, returns service, app bootstrap, executor flows)
- [ ] Phase 0 baseline artifacts fully captured (behavior matrix + OpenAPI baseline artifact/diff gate)
- [ ] Phase 2 wrapper/global compatibility symbol removal
- [ ] Phase 3 strict fail-fast/integer-only behavior rollout for authenticated paths
- [ ] Phase 4 compatibility side-effect path removal (`auto_ensure_proxies` internal path)
- [ ] Phase 5 final cleanup and move doc to `docs/planning/completed/`

## Safety Criteria For Removal

Removal is allowed without deprecation period when all safety checks pass:

1. Caller inventory complete and updated.
2. `rg` confirms no remaining internal call sites to removed symbols (excluding history/docs).
3. Targeted test gates pass in the validation environment.
4. Rollback path is prepared in the same PR/phase.

## Critical Pre-Work Blockers

1. Fix compatibility wrapper contract mismatch before structural refactor:
- `inputs/portfolio_manager.py::update_portfolio_expected_returns(...)` currently requires `portfolio_name`.
- Backward-compat wrapper `update_portfolio_expected_returns(expected_returns_dict, replace_all=False)` does not pass `portfolio_name`.
- This must be fixed first to prevent migrating an already-broken contract.

## Validation Environment Prerequisites

Required for all phase gates:

1. Run commands from repo root.
2. `DATABASE_URL` points to a reachable test/dev database.
3. Base schema/migrations are applied (`python3 database/run_migration.py`).
4. Python env uses project dependencies from `requirements.txt`.
5. For MCP smoke checks, set `RISK_MODULE_USER_EMAIL` to a seeded test user.
6. If a gate is intentionally run in mock-only mode, explicitly mark any skipped checks in the phase notes.

## Phase 0: Baseline and Test Hardening

### Deliverables

1. Baseline behavior matrix (documented expectations for each public method).
2. Tests covering:
- DB mode success/failure
- file fallback behavior (current behavior captured)
- proxy side-effect behavior in create/update flows
3. Wrapper compatibility bug fixed and regression-tested:
- `update_portfolio_expected_returns` wrapper forwards correct arguments
- fallback path in Claude `set_expected_returns` does not rely on a broken wrapper signature

### Tasks

1. Expand/refresh tests for current `PortfolioManager` methods.
2. Fix wrapper contract mismatch and add regression tests.
3. Record baseline commands and outputs.
4. Capture API contract baseline:
- `python3 - <<'PY' > docs/planning/baselines/openapi.portfolio-manager-refactor.baseline.json`
- `import json; from app import app; print(json.dumps(app.openapi(), sort_keys=True))`
- `PY`
5. Freeze baseline before structural changes.
6. Classify utility test scope:
- either update `tests/utils/test_final_status.py` to current signatures
- or mark as non-gating legacy utility and exclude from phase gates until fixed

### Validation Gate

1. `pytest tests/api/test_portfolio_crud.py -q`
2. `pytest tests/api/test_portfolio_api_crud.py -q`
3. `pytest tests/utils/test_claude_functions.py -q`

### Rollback

1. Revert test-only changes if baseline cannot be stabilized.

## Phase 1: Extract Repository + Assembler (No Behavior Change)

### Deliverables

1. `PortfolioRepository` implemented and used internally.
2. `PortfolioAssembler` implemented and used internally.
3. `PortfolioManager` remains external entry point with unchanged signatures.

### Tasks

1. Move DB/file CRUD logic from `PortfolioManager` to `PortfolioRepository`.
2. Move filter/consolidate/cash-map/build logic to `PortfolioAssembler`.
3. Keep orchestration in facade so call-site behavior is unchanged.
4. Add unit tests for repository and assembler classes.
5. Handle `ReturnsService` coupling explicitly:
- keep a facade-compatible dependency contract during Phase 1 so `ReturnsService` behavior does not change
- then introduce a narrow protocol/interface for returns coverage methods (`get_portfolio_tickers`, `get_expected_returns`) before any direct repository wiring
- add focused tests for `ReturnsService` coverage paths against the extracted components/facade

### Validation Gate

1. All Phase 0 tests pass unchanged.
2. New unit tests pass.
3. No API contract changes in existing routes.
4. API contract diff gate:
- `python3 - <<'PY' > /tmp/openapi.portfolio-manager-refactor.after.json`
- `import json; from app import app; print(json.dumps(app.openapi(), sort_keys=True))`
- `PY`
- `diff -u docs/planning/baselines/openapi.portfolio-manager-refactor.baseline.json /tmp/openapi.portfolio-manager-refactor.after.json`
5. Returns coverage behavior gate:
- `pytest tests/utils/test_claude_functions.py -q`
- `pytest tests/api/test_portfolio_crud.py -q` (ensure expected-returns/coverage-dependent flows unchanged)

### Rollback

1. Revert to pre-phase branch point (facade still exists, easy rollback).

## Phase 2: Isolate Legacy File/Scenario Helpers

### Deliverables

1. New `LegacyPortfolioFileService` owns scenario/file helper methods.
2. Internal callers updated to new service where practical.
3. Legacy wrapper functions removed when safety criteria are met.

### Tasks

1. Move:
- `create_what_if_yaml`
- `create_portfolio_yaml`
- format conversion helpers
2. Update first-party callers to use service/facade method signatures directly.
3. Remove wrappers/global helper exports once internal caller inventory is clean.
4. Verify no internal references remain:
- `rg -n "from inputs\\.portfolio_manager import .*create_what_if_yaml|from inputs\\.portfolio_manager import .*create_portfolio_yaml|from inputs\\.portfolio_manager import .*update_portfolio_expected_returns|from inputs\\.portfolio_manager import .*portfolio_manager|inputs\\.portfolio_manager\\.(create_what_if_yaml|create_portfolio_yaml|update_portfolio_expected_returns|portfolio_manager)" inputs services app.py tests`

### Validation Gate

1. Claude executor scenario creation path still works.
2. `tests/utils/test_claude_functions.py` passes.
3. `rg` confirms no internal imports/usages of removed wrapper symbols.

### Rollback

1. Restore removed wrapper exports only if a hard blocker appears and cannot be fixed in-phase.

## Phase 3: Behavior Tightening (DB-First Flows)

### Deliverables

1. DB mode is fail-fast by default for authenticated API/Claude flows.
2. Optional fallback only behind explicit legacy flag.
3. Constructor path expects resolved integer `user_id` for DB mode.
4. Explicit compatibility policy for non-integer `user_id` callers.

### Tasks

1. Introduce explicit fallback control (env/config flag).
2. Update DB-mode callers to pass integer `user_id` only.
3. Remove implicit string-based identity translation from core manager path.
4. Update error messages to be explicit and actionable.
5. Add migration handling for non-integer callers:
- Keep `PORTFOLIO_MANAGER_ALLOW_STRING_USER_ID=true` only for legacy/test utilities during migration.
- Update known string-ID tests/utilities to resolve to integer IDs (or mark legacy-only).
- Switch authenticated API/Claude paths to strict integer-only behavior first.

### Validation Gate

1. Authenticated route tests pass with DB-first behavior.
2. Expected errors occur when DB unavailable and fallback is disabled.
3. No silent fallback in authenticated request path logs.
4. `pytest tests/api/test_portfolio_crud.py -q`
5. `pytest tests/api/test_portfolio_api_crud.py -q`
6. `pytest tests/utils/test_claude_functions.py -q`

### Rollback

1. Temporarily re-enable legacy fallback flag while investigating regressions.

## Phase 4: Make Side Effects Explicit

### Deliverables

1. CRUD methods no longer auto-trigger factor proxy generation by default.
2. Proxy generation moved to orchestration layer (API/service call sites).

### Tasks

1. Add explicit orchestration calls where needed in `app.py` and executor/service code.
2. Keep temporary compatibility option if required (`auto_ensure_proxies=True`) during transition.
3. Remove hidden side effects from repository/facade core CRUD operations.

### Validation Gate

1. Portfolio create/update endpoints still yield expected analysis-ready behavior.
2. Proxy coverage checks pass where expected.
3. DB failure fallback path for expected-returns update is regression-tested and does not fail due to legacy wrapper removal.
4. `pytest tests/utils/test_claude_functions.py -q`

### Rollback

1. Re-enable compatibility option to restore automatic behavior short-term.

## Phase 5: Final Cleanup

### Deliverables

1. Remove any remaining wrapper and compatibility-only code.
2. Update docs and architecture references.
3. Final simplified `PortfolioManager` (or replace with repository+assembler directly).

### Tasks

1. Remove dead code paths after migration window.
2. Clean imports and update tests.
3. Move final notes to `docs/planning/completed/`.

### Validation Gate

1. Full targeted backend suite passes.
2. No import references to removed wrapper/compatibility symbols.

### Rollback

1. Restore removed symbols only for missed critical references, then patch callers immediately.

## Testing Strategy

## Unit Tests

1. Repository:
- DB load/save/list/delete
- expected returns get/update
- explicit error propagation

2. Assembler:
- filtering derivatives/invalid tickers
- consolidation rules
- mixed-currency warning behavior
- cash mapping behavior

3. Legacy service:
- scenario YAML generation
- input format detection and conversion

## Integration Tests

1. API CRUD endpoints using authenticated user context.
2. Claude function executor paths:
- setup/portfolio scenario creation
- set expected returns
- portfolio switching
- expected-returns DB-failure fallback path remains functional

3. MCP smoke checks for unaffected paths:
- risk/performance/optimization tools still operate via live positions.

## Feature Flags and Defaults

Use explicit flags with planned defaults by phase.

1. `PORTFOLIO_MANAGER_DB_BEHAVIOR`
- Values: `legacy_fallback`, `fail_fast`
- Default:
  - Phases 0-2: `legacy_fallback`
  - Phase 3 onward (authenticated API/Claude): `fail_fast`
- Compatibility mapping with existing `STRICT_DATABASE_MODE`:
  - Resolution precedence: `PORTFOLIO_MANAGER_DB_BEHAVIOR` overrides `STRICT_DATABASE_MODE`.
  - If `PORTFOLIO_MANAGER_DB_BEHAVIOR` is unset:
    - `STRICT_DATABASE_MODE=true` => `fail_fast`
    - otherwise => `legacy_fallback`
  - Remove direct `STRICT_DATABASE_MODE` checks after Phase 3 gate is green.

2. `PORTFOLIO_MANAGER_AUTO_ENSURE_PROXIES`
- Values: `true`, `false`
- Default:
  - Phases 0-3: `true`
  - Phase 4 onward: `false` (callers orchestrate explicitly)

3. `PORTFOLIO_MANAGER_ALLOW_STRING_USER_ID`
- Values: `true`, `false`
- Default:
  - Phases 0-2: `true` (compatibility)
  - Phase 3: `false` for authenticated API/Claude paths; `true` only for temporary legacy/test flows
  - Phase 5: `false` globally

## Observability and Safety

1. Add structured logs for:
- fallback usage
- explicit proxy generation calls
- repository operation failures

2. Add counters/metrics:
- fallback invocation count
- fail-fast DB errors by endpoint
- proxy generation latency

3. Add temporary migration diagnostics:
- warning logs when removed symbol access is attempted (if temporary guard hooks are used)

## Risks and Mitigations

1. Risk: Hidden consumers rely on wrappers.
- Mitigation: caller inventory + `rg` reference checks + targeted tests before removal.

2. Risk: Removing fallback breaks local/dev workflows.
- Mitigation: explicit legacy fallback flag and clear error messages.

3. Risk: Side-effect extraction causes missing proxies.
- Mitigation: add explicit orchestration calls and test gates before removing compatibility toggle.

4. Risk: Behavior drift during extraction.
- Mitigation: Phase 0 baseline tests and no-signature-change rule in Phase 1.

## Rollout Approach

1. Use feature flags for behavior-changing phases (3 and 4), with defaults from the flag matrix above.
2. Merge phase-by-phase, not all at once.
3. Keep each phase independently deployable and reversible.

## Estimated Effort

1. Phase 0: 0.5-1 day
2. Phase 1: 1-2 days
3. Phase 2: 0.5-1 day
4. Phase 3: 1 day
5. Phase 4: 1 day
6. Phase 5: 0.5 day

Total: ~4.5 to 6.5 engineering days (excluding unexpected test debt).

## Definition of Done

1. `PortfolioManager` no longer contains mixed concerns at current scale.
2. DB-first authenticated flows are deterministic (no silent fallback).
3. Side effects are explicit and test-covered.
4. Legacy helpers are isolated from core DB portfolio lifecycle logic.
5. Documentation and tests reflect final architecture.

## Execution Checklist

- [ ] Phase 0 complete and baseline green
- [x] Phase 1 extraction merged with no behavior change
- [ ] Phase 2 legacy helper isolation merged (partial: service extracted, wrappers retained intentionally)
- [ ] Phase 3 fail-fast DB behavior enabled for authenticated flows
- [ ] Phase 4 explicit proxy orchestration merged (partial: app orchestration added, compatibility path retained)
- [ ] Phase 5 cleanup complete
- [ ] Final doc moved to `docs/planning/completed/` with postmortem notes
