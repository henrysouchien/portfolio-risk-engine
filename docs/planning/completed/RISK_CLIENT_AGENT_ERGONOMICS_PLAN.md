> **✅ CLOSED — Superseded by the shipped RiskClient minimal robustness pass; retained as historical rubric reference. Moved during 2026-05-28 docs cleanup.**

# Risk Client — Agent Ergonomics Pass  *(SUPERSEDED 2026-05-26)*

> **⚠️ SUPERSEDED — DO NOT IMPLEMENT THIS PLAN.**
>
> The load-bearing robustness subset of this plan (typed-message HTTP error wrapping, server-side 404 typo suggestion, `Formats:` line in docstrings) has been re-scoped into the **smaller, lower-surface** `RISK_CLIENT_MINIMAL_ROBUSTNESS_PLAN.md` (v1.2 PASS, 2026-05-26). The minimal plan ships those wins in one commit without the broader surface (`describe()`/`guide()` methods, exception subclass hierarchy, `@overload` auto-discovery, `dry_run` audit, uniform `auth_warnings`, `__repr__`).
>
> **Active plan:** `docs/planning/RISK_CLIENT_MINIMAL_ROBUSTNESS_PLAN.md`
>
> **Why this plan stays on file:** it's the reference document for the full 11-dimension agent-ergonomics rubric. The deferred features (`describe()`, exception subclasses, `@overload`s, etc.) are documented here in case they become load-bearing later. Per `feedback_capability_not_workflow_gate`, these capabilities are documented but not built — they'd unlock emergent workflows we haven't needed yet.
>
> **Don't:** spawn implementation against the wave breakdown below. The minimal plan supersedes it.

**Status (historical):** v3.5 — **Codex sign-off PASS 2026-05-22**. Implementation-ready. Absorbs 3 Codex v3.4 wiring blockers (httpx→requests adapter, invalid-claim for 401, local mutator registry for 403) and adds a 400 integration case. v3.5 Codex non-blocking polish baked into the wave-1 implementation brief: (i) add `seen` set in `AgentAPIError.__subclasses__()` walk for multiple-inheritance safety; (ii) 400 trigger uses a tool-with-required-param invoked without that param (`routes/agent_api.py:99` raises 400 explicitly, not 422). **SUPERSEDED before dispatch** by the minimal plan.
**Authors:** Claude + Henry
**Date:** 2026-05-21
**Mode:** Plan-first per CLAUDE.md (plan → Codex review → Codex implement)
**Audit upstream:** `/agent-ergonomics-and-intuitiveness-maximization-for-cli-tools` skill, audit-only mode, in-context.
**Target SHA:** `38262ed2` (post-`05e7ed9b Remove RiskClient bearer fallback`)

> **v1 → v2 changelog (load-bearing context):**
> v1 was drafted against a stale snapshot of `risk_client`. Mid-session, two commits landed:
> 1. `83e680a4 Clarify RiskClient wrapper param surface` — minor reformat.
> 2. `05e7ed9b Remove RiskClient bearer fallback` — **removed `api_key` constructor param and `_uses_signed_claim` attribute**; signed-claim is now the only auth path. README, tests, and generator all consistent.
>
> v2 dropped bearer references, retuned R-002 (403 → mutation-disabled), retuned R-007 (no `_uses_signed_claim`), dropped R-004's wrong candidate list for auto-discovery, fixed R-005's dry_run inventory, scoped R-010 per-function.
>
> **v2 → v3 changelog (this revision):**
> - **R-004 (Codex v2 Block 1+2):** auto-discover uses `resolved_hints` (the generator already builds these via `get_type_hints` to handle postponed annotations), AND updates `_implementation_return_type()` so the implementation return is the union of all overload variants (otherwise mypy rejects the overload set). Also skips multi-format Literals that don't include `'agent'` (overloads would be no-op).
> - **R-010 (Codex v2 Block 3):** required-key promotion is **deferred entirely** — the existing contract test already exercises non-agent formats for ≥8 aggregate TypedDicts, so promoting agent-format-only keys would make non-agent runtimes fail. Wave 3 ships R-009 (uniform `auth_warnings`) only; required-key tightening waits for R-006's per-format TypedDicts.
> - **R-001 (Codex v2 Block 4):** describe cache keyed by `type(self)` so subclasses don't share the base slot.
> - **R-002 polish:** 401 hint no longer references nonexistent `describe()['env']`; add `AgentAPIRateLimitError` (429) as a sixth subclass.
> - **R-008 polish (Codex v2 NB):** docstring lines rendered via `repr()` instead of manual `"""` escape — more robust against future content.
> - **R-005 polish:** dedup `set_target_allocation` in the inventory table; clarify it's wrapper-inventory not registry-wide.
> - Soften the "no api_key references" wording — historical/negative mentions (changelog, README breaking-change note) remain by design.
>
> **v3 → v3.1 changelog (this revision):** Codex v3 PASS with these non-blocking polish items absorbed:
> - R-002: `Retry-After` parser exposes raw value + parses seconds-int OR HTTP-date if recognized, never throws on malformed.
> - R-002: added optional `AgentAPIBadRequestError` (400) — Codex flagged as useful but not required.
> - R-005 inventory: added preview wrappers (`preview_trade`, `preview_basket_trade`, `preview_futures_roll`, `preview_option_trade`) — flagged for per-tool semantic review during the audit (preview is itself dry-run-shaped).
> - R-009: wording shifted from "21 result TypedDicts" to "every result TypedDict" (actual count: ~20 missing today out of 25 total).
> - R-010 stale wording removed from §4 and §12.
> - Describe-cache test extended to assert mutation isolation (deepcopy from cache OR documented no-mutate contract).
>
> **v3.3 → v3.4 changelog (this revision — drift-resistance hardening):**
> - **R-001:** `describe()['exceptions']` enumerates `AgentAPIError.__subclasses__()` at runtime instead of hand-coding the catalog. Test asserts every subclass appears.
> - **R-002:** added integration-test layer in `test_risk_client_error_wrapping.py` using the existing `_build_agent_api_app(monkeypatch)` + `_FastAPISession` harness from `test_risk_client_contract.py`. Three cases hit the real route layer (401/403/404) and verify the exception mapping holds against actual `routes/agent_api.py` behavior, not just mocked responses. The 401 case uses a present-but-invalid signed claim because `RiskClient` itself preflights missing claim env vars before the HTTP request. Catches drift if anyone changes route-layer status semantics without updating client.
> - **R-007:** class docstring's env var list is now generated from `_AGENT_API_CLAIM_ENV_TO_HEADER` at render time (single source of truth — same tuple the client actually reads). Generator-sync test fails CI if tuple changes without regen. Test asserts `RiskClient.__doc__` contains every name from the tuple.
> - Motivation: a v3.3 read by Henry flagged that I'd hand-waved R-007 with "future refactors will reasonably grep" — that's human-discipline, not automated. v3.4 converts every wave-1 drift surface to an automated catcher.
>
> **v3.4 → v3.5 changelog (this revision — Codex v3.4 wiring blockers):**
> - **R-001 subclass walk hardening:** filter to `cls.__module__ == AgentAPIError.__module__` (downstream user subclasses MUST NOT appear in `describe()`); recurse through full lineage (not just immediate children); sort by name for byte-deterministic output. Test asserts mocked downstream subclass does NOT appear.
> - **R-002 integration test wiring (3 fixes):** (i) `_FastAPISession` returns `httpx.Response`, but our wrap path catches `requests.HTTPError` — new test file defines a small `_RequestsLikeResponse` adapter. (ii) 401 case uses present-but-invalid signed claim, not missing env (client preflights missing). (iii) 403 requires a `read_only=False` mutator in the test registry — new test file builds its own minimal registry rather than monkey-patching `_build_agent_api_app`.
> - **R-002 added 400 integration case:** pins the recently-added `AgentAPIBadRequestError` mapping against real route behavior.

