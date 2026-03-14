# Portfolio Manager Complexity Audit

Date: 2026-02-17
Status: Completed

## Scope

Audit `inputs/portfolio_manager.py` complexity for CLI/MCP relevance and recommend what to keep vs simplify.

## Executive Decision

1. Keep `PortfolioManager` as a DB-backed portfolio repository/assembler for authenticated API and Claude chat paths.
2. Do not use `PortfolioManager` as the primary runtime path for MCP analysis tools (current MCP already uses live `PositionService` flow).
3. Reduce `PortfolioManager` scope by extracting legacy file-mode/scenario helpers and removing implicit fallback behavior from DB-first paths.

## Evidence Snapshot

- `PortfolioManager` size is 1222 lines (`inputs/portfolio_manager.py`).
- It currently combines identity resolution, storage, transformation, proxy orchestration, expected-returns CRUD, and legacy YAML scenario generation in one class (`inputs/portfolio_manager.py:48`, `inputs/portfolio_manager.py:311`, `inputs/portfolio_manager.py:471`, `inputs/portfolio_manager.py:713`, `inputs/portfolio_manager.py:936`).
- API routes instantiate DB mode repeatedly and require DB for multi-user operation (`app.py:252`, `app.py:1194`, `app.py:3186`).
- MCP risk/perf/optimization paths build `PortfolioData` from live positions, not from `PortfolioManager` (`mcp_tools/risk.py:100`).
- CLI analysis path uses `load_portfolio_config` directly, not `PortfolioManager` (`run_risk.py:325`, `run_portfolio_risk.py:202`).

## Findings

1. Responsibility overload in one class.
- Constructor handles multi-type user identity and DB setup (`inputs/portfolio_manager.py:48`).
- Load path also performs filtering, consolidation, cash mapping, factor proxy generation, and metadata assembly (`inputs/portfolio_manager.py:329`, `inputs/portfolio_manager.py:333`, `inputs/portfolio_manager.py:336`, `inputs/portfolio_manager.py:351`).

2. Implicit DB-to-file fallback in DB mode is risky for authenticated flows.
- DB load/save and expected-returns update can silently fall back to file mode (`inputs/portfolio_manager.py:395`, `inputs/portfolio_manager.py:465`, `inputs/portfolio_manager.py:969`).
- For API multi-user behavior, this can obscure root causes and weaken deterministic data provenance.

3. Hidden side effects in CRUD paths.
- Portfolio create/update performs factor proxy generation as an implicit side effect (`inputs/portfolio_manager.py:213`, `inputs/portfolio_manager.py:272`).
- This couples storage operations with external proxy generation and can surprise callers.

4. Legacy file/scenario helpers are mixed with production DB behavior.
- Scenario YAML creation and format-conversion helpers live in the same class (`inputs/portfolio_manager.py:713`, `inputs/portfolio_manager.py:793`).
- Backward-compat global singleton and wrappers further blur runtime contract (`inputs/portfolio_manager.py:1204`).

5. Position consolidation logic is acknowledged as transitional.
- Existing TODO already states this should move to `PositionService` when ready (`inputs/portfolio_manager.py:475`).

## Keep vs Simplify

## Keep

- DB-backed portfolio load/save/list/delete APIs used by authenticated app and Claude function executor.
- Current mapping/consolidation behavior as temporary source of truth until Position module handoff is complete.
- DB expected-returns CRUD path used by optimization/returns workflows.

## Simplify

- Remove user-identity translation (`str` OAuth ID -> DB ID) from `PortfolioManager`; require resolved integer `user_id` at call sites.
- Remove implicit fallback in DB mode for API/MCP paths (fail fast by default; fallback only in explicitly legacy mode).
- Move legacy file/scenario helpers (`create_portfolio_yaml`, `create_what_if_yaml`, file expected-returns helpers) to a separate legacy helper module.
- Make factor proxy generation explicit at orchestration layer (caller-owned), not implicit in CRUD methods.
- Split class into focused components:
  - `PortfolioRepository` (DB/file CRUD),
  - `PortfolioAssembler` (filter/consolidate/map/build `PortfolioData`),
  - `LegacyScenarioFileService` (YAML scenario generation helpers).

## Suggested Refactor Sequence

1. Phase 1 (safe, no external behavior change):
- Add explicit mode flags and telemetry for fallback usage.
- Introduce thin interfaces (`PortfolioRepository`, `PortfolioAssembler`) and delegate internally.

2. Phase 2 (behavior tightening):
- Default DB mode to fail-fast (no file fallback) for authenticated API/MCP contexts.
- Require integer `user_id` in constructor; resolve email/OAuth IDs before instantiation.

3. Phase 3 (surface cleanup):
- Move legacy scenario/file helpers out of `PortfolioManager`.
- Keep compatibility shims with deprecation notes until callers migrate.

## Outcome for TODO

Complexity is justified for web multi-user workflows but excessive for CLI/MCP scope.  
Recommendation is to keep DB-backed portfolio lifecycle capabilities and progressively extract legacy/file concerns plus implicit side effects from `PortfolioManager`.
