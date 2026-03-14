# Futures Phase 8b — instrument_types DB Read Path
**Status:** DONE

## Context

The `instrument_types` dict (`{ticker: "futures"|"option"|"bond"|...}`) drives critical downstream decisions: pricing provider selection, FMP ticker mapping, contract spec lookups, and ticker collision guards. It's auto-detected in `PortfolioPositions.to_portfolio_data()` (used by MCP tools/services) but **not** in the `PortfolioManager._load_portfolio_from_database()` → `PortfolioAssembler.build_portfolio_data()` path (used by YAML config loading).

**Two gaps exist:**
1. **Read path**: The assembler never extracts `instrument_types` or `contract_identities` from DB position metadata when building `PortfolioData`.
2. **Write path inconsistency**: IBKR direct positions (`providers/ibkr_positions.py:34`) map `FUT → "derivative"`, while IBKR Flex (`ibkr/flex.py:193`) maps `FUT → "futures"`. This causes `filter_positions()` to DROP IBKR-direct futures (it blocks `type == "derivative"`).

**DB type values by source:**
| Source | Futures | Options | Bonds | Other non-equity |
|--------|---------|---------|-------|-------------------|
| IBKR Flex | `futures` | `option` | `bond` | `fx_artifact`, `unknown` |
| IBKR Direct | `derivative` | `option` | `bond` | `mutual_fund` |
| SnapTrade | `futures` | `option` | `bond` | `fx_artifact`, `unknown` |
| Plaid | `futures` | `option` | `bond` | `fx_artifact`, `unknown` |
| Schwab | — | `option` | `bond` | `mutual_fund` |

Without `instrument_types`, the assembler path silently treats all non-cash positions as equities, causing wrong pricing, missing FMP ticker maps for futures, and no contract_identities for options.

## Gap Analysis

### Current flow (broken):
```
_load_portfolio_from_database()
  → raw_positions (some have type="derivative" for IBKR-direct futures)
  → filter_positions()              ← DROPS type="derivative" (IBKR-direct futures lost!)
  → consolidate_positions()
  → build_ticker_and_currency_maps() ← extracts fmp_ticker_map + currency_map
  → build_portfolio_data()           ← calls PortfolioData.from_holdings() WITHOUT instrument_types
```

### Reference flow (working, in `to_portfolio_data()`):
```
PortfolioPositions.to_portfolio_data()
  → auto-detect instrument_types from position type + IBKR exchange mappings  (L654-670)
  → auto-detect contract_identities from option positions/symbols             (L672-702)
  → populate futures fmp_ticker_map from contract specs                       (L704-719)
  → PortfolioData.from_holdings(..., instrument_types=..., contract_identities=...)
```

## Changes

### 8b-0. Make `filter_positions()` derivative-aware (not blanket-drop)
**File**: `inputs/portfolio_assembler.py`

The filter currently blocks ALL `type == "derivative"` positions. But IBKR direct positions store futures as `type="derivative"` (`providers/ibkr_positions.py:34`), and Plaid stores options as `"derivative"` too. At the same time, Plaid also uses `"derivative"` for warrants and SnapTrade for structured products — those SHOULD still be excluded.

**Approach**: Run `build_instrument_types_map()` on raw positions FIRST (before filtering), then use its output to decide which derivatives to keep. Only derivatives promoted to `"futures"` or `"option"` survive; unpromoted derivatives (warrants, structured products) are still dropped.

Change `filter_positions()` to accept an optional `promoted_tickers` set:
```python
def filter_positions(
    self,
    positions: List[Dict[str, Any]],
    promoted_derivatives: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Filter out unsupported/invalid positions."""
    promoted = promoted_derivatives or set()
    filtered_positions: List[Dict[str, Any]] = []

    for position in positions:
        ticker = position.get("ticker")
        position_type = position.get("type")

        if position_type == "derivative":
            if ticker and ticker in promoted:
                filtered_positions.append(position)
            else:
                portfolio_logger.info("⏭️ Skipping derivative: %s", ticker)
            continue

        if not ticker or ticker.strip() == "":
            portfolio_logger.info("⏭️ Skipping position with invalid ticker")
            continue

        filtered_positions.append(position)

    return filtered_positions
```

