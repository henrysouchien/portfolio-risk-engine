# Plan: Profile-Based Risk Limits

_Created: 2026-02-18_
_Last updated: 2026-02-19 (Implemented)_
_Status: Complete (moved to completed plans)_

## Context

Risk limits are generic defaults that don't match actual portfolio style. A concentrated income/REIT portfolio triggers 5 compliance violations against limits designed for a diversified equity portfolio:
- `max_single_factor_loss` of -0.10 produces an impossible max market beta of 0.43 (derived via `calc_max_factor_betas()`)
- `max_factor_contribution` of 0.30 vs actual 0.77 — structurally wrong for any stock-heavy portfolio
- `max_industry_contribution` of 0.30 vs actual 0.31 — too tight for a REIT-concentrated portfolio

The system already has `calculate_suggested_risk_limits()` in `portfolio_risk_score.py` that derives limits from max loss tolerance, but it's only used for display — never to actually configure limits.

## Approach

Add a thin profile layer on top of existing infrastructure. Four user inputs drive all limits:

1. **Profile** (income / growth / trading / balanced) — sets structural parameters
2. **Max loss tolerance** — "I can't lose more than X% in a crash"
3. **Volatility target** — max acceptable portfolio volatility
4. **Leverage** — portfolio leverage multiplier. Default behavior: auto-read from current portfolio positions, so it stays dynamic as leverage changes. User or upstream planner can override when target leverage differs from current state.

The downstream consumption path (`evaluate_portfolio_risk_limits()`, `evaluate_portfolio_beta_limits()`, `calc_max_factor_betas()`) is completely unchanged — it still receives the same `RiskLimitsData.to_dict()` structure.

## Changes

### 1. New module: `core/risk_profiles.py`

Profile definitions and derivation function. ~80 lines.

```python
RISK_PROFILES = {
    "income": {
        "label": "Income / Concentrated",
        "description": "High-yield, concentrated positions. Tolerates sector concentration.",
        "max_single_stock_weight": 0.45,
        "max_factor_contribution": 0.85,
        "max_market_contribution": 0.60,
        "max_industry_contribution": 0.50,
        "max_single_factor_loss": -0.15,
        "default_max_loss": 0.25,
        "default_vol_target": 0.20,
    },
    "growth": {
        "label": "Growth Equity",
        "description": "Moderate concentration, higher beta tolerance.",
        "max_single_stock_weight": 0.25,
        "max_factor_contribution": 0.80,
        "max_market_contribution": 0.55,
        "max_industry_contribution": 0.35,
        "max_single_factor_loss": -0.12,
        "default_max_loss": 0.20,
        "default_vol_target": 0.18,
    },
    "trading": {
        "label": "Active Trading",
        "description": "Tight concentration, wider factor variance, tighter vol.",
        "max_single_stock_weight": 0.15,
        "max_factor_contribution": 0.85,
        "max_market_contribution": 0.55,
        "max_industry_contribution": 0.40,
        "max_single_factor_loss": -0.12,
        "default_max_loss": 0.15,
        "default_vol_target": 0.15,
    },
    "balanced": {
        "label": "Balanced / Diversified",
        "description": "Middle-ground allocation across sectors and factors.",
        "max_single_stock_weight": 0.25,
        "max_factor_contribution": 0.70,
        "max_market_contribution": 0.50,
        "max_industry_contribution": 0.35,
        "max_single_factor_loss": -0.10,
        "default_max_loss": 0.20,
        "default_vol_target": 0.18,
    },
}
```

