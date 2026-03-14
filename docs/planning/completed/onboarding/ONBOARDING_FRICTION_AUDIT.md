# Onboarding Friction Audit
**Status:** ACTIVE

**Date**: 2026-03-08
**Goal**: Make it as easy as possible for a new user to connect their portfolio and get value from the system.

## Context

Three layers of brokerage integration, each with different friction and value:

| Layer | What it powers | Current path | New user friction |
|-------|---------------|--------------|-------------------|
| **Positions** | Risk analysis, optimization, what-if, factor analysis, income projection | SnapTrade/Plaid API | API keys, OAuth, paid accounts |
| **Transactions** | Realized performance, trading analysis, tax harvest, FIFO lots | Schwab API/Plaid/IBKR Flex | Same + historical data window limits |
| **Trading** | Execute trades, order management, rebalance execution | IBKR Gateway | Broker account + Gateway running + client IDs |

For a new user, the unlock order is: Positions first (80% of tool value) → Transactions second → Trading last (advanced users only).

---

## Hard Blockers (system won't start)

| # | Blocker | What it requires | Time | Notes |
|---|---------|-----------------|------|-------|
| H1 | **PostgreSQL database** | Install Postgres, create DB, run schema | 15-30 min | **Addressed by Phase A.1** (no-DB mode, commit `ecc66f7d`). 22 tools work without Postgres. |
| H2 | **FMP API key** | Sign up at financialmodelingprep.com | 5 min | Free tier = 100 calls/day. Required for all pricing, treasury rates, company data. |
| H3 | **Google OAuth credentials** | Create Google Cloud project, OAuth consent screen, get client ID/secret | 10-15 min | **Addressed by Phase A.1** — skipped in MCP mode (no web app). |

**Total minimum setup time: ~30-60 minutes** before a user can even start the system.

---

## Soft Blockers (features won't work)

| # | Blocker | What it gates | Time | Notes |
|---|---------|--------------|------|-------|
| S1 | **No portfolio data** | Everything — blank dashboard, every tool returns nothing | varies | The real wall. User has working system but zero value. |
| S2 | **Plaid credentials** | Live brokerage positions & transactions | 30+ min | Paid ($500+/mo production). Sandbox available but useless for real data. |
| S3 | **IBKR Flex credentials** | IBKR trade history, realized performance | 20-30 min | Requires IBKR account + Flex Query setup on IBKR portal. |
| S4 | **Schwab OAuth** | Schwab positions & transactions | 15 min | Token expires every 7 days. Manual browser re-auth required. |
| S5 | **IBKR Gateway running** | Live market data, trade execution | 30+ min | Java app, requires IBKR account, client ID management. |
| S6 | **MCP server registration** | Claude Code integration | 5 min | Manual `claude mcp add` commands. Three servers to register. |

---

## UX Blockers (friction / confusion)

| # | Blocker | Issue |
|---|---------|-------|
| U1 | **No onboarding wizard** | User sees blank dashboard with no guidance on what to do next. |
| U2 | **No CSV/paste import path** | No way to quickly load positions without an API connection. The simplest current path is raw JSON via `ingest_transactions` MCP tool. |
| U3 | **No `.env` validation** | Missing env vars produce cryptic runtime errors instead of helpful "you need to set X" messages. |
| U4 | **No demo/sample portfolio** | Can't try the system without real data. No way to see what the tools do before committing to setup. |
| U5 | **50+ MCP tools, no guidance** | Overwhelming tool list. No "start here" or recommended first-use flow. |
| U6 | **No setup verification** | No `make check-setup` or health check that validates all dependencies are configured correctly. |

---

## Current Minimum Viable Setup

```bash
# 1. Install Python deps
pip install -r requirements.txt

# 2. Create PostgreSQL DB + run schema
createdb risk_module_db
# (manual schema step — unclear how)

# 3. Create .env
cat > .env << EOF
DATABASE_URL=postgresql://user:password@localhost:5432/risk_module_db
FMP_API_KEY=<from financialmodelingprep.com>
GOOGLE_CLIENT_ID=<from Google Cloud Console>
GOOGLE_CLIENT_SECRET=<from Google Cloud Console>
EOF

# 4. Start backend
uvicorn app:app --port 5001

# 5. Start frontend
cd frontend && npm install && npm run dev

# 6. Register MCP servers (for Claude Code users)
claude mcp add portfolio-mcp -e RISK_MODULE_USER_EMAIL=you@example.com -- python mcp_server.py
claude mcp add fmp-mcp -- python3 -m fmp.server
```

