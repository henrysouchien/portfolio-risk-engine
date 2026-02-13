# OpenAPI Migration Plan

*Author: Engineering Team*
*Date: 2025-08-04*

---

## Objective

Replace hand-written TypeScript interfaces and drifting Markdown docs with an **auto-generated, single-source API contract** powered by OpenAPI 3.0. This guarantees that backend responses, interactive docs, and frontend typings stay in perfect sync.

---

## Technology Stack

| Layer        | Choice                      | Reason |
|--------------|-----------------------------|--------|
| Flask ↔ Spec | **flask-smorest** + Marshmallow | Lightweight, decorator-based, good with dataclasses |
| Spec Format  | OpenAPI 3.0.3 (JSON/YAML)   | Industry standard |
| Front-end TS | **openapi-typescript**      | Simple CLI, produces `paths` namespace with in-place typings |
| Docs UI      | Swagger-UI (auto-served by flask-smorest) | Zero config |

*Pydantic + `flask-openapi3` is an easy swap if dataclass → Pydantic conversion becomes desirable later.*

---

## Roll-out Phases & Timeline

| Phase | Description | Target Duration |
|-------|-------------|-----------------|
| 0 | **Preparation** – install deps, create feature branch | ½ day |
| 0.5 | **Result Object Alignment Audit** – fix core function → result object data flow | 1 day |
| 1 | **Backend Scaffold** – spec config, base schemas, annotate one endpoint | 1 day |
| 1.5 | **Result Object Refactoring** – add `to_api_response()` methods, create detailed schemas | 1–1.5 days |
| 1.6 | **Schema Evolution** – refine schemas from permissive to curated, optimize for frontend | 1–2 days |
| 2 | **OpenAPI Integration** – flask-smorest decorators, full route coverage | 2–3 days |
| 2.5 | **Frontend Pipeline Integrity Audit** – validate data flow from API to components | ½ day |
| 3a | **Frontend Type Migration** – mechanical import swaps, no logic changes | ½ day |
| 3b | **Frontend Data Enhancement** – extend adapters/components for new data (optional) | 1 day |
| 3c | **Type Generation Automation** – scripts and npm integration | ½ day |
| 4 | **CI Gate & Clean-up** – automated validation, delete obsolete types | ½ day |
| 5 | **Team Adoption & Docs** – dev guide, code owners, retro | ½ day |

Total ≈ **8–9.5 dev days**.

---

## Detailed Task Breakdown

### Phase 0 – Preparation
1. `pip install flask-smorest marshmallow`
2. `npm i -D openapi-typescript`
3. Branch: `feat/openapi-scaffold`

### Phase 0.5 – Result Object Alignment Audit (CRITICAL PRE-STEP)
**MUST COMPLETE BEFORE SCHEMA WORK**: Ensure result objects capture all data from core functions.

1. **Audit Core Function → Result Object Data Flow**:
   ```python
   # CURRENT PROBLEM: Data being lost in translation
   
   # run_risk_score_analysis() returns:
   {
       "risk_score": {...},
       "limits_analysis": {...},
       "portfolio_analysis": {...},
       "suggested_limits": {...},        # ← LOST!
       "analysis_date": "2024-01-15",    # ← REPLACED with datetime.now()!
       "portfolio_file": "portfolio.yaml", # ← LOST!
       "formatted_report": "..."         # ← LOST!
   }
   
   # RiskScoreResult.from_risk_score_analysis() only captures:
   {
       "risk_score": {...},      # ✅ 
       "limits_analysis": {...}, # ✅
       "portfolio_analysis": {...}, # ✅
       # Missing: suggested_limits, original analysis_date, portfolio_file, formatted_report
   }
   ```

2. **Fix Result Object Factory Methods**:
   ```python
   # Fix RiskScoreResult.from_risk_score_analysis() 
   @classmethod
   def from_risk_score_analysis(cls, risk_score_result: Dict[str, Any],
                               portfolio_name: Optional[str] = None) -> 'RiskScoreResult':
       return cls(
           risk_score=risk_score_result["risk_score"],
           limits_analysis=risk_score_result["limits_analysis"],
           portfolio_analysis=risk_score_result["portfolio_analysis"],
           suggested_limits=risk_score_result.get("suggested_limits", {}),  # ← CAPTURE!
           analysis_date=datetime.fromisoformat(risk_score_result["analysis_date"]), # ← USE ORIGINAL!
           portfolio_file=risk_score_result.get("portfolio_file"),         # ← CAPTURE!
           formatted_report=risk_score_result.get("formatted_report", ""), # ← CAPTURE!
           portfolio_name=portfolio_name
       )
   ```

3. **Audit All Result Objects**:
   - **RiskScoreResult** ← `run_risk_score_analysis()`
   - **RiskAnalysisResult** ← `build_portfolio_view()` 
   - **PerformanceResult** ← `run_portfolio_performance()`
   - **WhatIfResult** ← `run_what_if()`
   - **OptimizationResult** ← `run_min_variance()`, `run_max_return()`

4. **Add Missing Fields to Result Object Classes**:
   ```python
   @dataclass
   class RiskScoreResult:
       risk_score: Dict[str, Any]
       limits_analysis: Dict[str, Any] 
       portfolio_analysis: Dict[str, Any]
       suggested_limits: Dict[str, Any]  # ← ADD MISSING FIELD
       portfolio_file: Optional[str]     # ← ADD MISSING FIELD
       formatted_report: str             # ← ADD MISSING FIELD
       analysis_date: datetime
       portfolio_name: Optional[str] = None
   ```

