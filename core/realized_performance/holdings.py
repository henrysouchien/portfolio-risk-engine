from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

import numpy as np
import pandas as pd

from portfolio_risk_engine.performance_metrics_engine import compute_performance_metrics
from portfolio_risk_engine.data_loader import fetch_monthly_close, fetch_monthly_treasury_rates
from portfolio_risk_engine.factor_utils import calc_monthly_returns
from ibkr.compat import (
    fetch_ibkr_bond_monthly_close,
    fetch_ibkr_fx_monthly_close,
    fetch_ibkr_monthly_close,
    fetch_ibkr_option_monthly_mark,
    get_ibkr_futures_fmp_map,
)
from portfolio_risk_engine.providers import get_fx_provider
from providers.flows.common import build_slice_key
from providers.flows.extractor import extract_provider_flow_events
from providers.fmp_price import FMPPriceProvider
from providers.ibkr_price import IBKRPriceProvider
from providers.interfaces import PriceSeriesProvider
from providers.normalizers.schwab import get_schwab_security_lookup
from providers.registry import ProviderRegistry
from providers.routing import (
    IBKR_TRANSACTION_SOURCES,
    SCHWAB_TRANSACTION_SOURCES,
    get_canonical_provider,
    provider_family,
    resolve_provider_token,
)
from providers.routing_config import resolve_account_aliases
from settings import (
    BACKFILL_FILE_PATH,
    DATA_QUALITY_THRESHOLDS,
    REALIZED_COVERAGE_TARGET,
    REALIZED_MAX_INCOMPLETE_TRADES,
    REALIZED_MAX_RECONCILIATION_GAP_PCT,
    REALIZED_PROVIDER_FLOWS_REQUIRE_COVERAGE,
    REALIZED_PROVIDER_FLOW_SOURCES,
    REALIZED_USE_PROVIDER_FLOWS,
    TRANSACTION_STORE_MAX_AGE_HOURS,
    TRANSACTION_STORE_READ,
    TRANSACTION_STORE_RETRY_COOLDOWN_MINUTES,
)
from trading_analysis.analyzer import TradingAnalyzer
from trading_analysis.data_fetcher import fetch_transactions_for_source, match_institution
from trading_analysis.fifo_matcher import FIFOMatcher, IncompleteTrade, OpenLot
from trading_analysis.instrument_meta import InstrumentMeta, coerce_instrument_type
from trading_analysis.symbol_utils import parse_option_contract_identity_from_symbol

from . import _helpers

