# Risk Client Type Polish — Phase 1 Plan

**Parent plan**: `AGENT_SURFACE_AUDIT.md` (Phase 1 scope)
**Status**: **SHIPPED 2026-04-17** — all 6 phases landed + live-smoke follow-up patch
**Date**: 2026-04-17

## Ship log

Plan approved after Codex R5 PASS (5 review rounds). Implemented by a fresh Codex session with per-phase commits:

| Phase | Commit | Summary |
|---|---|---|
| P1.1 | `fd3d41fa` | Generator script + signature typing (80 wrappers, zero `**kw: Any`) |
| P1.2 | `2511a519` | `risk_client/types.py` scaffold + pyproject `requires-python >= 3.11` |
| P1.3 | `1187407a` | 15 Tier A curated TypedDicts + generator cast-elision for `ToolResult` |
| P1.4 | `62b0ea3f` | Overloads for `run_whatif` (4 variants), `run_backtest` (3), `get_income_projection` (4); `suggest_tax_loss_harvest` rejected after inspection |
| P1.5 | `963c67fa` | Drift test, 26 contract tests using real registered callables under existing mocks; caught `from __future__ import annotations` bug that was silently breaking `__required_keys__` |
| P1.6 | `8b507cdc` | Version bump 0.1.0 → 0.2.0, README with migration guide, CHANGELOG entry |
| Post | `b8d592a5` | Post-smoke follow-up: `RiskAnalysisResult` gained `factor_variance_pct` + `idiosyncratic_variance_pct`; F36 filed (run_whatif agent format 500 via numpy bool leak) |

**Live smoke test** (post-deploy, against `localhost:5001`): all happy paths work — typed returns, overload dispatch, error raises `AgentAPIError`, escape hatch `call()` preserved. Real composition flow exercised: `get_positions` → extract tickers → `get_correlation_matrix` on live portfolio. F36 is the only blocker surfaced.

See `CHANGELOG.md` 0.2.0 entry for user-facing summary.

---

---

## 1. Goal

Replace the `risk_client.RiskClient` signature pattern `(**kw: Any) -> dict[str, Any]` with typed method signatures + curated return types for the **80 currently-wrapped registered functions**.

The agent running in the AI-excel-addin sandbox (`from risk_client import RiskClient`) gets signature-level guidance + labeled return fields without a single architectural change. Backend and HTTP contract untouched.

Out of scope for Phase 1: the 16 registered functions (mostly research/editorial) currently NOT wrapped by RiskClient — deferred to a follow-up (§5).

---

## 2. Current state (verified)

- `risk_client/__init__.py` — 390 lines, **80 wrapper methods** (Codex R1 correction). Every method is `(self, **kw: Any) -> dict[str, Any]`. Each wrapper returns the HTTP envelope `{function, ok, result, error_type}` via `self.call(...)` — NOT the inner result.
- `agent/registry.py` — 96 registered functions (building_block=10, tool=86). Each registered function has a real Python signature with types + docstring.
- **Parity gap**: 16 registered functions are NOT wrapped by RiskClient (concentrated in research/editorial tool tier). Deferred to follow-up; see §5.
- `routes/agent_api.py:159` — `_build_schema(entry)` already introspects registered functions via `inspect.signature` + `get_type_hints` and emits JSON schemas. Served at `GET /api/agent/registry`. **The server already knows the param types — we just need to thread them to the client.**
- `routes/agent_api.py:123` — `_sanitize_params()` strips `user_email` (injected server-side from auth) and `BLOCKED_PARAMS` before dispatch.
- `BLOCKED_PARAMS` today: `{"backfill_path": None, "output": "inline", "debug_inference": False}`. `output="inline"` is force-set → `file_path` response branches are **unreachable from the sandbox**.
- `user_id` is NOT server-injected (only `user_email` is, per `routes/agent_api.py:89`). But `user_id` exposes internal identity on some tools (e.g., `mcp_tools/news_events.py`) and shouldn't be client-supplied from the sandbox. Handled as a client-side denylist (D8) — sandbox policy, not server behavior.
- `tests/test_risk_client.py` — 429 lines, uses `DummySession` pattern for mocking HTTP.
- `tests/test_tool_surface_sync.py` — 140 lines, already enforces cross-surface parity (MCP ↔ REST ↔ agent registry).
- `risk_client/pyproject.toml` — `name="risk-client", version=0.1.0, dependencies=["requests"]`. No `requires-python` set.

