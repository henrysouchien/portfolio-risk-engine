# F156 Reader Analyst And Note Layer Spec

**Status:** Reconciled product/architecture spec — artifact/evidence layer; UI action surface superseded by the on-top overlay direction
**Date:** 2026-05-28
**Owner:** Research Workspace / Filing Reader / Analyst Layer
**Companion:** `F156_READER_SYSTEM_ARCHITECTURE.md`, `F156_SEC_HTML_READER_ARCHITECTURE_SPEC.md`, `F156_READER_ON_TOP_LAYER_SPEC.md`, `F156_READER_AGENT_INTERFACE_SPEC.md`

## Summary

The filing reader now has the right human baseline: the analyst reads the SEC/source HTML, not corpus markdown. The next layer is the analyst and note-taking workflow that makes the reader useful for research without degrading SEC readability.

This spec owns the durable artifact/evidence/promotion model. It no longer owns a rich sidebar action-card UI. The current product direction is agent-first: the analyst directs the agent in the rail, the agent acts on the visible document through anchored reader actions, and the only direct on-document selection surface is the minimal `Ask / Save / Flag` overlay chip.

The product target is:

```text
SEC filing reader as the human baseline
  + agent sidecar that understands the current filing/section/selection
  + agent-driven highlights, callouts, and go-to links
  + minimal visible passage chip for Ask / Save / Flag
  + durable note and citation capture behind those actions
  + saved research artifacts that can feed thesis, report, and model work
```

The corpus remains hidden infrastructure. It gives the agent retrieval, offsets, section maps, source ids, and citation confidence. It must not become the primary visual reader again.

## Non-Negotiables

1. **The document remains primary.** Opening the analyst layer cannot make the filing materially less readable than the direct SEC browser view. The sidecar is collapsible, width-gated, and never required for basic reading.
2. **Agent-first, human-owned.** The primary loop is ask/direct in the rail -> agent reads and acts on the filing -> analyst judges what to keep. Manual passage selection remains important, but it is the secondary pointing/capture path.
3. **No rich sidebar action panel.** Direct passage actions are `Ask / Save / Flag` in the on-document overlay. Rich actions such as compare, save to thesis, add to risk/catalyst/assumption, and promote are agent-mediated capabilities with explicit analyst approval for durable typed writes.
4. **Visible selection is not automatically a corpus span.** A selected SEC HTML passage starts as a visible filing anchor. It becomes an exact corpus citation only when the bridge proves an exact or high-confidence mapping.
5. **Notes are analyst-owned artifacts.** The agent may suggest, draft, summarize, and compare, but the analyst decides what becomes a note, pinned artifact, thesis claim, or report input.
6. **Citations are automatic but honest.** The UI should make citation capture feel effortless while preserving anchor kind and confidence internally.
7. **Research artifacts outlive chat.** Important notes, quotes, flags, and findings must not disappear into transient conversation history.

## Current State

The current implementation already provides the underlying capabilities this spec preserves:

- Faithful SEC/source HTML rendering in the main canvas.
- A compact reader toolbar with filing identity, current section, SEC link, and diagnostics menu.
- A collapsible right rail titled `Research Analyst`.
- Reader context in the rail: filing id, current section, active thread count, flagged count, posture, and lens.
- A rail composer scoped to the filing.
- Visible SEC HTML selection capture after materialized identity verification, including `source_html_hash`. Route-bound descriptor verification alone is not sufficient because selection capture is parent-side DOM instrumentation.
- A previous rich selected-passage rail card with `Ask analyst`, `Save note`, `Save quote`, `Flag`, `Add to thesis`, and `Compare`. This is now a legacy entry surface to collapse, not the target UI.
- Durable reader artifacts for notes, quotes, and flags, shown in a recent-artifacts rail list.
- Evidence registration from workbench artifacts into canonical source/excerpt references.
- Promotion candidate cards for non-general target buckets once a saved artifact needs thesis/risk/report/model review.
- Bottom quick actions such as `Ask what changed in this filing`, `Open financial statement footnotes`, `Compare peer filing language`, and `Compare holdings exposure`.

The current gaps:

- The visible selection affordance is split between the top document toolbar and the rail; the reconciled direction is to collapse both into the minimal on-document `Ask / Save / Flag` overlay and move rich actions into agent-mediated flows.
- Exact/high corpus mapping is intentionally disabled for visible selections until a backend mapping record proves the HTML-to-corpus span.
- Verified identity now flows through the shared reader context and serialized document context, including source type, sanitizer version, and verification time. The next hardening pass should use that shared identity more aggressively for stale-selection clearing and rail gating.
- The promotion surface is a promotion candidate/review prompt, not yet an approved typed mutation into thesis/report/model state.
- The rail is still more workflow/control-heavy than the original preview's conversation-first reading companion; it should become context, conversation, go-to links, and recent artifacts rather than a panel of passage buttons.

## Review Finding Resolutions

This spec deliberately resolves the first adversarial architecture review findings before implementation:

| Finding | Resolution |
| --- | --- |
| Reader artifacts could become a parallel evidence store. | Reader artifacts are a durable workbench layer, not authoritative evidence by default. Canonical evidence is still `Thesis.sources[]` with `Excerpt` atoms. Promotion requires an explicit evidence-registration step that produces canonical `source_refs` / `excerpt_ids`, or a `data_gap`. |
| Typed promotion was sequenced before evidence was safe. | Typed promotion is split from note capture. The evidence-registration/promotion wave registers evidence and creates promotion review cards. Actual thesis/report/model writes remain blocked unless canonical evidence or an explicit data gap exists. |
| Chat context contract did not match current wire paths. | The v2 `document_context` shape is sent on live turns through `context.document_context`, because that is the gateway channel that survives today. The same payload is persisted on stored messages as `metadata.document_context` for replay/audit. Wire keys are snake_case and a legacy compatibility adapter handles the existing source/section/char-offset shape. |
| Durable anchors lacked a local materialized-identity gate. | Reader shell state must expose verified materialized source HTML identity before enabling durable `Save note`, `Flag`, or evidence-backed ask flows. |
| Selected filing text can contain prompt injection. | All selected filing text, saved quote text, and note bodies are untrusted quoted data in prompt assembly. The agent must not follow instructions contained inside source documents or note bodies. |
| Live reader security model drifted from the two-frame plan. | The companion reader architecture now documents the actual CSP-constrained same-origin iframe model, including server-side materialization of safe SEC Archives redirects so the iframe remains same-origin. This spec assumes that model: parent-side selection capture is allowed only after materialized identity verification with `source_html_hash`, and source markup remains no-script/no-form/no-connect by CSP. |
| Visible selections could overclaim mapped corpus offsets. | Selection capture now persists quote-level anchors by default. The backend rejects `filing_mapped` reader artifacts until an authoritative mapping registry exists; exact/high mapped anchors require a real backend mapping record id before corpus offsets may be stored or registered as mapped evidence. |
| Promotion review was only a label. | The UI should distinguish `Promotion candidate` before canonical evidence from `Promotion review` after evidence registration. Typed thesis/report/model mutation remains a later approved apply path. |

## Target User Flow

The primary loop is agent-first:

```text
Analyst asks/directs in the rail
  -> agent uses corpus/tools to find located evidence
  -> reader renders anchored highlights/callouts/go-to links
  -> analyst reads the marked filing
  -> analyst saves, flags, or promotes only what they approve
```

Manual selection is still essential, but it is the secondary "point at this" loop:

```text
Analyst selects visible filing passage
  -> minimal overlay offers Ask / Save / Flag
  -> note/artifact/evidence machinery preserves provenance
```

### 1. Read

The analyst opens a filing and reads the SEC HTML normally. The filing is the work surface. The rail may be collapsed or open, but it must not visually dominate the document.

Visible state:

- Main canvas: SEC filing.
- Toolbar: filing identity, section identity, SEC source link, diagnostics.
- Rail idle state: current filing and section context, short prompt, recent captured artifacts if any.

### 2. Select

The analyst selects a sentence, paragraph, table cell, table row, footnote, or heading inside the filing.

System behavior:

- Capture the visible selected text.
- Capture filing identity: `source_id`, `source_type`, `document_id`, accession, SEC primary document URL, corpus hash, sanitizer version, source HTML hash.
- Capture visible anchor context: quote, prefix/suffix, section hint, optional table context, optional DOM path.
- Attempt mapping to corpus only if a backend mapping layer returns a durable mapping record.
- Set anchor confidence honestly:
  - `exact` or `high` only when mapping is proven and has a real `mapping_record_id`.
  - `quote` for visible quote anchors without safe corpus offsets.
  - `section_only` for section-level context.
  - `none` for document-level fallback.

Visible state:

- A compact selection chip appears near the selection.
- The rail stays conversation-first and updates its context/composer to the selected passage.

Required direct actions:

- `Ask`
- `Save`
- `Flag`

Agent-mediated rich actions:

- `Save quote`
- `Add to thesis`
- `Compare`
- `Add to risk`
- `Add to catalyst`
- `Add to assumption`
- `Open related passages`

### 3. Ask Analyst

The analyst chooses `Ask analyst` or types into the rail composer while a selection is active.

System behavior:

- The outgoing message includes `document_context`.
- `document_context` includes the selected passage anchor, filing identity, section, and confidence.
- The agent receives the visible quote and can use corpus retrieval/search for broader grounding.
- If the anchor is quote-only, the agent can discuss the passage but must not claim exact corpus-offset provenance.

Visible state:

- Composer placeholder changes from `Ask about this filing...` to `Ask about selected passage...`.
- The overlay chip or a quiet selection-context strip remains visible while the answer streams; the rail does not show a rich action-card.
- The answer can offer follow-up artifact actions through agent-mediated commands: `Save as note`, `Add to thesis`, `Compare prior filing`, `Find related language`.

### 4. Save Note

The analyst chooses `Save note` from the selection affordance or from an agent answer.

The note editor should be lightweight:

- Selected quote preview.
- Analyst note text.
- Tags.
- Target bucket.
- Save/cancel.

Suggested tags:

- `Revenue`
- `Margin`
- `Capex`
- `Accounting`
- `Liquidity`
- `Risk`
- `Guidance`
- `Competition`
- `Legal`
- `Management`

Suggested target buckets:

- `General note`
- `Thesis`
- `Risk`
- `Catalyst`
- `Assumption`
- `Valuation`
- `Model input`

System behavior:

- Persist the note as a durable research artifact scoped by `research_file_id`.
- Persist the anchor using the v2 anchor union.
- Store selected text, analyst note, tags, target bucket, author, timestamps, and citation metadata.
- Keep the saved note in workbench state until evidence registration runs.
- If the selected passage is mapped with `exact` or `high` confidence and a real mapping record id, evidence registration can create canonical source refs and excerpt atoms with mapped corpus/filing provenance.
- If quote-only, evidence registration can create a canonical quote-level excerpt locator, but it must remain marked as quote-level evidence and cannot masquerade as exact corpus-offset evidence.

### 5. Artifact Trail

Saved notes and important agent outputs appear in the rail as durable workbench artifacts, not only as chat messages.

Artifact card types:

- **Note:** analyst-authored interpretation attached to a passage.
- **Quote:** captured source passage without added analyst interpretation.
- **Flag:** notable passage or risk that needs follow-up.
- **Finding:** analyst-approved synthesized claim.
- **Comparison:** agent-created comparison across filings or peers.

Each artifact card should show:

- Short title or first line.
- Source label, for example `MSFT 10-Q 2025 / Cover Page`.
- Anchor confidence badge for internal clarity, for example `Quote`, `Mapped`, `Section`.
- Evidence state, for example `Workbench`, `Evidence registered`, `Needs mapping`, or `Promoted`.
- Optional tags.
- Actions: `Open source`, `Ask`, `Promote`, `Edit`, `Remove`.

The default rail should show a compact recent artifact list, with a deeper artifact drawer later if volume grows.

### 6. Register Evidence

Evidence registration is the bridge from reader workbench artifacts into the canonical research artifact layer.

Rules:

- `reader_artifacts` are not authoritative Layer 1 evidence by themselves.
- Canonical evidence lives in `Thesis.sources[]` with `Excerpt` atoms, per `RESEARCH_ARTIFACT_LAYERS.md`.
- Registering a reader artifact either:
  - reuses an existing `SourceRecord` for the filing and adds/dedupes an `Excerpt`, or
  - creates a new `SourceRecord` with stable filing identity and adds/dedupes an `Excerpt`.
- `Excerpt.locator` must support v2 `DocumentAnchor` locators, including quote-level visible filing anchors and exact/high mapped anchors. The target locator is a discriminated `reader_anchor` object, not a string-prefix protocol:

```ts
type ReaderAnchorExcerptLocator =
  | {
      kind: 'reader_anchor';
      reader_anchor_version: 'v2';
      anchor_kind: 'filing_quote';
      confidence: 'quote' | 'section_only' | 'none';
      source_id: string;
      document_id: string;
      source_html_hash: string;
      corpus_content_hash: string;
      visible_text_anchor: VisibleTextAnchor;
      anchor_hash: string;
    }
  | {
      kind: 'reader_anchor';
      reader_anchor_version: 'v2';
      anchor_kind: 'filing_mapped';
      confidence: 'exact' | 'high';
      source_id: string;
      document_id: string;
      source_html_hash: string;
      corpus_content_hash: string;
      mapping_record_id: string;
      offset_frame: 'corpus_doc';
      char_start: number;
      char_end: number;
      visible_text_anchor: VisibleTextAnchor;
      anchor_hash: string;
    };
```

Legacy `external_anchor` strings emitted by the current service remain readable during migration, but new evidence registration code must write the object form and should treat string locators as compatibility input only.
- Quote-level excerpts are valid evidence atoms for "this passage was captured from this filing" but not precise corpus-offset citations.
- Exact/high mapped excerpts may carry corpus offsets and support precise citation/highlight projection.
- Evidence registration writes must follow the same lock/dedup discipline as `register_sources`.

Evidence states:

- `workbench_only`: saved in the reader artifact table only; not yet canonical evidence.
- `registered_quote`: canonical source/excerpt exists with quote-level visible filing locator.
- `registered_mapped`: canonical source/excerpt exists with exact/high mapped locator and durable mapping record id.
- `promotion_proposed`: a review card exists, but no typed thesis/report/model mutation has landed.
- `promoted`: a typed target references the canonical evidence.
- `data_gap`: promotion was blocked by missing/insufficient evidence and recorded as a gap.

### 7. Promote

Promotion moves a saved artifact into a typed research output.

Allowed promotion targets:

- Thesis claim.
- Risk.
- Catalyst.
- Assumption.
- Valuation driver.
- Model input.
- Report section.
- Data gap.

Promotion rules:

- The analyst must approve promotions that change typed thesis/report/model state.
- Promoted claims must carry source refs or explicit data gaps.
- Workbench-only artifacts cannot directly mutate thesis/report/model state.
- Quote-level registered evidence can support draft claims and claims whose citation semantics accept quote-level provenance.
- Exact/high mapped evidence is required for precise corpus-offset citations.
- Promotion writes should include a decisions-log rationale when they change durable thesis state.
- The current implementation creates promotion candidates and review prompts. A later apply path must turn reviewed candidates into typed thesis/report/model mutations through an explicit analyst-approved write.

## Right Rail States

### Idle

Purpose: support reading without demanding attention.

Contents:

- `Research Analyst`
- `Reading · {filing label} · {section}`
- One-line task framing.
- Reader cues: section, thread count, flags, posture, lens.
- Recent saved artifacts.
- Filing-scoped composer.

### Selection Active

Purpose: keep the agent and composer scoped to the exact visible passage while the on-document overlay carries the direct actions.

Contents:

- Quiet selected-passage context strip or compact quote preview.
- Source identity line.
- Confidence line hidden by default or visually quiet.
- No rich sidebar action buttons. Direct actions live in the overlay chip: `Ask`, `Save`, `Flag`.
- Rich actions are typed or confirmed conversationally, for example "save that to the thesis" or "compare this to last year's filing."
- Composer scoped to the selection.

