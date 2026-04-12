# Fix: Schwab OAuth SSL Certificate — mkcert + Monkey-Patch

## Context

schwab-py's `client_from_login_flow()` spawns a Flask subprocess with `ssl_context='adhoc'` (ephemeral self-signed cert). Modern Chrome/Safari silently reject these certs — the OAuth redirect fails silently, Flask never receives the callback. Fix: use `mkcert` to generate a locally-trusted certificate, then monkey-patch schwab-py's server function to use it.

## Changes: 3 Files

### 1. `brokerage/config.py` — add cert path constants (after line 16)

```python
SCHWAB_SSL_CERT_PATH: str = os.path.expanduser("~/.schwab_auth/127.0.0.1.pem")
SCHWAB_SSL_KEY_PATH: str = os.path.expanduser("~/.schwab_auth/127.0.0.1-key.pem")
```

### 2. `brokerage/schwab/client.py` — add patch function + apply it

**A) Add module-level `_original_server_fn: Any = None` sentinel** to cache the true original.

**B) Add `_apply_mkcert_ssl_patch(auth_module)` function** before `schwab_login()`:
- On first call: saves the true original via `_original_server_fn = getattr(auth_module, '__run_client_from_login_flow_server')` (only when `_original_server_fn is None`)
- Checks if cert+key exist at configured paths
- If missing: **restores original** via `setattr(auth_module, '__run_client_from_login_flow_server', _original_server_fn)`, logs warning pointing to `setup-ssl`, returns. Because `_original_server_fn` is captured once before any patch, this always restores the true schwab-py function — not a stale closure from a prior patch.
- If present: defines `_patched_server(q, callback_port, callback_path)` — identical to schwab-py's original `__run_client_from_login_flow_server` except `ssl_context=(cert_path, key_path)` instead of `ssl_context='adhoc'`
- Applies via `setattr(auth_module, '__run_client_from_login_flow_server', _patched_server)`
- The patched function is a closure capturing cert/key paths as strings — serializes cleanly via `dill`/`multiprocess`

**B) In `schwab_login()`, after `auth = _load_schwab_auth_module()` (line 252), add:**
```python
_apply_mkcert_ssl_patch(auth)
```
Applied unconditionally — only affects `client_from_login_flow`, not `client_from_manual_flow`.

### 3. `scripts/run_schwab.py` — add `setup-ssl` subcommand

`cmd_setup_ssl()`:
1. Check for `mkcert` via `shutil.which('mkcert')`. If missing, attempt `brew install mkcert`. If Homebrew also missing, print manual install instructions and exit with error.
2. Run `mkcert -install` (installs local CA to macOS keychain, idempotent)
3. Create `~/.schwab_auth/` directory
4. Run `mkcert -cert-file ~/.schwab_auth/127.0.0.1.pem -key-file ~/.schwab_auth/127.0.0.1-key.pem 127.0.0.1`

Register in parser + handlers dict.

## Why the monkey-patch works

- `__run_client_from_login_flow_server` is module-level (no class name mangling)
- `client_from_login_flow` resolves `target=__run_client_from_login_flow_server` via module globals at call time
- `setattr(auth, '__run_client_from_login_flow_server', patched_fn)` modifies the same globals dict
- Patch is applied between `_load_schwab_auth_module()` and `client_from_login_flow()` — guaranteed to be picked up

## Usage

```bash
# One-time setup (once per machine)
python3 -m scripts.run_schwab setup-ssl

# Login (now works in Chrome/Safari)
python3 -m scripts.run_schwab login
```

## Verification

1. `python3 -m scripts.run_schwab setup-ssl` — generates certs, no errors
2. `python3 -m scripts.run_schwab login` — Flask starts with mkcert certs, browser completes redirect without SSL warning
3. `pytest tests/brokerage/test_schwab_client.py -v` — existing tests still pass
