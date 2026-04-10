# Fix A5.1: `_parse_shift()` Float Coercion Crash

**Bug**: `delta_changes` with float values crashes — `'float' object has no attribute 'strip'` in `_parse_shift()` at `utils/helpers_input.py:34`.
**Severity**: HIGH. **Scope**: Small (~5 lines of logic + tests).

---

## 1. Problem Trace

```
AI agent sends: {"TLT": 0.10, "SPY": -0.05}   (JSON numbers — natural for agents)
Expected by code: {"TLT": "+10%", "SPY": "-5%"} (human-friendly strings)

run_backtest(delta_changes={"TLT": 0.10})
  └─ mcp_tools/backtest.py:169
  └─ parse_delta(literal_shift={"TLT": 0.10})
       └─ utils/helpers_input.py:108  →  _parse_shift(0.10)
            └─ line 34: txt.strip()  →  AttributeError: 'float' object has no attribute 'strip'
```

JSON has no distinction between `0.10` (float) and `"0.10"` (string). When an AI agent constructs `delta_changes` from a JSON payload, numeric values arrive as Python `float` or `int`, not strings. `_parse_shift()` unconditionally calls `.strip()` on its argument, crashing on non-string types.

## 2. Root Cause

`_parse_shift(txt: str)` at `utils/helpers_input.py:27-39` assumes its input is always a string. It calls `txt.strip()` on line 34 without any type guard. The function is called from `parse_delta()` (line 108), which iterates `literal_shift.items()` and passes values directly — no coercion.

### Call site analysis

| Call site | File:Line | Source of values | Vulnerable? |
|-----------|-----------|-----------------|-------------|
| `parse_delta(literal_shift=...)` via backtest | `mcp_tools/backtest.py:169` | MCP JSON `delta_changes` dict — values are untyped | **YES** |
| `parse_delta(literal_shift=shift_dict)` via optimizer | `portfolio_risk_engine/portfolio_optimizer.py:892` | `shift_dict` param from `analyze_scenario()` — comes from MCP/REST callers | **YES** |
| `parse_delta(literal_shift=...)` via whatif | `mcp_tools/whatif.py` | MCP JSON `delta_changes` dict — same vulnerability as backtest | **YES** |
| `parse_delta(literal_shift=...)` via compare_scenarios | `mcp_tools/compare.py` | MCP JSON `delta_changes` per scenario — same vulnerability | **YES** |
| `parse_delta(yaml_path=...)` via risk orchestration | `core/risk_orchestration.py:464` | YAML file values — **not always strings**: `yaml.safe_load` coerces unquoted `0.10` to float, `true` to bool. Only quoted values remain strings. | Partially (unquoted numeric/bool YAML scalars are vulnerable) |
| `parse_delta(literal_shift=delta_dict_str)` via risk orchestration | `core/risk_orchestration.py:475` | Inline delta string split by `:` — always strings after `.split()` | No |

The first four call sites are vulnerable because their values originate from JSON deserialization (MCP tool arguments or REST request bodies), where `0.10` is a float, not `"0.10"`. The YAML path is partially vulnerable because `yaml.safe_load` performs type coercion on unquoted scalars: `0.10` becomes `float`, `true` becomes `bool`, `100bp` stays `str`. The `_parse_shift()` fix protects all paths regardless.

## 3. Fix

### File: `utils/helpers_input.py`

#### 3a. `_parse_shift()` — numeric type guard (defense-in-depth)

**Current code** (lines 27-39):
```python
def _parse_shift(txt: str) -> float:
    """
    Convert a human-friendly shift string to decimal.

    "+200bp", "-75bps", "1.5%", "-0.01"  →  0.02, -0.0075, 0.015, -0.01
    """
    # LOGGING: Add input validation logging with original and parsed values
    t = txt.strip().lower().replace(" ", "")
    if t.endswith("%"):
        return float(t[:-1]) / 100
    if t.endswith(("bp", "bps")):
        return float(t.rstrip("ps").rstrip("bp")) / 10_000
    return float(t)                       # already decimal
```

