# Business Actions Layer Plan

**Status:** Draft
**Date:** 2026-04-08
**Parent:** `docs/TODO.md` -> Architecture / Extraction

---

## 1. Problem

The repo currently mixes transport code, workflow orchestration, and integration logic across the same modules. The main seam problem is that some HTTP routes and service modules import MCP modules directly instead of calling a shared business layer.

Concrete examples of route → MCP seams (exact import edges):

- `routes/portfolios.py` → `mcp_tools.portfolio_management`
- `routes/income.py` → `mcp_tools.income`
- `routes/baskets_api.py` → `mcp_tools.basket_trading`, `mcp_tools.baskets`
- `routes/trading.py` → `mcp_tools.trading_analysis`
- `routes/tax_harvest.py` → `mcp_tools.tax_harvest`
- `routes/hedging.py` → `mcp_tools.trading_helpers`
- `routes/hedge_monitor_api.py` → `mcp_tools.hedge_monitor`
- `routes/onboarding.py` → `mcp_tools.import_portfolio`
- `routes/positions.py` → `mcp_tools.news_events`, `mcp_tools.factor_intelligence`, `mcp_tools.metric_insights`

Service → MCP seams:

- `services/agent_building_blocks.py` imports `mcp_tools.common` and `mcp_tools.risk`
- `services/agent_registry.py` registers many `mcp_tools/*` callables directly

Misplaced shared helpers in MCP layer:

- `mcp_tools/common.py` exports transport-neutral helpers (`handle_http_errors`, parsing helpers, alert-threshold loading) consumed by `routes/positions.py`, `routes/agent_api.py`, and `services/agent_building_blocks.py`
- `mcp_tools/positions.py` exports auth-warning helpers consumed by `mcp_tools/risk.py`
- `mcp_tools/risk.py` owns reusable portfolio-loading workflow code in `_load_portfolio_for_analysis()`, called by 7+ MCP tools (risk, whatif, optimization, backtest, compare, monte_carlo) and `services/agent_building_blocks.py`

This creates five problems:

1. **Wrong dependency direction**: app surfaces depend on other app surfaces.
2. **Workflow drift**: HTTP, MCP, and agent surfaces can diverge while doing "the same thing".
3. **Testing friction**: workflow logic is harder to test without transport wrappers.
4. **Change risk**: changing one surface can unintentionally break another.
5. **Trapped helpers**: transport-neutral code in `mcp_tools/` forces all consumers to take a dependency on the MCP layer.

---

## 2. Goal

Introduce a reusable `actions/` layer for user-scoped business workflows, so all transport surfaces call the same orchestration code.

Target outcome:

- `routes/` becomes HTTP transport only
- `mcp_tools/` becomes MCP transport only
- `routes/agent_api.py` and `services/agent_registry.py` call shared actions, not MCP internals
- `actions/` owns workflow orchestration
- `services/` stays focused on provider, cache, DB, and integration concerns
- `portfolio_risk_engine/` and `core/` remain the analytics engines

This is a boundary refactor, not a product rewrite.

---

## 3. Non-Goals

This plan does **not** do the following:

- split `app.py` first
- rewrite `portfolio_risk_engine/` or `core/`
- change public HTTP or MCP response shapes in the first pass
- collapse `services/` and `actions/` into one layer
- move every helper into `actions/` indiscriminately

If a helper is provider-specific, cache-specific, or a technical integration detail, it should remain in `services/`.

---

## 4. Target Architecture

Desired dependency graph:

```text
routes/                 -> actions/
mcp_tools/              -> actions/
agent/                  -> actions/

actions/                -> services/
actions/                -> core/
actions/                -> portfolio_risk_engine/

services/               -> providers / DB / cache / external APIs
core/                   -> portfolio_risk_engine/
```

Note: `agent/` is a transport-level package (same tier as `routes/` and `mcp_tools/`), not a service. It is created in Phase 6 by relocating `services/agent_registry.py`, `services/agent_building_blocks.py`, and optionally `routes/agent_api.py`. This avoids a `services/ -> actions/` cycle.

Forbidden end state (enforced as "no new imports" with shrinking allowlist):

- `routes/ -> mcp_tools/` (allowlisted: all current violations; see Section 8 for complete list)
- `services/ -> mcp_tools/` (allowlisted: agent modules until Phase 6 moves them)
- `services/ -> actions/` (no allowlist — hard rule from Phase 0)
- `actions/ -> fastapi` (no allowlist — hard rule)
- `actions/ -> mcp_tools/` (no allowlist — hard rule)
- `agent/ -> mcp_tools/` (allowlisted: unmigrated registry callables until future plans extract them)

