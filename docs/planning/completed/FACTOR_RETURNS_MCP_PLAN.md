# Plan: Add Lightweight `analysis_type="returns"` to `get_factor_analysis`

## Context

The factor intelligence `get_factor_analysis` tool has two modes: `"correlations"` (works well) and `"performance"` (needs 24+ months of monthly data for CAPM regression, fails on short windows). When Claude needs to answer "how have factors done over 3 months?", it has to manually fetch FMP prices and compute returns — the tool can't answer this directly.

**Goal**: Two changes in one:
1. Add `analysis_type="returns"` that computes simple price returns for factor ETFs over any time window (no minimum data requirement beyond 2 observations). Supports multiple trailing windows (1m, 3m, 6m, 1y) in a single call for momentum analysis.
2. Add `include` section filtering parameter (same pattern as `get_risk_analysis`) so Claude can request specific pieces (e.g., just rate sensitivity or just rankings) instead of getting the full 961K JSON blob.

## Changes (6 files)

### 1. `core/result_objects.py` — New `FactorReturnsResult` class (after `FactorPerformanceResult`, ~line 6593)

Follows the same pattern as `FactorCorrelationResult` and `FactorPerformanceResult`. **Keys `factors` dict by ticker** (consistent with `FactorPerformanceResult.per_factor`), with `label` as a field inside each entry:

```python
class FactorReturnsResult:
    """Structured result for lightweight factor returns snapshot."""

    def __init__(self, factors, industry_groups, rankings, by_category, windows, data_quality, performance, analysis_metadata):
        self.factors = factors or {}              # {ticker: {label, category, windows: {window: {total_return, ...}}}}
        self.industry_groups = industry_groups or {}  # {group_label: {members, windows: {window: {total_return, ...}}}}
        self.rankings = rankings or {}            # {window: [sorted list by return]}
        self.by_category = by_category or {}      # {category: {window: {avg_return, best, worst}}}
        self.windows = windows or []
        self.data_quality = data_quality or {}
        self.performance = performance or {}
        self.analysis_metadata = analysis_metadata or {}

    @classmethod
    def from_core_analysis(cls, core_output, ...) -> 'FactorReturnsResult': ...

    def to_api_response(self) -> Dict[str, Any]:
        # factors, industry_groups, rankings, by_category, windows, data_quality, performance, analysis_metadata, formatted_report

    def to_cli_report(self, top_n: int = 10) -> str:
        # Text table: per-window rankings showing top/bottom performers with category labels
```

### 2. `core/factor_intelligence.py` — New core function

Add `compute_factor_returns_snapshot()` after `compute_factor_performance_profiles` (line ~1340):

- **Input**: `returns_panel` (existing panel from `build_factor_returns_panel`), `windows` list (e.g., `["1m", "3m", "6m", "1y"]`), optional `categories` filter, `industry_granularity`
- **Computation**: For each window, slice the tail N months of the panel, compute `total_return = (1+r).prod() - 1` per factor. When N >= 3, also compute `annualized_return` and `volatility`.
- **Industry grouping**: Reuse `_build_industry_series_by_granularity()` for `granularity="group"` composites. The helper returns **label-keyed** composites (group names like "Defensive", "Sensitive") not tickers. These are placed in a **separate `industry_groups` dict** (not in `factors`), keeping the two namespaces clean:
  - `factors`: keyed by ticker (e.g., `"XLF"`) — individual ETFs only
  - `industry_groups`: keyed by group label (e.g., `"Defensive"`) — equal-weight composites from `_build_industry_series_by_granularity()`
  - Ungrouped industries (no `sector_group` mapping) are excluded from group composites and tracked in `data_quality.unlabeled_industries`. **Note**: this differs slightly from correlations mode, which emits both grouped and raw industry outputs simultaneously (`out_key="industry_groups"` + `out_key="industry"`). Returns mode only emits group composites when `industry_granularity="group"`, matching the simpler performance-mode pattern.
- **Output structure**: `{"factors": {ticker: {...}}, "industry_groups": {label: {...}}, "rankings": {window: [...]}, ...}`

Add `_parse_windows()` helper: converts window specs to month counts.

