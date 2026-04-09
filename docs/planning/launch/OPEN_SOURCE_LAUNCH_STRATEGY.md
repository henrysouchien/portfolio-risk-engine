# Open Source Launch Strategy

> **Created**: 2026-03-16
> **Vision**: Ship an open-source investment platform — connect any brokerage, any data provider, bring your own model, get a customizable AI analyst out of the box.
> **Tagline**: "Your infrastructure. Your data. Your model. Your analyst."

---

## What We're Building

An open-source platform that gives anyone — from a solo dev to a small fund — the complete infrastructure to build AI-powered investment workflows. Not a SaaS product with a free tier. Real infrastructure that you own and control.

**The pitch**: Connect your brokerage. Connect your data provider. Plug in your model. You get a working AI investment analyst that you can customize, extend, and build on.

**Why open source**: The code isn't the moat — the expertise to configure, tune, and deploy it for specific workflows is. Open source is distribution. Every builder who adopts the platform becomes a potential customer for the business product.

---

## Three Deliverables

### 1. The Platform (open source packages)

Infrastructure packages that work standalone or together:

| Package | Purpose | Status |
|---------|---------|--------|
| `brokerage-connect` | Unified API for IBKR, Schwab, SnapTrade, Plaid | Published (PyPI v0.2.0) |
| `portfolio-risk-engine` | Factor analysis, optimization, risk scoring, Monte Carlo | Published (PyPI v0.1.0) |
| `fmp-mcp` | 19 MCP tools for market/fundamental data | Published (PyPI v0.1.0) |
| `interactive-brokers-mcp` | 6 MCP tools for IB Gateway access | Published (PyPI v0.1.0) |
| `portfolio-mcp` | 40+ MCP tools — the batteries-included analytical toolkit | Not yet extracted |
| `agent-gateway` | Model-agnostic agent orchestration (Anthropic, OpenAI, local) | Not yet built |

**The "connect any brokerage" story**: `brokerage-connect` + the normalizer builder pattern. Users can connect supported brokerages out of the box, or build a normalizer for any new source via the CLI wizard.

**The "connect any data provider" story**: `fmp-mcp` ships as the default data provider. The provider registry pattern (`providers/registry.py`) makes it pluggable — swap in Bloomberg, Refinitiv, or a custom source.

### 2. The Agent (open source, customizable)

A working AI investment analyst that composes the platform packages. Ships with:

- **Agent runner**: Agentic loop that orchestrates model conversations + tool execution
- **Tool dispatcher**: Routes calls to MCP servers, local tools, approval gates for dangerous ops
- **Memory system**: Structured knowledge store (entity/attribute/value + semantic recall + markdown workspace)
- **Portable config**: System prompts, tool selection, workflow definitions as YAML/JSON — fork and customize
- **Agent gateway**: Model-agnostic — plug in Anthropic, OpenAI, Gemini, or local models (Ollama/vLLM)

**Source**: Most of this exists today in `AI-excel-addin/api/` (agent runner, tool dispatcher, memory store, MCP client, FastAPI gateway). Needs to be extracted, made model-agnostic, and packaged.

**Key differentiator**: This isn't a chatbot wrapper. It's an agent with real tools — it can see your positions, run risk analysis, execute factor decomposition, simulate trades, and generate rebalancing recommendations. The 40+ MCP tools are its hands.

### 3. The Web App (open source, fast-follow — your personal investment OS)

The web app replaces the fragmented experience of using your broker's app for positions, Yahoo Finance for research, a spreadsheet for tracking, and ChatGPT for analysis. Everything in one place, personalized to your portfolio from the moment you connect.

**Not a SaaS dashboard — a personal investment OS.** Think of the relationship like Claude Code (CLI) vs Claude.ai (browser): same model, same tools, different interface. The AI is the primary interface — the dashboard, charts, and controls are visualizations of what the agent knows and can do.

**The portfolio system you didn't realize you needed.** Your trading app is where you execute. This is where you *think*. It's not competing with Schwab on order routing — it's a new category:
- Your trading app shows you positions and P&L. This shows you *why* your portfolio behaves the way it does (factor exposures, concentration risk, correlation).
- Your trading app can't run factor analysis, stress test your portfolio, or tell you what to sell to reduce concentration — this can.
- Your trading app doesn't have an AI that knows your holdings, remembers your investment thesis, and can execute multi-step analytical workflows — this does.
- Skills mean the app proactively does what you'd normally do manually across 3-4 apps (broker + research + spreadsheet + ChatGPT).

