# Hank Platform MVP Plan

> **Status**: PLANNED — Phase 0 (external-access auth + billing co-design) must precede Phase 1 implementation. Open commercial questions Q1–Q9 to resolve in parallel.
> **Created**: 2026-05-21
> **Revised**: 2026-05-25 (r6.1 — R7 Codex cleanup: funnel diagram now shows direct paths into HP1 (not all paths gated by Hank consumer); premium scope clarified as inside Pro (not separate SKU); Q4 resolved via Q1; Next Actions + Open Questions intro updated to reflect Q1/Q2/Q4/Q5 RESOLVED. **Codex R7 PASS**.)
> **Prior revisions**: r6 business model clarification (2026-05-25); r5.1 final count drift; r5 R5 cleanup; r4.1 architectural simplification + R4 cleanup; r3 Codex R1→R3 PASS
> **Codex review history**: R1 FAIL (10) → R2 FAIL (8) → R3 PASS (6 P2) → R4 FAIL (1 P1 + 5 P2) → R5 PASS (5 P2) → R6 PASS (1 P2) → **R7 PASS (4 P2 — funnel + Q1/Q2/Q4/Q5 resolution drift fixed)**.
> **Prior revisions**: r3 2026-05-21 (Codex review R1→R3 PASS — Phase 0 + explicit allowlist + Q7–Q9 + audience-as-hypothesis + exposure-policy contradiction fix + brokerage-binding entity model fix + concrete Phase 0 artifacts)
> **Supersedes**: `docs/planning/PORTFOLIO_MCP_EXTRACTION_PLAN.md` (B4 OSS-extraction direction) for the independent-investor audience. B4 remains valid framing for a self-host audience but is deprioritized.
> **Parent**: `docs/planning/launch/OPEN_SOURCE_LAUNCH_STRATEGY.md`
> **Tracking ID**: `Launch-HP1` (replaces `Launch-B4` in `docs/TODO.md`)

---

## Goal

Ship Hank Platform — a hosted MCP endpoint that exposes a **curated, safety-scoped subset** of Hank's investment toolchain to independent investors building workflows in Claude Code / Codex / other MCP clients. **HP1 is the primary paid product** (where day-to-day customer activity and recurring revenue live); Hank consumer is the demo/showcase surface that drives discovery + onboarding; HP2 OSS agent is the top-of-funnel distribution channel; Fifth Avenue AI services is the high-touch revenue line on top.

**Pitch:** "Hank-quality investment research in your own Claude Code / Codex workflow." Investors install once with `claude mcp add`, OAuth their brokerage via our portal, get institutional-grade portfolio + research tools + Hank's methodology delivered as `get_skill()` MCP responses — all consumed by the investor's existing agent. They direct; their agent acts; our tools + methodology power the work. Public surface is intentionally narrower than Hank's internal surface — admin, normalizer, brokerage-routing, and execution-side trading tools stay internal-only (or behind explicit scope opt-ins).

---

## Audience (hypothesis, not yet validated)

**Working hypothesis:** Independent investors — likely individual, family-office, or small-fund — who:

- Are MCP-fluent (understand the pattern, already connect MCPs)
- Use Claude Code / Codex as their primary AI surface
- Are starting to build their own investment workflows / skills
- Want hosted infrastructure (not self-host), but want to be the agent themselves

**Not the target:** pure software developers (would prefer OSS install), Hank's consumer end-users (want managed analyst output, not tools), institutional funds (different procurement/compliance path).

**Validation activities required before Phase 1 launch** (treat audience as hypothesis to test, not premise to build on):

1. **Landing page email-signup test** at `platform.hank.investments` (or `/platform`) describing the offering — target: ≥100 qualified signups in 4 weeks before Phase 1 implementation begins
2. **Subreddit / community signal harvesting** — r/ClaudeAI, r/investing, MCP Discord, Anthropic Discord — quantify mentions of "brokerage + Claude / Codex" pull (target: ≥20 signal observations)
3. **Fifth Avenue AI design-partner pilot** — at least 3 prospective clients commit to using Hank Platform in their workflow during private beta (leverages existing consulting partnership)
4. **Hank consumer cross-sell signal** — survey existing paid Hank users: "would you use these tools in your own Claude Code workflow?" Target: ≥30% interest before sequencing this ahead of other launch work

**Anti-signal that kills this plan:** if signups are <50, signal observations <10, and Fifth Avenue clients show no interest, the hosted-MCP-for-investors hypothesis is wrong — reconsider audience or pivot to dev-tooling positioning.

The narrative "independent investors searching 'how do I connect my brokerage to Claude' today have no clean answer" is currently **untested intuition**, not validated demand. Validation criteria above convert it to evidence before we commit to build.

---

## Position

**Hank Platform is the substrate that powers all Hank surfaces.** Today's managed-agent channels (web app, Excel add-in, TUI, Telegram, CLI, autonomous cron) bundle Hank's agent + UI on top of Platform. The new MCP channel exposes Platform tools to the user's own agent without Hank's orchestration on top.

### Architectural relationship

```
Hank Platform (substrate — infrastructure layer)
├── MCPs: portfolio, research, research-workbench, edgar, fmp, macro, fred, options
├── Gateway: multi-user auth, BYOK, strict-mode, brokerage OAuth (Plaid/SnapTrade/Schwab/IBKR)
├── Storage: per-user Postgres, corpus, methodology data
└── Connectors: brokerage adapters, data ingestion (Edgar parser, FMP, ORATS)

Powers two product categories:

  Hank (managed-agent surfaces — Hank's agent + Hank's UI on top of Platform)
  ├── Web app  (hank.investments)
  ├── Excel add-in
  ├── TUI
  ├── Telegram bot
  └── CLI / autonomous cron

  Hank Platform (BYO-agent surface — Platform tools exposed via MCP)
  └── MCP endpoint (claude mcp add hank-platform)
```

