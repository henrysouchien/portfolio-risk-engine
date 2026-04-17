# Research Workspace MCP Tool Surface

**Status**: DRAFT v11 (Codex R1-R10: 14→2→4→4→4→4→4→4→3→1 findings, all fixed)
**Closes**: TODO §"Research Workspace MCP Tool Surface". **Partially addresses** F33 (agent-mediated build via MCP; full F33 needs upstream override support).

---

## Goal

Expose the research workspace through MCP so agents can drive the capture → diligence → handoff → model-build pipeline without the frontend. Explore/chat is read-only (agents can read threads but sending messages requires gateway SSE transport — deferred). 15 workflow-level tools, not 25 REST-level endpoints.

## Codex R1 Findings — Resolution Summary

| # | Finding | Resolution |
|---|---------|------------|
| 1 | `send_research_message` uses wrong transport (`POST /chat` not `POST /messages`) | **Deferred.** Chat goes through gateway SSE streaming — different transport. Read-only `read_research_thread` retained. Agent-initiated research chat needs upstream design. |
| 2 | Rollout phasing doesn't match upstream phases | **Clarified.** MCP phases are implementation phases (what code we write when), not upstream deployment phases. Renamed for clarity. |
| 3 | Excluding `new-version` breaks lifecycle | **Added** `new_handoff_version` tool. |
| 4 | Sync gateway client underspecified, duplicates auth logic | **Redesigned.** Async adapter wrapping existing `GatewaySessionManager` via `asyncio.run()` (safe: `nest_asyncio` applied). Zero duplication. |
| 5 | Error mapping incomplete (`cross_user_reuse`, `credentials_unavailable`) | **Fixed.** Full error mapping including all known upstream codes. |
| 6 | `ActionError` hierarchy lost at MCP boundary | **Fixed.** MCP layer does explicit `ActionError` subclass dispatch before `handle_mcp_errors` fallback. |
| 7 | Registry `_unwrap` bypasses `@handle_mcp_errors` | **Fixed.** Register action-layer functions (undecorated), not MCP tool functions. |
| 8 | File snapshot inflated beyond upstream surface | **Fixed.** Snapshot matches `GET /files` response: basic metadata only. Enrichment available via per-file `get_diligence_state`. |
| 9 | `load_document` half-designed (no section param, no ingest) | **Fixed.** Added `section` param. Added `ingest_document` tool. |
| 10 | `update_diligence` needless multiplexing | **Split** into `update_diligence_section` + `manage_qualitative_factor`. |
| 11 | No timeout policy for long-running calls | **Fixed.** Explicit timeouts matching proxy: `connect=10s, read=None, write=30s, pool=30s`. |
| 12 | `resolve_action_context()` can return `user_id=None` | **Fixed.** Explicit `ActionValidationError` if `user_id` is None after resolution. |
| 13 | Write tools chain public read tools (backwards layering) | **Fixed.** Actions call gateway helpers directly. Shared private helpers in action layer. |
| 14 | Integration tests optional is weak | **Fixed.** Integration test against live upstream required in implementation Phase 2 gate. |

---

## Design Decisions

### D1 — Tool granularity: workflow-level, not REST-level

Each MCP tool wraps 1-3 upstream REST calls into one meaningful agent operation. The UI's fine-grained CRUD endpoints stay in `routes/research_content.py` unchanged.

### D2 — Async adapter around existing GatewaySessionManager

All existing MCP tools are sync. Rather than duplicating the async `GatewaySessionManager` as a sync class (which would drift), we create a thin sync adapter using `asyncio.run()`. This is safe because `nest_asyncio.apply()` is called at MCP server startup (`mcp_server.py:118`). The adapter wraps `get_token()` and `invalidate_token()` — zero duplication of consumer-key rotation, token extraction, or init error handling.

### D3 — Gateway helper in `services/research_gateway.py`

Thin sync client that:
- Wraps `GatewaySessionManager` for token management (async adapter)
- Uses `httpx.Client` (sync) for HTTP calls with proxy-matching timeouts
- Handles retry-on-401 with same logic as `routes/research_content.py`
- Injects `X-Research-User-Id` header
- Classifies upstream errors into `ActionError` subclasses

Reuses `default_http_client_factory` timeout values and `_parse_ssl_verify` for SSL config.

### D4 — Agent format via snapshot + flags

Same `{status, format, snapshot, flags}` shape as all other agent-format tools. Research file snapshot matches what `GET /files` actually returns (basic metadata). Richer snapshots (diligence state, handoff detail) come from dedicated tools, not inflated list responses.

