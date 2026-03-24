# Configurable Stress Scenarios — YAML + MCP Tool

## Context

Stress scenarios are hardcoded in `STRESS_SCENARIOS` dict in `stress_testing.py`. The only way to add/remove/edit them is editing Python and restarting. We want the AI agent to create custom scenarios conversationally ("create a scenario where 10Y rises 200bp and credit spreads widen 150bp") and persist them across restarts. YAML config + MCP tool.

## Design

### Storage: `config/stress_scenarios.yaml`

```yaml
interest_rate_shock:
  name: Interest Rate Shock
  description: 300bp parallel shift in yield curve
  severity: High
  shocks:
    rate_2y: 0.03
    rate_5y: 0.03
    rate_10y: 0.03
    rate_30y: 0.03

bear_flattener:
  name: Bear Flattener
  description: "Short rates rise sharply, long end anchored — classic Fed hiking path"
  severity: High
  shocks:
    rate_2y: 0.03
    rate_5y: 0.02
    rate_10y: 0.015
    rate_30y: 0.01

# ... (all 9 current scenarios)
```

User-created scenarios go in the same file. No separate "custom" vs "built-in" distinction — all scenarios are equal. The YAML file is the single source of truth.

### Load: `stress_testing.py`

Rename current hardcoded dict to `_DEFAULT_SCENARIOS`. Replace `get_stress_scenarios()` with a YAML-backed loader:

```python
_SCENARIO_YAML = "stress_scenarios.yaml"
_VALID_SEVERITIES = {"Low", "Medium", "High", "Extreme"}

def _validate_scenario(entry: Any) -> Dict[str, Any] | None:
    """Validate a single scenario entry. Returns cleaned dict or None."""
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    desc = entry.get("description", "")
    severity = entry.get("severity", "Medium")
    shocks = entry.get("shocks")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(shocks, dict) or not shocks:
        return None
    if severity not in _VALID_SEVERITIES:
        severity = "Medium"  # default if invalid
    clean_shocks = {}
    for sk, sv in shocks.items():
        try:
            fv = float(sv)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(fv) or isinstance(sv, bool):
            continue
        clean_shocks[str(sk)] = fv
    if not clean_shocks:
        return None
    return {
        "name": name.strip(),
        "description": str(desc).strip() if desc else "",
        "severity": severity,
        "shocks": clean_shocks,
    }

def _load_scenarios() -> Dict[str, Dict[str, Any]]:
    """Load scenarios from YAML, falling back to hardcoded defaults."""
    try:
        path = _scenario_yaml_path()
        with open(path) as f:
            raw = yaml.safe_load(f)
        if isinstance(raw, dict) and raw:
            validated = {}
            for k, v in raw.items():
                # Validate scenario_id key: must be string matching snake_case
                if not isinstance(k, str) or not re.match(r"^[a-z][a-z0-9_]*$", k):
                    continue  # skip non-string or invalid keys (e.g., YAML `1:` or `true:`)
                try:
                    clean = _validate_scenario(v)
                except Exception:
                    continue  # skip malformed entry, don't nuke all scenarios
                if clean:
                    validated[k] = clean
            if validated:
                return validated
    except Exception:
        pass
    return copy.deepcopy(_DEFAULT_SCENARIOS)  # deep copy — prevents mutation of fallback
```

`_load_scenarios()` returns a **deep copy** on fallback so callers that mutate nested `shocks` dicts don't contaminate the in-memory defaults. `get_stress_scenarios()` wraps `_load_scenarios()` and preserves the existing deep-copy contract (current code already does `copy.deepcopy` in the public API). (Codex R4 issue 1, R5 issue 1)

Validation enforces: `name` (non-empty string), `description` (string, defaults to ""), `severity` (enum, defaults to "Medium"), `shocks` (non-empty dict, finite numeric values, no bools). Malformed entries are silently dropped — if all entries fail, falls back to `_DEFAULT_SCENARIOS`. (Codex R2 issue 3)