def _build_current_positions(
    positions: "PositionResult",
    institution: Optional[str] = None,
    account: Optional[str] = None,
    rows_override: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str], List[str]]:
    """Build ticker->position map and ticker_alias map from PositionResult."""
    current_positions: Dict[str, Dict[str, Any]] = {}
    ticker_alias_map: Dict[str, str] = {}
    warnings: List[str] = []
    filtered_positions = 0
    missing_brokerage_name = 0
    account_filtered_positions = 0

    rows = rows_override if rows_override is not None else list(getattr(positions.data, "positions", []) or [])
    for pos in rows:
        if institution:
            brokerage_name = str(pos.get("brokerage_name") or "")
            if not match_institution(brokerage_name, institution):
                filtered_positions += 1
                if not brokerage_name.strip():
                    missing_brokerage_name += 1
                continue
        if account and not _match_account(pos, account):
            account_filtered_positions += 1
            continue

        ticker = pos.get("ticker")
        if not ticker or not isinstance(ticker, str):
            continue
        ticker = ticker.rstrip(".")
        if not ticker:
            continue
        if pos.get("type") == "cash" or ticker.startswith("CUR:"):
            continue

        quantity = _helpers._as_float(pos.get("quantity"), 0.0)
        if abs(quantity) < 1e-9:
            continue

        currency = pos.get("original_currency") or pos.get("currency") or "USD"
        has_cost_basis_usd = pos.get("cost_basis_usd") is not None
        cost_basis = pos.get("cost_basis_usd")
        if cost_basis is None:
            cost_basis = pos.get("cost_basis")
        cost_basis_is_usd = has_cost_basis_usd or str(currency).upper() == "USD"
        instrument_type = _helpers._infer_position_instrument_type(pos)
        security_identifiers = {
            k: v
            for k, v in {
                "cusip": pos.get("cusip"),
                "isin": pos.get("isin"),
                "figi": pos.get("figi"),
            }.items()
            if isinstance(v, str) and v.strip()
        }

        if ticker in current_positions:
            existing_currency = current_positions[ticker].get("currency")
            if existing_currency != currency:
                warnings.append(
                    f"Mixed currencies in current positions for {ticker} ({existing_currency} vs {currency}); using first currency."
                )
                continue
            current_positions[ticker]["shares"] += quantity
            current_positions[ticker]["value"] += _helpers._as_float(pos.get("value"), 0.0)
            if cost_basis is not None:
                current_positions[ticker]["cost_basis"] = _helpers._as_float(
                    current_positions[ticker].get("cost_basis"), 0.0
                ) + _helpers._as_float(cost_basis, 0.0)
            if current_positions[ticker].get("cost_basis_is_usd") != cost_basis_is_usd:
                warnings.append(
                    f"Mixed cost_basis provenance in current positions for {ticker}; using first provenance."
                )
            if current_positions[ticker].get("instrument_type") != instrument_type:
                warnings.append(
                    f"Mixed instrument_type in current positions for {ticker} "
                    f"({current_positions[ticker].get('instrument_type')} vs {instrument_type}); "
                    "using first instrument_type."
                )
        else:
            current_positions[ticker] = {
                "shares": quantity,
                "currency": str(currency),
                "cost_basis": None if cost_basis is None else _helpers._as_float(cost_basis, 0.0),
                "cost_basis_is_usd": cost_basis_is_usd,
                "value": _helpers._as_float(pos.get("value"), 0.0),
                "instrument_type": instrument_type,
                "security_identifiers": security_identifiers or None,
            }

        ticker_alias = (
            pos.get("ticker_alias")
            if "ticker_alias" in pos
            else pos.get("fmp_ticker")
        )
        if isinstance(ticker_alias, str) and ticker_alias.strip() and ticker not in ticker_alias_map:
            ticker_alias_map[ticker] = ticker_alias.strip()

    if institution and filtered_positions:
        warnings.append(
            f"Institution filter '{institution}': excluded {filtered_positions} position row(s)"
            f" ({missing_brokerage_name} missing brokerage_name)."
        )
    if account and account_filtered_positions:
        warnings.append(
            f"Account filter '{account}': excluded {account_filtered_positions} position row(s)."
        )

    return current_positions, ticker_alias_map, warnings

@dataclass
class SourceScopedHoldings:
    current_positions: Dict[str, Dict[str, Any]]
    ticker_alias_map: Dict[str, str]
    source_holding_symbols: List[str]
    source_holding_count: int
    cross_source_holding_leakage_symbols: List[str]
    holdings_scope: str = "source_scoped"

def _normalize_source_token(value: Any) -> Optional[str]:
    return resolve_provider_token(str(value or ""))

def _resolve_institution_slug(raw_value: str) -> str:
    """Resolve a brokerage/institution name to a canonical slug."""
    from settings import INSTITUTION_SLUG_ALIASES

    text = str(raw_value or "").lower().replace("_", " ").replace("-", " ").strip()
    text = " ".join(text.split())
    if not text:
        return "unknown"

    def _slugify(value: str) -> str:
        return str(value or "").lower().replace("-", "_").replace(" ", "_").strip("_")

    aliases = {
        " ".join(str(alias).lower().replace("_", " ").replace("-", " ").split()): str(slug).lower().strip()
        for alias, slug in INSTITUTION_SLUG_ALIASES.items()
    }
    canonical_slugs = {slug for slug in aliases.values() if slug}

    text_slug = _slugify(text)
    if text_slug in canonical_slugs:
        return text_slug

    for alias, slug in aliases.items():
        if alias and alias in text:
            return slug

    return text_slug or "unknown"

def _match_account(row: Dict[str, Any], account_filter: Optional[str]) -> bool:
    """Match account filter against account_id or account_name (exact, case-insensitive)."""
    normalized_filter = str(account_filter or "").strip().lower()
    if not normalized_filter:
        return True
    aliases = resolve_account_aliases(normalized_filter)
    account_id = str(row.get("account_id") or "").strip().lower()
    account_name = str(row.get("account_name") or "").strip().lower()
    return bool((aliases & {account_id, account_name}) - {""})

def _is_ibkr_identity_field(field_name: str, normalized_value: str) -> bool:
    if "interactive brokers" in normalized_value or "ibkr" in normalized_value:
        return True
    if field_name == "account_id" and bool(_helpers._IBKR_ACCOUNT_ID_RE.match(normalized_value.replace(" ", ""))):
        return True
    return False

