# Beta Release Gap Audit — Hank vs Fintool

**Created:** 2026-04-19
**Context:** Microsoft acquired Fintool on 2026-04-17 (see `docs/research/fintool/`). Acquisition validates AI-agent-for-finance category. This audit maps Hank's four-repo stack against Fintool's customer-paid workflows + Hank's wedge, to prioritize remaining work before beta.
**Scope:** 4 repos — `Edgar_updater/`, `AI-excel-addin/`, `risk_module/`, `investment_tools/`. `investment_system/` is dead.
**Beta target audience:** Prosumer AND institutional (non-exclusive).

---

## Executive summary

**Headline:** Hank is stronger than Fintool on the **portfolio/quant/action** dimensions Fintool never touched, and behind on **citation UX, universe-scale qualitative screening, monitoring/alerts, and multi-format agentic output**. The schema unification plan (R3) is the right spine but is design-only — no contracts shipped yet.

**One-line take on beta readiness:** We have a **working prosumer portfolio analyst** today. To reach institutional bar, three things must ship: (1) citation-first filing Q&A, (2) alert/monitoring surface, (3) Excel/PPT/Word output from the research agent. Everything else is polish.

**Strategic framing:** The same stack that makes Hank viable is also the engine for a **general-purpose Research product** serving consulting, IB analysts, sell-side research, IR/corp dev, private credit — a much larger market than portfolio-only. Fintool was acquired for exactly this kind of platform. Capabilities in this doc are labeled 🟦 **Platform** vs 🟧 **Hank-product** vs ⚪ **Shared** to preserve the option to unveil a second product on the same stack post-beta at near-zero marginal cost. Discipline rule: Platform work assumes no portfolio state; Hank-product work wires portfolio state in at the edge.

---

## Capability matrix

**Scoring:** ✅ ships · ⚠️ partial · ❌ gap · 🔄 in-flight
**Layer:** 🟦 **P** Platform (audience-agnostic; serves any product on the stack) · 🟧 **H** Hank-product (portfolio-opinionated, voice-specific, prosumer-focused) · ⚪ **S** Shared (infrastructure used across layers)

| # | Capability | Source | Status | Layer | Where it lives |
|---|---|---|---|---|---|
| 1 | Q&A over SEC filings + earnings calls **with citations** | Fintool wedge | ⚠️ | 🟦 P | `Edgar_updater` extracts; citation UX not shipped |
| 2 | **Qualitative** screening across universe ("which tech co's discussing AI capex") | Fintool wedge | ⚠️ | 🟦 P | `investment_tools` has quant 7-signal screener, not NL-over-corpus |
| 3 | Feed / alerts / monitoring with custom prompts | Fintool wedge | 🔄 | 🟦 P | `SCREENING_ALERT_INFRASTRUCTURE.md` designed, not built |
| 4 | Data extraction to tables (XBRL, GAAP normalized across universe) | Fintool wedge | ⚠️ | 🟦 P | `Edgar_updater` does per-filing; no cross-company normalization / fiscal calendar DB |
| 5 | Agentic long-runs → **Excel DCF / PPT deck / Word memo** | Fintool V5 (acquisition trigger) | ⚠️ | 🟦 P | `AI-excel-addin` does Excel; PPT + Word don't exist. Engine is platform; templates per product. |
| 6 | Public API for embedding | Fintool wedge | ❌ | 🟦 P | Session-auth only; no multi-tenant/third-party story |
| 7 | Portfolio-opinionated "given your book" analysis | **Hank wedge** | ✅ | 🟧 H | `risk_module` (84 MCP tools) |
| 8 | Live brokerage integration (Plaid/SnapTrade/IBKR/Schwab) | **Hank wedge** | ✅ | 🟧 H | `risk_module` — 4 providers live |
| 9 | Quant risk engine (factor/stress/MC/optimize/hedge) | **Hank wedge** | ✅ | 🟧 H | `risk_module/core/`, `portfolio_risk_engine/`. Generalizable later but portfolio-coupled today. |
| 10 | Action surface (tax/rebalance/options/income) | **Hank wedge** | ✅ | 🟧 H | `risk_module` — all shipping |
| 11 | Research workspace + handoff artifact | Overlap | ✅ | 🟦 P | `AI-excel-addin/api/research/` backend + risk_module UI. Hank uses for investment memos; Research product would use for consulting decks / pitch prep. |
| 12 | Thesis as living artifact | Overlap | ⚠️ | 🟦 P | Design locked in schema plan R3; no code. Applies to any research target, not just portfolio holdings. |
| 13 | Financial model build (DCF, driver trees) | Overlap | ✅ | 🟦 P | `AI-excel-addin/schema/` — FinancialModel + driver mapping |
| 14 | MCP-first agent surface | Overlap | ✅ | ⚪ S | ~90+ tools across 5 MCP servers. Infrastructure is shared; tool bundles differ per product. |
| 15 | Adversarial eval harness (ticker disambig, fiscal periods, fake-number defense) | Fintool table-stakes | ❌ | 🟦 P | Unit tests exist; no domain eval set |
| 16 | Stable-prefix prompt caching audit | Fintool optimization | ❌ | ⚪ S | No audit; ~10× cost opportunity |
| 17 | Citation-blocking-render discipline | Fintool trust pattern | ❌ | 🟦 P | Source chips in handoff F25; not enforced project-wide |
| 18 | User-authored skills surface | Fintool differentiator | ⚠️ | 🟦 P | YAML configs exist. Skills system is platform; individual skills are product-specific (Hank has `/morning`, `/positions`; Research would have `/comp-analysis`, `/pitch-prep`). |

