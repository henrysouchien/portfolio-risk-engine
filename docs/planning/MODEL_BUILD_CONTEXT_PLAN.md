# ModelBuildContext — Implementation Plan

**Status**: PASS (Codex R8). R1-R7 change logs preserved inline.
**Created**: 2026-04-20
**Design inputs**:
- `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` — contract shapes (PASS R6), esp. §6.3 (ModelBuildContext) and §10a.15 (three-category segment-mode driver resolution)
- `docs/planning/THESIS_LIVING_ARTIFACT_PLAN.md` — plan #1 (PASS R7)
- `docs/planning/HANDOFF_ARTIFACT_V1_1_PLAN.md` — plan #2 (PASS R5)
- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md`

**Closes**: **G2** (the Rosetta Stone between handoff and FinancialModel). Unblocks plan #6 (ModelInsights/PriceTarget consumes MBC), plan #8 (EDGAR/FMP precedence refines MBC `historical_sources`).

**Hard prereqs**:
- Plan #1 implemented (for Thesis types + shared-slice module via plan #2's derivation path)
- Plan #2 implemented (for `HandoffArtifact v1.1` — MBC construction reads from this)

---

## 1. Purpose & scope

Ship the `ModelBuildContext` typed bridge between `HandoffArtifact v1.1` and `build_model()`. Specifically:

1. Pydantic `ModelBuildContext v1.0` in `schema/model_build_context.py`.
2. Construction function that derives MBC from HandoffArtifact v1.1 + workspace state + optional user overrides.
3. **Two-phase validation at MBC construction**: Phase 1 static (driver_mapping.yaml + raw-key check against SIA template), Phase 2 post-expansion (segment-mode builds, simulates `expand_segments()` against `segment_profile_snapshot`).
4. **Builder behavior change**: `build_model()` honors `segment_profile_snapshot` verbatim — no re-discovery, no re-sort, no override reapplication when snapshot is populated.
5. **`driver_mapping.yaml` rework** per Decision 15: Category A keys (`revenue.segment_N.volume_growth`, `.price_growth`) emit segment-aware resolutions. Category B keys (e.g., `.operating_metric`, `.revenue` — derived after expansion) rejected with `UnsupportedInSegmentMode`. Category C unchanged.
6. **Typed error surface**: `InvalidDriverKey`, `SegmentExpansionAmbiguity`, `UnsupportedInSegmentMode`, `MissingSegmentSnapshot`, `SegmentProfileMismatch`. Replaces today's tolerant-skip behavior at `annotate.py:82-86`.
7. MCP tool `get_model_build_context(research_file_id, overrides?)`. Existing `build_model` MCP tool accepts an optional `model_build_context_id`; when supplied, the tool resolves the MBC row and dispatches to the new `build_model_from_mbc(mbc)` wrapper (per §10 — legacy `build_model()` signature is preserved untouched; MBC-first path flows through the wrapper).

**Non-goals** (deferred):
- `ModelInsights` + `PriceTarget` + `HandoffPatchOp` — plan #6.
- EDGAR vs FMP request-time precedence beyond the MBC field (i.e., wiring it through `populate_historicals`) — plan #8.
- Rewriting `annotate_model_with_research` to consume MBC directly — done in this plan only at the validation boundary; the existing `resolve_driver_cells()` path stays intact as the final address resolver.
- ProcessTemplate-driven driver taxonomy overrides — plan #5.
- Frontend UI for MBC preview — deferred.

---

## 2. Sub-phase summary

| # | Sub-phase | Scope | Duration | Depends on |
|---|---|---|---|---|
| A | `ModelBuildContext` Pydantic type | Shape per design §6.3 + typed error hierarchy | ~2 days | None (self-contained) |
| B | Phase 1 static validator | `driver_mapping.yaml` + raw-key resolution against SIA template | ~2 days | A |
| C | `driver_mapping.yaml` rework (Category A segment-aware) | YAML + `resolve_driver_key` extension for segment-indexed keys | ~3 days | A |
| D | Phase 2 post-expansion validator | Simulates `expand_segments()` against `segment_profile_snapshot`; categorizes Cat A/B1/B2/C | ~3 days | A, B, C |
| E | MBC constructor: HandoffArtifact v1.1 → MBC | Action-layer function; reads plan #2 artifact + workspace state | ~3 days | A, plan #2 |
| F | `build_model()` behavior change (honor snapshot verbatim) | Add `mbc_segment_config` parameter for snapshot-authoritative branch; ship `build_model_from_mbc(mbc)` wrapper for MBC-driven scalars | ~3 days | A |
| I | Orchestrator + annotate threading (R2 — new) | `build_model_orchestrator` calls `build_model_from_mbc(mbc)` AND `annotate_model_with_research_from_mbc(mbc)` wrappers (per §10 — legacy functions unchanged) | ~2 days | A, E, F |
| J | MBC persistence (R2 — split from G) | `model_build_contexts` SQLite table + repo API + migration v4→v5 | ~2 days | A |
| G | MCP tool surface | `get_model_build_context` + `build_model` MCP tool accepts `model_build_context_id` and dispatches to `build_model_from_mbc` wrapper | ~2 days | B, D, E, F, I, J |
| H | `SKILL_CONTRACT_MAP.md` updates | `/build-model` skill row + contracts table | ~0.5 day | G |

**Total**: ~22.5 working days. Parallelism: B/C in parallel after A; D after B+C; E parallel with B/C/D; F after A; J parallel with F; I after E+F; G after D+E+F+I+J.

---

## 3. Dependency graph

```
Plan #1 + Plan #2 (implemented, not just PASSed)    ◄── hard prereqs
   │
   ▼
A (MBC Pydantic type + error hierarchy)
  ├── B (Phase 1 static validator)  ──┐
  ├── C (driver_mapping.yaml rework) ─┼── D (Phase 2 post-expansion validator)
  ├── E (MBC constructor)             │
  ├── F (build_model behavior change) │
  ├── J (MBC persistence + v4→v5 mig) │
  │                                    │
  └── I (orchestrator + annotate MBC threading) ◄── after E + F
      │
      └── G (MCP tools) ◄──────────────┘
           │
           └── H (SKILL_CONTRACT_MAP)
