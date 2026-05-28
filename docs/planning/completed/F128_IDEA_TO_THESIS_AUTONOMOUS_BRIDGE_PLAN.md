# F128 Idea-To-Thesis Autonomous Bridge Plan

**Status:** ✅ COMPLETE / IMPLEMENTED 2026-05-27 — Codex PASS (R5, 5-round arc). Shipped to AI-excel-addin `main`: `495c4a47` + `253c6444`. 44 tests pass / 1 skipped; dry-run verified. Live smoke 2026-05-27 confirmed the bridge wiring is correct end-to-end and correctly gated at the autonomous `state_write` boundary (autonomous completion needs F131 `research_producer` + a small wiring step — tracked as `F128-followup` in `docs/TODO.md`).
**Date:** 2026-05-26
**Owner:** Thesis & Research Artifact autonomous-loop workstream
**Primary implementation repo:** `/Users/henrychien/Documents/Jupyter/AI-excel-addin`
**Tracking repo:** `/Users/henrychien/Documents/Jupyter/risk_module`

## Executive Summary

F128 is an orchestration gap, not a missing schema or missing `start_research` tool.

The existing system already has the typed ingress foundation:

- `InvestmentIdea` is a typed schema (`schema/investment_idea.py:61`). **Required** fields: `ticker`, `thesis`, `source`, `source_date`, `idea_id`, `surfaced_at`, `source_ref` (with a `surfaced_at >= source_date` model validator). **Optional**: `company_name`, `strategy`, `direction` (default `long`), `catalyst`, `timeframe`, `conviction`, `tags`, `suggested_process_template_id`, `label`, `metadata`. The required `ticker` is what lets the run contract call `start_research(ticker=idea.ticker, ...)`; the live smoke fixture must populate every required field (and satisfy `surfaced_at >= source_date`) or `InvestmentIdea` validation rejects it before the agent launches.
- `start_research(..., idea=...)` is exposed through risk_module MCP.
- AI-excel-addin `start_research_from_idea(...)` persists the idea, creates/reuses a research file, writes idea provenance, creates/reuses the draft handoff, and bootstraps an empty typed Thesis shell with `from_idea`.
- Tool-level tests already prove the idea payload is forwarded and that response fields such as `idea_seeded` and `thesis_bootstrapped` are surfaced.

What is missing is one autonomous workflow that consumes a single idea and completes the loop:

```text
InvestmentIdea
  -> start_research(idea=...)
  -> read bootstrapped Thesis shell
  -> drive thesis-consultation (autonomous): research, synthesize, self-apply typed thesis
  -> append a Decisions Log entry (with idea provenance)
  -> leave a replayable run artifact
```

The recommended fix is a thin `idea-to-thesis` ingress skill plus a deterministic run wrapper. It drives the existing canonical thesis writer (`thesis-consultation`) in a new autonomous mode rather than re-composing producers; it should not create another thesis model, another ingestion contract, another free-form memory write path, or a duplicate thesis writer.

## Confirmed Design Decisions (2026-05-26)

Two architectural forks were resolved with the user after Codex R1:

