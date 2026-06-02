# Agent Control Surface — UI/UX Target And Implementation Plan

**Date:** 2026-05-31  
**Status:** Draft target for review  
**Preview:** `docs/design/agent-control-surface-preview.html`  
**Primary surface:** `/analyst` primary chat view, not the dashboard sidebar and not a popup/modal chat

## 1. Starting Point

The agent-control foundation exists in the sibling `AI-excel-addin` repo and is usable today:

- `agent_gateway/control_plane/` exposes the shipped `/control/*` HTTP plane for health, skills, runs, logs, schedules, artifacts, approvals, and SSE events.
- `packages/agent-gateway-cli` exposes `agent_gateway_cli control ...` as the JSON-first non-interactive client.
- `packages/agent-gateway-tui` exposes slash-command control in the TUI.
- Live read-only smoke on 2026-05-31 against the `excel-addin` namespace confirmed:
  - `/control/health` available, version `1`, channel `cli`.
  - `GET /control/skills` returned the full skill catalog.
  - `GET /control/runs` returned one live chat run.
  - `GET /control/approvals`, `/control/schedules`, and `/control/artifacts` returned empty arrays cleanly.
- Local control-client verification:
  - CLI focused control tests: `124 passed`.
  - TUI package tests: `72 passed`.
  - TUI integration tests: `11 passed`.

The Hank web UI already has the right primary host surface:

- `frontend/packages/ui/src/components/apps/AnalystApp.tsx` owns `/analyst`.
- `frontend/packages/ui/src/components/layout/ChatInterface.tsx` renders the full-screen analyst chat route.
- `frontend/packages/ui/src/components/chat/shared/ChatCore.tsx` owns message rendering, composer, inline approvals, artifacts, citations, and streaming status.
- `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts` owns chat state and gateway stream orchestration.
- `frontend/packages/chassis/src/services/GatewayService.ts` owns `/api/gateway/chat` SSE transport and `/api/gateway/tool-approval`.

The main architectural gap in `risk_module` is not the UI. It is the missing web proxy/client layer for `/control/*`; the current proxy only forwards chat and foreground tool approvals.

## 2. Product Goal

The agent-control surface should make autonomous agent work visible, steerable, and reviewable inside the same place the user already talks to the analyst.

The target experience should feel closer to the Codex app than to a SaaS dashboard:

- The conversation remains the command center.
- Background work is visible as live, inspectable runs, not hidden jobs.
- Tool calls, approvals, artifacts, logs, and state changes appear as a coherent work trace.
- Control is immediate: dispatch, watch, approve, deny, cancel, resume/review.
- A selected control run expands in the main chat surface into a Codex-style working/output thread where the user can see the run's actual output and steer the run directly.
- The side control deck is the selector, queue, approval, metadata, and control surface. It should not become a second full chat surface competing with the main thread.
- Run artifacts are reviewable as human-facing visual outputs, not only as machine-readable contract payloads or file links. The existing artifact panel becomes the visual review lane for skill/run results.
- The interface is dense, editorial, and operational. No card quilt, no marketing layout, no decorative chrome.

## 3. UI Direction

### 3.1 Layout

Use the existing `/analyst` shell and extend `ChatInterface` into a two-zone work surface:

1. **Analyst Thread**
   - Main conversation column.
   - Existing chat messages, citations, artifacts, inline approvals, and composer remain here.
   - Run activity can also appear inline as compact event strips when launched from the conversation.
   - When no run is selected, this remains the normal Hank chat.
   - When a run is selected or actively watched, this main surface becomes the selected run's output thread: streamed agent output, run events, citations, artifacts, and operator messages appear here in the same conversational reading surface.
   - If Hank launches or references a run, the main thread may show a compact run chip/event strip inside Hank's response, for example: `RUN bg_184 · COMPETITIVE-POSITION · MSFT` followed by "Agent is building the peer set and checking source coverage."
   - The side deck should not duplicate the full selected-run transcript. It may show compact status/log tail previews, but the readable output belongs in the main surface.

