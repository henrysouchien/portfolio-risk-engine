# Onboarding Wizard Plan
**Status:** NOT STARTED
**Date:** 2026-03-10

## Goal

Guided first-run experience that gets a new user from "I just set this up" to "I can see my portfolio" in under 2 minutes. Adapts the finance-cli OnboardingWizard pattern to our multi-provider architecture.

---

## Design Principles

1. **Institution-first** — User picks their broker ("I have Schwab"), we route to the right provider behind the scenes. They shouldn't need to know what Plaid/SnapTrade/Flex is.
2. **Two paths** — "Connect your brokerage" (live data) or "Import a CSV" (no API needed). Same as finance-cli's dual-option welcome.
3. **Progressive disclosure** — Don't show all 5 providers. Show the top brokerages + "Other" → we figure out the provider routing.
4. **Immediate value** — After connection/import, auto-navigate to the dashboard with data loaded. No extra steps.
5. **Dismissible** — User can skip and land on `EmptyPortfolioLanding` (with inline connection options). Once a portfolio exists, subsequent account management is via Settings → Connections.
6. **Shared components** — Broker selection and connection flows are shared between the wizard and Settings → Connections. Extract from `AccountConnections` first, then compose into both surfaces.

---

## User Flow

```
┌─────────────────────────────────────────────┐
│  Step 1: WELCOME                            │
│                                             │
│  "Get started with your portfolio"          │
│                                             │
│  ┌──────────────┐  ┌──────────────┐        │
│  │ Connect      │  │ Import       │        │
│  │ a brokerage  │  │ a CSV        │        │
│  └──────────────┘  └──────────────┘        │
│                                             │
│  [ Skip for now ]                           │
└─────────────────────────────────────────────┘
          │                    │
          ▼                    ▼
┌─────────────────┐  ┌──────────────────────┐
│  Step 2a:       │  │  Step 2b:            │
│  SELECT BROKER  │  │  CSV IMPORT          │
│  (shared comp)  │  │                      │
│                 │  │  Select broker: [▼]  │
│  Popular:       │  │  Upload file: [📁]   │
│  ○ Schwab       │  │                      │
│  ○ Fidelity     │  │  [ Import ]          │
│  ○ Vanguard     │  │                      │
│  ○ IBKR         │  └──────────────────────┘
│  ○ E*Trade      │            │
│  All: [...]     │            │
└─────────────────┘            │
          │                    │
          ▼                    │
┌─────────────────────────┐    │
│  Step 3a:               │    │
│  CONNECT (shared comp)  │    │
│                         │    │
│  Provider-routed:       │    │
│  - Plaid hosted link    │    │
│  - SnapTrade hosted UI  │    │
│  - Schwab: CLI guide    │    │
│  - IBKR: Gateway guide  │    │
│                         │    │
│  [ I've completed it ]  │    │
└─────────────────────────┘    │
          │                    │
          ▼                    ▼
┌─────────────────────────────────┐
│  Step 4: PROCESSING             │
│                                 │
│  ⟳ Syncing your positions...   │
└─────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────┐
│  Step 5: DONE                   │
│                                 │
│  ✓ Your portfolio is ready      │
│    47 positions loaded          │
│                                 │
│  [Go to Dashboard]              │
│  [Connect another account]      │
└─────────────────────────────────┘
```

---

## Existing Code to Leverage

### Already Built (reuse, don't rewrite)

| What | Where | How to reuse |
|------|-------|-------------|
| **Institution grid + selection modal** | `AccountConnections.tsx:540-580` | Extract into shared `<InstitutionPicker>` |
| **Institution config list** (IDs, names, logos, popular flags) | `providers.ts:121` → `INSTITUTION_CONFIG` | Import directly — single source of truth for broker list |
| **Provider routing API** | `provider_routing_api.py` → `GET /api/provider-routing/institution-support/{slug}` | Extend to include Schwab/IBKR flow types |
| **Plaid Link flow** | `AccountConnectionsContainer.tsx` → `usePlaid()`, `useConnectAccount()` | Reuse hooks directly |
| **SnapTrade connection URL** | `routes/snaptrade.py:512`, `brokerage/snaptrade/connections.py` | Call existing API |
| **Query keys** | `queryKeys.ts:198-219` | Full invalidation list |
| **Welcome card** | `ModernDashboardApp.tsx:322-348` | Replace with wizard trigger |

### Backend Gaps (need new work)

| Gap | Current State | What's Needed |
|-----|--------------|---------------|
| **Provider routing doesn't know Schwab/IBKR** | Only returns `snaptrade_supported`/`plaid_supported` | Add `schwab_supported`, `ibkr_supported`, `flow_type` field |
| **Schwab OAuth is CLI-only** | `schwab_login()` in `client.py` opens local browser, saves to `~/.schwab_token.json` | For MVP: guide user to run CLI command. Future: web-based OAuth callback route |
| **IBKR is server-local probe** | `routing.py:289` tests Gateway connection | For MVP: guide user to start Gateway. Expose `GET /api/ibkr/status` |
| **SnapTrade doesn't take institution slug** | `connections.py:22` passes `broker=None` | Pass institution hint so SnapTrade pre-selects the right broker |
| **No onboarding status endpoint** | First-run detection only via `!currentPortfolio` | New endpoint aggregating connection + position state |
| **No per-connection status** | Plaid tracks per-item, SnapTrade per-auth | Unified connection status shape |

---

## Step Details

### Step 1: Welcome

Two-card grid. Shown when:
- No portfolio exists (initializer fetch returns 404), AND
- User hasn't completed or dismissed onboarding (see localStorage contract below)

**localStorage contract:**
- `onboarding_completed_{userId}` — Set to `"true"` when wizard completes successfully (user clicks "Go to Dashboard"). Once set, the **wizard** is NEVER shown again. If the portfolio later becomes empty (e.g., provider disconnected, data expired), the user sees `EmptyPortfolioLanding` (not the wizard) — a purpose-built reconnection UI with inline `<InstitutionPicker>` + `<ConnectionFlow>`. The dashboard itself cannot handle empty portfolios (see gate logic below).
- `onboarding_dismissed_{userId}` — Set to `"true"` when user clicks "Skip for now". Shows `EmptyPortfolioLanding` instead of wizard. Can be cleared to re-show wizard.
- **Gate logic in `PortfolioInitializer`:**
  - 404 error + `onboarding_completed` NOT set → `onboardingFallback` (wizard or empty landing)
  - 404 error + `onboarding_completed` IS set → `EmptyPortfolioLanding` (NOT dashboard children — dashboard hooks fire queries without `enabled: !!currentPortfolio` guards, producing error panels)
  - 200 + empty holdings + `onboarding_completed` NOT set → `onboardingFallback`
  - 200 + empty holdings + `onboarding_completed` IS set → `EmptyPortfolioLanding` (NOT dashboard children — backend `validation_service.py:138` rejects empty portfolios, so `usePerformance`/`useRiskAnalysis` error, and containers like `PortfolioOverviewContainer.tsx:164` render error panels instead of empty state)
  - 200 + non-empty holdings → render children (normal dashboard)
  - Other errors (500, network) → `errorFallback` always (regardless of localStorage)

**Bootstrap gate problem:** `ModernDashboardApp.tsx` is wrapped in `PortfolioInitializer` (line 491), which blocks rendering children until it finds or fetches a portfolio. On true first-run with no connected brokerages, the initializer's `getPortfolio()` call fails → renders error UI at `PortfolioInitializer.tsx:172`. The wizard never renders because it's inside the blocked children.

**Solution — modify `PortfolioInitializer` to detect onboarding state:**

The current initializer treats all errors the same (line 172). We need three branches:
- **No portfolio (onboarding case):** Backend returns 404, or 200 with empty holdings → show onboarding UI
- **Existing connections but no portfolio yet:** Connected providers exist but portfolio not ready → show onboarding
- **Backend error:** Network failure, 500, etc. → show error UI with retry

Approach: Modify `PortfolioInitializer` to add an `onboardingFallback` prop:

```tsx
<PortfolioInitializer
  onboardingFallback={
    !isDismissed
      ? <OnboardingWizard onDismiss={() => setDismissed(true)} />
      : <EmptyPortfolioLanding />
  }
  errorFallback={(error) => <DefaultErrorUI error={error} />}
>
```

