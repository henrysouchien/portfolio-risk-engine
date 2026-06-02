# F148 Presentation Packs Plan

**Status:** R2 — CODEX PASS (round 3, 2026-06-02). Ready to dispatch PR-2; PR-5 (THESIS_PACK) gates on F147 PR-2.

> **R2 reconciliation note.** R1 was reviewed by Codex (read-only, against the live tree) and returned FAIL with 6 P1 findings. R2 round 2 closed 5 of 6 (1 remaining P1 + 2 new minor); R2 round 3 closed all (P1-5 registry-validity vs composition-time distinction, recap ts/hash on the interface, PR-3/PR-4 dependency split) and returned **PASS**. Two facts R1 missed: (a) the PR-0 type/registry scaffold and PR-1 recap-inventory adapter are **already shipped to `main`** — commits `dd60561aa` (scaffold) and `ed6850053` (registry-matching hardening), files under `frontend/packages/ui/src/components/dashboard/views/modern/presentation-packs/`; (b) Block D `RecapArtifact` carries **no descriptor id**, so descriptor resolution must be F148-local, not a Block D contract change. R2 folds in all 6 P1 fixes, corrects §10 to mark shipped PRs, adds a recap-ingress step, fixes pack id/version semantics, and resolves the §12 open questions. See §14 for the R1→R2 changelog.

**Owner repo:** `risk_module`.

**Companion repo dependency:** `AI-excel-addin` Block D `session_recap` inventory and Block B replay/fan-out.

**Visualization stack layer:** Layer 3 - composition.

---

## 1. Purpose

Layer 1 gives Hank a visual component vocabulary. Layer 2 gives Hank a curated artifact registry. Layer 3 defines the grammar for assembling those artifacts into a named deliverable.

F148 introduces Presentation Packs: named, versioned, deterministic composition templates such as `THESIS_PACK` and `BRIEFING_PACK`. A pack turns a runtime inventory of generated artifacts into an ordered, sectioned, addressable deliverable that can be rendered in the UI and exported through target-specific adapters.

The core product goal is consistency. A thesis should not depend on the agent improvising layout from scratch. The agent may choose a pack and provide constrained narrative inputs, but the pack template owns ordering, grouping, required artifact slots, fallback behavior, and export affordances.

---

## 2. Locked Decisions

### D1. F148 Owns `ArtifactComposition`

Block D `session_recap` is a factual runtime inventory. It reports artifacts, verdicts, approvals, failures, tool summary, and usage. It does not carry pack sections, narrative slots, layout hints, export hints, or presentation ordering.

F148 owns `ArtifactComposition` as a Pack-layer model derived from `SessionRecapEvent.artifacts`.

### D2. Packs Are Templates, Not Agent Freeform Layouts

The agent does not invent deliverable structure. It selects a named pack and the pack's section and slot definitions determine the layout.

Allowed agent discretion in v1:
- choose the pack when more than one pack is valid
- provide concise section insight text for declared narrative slots
- select among explicitly allowed artifact variants when the pack slot permits it

Not allowed in v1:
- arbitrary section creation
- arbitrary artifact ordering
- raw HTML layout instructions
- export-specific layout overrides outside adapter-owned hints

### D3. The Registry Is The Artifact Authority

Every artifact in a pack must resolve through the Layer 2 registry. A `session_recap` artifact that cannot be mapped to a registry descriptor is preserved as unmatched inventory, not silently rendered into a pack.

### D4. Composition Is Addressable

A rendered pack is a first-class object, not an ephemeral UI stack. It needs a stable id, version, source recap reference, source artifact ids, creation timestamp, and export status.

### D5. Export Adapters Consume Packs

PDF, Excel, HTML, Telegram, and future export surfaces are adapters over `ArtifactComposition`. They do not define the composition model.

### D6. Descriptor Resolution Is F148-Local

