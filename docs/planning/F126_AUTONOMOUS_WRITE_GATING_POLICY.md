# F126 — Autonomous Write Gating Policy

**Status:** Completed 2026-05-23. Policy decision only; enforcement is F134.
**Closes:** Research Artifact Layers D10 policy half; supports R7 and Success Criterion 4.
**Depends on:** F124 completed typed monitoring/ownership reads; F125 audit backbone still required before scheduled autonomous writes ship.
**Enforcement owner:** F134.

---

## 1. Problem

The research loop now has enough write surfaces that "the agent can write Thesis state" is too broad. Some writes are reversible state updates, some trigger expensive or user-visible downstream actions, and some can move real money.

The old implicit rule was: Thesis writes are reversible because a HandoffArtifact can be regenerated. That is true only until a downstream action acts on the changed state. Once a model build, portfolio recommendation, order preview, or trade execution has happened, the blast radius is larger than the Thesis row.

F126 defines the policy. F134 will enforce it in orchestrators, skill boundaries, and tests.

---

## 2. Policy

### 2.1 Thesis-only writes

**Rule:** autonomous allowed, after the evidence/audit gates pass.

Examples:
- `apply_patch_ops` for sourced Thesis claims, risks, catalysts, assumptions, monitoring, ownership, peers, and data gaps.
- `thesis_update_section`, `manage_qualitative_factor`, `thesis_upsert_link`, and `thesis_append_decisions_log` when they only mutate Thesis state.
- Zero-patch `decisions_log` entries that record `INSUFFICIENT_DATA`, no-op verdicts, or abstentions.

Required gates:
- F125-era positive claims must link `claim -> source_refs -> SourceRecord.excerpts -> Excerpt.claim_ids`.
- Same-target positive claim plus `data_gap` is rejected.
- Update ops that materially change meaning need fresh evidence or a carry-forward rationale.
- Every autonomous run leaves a decision-log trace, including no-op runs.

### 2.2 Build-affecting writes

**Rule:** autonomous allowed with automatic build follow-through and audit trace.

Examples:
- Writes that change model inputs or assumptions enough that the current workbook/model output is stale.
- `build_model` after a finalized handoff.
- Future model rebuilds triggered by `update_thesis_quantitative`, model links, valuation assumptions, or other model-bound Thesis fields.

Required gates:
- The triggering write must satisfy the Thesis-only evidence gates.
- The orchestrator must either run the build or record why the build did not run.
- `decisions_log` must include a `build-triggered` entry with the triggering op ids, build attempt id or failure reason, and resulting model/handoff reference when available.
- Build outputs must remain projections back onto Thesis, not the only durable read path.

Rationale: a stale model after an autonomous build-affecting write is more dangerous than an automatically rebuilt model with a clear audit entry. The side effect is material but reversible by rebuilding from prior Thesis/Handoff versions.

### 2.3 Portfolio-affecting writes and executions

**Rule:** always human-gated. No autonomous or scheduled path may call execution tools or directly change portfolio configuration without an explicit human gate for that action.

Always-gated tools include:
- `execute_trade`
- `execute_option_trade`
- `execute_basket_trade`
- `execute_futures_roll`
- `cancel_order`
- Any future tool that submits, cancels, modifies, or routes broker orders.

Portfolio configuration writes are also portfolio-affecting unless explicitly scoped as read-only diagnostics:
- `set_risk_profile`
- `set_target_allocation`
- Account activation/deactivation or brokerage-routing changes
- Any tool that changes user-account portfolio state outside Thesis

Allowed before the gate:
- `generate_rebalance_trades`
- `preview_trade`
- `preview_option_trade`
- `preview_basket_trade`
- `preview_futures_roll`
- Read-only risk, position, quote, order, performance, and exit-signal tools

Preview tools may still trigger notional review thresholds. Preview approval does not authorize execution.

### 2.4 Position lifecycle writeback

`Thesis.position_metadata` writeback is allowed only after a confirmed external event:
- successful user-approved execution; or
- explicit user confirmation of manual initiation.

After that event, `update_position_size` and `set_date_initiated` are observed-state writes and should be applied immediately using the resolved `research_file_id`. They must not infer the target Thesis from ticker-global memory.

---

## 3. Existing Precedents

The policy matches existing behavior rather than inventing a new safety model:

- `position-initiation` already says to call `preview_trade`, then call `execute_trade(preview_id=...)` only after the user confirms, and only then write `Thesis.position_metadata`.
- Analyst profile configuration exposes preview tools while excluding execution tools from normal autonomous paths.
- The tool dispatcher has approval plumbing for gated tools, and execution tools are configured as never-cache approvals.
- Existing recommend-mode prompts tell sub-agents to stop before execution and return recommendations to the parent.

F134 should turn these precedents into a single enforced contract instead of relying on skill prose.

---

## 4. F134 Enforcement Requirements

F134 should implement this policy with three explicit surfaces:

1. **Classification registry.** Every tool/op the autonomous loop can invoke is classified as `thesis_only`, `build_affecting`, `portfolio_affecting`, or `operational`. Unknown write tools default to blocked until classified.
2. **Orchestrator gate.** Autonomous/scheduled runs may execute `thesis_only`; may execute `build_affecting` only through the build-follow-through path; and must block `portfolio_affecting` unless the call context carries a one-action human gate token.
3. **Skill boundary tests.** Skills that recommend trades may preview but cannot execute. Build-affecting writes must emit `build-triggered` audit entries. Portfolio-affecting execution without a human gate must fail before dispatch.

Minimum tests:
- Autonomous `position-initiation` or monitoring agent cannot call `execute_trade`.
- A parent interactive run can execute only after explicit approval for that specific execution call.
- Approval for preview does not authorize execution.
- `execute_trade` approvals are never cached across calls.
- Build-affecting Thesis write triggers a build attempt or a recorded build failure.
- Unclassified write tools are blocked in autonomous mode.

---

## 5. Decision

Use the three-tier policy:

1. **Thesis-only:** autonomous OK after audit validation.
2. **Build-affecting:** autonomous OK only with build follow-through and `build-triggered` audit.
3. **Portfolio-affecting:** human gate required per action, always.

This keeps the autonomous loop useful while keeping irreversible or externally stateful actions under human control.
