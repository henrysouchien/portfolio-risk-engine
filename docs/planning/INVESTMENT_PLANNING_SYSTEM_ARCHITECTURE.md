# Investment Planning System — Architecture Document
**Status:** ACTIVE

## Purpose

This is a **design document**, not an implementation plan. It maps out how three existing systems (finance-cli, risk_module, analyst-claude) connect into a unified investment planning layer. No code changes until we align on the architecture.

## The Problem

Three systems each own a piece of the investment picture but don't talk to each other:

- **finance-cli** — "How much can I invest?" (cash flow, savings, debt, obligations)
- **risk_module** — "What should I own?" (portfolio, risk, allocations, optimization)
- **ai-excel-addin (analyst-claude)** — "What should I buy/sell?" (research, screening, idea pipeline, autonomous agent, Excel model integration)

Today Claude orchestrates between them conversationally, but there's no persistent plan connecting them. Each session starts from scratch.

**Key: ai-excel-addin is the analyst-claude system.** It includes:
- Autonomous analyst agent (`api/analyst/runner.py`) — runs periodic market/portfolio scans, writes daily briefings
- Memory workspace (`api/memory/workspace/`) — markdown files + SQLite ticker DB (`analyst_memory.db`), auto-indexed
- 10 workflow skills (`memory/skills/`) — allocation-review, risk-review, performance-review, earnings-review, position-initiation, stock-pitch, hedging, scenario-analysis, strategy-design, model-update
- 83+ ticker memory files with structured knowledge (thesis, conviction, catalysts, risk)
- Financial model schema engine (`schema/`) — Excel model parsing, EDGAR data matching
- MCP servers: excel-mcp, model-engine, sheetsfinance-mcp

## Architecture: Hybrid Model

```
┌──────────────────────────────────────────────────────────┐
│                 CLAUDE (Hub Orchestrator)                  │
│  Workflow skills choreograph multi-tool review sequences   │
│  Claude is the ONLY entity that crosses system boundaries  │
└─────────┬──────────────────┬──────────────────┬──────────┘
          │                  │                  │
          ▼                  ▼                  ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  finance-cli    │ │  risk_module    │ │  analyst-claude  │
│                 │ │                 │ │                  │
│ financial_      │ │ target_alloc    │ │ ai-excel-addin   │
│   summary       │ │ risk_profile    │ │                  │
│ net_worth_proj  │ │ optimization    │ │ ticker workspace │
│ liquidity       │ │ rebalance       │ │ 10 workflow skills│
│ goal_set/status │ │ whatif           │ │ autonomous agent │
│ spending_trends │ │ risk_score      │ │ Excel models     │
│ debt_dashboard  │ │ income_proj     │ │ daily briefings  │
│ biz_forecast    │ │ performance     │ │                  │
└────────┬────────┘ └────────┬────────┘ └────────┬────────┘
         │                   │                    │
         ▼                   ▼                    ▼
   finance-cli DB      risk_module DB     memory workspace
   (SQLite)            (Postgres)         (markdown + SQLite)
```

**Key principle:** Claude is the hub. No direct inter-MCP communication. The **plan artifact** is the shared state that all three systems contribute to and reference.

**Dual storage:** risk_module DB as source of truth for plan policy/allocations (machine-queryable, drift monitoring). ai-excel-addin memory workspace for research pipeline state (ticker knowledge, daily briefings, trade journal). finance-cli DB for goals and financial picture.

## The Plan Object

Five layers, each sourced from a different system:

### Layer 1: Financial Context (from finance-cli)
Snapshot of financial picture at plan creation/review time.
- Net worth, liquid cash, monthly savings, investable surplus
- Debt obligations, emergency fund months
- Business income (if applicable)
- **Sourced by:** `financial_summary()`, `liquidity()`, `spending_trends()`, `debt_dashboard()`

