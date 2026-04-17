# Editorial Pipeline Audit — Overview Personalization

**Created:** 2026-04-13
**Updated:** 2026-04-13 (reframed from LLM-vs-pipeline comparison to persistent surface personalization)
**Status:** FINDINGS + RECOMMENDATIONS

## Framing

The overview page is not a worse version of the chat briefing. They serve different purposes:

- **The chat briefing** is a conversation you have once. The LLM walks in, tells you what matters, and the response scrolls away. It's great at narrative, synthesis, and pointed questions.
- **The overview page** is the persistent surface you glance at throughout the day. Metrics update live, attention cards stay visible until resolved, margin annotations prompt follow-up whenever you're ready.

**The question is not** "how do we make the overview match the briefing." **The question is:** is the overview's persistent surface — metric strip, lead insight, attention cards, margin annotations, exit ramps, artifacts — personalized to *this user* with *this portfolio* right now?

The LLM briefing experiment is used as a reference point for *what good editorial judgment looks like*, not as a target to replicate.

## Background

The LLM briefing experiment (`LLM_BRIEFING_EXPERIMENT_PLAN.md`, validated 2026-04-07) proved that an LLM with full tool access could produce sharp editorial briefings. The deterministic editorial pipeline (`OVERVIEW_EDITORIAL_PIPELINE_PHASE1_PLAN.md`) was built as the production fast-path. A live comparison on 2026-04-13 revealed significant gaps in the pipeline's output, which were initially framed as "missing vs the briefing" but are better understood as "the persistent surface isn't personalized enough."

---

## Information Sources — Side by Side

### LLM Experiment (chat-based, validated)

The AI called these tools and made a holistic editorial judgment:

| Data source | Tool called | Information used |
|---|---|---|
| Positions | `get_positions()` | Full portfolio state, holdings, weights, flags |
| Risk | `get_risk_analysis()` / `get_risk_score()` | Risk framework gaps, limit violations, risk drivers |
| Performance | `get_performance()` | Benchmark comparison, income progress, alpha, beta |
| Events | `get_portfolio_events_calendar()` | Upcoming earnings, dividends, corporate events (7-day window) |
| Editorial memory | Full `editorial_memory_seed.json` | investor_profile, editorial_preferences (lead_with, care_about, less_interested_in), briefing_philosophy (alert/default state, tone, depth), conversation_extracts, current_focus |

**Key capability:** The experiment made a binary state judgment — "alert" (something broke the risk framework) vs "default" (system is working, show performance + income). This shaped the entire brief's posture, not just individual candidate scores.

### Deterministic Pipeline (shipped Phase 1)

Three generators produce candidates from normalized snapshots:

| Data source | Generator | Information used |
|---|---|---|
| Positions | `ConcentrationInsightGenerator` | Top 10 holdings, weights, HHI, position count |
| Risk | `RiskInsightGenerator` | Volatility, leverage, factor variance %, risk limit violations, risk drivers |
| Performance | `PerformanceInsightGenerator` | Total return, Sharpe, max drawdown |
| Events | **No generator** | — |
| Income | **No generator** | — |
| Trading | **No generator** | — |
| Factor | **No generator** | — |
| Editorial memory | Score modifiers only | +0.15 lead_with, +0.08 care_about, -0.08 less_interested_in (category match) |

**LLM arbiter** (async, best-effort): Rewrites headline, evidence, selection_reasons. Cannot add metrics, change structure, or use additional data sources. Runs after response is sent; enhanced version only surfaces on next page load.

---

## Gap Analysis — Is the Persistent Surface Personalized?

Each gap is evaluated through the lens: **does this prevent the overview from showing the right persistent information for this user and this portfolio?**

Gaps are classified by root cause:
- **SPEC DRIFT** — the Phase 1 plan specified this; the implementation didn't deliver it.
- **PHASE 2 SCOPE** — the design/plan explicitly deferred this to Phase 2.
- **NOT IN PLAN** — neither the design nor plan covered this. Requires new design work.

And by personalization impact:
- **HIGH** — the overview is missing information this specific user needs to see persistently.
- **MEDIUM** — the overview is showing the right topics but not tailored to the user.
- **LOW** — nice to have; doesn't meaningfully affect whether the overview feels personalized.

