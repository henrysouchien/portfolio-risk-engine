# Plan: USD-Normalized Expectancy & Profit Factor in Trading Analysis

> Status: DRAFT v2 — addressing Codex review findings
> Date: 2026-03-17

## Context

The trading analysis MCP tool returns `expectancy` and `profit_factor` computed from raw `pnl_dollars` (native currency amounts). In multi-currency portfolios, this produces meaningless blended numbers — e.g. expectancy of -632.73 that mixes USD and HKD trades. Meanwhile, `total_trading_pnl_usd` and per-trade `pnl_dollars_usd` are already USD-normalized via FX conversion in `analyzer.py`.

The hero P&L in the TradingPnLCard already shows the USD-normalized total ($176), but the supporting metrics (expectancy, profit factor) use the raw blended values, creating an inconsistency.

**Goal:** Add `expectancy_usd` and `profit_factor_usd` to the backend MCP response so all consumers (frontend, Telegram bot, CLI, any MCP client) get USD-normalized trading metrics.

## Current State

- `analyzer.py:60-79` — FX rates fetched, `pnl_dollars_usd` set on each `TradeResult`
- `metrics.py:256-316` — `_calculate_realized_performance()` computes `expectancy` and `profit_factor` from `pnl_dollars` (raw currency)
- `models.py:425-467` — `RealizedPerformanceSummary` dataclass holds the metrics
- `models.py:237-253` — `_summary_to_dict()` helper serializes per-currency summaries
- `models.py:448-466` — `RealizedPerformanceSummary.to_dict()` serializes the top-level summary
- `models.py:857-956` — `to_api_response()` and `to_summary()` assemble the MCP response

The per-trade `pnl_dollars_usd` is already computed but never aggregated into summary-level metrics.

## Files to Modify

| # | File | Change |
|---|------|--------|
| 1 | `trading_analysis/models.py` | Add `expectancy_usd` and `profit_factor_usd` fields to `RealizedPerformanceSummary`; update `to_dict()` serialization |
| 2 | `trading_analysis/metrics.py` | Compute USD variants in `_calculate_realized_performance()` using `pnl_dollars_usd` |
| 3 | `frontend/packages/chassis/src/catalog/types.ts` | Add `expectancy_usd` and `profit_factor_usd` to `realized_performance` type |
| 4 | `frontend/packages/connectors/src/resolver/registry.ts` | Pass through new fields in resolver |
| 5 | `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx` | Use `_usd` fields; show `$` formatting since values are now truly USD |

All paths relative to `risk_module/`.

## Codex Review Findings (v1 → v2)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | Missing serialization paths: `get_agent_snapshot()` and `to_cli_report()` not covered | Update both: agent snapshot includes `_usd` fields; CLI report uses `_usd` fields for display |
| 2 | Medium | `pnl_dollars_usd` fallback: models use `_effective_pnl_usd()` which falls back to raw `pnl_dollars` when `pnl_dollars_usd == 0.0`. Must use same fallback in metrics calculation, otherwise 0-sentinel trades become false breakevens | Use `_effective_pnl_usd()` pattern (or equivalent) in metrics: `pnl_usd = t.pnl_dollars_usd if t.pnl_dollars_usd != 0.0 else t.pnl_dollars` |
| 3 | Medium | Test updates needed: `test_result_serialization.py` hard-codes response shapes; `test_agent_snapshot.py` asserts no `_usd` keys; need new multi-currency calculation tests | Update existing snapshot tests; add new tests in `test_usd_normalization.py` |

## Step 1: Add fields to `RealizedPerformanceSummary`

**File:** `trading_analysis/models.py` (line ~425)

Add two new fields to the dataclass:

```python
@dataclass
class RealizedPerformanceSummary:
    # ... existing fields ...
    expectancy: float = 0.0
    profit_factor: Optional[float] = None
    # NEW:
    expectancy_usd: float = 0.0
    profit_factor_usd: Optional[float] = None
```

Update `to_dict()` (line ~448) to include:

```python
def to_dict(self) -> dict:
    d = {
        # ... existing fields ...
        'expectancy': round(self.expectancy, 2),
        'profit_factor': round(self.profit_factor, 2) if self.profit_factor is not None else None,
        # NEW:
        'expectancy_usd': round(self.expectancy_usd, 2),
        'profit_factor_usd': round(self.profit_factor_usd, 2) if self.profit_factor_usd is not None else None,
    }
    # ... rest unchanged ...
```

Update ALL serialization paths that surface these metrics:

- `to_dict()` (line ~448) — used by `to_api_response()` for `format="full"`
- `to_summary()` (line ~907) — used for `format="summary"` (Telegram bot default)
- `get_agent_snapshot()` (line ~699) — used for `format="agent"`
- `to_cli_report()` (line ~1085) — used for `format="report"`. Update to display `_usd` values instead of raw blended values

**Note:** `_summary_to_dict()` in `metrics.py` handles per-currency summaries. Per-currency summaries are already single-currency, so they don't need USD variants — only the top-level summary does.

## Step 2: Compute USD variants in metrics calculation

**File:** `trading_analysis/metrics.py` (line ~256)

In `_calculate_realized_performance()`, after the existing `pnl_dollars` aggregation, add a parallel pass using `pnl_dollars_usd`:

```python
# Existing: raw currency metrics
pnl_values = [float(_trade_value(t, 'pnl_dollars', 0.0)) for t in trades]
# ... existing wins/losses/expectancy/profit_factor calculation ...

# NEW: USD-normalized metrics
# Use effective USD P&L with same fallback as _effective_pnl_usd():
# pnl_dollars_usd if non-zero, else fall back to pnl_dollars
def _effective_usd(t):
    usd = float(_trade_value(t, 'pnl_dollars_usd', 0.0))
    return usd if usd != 0.0 else float(_trade_value(t, 'pnl_dollars', 0.0))

pnl_usd_values = [_effective_usd(t) for t in trades]
wins_usd = [p for p in pnl_usd_values if p > 0]
losses_usd = [p for p in pnl_usd_values if p < 0]

total_win_usd = sum(wins_usd)
total_loss_usd = sum(abs(p) for p in losses_usd)
avg_win_usd = _safe_divide(total_win_usd, len(wins_usd), 0.0)
avg_loss_usd = _safe_divide(total_loss_usd, len(losses_usd), 0.0)

profit_factor_usd = _safe_divide_optional(total_win_usd, total_loss_usd)
expectancy_usd = (win_proportion * avg_win_usd) - (loss_proportion * abs(avg_loss_usd))
```

**Fallback semantics (Codex finding #2):** The `_effective_pnl_usd()` pattern in `models.py:624` treats `pnl_dollars_usd == 0.0` as "FX conversion not available, fall back to raw." We replicate this so win/loss classification stays consistent — a trade that's a win in raw currency remains a win in the USD pass.

Then pass these to the `RealizedPerformanceSummary` constructor:

```python
return RealizedPerformanceSummary(
    # ... existing fields ...
    expectancy_usd=expectancy_usd,
    profit_factor_usd=profit_factor_usd,
)
```

**Important:** `win_proportion` and `loss_proportion` stay the same (trade counts don't change with currency normalization — only dollar amounts do). `len(wins_usd)` and `len(losses_usd)` should equal `num_wins` and `num_losses` since we're using the same trades, just different P&L values.

**Note:** The `include_by_currency` path calls `_calculate_realized_performance` recursively for each currency. Single-currency subsets will have `pnl_dollars_usd == pnl_dollars * fx_rate`, but these per-currency summaries don't need `_usd` variants since they're already single-currency. Only the top-level call (which blends currencies) benefits from USD normalization. We should still compute and populate the fields for consistency, but they'll naturally be correct.

## Step 3: Update frontend types

**File:** `frontend/packages/chassis/src/catalog/types.ts` (line ~213)

Add to the `realized_performance` interface:

```typescript
realized_performance?: {
    // ... existing fields ...
    expectancy: number;
    profit_factor: number | null;
    // NEW:
    expectancy_usd: number;
    profit_factor_usd: number | null;
    // ... rest ...
};
```

## Step 4: Pass through in resolver

**File:** `frontend/packages/connectors/src/resolver/registry.ts`

In the `realized_performance` mapping block, add:

```typescript
expectancy_usd: rp.expectancy_usd,
profit_factor_usd: rp.profit_factor_usd,
```

## Step 5: Use USD fields in TradingPnLCard

**File:** `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx`

Replace the current `profitFactorDisplay` and `expectancyDisplay` (lines 66-76):

```typescript
const profitFactorDisplay = !realizedPerformanceData
  ? '—'
  : realizedPerformanceData.profit_factor_usd === null
    ? realizedPerformanceData.num_losses === 0 && realizedPerformanceData.num_wins > 0
      ? '∞'
      : '—'
    : `${formatNumber(realizedPerformanceData.profit_factor_usd, { decimals: 2 })}x`

const expectancyDisplay = realizedPerformanceData
  ? `${formatCurrency(realizedPerformanceData.expectancy_usd)} / trade`
  : '—'
```

Key change: expectancy now uses `formatCurrency()` (with `$`) since the value is truly USD-normalized.

## Expected Results

| Metric | Before (raw blended) | After (USD-normalized) |
|--------|---------------------|----------------------|
| Expectancy | -632.73 / trade | ~$4.15 / trade |
| Profit Factor | 0.19x | ~1.24x |

The hero P&L ($176) stays the same — it was already USD-normalized.

## Verification

### Test updates needed (Codex finding #3)

1. **`tests/trading_analysis/test_result_serialization.py`** — Update hard-coded response shape assertions to include `expectancy_usd` and `profit_factor_usd` in both `to_dict()` and `to_summary()` output
2. **`tests/trading_analysis/test_agent_snapshot.py`** — Update agent snapshot assertions to include `_usd` fields (currently asserts they don't exist)
3. **`tests/trading_analysis/test_usd_normalization.py`** — Add new test cases:
   - Multi-currency: USD + HKD trades → verify `expectancy_usd` differs from `expectancy`
   - All-USD: `expectancy_usd` ≈ `expectancy` (within rounding)
   - Zero-sentinel fallback: trade with `pnl_dollars_usd == 0.0` falls back to `pnl_dollars`
   - No-losses case: `profit_factor_usd` is `None`, not infinity

### Manual verification

1. Run tests: `pytest tests/trading_analysis/ -q`
2. Call MCP tool: `get_trading_analysis(format="full")` — verify `realized_performance` contains `expectancy_usd` and `profit_factor_usd`
3. Call MCP tool: `get_trading_analysis(format="summary")` — verify summary includes new fields
4. Call MCP tool: `get_trading_analysis(format="agent")` — verify agent snapshot includes new fields
5. Start frontend dev server, navigate to Performance view, verify card shows `$4.15 / trade` expectancy and `1.24x` profit factor
6. Verify existing `expectancy` and `profit_factor` fields are unchanged (backward compat)