```

Plan #2 hard prereq is only for sub-phase E (reads HandoffArtifact v1.1). A/B/C/D/F can drop earlier against the schema design doc if plan #2 implementation lags.

---

## 4. Cross-cutting concerns

### 4.1 Derivation, not authoring

MBC is **derived** from HandoffArtifact v1.1 + workspace state. It is NOT authored independently — analysts/agents do not write MBC rows. The only user-facing write path is the `overrides?` parameter on the constructor, which layers on top of the derived base. This keeps MBC in sync with the canonical thesis/handoff and prevents drift.

### 4.2 Validation at construction, not at cell-write

Today, driver-key resolution happens at cell-write time in `schema/annotate.py:83` via `resolve_driver_cells(model, driver_key)`. On failure, the assumption is silently skipped (`annotate.py:82-86`). Under MBC, validation moves to **construction time**:

- Phase 1 runs during `get_model_build_context()` — before any model I/O.
- Phase 2 runs for segment-mode builds, also at MBC construction — before `expand_segments()` actually runs.
- Both phases emit typed errors. The existing `resolve_driver_cells` at `annotate.py:83` remains the final address resolver; under MBC it becomes a no-op safety net since every driver_key has been pre-validated.

### 4.3 segment_profile_snapshot AUTHORITATIVE

Per design §6.3 R6 binding rule: when `segment_config.segment_profile_snapshot` is populated in MBC, the builder MUST use it verbatim. No re-discovery (`discover_all_axes()`), no re-sort by current-year revenue (`segments.py:220`), no re-application of `segment_mapping` overrides. The snapshot IS the input.

Sub-phase F implements this. The existing `build_model()` at `build.py:496-569` currently re-discovers in segment mode; plan 3 replaces the discovery branch with "if MBC.segment_config.segment_profile_snapshot is populated, use it; else fall back to legacy discovery for non-MBC callers."

### 4.4 Three-category segment-mode driver resolution (Decision 15)

Per design §10a.15:
- **Category A** — post-expansion INPUT rows (`business_segment_{n}_volume_growth`, `.price_growth`). At MBC Phase 2, rewrite YAML-sourced keys to `raw:tpl.a.revenue_drivers.business_segment_{n}_{role}` using `segment_profile_snapshot.segments[index].segment_index`. Deterministic.
- **Category B1** — not rebuilt by expansion (`.operating_metric`): `UnsupportedInSegmentMode(reason="no post-expansion equivalent")`.
- **Category B2** — rebuilt but not as input (`.revenue` → `business_segment_{n}_revenue` is `ItemType.derived`, rejected by `driver_resolver._validate_mapping` at `driver_resolver.py:55`): `UnsupportedInSegmentMode(reason="post-expansion target is derived, not input")`.
- **Category C** — non-segment (`tax_rate`, `dso`, `capex_pct`, `debt_change`): unaffected by expansion. Phase 1 validates via static YAML; Phase 2 passes through.

Sub-phase C implements the YAML rework + `resolve_driver_key` extension to emit Category A segment-aware resolutions. Sub-phase D implements Phase 2 validation + Category B rejection.

### 4.5 Cross-plan alignment

- **Plan #2**: MBC constructor (sub-phase E) reads `HandoffArtifact v1.1` via the plan #2 API. Specifically: `valuation.method`, `assumptions[].{driver, value, unit, rationale, confidence?, driver_category?}`, `catalysts`, `risks`. These are shared-slice fields copied from Thesis.
- **Plan #1**: MBC does NOT read Thesis directly. Everything flows through HandoffArtifact v1.1 (plan #2's artifact). Keeps MBC stateless relative to Thesis mutations between snapshots.
- **Plan #6 (future)**: `ModelInsights` consumes MBC to produce sensitivities; `HandoffPatchOp` can update `HandoffArtifact.assumptions[].value`, which re-runs MBC on next build.

### 4.6 Enum canonicalization (R2 — narrowed per Codex R1 should-fix #1)

Plan #1's `schema/enum_canonicalizers.py` covers `direction/strategy/timeframe` only — those apply to Thesis/HandoffArtifact headline fields, not MBC.

MBC-specific enum handling:
- **`ValuationMethod`** (`dcf | multiples | sum_of_parts | hybrid`): direct Pydantic `Literal` validation. No canonicalizer needed — shared with `HandoffArtifact.valuation.method` (plan #2 §6.2) and `ProcessTemplate.valuation_methods_allowed` (design §6.5). Strict match; no legacy Title-Case input expected.
- **`Unit`** (`dollars | percentage | ratio | count | per_share | days | multiple`): direct Pydantic `Literal`. Already an enum in `schema/models.py:84`.
- **`driver_key`**: NOT an enum. Normalized by `resolve_driver_key()` in the resolver (per sub-phase C), not by enum canonicalizers.

---

## 5. Sub-phase A — `ModelBuildContext` Pydantic type + error hierarchy

### 5.1 Goal

Pydantic v2 type in `schema/model_build_context.py` matching design §6.3 shape. Plus typed error hierarchy.

### 5.2 Design

Field shape follows design §6.3 verbatim. Key types:

- `ModelBuildContext` — top-level
- `FiscalAxis` — `period_mode`, `historical_years: list[int]`, `projection_years: list[int]`
- `SegmentConfig` — `axis?`, `segment_mapping?: list[SegmentMappingEntry]`, `segment_profile_snapshot: SegmentProfileSnapshot` (REQUIRED when `SegmentConfig` populated per R6)
- `SegmentMappingEntry` — `{edgar_member, name?, volume_label?, price_label?}` (matches `apply_segment_overrides` input at `segments.py:263`)
- `SegmentProfileSnapshot` — `axis_used?, source, segments: list[SegmentSnapshotEntry], total_revenue_check?`
- `SegmentSnapshotEntry` — `{segment_index, name, edgar_member?, volume_label?, price_label?, revenue_values?}` (includes volume_label + price_label per R5 of design)
- `Driver` — `{assumption_id?, value, unit: Unit, periods?: list[int], sia_category?: DriverCategory, rationale?, confidence?: Confidence}`. Keyed by `driver_key` in the containing dict.
- `Scenario` — `{description?, overrides: dict[driver_key, ScenarioOverride]}`
- `ScenarioOverride` — `{value, periods?: list[int]}`
- `Valuation` — `{method: ValuationMethod, inputs: ValuationInputs, ranges: ValuationRanges, rationale}`
- `ValuationInputs` — `{discount_rate?: DiscountRateSpec, terminal_growth?, exit_multiple?}`
- `HistoricalSources` — `{default_source: Literal["fmp", "edgar"], overrides: list[HistoricalSourceOverride]}`
- `HistoricalSourceOverride` — `{concept_id, preferred: fmp|edgar, fallback_order: list[str]}`
- `BuildFlags` — `{include_historicals: bool, annotate_with_research: bool, preview_mode: bool}`

**Dict-keyed uniqueness**: `drivers: dict[str, Driver]` and `scenarios[name].overrides: dict[str, ScenarioOverride]` — Pydantic dict key enforces uniqueness. Closes the R2 finding on list-based ambiguity from the schema design doc.

**Error hierarchy** (`schema/model_build_context_errors.py`):

```python
class ModelBuildContextError(Exception): ...  # base

class InvalidDriverKey(ModelBuildContextError):
    driver_key: str
    reason: str                  # "not in driver_mapping.yaml" | "raw: target missing from template" |
                                 # "raw: target is not ItemType.input" | ...

class SegmentExpansionAmbiguity(ModelBuildContextError):
    driver_key: str
    segment_index: int | None
    reason: str

class UnsupportedInSegmentMode(ModelBuildContextError):
    driver_key: str
    category: Literal["B1", "B2"]
    reason: str

class MissingSegmentSnapshot(ModelBuildContextError):
    reason: str                  # "segment_config populated without segment_profile_snapshot"

class SegmentProfileMismatch(ModelBuildContextError):
    # Raised at build time if actual discovery disagrees with snapshot
    # (observability guardrail; NOT expected in normal flow post-F).
    reason: str
