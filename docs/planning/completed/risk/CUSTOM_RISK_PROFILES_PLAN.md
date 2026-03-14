# Plan: Custom Risk Profiles (User-Defined, No Code Dependency)

_Created: 2026-02-18_
_Last updated: 2026-02-19 (Implemented)_
_Status: Complete (moved to completed plans)_

## Context

Profile-based risk limits work, but profile definitions are hardcoded in `core/risk_profiles.py`. The user wants profiles to be **purely user-defined** — the code should have no runtime dependency on hardcoded profile definitions. Built-in presets (income/growth/trading/balanced) become seed templates only, used to bootstrap a user's first profile.

## Approach

**Store full profile definition inline in `additional_settings`.** When a user sets a profile, the complete structural parameters are snapshot into `additional_settings` alongside the user's inputs. Derive-on-load reconstructs limits from the stored structural params — no code lookup needed.

Key changes from current design:
- `RISK_PROFILES` dict → renamed to `PROFILE_TEMPLATES` (seed data only, not runtime authority)
- `derive_risk_limits(profile_name, ...)` → `derive_risk_limits(profile_params, max_loss, vol_target)` — takes explicit params, not a name to look up
- `additional_settings` stores complete structural params (`profile_params`) instead of just a profile name
- Derive-on-load uses stored `profile_params` directly instead of looking up `RISK_PROFILES[name]`
- `set_risk_profile()` MCP tool accepts optional structural param overrides — start from a template, customize any parameter

### `additional_settings` new shape

```python
{
    "profile": "income",                    # base template used (informational)
    "profile_name": "My Custom Income",     # optional user-defined display name
    "max_loss_input": 0.25,                 # user input
    "vol_target_input": 0.20,               # user input
    "leverage_input": 1.0,                  # user input
    "derived_at": "2026-02-18T...",         # timestamp
    "profile_params": {                     # NEW — full structural definition
        "max_single_stock_weight": 0.45,
        "max_factor_contribution": 0.85,
        "max_market_contribution": 0.60,
        "max_industry_contribution": 0.50,
        "max_single_factor_loss": -0.15,
    }
}
```

### Structural parameters

| Parameter | What it controls | Valid range |
|-----------|-----------------|-------------|
| `max_single_stock_weight` | Max any single stock as % of portfolio | 0.01–1.0 |
| `max_factor_contribution` | Max variance from factor exposure | 0.01–1.0 |
| `max_market_contribution` | Max variance from market beta | 0.01–1.0 |
| `max_industry_contribution` | Max variance from industry concentration | 0.01–1.0 |
| `max_single_factor_loss` | Max loss from a single factor (negative) | -0.50– -0.01 |

**Note:** Lower bounds are `0.01` (not `0.0`) to match `RiskLimitsData.validate()` which requires variance limits `> 0` and factor loss `< 0`.

## Changes

### 1. Refactor `core/risk_profiles.py`

**Rename and restructure:**
- `RISK_PROFILES` → `PROFILE_TEMPLATES` (clarifies these are seeds, not runtime definitions)
- Each template keeps its structural `params` dict plus metadata: `label`, `description`, `default_vol_target`, `default_max_loss`
- `list_profiles()` → `list_templates()` (returns templates for UI discovery)

**Refactor `derive_risk_limits()` signature:**

```python
def derive_risk_limits(
    profile_params: dict,    # explicit structural params (the 5 values)
    max_loss: float,
    vol_target: float,       # REQUIRED — caller must resolve before calling
) -> Dict[str, Any]:
```

`vol_target` is now required (not optional). Callers are responsible for resolving it before calling — either from the user's explicit input or from the template's `default_vol_target`. This eliminates ambiguity about where the default comes from.

**`vol_target` resolution precedence** (in MCP tool `set_risk_profile()`, before calling `derive_risk_limits()`):
1. User-provided `vol_target` param → use it
2. Template `default_vol_target` for the selected base template → use it

**Note:** We do NOT fall back to stored `vol_target_input` from a previous profile. When setting a new profile, the vol_target comes from user input or the new template's default — never from a prior profile's stored value. This prevents cross-profile bleed (e.g., switching from income to trading wouldn't carry over income's vol_target).

**`vol_target` resolution in derive-on-load** (different context — re-deriving existing profile):
- Uses stored `vol_target_input` from `additional_settings` (this is the value that was resolved at set-time)

