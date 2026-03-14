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
from providers.routing import get_canonical_provider, resolve_provider_token
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

def _normalize_optional_identifier(value: Any) -> str | None:
    """Return stripped identifier string or ``None`` when empty."""

    text = str(value or "").strip()
    return text or None

def _normalize_replay_identifier(value: Any, *, default: str) -> str:
    token = str(value or "").strip()
    if not token:
        return default
    token = re.sub(r"[\s\-]+", "_", token.upper())
    token = re.sub(r"_+", "_", token).strip("_")
    return token or default

def _normalize_realized_replay_provider(
    value: Any,
    *,
    diagnostics: Optional[Dict[str, Any]] = None,
) -> str:
    raw = str(value or "").strip()
    normalized = _normalize_replay_identifier(raw, default="UNKNOWN")
    normalized = _helpers.REALIZED_PROVIDER_ALIAS_MAP.get(normalized, normalized)

    if diagnostics is not None and raw:
        raw_upper = raw.upper()
        if normalized != raw_upper:
            diagnostics["alias_normalization_mismatch_count"] = int(
                _helpers._as_float(diagnostics.get("alias_normalization_mismatch_count"), 0.0)
            ) + 1
            pair = {
                "raw_provider": raw,
                "normalized_provider": normalized,
            }
            samples = diagnostics.setdefault("alias_normalization_mismatch_samples", [])
            if pair not in samples and len(samples) < 5:
                samples.append(pair)

    return normalized

def _replay_account_identity(row: Dict[str, Any]) -> str:
    account_id = _normalize_optional_identifier(row.get("account_id"))
    if account_id:
        return f"ACCOUNT_ID:{_normalize_replay_identifier(account_id, default='UNKNOWN')}"

    account_number = _normalize_optional_identifier(row.get("account_number"))
    if account_number:
        return f"ACCOUNT_NUMBER:{_normalize_replay_identifier(account_number, default='UNKNOWN')}"

    institution = _normalize_replay_identifier(
        _normalize_optional_identifier(row.get("institution")),
        default="UNKNOWN_INSTITUTION",
    )
    masked_account = _normalize_optional_identifier(row.get("masked_account"))
    if not masked_account:
        masked_account = _normalize_optional_identifier(row.get("account_name"))
    if not masked_account:
        masked_account = _normalize_optional_identifier(row.get("provider_account_ref"))
    masked_component = _normalize_replay_identifier(
        masked_account,
        default="UNKNOWN_ACCOUNT",
    )
    return f"FALLBACK:{institution}|{masked_component}"

