> **✅ SHIPPED — fix(mcp) repair Phase 7 test fallout. Moved during 2026-05-26 docs cleanup.**

# MCP Tools Test Failures — Fix Plan

**Status**: Codex R1 PASS — ready for implementation
**Scope**: 28 failing tests in `tests/mcp_tools/`
**Root cause**: Phase 7 (`f9c12dea feat(mcp): portfolio-mcp per-user identity`) replaced `settings.get_default_user()` with `settings.resolve_user_email()` + `UserContextError`. Three test files were not updated, and one production wrapper was left referencing a removed symbol.

---

## §1 Failure Inventory

| File | Failing tests | Symptom | Diagnosis |
|---|---|---|---|
| `tests/mcp_tools/test_news_events_portfolio.py` | 16 | `ImportError: cannot import name 'UserContextError' from 'settings'` raised at `mcp_tools/news_events.py:113` | Test fixture `_patch_loader_deps` builds a fake `settings` ModuleType with only `get_default_user` + `INSTITUTION_SLUG_ALIASES`; production code now also imports `UserContextError` and `resolve_user_email` from `settings` (deferred import inside `_resolve_portfolio_user`) |
| `tests/mcp_tools/test_news_events_builder.py` | 3 | Same `ImportError` | Same fake-settings pattern, two call sites (lines 49–52 and 960–963) |
| `tests/mcp_tools/test_performance.py` | 5 | `AttributeError: module 'services.performance_helpers' has no attribute 'get_default_user'` raised at `mcp_tools/performance.py:68` | **Production bug**: `mcp_tools/performance.py:58–67` snapshots/overrides a list of names on `_performance_helpers`, but `services/performance_helpers.py` removed `get_default_user` in Phase 7. Override loop fails before the test's own monkeypatches matter. Test also patches stale name `_resolve_user_id` instead of the new `resolve_user_email` flow. |
| `tests/mcp_tools/test_factor_intelligence.py` | 5 | Real portfolio (27 tickers from `RISK_MODULE_USER_EMAIL=henry.souchien`) flows into `_StubFactorIntelligenceService.recommend_portfolio_offsets`; inner `assert kwargs["weights"] == {"AAPL": 0.6, "MSFT": 0.4}` fails; caller swallows at `factor_intelligence.py:463–465` → `build_ai_recommendations()` returns `[]` → `assert len(recommendations) == 2` fails (`0 == 2`) | `_setup_ai_recommendations` (test line 72–77) patches `settings.get_default_user`, but production now calls `resolve_user_email(None)` — falls back to env var → real DB user_id → `get_portfolio_snapshot` real-DB path |

---

## §2 Production Bug to Fix

### `mcp_tools/performance.py:58–67` — stale override list

```python
overrides = {
    "get_default_user": get_default_user,        # <-- name no longer on _performance_helpers
    "resolve_user_email": resolve_user_email,
    "resolve_user_id": _resolve_user_id,
    ...
}
originals = {name: getattr(_performance_helpers, name) for name in overrides}  # <-- AttributeError
```

After Phase 7, `services/performance_helpers.py:21` imports `UserContextError, format_missing_user_error, resolve_user_email` (no `get_default_user`). The wrapper above tries to read `_performance_helpers.get_default_user` → `AttributeError`. (`settings.get_default_user` itself still exists; the issue is that the helper module no longer re-imports it.)

This affects production, not just tests: every call to `mcp_tools.performance.get_performance` reaches `_select_load_portfolio_for_performance()` at line 551 → `_load_portfolio_for_performance` → AttributeError on the override loop. The fact that nobody noticed in prod suggests the live code path has been routing through the gateway/MCP server differently, but the wrapper is dead code that crashes when invoked.

**Fix**: drop `"get_default_user"` from the `overrides` dict and from the corresponding top-level `from settings import get_default_user, resolve_user_email` (line 36) — `get_default_user` is unused after the override entry is removed.

```python
# mcp_tools/performance.py
- from settings import get_default_user, resolve_user_email
+ from settings import resolve_user_email

  overrides = {
-     "get_default_user": get_default_user,
      "resolve_user_email": resolve_user_email,
      "resolve_user_id": _resolve_user_id,
      ...
  }
```

This is a small, scoped production fix. Per CLAUDE.md, this still goes through Codex review before implementation.

---

## §3 Test Fixes

All three test files are fixed test-side. No further production changes.

### 3.1 `tests/mcp_tools/test_news_events_portfolio.py` (16 failures)