**PortfolioInitializer changes:**
1. Backend `GET /api/portfolios/{name}` returns HTTP `404` (not 500) when no portfolio exists. The current handler at `app.py:3770` has a blanket `except Exception → 500` catch-all that swallows `PortfolioNotFoundError`. Fix: add an explicit `except PortfolioNotFoundError` clause BEFORE the generic `except Exception`, raising `HTTPException(status_code=404, detail={"message": "Portfolio not found", "error_code": "NOT_FOUND"})`. `PortfolioNotFoundError` is already raised by `database_client.py:687` (`get_portfolio_positions()`) and propagates through `PortfolioManager.load_portfolio_data()`. No error body parsing needed on the frontend — `HttpClient.ts:153` preserves HTTP status on thrown errors.
2. `PortfolioInitializer.tsx:108` — on query error, check HTTP status AND localStorage:
   - `error.status === 404` AND `onboarding_completed_{userId}` NOT set → render `onboardingFallback`
   - `error.status === 404` AND `onboarding_completed_{userId}` IS set → render `EmptyPortfolioLanding` (NOT dashboard children). The dashboard mounts portfolio-dependent hooks (`useRiskAnalysis`, `usePerformance` via `useDataSource`) that fire queries without `enabled: !!currentPortfolio` guards. Without a current portfolio, these hooks would error and surface error panels instead of an empty state. `EmptyPortfolioLanding` provides a clean reconnection UI with inline `<InstitutionPicker>` + `<ConnectionFlow>`.
   - Other errors (500, network, undefined status) → render `errorFallback` always (regardless of localStorage)
   - No error-body parsing required — keeps the gate simple and transport-agnostic.
3. Also handle successful-but-empty: In the `queryFn`, when the backend returns a portfolio with empty `holdings` array → throw a sentinel error (e.g., `new Error('empty_portfolio')` with `status: 404` property) so the query enters the error branch, which routes through the same 404 + localStorage logic in step 2. This means:
   - Empty holdings + `onboarding_completed` NOT set → `onboardingFallback` (wizard)
   - Empty holdings + `onboarding_completed` IS set → `EmptyPortfolioLanding` (reconnection UI)

   The dashboard cannot handle empty portfolios: `validation_service.py:138` rejects them, `usePerformance`/`useRiskAnalysis` hooks error out, and containers (`PortfolioOverviewContainer.tsx:164`, `RiskAnalysisModernContainer.tsx:374`) render error panels. Routing to `EmptyPortfolioLanding` in both cases avoids this.
4. `GET /api/onboarding/status` — used by wizard and EmptyPortfolioLanding internally to show existing connections and guide the user. NOT used for the initializer gate — that uses the simpler 404/empty detection.

**Wizard completion — deferred exit:**
The wizard's Done screen (Step 5) must remain visible until the user clicks "Go to Dashboard". If we `resetQueries` immediately on success, `PortfolioInitializer` stops rendering the wizard (switches to children) and the completion screen vanishes.

Solution: the wizard manages a two-phase completion:
1. **Phase A (on connection success):** Call `manager.refreshHoldings()` directly or CSV activation. **Check result before writing to store:** If `portfolio` is non-null with non-empty `holdings` → wrap and write: `PortfolioRepository.add({ ...portfolio, portfolio_name: 'CURRENT_PORTFOLIO' })` + `setCurrent()`, set `wizardComplete=true`, show Done screen with position count. Do NOT reset queries yet.

   **Refresh failure guard:** If `refreshHoldings()` returns `{portfolio: null, error}` (e.g., provider connected but positions not synced yet, or provider returned empty data), do NOT call `add()/setCurrent()`. The current provider refresh routes raise on empty data: `position_service.py:1093` raises `ValueError` on empty holdings, which Plaid (`plaid.py:1058`) and SnapTrade (`snaptrade.py:875`) routes turn into 500s. `PortfolioManager.ts:721` then returns `{portfolio: null, error: 'No provider data'}`. This means the wizard gets an error, not empty holdings.

   Instead of treating this as a fatal error, show a "waiting for positions" state: "Your account is connected but positions haven't synced yet. This can take a few minutes." with a "Retry" button that re-calls `refreshHoldings()`. After 3 retries, show "Positions may take time to sync. You can continue to the dashboard and check back later." with "Go to Dashboard anyway" (sets `onboarding_completed`, does NOT call `add()/setCurrent()`, resets queries → initializer runs gate logic → 404/empty → `EmptyPortfolioLanding`).

   The key store-write invariant: `add()/setCurrent()` is ONLY called when `portfolio?.holdings?.length > 0`. Once `currentPortfolio` is set in the store, `PortfolioInitializer.tsx:108` disables its bootstrap query (`enabled: !currentPortfolio`), and `resetQueries` would fall through to dashboard children — bypassing the empty-portfolio gate. This is why the wizard must not write empty/null portfolios to the store.

2. **Phase B (user clicks "Go to Dashboard"):** THEN call `queryClient.resetQueries({ queryKey: initialPortfolioKey })`. Two outcomes depending on Phase A:
   - **Phase A succeeded (store has portfolio):** `currentPortfolio` is set in Zustand store → `PortfolioInitializer` query is disabled (`enabled: !currentPortfolio` at `PortfolioInitializer.tsx:110`). `resetQueries` clears the TanStack Query error state but the query doesn't re-run. Initializer falls through to `children` immediately — dashboard mounts with the portfolio from the store. This is correct behavior.
   - **Phase A failed / "Go to Dashboard anyway" (store is empty):** `currentPortfolio` is null → `resetQueries` clears `isError` → query re-runs → `queryFn` hits backend `GET /api/portfolios/CURRENT_PORTFOLIO` → success with data (if provider sync completed in background) → dashboard, OR 404/empty → `EmptyPortfolioLanding` (via the gate logic).
   - **Note on `queryFn` fast path:** Even when the query runs (no `currentPortfolio`), the `queryFn` (line 113-120) first checks `usePortfolioStore.getState().byId` and picks the first in-memory portfolio if one exists, before hitting the backend. Since Phase A failure means nothing was written to the store, this fast path is a no-op in the failure case. In the success case, the query is already disabled.
3. **"Connect another account":** Loops back to Step 2a without resetting queries. The wizard stays in the `onboardingFallback` surface.

**Skip / dismiss path:** When user clicks "Skip for now", they land on `<EmptyPortfolioLanding>` — a purpose-built empty state that lives in `onboardingFallback` (outside `PortfolioInitializer` children), so the dashboard shell and Settings are NOT mounted. Therefore EmptyPortfolioLanding must embed connection flows directly using the shared components:
- "Your portfolio is empty" message
- "Connect a brokerage" button → opens `<InstitutionPicker>` + `<ConnectionFlow>` inline (same shared components as wizard, not a route to Settings)
- "Import a CSV" button → opens CSV import flow inline
- "Start wizard" button → **only shown when `onboarding_completed` is NOT set** (i.e., user dismissed but never completed). Re-enters wizard (clears `onboarding_dismissed_{userId}` from localStorage). When `onboarding_completed` IS set (user completed onboarding previously, portfolio later became empty), the "Start wizard" button is hidden — the inline connection/import flows are sufficient for reconnection.
- This is NOT the error UI. It's a standalone surface with its own connection capabilities.

**Re-entering the wizard:** Only possible when `onboarding_completed` is not set. The "Start wizard" button on EmptyPortfolioLanding clears `onboarding_dismissed` and shows the wizard. Once `onboarding_completed` is set, the wizard is permanently hidden — the user reconnects via the inline flows on `EmptyPortfolioLanding` or Settings → Connections. Once any connection succeeds (via landing or wizard), the same deferred-exit flow lets user see the Done screen, then "Go to Dashboard" triggers the query reset and mounts the dashboard.

**Secondary trigger:** Inside the dashboard (post-bootstrap), if the user has a portfolio but it's stale or they want to add accounts, they use Settings → Connections (not the wizard).

Cards:
- **Connect a brokerage** — "Link your account for live positions and market data"
- **Import a CSV** — "Upload a position export from any brokerage"
- **Skip for now** — Dismisses wizard, stores in localStorage

### Step 2a: Select Broker (Connect path)

**Reuses extracted `<InstitutionPicker>`** — the same component that powers the "Add Account" modal in Settings → Connections (`AccountConnections.tsx:540`).

Data source: `INSTITUTION_CONFIG` from `providers.ts` (single source of truth). Popular brokerages shown first, full list searchable below.

On selection, calls extended provider routing endpoint to determine the connection flow:

```json
// GET /api/provider-routing/institution-support/charles_schwab
// ADDITIVE extension — no breaking changes. Existing fields (`institution_slug`,
// `recommended_provider`, `snaptrade_supported`, `plaid_supported`, `providers: string[]`)
// are preserved. New fields added alongside: `flow_type`, `schwab_supported`,
// `ibkr_supported`, `provider_details[]`. Frontend ProviderRoutingService.ts must
// extend its InstitutionSupport interface to consume new fields; old callers
// that only read existing fields continue to work.
{
  "institution_slug": "charles_schwab",           // KEEP existing field name
  "recommended_provider": "snaptrade",            // KEEP as snaptrade|plaid ONLY — existing callers branch on these
  "flow_type": "cli_oauth",                       // NEW: wizard uses this instead of recommended_provider
  "direct_provider": "schwab",                    // NEW: the actual direct provider (schwab|ibkr|null)
  "schwab_supported": true,                        // NEW
  "ibkr_supported": false,                         // NEW
  "snaptrade_supported": true,                     // existing
  "plaid_supported": false,                        // existing
  "providers": ["schwab", "snaptrade"],            // KEEP as string[] for backwards compat
  "provider_details": [                            // NEW additive field (object array)
    {"name": "schwab", "flow_type": "cli_oauth", "primary": true},
    {"name": "snaptrade", "flow_type": "hosted_ui", "primary": false}
  ]
}
```

