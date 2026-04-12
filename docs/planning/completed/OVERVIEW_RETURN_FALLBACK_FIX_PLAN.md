# Plan: Fix Overview Return 142% Fallback Bug

## Context

The Overview card's "Return" metric displays 142% for "All Accounts" because the fallback chain silently degrades from YTD return to annualized-since-inception return without changing the label.

**Observed behavior**: Return shows `+142.0%` labeled `vs SPY` — user reads this as YTD performance but it is actually the full-period annualized return.

**Data flow**:
```
PortfolioOverviewContainer
  ├─ usePortfolioSummary() → PortfolioSummaryAdapter.transform(riskAnalysis, riskScore, holdings, perfData)
  │     └─ summary.ytdReturn = ytdPeriod.portfolioReturn ?? returns.totalReturn
  │        where ytdPeriod = performanceSummary.periods.YTD  (does NOT exist in PerformanceAdapter output)
  │        and   returns.totalReturn = full-period total return (NOT YTD)
  │
  └─ usePerformance() → PerformanceAdapter.transform()
        └─ performanceSummary.periods = { "1D", "1W", "1M", "1Y" }  — no "YTD" period
        └─ returns.annualizedReturn = full-period annualized return (142%)
```

### Primary Bug: `returns.totalReturn` is mislabeled as `ytdReturn`

The 142% value is **primarily** caused by `PortfolioSummaryAdapter` line 372:

```typescript
derivedYtdReturn = this.toNullableNumber(ytdPeriod.portfolioReturn)
                ?? this.toNullableNumber(returns.totalReturn);
```

Since `ytdPeriod.portfolioReturn` is always null (PerformanceAdapter has no YTD period), the `returns.totalReturn` fallback fires every time. `totalReturn` is the cumulative return over the entire analysis window (potentially years), NOT YTD. This value (e.g. 380%) gets assigned to `summary.ytdReturn` and propagated through the entire UI as if it were a YTD figure.

The secondary bug in `overviewBrief.tsx` (lines 332-336) compounds the issue — if `summary.ytdReturn` were somehow null, it falls further to `performance.oneYearReturn ?? performance.annualizedReturn`, which could yield 142% (the annualized figure). But the **first fallback that fires** is `returns.totalReturn` in the adapter.

**Root cause chain (3 bugs, in order of firing)**:

1. **PortfolioSummaryAdapter (line 372)** [PRIMARY]: `derivedYtdReturn` falls back from `ytdPeriod.portfolioReturn` (always null) to `returns.totalReturn` (full-period cumulative return). This is the value that actually becomes `summary.ytdReturn` everywhere.

2. **overviewBrief.tsx (lines 332-336)** [SECONDARY]: The fallback chain `summary.ytdReturn ?? performance.ytdReturn ?? performance.oneYearReturn ?? performance.annualizedReturn` silently degrades to non-YTD metrics. With bug #1 fixed, this becomes the active fallback path and would still substitute misleading values.

3. **overviewBrief.tsx (lines 337-340)**: The detail label only distinguishes "1Y" vs blank — it never shows "no YTD data", so the user has no indication that the displayed number is not YTD.

**Why PerformanceAdapter has no YTD period**: `transformPerformanceSummary()` (PerformanceAdapter.ts line 801) builds `1D`, `1W`, `1M`, `1Y` from the backend response. Only `RealizedPerformanceAdapter` computes a `YTD` period (line 391) by filtering `monthly_returns` to the current year. The overview data path uses `usePerformance()` which routes through `PerformanceAdapter`, not `RealizedPerformanceAdapter`.

---

## Scope Decision: Core Fix vs Type Cleanup

**Core fix (this plan, Changes 1-2)**: Remove the dangerous fallbacks in PortfolioSummaryAdapter and overviewBrief.tsx. Change 2 includes updating the detail label to `'YTD vs ...'` / `'(no YTD data)'` — this copy change is part of the core fix because removing the fallback chain makes the old label logic (which distinguished "1Y" vs blank) nonsensical. The label must reflect what the metric now actually shows: either confirmed YTD data or nothing.

**Type cleanup (follow-up, Change 3)**: Removing `annualizedReturn`/`oneYearReturn` from `OverviewBriefPerformanceInput` and updating the call site in PortfolioOverviewContainer is a broader interface change. This is explicitly marked as a **follow-up change** to keep the core fix tightly scoped. It can be done in the same PR if desired, but the core fix stands alone.

