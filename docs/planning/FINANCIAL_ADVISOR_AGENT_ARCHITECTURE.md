# Financial Advisor Agent — Architecture Document

**Status:** DESIGN
**Created:** 2026-03-10
**Related:** `INVESTMENT_PLANNING_SYSTEM_ARCHITECTURE.md` (predecessor — plan artifact design still relevant)

## Purpose

High-level design for a unified **financial advisor agent** that bridges three existing systems into one coherent advisory experience. No repo merges — each system stays independent. The advisor is a new agent profile that orchestrates across all of them.

## The Problem

Three systems, three agents, three memory stores — but no unified advisor perspective:

| System | Repo | Agent | Domain | Data Store | Cadence |
|--------|------|-------|--------|------------|---------|
| **finance-cli** | `finance_cli/` | finance-cli claude | Personal finance: cash flow, budgets, goals, spending, debt, business accounting | SQLite | Daily / as-needed |
| **risk_module** | `risk_module/` | portfolio-mcp claude | Investment management: portfolio, risk, trading, optimization, performance | Postgres | On-demand |
| **analyst-claude** | `AI-excel-addin/` | analyst-claude | Research & execution: market scans, stock pitches, models, daily briefings, idea pipeline | Markdown workspace + SQLite (`analyst_memory.db`) | Daily (autonomous) |

Today, Claude can access all three in a single session (all MCP servers are registered), but:
1. **No persistent advisor state** — every session starts cold
2. **No cross-domain reasoning** — each agent thinks within its own domain
3. **No unified plan** — goals live in finance-cli, allocations in risk_module, research in analyst-claude
4. **No structured review cadence** — reviews happen ad-hoc, not systematically

## Architecture: Three Agents, One Advisor

```
                    ┌─────────────────────────────────────┐
                    │        ADVISOR-CLAUDE (new)          │
                    │                                      │
                    │  "Am I on track? What should change?" │
                    │                                      │
                    │  Cadence: Weekly / monthly            │
                    │  Memory: advisor workspace            │
                    │  Skills: /plan-review, /checkup,      │
                    │          /goal-progress, /rebalance   │
                    │                                      │
                    ├──────┬──────────────┬────────────────┤
                    │      │              │                │
                    ▼      ▼              ▼                ▼
        ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
        │ finance-cli  │ │ portfolio-mcp│ │ fmp-mcp      │
        │ MCP (~100    │ │ MCP (~50     │ │ (~15 tools)  │
        │ tools)       │ │ tools)       │ │              │
        └──────┬───────┘ └──────┬───────┘ └──────────────┘
               │                │
               ▼                ▼
        finance-cli DB    risk_module DB
        (SQLite)          (Postgres)
```

```
    ┌──────────────────────────────────────────────────────────┐
    │              ANALYST-CLAUDE (existing)                    │
    │                                                          │
    │  "What's happening in the market and my portfolio?"       │
    │                                                          │
    │  Cadence: Daily (autonomous)                             │
    │  Memory: workspace/memory/ (markdown + SQLite)           │
    │  Skills: 19 workflow skills                              │
    │  Runner: api/analyst/runner.py (autonomous scans)        │
    │  Connectors: 8 data enrichment modules                   │
    │                                                          │
    ├──────┬──────────────┬───────────┬───────────────────────┤
    │      │              │           │                        │
    ▼      ▼              ▼           ▼                        ▼
  portfolio  fmp-mcp   ibkr-mcp   model-engine         excel-mcp
  -mcp                             sheetsfinance
    └──────────────────────────────────────────────────────────┘
```

```
    ┌──────────────────────────────────────────────────────────┐
    │            FINANCE-CLI CLAUDE (existing)                  │
    │                                                          │
    │  "What's happening with my money?"                        │
    │                                                          │
    │  Cadence: Daily / as-needed                              │
    │  Memory: ~/.claude/projects/.../memory/MEMORY.md         │
    │  Workflows: 11 documented in AGENT_WORKFLOWS.md          │
    │  Services: Backend + Frontend + Telegram bot + Gateway   │
    │                                                          │
    ├──────────────────────────────────────────────────────────┤
    │                                                          │
    ▼                                                          ▼
  finance-cli MCP                                     Plaid / Schwab sync
  (~100 tools)                                        (bank connections)
    └──────────────────────────────────────────────────────────┘
```

### Why Three Agents, Not One

| Concern | One Agent | Three Agents |
|---------|-----------|-------------|
| Tool count | 200+ tools in context | 50-100 per agent, focused |
| Persona | Confused — analyst vs conservative advisor | Each has a clear identity |
| Cadence | Everything runs at once | Daily research, daily finance, weekly/monthly planning |
| Context pollution | Emergency fund analysis bleeds into stock pitch | Clean domain boundaries |
| System prompt | Massive, contradictory | Short, focused, domain-specific |

