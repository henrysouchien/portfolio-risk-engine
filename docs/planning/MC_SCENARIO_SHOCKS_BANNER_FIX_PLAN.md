# MC Scenario Shocks Banner Fix Plan

**Bug**: When navigating from StressTestTool to MonteCarloTool via "Simulate recovery" exit ramp, the context banner does not show "Scenario-conditioned drift" even though the backend correctly applies scenario shocks.

**Status**: v5 — Codex review of v4 caught a Pydantic response-model boundary issue. Backend fix expanded.
**Files**: 4 changed, 1 new test file
**Risk**: Low (additive backend changes + additive frontend fallback)
**Severity**: **Medium** (re-tagged from Low — confirmed via code: this was not just a cosmetic banner bug; MC was skipping scenario-conditioned drift entirely on the stress→MC navigation path. See "Confirmed: Feature Was Broken" section below.)

---

## Plan History (Codex reviews on prior drafts)

- **v1** (FAIL): Proposed `key={activeTool}` on `<Suspense>` + blanket `useEffect([context])` sync on MC. Codex rejected: cross-type swap already remounts; blanket effect conflicts with "Clear context".
- **v2** (FAIL): Proposed `contextDismissedRef` + stale-`contextKey` refactor. Codex found 4 issues: stale `incoming*` key, incorrect empty-context semantics, nonexistent `factorShocks` field, ref never resets.
- **v3** (Diagnostic-first draft): Phase 1 added `console.warn` probes at 3 junctures to capture root cause in a live repro, Phase 2 deferred until diagnostics landed.
- **v4**: **Live browser investigation of a real repro superseded Phase 1.** Root cause confirmed without shipping diagnostics. Backend service-layer patch + frontend fallback. Codex review FAIL: missed Pydantic `response_model` boundary, missed API-level test coverage, missed code-level confirmation that MC drift was actually broken.
- **v5** (this draft): Adds the response-model update, adds an API-level test, upgrades severity to Medium, removes "Open Question" (resolved).

---

## Live Repro Findings (2026-04-09)

Reproduced in the browser on the live dev stack:

1. Navigated to `#scenarios/stress-test`, ran **Interest Rate Shock**.
2. Clicked **Simulate recovery** → `#scenarios/monte-carlo`.
3. MC context banner rendered as:
   > `"Running with context from Post-Interest Rate Shock recovery · Vol scale: 1.5x"`

   Missing the expected `"· Scenario-conditioned drift"` suffix.
4. Introspected React fiber state on `MonteCarloTool` via browser devtools. `context` prop:
   ```
   context = {
     source: "stress-test",
     label: "Post-Interest Rate Shock recovery",
     volScale: 1.5,
     distribution: "t",
     scenarioShocks: undefined    ← property exists, value is undefined
   }
   ```
   `hasOwnProperty("scenarioShocks") === true`, `scenarioShocks === undefined`. `StressTestTool` explicitly set the key.

5. Inspected the React Query cache entry for the stress-test run:
   ```
   {
     success: true,
     scenario_name: "Interest Rate Shock",
     factor_contributions: [
       { factor: "rate_10y", shock: 0.03, ... },
       { factor: "rate_5y",  shock: 0.03, ... },
       { factor: "rate_30y", shock: 0.03, ... },
       { factor: "rate_2y",  shock: 0.03, ... }
     ],
     // NO `scenario`, NO `scenario_id`, NO `scenario_key`
     ...
   }
   ```
   The backend response only contains `scenario_name`. The `scenario` key is absent.

### Full failure path (top → bottom)