### Note Draft

Purpose: capture analyst thinking quickly.

Contents:

- Quote preview.
- Note textarea.
- Tags.
- Target bucket selector.
- Save/cancel.

Rules:

- Do not navigate away from the filing.
- Do not require selecting a thread before saving.
- Saving creates a durable artifact and can optionally attach to the active thread.

### Agent Answer

Purpose: answer the current filing/selection question.

Contents:

- Streaming answer.
- Citation/source chips.
- Follow-up artifact actions.
- Distinction between agent-generated content and analyst-owned saved notes.

### Artifact Review

Purpose: inspect and reuse captured research objects.

Contents:

- Recent artifacts.
- Filters by tag/type.
- Open source action.
- Register evidence action when a workbench artifact has enough verified identity.
- Promote actions.

## Data Model

This spec relies on the v2 `DocumentAnchor` union defined in `F156_SEC_HTML_READER_ARCHITECTURE_SPEC.md`.

Add or adapt a durable note/artifact shape equivalent to:

```ts
interface ReaderResearchArtifact {
  artifact_id: string;
  research_file_id: number;
  artifact_type: 'note' | 'quote' | 'flag' | 'finding' | 'comparison';
  artifact_status: 'active' | 'superseded' | 'deleted';
  evidence_status: 'workbench_only' | 'registered_quote' | 'registered_mapped' | 'promotion_proposed' | 'promoted' | 'data_gap';
  title?: string | null;
  body: string;
  selected_text?: string | null;
  tags: string[];
  target_bucket?: 'general' | 'thesis' | 'risk' | 'catalyst' | 'assumption' | 'valuation' | 'model_input' | 'report' | null;
  anchor: DocumentAnchor;
  canonical_evidence?: Array<{
    source_ref: string;
    excerpt_id: string;
    registration_status: 'registered_quote' | 'registered_mapped';
    registered_at: string;
  }>;
  author: 'user' | 'agent';
  created_at: string;
  updated_at: string;
  deleted_at?: string | null;
  supersedes_artifact_id?: string | null;
  promoted_to?: Array<{
    target_type: 'thesis_claim' | 'risk' | 'catalyst' | 'assumption' | 'valuation_driver' | 'model_input' | 'report_section' | 'data_gap';
    target_id: string;
    promoted_at: string;
  }>;
}
```

Storage rules:

- The authoritative key is `research_file_id`, not ticker.
- The anchor is stored as structured JSON with `anchor_schema_version = 'v2'`.
- Existing legacy annotations remain readable as corpus-span anchors where identity can be resolved.
- Reader artifacts are durable workbench state, not authoritative evidence unless `canonical_evidence` has at least one entry.
- `canonical_evidence` is plural because findings and comparisons can cite multiple excerpts or sources; simple note/quote artifacts usually carry one entry.
- The UI may render annotation highlights as derived state, but the durable workbench artifact is the note/quote/finding plus anchor and evidence status.
- Deletes are soft deletes. Edits create a superseding revision when the selected text, anchor, or promoted meaning changes; simple typo/tag edits may update in place.
- Promotion paths must read canonical evidence from `Thesis.sources[]`, not from reader artifact side fields.

## Agent Context Contract

When the analyst asks about a filing or selected passage, the frontend sends live request context with:

```ts
interface ReaderDocumentContext {
  source_id: string;
  source_type: 'filing' | 'transcript';
  document_id: string;
  filing_label?: string;
  section_header?: string | null;
  active_anchor?: DocumentAnchor | null;
  active_artifact_id?: string | null;
  research_file_id: number;
  context_schema_version: 'v2';
  verified_identity?: VerifiedReaderIdentity | null;
}

interface ReaderDocumentContextWire {
  context_schema_version: 'v2';
  source_id: string;
  source_type: 'filing' | 'transcript';
  document_id: string;
  filing_label?: string;
  section_header?: string | null;
  active_anchor?: DocumentAnchorWire | null;
  active_artifact_id?: string | null;
  research_file_id: number;
  verified_identity?: VerifiedReaderIdentityWire | null;
}
```

