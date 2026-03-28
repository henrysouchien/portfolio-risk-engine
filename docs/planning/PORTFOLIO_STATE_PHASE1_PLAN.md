# F12b Phase 1: Create PortfolioState + get_portfolio_state()

## Context

Phase 1 of the canonical PortfolioState architecture (see `CANONICAL_TRADE_SNAPSHOT_PLAN.md`). Creates new data structures and PositionService method. No existing callers modified — purely additive.

## Implementation

### Step 1: Create `core/result_objects/portfolio_state.py`

```python
"""Canonical portfolio state for trade-path consumption."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any, Dict, Literal, Mapping, Optional

class Scope(str, Enum):
    PORTFOLIO = "portfolio"
    ACCOUNT = "account"

class WeightBasis(str, Enum):
    GROSS_RISK = "gross_risk"
    NET_RISK = "net_risk"
    NET_LIQUIDATION = "net_liquidation"

class CashPolicy(str, Enum):
    EXCLUDE = "exclude"
    SEPARATE = "separate"
    PROXY_FOR_RISK = "proxy_for_risk"

@dataclass(frozen=True)
class AggregatePosition:
    ticker: str
    signed_quantity: float           # raw float, NOT truncated (fractional shares preserved)
    market_value: float              # signed
    mark_price: Optional[float]
    instrument_type: Optional[str]
    currency: Optional[str]
    is_cash: bool
    account_ids: tuple = ()
    sources: tuple = ()

@dataclass(frozen=True)
class ExposureTotals:
    cash: float
    risk_long: float
    risk_short: float
    risk_net: float
    risk_gross: float
    net_liquidation: float

@dataclass(frozen=True)
class PricingContext:
    as_of: datetime
    source: Literal["snapshot", "live"]
    prices: Mapping[str, float] = field(default_factory=lambda: MappingProxyType({}))

@dataclass(frozen=True)
class PortfolioState:
    scope: Scope
    scope_id: Optional[str]
    pricing: PricingContext
    positions: Mapping[str, AggregatePosition]  # MappingProxyType for deep immutability
    totals: ExposureTotals
    raw_positions: tuple = ()
    provider_errors: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))  # {provider: error_msg}

    def weights(self, *, basis: WeightBasis = WeightBasis.GROSS_RISK,
                include_cash: bool = False) -> Dict[str, float]:
        denom = {
            WeightBasis.GROSS_RISK: self.totals.risk_gross,
            WeightBasis.NET_RISK: self.totals.risk_net,
            WeightBasis.NET_LIQUIDATION: self.totals.net_liquidation,
        }[basis]
        if denom == 0:
            return {t: 0.0 for t, p in self.positions.items()
                    if include_cash or not p.is_cash}
        return {
            t: p.market_value / denom
            for t, p in self.positions.items()
            if include_cash or not p.is_cash
        }

    def reprice(self, prices: Dict[str, float], *,
                as_of: Optional[datetime] = None,
                require_complete: bool = False) -> "PortfolioState":
        """Reprice using live prices keyed by TICKER (not dict key).
        For multi-currency positions (key=AAPL:GBP), looks up by pos.ticker (AAPL).

        If require_complete=True, raises ValueError when any non-cash position
        is missing from prices (enforces coherent pricing). Default False for
        backward compatibility.
        """
        # Validate prices first: reject non-finite and non-positive
        valid_prices = {
            t: p for t, p in prices.items()
            if isinstance(p, (int, float)) and math.isfinite(p) and p > 0
        }

        # Positions eligible for repricing: non-cash with nonzero quantity.
        # Zero-qty non-cash positions with value are risk-bearing (in _compute_totals)
        # but NOT repriceable (qty*price=0 would wipe their value). They always keep
        # snapshot pricing and prevent source="live" from being fully accurate.
        repriceable = {
            key for key, pos in self.positions.items()
            if not pos.is_cash and pos.signed_quantity != 0
        }
        unrepriceable_risk = {
            key for key, pos in self.positions.items()
            if not pos.is_cash and pos.signed_quantity == 0 and pos.market_value != 0
        }

        if require_complete:
            missing = sorted({
                self.positions[key].ticker for key in repriceable
                if self.positions[key].ticker not in valid_prices
            })
            if missing:
                raise ValueError(
                    f"Incomplete price set for reprice: missing {', '.join(missing)}. "
                    "Pass require_complete=False to allow mixed snapshot/live pricing."
                )

        new_positions = {}
        repriced_keys = set()
        for key, pos in self.positions.items():
            new_price = valid_prices.get(pos.ticker)
            if new_price is not None and pos.signed_quantity != 0:
                if key in repriceable:
                    repriced_keys.add(key)  # only track non-cash for source determination
                new_positions[key] = AggregatePosition(
                    ticker=pos.ticker,
                    signed_quantity=pos.signed_quantity,  # raw float preserved
                    market_value=pos.signed_quantity * new_price,
                    mark_price=new_price,
                    instrument_type=pos.instrument_type,
                    currency=pos.currency,
                    is_cash=pos.is_cash,
                    account_ids=pos.account_ids,
                    sources=pos.sources,
                )
            else:
                new_positions[key] = pos

        # "live" only if ALL repriceable positions were repriced AND no
        # unrepriceable risk positions exist (they're always snapshot-priced)
        all_repriced = repriced_keys >= repriceable
        source = "live" if all_repriced and not unrepriceable_risk else "snapshot"

        return PortfolioState(
            scope=self.scope,
            scope_id=self.scope_id,
            pricing=PricingContext(
                as_of=as_of or datetime.utcnow(),
                source=source,  # "live" only if ALL repriceable positions repriced
                prices=MappingProxyType(valid_prices),  # store validated prices only
            ),
            positions=MappingProxyType(new_positions),
            totals=_compute_totals(new_positions),
            raw_positions=self.raw_positions,
            provider_errors=self.provider_errors,  # carry forward (already MappingProxyType)
        )

def _compute_totals(positions: Mapping[str, AggregatePosition]) -> ExposureTotals:
    cash = 0.0
    risk_long = 0.0
    risk_short = 0.0
    for pos in positions.values():
        if pos.is_cash:
            cash += pos.market_value
            continue
        # Use quantity sign when available, fall back to value sign for zero-qty
        if pos.signed_quantity > 0:
            risk_long += abs(pos.market_value)
        elif pos.signed_quantity < 0:
            risk_short += abs(pos.market_value)
        elif pos.market_value > 0:
            risk_long += pos.market_value
        elif pos.market_value < 0:
            risk_short += abs(pos.market_value)
        # qty=0 and value=0: skip (contributes nothing)
    risk_net = sum(p.market_value for p in positions.values() if not p.is_cash)
    risk_gross = risk_long + risk_short
    return ExposureTotals(
        cash=cash, risk_long=risk_long, risk_short=risk_short,
        risk_net=risk_net, risk_gross=risk_gross,
        net_liquidation=risk_net + cash,
    )

def _is_cash(position: Dict[str, Any], ticker: str) -> bool:
    """Shared cash detection — matches PortfolioData.to_portfolio_data() logic."""
    position_type = str(position.get("type") or "").strip().lower()
    return (
        position_type == "cash"
        or ticker.startswith("CUR:")
        or position.get("is_cash_equivalent") is True
    )
```