**Result**: System starts, user logs in, sees blank portfolio. No data, no value yet.

---

## Key Insight

Blockers H1-H3 are unavoidable infrastructure setup (~30 min). But blocker **S1** is the real wall — after all that setup, the user has a working system with **zero value** because there's no portfolio data. The only paths to load data are:

1. **Plaid** — expensive, complex OAuth, paid API keys
2. **SnapTrade** — similar complexity
3. **Schwab direct** — requires Schwab developer account + 7-day expiring tokens
4. **IBKR Flex** — requires IBKR account + Flex Query setup
5. **`ingest_transactions` MCP tool** — accepts raw JSON, but no CSV support and requires knowing the exact schema

None of these are "upload a CSV from your brokerage and go." Every brokerage (Schwab, Fidelity, Vanguard, IBKR, Merrill, E*Trade) lets users download CSV exports of positions and transactions. Supporting that would bypass all brokerage API friction entirely.

**User journey insight**: CSV and API are sequential phases, not concurrent data sources.
The user starts with CSV to try the system ("let me see my risk"), then graduates to
API when they want automation ("just keep my positions updated"). No dedup between CSV
and API is needed — the API replaces CSV as the source of truth.

---

## Database Dependency Analysis

### SQLite Compatibility (raw assessment)

**Verdict: Full migration not feasible.** The system is deeply coupled to PostgreSQL:

- **Raw psycopg2 everywhere** — `DatabaseClient` wraps psycopg2 directly, no ORM. All callers use `RealDictCursor`, `psycopg2.sql.SQL()`.
- **JSONB columns** in 12+ tables (raw_data, fetch_metadata, payload, fmp_data, etc.)
- **`::type` casting** in 30+ SQL statements (`%s::jsonb`, `%s::uuid`, etc.)
- **PL/pgSQL triggers** — `update_updated_at_column()`, `prevent_expected_returns_modifications()` applied to 10+ tables
- **pgcrypto UUIDs** — `gen_random_uuid()` as column defaults in 5+ tables
- **SERIAL/BIGSERIAL** auto-increment in 8+ tables
- **Connection pooling** — `psycopg2.pool.SimpleConnectionPool` in `database/pool.py`

### Per-Tool DB Dependency Audit

**22 tools need NO database** (pure computation from positions + FMP data):

> get_positions, export_holdings, get_risk_profile, get_quote, preview_trade,
> preview_futures_roll, execute_trade, execute_futures_roll, preview_option_trade,
> execute_option_trade, get_orders, futures_curve, chain_analysis,
> income_projection, news_events, aliases, signals, stock, quote,
> hedge_monitor, multi_leg_options, get_mcp_context

**2 tools have optional DB** (flag-gated, fall back to API fetching):

> get_trading_analysis, suggest_tax_loss_harvest
> (controlled by `TRANSACTION_STORE_READ` flag)

**36 tools require DB** — but breakdown by *what* they need:

| DB Feature | Tools | Complexity |
|------------|-------|------------|
| **User config** (risk limits, allocations, risk profile) | get_risk_score, get_risk_analysis, set_risk_profile, get_leverage_capacity, run_optimization, run_whatif, run_backtest, compare_scenarios | Key-value storage. Trivial in SQLite or JSON files. |
| **Baskets** (user-defined portfolios) | create/list/get/update/delete_basket, analyze_basket, preview/execute_basket_trade, create_basket_from_etf | Small relational table. Simple SQLite-compatible schema. |
| **Allocations** | set_target_allocation, get_target_allocation | Key-value. Trivial. |
| **Audit trail** | record_workflow_action, update_action_status, get_action_history | Append-only log. Simple schema. |
| **Transaction store** | ingest/list/inspect_transactions, list_ingestion_batches, list_flow_events, list_income_events, refresh_transactions, transaction_coverage | **Heavy Postgres** — JSONB upsert, complex dedup, provider normalization. NOT needed day one. |
| **Performance** | get_performance (mode=realized) | Uses transaction store. `mode=hypothetical` is DB-free. |
| **Factor intelligence** | get_factor_analysis, get_factor_recommendations | Optional basket reads. |
| **Rebalance** | generate_rebalance_trades | Optional allocation reads. |

