# Vals AI Finance Agent Benchmark — Run Plan

**Created:** 2026-04-20
**Revised:** 2026-04-20 (r3 — publish posture + 8-week iteration arc); (r4 — cleanup stale one-week references); (r5 — Codex consistency cleanup).
**Status:** Strategic envelope. Implementation plan at `docs/planning/VALS_FINANCE_AGENT_IMPL_PLAN.md` (r5) is the executable spec.
**Supersedes:** `FINANCEBENCH_RUN_PLAN.md` as the primary v1 benchmark sprint. FinanceBench demoted to secondary; see §10.

> **This document is the strategic envelope.** Targets, configurations, thresholds, publish posture, iteration budget. Day-by-day execution lives in the impl plan §7 (r5 — 8-week arc, baseline + iteration + Week-8 decision gate).
**Scope:** 8-week iteration arc — run Hank on Vals AI Finance Agent v1.1 public 50, iterate architecturally, decide publish posture at Week 8 per §3.4.
**Context:** This is the benchmark where the "agent wrapper beats raw model" pattern is publicly demonstrated in finance (Fintool 90% vs Sonnet 4.5 55% = +35pp). It's the finance equivalent of "Claude Code beats raw Claude on SWE-bench." Current raw-model ceiling: Opus 4.7 = 64.4%, cited in Anthropic's April 15 2026 release.

**Why swapped from FinanceBench:**
- Vals AI Finance Agent has fresh, publicly-tracked raw-model baselines (Opus 4.7 at 64.4%); FinanceBench is saturated at the top (Fintool 97-98%) and not in current leaderboards
- Anthropic's Opus 4.7 release cites Finance Agent as THE finance benchmark, not FinanceBench
- Fintool publicly demonstrated the +35pp agent-wrapper-wins pattern specifically on this benchmark
- Commercial story shape is stronger: "Hank beats raw Opus 4.7 by X pp" > "Hank matches Fintool's 97%"

---

## 1. Goal

Produce a defensible, reproducible Hank score on the Vals AI Finance Agent v1.1 **public 50 samples** so we can:

- Demonstrate the agent-wrapper-wins pattern with a specific delta vs raw Opus 4.7 (currently 64.4%)
- Position Hank as "the finance equivalent of Claude Code" — same base model, measurably better outcomes because of the wrapper
- Surface specific failure modes informing architectural priorities
- Hold a reproducible artifact for future re-runs

**This is NOT a product feature.** It's an 8-week iteration arc (Week 1 baseline → Weeks 2-8 architectural iteration → Week 8 decision gate).

---

## 2. What Vals AI Finance Agent v1.1 is

- **Source:** Vals AI. Paper published Aug 2025: https://arxiv.org/abs/2508.00828
- **URL:** https://www.vals.ai/benchmarks/finance_agent
- **GitHub harness (MIT-licensed):** https://github.com/vals-ai/finance-agent
- **Total dataset:** 537 expert-authored questions, 9 categories
- **Public subset:** 50 validation samples (fully open, what we run)
- **Private: ** 150 validation + 337 test (licensed access, permanently private for overfitting prevention)

### 9 categories tested

1. Quantitative retrieval
2. Qualitative retrieval
3. Numerical reasoning
4. Complex retrieval
5. Adjustments
6. Beat-or-miss
7. Trends
8. Financial modeling
9. Market analysis

### Tools harness provides to agents

- SEC EDGAR API (filings retrieval)
- Google Search via Tavily
- HTML parser
- Information retrieval tool
- `submit` tool for final answer

### Scoring

LLM-as-judge (GPT-5.2), mode of three evaluations. Matches Vals's published methodology.

### Published baselines we target against

| Model | Score | Source |
|---|---|---|
| Claude Opus 4.7 | **64.4%** | Anthropic release, April 2026 |
| Claude Sonnet 4.6 | 63.3% | Vals leaderboard |
| Muse Spark | 60.6% | Vals leaderboard |
| Claude Opus 4.6 (Thinking) | 60.1% | Vals leaderboard |
| GPT-5.4 Pro | 61.5% | Anthropic-cited |
| Gemini 3.1 Pro | 59.7% | Anthropic-cited |
| OpenAI o3 (paper baseline) | 46.8% | Finance Agent paper |
| **Fintool (agent wrapper)** | **90%** | https://fintool.com/benchmark/finance-agent-benchmark-fintool |

**The gap Fintool demonstrated (+35pp over raw Sonnet 4.5) is the pattern we're trying to replicate with our own architecture.**

---

## 3. Locked decisions (agreed before kickoff)