Block D `RecapArtifact` carries `artifact_id`, `skill`, `contract_name`, `ticker`, `artifact_path`, `emitted_at_seq`, `ts` — and **no registry descriptor id**. F148 resolves each recap artifact to a Layer 2 descriptor **locally**, keyed on `(contract_name, skill, ticker)`, never on a descriptor id emitted by Block D. Any `descriptorId` that appears on an F148 type is a *post-resolution F148 enrichment field*, clearly separated from the raw Block D recap shape. The current scaffold's `RecapArtifact.descriptor_id?`/`descriptorId?` fields (`types.ts:53`) are reframed in R2 as F148-local enrichment on a derived type, not as part of the Block D contract, and are removed from the raw `RecapArtifact` interface. This keeps D1 intact: Block D stays a factual inventory.

### D7. Recap Ingress Is A Prerequisite, Not An Assumption

R1 assumed a `session_recap` is available to the Hank web client. It is not yet. F147 PR-0 shipped artifact/aggregate event plumbing (`artifact_ready`/`aggregate_ready`, `useArtifactReady`, `useThesis`, `/api/artifacts/*`), but the web stream layer has no `session_recap` path: `ClaudeStreamChunk` has no recap variant and `GatewayService.mapEvent` drops unknown events. F148 owns a dedicated **recap-ingress** step (typed stream parsing for a `session_recap` chunk and/or a trusted `POST /chat/recap` proxy path) that must land before any production composition by recap reference. Local-fixture composition (preview against a recap JSON fixture) does not depend on ingress and can proceed first.

---

## 3. Inputs And Dependencies

### Required Inputs

- `SessionRecapEvent` from AI-excel-addin Block D.
- `RecapArtifact[]` inventory from the recap.
- Layer 2 artifact descriptors from F147 via `getArtifactDescriptor(id)`.
- Artifact fetch/proxy path from F147 PR-0.
- Renderer scaffolding from F147 PR-1.

### Required Implementation Dependencies

- **AI-excel-addin Block B:** replay-ready envelope and subscribe/reconnect path.
- **AI-excel-addin Block D:** `session_recap` event and explicit recap endpoint.
- **F147 PR-0/PR-1:** descriptor lookup, artifact fetch substrate, and registry scaffolding.

### Soft Dependencies

- **Block C approvals:** fills the recap approval bucket, but F148 can ship with an empty approval section.
- **F122 HTML artifact renderer:** useful for HTML export and pack previews, but not required for the composition model.
- **F149 tufte-viz:** design-time review for every canonical pack template.

---

## 4. Non-Goals

- Do not amend Block D with composition metadata.
- Do not replace F147 artifact rendering.
- Do not implement session-cumulative recap in AI-excel-addin as part of F148.
- Do not build arbitrary agent-authored decks in v1.
- Do not require every export target to ship before the pack renderer.
- Do not use pack templates as a backdoor for unregistered artifact types.

---

## 5. Core Concepts

### 5.1 `PresentationPack`

A pack is the named template.

```ts
export interface PresentationPack {
  id: string;                 // STABLE id, version-free: "pack.thesis" (NOT "pack.thesis.v1")
  label: string;              // "Thesis Pack"
  version: number;            // separate integer; getPresentationPack(id, version?) returns latest by version
  description: string;
  audience: "internal" | "client" | "public";
  sections: PresentationPackSection[];
  exports: PackExportTarget[];
}

export interface PresentationPackSection {
  id: string;                 // "comparables"
  label: string;              // "Comparable Set"
  purpose: string;            // why this section exists
  narrativeSlots: NarrativeSlot[];
  artifactSlots: ArtifactSlot[];
  layout: SectionLayoutHint;
}

export interface ArtifactSlot {
  id: string;
  descriptorIds: string[];    // registry ids accepted by this slot
  required: boolean;
  role: "primary" | "supporting" | "evidence" | "appendix";
  maxArtifacts?: number;
  emptyState: "hide" | "show_missing" | "show_affordance";
}
```

### 5.2 `ArtifactComposition`

A composition is the instantiated pack for a specific recap/session.