### Key Insight: Three-Tier Strategy

Full Postgres abstraction is unnecessary. Instead:

1. **No-DB mode** (22 tools) — Works today with graceful fallbacks when DB isn't configured. Core portfolio analysis, pricing, trading, options.
2. **Lightweight persistence** (14 tools) — User config, baskets, allocations, audit trail. Simple key-value / small relational data. SQLite or JSON files trivially support this.
3. **Full Postgres** (24 tools) — Transaction store, realized performance, multi-user auth. Production path. Not needed for onboarding.

A new user gets 22 tools immediately with zero DB. Adding lightweight persistence for config/baskets brings it to 36 tools. Only the transaction store (Phase 2 concern) requires Postgres.

---

## Scoping TODOs

### TODO 1: Graceful No-DB Mode (solves H1 for MCP users) — DONE (`ecc66f7d`)

Make the system start and serve the 22 DB-free tools when no `DATABASE_URL` is configured. DB-dependent tools return a clear "database not configured" error instead of crashing.

**Scope:**
- [x] Audit startup path — does `app.py` / `mcp_server.py` crash without `DATABASE_URL`? Add graceful fallback.
- [x] Add `DB_REQUIRED=false` (default) mode — skip DB connection at startup, lazy-connect when a DB-dependent tool is called
- [x] DB-dependent tools: return `{status: "error", message: "This feature requires a database. Run 'make setup-db' to configure."}` instead of crashing
- [x] Verify all 22 no-DB tools work cleanly without `DATABASE_URL` set

### TODO 2: Lightweight Config Store (extends TODO 1 to 36 tools)

Replace Postgres dependency for user config / baskets / allocations with a backend-agnostic config store. SQLite file or JSON files for single-user, Postgres for multi-user.

**Scope:**
- [ ] Audit `RiskLimitsManager` — what DB calls does it make? Can it fall back to a JSON/YAML config file?
- [ ] Audit basket CRUD — `user_factor_groups` table schema. Simple enough for SQLite?
- [ ] Audit target allocations — same question
- [ ] Audit audit trail — append-only, simple schema
- [ ] Design: `ConfigStore` interface with `PostgresConfigStore` and `SQLiteConfigStore` (or `FileConfigStore`) backends
- [ ] Key decision: SQLite (single file, SQL queries work) vs JSON files (zero deps, simpler but no queries)

### TODO 3: CSV Position Import (solves S1, U2)

Let users upload a brokerage CSV export to load their portfolio. This is the single highest-impact onboarding fix — bypasses all API credential friction.

**Scope investigation:**
- [ ] Collect sample CSV exports from major brokerages (Schwab, Fidelity, Vanguard, IBKR, E*Trade, Merrill) — what columns, what format?
- [ ] Design the column mapping: which fields are required (ticker, shares) vs optional (cost_basis, currency, account)?
- [ ] Where does the imported portfolio live? Current system loads positions from brokerage APIs via `standardize_portfolio_input()` — CSV import needs to feed into the same path
- [ ] Entry points: MCP tool (`import_portfolio`), REST endpoint, frontend drag-and-drop, paste-in-chat?
- [ ] Auto-detection: can we infer the brokerage from CSV headers/structure?
- [ ] Does this need DB persistence, or can it live in-memory / JSON file for no-DB mode?

### TODO 4: Local Auth / Dev Mode (solves H3)

Skip Google OAuth for local development and single-user MCP usage.

**Scope:**
- [ ] How deep is Google OAuth wired in? Is it just the login route, or do user IDs propagate through the whole system?
- [ ] Can we add `AUTH_MODE=local` that auto-creates a dev user and skips OAuth entirely?
- [ ] For MCP-only mode: is auth even needed? The MCP server already uses `RISK_MODULE_USER_EMAIL` env var for user scoping

### TODO 5: Startup Validation & Setup Script (solves U3, U6)

Validate configuration on first run. Helpful error messages instead of cryptic crashes.

**Scope:**
- [ ] Add `.env` validation at app startup — check required vars, print missing ones with setup instructions
- [ ] `make setup` or `python setup.py` — interactive first-run that creates `.env`, sets up DB (if wanted), loads sample data
- [ ] `make check` — non-destructive health check that validates FMP key, DB connection (if configured), schema version

### TODO 6: Sample Portfolio (solves U4)

Ship a realistic demo portfolio so every tool works out of the box.

