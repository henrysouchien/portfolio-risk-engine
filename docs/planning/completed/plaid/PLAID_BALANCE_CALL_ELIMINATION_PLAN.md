# Plaid Balance Call Elimination + Margin-Corrected Gap Plan

> **Goals:**
> 1. **Stop calling Plaid `/accounts/balance/get`** on every holdings refresh. Balance data we need is already in the `/investments/holdings/get` response. Eliminates 100% of per-call Balance charges.
> 2. **Fix a latent net-value bug.** Today's gap formula (`gap = current - sum(holdings)`) silently overstates cash by the amount of `margin_loan_amount` on institutions where `current` reports total assets. Real-data verification on Merrill: today's code shows $50,248 "idle cash" when the true net (cash − margin) is $50,000. Correct the gap formula to subtract `margin_loan_amount` when present.
>
> **Scope discipline**: This plan **preserves the codebase's existing single-net-`CUR:USD`-row convention**. Margin is represented as negative cash (when gap goes negative) — same as today. We are fixing the numeric correctness of the gap, not restructuring cash/margin into separate rows. Split-row representation was considered and rejected because it would break consolidation paths (`services/position_service.py:1501`, `inputs/portfolio_assembler.py:127`, `providers/plaid_loader.py:895`, `routes/positions.py:337`) and existing tests that assume single-net-row (`tests/unit/test_position_result.py:396`, `tests/core/test_position_flags.py:287`, `tests/routes/test_hedging_short_support.py:274`). A proper refactor to a first-class liability representation is deferred to a separate plan.

---

## Context

### The bill

User received a Plaid bill of **$342.40** for 3,424 `/accounts/balance/get` calls @ $0.10/call.

### Already mitigated (2026-04-16)

Config-only fix applied:
- `SYNC_PROVIDER_PLAID_VIA_CELERY=false` in `.env`
- `celery_beat` + `risk_module` restarted
- Effect: hourly beat (`workers/beat_schedule.py:44`) and webhook-driven auto-syncs (`routes/plaid.py:1509`) no longer fire
- Webhooks still mark `has_pending_updates=true` → UI badge → user-initiated refresh only

This plan addresses the remaining issue: every *user-initiated* refresh still makes `N institutions × (1 holdings call + 1 balance call)`. The balance call is redundant.

### Real-data verification (2026-04-16)

After reconnecting Merrill via Plaid Link (the old token was hard-deleted from AWS earlier today) and running a diagnostic against the new item, we captured actual `accounts[].balances` payloads from `/investments/holdings/get`. Key finding on the Merrill CMA-Edge account:

```json
{
  "available": 0.0,
  "current": 90509.66,
  "limit": null,
  "iso_currency_code": "USD",
  "margin_loan_amount": 248.4
}
```
Holdings sum for this account: **$40,261.26**.

