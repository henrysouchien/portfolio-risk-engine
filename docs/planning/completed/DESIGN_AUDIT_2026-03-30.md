# Design Audit: PortfolioRisk Pro
**Date:** 2026-03-30
**URL:** http://localhost:3000
**Branch:** main
**Scope:** Full site (7 views)
**Classification:** APP UI (dashboard-driven, data-dense, task-focused)

---

## Headline Scores

| Metric | Grade |
|--------|-------|
| **Design Score** | **C+** |
| **AI Slop Score** | **B** |

---

## First Impression

The site communicates **competence and data density**. This is clearly a financial analytics tool built by someone who understands the domain.

I notice the **6-card metric grid dominates the dashboard** with equal visual weight across all metrics. Total Portfolio Value ($139,983) doesn't feel more important than Sharpe Ratio, even though it is.

The first 3 things my eye goes to are: **the green dinosaur logo**, **the red negative numbers** (-3.3%, -10.1%, -12.0%), and **the "AI Insights" button**.

If I had to describe this in one word: **functional**.

---

## Inferred Design System

### Fonts
- **Primary:** Inter (with -apple-system fallback)
- **Secondary:** Crimson Text imported in CSS but never used
- **System fallback:** ui-sans-serif, system-ui stack (some elements)
- **Verdict:** Single-font system. Inter is competent but generic for a financial product. The unused Crimson Text import suggests an intent for editorial hierarchy that was never realized.

### Colors
- **Foundation:** Well-defined HSL CSS variables on `:root` (~40 semantic tokens)
- **Primary accent:** Emerald/green (brand, positive states)
- **Error/negative:** Red spectrum (rgb(220,38,38) through rgb(239,68,68))
- **Neutral palette:** Warm-leaning, 210° hue base (8 steps)
- **Problem:** Charts and transitions bypass the system with hardcoded hex/rgb values
- **Verdict:** Good foundation, incomplete enforcement. ~70% of color usage goes through the system.

### Heading Scale
| Tag | Size | Weight | Usage |
|-----|------|--------|-------|
| H1 | 18px | 600 | Brand name only |
| H2 | ~24px | 600 | Page titles (Scenarios) |
| H3 | ~20px | 600 | Section headings |
| H4 | 16px | 600 | Card titles |
| H5 | 12px | 600 | Sub-labels |
- **Problem:** H5 at 12px is below recommended caption minimum. H1 at 18px feels undersized for brand anchor.

### Spacing
- **No systematic scale.** Mix of Tailwind utilities (p-4, gap-2) and magic numbers (right-[510px], w-[550px], min-h-[260px]).
- Border-radius values: 4px, 8px, 10px, 12px, 16px, 9999px. The 10px breaks the 4px-step pattern.

### Performance
- **Load time:** 208ms total (excellent)
- **Code splitting:** 16 chunks, ~1MB deferred
- **LCP:** Well under 2.0s target

---

## Category Grades

| Category | Grade | Weight | Key Finding |
|----------|-------|--------|-------------|
| Visual Hierarchy | C | 15% | Dashboard card grid has no focal point, equal visual weight everywhere |
| Typography | C | 15% | Inter-only, unused Crimson Text, tiny 10-11px metadata |
| Spacing & Layout | C | 15% | Magic numbers, no systematic scale, arbitrary Tailwind values |
| Color & Contrast | B | 10% | Good CSS variable system, partial enforcement in charts |
| Interaction States | B | 10% | Hover states present, workflow CTAs well-designed |
| Responsive | D | 10% | Stacked desktop on mobile, content truncation, desktop-only testing |
| Content Quality | B | 10% | Clear copy, good scenario descriptions, debug text leaking |
| AI Slop | B | 5% | No major slop patterns, card grid borderline but functional |
| Motion | B | 5% | Landing reveals good, some ornamental animations in-app |
| Performance | A | 5% | 208ms load, excellent code splitting |

---

## Litmus Checks (Cross-Model Consensus)

