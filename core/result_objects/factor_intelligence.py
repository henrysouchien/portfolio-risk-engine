"""Factor Intelligence result objects."""

from typing import Dict, Any, Optional, List, Union, Tuple
import numbers
import math
import pandas as pd
from datetime import datetime, UTC
import json
import numpy as np
from dataclasses import dataclass, field
from utils.serialization import make_json_safe
from ._helpers import (_convert_to_json_serializable, _clean_nan_values, _format_df_as_text, _abbreviate_labels, _DEFAULT_INDUSTRY_ABBR_MAP)

class FactorCorrelationResult:
    """
    Structured result for factor correlation analysis.

    Attributes
    ----------
    matrices : Dict[str, Any]
        Per-category correlation matrices (pandas DataFrames).
    overlays : Dict[str, Any]
        Optional overlay matrices and metadata (rate/market/macro views).
    data_quality : Dict[str, Any]
        Coverage and exclusion info by category.
    performance : Dict[str, Any]
        Timing metrics (ms) for correlation construction.
    analysis_metadata : Dict[str, Any]
        Echo of analysis window and universe hash.
    """

    def __init__(self, matrices: Dict[str, Any], overlays: Dict[str, Any], data_quality: Dict[str, Any], performance: Dict[str, Any], analysis_metadata: Dict[str, Any], labels: Optional[Dict[str, str]] = None, market_exchanges: Optional[Dict[str, str]] = None, style_exchanges: Optional[Dict[str, Dict[str, str]]] = None):
        self.matrices = matrices or {}
        self.overlays = overlays or {}
        self.data_quality = data_quality or {}
        self.performance = performance or {}
        self.analysis_metadata = analysis_metadata or {}
        self.labels = labels or {}
        self.market_exchanges = market_exchanges or {}
        self.style_exchanges = style_exchanges or {}

    @classmethod
    def from_core_analysis(cls,
                          core_matrices: Dict[str, Any],
                          overlays: Dict[str, Any],
                          data_quality: Dict[str, Any],
                          performance: Dict[str, Any],
                          analysis_metadata: Dict[str, Any],
                          labels: Optional[Dict[str, str]] = None,
                          market_exchanges: Optional[Dict[str, str]] = None,
                          style_exchanges: Optional[Dict[str, Dict[str, str]]] = None) -> 'FactorCorrelationResult':
        """
        Create FactorCorrelationResult from core factor intelligence analysis data.

        ARCHITECTURE CONTEXT:
        This is the primary factory method for creating FactorCorrelationResult objects from
        core factor intelligence functions (compute_per_category_correlation_matrices, etc.).
        It transforms raw correlation analysis data into a structured result object ready for API responses.

        DATA FLOW:
        factor_intelligence_service.analyze_correlations() → core analysis data → from_core_analysis() → FactorCorrelationResult

        INPUT DATA STRUCTURE:
        - core_matrices: Output from compute_per_category_correlation_matrices() containing:
          • Per-category correlation matrices (Dict[str, pd.DataFrame])
        - overlays: Rate/market sensitivity and macro matrices (Dict[str, Any])
        - data_quality: Coverage and exclusion info by category (Dict[str, Any])
        - performance: Timing metrics (ms) for correlation construction (Dict[str, Any])
        - analysis_metadata: Analysis window, universe hash, and configuration (Dict[str, Any])

        Returns
        -------
        FactorCorrelationResult
            Structured result object ready for API serialization
        """
        return cls(
            matrices=core_matrices,
            overlays=overlays,
            data_quality=data_quality,
            performance=performance,
            analysis_metadata=analysis_metadata,
            labels=labels or {},
            market_exchanges=market_exchanges or {},
            style_exchanges=style_exchanges or {}
        )

    @staticmethod
    def _df_to_nested(df) -> Dict[str, Dict[str, float]]:
        try:
            return {r: {c: float(v) for c, v in row.items()} for r, row in df.round(4).to_dict(orient='index').items()}
        except Exception:
            return {}

    def to_dict(self) -> Dict[str, Any]:
        mats = {}
        for name, df in self.matrices.items():
            mats[name] = self._df_to_nested(df) if hasattr(df, 'to_dict') else {}
        return {
            'matrices': mats,
            'overlays': self.overlays,
            'data_quality': self.data_quality,
            'performance': self.performance,
            'analysis_metadata': self.analysis_metadata,
        }

    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert FactorCorrelationResult to comprehensive API response format.

        CONSUMER ANALYSIS:
        - Direct API: Uses full structured response for factor analysis and visualization
        - Claude/AI: Uses formatted_report (to_cli_report) for human-readable analysis
        - Frontend: Uses matrices and overlays for correlation heatmaps and charts

        Returns structured data suitable for JSON serialization and API responses.
        This method provides complete factor correlation analysis including matrices,
        overlays, performance metrics, and data quality information.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing all factor correlation data with the following fields:

            - matrices: Dict[str, Dict[str, Dict[str, float]]] - Per-category correlation matrices
            - overlays: Dict[str, Any] - Rate/market sensitivity and macro matrices
            - data_quality: Dict[str, Any] - Coverage and exclusion info by category
            - performance: Dict[str, Any] - Timing metrics (ms) for correlation construction
            - analysis_metadata: Dict[str, Any] - Analysis window, universe hash, and configuration
            - formatted_report: str - Human-readable CLI report (identical to to_cli_report)

        Example
        -------
        ```python
        result = service.analyze_correlations(start_date="2020-01-01", end_date="2024-12-31")
        api_data = result.to_api_response()

        # Access correlation matrices
        industry_matrix = api_data["matrices"]["industry"]

        # Access sensitivity overlays
        rate_sensitivity = api_data["overlays"]["rate_sensitivity"]

        # Access performance metrics
        timing = api_data["performance"]
        ```
        """
        # Convert matrices to nested format for JSON serialization
        matrices_serialized = {}
        for name, df in self.matrices.items():
            matrices_serialized[name] = self._df_to_nested(df) if hasattr(df, 'to_dict') else {}

        # Build resolved labels: apply market exchange prettifying for market tickers
        resolved_labels = dict(self.labels or {})
        style_tickers: set = set()
        if isinstance(self.style_exchanges, dict):
            for mapping in self.style_exchanges.values():
                if isinstance(mapping, dict):
                    for tk in mapping.values():
                        if tk:
                            style_tickers.add(str(tk))

        if isinstance(self.market_exchanges, dict):
            def _pretty_exch(s: str) -> str:
                p = str(s).replace('_', ' ').strip()
                return p.title()
            for tkr, exch in self.market_exchanges.items():
                if str(tkr) in style_tickers:
                    continue
                pretty = _pretty_exch(exch)
                resolved_labels[tkr] = f"{pretty} ({tkr})"
        if isinstance(self.style_exchanges, dict):
            def _pretty_exch(s: str) -> str:
                p = str(s).replace('_', ' ').strip()
                return p.title()
            for exch, factors in self.style_exchanges.items():
                pretty = _pretty_exch(exch)
                if isinstance(factors, dict):
                    for ftype, tkr in factors.items():
                        if not tkr:
                            continue
                        label = f"{pretty} Market ({tkr})" if ftype == 'market' else f"{pretty} {ftype.title()} ({tkr})"
                        resolved_labels[str(tkr)] = label

        return {
            "matrices": matrices_serialized,                                    # DICT: Per-category correlation matrices (nested format)
            "overlays": _convert_to_json_serializable(self.overlays),          # DICT: Rate/market sensitivity and macro matrices
            "data_quality": _convert_to_json_serializable(self.data_quality),  # DICT: Coverage and exclusion info
            "performance": _convert_to_json_serializable(self.performance),    # DICT: Timing metrics
            "analysis_metadata": _convert_to_json_serializable(self.analysis_metadata),  # DICT: Analysis configuration
            "labels": _convert_to_json_serializable(resolved_labels),          # DICT: Optional ticker → display label mapping
            "style_exchanges": _convert_to_json_serializable(self.style_exchanges),
            "formatted_report": self.to_cli_report(),                          # STR: Human-readable report
        }

    def get_agent_snapshot(self) -> Dict[str, Any]:
        """Compact metrics for agent consumption."""
        def _safe_float(val, default: float = 0.0) -> float:
            try:
                result = float(val) if val is not None else default
                return default if (math.isnan(result) or math.isinf(result)) else result
            except (TypeError, ValueError):
                return default

        high_corr_pairs: List[Dict[str, Any]] = []
        matrices = self.matrices or {}
        for category, matrix in matrices.items():
            if isinstance(matrix, pd.DataFrame) and not matrix.empty:
                tickers = list(matrix.columns)
                for i, t1 in enumerate(tickers):
                    for j in range(i + 1, len(tickers)):
                        t2 = tickers[j]
                        try:
                            raw_corr = matrix.loc[t1, t2]
                        except KeyError:
                            continue
                        corr = _safe_float(raw_corr) if pd.notna(raw_corr) else 0.0
                        if abs(corr) > 0.7:
                            high_corr_pairs.append(
                                {
                                    "factor1": t1,
                                    "factor2": t2,
                                    "correlation": round(corr, 3),
                                    "category": category,
                                }
                            )
            elif isinstance(matrix, dict):
                tickers = list(matrix.keys())
                for i, t1 in enumerate(tickers):
                    row = matrix.get(t1)
                    if not isinstance(row, dict):
                        continue
                    for t2 in tickers[i + 1:]:
                        corr = _safe_float(row.get(t2))
                        if abs(corr) > 0.7:
                            high_corr_pairs.append(
                                {
                                    "factor1": t1,
                                    "factor2": t2,
                                    "correlation": round(corr, 3),
                                    "category": category,
                                }
                            )

        high_corr_pairs.sort(key=lambda x: (-abs(x["correlation"]), x["factor1"], x["factor2"]))
        total_high_corr_count = len(high_corr_pairs)
        high_corr_pairs = high_corr_pairs[:5]

        overlays_available: List[str] = []
        overlays = self.overlays or {}
        for key in ["rate_sensitivity", "market_sensitivity", "macro_composite_matrix", "macro_etf_matrix"]:
            if overlays.get(key) is not None:
                overlays_available.append(key)

        categories_analyzed = list(matrices.keys())
        total_factors = 0
        for matrix in matrices.values():
            if isinstance(matrix, pd.DataFrame):
                total_factors += len(matrix.columns)
            elif isinstance(matrix, dict):
                total_factors += len(matrix)

        if not matrices or total_factors == 0:
            verdict = "no correlation data available"
        elif total_high_corr_count:
            verdict = "high correlations detected"
        else:
            verdict = "factor correlations normal"

        return {
            "verdict": verdict,
            "analysis_type": "correlations",
            "categories_analyzed": categories_analyzed,
            "total_factors": total_factors,
            "high_correlation_pairs": high_corr_pairs,
            "total_high_corr_count": total_high_corr_count,
            "overlays_available": overlays_available,
        }

    def to_cli_report(self, max_rows: int = 10) -> str:
        """Human-readable summary for CLI/AI contexts.

        Includes:
        - Per-category correlation matrices (top-left submatrix)
        - Macro overlays when present:
          • Macro composite matrix (equity/fixed_income/cash/commodity/crypto)
          • Macro ETF matrix (curated), if computed
        """
        lines: List[str] = []
        lines.append("FACTOR CORRELATIONS (summary)")
        style_group_available = isinstance(self.style_exchanges, dict) and len(self.style_exchanges) > 0
        for name, df in self.matrices.items():
            if name == 'style' and style_group_available:
                continue
            title = f"[{name}]"
            display_df = df
            if name == 'industry' and df is not None and not getattr(df, 'empty', True):
                from utils.sector_config import resolve_sector_preferences
                preferred_tickers, preferred_labels = resolve_sector_preferences()
                preferred_names: List[str] = []
                for ticker in preferred_tickers:
                    label = preferred_labels.get(ticker)
                    if label and label not in preferred_names:
                        preferred_names.append(label)
                ordered: List[str] = []
                seen: set[str] = set()
                for name in preferred_names:
                    if name in df.columns and name not in seen:
                        ordered.append(name)
                        seen.add(name)
                for name in df.columns:
                    if name not in seen:
                        ordered.append(name)
                        seen.add(name)

                display_df = df.reindex(index=ordered, columns=ordered)
                try:
                    display_df.columns = [
                        _abbreviate_labels([str(c)], max_width=12, mapping=_DEFAULT_INDUSTRY_ABBR_MAP).get(str(c), str(c))
                        for c in display_df.columns
                    ]
                    display_df.index = [
                        _abbreviate_labels([str(r)], max_width=16, mapping=_DEFAULT_INDUSTRY_ABBR_MAP).get(str(r), str(r))
                        for r in display_df.index
                    ]
                except Exception:
                    pass

                block = _format_df_as_text(
                    display_df,
                    title=title,
                    max_rows=max_rows,
                    max_cols=max_rows,
                    wrap_header=False,
                )
            # Apply ticker display labels (non-industry categories only)
            elif df is not None and not getattr(df, 'empty', True) and (self.labels or self.market_exchanges):
                try:
                    display_df = df.copy()
                    # Build resolved labels for market tickers
                    def _pretty_exch(s: str) -> str:
                        p = str(s).replace('_', ' ').strip()
                        return p.title()
                    resolved = dict(self.labels or {})
                    style_tickers_cli = set(style_tickers)
                    if isinstance(self.market_exchanges, dict):
                        for tkr, exch in self.market_exchanges.items():
                            if str(tkr) in style_tickers_cli:
                                continue
                            resolved[tkr] = f"{_pretty_exch(exch)} ({tkr})"
                    if isinstance(self.style_exchanges, dict):
                        for exch, factors in self.style_exchanges.items():
                            pretty = _pretty_exch(exch)
                            if isinstance(factors, dict):
                                for ftype, tkr in factors.items():
                                    if not tkr:
                                        continue
                                    label = f"{pretty} Market ({tkr})" if ftype == 'market' else f"{pretty} {ftype.title()} ({tkr})"
                                    resolved[str(tkr)] = label
                    display_df.columns = [resolved.get(str(c), str(c)) for c in df.columns]
                    display_df.index = [resolved.get(str(r), str(r)) for r in df.index]
                except Exception:
                    display_df = df
                block = _format_df_as_text(
                    display_df,
                    title=title,
                    max_rows=max_rows,
                    max_cols=max_rows,
                    wrap_header=True,
                )
            else:
                block = _format_df_as_text(
                    display_df,
                    title=title,
                    max_rows=max_rows,
                    max_cols=max_rows,
                    wrap_header=(name != 'industry'),
                )
            lines.extend(block)

        # Overlays: Rate/market sensitivity plus macro matrices (if present)
        ov_dict = self.overlays or {}

        def _extract_matrix(payload: Any):
            if isinstance(payload, dict):
                mat = payload.get("matrix")
                if hasattr(mat, "empty") and not getattr(mat, "empty", True):
                    return mat
            return None

        def _format_matrix_block(
            title: str,
            df: Any,
            preferred_rows: Optional[List[str]] = None,
            label_map: Optional[Dict[str, str]] = None,
        ) -> List[str]:
            out: List[str] = []
            out.append(f"\n{title}")
            if df is None or getattr(df, 'empty', True):
                out.append("(empty)")
                return out
            # Limit for readability
            rows_all = list(df.index)
            if preferred_rows:
                preferred_upper = [str(r).upper() for r in preferred_rows]
                index_map = {str(r).upper(): r for r in rows_all}
                ordered = [index_map[t] for t in preferred_upper if t in index_map]
                if ordered:
                    rows_all = ordered
            rows = rows_all[:max_rows]
            cols = list(df.columns)[:min(max_rows, len(df.columns))]
            sub = df.reindex(index=rows, columns=cols).copy()
            col_width = 8
            header = " " * 12 + " ".join(f"{str(c)[:col_width].rjust(col_width)}" for c in sub.columns)
            out.append(header)
            label_map_upper = {str(k).upper(): str(v) for k, v in (label_map or {}).items()}
            row_label_width = 22
            for r in sub.index:
                rowvals = []
                for c in sub.columns:
                    try:
                        v = float(sub.loc[r, c])
                        rowvals.append(f"{v:+0.2f}")
                    except Exception:
                        rowvals.append(" nan")
                display_label = label_map_upper.get(str(r).upper(), str(r))
                out.append(f"{display_label[:row_label_width].ljust(row_label_width)}  " + " ".join(val.rjust(col_width) for val in rowvals))
            return out

        try:
            if isinstance(ov_dict, dict):
                rate_payload = ov_dict.get('rate_sensitivity')
                rate_df = _extract_matrix(rate_payload)
                if rate_df is not None:
                    display_df = rate_df.copy()
                    if isinstance(rate_payload, dict):
                        preferred = rate_payload.get('analysis_metadata', {}).get('preferred_tickers')
                        label_map = rate_payload.get('analysis_metadata', {}).get('preferred_labels')
                        if preferred:
                            ordered_rows = []
                            for ticker in preferred:
                                if ticker in display_df.index:
                                    ordered_rows.append(ticker)
                            for idx in display_df.index:
                                if idx not in ordered_rows:
                                    ordered_rows.append(idx)
                            display_df = display_df.reindex(index=ordered_rows)
                        if label_map:
                            display_df = display_df.rename(
                                index=lambda x: label_map.get(str(x), str(x))
                            )
                    lines.extend(_format_df_as_text(
                        display_df,
                        title="RATE BETA (ETF vs Δy)",
                        max_rows=max_rows,
                        max_cols=max_rows,
                        wrap_header=False,
                    ))

                market_payload = ov_dict.get('market_sensitivity')
                market_df = _extract_matrix(market_payload)
                if market_df is not None:
                    display_df = market_df.copy()
                    if isinstance(market_payload, dict):
                        preferred = market_payload.get('analysis_metadata', {}).get('preferred_tickers')
                        label_map = market_payload.get('analysis_metadata', {}).get('preferred_labels')
                        if preferred:
                            ordered_rows = []
                            for ticker in preferred:
                                if ticker in display_df.index:
                                    ordered_rows.append(ticker)
                            for idx in display_df.index:
                                if idx not in ordered_rows:
                                    ordered_rows.append(idx)
                            display_df = display_df.reindex(index=ordered_rows)
                        if label_map:
                            display_df = display_df.rename(
                                index=lambda x: label_map.get(str(x), str(x))
                            )
                    lines.extend(_format_df_as_text(
                        display_df,
                        title="MARKET BETA (ETF vs benchmarks)",
                        max_rows=max_rows,
                        max_cols=max_rows,
                        wrap_header=False,
                    ))

                # Add industry group rate betas
                rate_groups_payload = ov_dict.get('rate_sensitivity', {}).get('industry_groups') if ov_dict else None
                rate_groups_df = _extract_matrix(rate_groups_payload)
                if rate_groups_df is not None:
                    lines.extend(_format_df_as_text(
                        rate_groups_df,
                        title="RATE BETA (industry_groups vs Δy)",
                        max_rows=max_rows,
                        max_cols=max_rows,
                        wrap_header=False,
                    ))

                # Add industry group market betas
                market_groups_payload = ov_dict.get('market_sensitivity', {}).get('industry_groups') if ov_dict else None
                market_groups_df = _extract_matrix(market_groups_payload)
                if market_groups_df is not None:
                    lines.extend(_format_df_as_text(
                        market_groups_df,
                        title="MARKET BETA (industry_groups vs benchmarks)",
                        max_rows=max_rows,
                        max_cols=max_rows,
                        wrap_header=False,
                    ))

                mc = ov_dict.get('macro_composite_matrix')
                if isinstance(mc, dict) and hasattr(mc.get('matrix'), 'corr'):
                    lines.extend(_format_df_as_text(mc.get('matrix'),
                                                    title="MACRO COMPOSITE MATRIX (equity/fixed_income/cash/commodity/crypto)",
                                                    max_rows=max_rows,
                                                    max_cols=max_rows,
                                                    wrap_header=False))

                me = ov_dict.get('macro_etf_matrix')
                if isinstance(me, dict) and hasattr(me.get('matrix'), 'corr'):
                    groups = me.get('groups') or {}
                    if isinstance(groups, dict) and groups:
                        lines.append("\nMacro ETF groups:")
                        for g, etfs in groups.items():
                            lines.append(f"  - {g}: {len(etfs)} ETFs")
                    lines.extend(_format_df_as_text(me.get('matrix'),
                                                    title="MACRO ETF MATRIX (curated)",
                                                    max_rows=max_rows,
                                                    max_cols=max_rows,
                                                    wrap_header=False))
        except Exception:
            # Overlays are optional; keep CLI resilient
            pass
        return "\n".join(lines)

class FactorPerformanceResult:
    """
    Structured result for factor performance analysis.

    Attributes
    ----------
    per_factor : Dict[str, Any]
        Performance metrics per ETF.
    composites : Dict[str, Any]
        Composite performance across macro and factor categories.
    data_quality : Dict[str, Any]
        Coverage of tickers/groups used in composites.
    performance : Dict[str, Any]
        Timing metrics (ms).
    analysis_metadata : Dict[str, Any]
        Echo of analysis window and universe hash.
    """

    def __init__(self, per_factor: Dict[str, Any], composites: Dict[str, Any], data_quality: Dict[str, Any], performance: Dict[str, Any], analysis_metadata: Dict[str, Any]):
        self.per_factor = per_factor or {}
        self.composites = composites or {}
        self.data_quality = data_quality or {}
        self.performance = performance or {}
        self.analysis_metadata = analysis_metadata or {}

    @classmethod
    def from_core_analysis(cls,
                          per_factor_metrics: Dict[str, Any],
                          composite_performance: Dict[str, Any],
                          data_quality: Dict[str, Any],
                          performance: Dict[str, Any],
                          analysis_metadata: Dict[str, Any]) -> 'FactorPerformanceResult':
        """
        Create FactorPerformanceResult from core factor intelligence performance analysis data.

        ARCHITECTURE CONTEXT:
        This is the primary factory method for creating FactorPerformanceResult objects from
        core factor intelligence functions (compute_factor_performance_profiles, compute_composite_performance).
        It transforms raw performance analysis data into a structured result object ready for API responses.

        DATA FLOW:
        factor_intelligence_service.analyze_performance() → core analysis data → from_core_analysis() → FactorPerformanceResult

        INPUT DATA STRUCTURE:
        - per_factor_metrics: Output from compute_factor_performance_profiles() containing:
          • Performance metrics per ETF (Sharpe, volatility, returns) (Dict[str, Any])
        - composite_performance: Output from compute_composite_performance() containing:
          • Composite performance across macro and factor categories (Dict[str, Any])
        - data_quality: Coverage of tickers/groups used in composites (Dict[str, Any])
        - performance: Timing metrics (ms) for performance calculations (Dict[str, Any])
        - analysis_metadata: Analysis window, universe hash, and configuration (Dict[str, Any])

        Returns
        -------
        FactorPerformanceResult
            Structured result object ready for API serialization
        """
        return cls(
            per_factor=per_factor_metrics,
            composites=composite_performance,
            data_quality=data_quality,
            performance=performance,
            analysis_metadata=analysis_metadata
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'per_factor': self.per_factor,
            'composites': self.composites,
            'data_quality': self.data_quality,
            'performance': self.performance,
            'analysis_metadata': self.analysis_metadata,
        }

    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert FactorPerformanceResult to comprehensive API response format.

        CONSUMER ANALYSIS:
        - Direct API: Uses full structured response for performance analysis and charts
        - Claude/AI: Uses formatted_report (to_cli_report) for human-readable summaries
        - Frontend: Uses per_factor and composites for performance visualization

        Returns structured data suitable for JSON serialization and API responses.
        This method provides complete factor performance analysis including per-ETF
        metrics, composite performance, and data quality information.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing all factor performance data with the following fields:

            - per_factor: Dict[str, Any] - Performance metrics per ETF (Sharpe, volatility, returns)
            - composites: Dict[str, Any] - Composite performance across macro and factor categories
            - data_quality: Dict[str, Any] - Coverage of tickers/groups used in composites
            - performance: Dict[str, Any] - Timing metrics (ms) for performance calculations
            - analysis_metadata: Dict[str, Any] - Analysis window, universe hash, and configuration
            - formatted_report: str - Human-readable report (identical to to_cli_report)
        """
        return {
            "per_factor": _convert_to_json_serializable(self.per_factor),        # DICT: Performance metrics per ETF
            "composites": _convert_to_json_serializable(self.composites),        # DICT: Composite performance data
            "data_quality": _convert_to_json_serializable(self.data_quality),    # DICT: Coverage and quality info
            "performance": _convert_to_json_serializable(self.performance),      # DICT: Timing metrics
            "analysis_metadata": _convert_to_json_serializable(self.analysis_metadata),  # DICT: Analysis configuration
            "formatted_report": self.to_cli_report(),                           # STR: Human-readable report
        }

    def get_agent_snapshot(self) -> Dict[str, Any]:
        """Compact metrics for agent consumption."""
        per_factor = self.per_factor or {}
        factor_metrics: List[Dict[str, Any]] = []

        def _safe_float(val, default: float = 0.0) -> float:
            try:
                result = float(val) if val is not None else default
                return default if (math.isnan(result) or math.isinf(result)) else result
            except (TypeError, ValueError):
                return default

        for ticker, metrics in per_factor.items():
            if isinstance(metrics, dict):
                factor_metrics.append(
                    {
                        "ticker": ticker,
                        "sharpe_ratio": round(_safe_float(metrics.get("sharpe_ratio")), 3),
                        "annual_return_pct": round(_safe_float(metrics.get("annual_return")), 2),
                        "volatility_pct": round(_safe_float(metrics.get("volatility")), 2),
                    }
                )
        factor_metrics.sort(key=lambda x: (-x["sharpe_ratio"], x["ticker"]))
        top_factors = factor_metrics[:5]
        bottom_factors = list(reversed(factor_metrics[-3:])) if factor_metrics else []

        macro_summary: Dict[str, Dict[str, float]] = {}
        composites = self.composites or {}
        macro = composites.get("macro") or {}
        for name, metrics in macro.items():
            if isinstance(metrics, dict):
                macro_summary[name] = {
                    "sharpe_ratio": round(_safe_float(metrics.get("sharpe_ratio")), 3),
                    "annual_return_pct": round(_safe_float(metrics.get("annual_return")), 2),
                }

        if not factor_metrics:
            verdict = "no factor performance data"
        else:
            best_sharpe = top_factors[0]["sharpe_ratio"]
            if best_sharpe > 1.0:
                verdict = "strong factor performance"
            elif best_sharpe > 0.5:
                verdict = "moderate factor performance"
            elif best_sharpe > 0:
                verdict = "weak factor performance"
            else:
                verdict = "negative factor performance"

        return {
            "verdict": verdict,
            "analysis_type": "performance",
            "top_factors": top_factors,
            "bottom_factors": bottom_factors,
            "macro_composites": macro_summary,
            "factors_analyzed": len(factor_metrics),
        }

    def to_cli_report(self, top_n: int = 10) -> str:
        """Human-readable summary highlighting top Sharpe factors and macro composites."""
        lines: List[str] = []
        lines.append("FACTOR PERFORMANCE (summary)")
        pf = self.per_factor or {}
        # Sort by Sharpe where available
        try:
            ranked = sorted(pf.items(), key=lambda kv: (-(kv[1].get('sharpe_ratio') or float('-inf'))))[:top_n]
        except Exception:
            ranked = list(pf.items())[:top_n]
        if ranked:
            lines.append("\nTop factors by Sharpe:")
            for k, v in ranked:
                sr = v.get('sharpe_ratio')
                vol = v.get('volatility')
                ar = v.get('annual_return')
                lines.append(f"  {k:<10}  Sharpe={sr!s:<6}  Vol={vol!s:<6}  AnnRet={ar!s:<6}")
        comps = self.composites or {}
        macro = comps.get('macro') or {}
        if macro:
            lines.append("\nMacro composites:")
            for name, metrics in macro.items():
                sr = metrics.get('sharpe_ratio'); vol = metrics.get('volatility'); ar = metrics.get('annual_return')
                lines.append(f"  {name:<12}  Sharpe={sr!s:<6}  Vol={vol!s:<6}  AnnRet={ar!s:<6}")
        return "\n".join(lines)