def _provider_matches_from_position_row(
    pos: Dict[str, Any],
) -> Tuple[set[str], str]:
    primary_matches: set[str] = set()
    secondary_matches: set[str] = set()
    tertiary_matches: set[str] = set()

    for field_name in ("account_id", "account_name", "brokerage_name", "institution"):
        value = str(pos.get(field_name) or "").strip()
        if not value:
            continue
        normalized = " ".join(value.lower().replace("_", " ").replace("-", " ").split())

        mapped = _normalize_source_token(normalized)
        if mapped:
            primary_matches.add(mapped)

        canonical = get_canonical_provider(value, data_type="transactions")
        canonical_mapped = _normalize_source_token(canonical)
        if canonical_mapped:
            primary_matches.add(canonical_mapped)
            if canonical_mapped == "schwab":
                primary_matches.update(SCHWAB_TRANSACTION_SOURCES)

        if _is_ibkr_identity_field(field_name, normalized):
            primary_matches.update(IBKR_TRANSACTION_SOURCES)

    raw_source = str(pos.get("position_source") or "").strip().lower()
    if raw_source:
        for token in [tok.strip() for tok in raw_source.split(",") if tok.strip()]:
            mapped = _normalize_source_token(token)
            if mapped:
                secondary_matches.add(mapped)

    brokerage_candidates = [
        str(pos.get("brokerage_name") or "").strip(),
        str(pos.get("institution") or "").strip(),
    ]
    for brokerage_name in brokerage_candidates:
        if not brokerage_name:
            continue
        if match_institution(brokerage_name, "ibkr"):
            tertiary_matches.update(IBKR_TRANSACTION_SOURCES)
        if match_institution(brokerage_name, "schwab"):
            tertiary_matches.update(SCHWAB_TRANSACTION_SOURCES)

    if primary_matches:
        return primary_matches, "primary"
    if secondary_matches:
        # Prefer native broker APIs over aggregator mirrors when both appear.
        native_sources = set(SCHWAB_TRANSACTION_SOURCES) | set(IBKR_TRANSACTION_SOURCES)
        aggregator_sources = {"plaid", "snaptrade"}
        native_in = secondary_matches & native_sources
        aggregator_in = secondary_matches & aggregator_sources
        if native_in and aggregator_in:
            secondary_matches = native_in
        return secondary_matches, "secondary"
    if tertiary_matches:
        return tertiary_matches, "tertiary"
    return set(), "none"

