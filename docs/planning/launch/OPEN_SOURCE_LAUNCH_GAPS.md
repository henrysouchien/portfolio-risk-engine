# Open Source Launch — Gap Analysis & Work Items

> **Created**: 2026-03-16
> **Last refreshed**: 2026-05-21
> **Parent doc**: `docs/planning/launch/OPEN_SOURCE_LAUNCH_STRATEGY.md`
> **Purpose**: Tracks what needs to be built, current state, and prioritization for the open source + web app launch.

---

## Current State Summary

| Component | What Exists | What's Missing |
|---|---|---|
| **User tiers** | DB schema + A1 enforcement (`@require_tier`/`create_tier_dependency`) shipped `90f52fe1`; ~30 paid endpoints gated across `routes/plaid.py`, `routes/snaptrade.py`, `routes/income.py`, `routes/baskets_api.py`, etc.; gateway proxy context-aware tier check | — |
| **Billing/payments** | Kartra webhook generates API keys externally; `STRIPE_INTEGRATION_PLAN.md` filed | No Stripe checkout/webhook code; **blocked by V1.1 pricing decision** |
| **Agent gateway** | **Multi-user gateway live in prod** (Hank at `hank.investments` since 2026-05-04); strict-mode auth + BYOK + channel cutover (Excel/web/Telegram/CLI/TUI/autonomous cron) live-verified 2026-05-16; `CompletionProvider` protocol abstracts non-chat AI tasks (provider-swappable via `LLM_PROVIDER`) | Chat path still Anthropic-shaped — no `OpenAIGatewayProvider`/`LocalGatewayProvider` adapters (C1) |
| **Skills system** | A3 design DONE (Codex PASS x5); `WORKFLOW_SKILLS_PLAN`, `WORKFLOW_SKILLS_PHASE4_PLAN`, `WORKFLOW_SKILLS_STOCK_RESEARCH_PLAN` all shipped (in `completed/`); B9 Vals Config D `config_d_hank_skills.py` wires skills into wrapper | Surface reframe (V2.P6) deferred to V1-end; user-authored YAML skill format not built |
| **Docker/self-hosting** | `DOCKER_COMPOSE_PLAN.md` filed | No Dockerfile, no compose, no containerization (B2) |
| **User-level config** | Env vars + repo-rooted YAML (`config/`); **SSM hydration shipped** — 16 keys live in `/risk-module/{dev,prod}/{shared,broker}/` SSM (KMS-encrypted) via `bootstrap_env`; `.env` reserved for infra/personal/AWS-bootstrap | No `~/.openclaw/` or user-facing config system (C2) |
| **Database** | PostgreSQL with 47 migrations, no-DB mode for analysis-only | No SQLite fallback; Postgres required for full features |
| **portfolio-mcp extraction** | **114 tools** post V2.P10 split (verified 2026-05-21 via `grep -c "@mcp\.tool()" mcp_server.py`); `research-mcp` spun out as 22-tool sibling (`mcp_server_research.py`, 2026-05-04); 23 tools internal-only via `mcp_tools/_tier_policy.py:7` `INTERNAL_ONLY_PORTFOLIO_TOOLS`; `app_platform`, `fmp-mcp`, `brokerage-connect`, `portfolio-risk-engine` already published to PyPI as dependencies | **OSS-extraction direction superseded** by `HANK_PLATFORM_MVP_PLAN.md` (2026-05-21) for the independent-investor audience — pivot to hosted MCP bundle (`claude mcp add --transport http`) with curated allowlist instead of pip install. B4 plan remains valid for a self-host audience (devs, sovereignty-minded users) but deprioritized |
| **Agent extraction** | `agent-gateway` source extracted to `AI-excel-addin/api/`, published to PyPI as `ai-agent-gateway`, deployed via `agent-gateway-dist` (sync via `scripts/sync_agent_gateway.sh`, publish via `scripts/publish_agent_gateway.sh`) | Not yet packaged as standalone `openclaw-agent` consumer-facing wrapper; runner/dispatcher/memory still coupled to AI-excel-addin shape (C3) |
| **CLI setup wizard** | Nothing | Entirely new (C2) |
| **Release scrub** | Investigation done (`docs/planning/PUBLIC_RELEASE_SCRUB_PLAN.md`, `docs/deployment/RELEASE_SCRUB_FINDINGS.md`) | Execution pending (C4) |
| **CSV import (free tier)** | Works — AI-assisted normalizer, multi-format support | Requires session auth (fine for free tier) |
| **Plaid** | Full integration with 24hr cache, webhook support; **tier-gated** via A1 (`_require_paid_user` on ~5 routes in `routes/plaid.py`) | — (functional gating live; payment flow waits on B1 Stripe) |
| **Frontend tier UI** | A2 shipped `948f38f4` — `useTier()` hook (`frontend/packages/chassis/src/hooks/useTier.ts`), `UpgradePrompt` component, `UpgradeRequiredError` 403 split, tier in auth store; 607 frontend tests | Pricing page + Stripe checkout UI (waits on B1) |

