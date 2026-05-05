# API Budget Subscription-Dimension Plan (V4a)

**Status:** **SHIPPED 2026-04-26** — v7 plan preserved for historical reference.
**Parent doc:** `docs/planning/API_BUDGET_GUARD_PLAN.md`
**Blocks:** V4 (`API_BUDGET_DRY_RUN=false` flip) until V4a lands.
**Date:** 2026-04-25

**v7 changes from v6 (V4c R2 + V4c-tail SHIPPED reality fold-in):** Parallel session committed `5f61dd5b` (2026-04-25 15:09) which verified SnapTrade contracted rates from `dashboard.snaptrade.com`. Three corrections:
1. **Connected User rate $2.00 → $1.50/user/month** — contracted dashboard rate (key `HENRY-CHIEN-LLC-RTXYG`), lower than public $2.00 list. Updated `SNAPTRADE_PER_CONNECTED_USER_MONTH_RATE` in §4.
2. **Manual Refresh $0.05/call** verified — added `("snaptrade", "connections.refresh_brokerage_authorization"): Decimal("0.0500")` to `COST_PER_CALL` (was a TBD comment in v6).
3. **NEW per-call axis: Recent Orders $0.002/call** — `accounts.orders` is metered as a separate per-call dimension, NOT bundled into the Connected User subscription. Moved `"accounts.orders"` OUT of `SNAPTRADE_SUBSCRIPTION_OPS` (now 16 ops, not 17) and ADDED `("snaptrade", "accounts.orders"): Decimal("0.0020")` to `COST_PER_CALL`. Updated all "17 subscription ops" references to "16 subscription ops" + "2 per-call exceptions". Exact-equality validation test now expects 16-op set (live ops minus `connections.refresh_brokerage_authorization` minus `accounts.orders`).

V4c R2 also surfaced the test app `HENRY-CHIEN-LLC-TEST-GCXHL` is FREE and a 3% processing fee per invoice exists — both informational, no schema impact.

**v6 changes from v5 (Codex round-5 FAIL fixes):** Updated D4 to match v5 reality (SnapTrade `guard_call` signature unchanged but production callsites — `adapter.py`, `routes/snaptrade.py`, scripts — need wiring; v5 D4 still claimed "no new wrapper params" which contradicted §6/P3). Replaced the broken `rg --multiline` + line-grep sweep with AST-based Python detection that walks every `guard_call(...)` invocation individually and reports the per-call file:line for any SnapTrade callsite missing `budget_user_id`. Added a parallel AST sweep on public SnapTrade boundary functions (`register_snaptrade_user`, `delete_snaptrade_user`, etc.) for upstream callers. Old `xargs rg -L` file-level sweep dropped (false-negatives on mixed files). Acknowledged Codex round-5 LoC question — P3 likely closer to ~500-700 LoC than v5's ~350 estimate; updated the §9 P3 row.

**v5 changes from v4 (Codex round-4 FAIL fixes):** Corrected `SNAPTRADE_SUBSCRIPTION_OPS` to use the actual `guard_call(operation=...)` strings from `brokerage/snaptrade/client.py` (v4 used wrapper-name abbreviations — `symbol_search_user_account` → `reference_data.symbol_search_user_account`, `order_impact` → `trading.get_order_impact`, `place_order` → `trading.place_order`, `get_user_account_orders` → `accounts.orders`, `cancel_order` → `trading.cancel_order`, `get_activities` → `transactions_and_reporting.get_activities`). Withdrew the "no production wiring needed for SnapTrade" claim — `brokerage/snaptrade/adapter.py` (lines 253, 259, 324, 330), `routes/snaptrade.py` (lines 594, 1323 — register/delete user lifecycle), `scripts/run_snaptrade.py` (39, 121), `scripts/snaptrade_sdk_smoke.py` (40, 53), and `scripts/explore_transactions.py` ALL call SnapTrade subscription ops without `budget_user_id`. P3 explicitly wires these — LoC bumped from ~220 to ~350. Sweep commands rewritten for multiline matches (the v4 single-line regex would have missed actual code). Added config-validation test asserting **exact equality** between `SNAPTRADE_SUBSCRIPTION_OPS` and the live op names in `brokerage/snaptrade/client.py` (would have caught the v4 op-name bug). V4c-tail (Manual Sync rate) explicitly noted as a prerequisite for V4 unblock — V4a alone leaves Manual Sync at $0 in the rollup.

**v4 changes from v3:** Plan now covers SnapTrade alongside Plaid (V4c "FOLDS INTO V4a" finding — same structural mismatch, parallel dimension). New `cost_model` enum value `'per_connected_user_month'` for SnapTrade's $2.00/Connected User/month billing across all 17 subscription ops (Manual Sync stays per-call, V4c-tail config-only). Second charges table `api_connected_user_subscription_charges` keyed on `(provider, user_id, billing_month)` — no operation breakdown because SnapTrade bundles all subscription ops into one Connected User charge. Deleted phantom SnapTrade per-call entries (`accounts.list` $0.05, `accounts.positions` $0.05) — both wrong per V4c.

**v3 changes from v2:** Dropped `database/schema.sql` append (verified — `schema.sql` doesn't track `api_call_log` today; V4a follows V1's migration-only convention); fixed `_compute_cost_for_log` signature to take `provider_key`/`operation_key` as explicit kwargs (v2 used them as free variables); added explicit signature notes for `_maybe_write_api_call_log` and `_write_api_call_log` (additive new kwargs + INSERT columns); moved DB-failure test from `test_subscription_charges.py` (helper raises by design) to `test_guard.py` (where the catch-and-fallback lives); P2 row in §9 now honest — "operationally safe, telemetry inaccurate" with explicit warning not to size V4 thresholds from P2-only data.