def _build_source_scoped_holdings(
    positions: "PositionResult",
    source: str,
    warnings: List[str],
    institution: Optional[str] = None,
    account: Optional[str] = None,
) -> SourceScopedHoldings:
    """Build source-scoped holdings with deterministic attribution and leakage diagnostics."""
    if source == "all":
        return SourceScopedHoldings(
            current_positions={},
            ticker_alias_map={},
            source_holding_symbols=[],
            source_holding_count=0,
            cross_source_holding_leakage_symbols=[],
            holdings_scope="consolidated",
        )

    candidate_rows: List[Tuple[Dict[str, Any], str]] = []
    symbol_institution_sources: Dict[Tuple[str, str], set[str]] = defaultdict(set)
    symbol_to_sources: Dict[str, set[str]] = defaultdict(set)
    row_level_ambiguous_pairs: set[Tuple[str, str]] = set()
    institution_filtered_rows = 0
    institution_missing_brokerage_name = 0
    account_filtered_rows = 0

    for pos in list(getattr(getattr(positions, "data", None), "positions", []) or []):
        if institution:
            brokerage_name = str(pos.get("brokerage_name") or pos.get("institution") or "")
            if not match_institution(brokerage_name, institution):
                institution_filtered_rows += 1
                if not brokerage_name.strip():
                    institution_missing_brokerage_name += 1
                continue
        if account and not _match_account(pos, account):
            account_filtered_rows += 1
            continue

        ticker = pos.get("ticker")
        if not ticker or not isinstance(ticker, str):
            continue
        if pos.get("type") == "cash" or ticker.startswith("CUR:"):
            continue

        quantity = _helpers._as_float(pos.get("quantity"), 0.0)
        if abs(quantity) < 1e-9:
            continue

        matches, _match_basis = _provider_matches_from_position_row(pos)
        symbol = ticker.strip()
        sources_for_symbol = set(matches)
        raw_source = str(pos.get("position_source") or "").strip().lower()
        if raw_source:
            for token in [tok.strip() for tok in raw_source.split(",") if tok.strip()]:
                mapped = _normalize_source_token(token)
                if mapped:
                    sources_for_symbol.add(mapped)
                else:
                    collapsed = " ".join(token.replace("_", " ").replace("-", " ").split())
                    if collapsed:
                        sources_for_symbol.add(collapsed)
        if not sources_for_symbol:
            continue
        row_institution = _resolve_institution_slug(
            str(pos.get("brokerage_name") or pos.get("institution") or "")
        )
        symbol_institution_sources[(symbol, row_institution)].update(sources_for_symbol)
        symbol_to_sources[symbol].update(sources_for_symbol)
        match_families = {provider_family(match) or match for match in matches}
        if len(match_families) > 1 and source in matches:
            row_level_ambiguous_pairs.add((symbol, row_institution))

        if source in matches:
            candidate_rows.append((pos, row_institution))

    _NATIVE_SOURCE_FAMILIES = {"schwab", "ibkr"}
    _AGGREGATOR_SOURCE_FAMILIES = {"plaid", "snaptrade"}
    normalized_source = provider_family(source) or source

    candidate_pairs = {
        (str(row.get("ticker") or "").strip(), inst)
        for row, inst in candidate_rows
    }

    leakage_pairs: set[Tuple[str, str]] = set()
    for (symbol, inst), sources in symbol_institution_sources.items():
        if (symbol, inst) not in candidate_pairs:
            continue
        normalized_sources = {provider_family(token) or token for token in sources}
        if normalized_source not in normalized_sources or len(normalized_sources) <= 1:
            continue
        if inst == "unknown":
            leakage_pairs.add((symbol, inst))
            continue
        native_in = normalized_sources & _NATIVE_SOURCE_FAMILIES
        aggregator_in = normalized_sources & _AGGREGATOR_SOURCE_FAMILIES
        unknown_sources = normalized_sources - _NATIVE_SOURCE_FAMILIES - _AGGREGATOR_SOURCE_FAMILIES
        if (
            native_in
            and aggregator_in
            and len(native_in) == 1
            and not unknown_sources
            and normalized_source in native_in
        ):
            continue
        leakage_pairs.add((symbol, inst))

    all_leakage_pairs = leakage_pairs | row_level_ambiguous_pairs

    survived_symbols: set[str] = set()
    for row, inst in candidate_rows:
        symbol = str(row.get("ticker") or "").strip()
        if (symbol, inst) not in all_leakage_pairs:
            survived_symbols.add(symbol)

    all_leakage_symbols = {symbol for symbol, _inst in all_leakage_pairs}
    fully_excluded = sorted(all_leakage_symbols - survived_symbols)
    partially_excluded = sorted(all_leakage_symbols & survived_symbols)

    if fully_excluded:
        preview = ", ".join(fully_excluded[:5])
        if len(fully_excluded) > 5:
            preview = f"{preview}, ..."
        warnings.append(
            f"Excluded {len(fully_excluded)} cross-source holding symbol(s) from {source} "
            f"strict holdings scope ({preview}); attribution remained ambiguous after "
            f"institution-aware precedence checks."
        )
    if partially_excluded:
        preview = ", ".join(partially_excluded[:5])
        if len(partially_excluded) > 5:
            preview = f"{preview}, ..."
        warnings.append(
            f"Partially excluded {len(partially_excluded)} symbol(s) from {source} scope "
            f"({preview}); some institution rows were ambiguous but other institutions' "
            f"rows were retained."
        )
    if institution and institution_filtered_rows:
        warnings.append(
            f"Institution filter '{institution}': excluded {institution_filtered_rows} source-scoped position row(s)"
            f" ({institution_missing_brokerage_name} missing brokerage/institution)."
        )
    if account and account_filtered_rows:
        warnings.append(
            f"Account filter '{account}': excluded {account_filtered_rows} source-scoped position row(s)."
        )

    strict_rows = [
        row for row, inst in candidate_rows
        if (str(row.get("ticker") or "").strip(), inst) not in all_leakage_pairs
    ]
    scoped_positions, scoped_fmp_map, scoped_warnings = _build_current_positions(
        positions,
        institution=None,
        rows_override=strict_rows,
    )
    warnings.extend(scoped_warnings)
    symbols = sorted(scoped_positions.keys())
    return SourceScopedHoldings(
        current_positions=scoped_positions,
        ticker_alias_map=scoped_fmp_map,
        source_holding_symbols=symbols,
        source_holding_count=len(symbols),
        cross_source_holding_leakage_symbols=fully_excluded,
        holdings_scope="source_scoped",
    )

__all__ = [
    '_build_current_positions',
    'SourceScopedHoldings',
    '_normalize_source_token',
    '_resolve_institution_slug',
    '_match_account',
    '_is_ibkr_identity_field',
    '_provider_matches_from_position_row',
    '_build_source_scoped_holdings',
]