**Migration approach:**
- `recommended_provider` stays `'snaptrade' | 'plaid'` only — existing `ProviderRoutingService.ts:101,123,283,315` callers continue to work. Schwab/IBKR institutions that also have SnapTrade/Plaid aggregator support (e.g., `routing_config.py:178,182`) still route through their aggregator in the existing Settings UI.
- New wizard uses `flow_type` and `direct_provider` fields instead. `direct_provider` = `"schwab"` or `"ibkr"` when a direct connection is available, `null` otherwise.
- Existing aggregator paths for Schwab/IBKR users are NOT changed — users who currently connect Schwab via SnapTrade continue to work. The wizard offers the direct path as the primary option via `flow_type`.

### Step 3a: Provider-Specific Connection

Each provider has a different auth UX. The wizard renders the appropriate flow based on `flow_type`.

> **Phase boundary:** This section describes all 4 flow types for the complete design. **Phase 1 only implements `hosted_link` (Plaid) and `hosted_ui` (SnapTrade).** The `cli_oauth` (Schwab) and `gateway_guide` (IBKR) flows are implemented in **Phase 2**. In Phase 1, institutions with `cli_oauth`/`gateway_guide` flow types show a "Coming soon" badge and fall back to their aggregator path.

**`hosted_link` — Plaid** (Vanguard, Merrill, banks, "Other"):
1. Backend creates hosted link token → returns URL + `link_token`
2. Wizard opens Plaid Link in new tab (reuses existing `usePlaid()` hook from `AccountConnectionsContainer`)
3. User authenticates with their bank
4. **Attempt correlation**: Wizard holds the `link_token` from step 1 and polls via existing `PlaidPollingService.startPolling(linkToken, ...)` — this is the existing completion detection path (`POST /plaid/poll_completion` keyed by `link_token`)
5. **Token exchange**: On poll success, `PlaidPollingService` returns a `public_token` (from `routes/plaid.py:1238`). Wizard must call `exchangePublicToken(publicToken)` (from `usePlaid.ts:150` → `routes/plaid.py:787`) to persist the Plaid connection. Without this step, the Link session completes but no `item` is created in the backend.
6. On successful exchange → wizard advances to Step 4 (Processing)

**`hosted_ui` — SnapTrade** (Fidelity, E*Trade):
1. Wizard snapshots current SnapTrade connections via `SnapTradeService.getConnections()` → count distinct `authorization_id` values from `connections[]` array (each `SnapTradeConnection` has an `authorization_id` field; the UI already groups by this in `AccountConnectionsContainer.tsx:676-680`)
2. Backend creates connection URL via existing `routes/snaptrade.py` → returns redirect URL
3. Wizard opens SnapTrade UI in new tab
4. User authenticates with their broker
5. **Attempt correlation**: The manual "I've completed the connection" button is the **primary completion signal** (user confirms they finished in the SnapTrade popup). As an optimization, wizard also polls `SnapTradeService.getConnections()` in the background and counts distinct `authorization_id` values — if count increases, auto-advance without requiring the button click.
   - **Backend limitation**: `GET /api/snaptrade/connections` returns `success: true, connections: []` on both real "no connections" and degraded/error paths (`routes/snaptrade.py:580,635`). This makes auto-detection unreliable. The manual button is the reliable path. Background polling is best-effort only — if it detects a new auth, great; if not, the manual button handles it.
6. On completion (manual or auto-detected) → wizard advances to Step 4 (Processing)

**`cli_oauth` — Schwab** (Charles Schwab):
- Schwab OAuth currently requires a local CLI flow (`python3 -m scripts.run_schwab login`) that opens a browser and captures the callback on `localhost:8182`.
- **MVP scope: single-user / server-local only.** The token file (`~/.schwab_token.json`) is global to the server — there is no per-user token isolation. This is acceptable for the current single-user deployment model.
- **MVP approach**: Wizard shows a guided instruction panel:
  1. "Open your terminal and run: `python3 -m scripts.run_schwab login`"
  2. "Complete the Schwab login in your browser"
  3. "Come back here and click 'I've completed it'"
- Wizard polls `/api/onboarding/connection-status?provider=schwab` to detect when token file appears and positions become available
- **Future**: Web-based Schwab OAuth callback route + per-user token storage for multi-user

**`gateway_guide` — IBKR** (Interactive Brokers):
- IBKR requires the IB Gateway application running locally on the server.
- **MVP scope: single-user / server-local only.** The Gateway connection is global — all users share one Gateway session. This is acceptable for the current single-user deployment model.
- **MVP approach**: Wizard shows a step-by-step guide:
  1. "Download IB Gateway from Interactive Brokers"
  2. "Start IB Gateway and log in with your IBKR credentials"
  3. "Make sure it's running on the default port (7496)"
- Wizard polls new `GET /api/ibkr/status` endpoint to detect Gateway
- Once connected, auto-fetches positions

**Known gap — IBKR dual-provider**: Complete IBKR setup requires both Gateway (live positions/trading)
AND Flex (historical transactions for realized performance, trading analysis, tax harvest). This wizard
phase only covers Gateway. Flex setup guidance (create query on IBKR portal, get token + query ID) is
deferred to Phase D (Brokerage Connection Friction Reduction). Users who complete IBKR Gateway setup
will have positions but no transaction history until Flex is configured separately.

### Step 2b/3b: CSV Import (Import path)

1. Institution dropdown — populated from `INSTITUTION_CONFIG` (same source as broker selection)
2. File picker (`.csv` only)
3. **Preview step** — calls `POST /api/onboarding/preview-csv` (dry-run parse):
   ```json
   // Multipart form: file + institution
   // Response: parsed summary without persisting
   {
     "status": "success",
     "positions_count": 47,
     "cash_entries_count": 3,
     "total_value": 523400.00,
     "sample_holdings": [
       {"ticker": "AAPL", "shares": 100, "value": 21500.00},
       {"ticker": "MSFT", "shares": 50, "value": 21250.00}
     ],
     "warnings": ["Unknown ticker: FCASH (mapped to cash)"]
   }
   ```
   UI shows position count, total value, sample holdings table, and any warnings.
4. Confirm → calls `POST /api/onboarding/import-csv` (same file, persists + returns full portfolio_data)

**Depends on:** Phase A Step 2 (CSV importer) — the backend parser. Both preview and import endpoints wrap it. Preview calls parser with `dry_run=True`, import calls with `dry_run=False`.

### Step 4: Processing

Animated spinner with progressive status messages:
- "Connecting to [institution name]..."
- "Fetching your positions..."
- "Loading market data..."

### Step 5: Done / Error

