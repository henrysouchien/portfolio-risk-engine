# Agent Registry Discovery Schema Enhancement

> **Status**: DRAFT — Codex R1 FAIL, revised (see Codex Feedback below)
> **Scope**: Replace `_type_name()` with JSON-Schema-like `_type_schema()` in registry endpoint
> **Depends on**: Agent Registry Audit (`completed/AGENT_REGISTRY_AUDIT_PLAN.md`)

---

## Context

The `GET /api/agent/registry` endpoint exposes tool metadata for agent code execution clients. Currently `_type_name()` (`routes/agent_api.py:178-186`) reduces all Python annotations to bare names — `Literal["hypothetical", "realized"]` becomes `"Literal"`, `Optional[str]` becomes `"Optional"`. An agent composing multi-step workflows can't determine valid parameter values from the schema alone.

This enhancement replaces `_type_name()` with `_type_schema()` that returns JSON-Schema-like dicts with enum values, nullable flags, and container type info.

---

## Key Design Decision: `get_type_hints()`

26 of 40 MCP tool files use `from __future__ import annotations`, which turns annotations into strings at runtime. `inspect.signature()` returns `'Optional[str]'` (a literal string), not a type object. We must use `typing.get_type_hints()` to resolve these back to real types. Fallback to `param.annotation` if `get_type_hints()` fails (e.g., unresolvable forward reference).

---

## Output Format (before → after)

```
Literal["hypothetical", "realized"]
  Before: {"type": "Literal"}
  After:  {"type": "string", "enum": ["hypothetical", "realized"]}

Optional[float]
  Before: {"type": "Optional"}
  After:  {"type": "number", "nullable": true}

dict[str, float]
  Before: {"type": "dict"}
  After:  {"type": "object", "value_type": "number"}

Optional[dict[str, float]]
  Before: {"type": "Optional"}
  After:  {"type": "object", "nullable": true, "value_type": "number"}

list[dict[str, Any]]
  Before: {"type": "list"}
  After:  {"type": "array", "items": {"type": "object"}}

tuple[float, float]
  Before: {"type": "tuple"}
  After:  {"type": "array", "items": {"type": "number"}, "length": 2}

str / int / float / bool
  Before: {"type": "str"} / {"type": "int"} etc.
  After:  {"type": "string"} / {"type": "integer"} / {"type": "number"} / {"type": "boolean"}

Any / empty
  Before: {"type": "Any"}
  After:  {"type": "any"}
```