**New code**:
```python
import math
import numbers

def _parse_shift(txt) -> float:
    """
    Convert a human-friendly shift string **or numeric value** to decimal.

    "+200bp", "-75bps", "1.5%", "-0.01"  →  0.02, -0.0075, 0.015, -0.01
    0.10, -0.05, 0                        →  0.10, -0.05, 0.0

    Raises TypeError for bool/None, ValueError for non-finite (nan/inf).
    """
    if isinstance(txt, bool):
        raise TypeError(f"_parse_shift() does not accept bool: {txt!r}")
    if isinstance(txt, numbers.Real):
        val = float(txt)
        if not math.isfinite(val):
            raise ValueError(f"_parse_shift() does not accept non-finite value: {txt!r}")
        return val
    if txt is None:
        raise TypeError("_parse_shift() does not accept None")
    t = str(txt).strip().lower().replace(" ", "")
    if t.endswith("%"):
        val = float(t[:-1]) / 100
    elif t.endswith(("bp", "bps")):
        val = float(t.rstrip("ps").rstrip("bp")) / 10_000
    else:
        val = float(t)                    # already decimal
    # Final non-finite guard — catches nan/inf from ALL branches (string included)
    if not math.isfinite(val):
        raise ValueError(f"_parse_shift() does not accept non-finite value: {txt!r}")
    return val
```

Seven changes:
1. **Type annotation**: `txt: str` → `txt` (untyped). Could use `Union[str, int, float]` but the function already handles arbitrary types via `str(txt)` fallback, so leaving it untyped is more honest. The docstring documents accepted types.
2. **Bool rejection** (before numeric check): `isinstance(txt, bool)` → `TypeError`. Because `bool` subclasses `int` in Python, `True`/`False` would pass a bare `isinstance(txt, (int, float))` check and silently coerce to `1.0`/`0.0`. This would turn `{"AAPL": true}` into a +1.0 shift — a dangerous silent misparse. The explicit bool guard MUST come before the numeric check. Pattern matches `data_objects.py:525`.
3. **Broad numeric guard**: `isinstance(txt, numbers.Real)` (stdlib `numbers` module) instead of `isinstance(txt, (int, float))`. This catches `np.float32`, `np.int64`, and other numeric scalar types that register with the `numbers` ABC directly through the fast path. Note: `Decimal` does NOT register with `numbers.Real` (`isinstance(Decimal("0.10"), numbers.Real)` is `False`), so `Decimal` values fall through to the `str(txt)` fallback path — which is fine, since `str(Decimal("0.10"))` produces `"0.10"` and parses correctly via the existing `return float(t)` branch.
4. **`nan`/`inf` rejection (numeric branch)**: After `float(txt)` conversion in the `numbers.Real` branch, check `math.isfinite(val)` and raise `ValueError` for `nan`, `inf`, `-inf`. These are technically valid floats but nonsensical as portfolio weight shifts.
5. **`None` rejection**: Explicit `TypeError` for `None` before the `str(txt)` fallback, which would produce `"None"` and then fail with an unhelpful `ValueError` from `float("None")`. Fail fast with a clear message instead.
6. **`str(txt)` fallback**: Change `txt.strip()` to `str(txt).strip()`. Belt-and-suspenders for any other non-string types that slip through. The `numbers.Real` guard handles the common numeric case efficiently; `str()` handles the long tail.
7. **Final `math.isfinite()` guard (all branches)**: After the string parsing branches (`%`, `bp`/`bps`, raw decimal), check `math.isfinite(val)` before returning. This catches non-finite values that originate from string inputs like `"nan"`, `"inf"`, `"+nan%"` — which Python's `float()` happily parses into `float("nan")` or `float("inf")`. Without this, the `numbers.Real` branch's finite check would only protect numeric inputs, leaving string non-finite values uncaught.

**Why fix in `_parse_shift()` and not at call sites**: The function is the natural coercion boundary. Fixing at each call site would require 2+ changes (backtest, optimizer) and miss future callers. A type guard at the function level is one change that protects everything — current and future.