```

### 5.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `schema/model_build_context.py` | MBC Pydantic type + nested types | ~500 |
| `schema/model_build_context_errors.py` | Typed error hierarchy | ~80 |
| `tests/schema/test_model_build_context_types.py` | Pydantic unit tests | ~350 |

### 5.4 Tests (~32)

- Pydantic validation per field (~16)
- Dict-key uniqueness (drivers + scenarios) (4)
- `segment_profile_snapshot` required when `segment_config` populated (2, positive + negative)
- Enum canonicalization (3)
- Error hierarchy types (5)
- JSON roundtrip (2)

### 5.5 Acceptance gate

- All tests pass.
- All 5 typed errors importable.
- Dict-keyed fields reject duplicate keys at Pydantic validation.

### 5.6 Rollback

Delete the three new files. No downstream consumer yet.

---

## 6. Sub-phase B — Phase 1 static validator

### 6.1 Goal

`validate_phase1(mbc: ModelBuildContext) -> None` raises typed errors for any `driver_key` that fails static resolution against SIA template.

### 6.2 Design

For every `driver_key` in `mbc.drivers.keys()` and every `mbc.scenarios[*].overrides.keys()`:

1. If `driver_key.startswith("raw:")`: strip prefix, validate against SIA template via `_find_item()` (adapted from `driver_resolver.py:30`). Item must exist AND be `ItemType.input`.
2. Else: validate via `load_driver_mapping()` (driver_resolver.py:40) + template lookup. If key not in YAML → `InvalidDriverKey(reason="not in driver_mapping.yaml")`.

Failures raise `InvalidDriverKey` with the offending key + reason. No silent skip.

**Template loading**: uses `load_sia_generic_template()` (existing at `driver_resolver.py:11`). Reuses `_validate_mapping()` semantics from `driver_resolver.py:55` for the `ItemType.input` check.

### 6.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `schema/mbc_validator_phase1.py` | Static validator | ~200 |
| `tests/schema/test_mbc_phase1.py` | Static validation tests | ~300 |

### 6.4 Tests (~20)

- Valid YAML key → passes (3)
- Valid `raw:` key resolving to input item → passes (2)
- Unknown YAML key → `InvalidDriverKey` (3)
- `raw:` targeting non-existent template item → `InvalidDriverKey` (2)
- `raw:` targeting `ItemType.derived` / `header` → `InvalidDriverKey` (3)
- Applies to both `drivers` and `scenarios[].overrides` (3)
- Empty MBC → no error (1)
- Category C keys (`tax_rate`, `dso`) pass Phase 1 (3)

### 6.5 Acceptance gate

- All tests pass.
- Every Phase 1 failure produces a typed error with actionable `reason`.

### 6.6 Rollback

Delete the two files. MBC construction skips Phase 1; downstream paths fall back to existing `resolve_driver_cells` behavior (tolerant skip).

---

## 7. Sub-phase C — `driver_mapping.yaml` rework for Category A segment-aware resolutions

### 7.1 Goal

Per Decision 15 Category A: segment-qualified driver keys resolve to the correct post-expansion `business_segment_{n}_*` item at build time, rather than targeting pre-expansion IDs that `expand_segments()` deletes.

### 7.2 Design — tag-free structured YAML (R2 — closes Codex R1 blocker #1)

**Keep YAML flat + safe-load compatible.** No tags, no placeholders. All segment-aware logic lives in `resolve_driver_key()`, not in YAML structure. This avoids PyYAML constructor errors and `_validate_mapping` pre-substitution failures.

**YAML structure** (two top-level keys; second key is optional but normative):

```yaml
mappings:
  # Unchanged: flat dict[str, str]. Every value is a literal template item_id.
  # Enumerate segment-aware entries explicitly per N-segment support needed.
  revenue.segment_1.volume_growth: tpl.a.revenue_drivers.business_segment_1_volume_growth
  revenue.segment_1.price_growth:  tpl.a.revenue_drivers.business_segment_1_price_growth
  revenue.segment_2.volume_growth: tpl.a.revenue_drivers.business_segment_2_volume_growth
  revenue.segment_2.price_growth:  tpl.a.revenue_drivers.business_segment_2_price_growth
  # ... (enumerate through N as needed; resolver can extend via regex for indices beyond
  #      the enumerated set — see below)

  # Category C — unchanged
  tax_rate: tpl.a.tax_net_income.tax_rate
  dso: tpl.a.balance_sheet_wc.days_sales_outstanding
  # ... rest unchanged

# NEW top-level list: Category B rejection keys. Resolver checks this list and raises
# UnsupportedInSegmentMode with the `reason` field.
unsupported_in_segment_mode:
  - key: revenue.segment_N.operating_metric
    reason: "no post-expansion equivalent — expand_segments() does not emit an operating_metric row"
  - key: revenue.segment_N.revenue
    reason: "post-expansion target business_segment_N_revenue is ItemType.derived (per sia_generic.json:981/1375), not input"
```

The `key` uses `segment_N` as a *literal string marker* (not a placeholder — just the pattern-matching key the resolver checks). The resolver pattern-matches incoming keys like `revenue.segment_3.operating_metric` against this list's `key` field treating `N` as the numeric capture group.

**`resolve_driver_key()` extension** at `AI-excel-addin/schema/driver_resolver.py:76`:

1. **Pre-check Category B**: for each entry in the YAML `unsupported_in_segment_mode` list, compile a key-specific regex by replacing the literal `N` in the entry's `key` field with `(\d+)` (e.g., `revenue.segment_N.operating_metric` → `r"^revenue\.segment_(\d+)\.operating_metric$"`). If the incoming driver_key matches any Category B entry's compiled regex → raise `UnsupportedInSegmentMode(driver_key, reason)` with the entry's `reason` verbatim. This is per-literal compilation, NOT one broad `(\w+)` pattern — keeps rejection precise to the actual unsupported roles.
2. **Direct lookup** in `mappings`: if key is literally present (e.g., `revenue.segment_1.volume_growth` was enumerated) → return its literal value.
3. **Dynamic Category A extension**: if key matches `r"^revenue\.segment_(\d+)\.(\w+)$"` AND role is in the known Category A set (`volume_growth`, `price_growth` — explicit allowlist), construct the target item_id `tpl.a.revenue_drivers.business_segment_{N}_{role}` and validate via `_find_item()` against the template. This handles segment indices beyond the enumerated YAML entries.
4. **`raw:` prefix handling**: unchanged from current `resolve_driver_key`.
5. All other unknown keys → `InvalidDriverKey`.

**Backward compat**: existing YAML keys continue to resolve via direct lookup (step 2). Existing callers see no change for non-segment keys.

**Why not templated YAML**: PyYAML safe-load + `_validate_mapping`'s immediate item-ID check at load time makes placeholder resolution impossible without reworking the load pipeline. Keeping literal YAML values avoids that rewrite.

### 7.3 Files to modify

| File | Change |
|---|---|
| `AI-excel-addin/schema/templates/driver_mapping.yaml` | Add literal segment-aware entries + new `unsupported_in_segment_mode` top-level list |
| `AI-excel-addin/schema/driver_resolver.py` | Extend `resolve_driver_key()` for regex-based segment resolution + `unsupported_in_segment_mode` pre-check |
| `tests/schema/test_driver_resolver_segment_aware.py` | New (~350 lines) |

### 7.4 Tests (~25)

- Category A segment-aware resolution (5: segments 1, 2, 3, 4, N)
- Category B1 raises `UnsupportedInSegmentMode` (2)
- Category B2 raises `UnsupportedInSegmentMode` (2)
- Category C unchanged (3)
- Legacy fully-qualified key fallback (3)
- `unsupported_in_segment_mode` list parsing + Category B pre-check (4)
- `UnsupportedInSegmentMode.reason` propagates from YAML `reason` field (2)
- Regex mismatch safety (2)
- Template item not found after substitution → `InvalidDriverKey` (2)

### 7.5 Acceptance gate

- All tests pass.
- Existing callers of `resolve_driver_key` (`annotate.py:82`) unaffected for non-segment keys.
- Category B keys raise at resolve time, not silently skipped.

### 7.6 Rollback

Revert YAML + `driver_resolver.py` changes. Segment-mode MBC construction will fail Phase 2 for Category A keys unless users use raw: overrides (acceptable fallback per Decision 15 "until rework lands").

---

## 8. Sub-phase D — Phase 2 post-expansion validator

### 8.1 Goal

`validate_phase2(mbc: ModelBuildContext) -> None` runs only for segment-mode MBCs (`mbc.segment_config` present). Simulates `expand_segments()` against the snapshot; categorizes each driver_key A/B1/B2/C; rejects Category B; raises `SegmentExpansionAmbiguity` for unresolvable Category A.

### 8.2 Design

When `mbc.segment_config` is present:

1. Verify `segment_profile_snapshot` populated — else `MissingSegmentSnapshot`. (Pydantic catches this in A, but defensive check at validator boundary.)
2. **Verify segment_index integrity** (R2 — closes Codex R1 blocker #5). The snapshot's segment_index values MUST form a complete 1-based sequence `[1, 2, ..., N]`, no gaps, no duplicates, no zeros, no negatives. Algorithm:
   ```
   indices = sorted(s.segment_index for s in snapshot.segments)
   if indices != list(range(1, len(snapshot.segments) + 1)):
       raise SegmentProfileMismatch(reason=f"segment_index sequence must be 1..N complete; got {indices}")
   ```
3. For each `driver_key` in `mbc.drivers.keys()` and `mbc.scenarios[name].overrides.keys()`:
   - Classify A/B1/B2/C using `resolve_driver_key` per sub-phase C.
   - Category B1/B2 → record `UnsupportedInSegmentMode`.
   - Category A → extract segment_index from the key (regex capture group). Verify it's in the snapshot's valid range `1..N`. If out-of-bounds → record `SegmentExpansionAmbiguity`.
   - Category C → pass through (no segment-index check).
4. All errors surfaced as structured, **MCP-serializable** list (R2 — closes Codex R1 blocker #6).

**`ValidationReport`** shape — MCP-safe serializable (R2):

```python
class DriverVerdict(BaseModel):
    origin:            Literal["drivers", "scenarios"]
    scenario_name:     str | None           # populated when origin == "scenarios"
    driver_key:        str
    category:          Literal["A", "B1", "B2", "C"] | None
    resolved_item_id:  str | None
    error_type:        Literal["InvalidDriverKey", "SegmentExpansionAmbiguity",
                               "UnsupportedInSegmentMode",
                               "MissingSegmentSnapshot",
                               "SegmentProfileMismatch"] | None
    error_reason:      str | None