**Note**: We intentionally keep `_SEC_TYPE_MAP` in `providers/ibkr_positions.py` as-is (`FUT → "derivative"`) because 5+ downstream consumers depend on that value (`data_objects.py:659`, `routes/positions.py:134`, `position_enrichment.py:25`, `portfolio_service.py:1121,1481`). The normalization happens at the assembler read path only.

Also update the manager's `_filter_positions()` wrapper (`portfolio_manager.py:559`) to pass through the new param:
```python
def _filter_positions(
    self,
    positions: List[Dict[str, Any]],
    promoted_derivatives: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    return self.assembler.filter_positions(positions, promoted_derivatives=promoted_derivatives)
```

### 8b-1. Add `build_instrument_types_map()` to `PortfolioAssembler`
**File**: `inputs/portfolio_assembler.py`

Extract `instrument_types` from the raw position `type` field. Only include non-equity types (equity is the default). Handle legacy `derivative` type by promoting to `futures` via IBKR exchange mappings (same logic as `to_portfolio_data()` L654-670).

```python
def build_instrument_types_map(
    self,
    filtered_positions: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Extract instrument_types from position metadata."""
    instrument_types: Dict[str, str] = {}
    non_equity_types = {"futures", "option", "bond", "fx_artifact", "mutual_fund"}

    try:
        from ibkr.compat import get_ibkr_futures_exchanges
        known_futures = get_ibkr_futures_exchanges()
    except Exception:
        known_futures = set()

    try:
        from trading_analysis.symbol_utils import parse_option_contract_identity_from_symbol
    except Exception:
        parse_option_contract_identity_from_symbol = None

    for position in filtered_positions:
        ticker = position.get("ticker")
        if not ticker:
            continue
        pos_type = str(position.get("type") or "").strip().lower()
        normalized = str(ticker).strip().upper()

        if pos_type in non_equity_types:
            instrument_types[ticker] = pos_type
            continue

        if pos_type == "derivative":
            # Legacy IBKR-direct rows: promote to "futures" if ticker matches
            # known futures roots (same guard as to_portfolio_data() L659-668)
            if normalized in known_futures:
                instrument_types[ticker] = "futures"
                continue
            # Fall through to option symbol parse — Plaid stores options as
            # "derivative" too (plaid_loader.py:680)

        # Promote parseable option symbols regardless of original type
        # (matches to_portfolio_data() L696-700 fallback detection).
        # Catches: equity-typed options, derivative-typed options (Plaid).
        if normalized not in instrument_types and parse_option_contract_identity_from_symbol:
            parsed = parse_option_contract_identity_from_symbol(normalized)
            if parsed:
                instrument_types[ticker] = "option"

    return instrument_types
```

### 8b-2. Add `build_contract_identities_map()` to `PortfolioAssembler`
**File**: `inputs/portfolio_assembler.py`

Parse option contract identities from ticker symbols. Reuses existing `parse_option_contract_identity_from_symbol()` and `enrich_option_contract_identity()` from `trading_analysis/symbol_utils.py`.

```python
def build_contract_identities_map(
    self,
    filtered_positions: List[Dict[str, Any]],
    instrument_types: Dict[str, str],
) -> Dict[str, Dict[str, Any]]:
    """Parse contract identities for option positions.

    Keys are uppercased to match downstream lookups in portfolio_risk.py:622,689
    (same convention as to_portfolio_data() at data_objects.py:680).
    """
    from trading_analysis.symbol_utils import (
        parse_option_contract_identity_from_symbol,
        enrich_option_contract_identity,
    )

    contract_identities: Dict[str, Dict[str, Any]] = {}
    for position in filtered_positions:
        ticker = position.get("ticker")
        if not ticker or instrument_types.get(ticker) != "option":
            continue
        normalized_ticker = str(ticker).strip().upper()
        parsed = parse_option_contract_identity_from_symbol(normalized_ticker)
        if parsed:
            contract_identities[normalized_ticker] = enrich_option_contract_identity(parsed, "option")

    return contract_identities
```

### 8b-3. Populate futures FMP tickers from contract specs
**File**: `inputs/portfolio_assembler.py`

After building `fmp_ticker_map` and `instrument_types`, fill in missing futures FMP symbols. Same logic as `to_portfolio_data()` lines 704-719.

