# Skill → Artifact → Visual Matrix

**Status:** Audit v1 (2026-05-23). F150 deliverable.
**Purpose:** Operationalizes the "no bare artifacts" non-negotiable from `docs/standards/INVESTMENT_VISUAL_LAYER_PRINCIPLES.md` (§7) + the skill-artifact-visual coupling rule in `docs/reference/VISUALIZATION_STACK.md`. For every artifact-producing skill across both repos, classify the current chat-surface visual state and the recommended approach.
**Scope:** AI-excel-addin skills (`api/memory/workspace/notes/skills/*.md`) + risk_module overview-editorial generators (`core/overview_editorial/generators/*.py`).
**Authority layering:**
- `docs/standards/INVESTMENT_VISUAL_LAYER_PRINCIPLES.md` — **principles** (governs classification: when canonical vs scaffolding vs editorial-only)
- `docs/reference/VISUALIZATION_STACK.md` — **implementation reference** (defines the patterns this matrix classifies into)
- This doc — **inventory** (skill-by-skill audit)
**Source-of-truth references:** `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` (skill→contract map), `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts` (shipped overview canonical visuals), `AI-excel-addin/docs/design/demo-surface-spec.md` (shipped renderer router).

---

## The principle (recap)

> Every skill that emits a persistent artifact must have a paired visual on the chat surface — canonical (registry entry) for stable-shape outputs, scaffolding (HTML artifact) for variable-shape outputs. No bare artifacts. The visual is not a summary of the artifact; it's a first-class output of the skill. "Visual" includes tables, charts, metric strips, structured layouts — anything that's NOT bare prose or "file produced."

Full principle + spectrum at `docs/reference/VISUALIZATION_STACK.md` ("The skill-artifact-visual coupling rule").

---

## Column definitions

| Column | Meaning |
|---|---|
| **Skill** | Skill name (without `.md` suffix) or generator name |
| **Artifact produced** | What persistent output the skill emits — typed contract field(s), Excel file, etc. |
| **Current visual** | What the user sees on the chat surface today: `Canonical shipped` / `Markdown only` / `None visible` / `Side-table only` |
| **Recommended approach** | `Canonical` (registry entry) / `Scaffolding` (Pattern 2A HTML) / `Editorial` (markdown rendering, no structured artifact) / `None` (internal ops) / `Already shipped` |
| **Notes** | One-line reasoning + F-number ties |

---

## AI-excel-addin skills

### Already-shipped canonical renderers (3)

| Skill | Artifact produced | Current visual | Recommended | Notes |
|---|---|---|---|---|
| `earnings-scenarios` | `EarningsScenarios` typed payload + `Thesis.quantitative_framing.scenarios.*` | **Canonical shipped** | Already shipped | `scenario-tree` renderer; demo-surface v1 lineup. Reference example of canonical pattern. |
| `ir-composer` | `LpLetter` typed payload + `.docx` binary | **Canonical shipped** | Already shipped | `letter-download-button` renderer; demo-surface v1 lineup. |
| `critical-factors` + `quantifying-risk` + live positions (aggregate) | `MaterialityThreshold` + `DifferentiatedViewClaim[]` + `PortfolioFit` + portfolio response | **Canonical shipped** | Already shipped | `position-card` aggregate renderer — multi-source, not single-source. Reference for aggregate pattern. |

### Thesis lifecycle skills (4) — high-priority canonical candidates

| Skill | Artifact produced | Current visual | Recommended | Notes |
|---|---|---|---|---|
| `thesis-consultation` | Thesis sections: `thesis.*`, `differentiated_view`, `quantitative_framing`, `catalysts`, `risks`, `invalidation_triggers`, `position_metadata`, `business_overview` | None visible | **Canonical** — composite | Reference visual: thesis summary card with section headers + diff indicators (what was added/changed). High-frequency skill; visible chat-surface output is load-bearing. |
| `thesis-review` | `ThesisScorecard` + auditor `HandoffPatchOp[]` proposals | None visible | **Canonical** | Reference visual: scorecard table (claims × evidence × verdict) + proposed-ops list with diff. |
| `thesis-pre-mortem` | Risk register + proposed `invalidation_triggers` + `risks` | None visible | **Canonical** | Reference visual: risk register table + invalidation-trigger list with mechanism columns. |
| `thesis-articulation` | `Thesis.thesis`, `differentiated_view[]`, `catalysts[]`, pitch outline | None visible | **Canonical** | Reference visual: pitch card with thesis statement banner + 4-pillar table + dated catalyst timeline. |

### Analysis skills with typed Thesis output (~25) — canonical or aggregate candidates

