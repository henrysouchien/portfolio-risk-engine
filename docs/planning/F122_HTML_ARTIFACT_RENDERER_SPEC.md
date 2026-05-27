# F122 — Hank Web HTML Artifact Renderer Spec

_Authored: 2026-05-22 | revised: 2026-05-22 (rounds 1–6 Codex CONCERNS → addressed) | status: **CODEX PASS round 7 (2026-05-22) — READY FOR IMPL PLAN** | scope: the Hank web (risk_module frontend) renderer-side consumer of the `HtmlArtifact` typed contract defined in AI-excel-addin's `docs/design/demo-surface-html-artifact-addendum.md` (CODEX PASS round 6, 2026-05-20)._

> **Workflow next steps** per CLAUDE.md plan-first workflow: (1) ✅ spec → CODEX PASS round 7, (2) impl plan written (next — separately authored), (3) impl plan → CODEX PASS, (4) impl via Codex. **Not v1 demo critical-path** — picks up after parent spec PR 7-b + PR 8 ship (both shipped 2026-05-20). **Blocked-on-foundation**: F122 impl can develop against mocks in parallel, but cannot live-test until AI-excel-addin's foundation-layer impl ships (`HtmlArtifact` contract + `emit_html_artifact` tool + `/api/html-artifacts/*` endpoints + `ticker: str | None` widening + `event_from_dict` null-fix).

> **F122 is upstream of a second consumer surface — analyst-view extension** (filed 2026-05-23, CODEX PASS round 3). Hank web has TWO chat surfaces: (a) the **research workspace** (`useResearchChat`, multi-tab — what THIS spec covers) and (b) the **Portfolio Analyst chat** (`ChatInterface` / `usePortfolioChat` → existing `ArtifactPanel` slide-over for `:::artifact` blocks). The analyst-view extension is specced at `AI-excel-addin/docs/design/f122-analyst-view-extension-spec.md` as a **delta-spec** that explicitly defers to THIS spec for all shared infra (contract, proxy router `routes/html_artifacts_proxy.py`, `sign_user_claim_headers` helper, hooks, sandbox, CSP, SSE chunk type, exports) and adds ONLY analyst-view-specific bits: register `html-artifact` block into the existing `:::artifact` block-registry pipeline so `ArtifactPanel` renders it + inline chip in `ChatCore.tsx` analyst-path (not workspace tab). **Implication for THIS spec's impl plan**: the deliverables in §11 lock #4 (proxy router) + §11 lock #21 (`sign_user_claim_headers`) + §3 components (`buildSandboxedDocument` + `StaticExportsBar`) + §4 hooks (`useHtmlArtifact`, `requestText`) + §5 SSE chain extension are **shared infra two surfaces will consume** — don't scope them as research-workspace-private. The analyst-view extension impl plan is PARKED until this spec's impl plan ships those deliverables; ~1 small PR (~250-400 LOC) after. **A prior parallel-session F122 spec + impl plan at `AI-excel-addin/docs/design/f122-html-artifact-renderer-spec.md` and `…-impl-plan.md` are SUPERSEDED 2026-05-23** — had load-bearing architectural errors (wrong auth model, wrong proxy structure, missing `key={id}` re-mount) because they were drafted without surveying `risk_module/docs/planning/` first. Meta-lesson captured in `feedback_survey_target_frontend_before_spec.md`. Use the delta-spec for the analyst-view side, not the superseded twin specs.

> **Round 5 → Round 6 deltas.** Round 5 Codex CONCERNS identified 0 blockers + 3 non-blocking text-sweep items: (1) lock #16 still said `utils/agent_claim.sign_user_claim` (nonexistent) → updated to `sign_user_claim_headers` with cross-reference to lock #21; (2) §12 still had stale "CI parity check" language in three spots ("sync is enforced by a CI parity check", "Two tests + a CI parity check", "CI parity check catches missed paired updates") → all rewritten to reflect PR-time manual sync; (3) §2.3 helper sketch `sign()` kwarg order didn't mirror shipped — reordered to `hmac_key, audience, issued_at, expiry, user_id, user_email, nonce` matching `utils/agent_claim.py:37` (not runtime-breaking since all keyword-only, but improves auditability). **Round-5 confirmations**: audience is `agent_api_v1`; §8/PR-plan clean of stale `gateway_proxy.py` extension instructions; lock #17 is correctly a merge placeholder, lock #12 canonical; `ts` is seconds from `time.time()`. No major missing spec coverage. **Round 6 expected verdict**: PASS.

> **Round 4 → Round 5 deltas.** Round 4 Codex CONCERNS identified 1 blocking + 4 non-blocking + 3 confirmations of round-3 alignment: (1) `sign_user_claim_headers` helper sketch was wrong — `sign()` returns a hex signature string (not dict), needs `issued_at`/`expiry`/`nonce` as inputs, and audience default should be `agent_api_v1` (not `agent-api`). Fully rewritten with correct `sign()` signature. (2) §8 sequencing + PR plan still said "extend `routes/gateway_proxy.py`" — contradicts §11 lock #4 which locks dedicated new router. Swept to consistent language. (3) Lock #17 was a duplicate of lock #12 SSE chain enumeration — merged. Codex confirmed no 6th parser/state-machine layer exists (parseSSE, GatewayStreamController, ResearchStreamContext are all pass-through). (4) §12 parity-fixture "CI cross-repo parity check runs in both repos" was aspirational — neither repo has the workflow today. Downgraded to PR-time manual sync + per-repo parity test + human-enforced diff at PR review. Aspirational CI noted as v2. (5) `ts` unit mislabeled as "epoch milliseconds" — shipped emitters use `time.time()` which returns seconds. Fixed. **Confirmations**: CSP no-telemetry aligned across §7/§9/§11/§12; reload recovery is consistently Workbench-only; 60/120 rate limit defaults reasonable. **All 5 findings resolved.**

> **Round 3 → Round 4 deltas (preserved for traceability).** Round 3 Codex CONCERNS identified 3 blocking + 2 non-blocking + 3 confirmations of round-2 fixes verified correct: (1) `sign_user_claim(user_id, user_email, ttl_seconds=600)` doesn't exist in risk_module — `utils/agent_claim.py` only has `sign(hmac_key, ...)` + `verify(...)`. The function I named lives in AI-excel-addin's `_agent_claim.py` but returns `AGENT_API_CLAIM_*` env-var keys for subprocess injection, NOT `X-Agent-Claim-*` HTTP headers.

> **Round 3 → Round 4 deltas.** Round 3 Codex CONCERNS identified 3 blocking + 2 non-blocking + 3 confirmations of round-2 fixes verified correct: (1) `sign_user_claim(user_id, user_email, ttl_seconds=600)` doesn't exist in risk_module — `utils/agent_claim.py` only has `sign(hmac_key, ...)` + `verify(...)`. The function I named lives in AI-excel-addin's `_agent_claim.py` but returns `AGENT_API_CLAIM_*` env-var keys for subprocess injection, NOT `X-Agent-Claim-*` HTTP headers. F122 must add a new helper that wraps the existing `sign()` primitive and produces header-keyed output. (2) `ticker: str | None` is NOT yet shipped on `ArtifactReadyEvent` — it's a foundation-layer impl deliverable. Also: shipped `event_from_dict` coerces `str(payload["ticker"])` which would round-trip null as string `"None"`. F122 has an explicit dependency on the foundation-layer impl landing both the type widening AND the null-preservation fix BEFORE F122 can ship. (3) Stale locked/open sections survived from earlier rounds — §11 still says "four layers" SSE, §9 still mentions CSP "violation reporting for telemetry", §12 opens still asks about reporting target + reload restoration. Sweep needed. Non-blocking: (4) §1 chip-on-persisted-messages claim contradicts §5.4's client-side-session-only lock — recovery is via Workbench only. (5) Proxy observability + rate limiting underspecified — new router doesn't inherit existing `gateway_proxy.py` logging; add per-user rate limit + structured logging fields. **Confirmations**: `parseClaudeStreamChunk` discriminator is real; `APIService.requestRaw` + `throwOnHttpError=false` confirmed; parity-fixture mechanics acceptable for v1. **All 5 findings resolved in this revision** — see §2.3 (new `sign_user_claim_headers` helper specified, wraps existing `sign()` primitive), §5.2 (explicit foundation-layer-impl dependency stated), §11 + §12 + §9 (sweep applied — "five layers" everywhere, CSP-reporting language removed, opens scrubbed), §1 (chip-on-persisted-messages claim removed), §2.5 (proxy observability + rate limit added).

> **Round 2 → Round 3 deltas (preserved for traceability).** Round 2 Codex CONCERNS identified 5 blocking + 2 non-blocking + 3 confirmations: signed-claim path was hand-waved as "reuse chat helpers" but those don't exist at the gateway proxy — the gateway artifact API actually requires `X-Agent-Claim-*` headers verified by `_verify_signed_user_claim`, distinct from chat's session-token+Bearer mechanism.