### D5 — User resolution with explicit validation

Use `resolve_action_context()` from `actions/context.py`. If `ActionContext.user_id` is `None` after resolution, raise `ActionValidationError("Research tools require a resolved user_id")` immediately — don't pass `None` downstream.

### D6 — Error mapping (complete)

Upstream errors map to `ActionError` hierarchy with full coverage:

| Upstream condition | ActionError subclass |
|---|---|
| 401 + `session_expired` | Retry once → `ActionAuthError` |
| 401 + `auth_expired` | Invalidate + retry → `ActionAuthError` |
| 401 + `cross_user_reuse` | `ActionAuthError("Cross-user session reuse detected")` |
| Init → `credentials_unavailable` | `ActionAuthError("Gateway credentials unavailable")` |
| Init → `credentials_timeout` | `ActionInfrastructureError("Gateway credentials timeout")` |
| Init → `strict_mode_default_user` | `ActionAuthError("Strict mode requires explicit user identity")` |
| Upstream → `missing_user_id` | `ActionValidationError("User ID not provided to upstream")` |
| Upstream 404 | `ActionNotFoundError` |
| Upstream 422 | `ActionValidationError(upstream_detail)` |
| Upstream 5xx | `ActionInfrastructureError` |
| `httpx.HTTPError` | `ActionInfrastructureError` |
| Missing `GATEWAY_URL`/`GATEWAY_API_KEY` | `ActionInfrastructureError` |

MCP layer catches `ActionError` subclasses explicitly before `handle_mcp_errors` fallback, preserving diagnostic specificity:
```python
try:
    result = action_fn(...)
except ActionAuthError as e:
    return {"status": "error", "error": str(e), "auth_required": True}
except ActionNotFoundError as e:
    return {"status": "error", "error": str(e), "not_found": True}
except ActionValidationError as e:
    return {"status": "error", "error": str(e), "validation_error": True}
# ActionInfrastructureError falls through to @handle_mcp_errors
```

### D7 — `build_model` lives in `mcp_tools/research.py`

Upstream `POST /handoffs/{id}/build-model` already orchestrates `model_build()` + `annotate_model_with_research()`. The MCP tool wraps this endpoint.

**F33 relationship**: F33 says "Build Model should be agent-mediated, not direct orchestrator call." The MCP tool *partially* addresses F33 by putting the agent in the loop: the agent can check diligence completion (via `get_diligence_state`), look up company metadata via existing MCP tools (e.g., `fmp_profile` for fiscal year end), and make the build/no-build decision *before* calling `build_model`. The tool itself calls the same upstream orchestrator, but the agent's pre-build workflow is the "mediation" F33 asks for. Full F33 closure (agent-driven fiscal year resolution, assumption mapping within the build itself) requires upstream changes to accept agent-provided overrides — that remains deferred. Note: `get_diligence_state` exposes section completion status, not section contents (fiscal metadata lives in the artifact's `company` object, not the diligence state response).

### D8 — `send_research_message` DEFERRED

Research messages go through `POST /chat` via gateway streaming (SSE), not REST CRUD. The gateway persists messages via `ResearchRepository.save_message()` in runtime hooks before the first SSE byte. This is a fundamentally different transport than the REST proxy.

Agent-initiated research chat requires either:
- (a) A new upstream endpoint that accepts a message and returns the response synchronously (no SSE)
- (b) SSE consumption in the MCP tool (complex, no precedent in this codebase)

Deferred to a separate design. `read_research_thread` (read-only) is retained — agents can read what humans discussed.

### D9 — Registry uses wrapper functions, following income pattern

`agent/registry.py:_register()` calls `_unwrap()` which strips `@handle_mcp_errors`. If we register MCP-decorated functions, the agent surface gets raw unwrapped functions with no error handling.

Solution: define wrapper functions inside `agent/registry.py` that call `actions.research.*` functions, following the existing income pattern (`registry.py:826-847` defines `get_income_projection()` wrapper that calls `income_actions.get_income_projection_data()`). Each wrapper handles its own formatting. Register these wrappers via `_register()`.

### D10 — Excluded from MCP surface (with rationale)