### What stays proprietary (the moat)

The **agent** — orchestration logic, prompts, skill files, methodology routing, voice. Tools are infrastructure (copyable). The agent is the differentiator. Exposing the tool surface doesn't dilute Hank; it grows surface area while preserving the moat.

### Exposure policy (single source of truth)

Tools fall into exactly one of two exposure classes. **No tool is in more than one class.**

1. **Internal-only (never exposed to third-party agents via Platform)** — admin/config/lifecycle/import/modeling tools that have no safe customer-facing MCP semantics:
   - **Brokerage lifecycle**: `initiate_brokerage_connection`, `complete_brokerage_connection`, `manage_brokerage_routing` (brokerage connect happens via hosted portal, never via MCP tool)
   - **Admin / config**: `manage_instrument_config`, `manage_proxy_cache`, `manage_stress_scenarios`, full `normalizer_*` family (normalizer_activate, normalizer_list, normalizer_sample_csv, normalizer_stage, normalizer_test)
   - **Import / ingest**: `import_portfolio`, `import_transaction_file`, `ingest_document`, `load_document` (covered by portal ingestion, never exposed)
   - **Internal diagnostics**: `get_mcp_context`, `thesis_run_scorecard`, `get_performance`
   - **Modeling (Hank consumer Excel add-in only)** — `excel-addin-only` sub-tag in manifest:
     - **`model-engine` tools** (separate MCP server, lives in own repo): `model_build`, `model_summarize`, `model_find`, `model_values`, `model_drivers`, `model_sensitivity`, `model_scenario`, `model_discover_segments`, `annotate_model_with_research`, `model_clear_cache`
     - **portfolio-mcp's model-adjacent tools** (live in `mcp_tools/research.py` + `mcp_tools/model_build_context.py`, wrap model-engine functionality): `build_model`, `get_model_build_context`, `get_model_insights`, `get_price_target`. **Phase 0.2 verifies each: if implementation depends on model-engine schema/templates → `excel-addin-only` (default classification); if purely consensus/analyst data with no model-engine dep → reclassify as `hosted-public:read`.** Default-deny until verified.
     - All modeling lives inside the Excel add-in where direct workbook access avoids the privacy / upload concerns of hosted modeling. Schema engine + SIA template + EDGAR-concept mapping stay proprietary in `AI-excel-addin/`. Not part of Platform's hosted surface.

2. **Hosted-public (exposed via hosted MCP endpoint, scope-gated per token)** — four scope tiers (Q8 finalizes):
   - **`read` scope (default for every Platform token)**: all read-side analysis tools (positions, risk, factor analysis, optimization, research/citation tools, data lookups, news, events), plus the methodology-delivery tool `get_skill(name)` (Phase 0.2). For tools that produce file outputs (e.g., `export_holdings` CSV, thesis-to-markdown exports), Platform returns content in the MCP response. **Local file persistence requires the user's MCP client to have filesystem-write capability** — Claude Code and Codex both have native `Write` / `Bash` tools, so this works out-of-box. For MCP clients without filesystem tools, Platform additionally returns a signed time-limited download URL in the response payload (security requirements: ≤1 hour expiry, cryptographically-unguessable token, scoped to the authenticated user/token, single-use preferred, every signed-URL issuance + redemption logged for audit). **Both paths included in every file-output tool's response — no custom local MCP needed.**
   - **`trade-preview` scope (default)**: `preview_trade`, `preview_basket_trade`, `preview_option_trade`, `preview_futures_roll`, `preview_rebalance_trades`, `suggest_tax_loss_harvest` — read-side trade preparation, no execution
   - **`trade-execute` scope (explicit portal opt-in with confirmation step, Q3)**: `execute_trade`, `execute_basket_trade`, `execute_option_trade`, `execute_futures_roll`, `cancel_order` — execution-side trading tools. **These ARE publicly exposable behind the explicit opt-in scope; this is the intentional product decision (Q3 recommendation).** Token without `trade-execute` scope cannot see or call these tools (gateway filters tool-list response).
   - **`premium` scope (v1.5 add-on, separate billing tier)**: `jobs-mcp` family (insider buying, quality screens, biotech catalysts, etc.), `alerts` (Telegram/iMessage/email notifications), `timesfm` (forecasting). Heavy-compute or recurring-cost tools gated behind a separate Premium subscription.

The 23 tools in `INTERNAL_ONLY_PORTFOLIO_TOOLS` (`mcp_tools/_tier_policy.py:7`) currently overlap classes (1) and (2) — specifically the `execute_*` family is internal-only for non-owner Hank-internal roles today, but for Hank Platform they shift to scope-gated public. Phase 0.2 outputs the **definitive** per-tool exposure-class manifest as a checked-in JSON file (not a Python frozenset), with one class per tool, no ambiguity. The current `_tier_policy.py` is a starting point, not the final policy. **Modeling tools** in the manifest are tagged `internal-only` with sub-tag `excel-addin-only` to make the location explicit.

### Vertical-integration analogue

Same shape as Anthropic (Claude API + Claude.ai), Replit (Repls + Repl Deployments), Vercel (Vercel platform + flagship demos): platform underneath, flagship app on top that proves and dogfoods it. Hank Platform sells infrastructure to a builder audience; Hank consumer sells finished agent intelligence to a non-builder audience. Same backend, two pricing models matched to channel economics.

### Design principle: hybrid hosted+local

