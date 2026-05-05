# V4e — LLM Cost-Accuracy + Token-Volume Telemetry

**Parent:** `docs/planning/API_BUDGET_GUARD_PLAN.md` (cost guard cluster)
**Upstream:** `docs/planning/completed/V4D_PROVIDER_RATE_VERIFICATION_PLAN.md` (R2 §0 surfaced this gap, 2026-04-25)
**Sibling:** `docs/planning/completed/API_BUDGET_SUBSCRIPTION_DIMENSION_PLAN.md` (V4a — P1 migration shipped at `d3f4e3bb`, full ship at `483374be` 2026-04-26)
**Date:** 2026-04-26
**Status:** Draft (v2 — addresses Codex R1 FAIL: math correctness on `input_tokens` semantics, migration ordering claim, row-scan claim, line-number drift)

---

## 1. Problem

Two related gaps in the LLM cost-guard pipeline, both rooted in the same data structure (`LLMUsage`) and the same persistence path (`api_call_log`).

### 1.1 Cost-accuracy gap (from V4d §0 finding, 2026-04-25)

The current `LLMUsage` dataclass at `app_platform/api_budget/llm_cost.py:10-14` carries only three fields:

```python
@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int
    model: str
```

`estimate_cost_usd()` (`app_platform/api_budget/llm_cost.py:59-71`) bills both buckets at the flat per-1M-token rates from `LLM_PRICES` (`config/api_budget_costs.py:114-120`).

This is wrong for Anthropic in two billable dimensions:

1. **Prompt caching.** When a caller passes `cache_control` blocks, Anthropic returns split token counts: `cache_creation_input_tokens` (billed at **125%** of base input rate, i.e. write surcharge) and `cache_read_input_tokens` (billed at **10%** of base input rate, i.e. cache hit). Verified at the SDK layer: `anthropic.types.usage.Usage` exposes `input_tokens: int`, `output_tokens: int`, `cache_creation_input_tokens: Optional[int]`, `cache_read_input_tokens: Optional[int]` (introspected via `anthropic.types.usage.Usage.model_fields` against the installed SDK, 2026-04-26). Today's `anthropic_usage` adapter (`app_platform/api_budget/llm_cost.py:26-32`) reads only `input_tokens` and `output_tokens` — the cache fields are silently dropped.
2. **Batch API.** Anthropic Batch endpoints discount **50%** off both input and output rates. The SDK signals batch via `Message.usage.service_tier == "batch"` (verified field on the same Usage type, 2026-04-26). Today's adapter never reads `service_tier`.

Combined, real Anthropic spend can diverge **15–90%** from `api_call_log.estimated_cost_usd` depending on cache hit rate and any batch usage. Today's actual call sites do not yet pass `cache_control` (single guard call at `providers/completion.py:402-410`), so the live miscount is small — but as soon as V2.P5 (stable-prefix prompt caching audit, `docs/TODO.md` row) ships, the divergence becomes load-bearing.

### 1.2 Observability gap (from V4a planning discussion, 2026-04-25)

Token volumes are computed at call-time inside the `cost_fn` adapters (`openai_usage` / `anthropic_usage`) → consumed by `estimate_cost_usd()` → converted to a single `Decimal` USD value → stored in `api_call_log.estimated_cost_usd` → token counts **discarded**.

Verified by reading every column on the `api_call_log` table:
- Original `database/migrations/20260426_api_budget.sql:24-48` ships 21 columns.
- V4a P1 (`database/migrations/20260427_api_budget_subscription_dimension.sql:51-53`, commit `d3f4e3bb`) adds two more: `item_id`, `cost_model`.

None of the 23 columns is a token count. Today:

| Question | Answerable? |
|---|---|
| "How much did Anthropic cost yesterday?" | YES — `SUM(estimated_cost_usd) WHERE provider='anthropic'` |
| "How many tokens did we burn?" | NO in production. YES in eval harness (`evals/vals-finance-agent/harness/trace_logger.py:72-76` records `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`) |
| "Did we save money from prompt caching last week?" | NO — cache reads vs full input invisible |
| "What's our average input length per Anthropic call?" | NO |

The asymmetry between eval harness (which already captures all five token dimensions) and production (which captures none) is itself the argument: the data exists at the SDK boundary; we throw it away. Restoring it costs ~5 columns of nullable storage per call.

### 1.3 Why combine the two gaps

