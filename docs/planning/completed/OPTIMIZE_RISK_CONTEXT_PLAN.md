# Optimization with Upstream Risk Context — v10

> **v10** — addresses 3 Codex findings from v9 review (banner placement, file list, style reference).

## Context

The optimizer has 4 modes (`min_variance`, `max_return`, `max_sharpe`, `target_volatility`) but they're all disconnected from upstream risk findings. When Monte Carlo says "38% probability of loss" or a stress test shows "-15% impact", there's no way to feed that intelligence into the optimization. This plan adds two mechanisms:

1. **Volatility translation**: Convert MC risk metrics → appropriate `target_volatility` value
2. **Constraint overrides**: Tighten risk limits per-call based on upstream findings

Both are backward compatible — no changes to core solver math.

**Deferred (Approach 3)**: Direct CVaR minimization using MC simulation paths. Captured in TODO as A7b-future.

---

## Approach 1: Volatility Translation

### Heuristic — `derive_target_volatility_from_risk()`

**File**: `mcp_tools/optimization.py` (new helper, top of file)

```python
def derive_target_volatility_from_risk(
    current_volatility: float,
    probability_of_loss: Optional[float] = None,
    var_95: Optional[float] = None,
    target_loss_probability: float = 0.25,
) -> float:
    """Translate MC risk metrics into a target volatility for optimization.

    Rules (using >= for unambiguous boundary behavior):
    - probability_of_loss >= 0.40: aggressive reduction (0.65x)
    - probability_of_loss >= 0.30: moderate reduction (0.75x)
    - probability_of_loss >= 0.20: mild reduction (0.85x)
    - Otherwise: no reduction needed, return current vol

    Clamp result to [0.05, current_volatility] to avoid infeasible targets.
    """
    if probability_of_loss is None:
        return current_volatility

    if probability_of_loss >= 0.40:
        scale = 0.65
    elif probability_of_loss >= 0.30:
        scale = 0.75
    elif probability_of_loss >= 0.20:
        scale = 0.85
    else:
        return current_volatility

    return max(0.05, current_volatility * scale)
```

---

### Backend: MCP tool (`mcp_tools/optimization.py`)

Add `risk_context` and `constraint_overrides` params to `run_optimization()` at line 75:

```python
@handle_mcp_errors
def run_optimization(
    user_email: Optional[str] = None,
    optimization_type: Literal["min_variance", "max_return", "max_sharpe", "target_volatility"] = "min_variance",
    target_volatility: Optional[float] = None,
    risk_context: Optional[dict] = None,          # NEW (Approach 1)
    constraint_overrides: Optional[dict] = None,   # NEW (Approach 2)
    portfolio_name: str = "CURRENT_PORTFOLIO",
    format: Literal["full", "summary", "report", "agent"] = "summary",
    output: Literal["inline", "file"] = "inline",
    use_cache: bool = True
) -> dict:
```

**Codex v2 finding #1 fix — resolve effective mode BEFORE expected-returns preload:**

The `risk_context` → `target_volatility` switch must happen between steps 2 (load risk limits) and 3 (load expected returns), because `target_volatility` requires expected returns but `min_variance` does not. Insert new step 2.5:

```python
    # 2.5 Apply risk_context: resolve effective optimization type BEFORE expected returns preload
    #
    # Contract: risk_context may switch ONLY min_variance to target_volatility.
    # max_return, max_sharpe, target_volatility are left unchanged — they already
    # have return-aware objectives or explicit user targets.
    risk_context_metadata = {}
    if risk_context and optimization_type == "min_variance":
        rc_current_vol = risk_context.get("current_volatility")
        rc_prob_loss = risk_context.get("probability_of_loss")
        if rc_current_vol is not None and rc_prob_loss is not None:
            derived_vol = derive_target_volatility_from_risk(
                current_volatility=float(rc_current_vol),
                probability_of_loss=float(rc_prob_loss),
            )
            if derived_vol < float(rc_current_vol):
                # Save original BEFORE mutation
                original_type = optimization_type
                # Switch to target_volatility mode with derived value
                optimization_type = "target_volatility"
                target_volatility = derived_vol
                risk_context_metadata = {
                    "risk_context_applied": True,
                    "derived_target_volatility": derived_vol,
                    "original_optimization_type": original_type,
                    "source": risk_context.get("source", "upstream_risk"),
                }

    # 3. Load expected returns (now uses the potentially-switched optimization_type)
    if optimization_type in ("max_return", "max_sharpe", "target_volatility"):
        ...  # existing preload logic unchanged
```

