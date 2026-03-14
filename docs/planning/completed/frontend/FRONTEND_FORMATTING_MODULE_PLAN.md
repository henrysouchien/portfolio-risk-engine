# Shared Number Formatting Module

**Date**: 2026-02-27
**Status**: COMPLETE — implemented by Codex, verified in Chrome (2026-02-27)
**Parent doc**: `completed/FRONTEND_PHASE2_WORKING_DOC.md` (Cross-Cutting section)

## Context

During Wave 1 visual verification, we caught a bug where `RiskMetricsContainer.tsx` displayed raw floats like `"14.70129355005772%"` in progress bars. The fix was a `Math.round()` wrapper — but the root cause is deeper: **the codebase has zero shared formatting utilities**. There are 5 separate `formatCurrency` / `formatPercent` definitions across 5 components, each with different behavior (decimal places, sign handling, compact notation). ~150+ inline `.toFixed()` calls across the UI package with inconsistent precision. This is a ticking time bomb for Wave 2, which will add more containers with more formatting needs.

**Goal**: Create a single formatting module in `@risk/chassis` that all packages can import. Migrate the two Wave 1 containers first, then existing presentation components.

---

## Current State (Audit)

### 5 Locally-Defined Formatters (all incompatible)

| File | `formatCurrency` | `formatPercent` |
|---|---|---|
| `RiskMetricsContainer.tsx` | `Intl.NumberFormat` USD, 0 decimals, manual negative sign | *(none — uses inline `.toFixed()`)* |
| `PerformanceView.tsx` | `Intl.NumberFormat` USD, 0 decimals, `notation: 'compact'` for >$1M | `±` sign prefix, `.toFixed(2)` |
| `HoldingsView.tsx` | `Intl.NumberFormat` USD, 0 decimals | `±` sign prefix, `.toFixed(1)` ← different precision |
| `PortfolioOverview.tsx` | Manual `$X.XXM` / `$XK` string interpolation | `±` sign prefix, `.toFixed(2)` |
| `StockLookup.tsx` | *(none)* — has `formatMarketCap` (T/B/M) | *(none — inline `.toFixed(2)`)* |

### Inline `.toFixed()` calls: ~150+ across `ui`, ~20 in `connectors`, 0 in `chassis`

### Notable Inconsistencies

1. **`formatPercent` decimal places vary**: `HoldingsView` uses `.toFixed(1)`, `PerformanceView` and `PortfolioOverview` use `.toFixed(2)`
2. **`formatCurrency` implementations differ**: `PortfolioOverview` does manual M/K scaling, others use `Intl.NumberFormat`, `PerformanceView` uses `notation: 'compact'` for large values
3. **`useAnalysisReport.ts`**: Formats `totalPortfolioValue` with `.toFixed(2)` (raw number with no `$`) — inconsistent with every other portfolio value display
4. **`RiskAnalysisAdapter.ts`**: `parseFloat(beta.toFixed(3))` — pointless roundtrip that both rounds precision AND returns a float that may re-introduce floating point noise
5. **`StrategyBuilder.tsx`**: `.toLocaleString()` with no arguments — locale and decimal behavior is system-dependent
6. **`chartDataAdapters.ts` `formatPercentage`**: Returns a `number` (rounded math), not a display string — likely misnamed

---

## Shared Formatting API

New file: `frontend/packages/chassis/src/utils/formatting.ts`

```typescript
// --- Currency ---
formatCurrency(value: number, opts?: { decimals?: number; compact?: boolean }): string
// Default: USD, 0 decimals, standard notation
// compact: true → uses Intl compact notation ($1.2M, $450K)
// Handles negative values correctly via Intl (no manual sign logic)

// --- Percent ---
formatPercent(value: number, opts?: { decimals?: number; sign?: boolean }): string
// Default: 1 decimal, no sign prefix
// sign: true → "+12.3%" / "-4.5%"
// Handles the % suffix

// --- Number ---
formatNumber(value: number, opts?: { decimals?: number; sign?: boolean }): string
// Default: 2 decimals, no sign
// For betas, ratios, correlations, t-stats

// --- Compact ---
formatCompact(value: number, opts?: { decimals?: number; prefix?: string }): string
// For market cap / large values: 1.2T, 450B, 12.3M, 5.6K
// prefix: "$" → "$1.2T"

// --- Basis Points ---
formatBasisPoints(value: number): string
// Input: decimal (e.g. 0.0042) → "42 bp"

// --- Numeric Rounding (not display) ---
roundTo(value: number, decimals?: number): number
// Default: 2 decimals. Returns number, not string.
// Replaces patterns like `parseFloat(beta.toFixed(3))` and `formatPercentage(): number`
```

