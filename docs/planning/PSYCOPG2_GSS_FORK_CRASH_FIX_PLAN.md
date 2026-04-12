# Fix: Disable GSS/Kerberos probe on psycopg2 connections (macOS fork crash)

## Context

Celery prefork workers segfault (`SIGSEGV` in `_os_log_preferences_refresh`) when
creating their first PostgreSQL connection. The root cause: libpq probes for
Kerberos/GSS credentials on every new connection by default. On macOS, this probe
calls into XPC, which inherits invalid mach port state from the parent process
after `fork()`. The child dereferences a stale pointer and crashes.

### Crash chain

```
psycopg2.connect()
  → PQconnectdb()                    # libpq opens connection
  → pg_GSS_have_cred_cache()         # libpq checks for Kerberos tickets
  → gss_acquire_cred()               # GSS probes macOS credential store
  → krb5_cccol_have_content()        # Kerberos reads cache
  → xpc_connection_resume()          # XPC uses inherited (invalid) mach port
  → _os_log_preferences_refresh()    # reads unmapped address → SIGSEGV
```

### Why it crashes in the forked child

`fork()` copies the parent's memory (including XPC connection structs) but does NOT
duplicate kernel-side mach ports. The child inherits structs that look valid but
point to non-existent kernel resources. When XPC tries to use them, it dereferences
a stale pointer into unmapped memory.

## Scope

**This fix targets the Celery prefork crash only.** The crash requires `fork()` +
subsequent `psycopg2.connect()` in the child — a combination that only occurs in
Celery workers (prefork pool). Standalone scripts (`run_migrations.py`,
`health_check.py`) and test fixtures run in a single process and are not affected.

## Connection audit (for reference)

9 `psycopg2.connect()` / pool creation points across 5 files:

| # | File | Line | Type | Affected by fork crash? |
|---|------|------|------|------------------------|
| 1 | `app_platform/db/pool.py` | 63 | `ThreadedConnectionPool()` | YES — crash site |
| 2 | `fmp/estimate_store.py` | 105 | `psycopg2.connect()` | YES if called in worker |
| 3 | `fmp/estimate_store.py` | 120 | `SimpleConnectionPool()` | YES if called in worker |
| 4 | `scripts/run_migrations.py` | 12 | `psycopg2.connect()` | No — single process |
| 5 | `scripts/run_migrations.py` | 34 | `psycopg2.connect()` | No — single process |
| 6 | `scripts/health_check.py` | 178 | `psycopg2.connect()` | No — single process |
| 7 | `tests/fmp/test_estimate_store.py` | 49 | `psycopg2.connect()` | No — single process |
| 8 | `tests/fmp/test_estimate_store.py` | 65 | `psycopg2.connect()` | No — single process |
| 9 | `tests/fmp/test_estimate_store.py` | 74 | `psycopg2.connect()` | No — single process |

## Approach — `PGGSSENCMODE` environment variable

libpq reads `PGGSSENCMODE` automatically for all connections when no explicit
`gssencmode` is in the DSN or kwargs. It provides a default — lower precedence
than DSN params, so it respects explicit config if ever set.

Set it once in `workers/celery_app.py` at module level. This module is imported
by the Celery parent process before it forks children, so the env var is inherited
by all worker children. `setdefault` preserves any explicit value.

Note: `workers.celery_app` is also imported by beat (`workers/beat_schedule.py`),
the API lifespan (`app.py`), and sync polling (`services/sync_runner.py`). The
env var will therefore be set in those processes too. This is harmless — disabling
the GSS probe just skips an unused Kerberos check. The env var only *matters* in
the Celery prefork case where the probe crashes after `fork()`.

## Changes

### 1. `workers/celery_app.py` — `setdefault` at module top (after `import os`)

```python
# Prevent macOS fork crash: libpq's default GSS/Kerberos credential probe
# calls into XPC which is not fork-safe. Only applies if not already set.
os.environ.setdefault("PGGSSENCMODE", "disable")
```

