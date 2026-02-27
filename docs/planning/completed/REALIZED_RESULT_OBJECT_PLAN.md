# RealizedPerformanceResult Data Object (B-016)

## Context

The realized performance path (`analyze_realized_performance()`) returns a plain `Dict[str, Any]` with 30+ keys and a nested `realized_metadata` dict containing 30+ more keys. All consumers access fields via string-key `.get()` calls — fragile, no IDE support, no type checking. The hypothetical path already uses a proper `PerformanceResult` dataclass (`core/result_objects.py:3178-3668`) with factory methods (`from_core_analysis()`) and serialization (`to_api_response()`). This change brings the realized path to parity.

**Design decision:** Composition, not inheritance. `RealizedPerformanceResult` holds the same core metric fields as `PerformanceResult` (both come from `compute_performance_metrics()`) but does NOT inherit from it. The realized path has fundamentally different metadata and the hypothetical-specific fields (`_allocations`, `dividend_metrics`, `excluded_tickers`, `analysis_notes`) don't apply. Duplicating ~8 core metric fields is cleaner than an awkward inheritance hierarchy.

**Error handling:** The error return path stays as a plain dict `{"status": "error", ...}`. Callers already check `isinstance(result, dict) and result.get("status") == "error"` or `result.get("status") == "error"` before accessing the result. We preserve this pattern.

## Files to Modify

1. `core/result_objects.py` — Add `RealizedPerformanceResult`, `RealizedMetadata`, `RealizedIncomeMetrics`, `RealizedPnlBasis` dataclasses
2. `core/realized_performance_analysis.py` — Wrap return dict in `RealizedPerformanceResult.from_analysis_dict()`
3. `services/portfolio_service.py` — Update return type annotation
4. `mcp_tools/performance.py` — Refactor `_apply_date_window()` to accept/return typed object; update format handlers
5. `run_risk.py` — Update `run_realized_performance()` to handle typed result (line ~895)
6. `tests/core/test_realized_performance_analysis.py` — Update assertions for typed object
7. `tests/mcp_tools/test_performance.py` — Update assertions for typed object (including `_apply_date_window` tests)
8. `tests/services/test_portfolio_service.py` — Update assertions for typed object

## Changes

### 1. Add dataclasses to `core/result_objects.py`

Add after the `PerformanceResult` class (after end of class, approximately line ~3818). Keep them in this order since they compose upward.

#### 1a. `RealizedIncomeMetrics`

```python
@dataclass
class RealizedIncomeMetrics:
    """Income breakdown for realized performance analysis."""
    total: float
    dividends: float
    interest: float
    by_month: Dict[str, Any]
    by_symbol: Dict[str, Any]
    current_monthly_rate: float
    projected_annual: float
    yield_on_cost: float
    yield_on_value: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "dividends": self.dividends,
            "interest": self.interest,
            "by_month": self.by_month,
            "by_symbol": self.by_symbol,
            "current_monthly_rate": self.current_monthly_rate,
            "projected_annual": self.projected_annual,
            "yield_on_cost": self.yield_on_cost,
            "yield_on_value": self.yield_on_value,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RealizedIncomeMetrics":
        return cls(
            total=d.get("total", 0.0),
            dividends=d.get("dividends", 0.0),
            interest=d.get("interest", 0.0),
            by_month=d.get("by_month", {}),
            by_symbol=d.get("by_symbol", {}),
            current_monthly_rate=d.get("current_monthly_rate", 0.0),
            projected_annual=d.get("projected_annual", 0.0),
            yield_on_cost=d.get("yield_on_cost", 0.0),
            yield_on_value=d.get("yield_on_value", 0.0),
        )
```

#### 1b. `RealizedPnlBasis`

```python
@dataclass
class RealizedPnlBasis:
    """Methodology labels for each P&L track."""
    nav: str                # e.g. "nav_flow_synthetic_enhanced"
    nav_observed_only: str  # e.g. "nav_flow_observed_only"
    lot: str                # e.g. "fifo_observed_lots"

    def to_dict(self) -> Dict[str, str]:
        return {
            "nav": self.nav,
            "nav_observed_only": self.nav_observed_only,
            "lot": self.lot,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RealizedPnlBasis":
        return cls(
            nav=d.get("nav", "nav_flow_synthetic_enhanced"),
            nav_observed_only=d.get("nav_observed_only", "nav_flow_observed_only"),
            lot=d.get("lot", "fifo_observed_lots"),
        )
```

#### 1c. `RealizedMetadata`

