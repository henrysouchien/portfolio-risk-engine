# Portfolio Workflow Skills — Allocation Review + Risk Review

## Context

`WORKFLOW_DESIGN.md` defines 7 portfolio workflows with 5-step sequences. Cross-cutting backend gaps are mostly closed (rebalance trades, batch comparison, audit trail). One small backend fix is needed (add `allocation_review` to the audit allowlist). The existing MCP tools are sufficient primitives — what's missing is the agent-side choreography that chains them into structured workflows.

In AI-excel-addin, agent skills are markdown files (`api/memory/workspace/memory/skills/*.md`) with YAML frontmatter + step-by-step instructions. The agent discovers skills from the catalog in its system prompt, reads the full file via `memory_read()` when matching a user request, then follows the workflow.

**Deliverable**: Two new skill files for the priority 1-2 workflows (Allocation Review and Risk Review), plus a backend fix to add `allocation_review` to the audit allowlist.

---

## Changes

### 1. Backend: Update audit allowlist (risk_module)

**File**: `mcp_tools/audit.py` — add `"allocation_review"` to `_ALLOWED_WORKFLOWS`.

Current allowlist (line 13): `{"hedging", "scenario_analysis", "strategy_design", "risk_review"}`

New allowlist: `{"hedging", "scenario_analysis", "strategy_design", "risk_review", "allocation_review"}`

This is required because both skills call `record_workflow_action(workflow_name=...)` and `get_action_history(workflow_filter=...)` with their respective workflow names. `risk_review` is already present; `allocation_review` is not. **This code change must be applied before the allocation-review skill can record audit actions.**

### 2. Skill: `allocation-review.md` (AI-excel-addin)

**File**: `api/memory/workspace/memory/skills/allocation-review.md`