| # | Location | What happens |
|---|---|---|
| 1 | `portfolio_risk_engine/stress_testing.py:297-310` | `run_stress_test()` returns a dict with `scenario_name` only — no `scenario` key. |
| 2 | `services/scenario_service.py:506-511` | `analyze_stress_scenario` knows the `scenario` identifier (it was the `scenario` parameter at line 485) but returns the engine result unchanged. Contrast with `run_all_stress_tests` at `stress_testing.py:331` and `agent_building_blocks.run_stress_test` at line 459, which both manually attach `result["scenario"] = scenario_id`. |
| 3 | `POST /api/stress-test` response | Payload is missing the `scenario` field. |
| 4 | `StressTestAdapter.ts:131` | `scenarioId: apiResponse.scenario` → `undefined`. |
| 5 | `StressTestTool.tsx:176` | `scenarioOptions.find(s => s.id === undefined)` → `undefined`. |
| 6 | `StressTestTool.tsx:183` | `setLastRunScenarioShocks(executedScenario?.shocks ?? null)` → **`null`**. |
| 7 | `StressTestTool.tsx:563` | Navigation context built with `scenarioShocks: lastRunScenarioShocks ?? undefined` → **`undefined`**. |
| 8 | `MonteCarloTool.tsx:281` | `initialContext.scenarioShocks` is `undefined`, so `contextScenarioShocks` state is never set. |
| 9 | `MonteCarloTool.tsx:1002-1019` | Banner render condition `contextScenarioShocks ? " · Scenario-conditioned drift" : ""` → empty string. **Observed bug.** |

### What the v3 diagnostic scenarios predicted vs what we found

v3's diagnostic table enumerated five possible failure modes:

| Scenario | D1 result | D2 result | D3 result | Root cause |
|---|---|---|---|---|
| **A** | NOT FOUND | null | absent | **scenarioId mismatch** ← **MATCHES REPRO** |
| B | FOUND | null | absent | nav timing race |
| C | FOUND | truthy | absent | propagation bug |
| D | FOUND | truthy | present | normalize rejects shape / render bug |
| E | works | works | works | intermittent |

Live investigation **confirmed Scenario A**, but with a twist v3 didn't anticipate: it's not an ID *mismatch* — the ID is *entirely missing* from the backend response. The same-instance rerender hazard v3's Change 2 was designed to guard is **not the bug**.

### MCP path is unaffected

`services/agent_building_blocks.run_stress_test` (the MCP/agent path) already sets `result["scenario"] = scenario_id` at line 459. Only the REST path via `services/scenario_service.analyze_stress_scenario` is broken.

---

## Confirmed: Feature Was Broken (not just cosmetic)

Codex flagged this on review and the code chain confirms it. Tracing the failure forward:

1. `StressTestTool.tsx:183` sets `lastRunScenarioShocks` to `null` when `executedScenario` lookup fails.
2. `StressTestTool.tsx:559` (`handleMonteCarloNavigation`) **omits `scenarioShocks` from the navigation context entirely** when null (passes `lastRunScenarioShocks ?? undefined`).
3. `MonteCarloTool.tsx:705` only forwards `scenarioShocks` to the run params when present.
4. `MonteCarloTool.tsx:1005` only renders the "· Scenario-conditioned drift" suffix when present.

So on every "Simulate recovery" navigation since A7c shipped (`346bca92`), the resulting MC run has executed **without** scenario-conditioned drift overrides — just a regular distribution + scaled vol. The missing banner suffix was the visible symptom of the broken feature, not the bug itself.

Additional collateral damage: `StressTestsTab.tsx:148` reads `stressTestData.severity` to render a single-run severity badge. Currently always falsy → badge silently absent. Same root cause, fixed by the same response-model + service-layer patch.

This raises the bug from **Low (cosmetic)** to **Medium (broken feature)**. `docs/TODO.md` should be updated.

---

## Fix

### Change 1a (backend, response model): declare `scenario` + `severity` on `StressTestResponse`

**File**: `models/response_models.py`
**Why**: FastAPI's `response_model=get_response_model(StressTestResponse)` at `app.py:3065` runs Pydantic validation on every response and **strips any field not declared on the model**. Without this change, the service-layer attachment in Change 1b would be silently dropped at the route boundary. Codex caught this on v4 review by confirming `StressTestResponse` only declares 7 fields (none of which are `scenario` or `severity`).

**Before** (lines 155-162):
```python
class StressTestResponse(BaseModel):
    success: bool
    scenario_name: str
    estimated_portfolio_impact_pct: float
    estimated_portfolio_impact_dollar: Optional[float]
    position_impacts: List[Dict[str, Any]]
    factor_contributions: List[Dict[str, Any]]
    risk_context: Dict[str, Any]
```

**After**:
```python
class StressTestResponse(BaseModel):
    success: bool
    scenario_name: str
    scenario: Optional[str] = None
    severity: Optional[str] = None
    estimated_portfolio_impact_pct: float
    estimated_portfolio_impact_dollar: Optional[float]
    position_impacts: List[Dict[str, Any]]
    factor_contributions: List[Dict[str, Any]]
    risk_context: Dict[str, Any]
```