5. **Validate Data Completeness**: Ensure no data from core functions is lost in result objects.

6. **📝 Update Documentation**:
   - Document findings in `docs/RESULT_OBJECT_AUDIT_REPORT.md`
   - Update `core/result_objects.py` docstrings with complete field mappings
   - Add data flow diagrams to `docs/BACKEND_ARCHITECTURE.md` 
   - Note any breaking changes in `CHANGELOG.md`

### Phase 1 – Backend Scaffold
1. **Configure smorest** in `app.py` (or `api_spec.py`):
   ```python
   from flask_smorest import Api
   app.config.update(
       API_TITLE='Risk Module API',
       API_VERSION='3.1',
       OPENAPI_VERSION='3.0.3',
       OPENAPI_URL_PREFIX='/docs',
       OPENAPI_SWAGGER_UI_PATH='/',
       OPENAPI_SWAGGER_UI_URL='https://cdn.jsdelivr.net/npm/swagger-ui-dist/'
   )
   api = Api(app)
   ```
2. **Base wrapper schemas** (`schemas/common.py`):
   ```python
   class SuccessWrapper(Schema):
       success  = fields.Boolean(required=True, example=True)
       data     = fields.Dict(required=True)
       summary  = fields.Raw()
       endpoint = fields.String()

   class ErrorWrapper(Schema):
       success    = fields.Boolean(required=True, example=False)
       error      = fields.String()
       error_code = fields.String()
       message    = fields.String()
       details    = fields.Dict()
       timestamp  = fields.DateTime()
   ```
3. **Annotate pilot endpoint** (`/api/performance`):
   ```python
   from schemas.performance import PerformanceMetricsSchema
   @bp.arguments(PerformanceRequestSchema)
   @bp.response(200, SuccessWrapper)
   def api_performance(args):
       ...
       return {
           "success": True,
           "data": result.to_dict(),
           "summary": result.get_summary(),
           "endpoint": "performance"
       }
   ```
4. Verify: visit `http://localhost:5001/docs/` – Swagger UI appears.

5. **📝 Update Documentation**:
   - Update `docs/API_REFERENCE.md` with OpenAPI setup instructions
   - Document schema design patterns in `docs/OPENAPI_SCHEMA_GUIDE.md`
   - Add base configuration examples to `README.md`

### Phase 1.5 – Result Object Refactoring (NEW)
**CRITICAL**: Refactor result objects to work with schemas before Phase 2.

1. **Refactor result objects to use schema-compliant methods** (`core/result_objects.py`):

Refactor all result objects: replace to_dict() methods with to_api_response() methods that return a schema-compliant structure (1:1 mapping, no structural changes yet).

Example:

Replace this:

   ```python
   class RiskScoreResult:
       def to_dict(self) -> Dict[str, Any]:
           # existing implementation
       
With this:
       def to_api_response(self) -> Dict[str, Any]:
           """Schema-compliant API response"""
           return {
               "risk_score": {
                   "score": self.get_overall_score(),
                   "category": self.get_risk_category(),
                   "component_scores": self._get_component_scores_dict()
               },
               "limits_analysis": {
                   "risk_factors": self.get_risk_factors(),
                   "recommendations": self.get_recommendations(),
                   "violations_count": len(self.get_risk_factors()),
                   "compliance_status": self.is_compliant()
               },
               "analysis_date": self.analysis_date.isoformat()
           }
   ```

2. **Create detailed schemas that match result object structure** (`schemas/risk_score.py`):
   ```python
   class RiskScoreDataSchema(Schema):
       score = fields.Integer(validate=Range(min=0, max=100))
       category = fields.String(validate=OneOf(['EXCELLENT', 'GOOD', 'MODERATE', 'POOR']))
       component_scores = fields.Dict(keys=fields.String(), values=fields.Integer())
   
   class RiskScoreResponseSchema(SuccessWrapperSchema):
       risk_score = fields.Nested(RiskScoreDataSchema)
       limits_analysis = fields.Nested(LimitsAnalysisSchema)
       analysis_date = fields.DateTime(format='iso')
   ```

3. **Update endpoints to use schema-compliant methods**:
Refactor all usages of to_dict() in API-facing code to use to_api_response()

   ```python
   # Replace: result.to_dict()
   # With:    result.to_api_response()
   ```
   
4. **📝 Update Documentation**:
   - Document new `to_api_response()` patterns in `core/result_objects.py` docstrings
   - Update `docs/OPENAPI_SCHEMA_GUIDE.md` with result object schema mapping examples
   - Add migration notes to `CHANGELOG.md` for any breaking changes

### Phase 1.6 – Schema Evolution 
**CRITICAL**: Transform permissive schemas into structured, well-documented schemas for meaningful OpenAPI documentation.

**Status**: Ready to begin after Phase 1.5 completion.

#### Phase 1.6A: Data Structure Audit & Completeness Validation
**Goal**: Understand what's inside the `fields.Dict()` containers using CLI output as ground truth, while auditing Phase 1.5 completeness.

1. **Sample Real API Responses**:
   ```python
   # Create script to sample actual data from each result object
   from core.result_objects import *
   
   # For each result object, capture real to_api_response() output
   # Document actual keys, types, nesting patterns
   # Identify shared structures across objects
   ```

