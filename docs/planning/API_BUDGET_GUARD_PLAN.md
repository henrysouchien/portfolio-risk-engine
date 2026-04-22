# Centralized API Budget Guard

**Status:** **BLOCKED** — paused pending the Vendor SDK Boundary Refactor (`VENDOR_SDK_BOUNDARY_REFACTOR_PLAN.md`). Codex review iterations (4 rounds) revealed that the codebase has no real vendor-SDK boundary today: `providers/plaid_loader.py` (legacy) duplicates `brokerage/plaid/` (new), boundary `__init__.py` files re-export raw clients, and ~15+ files across `routes/`, `services/`, `mcp_tools/`, `trading_analysis/`, `scripts/` import vendor SDKs directly. Hermetic cost-guard coverage requires the boundary to exist first. After the refactor lands, this plan will be revived as Phase 2 — its job becomes "add `guard_call(...)` inside the now-hermetic boundary functions" rather than "find every scattered SDK call site."

**Original v4 plan content below (kept for reference):**

---

**v4 — addresses Codex round 3 FAIL findings.**

## Context

The team got hit with an unexpected **$342 Plaid bill in one month of testing** because there was no per-provider call counting, no configurable spend limits, and no proactive alerting. A separate effort patches the specific Plaid balance call, but the gap is systemic: every external provider currently has zero unified visibility into call volume or estimated cost. A runaway loop, retry storm, or scheduler misconfig will silently burn money until the invoice arrives.

This plan introduces a **centralized API budget guard**: every external SDK/HTTP call site is wrapped in `guard_call(...)`, which atomically increments per-operation, provider-aggregate, global, and per-user counters in a dedicated Redis DB via a single Lua script, returns a decision (`ok`/`warned`/`blocked`) reflecting the true max severity across all keys, fires alerts via direct Telegram Bot API calls (no MCP dependency in the running app), and (in non-dry-run mode) raises `BudgetExceededError` when over hard caps. Counters snapshot to Postgres via `SCAN budget:counter:*` every 60s for queryable history. Per-call cost flows to Postgres (`api_call_log`) only — no Redis cost aggregation in v1. A pytest autouse fixture blocks tests from hitting real providers, with a `@pytest.mark.real_provider` opt-in marker; rollout is phased so existing real-provider tests are migrated before the blocker is enabled repo-wide.

