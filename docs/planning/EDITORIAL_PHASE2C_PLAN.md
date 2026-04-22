# Overview Editorial Pipeline — Phase 2C Implementation Plan: Infrastructure

**Status**: DRAFT — pending Codex review
**Created**: 2026-04-13
**Inputs**:
- Architecture spec: `docs/planning/completed/OVERVIEW_EDITORIAL_PIPELINE_ARCHITECTURE.md` (sections 10, 14, 15)
- Audit findings: `docs/planning/EDITORIAL_PIPELINE_AUDIT.md`
- Phase 1 plan pattern: `docs/planning/completed/OVERVIEW_EDITORIAL_PIPELINE_PHASE1_PLAN.md`

This plan covers the **Phase 2C infrastructure improvements** — six items from the architecture spec §14 under "P2 — Infrastructure + UI." Four items are code changes; two are documentation/research tasks.

---

## 1. Plan Purpose

Phase 2C addresses infrastructure debt and quality gates that strengthen the editorial pipeline without adding new editorial content (generators, memory depth). These items are independent of Phase 2A (personalization) and Phase 2B (generator expansion) and can be executed in parallel.

**Goals**:
- Ship four code items as independently committable sub-phases
- Produce two documentation deliverables (observability, model benchmarking)
- Each code sub-phase has concrete file paths, test counts, and acceptance gates

**Non-goals**:
- New generators (Phase 2A/2B scope)
- Deep editorial memory usage (Phase 2D scope)
- Writing actual code (this is the plan, not the implementation)

---

## 2. Sub-phase Summary

| # | Sub-phase | Type | Scope | Duration | Depends on | Commits |
|---|---|---|---|---|---|---|
| C1 | Attention Items UI Component | Code | New design system component + container integration | ~3 days | None | 1 |
| C2 | `complete_structured()` helper + provider methods | Code | Standalone helper function + OpenAI/Anthropic overrides + arbiter/seeder migration | ~4 days | None | 1 |
| C3 | Architecture Test for Invalidation Hooks | Code | New test in `test_architecture_boundaries.py` | ~1 day | None | 1 |
| C4 | Eval Framework | Code | Fixture-based editorial pipeline scenarios | ~3 days | None | 1 |
| C5 | Observability Dashboards | Documentation | Telemetry catalog + dashboard spec + tooling recommendation | ~2 days | None | 0 (doc only) |
| C6 | LLM Arbiter Model Benchmarking | Research | Run eval suite across 3 models, document results + recommendation | ~3 days | C4 (uses eval fixtures) | 0 (doc only) |

**Total committable code units**: 4
**Total duration**: ~16 working days (~3 weeks), highly parallelizable
**Parallelizable**: C1, C2, C3, C4 are fully independent. C5 can run anytime. C6 benefits from C4 fixtures.

---

## 3. Dependency Graph

```
C1 (attention items UI)     — independent
C2 (complete_structured)    — independent
C3 (invalidation arch test) — independent
C4 (eval framework)         — independent
C5 (observability docs)     — independent
C6 (model benchmarking)     — soft dependency on C4 for eval fixtures
```

All six items are independent of Phase 2A/2B generators.

---

## 4. Cross-Cutting Concerns

### 4.1 Design system compliance (C1)
The attention items component must follow DESIGN.md: urgency hierarchy (watch/act/alert with defined color tokens), typography registers (Geist Mono for labels, Instrument Sans for prose), spacing scale (4px base unit).

### 4.2 Protocol backward compatibility (C2)
The existing `complete()` method on `CompletionProvider` must remain unchanged. `complete_structured()` is additive. Existing callers must continue to work without modification.

### 4.3 `actions/` transport neutrality
Per `tests/test_architecture_boundaries.py:200-213`, `actions/` cannot import `fastapi` or `mcp_tools`. Any new test or eval code respects this boundary.

---

## 5. Sub-phase C1 — Attention Items UI Component

### 5.1 Goal

New design system component that renders attention items from the editorial pipeline. Replaces inline rendering in the container with a proper component following DESIGN.md.