**Success (deferred exit — wizard stays visible until user clicks "Go to Dashboard"):**
- **Done screen copy:** "Your portfolio is ready — X positions loaded" (position count from `portfolio.holdings.length`). Always generic, never institution-specific. `refreshHoldings()` does not report which providers produced the result (`PortfolioManager.ts:716-731`), and the wizard calls it unscoped (all connected providers). Even for a "first connection," pre-existing providers may exist from previous sessions, and the wizard cannot verify which provider's data is in the result. Institution-specific success claims (e.g., "loaded from Schwab") would be false positives if an older provider satisfied the refresh while the newly added one failed.
- **Portfolio activation happens in background** (before showing Done screen):
  1. For live providers: Call `manager.refreshHoldings()` **directly** from the wizard (NOT via `IntentRegistry.triggerIntent('refresh-holdings')`). The intent handler in `SessionServicesProvider.tsx:315` immediately writes any successful refresh to the store via `PortfolioRepository.add() + setCurrent()` before the caller can inspect holdings, and it only returns `{success, error}` — not the portfolio data (`NavigationIntents.ts:78,127`). The wizard needs the portfolio result to apply the empty-holdings guard from Phase A (see deferred exit section above). Calling `manager.refreshHoldings()` directly returns `{portfolio, error}` and lets the wizard decide whether to write to the store.
     - **Store write decision:** If `portfolio?.holdings?.length > 0` → wrap with identifier: `PortfolioRepository.add({ ...portfolio, portfolio_name: 'CURRENT_PORTFOLIO' })` → `setCurrent(id)`. `refreshHoldings()` returns bare `Portfolio` fields (`holdings`, `total_portfolio_value`, etc.) without `id` or `portfolio_name` (`PortfolioManager.ts:679`), and `PortfolioRepository.add()` throws if both are missing (`PortfolioRepository.ts:129`). The existing intent handler does the same wrapping at `SessionServicesProvider.tsx:328`. If empty → do NOT write to store, stay in retry/waiting state (see Phase A empty-holdings guard).
     - **Single-provider initial connection (typical onboarding):** When only one provider is connected, `refreshHoldings()` returns that provider's portfolio directly (`PortfolioManager.ts:731-732` — `portfolios.length === 1` path). No concatenation or dedup needed.
     - **Multi-provider "Connect another account" flow:** When 2+ providers are connected, `refreshHoldings()` does `flatMap(portfolio.holdings)` (`PortfolioManager.ts:736`) — simple array concatenation without dedup. Overlapping tickers from different providers will appear as separate holdings in the in-session portfolio. On page reload, `PortfolioInitializer` re-fetches from `GET /api/portfolios/CURRENT_PORTFOLIO`, which reads from the DB where each provider's positions are stored with distinct `position_source` and the backend assembler consolidates by ticker. This in-session vs reload divergence is a **pre-existing limitation** of the multi-provider `refreshHoldings()` path — it affects Settings → Connections identically. Not introduced by the wizard.
     - **Multi-provider partial success limitation:** `refreshHoldings()` (`PortfolioManager.ts:716-719`) drops rejected providers from the result as long as at least one provider fulfilled. If the newly added provider is still unsynced or returning 500, while the previously connected provider refreshes successfully, the wizard will advance to Done screen showing only the old provider's holdings — missing the new account. This is a **pre-existing limitation** of `refreshHoldings()`'s partial-success model. For MVP, accept this: the wizard shows whatever positions are available and the Done screen position count reflects what's currently loaded.
     - **Will missing provider data appear later?** Depends on whether the backend sync succeeded. If the provider's backend sync wrote rows to DB (via `save_positions_from_dataframe()`) but the frontend `Promise.allSettled` response was rejected, a page reload will show the new data — `PortfolioInitializer` fetches from `GET /api/portfolios/CURRENT_PORTFOLIO` which reads all provider rows from DB. If the backend sync itself failed (provider not ready, empty data → 500), the DB has no data for that provider and reload won't help. The user would need to trigger a manual refresh via Settings → Connections or wait for an automated sync interval. A more robust approach (provider-specific completion detection) can be added in Phase 4 polish.
     - **Cooldown handling:** Both Plaid and SnapTrade refresh routes enforce a 60-second cooldown (`plaid.py:176,990`, `snaptrade.py:227,834`). `PortfolioManager.refreshHoldings()` fails the whole operation if any provider returns 429 (`PortfolioManager.ts:705`). For the "Connect another account" flow, where a second connection completes within 60s of the first refresh: the wizard catches 429 errors and shows "Your accounts are syncing... please wait a moment" with a fixed 60-second countdown, then auto-retries. Uses a fixed 60s timer (not `Retry-After` header — the current error pipeline at `HttpClient.ts:153` → `PortfolioManager.ts:705` does not propagate `Retry-After`). This ensures the newly added account appears before the user proceeds to the dashboard.
  2. For CSV import: `PortfolioRepository.add({ ...portfolio_data, portfolio_name: 'CURRENT_PORTFOLIO' })` + `setCurrent()` (no refresh-holdings needed — CSV response always has holdings). Note: the import response has `portfolio_name` at the top level alongside `portfolio_data`, so it must be merged into the object passed to `add()`. Same pattern as the live-provider path above.
  3. Set `wizardComplete=true` in wizard local state → show Done screen
- **Done screen buttons:**
  - "Go to Dashboard" (primary) → sets `onboarding_completed_{userId}` in localStorage, then calls `queryClient.resetQueries({ queryKey: initialPortfolioKey })` → `PortfolioInitializer` exits `onboardingFallback`, mounts dashboard children
  - "Connect another account" (secondary) → loops back to Step 2a (does NOT reset queries — wizard stays in `onboardingFallback`)
  - Hint: "You can always add more accounts in Settings → Connections"
- Auto-invalidate provider + portfolio queries (Phase A invalidations from the Query Invalidation section) — run when Done screen appears, in background. The `resetQueries(initialPortfolioKey)` (Phase B) runs ONLY when user clicks "Go to Dashboard" — this is the deferred exit trigger.

**Error:**
- Clear error message
- "Try again" button (retries current step)
- "Import CSV instead" fallback
- "Skip for now" escape hatch

---

## Multi-Account Management

The wizard handles **first-run only**. Ongoing account management lives in **Settings → Connections**.

### Shared Components (wizard + Settings use the same)

| Component | Used in Wizard | Used in Settings |
|-----------|---------------|-----------------|
| `<InstitutionPicker>` | Step 2a (broker selection) | "Add Account" modal |
| `<ConnectionFlow>` | Step 3a (provider auth) | "Add Account" after selection |
| `<ConnectionStatus>` | Step 4 (processing) | Per-account sync status |

### Wizard → Settings handoff
- Wizard completion offers "Connect another account" → loops to broker selection
- After first successful connection, wizard won't auto-show again (localStorage)
- All subsequent connections go through Settings → Connections

### Settings → Connections enhancements (post-wizard)
- **Per-account status** — Last sync time, position count, re-auth warnings
- **Re-auth flow** — Schwab (7-day token), Plaid (item errors), SnapTrade (disabled connections)
- **Disconnect** — Remove provider connection + clear cached positions
- **Sync now** — Manual refresh per-account or all accounts

---

## Backend Requirements

### Extend Existing Endpoints

**`GET /api/provider-routing/institution-support/{slug}`** — Additive extension (backwards compatible):
```json
{
  "institution_slug": "charles_schwab",          // existing (keep name)
  "recommended_provider": "snaptrade",           // KEEP as snaptrade|plaid only for existing callers
  "flow_type": "cli_oauth",                     // NEW (wizard uses this)
  "direct_provider": "schwab",                  // NEW (schwab|ibkr|null)
  "schwab_supported": true,                      // NEW
  "ibkr_supported": false,                       // NEW
  "snaptrade_supported": true,                   // existing
  "plaid_supported": false,                      // existing
  "providers": ["schwab", "snaptrade"],          // existing string[] (keep)
  "provider_details": [                          // NEW additive field
    {"name": "schwab", "flow_type": "cli_oauth", "primary": true},
    {"name": "snaptrade", "flow_type": "hosted_ui", "primary": false}
  ]
}
```

Flow type determination logic (in `provider_routing_api.py`):
- `flow_type`: Primary connection UX. For institutions with a direct provider (`schwab`/`ibkr`), use the direct flow type. Fallback to aggregator flow type:
  - Institution in `POSITION_ROUTING` with schwab → `cli_oauth`
  - Institution in `POSITION_ROUTING` with ibkr → `gateway_guide`
  - SnapTrade supported → `hosted_ui`
  - Plaid supported → `hosted_link`
- `direct_provider`: `"schwab"` if `POSITION_ROUTING` maps to schwab, `"ibkr"` if maps to ibkr, `null` otherwise.
- `schwab_supported`: `True` if institution maps to schwab in `POSITION_ROUTING` AND `is_provider_enabled('schwab')`. Note: uses `enabled` not `available` — Schwab's CLI OAuth flow is the SETUP flow that creates the token file. `is_provider_available()` would require the token to already exist, hiding the very flow meant to create it.
- `ibkr_supported`: `True` if institution maps to ibkr in `POSITION_ROUTING` AND `is_provider_enabled('ibkr')`. Same reasoning: the Gateway guide flow is the SETUP flow that gets the user to start Gateway.
- `snaptrade_supported`: Check `is_provider_available('snaptrade')` — SnapTrade can be unavailable at runtime (`snaptrade.py:491`). Don't advertise if not available.
- `plaid_supported`: Check whether Plaid client creation succeeds (`brokerage/plaid/client.py:46` can return None). Don't advertise if client unavailable.
- `flow_type` selection: Use direct flow (`cli_oauth`/`gateway_guide`) when `*_supported` is True. Fall back to aggregator flow type only if aggregator (`snaptrade_supported`/`plaid_supported`) is also True. If neither direct nor aggregator available → `flow_type: null` (institution shown as unavailable in wizard).
- The existing helper at `provider_routing_api.py:472` only recognizes `snaptrade|plaid|manual`. Extend it to also populate the new fields from `POSITION_ROUTING` direct-provider entries.

**Phase 1 wizard behavior:** Only Plaid and SnapTrade flows are implemented. When `flow_type` is `cli_oauth` or `gateway_guide`:
- **If aggregator fallback available** (`snaptrade_supported` or `plaid_supported` is true): Show institution with a "Coming soon" badge on the direct flow. Selection shows: "Direct connection coming soon. You can connect via [aggregator] instead." and falls back to the aggregator `recommended_provider` path.
- **If NO aggregator fallback available** (only direct provider enabled, no Plaid/SnapTrade): Institution is shown as **unavailable** in Phase 1 wizard (grayed out with "Requires direct setup — coming in a future update"). This prevents a dead-end where the user selects an institution but there is no implemented connection flow. Phase 2 removes this restriction and implements the direct flows.

### New Endpoints