```ts
export interface ArtifactComposition {
  compositionId: string;
  packId: string;
  packVersion: number;
  sessionId: string;
  sourceRecapSeqRange: [number, number];
  sourceRecapTrigger: "turn_end" | "explicit" | "session_gc";
  sourceRecapTs: number;        // recap event timestamp — disambiguates per-turn recaps (Block D is per-turn in v1)
  sourceRecapHash: string;      // hash of the recap payload — provenance + dedup
  createdAt: string;
  sections: ArtifactCompositionSection[];
  unmatchedArtifacts: CompositionUnmatchedArtifact[];
  missingRequiredSlots: MissingRequiredSlot[];
  status: "draft" | "ready" | "exported" | "invalid";
}

export interface ArtifactCompositionSection {
  sectionId: string;
  label: string;
  narrative: Record<string, string>;
  artifacts: CompositionArtifactRef[];
  layout: SectionLayoutHint;
}

export interface CompositionArtifactRef {
  slotId: string;
  descriptorId: string;        // F148-LOCAL resolution result (see D6); NOT sourced from the Block D recap
  artifactId: string;          // = RecapArtifact.artifact_id
  artifactPath: string;        // = RecapArtifact.artifact_path (fetched via F147 /api/artifacts/* proxy)
  ticker: string | null;
  role: ArtifactSlot["role"];
  sourceSeq: number;           // = RecapArtifact.emitted_at_seq
}
```

`descriptorId` on `CompositionArtifactRef` is the output of F148-local resolution per D6 — the composer maps `(contract_name, skill, ticker)` to a Layer 2 descriptor. It is never read off the raw recap. Composition provenance must also capture recap `ts` and a recap payload hash (see §8), because Block D is per-turn in v1 and a single session can produce multiple recaps — `sourceRecapSeqRange + trigger` alone is not a unique key.

### 5.3 Narrative Slots

Narrative slots are constrained text fields defined by the pack. They are not freeform markdown pages.

Examples:
- `section_thesis`: one or two sentences stating the section insight
- `risk_callout`: concise downside framing
- `source_note`: optional caveat for incomplete or stale artifact data

Each slot should define max length, tone, and whether it is required.

### 5.4 Layout Hints

Layout hints are pack-level hints consumed by renderers/export adapters. They are not CSS.

Examples:
- `density: "compact" | "standard" | "appendix"`
- `preferredColumns: 1 | 2`
- `pageBreakBefore: boolean`
- `emphasis: "diagnosis" | "evidence" | "summary"`

---

## 6. V1 Named Packs

### 6.1 `THESIS_PACK`

Purpose: a complete investment thesis deliverable.

**Descriptor-availability gate.** The Layer 2 thesis registry (`THESIS_ARTIFACT_REGISTRY` in `artifacts/thesis-registry.ts`) is currently **empty** — F147 PR-2 ships the first real thesis descriptor. The artifact slots below name concepts (comp table, growth trend, revenue segments, market share, unit economics) that do **not** yet map to real descriptor ids.

Two distinct mechanisms must not be conflated (R2 fix for the shipped validator invariant):

- **Registry-time validity** (`validatePresentationPackRegistry`): a slot with `required: true` **and** empty `descriptorIds` is rejected as `empty_required_artifact_slot` — a required slot that can never be satisfied is a malformed pack. So a slot with no real descriptor yet **must be declared `required: false`**, with `emptyState: "show_affordance"`. The pack stays registry-valid.
- **Composition-time missing** (`missingRequiredSlots`): applies only to slots that are `required: true` (i.e. already have real `descriptorIds`) but had no matching artifact in a given recap.

Therefore the first shippable `THESIS_PACK` is **deliberately-incomplete**: not-yet-available slots are `required: false` + `show_affordance`. When F147 lands a descriptor, wire its real id into the slot and **promote it to `required: true`** — only then does its absence in a recap surface as `missingRequiredSlots`. Never author slots against invented descriptor ids. This keeps the pack registry-valid and honest from day one, and lets it grow with F147 rather than blocking on the full thesis registry.

