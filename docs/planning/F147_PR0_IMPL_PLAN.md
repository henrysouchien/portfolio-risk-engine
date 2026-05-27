# F147 PR-0 — Data Substrate (Implementation Plan)

**Status:** CODEX PASS R7 — ready for implementation.
**Created:** 2026-05-25. **Revised:** 2026-05-26 (R6 → R7).

**R6 → R7 changelog:**
- **B1 (caller files not enumerated):** Added explicit caller-file entries to §3 file diff manifest — `AgentPanel.tsx`, `ExploreTab.tsx`, `ResearchWorkspace.tsx` (verified paths at `frontend/packages/ui/src/components/research/`). `useResearchChat` signature makes `ticker: string` REQUIRED (not optional). Acceptance criterion 13 added: no publisher reads `researchStore.activeFile`.
- **NB1/2 (test count headers stale + numbering):** Renumbered tests to consecutive 1-46. Section headers updated to actual counts.
- **NB3 (Codex prompt count drift "43 tests"):** Synced to "46 tests."
- **NB4 (B.2 wording stale):** Codex prompt B.2 wording updated to "only `tool_input` is new; `tool_name`/`result`/`error` already shipped; connector parser surfacing is the rest."

---

**R5 → R6 changelog:**

**R5 → R6 changelog:**
- **B1 (researchStore.activeFile global → wrong ticker on activeFile change mid-stream):** Reframed. Ticker is passed as a hook option (`useResearchChat({ ticker, researchFileId, ... })`) from the calling component (AgentPanel/ExploreTab), captured AT sendMessage START, and held in a ref so that activeFile changes during the stream don't shift it. Publishers reference the captured ref, not `researchStore.activeFile`. Test added for "activeFile changes mid-stream, mutation still uses original ticker."
- **NB1 (B test count drift "5 tests" but lists 8):** Renumbered + header corrected.
- **NB2 (D test count drift "3 tests" but lists 7):** Renumbered + header corrected.
- **NB3 (impl prompt stale wording + 43 vs 45):** Codex prompt swept — B.2 wording fixed; test count 45.
- **NB4 (§5 doesn't gate connector re-exports):** Acceptance criterion 12 added explicitly.

---

**R4 → R5 changelog:**

**R4 → R5 changelog:**
- **B1 (`useThesis` ticker subscriber misses researchFileId-only mutations on null-to-non-null thesis creation):** Publishers publish BOTH keys where derivable. `useResearchChat` carries `researchFileId` but ALSO has access to the active ticker via `researchStore` (or whichever local store holds the current research-file context). When publishing stream-complete or apply_patch_ops, include both `ticker` and `researchFileId` if ticker is derivable. New test 32d asserts null-to-non-null useThesis invalidation when a thesis is created mid-session.
- **B2 (connector re-exports not in file manifest):** Added `frontend/packages/connectors/src/index.ts` to §3.5 file diff manifest + §5 acceptance. Re-exports `useThesis`, `useArtifactReady`, `useArtifactEventStore`, store types so downstream PRs can consume via `@risk/connectors` package API.
- **NB1 (test count drift in §B):** Renumbered chassis/parser tests; header says "7 tests" matching actual list.
- **NB2 (B.3 lifecycle):** Added test 11a explicit: `pendingToolInputs` map is per-`GatewayService` instance + cleared on `close()` / stream-end.
- **NB3 (impl prompt B.2 stale wording):** Codex prompt sweep — chassis correctly described as "already has tool_name/result/error; tool_input new via B.3 correlation."

---

**R3 → R4 changelog:**

**R3 → R4 changelog:**
- **B1 (tests don't lock B.3 correlation):** Replaced/added tests for the actual correlation flow — raw `tool_call_start` chunk with `tool_input` followed by `tool_call_complete` chunk WITHOUT `tool_input`, asserting GatewayService consumes from the correlation map and emits the typed chunk WITH the inferred `tool_input`. Map clear-on-consume verified.
- **B2 (hook publishing tests muddy):** Added explicit tests — `test_useResearchChat_publishes_stream_complete_with_researchFileId`, `test_useResearchChat_publishes_apply_patch_ops_via_correlated_tool_input`, `test_usePortfolioChat_publishes_apply_patch_ops_only_no_stream_complete`. Test 32 reframed — it was previously claiming the parser publishes, but actually hooks publish; corrected.
- **B3 (position_card_full sidecar implication):** Swept §1 + §3.5 — position_card_full is an AGGREGATE composed from `useArtifactReady('critical-factors')` + `useArtifactReady('quantifying-risk')`. NO `/api/artifacts/.../position_card_full` endpoint. No separate sidecar.
- **NB1 (DoD count):** Sweep — DoD says "6 SSE integration acceptance tests" everywhere.
- **NB2 (dedupe/ordering semantics):** Event-store dedupe rule: keyed by `(ticker, skill, artifact_id)` for artifacts; `(ticker, view_model_id, ts)` for aggregates (later `ts` wins). Out-of-order: store accepts but doesn't re-notify if newer `ts` already seen.
- **NB3 (impl prompt stale chassis claim):** Codex prompt wording corrected — chassis already exposes `tool_name`, `result`, `error`; only `tool_input` is new (via B.3 correlation).

---

**R2 → R3 changelog:**

**R2 → R3 changelog:**
- **B1 (`tool_call_complete` lacks `tool_input`):** Verified at `AI-excel-addin/packages/agent-gateway/agent_gateway/runner.py:2217, 2348` — `tool_input` emitted on `tool_call_start` only. Since we can't modify AI-excel-addin, chassis `GatewayService` must correlate by `tool_call_id`: track an in-memory `Map<tool_call_id, tool_input>` populated on `tool_call_start` and attach to the typed chunk on `tool_call_complete`. New sub-scope B.3. Test 35 reframed as start+complete sequence.
- **B2 (API not consistently propagated):** Swept sub-scope D, test names, acceptance criteria, and Codex prompt to use unified `publishThesisMutation({source, ticker?, researchFileId?})`. `useResearchChat` publishers use `researchFileId` (not `activeTicker` — confirmed it carries researchFileId).
- **B3 (`usePortfolioChat` underspecified):** Scope clarified — portfolio-channel chat publishes ONLY `apply_patch_ops` mutations via correlated `tool_input.research_file_id`. NO stream-complete publish from portfolio channel (no thesis-context source). Research chat publishes both signals.
- **NB1:** Added `connectors/src/index.ts` re-exports to file diff manifest + acceptance.
- **NB2:** `AggregateReadyChunk` shape made explicit (skill_run_id, ticker, view_model_id, trigger, sources_complete, ts).
- **NB3:** Clarified `position_card_full` composes from `critical-factors` + `quantifying-risk` artifact subscriptions; does NOT fetch a separate `/artifacts/.../position_card_full` endpoint.
- **NB4:** DoD updated — "6 SSE integration acceptance tests" (not 3).

---

**R1 → R2 changelog:**

**R1 → R2 changelog:**
- **B1 (apply_patch_ops keyed by research_file_id, not ticker):** Verified — `useResearchChat` carries `researchFileId`; `usePortfolioChat` has no thesis ticker context; `apply_patch_ops` tool input uses `research_file_id` (`AI-excel-addin/api/research/routes.py:326`). Replaced ticker-only `publishToolResponse` with unified `publishThesisMutation({ source, ticker?, researchFileId? })`. `useThesis(ticker)` resolves `research_file_id` from initial fetch and subscribes by BOTH keys. `apply_patch_ops` publishers extract `tool_input.research_file_id`; ticker derived if available, otherwise null.
- **B2 (test paths don't match Vitest config):** Verified at `frontend/vitest.config.mts:7` — Vitest only picks up `packages/*/src/**/*.test.{ts,tsx}`. All planned tests moved from `packages/*/tests/...` to colocated `packages/*/src/**/*.test.{ts,tsx}` paths matching the shipped pattern (e.g., `GatewayService.test.ts:184` lives in `src/services/`).
- **B3 (initial mount /latest race vs newer event):** `useArtifactReady` now tracks a request-generation token + desired-artifact-ID. The `/latest` initial fetch commits ONLY if no newer event has been accepted during the in-flight request, OR if the `/latest` response's `artifact_id` matches the current desired ID. Added test 36 for stale-/latest-over-new-event path.
- **NB1 (chassis tool_result fields stale):** Verified — chassis `ClaudeStreamTypes.ts` already exposes `tool_name`, `result`, `error`, `final_tool_result_blocks`. Only `tool_input` is missing. Sub-scope B.2 narrowed to "add `tool_input` field"; the connector parser strip is the actual gap (extract `tool_name` + `tool_input` from already-typed chunks).
- **NB2 (debounce semantics):** `useThesis` debounce marks dirty (not drop). Signals during in-flight fetch schedule another fetch after completion. Added invariant in §3.
- **NB3 (AggregateReadyChunk fields):** Extended chunk shape to preserve `skill_run_id`, `trigger`, `sources_complete` from upstream `AggregateReadyEvent` (`events.py:69`).
- **NB4 (integration test scope too happy-path):** Tests 33-35 expanded with explicit error/race paths — malformed chunk (36), sidecar fetch failure + recovery (37), stale-cache-over-event race (38).
- **NB5 (connector exports):** Added re-exports for `useThesis`, `useArtifactReady`, store types in `packages/connectors/src/index.ts` per current export-pattern.
**Owner:** Henry.
**Per CLAUDE.md plan-first workflow:** Codex review → PASS → impl via Codex.

**Parent docs (read first):**
- Spec (architectural authority): `docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md` (R7 CODEX PASS)
- Umbrella / cross-PR coordination: `docs/planning/F147_IMPL_PLAN.md` (R4)
- Principles: `docs/standards/INVESTMENT_VISUAL_LAYER_PRINCIPLES.md`

**Scope policy:** This plan covers ONLY PR-0 — the data substrate that unblocks all F147 entries. Other PRs have their own per-PR plans (PR-1 onwards).

---

## 1. Goal

Ship the frontend data plumbing that F147 entries depend on:

1. **Thesis snapshot reads** via the existing research-content proxy (no new backend route)
2. **Artifact-fetch proxy** for sidecar-backed skills — only 2 v1 entries DIRECTLY subscribe via `useArtifactReady` for sidecar fetch: `critical_factors_card` and `quantifying_risk_card`. The `position_card_full` aggregate COMPOSES from these two existing subscriptions; it does NOT have its own sidecar/endpoint.
3. **Chassis event typing** — surface `artifact_ready` / `aggregate_ready` events (currently dropped at chassis boundary)
4. **Module-level artifact event store** with pub/sub for distributed event consumption
5. **Connector hooks** — `useThesis(ticker)` + `useArtifactReady(skill, ticker)`
6. **Triple invalidation** for `useThesis` — stream-complete + `apply_patch_ops` tool_response + opportunistic `artifact_ready`

---

## 2. Sub-scopes

| ID | What ships | Repo |
|---|---|---|
| A.1 | NO new backend route — Thesis reads use existing `/api/research/content/theses` proxy | risk_module (no change) |
| A.2 | NEW `routes/artifacts_proxy.py` at `/api/artifacts/*` (3 endpoints) + `sign_user_claim_headers` helper | risk_module |
| B.1 | Chassis `ClaudeStreamChunk` + `GatewayService.mapEvent` extensions for `artifact_ready` + `aggregate_ready` | risk_module `packages/chassis` |
| B.2 | Chassis `tool_result` event surfacing — extend to include `tool_name` + `tool_input` (currently only `sources`) | risk_module `packages/chassis` |
| C.1 | Module-level artifact event store + React hook wrapper | risk_module `packages/connectors` |
| C.2 | `useThesis` + `useArtifactReady` hooks | risk_module `packages/connectors` |
| D | `chatStreamPayloads.ts` typed branches publishing to module-level store; chat hooks publishing stream-complete + tool-response | risk_module `packages/connectors` |
| E | SSE integration test (acceptance gate) | risk_module |

---

## 3. File diffs

### A.2 — Artifacts proxy + auth helper

| File | Action | Description |
|---|---|---|
| `utils/agent_claim.py` | EXTEND | Add `sign_user_claim_headers(hmac_key: str, *, audience='agent_api_v1', user_id, user_email, ttl_seconds=600) -> dict[str, str]`. Wraps existing `sign(hmac_key: str, ...)` primitive (signature confirmed `str` at `utils/agent_claim.py:37`). Returns 7-header dict. |
| `routes/artifacts_proxy.py` | NEW | FastAPI router at `/api/artifacts`:<br>- `GET /{ticker}` — list artifacts for ticker<br>- `GET /{ticker}/{skill}/latest` — latest artifact for (ticker, skill)<br>- `GET /{ticker}/{skill}/{artifact_id}` — specific artifact by id<br>Proxies to AI-excel-addin `/api/artifacts/*` with `sign_user_claim_headers` auth. Rate limits: 60/min list, 120/min content. Verified endpoint shapes at `AI-excel-addin/packages/agent-gateway/agent_gateway/server.py:1023, 1038, 1057`. |
| `app.py` (FastAPI app assembly) | EXTEND | Register `artifacts_proxy.router`. |

### B.1 — Chassis artifact + aggregate event typing

| File | Action | Description |
|---|---|---|
| `frontend/packages/chassis/src/services/ClaudeStreamTypes.ts` | EXTEND | Add `ArtifactReadyChunk` discriminated variant: `{ type: 'artifact_ready', skill_run_id, ticker, skill, artifact_id, artifact_path, binary_artifact_path: string \| null, contract_name, data_source: 'live' \| 'fixture', ts }`. Shape verified at `AI-excel-addin/packages/agent-gateway/agent_gateway/events.py:49`. Also add `AggregateReadyChunk`: `{ type: 'aggregate_ready', ticker, view_model_id, ts, ... }` (shape from `events.py:69`). |
| `frontend/packages/chassis/src/services/GatewayService.ts` | EXTEND | At `mapEvent` (line ~437): add typed switch branches for `'artifact_ready'` + `'aggregate_ready'` raw event types, returning the new chunk variants. Today these return `null` (events dropped). |

### B.2 — Chassis tool_result field surfacing (narrowed per R1 NB1)

Chassis `ClaudeStreamTypes` already exposes `tool_name`, `result`, `error`, `final_tool_result_blocks` on `tool_result` chunks. Only `tool_input` is missing. Scope:

| File | Action | Description |
|---|---|---|
| `frontend/packages/chassis/src/services/ClaudeStreamTypes.ts` | EXTEND | Add `tool_input?: unknown` to `tool_result` chunk shape. `tool_name`, `result`, `error`, `final_tool_result_blocks` ALREADY present — no change. |
| `frontend/packages/connectors/src/features/external/chatStreamPayloads.ts:258` | EXTEND | When parsing `tool_result` chunks, surface `tool_name` + `tool_input` to consumers (currently strips down to `sources` only — see chatStreamPayloads.ts:258). |

### B.3 — Chassis tool_call_id correlation (NEW per R2 B1)

Upstream emits `tool_input` ONLY on `tool_call_start` events (`AI-excel-addin/packages/agent-gateway/agent_gateway/runner.py:2217`); `tool_call_complete` omits it (`runner.py:2348`). Since we can't modify AI-excel-addin, chassis correlates:

| File | Action | Description |
|---|---|---|
| `frontend/packages/chassis/src/services/GatewayService.ts` | EXTEND | Add in-memory `pendingToolInputs: Map<tool_call_id, unknown>` populated on `tool_call_start`; consumed + cleared on `tool_call_complete` → attached to the typed `tool_result` chunk before emit. Lifetime bounded to the SSE stream connection; cleared on stream close. Map capped (e.g., 50 entries) to bound memory. |
| `frontend/packages/chassis/src/services/GatewayService.ts` (mapEvent `tool_call_start` branch) | EXTEND | Populate `pendingToolInputs.set(chunk.tool_call_id, chunk.tool_input)` if `tool_input` present. |
| `frontend/packages/chassis/src/services/GatewayService.ts` (mapEvent `tool_call_complete` / `tool_result` branch ~line 447) | EXTEND | Look up `pendingToolInputs.get(raw.tool_call_id)` and attach to the typed chunk; clear from map. |

### C.1 — Module-level artifact event store

| File | Action | Description |
|---|---|---|
| `frontend/packages/connectors/src/features/artifacts/artifactEventStore.ts` | NEW | Module-level singleton. **Unified mutation event per R1 B1** — `publishThesisMutation({ source, ticker?, researchFileId? })` replaces ticker-only invalidation. Both ticker and research_file_id are first-class keys; subscribers can listen on either. Exports:<br>- `publishArtifactReady(chunk: ArtifactReadyChunk)` — artifact event<br>- `publishAggregateReady(chunk: AggregateReadyChunk)` — aggregate event (preserves upstream `skill_run_id`, `trigger`, `sources_complete`, `ticker`, `view_model_id`, `ts` per NB3)<br>- **`publishThesisMutation(payload: { source: 'stream_complete' \| 'apply_patch_ops' \| 'artifact_ready'; ticker?: string; researchFileId?: number })`** — thesis-invalidation event with BOTH key types<br>- `getLatestArtifact(ticker, skill, artifact_id?)` — read<br>- `getLatestAggregate(ticker, view_model_id)` — read<br>- `subscribe(listener)`, `subscribeToTicker(ticker, listener)`, **`subscribeToThesisMutation({ ticker?, researchFileId? }, listener)`** (matches if EITHER key matches), `subscribeToAggregate(ticker, view_model_id, listener)`<br><br>Internal state:<br>- `artifactsByTickerSkill: Map<(ticker, skill), ArtifactReadyChunk[]>` — latest = head; cap at N events per key<br>- `aggregatesByTickerViewModel: Map<(ticker, view_model_id), AggregateReadyChunk>` — tuple-keyed (no cross-ticker contamination)<br><br>Notifies relevant subscribers on each publish. **No React hooks inside this file** — pure module API. |
| `frontend/packages/connectors/src/features/artifacts/useArtifactEventStore.ts` | NEW | React hook wrapper for reactive reads. Uses `useSyncExternalStore` for React 18 concurrent-safe. Returns `{ getLatestArtifact, getLatestAggregate, subscribeToTicker, subscribeToThesisMutation, subscribeToAggregate }` (read-only — components don't publish). |

### C.2 — Connector hooks

| File | Action | Description |
|---|---|---|
| `frontend/packages/connectors/src/features/thesis/types.ts` | NEW | TS types: `ThesisSnapshot`, `ThesisField`, etc. matching `AI-excel-addin/schema/thesis.py:386-425` shape. |
| `frontend/packages/connectors/src/features/thesis/useThesis.ts` | NEW | `useThesis(ticker): { data: ThesisSnapshot \| null; loading: boolean; error: Error \| null }`.<br><br>**Fetch logic:** `GET /api/research/content/theses?ticker={ticker}` (returns list sorted by `updated_at DESC, id DESC` per `AI-excel-addin/api/research/repository.py:2198`); take first item to get `research_file_id`; then `GET /api/research/content/theses/{research_file_id}` for full snapshot. SWR-style caching by ticker. **Holds resolved `research_file_id`** for the lifetime of the subscription so it can match `apply_patch_ops` events that lack ticker.<br><br>**Triple invalidation via unified `subscribeToThesisMutation` (per R1 B1):**<br>Hook subscribes with `{ ticker, researchFileId }` — matches if EITHER key matches an incoming `publishThesisMutation` event.<br>- `stream_complete` source — fires on any chat turn end matching ticker OR researchFileId<br>- `apply_patch_ops` source — fires on `tool_input.research_file_id` match (no ticker required)<br>- `artifact_ready` source — fires on ticker match (opportunistic; only the 4 contract-backed skills emit these events at all)<br><br>Coverage: ALL skill writes invalidate via stream_complete OR apply_patch_ops; the 3 sidecar entries also get artifact_ready for instant refresh.<br><br>**Debounce (per R1 NB2):** trailing 200ms window. Signals arriving during in-flight fetch mark the request DIRTY and schedule a new fetch after completion — never dropped. |
| `frontend/packages/connectors/src/features/artifacts/useArtifactReady.ts` | NEW | `useArtifactReady(skillName, ticker): { sidecar: ArtifactSidecarPayload \| null; event: ArtifactReadyChunk \| null; loading; error }`.<br><br>**Logic:** subscribes via `useArtifactEventStore` for `(skillName, ticker)` matches. On each event, fetches sidecar via `GET /api/artifacts/{ticker}/{skillName}/{event.artifact_id}` (fetch by event's `artifact_id` — NOT `/latest` — to avoid race on rapid events). Initial mount with no prior event: fires `/api/artifacts/{ticker}/{skillName}/latest` once. Cache by `(skillName, ticker, artifact_id)`.<br><br>**Race guard per R1 B3:** Hook tracks two state pieces:<br>1. `requestGeneration: number` — monotonically increments on each new fetch (event-driven OR initial /latest)<br>2. `desiredArtifactId: string \| null` — latest accepted event's artifact_id; null when only /latest in flight<br><br>On `/latest` response: commits ONLY if `desiredArtifactId === null` (no event accepted during in-flight) OR if response's `artifact_id === desiredArtifactId`. Otherwise discards as stale.<br><br>On event-driven fetch response: commits ONLY if response's `artifact_id === desiredArtifactId`. Race-test 36 covers stale-/latest-over-newer-event.<br><br>**Only 2 v1 entries DIRECTLY use this hook:** `critical_factors_card`, `quantifying_risk_card`. The `position_card_full` aggregate composes from those two existing subscriptions — NOT a third invocation of `useArtifactReady('position_card_full', ...)` (no such sidecar exists). |

### D — Payload parsing publishes to store

| File | Action | Description |
|---|---|---|
| `frontend/packages/connectors/src/features/external/chatStreamPayloads.ts` | EXTEND | Add typed branches for `artifact_ready` + `aggregate_ready` chunks. Each branch calls **module-level** `publishArtifactReady(chunk)` / `publishAggregateReady(chunk)` from `artifactEventStore.ts`. Also: when the `artifact_ready` branch fires, publish a `publishThesisMutation({ source: 'artifact_ready', ticker: chunk.ticker })` so non-sidecar `useThesis` subscribers refresh too (opportunistic for the 4 contract-backed skills). **Never invoke the React hook from the parser** — module-level functions only. |
| `frontend/packages/connectors/src/index.ts` | EXTEND | Re-export new public hooks/types: `useThesis`, `useArtifactReady`, `useArtifactEventStore`, `ThesisSnapshot` type, `ArtifactSidecarPayload` type. Existing consumers import via `@risk/connectors` package API; without these re-exports, downstream PRs can't consume the new hooks through the package. |
| `frontend/packages/connectors/src/features/external/hooks/useResearchChat.ts` | EXTEND | **Per R5 B1, ticker is a HOOK OPTION passed from caller (not read from `researchStore.activeFile` mid-stream — `activeFile` is global and can change during the SSE stream).** Hook signature: `useResearchChat({ ticker, researchFileId, threadId, ... })`. At `sendMessage` START, capture ticker into a ref (`capturedTickerRef`) that publishers reference. Two publish points:<br>1. **Turn-end signal** — on `onStreamComplete`, call `publishThesisMutation({ source: 'stream_complete', researchFileId, ticker: capturedTickerRef.current })`.<br>2. **`apply_patch_ops` tool result** — when a typed `tool_result` chunk has `tool_name === 'apply_patch_ops'`, extract `tool_input.research_file_id` (via B.3 correlation) and call `publishThesisMutation({ source: 'apply_patch_ops', researchFileId: tool_input.research_file_id, ticker: capturedTickerRef.current })`.<br><br>**Callers updated to pass `ticker` explicitly** (paths verified):<br>- `frontend/packages/ui/src/components/research/AgentPanel.tsx`<br>- `frontend/packages/ui/src/components/research/ExploreTab.tsx`<br>- `frontend/packages/ui/src/components/research/ResearchWorkspace.tsx`<br><br>Make `ticker: string` REQUIRED in `useResearchChat` options (TS-enforced). |
| `frontend/packages/ui/src/components/research/AgentPanel.tsx` | EXTEND | Pass `ticker` prop to `useResearchChat({ ticker, researchFileId, ... })`. Add `ticker: string` to component props if not already present; thread from parent. |
| `frontend/packages/ui/src/components/research/ExploreTab.tsx` | EXTEND | Pass `ticker` prop to `useResearchChat`. Add ticker prop / context resolution as needed. |
| `frontend/packages/ui/src/components/research/ResearchWorkspace.tsx` | EXTEND | Thread `ticker` to children (AgentPanel, ExploreTab). Use research-file → ticker resolution (today via active research_file lookup); pass as prop to avoid global-store dependency. |
| `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts` | EXTEND | **Scope (per R2 B3):** portfolio-channel chat has NO thesis ticker/researchFileId context, so DO NOT publish stream-complete from here. ONLY publish `apply_patch_ops` mutations by correlated `tool_input.research_file_id`: when a typed `tool_result` chunk has `tool_name === 'apply_patch_ops'`, call `publishThesisMutation({ source: 'apply_patch_ops', researchFileId: tool_input.research_file_id })`. Identical to useResearchChat's apply_patch_ops branch. |

---

## 4. Tests

### A.2 — Backend proxy + auth helper (8 tests)

1. `test_sign_user_claim_headers_produces_7_headers` — `tests/utils/test_agent_claim.py`
2. `test_sign_user_claim_headers_audience_is_agent_api_v1`
3. `test_sign_user_claim_headers_signature_verifies_upstream`
4. `test_artifacts_proxy_list_endpoint` — `tests/routes/test_artifacts_proxy.py`
5. `test_artifacts_proxy_latest_endpoint`
6. `test_artifacts_proxy_by_id_endpoint`
7. `test_artifacts_proxy_rate_limit_enforced`
8. `test_artifacts_proxy_requires_signed_claim`

### B.1 + B.2 + B.3 — Chassis event typing + correlation (8 tests including B.3 correlation flow)

9. `test_chassis_artifact_ready_chunk_parsed` — `frontend/packages/chassis/src/services/GatewayService.test.ts`
10. `test_chassis_aggregate_ready_chunk_parsed`
11. `test_chassis_tool_call_start_populates_correlation_map` — raw `tool_call_start` with `tool_input` adds entry to pendingToolInputs
11a. `test_chassis_pendingToolInputs_is_per_instance_and_cleared_on_close` — per-GatewayService-instance state; cleared on `close()` / stream-end (per R4 NB2)
12. `test_chassis_tool_call_complete_consumes_and_clears_correlation` — raw `tool_call_complete` (WITHOUT tool_input) emits typed chunk WITH tool_input via map lookup; entry cleared after consume
13. `test_chassis_tool_call_complete_without_prior_start_emits_chunk_without_tool_input` — graceful fallback when start was missed
14. `test_connectors_chatStreamPayloads_extracts_tool_name_and_tool_input` (parser strip fix; verifies downstream visibility after correlation)
13. `test_chassis_unhandled_event_returns_null_unchanged`

### C.1 — Event store (8 tests)

14. `test_artifactEventStore_publish_artifact_ready_notifies_subscribers` — `frontend/packages/connectors/src/features/artifacts/artifactEventStore.test.ts`
15. `test_artifactEventStore_getLatestArtifact_returns_head`
16. `test_artifactEventStore_aggregates_keyed_by_ticker_view_model_id_tuple` (no cross-ticker contamination)
17. `test_artifactEventStore_publishThesisMutation_notifies_ticker_subscribers` (matches by ticker)
18. `test_artifactEventStore_publishThesisMutation_notifies_researchFileId_subscribers` (matches by researchFileId even when ticker not provided)
19. `test_artifactEventStore_duplicate_publisher_dedupes`
20. `test_artifactEventStore_out_of_order_events_handled_by_ts`
21. `test_useArtifactEventStore_hook_wrapper_via_useSyncExternalStore`

### C.2 — Connector hooks (8 tests)

22. `test_useThesis_fetches_latest_thesis_for_ticker`
23. `test_useThesis_returns_null_when_no_thesis_exists`
24. `test_useThesis_invalidates_on_stream_complete`
25. `test_useThesis_invalidates_on_apply_patch_ops_tool_response`
26. `test_useThesis_invalidates_on_artifact_ready_for_ticker`
27. `test_useArtifactReady_fetches_sidecar_by_artifact_id_from_event` (NOT latest)
28. `test_useArtifactReady_initial_mount_fetches_latest_once`
29. `test_useArtifactReady_caches_by_artifact_id`

### D — Payload parsing + hook publishers (8 tests, including 32a-e hook publish coverage)

30. `test_chatStreamPayloads_artifact_ready_publishes_to_module_store` (parser-level)
31. `test_chatStreamPayloads_aggregate_ready_publishes_to_module_store` (parser-level)
32. `test_chatStreamPayloads_artifact_ready_also_publishes_thesis_mutation` (parser also fires opportunistic thesis-mutation refresh signal)
32a. `test_useResearchChat_publishes_stream_complete_with_researchFileId` (hook-level — verifies onStreamComplete handler) — `src/features/external/hooks/useResearchChat.test.ts`
32b. `test_useResearchChat_publishes_apply_patch_ops_via_correlated_tool_input` (hook-level — verifies tool_result chunk with apply_patch_ops extracts research_file_id from chassis-correlated tool_input)
32c. `test_usePortfolioChat_publishes_apply_patch_ops_only_no_stream_complete` (hook-level — verifies portfolio chat scope per R2 B3) — `src/features/external/hooks/usePortfolioChat.test.ts`
32d. `test_useThesis_invalidates_on_null_to_non_null_thesis_creation` (per R4 B1 — mounted useThesis(ticker) with no thesis sees the post-thesis_create mutation event because useResearchChat publishes BOTH ticker AND researchFileId)
32e. `test_useResearchChat_captures_ticker_at_sendMessage_start_not_mid_stream` (per R5 B1 — activeFile changes mid-stream do NOT shift the published ticker; capturedTickerRef holds the original) — `src/features/external/hooks/useResearchChat.test.ts`

### E — SSE integration (acceptance gate)

33. **`test_sse_integration_full_chain`** — `frontend/packages/connectors/src/features/artifacts/sse-chain.test.ts`

Sends a synthetic SSE event matching shipped contract:

```json
{
  "type": "artifact_ready",
  "skill_run_id": "test-run-001",
  "ticker": "PCTY",
  "skill": "critical-factors",
  "artifact_id": "art-001",
  "artifact_path": "artifacts/PCTY/critical-factors/art-001.json",
  "binary_artifact_path": null,
  "contract_name": "CriticalFactors",
  "data_source": "fixture",
  "ts": 1234567890
}
```

Asserts:
1. `GatewayService.mapEvent` returns typed `ArtifactReadyChunk` (not null)
2. Parser routes the chunk to `publishArtifactReady`
3. `useArtifactEventStore.subscribeToTicker('PCTY')` listener fires
4. `useArtifactReady('critical-factors', 'PCTY')` hook returns the sidecar payload
5. Downstream test component re-renders

34. **`test_sse_integration_aggregate_ready`** — same shape but for aggregate event variant
35. **`test_sse_integration_apply_patch_ops_invalidates_thesis_by_research_file_id`** — tool_result with `tool_name: 'apply_patch_ops'` + `tool_input.research_file_id` triggers `useThesis` refetch via subscribeToThesisMutation (matches researchFileId even without ticker)

### Error / race / edge paths (per R1 NB4 — acceptance gate must cover beyond happy path)

36. `test_useArtifactReady_stale_latest_response_discarded_when_newer_event_received` — fires /latest, then accepts artifact_ready event with newer artifact_id during in-flight; /latest response must be discarded
37. `test_useArtifactReady_sidecar_fetch_failure_surfaces_error_then_recovers` — sidecar fetch returns 500; hook exposes error state; next valid event recovers
38. `test_chassis_malformed_artifact_ready_chunk_does_not_crash_mapEvent` — malformed payload (missing required field) returns null gracefully; no exception

---

## 5. Acceptance criteria

PR-0 ships when ALL of the following pass:

1. ✓ `routes/artifacts_proxy.py` registered; 3 endpoints respond with proxied data
2. ✓ `sign_user_claim_headers` emits 7 correctly-keyed headers; signature verifies upstream
3. ✓ Chassis `ClaudeStreamChunk` union includes both new variants + extended `tool_result`; `mapEvent` returns them
4. ✓ Module-level event store: `publishArtifactReady` / `publishAggregateReady` / `publishThesisMutation` all functional; subscribers notified correctly (including ticker-only AND researchFileId-only mutation match paths)
5. ✓ Aggregate index keyed by `(ticker, view_model_id)` tuple — no cross-ticker contamination
6. ✓ `useThesis(ticker)` returns non-null `ThesisSnapshot` for a real ticker
7. ✓ `useThesis` invalidates on all three signals (stream-complete, apply_patch_ops, artifact_ready)
8. ✓ `useArtifactReady` returns fetched sidecar payload + event metadata; fetches by event's `artifact_id` (not /latest)
9. ✓ All 46 tests pass
10. ✓ SSE integration tests (33-38) pass — full event chain end-to-end + race + error + malformed
11. ✓ No regression in existing diligence rendering paths
12. ✓ `frontend/packages/connectors/src/index.ts` re-exports `useThesis`, `useArtifactReady`, `useArtifactEventStore`, `ThesisSnapshot` type, `ArtifactSidecarPayload` type — downstream PRs can consume via `@risk/connectors`
13. ✓ No publisher reads `researchStore.activeFile` directly. `useResearchChat` enforces `ticker: string` REQUIRED in its TS signature. All callers (`AgentPanel`, `ExploreTab`, `ResearchWorkspace`) pass ticker explicitly from props/context, captured at sendMessage start.

---

## 6. Codex implementation prompt

When dispatching PR-0 to Codex via `mcp__codex__codex` (after this plan PASSes review):

```
Implement PR-0 for F147 THESIS_ARTIFACT_REGISTRY per the impl plan at:
docs/planning/F147_PR0_IMPL_PLAN.md

The data substrate that unblocks all F147 entries.

Sub-scopes (§2):
- A.1: NO new backend route — Thesis reads via existing /api/research/content/* proxy
- A.2: NEW routes/artifacts_proxy.py + sign_user_claim_headers helper in utils/agent_claim.py
- B.1: Extend chassis ClaudeStreamTypes + GatewayService.mapEvent for artifact_ready + aggregate_ready
- B.2: Add `tool_input` to chassis tool_result chunk shape (`tool_name`/`result`/`error` already shipped); extend connector parser at `chatStreamPayloads.ts:258` to surface `tool_name` + `tool_input` (parser currently strips down to sources only).
- B.3: NEW — chassis correlates tool_input via tool_call_id map (populate on tool_call_start, consume on tool_call_complete) since upstream omits tool_input from completion events.
- C.1: NEW module-level artifactEventStore.ts + React hook wrapper
- C.2: NEW useThesis + useArtifactReady hooks
- D: Extend chatStreamPayloads.ts to publish to module-level store; extend chat hooks to publish stream-complete + tool-response
- E: SSE integration tests (acceptance gate, tests 33-38 — happy paths + race + error + malformed)

File diff manifest: §3 (8 backend/connector files + 3 chassis files)
Tests: §4 (46 tests total — 6 SSE integration acceptance tests covering happy + race + error + malformed)
Acceptance: §5

Reference docs:
- F147 spec: docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md (R7 PASS)
- Event shape: AI-excel-addin/packages/agent-gateway/agent_gateway/events.py:49 (artifact_ready), :69 (aggregate_ready)
- Endpoint shapes: AI-excel-addin/packages/agent-gateway/agent_gateway/server.py:1023
- Materializer gate: AI-excel-addin/api/research/materializer.py:153 (only contract-backed skills emit artifact_ready — this is why useThesis needs stream-complete + apply_patch_ops invalidation, not just artifact_ready)

Per CLAUDE.md Codex MCP conventions:
- approval-policy: "never"
- sandbox: "workspace-write" for impl; "danger-full-access" if commit needed
- cwd: /Users/henrychien/Documents/Jupyter/risk_module
- DO NOT pass model or config.model_reasoning_effort (inherit ~/.codex/config.toml)

Work sub-scope by sub-scope. Tests per sub-scope before moving on.
Cross-repo: NO changes to AI-excel-addin in this PR — only proxies to existing endpoints.
Report any blocker requiring AI-excel-addin changes; do NOT modify that repo.
```

---

## 7. Codex review brief (for this plan)

**Areas to challenge:**

1. **Triple invalidation coverage** — is stream-complete + apply_patch_ops + artifact_ready actually exhaustive? Are there agent code paths that write Thesis without triggering any of these signals?
2. **Debouncing** — 200ms debounce coalesces successive triggers. Is that the right window, or does it risk dropping legitimate fast-fire signals?
3. **Aggregate keying** — `(ticker, view_model_id)` tuple. Could a view_model legitimately be ticker-less (portfolio-scoped aggregate)? If yes, key needs to handle null ticker.
4. **Initial mount race** — `useArtifactReady` fires `/latest` on initial mount. If an event arrives DURING that fetch, do we keep the event's artifact_id or the /latest response?
5. **`tool_result` field surfacing** — extending chassis to expose `tool_name` + `tool_input` + `result` is a small but potentially-disruptive change. Verify no existing chassis consumers rely on the narrower shape.
6. **Test 33-35 integration scope** — three SSE integration tests cover the happy paths. Are there error paths (network failure, malformed chunk, stale cache) that need explicit tests?

**Inputs available for local execution:**
- `frontend/packages/chassis/src/services/ClaudeStreamTypes.ts` (variant to extend)
- `frontend/packages/chassis/src/services/GatewayService.ts:437` (mapEvent location)
- `frontend/packages/chassis/src/services/GatewayService.ts:447` (tool_result chunk location)
- `frontend/packages/connectors/src/features/external/chatStreamPayloads.ts:47` (parser tool_result location)
- `frontend/packages/connectors/src/features/external/hooks/useResearchChat.ts`
- `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts`
- `utils/agent_claim.py:37` (sign signature)
- `app_platform/gateway/proxy.py` (existing proxy pattern)
- `routes/research_content.py:195` (existing research proxy pattern)
- `AI-excel-addin/packages/agent-gateway/agent_gateway/server.py:1023, 1038, 1057` (artifact endpoint shapes)
- `AI-excel-addin/packages/agent-gateway/agent_gateway/events.py:49, 69` (event shapes)
- `AI-excel-addin/api/research/materializer.py:153, 207` (materializer gate behavior)
- `AI-excel-addin/api/research/repository.py:2198` (theses list endpoint sort order)

---

## 8. Open questions

1. **Debounce window** — 200ms is my guess. Real number based on observed latency between agent skill end → patch op apply → SSE turn complete. Verify in impl.
2. **`useThesis` cache size** — SWR per ticker; cap at N=10 tickers? Open.
3. **Aggregate index cap** — `aggregatesByTickerViewModel` should bound size to avoid memory bloat. N=50?
4. **Error states** — `useArtifactReady` returns `error` on fetch fail. Does the component show error or fall back to stale cached value? Default: stale + small error indicator.

---

## 9. Definition of done

PR-0 ships when:

1. All 46 tests pass (incl. 6 SSE integration acceptance tests — tests 33-38)
2. No regression in existing diligence rendering
3. Manual test: rendering `thesis.critical_factors_card` (from PR-2, mock impl) shows live data for a real ticker
4. Code review (human) — no unaddressed concerns
5. Codex review of THIS plan — PASS

---

## 10. References

- Spec: `docs/planning/THESIS_ARTIFACT_REGISTRY_PLAN.md` (CODEX PASS R7)
- Umbrella: `docs/planning/F147_IMPL_PLAN.md`
- PR-1 plan: `docs/planning/F147_PR1_IMPL_PLAN.md` (ships parallel to PR-0)
- Principles: `docs/standards/INVESTMENT_VISUAL_LAYER_PRINCIPLES.md`