**Semantic note**: When an agent sends `{"TLT": 0.10}`, the `0.10` is treated as a decimal shift (i.e., +10 percentage points of portfolio weight). This is correct — it matches the semantics of the string `"-0.01"` which the existing code already parses as a raw decimal on the `return float(t)` fallback path (line 39). The agent convention for `delta_changes` is decimal shifts, not percentage strings.

#### 3b. `parse_delta()` type annotation — document mixed-type support

**Current** (line 43):
```python
literal_shift: Optional[Dict[str, str]] = None,
```

**New**:
```python
literal_shift: Optional[Dict[str, object]] = None,
```

This documents that values can be strings, floats, or ints — matching the actual runtime behavior after the `_parse_shift()` fix. Using `object` rather than `Union[str, int, float]` avoids over-constraining (YAML `safe_load` can produce other scalar types).

Also update the docstring for `literal_shift` (line 59):
```
literal_shift : dict | None
    In-memory dict of {ticker: shift_value}. Values can be:
    - Strings: "+500bp", "1.5%", "-0.01"
    - Numbers: 0.10, -0.05 (treated as decimal shifts)
    Overrides YAML deltas if both are provided.
```

---

## 4. Test Plan

### File: `tests/utils/test_helpers_input.py` (new file)

No existing tests for `_parse_shift()` or `parse_delta()` exist. Create a dedicated test file.

#### 4a. `_parse_shift()` unit tests

| # | Test | Input | Expected |
|---|------|-------|----------|
| 1 | `test_parse_shift_float_positive` | `0.10` | `0.10` |
| 2 | `test_parse_shift_float_negative` | `-0.05` | `-0.05` |
| 3 | `test_parse_shift_float_zero` | `0.0` | `0.0` |
| 4 | `test_parse_shift_int` | `0` | `0.0` |
| 5 | `test_parse_shift_int_nonzero` | `1` | `1.0` |
| 6 | `test_parse_shift_string_percent` | `"+10%"` | `0.10` |
| 7 | `test_parse_shift_string_negative_percent` | `"-5%"` | `-0.05` |
| 8 | `test_parse_shift_string_bp` | `"+200bp"` | `0.02` |
| 9 | `test_parse_shift_string_bps` | `"-75bps"` | `-0.0075` |
| 10 | `test_parse_shift_string_decimal` | `"-0.01"` | `-0.01` |
| 11 | `test_parse_shift_string_with_spaces` | `" +10% "` | `0.10` |
| 12 | `test_parse_shift_bool_true_raises` | `True` | `TypeError` |
| 13 | `test_parse_shift_bool_false_raises` | `False` | `TypeError` |
| 14 | `test_parse_shift_none_raises` | `None` | `TypeError` |
| 15 | `test_parse_shift_nan_raises` | `float("nan")` | `ValueError` |
| 16 | `test_parse_shift_inf_raises` | `float("inf")` | `ValueError` |
| 17 | `test_parse_shift_neg_inf_raises` | `float("-inf")` | `ValueError` |
| 18 | `test_parse_shift_decimal` | `Decimal("0.10")` | `0.10` (via `str(txt)` fallback path — `Decimal` is NOT caught by `numbers.Real`) |
| 19 | `test_parse_shift_numpy_float32` | `np.float32(0.10)` | `≈0.10` (via `numbers.Real` path) |
| 20 | `test_parse_shift_numpy_int64` | `np.int64(1)` | `1.0` (via `numbers.Real` path) |
| 21 | `test_parse_shift_string_nan_raises` | `"nan"` | `ValueError` (caught by final `isfinite` guard) |
| 22 | `test_parse_shift_string_inf_raises` | `"inf"` | `ValueError` (caught by final `isfinite` guard) |
| 23 | `test_parse_shift_string_neg_inf_raises` | `"-inf"` | `ValueError` (caught by final `isfinite` guard) |

