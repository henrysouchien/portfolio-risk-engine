# Plan: Enrich Trading P&L Card with Full Trading Analysis Data

> Status: DRAFT v3 — addressing Codex review findings (rounds 1+2)
> Date: 2026-03-16

## Context

The TradingPnLCard in the Performance view currently shows only 3 data points: Total Trading P&L, Win Rate, and Overall Grade. Meanwhile, the `get_trading_analysis` MCP tool returns rich data including win/loss records, profit factor, expectancy, per-trade scorecards with grades, return distribution, sub-grade breakdown (conviction, timing, position sizing, averaging down), and per-currency P&L splits. The resolver drops most of this data — only `summary` and `income_analysis` are passed through to the frontend.

**Goal:** Surface the trading analysis insights already available from the backend into the card UI without adding new backend endpoints.

## Codex Review Findings (v1 → v2)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | Expectancy is currency-agnostic, not USD — `$` formatting misleading in multi-currency | Show expectancy without currency symbol; label as "per trade" with no `$` prefix |
| 2 | High | `num_breakeven` omitted — W+L won't equal total trades | Add `num_breakeven` to type; render "BE" count when > 0 |
| 3 | Medium | Resolver too lossy/UI-specific — pre-slicing top trades doesn't match IncomeProjectionCard pattern | Pass normalized `trade_scorecard` array through resolver; card derives top trades locally via `useMemo` |
| 4 | Medium | Type drift — `conviction_aligned` should be `boolean`; `by_currency` shape doesn't match backend; `trade_scorecard` mistyped as `Record` | Fix `conviction_aligned: boolean`; align `by_currency` with actual backend serialization; type `trade_scorecard` as array in `APIService` |
| 5 | Medium | Empty object truthiness — backend returns `{}` for empty `realized_performance` | Gate on required numeric fields (`total_trades > 0`), not object truthiness |
| 6 | Low | Grade normalization — sub-grades can be `A+`, `A-`, etc. but tone map only keys `A/B/C/D/F`; removing overall grade makes card slower to scan | Normalize grade to base letter for color; keep overall grade badge + add sub-grade pills below it |

### Round 2 Findings

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 7 | Medium | `trade_scorecard` status can be `PARTIAL` too; resolver still filters to `CLOSED` only — not a true pass-through | Pass all entries through resolver; card filters `CLOSED` in `useMemo`; type `status` as `string` |
| 8 | Medium | `profit_factor` can be `null` when no losses; typed too narrowly as `number` | Type as `number | null` everywhere (incl. `by_currency`); render "∞" when null + wins > 0, else "—" |
| 9 | Low | Catalog `descriptors.ts` advertises old field list — should include new fields | Update descriptor metadata for `trading-analysis` |

## Files to Modify

| # | File | Change |
|---|------|--------|
| 1 | `frontend/packages/chassis/src/services/APIService.ts` | Tighten `TradingAnalysisApiResponse` — `trade_scorecard` as typed array |
| 2 | `frontend/packages/chassis/src/catalog/types.ts` | Extend `TradingAnalysisSourceData` with new fields; fix `conviction_aligned` to boolean |
| 3 | `frontend/packages/chassis/src/catalog/descriptors.ts` | Update `trading-analysis` descriptor to advertise new fields |
| 4 | `frontend/packages/connectors/src/resolver/registry.ts` | Pass normalized backend blocks through (full scorecard, no pre-filtering) |
| 5 | `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx` | Enhance card UI; card-local derivation of top trades |

All paths relative to `risk_module/`.

## Step 1: Tighten API response type

**File:** `frontend/packages/chassis/src/services/APIService.ts` (line 520)

Add a typed interface for trade scorecard entries and use it in the response type:

```typescript
export interface TradeScoreEntry {
  symbol: string;
  name: string;
  currency: string;
  direction: 'LONG' | 'SHORT';
  days_in_trade: number;
  pnl_percent: number;
  pnl_dollars: number;
  pnl_dollars_usd: number;
  win_score: number;
  grade: string;
  status: string;  // 'CLOSED' | 'OPEN' | 'PARTIAL'
  entry_date: string;
  exit_date: string;
  avg_buy_price: number;
  avg_sell_price: number;
}

export interface TradingAnalysisApiResponse {
  status: string;
  summary?: Record<string, unknown>;
  realized_performance?: Record<string, unknown>;
  trade_scorecard?: TradeScoreEntry[];  // was Record<string, unknown>
  timing_analysis?: Record<string, unknown>;
  income_analysis?: Record<string, unknown>;
  behavioral_analysis?: Record<string, unknown>;
  return_statistics?: Record<string, unknown>;
  return_distribution?: Record<string, unknown>;
  [key: string]: unknown;
}
```

