# Centralized API Budget Guard

**Status:** v10 — addresses Codex round 5 FAIL against v9: Schwab normalizer site reclassified (it's plain `client.get_quotes(filtered)` with no `try/except TypeError` — wrap directly, no helper); IBKR remote-dispatch allowlist extended with `cancel*` methods (`cancelMktData`, `cancelPnL`, `cancelPnLSingle`); IBKR file scope extended with `services/trade_execution_service.py` (live `ib.reqCompletedOrders(apiOnly=False)` at `:3254` was outside scope).

## Context

The team got hit with an unexpected **$342 Plaid bill in one month of testing** because there was no per-provider call counting, no configurable spend limits, and no proactive alerting. The Vendor SDK Boundary Refactor established a hermetic boundary per provider — every external SDK/HTTP call now goes through a curated set of public boundary functions. v5 leverages that boundary: the cost guard becomes a focused integration that wraps each public boundary function with `guard_call(...)`, gets atomic per-provider counters in Redis, raises `BudgetExceededError` when over hard caps, and fires alerts via direct Telegram Bot API. Counters snapshot to Postgres for queryable history.

**v4 vs v5:** v4 spent ~400 lines on the refactor inventory, two-rule lint, autouse blocker, and `RULE_B_BASELINE` mechanics — all shipped by the boundary work. v5 drops those entirely and focuses on the actual cost guard: Lua atomic counters, threshold config, Postgres persistence, alerts, dry-run rollout, admin UI. Rough size: 250 lines vs 532.

**Non-goals (v1):** per-second token-bucket rate limiting (FMP `fmp/client.py` already has 700/min), pre-call hard-blocking of LLM calls *based on cost* (count caps still apply pre-call; cost-based caps deferred to v2 — LLM cost is computed post-call from token usage), streaming LLM cost extraction, replacing `services/circuit_breaker.py`, Redis-side cost aggregation (Postgres-only).

---

## Architecture

### Where `guard_call` lives — at the dispatch/retry layer (one wrap per outbound vendor call)

**Wrap unit (corrected per Codex):** the goal is "every outbound vendor call counted exactly once," NOT "every public boundary function wrapped once." Some public functions make 0/1/N vendor calls — examples in this codebase:
- `brokerage/plaid/client.py:wait_for_public_token` polls `link_token_get` in a loop until done; one logical "call" = N physical attempts
- `brokerage/plaid/client.py:get_institution_info` (around line 165) makes two Plaid calls per invocation
- `brokerage/snaptrade/_shared.py:100` and `brokerage/schwab/adapter.py:149` retry on errors; each retry is a real billable attempt
- `fmp/client.py:fetch` may return from cache without hitting HTTP — wrapping `fetch` would over-count cache hits

Wrap target per provider is the layer where one call = one outbound HTTP/SDK attempt:

| Provider | Wrap target (one call = one vendor attempt) | Notes |
|---|---|---|
| Plaid | Each SDK method invocation inside boundary files (`brokerage/plaid/client.py`, `brokerage/plaid/connections.py`) — wrap each `client.X(...)` call site, NOT the enclosing public function | Polling loops increment per attempt; multi-call publics increment per call |
| SnapTrade | Same pattern — wrap each SDK method invocation in boundary files (`brokerage/snaptrade/{client,connections,trading,users,recovery}.py`); for retry-decorated functions in `brokerage/snaptrade/_shared.py:with_snaptrade_retry`, wrap INSIDE the retry so each retry counts | The retry decorator is the multiplier — wrap below it |
| Schwab | Wrap each SDK method invocation in `brokerage/schwab/client.py`; for retry-decorated calls in `brokerage/schwab/adapter.py:_call_with_backoff` (around `:149`), wrap INSIDE the retry. **For `providers/schwab_positions.py:103, :105` and `providers/schwab_transactions.py:180, :186`** — these have signature-fallback `try/except TypeError` shims around the SDK call. Extract a thin local helper that does the try/except internally and wrap the helper (example below). The local `TypeError` (signature mismatch) never reaches the counter. **For `providers/normalizers/schwab.py:463`** — plain `client.get_quotes(filtered)`, no shim — wrap directly. | Same retry-multiplier rule |
| IBKR | Wrap by **remote-dispatch method name**, not raw syntax pattern. Count attempts on these methods of the IB instance: `connect`, `qualifyContracts`, `req*` (any method starting with `req`), `whatIfOrder`, `placeOrder`, `cancelOrder`, `cancelMktData`, `cancelPnL`, `cancelPnLSingle`. Plus the two `urlopen()` calls at `ibkr/flex.py:1350` and `:1386`. **Do NOT count** local/cache/control helpers: `managedAccounts`, `positions`, `portfolio`, `accountValues`, `openTrades`, `ticker`, `sleep`, `disconnect`. Files in scope: `brokerage/ibkr/adapter.py`, `ibkr/account.py`, `ibkr/metadata.py`, `ibkr/market_data.py`, `ibkr/connection.py:90`, `ibkr/flex.py:1350,1386`, **and `services/trade_execution_service.py` (specifically the `ib.reqCompletedOrders(apiOnly=False)` at `:3254`)**. NOT `ibkr/client.py` (facade — only direct SDK call is `managedAccounts()` accessor) and NOT `ibkr/server.py` (RPC). Implementation greps each file for the remote-dispatch method names above and wraps every match. | |
| OpenAI / Anthropic | Wrap `client.chat.completions.create(...)` at `providers/completion.py:227` and `client.messages.create(...)` at `providers/completion.py:384` — each is the single raw SDK call shared by `complete`, `complete_structured`, and `complete_structured_with_metadata`. One wrap per provider per raw-SDK-call site (so one provider method invocation = one count) | Pass `cost_fn=openai_usage` / `cost_fn=anthropic_usage` to extract usage from the raw SDK response BEFORE provider-side post-processing |
| FMP | Wrap the single `requests.get(...)` attempt INSIDE the retry loop in `FMPClient._make_request` (around `fmp/client.py:216–220` — the loop body iterates up to `_RATE_LIMIT_RETRIES`). NOT `_make_request` itself (would miss retry counts), and NOT `fetch` (`:373`) or `fetch_raw` (`:472`) (cache hits would over-count). Implementation: extract `_dispatch_once()` helper containing the wrapped `requests.get`, call from the loop. Cache hits short-circuit before the loop and do NOT count | Count-only mode — FMP retains its own 700/min limiter |
| FMP estimates | Wrap the HTTP call inside `fmp/estimates_client.py:get` | Separate provider name `fmp_estimates` |

`guard_call` is implemented as a thin wrapper — same shape as v5 but emphasis is on physical-attempt granularity:

```python
# app_platform/api_budget/guard.py
def guard_call(*, provider, operation, fn, args=(), kwargs=None,
               budget_user_id=None, account_id=None, caller=None,
               cost_fn=None, cost_per_call=None) -> Any:
    """Atomic per-provider counter + threshold check + alerting.

    Wraps a single outbound vendor call. Increments Redis counters atomically
    via Lua script. Raises BudgetExceededError if over hard cap (unless dry-run).

    Note on naming: budget_user_id (NOT user_id) to avoid clash with the
    existing user_id parameter on many boundary functions
    (brokerage/plaid/client.py:94,126, brokerage/snaptrade/recovery.py:125, etc.).
    """
```

Inside each boundary function, replace the SDK call with `guard_call`:

```python
# Before (post-boundary, pre-cost-guard) — brokerage/plaid/client.py around line 251:
def fetch_plaid_balances(access_token: str) -> dict:
    client = _get_or_create_client()
    return client.accounts_balance_get(AccountsBalanceGetRequest(access_token=access_token))

# After (cost-guard wrap):
def fetch_plaid_balances(access_token: str, *, budget_user_id: int | None = None) -> dict:
    client = _get_or_create_client()
    return guard_call(
        provider="plaid",
        operation="accounts_balance_get",
        budget_user_id=budget_user_id,
        cost_per_call=0.30,
        fn=client.accounts_balance_get,
        args=(AccountsBalanceGetRequest(access_token=access_token),),
    )
```

For polling loops (`wait_for_public_token`):

```python
# Each iteration of the poll wraps the SDK call individually:
while not done:
    resp = guard_call(
        provider="plaid",
        operation="link_token_get",
        budget_user_id=budget_user_id,
        fn=client.link_token_get,
        args=(LinkTokenGetRequest(link_token=link_token),),
    )
    ...
```

For Schwab's `try/except TypeError` signature-fallback shims (Codex round 4), extract a thin local helper that resolves the right signature, then wrap the helper:

```python
# providers/schwab_positions.py — was:
try:
    response = client.get_account(account_hash, fields=["positions"])
except TypeError:
    response = client.get_account(account_hash)

# After: extract helper that does the shim internally, wrap the helper:
def _call_schwab_get_account(client, account_hash, fields=None):
    try:
        return client.get_account(account_hash, fields=fields) if fields else client.get_account(account_hash)
    except TypeError:
        return client.get_account(account_hash)

response = guard_call(
    provider="schwab",
    operation="get_account",
    fn=_call_schwab_get_account,
    args=(client, account_hash),
    kwargs={"fields": ["positions"]},
)
```

The wrap fires ONCE around the helper. If the first SDK call raises local `TypeError` (signature mismatch — not a vendor attempt), the helper's except branch falls back to the simpler signature; the user never sees two counts and the local `TypeError` doesn't reach `guard_call`'s counter. One logical call = one count.

For functions with internal retry loops (FMP `_make_request` has up to 3 `requests.get` attempts per call), wrap the SINGLE attempt inside the loop, NOT the enclosing function. Preserve existing exception translation by keeping the `requests.exceptions` → `FMPAPIError` conversion in `_make_request` (the caller of `_dispatch_once`):

```python
# fmp/client.py — extract _dispatch_once() to do exactly the requests.get + guard_call:
def _dispatch_once(self, url, request_params):
    return guard_call(
        provider="fmp",
        operation="<endpoint name>",  # passed in from caller
        cost_per_call=0,  # FMP has its own rate limiter; count-only
        fn=requests.get,
        args=(url,),
        kwargs={"params": request_params, "timeout": self.timeout},
    )

# _make_request keeps exception translation — translates raw requests exceptions to FMPAPIError:
def _make_request(self, endpoint, params):
    ...
    for attempt in range(1, self._RATE_LIMIT_RETRIES + 1):
        try:
            resp = self._dispatch_once(url, request_params)  # may raise BudgetExceededError
        except requests.exceptions.Timeout:
            self._log_error(endpoint.name, "Request timeout")
            raise FMPAPIError(...)
        except requests.exceptions.RequestException as e:
            self._log_error(endpoint.name, str(e))
            raise FMPAPIError(...)
        ...  # 429 retry handling stays unchanged
```

`BudgetExceededError` propagates through unchanged (cost-guard exception is meant to surface to caller).

For retry-decorated functions, the wrap goes INSIDE the retry decorator's wrapped function so each retry attempt counts:

```python
# brokerage/snaptrade/client.py
@with_snaptrade_retry("accounts_list")
def _accounts_list(client, user_id, user_secret):
    return guard_call(
        provider="snaptrade",
        operation="accounts.list",
        fn=client.account_information.list_user_accounts,
        kwargs={"user_id": user_id, "user_secret": user_secret},
    )
```

External callers don't change — they call boundary functions exactly as before. The wrap is transparent.

**`budget_user_id` plumbing:** boundary functions add an optional `budget_user_id=None` kwarg passed through to `guard_call` for per-user attribution. Callers pass it where available (e.g., from request context); missing is OK (counts only against global keys). Distinct from existing `user_id` parameters that have unrelated semantics (Plaid SDK user identifier, SnapTrade app user identifier, etc.).

### Storage — Redis primary on dedicated DB

`API_BUDGET_REDIS_URL=redis://localhost:6379/2` — distinct from Celery broker `/1` (mirrors `services/circuit_breaker.py:30–34`).

**Key namespace:**
```
budget:counter:{provider}:{operation}:{scope}:{user_id?}:{window_kind}:{window_start}
budget:counter:{provider}:_all_:{scope}:{user_id?}:{window_kind}:{window_start}    -- aggregate
budget:alert:{provider}:{severity}                                                  -- alert dedup (separate namespace)
```

Snapshot uses `SCAN MATCH budget:counter:*` (excludes alerts). Celery beat task `snapshot-api-budget` runs every 60s, UPSERTs current counters into `api_call_counters`.

### DB schema

```sql
CREATE TABLE api_call_counters (
  provider        TEXT NOT NULL,
  operation       TEXT NOT NULL,                     -- '_all_' for provider-aggregate
  scope           TEXT NOT NULL CHECK (scope IN ('global','user')),
  user_id         INT NULL,
  window_kind     TEXT NOT NULL CHECK (window_kind IN ('daily','monthly')),
  window_start    TIMESTAMPTZ NOT NULL,
  call_count      BIGINT NOT NULL DEFAULT 0,
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK ((scope = 'global' AND user_id IS NULL) OR (scope = 'user' AND user_id IS NOT NULL))
);

CREATE UNIQUE INDEX ux_api_call_counters_global
  ON api_call_counters(provider, operation, window_kind, window_start)
  WHERE scope = 'global';

CREATE UNIQUE INDEX ux_api_call_counters_user
  ON api_call_counters(provider, operation, user_id, window_kind, window_start)
  WHERE scope = 'user';

CREATE INDEX ix_api_call_counters_lookup
  ON api_call_counters(provider, window_kind, window_start DESC);

CREATE TABLE api_call_log (
  id                   BIGSERIAL PRIMARY KEY,
  provider             TEXT NOT NULL,
  operation            TEXT NOT NULL,
  caller               TEXT,
  user_id              INT NULL,
  account_id           TEXT NULL,
  task_id              TEXT NULL,
  trace_id             TEXT NULL,
  duration_ms          INT,
  estimated_cost_usd   NUMERIC(12,4),
  decision             TEXT NOT NULL CHECK (decision IN ('ok','warned','blocked','error')),
  blocked_scope        TEXT NULL CHECK (blocked_scope IN ('global','user','both')),
  blocked_key_kind     TEXT NULL CHECK (blocked_key_kind IN ('op','agg')),
  blocked_window_kind  TEXT NULL CHECK (blocked_window_kind IN ('daily','monthly')),
  blocked_threshold    BIGINT NULL,
  blocked_count        BIGINT NULL,
  count_before_global  BIGINT,
  count_after_global   BIGINT,
  count_before_user    BIGINT NULL,
  count_after_user     BIGINT NULL,
  dry_run              BOOLEAN NOT NULL,
  redis_state          TEXT NOT NULL CHECK (redis_state IN ('ok','unavailable')),
  ts                   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_api_call_log_ts          ON api_call_log USING BRIN(ts);
CREATE INDEX ix_api_call_log_provider_ts ON api_call_log(provider, ts DESC);
CREATE INDEX ix_api_call_log_user_ts     ON api_call_log(user_id, ts DESC) WHERE user_id IS NOT NULL;
```

UPSERT uses partial-index `ON CONFLICT (...) WHERE scope='global'` / `WHERE scope='user'` syntax (snapshot job dispatches by scope).

### Atomic multi-key increment via Lua

Single Lua script, atomic across 4 (or 8 with user_id) counter keys. Computes `decision` (max severity), tracks threshold crossings, returns full state in one round trip.

```lua
-- KEYS (always present):
--   [1] global_op_daily       [2] global_op_monthly
--   [3] global_agg_daily      [4] global_agg_monthly
-- KEYS (optional, present iff user_id supplied):
--   [5] user_op_daily         [6] user_op_monthly
--   [7] user_agg_daily        [8] user_agg_monthly
--
-- ARGV: inc_amount, (limit, warn, ttl_seconds) tuples aligned with KEYS, "-1" = no cap.
-- Per key: INCRBY, EXPIRE iff TTL not set, compute new vs old crossing.
-- Crossing: (new >= threshold) AND (old < threshold) — fires once.
-- Dual-threshold same call: emit ONE crossing record with threshold_kind="limit".
-- Crossings ordered by KEYS index ascending.
--
-- Returns: { decision, blocked_scope, blocked_key_kind, blocked_window_kind,
--            blocked_threshold, blocked_count, crossings, counts }
```

`decision` is **always** the true max severity across all keys (no dry-run collapsing). `guard_call` decides whether to raise based on `(decision, dry_run config)`:
- `ok`: proceed.
- `warned`: log + alert(severity="medium"), proceed.
- `blocked` AND dry_run: log + alert(severity="high", note="would block"), proceed (counter still incremented for visibility).
- `blocked` AND NOT dry_run: log + alert(severity="critical"), raise `BudgetExceededError(blocked_scope, blocked_key_kind, blocked_window_kind, blocked_threshold, blocked_count)`.

### Per-user attribution

8 keys at most per call (4 if no `user_id`). Caps enforced independently. Lua handles atomicity across all keys.

### Configuration — structured JSON + simple env switches + startup validation

```bash
# Switches (env vars)
API_BUDGET_ENABLED=true
API_BUDGET_DRY_RUN=true                          # default for safe rollout
API_BUDGET_FAIL_OPEN=true                        # if Redis unavailable, allow + alert
API_BUDGET_REDIS_URL=redis://localhost:6379/2    # dedicated DB
API_BUDGET_SAMPLE_LOG_PCT=10                     # non-LLM; LLM always 100%
API_BUDGET_SNAPSHOT_INTERVAL_SECONDS=60
API_BUDGET_LOG_RETENTION_DAYS=30
API_BUDGET_TELEGRAM_BOT_TOKEN=                   # mirrors scripts/check_schwab_token.py:62
API_BUDGET_TELEGRAM_CHAT_ID=
API_BUDGET_ALERT_DEDUP_SECONDS=600               # 10-min window per (provider, severity)
```

`API_BUDGET_THRESHOLDS_JSON` (single-line, copy-paste valid; satisfies startup validation rule below):
```json
{"providers":{"plaid":{"default":{"global":{"daily":{"warn":80,"limit":100},"monthly":{"warn":2000,"limit":2500}},"per_user":{"daily":{"warn":8,"limit":10},"monthly":{"warn":50,"limit":60}}},"operations":{"accounts_balance_get":{"global":{"daily":{"warn":120,"limit":150}}}}},"openai":{"default":{"global":{"daily":{"warn":1000,"limit":2000}}}},"anthropic":{"default":{"global":{"daily":{"warn":1000,"limit":2000}}}},"snaptrade":{"default":{"global":{"daily":{"warn":500,"limit":800}}}},"schwab":{"default":{"global":{"daily":{"warn":500,"limit":800}}}},"ibkr":{"default":{"global":{"daily":{"warn":50,"limit":100}}}},"fmp":{"default":null},"fmp_estimates":{"default":{"global":{"daily":{"warn":1000,"limit":2000}}}}}}
```

Resolution per call: `operations.<op>.<scope>.<window>` overrides `default.<scope>.<window>`. Missing values mean "no cap" (count-only). `null` provider = count-only entirely.

**Startup validation rule:** for the pre-enqueue gate to be consistent with per-call enforcement, per-operation caps must be ≥ the aggregate cap (aggregate is the floor). Validated at startup; loud failure on violation. Per-op caps may be HIGHER than aggregate (special allowance), never tighter. (The example above satisfies this — `accounts_balance_get` limit=150 ≥ default limit=100.)

### Failure mode — fail-open + alert only

- Redis available: enforce per Lua.
- Redis unavailable: log `severity=high` (deduped per minute, in-process), allow call, no sampling-block.
- `GET /api/admin/api-budget` shows `redis_state` so extended outages are visible. Operator can flip `API_BUDGET_FAIL_OPEN=false` for emergency hard-stop.

### Idempotency

`guard_call` does NOT take an `idempotency_key` parameter. Spending counts are not deduped (a Celery retry that re-spends should re-count).

### Pre-enqueue gate — `services/sync_runner.py`

`services/sync_runner.py:90` is the explicit boundary all provider syncs go through. Modify `enqueue_sync()` to call `is_provider_over_budget(provider, user_id)` first, returning `state="budget_exceeded"` if true. Implementation reads aggregate keys via `MGET` (one round trip). Aggregate keys are maintained by the same Lua script that does per-call increments, so consistency is by construction.

### Alert delivery — direct Telegram Bot API, claim-then-confirm dedup

Mirrors `scripts/check_schwab_token.py:60–79`:
```python
def send_alert(severity, provider, message, **details):
    log_alert(...)                                              # always — audit (utils.logging)
    if severity in {"high", "critical"}:
        dedup_key = f"budget:alert:{provider}:{severity}"
        if _redis.set(dedup_key, "1", nx=True, ex=ALERT_DEDUP_SECONDS):
            try:
                _send_telegram(message, **details)              # urllib POST to bot API
            except Exception:
                _redis.delete(dedup_key)                        # release on failure
                raise
```

### LLM cost — Postgres-only in v1

No Redis cost aggregation. `estimated_cost_usd` flows through `api_call_log` only, computed post-call from `LLMUsage`:

```python
@dataclass
class LLMUsage:
    input_tokens: int
    output_tokens: int
    model: str

def openai_usage(response) -> LLMUsage:
    u = response.usage
    return LLMUsage(u.prompt_tokens, u.completion_tokens, response.model)

def anthropic_usage(response) -> LLMUsage:
    u = response.usage
    return LLMUsage(u.input_tokens, u.output_tokens, response.model)
```

`LLM_PRICES` per-model lives in `config/api_budget_costs.py` (project-specific). LLM calls always logged (`sample_log_pct=100` for `openai`/`anthropic`); non-LLM respect `API_BUDGET_SAMPLE_LOG_PCT`. Cost-based caps deferred to v2; pre-call hard caps still apply on call-count (Lua doesn't need cost). Streaming explicitly out of scope (current `providers/completion.py` doesn't stream; no `complete_structured_with_metadata` streaming variant exists per PR6/PR7).

### `app_platform/pyproject.toml`

```toml
[project.optional-dependencies]
api-budget = ["redis>=5.0,<6"]
all = ["app-platform[fastapi,auth-google,gateway,api-budget]"]
```

### Observability — canonical `api_call_log` shape

All fields documented in the schema above. A blocked row is self-explanatory: `blocked_scope=user, blocked_key_kind=op, blocked_window_kind=daily, blocked_threshold=10, blocked_count=11` reads as "user-scope per-operation daily limit of 10 was exceeded at count 11."

### Admin route + CLI

- `GET /api/admin/api-budget?provider=plaid` — admin auth required; live counters, recent log rows, threshold config, today's cost per provider (`SUM(estimated_cost_usd)`), `redis_state`.
- `python -m app_platform.api_budget status [--provider plaid]`
- `python -m app_platform.api_budget reset plaid --window daily [--user-id 42]` — manual counter reset (logs audit event).

---

## Files Modified / Added

### New (framework — `app_platform/api_budget/`)
- `app_platform/api_budget/__init__.py`
- `app_platform/api_budget/guard.py` — `guard_call()`, `is_provider_over_budget()`
- `app_platform/api_budget/store.py` — Redis adapter, Lua loader, snapshot writer (uses `SCAN`)
- `app_platform/api_budget/lua/budget_incr.lua`
- `app_platform/api_budget/config.py` — startup validation
- `app_platform/api_budget/exceptions.py` — `BudgetExceededError`
- `app_platform/api_budget/alerts.py` — claim-then-confirm Telegram dedup
- `app_platform/api_budget/snapshot.py` — Redis SCAN → Postgres UPSERT
- `app_platform/api_budget/llm_cost.py` — `LLMUsage`, OpenAI/Anthropic adapters
- `app_platform/api_budget/cli.py`
- `app_platform/pyproject.toml` — add `api-budget` extra; update `all`

### New (project — `risk_module/`)
- `config/api_budget_costs.py` — `COST_PER_CALL` map, `LLM_PRICES`
- `database/migrations/NNNN_api_budget.sql`
- `routes/admin_api_budget.py` — `GET /api/admin/api-budget`
- `tests/api_budget/test_guard.py`
- `tests/api_budget/test_lua_atomicity.py`
- `tests/api_budget/test_config_validation.py`
- `tests/api_budget/test_alerts.py`
- `tests/api_budget/test_llm_cost.py`
- `tests/api_budget/test_snapshot.py`
- `tests/api_budget/test_sync_runner_gate.py`

### Modified — wrap `guard_call(...)` at the dispatch layer (one wrap per outbound vendor call)
For each provider, the integration replaces each direct SDK/HTTP call with a `guard_call` wrapper. The boundary's existing `_get_or_create_client()` memoization composes cleanly with `guard_call(fn=bound_method, ...)` — no interaction. Wraps go INSIDE retry decorators so each retry counts.

- `brokerage/plaid/client.py`, `brokerage/plaid/connections.py` — wrap each `client.X(...)` SDK invocation. Polling loop in `wait_for_public_token` wraps each iteration. `get_institution_info` wraps both Plaid calls.
- `brokerage/snaptrade/{client,connections,trading,users,recovery}.py` — wrap each SDK invocation INSIDE the body of each `with_snaptrade_retry`-decorated function (so retries multiply correctly)
- `brokerage/snaptrade/_shared.py:100` — verified retry decorator structure (`with_snaptrade_retry`) makes per-retry wrapping ergonomic; no helper changes needed
- `brokerage/schwab/client.py` — wrap each SDK invocation. For functions in `brokerage/schwab/adapter.py:_call_with_backoff` (around `:149`), wrap INSIDE the retry
- `providers/schwab_positions.py:103, :105`, `providers/schwab_transactions.py:180, :186` — `try/except TypeError` shim sites. Extract a `_call_schwab_<method>` helper per call site that does the try/except internally; wrap the helper with `guard_call`. Local `TypeError`s never reach the counter
- `providers/normalizers/schwab.py:463` — plain `client.get_quotes(filtered)`; wrap directly (no helper)
- IBKR — wrap by **remote-dispatch method name**: `connect`, `qualifyContracts`, `req*` (any), `whatIfOrder`, `placeOrder`, `cancelOrder`, `cancelMktData`, `cancelPnL`, `cancelPnLSingle`. Plus `urlopen()` at `ibkr/flex.py:1350, :1386`. Do NOT wrap local/cache helpers (`managedAccounts`, `positions`, `portfolio`, `accountValues`, `openTrades`, `ticker`, `sleep`, `disconnect`). Files in scope: `brokerage/ibkr/adapter.py`, `ibkr/account.py`, `ibkr/metadata.py`, `ibkr/market_data.py`, `ibkr/connection.py:90`, `services/trade_execution_service.py:3254`. NOT `ibkr/client.py` and NOT `ibkr/server.py`
- `providers/completion.py:227` — wrap `client.chat.completions.create(...)` (the single OpenAI raw-SDK call site shared by all three OpenAI provider methods); `cost_fn=openai_usage`
- `providers/completion.py:384` — wrap `client.messages.create(...)` (the single Anthropic raw-SDK call site shared by all three Anthropic provider methods); `cost_fn=anthropic_usage`
- `fmp/client.py` — extract `_dispatch_once()` helper containing the wrapped `requests.get(...)` (`:216`-area), call from the retry loop in `_make_request` (`:197`-area). Each retry attempt counts as a separate physical call. `fetch`/`fetch_raw` remain unwrapped (cache hits don't count)
- `fmp/estimates_client.py:get` — wrap the actual HTTP call inside (separate provider name `fmp_estimates`)

`budget_user_id` plumbing: each public boundary function adds an optional `budget_user_id: int | None = None` kwarg passed through to `guard_call`. Existing `user_id` parameters (Plaid SDK user identifier, SnapTrade app user id) keep their meanings unchanged.

### Modified — pre-enqueue gate + scheduler + env
- `services/sync_runner.py:90` — add `is_provider_over_budget(...)` gate at top of `enqueue_sync`
- `workers/beat_schedule.py` — add `snapshot-api-budget` (every 60s) + `truncate-api-call-log` (daily)
- `.env.example` — add documented env vars + starter `API_BUDGET_THRESHOLDS_JSON` (must pass startup validation rule)

### Reused (no changes — listed for reference)
- `utils/logging.py` — `log_alert()`, `log_event()`, `log_usage()`
- `services/circuit_breaker.py:30–34` — Redis client pattern
- `services/sync_runner.py:48–49,90` — Redis pattern + enqueue gate point
- `database/session.py` — `SessionManager` for snapshot writes
- `scripts/check_schwab_token.py:60–79` — Telegram pattern
- `tests/conftest.py` — autouse blocker (already shipped by boundary refactor; cost guard tests don't need to add anything; just write tests under `tests/api_budget/` or use `@pytest.mark.real_provider` if integration testing)

---

## Phasing — 4 PRs (PR1 split per Codex round 1)

| # | PR | Scope |
|---|---|---|
| 1 | **Framework + schema + admin/CLI** | Build `app_platform/api_budget/` (all modules + Lua), schema migration, snapshot beat job, log-retention beat job, admin route, CLI. NO provider wraps yet, NO sync gate. Ships the mechanism; nothing wired up. `app_platform[api-budget]` extra published. Tests cover Lua atomicity, partial-index UPSERT, alert dedup, LLM cost extraction, config validation, fail-open. Verifies framework works end-to-end via the proving test (synthetic provider entry). |
| 2 | **Plaid integration + sync gate** | Wrap each outbound vendor call inside `brokerage/plaid/{client,connections}.py` (per the dispatch-layer rule). Plumb `budget_user_id` through Plaid public functions. Add `is_provider_over_budget()` gate to `services/sync_runner.py:enqueue_sync` (Plaid only — other providers added in PR3). Dry-run on. Verify real Plaid call volumes via `GET /api/admin/api-budget?provider=plaid`. |
| 3 | **Remaining providers** | Wrap each outbound vendor call in SnapTrade (`brokerage/snaptrade/*.py`), Schwab (`brokerage/schwab/*.py`), IBKR (`ibkr/*.py`), OpenAI/Anthropic (`providers/completion.py`), FMP (`fmp/client.py:_make_request`), FMP estimates (`fmp/estimates_client.py:get`). Extend the `is_provider_over_budget()` gate to all providers. Wraps go INSIDE retry decorators so each retry counts. Each provider is independent; can be one PR per provider or one mega-PR per review preference. |
| 4 | **Tune + flip dry-run off + admin UI (optional)** | After 1 week observation, tune thresholds at 1.5× observed P99 from `api_call_counters`, configure Telegram, flip `API_BUDGET_DRY_RUN=false`. Optionally add a frontend admin tile for live counters + cost. |

---

## Verification

### Unit (no external deps)
- Lua: atomic increment of all 4/8 keys, TTL set-once, `decision` correctly distinguishes ok / warned / blocked, dual-threshold same-call emits ONE crossing with `threshold_kind="limit"`, `decision = max severity across keys`, `blocked_scope` correct for mixed-scope cases.
- `guard_call`: dry-run returns `decision=blocked` AND `dry_run=true` → log + alert + return (no raise). Live mode: `decision=blocked` → raise `BudgetExceededError` with all blocked_* fields.
- `is_provider_over_budget`: single `MGET` of 2 (or 4) aggregate keys.
- Config validation: rejects op-cap < aggregate-cap; accepts conforming.
- Telegram: claim-then-confirm releases dedup key on send failure.
- LLM: `openai_usage` / `anthropic_usage` map response shapes correctly; `estimated_cost_usd` written to `api_call_log`.
- Partial-index UPSERT: both global and user branches succeed against fresh + existing rows.
- `guard_call` does NOT accept `idempotency_key` (regression).

### Integration (real Redis, Postgres test DB)
- Snapshot: 100 INCRs across 5 providers → SCAN excludes `budget:alert:*` → Postgres UPSERTs land in correct partial index.
- Pre-enqueue gate: with aggregate `default.global.daily.limit=2`, fire 3 `enqueue_sync(provider="plaid", user_id=1)` → 3rd returns `state="budget_exceeded"`.
- Telegram: trigger crossing → POST observed; trigger again within dedup → no POST. Force POST failure → dedup key released.
- Cost SQL: trigger 5 OpenAI calls with synthetic usage → `SELECT SUM(estimated_cost_usd) FROM api_call_log WHERE provider='openai'` matches.

### E2E (manual, dev backend)
1. `API_BUDGET_ENABLED=true`, `API_BUDGET_DRY_RUN=true`, `API_BUDGET_THRESHOLDS_JSON='{"providers":{"plaid":{"default":{"global":{"daily":{"warn":2,"limit":3}}}}}}'`. Restart `risk_module`.
2. Trigger 5 Plaid balance refreshes via the standard frontend flow.
3. Verify in `api_call_log`:
   - Call 1: `decision=ok, count_after_global=1`.
   - Call 2: `decision=warned, count_after_global=2`. `log_alert` warning fires (crossing).
   - Call 3: `decision=warned, count_after_global=3`. NO new alert (already past warn).
   - Call 4: `decision=blocked, blocked_scope=global, blocked_key_kind=agg, blocked_window_kind=daily, blocked_threshold=3, blocked_count=4, dry_run=true`. `log_alert` critical + Telegram fires.
   - Call 5: same fields, NO new Telegram (within dedup window).
4. Hit `GET /api/admin/api-budget?provider=plaid` — confirm counts, log rows, today's cost, `redis_state="ok"`.
5. `python -m app_platform.api_budget reset plaid --window daily` → counts 0.
6. `API_BUDGET_DRY_RUN=false`, restart, repeat: 4th call raises `BudgetExceededError` (HTTP 429 with structured error from route layer).
7. Stop Redis: trigger a call → `redis_state="unavailable"`, `decision="ok"`, fail-open, severity=high alert deduped per minute.
8. Pre-enqueue gate: counter at 4 → `enqueue_sync(provider="plaid")` returns `state="budget_exceeded"`.

### Acceptance
- **Every outbound vendor call is guarded exactly once.** This is the load-bearing criterion: one physical SDK/HTTP attempt = one Redis increment. Polling loops increment per attempt. Multi-call public functions increment per call. Retry decorators increment per retry. Cache hits do NOT increment.
- Lua script + Postgres snapshot work end-to-end.
- Admin route surfaces live counters + today's cost per provider (`SELECT SUM(estimated_cost_usd) ... GROUP BY provider`).
- Dry-run rollout for 1 week → real call volumes visible in `api_call_counters` → tune thresholds at 1.5× observed P99 → flip `API_BUDGET_DRY_RUN=false`.
- Telegram alerts fire on threshold crossing + dedupe correctly via claim-then-confirm.
- `budget_user_id` is the cost-guard parameter name (NOT `user_id`, which collides with existing semantics on Plaid/SnapTrade boundary functions).

---

## Risks

1. **`budget_user_id` plumbing surface.** Adding `budget_user_id=None` kwarg to every public boundary function may surface places where the request user isn't readily available. Mitigation: `budget_user_id` is optional; missing means "global only" and no per-user attribution. **SnapTrade holdings path needs explicit threading at multiple drop points (Codex round 4):**
   - `services/position_service.py:322, :2223` — top of chain, already has `user_id`
   - `providers/interfaces.py:36` — `fetch_positions(user_email, **kwargs)` interface accepts kwargs
   - `providers/snaptrade_positions.py:24, :35` — currently only reads `region` from kwargs; PR3 adds `budget_user_id` extraction and forwarding
   - `brokerage/snaptrade/__init__.py:45` — currently doesn't accept `budget_user_id`; PR3 adds parameter
   - `providers/snaptrade_loader.py:850` — re-bound functions; PR3 threads kwarg through
   - `brokerage/snaptrade/client.py:117, :151, :165` — retry helpers; PR3 accepts `budget_user_id` and passes to `guard_call`
   
   Even the existing `client` kwarg passed from `services/position_service.py:2225` isn't honored end-to-end on this path today; PR3 fixes both the unsplitted kwarg drop AND adds `budget_user_id`.

2. **Threshold tuning.** Initial thresholds in `.env.example` are guesses. Phase 3 (tune after observation) is the actual right answer. Risk: dry-run period misses the actual problem if thresholds are too lax. Mitigation: ship with conservative starter thresholds (over-estimate cost = early alerts).

3. **`api_call_log` growth.** ~10K calls/day × LLM-always-logged + 10% sampling for others ≈ ~5K rows/day. With 30-day BRIN-indexed retention, table stays bounded (<200K rows). Re-evaluate partitioning if it crosses 10M.

4. **LLM `cost_fn` signature drift.** OpenAI/Anthropic SDKs occasionally change response shapes. Mitigation: `complete_structured_with_metadata` (PR 6/7 from boundary refactor) already normalizes via `LLMUsage` dataclass; reuse that for cost computation.

5. **Pre-enqueue gate consistency.** Codex round 4 of v4 caught a subtle bug: per-op caps tighter than aggregate caps make the pre-enqueue gate (which checks aggregate only) inconsistent with per-call enforcement. The startup validation rule (per-op limit ≥ aggregate limit) prevents this. Verify the rule fires on a deliberately-bad config in unit tests.

---

## Resolved questions (carried from v4)

1. **Default thresholds in `.env.example`** — Yes; conservative starter JSON (after fixing the example to satisfy startup validation).
2. **Telegram channel** — `API_BUDGET_TELEGRAM_BOT_TOKEN` + `API_BUDGET_TELEGRAM_CHAT_ID`.
3. **`api_call_log` retention** — Daily Celery beat truncate, BRIN(ts) index supports cheap deletes.
4. **`app_platform/` sync** — Ship in `app_platform/`; downstream opts in via `pip install app-platform[api-budget]`.
5. **Cost mapping accuracy** — Conservative (highest tier) — over-estimate triggers earlier alerts.
6. **Cost-based caps** — Deferred to v2; v1 is count-based + Postgres cost reporting.
7. **Streaming LLM** — Out of scope v1.
8. **Op vs aggregate threshold consistency** — Enforced by startup validation rule.
9. **Test blocker / lint mechanism** — Already shipped by boundary refactor; cost guard tests just live under `tests/api_budget/` (already exempt from Rule B).

---

# v4 (BLOCKED) — historical reference

The v4 plan is preserved here for context. v5 supersedes it.

[v4 content removed for brevity in v5; original lives in git history at commit `0a32a5ae` and earlier under this same file path]
