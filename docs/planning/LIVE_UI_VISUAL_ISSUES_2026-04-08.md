# Live UI Visual Issues and Improvement Plan (2026-04-08)

## Scope
This document captures visual-only feedback from the live app running on `http://localhost:3000` on April 8, 2026.

Primary screens reviewed:
- Overview
- Holdings
- Performance
- Risk
- Research
- Stress Test
- Settings

Live captures used:
- `test-results/live-ui/overview.png`
- `test-results/live-ui/holdings.png`
- `test-results/live-ui/performance.png`
- `test-results/live-ui/risk.png`
- `test-results/live-ui/research.png`
- `test-results/live-ui/stress-test.png`
- `test-results/live-ui/settings.png`

## Current Visual Strengths
- Clear, distinct product identity with a cohesive dark "desk" aesthetic.
- Consistent page scaffold across major views (left nav, top ticker, central content, right rail).
- Strong narrative-first pattern in hero cards that frames the data context.
- Color usage generally communicates gain/loss and severity states effectively.

## Prioritized Issues

### P1: Low text contrast in secondary and metadata content
Observed in tables, labels, chips, right-rail annotations, and helper lines.

Impact:
- Reduces readability and scan speed.
- Increases eye strain in dense screens (Overview, Holdings, Performance).
- Makes secondary context feel "disabled" even when it is important.

### P1: Visual density too high in core analytical views
Observed in Overview and Holdings where many bordered blocks compete at similar visual weight.

Impact:
- Weakens focal priority.
- Makes it harder to identify "what matters now" in the first 3-5 seconds.
- Contributes to cognitive load during decision workflows.

### P1: Right rail competes with core content while being hard to read
The right rail is persistent and information-rich, but has low contrast and high block repetition.

Impact:
- Pulls attention away from main analysis panel.
- Does not consistently communicate hierarchy among note, overnight change, and prompts.

### P2: Active navigation state lacks emphasis
Active left-nav state is visible but not dominant enough for fast orientation, especially with many menu items.

Impact:
- Slower context switching.
- Reduced confidence about the currently selected analysis surface.

### P2: Card and border treatment creates noise
Many cards use similar line weight, corner style, and tonal separation.

Impact:
- Flat visual hierarchy between critical KPI surfaces and secondary containers.
- Overly "grid-like" feeling that reduces clarity.

### P2: Data table readability can improve for long-session use
In holdings/performance tables, row spacing and text scale are compact against a low-contrast palette.

Impact:
- Harder symbol/name/value association.
- Faster fatigue when scanning cross-column relationships.

## Suggested Visual Improvements

### 1) Raise baseline contrast for non-primary text (P1)
- Increase contrast for muted text tokens used by metadata, headers, labels, and right-rail copy.
- Keep primary numbers bright; bring secondary copy up one step to preserve hierarchy.
- Validate all table labels and annotation text against dark-surface accessibility targets.

Expected result:
- Better scan speed and reduced fatigue without changing overall dark aesthetic.

### 2) Rebalance hierarchy in dense screens (P1)
- Explicitly define 1 primary zone, 2 secondary zones, and tertiary details per page.
- Increase spacing between major blocks before adding new borders.
- Reduce equal-weight card styling so KPI strip, narrative card, and core table/chart are visually tiered.

Expected result:
- Clearer first-glance interpretation and stronger analytical flow.

### 3) Simplify and demote right rail presentation (P1)
- Reduce right-rail block count or collapse non-critical sections by default.
- Increase heading contrast and spacing between rail sections.
- Keep one primary call-to-action in the rail; demote secondary prompts.

Expected result:
- Main canvas regains focus; right rail becomes supportive instead of competitive.

### 4) Strengthen active navigation affordance (P2)
- Use a stronger active treatment (higher contrast fill, left accent bar, or icon+text emphasis).
- Ensure inactive states are clearly subdued relative to active state.

Expected result:
- Faster orientation and fewer navigation mistakes.

### 5) Reduce border noise and rely more on spacing (P2)
- Decrease frequency/intensity of card outlines.
- Use tonal grouping and consistent vertical rhythm to separate sections.
- Reserve stronger boundaries for truly interactive or critical regions.

Expected result:
- Cleaner, more modern visual rhythm with improved hierarchy.

### 6) Improve table legibility for analysis-heavy workflows (P2)
- Increase row height slightly in holdings/performance data tables.
- Tighten column typography rules (primary value vs metadata scale).
- Add subtle zebra/hover differentiation only where it improves row tracking.

Expected result:
- Easier symbol-to-metric reading and reduced long-session strain.

## Suggested Execution Order
1. Contrast tokens and text readability pass.
2. Right rail simplification and hierarchy pass.
3. Dense screen hierarchy pass (Overview and Holdings first).
4. Navigation state emphasis.
5. Table readability tuning.