### How They Relate

```
  analyst-claude ─── produces ──→ research output (briefings, ideas, conviction scores)
       │                                    │
       │                                    ▼
       │                          advisor-claude reads
       │                          analyst output during
       │                          plan reviews
       │                                    │
       ▼                                    ▼
  portfolio-mcp ←── shared ───→ advisor-claude uses
  (positions, risk,              same MCP tools to
   performance)                  check portfolio state
                                            │
                                            ▼
                                 finance-cli MCP
                                 (goals, cash flow,
                                  surplus, debt)
```

- **Analyst → Advisor**: Advisor reads analyst's ticker memory files, daily briefings, and conviction scores during plan reviews. "The analyst has 3 high-conviction ideas — do they fit the plan?"
- **Finance-cli → Advisor**: Advisor pulls financial context (surplus, goals, debt) to inform portfolio decisions. "Surplus dropped $800/mo — should we pause new deployments?"
- **Advisor → Portfolio-mcp**: Advisor uses risk_module tools to check portfolio state, run what-ifs, generate rebalance trades. "Drift from target is 4% — here are the rebalance legs."
- **Analyst and finance-cli don't need to know about each other.** The advisor is the bridge.

## Agent Profiles

### advisor-claude

**Identity:** Holistic financial advisor. Conservative by default. Goal-oriented. Bridges personal finance and investment management.

**MCP Servers:**
- `finance-cli` — financial context, goals, spending, debt
- `portfolio-mcp` — portfolio state, risk, performance, trading
- `fmp-mcp` — market data, sector overview, economic context

**Does NOT need:**
- `ibkr-mcp` — trade execution is analyst-claude's domain
- `model-engine` / `excel-mcp` — financial modeling is analyst-claude's domain
- `sheetsfinance` — formula work is analyst-claude's domain

**Memory Workspace:** Persistent directory for:
- Investment plan (policy, allocations, sleeves, constraints)
- Review history (point-in-time snapshots)
- Financial context snapshots (surplus, goals, debt — from finance-cli)
- Decision log (why changes were made)

**Workflow Skills:**
- `/plan-review` — structured 7-step review cycle (from `INVESTMENT_PLANNING_SYSTEM_ARCHITECTURE.md`)
- `/financial-checkup` — quick financial health check (surplus, goal pace, debt)
- `/goal-progress` — goal-by-goal status with required return calculation
- `/rebalance-review` — drift analysis + rebalance recommendation

**Cadence:** Weekly quick check, monthly deep review. User-initiated, not autonomous (yet).

### analyst-claude (existing, unchanged)

**Identity:** Aggressive researcher, market analyst, trade executor. Conviction-driven. Autonomous.

**MCP Servers:** portfolio-mcp, fmp-mcp, ibkr-mcp, model-engine, excel-mcp, sheetsfinance

**Memory:** `AI-excel-addin/api/memory/workspace/` — 86 ticker files, 19 skills, daily briefings, trade journal

**Cadence:** Daily autonomous scans + on-demand research

### finance-cli claude (existing, unchanged)

**Identity:** Personal finance assistant. Budget-conscious, goal-tracking, spending-aware.

**MCP Servers:** finance-cli

**Memory:** `~/.claude/projects/.../memory/MEMORY.md` — budget targets, financial context

**Cadence:** Daily / as-needed. Proactive budget alerts.

## The Advisor's Core Capabilities

### 1. Cross-Domain Context Assembly

The advisor's superpower: pulling from both systems in one reasoning pass.

```python
# Pseudo-workflow for a plan review
financial_picture = finance_cli.financial_summary()     # income, expenses, surplus
goals             = finance_cli.goal_status()           # goal progress
portfolio_state   = portfolio_mcp.get_risk_analysis()   # current allocation, risk
performance       = portfolio_mcp.get_performance()     # returns, benchmark
risk_score        = portfolio_mcp.get_risk_score()      # compliance, violations
target_alloc      = portfolio_mcp.get_target_allocation() # target vs actual

# Cross-domain reasoning (Claude's job):
# "Surplus is $3,200/mo, retirement goal is on track,
#  but house fund is behind. Portfolio is 4% overweight tech.
#  Recommendation: redirect $500/mo to house fund,
#  rebalance tech overweight into fixed income."
```

### 2. Plan Artifact as Shared State

The investment plan connects all three systems (design from `INVESTMENT_PLANNING_SYSTEM_ARCHITECTURE.md`):