2. **Analyze CLI Output Formatting**:
   ```python
   # Cross-reference with CLI display functions
   # Examine how each result object formats data for human consumption
   # Map CLI table structures → potential nested schemas
   # Identify field prioritization (what gets displayed vs. hidden)
   ```
   
   **Key CLI Analysis Questions**:
   - How does the CLI organize/group related fields into sections?
   - Which fields are displayed prominently vs. buried in details?
   - What formatting hints reveal data structure (percentages, dates, tables)?
   - How are nested relationships presented (parent-child, grouped sections)?

3. **Cross-Reference Data + Display**:
   - **Raw data structure**: `performance_result.to_api_response()['returns']` 
   - **CLI presentation**: How `run_performance()` displays returns data
   - **Schema design**: Combine both to create optimal nested structure
   - **Field importance**: CLI prominence indicates frontend priority

4. **Create Comprehensive Data Structure Inventory**:
   ```markdown
   ## PerformanceResult Schema Design
   
   ### Raw Data Analysis:
   - `analysis_period` → `{years: 2.5, start_date: '2022-01-01', end_date: '2024-06-30'}`
   - `returns` → `{total_return: 0.245, annualized_return: 0.098, win_rate: 0.67}`
   
   ### CLI Display Analysis:
   - Returns section shows: "Total Return: 24.50% | Annualized: 9.80% | Win Rate: 67%"
   - Suggests ReturnsSchema with clear field names and percentage formatting hints
   
   ### Recommended Schema Structure:
   class ReturnsSchema(Schema):
       total_return = fields.Float(metadata={'format': 'percentage'})
       annualized_return = fields.Float(metadata={'format': 'percentage'})  
       win_rate = fields.Float(metadata={'format': 'percentage'})
   ```

5. **Phase 1.5 Completeness Audit**:
   ```python
   # Use CLI functions as ground truth for completeness validation
   # CLI outputs represent complete analysis data from core business functions
   ```
   
   **Audit Questions**:
   - **Coverage Check**: Do we have result objects for every CLI analysis function?
   - **Field Completeness**: Does `result.to_api_response()` include every field the CLI displays?
   - **Data Structure Match**: Do our result object fields match CLI organization/grouping?
   - **Missing Objects**: Are there CLI functions that don't correspond to migrated result objects?
   
   **Systematic CLI Audit Process**:
   ```python
   # For each core analysis function:
   # 1. Run CLI version: run_portfolio_analysis(), run_performance(), etc.
   # 2. Catalog ALL output fields/sections shown
   # 3. Compare with result.to_api_response() output
   # 4. Flag discrepancies:
   #    - CLI shows field X, API response missing field X → Add to result object
   #    - CLI groups fields A,B,C together → Should be nested schema
   #    - CLI formats as percentage → Add metadata hint
   #    - CLI function exists but no result object → Missing migration
   ```

6. **Gap Analysis & Remediation**:
   - **Missing Result Objects**: Create and migrate any CLI functions without corresponding result objects
   - **Incomplete Data**: Add missing fields to existing `to_api_response()` methods
   - **Structure Mismatches**: Reorganize result object data to match CLI groupings
   - **Type Inconsistencies**: Align data types with CLI formatting expectations

7. **Identify Schema Design Patterns**:
   - **Common CLI sections** → Shared component schemas
   - **Repeated formatting patterns** → Standard field metadata
   - **Display groupings** → Natural nested schema boundaries
   - **Field prioritization** → Required vs. optional field distinctions
   - **CLI organization** → Optimal nested schema hierarchy

#### Phase 1.6B: Schema Design
**Goal**: Design the nested schema architecture and shared components.

1. **Create Shared Component Schemas**:
   ```python
   # Design reusable schemas first
   class AnalysisPeriodSchema(Schema):
       years = fields.Float()
       start_date = fields.String()
       end_date = fields.String()
   
   class ReturnsSchema(Schema):
       total_return = fields.Float()
       annualized_return = fields.Float()
       win_rate = fields.Float()
   ```

2. **Plan Schema Hierarchy**:
   - Identify which schemas can be shared across result objects
   - Design inheritance/composition patterns
   - Prioritize simple → complex objects for implementation

3. **Validate Against Frontend Usage**:
   - Cross-reference with current TypeScript interfaces
   - Ensure new schemas cover all frontend data access patterns
   - Plan any frontend adaptation needed

#### Phase 1.6C: Schema Implementation  
**Goal**: Replace permissive `fields.Dict()` with structured `fields.Nested()` schemas.

1. **Pilot Implementation**:
   ```python
   # BEFORE: Permissive schema (Phase 1.5)
   class PerformanceResultSchema(Schema):
       analysis_period = fields.Dict()      # Generic dict
       returns = fields.Dict()              # No structure info
       
   # AFTER: Structured schema (Phase 1.6C)
   class PerformanceResultSchema(Schema):
       analysis_period = fields.Nested(AnalysisPeriodSchema)  # Structured!
       returns = fields.Nested(ReturnsSchema)                 # Documented!
   ```

2. **Systematic Migration**:
   - Start with `PerformanceResult` (well-structured, good pilot candidate)
   - Validate each migration with real data
   - Scale successful patterns to remaining objects
   - Test OpenAPI doc generation at each step

#### Phase 1.6D: Schema Deduplication
**Goal**: Eliminate Direct* schema duplication via inheritance/composition.