**The "works right out of the box" experience**:
1. **Sign up** → land on empty state with guided onboarding
2. **Immediate value**: Upload a CSV, connect via Plaid OAuth, or just tell the agent what you hold in conversation — the agent builds the portfolio
3. **Instant dashboard**: Positions, performance, risk score, sector breakdown — populated the moment data is connected
4. **Progressive depth**: "Want deeper analysis?" → AI chat. "Want live data?" → connect FMP. "Want to trade?" → connect broker API.
5. **Skills surface**: Pre-built workflows as one-click actions — Morning Briefing, Risk Check, Rebalance Analysis (see Skills section below)

**Minimum friction design**: Every step is optional. A user can get value with just a CSV upload and no API keys. Each additional connection (brokerage, data provider, model) unlocks more capability but nothing is gated behind mandatory setup. The progression is:

```
Free tier:
  CSV upload (instant, no API cost to us)
    → Dashboard, risk score, factor analysis, stress testing

Pro tier (covers our API costs):
  → Plaid OAuth (live positions from 10,000+ institutions)
    → Real-time market data (managed FMP key)
      → AI agent + skills + memory + workflows
        → Broker API (live trading, real-time quotes)
```

**Source**: `frontend/` monorepo (4 packages: `@risk/app-platform`, `@risk/chassis`, `@risk/ui`, `@risk/connectors`) + FastAPI backend (`app.py`). Frontend is near-complete — dashboard, portfolio selector, scenario analysis, trading tools, AI chat sidebar, CSV import with AI-assisted normalizer all built.

**Deployment**: Self-hostable (Docker compose) or use our hosted version. Same codebase either way.

---

## Setup Experience

### CLI Setup Wizard

The first-run experience that makes or breaks adoption. A user installs the package, runs the wizard, and within 5 minutes has a working analyst connected to their real data.

```
$ openclaw setup

Welcome to OpenClaw — your AI investment analyst platform.

Step 1/4: Brokerage Connection
  Choose a brokerage to connect:
  > [1] Interactive Brokers (API)
    [2] Schwab (OAuth)
    [3] Plaid (OAuth — supports 10,000+ institutions)
    [4] SnapTrade (OAuth)
    [5] CSV Import (any brokerage — AI-assisted normalizer)
    [6] Skip for now

Step 2/4: Market Data Provider
  > [1] FMP — Financial Modeling Prep (default, requires API key)
    [2] Use hosted API key ($X/month — we manage rate limits and caching)
    [3] Skip for now (limited functionality)
  Enter your FMP API key: ________

Step 3/4: AI Model
  Choose your model provider:
  > [1] Anthropic (Claude) — recommended
    [2] OpenAI (GPT-4)
    [3] Google (Gemini)
    [4] Local model (Ollama / vLLM)
  Enter your API key: ________

Step 4/4: Portfolio Configuration
  Base currency: [USD]
  Portfolio name: [My Portfolio]

Setup complete! Starting your analyst...
  - Brokerage: Connected (IBKR — 47 positions loaded)
  - Market data: FMP (ready)
  - Model: Claude (ready)
  - Dashboard: http://localhost:3000

Type 'openclaw chat' to start a conversation, or open the dashboard.
```

### What the Wizard Produces

- `~/.openclaw/config.yaml` — provider credentials, model config, portfolio settings
- `~/.openclaw/agent.yaml` — agent personality, tool permissions, workflow definitions (forkable)
- MCP server configs wired up (portfolio-mcp, fmp-mcp, optionally ibkr-mcp)
- Local database initialized (SQLite for memory, optionally Postgres for multi-user)

### "Add Your Own" Extensibility

The normalizer builder pattern (already built for brokerages) extends to data providers:

```
$ openclaw add brokerage
  Upload a CSV or connect via API...
  AI analyzes the format → generates normalizer → tests → activates

$ openclaw add data-provider
  Register an endpoint, map fields, configure caching...
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│  SURFACE LAYER — where users interact                     │
│  Web Dashboard  ·  CLI  ·  Claude Code/MCP  ·  Excel     │
├──────────────────────────────────────────────────────────┤
│  AGENT LAYER — the brain                                  │
│  Agent Runner  ·  Memory  ·  Tool Dispatcher              │
│  Agent Gateway (model-agnostic)  ·  Portable Config       │
├──────────────────────────────────────────────────────────┤
│  TOOL LAYER — the hands                                   │
│  portfolio-mcp (40+ tools)  ·  fmp-mcp  ·  ibkr-mcp     │
│  brokerage-connect  ·  portfolio-risk-engine              │
├──────────────────────────────────────────────────────────┤
│  DATA LAYER — the senses                                  │
│  Provider Registry  ·  Normalizers  ·  Transaction Store  │
│  Brokerage APIs  ·  Market Data APIs  ·  SEC EDGAR       │
└──────────────────────────────────────────────────────────┘
```

Each layer is independently useful:
- **Tool layer alone**: Power users install `portfolio-mcp` into Claude Code and go
- **Tool + Agent**: Full analyst experience via CLI or API
- **Full stack**: Web dashboard with everything wired together

---

## The Claude Code / Co-Work Analogy

The two entry points mirror Anthropic's own product strategy:

| Claude Code (CLI) | Our CLI + MCP |
|---|---|
| Install → configure → go | `pip install` → setup wizard → go |
| MCP servers for extensibility | Same MCP servers (portfolio-mcp, fmp-mcp, ibkr-mcp) |
| Skills / custom slash commands | Our skills (workflow definitions, analysis templates) |
| CLAUDE.md for project context | Agent config YAML for portfolio context |
| Power users, developers | Builders, quants, devs (H1) |

| Claude.ai / Co-Work (browser) | Our Web App |
|---|---|
| Zero setup, browser-based | Sign up, upload CSV, start analyzing |
| Same model + tools as CLI | Same agent + tools as CLI |
| Artifacts for rich output | `:::ui-blocks` + `:::artifact` for charts, tables, reports |
| Projects for persistent context | Portfolio memory across sessions |
| Teams/Enterprise for organizations | Business product for institutions |

**Key principle**: The web app is not a dumbed-down version. It's the same agent with a visual surface. A user who starts on the web app and later discovers the CLI gets the same tools, same memory, same skills. No feature cliff between surfaces.

---

## Skills System

Skills are pre-built, composable workflows that bridge the gap between "I don't know what to ask" and "I'm a power user." They're the product's equivalent of Claude Code's slash commands.

### What a Skill Is

A skill is a portable workflow definition (YAML) that specifies:
- **Trigger**: How it's invoked (button, slash command, schedule, condition)
- **Context**: What data to load before running (positions, risk metrics, market data)
- **Steps**: Sequence of tool calls + reasoning
- **Output**: How to present results (chat response, artifact report, dashboard update, notification)

```yaml
# Example: Morning Briefing skill
name: morning_briefing
description: Daily portfolio health check and market update
trigger:
  - button: "Morning Briefing"
  - command: "/briefing"
  - schedule: "0 7 * * 1-5"  # 7am weekdays
context:
  - positions: current
  - risk: portfolio_score
  - market: overnight_moves
steps:
  - tool: get_positions
    summarize: top movers, new positions
  - tool: get_risk_score
    flag_if: score_changed > 5
  - tool: get_market_context
    focus: sectors_matching_portfolio
  - tool: get_events_calendar
    filter: holdings_only, next_5_days
output:
  format: artifact
  title: "Morning Briefing — {date}"
```

### Skill Tiers

**Built-in skills** (ship with the platform):
- Morning Briefing — daily portfolio + market snapshot
- Risk Check — risk score + limit breaches + concentration alerts
- Rebalance Analysis — drift from targets + recommended trades
- Earnings Preview — upcoming earnings for held positions + estimate revisions
- Exit Signal Scan — technical + fundamental signals for positions to review
- Performance Review — period performance vs benchmarks + attribution

**User-created skills** (via the agent or YAML):
- "After every trade, recalculate risk score and check limits"
- "Weekly sector rotation analysis comparing my weights to SPY"
- "Alert me when any position drops >5% intraday"

**Community skills** (post-launch marketplace):
- Contributed by other users, reviewed, installable via CLI or web app

### Skills in the Web App

In the web app, skills surface as:
- **Skill cards** on the dashboard — one-click to run
- **Command palette** in chat — `/briefing`, `/risk-check`, etc.
- **Scheduled runs** — configure in settings, results appear as notifications or artifacts
- **Customizable** — fork any built-in skill, modify parameters, save as your own

