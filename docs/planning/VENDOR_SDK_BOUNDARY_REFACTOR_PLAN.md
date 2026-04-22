# Vendor SDK Boundary Refactor

**Status:** v9 — addresses Codex round 8 PASS-WITH-CHANGES (1 rollout-story reconciliation).

## Context

A separate effort (`API_BUDGET_GUARD_PLAN.md`, paused) tried to add centralized API cost guards in response to a $342 unexpected Plaid bill. Four review rounds revealed the codebase has no real vendor-SDK boundary today: `providers/plaid_loader.py:15` and `brokerage/plaid/client.py:314` both expose a module-level `client`; `brokerage/plaid/__init__.py:4` re-exports it; `brokerage/snaptrade/__init__.py:2` exports `snaptrade_client`; `brokerage/schwab/__init__.py:2` exports `get_schwab_client`; `brokerage/snaptrade/adapter.py:281+` calls the SDK directly despite `client.py` being the supposed wrapper; `brokerage/ibkr/adapter.py` imports `ib_async` directly even though `ibkr/` is the IBKR home; ~15+ external files import vendor SDKs directly. Existing public boundary functions (`fetch_plaid_balances(access_token, client)`, `remove_plaid_connection(access_token, client)`) take the raw client as a parameter, which forces callers to acquire it externally.

This plan introduces the canonical boundary per provider, refactors public functions to acquire clients internally (so callers never need to touch a raw client), removes raw-client exports from every location they leak, refactors all out-of-boundary callers, and adds a two-rule import lint (forbidden vendor packages + forbidden import paths). After this lands, the cost-guard PR becomes a one-line addition inside each boundary function.

**Scope: all 7 providers in one plan**, implemented as **9 sequential PRs** (1 test-infra + 7 per-provider + 1 final blocker flip).

**Non-goals:** changing provider behavior, adding rate limits/retries, refactoring business logic inside `providers/*_loader.py`. The loader files are accepted as **transitional** boundary files — they hold real business logic that won't be untangled here, but the plan forbids any *new* external imports targeting them.

---

## Architecture: boundary = curated file allowlist + canonical-import rule

### Two-rule model

**Rule A — Vendor-package allowlist.** Vendor SDK imports (and direct HTTP-to-vendor URLs) are confined to a curated list of files per vendor. Files outside the list may not `import plaid`, `from snaptrade_client import ...`, etc.

