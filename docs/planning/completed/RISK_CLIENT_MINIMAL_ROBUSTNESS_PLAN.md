# Risk Client — Minimal Robustness Pass

**Status:** v1.2 — **Codex sign-off PASS 2026-05-26 (round 3).** Implementation-ready.
**Authors:** Claude + Henry
**Mode:** Plan-first per CLAUDE.md (plan → Codex review → Codex implement)
**Target SHA:** current `main`
**Supersedes (in scope):** the load-bearing robustness subset of `RISK_CLIENT_AGENT_ERGONOMICS_PLAN.md` (v3.5 PASS). That plan stays on file as a reference for the full ergonomics rubric; this plan ships only the changes that move observable code-execution robustness.

> **v1.1 → v1.2 changelog:**
> - **Blocker (Codex v1.1):** `_error_type_from_status(status, label)` conflated the display label with the endpoint context. If an agent called `rc.call("registry")`, the function name `"registry"` would have mapped its 404 to `"transport"` instead of `"unknown_function"`. Fix: separate `label` (display string for `.function` attr) from `endpoint` (`"call"` or `"registry"`, controls status→error_type mapping). Helper signatures now `_wrap_http_error(exc, *, label, endpoint)` and `_error_type_from_status(status, *, endpoint)`.
> - **Polish (Codex v1.1 NB):** §7 now explicitly asserts `requests.exceptions.SSLError` propagation alongside `ConnectionError` and `Timeout`. The README and §3 already promised this; v1.1 had the claim without the test.
>
> **v1 → v1.1 changelog:**
> - **Blocker 1 (Codex):** existing route test `test_agent_call_excluded_function_returns_404` at `tests/routes/test_agent_api.py:1114` asserts the old exact `"Unknown function: name"` string. §7 now explicitly calls for updating it to `"Unknown function: 'not_registered_tool'"` (quotes added) AND asserting absence of `"Did you mean"`.
> - **Blocker 2 (Codex):** `Formats:` injection at the `_render_method` call site was `DOCSTRING_OVERRIDES.get(name) or _docstring_with_formats(...)`, which skipped formats on overridden wrappers (`get_risk_analysis`, `analyze_option_chain`, `analyze_option_strategy`, `get_factor_analysis`). Change C now appends `Formats:` to override strings too, unless the override already contains `"Formats:"`. Test plan adds one normal-wrapper + one overridden-wrapper docstring assertion.
> - **Polish (Codex NB):** (a) `status` is keyword-only in `AgentAPIError.__init__` (`*, status: int | None = None`). (b) `_wrap_http_error` handles `exc.response is None` (rare — e.g., HTTPError raised without a response object). (c) `registry()` 404 must not be labeled `"unknown_function"` — `_error_type_from_status` is label-aware: registry-path 404s map to `"transport"`. (d) HTTP 5xx maps to `"infrastructure"` (not `"server"`) for consistency with the server-side `_postprocess_error_type` namespace at `routes/agent_api.py:283`. (e) `risk_client/README.md` updated alongside CHANGELOG. (f) Test plan adds non-JSON 5xx fallback case.

---

## 1. Problem

When an agent runs Python in the code-execution sandbox using `risk_client`, HTTP errors against the agent API surface as raw `requests.HTTPError` with no actionable text. The agent sees:

```
requests.HTTPError: 403 Client Error: Forbidden for url: https://hank.investments/api/agent/call
```

…and has to guess whether it's an auth problem, a mutation-disabled problem, a typo, or a server fault. The information needed to recover (the FastAPI `{detail: ...}` body) is on the response but never reaches the exception message. Similarly, the agent often picks the wrong `format=` value because the generated client docstring is truncated to the first line — the format options are documented on the server-side function but never make it into the wrapper.