| Skill | Artifact produced | Current visual | Recommended | Notes |
|---|---|---|---|---|
| `identifying-risk` | `Thesis.risks[]` (canonical types) + `Thesis.invalidation_triggers[]` + `Thesis.data_gaps[]` | None visible | **Canonical** | Risk register table (4 pillars) + invalidation-trigger rows. |
| `quantifying-risk` | `Thesis.position_metadata.portfolio_fit` (factor exposure / decomposition) + per-factor `Thesis.risks[]` | Partially canonical (consumed by `position-card` aggregate) | **Canonical extend** | Add standalone visual: factor table (β / R² / window) + idio decomposition pie + classification banner. |
| `competitive-position` | `Thesis.industry_analysis.{landscape, macro_overlay, structural_trends, editorial_peer_set}` (4 sections) | None visible | **Canonical** — composite | Reference visual: 4-pillar scorecard + 10-attribute pattern grid + section-by-section text panels. |
| `comparative-analysis` | `Thesis.industry_analysis.peer_comparison` (focal + 4-6 peers, KPI matrix) | None visible | **Canonical** | Reference visual: focal-vs-peers KPI matrix (table) + three-lens summary + verdict banner. |
| `peer-curation` | `Thesis.industry_analysis.editorial_peer_set` | None visible | **Canonical** | Reference visual: peer roster table (ticker, rationale tag, pillar score) + diff vs prior. |
| `comps-narrative` | `Thesis.industry_analysis.comps_narrative` (narrative + citations) | None visible | **Scaffolding** | Variable narrative shape; Pattern 2A HTML with citation chips. |
| `industry-onboarding` | Config files (`industry_kpis_<key>.yaml`, `operating_comps_<key>_v1.yaml`, fixture CSV, taxonomy patch) | None visible | **Canonical** — preview | Reference visual: config preview card + canonical-bucket table + diff against prior config. |
| `industry-landscape` | `Thesis.industry_analysis.landscape` | None visible | **Canonical** — composite cell | Sub-component of competitive-position composite. |
| `industry-macro-overlay` | `Thesis.industry_analysis.macro_overlay` (3-7 drivers with sensitivity) | None visible | **Canonical** — composite cell | Macro drivers table. Sub-component of competitive-position. |
| `structural-trends` | `Thesis.industry_analysis.structural_trends` (multi-year) | None visible | **Canonical** — composite cell | Structural-trends timeline / list. Sub-component of competitive-position. |
| `post-comps-landscape-refresh` | `Thesis.industry_analysis.landscape` (refresh only) | None visible | **Canonical** — reuse | Same renderer as `industry-landscape`; diff overlay. |
| `dcf-relative-valuation` | `PriceTarget` typed + `Thesis.valuation` updates | Side-table only (`price_target`) | **Canonical** | Reference visual: three-way valuation table (9 method-scenario cells) + triangulation spread + comp reality-check banner. F133 promotes `price_target` from side-table to Thesis field. |
| `forecast-assumptions` | `Thesis.assumptions[]` (with values + rationale + confidence + held_at_base) + workbook writes | None visible | **Canonical** | Reference visual: driver dictionary table + per-driver confidence/decay chart. |
| `valuation-inputs` | Workbook valuation-input cells (FMP price, beta, ERP, RFR, SOFR, credit spread) | None visible | **Canonical** — small | Reference visual: inputs strip (current/proposed/source). Live FRED refresh visible. |
| `fundamental-research` | `Thesis.sources[]` (4-8 SourceRecord) + `Thesis.data_gaps[]` + `Thesis.business_overview` (proposed section) | None visible | **Canonical** | Reference visual: 6-step worksheet output + sources panel + proposed-section diff. |
| `position-initiation` | Composite: `business_overview`, `qualitative_factors`, `risks`, `invalidation_triggers`, `materiality`, `differentiated_view`, `assumptions`, `monitoring.watch_list`, `catalysts`, `position_metadata` | None visible | **Canonical** — composite (large) | Reference visual: full diligence card across 5 sections. Likely the largest single canonical artifact. |
| `business-quality-assessment` | `Thesis.qualitative_factors[]` (category=business_quality) | None visible | **Canonical** | Reference visual: quality-factors table + per-pillar evidence rows. |
| `financial-red-flags` | `Thesis.qualitative_factors[]` (category=financial_red_flags) + `Thesis.risks[]` + `Thesis.invalidation_triggers[]` | None visible | **Canonical** | Reference visual: red-flag checklist with severity + paired-risk rows. |
| `business-model-construction` | `BusinessModel` typed contract | None visible | **Canonical** | Reference visual: business-model schema (drivers / segments / mappings) + compile preview. |
| `earnings-review` | Multiple Thesis updates (eps_fcf, assumptions, catalysts, consensus_view) + verdict block | None visible | **Canonical** | Reference visual: quarter scorecard + thesis-reconciliation diff + proposed-ops list. High-frequency skill. |
| `risk-review` | `Thesis.risks[]` + `invalidation_triggers[]` + `portfolio_fit` (per-ticker quantification) | None visible | **Canonical** | Reference visual: per-ticker fingerprint table + cluster identification + factor-stability indicator. |
| `allocation-review` | `Thesis.position_metadata.position_size` (per-ticker) | None visible | **Canonical** — small | Reference visual: sizing-decision strip (target / current / delta / rationale). |
| `scenario-analysis` | `Thesis.quantitative_framing.scenarios.{bull,base,bear}` + eps_fcf + assumptions | Partially canonical (overlaps earnings-scenarios shipped) | **Canonical** — reuse | Likely same renderer as `earnings-scenarios` (`scenario-tree`). Verify in F147 plan. |
| `model-vs-consensus` | `HandoffPatchOp.update_eps_fcf` + `update_consensus_view` + `Thesis.consensus_view` | None visible | **Canonical** | Reference visual: model-vs-consensus delta table + basis check banner. |
| `assumption-audit` | `ThesisScorecard` (assumption subset) + `update_assumption_field` ops | None visible | **Canonical** — partial | Reference visual: assumption audit table (assumption × confidence-change × evidence). Could reuse `thesis-review` scorecard component. |
| `guidance-extraction` | `Thesis.sources[]` adds + propagation to cited sections via `update_assumption_field` / `update_thesis_quantitative` | None visible | **Scaffolding** | Variable shape (depends on filing). Pattern 2A HTML — table of extracted guidance + source chips. |
| `filing-extractor` | `Thesis.sources[]` + section propagation | None visible | **Scaffolding** | Same as guidance-extraction; variable filing shape. |
| `decision-log` | `Thesis.decisions_log` entries | Markdown only (free-form) | **Canonical** — log view | Reference visual: decisions-log timeline with methodology-citation chips + applied-ops summary. |
| `monitoring-init` | `Thesis.monitoring.watch_list` initialization | None visible | **Canonical** — small | Reference visual: watchlist table (factor × trigger × threshold × evidence-source). |
| `ownership-refresh` | `Thesis.monitoring.watch_list` ownership-side updates | None visible | **Canonical** — small | Same renderer as `monitoring-init`; diff overlay. |
_(Note: 5 skills originally listed here as "needs investigation" were reclassified during the Tier-4 audit pass — see "Advisor analysis skills" section below. They produce standalone analyses, NOT Thesis contract writes.)_

