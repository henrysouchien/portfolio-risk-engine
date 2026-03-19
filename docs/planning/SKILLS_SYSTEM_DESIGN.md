# A3: Skills System Design

> **STATUS: SUPERSEDED — DO NOT IMPLEMENT.** Both this doc and `docs/specs/skill-loader-spec.md` are superseded. See `docs/planning/WORKFLOW_GUIDES_PLAN.md` for the replacement approach: workflow guides as domain knowledge attached to portfolio-mcp tools, not a standalone skill system.

> **Created**: 2026-03-16
> **Parent**: `docs/OPEN_SOURCE_LAUNCH_GAPS.md` (item A3)
> **Goal**: Design the skill system for the open source launch. Builds on existing `docs/specs/skill-loader-spec.md` (Codex-approved) and `docs/planning/WORKFLOW_SKILLS_PLAN.md`.

---

## Existing Work

**This plan does NOT start from scratch.** Two prior documents define the skills architecture:

1. **`docs/specs/skill-loader-spec.md`** (Codex-approved, 5 review rounds):
   - `SKILL.md` + YAML frontmatter is the source of truth
   - Two execution modes: Claude Code (interactive) and CLI/API runner (headless)
   - Parser, loader, runner, CLI — all specified with code outlines
   - Skills live in-repo at `skills/skill_defs/<name>/SKILL.md`
   - Tool allowlist enforcement, multi-server support, `tools/list` discovery
   - Stock analysis skill fully defined as Phase 1

2. **`docs/planning/WORKFLOW_SKILLS_PLAN.md`**:
   - 2 portfolio workflow skills (allocation-review, risk-review)
   - Uses `mcp_tools/audit.py` workflow action trail for recommendation/execution state
   - Skills stored as markdown in `api/memory/workspace/memory/skills/` (AI-excel-addin pattern)

**What this document adds**: How skills surface in the web app for the open source launch, and the minimal set of changes needed to ship.

---

## Design Decisions

### D1: SKILL.md + YAML frontmatter is the format

Per the skill-loader-spec. NOT pure YAML files. The markdown body is the prompt — human-readable and AI-interpretable. The YAML frontmatter carries structured metadata (inputs, servers, tools, steps, output format).

```
skills/skill_defs/<name>/SKILL.md
  ├── YAML frontmatter (inputs, servers, tools, steps)
  └── Markdown body (prompt instructions for the agent)
```

### D2: Minimal first pass — validate format + runtime before building infrastructure

Ship the skill-loader-spec's Phase 1-2 first:
1. Parser + loader + runner (from spec)
2. 2-3 built-in skills
3. Verify via CLI + Claude Code

Defer: Web app integration (requires gateway skill-loading mechanism), DB-backed user skills, CRUD APIs, scheduling, dashboard skill cards, marketplace. Build those after the format and runtime are proven with real usage.

### D3: Runner uses MCP `tools/list` for discovery, not a hand-maintained registry

Per the skill-loader-spec, the runner connects to MCP servers declared in the skill's frontmatter, calls `tools/list` on each, and filters to the declared allowlist. No separate tool catalog to maintain.

### D4: Web identity bridge — explicit gap, solve incrementally

MCP tools resolve user via `RISK_MODULE_USER_EMAIL` env var. This works for:
- Claude Code (local, single user) ✓
- CLI runner (local, single user) ✓
- Web app (multi-user) ✗

For the web app, the gateway proxy already handles user context. When skills run through the gateway (as structured prompts to the agent), the agent's session already has the user's portfolio context. The env-var limitation only matters for headless/scheduled skill execution — defer that to B3 (Skills Implementation).

### D5: Audit trail is per-workflow, not a general skill execution log

`mcp_tools/audit.py` provides `record_workflow_action()`, `update_action_status()`, and `get_action_history()` for tracking recommendations and decisions within specific workflows. The allowlist (`_ALLOWED_WORKFLOWS`) only supports specific names: `hedging`, `scenario_analysis`, `strategy_design`, `risk_review`, `allocation_review`, `stock_research`.

**For recommendation-style skills** (allocation-review, risk-review): Use the audit trail as designed. These skills record recommendations and track execution status. The allowlist already includes them (or can be extended trivially).

**For informational skills** (morning-briefing, portfolio-checkup, stock-analysis): These produce reports, not recommendations. They have no execution state to track. **No execution history in the first pass.** If we want run history later, add it as a lightweight log (not by repurposing `workflow_actions`).

---

## What to Build (Minimal First Pass)

### Phase 1: Core Infrastructure (from skill-loader-spec)

Already specified in detail in `docs/specs/skill-loader-spec.md`. Implementation only — no design work.

