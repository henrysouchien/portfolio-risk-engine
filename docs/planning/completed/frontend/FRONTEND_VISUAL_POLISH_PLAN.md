# Frontend Visual Polish Plan

> **Status**: PARTIAL — Batches 2+4 done, 1/3/5/6 skipped by design decision
> **Commit**: `cd841d9a`

## Context

The dashboard UI is functional and well-structured but reads as generic — flat typography, uniform card treatment, safe color palette, no visual focal point. The design system (Tailwind + CSS custom properties + CVA) is solid infrastructure, but the aesthetic layer needs intentionality. Goal: elevate the visual quality from "SaaS template" to "premium financial tool" through targeted CSS/component changes with minimal structural risk.

## Scope

6 batches proposed, 2 implemented. The rest were evaluated and intentionally skipped — they add complexity for marginal gain, the same kind of visual bloat removed in the AccountConnections simplification (`08c4ed91`).

## Decision Summary

| Batch | What | Decision | Rationale |
|-------|------|----------|-----------|
| 1 | Typography — Plus Jakarta Sans | **SKIP** | Adds external Google Font dependency (network request, FOIT/FOUT risk). Inter is already strong for financial UI. Marginal gain for real cost. |
| 2 | Fix Sharpe badge colors | **DONE** — `cd841d9a` | Real bug: "Poor" showed green. Threshold logic: >=1.0 positive, >=0.5 warning, <0.5 negative. |
| 3 | Hero card for Total Portfolio Value | **SKIP** | Making one card bigger in a uniform grid often looks awkward. Top-to-bottom reading order already provides hierarchy. |
| 4 | tabular-nums on metric values | **DONE** — `cd841d9a` | Functionally useful — prevents layout shift when numbers update. Applied to OverviewMetricCard + MetricCard. |
| 5 | Section differentiation (accent borders) | **SKIP** | Low impact, minor visual change. |
| 6 | Mesh gradient background | **SKIP** | Risks looking gimmicky, likely breaks dark mode, fights the clean flat aesthetic. |

---

## Batch 2: Fix Severity Badge Colors (Bug) `DONE`

**Problem**: Sharpe Ratio shows "Poor" with green/positive styling because `changeType` is hardcoded to `"positive"` regardless of value.

**Fix** in `useOverviewMetrics.ts`:
```ts
changeType: summary
  ? (summary.sharpeRatio >= 1.0 ? "positive"
     : summary.sharpeRatio >= 0.5 ? "warning"
     : "negative")
  : "neutral",
```

Alpha Generation was already correct (line 83 uses `summary.alphaAnnual > 0` conditional).

---

## Batch 4: Number Typography Polish `DONE`

Added `tabular-nums` class to primary value displays:
- `OverviewMetricCard.tsx` (line 93) — dashboard metric cards
- `metric-card.tsx` (line 159) — reusable MetricCard block

No CSS changes needed — Tailwind's `tabular-nums` utility already exists. Several other components (LiveClock, PortfolioHoldings, IncomeProjectionCard, PercentageBadge) already used it.