```markdown
---
name: allocation-review
description: Portfolio allocation drift check — assess current vs target, generate rebalance plan, preview impact, and execute.
---

# Allocation Review

## When to Use
- The user asks to check portfolio drift, allocation alignment, or whether they need to rebalance.
- Periodic portfolio checkup (monthly, quarterly) to verify allocations are on target.
- After a market move, the user wants to know if drift has become material.

## When NOT to Use
- The user wants a quick positions snapshot with no target comparison (just call `get_positions`).
- The task is about risk analysis or compliance without allocation targets (use risk-review).
- The user is researching a specific stock (use position-initiation or stock-pitch).

## Workflow

1. Confirm scope and check targets.
- Confirm portfolio name if not obvious (default: CURRENT_PORTFOLIO).
- `get_target_allocation()`: check if targets are set.
- If no targets exist, ask the user to define them or offer to run `set_target_allocation()` first.

2. Run portfolio assessment (parallel tool calls).
- `get_risk_analysis(format="full")`: full response includes `asset_allocation` array with drift data (target_pct, drift_pct, drift_status, drift_severity per asset class). The agent format (`format="agent"`) does NOT include drift — use `format="full"` here.
- `get_positions(format="agent")`: top holdings, concentration, sector exposure.
- `get_action_history(workflow_filter="allocation_review")`: prior allocation review actions (context from past sessions).

3. Assess drift and present findings.
- Review drift data from the `asset_allocation` array in the risk analysis response. Each entry has: `category`, `percentage` (current %), `target_pct`, `drift_pct`, `drift_status`, `drift_severity`.
- Identify which asset classes have drifted most (sort by absolute `drift_pct`).
- Check for concentration violations or compliance breaches from `risk_limit_violations_summary` and `beta_exposure_checks_table` in the full response.
- Check for `stale_pending_actions` from prior reviews (from `get_action_history` flags).
- **Present drift summary to user**: current vs target by asset class, severity (on_target / overweight / underweight), top contributors to drift.
- If drift is within tolerance (all classes ±2%), report "on target" and stop unless user wants to dig deeper.

4. Generate rebalance plan (if drift is material).
- Convert target allocation to ticker-level target weights (decimal, not percent):
  - For each asset class, distribute target weight pro-rata across current holdings in that class.
  - Example: if equity target is 60% and current equity holdings are AAPL (40%) + MSFT (60%) of equity sleeve, then AAPL target = 0.24, MSFT target = 0.36.
  - If an asset class has no current holdings (empty sleeve), ask the user which tickers to use for that allocation.
- `preview_rebalance_trades(target_weights={"AAPL": 0.24, "MSFT": 0.36, ...}, format="agent")`: get sequenced BUY/SELL legs.
- `record_workflow_action(workflow_name="allocation_review", recommendation_type="rebalance", recommendation_text="Rebalance to target allocation: ...", source_tool="preview_rebalance_trades")`: record the recommendation.
- Present trade plan to user: sells first, then buys, estimated values, cash impact.

5. Preview impact.
- `run_whatif(target_weights={"AAPL": 0.24, "MSFT": 0.36, ...}, format="agent")`: before/after risk comparison. Note: `run_whatif` requires risk limits to be configured — if it returns an error about missing risk limits, skip the preview and inform the user they can set up limits via `set_risk_profile` to enable scenario previews.
- Compare: volatility change, concentration change (HHI), compliance status after rebalance.
- Present: "This rebalance would reduce vol from X% to Y%, resolve N concentration violations, etc."
- Ask user: proceed, modify, or skip?

6. Execute (only with explicit user approval).
- First update audit trail: `update_action_status(action_id, "accepted")` for the recommendation from step 4.
- `preview_rebalance_trades(target_weights={...}, preview=True, account_id="...")`: preview each leg with broker. Each leg returns a `preview_id`.
- For each approved leg: `execute_trade(preview_id="<preview_id from previous step>")`. The tool takes only `preview_id`, not ticker/side/quantity.
- `update_action_status(action_id, "executed", execution_result={...})`: update audit trail with execution details.
- After execution: `get_risk_analysis(format="full")` to verify drift resolved.
- If user declines any recommendation: `update_action_status(action_id, "rejected", status_reason="<user's reason>")`.

## Output Format

1. `Allocation Snapshot`
- Table: asset class, current %, target %, drift %, status (on target / overweight / underweight).

2. `Key Observations`
- Material drift items, compliance violations, concentration flags.
- Context from prior allocation reviews if available.

3. `Rebalance Plan` (if applicable)
- Table: ticker, side (BUY/SELL), shares, estimated value, weight change.
- Summary: total sell value, total buy value, net cash impact.

4. `Impact Preview` (if applicable)
- Before/after: volatility, concentration (HHI), beta, compliance status.

5. `Action Items`
- Trades to execute, targets to update, next review date suggestion.

## Tool Notes
- Prefer parallel tool calls in step 2 for independent data pulls.
- This is a multi-turn workflow — present drift assessment (after step 3) before generating a rebalance plan. The user may be satisfied with the snapshot alone.
- If the user doesn't have targets set, help them define reasonable ones based on current allocation + risk profile before proceeding.
- Use `record_workflow_action` at step 4 when presenting the rebalance recommendation. Use `update_action_status` at step 6 after execution completes.
- Keep the review proportional — if drift is minimal, a brief "all on target" summary is sufficient.
- All target_weights values are decimals (0.24 = 24%), not percentages.
- The audit status flow is: `pending` → `accepted` → `executed` (or `pending` → `rejected`). Always transition through `accepted` before `executed`.
```

### 3. Skill: `risk-review.md` (AI-excel-addin)

**File**: `api/memory/workspace/memory/skills/risk-review.md`