### Safety / Edge Case Policy

- **NaN / Infinity**: Display formatters return `"—"` for non-finite inputs (consistent "no data" indicator). `roundTo` returns `NaN` for non-finite input (numeric passthrough).
- **Negative zero**: Normalized to `0` before formatting (`Object.is(value, -0) ? 0 : value`)
- **Locale**: Hardcoded `'en-US'` — no dynamic locale switching (matches all existing formatters)
- **Currency**: Hardcoded `'USD'` — multi-currency display is not in scope
- **Intl caching**: Create `Intl.NumberFormat` instances at module level for common option combos (0-decimal currency, 1-decimal percent, 2-decimal number). Construct on-demand for custom decimals — Intl is already cached by the engine for identical options.

All functions are pure, no side effects, tree-shakeable.

---

## Implementation Plan

### Step 1: Create the formatting module

**File**: `frontend/packages/chassis/src/utils/formatting.ts` (new)

- Implement 6 functions listed above (5 display formatters + `roundTo` numeric helper)
- Each display function: typed input, typed options object, string output
- `roundTo`: typed input, returns number (for data-layer rounding, replaces `parseFloat(x.toFixed(n))`)
- Unit-precision defaults chosen to match the most common existing usage:
  - Currency: 0 decimals (matches 4/5 existing formatters)
  - Percent: 1 decimal (most metric displays use 1; `sign: true` for return displays that use 2)
  - Number: 2 decimals (matches beta/ratio displays)

### Step 2: Export from chassis barrel

**File**: `frontend/packages/chassis/src/index.ts` (edit)

- Add: `export * from './utils/formatting';`

