# Organize Peer Comparison Table into Grouped Sections

## Context

The vs Peers tab shows 13 metrics in a flat table with no grouping. Organizing into sections (Valuation, Profitability, Balance Sheet & Returns) makes it scannable by category.

## Metric Keys (from `fmp/tools/peers.py:30-43`)

The backend already emits metrics in a stable order:

```python
DEFAULT_PEER_METRICS = [
    # --- Valuation ---
    "priceToEarningsRatioTTM",        # P/E Ratio
    "priceToBookRatioTTM",            # P/B Ratio
    "priceToSalesRatioTTM",           # P/S Ratio
    "priceToFreeCashFlowRatioTTM",    # P/FCF
    # --- Profitability ---
    "grossProfitMarginTTM",           # Gross Margin
    "operatingProfitMarginTTM",       # Operating Margin
    "netProfitMarginTTM",             # Net Margin
    # --- Balance Sheet & Returns ---
    "debtToEquityRatioTTM",           # Debt/Equity
    "currentRatioTTM",                # Current Ratio
    "dividendYieldTTM",               # Dividend Yield
    # --- Valuation (cont.) ---
    "priceToEarningsGrowthRatioTTM",  # PEG Ratio
    "enterpriseValueMultipleTTM",     # EV/EBITDA
    # --- Returns ---
    "freeCashFlowPerShareTTM",        # FCF/Share
]
```

The order is mostly grouped already but PEG and EV/EBITDA are after the balance sheet metrics. We'll define the grouping in the frontend and sort into groups.

## Changes — Single File

**`frontend/packages/ui/src/components/portfolio/stock-lookup/PeerComparisonTab.tsx`**

### Approach

Define a map from `metric_key` → group label. As we iterate through the rows, track the current group and inject a header `<tr>` when the group changes.

```typescript
const METRIC_GROUP: Record<string, string> = {
  priceToEarningsRatioTTM: "Valuation",
  priceToBookRatioTTM: "Valuation",
  priceToSalesRatioTTM: "Valuation",
  priceToFreeCashFlowRatioTTM: "Valuation",
  priceToEarningsGrowthRatioTTM: "Valuation",
  enterpriseValueMultipleTTM: "Valuation",
  grossProfitMarginTTM: "Profitability",
  operatingProfitMarginTTM: "Profitability",
  netProfitMarginTTM: "Profitability",
  debtToEquityRatioTTM: "Balance Sheet & Returns",
  currentRatioTTM: "Balance Sheet & Returns",
  dividendYieldTTM: "Balance Sheet & Returns",
  freeCashFlowPerShareTTM: "Balance Sheet & Returns",
};

const GROUP_ORDER = ["Valuation", "Profitability", "Balance Sheet & Returns"];
```

### Rendering — sort then inject headers

1. Sort `peerComparisonRows` by group order (preserving within-group API order):

```typescript
const sortedRows = useMemo(() => {
  const groupIndex = (key: string) => {
    const group = METRIC_GROUP[key];
    const idx = group ? GROUP_ORDER.indexOf(group) : GROUP_ORDER.length;
    return idx >= 0 ? idx : GROUP_ORDER.length;
  };
  return [...peerComparisonRows].sort(
    (a, b) => groupIndex(a.metricKey) - groupIndex(b.metricKey)
  );
}, [peerComparisonRows]);
```

2. Render with section headers when group changes:

```tsx
{(() => {
  let lastGroup = "";
  return sortedRows.map((row, index) => {
    const group = METRIC_GROUP[row.metricKey] ?? "Other";
    const showHeader = group !== lastGroup;
    lastGroup = group;
    return (
      <Fragment key={row.metricKey}>
        {showHeader && (
          <tr>
            <td
              colSpan={peerTableTickers.length + 1}
              className="pt-4 pb-2 text-left text-xs font-medium uppercase tracking-wider text-muted-foreground"
            >
              {group}
            </td>
          </tr>
        )}
        {/* existing row rendering */}
      </Fragment>
    );
  });
})()}
```

Uses `<td>` with colspan matching actual columns (`peerTableTickers.length + 1` = Metric column + ticker columns). No `scope` attribute since we're using a single `<tbody>` — keeps it simple. `Fragment` from React (check existing imports, add if needed).

### Edge cases

- Unknown `metric_key` not in `METRIC_GROUP` → assigned to "Other" group, sorted to end
- Empty `peerComparisonRows` → no headers rendered (existing empty state unchanged)
- Single group with all metrics → one header, then all rows
- `failedTickers` display → unchanged, separate section below the table

## What Does NOT Change

- API response — unchanged
- Backend metric order in `fmp/tools/peers.py` — unchanged
- Ranking logic, color coding, value formatting — unchanged
- Container/adapter — no changes
- `helpers.ts` (LOWER_IS_BETTER_METRICS, etc.) — unchanged

## Verification

1. `cd frontend && npx tsc --noEmit --project packages/ui/tsconfig.json` — full tsc, no errors in PeerComparisonTab (pre-existing errors in unrelated files only)
2. Browser: Research → AAPL → vs Peers → metrics grouped under "Valuation", "Profitability", "Balance Sheet & Returns"
3. All 13 metrics visible, valuation metrics together (including PEG and EV/EBITDA which were previously scattered)
4. Ranking badges and color coding work correctly within each group
5. If API ever adds a new metric_key not in METRIC_GROUP, it appears under "Other" at the end
