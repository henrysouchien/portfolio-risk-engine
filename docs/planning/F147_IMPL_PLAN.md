# F147 — `THESIS_ARTIFACT_REGISTRY` Implementation Plan

**Status:** UMBRELLA DRAFT R4 — superseded for PR-0 and PR-1 by the CODEX PASS per-PR plans.
**Created:** 2026-05-25. **Revised:** 2026-05-25 (R3 → R4).

**R3 → R4 changelog:**
- **B1 (triple invalidation API incomplete):** Module-level store API extended with `publishStreamComplete(ticker)` + `publishToolResponse(toolName, ticker, response)` + matching subscribe methods. Parser publishes via these. Chassis-side tool_result surfacing also extended — see new sub-scope B.2 (small chassis change to surface `tool_name` + `tool_input` on `tool_result` events, not just `sources`). Required for `apply_patch_ops` detection.
- **B2 (old language remains in §2 path distribution + §6):** Swept. §2 path-distribution row updated to "useThesis invalidates on stream-complete + apply_patch_ops + (opportunistic) artifact_ready". §6 PR-3-6 differentials updated likewise.
- **B3 (aggregate key contamination):** Module-level store aggregate index keyed by `(ticker, view_model_id)` (not view_model_id alone). `getLatestAggregate` + `subscribeToAggregate` take both args. Verified ticker is in shipped `AggregateReadyEvent` shape.
- **B4 (parser/store API contradiction):** §3.2.D corrected — parser calls module-level `publishArtifactReady` / `publishAggregateReady` (not `useArtifactEventStore.publish`).
- **B5 (PR-2 ready branch ignores sidecar):** Ready branch updated to PREFER sidecar `differentiated_view_claims` when present; falls back to `thesis.differentiated_view`. Same pattern for `assumptions` + `monitoring_watch_items` (already correct in R3).
- **NB1:** Added tests to PR-0 §3.3 — stream-complete propagation, apply_patch_ops invalidation, ticker-scoped aggregate keys, module-level publish API, duplicate-publisher prevention.
- **NB2:** §8.1 cross-repo updated — only 3 `useArtifactReady` subscriptions remain (critical-factors, quantifying-risk, position_card_full sources). Other 13 cards listed under "stream-complete + apply_patch_ops invalidation" not "skill artifact emission verification."
- **NB3:** PR-12 tests expanded — concrete fixture names, explicit branch + render assertions per test.

