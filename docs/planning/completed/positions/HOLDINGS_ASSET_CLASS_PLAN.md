# Holdings View — `assetClass` Enrichment

## Context

The Holdings view (`HoldingsView.tsx`) uses `assetClass` for color-coded styling (blue for equities, emerald for bonds, orange for commodities, etc.) but the field is never populated from the backend. It defaults to `"Equity"` for every position, making the color coding useless. The `PositionsHolding` interface in `PositionsAdapter.ts` doesn't declare `assetClass`, and `normalizeHolding()` doesn't map it.

The backend already computes `asset_classes` per-ticker during `enrich_positions_with_risk()` via `analyze_portfolio()` → `risk_result.analysis_metadata['asset_classes']` (line 941 of `portfolio_service.py`). The data is there — it just isn't threaded to individual position dicts.

**Goal:** Thread `asset_class` from the existing risk enrichment to each position dict, map it in the adapter, and expose it to the Holdings view — so positions show correct asset class colors.

---

## Canonical Asset Classes

From `portfolio_risk_engine/constants.py`:
- `equity`, `bond`, `real_estate`, `commodity`, `crypto`, `cash`, `mixed`, `unknown`

Display names from `ASSET_CLASS_DISPLAY_NAMES`: `Equity`, `Fixed Income`, `Real Estate`, `Commodities`, `Cryptocurrency`, `Cash`, `Mixed Assets`, `Other`.

Note: These are **asset classes**, not security types. ETFs are classified by their underlying asset class (e.g., SPY → `equity`, TLT → `bond`, GLD → `commodity`).

---

## Changes

### 1. Backend: Thread `asset_class` in `enrich_positions_with_risk()` (~3 lines)

**File:** `services/portfolio_service.py`

After `risk_result = self.analyze_portfolio(portfolio_data)` (line 941), extract `asset_classes` and build an uppercase-keyed lookup (both **outside** the per-position loop):

```python
asset_classes = risk_result.analysis_metadata.get('asset_classes', {})
asset_classes_upper = {k.upper(): v for k, v in asset_classes.items()}
```

Then **inside** the per-position loop (lines 982-1020), after setting `max_drawdown` (line 1020), add:

```python
position["asset_class"] = asset_classes_upper.get(ticker, None)
```

Note: `get_tickers()` preserves key casing from `portfolio_input`, and `get_full_classification()` preserves incoming keys. While most paths uppercase tickers, this is not guaranteed — so we normalize the lookup dict to uppercase to safely match `ticker` (uppercased at line 983).

### 2. Frontend: Add `asset_class` to `PositionsMonitorPosition` type

**File:** `frontend/packages/chassis/src/types/index.ts`

Add to `PositionsMonitorPosition` interface (after `max_drawdown` on line 124, alongside other risk-enrichment fields):
```typescript
asset_class?: string | null;
```

### 3. Frontend: Add `assetClass` to `PositionsHolding` + mapping

**File:** `frontend/packages/connectors/src/adapters/PositionsAdapter.ts`

Add to `PositionsHolding` interface (after `sector?: string;` on line 15):
```typescript
assetClass?: string;
```

Add to `normalizeHolding()` return object (after `sector:` line 82):
```typescript
assetClass: toOptionalString(position.asset_class),
```

### 4. Update color mapping in `HoldingsView.tsx`

**File:** `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx`

There are **two** color mappings at lines 708-716 that both check for `"US Equity"`, `"US ETF"`:

1. **Background gradient** (lines 708-710) — the card icon container background
2. **Icon text color** (lines 712-715) — the `SectorIcon` color inside the container

Update **both** to match canonical asset class values, aligned with `ASSET_CLASS_COLORS` from `portfolio_risk_engine/constants.py`:

**Background gradient (lines 708-710):**
```typescript
holding.assetClass === "equity" ? 'bg-gradient-to-br from-blue-100 to-blue-200' :
holding.assetClass === "bond" ? 'bg-gradient-to-br from-emerald-100 to-emerald-200' :
holding.assetClass === "real_estate" ? 'bg-gradient-to-br from-amber-100 to-amber-200' :
holding.assetClass === "commodity" ? 'bg-gradient-to-br from-orange-100 to-orange-200' :
holding.assetClass === "crypto" ? 'bg-gradient-to-br from-purple-100 to-purple-200' :
holding.assetClass === "cash" ? 'bg-gradient-to-br from-gray-100 to-gray-200' :
holding.assetClass === "mixed" ? 'bg-gradient-to-br from-neutral-100 to-neutral-200' :
'bg-gradient-to-br from-neutral-100 to-neutral-300'
```

**Icon text color (lines 712-715):**
```typescript
holding.assetClass === "equity" ? 'text-blue-600' :
holding.assetClass === "bond" ? 'text-emerald-600' :
holding.assetClass === "real_estate" ? 'text-amber-600' :
holding.assetClass === "commodity" ? 'text-orange-600' :
holding.assetClass === "crypto" ? 'text-purple-600' :
holding.assetClass === "cash" ? 'text-gray-600' :
holding.assetClass === "mixed" ? 'text-neutral-600' :
'text-neutral-500'
```

Update the default assignment at lines 284 and 336. Currently `assetClass: holding.assetClass || "Equity"`. Change to:
```typescript
assetClass: holding.assetClass || "unknown"
```

This avoids misclassifying positions as equities when `asset_class` is absent (e.g., risk enrichment fails — it's wrapped in try/except and silently skipped on error per `routes/positions.py:157`).

---

## Files to Modify

| File | Change | ~Lines |
|------|--------|--------|
| `services/portfolio_service.py` | Extract `asset_classes` from risk result, set on each position | +3 |
| `frontend/packages/chassis/src/types/index.ts` | Add `asset_class` to `PositionsMonitorPosition` | +1 |
| `frontend/packages/connectors/src/adapters/PositionsAdapter.ts` | Add `assetClass` to interface + mapping | +2 |
| `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx` | Update background + icon color mappings to canonical values, default to `"unknown"` | ~16 changed |

---

## Edge Cases

- **Risk enrichment failure**: `enrich_positions_with_risk()` is wrapped in try/except in `routes/positions.py:157`. If it fails, no positions get `asset_class`. The adapter returns `undefined` via `toOptionalString()`, and `HoldingsView` defaults to `"unknown"` — gray styling, which is correct.
- **Futures/options**: Classified as `commodity` or `equity` by `SecurityTypeService` depending on underlying. Works correctly.
- **Cash positions (CUR:XXX)**: Classified as `cash`. Will get gray styling.

---

## Verification

1. `python3 -m pytest tests/ -x -v` — no regressions
2. Start backend, load Holdings view in browser
3. Verify positions show varied asset class colors (not all blue/equity)
4. Check a bond position shows emerald/green, a commodity shows orange, cash shows gray, crypto shows purple, etc.
