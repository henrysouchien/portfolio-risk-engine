# Cross-Browser and Mobile Verification QA Plan

**Status**: PROPOSED
**Created**: 2026-03-19
**Last Updated**: 2026-03-19

---

## 1. Objective

Systematically verify the PortfolioRisk Pro frontend renders correctly and functions reliably across all target browsers and device form factors before public launch. The app currently runs Playwright e2e tests against Chromium only. This plan extends coverage to Firefox, Safari, Edge (desktop) and iOS Safari / Android Chrome (mobile).

---

## 2. Current State Assessment

### 2.1 Tech Stack

| Layer | Technology | Browser Relevance |
|-------|-----------|-------------------|
| Build | Vite 7.1, React 19.2, TypeScript 5.8 | Vite defaults to `esnext` build target -- no explicit `build.target` set |
| CSS | Tailwind 3.4, PostCSS + Autoprefixer | Autoprefixer handles vendor prefixes; Tailwind utilities are standards-based |
| UI primitives | Radix UI (25 components), Vaul (drawer), CVA, cmdk | Radix is well-tested cross-browser; Vaul uses touch events internally |
| Charts | Recharts 2.8 (SVG-based, 37 chart files) | SVG rendering varies slightly across engines; tooltip positioning can differ |
| Animation | Framer Motion 12.x, CSS keyframes, backdrop-filter | `backdrop-filter` has partial Safari support; Framer uses Web Animations API |
| State | Zustand 4.5, TanStack Query 5.x | No browser-specific concerns |
| Streaming | SSE via fetch/EventSource (GatewayClaudeService) | EventSource compatibility is good; fetch-based SSE needs ReadableStream |
| Markdown | react-markdown 10, KaTeX 0.16, remark-gfm | KaTeX renders math via DOM manipulation -- needs verification |

### 2.2 CSS Features Requiring Verification

Found in `frontend/packages/ui/src/index.css`:

| CSS Feature | Browser Risk | Lines |
|-------------|-------------|-------|
| `backdrop-filter: blur()` | Safari needs `-webkit-` prefix (Autoprefixer should handle) | glass-premium, glass-tinted |
| `mask-composite: xor` | Firefox uses `-webkit-mask-composite: exclude` | morph-border |
| `text-wrap: balance` | Not supported in older Safari/Firefox | text-balance-optimal |
| `-webkit-text-fill-color` | WebKit-only, needs fallback check | text-gradient-premium |
| `scrollbar-color` / `::-webkit-scrollbar` | Split API: Firefox uses `scrollbar-color`, WebKit uses pseudo-elements | scroll-premium |
| `overflow: hidden` + `background-clip: padding-box` | Interaction with border-radius can differ | rounded-3xl/2xl fix |
| `@media (prefers-reduced-motion)` | Well-supported but must verify honor | Accessibility section |

### 2.3 Existing Test Infrastructure

- **Playwright config**: `e2e/playwright.config.ts` -- Chromium only, 90s timeout, 1 worker
- **Existing e2e tests**: 5 spec files (onboarding navigation, CSV import happy path, CSV import errors, normalizer builder, portfolio selector scoping)
- **Auth mock**: `e2e/global-setup.ts` creates `auth-state.json` with session cookie
- **API mocking**: `e2e/helpers/api-mocks.ts` with `mockAuth()`, `mockEmptyPortfolioList()`, `mockPreviewSuccess()`, etc.
- **Unit tests**: Vitest with jsdom/happy-dom (443+ tests in frontend packages)
- **No browserslist in active config**: The workspace `package.json` has no browserslist. A stale `package-update.json` has `">0.2%, not dead, not op_mini all"` for production.
- **No Vite build target**: `vite.config.ts` does not set `build.target`, so Vite defaults to `esnext`.

### 2.4 Responsive CSS

Minimal responsive CSS exists today:

- **Single `@media (max-width: 768px)` block**: Disables hover effects on mobile, tightens `.container-claude` padding.
- **Tailwind responsive utilities**: 78 files use `sm:`, `md:`, `lg:`, `xl:` prefixes (most commonly `xl:grid-cols-2`, `xl:inline` for nav labels, `md:` grid layouts).
- **No touch-action directives**: No explicit `touch-action` CSS or touch event handlers found.
- **Sidebar**: Fixed `w-16` (64px) -- no collapse/hamburger for mobile.
- **NavBar**: Labels hidden below `xl` breakpoint (`hidden xl:inline`), icons-only on smaller screens.

---

## 3. Browser Matrix

### 3.1 Desktop Browsers

| Browser | Engine | Min Version | Priority | Notes |
|---------|--------|-------------|----------|-------|
| Chrome | Blink | 120+ | P0 | Primary dev browser, Playwright Chromium project |
| Firefox | Gecko | 120+ | P1 | Different CSS masking, scrollbar API |
| Safari | WebKit | 17.0+ (macOS 14+) | P1 | backdrop-filter, text-wrap, WebKit-specific CSS |
| Edge | Chromium | 120+ | P2 | Same engine as Chrome, test for Microsoft-specific quirks |

### 3.2 Mobile Browsers

| Browser | OS | Min Version | Priority | Notes |
|---------|-----|-------------|----------|-------|
| Safari | iOS 17+ | P0 | Touch targets, viewport handling, 100vh issue, safe-area-inset |
| Chrome | Android 13+ | P1 | Touch scroll, chart interaction, soft keyboard |

### 3.3 Explicitly Out of Scope

- Internet Explorer (EOL)
- Opera Mini (no JS)
- Samsung Internet (follows Chromium closely, low user share)
- Firefox Mobile (< 1% of expected user base)

---

## 4. Device Breakpoints

| Breakpoint | Width | Represents | Tailwind Prefix |
|------------|-------|-----------|-----------------|
| Mobile S | 375px | iPhone SE / iPhone 13 mini | (default) |
| Mobile L | 428px | iPhone 14 Pro Max / Pixel 7 | (default) |
| Tablet | 768px | iPad Mini / iPad (portrait) | `md:` |
| Tablet landscape | 1024px | iPad Pro (portrait) / iPad (landscape) | `lg:` |
| Desktop | 1280px | Standard laptop / 13" MacBook | `xl:` |
| Desktop L | 1920px | External monitor / iMac | `2xl:` |

---

## 5. Test Scenarios Per Page

### 5.1 Landing Page / Authentication (LandingApp)

| # | Scenario | What to Verify |
|---|----------|---------------|
| L1 | Google OAuth button renders | Button visible, clickable, correct styling in both themes |
| L2 | Error message display | Auth failure message appears with correct contrast |
| L3 | Responsive layout | Hero section, CTA buttons stack vertically on mobile |
| L4 | Dark/light theme | Both themes render without broken contrast |

### 5.2 Onboarding Wizard (OnboardingWizard)

| # | Scenario | What to Verify |
|---|----------|---------------|
| O1 | Welcome step | Heading visible, progress indicator, "Skip for now" button |
| O2 | CSV import step | File picker opens, drag-drop zone visible (file input, not native DnD) |
| O3 | Processing step | Loading animation plays, progress bar fills |
| O4 | Completion step | Success state, "Go to Dashboard" button |
| O5 | Normalizer builder | Column mapping dropdowns work, preview table scrolls |
| O6 | Mobile layout | All steps usable at 375px, buttons have adequate touch targets (48px) |

### 5.3 Dashboard / Overview (score view)

| # | Scenario | What to Verify |
|---|----------|---------------|
| D1 | Portfolio overview card | Metric cards render, numbers formatted, gradient backgrounds visible |
| D2 | Holdings summary card | Top positions table renders, scroll if overflow |
| D3 | Alerts panel | Alert cards visible, dismiss/mark-read buttons work |
| D4 | Performance strip | Sparkline chart renders, period badges visible |
| D5 | Asset allocation | Pie/donut chart renders correctly in SVG |
| D6 | Income card | Bar chart renders, tooltip on hover/tap |
| D7 | Grid layout | `xl:grid-cols-2` at 1280px+, single column below |
| D8 | Portfolio selector | Dropdown opens, portfolio switch triggers data reload |
| D9 | Dark mode | All cards, charts, glass effects render correctly |