Both touch the same three files in lockstep:
1. `app_platform/api_budget/llm_cost.py` — `LLMUsage` schema + `estimate_cost_usd` math.
2. `app_platform/api_budget/guard.py` — `_compute_cost_for_log` + `_maybe_write_api_call_log` payload (which V4a just expanded for `item_id` + `cost_model`).
3. `database/migrations/` — `api_call_log` columns + `cost_model` CHECK constraint.

Splitting them would force two migrations + two adapter changes touching the same lines — needless rebase risk against V4a. Combining keeps the migration single and locks the adapter in one shape.

---

## 2. Goal

Extend the LLM cost-guard pipeline so that:

1. **Cost accuracy.** `estimate_cost_usd()` produces an Anthropic dollar figure correct to within Anthropic's published billing rules, regardless of cache hit rate or batch usage.
2. **Token observability.** `api_call_log` rows carry the raw token decomposition (`input_tokens`, `output_tokens`, `cache_creation_tokens`, `cache_read_tokens`, `is_batch`) so production analytics match eval-harness analytics.
3. **Backwards compat.** Every change is additive: new `LLMUsage` fields are `Optional` with defaults; new `api_call_log` columns are NULLable; `cost_model` enum is extended (not replaced); existing non-LLM call sites and existing rows behave identically. OpenAI rows continue to populate input/output tokens but leave cache fields NULL — OpenAI's Chat Completions API doesn't expose comparable cache split fields, so no behavior change there.

Target outcome:

- `LLMUsage` exposes 5 new optional fields; `anthropic_usage` populates them; `openai_usage` stays at 2 fields.
- `estimate_cost_usd()` applies cache-tier rates + batch multiplier for Anthropic; falls back to today's flat math when cache/batch fields are absent or zero.
- `api_call_log` gains 5 nullable columns; `cost_model` CHECK constraint extended with `'per_token'`.
- `get_cost_model_and_rate()` returns `('per_token', Decimal('0'))` for `provider in _LLM_PROVIDERS`.
- `_compute_cost_for_log` gains a third `'per_token'` branch that persists the token decomposition alongside the dollar estimate.

---

## 3. Non-Goals

- **Not refactoring the `cost_fn` architecture.** `cost_fn` returns `LLMUsage`; `estimate_cost_usd()` consumes it; that contract stays. V4a's `_compute_cost_for_log` 2-tuple `(Decimal | None, str)` is **extended to a 3-tuple** `(Decimal | None, str, dict | None)` to carry token telemetry alongside cost — see §4.7. This is an additive shape change at the function boundary; both call sites in `guard.py` are updated atomically (Phase 4).
- **Not adding token-budget thresholds.** V4d §2 confirmed token-priced billing is already representable end-to-end; threshold-on-tokens is a future V4f-or-later concern. V4e's job is accuracy + observability, not new enforcement.
- **Not extending OpenAI to fake cache fields.** OpenAI Chat Completions returns `prompt_tokens`/`completion_tokens` only (verified via the existing `_build_openai_usage` adapter at `providers/completion.py:128-135` and the `openai_usage` test at `tests/api_budget/test_llm_cost.py:10-20`). New cache fields stay `None` for OpenAI.
- **Not backfilling historical rows.** Rows logged before this migration leave the new columns NULL. Migration is forward-only.
- **Not touching the eval harness.** `evals/vals-finance-agent/harness/trace_logger.py:72-76` already records the same token decomposition independently. V4e brings production into parity with eval; eval stays as-is.
- **Not changing alert/threshold logic.** `is_provider_over_budget`, threshold tuning, and Telegram routing are unchanged.
- **Not a full audit of every Anthropic billing edge case.** Service-tier `"priority"` (Priority Tier discount), input geo (`inference_geo`), and `server_tool_use` are visible on `Usage` but out of V4e scope — they are non-zero only when the caller explicitly opts in, and we don't.

---

## 4. Target architecture

### 4.1 New `LLMUsage` field set

`app_platform/api_budget/llm_cost.py`:

```python
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class LLMUsage:
    # Existing — unchanged shape, unchanged callers.
    input_tokens: int
    output_tokens: int
    model: str
    # New — all Optional so OpenAI adapter (and any future provider) can leave NULL.
    cache_creation_tokens: Optional[int] = None  # Anthropic: response.usage.cache_creation_input_tokens
    cache_read_tokens: Optional[int] = None      # Anthropic: response.usage.cache_read_input_tokens
    is_batch: Optional[bool] = None              # Anthropic: response.usage.service_tier == "batch"
```

Why three fields and not five: `input_tokens` and `output_tokens` already exist; we only add the three Anthropic dimensions. Naming convention follows the eval harness (`cache_read_tokens`, `cache_write_tokens` ≈ our `cache_creation_tokens`) — except the eval calls writes "writes" and Anthropic SDK calls them "creation", so the SDK name wins to avoid ambiguity at the adapter layer.