1. **Two configurations — Hank agent vs raw Opus 4.7 baseline.**
   - Config A: Hank v1 curated wrapper per impl plan r5 §3.2.3 — 25 tool classes (9 edgar-financials + 8 FMP analytical + 2 registry-backed + 1 code-exec + 4 harness-native + HankSubmit). Modeling studio DEFERRED per r4 §3.2.8.
   - Config B: Raw Claude Opus 4.7 with only the harness-provided tools (SEC EDGAR, Tavily, HTML parser, retrieval, submit).
   - **Why both:** the Config A − Config B delta IS the story. Anthropic's published Opus 4.7 (64.4%) is another reference; our own Config B ensures apples-to-apples.

2. **Model: Claude Opus 4.7 as the consistent base.**
   - Both configs use Opus 4.7 as the underlying model.
   - The delta attributable to architecture, not to model choice.

3. **Citation discipline: matches Hank's stated architecture.**
   - Hank refuses to answer if no supporting evidence passage found.
   - Might score slightly lower than "best effort" but matches our citation-first principle.
   - Honest architecture > chasing the score.

4. **Publish posture (revised 2026-04-20 r3): "publish when working and far outperforming" — goals, not pre-commits.**

   Per Codex r2 review (should-fix #7), the previous "pre-committed thresholds" framing was too aggressive before we have a baseline. r3 reframes as **targets + a committed floor**, not a commitment to publish at specific numbers.

   The first Config A run is a **baseline measurement**, not a publish candidate. Expected to reveal architectural gaps via failure analysis. Publishing happens only after iteration closes gaps.

   **Publish targets at decision gate (Week 8):**

   | Config A score | Delta over Config B | Narrative class | Action |
   |---|---|---|---|
   | **≥95%** | ≥25pp | Dominant-SOTA hero | Publish hero story |
   | **≥92%** | ≥25pp | SOTA-claim | Publish — beats Fintool's 90% meaningfully |
   | **88-92%** | ≥25pp | Approach-SOTA | Likely extend 4 weeks with a specific architectural hypothesis; only publish if plateauing after extension |
   | **80-88%** | ≥15pp | Delta-only | Pure agent-wrapper delta narrative (no SOTA claim); engage Vals private 337 |
   | **<80% OR delta <15pp** | — | HOLD | Architectural rework before publishing anything |

   **Committed floor (the only hard pre-commit):** do NOT publish if Config A < 80% OR delta < 15pp. Everything else is framed as goals + narrative classes, not triggers.

   **Iteration budget: 8 weeks from sprint Day 1.** Weekly checkpoints. Week 8 = decision gate (publish / extend / hold — based on actual observed number + judgment, not mechanical triggers).

   **Goals: 92% target, 95% stretch, 80% floor.** Actual decision at Week 8 factors in: absolute score, delta, score trajectory over the 8 weeks, private 337 engagement status, and whether remaining gaps look like 1-2 more weeks of work or a deeper rework.

   See impl plan §3.6 for iteration hygiene (architectural fixes only, not score-hacking) and §7 for the 8-week timeline.

5. **Ownership: 1-2 engineers, 8 weeks + decision gate.** Week 1 sprint = baseline + first iteration wave. Weeks 2-8 = architectural iteration + weekly reruns. Consider splitting: one engineer on benchmark + architecture, one on Vals AI licensing + private 337 prep (starts ~week 4).

---

## 4. Day-by-day plan

### Day 1 — Acquire + wrap (~4-6 hours)

- [ ] Clone `https://github.com/vals-ai/finance-agent` into `evals/vals-finance-agent/`
- [ ] Install per repo instructions: `pip install -e .`
- [ ] Obtain required API keys: Vals platform key (registration), Tavily key, SEC EDGAR key, Claude API key
- [ ] Run the harness on 2-3 public questions with raw Opus 4.7 to confirm everything works
- [ ] Study the `get_custom_model` extension point — understand how to plug Hank in
- [ ] Read the paper (https://arxiv.org/abs/2508.00828) to understand scoring nuances

### Days 2-5 — Build + baseline run + analysis

**Superseded by `VALS_FINANCE_AGENT_IMPL_PLAN.md` §7 (r5)** which spans 8 weeks (Week 1 sprint → Weeks 2-8 iteration → Week 8 decision gate). Week 1 Day 2 narrowed per Codex feedback. Modeling studio deferred. See the impl plan for the executable day-by-day.

---

## 5. Open tactical questions (resolve during, not blocking)

- **Vals API key gating** — if Vals platform registration takes days, start that process on Day 0. Shouldn't be Day 1 blocker.
- **Gold-answer disputes** — if we find ≥5 questions where we believe the gold answer is wrong, flag them and report two scores ("with disputed" / "excluding disputed").
- **Cost** — 50 questions × 2 configs × multi-tool-call agent runs = roughly $50-150 total. Non-blocking.
- **Timing** — results go to founders first, no external leaks.
- **Private test set engagement** — initiate Vals AI licensing conversation Week 4-5 (see impl plan §3.6.4); target is a licensed private 337 validation at publish time.

---

## 6. Deliverables (end of 8-week iteration arc)

**Baseline (end of Week 1):**
- `evals/vals-finance-agent/` — wrapper + scripts + initial Config A/B results JSON
- `docs/research/vals-finance-agent-baseline.md` — baseline methodology + first scores + architectural gap list

**Final (Week 8 decision gate):**
- Full run_log (all weekly reruns per §3.6.2)
- `docs/research/vals-finance-agent-result.md` — final writeup with methodology + score trajectory + delta analysis
- Decision memo: publish / extend / hold per §3.4 tiers
- If publishing: landing-page + essay drafts

**Non-deliverable:** public landing page + essay + PR push happen post-decision, not during iteration.

---

## 7. What happens after the Week-8 decision gate

**Superseded by §3.4 (revised r3) above** — see the updated publish-trigger table and 8-week iteration arc. Old tier thresholds in this section removed to avoid internal contradiction.

**Quick reference:**
- Config A ≥95% → hero publish
- Config A ≥92% → SOTA-claim publish
- 88-92% → extend 4 weeks
- 80-88% → delta-only publish + private 337 engagement
- <80% OR delta <15pp → HOLD, architecture rework

Full posture: this doc §3.4 (publish posture + trigger table). Iteration hygiene: impl plan §3.6. 8-week timeline: impl plan §7.

---

## 8. What we're explicitly NOT doing in v1 (Weeks 1-8)

- Not running the 337 private test samples (requires Vals licensing; Phase 4 work)
- Not testing multiple underlying models (single-model narrative; Opus 4.7 only)
- Not running FinanceBench, MCP-Atlas, or GDPval (sequential; those are follow-up sprints)
- Not building public benchmark landing page (post-decision)
- Not writing the v1 manifesto essay (parallel track)
- Not doing score-hacking architectural changes (tuning specific questions). Architectural iteration in Weeks 2-8 is encouraged per impl plan §3.6, but only for changes that generalize beyond the benchmark.

---

## 9. Success criteria

**Week 1 (baseline) successful if:**
1. Config A + Config B scores captured on public 50 (methodology auditable)
2. Week-1 architectural gap list produced from failure analysis
3. Config B reproduces Anthropic's 64.4% within fidelity band (§5.2 impl plan)
4. Reproducible artifact committed

**Week 8 (decision gate) successful if:**
1. Iteration trajectory recorded (per §3.6.2 run_log)
2. Clear publish / extend / hold decision per §3.4 tiers
3. Non-benchmark regression suite still passing (§3.6.5 impl plan)
4. If at publish threshold: Vals private 337 engagement in-flight (§3.6.4)

**NOT successful if:**
- Config B never reproduces Anthropic's baseline (harness broken)
- Run log missing (can't audit methodology)
- Config A trajectory is flat across 8 weeks (architecture not responding to iteration)

---

## 10. Links + references

- Vals AI Finance Agent: https://www.vals.ai/benchmarks/finance_agent
- Paper: https://arxiv.org/abs/2508.00828
- GitHub harness: https://github.com/vals-ai/finance-agent
- Fintool's 90% claim: https://fintool.com/benchmark/finance-agent-benchmark-fintool
- Anthropic Opus 4.7 release: https://www.anthropic.com/news/claude-opus-4-7
- Hank's benchmark landscape research: `docs/research/fintool/agent-benchmarks-landscape.md`
- Broader benchmark strategy: `HANK_RELEASE_SEQUENCING_PLAN.md` §4 + §8
- Architecture principles: `BETA_RELEASE_GAP_AUDIT.md` T1.1 + T2.6
- FinanceBench (demoted secondary target): `FINANCEBENCH_RUN_PLAN.md` — run after this one completes

---

## 11. Next sprints queued after this one

Per `docs/research/fintool/agent-benchmarks-landscape.md` §9 recommended sequence:

| Order | Benchmark | Rationale |
|---|---|---|
| 1 (this sprint) | **Vals AI Finance Agent v1.1 public 50** | Primary — agent-wrapper-wins story |
| 2 | **MCP-Atlas** | Validates 80+ MCP tool surface investment |
| 3 | **FinanceBench** | Legacy credibility floor |
| 4 | **Vals Finance Agent private 337** | Real leaderboard entry (requires licensing) |
| 5 | **GDPval financial-analyst subset** | Cross-industry credibility |