| Endpoint | Why excluded |
|---|---|
| `PATCH /files/{id}` | Architecture doc: "user-driven only; agent never calls this" |
| `re-annotate` | Retry-only op, agent can call `build_model` again |
| `download` | Binary file download, not useful for MCP (returns bytes) |
| `export` | JSON export — agent already has structured data from other tools |
| `send_research_message` | Deferred (D8) — needs gateway SSE transport design |
| `list_threads` / `read_thread_by_id` | Scope reduction — `read_research_thread` covers explore/panel only. Arbitrary named analysis threads (e.g., `seed_message_ids` threads) not yet accessible. Add when agent needs to navigate non-standard threads. |

---

## Architecture

```
mcp_server.py
  └─ @mcp.tool() wrappers (thin, 5-10 lines each)
       └─ mcp_tools/research.py
            ├─ @handle_mcp_errors decorator (outer catch-all)
            ├─ Explicit ActionError subclass dispatch (inner, before fallback)
            ├─ Format selection (agent/summary)
            ├─ _build_research_snapshot() / _build_research_agent_response()
            └─ calls actions/research.py
                 ├─ ActionContext resolution (user_id validated non-None)
                 ├─ Business logic (composite gateway calls via private helpers)
                 └─ calls services/research_gateway.py
                      ├─ Async adapter: asyncio.run(GatewaySessionManager.get_token())
                      ├─ httpx.Client (sync, timeouts: connect=10, read=None, write=30, pool=30)
                      ├─ Retry-on-401 with error classification
                      └─ → GATEWAY_URL/api/research/{path}

core/research_flags.py
  └─ generate_research_flags(snapshot, context) -> list[dict]

agent/registry.py
  └─ Wrapper functions calling actions/research.py + _register() calls (income pattern)
```

---

## Gateway Helper — `services/research_gateway.py`

Sync adapter over existing async infrastructure. No duplication of auth logic.

### Public API

```python
class ResearchGatewayClient:
    """Sync client for upstream research API.

    Wraps GatewaySessionManager (async) via asyncio.run() adapter.
    Uses httpx.Client (sync) for HTTP calls.
    """

    def __init__(self):
        self._session_manager = GatewaySessionManager()
        self._lock = threading.Lock()

    def request(
        self,
        user_id: str,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        params: dict | None = None,
    ) -> dict | list | None:
        """
        Call upstream /api/research/{path}.

        Token lifecycle: async adapter around GatewaySessionManager.get_token().
        Retry: on 401/session_expired/auth_expired, invalidate + retry once.
        Error classification: maps upstream HTTP status + error codes to ActionError subclasses.

        Raises:
            ActionAuthError: 401 after retry, cross_user_reuse, credentials_unavailable
            ActionNotFoundError: upstream 404
            ActionValidationError: upstream 422
            ActionInfrastructureError: upstream 5xx, httpx errors, missing config
        """

    def _get_token_sync(self, user_id: str, *, force_refresh: bool = False) -> str:
        """Sync wrapper around async GatewaySessionManager.get_token().

        Creates a per-call httpx.AsyncClient for the token init POST only.
        The async client is closed within asyncio.run() scope.
        """
        async def _acquire():
            async with httpx.AsyncClient(
                verify=_parse_ssl_verify(os.getenv("GATEWAY_SSL_VERIFY", "")),
                timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0),
            ) as client:
                return await self._session_manager.get_token(
                    user_key=user_id,
                    client=client,
                    api_key_fn=lambda: os.getenv("GATEWAY_API_KEY", "").strip(),
                    gateway_url_fn=lambda: os.getenv("GATEWAY_URL", "").strip().rstrip("/"),
                    force_refresh=force_refresh,
                )
        return asyncio.run(_acquire())

    def _create_sync_client(self) -> httpx.Client:
        """Sync HTTP client with proxy-matching timeouts."""
        ssl_verify = _parse_ssl_verify(os.getenv("GATEWAY_SSL_VERIFY", ""))
        return httpx.Client(
            verify=ssl_verify,
            timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=30.0),
        )

# Module-level singleton
research_gateway = ResearchGatewayClient()
```

### Token lifecycle (delegated to GatewaySessionManager)

1. `_get_token_sync()` → `asyncio.run(session_manager.get_token())` — includes consumer-key rotation check
2. On 401 → `session_manager.invalidate_token()` + retry with `force_refresh=True`
3. On `session_expired`/`auth_expired` → same retry
4. On `cross_user_reuse` → raise `ActionAuthError` immediately (no retry — this is a security error)

### Error classification