2. **Control Deck**
   - Docked inside the analyst chat surface, not the app sidebar.
   - Width target: `340-380px` desktop.
   - Collapses below `lg` into a priority bottom sheet/rail, not a full block above the chat. Pending approvals and blocking states appear first when expanded.
   - Shows health, active runs, approvals, recent artifacts, quick dispatch state, log tail, and selected-run controls.
   - It must not contain a duplicate selected-run transcript block or a side steering composer. The selected run's transcript and steering composer belong in the main analyst thread.

This is intentionally different from the current `ArtifactPanelConnected` slide-over. Artifacts are output inspection; the control deck is live operation.

#### Human Artifact Render Lane

The artifact panel is the human artifact render lane for run and skill outputs. It should display the reviewable visual result of an artifact: thesis scorecards, model summaries, comp tables, scenario trees, evidence diffs, sandboxed HTML reports, or other contract-backed visuals. It is not merely a raw JSON/file inspector.

Keep the distinction explicit:

- **Machine artifact:** the typed contract, sidecar, schema payload, file path, or binary output passed between workflow stages and agents.
- **Human artifact render:** the visual view-model derived from that contract for analyst review, approval evidence, reuse, and eventual report inclusion.

These two objects share identity and provenance (`artifact_id`, `run_id`, `skill_run_id`, `contract_name`, source references, timestamps, and export handles), but they serve different users. The machine artifact supports workflow continuity; the human render supports decision review.

Agent control should route artifacts into the artifact panel from three places:

- artifact rows in the control deck `Recent` / selected-run metadata
- artifact references inside the selected-run main thread
- approval evidence steps such as `Review Evidence`

The control deck may show artifact titles, status, contract names, compact provenance, and open actions. It should not render full artifact details. When an artifact is open, the deck compresses to an approval/status rail on constrained desktop widths so the user can keep approving or denying while reviewing evidence.

The static HTML preview includes an outer documentation header and framed workspace only so the target can be reviewed in isolation. Production stays in the existing full-height `/analyst` route: `AnalystSidebar` plus the primary chat workspace.

Artifact coexistence uses lane arbitration instead of two permanent right panels:

- **Operator state:** chat thread plus full control deck.
- **Evidence review state:** existing `ArtifactPanelConnected` remains the artifact viewer; the control deck compresses to an approval rail/inspector pinned in the chat surface so approve/deny remains visible while evidence is open.
- **Small screens:** the control deck becomes a bottom sheet/rail so the main thread remains the primary surface. When expanded, blocking approvals become the first control item before non-blocking run history.

### 3.2 First-Viewport Target

The first viewport should show:

- The analyst conversation/output thread as the largest visual object. In normal mode it is Hank chat; in watch/selected-run mode it shows the selected agent run's output in that same main reading surface.
- A right control deck with:
  - A compact header with `Agent Control` and an icon-only hide/show control. Avoid visible healthy-state implementation metadata such as `online`, `v1`, route names, or a separate full-width page status strip; surface health/version only when degraded or in secondary details.
  - When collapsed, keep a small persistent affordance with blocking-state visibility, for example an approval badge, so hiding the deck does not hide urgent decisions.
  - `Now` section: active/in-progress run cards only. Include states such as `starting`, `running`, `queued`, `waiting`, and `approval_pending` when present; selecting a card makes that run the main surface's selected-run output thread.
  - `Waiting` section: approvals or blocked runs.
  - `Dispatch` section: compact `New Agent` launch affordance that moves the user into the main composer agent flow; it is not a persistent profile/mode/skill/ticker form.
  - `Recent` section: completed, failed, cancelled, or otherwise terminal runs and artifacts. Artifact rows open the human render in the artifact panel, not a raw file drawer.
  - `Log Tail` section: compact latest events/logs for the selected run.
  - A compact deck header jump nav may mirror these sections. Labels should be operational section anchors such as `Waiting`, `Now`, `Dispatch`, and `Logs`; they are not separate chat modes and should not imply a side run-session surface.
- The composer with a segmented mode:
  - `Chat` sends a normal analyst chat message.
  - `Agent` prepares an autonomous dispatch draft.
  - `Watch <run>` keeps chat scoped to a selected run without issuing control writes.

### 3.3 Interaction Model

Core workflows:

- **Observe**
  - Read live run state.
  - Watch selected-run output stream into the main chat surface.
  - Watch compact state/events in the deck and selected run timeline.
  - Open logs without leaving the chat route.
  - Keep detailed readable run output in the main surface; keep dense operational metadata in the deck.

