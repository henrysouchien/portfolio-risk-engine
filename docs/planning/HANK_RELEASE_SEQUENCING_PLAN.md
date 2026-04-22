# Hank Release Sequencing Plan — Product + Benchmarks

**Created:** 2026-04-19
**Status:** Draft — strategic framing doc, pre-implementation
**Scope:** High-level sequencing for commercial launch across v1 → v3, pairing each stage with benchmark strategy
**Precedent:** Built on Fintool's GTM trajectory (see `docs/research/fintool/gtm-trajectory.md`). Gap audit context in `BETA_RELEASE_GAP_AUDIT.md`.

---

## 1. Purpose

Lock the sequencing shape for going to market — what we launch first, what follows, how benchmarks pair with each stage, and what discipline keeps the dual-product option (Hank + future Research platform) alive.

Not a tactical implementation plan. That comes per-stage, after this shape is agreed.

---

## 2. Guiding principles (from Fintool's actual trajectory)

1. **One product = one analyst verb.** Fintool v1 was literally only "ChatGPT + EDGAR" (filings Q&A). They did not launch a platform. Each later product (Screener, Feed, Spreadsheet Builder, V5 agentic) was shipped separately as a standalone thing.
2. **Benchmark + essay is the launch, not the press release.** Fintool's inflection moments were 80% content/benchmark events (essays, FinanceBench 97%, Finance Agent Benchmark 90%, case studies), 20% product launches. Product launches without benchmark narratives would have been invisible.
3. **External benchmarks for credibility, own benchmarks for differentiation.** FinanceBench (Patronus AI, external) gave Fintool a credibility anchor. Finance Agent Benchmark (Fintool-created) let them tell their specific story and capture SEO. Both are needed.
4. **Prosumer trajectory is real.** Fintool's Feb 2024 early users included hobbyist investors. Institutional positioning came later. Do not force institutional-only at launch.
5. **Capital + team discipline.** $7.24M raised, 7 people, sold to Microsoft. This is a template, not a caution. Stay tight.
6. **Platform discipline preserves dual-product option.** New capabilities live in shared layers (`AI-excel-addin` research backend, `Edgar_updater` data layer). Hank-product is a skin + voice + skill bundle on top. This preserves the option to unveil a second product (general Research) on the same stack at near-zero marginal cost post-v1. See `BETA_RELEASE_GAP_AUDIT.md` for the Platform / Hank-product / Shared taxonomy.

---

## 3. Sequencing overview

| Stage | Months | Lead verb | Product frame | Platform layer work |
|---|---|---|---|---|
| **v1** | 0-3 | Analyze + Act | "Hank — personal AI investment analyst that can actually do things" | Stable-prefix caching audit, skills surface, eval harness (all 🟦 P) |
| **v2** | 3-9 | Research + Monitor | Extend Hank with filings Q&A + Feed | Citation-first Q&A, NL screener, Feed engine (all 🟦 P) |
| **v3** | 9-18 | Produce | Office-format deliverables (Excel/Word/PPT from agent) | Multi-format artifact pipeline (🟦 P) |
| **v4** | 18-24 | (Dual product) | Unveil general Research product on shared platform, separate brand | No new platform work; repackaging |

Platform assets complete by end of v3. v4 is a product/positioning layer, not new infrastructure.

---

## 4. Stage v1 — "Analyze + Act"

### Product

- **Headline (locked 2026-04-19):** *"Your portfolio. Analyzed. Executed."*
- **Primary positioning angle (Angle A):** "Your portfolio. Analyzed. What to do about it." — the risk + factor + hedge recommendation story. Answers the universal *"is my portfolio okay?"* question.
- **Secondary positioning angle (Angle B):** "The AI analyst that actually does the work." — the action surface (tax harvest, rebalance, hedge, trade preview). Proves Hank is different from Fintool-class research tools and from robo-advisors.
- **Brand voice:** Hank voice rule per `BRAND.md` — "Hank doesn't hedge. Hank says the thing."
- **Scope:** Everything currently ✅ shipping in `risk_module` (portfolio analytics, brokerage integrations, risk/factor/stress/MC/optimize/hedge/tax/income/options, research workspace, handoff artifact). **Zero new features for v1 launch.**
- **NOT in scope for v1:** filing Q&A chat surface, NL screener, alerts/Feed, Word/PPT output, thesis living artifact. Those come in v2/v3.
- **Distribution:** Free tier + "talk to us" premium. No self-serve paid checkout. Follows Fintool's pattern.
- **Benchmark pairing:** PDB v1 is the lead benchmark (maps to Angle A). APTB v1 is the companion benchmark (maps to Angle B). Both land within v1's 0-6 month window.