1. **Implement Schema Inheritance**:
   ```python
   # BEFORE: Duplicated schemas
   class OptimizationResultSchema(Schema):
       optimized_weights = fields.Dict()
       optimization_type = fields.String()
       # ... 8 more fields
       
   class DirectOptimizationResultSchema(Schema):
       analysis_type = fields.String()
       optimized_weights = fields.Dict()    # Duplicated!
       optimization_type = fields.String()  # Duplicated!
       # ... 8 more duplicated fields
       
   # AFTER: Clean inheritance  
   class DirectOptimizationResultSchema(OptimizationResultSchema):
       analysis_type = fields.String()
       # Inherits all other fields automatically
   ```

2. **Validate Schema Reuse**:
   - Ensure inheritance doesn't break existing API responses
   - Test that OpenAPI generation works correctly
   - Verify frontend compatibility

**Acceptance Criteria for Phase 1.6**:
- [ ] All `fields.Dict()` replaced with structured nested schemas
- [ ] Shared component schemas created and reused  
- [ ] Direct* schema duplication eliminated
- [ ] OpenAPI documentation shows meaningful field structure
- [ ] All existing API responses still work correctly
- [ ] Frontend can consume new structured data

#### Phase 1.6 → Phase 2 Transition
After Phase 1.6 completion:
- All schemas are structured and well-documented
- OpenAPI spec generation will show meaningful field definitions  
- Phase 2 decorator additions will create truly useful API documentation

---

2. **Design Curated Schema Architecture** (LEGACY - replaced by 1.6A-D above):
   ```python
   # BEFORE: Permissive schema (Phase 1.5)
   class RiskScoreResponseSchema(SuccessWrapperSchema):
       risk_score = fields.Dict()           # Accepts anything
       limits_analysis = fields.Dict()      # Accepts anything
   
   # AFTER: Curated schema (Phase 1.6)
   class RiskScoreResponseSchema(SuccessWrapperSchema):
       # Flatten for frontend consumption
       overall_risk_score = fields.Integer(validate=Range(min=0, max=100))
       risk_category = fields.String(validate=OneOf(['EXCELLENT', 'GOOD', 'MODERATE', 'POOR']))
       
       # Standardized financial data structures
       risk_factors = fields.List(fields.Nested(RiskFactorSchema))
       correlation_matrix = fields.Nested(CorrelationMatrixSchema)
       performance_metrics = fields.Nested(PerformanceMetricsSchema)  
       
       # Business-focused groupings
       recommendations = fields.List(fields.String())
       analysis_metadata = fields.Nested(AnalysisMetadataSchema)
   ```

3. **Create Standardized Financial Schemas** (`schemas/financial_common.py`):
   ```python
   class CorrelationMatrixSchema(Schema):
       """Standardized correlation matrix format"""
       matrix = fields.Dict(keys=fields.String(), values=fields.Dict())
       symbols = fields.List(fields.String())
       
   class PerformanceMetricsSchema(Schema):
       """Standardized performance metrics"""
       annual_return = fields.Float()
       volatility = fields.Float() 
       sharpe_ratio = fields.Float()
       max_drawdown = fields.Float()
       
   class HoldingSchema(Schema):
       """Standardized holding representation"""
       ticker = fields.String(required=True)
       weight = fields.Float(validate=Range(min=0, max=1))
       value = fields.Float(validate=Range(min=0))
       sector = fields.String(allow_none=True)
       
   class RiskContributionSchema(Schema):
       """Top risk contributors format"""
       ticker = fields.String()
       contribution = fields.Float()
       percentage = fields.Float()
   ```

4. **Update Result Object Methods for Curated Output**:
   ```python
   def to_api_response(self) -> Dict[str, Any]:
       """Curated, frontend-optimized response"""
       return {
           # Flatten key metrics to top level
           "overall_risk_score": self.get_overall_score(),
           "risk_category": self.get_risk_category(),
           
           # Use standardized structures for complex data
           "risk_factors": self._format_risk_factors(),
           "correlation_matrix": self._format_correlation_matrix(),
           "top_risk_contributors": self._get_top_contributors(5),
           
           # Group related business data
           "recommendations": self.get_recommendations(),
           "analysis_metadata": {
               "analysis_date": self.analysis_date.isoformat(),
               "portfolio_file": self.portfolio_file,
               "portfolio_name": self.portfolio_name
           }
       }
       
   def _format_risk_factors(self) -> List[Dict[str, Any]]:
       """Convert risk factors to standardized format"""
       return [
           {
               "factor": factor,
               "severity": severity,
               "description": description,
               "recommendation": recommendation
           }
           for factor, severity, description, recommendation in self.get_risk_factors()
       ]
   
   def _format_correlation_matrix(self) -> Dict[str, Any]:
       """Convert correlation matrix to standardized format"""
       if self.correlation_matrix.empty:
           return {"matrix": {}, "symbols": []}
           
       symbols = list(self.correlation_matrix.columns)
       matrix = {}
       for symbol in symbols:
           matrix[symbol] = self.correlation_matrix[symbol].to_dict()
           
       return {"matrix": matrix, "symbols": symbols}
   ```

5. **Schema Design Philosophy - Apply These Principles**:
   - **Flatten business complexity**: Remove unnecessary nesting that serves no frontend purpose
   - **Standardize financial structures**: Reusable schemas for correlation matrices, performance metrics, holdings
   - **Preserve semantic meaning**: Don't flatten so much that you lose data relationships
   - **Frontend-first design**: Structure data for easy consumption by React components
   - **Type safety focus**: Strong TypeScript types from well-defined schemas

6. **Migration Strategy**:
   ```python
   # Keep both methods during transition
   def to_dict(self) -> Dict[str, Any]:
       """Legacy method for backward compatibility"""
       # existing implementation
   
   def to_api_response(self) -> Dict[str, Any]:
       """New curated method for OpenAPI"""
       # curated implementation
   ```