```python
@dataclass
class RealizedMetadata:
    """
    Realized performance metadata: P&L tracks, income, data quality, synthetic positions.

    This is the typed equivalent of the ``realized_metadata`` nested dict returned by
    ``analyze_realized_performance()``.
    """
    # P&L tracks (nav_pnl_usd and reconciliation_gap_usd are Optional because
    # _apply_date_window sets them to None when NAV P&L can't be computed for
    # custom windows)
    realized_pnl: float
    unrealized_pnl: float
    net_contributions: float
    nav_pnl_usd: Optional[float]
    nav_pnl_synthetic_enhanced_usd: Optional[float]
    nav_pnl_observed_only_usd: Optional[float]
    nav_pnl_synthetic_impact_usd: Optional[float]
    lot_pnl_usd: float
    reconciliation_gap_usd: Optional[float]
    pnl_basis: RealizedPnlBasis
    nav_metrics_estimated: bool
    high_confidence_realized: bool
    # Income
    income: RealizedIncomeMetrics
    # Coverage and dates
    data_coverage: float
    inception_date: str
    # Synthetic position tracking
    # NOTE: synthetic_positions is a List[Dict[str, str]], NOT int.
    # Each entry is {"ticker": ..., "currency": ..., "direction": ..., "reason": ...}
    synthetic_positions: List[Dict[str, str]]
    synthetic_entry_count: int
    synthetic_current_position_count: int
    synthetic_current_position_tickers: List[str]
    synthetic_current_market_value: float
    synthetic_incomplete_trade_count: int
    # Data quality
    first_transaction_exit_count: int
    first_transaction_exit_details: List[Any]
    extreme_return_months: List[Any]
    # NOTE: data_quality_flags is a List[Dict[str, Any]], NOT Dict.
    # Each entry is {"code": str, "severity": str, "message": str, ...}
    data_quality_flags: List[Dict[str, Any]]
    unpriceable_symbol_count: int
    unpriceable_symbols: List[str]
    unpriceable_reason_counts: Dict[str, int]    # e.g. {"no_fmp_data": 5, "option_no_pricing": 8}
    unpriceable_reasons: Dict[str, str]           # symbol → reason string
    ibkr_pricing_coverage: Dict[str, Any]         # {"total_symbols_priced_via_ibkr": int, "by_instrument_type": dict}
    source_breakdown: Dict[str, int]
    data_warnings: List[str]
    # Optional series (only when include_series=True)
    monthly_nav: Optional[Dict[str, float]] = None
    growth_of_dollar: Optional[Dict[str, float]] = None
    # Internal diagnostics (stripped before API output)
    _postfilter: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "net_contributions": self.net_contributions,
            "nav_pnl_usd": self.nav_pnl_usd,
            "nav_pnl_synthetic_enhanced_usd": self.nav_pnl_synthetic_enhanced_usd,
            "nav_pnl_observed_only_usd": self.nav_pnl_observed_only_usd,
            "nav_pnl_synthetic_impact_usd": self.nav_pnl_synthetic_impact_usd,
            "lot_pnl_usd": self.lot_pnl_usd,
            "reconciliation_gap_usd": self.reconciliation_gap_usd,
            "pnl_basis": self.pnl_basis.to_dict(),
            "nav_metrics_estimated": self.nav_metrics_estimated,
            "high_confidence_realized": self.high_confidence_realized,
            "income": self.income.to_dict(),
            "data_coverage": self.data_coverage,
            "inception_date": self.inception_date,
            "synthetic_positions": self.synthetic_positions,
            "synthetic_entry_count": self.synthetic_entry_count,
            "synthetic_current_position_count": self.synthetic_current_position_count,
            "synthetic_current_position_tickers": self.synthetic_current_position_tickers,
            "synthetic_current_market_value": self.synthetic_current_market_value,
            "synthetic_incomplete_trade_count": self.synthetic_incomplete_trade_count,
            "first_transaction_exit_count": self.first_transaction_exit_count,
            "first_transaction_exit_details": self.first_transaction_exit_details,
            "extreme_return_months": self.extreme_return_months,
            "data_quality_flags": self.data_quality_flags,
            "unpriceable_symbol_count": self.unpriceable_symbol_count,
            "unpriceable_symbols": self.unpriceable_symbols,
            "unpriceable_reason_counts": self.unpriceable_reason_counts,
            "unpriceable_reasons": self.unpriceable_reasons,
            "ibkr_pricing_coverage": self.ibkr_pricing_coverage,
            "source_breakdown": self.source_breakdown,
            "data_warnings": self.data_warnings,
        }
        if self.monthly_nav is not None:
            d["monthly_nav"] = self.monthly_nav
        if self.growth_of_dollar is not None:
            d["growth_of_dollar"] = self.growth_of_dollar
        if self._postfilter is not None:
            d["_postfilter"] = self._postfilter
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RealizedMetadata":
        return cls(
            realized_pnl=d.get("realized_pnl", 0.0),
            unrealized_pnl=d.get("unrealized_pnl", 0.0),
            net_contributions=d.get("net_contributions", 0.0),
            nav_pnl_usd=d.get("nav_pnl_usd"),
            nav_pnl_synthetic_enhanced_usd=d.get("nav_pnl_synthetic_enhanced_usd"),
            nav_pnl_observed_only_usd=d.get("nav_pnl_observed_only_usd"),
            nav_pnl_synthetic_impact_usd=d.get("nav_pnl_synthetic_impact_usd"),
            lot_pnl_usd=d.get("lot_pnl_usd", 0.0),
            reconciliation_gap_usd=d.get("reconciliation_gap_usd"),
            pnl_basis=RealizedPnlBasis.from_dict(d.get("pnl_basis", {})),
            nav_metrics_estimated=d.get("nav_metrics_estimated", False),
            high_confidence_realized=d.get("high_confidence_realized", False),
            income=RealizedIncomeMetrics.from_dict(d.get("income", {})),
            data_coverage=d.get("data_coverage", 0.0),
            inception_date=d.get("inception_date", ""),
            synthetic_positions=d.get("synthetic_positions", []),
            synthetic_entry_count=d.get("synthetic_entry_count", 0),
            synthetic_current_position_count=d.get("synthetic_current_position_count", 0),
            synthetic_current_position_tickers=d.get("synthetic_current_position_tickers", []),
            synthetic_current_market_value=d.get("synthetic_current_market_value", 0.0),
            synthetic_incomplete_trade_count=d.get("synthetic_incomplete_trade_count", 0),
            first_transaction_exit_count=d.get("first_transaction_exit_count", 0),
            first_transaction_exit_details=d.get("first_transaction_exit_details", []),
            extreme_return_months=d.get("extreme_return_months", []),
            data_quality_flags=d.get("data_quality_flags", []),
            unpriceable_symbol_count=d.get("unpriceable_symbol_count", 0),
            unpriceable_symbols=d.get("unpriceable_symbols", []),
            unpriceable_reason_counts=d.get("unpriceable_reason_counts", {}),
            unpriceable_reasons=d.get("unpriceable_reasons", {}),
            ibkr_pricing_coverage=d.get("ibkr_pricing_coverage", {}),
            source_breakdown=d.get("source_breakdown", {}),
            data_warnings=d.get("data_warnings", []),
            monthly_nav=d.get("monthly_nav"),
            growth_of_dollar=d.get("growth_of_dollar"),
            _postfilter=d.get("_postfilter"),
        )
```