---

## 1. Problem statement

`risk_client` is the Python HTTP client that the AI sandbox (and other trusted automation) uses to call the agent execution API. 80 typed wrappers + escape-hatch `call()` / `call_or_raise()` + `registry()` for server-side discovery. Constructor takes only `base_url`; signed-claim env vars (`AGENT_API_CLAIM_*`) provide auth; runtime injects them in the sandbox.

In-context audit against the 11-dimension agent-ergonomics rubric (adapted Python ↔ CLI: docstrings ↔ `--help`, exceptions ↔ exit codes, `format='agent'` ↔ `--robot-*`, TypedDicts ↔ `--json` schema):

| Score | Dimension | Issue |
|---:|---|---|
| 800 | agent_intuitiveness | First-try success is strong; method names mirror server. |
| 800 | regression_resistance | Generator + sync test prevents client-server drift. |
| 750 | composability | Returns are dicts; errors are exceptions. |
| 650 | agent_ergonomics | One call per wrapper; no mega-method. |
| 600 | safety_with_recovery | `preview→execute` split is excellent; `dry_run` coverage inconsistent (3/many mutators). |
| 600 | determinism | Stateless calls; `use_cache` kwarg. |
| 550 | output_parseability | TypedDicts heavy on `NotRequired`; overloads only on 3 of ~33 format-discriminated methods. |
| 450 | agent_ease_of_use | `rc.registry()` undiscoverable from class surface; docstrings one-line. |
| 400 | self_documentation | Class docstring is 8 words; no `__repr__`; no client-side capabilities surface. |
| 350 | error_pedagogy | Raw `requests.HTTPError` propagates with no context. |
| 250 | intent_inference | Zero. Typo'd function name hits the server. |

**Goal:** lift the bottom four dimensions (error_pedagogy, intent_inference, self_documentation, agent_ease_of_use) to 700+ and partially close the gaps on output_parseability and safety_with_recovery, **without** breaking the generator-sync test, the auth contract, or backwards compat.

---

## 2. Architectural constraint (read this first)

`risk_client/__init__.py` is **generated** by `scripts/generate_risk_client.py` from `agent.registry`. CI-enforced sync test (`tests/test_risk_client_generator_sync.py`) byte-compares the file to `render_client()`. Codex confirmed (`python3 scripts/generate_risk_client.py --check` passes at the target SHA, no hand-edited additions survive).

**Implication:** Every recommendation lands in one of three places, not in `__init__.py` directly:

| Layer | What lives here | Used by recs |
|---|---|---|
| `scripts/generate_risk_client.py` — template (the `render_client()` f-string) | Class body shared by all wrappers: `__init__`, `call`, `call_or_raise`, `registry`, `AgentAPIError`. New shared methods go here. | R-001, R-002, R-003, R-007 |
| `scripts/generate_risk_client.py` — config (constants + `_docstring_line`, `OVERLOAD_SPECS`) | Per-wrapper rendering: which return type, how many overload variants, how much of the docstring is preserved. | R-004, R-008 |
| `risk_client/types.py` (hand-maintained) | TypedDict definitions. Not generated; not in sync test. | R-009 |
| `agent/registry.py` | `AgentFunction` metadata (`tier`, `read_only`, `category`, `has_user_email`). Drives generator decisions; read but not edited in this pass. | R-005 (read-only flag → dry_run audit) |
| `tests/test_risk_client_contract.py` | Runtime shape tests against TypedDict `__required_keys__`. | R-010 |

**Non-goal:** we do NOT loosen the generator-sync test. Every change either flows through the generator or lives in `types.py` / tests.

---

## 3. Scope guardrails (do not touch)

- **No changes to `agent/registry.py` callable signatures.** Server functions remain unchanged.
- **No changes to the auth contract.** Signed-claim is the only auth path; this pass does NOT reintroduce bearer fallback, does NOT change the `AGENT_API_CLAIM_*` env var set, and does NOT modify constructor signature.
- **No changes to `risk_client/__init__.py` outside of the generator.** All edits go through `scripts/generate_risk_client.py` and are validated by re-running the generator + sync test.
- **No removal of `call()` / `call_or_raise()` escape hatches.**
- **No removal of `ToolResult` (`dict[str, Any]`) defaults.** Tier-A wrappers keep their existing TypedDict return types (`PositionsResult`, `RiskAnalysisResult`, etc.); the rest keep `ToolResult` until each has a dedicated audit.
- **No removal of `requests.ConnectionError` / `requests.Timeout` propagation.** R-002 wraps `requests.HTTPError` only — pre-response network failures keep their original types so retry-aware callers can `except requests.ConnectionError:` as before.
- **Backwards compat: no rename/removal of existing methods or kwargs.** Additive only. `AgentAPIError` subclasses (R-002) — existing `except AgentAPIError:` catches must still catch all subclasses. New exception classes get added to `__all__`.
- **No network call from `call()` / `call_or_raise()` solely to suggest a typo.** R-003's suggestion source is the static wrapper set; `rc.registry()` is consulted only if already cached on the instance.
- **Sandbox preamble (in AI-excel-addin repo) must continue working unchanged.** `from risk_client import RiskClient` + `rc = RiskClient()` (no args) + method calls stay backwards-compat.