**Scope:**
- [ ] Design a 15-20 position portfolio (mix of large/mid/small cap, international, ETFs, maybe a bond)
- [ ] Where does it live? JSON fixture file loaded on first run? Or a `--demo` flag?
- [ ] Should it include sample transactions too (for realized performance demo)?

### TODO 7: Docker Compose (alternative path for full-stack users)

For users who want the full system (frontend + DB + all features), provide one-command setup.

**Scope:**
- [ ] `docker-compose.yml` with Postgres + backend + auto-schema migration
- [ ] Volume persistence for DB data
- [ ] Frontend dev server (or serve built frontend from backend)
- [ ] How does this interact with MCP? Claude Code runs locally, MCP server needs to reach the Docker backend

---

## Provider Friction Inventory

**Date:** 2026-03-11

Detailed audit of every brokerage provider's setup flow, env vars, auth requirements, and re-auth cycles. Cross-referenced with `ONBOARDING_WIZARD_PLAN.md` for gap analysis.

### Per-Provider Setup Matrix

| | **Plaid** | **SnapTrade** | **Schwab** | **IBKR Gateway** | **IBKR Flex** |
|---|---|---|---|---|---|
| **Type** | Aggregator | Aggregator | Direct API | Direct (socket) | Historical API |
| **Default enabled** | Yes | Yes | No (`SCHWAB_ENABLED`) | No (`IBKR_ENABLED`) | No (`IBKR_FLEX_ENABLED`) |
| **Env vars** | 3 | 2 | 4 + token file | 3 | 3 |
| **External accounts** | Plaid dev ($) | SnapTrade dev | Schwab dev | IBKR account + Gateway | IBKR account |
| **User auth steps** | OAuth popup | OAuth redirect | CLI + browser | Start Gateway app | Portal: create query |
| **Re-auth cycle** | Rare | Rare | **7 days** | Gateway restart | Never |
| **Total setup steps** | ~5 | ~4 | ~6 | ~5 + local app | ~6 (one-time) |
| **Coverage** | Banks + some brokers | 15+ brokerages | Schwab only | IBKR only (real-time) | IBKR only (historical) |
| **Cost** | $500+/mo production | Free tier available | Free | Free | Free |

### Env Var Requirements

**Plaid** (3 vars, no credential check in `PROVIDER_CREDENTIALS`):
```
PLAID_CLIENT_ID          # OAuth client identifier
PLAID_SECRET             # OAuth client secret
PLAID_ENV                # "sandbox" | "development" | "production"
```

**SnapTrade** (2 vars + per-user secret in AWS Secrets Manager):
```
SNAPTRADE_KEY            # Service account API key
SNAPTRADE_SECRET         # Service account API secret
# Per-user: snaptrade/user/{email} in AWS Secrets Manager
```

**Schwab** (4 vars + token file):
```
SCHWAB_ENABLED=true      # Feature toggle (default: false)
SCHWAB_APP_KEY           # OAuth client ID from developer.schwab.com
SCHWAB_APP_SECRET        # OAuth client secret
SCHWAB_CALLBACK_URL      # Redirect URI (default: https://localhost:8000/callback)
SCHWAB_TOKEN_PATH        # Token file path (default: ~/.schwab_token.json)
# Optional:
SCHWAB_HISTORY_DAYS      # Transaction lookback (default: 365)
SCHWAB_TRANSACTIONS_CACHE_PATH  # Cache file path
```

**IBKR Gateway** (3 vars):
```
IBKR_ENABLED=true        # Feature toggle (default: false)
IBKR_GATEWAY_HOST        # Default: 127.0.0.1
IBKR_GATEWAY_PORT        # Default: 7496
# Optional:
IBKR_CLIENT_ID           # Default: 1
IBKR_TRADE_CLIENT_ID     # Default: CLIENT_ID + 2
IBKR_TIMEOUT             # Default: 10s
IBKR_READONLY            # Default: false
IBKR_AUTHORIZED_ACCOUNTS # Comma-separated account whitelist
IBKR_CONNECTION_MODE     # "ephemeral" | "persistent" (default: ephemeral)
```

**IBKR Flex** (3 vars):
```
IBKR_FLEX_ENABLED=true   # Feature toggle (default: false)
IBKR_FLEX_TOKEN          # Query token from IBKR Flex portal
IBKR_FLEX_QUERY_ID       # Query ID from IBKR Flex portal
# Optional:
IBKR_STATEMENT_DB_PATH   # Statement storage directory
```