Key function: `derive_risk_limits(profile, max_loss, vol_target=None) -> dict`
- Returns a dict compatible with `RiskLimitsData.from_dict()`
- Profile sets structural params (concentration, variance limits, max_single_factor_loss)
- `vol_target` → `portfolio_limits.max_volatility` directly (no leverage scaling — see Leverage Dynamics section)
- `max_loss` → `portfolio_limits.max_loss` — **sign convention:** MCP input is positive (e.g., 0.25 = "I can lose 25%"). `derive_risk_limits()` stores as negative (`-abs(max_loss)`) because `RiskLimitsData.validate()` requires `max_loss < 0`. The `additional_settings.max_loss_input` stores the original positive value for display.
- **Leverage is NOT an input to `derive_risk_limits()`** — it is stored as metadata only. Limits are stored unlevered; the analysis engine handles leverage dynamically at check time (see Leverage Dynamics section).
- Beta limits are NOT baked in here — they're derived downstream at analysis time by `calc_max_factor_betas()` using `max_single_factor_loss` + historical data. Note: `calc_max_factor_betas()` does not take a leverage parameter — beta limits are leverage-unaware. Leverage is captured separately via `calculate_factor_risk_loss()` in the risk scoring path.

Also: `list_profiles() -> dict` — returns all profiles with labels/descriptions for MCP display.

### 2. Enable `additional_settings` JSONB flow — BOTH paths

The `additional_settings` JSONB column exists in the DB but is currently unused. Two separate code paths need patching:

**`inputs/database_client.py`** (the data access layer):
- `save_risk_limits()` (line ~2103): Replace `None` with `json.dumps(risk_limits.get('additional_settings'))` when present, else `None`
- `save_risk_limits()` (line ~2095): Replace hardcoded `"Default"` name with `risk_limits.get('name', 'Default')` — the INSERT currently ignores the `name` field from `RiskLimitsData`, always writing `"Default"`. This must use the caller-supplied name so `Profile_income` etc. persists.
- `get_risk_limits()` (lines ~2021-2024): Un-comment the `additional_settings` reading. Store as separate key:
  ```python
  if result['additional_settings']:
      risk_limits['additional_settings'] = result['additional_settings']
  ```

**`inputs/risk_limits_manager.py`** (the business logic layer — does its own SQL):
- `_load_risk_limits_from_database()` (line ~422): The manager has its own SQL query and dict construction. Un-comment/add `additional_settings` reading here too:
  ```python
  if row["additional_settings"]:
      risk_limits["additional_settings"] = row["additional_settings"]
  ```

Both paths must be patched — the manager does NOT delegate loading to `DatabaseClient.get_risk_limits()`.

**Canonical `additional_settings` shape:**
```json
{
    "profile": "income",
    "max_loss_input": 0.25,
    "vol_target_input": 0.20,
    "leverage_input": 1.0,
    "derived_at": "2026-02-18T12:00:00Z"
}
```

This is always stored as a nested dict under the `additional_settings` key — never flattened into top-level risk limit keys.

**Canonical shape enforcement — the `to_dict()` flattening problem:**

`RiskLimitsManager.save_risk_limits()` (line 278) calls `risk_limits_data.to_dict()`, which flattens `additional_settings` into top-level keys (line 1149: `result.update(self.additional_settings)`). It also omits `name` entirely. By the time the dict reaches `DatabaseClient.save_risk_limits()`, there is no nested `additional_settings` key and no `name` — both are lost.

**Fix: patch `RiskLimitsManager.save_risk_limits()` to re-inject after `to_dict()`:**
```python
# Line 278 in save_risk_limits():
risk_limits_dict = risk_limits_data.to_dict()
# to_dict() flattens additional_settings into top-level — re-inject as nested for DB
if risk_limits_data.additional_settings:
    risk_limits_dict['additional_settings'] = risk_limits_data.additional_settings
# to_dict() omits name — inject for DB persistence
if risk_limits_data.name:
    risk_limits_dict['name'] = risk_limits_data.name
```

This is minimal and surgical. The flattened keys also remain in the dict (harmless — DB save only reads known keys + `additional_settings` + `name`). Downstream consumers that use `to_dict()` output for analysis are unaffected.

**File-mode fallback:** The re-injection happens before the DB/file branch (`save_risk_limits()` line 280). For file mode, the YAML will contain both flattened metadata keys AND nested `additional_settings`. This is acceptable because:
- File mode is a fallback path (rare in production — DB is the primary store)
- On reload, the fixed `_from_yaml_format()` correctly handles both the nested `additional_settings` key and any extra top-level keys (they get merged into `additional_settings`)
- The `_from_yaml_format()` fix (see above) ensures no double-nesting regardless of input shape