**R2 → R3 changelog:**
- **B1 (Thesis-only invalidation invalid — non-contract skills don't emit `artifact_ready`):** REFRAMED. `useThesis` invalidation moves to TWO signals: (a) **stream-complete** — when a chat SSE turn finishes, refetch Thesis for the active ticker; (b) **`tool_execute_response` for `apply_patch_ops`** — fine-grained invalidation when the agent applies patches. Both are observable in the existing chat event stream regardless of whether the calling skill has `typed_outputs_contract`. Covers all 15 Thesis-only cards. `useArtifactReady` events stay as an additional invalidation source for the 3 sidecar cards.
- **B2 (event store design inconsistent — parser called hook):** Reframed. Module-level singleton store + React `useArtifactEventStore()` hook wrapper. Parser (`chatStreamPayloads.ts`) publishes to the module-level store directly (no hook call). Aggregate events get a separate index keyed by `view_model_id` (the only field they share).
- **B3 (PR-2 sidecar mapping wrong fields):** Fixed. Actual `critical-factors` typed_outputs verified at `critical-factors.md:238`: `materiality` (not `materiality_threshold`), `differentiated_view_claims` (not `differentiated_view`), `assumptions`, `monitoring_watch_items`. PR-2 builder code updated accordingly.
- **B4 (aggregate PRs lack detail):** Added PR-2-level detail to PR-11, PR-12, PR-13 — file diff manifest, builder branch logic, test list (12+ per aggregate), acceptance criteria.
- **B5 (spec/impl plan conflict on `useArtifactReady` rows):** Added explicit override notes per affected row in §6/§7, naming the impl plan as authoritative for the 13 reframed cards. Spec stays as architectural source; impl plan supersedes its `useArtifactReady` claims for cards whose source skill lacks `typed_outputs_contract`.
- **NB1:** Swept PR count drift — "15 PRs" consistent throughout; §9 DoD updated.
- **NB2:** Confirmed paths — `usePortfolioChat.ts` lives at `features/external/hooks/usePortfolioChat.ts` (not `features/portfolio/`); scoped file list corrected.
- **NB3:** Added event-store tests to PR-0 §3.3 — publish/subscribe, latest ordering, artifact dedupe, aggregate index, duplicate-publisher prevention.

**R1 → R2 changelog:**
- **B1 (most cards lack `typed_outputs_contract`):** Verified — only 4 skills emit sidecars via materializer (critical-factors, quantifying-risk, earnings-scenarios, ir-composer). Path (A) chosen: 3 cards use `useArtifactReady` (critical-factors, quantifying-risk, position_card_full aggregate); 15 cards use pure `useThesis(ticker)` read. `useThesis` refreshes on coarse signal: any `artifact_ready` event for the ticker invalidates the cache. The 13 reframed cards still render the same typed Thesis data — their source skills DO write to Thesis via patch ops; we just don't get a per-skill push notification. Cross-repo sidecar contract work for those skills is OUT OF F147 v1 scope (v1.1+ optimization).
- **B2 (no event distribution mechanism):** PR-0 sub-scope C now ships a connector-level **artifact event store** (`useArtifactEventStore`) with pub/sub. Chat hooks (`useResearchChat`, `usePortfolioChat`) publish to the store on `artifact_ready` / `aggregate_ready` events. `useArtifactReady` and `useThesis` subscribe.
- **B3 (path drift):** Corrected paths — `chatStreamPayloads.ts` is at `frontend/packages/connectors/src/features/external/chatStreamPayloads.ts`. `sign(hmac_key: str)` signature confirmed (str, not bytes) — `sign_user_claim_headers` wrapper matches.
- **B4 (fetch race):** `useArtifactReady` now fetches sidecar by event's `artifact_id` (not `/latest`) when reacting to an event. `/latest` only used for initial mount without prior event.
- **B5 (PR-2 builder logic bug):** Reordered branches — check `loading` → `error` → `partial` (artifact without materiality) → `ready` (both present) → `empty`. Ready state now maps sidecar `typed_outputs` to component props explicitly.
- **B6 (aggregates not actionable as batch):** Split aggregates from PR-10 into PR-11 (consultation_summary), PR-12 (review_card), PR-13 (position_card_full). PR-10 keeps Tier 2 batch 3 single-source entries (risk_review + managing_risk). Total PRs: 13.
- **NB1:** PR-1 import compatibility note — `ArtifactDescriptor` re-exported from `index.ts` so existing `registry.ts` consumers don't break.
- **NB2:** Block-library extensions named explicitly per PR — severity chips, citation chips, etc.
- **NB3:** PR-0 tests expanded to cover fetch-by-id, dedupe, and out-of-order events.
- **NB4:** PR-8 and PR-9 split into 2 entries each (PR-8a/8b, PR-9a/9b). Total PRs: 15 (was 11).
**Owner:** Henry.
**Spec:** `docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md` (CODEX PASS round 7, 2026-05-25).
**Per CLAUDE.md plan-first workflow:** this impl plan is reviewed by Codex before any code lands; PR-0 implementation is via Codex per the prompts in §3 once Codex PASSes this doc.

**Implementation authority note (2026-05-26):** use `docs/planning/F147_PR0_IMPL_PLAN.md` for PR-0 and `docs/planning/F147_PR1_IMPL_PLAN.md` for PR-1. Both per-PR plans passed Codex review after this umbrella draft; their file manifests, acceptance gates, and prompts supersede the PR-0/PR-1 details below.

**What this doc does:** turns the F147 spec into actionable per-PR Codex prompts. The spec defined architecture + 18 entries; this impl plan defines the file diffs, function signatures, test names, and acceptance gates for each PR.

**Scope policy:** PR-0 and PR-1 are detailed in full (they ship the foundation + can run in parallel). PR-2 is detailed in full as the **vertical-slice template**. PR-3 through PR-10 are stubbed with per-entry differentials only — they follow PR-2's template byte-for-byte with entry-specific swaps.

---

## 1. Companion docs (all CODEX PASS)

- **Spec:** `docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md` (R7 PASS) — architecture, 18 entries, design decisions
- **Principles:** `docs/standards/INVESTMENT_VISUAL_LAYER_PRINCIPLES.md` — visual-decision authority
- **Stack reference:** `docs/reference/VISUALIZATION_STACK.md` — patterns + plan inventory
- **Audit:** `docs/planning/SKILL_ARTIFACT_VISUAL_MATRIX.md` — F150 deliverable; defined this scope
- **Cross-repo:** `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` — skill → typed contract authority

---

## 2. PR sequence overview

| PR | Scope | Path | Foundation? | Ships parallel? |
|---|---|---|---|---|
| PR-0 | Data substrate (chassis events + artifact event store + `useThesis` + `useArtifactReady` + `/api/artifacts/*` proxy + `sign_user_claim_headers`) | — | Yes | ✓ with PR-1 |
| PR-1 | Foundation types + thesis-side scaffolding | — | Yes | ✓ with PR-0 |
| PR-1b | Overview migration to `BuilderResult` (deferred) | — | No | After v1 |
| PR-2 | Thin slice — `thesis.critical_factors_card` end-to-end | Sidecar (`useArtifactReady`) | TEMPLATE | Blocked on PR-0+PR-1 |
| PR-3 | `thesis.articulation_card` | **Thesis-only** (`useThesis`) | No | After PR-2 |
| PR-4 | `thesis.position_initiation_card` | **Thesis-only** | No | After PR-2 |
| PR-5 | `thesis.earnings_review_card` | **Thesis-only** | No | After PR-2 |
| PR-6 | `thesis.build_model_card` | **Thesis-only** | No | After PR-2 |
| PR-8a | `thesis.competitive_position_card` + `thesis.comparative_analysis_card` | **Thesis-only** | No | After PR-2 |
| PR-8b | `thesis.dcf_relative_valuation_card` + `thesis.business_quality_card` | **Thesis-only** | No | After PR-2 |
| PR-9a | `thesis.financial_red_flags_card` + `thesis.forecast_assumptions_card` | **Thesis-only** | No | After PR-2 |
| PR-9b | `thesis.identifying_risk_card` + `thesis.quantifying_risk_card` | Mix (id'risk Thesis-only; q'risk sidecar) | No | After PR-2 |
| PR-10 | `thesis.risk_review_card` + `thesis.managing_risk_card` | **Thesis-only** | No | After PR-9b |
| PR-11 | `thesis.consultation_summary` (aggregate) | **Thesis-only** (multi-section composite) | No | After PR-3 |
| PR-12 | `thesis.review_card` (aggregate) | **Thesis-only** (ThesisScorecard from Thesis) | No | After PR-2 |
| PR-13 | `thesis.position_card_full` (aggregate) | Sidecar (`useArtifactReady` for both critical-factors + quantifying-risk) | No | After PR-2 + PR-9b |

**Total: 15 PRs.** Increased from 11 per R1 NB4 (Tier-2 batches split) + R1 B6 (aggregates split).

**Path distribution:**
- **Sidecar (`useArtifactReady`, 3 cards):** critical_factors, quantifying_risk, position_card_full
- **Thesis-only (15 cards):** all others. `useThesis(ticker)` invalidates on (a) **stream-complete** for the active ticker, (b) **`tool_execute_response`** for `apply_patch_ops`, (c) opportunistic `artifact_ready` for ticker. Triple-signal because non-contract skills don't emit `artifact_ready` — but they DO complete the SSE turn and they DO trigger `apply_patch_ops` tool responses.

---

## 3. PR-0 — Data substrate

**Goal:** unlock F147 entries by providing the Thesis + artifact-event data plumbing on the frontend. Spec §10 PR-0.

### 3.1 Sub-scope manifest

| Sub-scope | What ships | Repo |
|---|---|---|
| A.1 | Use existing `/api/research/content/*` proxy for Thesis fetch (NO new backend route) | risk_module (no change) |
| A.2 | NEW `routes/artifacts_proxy.py` at `/api/artifacts/*` (3 endpoints) + new `sign_user_claim_headers` helper wrapping existing `sign(hmac_key: str, ...)` | risk_module |
| B | Chassis `ClaudeStreamChunk` union + `GatewayService.mapEvent` extensions for `artifact_ready` + `aggregate_ready` | risk_module (`packages/chassis`) |
| **C.1** | **NEW** connector-level artifact event store (`useArtifactEventStore`) with pub/sub (per R1 B2) | risk_module (`packages/connectors`) |
| C.2 | Connector hooks `useThesis(ticker)` + `useArtifactReady(skillName, ticker)` consume the event store | risk_module (`packages/connectors`) |
| D | `chatStreamPayloads.ts` (at `features/external/chatStreamPayloads.ts` — corrected per R1 B3) typed branches publish to event store | risk_module (`packages/connectors`) |
| E | SSE integration test (acceptance gate) | risk_module |

### 3.2 File diffs

**Sub-scope A.2 — Backend artifact-fetch proxy (NEW)**

| File | Action | Description |
|---|---|---|
| `utils/agent_claim.py` | EXTEND | Add `sign_user_claim_headers(hmac_key: str, *, audience: str = 'agent_api_v1', user_id: str, user_email: str, ttl_seconds: int = 600) -> dict[str, str]`. Wraps existing `sign(hmac_key: str, ...)` primitive — signature confirmed `str` per R1 B3 cross-check at `utils/agent_claim.py:37`. Produces 7-header dict (`X-Agent-Claim-User-Id`, `X-Agent-Claim-User-Email`, `X-Agent-Claim-Audience`, `X-Agent-Claim-Issued-At`, `X-Agent-Claim-Expiry`, `X-Agent-Claim-Nonce`, `X-Agent-Claim-Signature`). Audience hardcoded to `agent_api_v1`. |
| `routes/artifacts_proxy.py` | NEW | FastAPI router mounted at `/api/artifacts` with 3 handlers:<br>- `GET /{ticker}` → list artifacts for ticker<br>- `GET /{ticker}/{skill}/latest` → latest artifact for (ticker, skill)<br>- `GET /{ticker}/{skill}/{artifact_id}` → specific artifact by id<br>Each proxies to AI-excel-addin `/api/artifacts/*` using `sign_user_claim_headers` for auth. Per-user rate limits: 60/min list, 120/min content (mirrors F122 convention). Structured logging on each request. |
| `app.py` (or wherever FastAPI app is assembled) | EXTEND | Register `artifacts_proxy.router` |

**Sub-scope B — Chassis event typing (extend shipped chassis)**

| File | Action | Description |
|---|---|---|
| `frontend/packages/chassis/src/services/ClaudeStreamTypes.ts` | EXTEND | Add `ArtifactReadyChunk` + `AggregateReadyChunk` variants to `ClaudeStreamChunk` discriminated union. Field shapes mirror `AI-excel-addin/packages/agent-gateway/agent_gateway/events.py:49` exactly: `{ type: 'artifact_ready', skill_run_id: string, ticker: string, skill: string, artifact_id: string, artifact_path: string, binary_artifact_path: string \| null, contract_name: string, data_source: 'live' \| 'fixture', ts: number }`. Aggregate shape per `events.py:72`: `{ type: 'aggregate_ready', view_model_id: string, ... }`. |
| `frontend/packages/chassis/src/services/GatewayService.ts:437` | EXTEND | Add typed branches to `mapEvent` switch for `'artifact_ready'` and `'aggregate_ready'` raw event types. Returns the new typed `ClaudeStreamChunk` variants. Today these return `null` (events dropped). |

**Sub-scope C.1 — Artifact event store (NEW per R1 B2, REFRAMED per R2 B2)**

Module-level singleton store + React hook wrapper. Parser publishes to the module-level store DIRECTLY (no hook call from a parser). Hook wrapper subscribes via `useSyncExternalStore` for components/hooks that need reactive updates.

| File | Action | Description |
|---|---|---|
| `frontend/packages/connectors/src/features/artifacts/artifactEventStore.ts` | NEW | **Module-level singleton.** Exports: `publishArtifactReady(chunk)`, `publishAggregateReady(chunk)`, `publishStreamComplete(ticker)`, `publishToolResponse(toolName, ticker, response)`, `getLatestArtifact(ticker, skill, artifact_id?)`, `getLatestAggregate(ticker, view_model_id)`, `subscribe(listener)`, `subscribeToTicker(ticker, listener)`, `subscribeToToolResponse(toolName, listener)`, `subscribeToStreamComplete(ticker, listener)`, `subscribeToAggregate(ticker, view_model_id, listener)`. Internal state: `artifactsByTickerSkill: Map<(ticker, skill), ArtifactReadyChunk[]>` (latest = head), `aggregatesByTickerViewModel: Map<(ticker, view_model_id), AggregateReadyChunk>` — **keyed by tuple to prevent cross-ticker contamination per R3 B3** (aggregate event shape has both fields per `events.py:69`). Notifies subscribers on publish. |
| `frontend/packages/connectors/src/features/artifacts/useArtifactEventStore.ts` | NEW | **React hook wrapper** around the module-level store. Exports `useArtifactEventStore()` returning `{ getLatestArtifact, getLatestAggregate, subscribeToTicker, subscribeToToolResponse }` (read-only — components don't publish). Uses `useSyncExternalStore` for React 18 concurrent-safe reads. |
| `frontend/packages/connectors/src/features/external/chatStreamPayloads.ts` | EXTEND | When parsing `artifact_ready` / `aggregate_ready` chunks, call MODULE-LEVEL `publishArtifactReady(chunk)` / `publishAggregateReady(chunk)`. **Never call the hook here.** |
| `frontend/packages/connectors/src/features/external/hooks/useResearchChat.ts` (existing) | EXTEND | Stream-complete signal (`onTurnEnd` callback or equivalent) publishes a `stream_complete` event to the store (`publishStreamComplete(ticker)`); `useThesis` subscribes via `subscribeToTicker`. Verified at `useResearchChat.ts:98`. Plus: forward `tool_execute_response` events to the store via `publishToolResponse(name, response)` so `useThesis` can subscribe to `apply_patch_ops` responses. |
| `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts` (verified existing — `features/external/hooks/`) | EXTEND | Same publisher behavior for portfolio-channel chat. |

**Sub-scope C.2 — Hooks (NEW)**

| File | Action | Description |
|---|---|---|
| `frontend/packages/connectors/src/features/thesis/useThesis.ts` | NEW | `useThesis(ticker): { data: ThesisSnapshot \| null; loading: boolean; error: Error \| null }`. Fires `GET /api/research/content/theses?ticker={ticker}` (list sorted by `updated_at DESC` per `AI-excel-addin/api/research/repository.py:2198`), takes first item to get `research_file_id`, then `GET /api/research/content/theses/{research_file_id}`. SWR-style caching by ticker. **Invalidation triggers (per R2 B1 — non-contract skills don't emit `artifact_ready`, so we need invalidation signals that fire for ALL skill writes):** (1) **Stream-complete** — when the active chat SSE turn finishes (`useResearchChat` / `usePortfolioChat` signal), refetch Thesis for the active ticker. Covers any skill that writes during the turn. (2) **`tool_execute_response` for `apply_patch_ops`** — fine-grained: when the agent applies patch ops via the MCP tool, invalidate immediately. (3) **`artifact_ready` for ticker** — opportunistic; covers the 3 sidecar-backed skills with no extra cost. Use any-of-the-above as invalidation signals; debounce 200ms to coalesce successive triggers. |
| `frontend/packages/connectors/src/features/thesis/types.ts` | NEW | TS type for `ThesisSnapshot` matching `AI-excel-addin/schema/thesis.py:386-425` shape. |
| `frontend/packages/connectors/src/features/artifacts/useArtifactReady.ts` | NEW | `useArtifactReady(skillName, ticker): { sidecar: ArtifactSidecarPayload \| null; event: ArtifactReadyChunk \| null; loading: boolean; error: Error \| null }`. Subscribes to `useArtifactEventStore` for `(skillName, ticker)` matches. On each event, fetches sidecar via `GET /api/artifacts/{ticker}/{skillName}/{event.artifact_id}` (per R1 B4 — fetch by event's `artifact_id`, NOT `/latest`, to avoid race on rapid successive events). Initial mount with no prior event: fetches `/api/artifacts/{ticker}/{skillName}/latest` once. Cache by `(skillName, ticker, artifact_id)`. **Only 3 v1 entries** use this: critical-factors, quantifying-risk, position_card_full aggregate. The other 15 entries use `useThesis` only. |

**Sub-scope D — Payload parsing (corrected path per R1 B3)**

| File | Action | Description |
|---|---|---|
| `frontend/packages/connectors/src/features/external/chatStreamPayloads.ts` | EXTEND | Add typed branches for `artifact_ready` + `aggregate_ready` chunks. Each branch calls **module-level** `publishArtifactReady(chunk)` / `publishAggregateReady(chunk)` from `artifactEventStore.ts`. **Never invoke the React hook from the parser** — module-level functions only. Also extend the existing `tool_result` parser to surface `tool_name` + `tool_input` + `result` (today only `sources` is extracted per `chatStreamPayloads.ts:47`) — needed for `apply_patch_ops` detection downstream. New PR-0 sub-scope B.2 covers the chassis-side change at `GatewayService.ts:447` to include these fields. No unhandled-event warnings. |

### 3.3 Test cases

| Test name | File | Sub-scope |
|---|---|---|
| `test_sign_user_claim_headers_produces_7_headers` | `tests/utils/test_agent_claim.py` | A.2 |
| `test_sign_user_claim_headers_audience_is_agent_api_v1` | same | A.2 |
| `test_artifacts_proxy_list_endpoint` | `tests/routes/test_artifacts_proxy.py` | A.2 |
| `test_artifacts_proxy_latest_endpoint` | same | A.2 |
| `test_artifacts_proxy_by_id_endpoint` | same | A.2 |
| `test_artifacts_proxy_rate_limit_enforced` | same | A.2 |
| `test_artifacts_proxy_requires_signed_claim` | same | A.2 |
| `test_chassis_artifact_ready_chunk_parsed` | `frontend/packages/chassis/tests/services/GatewayService.test.ts` | B |
| `test_chassis_aggregate_ready_chunk_parsed` | same | B |
| `test_chassis_unhandled_event_returns_null_unchanged` | same | B |
| `test_useThesis_fetches_latest_thesis_for_ticker` | `frontend/packages/connectors/tests/features/thesis/useThesis.test.ts` | C |
| `test_useThesis_returns_null_when_no_thesis_exists` | same | C |
| `test_useThesis_refetches_on_artifact_ready_event` | same | C |
| `test_useArtifactReady_fetches_sidecar_on_event` | `frontend/packages/connectors/tests/features/artifacts/useArtifactReady.test.ts` | C |
| `test_useArtifactReady_caches_by_artifact_id` | same | C |
| `test_chatStreamPayloads_handles_artifact_ready` | `frontend/packages/connectors/tests/chatStreamPayloads.test.ts` | D |
| **`test_sse_integration_full_chain`** | `frontend/packages/connectors/tests/integration/sse-chain.test.ts` | **E — acceptance gate** |

The integration test (last row) is the PR-0 acceptance gate. Per spec §9.5:
1. Send synthetic SSE event `{ type: 'artifact_ready', skill_run_id, ticker: 'PCTY', skill: 'critical-factors', artifact_id, artifact_path, binary_artifact_path: null, contract_name: 'CriticalFactors', data_source: 'fixture', ts }`
2. Assert `GatewayService.mapEvent` returns typed `ArtifactReadyChunk` (not null)
3. Assert `chatStreamPayloads.ts` routes the chunk (no warning)
4. Assert `useArtifactReady('critical-factors', 'PCTY')` hook returns sidecar payload
5. Assert downstream component re-renders with new payload (use a minimal test consumer)
6. Repeat for `aggregate_ready` variant

### 3.4 Acceptance criteria

PR-0 ships when ALL of the following pass:

1. ✓ `routes/artifacts_proxy.py` registered; 3 endpoints respond with proxied data
2. ✓ `sign_user_claim_headers` helper emits 7 correctly-keyed headers; signature verifies upstream
3. ✓ Chassis `ClaudeStreamChunk` union includes both new variants; `mapEvent` returns them (no longer null)
4. ✓ `useThesis(ticker)` returns non-null `ThesisSnapshot` for a real ticker with shipped Thesis
5. ✓ `useArtifactReady` returns fetched sidecar payload + event metadata
6. ✓ All 17 test cases pass; SSE integration test (acceptance gate) passes
7. ✓ No regression in existing diligence rendering paths (existing tests still pass)
8. ✓ No unhandled-event console warnings during normal operation

### 3.5 PR-0 Codex prompt

When dispatching PR-0 to Codex via `mcp__codex__codex`:

```
Implement PR-0 for F147 THESIS_ARTIFACT_REGISTRY per the impl plan at:
docs/planning/F147_IMPL_PLAN.md §3

The data substrate that unblocks all subsequent F147 PRs.

Sub-scopes:
A.1: NO new backend route — confirm /api/research/content/* already proxies the research/theses endpoints
A.2: NEW routes/artifacts_proxy.py + sign_user_claim_headers helper in utils/agent_claim.py
B: Extend chassis ClaudeStreamTypes + GatewayService.mapEvent
C: NEW useThesis + useArtifactReady hooks in packages/connectors
D: Extend chatStreamPayloads.ts
E: SSE integration test (acceptance gate)

Reference docs:
- Spec: docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md §10 PR-0
- Event shape: AI-excel-addin/packages/agent-gateway/agent_gateway/events.py:49
- Endpoint shape: AI-excel-addin/packages/agent-gateway/agent_gateway/server.py:1023
- Auth helper pattern: F122's sign_user_claim_headers approach
- Research theses endpoint: /api/research/content/theses?ticker={t} (existing proxy)

File diff manifest + 17 test cases in §3.2 / §3.3.
Acceptance criteria in §3.4.

Per CLAUDE.md Codex MCP conventions:
- approval-policy: "never"
- sandbox: "workspace-write" for impl, "danger-full-access" if commit needed
- cwd: /Users/henrychien/Documents/Jupyter/risk_module
- DO NOT pass model or config.model_reasoning_effort (inherit ~/.codex/config.toml)

Work sub-scope by sub-scope. Tests per sub-scope before moving on.
Cross-repo coordination: chassis + connectors + routes all in risk_module
this round; AI-excel-addin changes ZERO. Only risk_module proxies to
existing AI-excel-addin endpoints.

Report any blocker that requires AI-excel-addin changes — DO NOT
modify AI-excel-addin in this PR.
```

---

## 4. PR-1 — Foundation types + thesis scaffolding

**Goal:** ship the 3-generic `ArtifactDescriptor<C, P, R>`, `BuilderResult<P>` discriminated union, central lookup, and empty thesis-side scaffolding. **No behavior change** for overview entries. Ships parallel to PR-0 since it's substrate-independent.

### 4.1 File diffs

| File | Action | Description |
|---|---|---|
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/types.ts` | EXTEND | Add: `BuilderResult<Props>` discriminated union (`ready \| partial \| empty \| loading \| error` variants); `isRenderable<P>(result): bool` type guard; `RenderContext` interface; `ArtifactRenderer<P>` type. Widen `ArtifactDescriptor` to `<Context, Props, R = BuilderResult<Props>>` — `R` defaults to BuilderResult; overview specializes to `GeneratedArtifactProps \| null`. |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts` | EXTEND (type-only) | Update `OVERVIEW_ARTIFACT_REGISTRY` declaration to `ArtifactDescriptor<OverviewArtifactBuilderContext, GeneratedArtifactProps, GeneratedArtifactProps \| null>[]`. Builder functions unchanged. Same byte output. |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis-registry.ts` | NEW | Export empty `THESIS_ARTIFACT_REGISTRY: readonly ArtifactDescriptor<ThesisArtifactBuilderContext, unknown, BuilderResult<unknown>>[] = []`. Filled in PR-2+. |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis-dispatch.tsx` | NEW | Export empty `THESIS_RENDERER_DISPATCH: Record<string, ArtifactRenderer<any>> = {}` + `renderThesisArtifact(id, result, ctx)` function. Filled in PR-2+. |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/index.ts` | NEW | Export `AnyArtifactDescriptor = ArtifactDescriptor<any, any, any>`. Export `REGISTRIES` map (`{ overview: OVERVIEW_ARTIFACT_REGISTRY, thesis: THESIS_ARTIFACT_REGISTRY }`). Export `getArtifactDescriptor(id): AnyArtifactDescriptor \| null`. Export `getAllArtifactIds(): readonly string[]`. Export `propsOrNull<P>(result): P \| null` adapter with runtime guard. |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis/useThesisArtifactContext.ts` | NEW (skeleton) | Export `ThesisArtifactBuilderContext` interface (initial fields: `ticker`, `thesis`, `artifactReady`, `positions`, `loadingStates`). Export skeleton `useThesisArtifactContext(ticker: string)` returning the interface — fills out as entries land. |

### 4.2 Test cases

| Test name | File |
|---|---|
| `test_BuilderResult_type_guard_isRenderable_ready` | `artifacts/types.test.ts` |
| `test_BuilderResult_type_guard_isRenderable_partial` | same |
| `test_BuilderResult_type_guard_isRenderable_empty_returns_false` | same |
| `test_OVERVIEW_REGISTRY_compiles_with_widened_descriptor_type` | `artifacts/registry.test.ts` (existing — verify no regression) |
| `test_getArtifactDescriptor_returns_overview_concentration` | `artifacts/index.test.ts` |
| `test_getArtifactDescriptor_unknown_id_returns_null` | same |
| `test_getArtifactDescriptor_unknown_namespace_returns_null` | same |
| `test_getAllArtifactIds_includes_overview_ids` | same |
| `test_getAllArtifactIds_returns_empty_for_thesis_in_PR1` | same |
| `test_propsOrNull_passes_through_legacy_props` | same |
| `test_propsOrNull_returns_props_for_ready_BuilderResult` | same |
| `test_propsOrNull_returns_props_for_partial_BuilderResult` | same |
| `test_propsOrNull_returns_null_for_empty_loading_error` | same |
| `test_renderThesisArtifact_unknown_id_returns_null` | `artifacts/thesis-dispatch.test.tsx` |

### 4.3 Acceptance criteria

1. ✓ `OVERVIEW_ARTIFACT_REGISTRY` type-checks against the new 3-generic signature with `R = GeneratedArtifactProps | null`
2. ✓ All existing overview tests pass (no behavior change)
3. ✓ `getArtifactDescriptor('overview.concentration')` returns the existing descriptor
4. ✓ `propsOrNull` handles all variants correctly (5 variants + legacy null + legacy props)
5. ✓ `THESIS_ARTIFACT_REGISTRY` is empty array; `THESIS_RENDERER_DISPATCH` is empty map; downstream PRs add entries

### 4.4 PR-1 Codex prompt

```
Implement PR-1 for F147 THESIS_ARTIFACT_REGISTRY per the impl plan at:
docs/planning/F147_IMPL_PLAN.md §4

Foundation types + thesis-side scaffolding. No behavior change to
overview entries.

Scope: §4.1 file diff manifest (6 files: 2 EXTENDED, 4 NEW)
Tests: §4.2 (14 tests)
Acceptance: §4.3

Reference docs:
- Spec: docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md §3 (architecture)
- Current registry shape: frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts (73 lines, 7 overview entries)

Per CLAUDE.md Codex MCP conventions: approval-policy "never",
sandbox "workspace-write", cwd risk_module root.

Critical invariants:
- OVERVIEW_ARTIFACT_REGISTRY builders MUST NOT change behavior (only
  type signature widens). Same byte output for all 7 overview builders.
- THESIS_ARTIFACT_REGISTRY ships empty; PR-2 adds first entry.
- BuilderResult discriminated union must be the 5 variants listed
  in spec §3.3.

PR-1 ships parallel to PR-0; they touch different files and have no
mutual dependency.
```

---

## 5. PR-2 — Thin slice — `thesis.critical_factors_card`

**Goal:** prove the end-to-end template. Ships one Tier-1 entry with all the layers: builder + component + dispatch wiring + tests. Subsequent PR-3 through PR-10 follow this template byte-for-byte with entry-specific swaps.

### 5.1 Why this entry first

Per spec §10 PR-2 + R2 NB3:
- `critical-factors` skill has typed contract ALREADY SHIPPING via the position-card aggregate (`critical-factors → CriticalFactor[]` per `SKILL_CONTRACT_MAP.md`)
- Reduces first-PR risk: the contract + payload shape are already proven in production
- Standalone view extracts a subset of what position-card already renders

### 5.2 File diffs

| File | Action | Description |
|---|---|---|
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis/CriticalFactorsCard.tsx` | NEW | React component. Props: `{ result: BuilderResult<CriticalFactorsCardProps>; renderContext: RenderContext }`. Renders: materiality banner (from `Thesis.materiality`) + 4-pillar factor ranking table + paired-risk strip. Empty state: "Run `/critical-factors` to populate" affordance. Partial state: shows available pillars + skeleton for missing. Loading: skeleton. Error: error banner with retry. |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis/useThesisArtifactContext.ts` | EXTEND (from PR-1 skeleton) | Add `criticalFactorsArtifact: ArtifactSidecarPayload \| null` field; populate via `useArtifactReady('critical-factors', ticker)` in `useMemo`. |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis/builders.ts` | NEW | Export `buildCriticalFactorsResult(ctx: ThesisArtifactBuilderContext): BuilderResult<CriticalFactorsCardProps>`. Pure selector. Reads `ctx.thesis.materiality`, `ctx.thesis.differentiated_view`, `ctx.thesis.historical_coincidences`, `ctx.thesis.data_gaps`, `ctx.thesis.catalysts`, `ctx.thesis.risks`, `ctx.thesis.invalidation_triggers` + `ctx.criticalFactorsArtifact`. Returns `ready` when materiality + at least one factor exist; `partial` when artifact exists but Thesis materiality missing; `empty` otherwise. |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis-registry.ts` | EXTEND | Add `thesis.critical_factors_card` descriptor: `{ id, label: 'Critical Factors', builderRef: 'buildCriticalFactorsResult', requiresHooks: ['useThesis', 'useArtifactReady:critical-factors'], builder: buildCriticalFactorsResult }`. |
| `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis-dispatch.tsx` | EXTEND | Add `'thesis.critical_factors_card': (result, ctx) => <CriticalFactorsCard result={result} renderContext={ctx} />`. |

### 5.3 Component spec — `CriticalFactorsCard.tsx`

Reference visual: materiality banner (threshold + basis + rationale) → factor ranking table (claim × evidence × source-chips × verdict) → paired-risk strip (one row per invalidation_trigger paired with its risk).

Render priority — visual hierarchy per `INVESTMENT_VISUAL_LAYER_PRINCIPLES.md` §6:
1. **Materiality banner** — the "what matters" diagnosis at top. ~20px Instrument Sans for threshold; muted for basis/rationale.
2. **Factor ranking table** — `DataTable` (block primitive) with columns: factor name, evidence (citation chip), historical-coincidence indicator, severity badge.
3. **Paired-risk strip** — secondary panel with invalidation_trigger + paired risk in compact rows.

Reuses block-library primitives: `InsightBanner` for materiality, `DataTable` for factor ranking, `StatusCell` for severity, `PercentageBadge` for confidence (where applicable).

### 5.4 Builder spec — `buildCriticalFactorsResult`

**Branch order (corrected per R1 B5):** `loading` → `error` → `partial` (artifact present but Thesis missing materiality) → `ready` (both present) → `empty` (last). Without this order, an artifact-without-materiality case incorrectly falls through to `empty`.

**Contract fields verified per R2 B3** — actual `critical-factors` typed_outputs at `critical-factors.md:238`: `materiality`, `differentiated_view_claims`, `assumptions`, `monitoring_watch_items`. The earlier R2 code used wrong field names (`materiality_threshold`, `factor_ranking`, `evidence`) — fixed below.

```ts
import type { CriticalFactorsSidecar } from 'shared/types';

export interface CriticalFactorsCardProps {
  materiality: MaterialityThreshold;             // matches schema MaterialityThreshold
  differentiatedViewClaims: DifferentiatedViewClaim[];
  historicalCoincidences: HistoricalCoincidence[];
  catalysts: Catalyst[];
  assumptions: Assumption[];                      // from sidecar typed_outputs.assumptions
  monitoringWatchItems: MonitoringWatchItem[];   // from sidecar typed_outputs.monitoring_watch_items
  pairedRisks: Array<{ risk: Risk; trigger: InvalidationTrigger }>;
  sources: SourceRecord[];
}

export function buildCriticalFactorsResult(
  ctx: ThesisArtifactBuilderContext
): BuilderResult<CriticalFactorsCardProps> {
  const { thesis, criticalFactorsArtifact, loadingStates } = ctx;

  // 1. Loading
  if (loadingStates.thesis === 'loading' || loadingStates['critical-factors'] === 'loading') {
    return { status: 'loading', sources: ['thesis', 'critical-factors'] };
  }
  // 2. Error
  if (loadingStates.thesis === 'error') {
    return { status: 'error', reason: 'thesis-fetch-failed', sources: ['thesis'] };
  }
  // 3. Partial — artifact present but Thesis missing materiality (CHECK BEFORE empty)
  if (criticalFactorsArtifact && !thesis?.materiality) {
    return {
      status: 'partial',
      props: {
        // Populate from sidecar typed_outputs (verified field names)
        materiality: criticalFactorsArtifact.typed_outputs.materiality,
        differentiatedViewClaims: criticalFactorsArtifact.typed_outputs.differentiated_view_claims ?? [],
        historicalCoincidences: [],
        catalysts: [],
        assumptions: criticalFactorsArtifact.typed_outputs.assumptions ?? [],
        monitoringWatchItems: criticalFactorsArtifact.typed_outputs.monitoring_watch_items ?? [],
        pairedRisks: [],
        sources: [],
      },
      missingSources: ['Thesis.materiality', 'Thesis.risks', 'Thesis.invalidation_triggers'],
      reason: 'artifact-without-thesis-state',
    };
  }
  // 4. Ready — Thesis materiality + (sidecar OR Thesis-derived claims) present
  if (thesis?.materiality && (criticalFactorsArtifact || thesis.differentiated_view?.length)) {
    return {
      status: 'ready',
      props: {
        materiality: thesis.materiality,
        // Prefer sidecar when present (verified/typed source) per R3 B5; fallback to Thesis
        differentiatedViewClaims: criticalFactorsArtifact?.typed_outputs.differentiated_view_claims
          ?? thesis.differentiated_view ?? [],
        historicalCoincidences: thesis.historical_coincidences ?? [],
        catalysts: thesis.catalysts ?? [],
        assumptions: criticalFactorsArtifact?.typed_outputs.assumptions ?? thesis.assumptions ?? [],
        monitoringWatchItems: criticalFactorsArtifact?.typed_outputs.monitoring_watch_items
          ?? thesis.monitoring?.watch_list ?? [],
        pairedRisks: pairRisksWithTriggers(thesis.risks ?? [], thesis.invalidation_triggers ?? []),
        sources: thesis.sources ?? [],
      },
    };
  }
  // 5. Empty — last
  return {
    status: 'empty',
    reason: 'no-critical-factors-yet',
    affordance: { skillName: 'critical-factors', label: 'Run /critical-factors to populate' },
  };
}
```

### 5.5 Test cases

| Test name | File |
|---|---|
| `test_buildCriticalFactorsResult_ready_when_materiality_and_factors_present` | `artifacts/thesis/builders.test.ts` |
| `test_buildCriticalFactorsResult_partial_when_artifact_without_materiality` | same |
| `test_buildCriticalFactorsResult_empty_when_no_thesis` | same |
| `test_buildCriticalFactorsResult_empty_affordance_points_at_critical_factors_skill` | same |
| `test_buildCriticalFactorsResult_loading_when_thesis_loading` | same |
| `test_buildCriticalFactorsResult_error_when_thesis_fetch_failed` | same |
| `test_CriticalFactorsCard_renders_materiality_banner_when_ready` | `artifacts/thesis/CriticalFactorsCard.test.tsx` |
| `test_CriticalFactorsCard_renders_factor_ranking_table_when_ready` | same |
| `test_CriticalFactorsCard_renders_paired_risk_strip_when_ready` | same |
| `test_CriticalFactorsCard_renders_empty_affordance_when_empty` | same |
| `test_CriticalFactorsCard_renders_partial_skeleton_for_missing_materiality` | same |
| `test_CriticalFactorsCard_renders_loading_skeleton` | same |
| `test_CriticalFactorsCard_renders_error_banner` | same |
| `test_thesis_registry_contains_critical_factors_card` | `artifacts/thesis-registry.test.ts` |
| `test_renderThesisArtifact_dispatches_critical_factors_card` | `artifacts/thesis-dispatch.test.tsx` |
| `test_getArtifactDescriptor_returns_thesis_critical_factors_card` | `artifacts/index.test.ts` |

### 5.6 Acceptance criteria

1. ✓ Rendering `thesis.critical_factors_card` with a real ticker (e.g., PCTY) shows the materiality banner + factor ranking + paired-risk strip
2. ✓ All 5 `BuilderResult` variants render their respective UI states correctly
3. ✓ Empty state affordance correctly names `/critical-factors`
4. ✓ Partial state shows what's available with explicit missing-sources callout
5. ✓ All 16 tests pass
6. ✓ `getArtifactDescriptor('thesis.critical_factors_card')` returns the registered descriptor
7. ✓ `renderThesisArtifact('thesis.critical_factors_card', result, ctx)` returns the React element

### 5.7 PR-2 Codex prompt

```
Implement PR-2 for F147 — thin-slice end-to-end vertical for
thesis.critical_factors_card.

Impl plan: docs/planning/F147_IMPL_PLAN.md §5
Spec: docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md §4.0 (readiness),
      §4.1 (Tier 1 entry definition)
Critical-factors contract: AI-excel-addin/docs/SKILL_CONTRACT_MAP.md
  (verified shipped via shipped position-card aggregate)

File diffs: 5 files (1 NEW component, 1 EXTEND context, 1 NEW builder,
2 EXTEND registry+dispatch). See §5.2.

Builder logic: §5.4 (BuilderResult variants explicit)
Component visual: §5.3 (reuses block-library primitives)
Tests: §5.5 (16 tests)
Acceptance: §5.6

Per CLAUDE.md Codex MCP conventions: approval-policy "never",
sandbox "workspace-write", cwd risk_module root.

This is the TEMPLATE PR. Subsequent PR-3 through PR-10 follow this
shape byte-for-byte with entry-specific swaps. Get the shape right.

PR-2 depends on PR-0 (substrate hooks) + PR-1 (foundation types).
Both must be merged before PR-2 starts impl.
```

---

## 6. PR-3 through PR-6 — Tier 1 entries (differentials only)

Each follows the PR-2 template. **All four are Thesis-only path per R1 B1** — source skills don't have `typed_outputs_contract` frontmatter so the materializer doesn't produce sidecars. Builders consume `useThesis(ticker)` only. **Invalidation triple per R3 B1:** `useThesis` refreshes on stream-complete + `apply_patch_ops` tool-response + (opportunistic) `artifact_ready` for ticker. The first two signals fire for ALL skill writes regardless of typed contract status. Cards still render the same typed Thesis data — source skills DO write to Thesis via patch ops.

### 6.1 PR-3 — `thesis.articulation_card` (Thesis-only)

| Differential | Value |
|---|---|
| Visual owner skill | `thesis-articulation` (✓ built; writes patch ops to Thesis) |
| Thesis read fields | `thesis.*` (statement, direction, strategy, timeframe, conviction), `differentiated_view[]`, `catalysts[]` |
| Artifact subscription | **NONE** — pure Thesis read |
| Visual | Pitch card: thesis statement banner (top) + 4-pillar table (statement / variant / catalyst / risk) + dated catalyst timeline |
| Component file | `thesis/ArticulationCard.tsx` |
| Builder name | `buildArticulationResult` (in `thesis/builders.ts`) |
| Empty affordance | "Run `/thesis-articulation`" |
| Builder branches | loading → error → ready (when `thesis.thesis.statement` non-empty) → empty |

### 6.2 PR-4 — `thesis.position_initiation_card` (Thesis-only)

| Differential | Value |
|---|---|
| Visual owner skill | `position-initiation` (~ partial; Thesis-write paths exist) |
| Thesis read fields | `business_overview`, `qualitative_factors[]`, `risks[]`, `invalidation_triggers[]`, `materiality`, `differentiated_view[]`, `assumptions[]`, `monitoring.watch_list`, `catalysts[]`, `position_metadata` |
| Artifact subscription | **NONE** — pure Thesis read |
| Visual | Largest single-source card — full diligence across 5+ sections |
| Component file | `thesis/PositionInitiationCard.tsx` |
| Builder name | `buildPositionInitiationResult` |
| Empty affordance | "Run `/position-initiation`" |
| Builder branches | loading → error → partial (some sections present, others missing — composite renders available) → ready (all key sections present) → empty |

### 6.3 PR-5 — `thesis.earnings_review_card` (Thesis-only)

| Differential | Value |
|---|---|
| Visual owner skill | `earnings-review` (~ partial v3.2) |
| Thesis read fields | `quantitative_framing.eps_fcf`, `assumptions[]` (recent changes), `catalysts[]`, `consensus_view` |
| Artifact subscription | **NONE** — pure Thesis read |
| Visual | Quarter scorecard (top) + thesis-reconciliation diff (recent Thesis updates) |
| Component file | `thesis/EarningsReviewCard.tsx` |
| Builder name | `buildEarningsReviewResult` |
| Empty affordance | "Run `/earnings-review`" |
| Special note | Without sidecar, "proposed-ops list" (was based on sidecar payload) is dropped from v1 scope. Card renders the Thesis fields the skill writes; the verdict-block visual narrows to a Thesis-derived summary. v1.1 candidate: add `earnings-review` to typed_outputs_contract skills + restore proposed-ops view. |

### 6.4 PR-6 — `thesis.build_model_card` (Thesis-only)

| Differential | Value |
|---|---|
| Visual owner skill | `build-model` (✓ built) |
| Thesis read fields | `model_insights[]`, `price_target`, `model_ref` (all live in `Thesis` schema per `schema/thesis.py:424-425`) |
| Artifact subscription | **NONE** — pure Thesis read |
| Visual | Model summary: key drivers (from `model_insights[]`) + price target range/midpoint (from `price_target`) + executive summary + .xlsx download link (from `model_ref.path`) |
| Component file | `thesis/BuildModelCard.tsx` |
| Builder name | `buildBuildModelResult` |
| Empty affordance | "Run `/build-model`" |
| Builder branches | loading → error → partial (model_ref but no model_insights) → ready (both present) → empty |

---

## 7. PR-8 through PR-10 — Tier 2 single-source (differentials only)

Split into PR-8a/8b/9a/9b/10 per R1 NB4. Each PR ships 2 entries. All Thesis-only path except `thesis.quantifying_risk_card` (sidecar — typed_outputs_contract verified).

### 7.1 PR-8a — `competitive_position_card` + `comparative_analysis_card` (both Thesis-only)

- **`thesis.competitive_position_card`** — visual owner `competitive-position` (✓). Reads `industry_analysis.{landscape, macro_overlay, structural_trends, editorial_peer_set}`. Visual: 4-pillar scorecard + 10-attribute grid + section panels. Composite — partial-render rules apply per section.
- **`thesis.comparative_analysis_card`** — visual owner `comparative-analysis` (✓). Reads `industry_analysis.peer_comparison`. Visual: focal-vs-peers KPI matrix table + verdict banner.

### 7.2 PR-8b — `dcf_relative_valuation_card` + `business_quality_card` (both Thesis-only)

- **`thesis.dcf_relative_valuation_card`** — visual owner `dcf-relative-valuation` (✓). Reads `price_target` (Thesis-level) + `valuation`. Visual: 3-way valuation table + triangulation spread.
- **`thesis.business_quality_card`** — typical writer `position-initiation` composite + `business-quality-assessment` standalone (verify in impl plan per spec §4.0 — but card behavior unchanged either way; reads `qualitative_factors[]` category=business_quality from Thesis). Visual: quality-factors table.

### 7.3 PR-9a — `financial_red_flags_card` + `forecast_assumptions_card` (both Thesis-only)

- **`thesis.financial_red_flags_card`** — typical writers: `position-initiation` (qualitative_factors) + `financial-red-flags` standalone (risks/triggers). Reads `qualitative_factors[]` (category=financial_red_flags) + `risks[]` + `invalidation_triggers[]`. Visual: red-flag checklist + paired-risk rows. Partial-render rules per spec §4.0.
- **`thesis.forecast_assumptions_card`** — visual owner `forecast-assumptions` (~ ready). Reads `assumptions[]`. Visual: driver dictionary table + per-driver confidence.

### 7.4 PR-9b — `identifying_risk_card` + `quantifying_risk_card` (MIX — Thesis-only + sidecar)

- **`thesis.identifying_risk_card`** (Thesis-only) — visual owner `identifying-risk` (✓). Reads `risks[]`, `invalidation_triggers[]`, `data_gaps[]`. Visual: risk register table (4 pillars).
- **`thesis.quantifying_risk_card`** (sidecar) — visual owner `quantifying-risk` (✓). Subscribes via `useArtifactReady('quantifying-risk', ticker)` + reads `position_metadata.portfolio_fit` from Thesis. Visual: factor table (β / R² / window) + idio decomposition + classification banner. Uses the full BuilderResult pattern with sidecar mapping like PR-2.

### 7.5 PR-10 — `risk_review_card` + `managing_risk_card` (both Thesis-only)

- **`thesis.risk_review_card`** (Thesis-only) — visual owner `risk-review` (~ partial v2.1). Reads per-ticker `risks[]` + `invalidation_triggers[]` + `position_metadata.portfolio_fit`. Visual: per-ticker fingerprint table.
- **`thesis.managing_risk_card`** (Thesis-only — sizing display only per spec §4.0/§4.2). Reads `position_metadata.position_size`. Thin card. Affordance: `/position-initiation` or `/allocation-review` for populate.

---

## 7.5 PR-11 — `thesis.consultation_summary` (aggregate, Thesis-only)

Dedicated PR per R1 B6, fully detailed per R2 B4.

**Spec override (per R2 B5):** F147 spec §5.4 lists `useArtifactReady('thesis-consultation', ticker)` as part of the source roster. Impl plan supersedes: `thesis-consultation` lacks `typed_outputs_contract` so no `artifact_ready` event fires. Card uses pure Thesis read.

**Source roster:** live `useThesis(ticker)` only.

**Sections read:** `thesis.*` (statement, etc.), `differentiated_view[]`, `quantitative_framing`, `catalysts[]`, `risks[]`, `invalidation_triggers[]`, `position_metadata`, `business_overview`.

**File diffs:**

| File | Action | Description |
|---|---|---|
| `thesis/ConsultationSummary.tsx` | NEW | React component. Renders section-header strip for ~8 sections + per-section 1-line summary + last-updated indicator + expand affordance. Reuses `SectionHeader` + `MetricCard` block primitives. |
| `thesis/aggregates.ts` | NEW | Exports `buildConsultationSummaryResult(ctx): BuilderResult<ConsultationSummaryProps>`. |
| `thesis-registry.ts` | EXTEND | Add `thesis.consultation_summary` descriptor. |
| `thesis-dispatch.tsx` | EXTEND | Add dispatch entry. |

**Builder branches:**
- Loading → if Thesis fetch in flight
- Error → if Thesis fetch failed
- Empty → if no Thesis exists for ticker
- Partial → at least one section populated but `>2` core sections missing (composite — show available)
- Ready → ≥6 sections populated (full composite render)

**Tests (12):**
1. `test_buildConsultationSummary_loading_when_thesis_loading`
2. `test_buildConsultationSummary_error_when_thesis_error`
3. `test_buildConsultationSummary_empty_when_no_thesis`
4. `test_buildConsultationSummary_partial_with_minority_sections`
5. `test_buildConsultationSummary_ready_with_full_sections`
6. `test_ConsultationSummary_renders_section_strip`
7. `test_ConsultationSummary_renders_per_section_summary_line`
8. `test_ConsultationSummary_renders_partial_skeleton_for_missing`
9. `test_ConsultationSummary_renders_empty_affordance`
10. `test_ConsultationSummary_handles_expand_affordance_click`
11. `test_thesis_registry_contains_consultation_summary`
12. `test_renderThesisArtifact_dispatches_consultation_summary`

**Acceptance:**
1. ✓ All 12 tests pass
2. ✓ Rendering for a ticker with full Thesis shows all 8 sections
3. ✓ Partial state renders available sections, skeleton for missing
4. ✓ Empty state shows "Run `/thesis-consultation`" affordance

## 7.6 PR-12 — `thesis.review_card` (aggregate, Thesis-only)

Dedicated PR per R1 B6, fully detailed per R2 B4.

**Spec override (per R2 B5):** F147 spec §4.3 + §5.4 lists `useArtifactReady('thesis-review', ticker)` for `ThesisScorecard`. Impl plan supersedes: `thesis-review` lacks `typed_outputs_contract` so no sidecar. Card uses pure Thesis read for v1.

**Source roster:** live `useThesis(ticker)` only.

**Fields read:** `materiality`, `differentiated_view[]` (claims), `assumptions[]`, `risks[]`, `decisions_log` entries with `entry_type='review'` or similar (verify exact filter in impl).

**View-model:** scorecard table (claims × evidence × decisions_log verdict) + materiality context. The "proposed-ops list with diff preview" view is **dropped from v1 scope** (was based on sidecar) — v1.1 candidate when `thesis-review` gets a typed contract.

**File diffs:**

| File | Action | Description |
|---|---|---|
| `thesis/ReviewCard.tsx` | NEW | React component. Renders materiality banner + scorecard table (one row per claim) + decisions_log-derived verdict column. |
| `thesis/aggregates.ts` | EXTEND | Add `buildReviewResult(ctx): BuilderResult<ReviewCardProps>`. |
| `thesis-registry.ts` | EXTEND | Add `thesis.review_card` descriptor. |
| `thesis-dispatch.tsx` | EXTEND | Add dispatch entry. |

**Builder branches:**
- Loading → Thesis loading
- Error → Thesis fetch error
- Empty → no claims AND no decisions_log review entries
- Partial → claims exist but no verdicts yet (skill hasn't run)
- Ready → ≥1 claim with matching review verdict

**Tests (10):**
1-5: builder branch tests
6-9: component render tests (ready / partial / empty / error)
10: registry + dispatch wiring

**Acceptance:**
1. ✓ All 10 tests pass
2. ✓ Scorecard table renders correctly with claim × evidence × verdict
3. ✓ Verdict source = decisions_log entries (not artifact_ready sidecar)
4. ✓ Empty/partial states render correctly

## 7.7 PR-13 — `thesis.position_card_full` (aggregate, SIDECAR + Thesis)

Dedicated PR per R1 B6, fully detailed per R2 B4. **The most complex card** — full source-ownership rules per spec §5.5.

**Sources:**
- `useArtifactReady('critical-factors', ticker)` — thesis-drift summary (sidecar, ✓ has typed_outputs_contract)
- `useArtifactReady('quantifying-risk', ticker)` — sizing-vs-cap (sidecar, ✓ has typed_outputs_contract)
- Live `get_positions(format='agent')` — current weight
- `useThesis(ticker)` — `assumptions`, `price_target`, `materiality`

**Source ownership map (per spec §5.5):**

```ts
const SOURCE_OWNERSHIP = {
  'thesis_drift_summary': 'critical-factors-artifact',
  'sizing_vs_cap': 'quantifying-risk-artifact',
  'current_weight': 'live_get_positions',
  'top_assumptions': 'thesis.assumptions',
  'price_target_range': 'thesis.price_target',
  'materiality_threshold': 'thesis.materiality',
};
```

**Staleness:** per-source timestamps; >24h threshold for stale badge. Fallback rules per spec §5.5.

**Aggregate-ready emission:** publish `AggregateReadyChunk` to module-level event store on view-model rebuild. Use shallow-equality check on prior view-model to suppress no-op rebuilds.

**File diffs:**

| File | Action | Description |
|---|---|---|
| `thesis/PositionCardFull.tsx` | NEW | Component. Renders position card aggregate with source-ownership rules + provenance chips per row. |
| `thesis/aggregates.ts` | EXTEND | Add `buildPositionCardFullResult(ctx): BuilderResult<PositionCardFullProps>`. |
| `thesis/sourceOwnership.ts` | NEW | Export `SOURCE_OWNERSHIP` map + `resolveOwnedField<T>(concept, sources): { value, ownerSource, isStale }`. |
| `thesis-registry.ts` | EXTEND | Add `thesis.position_card_full` descriptor. |
| `thesis-dispatch.tsx` | EXTEND | Add dispatch entry. |

**Builder branches:**
- Loading → any source loading
- Error → any source error
- Empty → all sources missing
- Partial → some sources present (render with explicit missing-source affordances per concept)
- Ready → all sources present and fresh

**Tests (15):**
1-5: builder branches (loading / error / empty / partial / ready)
6-7: SOURCE_OWNERSHIP resolution (declared owner wins; secondary source ignored when owner present)
8-9: Staleness behavior (stale badge when owner >24h; explicit fallback when owner stale and secondary fresh)
10-11: Aggregate-ready emission (emits on view-model change; suppresses on shallow-equal rebuild)
12-13: Source-update propagation (changing each source triggers rebuild)
14-15: Registry + dispatch wiring

**Acceptance:**
1. ✓ All 15 tests pass
2. ✓ SOURCE_OWNERSHIP rules enforced — no double-rendering
3. ✓ Stale-source badge appears when owner >24h old
4. ✓ `aggregate_ready` event emitted on view-model rebuild only (not every render)
5. ✓ Partial state renders available concepts; missing concepts show "Run X" affordances

---

## 7.8 Spec override notes (R2 B5)

The F147 spec's `useArtifactReady` references in §4.3 + §5.4 are SUPERSEDED for non-contract skills per the typed_outputs_contract finding (only 4 skills have sidecars). This impl plan is authoritative for:

| Card | Spec says (§4.3 / §5.4) | Impl plan says |
|---|---|---|
| `thesis.earnings_review_card` | `useArtifactReady + useThesis` | `useThesis` only (earnings-review lacks contract) |
| `thesis.risk_review_card` | `useArtifactReady + useThesis` | `useThesis` only (risk-review lacks contract) |
| `thesis.review_card` (aggregate) | `useArtifactReady('thesis-review', ticker) + useThesis` | `useThesis` only (thesis-review lacks contract) |
| `thesis.consultation_summary` (aggregate) | `useThesis` (already correct) | unchanged |
| Other 12 reframed cards | Various spec wording | `useThesis` only |

Card behavior unchanged from spec — same Thesis fields read, same render shape. Only the invalidation/refresh mechanism differs (stream-complete + apply_patch_ops instead of artifact_ready). Visual fidelity preserved.

---

## 8. Cross-repo coordination

### 8.1 AI-excel-addin

**Verify in PR-0 impl (not change):**
- `/api/artifacts/{ticker}` endpoint exists and returns expected shape
- `/api/artifacts/{ticker}/{skill}/latest` endpoint exists
- `/api/artifacts/{ticker}/{skill}/{artifact_id}` endpoint exists
- `ArtifactReadyEvent` TS shape matches risk_module's new chassis types
- Skill artifact emission for `critical-factors`, `thesis-articulation`, `position-initiation`, `earnings-review`, `build-model`, `competitive-position`, `comparative-analysis`, `dcf-relative-valuation` (the 8 entries with `useArtifactReady` subscriptions)

**No AI-excel-addin code changes** expected in F147 v1.

### 8.2 risk_module

All code changes scoped to:
- `routes/` (PR-0 only)
- `utils/agent_claim.py` (PR-0 only)
- `frontend/packages/chassis/src/services/` (PR-0 only)
- `frontend/packages/connectors/src/features/` (PR-0 only)
- `frontend/packages/connectors/src/chatStreamPayloads.ts` (PR-0 only)
- `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/` (PR-1 through PR-10)
- `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/thesis/` (PR-2 through PR-10)
- Test files mirroring above

---

## 9. Definition of done (F147 v1)

Per spec §14 (updated for impl plan):

1. ✓ PR-0 through PR-13 merged (15 PRs: PR-0, PR-1, PR-2, PR-3, PR-4, PR-5, PR-6, PR-8a, PR-8b, PR-9a, PR-9b, PR-10, PR-11, PR-12, PR-13). PR-1b deferred. PR-7 placeholder unused.
2. ✓ All 18 thesis registry entries pass unit + aggregate integration tests
3. ✓ `getArtifactDescriptor(id)` returns correct descriptor for any `overview.*` or `thesis.*` ID
4. ✓ `renderThesisArtifact(id, result, ctx)` routes correctly for thesis namespace; overview continues via `renderOverviewArtifactEntry` (cross-namespace unified router deferred to PR-1b)
5. ✓ `BuilderResult<Props>` discriminated union renders correctly for all 5 variants
6. ✓ All 3 aggregates render correctly with full + partial source data; SOURCE_OWNERSHIP rules enforced
7. ✓ PR-0 substrate verified: `useThesis(ticker)` returns Thesis snapshots; `useArtifactReady(skill, ticker)` reflects SSE events + fetched sidecar; `chatStreamPayloads.ts` parses both events
8. ✓ Visual coverage metric: ≥41% canonical coverage (10 shipped overview + 18 thesis = 28 of ~69 audit entries)
9. ✓ F147 TODO entry moved to `TODO_COMPLETED.md`
10. ✓ v1.1 successor TODOs filed for advisor/plan/review namespaces
11. ✓ Matrix doc updated: shipped entries moved from "Recommended: Canonical" to "Canonical shipped"

---

## 10. Codex review brief (for this impl plan)

**Areas to challenge:**

1. **PR-0 sub-scope sequencing** — does Sub-scope A.2 (artifacts proxy) need to land before B (chassis types)? Or can they ship simultaneously? Verify file independence.
2. **`useArtifactReady` fetch trigger** — fires sidecar fetch on every event. For high-frequency skills, does this thrash? Should it debounce or rely on artifact_id stability for dedupe?
3. **PR-2 component visual** — `CriticalFactorsCard.tsx` reuses block primitives. Verify the block-library API surface actually supports the proposed layout (materiality banner + 4-pillar table + paired-risk strip).
4. **Test coverage gaps** — are 16 PR-2 tests sufficient, or are integration tests across (substrate → builder → render) needed beyond unit + the PR-0 SSE chain test?
5. **PR-3 through PR-6 differentials** — they're listed as table rows but lack the BuilderResult discrimination logic detail per entry. Should each PR get its own §5-style detailed spec, or is the template-with-differentials sufficient?
6. **PR-8 through PR-10 batching** — 4 entries per PR may be too many for review. Should we split into 1-entry-per-PR for Tier 2?
7. **Aggregate impl scope (PR-10)** — 3 aggregates in one PR is the heaviest single PR. SOURCE_OWNERSHIP rules add complexity. Should aggregates each get a dedicated PR?
8. **Block-library extensions** — F147 reuses `MetricCard`, `DataTable`, `InsightBanner`, `StatusCell`, etc. Are there extensions needed (e.g., a new chip type for citation chips on the comp matrix)? Identify in impl plan or defer to per-PR impl?

**Inputs available for local execution:**

- All spec docs (see §1)
- `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/` (live registry pattern)
- `frontend/packages/ui/src/components/blocks/` (block primitives — verify API surface)
- `frontend/packages/chassis/src/services/` (chassis to extend in PR-0)
- `frontend/packages/connectors/src/` (connectors to extend in PR-0)
- `AI-excel-addin/packages/agent-gateway/agent_gateway/server.py:1023` (artifact endpoints to proxy)
- `AI-excel-addin/packages/agent-gateway/agent_gateway/events.py:49` (event shape for chassis types)
- `AI-excel-addin/api/research/repository.py:2198` (research/theses endpoint behavior)

---

## 11. Open questions

1. **Block-library extensions needed?** — list per entry whether new primitives are required vs reusing existing.
2. **Visual regression infra** — Playwright is available; Chromatic unverified. Decision: ship with Playwright snapshots only; defer Chromatic if not available.
3. **Per-PR Codex prompts** — should every PR get a standalone Codex prompt (like §3.5, §4.4, §5.7) or just PR-0 through PR-2 with subsequent prompts derived?
4. **PR-1b scoping** — when does the overview migration land? After F147 v1 (target), but the impl plan stub is named only; needs its own impl plan doc.

---

## 12. References

- F147 spec: `docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md` (R7 PASS)
- Visualization stack: `docs/reference/VISUALIZATION_STACK.md`
- Principles: `docs/standards/INVESTMENT_VISUAL_LAYER_PRINCIPLES.md`
- Matrix audit: `docs/planning/SKILL_ARTIFACT_VISUAL_MATRIX.md`
- Cross-repo: `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md`