### Model-build + valuation skills (3)

| Skill | Artifact produced | Current visual | Recommended | Notes |
|---|---|---|---|---|
| `build-model` | `FinancialModel` (.xlsx file) + `Thesis.model_insights[]` + `Thesis.price_target` (post-build) | Excel file link only | **Canonical** | Reference visual: model summary card (key drivers + sensitivity strip + executive summary + link to .xlsx). Explicit example the user gave when filing F150. |
| `model-update` | `FinancialModel` updates + `HandoffPatchOp` proposals | Excel file link only | **Canonical** — reuse | Same renderer family as `build-model`; diff overlay against prior version. |
| `filing-source-selection` | Filing source-pack PLAN (intent classifier + targeted reads) — consumed by downstream skills | None — internal routing | **None** | Confirmed Tier-4 audit: this is a planner/router skill that selects filing source packs for downstream analyst skills. Not an artifact producer itself. The downstream skill produces the user-visible artifact. |

### Advisor analysis skills (5) — `advisor-no-state`, no Thesis writes

**Structural finding from Tier-4 audit:** These 5 skills produce standalone analytical outputs but do NOT write to Thesis contracts (`state_class: advisor-no-state`, `persist_state: false`). They're decision-support analyses on demand, not Thesis-section updates. Each still needs a canonical visual under the coupling rule — the output is the artifact even without Thesis persistence. Suggests a namespace beyond `thesis.*` in the registry (e.g., `advisor.*`).

| Skill | Artifact produced | Current visual | Recommended | Notes |
|---|---|---|---|---|
| `acquisition-strategy-analysis` | Transaction table (closing date / target / consideration / category) + strategic-alignment synthesis | None visible | **Canonical** — `advisor.*` namespace | M&A activity table + category mapping overlay; strategic-pivot narrative panel. Filing-grounded; exact transaction facts preserved before interpretation. |
| `debt-sensitivity-analysis` | Sensitivity table (debt base × rate shock × pretax/after-tax impact); reconciliation of excluded debt categories | None visible | **Canonical** — `advisor.*` namespace | Leverage-sensitivity table with primary case + alternates + caveats (no-tax-shield, loss-widening signs). |
| `dilution-analysis` | Dilution waterfall (per tranche: convertibles / warrants / options / RSUs); exact + rounded share counts | None visible | **Canonical** — `advisor.*` namespace | Tranche table + waterfall + reconciliation to reported anti-dilutive table. Filing-grounded, exact-unit math. |
| `metric-trend-analysis` | Multi-period metric series (annual or quarterly) + YoY/CAGR deltas + inflection-point evidence | None visible | **Canonical** — `advisor.*` namespace | Period table + Recharts line chart. Highly visual — trend chart is the primary output. |
| `peer-comparison-analysis` | Metric-aware peer ranking with peer-lens classification (operating / valuation / capital_allocation) | None visible | **Canonical** — `advisor.*` namespace; renderer-overlaps with `comparative-analysis` | Peer ranking table. Same renderer family as `comparative-analysis` peer matrix but no Thesis write (ad hoc rather than thesis-scoped). |

