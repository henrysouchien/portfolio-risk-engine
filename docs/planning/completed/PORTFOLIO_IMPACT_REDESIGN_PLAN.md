# Portfolio Impact Tab — Investor-Oriented Redesign

## Context
The Portfolio Impact tab currently shows developer-facing UI ("Build what-if delta payloads with string percentages"), requires a manual "Run Portfolio Fit" button click before showing anything, and has a sparse empty state. An investor looking at a stock wants to immediately understand: "What happens to my portfolio if I add this?"

## Target Layout

**Section 1 — Position Sizing (always visible):**
- Title: "Add to Portfolio" (not "Position Sizing")
- Show portfolio value + stock price (compact, one line)
- Size selector buttons (1%, 2.5%, 5%) — selecting one **auto-runs** the what-if analysis
- For each size, show inline: dollar amount and estimated shares (e.g., "2.5% = $3,079 ≈ 12 shares")
- Guard: if `selectedStock.price <= 0`, show 0 shares. If `portfolioValue <= 0`, show $0 and 0 shares. These edge cases display as zeros, not "N/A" (consistent with the formula output).

**Section 2 — Impact Analysis (auto-triggered on size select):**
- Before/After risk metrics table (keep current — it's useful)
- Risk checks (Pass/Fail) — keep but make more compact inline badges
- Loading spinner while analysis runs
- Small "Re-run" link/button for retry in case of errors or stale data (replaces the big "Run Portfolio Fit" button)

**Section 3 — Trade Preview (appears after analysis):**
- Clean trade summary: ticker, side (BUY), shares, dollar amount, reference price
- Label: "Trade Summary" (not "Trade Preview (MVP)")
- "Preview Trade" button stays

## Implementation

### Step 1: Auto-run on size selection
**File:** `frontend/.../StockLookupContainer.tsx`

Add a `useEffect` that triggers `handleRunPortfolioFit()` when `portfolioFitSize` changes AND a stock is selected AND portfolio context is ready:

```typescript
// Derive a scalar readiness signal — don't depend on the full currentPortfolio object
// Gate on portfolio ID existence — matches what-if hook's execution condition
// (zero-value portfolios with valid ID still run analysis)
const portfolioReady = Boolean(currentPortfolio?.id)

// Use a ref for the handler to avoid re-firing when runScenario's callback identity changes
// (runScenario is recreated on every currentPortfolio change, which would cause infinite re-runs)
const runPortfolioFitRef = useRef(handleRunPortfolioFit)
runPortfolioFitRef.current = handleRunPortfolioFit

useEffect(() => {
  if (selectedSymbol && portfolioFitSize && portfolioReady) {
    runPortfolioFitRef.current()
  }
}, [portfolioFitSize, selectedSymbol, portfolioReady, portfolioId])
```

Where `portfolioId` is derived as:
```typescript
const portfolioId = currentPortfolio?.id ?? ''
```

**Key design decisions:**
- `portfolioReady` gates on `Boolean(currentPortfolio?.id)` — matches the what-if hook's execution condition. Handles bootstrap (object exists but ID not yet set) and zero-value portfolios correctly.
- The effect fires on stock selection regardless of active tab — this is intentional **prefetch** so results are ready when the user clicks Portfolio Impact
- `portfolioId` is a scalar string — triggers re-run when user switches portfolios (ready→ready transition that portfolioReady alone wouldn't catch)
- `runPortfolioFitRef` stabilizes the handler reference — `handleRunPortfolioFit` depends on `runScenario` which is recreated on every `currentPortfolio` change. Without the ref, the effect would re-fire on every portfolio refresh.
- Effect deps are only scalars: `portfolioFitSize` (number), `selectedSymbol` (string), `portfolioReady` (boolean), `portfolioId` (string)
- Stale result clearing happens **synchronously** in two places:
  1. **`handlePortfolioFitSizeChange`** (line 408): add `setPortfolioFitScenarioName(null)` alongside existing `setTradePreview(null)` — prevents flash on size change
  2. **`handleSelectStock`** (line 348): add `setPortfolioFitScenarioName(null)` and `setTradePreview(null)` — prevents flash when switching stocks while prior analysis is visible
  Both clear before render since state updates batch in the same handler.

This replaces the manual button click. The effect fires on stock selection, size change, AND when portfolio data first becomes available.

### Step 2: Redesign PortfolioFitTab layout
**File:** `frontend/.../stock-lookup/PortfolioFitTab.tsx`

**Section 1 — "Add to Portfolio" card:**
- Title: "Add to Portfolio"
- Subtitle line: `Portfolio: $123,174 · AAPL: $247.99`
- Size buttons in a row, each with dollar + share estimate below:
  ```
  [  1%  ]    [ 2.5% ]    [  5%  ]
  $1,232       $3,079       $6,159
  ~5 shares    ~12 shares   ~25 shares
  ```
- Share calc: `selectedStock.price > 0 ? Math.floor(dollars / selectedStock.price) : 0`
- No "Build what-if delta payloads" text
- No big "Run Portfolio Fit" button (auto-triggered)
- Small muted "Re-run analysis" text button for manual retry (for error recovery / stale data)

**Section 2 — Impact Analysis:**
- Loading: inline spinner + "Analyzing impact..." text (replaces big spinner)
- Error: compact red inline message
- Results: keep the before/after 4-column metrics table
- Risk checks: compact — two inline badges (✓ Risk / ✗ Beta) instead of two full rows
- Remove "What-If Complete" badge

**Section 3 — Trade Preview:**
- Rename "Trade Preview (MVP)" → "Trade Summary"
- Keep the grid of trade details
- "Preview Trade" button stays

### Step 3: Compute share estimates in the component
**File:** `frontend/.../stock-lookup/PortfolioFitTab.tsx`

```typescript
const sizeDetails = portfolioFitSizeOptions.map(size => {
  const dollars = portfolioValue * size / 100
  const shares = selectedStock.price > 0 ? Math.floor(dollars / selectedStock.price) : 0
  return { size, dollars, shares }
})
```

### Step 4: Clean up props
**File:** `frontend/.../stock-lookup/types.ts`

`onRunPortfolioFit` prop stays in the interface (for the retry button) but is no longer the primary trigger.

**File:** `frontend/.../StockLookup.tsx`

Keep passing `onRunPortfolioFit` to PortfolioFitTab (used for retry). No changes needed here beyond what's already wired.

## Files Changed

| File | Changes |
|------|---------|
| `StockLookupContainer.tsx` | Add useEffect for auto-run with portfolio readiness gate |
| `PortfolioFitTab.tsx` | Full layout redesign: "Add to Portfolio", inline sizing, compact analysis, clean labels |
| `types.ts` | No changes needed (onRunPortfolioFit stays for retry) |
| `StockLookup.tsx` | No changes needed (props already wired) |

2 production files + test coverage. No backend changes.

**Tests to add** (in existing or new test file):
- Auto-run does NOT fire during bootstrap (mock currentPortfolio = { id: undefined } or {}), only after real ID is set
- Auto-run fires once when portfolioReady becomes true
- Size change triggers re-run (mock runScenario, verify called with new size)
- Size change causes old analysis/trade preview to disappear while new run is pending
- Unrelated portfolio object refresh does NOT retrigger effect (ref pattern works)
- Portfolio switch (different portfolioId, both ready) triggers re-run
- Stock switch clears old analysis immediately (no one-frame flash of previous stock's results)

## Verification
1. Load Stock Lookup → select AAPL → click Portfolio Impact tab
2. Should see "Add to Portfolio" with portfolio value, stock price, size buttons with dollar/share estimates
3. Default 2.5% auto-runs: impact analysis appears without clicking anything
4. Click 1% or 5% → analysis re-runs automatically
5. Before/after metrics table renders correctly
6. "Re-run analysis" retry link works
7. Trade preview works after analysis completes
8. Edge case: portfolioValue = 0 → dollar/share estimates show appropriately, no crash
9. Size change clears stale results immediately (no flash of old metrics with new label)
10. Auto-run does NOT fire before portfolio data is loaded