Hosted is authoritative (source of truth for user state, queryable from any device, integrated across all Hank surfaces). Local is where files land when the user needs to open them with native tools (Excel, Markdown editors, file browsers).

Same pattern already proven by Hank's memory architecture (`AI-excel-addin/api/memory/`): SQLite-as-authoritative + markdown sync layer for human curation. Hank Platform applies this principle by **delegating the local layer to the user's existing MCP client** (Claude Code / Codex / etc.) — when Platform tools return file content, the user's agent uses its own `Write` / `Edit` / `Bash` tools to save locally. No custom local MCP companion needed.

### Product surface map + funnel mechanics

Four surfaces; one of them is the primary revenue product; the others are funnel + services.

| Surface | Role | Pricing posture | What customer does |
|---|---|---|---|
| **HP2 — Hank Agent OSS** (open agent runtime) | Top-of-funnel distribution channel | Free (OSS) | Installs from PyPI, points at any MCP, eventually discovers HP1 |
| **Hank consumer** (web app, Excel add-in, Telegram, TUI, CLI) | **Demo + onboarding surface** (intentional high-touch friction → consulting + feedback channel; evolves to credit-based self-serve managed agent vNext) | Paid showcase tier today; credit-based with outcome-named bundles ("monthly portfolio review", "earnings calendar coverage", "due diligence runs") at vNext | Signs up → we onboard via call → experiences full Hank agent + UI |
| **HP1 — Hank Platform** (hosted MCP bundle) | **PRIMARY PRODUCT — where customer day-to-day activity + recurring revenue live** | Paid Standard / Pro tiers + Premium add-on; per-seat (individual) or per-firm (institutional) | Connects MCP endpoint to their Claude Code/Codex; their agent directs, our tools + methodology power the work |
| **Fifth Avenue AI services** | High-touch consulting / co-work on top of HP1 | Per-engagement / retainer | Methodology customization, skill development, integration work alongside Claude Code |

**Funnel mechanics** — multiple direct paths into HP1, plus an enriched path through Hank consumer onboarding:

```
Discovery channels → HP1 (primary product)

Path A (direct, technical):
  OSS HP2 install → discovers Hank ecosystem → upgrades to HP1

Path B (direct, content/SEO):
  Landing page (platform.hank.investments) → self-serve HP1 signup

Path C (direct, referral):
  Fifth Avenue AI referral → HP1 with services package

Path D (enriched, demo-led):
  Hank consumer signup → onboarding call (intentional friction →
  feedback + consulting upsell) → discovery → HP1 upgrade

All paths converge on HP1 as the primary recurring revenue product.
Within HP1: Standard tier → Pro tier (adds trade-execute + premium scopes) →
Fifth Avenue AI services for institutional accounts.
```

**No path requires going through Hank consumer.** Hank consumer is an enriched discovery channel (demo-led, high-touch onboarding generates feedback + consulting opportunities), not a mandatory gate.

**Why intentional onboarding friction on Hank consumer:**

The friction IS the feature. The high-touch onboarding call is:
- Feedback channel (every onboarding teaches us what investors actually need)
- Consulting upsell opportunity (Fifth Avenue AI gets a natural intro)
- Case-study + reference-customer generator
- Avoids the "self-serve scaling before product-market fit" trap

vNext (post-validation, once usage patterns are clear): Hank consumer evolves to self-serve standalone managed agent with credit-based pricing (user-facing UI shows outcomes, not raw credits). The high-touch surface stays available as "Hank consumer with white-glove onboarding" SKU for the institutional segment.

---

## Bundle Taxonomy

### v1 — Hank Platform (hosted MCP, no install)

Single MCP endpoint, flat tool namespace (Option A from architecture discussion). One `claude mcp add` command. **Public tool surface ≠ Hank's full internal surface** — see "What stays internal" above + Phase 0 scope model.

#### Source MCPs in the bundle

| Category | MCPs | Internal tool count | Why bundled |
|---|---|---|---|
| **User-state tools** | `portfolio-mcp`, `research-mcp`, `research-workbench-mcp` | 114 + 22 + ~15 | Per-user DB-bound — share auth + Postgres scoping |
| **Stateless data** | `edgar-financials`, `macro-mcp`, `fred-mcp` | ~20 + ~6 + ~4 | No user state, but valuable in tandem with user-state tools (e.g., research-mcp + edgar used together — F102 hardened this pattern) |
| **BYOK passthrough** | `fmp-mcp`, `options-mcp` | ~15 + ~3 | User provides API key (FMP / ORATS); we proxy + rate-limit (Q9) |

**Tool counts** (verified 2026-05-21): `mcp_server.py` has 114 `@mcp.tool()` registrations; `mcp_server_research.py` has 22. Other MCP servers live in `investment_tools/` and `Edgar_updater/` — exact public-surface counts to be enumerated in Phase 0 once allowlist is finalized.

#### Public-surface composition (placeholder — Phase 0.2 produces the definitive manifest)

Before exposing any tools externally, Phase 0.2 produces the **per-tool exposure-class manifest** (one class per tool from the "Exposure policy" section above) as a checked-in JSON file. The composition rule:

- **Internal-only**: lifecycle + admin + import + diagnostics + modeling (~32 tools: 18 from current `INTERNAL_ONLY_PORTFOLIO_TOOLS` minus the 5 execution tools that move to hosted-public:`trade-execute`, PLUS ~10 `model-engine` tools (Excel-add-in-only), PLUS 4 portfolio-mcp model-adjacent tools — `build_model`, `get_model_build_context`, `get_model_insights`, `get_price_target` — pending Phase 0.2 verification)
- **Hosted-public, `read` scope**: ~80–90 read-side analysis tools, including file-output tools that return content in MCP response (`export_holdings` returns CSV text; user's agent writes locally)
- **Hosted-public, `trade-preview` scope**: ~6 trade-preview tools (default for every Platform token)
- **Hosted-public, `trade-execute` scope**: ~5 execution tools (explicit portal opt-in per Q3)

**Estimated hosted-public surface count**: ~90–100 tools at `read` scope (includes `get_skill`); +6 at `trade-preview`; +5 at `trade-execute` (full opt-in); v1.5 adds `premium` scope (jobs/alerts/timesfm — ~15 tools). Internal-only ≈ 32 tools never exposed externally (18 admin/lifecycle/diagnostics + ~10 model-engine tools + 4 portfolio-mcp model-adjacent tools pending Phase 0.2 verification). **Exact counts in the Phase 0.2 manifest are the source of truth — these estimates are rough.**

**Cross-repo source**: bundle spans risk_module (portfolio-mcp, research-mcp), Edgar_updater (edgar-financials), investment_tools (research-workbench-mcp, macro-mcp, fred-mcp, options-mcp). Five of these already co-packaged in `investment_tools/` repo, which simplifies release coordination.

**Architecture**: hosted gateway aggregates the underlying MCP servers behind one HTTP endpoint. Hank's prod gateway at `hank.investments` already routes to all 8 *internally* for Hank's own agent — exposing them *externally* requires new MCP-protocol surface + external bearer auth + scope filtering (Phase 0), not just exposing what's already running.

### Local file handling — no custom MCP needed

For file-output tools (`export_holdings` → CSV, thesis-to-markdown, brief-to-PDF, etc.), the pattern is:

1. User's agent (Claude Code, Codex) calls the hosted Platform tool
2. Platform returns content in the MCP response — text for CSV/markdown; base64-encoded bytes or signed download URL for binary (PDFs, etc.)
3. User's agent uses its **own native filesystem tools** (`Write`, `Edit`, `Bash` for `curl > file`) to save locally

**No custom local MCP package needed.** The user's MCP client already provides the local file layer; Platform just needs to deliver content in a usable format.

For **Excel modeling specifically** — where file workflow naturally lives — see the Hank consumer Excel add-in. Modeling tools are not part of Platform; they live in `AI-excel-addin/` with direct workbook access.

### v1.5 — Hosted Premium Add-on

Heavy-compute tools that need hosted execution but warrant separate pricing/tier.

| Tool | Why premium |
|---|---|
| `jobs-mcp` | Long-running research jobs (insider buying, quality screens, biotech catalysts, ownership scans, fingerprint screens). Real institutional-grade value, but per-job compute cost is meaningful |
| `alerts` | Notification surface (Telegram/iMessage/email). Pairs naturally with jobs-mcp — bundled together |
| `timesfm` | TimesFM zero-shot forecasting. Requires model server infrastructure |

### Standalone only (not bundled)

| Tool | Reason |
|---|---|
| `ibkr-mcp` | Requires user's local IBKR Gateway process — can't host |
| `scheduler-mcp`, `services-mcp`, `agents-mcp` | Admin/ops tools, not end-user tools |

### Top-of-funnel standalone (also available outside the bundle)

`edgar-financials`, `fmp-mcp`, `fred-mcp` remain installable standalone via their original distribution paths. Serves narrower-need audiences (SEC-only, data-only) and acts as a discovery funnel — install standalone → discover Hank Platform → upgrade.

Brand note: standalone tools keep neutral naming (`edgar-financials`, not "Hank Edgar"). Branding them "Hank" would limit reach to the Hank-aware audience.

---

## Sync Architecture

Hybrid hosted+local — but "local" is **the user's existing MCP client (Claude Code / Codex)**, not a custom Hank component.

| Data | Authoritative | Local copy? | How |
|---|---|---|---|
| Positions, transactions | Hosted DB (live from brokerage) | No | Direct MCP tool reads from hosted state |
| Thesis, diligence runs, findings | Hosted DB | Optional export | Platform returns markdown text in MCP response; user's agent writes to disk via native `Write` tool |
| Research workbench (studies, signals, screen hits) | Hosted DB | Optional export | Same — Platform returns content; user's agent saves locally |
| Excel models | **Local filesystem (Excel add-in only)** | n/a | Hank consumer Excel add-in operates on user's active workbook directly; Platform never sees model files |
| Brokerage credentials | Hosted (encrypted, SSM-backed) | No | OAuth flow via portal; tokens stay server-side |
| User config / skills | User's `~/.claude/` | n/a | User-owned (Claude Code's own config) |

**v1 ships no Hank-built local layer.** Platform exposes hosted MCP; user's agent runtime (Claude Code/Codex) handles all local file operations using its own tools. This is the simplest possible architecture — no extra packages, no auth-sharing between hosted MCP and local component, no cross-version coordination problem. Bidirectional file sync (Dropbox-style) deferred until usage shows demand and a clear need beyond what users' agents can already do with their own filesystem tools.

---

## Architecture Leverage

Much of the heavy infrastructure is already live for *internal* / cookie-session use. External MCP exposure requires net-new work — be careful not to overstate what's "shipped."

**Already shipped (since 2026-05-04, usable as a foundation):**