```markdown
---
name: risk-review
description: Portfolio risk assessment — identify violations, diagnose drivers, recommend mitigations, preview impact, and execute.
---

# Risk Review

## When to Use
- The user asks to review portfolio risk, check compliance, or assess risk exposure.
- After a market event and the user wants to understand risk impact.
- Proactive risk monitoring — periodic check for new violations or emerging risks.
- The user sees a risk flag and wants to understand and address it.

## When NOT to Use
- The task is specifically about allocation drift and rebalancing (use allocation-review).
- The user wants performance attribution or trade review (use performance-review).
- The user is researching a single stock (use position-initiation or stock-pitch).

## Workflow

1. Confirm scope.
- Confirm portfolio name if not obvious.
- Ask if the user has a specific risk concern (concentration, volatility, factor exposure) or wants a full review.

2. Run risk assessment (parallel tool calls).
- `get_risk_analysis(format="agent")`: compliance status, violations, risk factors, variance decomposition, concentration.
- `get_risk_score(format="agent")`: overall score (0-100), component scores, recommendations. Note: if risk limits are not configured, this tool returns an error — treat that as "no risk score available" and proceed with risk analysis data only.
- `get_positions(format="agent")`: holdings with concentration flags, sector breakdown.
- `get_action_history(workflow_filter="risk_review")`: prior risk review actions.

3. Diagnose risk drivers.
- Review flags from risk analysis and risk score — focus on error and warning severity first.
- For each violation, identify the driver positions:
  - Concentration: which positions exceed limits?
  - Volatility: which positions contribute most to portfolio vol? (from `risk_attribution` in risk analysis response)
  - Factor exposure: which factor bets are unintended? (from `factor_exposures` in risk analysis response)
- If factor analysis needed: `get_factor_analysis(format="agent")` for correlation and factor exposure details.
- If leverage concern: `get_leverage_capacity(format="agent")` for margin and leverage metrics.
- **Present diagnosis to user**: prioritized list of issues, driver positions, severity.

4. Recommend mitigations.
- For each material issue, generate specific actions:
  - **Concentration**: reduce overweight positions via `preview_rebalance_trades(weight_changes={"AAPL": -0.05, ...})`. Values are decimal deltas.
  - **Factor exposure**: `get_factor_recommendations(format="agent")` for hedge candidates.
  - **Tax efficiency**: `suggest_tax_loss_harvest(format="agent")` to check if any mitigation trades are also tax-efficient.
  - **Exit signals**: For each flagged ticker, call `check_exit_signals(ticker="AAPL", format="agent")` individually. This is a single-ticker tool — loop through flagged positions one at a time.
- `record_workflow_action(workflow_name="risk_review", recommendation_type="<one of: trade, rebalance, hedge, reduce_position, add_position, custom>", recommendation_text="...", source_tool="...", source_flag="...", flag_severity="<error|warning|info>")`: record each recommendation. The `recommendation_type` must be one of the allowed enum values.
- Present ranked recommendations to user with estimated impact per action.

5. Preview combined impact.
- Build combined target_weights or delta_changes that reflect all accepted mitigations. `target_weights` use decimals (0.24 = 24%). `delta_changes` support decimals OR string format: `{"AAPL": "+5%", "TSLA": "-200bp"}` (percent and basis point strings).
- `run_whatif(target_weights={...} or delta_changes={...}, format="agent")`: simulate combined effect. Note: `run_whatif` and `compare_scenarios` both require risk limits to be configured — if they return an error about missing risk limits, skip the preview and inform the user they can set up limits via `set_risk_profile` to enable scenario previews.
- Compare before/after: volatility, compliance status, factor exposures.
- If multiple options: `compare_scenarios(mode="whatif", scenarios=[{"name": "Option A", "target_weights": {...}}, {"name": "Option B", "delta_changes": {...}}])` to rank alternatives. Each scenario needs a unique `name` and exactly one of `target_weights` or `delta_changes`.
- Present: "These changes would reduce vol from X% to Y%, resolve N violations."
- Note: what-if output includes volatility and compliance but NOT risk score. To get an updated risk score after changes, run the actual trades and re-check.

6. Execute (only with explicit user approval).
- First: `update_action_status(action_id, "accepted")` for each recommendation the user approves. For rejected ones: `update_action_status(action_id, "rejected", status_reason="<reason>")`.
- `preview_rebalance_trades(target_weights={...} or weight_changes={...}, preview=True, account_id="...")`: each leg returns a `preview_id`.
- For each approved leg: `execute_trade(preview_id="<preview_id>")`. The tool takes only `preview_id`.
- `update_action_status(action_id, "executed", execution_result={...})` for each executed recommendation.
- After execution: `get_risk_analysis(format="agent")` to verify violations resolved. Optionally `get_risk_score(format="agent")` if risk limits are configured (may error without them — treat as informational).

## Output Format

1. `Risk Summary`
- Risk score (0-100) if available, category, compliance status.
- Count and severity of violations.

2. `Issues & Drivers`
- Prioritized table: issue, severity, driver positions, current value vs limit.

3. `Recommendations`
- Ranked actions: what to do, which positions, estimated impact, tax implications.

4. `Impact Preview` (if applicable)
- Before/after: volatility, compliance, factor exposures.

5. `Action Items`
- Approved trades to execute, risk limits to adjust, monitoring items.

## Tool Notes
- Prefer parallel tool calls in step 2 for the initial assessment.
- This is a multi-turn workflow — present diagnosis (after step 3) before generating recommendations. The user may want to prioritize certain issues over others.
- Some issues may be informational only (no action needed). Don't recommend trades for every flag.
- Use `record_workflow_action` when presenting each recommendation. Track which ones the user accepts vs rejects via `update_action_status`.
- The audit status flow is: `pending` → `accepted` → `executed` (or `pending` → `rejected`). Always transition through `accepted` before `executed`.
- If the user's risk profile is too restrictive (many violations that are intentional), suggest `set_risk_profile` to adjust limits rather than forcing trades.
- Cross-reference with `get_action_history` to avoid re-recommending recently rejected actions.
- `target_weights` and `weight_changes` use decimal values (0.05 = 5%). `delta_changes` supports both decimals and string format (`"+5%"`, `"-200bp"`).
- `check_exit_signals` is a single-ticker tool — call it once per ticker, not with a list.
```

