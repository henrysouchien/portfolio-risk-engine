
#EXAMPLE FULLY-DETAILED PROMPT:
---

**PROMPT FOR CLAUDE**

You are an engineering assistant working in the `risk_module` repository.  
Your task is to execute the **pilot refactor** for Phase 1.5 of our OpenAPI migration, limited to the single result object **`RiskAnalysisResult`**.

---

## 1. Goals

1. Replace all API-facing uses of `RiskAnalysisResult.to_dict()` with a new, schema-compliant `to_api_response()` method.
2. Create a Marshmallow schema that matches the structure returned by `to_api_response()`.
3. Update every endpoint that returns a `RiskAnalysisResult` so it:
   • Calls `to_api_response()`  
   • Is decorated with `@bp.response(200, RiskAnalysisResultSchema)` (or via SuccessWrapper if that’s the existing pattern).  
4. Leave internal/back-compat hooks in place (see details).

When you finish, all tests must pass and Swagger UI (`/docs/`) must generate without errors.

---

## 2. Detailed Requirements

### 2.1 Result Object Changes

File: `core/result_objects.py`

1. Locate the `RiskAnalysisResult` class.
2. **Add** a method:
   ```python
   def to_api_response(self) -> Dict[str, Any]:
       """
       Schema-compliant version of the old to_dict().
       For Phase 1.5 this must be a 1-to-1 copy of to_dict()’s output
       (no structural changes, no field renames, no pruning).
       """
       # COPY the existing to_dict() logic verbatim
   ```
3. **Deprecate** `to_dict()` but keep it temporarily:
   ```python
   def to_dict(self) -> Dict[str, Any]:
       """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
       import warnings
       warnings.warn("RiskAnalysisResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
       return self.to_api_response()   # delegate
   ```
4. Update class docstring to note the new method.

### 2.2 Schema

1. Create file `schemas/risk_analysis_result.py`.
2. Define a **permissive but keyed** schema so Swagger is useful yet implementation is fast:

   ```python
   from marshmallow import Schema, fields

   class VolatilityMetricsSchema(Schema):
       annual = fields.Float()
       monthly = fields.Float()

   class RiskAnalysisResultSchema(Schema):
       volatility_annual        = fields.Float()
       volatility_monthly       = fields.Float()
       herfindahl               = fields.Float()
       portfolio_factor_betas   = fields.Dict()
       variance_decomposition   = fields.Dict()
       risk_contributions       = fields.Dict()
       df_stock_betas           = fields.Dict()
       covariance_matrix        = fields.Dict()
       correlation_matrix       = fields.Dict()
       allocations              = fields.Dict()
       factor_vols              = fields.Dict()
       weighted_factor_var      = fields.Float()
       asset_vol_summary        = fields.Dict()
       portfolio_returns        = fields.Dict()
       euler_variance_pct       = fields.Dict()
       industry_variance        = fields.Dict()
       suggested_limits         = fields.Dict()
       risk_checks              = fields.Dict()
       beta_checks              = fields.Dict()
       max_betas                = fields.Dict()
       max_betas_by_proxy       = fields.Dict()
       analysis_date            = fields.DateTime()
       portfolio_name           = fields.String()
       formatted_report         = fields.String()
   ```

   (Most complex fields are left as `Dict` for now—Phase 1.6 will curate.)

3. Add an import in `schemas/__init__.py`:
   ```python
   from .risk_analysis_result import RiskAnalysisResultSchema
   ```

### 2.3 Endpoint Updates

Search/replace all call-sites listed in the audit:

| File | Line (audit) | Action |
|------|--------------|--------|
| `routes/api.py` | 115 & 259 | replace `result.to_dict()` → `result.to_api_response()`; add `@bp.response(200, RiskAnalysisResultSchema)` (or wrap inside SuccessWrapper if route returns wrapper). |
| `services/portfolio/context_service.py` | 305 | same replacement (no decorator change needed here). |

Implementation notes:

• **Import** the new schema at the top of `routes/api.py`:
```python
from schemas import RiskAnalysisResultSchema
```

• If the endpoint currently returns a wrapper like
```python
return {"success": True, "data": result.to_dict(), ...}
```
change only the `data` value to `result.to_api_response()`.  
Decorate with the wrapper schema if that pattern exists (`SuccessWrapperSchema`); otherwise use `RiskAnalysisResultSchema` directly.

### 2.4 Tests & Validation

1. Run `pytest` – ensure green.
2. Manually hit `/api/portfolio-analysis` (or equivalent) and confirm JSON returns identical content as before.
3. Open Swagger UI (`/docs/`) – new schema should appear in the docs without validation errors.

### 2.5 Docs

1. Add `RiskAnalysisResultSchema` to `docs/API_REFERENCE.md` endpoint table (optional but nice).
2. No other doc work required in this PR.

---

## 3. Acceptance Criteria

• **No failing tests** (`pytest` green).  
• **Swagger UI** renders and includes `RiskAnalysisResult` schema.  
• All three `to_dict()` call-sites updated.  
• `RiskAnalysisResult.to_dict()` emits `DeprecationWarning`.  
• New schema file and `schemas/__init__.py` updated.  
• Code style passes `pytest --flake8` (if flake8 is part of suite).  

