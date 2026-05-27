# F128 Idea-To-Thesis Autonomous Bridge Plan

**Status:** DRAFT R1 - needs Codex review
**Date:** 2026-05-26
**Owner:** Thesis & Research Artifact autonomous-loop workstream
**Primary implementation repo:** `/Users/henrychien/Documents/Jupyter/AI-excel-addin`
**Tracking repo:** `/Users/henrychien/Documents/Jupyter/risk_module`

## Executive Summary

F128 is an orchestration gap, not a missing schema or missing `start_research` tool.

The existing system already has the typed ingress foundation:

- `InvestmentIdea` is a typed schema with `idea_id`, `source_ref`, `thesis`, `direction`, `strategy`, `conviction`, `timeframe`, `label`, and optional `suggested_process_template_id`.
- `start_research(..., idea=...)` is exposed through risk_module MCP.
- AI-excel-addin `start_research_from_idea(...)` persists the idea, creates/reuses a research file, writes idea provenance, creates/reuses the draft handoff, and bootstraps an empty typed Thesis shell with `from_idea`.
- Tool-level tests already prove the idea payload is forwarded and that response fields such as `idea_seeded` and `thesis_bootstrapped` are surfaced.

What is missing is one autonomous workflow that consumes a single idea and completes the loop:

```text
InvestmentIdea
  -> start_research(idea=...)
  -> read bootstrapped Thesis shell
  -> run bounded research producer skills
  -> apply auditable Thesis writes
  -> append a Decisions Log entry
  -> leave a replayable run artifact
```

The recommended fix is a thin `idea-to-thesis` producer skill plus a deterministic run wrapper. It should compose existing skills and tools; it should not create another thesis model, another ingestion contract, or another free-form memory write path.

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
description: Convert one typed InvestmentIdea into a grounded typed Thesis by registering/reusing the research workspace, running the minimal research stack, applying Thesis writes, and appending a Decisions Log entry.
version: 1.0
scope: idea
state_class: producer
agent_callable: true
resumable: true
max_turns: 28
max_budget_usd: 8.0
mcp_servers:
  - portfolio-mcp
  - research-corpus-mcp
  - idea-workbench-mcp
---
```

The skill input should be exactly one typed idea payload or one resolvable idea reference. Do not accept an open-ended ticker-only request for this skill; ticker-only initiation belongs to existing ticker-scoped skills.

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
6. Run the bounded research stack:
   - `fundamental-research`
   - `critical-factors`
   - `identifying-risk`
   - `thesis-articulation`
7. Apply allowed typed writes to the same `research_file_id`.
8. Append exactly one `thesis_append_decisions_log(...)` entry for the bridge run.
9. Read the Thesis again and emit a final run summary.

The bridge should treat the bootstrapped Thesis shell as the canonical target. If `thesis_read` shows that no Thesis exists, it may call `thesis_create(research_file_id=..., initial_fields=...)`; that should be an exception path, not the normal path.

### 4. Keep atomic skills atomic

The bridge should orchestrate existing skills, not merge their bodies into a huge prompt.

Recommended split:

- `fundamental-research` owns source registration and `business_overview`.
- `critical-factors` owns materiality, differentiated-view candidates, assumptions, catalysts, and watch items.
- `identifying-risk` owns risk register and invalidation triggers.
- `thesis-articulation` owns the final statement and pitchable synthesis.
- `idea-to-thesis` owns sequencing, target identity, write application, final audit, and decision log.

This keeps each producer reusable outside the idea bridge and avoids turning F128 into an unmaintainable mega-skill.

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

The bridge writes Thesis state. In interactive/dev use it can run with existing approval gates. In headless autonomous mode it should depend on F134 enforcement for final autonomous write policy.

Practical sequencing:

- Implement the skill and wrapper first.
- Add deterministic tests that do not require live LLM.
- Allow live dev runs with explicit operator invocation.
- Gate scheduled/headless use behind F134 policy enforcement.

F128 should not weaken F134. It should become one of the concrete workflows F134 classifies and tests.

## Persistence Contract

At completion, a successful F128 run should leave:

- A research file with `idea_id`, `idea_provenance`, and `source_ref`.
- A typed Thesis with `from_idea.idea_id` matching the input.
- A non-empty `thesis.statement`.
- Direction, strategy, conviction, and timeframe populated from the idea or the final articulation.
- At least one registered source or a clear data-gap verdict explaining why sourced claims could not be written.
- A business overview when `fundamental-research` completes.
- Materiality / critical-factor output when `critical-factors` completes.
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

- Valid idea JSON is accepted.
- Invalid idea JSON fails before launching an agent.
- The generated task prompt includes exactly one idea payload and requires same-`research_file_id` writes.
- Dry run produces a plan artifact without calling the live agent.
- User identity is sourced from the runtime/config, not from hard-coded constants.

### Skill validation tests

Extend skill validation to prove:

- `idea-to-thesis` exists and is `agent_callable`.
- `scope` is `idea`.
- `state_class` is `producer`.
- Required MCP servers are declared.
- The skill text names the required tools:
  - `start_research`
  - `thesis_read`
  - `thesis_update_section`
  - `apply_patch_ops`
  - `thesis_append_decisions_log`
- The skill text forbids ticker-only operation.

### Mocked orchestration test

Add a non-LLM test for the deterministic wrapper with mocked autonomous output:

- Input idea is validated.
- Mock run returns `research_file_id`, write summary, and decision-log entry id.
- Wrapper writes a run artifact.
- The artifact is schema-valid and includes the expected identity fields.

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
- Do not collapse the atomic producer skills into one large prompt.
- Do not enable unattended scheduled/headless writes before F134 enforcement covers this workflow.

## Suggested Implementation Order

1. Add `idea-to-thesis.md` as an orchestration skill.
2. Add skill validation tests.
3. Add `scripts/run_idea_to_thesis.py` with validation and dry-run artifact output.
4. Add mocked wrapper tests.
5. Add the live-gated smoke script path.
6. Run one local dry run with a fixture idea.
7. Run one live dev-mode smoke with an operator-approved idea.
8. Update F128 TODO status with live evidence.
9. After F134 lands, classify the bridge for autonomous write enforcement and enable scheduled/headless use only if still desired.