**risk_context contract** (Codex v3 finding #2 fix):
- `risk_context` may switch ONLY `min_variance` → `target_volatility`
- `max_return`, `max_sharpe` are already return-aware objectives — switching them to target_volatility would lose their intent
- `target_volatility` with explicit user target takes precedence
- This same contract applies to both MCP and REST surfaces

**Metadata capture** (Codex v3 finding #4 fix): `original_type` saved before mutating `optimization_type`.

**MCP metadata location** (Codex v6 finding #3 fix): The MCP `run_optimization()` returns a dict directly (not via Pydantic). Merge `risk_context_metadata` into the top-level response dict for ALL formats:

```python
# After formatting response (summary/full/agent/report), before return:
if risk_context_metadata:
    response["risk_context"] = risk_context_metadata
```

This works because MCP responses are plain dicts — no Pydantic serialization. The `agent` format already returns `{"status", "format", "snapshot", "flags", "file_path"}` — adding `"risk_context"` is additive. The `summary`/`full`/`report` formats similarly return dicts.

### Backend: MCP server wrapper (`mcp_server.py`)

Thread `risk_context` + `constraint_overrides` params through the MCP wrapper at line 1674.

### Backend: REST surface (`app.py`)

**Step 1** — Extend request model (line 656):
```python
class OptimizationRequest(BaseModel):
    portfolio_name: str = "CURRENT_PORTFOLIO"
    target_return: Optional[float] = None
    risk_tolerance: Optional[float] = None
    risk_context: Optional[dict] = None          # NEW (Approach 1)
    constraint_overrides: Optional[dict] = None   # NEW (Approach 2)
```

**Step 2** — Thread in `_run_min_variance_workflow` (line 3520) ONLY:

Per the contract, `risk_context` only applies to `min_variance`. The other 3 workflows (`max_return`, `max_sharpe`, `target_volatility`) ignore `risk_context` — they already have return-aware objectives or explicit targets.

In `_run_min_variance_workflow`, after loading risk limits and before calling `optimize_minimum_variance()`:

1. Check `optimization_request.risk_context`
2. If present: derive target vol via `derive_target_volatility_from_risk()`
3. If derived vol < current vol: load expected returns, call `optimize_target_volatility_portfolio()` instead
4. Include `risk_context_applied` metadata in response

Extract a helper `_apply_risk_context(risk_context: dict | None) -> tuple[str, float | None, dict]` returning `(effective_type, target_vol, metadata)` for reuse between MCP and REST.

---

## Approach 2: Constraint Overrides

### Backend: MCP tool (`mcp_tools/optimization.py`)

**RiskLimitsData actual fields** (from `portfolio_risk_engine/data_objects.py:1397`):
- `portfolio_limits: Optional[Dict[str, float]]` — contains `max_volatility`, `max_loss`
- `concentration_limits: Optional[Dict[str, float]]` — contains `max_single_stock_weight`
- `variance_limits: Optional[Dict[str, float]]` — contains `max_factor_contribution`
- `max_single_factor_loss: Optional[float]` — top-level field (NOT in a `.data` dict)

Override application (after loading risk_limits_data, before calling optimize_*):

```python
import copy

if constraint_overrides:
    risk_limits_data = copy.deepcopy(risk_limits_data)  # Safe — pure @dataclass with dicts
    if "max_volatility" in constraint_overrides:
        if risk_limits_data.portfolio_limits is None:
            risk_limits_data.portfolio_limits = {}
        risk_limits_data.portfolio_limits["max_volatility"] = constraint_overrides["max_volatility"]
    if "max_single_stock_weight" in constraint_overrides:
        if risk_limits_data.concentration_limits is None:
            risk_limits_data.concentration_limits = {}
        risk_limits_data.concentration_limits["max_single_stock_weight"] = constraint_overrides["max_single_stock_weight"]
    if "max_single_factor_loss" in constraint_overrides:
        risk_limits_data.max_single_factor_loss = constraint_overrides["max_single_factor_loss"]
    if "max_factor_contribution" in constraint_overrides:
        if risk_limits_data.variance_limits is None:
            risk_limits_data.variance_limits = {}
        risk_limits_data.variance_limits["max_factor_contribution"] = constraint_overrides["max_factor_contribution"]
```

**Cache-safety** (applies to REST/service path only — MCP tool calls raw `optimize_*` functions directly, not `OptimizationService`, so no service-level caching concern there):
- `deepcopy` creates a new instance → the modified copy has a different `get_cache_key()` hash (since `get_cache_key()` at `data_objects.py:1602` hashes all field values via MD5)
- On the REST path, `OptimizationService` caches with `f"{opt_type}_{portfolio_data.get_cache_key()}_{risk_cache_key}"` — modified risk_limits produce a different cache key, so no stale hits
- The original cached `RiskLimitsData` instance is never mutated
- On the MCP path, overrides are applied to `risk_limits_data` before passing to raw `optimize_*()` functions which have no caching — so overrides always take effect

### Backend: REST surface (`app.py`)

Thread `constraint_overrides` through all 4 workflow functions. Apply deepcopy + override pattern (same as MCP tool) before passing `risk_limits_data` to the service.

**Shared helper** `_apply_constraint_overrides(risk_limits_data, overrides)`:

```python
def _apply_constraint_overrides(
    risk_limits_data: Optional[RiskLimitsData],
    overrides: Optional[dict],
) -> tuple[Optional[RiskLimitsData], dict]:
    """Apply per-call constraint overrides on a deepcopy.

    Returns (modified_or_original, metadata_dict).
    When risk_limits_data is None (DB fallback), overrides are silently skipped.
    """
    if not overrides or risk_limits_data is None:
        metadata = {}
        if overrides and risk_limits_data is None:
            metadata = {"constraint_overrides_skipped": True, "reason": "risk_limits loaded from file fallback"}
        return risk_limits_data, metadata

    import copy
    modified = copy.deepcopy(risk_limits_data)
    # ... apply overrides on modified (same logic as MCP section above)
    return modified, {"constraint_overrides_applied": True, "overrides": overrides}
```

**Codex v3 finding #3 fix**: When `risk_limits_data` is None (DB failure fallback at `app.py:3566`), the service caches off `risk_file` path, not a `RiskLimitsData` object. Overrides cannot be applied to a file path, so they are silently skipped.

**Codex v4 finding #2 fix — metadata location**: All `risk_context` and `constraint_overrides` metadata is placed inside the existing `risk_limits_metadata` dict in the REST response (which already exists in `MinVarianceResponse`, `MaxReturnResponse`, etc. at `response_models.py:108`). This avoids adding new top-level fields that would be dropped by Pydantic serialization.

```python
# In workflow function, merge into existing risk_limits_metadata:
risk_limits_metadata = {
    'name': risk_limits_name,
    'source': 'database' if risk_limits_name not in ['Default', 'Default (Fallback)'] else 'file',
    # NEW: risk context metadata (when applied)
    **risk_context_metadata,          # e.g. risk_context_applied, derived_target_volatility, original_optimization_type
    **constraint_override_metadata,   # e.g. constraint_overrides_applied, constraint_overrides_skipped
}
```

The `risk_limits_metadata` field is typed as `Dict[str, Any]` in the response models, so additional keys are accepted without schema changes.

### Backend: MCP server wrapper (`mcp_server.py`)

Thread `constraint_overrides` through wrapper.

### Frontend usage (deferred)

Constraint overrides are primarily for the **agent surface**. Frontend UI for constraint editing is out of scope.

---

## Frontend: MC → Optimize Context Flow

### Step 1: MonteCarloTool passes risk context

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/MonteCarloTool.tsx`

**Codex v2 finding #2 fix — use actual MC result fields, not nonexistent `portfolio_volatility`.**

The MC result shape (from `portfolio_risk_engine/monte_carlo.py:669`) has:
- `terminal_distribution.probability_of_loss` — exists ✓
- `terminal_distribution.var_95` — exists ✓
- `terminal_distribution.cvar_95` — exists ✓
- `portfolio_volatility` — **DOES NOT EXIST** on MC result

**Solution**: The MC result does not include current portfolio volatility, and it shouldn't — MC simulates forward, it doesn't measure current state. Instead:
- Pass only the fields that exist: `probabilityOfLoss`, `var95`, `cvar95`
- Omit `currentVolatility` from the context payload
- Let OptimizeTool use `probabilityOfLoss` alone for strategy selection (the heuristic only needs `probability_of_loss` to decide the scale factor)
- For the actual `target_volatility` value, OptimizeTool reads **current portfolio vol from performance data** (already available via the shared portfolio context)

Change line 893 from:
```tsx
onClick={() => onNavigate("optimize")}
```
To:
```tsx
onClick={() => onNavigate("optimize", {
  source: "monte-carlo",
  label: "Monte Carlo risk assessment",
  mcRunId: Date.now(),  // unique per click — ensures fingerprint uniqueness even with identical metrics
  riskContext: {
    probabilityOfLoss: terminal?.probability_of_loss,
    var95: terminal?.var_95,
    cvar95: terminal?.cvar_95,
  },
})}
```

**Codex v6 finding #2 fix**: `mcRunId` is a timestamp generated at click time, ensuring each MC→Optimize navigation produces a unique fingerprint even when two MC runs have identical terminal metrics.

### Step 2: OptimizeTool reads context (stop discarding it)

**File**: `frontend/packages/ui/src/components/portfolio/scenarios/tools/OptimizeTool.tsx`

Line 172 currently destructures as `context: _context` (discarded). Change to:
```tsx
export default function OptimizeTool({ context, onNavigate }: OptimizeToolProps)
```

Read risk context:
```tsx
const riskContext = context?.riskContext as {
  probabilityOfLoss?: number
  var95?: number
  cvar95?: number
} | undefined
```

### Step 3: Get current volatility from performance data

**Codex v3 finding #1 fix**: OptimizeTool does NOT currently load performance data on first entry — `usePerformance` is only enabled after an optimization run. Must explicitly load performance when `riskContext` is present.

Add new imports to `OptimizeTool.tsx` (these are NOT currently imported — must be added):

```tsx
import { useCurrentPortfolio } from "@risk/chassis"          // NEW — portfolioId source
import { useDataSource } from "@risk/connectors"              // NEW — performance data loader
import { deriveTargetVolatilityFromRisk } from "./optimize/riskContextUtils"  // NEW — heuristic
```

Add a `useDataSource('performance', ...)` call with `enabled: !!riskContext` to load current portfolio volatility on demand:

```tsx
const currentPortfolio = useCurrentPortfolio()  // NEW import
const portfolioId = currentPortfolio?.id

// Load performance data when risk context needs current volatility
const hasRiskContext = !!riskContext?.probabilityOfLoss
const performanceForVol = useDataSource('performance', { portfolioId }, { enabled: hasRiskContext && !!portfolioId })
const currentVolPct = performanceForVol.data?.risk?.volatility  // percent, e.g. 18.5
const currentVolDecimal = currentVolPct != null ? currentVolPct / 100 : undefined  // 0.185
```

**Unit conversion**: Backend performance emits volatility in percent (`performance_metrics_engine.py:304` returns `round(portfolio_volatility * 100, 2)`). Divide by 100 for decimal form before passing to `optimizeTargetVolatility()`.

### Step 4: Derive + latch prefill into local state

**Codex v5 finding #1 fix**: The derivation must write into the same `strategy`/`targetVolatility` local state that the Run button reads (`OptimizeTool.tsx:182`, `:459`). Use a `useEffect` that latches derived values into state — this is StrictMode-safe because it only writes state (idempotent), not imperative API calls.

**Codex v5 finding #2 fix**: Track override per-fingerprint. Reset on new fingerprint. Treat both strategy changes AND target-vol input edits as overrides.

```tsx
// --- Risk context derivation ---

// Fingerprint = stable identity for this risk context + MC run
// Includes mcRunId from navigate payload to distinguish runs with identical metrics
const mcRunId = context?.mcRunId as number | undefined
const contextFingerprint = useMemo(
  () => riskContext ? JSON.stringify({ ...riskContext, mcRunId }) : null,
  [riskContext, mcRunId]
)

// Pure derivation (no side effects)
// deriveTargetVolatilityFromRisk is defined in a new file:
// frontend/packages/ui/src/components/portfolio/scenarios/tools/optimize/riskContextUtils.ts
const riskContextDerived = useMemo(() => {
  if (!riskContext?.probabilityOfLoss || currentVolDecimal == null) return null
  const derivedVol = deriveTargetVolatilityFromRisk(currentVolDecimal, riskContext.probabilityOfLoss)
  if (derivedVol >= currentVolDecimal) return null
  return { strategy: 'target_volatility' as const, targetVolatility: derivedVol }
}, [riskContext, currentVolDecimal])

// Per-fingerprint tracking: which fingerprint we've latched, and whether user overrode it
const [latchedFingerprint, setLatchedFingerprint] = useState<string | null>(null)
const [overriddenFingerprint, setOverriddenFingerprint] = useState<string | null>(null)

// Latch derived values into local state when new fingerprint arrives with data ready
useEffect(() => {
  if (
    contextFingerprint === null ||
    contextFingerprint === latchedFingerprint ||
    contextFingerprint === overriddenFingerprint ||
    riskContextDerived === null
  ) return

  // Write into the same state the Run button reads.
  // Codex v6 finding #1: OptimizeTool stores targetVolatility as a PERCENT STRING
  // (e.g. "11.7" for 11.7%), not a decimal float. The derived value is decimal (0.117).
  // Convert: derivedVol * 100, format to 1 decimal place, as string.
  setStrategy(riskContextDerived.strategy)
  setTargetVolatility(String(Number((riskContextDerived.targetVolatility * 100).toFixed(1))))
  setLatchedFingerprint(contextFingerprint)
}, [contextFingerprint, latchedFingerprint, overriddenFingerprint, riskContextDerived])

// Show banner when latched
const showRiskContextBanner = (
  contextFingerprint !== null
  && contextFingerprint === latchedFingerprint
  && contextFingerprint !== overriddenFingerprint
)

// --- Override tracking ---

// Wrap existing strategy change handler
const handleStrategyChange = (newStrategy: OptimizationStrategy) => {
  if (contextFingerprint) setOverriddenFingerprint(contextFingerprint)
  setStrategy(newStrategy)  // existing logic
}

// Wrap existing target vol input handler (string-based — GoalSelector emits string values)
const handleTargetVolChange = (vol: string) => {
  if (contextFingerprint) setOverriddenFingerprint(contextFingerprint)
  setTargetVolatility(vol)  // existing logic — stored as percent string e.g. "11.7"
}
```

**Why this is StrictMode-safe**: The effect only calls `setState`, which is idempotent (React deduplicates identical state). No imperative API calls. StrictMode double-mount produces the same state.

**Behavior**:
- New fingerprint + perf data ready → latches strategy + targetVol into state, shows banner
- Same fingerprint → no re-latch (already applied)
- User changes strategy OR edits target vol → marks this fingerprint as overridden, banner hides
- New MC run → new fingerprint → `overriddenFingerprint` doesn't match → latches again
- No riskContext → no performance load, no state changes

### Step 5: Banner JSX

Render the risk-context info banner in `OptimizeTool.tsx`, **above** the `<GoalSelector />` call (not inside GoalSelector — the `Card`/`CardContent` wrapper lives inside `GoalSelector.tsx:74-95`, not in OptimizeTool):

```tsx
{/* Risk context banner — renders above GoalSelector in OptimizeTool's render tree */}
{showRiskContextBanner && riskContext?.probabilityOfLoss != null && (
  <div className="rounded-xl border border-blue-200 bg-blue-50/60 px-4 py-3 text-sm text-blue-800">
    <span className="font-medium">Monte Carlo context:</span>{" "}
    {Math.round(riskContext.probabilityOfLoss * 100)}% probability of loss detected
    — targeting {targetVolatility}% volatility to reduce downside exposure.
  </div>
)}
<GoalSelector ... />
```

**Placement**: A standalone `<div>` rendered directly in `OptimizeTool`'s return, immediately above `<GoalSelector />`. No changes to `GoalSelector.tsx` needed. Styling uses Tailwind utility classes: `rounded-xl border border-blue-200 bg-blue-50/60 px-4 py-3 text-sm text-blue-800` — consistent with the blue info-box pattern used in `MonteCarloTool.tsx` empty state.

**Show condition**: `showRiskContextBanner` (fingerprint latched AND not overridden).
**Hide condition**: User changes strategy or edits target vol → `overriddenFingerprint` set → `showRiskContextBanner` becomes false.
**Copy**: Reads `riskContext.probabilityOfLoss` (0-1 decimal from MC) and `targetVolatility` (local state, percent string).

### Step 6: User clicks Run

User clicks "Run" → the existing `handleRunOptimization()` reads the latched `strategy` + `targetVolatility` from local state → calls `workflow.optimizeTargetVolatility(targetVol)` → existing `usePortfolioOptimization` → `useDataSource` → REST flow. **No new resolver params, no API contract changes, no adapter changes.** Backend sees a normal `target_volatility` call.

---

## What This Does NOT Change

- **Core solver math**: No changes to CVXPY objectives or constraint formulations
- **Optimization types**: Still 4 types (no new `min_cvar`)
- **Risk limits persistence**: Overrides are per-call, not persisted
- **Frontend resolver/adapter**: No changes needed (frontend derives vol client-side)

---

## Files Summary

**Backend (4 files)**:
1. `mcp_tools/optimization.py` — `derive_target_volatility_from_risk()` helper, `risk_context` + `constraint_overrides` params, mode resolution before preloads, deepcopy override logic
2. `mcp_server.py` — thread new params in MCP wrapper
3. `app.py` — extend `OptimizationRequest` model, shared `_apply_risk_context()` + `_apply_constraint_overrides()` helpers, thread in all 4 workflow functions

**Frontend (3 files)**:
4. `MonteCarloTool.tsx` — pass risk context (probabilityOfLoss, var95, cvar95, mcRunId) in optimize exit ramp
5. `OptimizeTool.tsx` — read context, load current vol from performance, latch derived state, show banner, fingerprint tracking
6. `frontend/packages/ui/src/components/portfolio/scenarios/tools/optimize/riskContextUtils.ts` — NEW: `deriveTargetVolatilityFromRisk(currentVol: number, probabilityOfLoss: number): number` — TypeScript port of the Python heuristic (same `>=` boundaries + 0.05 clamp)

**Tests (3 files)**:
6. `tests/mcp_tools/test_optimization_risk_context.py` — MCP tool tests (heuristic, risk_context, constraint_overrides, backward compat)
7. `tests/test_app_optimization_risk_context.py` — REST endpoint tests (min_variance + risk_context switch, constraint_overrides threading, expected returns preload)
8. `frontend/packages/ui/src/components/portfolio/scenarios/tools/__tests__/OptimizeTool.risk-context.test.tsx` — frontend tests (MC exit ramp payload, OptimizeTool prepopulation, one-time application, strategy auto-select)

---

## Tests

### MCP tests (`tests/mcp_tools/test_optimization_risk_context.py`)

| Test | Description |
|------|-------------|
| `test_derive_target_volatility_from_risk_aggressive` | `prob=0.45` → 0.65x scale |
| `test_derive_target_volatility_from_risk_boundary_040` | `prob=0.40` → 0.65x (boundary, `>=`) |
| `test_derive_target_volatility_from_risk_moderate` | `prob=0.35` → 0.75x |
| `test_derive_target_volatility_from_risk_boundary_030` | `prob=0.30` → 0.75x (boundary, `>=`) |
| `test_derive_target_volatility_from_risk_mild` | `prob=0.25` → 0.85x |
| `test_derive_target_volatility_from_risk_no_reduction` | `prob=0.15` → no reduction |
| `test_derive_target_volatility_from_risk_none` | `prob=None` → no reduction |
| `test_derive_target_volatility_from_risk_clamp` | Very high prob + low vol → clamped to 0.05 |
| `test_risk_context_switches_min_variance_to_target_vol` | `min_variance` + risk_context → switches to `target_volatility`, loads expected returns |
| `test_risk_context_ignored_for_max_sharpe` | `max_sharpe` + risk_context → no switch (contract: only min_variance switches) |
| `test_risk_context_ignored_for_max_return` | `max_return` + risk_context → no switch |
| `test_risk_context_ignored_for_explicit_target_vol` | Explicit `target_volatility=0.10` + risk_context → explicit wins |
| `test_risk_context_metadata_captures_original_type` | Metadata `original_optimization_type` = `"min_variance"` (saved before mutation) |
| `test_constraint_overrides_applied` | `max_volatility` override → tighter constraint used |
| `test_constraint_overrides_deepcopy_safety` | Original `RiskLimitsData` NOT mutated |
| `test_constraint_overrides_cache_key_differs` | Modified copy has different `get_cache_key()` |
| `test_constraint_overrides_null_dict_init` | Override on None dict → dict created + override applied |
| `test_no_new_params_unchanged` | No risk_context, no constraint_overrides → identical behavior |

### REST tests (`tests/test_app_optimization_risk_context.py`)

| Test | Description |
|------|-------------|
| `test_min_variance_with_risk_context_switches_to_target_vol` | POST /api/min-variance + risk_context → expected returns loaded, target_volatility path taken |
| `test_max_sharpe_with_risk_context_no_switch` | POST /api/max-sharpe + risk_context → no switch (contract: only min_variance switches) |
| `test_max_return_with_risk_context_no_switch` | POST /api/max-return + risk_context → no switch |
| `test_constraint_overrides_threaded_to_optimizer` | POST /api/min-variance + constraint_overrides → tighter limits in result |
| `test_constraint_overrides_null_risk_limits_skipped` | DB fallback → risk_limits_data=None → overrides silently skipped, response has `constraint_overrides_skipped` |
| `test_risk_context_metadata_in_response` | Response includes `risk_context_applied` + `original_optimization_type` metadata |
| `test_no_new_fields_backward_compat` | Existing requests without new fields → unchanged behavior |

### Frontend tests (`OptimizeTool.risk-context.test.tsx`)

| Test | Description |
|------|-------------|
| `test_mc_exit_ramp_passes_risk_context` | MonteCarloTool onNavigate called with `riskContext` payload (probabilityOfLoss, var95, cvar95) |
| `test_latch_sets_strategy_and_vol` | riskContext + perf vol loaded → local `strategy` state = `target_volatility`, `targetVolatility` state = derived vol |
| `test_banner_shows_when_latched` | Banner visible when latchedFingerprint matches current fingerprint and not overridden |
| `test_late_perf_delays_latch` | riskContext present but perf loading → no latch; after load → state latched |
| `test_same_fingerprint_no_re_latch` | Same fingerprint on rerender → no state change |
| `test_new_fingerprint_re_latches` | New MC run → different fingerprint → state re-latched |
| `test_strategy_change_overrides_fingerprint` | User changes strategy → overriddenFingerprint set, banner hides |
| `test_vol_edit_overrides_fingerprint` | User edits target vol input → overriddenFingerprint set, banner hides |
| `test_new_fingerprint_after_override_latches` | After override, new fingerprint → latches again (override was for old fingerprint) |
| `test_no_risk_context_no_perf_load` | No riskContext → useDataSource('performance') not enabled, no state changes |
| `test_run_reads_latched_state` | After latch, user clicks Run → optimizeTargetVolatility called with latched derivedVol |

---

## Verification

1. **MCP tool**: `run_optimization(risk_context={"probability_of_loss": 0.40, "current_volatility": 0.18})` → auto-selects `target_volatility` with derived value `0.18 * 0.65 = 0.117`, expected returns loaded
2. **MCP tool**: `run_optimization(constraint_overrides={"max_volatility": 0.15})` → runs with tighter vol constraint
3. **Backward compat**: `run_optimization()` with no new params → identical behavior
4. **REST**: POST `/api/min-variance` with `{"risk_context": {"probability_of_loss": 0.40, "current_volatility": 0.18}}` → switches to target_volatility, response includes `risk_context_applied`
5. **Frontend**: Run MC → click "Optimize for better outcomes" → verify banner + auto-selected target_volatility + derived vol pre-populated from performance data
6. **Tests**: `python3 -m pytest tests/mcp_tools/test_optimization_risk_context.py tests/test_app_optimization_risk_context.py -x -v`

---

## Future: Approach 3 — CVaR Optimization (deferred)

Direct tail-risk minimization using MC simulation paths as scenarios. Would add a 5th optimization type `min_cvar` that minimizes Conditional Value-at-Risk at a specified confidence level. Requires:
- Scenario-based returns (from MC or historical)
- New CVXPY formulation with auxiliary variables (Rockafellar-Uryasev)
- Integration with MC output as scenario source
- Testing against existing constraint cascade

Captured in TODO as A7b-future.