No more profile-name lookup inside `derive_risk_limits()`. It builds the limits payload from the explicit `profile_params` dict + `max_loss` + `vol_target`.

**Add new helpers:**
- `get_template(name: str) -> dict` — look up a template by name, return full template dict (params + metadata including `default_vol_target`)
- `validate_profile_params(params: dict) -> dict` — validates all 5 required keys present, clamps to valid ranges, normalizes `max_single_factor_loss` sign. Raises `ValueError` on missing keys.
- `STRUCTURAL_PARAM_RANGES` dict — range metadata for validation

### 2. Extend `set_risk_profile()` MCP tool

**`mcp_tools/risk.py`** — add optional structural param overrides + custom name to `set_risk_profile()`:

```
profile_name: Optional[str]                 — custom display name
max_single_stock_weight: Optional[float]    — override from template
max_factor_contribution: Optional[float]    — override from template
max_market_contribution: Optional[float]    — override from template
max_industry_contribution: Optional[float]  — override from template
max_single_factor_loss: Optional[float]     — override from template
```

Flow:
1. Load base template params via `get_template(profile)`
2. Apply any user-provided overrides on top (non-None values replace template values)
3. Validate merged params via `validate_profile_params()`
4. Pass explicit params to `derive_risk_limits(profile_params, max_loss, vol_target)`
5. Store full `profile_params` in `additional_settings`

Response includes `profile_params` showing the full resolved definition.

### 3. Extend `RiskLimitsManager.set_risk_profile()`

**`inputs/risk_limits_manager.py`** — change to accept explicit `profile_params: dict` instead of looking up by name. Also accept optional `profile_name: str`.

Store in `additional_settings`:
```python
limits_dict["additional_settings"] = {
    "profile": base_template_name,          # informational — which template started from
    "profile_name": profile_name,           # user's custom name (or None)
    "max_loss_input": abs(float(max_loss)),
    "vol_target_input": ...,
    "leverage_input": ...,
    "derived_at": ...,
    "profile_params": profile_params,       # full structural definition
}
```

### 4. Simplify derive-on-load (both paths)

**`inputs/risk_limits_manager.py`** (line ~432) and **`inputs/database_client.py`** (line ~2033):

New logic — use stored `profile_params` directly, with cascading fallback:

```python
additional = risk_limits.get("additional_settings")
if additional and isinstance(additional, dict):
    max_loss = additional.get("max_loss_input")
    vol_target = additional.get("vol_target_input")

    # Try primary path: stored profile_params
    profile_params = additional.get("profile_params")
    used_fallback = False
    if profile_params and isinstance(profile_params, dict):
        try:
            profile_params = validate_profile_params(profile_params)  # validate + normalize; use returned copy
        except Exception:
            profile_params = None  # malformed — fall through to legacy
            used_fallback = True

    # Fallback: legacy row with profile name but no profile_params
    if not profile_params and additional.get("profile"):
        try:
            from core.risk_profiles import get_template
            profile = str(additional["profile"]).strip().lower()
            template = get_template(profile)
            if template:
                profile_params = template["params"]
                # Fill missing vol_target from template default
                if not _is_valid_profile_preference(vol_target):
                    vol_target = template.get("default_vol_target")
                used_fallback = True
        except Exception:
            profile_params = None

    # Derive if we have valid params
    if profile_params and _is_valid_profile_preference(max_loss) and _is_valid_profile_preference(vol_target):
        try:
            fresh = derive_risk_limits(profile_params, float(max_loss), float(vol_target))
            risk_limits["portfolio_limits"] = fresh["portfolio_limits"]
            risk_limits["concentration_limits"] = fresh["concentration_limits"]
            risk_limits["variance_limits"] = fresh["variance_limits"]
            risk_limits["max_single_factor_loss"] = fresh["max_single_factor_loss"]
        except Exception as e:
            print(f"⚠️ Profile re-derivation failed, using baked limits: {e}")
```

**Key behaviors:**
- Malformed `profile_params` → falls through to legacy template lookup (not silently skipped)
- Legacy row missing `vol_target_input` → uses template's `default_vol_target`
- Both paths converge to a single derive call at the bottom

### 5. Update `get_risk_profile()` response

**`mcp_tools/risk.py`** — surface `profile_params`, `profile_name`, and base template from `additional_settings` in the response. Keep `available_profiles` key in response for compatibility, add `available_templates` alongside it.