class ValidationReport(BaseModel):
    phase1_passed:    bool
    phase2_passed:    bool
    driver_verdicts:  list[DriverVerdict]    # list, not dict — preserves per-origin location
    summary:          dict[str, int]         # {"A": N, "B1": N, "B2": N, "C": N, "errors": N}
```

Error objects are NOT embedded; only typed strings (`error_type`, `error_reason`). Safe for JSON serialization across MCP gateway. The list-based `driver_verdicts` preserves origin (drivers vs scenarios[name]) so the same driver_key appearing in both contexts gets two separate verdicts.

### 8.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `schema/mbc_validator_phase2.py` | Post-expansion validator | ~300 |
| `tests/schema/test_mbc_phase2.py` | Phase 2 tests | ~400 |

### 8.4 Tests (~28)

- Phase 2 skipped when `segment_config is None` (2)
- Missing snapshot → `MissingSegmentSnapshot` (2)
- Category A resolution across segment_index 1..N (5)
- Category B1 rejection (3)
- Category B2 rejection (3)
- Category C pass (3)
- Out-of-bounds segment_index → `SegmentExpansionAmbiguity` (2)
- ValidationReport accumulation (3)
- End-to-end: mix of A/B1/B2/C in one MBC (3)
- Scenario overrides validated identically to drivers (2)

### 8.5 Acceptance gate

- All tests pass.
- Report-based validation permits batch error reporting for agent-friendly output.
- Fail-fast mode available via `raise_on_first_error=True`.

### 8.6 Rollback

Delete the two files. MBC skips Phase 2; segment-mode builds degrade to legacy tolerant-skip behavior.

---

## 9. Sub-phase E — MBC constructor (HandoffArtifact v1.1 → MBC)

### 9.1 Goal

`get_model_build_context(research_file_id, overrides: dict | None = None) -> MbcResult`. Derives MBC from plan #2's HandoffArtifact v1.1 + workspace state + user overrides; persists it; returns a typed result.

**Single canonical return type** (R4 — locks Codex R3 medium):

```python
class MbcResult(BaseModel):
    mbc_id:             str                  # UUID4 of the persisted row in model_build_contexts
    mbc:                ModelBuildContext    # the constructed + validated MBC
    validation_report:  ValidationReport     # §8.2 shape