**Non-goals (v1):** per-second token-bucket rate limiting (FMP `fmp/client.py` already has 700/min; others don't need it at current scale), pre-call hard-blocking of LLM calls *based on cost* (count caps still apply pre-call; cost-based caps deferred to v2), streaming LLM cost extraction (`providers/completion.py` does not stream today), replacing `services/circuit_breaker.py` (different concern), Redis-side cost aggregation (Postgres-only).

---

## Architecture

### Boundary model — directory as boundary

Codex rounds 2 and 3 caught that the original "one boundary module per provider" design (`brokerage/plaid/sdk.py` next to existing `brokerage/plaid/client.py`) was both incomplete (live SDK call sites scattered across many files) and contradictory (the existing wrapper modules already import vendor SDKs). The cleaner model: **the existing per-provider directory IS the boundary.**

| Provider | Boundary directory | Public API exported via |
|---|---|---|
| Plaid | `brokerage/plaid/` | `brokerage/plaid/__init__.py` |
| Schwab | `brokerage/schwab/` | `brokerage/schwab/__init__.py` |
| SnapTrade | `brokerage/snaptrade/` | `brokerage/snaptrade/__init__.py` |
| IBKR Flex | `ibkr/` (subset — `flex.py` + new `flex_http.py` extracted from `flex.py:1350+`) | `ibkr/__init__.py` |
| OpenAI / Anthropic | `providers/completion.py` (single-file boundary) | module-level public functions |
| FMP | `fmp/` (existing `fmp/client.py` is the SDK wrapper; new `fmp/estimates_client.py` for the rogue HTTP in `fmp/tools/estimates.py:34`) | `fmp/__init__.py`, `fmp/estimates_client.py` |

**Rules:**
1. Vendor SDK imports (`plaid`, `plaid_api`, `plaid.model.*`, `snaptrade_python_sdk`, `schwab`, `schwab.*`, `openai`, `anthropic`) and direct HTTP-to-vendor URLs (`urllib.request.urlopen` to `interactivebrokers.com`, `_requests.get` to `financialmodelupdater.com`) are confined to the boundary directory.
2. Every SDK call inside the boundary is wrapped in `guard_call(...)`.
3. External code (`routes/`, `mcp_tools/`, `services/`, `trading_analysis/`, `scripts/`) calls the boundary's public functions only — never imports vendor SDKs and never accesses internal/private attributes.
4. Public LLM API on `OpenAICompletionProvider` / `AnthropicCompletionProvider` is **`complete()` and `complete_structured()` only**. The previously-public `client` property (`providers/completion.py:67`) is removed (renamed to `_get_client()` internal helper) — external `provider.client.chat.completions.create(...)` access (currently in `scripts/benchmark_editorial_arbiter.py:176`) raises `AttributeError`.

### Refactor inventory (verified live SDK call sites that must move into the boundary or be wrapped)

| File:Line | Current call | Action |
|---|---|---|
| `brokerage/plaid/client.py:266` | `client.accounts_balance_get(request)` | Wrap with `guard_call` (in-place) |
| `brokerage/plaid/client.py:187` | `client.investments_holdings_get(request)` | Wrap |
| `brokerage/plaid/client.py:153` | `client.link_token_get(...)` | Wrap |
| `brokerage/plaid/client.py:97` | `client.link_token_create(req)` | Wrap |
| `brokerage/plaid/connections.py:37` | `client.item_remove(request)` | Wrap |
| `brokerage/plaid/` (any other `institutions_get_by_id`, `item_get`) | Wrap |
| `routes/plaid.py:944` | `plaid_client.item_public_token_exchange(...)` | Move into `brokerage/plaid/`; route calls boundary function |
| `mcp_tools/connections.py:584` | `plaid_client.item_public_token_exchange(...)` | Move into boundary |
| `trading_analysis/data_fetcher.py:414` | `client.investments_transactions_get(...)` | Move into boundary |
| `brokerage/snaptrade/client.py:47` | `client.authentication.register_snap_trade_user(...)` | Wrap |
| `brokerage/snaptrade/client.py:50+` | `client.authentication.login_snap_trade_user(...)` | Wrap |
| All other `brokerage/snaptrade/client.py` SDK calls (auth/order/authz endpoints) | Wrap |
| `brokerage/snaptrade/adapter.py:281` | `client.connections.refresh_brokerage_authorization(...)` | Move into `brokerage/snaptrade/` (new function); adapter calls boundary |
| `mcp_tools/connections.py:257` | `client.connections.list_brokerage_authorizations(...)` | Move into boundary |
| `trading_analysis/data_fetcher.py:287` | `client.account_information.get_account_activities(...)` | Move into boundary |
| `brokerage/schwab/adapter.py:202,206` | `client.get_account(...)` | Wrap |
| `brokerage/schwab/adapter.py:213` | `client.get_quote(symbol)` | Wrap |
| `brokerage/schwab/adapter.py:300+` | `schwab.orders.equities` builder paths + `client.place_order` | Wrap order placement |
| `brokerage/schwab/adapter.py:390` | `client.search_instruments(...)` | Wrap |
| `brokerage/schwab/adapter.py:545` | `client.get_orders_for_account(...)` | Wrap |
| `brokerage/schwab/adapter.py` `cancel_order` | Wrap |
| `brokerage/schwab/client.py:363` | `client.get_account_numbers()` | Wrap |
| `providers/schwab_positions.py:99` | `client.get_account(...)` | Move into `brokerage/schwab/`; caller uses boundary |
| `providers/schwab_transactions.py:177` | `client.get_transactions(...)` | Move into boundary |
| `providers/normalizers/schwab.py:464` | `client.get_quotes(filtered)` | Move into boundary |
| `ibkr/flex.py:1350+` | `urllib.request.urlopen(url, timeout=30)` to `interactivebrokers.com` | Extract to `ibkr/flex_http.py` and wrap |
| `providers/completion.py:79` | `client.chat.completions.create(...)` | Wrap inside `OpenAICompletionProvider.complete()` |
| `providers/completion.py:107` | OpenAI structured | Wrap |
| `providers/completion.py:174` | `client.messages.create(...)` | Wrap inside `AnthropicCompletionProvider.complete()` |
| `providers/completion.py:199` | Anthropic structured | Wrap |
| `providers/completion.py:67` | `client` public property | Remove — make `_get_client()` internal |
| `scripts/benchmark_editorial_arbiter.py:176` | `provider.client.chat.completions.create(...)` | Refactor to `provider.complete(...)` |
| `fmp/client.py:FMPClient.get` | HTTP request | Wrap with `guard_call(provider="fmp", count-only)` |
| `fmp/tools/estimates.py:34` | `_requests.get(...)` to `financialmodelupdater.com` | Move into new `fmp/estimates_client.py` (separate provider name `fmp_estimates`); wrap |

### Storage — Redis primary on dedicated DB

`API_BUDGET_REDIS_URL=redis://localhost:6379/2` — distinct from Celery broker `/1`. Mirrors `services/circuit_breaker.py:30–34`.

**Key namespace split** (Codex round 2):
```
budget:counter:{provider}:{operation}:{scope}:{user_id?}:{window_kind}:{window_start}
budget:counter:{provider}:_all_:{scope}:{user_id?}:{window_kind}:{window_start}    -- aggregate
budget:alert:{provider}:{severity}                                                  -- alert dedup
```
Snapshot uses `SCAN MATCH budget:counter:*` (excludes alerts).

**Cold path:** Celery beat task `snapshot-api-budget` (every 60s) UPSERTs current counters into `api_call_counters`.

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

-- Partial unique indexes (Postgres ≥9.5 supports ON CONFLICT (...) WHERE matching the partial predicate)
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

**UPSERT SQL — global scope:**
```sql
INSERT INTO api_call_counters (provider, operation, scope, user_id, window_kind, window_start, call_count, updated_at)
VALUES ($1, $2, 'global', NULL, $3, $4, $5, NOW())
ON CONFLICT (provider, operation, window_kind, window_start) WHERE scope = 'global'
DO UPDATE SET call_count = EXCLUDED.call_count, updated_at = NOW();
```

**UPSERT SQL — user scope:**
```sql
INSERT INTO api_call_counters (provider, operation, scope, user_id, window_kind, window_start, call_count, updated_at)
VALUES ($1, $2, 'user', $3, $4, $5, $6, NOW())
ON CONFLICT (provider, operation, user_id, window_kind, window_start) WHERE scope = 'user'
DO UPDATE SET call_count = EXCLUDED.call_count, updated_at = NOW();
```

The `WHERE` clause on `ON CONFLICT` matches the partial unique index predicate (Postgres requirement). Snapshot job dispatches to the correct branch based on `scope`.

### Atomic multi-key increment via Lua

```lua
-- KEYS (always present):
--   [1] global_op_daily       budget:counter:{provider}:{operation}:global:daily:{day}
--   [2] global_op_monthly     budget:counter:{provider}:{operation}:global:monthly:{month}
--   [3] global_agg_daily      budget:counter:{provider}:_all_:global:daily:{day}
--   [4] global_agg_monthly    budget:counter:{provider}:_all_:global:monthly:{month}
-- KEYS (optional, present iff user_id supplied):
--   [5] user_op_daily         budget:counter:{provider}:{operation}:user:{user_id}:daily:{day}
--   [6] user_op_monthly       budget:counter:{provider}:{operation}:user:{user_id}:monthly:{month}
--   [7] user_agg_daily        budget:counter:{provider}:_all_:user:{user_id}:daily:{day}
--   [8] user_agg_monthly      budget:counter:{provider}:_all_:user:{user_id}:monthly:{month}
--
-- ARGV: inc_amount,
--       (limit, warn, ttl_seconds) tuples aligned with KEYS, "-1" means no cap.
--
-- Per key: INCRBY, EXPIRE iff TTL not set, compare new vs old.
-- Crossing definition: (new >= threshold) AND (old < threshold). Fires once per key per threshold.
-- If a single increment crosses BOTH warn and limit on the same key, emit ONE crossing record
-- with threshold_kind="limit" (limit subsumes warn).
-- Crossings are returned in KEYS-index ascending order (deterministic).
--
-- Returns: {
--   decision,             -- "ok" | "warned" | "blocked" — max severity across all keys
--   blocked_scope,        -- "global" | "user" | "both" | nil — scope(s) where any key blocked
--   blocked_key_kind,     -- "op" | "agg" | nil — whether per-op or aggregate key blocked first
--   blocked_window_kind,  -- "daily" | "monthly" | nil
--   blocked_threshold,    -- the limit value that was crossed (nil if not blocked)
--   blocked_count,        -- the count at the time of block (nil if not blocked)
--   crossings,            -- ordered list of {key_index, threshold_kind, count_before, count_after}
--   counts,               -- per-key new counts, indexed by KEYS position
-- }
```

`would_block` (v3) is dropped — redundant with `decision == "blocked"`. `decision` is the unconditional truth; `guard_call` decides whether to raise based on `(decision, dry_run config)`:

- `decision="ok"`: proceed.
- `decision="warned"`: log + alert(severity="medium"), proceed.
- `decision="blocked"` AND dry_run: log + alert(severity="high", note="would block"), proceed.
- `decision="blocked"` AND NOT dry_run: log + alert(severity="critical"), raise `BudgetExceededError(blocked_scope, blocked_key_kind, blocked_window_kind, blocked_threshold, blocked_count)`.

### Race / atomicity

Solved by Lua. Two parallel workers at 99 with limit=100: Redis serializes script invocations. Worker A returns `decision="ok", count_after=100`; Worker B returns `decision="blocked", count_after=101`. No read-before-write race.

### Per-user attribution

8 keys at most per call (4 if no user_id). Caps enforced independently per key via the Lua script.

### Configuration — structured JSON + simple env switches + startup validation

```bash
API_BUDGET_ENABLED=true
API_BUDGET_DRY_RUN=true
API_BUDGET_FAIL_OPEN=true
API_BUDGET_REDIS_URL=redis://localhost:6379/2
API_BUDGET_SAMPLE_LOG_PCT=10                         # non-LLM; LLM always 100%
API_BUDGET_SNAPSHOT_INTERVAL_SECONDS=60
API_BUDGET_LOG_RETENTION_DAYS=30
API_BUDGET_TELEGRAM_BOT_TOKEN=
API_BUDGET_TELEGRAM_CHAT_ID=
API_BUDGET_ALERT_DEDUP_SECONDS=600
```

`API_BUDGET_THRESHOLDS_JSON` (single-line, copy-paste valid):
```json
{"providers":{"plaid":{"default":{"global":{"daily":{"warn":80,"limit":100},"monthly":{"warn":2000,"limit":2500}},"per_user":{"daily":{"warn":8,"limit":10},"monthly":{"warn":50,"limit":60}}},"operations":{"accounts_balance_get":{"global":{"daily":{"warn":50,"limit":80}}}}},"openai":{"default":{"global":{"daily":{"warn":1000,"limit":2000}}}},"anthropic":{"default":{"global":{"daily":{"warn":1000,"limit":2000}}}},"snaptrade":{"default":{"global":{"daily":{"warn":500,"limit":800}}}},"schwab":{"default":{"global":{"daily":{"warn":500,"limit":800}}}},"ibkr":{"default":{"global":{"daily":{"warn":50,"limit":100}}}},"fmp":{"default":null},"fmp_estimates":{"default":{"global":{"daily":{"warn":1000,"limit":2000}}}}}}
```

**Startup validation rule (Codex round 3):** for the pre-enqueue gate to be consistent with per-call enforcement, the aggregate cap must be the *floor*: per-operation caps must be ≥ aggregate cap. Validated at startup:

```
For each provider, for each (scope, window):
  agg_limit = providers[p].default[scope][window].limit
  for each op in providers[p].operations:
    op_limit = providers[p].operations[op][scope][window].limit
    if op_limit < agg_limit:
      raise ConfigError(f"{p}.{op} {scope} {window} limit ({op_limit}) is tighter than aggregate ({agg_limit})")
```

Per-op caps may be HIGHER than aggregate (special allowance), but never tighter. This makes the pre-enqueue gate's aggregate-only check **safely conservative**: if aggregate is below limit, no per-op key has crossed limit either.

The example config above (op `accounts_balance_get` limit=80, default limit=100) **violates** this rule and would fail startup. Example fix: raise default limit to 200 if `accounts_balance_get` is the tightest op.

### Failure mode — fail-open + alert only

Redis available: enforce per Lua. Redis unavailable: log `severity=high` (deduped per minute, in-process), allow call, no sampling-block. Operator can flip `API_BUDGET_FAIL_OPEN=false` for hard-stop.

### Idempotency

`guard_call` does NOT take an `idempotency_key` parameter. Spending counts are not deduped.

### Pre-enqueue gate — `services/sync_runner.py`

Verified at `services/sync_runner.py:90`. Modify `enqueue_sync()`:

```python
from app_platform.api_budget import is_provider_over_budget

over_budget, reason = is_provider_over_budget(provider=provider_key, user_id=user_id)
if over_budget:
    portfolio_logger.warning("Skipping sync enqueue: ... reason=%s", reason)
    return {"state": "budget_exceeded", "already_running": False, "task_id": None, "job_id": None, "error": reason}
```

`is_provider_over_budget(provider, user_id=None)` reads via single `MGET` of 2 (or 4) aggregate keys:
- `budget:counter:{provider}:_all_:global:daily:{day}`
- `budget:counter:{provider}:_all_:global:monthly:{month}`
- If `user_id`: same for `:user:{user_id}:`

Compares each to corresponding aggregate threshold from `default.global` / `default.per_user`. Returns over-budget if any exceeds limit. **Consistent with per-call enforcement by construction** (because of the startup validation above).

### Alert delivery — direct Telegram Bot API, claim-then-confirm dedup

Verified pattern at `scripts/check_schwab_token.py:60–79`. `app_platform/api_budget/alerts.py`:

```python
def send_alert(severity, provider, message, **details):
    log_alert(...)                                                     # always (audit)
    if severity not in {"high", "critical"}:
        return
    dedup_key = f"budget:alert:{provider}:{severity}"
    claimed = _redis.set(dedup_key, "1", nx=True, ex=ALERT_DEDUP_SECONDS)
    if not claimed:
        return                                                         # within dedup window
    try:
        _send_telegram(message, **details)                             # urllib POST to bot API
    except Exception:
        _redis.delete(dedup_key)                                       # release claim on failure
        raise
```

Codex round 3 fix: claim-then-confirm avoids suppressing alerts for the full TTL when the Telegram POST fails. If the POST succeeds, the dedup key sticks until natural expiry.

### LLM cost — Postgres-only in v1

No Redis cost aggregation. `estimated_cost_usd` is computed post-call from `LLMUsage` + `LLM_PRICES` and written to `api_call_log`. Sample rate = 100% for LLM providers (`openai`, `anthropic`); non-LLM respect `API_BUDGET_SAMPLE_LOG_PCT`. Aggregate cost via SQL on demand. Cost-based caps deferred to v2; pre-call hard-block uses count caps via Lua.

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

`LLM_PRICES` lives in `config/api_budget_costs.py`.

### Public-API discipline on LLM providers (Codex round 3 raw-client ban)

Currently `OpenAICompletionProvider.client` is a public property (`providers/completion.py:67–77`) that lazily imports `openai` and instantiates the SDK client. Codex correctly noted that renaming to `_client` is just convention — the actual fix is to **remove the public property entirely**:

```python
# providers/completion.py — refactored
class OpenAICompletionProvider:
    def __init__(self, api_key=None, default_model="gpt-4.1"):
        self._api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._default_model = default_model
        self._client_singleton: Any | None = None

    def _get_client(self) -> Any:
        if self._client_singleton is None:
            import openai
            self._client_singleton = openai.OpenAI(api_key=self._api_key)
        return self._client_singleton

    def complete(self, ...) -> ...:
        client = self._get_client()
        return guard_call(
            provider="openai", operation="chat_completions_create",
            cost_fn=openai_usage,
            fn=client.chat.completions.create, ...
        )
```

External `provider.client.chat.completions.create(...)` raises `AttributeError` naturally. Lint test (below) catches `provider.client` access patterns as defense-in-depth. The single known external caller (`scripts/benchmark_editorial_arbiter.py:176`) is refactored to use `provider.complete(...)`.

### Import-lint (with documented limits)

`tests/api_budget/test_import_boundaries.py`:
- AST-walks all `.py` files; checks `Import` and `ImportFrom` nodes.
- Asserts vendor SDK modules are imported only from files inside the boundary directory list.
- Special-case regex for: `importlib.util.find_spec("schwab"|"plaid"|"openai"|"anthropic"|"snaptrade_python_sdk")`, `importlib.import_module("plaid...")`.
- Special-case regex for: `\.client\.(chat|messages)\.` access patterns outside `providers/completion.py`.

**Documented limit:** static patterns only. Runtime safety net = autouse fixture (below).

### Observability — canonical `api_call_log` shape

| Field | Purpose |
|---|---|
| `provider`, `operation`, `caller`, `user_id`, `account_id`, `task_id`, `trace_id` | Standard attribution |
| `duration_ms`, `estimated_cost_usd` | Performance + spend |
| `decision` | `ok` / `warned` / `blocked` / `error` |
| `blocked_scope` | `global` / `user` / `both` — which scope blocked |
| `blocked_key_kind` | `op` / `agg` — was it the per-op or aggregate key |
| `blocked_window_kind` | `daily` / `monthly` |
| `blocked_threshold` | The limit value crossed |
| `blocked_count` | The count at block time |
| `count_before_global`, `count_after_global` | Aggregate context |
| `count_before_user`, `count_after_user` | Per-user context |
| `dry_run`, `redis_state` | Mode flags |

A blocked row is now self-explanatory: `blocked_scope=user, blocked_key_kind=op, blocked_window_kind=daily, blocked_threshold=10, blocked_count=11` reads as "user-scope per-operation daily limit of 10 was exceeded at count 11."

### Admin route + CLI

- `GET /api/admin/api-budget?provider=plaid` — admin auth required; returns live counters, recent log rows, threshold config, today's cost per provider, `redis_state`.
- `python -m app_platform.api_budget status [--provider plaid]`
- `python -m app_platform.api_budget reset plaid --window daily [--user-id 42]`

---

## Test rollout — 2-PR sequence (Codex round 3)

The repo currently has 3 autouse fixtures in `tests/conftest.py:1` and uses env-gated patterns for real-provider tests (e.g., `tests/fmp/test_fmp_client.py:873` skipif-no-key, `tests/snaptrade/test_snaptrade_registration.py:24`). `pytest.ini` has no `markers` registration. Flipping a repo-wide blocker before migrating these would break the test suite.

**PR 1 (test infrastructure prep):**
1. Add `markers` registration to `pytest.ini`:
   ```ini
   [pytest]
   markers =
       real_provider: test makes real external API calls; opt-in via @pytest.mark.real_provider
   ```
2. Migrate existing real-provider tests to `@pytest.mark.real_provider` (mechanical: replace `@pytest.mark.skipif(not os.getenv(...))` with the marker; the marker handler in `tests/api_budget/conftest.py` honors env-gating via fixture).
3. Add `tests/api_budget/conftest.py` with the `_block_real_provider_calls` autouse fixture, scoped to `tests/api_budget/` only initially — proves the mechanism works without affecting the broader suite.

**PR 2 (flip repo-wide):**
1. Move `_block_real_provider_calls` registration from `tests/api_budget/conftest.py` to `tests/conftest.py` so all tests outside `tests/api_budget/` are also blocked unless they have the marker or use the `allow_real_provider_calls` fixture.
2. Verify full test suite still passes.
3. Ship.

The fixture honors `request.node.iter_markers("real_provider")` and `request.fixturenames` to skip its blocker when opted in.

---

## Files Modified / Added

### New (framework — `app_platform/api_budget/`)
- `app_platform/api_budget/__init__.py`
- `app_platform/api_budget/guard.py`
- `app_platform/api_budget/store.py`
- `app_platform/api_budget/lua/budget_incr.lua`
- `app_platform/api_budget/config.py` — includes startup validation (op-vs-aggregate consistency rule)
- `app_platform/api_budget/exceptions.py`
- `app_platform/api_budget/alerts.py` — claim-then-confirm dedup
- `app_platform/api_budget/snapshot.py` — uses `SCAN MATCH budget:counter:*`, partial-index UPSERT branches
- `app_platform/api_budget/llm_cost.py`
- `app_platform/api_budget/cli.py`
- `app_platform/pyproject.toml` — add `api-budget = ["redis>=5.0,<6"]`; update `all`

### New (project — `risk_module/`)
- `ibkr/flex_http.py` — extract `urlopen` calls from `flex.py:1350+`; wrap with `guard_call`
- `fmp/estimates_client.py` — extract `_requests.get` from `fmp/tools/estimates.py:34`; wrap
- `config/api_budget_costs.py` — `COST_PER_CALL`, `LLM_PRICES`
- `database/migrations/NNNN_api_budget.sql`
- `routes/admin_api_budget.py`
- `tests/api_budget/conftest.py` — autouse + `@pytest.mark.real_provider` opt-in
- `tests/api_budget/test_lua_atomicity.py` — multi-key INCR, TTL set-once, crossing detection (single + dual-threshold), decision-max-severity, blocked_scope/key_kind/window_kind/threshold/count
- `tests/api_budget/test_guard.py` — dry-run vs live, fail-open, aggregate consistency
- `tests/api_budget/test_config_validation.py` — op-vs-aggregate consistency, copy-paste-valid JSON
- `tests/api_budget/test_import_boundaries.py` — static + dynamic-import + raw-client-access detection
- `tests/api_budget/test_sync_runner_gate.py`
- `tests/api_budget/test_snapshot.py` — partial-index UPSERT correctness for both scopes
- `tests/api_budget/test_alerts.py` — claim-then-confirm dedup + send-failure rollback
- `tests/api_budget/test_llm_cost.py`
- `tests/api_budget/test_no_real_provider_calls.py`

### Modified — wrap SDK calls in place + refactor external callers to use boundary public functions
(see Refactor inventory table above for the full list)

Notable changes:
- `providers/completion.py` — remove public `client` property; add `_get_client()`; wrap both providers' `complete` and `complete_structured` with `guard_call(cost_fn=...)`
- `scripts/benchmark_editorial_arbiter.py:176` — refactor to `provider.complete(...)`
- `services/sync_runner.py:90` — pre-enqueue `is_provider_over_budget()` gate
- `workers/beat_schedule.py` — add `snapshot-api-budget` (60s) + `truncate-api-call-log` (daily)
- `pytest.ini` — register `real_provider` marker (PR 1)
- `tests/conftest.py` — apply `_block_real_provider_calls` autouse repo-wide (PR 2)
- `.env.example` — add documented env vars + starter `API_BUDGET_THRESHOLDS_JSON` (passing the startup validation rule)

### Reused
- `utils/logging.py` — `log_alert()`, `log_event()`, `log_usage()`
- `services/circuit_breaker.py:30–34` — Redis client pattern
- `services/sync_runner.py:48–49,90` — Redis pattern + enqueue gate point
- `database/session.py` — `SessionManager`
- `scripts/check_schwab_token.py:60–79` — Telegram pattern

---

## Verification

### Unit (no external deps)
- Lua: atomic increment of all 4/8 keys, TTL set-once, crossings ordered by KEYS index ascending.
- Lua: dual-threshold same call (warn AND limit crossed in one increment) emits ONE crossing with `threshold_kind="limit"`.
- Lua: `decision = max severity across all keys` (cases: global=warned + user=blocked → `blocked, blocked_scope=user`; global=blocked + user=blocked → `blocked, blocked_scope=both`; both=ok → `ok`).
- Lua: `blocked_key_kind`, `blocked_window_kind`, `blocked_threshold`, `blocked_count` correctly populated for each blocking case.
- `guard_call` dry-run: `decision=blocked` → log + alert + return (no raise).
- `guard_call` live: `decision=blocked` → raise `BudgetExceededError` with all blocked_* fields.
- `is_provider_over_budget` performs a single `MGET` of 2 (or 4) aggregate keys.
- Config validation: rejects example with op limit < aggregate limit; accepts conforming config.
- Import lint: catches static `from plaid import api`, `importlib.util.find_spec("plaid_api")`, `provider.client.chat.completions...` outside `providers/completion.py`.
- Telegram dedup: claim-then-confirm releases dedup key on send failure (regression test).
- LLM: `openai_usage` and `anthropic_usage` map response shapes correctly; `estimated_cost_usd` written to `api_call_log`.
- Partial-index UPSERT: both global and user branches succeed against fresh + existing rows.

### Integration (real Redis, Postgres test DB)
- Snapshot: 100 INCRs across 5 providers via Lua → `SCAN MATCH budget:counter:*` excludes `budget:alert:*` → Postgres UPSERTs land in correct partial index.
- Pre-enqueue gate: with aggregate `default.global.daily.limit=2`, fire 3 `enqueue_sync(provider="plaid", user_id=1)` → 3rd returns `state="budget_exceeded"` (aggregate aware).
- Telegram: trigger crossing → POST observed; trigger again within dedup → no POST. Force POST failure → assert dedup key released.

### E2E (manual, against dev backend)
1. `API_BUDGET_ENABLED=true`, `API_BUDGET_DRY_RUN=true`, `API_BUDGET_THRESHOLDS_JSON='{"providers":{"plaid":{"default":{"global":{"daily":{"warn":2,"limit":3}}}}}}'`. Restart `risk_module`.
2. Trigger 5 Plaid balance refreshes:
   - Call 1: `decision=ok, count_after_global=1`.
   - Call 2: `decision=warned, count_after_global=2`. `log_alert` warning fires (crossing).
   - Call 3: `decision=warned, count_after_global=3`. NO new alert (already past warn).
   - Call 4: `decision=blocked, blocked_scope=global, blocked_key_kind=agg, blocked_window_kind=daily, blocked_threshold=3, blocked_count=4, dry_run=true`. `log_alert` critical + Telegram fires.
   - Call 5: same fields, NO new Telegram (within dedup window).
3. `GET /api/admin/api-budget?provider=plaid` — counts, log rows, `redis_state="ok"`, today's cost.
4. `python -m app_platform.api_budget reset plaid --window daily` → counts back to 0.
5. `API_BUDGET_DRY_RUN=false`, restart, repeat: 4th call raises `BudgetExceededError` (HTTP 429).
6. Stop Redis: call → `redis_state="unavailable"`, `decision="ok"`, fail-open, `severity=high` deduped.
7. Pre-enqueue gate: counter at 4 → `enqueue_sync(provider="plaid")` returns `state="budget_exceeded"`.
8. Provider `client` access ban: `python -c "from providers.completion import OpenAICompletionProvider; OpenAICompletionProvider().client"` → `AttributeError`.

### Pytest autouse + opt-in (after PR 2)
- Test mocking the boundary → passes.
- Test without mock + no marker → fails: `RuntimeError("Real provider call attempted in test; use @pytest.mark.real_provider or allow_real_provider_calls fixture")`.
- Test marked `@pytest.mark.real_provider` → autouse skips block, test proceeds.

---

## Rollout

1. **Phase 1 — Framework + Plaid only** (1 PR): Build `app_platform/api_budget/`, schema migration, wrap all `brokerage/plaid/` SDK calls, refactor `routes/plaid.py:944` + `mcp_tools/connections.py:584` + `trading_analysis/data_fetcher.py:414` to call boundary functions, add `is_provider_over_budget()` gate to `sync_runner.py`, dry-run on, Telegram off. Verify no functional regression. Ship `app_platform[api-budget]` extra.
2. **Phase 2a — Test rollout PR 1** (test-only): register `real_provider` marker in `pytest.ini`; migrate existing real-provider tests to the marker; add `tests/api_budget/conftest.py` with autouse scoped to `tests/api_budget/`.
3. **Phase 2b — Test rollout PR 2** (test-only): flip autouse repo-wide via `tests/conftest.py`. Verify full suite passes.
4. **Phase 3 — Remaining provider boundaries** (1 PR per or mega-PR): Schwab (incl. `brokerage/schwab/adapter.py:202,213,300+,390,545`, refactor `providers/schwab_*.py`), SnapTrade (incl. `trading_analysis/data_fetcher.py:287`, `mcp_tools/connections.py:257`), IBKR Flex extract, OpenAI/Anthropic (incl. removing public `client` property + refactor `scripts/benchmark_editorial_arbiter.py:176`), FMP, FMP estimates extract.
5. **Phase 4 — Tune + flip dry-run off**: 1 week observation, set thresholds at 1.5× observed P99, configure Telegram, flip `API_BUDGET_DRY_RUN=false`.
6. **Phase 5 — Admin UI** (optional): frontend tile for live counters + cost.

---

## Resolved questions (v1 → v4)

1. **Default thresholds in `.env.example`** — yes, conservative starter JSON above.
2. **Telegram channel** — `API_BUDGET_TELEGRAM_BOT_TOKEN` + `API_BUDGET_TELEGRAM_CHAT_ID`.
3. **`api_call_log` retention** — daily Celery beat, `BRIN(ts)` index supports cheap deletes.
4. **`app_platform/` sync** — ship in `app_platform/`; `[api-budget]` extra; downstream installs `app-platform[api-budget]`.
5. **Cost mapping accuracy** — conservative (highest tier).
6. **Cost-based caps** — deferred to v2; v1 is count-based + Postgres cost reporting.
7. **Streaming LLM** — out of scope v1.
8. **Op vs aggregate threshold consistency** — enforced by startup validation rule (per-op limits must be ≥ aggregate limits).
9. **Test blocker rollout** — phased over 2 PRs (register marker + migrate; then flip repo-wide).