**Summary by layer:**
- 🟦 **Platform (11 capabilities):** 1, 2, 3, 4, 5, 6, 11, 12, 13, 15, 17, 18 — this is the stack that both Hank AND a future Research product inherit
- 🟧 **Hank-product (4 capabilities):** 7, 8, 9, 10 — portfolio math + brokerage integration + action surface. None of this transfers to a general research product.
- ⚪ **Shared (2 capabilities):** 14, 16 — infrastructure discipline, agent surface plumbing

**Key observation:** **most of the unshipped work is Platform.** The Hank-product capabilities are already ✅. The T1/T2 gap work is overwhelmingly Platform investment — meaning the cost to stand up a second product on the same stack is low once we complete it.

---

## Platform / Hank-product / Shared taxonomy

**Why this split exists:** The stack we're building serves a much larger audience than portfolio-opinionated individuals. The same filings + transcripts + corpus index + Excel modeling + research workspace serves consulting, investment banking analysts, sell-side equity research, corporate IR/corp dev, private credit, and VC/PE portfolio monitoring. Fintool was acquired specifically to take this kind of platform horizontal inside Office 365.

**Strategic framing:**
- **Hank-product** = the portfolio-opinionated analyst, tight positioning, prosumer + institutional-PM wedge, voice locked in `BRAND.md`
- **Platform** = audience-agnostic capabilities the same stack provides. Unveilable as a second product immediately post-Hank-beta with a different brand/voice/UX skin. Near-zero marginal cost if platform work is kept product-agnostic.
- **Shared** = infrastructure plumbing that both layers consume

**The discipline that preserves the option:**
1. Build Platform capabilities with no portfolio assumption. Pass user context in; don't reach for broker-connected state.
2. Keep voice/positioning in Hank-product prompts (`BRAND.md`, Hank-specific skill bundle). Platform defaults to voice-neutral.
3. Skills are product-scoped — Hank ships `/morning`, `/positions`, `/changelog`; Research product ships `/comp-analysis`, `/pitch-prep`, `/industry-map`. Same runtime, different bundles.
4. New platform work lives in `AI-excel-addin` (research backend + modeling) and `Edgar_updater` (data layer). `risk_module` is where Hank-product-specific code goes.

### Repo ownership under this taxonomy