```

All entry points return `MbcResult`:
- Internal service function `mbc_service.get_model_build_context(...)` → `MbcResult`.
- MCP tool `get_model_build_context(...)` → `MbcResult.model_dump()` (JSON-serialized for wire).
- Orchestrator consumes `MbcResult`: passes `.mbc` to `build_model_from_mbc` and `annotate_model_with_research_from_mbc`; writes `.mbc_id` into `HandoffArtifact.model_ref.model_build_context_id` via plan #2 Handoff-only write path.

One contract, one type. No `ModelBuildContext` direct return; no `{mbc_id}` dict shape; no implicit conversion.

### 9.2 Design

Algorithm:

1. Load finalized HandoffArtifact v1.1: `handoff_service.get_latest_handoff(research_file_id, status='finalized')`. R2 — per Codex R1 should-fix #4, typed error matrix:
   - **No handoff row exists** (no draft, no finalized): `raise NoHandoffExists(research_file_id)` — the research_file has never been worked on.
   - **Draft-only** (one or more drafts, no finalized): `raise HandoffNotFinalized(research_file_id, latest_draft_id)` — analyst hasn't completed diligence.
   - **Finalized exists**: proceed with latest finalized row.
   Both error types serialize to MCP with typed `error_type` + actionable `reason`.
2. Resolve company metadata: `company = handoff.company` (ticker, fiscal_year_end, most_recent_fy).
3. Derive `fiscal_axis`:
   - `period_mode`: from workspace config (defaults `yearly`).
   - `historical_years`: range of `[most_recent_fy - n_historical + 1, most_recent_fy]` (n_historical defaults to 5; override via `overrides.n_historical`).
   - `projection_years`: range of `[most_recent_fy + 1, most_recent_fy + n_projection]` (defaults 12).
4. Derive `drivers`:
   - For each `handoff.assumptions[]` entry:
     - Key: `assumption.driver` (plan #2 preserves this field verbatim from Thesis)
     - Value: `Driver(assumption_id=assumption.assumption_id, value=..., unit=..., rationale=..., confidence=..., sia_category=assumption.driver_category)`.
5. Derive `valuation`:
   - Map `handoff.valuation.method` → `ValuationMethod` enum (with enum canonicalization).
   - `handoff.valuation.{low, mid, high}` → `ValuationRanges`.
   - `handoff.valuation.{discount_rate, terminal_growth, exit_multiple}` → `ValuationInputs` (if HandoffArtifact.valuation has these — plan #2 keeps the v1.0 shape; ModelBuildContext extracts what's there, leaves the rest None).
6. Derive `scenarios`: **start empty dict** (R2 — closes Codex R1 should-fix #2). Catalyst-driven auto-seeding is too speculative for v1 and conflicts with the plan's own §15 risk note that scenarios should start empty until a canonical source exists. Scenarios populated via `overrides` only in v1. Plan #5 (ProcessTemplate) will seed default scenarios per investor process in a later release.
7. Apply `overrides` layer (R2 — explicit list/dict semantics per Codex R1 should-fix #3):
   - **Dict fields** (`drivers`, `scenarios`, nested dicts like `valuation.inputs`): **deep merge**. `overrides.drivers["key1"]` merges into base `drivers["key1"]`; unspecified keys preserved.
   - **List fields** (`historical_sources.overrides`, `segment_config.segment_mapping`, `snapshot.segments`): **replace-whole-list**. User must supply the complete list; partial list overrides are an anti-pattern (too easy to miss entries).
   - **Scalar fields** (`source`, `n_historical`, `n_projection`, `formula_first`, `sector`): replace.
   - **Unknown override keys**: Pydantic validation rejects (no silent ignore).
8. Derive `segment_config`:
   - If `overrides.segment_config` populated → use as-is (Phase 2 will validate).
   - Else → `None` (non-segment build). `build_model` will honor this.
9. Derive `historical_sources`:
   - `default_source`: `overrides.historical_sources.default_source` or `"fmp"` default.
   - Per-concept overrides: `overrides.historical_sources.overrides` or empty.
10. `build_flags`: from `overrides.build_flags` or defaults (`include_historicals=True`, `annotate_with_research=True`, `preview_mode=False`).
11. Validate: run Phase 1 (always). If `segment_config` present, run Phase 2.
12. Persist to `model_build_contexts` table (per §11.3); obtain `mbc_id`.
13. Return `MbcResult(mbc_id=..., mbc=validated_mbc, validation_report=...)`.

**User override precedence**: overrides layer trumps derived values at field granularity. E.g., `overrides.drivers["revenue.segment_1.volume_growth"].value = 0.22` updates that single driver without disturbing others.

### 9.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `AI-excel-addin/api/research/mbc_service.py` | Constructor + overrides merge | ~400 |
| `tests/api/research/test_mbc_service.py` | Constructor tests | ~500 |

### 9.4 Tests (~30)

- Derive MBC from minimal finalized handoff (3)
- Derive MBC from full-populated handoff (4)
- HandoffNotFinalized raised when no finalized (2)
- Per-field override precedence (5)
- Overrides add new scenarios not in handoff (2)
- Fiscal axis defaulting + overrides (3)
- Category C drivers derive correctly (3)
- Segment-mode: segment_config provided via overrides → validates (3)
- Invalid overrides: Pydantic rejection (3)
- Phase 1 + Phase 2 run inside constructor (2)

### 9.5 Acceptance gate

- All tests pass.
- Derived MBC passes both validation phases on well-formed v1.1 handoffs.
- Overrides layer is ergonomic (dict-based, dot-path OK but not required).

### 9.6 Rollback

Delete the two files. Callers can't construct MBC; block on G.

---

## 10. Sub-phase F — `build_model()` behavior change

### 10.1 Goal

Honor `segment_profile_snapshot` verbatim when supplied. Remove re-discovery branch for snapshot-authoritative builds. Per §10.2, `build_model()` itself gains only a narrow `mbc_segment_config: SegmentConfig | None = None` parameter; MBC-driven scalar calls flow through the new `build_model_from_mbc(mbc)` wrapper. Legacy `build_model()` signature (required args + existing optional defaults) is preserved unchanged.

### 10.2 Design

Current `build_model()` signature at `AI-excel-addin/schema/build.py:496`:

```python
def build_model(
    ticker, company_name, fiscal_year_end, most_recent_fy,
    output_path=None, source="fmp", fmp_data=None, sector=None,
    n_historical=5, n_projection=12,
    formatter=None, edgar_fetcher=None, segment_mapping=None,
    edgar_financials_fetcher=None, axis=None, formula_first=True,
) -> BuildResult: ...
```

**Plan 3 addition to `build_model()`**: single new optional `mbc_segment_config: SegmentConfig | None = None` parameter (scoped to segment snapshot only). MBC-driven scalars are NOT passed via `build_model()` — the `build_model_from_mbc(mbc)` wrapper handles that.

**Signature after plan 3** (R4 — closes Codex R3 high; true backward compat via wrapper):

```python
# UNCHANGED from today: required args stay required; defaults preserved verbatim.
def build_model(
    ticker, company_name, fiscal_year_end, most_recent_fy,      # still required
    output_path=None,
    source="fmp",
    fmp_data=None,
    sector=None,
    n_historical=5,
    n_projection=12,
    formatter=None,
    edgar_fetcher=None,
    segment_mapping=None,
    edgar_financials_fetcher=None,
    axis=None,
    formula_first=True,
    # New optional plan 3 addition — internal branch for segment-snapshot mode
    mbc_segment_config: SegmentConfig | None = None,
) -> BuildResult:
    ...
```

`build_model()` keeps its required positional args exactly as today. Calling it with missing required args raises the same `TypeError` it raises today. No legacy caller breaks.

The only new parameter is `mbc_segment_config` — narrow and optional. When present, it triggers the snapshot-authoritative branch inside `build_model()` (skip `discover_all_axes` / `discover_segments` / `apply_segment_overrides`; build `SegmentProfile` from `segment_config.segment_profile_snapshot`).

**New MBC-first wrapper** (R4 — replaces the `None`-defaulting approach):

```python
def build_model_from_mbc(
    mbc: ModelBuildContext,
    *,
    output_path: str | None = None,
    formatter: ModelFormatter | None = None,
    edgar_fetcher: Callable | None = None,
    edgar_financials_fetcher: EdgarFinancialsFetcher | None = None,
    fmp_data: dict | None = None,
) -> BuildResult:
    """MBC-first entry. Derives all scalar args from MBC; delegates to build_model()."""
    return build_model(
        ticker=mbc.company.ticker,
        company_name=mbc.company.name,
        fiscal_year_end=mbc.company.fiscal_year_end,
        most_recent_fy=mbc.company.most_recent_fy,
        output_path=output_path,
        source=mbc.source,
        fmp_data=fmp_data,
        sector=mbc.sector,
        n_historical=mbc.n_historical,
        n_projection=mbc.n_projection,
        formatter=formatter,
        edgar_fetcher=edgar_fetcher,
        edgar_financials_fetcher=edgar_financials_fetcher,
        axis=None,                              # supplanted by segment_config when present
        segment_mapping=None,                   # supplanted by segment_config when present
        formula_first=mbc.formula_first,
        mbc_segment_config=mbc.segment_config,  # drives snapshot-authoritative branch
    )