**`_from_yaml_format()` double-nesting fix (`core/data_objects.py` line 1219):**

`_from_yaml_format()` uses a dict comprehension that puts ALL non-core keys into `additional_settings` — including a key named `additional_settings` itself. So passing `{"portfolio_limits": {...}, "additional_settings": {"profile": "income"}}` produces `additional_settings = {"additional_settings": {"profile": "income"}}` — double-nested.

**Fix:** Add `additional_settings` to the exclusion list in the dict comprehension, and merge it separately:
```python
@classmethod
def _from_yaml_format(cls, data, user_id=None, portfolio_id=None, name=None):
    core_keys = {'portfolio_limits', 'concentration_limits', 'variance_limits',
                 'max_single_factor_loss', 'additional_settings'}
    extra = {k: v for k, v in data.items() if k not in core_keys}
    # Merge explicit additional_settings with any extra keys
    # Nested additional_settings is authoritative over flattened extras
    raw_additional = data.get('additional_settings', {})
    additional = raw_additional if isinstance(raw_additional, dict) else {}
    if extra:
        additional = {**extra, **additional}  # additional wins on conflict
    return cls(
        portfolio_limits=data.get('portfolio_limits'),
        concentration_limits=data.get('concentration_limits'),
        variance_limits=data.get('variance_limits'),
        max_single_factor_loss=data.get('max_single_factor_loss'),
        additional_settings=additional or None,
        name=name,
        user_id=user_id,
        portfolio_id=portfolio_id,
    )
```

This also fixes the DB load path — when `_load_risk_limits_from_database()` injects `additional_settings` as a nested key, `from_dict()` now handles it correctly.

**Serialization note:** `RiskLimitsData.to_dict()` currently flattens `additional_settings` into top-level keys (line 1149: `result.update(self.additional_settings)`). This is OK for downstream consumption because:
- `from_dict()` re-buckets unknown keys back into `additional_settings` (line 1219)
- Downstream consumers (`resolve_risk_config()`, `evaluate_portfolio_risk_limits()`) only access known keys and ignore extras
- Round-trip is safe: `from_dict(data.to_dict())` preserves the profile metadata

No schema migration needed — column already exists.

### 3. Add `set_risk_profile()` to RiskLimitsManager

**`inputs/risk_limits_manager.py`**:

```python
def set_risk_profile(self, portfolio_name: str, profile: str,
                     max_loss: float, vol_target: float = None,
                     leverage: float = 1.0) -> RiskLimitsData:
    """Derive limits from profile + inputs, persist with metadata.

    max_loss: positive float (e.g. 0.25 = 25%). Stored as negative internally.
    """
    from core.risk_profiles import derive_risk_limits, RISK_PROFILES

    limits_dict = derive_risk_limits(profile, max_loss, vol_target)
    # derive_risk_limits() stores max_loss as -abs(max_loss) for validate() compat
    additional_settings = {
        "profile": profile,
        "max_loss_input": abs(max_loss),  # always positive for display
        "vol_target_input": vol_target or RISK_PROFILES[profile]["default_vol_target"],
        "leverage_input": leverage,
        "derived_at": datetime.utcnow().isoformat(),
    }
    limits_dict["additional_settings"] = additional_settings
    risk_limits_data = RiskLimitsData.from_dict(
        limits_dict, user_id=self.user_id, name=f"Profile_{profile}")
    # save_risk_limits() calls to_dict() internally, then re-injects
    # additional_settings and name (see Section 2 fix)
    success = self.save_risk_limits(risk_limits_data, portfolio_name)
    if not success:
        raise RuntimeError(f"Failed to persist risk profile '{profile}' for {portfolio_name}")
    return risk_limits_data
```

Also update `_get_default_risk_limits()` to use `derive_risk_limits("balanced", 0.25)` instead of hardcoded values — new users get profile-derived defaults.

