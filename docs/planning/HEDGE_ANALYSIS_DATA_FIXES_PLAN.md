# Hedge Analysis Data Fixes: F8, F9, F10, F11

## Context

The hedge tool redesign (`f31528f5`) introduced `recommend_portfolio_offsets()` — a factor-first methodology for generating hedge/diversification recommendations. Four data bugs were identified during QA:

- **F8**: Beta alternative Sharpe ratios always N/A
- **F9**: `_etf_to_sector` YAML normalization (minor robustness)
- **F10**: Portfolio Vol displays 669% — diagnostic logging (root cause is upstream data quality, not formula bug)
- **F11**: Diversification recs show positive correlations (+0.08, +0.18)

All bugs are in `services/factor_intelligence_service.py` and related config. F7 (driver display labels) is deferred.

---

## F8: Sharpe filter too aggressive in `_compute_beta_alternatives()`

**File**: `services/factor_intelligence_service.py:1279`

**Bug**: The filter `if sharpe is None or sharpe <= 0: continue` drops ALL candidates with zero or negative Sharpe. In bear markets or low-return environments, this eliminates the entire candidate universe → empty beta_alternatives → "N/A" in the UI.

**Fix**: Change line 1279 from:
```python
if sharpe is None or sharpe <= 0:
```
to:
```python
if sharpe is None:
```

Positive-Sharpe candidates still rank higher via the existing sort (line 1296-1299: Sharpe DESC as tiebreaker). This just stops dropping valid candidates.

**Test impact**: Existing test `test_compute_beta_alternatives_filters_ranks_and_skips_portfolio_holdings` still passes — DBA (Sharpe=-0.1, beta=0.30) would be 4th of 4 candidates, truncated by `max_candidates=3`. Add a new test with `max_candidates=5` to verify DBA is now included.

---

## F9: Defensive uppercase in `_etf_to_sector` construction

**File**: `services/factor_intelligence_service.py:1462`

**Bug**: `_extract_proxy_ticker()` already returns uppercase, but the intent isn't explicit at the call site. If `_extract_proxy_ticker` ever changes, the reverse map breaks silently.

**Fix**: At line 1462, add explicit `.upper()`:
```python
_etf_to_sector.setdefault(_etf.upper(), []).append(_sname)
```

Minimal change, defense-in-depth only. No functional behavior change expected.

---

## F10: Portfolio Vol diagnostic logging (no cap)

**File**: `services/factor_intelligence_service.py:1645-1650`

**Finding**: `annual_vol = sqrt(portfolio_variance) * 100` displays 669% instead of ~18-20%. The formula chain is unit-correct (annualized variance → annualized vol %), so the computation code is correct. The root cause is upstream data quality (extreme factor_vols or idio_var for a specific ticker). Needs runtime data to track down.

**Fix**: Add diagnostic logging without capping/distorting the value. After the existing computation at line 1650, add a warning log when vol exceeds a threshold:
```python
portfolio_variance = (view.get("variance_decomposition") or {}).get("portfolio_variance")
annual_vol = (
    round(float(np.sqrt(portfolio_variance)) * 100, 2)
    if portfolio_variance is not None and float(portfolio_variance) > 0
    else None
)
if annual_vol is not None and annual_vol > 200.0:
    _var_decomp = view.get("variance_decomposition") or {}
    logger.warning(
        "recommend_portfolio_offsets: portfolio vol %.1f%% looks extreme — "
        "portfolio_variance=%.6f, factor_var=%.6f, idio_var=%.6f. "
        "Investigate per-ticker factor_vols and idio_var for outliers.",
        annual_vol,
        float(_var_decomp.get("portfolio_variance", 0)),
        float(_var_decomp.get("factor_variance", 0)),
        float(_var_decomp.get("idiosyncratic_variance", 0)),
    )
```

No cap, no distortion — just logs the breakdown so we can identify the offending ticker next time it fires.

---

## F11: Correlation threshold alignment

**Bug**: Three conflicting defaults produce inconsistent behavior:

| Source | Value | Used by |
|--------|-------|---------|
| `settings.py:294` `OFFSET_DEFAULTS` | **0.3** | `recommend_offsets()` function default |
| `settings.py:299` `PORTFOLIO_OFFSET_DEFAULTS` | **0.3** | `recommend_portfolio_offsets()` fallback |
| `data_objects.py:1691` `PortfolioOffsetsData` | **-0.2** | MCP tool path |
| `mcp_tools/factor_intelligence.py:1031,1033` fallbacks | **0.3** | MCP None-guard |

The filter `if corr_val <= 0.3` accepts weak positive correlations (+0.08, +0.18) as "diversifiers."

**Fix — eliminate redundant fallbacks, centralize to one value**:

The single source of truth is `PortfolioOffsetsData.correlation_threshold = -0.2` in `data_objects.py:1691`. All other locations should align to `-0.2` and stop inventing their own defaults.

1. **`settings.py`** lines 294, 299: Change both `0.3` → `-0.2`
   - Update line 299 comment to: `# max correlation for diversifier candidates; more negative = stricter`

2. **`mcp_tools/factor_intelligence.py`** lines 1031, 1033: Change hardcoded `0.3` fallback → `-0.2`

No new fallback logic. Fewer fallback layers = fewer places for values to diverge.

---

## Implementation Order

1. **F11** (settings + mcp_tools) — most impactful, fixes misleading recommendations
2. **F8** (line 1279) — surgical one-line fix
3. **F10** (lines 1645-1650) — diagnostic logging
4. **F9** (line 1462) — minor robustness

## Files to Modify

| File | Changes |
|------|---------|
| `settings.py` | F11: lines 294, 299 (threshold 0.3 → -0.2) |
| `mcp_tools/factor_intelligence.py` | F11: lines 1031, 1033 (fallback 0.3 → -0.2) |
| `services/factor_intelligence_service.py` | F8: line 1279, F9: line 1462, F10: logging after line 1650 |
| `tests/services/test_factor_intelligence_service.py` | Update existing F8 test, add new tests for each fix |

## Verification

1. Run existing test suite: `pytest tests/services/test_factor_intelligence_service.py -x`
2. Run new tests for each fix
3. Manual: call `recommend_portfolio_offsets()` MCP tool and verify:
   - Beta alternatives show Sharpe values (not N/A)
   - Correlation alternatives have negative correlations
   - Portfolio Vol displays reasonable value (15-25% range for a typical equity portfolio)