**Rule B — Canonical-import allowlist.** External code (anything outside a provider's boundary file allowlist) may import only from the **provider's package init** — never from internal modules. Specifically:
- ✅ `from brokerage.plaid import fetch_plaid_balances`
- ❌ `from brokerage.plaid.client import fetch_plaid_balances` (bypasses init)
- ❌ `from brokerage.plaid.client import client` (raw client)
- ❌ `from providers.plaid_loader import client` (legacy loader; **transitional only**)
- ❌ `from brokerage.plaid import client` (raw export; removed)
- ❌ `from brokerage.schwab import get_schwab_client` (raw factory; removed)

Rule B catches the gap Codex flagged: deleting names from `__all__` does not stop `from brokerage.plaid.client import create_client`. The path itself must be forbidden.

**Rule B baseline / grandfather mechanism (Codex rounds 2–4).** Existing code already violates Rule B; landing it strict in PR 1 would red the suite. The lint ships with a **generated baseline artifact at `tests/api_budget/rule_b_baseline.json`** — NOT an ad-hoc inline constant.

**Generator script:** `scripts/generate_rule_b_baseline.py` runs the lint over the repo, normalizes paths to repo-relative, sorts entries deterministically, and writes the JSON file. PR 1 includes both the generator and the captured baseline. Each per-provider PR re-runs the generator after its refactor and commits the updated baseline (smaller than before). Reviewers can diff the JSON to see which entries were retired.

**Strict equality assertion (Codex round 4):** the lint test asserts `computed_violations == baseline_set` (set equality), NOT `computed_violations.issubset(baseline_set)`. This means stale baseline entries — refactored callers that still appear in the JSON — fail the test. Forces per-PR shrinkage discipline: if you removed the violation, you MUST also remove it from the baseline.

**Diff-style failure output (Codex round 5):** on mismatch, the test prints two clearly-labeled lists — `unexpected violations (new — refactor or grandfather)` and `stale baseline entries (refactored — remove from baseline JSON)`. Avoids whack-a-mole when a PR introduces both shapes simultaneously.

**Parallel-PR workflow (Codex round 5):** if two PRs land in parallel, both regenerating the baseline, merge conflicts on `tests/api_budget/rule_b_baseline.json` are likely. Workflow: **rebase onto latest `main`, rerun `python scripts/generate_rule_b_baseline.py`, never hand-merge the JSON.** Documented in PR1 with a CONTRIBUTING note next to the generator script.

**Note on the apparent contradiction with "deliberately permissive scaffold" (Codex round 3):** Rule A's `VENDOR_BOUNDARY_ALLOWLIST` starts empty in PR 1 and grows per-provider PR — that's the "permissive scaffold." Rule B's `RULE_B_BASELINE` is captured fully in PR 1 and SHRINKS per-provider PR. Different mechanisms, different directions, both ship in PR 1.

Concrete baseline entries (from Codex catches across rounds 1–3; PR 1 capture will surface any others):
- `tests/api/test_snaptrade_integration.py:29` → migrated in SnapTrade PR 3
- `tests/snaptrade/test_snaptrade_registration.py:17` → migrated in SnapTrade PR 3
- `tests/snaptrade/test_snaptrade_credentials.py:13` → migrated in SnapTrade PR 3
- `tests/snaptrade/test_snaptrade_recovery.py:12, 16` (uses `import brokerage.snaptrade.recovery as ...`) → migrated in SnapTrade PR 3
- `tests/providers/test_plaid_loader.py:8` → migrated in Plaid PR 2
- `tests/test_schwab_positions.py:9` → migrated in Schwab PR 4
- `tests/ibkr/test_client.py:24` → migrated in IBKR PR 5

Each per-provider PR (a) refactors its listed test files to use the public boundary or `@pytest.mark.real_provider(env=(...))`, and (b) removes the corresponding entries from `RULE_B_BASELINE`. PR 9 verifies the baseline is empty.

Tests inside `tests/api_budget/` (the lint's own home) are exempt — they need to import internals to verify enforcement.

### Per-provider boundary table

| Provider | Boundary file allowlist | Public API path | Vendor packages |
|---|---|---|---|
| Plaid | `brokerage/plaid/*.py`, `providers/plaid_loader.py` (transitional), `providers/plaid_positions.py` | `brokerage.plaid` | `plaid`, `plaid.api`, `plaid.model.*` |
| SnapTrade | `brokerage/snaptrade/*.py`, `providers/snaptrade_loader.py` (transitional) | `brokerage.snaptrade` | `snaptrade_client`, `snaptrade_client.exceptions` |
| Schwab | `brokerage/schwab/*.py`, `providers/schwab_positions.py`, `providers/schwab_transactions.py`, `providers/normalizers/schwab.py` | `brokerage.schwab` | `schwab`, `schwab.orders`, `schwab.auth` |
| IBKR | `ibkr/*.py`, `options/portfolio_greeks.py` (uses `ib_async.Option`), `brokerage/ibkr/adapter.py` (uses dedicated `client_id`) | `ibkr` | `ib_async`, `ib_insync` |
| OpenAI | `providers/completion.py` | `providers.completion` (instance methods) | `openai` |
| Anthropic | `providers/completion.py` | `providers.completion` (instance methods) | `anthropic` |
| FMP | `fmp/client.py`, `fmp/estimates_client.py` (NEW) | `fmp` | `requests` calls to `financialmodelingprep.com` and `financialmodelupdater.com` |

### Public API discipline — boundary functions own client acquisition

Codex round 1 caught that public functions like `fetch_plaid_balances(access_token, client)` and `remove_plaid_connection(access_token, client)` (`brokerage/plaid/client.py:73`, `brokerage/snaptrade/connections.py:24`) require the *caller* to obtain the raw client first — defeating the boundary. Same for Schwab where `brokerage/schwab/__init__.py:2` exports `get_schwab_client`.

**v2 rule:** every public boundary function takes domain types only (access_token, account_id, user_email, request_payload). The function acquires the SDK client internally via a private helper (`_get_or_create_client()`). The raw client is never returned to or accepted from external callers.

**Memoization is required and MUST be thread-safe (Codex rounds 2 + 3).** `_get_or_create_client()` MUST be memoized at module level using `functools.lru_cache(maxsize=1)` — NOT raw `global _client` lazy-init. Reason: FastAPI runs request handlers in threads under default config; concurrent first-use inside one worker can race with `if _client is None`. `lru_cache` uses an internal lock and is thread-safe. Pattern:

```python
# brokerage/plaid/client.py
import functools

@functools.lru_cache(maxsize=1)
def _get_or_create_client() -> "plaid_api.PlaidApi":
    return create_client()
```

Same pattern applies to SnapTrade and Schwab. Test: `assert _get_or_create_client() is _get_or_create_client()` — same instance per process.

**On invalidation (Codex round 3):** SnapTrade user-secret rotation is NOT a stale-client problem. The SnapTrade client constructor at `brokerage/snaptrade/client.py:23` only uses *app credentials* (client_id, consumer_key); rotated *user* secrets are passed as separate per-call inputs (`brokerage/snaptrade/recovery.py:91`). So memoization at the client level is safe across user-secret rotations. No invalidation hook needed.

Example refactor:
```python
# Before (brokerage/plaid/client.py:251 — current public signature):
def fetch_plaid_balances(access_token: str, client: "plaid_api.PlaidApi") -> Dict[str, Any]:
    ...

# After (boundary owns acquisition):
def fetch_plaid_balances(access_token: str) -> Dict[str, Any]:
    client = _get_or_create_client()
    ...
```

Schwab equivalent: drop `get_schwab_client` from `brokerage/schwab/__init__.py:2` exports. Replace with operation-shaped functions like `get_account_data(account_hash, *, fields=None)`, `check_token_health()`, `get_account_hashes()`, `get_quote(symbol)`, etc. — each acquires the client internally via a memoized helper. (Names corrected per Codex round 4 — see canonical Schwab section below for the full list.) **Schwab CLI surface:** `scripts/run_schwab.py:16,56` also needs `schwab_login(manual: bool = False)` and `is_invalid_grant_error(exc)`. These are operation-shaped functions, not raw clients — export them from `brokerage/schwab/__init__.py` alongside the others.

**Schwab cache invalidation hook (Codex round 4):** Schwab's existing `schwab_login()` (`brokerage/schwab/client.py:289`) and `invalidate_schwab_caches()` (`brokerage/schwab/client.py:460`) currently clear module-level globals. With `lru_cache`-memoized `_get_or_create_client()`, both of these MUST also call `_get_or_create_client.cache_clear()` so the next call constructs a fresh client with rotated credentials. Required edit in the Schwab PR.

### Transitional rule for `providers/*_loader.py`

These files (Plaid: 500+ lines; SnapTrade: 2000+ lines) hold real business logic (cash gap detection, normalization, multi-token orchestration) that would explode scope to refactor. Plan accepts them as boundary files **but adds an explicit transitional rule:**

> No new external code may import from `providers/plaid_loader.py` or `providers/snaptrade_loader.py`. Existing importers are migrated to `brokerage.<provider>` in the per-provider PR. The loaders themselves remain in the boundary so their internal vendor SDK use is legal.

The lint test enforces this via the canonical-import allowlist (Rule B) for new code, and via per-PR migration of existing importers.

---

## Refactor inventory by provider (v2 — completed inventory)

Sourced from three parallel Explore passes plus Codex round 1 corrections.

### Plaid

**Boundary files (vendor SDK + canonical import allowed):**
- `brokerage/plaid/client.py` — primary SDK wrapper
- `brokerage/plaid/connections.py` — item lifecycle
- `brokerage/plaid/secrets.py` — secret store
- `providers/plaid_loader.py` — TRANSITIONAL (loader/normalization business logic)
- `providers/plaid_positions.py` — positions provider

**Public API additions to `brokerage/plaid/__init__.py`:**
- Existing functions get re-signatured to drop the `client` parameter (acquired internally).
- Add new public functions:
  - `exchange_public_token(public_token: str) -> dict`
  - `get_investments_transactions(access_token: str, *, start_date, end_date, options=None) -> dict`
  - `get_item(access_token: str) -> dict`

**Raw-client export removal — three locations:**
1. `brokerage/plaid/__init__.py:3` — remove `client` from import block; remove from `__all__`
2. `providers/plaid_loader.py:15` — remove `client` and `create_client` from re-exports
3. `brokerage/plaid/client.py:314` — remove module-level `client = ...` (the actual leak source); refactor any internal users to `_get_or_create_client()`

**Out-of-boundary callers to refactor:**
| File:Line | Current | Refactor target |
|---|---|---|
| `routes/plaid.py:942–944` | `from plaid.model.* import ...` + `client.item_public_token_exchange(...)` | `from brokerage.plaid import exchange_public_token` |
| `mcp_tools/connections.py:57` | `from plaid.model.item_public_token_exchange_request import ...` | Remove import |
| `mcp_tools/connections.py:584` | `client.item_public_token_exchange(...)` | `exchange_public_token(...)` |
| `mcp_tools/connections.py:10–21` | `from brokerage.plaid import client, create_client` | Remove `client`/`create_client`; use boundary functions |
| `trading_analysis/data_fetcher.py:415–416,470` | Plaid model imports + `client.investments_transactions_get(...)` | `from brokerage.plaid import get_investments_transactions` |
| `scripts/plaid_reauth.py:16, 97, 102` | `from plaid.model.item_get_request import ItemGetRequest` + `client.item_get(...)` | `from brokerage.plaid import get_item` |
| `scripts/explore_transactions.py:126–127, 176` | Plaid model imports + `client.investments_transactions_get(...)` | Use boundary functions |
| `scripts/run_plaid.py:18` | Direct loader/client import | Use `from brokerage.plaid import ...` |
| `services/position_service.py:1665` | `from providers.plaid_loader import client as plaid_client` | Use `from brokerage.plaid import fetch_plaid_balances/holdings` (no raw client needed) |
| `routes/onboarding.py:24` (Codex round 2; Plaid) | Direct loader/client import | Use boundary functions |
| `routes/plaid.py:157` (Codex round 2) | Direct loader/client import | Use boundary functions |
| `scripts/diagnose_plaid_balances.py:23` (Codex round 2; ACTIVE — referenced in `PLAID_BALANCE_CALL_ELIMINATION_PLAN.md:48`) | Direct loader/client import | Use boundary functions |
| `app.py` (any plaid imports) | Direct vendor imports | Use boundary functions |

**Plaid test files to migrate from RULE_B_BASELINE in this PR (Codex round 3):**
- `tests/providers/test_plaid_loader.py:8` — refactor through `brokerage.plaid` boundary OR add `@pytest.mark.real_provider(env=(...))` if it's an integration test.

### SnapTrade

**Boundary files:**
- `brokerage/snaptrade/*.py` (all sub-modules)
- `providers/snaptrade_loader.py` — TRANSITIONAL

**Public API additions to `brokerage/snaptrade/__init__.py`:**
- Existing functions re-signatured to drop `client` parameter where present.
- Add new public functions:
  - `list_user_brokerage_authorizations(user_email: str) -> list[dict]`
  - `get_account_activities(user_email: str, account_id: str, *, start_date, end_date, offset, limit) -> dict`
  - `list_user_accounts(user_email: str) -> list[dict]`
  - `get_activities(user_email: str, *, start_date, end_date) -> list[dict]` (transactions_and_reporting variant)
- Re-export `SnapTradeApiException` (stop callers from importing `snaptrade_client.exceptions`).

**Raw-client export removal:**
1. `brokerage/snaptrade/__init__.py:2` — remove `snaptrade_client` and `get_snaptrade_client` from import + `__all__`
2. `providers/snaptrade_loader.py` — audit for re-exports of raw client; remove

**Adapter self-violation fix:**
- `brokerage/snaptrade/adapter.py:281, 291, 362, 371` — refactor to call new function in `brokerage/snaptrade/connections.py` (e.g., `refresh_brokerage_authorization(authorization_id, user_email)`).
- **Behavior-change verification (Codex round 2).** This refactor adds the retry decorator (currently absent on the direct adapter call). Required tests:
  - Unit test simulating a `429 Too Many Requests` from `connections.refresh_brokerage_authorization` → assert retry fires per the existing `with_snaptrade_retry` policy and second attempt succeeds.
  - Unit test simulating a SnapTrade secret-rotation 401 → assert the existing `_try_rotate_secret` path still triggers (currently at `brokerage/snaptrade/adapter.py:289`).
  - Integration smoke (manual): trigger a real refresh in dev, verify behavior unchanged.

**Dead-code cleanup:**
- `providers/snaptrade_loader.py:1633-1801` — duplicate SDK call implementations; the names are rebound at line 2165 to extracted implementations from `brokerage/snaptrade/`. Delete the dead block in the SnapTrade PR with a regression test verifying the rebind still works.

**Out-of-boundary callers to refactor:**
| File:Line | Current | Refactor target |
|---|---|---|
| `mcp_tools/connections.py:10–21,57` | `from brokerage.snaptrade import snaptrade_client` + `from snaptrade_client import SnapTrade` | Remove; use boundary functions |
| `mcp_tools/connections.py:257` | `client.connections.list_brokerage_authorizations(...)` | `list_user_brokerage_authorizations(...)` |
| `mcp_tools/connection_status.py:12` | (verify import; refactor if it imports raw client) | Use boundary functions |
| `trading_analysis/data_fetcher.py:238, 287` | `client.account_information.list_user_accounts()`, `client.account_information.get_account_activities(...)` | Boundary functions |
| `scripts/explore_transactions.py:62` | `client.transactions_and_reporting.get_activities(...)` | `get_activities(...)` |
| `scripts/run_snaptrade.py:25` | Direct loader import | Use `from brokerage.snaptrade import ...` |
| `routes/snaptrade.py:151` | (verify; refactor away raw-client import) | Use boundary functions |
| `routes/provider_routing.py:420` | (verify; refactor away raw-client import) | Use boundary functions |
| `services/trade_execution_service.py:46` | `from snaptrade_client.exceptions import ApiException as SnapTradeApiException` | `from brokerage.snaptrade import SnapTradeApiException` |
| `services/position_service.py` (SnapTrade refs) | Direct client access | Boundary functions |
| `routes/onboarding.py:30` (Codex round 3 — was miscategorized as Plaid in v3) | Direct SnapTrade loader/client import | Use `brokerage.snaptrade` boundary functions |
| `providers/routing.py:351` (Codex round 3 — was miscategorized as Plaid in v3) | Direct SnapTrade loader/client import | Use `brokerage.snaptrade` boundary functions |

**SnapTrade test files to migrate from RULE_B_BASELINE in this PR (Codex round 3):**
- `tests/snaptrade/test_snaptrade_credentials.py:13` — refactor through boundary OR add real_provider marker.
- `tests/snaptrade/test_snaptrade_recovery.py:12, 16` — uses `import brokerage.snaptrade.recovery as ...` (caught by Rule B `Import` walker, see Lint section). Refactor through `brokerage.snaptrade` package init.
- `tests/api/test_snaptrade_integration.py` — already in baseline; refactor or `real_provider` marker.

### Schwab

**Boundary files:**
- `brokerage/schwab/*.py`
- `providers/schwab_positions.py`, `providers/schwab_transactions.py`, `providers/normalizers/schwab.py`

**Raw-client export removal — Codex rounds 1 + 3:**
- `brokerage/schwab/__init__.py:2` — currently exports `get_schwab_client`. **Remove.** Replace with operation-shaped boundary functions. Function names below match what already exists in `brokerage/schwab/client.py` (Codex round 3 corrected several invented names from v3):
  - `get_account_data(account_hash: str, *, fields=None) -> dict` (new — wraps `client.get_account`)
  - `get_account_hashes() -> dict[str, str]` (already exists at `brokerage/schwab/client.py`; wraps `client.get_account_numbers` SDK call)
  - `get_transactions(account_hash, *, start_date, end_date) -> list[dict]` (new — wraps `client.get_transactions`)
  - `get_quotes(symbols: list[str]) -> dict` (new)
  - `get_quote(symbol: str) -> dict | None` (new)
  - `search_instruments(symbol, *, projection="symbol-search") -> dict` (new)
  - `get_orders_for_account(account_hash, *, start, end) -> list[dict]` (new)
  - `cancel_order(account_hash, order_id) -> dict` (new)
  - `place_order(account_hash, order_spec) -> dict` (new)
  - `check_token_health() -> dict` (already exists at `brokerage/schwab/client.py`)
  - `schwab_login(manual: bool = False) -> None` (already exists at `brokerage/schwab/client.py:289`; preserve `manual` parameter — used by `scripts/run_schwab.py:56`)
  - `is_invalid_grant_error(exc: Exception) -> bool` (already exists; export from `__init__.py`)
- Each new function acquires the client internally via the memoized `_get_or_create_client()`. Existing functions (`check_token_health`, `get_account_hashes`, `schwab_login`, `is_invalid_grant_error`) keep their current implementations and become exported public API.

**Shim deletion:**
- Delete `providers/schwab_client.py` (3-line re-export shim).

**Vendor import consolidation:**
- `brokerage/schwab/adapter.py:305` — move `from schwab.orders import equities` to top of new `brokerage/schwab/orders.py`.

**Out-of-boundary callers to refactor:**
| File:Line | Current | Refactor target |
|---|---|---|
| `providers/normalizers/schwab.py:461` | Dynamic `from providers.schwab_client import get_schwab_client` inside method | Top-level `from brokerage.schwab.client import get_schwab_client` (still inside boundary file allowlist; this is fine — the consumer is also in allowlist) |
| Existing `from providers.schwab_client import ...` callers | Various | Re-point to `brokerage.schwab` (public API only) |
| `providers/schwab_positions.py:18-19, 92, 99` | Imports + uses `get_schwab_client; client.get_account` | Now in boundary allowlist; calls allowed but should ideally use boundary functions like `get_account_data()` for consistency |
| `providers/schwab_transactions.py:22, 177` | Same | Same |
| `mcp_tools/connection_status.py:11` | `from brokerage.schwab.client import check_token_health` | Re-import via package: `from brokerage.schwab import check_token_health` |
| `scripts/check_schwab_token.py:17`, `scripts/health_check.py:254` | Same | Same |
| `scripts/run_schwab.py:16-19, 56, 134, 142, 144, 173, 184, 186, 202, 213, 219` | `from providers.schwab_client import ...` + direct `client.get_account/get_orders_for_account/get_transactions(...)` + `schwab_login(manual=...)` | Use `brokerage.schwab` public functions (preserves `schwab_login(manual=...)` signature) |

**Schwab test files to migrate from RULE_B_BASELINE in this PR (Codex rounds 3 + 4):**
- `tests/test_schwab_positions.py:9` — refactor through `brokerage.schwab` boundary OR add real_provider marker.
- `tests/services/test_schwab_broker_adapter.py:8` (Codex round 4) — currently imports `brokerage.schwab.adapter` directly (internal-module bypass); refactor through `brokerage.schwab` package init.

### IBKR

**Boundary files:**
- `ibkr/*.py` (all)
- `options/portfolio_greeks.py:163` — uses `ib_async.Option` directly (Codex round 1 catch). Add to allowlist OR refactor to call boundary helper. Plan: **add to allowlist** (smaller scope; the file is options-domain logic that legitimately needs `Option` shape).
- `brokerage/ibkr/adapter.py` — uses dedicated `client_id`; per Codex, do NOT force through default factory; add to allowlist.

**Factory introduction (corrected per Codex rounds 3, 4, 5):**
- `get_ibkr_client(*, client_id=None) -> IBKRClient` in `ibkr/client.py` — returns a **fresh** instance (not cached singleton). **(Codex round 6 honesty:** today `client_id` only flows into market-data client creation at `ibkr/client.py:51`; account/metadata methods still use the default `IBKRConnectionManager()` at `ibkr/client.py:53`. PR5 does NOT redesign this — `get_ibkr_client(client_id=X)` passes the `client_id` to the existing market-data path; account/metadata behavior is unchanged. Documented limitation; expanding `client_id` plumbing is separate scope.)
- `probe_ibkr_connection(*, client_id=None) -> dict` in `ibkr/connection.py` — operation-shaped function returning a **dict** with the same shape `IBKRConnectionManager.probe_connection()` currently returns (preserves existing consumer expectations at `mcp_tools/connection_status.py:331` and `providers/routing.py:336`). The internal singleton manager is NOT publicly exported.
- `get_ibkr_connection_status() -> dict` — read-only state accessor, also returns dict.
- `fetch_flex_report(*, path=None, token=None, query_id=None) -> dict` in `ibkr/flex.py` — **(Codex round 6) this is a RENAME / public-API alias of the existing `fetch_ibkr_flex_payload()` at `ibkr/flex.py:1449`, NOT a new parser path.** The existing helper already returns a parsed structure. PR5 keeps `fetch_ibkr_flex_payload()` private and adds `fetch_flex_report()` as a thin public wrapper.

**`scripts/fetch_ibkr_trades.py` flag preservation (Codex round 7 correction):**
- `--save-xml` (`scripts/fetch_ibkr_trades.py:48`) maps cleanly to a new optional parameter `save_xml_path: str | None = None` on `fetch_flex_report()`; when set, the function writes the raw IBKR Flex XML response to disk before parsing.
- `--raw` (`scripts/fetch_ibkr_trades.py:64`) prints **raw trade attributes/rows from the parsed payload, NOT raw XML** (v7 said XML — corrected). It already operates on parsed data. Behavior preserved by exposing the parsed-but-pre-normalized rows in the returned dict (e.g., a `trades_raw` key alongside the normalized one). No functional regression.

**`brokerage/ibkr/adapter.py` self-violation:**
- It legitimately needs ib_async/ib_insync because of the dedicated `client_id`. Add it to the IBKR boundary allowlist explicitly. Plan does NOT force it through the default factory.

**Public API on `ibkr/__init__.py` — narrowed per Codex round 4:**

Codex round 4 caught that `IBKRConnectionManager.connect()` returns a raw `IB` (`ibkr/connection.py:111, 244`) and `fetch_flex_report` returns a raw `FlexReport`. Even though these are wrapped by in-house facades, the methods leak raw vendor objects to callers. Two fixes:

1. **Don't export `IBKRConnectionManager` directly.** External code that needs connection probing/status uses operation-shaped functions instead:
   - `probe_ibkr_connection(*, client_id=None) -> ProbeResult` (returns a status dict — used by `mcp_tools/connection_status.py:23, 331` and `providers/routing.py:336, 338`)
   - `get_ibkr_connection_status() -> dict` (read-only state)
   The singleton manager remains internal to `ibkr/connection.py`; external callers get parsed status, never the `IB` instance.

2. **`fetch_flex_report` returns parsed data, not raw `FlexReport`.** Signature: `fetch_flex_report(*, path=None, token=None, query_id=None) -> dict` (parsed account/trade rows). The raw `FlexReport` parsing happens inside the boundary function; callers see only normalized dicts. `scripts/fetch_ibkr_trades.py:50, 57` is refactored accordingly.

3. **`IBKRClient` facade audit.** Each public method on `IBKRClient` must return parsed data, not raw `IB`/`Stock`/`Contract` objects. The PR includes an audit step: for each public method, verify return type. Methods that currently return raw vendor objects get wrapped (return parsed dicts). Document any exception case explicitly in the PR description.

**Final `ibkr/__init__.py` exports:**
- `get_ibkr_client`, `IBKRClient` (facade class — methods audited to return parsed data only)
- `probe_ibkr_connection`, `get_ibkr_connection_status` (operation-shaped; replace `IBKRConnectionManager` direct export)
- `fetch_flex_report` (returns parsed dict)
- Do NOT export: `IBKRConnectionManager`, `IB`, `Stock`, `ContractDetails`, `FlexReport`, `Option`, etc.

**Out-of-boundary callers to refactor:**
| File:Line | Current | Refactor target |
|---|---|---|
| `providers/ibkr_positions.py:120, 124, 148` | Dynamic import + `IBKRClient()` + `client.get_portfolio_with_cash(...)` | Top-level `from ibkr import get_ibkr_client`; `get_ibkr_client()` |
| `routes/onboarding.py:593–595` | `from ibkr.client import IBKRClient`, `client = IBKRClient()` | `from ibkr import get_ibkr_client` |
| `services/trade_execution_service.py:3476–3478` | Same | Same |
| `services/position_service.py:28` | `from ibkr.client import IBKRClient` | `from ibkr import get_ibkr_client` |
| `mcp_tools/chain_analysis.py:17, 339` | Same | Same |
| `mcp_tools/options.py:203` | `ibkr_client=IBKRClient()` | Use factory |
| `scripts/run_ibkr_data.py:181, 316, 330` | Direct instantiation | Use factory |
| `scripts/fetch_ibkr_trades.py:50, 57` | `FlexReport(path=...); FlexReport(token=..., queryId=...)` | `fetch_flex_report(path=...)` / `fetch_flex_report(token=..., query_id=...)` |
| `scripts/run_options.py:235` | `ibkr_client=IBKRClient()` | Use factory |
| `mcp_tools/connection_status.py:23, 331` | `from ibkr.connection import IBKRConnectionManager`, `IBKRConnectionManager().probe_connection()` | `from ibkr import probe_ibkr_connection`; use operation function (per Codex round 4 — `IBKRConnectionManager` no longer publicly exported) |
| `providers/routing.py:336, 338` | Same | Same |
| ~~`trading_analysis/data_fetcher.py:141` (Codex round 4)~~ | `from ibkr.compat import ...` | **Removed in v6 (Codex round 5):** `ibkr.compat` is public API; this import is LEGAL. No refactor needed. |
| ~~`providers/ibkr_price.py:22` (Codex round 4)~~ | `from ibkr.compat import ...` | **Removed in v6 (Codex round 5):** same — legal import. |

**IBKR test files to migrate from RULE_B_BASELINE in this PR (Codex round 3):**
- `tests/ibkr/test_client.py:24` — refactor through `ibkr` boundary OR add real_provider marker.

**`ibkr.compat` decision (Codex round 5).** `ibkr/compat.py` is documented as public in `ibkr/README.md:128` and re-exported from `ibkr/__init__.py:25`. v6 keeps it public — it's existing public API with documented consumers (`trading_analysis/data_fetcher.py:141`, `providers/ibkr_price.py:22`). Lint allowlists `ibkr.compat` as a legal external import. The corresponding refactor entries above (which incorrectly said "ibkr.compat is internal") are wrong and removed; both consumers are LEGAL and need no refactor. (The IBKR PR audit will revisit `ibkr.compat`'s API surface to ensure it doesn't itself leak raw vendor objects, but that's an audit step, not a removal.)

### OpenAI / Anthropic

**Boundary file:** `providers/completion.py`.

**Public API discipline:**
- Remove `client` `@property` from `OpenAICompletionProvider` (line 67-77) and `AnthropicCompletionProvider` (line 166-???).
- Replace with private `_get_client()` helper used internally.

**API extension for usage/metadata access (Codex round 1 caught the gap):**
- `scripts/benchmark_editorial_arbiter.py:174-176, 200-202` accesses raw `provider.client` to read response usage tokens (input/output token counts). The current `complete_structured()` returns just the parsed payload — usage is lost.
- **Add a new method:** `complete_structured_with_metadata(...) -> CompletionResult` where:
  ```python
  @dataclass
  class CompletionResult:
      payload: dict        # parsed structured output
      usage: LLMUsage      # input_tokens, output_tokens, model
      raw_metadata: dict   # provider-specific opaque metadata (model, finish_reason, etc.)
  ```
- The benchmark script uses `complete_structured_with_metadata()` and reads `result.usage.input_tokens` / `result.usage.output_tokens`. No raw client access needed.
- This is a **deliberate API extension**, not a `**kwargs` escape valve. The signature is strict; only structured-output kwargs supported by both OpenAI (`response_format`) and Anthropic (`tools`) are accepted (each provider implementation adapts its own SDK call).

**Out-of-boundary callers to refactor:**
| File:Line | Current | Refactor target |
|---|---|---|
| `app.py:177` | `import anthropic` (UNUSED — no call sites in `app.py`; verified by Explore agent) | Delete the import |
| `scripts/benchmark_editorial_arbiter.py:174-176` | `provider = OpenAICompletionProvider(); provider.client.chat.completions.create(...)` + reads response usage | `provider.complete_structured_with_metadata(...)` |
| `scripts/benchmark_editorial_arbiter.py:200-202` | `provider = AnthropicCompletionProvider(); provider.client.messages.create(...)` + reads response usage | Same |

### FMP

**Boundary files:**
- `fmp/client.py` — `FMPClient` (canonical for `financialmodelingprep.com`)
- `fmp/estimates_client.py` (NEW) — wraps `_requests.get(...)` to `https://financialmodelupdater.com`. Treat as separate provider name `fmp_estimates` for future cost-guard purposes.

**Out-of-boundary callers to refactor (Codex round 1 corrected the inventory — most of my v1 list was false positives):**
| File:Line | Current | Refactor target |
|---|---|---|
| `fmp/tools/estimates.py:29-34` | `_requests.get(...)` to `financialmodelupdater.com` | Move HTTP into `fmp/estimates_client.py:get(path, params=None)`; tools/estimates.py calls the new client |
| `scripts/health_check.py:100, 109-110` | `request.urlopen(...)` to `financialmodelingprep.com/api/v3/quote-short/AAPL` | Use `FMPClient` (or a thin `health_check_endpoint()` helper) |

(Codex confirmed `mcp_server.py` and `utils/config.py` were false positives from docstrings.)

---

## Lint enforcement — two-rule import-boundary test

`tests/api_budget/test_import_boundaries.py`:

**Rule A — Vendor-package allowlist:**
1. AST-walks every `.py` file under repo root.
2. Maintains `VENDOR_BOUNDARY_ALLOWLIST` mapping each vendor module (`plaid`, `plaid.*`, `plaid_api`, `snaptrade_client`, `snaptrade_client.*`, `schwab`, `schwab.*`, `openai`, `anthropic`, `ib_async`, `ib_insync`) to the set of boundary files allowed to import it.
3. For each `Import` / `ImportFrom` node referencing a vendor module, asserts the importing file is in the allowlist.
4. Special-case regex grep for: `importlib.util.find_spec("plaid"|"snaptrade_client"|"schwab"|"openai"|"anthropic"|"ib_async"|"ib_insync")`, `importlib.import_module("plaid...")`.

**Rule B — Canonical-import enforcement via WHITELIST of legal names (Codex round 4 — switched from forbidden-regex to allowlist semantics):**

The forbidden-regex approach was incomplete; Codex found bypasses via submodule imports (`from brokerage.snaptrade import recovery`) and attribute-access (`import brokerage.snaptrade as s; s.client...`). v5 inverts the rule: external code may import ONLY explicitly-allowed names from each boundary's package init.

For each provider, the lint maintains:
- `BOUNDARY_LEGAL_IMPORTS = { "brokerage.snaptrade": frozenset([...]), ... }` — the public API surface. **Sourced by AST-parsing each boundary's `__init__.py` (or `.py` for module-boundaries) to extract the literal `__all__` list (Codex round 5 — NOT by importing the boundary at lint-time, because importing has side effects: `brokerage/plaid/client.py:314` constructs a client, `brokerage/snaptrade/client.py:250` constructs `snaptrade_client` and may hit AWS Secrets Manager via `brokerage/snaptrade/secrets.py:53`).** Each boundary declares `__all__` as a literal list. Verified literal-list shape for: `brokerage/plaid/__init__.py:22`, `brokerage/snaptrade/__init__.py:28`, `brokerage/schwab/__init__.py:11`. **`providers/completion.py` does NOT currently have `__all__` (Codex round 6) — PR6 (OpenAI) and PR7 (Anthropic) add it explicitly: `__all__ = ["OpenAICompletionProvider", "AnthropicCompletionProvider", "CompletionResult", "LLMUsage", ...]`.** `fmp/__init__.py` and `ibkr/__init__.py` audited similarly in their respective PRs.
- `BOUNDARY_BANNED_NAMES = { "brokerage.plaid": {"client", "create_client"}, "brokerage.snaptrade": {"snaptrade_client", "get_snaptrade_client"}, "brokerage.schwab": {"get_schwab_client"}, ... }` — names the lint **always** rejects regardless of `__all__` membership (Codex round 5 — protects PR1 from shipping ineffective lint while raw names still appear in `__all__` of unmigrated providers). Per-provider PRs separately remove these names from their boundary `__all__`; the lint enforces the ban from PR1 day one.
- `BOUNDARY_PACKAGE_PATHS = { "brokerage.snaptrade", "brokerage.plaid", "brokerage.schwab", "ibkr", "providers.completion", "fmp", ... }` — the legal import roots.
- `BOUNDARY_PARENT_PACKAGES = { "brokerage", "providers" }` — parent packages whose subpackage attribute access bypasses the boundary (Codex round 5 — `from brokerage import snaptrade` and `from providers import plaid_loader` succeed today against `brokerage/__init__.py:1` and `providers/__init__.py:1`; lint rejects these).

Lint walks BOTH `ImportFrom` AND `Import` AST nodes in every external file (files NOT in any boundary allowlist) and checks:

1. `from <module> import <name>`:
   - If `module` is in `BOUNDARY_PARENT_PACKAGES` AND `name` is the boundary subpackage name (e.g., `from brokerage import snaptrade`, `from providers import plaid_loader`) → **forbidden** (RULE_B_VIOLATION_PARENT_FALLBACK). Codex round 5 caught this: parent packages re-expose subpackages via attribute access; this bypass must be explicitly rejected.
   - If `module` starts with a `BOUNDARY_PACKAGE_PATHS` prefix and is NOT exactly that path (e.g., `from brokerage.snaptrade.recovery import X` — submodule reach-in) → **forbidden** (RULE_B_VIOLATION_SUBMODULE).
   - If `module` is a transitional loader path (`providers.plaid_loader`, `providers.snaptrade_loader`) → **forbidden for new code**, allowed only via baseline grandfather.
   - If `module` is exactly a boundary package path AND `name` ∈ `BOUNDARY_BANNED_NAMES[module]` → **forbidden** (RULE_B_VIOLATION_BANNED_NAME) — overrides `__all__`.
   - If `module` is exactly a boundary package path AND `name` is not in `BOUNDARY_LEGAL_IMPORTS[module]` → **forbidden** (RULE_B_VIOLATION_NAME).
   - If `module` is a vendor SDK or `<vendor>.exceptions` etc → handled by Rule A.

2. `import <module>` (with or without `as`):
   - If `module` starts with a `BOUNDARY_PACKAGE_PATHS` prefix and is NOT exactly that path (e.g., `import brokerage.snaptrade.recovery`) → **forbidden** (RULE_B_VIOLATION_SUBMODULE_IMPORT).
   - If `module` is exactly a boundary package path → allowed (the file gets the package object; subsequent attribute access `pkg.client` is caught by an additional regex check, see below).

3. **Attribute-access regex check** (catches alias-chain bypasses that AST can't statically resolve):
   - For each external file that imports a boundary package directly (`import brokerage.<provider>` with or without `as <alias>`), regex-grep the file for `<alias>\.<banned_name>\.` where `<banned_name>` ∈ `BOUNDARY_BANNED_NAMES[provider]`. Flag matches.
   - **Parent-package alias chain (Codex round 6):** for each external file that imports a parent package (`import brokerage` or `import brokerage as br` or `import providers as p`), regex-grep for `<alias>\.<boundary_name>\.<banned_name>\.` chains (e.g., `br.snaptrade.client.x`, `p.plaid_loader.client.x`). Flag matches. This closes the alias-chain bypass through parent-package attribute access.

4. **Star imports** (`from brokerage.snaptrade import *`) — forbidden in external code regardless of `__all__` contents (force explicit names so violations are inspectable).

Tests inside `tests/api_budget/` (the lint's own home) are exempt — they need to import internals to verify enforcement.

**Documented limits (Codex rounds 6 + 7):** the static lint catches direct imports, attribute-access regex on aliases bound at import-time, and parent-package fallback shapes. It does NOT catch:
- Dynamic patterns: `getattr(brokerage.snaptrade, "client")`, `__import__("plaid")`, `eval("...")`, `globals()["..."]`, monkeypatch.
- **Local alias re-binding (Codex round 7):** `import brokerage as br; sn = br.snaptrade; sn.client.x()` — the local `sn` re-bind is a runtime attribute access that AST cannot resolve to a known import, and the regex check looks for `<alias>.<boundary_name>.<banned_name>.` chains rooted at the imported alias, not arbitrary local names.

Runtime safety net = pytest autouse `_block_real_provider_calls` fixture, which monkeypatches the boundary file's vendor SDK objects to raise `RuntimeError`. Any test path that constructs a vendor object via these uncovered shapes still fails at runtime.

**Special-case regex for raw-client access patterns (outside `providers/completion.py`):**
- `\.client\.(chat|messages|completions)\.`
- `OpenAICompletionProvider\(\)\.client`
- `AnthropicCompletionProvider\(\)\.client`

**Special-case for boundary `__init__.py` exports:**
- Assert `client`, `snaptrade_client`, `get_schwab_client`, `IB`, `FlexReport`, `Stock`, `ContractDetails`, `Option` are NOT in the `__all__` of any boundary `__init__.py`.

**Documented limits:** lint catches static + named dynamic patterns. Won't catch `globals()["plaid_api"]`, `__import__("plaid")`, `eval`, monkeypatching, or `requests.Session.request` patterns. Runtime safety net = pytest autouse blocker.

---

## Test autouse blocker (real-provider opt-in) — corrected scope per Codex

Codex round 1 caught: `pytest_collection_modifyitems` in `tests/api_budget/conftest.py` won't affect `tests/fmp/` or `tests/snaptrade/`. Fix: marker hook lives in **top-level `tests/conftest.py` from PR1**.

**PR 1 (test infrastructure) does ALL of the following so the tooling is functional from day one:**

1. Register marker in `pytest.ini` with strict-marker enforcement:
   ```ini
   [pytest]
   markers =
       real_provider: test makes real external API calls; opt-in via @pytest.mark.real_provider(env=("API_KEY",))
   ```

2. Add `pytest_collection_modifyitems` hook in **`tests/conftest.py`** (top-level):
   - For each item with `@pytest.mark.real_provider`:
     - **Fail collection** if marker has no `env=` kwarg (force explicit declaration; prevents silent passes).
     - For each env var name in `marker.kwargs["env"]`: if unset, add `pytest.mark.skip(reason=f"{env_name} not set")`.
   - This preserves the `skipif(not os.getenv(...))` semantic exactly.

3. Add `_block_real_provider_calls` autouse fixture in `tests/conftest.py` (top-level, **scoped to `tests/api_budget/` only in PR1 via fixture scope check; goes repo-wide in PR9**):
   - Reads from `_BOUNDARY_ALLOWLIST_FOR_BLOCKER` (initially empty).
   - For each provider entry, monkeypatches the boundary file's vendor SDK objects to raise `RuntimeError("Real provider call attempted in test; opt in via @pytest.mark.real_provider(env=(...))")`.
   - Skip-blocks for tests carrying `@pytest.mark.real_provider`.
   - **Rollout (Codex round 8 — single unambiguous story):** the blocker code lives in `tests/conftest.py` from PR1 but only ACTIVATES for tests under `tests/api_budget/` (checked via `request.node.fspath`). Per-provider PRs (2–8) populate `_BOUNDARY_ALLOWLIST_FOR_BLOCKER` with their entries — these entries are USED by the proving test in `tests/api_budget/` and become effective everywhere only when PR9 removes the path-scope check. The blocker is therefore **inert outside `tests/api_budget/` until PR9**, regardless of how full the allowlist is. Per-provider PRs cannot accidentally start blocking unrelated tests.

4. Add `tests/api_budget/test_import_boundaries.py` with the two-rule lint and an empty per-provider allowlist scaffold. Each provider PR adds its entries.

5. Add a single PR1 proving test in `tests/api_budget/test_blocker_works.py`: the test runs under `tests/api_budget/` (where the blocker is active in PR1). It uses `monkeypatch.setattr(module, "_BOUNDARY_ALLOWLIST_FOR_BLOCKER", {...fake provider entry...})` (NOT in-place mutation, per Codex round 2 — keeps the test xdist-safe if parallel pytest is added later) to inject a fixture-provider entry, attempts a fake call against the fixture provider, asserts `RuntimeError`. This verifies the blocker mechanism end-to-end on a synthetic entry without requiring per-provider PRs to have populated the real allowlist.

6. Migrate existing real-provider tests to the marker (env-aware so the semantic is preserved):
   - `tests/fmp/test_fmp_client.py:874` → `@pytest.mark.real_provider(env=("FMP_API_KEY",))`
   - `tests/snaptrade/test_snaptrade_registration.py:24` → `@pytest.mark.real_provider(env=("SNAPTRADE_CLIENT_ID","SNAPTRADE_CONSUMER_KEY"))`
   - `tests/snaptrade/test_snaptrade_endpoints.py` → same
   - `tests/snaptrade/test_snaptrade_credentials.py:15` → same (Codex round 1 catch — currently has no marker)
   - `tests/snaptrade/test_snaptrade_existing_user.py:19` → same (Codex round 1 catch)
   - `tests/api/test_snaptrade_integration.py:48,130` → same (Codex round 1 catch — multiple raw SDK imports inside file)

7. **`tests/snaptrade/test_snaptrade_basic.py:19, 36`** — Codex round 1 caught this is NOT equivalent through any boundary (it tests raw SDK `api_status.check()` and direct user lifecycle). **Move to `scripts/snaptrade_sdk_smoke.py`** as a manual smoke script (not pytest-collected). Plan does not claim equivalence.

**Final flip PR (PR 9): activate the blocker repo-wide**
- All per-provider PRs (2–8) have populated `_BOUNDARY_ALLOWLIST_FOR_BLOCKER` with their entries; the data structure is fully populated.
- PR9 removes the `tests/api_budget/`-only path-scope check from the autouse fixture. The blocker becomes effective on the entire test suite. Verify full suite passes; ship.

---

## Phasing — 9 sequential PRs

| # | PR | Scope |
|---|---|---|
| 1 | **Test infra** | `pytest.ini` markers; `tests/conftest.py` env-aware marker hook + inert autouse blocker; `tests/api_budget/test_import_boundaries.py` two-rule lint scaffold; `tests/api_budget/test_blocker_works.py` proving test; migrate 5 existing real-provider tests to marker; move `tests/snaptrade/test_snaptrade_basic.py` to `scripts/snaptrade_sdk_smoke.py`. |
| 2 | **Plaid boundary** | Refactor public functions to drop `client` parameter; remove raw-client export from 3 locations (`brokerage/plaid/__init__.py:3`, `providers/plaid_loader.py:15`, `brokerage/plaid/client.py:314`); add `exchange_public_token`, `get_investments_transactions`, `get_item`; refactor 9+ external callers; add Plaid entries to vendor + canonical-import allowlists. |
| 3 | **SnapTrade boundary** | Refactor public functions; remove `snaptrade_client`/`get_snaptrade_client` from `__init__.py:2`; fix `brokerage/snaptrade/adapter.py:281+` self-violation via new `connections.refresh_brokerage_authorization`; add new boundary functions; re-export `SnapTradeApiException`; delete dead block at `providers/snaptrade_loader.py:1633-1801` (with regression test on rebind at :2165); refactor 8+ external callers; add SnapTrade entries to allowlists. |
| 4 | **Schwab boundary** | Remove `get_schwab_client` from `brokerage/schwab/__init__.py:2`; add operation-shaped public functions; delete `providers/schwab_client.py` shim; re-point importers to `brokerage.schwab` package; move `schwab.orders` import from adapter:305 to new `brokerage/schwab/orders.py`; refactor `scripts/run_schwab.py` to use boundary functions; add Schwab entries. |
| 5 | **IBKR boundary** | Add `get_ibkr_client` (fresh instance), `probe_ibkr_connection`, `get_ibkr_connection_status`, `fetch_flex_report` (returns parsed dict, not raw FlexReport); tighten `ibkr/__init__.py` exports (no `IBKRConnectionManager` export); audit `IBKRClient` 17 public methods to ensure none return raw `IB`/`Stock`/`Contract`; allowlist `options/portfolio_greeks.py` and `brokerage/ibkr/adapter.py` (dedicated client_id); decide keep/deprecate/delete on `ibkr.compat` (currently public per `ibkr/README.md:128`, re-exported at `ibkr/__init__.py:25` — see ibkr.compat decision below); refactor 12+ consumers; add IBKR entries. |
| 6 | **OpenAI boundary** | Remove `client` `@property` from `OpenAICompletionProvider`; add `complete_structured_with_metadata()` returning `CompletionResult`; refactor `scripts/benchmark_editorial_arbiter.py:174-176`; add OpenAI entries. |
| 7 | **Anthropic boundary** | Remove `client` `@property` from `AnthropicCompletionProvider`; same `complete_structured_with_metadata()` API; refactor `scripts/benchmark_editorial_arbiter.py:200-202`; delete unused `import anthropic` from `app.py:177`; add Anthropic entries. |
| 8 | **FMP boundary** | Create `fmp/estimates_client.py`; refactor `fmp/tools/estimates.py:29-34`; refactor `scripts/health_check.py:100, 109-110` to use `FMPClient`; add FMP entries. |
| 9 | **Activate blocker repo-wide** | Remove the `tests/api_budget/`-only path-scope check from `_block_real_provider_calls` so the blocker becomes effective on the full suite (allowlist already populated by PRs 2–8). Verify full suite passes. Ship. |

Each provider PR is independent. PRs 6, 7 are small. PRs 2 and 3 are largest (most external callers).

---

## Files Modified / Added (per PR see refactor inventory above)

**PR 1 (test infra):** `pytest.ini`, `tests/conftest.py`, `tests/api_budget/test_import_boundaries.py`, `tests/api_budget/test_blocker_works.py`, `scripts/snaptrade_sdk_smoke.py` (moved from `tests/snaptrade/test_snaptrade_basic.py`), edit 5 existing test files for marker migration.

**PRs 2–8:** see per-provider refactor inventory tables above.

**PR 9:** `tests/conftest.py` — remove the `tests/api_budget/`-only path-scope check from the autouse fixture (a few lines).

---

## Verification

### Per-PR (PRs 1–8)
```bash
pytest tests/api_budget/ -v                           # lint + blocker mechanism passes
pytest tests/<provider>/ -v                           # provider-specific tests pass
pytest -k "not real_provider" -v                      # full unit suite passes (no real provider opt-in)
```

E2E sanity per provider (after each PR): hit one representative endpoint via the dev backend; verify no behavior change.

### Final flip (PR 9)
```bash
pytest tests/ -v                                      # ENTIRE suite passes with active autouse blocker
pytest tests/snaptrade/ -v -m real_provider           # opt-in tests work when env set
SNAPTRADE_CLIENT_ID="" pytest tests/snaptrade/ -v     # opt-in tests skip cleanly when env unset
```

### Manual smoke

**Note (Codex round 4 correction):** Python's `from package import name` falls back to importing a submodule named `name` if `name` isn't an attribute of the package. So `from brokerage.plaid import client` after removing the `client` attribute would NOT raise `ImportError` — it would resolve to the **submodule** `brokerage.plaid.client`. The runtime guarantees we can rely on are tighter than v4 claimed:

1. `from brokerage.plaid import client` → succeeds, returns the SUBMODULE `brokerage.plaid.client`. The bypass attempt is caught by Rule B lint in CI (forbidden submodule attribute name on package).
2. `from brokerage.plaid.client import client` → `ImportError` (after removing the module-level `client = ...` at `brokerage/plaid/client.py:314`).
3. `from brokerage.snaptrade import snaptrade_client` → succeeds, returns submodule `brokerage.snaptrade.snaptrade_client` if such a submodule exists, otherwise `ImportError`. Caught by Rule B lint regardless.
4. `from brokerage.snaptrade.client import snaptrade_client` → `ImportError` after removing the module-level export from the client submodule.
5. `from brokerage.schwab import get_schwab_client` → `ImportError` (no submodule named `get_schwab_client`; attribute removed).
6. `OpenAICompletionProvider().client` → `AttributeError` (instance attribute removed).
7. `AnthropicCompletionProvider().client` → `AttributeError`.
8. `from providers.schwab_client import ...` → `ModuleNotFoundError` (file deleted).
9. `from providers.plaid_loader import client` → still importable (loader is a TRANSITIONAL boundary file); Rule B lint flags any NEW external importer (existing importers grandfathered via `RULE_B_BASELINE`).
10. Run `pytest tests/snaptrade/test_snaptrade_credentials.py` with `SNAPTRADE_CLIENT_ID` unset → cleanly skipped (marker semantic preserved).

**Lint is the primary gate, not runtime ImportError.** Removing public `__all__` entries gives partial protection at runtime (cases 5, 6, 7), but the comprehensive enforcement is the AST + regex + whitelist lint test running in CI.

### Acceptance
- All 7 providers have `__init__.py` exporting only the public API surface: domain-shaped operation functions (e.g., `fetch_plaid_balances`, `get_account_data`, `probe_ibkr_connection`, `get_ibkr_connection_status`, `fetch_flex_report`), in-house facade classes/factories (`IBKRClient`, `get_ibkr_client`), and exception aliases re-exported through the boundary (`SnapTradeApiException`). NO raw vendor SDK objects (`IB`, `FlexReport`, `Stock`, `ContractDetails`, `Option`, `SnapTrade`, `plaid_api.PlaidApi`, etc.). NO raw vendor-client factories that return vendor SDK objects (e.g., the removed `get_schwab_client`). `IBKRConnectionManager` is NOT publicly exported (per Codex round 5 — its `connect()` method returns raw `IB`).
- All 7 providers have public functions that take domain types only (no `client` parameter).
- Two-rule lint passes: no vendor-SDK import outside per-provider allowlist; no forbidden import-path bypass.
- No file accesses `provider.client` for OpenAI/Anthropic providers.
- All migrated real-provider tests use `@pytest.mark.real_provider(env=(...))`; missing-env-list fails collection; missing env vars at runtime skip cleanly.
- Autouse blocker is active repo-wide; tests without the marker can't reach a real provider.
- `tests/snaptrade/test_snaptrade_basic.py` is no longer pytest-collected (moved to `scripts/snaptrade_sdk_smoke.py`).

---

## Backward compatibility

**Breaking changes (intentional):**
- `from brokerage.plaid.client import client` → `ImportError` (after removing module-level `client` at line 314).
- `from brokerage.plaid import client` → resolves to **submodule** `brokerage.plaid.client` (Python's import-fallback behavior), but accessing attributes on it that were removed (the raw client) → `AttributeError`. Lint catches the import attempt.
- `from brokerage.snaptrade import snaptrade_client` → resolves to submodule if one exists; lint catches.
- `from brokerage.schwab import get_schwab_client` → `ImportError` (no submodule of that name).
- `OpenAICompletionProvider().client` → `AttributeError`.
- `AnthropicCompletionProvider().client` → `AttributeError`.
- `from providers.schwab_client import ...` → `ModuleNotFoundError` (file deleted).
- `fetch_plaid_balances(access_token, client)` → signature changed to `fetch_plaid_balances(access_token)`; same for `remove_plaid_connection`, `wait_for_public_token`, `get_institution_info`, etc. (any `brokerage.plaid` function previously taking `client`). Internal callers refactored in same PR.
- Same signature changes for `brokerage.snaptrade` functions.
- `IBKRConnectionManager` no longer publicly exported; consumers use `probe_ibkr_connection()` / `get_ibkr_connection_status()` operation functions instead.
- `fetch_flex_report` returns parsed dict, not raw `FlexReport`.

These are not externally-facing APIs (private application repo). All known internal callers are refactored in the same PR that introduces each break.

---

## Risks

1. **Hidden callers I still didn't find.** Mitigated by lint test running in CI from PR 1 onward — any unrefactored caller fails the test. Empty allowlist scaffold in PR 1 is *deliberately permissive* until each provider PR seeds its entries.

2. **`providers/snaptrade_loader.py:1633-1801` dead-block deletion.** Could break if the rebind at line 2165 isn't actually authoritative. Mitigation: regression test added in SnapTrade PR specifically verifying the rebound names point to `brokerage.snaptrade` implementations.

3. **`brokerage/snaptrade/adapter.py` retry semantic.** Currently the adapter calls `client.connections.refresh_brokerage_authorization(...)` directly without the retry decorator that `brokerage/snaptrade/client.py` functions wear. Refactor to a new `connections.refresh_brokerage_authorization(...)` with retry will *change behavior* (adds retry where there was none). Document; verify with the SnapTrade team this is desirable (likely yes, but call it out).

4. **IBKR adapter dedicated `client_id`.** Plan explicitly does NOT route `brokerage/ibkr/adapter.py:79` through the default `get_ibkr_client()` factory — it keeps using its dedicated `client_id`. Allowlisted as a boundary file. Risk: someone later "cleans up" by routing it through the default factory, breaking IBKR connection lifecycle. Mitigation: comment in the file + plan call-out.

5. **`scripts/benchmark_editorial_arbiter.py` API extension complexity.** `complete_structured_with_metadata()` is a new method that has to handle both OpenAI `response_format` and Anthropic `tools` shapes uniformly. Risk: the abstraction leaks. Mitigation: `CompletionResult.raw_metadata` is intentionally an opaque dict for provider-specific bits the script needs.

6. **`pytest.mark.real_provider` strict-collection enforcement.** A test that adds the marker without `env=` fails collection. Risk: existing CI may have a hidden test we didn't catch. Mitigation: PR 1 migration is exhaustive based on Codex's catch (5 known sites); CI failure surfaces any miss immediately.