### 5.2 Current state

Backend schema includes `attention_items` on `OverviewBrief` (`models/overview_editorial.py`). Generators emit `attention_item` candidates. `BackendBriefAdapter.ts` adapts them (`adaptAttentionItems`). The container renders them inline but not following DESIGN.md precisely.

### 5.3 Design

**Component**: `AttentionCards`

**Visual treatment** (from DESIGN.md urgency hierarchy):
- Each card: `bg-surface` with `border-border-subtle`, `rounded-[6px]`, `px-4 py-3`
- Urgency dot: 6px circle:
  - `alert`: `bg-[hsl(var(--down))]` (red)
  - `act`: `bg-[hsl(var(--accent))]` (gold)
  - `watch`: `bg-[hsl(var(--text-muted))]` (gray)
- Category + urgency label: Geist Mono, 9.5px, uppercase, `tracking-[0.08em]`, `text-[hsl(var(--text-dim))]`
- Headline: Instrument Sans, 14px, `text-ink`, `leading-[1.55]`
- Action button: follows `ExitRamps.tsx` pattern — `text-[13px] text-foreground hover:text-ink` with arrow
- Layout: `grid gap-2.5 md:grid-cols-2 xl:grid-cols-3`
- Empty state: returns `null` (0 items = no section)

### 5.4 Component interface

```typescript
export interface AttentionCardItem {
  category: string;
  headline: string;
  urgency: 'alert' | 'act' | 'watch';
  action?: { label: string; actionType: 'navigate' | 'chat_prompt'; payload: string };
}

interface AttentionCardsProps {
  items: AttentionCardItem[];
  onNavigate?: (view: string) => void;
  onSendMessage?: (message: string) => void;
  className?: string;
}
```

### 5.5 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `frontend/packages/ui/src/components/design/AttentionCards.tsx` | Design system component | ~80 |
| `frontend/packages/ui/src/components/design/AttentionCards.test.tsx` | Vitest tests | ~120 |

### 5.6 Files to modify

| File | Change |
|---|---|
| `frontend/packages/ui/src/components/design/index.ts` | Export `AttentionCards` |
| `PortfolioOverviewContainer.tsx` | Replace inline rendering with `<AttentionCards>` |

### 5.7 Tests (4 tests)

1. Renders nothing when items array is empty
2. Renders 1-3 cards with correct urgency dot color per level
3. Action button triggers `onNavigate` for navigate type, `onSendMessage` for chat_prompt type
4. Cards without action render no button

### 5.8 Acceptance gate

- Correct DESIGN.md colors at all urgency levels
- Empty array produces no DOM output
- Container uses new component instead of inline rendering
- No regressions in overview layout

### 5.9 Rollback

Revert `AttentionCards.tsx`, restore inline rendering in container.

---

## 6. Sub-phase C2 — `complete_structured()` Helper + Provider Methods

### 6.1 Goal

Add a standalone `complete_structured()` helper function with native structured output on both providers. Migrate arbiter and memory seeder from string JSON parsing to typed responses. The `CompletionProvider` Protocol itself is NOT modified — it remains a structural protocol requiring only `complete()`.

### 6.2 Current state

`CompletionProvider` protocol (`providers/interfaces.py`) defines `complete()` returning `str`. Arbiter (`core/overview_editorial/llm_arbiter.py`) calls `complete()`, then does `json.loads(raw)` and manually validates each field — 50+ lines of defensive parsing.

Arch spec §2 explicitly deferred this: "Phase 1 uses string JSON + Pydantic validation."

### 6.3 Design

**Important**: `CompletionProvider` is a `@runtime_checkable` structural Protocol (`providers/interfaces.py:204`). The concrete providers (`OpenAICompletionProvider`, `AnthropicCompletionProvider`) do NOT inherit from it — they satisfy it structurally. This means a default method on the Protocol would NOT be inherited by the providers. Two viable approaches:

**Approach A (recommended): Standalone helper + provider overrides**