**Sync mechanism to AI-excel-addin**: `RISK_CLIENT_PATH` env var on sandbox PYTHONPATH (verified earlier — preamble injects `from risk_client import RiskClient as _RiskClient`). Path-mount picks up source changes on next interpreter start; no package rebuild needed (Codex R1 confirmed).

---

## 3. Target state

### Return contract — BREAKING CHANGE

Current generated wrapper pattern returns the HTTP envelope:
```python
def get_positions(self, **kw: Any) -> dict[str, Any]:
    return self.call("get_positions", **kw)   # returns {function, ok, result, error_type}
```

**New pattern: generated wrappers call `call_or_raise()` and return the *inner result*.** Errors raise `AgentAPIError`:
```python
def get_positions(self, ...) -> PositionsResult:
    return cast(PositionsResult, self.call_or_raise("get_positions", ...))
```

**This is a breaking change** for any consumer who accessed `envelope["result"]["positions"]` directly. Justified because:
- 0.x semver allows breaking changes
- The new shape matches the spec principle that return types should be directly useful (no envelope unwrapping boilerplate)
- AI-excel-addin is the only known consumer and will be updated in lockstep
- `client.call()` and `client.call_or_raise()` remain public as escape hatches

### Method signature pattern (generated from `inspect.signature` of registered function)

```python
def run_monte_carlo(
    self,
    portfolio_name: str = "CURRENT_PORTFOLIO",
    num_simulations: int = 1000,
    horizon_days: int = 252,
    distribution: Literal["normal", "t", "bootstrap"] = "normal",
    drift_model: Literal["historical", "industry_etf", "risk_free", "zero"] = "industry_etf",
    drift_overrides: dict[str, float] | None = None,
    scenario_shocks: dict[str, Any] | None = None,
    df: int = 5,
    vol_scale: float = 1.0,
    resolved_weights: dict[str, float] | None = None,
    portfolio_value: float | None = None,
) -> MonteCarloResult:
    """Run the monthly Monte Carlo engine against a named portfolio."""
    return cast(MonteCarloResult, self.call_or_raise(
        "run_monte_carlo",
        portfolio_name=portfolio_name,
        # ... all params forwarded
    ))
```

Denied params (stripped from every generated signature — see D8): `user_email`, `user_id`, `backfill_path`, `output`, `debug_inference`.

### Return type pattern

```python
# risk_client/types.py

from typing import Literal, NotRequired, TypedDict

class AgentEnvelope(TypedDict):
    """Shared envelope for tools returning format="agent". file_path omitted — unreachable because BLOCKED_PARAMS forces output="inline"."""
    status: str
    format: Literal["agent"]
    snapshot: dict
    flags: list[dict]

class MonteCarloSnapshot(TypedDict):
    paths: dict  # p5/p50/p95 series
    terminal_values: dict
    var_95: float
    cvar_95: float
    # ... actual fields from building_blocks.run_monte_carlo

class MonteCarloResult(TypedDict):
    status: str
    portfolio_name: str
    horizon_days: int
    time_horizon_months: int
    simulation: MonteCarloSnapshot
    note: NotRequired[str]
```