#### 1d. `RealizedPerformanceResult`

```python
@dataclass
class RealizedPerformanceResult:
    """
    Typed result object for realized performance analysis.

    Mirrors the ``PerformanceResult`` pattern for the hypothetical path.
    Core metric fields (returns, risk_metrics, etc.) come from the shared
    ``compute_performance_metrics()`` engine. Realized-specific data lives
    in ``realized_metadata``.

    Usage:
        result = RealizedPerformanceResult.from_analysis_dict(raw_dict)
        summary = result.to_summary()
        full = result.to_dict()
    """
    # Core metrics (same structure as PerformanceResult, from compute_performance_metrics)
    analysis_period: Dict[str, Any]
    returns: Dict[str, float]
    risk_metrics: Dict[str, float]
    risk_adjusted_returns: Dict[str, float]
    benchmark_analysis: Dict[str, Any]
    benchmark_comparison: Dict[str, float]
    monthly_stats: Dict[str, float]
    risk_free_rate: float
    monthly_returns: Dict[str, float]
    # Realized-specific
    realized_metadata: RealizedMetadata
    # Warnings (shared pattern with PerformanceResult)
    warnings: Optional[List[str]] = None
    # Date-window indicator (set by _apply_date_window)
    custom_window: Optional[Dict[str, Any]] = None

    # ── Factory ─────────────────────────────────────────────────────────

    @classmethod
    def from_analysis_dict(cls, d: Dict[str, Any]) -> "RealizedPerformanceResult":
        """Build from the raw dict returned by analyze_realized_performance().

        The raw dict has core metric keys at the top level plus a nested
        ``realized_metadata`` dict. Top-level convenience copies (realized_pnl,
        income_total, etc.) are ignored here — they are re-derived from
        ``realized_metadata`` in ``to_dict()``.
        """
        meta_raw = d.get("realized_metadata", {})
        return cls(
            analysis_period=d.get("analysis_period", {}),
            returns=d.get("returns", {}),
            risk_metrics=d.get("risk_metrics", {}),
            risk_adjusted_returns=d.get("risk_adjusted_returns", {}),
            benchmark_analysis=d.get("benchmark_analysis", {}),
            benchmark_comparison=d.get("benchmark_comparison", {}),
            monthly_stats=d.get("monthly_stats", {}),
            risk_free_rate=d.get("risk_free_rate", 0.0),
            monthly_returns=d.get("monthly_returns", {}),
            realized_metadata=RealizedMetadata.from_dict(meta_raw),
            warnings=d.get("warnings"),
            custom_window=d.get("custom_window"),
        )

    # ── Serialization ───────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the same dict format that analyze_realized_performance()
        historically returned. Ensures backward compatibility with all consumers.

        Includes both the nested ``realized_metadata`` and the top-level
        convenience copies (realized_pnl, income_total, etc.).
        """
        meta_dict = self.realized_metadata.to_dict()
        income = self.realized_metadata.income

        d: Dict[str, Any] = {
            "analysis_period": self.analysis_period,
            "returns": self.returns,
            "risk_metrics": self.risk_metrics,
            "risk_adjusted_returns": self.risk_adjusted_returns,
            "benchmark_analysis": self.benchmark_analysis,
            "benchmark_comparison": self.benchmark_comparison,
            "monthly_stats": self.monthly_stats,
            "risk_free_rate": self.risk_free_rate,
            "monthly_returns": self.monthly_returns,
            "realized_metadata": meta_dict,
            # Top-level convenience copies (match historical dict keys)
            "realized_pnl": self.realized_metadata.realized_pnl,
            "unrealized_pnl": self.realized_metadata.unrealized_pnl,
            "income_total": income.total,
            "income_yield_on_cost": income.yield_on_cost,
            "income_yield_on_value": income.yield_on_value,
            "data_coverage": self.realized_metadata.data_coverage,
            "inception_date": self.realized_metadata.inception_date,
            "nav_pnl_usd": self.realized_metadata.nav_pnl_usd,
            "nav_pnl_observed_only_usd": self.realized_metadata.nav_pnl_observed_only_usd,
            "nav_pnl_synthetic_impact_usd": self.realized_metadata.nav_pnl_synthetic_impact_usd,
            "lot_pnl_usd": self.realized_metadata.lot_pnl_usd,
            "reconciliation_gap_usd": self.realized_metadata.reconciliation_gap_usd,
            "nav_metrics_estimated": self.realized_metadata.nav_metrics_estimated,
            "high_confidence_realized": self.realized_metadata.high_confidence_realized,
            "pnl_basis": self.realized_metadata.pnl_basis.to_dict(),
        }
        if self.warnings:
            d["warnings"] = self.warnings
        if self.custom_window is not None:
            d["custom_window"] = self.custom_window
        return d

    def to_summary(self, benchmark_ticker: str = "SPY") -> Dict[str, Any]:
        """Build the summary-format response dict.

        Replaces the inline summary construction in mcp_tools/performance.py
        (lines 681-728). Returns the same dict shape that the MCP summary
        format historically returned.
        """
        meta = self.realized_metadata
        income = meta.income
        benchmark = self.benchmark_analysis

        return {
            "status": "success",
            "mode": "realized",
            "start_date": self.analysis_period.get("start_date"),
            "end_date": self.analysis_period.get("end_date"),
            "total_return": self.returns.get("total_return"),
            "cagr": self.returns.get("annualized_return"),
            "annualized_return": self.returns.get("annualized_return"),
            "volatility": self.risk_metrics.get("volatility"),
            "sharpe_ratio": self.risk_adjusted_returns.get("sharpe_ratio"),
            "max_drawdown": self.risk_metrics.get("maximum_drawdown"),
            "win_rate": self.returns.get("win_rate"),
            "analysis_years": self.analysis_period.get("years", 0),
            "benchmark_ticker": benchmark.get("benchmark_ticker", benchmark_ticker),
            "alpha_annual": benchmark.get("alpha_annual"),
            "beta": benchmark.get("beta"),
            "realized_pnl": meta.realized_pnl,
            "unrealized_pnl": meta.unrealized_pnl,
            "income_total": income.total,
            "income_yield_on_cost": income.yield_on_cost,
            "income_yield_on_value": income.yield_on_value,
            "data_coverage": meta.data_coverage,
            "inception_date": meta.inception_date,
            "synthetic_current_position_count": meta.synthetic_current_position_count,
            "synthetic_current_market_value": meta.synthetic_current_market_value,
            "nav_pnl_usd": meta.nav_pnl_usd,
            "lot_pnl_usd": meta.lot_pnl_usd,
            "reconciliation_gap_usd": meta.reconciliation_gap_usd,
            "nav_metrics_estimated": meta.nav_metrics_estimated,
            "high_confidence_realized": meta.high_confidence_realized,
            "pnl_basis": meta.pnl_basis.to_dict(),
            "data_warnings": meta.data_warnings,
            "custom_window": self.custom_window,
            "performance_category": self._categorize_performance(),
            "key_insights": self._generate_key_insights(),
        }
```

