# Vals Finance Agent Config D - Full Skill Substrate Plan

**Status:** Draft design
**Date:** 2026-05-07
**Owner repos:** `risk_module` benchmark harness, `AI-excel-addin` agent skill runtime

## Goal

Config D should answer a different question from Config C:

- **Config C:** How does Hank perform through the dev gateway with the normal tool surface and benchmark context?
- **Config D:** How does Hank perform when the real AI-excel-addin analyst skill substrate is available, including the in-progress SIA methodology and skill catalog?

Config D must not become a benchmark-backfilled skill bundle. Benchmark misses are validation probes, not the source of truth for which skills exist. The source of truth is the product skill roadmap in `AI-excel-addin`: SIA wiki -> methodology units -> skills -> typed artifacts.

## Non-goals

- Do not create one-off skills named after VAL question failures.
- Do not hard-code benchmark checklists into the Config D prompt.
- Do not require every benchmark question to run a named skill.
- Do not mutate thesis/model state as a side effect of answering benchmark questions unless explicitly isolated.
- Do not treat local-judge Config D as a publishable Vals-hosted result.

## Current State

### risk_module benchmark harness

- Config C invokes `agent_gateway_cli chat --raw --auto-approve "*"`.
- Config C now adds benchmark as-of-date and exactness policy.
- Config C parses raw SSE events for terminal status, tool usage, and semantic tool-result errors.
- The CLI supports `--skill` and `--mode`, but `--skill` only forwards `context.skill` to `/api/chat`.

### AI-excel-addin skill substrate

- The interactive analyst system prompt already injects a compact `Analyst Skills` catalog from canonical `notes/skills/*.md`.
- The analyst runtime exposes `memory_read`, `memory_recall`, `load_tools`, and `run_agent(agent="<name>", task="...")`.
- Named agent skills are loaded from skill frontmatter where `agent_callable: true`.
- The SIA knowledge layer is in progress: wiki content is compiled, methodology units are being distilled, and atomic skills are being built around those units.
- Some benchmark-relevant skills already exist as real product skills, for example:
  - `filing-source-selection`
  - `guidance-extraction`
  - `filing-extractor`
  - `critical-factors`
  - `earnings-scenarios`
  - `business-quality-assessment`
  - `financial-red-flags`
  - `quantifying-risk`

## Design Principle

Config D should expose the **same capability substrate a user-facing analyst would have**, then measure:

1. Whether the agent recognizes that a skill or methodology applies.
2. Whether it loads the right skill or delegates to the right named agent.
3. Whether it can produce a direct benchmark answer after skill-assisted research.
4. Which misses reveal real product skill gaps versus ordinary benchmark exactness issues.

The benchmark should be a regression suite for skill discoverability and workflow adequacy, not the authoring blueprint for the skills themselves.

## Proposed Config D Shape

### 1. Add a Config D harness wrapper

Add `config_d_hank_skills.py` in `evals/vals-finance-agent/configs/`.

Config D should reuse the Config C dev-CLI execution path with these differences:

- output directory: `config_d`
- model label: `hank_vals_run_config_d`
- context mode: a new benchmark-safe mode, e.g. `mode="vals_benchmark"` or `mode="benchmark"`
- optional trace field: `skill_catalog_available=true`
- optional trace fields: `skill_reads`, `run_agent_usage`, `methodology_reads`

Do not use CLI `--skill` as the top-level mechanism. It is not currently wired to replace the interactive system prompt with a skill prompt. Config D should use the interactive analyst surface so the agent can choose among the full catalog.

### 2. Add a benchmark mode to the interactive system prompt

AI-excel-addin should add a context mode recognized by `api/agent/shared/system_prompt.py`.

Recommended name: `mode="benchmark"`.

This mode should add a short section with these rules:

- You are answering an evaluation question in one turn.
- Do not ask the user for clarification; make defensible assumptions and state them.
- Scan the skill catalog before tool calls.
- If a skill clearly matches, `memory_read("skills/<skill>.md")` and follow the relevant workflow.
- If a named agent workflow is useful and time permits, use `run_agent(agent="<name>", task="<bounded task>")`.
- If no skill matches, write a brief plan from first principles, use tools directly, and note the missing skill/workflow in the final answer only if relevant.
- Return a direct answer, not a long research memo.

This is a benchmark-mode adaptation of the existing analyst behavior, not a new benchmark skill.

### 3. Preserve Config C benchmark context

Config D should inherit the Config C benchmark context:

- as-of date: April 07, 2025 by default
- no post-as-of filings, transcripts, market data, or events
- exact source values and exact arithmetic before rounded explanation
- formula shown when arithmetic is material
- approximation markers avoided in final numeric answers unless the source is approximate

This context can live in the risk_module harness message, as Config C does today. AI-excel-addin should not hard-code the Vals date globally.

### 4. Add a meta-planning layer, but keep it product-general

There are two viable shapes.

**Option A: Prompt-level meta-planner first.**

Start with benchmark mode instructions only. The main agent does the routing:

1. classify the task;
2. decide whether to load a skill;
3. decide whether to call `run_agent`;
4. answer.

This is simplest and likely enough for the first Config D smoke.

**Option B: Add an `analysis-planner` skill later.**

If Config D traces show poor skill discovery, add a real product skill:

```yaml
name: analysis-planner
description: Plan an investment-analysis approach, choose relevant skills/methodology/tools, and identify gaps when no exact skill exists.
agent_callable: true
```

The output should be a small plan:

- task class
- required evidence families
- applicable skills
- applicable methodology units
- first tool calls
- fallback plan if no skill matches
- gap classification if the skill catalog lacks coverage

This should be useful outside VAL, for normal analyst requests. It should not mention VAL question IDs or benchmark rubrics.

Recommendation: implement Option A first. Add Option B only if traces show skill selection is the bottleneck.

## Instrumentation

Config D is valuable only if traces distinguish skill behavior from raw tool behavior.

Extend Config C trace parsing where possible:

- `tool_usage`
- `tool_error_usage`
- `memory_read` count and paths, especially `skills/*` and `methodology/*`
- `run_agent` count and named agents used
- `load_tools` server/pack usage
- terminal status and semantic tool errors

Derived analysis fields can be added by the aggregator:

- `skill_used`: true if `memory_read("skills/...")` or `run_agent(agent=...)` occurred
- `skills_loaded`: sorted skill names
- `methodology_units_loaded`: sorted paths
- `named_agents_called`: sorted agent names
- `skill_gap_candidate`: true if answer failed and no skill/methodology was loaded

Do not require these fields to score the run. They are diagnostic.

## Evaluation Plan

### Phase 0 - Design validation

- Confirm CLI `--mode benchmark` can flow into `/api/chat` context.
- Confirm the gateway system prompt includes the normal skill catalog in CLI channel.
- Confirm `run_agent(agent=...)` is available in CLI channel.
- Confirm benchmark mode does not ask for user approval before planning.

### Phase 1 - Harness smoke

Run a tiny targeted set with dry judge:

- `q006` - guidance exactness and implied arithmetic presentation
- `q021` - concentration-risk source selection
- `q025` - regulatory risk source selection
- `q036` - M&A/deal-term primary-source retrieval
- `q015` - exact arithmetic plus semantic tool-error trace sanity

Expected first-smoke outcome is not necessarily pass/fail. The real questions:

- Did it load a relevant skill or named agent?
- Did skill loading improve source coverage?
- Did it still answer directly?
- Did trace fields make the reason legible?

### Phase 2 - Full Config D local run

Run full public-50 with local judge after Phase 1 trace quality is acceptable.

Compare against:

- Config B raw Opus
- Config A curated wrapper
- Config C dev gateway without deliberate skill mode

Report:

- score
- run health
- skill usage rate by question type
- pass rate when skills loaded vs not loaded
- failed rows where no skill was loaded
- failed rows where a skill loaded but the workflow was insufficient

### Phase 3 - Gap review

Use the run to update the product skill roadmap:

- real missing methodology unit;
- real missing skill wrapper;
- existing skill not discoverable;
- existing skill too narrow;
- tool/parser/data gap;
- benchmark exactness policy issue.

This gap review belongs in AI-excel-addin TODO/design docs when it affects skills, and Edgar_updater TODO/design docs when it affects SEC retrieval primitives.

## Open Architecture Questions

1. **Mode name:** `benchmark`, `eval`, or `vals_benchmark`.
   - Prefer `benchmark`: product-general.

2. **Top-level system prompt location:**
   - Keep Vals as-of-date in risk_module harness.
   - Keep skill routing behavior in AI-excel-addin benchmark mode.

3. **State isolation:**
   - Config D should not pollute durable analyst memory or skill output directories during benchmark runs.
   - Options:
     - pass a benchmark user/workspace id;
     - set a benchmark output namespace;
     - allow read-only memory plus ephemeral trace output only.
   - This needs a design decision before full runs.

4. **Sub-agent cost and latency:**
   - Named skills may be heavy and can write outputs.
   - Config D should start with parallelism 1 and may need a per-question budget.

5. **Whether to expose all skills or catalog-visible skills only:**
   - Use the real catalog as the user sees it.
   - Hidden/tutor/internal skills should remain hidden unless the product would expose them.

## Implementation Sketch

### risk_module

- Add `harness/hank_devcli_skills_model.py` or parameterize `hank_devcli_model.py`.
- Add `configs/config_d_hank_skills.py`.
- Update local runner choices and aggregation labels for `config_d`.
- Extend trace parsing for skill/methodology/run_agent events if raw SSE payloads expose them.
- Add tests for:
  - Config D builds CLI args with `--mode benchmark`.
  - Config D preserves benchmark as-of-date wrapping.
  - trace parser extracts `memory_read("skills/...")` and `run_agent(agent=...)` when present.

### AI-excel-addin

- Add benchmark mode section in `system_prompt.py`.
- Add tests that `context={"mode": "benchmark", "channel": "cli"}` injects benchmark-mode skill-routing guidance.
- Decide state isolation mechanism before a full run.
- Optionally add `analysis-planner.md` only after first Config D traces show routing failures.

## Success Criteria

Config D is successful if it produces a clean, diagnosable run where:

- full public-50 completes without run-step contamination;
- traces show when skills/methodology/named agents were used;
- benchmark improvements or failures can be attributed to real product workflow behavior;
- follow-up gaps map cleanly to the AI-excel-addin skill/methodology roadmap or upstream tooling repos;
- no benchmark-only skill/prompt backfill is introduced.
