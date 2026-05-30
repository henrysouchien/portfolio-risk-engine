# F156 Reader Agent Interface Spec

**Status:** Draft v1 — for Codex review
**Date:** 2026-05-28
**Owner:** Research Workspace / Filing Reader / Agent Layer
**Companion / parent:** `F156_READER_SYSTEM_ARCHITECTURE.md` — this is the **operational contract** for the L2↔L3↔L5 seam: how the agent *perceives* the reader and *acts* on it. The system architecture names the action vocabulary and `document_context`; this spec pins the mechanism, transport, and as-built reality. Where the umbrella and this doc agree, the umbrella governs intent; this doc governs the interface.

## 0. Purpose

The agent-first journey (system arch L5) only renders if the agent can (a) *see* what the human is looking at and (b) *act* on the document with effects that show up. This spec defines that loop: **perception** (what the agent receives each turn), **action** (how it emits reader effects), and **transport** (how those cross the agent-runtime ↔ frontend boundary). It is grounded in what Codex already built, not an ideal.

## 1. As-built (verified 2026-05-28) — the loop is half-wired

| Piece | State | Evidence |
|---|---|---|
| **Perception — send** | **Built.** Frontend builds `DocumentContext` and sends `metadata.document_context` to the gateway. | `frontend/packages/connectors/src/stores/researchStore.ts:479–614`; `useResearchChat.ts:29–93`; `chassis/src/services/GatewayService.ts:302` |
| **Perception — gateway** | **DROPPED.** The gateway `ChatRequest` has **no `metadata` field**, so `document_context` is discarded before it reaches the runtime. | `AI-excel-addin/packages/agent-gateway/agent_gateway/server.py:129` |
| **Perception — storage** | **Not persisted on live turns.** Normal research-turn persistence saves only user text; `routes.py:219–225` merely *deserializes* already-stored metadata for the response. (Initial thread messages *can* store metadata — `repository.py:3467` — but live `useResearchChat` turns don't.) | `api/research/runtime.py:198` |
| **Perception — consumption** | **MISSING.** `document_context` is consumed **nowhere** in the agent runtime/gateway (grep: 0 consumers in `api` + `packages`). The agent sees only the user's typed text. | `runtime.py:_last_user_text` |
| **Research** | **Built.** Corpus tools return located findings (offsets). | `core/corpus/filings.py:98–262` |
| **Action — durable** | **Partial, gated.** `create_annotation` / `create_annotations` are **`state_write` agent tools**; the reader projects stored annotations as highlight + note (label = `annotation.note`). So "agent highlights a passage + note" is *expressible* via a durable annotation — but it's a gated state write, durable (heavyweight for transient marks), and depends on the reader refetching to show it. | `AI-excel-addin/api/agent/shared/server_policies.py:511,547`; `DocumentTab.tsx:125–159` |
| **Action — transient** | **None.** No lightweight, response-scoped channel for "I highlighted this for your question" marks that aren't durable artifacts. | — |
| **Action — point_to / flag / open** | **None.** | — |
| **Transport down** | **None for transient;** durable goes annotation-persist → reader reload (live push unverified). | — |

**Net:** the loop is barely connected — the perception payload is *sent but dropped at the gateway*, not persisted on live turns, and consumed nowhere; the durable annotation path works but is gated/heavyweight; there is no transient action channel. Closing perception is a **4-link chain** (gateway field → runtime preserve → message persist → prompt consume), not a one-line wire.

## 2. Two action classes (the core resolution)

Grounded in the as-built, agent reader actions split cleanly. This resolves the emission-mechanism fork:

| Class | Examples | Mechanism | Permission | Lifetime |
|---|---|---|---|---|
| **Durable** | a note/quote/finding the analyst keeps; a highlight saved as evidence | **tool call** (`create_annotation`, L6 reader-artifact + evidence-registration, promotion) | **state-write, gated** (profile/approval); typed promotion **human-approved** | persisted artifact |
| **Transient** | "I highlighted the two changed passages for your question"; point-to; a reading-aid mark | **structured directive in the response stream** (new) | read-only reading aid; **no approval**; bounded to the turn/query | turn/session-scoped; never durable evidence unless the human saves it |

Why two: making every agent reading-aid a gated, durable state write is wrong — it forces approval, clutters the annotation store, and can't be ephemeral. **Durable outputs reuse the existing (correct) gated path; transient reading aids get a new lightweight channel.** The human "saving" a transient mark is what promotes it to a durable annotation.

**Dual-mode caveat:** `annotate` and `flag` exist in *both* classes — the UI must visually distinguish an ephemeral agent mark from a saved annotation, and "save this mark" must route through the **gated durable path** (verified identity + registry rules). `open` stays a link/proposal only (viewport-consent) — never autonomous navigation.

## 3. Perception contract (close the consumption gap)

The agent prompt MUST include, when present:
- active document identity (`source_id` / `document_id` / `accession`),
- current section,
- active selection anchor + selected text, with anchor kind + confidence,
- recent relevant artifacts for this filing/section,
- whether the context is **verified-for-durable-evidence** vs **prompt-only** (per the note-layer verified-identity gate).

Payload = the existing `document_context` wire shape (`serializeDocumentContext`) + a **viewport signal** (perceptual bridge: current visible section/spans) — *to-build*.

**Immediate highest-leverage fix — a 4-link chain, not a one-liner:** after S1 locks the v2 `DocumentAnchor`/identity schema, (1) move/copy the live `document_context` into the existing surviving request channel, `context.document_context`, instead of relying on top-level request `metadata` that the gateway drops; (2) preserve `context.document_context` through the runtime; (3) persist the same payload on the user message as `metadata.document_context` for replay/audit; (4) inject it into agent input assembly. Today the payload is sent but **dropped at the gateway** and consumed nowhere — so "ask about this selection" does not give the agent the selection. This is mostly backend/gateway plus the send seam — no reader-UI collision.

Honest rule: prompt-only (unverified) context can seed a question but cannot authorize durable evidence.

## 4. Action contract (emission)

- **Durable** → tool calls. `create_annotation` for kept highlights/notes; L6 reader-artifact + evidence tools for notes/quotes/findings; promotion tools (human-approved). Auditable by construction (logged tool calls / state writes). Anchors resolved through the `ReaderBridge` module (L3).
- **Transient** → **typed stream events** on the response channel — **NOT** directives embedded in assistant prose. (Text-embedded directives are a prompt-injection vector — selected filing text or an injected instruction could induce visual actions — and they stream as flickering partial JSON.) The agent runtime emits a discrete, schema-validated `reader_action` event alongside the text, shaped like:
  ```
  { action: 'highlight' | 'annotate' | 'point_to' | 'flag',
    anchor: <DocumentAnchor>,        // carries kind, confidence, and required offset/visible-text frame
    label?: string,                  // the one-line ⚑ Agent callout
    confidence: 'exact'|'high'|'quote'|'section_only'|'none',
    source: 'agent' }                // provenance, for audit
  ```
  Requirements: the frontend stream parser (`chatStreamPayloads.ts:241`, which today has **no directive event type**) gains a typed `reader_action` event; it is **schema-validated**, **logged to the event log / message metadata so it is replayable from history**, and projected **only** via `ReaderBridge`. Directive handlers are **explicitly forbidden from calling durable write APIs** — a transient event can become a state write only through the human "save" path. Transient events do not persist as evidence and are not state writes.
- Both classes: every emitted anchor carries kind + confidence. Every offset-bearing anchor carries **offset_frame** (`corpus_doc` vs `api_excerpt`); visible filing quote anchors carry `visible_text_anchor.visible_text_offset_frame = 'source_html_visible_text_v1'`; non-offset section/document anchors do not fabricate an offset frame. Transient marks on table regions degrade per the alignment boundary; citeable table-cell anchors require same-filing parsed table/XBRL provenance. Durable *mapped* requires the registry. Registry exact/high mappings are producer-first: the normal source is the corpus/Edgar mapping sidecar emitted while generating corpus markdown, with post-hoc matching reserved for legacy/backfill.
- **Narration bound to action:** "I highlighted two passages" must correspond to two emitted (transient or durable) actions that render. The text describes visible marks.

## 5. Transport

- **Up (perception):** live turns send `request.context.document_context` (+ viewport signal once built). Persisted/replayed turns store the same payload as `message.metadata.document_context`. Send currently exists only as top-level request metadata, but the **gateway drops it** (no `metadata` on `ChatRequest`) — fix the 4-link chain (§3) by using the surviving `context` channel for live transport. Acceptance requires a runtime/prompt test proving the selected filing text, anchor, confidence, verified-vs-prompt-only state, and section arrive through `context.document_context`. Caveat: reloaded/replayed metadata normalization accepts only `filing_quote` and **drops `filing_mapped` + verified identity** (`useResearchContent.ts:127`) — replayed durable context loses mapped anchors until extended.
- **Down — durable:** tool call → persist → reader shows it. Needs a **live refresh/push** so agent-created annotations appear mid-turn, not only on reload (current refresh path unverified → treat as to-build).
- **Down — transient:** **typed `reader_action` stream events** (schema-validated, §4 — *not* parsed from assistant prose) → frontend parser → `ReaderBridge` → projection. Turn/session-scoped; cleared on navigation or source change.
- The `ReaderBridge` module (system arch §0.7 / L3) is the single resolver both directions call; the parser/emitter must not reach around it to touch the iframe DOM or corpus directly.

## 6. Role / permission / confidence

- **Durable** = state-write, gated by profile/approval; typed promotion human-approved (role model: agent proposes, human decides).
- **Transient** = reading aids, bounded to the query, no approval, no durable evidence, honest confidence.
- Selected filing text and note bodies are **untrusted quoted data** (prompt-injection discipline): the agent must not follow instructions embedded inside them; selected text alone never authorizes a tool write.

## 7. As-built vs to-build & sequencing

**Built:** perception **send only** (gateway drops it; not persisted on live turns; not consumed); corpus tools; durable annotation tool + projection.

**To-build (ordered by leverage / independence):**
1. **Schema lock first** — transient/durable action payloads and perception payloads use the S1 v2 `DocumentAnchor` contract. Do not add another ad hoc action-anchor shape in the runtime.
2. **Close the perception chain** — (a) send live context via `context.document_context`, (b) preserve through runtime, (c) persist on the user message as metadata for replay/audit, (d) inject into agent input. It's the gateway-drop fix + 3 more links, not a one-liner. Send seam + backend/gateway — **no reader collision after S1**.
3. **Transient `reader_action` channel** (emit + parse + project). Unlocks agent-first transient highlights without state-writes. Touches the response renderer + `ReaderBridge` projection → **coordinate with Wave A2/B + the ReaderBridge extraction.**
4. **Live refresh/push for durable agent annotations** (kept marks appear mid-turn).
5. **`point_to` / `flag` / `open`** transient actions.
6. **Viewport signal** (perceptual bridge) into perception after the privacy/retention policy is locked.

## 8. Open decisions

1. **Transient-by-default?** An agent highlight is transient unless the human saves it (saving promotes to a durable annotation). *Proposed: yes.*
2. **Transient directive protocol** — typed block parsed from the response stream (travels with the turn, replayable from history) vs a parallel SSE side-channel. *Proposed: in-stream typed block.*
3. **Durable down-transport** — reader refetch vs server push.
4. **Emission discipline** — does the agent emit reader actions as part of every answer, or only when the journey/skill calls for it (guard against over-highlighting the whole filing)?