**Presentation methods on the result object:**

`PerformanceResult` already has `_categorize_performance()` and `_generate_key_insights()` as instance methods (lines ~3433, ~3453 in `result_objects.py`). The MCP layer currently has standalone dict-based duplicates: `_categorize_performance_from_metrics()` and `_generate_key_insights_from_metrics()` (lines ~71-130 in `mcp_tools/performance.py`), explicitly labeled "Mirror PerformanceResult._categorize_performance for dict-based realized output."

Now that we have a typed result object, move these into `RealizedPerformanceResult` as instance methods (same pattern as `PerformanceResult`) and delete the MCP duplicates:

```python
def _categorize_performance(self) -> str:
    """Categorize performance based on risk-adjusted metrics."""
    sharpe = self.risk_adjusted_returns.get("sharpe_ratio")
    annual_return = self.returns.get("annualized_return")
    if sharpe is None or annual_return is None:
        return "poor"
    if sharpe >= 1.5 and annual_return >= 0.15:
        return "excellent"
    elif sharpe >= 1.0 and annual_return >= 0.10:
        return "good"
    elif sharpe >= 0.5 and annual_return >= 0.05:
        return "fair"
    return "poor"

def _generate_key_insights(self) -> List[str]:
    """Generate key insights bullets based on performance metrics."""
    insights: List[str] = []
    alpha = self.benchmark_analysis.get("alpha_annual")
    if alpha is not None and alpha > 5:
        insights.append(f"• Strong alpha generation (+{alpha:.1f}% vs benchmark)")
    elif alpha is not None and alpha < -2:
        insights.append(f"• Underperforming benchmark ({alpha:.1f}% alpha)")
    sharpe = self.risk_adjusted_returns.get("sharpe_ratio")
    if sharpe is not None and sharpe > 1.2:
        insights.append(f"• Excellent risk-adjusted returns (Sharpe: {sharpe:.2f})")
    elif sharpe is not None and sharpe < 0.5:
        insights.append(f"• Poor risk-adjusted returns (Sharpe: {sharpe:.2f})")
    volatility = self.risk_metrics.get("volatility")
    benchmark_vol = self.benchmark_comparison.get("benchmark_volatility")
    if volatility is not None and benchmark_vol is not None and benchmark_vol > 0 and volatility > benchmark_vol * 1.2:
        insights.append(f"• High volatility ({volatility:.1f}% vs {benchmark_vol:.1f}% benchmark)")
    win_rate = self.returns.get("win_rate")
    if win_rate is not None and win_rate > 65:
        insights.append(f"• High consistency ({win_rate:.0f}% positive months)")
    elif win_rate is not None and win_rate < 50:
        insights.append(f"• Low consistency ({win_rate:.0f}% positive months)")
    max_dd = self.risk_metrics.get("maximum_drawdown")
    if max_dd is not None and abs(max_dd) > 25:
        insights.append(f"• Significant drawdown risk (max: {max_dd:.1f}%)")
    return insights
```