This is what makes the web app "work right out of the box" — a new user doesn't need to know what to ask. They see "Morning Briefing" and click it. They see "Risk Check" and click it. Each skill is a guided entry point into the platform's capabilities.

---

## Monetization

### Built Into the Open Source (natural, non-hostile)

**Managed API keys**: Users can bring their own keys for Plaid, FMP, etc. — or pay a small data fee and use ours. We handle rate limits, caching, key rotation. This is the lowest-friction revenue path because it solves a real annoyance (managing API keys and billing relationships with 3+ providers).

```
Step 2/4: Market Data Provider
  > [1] FMP — use your own key (free)
    [2] Use OpenClaw managed key ($X/month)
```

### Two Funnels Into Business

**Funnel A — Bottom-up (web app)**:
Individual at a firm uses Free → upgrades to Pro → shows their team → "Get this for my team" → Business tier. They've already validated the product with their own portfolio. The implementation session customizes it for the firm.

**Funnel B — Developer-led (open source)**:
Developer/quant at a firm uses the open source packages → builds something internally → realizes they need the agent layer or managed infrastructure → reaches out. The open source is the proof of concept.

### Pricing Tiers

```
Free                    →  Pro                      →  Business
"See your portfolio"       "Your AI analyst"            "We build it for you"
```

#### Free Tier — The Hook

The free tier is the dashboard and analytical tools. This is what gets people in the door. No trading app offers this level of analysis for free.

**Gating principle**: Anything that costs us money to serve (LLM API calls, Plaid API calls, real-time market data) goes behind the paywall. The free tier is truly free to operate — zero ongoing API costs on our side.

**Included**:
- Full dashboard (positions, performance, risk score, sector breakdown)
- CSV import (any brokerage format, AI-assisted normalizer)
- Manual analysis tools (what-if, stress test, optimization — via UI, not agent)
- Static/delayed market data (enough to be useful, not real-time)

**Not included** (costs us money to serve):
- AI agent, skills, workflows, memory (LLM API costs)
- Plaid brokerage connection (Plaid API costs per connection)
- Real-time market data (FMP API costs)
- Live broker API connection (infrastructure costs)

**Why this works**: The dashboard alone is more powerful than most retail tools. Users see real value immediately — upload a CSV and get risk scoring, factor analysis, stress testing for free. But every time they think "I wish it could just do this automatically" or "I want to ask it a question" or "I want live data" — that's the upgrade prompt. The free tier creates the desire; the paid tier fulfills it.

#### Pro Tier — The Agent ($X/month)

The agent, skills, and workflows are the premium. This is what no other product offers — an AI analyst that knows your portfolio, remembers your preferences, and can execute multi-step analytical workflows.

**Added over Free** (everything that costs us money to serve):
- Plaid brokerage connection (live positions from 10,000+ institutions — no more CSV uploads)
- AI agent (chat with your portfolio — ask questions, get analysis, request actions)
- Skills library (6+ built-in skills: Morning Briefing, Risk Check, Rebalance, etc.)
- Custom skills (create your own workflows via chat or YAML)
- Scheduled skills (automated morning briefing, weekly risk review, etc.)
- Agent memory (remembers your preferences, past analyses, investment thesis)
- Real-time market data (managed FMP key included)
- Live brokerage API connection (IBKR, Schwab — for real-time quotes + trading)
- Priority support

**Why this is the right gate**: The agent is the highest-value, highest-cost component (LLM API calls, memory storage, real-time data). Gating here aligns cost with value — users who get the most value pay, users who just want a dashboard get it free.

#### Business Tier — White-Glove ($Y/month + implementation)

**The key insight**: A business shouldn't have to "contact sales" and wait for a demo. The trial IS the product. They should be able to:

1. **Try Free themselves** — upload a CSV, see the dashboard, understand the tools
2. **Upgrade to Pro** — connect live data, use the agent, see it work on their portfolio
3. **Hit "I want this for my team"** — not a sales call, an **implementation session**

The upgrade from Pro to Business is a conversation, not a procurement process. The business is already using the product when they decide they want more.

**Added over Pro**:
- **Implementation session**: We connect your data sources, configure the agent for your workflow, set up custom skills
- Multi-user / team access (shared portfolios, role-based permissions)
- Custom data source integration (Bloomberg, internal databases, proprietary models)
- Custom skill development (your specific workflows, encoded as skills)
- Compliance configuration (approval gates, audit trail, risk limits, reporting)
- Deployment options (our cloud, your VPC, on-prem)
- Dedicated support + ongoing optimization
- SLA guarantees

