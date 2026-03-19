# Risk Analysis Card Redesign — Plan

**Status**: PLAN v1
**Severity**: Low (visual polish)
**Scope**: `RiskAnalysis.tsx` only — visual-only changes, no data contract or prop changes
**Goal**: Align the Risk Analysis card with the app's established design language so it feels cohesive sitting next to the Factor Risk Model card on the Factors view.

---

## Current Problems

The Risk Analysis card was designed earlier than the rest of the app and uses different patterns:

| Element | Risk Analysis (current) | Rest of app |
|---------|------------------------|-------------|
| Header | `CardTitle` + plain `Shield` icon | `SectionHeader` with colored icon bubble + subtitle |
| Tabs | Light `bg-secondary`/`bg-card` toggle | Dark gradient pills (`from-neutral-900 to-neutral-800`) |
| Content items | Individually bordered sub-cards with heavy padding | Clean rows or compact cards |
| Progress bars | Already severity-mapped (emerald/amber/red) — no change needed | Color matches severity/context |
| Score display | `50/100` inline with name + badge — 3 elements competing | Single prominent metric with supporting context below |
| Information density | Low — lots of whitespace per item | Medium — compact but readable |

## Design Direction

Adopt the same patterns used in Factor Risk Model, Performance Insights, and Holdings:

### 1. Header — use `SectionHeader`

Replace `CardTitle` + plain Shield with:
```tsx
<SectionHeader icon={Shield} title="Risk Analysis" subtitle="Portfolio risk scoring" colorScheme="amber" size="md" />
```

### 2. Tabs — match dark gradient pill style from PerformanceView

Replace the light `bg-secondary`/`bg-card` tab style with the dark gradient style used in PerformanceView (note: FactorRiskModel also uses a lighter tab style — PerformanceView is the better reference):

`TabsList`:
```tsx
className="glass-tinted inline-flex w-full rounded-2xl border border-neutral-200/60 p-1"
```

`TabsTrigger`:
```tsx
className="rounded-xl text-sm font-medium transition-all duration-300
  data-[state=active]:bg-gradient-to-r data-[state=active]:from-neutral-900
  data-[state=active]:to-neutral-800 data-[state=active]:text-white"
```

### 3. Risk Score tab — compact row layout

Replace individually bordered sub-cards with a cleaner row layout. Each risk factor becomes a row (not a card-in-card):

```
[Name]  [Badge]                    [Score]
[Description text]
[Progress bar — color matches severity]
```

- Remove the outer card border per factor — use `divide-y` or spacing instead
- Keep expandable details on click (existing behavior)
- Progress bar color already severity-mapped — keep as-is
- Score right-aligned as a clean number, not inline with the name
- **Preserve click-to-expand behavior**: row click toggles `selectedRisk`, expandable details section stays

### 4. Stress Tests tab — same treatment

Replace bordered sub-cards with clean rows. Preserve:
- Scenario name, probability text, and impact value
- Stress Test Summary callout card (RiskAnalysis.tsx:315) — keep but restyle to match

### 5. Hedging tab — same treatment

Replace bordered sub-cards with clean rows. Preserve:
- Strategy details (cost, protection, duration, efficiency)
- "Implement Strategy" button (RiskAnalysis.tsx:389) — do NOT wrap in a row-level click handler that could intercept
- Hedge workflow dialog trigger (RiskAnalysis.tsx:406) — keep intact

---

## Files to Change

| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/portfolio/RiskAnalysis.tsx` | Visual restructure of Risk Score, Stress Tests, Hedging tabs. Import `SectionHeader` from `../blocks`. Remove unused `CardTitle` import. Possibly remove unused `Target` import if Stress Test Summary callout is restyled. |

## Files NOT Changed

- No data contract changes (props interface stays identical)
- No adapter changes
- No hook changes
- No backend changes
- Factor Risk Model card untouched

---

## Visual Reference

The target aesthetic is a blend of Factor Risk Model (row layout, density, icon bubble header) and PerformanceView (dark gradient tab pills, `glass-tinted` TabsList). Note: FactorRiskModel.tsx currently uses a manual icon bubble + `CardTitle` and lighter tabs — it's not a perfect reference, but its row layout and density are the right target. PerformanceView.tsx has the correct tab styling.

The Risk Analysis card should feel like a sibling to Factor Risk Model — same visual weight, same density, same patterns — just with different data.
