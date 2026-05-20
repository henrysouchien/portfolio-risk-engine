# Vals Guidance-Extraction Precision Rules — Plan

**Status:** ❌ SUPERSEDED / BAD REASONING — DO NOT IMPLEMENT.

**Reverted in AI-excel-addin commit `799a381d` on 2026-05-18.** Plan shipped (e3c263f0), validated empirically (Phase E rerun on q048/q050), and was a partial failure: targeted bugs closed but introduced regressions on adjacent per_check items.

**Why this plan was wrong (in plain reasoning terms):**
- **Rule 1 (q050)** wrote a rule about *computation* when the bug was about *presentation*. A 1-sentence formatting rule would have closed Q2 2.7%→2.6% without spillover. My maximalist rule instead nudged Hank to put the beat-delta ($80M) in the dollar slot where VAL expects the actual non-GAAP gross profit ($3,101M).
- **Rule 2 (q048)** restructured the whole verdict-classification logic when only one row's label needed a 1-line addition. I never asked "what was Hank doing RIGHT on the 6 passing rows that I need to PRESERVE?" The 3 support rows (SBC, Capex, Weighted Shares) were perfect on the May 17 run — my expanded rule + "pick one canonical label" closing read as "be precise, be minimal" and Hank dropped them.
- **Meta gap:** treated prompt edits as surgical code patches. Prompts are not surgical — adding a sentence reweights the whole answer. The discipline missed: (a) smallest rule that changes only the broken cell, (b) explicitly name what stays the same, (c) examples in rules should illustrate the FIX, not the underlying mechanic. My `80/3021` example DEMONSTRATED THE WRONG INTERPRETATION (delta in the dollar slot).
- **Codex review gap:** rounds 0-2 caught wording errors but not spillover risk. Should have prompted Codex specifically: "what other behaviors in this answer might shift if I add this rule?"

Preserved here as a negative example. Any future q048/q050 plan should be a fresh document, not an iteration of this one — the framing was wrong, not the wording.

---

**Original status (now historical):** Round 2 — addressing Codex round 1 findings.
**Owner repo:** AI-excel-addin (skill file edit). Verification in risk_module via Vals harness.
**Closes:** Vals Config D q048 (LMND IFP row label) + q050 (AMD Q2 percent rounding).
**Diagnosis source:** `docs/planning/VALS_CONFIG_D_20260517_DIAGNOSIS.md` §"Per-Question Diagnosis" and §"Cross-Cutting Fix Themes".

---

## 1. Context

Vals Config D run `static_public_20260517T171130Z` scored 39/50. Of the 11 failures, four are answer-policy exactness (P2). Two of those four (q048, q050) are governed by the canonical `guidance-extraction` skill, which Hank correctly loaded for both questions per the run traces.

**q050 (AMD beat/miss):** Question requested format "QX - $XXX million (X.X% BEAT or MISS)". Hank's table cell shows Q2 delta = `+$80.0M | +2.65%`; headline rendered "Q2 — $3,101 million (2.7% BEAT)". VAL expected `2.6% BEAT`. Single-step rounding of the raw value 80/3021 = 2.6481% → 2.6% (one decimal). The 2.65 intermediate is a double-rounding artifact — `round(2.6481, 2)` = 2.65, then half-up display rounding 2.65 → 2.7. Judge per_check failed Q2 correctness (0/3) and full-table contradiction (0/3).

**q048 (LMND guidance comparison):** 6/7 sub-checks passed. Only IFP row failed (0/3): answer rendered `$943.7M | In range (near high end)` while VAL expected `$944 Million, high end of guidance range`. IFP actual 943.7 rounds to 944 at the same precision the source uses for the guidance range (940–944). Hank picked a hybrid narrative verdict ("in range (near high end)") that satisfies neither the canonical 4-verdict set nor the row template.

Trace confirms `skill_reads: ['guidance-extraction']` for both questions and `guidance_route: matched`. Hank's failure is policy gaps, not routing or skill-load.

## 2. Goal

Add two precision rules to canonical `guidance-extraction.md` so that:

- **q050-class:** any beat/miss percent in a compact requested format is computed and displayed in a single rounding step from raw delta/denominator, never chained from an intermediate-rounded percent.
- **q048-class:** when the rounded actual at the source's guidance-display precision equals the rounded high-end (or low-end) at the same precision, the verdict label is `at the high end of range` (or `at the low end of range`), not `in range` / `in range (near high end)`.

Targeted re-run of q048 + q050 against Config D static-public passes (rounded actual matches VAL gold; both per_check correctness votes ≥2/3, no judge-flagged contradiction).

## 3. Scope

### In scope

- Edit canonical `api/memory/workspace/notes/skills/guidance-extraction.md` (AI-excel-addin).
- Add two bullets to **Response Posture** (the §"Response Posture" list at lines 38–82).
- Update the comparison-table template at line 269 to align verdict vocabulary with the Response Posture rules.

### Out of scope

- Routing fixes (q045) — separate Phase C.
- `metric-trend-analysis` rule strengthening (q014) — separate Phase D.
- Refresh of stale per-user skill copies in `data/users/*/workspace/notes/skills/` — confirmed unused by the loader (canonical-only), so these are dead artifacts. Hygiene cleanup is a separate follow-up, not a fix.
- Anything outside guidance-extraction.md (e.g., code-execute tool behavior, post-processor formatters). The fix is prompt-only.

## 4. Steps

### Step 1 — Add q050-class precision rule

Insert after line 41 ("…show the formula and keep rounded shorthand secondary."), as a new Response Posture bullet:

> - For derived percentages, deltas, and beat/miss values, compute and display in a single rounding step from raw source numerator and denominator. Do not chain `round(x, 2)` then `round(x, 1)`; intermediate rounding to a 5-tail can invert the final display rounding (e.g., 80/3021 = 2.648% rounds to 2.6%, but the chain 2.6481 → 2.65 → 2.7 gives the wrong final digit). Final-answer values must use the requested display precision consistently. If the requested answer is one decimal, do not show an intermediate-rounded two-decimal percent for the same metric anywhere in the final answer (table cells, prose, or headline). For auditability, show raw inputs, formulas, or unrounded calculations; only show a two-decimal percent when the user/source explicitly requests two-decimal display, and compute that two-decimal value directly from raw inputs.

### Step 2 — Add q048-class verdict-disambiguation rule

Strengthen the existing verdict rule at lines 59–62. Replace:

> - For source-range guidance, classify an actual inside the source range as `met`,
>   `in range`, or `at the high end of range`, not as a beat. Use `beat` only when the
>   actual is above the high end and `miss` only when it is below the low end, unless
>   the user/source explicitly defines a midpoint comparison.

With:

> - For source-range guidance, first determine inside-vs-outside the exact (unrounded) source range. If the actual is above the unrounded high end → `beat`; below the unrounded low end → `miss`; otherwise the actual is inside the range and one of the in-range labels applies. Then choose the in-range label by source guidance-display precision: when the rounded actual at the source's guidance-display precision equals the rounded high-end value at the same precision, use `at the high end of range` (e.g., guidance `940–944` to 0-decimal precision, actual `943.7` rounds to `944` → `at the high end of range`, not `in range`). When the rounded actual at the source's guidance-display precision equals the rounded low-end value at the same precision, use `at the low end of range`. Otherwise use `in range`. The user-requested precision can control display formatting of the actual, but it does not change this verdict-classification rule unless the user/source explicitly defines a different comparison basis (e.g., midpoint). Do not invent hybrid verdicts such as `in range (near high end)`; pick one of the canonical labels.

### Step 3 — Sync the comparison-table template vocabulary

At line 269, replace the row template:

```
| Revenue | $___-___m | $___m | Above / in range / below |
```

With:

```
| Revenue | $___-___m | $___m | beat / at the high end of range / in range / at the low end of range / miss |
```

Vocabulary exactly matches the Response Posture rule in Step 2 — no abbreviated labels — so model authors of the table row see the same vocabulary they're told to use.

## 5. Verification

### 5.1 Offline skill-content smoke (in AI-excel-addin) — deterministic gate

