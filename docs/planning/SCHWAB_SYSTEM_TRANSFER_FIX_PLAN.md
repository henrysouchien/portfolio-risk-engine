# Fix G (v2): Schwab System Transfer + Per-Symbol Inception for Single-Account

## Context

Fix G v1 (committed as `cb4b1237`, reverted in `14163072`) correctly emitted paired BUY + contribution for Schwab "System transfer" TRADE rows, but the BUY coexisted with existing synthetic positions instead of replacing them. This caused double-counting: the synthetic position inflated NAV, and the contribution added external capital that didn't correspond to any NAV increase.

**Root cause of v1 failure**: Per-symbol inception (Fix F, commit `86be4eb0`) was only enabled in the aggregated multi-account path (`_analyze_realized_performance_account_aggregated`, line 5658). In single-account runs, synthetics still used global inception regardless of `earliest_txn_by_symbol`. So a System transfer BUY at Aug 24, 2024 created a FIFO entry, but the synthetic for the same symbol was ALSO placed at global inception — both coexist, double-counting the position.

**v1 results (before revert):**
- Account 013 2025: moved from -3.49% to 0.00% (worse, wrong direction vs broker -14.69%)
- Schwab combined: moved from +17.67% to +23.13% (worse)
- Root cause: $88.75 contribution recorded but NAV didn't increase (synthetic already covered)

### Background: System Transfer Data

Schwab "System transfer" TRADE rows represent positions transferred between accounts (e.g., TD Ameritrade → Schwab migration). Raw structure:

```json
{
  "type": "TRADE", "netAmount": 0.0, "description": "System transfer",
  "transferItems": [{
    "instrument": {"symbol": "GLBE", "assetType": "EQUITY"},
    "amount": 2.0, "cost": 61.5, "price": 30.75
  }]
}
```

**Both the normalizer and flow parser skip these rows:**
- Normalizer (`providers/normalizers/schwab.py:838-843`): skips TRADE with no action + zero netAmount
- Flow parser (`providers/flows/schwab.py:36`): skips all TRADE rows via `_IGNORE_TYPES`

**Affected accounts:**
- Account 013: 4 transfers on Aug 24, 2024 (GLBE, CPPMF, LIFFF, DSU = **$88.75** total)
- Account 165: 5 transfers on Aug 24, 2024 (LIFFF, MSCI, PCTY, DSU, GLBE = **$18,342** total)
- Account 252: No System transfer rows
- All 9 System transfer rows are single-leg (verified — no multi-leg transfers exist)

## Approach

Three coordinated changes:

1. **Enable per-symbol inception for Schwab single-account runs** — so BUY entries suppress synthetics for the same symbol
2. **Normalizer**: Emit BUY at transfer cost for System transfer TRADE rows
3. **Flow parser**: Emit external contribution for the same cost

**Why all three are needed together:**
- BUY without per-symbol inception → double-counts (v1 failure)
- Per-symbol inception without BUY → no change (symbols still have no `earliest_txn_by_symbol` entry)
- BUY + contribution without per-symbol inception → contribution inflates denominator without NAV increase

## Files to Modify

| File | Change |
|------|--------|
| `core/realized_performance_analysis.py` | Pass `use_per_symbol_inception=True` for Schwab in single-scope call |
| `providers/normalizers/schwab.py` | Lines 837-843: emit BUY for System transfer |
| `providers/flows/schwab.py` | Before line 237: emit contribution for System transfer |

## Implementation

### Change 1: Enable per-symbol inception for Schwab single-account runs

**File:** `core/realized_performance_analysis.py`

**Location:** `analyze_realized_performance()` (the public dispatcher, line ~5715)

Currently the single-scope call at line ~5740 doesn't pass `use_per_symbol_inception`. Add it conditionally for Schwab:

```python
# Before the single-scope call, determine if per-symbol inception is safe:
is_schwab = (
    (institution is not None and match_institution(institution, "schwab"))
    or source == "schwab"
)

return _analyze_realized_performance_single_scope(
    ...
    use_per_symbol_inception=is_schwab,
)
```

**Safety analysis:**
- IBKR: `is_schwab=False` → `use_per_symbol_inception=False` → completely unchanged
- No shared state: parameter is per-call, not module-global
- Fallback preserved: symbols WITHOUT `earliest_txn_by_symbol` entry still use global inception
- The parameter is already accepted by `_analyze_realized_performance_single_scope` (line 2857) and threaded to both `build_position_timeline` calls (lines 3269, 4071)
- IBKR was the reason Fix F was restricted to aggregated path only (limited Flex query window) — Schwab has complete transaction history, so per-symbol inception is safe

### Change 2: Normalizer — emit BUY for System transfers

**File:** `providers/normalizers/schwab.py`

**Location:** Lines 837-843 (the `else` branch when `net == 0`)

Replace the unconditional skip: check for valid transfer leg via `_select_trade_leg(txn)`, verify non-currency instrument with positive quantity and price, then set `action = "BUY"` to fall through to existing pipeline.

```python
else:
    # System/account transfer: positions received with no cash impact.
    # Emit as BUY so the symbol appears in FIFO history.
    # A matching contribution from the flow parser neutralizes cash.
    transfer_leg = _select_trade_leg(txn)
    if transfer_leg is not None:
        leg_instrument = _extract_item_instrument(transfer_leg)
        if not _is_currency_instrument(leg_instrument):
            quantity = _extract_quantity(txn, transfer_leg)
            if quantity > 0:
                price = _extract_price_from_row(transfer_leg, quantity)
                if price > 0:
                    action = "BUY"
    if action is None:
        trading_logger.debug(
            "Skipping Schwab TRADE row with no action and zero netAmount: id=%s description=%s",
            txn.get("activityId") or txn.get("transactionId") or txn.get("id"),
            txn.get("description"),
        )
        continue
```