### Gap 1: Missing Metric Candidates — Beta and Alpha

**Classification: SPEC DRIFT** | **Personalization impact: HIGH**

This user runs a 0.34-beta defensive portfolio with `concentration_risk` and `unintended_factor_exposure` in their concerns. Beta should be a permanent fixture on their metric strip — it's the single number that tells them whether the portfolio is still doing what they designed it to do. Alpha matters because their default-state philosophy is "show me that the system is working" — positive alpha is that confirmation.

The plan specified both (`PerformanceGenerator` owns `"beta"` and `"alpha"` per line 1248). The implementation dropped them.

**Resolution:** Faithful re-implementation. Being addressed by Codex.

### Gap 2: No Events/Calendar Generator

**Classification: PHASE 2 SCOPE** | **Personalization impact: HIGH**

This is where the persistent surface has a natural advantage over the chat briefing. The briefing tells you "MSCI earnings late April" once and it scrolls away. The overview should show a persistent attention card or margin annotation — "MSCI Q1 earnings in 5 days (10% position)" — that counts down and stays visible until the event passes.

Events are the ideal persistent surface content: they're time-bounded, actionable, and specific to the portfolio. The user's `care_about` lists `upcoming_events`, `earnings_dates`, and `dividend_dates`. This user checks the overview to answer "is anything on fire" — an upcoming earnings date for a 10% position is exactly the kind of thing that should be waiting for them.

Explicitly deferred to Phase 2, but the persistence framing makes it a strong candidate for pull-forward.

### Gap 3: No Income Generator

**Classification: PHASE 2 SCOPE** | **Personalization impact: MEDIUM**

This user's `primary_goals` include `dividend_income` and `care_about` includes `income_generation`. Their default-state briefing philosophy is *"Show performance vs benchmark and income progress."* Without an income generator, the overview can only show the risk/concentration story — it can never show the "system is working" side.

For a persistent surface, income progress (yield on portfolio, next ex-dividend dates, income vs target) is the kind of slow-moving, reassuring data that belongs on the overview. It doesn't change minute to minute, but it anchors the user in "this is what the portfolio is doing for me."

Deferred to Phase 2. Lower priority than events for pull-forward because income data changes slowly and the user explicitly said they're less interested in daily PnL swings.

### Gap 4: Alert vs Default State Detection

**Classification: NOT IN PLAN** | **Personalization impact: MEDIUM (revised down from HIGH)**

In the chat briefing, the state call ("DEFAULT state — working defensively but leaving money on the table") was the strongest feature. But the overview doesn't need to announce a state the way a briefing does.

Instead, the persistent surface should naturally reflect the state through which components are active: more attention cards and a risk-focused lead insight in alert mode; a calmer lead insight with income/performance emphasis in default mode. The individual components already do this to some degree — if there are risk limit violations, the attention cards show them. The gap is that there's no holistic signal that shifts the *overall posture* of the page.

Rule-based state detection could still be useful as an input to the policy layer (e.g., alert state boosts risk candidates globally), but it's less critical for the persistent surface than it was for the one-shot briefing. The overview's persistence means the user sees all the signals and forms their own state judgment — they don't need the system to announce it.

**Resolution:** Nice to have as a policy-layer input. Not a top priority.

### Gap 5: Shallow Editorial Memory Usage

**Classification: PARTIAL SPEC DRIFT + NOT IN PLAN** | **Personalization impact: HIGH**

This is the core personalization gap. The editorial memory has five sections; the pipeline uses one (score modifiers from `editorial_preferences`). For a persistent surface that's supposed to be personalized, the other four sections are directly relevant:

| Memory section | What it enables for the persistent surface |
|---|---|
| `editorial_preferences` | Which metric categories to prioritize (implemented — score modifiers) |
| `investor_profile.concerns` | Which metrics should be *always-on* vs competitive. E.g., `concentration_risk` → lead weight is permanent, not competing for a slot |
| `briefing_philosophy` | Default vs alert visual treatment. Tone of lead insight copy |
| `current_focus.watching` | Boost specific tickers into attention cards or margin annotations. "I'm watching VALE" → VALE gets a persistent card |
| `conversation_extracts` | Background context for the LLM editorial pass (not useful for deterministic layer) |

