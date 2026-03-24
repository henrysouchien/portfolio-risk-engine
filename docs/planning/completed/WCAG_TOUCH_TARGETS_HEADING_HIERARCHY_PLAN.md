# 5A Design Audit — Touch Targets + Heading Hierarchy

**Status**: IMPLEMENTED — Codex 8 review rounds → PASS → implemented → browser verified. One Codex bonus change reverted (factor delta tone). Four bonus changes kept (RefreshCw icon, plural violations, risk violation detail, renderCheckBadge guard).
**Updated**: 2026-03-23
**Parent**: Design Audit (`completed/DESIGN_AUDIT_2026-03-19.md`)

**Context**: Two remaining items from the design audit (2026-03-19). Touch targets are undersized for WCAG compliance, and div elements styled as headings need semantic HTML tags. Heading tag swaps are zero-visual-impact. Touch target size bumps (24→32px, 28→32px) are low-risk with minor vertical growth in affected rows — no layout-breaking changes, but not invisible.

---

## Part 1: Touch Targets

**Target**: WCAG 2.2 SC 2.5.8 (Target Size Minimum, Level AA) requires **24×24px minimum**. The design audit originally referenced 44×44px (SC 2.5.5, Level AAA Enhanced), but that standard is impractical for a desktop-first data-dense analytics dashboard without fundamentally changing the UI density. Our approach brings all remediated button/input controls to **32px minimum** (comfortably exceeding the 24px AA requirement) by fixing specific callsites that override below 32px. The one exception is the RecentRunsPanel checkbox (20×20px), which passes via the SC 2.5.8 spacing exemption (sufficient spacing from adjacent targets). Base button component sizes (32-40px) are left unchanged.

**Approach**: Targeted callsite fixes, not base button size changes (avoids cascading layout density shift).

| # | File | Change | Lines |
|---|------|--------|-------|
| 1 | `blocks/data-table.tsx` | Add `min-h-8` (32px) to sort header Button className | ~118 |
| 2 | `scenario/PortfolioBuilderTab.tsx` | `h-6` → `h-8` on +/- weight buttons | ~162, ~179 |
| 3 | `scenario/PortfolioBuilderTab.tsx` | `h-7` → `h-8` on reset button | ~118 |
| 4 | `scenario/PortfolioBuilderTab.tsx` | `h-6` → `h-8` on weight input | ~170 |
| 5 | `scenario/StressTestsTab.tsx` | Remove `h-7` override on Run button (sm default = h-8) | ~113 |
| 6 | `scenario/HistoricalTab.tsx` | Remove `h-7` override on Run button | ~123 |
| 7 | `scenario/RecentRunsPanel.tsx` | `h-7` → `h-8` on Compare, Clear, Re-run buttons | ~50, ~59, ~115 |
| 8 | `stock-lookup/PortfolioFitTab.tsx` | Add `min-h-8` to "Re-run analysis" button (currently `h-auto p-0`) | ~128 |
| 9 | `scenario/RecentRunsPanel.tsx` | Add `h-5 w-5` to bare checkbox (currently 16×16px → 20×20px) | ~106 |

File paths: rows 1 is under `frontend/packages/ui/src/components/blocks/`, rows 2-9 are under `frontend/packages/ui/src/components/portfolio/`.

### Design Rationale