- Multi-user gateway live at `hank.investments` — routes Hank's agent to internal MCPs
- Strict-mode auth + BYOK + channel cutover (Excel/web/Telegram/CLI/TUI/autonomous cron live-verified 2026-05-16) — all use **cookie session auth** or **internal gateway-key auth**, not external bearer tokens
- SSM hydration (16 keys in `/risk-module/{dev,prod}/{shared,broker}/`, KMS-encrypted)
- Tier enforcement middleware (A1, `90f52fe1`) — `@require_tier` / `create_tier_dependency` on ~30 paid endpoints. **Cookie-session FastAPI dependency** (`app_platform/auth/dependencies.py:14`), reads `session_id` cookie. **Does not currently support bearer-token / per-token-scope flows needed for remote MCP clients.**
- Frontend tier awareness (A2, `948f38f4`) — `useTier()`, `UpgradePrompt`, 403 split
- Skills system design (A3, Codex PASS x5)
- agent-gateway published to PyPI as `ai-agent-gateway`, deployed via `agent-gateway-dist`
- Hank's prod gateway already routes to all 8 v1 bundle MCPs **internally for Hank's own agent**
- Plaid + SnapTrade brokerage OAuth flows live for Hank consumer surface — but these are **cookie-session flows** with `_require_paid_user` deps on mutating routes (`routes/plaid.py:717`, `routes/snaptrade.py:709`), not MCP-token compatible
- API budget infrastructure exists (`app_platform/api_budget/`) — has `guard.py`, `alerts.py`, `llm_cost.py` for rate-limit / cost-tracking hooks (extendable for Q9)

**Net-new work for v1 (NOT a "skin" over existing infra — substantial Phase 0 + Phase 1 build):**

- **External-access auth subsystem** (Phase 0): bearer-token issuance, per-token scopes, revocation/rotation/expiry, token-to-user-context propagation through gateway (does not exist today)
- **Portal-driven brokerage OAuth with user-account binding** (Phase 0): user OAuths via web portal — brokerage credentials bind to **user account** (same model as Hank consumer today). MCP tokens reference the user and inherit access. Tokens carry scopes; user accounts carry brokerage connections.
- **MCP-protocol aggregation surface** over existing gateway (Phase 1): flat namespace, one URL, scope-filtered tool list
- **Public allowlist + scope tiering** (Phase 0): codified set of externally-exposable tools, scope tags (`read`, `trade-preview`, `trade-execute`, `premium` for v1.5 jobs/alerts/timesfm)
- **Rate limiting + abuse controls** (Phase 0 or 1): per-token quota, BYOK passthrough budgets, abuse detection — extends `app_platform/api_budget/`
- **Billing surface co-designed with B1 Stripe** (Phase 0 + Phase 1): Q1/Q2/Q4/Q5 decisions feed into schema, webhook handler, and token-issuance logic — *not* a simple Free/Pro upgrade
- Hank Platform onboarding portal (signup → brokerage OAuth → MCP token issuance → `claude mcp add` instructions)
- Docs site targeted at MCP-fluent investors (different voice than Hank consumer docs)

**Net-new work for v1.5:**

- Premium tier billing (jobs/alerts/timesfm add-on) — extends Phase 1 billing surface
- Jobs-mcp / alerts / timesfm exposed via existing hosted MCP endpoint (no new client install)

(Hank Bridge dropped — see "Local file handling" section in Bundle Taxonomy. Modeling moved to Hank consumer Excel add-in.)

---

## Open Questions

**Foundational architecture is decided** (hybrid hosted+local where "local" = user's existing MCP client; single MCP endpoint with flat namespace; user-account-bound brokerage with token-borne scopes; **two-class exposure policy: internal-only (with `excel-addin-only` sub-tag for modeling) / hosted-public (with `read` / `trade-preview` / `trade-execute` / `premium` scope sub-tags)**). **Foundational business model is decided** (r6 2026-05-25): HP1 = primary paid product (Standard/Pro tiered, per-seat individual or per-firm institutional); Hank consumer = paid showcase with intentional onboarding friction (v1) → credit-based self-serve at vNext; HP2 = top-of-funnel OSS distribution; Fifth Avenue AI = services line. Q1/Q2/Q4/Q5 commercial decisions RESOLVED via r6 (see below). **Still open**: Q3 (trading default), Q6 (entry-point naming), Q7/Q8/Q9 (Phase 0 architectural details: auth shape / scope-model granularity / rate-limit model), exact $/mo numbers (V1.1 dependent):

### Q1 — SKU structure (RESOLVED 2026-05-25)

**Answer: Standard / Pro tiered structure across the product family.**

- **Hank consumer (showcase)** — paid showcase tier with intentional onboarding friction; evolves to credit-based self-serve at vNext (outcome-named bundles like "monthly portfolio review", "earnings calendar coverage", "due diligence runs")
- **HP1 Standard** — v1 hosted MCP bundle with `read` + `trade-preview` scopes (default for every Platform token); includes basic skill methodology via `get_skill()`
- **HP1 Pro** — adds `trade-execute` scope + v1.5 `premium` scope (jobs / alerts / timesfm); advanced skill methodology
- **Fifth Avenue AI services** — per-engagement / retainer, on top of any tier; methodology customization, integration co-work

**Naming note: "premium" is a scope tier inside Pro, not a separately-purchasable add-on SKU.** Jobs / alerts / timesfm tools require Pro tier (which includes `premium` scope by default). Avoids the "friction at exact wrong moment" trap (user reaching for a premium tool hits an upgrade dialog mid-workflow). Standard → Pro is the natural expansion path. Q4 below is closed by this answer — premium is bundled into Pro, not à la carte.

### Q2 — Hank-consumer entanglement (RESOLVED 2026-05-25)

**Answer: Hank consumer = paid showcase/onboarding surface; HP1 = primary product. Sold independently, but with intentional funnel design (Hank consumer drives HP1 discovery + onboarding).**

Hank consumer's job is **demo + funnel**, not primary recurring revenue. Customers paying for Hank consumer are paying for the full managed-agent experience (web/Excel/Telegram/TUI/CLI + Hank's agent + white-glove onboarding). Customers paying for HP1 are paying for tools-in-their-own-workflow (their Claude Code, their agent, our hosted MCP + methodology). Different value props, different recurring use, different SKUs.