The highest-value additions for the deterministic layer are `investor_profile.concerns` (drives which metrics are always-on) and `current_focus.watching` (surfaces specific tickers). `briefing_philosophy` and `conversation_extracts` are better suited for the LLM editorial pass.

### Gap 6: No "New Information" Awareness

**Classification: NOT IN PLAN** | **Personalization impact: LOW (for now)**

The pipeline tracks `changed_slots` (diff vs previous brief), and the overview shows a "PREVIOUSLY" banner. This partially addresses the "what changed" question. Full new-information awareness (news, filings, price shocks) becomes important when events/news generators exist but isn't blocking today.

The overview already has a natural advantage here: because the user sees it repeatedly, they notice when values change. The "PREVIOUSLY" banner and `changed_from_previous` flags on directives/annotations support this. The gap is real but not urgent.

### Gap 7: No Benchmark Comparison on Metrics

**Classification: NOT IN PLAN** | **Personalization impact: MEDIUM**

For a persistent metric strip you glance at repeatedly, context matters. "Sharpe -1.10" is a number. "Sharpe -1.10 vs 0.77 bmk" tells you something. The old hardcoded strip had this on some metrics; the editorial pipeline dropped it.

This is a schema/design issue: `MetricStripItem` has a single `value` field. Adding a `benchmark_value` or enriching `context_label` with benchmark data would close this. The data is available in the performance snapshot — it's just not being surfaced.

The personalization angle: the benchmark matters more to this user because `performance_vs_benchmark` is in their `care_about` list.

### Gap 8: No Loss Screening / Biggest Loser Detection

**Classification: NOT IN PLAN** | **Personalization impact: HIGH**

PCTY at -39% is exactly the kind of thing that should be a persistent attention card on the overview. Not because the LLM briefing caught it — but because a position down 39% needing a hold-or-harvest decision is something you want *staring at you* every time you open the page, until you take action.

The current generators only see concentration (top holdings by weight) and aggregate risk. No generator screens for the biggest dollar losers, largest unrealized losses, or positions needing exit decisions. This means single-name problems are invisible on the persistent surface unless they also happen to be the largest position.

For a persistent surface, loss screening is arguably the highest-value new generator because:
- Losses are actionable (harvest, sell, or affirm the thesis)
- They're time-sensitive (tax-loss harvest has calendar constraints)
- They persist until resolved — the user should see them every visit
- This user's `concerns` include `position_sizing_drift`, which a -39% position with no action is

**Resolution:** New generator needed — `LossScreeningInsightGenerator` or extending `ConcentrationInsightGenerator` to look at returns, not just weights.

---

### Priority Summary (re-evaluated through personalization lens)

| Priority | Gap | Classification | Why it matters for persistent surface |
|---|---|---|---|
| **P0** | 1. Beta/Alpha metrics | SPEC DRIFT | User's portfolio posture (0.34 beta) needs to be visible permanently |
| **P1** | 8. Loss screening | NOT IN PLAN | PCTY-type problems should stare at you until resolved |
| **P1** | 5. Deep editorial memory | NOT IN PLAN | Core personalization mechanism; `concerns` and `watching` drive what's always-on |
| **P1** | 2. Events generator | PHASE 2 SCOPE | Time-bounded events are the ideal persistent content |
| **P2** | 7. Benchmark comparison | NOT IN PLAN | Persistent metrics need context to be useful at a glance |
| **P2** | 3. Income generator | PHASE 2 SCOPE | "System is working" reassurance for income-focused user |
| **P3** | 4. State detection | NOT IN PLAN | Nice to have for visual treatment; user forms own judgment from persistent signals |
| **P3** | 6. New info awareness | NOT IN PLAN | Partially covered by change tracking; becomes important with events generator |

---

## Metric Strip Comparison

### Old hardcoded strip (7 items, always present)