---

## Prioritized Work Items

### Phase A: Do Now (while frontend work is active)

These are foundational — everything else builds on them.

#### A1. Tier Enforcement Middleware

**What**: Backend decorator/middleware that gates routes and tools by user tier.

**Why now**: This is the plumbing that every monetization feature depends on. Small, surgical — touches routes, not business logic.

**Current state (post A1 SHIPPED `90f52fe1` 2026-04+):**
- `users.tier` column exists: `VARCHAR(50) DEFAULT 'public'` (values: `public`, `registered`, `paid`, `business`)
- `create_tier_dependency` (`app_platform/auth/dependencies.py:14`) is the active **cookie-session** FastAPI dependency
- `_require_paid_user` gate live on ~30 paid endpoints across `routes/plaid.py`, `routes/snaptrade.py`, `routes/income.py`, `routes/baskets_api.py`, etc.
- Gateway proxy context-aware tier check (`purpose=normalizer` exempt, `purpose=chat` gated)
- Frontend `useTier()` + `UpgradePrompt` + 403 split shipped via A2 (`948f38f4`)
- **Open gap**: cookie-session auth does NOT cover bearer-token auth for remote MCP clients — that's HP1 Phase 0.1's net-new work

**Scope**:
- `@require_tier("pro")` decorator for backend routes (mirrors `@require_db` pattern)
- Gate Plaid routes (API cost to us)
- Gate agent/chat routes (LLM cost to us)
- Gate real-time market data endpoints (FMP cost to us)
- Free tier: CSV import, dashboard, static analysis endpoints — ungated
- Admin override for testing

**Key files to modify**:
- `mcp_tools/common.py` — add `@require_tier` decorator
- `routes/plaid.py` — add tier gate
- `routes/gateway_proxy.py` — add tier gate
- `routes/agent_api.py` — add tier gate
- `services/auth_service.py` — expose tier in session response

**Plan doc**: `docs/planning/TIER_ENFORCEMENT_PLAN.md` (to be created)

---

#### A2. Frontend Tier Awareness

**What**: UI knows the user's tier and conditionally shows features vs upgrade prompts.

**Why now**: You're actively working on the frontend. Adding tier awareness now avoids rework later when gating is enforced.

**Current state**:
- Auth store (`authStore.ts`) has user object but no tier field
- No conditional rendering based on tier anywhere in frontend
- No upgrade prompts or pricing UI

**Scope**:
- Expose `tier` in auth session response (backend) and auth store (frontend)
- `useTier()` hook or selector for components to check tier
- Conditional rendering: agent chat → "Upgrade to Pro" for free users
- Conditional rendering: Plaid connection → "Upgrade to Pro" for free users
- Upgrade prompt component (reusable, links to billing)
- Settings page: show current tier, upgrade button

**Key files to modify**:
- Backend: session response in `services/auth_service.py` or auth routes
- Frontend: `authStore.ts` — add tier to user type
- Frontend: new `UpgradePrompt` component
- Frontend: AI chat panel — conditional mount based on tier
- Frontend: Plaid connection UI — conditional based on tier

**Plan doc**: `docs/planning/FRONTEND_TIER_AWARENESS_PLAN.md` (to be created)

---

#### A3. Skills System Design

**What**: Define the skill data model, runner interface, and built-in skill set. Not full implementation — the architecture and format spec.

**Why now**: Skills are a core product feature (Pro tier differentiator). Getting the shape right early avoids rework. Also informs how the agent gateway and frontend skill UI are built.

**Current state**:
- 40+ MCP tools with agent-format output (snapshots + interpretive flags)
- 7 workflow skills exist as Claude Code slash commands (not portable)
- `workflow_actions` DB table exists for audit trail (action logging, not skill execution)
- No skill definition format, no runner, no YAML templates

