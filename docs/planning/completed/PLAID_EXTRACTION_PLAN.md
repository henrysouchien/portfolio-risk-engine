# Extract Plaid into `brokerage/plaid/` + sync to public repo — COMPLETED 2026-02-24

**Status:** Implemented, synced to public repo, shipped as brokerage-connect v0.2.0.

## Context
The brokerage-connect package shipped to GitHub with Schwab, SnapTrade, and IBKR — but Plaid was excluded. `plaid_loader.py` (1,657 lines) has the same pure-API / normalization split as SnapTrade. The pure API layer (Plaid SDK calls, AWS secrets, connection management) should move into `brokerage/plaid/`, with normalization staying in `plaid_loader.py`.

## What moves vs stays

### Moves → `brokerage/plaid/`
| Function | Lines | Module | Deps |
|----------|-------|--------|------|
| Plaid client setup (config, `create_client()`) | 60-91 | `client.py` | plaid SDK, certifi, env vars |
| `create_hosted_link_token()` | 107-172 | `client.py` | plaid SDK |
| `wait_for_public_token()` | 186-225 | `client.py` | plaid SDK, time |
| `get_institution_info()` | 240-274 | `client.py` | plaid SDK |
| `fetch_plaid_holdings()` | 405-473 | `client.py` | plaid SDK, logging |
| `fetch_plaid_balances()` | 486-557 | `client.py` | plaid SDK, logging |
| `store_plaid_token()` | 288-324 | `secrets.py` | boto3 |
| `get_plaid_token()` | 327-349 | `secrets.py` | boto3, logging |
| `list_user_tokens()` | 352-375 | `secrets.py` | boto3 |
| `delete_plaid_user_tokens()` | 1538-1589 | `secrets.py` | boto3, logging |
| `remove_plaid_connection()` | 1509-1536 | `connections.py` | plaid SDK, logging |
| `remove_plaid_institution()` | 1592-1654 | `connections.py` | boto3, plaid SDK, logging |

### Stays in `plaid_loader.py` (normalization — uses SecurityTypeService, PortfolioData, settings)
- `normalize_plaid_holdings()`, `get_enhanced_security_type()`, `_map_plaid_type_to_internal()`
- `convert_plaid_holdings_to_portfolio_data()`, `convert_plaid_df_to_yaml_input()`
- `load_all_user_holdings()`, `consolidate_holdings()`
- Cash gap functions: `calc_cash_gap()`, `append_cash_gap()`, `patch_cash_gap_from_balance()`, `should_skip_cash_patch()`, `map_cash_to_proxy()`, `_load_maps()`

## New files

### `brokerage/plaid/__init__.py`
Re-export all public names (same pattern as `brokerage/snaptrade/__init__.py`).

### `brokerage/plaid/client.py`
- `create_client()` → factory function (replaces module-level client setup)
- Move `create_hosted_link_token`, `wait_for_public_token`, `get_institution_info`, `fetch_plaid_holdings`, `fetch_plaid_balances`
- Replace `from utils.logging import ...` → `from brokerage._logging import ...`
- `fetch_plaid_holdings` and `fetch_plaid_balances` use `plaid_logger`, `log_error`, `log_service_health`, `log_critical_alert` — shim what we can, make the rest no-ops

### `brokerage/plaid/secrets.py`
- Move `store_plaid_token`, `get_plaid_token`, `list_user_tokens`, `delete_plaid_user_tokens`
- Same boto3 pattern as `brokerage/snaptrade/secrets.py`

### `brokerage/plaid/connections.py`
- Move `remove_plaid_connection`, `remove_plaid_institution`

## Changes to existing files

### `brokerage/_logging.py`
Add `plaid_logger` + additional logging shims:
- Import `plaid_logger`, `log_critical_alert`, `log_service_health`, `log_alert`, `log_event` from monorepo
- Fallback: `plaid_logger` = `_make_fallback_logger("plaid")`
- `log_critical_alert`, `log_service_health`, `log_alert`, `log_event` = no-op fallbacks
- **Fix `log_error` signature** — add `**kwargs` to fallback so `correlation_id=` kwarg doesn't raise `TypeError` in standalone mode

### `brokerage/config.py`
Add Plaid env vars:
```python
PLAID_CLIENT_ID: str = os.getenv("PLAID_CLIENT_ID", "")
PLAID_SECRET: str = os.getenv("PLAID_SECRET", "")
PLAID_ENV: str = os.getenv("PLAID_ENV", "production")
AWS_DEFAULT_REGION: str = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
```