Add a module-level helper function `complete_structured()` in `providers/completion.py` that implements the fallback path:

```python
def complete_structured(
    provider: CompletionProvider,
    prompt: str,
    *,
    response_model: type[T],
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = 2000,
    temperature: float = 0.5,
    timeout: float | None = None,
) -> T:
    """Structured output via provider. Uses native structured output if provider supports it, else falls back to complete() + parse."""
    if hasattr(provider, 'complete_structured'):
        return provider.complete_structured(prompt, response_model=response_model, ...)
    raw = provider.complete(prompt, system=system, model=model,
                           max_tokens=max_tokens, temperature=temperature, timeout=timeout)
    return response_model.model_validate(json.loads(raw))
```

Then add `complete_structured()` methods directly on `OpenAICompletionProvider` and `AnthropicCompletionProvider` (which use native structured output). The Protocol itself remains unchanged — only `complete()` is required.

**Approach B: Subprotocol**

Define `StructuredCompletionProvider(CompletionProvider, Protocol)` with the additional method. Callers that need structured output type-check against the subprotocol. More type-safe but adds complexity.

**Recommendation**: Approach A. Simpler, backward-compatible, and the `hasattr` check is acceptable for a 2-implementation system.

**OpenAI implementation**: Use `response_format={"type": "json_schema", ...}` with Pydantic model JSON schema.

**Anthropic implementation**: Use tool use with a single tool whose input schema is the Pydantic model's JSON schema. Scan `response.content` blocks for `tool_use` type (do NOT assume `response.content[0].input` — there may be text blocks before the tool use block).

**Migration targets**: Both the arbiter (`core/overview_editorial/llm_arbiter.py:91`, ~58 lines of defensive JSON parsing) AND the memory seeder (`core/overview_editorial/memory_seeder.py:111`, which also does `complete()` + `json.loads()` + `EditorialMemory.model_validate()`). Migrating both eliminates all duplicate parsing logic.

Define `ArbiterEnhancement(BaseModel)` for the arbiter's response shape. Define or reuse `EditorialMemory` for the seeder.

### 6.4 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `tests/providers/test_completion_structured.py` | Unit tests for both providers | ~200 |

### 6.5 Files to modify

| File | Change |
|---|---|
| `providers/completion.py` | Add `complete_structured()` helper function + method on both providers |
| `core/overview_editorial/llm_arbiter.py` | Define `ArbiterEnhancement`, migrate `enhance()` to use `complete_structured()` |
| `core/overview_editorial/memory_seeder.py` | Migrate `_llm_seed_from_summary()` to use `complete_structured()` |
| `tests/core/overview_editorial/test_llm_arbiter.py` | Update `_FakeProvider`, add structured path tests |

### 6.6 Tests (10 tests)

1. OpenAI `complete_structured()` returns validated Pydantic model via `response_format`
2. Anthropic `complete_structured()` returns validated Pydantic model via tool use (scan content blocks for `tool_use` type)
3. Fallback path works when provider only has `complete()` (no `complete_structured` method)
4. `ValidationError` on malformed response (both native and fallback paths)
5. Existing `complete()` unchanged on both providers
6. Arbiter `enhance()` uses structured path correctly
7. Arbiter falls back gracefully when `complete_structured()` fails (returns `None`, logs warning)
8. Memory seeder `_llm_seed_from_summary()` uses structured path correctly
9. Memory seeder falls back gracefully on failure
10. `_FakeProvider` in arbiter tests supports both methods

### 6.7 Acceptance gate

- `CompletionProvider` Protocol unchanged (no new required methods)
- `complete_structured()` helper dispatches to native method when available, fallback otherwise
- Both arbiter AND memory seeder migrated — no remaining `json.loads()` + `model_validate()` patterns
- Arbiter telemetry unchanged
- All existing arbiter + seeder tests pass

### 6.8 Rollback

Revert `completion.py`, arbiter, memory seeder. No data migration. Protocol untouched.

---

## 7. Sub-phase C3 — Architecture Test for Invalidation Hooks

