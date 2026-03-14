# Plan: Agent-Optimized Risk Analysis Output

_Created: 2026-02-18_
_Last updated: 2026-02-18 (v4.1 — Codex follow-up review resolutions)_
_Status: **COMPLETED** — implemented and verified via MCP live test_

## Context

`get_risk_analysis(format="full")` returns ~67K characters of JSON — too large and poorly structured for AI agent consumption. The summary format is too sparse (7 fields). There's no middle ground designed for how an agent actually uses risk data.

Two goals:
1. **Save full data to file** — like edgar-financials `output="file"` pattern. Keep full detail accessible without blowing up context. The agent gets a briefing inline, with the full reference material on disk to grep/search when it needs to dig deeper.
2. **Decision-oriented summary** — structure the returned summary around agent reasoning (what needs attention, where is risk, is anything out of bounds), not raw metrics.

Key principle: **design the agent output first** (what does the agent need?), then **align the data object** so those buckets have clean accessors. The agent format becomes a natural composition of getter methods, not a dict-construction exercise in the MCP layer.

## Current State

### Output formats

| Format | Size | Problem |
|--------|------|---------|
| `summary` | ~1-2 KB | Too sparse — missing composition, compliance, industry |
| `full` | ~67 KB | Too large — matrices, formatted report, redundant fields |
| `report` | ~50-500 KB | Human-only text, not machine-parseable |
| `include=[sections]` | ~10-150 KB | Useful but still raw data dumps, not insight-oriented |

### What's bloating `full`:
- Covariance/correlation matrices: ~200-500 KB (already excluded by default via `include_matrices=False`)
- `formatted_report` string: ~50-500 KB (human-only, included in every full response)
- `stock_betas` full DataFrame: ~50-200 KB
- `asset_vol_summary` full DataFrame: ~50-100 KB
- Redundant industry data (nested raw + flattened versions)
- Redundant compliance data (raw CLI-aligned + normalized versions)

### Existing getter methods on `RiskAnalysisResult`

| Method | Returns | Gap for agent use |
|--------|---------|-------------------|
| `get_summary()` | 7 fields (vol, herfindahl, factor/idio pct, top risk contributors, factor betas) | Missing total_value, exposure, leverage, position_count. Also contains per-position data (top_risk_contributors, factor_betas) that belongs in dedicated buckets. |
| `get_factor_exposures()` | `{factor: beta}` dict | Good as-is |
| `get_top_risk_contributors(n)` | `{ticker: contribution}` dict | Only returns contribution float — missing weight, beta, vol alongside |
| `get_variance_breakdown()` | factor_pct, idiosyncratic_pct, portfolio_variance | Good as-is |
| No compliance accessor | — | Raw `risk_checks`/`beta_checks` with CLI casing |
| No industry accessor | — | Raw nested `industry_variance` dict |

## Proposed Design

### Architecture: Three Layers

```
Layer 1: Data Accessors (RiskAnalysisResult getter methods)
    "Here's what the data says" — clean, typed, per-bucket

Layer 2: Analysis Rules (flags/warnings module)
    "Here's what that means" — interpretive logic, thresholds, severity

Layer 3: Agent Format (MCP tool composition)
    Composes Layer 1 + Layer 2 into agent response + file output
```

The key separation: **getters are data, flags are logic.** They serve different purposes and change for different reasons. A new flag rule shouldn't require touching the data object. A new data field shouldn't require updating flag logic.

### Layer 1: Enhanced getter methods on `RiskAnalysisResult`

Each agent bucket maps to a clean getter method on the data object. These are general-purpose accessors — useful for agent format, monitor enrichment, API consumers, anything.

#### Refactor `get_summary()` → portfolio-level snapshot only

Remove per-position data (top_risk_contributors, factor_betas) from the summary — those belong in their dedicated accessors. Summary becomes purely portfolio-level:

```python
def get_summary(self) -> Dict[str, Any]:
    """Portfolio-level snapshot: size, exposure, risk, concentration."""
    return {
        "total_value": self.total_value,
        "net_exposure": self.net_exposure,
        "gross_exposure": self.gross_exposure,
        "leverage": self.leverage,
        "position_count": (self.analysis_metadata or {}).get("active_positions") or (len(self.risk_contributions) if self.risk_contributions is not None else 0),
        "volatility_annual": self.volatility_annual,
        "volatility_monthly": self.volatility_monthly,
        "herfindahl": self.herfindahl,
        "factor_variance_pct": self.variance_decomposition.get('factor_pct', 0),
        "idiosyncratic_variance_pct": self.variance_decomposition.get('idiosyncratic_pct', 0),
    }
```

Notes:
- Removes `top_risk_contributors` and `factor_betas` — accessed via `get_top_risk_contributors()` and `get_factor_exposures()` respectively.
- `position_count` sourced from `analysis_metadata["active_positions"]` (stable), with `len(risk_contributions)` as fallback.
- **Breaking change** to `get_summary()`. The `format="summary"` MCP path currently calls this — will need updating (see Compatibility section).

#### Evolve `get_top_risk_contributors(n)` → enriched risk attribution

Change in place. Return enriched per-position dicts with weight, beta, vol alongside risk contribution:

```python
def get_top_risk_contributors(self, n: int = 5) -> List[Dict[str, Any]]:
    """Top N risk contributors with weight, beta, volatility context."""
    top_tickers = self.euler_variance_pct.nlargest(n).index.tolist()
    result = []
    for ticker in top_tickers:
        entry = {
            "ticker": ticker,
            "weight_pct": round(self._get_weight(ticker) * 100, 2),
            "risk_pct": round(float(self.euler_variance_pct.get(ticker, 0)) * 100, 2),
            "beta": self._safe_float(self.stock_betas, ticker, "market"),
            "volatility": self._safe_float(self.asset_vol_summary, ticker, "Vol A"),
        }
        result.append(entry)
    return result
```

Breaking change: return type changes from `Dict[str, float]` to `List[Dict]`. Callers to verify:
- `get_summary()` — uses `self.risk_contributions.nlargest(5).to_dict()` directly, not this method. Safe.
- `get_monitor_with_risk()` — accesses raw DataFrames directly. Safe.
- Any external callers — grep before implementing.

#### New: `get_compliance_summary()` → compliance bucket

Unified compliance view from the raw checks:

```python
def get_compliance_summary(self) -> Dict[str, Any]:
    """Compliance status: violations, beta breaches, overall pass/fail."""
    violations = []
    for check in (self.risk_checks or []):
        if not check.get("Pass", True):
            violations.append({
                "metric": check.get("Metric"),
                "actual": check.get("Actual"),
                "limit": check.get("Limit"),
            })

    beta_breaches = []
    for check in (self.beta_checks or []):
        if not check.get("pass", True):
            beta_breaches.append({
                "factor": check.get("factor"),
                "portfolio_beta": check.get("portfolio_beta"),
                "max_allowed_beta": check.get("max_allowed_beta"),
            })

    return {
        "is_compliant": len(violations) == 0 and len(beta_breaches) == 0,
        "violation_count": len(violations) + len(beta_breaches),
        "violations": violations,
        "beta_breaches": beta_breaches,
    }
```

#### New: `get_industry_concentration()` → industry bucket

Clean accessor for industry weight/variance data. Sorted by **positive contribution** (not absolute value) to avoid surfacing hedges as concentration risk:

```python
def get_industry_concentration(self, n: int = 5) -> List[Dict[str, Any]]:
    """Top N industries by portfolio variance contribution (positive only — hedges excluded)."""
    pct = self.industry_variance.get("percent_of_portfolio", {})
    # Filter to positive contributors only — negative variance = hedge, not concentration
    positive = [(ind, val) for ind, val in pct.items() if val > 0]
    sorted_industries = sorted(positive, key=lambda x: x[1], reverse=True)[:n]
    return [
        {"industry": industry, "variance_pct": round(val * 100, 2)}
        for industry, val in sorted_industries
    ]
```

#### New: helper methods