**`GET /api/onboarding/status`** — Aggregated first-run state
```json
{
  "has_positions": false,
  "total_positions_count": 0,
  "connections": [
    {"provider": "schwab", "status": "connected", "institution": "charles_schwab"},
    {"provider": "plaid", "items": [
      {"item_id": "abc", "institution": "vanguard", "status": "connected", "needs_reauth": false}
    ]},
    {"provider": "snaptrade", "connections": [
      {"authorization_id": "xyz", "institution": "fidelity", "status": "ACTIVE"}
    ]}
  ],
  "available_providers": ["schwab", "plaid", "snaptrade", "ibkr"]
}
// NOTE: Per-connection position counts and account counts are omitted.
// The DB schema (provider_items, positions) does not link positions to
// specific items/authorizations. Only total_positions_count is available
// (from positions table). Per-connection counts would require schema changes.
```

**`GET /api/onboarding/connection-status`** — Poll after connection attempt
```json
// GET /api/onboarding/connection-status?provider=schwab
{
  "provider": "schwab",
  "status": "connected",           // "pending" | "connected" | "error"
  "institution": "charles_schwab",
  "error": null
}

// GET /api/onboarding/connection-status?provider=plaid&item_id=abc
{
  "provider": "plaid",
  "status": "connected",
  "institution": "vanguard",
  "item_id": "abc",
  "needs_reauth": false,
  "error": null
}
```

**`GET /api/ibkr/status`** — Expose existing Gateway probe as REST
```json
{
  "gateway_reachable": true,
  "accounts": ["U12345"],
  "positions_count": 23
}
```

**`POST /api/onboarding/preview-csv`** — CSV dry-run parse (wraps Phase A Step 2 with `dry_run=True`)
```json
// Multipart form: file + institution
// Response: parsed summary without persisting
{
  "status": "success",
  "positions_count": 47,
  "cash_entries_count": 3,
  "total_value": 523400.00,
  "sample_holdings": [
    {"ticker": "AAPL", "shares": 100, "value": 21500.00},
    {"ticker": "MSFT", "shares": 50, "value": 21250.00}
  ],
  "warnings": ["Unknown ticker: FCASH (mapped to cash)"]
}
```

**`POST /api/onboarding/import-csv`** — CSV import (wraps Phase A Step 2 backend)
```json
// Multipart form: file + institution
// Response includes portfolio_data so frontend can create/activate portfolio
// Response format matches frontend Portfolio interface (holdings: Holding[])
{
  "status": "success",
  "positions_count": 47,
  "warnings": ["3 cash entries skipped"],
  "portfolio_data": {
    "holdings": [
      {"ticker": "AAPL", "shares": 50, "market_value": 10750.00, "security_name": "Apple Inc"},
      {"ticker": "MSFT", "shares": 25, "market_value": 10625.00, "security_name": "Microsoft Corp"}
    ],
    "total_portfolio_value": 523400.00,
    "statement_date": "2026-03-10",
    "account_type": "investment"
  },
  "portfolio_name": "CURRENT_PORTFOLIO"
}
```

> **SUPERSEDED**: The CSV storage model below (`position_source='csv_import'`, custom cleanup)
> is superseded by Phase A Step 2's `CSVPositionProvider` with `position_source='csv_{source_key}'`
> and provider-scoped deletion. The wizard's REST endpoints should wrap Phase A's `import_portfolio`
> backend. See "Cross-Plan Dependencies" section at the end of this document.

> **NOTE TO IMPLEMENTERS**: Everything below in this CSV section (persistence path, cleanup model,
> edge cases) describes the **original DB-based approach** using `save_portfolio()` and
> `position_source='csv_import'`. This is superseded by Phase A Step 2's filesystem-based
> `CSVPositionProvider` with `position_source='csv_{source_key}'`. The wizard's REST endpoints
> should wrap Phase A's `import_portfolio` backend. Do NOT implement the `save_portfolio()` path
> or the cleanup SQL below — use Phase A's provider-scoped deletion instead.

**Backend persistence path** (import-csv endpoint internals) — **SUPERSEDED, see note above**:
1. Parse CSV → array of position dicts (`[{ticker, quantity, currency, type, cost_basis, name}, ...]`)
2. Convert to ticker-keyed `portfolio_input` dict for `save_portfolio()`: `{ticker: {'shares': qty, 'currency': ccy, 'type': type, 'cost_basis': basis}}`. Duplicate tickers within same account are summed. This matches the existing `save_portfolio()` contract (`database_client.py:2467`), which expects `portfolio_data['portfolio_input']` as `{'TICKER': {'shares': N, ...}}`.
3. Call `save_portfolio(user_id, 'CURRENT_PORTFOLIO', portfolio_data, position_source='csv_import')` — uses **`csv_import`** as the `position_source` (distinct from `'database'` used by manual portfolios, and from `'plaid'`/`'snaptrade'` used by live providers).

**Coordination with Phase A Step 2**: This wizard's CSV persistence uses `save_portfolio()` with
`position_source='csv_import'` and custom cleanup logic. Phase A Step 2 introduces `CSVPositionProvider`
with `position_source='csv_{source_key}'` format and provider-scoped deletion. These two approaches
must be reconciled before implementation — the wizard should use Phase A's CSV backend rather than
implementing its own storage path. The wizard's REST endpoints (`/api/onboarding/preview-csv`,
`/api/onboarding/import-csv`) should wrap the same `import_portfolio` backend that the MCP tool uses.

4. Enrich with market prices via `latest_price()` per ticker.
5. Convert enriched positions to `Holding[]` array format for the response: `[{ticker, shares, market_value, security_name}]`. This matches the frontend `Portfolio` interface (`types/index.ts:61`) where `holdings: Holding[]`. The ticker-keyed dict is only used for the `save_portfolio()` call in step 3 — it never leaves the backend.

**CSV portfolio activation path** (distinct from live-provider path):
The `refresh-holdings` intent handler (`SessionServicesProvider.tsx:316`) only works for live providers (Plaid/SnapTrade). CSV import needs a separate activation path:
1. `POST /api/onboarding/import-csv` **persists the imported portfolio server-side as `CURRENT_PORTFOLIO`** with `position_source='csv_import'` (so `GET /api/portfolios/CURRENT_PORTFOLIO` succeeds on refresh/new tab) and returns `portfolio_data` in the response (with `holdings` as `Holding[]` array)
2. Wizard calls `PortfolioRepository.add({ ...portfolio_data, portfolio_name: 'CURRENT_PORTFOLIO' })` → returns `id`. The `normalise()` function in `PortfolioRepository.ts:120` derives `id` from `portfolio_name` — it does not reshape `holdings`, so the array format from the response passes through unchanged.
3. Wizard calls `PortfolioRepository.setCurrent(id)`
4. Shows Done screen (deferred exit — see bootstrap gate section)
5. User clicks "Go to Dashboard" → wizard calls `queryClient.resetQueries({ queryKey: initialPortfolioKey })` to exit `onboardingFallback`
6. No `refresh-holdings` needed — portfolio is already complete from the import response

**Durability:** Because the import endpoint persists server-side as `CURRENT_PORTFOLIO`, a page refresh or new tab will bootstrap normally via `PortfolioInitializer` → `getPortfolio('CURRENT_PORTFOLIO')` → success → render dashboard. The imported portfolio survives without needing a live provider connection.

**CSV + live provider coexistence — backend-side cleanup model:**
The DB uses provider-scoped deletion (`DELETE WHERE position_source = %s` in `database_client.py:2549`). Each provider sync only deletes its own rows:
- CSV import writes with `position_source='csv_import'`
- Plaid sync writes with `position_source='plaid'`
- SnapTrade sync writes with `position_source='snaptrade'`

Without explicit cleanup, connecting a live provider after CSV import would **merge** both sources (CSV rows persist alongside live rows), causing duplicate holdings for overlapping tickers.

**Cleanup rule — backend-side, path-independent:** The CSV cleanup is performed **inside** the existing provider sync code paths (`PositionService.refresh_holdings()` / `save_positions_from_dataframe()`), not by the frontend. When any live provider sync successfully writes new positions for `CURRENT_PORTFOLIO`, the sync method checks whether `csv_import` rows exist for the same portfolio and deletes them in the same DB transaction. This is a ~5-line addition to `save_positions_from_dataframe()` (`database_client.py:2710`):

```python
# After successful INSERT of live provider positions, clean up CSV bootstrap rows
cursor.execute(
    "DELETE FROM positions WHERE portfolio_id = %s AND position_source = 'csv_import'",
    (portfolio_id,)
)
if cursor.rowcount > 0:
    logger.info(f"🧹 Cleaned up {cursor.rowcount} csv_import bootstrap rows (superseded by {position_source})")
```

This approach:
- **Works from both wizard AND Settings → Connections** — any live provider sync cleans up CSV rows regardless of which frontend surface triggered it.
- **Is atomic** — cleanup and live position insert happen in the same DB transaction (the `conn.commit()` at `database_client.py:2814` covers both). No zero-positions window.
- **Is idempotent** — if no `csv_import` rows exist, the DELETE is a no-op.
- **No separate endpoint needed** — the frontend doesn't need to call a cleanup API. The backend handles it transparently.

