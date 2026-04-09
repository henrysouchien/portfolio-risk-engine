# Open Source Launch — Gap Analysis & Work Items

> **Created**: 2026-03-16
> **Parent doc**: `docs/planning/launch/OPEN_SOURCE_LAUNCH_STRATEGY.md`
> **Purpose**: Tracks what needs to be built, current state, and prioritization for the open source + web app launch.

---

## Current State Summary

| Component | What Exists | What's Missing |
|---|---|---|
| **User tiers** | DB schema (`public`/`registered`/`paid` column on users table) | Zero enforcement — no middleware, no route gating, no frontend awareness |
| **Billing/payments** | Kartra webhook generates API keys externally | No Stripe, no checkout flow, no self-serve upgrade |
| **Agent gateway** | Working proxy to Anthropic (backend + frontend SSE streaming) | Hardcoded to Claude API contract — not model-agnostic |
| **Skills system** | 40+ MCP tools with agent-format output; 7 workflow skills in Claude Code | No skill definition format, no runner, no UI surface |
| **Docker/self-hosting** | Nothing | No Dockerfile, no compose, no containerization |
| **User-level config** | Env vars + repo-rooted YAML (`config/`) | No `~/.openclaw/` or user-facing config system |
| **Database** | PostgreSQL with 18 migrations, no-DB mode for analysis-only | No SQLite fallback; Postgres required for full features |
| **portfolio-mcp extraction** | 75 modular tools in `mcp_tools/`, server in `mcp_server.py` | Tight coupling to `app_platform.db` and `settings.py` |
| **Agent extraction** | Exists in `AI-excel-addin/api/` (runner, dispatcher, memory, MCP client) | Not packaged, not model-agnostic, not in this repo |
| **CLI setup wizard** | Nothing | Entirely new |
| **Release scrub** | Investigation done (`docs/deployment/RELEASE_SCRUB_FINDINGS.md`) | Execution pending |
| **CSV import (free tier)** | Works — AI-assisted normalizer, multi-format support | Requires session auth (fine for free tier) |
| **Plaid** | Full integration with 24hr cache, webhook support | Behind auth but NOT behind tier — needs payment gate |
| **Frontend tier UI** | Nothing | No upgrade prompts, no feature gating in UI, no tier display |

---

## Prioritized Work Items

### Phase A: Do Now (while frontend work is active)

These are foundational — everything else builds on them.

#### A1. Tier Enforcement Middleware

**What**: Backend decorator/middleware that gates routes and tools by user tier.

**Why now**: This is the plumbing that every monetization feature depends on. Small, surgical — touches routes, not business logic.

**Current state**:
- `users.tier` column exists: `VARCHAR(50) DEFAULT 'public'` (values: `public`, `registered`, `paid`)
- `@require_db` decorator pattern already exists in `mcp_tools/common.py` — same pattern applies
- Agent API uses separate Bearer token auth (`AGENT_API_KEY`), independent of user tier
- No tier checks anywhere in the codebase

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

**Depends on**: A1 (tier enforcement), A2 (frontend tier awareness)

**Plan doc**: `docs/planning/STRIPE_INTEGRATION_PLAN.md` (to be created)

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

#### B4. Portfolio-MCP Extraction

**What**: Extract `mcp_server.py` + `mcp_tools/` into a standalone `portfolio-mcp` package.

**Current entanglement**:
- 75 tool imports from `mcp_tools/` (these move with extraction — internal)
- `app_platform.db.pool.close_pool()` (DB lifecycle management)
- `settings.py` → `get_default_user_context()`, `format_missing_user_error()`
- `utils.logging` → `portfolio_logger`

**Scope**:
- Create `portfolio_mcp/` package directory
- Move `mcp_tools/` wholesale into package
- Create `portfolio_mcp/server.py` entry point (same pattern as `fmp/server.py`)
- Abstract DB dependency (optional Postgres, graceful degradation)
- Abstract settings into package-level config
- Sync script: `scripts/sync_portfolio_mcp.sh`
- PyPI publish

**Depends on**: None (can start anytime, but lower priority than tier/billing)

**Plan doc**: `docs/planning/PORTFOLIO_MCP_EXTRACTION_PLAN.md` (to be created)

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

**Depends on**: C1 (model abstraction), B4 (portfolio-mcp extraction)

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
A1 (Tier Enforcement) ──────┐  ✅ DONE (90f52fe1)
A2 (Frontend Tier UI) ──────┤  ✅ DONE (948f38f4)
                             ├─→ B1 (Stripe) ─→ Web App Launch
A3 (Skills Design) ─────────┤  ✅ PLANNED (Codex PASS)
                             ├─→ B3 (Skills Impl)
                             │
B2 (Docker Compose) ─────────→ Self-Hosting Ready
                             │
B4 (portfolio-mcp Extract) ──┤
                             ├─→ C2 (CLI Wizard) ─→ Open Source CLI Launch
C1 (Gateway Abstraction) ────┤
                             ├─→ C3 (Agent Extraction)
                             │
C4 (Release Scrub) ──────────→ Public Repo Ready
```

---

## Plan Doc Tracker

| ID | Plan Doc | Status |
|----|----------|--------|
| A1 | `docs/planning/TIER_ENFORCEMENT_PLAN.md` | **DONE** — `90f52fe1`. 4 steps, ~30 paid endpoints, gateway context-aware check. 3908 tests. Live verified. |
| A2 | `docs/planning/FRONTEND_TIER_AWARENESS_PLAN.md` | **DONE** — `948f38f4`. 7 steps, useTier + UpgradePrompt + 403 handling + UI gating. 607 frontend tests. |
| A3 | `docs/planning/SKILLS_SYSTEM_DESIGN.md` | **Planned** — architecture spec, 3 built-in skills defined. Codex PASS (5 rounds). |
| B1 | `docs/planning/STRIPE_INTEGRATION_PLAN.md` | Not started |
| B2 | `docs/planning/DOCKER_COMPOSE_PLAN.md` | Not started |
| B3 | `docs/planning/SKILLS_IMPLEMENTATION_PLAN.md` | Not started |
| B4 | `docs/planning/PORTFOLIO_MCP_EXTRACTION_PLAN.md` | Not started |
| C1 | `docs/planning/AGENT_GATEWAY_ABSTRACTION_PLAN.md` | Not started |
| C2 | `docs/planning/CLI_SETUP_WIZARD_PLAN.md` | Not started |
| C3 | `docs/planning/AGENT_EXTRACTION_PLAN.md` | Not started |
| C4 | `docs/deployment/RELEASE_SCRUB_FINDINGS.md` | Investigation done, execution pending |

---

*This document is the execution companion to `docs/planning/launch/OPEN_SOURCE_LAUNCH_STRATEGY.md`. Strategy doc = what and why. This doc = what's missing and in what order.*
