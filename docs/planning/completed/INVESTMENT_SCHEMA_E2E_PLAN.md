# Investment Schema E2E Test — Cross-Repo Plan

**Status**: R4 PASS (Codex 2026-04-28) — implementation-ready. Final polish edits applied for residual quibbles (`test-token` → real JWT note, `get_or_create_draft_handoff` signature, residual `Barrier` text, L7/L18 cleanup, L24/L25 close R4 Q1-Q3, test 4 explicit `status == "success"` assertion).
**Created**: 2026-04-28
**Revision**: R3 — Codex R2 found that R2's broad direction was right but most concrete recipes (auth pattern, MCP signatures, return keys, stub preconditions, OCC stall mechanism) were wrong. R2→R3 corrections: §3.2/§5.2 alignment, §3.3 (build return shape + insights model_ref precondition), §4.1 (Plan #6 SessionStore pattern + per-module monkeypatch targets), §5.4 (`create_handoff(status="finalized")` direct seeding), §6.1 (every MCP signature + return key corrected), §7.2-7.3 (CAS-layer stall pattern from Plan #6 + correct route), §8.1 (assertion 3 explicit). All file:line references re-verified against source for R3.
**Scope**: New test infrastructure exercising the §2 spine of `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` end-to-end via risk_module MCP entry points → gateway → AI-excel-addin backend → patch engine → thesis update.
**Closes**: gap from audit — no full-spine cross-repo Python integration test exists today.

## R3 → R4 changelog (Codex review response)

