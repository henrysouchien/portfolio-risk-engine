# Fix: Handle Schwab RECEIVE_AND_DELIVER as Position Exit

## Context

Account 252 shows +273.92% TWR vs broker +10.65%. Root cause: 4 GLBE shares bought Aug-Oct 2024, then transferred out via `RECEIVE_AND_DELIVER` on Oct 17 2024. The normalizer skips this transaction type entirely (not TRADE, not DIVIDEND_OR_INTEREST → `_is_trade_candidate()` returns False at line 822). Position_timeline never gets an exit event, so `compute_monthly_nav()` keeps valuing 4 phantom GLBE shares at market price. GLBE's ~60% rally in Nov 2024 produces impossible +103% monthly returns on a $80 cash base, compounding to +274%.

There is exactly 1 RECEIVE_AND_DELIVER transaction across all Schwab data. It has:
- `type: "RECEIVE_AND_DELIVER"`, `amount: -4.0` (outbound), `price: 0.0`, `netAmount: 0.0`
- `instrument.closingPrice: 34.3`, `instrument.symbol: "GLBE"`

## Changes

### 1. Add shared `_resolve_receive_deliver()` helper in normalizer (near line 295)

**File:** `providers/normalizers/schwab.py`

This single helper resolves action, quantity, price, and instrument for RECEIVE_AND_DELIVER transactions. Both the normalizer and flow parser use it, ensuring identical leg selection and valuation logic.

```python
def _resolve_receive_deliver(
    txn: dict[str, Any],
) -> tuple[str, float, float, dict[str, Any]] | None:
    """Resolve action/quantity/price/instrument for RECEIVE_AND_DELIVER.

    Returns ``(action, quantity, price, instrument)`` or ``None`` if no
    qualifying security leg is found.  Used by both the normalizer (FIFO
    emission) and the flow parser (matching cash-flow emission).

    Leg selection: first non-currency transfer item with non-zero amount.
    Action: ``"SELL"`` if amount < 0 (shares out), ``"BUY"`` if amount > 0.
    Price: transfer-item price → closingPrice fallback → 0.0.
    """
    qualifying_count = 0
    result = None
    for row in _iter_transfer_items(txn):
        instrument = _extract_item_instrument(row)
        if _is_currency_instrument(instrument):
            continue
        raw_amount = safe_float(row.get("amount"))
        if raw_amount == 0:
            continue
        qualifying_count += 1
        if result is not None:
            # Already found first qualifying leg — just counting.
            continue
        action = "SELL" if raw_amount < 0 else "BUY"
        quantity = abs(raw_amount)
        price = _extract_price_from_row(row, quantity)
        if price <= 0:
            closing = safe_float(instrument.get("closingPrice"))
            if closing > 0:
                price = closing
        # Return even if price == 0 — action/quantity are still valid
        # for position tracking. Phantom position is worse than zero-price exit.
        result = (action, quantity, price, instrument)
    if qualifying_count > 1:
        trading_logger.warning(
            "RECEIVE_AND_DELIVER has %d qualifying legs; using first: id=%s",
            qualifying_count,
            txn.get("activityId") or txn.get("transactionId") or txn.get("id"),
        )
    return result
```

Key design choices:
- **Single leg selection rule**: first non-currency leg with non-zero amount (same for normalizer and flow)
- **Returns instrument**: normalizer uses it for symbol extraction — no separate `_select_trade_leg()` call
- **closingPrice fallback baked in**: scoped to this helper only, not general
- **Returns even if price=0**: a zero-price exit still removes the position from timeline, which is the primary goal. Phantom position (+274% return) is much worse than a zero-value exit (wrong P&L but correct position tracking). When price=0, the normalizer emits the SELL and the flow emits $0 withdrawal — both consistent.
- **Multi-leg warning**: counts qualifying legs and logs if > 1
- **Returns None only if no qualifying leg**: both normalizer and flow skip the row

### 2. Update `_is_trade_candidate()` to recognize RECEIVE_AND_DELIVER (~line 296)

**File:** `providers/normalizers/schwab.py`

```python
def _is_trade_candidate(txn: dict[str, Any]) -> tuple[bool, str | None]:
    family = _normalize_token(txn.get("type"))
    action = _resolve_trade_action(txn)
    if family == "TRADE" or action is not None:
        return True, action
    if family == "RECEIVE_AND_DELIVER":
        resolved = _resolve_receive_deliver(txn)
        return (True, resolved[0]) if resolved else (False, None)
    return False, None
```