Initial sections:
- `header`: ticker, company, thesis date, analyst/source metadata
- `diagnosis`: current rating/verdict and one-line thesis
- `comparables`: comp table, valuation bands, peer positioning
- `growth_evidence`: growth trend, revenue segments, unit economics where available
- `competitive_landscape`: industry landscape, market share, competitive position
- `risks`: downside factors, sensitivity/scenario outputs
- `appendix`: source notes, approvals, tool summary, failure caveats

### 6.2 `BRIEFING_PACK`

Purpose: a shorter, meeting-ready market or company update.

Initial sections:
- `header`
- `what_changed`
- `key_metrics`
- `supporting_artifacts`
- `open_questions`

### 6.3 `MODEL_REVIEW_PACK`

Purpose: review a model build or forecast update.

Initial sections:
- `model_context`
- `assumption_changes`
- `diagnostics`
- `forecast_bridge`
- `open_issues`

This can ship after thesis/briefing if F147 model artifacts are not ready.

---

## 7. Session To Pack Transformation

### 7.1 Pipeline

1. Receive or fetch a `SessionRecapEvent`.
2. Normalize `RecapArtifact[]` into `RuntimeArtifactInventory`.
3. Resolve each artifact against the Layer 2 registry.
4. Select candidate packs based on available descriptor ids.
5. Validate required slots.
6. Build `ArtifactComposition`.
7. Persist the composition.
8. Render pack in UI.
9. Export through one or more adapters.

### 7.2 Matching Rules

Artifact matching should be deterministic. Block D recap artifacts have **no descriptor id** (D6), so resolution is two-stage and F148-local:

1. **Resolve** each `RecapArtifact` to a Layer 2 descriptor locally, keyed on `(contract_name, skill, ticker)`. The resolved descriptor id is written onto the derived `CompositionArtifactRef.descriptorId`, never read off the recap.
2. **Match** the resolved descriptor id against each slot's `descriptorIds[]`.

Rules:
- primary key for resolution: `contract_name` (the typed-outputs contract name), then `skill`, then `ticker`
- never match only on human label
- a recap artifact that resolves to no descriptor is preserved as `unmatchedArtifacts`, never silently rendered (D3)

If multiple artifacts match one slot:
- prefer the newest artifact by source seq
- preserve alternates in slot metadata
- expose alternates only in an explicit UI control

If a required slot is missing:
- mark `missingRequiredSlots`
- render an affordance to run the missing skill
- do not pretend the pack is complete

### 7.3 Pack Selection

Pack selection can be automatic only when one pack is clearly valid.

If multiple packs are valid, the UI should present pack choices. The agent can recommend a pack, but the selected pack id should be explicit in the composition state.

---

## 8. Persistence And Addressability

### 8.1 Stored Object

Persist compositions in a **standalone `presentation_pack_compositions` table** (resolved from §12 Q1), not under research-thread storage. A pack is an addressable, exportable object derived from a session; thread storage is too narrow. Link to a research thread via a nullable FK rather than nesting inside it.

Columns:
- `composition_id` (PK)
- `user_id` (owner; authorization key)
- `research_file_id` (nullable FK — links a pack to a research thread when one applies)
- `pack_id`
- `pack_version`
- `source_session_id`
- `source_recap_seq_range`
- `source_recap_ts` (recap event timestamp — disambiguates per-turn recaps)
- `source_recap_hash` (hash of the recap payload — provenance + dedup; see §5.2)
- `composition_json` (the full `ArtifactComposition`)
- `status` (`draft` | `ready` | `exported` | `invalid`)
- `created_at`
- `updated_at`
- `created_by`
- export metadata (target, status, output ref, last-attempt ts — may be a child `presentation_pack_exports` table)

### 8.2 API Surface

Proposed v1 API:

```txt
POST /api/presentation-packs/compose
GET  /api/presentation-packs/{composition_id}
GET  /api/presentation-packs/{composition_id}/exports
POST /api/presentation-packs/{composition_id}/exports/{target}
```

The compose endpoint accepts:
- `session_recap` payload or recap reference
- `pack_id`
- optional narrative slot values

