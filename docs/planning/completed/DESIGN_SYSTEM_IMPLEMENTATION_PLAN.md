# Design System Implementation Plan

> Created: 2026-04-02
> Status: FINAL QA COMPLETE (FOLLOW-UP CLEANUP REMAINING)
> Visual Target: `docs/design-unified-preview.html`
> Design Spec: `DESIGN.md`
> Consultation: `docs/planning/DESIGN_CONSULTATION_2026-04-02.md`

## Definition of Done

The implementation is complete when the live frontend visually matches `docs/design-unified-preview.html` and the full DESIGN.md spec, including all dynamic and agent-driven capabilities. Specifically:

### Visual Parity with Preview
- [ ] Three-column layout: 180px sidebar, fluid content, 280px chat margin — matching the preview's proportions and spacing
- [ ] Ticker tape at top with live portfolio data, Geist Mono 11px, `--ticker-bg` background
- [ ] Sidebar reads as quiet table of contents: group labels, 2px active indicator, muted items
- [ ] Every view opens with a Dateline + InsightSection: `--surface-raised` background, `--ink` text at 20px Instrument Sans, "Ask the analyst →" top-right in gold
- [ ] MetricStrip below insights: hairline-separated, Geist Mono tabular numbers, colored deltas with period labels
- [ ] Named section breaks (CONCENTRATION, PERFORMANCE, etc.) with Geist Mono 9px uppercase labels
- [ ] Data tables with urgency dots (watch/act/alert), Geist Mono 12.5px, `--text-dim` headers
- [ ] Exit ramps at section bottoms with gold arrows, context-dependent per view
- [ ] Annotation tags (Methodology, What changed, Confidence, Source) below insights, expandable on click
- [ ] Revision marks showing struck-through previous insight + current update when data changed
- [ ] No card quilts, no emerald, no purple, no gradients, no skeleton loading, no decorative animations
- [ ] Dark theme default. Light theme fully functional with correct token overrides (warm cream `--surface-raised`, darkened `--ticker-bg`, 2px gold rail on generated artifacts)

### Typography
- [ ] Instrument Sans loaded and used for all prose, headings, UI text
- [ ] Geist Mono loaded and used for all data, tables, labels, datelines, ticker tape, section breaks
- [ ] Two-register system visually distinct: warm `--ink` at larger sizes = analyst talking, `--text` Geist Mono at smaller sizes = data/evidence
- [ ] `font-variant-numeric: tabular-nums` on every number-rendering element
- [ ] No Inter, no Crimson Text, no system font fallbacks visible

