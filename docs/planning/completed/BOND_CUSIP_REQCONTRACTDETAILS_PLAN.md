# Bond CUSIP → conId Resolution via reqContractDetails

## Context

The previous plan (implemented and tested) enriches `contract_identity` with CUSIP and creates a `Bond(secIdType="CUSIP", secId=...)` object in `resolve_bond_contract()`. Live testing against IBKR TWS revealed that **`qualifyContracts()` does not support `secIdType=CUSIP` for bonds**. The CUSIP data exists in `secIdList` on `ContractDetails` objects from `reqContractDetails()`, but direct qualification by CUSIP fails with "No security definition found" for every bond tested.

This plan adds the missing step: search bonds via `reqContractDetails()`, match the CUSIP from `secIdList`, and resolve to conId.

## Live Test Findings

```
# qualifyContracts with CUSIP — FAILS for ALL bonds (even known-good CUSIPs)
Bond(secIdType='CUSIP', secId='912810EW4') → "No security definition found"

# reqContractDetails by symbol — WORKS, CUSIPs in secIdList
Contract(secType='BOND', symbol='US-T') → 1158 results
  each has secIdList = [TagValue(tag='CUSIP', value='912810EW4'), ...]

# US Treasuries use symbol 'US-T' (not 'T' — that's AT&T corporate bonds)
# US Treasury CUSIPs start with '912' (Bureau of Fiscal Service issuer number)
```

## Approach

Two changes, both within `ibkr/` package:

1. **`ibkr/metadata.py`** — New `resolve_bond_by_cusip()` that searches `reqContractDetails()` and matches CUSIP from `secIdList`
2. **`ibkr/market_data.py`** — In `_request_bars()`, when qualification fails for a CUSIP-based bond, call the resolver and retry with the resolved conId

`resolve_bond_contract()` in `contracts.py` stays unchanged — it still creates the `Bond(secIdType='CUSIP')` object. The resolution to conId happens at qualification time when we have a live `ib` connection.

## Changes

### 1. `ibkr/metadata.py` — Add `resolve_bond_by_cusip()`

```python
def resolve_bond_by_cusip(
    ib,
    cusip: str,
    currency: str = "USD",
) -> int | None:
    """Search IBKR bond contracts and match CUSIP from secIdList.

    IBKR's qualifyContracts() does not support secIdType=CUSIP for bonds.
    Instead, we search by issuer symbol via reqContractDetails() and match
    the CUSIP from the secIdList field on each ContractDetails result.

    US Treasuries use symbol 'US-T'. Non-Treasury bonds not yet supported.

    Returns conId if found, None otherwise.
    """
    from ib_async import Contract

    cusip = cusip.strip().upper()
    if not cusip:
        return None

    # US Treasury CUSIPs start with 912 (Bureau of Fiscal Service)
    if not cusip.startswith("912"):
        return None  # Non-Treasury bonds not yet supported

    contract = Contract(secType="BOND", symbol="US-T", currency=currency)
    details = list(ib.reqContractDetails(contract) or [])

    for detail in details:
        sec_id_list = getattr(detail, "secIdList", None) or []
        for tag_value in sec_id_list:
            if (
                getattr(tag_value, "tag", "") == "CUSIP"
                and getattr(tag_value, "value", "").strip().upper() == cusip
            ):
                con = getattr(detail, "contract", None)
                con_id = getattr(con, "conId", None) if con else None
                if con_id:
                    return int(con_id)

    return None
```

### 2. `ibkr/market_data.py` — CUSIP fallback in `_request_bars()`

**Key issue**: `ib.qualifyContracts()` can either return `None`/empty (quiet failure) OR raise an exception with "no security definition" / "unknown contract" (noisy failure). The latter gets caught at line 162 and re-raised as `IBKRContractError`, bypassing any inline fallback. Both paths must trigger the CUSIP resolver.

Extract qualification into a helper `_qualify_contract()` that handles the CUSIP fallback for both failure modes:

```python
def _qualify_contract(self, ib, contract):
    """Qualify a contract, with CUSIP fallback for bonds.

    IBKR's qualifyContracts() does not support secIdType=CUSIP for bonds.
    When qualification fails for a CUSIP bond, search via reqContractDetails
    to resolve the CUSIP to a conId, then retry qualification.
    """
    # First attempt — may return None or raise for CUSIP bonds
    try:
        qualified = ib.qualifyContracts(contract)
        qualified_contract = next(
            (row for row in (qualified or [])
             if row is not None and getattr(row, 'conId', None)),
            None,
        )
        if qualified_contract is not None:
            return qualified_contract
    except Exception:
        # qualifyContracts raised (e.g. "no security definition")
        qualified_contract = None

    # CUSIP fallback: search via reqContractDetails
    if getattr(contract, 'secIdType', '') == 'CUSIP':
        from .metadata import resolve_bond_by_cusip
        resolved_con_id = resolve_bond_by_cusip(
            ib,
            getattr(contract, 'secId', ''),
            getattr(contract, 'currency', 'USD'),
        )
        if resolved_con_id:
            from ib_async import Bond
            retry_contract = Bond(conId=resolved_con_id)
            qualified = ib.qualifyContracts(retry_contract)
            qualified_contract = next(
                (row for row in (qualified or [])
                 if row is not None and getattr(row, 'conId', None)),
                None,
            )
            if qualified_contract is not None:
                return qualified_contract

    return None
```