| # | Metric | Detail line | Source |
|---|--------|-------------|--------|
| 1 | Return | "YTD vs SPY" | summary + performance hooks |
| 2 | Volatility | "annualized" | risk analysis hook |
| 3 | Diversif. / Top wt. | concentration score or "lead position" | positions hook |
| 4 | Beta (SPY) | "market sensitivity" | summary + performance hooks |
| 5 | Max Drawdown | "peak-trough" | summary + performance hooks |
| 6 | Sharpe | "vs X.XX bmk" | summary + performance hooks |
| 7 | Alpha | "vs SPY" | summary + performance hooks |

### Editorial pipeline strip (6 selected from 7 candidates)

| # | Candidate | Generator | Can appear? |
|---|-----------|-----------|-------------|
| 1 | Lead Weight | Concentration | Yes |
| 2 | Diversification | Concentration | Yes |
| 3 | Volatility | Risk | Yes (but may be cut by scoring) |
| 4 | Leverage | Risk | Yes |
| 5 | Return | Performance | Yes |
| 6 | Sharpe | Performance | Yes |
| 7 | Drawdown | Performance | Yes |
| — | **Beta** | **None** | **No — no candidate exists** |
| — | **Alpha** | **None** | **No — no candidate exists** |

**Net change:** Lost Beta and Alpha. Gained Lead Weight and Leverage. Volatility now competes for a slot instead of being guaranteed. Detail lines are thinner (no benchmark Sharpe comparison, no "peak-trough" label).

---

## LLM Arbiter Delivery Gap

The arbiter enhances the brief asynchronously via `BackgroundTasks`, then writes the result to the in-memory cache. There is no push mechanism to the client. The enhanced brief only surfaces on the *next* `GET /api/overview/brief` call.

If the user loads the overview once and doesn't refresh before the 1-hour TTL expires, the enhanced version is never seen. The arbiter may be doing work that never reaches the user.

---

## Live Comparison — LLM Briefing vs Overview Page (2026-04-13)

On 2026-04-13 we ran the LLM briefing through the agent chat ("Compose my morning briefing for today") and compared its output against the live overview page, both viewing the same portfolio state.

### LLM Briefing Output (agent chat)

| Element | Content |
|---|---|
| **State call** | "DEFAULT state — the book is working defensively but leaving money on the table in a risk-on tape" |
| **Portfolio framing** | $159K portfolio, 9.1% total return, 0.34 beta — running at roughly a third of market exposure |
| **Benchmark context** | SPY beat by 4.4 pts; markets ripped 2%+ Friday (S&P +2.1%, Nasdaq +2.5%) |
| **Risk score** | 89% with visual bar |
| **Alert cards** | DSU Concentration 29% (limit breached, 33.6% exposure) + PCTY down 39% (-$5K unrealized loss) |
| **Metrics table** | Total Return 9.1% vs SPY 14.4%, Annualized 7.8%, Sharpe 0.67 vs 0.77, Alpha +1.7%, Beta 0.34 vs 1.00, Volatility 7.4%, Max Drawdown -2.9% — **8 metrics with benchmark comparison** |
| **Narrative insights** | 3 bullets: (1) DSU is the whole concentration story — 29% weight, 33.6% exposure, only limit violation, underwater on cost. (2) PCTY is a -39% open wound — small weight but biggest dollar loser, needs hold-or-harvest decision. (3) Low beta is a feature, not a bug — but check if intentional; +1.7% alpha says getting paid, just not enough in a strong equity year. |
| **Events** | No earnings/dividends in 30 days; MSCI (10% position) Q1 earnings window late April/early May |
| **Market backdrop** | Risk-on Friday across all indices. Energy/Utilities led. Broad-based (Russell +2.4%). Income/REIT tilt (STWD, BXMT, CBL, ENB) should benefit if rally extends. |
| **"One thing that matters"** | *"Is DSU at 29% a deliberate high-conviction bet or position drift you haven't addressed?"* |
| **Suggested next steps** | (1) Run exit signal check on PCTY — down 39%, may qualify for tax-loss harvest, frees $1K capital + ~$1K realized loss. (2) Alternatively, trim DSU by 10 pts to get under concentration limits, redeploy into existing name or cash. |

### Editorial Pipeline Output (overview page)

