# Plan #7 — Industry Research Tools (Investment Schema Unification)

**Status**: **SHIPPED 2026-04-28** — R7 PASS plan preserved for historical reference.
**Created**: 2026-04-27
**Revision**: R7 — addresses Codex R6 FAIL (1 blocker, 0 should-fix). Three lingering "engine validates" / "engine-side" / "from the engine" phrases at §5.B Decision #2 (lines 65, 74) and §5.D R3 rationale (line 320) rewritten to consistently point at the request-boundary validation path (FastAPI parses `batch: HandoffPatchBatch`; `_coerce_batch` for in-process callers). R6 was substantively sound; R7 is the final pass on residual phrasing.
**Revision history**:
- R6 — addresses Codex R5 FAIL (2 blockers + 2 should-fix, editorial): §7 graph fixed to match prose; §5.B / §5.E "engine validation" wording rewritten to request-boundary; `cross-repo Pydantic import` removed from §4 / §5.B live text; §4 item #9 test count synced to §6 (43+5=48). R6 had three residual "engine validates" phrases at §5.B/§5.D — fixed in R7.
- R5 — addresses Codex R4 FAIL (2 blockers + 3 should-fix): §7 dep text fixed (D no longer depends on A); §5.B validation flow rewritten (FastAPI parses before engine); removed `format="full"` reference; removed `peer_tickers: list[str]` from live text; rewrote `IndustryAnalysisSectionTarget` reference. R5 introduced graph/prose mismatch + lingering "engine validation" wording — fixed in R6.
- R4 — addresses Codex R3 FAIL (4 blockers + 4 should-fix): scrub cross-repo Pydantic-import contradictions; `name=ticker` fallback (compare_peers summary lacks company names); handle FMP `{status: error}` return path; collapse `IndustryAnalysisSectionTarget` to `target: None`; document FastAPI 422 vs engine validation; add drift-prevention comment beside `SectionKey`; clarify MCP error-surfacing.
- R3 — addresses Codex R2 FAIL (5 blockers + 4 should-fix): explicit dual-edit of `_shared_slice.py` + `process_template.py` (Literal does NOT auto-propagate from tuple); add `SECTION_TITLES["industry_analysis"]`; drop invented `metrics` kwarg; drop cross-repo Pydantic import; restructure typed errors to single class. Plus: corrected `fmp.tools.peers` path; strict `time_horizon` canonicalizer; E2E count corrected to 5; §5.E reworded.
- R2 — addresses Codex R1 FAIL (5 blockers + 5 should-fix): real `process_template.section_config.required`; whole-Thesis CAS model corrected; `relative_position` dropped from v1; `register_source` / `UnknownSourceCitationError` removed (handoff normalization is the safety net); Decision #2 reversed (risk_module owns tool, originally proposed FMP signature `peer_tickers: list[str]` was wrong; shipped is `peers: str | None`). Plus: real FMP key names; route-level E2E; canonicalizer.
- R1 — initial draft. by (1) using shipped `process_template.section_config.required` + adding `industry_analysis` to `DILIGENCE_SECTION_KEYS`, (2) correcting whole-Thesis CAS model (engine retries are built-in; ops apply sequentially in orchestration), (3) dropping `relative_position` from Plan #7 entirely (deferred to v2 with explicit re-evaluation trigger), (4) dropping invented `register_source` / `UnknownSourceCitationError` (citation safety lives at handoff-derivation time per `handoff.py:304`), (5) reversing Decision #2 — tool lives in risk_module where FMP plumbing is, imports `IndustryPeerComparison` Pydantic from AI-excel-addin schema. Plus: real FMP key names from `DEFAULT_PEER_METRICS`, route-level E2E test, `time_horizon` canonicalizer, real classifier path. R1 change log preserved inline below.
**Closes**: G5 (tools side) per master plan §5
**Authoritative design reference**: `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` §6.2 (`industry_analysis` field on `HandoffArtifact v1.1`), §6.6 (shared-slice on `Thesis`), §10b.1 (open question — answered here), §12 row 7

---

## 1. Purpose

Populate the `Thesis.industry_analysis` shared-slice contract — already shipped in `AI-excel-addin/schema/thesis_shared_slice.py:306-348` and rendered by `frontend/.../HandoffSectionRenderer.tsx:420` — with **typed deterministic outputs** for peer comparison and **skill-synthesized narrative** for landscape, macro overlay, and structural trends.

**Schema is shipped.** This plan is **tools-only**: new MCP tools, new skills, new patch ops, orchestrator wiring. No new Pydantic types, no new write surface, no new renderer.

---

## 2. Audit findings (carried from session 2026-04-27)

The session's two-pass codebase audit established that all five "downstream" surfaces are already in place:

| Surface | Status | Location |
|---|---|---|
| `Thesis.industry_analysis` Pydantic | ✅ shipped | `AI-excel-addin/schema/thesis_shared_slice.py:306-348` |
| `HandoffArtifactV1_1.industry_analysis` | ✅ shipped | `AI-excel-addin/schema/handoff.py:136`; `_SHARED_SLICE_FIELDS` includes it |
| Thesis → Handoff verbatim derivation | ✅ shipped | `AI-excel-addin/api/research/handoff.py:387` |
| `thesis_update_section` write tool | ✅ shipped | `risk_module/mcp_tools/thesis.py:76` |
| `renderIndustryAnalysis` frontend | ✅ shipped | `risk_module/frontend/packages/ui/src/components/research/HandoffSectionRenderer.tsx:420,1053` |

