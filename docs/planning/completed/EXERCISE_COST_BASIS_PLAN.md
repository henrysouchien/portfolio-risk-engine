# Option Exercise Cost Basis Linkage Plan

**Created**: 2026-03-08
**Status**: Planning (v5 — addressing Codex v4 review findings)
**Impact**: Lot P&L per-line accuracy ($179 SLV gap), tax-correct cost basis
**Reviewed by**: Codex v1 (3F, 4C) → v2 (2F, 3C) → v3 (1F, 2C) → v4 (0F, 1C)

## Problem

When a long call is exercised, IBKR produces two trade rows:

| Row | Symbol | Side | Qty | Price | Code | Effect |
|-----|--------|------|-----|-------|------|--------|
| Option close | SLV 30C | SELL | 1 | $0 | `C;Ex` | Close option via exercise |
| Stock open | SLV | BUY | 100 | $30 | `Ex;O` | Receive shares at strike |

IBKR transfers the option premium ($178.71) into the stock's cost basis:
- Stock cost = $30.00 (strike) + $1.787 (premium/share) = **$31.787/share**
- Option realized P&L on the exercised contract = **$0**

Our engine treats these as independent FIFO events:
- Option SELL @ $0 → books **-$178.71 loss** (premium paid minus $0 exit)
- Stock BUY @ $30.00 → cost basis = **$30.00/share**

The net P&L across option + stock is identical in both systems. But per-line
P&L doesn't match IBKR, and the stock cost basis is wrong for tax purposes.

**Current gap**: -$179 on `SLV_C30_250620` option P&L.

## Approach: Pre-FIFO Linkage

Scan all normalized IBKR trades, detect exercise/assignment pairs using the
Flex `code` field, and adjust prices **before** FIFO matching. No changes to
the FIFO matcher itself.

### Why pre-FIFO (not post-FIFO)

- FIFO `_process_entry()` creates `OpenLot` with `entry_price`. If we adjust
  the stock's price before FIFO, the lot is created with the correct cost basis
  from the start — no lot mutation needed.
- Post-FIFO adjustment would require finding and modifying open lots, which
  breaks the immutable-after-creation pattern.
- Pre-FIFO keeps the linkage module self-contained with no FIFO dependencies.

### Math verification

**Single contract** (SLV case):
- `broker_cost_basis` = $178.71 per contract (from `flex.py:375-378`: `abs(raw_cost) / raw_qty`)
- `opt_qty` = 1 contract
- `total_premium` = `broker_cost_basis × opt_qty` = $178.71 × 1 = $178.71
- `premium_per_share` = `total_premium / stk_qty` = $178.71 / 100 = $1.787

Before (current):
- Option FIFO P&L: ($0 - $178.71) × 1 = **-$178.71**
- Stock lot entry: $30.00/share

After (with linkage):
- Option exit price set to `broker_cost_basis` ($178.71 per contract):
  FIFO P&L = ($178.71 - $178.71) × 1 = **$0.00**
- Stock entry price: $30.00 + $1.787 = **$31.787/share**

**Multi-contract** (hypothetical 3-contract exercise):
- `broker_cost_basis` = $178.71 per contract
- `opt_qty` = 3 contracts
- `total_premium` = $178.71 × 3 = $536.13
- `stk_qty` = 300 shares
- `premium_per_share` = $536.13 / 300 = $1.787/share ✓

**Cash replay impact**: Zero. Option cash delta changes by +total_premium
(from $0 to broker_cost_basis × opt_qty), stock cash delta changes by
-total_premium (from strike × stk_qty to (strike + premium_per_share) × stk_qty).
Net = $0.

## Scope & Exclusions

### In scope
- Long call exercise (`C;Ex` on option + `Ex;O` on stock BUY)
- Short put assignment (`A;C` on option + `A;O` on stock BUY)
- Short call assignment (`A;C` on option + `A;O` on stock SELL)
- Long put exercise (`C;Ex` on option + `Ex;O` on stock SELL)
- IBKR Flex source only

### Explicitly excluded
- **FOP (futures options)**: `assetCategory == "FOP"`. These exercise into
  futures contracts, not stock. Different multiplier/margin semantics. The Flex
  normalizer classifies FOP separately from OPT. We skip any `is_futures` on
  the stock side.