| Element | Content |
|---|---|
| **Lead insight** | "DSU is still doing outsized work in the book at 28.9% of exposure" |
| **Evidence** | Lead holding: DSU at 28.9% |
| **Alert cards** | Volatility outside configured limit + DSU is large enough to dominate the next drawdown |
| **Metric strip** | Max Drawdown (-50.7%), Alpha (-24.4% vs SPY), Beta (0.62 SPY), Return (-4.2% YTD vs SPY), Sharpe (-1.10), Diversification (14 holdings, HHI 0.150) — **6 metrics, no benchmark comparison** |
| **Exit ramps** | Review holdings, Open rebalance tool |
| **Margin annotations** | Ask about DSU concentration, analyst note (concentration + drawdown), "what changed overnight" |
| **Events** | None |
| **Market context** | None |
| **PCTY** | Not mentioned anywhere |
| **Suggested actions** | Generic navigation (review holdings, rebalance tool) |

### What the LLM Briefing Captured That the Pipeline Missed

1. **State call (alert vs default)** — The LLM opened with "DEFAULT state" and framed the entire brief around "working defensively but leaving money on the table." The pipeline has no equivalent state concept; its lead insight is descriptive ("DSU is doing outsized work") not diagnostic.

2. **Benchmark comparison on every metric** — The LLM showed Portfolio vs SPY side-by-side (Return 9.1% vs 14.4%, Sharpe 0.67 vs 0.77, Beta 0.34 vs 1.00). The pipeline's metric strip shows raw values with no benchmark reference.

3. **PCTY as an actionable callout** — The LLM identified the biggest dollar loser (-39%, -$5K) and recommended a specific action (exit signal check for tax-loss harvest). The pipeline doesn't mention PCTY at all — its generators only see the top holding by weight, not losers by dollar loss.

4. **Market backdrop** — The LLM contextualized Friday's broad rally (S&P +2.1%, Nasdaq +2.5%, Russell +2.4%), identified sector leaders, and connected it to the portfolio's income/REIT tilt. The pipeline has zero market context.

5. **Events awareness** — The LLM noted no near-term earnings/dividends and flagged the MSCI Q1 reporting window. The pipeline has no events data.

6. **Interpretive "one thing that matters"** — The LLM distilled everything to a single question: *is DSU deliberate or drift?* The pipeline's lead insight is a statement of fact, not a pointed question.

7. **Specific, actionable next steps** — The LLM suggested two concrete paths: (a) exit signal check on PCTY for harvest, (b) trim DSU by 10 pts. The pipeline offers generic navigation links (review holdings, open rebalance).

8. **Portfolio-level framing** — The LLM opened with "$159K portfolio, 0.34 beta, running at a third of market exposure" — immediately grounding the reader in portfolio scale and posture. The pipeline doesn't mention portfolio value or overall beta.

### What the Pipeline Did That the LLM Didn't

1. **Margin annotations** — The right sidebar has editorial notes ("Ask whether DSU is still earning its size", "what changed overnight") that prompt follow-up. The LLM briefing has no equivalent persistent prompts.

2. **Visual risk breakdown** — The overview sidebar has a risk category bar chart (RISK, CONC, VOL, CONC, DD) with severity. The LLM used a simple risk score bar.

3. **Revision tracking** — The "PREVIOUSLY" banner shows what changed from the last brief. The LLM briefing has no memory of prior output.

4. **Always-on artifact structure** — The overview's concentration table, performance chart, and composition sections are persistent visual artifacts. The LLM briefing is a one-shot text response.

---

## Summary

The overview page is not trying to be the chat briefing. It's a persistent surface that should show the right information for this user and this portfolio — and keep showing it until something changes or the user takes action.

**What the re-implementation will fix (P0):** Beta and alpha metrics appearing on the strip. This is spec drift, not a design gap.

**What needs new design work (P1):**
1. **Loss screening generator** — positions with large unrealized losses should be persistent attention cards until resolved. This is the highest-value new generator for the persistent surface.
2. **Deeper editorial memory usage** — `investor_profile.concerns` should drive which metrics are always-on (not competitive). `current_focus.watching` should surface specific tickers. This is the core personalization mechanism.
3. **Events generator (pull-forward from Phase 2)** — time-bounded events are the ideal persistent content. Countdown-style attention cards that disappear after the event passes.