```python
_KNOWN_UPSTREAM_ERRORS = frozenset({"auth_expired", "cross_user_reuse", "session_expired"})
_INIT_ERRORS = frozenset({"credentials_unavailable", "credentials_timeout", "strict_mode_default_user"})

def _get_token_sync(self, ...):
    """Token init can raise fastapi.HTTPException (not HTTP response).
    GatewaySessionManager raises HTTPException for init failures like
    credentials_unavailable, credentials_timeout, strict_mode_default_user.
    We catch HTTPException and map to ActionError subclasses."""
    try:
        return asyncio.run(self._acquire_token(...))
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
        error_code = detail.get("error", "")
        if error_code in ("credentials_unavailable", "strict_mode_default_user"):
            raise ActionAuthError(f"Gateway init failed: {error_code}") from exc
        raise ActionInfrastructureError(f"Gateway init failed: {error_code}") from exc

def _classify_and_raise(self, response: httpx.Response, path: str) -> None:
    status = response.status_code
    try:
        body = response.json()
    except Exception:
        body = None

    if status == 404:
        raise ActionNotFoundError(f"Research resource not found: {path}")
    if status == 422:
        detail = body.get("detail", str(body)) if isinstance(body, dict) else str(body)
        raise ActionValidationError(detail)
    if status >= 500:
        raise ActionInfrastructureError(f"Research upstream error: {status}")
    if status == 401:
        error_code = body.get("error") if isinstance(body, dict) else None
        if error_code == "cross_user_reuse":
            raise ActionAuthError("Cross-user session reuse detected")
        # Other 401s handled by retry logic in request()
```

### Async vs sync client split

- **Token init**: `_get_token_sync()` creates a per-call `httpx.AsyncClient` inside `asyncio.run()`, used only for the `/api/chat/init` POST via `GatewaySessionManager.get_token()`. Closed within the `async with` scope.
- **Research API calls**: `_create_sync_client()` returns an `httpx.Client` (sync) for all `GET/POST/PATCH/DELETE /api/research/*` calls.

---

## Tool Definitions — 15 Tools

### Tool 1: `list_research_files`

List all active research theses for the current user.

```python
def list_research_files(
    user_email: Optional[str] = None,
    format: Literal["summary", "agent"] = "agent",
) -> dict:
```

**Upstream**: `GET /files`
**Snapshot** (per file): `{id, ticker, label, company_name, stage, conviction, direction, strategy, created_at, updated_at}` — `stage` is `exploring|has_thesis|diligence|decision|monitoring|closed`, `conviction` is `int 1..5`
**Flags**: `no_research_files` (info), `multiple_active` (info, >3 files)

*Note: Snapshot matches upstream response fields. No derived counts — use `get_diligence_state` per-file for richer detail.*

### Tool 2: `start_research`

Start a new research thesis on a ticker. Composite: upserts file + creates explore thread.

```python
def start_research(
    ticker: str,
    label: Optional[str] = None,
    user_email: Optional[str] = None,
    format: Literal["summary", "agent"] = "agent",
) -> dict:
```

**Upstream**: `POST /files {ticker, label}` → `POST /threads {research_file_id, is_explore: true}` + `POST /threads {research_file_id, is_panel: true}` (parallel, matches frontend bootstrap invariant)
**Snapshot**: file metadata from upsert response + `explore_thread_id` + `panel_thread_id`
**Flags**: `research_started` (success), `existing_file_reused` (info)

### Tool 3: `read_research_thread`

Read conversation history from a research thread.

```python
def read_research_thread(
    research_file_id: int,
    thread_type: Literal["explore", "panel"] = "explore",
    limit: int = 20,
    user_email: Optional[str] = None,
) -> dict:
```

**Upstream**: `GET /threads?research_file_id=...` (find thread by type) → `GET /messages?thread_id=...&research_file_id=...&limit=...`
**Returns**: `{status, thread_id, thread_name, messages: [{role, content, content_type, created_at}]}`

### Tool 4: `load_document`

Load a filing or earnings transcript. Supports section filtering.

```python
def load_document(
    source_id: str,
    source_type: Literal["filing", "transcript"] = "filing",
    section: Optional[str] = None,
    user_email: Optional[str] = None,
) -> dict:
```

**Upstream**: `GET /documents?source_id=...&source_type=...`
**Returns**: Full document if `section` is None. If `section` provided, returns only that section's `{text, start, end}` from the sections dict. Transcripts also include `segments` filtered to the section.
**Note**: Section filtering is client-side (upstream returns full doc). Keeps the upstream call simple.

### Tool 5: `ingest_document`

Ingest a new filing or transcript into the research workspace.