The full ergonomics plan (R-001…R-010) addresses 11 rubric dimensions. This plan ships **only** the subset with observable code-execution failure modes today: typed-message HTTP error wrapping (R-002 collapsed onto the existing `AgentAPIError`), server-side Levenshtein for 404s (R-003's content, not its client-side warning machinery), and `Formats:` line injection on multi-format wrappers (R-008).

Explicit non-goals: new `describe()`/`guide()` methods, exception subclass hierarchy, auto-overloads, `dry_run` audit, `auth_warnings` schema tightening, `__repr__`.

---

## 2. Architectural constraint

`risk_client/__init__.py` is **generated** by `scripts/generate_risk_client.py` from `agent.registry`. CI-enforced sync test (`tests/test_risk_client_generator_sync.py`) byte-compares the generated output. Every client change lands via the generator, not by hand-editing the file.

Three edit surfaces in this plan:

| Surface | Change |
|---|---|
| `routes/agent_api.py` | Enrich 404 message with Levenshtein suggestion (one place: line 109) |
| `scripts/generate_risk_client.py` template | Wrap `requests.HTTPError` into existing `AgentAPIError` in `call()` and `registry()`; extend `AgentAPIError` ctor with optional `status` |
| `scripts/generate_risk_client.py` config | Replace `_docstring_line()` with `_docstring_with_formats()` — appends `Formats: 'a' \| 'b' \| ...` for multi-format wrappers |

No new public exception types. No new public methods. Existing `except AgentAPIError:` callers keep working. Existing `error_type` field semantics preserved.

---

## 3. Scope guardrails (do not touch)

- **No new exception subclasses.** All HTTP errors flow through the existing `AgentAPIError` class. Status is exposed as `.status` attribute.
- **No auth contract change.** Signed-claim stays the only auth path; constructor signature unchanged.
- **No removal of `call()` / `call_or_raise()` escape hatches.**
- **No removal of `ToolResult` (`dict[str, Any]`) defaults.** TypedDict returns unchanged.
- **`requests.ConnectionError` / `requests.Timeout` / `requests.exceptions.SSLError` propagate unchanged.** Only `requests.HTTPError` is wrapped — retry-aware callers depend on the network error types.
- **No `requests` version bump, no new transitive deps.** Levenshtein is hand-written (~12 lines, server-side).
- **No changes to `agent/registry.py` callable signatures.**
- **Sandbox preamble in AI-excel-addin must continue working unchanged.**

---

## 4. Out of scope (file as follow-ups)

- `describe()`/`guide()` introspection methods. Agent has `rc.registry()` + `dir(rc)` + TypedDict signatures already.
- Exception subclass hierarchy (`AgentAPIClaimError`, `AgentAPIWriteDisabledError`, …). Deferred — revisit only if agent failure analysis surfaces a need to discriminate by type rather than by message.
- `@overload` auto-discovery (R-004). Mypy polish; sandbox doesn't run mypy.
- `dry_run` audit doc (R-005).
- Uniform `auth_warnings` on TypedDicts (R-009).
- Per-format TypedDict splits (R-006).
- Class-level docstring + `__repr__` (R-007). Cosmetic.
- Client-side typo `UserWarning` on `rc.call("typo")` (R-003 client side). Server-side 404 message carries the suggestion; that's the only place it pays.

---

## 5. The three changes

### Change A — Server-side Levenshtein on 404 (`routes/agent_api.py`)

Current line 109:
```python
if not entry:
    raise HTTPException(status_code=404, detail=f"Unknown function: {function_name}")
```

After:
```python
if not entry:
    raise HTTPException(status_code=404, detail=_unknown_function_detail(function_name))
```

New helper (top of file):
```python
def _unknown_function_detail(name: str) -> str:
    registry_names = get_registry().keys()
    suggestion = _closest_name(name, registry_names, max_distance=2)
    if suggestion:
        return f"Unknown function: '{name}'. Did you mean '{suggestion}'?"
    return f"Unknown function: '{name}'"


def _closest_name(target: str, candidates: Iterable[str], max_distance: int) -> str | None:
    # Hand-written Levenshtein, ~12 lines. Returns best match within max_distance OR None.
    ...
```

The server has the full registry (~130 functions including unwrapped tools); suggestions are better than what a client-side implementation could compute against only the 80 wrappers.

**Files touched:** `routes/agent_api.py` (one helper added, one call site updated).

### Change B — Wrap `requests.HTTPError` into existing `AgentAPIError` (generator template)

Extend `AgentAPIError` constructor (`status` is keyword-only per Codex NB):
```python
class AgentAPIError(Exception):
    """Raised when the agent API returns an error envelope or HTTP error."""

    def __init__(
        self,
        function: str,
        error: str,
        error_type: str | None = None,
        *,
        status: int | None = None,
    ) -> None:
        self.function = function
        self.error = error
        self.error_type = error_type
        self.status = status
        super().__init__(f"{function}: {error}")
```

Add a private helper inside `RiskClient` (in the template). **`label` is the display string** (function name or `"registry"`) attached to the exception's `.function` attribute; **`endpoint` is the structural context** (`"call"` or `"registry"`) that drives status→error_type mapping. Keeping them separate prevents `rc.call("registry")` from being misclassified as a registry-path miss (Codex v1.1 blocker):
```python
def _wrap_http_error(
    self,
    exc: requests.HTTPError,
    *,
    label: str,
    endpoint: str,
) -> AgentAPIError:
    response = exc.response
    if response is None:
        return AgentAPIError(
            function=label,
            error=f"HTTP error (no response): {exc}",
            error_type="transport",
            status=None,
        )
    status = response.status_code
    detail = self._extract_detail(response)
    return AgentAPIError(
        function=label,
        error=detail,
        error_type=self._error_type_from_status(status, endpoint=endpoint),
        status=status,
    )

@staticmethod
def _extract_detail(response: requests.Response) -> str:
    try:
        body = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError):
        return response.text or response.reason or f"HTTP {response.status_code}"
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("error")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return str(detail)
    return str(body)

@staticmethod
def _error_type_from_status(status: int, *, endpoint: str) -> str | None:
    if status == 401:
        return "auth"
    if status == 403:
        return "permission"
    if status == 404:
        # Call-endpoint 404 = function name miss (function-not-in-registry).
        # Registry-endpoint 404 = route itself is gone — transport-shaped.
        return "unknown_function" if endpoint == "call" else "transport"
    if status == 400:
        return "bad_request"
    if status == 429:
        return "rate_limited"
    if 500 <= status < 600:
        # Align with server-side _postprocess_error_type namespace (routes/agent_api.py:283).
        return "infrastructure"
    return "transport"
```

Update `call()` and `registry()` in the template — the wrapper takes the exception itself so it can handle `response is None`:
```python
def call(self, function: str, **params: Any) -> dict[str, Any]:
    try:
        response = self._session.post(
            f"{self.base_url}/api/agent/call",
            json={"function": function, "params": params},
            headers=self._build_request_headers(),
            timeout=120,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise self._wrap_http_error(exc, label=function, endpoint="call") from exc
    return cast(dict[str, Any], response.json())

def registry(self, tier: str | None = None, category: str | None = None) -> dict[str, Any]:
    ...
    try:
        response = self._session.get(...)
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise self._wrap_http_error(exc, label="registry", endpoint="registry") from exc
    return cast(dict[str, Any], response.json())
```

**Critical guardrails:**
- Only `requests.HTTPError` is caught. `requests.ConnectionError`, `requests.Timeout`, `requests.exceptions.SSLError` propagate unchanged.
- `raise ... from exc` preserves the cause chain.
- `call_or_raise()` already raises `AgentAPIError` on `{ok: false}` envelopes — that path is unchanged; only the `raise_for_status()` path gets wrapped.
- Existing `error_type` semantics on 200-OK logical errors (set by `_postprocess_error_type` server-side) are untouched. New `error_type` values for HTTP errors are additive (`"auth"` was already a possible value).
- `AgentAPIError(function, error, error_type)` positional signature preserved — `status` is keyword-only optional. Backwards compat.

**Files touched:** `scripts/generate_risk_client.py` template (the `render_client()` f-string) + regenerated `risk_client/__init__.py`.

### Change C — `Formats:` line in generated docstrings (generator config)

Replace `_docstring_line()` at line 247 with:

```python
def _docstring_with_formats(
    fn: Any,
    signature: inspect.Signature,
    resolved_hints: dict[str, Any],
) -> str | None:
    doc = inspect.getdoc(fn)
    first_line = doc.splitlines()[0].strip().replace('"""', '\\"\\"\\"') if doc else None
    formats_line = _extract_formats_line(signature, resolved_hints)
    if first_line and formats_line:
        return f"{first_line} {formats_line}"
    return first_line or formats_line


def _extract_formats_line(
    signature: inspect.Signature,
    resolved_hints: dict[str, Any],
) -> str | None:
    format_param = signature.parameters.get("format")
    if format_param is None:
        return None
    annotation = resolved_hints.get("format", format_param.annotation)
    if get_origin(annotation) is not Literal:
        return None
    values = get_args(annotation)
    if len(values) < 2:
        return None  # single-value Literals (e.g., export_holdings(format='csv')) — skip
    rendered = " | ".join(repr(v) for v in values)
    return f"Formats: {rendered}."
```

Update the call site in `_render_method` (line 372). **Critical (Codex Blocker 2):** the prior version `DOCSTRING_OVERRIDES.get(name) or _docstring_with_formats(...)` skipped `Formats:` injection on overridden wrappers (`get_risk_analysis`, `analyze_option_chain`, `analyze_option_strategy`, `get_factor_analysis` all have multi-value format Literals + overrides). New shape composes them:

```python
override = DOCSTRING_OVERRIDES.get(function_name)
if override is not None:
    formats_line = _extract_formats_line(signature, resolved_hints)
    if formats_line and "Formats:" not in override:
        docstring = f"{override} {formats_line}"
    else:
        docstring = override
else:
    docstring = _docstring_with_formats(entry.callable, signature, resolved_hints)
```

Result on `get_positions` (no override path):
```python
def get_positions(...) -> PositionsResult:
    """Get current portfolio positions from brokerage accounts. Formats: 'full' | 'summary' | 'list' | 'by_account' | 'monitor' | 'agent'."""
    ...
```

Result on `get_risk_analysis` (overridden path — `Formats:` appended):
```python
def get_risk_analysis(...) -> RiskAnalysisResult:
    """Get risk analysis; include accepts a list, JSON array string, or comma string. Formats: 'full' | 'summary' | 'report' | 'agent'."""
    ...
```

Single-format wrappers (`export_holdings(format='csv')`) skip silently. Overrides that already contain `"Formats:"` are not re-appended (idempotent).

**Files touched:** `scripts/generate_risk_client.py` (`_docstring_line` → `_docstring_with_formats` + `_extract_formats_line`) + regenerated `risk_client/__init__.py`.

---

## 6. Implementation order

One Codex pass, one commit. All three changes are independent but small and land together.

| Step | What | Files |
|---|---|---|
| 1 | Server-side 404 enrichment + update existing 404 route test | `routes/agent_api.py` + `tests/routes/test_agent_api.py` (line 1114) |
| 2 | Generator: extend `AgentAPIError` (with `*, status` keyword-only), wrap `requests.HTTPError` in `call()` + `registry()` via `_wrap_http_error(exc, *, label, endpoint)`, endpoint-aware `_error_type_from_status`, `exc.response is None` handling | `scripts/generate_risk_client.py` template |
| 3 | Generator: `_docstring_with_formats` + extractor + override-aware composition (appends `Formats:` to overrides too) | `scripts/generate_risk_client.py` config |
| 4 | Regenerate `risk_client/__init__.py` (`python scripts/generate_risk_client.py`) | `risk_client/__init__.py` |
| 5 | Bump `risk_client/pyproject.toml` to 0.3.0 (`call()` exception type change) + update `risk_client/README.md` breaking-change section | `risk_client/pyproject.toml`, `risk_client/README.md` |
| 6 | Add tests (see §7) | New + existing test files |
| 7 | CHANGELOG entry | `CHANGELOG.md` |

Cross-cutting invariants:
- Generator sync test green after regen.
- No new transitive deps.
- AI-excel-addin sandbox preamble unchanged (no constructor/method signature changes).
- `except AgentAPIError:` keeps catching everything it used to + new HTTP wrap cases.

---

## 7. Test plan

### New tests

**`tests/test_risk_client_http_error_wrapping.py`** — covers Change B.

- 401 response → `AgentAPIError` raised with `.status == 401`, `.error_type == "auth"`, `.error` contains server's detail text.
- 403 → `.status == 403`, `.error_type == "permission"`, message contains mutation hint from server.
- 404 on `call()` → `.status == 404`, `.error_type == "unknown_function"`, message contains Levenshtein suggestion.
- 404 on `registry()` → `.status == 404`, `.error_type == "transport"` (NOT `"unknown_function"`; registry-endpoint 404 means the route is gone, not a function name miss).
- **404 on `rc.call("registry")`** → `.status == 404`, `.error_type == "unknown_function"` (Codex v1.1 blocker pin — the endpoint context is `"call"`, NOT inferred from the function name `"registry"`).
- 400 → `.status == 400`, `.error_type == "bad_request"`, message contains the rejected param name.
- 429 → `.status == 429`, `.error_type == "rate_limited"`.
- 500 → `.status == 500`, `.error_type == "infrastructure"` (matches server-side `_postprocess_error_type` namespace).
- **Non-JSON 5xx body** → `.error` falls back to `response.text` or `response.reason` (no JSONDecodeError leaks).
- **`exc.response is None`** → `AgentAPIError` raised with `.status is None`, `.error_type == "transport"`, `.error` starts with `"HTTP error (no response):"`.
- `requests.ConnectionError` → propagates unchanged (NOT caught).
- `requests.Timeout` → propagates unchanged (NOT caught).
- `requests.exceptions.SSLError` → propagates unchanged (NOT caught). Codex v1.1 NB: this was claimed in §3 + CHANGELOG but lacked a test assertion in v1.1.
- `except AgentAPIError:` catches all wrapped cases (single-catch backwards compat).
- `.__cause__` is the original `requests.HTTPError` (cause chain preserved).
- `registry()` HTTP errors carry label `"registry"` not a function name.
- `AgentAPIError(function="x", error="y", status=404)` works (keyword); `AgentAPIError("x", "y", "t", 404)` raises `TypeError` (status is keyword-only).

Use existing `_FastAPISession` harness from `tests/test_risk_client_contract.py` for the integration cases. One adapter helper required so `httpx.Response` from FastAPI `TestClient` looks like a `requests.Response` for the wrap path — small shim defined locally in the new test file (~15 lines, NOT promoted to shared fixture per Codex answer 6).

**`tests/routes/test_agent_api_unknown_function_suggestion.py`** — covers Change A.

- 404 on close typo (`get_postions`) → response body contains `"Did you mean 'get_positions'"`.
- 404 on distant garbage (`xyz`) → response body is just `"Unknown function: 'xyz'"` (no false suggestion, no `"Did you mean"` substring).
- 404 on exact mismatch but no close candidate → no suggestion appended.

**Update existing `tests/routes/test_agent_api.py:1114`** (Codex Blocker 1) — `test_agent_call_excluded_function_returns_404` currently asserts the unquoted detail string. Update assertion to `"Unknown function: 'not_registered_tool'"` (quotes added per Change A) AND assert absence of `"Did you mean"` since `not_registered_tool` is distance > 2 from any registered name.

**Extend `tests/test_risk_client_generator_sync.py`** — implicit: regen produces same byte content. No new test code, but the existing sync test fails CI until `risk_client/__init__.py` is regenerated and committed.

**Extend `tests/test_risk_client.py`** — two cases:
- Normal wrapper: `get_positions` wrapper docstring contains `"Formats:"` substring + at least one format value (covers non-override path of Change C).
- Overridden wrapper: `get_risk_analysis` wrapper docstring contains both its override prefix (`"Get risk analysis; include accepts..."`) AND `"Formats:"` substring (covers Codex Blocker 2 fix — override-aware composition).

### Existing tests must still pass

- `tests/test_risk_client.py`
- `tests/test_risk_client_contract.py`
- `tests/test_risk_client_generator_sync.py`
- `tests/routes/test_agent_api.py`
- `risk_client/_typecheck_overloads.py` (mypy)

### Manual smoke (post-deploy)

In a sandbox REPL with claim env injected:
```python
from risk_client import RiskClient
rc = RiskClient()

# Change A + B
try:
    rc.call("get_postions")  # typo
except Exception as e:
    print(type(e).__name__, e.status, e)
    # Expected: AgentAPIError 404 get_postions: Unknown function: 'get_postions'. Did you mean 'get_positions'?

# Change C
print(rc.get_positions.__doc__)
# Expected: ends with "Formats: 'full' | 'summary' | 'list' | 'by_account' | 'monitor' | 'agent'."
```

---

## 8. Rollout

Single PR, single commit (or two if Codex prefers to split server-side from client-side — review-time call). Shows:
- `routes/agent_api.py` diff (~15 lines) + `tests/routes/test_agent_api.py` line 1114 assertion update
- `scripts/generate_risk_client.py` diff (~90 lines of template + config)
- Regenerated `risk_client/__init__.py` diff (mechanical)
- Two new test files (HTTP error wrapping + 404 suggestion route test)
- Existing `tests/test_risk_client.py` extended with two docstring cases
- `risk_client/pyproject.toml` version bump 0.2.x → 0.3.0
- `risk_client/README.md` breaking-change section updated to mention exception type change
- `CHANGELOG.md` entry

Cross-repo: AI-excel-addin sandbox preamble references `RiskClient` only — does not pin to specific exception types or methods this plan touches (verified by Codex grep in v1 review: no `except requests.HTTPError` against `RiskClient` usage anywhere). No coordinated cross-repo PR needed.

CHANGELOG entry under `risk_client`:
> 0.3.0 — HTTP errors (401/403/404/400/429/5xx) are now wrapped in `AgentAPIError` with `.status` (keyword-only) and `.error_type` populated. `requests.HTTPError` is no longer raised by `call()` or `registry()`. Network errors (`ConnectionError`, `Timeout`, SSL) propagate unchanged. Server-side 404s on `call()` carry a Levenshtein "Did you mean" suggestion in the error message. Generated wrappers now include a `Formats:` line in their docstring for multi-format functions, including overridden ones.

README entry — add a paragraph to the "Breaking Change in 0.3.0" section mirroring the CHANGELOG text and showing the before/after exception shape:
```python
# Before (0.2.x):
try:
    rc.call("get_postions")  # typo
except requests.HTTPError as e:
    print(e)  # "404 Client Error: Not Found for url: ..."

# After (0.3.0):
try:
    rc.call("get_postions")  # typo
except AgentAPIError as e:
    print(e.status, e.error_type, e)
    # 404 unknown_function get_postions: Unknown function: 'get_postions'. Did you mean 'get_positions'?
```

---

## 9. Risks + mitigations

| Risk | Mitigation |
|---|---|
| External callers catching `requests.HTTPError` from `rc.call()` break | Minor version bump (0.3.0) + CHANGELOG note. Existing `except AgentAPIError:` keeps working and is the documented pattern. Internal consumer is the sandbox — already catches `AgentAPIError` or `Exception`. |
| Levenshtein false positive on the server (suggests wrong function for an intentional typo) | Distance ≤ 2 only. The suggestion is a hint in the error body; the agent still has to decide whether to retry with it. Worst case: agent sees the wrong suggestion, prints it, moves on. |
| `_extract_detail` mishandles non-JSON 5xx body | Falls back to `response.text` then `response.reason` then `f"HTTP {status}"`. Never throws. |
| Server changes 404 message format and breaks the route test | Test asserts substring (`"Did you mean"`), not exact match. Stable against minor wording tweaks. |
| Generator sync test fails on regen | By design — every plan re-runs the generator and commits. |
| `Formats:` line appears on a wrapper where `format` is unrelated to output shape (semantic mismatch) | `_extract_formats_line` only fires when `format: Literal[...]` has ≥2 values. Single-format Literals skip. If a future wrapper uses `format=` for something non-output-shape-related, the line still appears but is accurate to what the param accepts — not a correctness issue. |
| `status` attribute on `AgentAPIError` collides with existing usage | Verified: no existing code sets `.status` on `AgentAPIError` (grep). Pure addition. |

---

## 10. Codex review history

### v1 review (2026-05-26) — FAIL → addressed in v1.1

**Blockers (both resolved in v1.1):**
1. Route test `test_agent_call_excluded_function_returns_404` at `tests/routes/test_agent_api.py:1114` asserts old unquoted detail — §7 now explicitly updates it.
2. `Formats:` injection skipped overridden docstrings — Change C now composes override + `Formats:`.

**Specific answers received from Codex (folded into v1.1):**
1. **Backwards compat:** repo grep found no `except requests.HTTPError` against `RiskClient` usage. AI-excel-addin sandbox catches broad `Exception`. **0.3.0 is correct.**
2. **Error type values:** no namespace collision beyond deliberate `"auth"`. 5xx → `"infrastructure"` is preferred for consistency with `routes/agent_api.py:283`. `registry()` 404 should NOT be labeled `"unknown_function"` — label-aware mapping required. **Both folded into v1.1.**
3. **Levenshtein scope:** full registry confirmed correct — `agent_call` dispatches against full `get_registry()` at `routes/agent_api.py:107`, and unwrapped tools like `thesis_create` (registered at `agent/registry.py:1482`) are legitimate `rc.call()` targets.
4. **`_extract_detail` body shape:** FastAPI `HTTPException` paths use `{detail: ...}`; callable failures inside `_http_dispatch` are converted by `handle_http_errors` (at `services/common_helpers.py:123`) into **200 envelopes**, not 5xx. Secondary `error` probe is fine defensive code, not required for current behavior. **Plan keeps the defensive probe.**
5. **`Formats:` semantics:** all current multi-value `format: Literal[...]` params are output-shape selectors. `export_holdings(format='csv')` correctly skipped. **No semantic mismatch.**
6. **Shim placement:** keep `_RequestsLikeResponse` local to new test file.
7. **Non-blocking polish:** `*, status=None` keyword-only; `exc.response is None` handling; README update; non-JSON 5xx test. **All folded into v1.1.**

**Verification gap noted by Codex:** `python3 scripts/generate_risk_client.py --check` could not run in read-only sandbox (logging tries to open `logs/app.log` → PermissionError). Codex completed static grep/read review only. Implementation pass will run the generator + sync test in workspace-write.

### v1.1 review (2026-05-26) — FAIL → addressed in v1.2

**Blocker (resolved in v1.2):**
1. `_error_type_from_status(status, label)` conflated label with endpoint context. `rc.call("registry")` (legitimate call-path miss with function name = `"registry"`) would have mapped to `"transport"` instead of `"unknown_function"`. Fixed by splitting display label from endpoint context: `_wrap_http_error(exc, *, label, endpoint)` + `_error_type_from_status(status, *, endpoint)`. Test case added pinning this exact failure mode.

**Non-blocking (resolved in v1.2):**
2. SSL propagation was claimed in §3 + CHANGELOG but had no test assertion. Added to §7 test list.

**Confirmed passes (no change needed):**
- 404 route test update is now explicit ✓
- Change C override composition is structurally sound + idempotent ✓
- `*, status` keyword-only is backwards-compatible — all existing repo call sites use keyword construction ✓

### v1.2 review (2026-05-26, round 3) — **PASS**

Codex verdict:
1. Label/endpoint split wired consistently in Change B (verified citations: plan §5 helper signatures, all `_wrap_http_error` invocations).
2. Two 404 tests are distinguishable; Codex independently verified `agent.registry.get_registry()` does NOT contain a `"registry"` function name, so the `rc.call("registry")` test is a real call-path miss.
3. SSL propagation now in §3 + §7 + CHANGELOG with explicit test assertion.
4. No new findings, blocking or non-blocking.

Plan is implementation-ready. Dispatch via Codex MCP (`mcp__codex__codex`, `sandbox: "workspace-write"` per CLAUDE.md, or `"danger-full-access"` for the final commit step).

---

## 11. Definition of done

- All three changes shipped via Codex implementation pass, one commit (or two by Codex preference).
- Generator sync test green after regen.
- New unit tests green (`test_risk_client_http_error_wrapping.py`, `test_agent_api_unknown_function_suggestion.py`).
- Existing tests green (no regressions).
- `risk_client/pyproject.toml` bumped to 0.3.0.
- CHANGELOG entry added.
- Manual smoke verifies: typo gives suggestion in exception message; `Formats:` line appears in `get_positions.__doc__`.
- This plan moved to `docs/planning/completed/RISK_CLIENT_MINIMAL_ROBUSTNESS_PLAN.md` with ship log appended.
- Observable: agent in sandbox seeing a 403 or 404 now reads actionable hint text instead of `requests.HTTPError: ...`.

---

## Ship log

**2026-05-26** — v1.2 implemented and shipped. End-to-end smoke verified live against the running backend:

- `rc.call("get_postions")` → `AgentAPIError(status=404, error_type='unknown_function', message="get_postions: Unknown function: 'get_postions'. Did you mean 'get_positions'?")`, `__cause__` is `requests.HTTPError`.
- `rc.call("xyzzy_does_not_exist")` → 404, no false `"Did you mean"` suggestion.
- `rc.call("registry")` → `.error_type == "unknown_function"` (Codex v1.1 endpoint/label conflation blocker verified — endpoint context, not function name string, drives the 404 mapping).
- `rc.get_positions(format="summary")` happy path unchanged.
- `get_positions` (non-override path) docstring carries `Formats: 'full' | 'summary' | 'list' | 'by_account' | 'monitor' | 'agent'.`
- `get_risk_analysis` (override path) docstring carries BOTH the override prefix `"Get risk analysis;"` AND the `Formats:` line — Codex v1 Blocker 2 fix verified live.
- `AgentAPIError.__init__` rejects positional `status` (keyword-only enforced).

All 152 targeted tests pass; `python scripts/generate_risk_client.py --check` clean; mypy on `_typecheck_overloads.py` clean.

Follow-ups deferred per §4 (`describe()`/`guide()`, exception subclass hierarchy, `@overload` auto-discovery, `dry_run` audit, uniform `auth_warnings`, `__repr__`, per-format TypedDicts) — revisit only if observed agent failure modes point at them.