### Benchmarks

**Existing (agent-wrapper-beats-raw-model demonstrations — PRIMARY commercial story):**

- **Vals AI Finance Agent v1.1** (Vals AI) — ⭐ **v1 primary external target.** 537 expert-authored questions (50 public, 337 private), 9 categories of analyst work. Current raw-model ceiling: **Claude Opus 4.7 = 64.4%** (cited in Anthropic's April 15 2026 release). Fintool publicly reported **90%** on this benchmark (agent wrapper) vs Sonnet 4.5's 55% raw = **+35pp demonstrated gap**. This is the finance equivalent of "Claude Code beats raw Claude on SWE-bench." MIT-licensed harness on GitHub. Plan: `VALS_FINANCE_AGENT_RUN_PLAN.md`. Story shape: *"Hank beats raw Opus 4.7 by X pp on the same underlying model."*
- **MCP-Atlas** (Scale AI) — tool-use benchmark. Tests our 80+ MCP tool surface directly. Raw Opus 4.7 = 77.3%. No agent-wrapper-beats-raw-model demonstration exists here yet — **first-mover opportunity** on this benchmark. Runs week 2 after Vals.

**Existing (run later — legacy credibility floors):**

- **FinanceBench** (Patronus AI) — 150 Q&A pairs over filings. **Demoted from v1 primary 2026-04-20.** Saturated at the top (Fintool 97-98%), no current-model baselines tracked. Runs sprint 3 after Vals + MCP-Atlas. Still useful as credibility floor ("≥92% on FinanceBench"). Plan: `FINANCEBENCH_RUN_PLAN.md`.
- **FinQA** — numerical reasoning over financial reports. Technical appendix only.

**Own (category-defining — THE v1 headlines):**

- **Portfolio Diagnosis Benchmark** (PDB v1)
  - 100 test portfolios across diverse risk profiles, factor exposures, concentration levels, asset mixes
  - Answer keys from CFA panel + professional risk tools (Morningstar Direct, Bloomberg PORT risk model) as baselines
  - Score dimensions: factor decomposition agreement, risk score agreement, hedge recommendation rank correlation, concentration flag accuracy
  - Headline soundbite: *"Hank's portfolio risk assessment matches a CFA panel within X% across 100 diverse portfolios"*
  - Publish: GitHub repo + landing page + open leaderboard with ChatGPT/Claude/Perplexity baselines

- **Agent Portfolio Task Benchmark** (APTB v1)
  - 50 standardized tasks — task-completion benchmark (similar shape to τ-bench but finance-specific)
  - Example tasks: "harvest losses respecting wash-sale in taxable account," "rebalance to target allocation with tax-aware trading," "hedge concentrated position using options," "generate income projection with event calendar integration"
  - Success measured: did the output trade list / analysis achieve the task goal under realistic market data? Binary per task, aggregated to completion rate.
  - Headline soundbite: *"Hank completes portfolio tasks in under 2 min that take a human advisor 40+ min, with 95% accuracy across 50 standardized workflows"*
  - Publish: GitHub repo + landing page + open leaderboard

### Content cadence

Mirroring Fintool's Oct 2024 "Warren Buffett as a Service" moment:

1. **Month 0-1** — Soft launch to existing network. No public announcement.
2. **Month 1-2** — First architecture essay: *"The Personal AI Investment Analyst"* (or similar) — manifesto establishing what Hank is, what the category is, why portfolio-opinionated is distinct from Fintool's research-agent frame.
3. **Month 2-3** — Benchmark launches: PDB v1 + APTB v1 with published scores.
4. **Month 3+** — Steady cadence: one technical essay per month, one case study per quarter, one podcast per quarter. No other product launches during v1.

### Team + capital

- No new hires for v1. Ship with existing team.
- No fundraise for v1. Existing runway carries us.
- Founder-led sales. No salesperson hire.

### v1 exit criteria (to justify starting v2)

- 100+ paying/active users (prosumer, institutional, or mix)
- Both benchmarks published with ≥1 external citation
- 1+ third-party case study published (Anthropic, SnapTrade, Plaid, Braintrust, Datadog — anyone upstream)
- At least 3 essays gone modestly viral (HN front page, 10K+ X views, or similar)

---

## 5. Stage v2 — "Research + Monitor"

### Product

- **Frame:** "Hank now reads filings for you, answers questions with citations, and surfaces what changed across your holdings."
- **Scope additions:**
  - Citation-first filing Q&A chat surface (T1.1 from gap audit) — 🟦 P
  - Alert / Feed for watchlist + portfolio (T1.2) — 🟦 P engine + 🟧 H portfolio-scoped prompt bundle
  - NL qualitative screener over filings universe (T2.2) — 🟦 P
- **Product shape:** Hank v1 + three additions. Not a new product — features added to the existing surface. But each addition gets its own landing page and its own sub-launch.

### Benchmarks

**Existing (now the primary credibility story):**

- **FinanceBench becomes the hero here.** This is when we're on Fintool/MSFT's turf — filings Q&A. A ≥95% score is the table stakes to be credible. Pair it with our architectural differentiation (agentic filesystem search, post-RAG Obituary) — "we match the category leader on a different architecture."
- **FinQA, TAT-QA, ConvFinQA, BizBench, Vals AI Finance Agent Benchmark** — run on all of them, publish scores. Each adds a facet. Publish a single "Hank on every public finance benchmark" landing page for SEO capture.

**Own (gap-filling):**

- **Portfolio-Integrated Research Benchmark** (PIRB v1)
  - Tests the cross-reference between a research question and the user's actual holdings
  - Example: *"What disclosed risks in my top 5 holdings' most recent 10-Ks could materially affect a concentrated position?"*
  - Nothing existing tests this integration — Fintool/Hebbia/AlphaSense were all portfolio-agnostic
  - Score dimensions: accuracy of citation, relevance to holdings, actionability of the finding

### Content cadence

- **Month 3-4** — Architecture essay: *"Filings Q&A After RAG — Agentic Filesystem Search for Finance"*. Analog to Fintool's "RAG Obituary" positioning but applied to our implementation.
- **Month 4-5** — Feed launch + essay on "Monitoring as a workflow, not a notification"
- **Month 5-6** — NL screener launch + essay on universe-scale qualitative query
- **Month 6-9** — Benchmark extension essays + additional case studies

### Team + capital

- Maybe 1-2 engineering hires during v2 (specifically for citation UX + Feed delivery infrastructure)
- No sales hire
- Possible small bridge round if needed — aim for <$5M total raised cumulatively

---

## 6. Stage v3 — "Produce" (V5-analog)

### Product

- **Frame:** "Hank generates the deliverable your boss actually wants — the Excel model, the Word memo, the PowerPoint deck."
- **Scope additions:**
  - Word memo export from handoff artifact (T1.3, partial)
  - Excel model integration deepened (already partially shipping via `AI-excel-addin`)
  - PowerPoint deck generation (T1.3 completion)
  - Long-running agent job orchestration (Temporal-style)
- **This is the acquisition-bait stage.** Fintool shipped V5 in Jan 2026 and was acquired by April 2026. The Office-output frame is specifically what makes Microsoft / Bloomberg / BlackRock / SS&C / etc. view us as a strategic asset.

### Benchmarks

**Existing:** Thin for this capability. FinQA numerical reasoning is adjacent but not a real model-accuracy test.

**Own (category-defining):**

- **Model Accuracy Benchmark** (MAB v1)
  - Build DCF for N companies (start N=50)
  - Score against analyst-built models from public sell-side research where available; rubric-based score where not
  - Score dimensions: structural correctness, driver identification accuracy, valuation output within range, formula-dependency integrity
  - Landing page + leaderboard including Claude-in-Excel, MS Copilot, Shortcut AI

### Content cadence

- **Month 9-12** — Architecture essay on agentic Office-output pipeline. Analog to Fintool's V5 announcement.
- **Month 12-15** — Model Accuracy Benchmark launch + "Reverse Engineering AI Model Builders" essay (analog to Fintool's "Reverse Engineering Excel AI Agents")
- **Month 15-18** — Partnership/integration essays. Strategic positioning for acquisition or Series B.

### Team + capital

- Possibly grow to 8-10 people by end of v3
- Possible Series A ($5-10M) between v2 and v3 if we need to accelerate — or stay capital-efficient and let the product do the fundraising
- Hire at most one BD/partnerships person during v3. Still no dedicated sales org.

---

## 7. Stage v4 — Platform product unveil (optional)

### Decision gate

By end of v3, decide: do we unveil the **Research product** (non-portfolio-opinionated version for consulting / IB / sell-side / corp dev) as a second product on the shared platform?

Factors in the decision:
- Hank traction (is it still the primary business, or plateaued?)
- Strategic conversations (is acquisition the likely exit, or standalone growth?)
- Team capacity (can a 7-10 person team run two products?)

### If yes

- Separate brand, separate positioning ("AI research platform for finance professionals" — not investor-specific)
- Different skill bundle (no portfolio skills; comp analysis / pitch prep / industry mapping / M&A diligence skills)
- Different go-to-market (direct sales into consulting/IB/corp dev)
- Shared platform infrastructure, shared benchmark credibility

### If no

- Continue investing in Hank depth (more brokerage integrations, more asset classes, international, crypto)
- Platform stays internal

---

## 8. Consolidated benchmark roadmap

**Updated 2026-04-20** after `docs/research/fintool/agent-benchmarks-landscape.md` research. Vals AI Finance Agent replaces FinanceBench as v1 primary.

| Stage | External (role) | Own benchmark designed + published (role) |
|---|---|---|
| v1.0 (month 0-1) | **Vals AI Finance Agent v1.1 public 50 — HERO** ("Hank beats raw Opus 4.7 by X pp") | — |
| v1.0 (month 1-2) | **MCP-Atlas — validates tool-surface** (raw Opus 4.7 = 77.3%) | — |
| v1.0 (month 2-3) | FinanceBench — credibility floor (≥92% target) | **PDB v1 design + publish — v1 HEADLINE own-benchmark** |
| v1.5 (month 3-6) | Engage Vals AI for private 337 test samples | **APTB v1 design + publish — v1 SECONDARY HEADLINE** |
| v2.0 (month 6-9) | + FinQA, ConvFinQA, BizBench, GDPval finance subset | + **Portfolio-Integrated Research Benchmark (PIRB v1)** |
| v3.0 (month 12-18) | (extensions / updates) | + **Model Accuracy Benchmark (MAB v1)** |

**Role of each column:**
- **External benchmarks** = credibility floor. Run them early. Don't lead with them unless we're on the incumbent's turf (v2).
- **Own benchmarks** = headline story. Open-source artifact (repo + leaderboard + landing page). Category-defining.

**The benchmark-ownership playbook (from Fintool):**
1. **Phase 1 — Crush the established external benchmark.** Credibility inside the existing category. (Fintool: FinanceBench 97%.)
2. **Phase 2 — Create your own benchmark where you're uniquely advantaged.** Moves the frame. Now the conversation is about what *you* measure. (Fintool: Finance Agent Benchmark 90%.)
3. **Phase 3 — Get third parties to adopt or endorse your benchmark.** Academics, industry bodies, competitors reference it. Now it's "the benchmark the category uses," not "your marketing benchmark."

For Hank: v1 is mostly Phase 2 (PDB + APTB as own benchmarks in fresh categories) with Phase 1 floor running quietly. v2 fully enters Phase 1 on filings-Q&A turf. v3+ pushes toward Phase 3.

**Four own-benchmarks by end of v3.** Each creates an SEO moat + thought-leadership artifact + sales collateral.

---

## 9. Distribution cadence (cross-stage)

Fintool's 12 inflection moments were 80% content/benchmark, 20% product launches. Our target:

| Content type | Target cadence |
|---|---|
| Architecture/technical essay (Substack + blog) | Monthly, 12 per year |
| Benchmark launch + landing page | Quarterly, 4 per year |
| Third-party case study | Quarterly, 4 per year (pursue actively: Anthropic, SnapTrade/Plaid, Braintrust, Datadog, Temporal) |
| Podcast appearance | Quarterly, 4 per year (targeted: Patrick O'Shaughnessy, Animal Spirits, Yet Another Value Blog, Mostly Borrowed Ideas, On the Tape) |
| Product launch | Per stage (3 over 18 months) |
| Fundraise announcement | At most once per stage |

**Anti-patterns we're explicitly avoiding:**

- Big splashy "Hank 1.0 platform launch" — nobody wants that
- Product Hunt launch as a primary distribution moment (Fintool didn't do one)
- Conference sponsorships / booth presence
- Paid acquisition / performance marketing
- Horizontal AI-for-everything framing
- Pre-PMF sales hires

---

## 10. Team + capital discipline (cross-stage)

| Stage | Target team size | Target cumulative raise |
|---|---|---|
| v1 end | 4-5 | $0-2M |
| v2 end | 6-8 | $2-5M |
| v3 end | 8-10 | $5-15M |

Anchors:
- No salesperson hire before v3
- No marketing hire — founder-led content
- Founder-led sales throughout
- Engineering-heavy composition (Fintool: 6/7 engineering)
- No WFH at v2+ unless strategically necessary (Fintool's discipline)
- Capital efficiency as brand — ties into content story ("how we ship finance AI with 7 people")

---

## 11. Decision gates

Explicit go/no-go moments (can stay, can adjust, can exit):

| Gate | When | Question |
|---|---|---|
| G1 | End of v1 (month 3) | Did benchmarks publish with credible scores? Did first essay go modestly viral? Go → v2. |
| G2 | End of v2 (month 9) | Are Research/Feed additions pulling new user segments, or just retaining existing? If flat: double down on Hank-product depth instead of v3 Office output. |
| G3 | End of v3 (month 18) | Strategic conversations happening? Acquisition interest? Series A happening on capital-efficient terms? Decide: unveil second product (v4), raise + scale, or sell. |

---

## 12. Explicit non-goals for this plan

- Pricing design (separate work)
- Hiring plans in detail (separate work)
- Fundraise pitch deck (separate work)
- Specific customer acquisition tactics beyond content/benchmark pattern
- Legal/compliance (SOC 2, regulatory) — mostly handled separately, but v2+ enterprise will need it
- International expansion — defer post-v3

---

## 13. Open questions to resolve before executing v1

1. **Portfolio Diagnosis Benchmark test set construction** — who builds the answer key? CFA panel is credible but expensive; Morningstar/Bloomberg tools give us a ranking baseline but not ground truth. Do we go both (credibility via panel, repeatability via tool scores)?
2. **APTB task scoring** — binary per task, or rubric-based? How do we handle tasks where multiple valid answers exist (e.g., multiple valid hedge structures)?
3. **Which essay is the v1 "Warren Buffett as a Service" moment?** Architectural manifesto, or positioning essay? Needs to be written before benchmarks launch so benchmarks land in context.
4. **Prosumer-first vs. institutional-first positioning at launch** — Fintool's trajectory was actually prosumer → institutional. Do we commit to that trajectory or try to hit both immediately with segmented landing pages?
5. **Free tier gating** — what's free vs. premium in v1? Needs to be decided before soft launch.
6. **FinanceBench reporting posture at v1** — where does our score live? Technical docs appendix? Benchmark landing page "Also scored X% on FinanceBench"? Silent until v2? And what's our target threshold (≥92%? ≥95%?) before publishing at all?

These are v1 kickoff decisions. This plan doesn't resolve them; it just names them.

---

## 14. Summary

- v1 (0-3 mo): Hank = portfolio analyst that acts. PDB + APTB benchmarks. FinanceBench + FinQA as credibility floor.
- v2 (3-9 mo): Add Research + Monitor. PIRB benchmark. FinanceBench-family as anchor.
- v3 (9-18 mo): Add Office output. MAB benchmark. Acquisition-bait positioning.
- v4 (18+): Unveil Research product on shared platform — optional, decided at gate G3.

**Cross-stage anchor: content + benchmarks + case studies as distribution. Tiny team. Capital efficient. One analyst verb per product. Platform discipline preserves dual-product option.**

We're running Fintool's playbook on our stack, with our wedge (portfolio-opinionated) as the entry point and their acquisition-bait stage (Office output) as our endgame.
