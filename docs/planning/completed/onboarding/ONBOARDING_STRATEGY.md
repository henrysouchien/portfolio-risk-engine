# Onboarding Strategy — High-Level Flow

**Status:** REFERENCE | **Date:** 2026-03-11 | **Updated:** 2026-03-12

Orientation document for any Claude session working on onboarding, import, or deployment. Links to detailed plans for each phase.

---

## The Problem

A new user faces 30-60 minutes of setup before seeing any value. Full audit in `ONBOARDING_FRICTION_AUDIT.md`.

### Hard Blockers — ALL RESOLVED

| # | Blocker | Time | Status |
|---|---------|------|--------|
| H1 | PostgreSQL database | 15-30 min | **DONE** — Phase A.1 no-DB mode (`ecc66f7d`) |
| H2 | FMP API key | 5 min | Kept (minimal friction, free tier available) |
| H3 | Google OAuth credentials | 10-15 min | **DONE** — Phase A.1 (skipped in MCP mode) |

### Soft Blockers

| # | Blocker | Impact | Status |
|---|---------|--------|--------|
| S1 | No portfolio data | Zero value — blank dashboard | **DONE** — Phase A.2 CSV import (`982022d6`) |
| S2 | Plaid credentials | No live brokerage positions | Phase D **DONE** — credential gates + availability checks (`3046842e`) |
| S3 | IBKR Flex credentials | No IBKR trade history | Phase D **DONE** — IBKR dual-provider cross-check (`3046842e`) |
| S4 | Schwab OAuth (7-day expiry) | No Schwab data | Phase D **DONE** — proactive token monitor + re-auth UX (`3046842e`) |
| S5 | IBKR Gateway running | No live market data / trading | Phase D **DONE** — startup validation warning (`3046842e`) |

### UX Blockers

| # | Blocker | Status |
|---|---------|--------|
| U1 | No onboarding wizard | **REMAINING** — Phase C (plan ready, Codex-reviewed) |
| U2 | No CSV/paste import path | **DONE** — Phase A.2 (`982022d6`) |
| U3 | No `.env` validation | **DONE** — Phase A.3 (`8f480e99`) |
| U4 | No demo/sample portfolio | **REMAINING** — Phase B (quick win, just a JSON fixture) |
| U5 | 50+ MCP tools, no guidance | **REMAINING** — Phase C (wizard) |
| U6 | No setup verification | **DONE** — Phase A.3 `make check` (`8f480e99`) |

### Provider Friction — ADDRESSED

Full provider audit in `ONBOARDING_FRICTION_AUDIT.md` § "Provider Friction Inventory". All 4 friction items addressed in commit `3046842e`:
- Plaid/SnapTrade credential gates (was: empty checks, runtime crash)
- Schwab token monitor (launchd daily 9am check, proactive warning)
- Auth error classification in `handle_mcp_errors` decorator
- IBKR dual-provider cross-check in startup validation

---

## Product Architecture

One codebase, five tiers. `is_db_available()` is the primary gate between local MCP (Tiers 1-2) and hosted web app (Tiers 3-5). See `PRODUCT_TIERS.md` for full breakdown.

```
Tier 1: Open Source MCP (free)     — pip install + own FMP key + CSV import
Tier 2: Hosted Data MCP ($)        — same, but we provide the FMP key
Tier 3: Web App + CSV (free)       — browser-based, CSV upload, limited tools
Tier 4: Web App Full ($)           — live brokerage connections, all tools
Tier 5: Web App + Agent ($$)       — autonomous workflows, monitoring
```

## Onboarding Flow Per Tier

### Tier 1-2: MCP User (Terminal) — FULLY FUNCTIONAL

```
1. pip install portfolio-mcp
2. Set FMP_API_KEY and RISK_MODULE_USER_EMAIL in .env
3. Add to Claude Code: claude mcp add portfolio-mcp -e RISK_MODULE_USER_EMAIL=you@example.com
4. "Import my portfolio CSV" → agent calls import_portfolio(file_path, dry_run=True)
5. Agent reviews dry_run → confirms → import_portfolio(file_path)
6. Full portfolio analysis available immediately
7. "Import my transaction history" → import_transactions(file_path, brokerage="ibkr")
8. Trading analysis, tax harvest, realized performance available
```