7. **Frontend Benefits After Schema Evolution**:
   - **Better TypeScript types**: Specific field types instead of `Dict` 
   - **Easier component development**: Flattened structure, no deep nesting
   - **Consistent patterns**: Same correlation matrix format across all endpoints
   - **Reduced adapter complexity**: Less transformation needed in frontend adapters
   - **Better developer experience**: Autocomplete, error detection, refactoring support

8. **📝 Update Documentation**:
   - Document curated schema patterns in `docs/OPENAPI_SCHEMA_GUIDE.md`
   - Create schema design principles guide
   - Update result object documentation with both legacy and curated methods
   - Add frontend-backend data contract documentation

### Phase 2 – OpenAPI Integration & Full Route Coverage
Transform Flask routes to use OpenAPI decorators and schema validation.

1. **Start with pilot endpoint** (`/api/risk-score`):
   ```python
   # BEFORE: Basic Flask route
   @api_bp.route("/risk-score", methods=["POST"])
   def api_risk_score():
       result = portfolio_service.analyze_risk_score(portfolio_data)
       return jsonify({'success': True, **result.to_dict()})

   # AFTER: OpenAPI-integrated route
   from schemas.risk_score import RiskScoreRequestSchema, RiskScoreResponseSchema
   
   @api_bp.route("/risk-score", methods=["POST"])
   @bp.arguments(RiskScoreRequestSchema)           # ← Request validation
   @bp.response(200, RiskScoreResponseSchema)      # ← Response contract  
   @bp.alt_response(400, ErrorResponseSchema)      # ← Error handling
   def api_risk_score(args):
       result = portfolio_service.analyze_risk_score(portfolio_data)
       return {'success': True, **result.to_api_response()}  # ← Schema-compliant!
   ```

2. **Configure flask-smorest in app.py**:
   ```python
   from flask_smorest import Api
   
   app.config.update(
       API_TITLE='Risk Module API',
       API_VERSION='3.1', 
       OPENAPI_VERSION='3.0.3',
       OPENAPI_URL_PREFIX='/docs',
       OPENAPI_SWAGGER_UI_PATH='/',
   )
   
   api = Api(app)
   api.register_blueprint(api_bp)
   ```

3. **Test OpenAPI generation**: Visit `http://localhost:5001/docs/` → Swagger UI appears!

4. **Scale to all endpoints**:
   - `/api/portfolio-analysis` 
   - `/api/performance`
   - `/api/portfolios/*` (CRUD operations)
   - All remaining routes in `routes/api.py`, `routes/admin.py`

5. **For each endpoint**:
   - Add `@bp.arguments()` for request body validation
   - Add `@bp.response()` for success response schema
   - Add `@bp.alt_response()` for error responses  
   - Replace `result.to_dict()` with `result.to_api_response()`

6. **Validate**: `http://localhost:5001/docs/openapi.json` contains complete API contract

7. **📝 Update Documentation**:
   - Update `docs/API_REFERENCE.md` with complete OpenAPI endpoint documentation
   - Create `docs/DEVELOPER_WORKFLOW.md` - how to add new API endpoints with OpenAPI
   - Document request/response patterns in `docs/OPENAPI_SCHEMA_GUIDE.md`
   - Add OpenAPI validation to development checklist

### Phase 2.5 – Frontend Data Pipeline Integrity Audit
**VALIDATION**: Ensure frontend data flow works correctly before applying strict types.

1. **Create audit script** (`scripts/audit_frontend_pipeline.js`):
   ```javascript
   // Audit script to validate data flow from API → Service → Adapter → Hook → Component
   const auditDataPipeline = async (portfolioId) => {
     console.log("=== FRONTEND PIPELINE INTEGRITY AUDIT ===");
     
     try {
       // Step 1: Capture raw API response
       const apiResponse = await RiskAnalysisService.getRiskScore(portfolioId);
       const apiFields = Object.keys(apiResponse);
       console.log("📡 API Response fields:", apiFields);
       
       // Step 2: Check adapter transformation
       const adapterOutput = RiskScoreAdapter.transform(apiResponse);
       const transformedFields = Object.keys(adapterOutput);
       console.log("🔄 Adapter output fields:", transformedFields);
       
       // Step 3: Validate hook data management
       const { data: hookData } = useRiskScore(portfolioId);
       const hookFields = hookData ? Object.keys(hookData) : [];
       console.log("🪝 Hook provides fields:", hookFields);
       
       // Step 4: Check for data loss or mismatches
       auditFieldMappings(apiResponse, adapterOutput);
       auditDataTypes(adapterOutput);
       auditMissingFields(transformedFields);
       
     } catch (error) {
       console.error("🔥 PIPELINE FAILURE:", error.message);
     }
   };
   
   const auditFieldMappings = (apiData, transformedData) => {
     // Check for common field mapping issues
     if (apiData.risk_score && !transformedData.overall_risk_score) {
       console.warn("🔥 Field mapping issue: risk_score not transformed");
     }
     if (apiData.limits_analysis && !transformedData.risk_factors) {
       console.warn("🔥 Field mapping issue: limits_analysis not transformed");
     }
   };
   
   const auditDataTypes = (data) => {
     // Check for type mismatches that would break with strict types
     if (data.risk_factors && !Array.isArray(data.risk_factors)) {
       console.warn("🔥 Type mismatch: risk_factors should be array");
     }
   };
   ```