class FactorReturnsResult:
    """
    Structured result for lightweight factor returns snapshot.

    Attributes
    ----------
    factors : Dict[str, Any]
        Individual ETF returns keyed by ticker.
    industry_groups : Dict[str, Any]
        Industry group composite returns keyed by group label.
    rankings : Dict[str, Any]
        Per-window rankings sorted by total return.
    by_category : Dict[str, Any]
        Category-level summaries per window.
    windows : List[str]
        Window labels that were computed (e.g., ["1m", "3m", "6m", "1y"]).
    data_quality : Dict[str, Any]
        Coverage and validation diagnostics.
    performance : Dict[str, Any]
        Timing metrics.
    analysis_metadata : Dict[str, Any]
        Analysis context metadata.
    """

    def __init__(
        self,
        factors: Dict[str, Any],
        industry_groups: Dict[str, Any],
        rankings: Dict[str, Any],
        by_category: Dict[str, Any],
        windows: List[str],
        data_quality: Dict[str, Any],
        performance: Dict[str, Any],
        analysis_metadata: Dict[str, Any],
    ):
        self.factors = factors or {}
        self.industry_groups = industry_groups or {}
        self.rankings = rankings or {}
        self.by_category = by_category or {}
        self.windows = windows or []
        self.data_quality = data_quality or {}
        self.performance = performance or {}
        self.analysis_metadata = analysis_metadata or {}

    @classmethod
    def from_core_analysis(
        cls,
        factors: Dict[str, Any],
        industry_groups: Dict[str, Any],
        rankings: Dict[str, Any],
        by_category: Dict[str, Any],
        windows: List[str],
        data_quality: Dict[str, Any],
        performance: Dict[str, Any],
        analysis_metadata: Dict[str, Any],
    ) -> 'FactorReturnsResult':
        """Create FactorReturnsResult from core factor returns analysis data."""
        return cls(
            factors=factors,
            industry_groups=industry_groups,
            rankings=rankings,
            by_category=by_category,
            windows=windows,
            data_quality=data_quality,
            performance=performance,
            analysis_metadata=analysis_metadata,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "factors": self.factors,
            "industry_groups": self.industry_groups,
            "rankings": self.rankings,
            "by_category": self.by_category,
            "windows": self.windows,
            "data_quality": self.data_quality,
            "performance": self.performance,
            "analysis_metadata": self.analysis_metadata,
        }

    def to_api_response(self) -> Dict[str, Any]:
        """Convert FactorReturnsResult to API response format."""
        return {
            "factors": _convert_to_json_serializable(self.factors),
            "industry_groups": _convert_to_json_serializable(self.industry_groups),
            "rankings": _convert_to_json_serializable(self.rankings),
            "by_category": _convert_to_json_serializable(self.by_category),
            "windows": _convert_to_json_serializable(self.windows),
            "data_quality": _convert_to_json_serializable(self.data_quality),
            "performance": _convert_to_json_serializable(self.performance),
            "analysis_metadata": _convert_to_json_serializable(self.analysis_metadata),
            "formatted_report": self.to_cli_report(),
        }

    def get_agent_snapshot(self) -> Dict[str, Any]:
        """Compact metrics for agent consumption."""
        rankings = self.rankings or {}
        top_per_window: Dict[str, List[Any]] = {}
        bottom_per_window: Dict[str, List[Any]] = {}
        for window, ranked_list in rankings.items():
            if isinstance(ranked_list, list) and ranked_list:
                top_per_window[window] = ranked_list[:3]
                bottom_per_window[window] = ranked_list[-3:]

        by_category = self.by_category or {}
        category_summary: Dict[str, Dict[str, Any]] = {}
        for cat, data in by_category.items():
            if isinstance(data, dict):
                category_summary[cat] = {
                    k: round(v, 4) if isinstance(v, (int, float)) else v
                    for k, v in data.items()
                }

        windows = [w for w in (self.windows or []) if isinstance(w, str)]
        current_month = datetime.now(UTC).month
        _WINDOW_ORDER = {
            "1m": 1,
            "3m": 3,
            "6m": 6,
            "ytd": max(current_month - 1, 1),
            "1y": 12,
            "2y": 24,
            "3y": 36,
            "5y": 60,
        }
        all_window_candidates = set(windows) | set(rankings.keys())
        known_windows = sorted(
            [
                w
                for w in all_window_candidates
                if isinstance(w, str) and w in _WINDOW_ORDER and isinstance(rankings.get(w), list) and rankings[w]
            ]
        )
        shortest_window = (
            min(
                known_windows,
                key=lambda w: (_WINDOW_ORDER.get(w, 999), w == "ytd", w),
            )
            if known_windows
            else None
        )
        if not known_windows:
            verdict = "no factor returns data"
        else:
            verdict = "factor returns data available"

        shortest_ranked = rankings.get(shortest_window) if shortest_window else None
        if isinstance(shortest_ranked, list) and shortest_ranked:
            top = shortest_ranked[0]
            if isinstance(top, dict):
                top_return = top.get("total_return", 0)
                if isinstance(top_return, (int, float)):
                    if top_return > 0.1:
                        verdict = "strong recent factor returns"
                    elif top_return > 0.03:
                        verdict = "moderate recent factor returns"
                    elif top_return > 0:
                        verdict = "weak recent factor returns"
                    else:
                        verdict = "negative recent factor returns"

        return {
            "verdict": verdict,
            "analysis_type": "returns",
            "windows": windows,
            "shortest_window": shortest_window,
            "top_per_window": top_per_window,
            "bottom_per_window": bottom_per_window,
            "category_summary": category_summary,
            "factors_analyzed": len(self.factors) if self.factors else 0,
        }

    def to_cli_report(self, top_n: int = 10) -> str:
        """Human-readable per-window top/bottom return snapshot."""
        lines: List[str] = []
        lines.append("FACTOR RETURNS SNAPSHOT")
        if self.windows:
            lines.append(f"Windows: {', '.join(self.windows)}")

        rankings = self.rankings or {}
        def _safe_total_return(entry: Dict[str, Any]) -> float:
            try:
                return float(entry.get("total_return"))
            except Exception:
                return 0.0

        for window in self.windows:
            ranked = rankings.get(window) or []
            if not ranked:
                continue

            lines.append(f"\n{window.upper()} Top {min(top_n, len(ranked))}:")
            for entry in ranked[:top_n]:
                ticker = entry.get("ticker") or "N/A"
                label = entry.get("label") or ticker
                category = entry.get("category") or "unknown"
                total_return = entry.get("total_return")
                lines.append(f"  {ticker:<8} {label:<28} {category:<12} {total_return!s:<8}")

            bottom = sorted(
                ranked,
                key=_safe_total_return
            )[:top_n]
            if bottom:
                lines.append(f"\n{window.upper()} Bottom {len(bottom)}:")
                for entry in bottom:
                    ticker = entry.get("ticker") or "N/A"
                    label = entry.get("label") or ticker
                    category = entry.get("category") or "unknown"
                    total_return = entry.get("total_return")
                    lines.append(f"  {ticker:<8} {label:<28} {category:<12} {total_return!s:<8}")

        return "\n".join(lines)

