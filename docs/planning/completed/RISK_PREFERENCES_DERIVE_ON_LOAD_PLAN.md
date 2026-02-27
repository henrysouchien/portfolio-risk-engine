# Plan: Risk Preferences Config Layer (Derive on Load)

_Created: 2026-02-18_
_Last updated: 2026-02-19 (Implemented)_
_Status: Complete (moved to completed plans)_

## Context

Profile-based risk limits are working — `set_risk_profile(profile="income", max_loss=0.25, vol_target=0.2)` derives limits and writes them to the DB. But limits are baked at set-time. If we update a profile definition (e.g., raise income's `max_factor_contribution` from 0.85 to 0.90), existing portfolios don't pick it up because the old derived value is already in the DB.

The user wants risk preferences stored as first-class config — the user's intent (profile + inputs) is the source of truth, and limits are derived on the fly from current profile definitions.

## Approach

**Derive on load, not on set.** The `additional_settings` JSONB already stores the user's preferences (`profile`, `max_loss_input`, `vol_target_input`, `leverage_input`, `derived_at`). The change is: when loading risk limits, if preferences are present, re-derive from current profile definitions instead of trusting the baked flat columns.

~20 lines of code. No schema changes, no new tables, no new MCP tools.

## Changes

### 1. Add re-derivation to `_load_risk_limits_from_database()`

**`inputs/risk_limits_manager.py`** — after building `risk_limits` dict and loading `additional_settings` (line ~430), before returning:

```python
# After line 430 (additional_settings loaded):
# Re-derive from preferences if profile metadata is present
additional = risk_limits.get("additional_settings")
if additional and isinstance(additional, dict) and additional.get("profile"):
    try:
        from core.risk_profiles import derive_risk_limits, RISK_PROFILES
        profile = str(additional.get("profile", "")).strip().lower()
        max_loss = additional.get("max_loss_input")
        vol_target = additional.get("vol_target_input")
        # Only re-derive if profile is known and values are valid positive floats
        def _valid_pref(v):
            return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 < v <= 1.0
        if profile in RISK_PROFILES and _valid_pref(max_loss) and _valid_pref(vol_target):
            fresh = derive_risk_limits(profile, float(max_loss), float(vol_target))
            # Override baked limits with freshly derived ones
            risk_limits["portfolio_limits"] = fresh["portfolio_limits"]
            risk_limits["concentration_limits"] = fresh["concentration_limits"]
            risk_limits["variance_limits"] = fresh["variance_limits"]
            risk_limits["max_single_factor_loss"] = fresh["max_single_factor_loss"]
            # additional_settings preserved — preferences remain authoritative
    except Exception as e:
        # Re-derivation failed — keep baked DB values as safe fallback
        print(f"⚠️ Profile re-derivation failed, using baked limits: {e}")
```

**Behavior:**
- Profile-based limits (have `additional_settings.profile` + required keys): always re-derived from current profile definitions
- Partial metadata (missing `max_loss_input` or `vol_target_input`): skip re-derive, use baked DB values
- Unknown profile (removed from `RISK_PROFILES`): skip re-derive, use baked DB values
- Re-derivation error: catch, warn, use baked DB values
- Legacy/manual limits (no `additional_settings` or no `profile` key): use baked DB values as-is (no change)
- DB flat columns become a snapshot/cache — still written by `set_risk_profile()` for DB readability, but overridden on load

### 2. Add re-derivation to `DatabaseClient.get_risk_limits()`

**`inputs/database_client.py`** — same re-derivation block after `additional_settings` is loaded (line ~2022). This ensures all consumers get fresh limits, not just the manager path.

`services/trade_execution_service.py` (line ~1638) reads limits via `DatabaseClient.get_risk_limits()` directly — without this patch, trade-time risk checks would use stale baked values while MCP tools use fresh ones.

Same code pattern as the manager path — guarded with try/except, skips on missing keys or unknown profile.

## What Doesn't Change

- `set_risk_profile()` — still writes derived limits + preferences to DB (snapshot useful for DB queries/debugging)
- `get_risk_profile()` — still reads from loaded limits (now freshly derived)
- `derive_risk_limits()` — same function, called from two additional places
- DB schema — no migration
- `additional_settings` shape — same keys
- All downstream analysis — same `RiskLimitsData.to_dict()` structure

## Files to Modify

| File | Change | Size |
|------|--------|------|
| `inputs/risk_limits_manager.py` | Add re-derivation block in `_load_risk_limits_from_database()` after line ~430 | ~15 lines |
| `inputs/database_client.py` | Add re-derivation block in `get_risk_limits()` after line ~2022 | ~15 lines |

## Verification

1. Current state: `get_risk_profile()` — shows income profile with current limits
2. Temporarily change a profile value in `core/risk_profiles.py` (e.g., income `max_factor_contribution` 0.85 → 0.90)
3. Reconnect MCP (`/mcp`)
4. `get_risk_profile()` — should show `max_factor_contribution: 0.90` without re-setting the profile
5. `get_risk_analysis(format="agent")` — compliance checks use new derived value
6. Revert test change in `risk_profiles.py`
7. Test legacy path: manually remove `profile` from `additional_settings` in DB — limits should fall back to baked values
8. Test malformed metadata: set `additional_settings` to `{"profile": "income"}` (missing max_loss_input) — should skip re-derive, use baked values

## Codex Review Notes

### v1 → v2 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | `derive_risk_limits()` can raise on bad data, crashing load | High | **Fixed**: Wrapped in try/except. On failure, keeps baked DB values and prints warning. |
| 2 | Case-sensitive profile matching | Medium | **Fixed**: Normalize with `.strip().lower()` before lookup. |
| 3 | `DatabaseClient.get_risk_limits()` is a separate load path | Medium | **Fixed**: Added same re-derivation block to `database_client.py`. Trade execution and other direct consumers get fresh limits too. |
| 4 | Missing preference keys silently alter intent via defaults | Medium | **Fixed**: Require `max_loss_input` AND `vol_target_input` present. Skip re-derive if either is missing. |
| 5 | No automated tests | Low | **Noted**: Manual verification sufficient for this scope. Can add unit tests as follow-up. |

### v2 → v3 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 6 | Non-string `profile` value crashes `.strip().lower()` before try/except | High | **Fixed**: Moved all normalization inside try/except. Use `str(additional.get("profile", "")).strip().lower()` for safe coercion. |
| 7 | `None`/invalid-type values for `max_loss_input`/`vol_target_input` can drift | Medium | **Fixed**: Validate with `isinstance(val, (int, float))` before re-derive. Skip on `None`, strings, or other non-numeric types. Explicit `float()` cast for safety. |

### v3 → v4 resolutions

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 8 | `bool` is subclass of `int` — `True`/`False` pass isinstance check | Medium | **Fixed**: Added `not isinstance(v, bool)` exclusion in `_valid_pref()` helper. |
| 9 | No finite/range guard — 0, negatives, huge values could slip through | Medium | **Fixed**: `_valid_pref()` requires `0 < v <= 1.0` (both max_loss and vol_target are fractions in 0-1 range). |