- **Cash-settled options**: No stock delivery row. The option close has P&L
  directly. No linkage needed (exercise_code present but no matching stock row →
  graceful skip).
- **Non-IBKR brokers**: No `code` field available. Linkage is a no-op.

## Implementation

### Step 1: Feature flag (`settings.py`)

```python
EXERCISE_COST_BASIS_ENABLED = os.getenv("EXERCISE_COST_BASIS_ENABLED", "false").lower() == "true"
```

Add after `OPTION_MULTIPLIER_NAV_ENABLED` (line 143). Default false for safe rollout.

### Step 2: Parse `code` field in Flex normalizer (`ibkr/flex.py`)

**Location**: `normalize_flex_trades()`, lines 265-415.

The Flex XML `code`/`notes` field contains semicolon-separated flags. Known
values from IBKR docs and our statement data:
- `O` = Open, `C` = Close
- `Ex` = Exercise (long option holder exercises)
- `A` = Assignment (short option holder assigned)
- `Ep` = Expiry (expired worthless)
- `P` = Partial fill
- `AEx` = Automatic exercise (dividend-related)
- `MEx` = Manual exercise (dividend-related)
- `GEA` = Exercise or Assignment from offsetting positions
- Others (`CD`, `S0`, `S1`) — not exercise-related; ignored.

**Confirmed in our data** (`U2471778_20250401_20260303.csv`):
- `C;Ex` — SLV 30C option close via exercise
- `Ex;O` — SLV stock open from exercise
- `C;Ep` — SLV 35C option close via expiry

**Not confirmed but documented by IBKR**: `A;C`, `A;O` (assignment codes).
Linkage handles them but they won't activate until we have assignment data.

**Flex query requirement**: The `Notes/Codes` field must be included in the
Flex query configuration. If absent, `raw_code` will be empty and linkage
gracefully skips (no exercise flags set, `option_expired` falls back to the
existing price==0 heuristic as before — no regression from current behavior).

Add extraction after line 384 (account_id):

```python
raw_code = str(_get_attr(trade, "code", "notes", default="") or "").strip()
code_parts = {p.strip().upper() for p in raw_code.split(";") if p.strip()}

# Detect exercise/assignment from code tokens.
# Simple tokens: "Ex", "A", "Ep"
# Compound tokens: "AEx" (auto-exercise), "MEx" (manual exercise),
#                  "GEA" (exercise/assignment from offsetting positions)
_has_exercise_token = any(
    tok in ("EX", "AEX", "MEX") or tok.endswith("EX")
    for tok in code_parts
)
_has_assignment_token = "A" in code_parts or "GEA" in code_parts
is_exercise = _has_exercise_token and not _has_assignment_token
is_assignment = _has_assignment_token
is_exercise_or_assignment = is_exercise or is_assignment
```

Notes:
- `AEx`/`MEx` are exercise variants (holder-side). Map to `is_exercise=True`.
- `GEA` is "Exercise or Assignment from offsetting positions" — map to
  `is_assignment=True` since it's typically IBKR-initiated (short option side).
- The `tok.endswith("EX")` catch-all handles any future IBKR exercise code
  variants that follow the `*Ex` naming pattern.
- `GEA` contains "A" but also implies exercise. We map it to assignment since
  the stock delivery side is the same regardless.

**Stock delivery detection**: The Flex `_map_trade_type()` at line 170 maps
`BUY+O → BUY`, `BUY+C → COVER`, `SELL+O → SHORT`, `SELL+C → SELL`. For
exercise/assignment stock delivery rows:
- Call exercise / Put assignment: stock BUY+O → `trade_type = "BUY"` ✓
- Put exercise / Call assignment: stock SELL+C → `trade_type = "SELL"` ✓

So `stock_from_exercise` must admit both `BUY` and `SELL` (not `SHORT`):

```python
"option_exercised": is_option and is_exercise_or_assignment and trade_type in ("SELL", "COVER"),
"stock_from_exercise": (
    not is_option and not is_futures
    and is_exercise_or_assignment
    and trade_type in ("BUY", "SELL")  # BUY for call ex/put assign, SELL for put ex/call assign
),
"underlying": underlying,  # raw underlyingSymbol for ALL asset types (see Step 6)
"exercise_code": raw_code if is_exercise_or_assignment else None,
```