| File | Purpose | From spec |
|------|---------|-----------|
| `skills/__init__.py` | Package exports | Yes |
| `skills/models.py` | `Skill`, `SkillInput`, `SkillStep`, `ServerConfig` dataclasses | Yes |
| `skills/parser.py` | Parse SKILL.md → `Skill` object | Yes |
| `skills/loader.py` | Discover + load skills from `skill_defs/` | Yes |
| `skills/runner.py` | Claude API agentic loop with MCP server connections | Yes |
| `skills/cli.py` | CLI entry point (`python3 -m skills.cli`) | Yes |

### Phase 2: Built-in Skills (3 to start)

| Skill | Location | Status | Notes |
|-------|----------|--------|-------|
| `stock-analysis` | `skills/skill_defs/stock-analysis/SKILL.md` | Defined in spec | 7-step SIA framework, 3 MCP servers |
| `portfolio-checkup` | `skills/skill_defs/portfolio-checkup/SKILL.md` | Defined in spec Phase 3 | Positions + risk + factor + performance |
| `morning-briefing` | `skills/skill_defs/morning-briefing/SKILL.md` | Defined in spec Phase 3 | Market context + portfolio + news + events |

Each skill is a SKILL.md file following the frontmatter schema from the spec.

### Phase 3: Web App Integration — DEFERRED

Web app skill execution requires solving a mechanism that doesn't exist today: the gateway proxy only forwards `messages` and `context` — it has no way to load SKILL.md files or resolve `/skill-name` into a structured prompt.

**Options for when we build this** (not now):
- **Option A**: Inject skill prompt into chat message — backend endpoint reads SKILL.md, prepends it to the user message before forwarding to gateway. Simplest.
- **Option B**: Backend skill loader — new `/api/skills/{name}/execute` endpoint that runs the skill runner directly (bypassing the gateway chat). More isolated but duplicates the runner.
- **Option C**: Give the gateway agent access to SKILL.md files via its system prompt or a skill-discovery MCP tool.

**Decision**: Defer until Phase 1-2 are validated via CLI + Claude Code. The web integration design depends on which execution model works best in practice.

The frontend chat command palette is also deferred — it only has value once web execution works.

---

## Built-in Skill Definitions

### morning-briefing

```yaml
---
name: morning-briefing
description: Daily portfolio health check with market context and upcoming events.
inputs: {}  # no required inputs — uses current portfolio
servers:
  portfolio-mcp:
    command: "${RISK_MODULE_ROOT}/mcp_server.py"
    env: [RISK_MODULE_USER_EMAIL]
    tools: [get_positions, get_risk_score, get_performance]
  fmp-mcp:
    command: "${RISK_MODULE_ROOT}/fmp_mcp_server.py"
    env: [RISK_MODULE_USER_EMAIL]
    tools: [get_market_context, get_news, get_events_calendar]
steps:
  - title: Portfolio Snapshot
    tools: [get_positions]
  - title: Risk Check
    tools: [get_risk_score]
  - title: Market Context
    tools: [get_market_context, get_news]
  - title: Upcoming Events
    tools: [get_events_calendar]
  - title: Summary
    tools: []
output:
  format: markdown
  required_sections: [Portfolio Snapshot, Risk Status, Market Context, Upcoming Events, Action Items]
---
```

### portfolio-checkup

```yaml
---
name: portfolio-checkup
description: Comprehensive portfolio analysis — risk, factors, performance, and recommendations.
inputs: {}
servers:
  portfolio-mcp:
    command: "${RISK_MODULE_ROOT}/mcp_server.py"
    env: [RISK_MODULE_USER_EMAIL]
    tools: [get_positions, get_risk_analysis, get_factor_analysis, get_performance, get_income_projection]
steps:
  - title: Current Positions
    tools: [get_positions]
  - title: Risk Analysis
    tools: [get_risk_analysis]
  - title: Factor Exposure
    tools: [get_factor_analysis]
  - title: Performance Review
    tools: [get_performance]
  - title: Income Projection
    tools: [get_income_projection]
  - title: Summary and Recommendations
    tools: []
output:
  format: markdown
  required_sections: [Positions Summary, Risk Assessment, Factor Exposure, Performance, Income Outlook, Recommendations]
---
```

(stock-analysis already fully defined in skill-loader-spec)

---

## What to Defer

| Item | Why defer |
|------|-----------|
| DB-backed user skills (`user_skills` table) | Validate format + runtime first |
| CRUD API endpoints (`/api/skills/*`) | No user-created skills yet |
| Scheduled skill execution (cron) | Requires web identity bridge (D4) |
| Dashboard skill cards UI | Validate via chat command palette first |
| Skill marketplace | Community feature, way post-launch |
| User skill creation via chat ("make this a skill") | Needs proven format first |
| Skill execution history for informational skills | Not needed for reports; recommendation-style skills use `workflow_actions` (D5) |
| Web app skill execution | Gateway has no SKILL.md loading mechanism yet; defer until CLI+Claude Code validated |
| Frontend skill command palette | Only useful once web execution works |