**Where**: `_patch_loader_deps` helper at lines 43–59.

**Change**: extend the fake `settings` module to expose the symbols `mcp_tools/news_events.py` now imports.

```python
# Before
fake_settings = types.ModuleType("settings")
fake_settings.get_default_user = lambda: default_user
fake_settings.INSTITUTION_SLUG_ALIASES = INSTITUTION_SLUG_ALIASES
monkeypatch.setitem(sys.modules, "settings", fake_settings)

# After
class _UserContextError(RuntimeError):
    def __init__(self, message, *, context=None):
        super().__init__(message)
        self.context = dict(context or {})

def _resolve_user_email(email=None, context=None):
    resolved = email or default_user
    return _ResolvedUserEmail(resolved, {"source": "test"})

class _ResolvedUserEmail(str):
    def __new__(cls, value, ctx=None):
        obj = super().__new__(cls, value)
        obj.context = dict(ctx or {})
        return obj
    def __iter__(self):
        yield str(self)
        yield dict(self.context)

fake_settings = types.ModuleType("settings")
fake_settings.get_default_user = lambda: default_user
fake_settings.INSTITUTION_SLUG_ALIASES = INSTITUTION_SLUG_ALIASES
fake_settings.UserContextError = _UserContextError
fake_settings.resolve_user_email = _resolve_user_email
monkeypatch.setitem(sys.modules, "settings", fake_settings)
```