---

## Backend Change

| File | Repo | Change |
|------|------|--------|
| `mcp_tools/audit.py` line 13 | risk_module | Add `"allocation_review"` to `_ALLOWED_WORKFLOWS` |

## Skill Files

| File | Repo | Change |
|------|------|--------|
| `api/memory/workspace/memory/skills/allocation-review.md` | AI-excel-addin | NEW — allocation review skill |
| `api/memory/workspace/memory/skills/risk-review.md` | AI-excel-addin | NEW — risk review skill |

---

## Key Design Decisions

1. **Skills, not backend orchestrators** — The agent chains existing MCP tools guided by skill instructions. No new composite tools or Python orchestration code. This matches the AI-excel-addin pattern where skills are markdown choreography files.
2. **Multi-turn with breakpoints** — Both skills present findings at natural breakpoints (after assessment, after recommendations) so the user can steer before action. Matches `position-initiation` pattern.
3. **Audit trail integration** — Skills explicitly reference `record_workflow_action` at recommendation points and `update_action_status` at execution. This wires the new audit trail into workflow usage. Status flow: `pending` → `accepted` → `executed` (or `pending` → `rejected`).
4. **Cross-session context** — Skills call `get_action_history(workflow_filter=...)` at step 2 to pick up context from prior reviews (stale pending actions, recently rejected recommendations).
5. **Allocation Review is the simpler skill** — Steps 1-3 are often sufficient (drift check, report, done). Steps 4-6 only if rebalance needed. Risk Review always has more diagnosis steps.
6. **Ticker weight conversion in the skill** — The allocation review skill describes how to convert asset-class targets to ticker weights (pro-rata across current holdings). This is agent logic, not a backend tool, since the mapping depends on interpretation. Empty asset class sleeves require user input.
7. **Allocation review uses `format="full"`** — The agent format snapshot (`get_summary()`) does not include drift data. The full API response includes `asset_allocation` array with `target_pct`, `drift_pct`, `drift_status`, `drift_severity` per asset class. Risk review uses `format="agent"` since it doesn't need drift.
8. **`execute_trade` takes `preview_id` only** — The tool signature is `execute_trade(preview_id: str)`. All order details (ticker, side, quantity, account) are resolved from the preview. Skills must first call `preview_rebalance_trades(preview=True)` to get preview IDs.
9. **Weight units** — `target_weights` and `weight_changes` use decimal notation (0.24 = 24%). `delta_changes` also supports string format (`"+5%"`, `"-200bp"`). Skills explicitly note this to prevent confusion.
10. **What-if does not produce risk scores** — The what-if tool outputs volatility, compliance, and factor changes but not a 0-100 risk score. Skills do not claim before/after risk score in impact previews.
11. **What-if and compare_scenarios require risk limits** — Both tools hard-error without configured risk limits. Skills include fallback language: skip preview, inform user, suggest `set_risk_profile`.
12. **Compliance field names** — The full risk response uses `risk_limit_violations_summary` and `beta_exposure_checks_table`. Skills reference these correct field names.