`@dataclass(frozen=True)` + Optional defaults means existing call sites that construct `LLMUsage(input_tokens=..., output_tokens=..., model=...)` keep working unchanged.

### 4.2 Adapter updates

`anthropic_usage` (currently `llm_cost.py:26-32`):

```python
def anthropic_usage(response: Any) -> LLMUsage:
    usage = getattr(response, "usage", None)
    return LLMUsage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        model=str(getattr(response, "model", None) or ""),
        cache_creation_tokens=_safe_int(getattr(usage, "cache_creation_input_tokens", None)),
        cache_read_tokens=_safe_int(getattr(usage, "cache_read_input_tokens", None)),
        is_batch=(getattr(usage, "service_tier", None) == "batch"),
    )
```

`_safe_int` is a private helper that returns `None` on missing/None input and `int(value)` otherwise — preserves the "field absent → NULL in DB" semantic. Without it, `int(None)` would throw and `int(0)` would lose the absent/zero distinction in analytics.

`openai_usage` is unchanged — the new optional fields default to `None`.

### 4.3 `estimate_cost_usd` math

Cache-aware billing rules (verified against claude.com/pricing, locked at V4d R2 2026-04-25):

| Token bucket | Anthropic rate | Notes |
|---|---|---|
| Plain input (no cache) | `input_per_1m_tokens` × 100% | today's behavior |
| Cache write (`cache_creation_tokens`) | `input_per_1m_tokens` × **125%** | one-time surcharge |
| Cache read (`cache_read_tokens`) | `input_per_1m_tokens` × **10%** | hit discount |
| Output | `output_per_1m_tokens` × 100% | today's behavior |
| Batch (any of the above) | × **50%** | applies after cache math, on the total |

Math the proposed `estimate_cost_usd` runs (pseudocode):

```python
def estimate_cost_usd(usage, prices=None) -> Decimal | None:
    pricing = lookup_model_pricing(usage.model, prices=prices)
    if pricing is None:
        return None

    input_rate = Decimal(str(pricing["input_per_1m_tokens"]))
    output_rate = Decimal(str(pricing["output_per_1m_tokens"]))
    M = Decimal(1_000_000)

    cache_create = usage.cache_creation_tokens or 0
    cache_read   = usage.cache_read_tokens or 0
    plain_input  = usage.input_tokens
    # Anthropic SDK contract (verified Codex R1, 2026-04-26): Usage.input_tokens
    # is the NET/plain bucket — cache buckets reported separately. Total input
    # tokens = input_tokens + cache_creation_input_tokens + cache_read_input_tokens.
    # Do NOT subtract; that would undercount cached requests by double-removing
    # tokens that were never in input_tokens to begin with.

    cost = (
        Decimal(plain_input)  / M * input_rate
        + Decimal(cache_create) / M * input_rate * Decimal("1.25")
        + Decimal(cache_read)   / M * input_rate * Decimal("0.10")
        + Decimal(usage.output_tokens) / M * output_rate
    )
    if usage.is_batch:
        cost *= Decimal("0.5")
    return cost.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
```

Backwards-compat invariant: when `cache_creation_tokens`, `cache_read_tokens`, and `is_batch` are all `None`/falsy (the current state of every call), `cache_create + cache_read == 0` and the math reduces to `plain_input × input_rate + output_tokens × output_rate` — byte-identical to today's formula. Existing tests at `tests/api_budget/test_llm_cost.py:36-74` keep passing. **Phase 6 test plan adds a regression case with non-zero plain + cache + batch tokens** to lock the new math (caught by Codex R1 — see §6).

### 4.4 `LLM_PRICES` config — no surface change required

`config/api_budget_costs.py:114-120` already keys by base model. Cache and batch are derived multipliers in the math layer, not separate price entries. We do **not** add `cache_input_per_1m_tokens` etc. to `LLM_PRICES` — that would mean four price entries per model, four chances for drift. Single `input_per_1m_tokens` × derived multiplier is the canonical Anthropic billing shape.

If a future provider has cache tiers with non-standard multipliers, that becomes a per-provider override on `LLM_PRICES` — out of V4e scope.

### 4.5 Migration — `api_call_log` columns + `cost_model` CHECK

V4a's P1 migration (`database/migrations/20260427_api_budget_subscription_dimension.sql:51-65`, commit `d3f4e3bb`) added `item_id` + `cost_model` and registered the CHECK with idempotent `IF NOT EXISTS` + `pg_constraint` lookup. V4e follows the same pattern.