**Edge case — CSV-only user who never connects live:** CSV rows persist indefinitely with `position_source='csv_import'`. The user can re-import a new CSV (which replaces all `csv_import` rows via the same provider-scoped deletion in `save_portfolio()`). No cleanup needed.

**Edge case — user connects live, then disconnects all providers:** CSV rows were already cleaned up by the provider sync that wrote live rows. Disconnecting a provider (deleting its rows) may leave the portfolio empty. The user would need to re-import a CSV or connect another provider.

**Edge case — `save_portfolio()` path (manual portfolios):** Manual portfolio creation uses `position_source='database'` via `save_portfolio()`. This path does NOT clean up `csv_import` rows because it uses a different DB method. If a user imports CSV then manually creates a portfolio for `CURRENT_PORTFOLIO`, the CSV rows would merge. This is acceptable for MVP — manual portfolio creation is an advanced flow not expected during onboarding.

**Edge case — DB save failure during provider sync:** `PositionService._save_positions_to_db()` is wrapped in a try/except that logs a warning and continues (`position_service.py:455-458`). If `save_positions_from_dataframe()` fails (including the csv_import cleanup), the transaction rolls back — both the live position INSERT and the csv_import DELETE are reverted. The UI shows correct data for that session (built from the freshly fetched provider payload, not DB state), but the DB retains stale CSV rows, which would reappear on page refresh. This is a **pre-existing limitation** of the refresh architecture — it affects ALL DB persistence during provider sync, not just CSV cleanup. The csv_import cleanup inherits the same failure mode as the existing provider-scoped DELETE. Fixing this (fail-closed refresh, or reload-from-DB before returning) is out of scope for this plan and would be a separate reliability improvement to the provider sync pipeline.

**CSV price refresh:** The import endpoint returns market-price-enriched holdings (backend calls `latest_price()` per ticker during import). The processing step message "Loading market data..." corresponds to this server-side enrichment. The frontend does NOT need a separate pricing call — it's included in the import response's `portfolio_data`.

Note: `PortfolioManager.extractPortfolioData()` is disabled (`PortfolioManager.ts:238`). The CSV import bypasses it entirely — the backend does the parsing, and the frontend just receives the portfolio payload.

### SnapTrade Enhancement

Pass institution hint when creating connection URL so SnapTrade pre-selects the broker:

**Backend:**
- `brokerage/snaptrade/connections.py:22` — Add `broker` parameter mapping from our `institution_slug` to SnapTrade's broker identifier
- `routes/snaptrade.py:512` — Accept optional `institution_slug` query param, pass to `create_connection_url()`
- **Mapping source**: SnapTrade's `GET /api/v1/brokerages` API returns their broker IDs. Build a static lookup dict `INSTITUTION_TO_SNAPTRADE_BROKER = {"fidelity": "FIDELITY", "etrade": "ETRADE", ...}` in `brokerage/snaptrade/connections.py`. Fallback: pass `broker=None` if slug not in dict (current behavior).

**Frontend (full call chain):**
- `SnapTradeService.ts:createConnectionUrl()` — Add optional `institutionSlug?: string` parameter, pass as query param to backend
- `APIService.ts:458` → `createSnapTradeConnectionUrl()` — Add optional `institutionSlug?: string` parameter, forward to `snaptradeService.createConnectionUrl(institutionSlug)`
- `useSnapTrade.ts:188` → mutation — Accept optional `institutionSlug` in mutate variables
- `useConnectSnapTrade.ts:127` — Pass `institutionSlug` from wizard context through to `useSnapTrade` mutation

Reduces one step in the SnapTrade hosted UI

---

## Frontend Components

### Extracted Shared Components

```
frontend/packages/ui/src/components/connections/
├── InstitutionPicker.tsx       # Broker grid (popular + all) — extracted from AccountConnections.tsx:540
├── ConnectionFlow.tsx          # Provider-specific auth flow (Plaid/SnapTrade/Schwab/IBKR) — NEW component
├── ConnectionStatus.tsx        # Polling + status display during/after connection — NEW component
└── hooks/
    ├── useConnectionFlow.ts    # Manages provider auth lifecycle — NEW hook (adapts existing hooks)
    └── useConnectionStatus.ts  # Polls connection-status endpoint — NEW hook
```

**Extraction vs creation notes:**
- `InstitutionPicker` — **Extract** from `AccountConnections.tsx:540-588` (popular grid + all list). This is a clean presentational extraction.
- `ConnectionFlow` — **New component**, not an extraction. Currently `AccountConnections` closes the modal on selection and calls `onConnectAccount(selectedProvider)` immediately (`AccountConnections.tsx:596-602`). There is no existing inline connection flow UI to extract. The wizard needs a multi-step inline flow (show Plaid Link, show SnapTrade redirect, show CLI guide). This is new code that wraps existing hooks (`usePlaid`, `useConnectAccount`, `useConnectSnapTrade`).
- `ConnectionStatus` — **New component**. Wraps existing `PlaidPollingService` and new SnapTrade polling logic.
- `useConnectionFlow` — **New hook** that normalizes the different provider auth lifecycles (Plaid link_token flow, SnapTrade popup flow, Schwab CLI polling, IBKR Gateway polling) behind a unified interface.

### Onboarding-Specific Components

```
frontend/packages/ui/src/components/onboarding/
├── OnboardingWizard.tsx        # Step state machine + Dialog shell
├── WelcomeStep.tsx             # Two-card choice (connect vs import)
├── CsvImportStep.tsx           # File upload + institution picker + preview
├── ProcessingStep.tsx          # Uses shared <ConnectionStatus>
├── CompletionStep.tsx          # Success/error + portfolio activation + next action
├── EmptyPortfolioLanding.tsx   # Post-dismiss landing (connect/import buttons, not error UI)
└── useOnboardingState.ts       # First-run detection, localStorage dismissal, initializer reset
```

### Integration Points

- **`PortfolioInitializer.tsx`** — Add `onboardingFallback` prop (separate from `errorFallback`). When query returns 404 (no portfolio): render `onboardingFallback`. Other errors: render `errorFallback`.
- **`ModernDashboardApp.tsx`** — Wire `onboardingFallback` prop on `<PortfolioInitializer>` at line 491: pass `<OnboardingWizard>` (if not dismissed) or `<EmptyPortfolioLanding>` (if dismissed). After wizard completes and user clicks "Go to Dashboard", `resetQueries` clears the bootstrap error → initializer mounts dashboard children.
- **`AccountConnections.tsx`** — Refactor "Add Account" to use shared `<InstitutionPicker>` + `<ConnectionFlow>`
- **`providers.ts`** — `INSTITUTION_CONFIG` remains single source of truth for all broker lists

### Query Invalidation (on completion)

Use the actual query key factories from `queryKeys.ts`. Two layers: provider-specific keys + portfolio-scoped keys (mirroring `CacheCoordinator.invalidatePortfolioData()`).

**Two-phase invalidation** (matches the deferred exit pattern — Phase A runs on Done screen, Phase B runs on "Go to Dashboard"):

```ts
import {
  initialPortfolioKey,
  portfolioSummaryKey, performanceKey, positionsHoldingsKey,
  portfolioAlertsKey, marketIntelligenceKey, aiRecommendationsKey,
  metricInsightsKey, portfolioKey, riskScoreKey,
  plaidConnectionsKey, plaidHoldingsKey, plaidPendingUpdatesKey,
  snaptradeConnectionsKey, snaptradeHoldingsKey, snaptradePendingUpdatesKey,
} from '@risk/chassis';

// === Phase A: Run when Done screen appears (background, while user reads) ===
// These mark caches stale so data is fresh when the dashboard mounts later.
// They do NOT affect the wizard rendering — wizard is in onboardingFallback, not children.

// Layer 1: Provider-specific connection state (user-scoped keys)
queryClient.invalidateQueries({ queryKey: plaidConnectionsKey(userId) })
queryClient.invalidateQueries({ queryKey: plaidHoldingsKey(userId) })
queryClient.invalidateQueries({ queryKey: plaidPendingUpdatesKey(userId) })
queryClient.invalidateQueries({ queryKey: snaptradeConnectionsKey(userId) })
queryClient.invalidateQueries({ queryKey: snaptradeHoldingsKey(userId) })
queryClient.invalidateQueries({ queryKey: snaptradePendingUpdatesKey(userId) })

// Layer 2: Portfolio-scoped keys (mirrors CacheCoordinator.ts:228-236)
queryClient.invalidateQueries({ queryKey: portfolioSummaryKey(portfolioId) })
queryClient.invalidateQueries({ queryKey: performanceKey(portfolioId) })
queryClient.invalidateQueries({ queryKey: positionsHoldingsKey() })
queryClient.invalidateQueries({ queryKey: portfolioAlertsKey() })
queryClient.invalidateQueries({ queryKey: marketIntelligenceKey() })
queryClient.invalidateQueries({ queryKey: aiRecommendationsKey() })
queryClient.invalidateQueries({ queryKey: metricInsightsKey() })
queryClient.invalidateQueries({ queryKey: portfolioKey(portfolioId) })
queryClient.invalidateQueries({ queryKey: riskScoreKey(portfolioId) })

// === Phase B: Run ONLY when user clicks "Go to Dashboard" (NOT on Done screen) ===
// This exits the onboardingFallback — MUST be deferred to prevent Done screen disappearing.

// Layer 0: Bootstrap key — MUST use resetQueries (not invalidateQueries)
// invalidateQueries only marks stale; resetQueries fully clears isError/error state
queryClient.resetQueries({ queryKey: initialPortfolioKey })
```