### 5.4 Holdings View

| # | Scenario | What to Verify |
|---|----------|---------------|
| H1 | Holdings table | All columns visible, horizontal scroll on narrow screens |
| H2 | Table sorting | Click column header sorts ascending/descending |
| H3 | Table search/filter | Filter input works, results update |
| H4 | Holdings summary cards | Metric cards at top render with correct values |
| H5 | Mobile table | Table scrolls horizontally, first column sticky (if implemented) |

### 5.5 Performance View

| # | Scenario | What to Verify |
|---|----------|---------------|
| P1 | Performance header card | Key metrics (TWR, Sharpe, alpha) display correctly |
| P2 | Performance line chart | Recharts line renders, tooltips appear on hover/tap |
| P3 | Benchmarks tab | Benchmark comparison chart renders, legend visible |
| P4 | Attribution tab | Attribution bar chart renders |
| P5 | Period analysis tab | Period selector works, chart updates |
| P6 | Trading P&L card | Realized/unrealized P&L displays |
| P7 | Risk analysis tab | Drawdown chart, rolling risk charts render |
| P8 | Income projection card | Projection chart renders |
| P9 | Chart responsiveness | Charts resize correctly on window resize, no overflow |

### 5.6 Factors View

| # | Scenario | What to Verify |
|---|----------|---------------|
| F1 | Factor exposure model | Factor bars/chart render |
| F2 | Risk contribution | Pareto chart renders, sorted correctly |
| F3 | Radar chart | SVG radar renders correctly across browsers |
| F4 | Variance chart | Bar chart renders |

### 5.7 Scenarios View (ScenariosRouter)

| # | Scenario | What to Verify |
|---|----------|---------------|
| S1 | Scenarios landing | Tool cards visible, navigation works |
| S2 | What-if tool | Input sliders/fields work, results update |
| S3 | Stress test tool | Scenario selector works, results table renders |
| S4 | Monte Carlo tool | Simulation chart renders (fan chart), controls work |
| S5 | Optimize tool | Optimization runs, results table renders |
| S6 | Backtest tool | Historical chart renders, date range picker works |
| S7 | Efficient frontier tab | Scatter chart renders, hover reveals point details |
| S8 | Portfolio builder tab | Weight sliders work, allocation chart updates |

### 5.8 Research / Stock Lookup

| # | Scenario | What to Verify |
|---|----------|---------------|
| R1 | Search input | Autocomplete/search works, keyboard navigation |
| R2 | Price chart tab | Recharts line chart renders, period selector works |
| R3 | Overview tab | Stock fundamentals render in card layout |
| R4 | Mobile layout | Cards stack vertically, chart resizes |

### 5.9 AI Chat

| # | Scenario | What to Verify |
|---|----------|---------------|
| C1 | Chat interface loads | Input field, send button visible |
| C2 | SSE streaming | Messages stream in real-time, no buffer stalls |
| C3 | Markdown rendering | Bold, lists, code blocks, tables render correctly |
| C4 | KaTeX math | Math expressions render (if used in response) |
| C5 | UI blocks | `:::ui-blocks` render as React components |
| C6 | Artifact panel | Side panel opens (480px slide-out), Escape closes |
| C7 | Chat modal (paid) | Modal overlay opens, interaction works |
| C8 | Tool approval dialog | Approval buttons render, click triggers action |
| C9 | Mobile chat | Input stays above soft keyboard, messages scroll |

### 5.10 Settings

| # | Scenario | What to Verify |
|---|----------|---------------|
| T1 | Risk settings | Form controls (sliders, toggles, selects) work |
| T2 | Preferences card | Theme toggle, visual style toggle work |
| T3 | Account connections | Plaid link button works, connection cards render |
| T4 | CSV import card | File upload, preview table, import button |
| T5 | Mobile settings | All sections stack vertically, controls usable |