### Layer 2: Goals (owned by finance-cli)
**finance-cli is the single source of truth for all goals.** Investment goals are goals with an investment category. risk_module reads them via Claude orchestration during reviews — never stores a copy.
- Name, target amount, target date, priority, risk tolerance
- Required return (computed at review time: CAGR from current to target)
- Monthly contribution (allocated from investable surplus)
- Status: on_track / behind / ahead / at_risk
- **Sourced by:** `goal_status()`, `goal_set()` in finance-cli
- **Example:** "Retirement" ($2M, 2055, aggressive), "House" ($200K, 2028, conservative)

### Layer 3: Investment Policy (maps to risk_module)
Derived from goal blend. This IS the plan.
- Risk profile → maps to `set_risk_profile()`
- Target allocation by asset class → maps to `set_target_allocation()`
- **Sleeves** — sub-allocations within asset classes:
  - "Passive Core" (60%) — index funds, benchmark VTI
  - "Active Stock Picks" (15%) — connects to analyst-claude research pipeline
  - "Fixed Income" (20%) — bonds/REITs
  - "Cash Reserve" (5%) — liquidity buffer
- Constraints: max single position, max sector, max leverage, tax-loss harvesting

### Layer 4: Execution State (live, computed from risk_module)
Never stored — always a live query against current portfolio.
- Current allocation vs target → drift per asset class
- Drift status: within_band / needs_rebalance / critical
- Risk score, YTD performance, pending actions
- **Sourced by:** `get_risk_analysis()`, `get_performance()`, `get_risk_score()`, `get_target_allocation()`

### Layer 5: Research Pipeline (from ai-excel-addin / analyst-claude)
View into the memory workspace (`api/memory/workspace/tickers/`). Each ticker has a structured memory file (thesis, conviction, catalysts, key risks, valuation frame, entry price). Not duplicated — read via `memory_recall` or `memory_read` tools.
- Active ideas with conviction/stage/target sleeve (from ticker memory files)
- Recently sold (wash sale awareness, from `memory/trades/` journal)
- Watch list
- Daily briefings with alerts/actions (`memory/daily/`)
- **Existing skills that feed this:** position-initiation, stock-pitch, earnings-review

## Review Cycle

A guided 7-step workflow (implemented as a workflow skill):

```
Step 1: Financial Picture (finance-cli)
  → Has investable surplus changed? Emergency fund adequate?

Step 2: Portfolio State (risk_module)
  → Current allocation, drift, risk score, performance

Step 3: Compare Against Plan
  → Drift from targets, goal progress vs required pace

Step 4: Identify Gaps
  → Drift > threshold? Goal behind? Risk outside bounds?
    Financial picture changed? Research ideas ready?

Step 5: Propose Actions
  → Rebalance trades, contribution changes, risk adjustments,
    research requests, plan revisions

Step 6: Execute Approved Actions
  → User approves/rejects each. Uses existing tools:
    preview_rebalance_trades(), set_target_allocation(),
    record_workflow_action()

Step 7: Snapshot & Schedule
  → Save point-in-time state, set next review date, write summary to memory workspace
```

## What Needs to Be Built

### Already exists — just compose
| Component | Existing Tools |
|-----------|---------------|
| Financial context pull | `financial_summary()`, `liquidity()`, `spending_trends()`, `debt_dashboard()` |
| Portfolio state check | `get_risk_analysis()`, `get_performance()`, `get_risk_score()`, `get_target_allocation()` |
| Action audit trail | `record_workflow_action()`, `update_action_status()`, `get_action_history()` |
| Trade execution | `preview_rebalance_trades(preview=True)` |
| Risk profile management | `set_risk_profile()`, `get_risk_profile()` |
| Allocation management | `set_target_allocation()`, `get_target_allocation()` |
| Income projection | `get_income_projection()` |
| Scenario comparison | `compare_scenarios()` |

### Light additions
- Add `"plan_review"` to `_ALLOWED_WORKFLOWS` in `mcp_tools/audit.py` (1 line)
- Goal progress computation helper (required return, on_track status)
- Drift calculation helper (current - target per asset class)
- Extend existing allocation-review skill to include finance-cli context pull