### 8.3 Storage Location

V1 can store compositions in the existing application database as JSON metadata. Export files can use existing artifact/file storage conventions once the adapter writes concrete output.

---

## 9. Export Adapters

### 9.1 PDF

PDF is the primary external sharing target. It should consume the composition and rendered artifacts, not rebuild from raw recap.

### 9.2 Excel

Excel export is the addin-friendly target. It should preserve workbook ergonomics: sheet names, frozen panes, source notes, and repeatable section order.

### 9.3 HTML

HTML export can reuse Pattern 2A renderer infrastructure once F122 is available. Until then, UI preview can render the composition with React components.

### 9.4 Telegram

Telegram is a compact preview target. It should not attempt to render every artifact. It should select section summaries and links to the addressable pack.

---

## 10. Implementation Plan

Two PRs already shipped to `main` (R1 missed this). The remaining sequence is re-gated per the R1 Codex review: scaffold reconciliation first, recap ingress next, real pack templates only after F147 descriptors exist, then composer / design gate / preview / persistence / export.

Real scaffold location (not the placeholder `.../` path R1 used): `frontend/packages/ui/src/components/dashboard/views/modern/presentation-packs/`.

### PR-0 ✅ SHIPPED — Type And Registry Scaffolding (`dd60561aa`)

Landed: `types.ts`, `registry.ts`, `index.ts`, `registry.test.ts`. Provides `PresentationPack`/`ArtifactComposition`/`RecapArtifact`/`SessionRecapEvent` types, empty `PACK_REGISTRY`, `getPresentationPack(id, version?)` (stable id + separate version, returns latest by version), and `validatePresentationPackRegistry`. Registry lookup + version-uniqueness tests present.

### PR-1 ✅ SHIPPED — Recap Inventory Adapter + Hardened Matching (`ed6850053`)

Landed: `inventory.ts` + `inventory.test.ts`. Provides `runtimeInventoryFromSessionRecap(recap)`, descriptor resolution, unmatched-artifact preservation, missing-slot validation primitives, and deterministic slot selection.

### PR-2 — Scaffold Reconciliation (apply D6/D7)

The first remaining PR is cleanup, not new feature work — align the shipped scaffold with the R2 decisions:
- Remove `descriptor_id?`/`descriptorId?` from the **raw** `RecapArtifact` interface (`types.ts:53`); reintroduce `descriptorId` only on a derived F148-enrichment type per D6.
- Confirm resolution keys on `(contract_name, skill, ticker)`, not on any recap-supplied descriptor id.
- Audit pack id/version semantics against `getPresentationPack` (stable id, separate version) so templates never double-encode version.

Depends on: PR-0, PR-1 (both shipped).

### PR-3 — Recap Ingress (D7)

Add the missing `session_recap` path to the Hank web client: a typed `session_recap` variant in `ClaudeStreamChunk` + handling in `GatewayService.mapEvent` (which currently drops unknown events), and/or a trusted `POST /chat/recap` proxy that returns the explicit closed-log recap body. Needed before production composition by recap reference; local-fixture composition does not depend on it.

Depends on: PR-0. Coordinates with AI-excel-addin Block D recap event/endpoint shapes.

### PR-4 — Composition Builder

`composePresentationPack({ recap, packId, narrative })`: two-stage F148-local resolution (§7.2), deterministic artifact-slot matching, missing-required-slot reporting, alternate-artifact capture, recap `ts` + payload-hash provenance capture. Unit tests for duplicate, missing, stale, unmatched, and multi-recap inputs.

Depends on: PR-2. Runs against recap **fixtures** independent of PR-3; only production-by-reference needs PR-3.

### PR-5 — First Pack Template: deliberately-incomplete `THESIS_PACK`

Author `THESIS_PACK` against **real** F147 descriptor ids only. Slots whose F147 descriptor does not yet exist are declared `required: false` + `emptyState: "show_affordance"` so the pack passes `validatePresentationPackRegistry` (a `required: true` slot with empty `descriptorIds` is rejected as `empty_required_artifact_slot`); they are promoted to `required: true` when a real descriptor is wired in (§6.1). No invented descriptor ids. Validation tests must include: `validatePresentationPackRegistry` returns no issues for the incomplete pack, required sections present, slot ids unique, real descriptor ids only, no duplicate pack ids.