Add `derivation_source` field inferred from `additional_settings` shape (no plumbing needed from derive-on-load):
- `additional_settings` has `profile_params` → `"derivation_source": "custom_profile"`
- `additional_settings` has `profile` but no `profile_params` → `"derivation_source": "legacy_template_fallback"`
- No `additional_settings` → `"derivation_source": "manual_limits"`

**Note:** This is best-effort metadata based on stored shape. It cannot detect runtime derive failures that fell back to baked DB values (those are logged via `print()` warnings). This is acceptable — the field indicates the *intended* derivation path, not whether it succeeded. Runtime failures are transient and logged.

### 6. Update MCP server wrapper

**`mcp_server.py`** — pass the 6 new optional params through to `_set_risk_profile()`.

### 7. Update `_get_default_risk_limits()`

**`inputs/risk_limits_manager.py`** — currently calls `derive_risk_limits(profile="balanced", max_loss=0.25)`. Change to:

```python
from core.risk_profiles import get_template, derive_risk_limits
template = get_template("balanced")
defaults_dict = derive_risk_limits(
    profile_params=template["params"],
    max_loss=template["default_max_loss"],
    vol_target=template["default_vol_target"],
)
```

**Note:** `get_template()` returns the full template dict (params + metadata including `default_max_loss` and `default_vol_target`). Callers extract what they need. No hardcoded defaults — everything flows from the template. This keeps the API clean — `derive_risk_limits()` always requires all 3 arguments.

## Files to Modify

| File | Change | Size |
|------|--------|------|
| `core/risk_profiles.py` | Rename to templates, refactor `derive_risk_limits()` to take explicit params, add `get_template()`, `validate_profile_params()`, `STRUCTURAL_PARAM_RANGES` | ~40 lines net |
| `mcp_tools/risk.py` | Add 6 optional params to `set_risk_profile()`, resolve template+overrides, surface params in `get_risk_profile()` | ~30 lines |
| `inputs/risk_limits_manager.py` | `set_risk_profile()` takes `profile_params` + `profile_name`, derive-on-load uses stored params with legacy fallback, update default | ~20 lines |
| `inputs/database_client.py` | Derive-on-load uses stored `profile_params` with legacy fallback | ~10 lines |
| `mcp_server.py` | Pass 6 new params in wrapper | ~10 lines |
| `tests/core/test_risk_profiles.py` | Update imports and calls: `RISK_PROFILES` → `PROFILE_TEMPLATES`, `derive_risk_limits(profile_name, ...)` → `derive_risk_limits(profile_params, ...)` | ~10 lines |
| `tests/mcp_tools/test_risk_profile_tools.py` | Update to test new params, check `profile_params` in response, keep `available_profiles` key checks | ~10 lines |

## What Doesn't Change

- DB schema — no migration needed (`additional_settings` JSONB handles new shape)
- `RiskLimitsData` — no changes
- All downstream analysis — same `RiskLimitsData.to_dict()` structure
- `set_risk_profile()` still accepts a `profile` name for template selection — it's just used to look up starting values

## Backwards Compatibility

- **Existing DB rows** with `additional_settings.profile` but no `profile_params`: derive-on-load falls back to template lookup (current behavior). Next `set_risk_profile()` call stores `profile_params` and moves to the new path.
- **Code callers** of `derive_risk_limits()`: signature changes from `(profile_name: str, max_loss, ...)` to `(profile_params: dict, max_loss, vol_target)`. Direct callers: both derive-on-load blocks, `set_risk_profile()` in manager, `_get_default_risk_limits()`, and `tests/core/test_risk_profiles.py`. All updated in this plan.
- **`RISK_PROFILES` → `PROFILE_TEMPLATES`**: `tests/core/test_risk_profiles.py` imports `RISK_PROFILES` directly — needs updating. `list_profiles()` → `list_templates()` similarly.
- **`tests/mcp_tools/test_risk_profile_tools.py`**: Does NOT call `derive_risk_limits()` directly (stubs manager methods). Needs updates for response shape changes (`profile_params`, `available_templates` key) and new parameter tests.

## Verification