| Repo | Predominantly | Notes |
|---|---|---|
| **`Edgar_updater`** | 🟦 Platform | Pure data layer. Audience-agnostic. Keep it that way. |
| **`AI-excel-addin`** | 🟦 Platform (mostly) + ⚪ Shared | Research backend, modeling studio, cross-repo schema source-of-truth. Some UI is Hank-themed today; split later. |
| **`risk_module`** | 🟧 Hank-product (core) + 🟦 Platform (workspace UI) | Portfolio analytics + brokerage + Hank UI. The research workspace UI inside `risk_module` is Platform-style but currently Hank-branded. |
| **`investment_tools`** | 🟦 Platform | Screener, options analysis, macro — all audience-agnostic. Open question whether it stays standalone or gets absorbed. |

**Rule of thumb for new work:** if a capability needs portfolio positions to function, it's 🟧 H. If it works with just tickers / companies / documents, it's 🟦 P. When in doubt, make it P — you can always wrap it in Hank-specific glue later, but un-Hankifying Platform code is expensive.

---

## What ships today (the floor we're starting from)

| Repo | What users get today |
|---|---|
| **risk_module** | Full prosumer portfolio analyst: connect broker → positions → risk score → stress / MC / optimize / hedge / tax harvest / income projection / rebalance / options analysis. Research workspace with handoff artifact (F25 design pass done). OAuth sign-in. 84 MCP tools + FastAPI + React frontend. |
| **Edgar_updater** | SEC filing extraction: 9 MCP tools (filings metadata, XBRL financials, specific metrics, metric time series, narrative sections, custom extraction schemas). Excel/VBA pipeline for offline updates. |
| **AI-excel-addin** | Office.js taskpane for Excel, FastAPI backend hosting research workspace + modeling studio. FinancialModel schema + driver mapping + SIA template. 6 MCP servers including excel-mcp, model-engine, sheets-finance-mcp. **Owns the Pydantic source-of-truth for the 6 cross-repo contracts per schema plan.** |
| **investment_tools** | 7-signal quality screener CLI, IBKR options open-interest analysis, insider/institutional tracking, Jupyter-style research notebooks. FRED macro data. |

**Combined surface:** ~90+ MCP tools, 4 brokerage integrations, full SEC filing pipeline, Excel add-in for modeling, portfolio + research workspace UI. **This is substantial.** We're not starting from zero — we have more surface area than Fintool had at Series A.

---

## Tier 1 — beta blockers (must close to be institutional-credible)

These three are the difference between "impressive prototype" and "we could sell this alongside what Fintool sold."

### T1.1 — Citation-first filing Q&A · 🟦 Platform

**Why blocker:** The #1 Fintool trust pattern. Every number clicks to a source span with highlight. Missing or malformed citations **block render**, not degrade silently. We extract filings; we don't have the citation UX.

**What exists:**
- `Edgar_updater/` has `get_filing_sections` + `extract_filing_file` — we can pull narrative + tables
- `AI-excel-addin/api/research/` has `sources[]` registry in handoff artifact (per schema plan §6.2)
- F25 handoff report renderer has source chips

