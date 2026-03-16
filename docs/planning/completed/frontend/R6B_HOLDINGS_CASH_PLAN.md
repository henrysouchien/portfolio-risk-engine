# R6b Fix: Include Cash/Margin in Holdings + Revert Weight Denominator

**Status**: READY TO EXECUTE
**Date**: 2026-03-16
**Source**: R6b from `docs/planning/REVIEW_FINDINGS.md`
**Codex review**: Done — 5 issues found, all addressed below.

---

## Problem

After the R6 fix (`8531a6f3`) changed the holdings table weight denominator from `gross_exposure` to `total_portfolio_value`, the alert and table show different percentages for the same position:

- **Alert** (`core/position_flags.py:125`): `abs(value) / gross_non_cash * 100` → "NVDA is 16.9% of exposure"
- **Table** (`PositionsAdapter.ts:102-107`): `grossExposure / total_portfolio_value * 100` → "NVDA is 21.4%"

Using `gross_exposure` as the weight denominator is correct — it captures all investment positions and excludes cash/margin financing. The R6 fix was wrong — it switched the table to include cash in the denominator. Cash/margin positions are excluded from the holdings table entirely (`positions.py:342-343`), so users can't see what makes up the gap.

## Solution

1. **Include cash/margin in the monitor payload `positions` array** so they appear in the holdings table
2. **Revert the table weight denominator** to `gross_exposure` to match the alerts
3. **Guard downstream consumers** that iterate all positions (enrichment, flags, scenario tools)

---

## Step 1: Backend — Include cash positions in monitor payload

**File**: `core/result_objects/positions.py` — `_build_monitor_payload()`

Currently (lines 341-343), cash positions are filtered out and only used for `cash_value_usd` (line 561). They never appear in the response `positions` array.

**Change — ordering matters**: Keep the existing structure where `processed_positions` is built from `monitor_positions` (non-cash only). Compute `portfolio_totals_usd` from `processed_positions` as today — no guards needed because it only contains investment positions at that point. THEN, after `portfolio_totals_usd` is computed, append cash entries to `processed_positions` before building the final payload. This keeps `gross_exposure` correct by construction — the sum of absolute market values of all investment positions (equities, ETFs, options, futures, bonds), excluding cash/margin financing — without any type-check hacks.

Concrete sequence inside `_build_monitor_payload()`:
1. Lines 341-343: Split `cash_positions` / `monitor_positions` — **unchanged**
2. Lines 348-448: Process `monitor_positions` into `processed_positions` — **unchanged**
3. Lines 450-508: Accumulate `summary_by_currency` — **unchanged**
4. Lines 539-564: Compute `portfolio_totals_usd` from `processed_positions` — **unchanged** (only investment rows exist at this point, no cash/margin)
5. **NEW**: After line 564, loop over `cash_positions` and append simplified entries to `processed_positions`:

Cash entries reuse the same dict shape as investment entries:
- `type`: preserved from raw position (`"cash"`)
- `asset_class`: `"cash"` (must be set explicitly — enrichment skips cash rows so this won't be overwritten)
- `ticker`: preserved (`"CUR:USD"`, `"CUR:GBP"`, etc.)
- `name`: derived from ticker + sign — "Cash (USD)" for positive, "Margin Debt (GBP)" for negative
- `currency`: from position
- `direction`: `"LONG"` if value >= 0, `"SHORT"` if negative (margin debt)
- `quantity` / `shares`: from raw position quantity
- `gross_exposure`: `abs(value)`
- `net_exposure`: `value` (signed)
- `current_price`: `None`
- `entry_price` / `weighted_entry_price`: `None`
- `cost_basis` / `cost_basis_usd`: `None`
- `pnl` / `dollar_pnl` / `pnl_percent` / `pnl_usd`: all `None`
- `pnl_basis_currency`: `None`
- `entry_price_warning`: `False`
- `is_cash_equivalent`: `False` (these ARE cash, not proxies like SGOV)

6. Lines 566-603: Build final payload with `"positions": processed_positions` — now includes both investment and cash/margin rows

**What stays the same** — no new summary fields, no new variables, no guards:
- `cash_value_usd` computation (line 561) — unchanged, still reads from `cash_positions` list
- `total_portfolio_value` (line 562-563) — unchanged
- `summary_by_currency` — unchanged (loop at 450-508 ran before cash was appended)
- `portfolio_totals_usd` — unchanged (loop at 546-557 ran before cash was appended)
- `gross_exposure` is correct by construction: it's the sum of absolute market values of all investment positions (equities, ETFs, options, futures, bonds — everything with market risk). Cash and margin debt are financing entries, not positions with market exposure.

**Update `holdings_count`** (line 580-585): Add `and p.get("type") != "cash"` to the filter.

**Rename** `cash_positions_excluded` (line 587) → `cash_positions_count` (they're included in the payload now, just not in investment summaries). Update the empty payload in `routes/positions.py:94` to match.

## Step 2: Frontend — Revert weight denominator to `gross_exposure`

**File**: `frontend/packages/connectors/src/adapters/PositionsAdapter.ts`

Revert lines 101-112 (the R6 change). Use `gross_exposure` for weight denominator, keep `total_portfolio_value` for the display summary:

```typescript
static transform(payload: PositionsMonitorResponse): PositionsData {
    const grossExposure = toRequiredNumber(
      payload?.summary?.portfolio_totals_usd?.gross_exposure, 0
    );
    const totalPortfolioValue = toRequiredNumber(
      payload?.summary?.portfolio_totals_usd?.total_portfolio_value, 0
    );
    const timestamp = ...;
    const holdings = (payload?.positions ?? []).map((position) =>
      normalizeHolding(position, grossExposure)    // weight denominator = gross investment exposure
    );

    return {
      summary: {
        totalValue: totalPortfolioValue > 0 ? totalPortfolioValue : grossExposure,
        ...
      },
      holdings,
    };
```

This ensures position weights match `position_flags.py`'s `gross_non_cash` denominator. `summary.totalValue` still shows `total_portfolio_value` for the header card.

## Step 3: Backend — Guard enrichment pipeline against cash rows

### 3a: `enrich_positions_with_risk()` — `services/portfolio_service.py`

**Issue** (Codex finding #4): Line 1177 overwrites `asset_class` for every position: `position["asset_class"] = asset_classes_upper.get(ticker, None)`. This would clobber cash rows. Lines 1129-1134 compute `total_gross` from all payload positions — cash would inflate the denominator used for risk weight scoring.

**Fix**: Skip cash rows in three places within this function:
- Line 1055 (default-setting loop): `if position.get("type") == "cash": continue`
- Line 1130 (total_gross accumulation): skip `type == "cash"` entries
- Line 1136 (risk metric assignment loop): `if position.get("type") == "cash": continue`

This is the correct place for a type check because the enrichment function receives the already-assembled payload (which contains both investment and cash/margin rows after Step 1). Unlike `_build_monitor_payload` where ordering solves the problem, enrichment runs after the payload is built.

### 3b: `generate_position_flags()` — `core/position_flags.py`

**Issue** (Codex finding #2): The `monitor_positions` parameter at line 423 iterates all positions from the payload. Cash rows with `cost_basis=None` would trigger false `low_cost_basis_coverage` alerts (line 433-434, 455-458).

**Fix**: At line 427, filter to non-cash before iterating:
```python
for position in monitor_positions:
    if not isinstance(position, dict):
        continue
    if position.get("type") == "cash":
        continue
    total_positions += 1
```

The raw `positions` parameter (line 68) already filters cash at line 82-86 (`non_cash` list). No change needed there — the flags function already operates on `positions` (raw) for concentration and `monitor_positions` (processed) for P&L quality. Just need to skip cash in the `monitor_positions` loop.

### 3c: `is_cash_equivalent` badge — `PositionsAdapter.ts:86` / `HoldingsTable.tsx:179`

**Issue** (Codex finding #3): Setting `is_cash_equivalent: True` on cash entries would render a "Cash Proxy" badge via `isProxy` in `HoldingsTable.tsx:179`. Cash IS cash, not a proxy.

**Fix**: Set `is_cash_equivalent: False` on cash entries in the backend (they ARE cash, not proxies like SGOV). The "Cash Proxy" badge is for investment positions that represent cash equivalents (SGOV, etc.). Actual CUR:* cash rows should NOT show this badge.

## Step 4: Frontend — Cash row rendering in HoldingsTable

**File**: `frontend/packages/ui/src/components/portfolio/holdings/HoldingsTable.tsx`

The table already has `assetClass === "cash"` styling (lines 91-92, 110-111) for the icon/badge. Additional changes:

**Market Value cell** (lines 192-200): Suppress "X shares @ $Y" subtitle for cash:
```tsx
{holding.assetClass !== 'cash' && (
  <p className="text-xs text-neutral-500">
    {holding.shares.toLocaleString(...)} shares @ {formatCurrency(holding.currentPrice)}
  </p>
)}
```

**Negative value styling**: Red text for margin debt:
```tsx
<p className={`font-semibold ${holding.assetClass === 'cash' && holding.marketValue < 0 ? 'text-red-600' : 'text-neutral-900'}`}>
```

**Total Return cell** (lines 218-234): Dash for cash (no P&L):
```tsx
{holding.assetClass === 'cash' ? (
  <span className="text-sm text-muted-foreground">—</span>
) : ( /* existing */ )}
```

**Day Change cell** (lines 236-254): Same dash treatment.

**Volatility cell** (lines 256-263): Already handles zero volatility with "—". Cash will have `volatility: 0`, works as-is.

## Step 5: Frontend — Filter cash from summary metrics and downstream consumers

### 5a: `useHoldingsData.ts` — summary metrics

Lines 82-102: Filter cash from `summaryMetrics` so "Invested Positions" card stays correct:
```typescript
const invested = holdings.filter(h => h.assetClass !== 'cash');
const totalValue = invested.reduce((sum, h) => sum + h.marketValue, 0);
// ... rest uses invested
totalPositions: invested.length,
```

### 5b: `DashboardHoldingsCard.tsx` — holdings count + top holdings

Line 161-163: Exclude cash from count:
```typescript
h => h.shares !== 0 && h.type !== 'option' && h.type !== 'cash'
```

Line 65-68: `topHoldings` sorts by weight and takes top 10. Cash positions will have weight relative to `gross_exposure`. This is fine — if margin debt is 20% of gross exposure, showing it in top holdings is informative. **No change needed** — cash rows sort naturally.

### 5c: `useScenarioState.ts` — scenario tools

**Issue** (Codex finding #5): Line 126-128 maps ALL `positionsData.holdings` into `initialPositions` for stress test / what-if / optimization tools. Cash rows would leak into optimization inputs.

**Fix**: Filter cash before mapping:
```typescript
const initialPositions = useMemo(
    () =>
      (positionsData?.holdings ?? [])
        .filter((h) => h.type !== 'cash')
        .map((holding) => ({ ... })),
    [positionsData],
);
```

## Step 6: Tests

**Backend** (`tests/unit/test_position_result.py`):
- Update `test_to_monitor_view_total_portfolio_value_includes_cash` — verify cash positions now appear in `payload["positions"]`
- Add test: cash entry has correct shape (`type: "cash"`, P&L fields `None`, `is_cash_equivalent: False`)
- Add test: margin debt has `direction: "SHORT"`, descriptive name, negative `net_exposure`
- Verify `portfolio_totals_usd.gross_exposure` still excludes cash
- Verify `holdings_count` excludes cash

**Backend** (`tests/core/test_position_flags.py`):
- Add test: cash rows in `monitor_positions` don't inflate `low_cost_basis_coverage` count

---

## Verification

After fix:
1. Alert "NVDA is X% of exposure" matches table weight column X%
2. Cash/margin rows visible in holdings table with labels ("Cash (USD)" / "Margin Debt (GBP)")
3. Margin debt rows show red negative values, dashes for P&L/return columns
4. "Invested Positions" summary card shows investment-only (excludes cash/margin financing) totals
5. Holdings count excludes cash
6. `portfolio_totals_usd.gross_exposure` in API response remains investment-only (excludes cash/margin financing)
7. Scenario tools (stress test, what-if, optimization) don't receive cash rows
8. No false `low_cost_basis_coverage` alerts from cash rows
9. No "Cash Proxy" badge on actual cash rows (only on SGOV etc.)