Fix `option_expired` to exclude both exercises and assignments (line 390):

```python
# BEFORE:
option_expired = is_option and price == 0 and trade_type in ("SELL", "COVER")

# AFTER:
option_expired = (
    is_option and price == 0
    and trade_type in ("SELL", "COVER")
    and not is_exercise_or_assignment
)
```

### Step 3: Pass through fields in IBKRFlexNormalizer (`providers/normalizers/ibkr_flex.py`)

**Location**: `normalize()` method, FIFO dict construction at lines 135-158.

Pass through the new fields from the upstream `txn` dict:

```python
"option_exercised": bool(txn.get("option_exercised")),
"stock_from_exercise": bool(txn.get("stock_from_exercise")),
"underlying": txn.get("underlying"),
"exercise_code": txn.get("exercise_code"),
```

Fix the `option_expired` line (133) to use the upstream value instead of
re-deriving it (prevents exercise/assignment from being mislabeled as expiry):

```python
# BEFORE:
option_expired = is_option and price == 0 and trade_type in ("SELL", "COVER")

# AFTER:
option_expired = bool(txn.get("option_expired", False))
```

### Step 4: Persist exercise metadata in transaction store (`inputs/transaction_store.py`)

The transaction store's `normalized_transactions` table must round-trip the
exercise metadata so that store-backed reads can run `link_option_exercises()`.

**Approach**: Pack exercise fields into the existing `contract_identity` JSONB
column. No schema migration needed.

#### 4a: Store side — add to `contract_identity` before INSERT (line ~473)

Defensively copy before packing to avoid leaking `_` keys into the in-memory
transaction dict (the store layer only shallow-copies txn dicts):

```python
contract_identity = txn.get("contract_identity")
if not isinstance(contract_identity, dict):
    contract_identity = {}
else:
    contract_identity = dict(contract_identity)  # defensive copy

# Pack exercise metadata into contract_identity for round-trip
if txn.get("option_exercised"):
    contract_identity["_option_exercised"] = True
if txn.get("stock_from_exercise"):
    contract_identity["_stock_from_exercise"] = True
if txn.get("underlying"):
    contract_identity["_underlying"] = txn["underlying"]
if txn.get("exercise_code"):
    contract_identity["_exercise_code"] = txn["exercise_code"]

# Only store non-empty
contract_identity = contract_identity or None
```

#### 4b: Load side — unpack from `contract_identity` after SELECT (line ~972)

Unpack the `_`-prefixed exercise fields and **strip them** from
`contract_identity` so downstream consumers (e.g., `engine.py:999` contract
identity comparisons) see a clean dict:

```python
# After contract_identity is parsed from JSONB (line ~970):
_exercise_meta = {}
if isinstance(contract_identity, dict):
    for _key in ("_option_exercised", "_stock_from_exercise", "_underlying", "_exercise_code"):
        val = contract_identity.pop(_key, None)
        if val is not None:
            _exercise_meta[_key] = val

fifo_transactions.append(
    {
        # ... existing fields ...
        "contract_identity": contract_identity or None,
        # Unpack exercise metadata (stripped from contract_identity)
        "option_exercised": bool(_exercise_meta.get("_option_exercised")),
        "stock_from_exercise": bool(_exercise_meta.get("_stock_from_exercise")),
        "underlying": _exercise_meta.get("_underlying"),
        "exercise_code": _exercise_meta.get("_exercise_code"),
    }
)
```

**Why `contract_identity` JSONB instead of new columns**: Avoids a schema
migration. The `_` prefix convention signals these are internal metadata, not
part of the contract spec. The JSONB column is already used for variable
metadata (con_id, expiry, strike, right, multiplier, exchange).

**Re-ingestion**: Existing store data won't have these fields. First ingest
after the code change will upsert with the new metadata. Until then,
store-backed `link_option_exercises()` will no-op (no exercise flags), which
is the same as current behavior.

### Step 5: New linkage module (`trading_analysis/exercise_linkage.py`)

**New file**. ~130 lines.