---

## Codex Review Issues Addressed

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| 1 | HIGH | `allocation_review` not in `_ALLOWED_WORKFLOWS` | Added backend change to add it (line 13 of `mcp_tools/audit.py`) |
| 2 | HIGH | `execute_trade` called with wrong params | Fixed to `execute_trade(preview_id="...")` in both skills |
| 3 | HIGH | Audit status skips `accepted` → goes straight to `executed` | Added explicit `update_action_status(action_id, "accepted")` step before execution |
| 4 | HIGH | Drift data not in agent format snapshot | Allocation review now uses `format="full"` with note explaining why |
| 5 | HIGH | `check_exit_signals` requires single ticker | Added note: "call it once per ticker, not with a list" |
| 6 | HIGH | Weight units inconsistent (% vs decimal) | All examples use decimals (0.24), explicit note in Tool Notes |
| 7 | MED | No `rejected` status updates | Added `update_action_status(action_id, "rejected", ...)` for declined recommendations |
| 8 | MED | `get_risk_score` errors without risk limits | Added fallback note: "if risk limits not configured, treat as unavailable" |
| 9 | MED | `compare_scenarios` usage underspecified | Added explicit format: `scenarios=[{"name": "...", "target_weights": {...}}]` |
| 10 | MED | `recommendation_type` open-ended but backend has fixed enum | Listed all 6 allowed values in skill text |
| 11 | MED | Pro-rata missing decision for empty sleeves | Added: "If an asset class has no current holdings, ask the user which tickers to use" |
| 12 | MED | What-if claims before/after risk score | Removed risk score from impact preview claims; added note that what-if doesn't produce scores |

### Round 2 Issues (from re-review)

| # | Severity | Issue | Fix |
|---|----------|-------|-----|
| R2-1 | HIGH | Plan claimed `allocation_review` already in allowlist | Clarified as implementation step with "must be applied before skill can record audit actions" |
| R2-2 | MED | Outdated compliance field names in skill text | Updated to `risk_limit_violations_summary` / `beta_exposure_checks_table` |
| R2-3 | MED | `delta_changes` supports string format (`%`, `bp`) not just decimals | Updated Tool Notes and skill text to document string format support |
| R2-4 | MED | `run_whatif` and `compare_scenarios` hard-error without risk limits | Added fallback language in both skills' preview steps |

---

## Verification

### Functional testing (live, manual)
1. Ensure portfolio-mcp tools are loaded (`load_tools` in AI-excel-addin, or `/mcp` in Claude Code)
2. Test allocation-review skill:
   - Set targets: `set_target_allocation(allocations={"equity": 60, "bond": 30, "cash": 10})`
   - Say "review my allocation" → agent should discover and follow the skill
   - Verify: drift table presented, rebalance plan offered if needed, audit trail recorded
   - Verify: `record_workflow_action(workflow_name="allocation_review", ...)` succeeds (requires backend allowlist fix)
3. Test risk-review skill:
   - Say "review my portfolio risk" → agent should follow risk-review skill
   - Verify: risk score + violations presented, driver diagnosis, recommendations with audit trail
   - Test without risk limits configured → verify graceful handling when `get_risk_score` fails
4. Verify skill discovery: check that `_build_skills_section()` picks up both new files in the catalog
5. Verify execute flow: preview → `execute_trade(preview_id=...)` → `update_action_status` with accepted then executed

### Cross-session continuity
1. Run allocation review → accept some recommendations, reject others
2. Verify both `accepted` and `rejected` statuses recorded via `update_action_status`
3. In new session: run allocation review again → verify `get_action_history` shows prior actions
4. Verify stale pending actions flagged if prior recommendations not acted on
