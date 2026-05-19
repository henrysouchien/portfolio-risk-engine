# VALS Config D Diagnosis - 2026-05-17

**Status:** Active follow-up note for Config D source-basis/tooling work.
**Run:** `hank_local_static_public_20260517T171130Z_config_d_static_public`
**Score:** 39/50, 78.0%
**As-of frame:** public VAL static date, April 07, 2025.

Primary artifacts:

- `evals/vals-finance-agent/results/static_public_20260517T171130Z/config_d/run.json`
- `evals/vals-finance-agent/results/static_public_20260517T171130Z/config_d/traces.jsonl`
- `evals/vals-finance-agent/results/static_public_20260517T171130Z/config_d/latest_status.md`
- `evals/vals-finance-agent/results/latest_config_d_status.md`
- `evals/vals-finance-agent/config_d_classifications.json`

## Executive Summary

Config D is above raw-model baseline territory but below the v1 publish floor. The 11 misses are not one class of problem. The actionable queue splits into:

- Source-basis/tooling work: q012, q025, q030, q033, q046.
- Answer policy / synthesis exactness: q014, q045, q048, q050.
- Benchmark/rubric mismatch: q043, and part of q001.
- Harness/final-answer capture: q001.

The most efficient short-term score recovery is answer-policy exactness (`q014`, `q045`, `q048`, `q050`). The most important architectural work is source-basis selection and evidence packs (`q012`, `q025`, `q030`, `q033`, `q046`), because those same failure modes will recur outside the public 50.

## Priority Queue

| Priority | Question | Workstream | Why |
|---|---|---|---|
| P0 | q001 | Harness final-answer capture | Stored answer was only the arithmetic-verification follow-up; the judge missed the substantive answer. This can silently under-score any question with post-answer guard text. |
| P1 | q033 | Debt source-basis tooling | Recurrent finance-modeling class: select the right refinanceable debt base, not the broadest balance-sheet/debt-note total. |
| P1 | q012 | Guidance/FX/midpoint convention | Recurrent guidance modeling class: use prompt/rubric midpoint convention, preserve FX precision, and avoid post-cutoff transcript metadata. |
| P1 | q025 | Regulatory-risk evidence coverage | Evidence pack missed specific third-party supplier/cybersecurity snippets. This is source-retrieval quality, not answer wording. |
| P1 | q046 | Acquisition source-basis stability | Retrieval drifted across consideration bases and revenue-mix framing; needs stable acquisition source packs. |
| P2 | q014 | Cash-flow scope policy | Answer had expected normalized value but led with contradictory consolidated CFO table. |
| P2 | q030 | Convertible share precision + date filter | 172-share mismatch from rounded principal inputs; filing search also surfaced post-cutoff metadata. |
| P2 | q045 | Non-GAAP adjustment framing | Correct amount; wrong source frame. |
| P2 | q048 | Guidance row exactness | Correct data; needs rounded row-label convention. |
| P2 | q050 | Rounding exactness | Correct data; one percentage rounded the wrong way. |
| Hold | q043 | Benchmark/source-rubric mismatch | Uber source says Freight declined 2% c/c; VAL expects +2%. Do not invert source-correct sign only for score. |

## Per-Question Diagnosis

### q001 - US Steel / Nippon Merger

**Classification:** `final_answer_capture_and_temporal_rubric_mismatch`

Observed failure:

- `run.json` stored only the arithmetic-verification follow-up as `final_answer`.
- Judge checks looked for the substantive merger summary, but the stored answer did not include it.
- Existing temporal mismatch remains: the static April 07, 2025 answer cannot truthfully include later deal-close/investment commitments that VAL appears to expect.

Likely fix:

- Harness/gateway should preserve the full substantive final answer when a final-answer guard injects a follow-up verification turn.
- For benchmark notes, keep q001 marked as partly rubric-temporal mismatch even after capture is fixed.

Do not:

- Add post-April-07 evidence only to satisfy the public rubric in static-public mode.

### q012 - TSM Q1 2025 Guidance Projection

**Classification:** `guidance_fx_and_midpoint_convention`

Observed failure:

- Latest run correctly used the February-to-March sequential bridge.
- It projected Q1 revenue at about NT$825.1B.
- It compared against the guidance range using NT$32.8/USD and called the result "in range."
- VAL expected midpoint convention at 32.88, midpoint guidance NT$835.152B, and `-1.2% miss`.
- Trace also surfaced a post-cutoff transcript metadata observation dated 2025-04-17.

Likely fix:

- Guidance-modeling policy should explicitly decide range-vs-midpoint semantics from the prompt and benchmark convention.
- Preserve FX precision exactly as sourced or expected by the guidance conversion convention.
- Date-filter transcript lookups and metadata observations before they enter evidence context.

Validation target:

- Answer should include Q1 guidance midpoint NT$835.152B, projected Q1 NT$825.107B, and `-1.2% miss`.

### q014 - Zillow FCF Margin Trend

**Classification:** `cash_flow_scope_policy`

Observed failure:

- Answer computed the VAL-expected normalized FY2022 FCF margin of about 24.8% after excluding Zillow Offers/iBuying wind-down cash.
- It led with a reported consolidated CFO table showing FY2022 CFO of $4.504B and FCF margin of 224.2%.
- Judge treated the primary table as contradiction because VAL wanted the normalized trend: 2022 24.8%, 2023 11.3%, 2024 12.7%.
- Trace showed metric alias gaps for `cash flow from operations` and `capital expenditures`, forcing manual recovery.

Likely fix:

- For trend questions where discontinued/wind-down operating cash dominates the reported metric, lead with the comparable/normalized series if the prompt/rubric asks for trend.
- Put consolidated reported values in a caveat after the main answer, not as the main table.
- Add/repair Z metric aliases for CFO and capex.

Validation target:

- Primary answer table should lead with 2022 24.8%, 2023 11.3%, 2024 12.7%, and say margins declined substantially then stabilized in low teens.

### q025 - Paylocity FY2024 Regulatory Risks

**Classification:** `upstream_tooling`

Observed failure:

- Answer covered most regulatory risks, but missed two rubric checks:
  - third-party partners/suppliers may experience breaches, supply-chain attacks, or system failures;
  - increasing cybersecurity regulatory scrutiny requiring additional compliance investment.
- Trace had 3 as-of metadata violations from 2025-08-06 PCTY filings surfaced during search/list operations.

Likely fix:

- PCTY FY2024 risk-factor evidence pack needs to retain supplier/third-party security and cybersecurity regulatory scrutiny snippets.
- Filing list/search should filter or demote post-cutoff filings before returning search hits in static-as-of mode.

Validation target:

- Answer should include third-party/supplier breach/system-failure risk and increasing cybersecurity regulatory scrutiny/compliance costs.

### q030 - SNAP Convertible Notes Dilution

**Classification:** `convertible_share_count_precision`

Observed failure:

- Answer: 85,945,299 shares.
- VAL expected: 85,945,127 shares.
- Difference: 172 shares, from using rounded outstanding principal amounts for convert tranches.
- Trace also surfaced 2026 10-K metadata despite the April 07, 2025 cutoff, though final answer used FY2024 10-K.

Likely fix:

- Convertible-note calculator should prefer exact unrounded principal or source-reported max-share values where available, not displayed rounded $M values.
- If only rounded $M table values are available, explicitly note precision limit and avoid over-precise integer claims.
- Static-as-of filing search should not include later annual filings in candidate hit metadata.

Validation target:

- Answer should state 85,945,127 shares if all converts were converted, including out-of-the-money converts.

### q033 - Boeing Debt Refinance Sensitivity

**Classification:** `debt_source_basis_tooling`

Observed failure:

- Latest run used a broader debt-note carrying total of $53.625B and calculated a $1.271B after-tax impact.
- VAL expected a refinanceable debt-note base of $53.211B and a $1.261B negative impact to net income.
- Earlier passing run selected the expected source basis.

Likely fix:

- Debt-sensitivity source selection needs a typed base:
  - "all debt refinanced" should mean interest-bearing refinanceable debt from the debt-note schedule;
  - exclude leases/other non-refinanceable or non-interest-bearing balances unless the prompt asks for them.
- Add aliases/tests around Boeing 2024 debt metrics so fallback does not drift to the broadest balance-sheet line.

Validation target:

- Answer should compute $53.211B * 3.00% * (1 - 21%) = about $1.261B negative impact.

### q043 - Uber Revenue Growth Bridge

**Classification:** `source_rubric_mismatch`

Observed failure:

- Company-wide take-rate/volume decomposition passed.
- Remaining misses were segment-growth checks: Mobility growth 25%, Freight growth 2%.
- Source evidence says Freight Gross Bookings declined 2% constant currency. VAL expects +2%.

Likely fix:

- Treat as benchmark/source-rubric mismatch unless source evidence changes.
- Do not invert a source-correct sign for score fitting.

Optional mitigation:

- Include segment metrics as source-stated values and make the company-wide decomposition the answer core.

### q045 - Airbnb Stock-Based Compensation Adjustment

**Classification:** `source_framing_policy`

Observed failure:

- Amount was correct: $1.407B.
- Answer framed it as a cash-flow-statement adjustment.
- VAL expected adjusted EBITDA adjustment framing: Airbnb adjusted EBITDA by $1.407B to exclude stock-based compensation expense.

Likely fix:

- For "adjustment" questions, identify the target non-GAAP reconciliation first before answering from cash-flow add-backs.
- Prefer adjusted EBITDA reconciliation language when the prompt category/context points to non-GAAP adjustments.