**TypedDict, not dataclass** — HTTP returns JSON, JSON deserializes to `dict`. TypedDict matches the wire format exactly; zero runtime overhead; mypy still enforces field access. Dataclasses would need a conversion layer. (Phase 2's `portfolio_math` package will use dataclasses because those are pure-compute returns.)

---

## 4. Design decisions

### D1: Code generation, not hand-authoring (for signatures)

A generator script (`scripts/generate_risk_client.py`) introspects `agent/registry.py` via `inspect.signature` + `get_type_hints` and emits the typed `RiskClient` class. Re-run when the registry changes. Drift test in CI.

**Why**: 96 methods × 3-12 params each = too much manual work to keep in sync. The server already has the introspection logic — reuse it.

### D2: Curated return TypedDicts + shared envelopes (not 96 per-tool)

Hand-authoring 80+ exact TypedDicts is overbuilt for Phase 1 (Codex R1). Tiered approach:

- **Tier A — Curated (~15 tight types)**: the highest-traffic tools get full per-tool `TypedDict` returns with complete top-level keys. Target list: `get_positions`, `get_risk_analysis`, `get_risk_score`, `get_performance`, `run_monte_carlo`, `run_optimization`, `run_whatif`, `run_backtest`, `get_income_projection`, `compute_metrics`, `get_correlation_matrix`, `get_returns_series`, `get_price_series`, `get_factor_analysis`, `suggest_tax_loss_harvest`. (Codex R2 swap: replaced `analyze_stock` with `get_income_projection`.) Future expansion candidates: `analyze_stock`, `get_quote`.
- **Tier B — Shared envelope types**: tools following `{status, format, snapshot, flags, file_path}` get a common `AgentEnvelope` TypedDict (file_path omitted — unreachable per BLOCKED_PARAMS). Return as `AgentEnvelope` without per-tool snapshot specialization.
- **Tier C — Broad aliases**: the long tail returns `ToolResult = dict[str, Any]` (a named alias — still typed better than raw `dict`, documents intent, ready for future tightening).

Returns live in `risk_client/types.py`. Generator consumes a `FUNCTION_NAME → TypedDict` mapping; unmapped functions get `ToolResult`.

**Why**: 80% of agent interactions are with ~15 tools. Typing those tightly and the long tail coarsely captures most of the win at 20% of the effort.

### D3: Overloads narrowly scoped — Tier A only

Several target tools have MORE than one shape-gating param — not just `format`. `get_positions` changes shape on `by_account` and `include_risk`; `get_risk_analysis` on `include`; `get_factor_analysis` on `include_matrices`; etc. (Codex R1).

Decision: **`@overload` only where `format` is a clean sole discriminant with enumerable values, AND the tool is in Tier A** (Codex R4 scope-constraint). Limiting to Tier A ensures overload specializations share the same contract-test coverage as Tier A base types — no hidden scope.

Provisional candidates (from Tier A, validated during P1.3 by reading each tool's return branching):
- `run_whatif` — format sole discriminant
- `run_backtest` — format sole discriminant
- `suggest_tax_loss_harvest` — format sole discriminant (tentative)
- `get_income_projection` — format sole discriminant (tentative)

NOT overload candidates:
- `run_monte_carlo` — no `format` param at all
- `analyze_stock`, `analyze_option_strategy` — have clean format gating BUT are not in Tier A (Codex R4: keep scope aligned). If overloads on these become important, either promote them to Tier A first or add a dedicated mini-tier.
- `get_positions`, `get_risk_analysis`, `get_performance`, `get_factor_analysis`, `compare_scenarios`, `run_optimization` — shape gated by multiple params; broad union return

Final overload list determined at P1.3/P1.4 after per-tool branching inspection. The generator supports overload blocks but the default is a single return type.

### D4: `risk_client/types.py` organization

Single file, sections by category (positions, risk, scenarios, research, trading, transactions). ~500-800 LOC estimated. Splitting into a subpackage is premature — revisit if it exceeds 1500 LOC.

### D5: DEFER parity expansion (80 → 96)

RiskClient wraps 80 of 96 registered functions. The 16 missing are concentrated in research/editorial tool tier. Originally planned inclusion; **deferred to follow-up after Codex R1 feedback**.

Rationale: the agent-ergonomics payoff comes from typing the methods that already exist. Adding 16 new methods simultaneously enlarges review surface, bundles new-API-surface decisions with typing work, and stretches the timeline. Keep Phase 1 tight: type what's there.

Follow-up plan (post-Phase-1): add the 16 missing wrappers. At that point they benefit from the generator machinery already in place. Tentatively tracked as `RISK_CLIENT_PARITY_FOLLOWUP.md` (not yet drafted).

### D6: `call()` / `call_or_raise()` remain public escape hatches

Per §3, generated wrappers return the **inner result via `call_or_raise()`** — not the envelope. `AgentAPIError` is raised on `{ok: False}` responses.

`client.call()` (envelope-returning) and `client.call_or_raise()` (inner-result, raises on error) both remain public, unchanged. They're the escape hatch for:
- Calling functions not in the current client surface (e.g., the 16 registered-but-unwrapped functions deferred by D5)
- Consumers that need the envelope's `error_type` or `ok` field directly
- Dynamic function invocation where the function name isn't known at write time

### D7: Drift test enforces generator == committed file

`tests/test_risk_client_generator_sync.py`: runs generator, diffs against committed `risk_client/__init__.py`, fails if drift. Protects against hand-edits diverging from registry.

### D8: Complete param denylist (new, from Codex R1/R2)

Generator strips these params from every generated method signature — they are never legal to supply from the sandbox:

| Param | Policy | Enforcement | Source |
|---|---|---|---|
| `user_email` | Server-injected from auth | Server strips + injects | `routes/agent_api.py:89,126` |
| `user_id` | Client denylist (sandbox policy) | **Client-side only** — not stripped server-side. Rationale: exposes internal identity; not appropriate for sandbox to supply | `mcp_tools/news_events.py` |
| `backfill_path` | `BLOCKED_PARAMS[backfill_path] = None` | Server strips | `agent/registry.py:36` |
| `output` | `BLOCKED_PARAMS[output] = "inline"` | Server force-sets | `agent/registry.py:37` |
| `debug_inference` | `BLOCKED_PARAMS[debug_inference] = False` | Server force-sets | `agent/registry.py:38` |

**Formula** (hardcoded in generator):
```python
INTERNAL_ONLY_PARAMS = {"user_email", "user_id"}
DENYLIST = INTERNAL_ONLY_PARAMS | set(BLOCKED_PARAMS.keys())
# imports BLOCKED_PARAMS from agent.registry
```

Generator must:
1. Detect these params via `inspect.signature` and omit them from the emitted method signature
2. Not forward them in the `call_or_raise()` payload (server would reject unknown params anyway, but cleaner to not send)

Return-type implication: since `output` is always `"inline"`, the `file_path` branch is unreachable. **TypedDict returns for tools that conditionally return `file_path` must omit the `file_path` field.** `AgentEnvelope` does not include `file_path`.

Drift detection: denylist imports `BLOCKED_PARAMS` from registry. If server adds a new blocked param, the key appears automatically; generator output changes → drift test catches it. New `INTERNAL_ONLY_PARAMS` additions (like `user_id` was) are hand-added with a comment explaining rationale — those require explicit code review.

Future parity work (D5 follow-up): `ingest_document(source_path)` takes a server-side filesystem path. Separate security review needed before wrapping — `source_path` may warrant denylist too.

### D9: Python version declaration (new)

`risk_client/pyproject.toml` adds `requires-python = ">=3.11"`. Justification: the plan uses `NotRequired` (PEP 655, Python 3.11+), `Literal`, `type | None` syntax. 3.11 is widely available; AI-excel-addin sandbox confirmed to run 3.12. Alternative: `typing_extensions` — adds dep, not worth it.

---

## 5. Scope

### In scope
- Generator script (`scripts/generate_risk_client.py`) that introspects `agent/registry.py`
- Typed `risk_client/__init__.py` (regenerated) — **80 existing wrappers only**
- Return-contract breaking change: generated methods return inner result via `call_or_raise()` (§3)
- `risk_client/types.py` — **~15 curated TypedDicts (Tier A) + `AgentEnvelope` (Tier B) + `ToolResult` alias (Tier C)** per D2
- Overloads only where `format` is clean sole discriminant (D3) — estimated 2-3 tools
- Complete param denylist (D8): `user_email`, `user_id`, `BLOCKED_PARAMS` keys stripped from signatures
- `requires-python >= 3.11` in pyproject (D9)
- Tests: drift test (signatures), golden-key contract tests on Tier A return shapes, existing test suite green, mypy --strict clean on `risk_client/`
- Version bump `0.1.0 → 0.2.0` (breaking per §3), README update
- Re-sync note for AI-excel-addin (path-mount auto-picks-up; no rebuild)

### Out of scope (Phase 2+ or follow-ups)
- **Parity expansion — the 16 missing wrappers** (D5, deferred to follow-up)
- `portfolio_math/` package — separate plan (Phase 2)
- Changes to `agent/registry.py`, `mcp_tools/`, or `actions/`
- Deprecating `building_blocks` tier (Phase 3)
- Runtime validation of return shapes (TypedDict is static-only)
- Pydantic models (heavier than we need)
- Async client variant
- New MCP tools
- Per-tool snapshot specialization for Tier B envelope tools

---

## 6. Implementation phases (within this plan)

Codex R1 noted the original P1.1 baseline-reproduction step was wasted effort (existing wrappers already diverge from registry sigs). Revised phasing drops it.

### P1.1 — Generator + signature typing (1 day)
- `scripts/generate_risk_client.py`: reads `agent/registry.py`, introspects each registered function via `inspect.signature` + `get_type_hints`, emits typed method signatures
- Applies denylist per D8 (`user_email`, `user_id`, `BLOCKED_PARAMS`)
- Return type defaults to `ToolResult` (Tier C) at this stage; Tier A overrides in P1.3
- Generator emits methods using `call_or_raise()` (per return contract §3)
- Regenerate `risk_client/__init__.py` — all 80 existing wrappers + typed params + `ToolResult` return
- Existing `tests/test_risk_client.py` updated to reflect inner-result contract

### P1.2 — `AgentEnvelope` + `types.py` scaffold (0.5 day)
- `risk_client/types.py` — `AgentEnvelope` TypedDict (Tier B), `ToolResult = dict[str, Any]` alias (Tier C), section headers for Tier A additions in P1.3
- `pyproject.toml` → `requires-python = ">=3.11"` (D9)
- Generator picks up `ToolResult` + `AgentEnvelope` exports

### P1.3 — Tier A curated TypedDicts (1-1.5 days)
~15 highest-traffic tools get full per-tool return types (list in D2). For each:
1. Read the registered function implementation
2. Catalog actual return keys (check `get_agent_snapshot`, `to_api_response`, `get_summary` outputs)
3. Author `TypedDict` in `risk_client/types.py`
4. Add to `FUNCTION_NAME → TypedDict` mapping in generator
5. Regenerate + verify the 15 methods now have tight return types

### P1.4 — Overloads for clean-discriminant Tier A tools (0.25 day)
Add `@overload` blocks for Tier A tools where `format` is the sole shape-gating param. Provisional candidates per D3: `run_whatif`, `run_backtest`, possibly `suggest_tax_loss_harvest` and `get_income_projection`. Constraint (Codex R4): overload targets MUST be in Tier A — avoids hidden scope of specialized types + per-variant tests outside the curated 15. Final list determined here by reading each tool's return branching. Verify via mypy narrowing test. Implementation pitfall (Codex R3): add one contract/type test per declared overload variant — a single default-call test is insufficient.

### P1.5 — Tests + lint (1 day — revised up from 0.75 after Codex R3)
- `mypy --strict risk_client/` green
- `pytest tests/test_risk_client.py` green (updated for inner-result contract)
- `pytest tests/test_risk_client_generator_sync.py` green (drift test: regen = committed)
- NEW `tests/test_risk_client_contract.py` — per §9 revised design: for each of 15 Tier A methods, import the registered callable via `get_registry()[name].callable`, invoke it under existing `tests/core/*` / `tests/services/*` mock infra (reuse — do not build new mocks per tool), collect real output keys, assert `set(TypedDict.__required_keys__) ⊆ set(real_output_keys)`. Catches server-side return-shape drift. Implementation pitfall (Codex R3): assert against `__required_keys__` only — optional fields (e.g., `auth_warnings`) will otherwise make tests noisy. Per-overload-variant coverage (P1.4) also lands here.
- Smoke test (DummySession-based): call all 80 methods with minimal args; assert no TypeError

### P1.6 — Version bump + docs (0.25 day)
- `pyproject.toml` → `version = "0.2.0"` (breaking)
- `risk_client/README.md` (new): usage example showing typed returns + **breaking-change note on call_or_raise return contract**
- `CHANGELOG.md` entry
- Note for AI-excel-addin: path-mount picks up automatically; update any code that accessed `envelope["result"]["..."]` to use the new direct-return shape

**Total estimate**: 4 days. (Down from 7-8 after Codex R1 scope trim; P1.5 bumped 0.75→1 day after R3 contract-test re-scoping.)

### Implementation pitfalls (consolidated from Codex R1/R2/R3 for the implementation session)

1. **Tier A optional fields**: Several Tier A tools append `auth_warnings` (and other conditional top-level keys) on success paths. These must be modeled as `NotRequired` TypedDict fields — otherwise `required_keys ⊆ real_keys` assertions fail sporadically, and the "tight" types lie about the real surface. Audit each Tier A tool for conditional keys before authoring its TypedDict.
2. **Contract test budget**: If built from scratch, the 15 contract tests run over budget. Piggyback on existing `mcp_tools/*` and `services/*` test fixtures/helpers — reuse their mock portfolio state, FMP fixture data, and brokerage stubs rather than rebuilding per-tool.
3. **Overload variants need coverage**: P1.4 adds overloads for 2-3 tools. Each declared variant needs its own contract/type-narrowing test — the default call path doesn't exercise the narrowed branch.
4. **`__required_keys__` only**: Contract assertions must compare against `TypedDict.__required_keys__`, not all declared keys, to avoid false failures on conditional optional fields.

---

## 7. Files touched

| File | Change |
|---|---|
| `risk_client/__init__.py` | Rewritten (generated) — typed signatures, 80 wrappers, `call_or_raise` return contract |
| `risk_client/types.py` | NEW — `AgentEnvelope`, `ToolResult`, ~15 Tier A TypedDicts |
| `risk_client/README.md` | NEW — usage docs + breaking-change note on return contract |
| `risk_client/pyproject.toml` | Version bump 0.1.0 → 0.2.0; `requires-python = ">=3.11"` |
| `scripts/generate_risk_client.py` | NEW — generator |
| `tests/test_risk_client.py` | Updated — existing tests updated for inner-result contract |
| `tests/test_risk_client_generator_sync.py` | NEW — drift test |
| `tests/test_risk_client_contract.py` | NEW — golden-key contract tests for Tier A methods |
| `CHANGELOG.md` | Entry |

**NOT touched**: `agent/registry.py`, `agent/building_blocks.py`, `routes/agent_api.py`, `mcp_tools/*`, `actions/*`.

**Deferred to follow-up**: parity expansion wrapping the 16 missing registered functions (D5).

---

## 8. Risks + subtleties

1. **Return type drift** (Codex R1/R2 highlighted): TypedDicts are static. Registered function changes its return shape → TypedDict silently diverges. Mitigation (revised R2): contract tests that exercise the *real registered tool callables* under existing test infra mocks and compare actual output keys against declared TypedDict keys (not hand-written payload mocks — those only prove wrapper mechanics). See §9. Long tail (Tier C `ToolResult`) is untracked by design.

2. **Inner-result breaking change** (NEW, from §3): Every existing consumer accessing `envelope["result"]["..."]` breaks. Primary consumer is AI-excel-addin sandbox. Release requires:
   - AI-excel-addin PR in lockstep to update sandbox code that unwrapped envelopes
   - CHANGELOG entry + README call-out
   - Consider a transition period where both `call()` (returns envelope) and new typed methods (return inner) coexist — `call()` stays, so consumers can fall back if needed

3. **Multi-param shape gating** (Codex R1): Some tools change shape on `include`, `include_matrices`, `by_account`, `include_risk` — not just `format`. Overloads can't capture this cleanly. Accept broad union returns for these (Tier A types are supersets); document in docstrings.

4. **`@handle_mcp_errors` decorator**: Registered functions are wrapped. `agent/registry.py` uses `_unwrap()` to bypass the wrapper and expose the real signature. Generator reuses the registry's already-unwrapped callable (accessed via `entry.callable`), so this is handled.

5. **`Any` in registered signatures**: `building_blocks.get_correlation_matrix(tickers: Any, ...)` — generator emits `Any` faithfully. Source-side tightening is a separate effort (could be a trailing Phase 1.8 or a follow-up).

6. **`output` forced "inline"** (Codex R1): `BLOCKED_PARAMS[output] = "inline"` makes `file_path` response branches unreachable from sandbox. TypedDict returns for Tier A tools that conditionally return `file_path` must **omit** that field — otherwise we lie about the sandbox's observable surface.

7. **Full denylist coverage** (D8): Not just `user_email` and `BLOCKED_PARAMS` — `user_id` too. Risk: if a new server-injected param is added later and denylist isn't updated, generator emits it in signature, server strips, client doesn't know why. Mitigation: drift test catches any registry-derived signature change; keep denylist as a single centralized constant with comments.

8. **AI-excel-addin tests may break** (broader scope now due to return contract): Existing sandbox code accessing `envelope["result"]` must be updated. Test-run AI-excel-addin against new client BEFORE release. If scope gets hairy, consider introducing `RiskClient` in parallel with `RiskClientV1` (legacy envelope-return) and migrate in a later step — but default plan is single-step replacement.

9. **CI drift test timing**: Generator test must run in the default test path, not a separate job. Ensure it runs before release-tagging.

10. **Python version**: `requires-python >=3.11` for `NotRequired`. Verify AI-excel-addin Docker (`ai-excel-addin-code-exec:latest`) runs Python 3.11+ — current image is `python:3.12-slim`, so safe.

---

## 9. Tests

### Existing tests to keep green (with updates)
- `tests/test_risk_client.py` (429 lines) — DummySession-based. **Updates needed**: tests currently assert the envelope shape (`{ok: True, result: ...}`) from method calls; these must be updated since typed methods now return inner result (§3). The underlying `call()` / `call_or_raise()` method tests stay unchanged.
- `tests/routes/test_agent_api.py` (551 lines) — server-side agent API tests. No changes required.
- `tests/test_tool_surface_sync.py` (140 lines) — cross-surface parity. No changes required.

### New tests
- **Drift test** (`tests/test_risk_client_generator_sync.py`): run generator, diff against committed output, fail on drift. Catches both (a) registry changes not regenerated and (b) hand-edits to generated file.
- **Contract tests** (`tests/test_risk_client_contract.py`) — NEW, revised after Codex R2/R4: DummySession-based tests only verify wrapper behavior, not server-side return shape. To actually mitigate return-shape drift, contract tests must exercise the *real registered tool callable* under mocks for its external dependencies (DB, FMP, brokerage). For each of the 15 Tier A methods:
  1. Import the registered callable via `agent.registry.get_registry()[name].callable`
  2. Call it under the existing test-infra mocks used by `tests/core/*` / `tests/mcp_tools/*` / `tests/services/*` (reuse mock portfolio state, FMP fixture data, stubbed brokerage adapters — do not rebuild per tool, per Codex R3)
  3. Collect the real output dict's top-level keys
  4. **Assert**: `set(TypedDict.__required_keys__) ⊆ set(real_output_keys)` — every required TypedDict key is actually produced by the tool. Catches server-side removals of expected fields.
  5. Optionally log keys present in real output but not declared in TypedDict (soft signal — useful for noticing new server-side fields we should consider typing; not a test failure)

This catches the drift case Codex highlighted: if server changes a function's return shape, the real tool's output keys change → contract test fails on missing `__required_keys__`. DummySession pattern retained only for signature-level smoke (P1.5).
- **Smoke test**: construct a `RiskClient` with a DummySession, call each of the 80 methods with minimal args, assert no TypeError at call site.

### Type checking
- `mypy --strict risk_client/` must pass (clean on the generated code and types module)
- `mypy --strict scripts/generate_risk_client.py` (acceptable stretch goal)
- New: `mypy` must succeed on a sample agent sandbox code block (add as a doctest or dedicated file): proves the typed client is usable with mypy on the consumer side

---

## 10. Open questions — resolved by Codex R1

All 8 original questions have recommendations from Codex R1:

| # | Question | Resolution |
|---|---|---|
| 1 | TypedDict vs dataclass | ✅ TypedDict (matches HTTP wire) |
| 2 | Committed source vs `.pyi` stubs | ✅ Committed source (runtime signatures matter for sandbox) |
| 3 | Overload coverage | ✅ Only 2-3 tools with clean `format` discriminant (narrowed from 3-4) |
| 4 | Parity expansion (80 → 96) | ✅ DEFER to follow-up; Phase 1 types existing 80 only |
| 5 | Fail hard on CI drift | ✅ Fail hard |
| 6 | Keep public `call()` / `call_or_raise()` | ✅ Keep; generated wrappers use `call_or_raise()` |
| 7 | Version bump | ✅ 0.2.0 (0.x allows breaking changes per semver) |
| 8 | Generator location | ✅ Top-level `scripts/generate_risk_client.py` |

### New questions raised by Codex R1 (still open)
- **Transitional legacy client?** Should the first release also keep an envelope-returning `LegacyRiskClient` for a deprecation window? Default: no, rip the bandaid. But AI-excel-addin review may want a hedge.
- **Which Tier A 15 tools are canonical?** Current list in D2 is my best guess based on registry traffic. Codex/user should confirm before P1.3 starts.

---

## 11. Success criteria

- [ ] All **80 existing** wrapped registered functions have typed method signatures on `RiskClient`
- [ ] Zero `**kw: Any` in generated `risk_client/__init__.py`
- [ ] All methods return either a Tier A `TypedDict`, `AgentEnvelope`, or `ToolResult` alias (no bare `dict[str, Any]`)
- [ ] Return contract: all generated methods use `call_or_raise()` and return the inner result
- [ ] Denylist correctly applied: no method accepts `user_email`, `user_id`, `backfill_path`, `output`, or `debug_inference`
- [ ] `mypy --strict risk_client/` exits 0
- [ ] All existing tests green (updated for inner-result contract)
- [ ] Drift test + contract tests green
- [ ] A sample agent sandbox code block (audit §6) type-checks under mypy
- [ ] AI-excel-addin sandbox code updated to consume inner-result shape; AI-excel-addin tests green
- [ ] `requires-python = ">=3.11"` in pyproject; version bumped 0.1.0 → 0.2.0
- [ ] README documents breaking-change + migration example
