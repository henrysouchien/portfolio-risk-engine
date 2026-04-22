# Investment Schema Unification — Cross-Repo Design

**Status**: DRAFT R3 — pending Codex review
**Created**: 2026-04-17
**Revision**: R3 — addresses Codex R2 FAIL (3 residual blockers, 4 should-fix) with second-pass inventory on `segments.py`, `build.py`, `sia_standard.json`. R1 and R2 change logs preserved inline.
**Scope**: Design-only (types, ownership, versioning, decisions). Implementation plans follow this doc.

**Related docs / code**:
- `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md` — handoff artifact v1.0 (Decision 2A, lines 283-400)
- `docs/planning/completed/RESEARCH_WORKSPACE_MCP_PLAN.md` — 15 MCP tools + gateway client
- `AI-excel-addin/schema/models.py` — FinancialModel, LineItem, FormulaSpec, DriverCategory enum, DataSourceMapping
- `AI-excel-addin/schema/driver_resolver.py` — canonical `resolve_driver_key()` + `driver_mapping.yaml`
- `AI-excel-addin/schema/templates/driver_mapping.yaml` — segment-qualified driver key → LineItem ID map
- `AI-excel-addin/schema/build.py` — `populate_from_fmp()` / `populate_from_edgar()` + `preferred_source` handling
- `AI-excel-addin/schema/annotate.py` — `annotate_model_with_research()` — the code that today reads `assumptions[].driver`
- `AI-excel-addin/api/research/repository.py` — research workspace SQLite tables, `DILIGENCE_SECTION_KEYS`, initial artifact shape
- `AI-excel-addin/api/research/handoff.py` — `HandoffService._assemble_artifact()` — live v1.0 artifact builder
- `AI-excel-addin/api/memory/ingest.py` — `IdeaPayload` (today's idea ingress baseline)
- `AI-excel-addin/api/research/policy.py` — `STRATEGY_FACTOR_SUGGESTIONS` + snake_case strategy enum
- `AI-excel-addin/api/agent/profiles/analyst.py` — `DEV_PYTHONPATH_ENTRIES` (the cross-repo import reality)
- `AI-excel-addin/docs/design/thesis-as-source-of-truth-skill-architecture.md` — living Thesis / THESIS.md pattern
- `AI-excel-addin/docs/design/thesis-linkage-task.md` — F3c ThesisLink/ThesisScorecard spec
- `AI-excel-addin/schema/segments.py` — dynamic segment discovery/expansion (SegmentProfile, expand_segments)
- `AI-excel-addin/schema/templates/sia_standard.json` — live template: 392 line items across 26 sections (per `template_builder.py:39`); 52 with `data_concept_id` (13%), 418 with `driver_category` including non-line-item entities, 22 with `template_token`, `template_version: null`

---

## 1. Purpose

Lock the typed contracts that span the equity research workflow across four repos so that:
- An idea surfaces with provenance and flows into a research workspace without lossy re-entry.
- A thesis becomes a financial model without the agent guessing field mappings.
- A model produces refinements that flow back into the thesis and forward into the portfolio.
- A diligence process is configurable to an investor's style, not hardcoded.

**Design-only.** No sub-phases, no file paths, no test counts. Implementation plans cite this doc.

**Design philosophy**: every new type below is grounded in an existing code surface. This doc does not reinvent what the codebase already has — it formalizes it, fills gaps, and ties pieces together.

---

## 2. Workflow — End-to-End

```
investment_tools           idea sourcing
   │
   ▼  InvestmentIdea                                    ◄── contract #1
risk_module / research workspace
   │    (UI + MCP client; backend lives in AI-excel-addin via gateway)
   │
   │  ◄── edgar_updater (filings, XBRL, langextract sections)
   │  ◄── portfolio-mcp / FMP (prices, profile, financials, risk, technicals)
   │  ◄── knowledge wiki (distilled research bites) [addressed later]
   │
   ▼  HandoffArtifact v1.1                              ◄── contract #2
     (structured snapshot derived from living Thesis)
   │
   ▼  ModelBuildContext                                 ◄── contract #3
AI-excel-addin / modelling studio
   │
   ▼  FinancialModel (Excel + agent-readable)
   │
   ▼  ModelInsights + PriceTarget + HandoffPatchOp      ◄── contract #4
       back into Thesis + HandoffArtifact; forward to portfolio
   │
   ▼
portfolio-mcp (sizing, risk, monitoring)

Centering artifact that every view adjusts:
   Thesis (living) + ThesisLink + ThesisScorecard      ◄── contract #6
     rendered as THESIS.md in agent memory

Diligence shape across the whole flow:
   ProcessTemplate parameterizes which sections, which qualitative factors,
   which valuation methods are required for this investor's process.  ◄── contract #5
```

**Six typed contracts.** All Pydantic source-of-truth in `AI-excel-addin/schema/` (extending the existing `schema/models.py` pattern). The handoff artifact v1.0 anchors the center; the other five formalize existing seams or fill them.

---

## 3. Repo Ownership

| Repo | Owns |
|---|---|
| `investment_tools` | Idea sourcing (screens, findings, analyst actions). **Emits `InvestmentIdea`** (a superset of existing `IdeaPayload`). |
| `risk_module` | Research workspace UI + MCP tool surface + portfolio-mcp + gateway client. Proxies to AI-excel-addin backend via gateway. |
| `AI-excel-addin` | Research workspace **backend** (`api/research/`), agent brain + skills, modelling studio (`schema/`), Excel add-in host, ticker memory. **Pydantic source of truth for all six contracts.** |
| `edgar_updater` (+ `edgar-mcp`, `edgar-parser`) | Raw SEC data layer. Feeds modelling studio + workspace prepopulate via existing MCP tools. **Consumer of no contract defined here.** |

**Why AI-excel-addin owns the types**: it already owns `schema/models.py` (FinancialModel) and `api/research/repository.py` (handoff persistence). The living Thesis + THESIS.md pattern lives next to the skill runtime. Colocating the schema with the runtime that mutates it is the simpler model.

---

## 4. Today's Anchor — HandoffArtifact v1.0

The live v1.0 artifact (assembled by `handoff.py::_assemble_artifact`, described in `RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md:283`):

```
HandoffArtifact v1.0 (live today):
  schema_version = "1.0"
  handoff_id, created_at, research_file_id

  company:             {ticker, name, sector, industry, fiscal_year_end, most_recent_fy, exchange}
  thesis:              {statement?, direction, strategy, conviction, timeframe?, source_refs}
  business_overview:   {description?, segments: [{name, rev_pct}], source_refs}
  catalysts:           [{description, expected_date, severity, source_ref}]
  risks:               [{description, severity, type, source_ref}]
  valuation:           {method, low, mid, high, current_multiple, rationale, source_refs}
  peers:               [{ticker, name, source_refs}]
  assumptions:         [{driver, value, unit, rationale, source_refs}]
                       # driver = segment-qualified key resolved via driver_mapping.yaml
                       # (e.g., "revenue.segment_1.volume_growth", "tax_rate",
                       #        "raw:tpl.a.revenue_drivers.operating_metric")
  qualitative_factors: [{id, category, label, assessment, rating?, data?, source_refs}]
  ownership:           {institutional_pct?, insider_pct?, recent_activity?, source_refs}
  monitoring:          {watch_list: [string | {description|summary|label, ...}],
                        source_refs}                                # source_refs is live at handoff.py:224
                       # frontend handles both watch_list shapes (HandoffSectionRenderer.tsx:560-580)
  financials:          {source: "fmp"|"edgar", data}
  sources:             [{id, type, source_id, section_header?, char_start?, char_end?, text, annotation_id?}]
  metadata:            {analyst_session_id?, diligence_completion, diligence_sections, next_factor_id}
```

It's already a multi-consumer contract. Known structural gaps (§5) motivate v1.1 (§6.2).

---

## 5. Gaps

Fifteen gaps, grouped by severity. References are to live code or design docs.

### Tier 1 — structural

**G1. No `InvestmentIdea` type for workspace ingress.** `start_research(ticker, label)` accepts a bare string. `investment_tools/research/db.py` produces `findings` and `screen_hits`; `AI-excel-addin/api/memory/ingest.py` defines `IdeaPayload` (with `thesis`, `source`, `source_date`, `direction`, `strategy`, `catalyst`, `timeframe`, `conviction`, `tags`). Nothing types the handoff from investment_tools → research workspace, and `IdeaPayload` lacks provenance (`idea_id`, structured source).

**G2. ModelBuildContext is not formalized.** `annotate.py:75-83` already reads `assumption.driver` and calls `resolve_driver_cells()`. `driver_mapping.yaml` exists. What's missing:
- A typed contract describing what `build_model()` / `annotate_model_with_research()` consumes beyond the raw handoff (fiscal axis, scenario overrides, source precedence).
- Typed scenario shape (today: `ScenarioInputs.assumptions: Dict[str, float]`; no link to driver keys).
- Validation that driver keys resolve before build, not at write time.

**G3. No typed thesis ↔ model feedback loop.** Building the model sharpens the thesis. `new_handoff_version()` lets a human edit. No typed path for model-derived refinements to PATCH the handoff.

**G4. Model → price target → portfolio one-way + informal.** Valuation `FormulaSpec`s compute targets; no typed `PriceTarget` flows back. Portfolio can't consume a thesis-informed target.

**G13. Thesis is not a first-class living artifact.** No canonical `THESIS.md`. No `ThesisLink` / `ThesisScorecard` (spec exists as F3c, not built). No append-only Decisions Log. No CONSENSUS vs DIFFERENTIATED split in the schema — today's `thesis.statement` is a single prose blob.

### Tier 2 — design

**G5. Industry / unstructured research has no schema.** Handoff has `peers: [{ticker, name}]` only. No industry analysis, competitive dynamics, peer financial comparisons, macro overlay. Today these go into free-form `qualitative_factors[].data`.

**G6. Knowledge wiki not materialized as data.** "Actionable bites" from the course aren't a queryable, agent-callable schema. Agent access patterns are prose-level (skill files), not typed.

**G7. Diligence not configurable per investor process.** `DILIGENCE_SECTION_KEYS` is a hardcoded 9-tuple in `repository.py:109`. No `ProcessTemplate` to configure required sections, section order, seed qualitative factors, or valuation methods allowed.

**G8. EDGAR ↔ FMP precedence is concept-level only.** `DataSourceMapping.preferred_source` exists at concept granularity (`models.py:190`, applied at `build.py:287`). Missing: request-time override, batch-level routing policy, fallback order when `preferred` fails.

**G14. Enum normalization across repos.** Three conventions for strategy today:
- `IdeaPayload._ALLOWED_STRATEGIES = {"Value", "Special Situation", "Macro", "Compounder"}` (title case, `ingest.py:15`)
- `STRATEGY_FACTOR_SUGGESTIONS.keys() = {"value", "special_situation", "macro", "compounder"}` (snake_case, `policy.py:9`)
- `HandoffArtifact.thesis.strategy` = whichever caller wrote (no validator)
- Same problem for `direction` (title-case in IdeaPayload, pass-through in handoff) and `timeframe` (`"Near-term" | "Medium" | "Long-term"` in IdeaPayload, free-form in handoff).

### Tier 3 — polish

**G9. Section shape consistency.** `monitoring` is an object (`{watch_list: []}`); other list-bearing sections are arrays. `catalysts[].source_ref` singular vs `peers[].source_refs` plural. Minor dispatch friction.

**G10. Editorial layer for research report.** F25 `HandoffSectionRenderer` does structural rendering. The `core/overview_editorial/` pipeline is a proven pattern for portfolio overview briefs; it hasn't been cloned for research. Not a *schema* gap (editorial is render-layer by design) — noted for future work.

**G11. Annotation → model lineage one-way.** Annotations link source → finding. No back-link from a model assumption → annotations that justified it.

**G12. Qualitative factor seed categories.** Design doc describes seed categories per strategy; loading mechanism (hardcoded vs config) unspecified. Resolved by G7 (ProcessTemplate).

**G15. `monitoring.watch_list` polymorphism.** Frontend (`HandoffSectionRenderer.tsx:560-580`) handles both `List[string]` and `List[{description|summary|label, ...}]`. Schema is silent. Document both shapes or narrow.

---

## 6. Unified Schema Design

Six contracts. Pydantic source-of-truth in `AI-excel-addin/schema/`. TS types generated downstream.

### 6.0 Preamble — Thesis as the centering artifact

Before contracts, one framing principle (instantiated in §6.6):

**Thesis is the centering artifact.** Every other view — financial model, report, portfolio position, diligence checklist — *challenges or adjusts* the thesis. The model sharpens drivers. The report expresses conviction. The portfolio expresses sizing. Incoming data confirms or disconfirms. The schema reflects this directly.

This produces **two distinct but related artifacts** (§6.2, §6.6):

- **`Thesis` (living)** — the continuously-maintained, analyst-authored artifact. Markdown rendering at `theses/{TICKER}[__label].md`. Holds Differentiated View, Scenarios, Invalidation Triggers, Decisions Log, Model Linkage. Every ticker-scoped skill reads it first.
- **`HandoffArtifact` (snapshot)** — versioned structured snapshot derived from `Thesis` at a point in time, enriched with idea provenance, assumption lineage, and model refs. Consumed programmatically by model build, report, portfolio.

**Sync direction** (decided, §10): `Thesis` is the source of truth for the shared slice. `HandoffArtifact` is always derived on snapshot (finalize / new version). Skills mutate `Thesis`; `HandoffArtifact` fields with no analogue in `Thesis` (idea provenance, assumption lineage, process_template_id, scorecard_ref, thesis_ref, Handoff-shaped model_ref) are authored on the snapshot and preserved through re-derivation — never overwritten.

### 6.1 `InvestmentIdea` (new) — closes G1 + G14

**Key design choice**: superset of existing `IdeaPayload` — 100% backward compatible. Enums canonicalized to snake_case (see §6.2 decision). Provenance fields added.

```
InvestmentIdea v1.0:
  # Required baseline (aligned with IdeaPayload)
  ticker                                # [A-Z]{1,6}, normalized
  thesis                                # prose — initial hypothesis / "why this is interesting"
  source                                # string — origin label
  source_date                           # ISO date

  # Optional baseline (aligned with IdeaPayload)
  company_name?
  strategy?:  value | special_situation | macro | compounder
                                        # canonicalized; accepts Title Case input via canonicalizer
  direction?: long | short | hedge | pair
                                        # canonicalized; accepts Title Case input via canonicalizer
  catalyst?                             # prose — primary catalyst
  timeframe?: near_term | medium | long_term
                                        # canonicalized from "Near-term"/"Medium"/"Long-term"
  conviction?: int in [1, 5]
  tags?: [string]

  # NEW — provenance fields
  idea_id                               # stable UUID
  surfaced_at                           # timestamp (≥ source_date)
  source_ref:
    type: screen | finding | manual | newsletter | research_note | external
    source_id                           # stable ref back to origin row
    source_repo: investment_tools | manual | ...
    source_payload?                     # raw-ish original payload (typed where possible)

  # NEW — cross-linkage
  related:
    findings?:     [finding_id]         # investment_tools refs
    screen_hits?:  [screen_hit_id]
    annotations?:  [annotation_id]

  # NEW — process linkage
  suggested_process_template_id?        # hints ProcessTemplate selection (§6.5)
  label?                                # for multi-thesis concurrency: `research_files.label`

  # NEW — metadata
  metadata: {...}

  schema_version = "1.0"
```

**Producer**: `investment_tools` (structured from `findings`/`screen_hits`) or a manual-entry UI in risk_module.
**Consumer**: `start_research(idea: InvestmentIdea)` in AI-excel-addin backend (new signature, coexists with `start_research(ticker, label)` fallback). Seeds `research_file` with provenance, pre-populates `direction/strategy/conviction/timeframe` and writes `idea_provenance` into the initial handoff artifact.

### 6.2 `HandoffArtifact v1.1` — evolves v1.0, closes G5 / G9 / G11 / G13-partial / G14 / G15

**Backward-compatible at the structural level** (R3, tightened from R2's "strictly additive"): no field is renamed or removed, no required field added. Two caveats made explicit:
1. **Enum canonicalization is a write-time transform.** `direction` / `strategy` / `timeframe` normalize Title-Case legacy input to snake_case on write (§10a.9). v1.0 readers that don't validate enum casing keep working; v1.0 readers that strictly equality-compare against `"Long"` or `"Near-term"` must accept snake_case forms. The JSON *structure* is unchanged.
2. **All new fields are optional.** v1.0 readers ignore unknown keys.

```
HandoffArtifact v1.1 = v1.0 ∪ additions.

schema_version = "1.1"

Changes to existing sections (ADDITIVE ONLY — all new fields optional):

  thesis:
    statement, direction, strategy, conviction, timeframe, source_refs   # UNCHANGED
  + consensus_view?:                   # NEW — what the Street believes
      {narrative, citations: [source_id]}
  + differentiated_view?:              # NEW — where we disagree
      [{claim_id,                      # R4 — stable ID for patch-op targeting
        claim, rationale, evidence: [source_id],
        upside_if_right?, downside_if_wrong?}]
  + invalidation_triggers?:            # NEW — observable signals that kill the thesis
      [{trigger_id,                    # R4 — stable ID for patch-op targeting
        description, metric?, threshold?, direction?}]

  # R4 — thesis_ref moved OUT of the shared `thesis` field to a Handoff-only
  #       top-level field. Rationale: Thesis (SoT) doesn't need to reference itself;
  #       the snapshot needs to point back to the living Thesis it was derived from.

  catalysts:
    [{description, expected_date, severity, source_ref}]                 # UNCHANGED
  + catalyst_id?                       # R4 — stable ID for patch-op targeting (additive)

  risks:
    [{description, severity, type, source_ref}]                          # UNCHANGED
  + risk_id?                           # R4 — stable ID for patch-op targeting (additive)

  assumptions:
    driver, value, unit, rationale, source_refs                          # UNCHANGED
  + assumption_id?                     # NEW — stable ref for lineage + patch ops
  + driver_category?: SIA_enum         # NEW — optional hint (revenue|unit_economics|
                                       #   cost_structure|reinvestment|capital_sources|
                                       #   valuation|other). Informational only; authoritative
                                       #   mapping is still driver → LineItem via driver_mapping.yaml.
  + confidence?: low | medium | high   # NEW

  monitoring:
    watch_list:                                    # EXPLICIT POLYMORPHISM — both shapes remain valid
      [string | {description?|summary?|label?, threshold?, direction?,
                 last_checked?}]                   # (matches HandoffSectionRenderer.tsx dispatch)
    source_refs                                    # live field at handoff.py:224

New top-level sections (all optional):

+ industry_analysis?:                  # closes G5
    landscape?:         {narrative, citations: [source_id]}
    peer_comparison?:
      peers: [{ticker, name, key_metrics?, relative_position?, source_refs}]
    macro_overlay?:     {drivers: [{description, sensitivity, source_refs}]}
    structural_trends?: [{description, time_horizon?, source_refs}]

+ idea_provenance?:                    # closes G1 back-link
    idea_id, source_summary

+ assumption_lineage?:                 # closes G11
    [{assumption_id,
      supporting_annotation_ids: [annotation_id],
      refutes_annotation_ids?:   [annotation_id]}]

+ process_template_id?                 # closes G7 — which template governed this diligence

+ model_ref?:                          # closes G3/G4 forward links
    {model_id, version,                 # R3 — per §8 composite versioning rule
     model_build_context_id, model_build_context_version,
     last_price_target?}

+ scorecard_ref?:                      # closes G13 snapshot link
    {scorecard_id, version,             # R3 — per §8 composite versioning rule
     scored_at, summary_status}

+ thesis_ref?:                          # R4 — moved from thesis.thesis_ref to top-level
    {thesis_id, version,                # Handoff-only metadata: points back to the living Thesis
     markdown_path}                     # that produced this snapshot.
```

**Enum canonicalization rule** (closes G14): Pydantic validators on `direction`, `strategy`, `timeframe` canonicalize at write time — accept Title Case legacy input (`"Value"`, `"Near-term"`, `"Long"`), store snake_case. Readers always see canonical form. Canonicalizer helpers live in `schema/enum_canonicalizers.py`.

**Assembly rule** (preserves today's `_assemble_artifact` behavior): v1.1 fields are populated from the Thesis snapshot when present; v1.0 fields continue to be assembled from `file_row` + draft artifact + annotations exactly as today.

### 6.3 `ModelBuildContext` (new) — closes G2, the Rosetta Stone

**Key design choices** (R3):
- Dict-based drivers/scenarios (uniqueness enforced by Pydantic dict key; matches existing `ScenarioInputs.assumptions: Dict[str, float]` at `models.py:338`, not lists). Eliminates R2 ambiguity on duplicate/overlapping driver entries.
- Grounded in live `build_model()` signature at `build.py:496` — carries all build determinants explicitly: `formula_first`, `n_historical`, `n_projection`, `source`, `segment_config`.
- Segment expansion is first-class, not an afterthought. Dynamic segments 3+ produced by `expand_segments()` are captured via `segment_config.segment_profile_snapshot` so MBC is *complete* relative to what the builder needs.
- Driver key validation at MBC construction time — both `driver_mapping.yaml` keys AND `raw:` keys. Closes the R2 finding that `resolve_driver_key()` only strips the `raw:` prefix without checking the literal exists in the template.

```
ModelBuildContext v1.0:
  model_build_context_id
  handoff_ref: {research_file_id, handoff_id, handoff_version}

  # Build orchestration — grounded in build_model() signature (build.py:496-513)
  source: fmp | edgar                    # 'edgar' required when segment discovery enabled
  n_historical: int = 5
  n_projection:  int = 12
  formula_first: bool = True             # drives apply_formula_first() step (build.py:605)
  sector?

  company:
    ticker, name, fiscal_year_end, most_recent_fy

  fiscal_axis:
    period_mode: yearly | quarterly5     # matches PERIOD_MODE_* in models.py
    historical_years: [int]              # explicit, not just window count
    projection_years:  [int]

  # Segment discovery + override — grounded in segments.py + build_model(segment_mapping, axis)
  segment_config?:
    axis?: string                        # optional pin for EDGAR segment axis; auto-discover if null
    segment_mapping?:                    # caller overrides — shape per apply_segment_overrides (segments.py:263)
      [{edgar_member,                    # required for override match
        name?,                           # display rename
        volume_label?,                   # KPI label
        price_label?}]
    segment_profile_snapshot:            # R6 — REQUIRED when segment_config is populated
                                          # (i.e., whenever segment mode is in use)
      axis_used?,                        # actual axis used by discovery
      source: "edgar_auto" | "caller_override" | "fallback_single",
      segments: [{segment_index,         # 1-based; stable ordering locked at MBC time
                  name,                  # display name (used by expand_segments)
                  edgar_member?,
                  volume_label?,         # R6 — consumed by overrides + expansion (segments.py:294, :821)
                  price_label?,          # R6 — consumed by overrides + expansion
                  revenue_values?: {year: value}}]
      total_revenue_check?: {year: value}
                                          # R6 binding rule: when segment_config is present, this
                                          # snapshot MUST be populated and MUST be used by the builder
                                          # verbatim — NO re-discovery, NO re-sort by current-year
                                          # revenue, NO re-application of segment_mapping overrides at
                                          # build time. The snapshot IS the input.
                                          # MBC construction rejects segment_config without a populated
                                          # segment_profile_snapshot (typed `MissingSegmentSnapshot`).
                                          # Requires a build_model() behavior change (tracked in
                                          # MODEL_BUILD_CONTEXT_PLAN.md) — today's builder re-discovers.

  # Drivers — dict-based, keyed by driver_key (eliminates list ambiguity)
  drivers:
    {driver_key: {                       # SAME key space as HandoffArtifact.assumptions[].driver
        assumption_id?,                  # back-link to handoff assumption for patch ops
        value,
        unit: dollars|percentage|ratio|count|per_share|days|multiple,
        periods?: [int],                 # default: all projection_years
        sia_category?: DriverCategory,   # optional hint; authoritative mapping via resolve_driver_key
        rationale?,
        confidence?: low|medium|high}}

  # Scenarios — dict-based, matches ScenarioInputs.assumptions shape (models.py:338)
  scenarios:
    {scenario_name: {
        description?,
        overrides: {driver_key: {        # per-scenario; driver_key shadows base drivers entry
            value,
            periods?: [int]}}}}

  valuation:
    method: dcf | multiples | sum_of_parts | hybrid
    inputs:
      discount_rate?:    {value, method: capm|wacc|manual, inputs?: {...}}
      terminal_growth?:  {value, rationale?}
      exit_multiple?:    {value, multiple_type: p_e|ev_ebitda|p_b|p_s|ev_sales}
    ranges: {low, mid, high}
    rationale

  historical_sources:                    # closes G8 — request-time precedence over concept default
    default_source: fmp | edgar
    overrides:
      [{concept_id,                      # matches DataSourceMapping.concept_id
        preferred: fmp | edgar,
        fallback_order: [fmp | edgar]}]  # Layered on concept-level preferred_source at build.py:287

  build_flags:
    include_historicals: bool
    annotate_with_research: bool         # run annotate_model_with_research post-build
    preview_mode: bool

  schema_version = "1.0"
```

**Driver key validation at MBC construction — two-phase** (R4, closes Codex R3 finding #2):

The problem R3 didn't solve: `driver_mapping.yaml` sends `revenue.segment_1.volume_growth` → `tpl.a.revenue_drivers.volume_2_growth`, but `expand_segments()` (`segments.py:322-409`) **deletes that template ID** and rebuilds as `business_segment_{n}_*`. So static YAML validation approves keys the builder can't apply after expansion. Fix:

**Phase 1 — Static validation (always runs)**:
1. Non-`raw:` keys: must exist in `load_driver_mapping()`. Resolve → LineItem ID in SIA template.
2. `raw:`-prefixed keys: strip prefix, literal must resolve to an item in the SIA template via `_find_item()`.
3. Template item must be `ItemType.input`.

**Phase 2 — Post-expansion validation (segment-mode builds)**:

Segment mode requires `segment_config.segment_profile_snapshot` (per §6.3 schema). Phase 2 always runs for segment-mode MBCs:
1. Simulate expansion against the snapshot (authoritative input, not a cache).
2. Re-resolve every `driver_key`. Keys whose Phase 1 resolution targets a template ID **deleted by expansion** (e.g., `tpl.a.revenue_drivers.volume_2_growth` → deleted when segment 1 is expanded) must be replaced by a `raw:` key pointing to the post-expansion ID (e.g., `raw:tpl.a.revenue_drivers.business_segment_1_volume_growth`).
3. Per-key classification per Decision 15 (three categories). Unresolved Category A keys → `SegmentExpansionAmbiguity`. Category B keys → `UnsupportedInSegmentMode`. No silent skip.

**Prerequisite decision for segment-mode builds** (moved to §10a): either (a) rework `driver_mapping.yaml` to emit segment-expansion-aware resolutions (recommended long-term), or (b) require analysts/agents to use `raw:` keys for segment drivers once segments are known. Until (a) is done, MBC construction for segment-mode builds MUST use `raw:` keys for any segment-qualified Category A driver (Category B rejected outright). This is enforced by Phase 2 validation.

This shifts today's tolerant-skip behavior (`annotate.py:82-86`) to construction time: autonomous agent builds fail fast with actionable errors rather than silently dropping assumptions.

**Producer**: risk_module / AI-excel-addin backend on `build_model` invocation. Derived from `HandoffArtifact v1.1` + workspace state + optional user overrides.
**Consumer**: `modelling studio / build_model()` in AI-excel-addin. `resolve_driver_cells()` remains the final address resolver for writing values to cells.

**Payoff**: the builder's full input is typed and validated at construction. Autonomous agent model builds become deterministic — no free-string drift, no silent skips, no segment-3 ambiguity.

### 6.4 `ModelInsights` + `PriceTarget` + `HandoffPatchOp` (new) — close G3, G4

Three related types. `HandoffPatchOp` makes the model→thesis feedback loop a typed contract instead of prose.

```
ModelInsights v1.0:
  model_insights_id
  model_ref
  model_build_context_id
  generated_at

  driver_sensitivities:
    [{driver_key, target_metric,
      impact_per_unit,                             # sensitivity coefficient
      rank,
      periods?: [int]}]

  implied_assumptions:                             # assumptions the model made explicit beyond handoff
    [{driver_key, sia_category, value, unit, rationale,
      suggests_patch: bool}]                       # true if should propose to handoff

  risks_surfaced:                                  # risks the build process uncovered
    [{description, severity: low|medium|high, type?, evidence?: [source_id]}]

  handoff_patch_suggestions: [HandoffPatchOp]      # see below

  schema_version = "1.0"

HandoffPatchOp v1.0 (discriminated union, typed)
  # R4: all target references use stable IDs (assumption_id, risk_id, catalyst_id,
  #     claim_id, trigger_id) — no index-based targeting (indices drift under insert/reorder).
  # R5: patch ops target the Thesis (SoT) for shared-slice fields (including
  #     industry_analysis, which is shared-slice per §6.6). HandoffArtifact snapshots
  #     re-derive automatically. A small number of Handoff-only fields (idea_provenance,
  #     assumption_lineage) are rarely patched by model feedback; when needed, ops for
  #     them live in follow-on plans, not this doc.

  op_id, reason

  # === Assumptions (full CRUD) ===
  op: replace_assumption_value
    target: {assumption_id}
    value: float
  | update_assumption_field                        # rationale/confidence/unit/driver_category
    target: {assumption_id,
             field: "rationale" | "confidence" | "unit" | "driver_category"}
    value: scalar-per-field
  | add_assumption
    target: null
    value: {driver, value, unit, rationale, source_refs?, driver_category?, confidence?}
  | remove_assumption                              # R4 — missing in R3
    target: {assumption_id}
    value: null

  # === Thesis headline fields ===
  | replace_thesis_field
    target: {field: "statement" | "direction" | "strategy" | "conviction" | "timeframe"}
    value: scalar-per-field

  # === Thesis quantitative framing (Thesis-only, added back in R4) ===
  | update_thesis_quantitative
    target: {section: "revenue" | "margins" | "eps_fcf"
                    | "scenarios.bull" | "scenarios.base" | "scenarios.bear",
             field: string}                        # e.g., "base", "target_price", "return_pct"
    value: scalar

  # === Valuation (shared slice) ===
  | update_valuation
    target: {field: "low" | "mid" | "high" | "method" | "current_multiple" | "rationale"}
    value: scalar

  # === Consensus / Differentiated view (R4 — new) ===
  | update_consensus_view
    target: null
    value: {narrative?, citations?: [source_id]}
  | add_differentiated_view_claim
    target: null
    value: {claim, rationale, evidence: [source_id],
            upside_if_right?, downside_if_wrong?}
  | update_differentiated_view_claim
    target: {claim_id}
    value: {claim?, rationale?, evidence?, upside_if_right?, downside_if_wrong?}
  | remove_differentiated_view_claim
    target: {claim_id}
    value: null

  # === Risks (full CRUD — R4) ===
  | add_risk
    target: null
    value: {description, severity, type?}
  | update_risk
    target: {risk_id}
    value: {description?, severity?, type?}
  | remove_risk
    target: {risk_id}
    value: null

  # === Catalysts (full CRUD — R4) ===
  | add_catalyst
    target: null
    value: {description, expected_date?, severity}
  | update_catalyst
    target: {catalyst_id}
    value: {description?, expected_date?, severity?}
  | remove_catalyst
    target: {catalyst_id}
    value: null

  # === Invalidation triggers (full CRUD) ===
  | add_invalidation_trigger
    target: null
    value: {description, metric?, threshold?, direction?}
  | update_invalidation_trigger
    target: {trigger_id}                           # R4 — stable id, not index
    value: {description?, metric?, threshold?, direction?}
  | remove_invalidation_trigger
    target: {trigger_id}
    value: null

PriceTarget v1.0:
  price_target_id
  model_ref: {model_id, version}                   # R3 — per §8 composite versioning rule
  as_of
  ranges: {low, mid, high}
  confidence: low | medium | high
  method: dcf | multiples | sum_of_parts | hybrid  # R3 — unified with valuation.method (was "blended")
  driver_sensitivities: [{driver_key, delta_per_pct, rank}]
  time_horizon_months
  current_price, implied_return_pct
  schema_version = "1.0"
```

**Producer**: AI-excel-addin modelling studio (on model build + on scenario runs).
**Consumers**:
- `Thesis` + `HandoffArtifact v1.1` (via `model_ref.last_price_target` + applying `handoff_patch_suggestions` after analyst/skill review — never auto-applied, per §10 decision)
- Portfolio-mcp (for sizing signals — typed input, not prose)
- Research workspace UI / THESIS.md (displayed in thesis view)

### 6.5 `ProcessTemplate` (new) — closes G7, G12

**Key design choice** (scoped down from R1): v1 keeps the nine fixed `DILIGENCE_SECTION_KEYS` + fixed `DriverCategory` enum. Template configures *which sections are required*, *ordering*, *seed qualitative factors*, and *valuation methods allowed* — it does NOT redefine the section space or the driver taxonomy. Breaking those would require bumping template schema major + migrating `repository.py` + `handoff.py` + `driver_mapping.yaml` dependents.

```
ProcessTemplate v1.0:
  template_id
  name, description?
  investor_profile?:
    strategy_bias?: value | special_situation | macro | compounder
    holding_period_bias?: near_term | medium | long_term
    style_notes?

  section_config:
    # Overlay on fixed DILIGENCE_SECTION_KEYS — the keys themselves are not overridable in v1.
    required:     [section_key]                   # subset of DILIGENCE_SECTION_KEYS
    order:        [section_key]                   # permutation (default = existing order)
    min_completion: {section_key: "empty"|"draft"|"confirmed"}

  seed_qualitative_factors:                       # pre-populated categories for this template
    [{category, label, guidance?, default_rating?, default_data_shape?}]

  valuation_methods_allowed:
    [dcf | multiples | sum_of_parts | hybrid]

  required_source_coverage?:
    min_filings?, min_transcripts?, min_industry_refs?

  schema_version = "1.0"
```

**Producer**: config (YAML shipped with AI-excel-addin) + user-created via UI (stored in SQLite).
**Consumer**: `activate_diligence()` / `prepopulate_diligence()` / handoff finalization reads template to determine required completion + seed factors.
**Handoff link**: `HandoffArtifact.process_template_id` records which template governed this research.

**v1 constraints** (callouts for future versions):
- Does not redefine section keys (future: v2 with migration).
- Does not override `DriverCategory` enum (future: per-template driver taxonomy via template schema v2).
- Does not redefine qualitative factor shape — only seeds which categories to pre-populate.

### 6.6 `Thesis` + `ThesisLink` + `ThesisScorecard` (new) — closes G13

The centering living artifact + typed linkage to model + outcome tracker. Subsumes F3c.

**Shared-slice isomorphism** (locked in R3, completed in R4): `Thesis` uses the *identical field shapes* as `HandoffArtifact v1.1` for every concept that appears in both. Shared-slice fields mirror HandoffArtifact verbatim. Thesis-only fields (decisions_log, model_links, markdown_path, quantitative_framing, position_metadata) live at the top level alongside.

**R4 source-registry ownership** (closes Codex R3 finding #1): `Thesis.sources[]` is the **canonical source registry**. HandoffArtifact derivation copies `sources[]` verbatim — source IDs (`src_n`) persist across snapshots. The current `_SourceRegistry` behavior in `handoff.py:83` that generates snapshot-local IDs is superseded: under v1.1 assembly, the source registry reads from Thesis and preserves IDs. (Implementation detail for `HANDOFF_ARTIFACT_V1_1_PLAN.md`.)

**Keying** (unchanged from R2): `(user_id, ticker, label)` matches `research_files`. Markdown path:
- `theses/{TICKER}.md` when no label
- `theses/{TICKER}__{label_slug}.md` when labeled

```
Thesis v1.0:
  # Identity
  thesis_id
  user_id, ticker, label?                         # matches research_files (ticker, label)
  version                                         # auto-incremented on save
  created_at, updated_at
  markdown_path                                   # where THESIS.md lives

  # ═══ Shared slice — IDENTICAL shapes to HandoffArtifact v1.1 ═══

  company: {ticker, name, sector?, industry?,
            fiscal_year_end?, most_recent_fy?, exchange?}

  thesis:                                         # matches HandoffArtifact.thesis (v1.1)
    statement?                                    # headline prose
    direction?:  long | short | hedge | pair
    strategy?:   value | special_situation | macro | compounder
    conviction?: int in [1, 5]
    timeframe?:  near_term | medium | long_term
    source_refs: [source_id]
  consensus_view?:                                # matches HandoffArtifact v1.1
    {narrative, citations: [source_id]}
  differentiated_view?:                           # matches HandoffArtifact v1.1
    [{claim_id, claim, rationale, evidence: [source_id],
      upside_if_right?, downside_if_wrong?}]
  invalidation_triggers?:                         # matches HandoffArtifact v1.1
    [{trigger_id, description, metric?, threshold?, direction?}]

  business_overview?:                             # matches HandoffArtifact
    {description?, segments: [{name, rev_pct?}], source_refs}

  catalysts:                                      # matches HandoffArtifact (with catalyst_id)
    [{catalyst_id?, description, expected_date?, severity, source_ref?}]

  risks:                                          # matches HandoffArtifact (with risk_id)
    [{risk_id?, description, severity, type?, source_ref?}]

  valuation:                                      # matches HandoffArtifact (closes R2 blocker #1)
    {method, low, mid, high, current_multiple?, rationale, source_refs}

  peers:                                          # matches HandoffArtifact
    [{ticker, name, source_refs}]

  assumptions:                                    # matches HandoffArtifact (closes R2 blocker #1)
    [{assumption_id?, driver, value, unit, rationale, source_refs,
      driver_category?: DriverCategory,
      confidence?: low|medium|high}]

  qualitative_factors:                            # matches HandoffArtifact
    [{id, category, label, assessment, rating?, data?, source_refs}]

  ownership?:                                     # matches HandoffArtifact
    {institutional_pct?, insider_pct?, recent_activity?, source_refs}

  monitoring?:                                    # matches HandoffArtifact
    {watch_list: [string | {description?|summary?|label?, ...}],
     source_refs?}

  sources:                                        # R4 — canonical source registry (SoT)
    [{id,                                         # stable "src_n" ID, persists across snapshots
      type: filing | transcript | investor_deck | other,
      source_id, section_header?,
      char_start?, char_end?, text,
      annotation_id?}]                            # back-link to per-user research.db annotations

  industry_analysis?:                             # R5 — restored to shared slice
    {landscape?:      {narrative, citations: [source_id]},
     peer_comparison?: {peers: [{ticker, name, key_metrics?, relative_position?, source_refs}]},
     macro_overlay?:   {drivers: [{description, sensitivity, source_refs}]},
     structural_trends?: [{description, time_horizon?, source_refs}]}
                                                   # Lives on Thesis (SoT); derived verbatim to Handoff.
                                                   # All citations reference Thesis.sources[] registry.
                                                   # Resolves R4 source-registry tension + workflow gap
                                                   # for Thesis-first skills that need structured
                                                   # industry context between snapshots.

  # ═══ Thesis-only fields (no HandoffArtifact analogue) ═══

  quantitative_framing?:                          # R4 — restored as Thesis-only section
    revenue?:   {base?, bull?, bear?, rationale?} # Source of truth for Thesis scenario ranges.
    margins?:   {trajectory?, key_drivers?}       # HandoffPatchOp.update_thesis_quantitative
    eps_fcf?:   {projection?, delta_vs_consensus?} # targets these fields directly.
    scenarios?:
      bull?: {target_price, return_pct, what_has_to_happen}
      base?: {target_price, return_pct, methodology}
      bear?: {target_price, return_pct, what_goes_wrong}

  position_metadata:                              # fields without HandoffArtifact analogue
    position_size?: {target_pct?, current_pct?}
    date_initiated?
    portfolio_fit?:
      sector_exposure?, factor_exposure?, correlation_cluster?

  decisions_log:                                  # append-only audit trail
    [{date, skill, decision, rationale,
      previous_value?, new_value?,
      patch_ops_applied?: [HandoffPatchOp]}]      # typed record of what changed
                                                   # Append helper with per-(user_id, ticker, label) lock
                                                   # (§10a.7) prevents concurrent-skill corruption.

  model_ref?:                                     # Thesis-only shape — LIVING reference
    {model_id, version,                           # Points to the model currently linked to this thesis.
     file_path?, last_updated?,                   # Updated on every /thesis-link or model rebuild.
     drivers_locked: [driver_key]}
                                                   # NOTE: HandoffArtifact has a DIFFERENT-shaped
                                                   # model_ref (snapshot reference with
                                                   # model_build_context_id + last_price_target).
                                                   # Both are non-shared. No round-trip.

  model_links: [ThesisLink]
  scorecard?: ThesisScorecard                     # latest cached snapshot; source of truth in own table
  raw_markdown_extras?: string                    # unknown sections preserved verbatim (§10a.6 round-trip)

  schema_version = "1.0"
```

**Round-trip rule (R4, closes Codex R3 finding #1)**:

`Thesis` → `HandoffArtifact v1.1` derivation copies shared-slice fields **verbatim**, including `sources[]` (source IDs persist). Any shape change to a shared-slice field requires updating both schemas in lockstep (same PR). The isomorphism is a load-bearing invariant.

**Shared slice** (identical on both sides, copied verbatim):
company, thesis, consensus_view, differentiated_view, invalidation_triggers, business_overview, catalysts, risks, valuation, peers, assumptions, qualitative_factors, ownership, monitoring, sources, industry_analysis.

**Thesis-only** (does NOT flow to HandoffArtifact):
`decisions_log`, `model_links`, `position_metadata.*`, `markdown_path`, `raw_markdown_extras`, `quantitative_framing`, `model_ref` (Thesis-shaped), `scorecard`.

**HandoffArtifact-only** (authored on snapshot, preserved through re-derivation — never overwritten):
`idea_provenance`, `assumption_lineage`, `process_template_id`, `scorecard_ref`, `thesis_ref`, `financials`, `metadata.diligence_completion`, `metadata.diligence_sections`, `metadata.next_factor_id`, `model_ref` (Handoff-shaped).

Both sides have a `model_ref` field with *different shapes*. They point at the same underlying model from different perspectives (living vs snapshot). Neither is derived from the other.

**R5 note** — no Handoff-only section has citations by `source_id`. This means `HandoffArtifact.sources[]` is truly a verbatim copy of `Thesis.sources[]`. All source-id references live on shared-slice sections; snapshot-only sections (idea_provenance, assumption_lineage, financials, etc.) reference annotation_ids or IDs scoped to other registries, not `source_id`.

```
ThesisLink v1.0:                                  # typed bridge from claim → model variable
  thesis_link_id
  thesis_point_id                                 # stable ID for the claim
  thesis_text
  category: revenue | margin | growth | valuation | catalyst | risk

  # ═══ Anchor hierarchy (tried in order, documented in code) ═══
  driver_key?                                     # Primary: matches assumptions[].driver
                                                   # Resolves via driver_mapping.yaml (authoritative)
  data_concept_id?                                # Only ~12% of template items (52/418) populate this —
                                                   # works for imported items, fails silently otherwise
  structural_fingerprint?:                        # R3 NEW, R4 enhanced, R5 complete — 5th anchor
    sheet: "Assumptions" | "Financial_model" | ...
    section_id:            string                 # e.g., "revenue_drivers"
    driver_category?:      DriverCategory         # nearly universal on line items (stable)
    repeat_group_id?:      string                 # from LineItem.repeat_group_id (models.py:298)
    repeat_group_role?:    string                 # from LineItem.repeat_group_role
                                                   # e.g., "volume_growth" | "price_growth" | "revenue"
    segment_index?:        int                    # R5 — 1-based; which segment within a repeat_group
                                                   # Set by expand_segments() at build time (segments.py:368)
                                                   # Combines with repeat_group_role to uniquely identify
                                                   # items in expanded revenue sections.
    segment_edgar_member?: string                 # R5 — EDGAR segment member when available
                                                   # (SegmentInfo.edgar_member from segments.py:127)
                                                   # Survives segment renames; most durable anchor for
                                                   # EDGAR-discovered segments.
    label_pattern?:        string                 # literal or regex for label match (tiebreaker only)
    position_index?:       int                    # 1-based index within section (last-resort tiebreaker)
  model_item_id?                                  # Cache; warned as fragile when used

  # ═══ Resolution context ═══
  template_version?                               # ModelMetadata.template_version at link time
                                                   # Currently always null (sia_standard.json:26979);
                                                   # documented here for forward compatibility
  model_id?                                       # which specific model emitted this link

  # ═══ Thesis claim vs reality ═══
  thesis_value?
  thesis_direction: above_consensus | below_consensus | specific_value | directional
  periods: [int]
  consensus_value?

  schema_version = "1.0"
```

**ThesisLink resolution order (R5)** — structural fingerprint uses repeat-group + segment_index as primary matchers:

1. **`driver_key`** → `resolve_driver_key()` → item_id → `_find_item()` in current model. If found: resolved (anchor = `driver_key`). **Authoritative path for any driver in `driver_mapping.yaml`.**
2. **`data_concept_id`** → scan current model for items with matching `data_concept_id` (unique by convention). If found: resolved (anchor = `data_concept_id`). Skipped when the template item has `data_concept_id: null` (~87% of items today).
3. **`structural_fingerprint`** — match in this sub-order:
   1. `{sheet, section_id, repeat_group_id, repeat_group_role, segment_index}` → **primary match** for expanded-segment items. Unique by construction: `repeat_group_role` differentiates within a segment, `segment_index` differentiates across segments.
   2. `{sheet, section_id, repeat_group_id, repeat_group_role, segment_edgar_member}` → alternative primary match when the EDGAR member is known. Survives segment renames and reorderings.
   3. `{sheet, section_id, driver_category}` + `label_pattern` → secondary match for non-repeat-group items.
   4. `position_index` → last-resort tiebreaker only when other fields don't disambiguate.
4. **`template_version` + `model_item_id`** → if the link's `template_version` matches the current model's `ModelMetadata.template_version` AND both are non-null, `model_item_id` is trusted as a stable cache. Skip when either is null (current reality per `sia_standard.json:26979`).
5. **`model_item_id` as last resort** → direct lookup; emit warning `stale_model_item_id`.
6. **Unresolvable** → scorecard entry `status = unresolvable`, `resolution_anchor = none`.

**Template invariant for new-linkage items** (R3): when `/thesis-link` creates new `ThesisLink` entries, the skill requires at least one of `{driver_key, data_concept_id, structural_fingerprint}` to be populated. Pure `model_item_id`-only links are rejected at creation (only tolerated when reading legacy data).

**Known anchor-strength gap** (R5, called out by Codex R5 medium #3): the current SIA template populates `repeat_group_id` / `repeat_group_role` on expanded revenue Assumptions + `Financial_model.income_statement` rows (strong primary match). It does **not** populate them on expanded `Financial_model.margins` or `Financial_model.growth_rates` segment rows (per `sia_standard.json:18563, 19373` — those rows have `repeat_group_id: null`). Links to margin/growth rows will fall through step 3.1 and resolve via the weaker `{section_id, driver_category}` + `label_pattern` + `position_index` path. This is a template-data gap, not a schema gap: the fix is to populate `repeat_group_id` on those rows during `expand_segments()`. Tracked in `MODEL_BUILD_CONTEXT_PLAN.md` as a prereq for robust linkage to margin/growth drivers.

```
ThesisScorecard v1.0:
  scorecard_id
  thesis_id, scored_at
  entries:
    [{thesis_point_id, thesis_text,
      status: confirmed | tracking | challenged | disconfirmed | unresolvable,
      resolution_anchor: driver_key | data_concept_id | structural_fingerprint
                       | model_item_id | none,
      resolution_warnings?: [string],             # e.g., "stale_model_item_id"
      model_reflects_thesis: bool,
      latest_actual?, actual_vs_thesis?: above | at | below | not_yet_reported,
      consensus_vs_thesis?: converging | diverging | aligned,
      notes?}]
  summary_status: on_track | mixed | at_risk | invalidated
  confirmed_count, challenged_count, disconfirmed_count
  schema_version = "1.0"
```

**Relationship to HandoffArtifact v1.1**:
- `Thesis` is the **living source of truth** for the shared slice. Analysts write to it directly (markdown) or via skills.
- `HandoffArtifact v1.1` **derives** the shared slice from `Thesis` on finalize / new-version — verbatim copy. Non-shared HandoffArtifact fields are authored on the snapshot and preserved through re-derivation.
- **Shared-slice isomorphism is an invariant**: both schemas move together on any shared-slice change.

**Skill integration (workflow, not schema)** — lives in skill files, not types:
- `/thesis-consultation` creates/updates Thesis, appends to Decisions Log
- `/thesis-review` runs ThesisScorecard, surfaces status changes
- `/thesis-pre-mortem` stress-tests before initiation
- Ticker-scoped skills read Thesis as their first step (via CLAUDE.md hook in the skill-runtime project, not this repo's CLAUDE.md)

---

## 7. Type Location & Ownership

**Pydantic source of truth**: `AI-excel-addin/schema/` — extend the existing pattern of `schema/models.py`. Likely new modules:
- `schema/research_contracts.py` — `InvestmentIdea`, `HandoffArtifact v1.1` additions, `ModelInsights`, `PriceTarget`, `HandoffPatchOp`
- `schema/model_build_context.py` — `ModelBuildContext`
- `schema/process_template.py` — `ProcessTemplate`
- `schema/thesis.py` — `Thesis`, `ThesisLink`, `ThesisScorecard`
- `schema/enum_canonicalizers.py` — Title Case ↔ snake_case helpers for `direction`, `strategy`, `timeframe`

**Consumption patterns** (grounded in how cross-repo code runs today, `analyst.py:58-65`):

1. **Dev / local**: `DEV_PYTHONPATH_ENTRIES` wires `/Users/henrychien/Documents/Jupyter`, `risk_module`, `Edgar_updater` onto PYTHONPATH. Code in any sibling repo can import directly (e.g., `from schema.research_contracts import InvestmentIdea`). This is how `schema/annotate.py:16-18` already imports `from research.repository import ...` with a fallback alias. New contracts follow the same pattern.

2. **Production / cross-process**: gateway JSON. Pydantic emits JSON Schema at the boundary; consumers (other repos, MCP clients) validate JSON at ingress. No shared PyPI package required.

3. **Frontend (risk_module)**: TypeScript types generated from Pydantic JSON schemas. Pattern already established by F25 work (frontend knows the handoff artifact shape by convention).

4. **investment_tools**: in dev, imports `InvestmentIdea` via PYTHONPATH; in production, produces matching JSON validated at the gateway boundary.

**Enforcement**: gateway boundary validates on ingress. Contract violations → typed `ActionValidationError` (already exists).

---

## 8. Versioning Strategy

**Decided: per-contract semver with explicit composite rules.**

Each contract carries its own `schema_version: "MAJOR.MINOR"`. Rules:
- **MINOR** bump: additive, backward-compatible (new optional field, new enum variant).
- **MAJOR** bump: breaking (rename, remove, required-field addition). Requires migration.

Consumers pin to **major**. HandoffArtifact goes from `"1.0"` → `"1.1"` on the additions in §6.2 (non-breaking).

**Composite embedding rule** (closes R1 consider #1):
- If contract A embeds contract B inline, B retains its own `schema_version` field at the embedded location.
- If contract A references contract B by ID, A stores `{id, version}` — e.g., `model_ref: {model_id, version}`.
- A's own `schema_version` governs A's shape only; it is NOT bumped when embedded B's minor-version changes.

**Alternative considered**: single unified `schema_version` across all contracts. Rejected — couples the lifecycles of six independent types, forces a version bump on one whenever another changes.

---

## 9. Editorial vs Structural

Confirmed from the design discussion:

- **Structural layer** = the six contracts in §6. Defines *what* information exists, *how it's typed*, *how consumers read it*.
- **Editorial layer** = rendering concern over structure. Voice, layout, density, visual emphasis. Not a schema concern.

**Implication**: human-readable report, Excel model, and workspace UI all read the same structured core. Editorial differences live in the render layer (F25 `HandoffSectionRenderer` for workspace UI, a future research-editorial pipeline for PDF/export, modelling-studio renderer for Excel) — not in separate data schemas.

**Special case: `THESIS.md`.** The markdown file in agent memory is the analyst-authored rendering of `Thesis`. It's both *input* (analyst edits directly, skills parse back) and *output* (structured Thesis → markdown via serializer). Different from report/model renderings, which are output-only.

**Round-trip mechanism** (§10 decision): constrained sections with schema-enforced headers. A markdown parser with known section names populates structured fields; fields not found in markdown default to null. Free-form prose within each section is preserved verbatim. No AST-level markdown parsing — too fragile.

The existing `core/overview_editorial/` pipeline (portfolio overview brief) is a **proven pattern** that can be cloned for research report rendering when that becomes priority. Future project, not decided here.

---

## 10. Decisions (was: Open Questions)

Eleven decisions. Items the R1 review flagged as "can't be left open" are locked here; genuinely deferred questions stay in §10b.

### 10a — Locked decisions

1. **Versioning**: per-contract semver with composite embedding rule (§8).
2. **InvestmentIdea ingress API**: `start_research(idea: InvestmentIdea)` coexists with legacy `start_research(ticker, label)`. Simple-path users keep the ticker-only path; typed path enables provenance.
3. **ModelBuildContext construction**: derived automatically from `HandoffArtifact v1.1` + workspace state by a service helper; analyst/agent override points are explicit fields on the context (scenarios, historical_sources, build_flags), not hidden patches.
4. **handoff_patch_suggestions auto-apply**: **never auto-applied**. Always presented for analyst/skill confirmation. Thesis ownership stays with the analyst.
5. **Thesis ↔ HandoffArtifact sync direction**: `Thesis` is source of truth for the shared slice. HandoffArtifact derives the shared slice on snapshot (verbatim copy, including `sources[]` IDs and `industry_analysis`). HandoffArtifact-only fields (`idea_provenance`, `assumption_lineage`, `process_template_id`, `scorecard_ref`, `thesis_ref`, Handoff-shaped `model_ref`) are authored on the snapshot and preserved through re-derivation — never overwritten. **R5 correction**: `industry_analysis` is shared-slice (lives on Thesis, derived to Handoff), not Handoff-only. No Handoff-only section carries `source_id` citations, which keeps `Thesis.sources[]` → `HandoffArtifact.sources[]` as a verbatim copy.
6. **THESIS.md round-trip**: constrained sections with schema-enforced headers. Parser maps known sections → structured fields; unknown sections preserved verbatim in `raw_markdown_extras`.
7. **Decisions Log concurrency**: append helper tool in `schema/thesis.py` acquires a per-`(user_id, ticker, label)` lock (filesystem or SQLite advisory). Skills never write to the log directly.
8. **Scope identity (multi-thesis)**: `Thesis` keyed by `(user_id, ticker, label)` matching `research_files`. Markdown paths: `theses/{TICKER}.md` (no label) or `theses/{TICKER}__{label_slug}.md` (labeled).
9. **Enum canonicalization**: snake_case is canonical (`value`, `special_situation`, `macro`, `compounder`, `near_term`, `medium`, `long_term`, `long`, `short`, `hedge`, `pair`). Canonicalizer helpers accept Title Case legacy input on write and normalize.
10. **`monitoring.watch_list` polymorphism**: both `List[string]` and `List[object]` remain valid in v1.1. Documented in the schema. Future v2 may narrow.
11. **Cross-repo distribution**: no shared PyPI package in v1. Dev uses PYTHONPATH (`analyst.py:58-65` pattern extended to new contracts); production uses gateway JSON.
12. **`assumption_id` carry-forward rule**: IDs are stable across Thesis edits that preserve the `driver` key (same driver, updated value → same `assumption_id`). IDs are stable across HandoffArtifact snapshot re-derivation (snapshot derives from Thesis; Thesis assumption IDs flow through). Delete + re-add with the same `driver` key produces a **new** `assumption_id` (lineage correctness — prior lineage entries still reference the old ID, which is now an orphan marker in `assumption_lineage`). `assumption_id` is assigned by the Thesis backend on first write; never by the agent or frontend.
13. **Shared-slice isomorphism is load-bearing**: any change to a shared-slice field requires updating both `Thesis` and `HandoffArtifact v1.1` schemas in the same PR (§6.6). Enforced by a schema boundary test.
14. **Source registry ownership**: `Thesis.sources[]` is canonical. HandoffArtifact `sources[]` is a verbatim copy; source IDs (`src_n`) persist across snapshots. The current behavior in `handoff.py:_SourceRegistry` (generating snapshot-local IDs) is superseded by v1.1 assembly, which reads from Thesis. Tracked in `HANDOFF_ARTIFACT_V1_1_PLAN.md`.
15. **Segment-mode driver resolution — three categories** (R6 corrected):

    Category assignment depends on whether the post-expansion item is `ItemType.input` (driver targets must be inputs per `driver_resolver._validate_mapping` at `driver_resolver.py:55`).

    - **Category A — post-expansion INPUT rows** (e.g., `revenue.segment_N.volume_growth`, `.price_growth` → expand to `business_segment_{n}_{role}` which remain `ItemType.input`): at MBC Phase 2, rewrite to `raw:tpl.a.revenue_drivers.business_segment_{n}_{role}` using `segment_profile_snapshot.segments[index]`. Deterministic because snapshot is authoritative (per §6.3).
    - **Category B — unsupported in segment mode**, two sub-cases:
      - B1. **Not rebuilt by expansion** (e.g., `revenue.segment_1.operating_metric` — `expand_segments()` does not emit an `operating_metric` row in canonical segments).
      - B2. **Rebuilt but not as input** (e.g., `revenue.segment_N.revenue` — `business_segment_{n}_revenue` is `ItemType.derived` per `sia_standard.json:1149`; driver validation rejects non-input targets). R5 incorrectly listed `.revenue` in Category A — corrected here.
      Both B1 and B2 → MBC Phase 2 rejects with typed `UnsupportedInSegmentMode(driver_key, reason)`. Analysts/agents must either drop the assumption or use a different driver.
    - **Category C — non-segment drivers** (`tax_rate`, `dso`, `capex_pct`, `debt_change`, etc.): unaffected by expansion. Static YAML validation (Phase 1) is sufficient; Phase 2 passes them through.

    The `driver_mapping.yaml` rework (emit segment-expansion-aware resolutions for Category A + explicit Category B flags) is tracked in `MODEL_BUILD_CONTEXT_PLAN.md` as a first-class task. Until rework lands, Category A keys MUST use `raw:` in segment mode; Category B keys are rejected.
16. **Stable IDs on list-shaped sections**: `assumption_id`, `risk_id`, `catalyst_id`, `trigger_id` (for `invalidation_triggers`), and `claim_id` (for `differentiated_view[]`) are all backend-assigned on first write. Stable across Thesis edits that preserve identity; delete + re-add produces a new ID (same rule as §10a.12 for `assumption_id`). `HandoffPatchOp` targets use these IDs, never array indices.

### 10b — Still-open questions (genuinely deferrable)

1. **Industry research sourcing for G5**: who populates `industry_analysis`? New dedicated tools vs. agent-synthesized from FMP peers + filings. Affects industry tools plan, not schema.
2. **ProcessTemplate storage**: versioned YAML only, SQLite-only, or both? Lean both (defaults as YAML, user overrides in SQLite). Decide in `PROCESS_TEMPLATE_PLAN.md`.
3. **Knowledge wiki schema (G6)**: shape of "actionable bite" + agent retrieval pattern. Out of scope here; follow-on plan.
4. **investment_tools outbound shape**: Pydantic import via PYTHONPATH vs. producing JSON. Both options are viable under §7; decide in `INVESTMENT_IDEA_INGRESS_PLAN.md` based on deployment model.

---

## 11. Out of Scope

Not decided by this document:

- Editorial pipeline for research reports (future project, clones `overview_editorial` pattern)
- Storage migrations (SQLite schema deltas — belongs in per-contract implementation plans)
- Tool surface changes (new MCP tools to populate industry research, manage templates — downstream of contracts)
- Portfolio sizing math (how `PriceTarget` → position size — portfolio engine work)
- LLM prompt templates / skill voice (prompt engineering, lives in skill files)
- Authentication/authz (inherits from existing gateway)

**What cannot be deferred** (explicitly moved from §11 to §10 per R1 feedback): contract identity, derivation direction, citation/patch grammar, scope keying. These are type-design, not implementation.

---

## 12. Follow-On Implementation Plans

Once this doc is approved, these implementation plans get written. **Order reflects actual dependencies** (fixed from R1):

| # | Plan | Closes | Dependencies |
|---|---|---|---|
| 1 | `THESIS_LIVING_ARTIFACT_PLAN.md` | G13 (schema side) | This doc |
| 2 | `HANDOFF_ARTIFACT_V1_1_PLAN.md` | G5, G9, G11, G13-snapshot, G14, G15 | Thesis contract |
| 3 | `MODEL_BUILD_CONTEXT_PLAN.md` | G2 | HandoffArtifact v1.1 |
| 4 | `INVESTMENT_IDEA_INGRESS_PLAN.md` | G1 | HandoffArtifact v1.1 |
| 5 | `PROCESS_TEMPLATE_PLAN.md` | G7, G12 | HandoffArtifact v1.1 |
| 6 | `MODEL_INSIGHTS_PRICE_TARGET_PLAN.md` | G3, G4 | ModelBuildContext |
| 7 | `INDUSTRY_RESEARCH_TOOLS_PLAN.md` | G5 (tools side) | HandoffArtifact v1.1 |
| 8 | `EDGAR_FMP_PRECEDENCE_PLAN.md` | G8 (request-time overrides) | ModelBuildContext |
| 9 | `KNOWLEDGE_WIKI_SCHEMA_PLAN.md` | G6 | ProcessTemplate |
| 10 | `RESEARCH_EDITORIAL_PIPELINE_PLAN.md` | G10 (rendering) | HandoffArtifact v1.1 |

**Parallel-shippable**: `THESIS_LIVING_ARTIFACT_PLAN` and the thesis-as-SSoT skill triad (per `AI-excel-addin/docs/design/thesis-as-source-of-truth-skill-architecture.md`). Skills can start with a constrained markdown template before the full typed contracts ship.

---

## 13. Skill integration reference

The contracts defined here are the **deterministic output targets** for the skill/methodology layer that lives in `AI-excel-addin`. Skills consume qualitative methodology units (the SIA-derived knowledge layer) and produce typed artifacts populating these contracts.

**Authoritative cross-layer map**: `/Users/henrychien/Documents/Jupyter/AI-excel-addin/docs/SKILL_CONTRACT_MAP.md`

That doc answers:
- Which typed contract sections does a given skill populate?
- Which methodology unit does a skill apply when running?
- Which SIA module does a methodology unit come from?
- What are the integration patterns for skill → contract output (direct field authoring, HandoffPatchOp proposals, ModelBuildContext construction, ThesisScorecard scoring)?
- What are the checklists for adding a new skill, methodology unit, or contract change?

**Separation of concerns**:
- This doc (`INVESTMENT_SCHEMA_UNIFICATION_PLAN.md`) is the **source of truth for contract shapes** — Pydantic types, field semantics, versioning, round-trip rules.
- `SKILL_CONTRACT_MAP.md` is the **source of truth for skill integration** — which skill writes which field, which methodology unit drives which skill, which SIA module covers which workflow phase.

When a contract field changes, every row in `SKILL_CONTRACT_MAP.md` that references the field must be updated in the same PR. When a skill changes its typed output, both docs must agree. Living alignment, not one-shot documentation.

---

## 14. Summary

One canonical **investment schema** lives in AI-excel-addin as Pydantic source of truth. It's composed of **six typed contracts, centered on the thesis**:

1. **InvestmentIdea** — typed ingress, superset of `IdeaPayload`, adds provenance (G1, G14)
2. **HandoffArtifact v1.1** — strictly additive evolution; differentiated view, industry research, lineage, shape consistency (G5, G9, G11, G13-partial, G14, G15)
3. **ModelBuildContext** — typed bridge leveraging `driver_mapping.yaml`; builds become deterministic (G2)
4. **ModelInsights + PriceTarget + HandoffPatchOp** — typed back-channel with typed patch grammar (G3, G4)
5. **ProcessTemplate** — configurable diligence, scoped to config (not schema-overriding) in v1 (G7, G12)
6. **Thesis + ThesisLink + ThesisScorecard** — centering living artifact, aligned with HandoffArtifact field names, keyed by `(user_id, ticker, label)`, multi-anchor resolution (G13)

**Architectural spine**: `Thesis` (living, THESIS.md) is the analyst-authored source of intent that every view challenges or adjusts. `HandoffArtifact` is the structured snapshot that programmatic consumers bind to. All other contracts plug into that spine.

**Editorial/voice** stays a pure render-layer concern (G10) — with the special case that `THESIS.md` is itself a rendering of `Thesis` (analyst-authored + skill-authored, round-trippable via constrained sections).

**Decision requested**: approve the six-contract design + per-contract versioning + decisions in §10a. Then `THESIS_LIVING_ARTIFACT_PLAN.md` and `HANDOFF_ARTIFACT_V1_1_PLAN.md` get written first (Thesis → Handoff v1.1 → the rest follows the dependency chain).