Tests 1-5 verify the new numeric guard for built-in types. Tests 6-11 verify existing string behavior is preserved (regression safety). Tests 12-14 verify rejection of bool/None (finding #1, #3). Tests 15-17 verify non-finite rejection from the numeric branch. Tests 18 verifies `Decimal` works via the `str(txt)` fallback (NOT `numbers.Real`). Tests 19-20 verify `numbers.Real` catches numpy scalar types directly. Tests 21-23 verify non-finite rejection from string inputs (e.g., `"nan"`, `"inf"`).

#### 4b. `parse_delta()` integration tests

| # | Test | Input | Expected |
|---|------|-------|----------|
| 24 | `test_parse_delta_mixed_types` | `literal_shift={"TLT": 0.10, "SPY": "-5%"}` | `({"TLT": 0.10, "SPY": -0.05}, None)` |
| 25 | `test_parse_delta_all_floats` | `literal_shift={"TLT": 0.10, "SPY": -0.05}` | `({"TLT": 0.10, "SPY": -0.05}, None)` |
| 26 | `test_parse_delta_all_strings` | `literal_shift={"TLT": "+10%", "SPY": "-500bp"}` | `({"TLT": 0.10, "SPY": -0.05}, None)` |
| 27 | `test_parse_delta_empty_raises` | `literal_shift=None, yaml_path=None` | `ValueError` |
| 28 | `test_parse_delta_bool_value_raises` | `literal_shift={"AAPL": True}` | `TypeError` (propagated from `_parse_shift`) |

Test 24 is the primary bug reproduction — mixed float/string values in a single dict, which is the exact pattern an AI agent produces when it sends `{"TLT": 0.10, "SPY": "-5%"}`. Test 28 ensures bool rejection propagates through `parse_delta()` to catch the `{"AAPL": true}` JSON misparse at the integration level.

---

## 5. Files Modified

| File | Change |
|------|--------|
| `utils/helpers_input.py` | `import math` and `import numbers` at top; bool guard + `numbers.Real` numeric guard + nan/inf rejection (numeric branch) + None guard + final `math.isfinite()` guard (all branches) in `_parse_shift()`, type annotation updates |
| `tests/utils/test_helpers_input.py` | New test file — 28 tests (23 unit + 5 integration) |

---

## 6. Risks

- **Regression risk**: Very low. The bool/None guards raise on inputs that previously crashed with `AttributeError`, so no working call path is broken. The `numbers.Real` guard is a superset of `(int, float)` — all previously-working numeric types still work, plus numpy scalars now take the `numbers.Real` fast path; `Decimal` is supported via `str()` fallback. String inputs follow the exact same code path as before (the `str(txt)` call is equivalent to the original `txt.strip()` when `txt` is already a string, since `str("foo") == "foo"`).
- **Semantic ambiguity**: A float value `0.10` could mean either "+10 percentage points" (decimal shift) or "+10%" (percentage). The existing code treats the string `"-0.01"` as a decimal shift (the `return float(t)` fallback), so treating `0.10` as a decimal shift is consistent. This matches the agent convention: `delta_changes` values are decimal shifts where `0.10` = +10pp.
- **String non-finite values**: Python's `float()` happily parses `"nan"`, `"inf"`, `"-inf"` into non-finite floats. The final `math.isfinite()` guard catches these from all string branches (raw decimal, `%`, `bp`/`bps`). Without it, `_parse_shift("nan")` would silently return `float("nan")`.
- **New imports**: `math` and `numbers` are stdlib — no new dependencies. `numbers.Real` is the standard ABC for real numeric types; `math.isfinite` is the standard finite check.
- **Bool subclass trap**: `bool` is a subclass of `int` in Python, so `isinstance(True, int)` is `True`. Without the explicit bool guard, `True` would silently become `1.0` and `False` would become `0.0`. This is tested in cases 12-13.
- **No caller changes needed**: The fix is entirely within `_parse_shift()`. All 6 call sites (4 vulnerable, 1 partially vulnerable, 1 safe) benefit automatically. No coordination required.
- **Rollback**: Revert the single commit. The only behavioral changes are: (a) `_parse_shift(0.10)` returns `0.10` instead of raising `AttributeError`, (b) `_parse_shift(True)` / `_parse_shift(None)` raise clear `TypeError` instead of crashing, (c) `_parse_shift(float("nan"))` / `_parse_shift("nan")` / `_parse_shift("inf")` raise clear `ValueError` instead of silently returning non-finite floats.
