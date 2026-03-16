# Onboarding E2E Test Plan

**Status**: EXECUTED — ALL PASS
**Date**: 2026-03-12 (planned), 2026-03-14 (executed)
**Executor**: Claude (browser automation + file tools + MCP), with user assist for login and broker connections

---

## Overview

End-to-end validation of the full onboarding pipeline: new user → wizard → portfolio loaded → analysis running. Covers all 4 connection paths + the agent-driven transaction normalizer workflow.

**Tools Claude uses:**
- Chrome browser automation (`mcp__claude-in-chrome__*`) — navigate, click, fill forms, read pages, screenshots
- File system tools — write test CSVs, write normalizer files, read logs
- MCP tools — `import_transactions`, `import_portfolio` for direct API testing
- HTTP via browser — verify API responses, check endpoints

**User assists with:**
- Google OAuth login (one-time at start)
- Plaid/SnapTrade popup completion (if testing live connections)
- Schwab CLI command execution (if testing live Schwab)
- IBKR Gateway startup (if testing live IBKR)

---

## Prerequisites

- [ ] Backend running on `localhost:5001`
- [ ] Frontend dev server running on `localhost:3001`
- [ ] Chrome open with Claude extension active
- [ ] Sample CSVs available in `docs/` (already present)

---

## Test Phases

### Phase 1: Fresh State — Wizard Appears

**Goal**: Verify that a user with no portfolio sees the onboarding wizard.

| # | Step | Actor | How | Verify |
|---|------|-------|-----|--------|
| 1.1 | Clear onboarding localStorage | Claude | Browser JS: `Object.keys(localStorage).filter(k => k.startsWith('onboarding_')).forEach(k => localStorage.removeItem(k))` | Keys removed |
| 1.2 | Navigate to `http://localhost:3001` | Claude | `navigate` tool | Page loads |
| 1.3 | User logs in | **User** | Google OAuth popup | Authenticated |
| 1.4 | Screenshot the landing state | Claude | `computer` tool (screenshot) | Either OnboardingWizard dialog OR EmptyPortfolioLanding visible (depends on whether portfolio exists) |
| 1.5 | If dashboard shows (portfolio exists), clear it | Claude | Call `DELETE` or use MCP to remove positions, then refresh | Wizard/landing appears |
| 1.6 | Verify wizard Welcome step | Claude | Read page text | "Get started with your portfolio" visible, "Connect a brokerage" and "Import a CSV" cards visible |
| 1.7 | Verify Skip works | Claude | Click "Skip for now" | EmptyPortfolioLanding appears with connect/import buttons |
| 1.8 | Verify wizard re-entry | Claude | Click "Start wizard" on EmptyPortfolioLanding | Wizard reappears at Welcome step |

---

### Phase 2: CSV Import Path (Known Format — Schwab Positions)

**Goal**: Import the Schwab position CSV through the wizard, verify dashboard loads.

| # | Step | Actor | How | Verify |
|---|------|-------|-----|--------|
| 2.1 | From wizard Welcome, click "Import a CSV" | Claude | Click the Import card | CsvImportStep appears |
| 2.2 | Upload `docs/Individual-Positions-2026-03-10-171456.csv` | Claude | File input interaction | File accepted, brokerage auto-detected or selectable |
| 2.3 | Verify preview | Claude | Read page | Position count, total value, sample holdings table visible. Warnings (if any) shown. |
| 2.4 | Click "Import" / confirm | Claude | Click confirm button | ProcessingStep appears ("Loading...") |
| 2.5 | Wait for completion | Claude | Poll page until CompletionStep | "Your portfolio is ready — X positions loaded" |
| 2.6 | Screenshot completion | Claude | Screenshot | Position count matches expected |
| 2.7 | Click "Go to Dashboard" | Claude | Click button | Dashboard renders with real data |
| 2.8 | Verify dashboard has data | Claude | Read page — check for holdings table, portfolio value, charts | Not empty, position count matches import |
| 2.9 | Verify `onboarding_completed` set | Claude | Browser JS: `localStorage.getItem('onboarding_completed_' + userId)` | Returns `"true"` |
| 2.10 | Refresh page | Claude | Navigate to `localhost:3001` | Dashboard loads (not wizard) — portfolio persisted |

---

### Phase 3: CSV Import via API (Preview + Import endpoints)

**Goal**: Directly test the backend CSV endpoints outside the wizard UI.