2. **Run audit on each major data flow**:
   - Risk Score: API → RiskAnalysisService → RiskScoreAdapter → useRiskScore hook
   - Portfolio Analysis: API → PortfolioService → PortfolioAdapter → usePortfolioAnalysis hook  
   - Performance: API → PerformanceService → PerformanceAdapter → usePerformance hook

3. **Document findings and fix issues**:
   ```bash
   # Create audit report
   npm run audit:frontend-pipeline > frontend_pipeline_audit.md
   
   # Fix any field mapping bugs, type mismatches, or data loss
   # Update adapters to handle missing fields gracefully
   # Ensure hooks properly manage transformed data
   ```

4. **Validate clean pipeline**: All audits pass without warnings before proceeding to type migration

5. **📝 Update Documentation**:
   - Save audit report as `docs/FRONTEND_PIPELINE_AUDIT_REPORT.md`
   - Document data flow architecture in `docs/FRONTEND_ARCHITECTURE.md`
   - Update adapter patterns documentation with any fixes made
   - Add pipeline validation to frontend development checklist

### Phase 3a – Frontend Type Reference Migration
**MECHANICAL**: Replace manual type definitions with OpenAPI-generated types (no logic changes).

1. **Create type alias bridge** (`frontend/src/types/api.ts`):
   ```typescript
   import type { paths } from '../apiTypes';
   
   // Map existing interface names to OpenAPI types  
   export type RiskScoreResponse = 
     paths['/api/risk-score']['post']['responses']['200']['content']['application/json'];
   
   export type PortfolioAnalysisResponse = 
     paths['/api/portfolio-analysis']['post']['responses']['200']['content']['application/json'];
   ```

2. **Update service layer imports** (logic stays identical):
   ```typescript
   // BEFORE
   import { RiskScoreResponse } from '../chassis/types';
   
   // AFTER  
   import { RiskScoreResponse } from '../../types/api';
   
   // Method implementation stays EXACTLY the same
   async getRiskScore(): Promise<RiskScoreResponse> {
     // ... identical logic, better types
   }
   ```

3. **Update adapter imports** (transformation logic unchanged):
   ```typescript
   // BEFORE
   interface RiskScoreApiResponse { ... }
   
   // AFTER
   import type { RiskScoreResponse as RiskScoreApiResponse } from '../types/api';
   
   // Transform method stays identical:
   static transform(apiResponse: RiskScoreApiResponse) {
     // ... same transformation logic
   }
   ```

4. **Systematic import replacement**:
   ```bash
   # Find/replace imports across codebase
   find frontend/src -name "*.ts" -o -name "*.tsx" | \
     xargs sed -i 's|from '\''../chassis/types'\''|from '\''../types/api'\''|g'
   ```

5. **Remove old manual type definitions** from `chassis/types/index.ts`

6. **Test type alignment**: `npm run type-check` should pass with better type safety

7. **📝 Update Documentation**:
   - Document type alias bridge pattern in `docs/FRONTEND_ARCHITECTURE.md`
   - Update `frontend/README.md` with new import conventions
   - Add TypeScript migration notes to `CHANGELOG.md`
   - Create type generation workflow documentation

### Phase 3b – Frontend Data Enhancement (Optional)
**FUNCTIONAL**: Extend adapters and components to use additional data from Phase 0.5 alignment.

1. **Extend adapters to use new data fields**:
   ```typescript
   // frontend/src/adapters/RiskScoreAdapter.ts
   static transform(apiResponse: RiskScoreResponse) {
     return {
       // Existing transformations (unchanged)
       overall_risk_score: apiResponse.risk_score?.score || 0,
       component_scores: [...],
       risk_factors: apiResponse.limits_analysis?.risk_factors || [],
       
       // NEW: Use additional data from Phase 0.5 alignment
       suggested_limits: apiResponse.suggested_limits || {},           // ← NEW!
       portfolio_file: apiResponse.portfolio_file || '',              // ← NEW!
       formatted_report: apiResponse.formatted_report || '',          // ← NEW!
       analysis_timestamp: apiResponse.analysis_date || '',           // ← NEW!
       
       // Enhanced existing data
       recommendations: [
         ...apiResponse.limits_analysis?.recommendations || [],
         ...this.extractSuggestionsFromLimits(apiResponse.suggested_limits)
       ]
     };
   }
   ```

2. **Enhance components to display richer information**:
   ```typescript
   const RiskScoreDisplay = ({ riskData }) => {
     const { 
       overall_risk_score, 
       suggested_limits,     // ← NEW data available!
       portfolio_file,       // ← NEW metadata available!
       analysis_timestamp    // ← Accurate timestamp!
     } = riskData;

     return (
       <div>
         <h2>Risk Score: {overall_risk_score}</h2>
         
         {/* NEW: Show suggested limits */}
         {Object.keys(suggested_limits).length > 0 && (
           <SuggestedLimitsSection limits={suggested_limits} />
         )}
         
         {/* NEW: Show analysis metadata */}
         <AnalysisMetadata 
           portfolioFile={portfolio_file}
           timestamp={analysis_timestamp}
         />
       </div>
     );
   };
   ```

3. **Add new features using previously unavailable data**:
   - Risk limit recommendations dashboard
   - Analysis history tracking  
   - Portfolio file source indicators
   - Detailed formatted reports display

### Phase 3c – Type Generation Automation
**TOOLING**: Automate OpenAPI type generation and validation.