```

**Call-site migration**:
- Legacy callers (`build_model_orchestrator.py:77`, `model_engine_mcp_server.py:370`, etc.) — unchanged. Keep passing scalar args.
- MBC-aware callers (the new orchestrator path from §11.4) — call `build_model_from_mbc(mbc)` instead of `build_model(...)`.

**Rationale**: preserves true backward compat (legacy signature untouched — calls still fail with `TypeError` at Python layer if required args missing), while giving MBC callers a clean wrapper with MBC-derived scalars. No sentinel values needed.

**Annotation path update** — `annotate_model_with_research` (from §11.4) gains analogous `annotate_model_with_research_from_mbc(mbc, ...)` wrapper. Legacy `annotate_model_with_research(...)` unchanged.

**Segment branch** (R4 — keyed off `mbc_segment_config` parameter, per revised signature):
- **Snapshot-authoritative segment build** (`mbc_segment_config is not None`): `segment_profile_snapshot` is authoritative. Construct `SegmentProfile` from snapshot (sort by `segment_index` — see blocker #5 fix below). Do NOT call `discover_all_axes`, `discover_segments`, or `apply_segment_overrides`. Run `expand_segments(model, profile)` against snapshot-derived profile.
- **Non-segment build** (`mbc_segment_config is None AND axis is None`): existing non-segment path runs unchanged.
- **Legacy segment build** (`mbc_segment_config is None AND axis is not None`): existing re-discovery branch unchanged for non-MBC callers.

**Guardrails**:
- If `mbc_segment_config is not None AND segment_mapping is not None` → `ValueError("mbc_segment_config supplants the positional segment_mapping parameter")`.
- If `mbc_segment_config is not None AND axis is not None` → `ValueError("mbc_segment_config supplants the positional axis parameter")`.
- `edgar_financials_fetcher` remains allowed alongside `mbc_segment_config` — the fetcher is still used for concept-level historical pulls; the snapshot just bypasses its segment-discovery role.

**Caller inventory** (R2 — per Codex R1 consider note):
- `api/research/build_model_orchestrator.py:77,96` — routed through the new `build_model_from_mbc(mbc)` wrapper (not a direct `build_model` call with an `mbc=` kwarg).
- `mcp_servers/model_engine_mcp_server.py:370` — gains optional `model_build_context_id` path (plan 3 §11).
- `risk_module/actions/research.py:570`, `mcp_tools/research.py:307`, `mcp_server.py:2526`, `agent/registry.py:1080` — higher-level entrypoints; route through build_model_orchestrator so inherit the new MBC path automatically.

**Segment snapshot → SegmentProfile construction** (R2 — closes blocker #5):

```python
# Inside build_model(), when mbc_segment_config is not None:
# sort snapshot.segments by segment_index so SegmentInfo order is deterministic.
sorted_snap = sorted(
    mbc_segment_config.segment_profile_snapshot.segments,
    key=lambda s: s.segment_index,
)

profile = SegmentProfile(
    ticker=ticker,  # required arg, passed in
    segments=[
        SegmentInfo(name=s.name, edgar_member=s.edgar_member,
                    revenue_values=s.revenue_values,
                    volume_label=s.volume_label,
                    price_label=s.price_label)
        for s in sorted_snap
    ],
    source=mbc_segment_config.segment_profile_snapshot.source,
    axis_used=mbc_segment_config.segment_profile_snapshot.axis_used,
    total_revenue_check=mbc_segment_config.segment_profile_snapshot.total_revenue_check,
)
```

Index integrity (no gaps, no duplicates, 1-based complete sequence) is verified at Phase 2 validation — see sub-phase D §8.2 R2 update.

### 10.3 Files to modify

| File | Change |
|---|---|
| `AI-excel-addin/schema/build.py` | Add `mbc_segment_config` parameter + snapshot-authoritative branch; add `build_model_from_mbc(mbc)` wrapper |
| `tests/schema/test_build_model_mbc.py` | New (~400 lines) |

### 10.4 Tests (~22)

- Legacy `build_model(...)` call with no `mbc_segment_config` unchanged (5)
- `build_model_from_mbc(mbc)` wrapper derives scalars from MBC + delegates to `build_model()` (4)
- Segment snapshot honored verbatim via `mbc_segment_config` (2: 2-segment, 5-segment)
- No re-discovery when `mbc_segment_config` present (1: mock `discover_all_axes`, assert not called)
- No re-sort (1)
- No override reapplication (1)
- `mbc_segment_config` + positional `segment_mapping`/`axis` → ValueError (3)
- Phase 1 + Phase 2 pre-run before model loading inside the wrapper (2)
- Category A driver keys resolve via sub-phase C extension (2)
- `formula_first` flag honored via wrapper pass-through (1)

### 10.5 Acceptance gate

- All tests pass.
- Snapshot-mode builds are deterministic (same MBC + same fetcher data → same model hash).
- Legacy (non-MBC) callers unaffected.

### 10.6 Rollback

Revert `build.py` changes. MBC constructed but not consumed by builder; segment-mode builds fall back to pre-plan-3 behavior (re-discovery).

---

## 11. Sub-phase G — MCP tool surface

### 11.1 Goal

Two MCP tools + **persistent MBC storage** (R2 — closes Codex R1 blocker #3): `get_model_build_context(research_file_id, overrides?)` + extended `build_model` + new `model_build_contexts` SQLite table.

### 11.2 Tools

| Tool | Purpose |
|---|---|
| `get_model_build_context` | Construct + validate MBC; persist it; return `MbcResult` (§9.1 — `{mbc_id, mbc, validation_report}`). Errors returned as typed flags. |
| `build_model` (existing MCP tool) | Gains optional `model_build_context_id` arg. Resolves via `mbc_service.get_mbc(mbc_id)` (raises `ModelBuildContextNotFound` on missing row — caller sees the typed error) and dispatches to `build_model_from_mbc(mbc)` wrapper. Keeps legacy scalar-arg path for backward compat. |

### 11.3 Persistence — `model_build_contexts` table (R2 additive)

New table in per-user `research.db` (same pattern as plan #1 / plan #2):

```sql
CREATE TABLE IF NOT EXISTS model_build_contexts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mbc_id TEXT NOT NULL UNIQUE,                    -- UUID4
  user_id TEXT NOT NULL,
  research_file_id INTEGER NOT NULL,
  handoff_id INTEGER NOT NULL,                    -- the HandoffArtifact v1.1 this MBC derived from
  created_at REAL NOT NULL,
  expires_at REAL,                                -- NULL means no expiry; plan 3 default NULL
  mbc_json TEXT NOT NULL,                         -- full ModelBuildContext serialized
  overrides_json TEXT,                            -- user overrides for auditability / reconstruction
  schema_version TEXT NOT NULL DEFAULT '1.0',
  FOREIGN KEY(research_file_id) REFERENCES research_files(id) ON DELETE CASCADE,
  FOREIGN KEY(handoff_id)       REFERENCES research_handoffs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_mbc_research_file ON model_build_contexts(research_file_id);
CREATE INDEX IF NOT EXISTS idx_mbc_handoff       ON model_build_contexts(handoff_id);
```

Schema version: research.db bumps from **v4 (plan #1) → v5 (plan #3)** via `_migrate_schema`. Migration adds the single table + indices.

**Repository API** (added to `ResearchRepository` alongside plan #1/#2 APIs):

```python
def create_mbc(user_id, research_file_id, handoff_id, mbc: ModelBuildContext,
               overrides: dict | None = None) -> dict
