# Agent Registry Code Execution Audit Plan

> **Status**: DRAFT — Codex R1 FAIL, revised (see Codex Feedback below)
> **Scope**: Triage 13 MCP tools missing from agent registry
> **Result**: 75 → 77 functions (2 added, 11 intentionally excluded)

---

## Context

The agent registry (`services/agent_registry.py`) exposes MCP tools for the code execution API (`POST /api/agent/call`). Currently **75 functions** (65 tools + 10 building blocks) out of **78 MCP tools** in `mcp_server.py`. This audit triages the 13 missing tools — add what's safe and useful, formally document why the rest are excluded.

Prior work:
- **Tool Surface Alignment Audit** (`completed/TOOL_SURFACE_ALIGNMENT_AUDIT.md`) identified 19 gaps → 9 added (commit `bb882fff`)
- **Integration Review** (`completed/AGENT_REGISTRY_INTEGRATION_REVIEW_2026-03-23.md`) fixed user scoping, client drift, category drift

---

## Triage

### ADD (2 tools → registry 75 → 77)

| Tool | Source file | `read_only` | `category` | Rationale |
|------|------------|-------------|------------|-----------|
| `list_supported_brokerages` | `mcp_tools/connections.py` | `True` | `connections` | Pure read-only catalog of supported institutions + provider availability. No side effects, no filesystem access, no credentials. Useful for agent to understand connectable brokerages. |
| `manage_ticker_config` | `mcp_tools/user_overrides.py` | `False` | `config` | Per-user DB config for FMP aliases and cash proxies. User-scoped via `resolve_user_email(None)` → env var (same path as agent API). Well-validated inputs (regex on tickers/currencies). Mutations gated by `AGENT_API_ALLOW_WRITES`. Agent may need to fix ticker resolution (e.g., map `AT` → `AT.L`). |

### EXCLUDE (11 tools — documented in code)

| Tool | Source file | Exclusion reason |
|------|------------|------------------|
| `get_mcp_context` | `mcp_server.py` | Internal diagnostic (PID, cwd, dotenv path). Leaks server internals. |
| `import_portfolio` | `mcp_tools/import_portfolio.py` | Mixed-action filesystem-backed mutator — `file_path` param enables arbitrary reads, also writes to DB |
| `import_transaction_file` | `mcp_tools/import_transactions.py` | Mixed-action filesystem-backed mutator — `file_path` param enables arbitrary reads, also writes to DB |
| `normalizer_sample_csv` | `mcp_tools/normalizer_builder.py` | `file_path` param → arbitrary filesystem read |
| `normalizer_stage` | `mcp_tools/normalizer_builder.py` | Writes Python code to disk (code injection vector) |
| `normalizer_test` | `mcp_tools/normalizer_builder.py` | Dynamically imports and executes staged Python + `file_path` param (code execution + filesystem read) |
| `normalizer_activate` | `mcp_tools/normalizer_builder.py` | Moves files in staging directory (filesystem mutation) |
| `normalizer_list` | `mcp_tools/normalizer_builder.py` | Returns local directory paths (path-leak / filesystem coupling). Grouped with normalizer family. |
| `manage_instrument_config` | `mcp_tools/instrument_config.py` | Admin-only, not user-scoped. Changes ephemeral — `seed_all()` overwrites from YAML. |
| `initiate_brokerage_connection` | `mcp_tools/connections.py` | External OAuth flow requiring interactive browser auth. Not automatable. |
| `complete_brokerage_connection` | `mcp_tools/connections.py` | Completes OAuth; requires `link_token`/`pre_auth_ids` from browser step. |

---

## Implementation

### Step 1: `services/agent_registry.py` — add tools + exclusion docs

**1a. Imports** — add after existing transaction imports (~line 127):

```python
from mcp_tools.connections import list_supported_brokerages
from mcp_tools.user_overrides import manage_ticker_config
```

**1b. Read-only registration** — after `get_action_history` block (~line 174):

```python
_register("list_supported_brokerages", list_supported_brokerages, category="connections")
```

**1c. Write registration** — after `refresh_transactions` block (~line 296):

```python
_register(
    "manage_ticker_config",
    manage_ticker_config,
    read_only=False,
    category="config",
)
```

**1d. Exclusion comment block** — after `BLOCKED_PARAMS` dict (~line 21), before `AGENT_FUNCTIONS`:

```python
# ──────────────────────────────────────────────────────────────────────
# INTENTIONAL EXCLUSIONS — MCP tools deliberately NOT in the registry.
# Update this block when adding/removing MCP tools.
#
# get_mcp_context           — Internal diagnostic (PID, cwd). Leaks server internals.
# import_portfolio          — file_path param: filesystem-backed mutator (read + DB write)
# import_transaction_file       — file_path param: filesystem-backed mutator (read + DB write)
# normalizer_sample_csv     — file_path param: arbitrary filesystem read
# normalizer_stage          — Writes Python code to disk (code injection vector)
# normalizer_test           — Executes staged Python + file_path param (code exec + fs read)
# normalizer_activate       — Moves files in staging directory
# normalizer_list           — Returns local directory paths (path-leak, fs coupling)
# manage_instrument_config  — Admin-only, not user-scoped, changes ephemeral (seed_all)
# initiate_brokerage_connection   — External OAuth requiring interactive browser auth
# complete_brokerage_connection   — Completes OAuth; needs browser-provided tokens
# ──────────────────────────────────────────────────────────────────────
```

### Step 2: `tests/routes/test_agent_api.py` — update assertions

**2a.** Line 310: `assert payload["total"] == 75` → `assert payload["total"] == 77`

**2b.** Add presence checks (near existing assertions ~lines 312-322):

```python
assert "list_supported_brokerages" in functions
assert "manage_ticker_config" in functions
```

**2c.** Add property assertions:

```python
assert functions["list_supported_brokerages"]["read_only"] is True
assert functions["list_supported_brokerages"]["category"] == "connections"
assert functions["manage_ticker_config"]["read_only"] is False
assert functions["manage_ticker_config"]["category"] == "config"
```

**2d.** Add exclusion assertion to verify intentionally excluded tools stay out:

```python
for excluded in ("import_portfolio", "import_transaction_file", "get_mcp_context",
                 "normalizer_stage", "manage_instrument_config"):
    assert excluded not in functions
```

### Step 3: `risk_client/__init__.py` — add convenience wrappers

The parity test at `tests/test_risk_client.py:403` requires a `RiskClient` method for every tool-tier registry entry. Add two wrappers after `refresh_transactions` (~line 341):

```python
def list_supported_brokerages(self, **kw: Any) -> dict[str, Any]:
    return self.call("list_supported_brokerages", **kw)

def manage_ticker_config(self, action: str, **kw: Any) -> dict[str, Any]:
    return self.call("manage_ticker_config", action=action, **kw)
```

### Step 4: `tests/services/test_agent_building_blocks.py` — update count

Line 458: `assert len(registry) == 75` → `assert len(registry) == 77`

### Step 5: `tests/routes/test_agent_api.py` — additional assertions (from Codex R1)

**5a.** Assert `manage_ticker_config` is `has_user_email == False` (documents that it resolves user internally via env var, not injection):

```python
assert registry["manage_ticker_config"].has_user_email is False
```

(Add to `test_agent_registry_marks_user_scoped_allocation_and_audit_tools_for_injection` or a new test.)

### Step 6: `docs/TODO.md` — mark item #5 DONE

Line 19: change status to **DONE**, update description to reflect outcome.

---

## Verification

```bash
pytest tests/routes/test_agent_api.py tests/services/test_agent_building_blocks.py tests/test_risk_client.py -v
```

All tests pass. Count = 77. New tools present with correct metadata. Client parity maintained.

---

## Files Modified

| File | Changes |
|------|---------|
| `services/agent_registry.py` | 2 imports, 2 `_register()` calls, exclusion comment block |
| `risk_client/__init__.py` | 2 convenience wrappers (`list_supported_brokerages`, `manage_ticker_config`) |
| `tests/routes/test_agent_api.py` | Count bump 75→77, presence + property + exclusion + `has_user_email` assertions |
| `tests/services/test_agent_building_blocks.py` | Count bump 75→77 |
| `docs/TODO.md` | Item #5 status update |

## Risk Assessment

Minimal scope — 2 new `_register()` calls following exact existing pattern, 2 thin client wrappers, 1 documentation comment block, test updates. No architectural changes, no new files, no new dependencies. `manage_ticker_config` mutations correctly gated by `AGENT_API_ALLOW_WRITES`.

Note: `manage_ticker_config` has no `user_email` parameter (`has_user_email=False`). It resolves user internally via `resolve_user_email(None)` → `RISK_MODULE_USER_EMAIL` env var — the same path the agent API uses. This is an architectural caveat (tied to single-user env resolution), not a security issue.

---

## Codex Feedback

### R1: FAIL

1. **Missing downstream updates** — plan omitted `tests/services/test_agent_building_blocks.py:458` (hardcoded `len == 75`) and `risk_client/__init__.py` (parity test at `tests/test_risk_client.py:403` requires wrapper for every tool-tier entry). **Fixed**: added Steps 3-4.
2. **Exclusion rationale refinements** — `normalizer_test` executes staged Python (code exec, not just file read). `normalizer_list` returns local paths (path-leak). `import_*` are mixed-action mutators, not just readers. **Fixed**: updated exclusion table and comment block.
3. **Additional test assertions** — should assert `manage_ticker_config.has_user_email == False` to document the user-resolution pattern. **Fixed**: added Step 5a.
