# F122 - HTML Artifact Renderer Implementation Plan

**Status:** CODEX PASS R3 (2026-05-31) — ready for impl dispatch.
**Created:** 2026-05-26.
**Owner:** Henry.
**Spec authority:** `docs/planning/F122_HTML_ARTIFACT_RENDERER_SPEC.md` (CODEX PASS round 7, 2026-05-22).

## 0. Why this plan exists

F122 has a PASS spec, but the primary risk_module implementation plan was never authored. The only older implementation plan is archived in AI-excel-addin and explicitly superseded because it targeted the wrong surface and the wrong proxy/auth shape.

This plan is the risk_module-side implementation plan for the primary v1 renderer surface: the research workspace. It implements the shared infra that the later analyst-view delta-spec will reuse, but it does not ship the analyst-view integration itself.

## 1. Current-state findings

- `app.py` mounts the chat gateway proxy at `/api/gateway`, and that proxy only owns chat/tool-approval concerns.
- `routes/research_content.py` is the closest proxy pattern for user-scoped upstream forwarding, but F122 cannot reuse its bearer-token model because upstream HTML artifact endpoints require signed end-user claim headers.
- `utils/agent_claim.py` already has the primitive verifier/signature pieces: `AGENT_API_CLAIM_HEADERS`, `AGENT_API_CLAIM_AUDIENCE`, `sign(...)`, `verify(...)`.
- `GatewayService.mapEvent` currently drops unknown events, so `artifact_ready` never reaches connector hooks.
- `chatStreamPayloads.ts` currently returns `ignored` for unknown chunk types, so the connector layer also needs an explicit `artifact_ready` branch.
- `researchStore.ts` supports `explore | thread | document | diligence | handoff`; it has `documentTabs` but no artifact tab slice.
- `ResearchWorkspace.tsx` only resolves document-specific tab state; unknown non-document tabs fall through to thread/explore rendering unless explicitly handled.
- `ConversationFeed.tsx` has a pattern for action rows under assistant messages ("Open in reader", "Start thread") that can host the client-session-only generated-artifact chip.

## 2. Locked v1 decisions

1. **Surface:** research workspace tab, not inline full HTML rendering in the transcript.
2. **Tab name:** the list/recovery tab is named `Workbench`. Single-artifact tabs use the sidecar `title`.
3. **Workbench entry point:** add a compact icon button in the research workspace toolbar/action row near the existing research actions. It opens the Workbench tab for the active ticker. Use an accessible label/tooltip of "Workbench".
4. **List default:** request `limit=50` for the Workbench list. This matches the addendum default and avoids a frontend-specific divergence.
5. **Proxy path:** frontend calls `/api/html-artifacts`, not `/api/gateway/html-artifacts`.
6. **Upstream auth:** risk_module session cookie resolves the user; upstream calls use seven `X-Agent-Claim-*` headers minted by a new `sign_user_claim_headers(...)` helper.
7. **No server persistence for chips:** `ResearchMessageMetadata.htmlArtifacts` is client-side-session-only in v1. Reload recovery is the Workbench list.
8. **No `postMessage`:** sandboxed iframe uses `sandbox="allow-scripts"` only. No parent `message` listener, no iframe telemetry bridge.
9. **Live E2E is blocked until AI-excel-addin ships the gateway-side HTML foundation:** `HtmlArtifact`, `emit_html_artifact`, `/api/html-artifacts/*`, and the nullable ticker/event round-trip fix. All risk_module PRs must be testable with mocks before that.
10. **Analyst-view extension:** parked until this plan lands shared infra (`sign_user_claim_headers`, proxy router, hooks, renderer, sandbox builder, SSE chunk type).

## 3. PR sequence

| PR | Scope | Blocks |
|---|---|---|
| PR-1 | Backend proxy + signed-claim helper | Required for live fetch; frontend can mock before upstream exists |
| PR-2 | Contract types + fetch helpers/hooks | Components and store integration |
| PR-3 | SSE chain + client-session message annotation | Conversation chip and list invalidation |
| PR-4 | Research store + workspace tab/Workbench routing | Renderer host |
| PR-5 | Renderer components + sandbox/export utilities | UI completion |
| PR-6 | Integration/anti-pattern tests + docs status | Close F122 implementation |

PR-1 through PR-5 can be implemented with mocked upstream responses. Live E2E is a post-merge checklist once AI-excel-addin's gateway-side foundation is deployed.

## 4. PR-1 - backend proxy + signed-claim helper