Add `to_api_response()` as the single entry point for full API output:

```python
def to_api_response(self, benchmark_ticker: str = "SPY") -> Dict[str, Any]:
    """Full API response — single source of truth for realized output shape.

    Mirrors PerformanceResult.to_api_response() pattern. Includes presentation
    extras (performance_category, key_insights). Strips internal diagnostics.
    """
    response = self.to_dict()
    response.get("realized_metadata", {}).pop("_postfilter", None)
    response["status"] = "success"
    response["mode"] = "realized"
    response["performance_category"] = self._categorize_performance()
    response["key_insights"] = self._generate_key_insights()
    return response
```

Then `to_summary()` should also use the instance methods instead of relying on external helpers:
```python
def to_summary(self, benchmark_ticker: str = "SPY") -> Dict[str, Any]:
    ...
    summary["performance_category"] = self._categorize_performance()
    summary["key_insights"] = self._generate_key_insights()
    return summary
```

**MCP cleanup:** Delete `_categorize_performance_from_metrics()` and `_generate_key_insights_from_metrics()` from `mcp_tools/performance.py` (lines ~71-130). These are now methods on the result object.

### 2. Update `analyze_realized_performance()` in `core/realized_performance_analysis.py`

**Location:** End of function, line ~2187

**Current code:**
```python
        return performance_metrics
```

**New code:**
```python
        from core.result_objects import RealizedPerformanceResult
        return RealizedPerformanceResult.from_analysis_dict(performance_metrics)
```

The import is at point-of-use to avoid circular imports (same pattern used for `PerformanceResult` in `portfolio_risk.py`).

The error return at line ~2190 stays as-is:
```python
    except Exception as exc:
        return {
            "status": "error",
            "message": f"Realized performance analysis failed: {exc}",
            "data_warnings": sorted(set(warnings)) if warnings else [],
        }
```

### 3. Update `PortfolioService.analyze_realized_performance()` in `services/portfolio_service.py`

**Location:** Line ~618

**Change:** Update return type annotation:
```python
# Before
def analyze_realized_performance(self, ...) -> Dict[str, Any]:

# After
def analyze_realized_performance(self, ...) -> Union["RealizedPerformanceResult", Dict[str, Any]]:
```

Add `Union` to imports if not present. The function body remains unchanged — it already passes through the result from `_analyze_realized_performance()`, which now returns a `RealizedPerformanceResult` on success.

The error check at line ~678 needs updating:
```python
# Before
if isinstance(result, dict) and result.get("status") == "error":

# After (same — error path still returns dict)
if isinstance(result, dict) and result.get("status") == "error":
```
No change needed — the `isinstance(result, dict)` check naturally excludes `RealizedPerformanceResult`.

### 4. Update `mcp_tools/performance.py`

#### 4a. Update `_run_realized_with_service()` return annotation (line ~393)

```python
# Before
def _run_realized_with_service(...) -> dict:

# After
def _run_realized_with_service(...) -> Union["RealizedPerformanceResult", Dict[str, Any]]:
```

#### 4a2. Error check after `_run_realized_with_service()` (line ~668)

```python
# Before
if realized_result.get("status") == "error":

# After
if isinstance(realized_result, dict) and realized_result.get("status") == "error":
```