### 5.11 Global UI

| # | Scenario | What to Verify |
|---|----------|---------------|
| G1 | Sidebar navigation | All nav items clickable, active state visible |
| G2 | Top NavBar | Navigation works, icons-only below xl, labels at xl+ |
| G3 | Layout toggle | Sidebar/navbar layout switch works |
| G4 | Command palette | Cmd+K opens, search works, keyboard navigation |
| G5 | Notification center | Bell icon, notification list, dismiss actions |
| G6 | Ask AI FAB button | Fixed position correct, click opens chat |
| G7 | Keyboard shortcuts | Cmd+1-8, Cmd+K, Cmd+J all fire correctly |
| G8 | Online/offline | Offline banner appears, recovers on reconnect |
| G9 | Dark/light toggle | All views switch cleanly, no flash of wrong theme |
| G10 | Premium/classic toggle | Glass effects enable/disable, no layout shift |

---

## 6. Critical Interactions

### 6.1 Chart Interactions (Recharts SVG)

| Interaction | Desktop | Mobile | Risk |
|-------------|---------|--------|------|
| Tooltip on hover | Mouse hover shows tooltip | Touch-and-hold or tap | Recharts uses `onMouseMove` -- need to verify touch fallback |
| Chart zoom/pan | Not currently implemented | N/A | If added, verify pinch-to-zoom on mobile |
| Legend click to toggle series | Click toggles dataset visibility | Tap | Touch target size |
| Responsive resize | `ResponsiveContainer` adjusts | Same | Verify no overflow or aspect ratio break |

### 6.2 Table Interactions

| Interaction | Desktop | Mobile | Risk |
|-------------|---------|--------|------|
| Column sort | Click header | Tap header | Touch target may be too small |
| Horizontal scroll | Scroll wheel / trackpad | Swipe | No sticky column implemented |
| Row selection | Click row | Tap row | Hover state not applicable on mobile |
| Search/filter | Type in input | On-screen keyboard | Layout shift from keyboard appearing |

### 6.3 Modal Dialogs (Radix)

| Interaction | Desktop | Mobile | Risk |
|-------------|---------|--------|------|
| Open/close | Click trigger / Escape / click overlay | Tap trigger / tap overlay | Radix handles this well |
| Scroll within modal | Mouse wheel | Touch scroll | Body scroll lock needed on iOS |
| Focus trap | Tab cycles within modal | N/A (no hardware keyboard) | Verify Radix focus trap works in all browsers |
| Nested dialogs | Alert within dialog | Same | Z-index stacking |

### 6.4 SSE Streaming (AI Chat)

| Aspect | Risk | Browsers Affected |
|--------|------|-------------------|
| ReadableStream for fetch-based SSE | Older Safari may lack full Streams API | Safari < 17 |
| EventSource reconnection | Auto-reconnect behavior differs | All |
| Long-lived connections | Mobile browsers may kill background connections | iOS Safari, Android Chrome |
| Chunked text rendering | UI must handle partial markdown during stream | All |

### 6.5 File Upload (CSV Import)

| Interaction | Desktop | Mobile | Risk |
|-------------|---------|--------|------|
| File picker | Native dialog | Camera/Files app dialog | iOS shows action sheet |
| Drag-and-drop | Drop zone accepts file | Not applicable on mobile | Must have click-to-browse fallback |
| Large file | Reads file in browser | Same | Memory limits more constrained on mobile |

---

## 7. Accessibility Checklist

### 7.1 Keyboard Navigation

| Area | Requirement | Current State |
|------|-------------|---------------|
| Tab order | Logical flow through interactive elements | Radix components handle this; custom components need audit |
| Focus indicators | Visible `focus-visible` ring on all interactive elements | Global `*:focus-visible` rule exists (blue outline, 2px offset) |
| Skip links | Skip to main content link | Not implemented -- **gap** |
| Escape key | Closes modals, popovers, command palette | Radix handles for its components; verify custom overlays |
| Arrow keys | Navigate within menus, tabs, radio groups | Radix primitives support this natively |
| Enter/Space | Activate buttons and links | Standard behavior; verify custom `<div onClick>` patterns |