### 7.1 Goal

Automated test that fails if a known mutation path lacks `invalidate_brief_cache`. Currently relies on review discipline (arch spec §3.3).

### 7.2 Design

Add `test_mutation_paths_invalidate_brief_cache()` to `tests/test_architecture_boundaries.py`:

1. Registry of known mutation paths at **function-level granularity** (not just file-level, since a single file may have multiple mutation handlers that each need the call):
   ```python
   MUTATION_PATHS_REQUIRING_INVALIDATION = [
       ("workers/tasks/positions.py", "sync_provider_positions", "Brokerage sync completion"),
       ("routes/onboarding.py", "import_onboarding_csv", "CSV import (short form)"),
       ("routes/onboarding.py", "import_onboarding_csv_full", "CSV import (full form)"),
       ("core/overview_editorial/editorial_state_store.py", "set_editorial_memory", "Editorial memory write"),
       ("core/overview_editorial/editorial_state_store.py", "seed_editorial_memory_if_missing", "Auto-seed memory write"),
   ]
   ```

   Current verified call sites: `workers/tasks/positions.py:54`, `routes/onboarding.py:835` (`import_onboarding_csv`), `routes/onboarding.py:886` (`import_onboarding_csv_full`), `editorial_state_store.py` via `_fire_invalidation_callbacks()` called from both `set_editorial_memory` and `seed_editorial_memory_if_missing` (at `:85` and `:119` respectively).

2. AST scanning at function-level: parse the file, find the target function's AST node, walk its body for `invalidate_brief_cache` calls (or calls to `_fire_invalidation_callbacks` which wraps it). This is more robust than file-level scanning — it catches the case where one handler in a file regresses while another keeps the call.

3. Failure message explains what to do (add the call, or add to allowlist with justification).

### 7.3 Files to modify

| File | Change |
|---|---|
| `tests/test_architecture_boundaries.py` | Add registry + test function |

### 7.4 Tests (1 parametrized test)

1. `test_mutation_paths_invalidate_brief_cache` — parametrized over registry

### 7.5 Acceptance gate

- Test passes on current codebase
- Removing `invalidate_brief_cache` from any file causes failure
- Clear failure message

### 7.6 Rollback

Remove test function. No behavior change.

---

## 8. Sub-phase C4 — Eval Framework

### 8.1 Goal

Fixture-based editorial pipeline scenarios for quality validation. Deterministic checks: "given this portfolio + this memory, the brief contains expected elements."

### 8.2 Design

**Fixture structure**: JSON files containing portfolio snapshot data + editorial memory + expected outcomes + **explicit generator list**.

**Generator pinning**: Each fixture specifies which generators to use (e.g., `["concentration", "risk", "performance"]`). The test runner constructs `EditorialPolicyLayer(generators=[...])` with exactly those generators, NOT the default list. This makes eval scenarios stable across Phase 2A/2B generator additions — the default generator set in `EditorialPolicyLayer.__init__` changes as new generators land, but eval scenarios don't drift.

**Test runner**: `tests/core/overview_editorial/test_eval_scenarios.py` — loads fixtures, constructs `PortfolioContext`, runs **pinned** generators + policy, asserts expected outcomes.

**5 initial scenarios**:

| # | Archetype | Expected Lead | Expected Attention |
|---|---|---|---|
| 1 | Concentrated defensive (28%+ single position, low beta) | `concentration` | concentration alert |
| 2 | High-risk growth (high vol, leverage > 1) | `risk` | risk alert |
| 3 | Underperforming (negative return vs benchmark) | `performance` | None (watch) |
| 4 | Balanced (diversified, moderate risk) | Any | None |
| 5 | Risk limit violations | `risk` | risk alert |

### 8.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `tests/core/overview_editorial/eval_scenarios/` | Directory for fixtures | — |
| `tests/core/overview_editorial/eval_scenarios/*.json` | 5 scenario fixtures | ~80 each |
| `tests/core/overview_editorial/test_eval_scenarios.py` | Parametrized test runner | ~200 |

