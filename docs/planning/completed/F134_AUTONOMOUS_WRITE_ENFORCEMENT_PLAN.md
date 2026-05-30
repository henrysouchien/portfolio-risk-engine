> **✅ CLOSED — Superseded/absorbed by shipped F2j tool-policy work and F131 research_producer enablement; moved during 2026-05-28 docs cleanup.**

# F134 - Autonomous Write Enforcement Plan

> **⚠️ LARGELY SUPERSEDED 2026-05-26 — do not implement as written.** The F2j tool-policy refactor (`AI-excel-addin/docs/design/agent-tool-policy-architecture.md`, Round 8 PASS; PR1+PR2 shipped `66c8395a`) replaced this design. F2j's 6-class taxonomy + profile composition subsumes the classification here, and its `irreversible`-forbidden-in-autonomous config assertion is a stronger version of "portfolio_affecting always blocked." Critically, **F2j autonomous gating is STATIC profile-class exclusion at startup, NOT the runtime "critical gate interceptor" this plan proposes** (arch §4.1: no mid-stream approval). Two pieces of this plan survive F2j: **(1)** the **build-follow-through hook** (§3.3) — orphaned, no current consumer; **(2)** a **scoped autonomous `state_write`/`external_write` grant** for specific skills — F2j only unblocked `artifact_write`, so this capability is unbuilt; it is re-homed as **F129 PR-A** (`F129_MONITORING_EXIT_CADENCE_AGENT_PLAN.md`). The §1–§6 design below is retained for historical context + the surviving-pieces rationale; the runtime-gate architecture (§3.2) does not match the shipped F2j runtime. See the F134 row in `docs/TODO.md` for the reconciliation.

**Status:** ~~Proposed 2026-05-23. Needs review before implementation.~~ **LARGELY SUPERSEDED BY F2j 2026-05-26** (see banner).
**Depends on:** F126 policy decision; F125 audit backbone for strict evidence gates.
**Closes:** Research Artifact Layers D10 enforcement half; R7; Success Criterion 4.
**Primary code repo:** `AI-excel-addin/`.

---

## 1. Issue

F126 locked the policy, but enforcement is still fragmented:

- `AI-excel-addin/api/agent/shared/server_policies.py` classifies MCP tools only as `read`, `write`, or `predicate`.
- `requires_approval()` turns all known writes into approval-required calls, without distinguishing Thesis-only writes, build-affecting writes, or portfolio-affecting writes.
- Autonomous dispatch uses `should_avoid_permission_prompts=True`, so approval-required calls are headless-denied unless a profile or dev-mode allowlist pokes a hole.
- `get_autonomous_artifact_tools()` is an ad hoc allowlist for model/artifact tools, not a blast-radius policy.
- Portfolio execution tools have good partial coverage: profile exclusions, approval plumbing, and `never_cache_approval` already exist.
- Build-affecting Thesis writes have no enforced follow-through. There is no runtime hook that says "this autonomous write changed model inputs; run `build_model` or record why the build did not run; append a `build-triggered` decision-log entry."

Root cause: the runtime has approval mechanics, but no single autonomous-write contract keyed on F126's blast-radius categories.

---

## 2. Target Contract

F134 should enforce four explicit classifications for every write/predicate tool an autonomous run can reach:

| Class | Autonomous behavior | Examples |
|---|---|---|
| `thesis_only` | Allowed after F125 evidence/audit gates. | `apply_patch_ops` with non-model-bound ops, `thesis_update_section`, `manage_qualitative_factor`, `thesis_upsert_link`, `thesis_append_decisions_log` |
| `build_affecting` | Allowed only through build follow-through: trigger build or record failure, then append `build-triggered` audit. | model-bound Thesis patch ops, `build_model`, model-engine build/modification tools |
| `portfolio_affecting` | Always blocked in autonomous/headless runs; interactive parent runs still require per-action human approval. | `execute_trade`, `execute_option_trade`, `execute_basket_trade`, `execute_futures_roll`, `cancel_order`, risk profile/allocation/account-routing writes |
| `operational` | Allowed or blocked by explicit registry entry; unknown operational writes block by default. | notification/job/admin tools where an autonomous workflow intentionally needs them |

Unknown write/predicate tools must fail closed in autonomous contexts.

---

## 3. Proposed Architecture

### 3.1 Policy Registry

Add `AI-excel-addin/api/agent/shared/autonomous_write_policy.py`:

- `AutonomousWriteClass = thesis_only | build_affecting | portfolio_affecting | operational | unknown`
- `AutonomousWriteDecision = allow | allow_with_build_followthrough | deny`
- `classify_autonomous_tool(tool_name, tool_input) -> AutonomousWriteClass`
- `classify_handoff_patch_ops(tool_input) -> AutonomousWriteClass`
- Registry completeness test over `get_all_write_tools() | get_all_predicate_tools()`.