Both fields are `Optional` with `None` default — custom-shock runs and any future code path that legitimately omits the scenario ID stay valid.

### Change 1b (backend, service layer): attach `scenario` + `severity` in service layer

**File**: `services/scenario_service.py`
**Function**: `ScenarioService.analyze_stress_scenario` (line 482)
**Why this location**: The service has the authoritative `scenario` identifier from its parameter, and already looks up `scenario_config` to read `shocks` and `scenario_name`. Attaching the ID (and severity, which is also missing) is a 3-line addition at the existing callsite. Matches the pattern already used in `run_all_stress_tests` and `agent_building_blocks.run_stress_test`.

**Before** (lines 489-513):
```python
try:
    if scenario:
        scenarios = get_stress_scenarios()
        scenario_config = scenarios.get(scenario)
        if not scenario_config:
            available = ", ".join(sorted(scenarios.keys()))
            raise ValueError(f"Unknown stress scenario '{scenario}'. Available: {available}")
        shocks = scenario_config.get("shocks", {})
        scenario_name = scenario_config.get("name", scenario)
    else:
        shocks = custom_shocks or {}
        scenario_name = "Custom"

    if not shocks:
        raise ValueError("Stress test requires either a predefined scenario or custom_shocks")

    risk_result = self.portfolio_service.analyze_portfolio(portfolio_data)
    return run_stress_test(
        risk_result=risk_result,
        shocks=shocks,
        scenario_name=scenario_name,
        portfolio_value=risk_result.total_value,
    )
```

**After**:
```python
try:
    if scenario:
        scenarios = get_stress_scenarios()
        scenario_config = scenarios.get(scenario)
        if not scenario_config:
            available = ", ".join(sorted(scenarios.keys()))
            raise ValueError(f"Unknown stress scenario '{scenario}'. Available: {available}")
        shocks = scenario_config.get("shocks", {})
        scenario_name = scenario_config.get("name", scenario)
    else:
        shocks = custom_shocks or {}
        scenario_name = "Custom"

    if not shocks:
        raise ValueError("Stress test requires either a predefined scenario or custom_shocks")

    risk_result = self.portfolio_service.analyze_portfolio(portfolio_data)
    result = run_stress_test(
        risk_result=risk_result,
        shocks=shocks,
        scenario_name=scenario_name,
        portfolio_value=risk_result.total_value,
    )
    if scenario:
        result["scenario"] = scenario
        if scenario_config and scenario_config.get("severity") is not None:
            result["severity"] = scenario_config["severity"]
    return result
```

**Why include `severity`**: `StressTestAdapter.ts:132` reads `severity: apiResponse.severity` — it's also currently `undefined` for the REST path, for the same structural reason. Fixing it in the same place is nearly free and removes a second silent field. Custom-shock runs leave severity absent (correct — there's no pre-defined severity for custom scenarios).

**Not chosen** (alternative we considered): modifying `portfolio_risk_engine.stress_testing.run_stress_test` to accept a `scenario_key` parameter. Wider change, three callers (`run_all_stress_tests`, `agent_building_blocks.run_stress_test`, `scenario_service.analyze_stress_scenario`) would need updating, and the engine layer stays cleaner if it keeps knowing nothing about stable keys. Service-layer attachment is the minimal surface.

