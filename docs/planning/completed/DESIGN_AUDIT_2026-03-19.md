# Design Audit Report: PortfolioRisk Pro

**URL:** http://localhost:3000
**Date:** 2026-03-19
**Mode:** Full (6 pages audited)
**Visual Style:** Premium
**Design Score: B**
**AI Slop Score: B+**

---

## Phase 1: First Impression

- The site communicates **professional competence and financial seriousness.** It looks like a real portfolio management tool, not a template.
- I notice **the alert banner (yellow) dominates the above-the-fold space** — 3 separate DSU alerts consume ~40% of the visible viewport before you see any portfolio data.
- The first 3 things my eye goes to are: **the yellow alert banner**, **the $125,565 portfolio value**, and **the left sidebar icons**.
- If I had to describe this in one word: **functional.**

The dashboard works. It's not ugly. But it's not *distinctive* either. The alert banner steals the show when it shouldn't.

---

## Phase 2: Inferred Design System

### Fonts
- Primary: `Inter, -apple-system, system-ui, Segoe UI, Roboto, sans-serif`
- Fallback: `ui-sans-serif, system-ui, sans-serif`
- Only 1 font family (Inter) — good. But Inter is the most common AI-generated-app font. Not a ding per se, but worth noting.

### Colors (38 unique)
- Greens: `rgb(4,120,87)`, `rgb(16,185,129)`, `rgb(5,150,105)` — primary brand
- Yellows/Amber: `rgb(217,119,6)`, `rgb(180,83,9)` — warnings
- Reds: `rgb(220,38,38)`, `rgb(185,28,28)` — errors/negative
- Blues: `rgb(37,99,235)`, `rgb(29,78,216)` — links/info
- Purples: `rgb(147,51,234)`, `rgb(107,33,168)` — accent
- Neutrals: `rgb(37,50,65)`, `rgb(107,115,123)`, `rgb(244,245,246)` — cool-toned
- 38 colors is high but mostly systematic (semantic + variants). The palette is **cool-toned and consistent**.

### Heading Scale
- Only 1 H1 found: "PortfolioRisk Pro" at 18px/600w — **too small for an H1**
- Section titles like "Performance Analytics" and "Portfolio Holdings" are styled as headings but not using heading tags

### Touch Targets
- Multiple buttons at 32x32 (refresh, notifications, layout toggle) — **below 44px minimum**
- Table sort buttons at 16px height — **critically undersized**
- Ticker buttons at 26px height — **undersized**

### Performance
- DOM ready: 209ms, full load: 307ms — **excellent**

---

## Phase 3: Page-by-Page Findings

### Dashboard (Overview)
- Yellow alert banner dominates viewport — alert rows have no dismiss/collapse
- Large empty gap between alerts and stat cards (~80px of nothing)
- "AI Insights" button floating alone with no visual grouping
- Stat cards are clean and well-designed
- Performance trend chart is clean
- "Asset Allocation: Real Data | Source: useRiskAnalysis" debug text visible at bottom — **development artifact in UI**

### Holdings
- Well-structured data table with good information density
- Sector badges use color-coded pills — effective
- Summary cards at top (Invested Positions, Total Return, Avg Vol, Active Alerts) — good hierarchy
- Weight column has progress bars — nice visual indicator
- Risk Score column gets cut off at right edge — may need horizontal scroll awareness

### Performance
- Performance Analytics header has good visual hierarchy
- 4 metric cards (Portfolio Return, Benchmark, Excess Return, Sharpe) with color-coded badges — well done
- 3 insight cards (Performance, Risk, Opportunity) with impact badges — good pattern
- Color coding: green for positive, red for negative, yellow for caution — semantic and consistent
- "high impact" / "low impact" badges are clear

### Factors / Risk Analysis
- Two-panel layout (Factor Risk Model + Risk Analysis) — good use of space
- Factor exposure bars use gradient fills — visually distinctive
- Risk Score components (Concentration, Volatility, Factor, Sector) with progress bars — clear
- Tab navigation (Factor Exposure / Risk Attribution / Model Insights) works well
- Tab navigation (Risk Score / Stress Tests / Hedging) on right panel

### Research (Stock Lookup)
- Clean empty state with search icon, message, and example ticker pills (AAPL, TSLA, NVDA, JPM)
- Good empty state design — has warmth and direction
- Debug text visible: "Stock: None | Search: Empty | Results: 0" — **development artifact**

### Settings (Risk Management)
- Clean form layout with sliders
- Summary cards at top with key risk metrics
- Tab navigation (Risk Limits / Monitoring / Alerts)
- "Save Settings" green CTA is prominent and correct
- Slider controls are accessible and well-labeled