### Investment-plan skills (2) — `state_class: producer`, persistent advisor plan

| Skill | Artifact produced | Current visual | Recommended | Notes |
|---|---|---|---|---|
| `plan-create` | `advisor/plans/investment-plan.md` — full investment plan (financial picture / risk tolerance / goals / target allocations / IPS) | Markdown only | **Canonical** — `plan.*` namespace | Investment plan summary card: financial health dashboard + risk profile + target allocation + goals. Composite card spanning multiple sections — large like `position-initiation`. |
| `plan-review` | Quarterly review against saved plan — delta table + corrective-action recommendations | Markdown only | **Canonical** — `plan.*` namespace; companion to `plan-create` | Plan-review delta card: prior vs current financial picture + portfolio state + goal progress + crossing-threshold flags. Same renderer family as `plan-create`; diff overlay. |

### Idea-sourcing skills (3) — InvestmentIdea producers

| Skill | Artifact produced | Current visual | Recommended | Notes |
|---|---|---|---|---|
| `fingerprint-research` | `InvestmentIdea` (typed, via `from_fingerprint_screen` connector) | None visible | **Canonical** | Reference visual: ranked-ticker table with fingerprint score columns. Same renderer family as other screener outputs. |
| `biotech-research` | `InvestmentIdea` (via `from_biotech_catalyst`) | None visible | **Canonical** — reuse | Ranked-ticker table with biotech-catalyst columns. |
| `special-situations-research` | `InvestmentIdea` (via `from_special_situations`) | None visible | **Canonical** — reuse | Ranked-ticker table with situation-type columns. |

### Editorial / portfolio skills (5) — markdown rendering, no structured artifact

| Skill | Artifact produced | Current visual | Recommended | Notes |
|---|---|---|---|---|
| `morning-briefing` | Markdown rendering across open Thesis files + portfolio | Markdown only | **Editorial → Scaffolding** | Today's free-form output could be tightened to Pattern 2A HTML with consistent layout (briefing template). Block D session-summary primitive may subsume. |
| `stock-pitch` | Markdown rendering (reads Thesis) | Markdown only | **Editorial → Scaffolding** | Pattern 2A HTML pitch template. Could later become a Pack template (F148) if standardized as a deliverable. |
| `performance-review` | Markdown rendering (portfolio-mcp data) | Markdown only | **Canonical** — overlap with overview generators | Verify whether content overlaps with `performance.py` overview generator (already canonical). If yes, may consolidate. |
| `macro-review` | Markdown notes + possible ProcessTemplate macro_overlay seed | Markdown only | **Scaffolding** | Variable macro shape; Pattern 2A HTML. |
| `hedging` | Trade-recommendation preview (no thesis-scoped contract write) | Markdown only | **Canonical** — small | Recommendation table (instrument × size × rationale × risk-reduction estimate). |

### Strategy-level skills (4) — scope unclear / planned + sizing action layer

| Skill | Artifact produced | Current visual | Recommended | Notes |
|---|---|---|---|---|
| `managing-risk` | Per-ticker position-sizing recommendation (target / starter / max sizes + Reason-1 / Reason-2 sell triggers) + decision-log entry. Updates `Thesis.position_metadata.position_size`. | None visible | **Canonical** — small/medium card | Confirmed Tier-4 audit: `advisor-with-decision-log`, `mode: recommend`, `persist_state: true`. Reads multiple prior artifacts (`identifying-risk`, `quantifying-risk`, `earnings-scenarios`, `dcf-relative-valuation`, `forecast-assumptions`, `critical-factors`). Reference visual: sizing-decision card (target / current / delta) + sell-trigger list + risk-limit-check banner. Tier 2. |
| `strategy-design` | May produce `ProcessTemplate` drafts (future) | None visible | **Canonical** — when scoped | Verify scope; if produces `ProcessTemplate`, reference visual is template diff view. |
| `strategy-executor` | Executes pre-approved strategies (no thesis-scoped contract write) | None visible | **None or scaffolding** | Execution surface, not analyst output. May need approval-event visual (Block C consumer). |
| `scenario-executor` | Same as `strategy-executor` (renamed) | None visible | **None or scaffolding** | Same as above. |

### Internal ops / no artifact (4)

