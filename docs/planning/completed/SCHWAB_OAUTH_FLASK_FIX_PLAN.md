# Fix: Schwab OAuth Flask Crash

## Context

Running `python3 -m scripts.run_schwab login` crashes because Flask can't resolve the `schwab` package path inside the forked subprocess that `schwab-py` spawns for the OAuth callback server.

**Root cause**: `_load_schwab_auth_module()` in `brokerage/schwab/client.py` creates a synthetic `schwab` package in `sys.modules` (to avoid importing `schwab.__init__` which has side effects). The synthetic `ModuleSpec` has two issues: (1) missing `origin` field, and (2) `submodule_search_locations=[]` (empty, falsey). Flask's `_find_package_path` checks `submodule_search_locations` first — because it's falsey, Flask falls through to the non-package branch which calls `os.path.dirname(spec.origin)`. Since `origin` is `None`, it crashes.

**Error trace:**
```
File ".../flask/sansio/scaffold.py", line 751, in _find_package_path
    return os.path.dirname(root_spec.origin)
TypeError: expected str, bytes or os.PathLike object, not NoneType
```

**Call chain:**
1. `scripts/run_schwab.py:51` → `schwab_login(manual=False)`
2. `brokerage/schwab/client.py:252` → `_load_schwab_auth_module()` creates synthetic `schwab` in `sys.modules` with `ModuleSpec(origin=None)`
3. `brokerage/schwab/client.py:277` → `auth.client_from_login_flow()`
4. `schwab/auth.py:263` → `multiprocess.Process(target=__run_client_from_login_flow_server)` — child inherits synthetic `sys.modules['schwab']`
5. `schwab/auth.py:134` → `flask.Flask(__name__)` where `__name__='schwab.auth'`
6. Flask resolves root module `'schwab'` → gets synthetic spec → `os.path.dirname(None)` → crash

## Fix

**File:** `brokerage/schwab/client.py` (line 63-67)

Add `origin` and `submodule_search_locations` to the `ModuleSpec` constructor so the synthetic spec fully matches a real package:

```python
# Before (broken):
pkg_module.__spec__ = importlib.machinery.ModuleSpec(
    name=pkg_name,
    loader=None,
    is_package=True,
)

# After (fixed):
pkg_module.__spec__ = importlib.machinery.ModuleSpec(
    name=pkg_name,
    loader=None,
    origin=str(pkg_dir / "__init__.py"),
    is_package=True,
)
pkg_module.__spec__.submodule_search_locations = [str(pkg_dir)]
```

**Why this is correct:**
- `origin`: Line 60 already sets `pkg_module.__file__` to the same path — `origin` should match `__file__` for file-based modules. Flask uses `os.path.dirname(origin)` to find the package dir.
- `submodule_search_locations`: `ModuleSpec(..., is_package=True)` creates an empty `[]` which is falsey. Flask checks this to determine if the module is a package — falsey causes it to fall through to the non-package branch. Setting it to `[str(pkg_dir)]` matches the real schwab package's spec and ensures Flask takes the correct package path.
- `pkg_dir` is resolved from the real schwab package (line 58), so both paths are valid
- Both are purely metadata — no imports or side effects, does not break lazy-loading

## Verification

1. `python3 -m scripts.run_schwab login` — Flask callback server should start without crashing
2. Run existing tests: `pytest tests/brokerage/test_schwab_client.py -v`
