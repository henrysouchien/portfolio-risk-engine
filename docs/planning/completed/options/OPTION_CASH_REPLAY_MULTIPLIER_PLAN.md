# Option Cash Replay Multiplier Fix

**Date:** 2026-03-05
**Status:** Planning
**Prerequisite:** Option Multiplier NAV Fix (commits `62110090`, `e2c33f5f`) — price_cache now has per-contract prices for options

## Context

Cash replay in `nav.py` `derive_cash_and_external_flows()` computes cash impact of trades as `price * quantity`. For non-IBKR option trades, `price` is per-share (e.g. $2.50) and `quantity` is contracts (e.g. 5), so cash impact = $12.50 instead of $1,250. IBKR Flex option trades already have per-contract prices (×100 at `flex.py:356`).

With the NAV fix (commits `62110090`/`e2c33f5f`), option position *values* in NAV are now correct (price_cache has per-contract prices). But cash replay still undervalues option trades by 100x, causing NAV drift (positions correct, cash wrong).

**Goal:** Apply contract multiplier to `price * quantity` in cash replay for non-IBKR option trades. Gated by the same `OPTION_MULTIPLIER_NAV_ENABLED` flag.

---

## Fix

### Change 1: Thread `instrument_type`, `source`, `multiplier` into event dict — `nav.py` ~line 157

The event dict built from `fifo_transactions` currently has: `date`, `event_type`, `price`, `quantity`, `fee`, `currency`, `is_futures`, `symbol`. Add three fields:

```python
events.append(
    {
        "date": date,
        "event_type": str(txn.get("type", "")).upper(),
        "price": _helpers._as_float(txn.get("price"), 0.0),
        "quantity": abs(_helpers._as_float(txn.get("quantity"), 0.0)),
        "fee": abs(_helpers._as_float(txn.get("fee"), 0.0)),
        "currency": str(txn.get("currency") or "USD").upper(),
        "is_futures": is_futures,
        "symbol": symbol,
        # New fields for option multiplier fix:
        "instrument_type": instrument_type,
        "source": str(txn.get("source") or "").strip().lower(),
        "multiplier": _helpers._as_float(
            (txn.get("contract_identity") or {}).get("multiplier"), 1.0
        ),
    }
)
```

`instrument_type` is already computed at line 140. `source` and `contract_identity` are on the `txn` dict from normalizers.

### Change 2: Apply multiplier in cash replay — `nav.py` ~lines 287-294

**Important:** The `else` branch handles BUY/SELL/SHORT/COVER but also INCOME, PROVIDER_FLOW, and FUTURES_MTM events which do NOT have `price`/`quantity` keys. The multiplier logic must only apply to trade event types (BUY/SELL/SHORT/COVER).

Compute `pq` only for trade types, applying multiplier for non-IBKR option trades:

```python
        else:
            if event_type in ("BUY", "SELL", "SHORT", "COVER"):
                pq = event["price"] * event["quantity"]
                # Apply option multiplier for non-IBKR sources
                # (IBKR Flex trade prices already per-contract at flex.py:356).
                if (
                    OPTION_MULTIPLIER_NAV_ENABLED
                    and event.get("instrument_type") == "option"
                    and event.get("source") != "ibkr_flex"
                ):
                    mult = _helpers._as_float(event.get("multiplier"), 1.0)
                    if np.isfinite(mult) and mult > 1:
                        pq = pq * mult

                if event_type == "BUY":
                    cash -= (pq + event["fee"]) * fx
                elif event_type == "SELL":
                    cash += (pq - event["fee"]) * fx
                elif event_type == "SHORT":
                    cash += (pq - event["fee"]) * fx
                elif event_type == "COVER":
                    cash -= (pq + event["fee"]) * fx
            elif event_type == "INCOME":
                cash += event.get("amount", 0.0) * fx
            elif event_type == "PROVIDER_FLOW":
                ...  # unchanged
            elif event_type == "FUTURES_MTM":
                ...  # unchanged
```

### Change 3: Also fix `unpriceable_suppressed_usd` — `nav.py` ~line 281

The suppressed-symbol cash tracking at line 281 also uses `price * quantity`:
```python
unpriceable_suppressed_usd += abs(event["price"] * event["quantity"] * fx)
```
Apply the same multiplier logic here for consistency.

### Import

Add `from settings import OPTION_MULTIPLIER_NAV_ENABLED` at top of `nav.py`.

---

## Files Changed

| File | Change |
|------|--------|
| `core/realized_performance/nav.py` | +15 lines — 3 fields in event dict, multiplier in cash replay + import |

Only 1 file. No new feature flag needed (reuses `OPTION_MULTIPLIER_NAV_ENABLED`).

**Known limitation:** SnapTrade fallback symbols that can't be parsed produce option trades with `contract_identity=None`, so multiplier defaults to 1.0 and those trades remain per-share. This is acceptable degradation — those options also can't be priced (no contract_identity → empty price series → valued at $0 in NAV), so the cash mismatch is irrelevant.

---

## What This Completes

With this fix, `OPTION_MULTIPLIER_NAV_ENABLED=true` is safe to enable in production:
- Price cache: per-contract (fixed in `62110090`)
- Cash replay: per-contract (this fix)
- NAV positions: correct (uses price_cache)
- Cash: correct (uses replay)

---

## Verification

1. `python3 -m pytest tests/` — all existing tests pass (flag off = no behavior change)
2. With `OPTION_MULTIPLIER_NAV_ENABLED=true`: Simulate cash replay with a Schwab option trade — verify cash impact is $250 (not $2.50) for a $2.50 premium × 1 contract
3. Verify IBKR Flex option trades are NOT double-multiplied (source = `ibkr_flex` → skip)
4. Verify non-option trades are unaffected (`instrument_type != "option"` → skip)

---

## Reference Files

- `core/realized_performance/nav.py` — `derive_cash_and_external_flows()` (lines 56-310), `compute_monthly_nav()` (lines 450-506)
- `core/realized_performance/_helpers.py` — `_as_float()`, `_infer_instrument_type_from_transaction()`
- `ibkr/flex.py` — Line 356: IBKR Flex trade prices already ×multiplier for options
- `settings.py` — `OPTION_MULTIPLIER_NAV_ENABLED` (already exists)