### Color Discipline
- [ ] Gold accent (`--accent` #C8A44E) used ONLY for: "Ask the analyst →", scenario run buttons, active scenario tool in sidebar, exit ramp arrows, generated artifact gold rail. Nothing else.
- [ ] Red/green ONLY for financial direction (gain/loss). Delta color follows financial signal (good/bad), not arithmetic direction.
- [ ] `--ink` for analyst prose. `--text` for data. `--text-muted` for secondary. `--text-dim` for labels/captions.
- [ ] No emerald anywhere. No purple. No gradients. No blue buttons.

### Generated Artifacts (Canvas)
- [ ] Agent can produce generated artifacts that render inline in the main content area — not just in chat or a side panel
- [ ] Generated artifacts have: 1px gold left rail (2px light mode), NO container (sit on `--bg`), claim sentence above, interpretation below, annotation tags, exit ramps
- [ ] Draw sequence animation (~350ms): axes → data series draws L→R → callouts → metadata. Triggered on scroll-into-view. Only on generated artifacts, never on report charts.
- [ ] Report charts (pre-built) visually distinct: `--surface` container, legend box, 6-8 y-axis ticks, area fills. Already present when page loads.
- [ ] Generated artifacts use 3 y-axis ticks at chosen values, direct labels (no legend), max 3 callouts
- [ ] Parametric artifacts support preset pills (question-shaped: "Exit DSU", "Trim to 15%") that update the artifact locally
- [ ] `GEN · HH:MM AM` timestamp on every generated artifact

### Chat Margin + Agent Interaction
- [ ] Chat margin shows annotations-first by default: analyst notes, what-changed summaries, related conversations, "Ask about this →" links
- [ ] Chat input at bottom of margin, subordinate to annotations
- [ ] Agent can produce margin sketches: reduced-density artifacts (248px width, 100-140px height, max 2 series, max 1 annotation) that appear in the chat margin
- [ ] Margin sketches have "Open in briefing →" that promotes the artifact inline into the main content at full size
- [ ] Chat margin collapses to 24-32px icon strip with annotation indicator dots; click to re-expand
- [ ] Agent-generated blocks (`design:insight-section`, `design:metric-strip`, `design:generated-chart`, etc.) render correctly in both chat messages AND the main content area via shared BlockRenderer

### SDK + Rendering
- [ ] BlockRenderer and LayoutRenderer work outside of chat — importable and usable in main content area and chat margin
- [ ] All DESIGN.md component types registered in block registry as `design:*` blocks
- [ ] BriefingRenderer renders `UIRenderableSpec[]` in the main content area with briefing-flow layout (continuous top-to-bottom, not card grid)
- [ ] MarginRenderer renders blocks at margin-sketch quality in the chat column
- [ ] Existing `sdk:*` blocks continue to work in chat (backwards compatible)

### Conversational Loading
- [ ] No skeleton shimmers anywhere in the product
- [ ] Before data: single conversational sentence in `--ink` ("Choose a scenario and the analyst will assess the impact.")
- [ ] During load: status sentence in the same voice ("Assessing portfolio impact under 2022 Rate Shock...")
- [ ] After load: full insight replaces the sentence. Same location, same type treatment.

### Error States
- [ ] Errors displayed in analyst voice, not system errors
- [ ] "Can't reach Schwab right now. Working from yesterday's close." — not raw error codes

---

## Current State (as of 2026-04-02)

### What Works (infrastructure to reuse)
- **Zustand theme store** (`uiStore.ts`) — `.dark` class toggling + localStorage sync
- **CSS variable system** (`index.css`) — HSL semantic tokens in `@layer base`, `.dark` overrides
- **Tailwind config** — maps CSS vars to utility classes (`bg-background`, `text-foreground`, etc.)
- **Block registry** (`block-registry.ts`) — dynamically register component types
- **BlockRenderer + LayoutRenderer** (`components/chat/blocks/`) — recursive spec-to-component rendering
- **SDK components** — ChartPanel, MetricGrid, SourceTable, FlagBanner, Page, Grid, Stack, Split, Tabs
- **Artifact system** — `:::artifact` / `:::ui-blocks` markers parsed from AI responses, rendered via registry
- **ChatContext / useSharedChat()** — unified chat state across modal + fullscreen
- **Lazy loading** — React.lazy + Suspense already in place for views

### What's Wrong (values, not pipes)
- **Fonts:** Inter + Crimson Text instead of Instrument Sans + Geist Mono
- **Accent:** Emerald (#10b981) instead of Gold (#C8A44E)
- **Tokens:** Missing `--ink`, `--text-muted`, `--text-dim`, `--surface-raised`, `--up`, `--down`, `--chart-blue`, etc.
- **Border radius:** 12px base instead of 6px
- **Animations:** 77+ banned decorative animations (breathe, pulse, float)
- **Gradients:** 184 gradient usages across components
- **Skeletons:** 35 files with shimmer loading (banned)
- **InsightBanner:** 6 colored variants instead of single neutral
- **Border radius:** 254 occurrences of rounded-2xl/3xl
- **Default theme:** Light instead of dark
- **SDK scope:** BlockRenderer/LayoutRenderer walled off inside chat — can't render in main content

## Checkpoint Status (2026-04-05)

### Completed In This Checkpoint
- [x] Phase 0A-0D: foundation token swap, Tailwind token mapping update, font swap, dark theme default
- [x] Phase 1A-1E: ticker tape, three-column layout shell, quieter sidebar, chat margin column, continuous content area in `ModernDashboardApp`
- [x] Phase 2 core primitives: `Dateline`, `InsightSection`, `MetricStrip`, `NamedSectionBreak`, `ConversationalLoading`
- [x] Phase 3 revision layer: revision memory and revision marks now render across overview, trading, holdings, performance, risk, stock lookup, scenario landing, and the migrated scenario tools
- [x] Phase 4 foundation: shared block registry, shared `BlockRenderer` / `LayoutRenderer`, initial `design:*` registrations, `BriefingRenderer`, `MarginRenderer`
- [x] Phase 5 artifact foundation: generated chart block, annotation tags, exit ramps, inline margin-sketch promotion into the main briefing column
- [x] Phase 5 route adoption: generated briefing artifacts now appear in overview, risk, optimize, monte carlo, stress test, tax harvest, what-if, hedge, backtest, and rebalance flows
- [x] View migration foundation: overview, scenario tools, holdings, performance, risk, trading, stock lookup, and settings all have briefing-style route shells
- [x] First shared-renderer adoption outside chat: `SettingsView` top fold now renders via `BriefingRenderer`
- [x] Runtime stability pass: trading account selectors stay controlled, stock lookup direct-analysis flow no longer 500s on compat price fetches, and the shared dashboard error boundary now uses briefing-style fallback UI
- [x] Support-surface cleanup pass: `DataBoundary`, notification center, `PerformanceChart`, `HedgeWorkflowDialog`, the Plaid/SnapTrade success pages, and the shared dashboard summary cards now use the neutral briefing language instead of skeleton/gradient/emerald-era treatments
- [x] Extended cleanup sweep: onboarding/auth entry pages, strategy/scenario/performance internals, overview/risk support panels, onboarding connection flows, and setup/provider utilities have been pulled into the same neutral briefing language
- [x] Route and QA hardening: Vite now leaves `/plaid/success` to the SPA in local dev, and Playwright covers analyst entry, Plaid/SnapTrade success routes, onboarding navigation, overview first-paint, margin-artifact promotion, persisted light-theme rendering, and the full-page `/#chat` workspace route
- [x] Shared primitive cleanup: the live source tree no longer uses `premium` / `glass` button-card variants, `scroll-premium`, or `data-visual-style`, and the dead `visualStyle` setting has been removed from the active app surface
- [x] Overview/trading parity hardening: overview now renders immediately while enrichment catches up, trading no longer loops on mutation-object resets, and authenticated Playwright smokes cover both routes end-to-end
- [x] Annotation-depth pass: risk, scenario landing, and every migrated scenario tool now expose expandable `label` / `value` / `details` metadata instead of thin label-only chips
- [x] Live route parity QA: Chromium smokes now pass for overview, trading, and chat, while authenticated parity captures pass for overview, trading, and risk after the latest briefing and generated-artifact refinements
- [x] Full-page conversation polish: the dedicated `Conversation` route now uses the same quieter briefing shell language as the rest of the app instead of the old bordered assistant card
- [x] Residual live-surface cleanup: the remaining route-level hover/fade/stagger chrome has been removed from the active conversation, holdings, trading, research, risk, scenario, onboarding, and lower-overview surfaces, leaving only legacy/reference components with those older patterns
- [x] Overview shell parity pass: shell proportions, ticker spacing, dateline/insight/metric-strip sizing, and the concentration artifact now sit closer to `design-unified-preview.html` under same-width capture review
- [x] Trading state polish: account-loading notices inside Quick Trade and Orders now render as compact briefing notes, and the standalone trading smoke establishes a dev session before asserting the workspace route
- [x] First-fold metric fallback pass: the overview strip now derives live return, volatility, drawdown, Sharpe, alpha, and beta from the richer performance adapter when the summary payload is sparse, and it falls back to lead position weight instead of showing a misleading zero diversification score
- [x] Parity-capture coverage now includes the full-page `/#chat` conversation route alongside overview, trading, and risk
- [x] Lower-overview + conversation parity pass: `Tax Opportunities` now uses live unrealized-loss dollars with shorter estimated-benefit framing, and the full-page `/#chat` route now uses the same integrated dateline/selector header grammar as the other briefing surfaces
- [x] Final richer-data parity sweep: authenticated capture review now covers overview, lower overview, trading, risk, and full-page conversation, and the sweep closed the live-data `Market Context` formatting bug that was still printing raw `nan` values into overview
- [x] Scenario route QA hardening: direct rebalance, optimize, tax-harvest, and recent-run comparison flows now use explicit current headings/labels and pass the refreshed Playwright harness
- [x] Route ending consistency pass: trading, stock lookup, scenarios, holdings, performance, risk, overview, and conversation now end with intentional breathing room or follow-up tails instead of abrupt clipping

### Partially Complete
- Phase 3: revision marks and expandable annotation tags are broadly wired across the shipped briefing surfaces; the remaining work is secondary wording polish on methodology/source copy rather than missing mechanics.
- Phase 4: shared renderers are extractable and live on the main route set, chat, artifacts, and the margin path; the remaining work is optional broader adoption on secondary/legacy surfaces and any future margin-sketch refinement.
- Phase 5: generated-artifact plumbing, inline promotion, local preset pills, timestamps, and draw sequencing are in place; the remaining work is secondary sparse-data copy/value polish rather than missing rendering capabilities.
- Phase 6: route migration and richer-data parity review are complete on overview, trading, risk, and full-page conversation; the remaining work is limited to secondary interaction/data-edge cleanup, not shell parity.

### Still Outstanding
- Secondary sparse-data data-quality/content cleanup under live feeds, especially lingering `N/A`/empty metric wording, market-event field normalization beyond the current `nan` sanitization, and occasional single-name artifact copy tuning
- Secondary annotation-tag wording and generated-artifact micro-polish under richer live data, especially methodology/source phrasing, right-margin fidelity, and remaining lower-overview artifact density
- Optional cleanup and code-health pass on legacy/reference surfaces such as `risk-analysis-dashboard.tsx` and the older overview component stack that is no longer on the main live route

### Next Recommended Sequence
1. Keep the shipped UI stable and track only secondary sparse-data/content issues that show up in real usage.
2. If shared legacy/reference surfaces are touched again, do a narrow cleanup pass there and rerun the existing route/browser QA that covers overview, trading, risk, chat, scenarios, and artifact promotion.
3. If a formal closeout artifact is needed, backfill the Definition of Done checklist line-by-line from the now-shipped route set instead of using this implementation plan as a live work queue.

---

## Phase 0: Foundation (Tokens + Fonts + Cleanup)

**Goal:** Swap design system values so every existing component immediately looks closer to the target. No component rewrites — just change what the tokens resolve to.

**Why first:** Everything else references tokens. If tokens aren't right, every component built on top uses wrong colors.

### 0A. CSS Token Swap
**File:** `frontend/packages/ui/src/index.css`

Replace `:root` and `.dark` CSS variable values with DESIGN.md hex values (converted to HSL where the system expects HSL). Add missing tokens:

| New Token | Hex (dark / light) | Purpose |
|-----------|---------------------|---------|
| `--ink` | #F2F0EC / #1C1917 | Analyst voice color |
| `--text-muted` | #6B6F76 / #6B6F76 | Secondary text |
| `--text-dim` | #484C54 / #838790 | Labels, captions |
| `--surface-raised` | #21252D / #FDFCF9 | Insight sections |
| `--surface-2` | #22262E / #F0F0EE | Hover states |
| `--accent` | #C8A44E / #9E7E2E | Gold (was emerald) |
| `--accent-dim` | rgba(200,164,78,0.12) | Accent backgrounds |
| `--up` | #34A853 / #1B7F37 | Gains |
| `--down` | #EA4335 / #C5221F | Losses |
| `--up-bg` / `--down-bg` | rgba fills | Positive/negative backgrounds |
| `--chart-blue` | #5F8BB0 / #4A7A9E | Primary chart series |
| `--chart-series-2..5` | Terra cotta, sage, muted gold, steel blue | Additional series |
| `--revision-old` | #50545C / #A8A8A4 | Struck-through text |
| `--ticker-bg` | #0C0E12 / #E8E8E0 | Ticker tape background |

Map existing token names (`--background`, `--foreground`, `--primary`, `--border`) to DESIGN.md values so existing components get new colors without JSX changes.

### 0B. Tailwind Config Update
**File:** `frontend/tailwind.config.js`

- Add new color utilities: `ink`, `text-muted`, `text-dim`, `surface-raised`, `surface-2`, `accent-dim`, `up`, `down`, `chart-blue`, etc.
- Fix border-radius: `--radius` from 0.75rem (12px) to 0.375rem (6px). Makes `rounded-lg` = 6px, `rounded-md` = 4px, `rounded-sm` = 2px.
- Remove banned animation keyframes: `breathe`, `pulse-gentle`, `float-gentle`, `stagger-fade-in`
- Keep: `accordion-down/up`

### 0C. Font Swap
**File:** `frontend/packages/ui/src/index.css` (line ~114)

Replace `Inter + Crimson Text` import with:
```
https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap
```

Update body font-family to `'Instrument Sans'`. Update monospace to `'Geist Mono'`.

### 0D. Default Theme
**File:** `frontend/packages/connectors/src/stores/uiStore.ts`

Change default theme from `'light'` to `'dark'`.

### 0E. Global Cleanup
- Add `font-variant-numeric: tabular-nums` global rule for numeric elements
- Remove banned animation class usages (77+ occurrences)
- Global `rounded-2xl` → `rounded-lg` and `rounded-3xl` → `rounded-lg` (254+ occurrences)

### Verification
- Product loads with Instrument Sans + Geist Mono
- Dark theme is default
- Gold accent instead of emerald
- Border radius tighter across all cards
- No breathing/floating/pulsing animations
- Tabular-aligned numbers in data tables

---

## Phase 1: Layout Shell

**Goal:** Restructure the app to the four-layer DESIGN.md layout: ticker tape, sidebar, briefing content, chat margin.

### 1A. Ticker Tape
**New component:** `TickerTape.tsx`

Persistent full-width bar at top. Geist Mono 11px, `--ticker-bg`. Shows: portfolio daily change, benchmark, watch count, tax harvest candidates, next event. Data from existing portfolio summary hooks.

### 1B. App Layout Restructure
**File:** `ModernDashboardApp.tsx`

CSS grid: `grid-template-columns: 180px 1fr 280px; grid-template-rows: auto 1fr;`
- Row 1: Ticker tape (full width)
- Row 2: Sidebar | Content | Chat Margin

Chat margin replaces floating AIChat modal as default interaction surface.

### 1C. Sidebar Quieting
- Background: `--bg`, group labels: Geist Mono 9px uppercase `--text-dim`
- Items: 13px `--text-muted`, active: 2px left `--text` indicator, icon opacity 1.0
- No gold on nav

### 1D. Chat Margin Column
**New component:** `ChatMargin.tsx`

280px right column. Annotations-first: context label, analyst notes, "Ask about this →", margin sketches (Phase 5), chat input at bottom. Collapse toggle → 24-32px icon strip. Collapsed by default below 1280px.

### 1E. Content Area
- `overflow-y: auto`, padding 24px 32px
- Continuous top-to-bottom reading flow, no card-grid layout

### Verification
- Three-column layout at desktop, ticker tape at top, margin collapses on narrow screens

---

## Phase 2: Core Report Components

**Goal:** Build the DESIGN.md component vocabulary — the building blocks every view uses.

### New Components

| Component | Purpose | Key Specs |
|-----------|---------|-----------|
| `Dateline` | Dispatch timestamp | Geist Mono 11px, uppercase, letter-spacing 0.12em, `--text-dim` |
| `InsightSection` | Analyst's opening statement | `--surface-raised`, `--ink` 20px Instrument Sans, "Ask the analyst →" |
| `MetricStrip` | Horizontal metrics | Hairline-separated, labels 9px `--text-dim`, values 13px Geist Mono |
| `NamedSectionBreak` | Labeled dividers | Geist Mono 9px uppercase + `--border-subtle` rule |
| `ExitRamps` | Next-action links | `--text` with gold arrow |
| `UrgencyDot` | Watch/Act/Alert | 6px dot, gray/gold/red |
| `ConversationalLoading` | Loading states | `--ink` sentence replacing skeletons |

### Restyle Existing
- `InsightBanner` → kill 6 color variants, single `--surface-raised` + `--ink`
- `MetricCard` → kill gradient icons, restyle to dense metric
- `DataTable` → urgency dots, Geist Mono 9px uppercase headers

### Block Registry
Register as `design:dateline`, `design:insight-section`, `design:metric-strip`, `design:section-break`, `design:exit-ramps`

---

## Phase 3: Annotation Layer

**Goal:** Transparency and memory features that make the analyst credible.

- **AnnotationTags** — expandable metadata badges (Methodology, What changed, Confidence, Source). Geist Mono 10px, `--text-muted`, 3px radius. Show 2-3 per insight.
- **RevisionMarks** — struck-through previous in `--revision-old` + current in `--ink`. localStorage per view initially.
- **Ask the Analyst** — wire "Ask the analyst →" to open chat margin with context via `useSharedChat()`.

---

## Phase 4: SDK + Renderer Generalization

**Goal:** Decouple block rendering from chat so it works anywhere.

### 4A. Extract Renderers
Move `BlockRenderer` + `LayoutRenderer` from `components/chat/blocks/` to shared `sdk/rendering/`. No logic changes.

### 4B. BriefingRenderer
**New:** Takes `UIRenderableSpec[]`, renders in main content with briefing-flow CSS (continuous, no chat bubbles).

### 4C. Register DESIGN.md Block Types
Add `design:*` types alongside existing `sdk:*`: `design:generated-chart`, `design:insight-section`, `design:metric-strip`, `design:dateline`, `design:section-break`, `design:exit-ramps`, `design:annotation-tags`, `design:revision-marks`

### 4D. MarginRenderer
**New:** Renders blocks at margin-sketch quality (248px width, reduced density).

---

## Phase 5: Canvas (Generated Artifacts)

**Goal:** The analyst drawing charts inline to make a point.

- **GeneratedArtifact** — gold 1px left rail (2px light), no container, composition: claim → chart → interpretation → tags → exit ramps. `GEN · HH:MM AM` stamp.
- **Draw Sequence** — CSS animation: axes → data draws L→R → callouts → metadata. ~350ms. IntersectionObserver trigger.
- **Margin Sketches** — 248px width, 100-140px height, max 2 series, 1 annotation. Anchor label above.
- **Sketch-to-Exhibit Promotion** — "Open in briefing →" expands inline in main content.
- **Parametric Preset Pills** — 3-4 question-shaped pills ("Exit DSU", "Trim to 15%"). Local to artifact.

---

## Phase 6: View-by-View Migration

**Goal:** Apply design system to each dashboard view.

### Migration Order
1. **Overview** — first thing users see, closest to unified preview
2. **Scenario Tools** (Stress Test, What-If, Monte Carlo, Optimize, etc.) — already closest to analyst pattern
3. **Holdings** — concentration review, table-first
4. **Performance** — progress report
5. **Risk** — factor briefing
6. **Trading** — execution quality
7. **Stock Lookup** — research note format

### Per-View Pattern
- Add Dateline at top
- Replace metric cards with InsightSection + MetricStrip
- Replace card grids with continuous-surface briefing flow
- Add named section breaks + exit ramps
- Wire "Ask the analyst →" to chat margin
- Replace skeleton loading with conversational loading

---

## Phase 7: Component Cleanup + Visual Tightening (Follow-up Pass)

**Goal:** Sweep every remaining component and surface to ensure full compliance with DESIGN.md. This is the "no stragglers" pass after the structural work lands.

**Reminder — the Definition of Done (top of this doc) is the target.** Every checkbox must pass. This phase catches anything Phases 0-6 missed.

### 7A. UI Primitives
Audit and restyle all shared primitives in `components/ui/` and `components/blocks/`:
- `button.tsx` — no emerald, no gradients. Primary action in `--accent` (gold) for analyst-direct-address buttons only, secondary in `--surface-2`
- `card.tsx` — max `rounded-md` (6px), no glass, no shadows, no backdrop-blur. `--surface` bg + `--border` outline only
- `skeleton.tsx` — should be removed or replaced with `ConversationalLoading` everywhere it's used
- `metric-card.tsx` — no gradient icons, no colored circles. Dense monospace values.
- `insight-banner.tsx` — verify all 6 color variants are truly neutralized (all resolve to `--surface-raised` + `--ink`)
- `data-table.tsx` — Geist Mono 9px uppercase headers in `--text-dim`, urgency dots, `tabular-nums`

### 7B. Gradient & Color Sweep
Find and eliminate all remaining:
- `bg-gradient-*`, `from-*`, `to-*` classes used decoratively (184 occurrences identified in audit)
- Emerald, purple, indigo, blue color classes used for decoration (not financial signal)
- Any colored icon circles or badge backgrounds that aren't urgency dots

### 7C. Animation Sweep
Verify zero remaining usages of:
- `animate-breathe`, `animate-pulse-gentle`, `animate-float-gentle`, `animate-stagger-fade-in`
- `hover-lift-premium`, `hover-glow-premium`, `magnetic-hover`
- Any entrance animations (fade-in, slide-up) except the Canvas draw sequence

### 7D. Border Radius Sweep
Verify zero remaining `rounded-2xl` or `rounded-3xl` outside of pills (`rounded-full` is OK for pills/badges).

### 7E. Skeleton → Conversational Loading Migration
Every file that imports or uses `Skeleton` component or `skeleton-premium` class → replace with `ConversationalLoading` or remove. 35 files identified in audit.

### 7F. Typography Audit
- Verify Instrument Sans renders on all prose (no system font fallback visible)
- Verify Geist Mono renders on all data/labels/datelines
- Verify `--ink` used for analyst voice, `--text` for data, `--text-muted` for secondary, `--text-dim` for labels
- Verify `font-variant-numeric: tabular-nums` on all number-rendering elements
- Spot-check: no Inter, no Crimson Text anywhere

### 7G. Light Theme Verification
Switch to light theme and verify:
- `--surface-raised` is warm cream (#FDFCF9), not pure white
- `--ticker-bg` is visible (#E8E8E0), not blending with page
- Gold rail on generated artifacts is 2px + brighter #C8A44E
- All text has sufficient contrast
- No elements that only work in dark mode

### Verification
Run through every checkbox in the Definition of Done at the top of this doc. Any unchecked item is a bug to fix in this phase.

---

## Key Files

| File | Phase | Change |
|------|-------|--------|
| `packages/ui/src/index.css` | 0 | Token values, fonts, banned animations |
| `tailwind.config.js` | 0 | Colors, radius, animation cleanup |
| `packages/connectors/src/stores/uiStore.ts` | 0 | Default theme → dark |
| `components/apps/ModernDashboardApp.tsx` | 1 | 3-column grid layout |
| `components/chat/blocks/block-renderer.tsx` | 4 | Move to shared location |
| `components/chat/blocks/layout-renderer.tsx` | 4 | Move to shared location |
| `components/chat/blocks/register-sdk-blocks.ts` | 4 | Add design:* block types |
| `components/blocks/insight-banner.tsx` | 2 | Kill color variants |

## Existing Infrastructure to Reuse

- **Zustand theme store** (`uiStore.ts`) — just change default
- **CSS variable system** (`index.css`) — swap values, keep architecture
- **Tailwind config mapping** — add new utilities, keep pattern
- **Block registry** (`block-registry.ts`) — register design:* alongside sdk:*
- **BlockRenderer + LayoutRenderer** — generalize, don't rewrite
- **ChatContext / useSharedChat()** — wire "Ask the analyst →" links
- **SDK components** (ChartPanel, MetricGrid, SourceTable, FlagBanner) — restyle, don't rebuild
- **Lazy loading** (React.lazy + Suspense) — already in place

## Testing Strategy

- **Phase 0:** Visual regression — screenshot before/after. All 308 components render (may look different, shouldn't break).
- **Phase 1-2:** Component test page showing each new component in isolation.
- **Phase 3-5:** Integration — AI chat emits `design:insight-section` block, verify render in main content.
- **Phase 6:** Per-view QA with `/qa` against live dev server.
- **Throughout:** Existing 852 frontend tests pass (behavior, not styling).