- **Skill scope = `scope: ticker`** (not a new `scope: idea`). The agent-gateway `SkillProfile` only accepts `ticker`/`portfolio`/`industry` (`packages/agent-gateway/agent_gateway/skills.py:218`); adding `idea` would require a PyPI-package enum change rippling through every consumer. The precedent composite producer `position-initiation.md` starts from an idea and uses `scope: ticker`. The "idea-only input" constraint is enforced in the skill body + wrapper validation, NOT via scope.
- **Composition = drive the canonical thesis writer (`thesis-consultation`) in a new autonomous mode, in-context** (revised after Codex R2). The R2 "thin orchestrator re-composes 4 propose-only producers as sub-agents" design fought the codebase twice: sub-agent return values carry only streamed response text (`runner.py:929`), not the producers' `ops:` blocks (which they persist via `memory_write` and forbid echoing); and `thesis-articulation` needs a fuller diligence stack than FR+CF+IR supply, so it would usually return `THESIS_INSUFFICIENT`. Instead, `idea-to-thesis` is a thin ingress skill that `invoke_skill`-text-injects `thesis-consultation`, which already loads the full diligence methodology in-context, SELF-APPLIES the typed thesis via `thesis_create`/`thesis_update_section`, and writes its own Decisions Log (`thesis-consultation.md:106-124, 259-261, 245`). Text-injection runs those self-applied writes in the orchestrator's own context, so there is no sub-agent ops-parsing problem. The one addition to `thesis-consultation` is a `MODE=autonomous` recognition rule modeled on `peer-curation.md:49-52` that skips its interactive breakpoints; the interactive path stays intact. (Considered + rejected: a standalone autonomous writer that duplicates thesis-consultation's discipline — duplication/divergence risk; `position-initiation` — too heavy, runs through sizing + trade execution.)

## Current State

### Ingress and shell creation already work

`risk_module/actions/research.py:start_research(...)` accepts `idea: dict[str, Any] | None`, forwards it to the AI-excel-addin research gateway, and returns the important result flags:

- `idea_seeded`
- `idea_backfilled`
- `thesis_bootstrapped`
- `draft_handoff_provenance_seeded`
- `process_template_applied`

`risk_module/mcp_tools/research.py:start_research(...)` exposes that to agents. `risk_module/mcp_server.py:start_research(...)` exposes the same MCP surface.

AI-excel-addin `api/research/research_service.py:start_research_from_idea(...)` handles idempotency by `idea_id` and by `(ticker, label)`, backfills existing rows when appropriate, and invokes `bootstrap_from_idea(...)`.

`api/research/thesis_service.py:bootstrap_from_idea(...)` creates a typed Thesis row if one does not already exist. It intentionally leaves `thesis.statement` empty while preserving seed fields:

- `thesis.direction`
- `thesis.strategy`
- `thesis.conviction`
- `thesis.timeframe`
- `from_idea.idea_id`
- `from_idea.thesis_hypothesis`
- optional template-seeded qualitative factors

This means F128 should not call `thesis_create` blindly after `start_research(idea=...)`. The correct next step is `thesis_read` and then section/patch updates against the bootstrapped shell.

### The existing skills are atomic producers

Relevant shipped skills already exist:

- `fundamental-research` - source registration and `business_overview` proposal.
- `critical-factors` - materiality, differentiated-view claims, assumptions, catalysts, risks, and watch items.
- `identifying-risk` - risks and invalidation triggers.
- `thesis-articulation` - statement, direction, strategy, conviction, timeframe, differentiated view, catalysts, and pitch coherence.
- `decision-log` - canonical Decisions Log entry shape.
- `thesis-consultation` - broad thesis writer that knows how to register or update a typed Thesis, but it is ticker-scoped and does not own idea ingress.

These skills should not be duplicated. F128 should create a small bridge that sequences them for one idea and enforces the end-of-run persistence contract.

### Existing tests cover the lower layers

Risk_module tests already cover idea forwarding:

- `tests/mcp_tools/test_research_start_idea.py`
- `tests/routes/test_agent_api_idea.py`
- `tests/mcp_tools/test_process_template.py`

AI-excel-addin tests already cover server-side idea ingress:

- `tests/api/research/test_start_research_from_idea.py`
- `tests/integration/test_idea_end_to_end.py`
- `tests/integration/test_investment_schema_spine_e2e.py`

Those tests are necessary but not sufficient. They prove direct tool calls. They do not prove an autonomous agent can take an idea and finish a coherent Thesis write loop.

## Root Issue

The current system has durable components but no single autonomous contract for this workflow.

The practical failure modes are:

- An idea is registered and gets a typed Thesis shell, but the shell remains empty because no workflow fills `thesis.statement` and the core typed sections.
- Atomic skills produce useful research artifacts, but no bridge guarantees their outputs are applied to the same `research_file_id`.
- `from_idea` is present, but downstream Thesis fields may not trace back to the idea-run context in `decisions_log`.
- An agent can run a ticker skill without carrying the `idea_id`, `source_ref`, `label`, or process-template context into the run.
- Live autonomous runs can appear successful in chat while leaving no complete typed Thesis state.

This is why F128 is a loop-closure item: it must bind ingress, research, typed writes, and audit into one run.

## Proposed Architecture

### 1. Add an `idea-to-thesis` producer skill

Add a new AI-excel-addin skill file:

```text
api/memory/workspace/notes/skills/idea-to-thesis.md
```

Suggested frontmatter:

```yaml
---
name: idea-to-thesis
description: Convert one typed InvestmentIdea into a grounded typed Thesis by registering/reusing the research workspace via start_research, then driving thesis-consultation in autonomous mode to synthesize and self-apply the typed thesis and append a Decisions Log entry.
version: 1.0
scope: ticker
state_class: producer
agent_callable: true
resumable: true
max_turns: 85
max_budget_usd: 12.0
mcp_servers:
  - portfolio-mcp
  - research-corpus-mcp
  - idea-workbench-mcp
mcp_tools:
  portfolio-mcp:
    - start_research
    - thesis_create
    - thesis_update_section
    - apply_patch_ops
    - thesis_append_decisions_log
    - get_price_target
  research-corpus-mcp:
    - thesis_read
    - thesis_list
    - list_research_files
  idea-workbench-mcp:
    - search_findings
    - get_ticker_signals
    - search_screen_hits
---
```

Frontmatter notes:
- `scope: ticker` per Confirmed Design Decisions. `mcp_servers` MUST be a YAML list — the loader/validation tests reject a comma-separated string (`tests/test_skill_validation.py:350`).
- Because composition is `invoke_skill` text-injection (NOT a sub-agent), the injected `thesis-consultation` runs in idea-to-thesis's OWN tool environment. So idea-to-thesis must declare a SUPERSET of thesis-consultation's servers/tools: portfolio-mcp (`start_research`, `thesis_create`/`thesis_update_section`, `apply_patch_ops`, `thesis_append_decisions_log`, `get_price_target`), research-corpus-mcp (`thesis_read`, `thesis_list`, `list_research_files`), AND idea-workbench-mcp — thesis-consultation calls `idea-workbench-mcp.search_findings` / `get_ticker_signals` / `search_screen_hits` in its research phase (`thesis-consultation.md:144`), so it is NOT optional (corrected per Codex R3). Data servers (FMP/EDGAR) are channel/always-on tier, exactly as for thesis-consultation today.
- **`mcp_tools` is a restrictive PROMOTION ALLOWLIST, not additive documentation** (corrected per Codex R4): the autonomous runtime loads only the listed deferred tools from each server (`api/agent/autonomous/entry.py:545`, `api/agent/autonomous/runner.py:402`, `api/agent/shared/tool_catalog.py:927`; partial-promotion behavior in `tests/test_run_agent.py:2329`). The `mcp_tools` block above therefore enumerates EVERY tool the ingress + injected writer call — declaring only `get_price_target` (R4) would have excluded the thesis write tools and broken the run. Reconcile against the analyst autonomous profile's always-on core set at implementation: listing a tool that is already core is harmless; omitting a deferred one breaks the run.
- `max_turns: 85` / `max_budget_usd: 12.0` cover the FULL run in ONE loop, because text-injection accumulates the injected thesis-consultation synthesis into idea-to-thesis's own envelope (no sub-agent accumulation). Comparable to a complete thesis-consultation run plus ingress overhead. (This is back UP from R2's 28/16 — R2 sized for a thin sub-agent orchestrator that no longer exists.)