| Check | Claude (live) | Codex (source) | Consensus |
|-------|---------------|----------------|-----------|
| 1. Brand unmistakable in first screen? | YES | YES | YES |
| 2. One strong visual anchor? | NO (dashboard) | YES (landing) | SPLIT |
| 3. Understandable by scanning headlines? | YES | YES | YES |
| 4. Each section has one job? | MOSTLY | NO | NO |
| 5. Are cards actually necessary? | BORDERLINE | NO | NO |
| 6. Motion improves hierarchy? | NO | NO | NO |
| 7. Premium without decorative shadows? | NO | NO | NO |

### Hard Rejections
| Rule | Status |
|------|--------|
| 1. Generic SaaS card grid first impression | NO |
| 2. Beautiful image with weak brand | NO |
| 3. Strong headline with no clear action | NO |
| 4. Busy imagery behind text | NO |
| 5. Sections repeating same mood statement | NO |
| 6. Carousel with no narrative purpose | NO |
| 7. App UI made of stacked cards instead of layout | **YES** [cross-model] |

---

## Findings

### FINDING-001: Dashboard overview is stacked cards, not a layout [HIGH]
**Category:** Visual Hierarchy
**Impact:** The overview experience has no visual anchor. Six metric cards with equal weight, plus holdings card, alerts panel, and earnings card, all in a card quilt. The layout doesn't carry hierarchy, the cards do all the work.
**Source:** `ModernDashboardApp.tsx:188`, confirmed by Codex
**Suggestion:** Promote Total Portfolio Value to a hero-width element. Use the layout itself (column widths, vertical space) to create hierarchy instead of card borders.

### FINDING-002: Touch targets below 44px WCAG minimum [HIGH]
**Category:** Interaction States / Accessibility
**Impact:** Ticker pills at 26px height, sidebar buttons at 32px, sort buttons at 32px. Fails WCAG AA SC 2.5.8.
**Source:** Live audit (20 elements found below 44px)
**Suggestion:** Set `min-height: 44px` on button base styles. Ticker pills need padding increase.

### FINDING-003: Mobile layout is stacked desktop [HIGH]
**Category:** Responsive
**Impact:** On 375px, card content truncates ("$139," "$-10.1..."), sidebar icons still show eating horizontal space, no content adaptation for touch. Not a designed mobile experience.
**Source:** Responsive screenshots, Codex: `playwright.config.ts:27` (Desktop Chrome only)
**Suggestion:** Hide sidebar on mobile, use single-column layout, adapt card content.

### FINDING-004: Debug text leaking into production views [HIGH]
**Category:** Content Quality
**Impact:** "Performance: No Data | Portfolio: Loaded" (red text, bottom-right of Performance view), "Stock: None | Search: Empty | Results: 0" (Research view). Users see internal state.
**Source:** Live screenshots
**Suggestion:** Remove or gate behind `import.meta.env.DEV`.

### FINDING-005: Spacing uses magic numbers [HIGH]
**Category:** Spacing & Layout
**Impact:** `right-[510px]`, `w-[550px]`, `w-[480px]`, `rounded-[28px]`, `text-[10px]`, `text-[11px]`. No systematic scale.
**Source:** Codex: `AIChat.tsx:133`, `ArtifactPanel.tsx:58`, `ModernDashboardApp.tsx:242`
**Suggestion:** Define spacing tokens in Tailwind config. Replace magic numbers with named values.

### FINDING-006: Color system partially enforced [MEDIUM]
**Category:** Color & Contrast
**Impact:** Charts (PerformanceTrendChart, RiskWeightChart, BenchmarksTab) and transitions hardcode hex/rgb values instead of using CSS variables.
**Source:** Codex: `PerformanceTrendChart.tsx:60`, `BenchmarksTab.tsx:87`, `AuthTransition.tsx:97`
**Suggestion:** Use `var(--chart-1)` through `var(--chart-5)` consistently. Add chart-specific semantic tokens if needed.

### FINDING-007: Inter-only typography, unused Crimson Text import [MEDIUM]
**Category:** Typography
**Impact:** No typographic personality. Headings and body are all Inter. `index.css:114` imports Crimson Text but it's never applied. Secondary UI falls to tiny 10-11px uppercase metadata.
**Source:** Codex: `index.css:114`, `index.css:363`
**Suggestion:** Either apply Crimson Text as heading font for editorial contrast, or remove the import. Increase minimum text to 12px.