### 7.2 Screen Reader

| Area | Requirement | Current State |
|------|-------------|---------------|
| Page landmarks | `<main>`, `<nav>`, `<aside>` used correctly | Sidebar uses `<aside>`, nav uses `<nav>` -- verify `<main>` |
| Heading hierarchy | Single `<h1>`, logical `<h2>`-`<h6>` nesting | Inconsistent -- "PortfolioRisk Pro" is `<h1>`, view titles vary |
| ARIA labels | All icon-only buttons have `aria-label` | Sidebar buttons have `aria-label`; verify all icon-only buttons |
| Live regions | Dynamic content updates announced | Chart updates, notification counts need `aria-live` |
| Chart alternatives | SVG charts need `role="img"` + `aria-label` or description | Not implemented -- **gap** |
| Form labels | All inputs have associated labels | Radix `<Label>` used in some places; verify all forms |

### 7.3 Color Contrast

| Area | Requirement | Current State |
|------|-------------|---------------|
| Text on background | 4.5:1 minimum (WCAG AA) | Design system uses semantic colors; needs audit per theme |
| Large text | 3:1 minimum | Headers use foreground on background; likely compliant |
| Interactive elements | 3:1 against adjacent colors | Emerald on white may be borderline; check |
| Chart colors | Distinguishable without color alone | 5 chart colors defined; verify pattern/shape alternatives |
| Dark mode | Same ratios in dark theme | Dark theme was audited in Phase 5; verify edge cases |

### 7.4 Touch Targets

| Area | Requirement | Current State |
|------|-------------|---------------|
| Buttons | 44x44px minimum (WCAG) or 48x48px (Material) | Sidebar buttons: `h-11 w-11` (44px) -- meets minimum |
| Nav items | 44px minimum | NavBar items: `px-2.5 py-2` -- may be below 44px height |
| Table headers | Sortable headers need adequate target | Needs measurement |
| Close buttons | Modal/dialog close buttons | Radix default; verify size |

---

## 8. Known Issues to Verify

### 8.1 From CSS Analysis

| Issue | Description | Affected Browsers |
|-------|-------------|-------------------|
| `mask-composite: xor` | Used in `.morph-border::before`. Firefox needs `-webkit-mask-composite: exclude`. If Autoprefixer does not add this, the animated border will not render on Firefox. | Firefox |
| `text-wrap: balance` | Used in `.text-balance-optimal`. Not supported in Firefox < 121, Safari < 17.4. Text will still display but without balanced line breaking. | Older Firefox/Safari |
| `backdrop-filter` | Used in glass-premium, glass-tinted, nav backdrop. Autoprefixer should add `-webkit-backdrop-filter` for Safari. Verify. | Safari |
| `-webkit-text-fill-color: transparent` | Used for gradient text effect. Non-WebKit browsers ignore this but may show text with gradient background visible. Needs fallback or gating. | Firefox |
| `scrollbar-color` vs `::-webkit-scrollbar` | Two separate scrollbar APIs used in parallel. Firefox uses `scrollbar-color`, WebKit uses pseudo-elements. Both are present, so cross-browser should work. Verify visual consistency. | All |
| Mobile hover effects | `@media (max-width: 768px)` disables hover transforms, but `box-shadow: none` may remove wanted static shadows. | Mobile browsers |

### 8.2 Vite Build Target

**Issue**: No explicit `build.target` in `vite.config.ts`. Vite 7 defaults to `esnext`, which means the production build may emit syntax that older browsers cannot parse (e.g., top-level await, using declarations).

**Action needed**: Set `build.target` to a reasonable floor:
```ts
build: {
  target: ['es2020', 'chrome120', 'firefox120', 'safari17', 'edge120'],
}
```

### 8.3 Browserslist

**Issue**: The active workspace `package.json` has no `browserslist` key. Autoprefixer relies on browserslist to decide which prefixes to emit. Without it, Autoprefixer uses its defaults (which may be acceptable but should be explicit).