- `pytest tests/test_guidance_extraction_precision.py -q` should still pass; verify it doesn't pin the old 3-verdict template, and update if so.
- Add a new content-anchor smoke (small new test or grep assertion in CI) that loads the canonical skill file and asserts each of the three new pieces is present verbatim:
  - The phrase `single rounding step from raw source numerator and denominator` appears in Response Posture (anchors Step 1).
  - The phrases `at the high end of range` and `at the low end of range` each appear in Response Posture (anchors Step 2 verdict vocabulary).
  - The template row at the Step-3 location contains the literal `beat / at the high end of range / in range / at the low end of range / miss`.
- These three assertions are the deterministic gate that the implementer actually landed the rules. They fail loudly if the wording drifts.

### 5.2 Targeted Vals rerun (in risk_module)

Re-run q048 + q050 against Config D static-public. The script defaults the timestamp prefix; let it default unless a custom name is needed:

```
bash evals/vals-finance-agent/scripts/run_config_d_static_public.sh --question-ids q048,q050
```

Implementer: confirm the underlying harness accepts `--question-ids` passthrough before invoking. If passthrough is missing, file as a separate enabler before this rerun.

### 5.3 PASS criteria

- q050 per_check on "Q2 2024: $3,101 million (2.6% BEAT)" passes ≥2/3.
- q050 contradiction check on the full table passes ≥2/3.
- q048 per_check on "In Force Premium (IFP): $944 Million, high end of guidance range" passes ≥2/3.
- All other per_check items on q048 + q050 remain pass (regression check).

### 5.4 FAIL handling

If the smoke shows the model still produces `in range (near high end)` or `2.7%`, the rule wording is too weak. Iterate the bullet (move to "Red Flags" section for stronger emphasis, or add a worked example block). Do not re-architect the skill.

## 6. Risk

### 6.1 q048 rule

**Low.** Rule fires only when rounded actual at source-display precision equals the rounded high/low end at the same precision. Doesn't regress questions where actual is meaningfully inside the range. Edge case: if source guidance precision differs from actual-report precision (e.g., guidance to 0-decimal, actual to 1-decimal), the rule defines "source guidance-display precision" as the controlling one — picks the coarser precision of the two. Documented inline in the bullet.

### 6.2 q050 rule

**Low-medium.** Rule could be misread as "never show 2-decimal percents anywhere." Mitigated by allowing raw inputs, formulas, or unrounded calculations for auditability while forbidding intermediate-rounded two-decimal percents in final answers unless the user/source explicitly requests two-decimal display. Could regress if the model interprets "compute from raw" as "show 4 decimals always" — mitigated by "at the requested display precision" qualifier.

### 6.3 Template sync (Step 3)

**Low.** Same vocabulary as the Response Posture rule. Could break a downstream consumer that pattern-matches on "Above / in range / below" — none known. Worth a grep in AI-excel-addin during implementation.

### 6.4 Stale per-user skill copies

Not a risk for this fix (loader confirmed canonical-only). Filed as separate hygiene follow-up — no action in this plan.

## 7. Implementation Notes (for the Codex implementer)

- File path: `/Users/henrychien/Documents/Jupyter/AI-excel-addin/api/memory/workspace/notes/skills/guidance-extraction.md`.
- Three Edits total — one bullet insertion (Step 1), one bullet replacement (Step 2), one row-template replacement (Step 3).
- Codex MCP conventions per risk_module CLAUDE.md: inherit model from `~/.codex/config.toml`, `approval-policy: never`, `sandbox: workspace-write`, `cwd` = `/Users/henrychien/Documents/Jupyter/AI-excel-addin`.
- After implementation: `grep -n "Above / in range / below" /Users/henrychien/Documents/Jupyter/AI-excel-addin/` to confirm no other consumer references the old template vocabulary.
- Commit message: `skill(guidance-extraction): add precision rules for derived percents + range-boundary verdicts (Vals q048/q050)`.

## 8. Resolved decisions (from Codex round-0 review)

- **Source guidance-display precision controls the range-boundary verdict.** User-requested precision can format the displayed actual but does not change the classification. Encoded into Step 2 wording.
- **q050 rule does not mention banker's rounding.** Fix is single-step rounding from raw, not tie-breaking policy. Encoded into Step 1 wording.
- **Step 3 template sync is bundled here, not split out.** It removes a load-bearing internal contradiction; vocabulary now exactly matches Step 2 (full phrases, no abbreviations).