- **Dispatch**
  - Expose backend-available profiles from the skill/control catalog instead of hiding profiles in the web UI.
  - Gate by action class and approval policy, not by profile visibility.
  - The main composer captures the user's natural-language task in `Agent` mode.
  - Hank/control preflight infers mode, skill, ticker/context, profile, and guardrails from the task, current thread, and catalog.
  - The deck `Dispatch` section provides a `New Agent` shortcut that focuses or switches the main composer into `Agent` mode; it should not collect the task itself.
  - The user can review and adjust inferred fields in the preflight step when needed.
  - Dispatch creates a run card and selects it.
  - Agent-mode Enter opens a preflight confirmation; the actual autonomous launch requires an explicit `Dispatch` action. There is no one-keystroke autonomous launch.

- **Approve**
  - Foreground chat approvals stay inline in `ChatCore`.
  - Cross-session approvals appear in the control deck.
  - Approval cards show tool name, class, blast radius, reason, exact approve/deny actions, run id, session id, approval id, target object, consequence, sources, and the proposed diff or command payload.
  - Durable writes use an approval inspector rather than a compact card. Label the primary evidence step `Review Evidence`; the approve action remains disabled or de-emphasized until evidence/diff inspection is available.
  - Approval policy should stay low-friction: reads, logs, source gathering, calculations, and artifact generation do not ask for approval by default.
  - Durable memory/research writes require approval, and related writes should batch into one decision whenever the backend can present one coherent diff/payload.
  - Destructive, external, or high-blast-radius actions require explicit confirmation even if they are not durable research writes.

- **Review**
  - Selecting a run opens its readable output/timeline in the main chat surface and keeps compact logs, artifacts, cost, verdict, and final status discoverable from the control deck.
  - Artifacts continue to open through the existing artifact surface. The control deck passes artifact references to `ArtifactPanelConnected`; it does not render full artifact details itself.
  - The artifact panel is the canonical human review surface for run artifacts. For stable recurring contracts it should resolve to curated React renderers/registries; for long-tail outputs it should resolve to the sandboxed HTML artifact renderer once F122 lands; for future report assembly it should expose stable artifact references that presentation packs can consume.
  - Opening an artifact should preserve context: the selected run stays selected, the main thread remains the run/output surface, and the artifact panel shows the human render with provenance, source links, and export/reuse affordances.
  - Terminal runs leave `Now` and remain discoverable from `Recent`; resumable interrupted runs may show a resume affordance from their selected-run controls, but should not be presented as active unless the backend marks the replacement/resumed run active.

- **Steer**
  - Selecting a run expands it in the main chat surface into a selected-run output view with transcript/events and a message composer, matching the Codex pattern where selecting a side run opens its output in the primary thread surface.
  - The deck remains the control and metadata lane for that selected run, not a separate agent chat window.
  - Direct run messages use `POST /control/runs/:run_id/messages`.
  - Chat-kind runs continue with the existing full client-owned transcript contract and the chat-session credential returned by chat dispatch.
  - Autonomous control-plane runs are top-level `agent.autonomous` subprocesses, not the same object as in-process `run_agent(background=true)` task-registry entries. V1 therefore requires a small upstream bridge on the same route: `{ message, message_id? }` is appended to a per-run operator inbox owned by `AutonomousRegistry`, published as a `parent_message_sent`/operator-message control event, and consumed by the child autonomous runtime into the existing `AgentRunner.message_inbox` pattern before the next model turn.
  - The existing `send_message` plumbing remains the behavioral model for idempotency, event shape, and message injection, but the gateway cannot call a child-process runner ref directly.
  - Interrupted resumable autonomous runs expose `Resume` in the session header only when the upstream control plane marks the run resumable. Existing `resume_background_agent` supports in-process background sub-agents; top-level control-plane autonomous resume is a new bridge that must reconstruct the autonomous run from its durable log/events and link the resumed run back to the original.

- **Interrupt**
  - Cancel/stop is visible on running or waiting autonomous runs.
  - Destructive actions require confirmation in UI, matching CLI/TUI behavior.

Composer semantics:

- `Chat`: Enter sends the existing analyst chat message through `usePortfolioChat`.
- `Agent`: Enter opens a dispatch preflight panel from the typed task. The user confirms or edits inferred profile, skill/mode, context, and guardrails, then clicks `Dispatch`.
- `Watch <run>`: Enter operates in selected-run context. The main surface shows the selected run's output; the composer sends a normal Hank question about that run and must not issue control-plane writes.
- Direct steering: when the main surface is in selected-run mode, an explicit main-thread steering composer calls `/control/runs/:run_id/messages`. The payload shape is run-kind specific, but there is no side-deck steering composer.

### 3.4 Visual Rules

Follow `DESIGN.md`:

- Dark-first.
- Instrument Sans for analyst prose and UI.
- Geist Mono for ids, states, logs, timestamps, and compact metadata.
- Gold only for direct analyst/action signal.
- Gold is reserved for pending decisions and primary agent actions. Run progress, selected cards, active tabs, and generic activity use neutral borders or blue signal.
- Green/red only for financial direction or terminal success/failure state where semantically equivalent.
- 3-6px radius; avoid the current chat bubble drift toward larger radius.
- Dense tables/lists for control resources.
- Thin borders and typographic grouping over card-heavy composition.

Codex-app modeling should be functional more than literal:

- Conversation + work trace as the dominant mental model.
- Active background jobs visible without a modal.
- A selected-run inspector that expands into an agent session with direct steering.
- Composer as the launch surface.
- Clear status of what the agent is doing now.

## 4. Frontend Architecture

Respect the existing package hierarchy:

```text
@risk/app-platform
  -> @risk/chassis
  -> @risk/connectors
  -> @risk/ui
```

### 4.1 Backend Proxy Prerequisite

Add a web-safe control proxy to `app_platform.gateway` and mount it through `routes/gateway_proxy.py`.

Candidate browser-facing namespace:

```text
/api/gateway/control/session      internal bootstrap, not public API-key passthrough
/api/gateway/control/health
/api/gateway/control/skills
/api/gateway/control/runs
/api/gateway/control/runs/:id
/api/gateway/control/runs/:id/messages
/api/gateway/control/runs/:id/resume
/api/gateway/control/runs/:id/logs
/api/gateway/control/runs/:id/approvals/:approval_id
/api/gateway/control/events
/api/gateway/control/schedules
/api/gateway/control/artifacts
```

Implementation notes:

- The browser never receives `GATEWAY_API_KEY`.
- The proxy owns channel identity. It strips any client-provided channel, bootstraps `POST <gateway>/api/control/session` server-side using the configured gateway key, resolved user id/email, and `context.channel = "web"`.
- V1 write scope is autonomous dispatch/cancel, run messaging/steering, resumable autonomous resume, chat-kind run creation/continuation, and approval/deny handling. Schedule writes are deferred.
- Control-session tokens should be cached separately from chat tokens. Do not reuse `/api/chat/init` tokens for `/control/*`.
- Chat-kind control runs return `chat_session_token`, `chat_session_id`, and expiry. The proxy should store these server-side by user/run id or encrypt them in an HTTP-only session mechanism; do not expose gateway-issued chat-session bearer tokens to arbitrary browser code.
- `/control/events` is an SSE stream and should not use the chat stream lock. A user should be able to chat while watching agent-control events.
- Retry behavior should mirror chat where sensible: refresh control token on session/auth expiry and retry once for idempotent requests.
- Contract health should require `X-Control-Plane-Version: 1` or equivalent body version before enabling the UI.
- Dispatch payloads use the server-resolved channel. The browser may choose from an allow-listed profile and skill/mode, but cannot override channel claims.
- V1 implements `POST /control/runs/:run_id/messages` for both chat-kind and autonomous runs.
  - Chat-kind payload: `{ messages: ChatMessage[], request_id?, context?, model?, deadline_sec? }`; the browser sends the client-owned transcript to the risk-module proxy, and the proxy attaches the chat-session credential for that run.
  - Autonomous payload: `{ message: string, message_id?: string }`; the upstream control plane resolves the run to an `AutonomousRegistry` record, verifies user and channel ownership, rejects terminal/non-steerable states, appends the message to the run's operator inbox with exactly-once `message_id` handling, publishes a `parent_message_sent` control event, and returns the refreshed run snapshot plus delivery metadata.