Validation target:

- "In 2024, Airbnb adjusted EBITDA by $1.407B to exclude stock-based compensation expense."

### q046 - Zillow Acquisition Strategy / Revenue Mix

**Classification:** `acquisition_source_basis_regression`

Observed failure:

- Latest run used exact/alternative consideration bases and current-period revenue rebound framing.
- VAL expects:
  - Follow Up Boss for $399M plus up to $100M contingent consideration;
  - Spruce for $19M;
  - Aryeo for $35M;
  - post-COVID tight-housing-market decline framing for Residential/Premier Agent and Mortgages.

Likely fix:

- Acquisition source pack should preserve headline announced/10-K summary consideration alongside exact fair-value/net-of-cash values.
- Answer policy should choose headline consideration when asked for acquisition strategy, and reserve exact purchase-accounting values for accounting questions.
- Revenue-mix synthesis needs a stable historical framing: acquisitions build For Sale workflow capabilities against a post-COVID housing-market slowdown, even if later current-period revenue rebounds.

Validation target:

- Answer should describe subscription/software tuck-ins and connect them to Zillow's evolving revenue mix while preserving the expected headline consideration amounts.

### q048 - Lemonade FY2024 Actuals vs Prior Quarter Guidance

**Classification:** `guidance_row_exactness_policy`

Observed failure:

- Evidence coverage was mostly complete.
- IFP actual was 943.7M against 940-944M guidance.
- Answer said "in range, near high end"; VAL expected rounded `$944M`, high end of guidance range.

Likely fix:

- Guidance-row synthesis should round actuals to the same display precision as guidance when comparing to row labels.
- When rounded actual equals high end, say "at high end" rather than "near high end."

Validation target:

- IFP row should read `$944M`, high end of guidance range.

### q050 - AMD Non-GAAP Gross Profit Beat/Miss

**Classification:** `rounding_exactness_policy`

Observed failure:

- Source retrieval and actual values were correct.
- Q2 beat was computed as 2.65% and rounded to 2.7%.
- VAL expected 2.6%.
- Trace also showed missing structured metric cache for AMD Q1-Q4 2024, but fallback text extraction found the needed values.

Likely fix:

- Beat/miss formatting policy needs deterministic one-decimal convention matching benchmark expectations. For these rows, use conservative/truncated one-decimal display or source/rubric-compatible rounding.
- Add structured cache coverage or aliases for AMD non-GAAP gross profit/revenue to avoid text fallback churn.

Validation target:

- `Q2 - $3,101 million (2.6% BEAT)` and average `2.2% BEAT`.

## Cross-Cutting Fix Themes

### 1. Final-answer Preservation

If the gateway injects a final-answer guard after an answer, the harness should store the substantive answer plus the guard result, not only the guard's last message. q001 is the concrete failure.

Suggested test:

- Simulate an answer followed by an arithmetic-verification follow-up.
- Assert `run.json.results[].final_answer` includes the substantive answer.

### 2. Static As-Of Source Filtering

Several traces include post-cutoff metadata even when the final answer is source-correct:

- q012: transcript metadata dated 2025-04-17.
- q025: PCTY 2025-08-06 10-K metadata.
- q030: SNAP 2026-02-05 10-K metadata.
- q027 passed but final answer cited a 2026 Allstate 10-K date.

Static-as-of mode should filter candidate search/list metadata before the agent sees it, not rely only on final-answer judgment.

### 3. Source-Basis Typing

Failures repeatedly come from choosing a plausible but wrong basis:

- q033: broad debt carrying total vs refinanceable debt-note base.
- q046: fair-value/net-of-cash accounting basis vs headline acquisition consideration.
- q014: consolidated reported CFO vs comparable normalized FCF trend.
- q045: cash-flow add-back vs adjusted EBITDA reconciliation adjustment.

The tool layer should expose basis metadata, and the answer policy should select basis by question intent.

### 4. Precision And Display Conventions

Small formatting differences were enough for 0 scores:

- q030 integer share count precision.
- q048 rounded IFP row label.
- q050 one-decimal percentage convention.
- q012 FX precision and midpoint convention.

Add "display precision follows prompt/rubric/source table" as a synthesis rule for guidance, debt sensitivity, convertibles, and beat/miss questions.

## Suggested Next Implementation Order

1. Fix final-answer capture and rerun q001 targeted to separate harness loss from rubric mismatch.
2. Add source-basis rules/tests for debt sensitivity using q033.
3. Add guidance convention policy for q012/q048/q050 together.
4. Add PCTY regulatory-risk evidence coverage and as-of filtering checks for q025.
5. Add convertible precision and filing-date filter checks for q030.
6. Stabilize acquisition source packs for q046.
7. Keep q043 in benchmark-notes unless Vals/source expectations change.