### 8.4 Tests (5 parametrized)

Each scenario asserts:
1. Lead insight category matches expected
2. Metric strip contains expected category-affiliated metrics
3. Attention items match expected categories and urgency
4. Top-ranked candidate is from expected category

### 8.5 Acceptance gate

- All 5 scenarios pass
- Adding a new scenario = adding a JSON file
- Tests run as part of normal `pytest` suite

### 8.6 Rollback

Delete `eval_scenarios/` directory and test file. No production code affected.

---

## 9. Sub-phase C5 — Observability Documentation

### 9.1 Goal

Document telemetry events, define key metrics, recommend dashboard tooling. Documentation deliverable, not code.

### 9.2 Deliverable

Create `docs/ops/EDITORIAL_PIPELINE_OBSERVABILITY.md` containing:

**Section 1: Telemetry Event Catalog** — all structured log events with fields, types, trigger conditions.

**Section 2: Key Metrics**:
- Brief generation rate
- Cache hit rate
- Lead insight category distribution (validates editorial variety)
- Arbiter success rate (target ≥ 90%)
- Data status distribution
- Brief generation latency (p50/p95/p99)

**Section 3: Dashboard Tooling Recommendation**:
- Option A: Structured log queries (lowest cost)
- Option B: Grafana + log-based data source
- Option C: Lightweight Python script (founder stage)
- Recommendation: Start with Option C + define Option A templates

**Section 4: Sample Queries** — exact query per metric.

### 9.3 Acceptance gate

- All telemetry events from arch spec §10.1 documented
- Each key metric has a defined query
- Actionable tooling recommendation

---

## 10. Sub-phase C6 — LLM Arbiter Model Benchmarking

### 10.1 Goal

Benchmark GPT-4.1 (current), Claude Haiku, Claude Sonnet for the arbiter. Recommend default model.

### 10.2 Eval criteria

| Criterion | Weight |
|---|---|
| Headline quality (1-5) | 30% |
| Evidence coherence (1-5) | 25% |
| Parse success rate (%) | 20% |
| Latency (p50/p95) | 15% |
| Cost per enhancement | 10% |

### 10.3 Methodology

- Use C4 eval fixtures to generate 5 deterministic briefs with **pinned generators** (same Phase 1 set: Concentration, Risk, Performance) for reproducibility
- Record exact provider/model IDs from env vars for each run
- Run each brief through the arbiter with 3 models (15 runs × 3 repeats = 45 API calls)
- Score quality manually or with LLM judge
- Record latency + token counts

### 10.4 Deliverable

Create `docs/ops/EDITORIAL_ARBITER_MODEL_BENCHMARK.md` with results table, latency distribution, cost comparison, recommendation, configuration instructions.

### 10.5 Acceptance gate

- All 3 models tested with ≥ 5 scenarios each
- Results include all 5 eval criteria
- Clear recommendation with justification

---

## 11. Sequencing

**Week 1**: C1 (attention items), C2 (complete_structured), C3 (arch test) in parallel. C3 ships in 1 day.

**Week 2**: C4 (eval framework). C1/C2 finish. C5 (observability) starts.

**Week 3**: C6 (model benchmarking) after C4 fixtures available. C5 finishes.

**Total**: ~3 weeks with parallelization.

---

## 12. Summary Table

| # | Item | Type | Files Created | Files Modified | Tests | Duration |
|---|---|---|---|---|---|---|
| C1 | Attention Items UI | Code | 2 | 2 | 4 | ~3 days |
| C2 | `complete_structured()` | Code | 1 | 4 | 8 | ~4 days |
| C3 | Invalidation Arch Test | Code | 0 | 1 | 1 | ~1 day |
| C4 | Eval Framework | Code | 7 | 0 | 5 | ~3 days |
| C5 | Observability Docs | Doc | 1 | 0 | 0 | ~2 days |
| C6 | Model Benchmarking | Research | 1 | 0 | 0 | ~3 days |
| **Total** | | | **12** | **7** | **18** | **~16 days** |