**Ripple effects of changing defaults:**
- `services/auth_service.py` (~line 169): Uses defaults during onboarding — will automatically get profile-derived values via `_get_default_risk_limits()`. No code change needed if it calls through the manager.
- `inputs/risk_limits_manager.py` (~line 822): `reset_risk_limits()` hardcodes print messages with old default values ("Portfolio max volatility: 40%"). Update these to reflect the new balanced profile values.
- `services/claude/function_executor.py` (~line 1524): Check if it references old defaults; update if so.

### 4. Two new MCP tools

**`mcp_tools/risk.py`**:

**`set_risk_profile(profile, max_loss, vol_target, leverage, portfolio_name)`**
- `user_email` is internal-only (resolved from env, not exposed in MCP signature) — consistent with existing tool auth pattern (`mcp_server.py` wrappers)
- `leverage` defaults to `None`; when `None`, auto-reads from current portfolio via `PositionService`
- Input validation: profile must be valid enum, max_loss clamped to 0.05-0.50 range, vol_target clamped to 0.05-0.50, leverage clamped to 0.5-3.0
- Returns: applied limits, profile info, what changed
- Examples: "Set income profile with 25% max loss", "Switch to growth profile", "Set growth profile at 1.5x leverage"

**`get_risk_profile(portfolio_name)`**
- Loads current limits, extracts profile metadata from `additional_settings`
- If `additional_settings` is null (pre-profile/legacy limits): returns `profile: null` with a note
- Returns: current profile, user inputs, derived limits, list of available profiles
- Examples: "What's my current risk profile?", "Show available risk profiles"

**`mcp_server.py`**: Register both tools. Follow existing pattern — thin wrappers that call the `mcp_tools/risk.py` functions with `user_email=None`.

### 5. Profile preset calibration

The profile values need to be sensible for real portfolios. Key calibration points based on the current portfolio (income-style):

| Parameter | Old Default | Income Profile | Rationale |
|-----------|-------------|----------------|-----------|
| max_single_stock_weight | 0.40 | 0.45 | DSU is 37% — income portfolios run concentrated |
| max_factor_contribution | 0.30 | 0.85 | Current portfolio is 77% — any stock portfolio is factor-dominated |
| max_market_contribution | 0.50 | 0.60 | Slight uplift for equity-heavy |
| max_industry_contribution | 0.30 | 0.50 | REIT concentration normal for income |
| max_single_factor_loss | -0.10 | -0.15 | -0.10 produces 0.43 max market beta; -0.15 produces ~0.65 — still tight but achievable |
| max_volatility | 0.40 | 0.20 (vol_target) | User specifies |
| max_loss | -0.25 | user input | User specifies |

The `max_factor_contribution` is the biggest fix — 0.30 was absurdly low. Even a diversified equity portfolio is typically 60-80% factor-driven. The old default was producing guaranteed violations.

**Cross-profile consistency:** Concentration limits increase with portfolio style tolerance: trading (0.15) < growth (0.25) = balanced (0.25) < income (0.45). Growth and balanced share the same concentration limit but differ in factor/industry tolerance.

## Leverage Dynamics

**Core principle: limits are stored unlevered. The analysis engine handles leverage dynamically.**

- `additional_settings` stores `leverage_input` — the leverage at the time of profile configuration. This is informational metadata, NOT used to scale stored limits.
- `derive_risk_limits()` does NOT take leverage as an input. The stored `max_volatility` is the user's vol target. The stored `max_single_stock_weight` is the profile's concentration cap. These are unlevered intent.
- At analysis time:
  - `evaluate_portfolio_risk_limits()` compares live portfolio metrics (which already reflect leverage) against stored limits. A levered portfolio naturally shows higher vol and betas — the checks catch it.
  - `calc_max_factor_betas()` derives max allowed betas from `max_single_factor_loss / historical_worst_factor_loss`. **It does NOT take a leverage parameter.** Its signature is `(portfolio_yaml, risk_yaml, lookback_years, echo, *, stock_factor_proxies, fmp_ticker_map, max_single_factor_loss)`. Beta limits are leverage-unaware.
  - Leverage surfaces through risk scoring: `calculate_factor_risk_loss()` takes `leverage_ratio` and uses it in `factor_beta × worst_case_move × leverage_ratio`. So the risk *score* captures leverage, but the beta *limits* do not.