---

## 4. Out of scope (file as follow-ups)

- Server-side `dry_run` semantics for mutators that don't have one today. Each needs its own design (especially "dry-run a trade execution" when there's already `preview_trade → execute_trade(preview_id)` flow).
- Tightening every `NotRequired` field on result TypedDicts (required-key promotion). Deferred entirely to R-006's separate plan — see R-010 in §5.
- Refactoring how docstrings are sourced from `agent/registry.py` callables (long-form docstrings on server functions). Out of scope here; the generator already truncates, R-008 just relaxes that truncation.
- Adding a server-side `/api/agent/describe` endpoint. R-001 is **client-side** introspection only.
- Per-format TypedDict splits (the old R-006 in v1). Deferred to a separate plan — see §6 wave 4.

---

## 5. Scope — the 10 recommendations, decomposed (v2)

### Wave 1 — Generator template additions (low risk, additive)

#### R-001 · `RiskClient.describe()` + `RiskClient.guide()` + `RiskClient.tools` — client-side capabilities + handbook

Add to the generated class body in `render_client()`:

- **`RiskClient.tools`** — class-level `frozenset[str]` holding the 80 wrapper names. Emitted by the generator from its existing `WRAPPED_FUNCTIONS` tuple.
- **`describe()`** — always returns a dict `{tools, exceptions, examples, version, base_url_masked}`. **Pure client-side; no network call.** Structured introspection — designed for programmatic consumption.
  - The `exceptions` field is **auto-discovered** by walking `AgentAPIError.__subclasses__()` **recursively** at runtime, NOT hand-coded. Per-subclass entry includes `__name__`, `__doc__`, and the `status` class attribute when defined.
  - **Filter to in-module subclasses only** (per Codex v3.4 NB): `cls.__module__ == AgentAPIError.__module__`. Downstream consumers may subclass `AgentAPIError` for their own retry logic — those subclasses MUST NOT appear in `describe()` (the client never raises them, so listing them misleads the agent). `__subclasses__()` only sees immediate children, so the walk recurses through the lineage. The test for this filter mocks a hypothetical user subclass and asserts it does NOT appear in `describe()['exceptions']`.
  - **Sort the catalog by name** for stable, byte-deterministic output across re-runs.
  - A test asserts every in-module concrete `AgentAPIError` subclass appears in `describe()['exceptions']` so the auto-discovery is itself drift-checked.
- **`guide()`** — returns a paste-ready markdown handbook string, rendered from `describe()`. Designed for an agent that wants to read the handbook in chat or paste into a prompt. **No network call; calls `describe()` internally so there's no duplicated logic.**

**Two-method split rationale (per §11 Q1 resolution):** an agent reading `RiskClient` finds two verbs each with one obvious return shape (dict vs string) easier than one verb with a `format=` flag they have to remember. Matches the CLI ergonomics rubric's split between 📜 Self-Describing (structured) and 📖 In-Tool-Docs (handbook).