- V1 adds or verifies a resume route for interrupted resumable autonomous runs. This is not a direct call to the current `resume_background_agent` tool, which resumes in-process background sub-agents. The top-level autonomous resume route must create a new control run from the original autonomous transcript/events, carry forward parent messages, return the resumed run, and link `resumed_from`.
- `/control/artifacts` is a recent-artifact index. Artifact detail is opened through the existing artifact viewer/proxy, not a new control detail endpoint.

#### 4.1.1 Upstream Autonomous Steering Bridge

The focused architecture review found one hard boundary to make explicit before implementation: the shipped `/control/runs` autonomous path is backed by `AutonomousRegistry`, which spawns `python -m agent.autonomous` as a subprocess and tracks `AutonomousTask` records. The existing `send_message` and `resume_background_agent` handlers live inside `AgentRunner` and operate on in-process `TaskRegistry` entries created by `run_agent(background=true)`. They prove the UX and runtime pattern, but they are not directly callable for a top-level control-plane autonomous subprocess.

V1 should add the bridge in the upstream control plane before the risk-module proxy treats autonomous steering as available:

- Extend the control-plane messages route so the request body is discriminated by run kind instead of being hard-typed only as `ChatContinuationRequest`.
- Add `AutonomousRunMessageRequest`: `{ kind?: "autonomous", message: string, message_id?: string }`.
- Add a per-run operator inbox to `AutonomousRegistry`, most likely a JSONL file path injected into the child as `AGENT_AUTONOMOUS_OPERATOR_INBOX_PATH` plus in-memory delivered-message tracking on the gateway record.
- Add a child-runtime tail/poll task in `api/agent/autonomous/runner.py` that converts operator inbox rows into `ParentMessage` entries for the top-level `AgentRunner.message_inbox`.
- Reuse the existing `AgentRunner` behavior that injects parent messages before the next model turn. Mid-tool or mid-provider-call messages are accepted immediately but become model-visible on the next turn.
- Write `parent_message_sent` events with the same durable schema used by the existing `send_message` handler so SSE, transcript reconstruction, and resume all see a consistent event type.
- Verify user id and channel on every message. Existing autonomous lookup checks user ownership; the bridge must also compare the authenticated control session channel with the autonomous record channel.
- Return an idempotent delivery response for duplicate `message_id` values rather than enqueueing twice.

Top-level autonomous resume is also new upstream work:

- Define which autonomous terminal/interrupted states are resumable. Current `AutonomousRunState` only exposes `starting`, `running`, `completed`, `failed`, and `cancelled`; add a resumable/interrupted signal before exposing the UI action.
- Reconstruct the autonomous transcript from the child session log and control events, including prior parent messages.
- Start a new `AutonomousRegistry` run linked by `resumed_from` / `original_run_id`, not an in-process background task resume.
- Return `409` for non-resumable runs and `404` across user/channel boundaries.

### 4.2 `@risk/chassis`

Add typed transport and schemas:

- `services/ControlGatewayService.ts`
  - `health()`
  - `listSkills()`, `getSkill(name)`
  - `listRuns(filters)`, `getRun(id)`, `getRunLogs(id, tail)`
  - `dispatchRun(payload)`
  - `sendRunMessage(runId, payload)`
  - `resumeRun(runId, payload)`
  - `cancelRun(id)`
  - `listApprovals()`, `decideApproval(sessionId, approvalId, decision)`
  - `listSchedules()`, schedule writes as later gated scope
  - `listArtifacts(filters)`
  - `subscribeEvents(runId?, signal)`
- `services/ControlGatewayTypes.ts`
  - Mirror `Skill`, `Run`, `Schedule`, `Artifact`, `ApprovalRequest`, and `ControlEvent`.
  - Add discriminated response types for `ChatDispatchResponse` and `AutonomousDispatchResponse`; only chat dispatch includes chat-session credentials.
  - Add discriminated request types for `ChatRunMessageRequest` and `AutonomousRunMessageRequest`.
- Reuse the existing `parseSSE` helper or move it to a neutral shared module.
- Add control-run message continuation for chat-kind runs and parent-message delivery for autonomous runs in v1. Keep the API typed as discriminated payloads so the UI has one direct-steering concept without blurring backend semantics.

### 4.3 `@risk/connectors`

