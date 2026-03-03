# Stock Research Skill — Final Workflow (7 of 7)

## Context

6 of 7 workflows from WORKFLOW_DESIGN.md are implemented as skills. Stock Research was deferred because two existing skills overlap with it:

- **position-initiation** (9 steps) — deep diligence: business overview → financials → competitive → earnings → risk/scenario → decision → execute → journal. Uses fmp-mcp tools (`fmp_profile`, `get_financials`, `compare_peers`, `get_news`, `get_earnings_transcript`, `get_insider_trades`, `get_institutional_ownership`) + portfolio-mcp tools (`run_whatif`, `get_factor_analysis`, `analyze_option_chain`, `get_risk_score`, `get_leverage_capacity`, `preview_trade`, `execute_trade`) + memory tools.
- **stock-pitch** (5 steps) — structured write-up: gather prior work → pull data → draft SIA-format pitch → review → present. Explicitly designed to run *after* position-initiation.

The WORKFLOW_DESIGN.md Stock Research workflow (5 steps): Find & Profile → Analyze (6 dimensions) → Portfolio Fit → Size Position → Execute.

**Key observation:** position-initiation already covers Steps 1-2 and most of Steps 4-5. The gap is **Step 3 (Portfolio Fit)** — position-initiation does `run_whatif` and `get_factor_analysis` in step 6 but doesn't do the structured overlap/diversification analysis or multi-size comparison. Also, position-initiation is more oriented toward deep fundamental diligence, while Stock Research in WORKFLOW_DESIGN.md is more of a "quick research + portfolio integration" flow.

## Design Decision: Enhance position-initiation, don't create stock-research.md

Creating a separate `stock-research.md` would largely duplicate position-initiation. Instead:

1. **Enhance position-initiation.md** with the missing portfolio-fit and sizing steps from WORKFLOW_DESIGN.md
2. **Add `stock_research` to `_ALLOWED_WORKFLOWS`** in audit.py for audit trail
3. **Add audit integration** to position-initiation (currently has none)
4. **Update WORKFLOW_DESIGN.md** status to reflect this decision

The enhanced position-initiation becomes the single "research a stock" skill, with the depth calibrated to the situation (step-level note already says "keep diligence proportional to opportunity").

## Changes

### 1. Enhance `position-initiation.md` (AI-excel-addin)

**File**: `api/memory/workspace/memory/skills/position-initiation.md`

Add/modify these sections:

**Step 6 (Risk assessment and scenario analysis) — expand portfolio fit:**
Currently has `run_whatif` (with mention of "different position sizes") and `get_factor_analysis`. Make multi-size comparison structured and add portfolio overlap analysis:
- `get_risk_analysis(format="agent")` — current portfolio factor exposures, concentration, sector weights for overlap analysis
- `get_factor_analysis(analysis_type="correlations")` — correlation with existing holdings
- Multi-size `run_whatif`: test at 1%, 2.5%, 5% to find the sweet spot
- Explicit overlap/diversification synthesis: sector overlap, factor overlap, correlation, similar holdings
- `get_leverage_capacity()` — ensure position doesn't push leverage beyond capacity

**Step 7 (Decision framework) — expand sizing:**
Currently lists suggested position size as one bullet. Add:
- Sizing approaches: risk-budget, equal-weight, conviction, options entry
- `analyze_option_strategy` for options entry alternative (cash-secured put, etc.)
- Clear sizing table output: weight, shares, cost, vol impact, compliance per scenario

**Step 8 (Execute) — add audit trail:**
- `record_workflow_action(workflow_name="stock_research", recommendation_type="trade", recommendation_text="...")` after decision, before trade

**Breakpoints (already exist in Tool Notes, make explicit in step text):**
- After step 3 (business overview) — user can steer before deep diligence
- After step 6 (risk/portfolio fit) — user confirms before sizing/execution

### 2. Add `stock_research` to `_ALLOWED_WORKFLOWS` (risk_module)

**File**: `mcp_tools/audit.py` line 13