```python
def _get_weight(self, ticker: str) -> float:
    """Extract portfolio weight for a ticker from allocations DataFrame."""
    if self.allocations is not None and ticker in self.allocations.index:
        return float(self.allocations.loc[ticker, "Portfolio Weight"])
    return 0.0

def _safe_float(self, df: pd.DataFrame, ticker: str, col: str) -> Optional[float]:
    """Safely extract a float from a DataFrame, returning None on missing/NaN/non-numeric."""
    try:
        if df is not None and ticker in df.index and col in df.columns:
            val = df.loc[ticker, col]
            if val is not None and pd.notna(val):
                return round(float(val), 4)
    except (TypeError, ValueError, KeyError):
        pass
    return None

@staticmethod
def _safe_num(val, default=0):
    """Coerce value to float, returning default for None/NaN/non-numeric."""
    if val is None:
        return default
    try:
        f = float(val)
        return default if (f != f) else f  # NaN check: NaN != NaN
    except (TypeError, ValueError):
        return default
```

#### Already good as-is:
- `get_factor_exposures()` → returns `{factor: beta}` dict
- `get_variance_breakdown()` → returns factor_pct, idiosyncratic_pct, portfolio_variance

### Layer 2: Analysis Rules (flags/warnings)

Flags are the **interpretive logic layer** — separate from data accessors. They consume getter outputs and apply thresholds/rules to generate actionable warnings.

This logic lives in `mcp_tools/risk.py` (or a dedicated `mcp_tools/risk_flags.py` if it grows). It does NOT live on `RiskAnalysisResult` — the data object shouldn't contain analysis opinions.

```python
def _generate_flags(result: RiskAnalysisResult) -> List[Dict[str, Any]]:
    """
    Generate actionable flags from risk analysis data.

    Each flag is a structured dict with type, severity, human-readable message,
    and the underlying data values so the agent can reason about them.

    Severity levels:
    - "error": Compliance violations, hard breaches — requires attention
    - "warning": Concentration risk, outsized positions — worth discussing
    - "info": Informational observations — context for the agent
    """
    flags = []

    # --- Compliance flags (severity: error) ---
    compliance = result.get_compliance_summary()
    _sn = RiskAnalysisResult._safe_num  # shorthand

    for v in compliance["violations"]:
        actual = _sn(v.get("actual"))
        limit = _sn(v.get("limit"))
        flags.append({
            "type": "compliance_violation",
            "severity": "error",
            "message": f"VIOLATION: {v['metric']} at {actual:.2%} exceeds limit {limit:.2%}",
            "metric": v["metric"],
            "actual": actual,
            "limit": limit,
        })
    for b in compliance["beta_breaches"]:
        beta = _sn(b.get("portfolio_beta"))
        max_beta = _sn(b.get("max_allowed_beta"))
        flags.append({
            "type": "beta_breach",
            "severity": "error",
            "message": f"Beta breach: {b['factor']} at {beta:.2f} vs limit {max_beta:.2f}",
            "factor": b["factor"],
            "portfolio_beta": beta,
            "max_allowed_beta": max_beta,
        })

    # --- Concentration flags (severity: warning) ---

    # Outsized risk concentration: risk_pct > 3× weight_pct, but only for meaningful positions (weight > 2%)
    for pos in result.get_top_risk_contributors(10):
        if pos["weight_pct"] > 2.0 and pos["risk_pct"] > 3 * pos["weight_pct"]:
            flags.append({
                "type": "risk_weight_mismatch",
                "severity": "warning",
                "message": f"{pos['ticker']} contributes {pos['risk_pct']:.1f}% of risk at only {pos['weight_pct']:.1f}% weight",
                "ticker": pos["ticker"],
                "risk_pct": pos["risk_pct"],
                "weight_pct": pos["weight_pct"],
            })

    # Portfolio concentration (HHI)
    summary = result.get_summary()
    hhi = _sn(summary.get("herfindahl"))
    if hhi > 0.25:
        flags.append({
            "type": "hhi_concentrated",
            "severity": "warning",
            "message": f"Portfolio is concentrated (HHI: {hhi:.3f})",
            "herfindahl": hhi,
        })

    # --- Informational flags (severity: info) ---

    # Top 5 risk dominance
    top5 = result.get_top_risk_contributors(5)
    top5_total = sum(p["risk_pct"] for p in top5)
    if top5_total > 70:
        flags.append({
            "type": "top5_dominance",
            "severity": "info",
            "message": f"Top 5 positions account for {top5_total:.0f}% of portfolio risk",
            "top5_risk_pct": round(top5_total, 1),
        })

    return flags
```