### New infrastructure
- DB tables: `investment_plans`, `plan_snapshots` (no `plan_goals` — finance-cli owns goals)
- MCP tools: `set_investment_plan()`, `get_investment_plan()`, `save_plan_snapshot()`
- `set_investment_plan()` calls `set_risk_profile()` + `set_target_allocation()` as side effects
- New workflow skill: `/plan-review` (extends existing allocation-review + risk-review patterns)
- Plan summary written to ai-excel-addin memory workspace for analyst-claude awareness

## Phasing

### Phase 0: Workflow Skill Only (no new code)
- Write `/plan-review` skill in ai-excel-addin (`memory/skills/plan-review.md`) using only existing tools
- Extends existing allocation-review + risk-review patterns, adds finance-cli context pull
- Plan state captured in a markdown file in the memory workspace (`memory/plans/investment-plan.md`)
- Test the review workflow end-to-end
- **Value:** Structured review process immediately. Validates the workflow before building infrastructure.

### Phase 1: Plan Persistence
- DB tables + MCP tools in risk_module for plan CRUD
- `set_investment_plan()` as single entry point that configures downstream systems
- Plan summary synced to ai-excel-addin memory workspace so analyst-claude is aware of plan constraints
- **Value:** Machine-queryable plan. Drift computed programmatically.

### Phase 2: Goal Intelligence
- Goal progress computation + gap analysis
- `review_investment_plan()` MCP tool (steps 1-4 automated)
- Finance-cli integration for financial snapshots
- **Value:** "Goal X is behind, increase contributions by $Y/month"

### Phase 3: Research Pipeline Integration
- Connect "Active Stock Picks" sleeve to ai-excel-addin's ticker workspace
- During plan review, read ticker memory files for ideas with conviction=high and stage=ready_to_buy
- Check ideas against plan constraints (max position size, sector limits, total active sleeve allocation)
- Existing skills (position-initiation, stock-pitch) already produce structured ticker knowledge — just need to read it during reviews
- **Value:** Research ideas flow into plan as actionable, sized items.

### Phase 4: Automated Monitoring
- Periodic drift checks, goal pace alerts
- Financial context change detection
- **Value:** System tells you when attention is needed between reviews.

## Investment Questionnaire (Plan Creation)

The `/plan-create` or `/investment-questionnaire` skill is the front door to the system. It walks through foundational questions and translates answers into plan parameters:

- **Risk tolerance** — "If your portfolio dropped 20% in a month, would you buy more, hold, or sell?" → maps to `set_risk_profile()` (income/balanced/growth/trading)
- **Time horizons** — "When do you need this money?" → per-goal, drives asset allocation blend
- **Income needs** — "Do you need income from the portfolio, or is this pure growth?" → determines Fixed Income sleeve strategy (yield vs stability)
- **Concentration comfort** — "Are you OK with 10%+ in a single position?" → maps to `max_single_stock_weight` risk limit
- **Active vs passive preference** — "How much do you want to actively manage?" → determines Passive Core vs Active Picks sleeve split

The questionnaire produces the initial investment policy (Layer 3), which gets written to `set_risk_profile()` + `set_target_allocation()`. Future `/plan-review` runs check against this baseline.

The risk_module already has the machinery for all of this — 4 risk profile templates, configurable target allocations, risk limits with thresholds. The questionnaire is a structured way to populate those fields.

## Decisions Made

- **Sleeves:** Yes — sub-allocations with named strategies. Active Picks sleeve bridges to analyst-claude.
- **Goal storage:** finance-cli owns all goals. risk_module reads them during reviews via Claude orchestration.

## Open Questions

1. **Plan mutability:** Can goals/allocations change mid-review, or only at formal review points? How strict is the policy?

2. **Multi-plan:** Should we support multiple plans per user (e.g., taxable vs retirement account), or one plan with multiple sleeves?

3. **Phase 0 scope:** Should we start with Phase 0 (workflow skill only, no code) to validate the review workflow before building infrastructure?