Add a control feature slice:

- `features/agentControl/hooks/useControlHealth.ts`
- `features/agentControl/hooks/useControlRuns.ts`
- `features/agentControl/hooks/useControlRun.ts`
- `features/agentControl/hooks/useControlEvents.ts`
- `features/agentControl/hooks/useControlDispatch.ts`
- `features/agentControl/hooks/useControlRunMessages.ts`
- `features/agentControl/hooks/useControlRunResume.ts`
- `features/agentControl/hooks/useControlApprovals.ts`
- `features/agentControl/stores/controlEventStore.ts`
- `features/agentControl/stores/controlTranscriptStore.ts`

State ownership:

- React Query owns read resources: skills, runs, schedules, artifacts, approvals.
- A small event store owns live SSE events, selected run id, optimistic run updates, and replay/dedup by event id or `(type, run_id, ts)` fallback.
- A transcript store owns selected-run messages for the main output thread. For chat-kind runs it must send the full transcript on each continuation, matching the existing chat contract. For autonomous runs it keeps local UI transcript state and sends only the new parent message plus idempotency key. The control deck must not own or render a duplicate transcript.
- `usePortfolioChat` remains the chat owner. Do not blend control resource state into chat state except for intentional inline run/event chips.
- Selected-run output is presentation state for the main chat surface. Keep the underlying Hank chat state and control-run transcript state separate, but allow `ChatInterface` to choose which thread is displayed: normal Hank chat or selected-run output.
- `ControlGatewayService` is registered as a user-scoped singleton in `SessionServicesProvider`, beside `GatewayService`, so hooks do not instantiate ad hoc transports and multi-user isolation remains testable.

### 4.4 `@risk/ui`

Add UI components under a dedicated folder:

```text
frontend/packages/ui/src/components/agent-control/
  AgentControlSurface.tsx
  ControlDeck.tsx
  ControlStatusStrip.tsx
  ControlComposerMode.tsx
  RunList.tsx
  RunCard.tsx
  RunTimeline.tsx
  RunInspector.tsx
  SelectedRunThread.tsx
  SelectedRunComposer.tsx
  DispatchPanel.tsx
  ApprovalQueue.tsx
  ApprovalInspector.tsx
  SkillPicker.tsx
  LogTail.tsx
```

Integrate at:

- `ChatInterface.tsx`: compose `AgentControlSurface` beside `ChatCore`.
- `ChatInterface.tsx`: keep the main surface as the single conversational/output canvas. It may switch between normal Hank chat and selected-run output, but the side deck must not render a second full agent chat surface.
- `ChatCore.tsx`: expose mode controls around the composer only if we choose to place the `Chat` / `Agent` segmented control inside the composer itself.
- `AnalystApp.tsx`: no new sidebar item for v1. The feature lives inside the existing `chat` view.
- `ArtifactPanelConnected`: becomes the human artifact render lane for agent-control artifacts. Agent control sends it artifact references and shifts into compact approval-rail mode while the artifact panel is open.

Artifact render resolution should align with the broader visual stack:

- **Curated React / registry renderers:** stable recurring contracts should render through canonical visual components and namespace registries, consistent with F147's `THESIS_ARTIFACT_REGISTRY` direction and the existing `OVERVIEW_ARTIFACT_REGISTRY` pattern.
- **Sandboxed HTML artifacts:** long-tail or one-off `HtmlArtifact` outputs should render through the F122 shared renderer primitives once they land (`useHtmlArtifact`, `HtmlArtifactRenderer`, `buildSandboxedDocument`, static exports). The analyst-view integration should wrap those primitives inside `ArtifactPanelConnected`.
- **Generic fallback:** until a contract-specific renderer exists, the panel may show a compact metadata/provenance briefing with a clear "visual renderer unavailable" state. This is a fallback, not the product target.
- **Future packs:** report/presentation assembly should consume stable artifact references and render contracts, not screenshots. The panel should preserve artifact identity and exports so F148-style presentation packs can include reviewed artifacts later.

Bridge architecture for this lane is tracked in `docs/planning/AGENT_CONTROL_ARTIFACT_RENDER_BRIDGE_PLAN.md`. That plan owns the resolver/ref layer between control-plane artifact references and `ArtifactPanelConnected`; F122 and F147 remain the renderer/substrate plans.