**Note on CacheCoordinator**: `CacheCoordinator.invalidatePortfolioData(portfolioId)` handles a subset of Layer 2 (`portfolioSummaryKey`, `performanceKey`, `positionsHoldingsKey`, `portfolioAlertsKey`, `marketIntelligenceKey`, `aiRecommendationsKey`, `metricInsightsKey`) but does NOT include `portfolioKey` or `riskScoreKey`. For onboarding completion, use the explicit list above to ensure full invalidation.

**Note on SDK data-source layer:** The modern dashboard uses `['sdk', sourceId, ...]` query keys via `useDataSource` hooks (not the legacy keys above). These SDK queries are created fresh when the dashboard mounts — which happens AFTER `resetQueries(initialPortfolioKey)` exits the `onboardingFallback` and renders children. Therefore SDK query invalidation is NOT needed during onboarding completion — the dashboard mounts with clean cache. The Layer 1-2 invalidations above are for provider connection state caches (Plaid/SnapTrade items) that may be stale from pre-wizard polling.

---

## Implementation Order

### Phase 0: Extract Shared Components + Routing Refactor
1. Extract `<InstitutionPicker>` from `AccountConnections.tsx:540-588` → `components/connections/InstitutionPicker.tsx` (presentational extraction)
2. Refactor `AccountConnections` to use extracted `<InstitutionPicker>` (no behavior change — modal still closes on selection and calls `onConnectAccount`)
3. **Backend**: Extend `GET /api/provider-routing/institution-support/{slug}` with `flow_type`, `direct_provider`, `schwab_supported`, `ibkr_supported`, `provider_details[]` — update both the helper function (`provider_routing_api.py:472`) AND the Pydantic `InstitutionSupportResponse` model (`provider_routing_api.py:234`) to include the new optional fields. Without updating the response model, FastAPI will strip the new fields from the response.
4. **Frontend routing consumer**: Extend `ProviderRoutingService.ts` `InstitutionSupport` interface (lines 101-112) to add optional `flow_type`, `direct_provider`, `schwab_supported`, `ibkr_supported`, `provider_details[]` fields. **Do NOT change** `recommended_provider` type (`'snaptrade' | 'plaid'`), `ProviderRoutingResult`, or `routeConnection()` — those existing callers (Settings → AccountConnectionsContainer) continue to read `recommended_provider` and branch on `snaptrade`/`plaid` as before. The wizard uses `flow_type` and `direct_provider` fields directly.

   **Wizard fail-closed lookup:** The existing `checkInstitutionSupport()` fallback (`ProviderRoutingService.ts:196-204`) returns synthetic `plaid_supported: true` on any error — this is fail-open behavior designed for Settings (where Plaid is a safe assumption). The wizard must NOT use this fallback, as it would show a direct-only institution as Plaid-connectable (dead-end in Phase 1). Add a `checkInstitutionSupportStrict()` method (or a `failClosed: boolean` option) that treats any fetch error as "institution unavailable" (returns all `*_supported: false`). The wizard's `InstitutionPicker` uses the strict method; Settings continues using the existing fail-open `checkInstitutionSupport()`.

   **Known issue — `PROVIDER_CREDENTIALS` gaps**: `is_provider_available("plaid")` and
   `is_provider_available("snaptrade")` currently return True even without credentials configured
   (empty `PROVIDER_CREDENTIALS` lists in `settings.py`). The wizard's status endpoint may advertise
   providers that will fail at runtime. Fix: populate `PROVIDER_CREDENTIALS` for Plaid/SnapTrade with
   actual required env var names, or add a deeper availability check in the status endpoint. Tracked
   in Phase D (Brokerage Connection Friction Reduction).
5. **No Settings behavior change in Phase 0**: `AccountConnectionsContainer.tsx:859,875` is untouched — it reads `recommended_provider` (always `snaptrade|plaid`), branches on those values, and works exactly as before. No gating rule needed because no new flow types flow through the existing Settings path.

### Phase 1: Onboarding Wizard MVP (Plaid + SnapTrade)
6. **Backend: `GET /api/portfolios/{name}` returns 404 (not 500) when no portfolio exists** — enables `PortfolioInitializer` to distinguish "no portfolio" from "backend error"
7. **Modify `PortfolioInitializer`** — add `onboardingFallback` prop. On query error, check if 404 (no portfolio) → render `onboardingFallback`. On other errors → render `errorFallback`. Also handle 200+empty holdings via `onboarding_completed` localStorage check. Wire `onboardingFallback` in `ModernDashboardApp.tsx:491`.
8. `GET /api/onboarding/status` endpoint
9. `GET /api/onboarding/connection-status` endpoint
10. Build `useConnectionFlow` hook — normalizes Plaid (`usePlaid` + `PlaidPollingService` link_token polling + `exchangePublicToken`) and SnapTrade (`useConnectSnapTrade` + authorization-count polling) behind a unified `{start, status, error}` interface
11. Build `<ConnectionFlow>` component — renders provider-specific inline UI, delegates to `useConnectionFlow`
12. Build `<ConnectionStatus>` component — polling progress display
13. `OnboardingWizard.tsx` shell (deferred exit pattern) + `WelcomeStep.tsx`
14. Wire `<InstitutionPicker>` into wizard Step 2a
15. Wire `<ConnectionFlow>` into wizard Step 3a (Plaid + SnapTrade flows)
16. `ProcessingStep.tsx` + `CompletionStep.tsx` (deferred exit: show Done screen, "Go to Dashboard" sets `onboarding_completed` + triggers `resetQueries`)
17. `EmptyPortfolioLanding.tsx` — dismiss target with embedded `<InstitutionPicker>` + `<ConnectionFlow>`
18. Full query invalidation on completion (use actual key factories + `resetQueries` for `initialPortfolioKey`)

### Phase 2: Schwab + IBKR Flows
19. Extend `useConnectionFlow` hook with Schwab `cli_oauth` path (poll `/api/onboarding/connection-status?provider=schwab`)
20. Schwab `cli_oauth` UI in `<ConnectionFlow>` (guided CLI instructions panel)
21. `GET /api/ibkr/status` endpoint (expose Gateway probe)
22. Extend `useConnectionFlow` hook with IBKR `gateway_guide` path (poll `/api/ibkr/status`)
23. IBKR `gateway_guide` UI in `<ConnectionFlow>` (guided setup panel)
24. **Extend `PortfolioManager.refreshHoldings()`** — Currently only knows `{ plaid?: boolean; snaptrade?: boolean }` (`PortfolioManager.ts:670`). Add `schwab?: boolean` and `ibkr?: boolean` provider flags. For Schwab: call new `APIService.refreshSchwabHoldings()` → backend `POST /api/schwab/holdings/refresh` (force-sync, not cached `GET`). For IBKR: call new `APIService.refreshIBKRHoldings()` → backend `POST /api/ibkr/holdings/refresh`. Must use POST/refresh semantics (like existing Plaid `POST /plaid/holdings/refresh` at `plaid.py:978` and SnapTrade `POST /snaptrade/holdings/refresh` at `snaptrade.py:819`) to trigger a fresh fetch from the provider, not a cached read.
25. **Onboarding always triggers full `refresh-holdings`** — The intent handler (`SessionServicesProvider.tsx:316`) calls `manager.refreshHoldings()` with no provider filter, which refreshes ALL connected providers and returns the combined portfolio. This is correct behavior for onboarding: after adding Schwab as a second account, we need the merged Plaid+Schwab holdings, not just Schwab's. No provider-scoped refresh for the wizard — that would clobber existing holdings from other providers (since `PortfolioRepository.add()` replaces holdings, not merges).
26. **Integrate shared `<ConnectionFlow>` into Settings**: Refactor `AccountConnectionsContainer.tsx:859` "Add Account" to use shared `<ConnectionFlow>` component (instead of direct `routeConnection()` + Plaid/SnapTrade hooks). This gives Settings support for Schwab/IBKR flows via the same shared component. `<InstitutionPicker>` already integrated in Phase 0.
27. SnapTrade institution hint passthrough (map `institution_slug` → SnapTrade broker ID, pass to `connections.py:22`)

### Phase 3: CSV Import Path