#### 4b. Refactor `_apply_date_window()` (line ~250)

Change signature to accept `RealizedPerformanceResult`, return typed result or error dict:
```python
# Before
def _apply_date_window(result: dict, start_date: Optional[str], end_date: Optional[str]) -> dict:

# After
def _apply_date_window(
    result: "RealizedPerformanceResult",
    start_date: Optional[str],
    end_date: Optional[str],
) -> Union["RealizedPerformanceResult", Dict[str, Any]]:
```

Update the function body to use typed field access instead of `.get()`:
- `result.monthly_returns` instead of `result.get("monthly_returns")`
- `result.realized_metadata._postfilter` instead of `result.get("realized_metadata", {}).get("_postfilter", {})`
- `result.benchmark_analysis.get("benchmark_ticker")` instead of `result.get("benchmark_analysis", {}).get("benchmark_ticker")`

The function calls `compute_performance_metrics()` (or `_single_month_metrics` for 1-month windows) which returns a dict. Build a new `RealizedPerformanceResult` from the recomputed metrics + original metadata.

**Branches to preserve:**
1. One-month window (line ~315): calls `_single_month_metrics()` instead of `compute_performance_metrics()`
2. Two-month warning (line ~337): appends warning about limited statistical significance
3. NAV P&L recomputation (lines ~340-361): recomputes `nav_pnl_usd` from windowed NAV; sets to `None` if opening/ending NAV unavailable
4. Reconciliation gap nulling (line ~385): `reconciliation_gap_usd = None` for custom windows
5. `custom_window` dict shape (lines ~373-381): Must match existing format with `start_date`, `end_date`, `full_inception`, `note` keys — NOT `applied_start`/`applied_end`

```python
# After recomputing metrics from windowed series:
from core.result_objects import RealizedPerformanceResult, RealizedMetadata
import copy

# Build updated metadata with windowed NAV P&L and nulled reconciliation
updated_meta = copy.copy(result.realized_metadata)
updated_meta.nav_pnl_usd = round(nav_pnl_usd, 2) if nav_pnl_usd is not None else None
updated_meta.reconciliation_gap_usd = None
updated_meta.data_warnings = sorted(set(warnings))

windowed_dict = dict(metrics)  # from compute_performance_metrics or _single_month_metrics
windowed_dict["realized_metadata"] = updated_meta.to_dict()
windowed_dict["custom_window"] = {
    "start_date": snapped_start_iso,
    "end_date": snapped_end_iso,
    "full_inception": result.realized_metadata.inception_date,
    "note": (
        "Return/risk metrics and NAV P&L are for the custom window. "
        "Lot-based P&L (realized/unrealized/income) reflects all-time FIFO. "
        "Reconciliation gap is not applicable for custom windows."
    ),
}
return RealizedPerformanceResult.from_analysis_dict(windowed_dict)
```

On error, return a dict (unchanged — error dicts are checked by caller before typed access):
```python
return {"status": "error", "error": "..."}
```

**Important:** The caller at line ~674-677 must handle both error dict and typed result:
```python
if normalized_start or normalized_end:
    windowed = _apply_date_window(realized_result, normalized_start, normalized_end)
    if isinstance(windowed, dict) and windowed.get("status") == "error":
        return windowed
    realized_result = windowed
```

#### 4c. `_postfilter` cleanup (line ~679)

**IMPORTANT:** Do NOT mutate the result object in place — it may be cached by `PortfolioService` and reused for subsequent requests (including windowed requests that need `_postfilter` data). Instead, strip `_postfilter` only from the output dict.

```python
# Before
realized_result.get("realized_metadata", {}).pop("_postfilter", None)

# After — defer stripping to output serialization, not on the cached object.
# Remove the in-place pop entirely. Instead, strip _postfilter in each format branch:
# - summary: to_summary() never includes _postfilter (no change needed)
# - full: strip from the serialized dict
# - report: strip from the serialized dict
```

In the full-format branch (4e), strip after serialization:
```python
if format == "full":
    response = realized_result.to_dict()
    response.get("realized_metadata", {}).pop("_postfilter", None)
    response["status"] = "success"
    response["mode"] = "realized"
    return response
```

In the report-format branch (4f), same pattern:
```python
result_dict = realized_result.to_dict()
result_dict.get("realized_metadata", {}).pop("_postfilter", None)
return {
    "status": "success",
    "mode": "realized",
    "report": _format_realized_report(result_dict, benchmark_ticker),
}
```

Alternatively, add an `exclude_internal` parameter to `RealizedMetadata.to_dict()` that skips `_postfilter` when True, and have `RealizedPerformanceResult.to_dict(exclude_internal=True)` as the default for API output. Either approach works — the key constraint is: **never mutate the cached object**.

#### 4d. Summary format (lines 681-728)

```python
# Before: 50-line inline dict construction from nested .get() calls

# After:
if format == "summary":
    return realized_result.to_summary(benchmark_ticker=benchmark_ticker)
    # performance_category and key_insights are now included by to_summary()
```

#### 4e. Full format (lines 730-734)