- **WCAG AA, not AAA**: SC 2.5.8 (AA) requires 24px minimum. SC 2.5.5 (AAA) requires 44px. We target AA with a 32px floor — practical for a desktop analytics dashboard while exceeding the standard.
- **No base button changes**: The CVA button component defines `default` (h-9/36px), `sm` (h-8/32px), `lg` (h-10/40px), `icon` (h-9/36px). All already exceed the 24px AA minimum. We only fix callsites that override below 32px.
- **data-table sort headers**: The `h-auto p-0` override collapses buttons to text height (~16-20px). `min-h-8` (32px) ensures a reasonable click target. Note: `data-table.tsx` is a shared block component used by AttributionTab, PerformanceTab (strategy), DashboardHoldingsCard, and chat data-table-adapter — all consumers get the min-height bump. This is intentional (sort headers should meet 32px everywhere), but verification must cover these consumers.
- **Weight +/- buttons & input**: Bumping from `h-6` (24px) to `h-8` (32px). The `grid grid-cols-3 gap-2` layout absorbs this.
- **h-7 buttons**: 28px → 32px by using `h-8`. Minor 4px vertical growth, unlikely to cause layout issues.
- **PortfolioFitTab "Re-run analysis"**: `h-auto p-0` collapses to text height. Add `min-h-8` to ensure 32px clickable area.
- **RecentRunsPanel checkbox**: Base Checkbox primitive is 16×16px. Add `h-5 w-5` classes to bring to 20×20px. Checkboxes have an exemption in SC 2.5.8 when they have sufficient spacing from adjacent targets, which this one does.

---

## Part 2: Heading Hierarchy

**Hierarchy**: H1 (page) → H2 (SectionHeader) → H3 (tab content sections) → H4 (card titles) → H5 (subsections within cards that already have h4 titles).

Item-level labels in lists (run entry names in RecentRunsPanel, template names in StrategyBuilder) stay as `<div>` — converting them to headings would make screen reader heading navigation noisy. Note: card-title-level scenario names in StressTestsTab (~143) and HistoricalTab (~74) are *already* `<h4>` in the existing code and are not changed by this plan — our h5 additions are children of those existing h4s.

| # | File | Text | `<div>` → | Lines |
|---|------|------|-----------|-------|
| 1 | `stock-lookup/PortfolioFitTab.tsx` | "Add to Portfolio" | `<h3>` | ~117 |
| 2 | `stock-lookup/PortfolioFitTab.tsx` | "Impact Analysis" | `<h3>` | ~159 |
| 3 | `stock-lookup/PortfolioFitTab.tsx` | "Factor Exposure Changes" | `<h4>` | ~217 |
| 4 | `stock-lookup/PortfolioFitTab.tsx` | "Compliance Checks" | `<h4>` | ~244 |
| 5 | `stock-lookup/PortfolioFitTab.tsx` | "Trade Summary" | `<h3>` | ~282 |
| 6 | `scenario/MonteCarloTab.tsx` | "Simulations" | keep `<div>`, add `id` + `aria-labelledby` on RadioGroup | ~83 |
| 7 | `scenario/MonteCarloTab.tsx` | "Time Horizon" | keep `<div>`, add `id` + `aria-labelledby` on RadioGroup | ~103 |
| 8 | `scenario/StressTestsTab.tsx` | "Position Impacts (worst first)" | `<h5>` (parent card title is h4) | ~157 |
| 9 | `scenario/StressTestsTab.tsx` | "Factor Contributions" | `<h5>` (parent card title is h4) | ~192 |
| 10 | `scenario/StressTestsTab.tsx` | "Risk Context" | `<h5>` (parent card title is h4) | ~215 |
| 11 | `scenario/EfficientFrontierTab.tsx` | "Frontier Points" | keep `<div>`, add `id` + `aria-labelledby` on RadioGroup | ~177 |
| 12 | `scenario/HistoricalTab.tsx` | "Factor Impact:" | `<h5>` (parent card title is h4) | ~85 |
| 13 | `scenario/RecentRunsPanel.tsx` | "Recent Runs" | Add `<h3 className="sr-only">Recent Runs</h3>` before Collapsible | ~31 |
| 14 | `scenario/RecentRunsPanel.tsx` | "Comparison" | `<h4>` | ~132 |
| 15 | `scenario/ScenarioHeader.tsx` | "Analysis Complete" | `<h3>` | ~72 |

File paths: rows 1-5 under `frontend/packages/ui/src/components/portfolio/stock-lookup/`, rows 6-15 under `frontend/packages/ui/src/components/portfolio/scenario/`.

### Design Rationale