Wire placement:

- Live requests send this as `context.document_context`; that is the surviving gateway/runtime channel.
- Stored/replayed messages persist the same payload as `metadata.document_context` for audit and replay.
- Wire keys are snake_case.
- The current legacy shape `{source_id, source_type, section, selection}` remains accepted during migration.
- A compatibility adapter upgrades legacy corpus selections into v2 `CorpusSpanAnchor` values only when `document_id` and `corpus_content_hash` can be resolved from the active document descriptor.
- Legacy selections that cannot resolve identity are prompt-only context and cannot create durable evidence.

Agent prompt assembly should include:

- Research file identity and posture.
- Active document identity.
- Active section.
- Selected passage text when present.
- Anchor kind and confidence.
- Recent relevant artifacts from the same filing/section.
- Whether the context is verified for durable evidence or prompt-only.

Agent behavior:

- The agent may answer using visible quote context plus corpus retrieval.
- The agent must preserve source identity in citations.
- The agent must not silently upgrade quote-only anchors to exact corpus citations.
- The agent can suggest saved artifacts, but analyst approval creates analyst-owned notes/findings.
- Selected filing text, saved quote text, and note bodies are untrusted quoted data. The agent must not follow instructions embedded inside them.
- Tool writes require explicit user action or approved promotion flow; selected source text alone cannot authorize writes.

## Verified Identity Gate

Durable visible-reader actions require verified materialized identity.

```ts
interface VerifiedReaderIdentity {
  source_id: string;
  source_type: 'filing';
  document_id: string;
  accession: string;
  primary_document_url: string;
  corpus_content_hash: string;
  sanitizer_version: string;
  source_html_hash: string;
  verified_at: string;
}
```

Rules:

- `SourceHtmlPane` or the equivalent source HTML loader verifies source HTML metadata against the descriptor.
- The verified identity is lifted into reader-shell state, not kept only inside the iframe/pane.
- `Ask analyst` may run before materialized identity only with legacy/user-entered/document context that was not freshly captured from the iframe. Fresh visible-reader selection text or anchors require `materialized_identity_verified` because selection capture is DOM instrumentation.
- `Save note`, `Flag`, `Register evidence`, and `Promote` are disabled until verified identity is available.
- If identity verification fails or becomes stale after a source change, existing selection state is cleared and durable actions are disabled.

## Visual Rules

- The rail opens on the right and may narrow the filing only within width gates from the F156 reader spec.
- The filing keeps a white SEC-style document surface. The rail remains dark app chrome.
- Selection UI must be compact and should not cover meaningful filing text.
- Note and artifact cards use small, dense, work-focused styling.
- No marketing copy, oversized instructional text, or decorative cards.
- The rail should feel like a research instrument, not a second page beside the filing.
- The rail should not become a sidebar action panel. Direct passage actions are the overlay chip; the rail handles conversation, go-to links, and recent artifact state.
- Any bottom quick-action row remains secondary to the agent-first rail and direct passage overlay.

## Acceptance Criteria

### Product

- Analyst can read the filing without opening the rail.
- Analyst can open the rail without losing basic SEC readability.
- Analyst can select a visible filing passage and see passage-aware actions.
- Analyst can ask the agent about the selected passage.
- Analyst can save a note tied to the visible passage.
- Saved notes appear as durable artifacts in the rail.
- Analyst can reopen the source passage from a saved artifact.
- Analyst can promote an artifact to a thesis/report/model target with approval.

### Architecture

- Visible selections persist as v2 anchors.
- Quote-only anchors cannot enter corpus-offset-only APIs.
- Exact/high mappings are required before corpus offsets are persisted from SEC HTML selections.
- Every durable artifact carries filing identity, anchor kind, confidence, and source metadata.
- Reader workbench artifacts cannot be treated as canonical evidence unless registered into `Thesis.sources[]`.
- Promotion to typed thesis/report/model state preserves source refs or records a data gap.
- Prompt assembly treats source filing text and note bodies as untrusted quoted data.

### Visual QA

- Capture screenshots for:
  - rail collapsed
  - rail idle/open
  - selection active
  - note draft
  - saved artifact list
  - agent answer with selected passage context
