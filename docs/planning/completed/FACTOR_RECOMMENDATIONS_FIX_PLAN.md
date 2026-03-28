# Fix: get_factor_recommendations returns zero results

## Context

The `get_factor_recommendations` MCP tool returns zero hedge recommendations in both `single` and `portfolio` modes. Two bugs:

1. **MCP tool overrides portfolio-mode threshold** — Hardcodes `correlation_threshold=-0.2` for both modes. The service's portfolio default is `0.3` (settings.py:299) but the explicit `-0.2` overrides it. With `-0.2`, zero candidates pass the filter because the matrix has almost no correlations that negative.

2. **Fund tickers can't be resolved in correlation matrices** — Funds like DSU (`isFund: true`) get `proxies["industry"] = "DSU"` (proxy_builder.py:568). "DSU" isn't in any matrix. Affects both modes.

## Fix 1: Mode-appropriate correlation threshold

### 1a. `mcp_server.py:2008`
`correlation_threshold: float = -0.2` → `correlation_threshold: Optional[float] = None`
Update docstring (lines 2035-2036).

### 1b. `mcp_tools/factor_intelligence.py:904`
`correlation_threshold: float = -0.2` → `correlation_threshold: Optional[float] = None`
After line 948, before mode branching:
```python
if correlation_threshold is None:
    if mode == "portfolio":
        correlation_threshold = PORTFOLIO_OFFSET_DEFAULTS.get("correlation_threshold", 0.3)
    else:
        correlation_threshold = OFFSET_DEFAULTS.get("correlation_threshold", 0.3)
```

### 1c. `settings.py:294`
`"correlation_threshold": -0.2` → `"correlation_threshold": 0.3`

Some negative correlations exist (Biotechnology vs Agricultural ≈ -0.16), but the `-0.2` threshold is too strict for most queries. `0.3` returns useful low-correlation diversifiers. Users can pass explicit negative thresholds for strict hedging.

### 1d. `models/factor_intelligence_models.py`
- Line 313 (`OffsetRecommendationRequest`): `le=0.0` → `le=1.0`
- Line 339 (`PortfolioOffsetRecommendationRequest`): `le=0.0` → `le=1.0`

### 1e. Docstrings
Update "≤ 0.0 for hedges" in:
- `services/factor_intelligence_service.py:851`
- `services/factor_intelligence_service.py:1098`

## Fix 2: Extend `_resolve_label()` for fund tickers

**File:** `services/factor_intelligence_service.py`, `_resolve_label()` inner function (line 941-988)

This is a **single-point fix** that handles both modes. When `_resolve_label()` can't find a label via existing logic (exact match, normalization, alias, reverse ETF→sector, contains), add one final step before returning `None`:

```python
# Last resort: if label looks like a ticker, try resolving via FMP profile industry
raw_upper = raw.upper()
if raw_upper.isalpha() and len(raw_upper) <= 6:
    try:
        from core.proxy_builder import fetch_profile
        profile = fetch_profile(raw_upper)
        if profile:
            fmp_industry = profile.get("industry", "")
            if fmp_industry:
                # Try matching the industry name in the matrix
                if fmp_industry in df.index or fmp_industry in df.columns:
                    return fmp_industry
                ind_norm = _norm_label(fmp_industry)
                for lbl in all_labels:
                    if _norm_label(lbl) == ind_norm:
                        return lbl
    except Exception:
        pass  # fetch_profile can raise on missing provider/data — graceful fallback
```

**Key design decisions:**
- Wrapped in try/except: `fetch_profile()` (proxy_builder.py:297-337) can raise on missing provider/data. A resolution failure should degrade to "no label found", not crash.
- Uses `raw_upper = raw.upper()` for case-insensitive ticker detection and `fetch_profile()` call. Handles "dsu", "Dsu", "DSU" identically.
- Gate on `raw_upper.isalpha() and len(raw_upper) <= 6`: avoids false positives on industry names like "Asset Management" or "Financial - Mortgages" (which contain spaces/hyphens)
- Reuses existing `_norm_label()` and `all_labels` already computed in the function

**What this fixes:**
- `recommend_offsets("DSU")` → resolves to "Asset Management" → finds hedges
- Portfolio driver detection with "DSU" label → `recommend_offsets("DSU")` succeeds via the extended `_resolve_label()`

**What this doesn't fix (cosmetic, defer):**
- Driver display label still shows "DSU" instead of "Asset Management" in portfolio mode. This is a display-only issue — hedges ARE returned because `_resolve_label()` now handles the mapping. Fixing driver display labels touches the complex `_etf_to_sector` / `analysis_result` branch logic — defer to a follow-up.

## Files to modify

| File | Change |
|------|--------|
| `mcp_server.py` | `correlation_threshold` → `Optional[float] = None` (line 2008), docstring |
| `mcp_tools/factor_intelligence.py` | `correlation_threshold` → `Optional[float] = None` (line 904), mode-dispatch |
| `settings.py` | `offsets.correlation_threshold` → `0.3` (line 294) |
| `models/factor_intelligence_models.py` | `le=0.0` → `le=1.0` (lines 313, 339) |
| `services/factor_intelligence_service.py` | Extend `_resolve_label()` with FMP profile fallback; update docstrings (lines 851, 1098) |

## Verification

1. **Portfolio mode:** `get_factor_recommendations(mode="portfolio", format="agent")` → non-empty recommendations
2. **Single mode:** `get_factor_recommendations(overexposed_factor="Technology", format="agent")` → recommendations
3. **Strict threshold:** `get_factor_recommendations(overexposed_factor="Technology", correlation_threshold=-0.5)` → empty
4. **Fund single:** `get_factor_recommendations(overexposed_factor="DSU")` → resolves to industry, returns results
5. **REST positive threshold:** POST `/api/factor-intelligence/recommendations` with `correlation_threshold=0.3` passes Pydantic
6. **Existing tests:**
   ```
   pytest tests/mcp_tools/test_factor_recs_agent_format.py tests/core/test_factor_recommendation_flags.py tests/core/test_factor_recs_agent_snapshot.py tests/services/test_factor_intelligence_service.py tests/factor_intelligence/test_recommend_offsets_matching.py tests/factor_intelligence/test_api.py -x
   ```
7. **New tests:**
   - `_get_factor_recommendations()` dispatches different defaults by mode when `correlation_threshold=None`
   - `mcp_server.py` entrypoint signature has `correlation_threshold` defaulting to `None`
   - `_resolve_label()` resolves fund ticker (DSU) to FMP profile industry — test uppercase, lowercase, and mixed-case inputs
   - `_resolve_label()` returns `None` gracefully when `fetch_profile()` fails
   - Positive threshold (0.3) passes Pydantic validation on both request models