## 5. Implementation Plan

### Phase 0 — Finalize target and review

- Land this plan and HTML preview.
- Review with two subagents:
  - UX/UI reviewer: does the surface match `DESIGN.md`, Codex-style agent control, and the analyst-product mental model?
  - Architecture reviewer: does the frontend/proxy plan respect package boundaries and existing gateway contracts?
- Iterate until no blocking findings remain.

### Phase 1 — Control proxy and typed client

- Add or verify upstream control-plane support for autonomous run messaging before wiring the web proxy:
  - `POST /control/runs/:id/messages` accepts autonomous payloads `{ message, message_id? }`.
  - The route resolves `control_run_id -> AutonomousRegistry record`, verifies authenticated user/channel ownership, rejects terminal or non-steerable states, appends to the per-run operator inbox, publishes `parent_message_sent`, and returns `{ run, message_id, delivery_status }`.
  - The child autonomous runtime consumes the operator inbox into `AgentRunner.message_inbox` before the next model turn. This requires child-runtime work; it is not satisfied by the current in-process `send_message` handler alone.
  - `POST /control/runs/:id/resume` creates a new top-level autonomous control run from a resumable interrupted autonomous transcript, returns the resumed run, and links `resumed_from`. This requires top-level autonomous resume work; it is not satisfied by the current in-process `resume_background_agent` handler alone.
  - Existing chat-kind continuation behavior remains unchanged.
- Add server-side control-session management to `app_platform.gateway`.
- Add proxied read endpoints first: health, skills, runs, logs, approvals, artifacts.
- Add `ControlGatewayService` and types in `@risk/chassis`.
- Register `ControlGatewayService` in `SessionServicesProvider` as a user-scoped service.
- Focused tests:
  - Proxy bootstrap does not expose API key.
  - Proxy strips browser-provided channel and uses server-resolved `channel = "web"`.
  - Token cache is user scoped.
  - Chat dispatch stores returned chat-session credentials without exposing gateway bearer tokens to app code.
  - `/events` streams without chat stream lock.
  - Health gates version mismatch.
  - Chat-kind run continuation forwards the full client-owned transcript and returns a refreshed run snapshot.
  - Autonomous run messaging delivers exactly once for a repeated `message_id`, publishes a control event, is consumed by the child on the next model turn, and is rejected across users/channels.
  - Autonomous resume is available only for interrupted top-level autonomous runs marked resumable and creates a linked resumed control run.
  - Schedule writes are unavailable in v1.
  - Artifact detail requests route through the existing artifact viewer/proxy.

### Phase 2 — Read-only UI shell

- Add `AgentControlSurface` inside `ChatInterface`.
- Show health, runs, selected run details, approvals list, logs tail, and artifacts list.
- Add live event subscription and selected-run timeline.
- Add `AgentSessionPanel` in read-only mode for selected runs, including transcript/event timeline and steerability state.
- Route artifact rows/references to `ArtifactPanelConnected` as the human render lane. Initial fallback may be metadata-only, but the component boundary should be ready for contract-specific renderers.
- No dispatch/cancel yet.

### Phase 2b — Artifact render bridge

- Implement `ArtifactRenderRef` / resolver scaffolding from `docs/planning/AGENT_CONTROL_ARTIFACT_RENDER_BRIDGE_PLAN.md`.
- Change agent-control artifact rows to open artifact refs instead of synthetic block-only artifacts.
- Keep existing `:::artifact` panel behavior working while adding resolver-backed fallback states for control-plane artifacts.
- Defer F122 HTML and F147 curated renderer branches until their shared infra/registry substrate lands or is mocked cleanly.

### Phase 3 — Dispatch and cancel

- Add `DispatchPanel`.
- Add skill picker and mode/profile/ticker validation.
- Add `POST /control/runs` proxy and `DELETE /control/runs/:id` proxy.
- Dispatch creates/selects a run and starts watching events.
- Agent-mode Enter opens dispatch preflight; explicit Dispatch launches the run.
- Cancel requires confirmation.

### Phase 3b — Agent session continuation and steering