**Scope** (design doc, not implementation):
- Skill definition YAML schema (trigger, context, steps, output)
- Skill runner interface (how a skill invokes MCP tools in sequence)
- Built-in skill catalog (6 initial: Morning Briefing, Risk Check, Rebalance, Earnings Preview, Exit Signal Scan, Performance Review)
- Skill storage (where do skill definitions live — config files, DB, or both?)
- Skill execution model (synchronous chat response, background job, scheduled cron)
- Frontend surface spec (skill cards, command palette, schedule configuration)
- Relationship to agent gateway (skills as structured prompts vs standalone execution)

**Key questions to resolve**:
- Are skills "structured prompts that the agent executes" or "hardcoded tool sequences"?
- How does a user create a custom skill — via chat ("make this a skill"), via YAML, or both?
- Where do skill results surface — chat, artifact, notification, dashboard widget?

**Plan doc**: `docs/planning/SKILLS_SYSTEM_DESIGN.md` (to be created)

---

### Phase B: Do Next (before web app launch)

#### B1. Stripe Integration + Checkout Flow

**What**: Self-serve upgrade from Free → Pro. Stripe checkout, webhook for tier update, subscription management.

**Scope**:
- Stripe checkout session for Pro tier
- Webhook handler: `checkout.session.completed` → update `users.tier` to `paid`
- Webhook handler: `customer.subscription.deleted` → downgrade to `public`
- Frontend: pricing page, upgrade button, billing management link
- Handle trial periods, cancellation, reactivation

**Depends on**: A1 (tier enforcement — SHIPPED), A2 (frontend tier awareness — SHIPPED), **V1.1 pricing decision (BLOCKING)**, **HP1 SKU model co-design** (current single Free/Pro plan is incompatible with HP1 multi-SKU + premium add-ons + possible usage billing — refresh required)

**Plan doc**: `docs/planning/STRIPE_INTEGRATION_PLAN.md` — **filed but needs refresh** for HP1 multi-SKU model before implementation

---

#### B2. Docker Compose for Self-Hosting

**What**: One command to run the full stack locally.

**Scope**:
- `docker-compose.yml`: PostgreSQL + FastAPI backend + frontend build + nginx
- Environment variable template (`.env.example`)
- Volume mounts for persistent data (DB, config, uploads)
- Health checks
- README for self-hosting setup

**Plan doc**: `docs/planning/DOCKER_COMPOSE_PLAN.md` (to be created)

---

#### B3. Skills Implementation (Built-in Set)

**What**: Implement the skill runner and 6 built-in skills based on the A3 design.

**Scope**:
- Skill runner (executes skill YAML → MCP tool calls → formatted output)
- 6 built-in skills: Morning Briefing, Risk Check, Rebalance Analysis, Earnings Preview, Exit Signal Scan, Performance Review
- Skill registration and discovery
- Frontend skill cards + command palette

**Depends on**: A3 (skills design), A1 (tier gating — skills are Pro-only)

**Plan doc**: `docs/planning/SKILLS_IMPLEMENTATION_PLAN.md` (to be created)

---

#### B4. Portfolio-MCP Extraction — SUPERSEDED 2026-05-21

**Status**: Superseded by **HP1 (Hank Platform MVP)** for the independent-investor audience — see `docs/planning/HANK_PLATFORM_MVP_PLAN.md`. B4 framing (OSS pip-install) remains valid for a self-host audience (developers, sovereignty-minded users) but is deprioritized.

**Why superseded**: independent investors don't want pip install + bring-your-own-Postgres + Docker compose. They want one `claude mcp add --transport http` command pointing at a hosted endpoint. HP1 reframes "extract portfolio-mcp" as "expose a curated, scope-tiered subset of portfolio-mcp + 7 sibling MCPs via a hosted MCP-protocol aggregation gateway." Tool count is 114 (not 75 — V2.P10 split happened since this plan was filed), with ~23 internal-only enumerated in `mcp_tools/_tier_policy.py`.

**Historical content** (preserved for self-host-audience reference):

- Tool imports from `mcp_tools/` (now 114, was 75)
- `app_platform.db.pool.close_pool()` — DB lifecycle management
- `settings.py` → `get_default_user_context()`, `format_missing_user_error()`
- `utils.logging` → `portfolio_logger`

Original scope was: package directory, move `mcp_tools/` wholesale, sync script + PyPI publish. See `docs/planning/PORTFOLIO_MCP_EXTRACTION_PLAN.md` for the full historical plan if/when self-host audience is reprioritized.