```python
# Before
if format == "full":
    response = dict(realized_result)
    response["status"] = "success"
    response["mode"] = "realized"
    return response

# After
if format == "full":
    return realized_result.to_api_response(benchmark_ticker=benchmark_ticker)
    # to_api_response() handles status, mode, performance_category,
    # key_insights, and _postfilter stripping
```

#### 4f. Report format (lines 736-740)

```python
# Before
return {
    "status": "success",
    "mode": "realized",
    "report": _format_realized_report(realized_result, benchmark_ticker),
}

# After — use to_api_response() for the dict, then extract report
result_dict = realized_result.to_api_response(benchmark_ticker=benchmark_ticker)
return {
    "status": "success",
    "mode": "realized",
    "report": _format_realized_report(result_dict, benchmark_ticker),
}
```

#### 4g. Delete MCP presentation helpers (lines ~71-130)

Delete `_categorize_performance_from_metrics()` and `_generate_key_insights_from_metrics()` from `mcp_tools/performance.py`. These are now instance methods on `RealizedPerformanceResult`.

### 5. Update `run_risk.py` CLI consumer

**Location:** `run_risk.py` line ~895

`run_realized_performance()` calls `PortfolioService.analyze_realized_performance()` and accesses the result with `.get()`:
```python
# Line 895 — error check uses dict .get()
if result.get("status") == "error":
    print(f"Error: {result.get('message', 'Realized performance analysis failed')}")
    return result if return_data else None

# Line 904 — passes result to _format_realized_report()
print(_format_realized_report(result, benchmark_ticker))
```

**Changes:**
```python
# Error check: guard with isinstance (success path returns typed object, not dict)
if isinstance(result, dict) and result.get("status") == "error":
    print(f"Error: {result.get('message', 'Realized performance analysis failed')}")
    return result if return_data else None

# Format report: convert to dict for the formatting function
print(_format_realized_report(result.to_dict(), benchmark_ticker))
```

If `return_data=True`, the caller gets a `RealizedPerformanceResult` object instead of a dict. This is intentional and desired.

Also update the function's return type annotation and docstring to reflect the new return type:
```python
# Before
def run_realized_performance(...) -> Optional[Dict]:

# After
def run_realized_performance(...) -> Optional[Union["RealizedPerformanceResult", Dict]]:
```

### 6. Update tests

#### 6a. `tests/core/test_realized_performance_analysis.py`

Tests that call `analyze_realized_performance()` will now receive a `RealizedPerformanceResult` instead of a dict on success. Update assertions:

```python
# Before
assert result["returns"]["total_return"] > 0
assert result["realized_metadata"]["data_coverage"] > 0

# After
from core.result_objects import RealizedPerformanceResult
assert isinstance(result, RealizedPerformanceResult)
assert result.returns["total_return"] > 0
assert result.realized_metadata.data_coverage > 0
```

For tests that check the error path, assertions stay unchanged (error returns a dict).

**Alternative approach for minimal test churn:** If many tests do deep dict access, they can call `result.to_dict()` at the top and keep existing dict assertions. This is acceptable for the initial migration.

#### 6b. `tests/mcp_tools/test_performance.py`

Tests that mock `analyze_realized_performance` need to return a `RealizedPerformanceResult` from the mock instead of a dict. The simplest approach: build a dict fixture, then wrap it:

```python
mock_result = RealizedPerformanceResult.from_analysis_dict(mock_dict)
mock_service.analyze_realized_performance.return_value = mock_result
```

**Important:** Tests for `_apply_date_window()` (lines ~313, ~348, ~368) currently pass dict payloads directly. These must be updated to pass `RealizedPerformanceResult` objects instead. Build a fixture dict with `realized_metadata` containing `_postfilter` data, wrap it with `from_analysis_dict()`, and pass that.