New migration `database/migrations/20260428_api_budget_llm_telemetry.sql` (proposed name; date will be the actual ship date):

```sql
-- Purpose: V4e — LLM cost-accuracy + token-volume telemetry columns + 'per_token' cost_model.
-- Date: 2026-04-?? (TBD on ship). Reference: docs/planning/V4E_LLM_COST_ACCURACY_PLAN.md.

-- ========== api_call_log: per-call token decomposition ==========
ALTER TABLE api_call_log
  ADD COLUMN IF NOT EXISTS input_tokens          INTEGER NULL,
  ADD COLUMN IF NOT EXISTS output_tokens         INTEGER NULL,
  ADD COLUMN IF NOT EXISTS cache_creation_tokens INTEGER NULL,
  ADD COLUMN IF NOT EXISTS cache_read_tokens     INTEGER NULL,
  ADD COLUMN IF NOT EXISTS is_batch              BOOLEAN NULL;

-- ========== Extend cost_model CHECK constraint to allow 'per_token' ==========
-- V4a P1 (commit d3f4e3bb) shipped CHECK ('per_call', 'per_item_month',
-- 'per_connected_user_month'). V4e adds 'per_token' for LLM rows.
-- Idempotent: drop-if-exists, recreate. Postgres DOES validate existing rows
-- on ADD CONSTRAINT (not skipped by NULL-bypass — per Codex R1). On a
-- production-sized api_call_log this scan is bounded by table size; if it
-- becomes prohibitive in future, switch to ADD CONSTRAINT ... NOT VALID
-- followed by VALIDATE CONSTRAINT in a separate transaction.
DO $$ BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname  = 'api_call_log_cost_model_check'
      AND conrelid = 'api_call_log'::regclass
  ) THEN
    ALTER TABLE api_call_log DROP CONSTRAINT api_call_log_cost_model_check;
  END IF;
  ALTER TABLE api_call_log
    ADD CONSTRAINT api_call_log_cost_model_check
    CHECK (cost_model IS NULL OR cost_model IN (
      'per_call', 'per_item_month', 'per_connected_user_month', 'per_token'
    ));
END $$;
```

**Idempotency contract — V4a P1 is a hard prerequisite** (Codex R1 correction): the V4e migration's CHECK addition references the `cost_model` column; if V4e ran before V4a P1, the `ADD CONSTRAINT ... CHECK (cost_model ...)` would fail because `cost_model` does not exist. V4a P1 already shipped at commit `d3f4e3bb`, so normal forward order is the only deployment path — this is not a "both orders safe" claim. The plan v1 statement to the contrary was wrong; the migration must be applied after V4a P1 in any clean-slate environment. (Alternative: add `ADD COLUMN IF NOT EXISTS cost_model TEXT NULL` to V4e to make it self-contained — chose not to, because cluttering V4e with V4a's column hides the dependency and risks divergent CHECK enums.)

**No new indexes.** Token columns are not in any current query's WHERE clause; they support analytical aggregations that the BRIN `ix_api_call_log_ts` already covers via time-window pre-filter.

### 4.6 `get_cost_model_and_rate` — register `'per_token'` for LLM providers

Today (`config/api_budget_costs.py:97-111`):

```python
def get_cost_model_and_rate(provider, operation) -> tuple[Literal["per_call", "per_item_month", "per_connected_user_month"], Decimal]:
    ...
    return ("per_call", COST_PER_CALL.get(key, Decimal("0")))
```

V4e extends:

```python
_LLM_PROVIDERS_LOCAL = frozenset({"openai", "anthropic"})  # mirrors guard.py:31

def get_cost_model_and_rate(provider, operation) -> tuple[
    Literal["per_call", "per_item_month", "per_connected_user_month", "per_token"],
    Decimal,
]:
    provider_key = str(provider or "").strip().lower()
    operation_key = str(operation or "").strip()
    key = (provider_key, operation_key)

    plaid_sub_rate = SUBSCRIPTION_COSTS_PER_ITEM_MONTH.get(key)
    if plaid_sub_rate is not None:
        return ("per_item_month", plaid_sub_rate)

    if provider_key == "snaptrade" and operation_key in SNAPTRADE_SUBSCRIPTION_OPS:
        return ("per_connected_user_month", SNAPTRADE_PER_CONNECTED_USER_MONTH_RATE)

    if provider_key in _LLM_PROVIDERS_LOCAL:
        return ("per_token", Decimal("0"))  # actual rate computed in estimate_cost_usd

    return ("per_call", COST_PER_CALL.get(key, Decimal("0")))
```