The skill input must be exactly one typed idea payload or one resolvable idea reference. Do not accept an open-ended ticker-only request; ticker-only initiation belongs to the existing ticker-scoped skills. The skill is ticker-scoped for produced-artifact purposes but idea-gated on input.

### 2. Add a deterministic wrapper

Add a wrapper script in AI-excel-addin, for example:

```text
scripts/run_idea_to_thesis.py
```

The wrapper should:

- Load a JSON `InvestmentIdea` from a file or from an idea-workbench reference.
- Validate it with `schema.InvestmentIdea` before launching the agent.
- Launch the autonomous skill with a fixed task prompt that includes the serialized idea and requires a final JSON run summary.
- Write a run artifact with the input idea, `research_file_id`, thesis id, applied write summary, decision-log entry id, output artifact paths, and transcript/log references.
- Support dry-run and live-run modes.

The wrapper makes the live path testable without requiring a human to manually craft the prompt each time.

### 3. Define the run contract

Every `idea-to-thesis` run must follow this sequence:

1. Validate the `InvestmentIdea` input.
2. Call `start_research(ticker=idea.ticker, label=idea.label, idea=idea, format="agent")`.
3. Extract `research_file_id`.
4. Call `thesis_read(research_file_id=...)`.
5. Confirm `from_idea.idea_id == idea.idea_id`.
6. Drive the canonical thesis writer in autonomous mode against the bootstrapped shell: `invoke_skill(skill_name="thesis-consultation", args="MODE=autonomous CALLER=idea-to-thesis TICKER=<idea.ticker> RESEARCH_FILE_ID=<research_file_id> IDEA_ID=<idea.idea_id>")`. In autonomous mode thesis-consultation: loads the diligence methodology in-context; researches the name (corpus / FMP / EDGAR) and registers sources via `apply_patch_ops(register_sources)` where evidence supports claims (records data gaps otherwise); SELF-APPLIES the typed thesis into the EXISTING shell via `thesis_update_section`. **Write mechanics (corrected per Codex R3):** `thesis_update_section` takes `section_key` + native `section_data` (a dict/list, NOT a JSON string and NOT a `value=` field — `api/research/routes.py:1702`). The SCALAR fields the bootstrap left empty — `statement`, `direction`, `strategy`, `conviction`, `timeframe` — are written via `section_key="thesis"` with `section_data={statement, direction, ...}`; scalar field names are NOT valid section keys, `"thesis"` is the editable section (`routes.py:91,473`). The structured sections are each their own `section_key` update with native `section_data`: `consensus_view`, `differentiated_view`, `quantitative_framing`, `catalysts`, `risks`, `invalidation_triggers`, `valuation`, `model_ref`. It does NOT call `thesis_create` (the shell exists; create is exception-only). Source-ref-gated ops (e.g. `add_differentiated_view_claim`) stay propose-only/deferred when sources are not yet registered, preserving that content in the section payload (mirrors `thesis-consultation.md:272`). Because this is text-injection, all writes execute in idea-to-thesis's own context. NOTE: thesis-consultation's current existing-thesis refresh branch (`thesis-consultation.md:261`) enumerates only the structured section_keys and omits the scalars; the `MODE=autonomous` addition MUST write the scalars on the update branch via `section_key="thesis"`, since F128 always hits the existing-shell path with an empty `statement`.
7. thesis-consultation autonomous mode writes the single mandatory Decisions Log entry itself (as `peer-curation` does for its caller — `position-initiation.md:129`), stamped with the idea provenance passed via args (`caller=idea-to-thesis`, `idea_id`, applied sections/ops, verdict, `patch_ops_applied` as structured op-preview dicts). idea-to-thesis verifies exactly one provenance-stamped entry exists and does NOT append a duplicate (one entry per run — see Idempotency Predicate).
8. Read the Thesis again (`thesis_read`) and emit a final JSON run summary.

