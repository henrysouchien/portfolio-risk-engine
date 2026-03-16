# Frontend E2E Fixes — Batch 3 (Final Tier 2 + Tier 3)

## Context

Batches 1-2 shipped (`2d1e1551`, `66810bd8`). Another session handles F3/4/5/6. This plan covers the last actionable frontend fixes.

**Skipped (not actionable from frontend):**
- F12: "Accounts: 0" — DEV-only indicator (`import.meta.env.DEV`), not user-facing
- F22: Visual style toggle + benchmark — already built in SettingsPanel.tsx, accessible via overview settings gear button (not on Settings nav page, which is risk limits only)
- F27: Historical positions unlabeled — needs backend `isClosed` field, defer
- F9/F10: GOLD/SLV misclassification — FMP data quality, not frontend
- F11/F26: FIG risk score / factor t-stats — backend investigation needed

---

## Fix 1: F17 — Recovery Time and Tracking Error "--" without explanation

**Problem**: Performance → Risk Analysis shows "--" for Recovery Time and Tracking Error with no tooltip explaining why.

### File: `frontend/packages/ui/src/components/portfolio/performance/RiskAnalysisTab.tsx`

**Change A** — Line 56-59: Add tooltip to Recovery Time
```tsx
// Before
<div className="flex justify-between text-sm">
  <span className="text-red-800">Recovery Time:</span>
  <span className="font-medium">
    {performanceData.drawdownRecoveryDays != null ? `${performanceData.drawdownRecoveryDays} days` : "--"}
  </span>
</div>

// After — wrap label in Tooltip
<div className="flex justify-between text-sm">
  <Tooltip>
    <TooltipTrigger asChild>
      <span className="text-red-800 cursor-help">Recovery Time: <Info className="inline h-3 w-3 text-red-700" /></span>
    </TooltipTrigger>
    <TooltipContent>Days from maximum drawdown to recovery of previous peak value.</TooltipContent>
  </Tooltip>
  <span className="font-medium">
    {performanceData.drawdownRecoveryDays != null ? `${performanceData.drawdownRecoveryDays} days` : "--"}
  </span>
</div>
```

**Change B** — Line 74-76: Add tooltip to Tracking Error
```tsx
// Before
<div className="flex justify-between text-sm">
  <span className="text-neutral-700">Tracking Error:</span>
  <span className="font-medium">{formatOptionalPercent(performanceData.trackingError, 1)}</span>
</div>

// After
<div className="flex justify-between text-sm">
  <Tooltip>
    <TooltipTrigger asChild>
      <span className="text-neutral-700 cursor-help">Tracking Error: <Info className="inline h-3 w-3 text-neutral-400" /></span>
    </TooltipTrigger>
    <TooltipContent>Standard deviation of portfolio returns relative to the benchmark. Not available for all portfolios.</TooltipContent>
  </Tooltip>
  <span className="font-medium">{formatOptionalPercent(performanceData.trackingError, 1)}</span>
</div>
```

Note: `Tooltip`, `TooltipTrigger`, `TooltipContent`, and `Info` are already imported in this file.

---

## Fix 2: F25 — Alerts "View all 7" → "View 2 more"

**Problem**: Shows "View all 7" when 5 of 7 alerts are visible. Should show remaining count.

### File: `frontend/packages/ui/src/components/dashboard/cards/DashboardAlertsPanel.tsx`

**Change** — Line 132: Calculate remaining count
```typescript
// Before
{expanded ? 'Show less' : `View all ${allAlerts.length}`}

// After
{expanded ? 'Show less' : `View ${allAlerts.length - 5} more`}
```

---

## Verification

1. Navigate to Performance → scroll to Risk & Drawdown: Recovery Time and Tracking Error have Info icons with tooltips on hover
2. Navigate to Dashboard: if >5 alerts, button says "View 2 more" (not "View all 7")
3. Run `cd frontend && npx vitest run`

## Files Modified

| File | Fix |
|------|-----|
| `frontend/packages/ui/src/components/portfolio/performance/RiskAnalysisTab.tsx` | F17: Add tooltips to Recovery Time + Tracking Error |
| `frontend/packages/ui/src/components/dashboard/cards/DashboardAlertsPanel.tsx` | F25: "View N more" instead of "View all N" |