**No bundled "Hank Pro = consumer + Platform" SKU at v1** — that would muddle the value props during the validation phase. Once Hank consumer evolves to credit-based self-serve at vNext, a combined bundle becomes worth revisiting (HP1 Pro could include Hank consumer credits as a perk).

Implication for marketing surface: `hank.investments` = consumer demo + onboarding; `platform.hank.investments` = HP1 product. Different docs voice, different signup flows, both clearly part of Hank.

### Q3 — Trading enablement default

`preview_trade` / `execute_trade` / `preview_basket_trade` / `execute_basket_trade` / `execute_option_trade` / `preview_futures_roll` etc. — exposed by default or opt-in?

- **Read-only default**: safer; user explicitly enables trading via portal toggle
- **Full surface default**: more powerful out of the box; more blast radius
- **Tier-gated**: trading is Pro-only

Strong recommendation: **read-only default with explicit opt-in** for trading scopes. Matches what Plaid/SnapTrade users expect from "connect your brokerage" flows.

### Q4 — Premium tier composition (RESOLVED 2026-05-25 via Q1)

**Answer: bundled inside Pro tier (no separate à la carte).** Jobs / alerts / timesfm together as `premium` scope; granted to every Pro-tier token by default. Avoids friction-at-use-moment. Per-job-run usage costs absorbed into Pro pricing (tuned with first 30 days of usage data). Revisit at vNext if individual tool usage patterns surface clear price-discrimination opportunity.

### Q5 — Pricing model (PARTIALLY RESOLVED 2026-05-25)

**Answers locked:**

- **HP1**: tiered flat (Standard / Pro) per-seat for individual investors; per-firm for institutional (family-office, small fund). Multi-seat institutional pricing TBD with first design-partner deals.
- **Hank consumer at v1**: paid showcase tier with intentional onboarding-call friction (price reflects the white-glove component, not raw usage). Exact $/mo TBD with V1.1 decision.
- **Hank consumer at vNext**: credit-based pricing under the hood; user-facing UI shows **outcome-named bundles** ("monthly portfolio review", "earnings calendar coverage", "due diligence runs") not raw credits. Same model Anthropic uses (API credits + Claude Pro user-facing packaging).
- **HP1 Premium add-on**: lives inside Pro tier (no separate friction-creating SKU)
- **Fifth Avenue AI**: per-engagement / retainer

**Still open**: exact $/mo numbers for each tier — depends on V1.1 pricing decision (currently `BLOCKING` in `docs/TODO.md`) and Phase 0 audience-validation cost data. HP1 numbers must be coherent with Hank consumer numbers and competitive landscape (Hebbia, Quilt, AI investment tools generally).

### Q6 — Naming for entry point

`hank.investments/platform` vs separate subdomain (`platform.hank.investments`) vs separate brand (e.g., something other than "Hank Platform")?

Recommendation: **`platform.hank.investments`** — same brand, clear separation of audience. Different docs voice, different signup flow, but visibly part of Hank.

### Q7 — External-access auth shape (Phase 0 architecture decision)

Bearer-token model — what's the issuance, scope, revocation, and refresh story for hosted MCP clients?

- **Long-lived bearer tokens** (per-user, single-purpose) — simplest; weakest blast-radius if leaked
- **Short-lived bearer + refresh token** — better security posture; more complex client setup
- **OAuth 2.0 + PKCE** — full standard; overkill for v1 audience that's pasting `claude mcp add` commands
- **Reuse Hank's invite-key model** from AI-excel-addin gateway (`GATEWAY_USER_KEYS`) — fastest to ship, leverages existing pattern; check fit for external use

Decision affects Phase 0 design + scope opt-in flow + token rotation tooling.

### Q8 — Scope model / tool tiering

How fine-grained are scopes for tool exposure?

- **Coarse (single "platform" scope)** — token unlocks the public allowlist, nothing else. Simplest UX, no per-tool decisions for user.
- **Tiered (`read`, `trade-preview`, `trade-execute`, `premium`)** — token has scope set; agent only sees tools in granted scopes. Lets us default to read-only (Q3 recommendation) with explicit upgrade path for trading; `premium` scope gates v1.5 jobs/alerts/timesfm.
- **Fine-grained (per-tool or per-tool-group)** — most flexible; UX nightmare; not needed for v1.

Recommendation: **tiered**, with v1 launching `read` + `trade-preview` by default; `trade-execute` requires explicit portal opt-in with confirmation step.

### Q9 — Rate limiting + abuse controls model

Per-user / per-token quotas + BYOK passthrough budgets.

- **Per-token request-rate cap** (e.g., 60/min, 10K/day) — basic abuse protection
- **Per-tool cost-based budget** (using `app_platform/api_budget/` infrastructure) — tracks LLM-cost-equivalent or compute units per call
- **BYOK provider passthrough** (fmp/options) — user's API key, user's bill, our role = pass-through with optional our-side caching layer; rate limits enforced at provider's quota
- **Abuse detection signal** — anomalous request patterns, brute-force on auth, quota burning

Need a concrete shape before Phase 1 launch, even if numbers are tuned post-launch.

---

## Sequencing

### Prerequisites