### `brokerage/pyproject.toml` (monorepo)
Add `plaid` optional dep group:
```toml
plaid = ["plaid-python", "certifi", "boto3", "botocore"]
```

### `plaid_loader.py` (monorepo)
Replace extracted functions with re-imports from `brokerage.plaid.*` at top of file (same pattern as `snaptrade_loader.py`). Keep all normalization functions in place. The module-level `client` global re-exports the extracted singleton (same pattern as SnapTrade's `snaptrade_client`):
```python
from brokerage.plaid.client import client, create_client
```

Preserve `AWS_REGION` for consumers (`run_plaid.py` imports it):
```python
from brokerage.config import AWS_DEFAULT_REGION
AWS_REGION = AWS_DEFAULT_REGION
```

**Re-export checklist** (all names imported by consumers must remain available from `plaid_loader`):
- `client` (module-level Plaid API client) — `routes/plaid.py`, `run_plaid.py`, `providers/plaid_positions.py`, `services/position_service.py`
- `AWS_REGION` — `run_plaid.py`
- `create_hosted_link_token` — `routes/plaid.py`, `run_plaid.py`
- `wait_for_public_token` — `routes/plaid.py`
- `get_institution_info` — `routes/plaid.py`
- `store_plaid_token` — `routes/plaid.py`
- `list_user_tokens` — `routes/plaid.py`, `run_plaid.py`
- `remove_plaid_connection` — `routes/plaid.py`
- `delete_plaid_user_tokens` — `routes/plaid.py`, `run_plaid.py`
- `remove_plaid_institution` — `run_plaid.py`
- `fetch_plaid_holdings`, `fetch_plaid_balances` — used internally by `load_all_user_holdings` (stays)
- Normalization functions stay in place, no re-export needed

### `pyproject.toml` (public brokerage-connect repo)
Add `plaid` optional dep group.

### `README.md` (public brokerage-connect repo)
Add Plaid row to supported brokers table.

## Steps

1. **Add logging shims** — update `brokerage/_logging.py` with `plaid_logger`, `log_critical_alert`, `log_service_health`, `log_alert`, `log_event`
2. **Add config** — add Plaid env vars to `brokerage/config.py`
3. **Create `brokerage/plaid/`** — `__init__.py`, `client.py`, `secrets.py`, `connections.py`
4. **Update `plaid_loader.py`** — replace extracted functions with re-imports from `brokerage.plaid.*`, keep normalization code
5. **Update monorepo `pyproject.toml`** — add `plaid` optional dep
6. **Sync to public repo** — run `scripts/sync_brokerage_connect.sh`
7. **Update public repo** — patch `pyproject.toml` (add plaid deps), update `README.md`
8. **Commit & push** both repos
9. **Update docs** — `RELEASE_PLAN.md`, `BROKERAGE_CONNECT_PLAN.md`

## Verification
1. `python -c "from brokerage.plaid.client import create_client"` works in monorepo
2. `from plaid_loader import client, create_hosted_link_token` still works (re-exports)
3. `pytest tests/ -x` passes (zero consumer breakage)
4. Clean venv install of brokerage-connect, `from brokerage.plaid.client import create_client` works standalone
5. Scrub audit — no secrets/hardcoded paths in new files

## Critical files
- `plaid_loader.py` — source, becomes re-export shim for extracted functions
- `brokerage/_logging.py` — needs new shims
- `brokerage/config.py` — needs Plaid env vars
- `brokerage/snaptrade/` — reference pattern for the split
- `routes/plaid.py`, `run_plaid.py`, `providers/plaid_positions.py` — consumers (should not need changes)

## Codex Review Findings (2026-02-23)

### P0 — Fixed
- **`AWS_REGION` consumer break**: `run_plaid.py` imports `AWS_REGION` from `plaid_loader`. Added to re-export checklist above.

### P1 — Fixed / Noted
- **`log_error` signature**: fallback shim lacks `**kwargs`, will break on `correlation_id=` kwarg. Plan updated to fix.
- **Client singleton**: changed from `create_client()` to re-exporting the extracted `client` singleton (matches SnapTrade pattern).
- **`get_user_plaid_holdings` / `get_user_plaid_accounts`**: imported by `routes/provider_routing.py` but **not defined** in `plaid_loader.py`. Pre-existing issue, out of scope for this extraction.

### P2 — Noted
- **`fetch_plaid_balances` range**: clarified as lines 486-557 (not "486-end").
- **Re-export checklist**: added explicit symbol list with consumer file references.