**Action needed**: Add browserslist to `frontend/package.json`:
```json
"browserslist": [
  "last 2 Chrome versions",
  "last 2 Firefox versions",
  "last 2 Safari versions",
  "last 2 Edge versions",
  "iOS >= 17",
  "Android >= 120"
]
```

### 8.4 iOS Safari Specific

| Issue | Description |
|-------|-------------|
| `100vh` bug | iOS Safari's `100vh` includes the URL bar. Use `100dvh` or JS fallback. Check if any full-height views are affected. |
| Safe area insets | Notch / home indicator area. Check if `env(safe-area-inset-*)` is needed for fixed elements (Ask AI FAB, chat input). |
| Overscroll bounce | iOS rubber-band scroll may interfere with modal scroll lock. Vaul drawer uses this intentionally. |
| Software keyboard | Input focus may push content up. Chat input must remain visible. |
| Long-press context menu | Touch-and-hold triggers native context menu, may interfere with chart tooltip. |

### 8.5 No Mobile Navigation

**Issue**: The sidebar is fixed at `w-16` (64px) with no collapse or hamburger menu. On mobile widths (375px), this consumes 17% of screen width for icons only. The NavBar hides labels below `xl:` but stays visible.

**Action needed**: This is a UX gap, not a bug. Document for future work: bottom tab bar or hamburger menu for mobile.

---

## 9. Tooling Recommendation

### 9.1 Approach: Playwright Multi-Browser (Primary) + Manual Mobile (Supplementary)

**Rationale**: The project already has Playwright infrastructure (`e2e/playwright.config.ts`, 5 existing specs, auth mocking, API mocks). Extending the existing config to run against multiple browser engines is the lowest-friction path. Real device mobile testing is needed for iOS Safari quirks but can be done manually.

### 9.2 Playwright Config Changes

Extend `e2e/playwright.config.ts` to add browser projects:

```ts
projects: [
  {
    name: 'chromium',
    use: { ...devices['Desktop Chrome'] },
  },
  {
    name: 'firefox',
    use: { ...devices['Desktop Firefox'] },
  },
  {
    name: 'webkit',
    use: { ...devices['Desktop Safari'] },
  },
  // Mobile viewports (emulation, not real devices)
  {
    name: 'mobile-chrome',
    use: { ...devices['Pixel 7'] },
  },
  {
    name: 'mobile-safari',
    use: { ...devices['iPhone 14'] },
  },
  // Tablet
  {
    name: 'tablet',
    use: { ...devices['iPad (gen 7)'] },
  },
],
```

### 9.3 New Test Files to Create

| File | Coverage |
|------|----------|
| `e2e/tests/cross-browser/navigation.spec.ts` | Sidebar nav, NavBar, view switching, keyboard shortcuts |
| `e2e/tests/cross-browser/dashboard-overview.spec.ts` | Overview cards render, grid layout at breakpoints |
| `e2e/tests/cross-browser/charts.spec.ts` | Recharts SVG rendering, tooltip interaction |
| `e2e/tests/cross-browser/dark-mode.spec.ts` | Theme toggle, glass effects, contrast |
| `e2e/tests/cross-browser/responsive-layout.spec.ts` | Viewport resize, grid collapse, sidebar behavior |
| `e2e/tests/cross-browser/modals-dialogs.spec.ts` | Dialog open/close, focus trap, scroll lock |
| `e2e/tests/cross-browser/settings-forms.spec.ts` | Form controls, file upload, toggles |
| `e2e/tests/cross-browser/chat-streaming.spec.ts` | SSE mock, markdown render, artifact panel |
| `e2e/tests/cross-browser/accessibility.spec.ts` | axe-core audit, focus visible, keyboard nav |

### 9.4 Accessibility Automation

Install `@axe-core/playwright` and run automated accessibility audits:

```ts
import AxeBuilder from '@axe-core/playwright';

test('no accessibility violations on overview', async ({ page }) => {
  await page.goto('/');
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa'])
    .analyze();
  expect(results.violations).toEqual([]);
});
```

