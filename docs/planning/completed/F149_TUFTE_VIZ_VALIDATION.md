> **✅ DONE — Validation completed 2026-05-26; moved during 2026-05-28 docs cleanup.**

# F149 Tufte-Viz Validation

Date: 2026-05-26
Status: validated as a design-review companion, not an automated merge gate

## What Was Reviewed

F149 asked whether the external `tufte-viz` Claude Code skill should become part of Hank's visualization workflow.

External source reviewed:
- `https://gist.github.com/aparente/e48c353755958621b3c0004593105a90`

Local standards reviewed:
- `docs/standards/INVESTMENT_VISUAL_LAYER_PRINCIPLES.md`
- `docs/reference/VISUALIZATION_STACK.md`
- `DESIGN.md`
- `docs/planning/SKILL_ARTIFACT_VISUAL_MATRIX.md`
- `docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md`

Representative surfaces reviewed:
- Hedge Analysis: `frontend/packages/ui/src/components/portfolio/scenarios/tools/HedgeTool.tsx`
- Overview concentration artifact: `frontend/packages/ui/src/components/dashboard/views/modern/overviewArtifactBrief.ts`
- Thesis comp-table direction: `docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md`

## Decision

Use the Tufte-viz rubric as a design-time critique tool for investment visuals. Do not wire it as a required automated code-review or CI gate.

The useful parts are concrete and agent-friendly:
- Eraser test: remove duplicated labels, legends, gridlines, and chrome that do not carry information.
- Collision test: check annotation and label bounding boxes before a chart ships.
- Graphical integrity: verify scales, baselines, and proportional encoding.
- Small-multiple discipline: use repeated comparable views when comparison is the job.
- Table-first discipline: do not chart a dense finance table when the table is the clearer visual.

The parts that need Hank-specific override:
- "Default to grayscale" is too literal for Hank. We use semantic color tokens for analyst meaning: positive, warning, negative, neutral, urgency, and provenance.
- "Avoid chartjunk" must not remove intentional product grammar such as severity dots, source chips, provenance rails, or decision badges.
- Tufte's print-first bias should not suppress interactive affordances that are part of the workflow, such as "Ask AI about this", scenario navigation, and preset inspection.

## Trial Results

### 1. Hedge Analysis

Verdict: pass with review notes.

Why it fits:
- The surface starts with an analyst diagnosis, then shows evidence and recommendations.
- It uses bar charts for variance-share comparison, which is the right encoding for relative contribution.
- It attaches action paths: ask the analyst, test a hedge in What-If, and preview execution.
- The generated artifact has a claim and interpretation, so it is not a naked chart.

What Tufte-viz catches:
- There is intentional repetition between the metric strip, the generated artifact, and the detailed diagnosis chart. This is acceptable because they serve different scanning depths, but future changes should avoid adding a fourth restatement of top driver / beta / factor risk.
- The detailed diagnosis chart uses a hidden X-axis plus value labels at bar ends. That is defensible for scan speed, but the collision test should be part of visual QA for long driver names and large percentage labels.
- The "DQ" data-quality badge is not chartjunk because it changes interpretation of the volatility number.

### 2. Overview Concentration Artifact

Verdict: pass.

Why it fits:
- The artifact is claim-first: the claim and interpretation tell the user what the concentration means before the chart.
- It uses a compact bar chart rather than a generic dashboard layout.
- It limits ticks to chosen values and includes source/timestamp/methodology tags.
- It exposes decision exits: rebalance or hedge the overweight.

What Tufte-viz catches:
- For single-line comparison mode, the visual is intentionally minimal and should stay that way. Do not add legend chrome.
- In multi-row mode, callouts and reference lines must be visually checked for overlap with the lead bar label and value labels.
- The current table-like tags are useful because they preserve traceability; they should not be removed as "extra ink".

### 3. Thesis Comp-Table Direction

Verdict: pass, with a strong table-first constraint.

Why it fits:
- The F147/F150 direction treats comp tables as first-class visuals, which aligns with the investment visual-layer standard.
- Peer KPI matrices should remain canonical React tables with explicit definitions, units, sources, and periods.
- Charts are earned only for trend, sensitivity, dispersion, or inflection views.

What Tufte-viz catches:
- Do not make a default peer scatter/bubble chart just because a visual registry exists.
- A comp-table visual should solve comparison and traceability first: rows, columns, source chips, definitions, and deltas.
- If small multiples appear, they should share scale and period definitions, or the comparison becomes visually dishonest.

## Integration Mode

Recommended mode: design-time companion.

Use it when:
- Creating a new canonical artifact renderer.
- Reviewing a Pattern 2A agent-rendered HTML artifact.
- Reviewing a generated chart that is promoted from chat into the main content stream.
- Writing or reviewing F147/F148/F122 implementation plans.

Do not use it as:
- A CI gate.
- A generic dashboard linter.
- A replacement for `DESIGN.md` or `INVESTMENT_VISUAL_LAYER_PRINCIPLES.md`.
- A rule that blocks semantically meaningful color, badges, source chips, or workflow controls.

## Review Checklist To Reuse

1. State the decision job: what decision or inspection does this visual support?
2. Check the thesis/claim comes before the chart or table.
3. Run the eraser test: remove redundant chart chrome and duplicate labels.
4. Run the collision test: inspect labels, callouts, reference lines, and dense rows.
5. Check scale integrity: baseline, shared axes, and unit definitions.
6. Confirm traceability: source, timestamp, period, units, and methodology are visible.
7. Confirm interaction is earned: controls should inspect, compare, or route to action.
8. Confirm Hank exceptions are deliberate: severity dots, source chips, and decision badges are acceptable only when they alter interpretation.

## Follow-Ups

- F122 should include this checklist in the agent-HTML renderer evaluation harness.
- F147 implementation plans should apply it to every canonical Thesis artifact renderer before merge.
- F148 presentation packs should apply it at pack-template review time, not at every runtime render.
- F150's matrix can reference this validation when classifying canonical versus scaffolding visuals.