**No Postgres. No OAuth. No brokerage API.**

Also available: `make check` validates env vars and dependencies on first run.

**Auth modes across tiers:**
- Tiers 1-2 (MCP): No auth — `RISK_MODULE_USER_EMAIL` env var for user scoping
- Tier 3+ (Web App): Google OAuth by default
- Single-user web app: `AUTH_MODE=local` (Phase B) — auto-creates dev user, skips Google verification

The CSV import pipeline (`import_portfolio` + `import_transactions` MCP tools) is the universal entry point. It works at every tier. Agent-created normalizers are Tier 1 (local MCP) only — hosted tiers use reviewed built-in normalizers.

### Tier 3: Web App + CSV — BACKEND READY, NEEDS WIZARD

```
1. Sign up (Google OAuth)
2. Upload CSV via web UI → same import_portfolio pipeline
3. Dashboard shows portfolio analysis
4. Limited tool access, token cap on agent interactions
```

Backend supports this today. Missing: web UI for CSV upload (Phase C wizard).

### Tier 4-5: Web App Full — BACKEND READY, NEEDS WIZARD

```
1. Sign up (Google OAuth)
2. Onboarding wizard: "Connect your brokerage" or "Import a CSV"
   → Institution-first selection ("I have Schwab")
   → We route to the right provider (Plaid/SnapTrade/Schwab API/IBKR)
3. Positions sync automatically
4. CSV import via web upload for unsupported brokerages (built-in normalizers only)
5. Agent suggests clearing stale CSV data when API is connected
```

Backend supports this today (credential gates, auth error handling, provider routing all in place). Missing: wizard frontend (Phase C).

---

## Implementation Phases

### Phase A: Zero-Infrastructure MCP — COMPLETE
**Plan:** `completed/infrastructure/PHASE_A_NO_INFRA_PLAN.md`

| Step | What | Status | Commit |
|------|------|--------|--------|
| A.1 | No-DB mode (22 tools work without Postgres) | **DONE** | `ecc66f7d` |
| A.2 | CSV position import (`import_portfolio` MCP tool) | **DONE** | `982022d6`, fix `a13c482e` |
| A.3 | Startup validation (`.env` checks, `make check`) | **DONE** | `8f480e99` |

### Phase A+ : Filesystem Transaction Store — COMPLETE
**Plan:** `completed/infrastructure/FILESYSTEM_TRANSACTION_STORE_PLAN.md`

| Phase | What | Status | Commit |
|-------|------|--------|--------|
| A | JSON store + `import_transactions` MCP tool + IBKR parser | **DONE** | `cb9ba87f` |
| B | Wire into trading analysis, tax harvest, realized perf | **DONE** | `1699a83d` |

Remaining (backlog): Schwab CSV parser, Merrill PDF parser.

### Phase B: Lightweight Persistence — DEFERRED
**Plan:** `PHASE_B_LIGHTWEIGHT_PERSISTENCE_PLAN.md`

JSON/YAML backend for baskets, allocations, audit trail. Bypasses Postgres for single-user. Deferred because anyone technical enough to clone the repo can set up Postgres, and CSV import is the real unlock.

**Quick win available**: Sample portfolio (Phase B Step 7) requires no persistence mechanism — just a JSON fixture file. Could be done independently in ~1 hour. Addresses U4.

### Phase C: Onboarding Wizard (Web App) — IN PROGRESS
**Plan:** `ONBOARDING_WIZARD_PLAN.md` (Codex-reviewed, 35 rounds, PASS)

Guided first-run experience for the web app (Tiers 3-5). This is the **primary remaining onboarding work**.

| Phase | What | Status | Dependencies |
|-------|------|--------|-------------|
| 0 | Extract shared components from AccountConnections + routing extension | **DONE** | `61bdb81f` |
| 1 | Wizard MVP (Plaid + SnapTrade brokerage connections) | **DONE** | `de315bf3` |
| 2 | Schwab + IBKR connection flows | Not started | Phase 1 |
| 3 | CSV import path (web UI for upload + preview) | Not started | ~~Phase A.2~~ done |