### 9.5 Visual Regression (Optional, Phase 2)

Playwright supports screenshot comparison. Can add as a follow-up:

```ts
await expect(page).toHaveScreenshot('overview-desktop-chrome.png', {
  maxDiffPixelRatio: 0.01,
});
```

This generates baseline screenshots per browser and fails on visual drift. Recommended for charts and layout but requires maintained baselines.

### 9.6 BrowserStack / Real Devices

**When to use**: For iOS Safari issues that Playwright WebKit emulation cannot reproduce (viewport bugs, safe-area-inset, software keyboard). Not needed for initial pass -- Playwright WebKit covers most Safari quirks.

**If needed later**: BrowserStack Automate integrates with Playwright via `@browserstack/playwright`.

---

## 10. CI Integration

### 10.1 Current State

No CI pipeline exists for e2e tests. The `test:e2e` script in `package.json` runs locally.

### 10.2 Recommended CI Job

```yaml
# GitHub Actions example
cross-browser-e2e:
  runs-on: ubuntu-latest
  container:
    image: mcr.microsoft.com/playwright:v1.49.0-noble
  strategy:
    matrix:
      project: [chromium, firefox, webkit, mobile-chrome, mobile-safari]
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-node@v4
      with:
        node-version: 22
    - run: cd frontend && npm ci
    - run: cd e2e && npx playwright install --with-deps
    - run: cd frontend && npx playwright test --project=${{ matrix.project }}
    - uses: actions/upload-artifact@v4
      if: failure()
      with:
        name: playwright-report-${{ matrix.project }}
        path: frontend/playwright-report/
```

### 10.3 Parallelism

Matrix strategy runs each browser project in a separate CI job. This keeps wall-clock time ~equal to a single browser run while covering all 5 targets.

---

## 11. Pass/Fail Criteria

### 11.1 Per-Browser Gate

| Criteria | P0 (Chrome, iOS Safari) | P1 (Firefox, Safari, Android) | P2 (Edge) |
|----------|-------------------------|-------------------------------|-----------|
| All pages render without JS errors | MUST PASS | MUST PASS | MUST PASS |
| Charts (SVG) render correctly | MUST PASS | MUST PASS | MUST PASS |
| Navigation works (all views reachable) | MUST PASS | MUST PASS | MUST PASS |
| Dark/light mode works | MUST PASS | MUST PASS | SHOULD PASS |
| Glass effects render | MUST PASS | SHOULD PASS (fallback OK) | SHOULD PASS |
| Animations play | SHOULD PASS | SHOULD PASS | SHOULD PASS |
| Custom scrollbars | NICE TO HAVE | NICE TO HAVE | NICE TO HAVE |
| SSE streaming works | MUST PASS | MUST PASS | MUST PASS |
| All form controls work | MUST PASS | MUST PASS | MUST PASS |
| Accessibility audit (axe, 0 violations) | MUST PASS | MUST PASS | MUST PASS |

### 11.2 Mobile-Specific Gate

| Criteria | Required |
|----------|----------|
| All views render at 375px without horizontal overflow | MUST PASS |
| Touch targets >= 44px on interactive elements | MUST PASS |
| Charts render and show data (tooltip not required) | MUST PASS |
| Modals scrollable, body scroll locked | MUST PASS |
| Chat input visible above keyboard | MUST PASS |
| No layout shift on orientation change | SHOULD PASS |

### 11.3 Blocking vs. Non-Blocking

- **Blocking (launch blocker)**: Any MUST PASS failure on P0 or P1 browsers.
- **Non-blocking (post-launch fix)**: SHOULD PASS / NICE TO HAVE failures, P2 browser issues, cosmetic differences (e.g., scrollbar style).

---

## 12. Execution Plan

### Phase 1: Infrastructure Setup (1 day)

1. Add `build.target` to `vite.config.ts`
2. Add `browserslist` to `frontend/package.json`
3. Extend `e2e/playwright.config.ts` with multi-browser projects
4. Install `@axe-core/playwright`
5. Run existing 5 specs against all browser projects -- fix any immediate failures
6. Verify `mask-composite` / `backdrop-filter` / `text-wrap` CSS rendering in Firefox and Safari