## Step 2: Extend `TradingAnalysisSourceData` types

**File:** `frontend/packages/chassis/src/catalog/types.ts` (line 191)

All new fields are optional so the card degrades gracefully.

```typescript
export interface TradingAnalysisSourceData {
  signals: unknown[];
  confidence: number;

  trading_summary?: {
    total_trading_pnl: number;
    total_trading_pnl_usd: number;
    win_rate: number;
    avg_win_score: number;
    avg_timing_score: number | null;
    total_regret: number | null;
    conviction_aligned: boolean;  // FIXED: was number
    grades: {
      conviction: string;
      timing: string;
      position_sizing: string;
      averaging_down: string;
      overall: string;
    };
    total_pnl_by_currency?: Record<string, number>;
  };

  realized_performance?: {
    num_wins: number;
    num_losses: number;
    num_breakeven: number;  // ADDED: Codex finding #2
    total_trades: number;
    win_percent: number;
    profit_factor: number | null;  // null when no losses
    expectancy: number;
    avg_win: number;
    avg_loss: number;
    by_currency?: Record<string, {
      num_wins: number;
      num_losses: number;
      num_breakeven: number;
      total_trades: number;
      net_pnl: number;
      profit_factor: number | null;  // null when denominator is zero
      expectancy: number;
    }>;
  };

  // Normalized trade scorecard — card derives "best trades" locally
  trade_scorecard?: Array<{
    symbol: string;
    name: string;
    currency: string;
    direction: string;
    pnl_dollars_usd: number;
    pnl_percent: number;
    win_score: number;
    grade: string;
    days_in_trade: number;
    status: string;
  }>;

  // Return distribution histogram buckets
  return_distribution?: Array<{
    range_label: string;
    count: number;
    frequency: number;
  }>;

  income_analysis?: {
    total_income: number;
    total_dividends: number;
    current_monthly_rate: number;
    projected_annual: number;
  };

  summary?: string;
}
```

## Step 3: Pass normalized data through resolver

**File:** `frontend/packages/connectors/src/resolver/registry.ts` (lines 446-454)

Following the IncomeProjectionCard pattern: resolver normalizes raw backend data, card derives display subsets locally.

```typescript
return {
  signals,
  summary,
  confidence,
  trading_summary: backendData?.summary
    ? {
        ...(backendData.summary as SDKSourceOutputMap['trading-analysis']['trading_summary']),
        total_pnl_by_currency: (backendData.summary as any)?.total_pnl_by_currency,
      }
    : undefined,
  income_analysis: backendData?.income_analysis as SDKSourceOutputMap['trading-analysis']['income_analysis'],

  // Pass through realized_performance — gate on total_trades > 0 (Codex #5: empty {} guard)
  realized_performance: (() => {
    const rp = backendData?.realized_performance as any;
    if (!rp || typeof rp.total_trades !== 'number' || rp.total_trades === 0) return undefined;
    return {
      num_wins: rp.num_wins,
      num_losses: rp.num_losses,
      num_breakeven: rp.num_breakeven ?? 0,
      total_trades: rp.total_trades,
      win_percent: rp.win_percent,
      profit_factor: rp.profit_factor,
      expectancy: rp.expectancy,
      avg_win: rp.avg_win,
      avg_loss: rp.avg_loss,
      by_currency: rp.by_currency,
    };
  })(),

  // Pass through full scorecard — no status filtering (Codex #3, #7)
  // Card filters to CLOSED and derives top trades locally via useMemo
  trade_scorecard: Array.isArray(backendData?.trade_scorecard)
    ? (backendData.trade_scorecard as any[])
        .map((t) => ({
          symbol: t.symbol,
          name: t.name,
          currency: t.currency,
          direction: t.direction,
          pnl_dollars_usd: t.pnl_dollars_usd,
          pnl_percent: t.pnl_percent,
          win_score: t.win_score,
          grade: t.grade,
          days_in_trade: t.days_in_trade,
          status: t.status,
        }))
    : undefined,

  // Return distribution — gate on non-empty buckets array (Codex #5)
  return_distribution: (() => {
    const rd = backendData?.return_distribution as any;
    if (!Array.isArray(rd?.buckets) || rd.buckets.length === 0) return undefined;
    const nonZero = rd.buckets.filter((b: any) => b.count > 0);
    return nonZero.length > 0
      ? nonZero.map((b: any) => ({ range_label: b.range_label, count: b.count, frequency: b.frequency }))
      : undefined;
  })(),
};
```