**Key architecture decisions** (from Codex-reviewed plan):
- `onboardingFallback` prop on `PortfolioInitializer`
- Deferred exit pattern (`resetQueries` only on "Go to Dashboard")
- Direct `refreshHoldings()` call with store-write guard
- Backend CSV cleanup in `save_positions_from_dataframe()` transaction
- Fail-closed wizard routing lookup
- Institution-first broker selection ("I have Schwab" → we route to provider)
- Two paths: "Connect a brokerage" or "Import a CSV"
- Progressive disclosure — don't show all 5 providers

**All backend dependencies are met.** This is purely frontend work:
- CSV import backend: done (Phase A.2)
- Transaction import backend: done (Phase A+)
- Credential validation: done (Phase D)
- Auth error handling: done (Phase D)
- Provider routing: done (existing infrastructure)

### Phase D: Brokerage Connection Friction Reduction — COMPLETE
**Plan:** `completed/infrastructure/BROKERAGE_CONNECTION_FRICTION_PLAN.md` | **Commit:** `3046842e`

All 4 items done:
- [x] `PROVIDER_CREDENTIALS` gaps fixed — Plaid/SnapTrade credential checks + registration gates
- [x] Proactive Schwab token expiry — `check_schwab_token.py` + launchd daily 9am schedule
- [x] Re-auth UX — `_classify_auth_error()` in `handle_mcp_errors` + position/trading auth warnings
- [x] IBKR dual-provider cross-check — startup validation warning in `_validate_environment()`

---

## Key Design Decisions

1. **CSV import is the universal entry point.** Works at every tier, same pipeline, same contract. This is the fastest path to value for any new user.

2. **Dual-path storage is the product architecture.** `is_db_available()` gates filesystem JSON (Tiers 1-2) vs Postgres (Tiers 3-5). Same code, different backend.

3. **CSV → API graduation, not dedup.** Users start with CSV import, then graduate to live API connections. These are sequential states, not concurrent data sources. When API is connected, the user (or agent) clears stale CSV data. No institution-level dedup logic needed.

4. **Agent-created normalizers are the extensibility model.** When a user imports a CSV from an unsupported brokerage, the agent inspects the file, writes a normalizer, and re-runs the import — no manual coding required. This works for **both** positions and transactions (two separate systems, same pattern). Tier 1 (local MCP) only — hosted tiers use reviewed built-in normalizers. See § "Agent-Created Normalizer Pattern" below for details.

5. **Position ingestion contract is the boundary.** `PositionRecord` (frozen dataclass) is what every data source must produce. Validated at construction, immutable after.

---

## Agent-Created Normalizer Pattern

Core extensibility model: ship built-in normalizers for known brokerages, agent creates new ones at runtime for unknown CSV formats. **Two separate systems** — same agent workflow, different interfaces.

### Positions (function-based)

**Location:** `~/.risk_module/normalizers/{brokerage}.py` (runtime) or `inputs/normalizers/{brokerage}.py` (built-in)

**Interface:** Each normalizer is a Python module with two functions:
```python
def detect(df: pd.DataFrame) -> bool:
    """Return True if this CSV matches this brokerage format."""

def normalize(df: pd.DataFrame) -> list[PositionRecord]:
    """Transform raw CSV rows into PositionRecord frozen dataclasses."""
```

**Agent workflow:**
1. User says "Import my portfolio CSV" → agent calls `import_portfolio(file_path, dry_run=True)`
2. If no built-in normalizer matches → import fails with "unknown format"
3. Agent reads the CSV headers, inspects sample rows
4. Agent writes a new `.py` normalizer file to `~/.risk_module/normalizers/`
5. `discover_normalizers()` in `inputs/normalizers/__init__.py` picks it up
6. Agent re-runs `import_portfolio()` → success

**Discovery:** `discover_normalizers()` scans both `inputs/normalizers/` (built-in) and `~/.risk_module/normalizers/` (agent-created). Built-in normalizers take priority.

### Transactions (class-based)

**Location:** `providers/normalizers/{brokerage}.py` (built-in) or agent-created at runtime