### Files

| File | Change |
|---|---|
| `utils/agent_claim.py` | Add `sign_user_claim_headers(...)` next to `sign(...)` and `verify(...)`. |
| `routes/html_artifacts_proxy.py` | New dedicated router mounted at `/api/html-artifacts`. |
| `app.py` | Import and include `html_artifacts_proxy_router`. |
| `tests/routes/test_html_artifacts_proxy.py` | New route tests. |
| `tests/test_agent_claim.py` or equivalent existing test file | Cover header helper compatibility with `verify(...)`. |

### Helper contract

```python
def sign_user_claim_headers(
    *,
    user_id: str,
    user_email: str,
    hmac_key: str | None = None,
    ttl_seconds: int = 600,
    now: int | None = None,
) -> dict[str, str]:
    ...
```

Rules:

- Default audience is `agent_api_v1`.
- Default HMAC key is `AGENT_API_USER_CLAIM_HMAC_KEY`.
- Missing HMAC key is a fail-loud 500 at the proxy layer.
- Generates `issued_at`, `expiry`, and hex nonce locally.
- Returns header-keyed values using `AGENT_API_CLAIM_HEADERS`.
- Unit test signs headers and verifies with `verify(..., ttl_ceiling=600)`.

### Proxy contract

Use a new `APIRouter(prefix="/api/html-artifacts", tags=["html-artifacts"])`.

Handlers:

- `GET /api/html-artifacts`
- `GET /api/html-artifacts/{artifact_id}`
- `GET /api/html-artifacts/{artifact_id}/content`

Forward to upstream:

- `/api/html-artifacts`
- `/api/html-artifacts/{artifact_id}`
- `/api/html-artifacts/{artifact_id}/content`

Forward query params unchanged. Strip hop-by-hop request headers, cookies, client `Authorization`, and client-supplied `X-Agent-Claim-*`; inject only freshly signed claim headers. Pass through upstream body, status, and content-type. Cap upstream 5xx as 502, matching the research-content proxy pattern.

Auth: use the same user resolution model as the research workspace. Prefer the paid-user dependency used by `routes/research_content.py`; if product policy changes, downgrade explicitly in review rather than silently exposing artifacts to a broader tier.

Observability:

- Log `request_id`, `user_id`, `artifact_id` when present, upstream path, upstream status, duration, and response bytes.
- Do not log signed-claim headers or artifact HTML content.

Rate limiting:

- Apply v1 per-user limits: 60/min for list, 120/min for sidecar/content.
- The existing SlowAPI limiter (`app_platform/middleware/rate_limiter.py`) keys on IP or API key, not authenticated user — it cannot be cleanly reused here. Add a minimal in-memory per-user token-bucket (keyed on `user_id`) local to this router. Mark it as process-local v1 behavior (not shared across processes/replicas).

### Tests

- Helper returns all seven `X-Agent-Claim-*` headers and verifies.
- Missing HMAC key returns 500 with a typed, non-secret error.
- List route forwards query params and signed-claim headers.
- Sidecar route forwards JSON content-type and ETag.
- Content route forwards `text/html`.
- Upstream 404 passes through as 404.
- Upstream 500 maps to 502.
- Client-supplied `Authorization` and `X-Agent-Claim-*` do not reach upstream.

## 5. PR-2 - types, fetch helpers, and hooks

### Files

| File | Change |
|---|---|
| `frontend/packages/connectors/src/types/htmlArtifact.ts` | New TS contract types — hand-mirrored from spec §12.1. |
| `frontend/packages/connectors/src/types/__fixtures__/html_artifact_canonical.json` | Vendored copy of AI-excel-addin canonical fixture for parity test. |
| `frontend/packages/connectors/src/types/__tests__/htmlArtifact.parity.test.ts` | Parity test: loads vendored fixture, asserts `HtmlArtifactSidecar` interface accepts it exhaustively. |
| `frontend/packages/connectors/src/lib/requestText.ts` | New helper wrapping `api.requestRaw` with explicit non-OK throws. |
| `frontend/packages/connectors/src/features/external/hooks/useHtmlArtifacts.ts` | New React Query hooks. |
| `frontend/packages/connectors/src/index.ts` | Export hooks/types/helper. |
| `frontend/packages/connectors/src/features/external/__tests__/useHtmlArtifacts.test.tsx` | Hook tests. |

### Types