```python
def enrich_futures_fmp_tickers(
    self,
    fmp_ticker_map: Dict[str, str],
    instrument_types: Dict[str, str],
) -> None:
    """Populate missing FMP symbols for futures from contract specs (in-place)."""
    from brokerage.futures import get_contract_spec

    for ticker, inst_type in instrument_types.items():
        if inst_type != "futures" or ticker in fmp_ticker_map:
            continue
        spec = get_contract_spec(ticker)
        if spec and spec.fmp_symbol:
            fmp_ticker_map[ticker] = spec.fmp_symbol
```

### 8b-4. Thread new params through `build_portfolio_data()`
**File**: `inputs/portfolio_assembler.py`

Add `instrument_types` and `contract_identities` params to `build_portfolio_data()`, pass through to `PortfolioData.from_holdings()`:

```python
def build_portfolio_data(
    self,
    holdings: ...,
    ...,
    fmp_ticker_map: Dict[str, str],
    currency_map: Dict[str, str],
    instrument_types: Optional[Dict[str, str]] = None,       # NEW
    contract_identities: Optional[Dict[str, Dict]] = None,   # NEW
) -> PortfolioData:
    return PortfolioData.from_holdings(
        ...,
        instrument_types=instrument_types or None,
        contract_identities=contract_identities or None,
    )
```

### 8b-5. Thread `instrument_types` through `_ensure_factor_proxies()`
**File**: `inputs/portfolio_manager.py`

Add `instrument_types` param to `_ensure_factor_proxies()` (line 590) and pass through to `ensure_factor_proxies()` (line 601). Without this, futures/options admitted by this plan get bogus factor proxy lookups.

```python
def _ensure_factor_proxies(
    self,
    portfolio_name: str,
    tickers: set[str],
    allow_gpt: bool,
    instrument_types: Optional[Dict[str, str]] = None,  # NEW
) -> Dict[str, Dict[str, Any]]:
    ...
    return ensure_factor_proxies(
        ...,
        instrument_types=instrument_types,  # NEW
    )
```

### 8b-6. Update `_load_portfolio_from_database()` call order
**File**: `inputs/portfolio_manager.py`

Key change: run `build_instrument_types_map()` on RAW positions BEFORE `filter_positions()`, so promoted derivatives inform the filter. Updated flow:

```python
raw_positions = self.repository.get_portfolio_positions(...)

# NEW: Detect instrument types on raw positions (before filtering)
# so we know which derivatives are futures/options vs unsupported
instrument_types = self.assembler.build_instrument_types_map(raw_positions)
promoted_derivatives = {t for t, it in instrument_types.items() if it in ("futures", "option")}

# Pass promoted set to filter — keeps promoted derivatives, drops warrants/structured
filtered_positions = self._filter_positions(raw_positions, promoted_derivatives=promoted_derivatives)
consolidated_positions = self._consolidate_positions(filtered_positions)
cash_map = self._load_cash_mapping()
mapped_portfolio_input = self._apply_cash_mapping(consolidated_positions, cash_map=cash_map)

# ... existing metadata/factor/returns loading ...

complete_factor_proxies = factor_proxies
if self.auto_ensure_proxies:
    complete_factor_proxies = self._ensure_factor_proxies(
        portfolio_name,
        set(mapped_portfolio_input.keys()),
        allow_gpt=True,
        instrument_types=instrument_types,  # NEW — prevents bogus proxy lookups
    )

fmp_ticker_map, currency_map = self.assembler.build_ticker_and_currency_maps(filtered_positions)

# NEW: Build contract identities + enrich futures FMP tickers
contract_identities = self.assembler.build_contract_identities_map(
    filtered_positions, instrument_types
)
self.assembler.enrich_futures_fmp_tickers(fmp_ticker_map, instrument_types)

return self.assembler.build_portfolio_data(
    ...,
    fmp_ticker_map=fmp_ticker_map,
    currency_map=currency_map,
    instrument_types=instrument_types,          # NEW
    contract_identities=contract_identities,    # NEW
)
```

## Files to Modify

| File | Changes |
|------|---------|
| `inputs/portfolio_assembler.py` | 8b-0: remove derivative filter; 8b-1: `build_instrument_types_map()`; 8b-2: `build_contract_identities_map()` (uppercased keys); 8b-3: `enrich_futures_fmp_tickers()`; 8b-4: add params to `build_portfolio_data()` |
| `inputs/portfolio_manager.py` | 8b-5: thread `instrument_types` through `_ensure_factor_proxies()` (line 590-606); 8b-6: reorder `_load_portfolio_from_database()` call flow (lines 304-347) |

