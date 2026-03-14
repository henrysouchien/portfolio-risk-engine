# Futures Phase 1: Data Foundation

Parent design: `docs/planning/FUTURES_DESIGN.md`

## Goal

Build the futures contract data model and notional math layer. After this phase, the system knows what a futures contract is (multiplier, tick size, currency, asset class) and can calculate notional exposure. No pricing or portfolio integration yet — that's Phase 2+.

## 1. Extend `ibkr/exchange_mappings.yaml` — Add Multiplier + Tick Size

**File: `ibkr/exchange_mappings.yaml`**

Add `multiplier` and `tick_size` to the `ibkr_futures_exchanges` section. These are exchange-defined contract specifications.

```yaml
ibkr_futures_exchanges:
  # US Index Futures
  ES:    { exchange: CME,   currency: USD, multiplier: 50,    tick_size: 0.25 }
  MES:   { exchange: CME,   currency: USD, multiplier: 5,     tick_size: 0.25 }
  NQ:    { exchange: CME,   currency: USD, multiplier: 20,    tick_size: 0.25 }
  MNQ:   { exchange: CME,   currency: USD, multiplier: 2,     tick_size: 0.25 }
  YM:    { exchange: CBOT,  currency: USD, multiplier: 5,     tick_size: 1.0 }
  RTY:   { exchange: CME,   currency: USD, multiplier: 50,    tick_size: 0.10 }
  # International Index Futures
  NKD:   { exchange: CME,   currency: USD, multiplier: 5,     tick_size: 5.0 }
  MNK:   { exchange: CME,   currency: USD, multiplier: 0.5,   tick_size: 5.0 }
  NIY:   { exchange: CME,   currency: JPY, multiplier: 500,   tick_size: 5.0 }
  IBV:   { exchange: CME,   currency: USD, multiplier: 1,     tick_size: 5.0 }
  ESTX50:{ exchange: EUREX, currency: EUR, multiplier: 10,    tick_size: 1.0 }
  DAX:   { exchange: EUREX, currency: EUR, multiplier: 25,    tick_size: 1.0 }
  Z:     { exchange: ICEEU, currency: GBP, multiplier: 10,    tick_size: 0.5 }
  HSI:   { exchange: HKFE,  currency: HKD, multiplier: 50,    tick_size: 1.0 }
  # Metals
  GC:    { exchange: COMEX, currency: USD, multiplier: 100,   tick_size: 0.10 }
  MGC:   { exchange: COMEX, currency: USD, multiplier: 10,    tick_size: 0.10 }
  SI:    { exchange: COMEX, currency: USD, multiplier: 5000,  tick_size: 0.005 }
  HG:    { exchange: COMEX, currency: USD, multiplier: 25000, tick_size: 0.0005 }
  PL:    { exchange: NYMEX, currency: USD, multiplier: 50,    tick_size: 0.10 }
  PA:    { exchange: NYMEX, currency: USD, multiplier: 100,   tick_size: 0.05 }
  # Energy
  CL:    { exchange: NYMEX, currency: USD, multiplier: 1000,  tick_size: 0.01 }
  BZ:    { exchange: NYMEX, currency: USD, multiplier: 1000,  tick_size: 0.01 }
  NG:    { exchange: NYMEX, currency: USD, multiplier: 10000, tick_size: 0.001 }
  # Fixed Income
  ZB:    { exchange: CBOT,  currency: USD, multiplier: 1000,  tick_size: 0.03125 }
  ZN:    { exchange: CBOT,  currency: USD, multiplier: 1000,  tick_size: 0.015625 }
  ZF:    { exchange: CBOT,  currency: USD, multiplier: 1000,  tick_size: 0.0078125 }
  ZT:    { exchange: CBOT,  currency: USD, multiplier: 2000,  tick_size: 0.00390625 }
```

**Note**: Multiplier values are standard exchange-defined contract sizes. IBV, DAX, and ZT were corrected in Codex R1 review (see corrections table below). Remaining values to verify: MNK, NIY, HSI, PA, BZ.

## 2. Extend `ibkr/compat.py` — Export Full Contract Metadata

**File: `ibkr/compat.py`**

The existing `get_ibkr_futures_exchanges()` (line 55) explicitly rebuilds output as `{"exchange": ..., "currency": ...}`, dropping any extra YAML fields. We must NOT change this function's return shape — existing callers (including `to_portfolio_data()` auto-detection) depend on it.

Instead, add a new function that returns the full YAML metadata:

```python
def get_ibkr_futures_contract_meta() -> dict[str, dict[str, Any]]:
    """Load full IBKR futures contract metadata including multiplier and tick_size.

    Returns {symbol: {exchange, currency, multiplier, tick_size}} for all entries
    that have multiplier and tick_size defined.
    """
    raw_map = _load_ibkr_exchange_mappings().get("ibkr_futures_exchanges", {})
    out: dict[str, dict[str, Any]] = {}
    if isinstance(raw_map, dict):
        for symbol, meta in raw_map.items():
            if not isinstance(meta, dict):
                continue
            key = str(symbol or "").strip().upper()
            exchange = str(meta.get("exchange") or "").strip().upper()
            currency = str(meta.get("currency") or "USD").strip().upper()
            multiplier = meta.get("multiplier")
            tick_size = meta.get("tick_size")
            if key and exchange and multiplier is not None and tick_size is not None:
                out[key] = {
                    "exchange": exchange,
                    "currency": currency,
                    "multiplier": float(multiplier),
                    "tick_size": float(tick_size),
                }
    return out
```

Also add single-symbol convenience:

```python
def get_futures_contract_meta(symbol: str) -> Optional[dict[str, Any]]:
    """Return full contract metadata for an IBKR futures root symbol.

    Returns dict with: exchange, currency, multiplier, tick_size.
    Returns None if symbol is not a known futures root.
    """
    return get_ibkr_futures_contract_meta().get(str(symbol or "").strip().upper())
```

**Existing `get_ibkr_futures_exchanges()` is unchanged** — backward compatible.

**Update `load_contract_specs()` in `brokerage/futures/contract_spec.py`** to call `get_ibkr_futures_contract_meta()` instead of `get_ibkr_futures_exchanges()`:

```python
from ibkr.compat import get_ibkr_futures_contract_meta, get_ibkr_futures_fmp_map

exchanges = get_ibkr_futures_contract_meta()  # Returns full metadata including multiplier/tick_size
```

**Update existing `tests/ibkr/test_compat.py`** — add test for new `get_ibkr_futures_contract_meta()` function. Existing `get_ibkr_futures_exchanges()` tests remain unchanged (only returns exchange + currency).

## 3. Create `brokerage/futures/` — Domain Model

New subpackage in `brokerage/` alongside `ibkr/`, `schwab/`, `snaptrade/`, `plaid/`.

### 3a. `brokerage/futures/__init__.py`

Public exports:

```python
from brokerage.futures.contract_spec import (
    FuturesAssetClass,
    FuturesContractSpec,
    load_contract_specs,
    get_contract_spec,
)
from brokerage.futures.notional import (
    calculate_notional,
    calculate_point_value,
    calculate_tick_value,
)
```

### 3b. `brokerage/futures/contract_spec.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Literal, Optional

FuturesAssetClass = Literal[
    "equity_index",
    "fixed_income",
    "metals",
    "energy",
    "agricultural",
    "fx",
]

# IBKR root symbol → asset class mapping
_ASSET_CLASS_MAP: Dict[str, FuturesAssetClass] = {
    # US Index
    "ES": "equity_index", "MES": "equity_index",
    "NQ": "equity_index", "MNQ": "equity_index",
    "YM": "equity_index", "RTY": "equity_index",
    # International Index
    "NKD": "equity_index", "MNK": "equity_index", "NIY": "equity_index",
    "IBV": "equity_index", "ESTX50": "equity_index", "DAX": "equity_index",
    "Z": "equity_index", "HSI": "equity_index",
    # Metals
    "GC": "metals", "MGC": "metals", "SI": "metals",
    "HG": "metals", "PL": "metals", "PA": "metals",
    # Energy
    "CL": "energy", "BZ": "energy", "NG": "energy",
    # Fixed Income
    "ZB": "fixed_income", "ZN": "fixed_income",
    "ZF": "fixed_income", "ZT": "fixed_income",
}


@dataclass(frozen=True)
class FuturesContractSpec:
    """Broker-agnostic futures contract specification."""

    symbol: str             # Root symbol (e.g., "ES", "NQ", "GC")
    multiplier: float       # Contract multiplier (e.g., 50 for ES)
    tick_size: float         # Minimum price increment
    currency: str            # Settlement currency (e.g., "USD", "EUR")
    exchange: str            # Primary exchange (e.g., "CME", "EUREX")
    asset_class: FuturesAssetClass  # For risk grouping
    fmp_symbol: Optional[str] = None  # FMP commodity symbol for pricing fallback

    @property
    def tick_value(self) -> float:
        """Dollar value of one tick move (tick_size × multiplier)."""
        return self.tick_size * self.multiplier

    @property
    def point_value(self) -> float:
        """Dollar value of a one-point move (= multiplier)."""
        return self.multiplier

    def notional(self, quantity: float, price: float) -> float:
        """Calculate notional exposure: quantity × multiplier × price."""
        return quantity * self.multiplier * price

    def pnl(self, quantity: float, entry_price: float, exit_price: float) -> float:
        """Calculate P&L: quantity × multiplier × (exit - entry)."""
        return quantity * self.multiplier * (exit_price - entry_price)

    def to_contract_identity(self) -> Dict[str, object]:
        """Export as contract_identity dict for InstrumentMeta threading."""
        return {
            "symbol": self.symbol,
            "multiplier": self.multiplier,
            "tick_size": self.tick_size,
            "currency": self.currency,
            "exchange": self.exchange,
            "asset_class": self.asset_class,
        }