```python
"""Link option exercises/assignments to stock deliveries for cost basis transfer.

Pre-FIFO pass: adjusts prices on exercise/assignment pairs so that:
- Option close: exit price = broker_cost_basis (≈$0 FIFO P&L)
- Stock delivery: entry/exit price adjusted by premium per share

Called from TradingAnalyzer._normalize_data() and also from store-backed
read paths in engine.py/aggregation.py.

Dimensional note: broker_cost_basis is PER-CONTRACT (from flex.py:375-378).
Total premium = broker_cost_basis × option_quantity.
"""

from __future__ import annotations
from typing import Any
from utils.logging import trading_logger


def link_option_exercises(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Detect exercise/assignment pairs and transfer option premium to stock cost basis.

    Returns a new list with modified copies for linked transactions,
    originals for everything else.
    """
    # Index option exercise/assignment closes.
    # Key: (date_str, account_id, underlying_raw, currency, event_type)
    # event_type is "Ex" or "A" to prevent matching exercises with assignments
    option_exercises: dict[tuple, list[int]] = {}
    # Index stock deliveries from exercise/assignment.
    # Key: (date_str, account_id, underlying_raw, currency, event_type)
    stock_deliveries: dict[tuple, list[int]] = {}

    for i, txn in enumerate(transactions):
        date_str = str(txn.get("date") or "")[:10]
        account = str(txn.get("account_id") or "")
        currency = str(txn.get("currency") or "USD")
        # Classify as exercise or assignment from exercise_code
        # Must match the same logic as flex.py Step 2 detection
        exercise_code = str(txn.get("exercise_code") or "")
        code_parts = {p.strip().upper() for p in exercise_code.split(";") if p.strip()}
        _is_assign = "A" in code_parts or "GEA" in code_parts
        event_type = "A" if _is_assign else "Ex"

        if txn.get("option_exercised"):
            underlying = str(txn.get("underlying") or "").upper()
            if underlying:
                key = (date_str, account, underlying, currency, event_type)
                option_exercises.setdefault(key, []).append(i)

        elif txn.get("stock_from_exercise"):
            underlying = str(txn.get("underlying") or "").upper()
            if underlying:
                key = (date_str, account, underlying, currency, event_type)
                stock_deliveries.setdefault(key, []).append(i)

    if not option_exercises or not stock_deliveries:
        return transactions

    # Match pairs
    result = list(transactions)  # shallow copy of list
    linked_count = 0

    for key, opt_indices in option_exercises.items():
        stk_indices = stock_deliveries.get(key)
        if not stk_indices:
            trading_logger.debug("Exercise linkage: no stock match for key %s", key)
            continue

        for opt_idx in opt_indices:
            opt_txn = transactions[opt_idx]
            broker_cost_basis = opt_txn.get("broker_cost_basis")

            if broker_cost_basis is None or broker_cost_basis <= 0:
                trading_logger.warning(
                    "Exercise linkage: no broker_cost_basis for %s, skipping",
                    opt_txn.get("symbol"),
                )
                continue

            # broker_cost_basis is PER-CONTRACT. Total premium = per_contract × opt_qty.
            opt_qty = abs(float(opt_txn.get("quantity") or 0))
            if opt_qty <= 0:
                continue
            total_premium = broker_cost_basis * opt_qty

            multiplier = float(
                (opt_txn.get("contract_identity") or {}).get("multiplier", 100)
            )
            expected_stock_qty = opt_qty * multiplier

            # For disambiguation: use strike + stock delivery price to match
            opt_strike = float((opt_txn.get("contract_identity") or {}).get("strike", 0) or 0)

            matched_stk_idx = None
            best_score = float("inf")
            for si in stk_indices:
                stk_txn_candidate = transactions[si]
                stk_qty = abs(float(stk_txn_candidate.get("quantity") or 0))
                stk_price = float(stk_txn_candidate.get("price") or 0)

                # Quantity must match (within tolerance for rounding)
                if abs(stk_qty - expected_stock_qty) >= 1.0:
                    continue

                # Score: prefer stock delivery whose price matches option strike
                # (exercise delivers at strike price)
                price_diff = abs(stk_price - opt_strike) if opt_strike > 0 else 0
                if price_diff < best_score:
                    best_score = price_diff
                    matched_stk_idx = si

            if matched_stk_idx is None:
                trading_logger.warning(
                    "Exercise linkage: no qty-matched stock for %s "
                    "(expected %.0f shares, strike=%.2f)",
                    opt_txn.get("symbol"), expected_stock_qty, opt_strike,
                )
                continue

            stk_txn = transactions[matched_stk_idx]
            stk_qty = abs(float(stk_txn.get("quantity") or 0))
            premium_per_share = total_premium / stk_qty if stk_qty > 0 else 0

            # Determine call vs put from contract_identity
            opt_right = str(
                (opt_txn.get("contract_identity") or {}).get("right", "")
            ).upper() or "C"
            stk_side = str(stk_txn.get("type") or "").upper()

            # Adjust option close: set exit price to broker_cost_basis (per-contract)
            # so FIFO computes P&L ≈ $0 for the exercised/assigned contracts
            opt_copy = dict(opt_txn)
            opt_copy["price"] = broker_cost_basis  # per-contract, matches FIFO entry dimension
            opt_copy["exercise_linked"] = True
            opt_copy["exercise_premium_total"] = total_premium
            opt_copy["option_expired"] = False
            result[opt_idx] = opt_copy

            # Adjust stock delivery: add/subtract premium per share
            stk_copy = dict(stk_txn)
            stk_price = float(stk_txn.get("price", 0))

            if opt_right == "C" and stk_side == "BUY":
                # Long call exercise: premium increases stock cost basis
                stk_copy["price"] = stk_price + premium_per_share
            elif opt_right == "P" and stk_side == "BUY":
                # Short put assignment: premium decreases stock cost basis
                stk_copy["price"] = stk_price - premium_per_share
            elif opt_right == "C" and stk_side == "SELL":
                # Short call assignment: premium increases proceeds
                stk_copy["price"] = stk_price + premium_per_share
            elif opt_right == "P" and stk_side == "SELL":
                # Long put exercise: premium decreases proceeds
                stk_copy["price"] = stk_price - premium_per_share
            else:
                trading_logger.warning(
                    "Exercise linkage: unexpected right=%s side=%s for %s, skipping stock adj",
                    opt_right, stk_side, stk_txn.get("symbol"),
                )
                stk_copy = dict(stk_txn)  # revert to original

            stk_copy["exercise_linked"] = True
            stk_copy["exercise_premium_total"] = total_premium
            stk_copy["exercise_premium_per_share"] = premium_per_share
            result[matched_stk_idx] = stk_copy

            linked_count += 1
            stk_indices.remove(matched_stk_idx)  # prevent double-match

            trading_logger.info(
                "Exercise linkage: %s → %s | total_premium $%.2f "
                "(%.4f/share × %d shares) | right=%s side=%s",
                opt_txn.get("symbol"), stk_txn.get("symbol"),
                total_premium, premium_per_share, int(stk_qty),
                opt_right, stk_side,
            )

    if linked_count:
        trading_logger.info("Exercise linkage: %d pairs linked", linked_count)

    return result
```