1. **Template-based (regression):** `set_risk_profile(profile="income", max_loss=0.25)` → same limits as before, but now `profile_params` stored in `additional_settings`
2. **Custom override:** `set_risk_profile(profile="income", max_loss=0.25, max_single_stock_weight=0.35)` → income template with customized stock weight
3. **Named custom:** `set_risk_profile(profile="income", max_loss=0.25, max_single_stock_weight=0.35, profile_name="My Income")` → stored with custom name
4. **Derive-on-load uses stored params:** Disconnect MCP, reconnect, `get_risk_profile()` → limits derived from stored `profile_params`, not from code templates
5. **Legacy compat:** Existing DB row with `profile: "income"` but no `profile_params` → falls back to template lookup, still works
6. **`get_risk_profile()`:** Shows `profile_params`, `profile_name`, base template used
7. **Validation:** Invalid structural values clamped to range, missing required keys rejected
8. **Tests pass:** `tests/core/test_risk_profiles.py` and `tests/mcp_tools/test_risk_profile_tools.py` updated and passing

## Codex Review Notes

### v1 → v2 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | `vol_target` defaulting under-specified — new signature loses template default | High | **Fixed**: `vol_target` is now required in `derive_risk_limits()`. Callers resolve it before calling (user input → stored input → template `default_vol_target`). Templates keep `default_vol_target` metadata. |
| 2 | Range `0.0` for variance limits conflicts with `RiskLimitsData.validate()` requiring `> 0` | Medium | **Fixed**: Tightened all lower bounds to `0.01`. Factor loss upper bound to `-0.01`. Matches runtime validation. |
| 3 | Legacy fallback skips derivation when `vol_target_input` missing | Medium | **Fixed**: Legacy fallback now fills missing `vol_target` from template's `default_vol_target` before deriving. |
| 4 | Malformed `profile_params` bypasses legacy fallback (in `elif`) | Medium | **Fixed**: Restructured to cascading fallback — validate `profile_params` first, on failure fall through to legacy template lookup, then single derive call at bottom. |
| 5 | "Only 3 call sites" understates impact — tests also import old API | Medium | **Fixed**: Added `tests/core/test_risk_profiles.py` and `tests/mcp_tools/test_risk_profile_tools.py` to Files to Modify. Updated caller count in Backwards Compatibility. |
| 6 | Renaming `available_profiles` → `available_templates` is unnecessary API break | Low | **Fixed**: Keep `available_profiles` key for compatibility. Add `available_templates` alongside it. |
| 7 | Broad `except` + `print` hides degraded behavior | Low | **Fixed**: Added `derivation_source` field in `get_risk_profile()` response when fallback paths are used. |

### v2 → v3 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 8 | `_get_default_risk_limits()` example omits `vol_target` — would break since `vol_target` is now required | High | **Fixed**: Updated example to extract `template["params"]` and `template["default_vol_target"]` separately. `get_template()` returns full template dict with both. |
| 9 | `derivation_source` has no plumbing from derive-on-load to response | Medium | **Fixed**: Removed need for plumbing. `get_risk_profile()` infers source from `additional_settings` shape: has `profile_params` → `custom_profile`, has `profile` only → `legacy_template_fallback`, none → `manual_limits`. |
| 10 | `vol_target` precedence can cause cross-profile bleed when switching templates | Medium | **Fixed**: Separated set-time vs load-time precedence. At set-time: user input → template default (never stored value from prior profile). At load-time (derive-on-load): uses stored `vol_target_input` (which was already resolved at set-time). |
| 11 | Caller list overstates — `test_risk_profile_tools.py` doesn't call `derive_risk_limits()` directly | Low | **Fixed**: Tightened caller list. `test_risk_profile_tools.py` stubs manager methods — needs response shape updates only, not `derive_risk_limits()` signature updates. |

### v3 → v4 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 12 | `derivation_source` by shape can't detect runtime derive failures | Medium | **Acknowledged**: Field indicates intended derivation path, not success/failure. Runtime failures are transient and logged via `print()`. This is acceptable — added note in plan. |
| 13 | `validate_profile_params()` return value discarded in derive-on-load pseudocode | Medium | **Fixed**: Changed to `profile_params = validate_profile_params(profile_params)` — use returned normalized copy. |
| 14 | `_get_default_risk_limits()` hardcodes `max_loss=0.25` instead of using template `default_max_loss` | Low | **Fixed**: Now uses `template["default_max_loss"]`. No hardcoded defaults remain. |