def load_contract_specs() -> Dict[str, FuturesContractSpec]:
    """Load all contract specs from IBKR exchange mappings.

    Returns {symbol: FuturesContractSpec} for all known futures contracts.
    Loads IBKR metadata via compat boundary (no direct ibkr/ imports).
    """
    from ibkr.compat import get_ibkr_futures_contract_meta, get_ibkr_futures_fmp_map

    exchanges = get_ibkr_futures_contract_meta()
    fmp_map = get_ibkr_futures_fmp_map()
    specs: Dict[str, FuturesContractSpec] = {}

    for symbol, meta in exchanges.items():
        multiplier = meta.get("multiplier")
        tick_size = meta.get("tick_size")
        if multiplier is None or tick_size is None:
            continue  # Skip entries without contract spec data

        specs[symbol] = FuturesContractSpec(
            symbol=symbol,
            multiplier=float(multiplier),
            tick_size=float(tick_size),
            currency=meta["currency"],
            exchange=meta["exchange"],
            asset_class=_ASSET_CLASS_MAP.get(symbol, "equity_index"),
            fmp_symbol=fmp_map.get(symbol),
        )

    return specs


def get_contract_spec(symbol: str) -> Optional[FuturesContractSpec]:
    """Look up a single contract spec by IBKR root symbol."""
    specs = load_contract_specs()
    return specs.get(symbol.strip().upper())
```

### 3c. `brokerage/futures/notional.py`

Standalone functions for callers that don't need the full spec object:

```python
from typing import Optional

from brokerage.futures.contract_spec import FuturesContractSpec, get_contract_spec


def calculate_notional(symbol: str, quantity: float, price: float) -> Optional[float]:
    """Calculate notional exposure for a futures position.

    Returns None if the symbol is not a known futures contract.
    """
    spec = get_contract_spec(symbol)
    if spec is None:
        return None
    return spec.notional(quantity, price)


def calculate_point_value(symbol: str) -> Optional[float]:
    """Return the dollar value of a one-point move.

    Returns None if the symbol is not a known futures contract.
    """
    spec = get_contract_spec(symbol)
    if spec is None:
        return None
    return spec.point_value


def calculate_tick_value(symbol: str) -> Optional[float]:
    """Return the dollar value of one tick move.

    Returns None if the symbol is not a known futures contract.
    """
    spec = get_contract_spec(symbol)
    if spec is None:
        return None
    return spec.tick_value