Key design decisions:
- **`signed_quantity` stores raw float** — NOT truncated. Fractional shares are preserved for correct `reprice()`. Callers that need integer quantities (trade legs) apply `math.trunc` themselves.
- **`MappingProxyType`** for `positions` and `prices` — prevents dict mutation. `raw_positions` is a tuple of dicts — the dicts themselves remain mutable (deep-freezing every dict would be expensive for a diagnostic-only field). Document in docstring that `raw_positions` should not be mutated.
- **`_is_cash` includes `is_cash_equivalent`** — matches `data_objects.py:533-537` logic.
- **Zero-qty classification** uses `market_value` sign, not quantity sign, to avoid misclassification.
- **Aggregation key is `(ticker, currency)`** — multi-currency same-ticker positions kept separate with `ticker:CURRENCY` key format. `reprice()` looks up prices by `pos.ticker` (not dict key) so AAPL:GBP reprices from the AAPL price entry.
- **`account_ids` and `sources` are best-effort** — when `consolidate=True`, PositionService's cross-provider consolidation may flatten account_ids to "first" and join sources with commas. These fields are metadata for debugging, not for trade logic.

### Step 2: Add `get_portfolio_state()` to PositionService

**File**: `services/position_service.py`

```python
def get_portfolio_state(
    self, *, account: Optional[str] = None,
) -> "PortfolioState":
    from core.result_objects.portfolio_state import (
        AggregatePosition, PricingContext, PortfolioState,
        Scope, _compute_totals, _is_cash,
    )
    from types import MappingProxyType
    from mcp_tools.trading_helpers import normalize_ticker, safe_float

    # Use consolidate=False to preserve per-account position granularity.
    # consolidate=True nets opposite-signed same-ticker positions across
    # accounts ($100k long AAPL in A + $20k short AAPL in B → $80k net),
    # which understates gross exposure for long/short portfolios.
    #
    # For account-scoped calls (the primary trade-path use case), this
    # returns single-provider data with no cross-provider duplication.
    # For whole-portfolio calls (account=None), cross-provider cash
    # duplication is possible but acceptable — cash is excluded from
    # risk exposure calculations (only affects net_liquidation).
    result = self.get_all_positions(
        use_cache=True, force_refresh=False,
        consolidate=False, account=account,
    )
    raw_positions = list(getattr(result.data, "positions", []) or [])

    # Dedup cross-provider duplicates: for the same (ticker, currency, canonical_account),
    # keep the row with the largest absolute value (most authoritative source).
    # Uses _canonical_account_key to collapse alias-equivalent account IDs
    # (e.g., UUID vs U2471778 for the same IBKR account).
    from services.position_service import _canonical_account_key
    seen: Dict[tuple, Dict[str, Any]] = {}
    for position in raw_positions:
        ticker = normalize_ticker(position.get("ticker"))
        currency = str(position.get("currency") or "").strip().upper() or None
        raw_account = str(position.get("account_id") or "").strip()
        canonical_account = _canonical_account_key(raw_account) if raw_account else ""
        source = str(position.get("position_source") or "").strip().lower()
        # Namespace by source to prevent cross-brokerage collisions
        # (Schwab acct-1 AAPL ≠ Fidelity acct-1 AAPL)
        dedup_key = (ticker, currency, canonical_account, source)
        existing = seen.get(dedup_key)
        val = abs(safe_float(position.get("value")) or 0.0)
        if existing is None or val > abs(safe_float(existing.get("value")) or 0.0):
            seen[dedup_key] = position
    deduped_positions = list(seen.values())

    # Aggregate by (ticker, currency) — preserves multi-currency separation
    agg: Dict[tuple, dict] = {}
    for position in deduped_positions:
        ticker = normalize_ticker(position.get("ticker"))
        if not ticker:
            continue
        value = safe_float(position.get("value"))
        if value is None:
            continue

        quantity = safe_float(position.get("quantity")) or 0.0
        is_cash = _is_cash(position, ticker)
        position_type = str(position.get("type") or "").strip().lower() or None
        currency = str(position.get("currency") or "").strip().upper() or None
        # Derive USD mark_price from value/quantity (both USD after repricing).
        # Validate: must be finite and positive (matching reprice validation).
        raw_price = safe_float(position.get("price"))
        if raw_price is None and quantity and quantity != 0:
            raw_value = safe_float(position.get("value"))
            if raw_value is not None:
                raw_price = abs(raw_value / quantity)
        # Null out invalid prices (0.0, negative, non-finite)
        if raw_price is not None and (not math.isfinite(raw_price) or raw_price <= 0):
            raw_price = None
        price = raw_price
        account_id = str(position.get("account_id") or "").strip()
        source = str(position.get("position_source") or "").strip()

        key = (ticker, currency)
        if key not in agg:
            agg[key] = {
                "ticker": ticker, "value": 0.0, "quantity": 0.0,
                "instrument_type": position_type, "currency": currency,
                "is_cash": is_cash, "price": price,
                "account_ids": set(), "sources": set(),
            }
        agg[key]["value"] += value
        agg[key]["quantity"] += quantity
        # Merge is_cash with any() — if ANY row for this ticker is cash, treat as cash
        # (matches position_service consolidation behavior)
        agg[key]["is_cash"] = agg[key]["is_cash"] or is_cash
        if account_id:
            agg[key]["account_ids"].add(account_id)
        if source:
            agg[key]["sources"].add(source)

    # Build AggregatePosition objects — key in dict is ticker for single-currency,
    # ticker:currency for multi-currency same-ticker
    positions = {}
    ticker_currencies: Dict[str, list] = {}
    for (ticker, currency), data in agg.items():
        ticker_currencies.setdefault(ticker, []).append(currency)

    for (ticker, currency), data in agg.items():
        # Use ticker as key if single currency, ticker:CURRENCY if multi
        if len(ticker_currencies.get(ticker, [])) > 1 and currency:
            pos_key = f"{ticker}:{currency}"
        else:
            pos_key = ticker

        # Recompute mark_price from aggregated value/quantity (handles multi-row
        # aggregation where first row may have None/0 price but later rows don't).
        agg_qty = data["quantity"]
        agg_val = data["value"]
        if agg_qty and agg_qty != 0:
            computed_price = abs(agg_val / agg_qty)
            if not math.isfinite(computed_price) or computed_price <= 0:
                computed_price = None
        else:
            computed_price = data["price"]  # fallback to stored price for zero-qty

        positions[pos_key] = AggregatePosition(
            ticker=ticker,
            signed_quantity=agg_qty,  # raw float, no truncation
            market_value=agg_val,
            mark_price=computed_price,
            instrument_type=data["instrument_type"],
            currency=data["currency"],
            is_cash=data["is_cash"],
            account_ids=tuple(sorted(data["account_ids"])),
            sources=tuple(sorted(data["sources"])),
        )

    totals = _compute_totals(positions)
    # Key prices by pos.ticker (not dict key) for reprice() compatibility
    # Apply same validation as reprice(): finite and positive only
    price_map: Dict[str, float] = {}
    for p in positions.values():
        if (p.mark_price is not None
                and isinstance(p.mark_price, (int, float))
                and math.isfinite(p.mark_price)
                and p.mark_price > 0
                and p.ticker not in price_map):
            price_map[p.ticker] = p.mark_price
    pricing = PricingContext(
        as_of=datetime.utcnow(),
        source="snapshot",
        prices=MappingProxyType(price_map),
    )

    # Surface provider errors for fail-closed support (dict: provider → error message)
    raw_errors = getattr(result, 'provider_errors', None) or {}
    provider_errors = MappingProxyType(dict(raw_errors) if isinstance(raw_errors, dict) else {})

    return PortfolioState(
        scope=Scope.ACCOUNT if account else Scope.PORTFOLIO,
        scope_id=account,
        pricing=pricing,
        positions=MappingProxyType(positions),
        totals=totals,
        raw_positions=tuple(raw_positions),
        provider_errors=provider_errors,
    )
```

