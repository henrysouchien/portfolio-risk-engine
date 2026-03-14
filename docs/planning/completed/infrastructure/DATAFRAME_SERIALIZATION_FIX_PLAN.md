# B-006: DataFrame Serialization — Fix `_convert_to_json_serializable()`

**Status**: COMPLETE — commit `f2a48bcc`, verified in browser

## Context

`_convert_to_json_serializable()` in `core/result_objects/_helpers.py` calls `df.to_dict()` without an `orient` param, producing **column-oriented dicts** (`{"Column": {"0": value}}`) instead of **row arrays** (`[{"Column": value}]`). Docstrings and comments throughout the codebase say "row format" / `List[Dict]` but the actual output is column-oriented. The frontend added a `dataFrameToRows()` workaround in ScenarioAnalysis to handle this.

**However**, not all DataFrames should use `orient='records'`. Matrix-like DataFrames (`correlation_matrix`, `covariance_matrix`) naturally use column-oriented format as a lookup table (`matrix[ticker1][ticker2]`). The fix must be selective.

## Approach: Surgical — Add `orient` param to helper, fix specific callers

**Why not change the global default**: The global helper is called at 65+ sites across 6 files. Many callers pass nested dicts containing DataFrames (risk_score `portfolio_analysis`, factor_intelligence overlays with matrix DataFrames). Changing the global default cascades unpredictably — matrices inside nested payloads silently change shape. Three rounds of Codex review kept finding new blast radius issues.

**Surgical approach**: Add an optional `orient` parameter to `_convert_to_json_serializable()` that defaults to the current behavior (`'dict'`). Callers that want records format explicitly opt in with `orient='records'`. Fix only the specific call sites where records format is needed — the tabular check/comparison DataFrames in `optimization.py` and `whatif.py`.

This is safer, backward-compatible, and avoids the cascade problem entirely.

## Callers — Full Blast Radius

| File | # of calls | DataFrames? | Impact |
|------|-----------|-------------|--------|
| `core/result_objects/risk.py` | 14 | Yes — `allocations`, `covariance_matrix`, `correlation_matrix`, `stock_betas`, `asset_vol_summary`, `factor_vols`, `weighted_factor_var` + Series fields | **High** — matrices need pre-serialization |
| `core/result_objects/optimization.py` | 8 | Yes — `risk_checks`, `factor_checks`, `proxy_checks`, violations, legacy tables | **Medium** — tabular, records format is correct |
| `core/result_objects/whatif.py` | 8 | Yes — `risk_checks`, `factor_checks`, `proxy_checks`, violations, comparisons | **Medium** — tabular, frontend `dataFrameToRows()` already handles both |
| `core/result_objects/factor_intelligence.py` | 14 | Mixed — some overlays contain matrix DataFrames from analysis payloads | **None** (opt-in approach — all calls keep default `orient='dict'`) |
| `core/result_objects/performance.py` | 1 | No — plain dict | **None** |
| `core/result_objects/interpretation.py` | 1 | No — plain dict | **None** |

### pd.Series fields (unaffected)

`risk_contributions`, `portfolio_factor_betas`, `portfolio_returns`, `euler_variance_pct` — `pd.Series.to_dict()` always produces `{index: value}` regardless of orient. No change.

### Index preservation

DataFrames with meaningful row indexes (ticker names, factor names) need `reset_index()` before `to_dict(orient='records')` to avoid silently dropping the index.

**`reset_index()` caveat**: On a default RangeIndex, `reset_index()` adds an unwanted `index` column. On filtered integer slices (`df[~df['Pass']]`), the index is `Int64Index` (not RangeIndex) which would also trigger a naive `isinstance(RangeIndex)` check. Fix: use `index.name is not None` — this detects genuinely named indexes (e.g. factor names set via `df.index.name = "factor"`) without false-triggering on unnamed integer/filtered indexes.

## Changes

### 1. `core/result_objects/_helpers.py` — Add `orient` parameter

Add an optional `orient` parameter to `_convert_to_json_serializable()`:

```python
def _convert_to_json_serializable(data, orient='dict'):
    """...existing docstring..."""
    if isinstance(data, pd.DataFrame):
        df_copy = data.copy()
        # ... existing numpy/NaN cleanup ...
        if orient == 'records':
            # For records format, preserve named indexes as columns.
            # Use index.name to detect meaningful indexes (e.g. "factor", ticker names)
            # rather than isinstance(RangeIndex) which fails on filtered integer slices.
            if df_copy.index.name is not None:
                df_copy = df_copy.reset_index()
            result = df_copy.to_dict(orient='records')
        else:
            result = df_copy.to_dict()
        return _clean_nan_values(result)
    if isinstance(data, dict):
        return {k: _convert_to_json_serializable(v, orient=orient) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_convert_to_json_serializable(item, orient=orient) for item in data]
    # ... rest of scalar/Series handling unchanged ...
```

**Key details**:
- Default `'dict'` — fully backward-compatible
- `orient` is propagated through dict/list recursion
- `index.name is not None` detects meaningful named indexes (factor names, ticker names) without false-triggering on filtered integer slices from `df[~df['Pass']]`

### 2. `core/result_objects/whatif.py` — Use `orient='records'` for tabular DataFrames