| Skill | Artifact produced | Current visual | Recommended | Notes |
|---|---|---|---|---|
| `error-extraction` v3.0 | Internal ops (no contract output; surface unchanged with v3.0 discovery via `error_signals_collect`) | n/a | **None** | Not in investment workflow. |
| `oi-schedule-sync` | Internal ops | n/a | **None** | Annotations for `oi-schedule-sync` lane; not InvestmentIdea. |
| `tutor` | Interactive Socratic teaching dialogue (`interactive: true`, `agent_callable: false`) | Interactive chat surface | **None** | Confirmed Tier-4 audit: tutor mode wraps a methodology unit's Guide Mode. Output is dialogue history, not a persistent artifact. Not in artifact-producing scope. May benefit from a session-end summary card in a future tutor-mode polish pass — but not in v1 viz scope. |
| `thesis-link` (F3c planned) | `ThesisLink` entries connecting thesis points to model items | n/a (not built) | **Canonical** — when shipped | Reference visual: linkage table (thesis claim × model item × strength). Builds on existing `position-card` aggregate pattern. |

---

## risk_module overview editorial generators (9)

All sit behind `core/overview_editorial/generators/`. **Architectural finding from generator-audit pass 2026-05-23:** there are two distinct generator roles, not one. Five generators produce canonical `ArtifactDirective`s (all shipped via `OVERVIEW_ARTIFACT_REGISTRY`); four are *insight generators* that produce `InsightCandidate`s + `MarginAnnotation`s anchored to existing artifacts — they don't produce their own artifacts and don't need separate canonical renderers.

### Artifact-producing generators (5) — all shipped

| Generator | Artifact produced (`ArtifactDirective.artifact_id`) | Current visual | Notes |
|---|---|---|---|
| `concentration.py` | `overview.concentration` | **Canonical shipped** | Verified via `OVERVIEW_ARTIFACT_REGISTRY`. |
| `performance.py` | `overview.performance_attribution` | **Canonical shipped** | Generates `Performance` insights + the attribution artifact. |
| `tax_harvest.py` | `overview.tax_opportunity` | **Canonical shipped** | Registry entry. |
| `risk.py` | `overview.composition.asset_allocation` | **Canonical shipped** | Verified by grep — emits `ArtifactDirective(artifact_id="overview.composition.asset_allocation")` at line 150. Uses `useRiskAnalysis` hook. |
| `income.py` | `overview.income_projection` | **Canonical shipped** | F34 wiring fix in active OVERVIEW_INCOME_ARTIFACT_PLAN. |

### Insight-only generators (4) — anchor to existing artifacts; no separate canonical needed

| Generator | What it produces | Anchors to | Notes |
|---|---|---|---|
| `events.py` | `InsightCandidate[]` + `MarginAnnotation[]` (events calendar insights — earnings, dividends, splits with urgency tags) | (verify anchor target — likely overview decision or per-position artifacts) | 4 InsightCandidate/Margin instances. Not an `ArtifactDirective` producer. |
| `loss_screening.py` | `InsightCandidate[]` + `MarginAnnotation[]` (loss-harvesting candidates) | `artifact.overview.concentration` (verified anchor_id at line 121) | 3 instances. Surfaces loss-harvest candidates as anchored insights on the concentration artifact. |
| `trading.py` | `InsightCandidate[]` + `MarginAnnotation[]` (trading activity insights) | (verify anchor) | 8 instances — largest insight generator. Trading-activity narrative + recent-trade annotations. |
| `factor.py` | `InsightCandidate[]` + `MarginAnnotation[]` (factor exposure insights) | `artifact.overview.composition.asset_allocation` (verified anchor_id at line 213) | 7 instances. Factor exposure insights anchored to asset allocation. |

**No "missing editorial generators" — earlier matrix entry was wrong.** Insight generators don't produce canonical artifacts; their output flows into the shipped insight/margin panel that's anchored to the canonical artifact registry. Both surfaces (artifacts + insight panel) are shipped.

### Frontend-built artifacts (2) — RESOLVED 2026-05-23

`overview.composition.product_type` and `overview.decision` are **frontend-built**, not backend-generator-produced. Verified by grep — `overview.composition.product_type` builder lives at `frontend/packages/ui/src/components/dashboard/views/modern/overviewCompositionBrief.ts:390-391` (kind `'composition.product_type'`). Similar pattern for `overview.decision`.

**Architectural clarification:** The registry pattern supports BOTH paths:
- **Backend-generator path** — `core/overview_editorial/generators/*.py` emits `ArtifactDirective` → editorial pipeline → frontend renderer
- **Frontend-builder path** — frontend builder function in `overviewCompositionBrief.ts` (or similar) consumes hook data directly → `GeneratedArtifactProps` → registered renderer

Both paths land registry entries; the "unaccounted IDs" framing was based on a wrong assumption that all artifacts must come from backend generators. F147 plan should mention both producer paths explicitly.

---

## Summary statistics

Updated after Tier-4 audit pass 2026-05-23 (closed all 10 needs-investigation items).