Add `"stock_research"` to the set. Also update the error message strings at lines 89 and 222.

### 3. Update skill description in frontmatter

Current: `description: Full workflow from idea through diligence, risk assessment, and trade execution — maps to Notion Ideas/Portfolio/Journal databases.`

Updated to also mention stock research trigger: `description: Full stock research and position initiation — from idea through diligence, portfolio fit analysis, risk assessment, sizing, and trade execution.`

### 4. Update WORKFLOW_DESIGN.md status

**File**: `docs/planning/WORKFLOW_DESIGN.md`

Change Stock Research status from `Defined (deferred)` to `Skill implemented (via position-initiation enhancement)`.

Update the skill mapping table to show `stock-research → position-initiation.md (enhanced)`.

---

## Critical Tool Parameter Details

Same rules as Phase 4 apply. Additional for this skill:

**`run_whatif` for multi-size comparison:** `delta_changes` is a **dict** (not JSON string) at the MCP boundary. Call separately at each size level:
- `run_whatif(delta_changes={"AAPL": "+1%"}, format="agent")`
- `run_whatif(delta_changes={"AAPL": "+2.5%"}, format="agent")`
- `run_whatif(delta_changes={"AAPL": "+5%"}, format="agent")`

OR use `compare_scenarios` for batch (note: `scenarios` IS a JSON string at MCP boundary, but `delta_changes` inside each scenario object is a dict):
- `compare_scenarios(mode="whatif", scenarios='[{"name":"1%","delta_changes":{"AAPL":"+1%"}},{"name":"2.5%","delta_changes":{"AAPL":"+2.5%"}},{"name":"5%","delta_changes":{"AAPL":"+5%"}}]', rank_by="vol_delta", rank_order="asc")`

**`record_workflow_action` call:**
- `record_workflow_action(workflow_name="stock_research", recommendation_type="trade", recommendation_text="Buy 64 shares AAPL at $196 limit — 2.5% position, within all risk limits")`

**`delta_changes` values must be strings:** `"+1%"`, `"+2.5%"`, `"+5%"` — not raw floats.

---

## Files Changed

| File | Repo | Change |
|------|------|--------|
| `api/memory/workspace/memory/skills/position-initiation.md` | AI-excel-addin | MODIFY — add portfolio fit, sizing, audit, breakpoints |
| `mcp_tools/audit.py` | risk_module | MODIFY — add `stock_research` to allowed workflows |
| `docs/planning/WORKFLOW_DESIGN.md` | risk_module | MODIFY — update status table |

---

## Key Design Decisions

1. **Enhance, don't duplicate** — position-initiation already covers 90% of Stock Research. A separate skill would confuse the agent about which to load. One skill, calibrated depth.
2. **`stock_research` as workflow name (not `position_initiation`)** — The audit trail uses `stock_research` to match WORKFLOW_DESIGN.md's workflow naming. The skill file stays `position-initiation.md` because that's what's already deployed and referenced.
3. **`compare_scenarios` for multi-size comparison** — Same pattern as other Phase 4 skills. Batch compare sizing options instead of sequential `run_whatif` calls.
4. **stock-pitch remains separate** — It's a different output format (structured write-up) that runs *after* research. No merge needed.
5. **Catalog unchanged** — We're modifying an existing skill, not adding one. The 10-skill catalog stays at ~2036 chars, well within the 2500 limit.

---

## Verification

### Backend
- After adding `stock_research` to `_ALLOWED_WORKFLOWS`, verify: `record_workflow_action(workflow_name="stock_research", ...)` doesn't raise ValueError
- Run existing audit tests: `pytest tests/ -k "audit" -x`

### Live testing
- "research AAPL for me" → agent should discover position-initiation skill, call `memory_read`
- Verify tool chain: parallel data pulls (step 2) → portfolio fit analysis (step 6) → sizing comparison → audit recorded
- Verify breakpoints: agent pauses after step 3 and step 6

### Catalog sizing
- No change — still 10 skills, same catalog
