# Merge P/E Metrics — Forward Default, TTM Fallback

## Context

The peer comparison table shows both "P/E (TTM)" and "Fwd P/E" as separate rows. We want one "P/E" row that defaults to forward P/E, falls back to TTM P/E per-ticker when forward is unavailable.

## Approach

**Backend**: No changes. Both `priceToEarningsRatioTTM` and `forwardPE` stay in `DEFAULT_PEER_METRICS`.

**Frontend**: Before the ranking/grouping logic in `PeerComparisonTab.tsx`, preprocess the comparison array: merge the two P/E rows into one row keyed as `priceToEarningsRatioTTM` (reusing the existing key) with label "P/E". Per-ticker, prefer forward value, fall back to TTM. Store the source per-ticker on the row itself as a `_peSource` property.

## Changes — Frontend Only

### 1. `PeerComparisonTab.tsx` — preprocess comparison before ranking

Before the existing `peerComparison.comparison.map(...)` in the `peerComparisonRows` memo, add a preprocessing step:

```typescript
// Preprocess: merge forward + TTM P/E into one row
const preprocessed = useMemo(() => {
  if (!peerComparison) return [];
  const rows = [...peerComparison.comparison];

  const ttmIdx = rows.findIndex(r => r.metric_key === "priceToEarningsRatioTTM");
  const fwdIdx = rows.findIndex(r => r.metric_key === "forwardPE");

  if (ttmIdx < 0 && fwdIdx < 0) return rows;

  const ttmRow = ttmIdx >= 0 ? rows[ttmIdx] : null;
  const fwdRow = fwdIdx >= 0 ? rows[fwdIdx] : null;

  // Build merged row, reusing priceToEarningsRatioTTM key
  const merged: Record<string, unknown> = {
    ...(ttmRow ?? fwdRow),
    metric_key: "priceToEarningsRatioTTM",
    metric: "P/E",
  };
  const peSource: Record<string, string> = {};

  for (const ticker of peerTableTickers) {
    const fwdVal = fwdRow ? toNumericValue(fwdRow[ticker]) : null;
    const ttmVal = ttmRow ? toNumericValue(ttmRow[ticker]) : null;

    if (fwdVal !== null && fwdVal > 0) {
      merged[ticker] = fwdVal;
      peSource[ticker] = "fwd";
    } else if (ttmVal !== null && ttmVal > 0) {
      merged[ticker] = ttmVal;
      peSource[ticker] = "ttm";
    } else {
      merged[ticker] = null;
      peSource[ticker] = "";
    }
  }

  // Attach source map to the row for renderer access
  merged._peSource = peSource;

  // Replace TTM row with merged, remove fwd row
  const result = rows.filter(
    (_, i) => i !== ttmIdx && i !== fwdIdx
  );
  // Insert merged at the position of the earlier of the two original rows
  const insertAt = Math.min(
    ttmIdx >= 0 ? ttmIdx : Infinity,
    fwdIdx >= 0 ? fwdIdx : Infinity
  );
  result.splice(Math.min(insertAt, result.length), 0, merged);

  return result;
}, [peerComparison, peerTableTickers]);
```

Then the existing `peerComparisonRows` memo maps from `preprocessed` instead of `peerComparison.comparison`.

### Key design decisions:

- **Reuses `priceToEarningsRatioTTM` key** — stays in `METRIC_GROUP` as Valuation, stays in `LOWER_IS_BETTER_METRICS` and `NON_POSITIVE_EXCLUDES_RANKING`. No new key needed.
- **Source on the row** (`_peSource` property) — not in a ref, derived from the same data, consistent with render.
- **Inserted at original position** — preserves table ordering, no `unshift`.
- **`forwardPE` stays in METRIC_GROUP** as safety — if preprocessing fails for some reason, it falls to "Other" instead of disappearing. But normally it's filtered out.
- **All-invalid case**: if both sources are null/non-positive for every ticker, the merged row has all nulls → renders as "—" for every cell. This is correct — "P/E: —" is better than no P/E row.

### 2. Rendering — source indicator

In the cell renderer, for the `priceToEarningsRatioTTM` row, access `_peSource`:

```tsx
{entry.metricKey === "priceToEarningsRatioTTM" && entry.row._peSource && (
  <span className="text-[10px] text-muted-foreground ml-1">
    {(entry.row._peSource as Record<string, string>)[ticker] === "fwd" ? "(fwd)" :
     (entry.row._peSource as Record<string, string>)[ticker] === "ttm" ? "(ttm)" : ""}
  </span>
)}
```

### 3. `helpers.ts` — no changes needed

`priceToEarningsRatioTTM` is already in:
- `LOWER_IS_BETTER_METRICS` ✅
- `NON_POSITIVE_EXCLUDES_RANKING` ✅
- `formatPeerMetricValue` handles it (2 decimal places) ✅

### 4. `METRIC_GROUP` — keep both keys as safety

```typescript
priceToEarningsRatioTTM: "Valuation",  // Existing — now holds merged P/E
forwardPE: "Valuation",                // Safety — if preprocessing fails, shows in Valuation not "Other"
```

Normally `forwardPE` is filtered out by preprocessing. But if preprocessing somehow misses, it falls to Valuation group instead of "Other".

## What Does NOT Change

- Backend — no changes
- `helpers.ts` — no changes (existing key reused)
- PEG ratio — unchanged
- Other metrics — unchanged

## Verification

1. Browser: AAPL → vs Peers → single "P/E" row in Valuation, "(fwd)" labels on peers with analyst coverage
2. Mixed sources: some peers "(fwd)", others "(ttm)"
3. Ranking correct on merged values (lower is better, non-positive excluded)
4. No "Other" group at bottom
5. No duplicate P/E rows