### Blockers fixed
1. **§3.2/§5.2 token + binding (Codex R3 #1)** — R3 said `_get_token_sync` returns `"test-token"` literal, but §4.1 creates a real JWT; they didn't agree. R4: the patched method returns the real JWT created in §4.1's setup. Also the binding shape is corrected — instance-level monkeypatch takes `lambda user_id, *, force_refresh=False: <jwt>` (no `self`); class-level monkeypatch takes `lambda self, user_id, *, force_refresh=False: <jwt>`. R4 §3.2/§5.2 specifies instance patching with the no-`self` shape.
2. **Draft-handoff not superseded (Codex R3 #2)** — `start_research_from_idea` creates a draft (`research_service.py:156,161`); insights/price-target routes prefer drafts over finalized for reads (`routes.py:328,911,933`). R4 replaces the direct `create_handoff(status="finalized")` approach with: update the existing draft artifact via `repo.update_handoff_artifact(draft_id, {...})` (`repository.py:2710`), then `repo.finalize_handoff(draft_id)` (`repository.py:3103`). No leftover draft remains active.
3. **CAS monkeypatch on wrong object (Codex R3 #3)** — `routes.py:978` creates a fresh repo per request via factory; instance-level patch on a local repo doesn't reach the route's repo. R4 patches at class level: `monkeypatch.setattr(ResearchRepository, "update_thesis_artifact_if_version_matches", _stalling_cas)` (test 4) / `lambda **_: False` (test 5). All repo instances created during the test see the patched method.
4. **Test 5 off-by-one (Codex R3 #4)** — `max_retries=3` = 3 total attempts (`patch_engine.py:133-135`). With CAS always False: attempts at retry_count 0, 1, 2 → exhaustion → `PatchStaleRetryExhaustedError(retry_count=2)`. R4 §7.3 asserts 3 total attempts and `retry_count == 2` in the error envelope.

### Should-fix items addressed (R4)
1. **Thesis seed method locked** — Plan #6's pattern at `test_plan_6_e2e.py:353` uses `repo.update_thesis_artifact(thesis_id, {...})`. The thesis is auto-created by `start_research_from_idea` (per Plan #6's `_hydrate_patch_ready_thesis`), so the harness updates the existing row rather than creating one. Locked as L21.
2. **R3 Q2 closed** — `actions.thesis:8` imports `_resolve_research_action_context` from `actions.research`, NOT `resolve_action_context` directly. `mcp_tools.thesis:237` calls into `actions.thesis`. So patching `actions.research.resolve_action_context` is sufficient for the entire thesis readback chain. Locked as L22.
3. **R3 Q3 closed** — MCP error envelope key is `error_type` (`mcp_tools/research.py:697`). `PatchStaleRetryExhaustedError` normalizes `retry_count` per `actions/errors.py:171`. Test 5 asserts `response["error_type"] == "patch_stale_retry_exhausted"` (or whatever the exact slug is — confirm at impl) AND `response["retry_count"] == 2`. Locked as L23.
4. **Stale references corrected** — §12a L13 update to use `research_file_id` not `handoff_id` for insights/price-target reads; §11 patch-target list updated to use `actions.research.resolve_action_context` and `actions.model_build_context.resolve_action_context` (NOT `actions.context.resolve_action_context`).
5. **Barrier language replaced** — §4.3, §9.1, §10 acceptance gate, §11 all updated: OCC tests use `threading.Event`-based CAS-level stall, NOT `threading.Barrier(2)`.
6. **`build_model()` flags field** — `mcp_tools/research.py:459` returns `{**result, "flags": ...}`. Test 1 step 5 assertions ignore `flags` (they're cosmetic); the plan documents this so a future reader doesn't think `flags` is missing data.
7. **Step 9 thesis assertion correction** — `actions.thesis.thesis_read()` returns `{status, thesis, requested_sections}` (`actions/thesis.py:104`). Test 1 step 9 asserts on `response["thesis"]`, not the whole response.
8. **`PriceTarget.method` openness** — schema says `method: str | None` (`schema/price_target.py:46`); Plan #6 uses `"relative"` (`test_plan_6_e2e.py:468`). Test 1 step 7 asserts non-empty string OR fixture-equality, not enum membership.

---

## R2 → R3 changelog (Codex review response)

### Blockers fixed
1. **§4.1 auth pattern (Codex R2 #1)** — R2's `SESSION_STORE.sessions["test-token"] = {...}` was fake. Plan #6 pattern at `test_plan_6_e2e.py:87-89` uses `auth.SESSION_STORE.create_session(api_key_hash="test-key", user_id=...)` + `auth.issue_token(session)`. AND: `actions.context.resolve_action_context` is imported into `actions/research.py:7` and `actions/model_build_context.py:7` directly — patching the source module won't affect imported references. R3 patches the imported names: `actions.research.resolve_action_context` and `actions.model_build_context.resolve_action_context`. Token issued with real JWT pipeline.
2. **§5.2 / §3.2 inconsistency (Codex R2 #2)** — R2 left §5.2 with R1's "module-level httpx" wording. R3 §5.2 now matches §3.2 exactly: patch `_get_token_sync()` and `_create_sync_client()` on the gateway-client singleton.
3. **Prepopulate-bypass `repo.upsert_handoff` (Codex R2 #3)** — does not exist. R3 uses `repo.create_handoff(research_file_id, ticker, artifact, status="finalized")` (`repository.py:2619-2628`) — direct write at finalized status, bypassing `HandoffService.finalize_handoff()` entirely (which would rebuild the artifact from the Thesis + draft). Thesis is seeded separately via `repo.upsert_thesis(...)` (or whichever the thesis-create method is — confirm during impl).
4. **MCP signatures wrong throughout §6.1 (Codex R2 #4)** — R3 corrects every signature against source:
   - `get_model_build_context(research_file_id, overrides?, user_email, format)` (`mcp_tools/model_build_context.py:19-25`) — uses **research_file_id** not handoff_id
   - `build_model(research_file_id, handoff_id?, model_build_context_id?, user_email)` (`mcp_tools/research.py:441-446`) — no `format=` kwarg; both handoff_id and mbc_id optional, but plan passes mbc_id
   - `get_model_insights(research_file_id, model_insights_id?, user_email, format)` (`:466-471`) — uses **research_file_id**
   - `get_price_target(research_file_id, user_email, format)` (`:491-495`) — uses **research_file_id**
   - `get_handoff(research_file_id, handoff_id?, user_email)` (`:310-314`) — **no `format=` kwarg**
5. **Return keys wrong (Codex R2 #5)** — R3 corrects assertions:
   - `start_research()` returns `id` (`actions/research.py:147-149`), not `research_file_id`
   - `finalize_handoff()` `status` field is the *handoff* status (e.g. `"finalized"`), not wrapper `"success"` (`actions/research.py:1155`); R3 stops calling `finalize_handoff` MCP and seeds directly
   - `get_handoff(research_file_id, handoff_id=...)` returns `{status, mode: "single", **handoff_summary}` with **top-level artifact** in `_normalize_handoff_summary` output (`actions/research.py:573-589`), not `snapshot.handoff.artifact`
6. **`seed_insights` model_ref precondition (Codex R2 #6)** — `upsert_price_target` requires `artifact.model_ref is not None` (`model_insights_service.py:70-71`). Real build sets it via `update_model_ref()` before insights emission. R3 harness `seed_insights()` calls `repo.update_model_ref(handoff_id, model_ref_payload)` before `service.upsert_price_target()`.
7. **Build return shape (Codex R2 #7)** — R3 cites `actions/research.py:759-771` (the action-level mapping). Real shape: `{status, research_file_id, model_path, handoff_id, build_status, annotation_status, model_build_context_id?, ...}`. Note `status` and `build_status` are separate fields. Test 1 asserts both.
8. **OCC tests under-locked (Codex R2 #8)** — R3 §7.2 switches to the **CAS-layer stall** pattern from Plan #6 `test_plan_6_e2e.py:982-1024`: monkeypatch `repo.update_thesis_artifact_if_version_matches` with a stalling wrapper using `threading.Event`. Single MCP thread enters CAS stall; outside the stall, a direct-repo write bumps thesis version; release the stall; the engine's retry loop catches the stale state, retries, applies at v=N+2; assert response includes `retry_count > 0` and `fresh_version` increments correctly through the MCP envelope. Test 5 patches the same CAS to always return False (forces all 3 retry attempts to see stale, exhausts to `PatchStaleRetryExhaustedError`). Route corrected: `/files/{research_file_id}/patch-ops/apply` (`routes.py:972`), no `max_retries` threading.

### Should-fix items addressed (R3)
1. **§12b Q2 closeable** — `mcp_tools.thesis.thesis_read(research_file_id, sections?, user_email, format)` confirmed at `mcp_tools/thesis.py:39-45`. Locked as L16.
2. **§3.1 corrections** — drop "Playwright-only" claim about `risk_module/tests/integration/` (`test_sync_status_sql.py` exists there). Drop residual `DEV_PYTHONPATH_ENTRIES` mention. Test still lives in AI-excel-addin/tests/integration/ for the same reasons (where the FastAPI backend lives), but the rationale is updated.
3. **Test count contradiction** — Lock at **6 tests, no temporary 7th smoke**. Sub-phase A leaves all 6 tests defined and `@pytest.mark.skip`-ed; the harness verifies imports compile and the gateway adapter constructor doesn't raise — that's done as a `test_harness_compiles` collection-time assertion in the test module's top-level (NOT a 7th test). Sub-phases B/C/D unskip the 6 tests.
4. **Fixture validation location** — explicit: validation lives in the harness module's top-level (`_spine_e2e_harness.py`), called at module import. No `conftest.py` changes.
5. **§8.1 assertion 3 explicit** — `prior_values.get(driver_key)` returns `None` for both "missing key" and "key with None value" (`insights_deriver.py:478`). The check at `:479` excludes only the case where `prior_value is not None and not _is_material_deviation(...)`. So R3 assertion: list contains driver A (prior None / missing) AND driver B (material deviation), excludes driver C (prior matches non-material).
6. **§12b Q4 lockable** — committed JSON fixtures are canonical for CI. Regenerator script exists for human convenience but is NOT part of the CI path. Locked as L17.

---

## R1 → R2 changelog (Codex review response)

### Blockers fixed
1. **§3.2 gateway monkey-patch target** — `ResearchGatewayClient.request()` constructs the httpx client per-call (`research_gateway.py:107`). R1 plan claimed a single httpx handle to patch; this is wrong. R2 patches `_get_token_sync()` and `_create_sync_client()` on the gateway-client instance instead.
2. **§4.1 auth** — Plan #6's `SESSION_STORE` pattern is for direct route calls; the gateway path goes through risk_module's `resolve_action_context()` which can return `None` if the user table isn't seeded. R2 monkey-patches the action context to a fixed user_id and seeds the AI-excel-addin session token for the same user.
3. **§6.1 step 2 (handoff fetch)** — `get_handoff(research_file_id)` returns a *list of summaries* (`actions/research.py:591-599`). The artifact only comes from `get_handoff(research_file_id, handoff_id=...)` (`routes.py:1534-1543, 267`). R2 sequences `finalize_handoff()` first, captures `handoff_id` from response, then fetches the artifact.
4. **§6.1 step 3 (build tool)** — `mcp_tools.model_build_context` only exposes `get_model_build_context()` (`mcp_tools/model_build_context.py:19,50,81`). Build is `mcp_tools.research.build_model()` (`mcp_tools/research.py:441,459`) and returns `{model_path, status, ...}`, not a `FinancialModel`. R2 separates MBC validation (Pydantic) from build invocation (status-only assertion).
5. **§3.3 stub seam** — no `BuildModelOrchestrator.run_build()`. Real methods: `build_and_annotate(handoff_id, user_id, business_model)` (`build_model_orchestrator.py:123`) and `build_and_annotate_from_mbc_id(handoff_id, user_id, model_build_context_id, business_model)` (`:310`). Insights/price-target emission happens inside these methods at `:454-474`. R2 patches `build_and_annotate_from_mbc_id` and explicitly seeds insights via `service.record_insights()` + `service.upsert_price_target()`.
6. **§6.1 step 4 (`derive_insights`)** — does not exist. Insights auto-emit during build; readback is `mcp_tools.research.get_model_insights(handoff_id)` and `mcp_tools.research.get_price_target(handoff_id)` (`mcp_server.py:213,214`; `mcp_tools/research.py:466,491`). R2 drops `derive_insights` and uses the readback tools.
7. **§6.1 step 5 (`apply_patch_ops` shape)** — does not accept `expected_version`. Return is `{applied_op_ids, audit_id, idempotent_replay, retry_count, fresh_version}` (`routes.py:318,324`). R2 drops `expected_version=N` and asserts `fresh_version == N+1`.
8. **§7.2 OCC policy** — already shipped: retry-on-stale, default 3 attempts, `PatchStaleRetryExhaustedError` on exhaustion (`patch_engine.py:124-149`). Existing unit tests cover engine-level retry success + exhaustion (`tests/api/research/test_patch_engine.py:1182-1259`). R2 bakes in Behavior A explicitly and re-scopes test 4 to **gateway-boundary serialization** (verifying `fresh_version`, `retry_count`, `applied_op_ids` round-trip through the MCP wrapper) — what's actually new vs. existing engine tests.
9. **§8.1 degraded-path shapes** — R1 used vague "sentinel" language. R2 specifies actual returns: line 183 returns one zero-impact `DriverSensitivity` per `mbc.drivers` (sorted, `impact_per_unit=0.0`, `rank=1`); line 290 sets `impact = float(matched["delta"] or 0.0)`; line 481 only appends candidates where `_is_material_deviation` fires OR `prior_value is None`; line 799 returns the `fallback_mid` parameter directly.

### Should-fix items addressed
1. **`format="summary"`** — every MCP call uses `format="summary"` so assertions can read straight from the dict. Agent envelopes (`format="agent"`) are out of scope for machine assertions.
2. **Test count** — 6 tests total. The §5.5 "harness smoke" is the *collection check + 1 baseline assertion*, **not** a 7th test. Sub-phase A leaves the 6 test functions defined but skipped via `@pytest.mark.skip`; B/C/D unskip them.
3. **DEV_PYTHONPATH_ENTRIES inheritance** — dropped. Plan #6 explicitly mutates `sys.path` at module load (`test_plan_6_e2e.py:22-27`); R2 uses the same pattern, prepending risk_module repo root.
4. **`@pytest.mark.flaky` precedent** — dropped. `pytest.ini` only declares `eval` (`AI-excel-addin/pytest.ini:1,3`); no flaky marker exists. R2 §7.2 commits to deterministic threading via `threading.Barrier`.
5. **Test 4 vs Plan #6 unit OCC test** — re-scoped per blocker #8 above.
6. **ThesisLink / Scorecard setup** — dropped from test 1's implicit assertion. R2 §6.1 only asserts `Thesis` shape after patch ops; ThesisLink/Scorecard generation runs through separate routes (`routes.py:1753,1769,1806,1847`) and is out of spine scope.
7. **Rollback wording** — R2 §11 explicitly cites the `TODO.md` mutation and requires `pytest`-style `monkeypatch` cleanup for the harness's process-global mutations.

**Related docs / code**:
- `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` — the schema spec being exercised
- `risk_module/mcp_server.py:199-221` — MCP tool registration (`start_research`, `get_handoff`, `finalize_handoff`, `apply_patch_ops`, `thesis_create`)
- `risk_module/mcp_tools/research.py`, `risk_module/mcp_tools/thesis.py`, `risk_module/mcp_tools/model_build_context.py` — wrapper layer
- `risk_module/actions/research.py` — gateway callers (`research_gateway.request(...)`)
- `risk_module/services/research_gateway.py` — `httpx.Client` to AI-excel-addin backend
- `AI-excel-addin/api/research/routes.py` — FastAPI router (mounted under `/api/research`)
- `AI-excel-addin/tests/integration/test_plan_6_e2e.py` — proven in-process pattern (FastAPI TestClient + repo factory + tmp_path)
- `AI-excel-addin/api/research/patch_engine.py` — `apply_patch_ops`, OCC on `theses.version`
- `AI-excel-addin/api/research/insights_deriver.py:183, 290, 481, 799` — known `TODO(plan-6F)` degraded paths

---

## 1. Purpose & scope

### Purpose
Provide one Python integration test module that walks the full investment schema spine from idea ingress to thesis update, exercising the cross-repo MCP boundary that no existing test covers. This is the structural test that catches:
- Pydantic schema drift at gateway boundaries
- HandoffPatchOp frozen-contract violations
- OCC retry logic on concurrent patch ops
- Spine integrity (every step's input shape matches the previous step's output shape)

### In scope
- Test module: `AI-excel-addin/tests/integration/test_investment_schema_spine_e2e.py`
- Six test functions, one per spine step or composition seam:
  1. `test_spine_happy_path_msft` — full §2 spine, single user, sequential
  2. `test_spine_handoff_artifact_v1_1_shape` — HandoffArtifact contract validation post-finalize
  3. `test_spine_patch_op_frozen_contract` — mutation attempt fails as designed
  4. `test_spine_occ_conflict_resolves` — concurrent `apply_patch_ops` on same thesis, OCC retry behaves per documented policy
  5. `test_spine_occ_retry_exhaustion_raises` — saturated conflict exhausts retry, surfaces typed `PatchStaleRetryExhaustedError`
  6. `test_spine_degraded_insights_paths` — verifies the four `TODO(plan-6F)` placeholder paths return their documented placeholder shape (non-business-model, +10% delta default, conservative surface, orchestrator fallback)
- Test ticker: `MSFT` (clean industry_analysis + segment structure; matches Plan #7's existing fixtures)
- Fixture-stubbed external data: FMP profile/financials, EDGAR filings, model-engine build output. Real DB writes (`tmp_path`-scoped repo factory).
- Gateway plumbing: in-process `httpx`-shaped adapter that dispatches risk_module gateway requests to AI-excel-addin's FastAPI router via `TestClient` (no real network).

### Out of scope
- The portfolio-mcp leg (step 7 of §2 spine) — out of scope per §11 of the master plan.
- `MethodologyUnit` / `WikiArticle` MCP mirror on risk_module side — Plan #9 sub-phase G was cut at R1; not part of the spine.
- Frontend (Playwright tests in `risk_module/e2e/` already exist for UI; this is a Python integration layer only).
- CLI `build_model` — does not exist (per Plan #8 ship notes).
- Real network calls to FMP / EDGAR — explicitly stubbed (Plan #8 fixture pattern).
- Live data freshness assertions — not the goal; we test schema shape + integrity.
- Full plan-6F closure (the four TODOs) — test 6 is a regression *tripwire*, not the fix.

---

## 2. Sub-phase summary

| # | Sub-phase | Closes | Tests added | Acceptance |
|---|---|---|---|---|
| A | Test harness — gateway adapter + fixture scaffolding | "no cross-repo MCP boundary test exists" | 0 (infra) | imports work, harness smoke-test asserts a risk_module MCP call lands in AI-excel-addin route |
| B | Happy-path spine — sequential walk through 7 steps | Audit gap #1 | tests 1, 2 | both pass; HandoffArtifact v1.1, ModelBuildContext, ModelInsights, PriceTarget, Thesis Pydantic-valid at their boundaries |
| C | OCC conflict path | Audit gap #3 + Plan #6 R2.4 architectural seam | tests 3, 4, 5 | three pass; concurrent threads behavior matches documented policy; retry-exhaustion surfaces typed error |
| D | Degraded paths — the 4 plan-6F TODOs | Audit gap #2 | test 6 | one pass; documents current placeholder behavior so future plan-6F closure has a baseline |
| E | CI integration + ship marker | — | 0 | test module runs green in default CI; ship marker commit |

Total: 6 tests, 1 new test module, 1 small-scope adapter helper, fixture bundle. **No production code changes.**

---

## 3. Test architecture decisions

### 3.1 Where the test lives — AI-excel-addin
**Decision** (R3): `AI-excel-addin/tests/integration/test_investment_schema_spine_e2e.py`.

**Why**:
- `AI-excel-addin/tests/integration/` is the existing home for cross-cutting Python integration tests (Plan #6, #7, #8 patterns all live here).
- AI-excel-addin owns the schema source of truth and the FastAPI backend; the test mounts that backend via `TestClient`.
- `risk_module/tests/integration/` does have *some* Python integration tests (`test_sync_status_sql.py`), but no FastAPI-backend test scaffolding. Locating the spine e2e in AI-excel-addin keeps it adjacent to the proven Plan #6 e2e + repo factory + auth patterns it borrows from.
- `sys.path` mutation for cross-repo imports is done explicitly per §5.3 (Plan #6 pattern); `DEV_PYTHONPATH_ENTRIES` (`analyst.py:60-65`) is for runtime-process imports, not pytest invocations.

### 3.2 Gateway plumbing — patch the gateway client's httpx + token methods
**Decision** (R2): `services.research_gateway.ResearchGatewayClient.request()` constructs the httpx client per-call (`research_gateway.py:107`) and acquires a session token per-request (`:103`, `_get_token_sync` at `:157`). There is no module-level httpx handle to monkey-patch.

The harness instead **patches two methods on the gateway-client instance** that risk_module action code uses (the singleton imported as `research_gateway` in `actions/research.py:9`). Note: instance-level `monkeypatch.setattr(instance, "method", lambda...)` binds the lambda *as the method* — it does NOT receive `self`. So the lambdas below take only the original method's external parameters:

1. `_get_token_sync` → return the real JWT created in §4.1's setup (NOT a literal string). Patch shape: `monkeypatch.setattr(research_gateway, "_get_token_sync", lambda user_id, *, force_refresh=False: real_jwt)`. Skips real gateway-token acquisition (which depends on `GATEWAY_URL` + `GATEWAY_API_KEY` env vars).
2. `_create_sync_client` → return a `_TestClientHttpxAdapter` (context manager) that forwards `request(method, url, json, params, headers)` to the in-process AI-excel-addin FastAPI `TestClient`, stripping the `gateway_url` prefix and translating to `client.request(method, "/api/research/<path>", ...)`. Patch shape: `monkeypatch.setattr(research_gateway, "_create_sync_client", lambda: _TestClientHttpxAdapter(client))`.

The `_TestClientHttpxAdapter` exposes the minimum subset of `httpx.Client` that `request()` actually consumes:
- `__enter__` / `__exit__` (context manager)
- `request(method, url, *, json, params, headers) -> Response` where the returned `Response` has `.status_code`, `.content`, `.json()`, `.headers` (TestClient's response object already satisfies this surface)

**Why**:
- Two-process tests (real gateway HTTP server + real backend + real model-engine subprocess) are slow and flaky; not the test's job to validate process supervision.
- `TestClient` already exercises real Pydantic validation + real request/response serialization at the FastAPI boundary. The wire shape is checked.
- Patching the client's two construction methods (rather than the global httpx) keeps the test surgical and reversible per-test.

**Risk acknowledged**: this is *not* testing the real `httpx.Client` behavior (timeouts, retries, connection pool, SSL verify). Those concerns are owned by `app_platform.gateway`; out of scope here.

**Implementation seam reference**:
```
research_gateway.py:103  session_token = self._get_token_sync(...)        ◄── patch returns real JWT (§4.1)
research_gateway.py:107  with self._create_sync_client() as client:       ◄── patch returns TestClient adapter
research_gateway.py:109    response = client.request(...)                 ◄── adapter forwards to TestClient
```

### 3.3 model-engine build — stub `BuildModelOrchestrator.build_and_annotate_from_mbc_id`
**Decision** (R3): The orchestrator's real public seams are:
- `BuildModelOrchestrator.build_and_annotate(handoff_id, user_id, business_model)` (`build_model_orchestrator.py:123`)
- `BuildModelOrchestrator.build_and_annotate_from_mbc_id(handoff_id, user_id, model_build_context_id, business_model)` (`build_model_orchestrator.py:310`)

The route at `routes.py:1577` dispatches to `build_and_annotate_from_mbc_id` when `model_build_context_id` is supplied. R3 patches `build_and_annotate_from_mbc_id`; the test always passes `model_build_context_id`.

**Build return shape** (R3 — corrected from R2): The action `actions/research.py:759-771` maps the route response to:
```
{
  status: "success" | "error",        # wrapper status (mapped from build_status)
  research_file_id: int,
  model_path: str | None,
  handoff_id: int,
  build_status: str,                  # the actual build outcome (separate field)
  annotation_status: str,             # "success" | "idle" | ...
  model_build_context_id: str?,       # echoed when supplied
  annotation_error?: ...,             # present on annotation failure
  ...
}
```
The orchestrator method (`build_and_annotate_from_mbc_id`) returns its own dict shape including `build_status` at `build_model_orchestrator.py:357`; the route layer wraps that with `status` for the action layer. Test 1 step 5 asserts:
- top-level `status == "success"` AND `build_status == "success"`
- `model_path` is non-None
- `handoff_id` matches the seeded handoff
- `annotation_status` is `"success"` or `"idle"` (per the action's mapping at line 754-756)

**Insights/price-target seeding** (R3 — `model_ref` precondition added): the real method emits insights inline at `build_model_orchestrator.py:454-474`, but `ModelInsightsService.upsert_price_target()` requires `artifact.model_ref is not None` (`model_insights_service.py:70-71`). The real build sets `model_ref` first (`build_model_orchestrator.py:349, 404`).

The harness `seed_insights(handoff_id, *, insights: ModelInsights, price_target: PriceTarget, model_ref: dict)` helper:
1. `repo.update_model_ref(handoff_id, model_ref)` — sets the precondition
2. `service.record_insights(research_file_id, handoff_id, insights)` — writes ModelInsights
3. `service.upsert_price_target(research_file_id, handoff_id, price_target)` — now passes precondition; also runs `update_model_ref` again with `last_price_target` set per service code (`:74-75`)

The stub patch for `build_and_annotate_from_mbc_id` calls `seed_insights(...)` with fixture data before returning the build response. This replicates the real flow's emission sequence in the right order.

**Why**:
- Real build is slow (~10–30s), depends on `openpyxl` (and Excel COM on some machines), and adds non-determinism.
- This test validates `ModelBuildContext` → build status round-trip + `ModelInsights`/`PriceTarget` Pydantic contracts at gateway boundary, not build correctness (which has its own test suite — Plan #8's 245 tests).
- Stubbing the MBC variant (not both) limits surface area; if a future plan introduces a third orchestrator path the test breaks loudly.

**Implementation seam reference**:
```
build_model_orchestrator.py:310  def build_and_annotate_from_mbc_id(...)  ◄── stub target
build_model_orchestrator.py:357  build_status field                       ◄── populated in real method's response
actions/research.py:759-771      action-level response mapping            ◄── what the MCP tool returns
build_model_orchestrator.py:349,404,454-474  model_ref + insights flow   ◄── replicated by seed_insights()
model_insights_service.py:70-71  upsert_price_target precondition         ◄── why seed_insights sets model_ref FIRST
```

### 3.4 Fixture data sources
**Decision**: One canned MSFT bundle, generated once and committed:
- `tests/integration/fixtures/spine_e2e/msft_idea.json` — `InvestmentIdea`
- `tests/integration/fixtures/spine_e2e/msft_handoff_artifact_v1_1.json` — pre-finalized artifact (with `industry_analysis`, `differentiated_view`, `sources`, `assumption_lineage` populated)
- `tests/integration/fixtures/spine_e2e/msft_financial_model.json` — `FinancialModel` snapshot for stub
- `tests/integration/fixtures/spine_e2e/msft_model_insights.json` — derived insights baseline

All fixtures pass Pydantic validation at module load (asserted in `_spine_e2e_harness.py` via a `_validate_fixtures()` function called at module import — NO `conftest.py` changes; aligned with §5.4).

**Generation**: write a one-shot regenerator script `tests/integration/fixtures/spine_e2e/regenerate.py` so the bundle is reproducible. The regenerator records from a real backend run; commit both the JSON and the script.

### 3.5 Test isolation
**Decision**: One `tmp_path` per test; new `ResearchRepositoryFactory(tmp_path)` per test; `auth.SESSION_STORE.sessions.clear()` between tests; no module-level state.

**Why**: Plan #6 e2e pattern (lines 59–68 of `test_plan_6_e2e.py`). Proven.

### 3.6 What the test does NOT exercise (architectural honesty)
- **Real httpx behavior** — covered by `app_platform.gateway` tests
- **Real model-engine subprocess lifecycle** — covered by model-engine's own tests
- **Real network to FMP/EDGAR** — covered by Plan #8 routing tests with their own stubs
- **Frontend rendering** — covered by `risk_module/e2e/` Playwright suite
- **Auth / SSO flow** — covered by `app_platform.gateway` session tests
- **Multi-tenant DB isolation** — covered by repository factory tests

This test exists to cover the **schema-boundary integrity across the spine**, nothing else. Other concerns are tested elsewhere; this is not the place to retest them.

---

## 4. Cross-cutting concerns

### 4.1 Auth — two-sided patching (R3 — Plan #6 SessionStore pattern + per-module monkeypatch targets)

**Risk_module side**: `actions/research.py:7` and `actions/model_build_context.py:7` import `resolve_action_context` directly:
```python
from actions.context import ActionContext, resolve_action_context
```
Patching the source module (`actions.context.resolve_action_context`) **does NOT** affect the imported references. R3 patches the imported names directly:
- `monkeypatch.setattr("actions.research.resolve_action_context", _fake_context_factory)`
- `monkeypatch.setattr("actions.model_build_context.resolve_action_context", _fake_context_factory)`

Where `_fake_context_factory(user_email=None) -> ActionContext` returns a fixture context with `user_id="101"` (numeric-string per Plan #6 convention at `test_plan_6_e2e.py:87`). If `mcp_tools.thesis` resolves context through a different module-level import, that path needs the same patch — confirm during impl by reading `mcp_tools/thesis.py` + the `_run_thesis_tool` helper it uses.

**AI-excel-addin side**: real session creation via Plan #6's verified pattern (`test_plan_6_e2e.py:87-89`):
```python
session = auth.SESSION_STORE.create_session(api_key_hash="test-key", user_id="101")
token = auth.issue_token(session)  # real JWT
```
The patched `_get_token_sync` (from §5.2) returns this real token. The gateway request includes `Authorization: Bearer <token>` + `X-Research-User-Id: 101`. AI-excel-addin's auth middleware verifies the JWT via `auth.verify_token()` (per `agent_gateway/session.py:189` cited by Codex), resolves the session, authorizes user `101`.

**Cleanup**: all patches via pytest `monkeypatch` fixture (auto-restores at teardown). The `_scoped_factories` autouse fixture (Plan #6 pattern at `test_plan_6_e2e.py:59-68`) clears `auth.SESSION_STORE.sessions` between tests.

**Why this pattern**: real JWT pipeline + session store = the auth path matches production behavior. The R2 fake `sessions["test-token"]` would have failed at `verify_token()`.

### 4.2 Schema version pinning
Test asserts `HandoffArtifact.schema_version == "1.1"` and `InvestmentIdea.schema_version == "1.0"` literally. If a future plan bumps to v1.2, this test must update — that's the contract. The test's job is to break loudly when a version bump happens without an opt-in update.

### 4.3 OCC fixture timing (R4 — Event-based CAS stall, not Barrier)
The OCC conflict test uses **`threading.Event`-based CAS-level stalling** (per Plan #6 pattern at `test_plan_6_e2e.py:982-1024`), NOT a caller-level `threading.Barrier`. A barrier at the MCP-call layer doesn't reach the engine's CAS — a class-level monkeypatch on `update_thesis_artifact_if_version_matches` with `entered.set()` + `release.wait()` is the correct mechanism. See §7.2 for the full setup.

### 4.4 Frozen-contract assertion
The frozen-contract test calls a `HandoffPatchOp`'s `__setattr__` directly (e.g. `op.target = something_else`) and asserts the assignment is rejected. Pydantic v2 raises `ValidationError` on frozen-model mutation; if Plan #6's config raises `TypeError` instead, accept either. The contract is "mutation rejected"; the exception type is incidental.

### 4.5 Degraded path test contract
For the 4 `TODO(plan-6F)` paths, the test asserts the *current* placeholder shape, not the future-correct shape. When plan-6F closes any of these TODOs, this test will fail and need updating — that's intentional. It serves as a regression tripwire for accidental behavioral drift in the placeholder logic.

### 4.6 Test runtime budget
Hard target: full module <30s on a developer machine. Per-test soft target: <5s for happy-path / shape / frozen-contract; <10s for OCC conflict (thread coordination); <5s for degraded paths.

---

## 5. Sub-phase A — Test harness

### 5.1 Goal
Wire risk_module's `research_gateway` to AI-excel-addin's FastAPI router via in-process adapter. Establish fixture path and skeleton test module.

### 5.2 Gateway adapter design (R3 — aligned with §3.2)
- New helper: `AI-excel-addin/tests/integration/_spine_e2e_harness.py`
- `class _TestClientHttpxAdapter`: implements the subset of `httpx.Client` that `ResearchGatewayClient.request()` consumes — `__enter__`/`__exit__` (context manager) + `request(method, url, *, json, params, headers) -> Response`. Strips the `gateway_url` prefix and forwards to `TestClient.request(method, "/api/research/<path>", ...)`.
- Pytest fixture `gateway_adapter(monkeypatch, client: TestClient, real_jwt)`:
  - `monkeypatch.setattr(research_gateway, "_get_token_sync", lambda user_id, *, force_refresh=False: real_jwt)`
  - `monkeypatch.setattr(research_gateway, "_create_sync_client", lambda: _TestClientHttpxAdapter(client))`
- `research_gateway` is the singleton instance from `services.research_gateway`, imported in `risk_module/actions/research.py:9` and `risk_module/actions/model_build_context.py`. Instance-level `monkeypatch.setattr(instance, "method", lambda...)` binds the lambda as the method — the lambda does NOT take `self`. Lambdas above match the external signatures of `_get_token_sync(user_id, *, force_refresh=False)` and `_create_sync_client()`.
- `real_jwt` comes from §4.1's auth setup: `auth.SESSION_STORE.create_session(api_key_hash="test-key", user_id="101")` then `auth.issue_token(session)`. The patched `_get_token_sync` returns this real JWT every call.
- No "module-level httpx client" exists to patch; the gateway constructs httpx per-request (`research_gateway.py:107`). Aligned with §3.2.

### 5.3 sys.path setup
- Test module prepends the risk_module repo root to `sys.path` at module load, mirroring the explicit-mutation pattern in `test_plan_6_e2e.py:22-27` (which prepends AI-excel-addin's `api/` and root). R2 does not rely on `DEV_PYTHONPATH_ENTRIES` inheritance — the `analyst.py:60-65` entries are for runtime-process imports, not for pytest invocations from AI-excel-addin's tree.
- Resolve the risk_module path relative to AI-excel-addin's location: `Path(__file__).resolve().parents[3] / "risk_module"` (assumes both repos are siblings under `Jupyter/`). Validate the path exists at module load; raise an explicit `ImportError` if not (so the test fails loudly rather than silently skipping cross-repo imports).

### 5.4 Files to create / modify (sub-phase A only)
- New: `AI-excel-addin/tests/integration/_spine_e2e_harness.py` (~80 LOC adapter + fixture)
- New: `AI-excel-addin/tests/integration/test_investment_schema_spine_e2e.py` (skeleton — empty test functions for B/C/D, marked `@pytest.mark.skip(reason="filled in sub-phase B/C/D")` initially)
- New: `AI-excel-addin/tests/integration/fixtures/spine_e2e/__init__.py` (empty)
- New: `AI-excel-addin/tests/integration/fixtures/spine_e2e/regenerate.py` (placeholder, fleshed out in B)
- Modify: none (no `conftest.py` changes needed if fixtures are local to the test module; reuse existing `_scoped_factories` pattern from `test_plan_6_e2e.py`)

### 5.5 Acceptance (R3 — locked at 6 tests, no temporary smoke)
- `pytest tests/integration/test_investment_schema_spine_e2e.py -v` collects exactly **6 tests**, all marked `@pytest.mark.skip(reason="filled in sub-phase B/C/D")` initially.
- The harness verifies its own basic correctness via:
  - Module-load assertions in `_spine_e2e_harness.py::_validate_fixtures()` (Pydantic round-trip on each fixture JSON)
  - Module-load assertion that `_TestClientHttpxAdapter` constructor doesn't raise
  - Module-load assertion that the gateway-client singleton import resolves (`from services.research_gateway import research_gateway`)
- Sub-phase A acceptance is "module imports + collection succeeds + 6 tests skipped". No 7th test is created. Sub-phases B/C/D progressively unskip.

### 5.6 Rollback
Delete the test module + harness file. No production code touched.

---

## 6. Sub-phase B — Happy-path spine

### 6.1 Test 1: `test_spine_happy_path_msft` (R3 — every signature/return verified against source)

**Handoff seeding** (R4 — draft-update-then-finalize, supersedes R3's direct create_handoff approach):

`start_research_from_idea` auto-creates a draft handoff (`research_service.py:156,161`); the routes for `get_model_insights` / `get_price_target` *prefer* drafts over finalized handoffs for reads (`routes.py:328,911,933`). If the harness creates a separate finalized handoff while the draft remains active, steps 6-7 will read the empty draft and 404.

Correct sequence (mirrors Plan #6 hydration pattern):
1. Look up the auto-created draft via `repo.get_or_create_draft_handoff(research_file_id=id)` (`repository.py:3016`).
2. `repo.update_handoff_artifact(draft_id, artifact=msft_handoff_artifact_fixture)` (`repository.py:2710`) — overwrites the draft's artifact with the canned fixture.
3. `repo.finalize_handoff(draft_id)` (`repository.py:3103`) — flips status to `finalized`. No leftover draft.
4. The Thesis row is also auto-created by `start_research_from_idea`; the harness updates it with the canned fixture via `repo.update_thesis_artifact(thesis_id, {...})` (`repository.py:2220`) — Plan #6 pattern at `test_plan_6_e2e.py:353`.

The gateway adapter routes each MCP call to AI-excel-addin's FastAPI via `TestClient`; responses Pydantic-validate before the next step.

| # | Call (risk_module side) | Real signature ref | Assertion |
|---|---|---|---|
| 1 | `mcp_tools.research.start_research(ticker="MSFT", idea=msft_idea, format="summary")` | `mcp_tools/research.py:99-104` → `actions/research.py:147` | `status == "success"`; `id` (int) is the research_file_id (NOT keyed `research_file_id`); `ticker == "MSFT"`; idea provenance fields round-trip into research file metadata. Capture `id` for subsequent steps |
| 2 | (harness setup, not an MCP call) `draft = repo.get_or_create_draft_handoff(research_file_id=id)` → `repo.update_handoff_artifact(draft["id"], artifact=msft_handoff_fixture)` → `repo.finalize_handoff(draft["id"])` → `repo.update_thesis_artifact(thesis_id, msft_thesis_fixture)` | `repository.py:3016, 2710, 3103, 2220` | After this seed: one finalized handoff, no active draft. `handoff_id = draft["id"]` for subsequent steps |
| 3 | `mcp_tools.research.get_handoff(research_file_id=id, handoff_id=handoff_id)` (NO `format=` kwarg) | `mcp_tools/research.py:310-314` → `actions/research.py:573-589` | response keys: `status`, `mode == "single"`, plus normalized handoff fields. Top-level `artifact` Pydantic-validates as `HandoffArtifactV1_1`; `schema_version == "1.1"`; required sections present per default ProcessTemplate |
| 4 | `mcp_tools.model_build_context.get_model_build_context(research_file_id=id, format="summary")` | `mcp_tools/model_build_context.py:19-25` | response `mbc` dict Pydantic-validates as `ModelBuildContext`; `mbc_id` (string) captured for step 5; `validation_report` present |
| 5 | (orchestrator's `build_and_annotate_from_mbc_id` patched per §3.3; stub calls `harness.seed_insights(handoff_id, ...)` then returns the canned build dict) `mcp_tools.research.build_model(research_file_id=id, model_build_context_id=mbc_id)` (NO `format=` kwarg) | `mcp_tools/research.py:441-462` → `actions/research.py:759-771` | `status == "success"` AND `build_status == "success"`; `model_path` non-None string; `handoff_id == handoff_id`; `annotation_status ∈ {"success","idle"}`; `model_build_context_id == mbc_id`. The MCP wrapper also adds a `flags` field (`mcp_tools/research.py:459`) — the test does not assert on it. **Does NOT return a `FinancialModel`** |
| 6 | `mcp_tools.research.get_model_insights(research_file_id=id, format="summary")` | `mcp_tools/research.py:466-471` | response Pydantic-validates as `ModelInsights`; matches the harness-seeded fixture shape |
| 7 | `mcp_tools.research.get_price_target(research_file_id=id, format="summary")` | `mcp_tools/research.py:491-495` | response Pydantic-validates as `PriceTarget`; `method` is non-empty string (schema `str \| None` at `schema/price_target.py:46` — not a closed enum, Plan #6 uses `"relative"`); fixture-equality assertion against the seeded price_target |
| 8 | construct 3 patch ops (`AddCatalystOp`, `ReplaceAssumptionValueOp`, `AddRiskOp`) referencing fixture-stable IDs from the artifact; `mcp_tools.research.apply_patch_ops(research_file_id=id, ops=ops, format="summary")` | `mcp_tools/research.py:548-563` → `routes.py:972-991` | response includes `fresh_version` (== prior+1), `applied_op_ids` (3 entries), `idempotent_replay == False`, `retry_count == 0`, `audit_id` populated |
| 9 | `mcp_tools.thesis.thesis_read(research_file_id=id, format="summary")` | `mcp_tools/thesis.py:39-45` → `actions/thesis.py:104` | response keys: `{status, thesis, requested_sections}`. Assert on `response["thesis"]`: Pydantic-validates as `Thesis`; `version` matches `fresh_version` from step 8; the catalyst, assumption replacement, and risk are reflected in their respective fields |

**Out of step-9 scope** (per Codex R1 should-fix #6): `ThesisLink` and `ThesisScorecard` are produced by separate routes (`routes.py:1753,1769,1806,1847`) and not asserted here. They have their own test surfaces.

### 6.2 Test 2: `test_spine_handoff_artifact_v1_1_shape`
Independent of test 1. Loads canned `msft_handoff_artifact_v1_1.json`, runs it through the full `HandoffArtifactV1_1` Pydantic round-trip, asserts:
- `schema_version == "1.1"`
- `industry_analysis` field present (master plan R5)
- `differentiated_view` field present (R4)
- `sources` registry present (R4 — canonical source registry)
- `assumption_lineage` field structure
- All `claim_id` / `catalyst_id` / `risk_id` / `trigger_id` stable IDs present (R4 patch-op targeting)
- `segment_profile_snapshot` present and well-formed when `segment_config` populated (R6 master-plan rule)

### 6.3 Files to create / modify (sub-phase B only)
- Modify: `tests/integration/test_investment_schema_spine_e2e.py` (fill in tests 1 + 2; remove `@pytest.mark.skip`)
- Generate: `fixtures/spine_e2e/msft_idea.json`, `msft_handoff_artifact_v1_1.json`, `msft_financial_model.json`, `msft_model_insights.json`
- Flesh out: `fixtures/spine_e2e/regenerate.py`

### 6.4 Acceptance
- 2 tests pass under `pytest -v`.
- Test 1 (9-step spine) runs in <8s; test 2 (shape-only) runs in <2s.
- HandoffArtifact, ModelBuildContext, ModelInsights, PriceTarget, Thesis Pydantic round-trip clean at every spine step.
- The harness `seed_insights()` helper is called from test 1 between the build call (step 5) and the insights readback (step 6); without it, steps 6-7 would return empty/missing data.

### 6.5 Rollback
Revert tests to skip-marker placeholders. Fixtures stay (cheap to keep).

---

## 7. Sub-phase C — OCC conflict path

### 7.1 Test 3: `test_spine_patch_op_frozen_contract`
- Construct `AddCatalystOp(...)` (or whichever op class is canonically frozen — confirm during impl).
- Attempt `op.target = SimpleNamespace(...)` and `op.description = "mutated"`.
- Assert each attempt raises `ValidationError` (Pydantic v2 frozen) or `TypeError` (legacy frozen). Accept either; assert both that the call raises *and* that `op` is unchanged.
- Test against at least 2 op classes from different tiers of the patch grammar (one mutate-thesis-field, one add-catalyst, one replace-assumption-value) to ensure freeze applies across the union.

### 7.2 Test 4: `test_spine_occ_gateway_serialization_roundtrip` (R3 — CAS-layer stall, Plan #6 pattern)

OCC policy (verified, baked-in):
- `apply_patch_ops` accepts `max_retries: int = 3` (default), `retry_backoff_seconds: float = 0.05` (`patch_engine.py:124-149`).
- On stale state, retries internally; `retry_count` increments per attempt.
- On exhaustion (`attempt + 1 >= total_attempts`), raises `PatchStaleRetryExhaustedError`.
- This is **Behavior A** (retry-on-stale, transparent to caller). Locked.

**Why this test is net-new**: existing engine-level OCC tests (`tests/api/research/test_patch_engine.py:1182-1259`) cover the retry semantics at the engine. What's NOT covered: the retry/version metadata (`fresh_version`, `retry_count`) round-tripping through FastAPI → gateway httpx adapter → risk_module action layer → MCP tool envelope. That's the gateway-specific contract this test asserts.

**Test 4 setup** (R4 — class-level CAS-stall, since the route creates fresh repo instances per request at `routes.py:978`):
1. Walk to step 8 of spine (thesis at `version=N`); harness exposes `research_file_id` + `thesis_id`.
2. Capture `original_cas = ResearchRepository.update_thesis_artifact_if_version_matches` (unbound method).
3. `entered = threading.Event()`; `release = threading.Event()`.
4. Define `_stalling_cas(self, *, thesis_id, thesis, expected_version) -> bool` (takes `self` because it's class-level):
   - On first call: `entered.set(); assert release.wait(5); return original_cas(self, thesis_id=thesis_id, thesis=thesis, expected_version=expected_version)`. (The original CAS now sees stale state — the concurrent writer will have bumped the version.)
5. `monkeypatch.setattr(ResearchRepository, "update_thesis_artifact_if_version_matches", _stalling_cas)` — class-level patch so every repo instance the route creates sees the patched method.
6. Spawn worker thread that calls `mcp_tools.research.apply_patch_ops(research_file_id=id, ops=ops_a, format="summary")` through the gateway adapter; capture response in a holder dict.
7. Main thread: `assert entered.wait(5)`; outside the stall, perform a direct write via a *separate* repo instance (`repo_concurrent = ResearchRepositoryFactory(tmp_path).get("101")`) bumping the thesis to `N+1` (e.g., `repo_concurrent.update_thesis_artifact(thesis_id, {"thesis": {"statement": "concurrent-write"}})`). Note: this concurrent write goes through the same `update_thesis_artifact_if_version_matches` (which is patched) — the harness must use a non-CAS write path (e.g., `update_thesis_artifact`, `repository.py:2220`) which bypasses the CAS, OR conditionally bypass the stall for the second call. Confirm during impl: Plan #6 at `test_plan_6_e2e.py:1012` uses `repo_b.update_thesis_artifact(...)` which appears to be the non-CAS path.
8. `release.set()`; `worker.join(5)`.

**Test 4 assertions**:
- Worker did not raise.
- Response is a success dict — explicitly `response["status"] == "success"` (NOT just "is dict, not exception" — the MCP wrapper can return error dicts at `mcp_tools/research.py:563-578`).
- Response includes `retry_count > 0` (engine retried after seeing stale).
- Response `fresh_version == N+2` (engine applied after retry, on top of the concurrent N→N+1 bump).
- Response `applied_op_ids` matches the worker's ops; `idempotent_replay == False`; `audit_id` populated.
- These fields are present in the MCP envelope (proves serialization through gateway httpx → risk_module action → MCP tool, not just engine return).
- Final thesis state has the worker's ops AND the concurrent writer's statement applied.

### 7.3 Test 5: `test_spine_occ_retry_exhaustion_raises` (R4 — class-level CAS-always-False, correct retry math)

The route `/files/{research_file_id}/patch-ops/apply` (`routes.py:972`) calls `apply_patch_ops_engine(repo, research_file_id, batch)` (`:981`) — `max_retries` is NOT threadable through the route. Force exhaustion at the CAS layer via class-level patch:

**Setup**:
1. Walk to step 8 (thesis at `version=N`).
2. `monkeypatch.setattr(ResearchRepository, "update_thesis_artifact_if_version_matches", lambda *args, **kwargs: False)` — class-level: every repo instance (including the route's fresh repo) sees False.
3. `mcp_tools.research.apply_patch_ops(research_file_id=id, ops=ops, format="summary")`.

**Engine retry math** (R4 — corrected from R3 off-by-one):
- `max_retries=3` (default) = 3 total attempts (`patch_engine.py:133-135`)
- Attempt 0 (retry_count=0): CAS False → raises `PatchStaleError` → loop continues
- Attempt 1 (retry_count=1): CAS False → raises `PatchStaleError` → loop continues
- Attempt 2 (retry_count=2): CAS False → raises `PatchStaleError` → `attempt + 1 >= total_attempts` → raises `PatchStaleRetryExhaustedError(retry_count=2)` (`patch_engine.py:136, 144-146`)

**Assertions**:
- The MCP call returns an error response — typed via the action error mapping.
- `response["error_type"]` matches the slug for `PatchStaleRetryExhaustedError` (`mcp_tools/research.py:697`; exact slug confirmed during impl by reading `_map_action_error` and `actions/errors.py:171`).
- `response["retry_count"] == 2` (NOT 3 — see retry math above).
- Engine made exactly 3 total attempts before raising.
- Verifies typed-error round-trip: engine → FastAPI exception handler → gateway httpx response → risk_module action mapper → MCP tool envelope.

### 7.4 Files to create / modify (sub-phase C only)
- Modify: `tests/integration/test_investment_schema_spine_e2e.py` (fill in tests 3, 4, 5)

### 7.5 Acceptance
- 3 tests pass.
- OCC retry behavior confirmed at the cross-repo boundary.
- Frozen contract enforced for at least 3 op classes spanning the patch-op union.
- Typed-error mapping works for `PatchStaleRetryExhaustedError`.

### 7.6 Rollback
Revert tests to skip-marker placeholders.

---

## 8. Sub-phase D — Degraded paths (plan-6F TODOs)

### 8.1 Test 6: `test_spine_degraded_insights_paths`
**R2 — concrete assertions** (per Codex R1 blocker #9). Each sub-assertion targets the *actual current return shape* at that line, not a vague sentinel:

| Sub-assertion | Source | Branch trigger | Concrete current behavior to assert |
|---|---|---|---|
| 1 | `insights_deriver.py:183-197` (non-business-model) | `cached` empty AND `_model_driver_sensitivities` returns empty | returns one `DriverSensitivity` row per `driver_key` in `sorted(mbc.drivers)`, each with `target_metric=<resolved name>`, `impact_per_unit=0.0`, `rank=1`, ranked by `_rank_driver_sensitivities` |
| 2 | `insights_deriver.py:282-301` (matched delta path) | a scenario `matched` dict is present for at least one driver_item | for those rows, `impact_per_unit == float(matched["delta"] or 0.0)`; `periods == _projection_periods(model)`; rows for unmatched drivers have `impact=0.0`, `periods=None` |
| 3 | `insights_deriver.py:471-489` (material/missing surfacing) | driver A: missing from `prior_values` (key absent); driver B: prior_value present but materially different from current; driver C: prior_value present and matches current (non-material). NOTE: `prior_values.get(driver_key)` returns `None` for both "key absent" and "key present with None" (`insights_deriver.py:478`); the exclusion at `:479` only fires when `prior_value is not None and not _is_material_deviation(...)` | candidates list contains rows for driver A and driver B; driver C is excluded. Sub-assertion explicitly verifies this 3-driver fixture exercises all 3 cases |
| 4 | `insights_deriver.py:790-801` (`fallback_mid` current price) | `build_result` lacks both `current_price` and `current_quote.price` | returned `current_price == fallback_mid` (the kwarg value passed by caller) |

This test is a *snapshot* of current behavior. When `plan-6F` closes any of these TODOs, the test will fail and need an update. **The failure is the point**: it forces the closure to be deliberate, surfaces silent behavioral drift, and doesn't let placeholders be quietly removed.

Test docstring must say so explicitly. Each sub-assertion must cite its `insights_deriver.py:line` so a future implementer can find the relevant code immediately.

### 8.2 Files to create / modify (sub-phase D only)
- Modify: `tests/integration/test_investment_schema_spine_e2e.py` (fill in test 6)

### 8.3 Acceptance
- 1 test passes.
- Each of 4 sub-assertions matches the documented placeholder shape.
- Test docstring documents the tripwire intent.

### 8.4 Rollback
Revert test to skip-marker placeholder.

---

## 9. Sub-phase E — CI integration + ship marker

### 9.1 CI integration
- Confirm the new test module is picked up by the default `pytest tests/integration/` invocation in CI. `AI-excel-addin/pytest.ini` declares only the `eval` marker (`pytest.ini:1,3`) — there is no allow-list to update.
- The OCC conflict test (test 4) must be deterministic via `threading.Event`-based CAS-level stalling per §4.3 + §7.2. R4 does NOT add `@pytest.mark.flaky` — that marker is not part of the project's testing convention (no precedent in `test_plan_6_e2e.py`). If timing flake surfaces during impl, fix the synchronization in the test, don't mask it.

### 9.2 Ship marker
- AI-excel-addin commit: ship marker comment in test module header citing this plan doc + commit refs.
- risk_module commit: bump `TODO.md` V2.P9 status note to "11 SHIPPED + spine e2e structural test live (`docs/planning/INVESTMENT_SCHEMA_E2E_PLAN.md`)".

### 9.3 Acceptance
- Full test module runs green in CI on a clean checkout.
- Total runtime <30s.
- 6 tests, 0 skips at end of sub-phase E (5 skips were temporary scaffolding in A).

### 9.4 Rollback
Revert ship-marker commits.

---

## 10. Acceptance gate (overall)

- [ ] 6 tests pass under `pytest tests/integration/test_investment_schema_spine_e2e.py -v`
- [ ] Test module runs in <30s on developer machine
- [ ] **No production code changes** (only test harness + fixtures + tests + docs + sub-phase E ship marker)
- [ ] Pydantic version-pin assertions in test 2 explicit (`schema_version == "1.1"`, `"1.0"`)
- [ ] OCC conflict test (test 4) deterministic via `threading.Event`-based CAS-level stall (class-level `monkeypatch.setattr(ResearchRepository, ...)`), no `@pytest.mark.flaky`
- [ ] Test 4 asserts gateway-serialization shape (`fresh_version`, `retry_count`, `applied_op_ids`, `idempotent_replay`, `audit_id`) as round-tripped through the MCP wrapper — net-new vs. `test_patch_engine.py:1182-1259`
- [ ] Frozen-contract test catches the rejection regardless of exception type (`ValidationError` or `TypeError`)
- [ ] Degraded-path test (test 6) cites `insights_deriver.py:line` for each of the 4 TODOs in test docstring AND asserts the concrete current return shape per L14
- [ ] Typed errors surface across the gateway boundary (test 5 asserts `PatchStaleRetryExhaustedError`, not generic 500 or `ActionInfrastructureError`)
- [ ] Fixture regenerator script (`regenerate.py`) is reproducible — running it from clean state produces byte-identical fixture JSONs (or at least Pydantic-equivalent — accept either)
- [ ] All MCP calls in tests use `format="summary"` (per L15) — no agent envelope unwrapping in assertions
- [ ] All monkey-patches use pytest `monkeypatch` fixture for auto-cleanup (per §11)

## 11. Rollback (overall)

The plan is purely additive (test code + fixtures + plan doc + ship-marker). To roll back:
- Delete `AI-excel-addin/tests/integration/test_investment_schema_spine_e2e.py`
- Delete `AI-excel-addin/tests/integration/_spine_e2e_harness.py`
- Delete `AI-excel-addin/tests/integration/fixtures/spine_e2e/`
- Revert the `risk_module/TODO.md` V2.P9 status-note bump (sub-phase E adds this)
- Revert this plan doc

**Process-global mutation safety**: the harness monkey-patches:
- `research_gateway._get_token_sync`, `research_gateway._create_sync_client` (instance-level on the gateway-client singleton)
- `actions.research.resolve_action_context`, `actions.model_build_context.resolve_action_context` (module-attribute level — patches the imported symbols, NOT `actions.context.resolve_action_context`)
- `BuildModelOrchestrator.build_and_annotate_from_mbc_id` (class-level, for the build stub)
- `ResearchRepository.update_thesis_artifact_if_version_matches` (class-level, OCC tests 4 + 5)

**All patches MUST go through pytest's `monkeypatch` fixture** (auto-restores at teardown) — never `unittest.mock.patch` as a raw context manager that could leak on test failure. The `_scoped_factories` autouse fixture (Plan #6 pattern at `test_plan_6_e2e.py:59-68`) provides additional cleanup belt-and-suspenders for `auth.SESSION_STORE`, repo factory, and template catalog.

No production code is touched at any point. No schema changes. No DB migrations. No service restarts. No `git` operations beyond commit/revert.

---

## 12. Decisions

### 12a — Locked (R2 adds L10–L15; resolves all R1 open questions)
- L1: Test lives in `AI-excel-addin/tests/integration/` (§3.1)
- L2: Gateway plumbing via `TestClient` adapter (patches `_get_token_sync` + `_create_sync_client` on the gateway-client singleton), not real httpx (§3.2)
- L3: Build stubbed via `BuildModelOrchestrator.build_and_annotate_from_mbc_id` patch + harness `seed_insights()` helper (§3.3)
- L4: One canned MSFT fixture bundle, regenerator script committed (§3.4)
- L5: 6 tests across sub-phases A→E (§2). Sub-phase A's "harness smoke" is a baseline check inside one of the 6 test functions, **not a 7th test**.
- L6: Ticker MSFT (§3.4)
- L7 (R4-corrected): Auth via two-sided patching: monkeypatch `actions.research.resolve_action_context` AND `actions.model_build_context.resolve_action_context` (risk_module side; the imported names, NOT `actions.context.resolve_action_context`) + real JWT via `auth.SESSION_STORE.create_session()` + `auth.issue_token()` (AI-excel-addin side) (§4.1)
- L8: Schema versions pinned literally; bumps must be explicit (§4.2)
- L9: Degraded-paths test is a tripwire, not a fix (§4.5, §8.1)
- **L10 (R2)**: OCC policy is Behavior A (retry-on-stale, default 3 attempts). Locked from `patch_engine.py:124-149`. Test 4 re-scoped to gateway-boundary serialization, NOT engine-level retry behavior (which is already covered by `test_patch_engine.py:1182-1259`).
- **L11 (R2, corrected R3)**: Insights are auto-emitted during build, not derived via a separate MCP call. `derive_insights` does not exist. Readback: `mcp_tools.research.get_model_insights(research_file_id)` + `get_price_target(research_file_id)` — both keyed by **research_file_id** (NOT handoff_id; corrected from R2's wrong claim).
- **L12 (R2)**: Build returns `{status, build_status, model_path, handoff_id, annotation_status, model_build_context_id?, flags, ...}` — NOT a `FinancialModel`. Test 1 step 5 asserts both `status` and `build_status` are `"success"`.
- **L13 (R2)**: `apply_patch_ops` does NOT accept `expected_version`. Return shape: `{applied_op_ids, audit_id, idempotent_replay, retry_count, fresh_version}`. Tests assert against this shape.
- **L14 (R2)**: Degraded-paths test asserts concrete current behavior per `insights_deriver.py:183-197, 282-301, 471-489, 790-801`, not vague sentinels (§8.1).
- **L15 (R2)**: All MCP calls use `format="summary"` for direct dict assertions; agent envelopes (`format="agent"`) are not used. **Exception**: `get_handoff()` and `build_model()` have NO `format=` kwarg — assertions read directly from the action-level dict shape.
- **L16 (R3)**: Thesis readback tool is `mcp_tools.thesis.thesis_read(research_file_id, sections?, user_email, format)` (`mcp_tools/thesis.py:39-45`) — supports `format="summary"`. Q2 closed.
- **L17 (R3)**: Committed JSON fixtures are canonical for CI. The regenerator script (`fixtures/spine_e2e/regenerate.py`) is for human convenience when schema evolves; it is NOT part of CI. Q4 closed.
- **L18 (R3, superseded by L23 in R4)**: Handoff seeding sequence is `get_or_create_draft_handoff` → `update_handoff_artifact` → `repo.finalize_handoff(draft_id)` (NOT direct `create_handoff(status="finalized")`, which left the auto-created draft active and broke insights/PT route reads). See L23.
- **L19 (R3, corrected R4)**: Test 5 forces OCC exhaustion via **class-level** `ResearchRepository.update_thesis_artifact_if_version_matches → False` patch, not instance-level (route at `routes.py:978` creates fresh repos per request). With `max_retries=3` default, exhaustion fires at attempt 3 with `retry_count=2` in the error envelope.
- **L20 (R4)**: MCP error envelope key is `error_type` (`mcp_tools/research.py:697`). `PatchStaleRetryExhaustedError` normalizes `retry_count` (`actions/errors.py:171`). Test 5 asserts `response["error_type"]` matches the slug AND `response["retry_count"] == 2`. Q3 closed.
- **L21 (R4)**: Thesis seeding via `repo.update_thesis_artifact(thesis_id, {...})` (`repository.py:2220`). Thesis is auto-created by `start_research_from_idea`; harness updates the existing row (Plan #6 pattern at `test_plan_6_e2e.py:353`). No `upsert_thesis` exists.
- **L22 (R4)**: `mcp_tools.thesis` calls into `actions.thesis`, which imports `_resolve_research_action_context` from `actions.research` (`actions/thesis.py:8`). Patching `actions.research.resolve_action_context` is sufficient for the entire thesis readback chain — `actions.thesis` does NOT need its own patch. Q2 closed.
- **L23 (R4)**: Handoff seeding sequence: `repo.get_or_create_draft_handoff()` (returns auto-created draft from start_research) → `repo.update_handoff_artifact(draft_id, ...)` → `repo.finalize_handoff(draft_id)`. Supersedes R3's direct `create_handoff(status="finalized")` which left the draft active and broke insights/price-target route reads (which prefer draft over finalized at `routes.py:328,911,933`).

### 12b — Closed in R4 (locked as L24-L25)
- **L24 (R4, was Q1+Q2)**: Test 4's concurrent-write path uses `repo.update_thesis_artifact()` which bypasses CAS — Codex R4 verified at `repository.py:2220-2235` (load → merge → `_persist_thesis_payload`) and `:1407-1420, 1456-1467` (version increment + write without `WHERE version=?`). No direct SQL escape hatch needed; the concurrent bump uses `repo_concurrent.update_thesis_artifact(thesis_id, {...})` while the CAS class-method patch is in place.
- **L25 (R4, was Q3)**: MCP error envelope keys: `error_type` from `_map_action_error` (`mcp_tools/research.py:697-704`); `retry_count` normalized in `PatchStaleRetryExhaustedError` (`actions/errors.py:171-185`). Test 5 asserts both keys.

All R4 open questions closed. No deferrals to impl.

---

## 13. Skill integration reference

This plan does not change skill integration. The test module exercises tool surfaces that skills consume; if any test reveals a skill-consumed tool's contract is broken, the skill will need its own update — but that's the test's job to flag, not this plan's job to pre-fix.

`SKILL_CONTRACT_MAP.md` (in AI-excel-addin) does not need an update for this plan; no new contract is introduced.

---

## 14. Summary

One new test module exercises the full §2 spine across the cross-repo boundary that no current test covers. Six tests across four buckets:
- happy-path (test 1) + shape (test 2)
- frozen-contract (test 3)
- OCC gateway-serialization (test 4) + OCC exhaustion typed-error mapping (test 5)
- degraded-paths tripwire (test 6)

Lives in `AI-excel-addin/tests/integration/`, uses FastAPI `TestClient` + gateway-client method patching (`_get_token_sync` + `_create_sync_client`) for in-process cross-repo simulation, fixture-driven (no network), `tmp_path`-isolated per test.

**Closes**: the audit's biggest gap — no full-spine cross-repo Python e2e exists today.
**Establishes**: regression tripwires for HandoffPatchOp frozen contract, gateway-boundary OCC serialization (vs. existing engine-level OCC tests), typed-error round-trip across the MCP wrapper, and the 4 `TODO(plan-6F)` degraded-path placeholder shapes.
**Cost** (R2 estimate): 6 tests, 1 new test module (~280 LOC), 1 harness file (~120 LOC — gateway adapter + auth patches + seed_insights helper + sys.path setup), ~300 LOC fixture JSON, regenerator script (~80 LOC). R1 estimate of ~250+80 LOC understated harness complexity once gateway-client method patching + cross-repo `sys.path` mutation + insights seeding helpers are accounted for.
**Production impact**: zero (test-only, additive). No schema changes, no DB migrations, no service restarts.
