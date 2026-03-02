# Bond/Treasury Pricing — CUSIP → IBKR con_id Resolver

## Context

Security identifiers (CUSIP/ISIN from Plaid, CUSIP from Schwab, FIGI from SnapTrade) are fully captured and threaded into `PortfolioData.security_identifiers`, but they're never used for pricing. Bond positions hit the `bond_missing_con_id` guard in `realized_performance_analysis.py:3352` and are valued at $0. The pricing infrastructure is ready — `resolve_bond_contract()` works with con_id, `fetch_monthly_close_bond()` works — we just need to bridge CUSIP → con_id.

## Approach — Clean Package Boundaries

CUSIP → con_id resolution is an **IBKR-specific concern**. The fix stays within package boundaries:

- **IBKR package** (`ibkr/`): `resolve_bond_contract()` learns to accept CUSIP in `contract_identity` — all IBKR-specific logic stays here
- **System layer** (`core/realized_performance_analysis.py`): Enriches `contract_identity` with security identifiers from positions before passing to the existing pricing chain
- **No changes** to `providers/interfaces.py`, `providers/fmp_price.py`, `_fetch_price_from_chain()` signature, or any provider protocol

The key insight: `contract_identity` is already a generic dict that flows through the entire pricing chain. We just add `cusip`/`isin`/`figi` keys to it at the system layer. The IBKR package checks for them internally. Non-IBKR providers ignore unknown keys.

## Changes

### 1. `ibkr/contracts.py` — Extend `resolve_bond_contract()`

Check `contract_identity` for CUSIP when con_id is missing. No new params — just look at additional keys in the existing dict:

```python
def resolve_bond_contract(
    symbol: str,
    contract_identity: dict[str, Any] | None = None,
) -> Contract:
    """Resolve a bond contract. Tries con_id first, then CUSIP."""
    # Try con_id first — catch IBKRContractError so CUSIP fallback works
    # when con_id is present but invalid (NaN, non-integer, etc.)
    try:
        con_id = _coerce_con_id(contract_identity)
    except IBKRContractError:
        con_id = None  # fall through to CUSIP

    if con_id is not None:
        # Existing path — direct con_id
        try:
            from ib_async import Bond
            return Bond(conId=con_id)
        except Exception:
            from ib_async import Contract
            return Contract(conId=con_id, secType="BOND")

    # NEW: CUSIP-based resolution via contract_identity
    identity = contract_identity if isinstance(contract_identity, dict) else {}
    cusip = identity.get("cusip")
    if isinstance(cusip, str) and cusip.strip():
        from ib_async import Bond
        bond = Bond()
        bond.secIdType = "CUSIP"
        bond.secId = cusip.strip()
        bond.currency = str(identity.get("currency") or "USD").upper()
        return bond

    raise IBKRContractError(
        "Bond pricing requires contract_identity with con_id or cusip"
    )
```

**No signature change** — `resolve_bond_contract(symbol, contract_identity)` stays the same. No changes needed in `resolve_contract()`, `fetch_series()`, `fetch_monthly_close_bond()`, `ibkr/compat.py`, or `providers/ibkr_price.py`.

### 2. `core/realized_performance_analysis.py` — Enrich contract_identity with identifiers

**In `_build_current_positions()` (~line 559)**: Extract identifiers from position dicts into current_positions map:

```python
current_positions[ticker] = {
    "shares": quantity,
    "currency": str(currency),
    "cost_basis": ...,
    "cost_basis_is_usd": ...,
    "value": ...,
    "instrument_type": instrument_type,
    "security_identifiers": {
        k: v for k, v in {
            "cusip": pos.get("cusip"),
            "isin": pos.get("isin"),
            "figi": pos.get("figi"),
        }.items() if isinstance(v, str) and v.strip()
    } or None,
}
```

**At the bond pricing guard (~line 3352)**: Enrich `contract_identity` with security identifiers before passing to the existing pricing chain:

```python
if instrument_type == "bond":
    has_ibkr = any(p.provider_name == "ibkr" for p in chain)
    con_id = None
    if isinstance(contract_identity, dict):
        con_id = contract_identity.get("con_id")

    # Enrich contract_identity with security identifiers when cusip
    # is not already present. This covers: no con_id, invalid con_id
    # (NaN/inf), or con_id present but we want CUSIP as fallback.
    existing_cusip = isinstance(contract_identity, dict) and contract_identity.get("cusip")
    sec_ids = (current_positions.get(ticker) or {}).get("security_identifiers")
    if sec_ids and not existing_cusip:
        enriched = dict(contract_identity) if isinstance(contract_identity, dict) else {}
        enriched.update(sec_ids)  # adds cusip, isin, figi keys
        contract_identity = enriched

    # Check: do we have anything useful for IBKR?
    has_cusip = isinstance(contract_identity, dict) and contract_identity.get("cusip")
    if has_ibkr and con_id in (None, "") and not has_cusip:
        warnings.append(
            f"No con_id or CUSIP for bond {ticker}; skipping IBKR bond pricing."
        )
        unpriceable_reason = "bond_missing_identifiers"
    else:
        # Existing pricing path — contract_identity now has cusip
        price_result = _fetch_price_from_chain(
            chain, ticker, price_fetch_start, end_date,
            instrument_type=instrument_type,
            contract_identity=contract_identity,
            fmp_ticker_map=fmp_ticker_map or None,
        )
        ...  # existing diagnostics code unchanged
```