**Pricing model**: Monthly subscription (covers infra + API costs + support) + one-time implementation fee (covers custom setup). The implementation fee is the consulting revenue — but it's positioned as "setup" not "consulting," which reduces friction.

**The funnel**:
```
Free (self-serve)           Pro (self-serve)            Business (assisted)
Sign up, upload CSV    →    Upgrade button         →    "Get this for my team" button
See dashboard               Get AI analyst              → Implementation call (not sales call)
                            Use skills                  → Custom setup in 1-2 sessions
                            Build workflows             → Ongoing optimization
```

**Least friction for business adoption**: The business tier prospect has already used the product. They know it works. The "sales" conversation is actually: "Here's what we saw in your portfolio during the trial. Here's how we'd customize the agent for your team's workflow. Here's what that looks like." It's a demo using *their own data*.

---

## What Needs to Be Built

### Must-Have for Launch

| # | Work Item | Source | Effort | Notes |
|---|-----------|--------|--------|-------|
| 1 | **CLI setup wizard** | New | Medium | The "hello world" — first thing a user touches |
| 2 | **Agent gateway model abstraction** | Refactor `AI-excel-addin/api/` | Medium | Currently Anthropic-only → pluggable adapter for OpenAI, Gemini, local |
| 3 | **Portable agent config** | New | Small | Extract system prompts + tool config + workflow defs to YAML |
| 4 | **`portfolio-mcp` extraction** | `mcp_server.py` → standalone package | Medium | Same pattern as fmp-mcp extraction |
| 5 | **Agent package extraction** | `AI-excel-addin/api/` → standalone | Large | Agent runner, tool dispatcher, memory, MCP client |
| 6 | **Config/secrets management** | Refactor `settings.py` | Small | Move from env vars to `~/.openclaw/config.yaml` for user-facing config |
| 7 | **Documentation** | New | Medium | Setup guide, architecture overview, "add your own brokerage/provider" guide |
| 8 | **Release scrub** | `docs/deployment/RELEASE_SCRUB_FINDINGS.md` | Small | Remove personal data, hardcoded paths (investigation already done) |

### Must-Have for Web App (fast-follow)

| # | Work Item | Source | Effort | Notes |
|---|-----------|--------|--------|-------|
| 9 | **Zero-friction onboarding flow** | Refactor existing onboarding | Medium | CSV upload → instant dashboard. No mandatory API keys. Progressive connection prompts. |
| 10 | **Skills system (built-in set)** | New + existing workflow skills | Medium | 6 built-in skills as YAML definitions + skill runner in agent. Surface as cards + command palette. |
| 11 | **Skills UI in web app** | Frontend work | Medium | Skill cards on dashboard, `/command` palette in chat, settings for scheduling |
| 12 | **Docker compose packaging** | New | Small | One command to run the full stack (frontend + backend + DB) |
| 13 | **Hosted version deployment** | Extend existing PUBLISH_PLAN infra | Medium | Our managed instance — sign up and go, no self-hosting required |

### Nice-to-Have for Launch

| # | Work Item | Notes |
|---|-----------|-------|
| 14 | Example agent configs | "Income investor", "Momentum trader", "Risk-first" presets |
| 15 | Provider template | Documented interface for adding a new data provider |
| 16 | Video walkthrough | 5-min "zero to working analyst" demo |
| 17 | User-created skill builder | In-chat: "make this a skill" → agent generates YAML |

### Post-Launch

| # | Work Item | Notes |
|---|-----------|-------|
| 18 | Workflow engine | Observe user patterns → propose → automate (skills that write themselves) |
| 19 | Skill marketplace | Community-contributed skills, normalizers, provider adapters |
| 20 | Excel add-in polish | Packaged surface for finance professionals |
| 21 | Mobile surface | Telegram bot or native app — same agent, mobile-optimized |

---

## Launch Sequence

### Phase 0: Pre-Launch (current state)
- [x] Core packages on PyPI (fmp-mcp, ibkr-mcp, brokerage-connect, portfolio-risk-engine)
- [x] 3000+ tests, production-hardened backend
- [x] Frontend app with multi-user auth, full feature set
- [x] Agent exists in AI-excel-addin (runner, memory, dispatcher, gateway)
- [ ] Release scrub (investigation done, execution pending)