---

## Relationship to Open Source Launch

| Surface | How skills work | Status |
|---------|----------------|--------|
| **CLI** | `python3 -m skills.cli morning-briefing` — headless runner | Phase 1 (this plan) |
| **Claude Code** | Synced to `~/.claude/skills/`, Claude reads SKILL.md as instructions | Phase 1 (this plan) |
| **Web app** | Deferred — requires gateway skill-loading mechanism (see Phase 3) | Deferred |

Skills are the same SKILL.md file across all three surfaces. The execution mode differs (CLI runner vs Claude Code vs gateway agent), but the workflow definition is portable.

---

## Execution Order

1. **Phase 1**: Implement skill-loader-spec (parser, loader, runner, CLI) — code from spec
2. **Phase 2**: Write 2 additional SKILL.md files (morning-briefing, portfolio-checkup) — follow stock-analysis pattern
3. **Verify**: Test all 3 skills via CLI and Claude Code
4. **Phase 3** (deferred): Web app integration — requires gateway skill-loading mechanism design

---

## Testing

Per skill-loader-spec acceptance criteria:
1. `parse_skill()` extracts structured data from SKILL.md frontmatter
2. `validate_skill()` catches missing tools, unresolved env vars, duplicate tool names
3. `SkillRunner.run()` completes within `MAX_TOOL_ROUNDS`, returns report with required sections
4. `--sync` copies skills to `~/.claude/skills/`
5. CLI: `python3 -m skills.cli morning-briefing` produces a formatted report
6. Claude Code: typing "morning briefing" triggers the skill workflow

---

## Open Questions

1. **Web app skill execution via gateway**: Does the agent behind the gateway have access to SKILL.md files? If not, the skill prompt needs to be injected into the chat message, not loaded from filesystem.
2. **Skill parameters in chat**: How does the user provide inputs for skills that require them (e.g., `stock-analysis` needs a ticker)? Option: chat prompt asks for missing inputs before running.
3. **Skill output format in web app**: Should skills produce `:::artifact` output for the side panel? The skill-loader-spec says markdown, but the web app has richer rendering.

---

## Codex Review Changelog

### Round 1 (2026-03-16) — 6 issues

| # | Finding | Fix |
|---|---------|-----|
| 1 | Plan conflicts with existing skill-loader-spec — proposes YAML files, not SKILL.md | Rebased entirely on skill-loader-spec. SKILL.md + YAML frontmatter is the format (D1). |
| 2 | Over-engineered — runner, DB, scheduling, CRUD APIs, UI before validating format | Cut to minimal first pass (D2). Defer DB/scheduling/CRUD/marketplace. |
| 3 | Wrong tool registry — hand-maintained catalog instead of MCP `tools/list` | Runner uses `tools/list` discovery per spec (D3). |
| 4 | Identity model broken for multi-user web execution | Acknowledged as explicit gap (D4). Web skills run through gateway (user context from session). Headless deferred. |
| 5 | Ignores existing audit trail (`workflow_actions`, `mcp_tools/audit.py`) | Skills reuse audit trail (D5). No separate execution tracking table. |
| 6 | Multi-server support under-specified | Already solved in skill-loader-spec: frontmatter declares servers, runner connects to each, `tools/list` + allowlist filtering. |

### Round 2 (2026-03-16) — 3 issues

| # | Finding | Fix |
|---|---------|-----|
| 1 | Web path assumes a mechanism that doesn't exist — gateway can't load SKILL.md or resolve `/skill-name` | Phase 3 explicitly deferred. Three options documented for future design. CLI + Claude Code ship first. |
| 2 | Audit trail reuse overstated — `workflow_actions` allowlist is workflow-specific, not general execution log | D5 rewritten: recommendation-style skills use audit trail; informational skills have no execution history in first pass. |
| 3 | Web command palette needs single source of truth for skill metadata | Deferred with Phase 3. Will need backend skill metadata endpoint or static manifest when web integration ships. |

### Round 3 (2026-03-16) — 3 issues

| # | Finding | Fix |
|---|---------|-----|
| 1 | Stale web references in D2, relationship table, and command palette text | Removed "web app integration via gateway" from D2 minimal pass. Updated relationship table to show web as "Deferred." |
| 2 | Command palette status contradictory — both "not deferred" and in defer table | Removed from first pass. Deferred with web execution. |
| 3 | Audit allowlist missing `stock_research` | Added to allowlist text. |