Depends on: PR-2, and **F147 PR-2** (first real thesis descriptor). `BRIEFING_PACK`/`MODEL_REVIEW_PACK` follow once their descriptors exist.

### PR-6 — Template Design Review Gate

Run the Tufte-viz + `INVESTMENT_VISUAL_LAYER_PRINCIPLES.md` review on `THESIS_PACK` **before** it becomes canonical (verdict-first, traceable, thesis-led — not a gallery). Design-time gate, not CI. This precedes building the preview so layout/section decisions are reviewed before they harden.

Depends on: PR-5.

### PR-7 — Pack Preview Renderer (namespace-aware)

React preview for `ArtifactComposition`: section nav, missing-slot affordances, source/provenance rail, compact appendix. **Rendering is namespace-aware**: descriptors are build metadata only and rendering is a separate dispatch — overview returns `GeneratedArtifactProps | null`, thesis returns `BuilderResult`; F148 calls namespace-specific builder contexts/dispatchers. There is no unified `renderArtifact` router in v1; do not assume one.

Depends on: PR-4, PR-6, and the specific F147 renderers for the slots THESIS_PACK actually uses.

### PR-8 — Persistence And API

Standalone `presentation_pack_compositions` table (§8.1) + `compose`/`read`/`exports` endpoints (§8.2). Authorization consistent with existing research/artifact APIs. Tests for ownership, missing composition, invalid pack id, multi-recap provenance, and stable readback. Anything user-addressable (shareable pack URL) needs this before export.

Depends on: PR-4. May overlap PR-7 for fixture/local preview, but a user-addressable pack requires persistence first.

### PR-9 — HTML Export Adapter (first/only v1 export)

One export target for v1: **HTML** (resolved from §12 Q4 — reuses the React preview path fastest). Thin consumer of `ArtifactComposition` + rendered artifacts, not a second composition implementation. Export status metadata, listing endpoint, failure/retry affordance. PDF (HTML-derived), Excel, Telegram are post-v1.

Depends on: PR-7, PR-8.

### PR-10 — Visual QA Hardening

Screenshot fixtures for core sections, desktop/mobile preview checks, long-text and missing-artifact stress tests.

Depends on: PR-7.

---

## 11. Tests

Core test cases:
- pack registry rejects duplicate ids and versions
- recap inventory preserves every artifact, including unmatched artifacts
- required slot missing produces `missingRequiredSlots`
- duplicate candidate artifacts select newest by source seq
- composition builder is deterministic across identical inputs
- narrative slots enforce length and required flags
- preview renderer does not render unmatched artifacts as matched content
- export adapter consumes `ArtifactComposition`, not raw recap

Integration tests:
- explicit recap from AI-excel-addin can compose into a thesis pack
- missing F147 descriptor produces unmatched inventory, not crash
- persisted pack readback equals composed pack

---

## 12. Resolved Decisions (were R1 open questions)

All five R1 open questions are resolved in R2 (Codex review + reconciliation). Recorded as decisions, not questions, so impl doesn't re-litigate them.

1. **Persistence location → standalone `presentation_pack_compositions` table** (not research-thread storage). A pack is an addressable, exportable object derived from a session; thread storage is too narrow. Link to a thread via nullable `research_file_id`. See §8.1.
2. **First thin slice → `THESIS_PACK`, deliberately incomplete.** Author against real F147 descriptor ids only; slots with no descriptor yet are declared `required: false` + `show_affordance` (registry-valid) and are promoted to `required: true` as F147 lands descriptors. Do not fake a complete thesis pack before F147 entries exist. See §6.1, PR-5.
3. **Narrative slots → user-editable before export, constrained.** Editable within slot max-length/tone rules, persisted as user overrides with audit metadata (who/when). Not freeform markdown.
4. **First export target → HTML.** Reuses the React preview path fastest; PDF is HTML-derived later; Excel is a separate workbook-semantics adapter; Telegram is summary-only. See PR-9, §9.
5. **Approvals/failures placement → body only for material blockers.** Missing required slots and blocking failures surface in the pack body; full approvals, tool summary, and non-blocking failures live in the appendix. See THESIS_PACK `appendix` section.