Note: `_resolve_trade_action()` checks description for BUY/SELL keywords. If a RECEIVE_AND_DELIVER description happens to contain "BUY" or "SELL", `_resolve_trade_action` would return an action, and `_is_trade_candidate` would return `(True, action)` via the first branch. This is handled by change #3: the main loop checks `family == "RECEIVE_AND_DELIVER"` BEFORE using the standard trade path, so the action from `_is_trade_candidate` is ignored for these rows.

### 3. Add RECEIVE_AND_DELIVER-specific path in main loop (~line 868)

**File:** `providers/normalizers/schwab.py`

For RECEIVE_AND_DELIVER, the normalizer uses the shared helper exclusively — not `_select_trade_leg()`, not the standard price extraction. This path is checked **by family**, not by action, so it runs regardless of how `_is_trade_candidate` resolved the action.

Insert after the `_is_trade_candidate` check at line 822 and before `trade_type` resolution at line 868:

```python
            is_trade, action = _is_trade_candidate(txn)
            if not is_trade:
                continue

            # RECEIVE_AND_DELIVER: dedicated path using shared resolver.
            # Checked by family (not action) to ensure we always use
            # _resolve_receive_deliver() regardless of how _is_trade_candidate
            # resolved the action (e.g., if description contained "SELL").
            if _normalize_token(txn.get("type")) == "RECEIVE_AND_DELIVER":
                resolved = _resolve_receive_deliver(txn)
                if not resolved:
                    continue
                rd_action, quantity, price, rd_instrument = resolved
                if _is_currency_instrument(rd_instrument):
                    continue
                rd_trade_type = SCHWAB_ACTION_TO_TRADE_TYPE.get(rd_action)
                if rd_trade_type is None:
                    continue
                symbol = str(rd_instrument.get("symbol") or "UNKNOWN").strip().upper()
                if not symbol:
                    symbol = "UNKNOWN"
                if quantity <= 0:
                    continue
                if price <= 0:
                    trading_logger.warning(
                        "RECEIVE_AND_DELIVER has no price — emitting with price=0: "
                        "symbol=%s qty=%s id=%s",
                        symbol, quantity,
                        txn.get("activityId") or txn.get("transactionId") or txn.get("id"),
                    )
                fee = _extract_fee(txn)
                currency = _extract_currency(txn, None)
                amount = abs(quantity * price)
                instrument_type = _instrument_type_for(rd_instrument.get("assetType"))

                trades.append(
                    NormalizedTrade(
                        symbol=symbol,
                        trade_type=rd_trade_type,
                        date=when,
                        units=quantity,
                        price=price,
                        amount=amount,
                        fee=fee,
                        source="schwab",
                        institution=institution,
                        account_id=account_id,
                        account_name=account_name,
                    )
                )
                fifo_transactions.append(
                    {
                        "symbol": symbol,
                        "type": rd_trade_type.value,
                        "date": when,
                        "quantity": quantity,
                        "price": price,
                        "fee": fee,
                        "currency": currency,
                        "source": "schwab",
                        "transaction_id": txn.get("activityId") or txn.get("transactionId") or txn.get("id"),
                        "account_id": account_id or "",
                        "account_name": account_name or "",
                        "_institution": institution,
                        "instrument_type": instrument_type,
                        "contract_identity": None,
                    }
                )
                continue

            # --- Existing action-resolution and standard trade path below ---
            if action is None:
```

Key points:
- **Does NOT skip on price=0**: logs warning but emits the SELL. Position exits timeline. Cash impact is $0 on both sides (normalizer SELL adds $0, flow withdrawal subtracts $0). Consistent.
- **Uses `rd_action` from helper, not `action` from `_is_trade_candidate`**: ensures action is from `_resolve_receive_deliver()` even if `_resolve_trade_action` matched a description keyword.
- **Computes `rd_trade_type` from `rd_action`**: independent of the outer `action` variable.

### 4. Exclude RECEIVE_AND_DELIVER from description map (~line 522)

**File:** `providers/normalizers/schwab.py`

In `_build_trade_description_map()`, add RECEIVE_AND_DELIVER to the skip list. Transfer rows are not reliable symbol hints:

```python
            if action is None and family == "TRADE" and safe_float(txn.get("netAmount")) == 0:
                continue

            if family == "RECEIVE_AND_DELIVER":
                continue
```

### 5. Add matching cash-flow emission for RECEIVE_AND_DELIVER

**File:** `providers/flows/schwab.py`

**Why this is needed:** The normalizer SELL causes cash replay to add proceeds (quantity × price). But RECEIVE_AND_DELIVER has `netAmount: 0` — no cash actually moved. Without a matching flow, cash inflates.

**Bidirectional handling** (mirrors System Transfer BUY → contribution pattern at lines 269-281):
- Outbound (SELL): normalizer adds cash → flow emits withdrawal → cash neutral
- Inbound (BUY): normalizer subtracts cash → flow emits contribution → cash neutral

Add import of the shared helper (line 32):
```python
from providers.normalizers.schwab import (
    SCHWAB_TRADE_ACTIONS,
    _extract_item_instrument,
    _extract_price_from_row,
    _extract_quantity,
    _is_currency_instrument,
    _resolve_receive_deliver,   # NEW — shared helper
    _select_trade_leg,
)
```

In `extract_schwab_flow_events()`, add handling **before** the existing RECEIVE_AND_DELIVER path at line 332:

```python
        # RECEIVE_AND_DELIVER with no cash impact: shares move in/out with
        # netAmount=0.  Normalizer emits BUY or SELL (affecting cash replay).
        # Emit a matching contribution (for BUY) or withdrawal (for SELL)
        # to keep cash neutral.  Uses the same shared resolver as the
        # normalizer to guarantee identical leg selection and valuation.
        # Symmetric with System Transfer BUY → contribution (lines 269-281).
        if row_type == "RECEIVE_AND_DELIVER" and raw_amount == 0:
            resolved = _resolve_receive_deliver(row)
            if resolved:
                action, quantity, price, _instrument = resolved
                transfer_value = abs(quantity * price)
                if transfer_value > 0:
                    if action == "SELL":
                        event = _flow_event(
                            row,
                            amount=-transfer_value,
                            flow_type="withdrawal",
                            is_external_flow=True,
                            transfer_cash_confirmed=True,
                        )
                    else:  # BUY
                        event = _flow_event(
                            row,
                            amount=transfer_value,
                            flow_type="contribution",
                            is_external_flow=True,
                            transfer_cash_confirmed=True,
                        )
                    if event:
                        events.append(event)
                # If transfer_value == 0 (price was 0), no flow needed —
                # normalizer SELL also adds $0 to cash. Both sides consistent.
            continue
```

**When price=0:** normalizer emits SELL with price=0, adding $0 to cash replay. Flow emits nothing (transfer_value=0). Net: position exits, cash unchanged. Consistent.

**When netAmount != 0:** falls through to existing `_classify_transfer_like_flow()` at line 332. Flow amount based on actual netAmount. Matches existing System Transfer pattern.

### 6. Tests

**File:** `tests/providers/test_schwab_normalizer.py`

Shared helper tests:
1. `_resolve_receive_deliver` with negative amount → returns `("SELL", qty, closingPrice, instrument)`
2. `_resolve_receive_deliver` with positive amount → returns `("BUY", qty, closingPrice, instrument)`
3. `_resolve_receive_deliver` with row price > 0 → uses row price, not closingPrice
4. `_resolve_receive_deliver` with price=0 and no closingPrice → returns `(action, qty, 0.0, instrument)`
5. `_resolve_receive_deliver` with no security leg → returns None
6. `_resolve_receive_deliver` with currency-only legs → returns None
7. `_resolve_receive_deliver` with multiple qualifying legs → logs warning, returns first

Normalizer integration tests:
8. RECEIVE_AND_DELIVER with negative amount → emits SELL FIFO transaction with closingPrice
9. RECEIVE_AND_DELIVER with positive amount → emits BUY FIFO transaction
10. RECEIVE_AND_DELIVER with price=0 → still emits FIFO transaction (with warning log)
11. RECEIVE_AND_DELIVER with description containing "SELL" → still uses helper action, not `_resolve_trade_action`
12. `_is_trade_candidate` recognizes RECEIVE_AND_DELIVER family
13. RECEIVE_AND_DELIVER excluded from description map