### Step 6: Integrate — two call sites

Exercise linkage must run consistently regardless of whether trades come from
the live TradingAnalyzer path or the transaction store read path.

#### 6a: TradingAnalyzer (`trading_analysis/analyzer.py`)

**Location**: `_normalize_data()`, **after** `_apply_account_filter()` and
`_deduplicate_transactions()`.

Rationale: Dedup keys include `price`. Running linkage before dedup would
change Flex exercise prices, breaking Flex-vs-Plaid dedup matching. Since
dedup removes the Plaid duplicate (keeping Flex), linkage should run on the
surviving Flex rows after dedup.

```python
self._apply_account_filter()
self._deduplicate_transactions()

# After dedup: link exercise/assignment pairs for cost basis transfer
if settings.EXERCISE_COST_BASIS_ENABLED:
    from trading_analysis.exercise_linkage import link_option_exercises
    self.fifo_transactions = link_option_exercises(self.fifo_transactions)
```

#### 6b: Store-backed read paths (4 call sites)

The transaction store stores raw normalized transactions with exercise metadata
packed into `contract_identity` JSONB (Step 4). The load side unpacks and
strips these fields (Step 4b), so `link_option_exercises()` sees the same
flags as the live path.

Add the linkage call after every `fifo_transactions = list(store_data.get(...))`
across ALL four store-backed read sites:

```python
fifo_transactions = list(store_data.get("fifo_transactions") or [])

# Apply exercise linkage to store-backed transactions
if settings.EXERCISE_COST_BASIS_ENABLED:
    from trading_analysis.exercise_linkage import link_option_exercises
    fifo_transactions = link_option_exercises(fifo_transactions)
```