**Plan doc (historical)**: `docs/planning/PORTFOLIO_MCP_EXTRACTION_PLAN.md` — marked SUPERSEDED in its own header.

---

### Phase C: Do Later (for open source CLI launch)

#### C1. Agent Gateway Model Abstraction

**What**: Make the gateway proxy model-agnostic (Anthropic, OpenAI, Gemini, local models).

**Current state**: Gateway hardcoded to Anthropic API contract:
- Session init: `POST {gateway_url}/api/chat/init`
- Chat streaming: `POST {gateway_url}/api/chat` (SSE)
- Tool approval: `POST {gateway_url}/api/chat/tool-approval`
- Frontend `GatewayClaudeService` maps Claude-specific event types

**Scope**:
- `AIGatewayProvider` protocol interface
- `AnthropicGatewayProvider` (extract current implementation)
- `OpenAIGatewayProvider` adapter
- `LocalGatewayProvider` adapter (Ollama/vLLM)
- Common event type contract (translate between provider-specific formats)
- Config-driven provider selection
- Frontend: rename `GatewayClaudeService` → `GatewayChatService`, add model selection

**Plan doc**: `docs/planning/AGENT_GATEWAY_ABSTRACTION_PLAN.md` (to be created)

---

#### C2. CLI Setup Wizard + User Config

**What**: `openclaw setup` wizard that walks user through brokerage, data, model, and portfolio config.

**Scope**:
- CLI tool (Click or similar)
- Interactive wizard (brokerage → data provider → model → portfolio)
- Produces `~/.openclaw/config.yaml` (credentials, model config, portfolio settings)
- Produces `~/.openclaw/agent.yaml` (agent personality, tool permissions, workflows)
- MCP server auto-configuration
- DB initialization (SQLite for simple, Postgres for full)

**Depends on**: C1 (model abstraction). **NOT** dependent on B4 extraction anymore — B4 is superseded by HP1 for the investor audience; CLI wizard is for the self-host audience, which keeps the original B4 framing valid if/when that audience is re-prioritized.

**Plan doc**: `docs/planning/CLI_SETUP_WIZARD_PLAN.md` (to be created)

---

#### C3. Agent Extraction from AI-Excel-Addin

**What**: Extract the agent runner, tool dispatcher, memory system, and MCP client from `AI-excel-addin/api/` into a standalone package.

**Scope**:
- Agent runner (agentic loop, multi-turn orchestration)
- Tool dispatcher (MCP, local, approval gates)
- Memory system (SQLite EAV store, embeddings, semantic recall, markdown sync)
- MCP client manager (server discovery, connection lifecycle)
- Model-agnostic (uses gateway abstraction from C1)
- Package as `openclaw-agent` or similar

**Depends on**: C1 (model abstraction)

**Plan doc**: `docs/planning/AGENT_EXTRACTION_PLAN.md` (to be created)

---

#### C4. Release Scrub Execution

**What**: Remove personal data, hardcoded paths, API key references from codebase.

**Current state**: Investigation complete — `docs/deployment/RELEASE_SCRUB_FINDINGS.md` + `docs/deployment/PUBLIC_RELEASE_EXCLUSION_CHECKLIST.md` detail what needs cleaning.

**Scope**: Execute the findings. 1-2 sessions.

**Plan doc**: Already exists — `docs/deployment/RELEASE_SCRUB_FINDINGS.md`

---

## Dependency Graph

```
A1 (Tier Enforcement) ──────┐  ✅ DONE (90f52fe1) [cookie-session; bearer-token TBD in HP1 Phase 0]
A2 (Frontend Tier UI) ──────┤  ✅ DONE (948f38f4)
                             ├─→ B1 (Stripe) ─┬─→ Web App Launch (Hank consumer)
A3 (Skills Design) ─────────┤  ✅ PLANNED (Codex PASS)  │
                             ├─→ B3 (Skills Impl) — partially shipped (WORKFLOW_SKILLS_*)
                             │                          │
                             │                          └─→ HP1 Phase 0 (bearer auth + billing co-design)
                             │                                   │
                             │                                   └─→ HP1 Phase 1 (hosted MCP) ─→ Hank Platform Launch
                             │                                   │
                             │                                   └─→ HP1 Phase 2 (Premium add-on only) ─→ Platform v1.5
                             │
B2 (Docker Compose) ─────────→ Self-Hosting Ready
                             │
B4 (portfolio-mcp Extract) ──[SUPERSEDED BY HP1 for investor audience; valid for self-host audience]
                             │
                             ├─→ C2 (CLI Wizard) ─→ Open Source CLI Launch
C1 (Gateway Abstraction) ────┤
                             ├─→ C3 (Agent Extraction) — agent-gateway already published to PyPI
                             │
C4 (Release Scrub) ──────────→ Public Repo Ready
```