| Layer | Source | Content |
|-------|--------|---------|
| **1. Financial Context** | finance-cli | Net worth, surplus, debt, emergency fund |
| **2. Goals** | finance-cli | Target amounts, dates, priorities, risk tolerance |
| **3. Investment Policy** | risk_module | Risk profile, target allocation, sleeves, constraints |
| **4. Execution State** | risk_module (live) | Current allocation, drift, risk score, performance |
| **5. Research Pipeline** | analyst-claude | Active ideas, conviction, stage, target sleeve |

The advisor reads all five layers. Layers 1-2 come from finance-cli. Layer 3 maps to `set_risk_profile()` + `set_target_allocation()`. Layer 4 is computed live. Layer 5 is read from analyst memory workspace.

### 3. Review Cycle

Structured weekly/monthly workflow:

```
Step 1: Financial Picture (finance-cli)
  → Has investable surplus changed? Emergency fund adequate?
  → Goal progress: on track / behind / ahead?

Step 2: Portfolio State (risk_module)
  → Current allocation vs target. Drift per asset class.
  → Risk score, violations, performance.

Step 3: Research Pipeline (analyst-claude output)
  → Any high-conviction ideas ready to deploy?
  → Any positions the analyst flagged for exit?

Step 4: Gap Analysis
  → Drift > threshold? Goal behind? Risk outside bounds?
  → Financial picture changed materially?
  → Research ideas ready but no capital allocated?

Step 5: Recommendations
  → Rebalance trades (preview_rebalance_trades)
  → Contribution changes (redirect surplus)
  → Risk adjustments (set_risk_profile)
  → Plan revisions (set_target_allocation)

Step 6: Execute (user approval required)
  → Each recommendation approved/rejected individually
  → Actions recorded (record_workflow_action)

Step 7: Snapshot & Schedule
  → Save review state to advisor memory
  → Set next review date
  → Write summary to analyst workspace (so analyst-claude is aware)
```

### 4. Cold Start Solution

Every advisor session reads the last review snapshot from memory:

```markdown
# Advisor Context — Last Review: 2026-03-10

## Financial Picture
- Monthly surplus: $3,200 (down from $3,800 — new car payment)
- Emergency fund: 4.2 months (target: 6)
- Investable after obligations: $2,400/mo

## Goals
- Retirement ($2M by 2055): ON TRACK — $850K, 7.2% CAGR needed
- House ($200K by 2028): BEHIND — $142K, need $2,900/mo (only allocating $2,000)
- Emergency Fund (6 months): IN PROGRESS — 4.2/6 months

## Portfolio
- Total: $850K | Equity: 78% | Fixed Income: 15% | Cash: 7%
- Risk score: 78.3 (Fair) — 5 violations
- YTD: +4.2% (benchmark +5.1%)
- Drift: Tech +4.3%, Healthcare -2.1%

## Active Research (from analyst)
- 3 high-conviction ideas: MSFT, GOOGL, AMZN
- 1 exit signal: SLV (thesis broken)

## Last Actions
- Redirected $500/mo from discretionary → house fund
- Rebalanced: trimmed NVDA 2%, added BND 2%

## Next Review: 2026-04-07
```

This is the advisor's "resume from where we left off" artifact.

## Implementation Approach

### What Already Exists (Just Compose)

| Capability | Existing Tools |
|-----------|---------------|
| Financial context | `financial_summary()`, `liquidity()`, `spending_trends()`, `debt_dashboard()` |
| Goals | `goal_status()`, `goal_set()` |
| Portfolio state | `get_risk_analysis()`, `get_performance()`, `get_risk_score()` |
| Target allocation | `get_target_allocation()`, `set_target_allocation()` |
| Risk profile | `get_risk_profile()`, `set_risk_profile()` |
| Rebalancing | `preview_rebalance_trades(preview=True)` |
| What-if analysis | `run_whatif()`, `compare_scenarios()` |
| Income projection | `get_income_projection()` |
| Action audit | `record_workflow_action()`, `get_action_history()` |
| Analyst output | analyst workspace files (readable via memory tools or direct file read) |

### What Needs Building

#### Phase 0: Agent Profile Only (no code)
- **Claude Code project**: `~/.claude/projects/advisor-claude/` with `CLAUDE.md` defining persona
- **MCP registration**: finance-cli + portfolio-mcp + fmp-mcp
- **Memory directory**: `advisor-claude/memory/` for plan state and review history
- **1-2 workflow skills**: `/plan-review` and `/financial-checkup` as markdown skill files
- **Value**: Structured advisor experience immediately. Validates the workflow before building infra.

