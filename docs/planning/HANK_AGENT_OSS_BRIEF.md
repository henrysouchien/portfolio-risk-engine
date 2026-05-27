# Hank Agent OSS — Brief

> **Status**: BRIEF FILED — needs full plan after HP1 Phase 0.2 contract decisions
> **Created**: 2026-05-22
> **Revised**: 2026-05-22 (post-Bridge-drop architectural simplification: model-engine confirmed Hank consumer Excel-add-in-only; no Hank Bridge — user's MCP client IS the local file layer)
> **Tracking ID**: `Launch-HP2`
> **Parent**: `docs/planning/launch/OPEN_SOURCE_LAUNCH_STRATEGY.md` Deliverable #2 (Agent extraction); was C3 in `OPEN_SOURCE_LAUNCH_GAPS.md` — brought forward to pair with HP1
> **Pairs with**: `docs/planning/HANK_PLATFORM_MVP_PLAN.md` (HP1)

## Out of scope (explicit non-goals)

- **Model-engine / Excel modeling tools** — these live in Hank consumer's Excel add-in (`AI-excel-addin/`), not in HP2's OSS scope. The schema engine, SIA template, and EDGAR-concept mapping all stay proprietary in the add-in where direct workbook access avoids hosted-file privacy concerns. HP2's open agent calling Platform tools will NOT have modeling capability — modeling is a Hank-consumer-only feature for v1.
- **Custom local file MCP (Bridge)** — not needed. The user's MCP client (Claude Code / Codex) already provides local filesystem tools (`Write`, `Edit`, `Bash`). When HP1 Platform tools return file content (CSV exports, markdown briefs, etc.), the user's agent saves locally using its own tools. HP2 doesn't ship a local-file companion.

---

## Goal

Open-source the Hank agent runtime (loop + dispatcher + memory + skill SCHEMA) on top of the already-shipped `ai-agent-gateway` PyPI package. **HP2's role in the product family: top-of-funnel distribution channel into HP1 (the primary paid product).** Technical investors discover Hank via the open agent, plug it into MCP servers, eventually adopt HP1 hosted Platform for tools + methodology delivery — natural upgrade path.

**Pattern reference**: Dexter — open agent that connects to a paid hosted data API. We extend the pattern: open agent + paid Platform that delivers both data AND methodology (via `get_skill()` MCP).

---

## Strategic position — why this works without compromising the wedge

The methodology IS the wedge — years of iteratively-tuned skill files, decision routing, prompt engineering. Open-sourcing the agent layer with methodology baked in would bleed the wedge.

**The fix: shift methodology delivery from "baked into agent code" to "delivered by Platform via MCP."** Open the runtime; keep methodology in our control as a Platform service.

| Open (free, distribution layer) | Platform-delivered (paid, the wedge) |
|---|---|
| Agent runtime: loop, dispatcher, MCP client | Hank's actual skill CONTENT (specific methodology, prompts, decision trees) |
| Memory system: SQLite store + markdown sync | Methodology routing baked into tool descriptions |
| Skill SCHEMA: the format spec (YAML/Markdown) | MCP prompt templates for skill execution |
| MCP client wiring + tool-call orchestration | `get_skill(name)` MCP tool — delivers skill spec on demand |
| Hooks for user-written skills | Hank's data + tools (HP1 v1 bundle) |

**Why this is more durable than "ship skills as code":**

1. **Out-iterate any fork on methodology.** Vals work shipped 3 new methodology rules yesterday (q030/q038/q050). Platform-delivered methodology gets these on next request; baked-in methodology needs a new agent release. Forks chase a moving target.
2. **Methodology is most valuable when current.** Snapshot via reverse-engineering MCP responses gets last month's content; ours is already three Vals runs ahead.
3. **Lower fork risk.** Fork the runtime; without Platform subscription, you have an agent with no methodology, just raw tool access.
4. **MCP was designed for this.** Rich tool descriptions, prompt templates, resources, response enrichment — all four are methodology delivery surfaces. Not fighting the protocol.

---

## Architecture: the layered stack

```
ALREADY OPEN (shipped — free, distribution layer)
└── ai-agent-gateway (PyPI)
    The harness: LLM proxy, session management, tool dispatch, SSE streaming.
    Extracted from AI-excel-addin/api/, deployed via agent-gateway-dist.

NEW OSS LAYER (HP2 scope)
├── hank-agent (or similar name — see Q1)
│   Agent loop on top of gateway: skill dispatcher, MCP client wiring,
│   tool-call orchestration. Source: AI-excel-addin/api/agent/.
├── hank-memory (or sub-module of hank-agent)
│   SQLite store + bidirectional markdown sync layer.
│   Source: AI-excel-addin/api/memory/ (per-user SQLite + workspace/ markdown sync).
└── Skill SCHEMA spec
    The grammar for skill files — name, triggers, required_tools, prompt
    template structure, output format. NOT the actual skill content.

PLATFORM-DELIVERED (HP1 — paid, the wedge)
├── Hank's skill CONTENT (the 50+ skill files in AI-excel-addin/api/agent/skills/)
├── Tool descriptions enriched with methodology routing
├── MCP prompt templates for skill execution
├── get_skill(name) MCP tool (delivers skill-as-template on demand)
└── Data + tools (already in HP1 plan)
```

---

## Scope — what's actually left to build

Most of the work is already done. The harness shipped. What's left:

1. **Lift agent layer** out of `AI-excel-addin/api/agent/` into a standalone `hank-agent` package. Remove Hank-specific skill files; ship the dispatcher mechanism only.
2. **Lift memory system** out of `AI-excel-addin/api/memory/` (could ship inside `hank-agent` or as separate `hank-memory` package).
3. **Document skill schema** — the format spec, not the content. Markdown-with-frontmatter or YAML; field definitions; loading semantics; dispatcher contract.
4. **Define `get_skill(name)` MCP contract** — coordinate with HP1 Phase 0.2. Platform-side endpoint that returns skill spec matching the open schema; auth via HP1 bearer token; client-side caching with short TTL + Platform-pushed invalidation.
5. **Package + README + examples** — including an example of pointing `hank-agent` at HP1 hosted Platform to get methodology delivery.
6. **Publish to PyPI + GitHub repo**; license decision (Q2).

**Estimated scope**: weeks, not months. Builds on `ai-agent-gateway` (already shipped) and pairs with HP1 Phase 0.2 (already planned).

---

## Why this strengthens HP1 (and vice versa)

**Without HP2**, HP1's pitch is "hosted MCP tool access" — abstract, generic.

**With HP2 paired**, HP1's pitch is "the methodology + tools + data engine that powers the open Hank Agent" — concrete, defensible, differentiated. Users install HP2 (free, runtime works alone), connect to HP1 (paid, methodology-enriched), see the difference immediately. Free → paid funnel is mechanical.

**Without HP1**, HP2 is "an open investment agent that talks to MCP servers" — competes with Aider/Cline.

**With HP1 paired**, HP2 is "the open investment agent purpose-built around Hank Platform's methodology delivery" — specific, differentiated.

The two ship better together than apart.

---

## Open questions

| ID | Question | Notes |
|---|---|---|
| Q1 | **Naming** — `hank-agent` vs `analyst-agent` vs other? | Hank-branded clarifies the Platform connection; neutral-named broadens TAM. `ai-agent-gateway` chose neutral; consistency argues for repeating. |
| Q2 | **License** — MIT / Apache 2.0 / AGPL? | MIT = max distribution. Apache 2.0 = same + patent clause. AGPL = prevents hosted forks from running our open agent against a competing data API. AGPL strongest for wedge protection; MIT/Apache better for adoption. |
| Q3 | **Skill cache TTL** — how aggressive on client-side caching of Platform-delivered skill content? | Trade-off: longer cache = faster + less Platform load; shorter = methodology updates propagate faster. Probably ≤1 hour with Platform-pushed invalidation. |
| Q4 | **User-skill collision rule** — when user-written skill and Platform-delivered skill have same name, which wins? | Probably user-written wins (override semantics, like CSS); needs explicit policy. |
| Q5 | **Memory portability** — is the SQLite store designed to be moved between machines? | Today it's local-only with markdown sync as the human-readable layer. Cross-device sync is a separate question deferred — Bridge was dropped, so no Hank-built sync mechanism exists. Users wanting cross-device memory would manually copy the SQLite file + workspace markdown, or use their own sync tool (Dropbox/iCloud/git). |
| Q6 | **Launch coordination** — ship HP2 with HP1 v1 launch, or after? | Together gives the strongest funnel story. Separately lets HP2 build OSS audience first. Recommend together. |

---

## Dependencies

- **HP1 Phase 0.2 must include `get_skill(name)` MCP contract design** — this is the bridge between open agent and paid methodology. Without it, HP2 has nothing to connect to. (HP1 plan updated 2026-05-22 to reference this.)
- **`ai-agent-gateway` (already shipped)** — provides the harness layer HP2 builds on. No additional gateway work needed for HP2 v1.
- **Audience validation activities for HP1** — gate HP2 launch coordination. If HP1 audience hypothesis fails validation, HP2 needs to reconsider standalone positioning.

---

## Next actions

1. Decide Q1 (naming) + Q2 (license) — gating decisions for repo + package setup
2. Draft full plan doc (`docs/planning/HANK_AGENT_OSS_PLAN.md`) once HP1 Phase 0.2 `get_skill()` contract is sketched — the contract shape determines hank-agent's skill-loading interface
3. Coordinate with HP1 sequencing — launch together if possible
4. Codex review the full plan when filed

---

## Supersedes / Related

- **Brings forward** `C3 Agent Extraction` from `OPEN_SOURCE_LAUNCH_GAPS.md` Phase C — was "Do Later"; now repositioned as Phase B parallel to HP1.
- **Refines** `OPEN_SOURCE_LAUNCH_STRATEGY.md` Deliverable #2 (Agent extraction) — the "methodology-stays-Platform-delivered" decision is new here.
- **Pairs with** `HANK_PLATFORM_MVP_PLAN.md` (HP1) — they're complementary; HP1 paid, HP2 free, OSS pull → paid Platform funnel.
