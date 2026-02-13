# MCP Section Filtering: `include` parameter for `get_risk_analysis`

**Status: ✅ COMPLETE** — Implemented and verified with real data + MCP end-to-end tests.

## Overview

Add an optional `include` parameter to `get_risk_analysis` so the agent can request specific sections from the full response instead of all 39 keys. Reduces LLM context window usage and lets the agent ask targeted questions.

## Design

- `include: Optional[list[str]]` — list of section names to return
- If `include` is not `None`, automatically uses "full" format as the base (no need to also set `format="full"`)
- `include=None` (default): behavior unchanged — respects `format` as before
- `include=[]` (empty list): returns only `status` key (explicit "give me nothing")
- `status` key is always preserved regardless of filtering
- Unrecognized section names reported via `invalid_sections` key in response (helps agent self-correct typos)
- Only applies to `get_risk_analysis` (not `get_risk_score` — its full response is only ~10 keys)

## Section mapping

Verified against actual `RiskAnalysisResult.to_api_response()` at `core/result_objects.py:1960-2011` (39 keys total):

| Section | Keys (from `to_api_response()`) |
|---------|------|
| `composition` | portfolio_weights, dollar_exposure, target_allocations, total_value, net_exposure, gross_exposure, leverage |
| `risk_metrics` | volatility_annual, volatility_monthly, herfindahl, risk_contributions, euler_variance_pct |
| `factor_analysis` | portfolio_factor_betas, stock_betas, effective_duration, variance_decomposition |
| `variance` | factor_variance_absolute, factor_variance_percentage, top_stock_variance_euler, asset_vol_summary, factor_vols, weighted_factor_var |
| `industry` | industry_group_betas, industry_variance_absolute, industry_variance_percentage, industry_variance |
| `matrices` | covariance_matrix, correlation_matrix |
| `compliance` | risk_checks, beta_checks, risk_limit_violations_summary, beta_exposure_checks_table, max_betas, max_betas_by_proxy |
| `historical` | portfolio_returns, historical_analysis |
| `metadata` | analysis_metadata, asset_allocation, formatted_report |