- **No double-tightening:** limits are never pre-scaled by leverage. Live metrics and risk scoring reflect leverage; stored limits and beta derivation don't. One adjustment, not two.
- If leverage changes significantly (e.g., 1.0× → 1.5×), the agent can note: "you set this at 1.0× but are now running 1.5× — your vol is exceeding your target."
- **Input format assumption:** MCP tools always use live dollar-denominated positions (via `PositionService`), which naturally reflect leverage in the computed metrics. For all-weight percentage inputs, `core/portfolio_config.py:175` normalizes weights to sum to 1.0, which may mask leverage. This is the existing behavior and only affects the CLI/YAML path, not the MCP path.

## How `max_loss` Flows

**Important:** `max_loss` is NOT directly checked by `evaluate_portfolio_risk_limits()`. The 5 risk checks are: volatility, max weight, factor var %, market var %, max industry var %. `max_loss` drives:

1. **Beta limit derivation** — `calc_max_factor_betas()` uses `max_single_factor_loss` (from profile) to derive max allowed betas. The overall `max_loss` informs `calculate_suggested_risk_limits()` for risk scoring.
2. **Risk score calculation** — `calculate_portfolio_risk_score()` uses `max_loss` from `portfolio_limits` as the denominator in excess ratio scoring.
3. **Suggested limits** — `calculate_suggested_risk_limits()` works backward from `max_loss` to suggest what limits would keep the portfolio within tolerance.

A direct max-loss compliance check (e.g., worst-case scenario loss vs `max_loss`) is a potential future enhancement but is out of scope for v1. The current system catches the underlying drivers (vol, beta, concentration) rather than the composite loss outcome.

## How Beta Limits Flow

Beta limits are NOT stored — they're computed at analysis time:

```
User sets: profile="income" → max_single_factor_loss = -0.15
                                    ↓
calc_max_factor_betas() uses: -0.15 / historical_worst_market_loss
                                    ↓
Example: -0.15 / -0.23 = 0.65 max market beta (vs old 0.43)
```

By raising `max_single_factor_loss` from -0.10 to -0.15 in the income profile, the derived max market beta goes from 0.43 (impossible) to ~0.65 (tight but achievable for a REIT-heavy portfolio with market beta ~1.19). This is still a meaningful limit — it just isn't structurally impossible anymore.

## Files to Modify

| File | Change | Size |
|------|--------|------|
| `core/risk_profiles.py` | **New**: profile definitions + `derive_risk_limits()` | ~80 lines |
| `core/data_objects.py` | Fix `_from_yaml_format()` double-nesting of `additional_settings` | ~10 lines |
| `inputs/database_client.py` | Enable `additional_settings` read/write, use caller-supplied `name` instead of hardcoded `"Default"` | ~12 lines |
| `inputs/risk_limits_manager.py` | Patch `save_risk_limits()` to re-inject `additional_settings`+`name` after `to_dict()`, enable `additional_settings` in SQL load, add `set_risk_profile()`, update `_get_default_risk_limits()`, update `reset_risk_limits()` print messages | ~45 lines |
| `mcp_tools/risk.py` | Add `set_risk_profile()` + `get_risk_profile()` MCP tools | ~100 lines |
| `mcp_server.py` | Register 2 new tools | ~20 lines |

## What Doesn't Change

- `evaluate_portfolio_risk_limits()` — same dict in, same checks out
- `evaluate_portfolio_beta_limits()` — same beta checks
- `calc_max_factor_betas()` — still derives beta limits from `max_single_factor_loss` + historical data (no leverage parameter)
- `RiskLimitsData` dataclass — fields unchanged. Only fix: `_from_yaml_format()` dict comprehension to avoid double-nesting `additional_settings`
- `resolve_risk_config()` — still normalizes the same dict structure
- `core/portfolio_analysis.py` — same consumption path
- DB schema — no migration (`additional_settings` JSONB column already exists)