Then in `_request_bars()`, replace the qualification block (lines 140-145) with:

```python
def _request_bars(self, contract, *, profile, what_to_show, start_ts, end_ts):
    with _ibkr_request_lock:
        ib = self._connect_ib()
        try:
            qualified_contract = self._qualify_contract(ib, contract)
            if qualified_contract is None:
                raise IBKRContractError("Unable to qualify IBKR contract")

            duration_str = self._duration_for_request(profile, start_ts, end_ts)
            bars = ib.reqHistoricalData(
                qualified_contract,
                # ... rest unchanged
```

This keeps the existing exception mapping (`except Exception` at line 162) intact for non-CUSIP contracts, while the CUSIP fallback is fully handled inside `_qualify_contract()`.

## Files Modified

| File | Action |
|------|--------|
| `ibkr/metadata.py` | Add `resolve_bond_by_cusip()` — CUSIP search via `reqContractDetails()` |
| `ibkr/market_data.py` | Extract `_qualify_contract()` with CUSIP fallback, simplify `_request_bars()` |
| `tests/ibkr/test_bond_cusip.py` | Test `resolve_bond_by_cusip()` + `_qualify_contract()` CUSIP fallback |

## Files NOT Modified

| File | Why |
|------|-----|
| `ibkr/contracts.py` | `resolve_bond_contract()` still creates Bond(secIdType=CUSIP) — correct |
| `core/realized_performance_analysis.py` | Already enriches contract_identity with CUSIP (previous plan) |
| Everything outside `ibkr/` | Package boundary preserved |

## Edge Cases

1. **Non-Treasury bonds**: CUSIP prefix check returns `None` → no search → falls through to "Unable to qualify" error. Future: add corporate bond issuer mapping.
2. **CUSIP not in search results**: Returns `None` → qualification still fails → existing error handling.
3. **Matured bonds**: Won't appear in `reqContractDetails()` → returns `None` → unpriceable.
4. **Gateway not running**: `_connect_ib()` raises `IBKRConnectionError` → caught by `fetch_series()`.
5. **Non-CUSIP bonds (conId path)**: Qualification succeeds on first attempt, CUSIP fallback never triggered.

## Test Cases

**`tests/ibkr/test_bond_cusip.py`** (new file — keeps bond CUSIP tests together):

`resolve_bond_by_cusip()` tests:
- `test_resolve_bond_by_cusip_treasury`: Mock `reqContractDetails` with secIdList containing target CUSIP → returns conId
- `test_resolve_bond_by_cusip_not_found`: CUSIP not in results → returns None
- `test_resolve_bond_by_cusip_non_treasury`: Non-912 prefix → returns None immediately (no API call)
- `test_resolve_bond_by_cusip_empty`: Empty/blank CUSIP → returns None

`_qualify_contract()` CUSIP fallback tests:
- `test_qualify_contract_cusip_fallback_none_result`: qualifyContracts returns None → CUSIP search resolves conId → retry succeeds
- `test_qualify_contract_cusip_fallback_exception`: qualifyContracts raises "no security definition" → CUSIP search resolves conId → retry succeeds
- `test_qualify_contract_cusip_fallback_not_found`: CUSIP search returns None → returns None (caller raises IBKRContractError)
- `test_qualify_contract_non_cusip_no_fallback`: Non-CUSIP bond (conId path) → qualification succeeds on first attempt, no fallback triggered

## Verification

```bash
# Unit tests
pytest tests/ibkr/test_bond_cusip.py -v

# All existing tests still pass
pytest tests/ -x -q -k "not slow"

# Live test (requires IBKR TWS on port 7496)
python3 -c "
import nest_asyncio; nest_asyncio.apply()
from ib_async import IB
from ibkr.metadata import resolve_bond_by_cusip

ib = IB()
ib.connect('127.0.0.1', 7496, clientId=99, timeout=10)
con_id = resolve_bond_by_cusip(ib, '912810EW4')
print(f'CUSIP 912810EW4 → conId={con_id}')
ib.disconnect()
"
```