```python
def ingest_document(
    source_path: str,
    user_email: Optional[str] = None,
) -> dict:
```

**Upstream**: `POST /documents/ingest {source_path}`
**Returns**: `{status, filing_id}` (content-hashed, idempotent)

### Tool 6: `create_annotation`

Annotate a section of a filing or transcript with a research note.

```python
def create_annotation(
    research_file_id: int,
    source_id: str,
    section_header: str,
    char_start: int,
    char_end: int,
    selected_text: str,
    note: str,
    source_type: Literal["filing", "transcript"] = "filing",
    author: Literal["user", "agent"] = "agent",
    diligence_ref: Optional[str] = None,
    user_email: Optional[str] = None,
) -> dict:
```

**Upstream**: `POST /annotations` — `author` field is in the DB schema (`annotations.author TEXT NOT NULL`); the upstream REST body accepts it (pass-through to `save_annotation()`). Architecture doc's endpoint listing omits it but the Phase 2 plan and schema include it.
**Returns**: `{status, annotation_id}`

### Tool 7: `get_diligence_state`

Get current diligence progress for a research file. Pure read — does not activate diligence.

```python
def get_diligence_state(
    research_file_id: int,
    user_email: Optional[str] = None,
    format: Literal["summary", "agent"] = "agent",
) -> dict:
```

**Upstream**: `GET /diligence/state?research_file_id=...`
**Snapshot**: `{research_file_id, ticker, handoff_id, total_sections, completed_sections, completion_pct, sections: [{key, label, status, has_evidence, source_ref_count}], qualitative_factors: [{id, category, label, assessment, rating}]}`
**Flags**: `diligence_not_activated` (info, no handoff exists yet — use `activate_diligence`), `diligence_not_started` (info), `diligence_incomplete` (warning), `diligence_confirmed` (success), `missing_qualitative_factors` (info), `ready_for_handoff` (success)
**Note**: Pure read. If diligence is not yet activated, returns `{status: "success", diligence_active: false}` with a `diligence_not_activated` flag. Does NOT auto-activate — use `activate_diligence` (Tool 15) for that.

### Tool 8: `update_diligence_section`

Update a single diligence section.

```python
def update_diligence_section(
    research_file_id: int,
    section_key: str,
    section_data: Optional[dict] = None,
    completion_state: Optional[str] = None,
    source_refs: Optional[list[dict]] = None,  # structured provenance: [{source_id, section_header, char_start, char_end, text, annotation_id?}]
    user_email: Optional[str] = None,
) -> dict:
```

**Upstream**: `GET /diligence/state` (get `handoff_id`) → `PATCH /diligence/sections/{section_key} {handoff_id, section_data, completion_state, source_refs}`
**Returns**: `{status, section_key, handoff_id}`

*Private helper `_get_handoff_id(research_file_id)` shared with other diligence tools — not a public tool call.*

### Tool 9: `manage_qualitative_factor`

Add, update, or remove a qualitative factor.

```python
def manage_qualitative_factor(
    research_file_id: int,
    action: Literal["add", "update", "remove"],
    factor_data: Optional[dict] = None,
    factor_id: Optional[int] = None,
    user_email: Optional[str] = None,
) -> dict:
```

**Upstream** (add): `GET /diligence/state` → `POST /diligence/factors {handoff_id, factor}`
**Upstream** (update): `GET /diligence/state` → `PATCH /diligence/factors/{factor_id} {handoff_id, updates}`
**Upstream** (remove): `GET /diligence/state` → `DELETE /diligence/factors/{factor_id}?handoff_id=...`
**Returns**: `{status, action, factor_id}`
**Validation**: `add` requires `factor_data`; `update` requires both `factor_id` + `factor_data`; `remove` requires `factor_id`.

### Tool 10: `prepopulate_diligence`

Trigger server-side pre-population of diligence sections.

```python
def prepopulate_diligence(
    research_file_id: int,
    sections: Optional[list[str]] = None,
    user_email: Optional[str] = None,
) -> dict:
```

**Upstream**: `POST /diligence/prepopulate {research_file_id, sections}`
**Returns**: `{status, sections_updated: [keys], sections_skipped: [keys]}`
**Note**: Long-running (10-30s). Timeout policy: `read=None` ensures no premature cutoff.

### Tool 11: `finalize_handoff`

Finalize the research handoff artifact. Locks diligence sections, produces summary.