**Window parsing rules:**
- Valid tokens: `"1m"`, `"3m"`, `"6m"`, `"1y"`, `"2y"`, `"ytd"` (case-insensitive, normalized to lowercase)
- `"ytd"` computes months from Jan 1 of `end_date`'s year to `end_date`; minimum 1 month
- Invalid tokens: logged as warning, skipped, reported in `data_quality.invalid_windows`
- Duplicates: silently deduplicated (preserves first occurrence order)
- Empty after filtering: raises `ValueError("No valid windows specified")`
- Returns: `List[Tuple[str, int]]` — `[(window_label, month_count), ...]` ordered by input

### 3. `services/factor_intelligence_service.py` — New service method

Add `analyze_returns()` method on `FactorIntelligenceService`:

```python
def analyze_returns(
    self, *,
    windows: Optional[List[str]] = None,   # default ["1m", "3m", "6m", "1y"]
    end_date: Optional[str] = None,
    categories: Optional[List[str]] = None,
    industry_granularity: str = "group",
    factor_universe: Optional[Dict] = None,
    asset_class_filters: Optional[Dict] = None,
    top_n: int = 10,
) -> FactorReturnsResult:
```

Key logic:
- Parse windows → determine longest window in months
- **Compute start_date** = `end_date - longest_window - 2 month buffer` (not the default 2010 start; avoids fetching 15 years of data)
- Call `self._panel(start_date, end_date, ...)` (reuses existing panel + cache infra)
- Call `compute_factor_returns_snapshot(panel, windows, ...)`
- Wrap output in `FactorReturnsResult.from_core_analysis()`
- Cache result with TTL key

**No `start_date` param on `analyze_returns()`** — the start is auto-derived from the longest window. The MCP tool's existing `start_date` parameter is **explicitly ignored** for returns mode (see section 4 below).

### 4. `mcp_tools/factor_intelligence.py` — New dispatch branch + section filtering

