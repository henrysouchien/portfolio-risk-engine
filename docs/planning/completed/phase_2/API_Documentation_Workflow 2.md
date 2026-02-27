# Automated API Documentation & Type-Sync Workflow

_Revision: 2025-07-29_

---

## 0. Why we need this

• Prevent drift between backend route implementation, public API reference, and frontend TypeScript types.  
• Enable any contributor (human or AI) to change an endpoint confidently—CI will flag mismatches.  
• Provide an always-up-to-date Swagger / Redoc site for external consumers.

---

## 1. Single Source of Truth

**Pydantic models** (or `dataclasses + pydantic.dataclasses`) in `core/schemas/` become the canonical definition of every request and response payload.

```
core/
  schemas/
    portfolio.py    # RiskScoreRequest, RiskScoreResponse …
    auth.py         # LoginRequest, AuthToken …
    __init__.py
```

> If you later adopt `attrs` or `dataclasses-json`, swap the generator, the overall workflow stays the same.

---

## 2. Route Wiring (Flask)

Use `flask-smorest` (wrapper around `apispec`) to bind schemas to routes **and** feed the spec generator.

```python
from flask_smorest import Blueprint
from core.schemas.portfolio import RiskScoreRequest, RiskScoreResponse

blp = Blueprint("portfolio", __name__, url_prefix="/api")

@blp.route("/risk-score", methods=["POST"])
@blp.arguments(RiskScoreRequest, location="json")
@blp.response(200, RiskScoreResponse)
@auth_required
@limiter.limit("200/day")
def risk_score(body):
    """Risk-score endpoint – full schema auto-generated."""
    ...
```

Outcome: validation, automatic docstring stubs, and spec feed with **one** line per schema.

---

## 3. Spec Generation Script

`/scripts/build_openapi.py`

```python
#!/usr/bin/env python
"""Dump OpenAPI spec produced by Flask‐Smorest to stdout."""
from myapp import create_app  # factory returns Flask
app = create_app()            # config=TESTING loads all blueprints
with app.app_context():
    spec = app.extensions["apispec_json"]  # provided by smorest
    print(spec)
```

### Add to `Makefile`
```
make regen-api:
	python scripts/build_openapi.py > docs/openapi.yaml
```

---

## 4. Frontend Type Generation

```
# package.json (frontend)
"scripts": {
  "gen:api-types": "openapi-typescript ../../docs/openapi.yaml -o src/types/api.generated.d.ts"
}
```

Run after backend spec build.

---

## 5. CI Pipeline (GitHub Actions example)

```yaml
# .github/workflows/ci.yml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      # Backend
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: make regen-api
      - run: git diff --exit-code docs/openapi.yaml  # fail if not committed

      # Frontend
      - uses: actions/setup-node@v3
        with:
          node-version: 20
      - run: cd frontend && npm ci
      - run: cd frontend && npm run gen:api-types
      - run: git diff --exit-code frontend/src/types/api.generated.d.ts
      - run: cd frontend && npm run type-check && npm test --ci

      # Unit tests backend
      - run: pytest -q
```

If either `openapi.yaml` or the generated TS types change during CI the build fails, forcing the PR author to regenerate and commit.

---

## 6. Public Documentation Site

1. Add a second job in the CI pipeline that, on merge to `main`, pushes `docs/openapi.yaml` to the `gh-pages` branch and hosts Swagger-UI / Redoc.
2. Option: use Redocly Cloud if you prefer.

---

## 7. Developer UX

1. **Edit route or Pydantic model**  → run `make regen-api` → run `npm run gen:api-types` → run tests.  
2. Pre-commit hook (optional) runs the same commands and adds any modified files to the commit.

```bash
pip install pre-commit
pre-commit install
```

`.pre-commit-config.yaml` excerpt:
```yaml
-   repo: local
    hooks:
      - id: regen-openapi
        name: Regenerate OpenAPI + TS
        language: system
        entry: make regen-api && cd frontend && npm run gen:api-types
```

---

## 8. Migration Checklist

1. Introduce Pydantic models (or migrate existing dataclasses).  
2. Install & configure `flask-smorest`.  
3. Add the `build_openapi.py` script.  
4. Wire `Makefile` / npm scripts.  
5. Add CI steps (diff-guard).  
6. Regenerate spec & TS types; commit baseline.  
7. Publish docs site via Pages.

---

## 9. Future Enhancements

• Auto-generate client SDKs (Python, Go) from the same `openapi.yaml`.  
• Add contract tests: front-end jest tests load `openapi.yaml` and validate sample fixtures.  
• Use `per-operationId` rate-limit headers and surface them in the spec. 