### Change 2 (belt-and-suspenders, frontend): factorContributions fallback

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/StressTestTool.tsx`
**Function**: Inside `useEffect` that sets `lastRunScenarioShocks` (line 170-184)

**Rationale**: Change 1 fixes the root cause, but the frontend currently silently produces `null` shocks whenever any future response shape regression drops `scenario`. `factorContributions` carries the same shock values and is always populated on a successful stress test. Using it as a fallback makes the pipeline robust to backend drift.

**Before** (line 170-184):
```tsx
useEffect(() => {
  if (!stressTest.data) {
    return
  }

  const pinnedScenarioId = stressTest.data.scenarioId ?? null
  const executedScenario = scenarioOptions.find((scenario) => scenario.id === stressTest.data?.scenarioId)
  const pinnedScenarioName = executedScenario?.name
    ?? stressTest.data.scenarioName
    ?? "Stress scenario"

  setLastRunScenarioId(pinnedScenarioId)
  setLastRunScenarioName(pinnedScenarioName)
  setLastRunScenarioShocks(executedScenario?.shocks ?? null)
}, [scenarioOptions, stressTest.data])
```

**After**:
```tsx
useEffect(() => {
  if (!stressTest.data) {
    return
  }

  const pinnedScenarioId = stressTest.data.scenarioId ?? null
  const executedScenario = scenarioOptions.find((scenario) => scenario.id === stressTest.data?.scenarioId)
  const pinnedScenarioName = executedScenario?.name
    ?? stressTest.data.scenarioName
    ?? "Stress scenario"

  // Fallback: if scenario lookup failed (e.g. backend omitted `scenario`),
  // reconstruct shocks from factorContributions, which is always populated
  // on a successful run and carries the same shock values by factor.
  const shocksFromContributions = stressTest.data.factorContributions.length > 0
    ? Object.fromEntries(
        stressTest.data.factorContributions.map((fc) => [fc.factor, fc.shock])
      )
    : null

  setLastRunScenarioId(pinnedScenarioId)
  setLastRunScenarioName(pinnedScenarioName)
  setLastRunScenarioShocks(executedScenario?.shocks ?? shocksFromContributions)
}, [scenarioOptions, stressTest.data])
```

**Trade-off note**: `factorContributions[].shock` is the shock value *applied* during the run. For predefined scenarios this equals `scenarioOptions[].shocks[factor]` exactly. For custom-shock runs it matches the custom input. No divergence risk.

### Dropped from prior drafts

- **v3 Phase 1 (console.warn diagnostics)** — not needed; root cause already traced via live fiber inspection.
- **v2/v3 Change 2 (`useEffect` + `contextDismissedRef` + `contextKey` refactor in `MonteCarloTool`)** — was addressing a theoretical same-instance rerender hazard that is not present in the actual bug path. `MonteCarloTool` does remount on cross-tool navigation (verified: fiber fresh, 80 hooks on a clean mount). Keeping this change in scope would add ~50 lines of code to defend against a non-issue.
- **v1 `key={activeTool}` on `<Suspense>`** — unnecessary, cross-type React reconciliation already remounts.

---

## Test Plan

### New backend test

**File**: `tests/services/test_scenario_service.py`
**Pattern**: Follow existing fixtures in the file (e.g. `test_scenario_shocks_thread_to_engine` at line 158).

```python
def test_analyze_stress_scenario_emits_scenario_key_and_severity(monkeypatch):
    """Regression: REST path must attach scenario ID + severity to result.

    Without this, StressTestAdapter.scenarioId is undefined, which causes
    StressTestTool → MonteCarloTool navigation to drop scenario shocks.
    """
    from services.scenario_service import ScenarioService

    fake_risk_result = _make_fake_risk_result()  # whatever existing tests use
    fake_portfolio_data = _make_fake_portfolio_data()

    svc = ScenarioService(portfolio_service=_stub_portfolio_service(fake_risk_result))

    result = svc.analyze_stress_scenario(
        portfolio_data=fake_portfolio_data,
        scenario="interest_rate_shock",
    )

    assert result["scenario"] == "interest_rate_shock"
    assert result["scenario_name"] == "Interest Rate Shock"
    assert result["severity"] in {"High", "Medium", "Low", "Extreme"}  # capitalized in YAML
    # existing engine fields still present
    assert "factor_contributions" in result
    assert "estimated_portfolio_impact_pct" in result


def test_analyze_stress_scenario_custom_shocks_omits_scenario_key(monkeypatch):
    """Custom-shock runs legitimately have no scenario ID or severity."""
    from services.scenario_service import ScenarioService

    svc = ScenarioService(portfolio_service=_stub_portfolio_service(_make_fake_risk_result()))

    result = svc.analyze_stress_scenario(
        portfolio_data=_make_fake_portfolio_data(),
        custom_shocks={"rate_10y": 0.02},
    )

    assert "scenario" not in result
    assert "severity" not in result
    assert result["scenario_name"] == "Custom"