- Add `POST /control/runs/:id/messages` proxy for chat-kind and autonomous runs.
- Add `POST /control/runs/:id/resume` proxy for interrupted resumable autonomous runs.
- Store per-run session transcript client-side. Send full transcript for chat-kind runs; send only the new message plus idempotency key for autonomous runs.
- Render a Codex-style selected-run thread in the main chat surface: transcript/events above, explicit steering composer below.
- Show direct steering only in the main selected-run thread for running/waiting steerable runs. Show `Resume` only for interrupted top-level autonomous runs that the control API marks resumable.
- Verify the primary analyst chat can stream while a control run message is in flight or `/control/events` is connected.

### Phase 4 — Approvals

- Add cross-session approval decisions through `/control/runs/:session_id/approvals/:approval_id`.
- Add `ApprovalInspector` for durable writes with run/session/approval identity, target object, consequence, sources, and exact diff/payload.
- Keep foreground chat approvals in `ChatCore`.
- Suppress duplicate foreground approval display by comparing session ids once the web control event includes enough identity.

### Phase 5 — Schedules and polish

- Add schedules read surface.
- Defer schedule create/update/delete unless we decide operator scheduling belongs in web v1.
- Add artifact-panel coexistence behavior: control deck compresses to approval rail when `ArtifactPanelConnected` is open.
- Add human-artifact-render integration polish: selected-run context preservation, contract-specific renderer loading states, provenance/source affordances, export/reuse actions, and report-pack inclusion hooks where available.
- Add responsive bottom sheet behavior, keyboard shortcuts, and empty/error states.

### Phase 6 — Live QA

Live QA must cover:

- Health and version gate.
- Skill catalog loading.
- Active run list and selected run detail.
- Dispatch an autonomous task with a low-risk prompt.
- Send a direct message to the running autonomous task through `/control/runs/:id/messages` and verify the message appears in the agent session/control events.
- Dispatch a chat-kind run and continue it through the same `/control/runs/:id/messages` UI action.
- Resume an interrupted resumable autonomous run in a controlled fixture or mocked run.
- Watch live events.
- Open logs.
- Confirm terminal state.
- Verify artifacts if emitted: deck reference opens the artifact panel, the panel renders the human artifact view or explicit fallback, provenance is visible, and selected-run context remains intact.
- Trigger or simulate approval queue behavior.
- Cancel a deliberately long-running run or mocked run in a safe environment.
- Confirm chat still streams while `/control/events` is connected.

## 6. Resolved Decisions And Remaining Open Items

Resolved for implementation:

1. **Web channel identity:** the risk-module proxy owns channel identity and uses server-resolved `channel = "web"` for v1. The browser cannot provide or override channel.
2. **V1 write scope:** expose autonomous dispatch/cancel, autonomous run messaging/resume, chat-kind run continuation, and approval/deny handling. Defer schedule writes.
3. **Artifact relationship:** keep `ArtifactPanelConnected` as the output viewer and human artifact render lane. The control deck lists artifact references and opens details through the existing artifact surface/proxy; it does not own full artifact rendering.
4. **Artifact render bridge:** control-plane artifacts should open an `ArtifactRenderRef` resolved by the artifact panel. The resolver routes to legacy block artifacts, F122 HTML artifacts, F147 curated registry renderers, binary/download affordances, or explicit metadata fallback.
5. **Profiles exposed:** expose backend-available profiles and gate risky behavior through approval/action policy instead of hiding profile options.
6. **Autonomous direct steering contract:** v1 requires an upstream control-plane bridge that maps `/control/runs/:id/messages` to a top-level autonomous operator inbox. The bridge should reuse the existing `send_message` semantics and event shape, but it must cross the subprocess boundary explicitly. Resume likewise needs a top-level autonomous resume bridge rather than a direct call to the in-process `resume_background_agent` tool.

Still open:

1. **Live autonomous smoke timing:** read-only smoke is complete. A real dispatch/message/cancel smoke should run after the upstream control-plane extension and proxy exist but before UI implementation begins, then again after UI implementation.
2. **Run history retention:** default target is active/waiting first plus last 24 hours in `Recent`; confirm if deeper pagination is needed.

## 7. Review Criteria

The plan is ready for implementation when:

- The preview is accepted as the target direction.
- UX review has no blocking findings.
- Architecture review has no blocking findings.
- The proxy design has tests for token isolation, SSE streaming, and version gating.