**NOT modified**: `providers/ibkr_positions.py` — `_SEC_TYPE_MAP` stays as-is (`FUT → "derivative"`) because 5+ downstream consumers depend on it (`data_objects.py:659`, `routes/positions.py:134`, `position_enrichment.py:25`, `portfolio_service.py:1121,1481`).

## Implementation Order

1. **8b-1** — `build_instrument_types_map()` (core detection, needed by filter)
2. **8b-0** — Make `filter_positions()` derivative-aware (uses 8b-1 output)
3. **8b-3** + **8b-4** — futures FMP enrichment + `build_portfolio_data()` plumbing
4. **8b-2** — contract_identities for options (additive, low risk)
5. **8b-5** — thread `instrument_types` through `_ensure_factor_proxies()`
6. **8b-6** — wire into the manager with new call order (depends on all above)

## Verification

1. **Unit tests** (`tests/inputs/`):
   - `test_build_instrument_types_map_futures()` — type="futures" → included
   - `test_build_instrument_types_map_option_bond()` — type="option"/"bond" → included
   - `test_build_instrument_types_map_excludes_equity()` — equity/cash/etf → excluded
   - `test_build_instrument_types_map_derivative_promotion()` — type="derivative" + known futures root → promoted to "futures"
   - `test_build_instrument_types_map_derivative_unknown()` — type="derivative" + non-futures ticker → excluded
   - `test_build_instrument_types_map_none_empty_type()` — type=None/"" → excluded
   - `test_build_instrument_types_map_option_symbol_promotion()` — equity-typed position with parseable option symbol → promoted to "option"
   - `test_build_instrument_types_map_derivative_option_promotion()` — derivative-typed position with parseable option symbol (Plaid pattern) → promoted to "option" (not dropped)
   - `test_build_contract_identities_map()` — option ticker symbols → parsed identities
   - `test_build_contract_identities_map_unparseable()` — unparseable option symbol → no identity (skipped gracefully)
   - `test_enrich_futures_fmp_tickers()` — fills in missing fmp_ticker for futures
   - `test_build_portfolio_data_passes_instrument_types()` — verify threaded to `from_holdings()`
   - `test_filter_positions_passes_futures_options()` — type="futures"/"option" pass filter
   - `test_filter_positions_promoted_derivative_passes()` — type="derivative" passes when in promoted_derivatives set
   - `test_filter_positions_unpromoted_derivative_dropped()` — type="derivative" dropped when NOT in promoted_derivatives (warrants, structured products)
2. **Update existing tests** (derivative filter removal — 8b-0):
   - `tests/inputs/test_portfolio_assembler.py` — existing tests assert derivatives are filtered; update to reflect derivatives now pass through
   - `tests/unit/test_positions_data.py:188` — may assert derivative filtering; update if affected
   - `tests/test_positions_sts_threading.py:58` — may encode derivative contract; verify still passes
   - `tests/providers/test_ibkr_positions.py:140` — IBKR FUT → "derivative" assertion stays (source NOT changed)
3. **Manager-level integration** (`tests/inputs/`):
   - `test_load_portfolio_from_database_threads_instrument_types()` — mock repository, verify PortfolioData has instrument_types populated
   - `test_ensure_factor_proxies_receives_instrument_types()` — with `auto_ensure_proxies=True` and option holding, verify `instrument_types` is passed to `ensure_factor_proxies()`
4. **Existing tests**: `python -m pytest tests/ -x -q --ignore=tests/integration` — no regressions
5. **Live test**: Load portfolio via DB path, verify `PortfolioData.instrument_types` is populated with futures/option types

## Out of Scope

- **Bond identifiers**: DB `positions` table lacks `cusip`/`isin`/`figi` columns. Bond `instrument_types` will be set but no security identifiers attached. Future work.
- **`unknown` type positions**: Positions with `type="unknown"` (from IBKR Flex/SnapTrade/Plaid for unrecognized asset categories) are excluded from `instrument_types` — they default to equity treatment. This matches existing `to_portfolio_data()` behavior.