Flow integration tests:
14. Outbound RECEIVE_AND_DELIVER (netAmount=0) → emits withdrawal flow equal to qty × closingPrice
15. Inbound RECEIVE_AND_DELIVER (netAmount=0) → emits contribution flow equal to qty × closingPrice
16. RECEIVE_AND_DELIVER with price=0 + netAmount=0 → no flow event (transfer_value=0)
17. RECEIVE_AND_DELIVER with netAmount != 0 → falls through to `_classify_transfer_like_flow`
18. RECEIVE_AND_DELIVER with no qualifying leg + netAmount=0 → no event emitted

Symmetry tests:
19. Normalizer and flow emit identical value for the same RECEIVE_AND_DELIVER row

## Files to Modify

| File | Change |
|------|--------|
| `providers/normalizers/schwab.py` | Add `_resolve_receive_deliver()`, update `_is_trade_candidate()`, add dedicated main loop path, exclude from description map |
| `providers/flows/schwab.py` | Add bidirectional flow emission using shared helper, import `_resolve_receive_deliver` |
| `tests/providers/test_schwab_normalizer.py` | Add 19 tests (helper, normalizer, flow, symmetry) |

## What NOT to Change

- No changes to FIFO matcher — it already handles SELL correctly
- No changes to `build_position_timeline()` — once SELL appears in fifo_transactions, GLBE will have an exit event
- No changes to TWR or NAV computation
- No changes to `_classify_transfer_like_flow()` — the new code handles the netAmount=0 case before it reaches that function

## Codex Review Findings

### Round 1

| ID | Severity | Issue | Resolution |
|----|----------|-------|------------|
| R1 | HIGH | Cash replay imbalance — SELL adds proceeds but no matching withdrawal | FIXED: bidirectional flow emission (change #5) |
| R2 | MEDIUM | closingPrice fallback too broad | FIXED: scoped inside `_resolve_receive_deliver()` only |
| R3 | MEDIUM | Multi-leg fragility | ACCEPTED: first leg wins, warning log added (change #1) |
| R4 | LOW | Description map pollution | FIXED: explicit skip (change #4) |

### Round 2

| ID | Severity | Issue | Resolution |
|----|----------|-------|------------|
| R5 | HIGH | Inbound zero-cash path missing | FIXED: bidirectional handling |
| R6 | HIGH | Symbol/instrument from `_select_trade_leg()` could differ | FIXED: helper returns instrument, normalizer uses it (change #3) |
| R7 | MEDIUM | Action-selection mismatch | FIXED: dedicated path uses `rd_action` from helper, checks by family not action |
| R8 | MEDIUM | Price=0 gates trade candidacy → phantom position | FIXED: price=0 no longer blocks emission — logs warning, emits with price=0 |
| R9 | MEDIUM | netAmount != 0 asymmetry | ACCEPTED: matches existing System Transfer pattern |
| R10 | LOW | Description map pollution (confirmed) | FIXED: explicit skip (change #4) |

### Round 3

| ID | Severity | Issue | Resolution |
|----|----------|-------|------------|
| R11 | HIGH | price=0 still skipped in main loop | FIXED: removed `continue` on price=0, log warning only (change #3) |
| R12 | MEDIUM | Action precedence — description could override helper action | FIXED: dedicated path checks by family, uses `rd_action` exclusively |
| R13 | LOW | Multi-leg warning missing from helper code | FIXED: added counting loop + warning log (change #1) |
| R14 | LOW | Unused `_iter_transfer_items` import | FIXED: removed from import list (change #5) |

## Verification

1. **Run existing tests:** `python3 -m pytest tests/providers/test_schwab_normalizer.py -x -q`
2. **Run realized perf tests:** `python3 -m pytest tests/core/test_realized_performance_analysis.py tests/core/test_synthetic_twr_flows.py -x -q`
3. **Live verification — Account 252:**
   ```
   get_performance(mode='realized', source='schwab', account='25524252', format='summary')
   ```
   - Before: +273.92%. After: should be much closer to +10.65%
   - GLBE should no longer appear in position_timeline after Oct 17
4. **Live verification — Schwab aggregate:**
   ```
   get_performance(mode='realized', source='schwab', format='summary')
   ```
   - Before: +22.13%. Should move significantly toward -8.29%
5. **Regression check — other sources unaffected:**
   - IBKR and Plaid returns should not change