| Category | Count |
|---|---|
| **Already shipped canonical (renderer in production)** | 3 skills + 7 generators = **10** |
| **Should be canonical (Pattern 1 / registry entry)** | ~33 thesis-namespace + 5 advisor-namespace + 2 plan-namespace + 1 review-namespace (performance-review) + 1 strategy + 1 idea = **~43** (editorial-generator audit removed the ~4 "missing generators" — they were insight generators, not artifact producers) |
| **Should be scaffolding (Pattern 2A HTML)** | ~6 skills |
| **Editorial / markdown-only (consider scaffolding)** | ~3 skills (morning-briefing, macro-review, stock-pitch) — may overlap with Pack composition (F148) |
| **None (internal ops / no artifact)** | 4 skills (`error-extraction`, `oi-schedule-sync`, `tutor`, `filing-source-selection`) |
| **Needs investigation** | 0 — Tier-4 audit complete |

**Visual coverage rate today: ~14% (10 of ~69 artifact-producing skills+generators have a shipped canonical visual on the chat surface).** The remaining ~86% are bare-artifact or markdown-only — exactly the gap the coupling rule is meant to close.

**Tier-4 audit findings (structural):**
1. **Multiple namespaces required.** The original viz stack doc sketched `thesis.*` only. The audit reveals at least 3 additional namespaces needed: `advisor.*` (5 advisor analysis skills with no Thesis writes), `plan.*` (2 investment-plan skills), plus potential `overview.*` extensions for missing generators. F147's hybrid per-namespace registry pattern handles this — but the v1 scope discussion should explicitly cover which namespaces ship first.
2. **`filing-source-selection` is a routing skill, not artifact-producing.** Correctly excluded from canonical scope.
3. **`tutor` is interactive, not artifact-producing.** Correctly excluded from v1 viz scope (could get a session-end summary card later but not load-bearing).
4. **`managing-risk` is the per-ticker action layer for sizing decisions.** Tier 2 canonical — sizing-decision card. Connects to `Thesis.position_metadata.position_size` and decision_log.
5. **Plan namespace is its own deliverable surface.** `plan-create` + `plan-review` produce a full advisor plan file — investment plan summary card + plan-review delta card. Distinct from thesis-scoped artifacts.

---

## The aggregate-renderer pattern (formalize in F147)

**Source:** `AI-excel-addin/docs/design/demo-surface-spec.md` §2.2 (shipped 2026-05-20). The `position-card` renderer is the reference example of the **aggregate-controller pattern** — a renderer that composes its view-model from multiple sources rather than one single-source artifact.

**Pattern shape:**

```
Aggregate-renderer-controller
  ├── subscribes to artifact_ready for skill A (current ticker / scope)
  ├── subscribes to artifact_ready for skill B (current ticker / scope)
  └── subscribes to live tool_execute_response for tool C

On any source update:
  rebuild view-model from latest available sources
  render with partial-source badges for any missing sources
  emit aggregate_ready event (separate event since aggregates have no persisted artifact_path)
```

**Behaviors:**
- **Partial-source rendering** — controller renders whenever any source has data; missing sources show "—" with a "Run X to populate" affordance.
- **Recomputation triggers** — any source's `artifact_ready` (or live tool refresh) rebuilds the view-model.
- **No on-disk persistence for aggregates** — view-model is computed on demand from source artifacts; the sources themselves persist.
- **`aggregate_ready` event** — controller emits this on every view-model rebuild; `sources_complete: true` indicates all expected sources have contributed.

**Shipped example — `position-card`:** Aggregates `critical-factors` (thesis-drift) + `quantifying-risk` (sizing-vs-cap) + live `get_positions` (current weight) into one PM-tab card.

**F147 implications — Tier 1/2 entries that need the aggregate pattern:**

| Entry | Sources aggregated | Notes |
|---|---|---|
| `thesis.review_card` (`thesis-review`) | `Thesis.materiality` + `Thesis.thesis.*` + `Thesis.differentiated_view` + `Thesis.assumptions` + `Thesis.risks` + `ThesisScorecard` | Composite scorecard view — multi-section read across Thesis. |
| `thesis.consultation_summary` (`thesis-consultation`) | Multiple `Thesis.*` sections written by the same skill run + read of existing sections | Largest aggregate — full thesis card across 8+ sections. |
| `thesis.position_card_full` (extends shipped position-card?) | critical-factors + quantifying-risk + live positions + assumptions + valuation | Extension of shipped position-card to surface more of the thesis state. |
| `plan.review_card` (`plan-review`) | Saved investment plan + current financial picture + portfolio state + goal progress | Diff overlay aggregate. |
| `plan.create_summary` (`plan-create`) | Financial picture + risk profile + target allocation + goals + IPS | Composite per-section card. |

**F147 plan should explicitly cover:**
1. The aggregate-renderer ID in `REGISTRIES` map (alongside single-source registries) — namespace-prefixed like everything else (e.g., `thesis.review_card`, `plan.review_card`)
2. The view-model derivation contract (which fields from which sources)
3. Partial-source rendering rules per aggregate entry (which sources gate render-vs-placeholder)
4. `aggregate_ready` event consumption on the Hank-web side

## Performance-review skill vs `performance.py` generator — RESOLVED

**Finding (2026-05-23 audit pass):** These are **complementary, not overlapping**. No consolidation needed.