def get_mbc(mbc_id) -> dict | None
def list_mbcs_for_handoff(handoff_id) -> list[dict]
def delete_expired_mbcs() -> int  # housekeeping, runs daily via service task
```

**Persisted vs in-process**: no in-process cache. Every `build_model(model_build_context_id=...)` call reads from `research.db`. Simpler, survives process restarts, consistent with plan #2's `HandoffModelRef.model_build_context_id` (which now points at a persisted row, not an ephemeral UUID).

**Reconstruction-on-miss policy** (R6 — reconciles §11.4 re-annotate path):
- **`mbc_repo.get_mbc(mbc_id)` contract**: strict. If `mbc_id` not found → return None (or `mbc_service.get_mbc` raises typed `ModelBuildContextNotFound` from the service layer when caller wants to treat missing as an error).
- **MCP tool `build_model(model_build_context_id=...)`**: strict. Caller supplied a specific id; `ModelBuildContextNotFound` surfaces to the caller. No silent reconstruction — the caller is responsible for the id they provided.
- **Orchestrator re-annotate path (§11.4)**: tolerant at the orchestrator layer. When handoff's `model_ref.model_build_context_id` points to a deleted/missing row, the orchestrator catches `ModelBuildContextNotFound` from its own `mbc_service.get_mbc()` call and falls back to fresh construction via `mbc_service.get_model_build_context(research_file_id, overrides=None)`. Logs the fallback for observability.
- Separation of concerns: the repository contract stays strict (no implicit reconstruction); higher-level orchestrator policies can catch + fall back as appropriate for their workflow. §11.2 tool table uses `mbc_service.get_mbc`; the repo-layer `mbc_repo.get_mbc` is an internal implementation detail of the service.

### 11.4 Threading MBC through assumption writes (R2 — closes Codex R1 blocker #4)

Plan 3 adds a new wrapper `annotate_model_with_research_from_mbc(mbc, handoff_id, user_id, ...)` — the legacy `annotate_model_with_research()` signature stays unchanged (mirrors the `build_model` / `build_model_from_mbc` split in §10):

```python
# UNCHANGED from today — legacy signature preserved:
def annotate_model_with_research(
    model_path: str,
    handoff_id: int,
    user_id: int,
    model: FinancialModel | None = None,
) -> dict[str, Any]: ...  # tolerant-skip from artifact.assumptions[]

# NEW wrapper:
def annotate_model_with_research_from_mbc(
    mbc: ModelBuildContext,
    model_path: str,
    handoff_id: int,
    user_id: int,
    *,
    model: FinancialModel | None = None,
) -> dict[str, Any]:
    """MBC-first annotation. Writes mbc.drivers to the workbook; pre-validated driver_keys
       are asserted (never silently skipped). Delegates cell-address resolution to the
       existing resolve_driver_cells path, same as legacy."""