`UserContextError` and `resolve_user_email` are the only deferred imports `news_events.py:113` pulls from settings. (Earlier draft also added `format_missing_user_error` defensively; Codex correctly flagged it as scope creep — this file doesn't import it, so we drop it.)

**Note on test expectation**: `test_load_portfolio_symbols_no_user` (line 99) asserts behavior when the user can't be resolved. The fake `resolve_user_email` should raise `_UserContextError` when no default user is available. Implementation:

```python
def _resolve_user_email(email=None, context=None):
    resolved = email or default_user
    if not resolved:
        raise _UserContextError("no user", context={"user_email": None})
    return _ResolvedUserEmail(resolved, {"source": "test"})
```

I'll re-read all 16 tests during implementation and confirm the stub matches each expected branch — but the shape above is the contract from `utils/user_context.py`.

### 3.2 `tests/mcp_tools/test_news_events_builder.py` (3 failures)

Same fix, applied at both fake-settings sites (lines 49–52 and 960–963). Extract a shared helper if both copies are identical.

### 3.3 `tests/mcp_tools/test_performance.py` (5 failures)

**Smaller change than R0 implied.** Most of the 5 failures are caused purely by the §2 production bug (the override loop crashes before any test code runs). Only one test patches `perf.get_default_user` directly and needs a code-side update.

**Failing tests and required action**:

| Line | Test | What it patches today | Action after §2 fix |
|---|---|---|---|
| 794 | `test_load_portfolio_for_performance_threads_dates_to_portfolio_data` | `perf.get_default_user`, `perf._resolve_user_id`, `perf.PositionService` | **Replace** `perf.get_default_user` patch with `perf.resolve_user_email`; keep `_resolve_user_id` and `PositionService` patches. |
| 837 | `test_load_portfolio_for_performance_uses_position_snapshot_cache` | `perf.PositionService`, `perf._performance_helpers.get_position_result_snapshot`, `perf._resolve_user_id` | No change needed — passes explicit `user_email="test@example.com"`. |
| 887 | `test_load_portfolio_for_performance_can_allow_stale_positions` | (re-check during impl) | Same — passes explicit `user_email`. |
| ~916 | `test_load_portfolio_for_performance_uses_provider_scoped_snapshot_for_filtered_scope` | (re-check during impl) | Same. |
| ~960 | `test_load_portfolio_for_performance_source_specific_realized_uses_unconsolidated_positions` | (re-check during impl) | Same. |

The single replacement at line 818:

```python
# Before
monkeypatch.setattr(perf, "get_default_user", lambda: "default@example.com")

# After
monkeypatch.setattr(
    perf,
    "resolve_user_email",
    lambda email=None: ("default@example.com", {"source": "test"}),
)
```

Why this works: after the §2 fix, `mcp_tools/performance.py:58–67` overrides `resolve_user_email` and `resolve_user_id` on `_performance_helpers` using values pulled from `mcp_tools.performance`'s own module attributes. Patching `perf.resolve_user_email` therefore propagates through. The other four tests already pass explicit `user_email` so the resolution path is short-circuited and they only needed the production bug fixed.

During implementation I will re-read each of the five failing tests to confirm this matches reality before sending to Codex.

### 3.4 `tests/mcp_tools/test_factor_intelligence.py` (5 failures)

**Where**: `_setup_ai_recommendations` helper (lines 72–77).

**Problem**: the helper patches `settings.get_default_user`, but `factor_intelligence.py:303` uses a deferred `from settings import UserContextError, resolve_user_email` and calls `resolve_user_email(None)`. With the patch ineffective:
1. `resolve_user_email(None)` falls back to env → returns real `henry.souchien@gmail.com`.
2. `resolve_user_id("henry.souchien@gmail.com")` returns 1 (real user).
3. `get_portfolio_snapshot(1, "CURRENT_PORTFOLIO")` returns the real 27-ticker portfolio.
4. `service.recommend_portfolio_offsets(weights=<27 tickers>)` triggers the stub's `assert kwargs["weights"] == {"AAPL": 0.6, "MSFT": 0.4}` → fails → caught at line 463 → returns `[]`.

**Fix**: patch `settings.resolve_user_email` and stub the user-id resolution so the workflow-cache path is skipped and the `_StubPositionService` path is taken.

```python
from utils.user_context import ResolvedUserEmail
import utils.user_resolution as _user_resolution

def _setup_ai_recommendations(monkeypatch, factor_service):
    monkeypatch.setattr(settings, "get_default_user", lambda: "user@example.com")
    monkeypatch.setattr(
        settings,
        "resolve_user_email",
        lambda email=None, context=None: ResolvedUserEmail(
            email or "user@example.com", {"source": "test"}
        ),
    )
    # Force resolved_user_id to None so workflow_cache path is bypassed
    # and the _StubPositionService path runs.
    monkeypatch.setattr(_user_resolution, "resolve_user_id", lambda _u: None)

    monkeypatch.setattr(position_service_module, "PositionService", _StubPositionService)
    monkeypatch.setattr(position_snapshot_cache, "PositionService", _StubPositionService)
    position_snapshot_cache.clear_position_snapshot_cache()
    monkeypatch.setattr(factor_tool, "FactorIntelligenceService", factor_service)
```

Three notes:
- **R0 correction**: `ResolvedUserEmail` lives in `utils.user_context`, not `settings`. `settings.py` re-exports `resolve_user_email` and `UserContextError` but not the class. Import it from `utils.user_context`. (Alternative: return a plain string. `factor_intelligence.py:315` does `str(resolve_user_email(user_email))`, so a string would also work — but `ResolvedUserEmail` keeps the contract honest for any code path that does tuple-unpack.)
- The `resolve_user_email` signature accepts `(email, context=None)` to match `utils/user_context.py:188`.
- Patching `utils.user_resolution.resolve_user_id` (the source module) is the only reliable way to intercept the deferred `from utils.user_resolution import resolve_user_id` at `factor_intelligence.py:320`.

`test_build_ai_recommendations_uses_portfolio_snapshot_when_user_id_available` (line 101) is a separate test that passes `user_id=17` explicitly — it bypasses the resolution entirely and patches `workflow_cache` directly. It already works (not in the failure list) and should not be touched.

---

## §4 Verification

After §2 + §3 changes:

```bash
python3 -m pytest tests/mcp_tools/test_news_events_portfolio.py \
                 tests/mcp_tools/test_news_events_builder.py \
                 tests/mcp_tools/test_performance.py \
                 tests/mcp_tools/test_factor_intelligence.py -v
```

Expected: 28 previously-failing tests pass, no new regressions. Then re-run the full `tests/mcp_tools/` suite to confirm 1452 pass / 1 skip.

---

## §5 Out of Scope

- Pydantic V1 → V2 validator deprecation warnings (separate cleanup).
- `datetime.utcnow()` deprecation in `inputs/database_client.py:4954` and `tests/mcp_tools/test_proxy_cache.py:395` (separate cleanup).
- Any broader audit of who else still patches `get_default_user`. Quick grep done as part of §1; no other failing tests reference it. If the §2 fix surfaces additional broken wrappers in other tools, they'll be addressed in their own PRs.

---

## §6 Workflow

Per `CLAUDE.md`:
1. **Plan** (this document) → user approval.
2. **Codex review** of this plan → iterate to PASS.
3. **Codex implementation** via `mcp__codex__codex` (`approval-policy: never`, `sandbox: workspace-write`, `cwd` = repo root, no `model` / `model_reasoning_effort` overrides).
4. Local `pytest` re-run by Claude.
