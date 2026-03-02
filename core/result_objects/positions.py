"""Positions result objects."""

from typing import Dict, Any, Optional, List, Union, Tuple
import numbers
import math
import pandas as pd
from datetime import datetime, UTC
import json
import numpy as np
from dataclasses import dataclass, field
from utils.serialization import make_json_safe
from core.data_objects import PositionsData
from ._helpers import _convert_to_json_serializable, _clean_nan_values

@dataclass
class PositionResult:
    """
    Transport/serialization layer for position data.

    Called by:
    - Position/routing services that return normalized holdings payloads.

    Used by:
    - API routes, Claude tools, and downstream analyzers expecting stable
      ``to_api_response`` / ``to_cli_report`` contracts.

    Wraps PositionsData and adds:
    - to_api_response() for API/MCP envelope
    - to_cli_report() for terminal display
    - to_summary() for quick responses
    - Computed summaries (total_value, by_type, etc.)
    - Strict validation inherited from PositionsData (fail-fast)
    """

    # Wrapped data object
    data: PositionsData

    # Error handling
    status: str = "success"  # "success" or "error"
    error_message: Optional[str] = None

    # Computed summaries (set in __post_init__)
    total_value: float = 0.0
    position_count: int = 0
    by_type: Dict[str, int] = field(default_factory=dict)
    by_source: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Compute summary statistics from wrapped data."""
        if self.data is None:
            raise ValueError("PositionResult requires data")
        positions = self.data.positions
        if positions is None:
            raise ValueError("PositionResult data.positions cannot be None")
        self.position_count = len(positions)
        self.total_value = 0.0
        for idx, position in enumerate(positions):
            raw_value = position.get("value")
            if raw_value is None:
                raise ValueError(f"positions[{idx}].value is required")
            if isinstance(raw_value, bool) or not isinstance(raw_value, numbers.Real):
                raise ValueError(f"positions[{idx}].value must be numeric")
            if math.isnan(float(raw_value)) or not np.isfinite(float(raw_value)):
                raise ValueError(f"positions[{idx}].value must be finite")
            self.total_value += float(raw_value)

        self.by_type = {}
        for idx, position in enumerate(positions):
            pos_type = position.get("type")
            if not isinstance(pos_type, str) or not pos_type.strip():
                raise ValueError(f"positions[{idx}].type must be a non-empty string")
            self.by_type[pos_type] = self.by_type.get(pos_type, 0) + 1

        self.by_source = {}
        for idx, position in enumerate(positions):
            raw_source = position.get("position_source")
            if not isinstance(raw_source, str) or not raw_source.strip():
                raise ValueError(f"positions[{idx}].position_source must be a non-empty string")
            for src in raw_source.split(","):
                if not src.strip():
                    raise ValueError(f"positions[{idx}] contains empty source entry")
                src = src.strip()
                self.by_source[src] = self.by_source.get(src, 0) + 1

    @classmethod
    def from_dataframe(
        cls,
        df: pd.DataFrame,
        user_email: str,
        sources: Optional[List[str]] = None,
        *,
        consolidated: bool = True,
        as_of: Optional[datetime] = None,
        from_cache: bool = False,
        cache_age_hours: Optional[float] = None,
    ) -> "PositionResult":
        """Create PositionResult from a DataFrame."""
        data = PositionsData.from_dataframe(
            df,
            user_email=user_email,
            sources=sources,
            consolidated=consolidated,
            as_of=as_of,
            from_cache=from_cache,
            cache_age_hours=cache_age_hours,
        )
        return cls(data=data)

    @classmethod
    def from_error(cls, error_msg: str, user_email: str) -> "PositionResult":
        """Create an error result for API/MCP boundary handling."""
        data = PositionsData(
            positions=[],
            user_email=user_email,
            sources=[],
            consolidated=True,
            as_of=datetime.now(),
        )
        return cls(data=data, status="error", error_message=error_msg)

    def to_api_response(self) -> Dict[str, Any]:
        """
        JSON response for MCP tools, CLI --format json, and API endpoints.

        Uses standard envelope format for AI consumption.
        """
        timestamp = (
            self.data.as_of.isoformat()
            if isinstance(self.data.as_of, datetime)
            else str(self.data.as_of)
        )

        if self.status == "error":
            payload = {
                "module": "positions",
                "version": "1.0",
                "timestamp": timestamp,
                "status": "error",
                "error": self.error_message,
                "metadata": {
                    "user_email": self.data.user_email,
                    "sources": self.data.sources,
                },
            }
            return make_json_safe(payload)

        payload = {
            "module": "positions",
            "version": "1.0",
            "timestamp": timestamp,
            "status": "success",
            "metadata": {
                "user_email": self.data.user_email,
                "sources": self.data.sources,
                "position_count": self.position_count,
                "total_value": round(self.total_value, 2),
                "consolidated": self.data.consolidated,
                "from_cache": self.data.from_cache,
                "cache_age_hours": self.data.cache_age_hours,
                "as_of": timestamp,
            },
            "data": {
                "positions": self.data.positions,
                "summary": {
                    "total_positions": self.position_count,
                    "total_value": round(self.total_value, 2),
                    "by_type": self.by_type,
                    "by_source": self.by_source,
                },
            },
            "chain": {
                "can_chain_to": ["run_analyze", "run_score", "run_optimize", "run_performance"],
                "portfolio_data_compatible": True,
            },
        }
        if hasattr(self, "_cache_metadata"):
            payload["metadata"]["cache_by_provider"] = self._cache_metadata
        return make_json_safe(payload)

    def to_portfolio_data(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        portfolio_name: str = "CURRENT_PORTFOLIO",
    ):
        """Delegate to wrapped PositionsData."""
        return self.data.to_portfolio_data(
            start_date=start_date,
            end_date=end_date,
            portfolio_name=portfolio_name,
        )

    def to_cli_report(self) -> str:
        """Human-readable formatted output for terminal display."""
        lines = []
        lines.append("=" * 120)
        lines.append(f"  PORTFOLIO POSITIONS - {self.data.user_email}")
        as_of = (
            self.data.as_of.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(self.data.as_of, datetime)
            else str(self.data.as_of)
        )
        sources = ", ".join(self.data.sources)
        lines.append(f"  As of: {as_of}")
        lines.append(f"  Sources: {sources}")
        lines.append("=" * 120)
        lines.append("")

        by_type_positions: Dict[str, List[Dict[str, Any]]] = {}
        for position in self.data.positions:
            pos_type = position["type"]
            by_type_positions.setdefault(pos_type, []).append(position)

        type_order = ["equity", "etf", "mutual_fund", "bond", "option", "cash", "other"]
        type_labels = {
            "equity": "EQUITIES",
            "etf": "ETFs",
            "mutual_fund": "MUTUAL FUNDS",
            "bond": "BONDS",
            "option": "OPTIONS",
            "cash": "CASH",
            "other": "OTHER",
        }

        def _format_number(value: Any, decimals: int = 2) -> str:
            """Format number for display. Returns empty string for None/missing optional fields."""
            if value is None:
                return ""
            try:
                numeric = float(value)
                if numeric != numeric:  # NaN check
                    return ""
                return f"{numeric:,.{decimals}f}"
            except (TypeError, ValueError):
                return ""

        def _truncate(s: Any, max_len: int) -> str:
            """Truncate string to max length for display."""
            if s is None:
                return ""
            s = str(s)
            return s[:max_len] if len(s) > max_len else s

        remaining_types = sorted([t for t in by_type_positions.keys() if t not in type_order])
        for pos_type in type_order + remaining_types:
            if pos_type not in by_type_positions:
                continue
            positions = by_type_positions[pos_type]
            lines.append(f"{type_labels.get(pos_type, pos_type.upper())} ({len(positions)} positions)")
            lines.append("-" * 120)
            lines.append(
                f"{'Ticker':<8} {'Name':<20} {'Qty':>10} {'Price ($)':>10} "
                f"{'Value ($)':>12} {'Basis ($)':>12} {'Ccy':<5} {'Brokerage':<15} {'Account':<15}"
            )
            lines.append("-" * 120)

            for position in sorted(positions, key=lambda x: x["value"], reverse=True):
                ticker = _truncate(position.get("ticker", ""), 8)
                name = _truncate(position.get("name", ""), 20)
                qty = _format_number(position.get("quantity"), 2)
                price = _format_number(position.get("price"), 2)
                value = _format_number(position.get("value"), 2)
                cost_basis = _format_number(position.get("cost_basis_usd"), 2)
                ccy = position.get("original_currency") or position.get("currency") or "USD"
                brokerage = _truncate(position.get("brokerage_name", ""), 15)
                account = _truncate(position.get("account_name", ""), 15)

                lines.append(
                    f"{ticker:<8} {name:<20} {qty:>10} {price:>10} "
                    f"{value:>12} {cost_basis:>12} {ccy:<5} {brokerage:<15} {account:<15}"
                )

            # Totals row for this type group (all USD)
            tot_value = sum(p.get("value") or 0 for p in positions)
            tot_cb = sum(float(p.get("cost_basis_usd") or 0) for p in positions)
            lines.append("-" * 120)
            lines.append(
                f"{'TOTAL':<8} {'':<20} {'':>10} {'':>10} "
                f"{_format_number(tot_value, 2):>12} {_format_number(tot_cb, 2):>12} {'':<5} {'':<15} {'':<15}"
            )
            lines.append("")

        lines.append("=" * 120)
        lines.append("SUMMARY")
        lines.append("-" * 120)
        lines.append(f"Total Positions:  {self.position_count}")
        lines.append(f"Total Value:      ${self.total_value:,.2f}")
        lines.append(f"By Type:          {self.by_type}")
        lines.append(f"By Source:        {self.by_source}")
        lines.append("=" * 120)
        return "\n".join(lines)

    @staticmethod
    def _safe_float(value: Any) -> Optional[float]:
        """Convert to float if possible and finite; otherwise return None."""
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric):
            return None
        return numeric

    @staticmethod
    def _is_valid_cost_basis(cost_basis: Any) -> bool:
        """Check if cost_basis is valid (not None, NaN, Inf, or zero)."""
        cb_float = PositionResult._safe_float(cost_basis)
        if cb_float is None:
            return False
        if cb_float == 0:
            return False
        return True

    @staticmethod
    def _is_valid_price(price: Any) -> bool:
        """Check if price is valid for P&L calculation (not None, NaN, or Inf)."""
        return PositionResult._safe_float(price) is not None

    def _build_monitor_payload(self, by_account: bool = False) -> Dict[str, Any]:
        """Build the monitor payload with exposure and P&L metrics (cash excluded).

        Notes:
        - Cash positions are excluded before processing.
        - Summary totals are grouped by currency.
        - Missing/invalid cost_basis, price, or quantity are handled without
          contaminating summary totals (positions are counted and flagged).
        """
        timestamp = (
            self.data.as_of.isoformat()
            if isinstance(self.data.as_of, datetime)
            else str(self.data.as_of)
        )

        positions = self.data.positions or []
        cash_positions = [p for p in positions if p.get("type") == "cash"]
        monitor_positions = [p for p in positions if p.get("type") != "cash"]

        processed_positions: List[Dict[str, Any]] = []
        summary_by_currency: Dict[str, Dict[str, Any]] = {}

        for position in monitor_positions:
            quantity = self._safe_float(position.get("quantity"))
            value = self._safe_float(position.get("value"))
            local_value = self._safe_float(position.get("local_value"))
            cost_basis = position.get("cost_basis")
            cost_basis_usd = position.get("cost_basis_usd")
            raw_price_input = position.get("local_price")
            currency = position.get("original_currency") or position.get("currency")
            using_usd_basis_fallback = False

            if raw_price_input is None:
                raw_price_input = position.get("price")
                local_value = value
                # If local pricing context is unavailable, avoid mixing USD price
                # with local-currency cost basis by switching to USD basis.
                if self._is_valid_cost_basis(cost_basis_usd):
                    cost_basis = cost_basis_usd
                    using_usd_basis_fallback = True

            valid_cost_basis = self._is_valid_cost_basis(cost_basis)
            valid_price = self._is_valid_price(raw_price_input)
            valid_quantity = quantity is not None and quantity != 0

            raw_price = None
            display_price = None
            if valid_price:
                raw_price = float(raw_price_input)
                display_price = abs(raw_price)
            elif valid_quantity and value is not None:
                raw_price = value / quantity
                display_price = abs(raw_price)

            entry_price = None
            if valid_cost_basis and valid_quantity:
                entry_price = abs(float(cost_basis)) / abs(quantity)

            entry_price_warning = False
            if entry_price is not None and display_price not in (None, 0):
                ratio = entry_price / display_price
                if ratio > 10 or ratio < 0.1:
                    entry_price_warning = True

            dollar_pnl = None
            pnl_percent = None
            if entry_price is not None and raw_price is not None and valid_quantity:
                # NOTE: P&L uses (price - entry_price) * quantity instead of value - cost_basis.
                # This is provider-agnostic and works regardless of how Plaid/SnapTrade sign
                # value and cost_basis for short positions.
                dollar_pnl = (raw_price - entry_price) * quantity
                pnl_percent = (dollar_pnl / abs(float(cost_basis))) * 100 if valid_cost_basis else None

            pnl_usd = None
            if (
                dollar_pnl is not None
                and value is not None
                and local_value is not None
                and local_value != 0
            ):
                fx_ratio = value / local_value
                pnl_usd = dollar_pnl * fx_ratio

            direction = None
            if valid_quantity and quantity > 0:
                direction = "LONG"
            elif valid_quantity and quantity < 0:
                direction = "SHORT"

            # Normalize currency at position level to match summary bucketing
            normalized_currency = currency if currency else "UNKNOWN"

            entry = {
                "ticker": position.get("ticker"),
                "name": position.get("name"),
                "type": position.get("type"),
                "currency": normalized_currency,
                "direction": direction,
                "quantity": quantity,
                "shares": abs(quantity) if quantity is not None else None,
                "entry_price": entry_price,
                "weighted_entry_price": entry_price,
                "current_price": display_price,
                "cost_basis": float(cost_basis) if valid_cost_basis else None,
                "cost_basis_usd": self._safe_float(cost_basis_usd),
                "gross_exposure": abs(value) if value is not None else None,
                "net_exposure": value,
                "gross_exposure_local": abs(local_value) if local_value is not None else None,
                "net_exposure_local": local_value,
                "pnl": dollar_pnl,
                "dollar_pnl": dollar_pnl,
                "pnl_percent": pnl_percent,
                "pnl_usd": pnl_usd,
                "pnl_basis_currency": "USD" if using_usd_basis_fallback else "local",
                "entry_price_warning": entry_price_warning,
            }

            if by_account:
                entry["account_name"] = position.get("account_name")
                entry["brokerage_name"] = position.get("brokerage_name")

            processed_positions.append(entry)

            summary = summary_by_currency.setdefault(
                normalized_currency,
                {
                    "long_count": 0,
                    "short_count": 0,
                    "long_exposure": 0.0,
                    "short_exposure": 0.0,
                    "gross_exposure": 0.0,
                    "net_exposure": 0.0,
                    "long_exposure_local": 0.0,
                    "short_exposure_local": 0.0,
                    "gross_exposure_local": 0.0,
                    "net_exposure_local": 0.0,
                    "total_cost_basis": 0.0,
                    # pnl_contributing_cost_basis: only positions where P&L was calculated
                    # Used as denominator for total_pnl_percent to avoid dilution
                    "pnl_contributing_cost_basis": 0.0,
                    "total_pnl": 0.0,
                    "total_pnl_usd": 0.0,
                    "total_pnl_percent": None,
                    "position_count": 0,
                    "positions_missing_cost_basis": 0,
                    "positions_missing_price_or_quantity": 0,
                },
            )

            summary["position_count"] += 1
            if value is not None:
                summary["gross_exposure"] += abs(value)
                summary["net_exposure"] += value
            if local_value is not None:
                summary["gross_exposure_local"] += abs(local_value)
                summary["net_exposure_local"] += local_value

            if valid_quantity and quantity > 0:
                summary["long_count"] += 1
                if value is not None:
                    summary["long_exposure"] += abs(value)
                if local_value is not None:
                    summary["long_exposure_local"] += abs(local_value)
            elif valid_quantity and quantity < 0:
                summary["short_count"] += 1
                if value is not None:
                    summary["short_exposure"] += abs(value)
                if local_value is not None:
                    summary["short_exposure_local"] += abs(local_value)

            if valid_cost_basis:
                summary["total_cost_basis"] += abs(float(cost_basis))
                if dollar_pnl is not None:
                    # Only include in pnl_contributing_cost_basis when P&L was calculated
                    summary["pnl_contributing_cost_basis"] += abs(float(cost_basis))
                    summary["total_pnl"] += dollar_pnl
                    if pnl_usd is not None:
                        summary["total_pnl_usd"] += pnl_usd
                else:
                    summary["positions_missing_price_or_quantity"] += 1
            else:
                summary["positions_missing_cost_basis"] += 1

        # Calculate total_pnl_percent using pnl_contributing_cost_basis (not total_cost_basis)
        # to avoid dilution from positions missing price/quantity
        for currency, summary in summary_by_currency.items():
            pnl_cost_basis = summary["pnl_contributing_cost_basis"]
            if pnl_cost_basis:
                summary["total_pnl_percent"] = (summary["total_pnl"] / pnl_cost_basis) * 100
            else:
                summary["total_pnl_percent"] = None
            summary["total_pnl_dollars"] = summary["total_pnl"]
            summary["unrealized_pnl_dollars"] = summary["total_pnl_dollars"]
            summary["unrealized_pnl"] = summary["total_pnl"]
            summary["unrealized_pnl_percent"] = summary["total_pnl_percent"]

        primary_currency = None
        if summary_by_currency:
            primary_currency = max(
                summary_by_currency.items(),
                key=lambda item: item[1]["gross_exposure"],
            )[0]

        has_multiple_currencies = len(summary_by_currency) > 1
        total_positions = len(monitor_positions)
        total_missing_cost_basis = sum(
            summary["positions_missing_cost_basis"] for summary in summary_by_currency.values()
        )
        total_missing_price_or_quantity = sum(
            summary["positions_missing_price_or_quantity"] for summary in summary_by_currency.values()
        )

        portfolio_totals_usd = {
            "gross_exposure": 0.0,
            "net_exposure": 0.0,
            "long_exposure": 0.0,
            "short_exposure": 0.0,
            "total_pnl_usd": 0.0,
        }
        for position in processed_positions:
            gross = position.get("gross_exposure")
            net = position.get("net_exposure")
            qty = position.get("quantity")
            if gross is not None:
                portfolio_totals_usd["gross_exposure"] += gross
            if net is not None:
                portfolio_totals_usd["net_exposure"] += net
                if qty is not None and qty > 0:
                    portfolio_totals_usd["long_exposure"] += abs(net)
                elif qty is not None and qty < 0:
                    portfolio_totals_usd["short_exposure"] += abs(net)
            pnl_usd_val = position.get("pnl_usd")
            if pnl_usd_val is not None:
                portfolio_totals_usd["total_pnl_usd"] += pnl_usd_val

        payload = {
            "status": "success",
            "module": "positions",
            "view": "monitor",
            "timestamp": timestamp,
            "exposure_currency": "USD",
            "price_pnl_currency": "local",
            "values_currency": "USD",
            "summary": {
                "by_currency": summary_by_currency,
                "primary_currency": primary_currency,
                "has_multiple_currencies": has_multiple_currencies,
                "has_partial_cost_basis": total_missing_cost_basis > 0,
                "total_positions": total_positions,
                "cash_positions_excluded": len(cash_positions),
                "positions_missing_price_or_quantity": total_missing_price_or_quantity,
                "portfolio_totals_usd": portfolio_totals_usd,
            },
            "positions": processed_positions,
            "metadata": {
                "consolidated": self.data.consolidated,
                "by_account": by_account,
                "sources": self.data.sources,
                "from_cache": self.data.from_cache,
                "cache_age_hours": self.data.cache_age_hours,
            },
        }
        if hasattr(self, "_cache_metadata"):
            payload["metadata"]["cache_by_provider"] = self._cache_metadata

        return payload

    def to_monitor_view(self, by_account: bool = False) -> Dict[str, Any]:
        """Position monitor with exposure and P&L metrics."""
        timestamp = (
            self.data.as_of.isoformat()
            if isinstance(self.data.as_of, datetime)
            else str(self.data.as_of)
        )

        if self.status == "error":
            payload = {
                "status": "error",
                "module": "positions",
                "view": "monitor",
                "timestamp": timestamp,
                "error": self.error_message,
                "metadata": {
                    "user_email": self.data.user_email,
                    "sources": self.data.sources,
                },
            }
            return make_json_safe(payload)

        payload = self._build_monitor_payload(by_account=by_account)
        return make_json_safe(payload)

    def get_top_holdings(self, n: int = 10) -> List[Dict[str, Any]]:
        """Return top N non-cash positions sorted by absolute value."""
        if n <= 0:
            return []

        non_cash = [
            position
            for position in (self.data.positions or [])
            if position.get("type") != "cash"
            and not str(position.get("ticker", "")).startswith("CUR:")
        ]
        sorted_positions = sorted(
            non_cash,
            key=lambda p: abs(float(p.get("value", 0) or 0)),
            reverse=True,
        )
        total_value = abs(self.total_value) if self.total_value else 0.0

        holdings: List[Dict[str, Any]] = []
        for position in sorted_positions[:n]:
            value = float(position.get("value", 0) or 0)
            weight_pct = (abs(value) / total_value * 100.0) if total_value else 0.0
            holdings.append(
                {
                    "ticker": position.get("ticker"),
                    "weight_pct": round(weight_pct, 1),
                    "value": round(value, 2),
                    "type": position.get("type"),
                }
            )
        return holdings

    def get_exposure_snapshot(self) -> Dict[str, Any]:
        """Return compact exposure breakdown for agent-oriented responses."""
        positions = self.data.positions or []

        net_exposure = 0.0
        gross_exposure = 0.0
        long_value = 0.0
        short_positions_value = 0.0  # actual short equity/ETF positions
        cash_balance = 0.0  # positive cash (settled, sweep, etc.)
        margin_debt = 0.0  # negative cash = borrowed funds
        investable_count = 0
        currency_totals: Dict[str, float] = {}

        for position in positions:
            ticker = str(position.get("ticker", ""))
            position_type = str(position.get("type", ""))
            raw_value = position.get("value", 0) or 0
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue

            is_cash = position_type == "cash" or ticker.startswith("CUR:")
            if is_cash:
                if value >= 0:
                    cash_balance += value
                    # Positive cash excluded from exposure (matches risk.py)
                    continue
                else:
                    margin_debt += value  # negative number
            else:
                investable_count += 1

            # Negative cash (margin debt) and all non-cash positions contribute to exposure
            net_exposure += value
            gross_exposure += abs(value)
            if not is_cash:
                if value > 0:
                    long_value += value
                elif value < 0:
                    short_positions_value += value  # negative number
                currency = str(position.get("currency") or "USD")
                currency_totals[currency] = currency_totals.get(currency, 0.0) + abs(value)

        leverage = (
            gross_exposure / abs(net_exposure)
            if abs(net_exposure) > 1e-12
            else 1.0
        )

        futures_positions = [
            p for p in positions
            if p.get("notional") is not None
        ]

        futures_exposure = None
        if futures_positions:
            total_notional = sum(
                self._safe_float(p.get("notional", 0)) or 0 for p in futures_positions
            )
            total_margin = sum(
                abs(self._safe_float(p.get("value", 0)) or 0) for p in futures_positions
            )

            by_asset_class: Dict[str, float] = {}
            for p in futures_positions:
                ac = p.get("asset_class", "unknown")
                by_asset_class[ac] = by_asset_class.get(ac, 0.0) + (self._safe_float(p.get("notional", 0)) or 0)

            futures_exposure = {
                "contract_count": len(futures_positions),
                "total_notional": round(total_notional, 2),
                "total_margin": round(total_margin, 2),
                "notional_to_margin": round(total_notional / total_margin, 1) if total_margin > 0 else None,
                "by_asset_class": {
                    ac: round(val, 2) for ac, val in sorted(by_asset_class.items(), key=lambda x: -x[1])
                },
            }

        option_positions = [p for p in positions if bool(p.get("is_option"))]
        options_exposure = None
        portfolio_greeks = None
        if option_positions:
            calls = 0
            puts = 0
            nearest_expiry_dt = None
            nearest_expiry_days = None
            by_underlying: Dict[str, int] = {}
            today = datetime.now(UTC).date()

            for position in option_positions:
                option_type = str(position.get("option_type") or "").strip().lower()
                if option_type == "call":
                    calls += 1
                elif option_type == "put":
                    puts += 1

                underlying = str(position.get("underlying") or "").strip().upper()
                if underlying:
                    by_underlying[underlying] = by_underlying.get(underlying, 0) + 1

                dte_raw = self._safe_float(position.get("days_to_expiry"))
                dte = int(dte_raw) if dte_raw is not None else None

                expiry_dt = None
                expiry_raw = str(position.get("expiry") or "").strip()
                if expiry_raw:
                    for fmt in ("%Y-%m-%d", "%Y%m%d"):
                        try:
                            expiry_dt = datetime.strptime(expiry_raw, fmt).date()
                            break
                        except ValueError:
                            continue

                if dte is None and expiry_dt is not None:
                    dte = (expiry_dt - today).days

                if dte is not None and (nearest_expiry_days is None or dte < nearest_expiry_days):
                    nearest_expiry_days = dte

                if expiry_dt is not None and (
                    nearest_expiry_dt is None or expiry_dt < nearest_expiry_dt
                ):
                    nearest_expiry_dt = expiry_dt

            options_exposure = {
                "option_count": len(option_positions),
                "calls": calls,
                "puts": puts,
                "nearest_expiry": nearest_expiry_dt.isoformat() if nearest_expiry_dt else None,
                "nearest_expiry_days": nearest_expiry_days,
                "by_underlying": {
                    ticker: count
                    for ticker, count in sorted(by_underlying.items(), key=lambda item: (-item[1], item[0]))
                },
            }

            try:
                from options.portfolio_greeks import compute_portfolio_greeks

                portfolio_greeks = compute_portfolio_greeks(option_positions).to_dict()
            except Exception:
                portfolio_greeks = None

        return {
            "total_value": round(self.total_value, 2),
            "position_count": self.position_count,
            "investable_count": investable_count,
            "equity_count": self.by_type.get("equity", 0),
            "etf_count": self.by_type.get("etf", 0),
            "cash_balance": round(cash_balance, 2),
            "margin_debt": round(margin_debt, 2),
            "long_exposure": round(long_value, 2),
            "short_exposure": round(short_positions_value, 2),
            "net_exposure": round(net_exposure, 2),
            "gross_exposure": round(gross_exposure, 2),
            "leverage": round(leverage, 2),
            "sources": list(self.by_source.keys()),
            "by_type": dict(self.by_type),
            "by_currency": {
                currency: round(value, 2)
                for currency, value in sorted(currency_totals.items(), key=lambda item: -item[1])
            },
            "futures_exposure": futures_exposure,
            "options_exposure": options_exposure,
            "portfolio_greeks": portfolio_greeks,
        }

    def to_monitor_cli(self, by_account: bool = False) -> str:
        """CLI table format for position monitor."""
        payload = self._build_monitor_payload(by_account=by_account)
        summary = payload["summary"]
        positions = payload["positions"]
        by_currency = summary["by_currency"]

        lines: List[str] = []
        lines.append("POSITION MONITOR (excludes cash)")
        lines.append("=" * 120)
        as_of = (
            self.data.as_of.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(self.data.as_of, datetime)
            else str(self.data.as_of)
        )
        sources = ", ".join(self.data.sources)
        lines.append(f"As of: {as_of}")
        lines.append(f"Sources: {sources}")
        lines.append("")

        def _format_number(value: Any, decimals: int = 2) -> str:
            if value is None:
                return "N/A"
            try:
                numeric = float(value)
                if numeric != numeric:  # NaN check
                    return "N/A"
                return f"{numeric:,.{decimals}f}"
            except (TypeError, ValueError):
                return "N/A"

        def _format_percent(value: Any) -> str:
            if value is None:
                return "N/A"
            try:
                numeric = float(value)
                if numeric != numeric:
                    return "N/A"
                return f"{numeric:,.2f}%"
            except (TypeError, ValueError):
                return "N/A"

        def _truncate(text: Any, max_len: int) -> str:
            if text is None:
                return ""
            text = str(text)
            return text[:max_len] if len(text) > max_len else text

        def _format_cell(text: Any, width: int, align: str = "right") -> str:
            s = str(text)
            if len(s) > width:
                s = s[:width]
            return s.ljust(width) if align == "left" else s.rjust(width)

        _CURRENCY_SYMBOLS = {"USD": "$", "GBP": "£", "EUR": "€", "JPY": "¥", "CNY": "¥", "CAD": "C$", "AUD": "A$", "CHF": "CHF"}

        def _cur_sym(code: str) -> str:
            return _CURRENCY_SYMBOLS.get(code, code)

        def _build_col_defs(local_currency: str):
            sym = _cur_sym(local_currency)
            defs = [
                ("Ticker", 8, "left"),
                ("Name", 22, "left"),
                ("Dir", 6, "left"),
                ("Shares", 10, "right"),
                (f"Entry ({sym})", 12, "right"),
                (f"Price ({sym})", 12, "right"),
                ("Gross Exp ($)", 14, "right"),
                ("Net Exp ($)", 14, "right"),
                (f"PnL ({sym})", 12, "right"),
                ("% PnL", 8, "right"),
                ("Wt%", 6, "right"),
            ]
            if by_account:
                defs.extend([
                    ("Brokerage", 15, "left"),
                    ("Account", 15, "left"),
                ])
            return defs

        # Use USD col_defs for table_width (consistent across groups)
        _base_col_defs = _build_col_defs("USD")
        _base_header = " ".join(
            _format_cell(name, width, "left") if align == "left" else _format_cell(name, width, "right")
            for name, width, align in _base_col_defs
        )
        table_width = len(_base_header)

        positions_by_currency: Dict[str, List[Dict[str, Any]]] = {}
        for position in positions:
            currency = position.get("currency") or "UNKNOWN"
            positions_by_currency.setdefault(currency, []).append(position)

        currency_order = sorted(
            positions_by_currency.keys(),
            key=lambda cur: by_currency.get(cur, {}).get("gross_exposure", 0),
            reverse=True,
        )

        if not positions:
            lines.append("No non-cash positions found.")
        else:
            total_gross = summary.get("portfolio_totals_usd", {}).get("gross_exposure", 0)
            has_entry_warning = False
            for currency in currency_order:
                currency_positions = positions_by_currency.get(currency, [])
                col_defs = _build_col_defs(currency)
                header = " ".join(
                    _format_cell(name, width, "left") if align == "left" else _format_cell(name, width, "right")
                    for name, width, align in col_defs
                )
                lines.append(
                    f"{currency} POSITIONS ({len(currency_positions)}) "
                    f"[prices/PnL in {currency}, exposure in USD]"
                )
                lines.append("-" * table_width)
                lines.append(header)
                lines.append("-" * table_width)

                for position in sorted(
                    currency_positions,
                    key=lambda p: p.get("gross_exposure") if p.get("gross_exposure") is not None else 0,
                    reverse=True,
                ):
                    ticker = _truncate(position.get("ticker", ""), 7)
                    if position.get("entry_price_warning"):
                        ticker = f"{ticker}⚠"
                        has_entry_warning = True
                    pos_weight = (position.get("gross_exposure", 0) / total_gross * 100) if total_gross > 0 else 0
                    row_values = [
                        ticker,
                        _truncate(position.get("name", ""), 22),
                        position.get("direction") or "N/A",
                        _format_number(position.get("shares"), 2),
                        _format_number(position.get("weighted_entry_price"), 2),
                        _format_number(position.get("current_price"), 2),
                        _format_number(position.get("gross_exposure"), 2),
                        _format_number(position.get("net_exposure"), 2),
                        _format_number(position.get("pnl"), 2),
                        _format_percent(position.get("pnl_percent")),
                        _format_percent(pos_weight),
                    ]

                    if by_account:
                        row_values.extend([
                            _truncate(position.get("brokerage_name", ""), 15),
                            _truncate(position.get("account_name", ""), 15),
                        ])

                    row = " ".join(
                        _format_cell(val, width, align)
                        for val, (_, width, align) in zip(row_values, col_defs)
                    )
                    lines.append(row)

                # Totals row for this currency group
                tot_gross_ccy = sum(p.get("gross_exposure") or 0 for p in currency_positions)
                tot_net = sum(p.get("net_exposure") or 0 for p in currency_positions)
                tot_pnl = sum(p.get("pnl") or 0 for p in currency_positions)
                tot_weight = (tot_gross_ccy / total_gross * 100) if total_gross > 0 else 0
                lines.append("-" * table_width)
                total_values = [
                    "TOTAL",
                    "",
                    "",
                    "",
                    "",
                    "",
                    _format_number(tot_gross_ccy, 2),
                    _format_number(tot_net, 2),
                    _format_number(tot_pnl, 2),
                    "",
                    _format_percent(tot_weight),
                ]
                if by_account:
                    total_values.extend(["", ""])
                total_row = " ".join(
                    _format_cell(val, width, align)
                    for val, (_, width, align) in zip(total_values, col_defs)
                )
                lines.append(total_row)

                lines.append("")

                currency_summary = by_currency.get(currency, {})
                lines.append(f"{currency} SUMMARY")
                lines.append("-" * table_width)
                lines.append(
                    f"Long Exposure:    ${_format_number(currency_summary.get('long_exposure'), 2)}"
                    f"    ({currency_summary.get('long_count', 0)} positions)"
                )
                lines.append(
                    f"Short Exposure:   ${_format_number(currency_summary.get('short_exposure'), 2)}"
                    f"    ({currency_summary.get('short_count', 0)} positions)"
                )
                lines.append(
                    f"Net Exposure:     ${_format_number(currency_summary.get('net_exposure'), 2)}"
                )
                lines.append(
                    f"Gross Exposure:   ${_format_number(currency_summary.get('gross_exposure'), 2)}"
                )
                sym = _cur_sym(currency)
                if currency != "USD":
                    lines.append(
                        f"Gross Exposure ({currency}): {sym}{_format_number(currency_summary.get('gross_exposure_local'), 2)}"
                    )
                    lines.append(
                        f"Net Exposure ({currency}):   {sym}{_format_number(currency_summary.get('net_exposure_local'), 2)}"
                    )
                lines.append("-" * table_width)
                lines.append(
                    f"Total Cost Basis: {sym}{_format_number(currency_summary.get('total_cost_basis'), 2)}"
                    "    (sum of |cost_basis|)"
                )
                lines.append(
                    f"Total PnL ({currency}): {sym}{_format_number(currency_summary.get('total_pnl'), 2)}"
                )
                if currency != "USD":
                    lines.append(
                        f"Total PnL (USD):  ${_format_number(currency_summary.get('total_pnl_usd'), 2)}"
                    )
                lines.append(
                    f"Total % PnL:      {_format_percent(currency_summary.get('total_pnl_percent'))}"
                )
                missing_cb = currency_summary.get("positions_missing_cost_basis", 0)
                if missing_cb:
                    lines.append(
                        f"* {missing_cb} position(s) excluded from P&L totals (missing cost basis)"
                    )
                missing_price = currency_summary.get("positions_missing_price_or_quantity", 0)
                if missing_price:
                    lines.append(
                        f"* {missing_price} position(s) excluded from P&L totals (missing price/quantity)"
                    )
                lines.append("")

            if summary.get("has_multiple_currencies"):
                portfolio_totals = summary.get("portfolio_totals_usd", {})
                lines.append("PORTFOLIO TOTALS (USD)")
                lines.append("-" * table_width)
                lines.append(
                    f"Long Exposure:    ${_format_number(portfolio_totals.get('long_exposure'), 2)}"
                )
                lines.append(
                    f"Short Exposure:   ${_format_number(portfolio_totals.get('short_exposure'), 2)}"
                )
                lines.append(
                    f"Net Exposure:     ${_format_number(portfolio_totals.get('net_exposure'), 2)}"
                )
                lines.append(
                    f"Gross Exposure:   ${_format_number(portfolio_totals.get('gross_exposure'), 2)}"
                )
                lines.append(
                    f"Total PnL:        ${_format_number(portfolio_totals.get('total_pnl_usd'), 2)}"
                )
                lines.append("")

            if has_entry_warning:
                lines.append("* ⚠ Entry price may be inaccurate")

        cash_excluded = summary.get("cash_positions_excluded", 0)
        if cash_excluded:
            lines.append(f"* {cash_excluded} cash position(s) excluded from monitor view")

        return "\n".join(lines)

    def to_summary(self) -> str:
        """One-line summary for quick AI responses."""
        return (
            f"{self.position_count} positions worth ${self.total_value:,.0f} "
            f"({self.by_type.get('equity', 0)} equities, "
            f"{self.by_type.get('etf', 0)} ETFs, "
            f"{self.by_type.get('cash', 0)} cash positions)"
        )