### Proposed package layout

```text
actions/
├── __init__.py
├── context.py
├── errors.py
├── models.py
├── portfolio_management.py
├── income_projection.py
├── risk_analysis.py
└── orders.py
```

Shared portfolio-loading logic goes to `services/portfolio_context.py` (not `actions/`), since it is a reusable data-loading service, not a user-scoped business workflow. See Phase 4.

Transport-neutral helpers currently trapped in `mcp_tools/common.py` and `mcp_tools/positions.py` are relocated to `services/` or `utils/` in Phase 1.

### Action contract

Keep the action interface simple:

- `ActionContext`: resolved user and execution policy
- typed request object or explicit keyword params
- typed result object or stable dict payload
- domain errors raised from `actions/errors.py`
- actions never open DB sessions directly — session/transaction ownership stays in services or repository helpers, and actions orchestrate that boundary

The transport layers keep ownership of:

- FastAPI `HTTPException` mapping
- MCP `handle_mcp_errors`
- JSON-RPC / HTTP response envelopes
- auth header / cookie parsing

---

## 5. Scope of the First Iteration

Start with the infrastructure work that unblocks the target dependency graph, then extract workflows already shared across multiple surfaces:

1. **Helper relocation** (prerequisite)
   - move transport-neutral helpers out of `mcp_tools/common.py` and `mcp_tools/positions.py`
   - without this, the target graph is not reachable
2. **Portfolio management**
   - current seam: `routes/portfolios.py` -> `mcp_tools/portfolio_management.py`
3. **Income projection**
   - current seam: `routes/income.py` -> `mcp_tools/income.py`
4. **Shared portfolio loading / scope resolution**
   - current seam: `_load_portfolio_for_analysis()` in `mcp_tools/risk.py`
   - 7+ callers across MCP tools and services — requires compatibility shim strategy
   - target: `services/portfolio_context.py` (not `actions/`)
5. **Risk actions** (side-effecting, not read-only)
   - `ensure_factor_proxies(allow_gpt=True)` writes to DB and invokes LLM — not purely read-only
   - follow once shared portfolio context is proven
6. **Agent surface decoupling**
   - creates `agent/` package to resolve `services/ -> actions/` cycle
   - scoped to only the callables migrated in earlier phases

Do **not** start with write-side trading mutations. The risk path has DB/LLM side effects that need explicit handling, but it is still lower risk than trading mutations.

---

## 6. Phased Plan

### Phase 0: Scaffolding and Guardrails

Create the `actions/` package and define the minimum shared conventions:

- `actions/context.py`
  - `ActionContext`
  - helper for resolving `user_email` / `user_id`
- `actions/errors.py`
  - `ActionError`
  - `ActionAuthError`
  - `ActionValidationError`
  - `ActionNotFoundError`
  - `ActionInfrastructureError`
- `actions/models.py`
  - only for cross-action shared request/result types if needed

Add a transitional architecture test:

- forbid new `routes/ -> mcp_tools/` imports
- forbid new `services/ -> mcp_tools/` imports
- forbid `services/ -> actions/` imports
- forbid `actions/ -> fastapi` imports
- forbid `actions/ -> mcp_tools/` imports
- start with an explicit allowlist for all current violations (see Section 8 for complete Phase 0 allowlist)
- shrink the allowlist as each phase lands

This avoids a big-bang refactor while still preventing backsliding.

### Phase 1: Helper Relocation

Move transport-neutral helpers out of `mcp_tools/` so the target dependency graph is reachable.

Identify and relocate:

- **From `mcp_tools/common.py`**: `handle_http_errors`, parsing helpers, alert-threshold loading, and any other helpers consumed by `routes/` or `services/`. Target: `services/common_helpers.py` or `utils/`.
- **From `mcp_tools/positions.py`**: auth-warning helpers consumed by `mcp_tools/risk.py`. Target: `services/auth_helpers.py` or `utils/`.

Migration strategy:

- move the implementation to the new location
- leave re-exports in `mcp_tools/common.py` and `mcp_tools/positions.py` as temporary shims (with `# DEPRECATED: import from services/...` comment)
- update `routes/` and `services/` consumers to import from the new location
- `mcp_tools/` consumers can keep importing from the shim until they are migrated in later phases
- remove shims once all consumers are migrated

Result:

- `routes/` and `services/` no longer depend on `mcp_tools/` for helper code
- boundary test allowlist shrinks