```python
def finalize_handoff(
    research_file_id: int,
    user_email: Optional[str] = None,
    format: Literal["summary", "agent"] = "agent",
) -> dict:
```

**Upstream**: `POST /handoffs/finalize {research_file_id}`
**Snapshot**: `{handoff_id, version, ticker, status, artifact_summary}` — passed through from upstream response
**Flags**: `handoff_finalized` (success)
**Note**: Agents should call `get_diligence_state` before finalizing to check section completion. The finalize response passes through `artifact_summary` from upstream — flag derivation from its contents is deferred to implementation (requires verifying `artifact_summary` includes `metadata.diligence_completion`). If upstream returns an error (e.g., no draft to finalize), it surfaces as `ActionValidationError`.

### Tool 12: `get_handoff`

Inspect a handoff artifact or list handoff versions for a research file.

```python
def get_handoff(
    research_file_id: int,
    handoff_id: Optional[int] = None,
    user_email: Optional[str] = None,
) -> dict:
```

**Upstream**: If `handoff_id` provided: `GET /handoffs/{handoff_id}` (returns full artifact row per Decision 2A schema). Otherwise: `GET /handoffs?research_file_id=...` (list version summaries).
**Returns**: Single mode: full artifact including `company`, `thesis`, `assumptions`, `qualitative_factors`, `sources`, `metadata.diligence_completion`, etc. (Decision 2A). List mode: version summaries `[{handoff_id, version, ticker, status, artifact_summary}]`.
**Note**: Single mode lets the agent inspect all build inputs (fiscal metadata, assumptions, sources) before calling `build_model`. This is key to the F33 agent-mediation workflow.

### Tool 13: `new_handoff_version`

Create a new draft from a finalized handoff for iteration.

```python
def new_handoff_version(
    research_file_id: int,
    user_email: Optional[str] = None,
) -> dict:
```

**Upstream**: `POST /handoffs/new-version {research_file_id}`
**Returns**: upstream response passed through: `{handoff_id, version, ticker, status, artifact_summary}` wrapped in `{status: "success", ...}`
**Note**: Required for lifecycle iteration. Without this, agent can't update research after first finalization.

### Tool 14: `build_model`

Trigger orchestrated model build from finalized handoff.

```python
def build_model(
    research_file_id: int,
    user_email: Optional[str] = None,
) -> dict:
```

**Upstream**: `GET /handoffs?research_file_id=...` (find finalized handoff) → `POST /handoffs/{handoff_id}/build-model`
**Returns**: `{status, model_path, handoff_id, build_status, annotation_status}`
**Flags**: `model_built` (success), `annotation_failed` (warning), `build_failed` (error), `no_finalized_handoff` (error)
**Note**: Long-running (30-120s). `read=None` timeout ensures completion. Partially addresses F33 — agent workflow before calling this tool provides the "mediation" layer.

### Tool 15: `activate_diligence`

Activate the diligence workflow for a research file. Creates a draft handoff if none exists.

```python
def activate_diligence(
    research_file_id: int,
    user_email: Optional[str] = None,
) -> dict:
```

**Upstream**: `POST /diligence/activate {research_file_id}`
**Returns**: `{status, handoff_id, research_file_id}`
**Note**: Idempotent — if diligence already active, returns existing handoff_id.

---

## Agent Format Schemas

### Research File Snapshot (matches upstream `GET /files`)

```python
{
    "id": int,
    "ticker": str,
    "label": str,
    "company_name": str | None,
    "stage": str,           # exploring | has_thesis | diligence | decision | monitoring | closed
    "conviction": int | None,  # 1..5 (integer scale per Decision 1 schema)
    "direction": str | None,
    "strategy": str | None,
    "created_at": str,
    "updated_at": str,
}
```

### Diligence Snapshot (from `GET /diligence/state`)

```python
{
    "research_file_id": int,
    "ticker": str,
    "diligence_active": bool,    # false if no handoff exists
    "handoff_id": int | None,    # None when diligence_active is false
    "total_sections": int,       # 0 when inactive
    "completed_sections": int,   # sections with status "confirmed"; 0 when inactive
    "completion_pct": float,     # 0.0 when inactive
    "sections": [                # empty list when inactive
        {
            "key": str,
            "label": str,
            "status": str,      # empty | draft | confirmed
            "has_evidence": bool,
            "source_ref_count": int,
        }
    ],
    "qualitative_factors": [     # matches Decision 2A factor entry shape; empty list when inactive
        {
            "id": int,
            "category": str,     # free-form string (NOT enum)
            "label": str,        # human-readable display name
            "assessment": str | None,   # narrative markdown
            "rating": str | None,       # high | medium | low | null
        }
    ],
}
```