**Introspection rules (per Codex NB2 + v2 Block 4):**
- `describe()` introspects `type(self)` (so subclass overrides are visible).
- Per-method format-Literal extraction wraps `inspect.signature(...)` in `try / except (TypeError, ValueError)`. On failure, the entry gets `"formats": "unknown"` and we continue.
- Non-Literal `format` annotation → empty `formats` list (not a crash).
- Format extraction also resolves postponed annotations via `get_type_hints(method)` — same approach the generator uses (so `from __future__ import annotations` modules don't silently produce empty `formats`).
- **Static descriptor is cached per concrete class** (`_describe_static_cache: dict[type, dict]` class attr; lookup is `cls._describe_static_cache.get(type(self))`). Contains the format-independent parts: `tools`, `exceptions`, `examples`, `version`. **Instance-varying fields** (`base_url_masked`) are injected into a fresh dict on every call — never cached — so two instances of the same class with different `base_url`s never collide (per Codex v3.2 Block 1). Subclass overrides do not share the base-class slot. Tests pin both behaviors: (a) subclass cache independence; (b) two instances of `RiskClient` with different `base_url`s see their own URLs in `describe()` output.

**Files touched:** `scripts/generate_risk_client.py` template only (template f-string + a `_render_tools_constant()` helper).

**Operator stack:** Σ Mega-Method + 📜 Self-Describing + 📖 In-Tool-Docs.

#### R-002 · Wrap `requests.HTTPError` in typed `AgentAPIError` subclasses

Two call paths to update: `call()` (has a `function` variable) and `registry()` (no `function` variable — uses label `"registry"` per Codex Block 4).

```python
def _wrap_http_error(exc: requests.HTTPError, label: str) -> "AgentAPIError":
    response = exc.response
    status = response.status_code if response is not None else None
    body_hint = _safe_json_extract(response)
    if status == 401:
        return AgentAPIClaimError(label, status, body_hint)
    if status == 403:
        return AgentAPIWriteDisabledError(label, status, body_hint)
    if status == 404:
        return AgentAPIUnknownFunctionError(label, status, body_hint, RiskClient.tools)
    if status == 429:
        raw_retry = response.headers.get("Retry-After") if response is not None else None
        return AgentAPIRateLimitError(label, status, body_hint, raw_retry)  # parses inside ctor; never throws
    if status == 400:
        return AgentAPIBadRequestError(label, status, body_hint)
    if status is not None and 500 <= status < 600:
        return AgentAPIServerError(label, status, body_hint)
    return AgentAPITransportError(label, status, body_hint)
```

Use sites:

```python
def call(self, function: str, **params: Any) -> dict[str, Any]:
    try:
        response = self._session.post(...)
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise _wrap_http_error(exc, function) from exc
    return cast(dict[str, Any], response.json())

def registry(self, ...) -> dict[str, Any]:
    try:
        response = self._session.get(...)
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise _wrap_http_error(exc, "registry") from exc
    return cast(dict[str, Any], response.json())
```

**Subclass catalog** (all extend `AgentAPIError`; existing `except AgentAPIError:` keeps catching):

| Subclass | Status | Meaning + hint |
|---|---|---|
| `AgentAPIClaimError` | 401 | Signed-claim invalid/expired/missing. Hint: "check `AGENT_API_CLAIM_*` env vars (`AUDIENCE`, `ISSUED_AT`, `EXPIRY`, `USER_ID`, `USER_EMAIL`, `NONCE`, `SIGNATURE`)." |
| `AgentAPIWriteDisabledError` | 403 | Server has `AGENT_API_ALLOW_WRITES=false`; this is a mutator. Hint: "the agent API is currently read-only; this function is a mutator." (Per v1 Block 4: 403 ≠ auth in `routes/agent_api.py`.) |
| `AgentAPIUnknownFunctionError` | 404 | Function name not registered. Hint: Levenshtein suggestions from `RiskClient.tools`. |
| `AgentAPIRateLimitError` | 429 | Route limiter triggered (currently only `POST /call` is rate-limited per `routes/agent_api.py`). `Retry-After` exposed when set: raw header value, plus parsed seconds-int **or** HTTP-date if format recognized. Malformed header never throws — falls through to raw-only. |
| `AgentAPIBadRequestError` | 400 | Optional dedicated subclass for client-side input validation failures (per Codex v3 NB). Includes body snippet so the agent can see *which* param the server rejected. |
| `AgentAPIServerError` | 5xx | Server fault. Includes status + body snippet. |
| `AgentAPITransportError` | other (e.g. 408, 451) | Generic. Includes status + body snippet. |

**Critical guardrails (per Codex NB10):**
- ONLY `requests.HTTPError` is wrapped. `requests.ConnectionError`, `requests.Timeout`, `requests.exceptions.SSLError` etc. **propagate unchanged** — retry-aware callers depend on these types.
- All new subclasses preserve `.function` (or `.label` for registry), `.status`, `.error`, `.error_type` attributes. Add `__all__` exports.
- `raise ... from exc` preserves the cause chain.

**Files touched:** `scripts/generate_risk_client.py` template only.

#### R-003 · Levenshtein-1/2 typo suggestion in `call()` / `call_or_raise()`

**Suggestion source (per Codex Block 5 + NB3):** static `RiskClient.tools` (80 wrappers) **only** — no network. If the instance has already called `rc.registry()` previously, the result is cached on `self._registry_cache`, and the suggester augments with those names (this is opt-in via the user calling `registry()`; `call()` never triggers a fresh registry fetch).

**Behavior:**

```python
def call(self, function: str, **params: Any) -> dict[str, Any]:
    if function not in RiskClient.tools and function not in self._registry_cache_names():
        suggestion = _closest_tool(function, RiskClient.tools | self._registry_cache_names(), max_distance=2)
        if suggestion:
            warnings.warn(
                f"call({function!r}): not in risk_client wrappers — did you mean {suggestion!r}? "
                f"Continuing in case the server has it (see rc.describe() for known wrappers).",
                UserWarning, stacklevel=2,
            )
    # Continue with POST regardless — the server is the source of truth.
    ...
```

**Why warn-not-block:** the server registers more functions than `WRAPPED_FUNCTIONS` covers (per Codex NB3, ~50 registered tool-tier functions are unwrapped — research tools, etc.). A legitimate `rc.call('thesis_create')` should work; we just emit a warning if the user appears to have typo'd a wrapper name.

**Helpers:**
- `_closest_tool(name, names, max_distance)` — hand-written Levenshtein, returns the closest match within distance OR None.
- `self._registry_cache_names()` — returns a set of names from cached `registry()` result; empty set if never called.

**Files touched:** `scripts/generate_risk_client.py` template only.

#### R-007 · Class-level docstring + `__repr__`

Replace the current `class RiskClient:` (no docstring) with:

```python
class RiskClient:
    """HTTP client for the agent execution API.

    Quick start:
        from risk_client import RiskClient
        rc = RiskClient()                  # reads RISK_API_URL + AGENT_API_CLAIM_* env
        rc.run_monte_carlo(num_simulations=1000)
        rc.describe()                      # structured dict — wrappers, exceptions, version
        rc.guide()                         # paste-ready markdown handbook
        rc.registry()                      # server-side function catalog

    Auth: signed-claim env vars are injected by the agent runtime
    ({CLAIM_ENV_NAMES_RENDERED_AT_GENERATE_TIME}).
    The constructor only accepts base_url; bearer-token fallback was removed in
    risk_client 0.3.

    Raises AgentAPIError (and subclasses) on server-side failure. Network errors
    (requests.ConnectionError, requests.Timeout) propagate unchanged. See
    rc.describe()['exceptions'] for the full catalog.
    """

    def __repr__(self) -> str:
        host = urlparse(self.base_url).netloc or self.base_url or "<unset>"
        return f"RiskClient(base_url={host!r})"
```

`__repr__` shows only host; nothing else to leak (no api_key, no claim values).

**Docstring drift resistance (v3.4 addition):** the `{CLAIM_ENV_NAMES_RENDERED_AT_GENERATE_TIME}` placeholder is interpolated by `render_client()` from `_AGENT_API_CLAIM_ENV_TO_HEADER` — the same tuple the client actually reads to build request headers. **Single source of truth:** changing the tuple (which controls real client behavior) automatically updates the docstring on next regen. The generator-sync test fails CI if anyone changes the tuple without regenerating. A unit test asserts `RiskClient.__doc__` contains every name from `_AGENT_API_CLAIM_ENV_TO_HEADER`. Belt-and-suspenders — eliminates the manual-grep drift surface entirely.

**Files touched:** `scripts/generate_risk_client.py` template only.

---

### Wave 2 — Generator config (additive, slightly larger diff)

#### R-004 · Extend `@overload` to format-discriminated methods (auto-discovered)

**Per Codex Block 2 + Block 5 + NB7**, drop the hand-maintained candidate list. The generator inspects each wrapper's signature at generate-time and applies this rule:

A wrapper is **overload-eligible** iff:
- It has a parameter named `format` resolved to `Literal[<values>]` (via `get_type_hints(...)`, the same approach the generator already uses for other annotations) with ≥ 2 values, AND
- One of those values is `'agent'` (otherwise overloads would all return the same aggregate type — pure noise; per Codex v2 NB), AND
- It is not already in `OVERLOAD_SPECS` (the 3 hand-curated ones stay).

For each eligible wrapper, emit overloads as:

| Literal value | Overload return type |
|---|---|
| `'agent'` | `AgentEnvelope` |
| *any other value* | **The method's existing aggregate return type** (e.g., `PositionsResult` for `get_positions`, `ToolResult` for un-typed wrappers) |

**The key correction from v1 Block 2:** non-agent overloads do NOT downgrade to `ToolResult` — they preserve whatever the wrapper currently returns. The win is *adding the `'agent'` overload* so callers using `format='agent'` get `AgentEnvelope` narrowing.

**v2 Block 1+2 fixes (load-bearing):**

1. **Use `resolved_hints`, not raw `annotation`.** The registry callables sit behind `from __future__ import annotations`, so `format_param.annotation` is a string at signature-inspect time. The generator already builds `resolved_hints = get_type_hints(entry.callable, include_extras=True)` for exactly this reason ([generate_risk_client.py L309](../../scripts/generate_risk_client.py)). `_autodiscover_overload` MUST consult `resolved_hints["format"]` not `format_param.annotation`.
2. **Update `_implementation_return_type()` too.** Today it only consults `OVERLOAD_SPECS` to compute the impl return type as `Union[variant_types...]`. The autodiscover path must hook the same branch so the impl's return annotation widens to e.g. `AgentEnvelope | PositionsResult` when overloads exist. Without this, mypy rejects the overload set ("overload signatures incompatible with implementation").

Implementation sketch:

```python
def _autodiscover_overload(
    function_name: str,
    signature: inspect.Signature,
    resolved_hints: dict[str, Any],
) -> tuple[tuple[str, str, bool], ...] | None:
    if function_name in OVERLOAD_SPECS:
        return None  # hand-curated wins
    format_param = signature.parameters.get("format")
    if format_param is None:
        return None
    annotation = resolved_hints.get("format", format_param.annotation)
    if get_origin(annotation) is not Literal:
        return None
    values = get_args(annotation)
    if len(values) < 2:
        return None  # single-value (e.g., export_holdings(format='csv')) — skip
    if "agent" not in values:
        return None  # no agent variant → overload set would be no-op — skip
    aggregate_return = RETURN_TYPE_OVERRIDES.get(function_name, DEFAULT_RETURN_TYPE)
    default_value = (
        format_param.default
        if format_param.default is not inspect.Parameter.empty
        else values[0]
    )
    return tuple(
        (
            value,
            "AgentEnvelope" if value == "agent" else aggregate_return,
            value == default_value,
        )
        for value in values
    )


def _effective_overload_spec(
    function_name: str,
    signature: inspect.Signature,
    resolved_hints: dict[str, Any],
) -> tuple[tuple[str, str, bool], ...] | None:
    """Single source of truth — used by both _render_overloads and _implementation_return_type."""
    if function_name in OVERLOAD_SPECS:
        return OVERLOAD_SPECS[function_name]
    return _autodiscover_overload(function_name, signature, resolved_hints)
```

Both `_render_overloads` (existing) and `_implementation_return_type` (modify) read from `_effective_overload_spec`. `_implementation_return_type` becomes:

```python
def _implementation_return_type(function_name: str, signature, resolved_hints) -> str:
    spec = _effective_overload_spec(function_name, signature, resolved_hints)
    if spec is None:
        return RETURN_TYPE_OVERRIDES.get(function_name, DEFAULT_RETURN_TYPE)
    ordered_types: list[str] = []
    for _, return_type, _ in spec:
        if return_type not in ordered_types:
            ordered_types.append(return_type)
    return " | ".join(ordered_types)
```

**Test addition:** extend `risk_client/_typecheck_overloads.py` with `assert_type` checks for at least 3 newly-overloaded methods. For example: `get_positions(format='agent')` narrows to `AgentEnvelope`; `get_positions()` still returns `PositionsResult`; `get_risk_analysis(format='agent')` narrows to `AgentEnvelope`.

**Files touched:** `scripts/generate_risk_client.py` (new helpers + `_render_overloads` + `_implementation_return_type` refactor) + `risk_client/_typecheck_overloads.py` (new asserts).

#### R-005 · Audit `dry_run` consistency on mutators (audit doc only)

**Current wrapper-inventory state (per `grep dry_run risk_client/__init__.py` at target SHA — note this is the **wrapper** view, not the full registry-wide mutator list; per Codex v2 NB):**

| Wrapper | Has `dry_run`? |
|---|---|
| `cancel_order` | ✅ |
| `delete_portfolio` | ✅ |
| `delete_basket` | ✅ |
| All other mutators (`set_target_allocation`, `set_risk_profile`, `account_activate`, `account_deactivate`, `update_basket`, `update_portfolio_accounts`, `execute_trade`, `execute_basket_trade`, `execute_option_trade`, `execute_futures_roll`, `record_workflow_action`, `update_action_status`, `create_portfolio`, `create_basket`, `create_basket_from_etf`, `manage_ticker_config`, `refresh_transactions`, `fetch_provider_transactions`) | ❌ |
| Preview-side of preview/execute pairs (`preview_trade`, `preview_basket_trade`, `preview_futures_roll`, `preview_option_trade`) — per Codex v3 NB, called out separately because dry-run semantics may not apply (preview is itself dry-run-shaped; the audit decides per-tool whether to add anyway) | ❌ (semantically n/a — review during audit) |

**Task (Wave 2):**

1. **Audit doc** — write `docs/planning/RISK_CLIENT_DRY_RUN_AUDIT.md` listing each `read_only=False` registration in `agent/registry.py`, whether its server-side callable accepts a `dry_run` param, and a one-line note about whether dry-run semantics make sense for that operation (e.g., `execute_trade` *already* has dry-run semantics via `preview_trade`).
2. **Regen verification** — re-run `python scripts/generate_risk_client.py --check`. If any wrapper is stale relative to its server signature, regenerate; otherwise no-op.
3. **No server-side dry_run additions in this pass.** Per Codex NB9 guardrail. Each missing dry_run becomes a separate follow-up plan.

**Files touched:** `docs/planning/RISK_CLIENT_DRY_RUN_AUDIT.md` (new). Possibly `risk_client/__init__.py` if regen is stale (no-op expected).

#### R-008 · Richer per-method docstrings + `Formats:` injection

Today the generator truncates docstrings to first line via `_docstring_line()`. Relax to multi-line:

```python
def _docstring_block(fn: Any) -> str | None:
    """Render the docstring as a Python string literal — robust against any content.

    Using repr() guarantees triple-quotes, backslashes, braces, and embedded newlines
    are all encoded safely. Caller emits ``f'        {literal}'`` so the indentation
    line up. (Per Codex v2 NB: repr-based renderer is preferred to ad-hoc escape.)
    """
    doc = inspect.getdoc(fn)
    if not doc:
        return None
    return repr(doc)  # e.g., "'Get current portfolio positions...'"
```

The emitter writes `f"        {literal}"` (a one-line string statement that's a valid Python expression — Python accepts a bare string literal as a docstring). For multi-line docstrings this is one long line with `\n` escapes embedded; readers may find this less pretty than a true triple-quoted block, but it's bulletproof against the f-string interpolation in `render_client()`. We accept the cosmetic trade-off for safety.

And inject a `Formats:` line listing the Literal options where applicable (auto-discovered alongside R-004):

```python
def get_positions(...) -> PositionsResult:
    """Get current portfolio positions from brokerage accounts.

    Formats: 'full' (default) | 'summary' | 'list' | 'by_account' | 'monitor' | 'agent'.
    """
```

**Per Codex NB5 confirmed scan results** of all 80 registry callable docstrings: 22 multi-line, 3 contain `{`/`}` braces (safe inside the rendered `methods` block — not f-string interpolated), 0 contain triple quotes today, 0 contain backslashes. **Safe to ship.** The triple-quote escape is defensive for future additions.

**Caveat:** the *content* of richer docstrings depends on server-side function docstrings. If those are one-liners, this rec degrades to a Formats: injection only — still a major discoverability win.

**Files touched:** `scripts/generate_risk_client.py` (`_docstring_line` → `_docstring_block`, plus `_format_options_line()` injector).

---

### Wave 3 — Types + tests (no generator changes)

#### R-009 · Uniform `auth_warnings` on every result TypedDict

Add `auth_warnings: NotRequired[list[AuthWarning]]` to every result TypedDict in `types.py` that doesn't already have it. Per Codex v3 NB: `types.py` defines 25 TypedDicts total; excluding the `AuthWarning` helper and `AgentEnvelope`, ~20 currently lack `auth_warnings`. The audit task lists every result-shape TypedDict by name in the PR description, not by count. Since `auth_warnings` is `NotRequired`, this is purely a contract-tightening addition — existing runtime payloads continue to validate; new payloads that emit `auth_warnings` get typed access.

**Files touched:** `risk_client/types.py` only.

#### R-010 · Required-key promotion — **DEFERRED to R-006's plan**

**Per Codex v2 Block 3:** v2's idea of "promote agent-format keys to required, parametrize the contract test" is still unsafe because `tests/test_risk_client_contract.py` already exercises non-agent formats for ≥8 aggregate TypedDicts (`RiskAnalysisResult`, `RiskScoreResult`, `PerformanceResult`, `OptimizationResult`, `WhatIfResult`, `IncomeProjectionResult`, `FactorAnalysisResult`, `TaxLossHarvestResult`). Promoting agent-format-only keys (e.g. `snapshot`, `flags`) would cause the summary/full/report fixtures to fail.

The only safe required-key promotion is "fields present across ALL formats" — which is essentially `status` (already required) and nothing else for most aggregate TypedDicts. Tightening further requires the **per-format TypedDict split** (R-006), which is already deferred to its own plan.

**Decision:** R-010 ships **only** as a contract-test parametrize extension that adds non-agent-format coverage for any TypedDict not currently parametrized (verify against the existing case list). No `__required_keys__` promotions in this pass. The required-key tightening becomes part of the R-006 follow-up plan.

**Files touched:** `tests/test_risk_client_contract.py` (additional parametrize cases for any TypedDict missing non-agent-format coverage). `risk_client/types.py` is **not** touched by R-010 — R-009 is the only types.py edit in wave 3.

---

### Wave 4 — Per-format TypedDicts (deferred to separate plan)

#### R-006 · Split monolithic TypedDicts into per-format variants

**Deferred per v1 + reaffirmed by Codex NB6.** True non-agent per-format splits require contract coverage for every `format=` runtime path, which doesn't exist yet. The wave-2 R-004 fallback rule (preserve existing aggregate return types for non-agent overloads) is the bridge that lets R-004 ship without R-006.

File as `docs/planning/RISK_CLIENT_PER_FORMAT_TYPEDICTS_PLAN.md` follow-up.

---

## 6. Implementation order + sequencing

One Codex implementation pass per wave. Each wave is its own commit.

| Wave | Recs | Files changed | Tests run | Risk |
|---:|---|---|---|---|
| 1 | R-001, R-002, R-003, R-007 | `scripts/generate_risk_client.py` (template only) + regenerated `risk_client/__init__.py` | sync test, contract test, full `test_risk_client.py`, new `test_risk_client_describe.py`, `test_risk_client_typo_suggestion.py`, `test_risk_client_error_wrapping.py`, `test_risk_client_repr.py` | Low |
| 2 | R-004, R-005, R-008 | `scripts/generate_risk_client.py` (config + auto-discover) + regenerated client + new `docs/planning/RISK_CLIENT_DRY_RUN_AUDIT.md` + extended `_typecheck_overloads.py` | sync test + new mypy asserts | Low-medium |
| 3 | R-009, R-010 | `risk_client/types.py` (R-009 only — add `auth_warnings` uniformly) + `tests/test_risk_client_contract.py` (R-010: add non-agent-format parametrize cases; no `__required_keys__` promotions) | contract test (parametrize expansion) + sync test (no-op verification) | Low |
| 4 | R-006 | *Deferred — separate plan.* | — | High (deferred) |

**Cross-wave invariants:**
- Generator sync test passes after each wave (regenerate + commit).
- No new transitive deps. Levenshtein is hand-written (~15 lines).
- No `requests` version bump.
- AI-excel-addin sandbox preamble unchanged.
- Auth contract unchanged (signed-claim only).

---

## 7. Test plan

### New tests

- **`tests/test_risk_client_describe.py`** — verifies `rc.describe()` returns expected dict structure; `rc.guide()` returns non-empty markdown string and mentions each of the 80 wrapper names at least once; `RiskClient.tools` is a frozenset matching `WRAPPED_FUNCTIONS`; describe survives a wrapper with non-Literal `format` annotation (synthesized via subclass) without crashing; **subclass `describe()` does NOT share base-class cache** (v2 Block 4 fix — define a subclass with an extra wrapper, call describe on both base and subclass instances, assert the subclass result contains the extra wrapper). Also assert **instance-data isolation** (v3.2 Block 1 fix): two `RiskClient` instances with different `base_url`s — assert each `describe()` result reports its own URL in `base_url_masked`, NOT the first instance's URL leaking via class cache. Also assert **mutation isolation**: mutating one caller's `describe()` dict (e.g., `result['tools']['x'] = 'mutated'`) does NOT affect another caller's result — either return a deepcopy from the cache, or document that callers must not mutate. Optionally assert `guide()` delegates through `describe()` (Codex v3.2 NB).
- **`tests/test_risk_client_typo_suggestion.py`** — `rc.call('get_postions')` emits UserWarning naming `get_positions`; distance-2 typo also warns; distance-3+ does not; legitimate-but-unwrapped function (e.g. `'thesis_create'`) does NOT warn (it's an exact-match in cached registry if loaded, or simply distance > 2 from any wrapper).
- **`tests/test_risk_client_error_wrapping.py`** — two layers per v3.4:

  **(a) Unit layer — mocked responses.** Mocked 401 → `AgentAPIClaimError`; 403 → `AgentAPIWriteDisabledError`; 404 → `AgentAPIUnknownFunctionError` (with Levenshtein suggestions in message); 429 → `AgentAPIRateLimitError` (with `Retry-After` parsed when header set; malformed header doesn't throw); 400 → `AgentAPIBadRequestError`; 500 → `AgentAPIServerError`; 451 → `AgentAPITransportError` (generic fallback); **`except AgentAPIError:` still catches all seven subclasses**. **Mocked `requests.ConnectionError` and `requests.Timeout` propagate unchanged** (per v1 NB10). Registry-path errors use label `'registry'` not a function name.

  **(b) Integration layer — real FastAPI route (v3.4 + v3.5 wiring fixes).** Reuses `_build_agent_api_app(monkeypatch)` from `tests/test_risk_client_contract.py` to hit the **actual `routes/agent_api.py` route layer**, not mocks. Three wiring fixes required (per Codex v3.4 review blockers):

  - **Wiring fix 1 — httpx ↔ requests adapter.** `_FastAPISession` in the contract test returns FastAPI `TestClient` responses (`httpx.Response`); their `.raise_for_status()` raises `httpx.HTTPStatusError`, NOT `requests.HTTPError`. Our wrap path catches only `requests.HTTPError` (correct in prod — `risk_client` uses `requests`). Solution: the new test file defines a small `_RequestsLikeResponse` adapter (a thin wrapper around the httpx response) so `.raise_for_status()` raises a `requests.HTTPError` with the matching status + body. Keeps prod code requests-only; localizes the test-harness translation. Use this adapter in place of `_FastAPISession` for the integration cases.
  - **Wiring fix 2 — 401 uses an INVALID claim, not missing claim.** `RiskClient.__init__` preflights all 7 `AGENT_API_CLAIM_*` env vars and raises a local `ValueError` if any are missing — before any HTTP request. To get a real route-layer 401, the test sets all 7 env vars with a **deliberately bad signature** (e.g., signed with wrong HMAC key, or wrong audience). The server's claim verifier then 401s and the client wraps it as `AgentAPIClaimError`. Test fixture builds the bad-claim env via `agent_claim.sign(...)` with a non-matching HMAC key.
  - **Wiring fix 3 — 403 needs a mutator in the test registry.** `_build_agent_api_app(monkeypatch)` today hard-codes a single `read_only=True` tool, so route 403 (which requires `not entry.read_only and not AGENT_API_ALLOW_WRITES`) cannot fire. The new test file defines its own minimal registry (or wraps the helper) that includes a `read_only=False` mutator. Keeps the contract test's helper unchanged and the new file fully self-contained.

  Cases pinning the route ↔ exception contract (minimum four — added 400 per Codex v3.4 NB):
  - **401** real-route: present-but-invalid signed claim → `AgentAPIClaimError`.
  - **403** real-route: mutator (`read_only=False` test registry) called with `AGENT_API_ALLOW_WRITES=False` → `AgentAPIWriteDisabledError`.
  - **404** real-route: unknown function name → `AgentAPIUnknownFunctionError`.
  - **400** real-route: malformed request body (e.g., invalid params shape) → `AgentAPIBadRequestError`. Cheap to trigger; pins the recently-added 400 mapping.

  This catches drift if anyone changes route-layer status code semantics without updating the client mapping. Without (b), the unit layer would silently pass while production fails.
- **`tests/test_risk_client_repr.py`** — `repr(rc)` includes only base_url host; never leaks claim values or env contents.

### Existing tests must still pass

- `tests/test_risk_client.py`
- `tests/test_risk_client_contract.py`
- `tests/test_risk_client_generator_sync.py`
- `risk_client/_typecheck_overloads.py` (mypy)
- All `tests/mcp_tools/test_*_agent_format.py`

### Manual smoke

After each wave, in a Python REPL with sandbox env injected:

```python
from risk_client import RiskClient
rc = RiskClient()                              # base_url from env
print(repr(rc))                                # R-007
print(sorted(RiskClient.tools)[:5])            # R-001
print(rc.describe()['tools']['get_positions']) # R-001
rc.call("get_postions")                        # R-003 — should warn before erroring
```

---

## 8. Rollout

- Single PR per wave. Each PR shows: generator diff + regenerated client diff + new tests. Reviewer can re-run `python scripts/generate_risk_client.py --check` locally.
- No staged feature flag; additions are pure-additive. Existing callers see no behavior change.
- The AI-excel-addin sandbox preamble references `RiskClient` only — it does not pin to any new method. No coordinated cross-repo PR needed for waves 1-3.

---

## 9. Risks + mitigations

| Risk | Mitigation |
|---|---|
| `describe()` runtime introspection slow on first call | Static descriptor cached on `RiskClient._describe_static_cache` (class attr, per `type(self)`); ~1ms cold path is fine. Instance-varying fields injected per call (v3.3). |
| Levenshtein false positive (warns "did you mean: X" when user wanted a valid unwrapped function) | **Warn, don't block.** Server's 404 path is the source of truth; suggestion is hint-only. Cached `rc.registry()` augments the known-good set. |
| `AgentAPIError` subclass introduction breaks existing `except AgentAPIError as e: e.error_type` users | All subclasses preserve `function`/`error`/`error_type` attributes; downstream code unaffected. New status + label attributes added but don't replace existing ones. |
| Richer docstrings exceed line-budget heuristic in `_format_signature` | Multi-line docstrings don't interact with signature line budget (`_format_signature` measures the `def` line only). Verified by reading `_format_signature`. |
| Generator-sync test failure on regenerate | **By design** — every wave re-runs the generator and commits the new `__init__.py`. The CI test enforces "did you forget to regenerate?". |
| R-002 wrapper hides original network exception | Use `raise ... from exc` to preserve cause; `requests.ConnectionError` / `Timeout` propagate as-is. |
| `inspect.signature` raises on a monkey-patched wrapper | Caught and downgraded to `"formats": "unknown"` per R-001 introspection rules. |
| 403 misclassified as auth issue | Per Codex Block 4, 403 = mutation disabled (`AGENT_API_ALLOW_WRITES=false`). Subclass message reflects this. |

---

## 10. Codex review prompts (v3 — what to ask Codex this round)

When sending v3 to Codex for review:

1. **Verify v2 → v3 changelog.** Confirm each v2 blocker is resolved:
   - R-004 auto-discover now uses `resolved_hints` instead of raw `format_param.annotation` (Block 1).
   - R-004 auto-discover threads through `_implementation_return_type` via a new `_effective_overload_spec` helper so impl + overloads agree (Block 2).
   - R-010 is deferred to R-006's plan; wave 3 ships R-009 + contract-test parametrize extension only (Block 3).
   - `describe()` static cache is keyed by `type(self)` via `_describe_static_cache: dict[type, dict]` (Block 4); per-call instance-data injection added in v3.3.
2. **R-002 + 429.** `AgentAPIRateLimitError` added with `Retry-After` parsing. Is the parsing right (header can be seconds-integer OR HTTP-date)? Any other 4xx I should distinguish (408 timeout? 451 unavailable-for-legal)?
3. **R-004 implementation hook.** `_effective_overload_spec` is the new single source of truth, called from both `_render_overloads` and `_implementation_return_type`. Does this fit the generator's existing structure (`_render_method` already builds `resolved_hints`)? Any plumbing I'm missing — e.g., does `_implementation_return_type` need to be called from a different code path I didn't update?
4. **R-008 repr-based renderer.** Producing a single-quoted one-line literal as the docstring is correct (Python accepts any string literal as the first-statement docstring). But: is there a readability cost in the generated file that outweighs the safety? Would a guarded `repr()` wrapped to multi-line via `textwrap.dedent` + triple-quote with `"""` → `\\"\\"\\"` substitution be better? Or is this overthinking it?
5. **R-010 deferral.** Agree that required-key promotion can't ship cleanly without per-format TypedDicts (R-006)? Is the contract-test parametrize extension (add missing non-agent cases) worth the wave-3 slot, or also defer?
6. **Subclass cache test.** Is the proposed test for `describe()` cache independence sufficient (synthesize a subclass with extra wrapper, assert subclass result contains it), or do you see edge cases?
7. **What I missed.** Anything not in v3 that should be? Anything in v3 that should be cut?

Iterate until **PASS**. Address ALL findings including non-blocking.

---

## 11. Resolved open questions (2026-05-21)

- **`describe()` shape:** Split into `describe()` (returns dict) + `guide()` (returns markdown string). Two verbs each with one obvious return shape are easier for an agent to internalize than one verb with a `format=` kwarg flag. `guide()` calls `describe()` internally — no duplicated logic.
- **R-005 audit doc:** Ships inside wave 2 PR (it IS the wave-2 R-005 deliverable per Codex v3 NB). Not a separate prep PR.
- **Exception names:** Kept as-is — `AgentAPIClaimError` / `AgentAPIWriteDisabledError` / `AgentAPIUnknownFunctionError` / `AgentAPIRateLimitError` / `AgentAPIBadRequestError` / `AgentAPIServerError` / `AgentAPITransportError`. All subclass `AgentAPIError`.
- **R-006 stub:** Yes — `docs/planning/RISK_CLIENT_PER_FORMAT_TYPEDICTS_PLAN.md` exists as a ~1-page deferred-work outline so the deferral is concrete (per CLAUDE.md "Don't defer to dodge friction"), not hand-waving.

---

## 12. Definition of done

- All three waves shipped via Codex implementation passes, each behind its own commit + PR (or single squashed PR if you prefer).
- Generator sync test green.
- Contract test green with the new non-agent-format parametrize cases (R-010 — no `__required_keys__` promotions in this pass).
- `_typecheck_overloads.py` mypy clean with new assertions.
- New unit tests (describe / typo / error wrapping / repr) green; `ConnectionError` / `Timeout` propagation tests green.
- This plan doc moved to `docs/planning/completed/RISK_CLIENT_AGENT_ERGONOMICS_PLAN.md` with a ship log appended.
- Re-score (in-context, follow-up turn): every dimension that was below 700 is now ≥700 *except* output_parseability (gated on R-006 in the separate plan).