### Phase 2: Portfolio Management Extraction

Create `actions/portfolio_management.py`.

Move workflow logic out of `mcp_tools/portfolio_management.py`, including:

- user resolution
- account ID normalization and validation
- portfolio payload building
- list/create/update/delete orchestration
- account activation and deactivation (currently exposed via `services/agent_registry.py`)

**Session/transaction ownership**: The current code mixes `DatabaseClient` calls with direct commits and `AccountRegistry` side effects throughout `mcp_tools/portfolio_management.py` (lines ~312-486). Before introducing `actions/portfolio_management.py`, extract the DB-touching code into a service/repository layer:

1. Create `services/portfolio_repository.py` (or extend existing DB helpers) to own:
   - session creation, commit, and rollback
   - portfolio CRUD operations that currently live inline in MCP tool functions
   - `AccountRegistry` side-effect calls
2. Then create `actions/portfolio_management.py` to orchestrate:
   - validation → service call → side-effect coordination
   - actions never open DB sessions directly
   - actions call service methods that own their own session lifecycle

This two-step extraction (repository first, then action) prevents the action layer from inheriting the current session-management mess.

Keep `mcp_tools/portfolio_management.py` as a thin MCP adapter.

Update:

- `routes/portfolios.py` -> call `actions/portfolio_management.py`
- `mcp_tools/portfolio_management.py` -> call `actions/portfolio_management.py`

Result:

- portfolio-management workflow is shared by HTTP and MCP
- route no longer depends on MCP code
- account activation/deactivation is action-backed for Phase 6

### Phase 3: Income Projection Extraction

Create `actions/income_projection.py`.

Move the reusable workflow logic out of `mcp_tools/income.py`, including:

- user resolution
- portfolio scope resolution
- position-loading orchestration
- income-specific position filtering
- dividend projection assembly

Keep MCP-specific formatting and error wrapping in `mcp_tools/income.py`.

Update:

- `routes/income.py` -> call `actions/income_projection.py`
- `mcp_tools/income.py` -> call `actions/income_projection.py`

### Phase 4: Shared Portfolio Context Extraction

Create `services/portfolio_context.py` (not `actions/` — this is a reusable data-loading service, not a user-scoped business workflow).

Note: `services/performance_helpers.py` already contains a transport-neutral shared loader. Evaluate whether to extend that module or create a new one. If they overlap significantly, consolidate.

Extract the portfolio-loading workflow currently embedded in `mcp_tools/risk.py`, centered on `_load_portfolio_for_analysis()`.

This module should own reusable **pure data-loading** logic for:

- resolve user and user ID
- resolve `PortfolioScope`
- load manual portfolio vs live positions
- apply filtered virtual portfolio scoping
- attach provider warnings / scope metadata
- merge user ticker overrides

**Factor proxy enrichment is NOT part of this module.** The current `_load_portfolio_for_analysis()` bundles `ensure_factor_proxies(allow_gpt=True)` (a DB/LLM side effect) inside the loader. During extraction, split into:

1. `services/portfolio_context.py` — pure context loader (no side effects)
2. `ensure_factor_proxies` stays as an explicit service-layer call that Phase 5 actions invoke directly and log

This prevents the side effect from being buried in a shared loader that all 7+ callers would silently trigger.

**Blast radius**: `_load_portfolio_for_analysis()` is called by 7+ MCP tools:

- `mcp_tools/risk.py` (risk score, risk analysis)
- `mcp_tools/whatif.py`
- `mcp_tools/optimization.py`
- `mcp_tools/backtest.py`
- `mcp_tools/compare.py`
- `mcp_tools/monte_carlo.py`
- `services/agent_building_blocks.py`

Migration strategy:

- move implementation to `services/portfolio_context.py`
- leave a compatibility shim in `mcp_tools/risk.py` that re-exports from the new location
- migrate callers one at a time (risk tools first, then scenario tools, then agent building blocks)
- remove shim once all callers are migrated

This service layer should be reused by:

- risk score and risk analysis (Phase 5)
- scenario tools (whatif, optimization, backtest, monte_carlo, compare)
- income projection where applicable
- agent building blocks (Phase 6)

### Phase 5: Risk Actions

Create `actions/risk_analysis.py`.

Move reusable orchestration out of `mcp_tools/risk.py` for:

- `get_risk_score`
- `get_risk_analysis`
- leverage-capacity setup where it shares the same portfolio context

**Side effects**: This is not purely read-only. `ensure_factor_proxies(allow_gpt=True)` in the risk path auto-generates missing proxy mappings, writing to DB and invoking the LLM. The action must:

- explicitly document which operations are side-effecting
- keep `ensure_factor_proxies` calls visible (not buried in a helper)
- treat proxy generation as a service-layer concern, not an action-layer concern
- log or flag when LLM-based proxy generation occurs

Keep the following in the MCP adapter:

- agent-format payload shaping
- file-output side effects
- `handle_mcp_errors`

### Phase 6: Agent Surface Decoupling

**Definition**: `agent/` is a **shared adapter package**, not a transport surface. It adapts business actions and (temporarily) MCP tools into the callable interface that the agent runtime expects. It sits at the same dependency tier as `routes/` and `mcp_tools/` — it may import `actions/` and `services/`, but nothing may import `agent/` except the HTTP route that mounts it.

Create the `agent/` package by relocating agent-facing modules out of `services/`:

- `services/agent_registry.py` -> `agent/registry.py`
- `services/agent_building_blocks.py` -> `agent/building_blocks.py`
- `routes/agent_api.py` remains under `routes/` and imports from `agent/` (this is the standard `routes/ -> non-MCP` pattern, not a forbidden edge)

This resolves the circular dependency: `agent/` -> `actions/` -> `services/` is acyclic, whereas the previous `services/` -> `actions/` -> `services/` was not.

Refactor so agent-facing modules stop treating MCP tools as the canonical business interface:

- registry entries point to action-backed callables or thin action adapters
- building blocks import actions or services, never MCP internals

**Transitional MCP imports in `agent/`**: The target graph forbids `agent/ -> mcp_tools/`, but the registry currently imports ~75 MCP callables directly. This plan only extracts a subset to actions. During transition:

- migrated callables → import from `actions/` (clean)
- unmigrated callables → keep `agent/ -> mcp_tools/` imports on a **temporary allowlist** in the boundary test, with an explicit comment per entry
- the allowlist shrinks as future plans extract more workflows to `actions/`
- the `agent/ -> mcp_tools/` forbidden rule is enforced as "no new imports" (same pattern as `routes/ -> mcp_tools/`)

**Scope**: Only migrate callables that have action-layer equivalents from Phases 2-5:

- `account_activate` / `account_deactivate` → action-backed (from Phase 2)
- `get_risk_score` / `get_risk_analysis` → action-backed (from Phase 5)
- `get_income_projection` → action-backed (from Phase 3)
- remaining registry entries (e.g., `get_leverage_capacity`, trading, baskets, hedging) → stay as MCP imports on the temporary allowlist

---

## 7. Testing Strategy

Each phase should add or preserve three test layers.

### 1. Action unit tests

Test the action directly with mocked services / DB helpers where practical.

Goal:

- verify workflow behavior without HTTP or MCP wrappers

### 2. Surface contract tests

For each migrated workflow:

- route response shape remains unchanged
- MCP response shape remains unchanged

The transport adapter should change; the surface contract should not.

### 3. Architecture boundary tests

Add a dedicated test module that checks imports.

Rules:

- no new `routes/ -> mcp_tools/`
- no new `services/ -> mcp_tools/`
- no `services/ -> actions/`
- no `actions/ -> fastapi`
- no `actions/ -> mcp_tools/`
- no `agent/ -> mcp_tools/`

Use an explicit temporary allowlist during migration so the test can land early. The complete Phase 0 allowlist is enumerated in Section 8.

---

## 8. Acceptance Criteria

This plan is successful when:

1. `routes/portfolios.py` no longer imports `mcp_tools/portfolio_management.py`
2. `routes/income.py` no longer imports `mcp_tools/income.py`
3. shared portfolio-loading logic lives in `services/portfolio_context.py`, not `mcp_tools/risk.py`
4. transport-neutral helpers no longer live in `mcp_tools/common.py` or `mcp_tools/positions.py`
5. `agent/` package owns registry and building-blocks code, not `services/`
6. no `services/ -> actions/` or `services/ -> mcp_tools/` imports exist
7. action-level tests exist for the extracted workflows
8. boundary tests enforce the new dependency rules
9. HTTP and MCP surfaces still return the same public shapes as before

### Phase 0 initial allowlist (all current violations)

The boundary test starts by allowlisting every existing violation. This is the complete list:

**`routes/ -> mcp_tools/` (in-scope — resolved by this plan):**

- `routes/portfolios.py` → `mcp_tools.portfolio_management` (resolved in Phase 2)
- `routes/income.py` → `mcp_tools.income` (resolved in Phase 3)
- `routes/positions.py` → `mcp_tools.common` (resolved in Phase 1)
- `routes/agent_api.py` → `mcp_tools.common` (resolved in Phase 1)

