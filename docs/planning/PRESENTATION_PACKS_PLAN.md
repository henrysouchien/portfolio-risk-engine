# F148 Presentation Packs Plan

**Status:** DRAFT R1 - 2026-06-02.

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
  id: string;                 // "pack.thesis.v1"
  label: string;              // "Thesis Pack"
  version: number;
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
  descriptorId: string;
  artifactId: string;
  artifactPath: string;
  ticker: string | null;
  role: ArtifactSlot["role"];
  sourceSeq: number;
}
```

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

Artifact matching should be deterministic:
- primary key: registry descriptor id
- secondary key: artifact contract name
- tertiary key: skill and ticker
- never match only on human label

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

Persist the `ArtifactComposition` JSON plus metadata:
- `composition_id`
- `pack_id`
- `pack_version`
- `session_id`
- `source_recap_seq_range`
- `created_at`
- `updated_at`
- `created_by`
- `status`

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

### PR-0: Type And Registry Scaffolding

Files:
- `frontend/packages/ui/src/components/.../presentation-packs/types.ts`
- `frontend/packages/ui/src/components/.../presentation-packs/registry.ts`
- `frontend/packages/ui/src/components/.../presentation-packs/index.ts`

Deliverables:
- `PresentationPack` and `ArtifactComposition` types
- empty `PACK_REGISTRY`
- `getPresentationPack(id)` helper
- tests for registry lookup and version uniqueness

Depends on:
- none, but should align with F147 descriptor naming.

### PR-1: Recap Inventory Adapter

Deliverables:
- `runtimeInventoryFromSessionRecap(recap)`
- registry descriptor resolution
- unmatched artifact preservation
- required/missing slot validation primitives

Depends on:
- F147 PR-1 descriptor types
- AI-excel-addin Block D recap event shape

### PR-2: V1 Pack Templates

Deliverables:
- `THESIS_PACK`
- `BRIEFING_PACK`
- optional stub `MODEL_REVIEW_PACK`
- validation tests for required sections, slot ids, descriptor ids, and no duplicate pack ids

Depends on:
- PR-0
- enough F147 descriptor ids to make the templates meaningful

### PR-3: Composition Builder

Deliverables:
- `composePresentationPack({ recap, packId, narrative })`
- deterministic artifact-slot matching
- missing required slot reporting
- alternate artifact capture
- unit tests for duplicate, missing, stale, and unmatched artifacts

Depends on:
- PR-1
- PR-2

### PR-4: Pack Preview Renderer

Deliverables:
- React preview component for `ArtifactComposition`
- section navigation
- missing-slot affordances
- source/provenance rail
- compact appendix for failures, approvals, and usage

Depends on:
- PR-3
- F147 renderers for the artifact slots used in v1 packs

### PR-5: Persistence And API

Deliverables:
- backend model/table or JSON persistence path
- compose/read endpoints
- authorization checks consistent with existing research/artifact APIs
- tests for ownership, missing composition, invalid pack id, and stable readback

Depends on:
- PR-3

### PR-6: Export Adapter Thin Slice

Deliverables:
- one export target first, preferably HTML or PDF
- export status metadata
- export listing endpoint
- failure capture and retry affordance

Depends on:
- PR-4
- PR-5

### PR-7: Design QA And Pack Hardening

Deliverables:
- Tufte-viz design review for `THESIS_PACK`
- mobile/desktop preview checks
- long-text and missing-artifact stress tests
- screenshot fixtures for core sections

Depends on:
- PR-4

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

## 12. Open Questions

1. Should v1 composition persistence live under research-thread storage or a standalone presentation-pack table?
2. Which pack is the first product-critical thin slice: `THESIS_PACK` or `BRIEFING_PACK`?
3. Should pack narrative slots be user-editable before export in v1?
4. Which export target should ship first: PDF for sharing, HTML for fastest renderer reuse, or Excel for addin continuity?
5. How much of approvals/failures belongs in the visible pack body versus appendix-only?

---

## 13. Dispatch Recommendation

Start with PR-0 and PR-1 only after F147 PR-0/PR-1 are either shipped or their descriptor interfaces are stable enough to import.

Do not start export adapters until the composition builder has passed missing/duplicate/unmatched artifact tests. Export adapters should be thin consumers, not a second composition implementation.

The first meaningful vertical slice should be:

```txt
SessionRecapEvent -> RuntimeArtifactInventory -> THESIS_PACK -> ArtifactComposition -> React preview
```

PDF/Excel/HTML/Telegram exports follow after the preview proves the grammar.