The LLM check has to come AFTER the subscription branches (LLM providers don't appear in either subscription table today, but the ordering is cheap insurance against future drift) and BEFORE the per-call fallback (which would otherwise mis-label every Anthropic row as `'per_call'`).

`Decimal("0")` is the sentinel "no flat rate, compute via estimate_cost_usd". The `_compute_cost_for_log` per-token branch ignores `rate` entirely — that branch only reads `cost_fn(result)` → `LLMUsage` → `estimate_cost_usd(...)`.

Open question Q4 below: should `_LLM_PROVIDERS` move out of `guard.py:31` into the config module so it's the single source of truth? Today it's defined in two places (the literal in `guard.py:31` and the new `_LLM_PROVIDERS_LOCAL` here). Defaulting to "leave both" until Codex weighs in.

### 4.7 `_compute_cost_for_log` — per-token branch + token persistence

V4a's `_compute_cost_for_log` (`app_platform/api_budget/guard.py:87-154`) returns `tuple[Decimal | None, str]`. V4e extends it to return token data alongside.

Two design options:

**Option A — extend the return tuple.** `tuple[Decimal | None, str, dict[str, Any] | None]` where the dict carries the token decomposition. Caller (`_maybe_write_api_call_log`) unpacks and merges into the row dict.

**Option B — keep return shape, add separate helper.** `_extract_llm_telemetry(result, cost_fn) -> dict | None` called separately at the same sites. Avoids touching V4a's tuple shape.

Going with **Option A** in this draft because the token decomposition is fundamentally part of the same per-call cost computation — splitting it duplicates the `cost_fn(result)` call. (Alternative would be caching the `LLMUsage` between calls, which adds a parameter-passing mess.) Codex Q5 below.

```python
def _compute_cost_for_log(
    *,
    provider_key: str,
    operation_key: str,
    cost_model: Literal["per_call", "per_item_month", "per_connected_user_month", "per_token"],
    rate: Decimal,
    item_key: str | None,
    budget_user_id: int | None,
    result: Any,
    cost_fn: Callable[[Any], Any] | None,
    cost_per_call: Decimal | float | int | str | None,
    billing_month: date,
) -> tuple[Decimal | None, str, dict[str, Any] | None]:
    """Returns (estimated_cost, effective_cost_model, token_telemetry).

    token_telemetry is populated for cost_model='per_token' only; otherwise None.
    """
    if result is None:
        return (None, cost_model, None)

    if cost_model == "per_item_month":
        ...  # unchanged from V4a; returns (cost, model, None)

    if cost_model == "per_connected_user_month":
        ...  # unchanged; returns (cost, model, None)

    if cost_model == "per_token":
        # cost_fn is required for per_token (anthropic_usage / openai_usage);
        # if absent, fall back to None cost + no telemetry (pathological — log warning).
        if cost_fn is None:
            return (None, cost_model, None)
        usage = cost_fn(result)
        if not isinstance(usage, LLMUsage):
            return (_round_cost(usage), cost_model, None)
        cost = estimate_cost_usd(usage)
        telemetry = {
            "input_tokens":          int(usage.input_tokens),
            "output_tokens":         int(usage.output_tokens),
            "cache_creation_tokens": usage.cache_creation_tokens,  # may be None
            "cache_read_tokens":     usage.cache_read_tokens,      # may be None
            "is_batch":              usage.is_batch,                # may be None
        }
        return (cost, cost_model, telemetry)

    # per_call fallback — unchanged
    return (
        _estimate_cost(...),
        cost_model,
        None,
    )
```

`_maybe_write_api_call_log` (`guard.py:248-309`) gains a single new kwarg `token_telemetry: dict[str, Any] | None`; if non-None, its five keys merge into the row dict before `_write_api_call_log`. The INSERT statement at `guard.py:182-235` gains five new columns and five new placeholders. Existing non-LLM call sites pass `token_telemetry=None` → all five fields persist as NULL.

---

## 5. Phased plan

### Phase 1 — Schema migration

1. Author `database/migrations/<date>_api_budget_llm_telemetry.sql` per §4.5.
2. Apply locally; verify `\d api_call_log` shows the five new columns and the four-value CHECK.
3. Idempotency check: re-apply migration; verify zero errors and zero schema drift.
4. **No code changes in this phase.** Migration is reversible by manual `DROP COLUMN` if rolled back before Phase 2 lands.

**Exit criteria:** migration applies cleanly forward and is idempotent on re-run; CHECK constraint enumerates four values.

### Phase 2 — `LLMUsage` schema + adapter updates

1. Extend `LLMUsage` dataclass in `app_platform/api_budget/llm_cost.py` per §4.1.
2. Update `anthropic_usage` per §4.2 (with `_safe_int` helper).
3. Leave `openai_usage` unchanged (defaults handle the new fields).
4. Update existing tests at `tests/api_budget/test_llm_cost.py:23-33` — keep the existing `anthropic_usage` test as the "no cache" case, add three new tests:
   - `test_anthropic_usage_populates_cache_fields_from_sdk_response`
   - `test_anthropic_usage_returns_none_when_cache_fields_absent`
   - `test_anthropic_usage_detects_batch_via_service_tier`
5. Existing `openai_usage` test stays unchanged; add `test_openai_usage_leaves_cache_fields_none` for explicitness.

**Exit criteria:** new fields populate from SDK response shape; OpenAI adapter unchanged; all existing `tests/api_budget/test_llm_cost.py` cases pass; `tests/providers/test_completion.py` passes (it pins `cost_fn is openai_usage` / `is anthropic_usage` at lines 110, 177 — unchanged).

### Phase 3 — `estimate_cost_usd` math + `LLM_PRICES` config sanity

1. Rewrite `estimate_cost_usd` per §4.3.
2. Update `tests/api_budget/test_llm_cost.py:36-74` (`test_guard_writes_estimated_cost_from_llm_price_lookup`) — keep existing case (verifies legacy math, no cache) and add six new cases:
   - `test_estimate_cost_with_cache_write_at_125_percent`
   - `test_estimate_cost_with_cache_read_at_10_percent`
   - `test_estimate_cost_with_mixed_cache_buckets`
   - `test_estimate_cost_with_nonzero_plain_plus_cache_billed_separately` — **new per Codex R1**: verify `cost == plain_input × rate + cache_create × rate × 1.25 + cache_read × rate × 0.10` when all three buckets are non-zero. Catches the v1 subtraction bug, which would compute `(input − cache_create − cache_read) × rate` instead of `input × rate` for the plain-input term — undercounts by exactly `(cache_create + cache_read) × rate / 1M` (before the cache surcharges and any batch multiplier).
   - `test_estimate_cost_applies_50_percent_batch_discount`
   - `test_estimate_cost_falls_back_to_legacy_math_when_cache_fields_none` (the regression guard)
3. **No `LLM_PRICES` shape change** (per §4.4).

**Exit criteria:** new math passes new tests; legacy math passes legacy tests byte-identically (the regression case nails this).

### Phase 4 — Persistence wiring

1. Extend `get_cost_model_and_rate` per §4.6 (config side).
2. Extend `_compute_cost_for_log` per §4.7 (return tuple now 3-element; per-token branch added).
3. Update `_maybe_write_api_call_log` to accept + forward `token_telemetry`.
4. Update `_write_api_call_log` INSERT statement to include the five new columns.
5. Update both `_compute_cost_for_log` call sites in `guard.py`:
   - Fail-open / Redis-down `finally` (`guard.py:413-428` — line numbers verified Codex R1)
   - Success `finally` (`guard.py:521-533`)
   - Both unpack the new 3-tuple and pass `token_telemetry` to `_maybe_write_api_call_log`.
6. Update `tests/api_budget/test_guard.py` integration cases — verify `api_call_log` row payload includes token columns for LLM rows and excludes them (NULL) for non-LLM rows.

**Exit criteria:** Anthropic call writes a row with token decomposition; Plaid/SnapTrade/IBKR/Schwab/FMP rows write tokens as NULL; `cost_model='per_token'` shows up in admin queries; no regression in V4a's per-Item-month / per-Connected-User-month tests.

### Phase 5 — Backfill + observability

1. **No backfill.** Pre-V4e rows leave the new columns NULL (decision logged here, called out in commit message).
2. Update `app_platform/api_budget/cli.py` `today_cost_by_provider` query (line 40-47) — **no change required** (it sums `estimated_cost_usd`, which is now cache-aware automatically). Optionally add a sibling `today_tokens_by_provider` aggregation; flag as nice-to-have for the admin route follow-up, **not** part of V4e Phase 5 unless Codex disagrees.
3. Document in `docs/TODO.md` V4e row → SHIPPED with date + commit; cross-reference V2.P5 (stable-prefix prompt caching audit) — V4e is the prerequisite that makes V2.P5's savings measurable.

**Exit criteria:** TODO row updated; admin query unchanged but produces correct numbers; V2.P5 unblocked from the measurement side.

---

## 6. Test strategy

### New unit tests
- `tests/api_budget/test_llm_cost.py`:
  - 4 new `anthropic_usage` cases (cache fields, batch, none-fallback).
  - 1 new `openai_usage` case (cache fields stay None).
  - 6 new `estimate_cost_usd` cases (write, read, mixed, **non-zero-plain-plus-cache-separately** (Codex R1), batch, legacy regression).
- `tests/api_budget/test_guard.py`:
  - 1 new case: LLM row `_compute_cost_for_log` returns 3-tuple, telemetry persists.
  - 1 new case: non-LLM row `_compute_cost_for_log` returns 3-tuple with telemetry=None.
  - Update existing cases that currently unpack a 2-tuple.

### Schema verification
- Migration test (manual, since we don't have an automated migration runner):
  - `psql -c "\d api_call_log"` → 28 columns total (23 pre-V4e + 5 new).
  - `psql -c "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'api_call_log'::regclass AND conname = 'api_call_log_cost_model_check'"` → returns the four-value CHECK.

### Regression guards
- `tests/providers/test_completion.py::test_*_uses_<provider>_usage` (lines 110, 177) — `cost_fn is openai_usage` / `is anthropic_usage` must still hold; the function references are unchanged in V4e.
- All V4a tests (`tests/api_budget/test_guard.py` cases for `per_item_month` + `per_connected_user_month`) must pass without modification — V4e's only V4a-touching change is the 2-tuple → 3-tuple unpack and a `None` token_telemetry passthrough.

### Integration smoke (manual, post-Phase 4)
- Live Anthropic call via dev account: invoke any path that calls `providers.completion.AnthropicCompletionProvider.complete(...)`; verify `psql -c "SELECT input_tokens, output_tokens, cache_creation_tokens, cache_read_tokens, is_batch, cost_model FROM api_call_log WHERE provider='anthropic' ORDER BY ts DESC LIMIT 1"` returns populated tokens, `is_batch=false`, `cost_model='per_token'`. Cache fields will be 0 or NULL (today's call sites don't pass `cache_control`).
- Cross-check `estimated_cost_usd` matches a hand-calculated value for known input/output token counts at the locked claude-sonnet-4-6 rate ($3.00 in / $15.00 out per 1M).

---

## 7. Risk and mitigation

| Risk | Mitigation |
|---|---|
| Anthropic SDK changes `Usage` field names in a future release | `_safe_int(getattr(usage, "cache_creation_input_tokens", None))` — `getattr` with default + `_safe_int` returns None for missing fields → row writes NULL → no exception. Pin Anthropic SDK version in `pyproject.toml` separately. |
| `usage.input_tokens` semantics shift to include cached tokens (double-count risk) | **Resolved Codex R1**: `Usage.input_tokens` is the NET/plain bucket. Math uses `plain_input = usage.input_tokens` directly (no subtraction). New test `test_estimate_cost_with_nonzero_plain_plus_cache_billed_separately` locks the math (Phase 3 step 2). |
| `is_batch` heuristic via `service_tier == "batch"` is wrong | Verify against SDK type literal: `Literal['standard', 'priority', 'batch']`. Confirmed introspection 2026-04-26. If a future fourth value (e.g. `"batch_priority"`) arises, the equality check returns False (cost over-attributes 50% — rate is 2× actual). Acceptable conservative posture; the alternative (substring match) over-attributes the other way. |
| V4a's `_compute_cost_for_log` 2-tuple vs V4e's 3-tuple breaks live during deploy | Phase 4 lands the tuple change + both call-site updates atomically; no in-between state. Tests pin the 3-tuple shape. |
| Migration ordering matters (V4a P1 before V4e) | V4a P1 already shipped (commit `d3f4e3bb`); V4a is a hard prerequisite (Codex R1). If V4e ran before V4a P1 the CHECK addition would fail because `cost_model` doesn't exist. See §4.5 for the full ordering contract. |
| OpenAI adapter accidentally writes `is_batch=False` (vs NULL) for OpenAI rows | `LLMUsage.is_batch: Optional[bool] = None` default — `openai_usage` doesn't set it → stays `None` → DB row gets NULL. Test `test_openai_usage_leaves_cache_fields_none` pins this. |
| Cost regression from a typo in the multipliers (1.25, 0.10, 0.50) | Five dedicated test cases at known input/output token values; explicit Decimal multiplier constants in code so a code reviewer can grep them once. |
| `cost_model` enum drift between code (Literal) and DB (CHECK constraint) | Mirror constants via a single source — keep the literal in `config/api_budget_costs.py` `get_cost_model_and_rate` signature; CHECK constraint values match in commit message. Codex Q4 below: should we add a runtime assertion in tests? |

---

## 8. Decisions (resolved in Codex R1)

**Q1 → RESOLVED.** Anthropic SDK contract: `Usage.input_tokens` is the **NET/plain bucket**. Total input = `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`. Verified via SDK type definitions in `anthropic.types.message` (Codex R1, anthropic==0.93.0). The §4.3 math uses `plain_input = usage.input_tokens` directly — does NOT subtract cache buckets (subtracting would undercount cached requests by removing tokens that were never in the input_tokens count).

**Q2 → RESOLVED with caveat.** `service_tier == "batch"` is correct for the Anthropic `Message.usage` field. **Caveat**: the Batch API wraps responses as `MessageBatchIndividualResponse → result → MessageBatchSucceededResult → message`. Current code at `providers/completion.py:409` only calls `client.messages.create` (synchronous, non-batch), so `is_batch` will stay `False`/`None` for all current call sites. When a future batch caller is added, the adapter only sees the right `service_tier` if the caller passes the **inner** `.message` to `cost_fn` — not the batch wrapper. This is informational-only today; a comment in the adapter docstring captures the future-caller contract.

**Q3 → RESOLVED.** Skip `total_tokens`. Derive in SQL when needed.

**Q4 → RESOLVED.** Keep `_LLM_PROVIDERS` duplicated (or move to config). Do NOT import `guard` from `config` — that would invert the layering. V4e §4.6's `_LLM_PROVIDERS_LOCAL` two-line literal is acceptable.

**Q5 → RESOLVED.** Option A (extend tuple to 3-element). If tuple churn starts spreading beyond `_compute_cost_for_log`, switch to a small `TypedDict`/dataclass. Not warranted yet.

**Q6 → RESOLVED.** `BOOLEAN NULL` for `is_batch`. Stays consistent with the four other nullable LLM-only columns.

**Q7 → RESOLVED.** Defer `today_tokens_by_provider` aggregation. V4e ships the schema + math; CLI/dashboard surfacing rides as a follow-up.

---

## 9. Rollout checkpoints

Single PR, all 5 phases. Reviewer checkpoints (mirroring V4a + IBKR-spec plan rhythm):

1. **After Phase 1:** `\d api_call_log` shows 28 columns + four-value CHECK; idempotent re-run produces zero diff.
2. **After Phase 2:** `tests/api_budget/test_llm_cost.py` passes; new `anthropic_usage` cases populate cache + batch fields; `openai_usage` cases leave them None.
3. **After Phase 3:** `tests/api_budget/test_llm_cost.py::test_estimate_cost_*` passes, including the legacy regression case (no cache → byte-identical to today's math).
4. **After Phase 4:** live Anthropic smoke against dev account writes a row with `cost_model='per_token'`, populated tokens, NULL cache fields (today's caller doesn't use cache); Plaid + SnapTrade smoke writes a row with NULL token columns; existing V4a per-Item / per-Connected-User tests still pass.
5. **PR-close:** TODO row flipped to SHIPPED; commit message documents the no-backfill decision and the V4a→V4e migration ordering invariant.

---

## 10. Size estimate

| Phase | Files touched | LoC net | Notes |
|---|---|---|---|
| 1 — Migration | 1 (new SQL file) | ~30 | Pure DDL; no Python changes |
| 2 — `LLMUsage` schema + adapters | 2 (`llm_cost.py` + `test_llm_cost.py`) | +35 / –4 | Three new fields + adapter populate + 4 new test cases |
| 3 — `estimate_cost_usd` math | 2 (`llm_cost.py` + `test_llm_cost.py`) | +30 / –10 | Math rewrite + 6 new tests; `LLM_PRICES` unchanged |
| 4 — Persistence wiring | 4 (`api_budget_costs.py` + `guard.py` + `test_guard.py` + INSERT site) | +60 / –10 | `get_cost_model_and_rate` enum extension + `_compute_cost_for_log` tuple + INSERT columns + 2 new tests |
| 5 — TODO + admin (optional) | 1 (`docs/TODO.md`) | +5 | TODO row update; CLI aggregation deferred per Q7 |
| **Total** | **8 files** | **~130 net LoC** | ~3–5 hour implementation; 1–2 Codex review rounds expected |

The work is small because every change is additive: no rename, no deletion, no caller migration, no boundary refactor. The challenge is correctness on the cache-rate math (Phase 3) and the tuple-shape coordination across V4a's existing call sites (Phase 4).

---