| # | Step | Actor | How | Verify |
|---|------|-------|-----|--------|
| 3.1 | Preview Schwab CSV | Claude | `POST /api/onboarding/preview-csv` with FormData (file + institution=charles_schwab) via browser fetch | `positions_count > 0`, `total_value > 0`, `sample_holdings` array |
| 3.2 | Preview with wrong institution | Claude | Same but institution=fidelity | Still works (auto-detect) or returns warning |
| 3.3 | Preview unknown CSV format | Claude | Create a fake CSV, upload | Returns error or `needs_normalizer`-style message |
| 3.4 | Import Schwab CSV | Claude | `POST /api/onboarding/import-csv` with FormData | `status: "success"`, `portfolio_data.holdings` non-empty |
| 3.5 | Verify portfolio accessible | Claude | `GET /api/portfolios/CURRENT_PORTFOLIO` | Returns portfolio with holdings |

---

### Phase 4: Transaction Import — Known Format (Schwab)

**Goal**: Import Schwab transaction CSV via MCP tool, verify auto-detection.

| # | Step | Actor | How | Verify |
|---|------|-------|-----|--------|
| 4.1 | Dry run Schwab transactions | Claude | MCP `import_transactions(file_path="docs/Individual_XXX252_Transactions_20260310-171524.csv", dry_run=true)` | `status: "ok"`, `trade_count > 0`, `income_count > 0`, `brokerage: "Charles Schwab"` |
| 4.2 | Verify auto-detection | Claude | Check response `provider_name` | `schwab_csv` |
| 4.3 | Import for real | Claude | MCP `import_transactions(file_path="...", dry_run=false)` | Transactions saved |
| 4.4 | Verify in store | Claude | MCP `list_transactions(source="schwab_csv")` | Returns trades matching import count |
| 4.5 | Verify income events | Claude | MCP `list_income_events(source="schwab_csv")` | Returns dividends/interest from Schwab CSV |
| 4.6 | Verify trading analysis | Claude | MCP `get_trading_analysis(source="all")` | Includes Schwab trades in analysis |

---

### Phase 5: Transaction Import — Unknown Format (Agent Normalizer Generation)

**Goal**: Simulate an unknown brokerage CSV → `needs_normalizer` → Claude writes normalizer → re-import succeeds.

| # | Step | Actor | How | Verify |
|---|------|-------|-----|--------|
| 5.1 | Create a fake "Acme Brokerage" CSV | Claude | Write file to `/tmp/acme_transactions.csv` with custom columns: `Trade Date, Type, Ticker, Shares, Price Per Share, Commission, Total` and 5-10 sample rows | File created |
| 5.2 | Attempt import | Claude | MCP `import_transactions(file_path="/tmp/acme_transactions.csv", dry_run=true)` | `status: "needs_normalizer"`, `first_20_lines` present, `message` points to `_example.py` |
| 5.3 | Read the example normalizer | Claude | Read `inputs/transaction_normalizers/_example.py` | Understand the protocol (detect + normalize functions) |
| 5.4 | Read the sample lines | Claude | From step 5.2 response `first_20_lines` | Identify column mapping |
| 5.5 | Write normalizer | Claude | Write `~/.risk_module/transaction_normalizers/acme.py` with `detect(lines)` and `normalize(lines, filename)` matching the Acme CSV format | File created with correct protocol |
| 5.6 | Dry run again | Claude | MCP `import_transactions(file_path="/tmp/acme_transactions.csv", dry_run=true)` | `status: "ok"`, trades detected, `brokerage: "Acme Brokerage"` |
| 5.7 | Import for real | Claude | MCP `import_transactions(file_path="/tmp/acme_transactions.csv", dry_run=false)` | Transactions saved |
| 5.8 | Verify in store | Claude | MCP `list_transactions(source="all")` | Acme trades present |
| 5.9 | Clean up | Claude | Delete `/tmp/acme_transactions.csv` and `~/.risk_module/transaction_normalizers/acme.py` | Cleaned |

---

### Phase 6: Broker Connection Paths (UI Verification)

**Goal**: Verify each connection flow renders correctly in the wizard. Live connections are optional (user-assisted).