## Verification

1. Set income profile via MCP: `set_risk_profile(profile="income", max_loss=0.25, vol_target=0.15)`
2. Run `get_risk_analysis(format="agent")` — should see dramatically fewer violations
3. Run `get_risk_profile()` — should show profile metadata and current limits
4. Run `get_risk_score()` — score should reflect calibrated limits
5. Verify DB: `additional_settings` JSONB should contain profile metadata
6. Test round-trip: load limits from DB, verify profile info preserved
7. Test legacy path: load limits that have no `additional_settings` — `get_risk_profile()` returns `profile: null` gracefully
8. Test default seeding: new portfolio gets balanced-profile defaults

## Decisions Made

1. **Four inputs, everything derived.** Profile + max_loss + vol_target + leverage → all limits. User doesn't need to think about `max_factor_contribution`.
2. **Store inputs, not just outputs.** `additional_settings` JSONB stores the profile name and user inputs so limits can be recalculated when historical data updates.
3. **No DB migration.** `additional_settings` JSONB column already exists and is unused.
4. **Beta limits stay derived.** `max_single_factor_loss` from the profile flows through existing `calc_max_factor_betas()` at analysis time — no need to store beta limits.
5. **4 profiles is enough.** Income, growth, trading, balanced. Can add more later if needed.
6. **Downstream untouched.** All changes are in how limits get seeded/configured, not how they get consumed.
7. **Legacy limits handled gracefully.** `get_risk_profile()` checks `additional_settings` — if null (pre-profile limits), returns `profile: null` with a note that these are legacy limits. No crash, no forced migration.
8. **Extensible by design.** Adding a new parameter = add to profile presets dict + optional arg on `derive_risk_limits()` + store in `additional_settings`. No schema migrations, no downstream changes.
9. **Limits stored unlevered.** `derive_risk_limits()` does not take leverage. Stored limits represent unlevered intent. The analysis engine applies live leverage dynamically — no double-tightening.
10. **`max_loss` is not a hard compliance check (v1).** It drives beta derivation and risk scoring, not a direct pass/fail check. Adding a scenario-based max-loss compliance check is a future enhancement.
11. **Cross-profile concentration consistency.** trading (0.15) < growth (0.25) = balanced (0.25) < income (0.45). Growth and balanced share concentration but differ in factor/industry tolerance.
12. **MCP auth follows existing pattern.** `user_email` is internal-only, resolved from env. Not exposed in MCP tool signatures.
13. **Both DB paths patched.** `RiskLimitsManager._load_risk_limits_from_database()` and `DatabaseClient.get_risk_limits()` both need `additional_settings` un-commented. The manager does its own SQL, separate from the DB client.
14. **Input validation on MCP tools.** Profile: strict enum. max_loss: 0.05-0.50. vol_target: 0.05-0.50. leverage: 0.5-3.0.

## Codex Review Notes

### v1 → v2 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | `additional_settings` won't round-trip unless manager path also patched | High | **Fixed**: Both `DatabaseClient.get_risk_limits()` and `RiskLimitsManager._load_risk_limits_from_database()` get patched. Explicitly called out in plan. |
| 2 | `to_dict()` / `from_dict()` serialization creates two valid shapes | High | **Accepted with documentation**: Flattening is existing behavior, round-trip safe via `from_dict()` re-bucketing. Canonical shape documented. Downstream consumers ignore unknown keys. |
| 3 | Leverage double-tightening — pre-scaling limits AND live metric adjustment | High | **Fixed**: `derive_risk_limits()` no longer takes leverage. Limits stored unlevered. Leverage handled at analysis time by live metrics in `evaluate_portfolio_risk_limits()` and by `calculate_factor_risk_loss()` in risk scoring. Note: `calc_max_factor_betas()` does not take leverage (corrected in v3). |
| 4 | `max_loss` not directly checked in compliance evaluator | Medium | **Noted as v1 scope**: max_loss drives beta derivation and risk scoring. Direct scenario-based max-loss check is future enhancement. |
| 5 | Cross-profile concentration inconsistency (balanced > growth) | Medium | **Fixed**: Balanced concentration lowered from 0.30 to 0.25, matching growth. They differ on factor/industry tolerance instead. |
| 6 | Breaking-change ripple broader than `_get_default_risk_limits()` | Medium | **Noted**: `reset_risk_limits()` print messages and `auth_service.py` onboarding identified as additional touchpoints. |
| 7 | MCP tool should not expose `user_email` | Medium | **Fixed**: `user_email` is internal-only, resolved from env per existing pattern. |