*Note: Factor `data` and `source_refs` fields from Decision 2A are omitted from the snapshot for compactness. Full factor detail available via `GET /diligence/state` response directly.*

### Handoff Snapshot (from `POST /handoffs/finalize` or `POST /handoffs/new-version`)

Matches upstream response shape: `{handoff_id, version, ticker, status, artifact_summary}`.

```python
{
    "handoff_id": int,          # integer PK from research_handoffs table
    "version": int,
    "ticker": str,
    "status": str,              # draft | finalized | superseded (upstream field name, not renamed)
    "artifact_summary": dict,   # upstream-defined summary of the research artifact
}
```

*Note: `artifact_summary` is passed through from upstream. The full artifact schema (Decision 2A, ARCHITECTURE_DECISIONS.md:285-383) defines `metadata.diligence_completion` as `{section_key: "empty"|"draft"|"confirmed"}` — this is the source for `unconfirmed_sections_at_finalize` flag derivation. Other artifact fields (company, thesis, business_overview, catalysts, risks, valuation, assumptions, qualitative_factors, sources) are part of the same locked schema.*

---

## Flag Definitions — `core/research_flags.py`

```python
def generate_research_flags(snapshot: dict, context: str = "file") -> list[dict]:
    """
    Generate interpretive flags for research workspace operations.
    context: "file" | "diligence" | "handoff" | "build"
    """
```

### File-level flags
| Flag | Severity | Condition |
|------|----------|-----------|
| `no_research_files` | info | Empty file list |
| `multiple_active` | info | >3 active research files |
| `research_started` | success | New file created |
| `existing_file_reused` | info | Upsert matched existing file |

### Diligence flags
| Flag | Severity | Condition |
|------|----------|-----------|
| `diligence_not_started` | info | All sections empty |
| `diligence_incomplete` | warning | Some sections empty/draft |
| `diligence_confirmed` | success | All sections confirmed |
| `missing_qualitative_factors` | info | No qualitative factors added |
| `ready_for_handoff` | success | All sections confirmed (no minimum factor count per Decision 4) |

### Handoff flags
| Flag | Severity | Condition |
|------|----------|-----------|
| `handoff_finalized` | success | Finalize succeeded |

### Build flags
| Flag | Severity | Condition |
|------|----------|-----------|
| `no_finalized_handoff` | error | build_model called with no finalized handoff |
| `model_built` | success | Build + annotate succeeded |
| `annotation_failed` | warning | Build ok, annotate failed |
| `build_failed` | error | Build failed |

---

## Files to Create / Touch

### New files (5)

| File | Lines (est.) | Purpose |
|------|-------------|---------|
| `services/research_gateway.py` | ~150 | Sync adapter wrapping async GatewaySessionManager + httpx.Client |
| `actions/research.py` | ~450 | Action layer — 15 functions + private helpers (`_get_handoff_id`, `_find_thread_by_type`) |
| `mcp_tools/research.py` | ~450 | MCP tool layer — explicit ActionError dispatch, format selection, snapshots |
| `core/research_flags.py` | ~120 | Flag generation (file/diligence/handoff/build contexts) |
| `tests/test_research_mcp.py` | ~500 | Unit tests for all layers + integration tests for gateway |

### Modified files (2)

| File | Change |
|------|--------|
| `mcp_server.py` | Import + 15 `@mcp.tool()` wrappers (~120 lines) |
| `agent/registry.py` | 15 wrapper functions (following income pattern at lines 826-847) + `_register()` calls (~240 lines) |

---

## Phased Implementation

### Phase A — Gateway + Read-Side (tools 1, 3, 4, 7, 12)

**Scope**: `services/research_gateway.py` (complete), `actions/research.py` (read functions + `_get_handoff_id` helper), `mcp_tools/research.py` (read tools), `core/research_flags.py`, `mcp_server.py` (5 wrappers), `agent/registry.py` (5 registrations)

**Tools**: `list_research_files`, `read_research_thread`, `load_document`, `get_diligence_state`, `get_handoff`

**Why first**: Read-only. Validates gateway client, async adapter, error mapping, and agent format pattern end-to-end. No state mutations.

**Tests**: Gateway client (mock httpx + mock GatewaySessionManager), action layer (mock gateway), MCP layer (mock actions with explicit ActionError subclass tests), flags (pure unit).