**What would improve but isn't blocking (P2-P3):**
4. Benchmark comparison on metrics (schema enrichment)
5. Income generator (Phase 2 scope, slow-moving data)
6. State detection (nice to have for visual treatment; user forms own judgment)
7. New information awareness (partially covered by change tracking)

**The LLM's role in the persistent surface:**
The chat briefing and the overview are complementary. The briefing gives you the narrative once. The overview gives you the instrument panel permanently. The LLM editorial pass (currently the arbiter) should evolve to help personalize the persistent surface — not by rewriting headlines, but by influencing which candidates get selected and what the exit ramps say, informed by the full editorial memory. The deterministic layer gathers data and generates candidates; the LLM decides what this user needs to see today.

---

## Post-Reimplementation Review (2026-04-13, 7:01 PM)

Codex completed a re-implementation of the editorial pipeline to address spec drift. Live review of the updated overview:

### What Improved

| Element | Before | After |
|---|---|---|
| **Metric strip** | 6 items: Lead Weight, Drawdown, Return, Leverage, Sharpe, Diversification | 6 items: Max Drawdown, **Alpha** (-24.4% vs SPY), **Beta** (0.62 SPY), Return, Sharpe, Diversification |
| **Margin annotations** | 2 ASK ABOUT (DSU size, concentration) + analyst note + what changed | **3 ASK ABOUT** (DSU size, asset mix outside limits, **gap vs SPY**) + analyst note + what changed |

**P0 gap (beta/alpha) is closed.** Both now appear on the metric strip with benchmark context labels ("vs SPY", "SPY"). Lead Weight and Leverage were replaced — the strip now better reflects this user's portfolio posture (defensive, low beta, underperforming benchmark).

The new "Ask what is driving the gap versus SPY" margin annotation is a meaningful addition — it surfaces the performance-vs-benchmark question that's in this user's `care_about` list as a persistent follow-up prompt.

### What Didn't Change

| Gap | Status after re-implementation |
|---|---|
| P1: Loss screening (PCTY at -39%) | **Still open** — no generator, PCTY invisible on overview |
| P1: Deep editorial memory | **Still open** — `concerns`, `watching`, `briefing_philosophy` not used by generators |
| P1: Events generator | **Still open** — no earnings/dividend awareness |
| P2: Benchmark comparison values | **Still open** — metrics show "vs SPY" labels but not side-by-side values (e.g., Beta 0.62 vs 1.00) |
| P2: Income generator | **Still open** — no income/yield data on overview |
| P3: State detection | **Still open** — no alert/default posture |
| P3: New info awareness | **Still open** — partially covered by "PREVIOUSLY" banner |

### Assessment

The re-implementation closed the spec drift and improved the margin annotations. The overview is now showing the right 6 metrics for this portfolio (beta and alpha are essential for a defensive, low-beta strategy). The remaining gaps are all P1+ items that require new design work — they were never in the Phase 1 plan.

**The priority order holds:**
1. Loss screening generator (PCTY should be a persistent attention card)
2. Deeper editorial memory usage (`concerns` → always-on metrics, `watching` → ticker-specific cards)
3. Events generator pull-forward (time-bounded persistent content)
4. Benchmark comparison enrichment on metric strip
5. Income generator

---

## Cross-Reference: Audit Gaps vs Existing Phase 2/3 Plans

The architecture spec (`OVERVIEW_EDITORIAL_PIPELINE_ARCHITECTURE.md` §14-15) and Phase 1 plan (line 3297+) define what was explicitly deferred. This section maps our audit gaps to what's already planned vs what's net-new.

### What Phase 2 already covers