## Step 4: Update catalog descriptors

**File:** `frontend/packages/chassis/src/catalog/descriptors.ts` (line ~267)

Add new field descriptor objects to the `trading-analysis` descriptor's `fields` array (each entry is `{ name, type, description }`):

```typescript
fields: [
  // ... existing 5 fields ...
  { name: 'realized_performance', type: 'object', description: 'Realized win/loss statistics, profit factor, expectancy, and per-currency breakdown.' },
  { name: 'trade_scorecard', type: 'array', description: 'Per-trade scorecard with grades, P&L, and timing.' },
  { name: 'return_distribution', type: 'array', description: 'Return distribution histogram buckets.' },
],
```

## Step 5: Enhance TradingPnLCard UI

**File:** `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx`

### Grade normalization helper (Codex #6)

```typescript
/** Extract base letter from grades like "A+", "A-", "B+" for color mapping */
function baseGrade(grade: string): string {
  return grade.trim().charAt(0).toUpperCase();
}
```

### Card Layout (top to bottom)

1. **Hero: Total Trading P&L (USD)** — keep existing large number, color-coded green/red

2. **Win/Loss Record** — "34W / 8L (42 trades)" with green W count and red L count. When `num_breakeven > 0`, append "/ 0 BE". Sourced from `realized_performance`.

3. **Metrics row** (2-col grid, `StatPair`):
   - Profit Factor: formatted number (e.g. "3.08x"); when `null`: show "∞" if `num_losses === 0 && num_wins > 0`, otherwise "—" (Codex #8)
   - Expectancy: formatted number **without currency symbol** (Codex #1) — e.g. "99.74 / trade"

4. **Overall Grade + Sub-grade pills** (Codex #6 — keep overall for quick scan):
   - Large overall grade badge (keep existing circle)
   - Below it: row of 4 compact pills: `Conv C` | `Time N/A` | `Size A` | `AvgD F`
   - Use `baseGrade()` for `gradeToneClasses` lookup

5. **Best Trades** — top 5 closed trades by `pnl_dollars_usd` desc, derived via `useMemo` filtering `status === 'CLOSED'` from `trade_scorecard` (Codex #3, #7):
   - Each row: symbol (bold) + direction arrow | P&L (green/red) + grade pill
   - Pattern from IncomeProjectionCard's "Top Payers"

6. **Return Distribution** — mini horizontal bar chart:
   - Inline CSS bars, width proportional to `frequency`
   - Only renders when `return_distribution` is present and non-empty

### Graceful degradation (Codex #5):
- Each section gated on data presence AND required fields being valid numbers
- `realized_performance` section: only render if `total_trades > 0`
- `trade_scorecard` section: only render if array length > 0
- `return_distribution` section: only render if array length > 0
- Loading skeleton: keep existing 3-row pulse animation
- Fallback states: keep existing partial-data and no-data branches

### Reuse existing:
- `StatPair` from `../../blocks`
- `gradeToneClasses` (already in file) + new `baseGrade()` helper
- `formatCurrency`, `formatPercent` from `@risk/chassis`
- `useMemo` for top trades derivation (like IncomeProjectionCard's `topContributors`)

## Verification

1. Start the risk_module frontend dev server (`cd frontend && pnpm dev`)
2. Navigate to Performance view in the dashboard
3. Verify the TradingPnLCard shows all new sections with real data
4. Check that expectancy displays without `$` prefix (Codex #1)
5. Check that W/L record sums correctly with breakeven trades (Codex #2)
6. Check that grade pills work for `A+`, `A-`, `B+` etc. (Codex #6)
7. Check loading skeleton still works
8. Check "Unavailable" state for portfolios without trading support
9. Check graceful degradation: backend returning empty `{}` for `realized_performance` should hide that section (Codex #5)
10. Compare visually with IncomeProjectionCard — cards should feel like siblings