- **h3**: Direct tab-level content sections (under SectionHeader's h2). "Add to Portfolio", "Impact Analysis", "Trade Summary", "Analysis Complete".
- **h3 (sr-only)**: "Recent Runs" is the panel-level heading but lives inside a `<Button>` (CollapsibleTrigger). A `<h3>` inside a `<button>` is invalid HTML. Instead, add a visually-hidden `<h3 className="sr-only">` before the Collapsible. Screen readers get the heading landmark; sighted users see the existing button text unchanged.
- **h4**: Subsections within h3-level content. "Factor Exposure Changes", "Compliance Checks" are under "Impact Analysis" (h3). "Comparison" in RecentRunsPanel (under the new sr-only h3).
- **h5**: Subsections inside cards whose titles are already h4 in the existing code. StressTestsTab scenario name (existing h4 at line 143), HistoricalTab scenario name (existing h4 at line 74) — their children "Position Impacts", "Factor Contributions", "Risk Context", "Factor Impact:" must be h5 to avoid flattening.
- **RadioGroup labels**: "Simulations", "Time Horizon", "Frontier Points" label entire RadioGroups, not single inputs. `<label>` is semantically wrong for group labels. Instead, keep `<div>` but add `id="mc-simulations-label"` (etc.) and `aria-labelledby` on the RadioGroup. This is the correct ARIA pattern for group labeling.
- **Existing patterns (unchanged by this plan)**: `section-header.tsx` uses `<h2>`, `PerformanceHeaderCard.tsx` uses `<h1>`, scenario tabs use `<h4>` for card titles (locally appropriate as the primary heading within each card, though the broader h2→h4 skip is a pre-existing gap outside this plan's scope).

---

## Files Touched (9 total)

1. `frontend/packages/ui/src/components/blocks/data-table.tsx` — touch target (sort header min-h)
2. `frontend/packages/ui/src/components/portfolio/scenario/PortfolioBuilderTab.tsx` — touch targets (3 fixes: +/- buttons, reset button, weight input)
3. `frontend/packages/ui/src/components/portfolio/scenario/StressTestsTab.tsx` — touch target (Run button) + 3 headings (h5)
4. `frontend/packages/ui/src/components/portfolio/scenario/HistoricalTab.tsx` — touch target (Run button) + 1 heading (h5)
5. `frontend/packages/ui/src/components/portfolio/scenario/RecentRunsPanel.tsx` — touch targets (3 buttons + checkbox) + 2 headings (sr-only h3 + h4)
6. `frontend/packages/ui/src/components/portfolio/scenario/MonteCarloTab.tsx` — 2 aria-labelledby additions
7. `frontend/packages/ui/src/components/portfolio/scenario/EfficientFrontierTab.tsx` — 1 aria-labelledby addition
8. `frontend/packages/ui/src/components/portfolio/scenario/ScenarioHeader.tsx` — 1 heading (h3)
9. `frontend/packages/ui/src/components/portfolio/stock-lookup/PortfolioFitTab.tsx` — 1 touch target (Re-run button) + 5 headings (h3/h4)

## Verification

1. `cd frontend && npm run build` — confirm no TypeScript errors
2. Visual check: open Scenario Analysis tabs, Stock Lookup Portfolio Fit, Holdings table, Attribution tab, Strategy Performance tab, and AI chat data tables — verify no layout shifts (data-table.tsx is shared)
3. Confirm all remediated button/input controls meet 32px minimum (checkbox exempt via SC 2.5.8 spacing)
4. Heading hierarchy check: all div→h3/h4/h5 swaps render correct semantic tags; no sibling h4+h4 where one should be h5 (within scope of this plan's changes). Pre-existing h2→h4 skips in scenario tabs are out of scope.
5. sr-only h3 check: RecentRunsPanel sr-only h3 is visually hidden but present in DOM and accessible to screen readers
6. aria-labelledby check: MonteCarloTab ("Simulations", "Time Horizon") and EfficientFrontierTab ("Frontier Points") RadioGroups have `aria-labelledby` pointing to valid `id` attributes on their label divs