The bridge should treat the bootstrapped Thesis shell as the canonical target. If `thesis_read` shows that no Thesis exists, it may call `thesis_create(research_file_id=..., initial_fields=...)`; that should be an exception path, not the normal path.

### 4. Composition: drive thesis-consultation in autonomous mode (in-context)

`idea-to-thesis` does NOT spawn sub-agents and does NOT re-compose FR/CF/IR/TA. It text-injects the canonical thesis writer.

Mechanism:

1. `invoke_skill(skill_name="thesis-consultation", args="MODE=autonomous CALLER=idea-to-thesis TICKER=<t> RESEARCH_FILE_ID=<id> IDEA_ID=<idea_id>")`. `invoke_skill` is text-injection (`api/agent/shared/tool_handlers.py:750`): thesis-consultation's instructions run inside idea-to-thesis's own agent loop, so every tool call it makes (`thesis_update_section`, `apply_patch_ops`, `register_sources`, `thesis_append_decisions_log`) executes in-context as idea-to-thesis's own calls. There is no sub-agent return boundary to parse — this is the core fix for Codex R2 [P1] #1.
2. thesis-consultation already loads the full diligence methodology in-context (business-evaluation, BQA, financial-red-flags, competitive-position, comparative-analysis, critical-factors, earnings-scenarios, materiality-analysis, identifying-risk, quantifying-risk, managing-risk, thesis-articulation — `thesis-consultation.md:106-124`) and SELF-APPLIES the typed thesis (`:259-261`). So the completeness gap that sank the FR+CF+IR→TA stack (Codex R2 [P1] #2) does not exist here: the writer pulls the full stack itself.
3. The one required change to `thesis-consultation`: add a `MODE=autonomous` recognition rule (precedent `peer-curation.md:49-52`) that (a) skips the interactive breakpoints ("ask one compact question", "propose then let user edit"), (b) accepts `CALLER` / `IDEA_ID` / `RESEARCH_FILE_ID` args, (c) stamps idea provenance into its mandatory Decisions Log entry. The interactive (non-autonomous) path must stay unchanged and keep its user breakpoints; both paths get tests.

Responsibility split:

- `thesis-consultation` (autonomous mode): all research, methodology synthesis, typed-thesis section writes (self-applied), source registration, and the single Decisions Log entry.
- `idea-to-thesis`: validate the idea, call `start_research(idea=...)`, confirm `from_idea` matches, invoke thesis-consultation autonomous with provenance args, verify one provenance-stamped decisions-log entry exists, emit the run summary. It owns ingress + target identity (`research_file_id`) + run audit, not the thesis-writing mechanics.

**Two implementation constraints surfaced by Codex R3 (both in scope for the autonomous-mode change, not separate work):** (a) idea-to-thesis must declare the full server/tool superset thesis-consultation uses — portfolio-mcp incl. `get_price_target`, research-corpus-mcp, AND idea-workbench-mcp (see §1 frontmatter notes), because the injected run executes in idea-to-thesis's tool environment. (b) The `MODE=autonomous` addition must write the empty scalar fields (`statement` etc.) on the EXISTING-shell update branch via `thesis_update_section(section_key="thesis", section_data={...})`; thesis-consultation's current refresh branch omits the scalars.

This reuses the canonical writer (no duplication), inherits its completeness, and sidesteps the sub-agent ops-return problem. The propose-only producer skills (FR/CF/IR/TA) are unchanged and unused by F128; they remain available for other workflows. (thesis-consultation itself loads the same methodology those skills encode, so their analytical content is not lost.)

### 5. Multi-user and identity requirements

F128 must be multi-user ready from the first implementation.

Requirements:

- Never hard-code user id `1`, user email, or local DB paths.
- Use the existing autonomous MCP identity setup and signed end-user claim path.
- Persist all writes through MCP/gateway tools, not direct SQLite access.
- Carry `research_file_id` returned by `start_research`; do not resolve by ticker alone after the initial start.
- Preserve `idea_id` idempotency. Re-running the same idea should reuse the same research file and append a new decision-log entry only if the bridge actually performed a new review/write.
- The run artifact should include the resolved user identity only as the platform-safe user reference already exposed by the runtime, not secrets or session tokens.

### 6. Write policy and F134 interaction

The bridge writes Thesis state (`apply_patch_ops` / `thesis_update_section` / `thesis_append_decisions_log` are `state_write`). In interactive/dev use it runs with existing approval gates. Headless/scheduled live writes must be gated.

**Runtime contract (resolves Codex R1 [P2] #8 — make the boundary enforceable, not aspirational):** the wrapper takes an explicit `--mode {dry-run|live-dev|live-headless}`. `live-headless` is REFUSED at wrapper entry unless the F128 workflow is present in the F134 autonomous-write policy registry (or the post-F2j scoped `state_write` grant re-homed as F129 PR-A — see the F134 reconciliation note in `docs/TODO.md`). `live-dev` requires explicit operator invocation and is never reachable from a scheduler. Absence of the policy grant is a hard refusal, not a warning — the wrapper does not assume "the caller is interactive."

Practical sequencing:

- Implement the skill and wrapper first (dry-run + live-dev only).
- Add deterministic tests that do not require a live LLM.
- Wire `live-headless` only after F134 (or the F129 PR-A scoped grant) classifies this workflow.

F128 does not weaken F134. It becomes one of the concrete workflows F134/F2j classifies and tests.

## Persistence Contract

At completion, a successful F128 run should leave:

- A research file with `idea_id`, `idea_provenance`, and `source_ref`.
- A typed Thesis with `from_idea.idea_id` matching the input.
- A non-empty `thesis.statement`.
- Direction, strategy, conviction, and timeframe populated from the idea or the final articulation.
- At least one registered source or a clear data-gap verdict explaining why sourced claims could not be written.
- A populated `business_overview` / `consensus_view` / `differentiated_view` section.
- Materiality + critical-factor (quantitative framing) output.
- Risks and invalidation triggers when source support is available.
- One Decisions Log entry with:
  - `skill="idea-to-thesis"`
  - `decision` naming create/update/no-op outcome
  - `rationale` carrying `idea_id`, source context, skill sequence, and write summary
  - `patch_ops_applied` as structured op previews, not strings
  - `verdict` if F125-era optional verdict support is available

If the run cannot complete the full stack, it should still persist the safe subset and append a decision-log entry with a partial or insufficient-data verdict.

## Test Plan

### Unit and contract tests

Add tests for the wrapper:

- Valid idea JSON is accepted; `fixtures/ideas/f128_smoke_msft.json` is created and includes ALL required InvestmentIdea fields (`ticker`, `thesis`, `source`, `source_date`, `idea_id`, `surfaced_at`, `source_ref`) and satisfies `surfaced_at >= source_date` — a test asserts it validates as `InvestmentIdea`.
- Invalid idea JSON (e.g., missing `source_ref`, or `surfaced_at < source_date`) fails before launching an agent.
- The generated task prompt includes exactly one idea payload and requires same-`research_file_id` writes.
- Dry run produces a plan artifact without calling the live agent.
- User identity is sourced from the runtime/config, not from hard-coded constants.
- `--mode live-headless` is REFUSED unless the F134 / F129-PR-A policy grant is present (assert the hard refusal).

### Skill validation tests

Extend skill validation to prove:

- `idea-to-thesis` exists, is `agent_callable`, `scope: ticker`, `state_class: producer`, and `mcp_servers` parses as a YAML list (not a comma-separated string).
- The idea-to-thesis skill text names `start_research`, `invoke_skill` (driving `thesis-consultation`), and `thesis_read` (verification), and forbids ticker-only INPUT (idea-gated) while remaining ticker-scoped for produced artifacts.
- `thesis-consultation` has a `MODE=autonomous` recognition rule (peer-curation pattern) that skips interactive breakpoints and accepts `CALLER` / `IDEA_ID` / `RESEARCH_FILE_ID`; a companion test asserts the interactive path still gates (no behavior change without `MODE=autonomous`).

### Mocked orchestration test

Add a non-LLM test for the deterministic wrapper with mocked autonomous output:

- Input idea is validated.
- Mock run returns `research_file_id`, write summary, and decision-log entry id.
- Wrapper writes a run artifact.
- The artifact is schema-valid and includes the expected identity fields.

Add a non-LLM test for thesis-consultation autonomous mode: with `MODE=autonomous` + `CALLER`/`IDEA_ID`/`RESEARCH_FILE_ID` args and mocked tool calls, it skips the interactive breakpoints, calls `thesis_update_section` per section (not `thesis_create` when a shell already exists), registers sources or records data gaps, and appends exactly ONE decisions-log entry stamped with the idea provenance. A companion test asserts that WITHOUT `MODE=autonomous` the interactive breakpoints are preserved (no behavior regression on the user-facing path).

### Existing lower-layer regression tests

Keep relying on existing tests for the lower layers:

- `risk_module/tests/mcp_tools/test_research_start_idea.py`
- `risk_module/tests/routes/test_agent_api_idea.py`
- `AI-excel-addin/tests/api/research/test_start_research_from_idea.py`
- `AI-excel-addin/tests/integration/test_investment_schema_spine_e2e.py`

F128 should add orchestration tests, not duplicate all start-research tests.

### Live smoke

Add a live-gated smoke, disabled by default:

```bash
RUN_F128_LIVE=1 python scripts/run_idea_to_thesis.py --idea-file fixtures/ideas/f128_smoke_msft.json --profile analyst
```

The smoke passes only if:

- The agent calls `start_research` with the idea payload.
- The run uses the returned `research_file_id`.
- `thesis_read` after the run shows matching `from_idea.idea_id`.
- `thesis.statement` is non-empty or the run records `INSUFFICIENT_DATA`.
- The Decisions Log contains the bridge entry.
- The run artifact contains enough IDs for replay/debug.

## Acceptance Criteria

F128 is complete when:

- `idea-to-thesis` exists as a producer skill.
- A deterministic wrapper can launch it from one `InvestmentIdea`.
- The bridge reuses `start_research(idea=...)` rather than creating a separate ingress path.
- The bridge fills or safely updates the bootstrapped Thesis shell for one `research_file_id`.
- The bridge appends a canonical Decisions Log entry.
- Multi-user identity flows through existing runtime/MCP mechanisms.
- Default tests cover prompt/task generation, skill contract, wrapper dry run, and mocked result artifacts.
- A live-gated smoke proves one real autonomous run can complete or fail with a typed insufficient-data verdict.

## Non-Goals

- Do not create another idea schema.
- Do not create another Thesis persistence API.
- Do not write directly to SQLite.
- Do not use ticker-only lookup after `start_research` returns `research_file_id`.
- Do not re-compose FR/CF/IR/TA as sub-agents (the R2 approach, rejected after Codex R2 — see Confirmed Design Decisions); drive `thesis-consultation` instead.
- Do not duplicate thesis-consultation's thesis-writing discipline in a standalone writer; reuse it via `invoke_skill`.
- Do not change thesis-consultation's interactive (non-autonomous) behavior; the autonomous mode is purely additive and the interactive path stays intact.
- Do not enable unattended scheduled/headless writes before F134 enforcement covers this workflow.

## Idempotency Predicate

Re-running the same `idea_id` reuses the same `research_file_id` (existing `start_research_from_idea` idempotency by `idea_id` and by `(ticker, label)`). Whether to append a NEW decisions-log entry is decided by an objective predicate, not vibe:

- **Append** a new entry iff the run applied at least one new/changed op (any `apply_patch_ops` / `thesis_update_section` that changed Thesis state, measured by op-id/section diff against the current Thesis) OR produced a new typed verdict (e.g., a fresh `INSUFFICIENT_DATA` after a prior `FACTORS_IDENTIFIED`).
- **No-op** (do NOT append) iff every producer returned a verdict already reflected in the Thesis and zero ops changed state. The run summary records `reused_existing=true, decisions_log_appended=false`.

Each appended entry carries a unique `run_id` so re-runs remain distinguishable in the audit trail.

## Codex Review History

**R1 (2026-05-26): GATE FAIL.** Five [P1] + three [P2] findings, all resolved in R2:

- [P1] `scope: idea` won't load (enum is ticker/portfolio/industry) → **resolved**: use `scope: ticker` (Confirmed Design Decisions).
- [P1] `mcp_servers` as comma string invalid → **artifact of the review prompt** (the embedded plan was flattened to one line), not the real plan; the actual frontmatter was always a YAML list. R2 makes the list form explicit and right-sizes it (dropped `idea-workbench-mcp`).
- [P1] Run sequencing applied all four producers before any writes, breaking read-dependencies → **resolved**: §3 interleaves apply-ops between producers with a Thesis re-read.
- [P1] "Compose existing skills" hand-waved → **resolved**: §4 specifies the sub-agent dispatch + ops-extraction + apply contract; all four producers are propose-only and the orchestrator owns application.
- [P1] InvestmentIdea required-field omission + missing fixture → **resolved**: Executive Summary lists required fields; Test Plan creates `fixtures/ideas/f128_smoke_msft.json` with all required fields.
- [P2] Budget under-specified for sub-agent accumulation → **resolved**: `max_budget_usd: 16.0` covers accumulated sub-agent cost; `max_turns: 28` is orchestrator-only.
- [P2] Idempotency predicate ambiguous → **resolved**: see Idempotency Predicate above.
- [P2] F134 boundary not enforceable → **resolved**: §6 wrapper `--mode` hard-refuses `live-headless` without the policy grant.

Codex confirmed no-issue: `patch_ops_applied` as structured op-preview dicts matches `DecisionsLogEntry.patch_ops_applied: list[dict[str, Any]]` (`schema/thesis.py:291`).

**R2 (2026-05-26): GATE FAIL.** R2 cleared R1 (Codex verified: `scope: ticker`, YAML-list `mcp_servers`, correct server homes, idea required fields, budget/turns, F134 boundary), but found the sub-agent re-compose approach fights the runtime:

- [P1] sub-agent return value carries only streamed response text (`runner.py:929`); producers persist deliverables via `memory_write` and forbid echoing `ops:` — so a thin orchestrator cannot parse the ops.
- [P1] `thesis-articulation` needs a full diligence stack (BQA / comparative / scenarios / valuation / consensus / catalysts / triggers — `thesis-articulation.md:78,95,252`); FR+CF+IR don't supply it, forcing `THESIS_INSUFFICIENT`.
- [P1] `critical-factors` emits overlapping `typed_outputs` + `ops` with no defined merge semantics.
- [P2] FR/CF/IR/TA don't declare `mcp_servers` (R2's claim was wrong); CF's decision-log template contradicts the propose-only claim.

**R3 (2026-05-26): pivot, GATE FAIL.** Composition changed from "sub-agent re-compose of 4 propose-only producers" to "drive `thesis-consultation` in a new autonomous mode via `invoke_skill` text-injection" (see Confirmed Design Decisions + §4). Codex VALIDATED the pivot architecture: `invoke_skill` IS inline text-injection (not a sub-agent spawn — `tool_handlers.py:750`, `tool_catalog.py:608`); `thesis-consultation` is catalogable/invoke-able (`catalog:false` is the gate; it isn't set); the `peer-curation` autonomous precedent holds (`peer-curation.md:49`); all R2 [P1]s are moot. Remaining issues were implementation-detail, fixed in R4:

- [P1] `thesis_update_section` takes `section_key` + native `section_data`; scalar fields (`statement` etc.) are written via `section_key="thesis"`, NOT per-scalar keys (`routes.py:91,473`), and thesis-consultation's existing-shell refresh branch (`:261`) currently omits the scalars → R4 §3 + impl-order step 1 write scalars via `section_key="thesis"` on the update branch.
- [P1] idea-to-thesis under-declared servers: thesis-consultation calls `idea-workbench-mcp` (`search_findings`/`get_ticker_signals`/`search_screen_hits`) + `portfolio-mcp.get_price_target` (`thesis-consultation.md:144,7`) → R4 frontmatter declares the full superset.
- [P2] `section_data` (native dict/list), not `value=`/JSON string (`routes.py:1702`) → R4 §3 specifies `section_data`.

**R4 (2026-05-26): GATE FAIL.** Codex confirmed R3 fixes #1 (scalars via `section_key="thesis"`) and #3 (`section_data` native dict) correct. One remaining [P1]: `mcp_tools` is a restrictive PROMOTION ALLOWLIST, not additive docs (`entry.py:545`, `runner.py:402`, `tool_catalog.py:927`; `test_run_agent.py:2329`) — R4 declared only `get_price_target` under portfolio-mcp, which would EXCLUDE the thesis write tools the run needs. → R5 enumerates the complete `mcp_tools` set per server.

**R5 (2026-05-26): completes the `mcp_tools` promotion enumeration; needs Codex re-review.**

## Suggested Implementation Order

1. Add a `MODE=autonomous` recognition rule to `thesis-consultation.md` (peer-curation pattern): skip interactive breakpoints, accept `CALLER` / `IDEA_ID` / `RESEARCH_FILE_ID`, stamp idea provenance into its Decisions Log entry, and write the empty scalar fields (`statement`/`direction`/`strategy`/`conviction`/`timeframe`) on the existing-shell update branch via `thesis_update_section(section_key="thesis", section_data={...})` (its current refresh branch omits them). Keep the interactive path unchanged.
2. Add the autonomous-mode + interactive-path-preserved tests for thesis-consultation.
3. Add `idea-to-thesis.md` (thin ingress skill: validate idea → `start_research(idea=...)` → invoke thesis-consultation autonomous → verify one provenance-stamped decisions-log entry → run summary).
4. Add skill validation tests.
5. Add `scripts/run_idea_to_thesis.py` with validation, `--mode {dry-run|live-dev|live-headless}`, and dry-run artifact output.
6. Add mocked wrapper tests + the fixture `fixtures/ideas/f128_smoke_msft.json` (all required idea fields).
7. Add the live-gated smoke script path.
8. Run one local dry run with the fixture idea.
9. Run one live dev-mode smoke with an operator-approved idea.
10. Update F128 TODO status with live evidence.
11. After F134 lands (or the F129 PR-A scoped grant), classify the bridge for autonomous write enforcement and enable scheduled/headless use only if still desired.