---

## Plan Doc Tracker

| ID | Plan Doc | Status |
|----|----------|--------|
| A1 | `docs/planning/TIER_ENFORCEMENT_PLAN.md` | **DONE** — `90f52fe1`. Cookie-session auth; bearer-token for external MCP clients added in HP1 Phase 0 |
| A2 | `docs/planning/FRONTEND_TIER_AWARENESS_PLAN.md` | **DONE** — `948f38f4`. 7 steps, useTier + UpgradePrompt + 403 handling. 607 frontend tests |
| A3 | `docs/planning/SKILLS_SYSTEM_DESIGN.md` | **Planned** — architecture spec, Codex PASS (5 rounds). Implementation partially shipped (`WORKFLOW_SKILLS_*` in `completed/`) |
| B1 | `docs/planning/STRIPE_INTEGRATION_PLAN.md` | **Needs refresh** for HP1 multi-SKU / premium add-on / usage-billing model. Current plan is single Free/Pro only — incompatible with HP1 Q1/Q2/Q4/Q5 |
| B2 | `docs/planning/DOCKER_COMPOSE_PLAN.md` | Not started — relevant for self-host audience only |
| B3 | `docs/planning/SKILLS_IMPLEMENTATION_PLAN.md` | **Partially shipped** — `WORKFLOW_SKILLS_PLAN`, `WORKFLOW_SKILLS_PHASE4_PLAN`, `WORKFLOW_SKILLS_STOCK_RESEARCH_PLAN` in `completed/`. Surface reframe (V2.P6) deferred |
| B4 | `docs/planning/PORTFOLIO_MCP_EXTRACTION_PLAN.md` | **SUPERSEDED 2026-05-21** by HP1 for investor audience; B4 framing valid for self-host audience but deprioritized |
| HP1 | `docs/planning/HANK_PLATFORM_MVP_PLAN.md` | **Plan r6 BUSINESS MODEL LOCKED + CODEX R7 PASS 2026-05-25** (review history: R1 FAIL 10 → R2 FAIL 8 → R3 PASS 6 P2 → R4 FAIL 1 P1 + 5 P2 → R5 PASS 5 P2 → R6 PASS 1 P2 → R7 PASS 4 P2). Architectural simplification: Bridge dropped (user's MCP client IS local file layer with signed-download fallback); model-engine moved to AI-excel-addin (avoids upload privacy issue); 2-class exposure with 4 scope sub-tags. Business model: HP1 = PRIMARY paid product (Standard/Pro tiered, per-seat individual or per-firm institutional); Hank consumer = paid showcase/onboarding surface with intentional friction (consulting + feedback line) → credit-based self-serve at vNext (outcome-named bundles); HP2 OSS = top-of-funnel distribution; Fifth Avenue AI = high-touch services revenue line. Phase 0 (bearer-token auth + manifest including `get_skill()` + brokerage user-account-binding + Redis counter rate limits + billing schema co-design) → Phase 1 (hosted MCP launch) → Phase 2 (Premium scope inside Pro: jobs+alerts+timesfm). **Q1/Q2/Q4/Q5 RESOLVED via r6**; still open Q3 (trading default), Q6 (naming), Q7-Q9 (Phase 0 architectural), exact $/mo (V1.1 dependent). Audience validation gates Phase 0 start |
| C1 | `docs/planning/AGENT_GATEWAY_ABSTRACTION_PLAN.md` | **Partially** — `CompletionProvider` protocol shipped for non-chat AI tasks. Gateway chat path still Anthropic-shaped |
| C2 | `docs/planning/CLI_SETUP_WIZARD_PLAN.md` | Not started |
| C3 | `docs/planning/AGENT_EXTRACTION_PLAN.md` | **Partially** — `agent-gateway` published to PyPI as `ai-agent-gateway` via `agent-gateway-dist`. Standalone consumer-facing wrapper TBD |
| C4 | `docs/deployment/RELEASE_SCRUB_FINDINGS.md` | Investigation done, execution pending (relevant for self-host audience only) |

---

*This document is the execution companion to `docs/planning/launch/OPEN_SOURCE_LAUNCH_STRATEGY.md`. Strategy doc = what and why. This doc = what's missing and in what order.*