## Open Questions
- Should the right rail remain always visible on desktop, or become context-collapsible per page?
- Is the desired visual direction "institutional terminal" (ultra dense) or "decision workspace" (more breathing room)?
- Do we want one global contrast uplift, or view-specific tuning for table-heavy pages only?

## Light Mode Review (Live)
Light mode was reviewed live on April 8, 2026 by setting `localStorage.theme = "light"` and reloading the app.

Live captures used:
- `test-results/live-ui-light/overview.png`
- `test-results/live-ui-light/holdings.png`
- `test-results/live-ui-light/performance.png`
- `test-results/live-ui-light/risk.png`
- `test-results/live-ui-light/research.png`
- `test-results/live-ui-light/stress-test.png`
- `test-results/live-ui-light/settings.png`

### Light Mode Observations
- Structure and hierarchy are easier to parse at first glance than dark mode.
- Primary narrative cards remain readable, but many secondary tokens are still low contrast.
- The interface becomes very monochrome gray, reducing section differentiation.
- Positive/negative metric colors remain useful, but neutral UI states can feel washed out.
- Right rail remains visually busy relative to its supporting role.

### Light-Mode-Specific Issues
- P1: Insufficient tonal separation between page background, cards, and table surfaces.
- P1: Muted text in labels/metadata still sits too close to background luminance.
- P2: Borders are visible but repetitive, producing a \"wireframe\" look instead of strong grouping.
- P2: Active navigation state is clearer than dark mode, but still not emphatic enough.

### Light-Mode Improvement Actions
1. Introduce stronger neutral steps for surface layering (page, card, inset, interactive).
2. Increase muted text contrast one token level for labels, helper text, and rail metadata.
3. Reduce border dependence by increasing surface contrast and spacing rhythm.
4. Add a stronger active navigation treatment (tone + accent + icon/text emphasis).
5. Keep state colors (gain/loss/severity) saturated, but increase neutral contrast around them.

## Visual Direction Statement
Current light-mode impression reads as editorial/institutional, similar to a financial publication or internal strategy memo.

To align implementation choices, choose one of these directions:

### Option A: Editorial Terminal
Goal:
- Lean into the FT/Economist/desk-brief feel with high information density and restrained visual language.

Principles:
- Narrative-first framing and report-like content rhythm.
- Tight grids, compact tables, and low-chrome controls.
- Minimal decorative color; use color mainly for state and risk signals.

Guardrails:
- Keep contrast high enough for long-session reading.
- Preserve clear active state affordances despite minimal styling.
- Avoid flattening all surfaces into one gray plane.

### Option B: Decision Workspace
Goal:
- Keep institutional credibility but shift toward a product-native, action-oriented workspace.

Principles:
- Stronger hierarchy between primary analysis, secondary context, and tertiary metadata.
- More explicit interaction cues (active tabs, selected nav, actionable controls).
- Increased breathing room around high-value modules.

Guardrails:
- Avoid consumer-app styling or overly playful visual treatment.
- Maintain analytical density where it improves speed of interpretation.
- Keep risk-state colors semantically consistent across views.

### Recommendation
Recommended default: Option B (`Decision Workspace`) with selective editorial cues from Option A.

Rationale:
- The product appears to be used for live decisions, not only passive reading.
- Current UI already carries institutional tone; the larger opportunity is improving decision speed and clarity.

## Right Rail v2: Conversational Intelligence Layer (View-Agnostic)
Keep the right rail as a permanent pattern, but define a consistent, view-agnostic contract so it supports both editorial reading and interactive AI workflows.

### Rail Contract (All Views)
1. Current State
- What matters now in the current view (short, high-signal summary).

2. Interpretation
- AI interpretation of current state when applicable.
- If interpretation is weak due to missing or stale data, state that explicitly.

3. Decision Support
- Recommended next step plus alternatives where useful.
- Keep this action-oriented, not only descriptive.

4. Interaction
- Prompt entry and suggested follow-ups tied to selected UI context.
- Clicking key modules (metric, row, chart segment, alert) should inject context into the rail conversation.

5. History
- Prior notes and prior questions remain available but collapsed by default.

### Per-View Semantics (Same Structure, Different Language)
- Risk: dominant drivers, regime sensitivity, hedge choices.
- Holdings: concentration map, line-level risk/reward, rebalance candidates.
- Performance: attribution quality, benchmark gap explanation, persistence checks.
- Research: evidence quality, peer context, decision readiness.
- Settings: configuration health, integration status, policy gaps.

### Visual Hierarchy Rules
- Rail stays visibly secondary to the main analysis canvas.
- Only one active block in the rail should have primary emphasis.
- Additional content is grouped as subdued sections (or collapsed).

### Mini Artifact Preservation
Preserve the existing mini artifact as a support element in the rail.

Guidance:
- Keep it compact and contextual (quick visual proof, not the main analysis surface).
- Attach it to the active rail block (Current State or Decision Support).
- Ensure it can deep-link to the full artifact or relevant main-pane module.
- Avoid stacking multiple mini artifacts at once; one active artifact is preferred.