This runs at import time in the parent process, before Celery forks worker children.
Children inherit the env. `setdefault` preserves any explicit value from `.env`.

### 2. `tests/workers/test_celery_app_config.py` — source-level regression test

```python
def test_celery_app_sets_pggssencmode_at_module_scope():
    """workers/celery_app.py must call os.environ.setdefault("PGGSSENCMODE", "disable")
    at module scope (not inside a function/class) so it runs at import time before fork."""
    import ast
    from pathlib import Path

    source = Path(celery_app.__file__).read_text()
    tree = ast.parse(source)

    found = False
    for node in ast.iter_child_nodes(tree):  # only top-level statements
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        # Match: os.environ.setdefault("PGGSSENCMODE", "disable")
        func = call.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "setdefault"
            and isinstance(func.value, ast.Attribute)
            and func.value.attr == "environ"
            and isinstance(func.value.value, ast.Name)
            and func.value.value.id == "os"
            and len(call.args) >= 2
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value == "PGGSSENCMODE"
            and isinstance(call.args[1], ast.Constant)
            and call.args[1].value == "disable"
        ):
            found = True
            break

    assert found, (
        'os.environ.setdefault("PGGSSENCMODE", "disable") '
        "not found at module scope in workers/celery_app.py"
    )
```

AST-based assertion that verifies:
- The exact `setdefault` call exists with key `"PGGSSENCMODE"` and value `"disable"`
- It's at module top level (`ast.iter_child_nodes(tree)` only yields top-level statements)
- Not inside a function, class, or conditional

No `importlib.reload`, no env-state dependency.

## What this does NOT change

- No kwargs added to any `psycopg2.connect()` or pool constructor
- No changes to `.env`, `DATABASE_URL` format, or `services.yaml`
- No changes to Celery config, fork behavior, or pool sizing
- No new dependencies

## Codex review history

### R1 findings

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | High | Hard-disabling GSS via kwargs overrides DSN intent | Switched to `PGGSSENCMODE` env var (lower precedence) |
| 2 | Medium | Count says 8, table has 9 | Fixed count to 9 |
| 3 | Medium | No test assertion for the fix | Added env var presence test |

### R2 findings

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | Medium | Test is tautology (monkeypatch then assert same var) | Rewrote: reload module, test both set/unset cases |
| 2 | Low | "covers all 9 sites" overstates — scripts don't load .env | Narrowed scope to Celery fork crash; added fork-affected column |

### R3 findings

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | Medium | `.env` change affects API/beat (non-forking) — broader than stated scope | Dropped `.env`/`.env.example` changes; `celery_app.py` setdefault alone suffices |
| 2 | Medium | `importlib.reload` duplicates Celery signal handlers, polluting test suite | Dropped reload; assert env var from already-imported module instead |

### R4 findings

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | Medium | Test passes if env already set externally, not reliable | Switched to source-level assertion via `inspect.getsource` |
| 2 | Medium | Scope claim inaccurate — celery_app imported by beat/API/sync too | Fixed: acknowledged all importers, clarified env var is harmless in non-fork contexts |

### R5 findings

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | Medium | Source assertion doesn't check value — `prefer`/`allow` would pass | Assert exact call including `"disable"` value |

### R6 findings

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | Medium | Source check passes even if setdefault moved into function/conditional | Added runtime assertion (`os.environ.get`) proving import-time execution |

### R7 findings

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | Medium | Runtime check doesn't prove module-scope; passes if env pre-set | Switched to AST check — `ast.iter_child_nodes(tree)` only yields top-level nodes |
| 2 | Medium | Runtime `== "disable"` conflicts with setdefault preservation | Dropped runtime check entirely; AST check is env-independent |

## Verification

1. `python -m pytest tests/workers/test_celery_app_config.py -v`
2. Manual: start a Celery worker and confirm no segfault on first task