Update `get_factor_analysis()`:
- Add `"returns"` to `analysis_type` Literal
- Add params: `windows: Optional[list[str]] = None`, `top_n: int = 10`, `include: Optional[list[str]] = None`, `include_macro_etf: bool = False`
- Pass `include_macro_etf` through to `service.analyze_correlations()` (it already accepts the param, just wasn't wired from MCP)
- Add `elif analysis_type == "returns":` branch calling `service.analyze_returns()`

**`start_date` handling for returns mode**: The MCP tool already exposes `start_date`. For returns mode, `start_date` is **ignored** (the window specs define the lookback). If `start_date` is provided with `analysis_type="returns"`, include `"note": "start_date is ignored for returns mode; use windows to specify lookback periods"` in the response. The `note` field is injected **before** section filtering runs (i.e., added to the full response dict before `_apply_section_filter()`), and `_apply_section_filter()` always preserves the `note` field alongside `status`. This ensures the note is never silently dropped by `include`.

**Section filtering** (applies to all analysis_types when `include` is provided):

Same pattern as `get_risk_analysis` — when `include` is specified, use full response as base and filter to selected sections. `status` always included. Invalid sections reported.

**`include` overrides `format`** — same as `get_risk_analysis`. When `include` is provided, section filtering is applied regardless of `format` setting. This is the simplest contract: `include` means "give me exactly these sections."

**Overlay extraction for correlations**: The correlation API response nests overlays under a top-level `overlays` dict (`{"overlays": {"rate_sensitivity": ..., "market_sensitivity": ..., "macro_composite_matrix": ...}}`). The section filtering must handle this nesting — overlay section names extract sub-keys from within `overlays`, not top-level keys:

```python
FACTOR_ANALYSIS_SECTIONS = {
    # Correlations sections
    "matrices": {"keys": ["matrices"]},
    "overlays": {"keys": ["overlays"]},                              # entire overlays dict
    "rate_sensitivity": {"nested": ("overlays", "rate_sensitivity")},  # extract from overlays
    "market_sensitivity": {"nested": ("overlays", "market_sensitivity")},
    "macro_composite": {"nested": ("overlays", "macro_composite_matrix")},
    "macro_etf": {"nested": ("overlays", "macro_etf_matrix")},  # requires include_macro_etf=True
    # Performance sections
    "per_factor": {"keys": ["per_factor"]},
    "composites": {"keys": ["composites"]},
    # Returns sections
    "rankings": {"keys": ["rankings"]},
    "by_category": {"keys": ["by_category"]},
    "factors": {"keys": ["factors"]},
    "industry_groups": {"keys": ["industry_groups"]},
    # Common sections
    "data_quality": {"keys": ["data_quality"]},
    "metadata": {"keys": ["analysis_metadata"]},
    "formatted_report": {"keys": ["formatted_report"]},
}
```

Filtering logic:
```python
def _apply_section_filter(response: dict, include: list[str]) -> dict:
    """Filter response to only requested sections."""
    filtered = {}
    invalid = []
    for section in include:
        spec = FACTOR_ANALYSIS_SECTIONS.get(section)
        if spec is None:
            invalid.append(section)
            continue
        if "keys" in spec:
            for k in spec["keys"]:
                if k in response:
                    filtered[k] = response[k]
        elif "nested" in spec:
            parent_key, child_key = spec["nested"]
            parent = response.get(parent_key, {})
            if child_key in parent:
                # Place nested value under its own key for easy access
                filtered.setdefault(parent_key, {})[child_key] = parent[child_key]
    filtered["status"] = "success"
    if "note" in response:
        filtered["note"] = response["note"]
    if invalid:
        filtered["invalid_sections"] = invalid
    return filtered
```

This handles the overlay nesting correctly: `include=["rate_sensitivity"]` extracts `response["overlays"]["rate_sensitivity"]` and returns it as `{"overlays": {"rate_sensitivity": ...}, "status": "success"}`.

**Compute-gated sections**: Some sections map to data that is only present when a compute flag is enabled (e.g., `macro_etf` requires `include_macro_etf=True`, which defaults to `False` but is now exposed as an MCP param). Similarly, `industry_groups` is only present when `industry_granularity="group"`. When `include` requests a section whose data wasn't computed, the section is simply absent from the result — this is **not** treated as invalid. The `invalid_sections` list only reports section names that don't exist in `FACTOR_ANALYSIS_SECTIONS` at all. This matches the risk tool behavior where requesting a section that has no data for the current portfolio simply returns nothing for that key.

**Summary format** for returns (designed for Claude consumption). **Uses all requested windows** (not hardcoded to `3m`):

```python
{
    "status": "success",
    "analysis_type": "returns",
    "windows": ["1m", "3m", "6m", "1y"],     # actual windows computed
    "top_performers": {                        # top_n per window
        "1m": [{ticker, label, category, total_return}, ...],
        "3m": [{ticker, label, category, total_return}, ...],
        ...
    },
    "bottom_performers": {                     # bottom top_n per window
        "1m": [{ticker, label, category, total_return}, ...],
        "3m": [{ticker, label, category, total_return}, ...],
        ...
    },
    "by_category": {                           # category summaries per window
        "industry": {"1m": {avg_return, best, worst}, "3m": ...},
        ...
    },
    "factors_analyzed": 95,
}
```

**Full format**: Complete `result.to_api_response()` output + status.
**Report format**: `result.to_cli_report()` text.

### 5. `mcp_server.py` — Update tool registration (line ~378)

- Add `"returns"` to `analysis_type` Literal
- Add `windows`, `top_n`, `include`, and `include_macro_etf` parameters
- Pass them through to `_get_factor_analysis()`
- Update docstring with returns, section filtering, and macro ETF examples

### 6. `settings.py` — Add returns defaults

Add `"returns"` section to `FACTOR_INTELLIGENCE_DEFAULTS` (after `"performance"` block, ~line 237):
```python
"returns": {
    "default_windows": ["1m", "3m", "6m", "1y"],
    "top_n": 10,
    "industry_granularity": "group",
},
```

## Implementation Sequence

1. `settings.py` — add defaults
2. `core/result_objects.py` — add `FactorReturnsResult` class
3. `core/factor_intelligence.py` — add `_parse_windows()` + `compute_factor_returns_snapshot()`
4. `services/factor_intelligence_service.py` — add `analyze_returns()` method, return `FactorReturnsResult`
5. `mcp_tools/factor_intelligence.py` — add returns dispatch + `_apply_section_filter()` + formatting
6. `mcp_server.py` — update tool registration
7. Test end-to-end via MCP

## Key Design Decisions

- **New `FactorReturnsResult` typed result class** in `core/result_objects.py` — follows the pattern of `FactorCorrelationResult` and `FactorPerformanceResult` for cohesive data outputs. Includes `to_api_response()`, `to_cli_report()`, and `from_core_analysis()` factory method. Uses `_convert_to_json_serializable()` helper (already exists in the file) for API serialization.
- **`factors` keyed by ticker, `industry_groups` keyed by label** — `factors` dict contains individual ETFs keyed by ticker (e.g., `"XLF"`, `"TLT"`), consistent with `FactorPerformanceResult.per_factor`. `industry_groups` is a separate dict keyed by group label (e.g., `"Defensive"`) containing equal-weight composites from `_build_industry_series_by_granularity()`. This separation avoids mixing ticker keys with label keys in the same dict.
- **No `start_date` param on returns mode** — auto-computed from longest window. Keeps it simple: "how have factors done in the last 3m/6m/1y?" If user passes `start_date` with returns mode, it's ignored with a note in the response.
- **`include` overrides `format`** — same contract as `get_risk_analysis`. When `include` is specified, section filtering is applied regardless of format. Keeps the behavior predictable.
- **Overlay nesting handled** — correlation overlays are nested under `response["overlays"]`. Section filtering uses a `nested` extraction path for `rate_sensitivity`, `market_sensitivity`, `macro_composite` to correctly pull from within the `overlays` dict, rather than treating them as top-level keys.
- **Post-response filtering for `include`** — section filtering happens after `to_api_response()`, not during compute. For correlations, the service's existing `sections` param can gate expensive compute (matrices, overlays), but `include` is an MCP-layer concern that filters the serialized output. Returns mode compute is lightweight (simple products over tail slices), so post-filtering is sufficient. We do NOT thread `include` down to the service/core layers.
- **Reuses existing data pipeline** — `_panel()` → `build_factor_returns_panel()` → FMP + parquet cache. No new FMP calls.
- **Reuses `_build_industry_series_by_granularity()`** — for group-level composites (Defensive, Sensitive, etc.). Output goes to `industry_groups` dict (separate from `factors`). Ungrouped industries are excluded at group granularity — count reported in `data_quality`. Note: correlations mode emits both grouped and raw industry outputs side-by-side; returns mode only emits group composites (matching the simpler performance-mode pattern).
- **Multiple windows in one call** — panel is fetched once using longest window's implied start date. Each shorter window just slices the tail.
- **Summary uses all windows** — top/bottom performers shown for every requested window, not hardcoded to any single window. Handles edge case where caller requests only `["1m"]`.
- **Window validation** — case-insensitive, deduplicated, invalid tokens skipped with warning. Empty result after filtering raises `ValueError`.

## Codex Review Resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | `include` mapping for correlation overlays is structurally wrong — overlays are nested under `overlays` key, not top-level | High | Changed `FACTOR_ANALYSIS_SECTIONS` to use `{"nested": (parent, child)}` extraction for overlay sub-keys. Added `_apply_section_filter()` helper that handles both top-level `keys` and `nested` paths. |
| 2 | `start_date` already exposed on MCP tool — returns mode ignores it but doesn't say so | High | Explicitly ignore `start_date` for returns mode. Include `"note"` in response when `start_date` is provided, explaining windows control the lookback. |
| 3 | `include` filters post-response only, misses service-layer `sections` for compute gating | Medium | Accepted: `include` is MCP-layer output filtering. For correlations, the existing `sections` param on `analyze_correlations()` already gates expensive compute — that's orthogonal to `include`. Returns compute is lightweight. Not worth coupling MCP section names to service internals. |
| 4 | `_build_industry_series_by_granularity("group")` drops ungrouped industries | Medium | Accepted: this is existing shared behavior across all three modes. Ungrouped count reported in `data_quality.unlabeled_industries`. Documented in plan. |
| 5 | `factors` keyed by label is fragile — existing pattern keys by ticker | Medium | Fixed: `factors` dict now keyed by ticker (e.g., `"XLF"`), with `label` as a field inside each entry. Consistent with `FactorPerformanceResult.per_factor`. |
| 6 | Summary format hardcoded to `3m` — breaks when caller requests only `["1m"]` | Medium | Fixed: summary includes top/bottom performers for **every requested window**, not a hardcoded single window. |
| 7 | Window parsing/validation behavior underspecified | Medium | Specified: case-insensitive, deduplicated, invalid tokens skipped with warning + reported in `data_quality.invalid_windows`, empty-after-filtering raises `ValueError`. `ytd` computes dynamically from Jan 1. |
| 8 | No test plan for include filtering or returns mode | Low | Added verification section covering returns windows, section filtering (including nested overlay extraction), invalid sections, and regression for existing modes. Unit tests deferred to implementation phase. |

**2nd-pass findings:**

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 2.1 | `_build_industry_series_by_granularity("group")` returns label-keyed composites, not ticker-keyed — contradicts ticker-keyed `factors` dict | High | Split into two dicts: `factors` (ticker-keyed, individual ETFs) and `industry_groups` (label-keyed, group composites). Added `industry_groups` to `FactorReturnsResult.__init__`, `to_api_response()`, and `FACTOR_ANALYSIS_SECTIONS`. |
| 2.2 | "Existing shared behavior" claim for ungrouped industries is inaccurate — correlations emits both grouped + raw, performance doesn't use industry granularity in core | Medium | Corrected: documented that returns mode emits group composites only (matching simpler performance pattern), noting correlations mode's dual-output is different. |
| 2.3 | `note` field can be dropped by `include` section filtering | Medium | `_apply_section_filter()` now always preserves `note` alongside `status`. Note is injected before filtering runs. |
| 2.4 | Section map misses `macro_etf_matrix` | Low | Now mapped: added `"macro_etf": {"nested": ("overlays", "macro_etf_matrix")}` to `FACTOR_ANALYSIS_SECTIONS`. Also exposed `include_macro_etf: bool = False` as a new MCP param (service already accepts it, just wasn't wired through). |

## Verification

**Returns mode:**
1. `get_factor_analysis(analysis_type="returns", windows=["3m"])` — 3-month returns for all ~95 factor ETFs
2. `get_factor_analysis(analysis_type="returns")` — default windows (1m, 3m, 6m, 1y) in one call
3. `get_factor_analysis(analysis_type="returns", categories=["industry"], windows=["1m", "3m"])` — just industry ETFs
4. `get_factor_analysis(analysis_type="returns", windows=["1m"])` — should work with just 1 month of data
5. `get_factor_analysis(analysis_type="returns", start_date="2024-01-01")` — should ignore start_date, include note in response

**Section filtering:**
6. `get_factor_analysis(analysis_type="correlations", include=["matrices"])` — just correlation matrices, no overlays
7. `get_factor_analysis(analysis_type="correlations", include=["rate_sensitivity"])` — extracts from nested `overlays.rate_sensitivity`
8. `get_factor_analysis(analysis_type="correlations", include=["overlays"])` — entire overlays dict
9. `get_factor_analysis(analysis_type="returns", include=["rankings"])` — just the ranked lists
10. `get_factor_analysis(analysis_type="returns", include=["rankings", "bogus"])` — rankings + `invalid_sections: ["bogus"]`
11. `get_factor_analysis(analysis_type="performance", include=["per_factor"])` — just per-factor metrics
12. `get_factor_analysis(analysis_type="correlations", include=["macro_etf"], include_macro_etf=True)` — macro ETF matrix from nested overlays
13. `get_factor_analysis(analysis_type="correlations", include=["macro_etf"])` — absent (include_macro_etf defaults False), not invalid

**Regression:**
14. `get_factor_analysis(analysis_type="correlations")` — existing mode unchanged
15. `get_factor_analysis(analysis_type="performance")` — existing mode unchanged