**`routes/ -> mcp_tools/` (out-of-scope — remain after this plan):**

- `routes/baskets_api.py` → `mcp_tools.basket_trading`, `mcp_tools.baskets`
- `routes/trading.py` → `mcp_tools.trading_analysis`
- `routes/tax_harvest.py` → `mcp_tools.tax_harvest`
- `routes/hedging.py` → `mcp_tools.trading_helpers`
- `routes/hedge_monitor_api.py` → `mcp_tools.hedge_monitor`
- `routes/onboarding.py` → `mcp_tools.import_portfolio`
- `routes/positions.py` → `mcp_tools.news_events`, `mcp_tools.factor_intelligence`, `mcp_tools.metric_insights`

**`services/ -> mcp_tools/` (resolved in Phase 1 + Phase 6):**

- `services/agent_registry.py` → `mcp_tools.*` (bulk — all registry imports; resolved in Phase 6)
- `services/agent_building_blocks.py` → `mcp_tools.common`, `mcp_tools.risk` (resolved in Phases 1 + 6)

### Residual post-plan allowlist

After all 7 phases land, only the out-of-scope `routes/ -> mcp_tools/` edges remain (7 route files, ~10 import edges). These are tracked for future extraction iterations.

---

## 9. Sequencing Notes

Recommended order:

1. Phase 0 scaffolding + boundary tests
2. Phase 1 helper relocation (unblocks target graph)
3. Phase 2 portfolio management extraction
4. Phase 3 income projection extraction
5. Phase 4 shared portfolio context (services layer)
6. Phase 5 risk actions
7. Phase 6 agent surface decoupling

Phase 1 must land before Phase 2, because routes and services currently consume helpers from `mcp_tools/common.py` — extracting actions before relocating helpers would create new forbidden imports.

Phase 4 should land before Phase 5, because risk actions depend on the shared portfolio-loading workflow.

Phase 6 must be last because it moves files between packages (`services/` → `agent/`) and depends on actions being stable.

Do **not** split `app.py` before Phases 2-4. Reducing seam complexity first will make later file decomposition cleaner and lower risk.

---

## 10. Risks and Mitigations

### Risk: Big-bang refactor causes surface regressions

Mitigation:

- migrate one workflow at a time
- keep thin MCP and HTTP adapters
- preserve response contracts with tests

### Risk: `actions/` becomes a second `services/` dump

Mitigation:

- only put end-to-end business workflows in `actions/`
- keep provider/cache/DB helpers in `services/`

### Risk: premature abstraction slows delivery

Mitigation:

- start only with workflows already shared across surfaces
- do not extract single-surface helpers yet

### Risk: hidden transport assumptions leak into actions

Mitigation:

- no FastAPI imports in `actions/`
- no MCP decorators in `actions/`
- keep error mapping at the adapter layer

### Risk: `services/ -> actions/` cycle from agent modules

Mitigation:

- Phase 6 relocates agent modules to `agent/` package before rewiring to actions
- boundary test forbids `services/ -> actions/` from Phase 0

### Risk: side-effecting code in "read-only" risk path

Mitigation:

- acknowledge `ensure_factor_proxies(allow_gpt=True)` as a side effect
- keep proxy generation as a service-layer call, visible and logged
- do not bury LLM/DB writes inside action helpers

### Risk: `_load_portfolio_for_analysis()` blast radius during migration

Mitigation:

- compatibility shim in `mcp_tools/risk.py` during transition
- migrate callers one at a time, not all at once
- each caller migration is a separate PR with its own surface contract tests

---

## 11. First Implementation Slice

The first PR should cover Phase 0 + Phase 1 only:

1. add `actions/__init__.py`, `actions/context.py`, and `actions/errors.py`
2. identify transport-neutral helpers in `mcp_tools/common.py` (parsing helpers, alert-threshold loading, `handle_http_errors`)
3. relocate those helpers to `services/common_helpers.py` or `utils/`
4. identify auth-warning helpers in `mcp_tools/positions.py` and relocate to `services/`
5. update all consumers (`routes/`, `services/`, `mcp_tools/`) to import from new locations
6. leave re-exports in `mcp_tools/common.py` as a temporary shim (with deprecation comment)
7. add boundary test with temporary allowlist for all known seams

This unblocks the target dependency graph. The second PR (Phase 2) then proves the actions pattern with portfolio management extraction.