| # | Step | Actor | How | Verify |
|---|------|-------|-----|--------|
| 6.1 | Open wizard, click "Connect a brokerage" | Claude | Click Connect card | InstitutionPicker modal appears with Popular Providers grid |
| 6.2 | Select a Plaid institution (e.g., Vanguard) | Claude | Click Vanguard | ConnectionFlow renders with "A Plaid window will open in a new tab" |
| 6.3 | Screenshot Plaid flow UI | Claude | Screenshot | Plaid flow card visible, status polling |
| 6.4 | Go back, select a SnapTrade institution (e.g., Fidelity) | Claude | Back → click Fidelity | ConnectionFlow renders with "Finish the connection in the popup" + "I've completed it" button |
| 6.5 | Screenshot SnapTrade flow UI | Claude | Screenshot | SnapTrade flow card + manual confirm button visible |
| 6.6 | Go back, select Schwab | Claude | Back → click Charles Schwab | ConnectionFlow renders CLI guide with terminal command `python3 -m scripts.run_schwab login` |
| 6.7 | Screenshot Schwab flow UI | Claude | Screenshot | Terminal command box, numbered steps, "Waiting for Schwab login..." status |
| 6.8 | Go back, select Interactive Brokers | Claude | Back → click Interactive Brokers | ConnectionFlow renders Gateway guide with setup instructions |
| 6.9 | Screenshot IBKR flow UI | Claude | Screenshot | Gateway setup steps, port info, "Checking for IB Gateway..." status |
| 6.10 | (Optional) Complete a live connection | **User** | Complete Plaid/SnapTrade popup OR run Schwab CLI OR start Gateway | Wizard detects connection, advances to ProcessingStep |

---

### Phase 7: Post-Import Dashboard Verification

**Goal**: After a successful import (CSV or connection), verify the dashboard renders correctly with real data.

| # | Step | Actor | How | Verify |
|---|------|-------|-----|--------|
| 7.1 | Navigate to dashboard | Claude | Navigate to `localhost:3001` | Dashboard loads |
| 7.2 | Check Portfolio Overview | Claude | Read page | Portfolio value displayed, holdings table populated |
| 7.3 | Check Risk Analysis | Claude | Navigate to risk view (or read risk card) | Risk score, VaR, metrics rendered (not error panels) |
| 7.4 | Check Performance | Claude | Navigate to performance view | Returns/charts rendered |
| 7.5 | Screenshot dashboard | Claude | Screenshot | Full dashboard with data visible |
| 7.6 | Verify no error panels | Claude | Search page for "error", "failed", red banners | None found (or only expected warnings) |

---

### Phase 8: Edge Cases & Error Paths

| # | Test | Actor | How | Verify |
|---|------|-------|-----|--------|
| 8.1 | Upload non-CSV file | Claude | Try uploading a .txt or .pdf in CsvImportStep | Error message shown, not crash |
| 8.2 | Upload empty CSV | Claude | Create empty CSV, upload | Graceful error ("No positions found" or similar) |
| 8.3 | Refresh page mid-wizard | Claude | Navigate away and back during processing | Wizard state recovers or restarts cleanly |
| 8.4 | `onboarding_completed` prevents wizard | Claude | Set localStorage flag, refresh | Dashboard or EmptyPortfolioLanding shows (NOT wizard) |
| 8.5 | Backend down during CSV import | Claude | (If testable) Stop backend, try import | Error shown in wizard, retry button works |
| 8.6 | IBKR status when Gateway not running | Claude | `GET /api/onboarding/ibkr-status` | `gateway_reachable: false`, no crash |
| 8.7 | Schwab status when no token | Claude | `GET /api/onboarding/connection-status?provider=schwab` | `status: "pending"`, no crash |

---

## Execution Order

**Recommended sequence** (each phase builds on the previous):

1. **Phase 1** (fresh state) — establish baseline
2. **Phase 6** (UI verification) — screenshot all 4 flow types without live connections
3. **Phase 2** (CSV wizard import) — the primary happy path
4. **Phase 3** (API-level CSV) — backend validation
5. **Phase 7** (dashboard verification) — confirm data renders
6. **Phase 4** (Schwab transaction import) — known format
7. **Phase 5** (agent normalizer generation) — the full agent workflow
8. **Phase 8** (edge cases) — error handling
9. **(Optional) Phase 6.10** — live broker connection with user assist

**Estimated time**: ~30 minutes for Claude-driven phases, plus user login time.

---

## Success Criteria

- [x] Wizard appears on fresh state (no portfolio)
- [x] CSV import through wizard: preview → confirm → dashboard with data
- [x] All 4 connection flow UIs render correctly (Plaid, SnapTrade, Schwab, IBKR)
- [x] Transaction import auto-detects Schwab CSV
- [x] Unknown CSV triggers `needs_normalizer` → agent writes normalizer → re-import works
- [x] Dashboard loads with real data after import (no error panels)
- [x] Page refresh preserves portfolio (not transient)
- [x] `onboarding_completed` localStorage prevents wizard re-showing — userId bug fixed (`c52f2492`)
- [x] Edge cases don't crash (bad files, missing backend, etc.)

## Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| E1 | Medium | `/auth/status` omitted `user_id` → `onboarding_completed_unknown` | **Fixed** — `c52f2492` |
| E2 | Low | Empty/non-CSV files route to normalizer builder | Deferred — not a crash, just suboptimal UX |
| E3 | Info | Vanguard uses SnapTrade flow, not Plaid | Plan discrepancy — not a bug |