**No changes to `_fetch_price_from_chain()`** — it already passes `contract_identity` through to providers.

## Files Modified

| File | Action |
|------|--------|
| `ibkr/contracts.py` | Extend `resolve_bond_contract()` to check for CUSIP in `contract_identity` |
| `core/realized_performance_analysis.py` | Extract identifiers in `_build_current_positions()`, enrich `contract_identity` at bond guard |
| `tests/ibkr/test_contracts.py` | Test CUSIP-based bond resolution |
| `tests/core/test_realized_performance_bond_pricing.py` | Test identifier extraction + enriched contract_identity flow |

## Files NOT Modified (boundary preserved)

| File | Why unchanged |
|------|---------------|
| `providers/interfaces.py` | Protocol stays generic — no bond-specific params |
| `providers/fmp_price.py` | FMP provider doesn't need to know about CUSIPs |
| `providers/ibkr_price.py` | Already passes `contract_identity` through — no changes needed |
| `ibkr/market_data.py` | Already passes `contract_identity` to `resolve_contract()` — no changes needed |
| `ibkr/compat.py` | Already passes `contract_identity` through — no changes needed |
| `_fetch_price_from_chain()` | Already passes `contract_identity` — no signature change |

## Edge Cases

1. **CUSIP not available** (IBKR Flex positions): Falls through to `bond_missing_identifiers` — same as current behavior
2. **CUSIP doesn't resolve in IBKR**: `qualifyContracts()` returns empty → existing error handling → unpriceable
3. **Matured bonds**: IBKR may not have contract data — qualification fails gracefully
4. **Invalid con_id with valid CUSIP**: `_coerce_con_id()` raises `IBKRContractError` on NaN/inf/non-integer con_id. `resolve_bond_contract()` catches this and falls through to CUSIP path. Only re-raises if neither con_id nor CUSIP is usable.
5. **FMP doesn't price bonds**: `FMPProvider` skips bonds (`providers/fmp_price.py:30`). When IBKR is in the chain, it's the only provider that handles bonds. The enriched `contract_identity` with CUSIP gives IBKR what it needs.
6. **Multiple identifiers**: CUSIP is preferred (most widely supported by IBKR). ISIN/FIGI included in enriched dict for future use.

## Existing Code Reused

- `ibkr/contracts.py` → `resolve_bond_contract()`, `_coerce_con_id()` — extended internally
- `ibkr/market_data.py` → `fetch_series()` → `qualifyContracts()` — CUSIP Bond goes through same qualification path, no changes needed
- `ib_async.Bond` → supports `secIdType`/`secId` natively
- `contract_identity` dict flows through entire pricing chain already
- Position identifiers already captured in normalizers (Plaid cusip/isin, Schwab cusip, SnapTrade figi)

## Test Updates Required

### Existing tests to update

| Test file | Current assertion | New assertion |
|-----------|------------------|---------------|
| `tests/ibkr/test_market_data.py` | Bond requires con_id, raises without it | Bond works with CUSIP when con_id missing |
| `tests/core/test_realized_performance_analysis.py` | Bond without con_id → `bond_missing_con_id` skip | Bond without con_id but WITH CUSIP → pricing attempted; bond without either → `bond_missing_identifiers` |

### New test cases

**`tests/ibkr/test_contracts.py`** (add to existing):
- `test_resolve_bond_contract_cusip`: CUSIP in contract_identity → Bond with secIdType=CUSIP
- `test_resolve_bond_contract_cusip_with_currency`: CUSIP + currency → Bond with correct currency
- `test_resolve_bond_contract_invalid_conid_cusip_fallback`: Invalid con_id (NaN) + valid CUSIP → falls through to CUSIP path
- `test_resolve_bond_contract_no_identifiers`: No con_id, no CUSIP → IBKRContractError

**`tests/core/test_realized_performance_bond_pricing.py`** (new file):
- `test_build_current_positions_extracts_identifiers`: Position with cusip/isin/figi → security_identifiers populated
- `test_build_current_positions_no_identifiers`: Position without identifiers → security_identifiers is None
- `test_bond_guard_enriches_contract_identity`: Bond ticker with CUSIP in current_positions → contract_identity enriched
- `test_bond_guard_no_identifiers_unpriceable`: Bond without con_id or CUSIP → `bond_missing_identifiers`
- `test_bond_guard_conid_present_no_enrichment`: Bond with valid con_id + CUSIP already in contract_identity → CUSIP not overwritten, con_id path used
- `test_bond_guard_invalid_conid_with_cusip`: Bond with invalid con_id (NaN) + CUSIP in positions → enrichment happens, pricing attempted via CUSIP fallback

## Verification

```bash
# Unit tests
pytest tests/ibkr/test_contracts.py -v -k bond
pytest tests/core/test_realized_performance_bond_pricing.py -v

# All existing tests still pass
pytest tests/ -x -q --timeout=30 -k "not slow"

# Import check
python3 -c "from ibkr.contracts import resolve_bond_contract; print('OK')"

# Live test (requires IBKR Gateway + bond with known CUSIP)
python3 -c "
from ibkr.contracts import resolve_bond_contract
contract = resolve_bond_contract('BOND', contract_identity={'cusip': '912828ZT6'})
print(f'Contract: {contract}, secIdType={contract.secIdType}, secId={contract.secId}')
"
```
