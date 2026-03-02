# Environment Variable & Config Consolidation

## Context

The env var / config situation is fragmented and already caused a real bug (IBKR client_id collision, commit `63a948a0`). There are ~16 `load_dotenv()` calls scattered across library modules, duplicate env var reads across config files, and a naming mismatch in the frontend. This plan addresses all of it in one pass.

---

## Phase 1: Backend — Remove `load_dotenv()` from Library Modules

Remove `load_dotenv()` from files that are always imported AFTER an entry point has already loaded `.env`. These calls are redundant.

| File | Line(s) | Action |
|------|---------|--------|
| `portfolio_risk_engine/factor_utils.py` | 38,42 | Remove `from dotenv import load_dotenv` + `load_dotenv()` |
| `proxy_builder.py` | ~247-250 | Remove import + `load_dotenv()` |
| `gpt_helpers.py` | 11,14 + 82 | Remove import + TWO `load_dotenv()` calls |
| `snaptrade_loader.py` | ~62 | Remove `load_dotenv()` |

**Keep** `load_dotenv()` in: entry points (`mcp_server.py`, `ibkr/server.py`, `app.py`), standalone packages (`fmp/client.py`), config modules (`ibkr/config.py`, `settings.py`), scripts (`scripts/*.py`).

**Add** `load_dotenv()` to utility entry scripts that currently rely on library-module `load_dotenv()`:
- `run_portfolio_risk.py` — imports `factor_utils` which currently bootstraps env
- `run_snaptrade.py` — imports `snaptrade_loader` which currently bootstraps env
- `run_risk.py` — imports `proxy_builder`/`gpt_helpers` which currently bootstrap env

---

## Phase 2: Backend — Eliminate Duplicate IBKR Vars in `brokerage/config.py`

`ibkr/config.py` is the canonical source for all IBKR env vars. `brokerage/config.py` re-reads 4 of them independently → replace with imports.