Commit message suggestion:
```
feat(api): add to_api_response & schema for RiskAnalysisResult

* Adds RiskAnalysisResult.to_api_response() (1:1 with previous to_dict()).
* Deprecates RiskAnalysisResult.to_dict().
* Introduces schemas.risk_analysis_result.RiskAnalysisResultSchema.
* Updates all endpoints and services to use the new method.
* Swagger UI now documents RiskAnalysisResult schema.
```

---

**End of prompt**

---

# Phase 1.5 – Result Object Refactor Prompts

Copy-ready prompts for Claude to migrate every remaining result object from `to_dict()` → `to_api_response()` and add Marshmallow schemas.  Each prompt mirrors the successful **RiskAnalysisResult** pilot refactor.  Hand one prompt at a time to a Claude instance (or developer) and review / merge sequentially.

---

## 📌 Usage Notes  
* Paste ONE prompt verbatim into a Claude chat.  
* Wait for the PR, review, merge, then move to the next prompt.  
* PR title convention: `feat(api): add to_api_response & schema for <ResultObject>`.
* Ensure CI + Swagger UI stay green after each merge.

---

#STUB PROMPTS TO UPDATE:

## 1. **PerformanceResult** – Prompt

```
You are an engineering assistant working in the `risk_module` repository.  
Your task is to execute the **Phase 1.5 refactor** for the single result object **`PerformanceResult`**.

---

## 1. Goals

1. Replace all API-facing uses of `PerformanceResult.to_dict()` with a new, schema-compliant `to_api_response()` method.
2. Create a Marshmallow schema that matches the structure returned by `to_api_response()`.
3. Update every endpoint that returns a `PerformanceResult` so it:
   • Calls `to_api_response()`  
   • Is decorated with `@bp.response(200, PerformanceResultSchema)` (or via SuccessWrapper if that's the existing pattern).  
4. Leave internal/back-compat hooks in place (see details).

When you finish, all tests must pass and Swagger UI (`/docs/`) must generate without errors.

---

## 2. Detailed Requirements

### 2.1 Result Object Changes

File: `/Users/henrychien/Documents/Jupyter/risk_module/core/result_objects.py`

1. Locate the `PerformanceResult` class.
2. **Add** a method:
   ```python
   def to_api_response(self) -> Dict[str, Any]:
       """
       Schema-compliant version of the old to_dict().
       For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
       (no structural changes, no field renames, no pruning).
       """
       # COPY the existing to_dict() logic verbatim
   ```
3. **Deprecate** `to_dict()` but keep it temporarily:
   ```python
   def to_dict(self) -> Dict[str, Any]:
       """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
       import warnings
       warnings.warn("PerformanceResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
       return self.to_api_response()   # delegate
   ```
4. Update class docstring to note the new method.

### 2.2 Schema

1. Create file `/Users/henrychien/Documents/Jupyter/risk_module/schemas/performance_result.py`.
2. Define a **permissive but keyed** schema so Swagger is useful yet implementation is fast:

   ```python
   from marshmallow import Schema, fields

   class PerformanceResultSchema(Schema):
       analysis_period = fields.Dict()
       returns = fields.Dict()
       risk_metrics = fields.Dict()
       risk_adjusted_returns = fields.Dict()
       benchmark_analysis = fields.Dict()
       benchmark_comparison = fields.Dict()
       monthly_stats = fields.Dict()
       risk_free_rate = fields.Float()
       monthly_returns = fields.Dict()
       analysis_date = fields.String()
       portfolio_name = fields.String(allow_none=True)
       formatted_report = fields.String()
   ```

   (Most complex fields are left as `Dict` for now—Phase 1.6 will curate.)

3. Add an import in `/Users/henrychien/Documents/Jupyter/risk_module/schemas/__init__.py`:
   ```python
   from .performance_result import PerformanceResultSchema
   ```

### 2.3 Endpoint Updates

Search/replace all call-sites listed in the audit:

| File | Line (audit) | Action |
|------|--------------|--------|
| `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py` | 981 | replace `result.to_dict()` → `result.to_api_response()`; add `@bp.response(200, PerformanceResultSchema)` (or wrap inside SuccessWrapper if route returns wrapper). |

Implementation notes:

• **Import** the new schema at the top of `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py`:
```python
from schemas import PerformanceResultSchema
```

• If the endpoint currently returns a wrapper like
```python
return {"success": True, "data": result.to_dict(), ...}
```
change only the `data` value to `result.to_api_response()`.  
Decorate with the wrapper schema if that pattern exists (`SuccessWrapperSchema`); otherwise use `PerformanceResultSchema` directly.

### 2.4 Tests & Validation

1. Run `pytest` – ensure green.
2. Manually hit `/api/performance-analysis` (or equivalent) and confirm JSON returns identical content as before.
3. Open Swagger UI (`/docs/`) – new schema should appear in the docs without validation errors.

### 2.5 Docs

1. Add `PerformanceResultSchema` to `/Users/henrychien/Documents/Jupyter/risk_module/docs/API_REFERENCE.md` endpoint table (optional but nice).
2. No other doc work required in this PR.

---

## 3. Acceptance Criteria

• **No failing tests** (`pytest` green).  
• **Swagger UI** renders and includes `PerformanceResult` schema.  
• All `to_dict()` call-sites updated.  
• `PerformanceResult.to_dict()` emits `DeprecationWarning`.  
• New schema file and `schemas/__init__.py` updated.  
• Code style passes `pytest --flake8` (if flake8 is part of suite).  

Commit message suggestion:
```
feat(api): add to_api_response & schema for PerformanceResult

* Adds PerformanceResult.to_api_response() (1:1 with previous to_dict()).
* Deprecates PerformanceResult.to_dict().
* Introduces schemas.performance_result.PerformanceResultSchema.
* Updates all endpoints and services to use the new method.
* Swagger UI now documents PerformanceResult schema.
```

---

**End of prompt**
```

---

## 2. **RiskScoreResult** – Prompt

```
You are an engineering assistant working in the `risk_module` repository.  
Your task is to execute the **Phase 1.5 refactor** for the single result object **`RiskScoreResult`**.

---

## 1. Goals

1. Replace all API-facing uses of `RiskScoreResult.to_dict()` with a new, schema-compliant `to_api_response()` method.
2. Create a Marshmallow schema that matches the structure returned by `to_api_response()`.
3. Update every endpoint that returns a `RiskScoreResult` so it:
   • Calls `to_api_response()`  
   • Is decorated with `@bp.response(200, RiskScoreResultSchema)` (or via SuccessWrapper if that's the existing pattern).  
4. Leave internal/back-compat hooks in place (see details).

When you finish, all tests must pass and Swagger UI (`/docs/`) must generate without errors.

---

## 2. Detailed Requirements

### 2.1 Result Object Changes

File: `/Users/henrychien/Documents/Jupyter/risk_module/core/result_objects.py`

1. Locate the `RiskScoreResult` class.
2. **Add** a method:
   ```python
   def to_api_response(self) -> Dict[str, Any]:
       """
       Schema-compliant version of the old to_dict().
       For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
       (no structural changes, no field renames, no pruning).
       """
       # COPY the existing to_dict() logic verbatim
   ```
3. **Deprecate** `to_dict()` but keep it temporarily:
   ```python
   def to_dict(self) -> Dict[str, Any]:
       """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
       import warnings
       warnings.warn("RiskScoreResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
       return self.to_api_response()   # delegate
   ```
4. Update class docstring to note the new method.

### 2.2 Schema

1. Create file `/Users/henrychien/Documents/Jupyter/risk_module/schemas/risk_score_result.py`.
2. Define a **permissive but keyed** schema so Swagger is useful yet implementation is fast:

   ```python
   from marshmallow import Schema, fields

   class RiskScoreResultSchema(Schema):
       risk_score = fields.Dict()
       limits_analysis = fields.Dict()
       portfolio_analysis = fields.Dict()
       suggested_limits = fields.Dict()
       portfolio_file = fields.String(allow_none=True)
       risk_limits_file = fields.String(allow_none=True)
       formatted_report = fields.String()
       analysis_date = fields.String()
       portfolio_name = fields.String(allow_none=True)
   ```

   (Most complex fields are left as `Dict` for now—Phase 1.6 will curate.)

3. Add an import in `/Users/henrychien/Documents/Jupyter/risk_module/schemas/__init__.py`:
   ```python
   from .risk_score_result import RiskScoreResultSchema
   ```

### 2.3 Endpoint Updates

Search/replace all call-sites listed in the audit:

| File | Line (audit) | Action |
|------|--------------|--------|
| `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py` | 375 | replace `result.to_dict()` → `result.to_api_response()`; add `@bp.response(200, RiskScoreResultSchema)` (or wrap inside SuccessWrapper if route returns wrapper). |
| `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py` | 1274 | replace `result_obj.to_dict()` → `result_obj.to_api_response()`; add `@bp.response(200, RiskScoreResultSchema)` (or wrap inside SuccessWrapper if route returns wrapper). |

Implementation notes:

• **Import** the new schema at the top of `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py`:
```python
from schemas import RiskScoreResultSchema
```

• If the endpoint currently returns a wrapper like
```python
return {"success": True, "data": result.to_dict(), ...}
```
change only the `data` value to `result.to_api_response()`.  
Decorate with the wrapper schema if that pattern exists (`SuccessWrapperSchema`); otherwise use `RiskScoreResultSchema` directly.

### 2.4 Tests & Validation

1. Run `pytest` – ensure green.
2. Manually hit `/api/risk-score` (or equivalent) and confirm JSON returns identical content as before.
3. Open Swagger UI (`/docs/`) – new schema should appear in the docs without validation errors.

### 2.5 Docs

1. Add `RiskScoreResultSchema` to `/Users/henrychien/Documents/Jupyter/risk_module/docs/API_REFERENCE.md` endpoint table (optional but nice).
2. No other doc work required in this PR.

---

## 3. Acceptance Criteria

• **No failing tests** (`pytest` green).  
• **Swagger UI** renders and includes `RiskScoreResult` schema.  
• All `to_dict()` call-sites updated.  
• `RiskScoreResult.to_dict()` emits `DeprecationWarning`.  
• New schema file and `schemas/__init__.py` updated.  
• Code style passes `pytest --flake8` (if flake8 is part of suite).  

Commit message suggestion:
```
feat(api): add to_api_response & schema for RiskScoreResult

* Adds RiskScoreResult.to_api_response() (1:1 with previous to_dict()).
* Deprecates RiskScoreResult.to_dict().
* Introduces schemas.risk_score_result.RiskScoreResultSchema.
* Updates all endpoints and services to use the new method.
* Swagger UI now documents RiskScoreResult schema.
```

---

**End of prompt**
```

---

## 3. **StockAnalysisResult** – Prompt

```
You are an engineering assistant working in the `risk_module` repository.  
Your task is to execute the **Phase 1.5 refactor** for the single result object **`StockAnalysisResult`**.

---

## 1. Goals

1. Replace all API-facing uses of `StockAnalysisResult.to_dict()` with a new, schema-compliant `to_api_response()` method.
2. Create a Marshmallow schema that matches the structure returned by `to_api_response()`.
3. Update every endpoint that returns a `StockAnalysisResult` so it:
   • Calls `to_api_response()`  
   • Is decorated with `@bp.response(200, StockAnalysisResultSchema)` (or via SuccessWrapper if that's the existing pattern).  
4. Leave internal/back-compat hooks in place (see details).

When you finish, all tests must pass and Swagger UI (`/docs/`) must generate without errors.

---

## 2. Detailed Requirements

### 2.1 Result Object Changes

File: `/Users/henrychien/Documents/Jupyter/risk_module/core/result_objects.py`

1. Locate the `StockAnalysisResult` class.
2. **Add** a method:
   ```python
   def to_api_response(self) -> Dict[str, Any]:
       """
       Schema-compliant version of the old to_dict().
       For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
       (no structural changes, no field renames, no pruning).
       """
       # COPY the existing to_dict() logic verbatim
   ```
3. **Deprecate** `to_dict()` but keep it temporarily:
   ```python
   def to_dict(self) -> Dict[str, Any]:
       """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
       import warnings
       warnings.warn("StockAnalysisResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
       return self.to_api_response()   # delegate
   ```
4. Update class docstring to note the new method.

### 2.2 Schema

1. Create file `/Users/henrychien/Documents/Jupyter/risk_module/schemas/stock_analysis_result.py`.
2. Define a **permissive but keyed** schema so Swagger is useful yet implementation is fast:

   ```python
   from marshmallow import Schema, fields

   class StockAnalysisResultSchema(Schema):
       ticker = fields.String()
       volatility_metrics = fields.Dict()
       regression_metrics = fields.Dict()
       factor_summary = fields.Dict()
       risk_metrics = fields.Dict()
       analysis_date = fields.String()
   ```

   (Most complex fields are left as `Dict` for now—Phase 1.6 will curate.)

3. Add an import in `/Users/henrychien/Documents/Jupyter/risk_module/schemas/__init__.py`:
   ```python
   from .stock_analysis_result import StockAnalysisResultSchema
   ```

### 2.3 Endpoint Updates

Search/replace all call-sites listed in the audit:

| File | Line (audit) | Action |
|------|--------------|--------|
| `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py` | 824 | replace `result.to_dict()` → `result.to_api_response()`; add `@bp.response(200, StockAnalysisResultSchema)` (or wrap inside SuccessWrapper if route returns wrapper). |

Implementation notes:

• **Import** the new schema at the top of `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py`:
```python
from schemas import StockAnalysisResultSchema
```

• If the endpoint currently returns a wrapper like
```python
return {"success": True, "data": result.to_dict(), ...}
```
change only the `data` value to `result.to_api_response()`.  
Decorate with the wrapper schema if that pattern exists (`SuccessWrapperSchema`); otherwise use `StockAnalysisResultSchema` directly.

### 2.4 Tests & Validation

1. Run `pytest` – ensure green.
2. Manually hit `/api/stock-analysis` (or equivalent) and confirm JSON returns identical content as before.
3. Open Swagger UI (`/docs/`) – new schema should appear in the docs without validation errors.

### 2.5 Docs

1. Add `StockAnalysisResultSchema` to `/Users/henrychien/Documents/Jupyter/risk_module/docs/API_REFERENCE.md` endpoint table (optional but nice).
2. No other doc work required in this PR.

---

## 3. Acceptance Criteria

• **No failing tests** (`pytest` green).  
• **Swagger UI** renders and includes `StockAnalysisResult` schema.  
• All `to_dict()` call-sites updated.  
• `StockAnalysisResult.to_dict()` emits `DeprecationWarning`.  
• New schema file and `schemas/__init__.py` updated.  
• Code style passes `pytest --flake8` (if flake8 is part of suite).  

Commit message suggestion:
```
feat(api): add to_api_response & schema for StockAnalysisResult

* Adds StockAnalysisResult.to_api_response() (1:1 with previous to_dict()).
* Deprecates StockAnalysisResult.to_dict().
* Introduces schemas.stock_analysis_result.StockAnalysisResultSchema.
* Updates all endpoints and services to use the new method.
* Swagger UI now documents StockAnalysisResult schema.
```

---

**End of prompt**
```

---

## 4. **OptimizationResult** – Prompt

```
You are an engineering assistant working in the `risk_module` repository.  
Your task is to execute the **Phase 1.5 refactor** for the single result object **`OptimizationResult`**.

---

## 1. Goals

1. Replace all API-facing uses of `OptimizationResult.to_dict()` with a new, schema-compliant `to_api_response()` method.
2. Create a Marshmallow schema that matches the structure returned by `to_api_response()`.
3. Update every endpoint that returns a `OptimizationResult` so it:
   • Calls `to_api_response()`  
   • Is decorated with `@bp.response(200, OptimizationResultSchema)` (or via SuccessWrapper if that's the existing pattern).  
4. Leave internal/back-compat hooks in place (see details).

When you finish, all tests must pass and Swagger UI (`/docs/`) must generate without errors.

---

## 2. Detailed Requirements

### 2.1 Result Object Changes

File: `/Users/henrychien/Documents/Jupyter/risk_module/core/result_objects.py`

1. Locate the `OptimizationResult` class.
2. **Add** a method:
   ```python
   def to_api_response(self) -> Dict[str, Any]:
       """
       Schema-compliant version of the old to_dict().
       For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
       (no structural changes, no field renames, no pruning).
       """
       # COPY the existing to_dict() logic verbatim
   ```
3. **Deprecate** `to_dict()` but keep it temporarily:
   ```python
   def to_dict(self) -> Dict[str, Any]:
       """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
       import warnings
       warnings.warn("OptimizationResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
       return self.to_api_response()   # delegate
   ```
4. Update class docstring to note the new method.

### 2.2 Schema

1. Create file `/Users/henrychien/Documents/Jupyter/risk_module/schemas/optimization_result.py`.
2. Define a **permissive but keyed** schema so Swagger is useful yet implementation is fast:

   ```python
   from marshmallow import Schema, fields

   class OptimizationResultSchema(Schema):
       optimized_weights = fields.Dict()
       optimization_type = fields.String()
       risk_table = fields.Dict()
       beta_table = fields.Dict()
       portfolio_summary = fields.Dict(allow_none=True)
       factor_table = fields.Dict()
       proxy_table = fields.Dict()
       analysis_date = fields.String()
       summary = fields.Dict()
   ```

   (Most complex fields are left as `Dict` for now—Phase 1.6 will curate.)

3. Add an import in `/Users/henrychien/Documents/Jupyter/risk_module/schemas/__init__.py`:
   ```python
   from .optimization_result import OptimizationResultSchema
   ```

### 2.3 Endpoint Updates

Search/replace all call-sites listed in the audit:

| File | Line (audit) | Action |
|------|--------------|--------|
| `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py` | 914 | replace `result_obj.to_dict()` → `result_obj.to_api_response()`; add `@bp.response(200, OptimizationResultSchema)` (or wrap inside SuccessWrapper if route returns wrapper). |

Implementation notes:

• **Import** the new schema at the top of `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py`:
```python
from schemas import OptimizationResultSchema
```

• If the endpoint currently returns a wrapper like
```python
return {"success": True, "data": result_obj.to_dict(), ...}
```
change only the `data` value to `result_obj.to_api_response()`.  
Decorate with the wrapper schema if that pattern exists (`SuccessWrapperSchema`); otherwise use `OptimizationResultSchema` directly.

### 2.4 Tests & Validation

1. Run `pytest` – ensure green.
2. Manually hit `/api/optimization` (or equivalent) and confirm JSON returns identical content as before.
3. Open Swagger UI (`/docs/`) – new schema should appear in the docs without validation errors.

### 2.5 Docs

1. Add `OptimizationResultSchema` to `/Users/henrychien/Documents/Jupyter/risk_module/docs/API_REFERENCE.md` endpoint table (optional but nice).
2. No other doc work required in this PR.

---

## 3. Acceptance Criteria

• **No failing tests** (`pytest` green).  
• **Swagger UI** renders and includes `OptimizationResult` schema.  
• All `to_dict()` call-sites updated.  
• `OptimizationResult.to_dict()` emits `DeprecationWarning`.  
• New schema file and `schemas/__init__.py` updated.  
• Code style passes `pytest --flake8` (if flake8 is part of suite).  

Commit message suggestion:
```
feat(api): add to_api_response & schema for OptimizationResult

* Adds OptimizationResult.to_api_response() (1:1 with previous to_dict()).
* Deprecates OptimizationResult.to_dict().
* Introduces schemas.optimization_result.OptimizationResultSchema.
* Updates all endpoints and services to use the new method.
* Swagger UI now documents OptimizationResult schema.
```

---

**End of prompt**
```

---

## 5. **WhatIfResult** – Prompt

```
You are an engineering assistant working in the `risk_module` repository.  
Your task is to execute the **Phase 1.5 refactor** for the single result object **`WhatIfResult`**.

---

## 1. Goals

1. Replace all API-facing uses of `WhatIfResult.to_dict()` with a new, schema-compliant `to_api_response()` method.
2. Create a Marshmallow schema that matches the structure returned by `to_api_response()`.
3. Update every endpoint that returns a `WhatIfResult` so it:
   • Calls `to_api_response()`  
   • Is decorated with `@bp.response(200, WhatIfResultSchema)` (or via SuccessWrapper if that's the existing pattern).  
4. Leave internal/back-compat hooks in place (see details).

When you finish, all tests must pass and Swagger UI (`/docs/`) must generate without errors.

---

## 2. Detailed Requirements

### 2.1 Result Object Changes

File: `/Users/henrychien/Documents/Jupyter/risk_module/core/result_objects.py`

1. Locate the `WhatIfResult` class.
2. **Add** a method:
   ```python
   def to_api_response(self) -> Dict[str, Any]:
       """
       Schema-compliant version of the old to_dict().
       For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
       (no structural changes, no field renames, no pruning).
       """
       # COPY the existing to_dict() logic verbatim
   ```
3. **Deprecate** `to_dict()` but keep it temporarily:
   ```python
   def to_dict(self) -> Dict[str, Any]:
       """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
       import warnings
       warnings.warn("WhatIfResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
       return self.to_api_response()   # delegate
   ```
4. Update class docstring to note the new method.

### 2.2 Schema

1. Create file `/Users/henrychien/Documents/Jupyter/risk_module/schemas/what_if_result.py`.
2. Define a **permissive but keyed** schema so Swagger is useful yet implementation is fast:

   ```python
   from marshmallow import Schema, fields

   class WhatIfResultSchema(Schema):
       scenario_name = fields.String()
       current_metrics = fields.Dict()
       scenario_metrics = fields.Dict()
       deltas = fields.Dict()
       analysis = fields.Dict()
       factor_exposures_comparison = fields.Dict()
       summary = fields.Dict()
   ```

   (Most complex fields are left as `Dict` for now—Phase 1.6 will curate.)

3. Add an import in `/Users/henrychien/Documents/Jupyter/risk_module/schemas/__init__.py`:
   ```python
   from .what_if_result import WhatIfResultSchema
   ```

### 2.3 Endpoint Updates

Search/replace all call-sites listed in the audit:

| File | Line (audit) | Action |
|------|--------------|--------|
| `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py` | 618 | replace `result.to_dict()` → `result.to_api_response()`; add `@bp.response(200, WhatIfResultSchema)` (or wrap inside SuccessWrapper if route returns wrapper). |
| `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py` | 1048 | replace `result.to_dict()` → `result.to_api_response()`; add `@bp.response(200, WhatIfResultSchema)` (or wrap inside SuccessWrapper if route returns wrapper). |

Implementation notes:

• **Import** the new schema at the top of `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py`:
```python
from schemas import WhatIfResultSchema
```

• If the endpoint currently returns a wrapper like
```python
return {"success": True, "data": result.to_dict(), ...}
```
change only the `data` value to `result.to_api_response()`.  
Decorate with the wrapper schema if that pattern exists (`SuccessWrapperSchema`); otherwise use `WhatIfResultSchema` directly.

### 2.4 Tests & Validation

1. Run `pytest` – ensure green.
2. Manually hit `/api/what-if` (or equivalent) and confirm JSON returns identical content as before.
3. Open Swagger UI (`/docs/`) – new schema should appear in the docs without validation errors.

### 2.5 Docs

1. Add `WhatIfResultSchema` to `/Users/henrychien/Documents/Jupyter/risk_module/docs/API_REFERENCE.md` endpoint table (optional but nice).
2. No other doc work required in this PR.

---

## 3. Acceptance Criteria

• **No failing tests** (`pytest` green).  
• **Swagger UI** renders and includes `WhatIfResult` schema.  
• All `to_dict()` call-sites updated.  
• `WhatIfResult.to_dict()` emits `DeprecationWarning`.  
• New schema file and `schemas/__init__.py` updated.  
• Code style passes `pytest --flake8` (if flake8 is part of suite).  

Commit message suggestion:
```
feat(api): add to_api_response & schema for WhatIfResult

* Adds WhatIfResult.to_api_response() (1:1 with previous to_dict()).
* Deprecates WhatIfResult.to_dict().
* Introduces schemas.what_if_result.WhatIfResultSchema.
* Updates all endpoints and services to use the new method.
* Swagger UI now documents WhatIfResult schema.
```

---

**End of prompt**
```

---

## 6. **InterpretationResult** – Prompt

```
You are an engineering assistant working in the `risk_module` repository.  
Your task is to execute the **Phase 1.5 refactor** for the single result object **`InterpretationResult`**.

---

## 1. Goals

1. Replace all API-facing uses of `InterpretationResult.to_dict()` with a new, schema-compliant `to_api_response()` method.
2. Create a Marshmallow schema that matches the structure returned by `to_api_response()`.
3. Update every endpoint that returns a `InterpretationResult` so it:
   • Calls `to_api_response()`  
   • Is decorated with `@bp.response(200, InterpretationResultSchema)` (or via SuccessWrapper if that's the existing pattern).  
4. Leave internal/back-compat hooks in place (see details).

When you finish, all tests must pass and Swagger UI (`/docs/`) must generate without errors.

---

## 2. Detailed Requirements

### 2.1 Result Object Changes

File: `/Users/henrychien/Documents/Jupyter/risk_module/core/result_objects.py`

1. Locate the `InterpretationResult` class.
2. **Add** a method:
   ```python
   def to_api_response(self) -> Dict[str, Any]:
       """
       Schema-compliant version of the old to_dict().
       For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
       (no structural changes, no field renames, no pruning).
       """
       # COPY the existing to_dict() logic verbatim
   ```
3. **Deprecate** `to_dict()` but keep it temporarily:
   ```python
   def to_dict(self) -> Dict[str, Any]:
       """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
       import warnings
       warnings.warn("InterpretationResult.to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
       return self.to_api_response()   # delegate
   ```
4. Update class docstring to note the new method.

### 2.2 Schema

1. Create file `/Users/henrychien/Documents/Jupyter/risk_module/schemas/interpretation_result.py`.
2. Define a **permissive but keyed** schema so Swagger is useful yet implementation is fast:

   ```python
   from marshmallow import Schema, fields

   class InterpretationResultSchema(Schema):
       ai_interpretation = fields.String()
       full_diagnostics = fields.String()
       analysis_metadata = fields.Dict()
       analysis_date = fields.String()
       portfolio_name = fields.String(allow_none=True)
       summary = fields.Dict()
   ```

   (Most complex fields are left as `Dict` for now—Phase 1.6 will curate.)

3. Add an import in `/Users/henrychien/Documents/Jupyter/risk_module/schemas/__init__.py`:
   ```python
   from .interpretation_result import InterpretationResultSchema
   ```

### 2.3 Endpoint Updates

Search/replace all call-sites listed in the audit:

| File | Line (audit) | Action |
|------|--------------|--------|
| `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py` | 1123 | replace `result.to_dict()` → `result.to_api_response()`; add `@bp.response(200, InterpretationResultSchema)` (or wrap inside SuccessWrapper if route returns wrapper). |
| `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py` | 1198 | replace `result.to_dict()` → `result.to_api_response()`; add `@bp.response(200, InterpretationResultSchema)` (or wrap inside SuccessWrapper if route returns wrapper). |
| `/Users/henrychien/Documents/Jupyter/risk_module/services/claude/function_executor.py` | 373 | replace `result.to_dict()` → `result.to_api_response()` (no decorator change needed here). |

Implementation notes:

• **Import** the new schema at the top of `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py`:
```python
from schemas import InterpretationResultSchema
```

• If the endpoint currently returns a wrapper like
```python
return {"success": True, "data": result.to_dict(), ...}
```
change only the `data` value to `result.to_api_response()`.  
Decorate with the wrapper schema if that pattern exists (`SuccessWrapperSchema`); otherwise use `InterpretationResultSchema` directly.

### 2.4 Tests & Validation

1. Run `pytest` – ensure green.
2. Manually hit `/api/interpretation` (or equivalent) and confirm JSON returns identical content as before.
3. Open Swagger UI (`/docs/`) – new schema should appear in the docs without validation errors.

### 2.5 Docs

1. Add `InterpretationResultSchema` to `/Users/henrychien/Documents/Jupyter/risk_module/docs/API_REFERENCE.md` endpoint table (optional but nice).
2. No other doc work required in this PR.

---

## 3. Acceptance Criteria

• **No failing tests** (`pytest` green).  
• **Swagger UI** renders and includes `InterpretationResult` schema.  
• All `to_dict()` call-sites updated.  
• `InterpretationResult.to_dict()` emits `DeprecationWarning`.  
• New schema file and `schemas/__init__.py` updated.  
• Code style passes `pytest --flake8` (if flake8 is part of suite).  

Commit message suggestion:
```
feat(api): add to_api_response & schema for InterpretationResult

* Adds InterpretationResult.to_api_response() (1:1 with previous to_dict()).
* Deprecates InterpretationResult.to_dict().
* Introduces schemas.interpretation_result.InterpretationResultSchema.
* Updates all endpoints and services to use the new method.
* Swagger UI now documents InterpretationResult schema.
```

---

**End of prompt**
```

---

## 7. **Direct* Result Objects** – Prompt (batch)

```
You are an engineering assistant working in the `risk_module` repository.  
Your task is to execute the **Phase 1.5 refactor** for all six **Direct* result wrapper objects**.

---

## 1. Goals

1. Replace all API-facing uses of `Direct*.to_dict()` with new, schema-compliant `to_api_response()` methods.
2. Create Marshmallow schemas that match the structure returned by `to_api_response()`.
3. Update every endpoint that returns a `Direct*Result` so it:
   • Calls `to_api_response()`  
   • Is decorated with `@bp.response(200, Direct*ResultSchema)` (or via SuccessWrapper if that's the existing pattern).  
4. Leave internal/back-compat hooks in place (see details).

When you finish, all tests must pass and Swagger UI (`/docs/`) must generate without errors.

---

## 2. Target Classes & Schema Files

| Class | File | Schema File |
|-------|------|-------------|
| `DirectPortfolioResult` | `/Users/henrychien/Documents/Jupyter/risk_module/core/result_objects.py` | `/Users/henrychien/Documents/Jupyter/risk_module/schemas/direct_portfolio_result.py` |
| `DirectStockResult` | `/Users/henrychien/Documents/Jupyter/risk_module/core/result_objects.py` | `/Users/henrychien/Documents/Jupyter/risk_module/schemas/direct_stock_result.py` |
| `DirectOptimizationResult` | `/Users/henrychien/Documents/Jupyter/risk_module/core/result_objects.py` | `/Users/henrychien/Documents/Jupyter/risk_module/schemas/direct_optimization_result.py` |
| `DirectPerformanceResult` | `/Users/henrychien/Documents/Jupyter/risk_module/core/result_objects.py` | `/Users/henrychien/Documents/Jupyter/risk_module/schemas/direct_performance_result.py` |
| `DirectWhatIfResult` | `/Users/henrychien/Documents/Jupyter/risk_module/core/result_objects.py` | `/Users/henrychien/Documents/Jupyter/risk_module/schemas/direct_what_if_result.py` |
| `DirectInterpretResult` | `/Users/henrychien/Documents/Jupyter/risk_module/core/result_objects.py` | `/Users/henrychien/Documents/Jupyter/risk_module/schemas/direct_interpret_result.py` |

---

## 3. Detailed Requirements

### 3.1 Result Object Changes (FOR EACH CLASS)

File: `/Users/henrychien/Documents/Jupyter/risk_module/core/result_objects.py`

1. Locate each `Direct*Result` class.
2. **Add** a method to each:
   ```python
   def to_api_response(self) -> Dict[str, Any]:
       """
       Schema-compliant version of the old to_dict().
       For Phase 1.5 this must be a 1-to-1 copy of to_dict()'s output
       (no structural changes, no field renames, no pruning).
       """
       # COPY the existing to_dict() logic verbatim
   ```
3. **Deprecate** `to_dict()` but keep it temporarily:
   ```python
   def to_dict(self) -> Dict[str, Any]:
       """DEPRECATED – use to_api_response().  To be removed in Phase 2."""
       import warnings
       warnings.warn("[ClassName].to_dict() is deprecated; "
                     "use to_api_response() instead.",
                     DeprecationWarning, stacklevel=2)
       return self.to_api_response()   # delegate
   ```
4. Update class docstring to note the new method.

### 3.2 Schemas (FOR EACH CLASS)

1. Create the corresponding schema files listed above.
2. Define **permissive but keyed** schemas:

   **DirectPortfolioResultSchema:**
   ```python
   from marshmallow import Schema, fields

   class DirectPortfolioResultSchema(Schema):
       analysis_type = fields.String()
       volatility_annual = fields.Float(allow_none=True)
       portfolio_factor_betas = fields.Dict()
       risk_contributions = fields.Dict()
       df_stock_betas = fields.Dict()
       covariance_matrix = fields.Dict()
       # Include all fields from raw_output as Dict
   ```

   **DirectStockResultSchema:**
   ```python
   from marshmallow import Schema, fields

   class DirectStockResultSchema(Schema):
       analysis_type = fields.String()
       # Include all fields from raw_output as Dict
   ```

   **DirectOptimizationResultSchema:**
   ```python
   from marshmallow import Schema, fields

   class DirectOptimizationResultSchema(Schema):
       analysis_type = fields.String()
       optimal_weights = fields.Dict()
       optimization_metrics = fields.Dict()
       # Include all fields from raw_output as Dict
   ```

   **DirectPerformanceResultSchema:**
   ```python
   from marshmallow import Schema, fields

   class DirectPerformanceResultSchema(Schema):
       analysis_type = fields.String()
       performance_metrics = fields.Dict()
       # Include all fields from raw_output as Dict
   ```

   **DirectWhatIfResultSchema:**
   ```python
   from marshmallow import Schema, fields

   class DirectWhatIfResultSchema(Schema):
       analysis_type = fields.String()
       current_scenario = fields.Dict()
       what_if_scenario = fields.Dict()
       comparison_metrics = fields.Dict()
       # Include all fields from raw_output as Dict
   ```

   **DirectInterpretResultSchema:**
   ```python
   from marshmallow import Schema, fields

   class DirectInterpretResultSchema(Schema):
       analysis_type = fields.String()
       ai_interpretation = fields.String()
       full_diagnostics = fields.String()
       analysis_metadata = fields.Dict()
       # Include all fields from raw_output as Dict
   ```

3. Add imports in `/Users/henrychien/Documents/Jupyter/risk_module/schemas/__init__.py`:
   ```python
   from .direct_portfolio_result import DirectPortfolioResultSchema
   from .direct_stock_result import DirectStockResultSchema
   from .direct_optimization_result import DirectOptimizationResultSchema
   from .direct_performance_result import DirectPerformanceResultSchema
   from .direct_what_if_result import DirectWhatIfResultSchema
   from .direct_interpret_result import DirectInterpretResultSchema
   ```

### 3.3 Endpoint Updates

Search `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py` for direct endpoints:

| File | Line (audit) | Action |
|------|--------------|--------|
| `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py` | 729 | replace `result.to_dict()` → `result.to_api_response()`; add appropriate schema decorator. |

Implementation notes:

• **Import** the new schemas at the top of `/Users/henrychien/Documents/Jupyter/risk_module/routes/api.py`:
```python
from schemas import (DirectPortfolioResultSchema, DirectStockResultSchema, 
                     DirectOptimizationResultSchema, DirectPerformanceResultSchema,
                     DirectWhatIfResultSchema, DirectInterpretResultSchema)
```

• Find all endpoints that contain `/direct/` in their routes and update them to use `to_api_response()` and appropriate schema decorators.

### 3.4 Tests & Validation

1. Run `pytest` – ensure green.
2. Manually hit direct endpoints and confirm JSON returns identical content as before.
3. Open Swagger UI (`/docs/`) – new schemas should appear in the docs without validation errors.

### 3.5 Docs

1. Add Direct*ResultSchemas to `/Users/henrychien/Documents/Jupyter/risk_module/docs/API_REFERENCE.md` endpoint table (optional but nice).
2. No other doc work required in this PR.

---

## 4. Acceptance Criteria

• **No failing tests** (`pytest` green).  
• **Swagger UI** renders and includes all Direct* schemas.  
• All `to_dict()` call-sites updated.  
• All `Direct*.to_dict()` methods emit `DeprecationWarning`.  
• New schema files and `schemas/__init__.py` updated.  
• Code style passes `pytest --flake8` (if flake8 is part of suite).  

Commit message suggestion:
```
feat(api): add to_api_response & schemas for Direct* result wrappers

* Adds to_api_response() methods for all Direct* result classes (1:1 with previous to_dict()).
* Deprecates all Direct*.to_dict() methods.
* Introduces schemas for DirectPortfolioResult, DirectStockResult, DirectOptimizationResult, 
  DirectPerformanceResult, DirectWhatIfResult, and DirectInterpretResult.
* Updates all direct endpoints to use the new methods.
* Swagger UI now documents all Direct* result schemas.
```

---

**End of prompt**
```

---

### ✅ After each refactor
* Verify `pytest` & Swagger UI.
* Grep the repo for lingering `to_dict()` calls of that class.
* Merge and move to the next prompt.

Happy refactoring!  🎉
