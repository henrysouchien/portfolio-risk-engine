# Plan: Step 9 Cleanup — Remove Local Estimate Fallback

## Context

Steps 1-8 of the earnings estimate AWS migration are complete. The MCP tools now use HTTP → EC2 FastAPI → RDS as the primary path, controlled by `ESTIMATE_API_URL` env var (set in `~/.claude.json`). The local fallback (direct psycopg2 → local Postgres) is dead code. This cleanup removes it along with the deprecated launchd plist.

## Changes

### 1. `fmp/tools/estimates.py` — Remove local fallback code

- Remove the `try/except` import of `EstimateStore` (lines 29-33)
- Remove `_get_estimate_revisions_local()` function (lines 201-272)
- Remove `_screen_local()` function (lines 347-364)
- Remove the `if _ESTIMATE_API_URL` branching — just call HTTP directly
- **Add env guard in both `get_estimate_revisions()` and `screen_estimate_revisions()`**: if `_ESTIMATE_API_URL` is not set, return `{"status": "error", "error": "ESTIMATE_API_URL environment variable is required. Set it to the hosted estimates API URL (e.g. https://financialmodelupdater.com)."}` — prevents `_api_get` from building a malformed URL from `None`. Place the guard **after** input validation (empty ticker check, negative days check) so those fast-fail paths remain independent of env config
- Update docstring to reflect HTTP-only mode

### 2. `tests/mcp_tools/test_estimates.py` — Update tests to mock HTTP path

Current tests monkeypatch `EstimateStore` and route through the local path. After removing the local fallback, tests must mock the HTTP path instead.

- **Set `_ESTIMATE_API_URL`** via monkeypatch so the HTTP path is active: `monkeypatch.setattr(estimates_tool, "_ESTIMATE_API_URL", "http://test")`
- **Mock `_api_get`** instead of `EstimateStore`:
  - `test_get_estimate_revisions_defaults_to_nearest_fiscal_date`: mock `_api_get` to return latest rows on first call, revision rows on second call
  - `test_get_estimate_revisions_returns_error_on_exception`: mock `_api_get` to raise an exception
  - `test_screen_estimate_revisions_filters_direction`: mock `_api_get` to return summary rows
- **Remove `_StoreStub` class** — no longer needed
- **Keep unchanged**: `test_get_estimate_revisions_requires_ticker` (no mock needed — input validation fires before env guard), `test_screen_estimate_revisions_rejects_negative_days` (no mock needed — same reason)
- **Add new test**: `test_get_estimate_revisions_missing_env` — ensure unset `_ESTIMATE_API_URL` returns `{"status": "error"}` with clear message. Monkeypatch `_ESTIMATE_API_URL` to `None`.
- **Add new test**: `test_screen_estimate_revisions_missing_env` — same for screening tool

### 3. `fmp/__init__.py` — Remove `EstimateStore` export

- Remove conditional `EstimateStore` import (lines 53-56)
- Remove `"EstimateStore"` from `__all__` (line 82)

### 4. Sync to fmp-mcp repo

- Copy updated `fmp/tools/estimates.py` → `~/Documents/Jupyter/fmp-mcp/fmp/tools/estimates.py`
- Copy updated `fmp/__init__.py` → `~/Documents/Jupyter/fmp-mcp/fmp/__init__.py`

### 5. Remove launchd plist

- Unload and delete `~/Library/LaunchAgents/com.riskmodule.snapshot_estimates.plist`
- Collection now runs on EC2 via systemd timer

### 6. Keep (do NOT delete)

- `fmp/estimate_store.py` — canonical source, copied to edgar_updater. Keep as reference.
- `fmp/scripts/snapshot_estimates.py` — deprecated but untracked, leave as-is
- `fmp/scripts/create_fmp_data_schema.sql` — canonical schema, keep as reference
- `tests/fmp/test_estimate_store.py` — still valid tests for the EstimateStore class itself
- Local `fmp_data_db` database — keep as backup, can drop later manually

## Files Modified

| File | Action |
|------|--------|
| `fmp/tools/estimates.py` | Remove local fallback functions + branching, add env guard |
| `tests/mcp_tools/test_estimates.py` | Rewrite mocks: `_StoreStub` → `_api_get` mock |
| `fmp/__init__.py` | Remove `EstimateStore` export |
| `~/Documents/Jupyter/fmp-mcp/fmp/tools/estimates.py` | Sync from risk_module |
| `~/Documents/Jupyter/fmp-mcp/fmp/__init__.py` | Sync from risk_module |
| `~/Library/LaunchAgents/com.riskmodule.snapshot_estimates.plist` | Unload + delete |

## Verification

1. `pytest tests/mcp_tools/test_estimates.py -v` — all tests pass with HTTP mocks
2. MCP: `get_estimate_revisions(ticker="AAPL")` — works via HTTP
3. MCP: `screen_estimate_revisions(direction="up", days=30)` — works via HTTP
4. Unset `ESTIMATE_API_URL` → tools return clear error (not silent failure)
5. `launchctl list | grep snapshot` → not found