**Backward compat**: `"type"` key is always present. Values change from Python names to JSON Schema names (`str`→`string`, `float`→`number`). No existing consumer parses these string values (verified: `risk_client` doesn't inspect them, tests don't assert on them, frontend doesn't read the endpoint).

---

## Implementation

### Step 1: `routes/agent_api.py` — replace `_type_name()` with `_type_schema()`

**1a. Add imports:**
```python
import types
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints
```

**1b. Add primitive mapping** (near `BLOCKED_PARAMS` import):
```python
_PYTHON_TO_JSON_TYPE = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}
```

**1c. New `_type_schema()` function** (replaces `_type_name()` at lines 178-186):

Handles in priority order:
1. `Parameter.empty` / `Any` → `{"type": "any"}`
2. `Literal[...]` → `{"type": "string", "enum": [values]}`
3. `Union[X, None]` (Optional) → recurse on X, add `"nullable": true`
4. `list[X]` → `{"type": "array", "items": recurse(X)}`
5. `dict[K, V]` → `{"type": "object"}` + `"value_type"` mapped from V if V is not `Any`
6. `tuple[X, ...]` → `{"type": "array", "items": recurse(X), "length": N}`
7. Bare `dict`/`list` → `{"type": "object"}` / `{"type": "array"}`
8. Primitives via `_PYTHON_TO_JSON_TYPE` lookup
9. Fallback → `{"type": "any"}`

```python
def _type_schema(annotation: Any) -> dict[str, Any]:
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {"type": "any"}

    origin = get_origin(annotation)
    args = get_args(annotation)

    # Literal → enum
    if origin is Literal:
        return {"type": "string", "enum": list(args)}

    # Optional / Union with None
    if origin is Union or origin is types.UnionType:
        non_none = [a for a in args if a is not type(None)]
        nullable = len(non_none) < len(args)
        if len(non_none) == 1:
            schema = _type_schema(non_none[0])
            if nullable:
                schema["nullable"] = True
            return schema
        return {"type": "any", **({"nullable": True} if nullable else {})}

    # list[X]
    if origin is list:
        schema: dict[str, Any] = {"type": "array"}
        if args:
            schema["items"] = _type_schema(args[0])
        return schema

    # dict[K, V]
    if origin is dict:
        schema = {"type": "object"}
        if len(args) >= 2 and args[1] is not Any:
            vtype = _PYTHON_TO_JSON_TYPE.get(args[1])
            if vtype:
                schema["value_type"] = vtype
        return schema

    # tuple[X, Y, ...] — filter out Ellipsis for variable-length tuples
    if origin is tuple:
        schema = {"type": "array"}
        if args:
            concrete = [a for a in args if a is not Ellipsis]
            if not concrete:
                return schema
            unique_types = set(concrete)
            if len(unique_types) == 1:
                schema["items"] = _type_schema(concrete[0])
            else:
                schema["items"] = {"type": "any"}
            if Ellipsis not in args:
                schema["length"] = len(concrete)
        return schema

    # Bare types
    if annotation is dict:
        return {"type": "object"}
    if annotation is list:
        return {"type": "array"}

    # Primitives
    json_type = _PYTHON_TO_JSON_TYPE.get(annotation)
    if json_type:
        return {"type": json_type}

    return {"type": "any"}
```

**1d. Update `_build_schema()`** (lines 150-175):

```python
def _build_schema(entry: AgentFunction) -> dict[str, Any]:
    signature = inspect.signature(entry.callable)
    try:
        resolved_hints = get_type_hints(entry.callable, include_extras=True)
    except Exception:
        resolved_hints = {}

    params = {}
    for param_name, param in signature.parameters.items():
        if param_name == "user_email" or param_name in BLOCKED_PARAMS:
            continue
        annotation = resolved_hints.get(param_name, param.annotation)
        param_info = _type_schema(annotation)
        if param.default is inspect.Parameter.empty:
            param_info["required"] = True
        else:
            param_info["default"] = param.default
        params[param_name] = param_info

    description = ""
    doc = inspect.getdoc(entry.callable)
    if doc:
        description = doc.splitlines()[0].strip()

    return {
        "tier": entry.tier,
        "category": entry.category,
        "description": description,
        "read_only": entry.read_only,
        "params": params,
    }
```

**1e. Delete `_type_name()`** — dead code after migration.

### Step 2: `tests/routes/test_agent_api.py` — schema tests

**Test 1: `test_schema_literal_enums`**
- Mock tool with `Literal["a", "b"]` param
- Assert `type == "string"`, `enum == ["a", "b"]`

**Test 2: `test_schema_nullable_types`**
- Mock tool with `Optional[str]`, `Optional[float]`, `Optional[dict]`
- Assert `nullable == True` + correct base type
- Also test PEP 604 `str | None` directly via `_type_schema()` unit test

**Test 3: `test_schema_container_types`**
- Mock tool with `dict[str, float]`, `list[dict[str, Any]]`, `tuple[float, float]`
- Assert object/array with items/value_type/length

**Test 4: `test_schema_primitives`**
- `str`→`"string"`, `int`→`"integer"`, `float`→`"number"`, `bool`→`"boolean"`

**Test 5: `test_schema_real_tools`**
- Use real registry (no mocking), spot-check:
  - `get_performance.mode` has `enum` containing `"hypothetical"` and `"realized"`
  - `run_optimization.optimization_type` has `enum` with `"min_variance"`, `"max_sharpe"`, etc.
  - `run_optimization.target_volatility` is `number` + `nullable`
  - `generate_rebalance_trades.target_weights` is `object` + `nullable` + `value_type: "number"`
  - `record_workflow_action.recommendation_data` (PEP 604 `dict | None`, from `mcp_tools/audit.py` with `__future__` annotations) is `object` + `nullable`
  - `get_action_history.status_filter` (PEP 604 `str | None`, wrapped + `__future__`) is `string` + `nullable`

**Test 6: `test_schema_type_key_always_present`**
- Iterate all params in all registry entries
- Assert every param dict has `"type"` key

---

## Verification

```bash
pytest tests/routes/test_agent_api.py -v
```

## Files Modified

| File | Changes |
|------|---------|
| `routes/agent_api.py` | Replace `_type_name()` with `_type_schema()`, update `_build_schema()` to use `get_type_hints()`, add `_PYTHON_TO_JSON_TYPE` |
| `tests/routes/test_agent_api.py` | 6 new test functions for schema validation |

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| `get_type_hints()` fails for some tool | try/except fallback to `param.annotation` from `inspect.signature()` |
| Decorated functions hide real signature | Registry already uses `_unwrap()` to follow `__wrapped__` |
| `from __future__ import annotations` in `agent_api.py` | Doesn't matter — `_type_schema` operates on resolved type objects from `get_type_hints()` |
| Non-string Literal values (e.g., `Literal[1, 2]`) | Not present in codebase. Could detect via `isinstance(args[0], str)` if needed later. |
| `tuple[X, ...]` (variable-length) vs `tuple[X, Y]` (fixed) | Filter `Ellipsis` from args, only emit `"length"` for fixed-length tuples |

---

## Codex Feedback

### R1: FAIL (3 issues)

1. **PEP 604 unions not tested** — tests only covered `Optional[...]` but live tools expose `dict | None`, `str | None` (e.g., `mcp_tools/audit.py` with `__future__` annotations). **Fixed**: added PEP 604 `str | None` to test 2, added `record_workflow_action.recommendation_data` and `get_action_history.status_filter` to real-tool test 5.

2. **Wrapped `__future__` tool not in real-tool tests** — `_unwrap()` only removes one `__wrapped__` layer. Need to prove `get_type_hints()` works on these tools. Codex verified it does for all 77 entries. **Fixed**: added `__future__`-annotated wrapped tools (`audit.py`) to real-tool test 5.

3. **Tuple `Ellipsis` bug** — `tuple[X, ...]` would produce `length: 2` with `Ellipsis` as second arg. **Fixed**: filter `Ellipsis` from args, only emit `"length"` for fixed-length tuples.