| File | Location | Context |
|------|----------|---------|
| `core/realized_performance/engine.py` | Line ~347 | Realized performance engine |
| `core/realized_performance/aggregation.py` | Line ~101 | Aggregation entry point |
| `mcp_tools/trading_analysis.py` | Line ~125 | Trading analysis MCP tool |
| `mcp_tools/tax_harvest.py` | Line ~140 | Tax loss harvest MCP tool |

### Step 7: Symbol canonicalization

**Problem**: For non-US stocks (e.g., AT listed on LSE), `flex.py:332-347`
resolves the stock symbol to `AT.L` via `resolve_fmp_ticker()`. But the
option's `underlying` field (line 309-311) uses the raw `underlyingSymbol`
which is just `AT`. If the linkage key for the stock side used `symbol`, it
would be `AT.L` vs the option's `AT` → no match.

**Fix**: In `flex.py`, emit `underlying` on the normalized dict using the
**raw** `underlying` variable (line 309-311) for ALL asset types. This variable
is set from `underlyingSymbol` and is never suffix-resolved.

For options, `underlying` is already the raw `underlyingSymbol` (e.g., `SLV`).
For stocks, `underlying` at line 309 defaults to `symbol` when
`underlyingSymbol` is absent — but this is the raw symbol BEFORE
`resolve_fmp_ticker()` at line 342. The `symbol` variable is only overwritten
at line 342 (for STK rows after exchange lookup). So `underlying` at line 309
captures the pre-resolution value.

**Verification**: In the SLV case:
- Option row: `underlyingSymbol=SLV` → `underlying=SLV` ✓
- Stock row: `underlyingSymbol=SLV` → `underlying=SLV` ✓
- Both match on key `(..., "SLV", ...)` ✓

For AT.L case:
- Option row: `underlyingSymbol=AT` → `underlying=AT`
- Stock row: `underlyingSymbol=AT` → `underlying=AT` (before `symbol` → `AT.L`)
- Both match on `AT` ✓

The linkage module uses `underlying` (not `symbol`) as the match key for both
option and stock sides.

### Step 8: Tests

**New file**: `tests/trading_analysis/test_exercise_linkage.py`

| Test | Description |
|------|-------------|
| `test_basic_call_exercise_single_contract` | 1 call BUY + 1 call SELL (exercised, broker_cost_basis=178.71) + 100 stock BUY. Verify: option price = 178.71, stock price = 30 + 1.787 = 31.787 |
| `test_call_exercise_multi_contract` | 3 calls exercised, broker_cost_basis=178.71/contract. Verify: total_premium = 536.13, stock price = 30 + 536.13/300 = 31.787 |
| `test_put_assignment_stock_buy` | Short put assigned → stock BUY at strike. Verify: stock price = strike - premium_per_share |
| `test_short_call_assignment_stock_sell` | Short call assigned → stock SELL at strike. Verify: stock price = strike + premium_per_share |
| `test_long_put_exercise_stock_sell` | Long put exercised → stock SELL at strike. Verify: stock price = strike - premium_per_share |
| `test_no_exercise_passthrough` | Normal BUY/SELL trades → no modifications |
| `test_missing_broker_cost_basis_skips` | Exercise pair but no broker_cost_basis → skip with warning |
| `test_quantity_mismatch_skips` | Option qty × multiplier ≠ stock qty → skip |
| `test_multiple_exercises_same_day_different_strikes` | Two options on same underlying, different strikes (30C and 35C), exercised same day. Verify: each pairs to correct stock row by strike-price matching |
| `test_cash_settled_option_no_stock` | Option exercise with no matching stock row → graceful skip |
| `test_feature_flag_disabled` | Flag off → no modifications |
| `test_integration_with_fifo` | Full pipeline: linkage → FIFO matcher → verify option P&L ≈ $0 |
| `test_suffix_resolved_symbol_matches` | Option underlying "AT" matches stock with underlying "AT" (not suffix-resolved "AT.L") |
| `test_dedup_then_linkage_order` | Plaid + Flex exercise rows → dedup removes Plaid → linkage adjusts surviving Flex rows |
| `test_store_round_trip` | Exercise metadata packed into contract_identity → stored → loaded → linkage runs correctly |
| `test_compound_exercise_codes` | `AEx`, `MEx` detected as exercise; `GEA` detected as assignment; `CD`/`S0` ignored |
| `test_mixed_exercise_and_assignment_same_day` | Exercise (`Ex`) and assignment (`A`) on same underlying same day → each pairs with its own stock delivery row, no cross-match |