### v2 → v3 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 8 | `calc_max_factor_betas()` doesn't take `current_leverage` — plan claims it does | High | **Fixed**: Corrected all references. `calc_max_factor_betas()` signature is `(portfolio_yaml, risk_yaml, lookback_years, echo, *, stock_factor_proxies, fmp_ticker_map, max_single_factor_loss)` — no leverage parameter. Leverage surfaces via `calculate_factor_risk_loss()` in risk scoring, not in beta limit derivation. Plan sections updated: Leverage Dynamics, Beta Limits Flow, What Doesn't Change, derive_risk_limits docstring. |
| 9 | `additional_settings` canonical shape inconsistent with serialization | Medium | **Fixed**: `set_risk_profile()` passes `limits_dict` with nested `additional_settings` to `save_risk_limits()`. The `to_dict()` flattening only affects downstream consumption, not DB persistence. `save_risk_limits()` reads `additional_settings` as a nested dict and `json.dumps()` it directly. |
| 10 | `max_loss` sign handling ambiguous — MCP input positive, `validate()` expects negative | Medium | **Fixed**: Explicit sign convention documented. MCP input is positive (0.25 = 25% loss tolerance). `derive_risk_limits()` stores as `-abs(max_loss)`. `additional_settings.max_loss_input` stores positive for display. |
| 11 | `name=f"Profile_{profile}"` vs DB INSERT hardcoded `"Default"` | Low | **Fixed**: `save_risk_limits()` line ~2095 must use `risk_limits.get('name', 'Default')` instead of hardcoded `"Default"`. Explicit callout added to database_client.py changes. |

### v3 → v4 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 12 | `save_risk_limits()` calls `to_dict()` which flattens `additional_settings` — nested dict lost before DB write | High | **Fixed**: Patch `RiskLimitsManager.save_risk_limits()` to re-inject `risk_limits_data.additional_settings` and `risk_limits_data.name` into the dict after `to_dict()`. Minimal, surgical — only the save path is touched. |
| 13 | `name` not included in `to_dict()` output — profile name lost before DB write | Medium | **Fixed**: Same patch as #12 — re-inject `risk_limits_data.name` into dict after `to_dict()`. |
| 14 | Weight-normalized inputs mask leverage in compliance metrics | Low/Medium | **Documented as assumption**: MCP tools always use dollar-denominated positions which reflect leverage. Weight-normalized CLI/YAML path is existing behavior, not affected by this change. |

### v4 → v5 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 15 | `_from_yaml_format()` double-nests `additional_settings` — dict comprehension catches ALL non-core keys including `additional_settings` itself | High | **Fixed**: Add `additional_settings` to exclusion set in `_from_yaml_format()`. Merge explicit `additional_settings` dict with any extra keys separately. Code change added to `core/data_objects.py` in plan + Files to Modify. |
| 16 | Re-injection patch pollutes file-mode fallback YAML with both flattened and nested shapes | Medium | **Accepted with mitigation**: File mode is a rare fallback. The `_from_yaml_format()` fix (finding 15) ensures correct reload regardless of shape — no double-nesting on round-trip. |
| 17 | `set_risk_profile()` ignores `save_risk_limits()` return value — could report success on failed save | Medium | **Fixed**: Check `save_risk_limits()` return; raise `RuntimeError` on failure. MCP tool catches and returns error to agent. |