**Gate**: All unit tests pass. Manual smoke test against live upstream if available.

### Phase B — Write-Side + Ingest (tools 2, 5, 6, 8, 9, 10, 15)

**Scope**: Extend `actions/research.py`, `mcp_tools/research.py`, `mcp_server.py`, `agent/registry.py`

**Tools**: `start_research`, `ingest_document`, `create_annotation`, `update_diligence_section`, `manage_qualitative_factor`, `prepopulate_diligence`, `activate_diligence`

**Why second**: Write ops use the gateway client validated in Phase A. Actions call gateway helpers directly — no dependency on public read tools.

**Tests**: Each write tool with mock gateway responses, including error paths (422, 404, 401-retry, `cross_user_reuse`).

**Gate**: All unit tests pass. **Integration test required**: at least one write tool (e.g., `start_research`) tested against live upstream to validate request/response contract.

### Phase C — Handoff + Build (tools 11, 13, 14)

**Scope**: Extend same files

**Tools**: `finalize_handoff`, `new_handoff_version`, `build_model`


**Why last**: Terminal pipeline ops. `build_model` is the longest-running call and partially addresses F33 (agent-mediated build).

**Tests**: Handoff finalize (happy + incomplete sections warning). New version (happy + no finalized handoff error). Build model (happy + annotation failure + no handoff error + timeout verification).

**Gate**: All tests pass. F33 partially addressed (agent can mediate build decisions; full closure needs upstream override support).

---

## Test Strategy

- **Gateway client** (`services/research_gateway.py`): Mock `httpx.Client` responses + mock `GatewaySessionManager`. Test: token acquisition, 401 retry, `session_expired` retry, `cross_user_reuse` → immediate `ActionAuthError`, `credentials_unavailable` → `ActionAuthError`, 404 → `ActionNotFoundError`, 422 → `ActionValidationError`, 5xx → `ActionInfrastructureError`, `httpx.HTTPError` → `ActionInfrastructureError`, missing env vars → `ActionInfrastructureError`.
- **Action layer** (`actions/research.py`): Mock `research_gateway.request()`. Test: composite logic (e.g., `start_research` creates file then thread), `_get_handoff_id` helper, `_find_thread_by_type` helper, `user_id=None` → `ActionValidationError`, each action's happy path + error paths.
- **MCP layer** (`mcp_tools/research.py`): Mock action functions. Test: explicit `ActionError` subclass dispatch (auth → `auth_required`, not_found → `not_found`, validation → `validation_error`), format selection, snapshot building.
- **Flags** (`core/research_flags.py`): Pure unit tests on snapshot dicts — no mocks. All conditions in flag tables above.
- **Integration** (Phase B gate): At least one end-to-end test against live upstream gateway. Validates request/response contract is correct.

Target: ~75 tests across all layers.

---

## Deferred Work

| Item | Why deferred | Prerequisite |
|------|-------------|--------------|
| `send_research_message` | Requires gateway SSE streaming transport, not REST | Upstream design: sync message endpoint or SSE adapter |
| `list_threads` / `read_thread_by_id` | Scope reduction: `read_research_thread` covers explore/panel only. Arbitrary named threads (e.g., `seed_message_ids` threads) not yet accessible | Phase A complete, agent use case identified |
| `opening_take` | Server-side synthesis op, lower priority than core pipeline | Phase B complete |
| `list_annotations` | Read-only, can add when agents need annotation review | Phase A complete |
| `extractions` (langextract) | Structured extraction from filings, Phase 2 upstream feature | Upstream Phase 2 shipped |

---

## References

- `routes/research_content.py` — existing async proxy (pattern source, URL prefix stripping: `/api/research/content/` → `/api/research/`)
- `app_platform/gateway/session.py` — `GatewaySessionManager` (async, wrapping target)
- `app_platform/gateway/proxy.py` — `_parse_ssl_verify`, `default_http_client_factory` (timeout values)
- `mcp_tools/income.py` → `actions/income_projection.py` → `core/income_projection_flags.py` — canonical tool pattern
- `actions/context.py` — `ActionContext` + `resolve_action_context()`
- `actions/errors.py` — `ActionError` hierarchy
- `mcp_tools/common.py` — `handle_mcp_errors` decorator
- `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE.md` — topology, REST surface, invariants
- `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md` — 7 locked decisions
- F33 (TODO.md) — Build Model agent mediation (partially addressed by tool 14 — agent-mediated workflow, not full override support)