**Important:** Tests that monkeypatch `_categorize_performance_from_metrics` / `_generate_key_insights_from_metrics` (lines ~454-455) must be updated since those MCP helpers are deleted. Either remove the monkeypatches (the methods now live on the result object and don't need patching), or patch `RealizedPerformanceResult._categorize_performance` / `_generate_key_insights` instead.

#### 6c. `tests/services/test_portfolio_service.py`

Same pattern as 6b — mock the core function to return a `RealizedPerformanceResult`.

## Verification

1. **Unit tests:** `python3 -m pytest tests/core/test_realized_performance_analysis.py tests/mcp_tools/test_performance.py tests/services/test_portfolio_service.py -v`
2. **Full test suite:** `python3 -m pytest tests/ -x -q`
3. **Round-trip fidelity test:** Add a test that builds a `RealizedPerformanceResult` from a known dict via `from_analysis_dict()`, calls `to_dict()`, and checks key fields match. Note: the round-trip is NOT exact because `to_dict()` adds top-level convenience copies (realized_pnl, income_total, etc.) that the input dict may also have at the top level. Test should verify that `output["realized_metadata"]` matches `input["realized_metadata"]` and that core metric keys match.
4. **MCP smoke test:** `get_performance(mode="realized")` — verify output format matches pre-change
5. **MCP summary test:** `get_performance(mode="realized", format="summary")` — verify all summary fields present
6. **MCP full test:** `get_performance(mode="realized", format="full")` — verify all fields present

## Codex Review Log

### Review 1 (2026-02-15)

**HIGH findings (all addressed):**
1. `synthetic_positions` typed as `int` but actual runtime type is `List[Dict[str, str]]` — **Fixed:** corrected to `List[Dict[str, str]]` with default `[]`
2. `data_quality_flags` typed as `Dict[str, Any]` but actual runtime type is `List[Dict[str, Any]]` — **Fixed:** corrected to `List[Dict[str, Any]]` with default `[]`
3. `nav_pnl_usd` and `reconciliation_gap_usd` typed non-optional but `_apply_date_window` sets them to `None` — **Fixed:** made `Optional[float]` with `None` defaults in `from_dict()`
4. Missing consumer: `run_risk.py:895` uses `.get()` on the result — **Fixed:** added Step 5 for `run_risk.py`
5. `custom_window` dict shape wrong (`applied_start`/`applied_end` vs `start_date`/`end_date`/`full_inception`/`note`) — **Fixed:** corrected to match existing shape
6. Backward compat: changing return type breaks all dict consumers — **Addressed:** all consumers enumerated and updated in steps 2-6

**MED findings (all addressed):**
1. `_apply_date_window` refactor missing branch preservation (1-month, 2-month warning, NAV recompute, reconciliation nulling) — **Fixed:** added explicit branch list in step 4b
2. `_apply_date_window` tests pass dict payloads directly — **Fixed:** added note in step 6b
3. Round-trip test fragility from conditional serialization — **Fixed:** updated verification note

**LOW findings (acknowledged):**
1. Line number for end of `PerformanceResult` class was stale — **Fixed:** updated to ~3818
2. Circular import risk — manageable with lazy imports as proposed

### Review 2 (2026-02-15)

**HIGH (1 — addressed):**
1. Cache mutation: setting `_postfilter = None` in-place on the cached object breaks subsequent windowed requests that need `_postfilter` data — **Fixed:** removed in-place mutation; strip `_postfilter` only from serialized output dicts in each format branch

**LOW (1 — addressed):**
1. `_apply_date_window` return type inconsistent (typed-only signature but dict error returns) — **Fixed:** return type is now `Union[RealizedPerformanceResult, Dict[str, Any]]`

### Review 3 (2026-02-15)

**MED (1 — addressed):**
1. `_postfilter` leaks into summary helper inputs via unsanitized `to_dict()` — **Fixed:** summary branch now builds sanitized dict (strips `_postfilter`) before passing to `_categorize_performance_from_metrics()` / `_generate_key_insights_from_metrics()`

**LOW (2 — addressed):**
1. `run_realized_performance()` annotation/docstring not updated — **Fixed:** added annotation update to Step 5
2. `_run_realized_with_service()` return annotation stale — **Fixed:** added Step 4a with `Union` return type

### Review 4 (2026-02-15) — to_api_response + presentation methods

**Findings (2 — both addressed):**
1. `_generate_key_insights` port dropped `"• "` bullet prefix from insight strings — output content change vs current helpers and `PerformanceResult` — **Fixed:** restored `"• "` prefix on all insight strings
2. Tests monkeypatch deleted MCP helpers (`_categorize_performance_from_metrics` / `_generate_key_insights_from_metrics` at test lines ~454-455) — will break — **Fixed:** added migration note in step 6b

### Pre-implementation check (2026-02-15) — IBKR instrument tagging (Phase 1)

Uncommitted changes from IBKR market data client Phase 1 added 3 new keys to `realized_metadata`:
- `unpriceable_reason_counts: Dict[str, int]` — count of symbols by unpriceable reason
- `unpriceable_reasons: Dict[str, str]` — symbol → reason mapping
- `ibkr_pricing_coverage: Dict[str, Any]` — `{"total_symbols_priced_via_ibkr": int, "by_instrument_type": dict}`

**Action:** Added all 3 to `RealizedMetadata` dataclass fields, `to_dict()`, and `from_dict()`.

No other changes affect the result object plan — the instrument tagging work is upstream (transaction ingestion, position timeline, pricing routing) and doesn't change the output schema shape beyond these 3 keys. Line numbers in `realized_performance_analysis.py` shifted (~250 lines) — `realized_metadata` dict is now at line ~2445 (was ~2085). The implementor should use the actual code, not hardcoded line numbers. (2026-02-15)

**MED (1 — addressed):**
1. `_postfilter` leaks into summary helper inputs via unsanitized `to_dict()` — **Fixed:** summary branch now builds sanitized dict (strips `_postfilter`) before passing to `_categorize_performance_from_metrics()` / `_generate_key_insights_from_metrics()`

**LOW (2 — addressed):**
1. `run_realized_performance()` annotation/docstring not updated — **Fixed:** added annotation update to Step 5
2. `_run_realized_with_service()` return annotation stale — **Fixed:** added Step 4a with `Union` return type