```

## 4. Tests

### 4a. `tests/brokerage/futures/test_contract_spec.py`

- `test_load_contract_specs_count_matches_yaml` — dynamically load YAML and verify spec count matches (not hardcoded)
- `test_load_contract_specs_has_key_symbols` — verify ES, NQ, GC, CL, ZN present
- `test_contract_spec_es` — verify ES: multiplier=50, tick_size=0.25, currency=USD, exchange=CME, asset_class=equity_index
- `test_contract_spec_nkd` — verify NKD: multiplier=5, currency=USD (CME-listed, USD-settled)
- `test_contract_spec_niy` — verify NIY: currency=JPY (CME-listed but JPY-settled)
- `test_contract_spec_gc` — verify GC: multiplier=100, asset_class=metals
- `test_contract_spec_zn` — verify ZN: multiplier=1000, asset_class=fixed_income
- `test_contract_spec_cl` — verify CL: multiplier=1000, asset_class=energy
- `test_contract_spec_ibv` — verify IBV: multiplier=1 (Codex-corrected from CME Chapter 354)
- `test_contract_spec_dax` — verify DAX: tick_size=1.0 (Codex-corrected from Eurex spec)
- `test_contract_spec_zt` — verify ZT: tick_size=0.00390625 (1/8 of 1/32, Codex-corrected)
- `test_get_contract_spec_unknown_returns_none`
- `test_get_contract_spec_case_insensitive`
- `test_asset_class_map_covers_all_symbols` — verify every symbol in specs has an explicit asset class (no silent default)

### 4b. `tests/brokerage/futures/test_notional.py`

- `test_notional_es` — 2 contracts × 50 × 5600 = 560,000
- `test_notional_gc` — 1 contract × 100 × 2400 = 240,000
- `test_notional_cl` — 3 contracts × 1000 × 75 = 225,000
- `test_notional_unknown_returns_none`
- `test_point_value_es` — 50
- `test_tick_value_es` — 0.25 × 50 = 12.50
- `test_pnl_calculation` — 2 ES contracts, entry 5600, exit 5620 → 2 × 50 × 20 = 2,000

### 4c. `tests/brokerage/futures/test_contract_spec_identity.py`

- `test_to_contract_identity_returns_dict` — verify shape and fields
- `test_fmp_symbol_populated` — ES → ESUSD, GC → GCUSD
- `test_fmp_symbol_index_mapping` — NKD → ^N225

### 4d. `tests/ibkr/test_compat.py` — Update existing

- Add `test_get_ibkr_futures_contract_meta_includes_multiplier` — verify new function returns multiplier + tick_size
- Add `test_get_ibkr_futures_contract_meta_count_matches_exchanges` — same count as `get_ibkr_futures_exchanges()`
- Existing `test_get_ibkr_futures_exchanges` tests remain unchanged (only exchange + currency)

## 5. Verify Multiplier Values

### Codex R1 Corrections Applied

The following values were corrected based on Codex review with exchange specification references:

| Symbol | Original | Corrected | Source |
|--------|----------|-----------|--------|
| IBV | multiplier: 0.05 | multiplier: 1 | CME Rulebook Chapter 354 — USD-denominated Ibovespa is $1.00 × index |
| DAX | tick_size: 0.5 | tick_size: 1.0 | Eurex DAX futures spec — minimum price change 1 point (EUR 25 tick value for FDAX) |
| ZT | tick_size: 0.0078125 | tick_size: 0.00390625 | CME Treasury spec — 2Y note min tick is 1/8 of 1/32 = 0.00390625 |

### Remaining Values to Verify

The following should still be verified against exchange specs before implementation:

| Symbol | Multiplier | Notes |
|--------|-----------|-------|
| MNK | 0.5 | Micro Nikkei — verify CME spec |
| NIY | 500 | Yen-denominated Nikkei — verify CME spec |
| HSI | 50 | Hang Seng — verify HKFE spec |
| PA | 100 | Palladium — verify NYMEX spec |
| BZ | 1000 | Brent Crude — verify NYMEX spec |

The US index (ES, NQ, YM, RTY), metals (GC, SI, HG), energy (CL, NG), and fixed income (ZB, ZN, ZF, ZT) multipliers are standard and well-documented.

## Key Files

| File | Change | Section |
|------|--------|---------|
| `ibkr/exchange_mappings.yaml` | Add multiplier + tick_size to all 27 entries | 1 |
| `ibkr/compat.py` | Add `get_ibkr_futures_contract_meta()` + `get_futures_contract_meta()` | 2 |
| `brokerage/futures/__init__.py` | New — public exports | 3a |
| `brokerage/futures/contract_spec.py` | New — FuturesContractSpec + load + asset class map | 3b |
| `brokerage/futures/notional.py` | New — standalone notional/point/tick functions | 3c |
| `tests/brokerage/futures/test_contract_spec.py` | New — spec loading + field verification + edge contracts | 4a |
| `tests/brokerage/futures/test_notional.py` | New — notional + P&L math | 4b |
| `tests/brokerage/futures/test_contract_spec_identity.py` | New — contract_identity export + FMP mapping | 4c |
| `tests/ibkr/test_compat.py` | Update — add tests for new contract meta function | 4d |

## Design Decisions

1. **`FuturesContractSpec` is frozen** — Contract specifications are immutable exchange-defined constants. No mutation after construction.
2. **Asset class map is hardcoded** — 27 contracts, well-defined categories. Not worth a YAML lookup for this small a set. Easy to extend inline. Test ensures full coverage (no silent defaults).
3. **`load_contract_specs()` imports from `ibkr.compat`** — Follows the established pattern where `portfolio_risk_engine/` already imports from `ibkr.compat` (line 617 of `data_objects.py`). Deliberate dependency from broker-agnostic domain model to IBKR metadata source — IBKR is the only futures data source. No direct `ibkr/` internal imports.
4. **Standalone notional functions** — Callers that just need "what's the notional for 2 ES at 5600?" don't need to import the full spec. Convenience layer.
5. **No caching on `load_contract_specs()`** — YAML is small (27 entries), load is fast. Can add `@lru_cache` later if profiling shows need.
6. **`to_contract_identity()` for threading** — Exports to the existing `InstrumentMeta.contract_identity` dict so futures metadata flows through established paths without new fields.
7. **No pricing in Phase 1** — This phase is pure data model. Pricing dispatch is Phase 2.