**Update**: `tests/ibkr/test_flex.py`
- Test `option_exercised=True` when code contains `Ex` on option SELL
- Test `option_exercised=True` when code contains `A` on option COVER (assignment)
- Test `stock_from_exercise=True` when code contains `Ex` on stock BUY
- Test `stock_from_exercise=True` when code contains `A` on stock SELL (call assignment)
- Test `option_expired=False` for exercised options (regression)
- Test `option_expired=False` for assigned options (regression)
- Test `underlying` populated for all asset types (raw, pre-resolution)
- Test compound codes: `AEx` → `option_exercised=True`, `MEx` → `option_exercised=True`
- Test `GEA` → `option_exercised=True` (assignment variant)
- Test non-exercise codes (`CD`, `S0`, `P`) → no exercise flags

### Step 9: Verification

Live verification with real SLV data:

```bash
EXERCISE_COST_BASIS_ENABLED=true python -c "
from mcp_tools.performance import get_performance
result = get_performance(mode='realized', source='ibkr_flex', start_date='2025-04-01')
# Check SLV_C30 option P&L: should be ~+$988 (was +$809)
# Check SLV stock cost basis via trading analysis
"
```

Expected changes:
- `SLV_C30_250620` realized P&L: +$809 → ~+$988 (+$179)
- `SLV` stock cost basis: $30.00 → $31.787/share
- `SLV` stock unrealized P&L: decreases by ~$179
- Net lot P&L: unchanged
- Lot P&L gap vs IBKR: narrows by $179

## Edge Cases

| Case | Handling |
|------|----------|
| **`code` field missing from Flex query** | `raw_code` = empty → no exercise flags → `option_expired` falls back to existing price==0 heuristic → identical to current behavior (no regression). |
| **`broker_cost_basis` unavailable** | Skip linkage for that pair, log warning. No degradation. |
| **Multi-contract exercise** | `total_premium = broker_cost_basis × opt_qty`. Dimensionally correct. |
| **Multiple exercises same day, same underlying, different strikes** | Match by qty + strike-to-price scoring. Stock delivery at $30 matches $30-strike option, not $35-strike. |
| **Mixed exercise + assignment same day** | Key includes `event_type` ("Ex" vs "A") from `exercise_code`. Exercises only match exercise stock rows; assignments only match assignment stock rows. No cross-matching. |
| **Multiple exercises same day, same underlying, SAME strike** | `broker_cost_basis` can differ if lots were opened at different prices. First-match is arbitrary — but this scenario requires buying and exercising the same option contract on the same day in separate fills, which IBKR would consolidate into one exercise row. Not a real concern. |
| **Partial exercise (3 of 12 contracts)** | Only the exercised contracts have `C;Ex` code. Market-sold contracts have plain `C`. Flex gives separate rows — linkage only touches `C;Ex` rows. |
| **Short call assignment** | Code `A;C` on option, `A;O` on stock. `is_assignment=True` triggers. Stock side = SELL (from `_map_trade_type(SELL, C) → SELL`). `right=C` + `side=SELL` → premium increases stock proceeds. |
| **Long put exercise** | Code `C;Ex` on option, `Ex;O` on stock. Stock side = SELL (from `_map_trade_type(SELL, C) → SELL`). `right=P` + `side=SELL` → premium decreases stock proceeds. |
| **Short put assignment** | Code `A;C` on option, `A;O` on stock BUY (from `_map_trade_type(BUY, O) → BUY`). `right=P` + `side=BUY` → premium decreases stock cost. |
| **Cash-settled option** | Option exercise with no stock delivery → no match in `stock_deliveries` → graceful skip. |
| **FOP (futures options)** | `is_futures` check in `stock_from_exercise` flag prevents futures delivery rows from entering the stock index. FOP not in scope. |
| **Non-IBKR brokers** | No `code` field → no exercise flags → linkage is a no-op. |
| **Dedup interaction** | Linkage runs AFTER dedup. Plaid duplicates removed first. Surviving Flex rows then get linked. No price-based dedup key corruption. |
| **Store-backed reads** | Exercise metadata packed into `contract_identity` JSONB (Step 4). Unpacked on load. `link_option_exercises()` called in both `engine.py` and `aggregation.py`. |
| **Stale store data (pre-code-change)** | No exercise fields in `contract_identity` → linkage no-ops → same as current behavior. First re-ingest populates the fields. |
| **Symbol suffix resolution** | Linkage key uses `underlying` (raw IBKR `underlyingSymbol`) for both option and stock sides. Suffix-resolved `symbol` not used in matching. |
| **Cash replay impact** | Net zero. Option cash Δ = +total_premium, stock cash Δ = -total_premium. |