**What's missing:**
- A chat UX that asks filing-scoped questions and streams answers with inline `[S1]` chips
- Click-to-source span iframe (Fintool's span-iframe pattern)
- Server-side citation validation that blocks response if claim has no source
- Extension of source-chip discipline from handoff artifact → general chat surface

**Effort estimate:** 2-3 weeks. Frontend chat component + backend validation gate + span-scroll integration.

### T1.2 — Alert / monitoring Feed · 🟦 Platform (engine) + 🟧 Hank-product (portfolio-scoped prompt bundle)

**Why blocker:** HN signal (2024) and every Fintool case study confirms: **alerts drive daily engagement**. Filing Q&A is episodic; alerts are persistent. Fintool's Feed was the retention surface.

**What exists:**
- `SCREENING_ALERT_INFRASTRUCTURE.md` (investment_tools) — design, not built
- `WATCHLIST_MIGRATION_PLAN.md` (risk_module) — design, not built
- `RESEARCH_BRIEFING_DISPATCH_PLAN.md` (risk_module) — design, not built
- Redis/Celery infrastructure exists for background jobs
- Telegram/email delivery via `alerts` folder at top level (already built for internal use)

**What's missing:**
- User-per-watchlist custom-prompt configuration
- Filing webhook → prompt eval → summary → delivery pipeline
- UI for managing watchlists + prompts + delivery channels
- "What changed" diff UX for repeat filings (10-Qs)

**Effort estimate:** 3-4 weeks. The pieces exist; the integration + UX is the work.

### T1.3 — Agentic long-run → multi-format output · 🟦 Platform (engine) + 🟧 Hank-product (thesis-memo / portfolio-review templates)

**Why blocker:** Fintool V5 shipped DCF-in-Excel + deck-in-PPT + memo-in-Word. Microsoft bought them ~3 months later. **The Office output format is what pro users hand to their PM** — it's literally the acquisition-trigger feature.

**What exists:**
- Excel: `AI-excel-addin` can build models; `model-engine` MCP can populate templates; SheetsFinance formula generation works
- Word: handoff report renderer (F25) produces structured markdown — close, but not `.docx`
- PPT: nothing

**What's missing:**
- Long-running agent job orchestration (Temporal-style, per Fintool pattern)
- `.docx` export from handoff artifact (thesis memo)
- `.pptx` export from research session (earnings deck / portfolio review)
- `artifact://` link scheme so agent output opens in UI with viewer

**Effort estimate:** 4-6 weeks. Word is fastest (markdown → python-docx). PPT needs template design. Orchestration layer is the real work.

---

## Tier 2 — table-stakes improvements (narrows gap, shippable in parallel)

### T2.1 — Adversarial eval harness · 🟦 Platform

**Why:** Fintool gate every PR on ~2K domain eval cases including **fake-number injection attacks**. We have unit tests, nothing domain-specific. Institutional buyers will ask "how do you prevent hallucination on financial numbers?"

**Required cases:**
- Ticker disambiguation (Apple vs APLE, Meta vs MSTR, Delta airline vs "delta hedging")
- Fiscal period normalization (Apple Q1 = Oct-Dec, Microsoft Q2 = Oct-Dec, most others calendar)
- Numeric precision (`$4.2B` vs `$4,200M` vs "four point two billion")
- Adversarial grounding — plant fake numbers in docs near real 10-K citations, verify agent cites the real one
- CI-block PR if eval regresses >5%

**Effort:** 3 weeks. Mostly authoring cases; the harness is small.

### T2.2 — Qualitative NL screener over filings universe · 🟦 Platform

**Why:** Fintool's primary wedge over Perplexity/ChatGPT was *"which tech companies are discussing capex for AI initiatives?"* run against 8,000 companies with 1-minute filing latency. Our 7-signal quant screener is different — numeric filters, not NL-over-corpus.

**What exists:**
- `Edgar_updater` has filings corpus
- `get_filing_sections` exposes narrative sections
- `investment_tools` has screener infrastructure

**What's missing:**
- Cross-company filing index (searchable by natural language, not just ticker)
- NL query → filing-corpus scan → evidence-tagged ticker list
- Universe-scoped scheduling (doesn't need to run in 1 min for beta; weekly cadence is fine)

**Effort:** 3-4 weeks. Heavy on retrieval architecture (see T2.6 on RAG-vs-agentic tradeoff).

### T2.3 — Stable-prefix prompt caching audit · ⚪ Shared

**Why:** Fintool's LLM Context Tax post documented **~10× input token cost reduction** with stable-prefix caching. Rule: byte-stable system prompt + tools at front, dynamic content (timestamps, user query) at end. Cache lives 5-10 minutes.

**What exists:** We use Anthropic's API with caching available.

**What's missing:**
- Audit of our MCP tool schemas for byte-stability across requests
- Audit of system prompts for timestamp/dynamic-content drift
- Monitoring for cache hit rate

**Effort:** 1 week audit + incremental fixes.

### T2.4 — Skills surface reframe · 🟦 Platform (runtime) + product-scoped skill bundles

**Why:** Fintool's biggest architectural claim: *"The model is not the product. The skills are now the product."* Markdown + YAML frontmatter, SQL-discoverable, copy-on-write per-user shadowing. Non-engineers (analysts, customers) author them.

**What exists:** We already have YAML-backed configs — factor proxies, stress scenarios, instrument configs, `driver_mapping.yaml`. The architecture bones are there.

**What's missing:**
- Unified `skills/` directory convention
- Skill file header (name, description, scope) — YAML frontmatter
- SQL-discoverable index (`fs_files` table or equivalent)
- Private/shared/public tier model for multi-user
- UI/CLI for users to browse + author skills
- Concrete analyst skills to ship with: `/morning` (portfolio brief), `/changelog` (session log), `/positions` (cross-broker pull with flags)

**Effort:** 2-3 weeks. Mostly packaging + UX, the pieces exist.

### T2.5 — Fiscal calendar normalization DB · 🟦 Platform

**Why:** Fintool maintains 10K+ company fiscal calendar DB. "Q1 2024" without normalization silently breaks cross-company comparisons. We don't have this.

**What exists:** `Edgar_updater` has fiscal period metadata per-filing.

**What's missing:** Cross-company fiscal-year registry + normalizer that maps "Q1 2024" → absolute date range based on ticker's fiscal calendar.

**Effort:** 1-2 weeks. Can be bootstrapped from EDGAR metadata.

### T2.6 — RAG-vs-agentic decision for filings corpus · 🟦 Platform

**Why:** Fintool threw out their 500GB Elasticsearch / hybrid / rerank pipeline and moved to Claude-Code-style grep-over-filesystem with frontier context models. Post-retrieval era. We haven't decided.

**Current state:** `Edgar_updater` has extraction but no canonical retrieval architecture yet. `LANGEXTRACT_REFACTOR_FILING_INGESTION_PLAN.md` (in-flight) is our opening move.

**Decision required:** Given the RAG Obituary + our solo/prosumer economics, **don't build a vector DB**. Mount filing corpus on filesystem, let agent navigate with ripgrep + glob.

**Effort:** Decision is free; architectural commit saves us months of vector-DB work.

---

## Tier 3 — defer beyond beta (Fintool had it, not our wedge)

| Capability | Why defer |
|---|---|
| Public multi-tenant API | Strategic question, not a technical one. Fintool's API was B2B embed; ours would be a different product. Ship prosumer/institutional-direct first. |
| Universe-scale XBRL-to-table extraction | Fintool's "pull into Excel table" workflow is powerful but 10Kx heavier than what most Hank users need. Revisit after T1/T2. |
| PowerPoint deck output | Word memo + Excel model covers 80% of pro handoff. PPT is polish. |
| GraphRAG / knowledge graphs | Fintool was exploring; not obviously load-bearing for our wedge. |
| OpenAI partnership on SEC extraction | Fintool-specific; we can ship without. |

---

## Schema unification role

`INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` R3 is **design-only**. 6 typed contracts: `InvestmentIdea`, `HandoffArtifact v1.1`, `ModelBuildContext`, `ModelInsights/PriceTarget/HandoffPatchOp`, `ProcessTemplate`, `Thesis/ThesisLink/ThesisScorecard`. Ownership in `AI-excel-addin/schema/`. 10 follow-on implementation plans listed.

**How it relates to beta:**

- The schema plan is **enabling infrastructure**, not a beta deliverable. None of it is user-facing.
- The **Thesis living artifact** pattern (G13 / `THESIS_LIVING_ARTIFACT_PLAN`) is arguably the highest-leverage piece — it's the "centering artifact every other view adjusts." If shipped, it closes the loop on research→model→portfolio and becomes a genuine differentiator.
- T1/T2 items above are **compatible with the schema plan** — they slot into the right contracts (citations → `sources[]`, alerts → `InvestmentIdea` provenance, agentic output → `HandoffArtifact` + `ModelInsights`, skills → referenced in `ProcessTemplate`).

**Recommendation:** Parallel-ship the schema work (Thesis + HandoffArtifact v1.1 as per the plan's dependency order) alongside T1 beta blockers. Don't wait for full schema migration before starting T1.

---

## Recommended beta scope

Organized by layer so the dual-product sequencing is explicit.

### 🟦 Platform deliverables (also unlock a future Research product)

- T1.1 **Citation-first filing Q&A** — platform capability, Hank uses for research workspace chat, Research-product uses as primary surface
- T1.2 **Alert / monitoring Feed** (minimal: watchlist + prompt + weekly email) — platform engine; Hank bundles portfolio-prompts, Research-product bundles coverage-prompts
- T1.3 **Word memo + Excel model** output from handoff agent — platform engine; Hank ships investment-memo templates, Research-product ships pitch/comp templates. PPT deferred.
- T2.1 **Adversarial eval harness** — platform trust infrastructure
- T2.3 **Prompt caching audit** — shared cost discipline
- T2.4 **Skills surface reframe** — platform runtime; Hank ships `/morning`, `/changelog`, `/positions`; Research product ships `/comp-analysis`, `/pitch-prep`, `/industry-map` in its own bundle
- **Thesis living artifact** (from schema plan) — platform centerpiece; works for any research target

### 🟧 Hank-product deliverables (beta-shipped, not transferable)

- Everything currently shipping stays shipping (portfolio analytics, brokerage, handoff report, SEC extraction, MCP surface)
- Hank voice/positioning locked per `BRAND.md`
- Hank-specific skill bundle (`/morning`, `/positions`, `/changelog`)
- Hank-specific UI (dashboard, positions, scenarios, research workspace Hank-skin)

### Out (post-beta)

- T2.2 Universe NL screener (platform capability but not beta table-stakes; 7-signal quant screener suffices for v1)
- T2.5 Fiscal calendar DB (bootstrap from EDGAR per-query, formalize later)
- Full schema unification implementation (ship minimum viable slice)
- PPT export
- Public API
- **Research product unveil itself** (platform assets are ready at end of beta; Research-product skin + positioning + go-to-market come T+1 month)

### Timeline

Assuming two parallel workstreams:
- Weeks 1-3: T1.1 (citation Q&A) + T2.4 (skills reframe) — **all 🟦 P**
- Weeks 3-6: T1.2 (alerts) + T2.1 (eval harness) + T2.3 (caching audit) — **all 🟦 P / ⚪ S**
- Weeks 6-10: T1.3 (Word/Excel agentic output) + Thesis living artifact — **all 🟦 P**
- Weeks 10-12: Beta hardening, Hank-skin polish, end-to-end QA, institutional pilots

**~3 months to institutional-credible Hank beta. Platform assets for a second product are ready at the same moment.**

### The unveil sequence

1. **Beta launch** — Hank ships, institutional pilots running, prosumer onboarding live
2. **T + 1 month** — Research product surfaces: same platform, different front door (different brand, different skill bundle, different positioning, different sales motion). No re-architecture required if platform discipline held.
3. **Dual motion ongoing** — prosumer funnel for Hank, institutional/consulting/IB direct sales for Research product. Shared infrastructure investment, two revenue lines.

---

## Risks / things to watch

1. **Schema plan is R3 draft, no code** — slipping on implementation drags every Tier 2 item. Keep it parallel, not blocking.
2. **investment_tools is drifting** — agent report flagged it as "more peripheral." Decision needed: is it absorbed into risk_module, or stays standalone?
3. **Multi-user gateway** — `GATEWAY_MULTI_USER_PHASE1_PLAN.md` is separate from this audit but blocks institutional multi-seat deployments. Cross-check timeline.
4. **Eval harness authoring is tedious** — easy to skip, but shipping without it is how we get burned by hallucination post-beta.
5. **Alert delivery** — Telegram/email integrations exist in `alerts/` top-level folder (used internally); confirm they work for external multi-user before betting T1.2 on them.

---

## Honest summary vs agent's optimistic read

The Explore agent scored us "8 of 9 Fintool workflows shipping." **That's too generous.** More honest:

- **3 ✅ ship at Fintool's bar** (portfolio-opinionated analysis, brokerage integration, quant risk engine — and these are our wedge, not overlap with Fintool).
- **5 ⚠️ partial** (citations, NL screener, table extraction, agentic multi-format output, skills surface).
- **3 ❌ gaps** (alerts, public API, adversarial evals).
- **1 🔄 in-flight** (Thesis living artifact via schema plan).

We have more surface area than Fintool had at Series A, but parity on their acquisition-bar capabilities requires the T1 items above. **The good news: those items are weeks of work, not rewrites.**