### FINDING-008: Table cells missing tabular-nums [MEDIUM]
**Category:** Typography
**Impact:** Summary cards use `tabular-nums` correctly, but the holdings table `<td>` elements don't. Number columns (Market Value, Weight, Returns) will shift width as data changes.
**Source:** Live audit (JS extraction)
**Suggestion:** Add `font-variant-numeric: tabular-nums` to table number cells.

### FINDING-009: Holdings table rows not clickable [MEDIUM]
**Category:** Interaction States
**Impact:** In a portfolio app, users expect to click a holding to see detail. The table rows have no click handler, no hover state suggesting interactivity, and no cursor change.
**Source:** Live interaction test
**Suggestion:** Add row click → navigate to stock research. Add hover highlight and `cursor: pointer`.

### FINDING-010: Sidebar nav icons have no labels [MEDIUM]
**Category:** Accessibility / Content Quality
**Impact:** Icon-only navigation requires memorization. Active state (green) is clear, but new users can't identify views without hovering.
**Source:** Live screenshots
**Suggestion:** Add text labels below icons, or at minimum ensure `aria-label` and tooltip on hover.

### FINDING-011: Border-radius inconsistency [POLISH]
**Category:** Spacing & Layout
**Impact:** Values 4/8/10/12/16/9999px. The 10px breaks the 4px-step pattern.
**Source:** Live JS extraction
**Suggestion:** Standardize to 4/8/12/16/9999 scale.

### FINDING-012: No text-wrap: balance on headings [POLISH]
**Category:** Typography
**Impact:** Multi-line headings on narrow viewports break unevenly.
**Source:** Live JS extraction (all headings use default `wrap`)
**Suggestion:** Add `text-wrap: balance` to h1-h4 in global CSS.

---

## CODEX SAYS (design source audit):

Classification: HYBRID leaning APP UI. Hard rejection #7 triggered (stacked cards as layout). Key findings:
1. Overview is stacked summary cards, not layout-led workspace
2. Responsive not reliable, hardcoded widths, desktop-only Playwright
3. Color foundation good but enforcement weak in charts
4. Spacing not systematic, many magic numbers
5. Typography competent but not expressive, Crimson Text imported unused
6. Accessibility incomplete, no landmarks on landing, small touch targets
7. Motion exists but some ornamental (breathing logo, pulsing dots, ping badge)

Litmus: YES/YES/YES/NO/NO/NO/NO (3/7)

## CLAUDE SUBAGENT (design consistency):

Three conflicting color definition patterns found (CSS vars, hardcoded Tailwind, hex in CSS). Spacing values inconsistent with no base scale evidence. Dashboard cards at `DashboardAlertsPanel.tsx:32-46` use hardcoded severity colors (`border-l-red-500`, `bg-red-50/50`). Button component at `button.tsx:15-29` has multiple size variants but some fall below 44px. Custom scrollbar `6px` hardcoded.

---

## Quick Wins (highest impact, <30 min each)

1. **Remove debug text** from Performance and Research views (gate behind `import.meta.env.DEV`)
2. **Add tabular-nums** to table number cells globally
3. **Add text-wrap: balance** to headings in global CSS
4. **Increase touch targets** to 44px minimum on button base styles
5. **Remove unused Crimson Text import** (or apply it to headings)

---

## Screenshots

| View | Desktop | Mobile | Tablet |
|------|---------|--------|--------|
| Dashboard | dashboard-desktop.png | dashboard-mobile.png | dashboard-tablet.png |
| Holdings | holdings-desktop.png | holdings-mobile.png | holdings-tablet.png |
| Scenarios | scenarios-desktop.png | scenarios-mobile.png | scenarios-tablet.png |
| Performance | performance.png | — | — |
| Risk | risk-full.png | — | — |
| Research | research.png | — | — |
| Trading | trading.png | — | — |
| Settings | settings.png | — | — |