Key design choices:
- **Flags are ordered by severity** (error → warning → info) so the agent sees the most important things first
- **Minimum weight floor** (2%) for risk/weight mismatch — avoids noise from tiny positions
- **Each flag carries its data** — the agent can use the values, not just the message string
- **Safe coercion** on all numeric formatting via `_safe_num()` — handles None, NaN, and non-numeric types
- **Thresholds are hardcoded constants** for now. If we add more rules or need configurability, extract to a `FLAG_RULES` config.

### Layer 3: Agent format in MCP layer

With clean getters and separate flag logic, the agent format is pure composition:

```python
def _build_agent_response(result: RiskAnalysisResult, file_path: str = None) -> Dict:
    return {
        "status": "success",
        "format": "agent",
        "snapshot": result.get_summary(),
        "flags": _generate_flags(result),
        "compliance": result.get_compliance_summary(),
        "risk_attribution": result.get_top_risk_contributors(5),
        "factor_exposures": result.get_factor_exposures(),
        "industry_concentration": result.get_industry_concentration(5),
        "variance_decomposition": result.get_variance_breakdown(),
        "file_path": file_path,
    }
```

### File output (`output="file"`)

New parameter on `get_risk_analysis()`:

- **`output="inline"` (default)**: Current behavior — response returned inline
- **`output="file"`**: Full JSON saved to disk, returns agent summary + `file_path`

Works with any format. When `output="file"`:
1. Run risk analysis as normal
2. Save full `to_api_response()` output to disk
3. Return whatever format was requested (agent, summary, full) with `file_path` attached

### File save details

- **Location**: `logs/risk_analysis/` directory (already gitignored)
- **Filename**: `risk_analysis_{YYYYMMDD}_{HHMMSS}.json`
- **Contents**: Full `to_api_response()` output (same as `format="full"`)
- **Path**: Absolute path (agent needs to read it directly)
- **Cleanup**: Optional TTL-based cleanup (e.g., keep last 7 days)

## Output hierarchy

Three tiers — all reading from the same underlying `RiskAnalysisResult` fields:

| Tier | Method/Format | Size | Use case |
|------|--------------|------|----------|
| Full dump | `to_api_response()` / `format="full"` | ~67 KB | File output, deep dives, programmatic analysis |
| CLI report | `to_cli_report()` / `format="report"` | ~50-500 KB | Human reading, LLM review/report generation |
| Summary | `get_summary()` / `format="summary"` | ~1-2 KB | Quick flat portfolio snapshot |
| Agent buckets | Getter methods / `format="agent"` | ~3-5 KB | Agent reasoning, decision-making, flagging |