```

Behavior:
- **Legacy path** (unchanged): `annotate_model_with_research(...)` reads `artifact.assumptions[]` from handoff and writes via `resolve_driver_cells` with tolerant-skip on unresolvable keys (preserves existing production behavior at `annotate.py:82-86`).
- **MBC-first path** (new wrapper): `annotate_model_with_research_from_mbc(mbc, ...)` reads `mbc.drivers` instead of `artifact.assumptions[]`. Every `driver_key` was pre-validated at MBC construction; any resolution failure at this stage is a programming error (raises, not skips). Writes use `mbc.drivers[key].value / periods` per driver entry.

**Call-site migration**: orchestrator (§11.4) calls the wrapper when an MBC is acquired/reloaded; legacy call sites (re-annotate fallback for pre-plan-3 handoffs) keep the bare function.

**Concrete MBC acquisition + reload path** (R3 — closes Codex R2 high #1):

1. **Initial build** — entry via `routes.py:676` (REST) → `build_model_orchestrator.build_model_flow(research_file_id, user_id, ...)`:
   - Orchestrator's first step (new, inserted at `build_model_orchestrator.py:63` pre-existing entry): call `mbc_service.get_model_build_context(research_file_id, overrides)` which **constructs + persists** a new MBC row. Returns `MbcResult(mbc_id, mbc, validation_report)`.
   - Orchestrator calls `build_model_from_mbc(result.mbc, ...)` AND `annotate_model_with_research_from_mbc(result.mbc, ...)` — both wrappers consume MBC; legacy `build_model()` / `annotate_model_with_research()` are NOT called on the MBC-first path.
   - On successful build, orchestrator writes `HandoffArtifact.model_ref.model_build_context_id = result.mbc_id` via plan #2 Handoff-only write path (`update_handoff_artifact`). This persists the linkage so re-annotation can reload the exact same MBC.

2. **Re-annotate** — entry via `routes.py` re-annotation endpoint → `build_model_orchestrator.re_annotate_model_flow(research_file_id, user_id)` (existing at `build_model_orchestrator.py:125` retry area; extended):
   - Read finalized HandoffArtifact. Extract `handoff.model_ref.model_build_context_id`.
   - If `model_build_context_id` present: call `mbc = mbc_service.get_mbc(mbc_id)`. The service layer raises typed `ModelBuildContextNotFound` if the row is missing; the orchestrator **catches it explicitly** and falls back to fresh construction via `mbc_service.get_model_build_context(research_file_id)` (same as the initial-build path). Orchestrator logs the fallback.
   - If `model_build_context_id` absent on the handoff (legacy pre-plan-3 handoff): skip the MBC path entirely and call bare `annotate_model_with_research(...)` (tolerant-skip preserved).
   - With MBC in hand → call `annotate_model_with_research_from_mbc(mbc, ...)` wrapper. When no MBC (legacy fallback) → bare `annotate_model_with_research(...)`. Never pass `mbc=` to the bare legacy function — legacy signature has no such kwarg per §11.4.

**Service vs repository layering**: orchestrator always calls the **service layer** (`mbc_service.get_mbc`) — never the repository directly. Service raises typed errors; repository returns None. MCP tool (§11.2) also uses `mbc_service.get_mbc` for consistency; the `mbc_repo.get_mbc` reference in the §11.2 tools table is an internal detail (service → repo). This keeps the error-contract boundary clean.

3. **Ownership**:
   - `mbc_service.get_model_build_context()` owns construction + persistence.
   - `build_model_orchestrator` owns the acquisition-or-reload decision + passing to downstream.
   - `mbc_repo` owns the table CRUD.
   - Plan #2's `HandoffArtifact.model_ref` is the durable cross-snapshot pointer; plan 3 writes the `model_build_context_id` field there on successful build.

Sub-phase **I** (orchestrator + annotate threading) covers all three paths above. ~2 days (upsized from R2's 1 day; reflects annotation pass-through + handoff write-back).

### 11.5 Design — MCP tool surface

`get_model_build_context` lives in `risk_module/mcp_tools/model_build_context.py` + `risk_module/actions/model_build_context.py` (gateway proxy to AI-excel-addin backend). Pattern matches existing research tools.

`build_model` MCP tool in `risk_module/mcp_tools/research.py`: accepts new optional `model_build_context_id` parameter. When supplied, the delegation target resolves the MBC via **`mbc_service.get_mbc(mbc_id)`** (which raises typed `ModelBuildContextNotFound` on missing row) and dispatches to `build_model_from_mbc(mbc, ...)` wrapper. Orchestrator-layer tolerance to missing rows (re-annotate fallback) is applied in the orchestrator, not in the service/repository.

### 11.4 Files to create / modify

| File | Change |
|---|---|
| `risk_module/mcp_tools/model_build_context.py` | New MCP tool (~200) |
| `risk_module/actions/model_build_context.py` | Gateway action proxy (~150) |
| `risk_module/mcp_server.py` | Register `get_model_build_context` (~10) |
| `risk_module/mcp_tools/research.py` | Extend `build_model` to accept `model_build_context_id` (~50) |
| `AI-excel-addin/api/research/mbc_service.py` (from E) | exposes `get_mbc(mbc_id)` (delegates to `mbc_repo.get_mbc`) for orchestrator + MCP callers |
| `tests/mcp_tools/test_model_build_context_tool.py` | New (~300) |

### 11.5 Tests (~18)

- `get_model_build_context` happy path (3)
- Overrides passed through to constructor (3)
- Validation errors surfaced as typed flags (5)
- `build_model` with `model_build_context_id` loads persisted MBC from DB (3)
- `ModelBuildContextNotFound` raised on missing `mbc_id` (2)
- `build_model` legacy path unchanged (2)

### 11.6 Acceptance gate

- All tests pass.
- MBC tools discoverable in MCP catalog.
- Typed errors surface through gateway unchanged.

### 11.7 Rollback

Revert MCP + action + server changes; delete MBC tool files. `build_model` legacy path still works.

---

## 12. Sub-phase H — SKILL_CONTRACT_MAP.md updates

### 12.1 Goal

Reflect plan 3 in the skill integration map.

### 12.2 Specific edits to `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md`:

- **§"Primary reference" contracts table**: `ModelBuildContext` row Location: drop `(planned)` → `schema/model_build_context.py`.
- **§"Analysis skills" table**: `/build-model` row — typed output column now explicitly reads: "Consumes `ModelBuildContext` (constructed from HandoffArtifact v1.1 via `get_model_build_context`). Produces `FinancialModel` + `ModelInsights` + `PriceTarget` (ModelInsights/PriceTarget from plan #6). Updates `Thesis.model_ref` (Thesis-shaped) + `HandoffArtifact.model_ref` (Handoff-shaped, via plan #6)."
- **§"Analysis skills" table**: `/assumption-audit` → clarify it consumes MBC-derived driver values for comparison, not the raw HandoffArtifact assumptions.
- **§"Cross-repo references" table**: add row for `AI-excel-addin/schema/templates/driver_mapping.yaml` (plan 3 extends with literal segment-aware entries + `unsupported_in_segment_mode` list).

### 12.3 Acceptance gate

- Map edits land in the same PR as sub-phase G.
- No stale `(planned)` references to `ModelBuildContext`.

---

## 13. Testing summary

- Unit tests per sub-phase: ~175 total.
- Integration: HandoffArtifact v1.1 → MBC → build_model → FinancialModel end-to-end (MBC-driven vs legacy-path equivalence on non-segment builds).
- Determinism: same MBC input → same model output hash (golden fixtures).
- Segment-mode: 3-segment snapshot → deterministic 3-segment model.

---

## 14. Rollout sequencing

**Week 1**: A (2 days) + C (3 days). A gates the rest; C takes the longest and is non-blocking for B.
**Week 2**: B (2 days) + D (3 days) + E starts (3 days). E depends on plan #2 implementation landing — may start week 2 or 3 depending on plan #2 timing.
**Week 3**: F (3 days) + E completes + G starts (2 days).
**Week 4**: G completes + H (0.5 day) + integration smoke (2 days).

Total: ~18.5 working days with parallelism. Slack for plan #2 dependency.

---

## 15. Risks

| Risk | Mitigation |
|---|---|
| Plan #2 implementation drifts from plan #2 PASS shape during its rollout | Plan #2's boundary test (plan 2 §10) catches shared-slice drift; MBC constructor (sub-phase E) reads only the shared-slice fields of HandoffArtifact v1.1, which are locked via isomorphism invariant. |
| `driver_mapping.yaml` rework breaks existing (non-segment) callers | YAML changes are backward-compatible: existing fully-qualified keys preserved alongside new literal segment_N entries; new top-level `unsupported_in_segment_mode` list is additive (ignored by callers that don't consume it). Tests cover both paths. |
| `build_model()` snapshot-authoritative path diverges from discovery results on stale snapshots | Snapshot captured at MBC construction; MBC persisted in `model_build_contexts` table with `expires_at` NULL by default (no automatic expiry). Stale snapshots manifest only if the underlying EDGAR segment data changes between construction and build — rare in the normal minutes-to-hours build flow. Mitigation: analyst/agent calls `get_model_build_context(research_file_id, overrides)` fresh when they want a current snapshot; the persisted row from a prior call remains available for re-annotation to preserve determinism across build + re-annotate. Housekeeping: `delete_expired_mbcs()` task sweeps rows with non-null `expires_at` in the past (opt-in; plan 3 default is no expiry). |
| Category B driver_keys in existing handoffs cause **hard failure** on first MBC-driven build (R2 — honest per Codex R1 should-fix #5) | **This is a hard break, not non-breaking.** Any segment-mode handoff containing `revenue.segment_N.operating_metric` or `revenue.segment_N.revenue` assumptions will fail MBC construction. Mitigation is **audit + migration**, not compatibility: (1) plan 3 ships an audit tool (`mbc_service.audit_handoffs_for_unsupported_drivers(user_id) -> list[UnsupportedDriverReport]`) that scans all existing finalized handoffs and lists B1/B2 assumptions by `(handoff_id, driver_key, reason)`; (2) analyst reviews the report and uses `HandoffPatchOp` (plan #6) or direct Thesis edits to remove/replace the affected assumptions; (3) legacy (non-MBC) `build_model` path remains available as explicit opt-out for any handoff where migration isn't feasible. Plan 3 acceptance gate includes running the audit on test fixtures + an "opt-out with deprecation warning" code path. |
| `annotate.py` tolerant-skip behavior masks MBC validation failures | Plan 3 replaces the tolerant skip with an `assert` that all driver_keys in the artifact were pre-validated by MBC. Regression: old (non-MBC) callers still get tolerant skip. |
| Workspace-derived scenarios (sub-phase E step 6) have no canonical source | Start with empty scenarios dict; override-driven. Plan #5 (ProcessTemplate) will establish default scenario templates per investor process. |

---

## 16. Acceptance gate

- All 8 sub-phases committed, tests green.
- `schema/model_build_context.py` (Pydantic type), `mbc_service.py` (constructor + validators + persistence), extended `build.py` (adds `mbc_segment_config` param + `build_model_from_mbc(mbc)` wrapper; legacy `build_model()` signature unchanged), extended `annotate.py` (adds `annotate_model_with_research_from_mbc(mbc)` wrapper; legacy unchanged), `driver_mapping.yaml` extended with literal segment-aware entries + top-level `unsupported_in_segment_mode` list, MCP tool in `risk_module/mcp_tools/model_build_context.py`.
- **Determinism comparator** (R2 — per Codex R1 should-fix #6): MBC-driven builds produce the same `FinancialModel` as legacy builds for non-segment cases. Comparator = **canonicalized FinancialModel dump**: serialize both models via `FinancialModel.model_dump(mode="json")` with dict keys sorted and floats rounded to 6 decimals, then assert equality. NOT workbook bytes (openpyxl is non-deterministic on cell styling). NOT opaque hashes. Explicit JSON diff for test failure output.
- `SKILL_CONTRACT_MAP.md` updated.
- End-to-end smoke: `finalize_handoff` on a research file → `get_model_build_context` → `build_model_from_mbc(mbc)` → `FinancialModel` written; `annotate_model_with_research_from_mbc(mbc)` populates the workbook.

---

## 17. Out of scope

- `ModelInsights` + `PriceTarget` + `HandoffPatchOp` (plan #6).
- EDGAR vs FMP request-time wiring through `populate_historicals` (plan #8; plan 3 exposes the MBC field, plan #8 wires it).
- ProcessTemplate-driven scenario seeding (plan #5).
- Frontend MBC preview UI.
- MBC versioning across template schema changes (future — when `template_version` populates per plan #1 §6.6).

---

## 18. Follow-on (post-plan-3)

- Plan #6 (ModelInsights/PriceTarget/HandoffPatchOp) consumes MBC-derived model outputs.
- Plan #8 (EDGAR/FMP precedence) wires `mbc.historical_sources` through `populate_historicals` at `schema/build.py:262`.
- Plan #5 (ProcessTemplate) seeds default scenarios per investor process into MBC constructor defaults.
