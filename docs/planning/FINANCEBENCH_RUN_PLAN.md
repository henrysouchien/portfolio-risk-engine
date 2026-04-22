# FinanceBench Run Plan

> **⚠️ DEMOTED 2026-04-20** — Primary first benchmark is now **Vals AI Finance Agent v1.1** (see `VALS_FINANCE_AGENT_RUN_PLAN.md`).
>
> Why: Vals Finance Agent has fresh raw-model baselines (Opus 4.7 = 64.4%, cited in Anthropic's April 2026 release) and a publicly-demonstrated agent-wrapper-wins pattern (Fintool 90% vs Sonnet 4.5 55% = +35pp). FinanceBench is saturated at the top (Fintool 97-98%) with no current-model tracked baselines. The commercial story shape is stronger for Vals.
>
> This plan remains valid as the **secondary** (B3) benchmark run — schedule after Vals AI Finance Agent and MCP-Atlas sprints complete. Everything below stays accurate; only the priority has shifted.
>
> See also: `docs/research/fintool/agent-benchmarks-landscape.md` for full landscape research.

---

**Created:** 2026-04-19
**Status:** SECONDARY (was primary) — run after Vals Finance Agent + MCP-Atlas
**Scope:** One-week sprint to get Hank's FinanceBench score and decide reporting posture
**Context:** Table-stakes credibility benchmark for finance AI. Fintool reports 97-98%. Published GPT-4 baseline ~19% closed-book. We need our number to ground the v1 benchmark narrative (see `HANK_RELEASE_SEQUENCING_PLAN.md`).
**Why this matters now:** No commercial decision downstream is grounded until we know this number. Planning-to-shipping ratio is off; this run shifts us toward real signal.

---

## 1. Goal

Produce a defensible, reproducible Hank score on the FinanceBench public open-source subset (150 questions), so we can:

- Confirm we meet the credibility floor for v1 (≥90% target)
- Generate a comparative story against published baselines (GPT-4 closed-book, RAG baselines, Fintool)
- Surface specific failure modes that inform where the architecture needs work
- Hold a reproducible artifact for future re-runs (architectural changes, model upgrades)

**This is not a product feature.** It's a one-week measurement exercise that produces a single number + a failure analysis + a decision memo.

---

## 2. What FinanceBench is

- **Source:** Patronus AI, published Oct 2023. Paper on arxiv, dataset on HuggingFace (`PatronusAI/financebench`) + GitHub
- **Full dataset:** 10,231 questions across 360 SEC filings
- **Public open-source subset:** **150 questions** (what everyone reports against, including Fintool)
- **Question types:** information retrieval, logical reasoning, numerical reasoning
- **Grounding:** each question tied to a specific filing (10-K / 10-Q / 8-K / proxy statement)
- **Scoring:** LLM-as-judge against gold answer + evidence passage, per Patronus's published rubric
- **Published baselines we'll compare against:**
  - GPT-4 closed-book ~19-23%
  - GPT-4 + naive RAG ~60% (exact number varies by paper)
  - Fintool 97-98% (self-reported, retrieval-augmented)

The 150 public subset is what we run. Single credible number to compare against everyone else in the category.

---

## 3. Locked decisions (agreed before kickoff)

1. **Retrieval approach — two configurations.**
   - Config A: Agentic filesystem + grep over the filing (post-RAG Obituary, our "new" architecture)
   - Config B: Stuff the whole filing into 1M context (Claude Opus 4.7 full context)
   - **Why both:** the comparison itself is content. If A matches B, the agentic story is validated. If A beats B, strong proof point.

2. **Model: Claude Opus 4.7 1M, single model across both configs.**
   - No provider routing. Single-model narrative is cleaner for v1.
   - Cost: roughly 150 × (~50K input + 2K output) × 2 configs = ~$150-300 total. Non-blocking.

3. **Citation discipline: matches Hank's stated architecture.**
   - Hank refuses to answer if no supporting evidence passage found.
   - Might score slightly lower than "best effort" but matches the citation-first principle we're committing to (see `BETA_RELEASE_GAP_AUDIT.md` T1.1).
   - Honest architecture > chasing the score.

4. **Publish threshold (set upfront to prevent post-hoc goalpost shifting):**
   - **≥95%** — publish as "matches Fintool on different architecture"
   - **90-95%** — publish as "competitive, running on post-RAG architecture"
   - **80-90%** — HOLD, investigate, fix, rerun before publishing
   - **<80%** — something's wrong with harness or retrieval; debug before publishing

5. **Ownership: one engineer, one week, end-to-end.**
   - Dedicated focus beats spread-across-team. Velocity matters more than thoroughness.

---

## 4. Day-by-day plan

### Day 1 — Acquire + understand (~4 hours)

- [ ] Fetch dataset from HuggingFace: `PatronusAI/financebench` → local `evals/financebench/data/`
- [ ] Read the methodology paper end-to-end
- [ ] Confirm scoring rubric details — implementation must match Patronus's exact methodology
- [ ] Verify filings coverage: for all 150 questions, confirm `Edgar_updater` has the referenced filing cached. Backfill any gaps (likely 0-5 missing) directly from SEC EDGAR API.
- [ ] Sanity-check 2-3 questions manually end-to-end — read question, read gold answer, read evidence passage, mentally simulate Hank answering. Confirm no blockers.

### Day 2 — Build the harness (~1 day)

- [ ] Create `evals/financebench/` folder structure:
  - `data/` — dataset files
  - `harness/` — runner code
  - `results/` — per-run output JSON
  - `scripts/` — one-off utilities
- [ ] Minimal Hank-as-FinanceBench-agent wrapper (two variants):
  - **Config A (agentic):** takes (question, ticker, filing_ref) → uses filesystem tool to grep/navigate the filing markdown via `Edgar_updater` extraction → passes retrieved context to Claude Opus 4.7 → returns (answer, cited_passage, confidence)
  - **Config B (1M context):** takes (question, ticker, filing_ref) → loads whole filing as markdown → passes to Opus 4.7 with question → returns (answer, cited_passage, confidence)
- [ ] LLM-judge scorer matching Patronus's published rubric (use their reference implementation if available)
- [ ] Per-question trace logging: question ID, config used, prompt sent, raw response, parsed answer, cited passage, score, failure category (if any)
- [ ] Dry-run on 10 questions end-to-end to confirm harness works

### Day 3 — Run the 150 × 2 (~4 hours compute + review)

- [ ] Execute full run for Config A (150 questions)
- [ ] Execute full run for Config B (150 questions)
- [ ] Parallel execution where possible to compress wall-clock
- [ ] Aggregate scores: overall %, by question type (retrieval / logical / numerical), by filing type (10-K / 10-Q / 8-K / proxy)
- [ ] Cross-config comparison: which config won per question? Any systematic differences?

### Day 4 — Failure-mode analysis (~1 day)

- [ ] Categorize every miss across both configs:
  - **Retrieval failure** — right filing, wrong section retrieved
  - **Reasoning error** — had the right context, computed/reasoned wrong
  - **Numerical error** — close but off on a number (rounding, unit, period mismatch)
  - **Hallucination** — cited something that doesn't support the answer
  - **Ambiguous gold answer** — gold answer itself is questionable (report but don't count)
  - **Citation refusal** — Hank refused to answer (per discipline decision); note but count as miss
- [ ] Compare against published baselines: GPT-4 closed-book, GPT-4 + RAG, Fintool
- [ ] **Decision gate:** apply the threshold table from §3.4. Output: publish / hold / fix-and-rerun / debug.

### Day 5 — Documentation + decision (~1 day)

- [ ] Write `docs/research/financebench-result.md`:
  - Methodology (what architecture was tested, what model, what retrieval)
  - Score by config, question type, filing type
  - Failure mode breakdown with representative examples
  - Comparison against published baselines
  - Limitations and caveats (we ran 150-public, not full 10K; single model; etc.)
- [ ] Reproducibility artifact:
  - Script entry point: `python evals/financebench/harness/run.py --config=A|B`
  - Pinned deps (model version, edgar_updater version, scoring rubric version)
  - Results JSON committed (or reference to S3 blob)
- [ ] Decision memo (one page):
  - Score
  - Recommendation: publish (where + how + when) / hold / fix
  - What we learned about the architecture
  - Implications for v1 narrative

---

## 5. Open tactical questions (resolve during, not blocking)

- **Filings coverage gaps** — if `Edgar_updater` is missing N of 150 filings, fetch directly from SEC EDGAR API for this run. Note in methodology: "improves to X% when Edgar_updater corpus is fully backfilled."
- **Cost** — Opus 4.7 1M at 150 × ~50K input + 2K output × 2 configs = ~$150-300. Non-blocking. Track actual cost for future reference.
- **Timing** — if results are surprising (very high or very low), results go to founders first before any broader sharing. Prevents premature leaks either way.
- **Gold-answer disputes** — if we find ≥5 questions where we believe the gold answer is wrong or ambiguous, flag them in the writeup and report two scores: "with disputed questions" and "excluding disputed questions."

---

## 6. Deliverables (end of week)

A single committed artifact:

- `evals/financebench/` — harness + scripts + results JSON
- `docs/research/financebench-result.md` — writeup
- Decision memo — published internally, not yet public
- Go/no-go call on publishing the score externally

**Explicit non-deliverable:** the public landing page + essay + PR push. That happens post-decision, if the score clears the publish threshold.

---

## 7. What happens after this week

### If score ≥95% ("hero tier")

- Draft landing page: `hank.com/benchmark/financebench` (or equivalent)
- Draft essay: *"How Hank Scores X% on FinanceBench on a Post-RAG Architecture"*
- Publish both alongside the v1 manifesto essay (when that's written)
- Use the score as the credibility anchor inside Angle A / Angle B landing pages
- Position: "matches Fintool on new architecture"

### If score 90-95% ("credible tier")

- Publish with honest framing ("competitive, running on the new architecture Fintool was moving toward")
- Less prominent placement — technical docs, not hero
- Pair with our own PDB benchmark (where we're uncontested) as the real headline

### If score 80-90% ("hold tier")

- Do NOT publish externally
- Analyze failure modes
- Targeted fixes: likely retrieval or citation discipline
- Rerun in 2-4 weeks

### If score <80% ("debug tier")

- Something's broken in the harness or retrieval path
- Debug, re-verify a handful of questions manually
- Rerun

---

## 8. What we're explicitly NOT doing this week

- Not running the full 10,231-question dataset (public 150 is the industry standard)
- Not testing multiple models (single-model narrative for v1)
- Not doing post-run architectural changes to boost score (that's a separate future project)
- Not building a public benchmark landing page (post-decision)
- Not writing the v1 manifesto essay (parallel track, separate work)
- Not running other external benchmarks (FinQA, TAT-QA etc. come in v1.5 or v2)

---

## 9. Success criteria

**This sprint is successful if, by end of week, we have:**

1. A reproducible Hank score on FinanceBench public 150
2. A categorized failure-mode analysis
3. A clear go/no-go on publishing
4. An artifact a future engineer can re-run with updated architecture

**It is NOT successful if:**

- We're still debugging the harness at end of week
- We have a number but can't defend the methodology
- The score requires extensive post-run explanation to interpret
- We ran but forgot to log traces so we can't analyze failures

---

## 10. Links + references

- Patronus FinanceBench paper: arxiv (search "FinanceBench Patronus AI 2023")
- HuggingFace dataset: `PatronusAI/financebench`
- GitHub: likely `patronus-ai/finance-bench` or similar
- Fintool's 97% claim context: `docs/research/fintool/architecture-learnings.md` §1
- Hank's architectural principles feeding this run: `BETA_RELEASE_GAP_AUDIT.md` T1.1 + T2.6
- Broader benchmark strategy: `HANK_RELEASE_SEQUENCING_PLAN.md` §4 + §8