---

## Phase 4: Cross-Page Consistency

- Navigation sidebar consistent across all pages
- Header bar (logo + account selector + notifications) consistent
- Card styling consistent (rounded, white background, subtle shadow)
- Color semantics consistent (green=good, red=bad, yellow=warning)
- Typography consistent but heading hierarchy is flat — no true H2-H6 usage

---

## Phase 5: AI Slop Detection

| Pattern | Found? | Notes |
|---------|--------|-------|
| Purple/violet gradients | Partial | Purple used for Real Estate sector badge, not as background gradient |
| 3-column feature grid | No | Stat cards are contextual, not generic features |
| Icons in colored circles | **Yes** | Section headers (Performance Analytics, Portfolio Holdings, Risk Management, Stock Lookup) all use icon-in-circle pattern |
| Centered everything | No | Left-aligned content throughout |
| Uniform bubbly border-radius | Partial | Consistent but not excessive — cards use moderate radius |
| Decorative blobs/SVGs | No | Clean |
| Emoji as design elements | No | |
| Colored left-border cards | No | |
| Generic hero copy | No | Domain-specific copy |
| Cookie-cutter section rhythm | No | Pages have distinct layouts |

**AI Slop Score: B+** — The icon-in-colored-circle pattern on section headers is the main tell. Otherwise the app reads as purposefully designed for its domain.

---

## Phase 6: Scoring

| Category | Grade | Weight | Key Findings |
|----------|-------|--------|-------------|
| Visual Hierarchy | B | 15% | Alert banner dominates; empty gap between sections; "AI Insights" floats |
| Typography | B- | 15% | Inter only (generic), H1 at 18px too small, no heading hierarchy in markup |
| Spacing & Layout | B | 15% | Mostly systematic; gap between alerts and cards is notable |
| Color & Contrast | A- | 10% | Consistent semantic palette, cool-toned, well-applied |
| Interaction States | B | 10% | Touch targets too small (32x32 buttons, 16px sort headers) |
| Responsive | C+ | 10% | Mobile sidebar doesn't collapse; content gets cramped at 375px |
| Content Quality | B- | 10% | Debug text visible ("Source: useRiskAnalysis", "Stock: None \| Search: Empty") |
| AI Slop | B+ | 5% | Icon-in-circle headers are the main tell |
| Motion | B | 5% | No distracting animations; couldn't evaluate transitions deeply |
| Performance | A | 5% | 307ms load, no console errors |

---

## Quick Wins (highest impact, lowest effort)

1. **Remove debug text** — "Asset Allocation: Real Data | Source: useRiskAnalysis" and "Stock: None | Search: Empty | Results: 0" are visible to users
2. **Increase touch targets** — Sidebar icon buttons, table sort headers, and ticker buttons are all below 44px minimum
3. **Collapse/dismiss alert banner** — 3 DSU alerts eating 40% of viewport; add a collapse toggle or limit to 1 visible with "show more"
4. **Reduce empty gap** between alert banner and stat cards on dashboard
5. **Fix H1 sizing** — "PortfolioRisk Pro" at 18px is too small for the only H1; or use proper H2-H6 for section titles

---

## Deferred / Deeper Work

- **Responsive redesign for mobile** — The sidebar-based navigation doesn't work well at 375px. Would need a bottom nav or hamburger menu for proper mobile support. This is an ocean, not a lake.
- **Icon-in-circle header pattern** — Replacing these across all section headers would be a design system change. Needs a design direction decision first.
- **Font differentiation** — Inter is fine but generic. A display font for headings (e.g., DM Sans, Manrope, or a custom choice) would add personality. Low priority unless aiming for A-tier design.
- **Heading semantic markup** — Using proper H2-H6 tags instead of styled divs improves accessibility and SEO. Medium effort across all pages.
- **Dark mode** — `color-scheme: normal` with no `data-theme` toggle visible. No `color-scheme: dark` on html. Dark mode support not detected.

---

## Screenshots

All screenshots saved to `docs/planning/design-audit-screenshots/`:
- `first-impression.png` — Dashboard at load
- `dashboard-bottom.png` — Dashboard scrolled (allocation + income)
- `dashboard-mobile.png` — Mobile viewport (375x812)
- `dashboard-tablet.png` — Tablet viewport (768x1024)
- `dashboard-desktop.png` — Desktop viewport (1280x720)
- `holdings.png` — Holdings page
- `performance.png` — Performance Analytics page
- `factors.png` — Factor Risk Model + Risk Analysis
- `research.png` — Stock Risk Lookup (empty state)
- `settings.png` — Risk Management Settings