1. **Audience validation activities** (see "Audience" section) — landing page signups, signal harvesting, design-partner pilot before committing implementation budget.
2. **V1.1 (Hank consumer pricing) resolved** — currently `BLOCKING` in `docs/TODO.md`. Hank Platform pricing decisions (Q1, Q2, Q5 above) must align — co-design, not sequential.
3. **Open commercial questions Q1–Q9 decided** — required before implementation begins; Q7, Q8 (auth shape + scope model) gate Phase 0 design.
4. **B1 Stripe plan refresh** — current `STRIPE_INTEGRATION_PLAN.md` is single Free/Pro subscription; HP1's multi-SKU + premium add-on + possible usage billing needs co-design before Phase 0 billing surface work begins.

### Phase 0: External-access auth + billing co-design (PRECEDES Phase 1)

This phase is net-new design + implementation work. **Phase 1 implementation cannot begin until Phase 0 completes** — Phase 1 building on shifting auth or scope foundations would force rework. Phase 0 itself IS implementation work (it produces the bearer-token subsystem, the exposure manifest, the rate-limit extension, etc. — not just design docs).

| Step | Scope | Depends on |
|---|---|---|
| 0.1 | **External MCP bearer-token subsystem.** **Acceptance artifacts:** DB migration adding `mcp_tokens` table (id, user_id FK, **token_prefix** for O(1) lookup, scopes JSON, hash, salt, created_at, expires_at, revoked_at, label) — token format `hank_pk_<prefix>_<secret>` where prefix is the indexed lookup key and secret is what gets hashed for `hmac.compare_digest` validation; token-issuance + revocation + rotation API endpoints with tests; bearer-token FastAPI dependency mirroring `create_tier_dependency` shape but reading `Authorization: Bearer` header instead of cookie; **threat model doc** (token theft, replay, brute force, scope escalation, prefix-only enumeration); MCP middleware contract for propagating `user_id` + `scopes` from bearer-token to tool-execution context. | Q7 (auth shape), Q8 (scope model) |
| 0.2 | **Per-tool exposure-class manifest + methodology-delivery contract.** **Acceptance artifacts:** checked-in JSON file (`config/mcp_exposure_manifest.json`) listing every `@mcp.tool()` from the 8 bundle MCPs + model-engine + jobs-mcp/alerts/timesfm + **`get_skill(name)`** with exactly one class (`internal-only` (with optional `excel-addin-only` sub-tag for model-engine + portfolio-mcp model-adjacent tools) / `hosted-public:read` (includes `get_skill`) / `hosted-public:trade-preview` / `hosted-public:trade-execute` / `hosted-public:premium` for v1.5 jobs/alerts/timesfm); validator script (CI-enforced) that fails if a new tool lands without a manifest entry; gateway tool-list filter that intersects the manifest with the requesting token's scopes; deprecation of the current `_tier_policy.py` (or refactor to read from the manifest); **`get_skill(name)` MCP tool contract** — Platform-side endpoint that returns a skill spec matching the open schema defined in `HANK_AGENT_OSS_BRIEF.md`. This is the bridge that delivers Hank's methodology (the wedge) to the open Hank Agent (HP2) without baking methodology into agent code. Auth via Phase 0.1 bearer token; client-side caching with short TTL + Platform-pushed invalidation. **Phase 0.2 also verifies the 4 portfolio-mcp model-adjacent tools** (`build_model`, `get_model_build_context`, `get_model_insights`, `get_price_target`): if model-engine-dependent → `internal-only:excel-addin-only`; if purely consensus/analyst data with no model-engine dep → reclassify to `hosted-public:read`. Default-deny pending verification. | Q8 |
| 0.3 | **Portal-driven brokerage OAuth uses standard user-account binding** — user OAuths brokerage via portal (Plaid/SnapTrade); brokerage credentials bind to **user account** (same model as Hank consumer today). MCP tokens reference the user and inherit access to that user's brokerage data via the user-account link. **Tokens carry scopes; user accounts carry brokerage connections.** Token revocation/rotation does not disturb the brokerage connection; brokerage disconnection does not invalidate tokens. **Acceptance artifacts:** new portal page at `platform.hank.investments/tokens` (signs in via existing cookie auth, lists+mints+revokes tokens); end-to-end test covering signup → brokerage OAuth → token mint → MCP call resolves user's positions; no schema change to brokerage tables (intentional — proves no binding to token). | Q7 |
| 0.4 | **Rate limit + abuse control model.** **Acceptance artifacts:** `app_platform/api_budget/` extension adding new `mcp_token` dimension to its Redis counter key scheme (today supports `budget:counter:<provider>:<operation>:{global|user}:<window>:<bucket>` with daily/monthly windows — see `store.py:140`; net-new is `mcp_token` scope with sub-minute window kind, e.g. `budget:counter:<provider>:<operation>:mcp_token:<token_id>:minute:<bucket>`); per-token request cap (e.g., 60/min, 10K/day defaults — tunable); per-tool cost-equivalent budget; BYOK provider passthrough (fmp/options) that enforces user's own provider rate limit, not ours; anomaly-detection signal (e.g., burst rate, failed-auth ratio); update `build_counter_key_specs` to emit token-scoped specs when a token context is present. **Note: this is a Redis counter-schema extension (new scope tag + new window kind), not a SQL migration — current store is Redis-key-based, not DB-table-based.** | Q9 |
| 0.5 | **Billing schema + entitlement model** co-designed with B1 Stripe. **Acceptance artifacts:** schema migration (subscription tier, premium add-on entitlements, audit log); refresh of `docs/planning/STRIPE_INTEGRATION_PLAN.md` to cover multi-SKU / add-on / usage-billing flows; webhook handler design for `checkout.completed` / `subscription.updated` / `subscription.deleted` that updates entitlements AND triggers token-scope updates; **Stripe entitlement matrix** (which Hank Platform SKU → which token scopes — `read`, `trade-preview`, `trade-execute`, `premium`). | V1.1, Q1, Q2, Q4, Q5 |
| 0.6 | **Phase 0 Codex review** — independent review of all acceptance artifacts above before Phase 1 begins. | All Phase 0 steps |