| | `performance.py` (generator) | `performance-review` (skill) |
|---|---|---|
| Repo | risk_module | AI-excel-addin |
| Scope | Portfolio overview surface | Retrospective trade analysis |
| Output | `overview.performance_attribution` ArtifactDirective + Performance InsightCandidates | Trade scorecard + thesis-accuracy grading + pattern analysis + decision_log entry |
| Lens | Current portfolio performance state (display_return / sharpe / drawdown / attribution) | Closed-trade outcomes — what worked / what didn't / why; thesis-vs-outcome grading |
| Persistence | Shipped via OVERVIEW_ARTIFACT_REGISTRY | None currently visible (markdown only) |
| Recommended approach | Already shipped | **Canonical** — new namespace candidate |

**Implications:**
- Keep `performance.py` → `overview.performance_attribution` as the portfolio-overview current-state surface (shipped, unchanged).
- `performance-review` skill needs its own canonical visual — distinct artifact, distinct mental model. Suggest namespace `review.*` (or fold into `portfolio.*` if we expect more portfolio-level retrospective skills). Reference visual: trade scorecard table + thesis-accuracy grade column + pattern-callout side panel.
- F147 plan should treat these as separate registry entries, not consolidate.

## Implications for F147 scope

The "Canonical" rows above define the v1 `THESIS_ARTIFACT_REGISTRY` scope. Tentative grouping:

### Tier 1 — highest-frequency / brand-critical (ship first)
- `thesis-articulation` — pitch card
- `thesis-consultation` — thesis summary composite
- `position-initiation` — full diligence card (largest)
- `earnings-review` — quarter scorecard
- `critical-factors` standalone view (currently only consumed by position-card aggregate; standalone visual missing)
- `build-model` — model summary card

### Tier 2 — analysis-skill canonical visuals (ship next)

**Thesis-scoped (`thesis.*`):**
- `competitive-position` (composite 4-section)
- `comparative-analysis` (peer KPI matrix)
- `dcf-relative-valuation` (three-way valuation)
- `business-quality-assessment` (quality factors)
- `financial-red-flags` (red-flag checklist)
- `forecast-assumptions` (driver dictionary)
- `identifying-risk` (risk register)
- `quantifying-risk` standalone view
- `risk-review` (per-ticker fingerprint)
- `managing-risk` (sizing-decision card) — added 2026-05-23 from Tier-4 audit

**Advisor-namespace (`advisor.*`) — new namespace from Tier-4 audit:**
- `acquisition-strategy-analysis` (M&A activity table + category mapping)
- `debt-sensitivity-analysis` (leverage-sensitivity table)
- `dilution-analysis` (dilution waterfall)
- `metric-trend-analysis` (period table + Recharts line)
- `peer-comparison-analysis` (peer ranking — renderer-overlaps with `comparative-analysis`)

**Plan-namespace (`plan.*`) — new namespace from Tier-4 audit:**
- `plan-create` (investment plan summary card)
- `plan-review` (plan-review delta card)

### Tier 3 — sub-section / composite-cell renderers
- `industry-landscape`, `industry-macro-overlay`, `structural-trends`, `post-comps-landscape-refresh` — share renderer family with composite-cell pattern
- `peer-curation`, `monitoring-init`, `ownership-refresh`, `decision-log` — small canonical cards
- `thesis-link` (when shipped) — linkage table
- `performance-review` (new namespace `review.*` or `portfolio.*`) — trade scorecard card; see "Performance-review vs generator" section
- ~~Editorial generators not yet in registry~~ — **REMOVED 2026-05-23 generator audit**: events/loss_screening/trading/factor are insight generators that anchor to existing artifacts, not artifact producers. No new registry entries needed.

### Tier-4 audit closed 2026-05-23

All 10 needs-investigation items classified — 7 → Tier 2 canonical (5 advisor-namespace + 2 plan-namespace), 2 → None (`tutor`, `filing-source-selection`), 1 → Tier 2 canonical strategy (`managing-risk`).

**Updated scope assessment:** The original 5-thesis-ID sketch in the viz stack doc was way too narrow. Audit reveals ~46 canonical entries across at least 4 namespaces (`overview.*` extensions, `thesis.*`, `advisor.*`, `plan.*`). F147's `THESIS_ARTIFACT_REGISTRY` is bigger than originally planned — and the *registry pattern* needs to be multi-namespace from day one, not retrofit later.

**Recommended F147 v1 scope:**
- Build the hybrid per-namespace registry pattern with central `getArtifactDescriptor(id)` (already locked direction 2026-05-23)
- Ship Tier 1 (6 thesis canonicals) + Tier 2 thesis subset (~10 entries) = ~16 entries in v1
- Defer Tier 2 advisor + Tier 2 plan to v1.1 — same pattern, different namespace; trivial extension
- Tier 3 → v2

This gives Hank a meaningful canonical-visual coverage jump (~14% today → ~37% after F147 v1 thesis subset) without overscoping the first ship.