### External Account Setup Steps

**Plaid:**
1. Create developer account at plaid.com
2. Create application in dashboard
3. Generate client ID + secret
4. Configure redirect URI
5. **Cost barrier**: Sandbox is free but useless for real data. Development ($) allows 100 live items. Production ($$$).

**SnapTrade:**
1. Create SnapTrade developer account
2. Register application, get service credentials
3. **AWS dependency**: Per-user secrets stored in AWS Secrets Manager (`snaptrade/user/{email}`)
4. Users connect via OAuth redirect URL

**Schwab:**
1. Create account at developer.schwab.com
2. Create application, get App Key + Secret
3. Configure callback URL in Schwab dashboard
4. Run `python3 -m scripts.run_schwab login` (CLI — opens browser)
5. Authenticate with Schwab, approve app access
6. Token saved to `~/.schwab_token.json`
7. **Repeat every 7 days** when refresh token expires

**IBKR Gateway:**
1. Have Interactive Brokers account
2. Download and install IB Gateway (Java app)
3. Start Gateway, log in with IBKR credentials
4. Gateway listens on localhost:7496
5. **Must stay running** — no headless mode for retail accounts

**IBKR Flex:**
1. Log into IBKR Account Management
2. Navigate to Flex Queries
3. Create query (select: Trades, Dividends, Interest, Fees, Cash, Positions)
4. Set date range (~12 months max — **hard IBKR limit, cannot extend**)
5. Generate token
6. Save Query ID + Token to env vars

### Availability Check Gaps

Found during audit of `providers/routing.py` and `settings.py`:

1. **Plaid: no credential check** — `PROVIDER_CREDENTIALS["plaid"] = []` means `is_provider_available("plaid")` returns True even with no `PLAID_CLIENT_ID`/`PLAID_SECRET`. Will fail at runtime when Plaid client tries to initialize.

2. **SnapTrade: no credential check** — `PROVIDER_CREDENTIALS["snaptrade"] = []`. Same issue. Will fail when AWS Secrets Manager lookup runs.

3. **SnapTrade: AWS dependency not documented** — Per-user secrets in Secrets Manager adds hidden deployment friction. A local dev can't use SnapTrade without AWS configured.

### Re-Auth Friction Ranking (worst → best)

1. **Schwab** (worst) — 7-day refresh token expiry. `check_token_health()` warns at ≤1 day remaining but only on-demand. No proactive notification. User must run CLI command. **No scheduled health check exists.**

2. **Plaid** — Rare but unpredictable. Item errors can require re-link. `create_update_link_token()` handles it, but error detection is passive (fails on next data fetch).

3. **SnapTrade** — Server-managed. Connections can be `disabled: true` but this is uncommon. Detection via `check_snaptrade_connection_health()`.

4. **IBKR Gateway** — Only fails if user restarts Gateway or it crashes. No token expiry. Auto-reconnect with backoff.

5. **IBKR Flex** — Token never expires. Only changes if user regenerates in IBKR portal.

### Onboarding Wizard Plan Coverage

The `ONBOARDING_WIZARD_PLAN.md` already addresses:
- ✅ Institution-first broker selection (user picks "Schwab", not "SnapTrade")
- ✅ All 4 flow types: `hosted_link`, `hosted_ui`, `cli_oauth`, `gateway_guide`
- ✅ CSV import fallback path
- ✅ Provider routing API extensions
- ✅ Phased rollout (P1: aggregators, P2: direct providers)
- ✅ EmptyPortfolioLanding as fallback surface

Gaps not covered by the wizard plan:
- ❌ **Plaid/SnapTrade `PROVIDER_CREDENTIALS` empty** — `is_provider_available()` lies
- ❌ **SnapTrade AWS Secrets Manager dependency** — hidden deployment friction
- ❌ **IBKR needs TWO providers** — Gateway (live positions) + Flex (historical transactions). Wizard only mentions Gateway. Complete IBKR setup needs both.
- ❌ **No proactive Schwab token expiry notification** — `check_token_health()` is on-demand only. No cron/scheduled warning before 7-day expiry.
- ❌ **No unified connection health dashboard** — wizard proposes `GET /api/onboarding/status` but no persistent "your Schwab expires in 2 days" surface in the frontend post-onboarding.

---

## Priority Order