**Key changes** (Codex R1 issue 1):
- `run_all_stress_tests()` currently iterates `STRESS_SCENARIOS` directly — change to call `get_stress_scenarios()`.
- `services/scenario_service.py` imports `STRESS_SCENARIOS` directly — change to call `get_stress_scenarios()` from `stress_testing`.
- `services/agent_building_blocks.py` imports `STRESS_SCENARIOS` — change to call `get_stress_scenarios()`.
- Keep `_DEFAULT_SCENARIOS` as a module constant for fallback only. Remove the public `STRESS_SCENARIOS` name. Any lingering direct importers will get an `ImportError` at startup — intentional, forces migration.

`get_stress_scenarios()` reads YAML on every call (no cache). File is <2KB, negligible I/O.

### Canonical Path: `_scenario_yaml_path()` (Codex R1 issue 2, R2 issue 1)

Both reads and writes use a single canonical path — NOT `resolve_config_path()`. This eliminates shadow-file risk where a stray YAML in CWD or project root could make reads and writes hit different files.

```python
def _scenario_yaml_path() -> Path:
    """Canonical read/write path for stress scenarios YAML."""
    return Path(__file__).resolve().parent.parent / "config" / _SCENARIO_YAML
```

`_load_scenarios()` reads from `_scenario_yaml_path()`. `_save_scenarios()` writes to `_scenario_yaml_path()`. Same file, always.

### Atomic + Locked Writes (Codex R1 issue 3, R2 issue 2)

Temp file + `os.replace()` prevents readers seeing partial YAML. A `threading.Lock` prevents concurrent add/remove from losing each other's updates:

```python
import tempfile, os, threading

_SCENARIO_LOCK = threading.Lock()

def _save_scenarios(scenarios: Dict[str, Dict[str, Any]]) -> Path:
    """Atomic write with lock. Caller must hold _SCENARIO_LOCK."""
    path = _scenario_yaml_path()
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".yaml.tmp")
    try:
        with os.fdopen(fd, "w") as f:
            yaml.dump(scenarios, f, default_flow_style=False, sort_keys=False)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path
```

The MCP tool's `add` and `remove` actions acquire `_SCENARIO_LOCK` before the read-modify-write cycle:

```python
with _SCENARIO_LOCK:
    scenarios = _load_scenarios()
    scenarios[scenario_id] = {...}
    _save_scenarios(scenarios)
```

`list` and `get` are read-only — no lock needed (YAML reads are atomic at the OS level after `os.replace`).

**Cross-process note** (Codex R5 issue 2): `threading.Lock` only serializes within one Python process. Each Claude Code session spawns its own MCP server process, so concurrent sessions could still lose updates. For this use case (admin-level scenario management, low write frequency), this is acceptable. If needed later, `fcntl.flock()` can be added — but the atomic `os.replace()` already prevents corruption; the worst case is a lost update, not data corruption.

### MCP Tool: `mcp_tools/stress_scenarios.py`

```python
@handle_mcp_errors
def manage_stress_scenarios(
    action: str,           # "list" | "add" | "remove" | "get"
    scenario_id: str | None = None,
    name: str | None = None,
    description: str | None = None,
    severity: str | None = None,
    shocks: str | None = None,     # JSON string: '{"rate_10y": 0.02, "market": -0.10}'
) -> dict:
```

Uses `@handle_mcp_errors` decorator (Codex R1 issue 5). Returns `{"status": "success"|"error", ...}` consistent envelope.

**Actions:**

- `list` — returns `{"status": "success", "scenarios": [{id, name, severity, shock_count}, ...], "count": N}`
- `get` — returns `{"status": "success", "scenario": {full scenario dict}}`. Error if not found.
- `add` — upsert semantics (creates or overwrites). Returns `{"status": "success", "scenario_id": ..., "created": bool}`. Requires `scenario_id`, `name`, `description`, `severity`, `shocks`.
- `remove` — returns `{"status": "success", "removed": scenario_id}`. Refuses if ≤1 scenario remains.