class OffsetRecommendationResult:
    """
    Structured result for correlation‑based offset recommendations.
    """

    def __init__(self, overexposed_label: str, recommendations: List[Dict[str, Any]], analysis_metadata: Dict[str, Any]):
        self.overexposed_label = overexposed_label
        self.recommendations = recommendations or []
        self.analysis_metadata = analysis_metadata or {}

    @classmethod
    def from_core_analysis(cls,
                          overexposed_label: str,
                          offset_recommendations: List[Dict[str, Any]],
                          analysis_metadata: Dict[str, Any]) -> 'OffsetRecommendationResult':
        """
        Create OffsetRecommendationResult from core factor intelligence offset analysis data.

        ARCHITECTURE CONTEXT:
        This is the primary factory method for creating OffsetRecommendationResult objects from
        core factor intelligence offset recommendation functions.
        It transforms raw offset analysis data into a structured result object ready for API responses.

        DATA FLOW:
        factor_intelligence_service.recommend_offsets() → core analysis data → from_core_analysis() → OffsetRecommendationResult

        INPUT DATA STRUCTURE:
        - overexposed_label: The factor/category that is overexposed (str)
        - offset_recommendations: List of offset recommendations with correlation data (List[Dict[str, Any]])
        - analysis_metadata: Analysis window, universe hash, and configuration (Dict[str, Any])

        Returns
        -------
        OffsetRecommendationResult
            Structured result object ready for API serialization
        """
        return cls(
            overexposed_label=overexposed_label,
            recommendations=offset_recommendations,
            analysis_metadata=analysis_metadata
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            'overexposed_label': self.overexposed_label,
            'recommendations': self.recommendations,
            'analysis_metadata': self.analysis_metadata,
        }

    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert OffsetRecommendationResult to comprehensive API response format.

        CONSUMER ANALYSIS:
        - Direct API: Uses full structured response for offset recommendations and portfolio rebalancing
        - Claude/AI: Uses formatted_report (to_cli_report) for human-readable recommendations
        - Frontend: Uses recommendations list for displaying offset suggestions with correlations

        Returns structured data suitable for JSON serialization and API responses.
        This method provides complete offset recommendation analysis including correlation-based
        suggestions for portfolio rebalancing.

        Returns
        -------
        Dict[str, Any]
            Dictionary containing all offset recommendation data with the following fields:

            - overexposed_label: str - The overexposed factor/ETF being analyzed
            - recommendations: List[Dict] - Ranked offset recommendations with correlations and metrics
            - analysis_metadata: Dict[str, Any] - Analysis configuration and metadata
            - formatted_report: str - Human-readable report (identical to to_cli_report)
        """
        return {
            "overexposed_label": self.overexposed_label,                        # STR: Overexposed factor identifier
            "recommendations": _convert_to_json_serializable(self.recommendations),  # LIST: Offset recommendations
            "analysis_metadata": _convert_to_json_serializable(self.analysis_metadata),  # DICT: Analysis metadata
            "formatted_report": self.to_cli_report(),                          # STR: Human-readable report
        }

    def get_agent_snapshot(self) -> dict:
        """Compact decision-oriented snapshot for agent consumption."""
        import math

        def _safe_float(val, default=0.0):
            if val is None:
                return default
            try:
                f = float(val)
                if f != f or math.isinf(f):  # NaN or inf
                    return default
                return f
            except (TypeError, ValueError):
                return default

        recs = self.recommendations or []
        top_recs = []
        for r in recs[:5]:
            top_recs.append({
                "label": r.get("label") or r.get("factor") or r.get("ticker") or "unknown",
                "correlation": _safe_float(r.get("correlation")),
                "sharpe_ratio": _safe_float(r.get("sharpe_ratio")),
                "category": r.get("category", "unknown"),
                "overexposed_label": r.get("overexposed_label"),  # which driver this hedge targets
            })

        has_recs = len(recs) > 0
        if has_recs:
            best = top_recs[0]
            verdict = f"Top hedge for {self.overexposed_label}: {best['label']} (corr={best['correlation']:.2f}, Sharpe={best['sharpe_ratio']:.2f})"
        else:
            verdict = f"No suitable hedges found for {self.overexposed_label}"

        return {
            "mode": "single",
            "overexposed_factor": self.overexposed_label,
            "verdict": verdict,
            "recommendation_count": len(recs),
            "top_recommendations": top_recs,
        }

    def to_cli_report(self, top_n: int = 10) -> str:
        """Human-readable recommendations list with basic ranking fields."""
        lines: List[str] = []
        lines.append(f"OFFSET RECOMMENDATIONS for {self.overexposed_label}")
        recs = (self.recommendations or [])[:top_n]
        if not recs:
            lines.append("(none)")
            return "\n".join(lines)
        for i, r in enumerate(recs, 1):
            lab = r.get('label') or r.get('factor') or r.get('ticker') or 'unknown'
            corr = r.get('correlation')
            sh = r.get('sharpe_ratio')
            cat = r.get('category')
            lines.append(f"  {i:>2}. {lab:<12}  Corr={corr!s:<6}  Sharpe={sh!s:<6}  Cat={cat!s:<10}")
        return "\n".join(lines)

class PortfolioOffsetRecommendationResult:
    """
    Portfolio-aware offset recommendations with detected drivers and suggested sizing.

    Attributes
    ----------
    drivers : List[Dict[str, Any]]
        Detected risk drivers (e.g., industries/factors) with metrics.
    recommendations : List[Dict[str, Any]]
        Recommended hedges with correlation, Sharpe, category, suggested_weight, and rationale.
    analysis_metadata : Dict[str, Any]
        Portfolio snapshot and configuration used for analysis.
    """

    def __init__(self, drivers: List[Dict[str, Any]], recommendations: List[Dict[str, Any]], analysis_metadata: Dict[str, Any]):
        self.drivers = drivers or []
        self.recommendations = recommendations or []
        self.analysis_metadata = analysis_metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            'drivers': self.drivers,
            'recommendations': self.recommendations,
            'analysis_metadata': self.analysis_metadata,
        }

    def to_api_response(self) -> Dict[str, Any]:
        return {
            'drivers': _convert_to_json_serializable(self.drivers),
            'recommendations': _convert_to_json_serializable(self.recommendations),
            'analysis_metadata': _convert_to_json_serializable(self.analysis_metadata),
            'formatted_report': self.to_cli_report(),
        }

    def get_agent_snapshot(self) -> dict:
        """Compact decision-oriented snapshot for agent consumption."""
        import math

        def _safe_float(val, default=0.0):
            if val is None:
                return default
            try:
                f = float(val)
                if f != f or math.isinf(f):  # NaN or inf
                    return default
                return f
            except (TypeError, ValueError):
                return default

        drivers = self.drivers or []
        top_drivers = []
        for d in drivers[:3]:
            top_drivers.append({
                "label": d.get("label") or d.get("id") or "unknown",
                "percent_of_portfolio": _safe_float(d.get("percent_of_portfolio") or d.get("factor_pct")),
                "driver_type": d.get("driver_type", "unknown"),
                "market_beta": _safe_float(d.get("market_beta")),
            })

        recs = self.recommendations or []
        top_recs = []
        for r in recs[:5]:
            top_recs.append({
                "label": r.get("label") or r.get("ticker") or "unknown",
                "correlation": _safe_float(r.get("correlation")),
                "sharpe_ratio": _safe_float(r.get("sharpe_ratio")),
                "category": r.get("category", "unknown"),
                "suggested_weight": _safe_float(r.get("suggested_weight")),
            })

        driver_count = len(drivers)
        rec_count = len(recs)
        if driver_count > 0 and rec_count > 0:
            top_driver = top_drivers[0]["label"]
            verdict = f"Portfolio has {driver_count} risk driver{'s' if driver_count != 1 else ''} (top: {top_driver}), {rec_count} hedge{'s' if rec_count != 1 else ''} available"
        elif driver_count > 0:
            verdict = f"Portfolio has {driver_count} risk driver{'s' if driver_count != 1 else ''} but no suitable hedges found"
        else:
            verdict = "No significant risk drivers detected in portfolio"

        return {
            "mode": "portfolio",
            "verdict": verdict,
            "driver_count": driver_count,
            "top_drivers": top_drivers,
            "recommendation_count": rec_count,
            "top_recommendations": top_recs,
        }

    def to_cli_report(self, top_n: int = 10) -> str:
        lines: List[str] = []
        lines.append("PORTFOLIO-AWARE OFFSET RECOMMENDATIONS")
        if self.drivers:
            lines.append("\nTop risk drivers:")
            for d in self.drivers:
                lab = d.get('label') or d.get('id')
                pct = d.get('percent_of_portfolio') or d.get('factor_pct')
                lines.append(f"  • {lab}: {pct!s}")
        recs = (self.recommendations or [])[:top_n]
        lines.append("\nRecommended hedges:")
        if not recs:
            lines.append("  (none)")
            return "\n".join(lines)
        for i, r in enumerate(recs, 1):
            lab = r.get('label') or r.get('ticker')
            cat = r.get('category')
            corr = r.get('correlation')
            sh = r.get('sharpe_ratio')
            w = r.get('suggested_weight')
            lines.append(f"  {i:>2}. {lab:<10}  Cat={cat!s:<10} Corr={corr!s:<6} Sharpe={sh!s:<6} Wgt={w!s:<6}")
        return "\n".join(lines)