---

## Change 1: Remove dangerous `totalReturn` fallback in PortfolioSummaryAdapter

**File**: `frontend/packages/connectors/src/adapters/PortfolioSummaryAdapter.ts`
**Lines**: 368-372

The `?? this.toNullableNumber(returns.totalReturn)` fallback assigns full-period total return to a field named `ytdReturn`. This is semantically wrong — `totalReturn` is the cumulative return over the entire analysis period (potentially years), not YTD.

**Current code**:
```typescript
        // YTD return - realized when available, hypothetical fallback
        const returns = this.asRecord(performanceRecord.returns);
        const perfSummaryPeriods = this.asRecord(this.asRecord(performanceSummary).periods);
        const ytdPeriod = this.asRecord(perfSummaryPeriods.YTD);
        derivedYtdReturn = this.toNullableNumber(ytdPeriod.portfolioReturn) ?? this.toNullableNumber(returns.totalReturn);
```

**New code**:
```typescript
        // YTD return — only trust the YTD period bucket (present in RealizedPerformanceAdapter,
        // absent in PerformanceAdapter). Do NOT fall back to returns.totalReturn — that is
        // the full-period cumulative return, not YTD.
        const perfSummaryPeriods = this.asRecord(this.asRecord(performanceSummary).periods);
        const ytdPeriod = this.asRecord(perfSummaryPeriods.YTD);
        derivedYtdReturn = this.toNullableNumber(ytdPeriod.portfolioReturn);
```

Also remove the now-unused `returns` variable (line 369) unless it is referenced elsewhere in the same try-block. Scanning the file: `returns` is only read on line 372 for `returns.totalReturn`, so the `const returns = ...` line can be deleted too.

**Cache key impact**: Line 580 references `returns.totalReturn` in the cache key via `performanceTotalReturn`. Removing this field without replacement means the cache won't invalidate when YTD data becomes available (e.g., when RealizedPerformanceAdapter eventually populates a YTD period).

**Lines**: 560, 580 (in `generateCacheKey`)

**Current code (line 560)**:
```typescript
    const returns = this.asRecord(performanceRecord.returns);
```

**Current code (line 580)**:
```typescript
      performanceTotalReturn: this.toNullableNumber(returns.totalReturn),
```

**New code**: Replace both with a cache key entry that tracks the actual YTD data source:

```typescript
    const cacheKeyPeriods = this.asRecord(this.asRecord(performanceSummary).periods);
    const cacheKeyYtdPeriod = this.asRecord(cacheKeyPeriods.YTD);
```

And on line 580:
```typescript
      performanceYtdReturn: this.toNullableNumber(cacheKeyYtdPeriod.portfolioReturn),
```

This ensures the cache invalidates when `performanceSummary.periods.YTD.portfolioReturn` transitions from null to a real value (e.g., when RealizedPerformanceAdapter output becomes available).

**Update comment on line 465**: From `// ytdReturn: derived from performance.returns.totalReturn` to `// ytdReturn: derived from performance.performanceSummary.periods.YTD.portfolioReturn`

**Summary of PortfolioSummaryAdapter changes**:
- Line 369: delete `const returns = this.asRecord(performanceRecord.returns);`
- Line 372: change to `derivedYtdReturn = this.toNullableNumber(ytdPeriod.portfolioReturn);`
- Line 560: replace `const returns = this.asRecord(performanceRecord.returns);` with YTD period lookup for cache key
- Line 580: replace `performanceTotalReturn: this.toNullableNumber(returns.totalReturn),` with `performanceYtdReturn: this.toNullableNumber(cacheKeyYtdPeriod.portfolioReturn),`
- Update comment on line 465

---

## Change 2: Remove dangerous `oneYearReturn` / `annualizedReturn` fallbacks in overviewBrief

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/overviewBrief.tsx`
**Lines**: 332-340

The `oneYearReturn` and `annualizedReturn` fallbacks silently substitute a different metric under the same "Return" label. If no YTD data is available, the metric should show "—" (null), not a misleading number.

**Current code**:
```typescript
  const resolvedReturn =
    summary.ytdReturn ??
    performance.ytdReturn ??
    performance.oneYearReturn ??     // ← dangerous fallback
    performance.annualizedReturn;    // ← dangerous fallback
  const resolvedReturnDetail =
    resolvedReturn == null || hasSummaryReturn || hasYtdPeriodReturn
      ? `vs ${resolvedBenchmarkTicker}`
      : `1Y vs ${resolvedBenchmarkTicker}`;