**Interpretation**:
- `margin_loan_amount` IS populated with a non-null, non-zero value → Plaid surfaces it for this institution.
- Per Plaid Investments docs, `balances.current` for investment accounts is *"the total value of assets as presented by the institution"* (i.e., total assets, excluding liabilities).
- Today's formula: `cash = current - sum(holdings) = $50,248.40` → overstates cash by $248.40 because it doesn't subtract the margin liability.
- Corrected formula: `net_cash = current - sum(holdings) - margin_loan_amount = $50,000.00`. If net_cash < 0, a margin debit row is emitted (today's behavior when gap is negative).

Diagnostic script: `scripts/diagnose_plaid_balances.py` (no cost — uses free holdings endpoint only).

---

## Root cause (code path)

`providers/plaid_loader.py:568` inside `load_all_user_holdings()`:

```python
holdings_data = fetch_plaid_holdings(access_token, client)   # /investments/holdings/get (free - Investments subscription)
balances_data = fetch_plaid_balances(access_token, client)    # /accounts/balance/get  ($0.10/call)

for acct in balances_data["accounts"]:
    acct_id  = acct["account_id"]
    acct_bal = acct["balances"]   # only balances["current"] + balances["iso_currency_code"] are used downstream
    ...
    df = patch_cash_gap_from_balance(df, acct_bal, ...)
```

### What `patch_cash_gap_from_balance` actually uses (today)

Tracing the balance dict through `calc_cash_gap`, `append_cash_gap`, `should_skip_cash_patch` (all in `providers/plaid_loader.py`):

| Field read | Used by | Purpose |
|---|---|---|
| `balances["current"]` | `calc_cash_gap` line 173 | Numerator for gap calc: `gap = current - sum(holdings.value)` |
| `balances.get("iso_currency_code", "USD")` | `append_cash_gap` line 211 | Currency label on synthetic `CUR:<ccy>` row |

No other balance-block fields are consumed today. No other callers use `fetch_plaid_balances` (grep verified — single caller at line 568).

### Latent margin-reporting bug

The gap formula assumes `current` = net equity. For institutions that report `current` = total assets (Merrill, verified empirically):

```
True state:  $40k positions + $50.5k cash − $0.25k margin loan
Plaid returns: current=$90.51k, sum(holdings)=$40.26k, margin_loan_amount=$248.40
Gap formula: gap = 90.51k − 40.26k = +$50.25k → labels entire amount as "idle cash"
Result: margin debit of $248.40 silently hidden
```

Plaid's `AccountBalance` in the investments context includes a dedicated **`margin_loan_amount`** field. Reading it directly eliminates the institution-specific ambiguity in `current`.

### Field availability — sources of truth

Plaid's `/investments/holdings/get` response includes an `accounts[]` array where every account has a `balances` object. Fields this plan consumes: `account_id`, `name`, `official_name`, `balances.current`, `balances.iso_currency_code`, `balances.margin_loan_amount`.

Source-of-truth hierarchy:
1. **Plaid Investments API docs** (authoritative): `accounts[].balances.margin_loan_amount` documented as *"The total amount of borrowed funds in the account. For investment-type accounts, the margin balance is the total value of borrowed assets."*
2. **Observed production payload** (confirmed): captured 2026-04-16 on Merrill CMA-Edge → field present with value $248.40 (see Context above).
3. **Local `plaid-python` SDK (38.4.0)**: does NOT declare `margin_loan_amount` on `AccountBalance` model. SDK `response.to_dict()` returns the raw Plaid JSON, so dict access (`balances.get("margin_loan_amount")`) works regardless. Do not rely on SDK typing for this field — treat it as permissive transport.

All other consumed fields (`current`, `iso_currency_code`, `account_id`, `name`, `official_name`) are declared in the local SDK's `AccountBase`/`AccountBalance` models and match what `/accounts/balance/get` returns.

### Semantics change (intentional)

The plan deliberately switches from **live** balance (forced institution pull via `/accounts/balance/get`) to **bundled cached** balance (whatever balance Plaid returns inside the holdings response):

- `/investments/holdings/get` → balances are whatever Plaid has cached/returned alongside holdings. Plaid does **not** publicly document atomic snapshot equality between `holdings[]` and `accounts[].balances` in this response.
- `/accounts/balance/get` → Plaid explicitly refreshes `available` and `current` at call time (per Plaid Balance docs).

This is a deliberate design choice: we accept slightly-staler balance data in exchange for eliminating the $0.10/call cost. The bundled cached value is still fresh enough for cash-gap detection (we're computing the gap between two values returned from a single API call seconds apart, regardless of whether Plaid atomically snapshotted them).

**Mitigation**: QA step below requires a live-data comparison of synthetic cash rows before and after the change on a real Plaid Item to confirm the values are close enough for our use case.

---

## Proposed change

### Change 1: Drop the separate balance call

`providers/plaid_loader.py:560-568` — replace:

```python
for secret_path in all_tokens:
    token_data = get_plaid_token(...)
    access_token = token_data["access_token"]
    holdings_data = fetch_plaid_holdings(access_token, client)
    balances_data = fetch_plaid_balances(access_token, client)

    for acct in balances_data["accounts"]:
```

with:

```python
for secret_path in all_tokens:
    token_data = get_plaid_token(...)
    access_token = token_data["access_token"]
    holdings_data = fetch_plaid_holdings(access_token, client)

    for acct in holdings_data["accounts"]:
```

### Change 2: Margin-corrected gap formula (finite-float safe)

Update `calc_cash_gap` (line 155) to subtract `margin_loan_amount` from the gap so the single net `CUR:USD` row correctly reflects cash − liability:

```python
import math

def _as_finite_float(value, default=0.0, *, context=""):
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        portfolio_logger.warning("Non-numeric value for %s: %r", context, value)
        return default
    if not math.isfinite(result):
        portfolio_logger.warning("Non-finite value for %s: %r", context, value)
        return default
    return result

def calc_cash_gap(df_acct, balances, tol=0.01):
    current = balances.get("current")
    if current is None:
        portfolio_logger.warning(
            "[%s] Skipping cash-gap detection: balances.current is None",
            balances.get("iso_currency_code") or "UNKNOWN",
        )
        return 0.0
    acct_total  = _as_finite_float(current, context="balances.current")
    pos_total   = df_acct["value"].sum(skipna=True)
    margin_loan = _as_finite_float(
        balances.get("margin_loan_amount"),
        context="balances.margin_loan_amount",
    )
    gap = round(acct_total - pos_total - margin_loan, 2)
    return 0.0 if abs(gap) < tol else gap
```

**Formula rationale** (per Plaid Investments docs):
- `current` = total value of assets (cash + positions, liability excluded)
- `margin_loan_amount` = borrowed funds (liability)
- `sum(holdings.value)` = positions
- Therefore: `net_cash = current − sum(holdings) − margin_loan_amount`

For Merrill: `90509.66 − 40261.26 − 248.40 = $50,000.00` (correct net), vs today's $50,248.40 (overstated by the margin amount).

If `net_cash > 0` → synthetic cash row (today's "Synthetic cash" label).
If `net_cash < 0` → synthetic margin debit row (today's "Synthetic margin debit" label). This path now triggers correctly when margin exceeds idle cash.

**Finite-float handling**: `balances.get("margin_loan_amount") or 0.0` would not guard against `float('nan')`. The `_as_finite_float` helper explicitly coerces and logs on missing / non-numeric / non-finite values (None, NaN, inf, string), returning the default. Same helper used for `current`. Prevents NaN from contaminating the gap calculation.

### Change 3: Observability log for margin_loan_amount

When `margin_loan_amount > 0`, emit a single structured INFO log line per account with:
- `institution` (e.g., "Merrill")
- `account_id`
- `current`
- `holdings_total`
- `margin_loan_amount`
- `net_cash` (after the subtraction)
- `native_cash_present` (bool)
- `branch` (one of: `"gap_with_margin"`, `"native_cash_adjust"`, `"skipped_current_none"`)

Purpose: future debugging + visibility without UI changes. Feeds naturally into a follow-up first-class-liability representation if we pursue that refactor later.

### Change 4: Edge case — native cash holding + margin (in-place adjustment)

`should_skip_cash_patch` today returns `True` if the account already has a holding with `type == "cash"`, and bypasses the entire patch. This was fine when the gap only represented idle cash. With margin now folded in, if Plaid reports a native cash holding AND `margin_loan_amount > 0`, the current skip would silently hide the margin.

**Fix**: when a native cash holding exists AND `margin_loan_amount > 0`, **subtract `margin_loan_amount` from the existing native cash row's cash-amount fields in lockstep (both `quantity` and `value`, since cash rows represent dollar amount as both)**. Do NOT emit a second row. This preserves the single-row convention across all downstream paths — including ones that don't run consolidation (`/monitor?by_account=true`, DB saves with raw per-account rows, and paths where Plaid-specific markers like `DEPOSIT` don't normalize to `CUR:<ccy>`).

**Why both fields**: downstream consumers are inconsistent about which field represents the dollar amount for cash rows. Some paths sum `value` (e.g., `services/position_service.py:1509`), others read `quantity` (e.g., `inputs/portfolio_assembler.py:225`, `core/result_objects/positions.py:432,439`). Updating only `value` leaves the row internally inconsistent and produces divergent cash amounts across views.

**Also null out `cost_basis`**: Plaid normalized rows carry a `cost_basis` field (`providers/plaid_loader.py:124`). Downstream, cash P&L and entry-price calculations read `cost_basis` (`services/position_service.py:1944`, `core/result_objects/positions.py:374,388,397`). If we reduce `quantity`/`value` to account for margin but leave `cost_basis` at its original Plaid-reported value, the monitor view will show a fabricated cash loss equal to the margin adjustment. Null `cost_basis` on the adjusted native cash row — this matches the synthetic-cash row convention (`append_cash_gap` line 222 sets `"cost_basis": None` on synthetic rows) and prevents spurious P&L.

Implementation sketch (inside `patch_cash_gap_from_balance`):
```python
margin_loan = _as_finite_float(
    balances.get("margin_loan_amount"),
    context="balances.margin_loan_amount",
)

if should_skip_cash_patch(df_acct):
    if margin_loan > 0:
        # In-place: subtract margin from the existing native cash row(s).
        # If multiple cash rows exist, subtract from the largest non-zero one
        # to avoid creating negative values on an already-zero row.
        cash_mask = df_acct["type"] == "cash"
        if cash_mask.any():
            target_idx = df_acct.loc[cash_mask, "value"].abs().idxmax()
            # Update quantity + value in lockstep (both represent cash dollars).
            df_acct.at[target_idx, "value"] -= margin_loan
            if "quantity" in df_acct.columns:
                df_acct.at[target_idx, "quantity"] -= margin_loan
            # Null cost_basis to prevent fabricated P&L. Matches the
            # synthetic-cash row convention in `append_cash_gap`.
            if "cost_basis" in df_acct.columns:
                df_acct.at[target_idx, "cost_basis"] = None
            # Review `normalize_plaid_holdings` output at implementation time for
            # any other dollar-amount columns (e.g., local-currency value) to
            # include in this lockstep update.
            portfolio_logger.warning(
                "[%s] Adjusted native cash row in-place for margin_loan_amount=%.2f",
                institution, margin_loan,
            )
    return df_acct

# No native cash: use margin-corrected gap (Change 2)
gap = calc_cash_gap(df_acct, balances)
...
```

**Why in-place**: every downstream path sees a single cash row per account — including consolidation-free paths. The net_cash value is correct regardless of whether consolidation runs, regardless of which dollar-amount field is read.

**Branch matrix** (`branch` field in the structured log):
| Native cash holding | margin_loan_amount | Behavior |
|---|---|---|
| No | null / 0 | Today's gap formula (subtraction is no-op) |
| No | > 0 | `gap_with_margin`: compute gap with subtraction, emit single synthetic row (cash or margin depending on sign) |
| Yes | null / 0 | Today's behavior (skip, no patch) |
| Yes | > 0 | `native_cash_adjust`: subtract margin from existing cash row in place, no new row |

### Change 5: Keep `fetch_plaid_balances`

`fetch_plaid_balances` stays in `brokerage/plaid/client.py` (unused after this change but kept for future manual/debug needs and to avoid touching `__all__` exports at `brokerage/plaid/client.py:321`, `brokerage/plaid/__init__.py:8,28`). Add a single-line comment above the function noting it is intentionally not on the hot path.

---

## Risk analysis

### What could go wrong

1. **Stale cached balance** — Plaid-side cache may lag the institution. For cash-gap purposes this is acceptable: we're comparing `balances.current` to `sum(holdings.value)` from the **same response**, and both values come from Plaid's cache at the same fetch. Snapshot atomicity is not documented by Plaid but drift between the two values in a single response is expected to be small. QA step validates this empirically.

2. **Accounts array coverage** — `/investments/holdings/get` returns **all accounts on the Item** (per `InvestmentsHoldingsGetResponse.accounts` SDK docstring: "the accounts associated with the Item"), not just investment accounts. This is the same set `/accounts/balance/get` returns. The loop is safe because the existing `if not h: continue` guard at line 578 skips accounts with no holdings — no accounts are lost by switching the source.

3. **`balances.current` is `None`** — **FIX REQUIRED**. Plaid marks `current` as nullable (`AccountBalance.current`). Current code `float(balances.get("current", 0.0))` at line 173 returns `None` if the key exists with a `None` value (dict `get` default only triggers on missing key), and `float(None)` raises `TypeError`. This bug exists today but is masked because `/accounts/balance/get` always refreshes `current` so it's rarely `None` there. With bundled cached balances, `None` is more likely.

   **Fix**: add explicit guard in `calc_cash_gap` — if `balances.current is None`, return `0.0` (skip gap detection for this account) and emit a warning log. Do NOT coerce `None` to `0.0` inline because that would fabricate a false cash/margin synthetic row equal to the negative of the holdings value.

4. **Currency code absence** — `iso_currency_code` missing/None. Already handled: `append_cash_gap` line 211-214 defaults to `"USD"` with a warning log.

### What cannot go wrong

- Cost regression — we're removing a call, not adding one.
- Tests — no tests mock `fetch_plaid_balances` directly (grep verified). Higher-level tests mock `load_all_user_holdings` or `PositionService`.
- **Graceful fallback for `margin_loan_amount`** — when the field is absent, null, or zero (common case for non-margin accounts and institutions that don't populate it), behavior is identical to today. The margin-direct path is purely additive for accounts that populate the field.

### What WILL change (accepted)

- **Net cash value reduces by `margin_loan_amount`** on accounts with margin. For Merrill right now: `CUR:USD` row changes from `+$50,248.40` (today) to `+$50,000.00` (after fix). Net portfolio value becomes correct. Leverage only changes when corrected net cash turns negative (see Expected impact section).
- **If an account has margin debit exceeding idle cash** (net_cash < 0), the synthetic row becomes a "Synthetic margin debit" instead of "Synthetic cash" — which is today's intended behavior for margin accounts, just now working correctly on institutions where `current` reports total assets.
- **For non-margin accounts and institutions that don't populate `margin_loan_amount`**: behavior is identical to today (same formula since `margin_loan_amount` defaults to 0, so the subtraction is a no-op).

---

## Files changed

| File | Change | LOC |
|---|---|---|
| `providers/plaid_loader.py` | (1) Remove `fetch_plaid_balances` call at line 568; iterate `holdings_data["accounts"]` on line 571. (2) Add `_as_finite_float` helper (handles None/NaN/inf/non-numeric with warning logs). (3) In `calc_cash_gap` (line 155), add `None` guard on `balances.get("current")` AND subtract `margin_loan_amount` (coerced via helper) from the gap. (4) Update `patch_cash_gap_from_balance` to handle the "native cash + margin" edge case by adjusting both `quantity` and `value` in lockstep on the largest existing cash row (no new row). (5) Add structured INFO log with all context fields when `margin_loan_amount > 0`. | ~20–30 lines |
| `brokerage/plaid/client.py` | Add single-line comment above `fetch_plaid_balances` noting it is not on the hot path. | 1 line |

Test files changed:
- `tests/providers/test_plaid_loader.py` (or equivalent) — new unit tests for `_as_finite_float`, `calc_cash_gap` with margin + None/NaN cases, `patch_cash_gap_from_balance` native-cash branch incl. lockstep quantity/value/cost_basis assertions.
- `tests/services/test_position_service_cash_dedup.py` — verify cash consolidation post-adjustment.
- `tests/inputs/test_portfolio_assembler.py` — cash summing behavior unchanged for non-margin, correct for margin.
- `tests/services/test_portfolio_service_monitor_risk.py` — new by-account integrity test (single row, `quantity=value=49500`, no P&L).
- Any existing tests that assert specific cash-gap values for margin accounts — update assertions to the margin-corrected net.

No changes to:
- Exports / `__all__` (function still exists)
- Callers of `load_all_user_holdings` (signature unchanged)
- Env / config
- Documentation beyond this plan

---

## Verification

### Before/after (expected, not guaranteed)

Cash-gap detection on an account with $1,000 in a stock position and $50 idle cash:
- **Before**: holdings call returns positions=$1,000; live balance call returns current=$1,050; gap=$50 → synthetic `CUR:USD` row for $50.
- **After**: holdings call returns positions=$1,000 AND accounts[].balances.current=$1,050 (cached); gap=$50 → same synthetic row **if** the cached balance is current enough. Small drift is possible and acceptable.

### Test plan

1. **Unit tests — `calc_cash_gap`**:
   - `current=None` → returns `0.0` + warning, does not raise.
   - `current=90509.66`, `holdings_sum=40261.26`, `margin_loan_amount=248.4` → returns `50000.00`. Asserts margin subtracted.
   - `current=40000`, `holdings_sum=40000`, `margin_loan_amount=500` → returns `-500.00` (negative triggers margin debit row downstream).
   - `margin_loan_amount=None` → identical to today's behavior.
   - `margin_loan_amount=0` → identical to today's behavior.
   - `margin_loan_amount=float('nan')` → returns gap without margin (NaN coerced via `_as_finite_float`) + warning log.
   - `margin_loan_amount=float('inf')` → same as NaN case.
   - `margin_loan_amount="bogus"` → same as NaN case (non-numeric).

2. **Unit tests — `patch_cash_gap_from_balance` native-cash branch**:
   - Account with one cash row (`quantity=50000, value=50000, cost_basis=50000`) AND `margin_loan_amount=500` → both `quantity` AND `value` on that row equal `49500`, `cost_basis` is `None`, **no new row appended**, log WARN emitted.
   - Account with one cash row AND `margin_loan_amount=null` → unchanged behavior (skip).
   - Account with multiple cash rows AND `margin_loan_amount=500` → subtracted from the row with the largest absolute value (not split across rows). Both `quantity` and `value` on that row reduced by 500; `cost_basis` nulled on that row.
   - Account with no cash row AND `margin_loan_amount=500`, `current=40000`, `holdings=40000` → emits single `CUR:USD = -500` row via the gap formula (both `quantity=-500` and `value=-500` on the synthetic row).
   - **P&L non-fabrication test** — adjusted native cash row must not produce a non-zero `pnl` / `gain_loss_usd` / `entry_price` discrepancy anywhere downstream. Run the `core/result_objects/positions.py` view builder on the adjusted row and assert cash P&L stays at zero (or `None`).

3. **Downstream consolidation tests** — run these with the new formula and assert single-net-row convention holds:
   - `tests/services/test_position_service_cash_dedup.py` — cash consolidation path (`services/position_service.py:1501`)
   - `tests/inputs/test_portfolio_assembler.py:178` — portfolio assembler cash summing (`inputs/portfolio_assembler.py:127`)
   - `tests/services/test_portfolio_service_monitor_risk.py:128` — `by_account=true` path (does NOT consolidate; critical for native-cash-adjust case)
   - `tests/unit/test_position_result.py:396` — CUR:USD negative = margin convention
   - `tests/core/test_position_flags.py:287` — flag logic on negative cash
   - `tests/routes/test_hedging_short_support.py:274` — hedge sizing with negative cash

4. **By-account integrity test** (new): simulate a Plaid account with a native cash holding of $50k AND `margin_loan_amount=500`. After sync, query `/monitor?by_account=true` endpoint and assert exactly ONE cash row per account with **both `quantity=49500` AND `value=49500`** (lockstep update verified). This specifically exercises the consolidation-free path and the dual-field update Codex flagged.

5. **Live validation against reconnected Merrill data**:
   - Before change: current `positions` table shows Merrill's `CUR:USD = +$50,248.40`.
   - After change: run a Plaid refresh via the app. Expected: `CUR:USD = +$50,000.00` (±small drift from cached balance; validate against Merrill statement).
   - Structured INFO log line for Merrill CMA-Edge should appear with `branch=gap_with_margin`, `margin_loan_amount=248.40`, `net_cash=50000.00`.

6. **Zero-balance-call verification** — after change, click "Refresh" on frontend, verify celery logs show:
   - `fetch_plaid_holdings` call present
   - **No** `fetch_plaid_balances` call
   - Plaid dashboard shows zero `/accounts/balance/get` calls for the next 24h.

7. **Regression check on non-margin accounts** — verify credit-card and savings accounts (which returned `margin_loan_amount: null` in the diagnostic) produce identical cash-gap output before/after.

8. **SnapTrade regression check** — run `tests/api/test_snaptrade_integration.py:314` and similar to confirm cross-provider consolidation is unaffected (SnapTrade path unchanged; this is a sanity check that Plaid-side changes don't leak).

---

## Expected impact

- **Cost**: $0.10 × every balance call eliminated. For a user with 3 institutions refreshing once per day: saves $0.30/day = ~$9/month per user.
- **Latency**: one fewer API call per refresh (~200-500ms saved per institution).
- **Correctness improvement (net cash)**: Net cash is no longer inflated by the margin liability. For Merrill: cash row drops from $50,248 → $50,000. For accounts where margin exceeds idle cash (e.g., $10k cash + $20k margin), net cash now correctly goes negative and emits a margin debit row — today's formula would show $10k of cash and silently lose the margin.
- **Correctness tradeoff (cash balance)**: For non-margin accounts, balances come from the holdings response's cached snapshot rather than the live balance call. Plaid does not document atomic snapshot equality. Drift is expected to be small and is validated by live testing against the reconnected Merrill account.
- **Leverage impact (narrowed)**: Net cash / net portfolio value become correct. **Leverage only changes when corrected net cash turns negative** — today's leverage math (`core/position_flags.py:154`, `portfolio_risk_engine/portfolio_config.py:232`) excludes positive cash from leverage calculations, so the Merrill example (cash drops from $50,248 to $50,000 but stays positive) will NOT surface a leverage change. Liability-aware leverage remains a separate plan.
- **No downstream representation change**: single-net-`CUR:USD`-row convention preserved across consolidation-free paths (`/monitor?by_account=true`, raw DB saves) and consolidated paths alike. No new row shapes introduced.

---

## Non-goals

- Re-enabling the Celery hourly beat — webhook + manual refresh is the correct design per `PLAID_COST_REDUCTION_PLAN.md` and user decision today.
- Removing `fetch_plaid_balances` function definition — keep for manual/debug use.
- Changes to SnapTrade / other providers — scoped to Plaid only.
- **First-class liability representation.** Introducing a separate margin/liability position type (distinct from negative cash) would be the architecturally cleaner fix, but requires touching consolidation paths (`services/position_service.py:1501`, `inputs/portfolio_assembler.py:127`, `providers/plaid_loader.py:895`, `routes/positions.py:337`), factor proxy logic (`services/factor_proxy_service.py:361`), and existing tests (`tests/unit/test_position_result.py:396`, `tests/core/test_position_flags.py:287`, `tests/routes/test_hedging_short_support.py:274`). Deferred to a separate plan.

---

## Codex review checklist

Ask Codex to verify:
1. **Formula correctness** — is `net_cash = current − sum(holdings) − margin_loan_amount` the right formula for the single-net-row convention, given Plaid Investments docs define `current` as total assets (excluding liability) for investment accounts?
2. **Balance-call elimination is complete** — does dropping the `fetch_plaid_balances` call at `providers/plaid_loader.py:568` remove ALL hot-path callers? Any remaining `balances_data` references in the file?
3. **Accounts array coverage** — does `/investments/holdings/get` `accounts[]` cover the same Item-level account set as `/accounts/balance/get`, with filtering still handled by the existing `if not h: continue` guard at line 578?
4. **Native-cash in-place adjustment** — the plan adjusts both `quantity` and `value` on the native cash row (lockstep). Are there OTHER dollar-amount columns on the row at this pipeline stage that would also need updating (e.g., local-currency value, cost_basis-derived columns)? Review the `normalize_plaid_holdings` output schema.
5. **Finite-float coercion** — is `_as_finite_float` (which handles None/NaN/inf/non-numeric with warning + default=0.0) correct for both `current` and `margin_loan_amount` use sites? Any edge case (e.g., `Decimal`, numpy scalars from the SDK) that would bypass the `math.isfinite` check?
6. **Downstream test coverage** — the plan expanded test coverage to include `test_position_service_cash_dedup.py`, `test_portfolio_assembler.py:178`, `test_portfolio_service_monitor_risk.py:128`, and a new by-account integrity test asserting both `quantity=value=49500`. Is this list complete, or is there another consolidation-free path still uncovered?
7. **Leverage impact claim** — plan states leverage only changes when net_cash goes negative, citing `core/position_flags.py:154` and `portfolio_risk_engine/portfolio_config.py:232`. Is this narrowed claim accurate for all leverage-consuming code paths?
8. **Observability log** — structured INFO log fields (`institution`, `account_id`, `current`, `holdings_total`, `margin_loan_amount`, `net_cash`, `native_cash_present`, `branch`) — sufficient for future debugging, or anything missing?