### Phase 2: Automated Cross-Browser Tests (3-4 days)

1. Write `navigation.spec.ts` -- sidebar, NavBar, view switching, Cmd+K
2. Write `dashboard-overview.spec.ts` -- mock data, verify card rendering per viewport
3. Write `charts.spec.ts` -- mock data, verify SVG elements exist, tooltip triggers
4. Write `dark-mode.spec.ts` -- toggle theme, verify no broken contrast
5. Write `responsive-layout.spec.ts` -- resize viewport through breakpoints, verify grid
6. Write `modals-dialogs.spec.ts` -- open/close/focus-trap for command palette, AI chat modal, Radix dialogs
7. Write `settings-forms.spec.ts` -- form controls at each viewport
8. Write `chat-streaming.spec.ts` -- mock SSE, verify markdown rendering
9. Write `accessibility.spec.ts` -- axe-core audit per view

### Phase 3: Manual Mobile Verification (1 day)

Real-device testing for issues Playwright emulation cannot catch:

| Test | Device | Browser | Action |
|------|--------|---------|--------|
| Full navigation flow | iPhone 14 | Safari | Navigate all views, verify no horizontal scroll |
| Chart interaction | iPhone 14 | Safari | Tap charts, verify tooltip or data display |
| Chat with keyboard | iPhone 14 | Safari | Open chat, type message, verify input stays visible |
| File upload | iPhone 14 | Safari | Upload CSV via Files app |
| Full navigation flow | Pixel 7 | Chrome | Navigate all views |
| Orientation change | iPad | Safari | Rotate between portrait/landscape |
| Command palette | iPad + keyboard | Safari | Cmd+K works with hardware keyboard |

### Phase 4: Fix and Verify (2-3 days)

1. Triage all failures from Phases 2-3
2. Fix blocking issues (CSS prefixes, layout breaks, JS errors)
3. Re-run full suite to confirm fixes
4. Document known non-blocking issues with browser-specific workarounds

### Phase 5: CI Integration (0.5 day)

1. Add GitHub Actions workflow for cross-browser e2e
2. Configure artifact upload for failure reports
3. Set as required check on PRs that touch `frontend/`

---

## 13. Estimated Total Effort

| Phase | Effort | Dependencies |
|-------|--------|-------------|
| Phase 1: Infrastructure | 1 day | None |
| Phase 2: Automated tests | 3-4 days | Phase 1 |
| Phase 3: Manual mobile | 1 day | Phase 1 (needs build running) |
| Phase 4: Fix and verify | 2-3 days | Phases 2-3 (depends on issue volume) |
| Phase 5: CI | 0.5 day | Phase 2 |
| **Total** | **7.5-9.5 days** | |

---

## 14. Dependencies and Prerequisites

- **Playwright browsers installed**: `npx playwright install --with-deps` (Chromium, Firefox, WebKit)
- **API mocking extended**: Current `e2e/helpers/api-mocks.ts` covers onboarding. Need mocks for portfolio data (holdings, performance, risk, charts) to test dashboard views.
- **Real iOS device or Mac for Safari**: Playwright WebKit is not true Safari. For Phase 3, need macOS with Safari or a physical iOS device.
- **Test data fixtures**: Create JSON fixtures for `mockPortfolioData()`, `mockPerformanceData()`, `mockRiskData()` to render charts with representative data.

---

## 15. Open Questions

1. **Mobile navigation pattern**: The sidebar does not collapse for mobile. Should this plan include implementing a mobile nav (bottom tabs / hamburger), or only test the current layout?
2. **Visual regression baselines**: Should we commit screenshot baselines for each browser, or rely on functional assertions only?
3. **Real device lab**: Do we have access to BrowserStack or physical devices for Phase 3, or should we scope to Playwright emulation only?
4. **Performance budgets**: Should cross-browser testing include Lighthouse/Web Vitals per browser, or keep scope to functional correctness?