| Audit gap | Phase 2 plan reference | Notes |
|---|---|---|
| Events generator | Arch spec §14 Phase 2: "Events, Income, Trading, Factor, Tax Harvest generators" | Planned. Blocked in Phase 1 because `get_portfolio_events_calendar()` had no cached builder (arch spec §3.1). Re-entry path defined: add `build_events_snapshot()` to result_cache. |
| Income generator | Same line — "Events, Income, Trading, Factor, Tax Harvest generators" | Planned. Drops in as a new generator, no pipeline changes needed. |
| Attention items UI rendering | Phase 1 plan line 3299: "attention_items UI rendering (backend schema present, frontend ignores)" | Backend schema exists and candidates are emitted. Frontend rendering deferred. Currently attention cards render but from the fallback path, not from the editorial pipeline's selected candidates. |
| `whyShowing` tooltip on metrics | Arch spec §7 MetricStrip extension: "whyShowing — reserved for Phase 2 hover/tooltip" | Schema field exists (`whyShowing` on `MetricStripItem`). Renderer ignores it in Phase 1. |
| Scoring weight tuning | Phase 1 plan line 1411: "tune weights in Phase 2 after telemetry" | Telemetry logs capture every score. Tuning deferred until 1-2 weeks of briefs observed. |
| LLM arbiter model benchmarking | Arch spec §15: "Phase 1 defaults to Haiku; model benchmarking is Phase 2" | Currently uses `gpt-4.1` (OpenAI default). No Anthropic/model comparison done. |
| Engagement tracking | Arch spec §14 Phase 3+: "Engagement tracking, per-user generator activation" | Fully deferred. No click logging or implicit preference signals. |

### What Phase 2/3 does NOT cover (net-new from this audit)

| Audit gap | Priority | Why it's not in the plan | What's needed |
|---|---|---|---|
| **Loss screening / biggest loser detection** | P1 | The plan's generators are organized by data domain (positions→concentration, risk→risk, performance→performance). No generator looks at positions through a "what's losing money" lens. The design doc lists 8 generator categories; none is "loss screening" or "position health." | New generator: `LossScreeningInsightGenerator`. Reads positions snapshot, screens for largest unrealized losses and biggest drawdowns. Emits attention_item candidates ("PCTY is down 39% — hold or harvest?") and exit ramps to tax-loss harvest or exit signal tools. |
| **Deep editorial memory usage** | P1 | The plan specifies `editorial_preferences` → score modifiers (implemented). No plan for using `investor_profile.concerns`, `current_focus.watching`, or `briefing_philosophy` in the deterministic layer. The arch spec says editorial_memory is "AI-managed" and the plan treats it as an opaque JSON blob the policy layer reads `editorial_preferences` from. | Design work needed: (1) `concerns` → always-on metric rules (e.g., `concentration_risk` in concerns → lead weight metric is permanent, not competitive). (2) `current_focus.watching` → ticker-specific attention card or margin annotation boosts. (3) `briefing_philosophy` → input to LLM editorial pass. |
| **Benchmark comparison values on metrics** | P2 | `MetricStripItem` has a single `value` field. The plan doesn't discuss showing portfolio-vs-benchmark side-by-side. The `context_label` field is used for text like "vs SPY" but not for a structured benchmark value. | Schema addition: `benchmark_value` field on `MetricStripItem`, or richer `context_label` population from performance snapshot (which already has benchmark Sharpe, beta=1.0, etc.). |
| **State detection (alert vs default)** | P3 | Not in any plan. The policy layer scores candidates individually. No holistic state concept. | If pursued: rule-based state detector as input to policy layer (boost risk candidates globally in alert mode). Or defer to upgraded LLM editorial pass. Lower priority in persistence framing — the overview's persistent signals speak for themselves. |
| **New information awareness** | P3 | Not in any plan beyond `changed_slots` diff. | Becomes relevant when events generator exists. Could leverage `changed_slots` expansion or a separate "new since last visit" mechanism. Low priority now. |

### Summary: What's already on the roadmap vs what's new

```
ALREADY PLANNED (Phase 2/3):          NEW FROM THIS AUDIT:
─────────────────────────             ─────────────────────
Events generator                      Loss screening generator (P1)
Income generator                      Deep editorial memory usage (P1)
Trading/Factor/Tax generators         Benchmark comparison on metrics (P2)
Attention items UI rendering          State detection (P3)
whyShowing tooltips                   New info awareness (P3)
Scoring weight tuning
LLM model benchmarking
Engagement tracking
```

The existing Phase 2 plan covers the **data expansion** (more generators) but misses the **personalization depth** (editorial memory driving always-on decisions, loss screening for actionable problems, benchmark context). The highest-priority net-new items — loss screening and deep editorial memory — are about making the persistent surface respond to *this user's portfolio*, not just adding more generator categories.