### Step 3: Update `core/result_objects/__init__.py`

Add: `from .portfolio_state import PortfolioState` and `"PortfolioState"` to `__all__`.

### Step 4: Tests

**New file**: `tests/services/test_portfolio_state.py` (44 tests)

**Data structures:**
1. `test_basic_long_only` — 3 equities + 1 cash → 3 non-cash positions, cash in totals.cash
2. `test_short_positions_preserved` — negative value/quantity flows through
3. `test_cash_detection_type` — type=cash → is_cash=True
4. `test_cash_detection_cur_prefix` — CUR:USD → is_cash=True
5. `test_cash_detection_equivalent` — is_cash_equivalent=True → is_cash=True

**Exposure totals:**
6. `test_exposure_totals_long_only` — risk_gross == risk_net == risk_long, risk_short == 0
7. `test_exposure_totals_mixed` — $100k long + $20k short → gross=120k, net=80k
8. `test_exposure_totals_all_short` — all short → risk_long=0, risk_net<0
9. `test_exposure_zero_qty_uses_value_sign` — qty=0, value>0 → risk_long. qty=0, value<0 → risk_short

**Weights:**
10. `test_weights_gross_basis` — GROSS_RISK: value / risk_gross
11. `test_weights_net_basis` — NET_RISK: value / risk_net
12. `test_weights_net_liquidation_basis` — NET_LIQUIDATION: value / (risk_net + cash)
13. `test_weights_exclude_cash_default` — cash not in output
14. `test_weights_include_cash` — include_cash=True
15. `test_weights_zero_denominator` — all weights 0.0
16. `test_long_only_gross_equals_net` — regression: GROSS weights == NET weights for pure long