1. **Create type generation script** (`scripts/gen_api_types.sh`):
   ```bash
   #!/bin/bash
   echo "🚀 Generating TypeScript types from OpenAPI spec..."
   
   # Fetch latest OpenAPI spec from running backend
   curl -s http://localhost:5001/docs/openapi.json > openapi.json
   
   # Generate TypeScript types
   npx openapi-typescript openapi.json \
       --output frontend/src/apiTypes.ts \
       --export-type
   
   echo "✅ Types generated at frontend/src/apiTypes.ts"
   ```

2. **Add npm script integration** (package.json):
   ```json
   {
     "scripts": {
       "gen:api-types": "./scripts/gen_api_types.sh",
       "dev": "npm run gen:api-types && react-scripts start",
       "type-check": "npm run gen:api-types && tsc --noEmit"
     }
   }
   ```

3. **Test automated type generation**: Verify types update when backend schemas change

4. **📝 Update Documentation**:
   - Document type generation workflow in `docs/DEVELOPER_WORKFLOW.md`
   - Update `frontend/README.md` with npm script usage
   - Add automation setup to development environment guide
   - Create troubleshooting guide for type generation issues

### Phase 4 – CI/CD Integration & Clean-up
Automate validation and clean up old manual type definitions.

1. **Add GitHub Actions validation** (`.github/workflows/api-validation.yml`):
   ```yaml
   name: API Contract Validation
   
   on: [push, pull_request]
   
   jobs:
     validate-api-types:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v3
         
         - name: Setup Node.js
           uses: actions/setup-node@v3
           with:
             node-version: '18'
             
         - name: Install dependencies
           run: npm ci
           
         - name: Start backend for OpenAPI generation
           run: |
             python -m venv venv
             source venv/bin/activate
             pip install -r requirements.txt
             python app.py &
             sleep 10  # Wait for server to start
             
         - name: Generate API types and check for drift
           run: |
             npm run gen:api-types
             git diff --exit-code frontend/src/apiTypes.ts
           env:
             # Fail if generated types differ from committed types
             CI: true
   ```

2. **Clean up old manual types**:
   ```bash
   # Delete redundant files
   rm frontend/src/types/RiskScoreResponse.ts
   rm frontend/src/types/PerformanceResponse.ts
   rm frontend/src/types/PortfolioAnalysisResponse.ts
   
   # Update imports throughout codebase
   find frontend/src -name "*.ts" -o -name "*.tsx" | \
     xargs sed -i 's|from.*types/RiskScoreResponse|from "../apiTypes"|g'
   ```

3. **Remove duplicate interfaces** from `frontend/src/chassis/types/index.ts`:
   ```typescript
   // DELETE these manual interfaces (now auto-generated):
   // export interface RiskScoreResponse { ... }
   // export interface PortfolioAnalysisResponse { ... }
   // export interface PerformanceResponse { ... }
   
   // KEEP core business interfaces:
   export interface User { ... }
   export interface Portfolio { ... }
   export interface Holding { ... }
   ```

4. **Update documentation**:
   - Update `README.md` to link to Swagger UI: `http://localhost:5001/docs/`
   - Update `docs/API_REFERENCE.md` to reference auto-generated docs
   - Add developer guide: `docs/CONTRIBUTING_API.md`

5. **Set up code ownership** (`.github/CODEOWNERS`):
   ```
   # API contract changes require both BE and FE review
   /schemas/           @backend-team @frontend-team
   /routes/api.py      @backend-team @frontend-team
   /frontend/src/apiTypes.ts @backend-team @frontend-team
   ```

### Phase 5 – Team Adoption
1. Write short **dev-guide** (`docs/CONTRIBUTING_API.md`) covering:
   • how to add a new endpoint schema
   • how to regenerate types
   • CI expectations
2. Set CODEOWNERS so API changes ping both BE & FE reviewers.
3. Retrospective after 2 sprints.

---

## Frontend Migration Strategy

### Two-Phase Approach

**Phase 3a: Type Migration (MECHANICAL)**
- ✅ **Zero functional changes** - same services, adapters, hooks, components
- ✅ **Perfect type safety** - frontend types exactly match backend responses
- ✅ **Risk-free deployment** - pure import statement changes
- ✅ **Immediate benefits** - better autocomplete, error detection, refactoring

**Phase 3b: Data Enhancement (FUNCTIONAL - Optional)**
- 🆕 **Extend functionality** - use additional data from Phase 0.5 alignment
- 🆕 **Enhance user experience** - display richer information (suggested limits, analysis metadata)
- 🆕 **Add new features** - leverage previously unavailable data
- 🆕 **Progressive enhancement** - build on established type foundation

### Key Benefits of Separation
1. **Get type safety first** without any functional risk
2. **Build new features later** on solid type foundation  
3. **Deploy incrementally** - mechanical changes separate from functional changes
4. **Test thoroughly** - type migration can be validated independently

## Result Object Migration Patterns

### Current Challenge: Dynamic Pandas Serialization
```python
# Current problematic pattern:
def to_dict(self) -> Dict[str, Any]:
    return {
        "covariance_matrix": _convert_to_json_serializable(self.covariance_matrix),  # ❌ Unpredictable!
        "risk_contributions": _convert_to_json_serializable(self.risk_contributions), # ❌ Could be anything!
    }
```

