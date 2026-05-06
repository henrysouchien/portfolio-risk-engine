# V2.P2 Slice D — Citation Chips + Sources + Validator on Both Chat Surfaces

**Status:** SHIPPED + LIVE-VERIFIED 2026-05-06. R9 PASS after 9 Codex review rounds. Implementation across 4 phases; live-verified on Analyst surface with MSFT 10-Q corpus query.

**Shipped commits:**
- `2bc2c6e7` Phase 1 — chassis types + GatewayClaudeService passthrough (`final_tool_result_blocks` + `citation_validation` chunk variant)
- `fdcfa4b2` Phase 2 — hook state capture + side-channel attachment model + atomic `reconcileResearchTurn` / `beginThreadRefresh` / `completeThreadRefresh` + `appendToMessage` + `streamingByThread` lifecycle + `ResearchStreamContext` `await onComplete`
- `4c934f5b` Phase 3 — `<CitationChip>`, `<SourcesList>`, `<ValidationBanner>`, `<CitedMessage>` components + `remarkCitations` plugin (custom HAST elements) + opt-in support in `MarkdownRenderer.tsx` and `ResearchMessageContent.tsx`
- `9f0050d4` Phase 4 — `ChatCore.tsx` + `ConversationFeed.tsx` single-anchor wiring
- `556a01dd` TODO mark — live-verified

**Verification:** 1236 frontend tests pass; live MSFT 10-Q query rendered inline `[S15]` chips throughout markdown body, 16-source `<SourcesList>` footer, and `<ValidationBanner>` "Validation timed out — N pending" degraded state per spec.

**Follow-ups (named, not deferred):** Slice D-Persist (server-side citation persistence — cross-repo) + Slice E (span-scroll iframe — blocked on F44).

---
**Depends on:** V2.P2 Slices A (citation envelope) + B (validator gate) + C (dev CLI chips) all SHIPPED in AI-excel-addin. C.1 (TUI source chips) shipped as reference implementation.
**Effort:** 1-2 weeks across 4 phases.
**Repo:** risk_module (frontend only). No AI-excel-addin changes — Slice A/B already emit the SSE events; we just consume them.
**Spec source:** `docs/planning/V2_P2_CITATION_FIRST_QA_PLAN.md` Slice D row.

## Goal

Render citation chips, a sources list, and validator violations on **every chat surface in risk_module**:
- Main chat: `AIChat.tsx` (modal) + `ChatInterface.tsx` (full-screen) — both wrap `ChatCore.tsx` → `usePortfolioChat`
- Research chat: `AgentPanel.tsx`, `ExploreTab.tsx`, `ResearchWorkspacePhase*` → `useResearchChat`

Both surfaces flow through `GatewayClaudeService` (chassis), so a single chassis-level plumbing change unblocks both.

## Locked design decisions (2026-05-04)

1. **Reusable wrapper, not per-surface duplication.** A new `<CitedMessage>` component renders the `[Sn]` chips + sources list + validator banner; both surfaces drop it into their existing message renderer. No changes to `ChatCore`'s contract.
2. **No new standalone page.** Citations follow chat surfaces, not gate behind a new route. Retrofit `AIChat`, `ChatInterface`, `AgentPanel`, `ExploreTab`. No `ResearchPage.tsx` at `frontend/packages/ui/src/pages/`.
3. **Validator overlay = per-message banner in v1.** Banner with Lucide `AlertTriangle` icon + "Unsourced claims (N) · click to expand" + click-to-expand violation list (claim text, reason, cited indexes, fabricated index if any). Inline yellow underlines on flagged spans deferred to v1.5 — markdown-renderer span injection across already-parsed nodes is non-trivial and can ship later without breaking v1. Codex R1 P3 confirmed: banner gives sufficient institutional-trust signal for v1.

## Cross-repo contract (verified against AI-excel-addin)

### `source_envelope` block (inside `tool_call_complete`)

The gateway emits `tool_call_complete` events. Their `final_tool_result_blocks[]` array contains zero or more blocks of shape:

```ts
{
  type: "source_envelope",
  registry_snapshot: Source[],   // server-authoritative dedup'd full registry — replace, don't merge
  // also has sources_for_call and fresh_sources keys per the gateway impl
}
```

### `Source` shape (verified against `agent-gateway-tui/src/source-registry.ts` + server `citations.py:14`)

```ts
type Source = {
  index: number;                   // 1-based, matches inline [Sn] reference
  document_id: string;
  ticker?: string;
  section?: string;
  source_url?: string;             // server fallback URL when source_url_deep is absent
  source_url_deep?: string;
  snippet?: string;
  source_kind?: string;
  form_type?: string;
  fiscal_period?: string;
  filing_date?: string;
  char_start?: number;
  char_end?: number;
  produced_by_tool?: string;       // tool that emitted this source
};
```

The TUI subset omits `source_url` and `produced_by_tool` — TUI doesn't need them. The React wrapper rendering should prefer `source_url_deep` and fall back to `source_url` for the chip's anchor.

### `source_envelope` block — full server shape

The full block (verified against `AI-excel-addin/api/agent/shared/citations.py:362`) carries more than `registry_snapshot`:

```ts
{
  type: "source_envelope",
  schema_version: number,
  _event_only: boolean,            // True for the SSE-only block sentinel
  tool_name: string,
  tool_call_id: string,
  registry_snapshot: Source[],     // server-authoritative dedup'd full registry — replace, don't merge
  sources_for_call: Source[],      // sources the LLM is allowed to cite for THIS tool result
  fresh_sources: Source[],         // newly-introduced sources in this turn (delta)
}
```