**v2 changes from v1:** Merged P2+P3 (P2 alone produced a $0 cost gap for holdings); preflight `item_id` check moved before `fn()` invocation (prevents un-attributable Plaid calls); fault-tolerant DB-failure handling (helper raises by design; `_compute_cost_for_log` catches and over-attributes `monthly_rate` — a DB blip no longer surfaces as an app exception); blocked-decision branch at `guard.py:354-371` plumbed for `item_id`+`cost_model`; dropped `routes/provider_routing.py` from callsite list (it's a `NotImplementedError` fallback); diagnostic scripts (`scripts/diagnose_plaid_balances.py`, `scripts/explore_transactions.py`) added to P3 wiring (would otherwise hard-error after enforcement); tightened `pg_constraint` guard to filter by `conrelid`; existing test-fixture updates added to P3 scope; accepted-estimate language added for Plaid TZ + Item lifecycle edge cases (mid-month removal, re-link, sandbox/dev/prod env separation).

---

## 1. Context

Two providers bill us as subscriptions, but our cost guard treats every call as per-call. Both produce structurally wrong dollar rollups in `today_cost_by_provider` (admin tile + `/api/admin/api-budget`).

### Plaid (verified 2026-04-25 from `dashboard.plaid.com/settings/team/billing` Master Agreement)

**Per-Item-per-month subscription** for 4 of 6 product paths:

| Product / Operation | Model | Rate |
|---|---|---|
| `accounts_balance_get` | per-call | $0.10/call |
| `investments_refresh` | per-call | $0.12/call |
| `investments_holdings_get` | **subscription** | $0.18/Item/month |
| `investments_transactions_get` | **subscription** | $0.35/Item/month |
| `transactions_get` / `transactions_sync` | **subscription** | $0.30/Item/month |
| `liabilities_get` | **subscription** | $0.20/Item/month |

`config/api_budget_costs.py` also has wrong values: Balance $0.30 (should be $0.10), `accounts_get` and `item_get` listed at $0.15 (Plaid lists both free).

### SnapTrade (verified 2026-04-25 from `snaptrade.com/pricing` + `snaptrade.com/developer-terms-of-use`, V4c finding)

**Subscription + per-call hybrid** (V4c R2 verified from `dashboard.snaptrade.com/settings/billing`, 2026-04-25):
- **Connected User subscription: $1.50/user/month** (contracted rate; public list is $2.00) — covers **16 of 18 wrapped ops** in `brokerage/snaptrade/client.py`. One $1.50 charge per user per month, regardless of how many brokerages they connect.
- **Manual Refresh: $0.05/call** — `connections.refresh_brokerage_authorization` is metered separately per call.
- **Recent Orders: $0.002/call** — `accounts.orders` is a separate per-call axis, NOT bundled into the subscription.

`config/api_budget_costs.py` currently has only `accounts.list` $0.05 and `accounts.positions` $0.05 — both wrong per V4c (should be deleted, replaced with the 3-axis schema). 16 of 18 wrapped ops are missing from config entirely.

### What changes

For 4 of 6 Plaid paths and 16 of 18 SnapTrade ops (the subscription-bundled ones), today's per-call rollup is wrong by 4-30x. V4 (flipping `API_BUDGET_DRY_RUN=false`) is blocked until both rollups become accurate.

**Forensics on the original $343 March 2026 incident:** ~3,435 Balance calls × $0.10 (per-call held). Subsequent fix dropped daily Balance calls to 0. Subscription billing was not implicated in that incident, but accurate accounting matters for the V4 dry-run flip.

**Outcome:** API budget guard correctly accounts for both cost models. `today_cost_by_provider` reports accurate daily $ totals. V4 (dry-run flip) becomes unblocked.

---

## 2. Locked architectural decisions

| ID | Decision |
|---|---|
| **D1** | **First-call-of-month charges full subscription.** First call to a (Plaid item, op, month) or a (SnapTrade user, month) writes the full subscription rate to `api_call_log.estimated_cost_usd`; subsequent calls in the same month write `$0`. Existing `SUM(estimated_cost_usd)` rollup in `routes/admin_api_budget.py:46-56` continues unchanged. |
| **D2** | **DB-only dedup, two charges tables (one per billing dimension).** `api_item_subscription_charges` keyed on `(provider, operation, item_id, billing_month)` for Plaid (per-Item-per-op-per-month). `api_connected_user_subscription_charges` keyed on `(provider, user_id, billing_month)` for SnapTrade (per-user-per-month, no operation breakdown — one $1.50 charge covers all 16 subscription ops for that user that month). INSERT...ON CONFLICT DO NOTHING RETURNING is atomic in both cases. No Redis fast-path. |
| **D3** | **Add `item_id` (TEXT, nullable) + `cost_model` (TEXT, 'per_call'\|'per_item_month'\|'per_connected_user_month') to `api_call_log`** for forensics. Both nullable — pre-V4a rows stay NULL. SnapTrade rows leave `item_id` NULL and use the existing `api_call_log.user_id` column as the Connected User identifier (it's already populated). |
| **D4** | **Subject identifiers flow as explicit params; no derivation inside `guard_call`.** Plaid: `item_id` is added to `guard_call`'s signature and threaded through Plaid wrappers from `get_plaid_token()` (token payload includes it — `brokerage/plaid/secrets.py:34-38`). SnapTrade: the existing `budget_user_id` param IS the Connected User identifier — `guard_call`'s signature doesn't change for SnapTrade, but production callsites that don't currently pass `budget_user_id` MUST be wired in P3 (`brokerage/snaptrade/adapter.py`, `routes/snaptrade.py`, scripts — see §6). NO derivation inside `guard_call` — both subject identifiers are explicit at every callsite by design. |
| **D5** | **Bundle wrong-cost-value fixes into V4a.** Single PR replaces config schema and ships correct values together for both providers (Plaid Balance $0.30 → $0.10, drop phantom `accounts_get`/`item_get`; SnapTrade `accounts.list`/`accounts.positions` $0.05 deleted; new SnapTrade subscription set + rate added). V4 stays narrow (threshold tuning + dry-run flip). |
| **D6** | **SnapTrade has 3 billing axes — subscription + 2 per-call carve-outs (V4c R2 verified).** (a) Subscription: $1.50/Connected User/month covers 16 of 18 wrapped ops. (b) Manual Refresh: `connections.refresh_brokerage_authorization` is metered per-call at $0.05. (c) Recent Orders: `accounts.orders` is metered per-call at $0.002 (separate axis, NOT bundled). All three fit within V4a's existing schema — subscription axis uses `SUBSCRIPTION_COSTS_PER_CONNECTED_USER_MONTH`-style routing, both per-call axes go in `COST_PER_CALL`. No schema additions beyond what v6 already specifies. |

---

## 3. Schema (Phase 1)

### Migration: `database/migrations/20260427_api_budget_subscription_dimension.sql`

```sql
-- ========== Plaid: per-Item-per-op-per-month dedup ==========
CREATE TABLE IF NOT EXISTS api_item_subscription_charges (
  id              BIGSERIAL PRIMARY KEY,
  provider        TEXT NOT NULL,
  operation       TEXT NOT NULL,
  item_id         TEXT NOT NULL,
  billing_month   DATE NOT NULL,
  charged_amount  NUMERIC(12,4) NOT NULL,
  charged_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT api_item_subscription_charges_billing_month_first_of_month
    CHECK (EXTRACT(DAY FROM billing_month) = 1)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_api_item_subscription_charges_dedup
  ON api_item_subscription_charges (provider, operation, item_id, billing_month);

CREATE INDEX IF NOT EXISTS ix_api_item_subscription_charges_billing_month
  ON api_item_subscription_charges (billing_month DESC);

CREATE INDEX IF NOT EXISTS ix_api_item_subscription_charges_item
  ON api_item_subscription_charges (provider, item_id, billing_month DESC);

-- ========== SnapTrade: per-Connected-User-per-month dedup ==========
-- One row per (provider, user_id, billing_month). No operation column —
-- SnapTrade's $1.50/Connected User/month bundles 16 of 18 ops together
-- (Manual Refresh + Recent Orders are per-call carve-outs in COST_PER_CALL).
CREATE TABLE IF NOT EXISTS api_connected_user_subscription_charges (
  id              BIGSERIAL PRIMARY KEY,
  provider        TEXT NOT NULL,
  user_id         INT NOT NULL,         -- our internal user_id (matches api_call_log.user_id)
  billing_month   DATE NOT NULL,
  charged_amount  NUMERIC(12,4) NOT NULL,
  charged_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT api_connected_user_subscription_charges_billing_month_first_of_month
    CHECK (EXTRACT(DAY FROM billing_month) = 1)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_api_connected_user_subscription_charges_dedup
  ON api_connected_user_subscription_charges (provider, user_id, billing_month);

CREATE INDEX IF NOT EXISTS ix_api_connected_user_subscription_charges_billing_month
  ON api_connected_user_subscription_charges (billing_month DESC);

CREATE INDEX IF NOT EXISTS ix_api_connected_user_subscription_charges_user
  ON api_connected_user_subscription_charges (provider, user_id, billing_month DESC);

-- ========== api_call_log forensics columns ==========
ALTER TABLE api_call_log
  ADD COLUMN IF NOT EXISTS item_id    TEXT NULL,
  ADD COLUMN IF NOT EXISTS cost_model TEXT NULL;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname  = 'api_call_log_cost_model_check'
      AND conrelid = 'api_call_log'::regclass    -- avoid name collision across tables
  ) THEN
    ALTER TABLE api_call_log
      ADD CONSTRAINT api_call_log_cost_model_check
      CHECK (cost_model IS NULL OR cost_model IN ('per_call', 'per_item_month', 'per_connected_user_month'));
  END IF;
END $$;
```

### Notes

- **`charged_amount NUMERIC(12,4)`** matches `api_call_log.estimated_cost_usd` precision (existing `database/migrations/20260426_api_budget.sql:34`) for both tables.
- **`api_connected_user_subscription_charges.user_id INT`** matches `api_call_log.user_id` type (existing schema, `INT NULL` at line 29 of the V1 migration). For SnapTrade, dedup is keyed on our internal `budget_user_id`, which is the same value persisted to `api_call_log.user_id`.
- **No `operation` column in the SnapTrade table** — V4c R2 confirmed the 16 SnapTrade subscription ops bundle into one $1.50/Connected User/month charge. First call from any of the 16 ops triggers the row; subsequent calls (whether same op or different) hit the conflict and write $0. The two per-call carve-outs (`connections.refresh_brokerage_authorization` and `accounts.orders`) bypass this table entirely — they go through the per-call branch.
- **CHECK on `billing_month`** enforces first-of-month at the DB layer in both tables — defense against direct-INSERT bugs in helper code.
- **Migration prefix `20260427`** sorts after the existing `20260426_api_budget.sql` (the ALTER targets `api_call_log` from that migration). Real-world date is 2026-04-25; the team uses lexicographic-ordering prefix dates rather than calendar dates (verified by reading existing migration files).
- **`api_call_log` ALTER:** both new columns nullable; old rows stay NULL (no backfill). Sub-second AccessExclusiveLock on a weeks-old table; rolling-restart safe.
- **No indexes on `item_id` or `cost_model` in `api_call_log`** — neither participates in hot-path queries today. Add `CREATE INDEX CONCURRENTLY` post-deploy if needed.

**Schema-file convention:** V4a is migration-only. `database/schema.sql` does NOT currently track `api_call_log` or `api_call_counters` (verified — the V1 `20260426_api_budget.sql` migration also did not update `schema.sql`). V4a follows the same convention: ship the migration, leave `schema.sql` alone. Anyone running fresh init must run all migrations in order — that's already the team's convention.

---

## 4. Config schema (Phase 2)

### Helper signature

```python
def get_cost_model_and_rate(
    provider: str, operation: str,
) -> tuple[Literal["per_call", "per_item_month", "per_connected_user_month"], Decimal]:
    """Lookup precedence:
    1. SUBSCRIPTION_COSTS_PER_ITEM_MONTH (Plaid)               → ('per_item_month', rate)
    2. SnapTrade subscription op set                           → ('per_connected_user_month', $1.50)
    3. COST_PER_CALL                                            → ('per_call', rate)
    4. None of the above                                       → ('per_call', Decimal('0'))

    Note: SnapTrade per-call carve-outs (Manual Refresh, Recent Orders) are in
    COST_PER_CALL and resolve via path 3, not path 2.
    """
```

### Full new content of `config/api_budget_costs.py`

```python
"""Project-specific starter costs for the API budget guard.

Units:
- COST_PER_CALL: USD per outbound call.
- SUBSCRIPTION_COSTS_PER_ITEM_MONTH: USD per (Item, calendar month).
  Applies to Plaid: "first call of the month charges the full subscription,
  subsequent calls charge $0."
- SNAPTRADE_SUBSCRIPTION_OPS + SNAPTRADE_PER_CONNECTED_USER_MONTH_RATE:
  SnapTrade bills $1.50/Connected User/month covering 16 of 18 subscription ops
  (V4c R2 verified contracted rate from dashboard.snaptrade.com, 2026-04-25).
  Two per-call carve-outs in COST_PER_CALL above:
    • connections.refresh_brokerage_authorization (Manual Refresh): $0.05/call
    • accounts.orders (Recent Orders): $0.002/call
- LLM_PRICES: USD per 1 million input/output tokens.

Subject identifier conventions at guard_call site:
- Plaid subscription ops MUST receive an item_id.
- SnapTrade subscription ops MUST have a non-None budget_user_id (the
  existing guard_call kwarg). Several production callsites currently
  do NOT pass it — they're wired in P3 (see plan §6).
See app_platform/api_budget/guard.py.

Plaid pricing source: Master Agreement on dashboard.plaid.com (verified 2026-04-25).
SnapTrade pricing source: snaptrade.com/pricing + developer-terms-of-use (V4c, 2026-04-25).
"""

from __future__ import annotations
from decimal import Decimal
from typing import Literal


COST_PER_CALL: dict[tuple[str, str], Decimal] = {
    # Plaid per-call
    ("plaid", "accounts_balance_get"): Decimal("0.1000"),  # was 0.3000 — D5
    ("plaid", "investments_refresh"):  Decimal("0.1200"),  # new
    # REMOVED ("plaid", "accounts_get") — Plaid lists free (D5)
    # REMOVED ("plaid", "item_get")     — Plaid lists free (D5)

    # SnapTrade per-call (V4c R2 verified 2026-04-25 from dashboard.snaptrade.com)
    ("snaptrade", "connections.refresh_brokerage_authorization"): Decimal("0.0500"),  # Manual Refresh
    ("snaptrade", "accounts.orders"):                              Decimal("0.0020"),  # Recent Orders (separate per-call axis)
    # REMOVED ("snaptrade", "accounts.list")      — wrong; subscription-billed (D5/V4c)
    # REMOVED ("snaptrade", "accounts.positions") — wrong; subscription-billed (D5/V4c)

    # Schwab per-call (V4d corrected to $0.00 — Trader API is rate-limit-only, free for account holders)
    ("schwab", "get_account"):  Decimal("0.0000"),
    ("schwab", "get_accounts"): Decimal("0.0000"),

    # IBKR per-call (V4d corrected to $0.00 — data API rate-limit-only; cost is market-data subscriptions)
    ("ibkr", "reqPositions"):      Decimal("0.0000"),
    ("ibkr", "reqAccountSummary"): Decimal("0.0000"),

    # FMP (flat-subscription; per-call cost $0)
    ("fmp", "fetch"):           Decimal("0.0000"),
    ("fmp_estimates", "get"):   Decimal("0.0000"),
}


SUBSCRIPTION_COSTS_PER_ITEM_MONTH: dict[tuple[str, str], Decimal] = {
    ("plaid", "investments_holdings_get"):     Decimal("0.1800"),
    ("plaid", "investments_transactions_get"): Decimal("0.3500"),
    ("plaid", "transactions_get"):             Decimal("0.3000"),  # defensive
    ("plaid", "liabilities_get"):              Decimal("0.2000"),  # defensive
}


# SnapTrade Connected-User-per-month subscription: $1.50 covers 16 of 18 wrapped ops
# (V4c R2 verified 2026-04-25 from dashboard.snaptrade.com, key HENRY-CHIEN-LLC-RTXYG).
# Two per-call carve-outs (in COST_PER_CALL above):
#   - `connections.refresh_brokerage_authorization` (Manual Refresh, $0.05/call)
#   - `accounts.orders` (Recent Orders, $0.002/call — separate per-call axis)
SNAPTRADE_PER_CONNECTED_USER_MONTH_RATE: Decimal = Decimal("1.5000")

SNAPTRADE_SUBSCRIPTION_OPS: frozenset[str] = frozenset({
    # Names are taken verbatim from the guard_call(operation="...") strings in
    # brokerage/snaptrade/client.py. The two per-call carve-outs above (Manual
    # Refresh, Recent Orders) intentionally do NOT appear here.
    "authentication.register_snap_trade_user",
    "authentication.login_snap_trade_user",
    "authentication.delete_snap_trade_user",
    "authentication.reset_snap_trade_user_secret",
    "accounts.list",
    "accounts.positions",
    "accounts.balance",
    "accounts.activities",
    "connections.list_brokerage_authorizations",
    "connections.detail_brokerage_authorization",
    "connections.remove_brokerage_authorization",
    "reference_data.symbol_search_user_account",
    "trading.get_order_impact",
    "trading.place_order",
    "trading.cancel_order",
    "transactions_and_reporting.get_activities",
})


def get_cost_model_and_rate(
    provider: str, operation: str,
) -> tuple[Literal["per_call", "per_item_month", "per_connected_user_month"], Decimal]:
    provider_key = str(provider or "").strip().lower()
    operation_key = str(operation or "").strip()
    key = (provider_key, operation_key)

    plaid_sub_rate = SUBSCRIPTION_COSTS_PER_ITEM_MONTH.get(key)
    if plaid_sub_rate is not None:
        return ("per_item_month", plaid_sub_rate)

    if provider_key == "snaptrade" and operation_key in SNAPTRADE_SUBSCRIPTION_OPS:
        return ("per_connected_user_month", SNAPTRADE_PER_CONNECTED_USER_MONTH_RATE)

    return ("per_call", COST_PER_CALL.get(key, Decimal("0")))


LLM_PRICES: dict[str, dict[str, float]] = {  # unchanged from current file (V4d-corrected rates)
    "gpt-4.1":          {"input_per_1m_tokens": 2.50, "output_per_1m_tokens": 10.00},
    "gpt-4.1-mini":     {"input_per_1m_tokens": 0.50, "output_per_1m_tokens":  2.00},
    "gpt-4o-mini":      {"input_per_1m_tokens": 0.20, "output_per_1m_tokens":  0.80},
    "claude-sonnet-4-6":{"input_per_1m_tokens": 3.00, "output_per_1m_tokens": 15.00},
    "claude-haiku-4-5": {"input_per_1m_tokens": 1.00, "output_per_1m_tokens":  5.00},
}


__all__ = [
    "COST_PER_CALL",
    "SUBSCRIPTION_COSTS_PER_ITEM_MONTH",
    "SNAPTRADE_SUBSCRIPTION_OPS",
    "SNAPTRADE_PER_CONNECTED_USER_MONTH_RATE",
    "LLM_PRICES",
    "get_cost_model_and_rate",
]
```

### Validation (in `tests/api_budget/test_costs_config.py`)

```python
# 1. Plaid subscription dict and per-call dict must not overlap.
overlap = set(COST_PER_CALL) & set(SUBSCRIPTION_COSTS_PER_ITEM_MONTH)
assert not overlap, f"keys must not overlap: {overlap}"

# 2. SnapTrade subscription ops must not appear in COST_PER_CALL (would shadow the subscription rate).
for op in SNAPTRADE_SUBSCRIPTION_OPS:
    assert ("snaptrade", op) not in COST_PER_CALL, (
        f"snaptrade op {op} is in both subscription set and COST_PER_CALL"
    )

# 3. Both per-call carve-outs MUST NOT be in the subscription set (V4c R2).
SNAPTRADE_PER_CALL_CARVEOUTS = {
    "connections.refresh_brokerage_authorization",  # Manual Refresh
    "accounts.orders",                              # Recent Orders
}
for op in SNAPTRADE_PER_CALL_CARVEOUTS:
    assert op not in SNAPTRADE_SUBSCRIPTION_OPS, f"{op} must be per-call, not subscription"
    assert ("snaptrade", op) in COST_PER_CALL, f"{op} must have a COST_PER_CALL entry"

# 4. CRITICAL — exact equality with live guard_call(operation=...) strings in
# brokerage/snaptrade/client.py. Catches the round-4 bug where the set used
# wrapper-name abbreviations (e.g., "place_order") instead of the actual
# guard_call key (e.g., "trading.place_order"), which would silently fall
# through to per-call $0 instead of subscription billing.
import re
from pathlib import Path

CLIENT_PATH = Path(__file__).parent.parent.parent / "brokerage" / "snaptrade" / "client.py"
src = CLIENT_PATH.read_text()
live_ops = set(re.findall(r'operation="([^"]+)"', src))
expected_subscription_ops = live_ops - SNAPTRADE_PER_CALL_CARVEOUTS

assert expected_subscription_ops == SNAPTRADE_SUBSCRIPTION_OPS, (
    f"SNAPTRADE_SUBSCRIPTION_OPS drift vs brokerage/snaptrade/client.py:\n"
    f"  missing in set: {expected_subscription_ops - SNAPTRADE_SUBSCRIPTION_OPS}\n"
    f"  extra in set:   {SNAPTRADE_SUBSCRIPTION_OPS - expected_subscription_ops}"
)
```

---

## 5. `guard_call` signature + branching (Phase 2 + flip in Phase 3)

### New signature (one new keyword-only parameter)

```python
def guard_call(*, provider, operation, fn, args=(), kwargs=None,
               budget_user_id=None, account_id=None, caller=None,
               cost_fn=None, cost_per_call=None,
               item_id: str | None = None) -> Any:   # NEW
```

Backwards compatible: existing callers that don't pass `item_id` get `None`. Subscription ops require non-empty `item_id` (Phase 3 hard-error; Phase 2 WARN-fallback).

### Three insertion points in `app_platform/api_budget/guard.py`

V1 missed the third `_maybe_write_api_call_log` site. All three need plumbing:

| Site | Lines | Decision | What changes |
|---|---|---|---|
| Preflight (NEW, top of `guard_call`) | inserted ~`:271` | n/a | Hard-error when `cost_model == 'per_item_month'` and `item_id` missing/empty (Phase 3 only — Phase 2 is WARN-fallback). Runs **before** `fn()` and before the Redis counter increment, so an un-attributable Plaid call never happens. |
| Fail-open / Redis-down `finally` | `:301-318` | "error" | Replace `_estimate_cost(...)` with cost-model branch; pass `item_id` + `cost_model` to `_maybe_write_api_call_log`. |
| Live blocked branch | `:354-371` | "blocked" | Plumb `item_id` + `cost_model` to `_maybe_write_api_call_log` (cost stays `None` because the call was blocked — no monthly_rate charge incurred). |
| Success `finally` | `:387-411` | "ok" / "warned" | Replace `_estimate_cost(...)` with cost-model branch; pass `item_id` + `cost_model` to `_maybe_write_api_call_log`. |

Update `_write_api_call_log` (`guard.py:97-161`) to INSERT the two new columns.

### Preflight check (NEW — runs before `fn()` in all paths)

Both subscription cost models require a subject identifier before we touch the vendor. The check is symmetric: missing identifier = WARN-fallback in P2, hard `ValueError` in P3.

```python
def guard_call(*, provider, operation, ..., budget_user_id=None, ..., item_id=None):
    config = get_budget_config()
    if not config.enabled:
        return fn(*args, **(kwargs or {}))

    provider_key = str(provider or "").strip().lower()
    operation_key = str(operation or "").strip()
    cost_model, rate = get_cost_model_and_rate(provider_key, operation_key)

    item_key = str(item_id or "").strip() or None

    # PREFLIGHT: subscription ops require their subject identifier BEFORE we touch
    # the vendor. Plaid: item_id. SnapTrade: budget_user_id.
    missing_subject = (
        (cost_model == "per_item_month" and item_key is None)
        or (cost_model == "per_connected_user_month" and budget_user_id is None)
    )
    if missing_subject:
        subject_kind = "item_id" if cost_model == "per_item_month" else "budget_user_id"
        if _PHASE_3_ENFORCED:
            raise ValueError(
                f"guard_call: subscription op {provider_key}/{operation_key} "
                f"requires {subject_kind} (preflight)"
            )
        # Phase 2: log WARN (one-time per (provider, op) via dedup) and fall
        # through. Cost is over-attributed to the full subscription rate at
        # write time below (status quo behavior — no worse than today).
        portfolio_logger.warning(
            "guard_call subscription op without %s provider=%s op=%s "
            "(falling back to full rate; Phase 3 will hard-error preflight)",
            subject_kind, provider_key, operation_key,
        )

    # ... existing counter increment, branching, fn() invocation ...
```

Note the rename: `_PHASE_4_ENFORCED` (v1) → `_PHASE_3_ENFORCED` (v2) because phases were renumbered after merging old P2+P3 (see §9).

### Cost computation at log-write sites (replaces `_estimate_cost(...)` at `:292-300` and `:389-393`)

Module-level helper in `app_platform/api_budget/guard.py`. Takes everything as explicit kwargs — no closure over `guard_call` locals. Codex round-2 flagged the v2 draft for using `provider_key`/`operation_key` as free variables; this signature fixes that.

```python
def _compute_cost_for_log(
    *,
    provider_key: str,
    operation_key: str,
    cost_model: Literal["per_call", "per_item_month", "per_connected_user_month"],
    rate: Decimal,
    item_key: str | None,
    budget_user_id: int | None,
    result: Any,
    cost_fn: Callable[[Any], Any] | None,
    cost_per_call: Decimal | float | int | str | None,
    billing_month: date,
) -> tuple[Decimal | None, str]:
    """Returns (estimated_cost, effective_cost_model) for the api_call_log row.

    Fault-tolerant: any DB failure inside a subscription branch degrades to
    over-attributing the full subscription rate (status-quo behavior) and logs
    a warning — a transient DB blip never turns a successful vendor call into
    an app exception.
    """
    if result is None:
        return (None, cost_model)

    if cost_model == "per_item_month":
        if item_key is None:
            # Preflight WARN-fallback (Phase 2). Over-attribute.
            return (_round_cost(rate), cost_model)
        try:
            charged = record_item_subscription_charge_if_first(
                provider=provider_key,
                operation=operation_key,
                item_id=item_key,
                billing_month=billing_month,
                monthly_rate=rate,
            )
            return (_round_cost(charged), cost_model)
        except Exception as exc:
            portfolio_logger.warning(
                "item subscription charge dedup failed provider=%s op=%s item=%s: %s "
                "(falling back to monthly_rate; api_call_log will over-attribute)",
                provider_key, operation_key, item_key, exc,
            )
            return (_round_cost(rate), cost_model)

    if cost_model == "per_connected_user_month":
        if budget_user_id is None:
            # Preflight WARN-fallback (Phase 2). Over-attribute.
            return (_round_cost(rate), cost_model)
        try:
            charged = record_connected_user_subscription_charge_if_first(
                provider=provider_key,
                user_id=int(budget_user_id),
                billing_month=billing_month,
                monthly_rate=rate,
            )
            return (_round_cost(charged), cost_model)
        except Exception as exc:
            portfolio_logger.warning(
                "connected-user subscription charge dedup failed provider=%s op=%s user=%s: %s "
                "(falling back to monthly_rate; api_call_log will over-attribute)",
                provider_key, operation_key, budget_user_id, exc,
            )
            return (_round_cost(rate), cost_model)

    # per_call — existing behavior preserved
    return (
        _estimate_cost(
            response=result,
            cost_fn=cost_fn,
            cost_per_call=(cost_per_call if cost_per_call is not None else rate),
        ),
        cost_model,
    )
```

Note the helper rename: v3 had a single `record_subscription_charge_if_first()`; v4 has two — `record_item_subscription_charge_if_first()` (Plaid, hits the per-Item table) and `record_connected_user_subscription_charge_if_first()` (SnapTrade, hits the per-Connected-User table). See §7.

### Signature changes to existing helpers

`_maybe_write_api_call_log` (`guard.py:164-221`) signature gets two new keyword-only params: `item_id: str | None` and `cost_model: str | None`. They flow into the row dict that's passed to `_write_api_call_log`. `_write_api_call_log` (`guard.py:97-161`) INSERT statement gets the two new columns. Both signatures are additive — existing call sites without the new kwargs default both to None (acceptable for non-Plaid providers).

### Plumbing into the three log-write sites

Each invocation passes `provider_key`, `operation_key`, `cost_model`, `rate`, `item_key` (Plaid subject), `budget_user_id` (SnapTrade subject — already in `guard_call`'s signature), plus the call-result-dependent inputs.

```python
# Site 1: fail-open finally (guard.py:301-318)
estimated_cost, effective_model = _compute_cost_for_log(
    provider_key=provider_key,
    operation_key=operation_key,
    cost_model=cost_model,
    rate=rate,
    item_key=item_key,
    budget_user_id=budget_user_id,
    result=result,
    cost_fn=cost_fn,
    cost_per_call=cost_per_call,
    billing_month=_current_billing_month(),
)
_maybe_write_api_call_log(
    ...,
    item_id=item_key,
    cost_model=effective_model,
    estimated_cost_usd=estimated_cost,
    ...,
)

# Site 2: live blocked branch (guard.py:354-371) — call was BLOCKED, no fn() ran.
# No subscription charge attempted; cost stays None; record dimension for forensics.
_maybe_write_api_call_log(
    ...,
    item_id=item_key,
    cost_model=cost_model,
    estimated_cost_usd=None,
    ...,
)

# Site 3: success finally (guard.py:387-411) — same signature as Site 1.
estimated_cost, effective_model = _compute_cost_for_log(
    provider_key=provider_key,
    operation_key=operation_key,
    cost_model=cost_model,
    rate=rate,
    item_key=item_key,
    budget_user_id=budget_user_id,
    result=result,
    cost_fn=cost_fn,
    cost_per_call=cost_per_call,
    billing_month=_current_billing_month(),
)
_maybe_write_api_call_log(
    ...,
    item_id=item_key,
    cost_model=effective_model,
    estimated_cost_usd=estimated_cost,
    ...,
)
```

For SnapTrade rows, `item_id` stays NULL in `api_call_log` — the `user_id` column (already populated from `budget_user_id`) IS the Connected User identifier.

### Edge cases (refined)

- **`item_id=None` for per-call op:** preflight does not fire; `api_call_log.item_id` stays NULL; `cost_model='per_call'`.
- **`item_id=""` empty:** treated as None at preflight (`.strip() or None`).
- **`budget_user_id=None` for per-call op or per-Item-month op:** preflight does not fire (only matters for `per_connected_user_month`).
- **`cost_per_call` passed for subscription op:** ignored. Document in `guard_call` docstring.
- **DB failure in either `record_*_subscription_charge_if_first`:** caught inside `_compute_cost_for_log`; logs WARN, over-attributes the full subscription rate. **Does not raise.** Successful vendor call surfaces normally.
- **Concurrent first-calls of month for same Plaid Item or same SnapTrade user:** `ON CONFLICT DO NOTHING RETURNING` is atomic on each unique constraint — exactly one returns rate, others return `Decimal('0')`.
- **SnapTrade: same user calls multiple subscription ops in same month:** first op (any of the 16 subscription ops) writes the $1.50 row; subsequent calls (any of the 16, including ones the first call didn't trigger) all hit the conflict and write $0. Single $1.50 charge per (user, month). Manual Refresh and Recent Orders go through the per-call branch — they never touch this table. Matches V4c R2 verified contract reality.
- **Dry-run mode:** subscription branches run identically. Dry-run only affects `BudgetExceededError` raising; charge-table writes still happen (continuity in cost history when dry-run flips off).
- **Failed vendor call (`result is None`):** `estimated_cost = None`, no charge row written — only successful calls bill.
- **Live blocked decision (call never made):** `estimated_cost = None`, no charge row written; `item_id` and `cost_model` still recorded in `api_call_log` for forensics.
- **`_PHASE_3_ENFORCED`:** module-level constant in `guard.py`. `False` while P2 is live; flipped to `True` in the P3 PR. Transitional code, removed after P3 is in production for ≥1 week.

---

## 6. Subject-identifier resolution at callsites (Phase 3)

### Plaid: `item_id` plumbing required

`get_plaid_token()` at `brokerage/plaid/secrets.py:61` returns a payload that includes `item_id` (verified — see `secrets.py:34-38` for the stored payload shape). Every production caller already retrieves the payload — they currently extract `access_token` and discard `item_id`. Phase 3 changes them to extract and forward `item_id`.

### Wrappers in `brokerage/plaid/client.py`

| Wrapper | Lines | Op | Cost model | Action |
|---|---|---|---|---|
| `_fetch_plaid_holdings` | 281-354 | `investments_holdings_get` | subscription | Add `item_id: str \| None = None` param; forward to `guard_call` |
| `fetch_plaid_holdings` | 357-367 | (delegates) | subscription | Add param; forward |
| `get_investments_transactions` | 488-514 | `investments_transactions_get` | subscription | Add param; forward |
| `_fetch_plaid_balances` | 371-442 | `accounts_balance_get` | per-call | Optional plumbing — recommend adding for consistency |
| `fetch_plaid_balances` | 445-455 | (delegates) | per-call | Same |
| `get_item`, `_get_institution_info`, `exchange_public_token`, `wait_for_public_token` | various | (per-call, free) | per-call | No change |

### Caller wiring (production)

**`services/plaid_portfolio_loader.py`** (~line 142):
```python
access_token = token_data["access_token"]
item_id = token_data.get("item_id")          # NEW — already in payload
holdings_data = fetch_plaid_holdings(access_token, item_id=item_id)
```

**`trading_analysis/data_fetcher.py`** (~line 440):
```python
access_token = token_data["access_token"]
item_id = token_data.get("item_id")          # NEW
response_dict = get_investments_transactions(
    access_token, start_date=..., end_date=..., options=..., item_id=item_id,
)
```

### Caller wiring (diagnostic scripts — REQUIRED before P3 enforcement flip)

These call subscription wrappers and would hard-error after the preflight check is enforced. Wire them in P3:

- **`scripts/diagnose_plaid_balances.py`** — calls subscription wrappers in dev sweeps. Plumb `item_id` from the same `get_plaid_token()` payload pattern as production callers.
- **`scripts/explore_transactions.py`** — same.

Both scripts already consume the secrets-manager payload; the change is one-line `item_id = token_data.get("item_id")` + forward.

### SnapTrade: production wiring REQUIRED (Codex round-4 fix)

V4 round-4 review surfaced that `budget_user_id` is **NOT** threaded through every SnapTrade callsite — it's threaded through `services/snaptrade_portfolio_loader.py` and the `brokerage/snaptrade/users.py` lifecycle wrappers' parameter signatures, but several production callers don't pass it. The "no production wiring" claim from v4 was wrong.

**Inventory of callsites that need wiring (verified 2026-04-25):**

| File | Line(s) | Op | Fix |
|---|---|---|---|
| `brokerage/snaptrade/adapter.py` | 253, 259 | `accounts.balance` (subscription) | Plumb `budget_user_id` through adapter call signature; thread to `_get_user_account_balance_with_retry(...)` |
| `brokerage/snaptrade/adapter.py` | 324, 330 | `accounts.list` (subscription) | Plumb `budget_user_id`; thread to `_list_user_accounts_with_retry(...)` |
| `brokerage/snaptrade/adapter.py` | other | trading + balance + symbol-search ops | Same — every call into `brokerage.snaptrade.client` from this file needs `budget_user_id` in scope and forwarded |
| `routes/snaptrade.py` | 594 | `register_snaptrade_user(user['email'])` (subscription) | Pass `budget_user_id=user['id']` from authenticated session |
| `routes/snaptrade.py` | 1323 | `delete_snaptrade_user(user['email'])` (subscription) | Same — pass authenticated `user['id']`. Note: lifecycle deletion paths must verify session is authenticated; if deletion is ever invoked from unauthenticated/admin context (e.g., GDPR purge), use sentinel `budget_user_id=0` and document the carve-out |
| `scripts/run_snaptrade.py` | 39, 121 | `register_snaptrade_user`, `delete_snaptrade_user` | Resolve `budget_user_id` from `args.user_email` via `inputs.database_client.get_user_by_email(...).id`, or pass `--budget-user-id` CLI arg. Sentinel `budget_user_id=0` acceptable for true non-user maintenance modes (document) |
| `scripts/snaptrade_sdk_smoke.py` | 40, 53 | same | Smoke script — sentinel `budget_user_id=0` is fine; this is intentionally test-traffic and shouldn't pollute real-user dedup |
| `scripts/explore_transactions.py` | (TBD) | (transactions ops) | Audit; same sentinel-vs-real treatment as run_snaptrade.py |

**P2 → P3 sequencing (Codex round-4 fix):** the wiring sweep + fixes belong in **P3** (P2 still ships dormant subscription branch with WARN-fallback so production isn't broken pre-wiring), but **MUST land before flipping `_PHASE_3_ENFORCED=True`**. Otherwise the flip turns these unwired callsites into runtime ValueError. P3 is now ordered: (1) wire all callsites, (2) update tests + sweep, (3) flip enforcement, all in the same PR.

**Sweep command (Codex round-5 fix — AST-based, robust against formatting):**

The earlier `rg --multiline` + line-grep approach false-positives every line of a multi-line `guard_call(...)` block, and the file-level `xargs rg -L 'budget_user_id'` misses files where one callsite has `budget_user_id` and another doesn't. Use Python AST to inspect each `guard_call(...)` call individually:

```bash
python3 - <<'PYEOF'
import ast, pathlib

SKIP = (".git/", "node_modules/", ".venv/", "build/", "dist/", "__pycache__/")

for path in pathlib.Path(".").rglob("*.py"):
    if any(s in str(path) for s in SKIP):
        continue
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match guard_call(...) — bare name OR module attribute access.
        callee = node.func
        name = callee.attr if isinstance(callee, ast.Attribute) else getattr(callee, "id", "")
        if name != "guard_call":
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        provider = kw.get("provider")
        if not (isinstance(provider, ast.Constant) and provider.value == "snaptrade"):
            continue
        if "budget_user_id" not in kw:
            print(f"{path}:{node.lineno} guard_call(provider='snaptrade', ...) MISSING budget_user_id")
PYEOF
```

Walks every `.py`, parses the AST, and reports each individual `guard_call(provider="snaptrade", ...)` invocation that doesn't pass `budget_user_id` — by line number, regardless of how the call is formatted. P3 must reduce this output to zero before flipping `_PHASE_3_ENFORCED=True`.

For the upstream callers (registers/deletes that haven't yet reached `guard_call`), a separate AST sweep on the public SnapTrade boundary functions:

```bash
python3 - <<'PYEOF'
import ast, pathlib

PUBLIC = {"register_snaptrade_user", "delete_snaptrade_user",
          "reset_snaptrade_user_secret", "fetch_snaptrade_holdings"}
SKIP = (".git/", "node_modules/", ".venv/", "build/", "dist/", "__pycache__/")

for path in pathlib.Path(".").rglob("*.py"):
    if any(s in str(path) for s in SKIP):
        continue
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name not in PUBLIC:
            continue
        kw = {k.arg for k in node.keywords if k.arg}
        if "budget_user_id" not in kw:
            print(f"{path}:{node.lineno} {name}(...) MISSING budget_user_id")
PYEOF
```

Both sweeps run in P3, output reduced to zero, P3 PR ships.

**Sweep limitations** (Codex round-6 acknowledged):
- The AST matcher catches `guard_call(...)` and `module.guard_call(...)`, but NOT aliased imports (`from app_platform.api_budget import guard_call as gc; gc(...)`). Current codebase doesn't use aliases — if a future PR introduces one, extend the matcher or ban aliasing in lint.
- The matcher uses `ast.Constant` for `provider="snaptrade"` literal matching. A caller passing `provider=PROVIDER_KEY` (variable) would silently slip through. Acceptable for V4a's current-state sweep — all live callers use the literal.

### No-derivation rule (D4 reaffirmed)

Per D4, `guard_call` does NOT look up `item_id` (Plaid) or `budget_user_id` (SnapTrade) internally — both flow in as explicit params. The plumbing is explicit and traceable through every call path. If a future caller doesn't have the right subject identifier in scope, that's a wiring bug — preflight catches it.

### Not a callsite

- **`routes/provider_routing.py:450`** (`_fetch_plaid_holdings`) — this is a `NotImplementedError` fallback today, NOT a real callsite. Removed from V1's wiring list. If/when the fallback is implemented, the implementer threads `item_id` then; not V4a's responsibility.

---

## 7. Dedup atomicity: two helpers (Phase 2)

Two helpers in `app_platform/api_budget/store.py` — one per billing dimension. Same INSERT...ON CONFLICT...RETURNING pattern, different tables and unique-constraint shapes. Both raise on DB failure (the catch-and-fallback lives in `_compute_cost_for_log`, see §5).

### Plaid helper: `record_item_subscription_charge_if_first`

Keys on `(provider, operation, item_id, billing_month)` because Plaid bills each subscription op independently per Item per month.

```python
def record_item_subscription_charge_if_first(
    *, provider: str, operation: str, item_id: str,
    billing_month: date, monthly_rate: Decimal,
) -> Decimal:
    """Atomically record a Plaid per-Item-per-op-per-month subscription charge.

    Returns monthly_rate on first call this (provider, op, item, month);
    Decimal('0') on subsequent calls. Atomicity from the UNIQUE constraint.
    """
    rate = Decimal(monthly_rate)
    with get_db_session() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO api_item_subscription_charges
                    (provider, operation, item_id, billing_month, charged_amount, charged_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (provider, operation, item_id, billing_month) DO NOTHING
                RETURNING id
                """,
                (
                    str(provider).strip().lower(),
                    str(operation).strip(),
                    str(item_id).strip(),
                    billing_month,
                    rate,
                ),
            )
            row = cursor.fetchone()
            conn.commit()
            return rate if row is not None else Decimal("0")
        except Exception:
            rollback = getattr(conn, "rollback", None)
            if callable(rollback):
                rollback()
            raise
        finally:
            close = getattr(cursor, "close", None)
            if callable(close):
                close()
```

### SnapTrade helper: `record_connected_user_subscription_charge_if_first`

Keys on `(provider, user_id, billing_month)` — no operation column because SnapTrade's $1.50 charge bundles 16 of 18 ops per (user, month). The two per-call carve-outs (`connections.refresh_brokerage_authorization`, `accounts.orders`) bypass this table.

```python
def record_connected_user_subscription_charge_if_first(
    *, provider: str, user_id: int,
    billing_month: date, monthly_rate: Decimal,
) -> Decimal:
    """Atomically record a SnapTrade per-Connected-User-per-month charge.

    Returns monthly_rate on first call this (provider, user, month) regardless
    of which of the 16 subscription ops was called; Decimal('0') on any
    subsequent subscription call (same op or different).
    Atomicity from the UNIQUE constraint.
    """
    rate = Decimal(monthly_rate)
    with get_db_session() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO api_connected_user_subscription_charges
                    (provider, user_id, billing_month, charged_amount, charged_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (provider, user_id, billing_month) DO NOTHING
                RETURNING id
                """,
                (
                    str(provider).strip().lower(),
                    int(user_id),
                    billing_month,
                    rate,
                ),
            )
            row = cursor.fetchone()
            conn.commit()
            return rate if row is not None else Decimal("0")
        except Exception:
            rollback = getattr(conn, "rollback", None)
            if callable(rollback):
                rollback()
            raise
        finally:
            close = getattr(cursor, "close", None)
            if callable(close):
                close()
```

### Race semantics

`ON CONFLICT DO NOTHING` with the UNIQUE index serializes inserts on the conflicting key:

- **T1 inserts, commits** → RETURNING returns row → T1 gets `rate`.
- **T2 starts after T1 commits** → sees conflict → RETURNING returns nothing → T2 gets `0`.
- **T1 and T2 race** → T2 blocks waiting for T1's outcome. If T1 commits, T2 sees conflict → `0`. If T1 rolls back, T2 succeeds → `rate`.

Either way exactly one logical insert succeeds. Standard Postgres ON CONFLICT semantics; no application-side coordination.

### Why no Redis fast-path (per D2)

A Redis-side check ("is there a key for this (item, month)?") would be eventually consistent with the DB. If Redis says "yes, already charged" but the DB committed nothing (silent failure), the second call would write $0 to `api_call_log` despite no real charge — under-attribution. Postgres-only is the source of truth. The cost is one extra DB round-trip per Plaid subscription call — negligible vs. the Plaid HTTP call itself.

---

## 8. `billing_month` representation

**Recommendation: `DATE`, set to first-of-month UTC.**

### Why DATE over TEXT 'YYYY-MM'

- Native date arithmetic in Postgres (`WHERE billing_month >= '2026-01-01'`).
- Type safety: TEXT accepts `'2026-13-99'`; DATE rejects. CHECK constraint pins to first-of-month.
- Indexable as a date.

### Why first-of-month + UTC

- Plaid bills on calendar-month boundaries. We pick UTC as the canonical TZ (matches `_period_start` in `app_platform/api_budget/store.py:86-92`, which uses `datetime.now(UTC).replace(day=1, ...)`).
- Predictable, no DST issues, deterministic in tests.
- If Plaid actually bills in non-UTC (e.g. America/Los_Angeles), our attribution will be off by 7-8h on month-boundary day. Acceptable accuracy for an estimate; one-helper change to fix later if needed.

### Helper

```python
def _current_billing_month(*, now: datetime | None = None) -> date:
    """First-of-month UTC. Mirrors _period_start convention in store.py:86-92."""
    current = (now or datetime.now(UTC)).astimezone(UTC)
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0).date()
```

---

## 9. Phasing

Four PR-sized phases (v1 had five — P2 and P3 merged after Codex flagged that P2 alone produced a $0 cost gap for holdings between rewriting the config and wiring the subscription path). Each ends in a Codex review gate. Phase boundaries are open to Codex tightening per user feedback ("scope reduction applies to impl, NOT API surface"); the API surface (§3 schema, §4 config, §5 guard signature, §7 dedup pattern) is locked.

| # | Phase | LoC | Files | Codex gate | Shippable on its own? |
|---|---|---|---|---|---|
| **0** | Land plan doc | ~80 docs | This doc; cross-link in `API_BUDGET_GUARD_PLAN.md` | `/codex review` this doc | Yes — pure docs |
| **1** | DB migration | ~70 SQL | `database/migrations/20260427_api_budget_subscription_dimension.sql` (new) — migration-only, no `schema.sql` append (matches the V1 `20260426_api_budget.sql` convention) | `/codex review <migration>` | Yes — schema-only, no behavior |
| **2** | Config + store helpers + guard branching (subscription path dormant) | ~450 (220 prod + 230 test) | `config/api_budget_costs.py` (rewrite + corrected per-call values + SnapTrade subscription set + V4d corrections), `app_platform/api_budget/store.py` (`record_item_subscription_charge_if_first` + `record_connected_user_subscription_charge_if_first`), `app_platform/api_budget/guard.py` (`item_id` param + preflight WARN-fallback for both subscription dimensions + 3-site cost-model branching + new log columns), `tests/api_budget/test_costs_config.py` (new — includes the exact-equality op-name test), `tests/api_budget/test_subscription_charges.py` (new — both helpers), `tests/api_budget/test_guard.py` (extend) | `/codex review <files>` | **Operationally safe, telemetry inaccurate for BOTH providers.** Default values for `item_id` and the `budget_user_id` preflight gate are WARN-fallback (no hard error). Balance per-call corrects to $0.10; SnapTrade `accounts.list`/`accounts.positions` per-call entries deleted. Plaid Holdings/Inv-Tx AND SnapTrade subscription ops over-attribute the full subscription rate per call until P3 wires `item_id` (Plaid) AND `budget_user_id` (SnapTrade — multiple production callsites need plumbing per §6). Dry-run masks the operational impact. **Do not use P2-only telemetry to size V4 thresholds — wait for P3.** |
| **3** | Plaid + SnapTrade callsite plumbing + flip enforcement | ~500-700 (Codex round-5 LoC re-estimate — adapter signature propagation, routes auth wiring, 3 scripts, fixture churn, new tests, enforcement flip) | **Plaid wiring:** `brokerage/plaid/client.py` (wrappers accept `item_id`), `services/plaid_portfolio_loader.py` (forward), `trading_analysis/data_fetcher.py` (forward), `scripts/diagnose_plaid_balances.py` + `scripts/explore_transactions.py` (forward). **SnapTrade wiring (Codex round-4 fix — was missing in v4):** `brokerage/snaptrade/adapter.py` (lines 253, 259, 324, 330 + any other `_with_retry` callsites — accept `budget_user_id` and forward), `routes/snaptrade.py:594, 1323` (pass authenticated `user['id']`), `scripts/run_snaptrade.py:39, 121` + `scripts/snaptrade_sdk_smoke.py:40, 53` + `scripts/explore_transactions.py` (resolve from email or use sentinel `0`). **Both providers:** `app_platform/api_budget/guard.py` (flip `_PHASE_3_ENFORCED = True` only AFTER all wiring above is complete in this PR). **Existing test fixtures updated to accept new kwargs:** Plaid — `tests/services/test_plaid_portfolio_loader.py`, `tests/providers/test_transaction_providers.py`, `tests/trading_analysis/test_provider_routing.py`, `tests/brokerage/test_plaid_client.py`. SnapTrade — `tests/brokerage/test_snaptrade_client.py`, `tests/services/test_snaptrade_portfolio_loader.py` (sweep + add sentinel where missing). **New tests:** `tests/brokerage/test_plaid_client_item_id_threading.py` (Plaid forwarding); `tests/brokerage/test_snaptrade_adapter_budget_user_id_threading.py` (new — SnapTrade adapter forwarding); SnapTrade preflight hard-error coverage in `test_guard.py`. **Sweep BEFORE flipping enforcement** (AST-based per Codex round-5): see §6 SnapTrade subsection for the AST sweep that walks every `guard_call(...)` invocation and reports per-callsite missing `budget_user_id`. Any unwired callsite found is a P3 blocker. | `/codex review <files>` | Yes — system functionally complete for both providers after this lands. |
| **4** | Verification + V4 unblock | ~50 docs | `docs/planning/API_BUDGET_GUARD_PLAN.md` (mark V4a done, lift V4 block), `docs/TODO.md` (close V4a row) | `/codex review <docs>` | Yes — pure docs |

**Critical path:** P1 → P2 → P3. Phases 0 and 4 are bookends.

**Phase 2 safety:** introduces the subscription branch but does NOT enforce preflight hard-error on missing subject identifiers (`item_id` for Plaid, `budget_user_id` for SnapTrade) — logs WARN and over-attributes the full subscription rate (status quo behavior — no regression vs. v1 broken-but-working). One-line module constant `_PHASE_3_ENFORCED = False` flips to `True` in Phase 3 in the same PR that wires Plaid `item_id` at all production callsites + diagnostic scripts and confirms SnapTrade `budget_user_id` is threaded everywhere.

**Why P2 doesn't break Plaid holdings cost or SnapTrade rollups (Codex round-1 + V4c fix):** `_plaid_cost_per_call("investments_holdings_get")` returning `Decimal("0")` after the config rewrite is fine — the subscription branch in `guard_call` (also landed in P2) consults `SUBSCRIPTION_COSTS_PER_ITEM_MONTH` directly via `get_cost_model_and_rate()`. Same for SnapTrade subscription ops: removing the wrong $0.05 entries from `COST_PER_CALL` doesn't matter because `get_cost_model_and_rate()` returns `('per_connected_user_month', $1.50)` for those ops. Wrapper-passed `cost_per_call=0` is ignored on both subscription paths. No cost gap.

**Existing test-fixture updates (Codex round-1 fix + V4c expansion):**

*Plaid side* — several existing tests monkeypatch `fetch_plaid_holdings`/`get_investments_transactions` with fakes that don't accept `item_id`. P3 must update these fakes before flipping `_PHASE_3_ENFORCED=True`, otherwise the test suite breaks:

```bash
rg -n 'fetch_plaid_holdings|get_investments_transactions|_fetch_plaid_holdings|fetch_plaid_balances' tests/
```

Identify monkeypatch sites, add `item_id=None` to the fake signatures.

*SnapTrade side* — existing tests already pass `budget_user_id` to SnapTrade wrappers (verified `tests/brokerage/test_snaptrade_client.py:43` and `tests/services/test_snaptrade_portfolio_loader.py`). But sweep to confirm none of the test scenarios call subscription ops with `budget_user_id=None`:

```bash
rg -n 'snaptrade.*guard_call|fetch_snaptrade_holdings|register_snaptrade_user|delete_snaptrade_user' tests/
```

If any test exercises a subscription op without `budget_user_id`, it'll hard-error after the P3 flip. Update fixtures to pass a sentinel (e.g., `budget_user_id=1`) where needed.

---

## 10. Test plan

| Test file | Phase | Coverage |
|---|---|---|
| `tests/api_budget/test_costs_config.py` (new) | P2 | `get_cost_model_and_rate` shape (3 cost-model values), D5 corrected per-call values (Balance $0.1000), phantom Plaid entries removed (`accounts_get`/`item_get`), Plaid subscription dict covers 4 D5 paths, **`SNAPTRADE_SUBSCRIPTION_OPS` exactly equals the live `guard_call(operation=...)` strings in `brokerage/snaptrade/client.py` minus the two per-call carve-outs (`connections.refresh_brokerage_authorization` + `accounts.orders`)** (Codex round-4 fix + V4c R2 corrections — would have caught the v4 op-name bug), neither carve-out in subscription set, both have COST_PER_CALL entries at the V4c R2 verified rates ($0.0500 and $0.0020), deleted SnapTrade per-call entries (`accounts.list`, `accounts.positions`) absent from `COST_PER_CALL`, dicts disjoint |
| `tests/api_budget/test_subscription_charges.py` (new) | P2 | Helper-level tests for **both helpers**. Plaid: first-call returns rate, second returns $0, concurrent threads exactly-once, multi-Item same op, same Item different ops, month-rollover re-charges, CHECK constraint enforcement (direct SQL `billing_month='2026-04-15'` raises). SnapTrade: first call ANY of the 16 subscription ops returns $1.50, subsequent calls (same OR different op) for same user same month return $0, different users same month each get charged once, month-rollover re-charges, CHECK constraint enforcement. Both helpers raise on DB failure by design (per §7) — that is verified at the guard level. |
| `tests/api_budget/test_guard.py` (extend) | P2 + P3 | Preflight WARN on missing item_id (P2 Plaid), preflight WARN on missing budget_user_id (P2 SnapTrade), preflight ValueError on either missing subject (P3 after flip), subscription first-call writes the rate to log, subsequent writes $0, blocked-decision branch logs `item_id` + `cost_model` with `estimated_cost_usd=NULL`, fail-open path also writes new fields, per-call passthrough unchanged, dry-run still writes charge row, **DB failure in `_compute_cost_for_log` does NOT raise** (helper-raised exception caught for both providers, falls back to over-attribution + WARN log), existing tests still pass |
| `tests/brokerage/test_plaid_client_item_id_threading.py` (new) | P3 | Wrappers forward `item_id` into `guard_call` for all Plaid subscription ops; per-call wrappers may also forward (consistency) |
| `tests/brokerage/test_snaptrade_adapter_budget_user_id_threading.py` (new) | P3 | **NEW (Codex round-4 fix)** — SnapTrade adapter forwards `budget_user_id` into `_with_retry` helpers and through to `guard_call`. Covers the production wiring at `brokerage/snaptrade/adapter.py:253, 259, 324, 330`. |
| Existing test-fixture updates — Plaid (sweep + patch) | P3 | Updates to monkeypatch fakes in `tests/services/test_plaid_portfolio_loader.py`, `tests/providers/test_transaction_providers.py`, `tests/trading_analysis/test_provider_routing.py`, `tests/brokerage/test_plaid_client.py`. Each fake `fetch_plaid_holdings`/`get_investments_transactions` signature gets `item_id=None` added. Run `rg -n 'fetch_plaid_holdings\|get_investments_transactions' tests/` to enumerate. |
| Existing test-fixture sweep — SnapTrade | P3 | Sweep + patch any test fixtures that exercise SnapTrade subscription ops without `budget_user_id`. `tests/brokerage/test_snaptrade_client.py:43` and `tests/services/test_snaptrade_portfolio_loader.py` already thread `budget_user_id`, but auth/lifecycle test scenarios in `routes/snaptrade.py`'s test files may not. Add a sentinel `budget_user_id=1` where missing (preflight will hard-error otherwise after P3 flip). Run `rg -n 'snaptrade.*guard_call\|fetch_snaptrade_holdings\|register_snaptrade_user\|delete_snaptrade_user' tests/` to enumerate. |

### DB fixture pattern

`tests/api_budget/test_subscription_charges.py` requires a real Postgres fixture (CHECK constraint enforcement + concurrency tests need actual DB). Existing `tests/api_budget/conftest.py` is Redis/monkeypatch oriented — it does NOT yet have a Postgres fixture. P2 must add one (or reuse the project-wide `db_fixture` pattern if one exists; check before writing).

Acceptable pattern: pytest fixture that creates a temp schema, runs `database/migrations/20260427_api_budget_subscription_dimension.sql` once, and rolls back per-test via `SAVEPOINT`. This matches how `test_snapshot.py` exercises `api_call_counters` upserts (read it first to confirm convention).

---

## 11. Verification protocol (live calls against dev accounts — both providers)

Run after Phase 3 lands. Pre: `API_BUDGET_ENABLED=true`, `API_BUDGET_DRY_RUN=true` (still dry-run; we're verifying attribution before V4 flip).

### Plaid (5 steps)

1. **First holdings fetch this month** — trigger refresh; verify one row in `api_item_subscription_charges` with `charged_amount=0.1800`; verify last `api_call_log` row has `cost_model='per_item_month'`, `estimated_cost_usd=0.1800`, `item_id=<known>`.
2. **Second holdings fetch same month** — trigger again; verify still exactly one charges row; verify new `api_call_log` row has `estimated_cost_usd=0.0000`.
3. **Balance call same Item** — trigger balance fetch; verify `cost_model='per_call'`, `estimated_cost_usd=0.1000`; no new charges row.
4. **Admin endpoint Plaid view** — `GET /api/admin/api-budget?provider=plaid` → `today_cost_by_provider` reflects $0.18 + $0.10 = $0.28, not pre-V4a inflated values.
5. **Plaid month rollover** — direct SQL insert of last-month charges row, then re-trigger holdings; verify new current-month row appears, `api_call_log` records $0.18.

### SnapTrade (6 steps — extra step for the new Recent Orders per-call axis)

1. **First subscription op this month** — trigger any SnapTrade flow that hits `accounts.list` (e.g., `fetch_snaptrade_holdings`); verify one row in `api_connected_user_subscription_charges` with `charged_amount=1.5000`, `user_id=<dev_budget_user_id>`; verify last `api_call_log` row has `cost_model='per_connected_user_month'`, `estimated_cost_usd=1.5000`, `user_id` populated, `item_id=NULL`.
2. **Second subscription op same month, same user, different op** — trigger `accounts.positions` for the same user; verify still exactly one charges row; verify new `api_call_log` row has `estimated_cost_usd=0.0000`. **This is the critical SnapTrade-specific check** — bundling 16 ops into one charge.
3. **Manual Refresh per-call** — trigger `connections.refresh_brokerage_authorization`; verify `cost_model='per_call'` in `api_call_log` with `estimated_cost_usd=0.0500`; no new charges row in `api_connected_user_subscription_charges`.
3b. **Recent Orders per-call** — trigger `accounts.orders`; verify `cost_model='per_call'` in `api_call_log` with `estimated_cost_usd=0.0020`; no new charges row.
4. **Admin endpoint SnapTrade view** — `GET /api/admin/api-budget?provider=snaptrade` → `today_cost_by_provider` reflects $1.50 (subscription) + $0.05 (Manual Refresh) + $0.002 (Recent Orders), not the pre-V4a wrong $0.05-per-call inflation.
5. **SnapTrade month rollover** — direct SQL insert of last-month charges row for `(provider='snaptrade', user_id=<dev>, billing_month=<last>)`, then re-trigger any subscription op; verify new current-month row appears, `api_call_log` records $1.50.

All eleven must pass (5 Plaid + 6 SnapTrade). Capture psql outputs in the V4a completion note appended to `docs/planning/API_BUDGET_GUARD_PLAN.md`.

---

## 12. Risk & rollout

- **No new feature flag.** `API_BUDGET_ENABLED` + `API_BUDGET_DRY_RUN` + phased rollout cover safety. Adding a third flag bloats the test matrix.
- **Migration safety:** `ADD COLUMN ... NULL` is sub-second on `api_call_log` (weeks of data). New table starts empty. Rolling-restart safe.
- **No backfill.** Pre-V4a `api_call_log` rows keep NULL `item_id`/`cost_model` and their wrong `estimated_cost_usd`. Admin tile's 1-day window cleans up within 24h; 30-day retention cleans the full log within a month.
- **Revert path:** revert P3 alone → wrappers stop passing `item_id` → guard hits preflight WARN-fallback → behavior returns to today's broken-but-working state (over-attributes monthly_rate per call instead of dedup-correct). P1–P2 are forward-compatible.
- **Dry-run telemetry post-V4a:** becomes accurate — exactly why V4 was deferred. After V4a lands, V4 flip becomes unblocked.
- **Subscription wrappers still pass `cost_per_call=0` after P2:** harmless — the subscription branch ignores it (consults `SUBSCRIPTION_COSTS_PER_ITEM_MONTH` via `get_cost_model_and_rate`). Documented in `guard_call` docstring.

### Accepted-estimate language (V4a is forecasting, not authoritative billing)

V4a's $ rollup is an **estimate** for live monitoring and threshold tuning, NOT a reconciliation against vendor invoices. Known mismatches:

- **TZ assumption:** we use UTC for the `billing_month` boundary on both providers (matching `_period_start` convention in `store.py:86-92`). Plaid and SnapTrade contracts may bill in different TZs (unverified for both). On month-boundary day, attribution can be off by 7-8h per provider. **Acceptance:** acceptable for forecasting; if reconciliation against either invoice diverges by >10%, revisit. **Action:** verify both providers' billing TZ at next dashboard peek; if non-UTC, swap `_current_billing_month()` to use that TZ (one-helper change, no schema change).
- **Plaid: "First successful call" trigger may not match Plaid's actual trigger.** Plaid may bill on Item existence + product enablement (regardless of whether we call), or on first call. Mismatch directions:
  - Item exists, products enabled, we never call → we record $0, Plaid bills full → we **under-charge**.
  - Item removed mid-month → we charged the full month, Plaid may pro-rate → we **over-charge**.
  - Item re-linked after disconnect (new `item_id`) → we charge twice in same calendar month, Plaid may bill once → we **over-charge**.
- **SnapTrade: "First successful subscription call" trigger may not match SnapTrade's actual trigger.** SnapTrade may bill on Connected User existence + ≥1 active connection, or on first API call:
  - User has connections but we never call → we record $0, SnapTrade bills $1.50 → **under-charge**.
  - User deletes all connections mid-month → we charged $1.50 already, SnapTrade may pro-rate → **over-charge**.
  - User deleted via `authentication.delete_snap_trade_user` mid-month → same pro-rate concern.
  - Multiple users sharing a SnapTrade Connected User identity (shouldn't happen — `snaptrade_user_id` is hash-derived from email — but enforced only by the email→hash function, not at the DB level).
  - **Acceptance:** all forecasting errors. The point of V4a is "stop the dollar rollup from being structurally wrong by 4-30x," not "match invoices to the penny." If observed accuracy in dev is within ±20% of the vendor dashboard, ship.
- **Unique key environment scope:** dedup keys (`(provider, operation, item_id, billing_month)` for Plaid; `(provider, user_id, billing_month)` for SnapTrade) assume one environment per Postgres DB. If we ever run sandbox + dev + prod against the same DB (we don't today), distinct envs with the same `item_id` or `user_id` would collide and undercount. **Acceptance:** single-env per DB today; if multi-env mixing becomes a thing, add `environment` to both unique keys (additive migration, no rewrite). **Action:** note in V4a completion summary as future consideration.

### Idempotency note on migration

`CREATE TABLE IF NOT EXISTS` and `ADD COLUMN IF NOT EXISTS` provide best-effort idempotence for re-running the migration. They do NOT detect/repair partial state (e.g., table exists but is missing a column from a half-applied earlier run). This is acceptable because: (a) production migrations run once via the migration runner with transaction-scoped guarantees, (b) dev partial-state is recoverable by manually dropping and re-running. The CHECK constraint guard (`pg_constraint` lookup with `conrelid` filter) is the only block where ambiguity would be silently dangerous, and it's already tightened.

### Out of scope: tiered/volume-based per-call pricing

`completed/V4D_PROVIDER_RATE_VERIFICATION_PLAN.md` §6 Edge 2 flagged "tiered per-call pricing" (e.g., volume discounts like `$0.05/call below 10K, $0.03 above`) as a known schema gap that V4a's flat `Decimal` rate dicts cannot represent. **No live provider in `config/api_budget_costs.py` uses tiered pricing today** — Plaid + SnapTrade are dual-axis (per-call + per-subscription-month, both flat); IBKR/Schwab/FMP are flat $0.00; Anthropic is per-token (handled by `LLMUsage` × `LLM_PRICES`); SnapTrade Custom Plan volume breakpoints are subscription-tier negotiations, not auto-applied per-call tiers. So the gap is dormant. If a provider ever introduces real tiered per-call pricing, file V4f at that point — additive change (probably a `TIERED_COSTS_PER_CALL` dict keyed on `(provider, op)` with a list of `(threshold_count, rate)` tuples + a fourth branch in `_compute_cost_for_log`). Acknowledged here so V4d's flag stays visible.

---

## 13. Codex review workflow (per CLAUDE.md plan-first rule)

1. **Land plan doc (P0):** run `/codex review docs/planning/completed/API_BUDGET_SUBSCRIPTION_DIMENSION_PLAN.md`. Reviewers are encouraged to execute locally — diff the proposed migration against `database/migrations/20260426_api_budget.sql`, sanity-check the helper SQL semantics, and trace the `get_plaid_token` → wrapper → `guard_call` thread. Iterate to PASS.
2. **Per-phase impl:** for each of P1–P4, send the approved plan section to `mcp__codex__codex` (sandbox `workspace-write`, no model/reasoning override per CLAUDE.md). Codex implements; we review the diff; commit.
3. **Per-phase Codex review:** after each PR is drafted, run `/codex review <files>` to catch what Claude missed.
4. **Scope-reduction policy:** API surface (§3 schema, §4 config, §5 guard signature, §7 dedup pattern) is non-negotiable. Phase boundaries (§9) are open to Codex tightening.
5. **Plan §5↔§6 sync:** keep guard signature and Plaid callsite plumbing locked together on every revision (per user feedback).

---

## 14. Critical files

### Both providers
- `config/api_budget_costs.py` — schema rewrite + corrected values + `SNAPTRADE_SUBSCRIPTION_OPS` set (P2)
- `app_platform/api_budget/guard.py` — `item_id` param + preflight (both subjects) + 3-site branching + log new fields (P2, P3 flip)
- `app_platform/api_budget/store.py` — `record_item_subscription_charge_if_first` + `record_connected_user_subscription_charge_if_first` helpers (P2)
- `database/migrations/20260427_api_budget_subscription_dimension.sql` — two new tables + ALTER api_call_log (P1)
- `tests/api_budget/test_costs_config.py` (new), `test_subscription_charges.py` (new — both helpers), `test_guard.py` (extend — both subscription branches) — P2
- `docs/planning/API_BUDGET_GUARD_PLAN.md` — cross-link + post-V4a unblock note (P0, P4)

### Plaid-specific (P3 wiring)
- `brokerage/plaid/client.py` — wrappers accept and forward `item_id`
- `services/plaid_portfolio_loader.py` — pluck `item_id` from token payload, forward
- `trading_analysis/data_fetcher.py` — pluck `item_id`, forward
- `scripts/diagnose_plaid_balances.py`, `scripts/explore_transactions.py` — pluck `item_id`, forward
- `tests/brokerage/test_plaid_client_item_id_threading.py` (new) — Plaid forwarding test
- Existing test-fixture updates (Plaid): `tests/services/test_plaid_portfolio_loader.py`, `tests/providers/test_transaction_providers.py`, `tests/trading_analysis/test_provider_routing.py`, `tests/brokerage/test_plaid_client.py`

### SnapTrade-specific (P3 wiring — Codex round-4 corrected scope)
- `brokerage/snaptrade/adapter.py` — accept and forward `budget_user_id` at lines 253, 259, 324, 330 (and any other `_with_retry` calls into `brokerage.snaptrade.client`)
- `routes/snaptrade.py` — pass authenticated `user['id']` at lines 594, 1323
- `scripts/run_snaptrade.py` (lines 39, 121), `scripts/snaptrade_sdk_smoke.py` (lines 40, 53), `scripts/explore_transactions.py` — resolve `budget_user_id` from email, or use sentinel `0` for non-user maintenance modes
- `tests/brokerage/test_snaptrade_adapter_budget_user_id_threading.py` (new — adapter forwarding test)
- `tests/brokerage/test_snaptrade_client.py`, `tests/services/test_snaptrade_portfolio_loader.py` — sweep + add sentinel `budget_user_id=1` to subscription-op test scenarios that don't currently pass one

### NOT a callsite
- `routes/provider_routing.py` — `_fetch_plaid_holdings` is a `NotImplementedError` fallback; do not touch in V4a.

---

*Verified during planning (2026-04-25):* `get_plaid_token()` payload shape (`brokerage/plaid/secrets.py:24-58`), `guard_call` signature + cost-write paths (`app_platform/api_budget/guard.py:97-411`), `_period_start` UTC convention (`app_platform/api_budget/store.py:86-92`), admin `today_cost_by_provider` SUM query (`routes/admin_api_budget.py:46-56`), existing migration ordering convention (`database/migrations/20260426_api_budget.sql`).