> **NOTE**: This phase wraps Phase A Step 2's `import_portfolio` backend. The REST endpoints
> call the same normalizer registry, `PositionRecord` contract, and storage layer. Do NOT
> implement a separate `save_portfolio()` path — use Phase A's `CSVPositionProvider` with
> `position_source='csv_{source_key}'` and the `get_all_positions()` safety guard for
> CSV→API graduation. See `PHASE_A_NO_INFRA_PLAN.md` Step 2.

28. `POST /api/onboarding/preview-csv` endpoint — wraps `import_portfolio(file_path, dry_run=True)`, returns summary + sample holdings
29. `POST /api/onboarding/import-csv` endpoint — wraps `import_portfolio(file_path, dry_run=False)`, persists via `CSVPositionProvider` with `position_source='csv_{source_key}'`. Returns `portfolio_data` matching the frontend `Portfolio` interface (`types/index.ts:61`).
30. **CSV→API graduation** — No explicit cleanup endpoint needed. The `get_all_positions()` safety guard auto-skips CSV positions when a live API provider has data for the same `brokerage_name`. Agent or UI suggests `import_portfolio(action="clear")` to remove stale CSV data after API connection.
31. **Fix `HttpClient.ts` for multipart uploads** — `HttpClient.ts:118` hard-sets `Content-Type: application/json`, which breaks browser-generated multipart boundaries. Add a `FormData` detection path: when `options.body instanceof FormData`, omit the `Content-Type` header (browser sets it automatically with the correct boundary). Alternatively, add a `sendFormData()` method that skips the JSON content type.
32. `CsvImportStep.tsx` — File upload (`FormData`) + institution picker + preview table + confirm/cancel

### Phase 4: Polish
33. Error recovery flows (retry, fallback to CSV)
34. Multi-account loop ("Connect another account" in completion step)
35. Mobile responsiveness
36. Re-auth warning integration in Settings → Connections

---

## Dependencies

- **Phase 0 is prerequisite** — Shared component extraction must happen before wizard implementation.
- **Phase A Step 2 (CSV importer)** — Required for Phase 3. Phases 0-2 proceed independently.
- **Provider credentials** — Plaid/SnapTrade flows require API keys configured on backend.
- **Schwab developer app** — Required for Schwab OAuth flow. MVP uses CLI guide as bridge.

---

## Design: Use Existing Components Only

**No new styling.** The wizard is built entirely from existing design system primitives. This keeps it centralized — theme changes, visual style toggles (`classic`/`premium`), and dark mode all work automatically.

### Component Mapping

| Wizard Element | Existing Component | Package |
|---------------|-------------------|---------|
| Modal shell | `Dialog` + `DialogContent` + `DialogHeader` + `DialogFooter` | `@risk/ui` |
| Step progress | `GradientProgress` (`colorScheme="emerald"`) | `@risk/blocks` |
| Welcome cards | `Card` (`variant="glass"` or `"glassTinted"`, `hover="lift"`) | `@risk/ui` |
| Broker grid | Extracted `<InstitutionPicker>` (uses `Button` + `INSTITUTION_CONFIG`) | `connections/` |
| Step titles | `SectionHeader` (`colorScheme="emerald"`) | `@risk/blocks` |
| Info/help text | `InsightBanner` (`variant="glass"`, `colorScheme="blue"`) | `@risk/blocks` |
| Primary CTA | `Button` (`variant="premium"`) | `@risk/ui` |
| Secondary CTA | `Button` (`variant="outline"`) | `@risk/ui` |
| Back button | `Button` (`variant="ghost"`) | `@risk/ui` |
| Processing spinner | `LoadingSpinner` (`size="large"`) | `@risk/shared` |
| Status messages | `InsightBanner` | `@risk/blocks` |
| Success state | `InsightBanner` (`colorScheme="emerald"`) + `MetricCard` (position count) | `@risk/blocks` |
| Error state | `InsightBanner` (`colorScheme="red"`) | `@risk/blocks` |
| File input | `Input` (`type="file"`) | `@risk/ui` |
| Broker dropdown | `Select` | `@risk/ui` |
| Completion metrics | `StatPair` (positions loaded, portfolio value) | `@risk/blocks` |

### Theme Compatibility

All components above automatically support:
- **Light / Dark mode** — via `.dark` class on `<html>`
- **Premium / Classic** — via `data-visual-style` attribute
- **Reduced motion** — all animations respect `prefers-reduced-motion`

### Animations (existing, no new CSS)

- Step transitions: `animate-fade-in-gentle`
- Card hover: `hover-lift-premium` (auto-disabled in classic mode)
- Processing: `animate-pulse-gentle`
- Completion: `animate-slide-up`
- Broker grid: `animate-stagger-fade-in`

### No Custom CSS

Everything goes through Tailwind utilities + existing component variants. If a visual element can't be built from existing primitives, add it to the block catalog first (reusable), not the wizard (one-off).

---

## Honest Limitations (MVP)

- **Schwab OAuth** — CLI-only for MVP. User must run terminal command. Token file (`~/.schwab_token.json`) is server-global, not per-user. **Single-user deployment only.** Web-based flow + per-user tokens is a future enhancement.
- **IBKR** — Requires local Gateway app. Gateway connection is server-global (one Gateway session shared). **Single-user deployment only.** Wizard can guide setup but can't automate installation. Polling detects when Gateway comes online.
- **SnapTrade broker pre-selection** — Currently opens generic broker picker. Institution hint passthrough is a Phase 2 enhancement (requires mapping our `institution_slug` → SnapTrade broker ID via their `GET /api/v1/brokerages` API).
- **CSV import** — Blocked on Phase A Step 2 (backend parser). Wizard can be built without it; CSV step shows "Coming soon" until parser lands.
- **Multi-user Schwab/IBKR** — Not supported in MVP. These providers have server-local state (token files, Gateway connections). Multi-user requires per-user credential isolation, which is out of scope until the multi-user deployment plan lands.
- **Settings dead-end for direct-only institutions (pre-Phase 2)** — Settings → Connections uses `recommended_provider` (always `snaptrade|plaid`) and unconditionally launches that aggregator (`AccountConnectionsContainer.tsx:866`, `ProviderRoutingService.ts:275`). For institutions where only a direct provider (Schwab/IBKR) is enabled and no aggregator is available, Settings has no working connection flow until Phase 2 (step 26) integrates the shared `<ConnectionFlow>` component. This is a pre-existing limitation of the Settings path, not introduced by the wizard. In Phase 1, the wizard correctly gates these institutions as unavailable.
- **In-session portfolio eviction not supported** — The `EmptyPortfolioLanding` for completed users (empty/404 portfolio) only triggers on bootstrap (page load). If the portfolio empties while the dashboard is already mounted (e.g., provider disconnected, all positions expired), there is no in-session mechanism to switch back to `EmptyPortfolioLanding`. The user would need to refresh the page. `PortfolioInitializer` disables its bootstrap query once `currentPortfolio` is set (`enabled: !currentPortfolio` at `PortfolioInitializer.tsx:110`), and nothing clears `currentPortfolio` on provider disconnect. This is a pre-existing architectural gap — adding an in-session portfolio-empty listener is a separate enhancement.

---

## Success Metrics

- New user → positions loaded in < 2 minutes (Plaid/SnapTrade path)
- New user → positions loaded in < 1 minute (CSV import path)
- Wizard completion rate > 80% (not abandoned at broker selection)
- Zero "I don't know what to do" states — every screen has a clear next action

---

## Cross-Plan Dependencies & Audit Findings (2026-03-11)

### Hard Dependencies
- **Phase 3 (CSV import)** depends on Phase A Step 2 (`import_portfolio` backend). REST endpoints should wrap the same normalizer registry, `PositionRecord` contract, and filesystem storage (Step 2) or DB storage (Tier 3+).
- **Phase 0-2** can proceed independently of Phase A Step 2.

### Reconciliation — RESOLVED
1. **CSV storage model**: This plan's original `save_portfolio()` + `position_source='csv_import'` is **superseded** by Phase A's `CSVPositionProvider` + `position_source='csv_{source_key}'`. The wizard should wrap Phase A's `import_portfolio` backend. The original persistence path and cleanup SQL in the CSV section above are kept for historical context only.
2. **CSV cleanup logic**: Phase A's provider-scoped deletion (`position_source='csv_{source_key}'`) handles cleanup. The custom `DELETE FROM positions WHERE position_source = 'csv_import'` SQL in this plan is unnecessary.
3. **CSV → API graduation**: No dedup needed. Safety guard in `get_all_positions()` auto-skips CSV positions when API data exists for the same `brokerage_name`. Agent suggests `import_portfolio(action="clear")` to remove stale CSV data. Sequential states, not concurrent.

### Known Gaps (from cross-plan audit)
- IBKR Flex setup not covered (Phase 2 only handles Gateway)
- `PROVIDER_CREDENTIALS` lies for Plaid/SnapTrade not addressed
- No Tier 3 vs Tier 4 distinction in wizard flow
- No tier detection / feature flag mechanism defined
