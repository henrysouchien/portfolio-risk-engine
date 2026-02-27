# Backend → Frontend Clean-Data Plan

*Author  |  AI-assisted Engineering Team*
*Date    |  2025-08-04*

---
## North-Star Goal
Deliver **clean, predictable, strictly typed data** from the Python backend to the TypeScript frontend so that React components can render and manipulate results with zero ad-hoc plumbing.

Success is achieved when:
1. Every public API endpoint emits a canonical `*Result` object.
2. Those Result objects double as the single source-of-truth schema (OpenAPI components).
3. The frontend compiles in TS `strict` mode using only auto-generated types.

---
## Four-Phase Roadmap

| Phase | Outcome | Key Tasks |
|-------|---------|-----------|
| **1 — Normalise Backend Outputs** | All endpoints return a `*Result` dataclass instance | • Inventory routes → flag non-Result returns  
• Add adapters (`.from_*` factories)  
• Contract test: call endpoints, assert return ↔ Result ↔ `json.dumps()` |
| **2 — Promote Result Objects to Schema** | Result objects = validated Pydantic models & OpenAPI components | • Decorate with `@pydantic_dataclass`  
• Script `tools/generate_openapi.py` exports `openapi/risk_module.yml`  
• Middleware validates every outbound payload against spec |
| **3 — Sync Frontend Types** | Front-end uses only generated interfaces | • `npx openapi-typescript openapi/risk_module.yml --output src/types/generated.ts`  
• Replace manual interfaces; update hooks/stores  
• Enable TS `strict`; fix compiler errors |
| **4 — CI & Governance** | Contract can’t drift | • Backend CI: run contract tests, regen spec, fail on diff  
• Frontend CI: regen TS types, fail on diff  
• PR template checkbox: “Updated Result object / regenerated schema” |

---
## Detailed Task List (AI-Trackable)

1. **backend-inventory** – Inventory endpoints; produce CSV of `route,verb,return_type` *(in progress)*
2. **adapter-wrap**      – Write adapters so all routes emit Result objects
3. **pydantic-conversion** – Add Pydantic decorators to all `*Result` classes
4. **generate-openapi**  – Script to export OpenAPI components & paths
5. **response-validation** – Middleware to reject schema-drift at runtime
6. **ci-backend**        – CI job: inventory tests + spec regen + diff check
7. **generate-ts-types** – CLI to emit `src/types/generated.ts`
8. **frontend-refactor** – Swap manual types for generated; update imports
9. **ts-strict-fix**     – Turn on TS `strict`, fix compile errors
10. **ci-frontend**      – CI job: regenerate TS, fail on diff

> An AI agent can pick up each task by its ID, perform code edits, run scripts/tests, and mark the task complete.

---
## Implementation Guide per Task

### backend-inventory (Python 3.9)
Location  `tools/inventory_endpoints.py`
```python
import inspect, json, csv
from flask import current_app as app
from core.result_objects import BaseResult  # create an ABC if needed

rows = []
for rule in app.url_map.iter_rules():
    func = app.view_functions[rule.endpoint]
    src  = inspect.getsource(func)
    return_annotation = inspect.signature(func).return_annotation
    rows.append({
        "route": str(rule),
        "verb": ",".join(rule.methods - {"HEAD", "OPTIONS"}),
        "return_type": getattr(return_annotation, "__name__", "None"),
    })

with open("inventory.csv", "w") as f:
    csv.DictWriter(f, rows[0].keys()).writerows(rows)
```
CI Assertion (pytest):
```python
import csv, importlib
from core import result_objects
AllResults = {name for name in dir(result_objects) if name.endswith("Result")}

with open("inventory.csv") as f:
    for row in csv.DictReader(f):
        assert row["return_type"].endswith("Result"), \  # fail if not normalised
            f"{row['route']} returns {row['return_type']}"
```

### adapter-wrap
*Pattern*
```python
# routes/api.py
from services.portfolio_service import run_portfolio_view
from core.result_objects import RiskAnalysisResult

@bp.post("/portfolio/analyze")
def analyze():
    raw = run_portfolio_view(request.json)
    return RiskAnalysisResult.from_build_portfolio_view(raw)
```

### pydantic-conversion
```python
from pydantic.dataclasses import dataclass  # instead of from dataclasses import dataclass

@dataclass
class RiskAnalysisResult:
    volatility_annual: float
    # ... existing fields ...
    class Config:
        orm_mode = True
        json_encoders = {pd.Series: lambda s: s.to_dict(), pd.DataFrame: lambda df: df.to_dict("list")}
```
Run bulk-replace (one-liner):
```bash
sed -i '' 's/from dataclasses import dataclass/from pydantic.dataclasses import dataclass/' core/result_objects.py
```

### generate-openapi
Location  `tools/generate_openapi.py`
```python
import json, yaml, importlib
from pydantic.schema import schema
from core import result_objects

MODELS = [getattr(result_objects, m) for m in dir(result_objects) if m.endswith("Result")]
openapi = {
    "openapi": "3.0.3",
    "info": {"title": "Risk Module API", "version": "1.0.0"},
    "paths": {},
    "components": schema(MODELS, ref_prefix="#/components/schemas/")
}
with open("openapi/risk_module.yml", "w") as f:
    yaml.safe_dump(openapi, f)
```

### response-validation
Flask example using `openapi_core`:
```python
from openapi_core import create_spec
from openapi_core.validation.response.validators import ResponseValidator
spec = create_spec(Path("openapi/risk_module.yml").read_text())
validator = ResponseValidator(spec)

@app.after_request
def validate_resp(resp):
    result = validator.validate(resp.request, resp)
    if result.errors:
        raise ValueError(result.errors)
    return resp
```

### generate-ts-types
```jsonc
// package.json
{
  "scripts": {
    "gen:api": "openapi-typescript openapi/risk_module.yml -o frontend/src/types/generated.ts"
  }
}
```

### ci-backend (GitHub Actions)
```yaml
- name: Contract tests
  run: pytest contracts/
- name: Regenerate OpenAPI & check diff
  run: |
    python tools/generate_openapi.py
    git diff --exit-code
```

### ci-frontend (GitHub Actions)
```yaml
- name: Generate TS types & check diff
  run: |
    npm run gen:api
    git diff --exit-code
```

---

---
## Timeline Snapshot (Typical)

Week 1   – Phase 1 complete (all endpoints normalised)  
Week 2   – Phase 2 spec generated + runtime validation active  
Week 3   – Phase 3 frontend refactor finished  
Week 4+  – Ongoing governance via CI

---
## Tooling Cheatsheet

```
# Export OpenAPI spec
python tools/generate_openapi.py

# Generate TypeScript models
npx openapi-typescript openapi/risk_module.yml \
    --output frontend/src/types/generated.ts
```

---
## Risks & Mitigations
| Risk | Mitigation |
|------|------------|
| Endpoint returns raw dict | Contract tests fail CI; adapter-wrap task converts to Result object |
| Schema drift | CI diff check + PR template |
| Developer unfamiliarity | This doc + pair sessions |

---
## Next Steps
1. Finish **backend-inventory** script and run it in CI.  
2. Address any flagged endpoints via **adapter-wrap**.  
3. Move on to **pydantic-conversion** once tests pass.

*End of document*