> **Round 2 → Round 3 deltas.** Round 2 Codex CONCERNS identified 5 blocking + 2 non-blocking + 3 confirmations: (1) signed-claim path was hand-waved as "reuse chat helpers" but those don't exist at the gateway proxy — the gateway artifact API actually requires `X-Agent-Claim-*` headers verified by `_verify_signed_user_claim`, distinct from chat's session-token+Bearer mechanism. F122 must use `utils/agent_claim.sign_user_claim` + `AGENT_API_USER_CLAIM_HMAC_KEY`. (2) Missed a 5th SSE layer — `parseClaudeStreamChunk` + `ParsedChatStreamEvent` in `chatStreamPayloads.ts:310` returns `ignored` for unknown types; must add `artifact_ready` to the parser too. (3) Event shape in §5.2 was wrong — used `run_id`, but shipped `ArtifactReadyEvent.events.py:49` carries `skill_run_id`, `data_source`, numeric `ts`. (4) `requestText` proposal didn't address non-2xx handling — `requestRaw` returns failed responses as data (no throw); naive `.text()` would render error bodies; must wrap with explicit status check. (5) Tab reload persistence claim was false — `researchStore` persists via devtools only; `hydrate` clears `documentTabs`. Drop reload restoration from v1; user recovers via Workbench list. Non-blocking: (6) fixture mechanics for cross-repo parity test under-specified — pin canonical fixture to AI-excel-addin source-of-truth, vendor a synced copy to risk_module with CI parity check. (7) Optimistic `ResearchMessageMetadata.htmlArtifacts` would be overwritten by `fetchResearchMessages` reconciliation — accept client-side-session-only metadata for v1; no server persistence; reload recovers via Workbench. **Confirmations preserved**: dedicated `/api/html-artifacts` router namespace mounts cleanly; `ResearchWorkspace` artifact branch is structurally clean; CSP no-telemetry trade-off is correct (per MDN: meta-tag CSP supports neither `report-uri` nor `Content-Security-Policy-Report-Only`). **All 7 findings resolved in this revision** — see §2.3 (signed-claim path named), §5 (5-layer extension), §5.2 (correct event shape), §4 (requestText with non-2xx handling), §1.2 (reload-restoration dropped + Workbench-recovery path), §12 (fixture mechanics), §5.4 (client-side-only metadata).

> **Round 1 → Round 2 deltas (preserved for traceability).** Round 1 Codex CONCERNS identified seven blocking + three non-blocking wiring gaps where the spec made wrong claims about shipped code: (1) `create_gateway_router` only proxies `/chat` and `/tool-approval`, not arbitrary paths — need explicit GET handlers + clarify mount path; (2) `GatewayService.mapEvent` returns `null` for unknown events; `useResearchChat` doesn't see `artifact_ready` today — need to extend `mapEvent` + `ClaudeStreamChunk` types + chat hook; (3) widening `ResearchTab.type` alone isn't enough — `ResearchWorkspace.tsx` falls through unknown non-document tabs to ThreadTab; need explicit `'artifact'` dispatch branch; (4) `requestJson` is local to hook files, NOT exported from `@risk/connectors`; `APIService.request` always JSON-parses — need `requestRaw().text()` or new exported `requestText`; (5) browser-side `SecurityPolicyViolationEvent` capture is unimplementable inside a sandboxed iframe without `allow-same-origin` — drop, no v1 CSP telemetry; (6) addendum §7 mentioned CSP report-only as a rollout option; F122 originally locked enforcing day one — reconcile to enforcing day one with no telemetry (security posture wins, telemetry too costly); (7) cross-repo TS schema sync missing.

> **Round 1 → Round 2 deltas.** Round 1 Codex CONCERNS identified seven blocking + three non-blocking wiring gaps where the spec made wrong claims about shipped code: (1) `create_gateway_router` only proxies `/chat` and `/tool-approval`, not arbitrary paths — need explicit GET handlers + clarify mount path; (2) `GatewayService.mapEvent` returns `null` for unknown events; `useResearchChat` doesn't see `artifact_ready` today — need to extend `mapEvent` + `ClaudeStreamChunk` types + chat hook; (3) widening `ResearchTab.type` alone isn't enough — `ResearchWorkspace.tsx` falls through unknown non-document tabs to ThreadTab; need explicit `'artifact'` dispatch branch; (4) `requestJson` is local to hook files, NOT exported from `@risk/connectors`; `APIService.request` always JSON-parses — need `requestRaw().text()` or new exported `requestText`; (5) browser-side `SecurityPolicyViolationEvent` capture is unimplementable inside a sandboxed iframe without `allow-same-origin` — drop, no v1 CSP telemetry; (6) addendum §7 mentioned CSP report-only as a rollout option; F122 originally locked enforcing day one — reconcile to enforcing day one with no telemetry (security posture wins, telemetry too costly); (7) cross-repo TS schema sync missing — Python contract in AI-excel-addin, TS types needed in `risk_module`; pick hand-mirrored + parity test. Non-blocking: (8) `ResearchMessageMetadata.htmlArtifacts` shape needs defining + optimistic-vs-persisted reconciliation; (9) anti-pattern test broadens beyond just no-`message`-listener; (10) UI state coverage gaps (loading/error/empty/retry/a11y/responsive). **All 10 findings resolved in this revision** — see §2 (gateway proxy rewrite with explicit handlers + mount path), §5 (SSE event pipeline chain enumerated), §1 (`ResearchWorkspace` dispatch branch), §4 (`requestText` choice), §7 (CSP telemetry dropped, enforcing-day-one preserved), §11+§12 (TS schema sync strategy locked), §1.1 + §3 (`ResearchMessageMetadata` extension + reconciliation), §6 (anti-pattern test broadened), §3 / §11 (UI state coverage enumerated).

> **Companion spec.** This is the **PRIMARY v1 renderer surface** per Henry decision 2026-05-22 (was originally "companion" to a taskpane Workbench pane; taskpane deferred indefinitely). The foundation layer (Pydantic contract, `emit_html_artifact` tool, `_html/` flat storage, `/api/html-artifacts/*` gateway endpoints, sandbox model, CSP, static export bridges) is surface-independent and ships from AI-excel-addin. This spec covers ONLY the renderer-side concerns: where in Hank web the artifact surfaces, how Hank web fetches it (gateway proxy extension), React-flavored sandboxed iframe rendering, and the F122-specific decisions deferred from the addendum.
>
> **Workflow position.** Per `CLAUDE.md`: spec → Codex review → impl plan → impl via Codex. This is round-1 draft. Expecting 2-4 rounds based on the addendum's iteration (which was 6 rounds, but most of those rounds were architectural pivots; this spec inherits the locked architecture).
>
> **Non-goals.** Does NOT respec the foundation layer (already locked in addendum). Does NOT define the contract, tool, storage, endpoints, CSP, or sandbox model (those are addendum §2–6). Does NOT cover the AI-excel-addin foundation-layer impl plan (separately tracked). Does NOT change `MarkdownRenderer.tsx` or any existing renderer.

---

## 1. Where in Hank UI does the renderer surface?

**Decision: new research-workspace tab type `'artifact'`** (locked, see §11).

Hank's research workspace already has a typed tab system at `frontend/packages/connectors/src/stores/researchStore.ts:83`:

```ts
export interface ResearchTab {
  id: string;
  type: 'explore' | 'thread' | 'document' | 'diligence' | 'handoff';
  // ...
}
```

The natural fit for HTML artifacts is a sixth type:

```ts
export interface ResearchTab {
  id: string;
  type: 'explore' | 'thread' | 'document' | 'diligence' | 'handoff' | 'artifact';
  // ...
}
```

A new `ArtifactTabData` shape is added alongside `DocumentTabData` (`researchStore.ts:235`), holding the loaded `HtmlArtifact` sidecar(s) for the tab's filter context (typically a ticker).

**Round 1 correction (locked round 2)**: widening `ResearchTab.type` alone is NOT enough. `ResearchWorkspace.tsx:93,425` currently falls back to `ThreadTab` rendering for any non-document tab type. F122 must add an explicit dispatch branch BEFORE the thread fallback:

```tsx
// In ResearchWorkspace.tsx, in the tab-content render switch:
if (activeTab?.type === 'document') {
  return <DocumentTab ... />;
}
if (activeTab?.type === 'artifact') {           // NEW
  return <ArtifactTabContent tab={activeTab} data={artifactTabs[activeTab.id]} />;
}
// (existing fallback to ThreadTab continues unchanged)
return <ThreadTab ... />;
```

`artifactTabs` is the new state slice on the research store, parallel to `documentTabs` at `researchStore.ts:235`.

**Rejected alternatives** (with reasons):

- **Inline rendering inside chat messages** — would tie artifacts to the message stream lifecycle (lost on tab switch, no persistence across reloads, no list view when multiple artifacts emitted). Artifacts need to be addressable independent of the chat that produced them.
- **Separate top-level page/route** — breaks the research workspace mental model. The artifact is a research output; it belongs in the research workspace.
- **Pane alongside AgentPanel** — competes for vertical space with the conversation feed in the existing layout. Tab-based addition is non-invasive.

**Tab labeling** (locked): the tab's label is the artifact's `title` field from the sidecar. When the user is viewing a list of HTML artifacts (multiple matches for current filter), the tab label is "Workbench" (or other — open question §12.1).

**Tab lifecycle** (locked round 3):
- Opens automatically when the user clicks an HTML artifact reference (from the conversation feed inline notification — see §1.1).
- Persists in the tab strip during the session (until the user closes it OR reloads).
- **On reload**: artifact tabs are NOT restored. AND inline chips in `ConversationFeed.tsx` are NOT restored (per §5.4 lock — `htmlArtifacts` metadata is client-side-session-only). The user's ONLY recovery path is via the Workbench-tab entry-point — a small affordance on the research-workspace toolbar that opens the Workbench tab (which lists all HTML artifacts for the active ticker, or unfiltered when in free-form view). Impl plan picks the exact affordance placement.

**Round 2 correction**: original spec claimed "re-opened from persisted state" — false. `researchStore` persistence is devtools-only (`researchStore.ts:561`); on hydrate, `documentTabs` is explicitly cleared. Artifact tabs would follow the same fate. Building real cross-reload persistence requires server-side state (which artifact tabs are open per user) — out of v1 scope. Acceptable tradeoff: artifacts are durable on disk + via the API; only the tab-open state is ephemeral.

- One tab per artifact when individually opened; one "Workbench" tab when showing the list view.

### 1.1 Conversation-feed surfacing

When the agent emits an HTML artifact during a chat turn, the assistant's message in `ConversationFeed.tsx` includes an inline reference: a small chip / link that reads something like "📄 Generated: PCTY historical-coincidences timeline" with an "Open" action. Click → opens the artifact tab.