**`_extract_price` fallback safety:** `_extract_price(txn, quantity, trade_leg)` (line 876) has a fallback to `netAmount / quantity` which gives 0 for System transfers. But `_extract_price_from_row` returns the transfer item's `price` field first. The `price > 0` guard ensures we only set `action = "BUY"` when the price is valid.

**`_build_trade_description_map` (lines 522-525):** Leave unchanged — "System transfer" description is shared across multiple symbols.

### Change 3: Flow parser — emit contribution for System transfers

**File:** `providers/flows/schwab.py`

**Location:** Before line 237 (the `_IGNORE_TYPES` check)

Add `_system_transfer_cost(row)` helper using the SAME extraction chain as the normalizer (imported from normalizer module). Uses `abs(quantity * price)` — NOT the `cost` field — to guarantee exact match with the BUY amount.

```python
def _system_transfer_cost(row: dict[str, Any]) -> float:
    """Return cash basis for Schwab TRADE system-transfer rows."""
    transfer_leg = _select_trade_leg(row)
    if transfer_leg is None:
        return 0.0
    instrument = _extract_item_instrument(transfer_leg)
    if _is_currency_instrument(instrument):
        return 0.0
    quantity = _extract_quantity(row, transfer_leg)
    if quantity <= 0:
        return 0.0
    price = _extract_price_from_row(transfer_leg, quantity)
    if price <= 0:
        return 0.0
    return abs(quantity * price)
```

Branch before `_IGNORE_TYPES`:

```python
if row_type == "TRADE" and raw_amount == 0:
    transfer_cost = _system_transfer_cost(row)
    if transfer_cost > 0:
        event = _flow_event(row, amount=transfer_cost, flow_type="contribution",
                            is_external_flow=True, transfer_cash_confirmed=True)
        if event:
            events.append(event)
        continue

if row_type in SCHWAB_TRADE_ACTIONS or row_type in _IGNORE_TYPES:
    continue
```

## Why This Works Together

1. System transfer BUY creates FIFO entry → populates `earliest_txn_by_symbol` with Aug 24, 2024
2. `use_per_symbol_inception=True` → synthetic for that symbol uses Aug 24 instead of global inception
3. Synthetic is placed at Aug 24 - 1s → co-located with the BUY (same monthly bucket)
4. No double-counting: synthetic covers pre-BUY moment, BUY establishes the position
5. Contribution neutralizes BUY's cash impact → net zero cash effect
6. For symbols WITHOUT any transaction history, fallback to global inception is preserved

## Previous Codex Review (v1) — Addressed

| Concern | Severity | Resolution |
|---------|----------|------------|
| Multi-leg transfer rows | High | All 9 rows are single-leg. Both sides use `_select_trade_leg` → same single leg |
| Cash neutrality | Medium | Both sides compute `price * quantity` from same extraction chain. No fees/FX involved |
| Account 165 return change | Medium | Transfer date and inception are same month. ±1pp acceptable as correctness improvement |

**New in v2:** Per-symbol inception enablement eliminates the double-counting that caused v1 to fail.

## Verification

```bash
# 1. Run existing tests
python3 -m pytest tests/ -x -q -k "schwab" 2>&1 | tail -10

# 2. Account 165 regression (must stay ~-7.97%, ±1pp acceptable)
python3 -c "
from mcp_tools.performance import get_performance
r = get_performance(mode='realized', institution='charles_schwab', account='87656165', format='agent', use_cache=False)
print(f'Account 165: {r[\"snapshot\"][\"returns\"][\"total_return_pct\"]}%')
"

# 3. Account 013 improvement (gap should decrease from +11pp vs broker -14.69%)
python3 -c "
from mcp_tools.performance import get_performance
import functools
r = get_performance(mode='realized', institution='charles_schwab', account='51388013', format='agent', use_cache=False)
s = r['snapshot']
monthly = s.get('monthly_returns', [])
y2025 = [m for m in monthly if m.get('date', '').startswith('2025')]
cum = functools.reduce(lambda a, b: a * (1 + b.get('return', 0)/100), y2025, 1.0)
print(f'Account 013 2025: {(cum-1)*100:.2f}% (broker: -14.69%, was: -3.49%)')
print(f'Account 013 total: {s[\"returns\"][\"total_return_pct\"]}%')
"

# 4. IBKR unchanged (-71.66%)
python3 -c "
from mcp_tools.performance import get_performance
r = get_performance(mode='realized', institution='interactive_brokers', format='agent', use_cache=False)
print(f'IBKR: {r[\"snapshot\"][\"returns\"][\"total_return_pct\"]}%')
"

# 5. Schwab combined
python3 -c "
from mcp_tools.performance import get_performance
r = get_performance(mode='realized', institution='charles_schwab', format='agent', use_cache=False)
print(f'Combined: {r[\"snapshot\"][\"returns\"][\"total_return_pct\"]}%')
"
```

## Acceptance Gates

- Account 165: ~-7.97% (±1pp acceptable as correctness improvement)
- Account 013 2025: gap vs broker (-14.69%) decreases from +11pp
- Account 252: unchanged (no System transfer rows)
- IBKR: unchanged (-71.66%)
- All existing tests pass