#### Phase 1: Composite Context Tool (optional, light code)
- **`get_advisor_context()` MCP tool** in risk_module — pulls portfolio state + target allocation + risk score + performance into one snapshot
- Saves the advisor 4-5 tool calls to orient itself each session
- Could also be a workflow skill rather than a coded tool

#### Phase 2: Plan Persistence (from INVESTMENT_PLANNING_SYSTEM_ARCHITECTURE.md Phase 1)
- DB tables in risk_module: `investment_plans`, `plan_snapshots`
- MCP tools: `set_investment_plan()`, `get_investment_plan()`, `save_plan_snapshot()`
- Machine-queryable plan. Drift computed programmatically.

#### Phase 3: Goal Intelligence (from INVESTMENT_PLANNING_SYSTEM_ARCHITECTURE.md Phase 2)
- Goal progress computation + gap analysis
- `review_investment_plan()` MCP tool (steps 1-4 automated)
- Cross-domain: reads finance-cli goals, checks against portfolio state

#### Phase 4: Automated Monitoring (from INVESTMENT_PLANNING_SYSTEM_ARCHITECTURE.md Phase 4)
- Periodic drift checks, goal pace alerts
- Financial context change detection
- Advisor becomes proactive — tells you when attention is needed

## Advisor Memory Workspace

Location: TBD — options:
1. **In risk_module repo**: `advisor/memory/` (co-located with portfolio tools)
2. **In AI-excel-addin repo**: `api/memory/workspace/advisor/` (co-located with analyst memory)
3. **Standalone directory**: `~/Documents/Jupyter/advisor-claude/` (independent)

Leaning toward **option 3** — the advisor is its own entity, not owned by either system.

### Workspace Structure

```
advisor-claude/
├── CLAUDE.md                    # Advisor persona + system prompt
├── memory/
│   ├── MEMORY.md                # Auto-memory (preferences, context)
│   ├── plan/
│   │   ├── investment-plan.md   # Current investment policy (Layer 3)
│   │   ├── goals-snapshot.md    # Last finance-cli goals pull (Layer 2)
│   │   └── financial-context.md # Last financial picture (Layer 1)
│   ├── reviews/
│   │   ├── 2026-03-10.md        # Review snapshots
│   │   ├── 2026-04-07.md
│   │   └── ...
│   └── decisions/
│       └── decision-log.md      # Why changes were made
├── skills/
│   ├── plan-review.md           # 7-step review workflow
│   ├── financial-checkup.md     # Quick health check
│   ├── goal-progress.md         # Goal-by-goal analysis
│   └── rebalance-review.md      # Drift + rebalance
└── .claude/
    └── settings.local.json      # MCP tool permissions
```

## Cross-Agent Communication

Agents don't talk directly. Communication flows through shared artifacts:

| From | To | Mechanism | Content |
|------|----|-----------|---------|
| analyst → advisor | Analyst workspace files | Ticker memory, briefings, conviction scores |
| advisor → analyst | Analyst workspace file | Plan summary (so analyst knows constraints) |
| finance-cli → advisor | finance-cli MCP tools | Goals, surplus, spending trends |
| advisor → finance-cli | finance-cli MCP tools | Goal updates, contribution changes |
| advisor → portfolio | portfolio-mcp tools | Risk profile, target allocation, rebalance |

The advisor writes a plan summary to the analyst's workspace so that analyst-claude is aware of plan constraints when making recommendations. Example: "Active Picks sleeve is capped at 15% of portfolio. Max single position 5%."

## Open Questions

1. **Advisor workspace location** — standalone directory, or nested in an existing repo?
2. **Analyst output access** — should advisor read analyst workspace files directly, or should there be a structured summary tool?
3. **Goal ownership** — finance-cli owns goals (decided in INVESTMENT_PLANNING_SYSTEM_ARCHITECTURE.md). But should the advisor be able to suggest goal changes that finance-cli then applies?
4. **Autonomous advisor** — Phase 4 envisions automated monitoring. Should the advisor eventually have its own autonomous runner (like analyst-claude), or should it stay user-initiated?
5. **Multi-account plans** — one plan with sleeves, or separate plans per account type (taxable vs retirement)?
6. **Telegram integration** — finance-cli already has a Telegram bot. Should the advisor also surface through Telegram for weekly check-ins?

## Decisions Made

- **Three agents, not one** — clean domain boundaries, focused personas, manageable tool sets
- **Advisor bridges, doesn't replace** — analyst and finance-cli continue operating independently
- **Plan artifact is shared state** — five-layer plan object from INVESTMENT_PLANNING_SYSTEM_ARCHITECTURE.md
- **Phase 0 is configuration only** — no code needed to start using the advisor pattern
- **finance-cli owns goals** — advisor reads them, may suggest changes, but doesn't store copies