```

**New code**:
```typescript
  const resolvedReturn =
    summary.ytdReturn ??
    performance.ytdReturn ??
    null;
  const resolvedReturnDetail =
    resolvedReturn != null
      ? `YTD vs ${resolvedBenchmarkTicker}`
      : '(no YTD data)';
```

Key changes:
- Fallback chain terminates at `performance.ytdReturn ?? null` — no silent substitution.
- Detail label explicitly says `YTD vs SPY` when data is present, and `(no YTD data)` when null.
- The `hasSummaryReturn` / `hasYtdPeriodReturn` boolean guards (lines 324-325) become unused for the detail label. Keep them if used elsewhere in the function; remove if not. Checking... `hasSummaryReturn` is not used anywhere else. `hasYtdPeriodReturn` is not used anywhere else. Delete both (lines 324-325).

**Lines**: 324-325

**Current code**:
```typescript
  const hasSummaryReturn = summary.ytdReturn != null;
  const hasYtdPeriodReturn = performance.ytdReturn != null;
```

**New code**: (delete both lines)

---

## Change 3 (follow-up — separate scope): Remove `oneYearReturn` and `annualizedReturn` from OverviewBriefPerformanceInput

> **Scope note**: This change is a type-level cleanup that removes fields no longer consumed after Change 2. It can be done in the same PR for cleanliness, but the core fix (Changes 1-2) is complete without it. Listed separately so the scope expansion is explicit.

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/overviewBrief.tsx`
**Lines**: 33-46

Since `oneYearReturn` and `annualizedReturn` are no longer consumed by `buildOverviewBrief`, remove them from the interface to prevent future misuse.

**Current code**:
```typescript
export interface OverviewBriefPerformanceInput {
  annualizedReturn: number | null;
  ytdReturn: number | null;
  oneYearReturn: number | null;
  volatility: number | null;
  ytdVolatility: number | null;
  oneYearVolatility: number | null;
  maxDrawdown: number | null;
  beta: number | null;
  sharpeRatio: number | null;
  alpha: number | null;
  benchmarkName: string | null;
  benchmarkSharpe: number | null;
}
```

**New code**:
```typescript
export interface OverviewBriefPerformanceInput {
  ytdReturn: number | null;
  volatility: number | null;
  ytdVolatility: number | null;
  oneYearVolatility: number | null;
  maxDrawdown: number | null;
  beta: number | null;
  sharpeRatio: number | null;
  alpha: number | null;
  benchmarkName: string | null;
  benchmarkSharpe: number | null;
}
```

Note: `oneYearVolatility` is still used in the volatility fallback chain (line 344-346), so keep it.