No data duplication across agent buckets — each bucket owns its data:
- `snapshot` → portfolio-level only (no per-position data)
- `risk_attribution` → per-position risk data (the only place)
- `factor_exposures` → factor betas (the only place)
- `compliance` → violation data (the only place)
- `industry_concentration` → industry data (the only place)
- `variance_decomposition` → factor vs idiosyncratic split (the only place)
- `flags` → interpretive layer (references data from other buckets but doesn't duplicate it)

## Agent format example output

```json
{
  "status": "success",
  "format": "agent",

  "snapshot": {
    "total_value": 161530,
    "net_exposure": 161530,
    "gross_exposure": 161530,
    "leverage": 1.0,
    "position_count": 24,
    "volatility_annual": 0.0937,
    "volatility_monthly": 0.0270,
    "herfindahl": 0.290,
    "factor_variance_pct": 0.72,
    "idiosyncratic_variance_pct": 0.28
  },

  "flags": [
    {
      "type": "risk_weight_mismatch",
      "severity": "warning",
      "message": "SLV contributes 20.5% of risk at only 4.3% weight",
      "ticker": "SLV",
      "risk_pct": 20.5,
      "weight_pct": 4.3
    },
    {
      "type": "top5_dominance",
      "severity": "info",
      "message": "Top 5 positions account for 75% of portfolio risk",
      "top5_risk_pct": 75.0
    }
  ],

  "compliance": {
    "is_compliant": true,
    "violation_count": 0,
    "violations": [],
    "beta_breaches": []
  },

  "risk_attribution": [
    {"ticker": "SLV", "weight_pct": 4.3, "risk_pct": 20.5, "beta": 0.65, "volatility": 0.645},
    {"ticker": "STWD", "weight_pct": 12.0, "risk_pct": 16.5, "beta": 1.56, "volatility": 0.113},
    {"ticker": "DSU", "weight_pct": 28.0, "risk_pct": 14.7, "beta": 0.65, "volatility": 0.047},
    {"ticker": "CBL", "weight_pct": 4.2, "risk_pct": 12.5, "beta": 1.50, "volatility": 0.340},
    {"ticker": "MSCI", "weight_pct": 11.3, "risk_pct": 10.4, "beta": 1.08, "volatility": 0.123}
  ],

  "factor_exposures": {
    "market": 0.87,
    "momentum": 0.12,
    "value": -0.05,
    "interest_rate": 0.34
  },

  "industry_concentration": [
    {"industry": "Real Estate", "variance_pct": 22.3},
    {"industry": "Technology", "variance_pct": 15.1},
    {"industry": "Energy", "variance_pct": 8.6}
  ],

  "variance_decomposition": {
    "factor_pct": 0.72,
    "idiosyncratic_pct": 0.28,
    "portfolio_variance": 0.00073
  },

  "file_path": "/Users/henrychien/Documents/Jupyter/risk_module/logs/risk_analysis/risk_analysis_20260218_143000.json"
}
```

### What each section answers for the agent:

| Section | Agent question |
|---------|---------------|
| `snapshot` | "What am I looking at? How big, how risky?" |
| `flags` | "What should I flag to the user right now?" |
| `compliance` | "Is anything out of bounds?" |
| `risk_attribution` | "Where is the risk concentrated?" |
| `factor_exposures` | "What systematic risks am I exposed to?" |
| `industry_concentration` | "Am I diversified?" |
| `variance_decomposition` | "Is risk factor-driven or stock-specific?" |
| `file_path` | "Where can I dig deeper if needed?" |

## Files to Modify

### 1. `core/result_objects.py` — Enhance/add getter methods

**Refactor `get_summary()`:**
- Portfolio-level only: total_value, exposure, leverage, position_count, vol, herfindahl, variance split
- Remove `top_risk_contributors` and `factor_betas` (now in dedicated accessors)
- `position_count` from `analysis_metadata["active_positions"]` with `len(risk_contributions)` fallback
- **Breaking change** — verify callers (especially `format="summary"` MCP path)

**Evolve `get_top_risk_contributors(n)` in place:**
- Return `List[Dict]` with ticker, weight_pct, risk_pct, beta, volatility
- Use `_safe_float()` for null/NaN-safe DataFrame access
- **Breaking change** — return type changes from `Dict[str, float]` to `List[Dict]`
- Grep for callers before implementing

**New `get_compliance_summary()`:**
- Unified compliance view from raw `risk_checks` + `beta_checks`
- Returns `{is_compliant, violation_count, violations, beta_breaches}`

**New `get_industry_concentration(n)`:**
- Top N industries by variance contribution from `industry_variance`
- Sorted by positive contribution (not abs) — hedges are not concentration risk
- Returns `[{industry, variance_pct}]`

**New helpers:**
- `_get_weight(ticker)` — extract weight from `allocations` DataFrame
- `_safe_float(df, ticker, col)` — null/NaN-safe DataFrame value extraction

### 2. `mcp_tools/risk.py` — Add `format="agent"`, `output` parameter, and flags logic

**`_build_agent_response(result, file_path)`:**
- Composes agent format by calling getter methods + flags
- Thin — just orchestration, no data extraction logic

**`_generate_flags(result)`:**
- Separate interpretive layer — consumes getter outputs, applies rules/thresholds
- Each flag: `{type, severity, message, ...contextual_data}`
- Ordered by severity (error → warning → info)
- Minimum weight floor (2%) for risk/weight mismatch flags
- Safe coercion via `_safe_num()` on all numeric formatting to guard against None/NaN/non-numeric

**File save logic:**
- When `output="file"`: save `to_api_response()` to `logs/risk_analysis/`
- Pass `file_path` path to response builder

**Update `format="summary"` path:**
- Currently calls `result.get_summary()` directly and returns its dict
- After refactor, compose a backward-compatible flat dict:
  ```python
  summary = result.get_summary()  # new portfolio-level snapshot
  summary["status"] = "success"  # preserve MCP response contract
  summary["herfindahl_index"] = summary.pop("herfindahl")  # preserve old key name
  # Use raw risk_contributions (same source as old get_summary) to preserve exact values
  summary["top_risk_contributors"] = result.risk_contributions.nlargest(5).to_dict()
  summary["factor_betas"] = result.get_factor_exposures()
  return summary
  ```
- Uses `result.risk_contributions.nlargest(5).to_dict()` directly (same as old `get_summary()`) to preserve exact values — not reconstructed from the enriched `get_top_risk_contributors()` which uses euler_variance_pct and rounding.
- This preserves the old field names, shape, and exact values while adding new portfolio-level fields (total_value, exposure, leverage, position_count). Strict superset of old output.

### 3. `mcp_server.py` — Expose new parameters

- Add `format="agent"` as valid option
- Add `output: str = "inline"` parameter
- Pass through to `get_risk_analysis()`

### 4. `mcp_tools/risk.py` tool schema — Update

- Add `"agent"` to format enum
- Add `output` parameter with `"inline"` / `"file"` enum
- Note: verify where schema is defined — may be in `mcp_server.py` registration rather than a `TOOL_METADATA` dict

## Compatibility

- `to_api_response()` unchanged — still the full dump
- `to_cli_report()` unchanged — still the formatted text
- `get_summary()` — **breaking change**: removes `top_risk_contributors` and `factor_betas`. Now portfolio-level only. `format="summary"` MCP path updated to compose equivalent output.
- `get_top_risk_contributors()` — **breaking change**: return type changes from `Dict[str, float]` to `List[Dict]`. Grep for callers.
- `format="summary"` — **stays as its own format** (enhanced flat snapshot). NOT aliased to agent. Different structure, different purpose.
- `format="agent"` — purely additive new format (nested buckets with flags)
- `output="file"` works with any format

## Decisions Made

1. **`format="agent"` and `output` are independent.** Agent format is useful inline. File save is useful with any format. They compose.
2. **No data duplication across buckets.** Snapshot is portfolio-level only. Per-position data lives only in risk_attribution. Factor betas only in factor_exposures.
3. **Flags are a separate interpretive layer**, not a data accessor. They live in the MCP tool layer (or dedicated module), not on the data object. Data object says "here's what is." Flags say "here's what that means."
4. **Evolve methods directly** rather than adding parallel methods. Less API surface. This is an internal data object, not a public API — breaking callers is acceptable after grep verification.
5. **Minimum weight floor (2%) for risk/weight mismatch flags.** Avoids noise from tiny positions where 3× is meaningless.
6. **Thresholds are hardcoded constants** for now. Extract to config if more rules are added.
7. **`file_path` uses absolute path.** Agent reads it directly.
8. **`output="file"` scoped to risk analysis only** for now. Can extend to other tools later.
9. **`format="summary"` and `format="agent"` are distinct formats.** Summary is a flat portfolio snapshot (~1-2KB, "give me the numbers quick"). Agent is nested decision-oriented buckets with flags (~3-5KB, "give me the analysis"). Different response shapes, different use cases.
10. **Industry concentration sorted by positive contribution**, not absolute value. Hedges (negative variance contribution) are not concentration risk.
11. **Safe coercion via `_safe_num()` and `_safe_float()`.** All numeric formatting uses these helpers, not `or 0` (which misses NaN). `_safe_num` uses `NaN != NaN` check. `_safe_float` catches TypeError/ValueError/KeyError.
12. **`position_count` sourced from `analysis_metadata["active_positions"]`** (stable count from analysis setup), with `len(risk_contributions)` as fallback.
13. **File output: simple write for v1.** Atomic writes / collision-safe filenames are over-engineering for a local-only file written by a single process. Can harden later if needed.
14. **`format="summary"` backward-compatible.** Reconstructs old field names (`herfindahl_index`, `top_risk_contributors`, `factor_betas`) by composing from new getters. Strict superset of old output.
15. **Standardized on `file_path`** (not `details_file`) for consistency with existing tool conventions.
16. **Future enhancement (not v1): "what changed" delta flags.** File output pattern enables diffing against previous runs.

## Codex Review Notes

### v3 → v4 resolutions

| # | Finding | Resolution |
|---|---------|-----------|
| 1 | `format="summary"` alias to agent is a hard contract break (nested vs flat) | **Resolved**: Keep them separate. Summary stays flat, agent is nested. |
| 2 | In-place change to `get_top_risk_contributors()` is risky | **Accepted**: Internal data object, not public API. Grep callers first. |
| 3 | File output missing atomic write | **Accepted risk**: Local-only single-process file. Simple write for v1. |
| 4 | Flag formatting can throw on null/NaN | **Fixed**: `_safe_num()` + `_safe_float()` helpers. |
| 5 | Industry abs-sorting surfaces hedges as concentration | **Fixed**: Filter to positive-only before sorting. |
| 6 | `position_count` from `risk_contributions` may diverge | **Fixed**: Source from `analysis_metadata["active_positions"]` with fallback. |
| 7 | `TOOL_METADATA` reference doesn't exist | **Noted**: Schema lives in function signatures (`mcp_server.py`), not a dict. |
| 8 | `include_matrices` not exposed in MCP signature | **Out of scope**: Separate concern. |
| 9 | Test coverage gap | **Resolved**: Concrete test targets specified below. |

### v4 → v4.1 resolutions (follow-up review)

| # | Finding | Resolution |
|---|---------|-----------|
| 1 | `format="summary"` contract still ambiguous (field renames, missing fields) | **Fixed**: Explicit backward-compatible composition with `herfindahl_index` key preserved and old fields reconstructed. Strict superset of old output. |
| 2 | Industry concentration can still include hedges (sorted but not filtered) | **Fixed**: Filter to positive-only before sorting. |
| 3 | `or 0` coercion doesn't catch NaN | **Fixed**: Replaced with `_safe_num()` static method (NaN != NaN check). |
| 4 | `file_path` vs `details_file` naming inconsistency | **Fixed**: Standardized on `file_path` throughout. |
| 5 | Test resolution non-actionable | **Fixed**: Concrete test cases below. |

## Test Plan

### `core/result_objects.py` getter tests
- `test_get_summary_portfolio_level_only` — verify no per-position data, all portfolio fields present
- `test_get_top_risk_contributors_enriched` — verify List[Dict] shape with ticker, weight_pct, risk_pct, beta, volatility
- `test_get_top_risk_contributors_missing_data` — verify None for tickers missing from stock_betas/asset_vol_summary
- `test_get_compliance_summary_clean` — verify is_compliant=True when no violations
- `test_get_compliance_summary_violations` — verify violations and beta_breaches populated correctly
- `test_get_industry_concentration_positive_only` — verify negative contributors excluded
- `test_safe_float_nan_handling` — verify None returned for NaN, missing ticker, missing column
- `test_safe_num_edge_cases` — verify NaN, None, non-numeric all return default

### `mcp_tools/risk.py` agent format tests
- `test_agent_format_structure` — verify all top-level keys present (snapshot, flags, compliance, risk_attribution, factor_exposures, industry_concentration, variance_decomposition, file_path)
- `test_flags_severity_ordering` — verify errors before warnings before info
- `test_flags_weight_floor` — verify positions below 2% weight don't trigger risk_weight_mismatch
- `test_flags_safe_on_empty_result` — verify no crash on minimal/empty RiskAnalysisResult
- `test_summary_format_backward_compatible` — verify herfindahl_index key, top_risk_contributors, factor_betas present in summary output
- `test_file_output_creates_file` — verify file written to logs/risk_analysis/ with correct content
- `test_file_output_returns_file_path` — verify file_path in response points to valid file