---

## 13. Dispatch Recommendation

PR-0/PR-1 scaffold has shipped. Dispatch order from here:

1. **PR-2 (scaffold reconciliation)** first — it's a cleanup gate that makes the shipped types honor D6/D7 before anything builds on them.
2. **PR-3 (recap ingress)** depends only on PR-0 (it touches the stream layer, not the reconciled scaffold types) so it can start immediately, in parallel with PR-2. **PR-4 (composition builder against fixtures)** depends on PR-2 (it uses the reconciled resolution path) and needs only a recap fixture, not live ingress — so PR-4 runs after PR-2, parallel to PR-3.
3. **PR-5 (THESIS_PACK)** gates on **F147 PR-2** landing the first real thesis descriptor. Until then, the only honest pack is the deliberately-incomplete one.
4. **PR-6 (design gate)** before **PR-7 (preview)** — review the template before its layout hardens.
5. **PR-8 (persistence)** before **PR-9 (HTML export)** — a user-addressable pack needs storage first.

Do not start the export adapter until the composition builder passes missing/duplicate/unmatched/multi-recap tests. Export is a thin consumer of `ArtifactComposition`, never a second composition implementation.

First meaningful vertical slice (fixtures, no live ingress):

```txt
SessionRecapEvent fixture -> RuntimeArtifactInventory -> (F148-local resolve) -> THESIS_PACK -> ArtifactComposition -> React preview
```

HTML export follows once the preview proves the grammar; PDF/Excel/Telegram are post-v1.

---

## 14. R1 → R2 Changelog

R1 reviewed by Codex (read-only, against the live `main` tree), returned **FAIL** with 6 P1 + 2 P2 findings. R2 changes:

- **Status/intro** — added R2 reconciliation note; recorded that PR-0/PR-1 scaffold shipped (`dd60561aa`, `ed6850053`).
- **D6 added** — descriptor resolution is F148-local keyed on `(contract_name, skill, ticker)`; Block D `RecapArtifact` has no descriptor id. Scaffold's `descriptor_id?`/`descriptorId?` on raw `RecapArtifact` flagged for removal (→ PR-2).
- **D7 added** — recap ingress is a prerequisite: web `ClaudeStreamChunk` has no `session_recap` and `GatewayService.mapEvent` drops unknown events; F148 owns a typed-chunk and/or `POST /chat/recap` step.
- **§5.1** — fixed pack id/version: stable id (`"pack.thesis"`) + separate `version`, matching shipped `getPresentationPack(id, version?)`. No double-encoding.
- **§5.2** — `CompositionArtifactRef.descriptorId` clarified as F148-local resolution output; added recap `ts` + payload-hash provenance (Block D is per-turn, multiple recaps per session).
- **§6.1** — THESIS_PACK is deliberately incomplete, gated on real F147 descriptor ids; no invented ids.
- **§7.2** — matching rewritten as two-stage local resolve-then-match; primary resolution key is `contract_name`.
- **§8.1** — standalone `presentation_pack_compositions` table with full column set (`user_id`, nullable `research_file_id`, `source_session_id`, `source_recap_ts`, `source_recap_hash`, `composition_json`, status, export metadata).
- **§10** — PR-0/PR-1 marked shipped with real paths; re-sequenced to reconcile → ingress → composer(fixtures) → THESIS_PACK(gated on F147 PR-2) → design gate → namespace-aware preview → persistence → HTML export → QA. Design review moved ahead of preview (was the too-late PR-7).
- **§12** — all five open questions resolved to decisions.
- **§13** — dispatch order rewritten around the shipped scaffold and F147 PR-2 gate.