**Reprice:**
17. `test_reprice_updates_values` — new value = signed_quantity * new_price
18. `test_reprice_preserves_fractional_qty` — 10.3 shares × $100 = $1030 (not $1000)
19. `test_reprice_returns_new_state` — original unchanged
20. `test_reprice_recomputes_totals` — new totals reflect new prices

**Aggregation:**
21. `test_ticker_aggregation_same_currency` — two rows for AAPL/USD summed
22. `test_multi_currency_same_ticker_kept_separate` — AAPL/USD + AAPL/GBP → two positions (AAPL, AAPL:GBP)
23. `test_multi_currency_reprice_uses_ticker` — AAPL:GBP reprices from prices["AAPL"] (not prices["AAPL:GBP"])

**Scoping:**
23. `test_account_scoped` — scope=ACCOUNT, scope_id set
24. `test_portfolio_scoped` — scope=PORTFOLIO, scope_id=None

**Immutability:**
25. `test_positions_dict_immutable` — MappingProxyType raises TypeError on mutation
26. `test_provider_errors_preserved_as_dict` — provider_errors is a dict {provider: msg}, not just keys. Error messages accessible.
27. `test_pricing_context_keyed_by_ticker` — state.pricing.prices keyed by ticker (AAPL), not dict key (AAPL:GBP)
28. `test_provider_errors_surfaced` — provider failure → state.provider_errors non-empty, positions may be empty
29. `test_reprice_carries_provider_errors` — repriced state retains provider_errors from original
30. `test_mark_price_derived_from_value_qty` — position with no price field but value=$500, qty=10 → mark_price=50.0
31. `test_reprice_require_complete_raises_on_missing` — require_complete=True + missing ticker → ValueError
32. `test_reprice_partial_marks_source_snapshot` — partial prices → source="snapshot" (not "live")
33. `test_reprice_complete_marks_source_live` — all non-cash prices provided → source="live"
34. `test_reprice_rejects_invalid_prices` — nan/inf/0/negative prices ignored, position keeps snapshot value
35. `test_reprice_cash_updates_when_price_provided` — cash position with FX rate reprices correctly
36. `test_unconsolidated_preserves_cross_account_gross` — long $100k AAPL in acct A + short $20k AAPL in acct B → gross=$120k (not $80k net)
37. `test_unrepriceable_risk_prevents_live_source` — zero-qty position with value → source stays "snapshot" even if all other positions repriced
38. `test_initial_snapshot_prices_validated` — position with price=0.0 → excluded from pricing.prices AND mark_price=None on AggregatePosition
39. `test_cross_provider_dedup` — same AAPL/USD/account from two providers → only one position (highest abs value kept)
40. `test_cross_provider_different_accounts_not_deduped` — AAPL/USD in acct A + AAPL/USD in acct B → two separate entries
41. `test_cross_provider_dedup_alias_ids` — same AAPL from UUID account + U2471778 account (alias pair) → deduped to one
42. `test_aggregated_mark_price_recomputed` — two rows for AAPL: first has price=None, second has price=100. Aggregated mark_price = value/qty (not None from first row)
43. `test_dedup_cross_brokerage_no_collision` — Schwab acct-1 AAPL + Fidelity acct-1 AAPL → both preserved (different source in dedup key)
44. `test_is_cash_merged_across_rows` — two rows for same ticker: first has is_cash=False, second has is_cash_equivalent=True → aggregated is_cash=True

## Files Changed

| File | Change |
|------|--------|
| `core/result_objects/portfolio_state.py` | New — all data structures + enums |
| `core/result_objects/__init__.py` | Add PortfolioState export |
| `services/position_service.py` | Add get_portfolio_state() method |
| `tests/services/test_portfolio_state.py` | New — 33 tests |

## NOT Changed

- No existing callers migrated
- No existing functions removed
- `project()` and `to_portfolio_data()` deferred to Phase 2+

## Verification

1. `pytest tests/services/test_portfolio_state.py -v`
2. `pytest tests/ -x -q --timeout=60` (full regression — purely additive, nothing should break)
