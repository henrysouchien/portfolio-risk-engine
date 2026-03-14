# Holdings Alert Badge Tooltip

## Context

The Holdings view shows a red pulsing badge on each position's icon with an alert count (e.g., "2"), but no context about *what* triggered the alerts. Users see a number but have to navigate to the Overview Smart Alerts section to understand it. The backend already computes full flag details (message, severity, type) per-ticker during the `/api/positions/holdings` request — it just discards them and only sends the count.

**Goal:** Show a native tooltip on hover with the alert messages (e.g., "AAPL is 25.3% of exposure").

## Approach: Extend Holdings Response (No Extra API Call)

The flags are already computed per-ticker in `routes/positions.py` lines 169-190. Portfolio-level alerts already send `alert_details` (lines 184-187). We mirror the same pattern for position-level alerts.

---

## Changes

### 1. Backend: `routes/positions.py` (~5 lines)

After the existing alert count loop (line 175-180), also collect per-ticker alert details:

```python
# Existing: alert_counts per ticker
alert_counts: Dict[str, int] = {}
alert_details: Dict[str, list] = {}          # NEW
for flag in flags:
    ticker = flag.get("ticker")
    if ticker:
        symbol = str(ticker).strip().upper()
        alert_counts[symbol] = alert_counts.get(symbol, 0) + 1
        alert_details.setdefault(symbol, []).append(     # NEW
            {"severity": flag["severity"], "message": flag["message"]}
        )

# Line 188-190: add details alongside count
for position in payload.get("positions", []):
    sym = str(position.get("ticker", "")).strip().upper()
    position["alerts"] = alert_counts.get(sym, 0)
    position["alert_details"] = alert_details.get(sym, [])   # NEW
```

### 2. Frontend types: `frontend/packages/chassis/src/types/index.ts`

Add `alert_details` to `PositionsMonitorPosition`:

```typescript
alert_details?: Array<{ severity: 'error' | 'warning' | 'info'; message: string }> | null;
```

### 3. Adapter: `frontend/packages/connectors/src/adapters/PositionsAdapter.ts`

Add `alertDetails` to `PositionsHolding` interface and map it in `normalizeHolding()`:

```typescript
// Interface addition:
alertDetails?: Array<{ severity: string; message: string }>;

// In normalizeHolding():
alertDetails: position.alert_details ?? [],
```

### 4. Component: `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx`

**4 touch points** (Codex review identified these):

**a. `Holding` interface (line ~208)** — add `alertDetails`:
```typescript
alertDetails: Array<{ severity: string; message: string }>
```

**b. `HoldingsViewProps` inline type (line ~239)** — add to holdings array item:
```typescript
alertDetails?: Array<{ severity: string; message: string }>;
```

**c. Initial state transform (line ~301)** — map `alertDetails`:
```typescript
alertDetails: holding.alertDetails || [],
```

**d. `useEffect` sync transform (line ~353)** — map `alertDetails`:
```typescript
alertDetails: holding.alertDetails || [],
```

**e. Badge rendering (line ~730)** — add `title` attribute:
```tsx
{holding.alerts > 0 && (
  <div
    className="absolute -top-1 -right-1 w-4 h-4 bg-red-500 rounded-full flex items-center justify-center animate-pulse"
    title={holding.alertDetails?.map(a => a.message).join('\n') || `${holding.alerts} alert(s)`}
  >
    <span className="text-xs text-white font-bold">{holding.alerts}</span>
  </div>
)}
```

Native browser `title` tooltip — no new components, no extra dependencies. Multi-line messages joined with `\n`.

---

## Files

| File | Action |
|------|--------|
| `routes/positions.py` | MODIFY — add `alert_details` dict + set on each position (~5 lines) |
| `frontend/packages/chassis/src/types/index.ts` | MODIFY — add `alert_details` to `PositionsMonitorPosition` (~1 line) |
| `frontend/packages/connectors/src/adapters/PositionsAdapter.ts` | MODIFY — add `alertDetails` to interface + mapping (~2 lines) |
| `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx` | MODIFY — 5 touch points: interface, props type, 2 transforms, badge title (~5 lines) |

## Codex Review (R1)

**FAIL** — 5 findings, all addressed above:
1. **High** — `HoldingsView.tsx` has internal `Holding` interface + `HoldingsViewProps` inline type + 2 transform sites that all need `alertDetails`. Plan originally only mentioned the badge `title`. → Fixed: all 5 touch points now listed in Section 4.
2. **Medium** — Severity not rendered in tooltip. → Accepted: message text is self-descriptive (e.g., "AAPL is 25.3% of exposure"). Severity adds noise in a tooltip.
3. **Medium** — Native `title` tooltip UX limits (no rich formatting, weak mobile). → Accepted as MVP. Can upgrade to custom tooltip component later if needed.
4. **Low** — `severity: string` is loose. → Fixed: using union type `'error' | 'warning' | 'info'` in chassis types.
5. **Low** — No tests. → Accepted: this is a pure data-threading + `title` attribute change. Verified via `pnpm typecheck` + manual browser test.

## Verification

1. `make dev` — start backend
2. `pnpm typecheck` — no TS errors
3. Open Holdings view in browser, hover over a red alert badge
4. Tooltip should show the alert message(s) (e.g., "AAPL is 25.3% of exposure")
5. Positions without alerts — no badge, no tooltip (unchanged behavior)
6. Edge cases: positions with multiple alerts show newline-separated messages