## Review Findings — Resolution Tracker

| # | Finding | v1 | v2 | v3 | Resolution |
|---|---------|----|----|-----|------------|
| 1 | Multi-contract math: `broker_cost_basis` is per-contract | FAIL | PASS | PASS | `total_premium = broker_cost_basis × opt_qty` |
| 2 | Assignment coverage: stock SELL quadrants | FAIL | FAIL | PASS | `stock_from_exercise` admits `BUY` and `SELL`. Four-way matrix. |
| 3 | Dedup breakage | FAIL | PASS | PASS | Linkage after dedup |
| 4 | Store-backed reads: metadata not persisted | CONCERN | FAIL | FAIL | v4: Pack into `contract_identity` JSONB + defensive copy + strip on load. All 4 store-read sites get linkage call. |
| 5 | Weak pair matching + compound codes | CONCERN | CONCERN | CONCERN | v5: Strike-to-price scoring + `event_type` in key + compound code detection (`AEx`, `MEx`, `GEA`). `tok.endswith("EX")` catch-all for future variants. |
| 6 | `code` field not guaranteed | CONCERN | CONCERN | PASS | No regression: falls back to existing price==0 heuristic. |
| 7 | FOP exclusion | CONCERN | PASS | PASS | `is_futures` gate |
| 8 | Symbol canonicalization | — | CONCERN | PASS | Step 7: `underlying` = raw `underlyingSymbol` for all types. |
| 9 | `contract_identity` leakage from exercise fields | — | — | CONCERN | v4: Strip `_`-prefixed keys on load + defensive copy on store. |
| 10 | Incomplete store-read sites (trading_analysis, tax_harvest) | — | — | FAIL | v4: All 4 sites covered in Step 6b. |

## Files Modified

| File | Change | Lines |
|------|--------|-------|
| `settings.py` | Add `EXERCISE_COST_BASIS_ENABLED` flag | ~1 line |
| `ibkr/flex.py` | Parse `code` field, emit exercise flags + `underlying` for all types | ~15 lines |
| `providers/normalizers/ibkr_flex.py` | Pass through exercise fields, use upstream `option_expired` | ~8 lines |
| `inputs/transaction_store.py` | Pack/unpack exercise metadata in `contract_identity` JSONB | ~20 lines |
| `trading_analysis/exercise_linkage.py` | **NEW** — linkage algorithm | ~130 lines |
| `trading_analysis/analyzer.py` | Call `link_option_exercises()` after dedup | ~3 lines |
| `core/realized_performance/engine.py` | Call `link_option_exercises()` on store-backed reads | ~3 lines |
| `core/realized_performance/aggregation.py` | Call `link_option_exercises()` on store-backed reads | ~3 lines |
| `mcp_tools/trading_analysis.py` | Call `link_option_exercises()` on store-backed reads | ~3 lines |
| `mcp_tools/tax_harvest.py` | Call `link_option_exercises()` on store-backed reads | ~3 lines |
| `tests/trading_analysis/test_exercise_linkage.py` | **NEW** — 15 tests | ~350 lines |
| `tests/ibkr/test_flex.py` | Add exercise/assignment flag tests | ~60 lines |

## Not Changing

- `trading_analysis/fifo_matcher.py` — no changes needed (pre-FIFO adjustment)
- `core/realized_performance/nav.py` — cash replay net impact is zero
- Non-IBKR normalizers — no exercise detection available
- Transaction store DB schema — JSONB column absorbs new fields