**`brokerage/config.py` changes:**
- Remove direct `os.getenv()` reads for `IBKR_READONLY`, `IBKR_AUTHORIZED_ACCOUNTS`, `IBKR_GATEWAY_HOST`, `IBKR_GATEWAY_PORT`
- Add: `from ibkr.config import IBKR_READONLY, IBKR_AUTHORIZED_ACCOUNTS, IBKR_GATEWAY_HOST, IBKR_GATEWAY_PORT`
- Delete `_int_env()` helper (only used for `IBKR_GATEWAY_PORT`, now imported)
- Remove `load_dotenv()` calls (rely on `ibkr/config.py`'s bootstrap + entry point)

No circular import risk: `ibkr/config.py` has zero local imports.

---

## Phase 3: Backend — Delete Dead Brokerage Credential Vars from `settings.py`

These `settings.py` credential vars have no live importers in production code (one test file imports 3 of them — redirected below).

**Delete from `settings.py`:**
- `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SCHWAB_CALLBACK_URL`, `SCHWAB_TOKEN_PATH` (live in `brokerage/config.py`)
- `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, `SNAPTRADE_BASE_URL`, `SNAPTRADE_ENVIRONMENT`, `SNAPTRADE_RATE_LIMIT`, `SNAPTRADE_HOLDINGS_DAILY_LIMIT`, `SNAPTRADE_WEBHOOK_SECRET`, `SNAPTRADE_WEBHOOK_URL`

**Keep in `settings.py`:**
- `SCHWAB_ENABLED`, `SCHWAB_HISTORY_DAYS`, `SCHWAB_TRANSACTIONS_CACHE_PATH` (live importers in `providers/schwab_transactions.py`)
- `ENABLE_SNAPTRADE = True` (feature flag, not a credential — imported by test file)

**Update test:** `tests/snaptrade/test_snaptrade_integration.py` imports `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, `SNAPTRADE_ENVIRONMENT` from `settings`. Redirect these 3 imports to `brokerage.config`. `ENABLE_SNAPTRADE` + `INSTITUTION_PROVIDER_MAPPING` stay imported from `settings`.

**Move `FRONTEND_BASE_URL`:** Change `brokerage/snaptrade/connections.py` to import from `settings` instead of `brokerage.config`, then delete from `brokerage/config.py`. Single source: `settings.py`.

---

## Phase 4: Backend — Standardize `ibkr/server.py` Override

Change `ibkr/server.py` from `override=True` to `override=False`. No IBKR env vars are set in `~/.claude.json` (MCP env vars don't propagate anyway). Consistent with all other entry points.

---

## Phase 5: Backend — Clean Up Dotenv Paths

`ibkr/config.py` tries to load `_pkg_dir / ".env"` (package-local `.env` that doesn't exist) before the project root `.env`. Remove the non-existent path.

| File | Current | After |
|------|---------|-------|
| `ibkr/config.py` | Two `load_dotenv` calls (pkg + parent) | Single: `load_dotenv(_pkg_dir.parent / ".env", override=False)` |
| `brokerage/config.py` | Two `load_dotenv` calls | Removed entirely (Phase 2) |

---

## Phase 6: Frontend — Fix Env Var Naming Mismatch + Document

**Bug:** `loadRuntimeConfig.ts` reads `VITE_API_BASE_URL` but `.env` defines `VITE_API_URL` → falls through to hardcoded default. Works by coincidence in dev (same localhost URL), would break in production.

**Fix `loadRuntimeConfig.ts` (line 59):**
- Change `import.meta.env.VITE_API_BASE_URL` → `import.meta.env.VITE_API_URL`

**Update `.env.example`:** Add missing optional vars referenced in code:
```
VITE_ENABLE_DEBUG=false
VITE_ENABLE_LOGGING=true
VITE_API_TIMEOUT=30000
VITE_ENABLE_SNAPTRADE=true
```

**Not in scope:** Merging `environment.ts` and `loadRuntimeConfig.ts` — they serve different purposes (eager auth config vs lazy runtime config). Not worth the churn.

---

## Files Changed Summary

| Phase | File | Change |
|-------|------|--------|
| 1 | `portfolio_risk_engine/factor_utils.py` | Remove `load_dotenv()` |
| 1 | `proxy_builder.py` | Remove `load_dotenv()` |
| 1 | `gpt_helpers.py` | Remove 2x `load_dotenv()` |
| 1 | `snaptrade_loader.py` | Remove `load_dotenv()` |
| 1 | `run_risk.py`, `run_portfolio_risk.py`, `run_snaptrade.py` | Add `load_dotenv()` at top (compensate for library removal) |
| 2 | `brokerage/config.py` | Import IBKR vars from `ibkr/config.py`, delete `_int_env`, remove `load_dotenv`, delete `FRONTEND_BASE_URL` |
| 3 | `settings.py` | Delete ~15 dead brokerage credential vars |
| 3 | `brokerage/snaptrade/connections.py` | Change `FRONTEND_BASE_URL` import source |
| 3 | `tests/snaptrade/test_snaptrade_integration.py` | Redirect SnapTrade credential imports to `brokerage.config` |
| 4 | `ibkr/server.py` | `override=True` → `override=False` |
| 5 | `ibkr/config.py` | Remove non-existent package `.env` path |
| 6 | `frontend/packages/chassis/src/utils/loadRuntimeConfig.ts` | `VITE_API_BASE_URL` → `VITE_API_URL` |
| 6 | `frontend/.env.example` | Add missing optional vars |

## Codex Review

**R1: FAIL** — Two findings addressed:
1. `SNAPTRADE_WEBHOOK_SECRET` in `routes/snaptrade.py` uses `os.getenv()` directly, not `settings.SNAPTRADE_WEBHOOK_SECRET` → safe to delete from settings. Other SnapTrade var references are in `risk_module_secrets/` (old analysis files), not live code.
2. `run_risk.py`, `run_portfolio_risk.py`, `run_snaptrade.py` lack their own `load_dotenv()` and rely on library modules. Fix: add `load_dotenv()` to these scripts as part of Phase 1.

Both findings incorporated into plan above.

**R2: FAIL** — One additional finding:
- `tests/snaptrade/test_snaptrade_integration.py` imports `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, `SNAPTRADE_ENVIRONMENT` from `settings`. Fix: redirect to `brokerage.config`. `ENABLE_SNAPTRADE` kept in settings (feature flag, not credential).
- `risk_module_secrets/run_*.py` also import affected modules but are outside the main repo (gitignored). No action needed.

Finding incorporated into plan above.

**R3: FAIL (wording only)** — Plan said "zero live importers" but test redirect was already in plan. Fixed wording to "no live importers in production code (one test file redirected below)". All functional checks passed: `brokerage/config.py` has the 3 SnapTrade vars for redirect, no other live importers found.

## Verification

1. `python3 -m pytest tests/ -x -q` — all tests pass
2. `python3 -c "from settings import IBKR_CLIENT_ID, SCHWAB_ENABLED; print('settings OK')"` — imports work
3. `python3 -c "from brokerage.config import IBKR_READONLY, PLAID_CLIENT_ID; print('brokerage OK')"` — re-exports work
4. `python3 -c "from ibkr.config import IBKR_GATEWAY_HOST; print('ibkr OK')"` — standalone works
5. `cd frontend && pnpm build` — frontend builds with no env errors