This is the only place the user discovers a new HTML artifact in v1 (no toast notifications, no auto-tab-switch — both intentionally absent; HTML artifacts are pull-not-push per addendum §11.3 open). Sidecar-list discovery via Workbench tab is the secondary path.

---

## 2. Gateway proxy extension — explicit GET handlers (locked round 2)

**Round 1 correction**: `create_gateway_router` does NOT proxy arbitrary gateway paths. Per Codex verification, it only registers `/chat` and `/tool-approval` (`app_platform/gateway/proxy.py:265,482`). The artifact endpoints need explicit handlers, AND the mount path matters — the existing proxy router is mounted at `/api/gateway` (`app.py:7793`), so naive paths under it would be `/api/gateway/chat`, `/api/gateway/tool-approval`.

**Decision**: add a NEW dedicated router at `routes/html_artifacts_proxy.py` mounted at `/api/html-artifacts` (NOT under `/api/gateway`). Three explicit GET handlers proxy to the upstream gateway. This keeps the artifact namespace clean for frontend consumers and isolates artifact-specific concerns from the chat-proxy router.

### 2.1 Router file + handlers

New file: `routes/html_artifacts_proxy.py`:

```python
"""Proxy router for HTML artifact endpoints (F122).

Forwards GET requests to the upstream AI-excel-addin gateway. Read-only;
no streaming; standard session-cookie auth chain.
"""
from fastapi import APIRouter, Depends, Request, Response
from app_platform.auth.dependencies import create_auth_dependency
# ... gateway client + signed-claim helpers reused from gateway_proxy.py

router = APIRouter(prefix="/api/html-artifacts", tags=["html-artifacts"])

@router.get("")
async def list_html_artifacts(
    request: Request,
    ticker: str | None = None,
    purpose: str | None = None,
    since: str | None = None,
    limit: int = 50,
    user = Depends(_get_current_user),
):
    # Build signed user claim, forward to gateway /api/html-artifacts with same query params
    # Return upstream JSON unchanged

@router.get("/{artifact_id}")
async def get_html_artifact_sidecar(
    artifact_id: str,
    request: Request,
    user = Depends(_get_current_user),
):
    # Forward to gateway /api/html-artifacts/{artifact_id}
    # Return upstream JSON

@router.get("/{artifact_id}/content")
async def get_html_artifact_content(
    artifact_id: str,
    request: Request,
    user = Depends(_get_current_user),
):
    # Forward to gateway /api/html-artifacts/{artifact_id}/content
    # Return text/html response (NOT JSON-parse — content is raw HTML)
```

### 2.2 Mount + auth

`app.py` registers `html_artifacts_proxy.router` alongside `gateway_proxy_router`. Auth dependency `_get_current_user` resolves from the session cookie (identical to existing patterns at `app.py:*` where `create_auth_dependency(auth_service)` is used).

### 2.3 Signed-claim generation for upstream gateway (locked round 3)

**Round 2 correction**: chat and artifact endpoints use DIFFERENT auth mechanisms upstream. Chat uses a gateway session token + `Authorization: Bearer ...` header established at session-init (`app_platform/gateway/proxy.py:355`). The gateway artifact endpoints (`/api/html-artifacts/*`) use **signed-claim HMAC headers** (`X-Agent-Claim-*`), verified by `_verify_signed_user_claim` in AI-excel-addin at `packages/agent-gateway/agent_gateway/server.py:354`. Re-using the chat-side gateway-session-token helper would NOT work.

**Actual path the new proxy must use** (locked round 4):

**Round 3 correction**: `sign_user_claim(user_id, user_email, ttl_seconds=600)` does NOT exist in risk_module. The file `utils/agent_claim.py` (~125 lines, ends at line 125) has only `sign(hmac_key, *, audience, issued_at, expiry, user_id, user_email, nonce) -> str` (the low-level primitive — returns a hex signature string; caller generates issued_at/expiry/nonce) and `verify(...)`. AI-excel-addin's `api/agent/interactive/_agent_claim.py:40` does have a `sign_user_claim` function, but it returns env-var-key dict (`AGENT_API_CLAIM_*`) for subprocess injection — not HTTP-header-key dict. F122 needs a different shape.

**F122 must add a new helper** (locked round 5, against shipped `sign()` signature):

```python
# risk_module/utils/agent_claim.py — add to existing file

import os
import secrets
import time

# 7 standard header names per the gateway's _verify_signed_user_claim contract
# (verified against AI-excel-addin packages/agent-gateway/agent_gateway/server.py:354)
_CLAIM_HEADER_NAMES = {
    "audience":   "X-Agent-Claim-Audience",
    "issued_at":  "X-Agent-Claim-Issued-At",
    "expiry":     "X-Agent-Claim-Expiry",
    "user_id":    "X-Agent-Claim-User-Id",
    "user_email": "X-Agent-Claim-User-Email",
    "nonce":      "X-Agent-Claim-Nonce",
    "signature":  "X-Agent-Claim-Signature",
}

# Gateway verifier accepts audience "agent_api_v1" (verified at
# AI-excel-addin packages/agent-gateway/agent_gateway/server.py:62)
_DEFAULT_AUDIENCE = "agent_api_v1"

def sign_user_claim_headers(
    *,
    user_id: str,
    user_email: str,
    ttl_seconds: int = 600,
    audience: str = _DEFAULT_AUDIENCE,
) -> dict[str, str]:
    """Build the 7-header dict for the signed user claim that the upstream gateway
    artifact endpoints require via `_verify_signed_user_claim`. Wraps the existing
    `sign()` primitive (which returns a hex signature string) and assembles all
    seven claim fields into HTTP header form."""
    hmac_key = os.environ["AGENT_API_USER_CLAIM_HMAC_KEY"]
    issued_at = int(time.time())
    expiry = issued_at + ttl_seconds
    nonce = secrets.token_hex(16)
    # Parameter order mirrors shipped sign() signature at utils/agent_claim.py:37 —
    # all keyword-only, so order doesn't affect correctness, but matching makes the
    # call site easier to audit alongside the primitive.
    signature = sign(
        hmac_key=hmac_key,
        audience=audience,
        issued_at=issued_at,
        expiry=expiry,
        user_id=user_id,
        user_email=user_email,
        nonce=nonce,
    )
    return {
        _CLAIM_HEADER_NAMES["audience"]:   audience,
        _CLAIM_HEADER_NAMES["issued_at"]:  str(issued_at),
        _CLAIM_HEADER_NAMES["expiry"]:     str(expiry),
        _CLAIM_HEADER_NAMES["user_id"]:    user_id,
        _CLAIM_HEADER_NAMES["user_email"]: user_email,
        _CLAIM_HEADER_NAMES["nonce"]:      nonce,
        _CLAIM_HEADER_NAMES["signature"]:  signature,
    }
```

**Round 4 correction**: previous sketch assumed `sign()` returns a dict — it actually returns a single hex signature string (`utils/agent_claim.py:37`). The helper must generate `issued_at`/`expiry`/`nonce` locally, pass all to `sign()`, then assemble the 7-header dict including all input fields + signature. Audience default corrected to `agent_api_v1` (per gateway verifier at `server.py:62`).

The new helper LIVES in `utils/agent_claim.py` alongside `sign()` and `verify()` so all claim-related code is centralized. F122 is the first caller; future signed-claim HTTP-header use cases (if any) reuse it.

- **Secret**: env var `AGENT_API_USER_CLAIM_HMAC_KEY` (set via SSM per the F114 / SSM Migration infrastructure).
- **TTL**: 600 seconds (per `AGENT_API_CLAIM_MAX_TTL_SECONDS` ceiling — also locked by F118).
- **Headers injected on forwarded request** (seven, per the signed-claim contract):
  - `X-Agent-Claim-Audience`
  - `X-Agent-Claim-Issued-At`
  - `X-Agent-Claim-Expiry`
  - `X-Agent-Claim-User-Id`
  - `X-Agent-Claim-User-Email`
  - `X-Agent-Claim-Nonce`
  - `X-Agent-Claim-Signature`

Per-request flow inside each of the three GET handlers:

```python
# Pseudocode for each handler
async def get_html_artifact_sidecar(artifact_id: str, request: Request, user = Depends(_get_current_user)):
    claim_headers = sign_user_claim_headers(
        user_id=user["user_id"],
        user_email=user["email"],
        ttl_seconds=600,
    )
    upstream_url = f"{GATEWAY_URL}/api/html-artifacts/{artifact_id}"
    async with http_client.get(upstream_url, headers=claim_headers) as resp:
        return JSONResponse(content=await resp.json(), status_code=resp.status_code)
```

(Real impl uses the shared http_client + error-handling pattern from `gateway_proxy.py`, not the simplified pseudocode above.)

**Shared-helper extraction**: the new `sign_user_claim_headers` helper lives in `utils/agent_claim.py` alongside existing `sign()` and `verify()`. F122 is the first caller. F114's `run_bash` claim minting uses a different helper variant (env-var injection for subprocesses) — they remain separate by intent.

### 2.4 Frontend public path