**Phase A — "MCP works with zero infrastructure":**
1. **TODO 1 (No-DB mode)** — Quick win. System starts without Postgres, 22 tools work immediately.
2. **TODO 3 (CSV import)** — Gets real portfolios in without any API credentials.
3. **TODO 5 (Startup validation)** — Clear error messages when things are missing.

**Phase B — "Full single-user experience":**
4. **TODO 2 (Lightweight config store)** — SQLite/JSON for user config, baskets, allocations. Brings tool count to 36.
5. **TODO 4 (Local auth)** — Skip Google OAuth for dev/MCP mode.
6. **TODO 6 (Sample portfolio)** — Try before committing to setup.

**Phase C — "Onboarding Wizard" (web app first-run):**
See `ONBOARDING_WIZARD_PLAN.md`. Guided first-run with brokerage selection + CSV upload.

**Phase D — "Brokerage Connection Friction Reduction":**
Fix `PROVIDER_CREDENTIALS` gaps, proactive Schwab re-auth, IBKR dual-provider setup.

**Infrastructure — Docker Compose (separate track):**
Docker Compose for full-stack setup is an infrastructure item, not an onboarding phase.

### Onboarding target after Phase A

```
git clone <repo>
pip install -r requirements.txt
cat > .env << 'EOF'
FMP_API_KEY=your_key
RISK_MODULE_USER_EMAIL=you@example.com
EOF
claude mcp add portfolio-mcp -e RISK_MODULE_USER_EMAIL=you@example.com -- python mcp_server.py

# Then in Claude:
> "import my portfolio from this CSV" (attach brokerage CSV export)
> "what's my risk analysis?"
> "run an optimization"
```

No Postgres. No Google OAuth. No Plaid. No broker API credentials. Just an FMP key and a CSV.

---

## Cross-Plan Audit Findings (2026-03-11)

Issues identified during cross-plan consistency audit:

1. **Two normalizer systems** — Position normalizers (`inputs/normalizers/`, function-based, raw lines) vs transaction normalizers (`providers/normalizers/`, class-based, parsed dicts). Different interfaces, different outputs. Documented in Phase A plan's "Two Normalizer Systems" section.

2. **`position_source` format** — No-DB path must use `"csv_{source_key}"` (not bare `"csv"`) to match DB path's `LIKE 'csv_%'` query. Fixed in Phase A plan.

3. **CSV→API graduation with safety guard** — Users graduate from CSV to API (sequential states). Lightweight safety guard in `get_all_positions()` auto-skips CSV positions when API data exists for the same `brokerage_name`. Agent suggests `import_portfolio(action="clear")` to remove stale CSV data. No institution alias governance needed.

4. **Sample portfolio** — Listed in Phase B but requires no persistence mechanism. Consider pulling into Phase A as a JSON fixture.

5. **Transaction import is DB-only** — No no-DB path for `BROKERAGE_STATEMENT_IMPORT_PLAN.md`. Onboarding story should note this limitation.

6. **Wizard CSV endpoints vs Phase A MCP tool** — Both wrap the same backend, but dual-interface not explicitly coordinated. Strategy doc updated with note.

---

## Related Documents

| Document | Purpose |
|----------|---------|
| `ONBOARDING_STRATEGY.md` | High-level onboarding flow, tier architecture, phase sequencing |
| `ONBOARDING_WIZARD_PLAN.md` | Web app first-run wizard design (Phase C) |
| `PHASE_A_NO_INFRA_PLAN.md` | Zero-infrastructure MCP implementation (Phase A) |
| `PHASE_B_LIGHTWEIGHT_PERSISTENCE_PLAN.md` | Lightweight persistence for single-user (Phase B) |
| `POSITION_INGESTION_CONTRACT.md` | `PositionRecord` schema + validation rules (position import) |
| `TRANSACTION_INGESTION_CONTRACT_PLAN.md` | Trade/income schema + validation layer (transaction import prerequisite) |
| `BROKERAGE_STATEMENT_IMPORT_PLAN.md` | Multi-brokerage CSV→transaction store infrastructure (IBKR, Schwab, agent-built) |
| `STATEMENT_IMPORT_PLAN.md` | IBKR Activity Statement CSV import (Phase 1 of statement import) |
| `PRODUCT_TIERS.md` | 5-tier product architecture with config mapping |
| `TODO.md` | Active work items — "Brokerage Connection Friction Reduction" section |