### Solution: Curated Schema-Driven Methods
```python
# New schema-compliant pattern:
def to_api_response(self) -> Dict[str, Any]:
    return {
        "top_risk_contributors": self._get_top_contributors(5),        # ✅ Controlled structure
        "volatility_metrics": {                                       # ✅ Explicit fields
            "annual": float(self.volatility_annual),
            "monthly": float(self.volatility_monthly)
        },
        "sector_breakdown": self._format_sector_allocation()          # ✅ Curated data
    }

def _get_top_contributors(self, n: int) -> List[Dict[str, Any]]:
    """Helper to format top risk contributors for API"""
    if self.risk_contributions.empty:
        return []
    
    top_contributors = self.risk_contributions.nlargest(n)
    return [
        {"ticker": ticker, "contribution": float(contrib)}
        for ticker, contrib in top_contributors.items()
    ]
```

### Key Result Objects to Refactor
1. **RiskAnalysisResult** → RiskAnalysisResponseSchema
2. **RiskScoreResult** → RiskScoreResponseSchema  
3. **PerformanceResult** → PerformanceResponseSchema
4. **WhatIfResult** → WhatIfResponseSchema
5. **StockAnalysisResult** → StockAnalysisResponseSchema

## Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| Initial annotation effort underestimated | Start with high-traffic routes; automate rest with `datamodel-code-generator` where possible |
| Schema drift due to forgotten decorator | CI gate fails build if spec-⇆-TS diff present |
| Complex pandas DataFrame serialization | Add `to_api_response()` methods that curate specific fields instead of dumping everything |
| Breaking existing internal usage | Keep existing `to_dict()` methods for backward compatibility; add new schema-compliant methods |
| Runtime cost of validation | Validation only on ingress/egress; can be toggled off in prod if micro-latency critical |
| Developer unfamiliarity | Provide dev-guide & pair session |

---

## Success Metrics
* 100 % of public routes covered by OpenAPI schema
* Frontend no longer contains hand-written API interfaces
* CI fails on any unsynchronised schema change
* Swagger UI available and up-to-date in staging and prod
* Reduction in “undefined field” TypeScript errors to ≈ 0

---

## Next Steps

### Phase 0-0.5: Critical Foundation
1. **Create `feat/openapi-scaffold` branch** and add flask-smorest config.  *(Owner: BE)*
2. **CRITICAL: Audit RiskScoreResult alignment**:
   - Document what `run_risk_score_analysis(return_data=True)` returns
   - Compare with what `RiskScoreResult.from_risk_score_analysis()` captures
   - Fix missing fields: `suggested_limits`, `portfolio_file`, `formatted_report`
   - Fix timestamp handling: use original `analysis_date` from core function
   - Add missing fields to `RiskScoreResult` dataclass
3. **Validate other result objects** have no data loss issues

### Phase 1: Scaffolding  
1. Annotate `/api/performance` + one more simple GET route to demonstrate.  *(Owner: BE)*

### Phase 1.5: Result Object Refactoring (CRITICAL)
1. **Start with RiskScoreResult** as pilot:
   - Add `to_api_response()` method with explicit structure
   - Create `schemas/risk_score.py` with matching schema
   - Update `/api/risk-score` endpoint to use new method
   - Test that schema validation works
2. **Apply pattern to remaining result objects**:
   - RiskAnalysisResult → RiskAnalysisResponseSchema
   - PerformanceResult → PerformanceResponseSchema  
   - WhatIfResult → WhatIfResponseSchema
3. **Validate approach** with one full endpoint before proceeding

### Phase 2: OpenAPI Integration
1. **Configure flask-smorest** in app.py and register blueprints
2. **Transform /api/risk-score endpoint** with OpenAPI decorators (@bp.arguments, @bp.response)
3. **Test Swagger UI generation** at http://localhost:5001/docs/
4. **Scale pattern to all endpoints** (portfolio-analysis, performance, etc.)
5. **Validate complete OpenAPI spec** generation

### Phase 2.5: Frontend Pipeline Integrity Audit (VALIDATION) 
1. **Create audit script** to trace data flow API → Service → Adapter → Hook → Component *(Owner: FE)*
2. **Run pipeline audits** on all major data flows (risk score, portfolio analysis, performance) *(Owner: FE)*
3. **Fix any field mapping bugs, type mismatches, or data loss** discovered *(Owner: FE)*
4. **Document clean pipeline** - all audits pass before type migration *(Owner: FE)*

### Phase 3a: Type Migration (MECHANICAL)
1. **Create type alias bridge** from OpenAPI to existing interface names *(Owner: FE)*
2. **Systematic import replacement** throughout frontend codebase *(Owner: FE)*
3. **Remove old manual type definitions** *(Owner: FE)*
4. **Test type alignment** with `npm run type-check`

### Phase 3b: Data Enhancement (FUNCTIONAL - Optional)
1. **Extend adapters** to transform new data fields from Phase 0.5 *(Owner: FE)*
2. **Enhance components** to display richer information *(Owner: FE)*
3. **Add new features** using previously unavailable data *(Owner: FE)*

### Phase 3c-5: Automation & CI/CD
1. **Create type generation automation** and npm integration *(Owner: FE)*
2. **Set up CI/CD validation** to prevent schema drift *(Owner: DevOps)*
3. **Clean up documentation and team adoption** *(Owner: Team)*

### Priority Order for Result Object Refactoring
1. **RiskScoreResult** (highest traffic, simplest structure)
2. **PerformanceResult** (well-defined metrics)
3. **RiskAnalysisResult** (most complex, needs careful curation)
4. **WhatIfResult** (scenario comparisons)
5. **StockAnalysisResult** (individual stock analysis)

---

*End of document*
*End of document*