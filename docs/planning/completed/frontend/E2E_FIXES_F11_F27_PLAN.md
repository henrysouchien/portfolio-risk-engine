# E2E Fixes — F11 + F27

## Context

Final two bugs from the 2026-03-13 E2E audit. F11 is a backend fix (partial risk score computation). F27 is a frontend fix (label historical positions in attribution).

---

## Fix 1: F11 — FIG missing risk score (Backend)

**Problem**: FIG (closed-end fund) shows "—" for risk score. All other positions have scores.

**Root cause**: `enrich_positions_with_risk()` in `services/portfolio_service.py` (lines 1137-1155) requires ALL FOUR metrics (volatility, max_drawdown, beta, weight) to compute a risk score. FIG's FMP profile fetch fails → no factor proxies → excluded from portfolio analysis → no vol/beta/drawdown.

**Fix**: Compute risk score from whatever metrics are available, re-normalizing component weights proportionally. Weight is computable when `gross_exposure` is present and `total_gross > 0`, so most positions will get at least a concentration-based score.

**Codex review**: Approved. Re-normalization math verified correct — when all 4 present, `total_weight=1.0`, formula identical to original. No existing tests break. `risk_score_partial` is a safe additive field (positions route returns raw payload, frontend adapter ignores unknown keys).

### File: `services/portfolio_service.py` (lines 1137-1157)

```python
# Before: all-or-nothing guard
risk_score: Optional[int] = None
if (volatility is not None and max_drawdown is not None
    and beta is not None and weight is not None):
    # ... compute all 4 ...
    risk_score = int(round(vol*0.35 + dd*0.25 + beta*0.20 + conc*0.20))

# After: lenient computation with re-normalized weights
risk_score: Optional[int] = None
risk_score_partial: bool = False
components: list[tuple[float, float]] = []  # (score, component_weight)
if volatility is not None:
    components.append((_clamp((volatility / 0.50) * 100.0), 0.35))
if max_drawdown is not None:
    components.append((_clamp((abs(max_drawdown) / 0.50) * 100.0), 0.25))
if beta is not None:
    components.append((_clamp((abs(beta) / 2.0) * 100.0), 0.20))
if weight is not None:
    components.append((_clamp((weight / 0.25) * 100.0), 0.20))
if components:
    total_weight = sum(w for _, w in components)
    risk_score = int(round(sum(s * w for s, w in components) / total_weight))
    risk_score_partial = len(components) < 4
```

Then update position assignment (line 1157):
```python
position["risk_score"] = risk_score
position["risk_score_partial"] = risk_score_partial if risk_score is not None else False
```

**Backward compatibility**: When all 4 metrics are present, `total_weight = 1.0`, formula is identical to the original. Existing behavior is unchanged for normal equities.

**Edge cases**:
- All metrics missing: `components` empty → `risk_score` stays None (same as before)
- Only weight available (gross_exposure present, total_gross > 0): concentration-based score
- Weight unavailable (no gross_exposure or total_gross = 0): only vol/beta/drawdown contribute
- `risk_score_partial` flag lets frontend optionally distinguish partial scores

---

## Fix 2: F27 — Historical positions unlabeled (Frontend)

**Problem**: Performance Attribution Contributors/Detractors show closed positions (ENB, CBL, IT, PCTY) without distinguishing them from current holdings.

**Approach**: Frontend cross-reference. Stamp `isCurrent` on each attribution row inside `PerformanceViewContainer` (avoids threading a Set prop through `PerformanceView`). No backend changes needed.

**Codex review findings**:
- `PerformanceViewContainer` does NOT currently use `usePositions()` — must add it
- `row.symbol` comes from `security_attribution.name` (backend ticker, uppercase). Normalize both sides with `.trim().toUpperCase()` to avoid casing mismatches.
- Staleness risk: positions and performance are separate 5-min SWR queries with different invalidation triggers. Acceptable — a brief mismatch after selling is harmless.
- Cleanest approach: compute `isCurrent` on each row in `PerformanceViewContainer` at the mapping step, add `isCurrent?: boolean` to type, render from `row.isCurrent` in `AttributionTab`. No need to thread a `Set` prop through `PerformanceView`.

### File A: `frontend/packages/ui/src/components/portfolio/performance/types.ts`

Add `isCurrent` to `PerformanceAttributionStock`:
```typescript
export interface PerformanceAttributionStock {
  symbol: string
  name: string
  contribution: number
  return: number
  weight: number
  targetPrice?: number
  analystRating?: string
  analystCount?: number
  isCurrent?: boolean  // NEW
}
```

### File B: `frontend/packages/ui/src/components/dashboard/views/modern/PerformanceViewContainer.tsx`

1. Add `usePositions` import from `@risk/connectors`
2. Call `usePositions()` to get current holdings
3. Build `currentTickers: Set<string>` from holdings (uppercased)
4. In `mapSecurityToAttributionItem()` (line ~375), stamp `isCurrent`:
```typescript
const { data: positionsData } = usePositions();
const currentTickers = useMemo(() => {
  const tickers = new Set<string>();
  for (const h of positionsData?.holdings ?? []) {
    if (h.ticker) tickers.add(h.ticker.trim().toUpperCase());
  }
  return tickers;
}, [positionsData]);

// In mapSecurityToAttributionItem:
isCurrent: currentTickers.has((item.symbol ?? item.name ?? '').trim().toUpperCase()),
```

### File C: `frontend/packages/ui/src/components/portfolio/performance/AttributionTab.tsx`

No prop changes needed — `isCurrent` is already on each `row` via the type. Update the stock column render (line ~96):
```tsx
render: (row) => (
  <span className="font-medium text-neutral-900">
    {row.symbol}
    {row.isCurrent === false && (
      <span className="ml-1 text-xs text-neutral-400">(closed)</span>
    )}
  </span>
),
```

Note: Check for `=== false` (not `!row.isCurrent`) so that `undefined` (no data) doesn't show "(closed)".

---

## Verification

1. **F11**: Position FIG should show a risk score instead of "—". Other positions should show identical scores to before (re-normalized weights = original weights when all 4 present).
2. **F27**: Performance → Attribution → Contributors/Detractors: closed positions (ENB, CBL, etc.) show "(closed)" label. Current positions show no label.
3. Run `python3 -m pytest tests/ -x -q -k "portfolio_service or enrich_positions"` for F11.
4. Run `cd frontend && npx vitest run` for F27.

## Files Modified

| File | Fix |
|------|-----|
| `services/portfolio_service.py` | F11: Lenient risk score with re-normalized weights |
| `frontend/.../performance/types.ts` | F27: Add `isCurrent` to type |
| `frontend/.../views/modern/PerformanceViewContainer.tsx` | F27: Add `usePositions`, compute `isCurrent` per row |
| `frontend/.../performance/AttributionTab.tsx` | F27: Render "(closed)" when `isCurrent === false` |