```

### New API-level test (catches the response-model boundary)

**File**: `tests/api/test_stress_test_api.py` (new file)
**Pattern**: Mirror `tests/api/test_monte_carlo_api.py:615` (`test_scenario_conditioning_preserved_in_response`).
**Why this is essential**: A pure service-layer test in `test_scenario_service.py` will pass even if `StressTestResponse` strips the new fields, because it never crosses the FastAPI route boundary. We need a `TestClient` test that hits `POST /api/stress-test` with a mocked workflow and asserts `scenario` and `severity` survive serialization.

```python
"""API-level coverage that scenario + severity survive the response_model boundary."""
from fastapi.testclient import TestClient
import app as app_module


def _mock_authenticated_user(monkeypatch):
    # match the helper used in test_monte_carlo_api.py
    ...


def test_stress_test_response_includes_scenario_and_severity(monkeypatch) -> None:
    """Regression: /api/stress-test must surface scenario ID + severity for the
    StressTest → MonteCarlo navigation to attach scenario-conditioned drift."""
    client = TestClient(app_module.app)
    client.cookies.set("session_id", "stress-session")
    _mock_authenticated_user(monkeypatch)
    monkeypatch.setattr(app_module, "get_user_scenario_service", lambda user: object())
    monkeypatch.setattr(app_module, "log_request", lambda *args, **kwargs: None)

    def _fake_workflow(portfolio_name, scenario, custom_shocks, user, scenario_service):
        return {
            "success": True,
            "scenario_name": "Interest Rate Shock",
            "scenario": "interest_rate_shock",
            "severity": "High",
            "estimated_portfolio_impact_pct": -5.0,
            "estimated_portfolio_impact_dollar": -5000.0,
            "position_impacts": [],
            "factor_contributions": [
                {"factor": "rate_10y", "shock": 0.03, "portfolio_beta": -6.87, "contribution_pct": -20.0},
            ],
            "risk_context": {},
        }
    monkeypatch.setattr(app_module, "_run_stress_test_workflow", _fake_workflow)

    response = client.post(
        "/api/stress-test",
        json={"portfolio_name": "TEST", "scenario": "interest_rate_shock"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scenario"] == "interest_rate_shock"
    assert body["severity"] == "High"
    assert body["scenario_name"] == "Interest Rate Shock"


def test_stress_test_custom_shocks_omits_scenario_and_severity(monkeypatch) -> None:
    """Custom-shock runs legitimately have no preset scenario ID or severity.
    Both should serialize as None (Optional fields), not be required."""
    client = TestClient(app_module.app)
    client.cookies.set("session_id", "stress-session")
    _mock_authenticated_user(monkeypatch)
    monkeypatch.setattr(app_module, "get_user_scenario_service", lambda user: object())
    monkeypatch.setattr(app_module, "log_request", lambda *args, **kwargs: None)

    def _fake_workflow(portfolio_name, scenario, custom_shocks, user, scenario_service):
        return {
            "success": True,
            "scenario_name": "Custom",
            "estimated_portfolio_impact_pct": -2.0,
            "estimated_portfolio_impact_dollar": -2000.0,
            "position_impacts": [],
            "factor_contributions": [{"factor": "rate_10y", "shock": 0.02, "portfolio_beta": -1.0, "contribution_pct": -2.0}],
            "risk_context": {},
        }
    monkeypatch.setattr(app_module, "_run_stress_test_workflow", _fake_workflow)

    response = client.post(
        "/api/stress-test",
        json={"portfolio_name": "TEST", "custom_shocks": {"rate_10y": 0.02}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body.get("scenario") is None
    assert body.get("severity") is None
    assert body["scenario_name"] == "Custom"
```

### New frontend test

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/__tests__/StressTestTool.test.tsx`
**Purpose**: Cover the factorContributions fallback path.

```tsx
it("reconstructs lastRunScenarioShocks from factorContributions when scenarioId is missing", async () => {
  // Set up a stress test response where scenarioId is undefined (simulating
  // the pre-fix backend bug, or any future regression)
  const stressTestData: StressTestData = {
    success: true,
    scenarioName: "Interest Rate Shock",
    scenarioId: undefined,
    estimatedImpactPct: -0.05,
    estimatedImpactDollar: -5000,
    positionImpacts: [],
    factorContributions: [
      { factor: "rate_10y", shock: 0.03, portfolioBeta: -6.87, contributionPct: -20 },
      { factor: "rate_5y",  shock: 0.03, portfolioBeta: -3.2,  contributionPct: -10 },
    ],
    riskContext: /* ... */,
    flags: [],
  }

  const onNavigate = vi.fn()
  renderStressTestTool({ stressTestData, onNavigate })

  // Trigger navigation to MC
  fireEvent.click(screen.getByRole("button", { name: /simulate recovery/i }))

  // Verify onNavigate was called with shocks reconstructed from factorContributions
  expect(onNavigate).toHaveBeenCalledWith("monte-carlo", expect.objectContaining({
    scenarioShocks: { rate_10y: 0.03, rate_5y: 0.03 },
  }))
})
```

### Existing tests that must still pass

- `tests/test_stress_testing.py` — `run_stress_test` engine tests (unchanged; engine not modified).
- `tests/services/test_scenario_service.py` — existing 5 tests (whatif/mc/scenario-shocks-threading; unaffected).
- `tests/mcp_tools/test_stress_test_tool.py` — MCP stress test tool tests (unchanged; `agent_building_blocks` path was never broken).
- `StressTestTool.test.tsx` — existing tests (the factorContributions fallback is a strict superset; shocks from scenarioOptions still win when scenarioId IS present).
- `MonteCarloTool.test.tsx` — existing scenarioShocks banner tests (should start passing end-to-end for the stress-test→MC flow after this fix; unit tests that directly pass `context.scenarioShocks` continue to pass).

### Live verification

After deploy:
1. Navigate to `#scenarios/stress-test`, run any predefined scenario.
2. Click "Simulate recovery".
3. MC banner should read:
   > `"Running with context from Post-<Scenario> recovery · Vol scale: 1.5x · Scenario-conditioned drift"`
4. Introspect React fiber (or just the rendered text): `context.scenarioShocks` should be a populated object, not `undefined`.

---

## Implementation Sequence

1. **Backend response model** — Edit `models/response_models.py:155-162`, add `scenario: Optional[str] = None` and `severity: Optional[str] = None` to `StressTestResponse`. ~2 lines.
2. **Backend service layer** — Edit `services/scenario_service.py:506-511`, assign engine call to `result`, attach `result["scenario"] = scenario` and `result["severity"] = scenario_config["severity"]` for the preset path, return `result`. ~5 net lines.
3. **Backend service test** — Add 2 tests to `tests/services/test_scenario_service.py` (happy path + custom-shocks path).
4. **Backend API test** — Create `tests/api/test_stress_test_api.py` with 2 tests (preset round-trip + custom-shocks round-trip). Catches the Pydantic boundary that pure service tests miss.
5. **Frontend fallback** — Edit `StressTestTool.tsx:170-184`, add `shocksFromContributions` reconstruction, chain it after `executedScenario?.shocks`. ~5 net lines.
6. **Frontend test** — Add 1 test to `StressTestTool.test.tsx` for the fallback path.
7. **Manual verification** — Reproduce the repro steps in "Live Repro Findings", confirm banner shows "Scenario-conditioned drift" AND the StressTest single-run severity badge appears AND the MC run params include `scenario_shocks` (verify by inspecting `/api/monte-carlo` request payload in devtools).
8. **TODO update** — Re-tag bug from Low → Medium severity in `docs/TODO.md` "Open Bugs" table; update the bug summary line to note the broken-feature scope (not cosmetic).

---

## Risk Assessment

| Dimension | Assessment |
|---|---|
| **Blast radius** | REST `/api/stress-test` response gains 2 optional fields. No consumer breaks: adapter already declared them, was just reading undefined; `StressTestsTab.tsx:148` severity badge starts rendering correctly (currently silently absent). MCP path unchanged. |
| **Backward compat** | Response is strictly additive. Both new fields are `Optional[str] = None`. Existing clients ignoring them are unaffected. |
| **Rollback** | All changes are isolated to 4 files and revertable atomically. |
| **Test coverage** | 2 new service-layer tests + 2 new API-level tests (the API tests are the critical guardrail against future Pydantic boundary regressions) + 1 new frontend test + existing MonteCarloTool scenario-shocks banner tests run end-to-end. |
| **Severity of bug fixed** | **Medium** — confirmed via code inspection that the MC engine was running without scenario-conditioned drift on the stress→MC path. Not just a cosmetic banner. See "Confirmed: Feature Was Broken" section above. |