Frontend calls land at `/api/html-artifacts/{...}` (the router's prefix). NOT `/api/gateway/html-artifacts/{...}`. This matches the addendum's URL design and keeps the artifact namespace symmetric with how typed-artifact endpoints would surface if/when they're added to Hank web in v2.

### 2.5 Why proxy through `risk_module` + observability + rate limiting (locked round 4)

1. **Auth consistency**: web → backend session cookie → gateway signed-claim. Direct gateway calls would require a separate per-user auth flow.
2. **CORS**: prod has `hank.investments` (web) and the gateway on different origins. Proxy avoids per-request CORS handling.
3. **Observability**: the new router does NOT inherit the existing `gateway_proxy.py` request log automatically (round-3 finding — it's a separate router instance). v1 adds structured logging at each handler with fields: `request_id`, `user_id`, `artifact_id` (where applicable), `upstream_status`, `upstream_duration_ms`, `bytes_returned`. Format matches the existing structured-log convention in `gateway_proxy.py` so log aggregation queries work uniformly.
4. **Rate limiting**: v1 adds a per-user limiter on the three GET endpoints — recommend 60 req/min for list, 120 req/min for sidecar+content (sidecar+content are typically paired so the budget should accommodate). Implementation: reuse the existing rate-limiting middleware/dep if one exists in `risk_module/middleware/`; otherwise add a minimal in-memory limiter (token bucket per user) since the artifact endpoints are read-only and rate-limit bypass is low-risk. Impl plan resolves the exact mechanism.

### 2.6 Streaming of `artifact_ready` events

`artifact_ready` events are emitted by the gateway as part of the existing SSE stream from `/api/chat` (already proxied through `gateway_proxy.py`). No new streaming endpoint needed. But — per round-1 finding #2 — the existing SSE pipeline currently DROPS unknown event types. F122 must extend the pipeline to deliver `artifact_ready` to the React layer. See §5 for the chain.

Per addendum §4.1, the `ticker` field on `ArtifactReadyEvent` is widened to `str | None` for HTML artifacts. The widening lands as part of AI-excel-addin's foundation-layer impl. Hank's SSE event mapper must tolerate `null` ticker once §5 extension lands.

---

## 3. Component architecture

Three new React components, all under `frontend/packages/ui/src/components/research/artifact/`:

```
artifact/
  HtmlArtifactRenderer.tsx       — single artifact render (the iframe + exports)
  HtmlArtifactList.tsx           — sub-list view (when multiple artifacts in tab filter)
  ArtifactTabContent.tsx         — tab content host, decides single vs list view
  __tests__/
    HtmlArtifactRenderer.test.tsx
    HtmlArtifactList.test.tsx
```

Plus one new hook file in connectors:

```
@risk/connectors/src/features/external/hooks/
  useHtmlArtifacts.ts            — useHtmlArtifacts({ ticker? }), useHtmlArtifact(artifactId)
```

And the `researchStore.ts` extension for the `'artifact'` tab type + `ArtifactTabData`.

### 3.1 `HtmlArtifactRenderer.tsx` — single-artifact render

```tsx
import { memo, useEffect, useRef } from 'react';
import type { HtmlArtifactSidecar } from '@risk/connectors';

import { buildSandboxedDocument } from './buildSandboxedDocument';
import { StaticExportsBar } from './StaticExportsBar';
import { ArtifactMetadataHeader } from './ArtifactMetadataHeader';

interface HtmlArtifactRendererProps {
  sidecar: HtmlArtifactSidecar;
  htmlContent: string;
}

export const HtmlArtifactRenderer = memo(function HtmlArtifactRenderer({
  sidecar,
  htmlContent,
}: HtmlArtifactRendererProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);

  const sandboxedDoc = buildSandboxedDocument({ agentHtml: htmlContent });
  // `key` tied to artifact_id ensures a fresh iframe per artifact (avoids srcdoc-doesn't-update bug)
  return (
    <div className="flex h-full min-h-0 flex-col">
      <ArtifactMetadataHeader sidecar={sidecar} />
      <iframe
        key={sidecar.artifact_id}
        ref={iframeRef}
        sandbox="allow-scripts"
        srcDoc={sandboxedDoc}
        title={sidecar.title}
        className="flex-1 w-full border-0 bg-white"
      />
      <StaticExportsBar exports={sidecar.exports} />
    </div>
  );
});
```

**Key React-specific design decisions** (locked per round 1):

1. **`srcDoc` as a normal React prop**, NOT `dangerouslySetInnerHTML`. React renders `srcdoc` natively as an attribute on `<iframe>`. No `dangerously*` API needed; the sandbox + CSP enforce safety, not HTML escaping at the React layer.

2. **`key={sidecar.artifact_id}`** is load-bearing. Without it, React would reuse the same iframe DOM node when the user switches between artifacts in the list view, and some browsers don't re-parse `srcdoc` when the attribute value changes on an existing iframe. The `key` forces React to unmount + remount the iframe, guaranteeing a fresh document.

3. **`memo` wrapper** matches the existing `MarkdownRenderer` pattern for re-render avoidance on stable props (sidecar + htmlContent are both immutable for a given artifact).

4. **No `iframeRef` usage in v1** — the ref is declared for future a11y / focus-management additions but not used. Reserved here so the type signature is stable for v2 work.

### 3.2 `HtmlArtifactList.tsx` — multi-artifact list view

Renders a clickable list of artifact rows when multiple HTML artifacts match the current tab's filter (typically a ticker). Each row shows title + summary + timestamp + source skill. Click → switches the tab to single-artifact view with the chosen artifact.

```tsx
interface HtmlArtifactListProps {
  artifacts: HtmlArtifactSidecar[];
  onSelect: (artifactId: string) => void;
}
```

Visual style follows existing Hank list patterns (subtle dividers, hover state, monospace timestamps). Defers to DESIGN.md for typography/color (per project rule: read DESIGN.md before visual decisions).

### 3.3 `ArtifactTabContent.tsx` — tab content host

Decides between single-artifact render and list view based on `ArtifactTabData`:

```tsx
interface ArtifactTabContentProps {
  tab: ResearchTab;            // type: 'artifact'
  data: ArtifactTabData;
}

// If data.mode === 'single' → HtmlArtifactRenderer
// If data.mode === 'list'   → HtmlArtifactList (with onSelect that flips to single mode)
```

### 3.4 `buildSandboxedDocument` — CSP shell construction

Pure function, exported separately for testability:

```tsx
const SANDBOX_CSP_V1 =
  "default-src 'none';" +
  "script-src 'unsafe-inline';" +
  "style-src 'unsafe-inline';" +
  "img-src data:;" +
  "font-src data:;" +
  "connect-src 'none';" +
  "form-action 'none';" +
  "base-uri 'none';" +
  "object-src 'none';" +
  "frame-src 'none';" +
  "frame-ancestors 'none';";

interface BuildSandboxedDocumentInput {
  agentHtml: string;
}

export function buildSandboxedDocument({ agentHtml }: BuildSandboxedDocumentInput): string {
  const bodyFragment = stripOuterDocumentWrappers(agentHtml);  // §3.5
  return `<!DOCTYPE html>
<html>
<head>
<meta http-equiv="Content-Security-Policy" content="${SANDBOX_CSP_V1}">
</head>
<body>
${bodyFragment}
</body>
</html>`;
}
```

Mirrors the addendum §6.2 + §6.3 logic. The CSP string is **identical** to the taskpane version (addendum §6.2) — both surfaces enforce the same policy.

### 3.5 `stripOuterDocumentWrappers` — body-fragment normalization

If the agent emits a full document (with `<!DOCTYPE>`, `<html>`, `<head>`), strip the wrappers and keep only `<body>` content + any `<style>` blocks from `<head>`. Mirrors addendum §6.3.

Implementation: DOM parsing via `DOMParser` on the agent's HTML, then `querySelector('body')` and `querySelectorAll('style')` extraction. Edge cases (malformed HTML, no body) fall back to wrapping the entire input as body content.

### 3.6 `StaticExportsBar` — clipboard exports

Renders 0–3 buttons depending on which exports the sidecar populated:

```tsx
interface StaticExportsBarProps {
  exports: StaticExports;
}
```

Each button:
- Renders only if its corresponding field on `exports` is non-null
- On click → `navigator.clipboard.writeText(...)` for prompt/markdown; `JSON.stringify(...)` for json
- Brief "Copied" state for 1.5s (visual feedback)
- No network calls, no `postMessage` — purely client-side clipboard write

Per addendum §8: exports are **static**, captured at emit time. The bar reads from `sidecar.exports`, NOT from inside the iframe.

---

## 4. Auth + fetch (connectors hooks)

New file: `frontend/packages/connectors/src/features/external/hooks/useHtmlArtifacts.ts`.

```ts
// Hooks for HTML artifact fetching

export function useHtmlArtifacts(options: {
  ticker?: string | null;
  purpose?: HtmlArtifactPurpose;
  since?: string;
  limit?: number;
}): { data: HtmlArtifactSidecar[] | undefined; isLoading: boolean; ... }

export function useHtmlArtifact(artifactId: string | null): {
  sidecar: HtmlArtifactSidecar | undefined;
  content: string | undefined;
  isLoading: boolean;
  // ...
}
```

**Fetch pattern** (locked round 3): `requestJson` is NOT exported from `@risk/connectors` (round-1 correction — local to hook files at e.g., `useResearchContent.ts:47`). `APIService.request` always parses response as JSON (`HttpClient.ts:50`), so the HTML content endpoint needs a different path.

**Round 2 correction**: `APIService.requestRaw` does exist BUT calls `HttpClient.requestRaw` with `throwOnHttpError=false` (`HttpClient.ts:187`) — non-2xx responses return the body, not throw. A naive `.text()` helper would render 404 error pages or 500 error bodies as artifact content, breaking the §6.6 failure-state requirements.

Resolution: add a small exported `requestText(api, path, opts)` helper that:

```ts
// frontend/packages/connectors/src/lib/requestText.ts (or wherever requestJson family ends up)

export async function requestText(
  api: APIService,
  path: string,
  opts?: RequestOptions,
): Promise<string> {
  const response = await api.requestRaw(path, opts);
  if (!response.ok) {
    throw new ApiError(response.status, await response.text());
  }
  return response.text();
}
```

Explicit non-2xx handling is load-bearing: `useHtmlArtifact` relies on the helper throwing to enter the failed-fetch state (§6.6). React Query treats thrown errors as query failures; success-on-non-2xx would render error HTML inside the iframe sandbox.

`ApiError` type already exists in the codebase (or is locally defined alongside the helper; impl plan resolves). Same pattern future helpers will want for `.docx` / raw file blob fetches.

**Two-step fetch for `useHtmlArtifact`**: hook fetches the sidecar first (`GET /api/html-artifacts/{id}` via `requestJson`), then content (`GET /api/html-artifacts/{id}/content` via `requestText`). React Query manages both cache entries; the hook composes them into `{ sidecar, content }`.

**React Query caching**: artifacts are immutable once emitted (the JSON sidecar + .html payload never change for a given artifact_id). Cache TTL is effectively infinite at the artifact_id level. List endpoint cache is shorter (new artifacts can arrive). Cache keys:
- `['html-artifacts', { ticker, purpose, since, limit }]` for list
- `['html-artifact', artifactId]` for sidecar
- `['html-artifact-content', artifactId]` for content

Cache invalidation on `artifact_ready` event with `contract_name === "HtmlArtifact"`: invalidate the matching list-query cache keys so the new artifact appears.

---

## 5. SSE event pipeline extension (locked round 2)

**Round 1 correction**: the existing SSE pipeline currently DROPS unknown event types. `GatewayService.mapEvent` (`frontend/packages/chassis/src/services/GatewayService.ts:437`) returns `null` for events it doesn't recognize; `useResearchChat` (`frontend/packages/connectors/src/features/external/hooks/useResearchChat.ts:103`) handles only mapped chunk types (text, tool results, citation validation). `artifact_ready` is not in the mapped set, so the frontend never sees it today.

F122 extension touches **five** layers in the SSE chain (round-2 correction: original sketch missed the `parseClaudeStreamChunk` layer):

### 5.1 Gateway-side event emission (out of scope — addendum)

AI-excel-addin foundation-layer impl emits `artifact_ready` with `contract_name === "HtmlArtifact"` from the `emit_html_artifact` tool via the `_emit_parent_event` bridge. Hank's existing chat proxy forwards SSE through unchanged. Spec just confirms this is upstream-ready.

### 5.2 Event mapping — `GatewayService.mapEvent` + `parseClaudeStreamChunk` (locked round 3)

**Round 2 correction**: the original §5.2 had the wrong field set (used `run_id`, was missing `data_source` and `skill_run_id`). The shipped `ArtifactReadyEvent` at `packages/agent-gateway/agent_gateway/events.py:49` carries:

```
{
  type: 'artifact_ready',
  skill_run_id: string,             // NOT 'run_id'
  ticker: string | null,            // widened per addendum §4.1
  skill: string,
  artifact_id: string,
  artifact_path: string,
  binary_artifact_path: string | null,
  contract_name: string,
  data_source: 'live' | 'fixture',  // per parent §2.4
  ts: number,                       // numeric (epoch SECONDS, from time.time()), NOT string
}
```

**Foundation-layer dependency** (round-3 finding #2): the shipped `ArtifactReadyEvent` schema in `events.py:49` currently has `ticker: str` (not nullable), and `event_from_dict` (`events.py:159`) coerces null to string `"None"` at deserialization. Both must be fixed by AI-excel-addin's foundation-layer impl plan BEFORE F122 ships. F122 declares the dependency explicitly: foundation-layer impl PRs land first, then F122 frontend changes assume the widened wire shape.

F122 TS chunk variant mirrors the POST-widening field set:

```ts
// In chassis ClaudeStreamChunk / connectors ParsedChatStreamEvent union

interface ArtifactReadyChunk {
  type: 'artifact_ready';
  skill_run_id: string;
  ticker: string | null;
  skill: string;
  artifact_id: string;
  artifact_path: string;
  binary_artifact_path: string | null;
  contract_name: string;            // "HtmlArtifact" for our case; other typed artifacts pass through too
  data_source: 'live' | 'fixture';
  ts: number;
}
```

Two parser sites must be updated, not one:

1. **`GatewayService.mapEvent`** (`frontend/packages/chassis/src/services/GatewayService.ts:437`): add a case for `artifact_ready` that maps the raw gateway event to `ArtifactReadyChunk`.

2. **`parseClaudeStreamChunk`** (`frontend/packages/connectors/src/features/external/chatStreamPayloads.ts:310`): add `'artifact_ready'` to the discriminator switch. Currently unknown chunk types return `ignored`; without this addition, chunks reach `useResearchChat` only to be silently dropped.

Unknown event types continue to return `null` / `ignored` in both layers (the existing safe default). Non-HTML typed artifacts (`EarningsScenarios`, `CriticalFactor`, etc.) pass through as `ArtifactReadyChunk` with a different `contract_name` — F122 logic at §5.3 discriminates on `contract_name === "HtmlArtifact"` before invalidating cache.

### 5.3 Chat hook consumption — `useResearchChat`

`useResearchChat.ts:103` (the chunk handler switch) adds a branch for `artifact_ready` chunks:

```ts
case 'artifact_ready':
  if (chunk.contract_name === 'HtmlArtifact') {
    // (a) Invalidate the html-artifacts list cache (matching ticker filter)
    queryClient.invalidateQueries({ queryKey: ['html-artifacts'] });
    // (b) Annotate the in-flight assistant message with the artifact reference
    appendArtifactReference(currentMessageId, {
      artifact_id: chunk.artifact_id,
      title: null,                                   // resolved lazily by ConversationFeed via useHtmlArtifact(artifact_id)
    });
  }
  // Non-HtmlArtifact events (typed contracts the addendum didn't address) currently ignored;
  // future contract additions hook in here.
  break;
```

### 5.4 Message metadata — `ResearchMessageMetadata.htmlArtifacts`

Currently `ResearchMessageMetadata` is open-ended with no artifact-reference shape (round-1 non-blocking finding #8). Add:

```ts
interface ResearchMessageMetadata {
  // ...existing fields
  htmlArtifacts?: Array<{
    artifact_id: string;
    title: string | null;          // null until sidecar loads; ConversationFeed fetches via useHtmlArtifact
  }>;
}
```

The optimistic in-flight assistant message accumulates `htmlArtifacts` via `appendArtifactReference` during the stream.

**Round 2 correction**: original spec claimed server persistence of `htmlArtifacts` on `ResearchMessage.metadata`. **Dropped for v1.** Reason: server-side message persistence today doesn't know about `artifact_ready` events (they're forwarded through SSE but not introspected by the message-finalization path). Adding server-side artifact-reference capture would require backend changes to research-message persistence — out of v1 scope.

**v1 behavior (locked)**: `htmlArtifacts` metadata is **client-side-session-only**. The chip in `ConversationFeed.tsx` appears during the session for any message that triggered an HTML artifact. On reload, `fetchResearchMessages` reconciles the persisted server message WITHOUT `htmlArtifacts` (the field doesn't survive). The chip disappears post-reload.

**Recovery path**: user finds artifacts via the **Workbench tab list** (lists all HTML artifacts for the active ticker or unfiltered). The artifacts themselves remain durable on disk; only the per-message chip annotation is ephemeral.

This is consistent with the §1.2 lock (no reload restoration of artifact tabs). v2 work: server-side persistence of artifact references on messages, restoring chip + tab state across reloads. Tracked as a v2 enhancement; not blocking F122 v1.

### 5.5 No auto-switch

Per addendum §11.3 lock: `artifact_ready` for HTML artifacts does NOT auto-switch the research workspace tab. Tab opens only on explicit user click (the inline chip in `ConversationFeed.tsx` per §1.1).

### 5.6 Test surface

- Mapper test: feed synthetic `artifact_ready` events into `GatewayService.mapEvent`; assert correct chunk discrimination.
- Hook test: assert `useResearchChat` invalidates `['html-artifacts']` query and annotates the current message on `contract_name === "HtmlArtifact"` chunks; assert non-HTML contract names don't trigger either action.
- Anti-pattern test (per §6 below): assert NO `contract_name` other than `"HtmlArtifact"` ever triggers HTML-side cache invalidation or chip annotation.

---

## 6. Tests

### 6.1 Component tests

In `frontend/packages/ui/src/components/research/artifact/__tests__/`:

- **`HtmlArtifactRenderer.test.tsx`** — iframe receives correct `srcdoc`; CSP meta tag present; sandbox attribute correct; key changes force remount; export buttons render conditionally.
- **`HtmlArtifactList.test.tsx`** — list renders all artifacts; click invokes `onSelect`; empty state renders.
- **`buildSandboxedDocument.test.ts`** — CSP string matches addendum §6.2 exactly (regression guard if anyone tries to loosen it); body-fragment normalization strips `<!DOCTYPE>`/`<html>`/`<head>` correctly.

### 6.2 Anti-pattern guard test

Mirror addendum §10 test (1) — assert that no typed-contract artifact is ever routed to `HtmlArtifactRenderer`. Implementation: in the event-stream consumer test, feed synthetic `artifact_ready` events with `contract_name` set to each typed contract name (`EarningsScenarios`, `CriticalFactor`, `LpLetter`, etc.) and assert the HTML artifact code path is never triggered.

### 6.3 Gateway proxy test

Backend test that `/api/html-artifacts/*` proxy routes correctly to the gateway and pass through the session-cookie → user-claim auth chain. Mirrors existing chat-proxy tests in `tests/routes/test_gateway_proxy.py` (if it exists; check during impl).

### 6.4 No live-state test

Explicit test that `HtmlArtifactRenderer` does NOT register any `message` event listener on `window` — guarantees the "no postMessage protocol in v1" architectural decision (addendum §8) holds in the renderer code.

### 6.5 F122-specific anti-pattern guard (broadened round 2)

Beyond the no-`message`-listener test, F122 needs Hank-side guards (round-1 finding #9):

- **Contract-name discrimination**: assert that ONLY `artifact_ready` events with `contract_name === "HtmlArtifact"` trigger artifact-chip annotation in `useResearchChat` and `['html-artifacts']` cache invalidation. Feed synthetic events with other contract names (`EarningsScenarios`, `CriticalFactor`, `LpLetter`, future contracts) and assert no HTML-side side effects.
- **Sandbox-attribute immutability**: assert `HtmlArtifactRenderer` always renders `<iframe sandbox="allow-scripts">` exactly — no `allow-same-origin`, no `allow-forms`, etc. Regression guard if someone tries to "just enable forms for this one case."
- **CSP string immutability**: assert `buildSandboxedDocument` outputs a document containing the exact CSP string from §3.4. Regression guard if someone tries to loosen the policy.
- **No `dangerouslySetInnerHTML`**: source-level grep test asserting `dangerouslySetInnerHTML` does not appear in `frontend/packages/ui/src/components/research/artifact/`. The iframe sandbox is the safety boundary; React-level innerHTML injection is forbidden.

### 6.6 UI state tests (round-1 finding #10 — broadened)

Per-component tests for each surface state:
- `HtmlArtifactRenderer`: loading sidecar, failed sidecar fetch, loading content, failed content fetch, content fetch timeout, deleted artifact (404 from content endpoint while sidecar exists), retry path, ARIA `title` present on iframe, focusable iframe for keyboard nav.
- `HtmlArtifactList`: empty list, loading, failed list fetch, very long list (scrolling), narrow viewport (responsive collapse).
- `ArtifactTabContent`: tab data missing for tabId, switching modes (list ↔ single), tab close + reopen reconstructs state from query cache.

These are explicit acceptance criteria — impl plan implements each as a test before declaring the surface complete.

---

## 7. CSP rollout strategy

Default-deny CSP is strict; live rollout risks blocking legitimate agent HTML that we haven't seen yet.

**Decision: ship enforcing CSP from day one, no v1 telemetry for violations** (locked round 2). The CSP is what gives the security model teeth — report-only mode would defeat the addendum's threat-model guarantee. If specific use cases need relaxations, those land via the v2 `csp_relaxations` field on the contract (currently locked OUT of v1 per addendum §11.2).

**Round 1 correction**: original spec proposed a browser-side `SecurityPolicyViolationEvent` listener capturing iframe CSP violations + sending to telemetry. **Unimplementable** as written — `sandbox="allow-scripts"` without `allow-same-origin` gives the iframe an opaque origin, and the parent cannot attach event listeners to the iframe document. The CSP-spec native `report-uri` / `report-to` directives could work, but meta-tag CSP has spotty `report-uri` support across browsers (HTTP header CSPs are more reliable, and we're using meta-tag CSP because of `srcDoc`). Adding script injection + `postMessage` to bridge violation reports would contradict the addendum's no-`postMessage`-listener rule.

**Resolution**: drop browser-side CSP-violation telemetry entirely for v1. Trade-off accepted: we don't get telemetry on blocked agent HTML; if a real use case surfaces blocking issues, we fix it via either (a) agent-side adjustments (change what the agent emits) or (b) v2 `csp_relaxations` field. Both paths are slower than live telemetry, but the alternative (weakening the sandbox model) is worse.

**Reconciliation with addendum §7**: addendum mentions "optional browser CSP report-only mode for logging violations during rollout" as a possibility F122 might consider. F122 declines it because (a) report-only mode in meta-tag CSP is unreliable across browsers, (b) the security posture matters more than the telemetry, (c) v1 use cases are agent-controlled (the agent writes the HTML; we can audit what it produces against the CSP statically if needed). Not a contradiction with the addendum — addendum left it as F122's call, F122 picks enforcing-no-telemetry.

---

## 8. Sequencing + dependencies

### Blocking dependencies

1. **AI-excel-addin foundation-layer impl** must land before F122 renderer can be live-tested:
   - `HtmlArtifact` Pydantic contract
   - `emit_html_artifact` tool
   - `_html/` storage layout
   - `/api/html-artifacts/*` endpoints
   - Event schema widening (incl. `event_from_dict` null-preservation fix)
2. **New dedicated proxy router** `risk_module/routes/html_artifacts_proxy.py` (§2) + new helper `sign_user_claim_headers` in `utils/agent_claim.py` (§2.3) — both can be drafted in parallel with foundation impl, must merge after gateway endpoints exist.

### Parallel-developable

- F122 components can be drafted against **mocked sidecar + HTML fixtures** in parallel with the foundation impl. Mocks are simple — JSON sidecar shape is locked (addendum §2.1); HTML is any valid body fragment.
- `useHtmlArtifacts` hooks can be written against mocked endpoints with a feature flag.

### Filming / dogfood gates

This is **not v1 demo critical-path**. Lands in the post-v1 product surface, not the v1 demos (which target the Excel taskpane).

### PR plan (rough)

| PR | Surface | Scope |
|---|---|---|
| 1 | backend proxy + auth helper | Add new `routes/html_artifacts_proxy.py` with three explicit GET handlers (§2); add `sign_user_claim_headers` to `utils/agent_claim.py` (§2.3); mount at `/api/html-artifacts` in `app.py`; structured logging + per-user rate limit (§2.5); test that proxy auth chain works against gateway |
| 2 | connectors | New `useHtmlArtifacts` + `useHtmlArtifact` hooks; React Query setup; types from addendum contract |
| 3 | research store | Extend `ResearchTab.type` union + `ArtifactTabData`; tab open/close actions; persistence |
| 4 | components | `HtmlArtifactRenderer` + `HtmlArtifactList` + `ArtifactTabContent` + `buildSandboxedDocument` + `StaticExportsBar` |
| 5 | conversation-feed integration | Inline "Generated artifact" chip in `ConversationFeed.tsx`; SSE listener updates `useHtmlArtifacts` cache |
| 6 | tests | All component tests + anti-pattern guard test + gateway proxy test |

PRs 1 + 2 + 3 + 4 can develop in parallel; 5 depends on 3 + 4; 6 follows the surface it tests.

### Downstream consumers (shared-infra reuse)

The deliverables from PRs 1 + 2 + 4 (proxy router, auth helper, hooks, sandbox, CSP, exports) are **shared infra** consumed by the analyst-view extension (`AI-excel-addin/docs/design/f122-analyst-view-extension-spec.md`, CODEX PASS round 3 2026-05-23). When writing F122's impl plan, scope these surfaces as shared / reusable — NOT research-workspace-private. Specifically:

- `routes/html_artifacts_proxy.py` (PR 1) — used by both research workspace and analyst-view fetches; no surface-discriminated paths needed.
- `sign_user_claim_headers` (PR 1) — generic helper; reusable by anything that proxies HMAC-signed gateway calls (future signed-claim endpoints reuse it too).
- `useHtmlArtifacts` / `useHtmlArtifact` (PR 2) — surface-agnostic React Query hooks; both surfaces call them.
- `HtmlArtifactRenderer` + `buildSandboxedDocument` + `StaticExportsBar` (PR 4) — pure rendering primitives; analyst-view's `ArtifactPanel` integration wraps `HtmlArtifactRenderer` for the slide-over context.

The analyst-view extension impl plan (PARKED) picks up as ~1 small PR (~250-400 LOC) once F122's PRs 1, 2, 4 land. It adds: (a) `html-artifact` block registration into the existing `:::artifact` block-registry pipeline so `ArtifactPanel` knows to mount `HtmlArtifactRenderer`, (b) inline chip in `ChatCore.tsx` for the analyst-path (pointing into `ArtifactPanel`, not the workspace `'artifact'` tab).

This sequencing is the cleanest path even ignoring the analyst-view side — research workspace gets the shared infra first, analyst-view bolts on with minimal incremental work.

---

## 9. F122-specific items NOT in the addendum

Items locked here that the addendum left for the renderer-side spec:

1. **Tab placement in research workspace** (vs. inline message rendering, separate page, side panel) — chose research-workspace tab type
2. **Gateway proxy extension** (vs. dedicated backend routes) — chose proxy extension
3. **React component layout** — three components + buildSandboxedDocument util
4. **Conversation-feed surfacing** — inline chip, manual click to open
5. **CSP rollout** — enforcing day one; NO browser-side violation telemetry (unimplementable across sandbox boundary; meta-tag CSP doesn't support `report-uri`/`Report-Only`)
6. **React-iframe gotchas resolved** — `srcDoc` as normal prop, `key={artifact_id}` for force-remount, no `dangerouslySetInnerHTML`
7. **Cache strategy** — React Query keyed on artifact_id, invalidate-on-event for list queries
8. **Test surface** — four test categories enumerated

---

## 10. Out of scope (explicitly)

- Editing inside the artifact (addendum §10 lock — no live re-prompting)
- `postMessage` protocol (addendum §10 lock — v2)
- Auto-tab-switch on `artifact_ready` (addendum §11.3 lock — never auto-switch in v1)
- Toast notifications (intentional — discovery is via inline chip + Workbench tab list)
- Cross-artifact composition (addendum §10 lock — v2)
- Multi-ticker dashboard view ("all my HTML artifacts across all tickers") — could be useful but not v1; user discovers via current ticker context or unfiltered list when in free-form view
- Sharing / export to URL — sandbox prohibits external links; sharing is via the copy-as-* buttons + paste into another tool
- Mobile-responsive layout — research workspace is desktop-focused; v2 question
- Light/dark theme switching inside the iframe — agent's HTML controls its own visuals; iframe sandbox doesn't inherit parent theme. Acceptable v1 limitation.

---

## 11. Locked decisions (F122)

1. **Tab placement**: new research-workspace tab type `'artifact'` (§1). Extends `ResearchTab.type` union; adds `ArtifactTabData` alongside `documentTabs`. **PLUS** explicit `'artifact'` dispatch branch in `ResearchWorkspace.tsx` before the thread fallback (round-2 round-1 finding).
2. **Component location**: `frontend/packages/ui/src/components/research/artifact/` (§3).
3. **Hook location**: `frontend/packages/connectors/src/features/external/hooks/useHtmlArtifacts.ts` (§4).
4. **Gateway access**: NEW dedicated proxy router `routes/html_artifacts_proxy.py` mounted at `/api/html-artifacts` with three explicit GET handlers (§2). NOT extending `gateway_proxy.py` (which only proxies `/chat` + `/tool-approval` and is mounted at `/api/gateway`).
5. **`srcDoc` as React prop** + `key={artifact_id}` for forced remount — no `dangerouslySetInnerHTML` (§3.1). Confirmed safe in React 19.
6. **`memo` wrapper** matching existing `MarkdownRenderer` pattern (§3.1).
7. **CSP enforcing day one; NO browser-side violation telemetry** (§7). Original sketch's `SecurityPolicyViolationEvent` capture is unimplementable across the sandbox boundary; meta-tag `report-uri` is unreliable; explicit acceptance of no-telemetry tradeoff.
8. **Discovery surface**: inline chip in `ConversationFeed.tsx` footer action row (§1.1); no toasts, no auto-switch (§5.5).
9. **Cache strategy**: React Query keyed on `artifact_id` (effectively immutable); list queries invalidate on `artifact_ready` event with `contract_name === "HtmlArtifact"` (§4, §5.3).
10. **No `postMessage` listener on parent** — explicit non-implementation; tested via §6.4 anti-pattern guard.
11. **CSP string identical to taskpane addendum §6.2** — single source of truth; both surfaces enforce the same policy.
12. **SSE pipeline extension at FIVE layers** (locked round 4 — round-2 corrected count): `GatewayService.mapEvent` adds `artifact_ready` case; `parseClaudeStreamChunk` (`chatStreamPayloads.ts:310`) adds discriminator branch (was missing); `ClaudeStreamChunk` / `ParsedChatStreamEvent` union adds `ArtifactReadyChunk` variant; `useResearchChat` handler adds discriminated branch; `ResearchMessageMetadata` adds optional `htmlArtifacts` array for message annotation (§5).
13. **`requestText` exported helper** in `@risk/connectors/src/lib/` — `requestJson` is local-only today (round-1 correction); HTML content endpoint needs a text-returning fetch helper. v1 adds it as a shared export.
14. **TS schema sync — hand-mirrored + parity test** (§12 below). Hand-write TS interfaces (`HtmlArtifactSidecar`, `StaticExports`, `ArtifactReadyChunk`) in `@risk/connectors`; add a parity test that fetches a known artifact and asserts the response shape exhaustively matches the TS interface. Future v2 may switch to OpenAPI codegen if the contract grows.
15. **`ResearchMessageMetadata.htmlArtifacts` shape locked** (§5.4) — array of `{ artifact_id, title: string | null }`. Title is lazy (resolved by `ConversationFeed` via `useHtmlArtifact`); only `artifact_id` is required at append time. **Client-side-session-only** (locked round 3 per round-2 finding #7) — not persisted server-side; reload clears; user recovers via Workbench tab list.
16. **Signed-claim header injection** (locked round 3, refined round 5): proxy handlers use the NEW `utils/agent_claim.sign_user_claim_headers` helper with TTL 600s (§2.3) — wraps the existing `sign()` primitive. Injects 7 `X-Agent-Claim-*` headers per request. NOT the chat-side session-token-Bearer mechanism (those are different upstream auth contracts). See lock #21 for full helper details.
17. *(merged into lock #12 round 5 — was duplicate enumeration of the 5-layer SSE chain. Lock #12 above is the canonical version.)*
18. **`ArtifactReadyChunk` field shape** (locked round 3 per round-2 finding #3): mirrors shipped `ArtifactReadyEvent.events.py:49` exactly — `skill_run_id` (NOT `run_id`), `data_source`, numeric `ts`, etc.
19. **`requestText` with explicit non-2xx handling** (locked round 3 per round-2 finding #4): helper throws on non-OK status. `useHtmlArtifact` relies on this to enter failed-fetch state. Naive `requestRaw().text()` would render error bodies as artifact content.
20. **No reload restoration for artifact tabs OR chip annotations** (locked round 3 per round-2 finding #5+#7): `researchStore` persistence is devtools-only; documentTabs are cleared on hydrate; artifact tabs follow the same fate. Recovery is via the Workbench-tab entry-point (a small affordance on the research-workspace toolbar — impl plan picks placement; see §12 open #4).
21. **`sign_user_claim_headers` helper added to `utils/agent_claim.py`** (locked round 4 per round-3 finding #1): new function wraps existing `sign()` primitive and returns `{X-Agent-Claim-*: value}` dict for direct HTTP-header injection. The function `sign_user_claim` from AI-excel-addin's `_agent_claim.py` is for ENV-VAR injection (subprocess pattern) — different shape, NOT reusable here.
22. **Foundation-layer dependency declared** (locked round 4 per round-3 finding #2): F122 cannot ship until AI-excel-addin's foundation-layer impl lands (a) `ArtifactReadyEvent.ticker: str → str | None` widening and (b) `event_from_dict` null-preservation bug-fix. F122 TS types declare the post-widening shape in anticipation.
23. **Proxy observability + rate limit** (locked round 4 per round-3 finding #5): structured logging at each handler (request_id, user_id, artifact_id, upstream_status, upstream_duration_ms, bytes_returned); per-user rate limit (60/min list, 120/min sidecar+content). Impl plan resolves limiter mechanism (reuse existing middleware vs. minimal in-memory).

---

## 12. Cross-repo TS schema sync (new section, round 2)

**Round 1 finding #7**: Python contract (`HtmlArtifact` Pydantic) lives in AI-excel-addin's `schema/html_artifact.py`. F122 imports TS types (`HtmlArtifactSidecar`, `StaticExports`, etc.) from `@risk/connectors`. The two need to stay in sync or the frontend silently breaks when contracts change.

**Decision: hand-mirrored + parity test** (locked).

### 12.1 Hand-mirrored TS interfaces

Define in `frontend/packages/connectors/src/types/htmlArtifact.ts`:

```ts
export type HtmlArtifactPurpose =
  | 'exploration'
  | 'comparison'
  | 'explainer'
  | 'session_log'
  | 'report'
  | 'other';

export interface StaticExports {
  copy_as_prompt: string | null;
  copy_as_markdown: string | null;
  copy_as_json: Record<string, unknown> | null;
}

export interface HtmlArtifactSidecar {
  artifact_id: string;
  title: string;
  purpose: HtmlArtifactPurpose;
  content_ref: string;
  summary: string;
  ticker: string | null;
  session_id: string | null;
  source_skill: string;
  sources: SourceRecord[];          // SourceRecord already exists in TS-side types if applicable; otherwise mirrored
  exports: StaticExports;
  ts: string;
  contract_name: 'HtmlArtifact';
}
```

These mirror the addendum's Pydantic shape one-to-one. Comments on each field reference the addendum location for traceability.

### 12.2 Parity test (mechanics locked round 3)

**Fixture source-of-truth**: canonical fixture lives in AI-excel-addin at `tests/fixtures/html_artifact_canonical.json` (alongside the addendum's other contract fixtures). AI-excel-addin's foundation-layer impl plan owns updates to this file when the contract changes.

**Vendored copy in risk_module**: `risk_module/frontend/packages/connectors/src/types/__fixtures__/html_artifact_canonical.json` is a **synced copy** of the AI-excel-addin fixture. Sync is human-enforced at PR review (no automated CI cross-repo check in v1 — see #3 below).

**Two per-repo parity tests + a PR-time manual sync guard** (three guards total):

1. **AI-excel-addin Python parity test** (`AI-excel-addin/tests/schema/test_html_artifact_fixture.py`): loads the canonical fixture, deserializes via the `HtmlArtifact` Pydantic class, asserts all fields populate, re-serializes, asserts byte-identical to the fixture (catches drift if the Pydantic class adds/renames/drops a field without updating the fixture).

2. **risk_module TypeScript parity test** (`frontend/packages/connectors/src/types/__tests__/htmlArtifact.parity.test.ts`): loads the vendored copy, asserts the `HtmlArtifactSidecar` interface accepts it (compile-time TypeScript type assertion + runtime exhaustive deep equality with a hand-written expected shape). Catches drift if the TS interface diverges from the fixture.

3. **PR-time manual sync + diff guard** (locked round 5): when AI-excel-addin foundation-layer impl touches `tests/fixtures/html_artifact_canonical.json`, the paired risk_module PR must include a byte-identical copy at `frontend/packages/connectors/src/types/__fixtures__/html_artifact_canonical.json`. The risk_module PR's parity test (#2 above) fails if the TS interface diverges from the vendored copy; the AI-excel-addin PR's parity test (#1 above) fails if Pydantic diverges from the canonical. The cross-repo byte-match check is human-enforced at PR review (reviewer eyeballs the diff or runs `diff` locally). Aspirational future state: a GitHub Action that checks out both repos and compares hashes — out of v1 scope, would require additional CI config not in either repo today.

**Sync ownership**: AI-excel-addin is canonical. When the addendum's foundation-layer impl plan adds a contract field, the impl plan PR updates the AI-excel-addin fixture AND opens a paired risk_module PR copying the new fixture + updating the TS interface. The risk_module PR's parity test catches divergence between the TS interface and the vendored fixture; human PR review catches divergence between the two repos' fixture copies.

When the contract grows past ~5 fields' worth of incremental change, revisit by switching to OpenAPI codegen (per §12.3).

### 12.3 v2 consideration

If the HTML artifact contract grows substantially (e.g., adds 5+ new fields, accumulates per-purpose subtypes), revisit by switching to OpenAPI-spec-driven codegen for TS types. For v1's 8-field contract, hand-mirrored is the right scope.

---

## 12. Open questions for Codex round 4 (scrubbed round 4)

Round-4 scrub: removed the `SecurityPolicyViolationEvent` reporting open (resolved as no-telemetry per §7 lock) and the tab-persistence open (resolved as no-restoration per §1.2 lock).

1. **Workbench tab naming** when in list mode (multiple artifacts): "Workbench" vs "HTML Artifacts" vs "Notes" vs "Custom". Inherits the addendum's §11 open question — F122 makes the final call. Preference: "Workbench" (matches the "long-tail exploration" framing).
2. **Inline chip styling**: should the inline chip in `ConversationFeed.tsx` be subtle (text-link style) or more prominent (badge/pill)? Affects discoverability vs. visual noise. Codex can arbitrate or defer to DESIGN.md alignment in impl plan.
3. **Sidecar list endpoint default limit**: addendum §5.2 says default 50, max 200. Is 50 the right default for the Workbench list view, or would 20 be saner (most users won't scroll past 20)? Defer to impl plan or pick now.
4. **Workbench-tab entry-point placement**: where on the research-workspace toolbar does the user click to open the Workbench tab when no artifact chip is visible (e.g., post-reload)? Adjacent to existing tab strip? Toolbar button? Impl plan picks placement.
5. **Print / screenshot affordance**: the addendum §9 use cases mention "give me a one-pager I could screenshot for my PM" — does v1 add an explicit print/screenshot button (browser-native print already works), or rely on the user's browser print? Probably leave to browser-native; flag as v2 enhancement if asked.

---

## 13. Changelog

- **2026-05-22 #1** — Initial draft. Locks 11 decisions for the renderer-side spec; 6 narrow opens for Codex round 1. Inherits addendum's locked architecture (foundation layer, CSP, sandbox, exports). Scope is the Hank web renderer + gateway proxy extension only. Filed under risk_module TODO F122; cross-repo dependency is the AI-excel-addin foundation-layer impl plan. Not v1 demo critical-path.
- **2026-05-23 #8** — **Forward-reference addition** (post-PASS, no Codex re-review). Parallel-session work in AI-excel-addin produced an `f122-analyst-view-extension-spec.md` delta-spec (CODEX PASS round 3 2026-05-23) that explicitly defers to THIS spec for shared infra (proxy router, auth helper, hooks, sandbox/CSP, exports, SSE chunk type) and adds only analyst-view-specific bits (block-registry integration + analyst-path inline chip). Two reciprocal changes: (a) preamble note added below "Workflow next steps" describing the second consumer surface + meta-lesson that prior twin specs in AI-excel-addin (`f122-html-artifact-renderer-spec.md` round-5 PASS + `…-impl-plan.md` draft) are **SUPERSEDED 2026-05-23** due to load-bearing architectural errors (wrong auth model, wrong proxy structure, missing `key={id}` re-mount); (b) §8 sequencing adds a "Downstream consumers (shared-infra reuse)" subsection telling F122's impl-plan-writer to scope PRs 1/2/4 deliverables as shared not workspace-private. No locked decisions change; the spec architecture remains as PASSed at round 7. Status: CODEX PASS round 7 — READY FOR IMPL PLAN (unchanged).
- **2026-05-22 #7** — **CODEX PASS round 7.** Both round-6 nits resolved (§12 parenthetical CI-parity wording removed; §2.3 prose description of `sign()` updated to match shipped signature). Codex verdict: "Both round-6 nits are addressed... No further polish concerns." Status: REVISION → **CODEX PASS — READY FOR IMPL PLAN**.
- **2026-05-22 #6** — Round 5 Codex returned CONCERNS (0 blockers + 3 non-blocking text-sweep items). All 3 resolved: (1) lock #16 updated to reference `sign_user_claim_headers` (lock #21 has full helper details), no more references to nonexistent function; (2) §12 stale "CI parity check" wording fully rewritten — three call sites updated to reflect human-enforced PR-time sync; (3) §2.3 helper sketch `sign()` kwarg order reordered to mirror shipped primitive at `utils/agent_claim.py:37`. Status: REVISION → READY FOR CODEX ROUND 6.
- **2026-05-22 #5** — Round 4 Codex returned CONCERNS (1 blocking + 4 non-blocking + 3 confirmations of round-3 alignment). All 5 findings resolved: (1) `sign_user_claim_headers` helper sketch rewritten to actually match shipped `sign()` signature — generates `issued_at`/`expiry`/`nonce` locally, calls `sign()` (returns hex signature string, not dict), assembles 7-header dict. Audience corrected to `agent_api_v1` (gateway verifier expects this, not `agent-api`). (2) §8 sequencing + PR plan swept clean of "extend `routes/gateway_proxy.py`" — both now correctly reference the new dedicated `routes/html_artifacts_proxy.py`. (3) Lock #17 (duplicate SSE chain enumeration) merged into lock #12 — Codex confirmed no 6th parser/state-machine layer exists. (4) §12.2 parity-fixture mechanics downgraded from "CI cross-repo parity check runs in both repos" (aspirational, no current workflow config) to "PR-time manual sync + per-repo parity test + human-enforced diff at PR review"; aspirational CI noted as v2. (5) `ts` unit corrected to "epoch seconds" (shipped emitters use `time.time()`). Confirmations preserved: CSP no-telemetry aligned across §7/§9/§11/§12; reload recovery consistently Workbench-only; 60/120 rate-limit defaults reasonable. Total locks: 23 (lock #17 merged into #12; lock count unchanged). Status: REVISION → READY FOR CODEX ROUND 5.
- **2026-05-22 #4** — Round 3 Codex returned CONCERNS (3 blocking + 2 non-blocking + 3 confirmations of round-2 fixes verified correct). All 5 findings resolved: (1) §2.3 rewritten — new helper `sign_user_claim_headers` to add to `utils/agent_claim.py` (wraps existing `sign()` primitive, returns header-keyed dict); the function I previously named doesn't exist in risk_module (only in AI-excel-addin's `_agent_claim.py`, with env-var-key output for subprocess injection — wrong shape for HTTP proxy use). (2) §5.2 — explicit dependency declared on foundation-layer impl landing `ticker: str | None` widening AND `event_from_dict` null-preservation fix BEFORE F122 ships. (3) Stale-section sweep applied — §11 now says FIVE layers (not four); §11 CSP-rollout lock corrected to no-telemetry; §12 opens scrubbed of `SecurityPolicyViolationEvent` reporting target + tab persistence questions; §1.2 chip-on-persisted-messages claim removed (consistent with §5.4 client-side-session-only lock). Non-blocking: (4) §1.2 reload-recovery language now consistent — chip disappears post-reload, only Workbench entry-point recovers (open #4 picks toolbar placement). (5) §2.5 expanded — proxy observability (structured logging fields enumerated) + per-user rate limit (60/min list, 120/min sidecar+content). Confirmations preserved: `parseClaudeStreamChunk` discriminator real; `requestRaw` + `throwOnHttpError=false` confirmed; parity-fixture mechanics acceptable. Total locks: 20 → 23. Status: REVISION → READY FOR CODEX ROUND 4.
- **2026-05-22 #3** — Round 2 Codex returned CONCERNS (5 blocking + 2 non-blocking + 3 confirmations). All 7 findings resolved: (1) §2.3 rewritten — actual signed-claim path named (`utils/agent_claim.sign_user_claim` + `AGENT_API_USER_CLAIM_HMAC_KEY` + 7 `X-Agent-Claim-*` headers; TTL 600s); NOT the chat-side gateway-session-Bearer mechanism. (2) §5 corrected — 5-layer SSE chain (added `parseClaudeStreamChunk` / `ParsedChatStreamEvent` in `chatStreamPayloads.ts:310`). (3) §5.2 chunk field shape corrected to match shipped `ArtifactReadyEvent.events.py:49`: `skill_run_id` (NOT `run_id`), `data_source`, numeric `ts`. (4) §4 `requestText` helper specified with explicit non-2xx throwing (else `requestRaw` returns 404/500 bodies as data). (5) §1.2 reload-restoration claim dropped — `researchStore` persistence is devtools-only; recovery via Workbench tab list. (6) §12.2 parity-fixture mechanics locked — canonical in AI-excel-addin, synced copy in risk_module, CI parity check between them. (7) §5.4 server-side persistence of `htmlArtifacts` dropped — client-side-session-only for v1; chip disappears post-reload; user recovers via Workbench. Confirmations preserved (per round-2 verification): dedicated `/api/html-artifacts` router mountable; `ResearchWorkspace` branch structurally clean; CSP no-telemetry correct (meta-tag CSP supports neither `report-uri` nor `Report-Only` per MDN). Total locks: 15 → 20. Status: REVISION → READY FOR CODEX ROUND 3.
- **2026-05-22 #2** — Round 1 Codex returned CONCERNS (7 blocking + 3 non-blocking). All 10 findings resolved: (1) gateway proxy claim corrected — `create_gateway_router` only proxies `/chat` + `/tool-approval`; F122 adds dedicated `routes/html_artifacts_proxy.py` with three explicit GET handlers mounted at `/api/html-artifacts` (not under `/api/gateway`); (2) SSE pipeline extension enumerated at four layers (`GatewayService.mapEvent`, `ClaudeStreamChunk` types, `useResearchChat` handler, `ResearchMessageMetadata` shape) — previously hand-waved as "surgical changes"; (3) `ResearchWorkspace.tsx` dispatch branch added explicitly to spec — widening the tab union alone wasn't enough; (4) `requestJson` claim corrected — it's local to hook files, not exported; F122 adds `requestText` exported helper for HTML content endpoint; (5) browser-side CSP-violation telemetry dropped — unimplementable across iframe sandbox boundary without violating no-postMessage rule; (6) CSP enforcing day one (no report-only mode) — reconciled with addendum §7 which left it as F122's call; (7) cross-repo TS schema sync locked to hand-mirrored + parity test (new §12), with OpenAPI codegen as v2 if contract grows; (8) `ResearchMessageMetadata.htmlArtifacts` shape locked + optimistic-vs-persisted reconciliation specified; (9) anti-pattern guard tests broadened beyond no-`message`-listener (contract-name discrimination, sandbox immutability, CSP immutability, no-`dangerouslySetInnerHTML` grep test); (10) UI state coverage explicit (per-component loading/error/empty/retry/a11y/responsive states enumerated as acceptance criteria). Total locks: 11 → 15. Status: DRAFT → READY FOR CODEX ROUND 2.