### Phase 1: Package the Platform
- [ ] Extract `portfolio-mcp` as standalone package (same pattern as fmp-mcp)
- [ ] Extract agent from `AI-excel-addin/api/` into standalone package
- [ ] Make agent gateway model-agnostic (adapter pattern)
- [ ] Portable agent config (YAML-based)
- [ ] CLI setup wizard (the first-run experience)
- [ ] Config/secrets management (`~/.openclaw/`)

### Phase 2: Documentation + Polish
- [ ] README and setup guide (the "5 minutes to working analyst" experience)
- [ ] Architecture docs for contributors
- [ ] "Add your own brokerage" guide (normalizer builder)
- [ ] "Add your own data provider" guide (provider registry)
- [ ] Example agent configurations
- [ ] Release scrub execution

### Phase 3: Launch (CLI + MCP)
- [ ] Choose name + create GitHub org
- [ ] Publish all packages under unified branding
- [ ] Announcement (dev communities, finance Twitter, HN)
- [ ] Monitor adoption, gather feedback, iterate

### Phase 3.5: Web App (fast-follow)
- [ ] Zero-friction onboarding (CSV → instant dashboard, no mandatory setup)
- [ ] Skills system — 6 built-in skills + skill runner
- [ ] Skills UI — cards, command palette, scheduled runs
- [ ] Docker compose for self-hosting
- [ ] Hosted version (our managed instance)
- [ ] Announcement round 2 — "now with a web app, no terminal required"

### Phase 4: Growth
- [ ] Workflow engine (skills that write themselves from observed patterns)
- [ ] Skill marketplace (community-contributed)
- [ ] Community normalizers / provider adapters
- [ ] Institution outreach (the business product)
- [ ] Additional surfaces (Excel add-in, mobile)

---

## Risks + Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| **LLM cost per Pro user** | Heavy users (5+ skill runs/day, long chat) could exceed subscription revenue | Usage tiers or token budget per month. Monitor cost-per-user from day 1. |
| **Free tier too generous** | Users never upgrade — they get enough from CSV + dashboard | Watch upgrade conversion rate. The gap between "click through 4 screens" and "say run my morning check" should be the natural upgrade moment. |
| **Open source cannibalization** | Developers self-host the full stack including agent, never pay | Expected and fine — H1 (builders) are distribution, not revenue. Pro value = managed infra + not running it yourself. |
| **Business tier scope creep** | Implementation becomes ongoing consulting (Bloomberg changes, new workflows) | Recurring subscription covers ongoing optimization budget. Scope implementation sessions clearly. |
| **Category confusion** | Users expect a Schwab replacement, disappointed by missing trading features | Position clearly as "the analytical layer" / "portfolio system you didn't realize you needed" — not a trading app competitor. |

---

## Open Questions

1. **Name**: "OpenClaw" or something else? Drives CLI name, GitHub org, PyPI namespace.
2. **Monorepo vs multi-repo for open source**: Currently local-first monorepo with sync scripts. Do we keep this pattern or restructure for community contribution?
3. **Managed key pricing**: What's the right price point for the data fee tier?
4. **Skill definition format**: YAML (human-readable, easy to share) vs Python (more expressive, harder to sandbox)?
5. **License**: MIT (current) vs Apache 2.0 vs something else?
6. **Hosted version scope**: Full feature parity with self-hosted, or a subset to encourage self-hosting?

---

## Related Docs

- `docs/PRODUCT_ARCHITECTURE.md` — three-layer architecture, market segments, design principles
- `docs/planning/launch/RELEASE_PLAN.md` — package extraction history + Phase 6 (AI Analyst) tasks
- `docs/planning/launch/PUBLISH_PLAN.md` — multi-user production deployment execution
- `~/.openclaw/workspace/MARKET_HYPOTHESIS.md` — H1/H2/H3 market segments, GTM strategy
- `docs/deployment/PACKAGE_DEPLOY_CHECKLIST.md` — package publish workflow
- `docs/deployment/RELEASE_SCRUB_FINDINGS.md` — what needs cleaning before public release

---

*This document captures the open source launch strategy as discussed 2026-03-16. It supersedes the Phase 6 section of `docs/planning/launch/RELEASE_PLAN.md` and aligns with the broader vision in PRODUCT_ARCHITECTURE.md.*