### Change 3b: Update call site in PortfolioOverviewContainer

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.tsx`
**Lines**: 667-670

Remove the `annualizedReturn` and `oneYearReturn` properties from the performance object passed to `buildOverviewBrief`.

**Current code**:
```typescript
      performance: {
        annualizedReturn: toOptionalNumber(performanceData?.returns?.annualizedReturn),
        ytdReturn: toOptionalNumber(performancePeriods?.YTD?.portfolioReturn),
        oneYearReturn: toOptionalNumber(performancePeriods?.['1Y']?.portfolioReturn),
```

**New code**:
```typescript
      performance: {
        ytdReturn: toOptionalNumber(performancePeriods?.YTD?.portfolioReturn),
```

(Lines 668 and 670 deleted.)

---

## Change 4: Audit and harden `summary.ytdReturn` null sites

After Change 1, `summary.ytdReturn` will be `null` more often (whenever the PerformanceAdapter path is used without RealizedPerformanceAdapter). This impacts multiple prose/insight sites that read `summary.ytdReturn` and inject it into sentences. Each site must handle null gracefully.

### 4a: `overviewBrief.tsx` — `buildLeadInsight()` (6 sites)

`summary.ytdReturn` is read at line 104 as `const ytd = summary.ytdReturn;` and then used in:

- **Line 188-189** (`riskScore < 60` branch): `{renderInsightValue(ytd, 'percent', ytd != null && ytd >= 0 ? 'up' : 'down', { sign: true })} year-to-date performance.`
  - **Null-safe** (renders "—") but **tone is misleading**: when `ytd` is null, the ternary `ytd != null && ytd >= 0 ? 'up' : 'down'` evaluates to `'down'`, giving a negative visual tone to a null/unknown value. **Deferred**: fixing this requires either a `'neutral'` tone branch or omitting the clause when null. Low priority because (a) the "—" placeholder already communicates "no data" to the reader and (b) adding a neutral tone path touches `renderInsightValue` callsite patterns used throughout the file. Can be addressed in a follow-up visual-polish pass.

- **Line 199-200** (`dayMove >= 1.5` branch): `leaving year-to-date return at {renderInsightValue(ytd, ...)} and max drawdown at ...`
  - **Already null-safe**: `renderInsightValue` renders "—" when null. Prose reads "...leaving year-to-date return at — and max drawdown at..." which is legible but not ideal. **Optional improvement**: guard with `ytd != null ? <>leaving year-to-date return at {renderInsightValue(ytd, ...)} and</> : null` to drop the clause entirely. Low priority — this branch requires `dayMove >= 1.5` which is the dominant signal.

- **Line 206** (`ytd != null && ytd >= 0` guard): This branch is only entered when `ytd` is non-null and positive. **Already safe** — null skips this branch.

- **Line 220-221** (default fallback): `Returns are {renderInsightValue(ytd, ...)} year to date with ...`
  - **Null-safe** (renders "—") but **tone is misleading**: same pattern as line 188 — null `ytd` falls to `'down'` tone. Prose reads "Returns are — year to date..." which is acceptable content-wise, but the red/down styling on a null value is semantically wrong. **Deferred** with the line 188 fix above.

### 4b: `overviewBrief.tsx` — `buildLeadInsightRevisionText()` (5 sites)

`summary.ytdReturn` is read at line 233 as `const ytd = summary.ytdReturn;` and used at lines 281, 289, 297-298, 305.

- **Line 281**: `${formatMetricValue(ytd, 'percent', { sign: true })} year-to-date performance.`
  - **Already null-safe**: `formatMetricValue` returns "—" for null.

- **Line 289**: `leaving year-to-date return at ${formatMetricValue(ytd, 'percent', { sign: true })}`
  - **Already null-safe**: returns "—".

- **Lines 294-298** (`ytd != null && ytd >= 0` guard): Only entered when non-null. **Safe**.

- **Line 305**: `Returns are ${formatMetricValue(ytd, 'percent', { sign: true })} year to date`
  - **Already null-safe**: returns "—".

### 4c: `useOverviewMetrics.ts` (line 19)

```typescript
const ytdReturn = summary?.ytdReturn ?? null;
```

Used at line 49: `ytdReturn != null ? formatPercent(ytdReturn, ...) : "—"`. **Already null-safe**.

### 4d: `ChatMargin.tsx` — `buildOverviewNote()` (lines 243-260)

```typescript
const ytdReturn = summary.ytdReturn;
const returnLabel = formatReturnPeriodLabel(summary);
```

Used at lines 251 and 259 via `formatCompactPercent(ytdReturn)` which returns "—" for null. **Already null-safe**.

### 4e: `ChatMargin.tsx` — `buildOverviewMarginMemo()` (lines 277-295)

```typescript
const ytdReturn = summary.ytdReturn;
const returnLabel = formatReturnPeriodLabel(summary);
```

Used at line 292: `${returnLabel} still sits at ${formatCompactPercent(ytdReturn)}`. **Already null-safe** — renders "—".

### 4f: `ChatMargin.tsx` — `buildOverviewGeneratedBars()` (lines 386-418)

```typescript
const returnBarLabel = summary?.returnPeriodLabel?.trim()?.toUpperCase() || 'YTD';
...
value: (summary?.ytdReturn ?? 0) * 100,
displayValue: formatCompactPercent(summary?.ytdReturn),
```

When `ytdReturn` is null: `value` becomes `0`, `displayValue` becomes "—". The bar renders at zero height with "—" label. **Tone is misleading**: `(summary?.ytdReturn ?? 0) >= 0` evaluates to `true` when null, so a null return bar gets an `'up'` tone (green). This is semantically wrong — a null value should be neutral, not positive. **Deferred** with the overviewBrief tone fixes above; same rationale (low impact, visual-polish scope).

### 4g: `ModernDashboardApp.tsx` (lines 337-353)

This is a **separate fallback chain** for the ChatMargin summary. It does its own resolution:
```typescript
const resolvedReturn = ytdReturn ?? oneYearReturn ?? annualizedReturn ?? null;
const returnPeriodLabel =
  ytdReturn != null ? 'YTD' : oneYearReturn != null ? '1Y' : annualizedReturn != null ? 'Ann.' : null;
return { ...summary, ytdReturn: resolvedReturn, returnPeriodLabel };
```

This overwrites `summary.ytdReturn` with a resolved value that includes oneYear/annualized fallbacks — but **with a `returnPeriodLabel`**. ChatMargin's prose uses `formatReturnPeriodLabel(summary)` which renders "1Y return" or "Ann. return" accordingly. This is a **labeled fallback**, not a mislabeled one, so it is semantically correct. **No change needed** — ChatMargin correctly distinguishes its fallback via `returnPeriodLabel`.

### Summary of Change 4

All `summary.ytdReturn` consumer sites already handle null gracefully via `formatMetricValue`/`renderInsightValue`/`formatCompactPercent` returning "—". No code changes required for **null safety** (no crashes, no wrong numbers displayed). However, three sites apply a **misleading tone** to null YTD values:

- `overviewBrief.tsx` lines 188, 200, and 220: null `ytd` gets `'down'` tone (red styling on unknown data) — line 200 is the `dayMove >= 1.5` branch which uses the same `ytd != null && ytd >= 0 ? 'up' : 'down'` expression
- `ChatMargin.tsx` line 400: null `ytd` gets `'up'` tone (green styling on unknown data)

These are **runtime-safe** (the "—" placeholder correctly communicates "no data") but **semantically misleading** (the color implies a directional signal that doesn't exist). **Deferred to a follow-up visual-polish pass** — fixing requires either adding `'neutral'` tone branches at each callsite or conditionally omitting the null clause, which is a broader pattern change across the insight prose. The core fix (stopping 142% from appearing) is complete without this.

**Optional improvement** (can be follow-up): In the `dayMove >= 1.5` branch of `buildLeadInsight()`, conditionally omit the "leaving year-to-date return at —" clause when `ytd` is null.

---

## Change 5: Add adapter and resolver tests

### 5a: `PortfolioSummaryAdapter.test.ts` — verify `totalReturn` is NOT used for `ytdReturn`

**File**: `frontend/packages/connectors/src/adapters/__tests__/PortfolioSummaryAdapter.test.ts`

Add a test that provides `returns.totalReturn` but no YTD period, and asserts `ytdReturn` is `null` (not the totalReturn value):

```typescript
it('does not use totalReturn as ytdReturn when no YTD period exists', () => {
  const adapter = new PortfolioSummaryAdapter();

  const result = adapter.transform(
    {},   // riskAnalysis
    {},   // riskScore
    {
      total_portfolio_value: 100000,
      holdings: [],
    },
    {
      returns: { totalReturn: 380 },
      performanceSummary: {
        periods: {
          '1Y': { portfolioReturn: 12.5 },
        },
        riskMetrics: {},
      },
    }
  );

  // totalReturn (380%) must NOT leak into ytdReturn
  expect(result.summary.ytdReturn).toBeNull();
});

it('uses YTD period portfolioReturn for ytdReturn when present', () => {
  const adapter = new PortfolioSummaryAdapter();

  const result = adapter.transform(
    {},
    {},
    {
      total_portfolio_value: 100000,
      holdings: [],
    },
    {
      returns: { totalReturn: 380 },
      performanceSummary: {
        periods: {
          YTD: { portfolioReturn: 8.4 },
          '1Y': { portfolioReturn: 12.5 },
        },
        riskMetrics: {},
      },
    }
  );

  expect(result.summary.ytdReturn).toBe(8.4);
});

it('cache invalidates when YTD period data appears on a subsequent call', () => {
  const adapter = new PortfolioSummaryAdapter();

  const baseRisk = {};
  const baseScore = {};
  const baseHoldings = { total_portfolio_value: 100000, holdings: [] };

  // First call — no YTD period
  const result1 = adapter.transform(baseRisk, baseScore, baseHoldings, {
    returns: { totalReturn: 380 },
    performanceSummary: {
      periods: { '1Y': { portfolioReturn: 12.5 } },
      riskMetrics: {},
    },
  });
  expect(result1.summary.ytdReturn).toBeNull();

  // Second call — same adapter instance, YTD period now populated
  const result2 = adapter.transform(baseRisk, baseScore, baseHoldings, {
    returns: { totalReturn: 380 },
    performanceSummary: {
      periods: {
        YTD: { portfolioReturn: 8.4 },
        '1Y': { portfolioReturn: 12.5 },
      },
      riskMetrics: {},
    },
  });

  // Must NOT be served from the first cache entry
  expect(result2.summary.ytdReturn).toBe(8.4);
});
```

### 5b: `portfolioScoping.test.ts` — fix mock that replicates the bug

**File**: `frontend/packages/connectors/src/resolver/__tests__/portfolioScoping.test.ts`

The mock `enrichPortfolioSummary` at line 102 reproduces the exact bug pattern:
```typescript
ytdReturn: performance?.returns?.totalReturn ?? null,
```

This must be updated to match the fixed adapter behavior. Either:
- Replace with `ytdReturn: null,` (if the mock doesn't provide YTD period data), or
- Add YTD period data to the mock performance fixture and read from there.

**Line 102 fix**:
```typescript
ytdReturn: (performance as any)?.performanceSummary?.periods?.YTD?.portfolioReturn ?? null,
```

**Line 660 fix**: The test at line 660 expects `ytdReturn` to be `8` after providing `returns: { totalReturn: 12 }` with no YTD period. After the fix, this should expect `null` (or the test should add a YTD period to the fixture).

Option A (preferred — fix the test to match corrected behavior):
```typescript
expect(enriched?.summary.ytdReturn).toBeNull();
```

Option B (add YTD period data to fixture at line 640-648):
```typescript
performanceDeferred.resolve({
  performance: {
    risk: { maxDrawdown: 4 },
    returns: { totalReturn: 12 },
    performanceTimeSeries: [{ portfolioValue: 3500 }, { portfolioValue: 3620 }],
    performanceSummary: {
      periods: {
        YTD: { portfolioReturn: 8 },
      },
      riskMetrics: { sharpeRatio: 1.4, alpha: 2.1 },
    },
    benchmark: { name: 'SPY' },
  },
});
// ...
expect(enriched?.summary.ytdReturn).toBe(8);
```

Option B is better because it validates the positive case (YTD period IS present).

### 5c: `PortfolioOverviewContainer.test.tsx` — verify Return metric label

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/PortfolioOverviewContainer.test.tsx`

The existing test at line 312 asserts:
```typescript
{ label: 'Return', value: '+6.2%', detail: 'vs IWM' },
```

This test provides a YTD period (`performanceSummary.periods.YTD.portfolioReturn: 6.2`), so the Return metric should still work. After the detail label change in Change 2, this should become:
```typescript
{ label: 'Return', value: '+6.2%', detail: 'YTD vs IWM' },
```

Add a new test case where no YTD period exists and verify the Return metric shows `—` with `(no YTD data)`:

```typescript
it('shows null return with "(no YTD data)" when no YTD period exists', () => {
  mockUsePortfolioSummary.mockReturnValue({
    data: {
      summary: {
        totalValue: 125000,
        dayChange: undefined,
        dayChangePercent: undefined,
        ytdReturn: undefined,   // ← adapter returns null without YTD period
        // ... other fields
      },
    },
    // ...
  });
  mockUsePerformance.mockReturnValue({
    data: {
      returns: { totalReturn: 380, annualizedReturn: 142 },
      risk: { volatility: 12.8, maxDrawdown: -4.0 },
      performanceSummary: {
        periods: {
          '1Y': { portfolioReturn: 15.2, volatility: 13.1 },
          // Note: NO YTD period
        },
        riskMetrics: { beta: 0.84, sharpeRatio: 1.27, maxDrawdown: -4.0, alpha: 2.4 },
      },
      benchmark: { name: 'SPY', benchmarkSharpe: '0.96' },
    },
  } as never);

  render(<PortfolioOverviewContainer />);

  const lastMetricStripCall = mockMetricStrip.mock.calls[mockMetricStrip.mock.calls.length - 1]?.[0];
  expect(lastMetricStripCall.items[0]).toMatchObject({
    label: 'Return',
    value: '—',
    detail: '(no YTD data)',
  });
});
```

---

## Change 6: Update existing overviewBrief tests + add regression test

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/overviewBrief.test.tsx`

### 6a: Update `emptyPerformance` fixture (only if Change 3 is included)

If Change 3 (type cleanup) is included, remove `annualizedReturn` and `oneYearReturn` from the fixture:

**Current code (lines 48-61)**:
```typescript
const emptyPerformance: OverviewBriefPerformanceInput = {
  annualizedReturn: null,
  ytdReturn: null,
  oneYearReturn: null,
  volatility: null,
  ...
```

**New code**:
```typescript
const emptyPerformance: OverviewBriefPerformanceInput = {
  ytdReturn: null,
  volatility: null,
  ...
```

If Change 3 is deferred, the fixture stays as-is (the extra fields are simply ignored).

### 6b: Update test expectation for Return detail label

The test at line 312 in PortfolioOverviewContainer.test.tsx and any other test that checks the Return metric detail string should be updated from `'vs IWM'` / `'vs SPY'` to `'YTD vs IWM'` / `'YTD vs SPY'` (matching the Change 2 label update).

### 6c: Add regression test

```typescript
it('shows null return with "(no YTD data)" detail when no YTD data is available', () => {
  const brief = buildOverviewBrief({
    summary: { ...baseSummary, ytdReturn: null },
    leadRow: null,
    concentrationRows: [],
    hasRenderableEnrichedRows: false,
    performance: { ...emptyPerformance, ytdReturn: null },
    riskAnalysisVolatility: null,
    formatMetricValue,
    renderInsightValue,
  });

  const returnMetric = brief.metricStrip.find((m) => m.label === 'Return');
  expect(returnMetric).toBeDefined();
  expect(returnMetric!.value).toBe('—');
  expect(returnMetric!.detail).toBe('(no YTD data)');
});
```

---

## Verification

After implementation:
1. Run `npx vitest run overviewBrief.test` — all tests pass
2. Run `npx vitest run PortfolioSummaryAdapter.test` — all tests pass
3. Run `npx vitest run portfolioScoping.test` — all tests pass (with updated expectations)
4. Run `npx vitest run PortfolioOverviewContainer.test` — all tests pass (with updated detail labels)
5. Run full TypeScript check (`npx tsc --noEmit`) — no type errors
6. Manual check: load "All Accounts" overview — Return metric should show `—` with `(no YTD data)` instead of `+142.0%`
7. Manual check: load a single portfolio with `supported_modes: ['performance_realized']` — `usePerformance()` routes to `RealizedPerformanceAdapter` (via `registry.ts`), which builds `performanceSummary.periods.YTD`. Return metric should show the actual YTD return with `YTD vs SPY`.
8. Manual check: load "All Accounts" or a portfolio using hypothetical `PerformanceAdapter` (no `performance_realized` mode) — Return metric should show `—` with `(no YTD data)` because `PerformanceAdapter` does not build a YTD period.

---

## Files Changed Summary

| File | Change |
|------|--------|
| `PortfolioSummaryAdapter.ts` | Remove `totalReturn` fallback, fix cache key |
| `overviewBrief.tsx` | Remove dangerous fallbacks, update detail label |
| `overviewBrief.test.tsx` | Add regression test, update fixture (if Change 3) |
| `PortfolioSummaryAdapter.test.ts` | Add adapter-level ytdReturn tests |
| `portfolioScoping.test.ts` | Fix mock + expectations |
| `PortfolioOverviewContainer.test.tsx` | Update detail label expectations, add no-YTD test |
| `PortfolioOverviewContainer.tsx` | Remove unused props (only if Change 3) |

**No code changes in this fix** (verified null-safe, no crashes or wrong numbers):
- `useOverviewMetrics.ts` — already handles null with `?? null` + ternary
- `ChatMargin.tsx` — null-safe via `formatCompactPercent`/`formatReturnPeriodLabel`; `buildOverviewGeneratedBars()` has a deferred misleading-tone issue (null YTD → `'up'` tone) tracked in Change 4 summary
- `ModernDashboardApp.tsx` — uses labeled fallback with `returnPeriodLabel`, not mislabeled