def _dedupe_income_provider_internal_flow_overlap(
    *,
    income_with_currency: List[Dict[str, Any]],
    provider_flow_events: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    diagnostics: Dict[str, Any] = {
        "dropped_count": 0,
        "dropped_net_usd": 0.0,
        "dropped_by_provider": {},
        "candidate_count": 0,
        "alias_normalization_mismatch_count": 0,
        "alias_normalization_mismatch_samples": [],
    }
    if not provider_flow_events or not income_with_currency:
        return list(provider_flow_events), diagnostics

    income_lookup: Dict[Tuple[str, str, datetime, int], List[Dict[str, Any]]] = defaultdict(list)
    for inc in income_with_currency:
        inc_date = _helpers._to_datetime(inc.get("date"))
        if inc_date is None:
            continue
        provider_key = _normalize_realized_replay_provider(
            inc.get("source"),
            diagnostics=diagnostics,
        )
        account_identity = _replay_account_identity(inc)
        amount = _helpers._as_float(inc.get("amount"), 0.0)
        amount_cents = int(round(amount * 100.0))
        income_lookup[(provider_key, account_identity, inc_date.date(), amount_cents)].append(
            {"amount": amount, "matched": False}
        )

    dropped_by_provider: Dict[str, int] = defaultdict(int)
    filtered_events: List[Dict[str, Any]] = []

    for provider_flow in provider_flow_events:
        if bool(provider_flow.get("is_external_flow")):
            filtered_events.append(provider_flow)
            continue

        flow_date = _helpers._to_datetime(provider_flow.get("timestamp") or provider_flow.get("date"))
        if flow_date is None:
            filtered_events.append(provider_flow)
            continue

        provider_key = _normalize_realized_replay_provider(
            provider_flow.get("provider") or provider_flow.get("source"),
            diagnostics=diagnostics,
        )
        account_identity = _replay_account_identity(provider_flow)
        amount = _helpers._as_float(provider_flow.get("amount"), 0.0)
        amount_cents = int(round(amount * 100.0))

        candidate_groups: List[List[Dict[str, Any]]] = []
        for cents in (amount_cents - 1, amount_cents, amount_cents + 1):
            bucket = income_lookup.get((provider_key, account_identity, flow_date.date(), cents))
            if bucket:
                candidate_groups.append(bucket)

        if candidate_groups:
            diagnostics["candidate_count"] = int(_helpers._as_float(diagnostics.get("candidate_count"), 0.0)) + 1

        matched = False
        for group in candidate_groups:
            for candidate in group:
                if candidate.get("matched"):
                    continue
                if abs(_helpers._as_float(candidate.get("amount"), 0.0) - amount) <= 0.01:
                    candidate["matched"] = True
                    matched = True
                    break
            if matched:
                break

        if matched:
            dropped_by_provider[provider_key] += 1
            diagnostics["dropped_count"] = int(_helpers._as_float(diagnostics.get("dropped_count"), 0.0)) + 1
            diagnostics["dropped_net_usd"] = _helpers._as_float(diagnostics.get("dropped_net_usd"), 0.0) + amount
            continue

        filtered_events.append(provider_flow)

    diagnostics["dropped_net_usd"] = round(_helpers._as_float(diagnostics.get("dropped_net_usd"), 0.0), 2)
    diagnostics["dropped_by_provider"] = dict(sorted(dropped_by_provider.items()))
    return filtered_events, diagnostics

def _flow_slice_key(
    *,
    provider: Any,
    institution: Any,
    account_id: Any,
    provider_account_ref: Any,
    account_name: Any,
) -> str:
    """Build canonical provider/institution/account key for flow authority slices."""

    return build_slice_key(
        provider=str(provider or "unknown").strip().lower() or "unknown",
        institution=_normalize_optional_identifier(institution),
        account_id=_normalize_optional_identifier(account_id),
        provider_account_ref=_normalize_optional_identifier(provider_account_ref),
        account_name=_normalize_optional_identifier(account_name),
    )

def _provider_flow_event_sort_key(event: Dict[str, Any]) -> Tuple[str, datetime, str, str, str]:
    """Stable sort key for deterministic provider-flow event deduplication."""

    provider = str(event.get("provider") or "unknown").strip().lower()
    timestamp = _helpers._to_datetime(event.get("timestamp") or event.get("date")) or datetime.min
    transaction_id = str(event.get("transaction_id") or "")
    account_id = str(event.get("account_id") or "")
    fingerprint = str(event.get("provider_row_fingerprint") or "")
    return provider, timestamp, transaction_id, account_id, fingerprint

def _deduplicate_provider_flow_events(
    events: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Deduplicate provider flow events and return diagnostics.

    Dedup semantics:
    - Prefer transaction-id keys when available.
    - Fall back to provider/account/date/amount/type fingerprint when needed.
    - Fail-open for rows lacking safe identity fields (kept, not dropped).
    """

    seen: set[Tuple[Any, ...]] = set()
    deduped: List[Dict[str, Any]] = []
    dropped_by_provider: Dict[str, int] = defaultdict(int)
    dropped_by_slice: Dict[str, int] = defaultdict(int)

    for event in sorted(events, key=_provider_flow_event_sort_key):
        provider = str(event.get("provider") or "unknown").strip().lower()
        slice_key = _flow_slice_key(
            provider=provider,
            institution=event.get("institution"),
            account_id=event.get("account_id"),
            provider_account_ref=event.get("provider_account_ref"),
            account_name=event.get("account_name"),
        )
        canonical_identity = slice_key.split("|")[-1]
        transaction_id = str(event.get("transaction_id") or "").strip()

        dedup_key: Tuple[Any, ...] | None
        if transaction_id:
            dedup_key = ("txn_id", provider, canonical_identity, transaction_id)
        else:
            timestamp = _helpers._to_datetime(event.get("timestamp") or event.get("date"))
            raw_description = str(event.get("raw_description") or "").strip()
            fingerprint = str(event.get("provider_row_fingerprint") or "").strip()
            if not raw_description and not fingerprint:
                # Fail-open: insufficient identity for safe dedup.
                dedup_key = None
            else:
                dedup_key = (
                    "fallback",
                    provider,
                    canonical_identity,
                    timestamp.isoformat() if timestamp else "",
                    round(_helpers._as_float(event.get("amount"), 0.0), 8),
                    str(event.get("currency") or "USD").upper(),
                    str(event.get("raw_type") or ""),
                    str(event.get("raw_subtype") or ""),
                    raw_description,
                    fingerprint,
                )

        if dedup_key is not None and dedup_key in seen:
            dropped_by_provider[provider] += 1
            dropped_by_slice[slice_key] += 1
            continue

        if dedup_key is not None:
            seen.add(dedup_key)
        deduped.append(event)

    diagnostics = {
        "input_count": len(events),
        "output_count": len(deduped),
        "duplicates_dropped_by_provider": dict(sorted(dropped_by_provider.items())),
        "duplicates_dropped_by_slice": dict(sorted(dropped_by_slice.items())),
    }
    return deduped, diagnostics

def _build_provider_flow_authority(
    events: List[Dict[str, Any]],
    fetch_metadata: List[Dict[str, Any]],
    *,
    require_coverage: bool,
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """Build slice-level authority map for provider-reported flow usage.

    Decision semantics:
    - Slice is authoritative when it has provider events.
    - Slice may also be authoritative with deterministic no-flow metadata
      (clean metadata indicates no events for that window).
    - ``require_coverage`` is retained for interface compatibility but does not
      gate authority in current direct-first mode.
    """

    # Gate-free mode: provider-reported events are authoritative when present.
    # ``require_coverage`` is retained for interface compatibility, but authority
    # no longer fails closed on metadata quality flags.
    _ = require_coverage
    authority: Dict[str, Dict[str, Any]] = {}
    fallback_reasons: List[str] = []
    event_count_by_slice: Dict[str, int] = defaultdict(int)

    for event in events:
        key = _flow_slice_key(
            provider=event.get("provider"),
            institution=event.get("institution"),
            account_id=event.get("account_id"),
            provider_account_ref=event.get("provider_account_ref"),
            account_name=event.get("account_name"),
        )
        event_count_by_slice[key] += 1

    metadata_by_slice: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in fetch_metadata:
        key = _flow_slice_key(
            provider=row.get("provider"),
            institution=row.get("institution"),
            account_id=row.get("account_id"),
            provider_account_ref=row.get("provider_account_ref"),
            account_name=row.get("account_name"),
        )
        metadata_by_slice[key].append(row)

    all_slices = set(event_count_by_slice.keys()) | set(metadata_by_slice.keys())
    for key in sorted(all_slices):
        slice_metadata = metadata_by_slice.get(key, [])
        event_count = int(event_count_by_slice.get(key, 0))
        has_metadata = len(slice_metadata) > 0
        has_error = any(str(row.get("fetch_error") or "").strip() for row in slice_metadata)
        has_partial = any(
            bool(row.get("partial_data")) or row.get("pagination_exhausted") is False
            for row in slice_metadata
        )
        unmapped_row_count = int(sum(_helpers._as_float(row.get("unmapped_row_count"), 0.0) for row in slice_metadata))
        has_unmapped = unmapped_row_count > 0
        has_snaptrade_sync_gap = any(_is_snaptrade_sync_gap_metadata_row(row) for row in slice_metadata)

        coverage_starts = [
            _helpers._to_datetime(row.get("payload_coverage_start") or row.get("fetch_window_start"))
            for row in slice_metadata
        ]
        coverage_ends = [
            _helpers._to_datetime(row.get("payload_coverage_end") or row.get("fetch_window_end"))
            for row in slice_metadata
        ]
        coverage_start = min((dt for dt in coverage_starts if dt is not None), default=None)
        coverage_end = max((dt for dt in coverage_ends if dt is not None), default=None)

        deterministic_no_flow = (
            has_metadata
            and event_count == 0
            and (
                (not has_error and not has_partial and not has_unmapped)
                or (has_snaptrade_sync_gap and not has_error and not has_unmapped)
            )
        )
        authoritative = event_count > 0 or deterministic_no_flow

        reason = ""
        if not authoritative:
            if event_count == 0 and has_metadata and not has_error and not has_partial and not has_unmapped:
                reason = "no_provider_events_with_clean_metadata"
            elif event_count == 0 and not has_metadata:
                reason = "missing_fetch_metadata"
            else:
                reason = "no_provider_events"
            fallback_reasons.append(f"{key}:{reason}")

        authority[key] = {
            "authoritative": authoritative,
            "has_metadata": has_metadata,
            "event_count": event_count,
            "coverage_start": coverage_start,
            "coverage_end": coverage_end,
            "has_error": has_error,
            "has_partial": has_partial,
            "deterministic_no_flow": deterministic_no_flow,
            "unmapped_row_count": unmapped_row_count,
        }

    return authority, sorted(set(fallback_reasons))

def _is_snaptrade_sync_gap_metadata_row(row: Dict[str, Any]) -> bool:
    """Detect SnapTrade metadata rows indicating transactions-sync initialization gap."""

    provider = str(row.get("provider") or "").strip().lower()
    if provider != "snaptrade":
        return False
    diagnostic_code = str(row.get("diagnostic_code") or "").strip().lower()
    transactions_sync_initialized = row.get("transactions_sync_initialized")
    row_count = int(_helpers._as_float(row.get("row_count"), 0.0))
    return (
        diagnostic_code == "snaptrade_transactions_sync_uninitialized"
        or (transactions_sync_initialized is False and row_count == 0)
    )

def _build_fetch_metadata_warnings(
    fetch_metadata: List[Dict[str, Any]],
    *,
    source: str,
    institution: Optional[str],
) -> List[str]:
    """Build user-facing warnings from provider fetch-metadata diagnostics."""

    warnings: List[str] = []
    seen: set[str] = set()
    source_filter = str(source or "all").strip().lower()

    for row in fetch_metadata:
        provider = str(row.get("provider") or "").strip().lower()
        if source_filter != "all" and provider != source_filter:
            continue

        row_institution = str(row.get("institution") or "")
        if institution and row_institution and not match_institution(row_institution, institution):
            continue

        is_snaptrade_sync_gap = _is_snaptrade_sync_gap_metadata_row(row)
        if not is_snaptrade_sync_gap:
            continue

        institution_label = row_institution.strip() or "unknown institution"
        account_label = (
            str(row.get("account_name") or "").strip()
            or str(row.get("account_id") or "").strip()
            or "unknown account"
        )

        warning = (
            f"SnapTrade transaction reporting is unavailable for {institution_label} ({account_label}); "
            "account activities returned zero rows. Use provider-native transaction feeds "
            "(for example, IBKR Flex for Interactive Brokers) for realized-performance history."
        )
        if warning in seen:
            continue
        seen.add(warning)
        warnings.append(warning)

    return warnings

def _is_authoritative_slice(
    authority: Dict[str, Dict[str, Any]],
    *,
    provider: Any,
    institution: Any,
    account_id: Any,
    provider_account_ref: Any,
    account_name: Any,
    event_date: datetime,
) -> bool:
    return _authoritative_slice_status(
        authority,
        provider=provider,
        institution=institution,
        account_id=account_id,
        provider_account_ref=provider_account_ref,
        account_name=account_name,
        event_date=event_date,
    ) == "authoritative_in_window"

def _authoritative_slice_status(
    authority: Dict[str, Dict[str, Any]],
    *,
    provider: Any,
    institution: Any,
    account_id: Any,
    provider_account_ref: Any,
    account_name: Any,
    event_date: datetime,
) -> str:
    key = _flow_slice_key(
        provider=provider,
        institution=institution,
        account_id=account_id,
        provider_account_ref=provider_account_ref,
        account_name=account_name,
    )
    row = authority.get(key)
    if not row or not bool(row.get("authoritative")):
        return "non_authoritative"

    start = _helpers._to_datetime(row.get("coverage_start"))
    end = _helpers._to_datetime(row.get("coverage_end"))
    if start is not None and event_date < start:
        return "authoritative_out_of_window"
    if end is not None and event_date > end:
        return "authoritative_out_of_window"
    return "authoritative_in_window"

def _combine_cash_snapshots(
    inference_snapshots: List[Tuple[datetime, float]],
    provider_cash_deltas: List[Tuple[datetime, float]],
) -> List[Tuple[datetime, float]]:
    inference_deltas: List[Tuple[datetime, float]] = []
    prev_cash = 0.0
    for when, cash_value in sorted(inference_snapshots, key=lambda row: row[0]):
        delta = _helpers._as_float(cash_value, 0.0) - prev_cash
        prev_cash = _helpers._as_float(cash_value, 0.0)
        inference_deltas.append((when, delta))

    combined_events: List[Tuple[datetime, int, float]] = []
    combined_events.extend((when, 0, _helpers._as_float(delta, 0.0)) for when, delta in inference_deltas)
    combined_events.extend((when, 1, _helpers._as_float(delta, 0.0)) for when, delta in provider_cash_deltas)
    combined_events.sort(key=lambda row: (row[0], row[1]))

    cash = 0.0
    snapshots: List[Tuple[datetime, float]] = []
    for when, _order, delta in combined_events:
        cash += delta
        snapshots.append((when, cash))
    return snapshots

def _normalize_source_name(value: Any) -> str:
    source = str(value or "unknown").strip().lower()
    return source or "unknown"

__all__ = [
    '_normalize_optional_identifier',
    '_normalize_replay_identifier',
    '_normalize_realized_replay_provider',
    '_replay_account_identity',
    '_dedupe_income_provider_internal_flow_overlap',
    '_flow_slice_key',
    '_provider_flow_event_sort_key',
    '_deduplicate_provider_flow_events',
    '_build_provider_flow_authority',
    '_is_snaptrade_sync_gap_metadata_row',
    '_build_fetch_metadata_warnings',
    '_is_authoritative_slice',
    '_authoritative_slice_status',
    '_combine_cash_snapshots',
    '_normalize_source_name',
]