**Validation** (Codex R1 issue 6):
- `severity` must be one of `Low`, `Medium`, `High`, `Extreme`
- `shocks` parsed from JSON string → dict with string keys and **finite** numeric values (reject NaN, Infinity, bool, empty)
- `scenario_id` must match `^[a-z][a-z0-9_]*$` (snake_case)
- `name` and `description` must be non-empty strings
- Shock keys: warn if unknown factor name, don't block

### Registration: `mcp_server.py`

Standard wrapper pattern. MCP-only tool — **not added to agent registry** (Codex R1 issue 4). This is an admin/power-user tool for the CLI agent, not the in-app AI chat agent. Mutating the global scenario catalog from the chat agent would be confusing UX.

```python
from mcp_tools.stress_scenarios import manage_stress_scenarios as _manage_stress_scenarios

@mcp.tool()
def manage_stress_scenarios(
    action: str,
    scenario_id: Optional[str] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    severity: Optional[str] = None,
    shocks: Optional[str] = None,
) -> dict:
    """Manage stress test scenarios: list, get, add, or remove custom scenarios."""
    return _manage_stress_scenarios(
        action=action, scenario_id=scenario_id, name=name,
        description=description, severity=severity, shocks=shocks,
    )
```

## Files to Modify

| File | Change |
|------|--------|
| `config/stress_scenarios.yaml` | **NEW** — all 9 current scenarios in YAML format |
| `portfolio_risk_engine/stress_testing.py` | Rename `STRESS_SCENARIOS` → `_DEFAULT_SCENARIOS`, add `_load_scenarios()`, `_scenario_yaml_path()`, `_save_scenarios()`. Update `get_stress_scenarios()` to read YAML. Update `run_all_stress_tests()` to call `get_stress_scenarios()` instead of iterating `STRESS_SCENARIOS` directly. |
| `services/scenario_service.py` | Change `from ... import STRESS_SCENARIOS` → call `get_stress_scenarios()` |
| `services/agent_building_blocks.py` | Change `from ... import STRESS_SCENARIOS` → call `get_stress_scenarios()` |
| `mcp_tools/stress_scenarios.py` | **NEW** — `manage_stress_scenarios()` with list/get/add/remove, `@handle_mcp_errors`, atomic YAML writes |
| `mcp_server.py` | Register `manage_stress_scenarios` tool (MCP only, not agent registry) |
| `tests/test_stress_testing.py` | Add YAML loading tests, fallback tests, round-trip test, schema validation test |
| `tests/mcp_tools/test_stress_scenarios.py` | **NEW** — all 4 actions, validation (bad severity, NaN/Infinity/bool shocks, empty shocks, bad id, empty name), atomic write verification (temp file + replace), lock serialization |
| `tests/services/test_agent_building_blocks.py` | Update if test references `STRESS_SCENARIOS` directly |

## What Does NOT Change

- `run_stress_test()` — still takes `shocks` dict, no changes
- Frontend — renders whatever scenarios the API returns. Dynamic dropdown already handles variable counts.
- Per-maturity beta storage — unaffected
- Agent registry — tool NOT exposed to in-app chat agent

## Verification

1. `pytest tests/test_stress_testing.py -x -q` — YAML loading + fallback tests pass
2. `pytest tests/mcp_tools/test_stress_scenarios.py -x -q` — all 4 actions tested
3. `pytest tests/services/test_agent_building_blocks.py -x -q` — no import breakage
4. MCP tool: `manage_stress_scenarios(action="list")` → 9 scenarios
5. MCP tool: `manage_stress_scenarios(action="add", scenario_id="credit_crunch", name="Credit Crunch", description="Severe credit tightening", severity="Extreme", shocks='{"rate_2y": 0.04, "rate_10y": 0.02, "market": -0.15}')` → persisted
6. MCP tool: `manage_stress_scenarios(action="list")` → 10 scenarios
7. Browser: stress test dropdown shows 10 scenarios including "Credit Crunch"
8. MCP tool: `manage_stress_scenarios(action="remove", scenario_id="credit_crunch")` → removed
9. Server restart → YAML scenarios still load
10. Delete YAML file → `get_stress_scenarios()` returns 9 defaults (fallback)