- Compare rail collapsed/open against direct SEC browser view for readability impact.
- Verify selection affordances do not obscure text on narrative prose and tables.
- Verify narrow viewport behavior moves the rail to a drawer/sheet instead of crushing the filing.

## Implementation Alignment

Current implementation sequencing lives in `F156_READER_IMPLEMENTATION_PLAN.md`. This note-layer spec aligns to that wave plan instead of defining an independent UI path.

### A1 - Framing

No artifact behavior change. Preserve the faithful SEC document, add the dark-desk/paper framing, and keep the note/evidence machinery untouched.

### Perception Chain

- Live turns send `context.document_context`.
- Stored/replayed turns persist `metadata.document_context`.
- Prompt assembly includes document identity, section, selected text/anchor, confidence, verified-vs-prompt-only status, and recent relevant artifacts.

Exit: asking about the selected passage actually gives the agent the selected passage and verified context.

### ReaderBridge Extraction

- Selection capture, quote/corpus mapping, and projection become typed bridge APIs.
- Note/artifact creation consumes anchors from the bridge rather than iframe DOM or corpus internals.
- Visible HTML selections must not store corpus `char_start` / `char_end` unless the authoritative mapping registry returns a durable `mapping_record_id` with `exact` or `high` confidence.
- The preferred source of those registry records is the corpus/Edgar producer mapping sidecar emitted while generating corpus markdown from SEC HTML; post-hoc quote matching is only a legacy/backfill path.
- Quote-only anchors remain durable as quote-level evidence; exact/high mapped evidence requires the registry.

Exit: artifact code can accept anchors without knowing how visible HTML and corpus offsets were reconciled.

### A2 - Action-Surface Rebind

- Add the minimal selection overlay: `Ask`, `Save`, `Flag`.
- Remove rich passage buttons from the rail and toolbar surfaces.
- Keep underlying save/note/flag/evidence/promotion handlers.
- Route rich actions through the agent path: compare, save quote, add to thesis/risk/catalyst/assumption, promote.

Exit: direct selection capture is simple, the rail is conversation-first, and no artifact capability has been deleted.

### Reader Action Channel And Findings Projection

- Agent emits transient `reader_action` events for highlights, callouts, point-to, and flags.
- Reader projects them through `ReaderBridge`.
- Durable saves of transient marks still require explicit user action and verified identity.

Exit: the agent can act on the filing visibly without turning every reading aid into a durable state write.

### Evidence Registration And Promotion

- Register saved reader artifacts into canonical `Thesis.sources[]` / `Excerpt` atoms when verified identity exists.
- Support quote-level visible filing locators now; add exact/high mapped locators only after the authoritative mapping registry exists.
- Create promotion candidates before canonical evidence exists and promotion review cards after evidence registration.
- Do not mutate typed thesis/report/model state from workbench-only artifacts.

Exit: saved reader artifacts can become canonical evidence and enter an approved promotion flow without overclaiming precision.

### Later Mapping / Perceptual / Visual Bridges

- Corpus producer mapping sidecar plus mapping registry enables durable exact/high visible HTML to corpus spans.
- Perceptual bridge adds viewport-aware context and any approved read-trail policy.
- Visual bridge localizes tables/charts, but cited values come from identity-bound parsed table/XBRL provenance; missing same-filing proof degrades to quote/section evidence.

Exit: artifact and evidence workflows stay aligned as bridge precision improves.

## Open Questions

1. Should saved reader artifacts live in a new `reader_artifacts` table or extend existing `annotations`/`research_messages` with an artifact table? Preference: new durable workbench artifact table, with annotations as derived render state.
2. Should note tags be free-form in v1 or seeded enum plus free-form? Preference: seeded suggestions plus free-form storage.
3. How aggressively should we migrate existing `external_anchor` string locators to the v2 `reader_anchor` object form? Preference: write object form for all new registrations and backfill legacy strings opportunistically when touched.
4. How much of the rail artifact list should be visible by default before a drawer is needed? Preference: recent 3 to 5 artifacts in rail, full list in drawer.