In `_build_risk_analysis()`, `_build_beta_analysis()`, and `_build_comparison_analysis()`, pass `orient='records'` for the tabular check/comparison/violation DataFrames:

```python
# _build_risk_analysis() (~line 707):
risk_checks = _convert_to_json_serializable(risk_df, orient='records')
risk_violations = _convert_to_json_serializable(risk_df[~risk_df['Pass']], orient='records')

# _build_beta_analysis() (~line 731):
factor_checks = _convert_to_json_serializable(factor_df, orient='records')
factor_violations = _convert_to_json_serializable(factor_df[~factor_df['pass']], orient='records')
proxy_checks = _convert_to_json_serializable(proxy_df, orient='records')
proxy_violations = _convert_to_json_serializable(proxy_df[~proxy_df['pass']], orient='records')

# _build_comparison_analysis() (~line 756):
risk_comparison = _convert_to_json_serializable(self.risk_comparison, orient='records')
beta_comparison = _convert_to_json_serializable(self.beta_comparison, orient='records')
```

The outer `to_api_response()` call at line 692 keeps default `orient='dict'` — all other nested fields (formatted tables, plain dicts) are unaffected.

### 3. `core/result_objects/optimization.py` — Use `orient='records'` for structured fields only

The **structured** fields (`risk_checks`, `factor_checks`, `proxy_checks`, violations) use `orient='records'` (~lines 434-446):

```python
"risk_checks": _convert_to_json_serializable(self.risk_table, orient='records'),
"factor_checks": _convert_to_json_serializable(self.beta_table, orient='records'),
"proxy_checks": _convert_to_json_serializable(self.proxy_table, orient='records'),
"risk_violations": _convert_to_json_serializable(risk_df[~risk_df['Pass']], orient='records'),
# ... same for factor/proxy violations ...
```

The **legacy** fields (`risk_table`, `beta_table`, `factor_table`, `proxy_table` at ~lines 475-478) keep default `orient='dict'` (column-oriented). These are documented as column-oriented in existing API samples and consumed by `show_api_output.py`.

### 4. `tests/utils/show_api_output.py` — Minimal update

Legacy fields (`risk_table`, `beta_table`, `proxy_table`) keep column-oriented format — **no changes needed for those**. Only update the `risk_violations` handler (if it reads from the structured `risk_violations` field which now uses records). This is a dev-only utility.

### 5. Frontend — No changes needed

- **`dataFrameToRows()`**: Already handles `Array.isArray(df)` by passing through. Records format works transparently.
- **TypeScript types**: All DataFrame fields consumed by frontend (correlation_matrix, weighted_factor_var, etc.) keep their existing column-oriented shape. No type changes.
- **Adapters/components**: All `Object.entries()` access patterns preserved. No adapter changes.

## Files Modified

| File | Change |
|------|--------|
| `core/result_objects/_helpers.py` | Add `orient` param (default `'dict'`), propagate through recursion, smart `reset_index()` via `index.name` |
| `core/result_objects/whatif.py` | Pass `orient='records'` for 8 tabular DataFrame calls in `_build_*` methods |
| `core/result_objects/optimization.py` | Pass `orient='records'` for structured fields only (~6 calls). Legacy fields keep default. |
| `tests/utils/show_api_output.py` | Update `risk_violations` handler if needed (legacy fields unchanged) |

## What Does NOT Change

- **`risk.py`** — all calls keep default `orient='dict'`. Matrices, lookup DataFrames, Series fields all unchanged.
- **`factor_intelligence.py`** — all calls keep default. No format change.
- **`performance.py`**, **`interpretation.py`** — plain dicts, unaffected.
- **Frontend** — zero changes. `dataFrameToRows()` handles both formats. TypeScript types unchanged. Adapters unchanged.

## Codex Findings (3 rounds)

### v1:
1. `reset_index()` not harmless on RangeIndex — adds unwanted `index` column
2. `weighted_factor_var` breaks `FactorRiskModelContainer.tsx` — Object.entries() access
3. `factor_vols` and `asset_vol_summary` — same pattern
4. MCP agent snapshots unaffected (don't use `_convert_to_json_serializable`)

### v2:
5. `show_api_output.py` — beta_table + proxy_table also need updating (not just risk_table)
6. Risk-score `portfolio_analysis` contains nested DataFrames (including matrices) — would change format
7. `factor_intelligence.py` overlays contain matrix DataFrames — would change format

### Resolution: Changed from global default to opt-in parameter
All v1+v2 findings stemmed from changing the global default behavior. **Switched to surgical approach**: add `orient` param, keep default as `'dict'`, only opt-in specific tabular callers in `whatif.py` and `optimization.py`. This eliminates the entire blast radius — risk.py, factor_intelligence.py, risk_score are completely untouched.

## Verification

1. `cd frontend && pnpm exec tsc --noEmit -p packages/ui/tsconfig.json` passes
2. `cd frontend && pnpm exec eslint` on modified files passes
3. Backend: `curl localhost:5001/api/analyze` → verify tabular fields are records format, `correlation_matrix` is still matrix format
4. Backend: `curl -X POST localhost:5001/api/what-if` → verify `risk_checks`, `risk_comparison` are records format
5. Frontend: Factor Analysis (⌘3), Scenario Analysis (⌘8) render correctly
6. `python3 tests/utils/show_api_output.py analyze` still works