**Identified gap**: `HandoffPatchOp` union (`AI-excel-addin/schema/handoff_patch.py:305-330`) has no industry_analysis ops. Multiple skills will write to `industry_analysis` concurrently — without typed patch ops, each must read-merge-write the entire section. This plan closes that gap (Decision #1 below).

---

## 3. Locked design decisions

Four decisions taken in design session 2026-04-27 (transcript: `schema-industry-research`):

### Decision #1 — Patch grammar
**Add four `IndustryAnalysisPatchOp` ops** to `HandoffPatchOp` union, plugged into the existing OCC engine (Plan #6 pattern at `api/research/patch_engine.py`).

| Op | Semantics |
|---|---|
| `update_industry_landscape` | replace `industry_analysis.landscape` (single-object slot) |
| `replace_industry_peer_comparison` | replace `industry_analysis.peer_comparison` wholesale (deterministic tool emits full peers list) |
| `update_macro_overlay` | replace `industry_analysis.macro_overlay` (skill regenerates entire drivers list) |
| `replace_structural_trends` | replace `industry_analysis.structural_trends` array wholesale |

**Scope cut from B-full → B-scoped-down**: no per-trend `add_structural_trend` / `remove_structural_trend` / `update_structural_trend` ops. Skills regenerate the whole array each run. **No `trend_id` schema bump required** — that field would only be load-bearing if per-trend ops existed.

**Why replace-only semantics**: each section is the output of a single skill or tool run. Per-element editing is not the workflow; full-section regeneration is. Matches `replace_assumption_value` pattern (singular) more than the `add_risk` / `update_risk` / `remove_risk` triplet.

### Decision #2 — Deterministic peer comp tool ownership (REVERSED in R2)

**R2 reversal**: tool lives in **risk_module** (not AI-excel-addin). R1 argued AI-excel-addin owns Pydantic SoT therefore the tool belongs there. Codex R1 SHOULD-FIX correctly noted: SoT-of-types ≠ SoT-of-data-fetching. The FMP integration lives in `risk_module/fmp/tools/peers.py:329` (`compare_peers(symbol, peers, limit, format)`). Putting a thin AI-excel-addin wrapper around that creates a useless cross-repo hop.

**New tool location**: `risk_module/mcp_tools/industry.py` (NEW)
- Wraps existing `fmp.tools.peers.compare_peers` directly — no gateway round-trip (in-repo import; matches shipped pattern at `fmp/server.py:39`)
- **R3 + R4: returns plain `dict`, NOT a Pydantic object.** Verified by Codex R2 that `mcp_tools/thesis.py` does not import AI-excel-addin types; this plan follows the same pattern. Type validation happens at the request boundary (FastAPI parses `batch: HandoffPatchBatch` in `routes.py:964`) when the caller posts a `replace_industry_peer_comparison` op; for in-process callers, `_coerce_batch` performs the same validation. Either path: malformed dict produces a typed Pydantic ValidationError BEFORE `apply_patch_ops_engine` runs.
- Reuses existing `DEFAULT_PEER_METRICS` constant from `fmp/tools/peers.py:45-70` for the metric set — **does NOT redefine metric names**. Real FMP keys: `grossProfitMarginTTM`, `operatingProfitMarginTTM`, `returnOnInvestedCapitalTTM`, `_computed_fcf_margin`, etc.
- Output dict shape matches `IndustryPeerComparison` field layout: `{"peers": [{"ticker": ..., "name": ..., "key_metrics": {...}, "relative_position": null, "source_refs": []}]}`
- Tool does NOT populate `relative_position` — see Decision #4 (dropped from v1)
- Tool does NOT call `thesis_update_section` or `apply_patch_ops` directly; returns the dict. Caller wraps it in a `replace_industry_peer_comparison` op and routes through the existing AI-excel-addin patch-ops endpoint (`/api/research/files/{id}/patch-ops/apply`, `routes.py:964`).

**Why risk_module owns the tool**:
- FMP plumbing already lives there
- No AI-excel-addin gateway HTTP route needed (one less moving part)
- Pydantic types still SoT in AI-excel-addin — but enforced at the request boundary (FastAPI / `_coerce_batch`), not at tool emission. Tool produces data; the patch-ops endpoint validates contract before the engine runs.
- Symmetry with existing FMP MCP tools (`mcp_tools/research.py`, `tests/mcp_tools/test_peers.py`)

**R1 trade-off**: this means the deterministic tool sits in risk_module's MCP surface directly — no risk_module-mirror, no gateway client step. The "Plan #6 MCP-mirror pattern" only applies when the tool lives in AI-excel-addin (e.g., the patch-ops apply route). Industry peer comp doesn't need that pattern.

### Decision #3 — Skill registration
**Three new skills, no retrofits.** Existing `macro-review.md` is portfolio-scope (regime check across whole book), not per-thesis-ticker — different artifact, don't retrofit.

| New skill | Writes to (via patch op) | Consumes |
|---|---|---|
| `industry-landscape` | `landscape` (`update_industry_landscape`) | `mcp__edgar-financials__get_filing_sections` (Item 1, Item 1A); `mcp__fmp-mcp__get_earnings_transcript` |
| `industry-macro-overlay` | `macro_overlay` (`update_macro_overlay`) | `mcp__fmp-mcp__get_economic_data`, `get_sector_overview`, `get_market_context` |
| `structural-trends` | `structural_trends` (`replace_structural_trends`) | `get_earnings_transcript` (multi-period), EDGAR Item 1A across years |

**Naming**: `industry-macro-overlay` (not `macro-overlay`) to avoid registry collision with the existing portfolio-scope `macro-review` skill. Both coexist.

**Orchestration hook**: `position-initiation.md` (existing single-ticker diligence orchestrator) gets a workflow step adding the four runs (deterministic peer comp + three narrative skills) when initiating a position.

### Decision #4 — Field taxonomy (TIGHTENED in R2 for `time_horizon`; `relative_position` DROPPED entirely)

**R2 changes vs R1**:
- **`relative_position` is dropped from Plan #7 entirely** (closes Codex R1 blocker #3 — race between deterministic peer comp tool and skill writing peer position via full replace). Tool leaves it `None`; skill does NOT touch peer_comparison. v2 plan adds `update_peer_relative_position` granular op when there's a real workflow that needs it. **Re-evaluation trigger**: when `industry-landscape` skill outputs reliably contain leader/laggard judgments AND a downstream consumer (e.g., portfolio risk overlay) needs the field. Both conditions must hold.
- **`time_horizon` ships with a strict canonicalizer** (closes Codex R1 SHOULD-FIX, R2 inconsistency, R3 final): `canonicalize_time_horizon()` (strict — raises on unknowns) + `canonicalize_optional_time_horizon()` (None-passthrough wrapper) in `AI-excel-addin/schema/enum_canonicalizers.py`. Mirrors the shipped pattern at `enum_canonicalizers.py:90` (`canonicalize_optional_timeframe` → strict `canonicalize_timeframe`). Accepts variations (`"3-5 years"`, `"long term"`, `"long-term"`, `"long_term"`, etc., with case + separator normalization); normalizes to one of `{near-term, medium-term, long-term}`. Unknown variants raise `ValueError` at field validation time. Applied via `field_validator("time_horizon", mode="before")` on `StructuralTrend`. Schema type stays `str | None`.
- **`sensitivity` stays free-form** — directional + magnitude ("EPS down ~3% per 100bp 10Y move") is too varied to canonicalize today; the prompt-level convention ("positive/negative/mixed first, then quantification") is the v1 contract. Re-evaluation trigger: 5+ distinct phrasings appear in real outputs.

**Why time_horizon ships canonicalizer NOW** (per "don't defer to dodge friction"): convention `{near-term, medium-term, long-term}` is already standard in equity research and across `macro-review.md` / earnings-review skills. There's no signal to "wait for" — the answer is known. Canonicalizer is small (one function + test), zero schema risk (additive validator on optional str field).

**Why `relative_position` is dropped** (also per "don't defer to dodge friction"): we explicitly don't have a workflow that consumes it yet. The "wait for usage pressure" rationale is forbidden — but here, the deferral is paired with a concrete re-evaluation trigger AND the architectural problem (deterministic-vs-skill replace race) has no clean v1 fix without granular per-peer ops. v1 ships without it; v2 adds it when the consumer exists.

**Why `sensitivity` stays free-form**: we'd need to see real macro-overlay skill outputs to know what taxonomy fits.

The deterministic peer comp tool writes raw numbers into `key_metrics: dict[str, ScalarValue]` and leaves `relative_position` as `None`. Skills write structurally clean Pydantic objects via patch ops; canonicalizer enforces `time_horizon` shape; `sensitivity` is prompted but not enforced.

---

## 4. Scope (mirrors §5 sub-phases)

In scope:
1. **4 new patch ops** in `AI-excel-addin/schema/handoff_patch.py` + handlers in `AI-excel-addin/api/research/patch_engine.py` (engine retry/CAS already shipped for whole-Thesis path; new ops plug into the existing fold logic)
2. **1 additive enum bump**: add `industry_analysis` to `DILIGENCE_SECTION_KEYS` in `AI-excel-addin/schema/_shared_slice.py:24` so `SectionKey` Literal in `schema/process_template.py:21` includes it (closes Codex R1 blocker #1 — `SectionConfig.required: list[SectionKey]` becomes the orchestration gate per §5.E)
3. **1 new deterministic tool** `industry_peer_comparison` in `risk_module/mcp_tools/industry.py` (NEW; returns plain dict — no Pydantic types imported from AI-excel-addin; type validation happens at the request boundary when the caller posts a `replace_industry_peer_comparison` op)
4. **1 canonicalizer** `canonicalize_time_horizon` in `AI-excel-addin/schema/enum_canonicalizers.py` + `StructuralTrend.time_horizon` validator
5. **3 new skill markdown files** in `AI-excel-addin/api/memory/workspace/notes/skills/`
6. **1 orchestration hook** in `position-initiation.md` (sequential ops, NOT batched — see §5.E)
7. **Typed error wiring**: 1 new error class in `risk_module/actions/errors.py` (`IndustryToolUpstreamError(ActionInfrastructureError)`). NO `_THESIS_ERROR_TYPES` classifier entry — the error is raised directly by the risk_module tool (sub-phase B) and surfaced by the MCP server layer; it doesn't flow through the gateway response classifier. Generic `PatchStaleRetryExhaustedError` is already in `_THESIS_ERROR_TYPES` from Plan #6 — no new mapping needed for industry ops.
8. **`SKILL_CONTRACT_MAP.md`** update with three new skill rows + one new tool row
9. **Test coverage** target: ~43 unit tests + 5 route-level E2E (~48 total per §6 detailed breakdown). Closes Codex R1 SHOULD-FIX on E2E gap.

Out of scope (explicit, per "don't defer to dodge friction" — each cut has an explicit re-evaluation trigger):
- **`relative_position` field population** — DROPPED for v1 per Decision #4 R2. Tool leaves it None; skill doesn't touch it. **Re-evaluation trigger**: when (a) `industry-landscape` outputs reliably contain leader/laggard judgments AND (b) a downstream consumer needs the field. Both must hold. v2 plan adds `update_peer_relative_position` granular op.
- **`sensitivity` enum tightening** — free-form for v1. **Re-evaluation trigger**: 5+ distinct phrasings appear in real macro-overlay outputs.
- **Per-trend granular ops** (`add_structural_trend` / `update_structural_trend` / `remove_structural_trend`) — Decision #1 scope cut. Workflow is full regeneration. **Re-evaluation trigger**: when a skill needs to incrementally edit a single trend without regenerating the array (e.g., user-driven manual edit flow).
- **Source-registration tool / `register_source` MCP surface** — DROPPED in R2 (closes Codex R1 blocker #4). Skills consume `Thesis.sources[]` read-only; if a needed source is unregistered, skill cites without `source_refs` (free narrative). Existing handoff normalization at `AI-excel-addin/api/research/handoff.py:304` already raises if `source_refs` don't resolve at handoff-derivation time — that's the safety net. **Re-evaluation trigger**: when more than one v1 skill (industry or otherwise) needs to add new sources mid-workflow.
- **New data providers** (reuse existing FMP + EDGAR + portfolio-mcp only; hard line)
- **Frontend renderer changes** — `renderIndustryAnalysis` already handles all four sections per audit (`HandoffSectionRenderer.tsx:420-565`)
- **`IdeaProvenance` lineage from idea → industry insight** — Plan #4 territory
- **Cross-thesis industry rollups** — portfolio-mcp aggregation feature, not Thesis.industry_analysis

---

## 5. Sub-phases

Order reflects dependency. Each sub-phase ships behind one Codex implementation pass.

### Sub-phase A — Patch op classes + engine integration + SectionKey bump + canonicalizer

**Owner repo**: AI-excel-addin
**Files** (R3: explicit dual-edit + DiligenceService update — closes Codex R2 blockers #1, #2):
- `AI-excel-addin/schema/_shared_slice.py:24` — add `"industry_analysis"` to `DILIGENCE_SECTION_KEYS` tuple
- `AI-excel-addin/schema/process_template.py:21` — **also** add `"industry_analysis"` to the hard-coded `SectionKey = Literal[...]`. The Literal does NOT auto-rebuild from the tuple at module-load; the existing test at `tests/schema/test_process_template.py:312` asserts the two stay equal, so both must be edited together. **R4: also add a one-line comment** above the `SectionKey` definition: `# Must match _shared_slice.DILIGENCE_SECTION_KEYS — parity enforced by tests/schema/test_process_template.py:312`. Cheap drift prevention per Codex R3 SHOULD-FIX.
- `AI-excel-addin/api/research/diligence_service.py:20` — add `"industry_analysis": "Industry Analysis"` (or whatever title fits the existing pattern; verify other entries) to the `SECTION_TITLES` dict. Required because `DiligenceService.list_sections` indexes `SECTION_TITLES[section_key]` at line 98 — without the entry, KeyError on iteration.
- `AI-excel-addin/schema/handoff_patch.py` — add 4 op classes + add to discriminated union
- `AI-excel-addin/schema/enum_canonicalizers.py` — add `canonicalize_time_horizon` (strict, raises on unknowns) + `canonicalize_optional_time_horizon` (None-passthrough wrapper). Mirrors the shipped pattern at `enum_canonicalizers.py:90` (`canonicalize_optional_timeframe` → strict `canonicalize_timeframe`).
- `AI-excel-addin/schema/thesis_shared_slice.py:344` — add `field_validator("time_horizon", mode="before")` on `StructuralTrend` calling `canonicalize_optional_time_horizon`. Type stays `str | None`. Unknown variants raise `ValueError` at validation time (matches shipped pattern; closes Codex R2 SHOULD-FIX inconsistency).
- `AI-excel-addin/api/research/patch_engine.py` — add op handlers (4 new branches in `_dry_fold_detailed`)
- `AI-excel-addin/tests/test_handoff_patch.py` — schema validation tests
- `AI-excel-addin/tests/integration/test_plan_7_e2e.py` (NEW) — engine + route-level E2E (covered in §6 test count)
- `AI-excel-addin/tests/test_enum_canonicalizers.py` — extend with `time_horizon` cases (positive: variants normalize; negative: unknown raises)
- `AI-excel-addin/tests/schema/test_process_template.py` — extend with `industry_analysis` in `section_config.required` validation; existing parity test at line 312 picks up the dual-edit automatically
- `AI-excel-addin/tests/api/research/test_diligence_service.py` (or existing) — add test asserting `SECTION_TITLES["industry_analysis"]` exists and `list_sections` doesn't KeyError when industry_analysis is required

**Op classes** (R4: `target: None = None` per Codex R3 SHOULD-FIX — op name is the discriminator; no need for a section-target type since each op maps to exactly one slot. Matches shipped pattern for single-slot ops like `update_consensus_view` at `handoff_patch.py:227`):

```python
class UpdateIndustryLandscapeOp(_PatchOpBase):
    op: Literal["update_industry_landscape"] = "update_industry_landscape"
    target: None = None
    value: IndustryLandscape

class ReplaceIndustryPeerComparisonOp(_PatchOpBase):
    op: Literal["replace_industry_peer_comparison"] = "replace_industry_peer_comparison"
    target: None = None
    value: IndustryPeerComparison

class UpdateMacroOverlayOp(_PatchOpBase):
    op: Literal["update_macro_overlay"] = "update_macro_overlay"
    target: None = None
    value: MacroOverlay

class ReplaceStructuralTrendsOp(_PatchOpBase):
    op: Literal["replace_structural_trends"] = "replace_structural_trends"
    target: None = None
    value: list[StructuralTrend]
```

R4 simplification (vs the section-target shape considered in R2/R3 — see revision history): no validator needed because there's no section field that could be wrong; the op name uniquely identifies the destination. Smaller surface, fewer test cases, matches shipped pattern (`UpdateConsensusViewOp` at `handoff_patch.py:227` uses the same `target: None = None` shape).

**Engine integration (R2 correction)**: the patch engine does **whole-Thesis CAS** (`patch_engine.py:120,155,183` — `apply_patch_ops` loads full Thesis, folds whole batch, CAS-writes via `update_thesis_artifact_if_version_matches`, retries up to `max_retries=3` with backoff). There is **NO section-level CAS**. Same-section concurrent writes are last-writer-wins after retry exhaustion. The four new op handlers are pure fold-functions: `_dry_fold_detailed` reads current `industry_analysis`, applies the op, returns folded Thesis. The engine handles versioning. R2 correction: R1's "CAS only re-fires the conflicting section" claim was incorrect; deleted from §10.

**Concurrency semantics**: in single-user single-session context (today's reality), CAS conflicts are rare. The 3-retry default absorbs them. Cross-session concurrent writes to the same `industry_analysis` slice will last-writer-wins after retries; that's acceptable for v1 since (a) skills regenerate the whole section so partial loss is bounded and (b) the orchestration in §5.E applies ops sequentially per the FAQ pattern below.

**Tests** (~15):
- 4 ops × 2 tests each = 8 schema-validation tests (positive + value-shape mismatch negative)
- 4 ops × 1 test each = 4 patch-engine `_dry_fold` tests (verify fold mutates the right section, leaves others untouched)
- 3 engine tests: full apply round-trip via `apply_patch_ops`; retry on `PatchStaleError` (mock version mismatch); `PatchStaleRetryExhaustedError` after max_retries

**Citations**: removed from R1's plan (closes Codex R1 blocker #4). Existing handoff normalization at `AI-excel-addin/api/research/handoff.py:304` raises if `source_refs do not resolve against sources[]` — the safety net is at handoff-derivation time, not patch-op apply. Patch ops accept whatever `source_refs` the caller provides; handoff normalization rejects dangling refs when the snapshot is built. Skills are responsible for citing only `Thesis.sources[]` IDs that already exist (read `Thesis.sources` first). v2 plan adds an `add_source` patch op if needed.

---

### Sub-phase B — Deterministic `industry_peer_comparison` tool (R2: risk_module-owned)

**Owner repo**: risk_module (R2 reversal — see Decision #2)
**Files**:
- `risk_module/mcp_tools/industry.py` (NEW) — MCP tool function + Pydantic-emitting helper
- `risk_module/mcp_server.py` — register tool via `@mcp.tool()` decorator (existing pattern at `mcp_server.py:218-228, 379+`)
- `risk_module/tests/mcp_tools/test_industry_peer_comparison.py` (NEW)
- `risk_module/tests/mcp_tools/fixtures/industry_peer_comparison_msft.json` (NEW — golden fixture)

**No new files in AI-excel-addin** for this sub-phase. Pydantic types `IndustryPeerComparison`, `IndustryPeerComparisonPeer` already shipped at `schema/thesis_shared_slice.py:312-323`.

**Tool signature** (R3: matches shipped `compare_peers` signature from `fmp/tools/peers.py:329` exactly — closes Codex R2 blocker #3):
```python
def industry_peer_comparison(
    symbol: str,
    peers: str | None = None,        # comma-separated; passed through to fmp.compare_peers
    limit: int = 5,                   # passed through to fmp.compare_peers
) -> dict: ...                        # NOT typed Pydantic — see "Cross-repo type concern" below
```

R3 changes vs R2:
- Drop invented `metrics: list[str]` kwarg. Shipped `compare_peers(symbol, peers, limit, format)` has no `metrics` param. Summary mode uses `DEFAULT_PEER_METRICS` internally (`peers.py:467`). v1 tool always uses summary mode — no metric override surface. v2 plan can revisit metric customization through the alternate format mode if needed.
- Rename first param `ticker` → `symbol` to match shipped signature.
- Pass-through `limit` since shipped tool exposes it.

**Type contract location**: tool returns a plain dict (matches `fmp.compare_peers` summary output shape, just normalized to the `IndustryPeerComparison` field layout). The risk_module tool does NOT import the `IndustryPeerComparison` Pydantic class from AI-excel-addin. Reason: `mcp_tools/thesis.py` already operates this way — it delegates through `actions.thesis` and only imports local errors, never AI-excel-addin types. This plan follows the established pattern; it does not invent a new import bridge.

Type validation happens at the request boundary, not the engine (R4 correction per Codex R4 blocker #2): when the caller posts a `replace_industry_peer_comparison` op to `/api/research/files/{id}/patch-ops/apply`, FastAPI parses the body via the `batch: HandoffPatchBatch` annotation in the route handler at `AI-excel-addin/api/research/routes.py:964`. Pydantic validates the discriminated-union `value: IndustryPeerComparison` BEFORE `apply_patch_ops_engine` runs. If the dict shape is wrong, the route returns 422 with structured detail; `services/research_gateway.py:270` maps non-dict 422 detail to a generic `ActionValidationError`. For in-process engine calls (e.g., direct Python from a test or orchestrator), `_coerce_batch` performs the same validation. Either path: caller sees a typed validation failure with field-level detail. AI-excel-addin still owns the type contract; the contract is enforced at whichever entry point reaches the patch engine.

**Behavior**:
- If `peers` is None, shipped FMP `compare_peers` derives the peer set internally (its existing default)
- Calls `fmp.tools.peers.compare_peers(symbol, peers=peers, limit=limit, format="summary")` — direct in-repo import, no MCP round-trip. Import path is `fmp.tools.peers` (NOT `risk_module.fmp.tools.peers`; matches shipped imports at `fmp/server.py:39`, `mcp_tools/__init__.py:61`).
- **R4: handle both FMP failure modes.** Shipped `compare_peers` catches exceptions internally and returns `{"status": "error", "error": "..."}` rather than raising. Tool MUST check `result.get("status") != "success"` and re-raise as `IndustryToolUpstreamError`. Tool MUST also wrap any unhandled exception from the call in `IndustryToolUpstreamError`. Both paths produce the same typed error to callers.
- **R4: `name` field source** (closes Codex R3 blocker #2). Shipped `compare_peers` summary output (`subject`, `peers`, `comparison`, `failed_tickers`) does NOT expose company names from the internal profile fetch. v1 fallback: `name = ticker` for every peer (deterministic, never fails, frontend can render). v2 plan can add a per-peer `fmp_profile` lookup to enrich names if there's frontend pressure.
- Summary-mode FMP output uses `DEFAULT_PEER_METRICS` keys verbatim (`grossProfitMarginTTM`, `_computed_fcf_margin`, etc. — see `peers.py:45-70`). Tool reshapes the FMP `comparison` rows into the `IndustryPeerComparison` dict layout: `{"peers": [{"ticker": <t>, "name": <t>, "key_metrics": {<all metric keys present in FMP comparison row>}, "relative_position": null, "source_refs": []}, ...]}`.
- No metric renaming — store FMP keys verbatim in `peers[].key_metrics` so the frontend renderer can use the existing `METRIC_LABELS` map at `peers.py:71+`
- `relative_position` always `None` (Decision #4 — dropped from v1)
- `source_refs` always `[]` (no FMP citation registry in v1)
- `failed_tickers` from FMP — drop silently in v1 (peers list reflects only `successful_peers`). Future improvement: surface a warning field.

**MCP error surfacing** (R4 clarification per Codex R3 SHOULD-FIX): when `industry_peer_comparison` raises `IndustryToolUpstreamError`, the MCP server layer converts it to `{"status": "error", "error": "<message>", "error_class": "IndustryToolUpstreamError"}` per the existing FMP MCP wrapper pattern (e.g., `fmp/server.py` returns `{status: error}` shapes). The error class is NOT preserved as a Python exception type to the MCP caller; it's serialized as a string label. Skills handling this output check `result.get("status") == "error"` and read `error_class` if they need to differentiate.

**Tool does NOT write to research.db.** Pure compute primitive returning a dict. Consumers route output through `apply_patch_ops` MCP tool (already shipped from Plan #6) which POSTs to `/api/research/files/{id}/patch-ops/apply`. Pydantic validation happens at the request boundary (FastAPI parses `batch: HandoffPatchBatch`) or at `_coerce_batch` for in-process calls — see "Validation error propagation" note in §10.

**Tests** (~13, R3 scope cut to match dropped `metrics` kwarg):
- 4 shape tests (output dict matches `IndustryPeerComparison` Pydantic shape — verified by constructing the type from the dict in the test, even though the tool itself doesn't import the type)
- 3 peer-set tests (explicit `peers="MSFT,GOOGL"`; FMP default discovery; empty `successful_peers` list handling at `peers.py:442`)
- 2 default-metric tests (assert FMP keys present in output; assert `relative_position` always None)
- 2 edge-case tests (focal ticker missing from FMP; FMP returns subset of metrics — tool propagates None for absent keys, doesn't crash)
- 1 golden-fixture test (MSFT peer comp; assert structure not exact values since FMP data shifts)
- 1 error-path test (FMP failure → `ActionInfrastructureError` via `IndustryToolUpstreamError` per §5.D R3)

---

### Sub-phase C — Three new skill markdown files

**Owner repo**: AI-excel-addin
**Files**:
- `api/memory/workspace/notes/skills/industry-landscape.md` (NEW)
- `api/memory/workspace/notes/skills/industry-macro-overlay.md` (NEW)
- `api/memory/workspace/notes/skills/structural-trends.md` (NEW)

**Skill template** (each follows existing `macro-review.md` / `position-initiation.md` shape):

```yaml
---
name: <skill-name>
description: <one line>
version: 1.0
scope: ticker
agent_callable: true
resumable: true
agent_description: <one line — agent-readable>
max_turns: <budget>
persist_state: true
---
```

**`industry-landscape`** (max_turns: 8):
- Pulls EDGAR Item 1 (Business) + Item 1A (Risk Factors) for focal ticker
- Pulls 1-2 most recent earnings transcripts (focal + 1 key peer)
- Synthesizes 3-5 paragraph narrative on industry structure, competitive dynamics, focal ticker's position
- Reads `Thesis.sources[]` first (read-only). Cites only `source_id`s that already exist there. If a needed source isn't registered, skill writes the narrative without citing it (no `register_source` call — that surface doesn't exist in v1; closes Codex R1 blocker #4).
- Output: `IndustryLandscape{narrative, citations}` → `update_industry_landscape` op
- **Does NOT touch `peer_comparison`** — `relative_position` is dropped from Plan #7 per Decision #4 R2. Skill stays in its lane (landscape narrative only).

**`industry-macro-overlay`** (max_turns: 6):
- Pulls `get_economic_data` (rates, FX, inflation indicators relevant to focal ticker's geography/sector)
- Pulls `get_sector_overview` for focal ticker's sector
- Pulls `get_market_context` for breadth signals
- Identifies 3-7 macro drivers with `description` + free-form `sensitivity` ("EPS down ~3% per 100bp 10Y move")
- Output: `MacroOverlay{drivers}` → `update_macro_overlay` op
- Soft taxonomy in prompt for `sensitivity`: directional label first ("positive"/"negative"/"mixed"), then quantified rationale

**`structural-trends`** (max_turns: 8):
- Pulls 3-4 earnings transcripts spanning 12-24 months
- Pulls EDGAR Item 1A across two annual filings (compare year-over-year for trend evolution)
- Identifies structural (multi-year, not cyclical) trends affecting focal company
- Output: `list[StructuralTrend]` → `replace_structural_trends` op
- `time_horizon` is canonicalized at write time by the new validator (Sub-phase A) — skill emits any of the recognized variants; canonicalizer normalizes to `{near-term, medium-term, long-term}`. Prompt documents the three buckets but doesn't enforce — schema validator is the enforcement point.

**Skill prompt boilerplate** (shared across all three, R2 corrected):
- "Citations: read `Thesis.sources[]` first. Cite only `source_id`s that already exist there. If your narrative would need an unregistered source, write without citing it for that claim. Do NOT call any source-registration tool — none exists in v1."
- "Output type: produce a typed `<Section>` Pydantic object. Wrap in the appropriate patch op via the `apply_patch_ops` MCP tool (existing — Plan #6)."
- "Concurrent safety: the patch engine retries CAS conflicts up to 3× automatically. If you get `PatchStaleRetryExhaustedError`, re-read the Thesis fully and decide whether to regenerate or abort."

**Tests** (~6):
- Skill smoke fixtures via `tests/skill_evals/fixtures/` — one fixture per skill (3 fixtures)
- Each fixture: a frozen ticker context + golden output validates as the typed Pydantic class
- 3 prompt-validation tests (frontmatter parses; agent_callable=true; max_turns set)

---

### Sub-phase D — Typed errors (R3: 1 error class, no classifier wiring needed)

**Owner repo**: risk_module
**Files** (R3: scope cut further per Codex R2 blocker #5):
- `risk_module/actions/errors.py` — add 1 typed error class (`IndustryToolUpstreamError`)
- `risk_module/tests/actions/test_errors_industry.py` (NEW) — 2 tests

**R3 changes vs R2** (closes Codex R2 blocker #5):

The R2 plan tried to wire 3 errors through `_THESIS_ERROR_TYPES` classifier (`research_gateway.py:49`). That was wrong on multiple counts:

1. **`IndustryToolUpstreamError`** is raised by the risk_module tool directly (sub-phase B), NOT returned via the AI-excel-addin gateway response that `_classify_and_raise` parses. So `_THESIS_ERROR_TYPES` is the wrong extension point. R3: the error class lives in `actions/errors.py` (extending `ActionInfrastructureError`); the sub-phase B tool raises it directly when FMP fails. MCP server catches `ActionError` subclasses and surfaces them to the caller.
2. **`IndustryPatchStaleError`** can't be selectively raised "for industry-section ops" because upstream `PatchStaleRetryExhaustedError(retry_count)` at `AI-excel-addin/api/research/errors.py:166` carries no op or section context — the gateway can't tell whether the stale was from an industry op or any other op. R3: drop this class entirely; generic `PatchStaleRetryExhaustedError` continues to flow through unchanged. Skills handle it the same way they handle stale errors from any other Plan #6 op.
3. **`IndustryAnalysisSectionMismatchError`** is fired by Pydantic discriminator when the op's `value` shape is wrong. That's a `pydantic.ValidationError` raised at the request boundary (FastAPI parses `batch: HandoffPatchBatch` before engine runs); `services/research_gateway.py:270` maps the resulting 422 detail to a generic `ActionValidationError`. R3: drop this class; the existing request-boundary validation is sufficient.

**Single error class** (R3):

```python
# risk_module/actions/errors.py — added after ActionInfrastructureError (line 89)
class IndustryToolUpstreamError(ActionInfrastructureError):
    """Raised by industry_peer_comparison when FMP upstream fails."""

    def __init__(self, message: str, *, ticker: str | None = None, upstream: str = "fmp") -> None:
        super().__init__(message)
        self.ticker = ticker
        self.upstream = upstream
```

No `error_type` attribute needed because this error is raised directly from the risk_module tool, not classified from a gateway response. No `_THESIS_ERROR_TYPES` registration. No detail dict required — base class `ActionInfrastructureError` is sufficient.

**Tests** (~2):
- 1 unit test (raise `IndustryToolUpstreamError`; verify ticker + upstream attrs round-trip)
- 1 integration test (mock `fmp.compare_peers` to raise; verify `industry_peer_comparison` re-raises as `IndustryToolUpstreamError`)

---

### Sub-phase E — `position-initiation` orchestration hook

**Owner repo**: AI-excel-addin
**Files**:
- `api/memory/workspace/notes/skills/position-initiation.md` — add workflow step
- `tests/skill_evals/fixtures/position-initiation/` — extend existing fixture to assert industry_analysis populated
- (no new files)

**Workflow step addition** (R2: SEQUENTIAL ops, NOT batched — closes Codex R1 blocker #2):

```markdown
## Step N — Industry Research (NEW per Plan #7)

Gating: skip this step if `process_template.section_config.required` (per `schema/process_template.py:60`) does NOT include `"industry_analysis"`. Templates that include it MUST run all four; partial industry analysis is not a v1 mode.

Apply ops SEQUENTIALLY (one apply_patch_ops call per op). The patch engine retries CAS conflicts up to 3× internally per call, so each step is robust to transient concurrent edits. Sequential apply means:
  - Each call writes one op
  - The next call reads the freshest Thesis (post-prior-write) before folding
  - No single-batch race window

Order:
1. Call deterministic tool: `industry_peer_comparison(symbol=<focal>)` → returns dict shaped to `IndustryPeerComparison`
   Apply: `apply_patch_ops` with one `replace_industry_peer_comparison` op (Pydantic validates the dict at the request boundary — FastAPI parses `batch: HandoffPatchBatch` before the engine runs)
2. Run `industry-macro-overlay` skill (parallel-safe with structural-trends but sequential to keep §10 simple)
   Apply: `apply_patch_ops` with one `update_macro_overlay` op
3. Run `structural-trends` skill
   Apply: `apply_patch_ops` with one `replace_structural_trends` op
4. Run `industry-landscape` skill (last because it can read the now-populated peer/macro/trends sections for narrative context)
   Apply: `apply_patch_ops` with one `update_industry_landscape` op

Why sequential (R3 reworded per Codex R2 SHOULD-FIX): the primary motivation is **dependency ordering** — `industry-landscape` benefits from reading already-populated peer/macro/trends sections to refine narrative. It is NOT a fix for cross-session concurrency correctness — same-session sequential apply still LWWs against any concurrent off-session writer (rare in single-user Hank context). R1 proposed a batch, which would couple the four ops into one fold-or-reject; sequential decouples the failure modes (one bad skill output doesn't block the others) and lets later skills see earlier sections. Cost: 4 round-trips instead of 1. Acceptable in single-user context.
```

**Tests** (~3):
- 1 orchestration smoke test (`industry_analysis` populated after position-initiation run with template that requires it)
- 1 process-template gating test (skip when `section_config.required` excludes `"industry_analysis"`)
- 1 sequential-ordering test (verify `industry-landscape` reads the populated peer/macro/trends from the same run before generating narrative)

---

### Sub-phase F — `SKILL_CONTRACT_MAP.md` + ship marker

**Owner repo**: AI-excel-addin
**Files**:
- `docs/SKILL_CONTRACT_MAP.md` — three new skill rows + one new tool row
- `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` (in `risk_module`) — §12 ship-notes block, V2.P9 rollup update to **9 SHIPPED / 2 DESIGNED**
- `risk_module/docs/TODO.md` — V2.P9 row marked SHIPPED

**Test count**: 0 (docs only)

---

## 6. Test count target (R2: rebalanced)

| Sub-phase | Tests | Notes |
|---|---|---|
| A — patch ops + canonicalizer + SectionKey bump + diligence_service.SECTION_TITLES | ~19 | +2 vs R2 (diligence_service test + dual-edit test) |
| B — deterministic tool | ~13 | -2 vs R2 (dropped metrics-kwarg tests since kwarg dropped) |
| C — skill markdown | ~6 | unchanged |
| D — typed errors | ~2 | -3 vs R2 (1 error class not 3; no classifier wiring) |
| E — orchestration | ~3 | unchanged |
| **E2E** | ~5 | R3 corrected (4 ops × 1 route preview/apply round-trip + 1 orchestration end-to-end). Mirrors `AI-excel-addin/tests/integration/test_plan_6_e2e.py:658,666,913` pattern. Lives at `AI-excel-addin/tests/integration/test_plan_7_e2e.py` (NEW). |
| F — docs | 0 | |
| **Total** | **~48** | |

R3 corrects E2E count to 5 per Codex R2 SHOULD-FIX. Each new op type gets its own route-level test (parameterized fixture acceptable). The 5th E2E covers the `position-initiation` orchestration end-to-end with a fixture template that requires `industry_analysis`.

---

## 7. Dependencies (R5 — graph fixed to match prose)

```
A (patch ops + SectionKey + canonicalizer) ──┐
                                              │
B (deterministic tool, risk_module) ──────────┤
                                              ├─→ E (orchestration) ──→ F (docs)
C (skill markdown) ───────────────────────────┤        │
                                              │   E2E tests
D (typed errors, risk_module) ────────────────┘
```

A, B, C, D can all ship in parallel (R4 correction per Codex R4 blocker #1: D no longer depends on A — `IndustryToolUpstreamError` is a direct risk_module tool error, no engine error codes flow through). E depends on A+B+C+D (orchestration needs op classes, tool, skills, and errors all wired). E2E tests depend on A+B+C+D. F is last.

**Cross-repo coordination** (R4: simpler still — no inter-PR ordering required):
- AI-excel-addin PR #1: sub-phases A + C (one branch covering schema + skill markdown)
- risk_module PR #1: sub-phases B + D (industry_peer_comparison MCP tool + IndustryToolUpstreamError class)
- AI-excel-addin PR #2: sub-phase E + E2E tests (depends on both PRs above merging)
- Both repos: sub-phase F docs (lockstep)

**No gateway sync needed** in R2: the deterministic tool runs entirely in risk_module process. The patch-ops apply route in AI-excel-addin is unchanged (same `/api/research/files/{id}/patch-ops/apply` from Plan #6) — adding new op classes to the discriminated union is automatically picked up by the existing handler. **No `agent-gateway-dist` resync needed** — confirmed by checking that no gateway HTTP route is added in this plan.

R1's "Verify -dist state" warning is moot for this plan but stays in the project memory for cross-repo work that DOES touch the gateway.

---

## 8. Codex review brief

Send to `mcp__codex__codex` for review. The active brief should:

- Reference the current §Status block + the most recent revision-history entry
- Cite the master plan §6.2 + §6.6 + §10b.1 + §12 row 7 as authoritative design source
- Call out the most contested decisions for the current revision
- Invite local execution per the "Codex reviewers should execute locally" memory rule
- Run a grep contract: every named term, file path, function/class name, and constant cited in the live spec should be verifiable in shipped code
- Request `PASS / FAIL` with file:line citations for any blockers

Each round's actual prompt is sent through the `mcp__codex__codex` tool call (not stored here, since round-specific phrasing rots fast). The plan's revision history (top of doc) records what each round addressed.

---

## 9. Open items

None — Codex R7 PASS. Plan is implementation-ready. Sub-phases A, B, C, D can ship in parallel per §7; E depends on all four; F is last.

---

## 10. Risks (R4 corrected)

**Validation-error propagation note** (R4 per Codex R3 SHOULD-FIX): malformed op bodies (e.g., a `replace_industry_peer_comparison` value missing the required `peers` key) validate at FastAPI request parsing — BEFORE `patch_engine.py:148-200`. The caller receives a 422 with FastAPI's structured detail. `services/research_gateway.py` maps that list-shaped detail to `ActionValidationError` (generic, not industry-specific). This is informative (caller sees field-level error from Pydantic) but it is NOT a typed engine error. Skills handling op-construction failures should expect 422 with detail describing the missing/wrong field, not a custom `ActionStructuredValidationError` subclass.



- **Skill output drift on `sensitivity`** — free-form strings could fragment. Mitigated by prompt-level convention. **Re-evaluation trigger**: 5+ distinct phrasings observed in real macro-overlay outputs.
- **`time_horizon` canonicalizer false negatives** — variants we didn't anticipate raise `ValueError` at write time. R3 strict mode (closes Codex R2 SHOULD-FIX inconsistency): matches shipped pattern (`canonicalize_optional_timeframe` raises on unknowns at `enum_canonicalizers.py:90`). Mitigation: skill prompts document the three accepted buckets; canonicalizer accepts common variants (hyphen/underscore/space/case); skill outputs are fixture-tested before production. If a real output raises in production, that's a skill-output bug to fix in the prompt, not a canonicalizer bug.
- **CAS retry exhaustion under concurrent edits** — engine retries 3× with 0.05s backoff per `patch_engine.py:125-145`. Under sustained concurrent writes (rare for single-user Hank), an industry op could surface generic `PatchStaleRetryExhaustedError` (from `AI-excel-addin/api/research/errors.py:166`; not industry-specific because upstream carries no op context). Mitigated by sequential orchestration in §5.E + retry-exhaustion is a recoverable error (caller decides whether to re-run skill).
- **Last-writer-wins on same-section concurrent writes** — explicit v1 semantic. Cross-session concurrent writes to the same `industry_analysis` section will lose one of them after retry exhaustion. Bounded loss (skills regenerate the whole section). v2 plan adds section-version optimistic locking if this becomes a real-world problem.
- **`compare_peers` FMP cost** — hitting FMP for N peer profiles is non-trivial. Mitigated by reusing existing FMP-MCP cache layer (`fmp/tools/peers.py:_get_cached_peer_metric_snapshot:106` already caches). No new caching in this plan.
- **Tool dict shape drift vs Pydantic contract** — risk_module's `industry_peer_comparison` emits a dict shaped to match `IndustryPeerComparison`. If the AI-excel-addin Pydantic shape changes (e.g., adds a required field), the dict will fail at patch-op apply. Mitigated by (a) `IndustryPeerComparison` is a shared-slice contract per master plan §6.6 — load-bearing invariant, not free to change; (b) the route-level E2E test in §6 catches drift on every CI run; (c) any contract change would be a versioned bump per master plan §8 versioning.