### Phase 1: v1 hosted MCP

| Step | Scope | Depends on |
|---|---|---|
| 1.1 | MCP-protocol aggregation gateway (HTTP/SSE endpoint exposing the public-allowlisted subset of the 8 v1 bundle MCPs as one flat tool surface, scope-filtered per token) | Phase 0.1, 0.2 |
| 1.2 | Onboarding portal (signup → brokerage OAuth via Phase 0.3 → FMP key collection → token issuance → `claude mcp add` instructions) | Phase 0.1, 0.3, 0.5 |
| 1.3 | Trading scope opt-in flow (separate portal page; Q3 read-only default; explicit confirmation for `trade-execute` scope) | Phase 0.2, 1.2 |
| 1.4 | Billing surface — Stripe checkout + webhook handlers + entitlement sync | Phase 0.5 |
| 1.5 | Rate limit enforcement live (extends `app_platform/api_budget/`) | Phase 0.4 |
| 1.6 | Docs site (MCP-installer audience) | None |
| 1.7 | Launch | All above |

### Phase 2: v1.5 hosted premium add-on

| Step | Scope | Depends on |
|---|---|---|
| 2.1 | Premium tier billing — extends Phase 1.4 Stripe surface with separate SKU for `jobs+alerts+timesfm` bundle | Phase 0.5 schema, Phase 1.4 billing |
| 2.2 | Expose `jobs-mcp`, `alerts`, `timesfm` tools via existing hosted MCP endpoint, gated by Premium entitlement (extension of Phase 0.2 manifest) | Phase 0.2 manifest, Phase 1.1 aggregation gateway |
| 2.3 | Per-job cost accounting + alert delivery (Telegram/iMessage/email) wiring | Phase 0.4 rate-limit infra |
| 2.4 | Premium launch | All above |

**No Bridge phase, no local pip package, no file metadata sync.** v1.5 is purely additive on the existing hosted infrastructure.

### Deferred to post-v1.5

- Bidirectional file sync (Dropbox-style)
- Selective tool scoping via URL params (`?scope=research`)
- Multi-namespace bundle option (Option B — split into hank-portfolio/hank-research/hank-edgar) if customer demand surfaces

---

## Supersedes / Related

### Supersedes for this audience

- `docs/planning/PORTFOLIO_MCP_EXTRACTION_PLAN.md` (B4) — the OSS-extraction direction. Reasoning: independent-investor audience doesn't want pip install + bring-your-own-Postgres + Docker compose. They want one `claude mcp add` command. The B4 plan was solving the wrong problem for this audience. B4 remains valid for a self-host audience (devs, sovereignty-minded users) but is deprioritized in favor of the hosted-bundle direction.

### Linked / not superseded

- `docs/planning/launch/OPEN_SOURCE_LAUNCH_STRATEGY.md` — parent strategy doc. Three deliverables: Platform, Agent, Web App. This plan refines the Platform deliverable for the independent-investor segment.
- `docs/planning/launch/OPEN_SOURCE_LAUNCH_GAPS.md` — gap analysis. A1/A2/A3 shipped (foundational); B2 Docker Compose still in scope for self-host audience; B1 Stripe required for this plan too; C1 gateway model abstraction is parallel work.
- `docs/planning/STRIPE_INTEGRATION_PLAN.md` (B1) — required for billing surface
- `docs/planning/HANK_RELEASE_SEQUENCING_PLAN.md` — V1.1 pricing decision blocks this plan
- `docs/planning/SKILLS_SYSTEM_DESIGN.md` (completed/) — relevant for understanding how skill files compose tool calls; Hank Platform customers will write their own skill files referencing Platform tool names

### MCP servers in scope

In-bundle: `portfolio-mcp`, `research-mcp`, `research-workbench-mcp`, `edgar-financials`, `fmp-mcp`, `macro-mcp`, `fred-mcp`, `options-mcp`
v1.5 hosted premium: `jobs-mcp`, `alerts`, `timesfm`
Excel-add-in-only (NOT exposed on Platform): `model-engine` family + portfolio-mcp model-adjacent tools (`build_model`, `get_model_build_context`, `get_model_insights`, `get_price_target` — pending Phase 0.2 verification)
Standalone only: `ibkr-mcp`

---

## Next Actions

1. Launch audience-validation activities (landing page, signal harvesting, Fifth Avenue pilot, Hank consumer survey) — see "Audience" section. Anti-signal kills this plan; do NOT begin Phase 0 implementation until validation lands.
2. Decide remaining commercial questions Q3 (trading default — recommended read-only opt-in), Q6 (entry-point naming — recommended `platform.hank.investments`); exact $/mo numbers (V1.1 pricing decision currently `BLOCKING` in `docs/TODO.md`). Q1/Q2/Q4/Q5 resolved via r6.
3. Decide Phase 0 architectural questions Q7–Q9 (auth shape, scope-model granularity, rate-limit model) — these gate Phase 0.1 / 0.2 / 0.4
4. Refresh `docs/planning/STRIPE_INTEGRATION_PLAN.md` to cover Standard/Pro tiering + premium-scope-inside-Pro + Hank consumer credit-based billing at vNext (was single Free/Pro only)
5. Begin Phase 0 implementation per the 6 steps in Sequencing (auth subsystem, exposure manifest, brokerage binding portal, rate-limit extension, billing schema, Codex review gate)
6. After Phase 0 Codex PASS, begin Phase 1 implementation