Changes from the original draft plan (in completed RISK_MCP_PLAN):
- Renamed `factor_betas` → `factor_analysis` (now includes `variance_decomposition` which is closely related)
- Moved `variance_decomposition` from `variance` → `factor_analysis` (it's the factor vs idiosyncratic split, not raw variance data)
- Added missing keys: `asset_vol_summary`, `factor_vols`, `weighted_factor_var` → `variance`
- Added missing key: `formatted_report` → `metadata`

## Files modified

| File | Change | Status |
|------|--------|--------|
| `mcp_tools/risk.py` | Add `RISK_ANALYSIS_SECTIONS` dict, add `include` param to `get_risk_analysis()`, add filtering logic | ✅ |
| `mcp_server.py` | Add `include` param + `Optional` import to `get_risk_analysis` tool registration wrapper | ✅ |

## Implementation

### 1. `mcp_tools/risk.py` — Add section dict + filtering ✅

Add at module level:
```python
RISK_ANALYSIS_SECTIONS = {
    "composition": ["portfolio_weights", "dollar_exposure", "target_allocations", "total_value", "net_exposure", "gross_exposure", "leverage"],
    "risk_metrics": ["volatility_annual", "volatility_monthly", "herfindahl", "risk_contributions", "euler_variance_pct"],
    "factor_analysis": ["portfolio_factor_betas", "stock_betas", "effective_duration", "variance_decomposition"],
    "variance": ["factor_variance_absolute", "factor_variance_percentage", "top_stock_variance_euler", "asset_vol_summary", "factor_vols", "weighted_factor_var"],
    "industry": ["industry_group_betas", "industry_variance_absolute", "industry_variance_percentage", "industry_variance"],
    "matrices": ["covariance_matrix", "correlation_matrix"],
    "compliance": ["risk_checks", "beta_checks", "risk_limit_violations_summary", "beta_exposure_checks_table", "max_betas", "max_betas_by_proxy"],
    "historical": ["portfolio_returns", "historical_analysis"],
    "metadata": ["analysis_metadata", "asset_allocation", "formatted_report"],
}
```

Update `get_risk_analysis` signature (use `list[str]` — no `List` import needed):
```python
def get_risk_analysis(
    user_email: Optional[str] = None,
    portfolio_name: str = "CURRENT_PORTFOLIO",
    format: Literal["full", "summary", "report"] = "summary",
    include: Optional[list[str]] = None,  # section names to filter full response
    use_cache: bool = True
) -> dict:
```

Update format logic — if `include` is provided, override format to "full" and filter.

Note on `status`: `to_api_response()` does not include `status` — it's added inside
`get_risk_analysis()` after formatting. So filtering cannot mask error states; errors are
caught by the outer `try/except` which returns `{"status": "error", ...}` before reaching
this code.

```python
# If include is specified, use full format as base and filter
if include is not None:
    response = result.to_api_response()
    keys = set()
    invalid = []
    for section in include:
        if section in RISK_ANALYSIS_SECTIONS:
            keys.update(RISK_ANALYSIS_SECTIONS[section])
        else:
            invalid.append(section)
    response = {k: v for k, v in response.items() if k in keys}
    response["status"] = "success"
    if invalid:
        response["invalid_sections"] = invalid
    return response
elif format == "summary":
    ...  # existing logic unchanged
```

Update docstring to document `include` param and available sections.

### 2. `mcp_server.py` — Add `include` to tool wrapper ✅

Add `Optional` to imports (`from typing import Literal, Optional`), then update registration:
```python
@mcp.tool()
def get_risk_analysis(
    portfolio_name: str = "CURRENT_PORTFOLIO",
    format: Literal["full", "summary", "report"] = "summary",
    include: Optional[list[str]] = None,
    use_cache: bool = True
) -> dict:
```

Pass through to implementation. Update docstring with section names and examples.

## Example agent usage

```
"Show me my factor betas"       → get_risk_analysis(include=["factor_analysis"])
"What's my correlation matrix?" → get_risk_analysis(include=["matrices"])
"Risk metrics and compliance"   → get_risk_analysis(include=["risk_metrics", "compliance"])
"Full risk report"              → get_risk_analysis(format="full")  # unchanged
"Quick summary"                 → get_risk_analysis()                # unchanged
```

## Verification

All cases verified with real portfolio data (direct function calls + MCP end-to-end via FastMCP Client):

1. ✅ Default behavior unchanged: `get_risk_analysis()` returns summary (8 keys), `get_risk_analysis(format="full")` returns all 40 keys (39 data + status)
2. ✅ Single section: `get_risk_analysis(include=["factor_analysis"])` returns only factor keys + status
3. ✅ Multiple sections: `get_risk_analysis(include=["risk_metrics", "compliance"])` returns union of both
4. ✅ Empty list: `get_risk_analysis(include=[])` returns only `{"status": "success"}`
5. ✅ Invalid section name: `get_risk_analysis(include=["typo"])` returns `{"status": "success", "invalid_sections": ["typo"]}`
6. ✅ Mixed valid/invalid: `get_risk_analysis(include=["risk_metrics", "typo"])` returns risk_metrics keys + `invalid_sections: ["typo"]`
7. ✅ `include` with `format="summary"` — include takes precedence, returns filtered full response

---

*Extracted from: `docs/planning/completed/RISK_MCP_PLAN.md`*
*Created: 2026-02-06*
*Updated: 2026-02-06 — Verified section mapping against actual to_api_response() keys, fixed 4 missing keys, renamed factor_betas → factor_analysis*
*Updated: 2026-02-06 — GPT review fixes: include=[] handling (P1), status flow clarification (P2), Optional type annotation (P2), invalid_sections warning (P3)*
*Implemented: 2026-02-06 — Codex implemented, verified with unit tests + MCP end-to-end tests. Commit: 4334c986*