Hand-mirror the sidecar shape exactly from spec §12.1. These types must match the AI-excel-addin `HtmlArtifact` Pydantic contract one-to-one. `SourceRecord` should reuse any existing TS-side source type; if none exists, mirror it alongside these types.

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
  sources: SourceRecord[];
  exports: StaticExports;
  ts: string;
  contract_name: 'HtmlArtifact';
}
```

**`SourceRecord`:** No existing TS type in the connectors package matches the `HtmlArtifact.sources` field (the existing `researchStore.Source` is a citation-registry shape, not the contract shape). PR-2 must define and export a `SourceRecord` interface in `types/htmlArtifact.ts` alongside the other types, mirroring the addendum's Python `SourceRecord` contract field-for-field.

The parity test at `types/__tests__/htmlArtifact.parity.test.ts` loads the vendored fixture from `types/__fixtures__/html_artifact_canonical.json` and asserts exhaustive deep equality with a hand-written expected shape. This catches TS interface drift when the upstream contract changes. Sync the vendored fixture copy manually when AI-excel-addin's foundation-layer impl updates `tests/fixtures/html_artifact_canonical.json` (human-enforced at PR review per spec §12.2).

### Hooks

- `useHtmlArtifacts({ ticker, limit = 50, enabled = true })`
  - Query key: `['html-artifacts', { ticker, limit }]`
  - Calls `/api/html-artifacts?ticker=...&limit=50` when ticker exists; omits ticker in free-form mode.
  - Short list staleness, e.g. 30 seconds.
- `useHtmlArtifact(artifactId)`
  - Query key: `['html-artifact', artifactId]`
  - Fetches sidecar JSON and HTML content.
  - Uses `requestText` for `/content`; throws on non-OK status.
  - Artifact-id queries can use effectively infinite stale time because IDs are immutable.

### Tests

- List hook encodes ticker and default limit.
- Sidecar + content fetch compose into one result.
- Non-2xx content response throws instead of rendering error HTML.
- Query keys are user/session safe by relying on `SessionServicesProvider` user-scoped API service and TanStack Query cleanup.

## 6. PR-3 - SSE chain and message annotation

### Files

| File | Change |
|---|---|
| `frontend/packages/chassis/src/services/ClaudeStreamTypes.ts` | Add `ArtifactReadyChunk`. |
| `frontend/packages/chassis/src/services/GatewayService.ts` | Map raw `artifact_ready` to typed chunk. |
| `frontend/packages/connectors/src/features/external/chatStreamPayloads.ts` | Add parsed `artifact_ready` event. |
| `frontend/packages/connectors/src/features/external/hooks/useResearchChat.ts` | Handle HTML artifact chunks; call `addMessageHtmlArtifact` to annotate the active optimistic message. |
| `frontend/packages/connectors/src/stores/researchStore.ts` | Add `ResearchMessageMetadata.htmlArtifacts`; add `addMessageHtmlArtifact(threadId, messageId, artifact)` action (analogous to `addMessageReaderAction`); extend `reconcileResearchTurn` to carry `htmlArtifacts` through alongside existing `readerActions`/`documentContext`. |
| Relevant tests | GatewayService, parser, useResearchChat, reconcile preserve. |

### Event shape

```ts
export interface ArtifactReadyChunk {
  type: 'artifact_ready';
  skill_run_id: string;
  ticker: string | null;
  skill: string;
  artifact_id: string;
  artifact_path: string;
  binary_artifact_path: string | null;
  contract_name: string;
  data_source: 'live' | 'fixture' | string;
  ts: number;
  scope?: string | null;
  portfolio_id?: string | null;
}
```

Rules:

- `skill_run_id`, `artifact_id`, `artifact_path`, `skill`, and `contract_name` are required strings. Malformed chunks parse as recoverable errors.
- `ticker` accepts string or null; never coerce null to `"None"`.
- `contract_name === "HtmlArtifact"` is the only trigger for F122 side effects.
- Non-HTML artifact events remain available to future consumers but do not annotate messages or invalidate HTML lists.

`useResearchChat` behavior:

- On HTML `artifact_ready`, invalidate `['html-artifacts']` queries.
- Add `{ artifact_id, title: null }` to the active optimistic assistant message metadata.
- Do not auto-open a tab.
- Do not persist this metadata server-side in v1.

**`reconcileResearchTurn` preserve rule (load-bearing):** `researchStore.reconcileResearchTurn` currently preserves only `readerActions` and `documentContext` from the optimistic message when replacing it with the server-fetched version. `htmlArtifacts` is client-session-only metadata (never stored server-side), so it will be silently dropped without an explicit carry-through. PR-3 must extend `reconcileResearchTurn` to also preserve `optimisticMessage.metadata?.htmlArtifacts` when assembling the reconciled message — same pattern as the existing `streamedReaderActions` / `streamedDocumentContext` preserve at `researchStore.ts:1815`.

**`addMessageHtmlArtifact` store action (new, analogous to `addMessageReaderAction`):** When `useResearchChat` receives an HTML `artifact_ready` chunk, it calls `addMessageHtmlArtifact(threadId, messageId, { artifact_id, title: null })` to append to the active optimistic message's `metadata.htmlArtifacts`. This action must be added to `ResearchStoreState` alongside the other message-mutation actions. The chip that renders from `htmlArtifacts` entries is scoped to PR-4 (where `openArtifactTab` is defined — chip dispatch requires that action to exist first).

**`reconcileResearchTurn` preserve rule (load-bearing):** Extend `reconcileResearchTurn` at `researchStore.ts:~1815` to also carry `optimisticMessage.metadata?.htmlArtifacts` through alongside the existing `streamedReaderActions` / `streamedDocumentContext` preserve. Include `htmlArtifacts` in both the merge condition check and the preserved-metadata assembly. No parameter signature change needed.

**`usePortfolioChat` callout:** `parseClaudeStreamChunk` is shared with `usePortfolioChat` (called at `usePortfolioChat.ts:~755`). Adding `artifact_ready` to the parser is safe — `usePortfolioChat` does not handle `artifact_ready` chunks and its dispatch path treats them as a no-op. The analyst-view delta-spec (parked, separate PR) is the future surface that will consume `artifact_ready` there.

Tests:

- GatewayService maps full event.
- Parser preserves fields and rejects malformed required fields.
- `useResearchChat` calls `addMessageHtmlArtifact` only on `contract_name === "HtmlArtifact"` chunks.
- `useResearchChat` ignores typed-contract artifacts like `CriticalFactor` or `LpLetter`.
- `reconcileResearchTurn` carries `htmlArtifacts` through to the reconciled message.
- `addMessageHtmlArtifact` appends without overwriting existing entries.

## 7. PR-4 - research store and workspace tab

### Files

| File | Change |
|---|---|
| `frontend/packages/connectors/src/stores/researchStore.ts` | Add artifact tab type/data/actions (`openArtifactWorkbench`, `openArtifactTab`, `selectArtifactInTab`). |
| `frontend/packages/ui/src/components/research/ResearchWorkspace.tsx` | Add Workbench entry point and artifact tab branch. |
| `frontend/packages/ui/src/components/research/ConversationFeed.tsx` | Add inline artifact chip: render one chip per `metadata.htmlArtifacts` entry in the action-row area (line ~237, same as existing "Open in tab" tool-call chips). Each chip shows artifact title (or "Artifact" while sidecar loads) and an "Open" button; click dispatches `openArtifactTab({ artifactId, title?: string | null, ticker?: string | null })`. If title needs to be resolved from the sidecar (lazy load from `artifact_id`), render each chip as a child `HtmlArtifactChip` component rather than calling `useHtmlArtifact` inside the parent `.map` — hook ordering must not vary across renders. This is the only v1 artifact discovery surface during a session. |
| `frontend/packages/ui/src/components/research/ResearchTabBar.test.tsx` / phase tests | Add tab behavior coverage. |

### Store additions

```ts
export interface ArtifactTabData {
  mode: 'list' | 'single';
  ticker?: string | null;
  artifactId?: string | null;
}
```

Actions:

- `openArtifactWorkbench(ticker?: string | null)`
- `openArtifactTab({ artifactId, title, ticker })`
- `selectArtifactInTab(tabId, artifactId, title)`

Close behavior mirrors document tabs: remove the matching entry from `artifactTabs` and clear active tab to Explore if needed. Hydration clears `artifactTabs` just like `documentTabs`.

### Workspace UI

- Add a Workbench icon button in the research workspace action area.
- Add explicit `activeTab?.type === 'artifact'` rendering branch before the thread fallback.
- Workbench tab uses id `artifact-workbench:${ticker ?? 'all'}` and label `Workbench`.
- Single artifact tabs use id `artifact:${artifactId}` and label from sidecar title or `Artifact` until sidecar loads.

Tests:

- Workbench button opens list tab for active ticker.
- Single artifact tab opens and becomes active.
- Closing an artifact tab removes `artifactTabs[tabId]`.
- Hydrate clears artifact tabs.
- Unknown artifact tab data renders an error/empty state instead of falling through to ThreadTab.

## 8. PR-5 - renderer components and sandbox

### Files

| File | Change |
|---|---|
| `frontend/packages/ui/src/components/research/artifact/buildSandboxedDocument.ts` | New CSP/srcdoc builder. |
| `frontend/packages/ui/src/components/research/artifact/HtmlArtifactRenderer.tsx` | New single-artifact renderer. |
| `frontend/packages/ui/src/components/research/artifact/HtmlArtifactList.tsx` | New Workbench list. |
| `frontend/packages/ui/src/components/research/artifact/ArtifactTabContent.tsx` | New tab host. |
| `frontend/packages/ui/src/components/research/artifact/StaticExportsBar.tsx` | New static export controls. |
| Component tests | New focused tests. |

### Rendering contract

- `HtmlArtifactRenderer` accepts `artifactId`.
- It calls `useHtmlArtifact(artifactId)`.
- It renders loading, empty, deleted/404, error + retry, and ready states.
- Ready state renders:
  - concise metadata header
  - `<iframe key={sidecar.artifact_id} srcDoc={buildSandboxedDocument(htmlContent)} sandbox="allow-scripts" title={sidecar.title} />`
  - `StaticExportsBar` when exports exist

`buildSandboxedDocument`:

- Strips agent-supplied outer `<html>`, `<head>`, and `<body>` wrappers when present.
- Injects a default-deny meta CSP matching the spec.
- Does not inject any bridge script.
- Does not use `dangerouslySetInnerHTML` outside `iframe.srcDoc`.

`StaticExportsBar`:

- Renders 0–3 clipboard buttons depending on which `StaticExports` fields are non-null: "Copy as prompt", "Copy as markdown", "Copy as JSON".
- Reads from `sidecar.exports` — static values captured at emit time, NOT fetched from inside the iframe.
- No dynamic calls into the iframe. No link/download controls.
- Uses existing button/icon patterns and compact labels/tooltips.

Tests:

- `key={artifact_id}` is present on iframe.
- `sandbox` is exactly `allow-scripts`.
- No `window.addEventListener('message', ...)` exists in renderer files.
- CSP meta is present in srcdoc.
- Long titles/summaries wrap without overflowing.
- List empty/loading/error/ready states.

## 9. PR-6 - integration, docs, and live checklist

Integration tests:

- Mock `artifact_ready` SSE through GatewayService -> parser -> `useResearchChat`.
- Assert message chip appears for current assistant message.
- Click chip -> opens single artifact tab.
- Workbench button -> list view -> select artifact -> single renderer.
- Mock sidecar/content fetches; no live upstream required.
- Assert `htmlArtifacts` metadata survives `reconcileResearchTurn` — chip still present after stream-completion reconcile replaces optimistic message with server version.
- Assert non-OK content fetch (e.g., 404, 500) enters the renderer error state instead of rendering the error response body inside the iframe.

Docs/status updates:

- Update `docs/TODO.md` F122 to implemented only after PR-6 passes.
- Update `docs/reference/VISUALIZATION_STACK.md` to remove references to the archived AI-excel impl plan as active.
- Keep AI-excel analyst-view delta parked until shared infra is merged.

Live checklist after AI-excel foundation ships:

1. Start local risk_module and AI-excel-addin gateway.
2. Run a skill that emits `HtmlArtifact`.
3. Confirm `/api/html-artifacts` list returns the new artifact.
4. Confirm research chat receives `artifact_ready` with `contract_name="HtmlArtifact"`.
5. Confirm inline chip opens an artifact tab.
6. Reload the page and confirm chip disappears but Workbench recovers the artifact.
7. Confirm no console CSP/postMessage errors and no parent message listener.

## 10. Done criteria

F122 is done when:

- Dedicated risk_module proxy works with signed claim headers.
- HTML artifact hooks fetch list/sidecar/content with explicit non-2xx errors.
- HTML `artifact_ready` events flow through all five frontend layers.
- Conversation chips are client-session-only and contract-filtered.
- Workbench recovery path works after reload.
- Renderer uses sandboxed srcdoc, default-deny CSP, no `postMessage`, no dynamic iframe bridge.
- Mocked integration tests pass in risk_module before upstream live availability.
- Live E2E passes after AI-excel-addin gateway-side foundation ships.