### Step 3: Migrate Wave 1 containers (first adopters)

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/RiskMetricsContainer.tsx` (edit)

- Replace local `formatCurrency` with `import { formatCurrency } from '@risk/chassis'`
- Replace inline `.toFixed()` calls with `formatPercent` / `formatNumber`
- Delete the local `formatCurrency` function (lines 54-59)

**File**: `frontend/packages/ui/src/components/dashboard/views/modern/FactorRiskModelContainer.tsx` (no formatting calls — skip)

### Step 4: Migrate presentation components (5 files)

Migrate in order of most formatting calls → fewest:

1. **`PerformanceView.tsx`** (~30 formatting calls)
   - Delete local `formatCurrency` + `formatPercent` (lines 639-659)
   - Replace all calls with chassis imports
   - Currency: existing fn uses `notation: 'compact'` when `amount > 1_000_000` → replace with `formatCurrency(value, { compact: true })` for the `currentValue` call site (line 1018), plain `formatCurrency(value)` elsewhere
   - Percent: existing fn uses `.toFixed(2)` with sign → replace with `formatPercent(value, { decimals: 2, sign: true })`

2. **`StrategyBuilder.tsx`** (~15 formatting calls)
   - Replace inline `.toFixed()` calls with `formatPercent` / `formatNumber`
   - Replace `.toLocaleString()` calls (lines 965, 1079) with `formatCurrency` / `formatCompact`

3. **`HoldingsView.tsx`** (~10 formatting calls)
   - Delete local `formatCurrency` + `formatPercent` (lines 635-647)
   - Currency: `formatCurrency(value)` — behavior matches (Intl, 0 decimals)
   - Percent: existing fn uses `.toFixed(1)` with sign → replace with `formatPercent(value, { sign: true })` (default 1 decimal matches)

4. **`PortfolioOverview.tsx`** (~8 formatting calls)
   - Delete local `formatCurrency` + `formatPercent` (lines 417-431)
   - Currency: existing fn has manual M/K scaling (`$1.23M`, `$450K`, `$123`). Replace with `formatCurrency(value, { compact: true })`. **Note**: Intl compact output may differ slightly (e.g. `$1.2M` vs `$1.23M`) — accept Intl output as the canonical format going forward. Visual verify in Chrome.
   - Percent: existing fn uses `.toFixed(2)` with sign → replace with `formatPercent(value, { decimals: 2, sign: true })`

5. **`FactorRiskModel.tsx`** (~7 formatting calls)
   - Replace inline `.toFixed()` with `formatPercent` / `formatNumber`

### Step 5: Migrate connectors adapters (optional — lower priority)

These are data-layer formatters producing display strings that flow into UI. Same pattern but lower priority since they're already consistent within each adapter.

- `RiskAnalysisAdapter.ts` (~8 calls)
- `PerformanceAdapter.ts` (~5 calls)
- `RiskSettingsAdapter.ts` (~2 calls)
- `useAnalysisReport.ts` (~5 calls)
- `registry.ts` (~3 calls)

---

## Files Modified (Summary)

| File | Action |
|---|---|
| `frontend/packages/chassis/src/utils/formatting.ts` | **New** — 6 functions (5 display + `roundTo`) |
| `frontend/packages/chassis/src/utils/__tests__/formatting.test.ts` | **New** — unit tests |
| `frontend/packages/chassis/src/index.ts` | **Edit** — add barrel export |
| `frontend/packages/ui/.../RiskMetricsContainer.tsx` | **Edit** — replace local formatter |
| `frontend/packages/ui/.../PerformanceView.tsx` | **Edit** — replace 2 local fns + ~30 calls |
| `frontend/packages/ui/.../StrategyBuilder.tsx` | **Edit** — replace ~15 inline calls |
| `frontend/packages/ui/.../HoldingsView.tsx` | **Edit** — replace 2 local fns + ~10 calls |
| `frontend/packages/ui/.../PortfolioOverview.tsx` | **Edit** — replace 2 local fns + ~8 calls |
| `frontend/packages/ui/.../FactorRiskModel.tsx` | **Edit** — replace ~7 inline calls |
| *(Optional)* 5 connectors adapter files | **Edit** — replace ~23 inline calls |

---

## Execution Order

1. Steps 1-2 (create module + barrel export) — foundation
2. Step 3 (Wave 1 containers) — validate the pattern works end-to-end
3. Step 4 files 1-2 (PerformanceView + StrategyBuilder) — highest call count
4. Step 4 files 3-5 (HoldingsView, PortfolioOverview, FactorRiskModel) — remaining UI
5. Step 5 (connectors) — if time permits, otherwise defer

Typecheck after each file migration. No behavior changes expected — this is a pure refactor.

---

## Verification

1. **Unit tests** (`formatting.test.ts`) — run after Step 1:
   - `formatCurrency`: positive, negative, zero, NaN, compact mode, custom decimals
   - `formatPercent`: default 1 decimal, 2 decimal override, sign prefix, NaN → `"—"`
   - `formatNumber`: default 2 decimal, sign, NaN/Infinity → `"—"`
   - `formatCompact`: T/B/M/K thresholds, prefix option
   - `formatBasisPoints`: 0.0042 → "42 bp", negative, zero
   - `roundTo`: precision, negative zero normalization, NaN passthrough
2. `cd frontend && pnpm typecheck` — 0 errors after each step
3. `cd frontend && pnpm lint` — no new errors
4. Visual verification in Chrome (after each migration step):
   - Score view: VaR, Beta, Volatility, Max Drawdown format unchanged
   - Performance view: returns, currency amounts format unchanged
   - Holdings view: position values, percentages format unchanged
   - Factor Analysis: exposures, contributions format unchanged
   - Strategy Builder: metrics, returns format unchanged
   - PortfolioOverview: compact currency values — accept Intl output as new canonical format
5. Grep for remaining local `formatCurrency`/`formatPercent` definitions — should be 0 in migrated files
6. Grep for `.toFixed()` in migrated files — should be 0 (all replaced)

---

## Codex Review v1 (2026-02-27)

**Result**: FAIL — 6 issues

| # | Severity | Issue | Resolution in v2 |
|---|---|---|---|
| 1 | High | PerformanceView compact currency not preserved in migration steps | Added explicit `formatCurrency(value, { compact: true })` for `currentValue` call site |
| 2 | High | PortfolioOverview replacement not output-equivalent | Acknowledged Intl compact differs from manual M/K; accept Intl as canonical, visual verify |
| 3 | High | Percent precision/sign migration incomplete for Holdings + PortfolioOverview | Added explicit option overrides for each file's `formatPercent` calls |
| 4 | Medium | API incomplete for numeric rounding patterns | Added `roundTo(value, decimals): number` helper |
| 5 | Medium | Missing safety/perf concerns (NaN, -0, locale, caching) | Added Safety / Edge Case Policy section |
| 6 | Low | No unit tests in verification | Added unit test step with edge case coverage |