---

## Implications for Pattern 2A scope

The "Scaffolding" rows define candidate consumers of the HTML artifact pipeline:

- `comps-narrative` — variable narrative shape
- `guidance-extraction` / `filing-extractor` — variable filing shape
- `morning-briefing` — daily briefing format with consistent template
- `macro-review` — macro-research narrative
- `stock-pitch` — pitch document (also a Pack template candidate)

These benefit from Pattern 2A's pinned `styles.css` + sandboxed iframe so the agent can emit consistent-looking variable-content documents without per-output React work.

---

## Bare-artifact gaps (follow-up plan candidates)

The ~35 "Canonical, none visible" entries represent direct bare-artifact gaps. Each is a candidate for a per-skill follow-up plan — but the right move is to bundle them under F147 (Tier 1 + Tier 2 phased shipping), not file 35 separate plans.

**Suggested filing approach:**
- F147 plan doc lists Tier 1 + Tier 2 as v1 scope (~15 entries)
- Tier 3 + Tier 4 named in F147 as v1.1+ scope (deferred but committed)
- No separate per-skill plans — too granular

---

## Open follow-ups

1. ~~**Tier-4 investigation pass**~~ — **CLOSED 2026-05-23.** All 10 unclassified skills classified. Findings folded into Tier 2 (advisor + plan namespaces added), Internal ops, and Strategy-level sections. Multi-namespace registry implication captured in F147 scope recommendation.
2. ~~**Editorial-generator audit**~~ — **CLOSED 2026-05-23.** Generator architecture clarified: 5 produce canonical artifacts (all shipped), 4 are insight generators that anchor to existing artifacts (no separate canonical needed). Earlier "missing generators" entry removed. 2 unaccounted artifact IDs (`overview.composition.product_type`, `overview.decision`) remain — lower-priority producer-path trace.
3. ~~**Aggregate-renderer pattern documentation**~~ — **CLOSED 2026-05-23.** Pattern documented in "The aggregate-renderer pattern" section above. F147 plan should formalize 5 named aggregate entries (`thesis.review_card`, `thesis.consultation_summary`, `thesis.position_card_full`, `plan.review_card`, `plan.create_summary`) alongside single-source entries.
4. ~~**Overlap between editorial skills and editorial generators**~~ — **CLOSED 2026-05-23.** `performance-review` skill vs. `performance.py` generator are complementary (retrospective trade analysis vs. portfolio-overview current state). No consolidation; `performance-review` gets its own canonical entry in new `review.*` namespace.
5. ~~**Block D coupling**~~ — **CLOSED 2026-05-25.** Resolved via the aggregate-renderer pattern section: Block D and Tier 1 thesis-summary composite share the same `ArtifactComposition` primitive (an ordered set of artifact references with section grouping). Block D ships first as runtime-generated substrate; F147 aggregate entries (`thesis.review_card`, `thesis.consultation_summary`, etc.) use the same aggregate-controller architecture. F148 Packs layer templates on top. Sequence already locked in viz stack doc.
6. ~~**Multi-namespace v1 vs v1.1 sequencing**~~ — **DEFERRED to F147 plan-writing 2026-05-25.** Recommendation captured in matrix ("Implications for F147 scope"): thesis subset of Tier 2 in v1 (~16 entries); advisor + plan + review namespaces in v1.1. The F147 plan-writing step locks the final decision; this matrix's recommendation is the input.
7. ~~**Producer-path trace for `overview.composition.product_type` + `overview.decision`**~~ — **CLOSED 2026-05-25.** Both are frontend-built in `frontend/packages/ui/src/components/dashboard/views/modern/overviewCompositionBrief.ts`, not backend-generator-produced. The registry pattern supports both backend-generator and frontend-builder producer paths. F147 plan should document both paths.

**All matrix follow-ups closed or deferred to F147 plan-writing.** The matrix is in stable shape; next step is F147 plan authoring.

---

## References

- `docs/reference/VISUALIZATION_STACK.md` ("Skill-Artifact-Visual Coupling Rule" section)
- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` (skill → contract authoritative map)
- `frontend/packages/ui/src/components/dashboard/views/modern/artifacts/registry.ts` (shipped overview canonical visuals)
- `AI-excel-addin/docs/design/demo-surface-spec.md` (shipped renderer router — current 3 canonical paths)
- `docs/planning/THESIS_WRITE_SURFACE_COVERAGE.md` (structural template for this matrix; producer-side counterpart)
- `docs/planning/RESEARCH_ARTIFACT_LAYERS.md` (3-layer model providing context for what "artifact" means)

---

## Maintenance

This matrix is a snapshot. Update on:
- Every new skill added (classify on add — coupling rule says no bare artifacts)
- Every contract change that affects a skill's output shape
- Every renderer shipped (move row from "Canonical" recommended → "Canonical shipped" current)
- Quarterly audit pass (verify classification still holds)

When updating, also update the summary statistics block + the F147 tiering implications.