`apply_patch_ops` needs input-aware classification:

- model-bound ops such as `update_thesis_quantitative`, valuation assumptions, model links, and future model-input fields are `build_affecting`;
- research-state ops such as risks, catalysts, monitoring, ownership, peers, data gaps, and decisions-log entries are `thesis_only`;
- mixed batches classify to the highest blast radius.

Portfolio-affecting tools should include execution/cancel tools plus portfolio configuration writes such as `set_risk_profile`, `set_target_allocation`, account activation/deactivation, brokerage-routing mutation, and direct portfolio/basket mutation.

### 3.2 Critical Autonomous Gate

Install a critical interceptor in autonomous/headless dispatch paths:

- `agent.autonomous.runner.create_session_objects()`
- sub-agent dispatchers created by `agent.shared.tool_handlers.make_run_agent_handler()`
- resume/background dispatchers that inherit autonomous/headless mode

Gate behavior:

- `portfolio_affecting`: deny before dispatch with `code="autonomous_portfolio_gate_required"`.
- `unknown`: deny before dispatch with `code="autonomous_write_unclassified"`.
- `thesis_only`: allow, relying on F125 evidence/audit validators at write time.
- `build_affecting`: allow only when the build-follow-through hook is installed; otherwise deny with `code="autonomous_build_followthrough_missing"`.

Interactive top-level runs keep existing approval behavior. `get_never_cache_tools()` remains the per-action guard for execution tools, and tests should prove persistent preview approval never authorizes execution.

### 3.3 Build Follow-Through Hook

Add a post-tool hook around successful autonomous tool calls:

1. Inspect the completed call with `classify_autonomous_tool(tool_name, tool_input)`.
2. If the call is not `build_affecting`, do nothing.
3. If it is a direct `build_model` / model-engine build call, record that the build-affecting side effect already happened.
4. If it is a Thesis write that changed model-bound inputs:
   - resolve `research_file_id` / handoff reference from the original input and result;
   - call `build_model` through the same user-scoped MCP client context;
   - append `thesis_append_decisions_log` with a `build-triggered` decision entry containing triggering tool/op ids, build attempt id or failure reason, and resulting model/handoff reference when available.

If the build fails, the original write remains valid, but the hook must append a failure audit entry. If the hook cannot resolve the target Thesis, it must block future autonomous build-affecting writes until the tool contract is made explicit.

### 3.4 Multi-User Requirements

- Never infer target Thesis from ticker-global memory.
- Reuse the same user/session-scoped MCP client and metadata injection path already used by the dispatcher.
- Human-gate tokens, if added later, must be scoped to one user, one session, one tool call, and one execution action. F134 does not need to introduce reusable portfolio gates.

---

## 4. Implementation Steps

1. Add the policy registry and classify all current known write/predicate tools.
2. Add registry drift tests so new write/predicate tools cannot ship unclassified.
3. Add the critical autonomous gate interceptor and install it in autonomous/sub-agent dispatchers.
4. Add tests proving autonomous/headless runs deny `execute_trade` and portfolio configuration writes even if the tool is visible.
5. Add the build follow-through hook for build-affecting Thesis writes.
6. Add tests for successful build follow-through and build-failure audit.
7. Update relevant skill docs (`position-initiation`, monitoring/reassessment producers) to point to the enforced contract rather than prose-only safety rules.
8. Update `docs/TODO.md`, `RESEARCH_ARTIFACT_LAYERS.md`, and `THESIS_WRITE_SURFACE_COVERAGE.md` only after tests pass.

---

## 5. Minimum Test Matrix

- `classify_autonomous_tool("execute_trade", ...) == portfolio_affecting`.
- `classify_autonomous_tool("preview_trade", ...)` is not a write and remains allowed pre-gate.
- Every `get_all_write_tools() | get_all_predicate_tools()` member has an autonomous classification.
- Autonomous dispatcher blocks `execute_trade` before dispatch.
- Autonomous dispatcher blocks `set_risk_profile` / `set_target_allocation` before dispatch.
- Interactive dispatcher still requests approval for `execute_trade`.
- `execute_trade` approvals remain never-cache, even if the user requests persistent approval.
- Preview approval does not authorize later execution.
- Autonomous `apply_patch_ops` with model-bound ops triggers `build_model` and appends a `build-triggered` decision-log entry.
- Build failure after a model-bound Thesis write appends a `build-triggered` failure entry.
- Unclassified synthetic write tools are blocked in autonomous mode.

---

## 6. Proposed First Slice

Implement the registry and critical gate first, with portfolio-affecting and unknown-write denial tests. That closes the irreversible-action risk immediately.

Then implement build follow-through as the second slice, because it needs more exact tool-result plumbing and should not be mixed with the gate safety change.