**Interface:** Each normalizer is a class implementing:
```python
class MyBrokerageNormalizer:
    provider_name: str = "my_brokerage"

    def can_handle(self, file_path: str) -> bool:
        """Return True if this file matches this brokerage format."""

    def normalize(self, file_path: str) -> tuple[list[NormalizedTrade], list[NormalizedIncome]]:
        """Parse file into normalized trade + income records."""

    def flatten_for_store(self, trades, income) -> list[dict]:
        """Flatten to JSON-serializable dicts for the transaction store."""
```

**Agent workflow:**
1. User says "Import my transaction history" → agent calls `import_transactions(file_path, brokerage="auto")`
2. If no registered normalizer can handle the file → import fails
3. Agent inspects the CSV (headers, sample rows, date formats, column semantics)
4. Agent writes a normalizer class following the interface above
5. Agent registers it in `_NORMALIZER_REGISTRY`
6. Agent re-runs `import_transactions()` → success

**Full design:** `BROKERAGE_STATEMENT_IMPORT_PLAN.md` §§ "Agent-Buildable Normalizer Infrastructure" and "Agent Workflow".

### Tier Gating

| Tier | Position normalizers | Transaction normalizers |
|------|---------------------|------------------------|
| 1-2 (Local MCP) | Built-in + agent-created | Built-in + agent-created |
| 3-5 (Web App) | Built-in only | Built-in only |

Agent-created normalizers execute arbitrary Python code — safe for local MCP (user's own machine), not loaded on shared hosted servers.

---

## Known Limitations & Gaps (Updated)

1. **CSV→API safety guard uses exact string matching.** When API positions exist for a brokerage, CSV positions with matching `brokerage_name` are auto-skipped. Mismatched names (e.g., "Interactive Brokers" vs "IBKR") may slip through. The agent suggests `import_portfolio(action="clear")` to clean up.

2. **No tier detection mechanism.** Product Tiers doc says "feature flags limit tools" for Tier 3, but no plan defines the flags, frontend tier detection, or backend enforcement. Deferred — all web app users get the same experience for now.

3. **Two normalizer systems.** Position normalizers (`inputs/normalizers/`, function-based) and transaction normalizers (`providers/normalizers/`, class-based) are completely separate systems with different interfaces. Both support agent-created normalizers at runtime (Tier 1 only). See § "Agent-Created Normalizer Pattern" above.

4. ~~**Transaction import is DB-only.**~~ **RESOLVED** — Filesystem transaction store (`cb9ba87f`, `1699a83d`) enables full transaction analysis without Postgres.

5. ~~**`PROVIDER_CREDENTIALS` gaps.**~~ **RESOLVED** — Credential gates added (`3046842e`).

6. ~~**IBKR dual-provider.**~~ **ADDRESSED** — Startup cross-check warns when only one of Gateway/Flex is configured (`3046842e`).

---

## Related Documents

| Document | Purpose | Status |
|----------|---------|--------|
| `PRODUCT_TIERS.md` | 5-tier product architecture with config mapping | Active |
| `completed/infrastructure/PHASE_A_NO_INFRA_PLAN.md` | Zero-infrastructure MCP | **DONE** |
| `PHASE_B_LIGHTWEIGHT_PERSISTENCE_PLAN.md` | Lightweight persistence for single-user | Deferred |
| `POSITION_INGESTION_CONTRACT.md` | `PositionRecord` schema + validation rules | Active (reference) |
| `TRANSACTION_INGESTION_CONTRACT_PLAN.md` | Trade/income schema + validation layer | Active (reference) |
| `BROKERAGE_STATEMENT_IMPORT_PLAN.md` | Multi-brokerage CSV→transaction store | Active (Schwab/Merrill remaining) |
| `completed/infrastructure/FILESYSTEM_TRANSACTION_STORE_PLAN.md` | Filesystem JSON store + analysis wiring | **DONE** |
| `ONBOARDING_FRICTION_AUDIT.md` | Friction analysis + provider friction inventory | Active (reference) |
| `ONBOARDING_WIZARD_PLAN.md` | Web app first-run wizard design | **NEXT** |
| `completed/infrastructure/BROKERAGE_CONNECTION_FRICTION_PLAN.md` | Provider credential gates + re-auth UX | **DONE** |