Slice D consumes only `registry_snapshot` for the rendering surface (per Slice C.1's TUI implementation). The other fields exist for the gateway-internal rule that "the LLM may only cite sources that appeared in `sources_for_call` for the call that produced them" — that rule is enforced server-side by the validator (Slice B), so the React side does not need to re-check.

### `citation_validation` event (top-level SSE event)

Verified against `AI-excel-addin/api/agent/shared/citation_validation_event_log.py:152-167`:

```ts
{
  type: "citation_validation",
  schema_version: 1,
  turn: number,
  violations: Violation[],
  violation_count: number,
  total_claims_detected?: number,
  total_sources_in_registry?: number,
  judge_called?: boolean,
  judge_path?: string,
  warning_codes: string[],
  duration_ms?: number,
  soft_mode?: boolean,                                          // true in current default
  validator_error_code?: "validation_timeout" | "validator_internal_error",
  pending_task_count?: number,
}
```

### `Violation` shape (from `AI-excel-addin/api/agent/shared/citations.py:41-48`)

```ts
type Violation = {
  span_start: number;
  span_end: number;
  claim_text: string;
  reason: string;          // e.g. "judge_flagged"
  detector: string;        // e.g. "regex" | "judge"
  fabricated_index?: string;     // e.g. "S99" — referenced [Sn] not in registry
  cited_indexes?: string[];      // e.g. ["S1","S3"] — what the LLM cited for this claim
};
```

Soft-mode default → frontend should treat violations as warnings, never block the assistant message render.

## Citation→message attachment model (load-bearing)

Codex R1 P1 #2/#3 surfaced two correlation gaps. Both are resolved here.

### The problem

- `citation_validation` events carry a gateway-internal `turn` field, not a React message id.
- `source_envelope` blocks live inside `tool_call_complete` and have no turn field at all.
- `useResearchChat` creates assistant messages with optimistic ids like `agent-${timestamp}` (line 73), then calls `replaceMessages` with server-authoritative messages on stream completion (lines 103-107). Any per-message-id citation state attached to the optimistic id is wiped immediately when server data arrives — not on reload, on completion.

### The model

**Side-channel maps keyed by `assistantMessageId`, not by turn position.**

R1 used `turnIndex` (assistant-message position in thread), which Codex R2 P1 #1 + #2 showed is fragile: turn positions shift on `deleteMessage` / `regenerate` (`usePortfolioChat.ts:968,1006,1040`); computing position from a React-state-captured closure in `usePortfolioChat` is unsafe (the `messages` closure is the pre-send array); and `ThreadTab` passes `messages.slice(-4)` into `ConversationFeed`, so position-from-visible-list would shift citations (`ThreadTab.tsx:29,78`). R2 keys by message id directly.

For each thread, store two maps in the existing per-surface store (separate from the message array):

```ts
type CitationsByMessage = {
  // assistantMessageId = the id of an assistant message at any moment
  //                     (optimistic during streaming, server-issued after replaceMessages)
  sources: { [assistantMessageId: string]: Source[] };
  violations: { [assistantMessageId: string]: ValidationEvent };
};
```

#### Streaming

- Hook creates the assistant placeholder message first (already happens in both hooks today: `usePortfolioChat.ts:662` sets `assistantMessageId = `assistant_${Date.now()}`` then appends the placeholder at line 672; `useResearchChat.ts:73` creates `agent-${timestamp}`). That id is captured into a stable closure variable for the duration of the stream — never recomputed from the messages array.
- During the stream, chassis chunks (`tool_result` carrying `final_tool_result_blocks`, and `citation_validation`) write into `sources[assistantMessageId]` / `violations[assistantMessageId]`. Source registry replaces (server-authoritative); validation event replaces.

#### Stream completion + research `replaceMessages` migration (atomic, race-safe)

`useResearchChat`'s `onComplete` (`useResearchChat.ts:98-108`) starts a detached `fetchResearchMessages(...).then(replaceMessages)` and returns immediately. Codex R4 P1 surfaced that under turn-overlap, this can stale-overwrite a newer turn (Scenario B). R4 fixes this with four pieces:

1. **`onComplete` awaits reconciliation — requires `ResearchStreamContext` API change.** R4's "just make `onComplete` async" claim was wishful: `ResearchStreamContext.tsx:82` currently calls `request.onComplete();` synchronously and ignores any returned promise (per Codex R5 P1 #1). Slice D pulls in three coordinated changes:
   - Change the request type from `onComplete: () => void` to `onComplete: () => void | Promise<void>` in `ResearchStreamContext`'s request interface.
   - Change the call site at `ResearchStreamContext.tsx:82` from `request.onComplete();` to `await request.onComplete();`.
   - Update `useResearchChat.ts:98` to `async onComplete()`. Inside, wrap the fetch + reconcile in try/catch — preserve the existing non-fatal behavior (post-stream fetch failure must NOT propagate as a stream error). On catch: drop the optimistic side-channel entry and log; do NOT throw.
   With these three changes, `ResearchStreamContext`'s existing `currentSendRef` serialization (which aborts prior controllers and awaits the prior send before starting the next — `ResearchStreamContext.tsx:57`) extends through reconciliation. Cross-turn race eliminated for UI-driven sends. Note: programmatic callers that bypass `sendMessage` and call `streamManager.send` directly are NOT protected by this serialization. v1 ships UI-driven only; programmatic-caller protection is filed as a follow-up if needed.
2. **Single atomic store action `reconcileResearchTurn({ threadId, optimisticId, optimisticPosition, capturedSequence, serverMessages })`** — runs ONE Zustand `set(state => ...)` reducer that does ALL of: stale-fetch sequence check, validate optimistic id still present, identify migration target, window-replace messages preserving local suffix added after the optimistic turn, copy + delete side-channel entries. No intermediate state is ever observable to the renderer. (Step order detailed below.)
3. **Reducer logic** (R5 spec — strict step order):
   0. **Sort `serverMessages`** via the existing `sortMessages` utility (`researchStore.ts:284`) — `fetchResearchMessages` does not sort, but the `optimisticPosition` lookup and final write must be in chronological order to be reliable (per Codex R7 P2 #3).
   1. **Stale-fetch guard.** Check `state.reconcileSequence[threadId] === capturedSequence`. If false → this fetch was superseded by a later refresh/turn; drop the optimistic side-channel entry. Do NOT touch messages. Return.
   2. **Validate optimistic still present.** Read `currentMessages = state.messagesByThread[threadId]`. If `currentMessages[optimisticPosition]?.id !== optimisticId`, the optimistic was already removed (delete / regenerate / earlier reconcile / mid-stream abort). → Drop the optimistic side-channel entry. Do NOT touch messages. Return.
   3. **Identify migration target** with this priority order:
      1. If `serverMessages` contains an assistant message with `id === optimisticId` (server preserved client id) → target is `optimisticId` itself; flag as same-id (skip the copy/delete in step 5 — but DO write messages in step 4).
      2. Else if `serverMessages.length > optimisticPosition` and `serverMessages[optimisticPosition].author` is assistant → target is `serverMessages[optimisticPosition].id`.
      3. Else if the optimistic message was the latest assistant in pre-fetch state AND `serverMessages` ends with an assistant whose content matches the streamed content → target is that id.
      4. Else → flag as drop (skip step 5 migration; still proceed to step 4 message write).
   4. **Window-replace messages preserving local suffix added after the optimistic turn.** New messages array = `[...serverMessages, ...localSuffix]` where `localSuffix = currentMessages.slice(optimisticPosition + 1).filter(m => !serverMessages.some(s => s.id === m.id))`.
      - **Why `optimisticPosition + 1`, not `serverMessages.length`** (per Codex R5 P1 #2): on a thread already at the 50-message `TRANSCRIPT_LIMIT` (`useResearchChat.ts:10,103`), the server fetch returns the latest 50 INCLUDING the persisted new turn. `serverMessages.length` could equal `optimisticPosition` (server has the persisted turn at the same slot the optimistic occupied) — slicing from `serverMessages.length` would re-include the optimistic user + assistant pair, duplicating the turn. Slicing from `optimisticPosition + 1` correctly preserves only what came AFTER the just-completed assistant.
      - **Suffix de-dup** (per Codex R5 P3 #6): drop suffix entries whose id already appears in `serverMessages` to avoid duplicate React keys in `ConversationFeed.tsx:87`.
      - When the localSuffix is empty (no new turns started during the gap), this devolves to `messages = serverMessages`.
      - **Final sort:** the merged array passes through `sortMessages` before being written, matching the existing `replaceMessages` invariant. Suffix entries (in-flight optimistic for newer turns) carry `createdAt` timestamps, so they sort to the correct chronological positions.
      - **Same-id case still writes messages.** A server-preserved assistant id does NOT mean the rest of the message data (user pending ids, timestamps, server-normalized fields) is identical (per Codex R5 P2 #4). Step 4 ALWAYS writes the new messages array; step 3 only determines whether step 5's migration runs.
   5. **Migrate side-channel.** If target was flagged same-id → no-op (`if (optimisticId === targetServerId) skip`); copy + delete would cancel. Else if target was a different id → `sources[target] = sources[optimisticId]; violations[target] = violations[optimisticId]; delete sources[optimisticId]; delete violations[optimisticId]`. If target was flagged drop → `delete sources[optimisticId]; delete violations[optimisticId]`.
4. **`beginThreadRefresh(threadId): number` (start guard) + `completeThreadRefresh({ threadId, capturedSequence, serverMessages })` (completion guard).** Per Codex R6 P1: a start-only guard is asymmetric — protects the stream-completion reducer from stale fetches, but does NOT protect non-stream `replaceMessages` writes against a newer turn that started after the refresh. If a manual refresh starts at seq=2, then a `sendMessage` runs (seq=3, adds optimistic), then the refresh's fetch returns, the current `replaceMessages` (`researchStore.ts:700`) is unconditional and would blindly overwrite the optimistic turn.

   Slice D requires both halves of the guard:
   - `beginThreadRefresh(threadId)` → increments `reconcileSequence[threadId]`, returns the new value as `capturedSequence`. Every non-stream replacement path MUST call this BEFORE its fetch.
   - `completeThreadRefresh({ threadId, capturedSequence, serverMessages })` → atomic reducer that writes `messagesByThread[threadId] = serverMessages` ONLY IF `state.reconcileSequence[threadId] === capturedSequence`. Mismatch → drop the write (a newer write has superseded). Every non-stream replacement path MUST use this in place of `replaceMessages` for completion.

   Sites that need both calls (per-thread replacement paths only — workspace-scoped writes go through `hydrate` and reset all per-thread state, not through `begin/complete`):
   - Manual user-triggered thread refresh.
   - `retry()` in `useResearchChat.ts:123` (currently calls `fetchResearchMessages` + `replaceMessages`).
   - Any future per-thread refresh path that calls `replaceMessages` outside a stream completion.

   **Workspace-scoped writes** (`bootstrapResearchWorkspace` is a pure loader → `hydrate` reducer at `researchStore.ts:383` is the integration point) are handled separately: `hydrate` resets `citationsByThread`, `reconcileSequence`, and `streamingByThread` to `{}` in its `set(...)` call. No `begin/complete` needed because workspace switches are not racing per-thread replacement writes.

   `sendMessage` ALSO calls `beginThreadRefresh(threadId)` at send-time and captures the resulting sequence. The stream-completion `reconcileResearchTurn` reducer's step 1 checks the captured sequence, exactly as `completeThreadRefresh` does for non-stream paths.

`usePortfolioChat` does NOT call `replaceMessages` (uses local React state — `usePortfolioChat.ts:240`); the optimistic id persists for the message's lifetime. No reconciliation needed.

**Component unmount / workspace switch behavior** (per Codex R8 P3 #3): navigating between threads while the research provider stays mounted is fine — streams target the store by `threadId`, so unrelated threads' state is unaffected. Full workspace/provider unmount triggers `hydrate` (or component unmount), which resets per-thread state; in-flight old streams whose `onComplete` runs against the cleared state will see `state.reconcileSequence[threadId] === undefined`, fail the stale-fetch guard, and no-op. Browser tab close requires no special handling — in-memory side-channel disappears with the page; reload-survival is in Slice D-Persist.

#### Lifecycle hooks (R2 explicit)

The side-channel must respond to message-array mutations to avoid stale data attaching to wrong messages:

| Mutation | Side-channel response |
|---|---|
| `deleteMessage(id)` (`usePortfolioChat.ts:968`) | Delete `sources[id]` and `violations[id]`. Other entries unaffected (id-keyed, not position-keyed). |
| `regenerate()` (`usePortfolioChat.ts:1006` — takes NO id, truncates the tail after the last user message) | Compute the set of removed assistant ids = all assistant messages in `messages.slice(lastUserMessageIndex + 1)`. Clear `sources[id]` + `violations[id]` for every removed id. The regenerated message will get a new id and stream fresh citations. |
| `retryMessage(id)` (`usePortfolioChat.ts` — retry tail truncation, similar shape to `regenerate`) | Same as regenerate — clear all removed assistant ids' citations. |
| Failed assistant placeholder removals (`usePortfolioChat.ts:833,898`) | Clear the failed `assistantMessageId`'s citations (no-op if no citations were attached, still safe). |
| `reload` thread (`usePortfolioChat.ts:1040` / research store reload) | Clear `sources` and `violations` for the entire thread. Reload restarts side-channel from empty (consistent with the Slice D-Persist boundary — server doesn't return citation data). |
| Research `replaceMessages` triggered by stream completion | Run `reconcileResearchTurn` (atomic action above); other thread entries unaffected. |
| Research `replaceMessages` outside of streaming completion (initial load, manual refresh) | Clear all side-channel entries for the thread (no streaming context to migrate from). |
| Research `hydrate(...)` (`useResearchContent.ts:370` — initial bootstrap of workspace state) | Include `citationsByThread: {}` in the hydrate `set(...)` call. Per Codex R4 P2 #5: Zustand `set` does NOT auto-clear keys not mentioned in the partial state, so a workspace switch could leak stale in-memory citations from the previous workspace's thread ids unless explicitly reset. |

Phase 2 implements these hooks alongside the chunk-capture branches.

### Consequences of the model

- The renderer (`<CitedMessage>`) takes explicit `sources` and `violations` props from the per-message lookup. The wrapper just queries `sources[message.id]` / `violations[message.id]` from the per-thread side-channel.
- `tool_result` blocks during streaming attach to the IN-FLIGHT assistant message (the captured `assistantMessageId`). Multiple tool calls in one turn append all their source_envelopes; `registry_snapshot` is server-authoritative dedup, so the last write wins (replace, not merge).
- Lifecycle: id-keyed side-channel is stable under delete/regenerate (the deleted/regenerated id loses its citations cleanly, others stay attached to their owners).
- Across page reload: side-channel is in-memory only and does NOT survive — see Slice D-Persist below.

### Slice D vs Slice D-Persist (explicit scope split)

| Concern | Slice D (this plan) | Slice D-Persist (followup) |
|---|---|---|
| In-session render of chips + sources + banner | ✓ | (already done) |
| Survives `replaceMessages` after stream completion | ✓ via side-channel | (already done) |
| Survives page reload / re-opening a thread | ✗ — falls back to plain | ✓ via server persistence |
| Repo scope | `risk_module` only | Cross-repo: AI-excel-addin (or wherever `/api/research/content/messages` upstream lives) + `risk_module` |
| Effort | 1-2 weeks | TBD — cross-repo coordination required |

**Why the split is sanctioned, not silent deferral:**

1. `/api/research/content/messages` is a proxy in `routes/research_content.py:188-194` that forwards to an upstream API. The upstream owns the message store; risk_module cannot persist citations there alone.
2. In-session preservation (the load-bearing UX — user just got the answer with chips and is reading it now) is fully in scope and shipped in Slice D.
3. Reload-survival is a coherent follow-up scope, named, with a clear cross-repo work item — not "we can add this later."
4. The user-visible degradation on reload (chips disappear, message text remains) is graceful, not broken.

## Frontend codepath inventory (gap audit)

| File | Current behavior | Slice D change |
|---|---|---|
| `frontend/packages/chassis/src/services/ClaudeStreamTypes.ts` | Active `ClaudeStreamChunk` discriminated union (imported by `GatewayClaudeService.ts` and re-exported from `services/index.ts:78`). The legacy `ClaudeService.ts` is NOT the active union. | Add new `citation_validation` variant; add optional `final_tool_result_blocks` to existing `tool_result` variant. |
| `frontend/packages/chassis/src/services/GatewayClaudeService.ts:296-313` | `mapEvent` strips `final_tool_result_blocks` from `tool_call_complete`; no `citation_validation` case (silently dropped — falls through `mapEvent` which returns null). | Pass `final_tool_result_blocks` through on `tool_call_complete`; add new `citation_validation` case that emits the new chunk variant. |
| `frontend/packages/connectors/src/features/external/hooks/useResearchChat.ts:93-97,98-108,123` | `onChunk` callback handles only `text_delta`. `onComplete` (lines 98-108) is fire-and-forget. `retry` (line 123) calls `fetchResearchMessages` + `replaceMessages`. | (a) Capture `tool_result.final_tool_result_blocks[]` source_envelopes → side-channel; capture `citation_validation` → side-channel; (b) make `onComplete` async, await `fetchResearchMessages`, dispatch `reconcileResearchTurn` action, wrap in try/catch (preserve non-fatal fetch behavior); (c) `retry` must call `beginThreadRefresh` before its fetch. |
| `frontend/packages/connectors/src/features/external/contexts/ResearchStreamContext.tsx:57,82` | Stream manager: serializes streams via `currentSendRef.await`; calls `request.onComplete()` synchronously and ignores any returned promise. | (a) Change request type from `onComplete: () => void` to `onComplete: () => void \| Promise<void>`; (b) Change call site from `request.onComplete()` to `await request.onComplete()`. This extends serialization through reconciliation, eliminating the cross-turn race for UI-driven sends. |
| `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts:701` | Inline `for await` chunk loop, NOT an `onChunk` callback. Already handles `text_delta`, `tool_call_start`, etc. | Add new branches in the same `for await` loop for `chunk.type === 'tool_result'` (post-`mapEvent` chunk type — extract `final_tool_result_blocks[]` source_envelopes → side-channel) and `chunk.type === 'citation_validation'` (→ side-channel). Hook return shape extended so `ChatCore` can read citations. |
| `frontend/packages/connectors/src/stores/researchStore.ts` (existing — note: in `connectors` package, not `ui`) | Per-thread message state. `replaceMessages` (line 700) is unconditional. `appendToLastMessage` (line 682) targets last message in array. | (a) Add `citationsByThread: { [threadId]: { sources: { [messageId]: Source[] }, violations: { [messageId]: ValidationEvent } } }`; (b) Add `reconcileSequence: { [threadId]: number }` slice; (c) Add atomic actions `reconcileResearchTurn`, `beginThreadRefresh`, `completeThreadRefresh`; (d) Add `appendToMessage(threadId, messageId, content)` targeting captured id (replaces unsafe `appendToLastMessage` from streaming chunks); (e) Add `streamingByThread: { [threadId]: boolean }` flag; (f) Lifecycle hooks attached to existing message-mutation paths. |
| `frontend/packages/connectors/src/features/external/hooks/useResearchContent.ts:202,365`; `researchStore.ts:383` | `bootstrapResearchWorkspace` (line 202) is a pure loader — fetches messages and returns a payload, does NOT call `replaceMessages` directly (per Codex R7 P2 #2). The store write happens later via `hydrate(payload)` (called at line 365 of the hook → reducer at researchStore.ts:383). | Bootstrap stays a pure loader — no begin/complete needed. **`hydrate` reducer is the integration point**: reset `citationsByThread: {}`, `reconcileSequence: {}`, `streamingByThread: {}` in the `set(...)` call (Zustand does not auto-clear keys not mentioned). Workspace switches go through `hydrate` → all per-thread side-channels and sequence counters reset cleanly. Per-thread `begin/complete` is NOT applied to `bootstrap`/`hydrate` — those are workspace-scoped, not thread-scoped writes. |
| All `replaceMessages` write paths (researchStore.ts:700) | Currently sorts via `sortMessages` at line 284. `fetchResearchMessages` normalizes but does not sort (per Codex R7 P2 #3). | New atomic actions `reconcileResearchTurn` and `completeThreadRefresh` MUST sort `serverMessages` via the existing `sortMessages` utility before positional matching, and sort the final `[...serverMessages, ...localSuffix]` array before write. Without sorting, the `optimisticPosition` lookup is unreliable. |
| `frontend/packages/ui/src/components/chat/shared/ChatCore.tsx` | Renders portfolio chat messages. Calls `MarkdownRenderer.tsx:59` for message body. | No contract change to `ChatCore`. The assistant-message render path becomes `<CitedMessage>` wrapping existing markdown rendering when citation data is present at the turn position. |
| `frontend/packages/ui/src/components/chat/shared/MarkdownRenderer.tsx:59` | `react-markdown` rendering for portfolio chat. | When invoked inside `<CitedMessage>`, opt-in to the `remarkCitations` plugin and add a `components` override mapping the custom citation HAST element to `<CitationChip>`. Default (non-cited) rendering path unchanged. (Inline span underlines on flagged claims are still deferred per locked decision #3.) |
| `frontend/packages/ui/src/components/research/ConversationFeed.tsx:67` | Shared message-rendering surface for research chat — consumed by `AgentPanel.tsx`, `ExploreTab.tsx`, `ThreadTab.tsx`. | The lower-risk integration anchor for ALL research surfaces. Wrap assistant-message render with `<CitedMessage>` here, not per-surface. |
| `frontend/packages/ui/src/components/research/ThreadTab.tsx:78` | Renders messages via `ConversationFeed`. | No direct edit — picks up `<CitedMessage>` via `ConversationFeed`. |
| `frontend/packages/ui/src/components/research/ResearchMessageContent.tsx:88` | `react-markdown` rendering for research messages. | Same as `MarkdownRenderer.tsx` — opt-in to `remarkCitations` plugin + `<CitationChip>` `components` override when invoked inside `<CitedMessage>`. Default rendering unchanged. |
| `frontend/packages/ui/src/components/research/AgentPanel.tsx`, `ExploreTab.tsx`, `ResearchWorkspacePhase*.tsx` | Compose `ConversationFeed`. | No direct edit — pick up `<CitedMessage>` via `ConversationFeed`. |

## Phased implementation

Each phase is independently shippable. Each ends with the existing chat surfaces still working — Slice D is additive, not invasive.

### Phase 1 — Chassis plumbing (foundation)

**Goal:** SSE events reach hook callers without dropping data.

- Extend `ClaudeStreamChunk` (in `frontend/packages/chassis/src/services/ClaudeStreamTypes.ts` — the active union) with a new `citation_validation` variant typed off the cross-repo contract above.
- Add `final_tool_result_blocks?: unknown[]` to the existing `tool_result` chunk type in `ClaudeStreamTypes.ts`.
- Update `GatewayClaudeService.mapEvent` (`GatewayClaudeService.ts:296-313`):
  - `tool_call_complete` case: pass through `final_tool_result_blocks` if present (preserves the inner `source_envelope` blocks for downstream consumers).
  - New `citation_validation` case: emit the new chunk variant.
- Tests: extend `GatewayClaudeService.test.ts` with two cases — `tool_call_complete` carrying `source_envelope` block (with all envelope fields including `_event_only`/`schema_version`/`tool_call_id`), and top-level `citation_validation` event covering the success path plus `validator_error_code: validation_timeout` and `validator_error_code: validator_internal_error` paths.

**Acceptance:**
- Unit tests pass.
- Behavior parity for existing chat surfaces — manual smoke or snapshot test that a non-citation chat turn renders identically pre/post-Phase-1.
- Hook callers see new chunk types but ignore them (no consumer yet) — confirmed by Phase 2 NOT being a precondition for Phase 1's ship gate.

### Phase 2 — Hook state capture (research + portfolio)

**Goal:** Hooks populate side-channel `sources` + `violations` maps keyed by `assistantMessageId` (per the attachment model); maps survive `replaceMessages` via id migration; existing render path unchanged.

- **`useResearchChat.ts`**:
  - Extend `onChunk` (line 93) to handle two new chunk variants. On `chunk.type === 'tool_result'` with `final_tool_result_blocks` populated, extract any `source_envelope` blocks and replace `sources[assistantMessageId]` with their `registry_snapshot` (server-authoritative — replace, not merge). On `chunk.type === 'citation_validation'`, set `violations[assistantMessageId]`. The `assistantMessageId` is captured from the optimistic message creation at line 73 — held in a closure for the stream's duration, never recomputed.
  - **Targeted chunk append + abort cleanup** (per Codex R6 P2 #3 + R7 P3 #4): the existing `appendToLastMessage(threadId, content)` (`researchStore.ts:682`) appends to whatever's at the end of the array. If a manual refresh runs mid-stream and replaces messages, subsequent chunks would append to the wrong message. Replace with `appendToMessage(threadId, assistantMessageId, content)` that targets the captured optimistic id. **If the message is no longer in the array** (refreshed away mid-stream): drop the append AND immediately delete `sources[assistantMessageId]` + `violations[assistantMessageId]` AND mark a closure-local `aborted = true` flag. Subsequent `tool_result` / `citation_validation` chunks for this stream check the flag and no-op (no orphan side-channel writes). The `onComplete` reducer also no-ops when `aborted` (no migration to perform).
  - **`streamingByThread` lifecycle** (per Codex R7 P1): set `streamingByThread[threadId] = true` at send-start (synchronously, before any async work). Clear it ONLY in a `finally` block that wraps the entire stream + reconcile lifecycle — set false after the reconcile dispatch (success or catch). This guarantees the streaming flag covers the full streaming + post-stream reconcile gap, not just the SSE phase. Non-stream refresh entry points check `streamingByThread[threadId]` BEFORE calling `beginThreadRefresh`; if true, defer (or no-op for view-only refresh entry points).
  - Convert `onComplete` (line 98) to `async`. At send-start (in `sendMessage`), call `beginThreadRefresh(threadId)` and capture the returned sequence into the stream-start closure as `capturedSequence`. Also capture `optimisticPosition` (the index where the optimistic placeholder was inserted). Inside `onComplete`: try { `serverMessages = await fetchResearchMessages(...)`; dispatch `reconcileResearchTurn({ threadId, optimisticId, optimisticPosition, capturedSequence, serverMessages })` } catch (any error including reducer-thrown) { drop side-channel for this optimisticId; log. Do NOT rethrow — preserve existing non-fatal fetch behavior. }.
  - Modify `retry` (line 123): call `const seq = beginThreadRefresh(threadId)` BEFORE its `fetchResearchMessages`; on response, call `completeThreadRefresh({ threadId, capturedSequence: seq, serverMessages })` instead of the existing `replaceMessages`. On fetch error, drop nothing (this path doesn't own a side-channel entry).
- **`ResearchStreamContext.tsx`**:
  - Change request interface: `onComplete: () => void` → `onComplete: () => void | Promise<void>`.
  - Change call site at line 82: `request.onComplete()` → `await request.onComplete()`.
  - Existing `currentSendRef.await` serialization (line 57) now extends through reconciliation.
- **`usePortfolioChat.ts`**: extend the inline `for await` loop at line 701 with two new branches: `chunk.type === 'tool_result'` (handles what was raw `tool_call_complete` upstream — note: `GatewayClaudeService.mapEvent` rewrites `tool_call_complete` to chunk type `tool_result` at `GatewayClaudeService.ts:306`) and `chunk.type === 'citation_validation'`. Use the existing `assistantMessageId` constant set at `usePortfolioChat.ts:662` (the message placeholder is appended at line 672). Hook return shape extended so consumers (specifically `ChatCore`) can read `sources[messageId]` / `violations[messageId]` from the hook's per-thread side-channel maps. No `replaceMessages` migration needed — `usePortfolioChat` uses local React state.
- **Stores**: `researchStore` and the portfolio-chat state slice each gain `citationsByThread: { [threadId: string]: CitationsByMessage }`. Crucially, the message-array operations (`replaceMessages`, `setMessages`) are NOT modified — the side-channel is a separate slice. The lifecycle hooks (`deleteMessage`, `regenerate`, `reload`) per the table in §"Citation→message attachment model" are added.
- **Lifecycle wiring** for `usePortfolioChat`:
  - `deleteMessage(id)` (line 968): also delete `sources[id]` + `violations[id]`.
  - `regenerate()` (line 1006 — takes no id, truncates tail after last user message): clear citations for ALL removed assistant ids in `messages.slice(lastUserMessageIndex + 1)`. The new stream will populate fresh under a new assistant id.
  - `reload(threadId)` (line 1040): clear the thread's `citationsByThread[threadId]` entirely.
- **Lifecycle wiring** for `useResearchChat`: research store's `replaceMessages` outside of an active stream → clear the thread's citations slice. Inside an active stream, run the migration step instead.
- Tests:
  - `useResearchChat.test.tsx`: stream a turn with `tool_result` (carrying source_envelope) + `citation_validation` + `stream_complete` + simulated `replaceMessages` with a different server id. After replacement, `sources[serverId]` is populated and `sources[optimisticId]` is gone (migration succeeded).
  - `useResearchChat.test.tsx` TRANSCRIPT_LIMIT edge (per Codex R6 P3 #4): pre-load a thread with 49 messages. Send a turn (user inserted at 49, optimistic assistant at 50). Server returns latest 50 INCLUDING the persisted new turn at index 49 (older messages dropped by pagination). Migration target identification falls back to the "ends with assistant whose content matches" path, NOT the direct slot match. Verify migration succeeds and side-channel ends up keyed under the server id.
  - Refresh-then-send race: `beginThreadRefresh` (seq=2) → call `sendMessage` (seq=3, optimistic added) BEFORE refresh fetch resolves → refresh fetch resolves → `completeThreadRefresh({capturedSequence: 2, ...})` → reducer detects mismatch, drops the write. Optimistic turn preserved.
  - Mid-stream refresh guard: with `state.streamingByThread[threadId]` set, non-stream refresh entry points skip / defer.
  - `usePortfolioChat.test.tsx`: stream a turn with the inline-loop hook. Verify `sources[assistantMessageId]` populated. Verify `deleteMessage(id)` clears it. Verify `regenerate()` clears citations for all assistant ids in the truncated tail (multi-turn fixture: turn 1 + turn 2 + regenerate from turn 1's user message → both turn 1's and turn 2's assistant citations should be cleared).
  - Chassis-level test: `tool_result` carrying `final_tool_result_blocks` is forwarded with the field intact (already covered in Phase 1, listed here for cross-phase visibility).

**Acceptance:**
- Existing renderers ignore citation metadata (no UI change visible).
- `useResearchChat` simulation: stream a turn with `tool_result` carrying `source_envelope` + a `citation_validation` event + `stream_complete` + simulated `replaceMessages` with a new server id. After migration, `sources[serverId]` is populated with the `registry_snapshot` and `sources[optimisticId]` is gone.
- `usePortfolioChat` simulation: same shape with the inline-loop hook (no migration step). Verify `sources[assistantMessageId]` populated after stream.
- Phase 2 ships behavior-neutrally to users (no consumer yet); Phase 4 makes the data visible.

### Phase 3 — Components (CitedMessage, SourcesList, ValidationBanner)

**Goal:** Three reusable components, ready to drop into any chat surface.

- `<CitedMessage text={...} sources={...} violations={...} markdownVariant="portfolio" | "research">` — combines three responsibilities for assistant message rendering when citation data is present:
  1. **Inline `[Sn]` chip rendering** — implemented as a **remark plugin** (`remarkCitations`) that runs during markdown AST construction. The plugin walks `text` nodes in the mdast and splits them into `[text, citation, text, ...]` segments wherever `[Sn]` tokens are found, emitting custom `citation` HAST elements (e.g., `<span data-citation-index="1">`). A standard `components` override on `react-markdown` v10's `Components` map (`react-markdown@10.1.0` per `frontend/packages/ui/package.json:45`) renders those custom elements as `<CitationChip>` React components with full source data passed as props. (Per Codex R4 P2 #3: the plan's earlier "text-renderer override" approach used an API that doesn't exist in v10 — `components` only maps element tag names. The remark-plugin approach IS the correct anchor for this pattern in v10.) The same plugin is used by both `MarkdownRenderer.tsx` and `ResearchMessageContent.tsx` callers; existing per-surface markdown plugins (e.g., portfolio's `:::ui-block` handling) compose alongside `remarkCitations` without conflict.
  2. **Sources footer** — `<SourcesList sources={sources}>` rendered below the message body.
  3. **Validator banner** — `<ValidationBanner event={violations}>` rendered above the message body (or below — TBD design call during Phase 4 live render).
- `MarkdownRenderer.tsx` and `ResearchMessageContent.tsx` get a small edit: their `react-markdown` instances opt-in to the `remarkCitations` plugin and the `<CitationChip>` component override when rendered inside `<CitedMessage>`. Edits are additive — non-cited rendering paths are unchanged.
- `<SourcesList sources={...}>` — full per-turn source list. Renders document_id + section + filing_date / fiscal_period + ticker + a clickable URL anchor (prefer `source_url_deep`, fall back to `source_url`). Single component; consumers pass layout container.
- `<ValidationBanner event={...}>` — banner above or below the assistant message. Uses Lucide `AlertTriangle` (or equivalent) icon — not a raw `⚠` glyph — for consistency with the design system (per Codex R1 P3). Banner state derives from the citation_validation event:

  | `validator_error_code` | Banner state | Banner text |
  |---|---|---|
  | absent + `violation_count > 0` | "violations" | `Unsourced claims ({violation_count}) · click to expand` |
  | absent + `violation_count == 0` | hidden | (no banner — clean turn) |
  | `validation_timeout` | "validator-degraded" | `Validation timed out — {pending_task_count} pending` |
  | `validator_internal_error` | "validator-degraded" | `Validation unavailable` |

  Banner UX keys off `validator_error_code` directly (per Codex R2 P5: upstream emits `validator_internal_error` with `warning_codes: []`, so warning_codes is not a reliable signal). Click on a "violations" banner reveals a panel listing each violation: `claim_text`, `reason` (e.g., "judge_flagged"), `detector` (regex / judge), `cited_indexes`, and `fabricated_index` if present (mark fabricated chip refs visibly — these are `[Sn]` references the LLM made up that have no entry in the registry). Click on a "validator-degraded" banner reveals `warning_codes` if present plus the explicit error reason — gives the user transparency that validation didn't run cleanly, which is precisely the failure mode that erodes institutional trust if silently skipped.

  **Edge precedence rules** (per Codex R3 P3 #7):
  - Compute violation count from `violation_count ?? violations.length` — handles future schema variants.
  - Unknown `validator_error_code` (a future code we haven't seen) → treat as "validator-degraded" with the raw code shown. Don't crash, don't hide.
  - If a `validator_error_code` event ALSO has non-empty `violations` (shouldn't happen today but defensible) → show "validator-degraded" status while still exposing the violation list. Degraded takes precedence on the banner state, but violations remain visible.
- Tests for each component with fixture data: a clean turn (no violations); a turn with three violations including one `fabricated_index`; an empty-sources turn (component degrades to plain rendering); a `validator_error_code: validation_timeout` event (banner shows "validation timed out — N pending" not "0 violations").

**Acceptance:** components render correctly with fixture data; tests pass; components can be imported but no surface uses them yet.

### Phase 4 — Wiring into existing surfaces

**Goal:** Citation UX live on both surfaces, integrated at the lowest-risk shared anchors.

- **Research surfaces — single anchor**: `ConversationFeed.tsx:67` is the shared message-rendering surface consumed by `AgentPanel.tsx`, `ExploreTab.tsx`, `ThreadTab.tsx`, and any `ResearchWorkspacePhase*` consumer. Wrap assistant-message render with `<CitedMessage>` here. All four surfaces pick up the change automatically — no per-surface edits needed.
- **`ThreadTab` slice handling**: `ThreadTab.tsx:29,78` passes `messages.slice(-4)` as `visibleMessages` into `ConversationFeed`. Because side-channel keys are `assistantMessageId` (R2 model), the slice does not affect citation lookup — each visible message looks up `sources[message.id]` directly. No special handling required.
- **Main chat surfaces — single anchor**: `ChatCore.tsx` wraps assistant-message render with `<CitedMessage>`. `AIChat` (modal) and `ChatInterface` (full-screen) both wrap `ChatCore` (verified at `AIChat.tsx:141` and `ChatInterface.tsx:125` per Codex R1) — no per-surface edits.
- **`renderBody` selection**: `ConversationFeed` uses `ResearchMessageContent`; `ChatCore` uses `MarkdownRenderer`. `<CitedMessage>` accepts each as the `renderBody` prop — preserves their existing markdown handling.
- **`SourcesList` placement (v1)**: per-turn footer right below the assistant message body. Fits both modal `AIChat` (constrained width but vertical space available) and full-screen `ChatInterface`. Sidebar variant explicitly deferred — wait for actual usage feedback before building a more complex layout.
- **Live verification**: same MSFT/GOOG cross-source cloud query used as the live anchor for Slices A+B+C (≈30 distinct `[Sn]` references). Run on both research and main chat. Verify: chips render styled, sources footer populated, banner appears for any violations, side-channel data persists across the post-completion `replaceMessages` (test by sending a follow-up message and confirming previous chips remain).

**Acceptance:** end-to-end live verification on dev. Both surface families show chips + sources + (when violations exist) banner. Existing non-citation chat turns render identically (regression check).

## Out of scope (explicit deferrals — sanctioned, not silent)

- **Slice D-Persist — citation reload survival.** Page reload / re-opening a thread loses the side-channel maps. Reload-survival requires server-side persistence of source_envelope + citation_validation events on the upstream that owns `/api/research/content/messages` (a proxy from this repo, see `routes/research_content.py:188-194`). That's cross-repo work with a real coordination cost. Slice D ships in-session preservation (the load-bearing UX); Slice D-Persist is filed as the named follow-up scope, with explicit upstream + frontend deltas needed. **NOT** "we can add this later" — named slice with clear scope, gated by cross-repo coordination availability.
- **Inline yellow underlines on flagged claim spans.** Per locked decision #3 + Codex R1 P3 confirmation: `react-markdown` node-tree span injection across already-parsed markdown is real complexity (span offsets become wrong after parsing). Banner with expandable violation list is a sufficient institutional-trust signal for v1. Filed for v1.5 if user feedback shows banner-only is insufficient.
- **Sidebar `<SourcesList>` variant.** v1 ships footer-only. If the modal `AIChat` constraint or the full-screen `ChatInterface` layout proves the footer doesn't read well, a sidebar variant of the same component is straightforward — but ship the footer first and use real renders to drive layout.
- **Slice E (span-scroll iframe — Fintool-style click-to-source).** Blocked on F44 (markdown↔HTML offset map) which is not yet implemented.
- **Slice C.3 (TUI citation_validation event handling).** Different surface (TUI in AI-excel-addin), filed in `V2_P2_CITATION_FIRST_QA_PLAN.md`.
- **Validation hard-mode** (block render on violations). Slice B ships soft-mode by default; flipping to hard-mode is a server-side configuration, not a frontend change. Out of Slice D scope.
- **`fabricated_index` chip behavior beyond marking.** v1 marks fabricated `[Sn]` refs visually (Phase 3 ValidationBanner panel lists them). Behavior beyond marking — auto-suppressing the [S99] chip from rendered text, replacing with a "?" — out of v1 scope. Marking is sufficient for institutional-trust v1; suppression is layout-engine work.

## Testing

- **Unit:** chassis mapEvent (Phase 1), hook state (Phase 2), components (Phase 3). Covers the `validator_error_code` paths (timeout, internal_error) — banner should still render with empty violations + warning code.
- **Integration:** spin up the gateway with a real corpus query; verify chassis chunks → hook state → component render. Use the same MSFT/GOOG cross-source query that was the live-verification anchor for Slices A+B+C.
- **Regression:** existing `ChatCore.approval.test.tsx`, `useResearchChat.test.tsx`, `usePortfolioChat.test.tsx` continue to pass without changes.

## Open questions

1. **Source list placement on main chat (`AIChat` modal).** The modal is bottom-right floating; a per-turn footer is natural but space-constrained. Phase 4 ships footer; whether to ship a sidebar variant for the full-screen `ChatInterface` is a layout call best made during the Phase 4 live render rather than predetermined.
2. **`fabricated_index` chip rendering.** Phase 3 marks fabricated chips visually in the validator banner. Should the inline chip itself also render differently (disabled / red-tinted) to flag fabrication at the cite site? Lean: yes, but keep the fix simple — disable the anchor link, add a tooltip "source not in registry." Final call during Phase 3 when chip styling is concretely designed.
3. **Side-channel size budgeting.** Long-running threads accumulate `sources[id]` entries indefinitely. At 100+ assistant messages × ~20 sources each, the in-memory map is meaningfully large but still small in absolute terms (~tens of KB). v1 ships uncapped; if real usage shows long sessions causing perf issues, add a `MAX_MESSAGES_RETAINED` cap as a Slice D follow-up. Not blocking impl.

## References

- `docs/planning/V2_P2_CITATION_FIRST_QA_PLAN.md` — overall V2.P2 plan, Slice D row
- `docs/planning/completed/V2_P2_SLICE_A_PLAN.md` — citation envelope contract
- `docs/planning/completed/V2_P2_SLICE_B_PLAN.md` — validator gate contract
- `AI-excel-addin/api/agent/shared/citations.py:41` — Violation dataclass
- `AI-excel-addin/api/agent/shared/citation_validation_event_log.py:152` — citation_validation event emitter
- `AI-excel-addin/packages/agent-gateway-tui/src/source-registry.ts` — TUI Source type (TS reference for frontend types)
- `AI-excel-addin/packages/agent-gateway-tui/src/event-adapter.ts:342` — TUI extractSources implementation (algorithmic reference)
