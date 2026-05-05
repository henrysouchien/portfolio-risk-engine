# EDGAR / FMP Source Precedence — Implementation Plan

**Status**: **SHIPPED 2026-04-28** — R5 PASS plan preserved for historical reference.
**Created**: 2026-04-27
**Closes**: G8 from `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md`
**Depends on**:
- ModelBuildContext (SHIPPED) — `docs/planning/completed/MODEL_BUILD_CONTEXT_PLAN.md`
- HandoffArtifact v1.1 (SHIPPED) — `docs/planning/completed/HANDOFF_ARTIFACT_V1_1_PLAN.md`

## R4 → R5 changelog

- **§6.2 blocker fix.** R4 §6.2 had `build_model()` re-promoting `historical_sources=None` to `HistoricalSources(default_source=source)` — the exact pattern R4's architectural split was supposed to remove. Codex caught it. R5: `build_model()` passes `historical_sources` through unchanged (including `None`); `populate_historicals` does the legacy/routed dispatch (§5.4). End-to-end legacy preservation.
- **§2 phase B summary cleanup.** R4 left `_reconcile_mbc_routing()` named in the phase summary even though R4's architectural split removed the helper. R5 updated.
- **§1 in-scope reconciled with §6.5.** R4 in-scope said "replace warning" but §6.5 said "keep warning for legacy mode." R5 in-scope updated to match §6.5.
- **§1 routed-path infrastructure-failure behavior defined.** Codex should-fix: fallback only masks per-concept missing data, NOT infrastructure failures (matches today's `populate_from_edgar` semantics — when the EDGAR API itself fails, the build raises through).

## R3 → R4 changelog

- **§4.4 + §5.4 + §6.3 architectural fix (R3 blocker #2/#3).** R3 promoted legacy `source` to `HistoricalSources(default_source=source)` then applied layered precedence — but taxonomy layer can then override the caller's explicit `source="edgar"`, so `gross_profit` (taxonomy=`fmp`) routes to FMP for a caller who said EDGAR. Behavior change for legacy callers — Codex flagged correctly. R4 fix: split legacy and routed code paths. **Legacy path** (`historical_sources is None`) calls today's `populate_from_fmp` / `populate_from_edgar` directly — no resolver, no taxonomy routing, behavior identical to today. **Routed path** (`historical_sources` supplied) uses new resolver + buffers + layered precedence. Branch by presence of `historical_sources`, not by promotion. Reconciliation in `build_model_from_mbc` becomes "is `historical_sources` at defaults? → legacy path; else → routed path." Removes the `_reconcile_mbc_routing` helper from R3.
- **§5.2 BuildSource cast fix (R3 blocker #1).** `BuildSource = Literal["fmp", "edgar"]`, not an enum. R3's `BuildSource(taxonomy_concept.preferred_source)` raises `TypeError: Cannot instantiate typing.Literal` (Codex executed). R4 uses explicit membership check + `typing.cast()`.
- **§5.3 FmpConceptFetchResult per-year provenance (Codex should-fix).** R3's `fmp_field_used: str | None` was too coarse — primary `fmp_field` may serve some years and `fallback_fmp_field` may serve others. R4 uses `field_used_by_year: dict[int, str]` for per-year granularity.
- **§5.3 EDGAR provenance description corrected (Codex should-fix).** R3 said EDGAR result tracks "which `edgar_tags[i]` ultimately served." Actual shape is per-year via `EdgarConceptFetchResult.provenance_by_year`. R4 corrected.

## R2 → R3 changelog

- **§6.3 reconciliation fix (R2 blocker #1).** R2's `model_fields_set` check fails for service-created MBCs because `mbc_service._build_base_payload()` always injects `historical_sources` defaults — Codex executed this and verified. R3 fix: stop the service from injecting `historical_sources` defaults; let Pydantic supply them. `model_fields_set` then becomes a meaningful signal for reconciliation. Adds `mbc_service.py` to phase B's modified files.
- **§4.5b hard-enforcement (R2 blocker #2).** R2 had `fallback_order[0] == preferred` as a soft warn. Codex: "dispatcher walks `fallback_order`, not `primary`. If they disagree, routing and telemetry diverge." R3: Pydantic validator on `HistoricalSourceOverride` HARD-RAISES if `fallback_order[0] != preferred`. No soft mode. Caller intent must be unambiguous.
- **§5.3 buffer shape (R2 blocker #3).** R2's `ConceptDataBuffer` had only `values` + `error`. Insufficient — current `populate_from_edgar()` tracks provenance, partial-failure status, per-year failures, API call counts via existing `EdgarConceptFetchResult`. R3 reuses `EdgarConceptFetchResult` for EDGAR buffer + introduces parallel `FmpConceptFetchResult` for FMP. Both feed into `_write_routed_historicals()` which threads provenance into `_set_imported_value` / `_set_constant_override`.
- **§7 CLI dropped (R2 blocker #4).** Codex: `AI-excel-addin/schema/tools_cli.py` is model-inspection only (summarize/find/drivers/sensitivity/scenario) — no `build_model` CLI exists today. Per "don't defer to dodge friction" rule, R3 kills CLI from scope rather than expanding it. Phase C is now MCP-only. CLI as a separate plan if/when needed.
- **§5.2 explicit cast (Codex should-fix).** `DataSourceMapping.preferred_source` is typed `Optional[str]`, not `BuildSource`. R3 explicitly casts/validates: `BuildSource(taxonomy_concept.preferred_source)` raises `ValueError` on unrecognized strings rather than relying on downstream Pydantic.
- **§4.5 telemetry semantics (Codex should-fix).** R2's `fallback_used` comment was wrong: full-ordered-list semantics make it `actual_index_used > 0`, not `served_by != requested_primary`. R3 corrected.
- **§4.1 layering wording (Codex should-fix).** R2's "highest-precedence layer that addresses the concept" was loose because MBC default always addresses every concept. R3 reframes as explicit precedence chain: `MBC override > taxonomy concept-default (when present) > MBC build-wide default`.
- **§5.6 PopulateStats type (Codex should-fix).** R2 changed `PopulateStats` to `BaseModel`. It's currently a dataclass — R3 keeps dataclass, adds `source_resolution: list[SourceResolutionEntry] = field(default_factory=list)`.
- **§6.3 snippet scope (Codex should-fix).** R3 includes `load_data_taxonomy()` import in the `build_model_from_mbc()` reconciliation snippet so taxonomy is in scope for eligibility validation.

---

**Related code** (same as R2, repeated for self-contained reading):
- `AI-excel-addin/schema/model_build_context.py:158-190` — shipped `HistoricalSources` + `HistoricalSourceOverride` + MBC field
- `AI-excel-addin/schema/build.py:247-308` — `populate_from_fmp()`
- `AI-excel-addin/schema/build.py:311-480` — `populate_from_edgar()` (uses `EdgarConceptFetchResult`)
- `AI-excel-addin/schema/build.py:356` — current `preferred_source` warning (replaced by routing telemetry per §6.5)
- `AI-excel-addin/schema/build.py:525-550` — `populate_historicals()` (the global-source switch)
- `AI-excel-addin/schema/build.py:680` — segment-mode source forcing site #2
- `AI-excel-addin/schema/build.py:775` — diagnostic field (EDGAR-only — telemetry belongs elsewhere)
- `AI-excel-addin/schema/build.py:809-841` — `build_model_from_mbc()` (ignores `historical_sources` today)
- `AI-excel-addin/schema/build.py:~1561` — `_set_imported_value` / `_set_constant_override` (mutation entry — only `_write_routed_historicals` may call these)
- `AI-excel-addin/schema/models.py:189-204` — `DataSourceMapping.preferred_source: Optional[str]`
- `AI-excel-addin/schema/handoff.py:104` — `HandoffArtifactV1_1.financials.source` (only routing surface in shipped artifact)
- `AI-excel-addin/api/research/mbc_service.py:193` — `get_model_build_context()` + `_build_base_payload()` (R3 modifies to NOT inject `historical_sources` defaults)
- `AI-excel-addin/schema/templates/data_taxonomy.json` — bundled taxonomy registry
- `AI-excel-addin/schema/templates/__init__.py:40-67` — `load_data_taxonomy()`
- `AI-excel-addin/mcp_servers/model_engine_mcp_server.py:344-372` — `model_build` MCP tool (segment-mode forces `source="edgar"` at line 370)

---

## 1. Purpose & scope

The shipped `ModelBuildContext.historical_sources` field is **dead code**: `build_model_from_mbc()` ignores it and passes only `mbc.source` (a global string) downstream. The Pydantic contract exists; the runtime doesn't honor it.

This plan wires `historical_sources` into the build pipeline so that:

1. **A single build can mix sources.** FMP for normalized statements, EDGAR for company-specific concepts (segment revenue, custom XBRL tags). Today's global `source` flag forces all-or-nothing.
2. **Cross-source fallback executes.** When the preferred source returns no data for a concept, the build tries the next source in `fallback_order` automatically.
3. **Callers override at request time via MCP.** `model_build` accepts a `historical_sources` parameter.
4. **Source resolution is observable.** Per-concept `{requested_primary, served_by, fallback_used}` telemetry on `PopulateStats.source_resolution`.

### Headline framing
This plan **enables mixed-source builds in a single run** — it is not an API-cost optimization. Decision: bulk-fetch both sources every build (when routing could touch either). No demand-driven fetch optimization in v1.

### In scope
- Routing resolver (pure function, three-layer precedence)
- `populate_historicals()` refactor — split fetch from write, route per-concept, fallback execution, per-concept telemetry baked into return shape
- Reuse `EdgarConceptFetchResult` for EDGAR buffer; introduce `FmpConceptFetchResult` for FMP (parallel shape with FMP-specific telemetry)
- `build_model_from_mbc()` dispatches: legacy path when `historical_sources` is at Pydantic defaults (passes `mbc.source` through unchanged), routed path when supplied (made distinguishable via service-payload fix)
- `build_model()` accepts an optional `historical_sources` parameter alongside the existing `source: str` (additive, non-breaking; `None` preserved through to populate dispatch)
- `mbc_service._build_base_payload()` change: stop injecting `historical_sources` defaults so `model_fields_set` is meaningful
- Pydantic validator on `HistoricalSourceOverride`: hard-enforces `fallback_order[0] == preferred`
- Eligibility validation at service entry + build entry (hard-fail on ineligible explicit overrides)
- MCP `model_build` accepts a `historical_sources` parameter
- Segment-mode coupling: ensure routing isn't overwritten by source-force at `build.py:680` and `model_engine_mcp_server.py:370`; ensure EDGAR fetcher is created whenever routing touches EDGAR
- Existing `build.py:356` warning kept for legacy mode (still useful when `source="edgar"` is explicitly chosen against taxonomy preference); routed mode replaces it with `SourceResolutionEntry` telemetry — see §6.5
- Routed-path EDGAR infrastructure-failure behavior: when fetching the EDGAR buffer raises (e.g., API down, auth failure), the routed path raises through — fallback only masks per-concept missing data, NOT infrastructure failures (matches today's `populate_from_edgar` semantics)
- Tests covering routing, fallback, eligibility, legacy/routed dispatch, segment-mode interaction, validator enforcement, infrastructure-failure behavior, and telemetry shape

### Out of scope
- **`DataSourceMapping` registry redesign.** `data_taxonomy.json` `preferred_source` stays as the **base layer**; MBC routing layers on top.
- **Removing the segment-mode forced-source-EDGAR rule.** Coexistence is in scope; removal is its own plan.
- **Caching** across builds or across sources.
- **Demand-driven fetch optimization** — see headline.
- **HandoffArtifact v1.1 → MBC routing-block expansion** — separate v1.2 schema plan.
- **CLI surface for `build_model`.** No `build_model` CLI exists today; `tools_cli.py` is model-inspection only. MCP is the request-time surface for v1. CLI is a separate plan if needed.

---

## 2. Sub-phase summary

| Phase | Goal | Primary new surface |
|---|---|---|
| A | Routing resolver + populate refactor + telemetry. Resolver pure function; `populate_historicals` split into fetch (returns per-source `*ConceptFetchResult` buffers) + write (consumes buffers + routing); fallback execution; `PopulateStats.source_resolution` populated. Pydantic validator on `HistoricalSourceOverride`. | `resolve_source_for_concept()`, `validate_route_eligibility()`, `_fetch_fmp_concept_buffer()`, `_fetch_edgar_concept_buffer()`, `_write_routed_historicals()`, `FmpConceptFetchResult`, `SourceResolutionEntry` |
| B | Wire `historical_sources` through `build_model_from_mbc()` → `build_model()` via legacy/routed dispatch (§4.4). `mbc_service._build_base_payload()` stops injecting `historical_sources` defaults so `model_fields_set` is meaningful. Eligibility validation at service + build entry. | `historical_sources` parameter plumbing (passed through unchanged, including `None`); service-payload change; eligibility check call sites |
| C | Request-time surface — MCP `model_build` `historical_sources` param; ensure EDGAR fetcher creation triggers on any routed-to-EDGAR concept | MCP tool param + EDGAR-fetcher trigger fix |
| D | Integration tests — cross-source builds, fallback paths, back-compat (existing `source: str` callers, including service-created MBCs), segment-mode coexistence, eligibility hard-fail, validator enforcement | new + existing tests |

---

## 3. Dependency graph

```
A (resolver + populate + telemetry + validator)
  └── B (MBC wiring + service-payload fix + eligibility)
        └── C (MCP surface)
              └── D (integration tests)
```

Linear chain. Per-phase unit tests inline.

---

## 4. Cross-cutting concerns

### 4.1 Additive layering — explicit precedence chain (R3 — tightened wording)

**Precedence (highest → lowest)**:
1. **MBC `overrides[concept_id]`** — per-concept request-time pin. Wins unconditionally.
2. **Taxonomy concept-default** — `DataSourceMapping.preferred_source` from `data_taxonomy.json`. Concept-aware data-quality knowledge. Used when no override addresses this concept AND the taxonomy entry has a non-null `preferred_source`.
3. **MBC `default_source`** — build-wide catch-all. Used when neither override nor taxonomy default applies.

**Resolution rule**: walk top-down; first layer that produces a route wins. `fallback_order` is **only** populated from layer 1 (overrides); layers 2 and 3 produce single-source routes (`fallback_order = [primary]`).

Note: this matches parent design doc §6.3 ("Layered on concept-level preferred_source") — taxonomy carries concept-aware knowledge; MBC build-wide default is the catch-all for concepts with no taxonomy preference.

### 4.2 Concept eligibility — hard-fail explicit overrides; soft-skip default routes

Two cases:

**Case 1 — explicit override.** `historical_sources.overrides[]` names a concept and a source the concept can't serve (e.g., overrides `revenue` to EDGAR but the concept has no `edgar_tags`). Typed error: `UnsupportedSourceForConcept`. Raised at service entry + build entry.

**Case 2 — default route.** Layer-2 (taxonomy) or layer-3 (MBC default) picks a source the concept can't serve. Validation can't happen until template + segment expansion materializes the concept set. Lives in the populate path; logs warning, treats concept as missing, no hard-fail.

**Validation location**: NOT in Pydantic `ModelBuildContext` (no taxonomy hookup). Lives in:
- `api/research/mbc_service.py:get_model_build_context()` — service-entry validation for persisted MBCs
- `build.py:build_model_from_mbc()` entry — direct-call validation
- The populate path itself for default-route case-2

Shared `validate_route_eligibility(route, taxonomy_concept, *, is_explicit_override: bool)` helper in `schema/source_routing.py`.

### 4.3 Always-both bulk fetch
Decided 2026-04-27. Pre-resolve routing across all model concepts; compute the union of sources required (primary OR fallback). Fetch only those sources. Empty/default routing preserves today's single-source behavior.

### 4.4 Backward compatibility — legacy / routed code-path split (R4)

**Foundational rule (R4)**: legacy callers (those passing `source: str` and not `historical_sources`) hit a code path that **does NOT touch the resolver, layered precedence, or taxonomy routing**. They get today's `populate_from_fmp` / `populate_from_edgar` behavior identically. Routed callers (those passing `historical_sources`) hit the new resolver + buffer + dispatch flow.

This avoids the R3 mistake of promoting `source` into a default `HistoricalSources` and then letting taxonomy override it — which would silently change behavior for `source="edgar"` callers (e.g., `gross_profit` would route to FMP).

**Layer 1 — `populate_historicals(source=, historical_sources=None, ...)` dispatch**:
```
if historical_sources is None:
    # LEGACY PATH — single-source, today's behavior, no taxonomy routing
    if source == "fmp": return populate_from_fmp(model, fmp_data, taxonomy)
    if source == "edgar": return populate_from_edgar(model, ticker, taxonomy, edgar_fetcher)
else:
    # ROUTED PATH — resolver + buffers + layered precedence + fallback
    return _populate_routed(model, historical_sources, ...)
```

If both `source` and `historical_sources` are passed → routed path wins; `source` ignored (debug log).

**Layer 2 — `build_model(source=, historical_sources=None, ...)`**: same dispatch. Threaded through to `populate_historicals`.

**Layer 3 — `build_model_from_mbc(mbc, ...)` dispatch**:
```
is_default_hs = "historical_sources" not in mbc.model_fields_set
if is_default_hs:
    # LEGACY PATH — pass mbc.source through, no routing
    return build_model(..., source=mbc.source, historical_sources=None, ...)
else:
    # ROUTED PATH — eligibility check + threaded routing
    validate_route_eligibility(...)  # for each override
    return build_model(..., source=mbc.source, historical_sources=mbc.historical_sources, ...)
```

For this dispatch to work, `mbc.model_fields_set` must accurately reflect whether `historical_sources` was supplied by the caller. Phase B's §6.4 service-payload change is the prerequisite: `mbc_service._build_base_payload()` must NOT inject `historical_sources` when overrides don't supply it.

**Layer 4 — MCP `model_build`**:
Existing `source` param stays. `historical_sources` additive optional. Both passed → `historical_sources` wins, conflicting `source` logged as warning.

**Layer 5 — `data_taxonomy.json`**: unchanged.

**Net effect for back-compat**: `populate_historicals(source="edgar")` and `build_model(source="edgar")` behave EXACTLY as today (no routing, no taxonomy override). Routed mode is opt-in via `historical_sources`.

### 4.5 Telemetry shape (`PopulateStats.source_resolution`)

```python
@dataclass
class SourceResolutionEntry:
    concept_id: str
    requested_primary: BuildSource
    requested_fallback_order: list[BuildSource]  # full ordered list per §4.5b
    layer_decided: Literal["taxonomy", "mbc_default", "mbc_override"]
    served_by: BuildSource | None  # None when no source had data
    fallback_used: bool            # actual_index_used > 0 (R3 — corrected semantics)
    served_year_count: int
```

Aggregated as `source_resolution: list[SourceResolutionEntry]` on `PopulateStats`.

### 4.5b `fallback_order` convention — HARD-enforced (R3)

**Convention**: `fallback_order` is the **full ordered try-list**, with `preferred` repeated as element [0]. Dispatcher walks the list in order; first source with non-empty data for the concept wins. `served_by` is the source that won; `fallback_used = (actual_index_used > 0)`.

**Enforcement** (R3 — hard, not soft):
Pydantic validator on `HistoricalSourceOverride` raises `ValueError` if `fallback_order[0] != preferred`:
```python
class HistoricalSourceOverride(_ContractModel):
    concept_id: str = Field(min_length=1)
    preferred: BuildSource
    fallback_order: list[BuildSource] = Field(min_length=1)

    @model_validator(mode="after")
    def _enforce_fallback_order_head(self) -> "HistoricalSourceOverride":
        if self.fallback_order[0] != self.preferred:
            raise ValueError(
                f"fallback_order[0] must equal preferred (got {self.fallback_order[0]!r} vs {self.preferred!r})"
            )
        return self
```

This is a small additive validator on the SHIPPED contract. It catches caller mistakes at MBC construction. Existing service test (`fallback_order=["edgar", "fmp"]` with `preferred="edgar"`) passes unchanged.

### 4.6 Segment-mode coexistence

Source forcing at TWO sites:
- `mcp_servers/model_engine_mcp_server.py:370` — MCP entry forces `source="edgar"` when segment discovery requested
- `schema/build.py:680` — build-time forcing (Codex flagged — exact behavior verified during phase B)

**Constraints**:
1. Per-concept routing in `historical_sources` is independent of and additive to the global `source` field. Source forcing must not overwrite routing.
2. MCP entry must create the EDGAR fetcher whenever routing **could touch EDGAR** (default OR any override OR any `fallback_order` mentions edgar) — not only when `source=="edgar"`.
3. Segment-mode forcing rule itself stays put — coexistence in scope, removal not.

---

## 5. Sub-phase A — Resolver + populate refactor + telemetry + validator

### 5.1 Goal
Four things rolled into one phase:
1. Pure-function routing resolver
2. `populate_historicals()` refactored: split fetch from write, route per-concept, execute fallback
3. Per-concept telemetry baked into return shape
4. Pydantic validator on `HistoricalSourceOverride` enforcing `fallback_order[0] == preferred`

### 5.2 Resolver design (R3 — explicit BuildSource cast for taxonomy)
```python
# schema/source_routing.py (new)

from typing import Literal
from pydantic import BaseModel

from schema.model_build_context import HistoricalSources, BuildSource
from schema.models import DataSourceMapping


class ConceptSourceRoute(BaseModel):
    concept_id: str
    primary: BuildSource
    fallback_order: list[BuildSource]  # full ordered list, [0] == primary
    layer_decided: Literal["taxonomy", "mbc_default", "mbc_override"]


class UnsupportedSourceForConcept(ValueError):
    """Raised when explicit override targets a source that cannot serve the concept."""


def resolve_source_for_concept(
    concept_id: str,
    historical_sources: HistoricalSources,
    taxonomy_concept: DataSourceMapping | None,
) -> ConceptSourceRoute:
    # Layer 1: MBC override (highest)
    for ov in historical_sources.overrides:
        if ov.concept_id == concept_id:
            return ConceptSourceRoute(
                concept_id=concept_id,
                primary=ov.preferred,
                fallback_order=list(ov.fallback_order),  # full ordered list
                layer_decided="mbc_override",
            )
    # Layer 2: taxonomy concept-default (if non-null)
    if taxonomy_concept is not None and taxonomy_concept.preferred_source:
        # R4 fix — BuildSource = Literal["fmp", "edgar"], not enum. Membership check + cast.
        from typing import cast, get_args
        raw = taxonomy_concept.preferred_source
        if raw not in get_args(BuildSource):
            raise ValueError(
                f"Taxonomy concept {concept_id!r} has unrecognized preferred_source "
                f"{raw!r} (must be one of {get_args(BuildSource)})"
            )
        primary: BuildSource = cast(BuildSource, raw)
        return ConceptSourceRoute(
            concept_id=concept_id,
            primary=primary,
            fallback_order=[primary],  # single-source route
            layer_decided="taxonomy",
        )
    # Layer 3: MBC default (catch-all)
    primary = historical_sources.default_source
    return ConceptSourceRoute(
        concept_id=concept_id,
        primary=primary,
        fallback_order=[primary],
        layer_decided="mbc_default",
    )


def validate_route_eligibility(
    route: ConceptSourceRoute,
    taxonomy_concept: DataSourceMapping | None,
    *,
    is_explicit_override: bool,
) -> None:
    """Hard-fail explicit overrides with ineligible sources; soft-skip otherwise."""
    # Per §4.2 — case-1 hard-raise UnsupportedSourceForConcept; case-2 caller logs warning
```

Eligibility checks:
- `primary == "fmp"` requires `taxonomy_concept.fmp_endpoint` and `fmp_field` non-null.
- `primary == "edgar"` requires `taxonomy_concept.edgar_tags` non-empty OR `registry_group_id` non-null.
- Each entry in `fallback_order` validated the same way.

### 5.3 Buffer shape — reuse + extend existing types (R3 — Codex blocker #3 fix)

**EDGAR buffer reuses `EdgarConceptFetchResult`** (existing — the structure today's `populate_from_edgar()` builds in its `concept_cache` dict at `build.py:342`). It already carries:
- per-concept fetched data (year → value)
- error / partial-failure status
- per-year provenance via `provenance_by_year` (R4 — corrected from R3's "concept-level tag")
- API call count / failed years

**FMP buffer — new `FmpConceptFetchResult`** with parallel per-year shape:
```python
@dataclass
class FmpConceptFetchResult:
    concept_id: str
    values: dict[int, float]                  # {year: value}; empty if missing
    field_used_by_year: dict[int, str]        # R4 — per-year provenance: which fmp_field served each year
    fallback_field_years: set[int]            # subset of years where fallback_fmp_field served
    missing: bool                             # True when no FMP data for any year
```

Per-year granularity (R4 — Codex should-fix) because primary `fmp_field` may serve some years and `fallback_fmp_field` may fill gaps in others; concept-level "field used" loses that signal.

**Why parallel-not-unified**: each source's per-concept telemetry is shaped differently (FMP has field-level fallback, EDGAR has tag-level fallback). Forcing a single `ConceptDataBuffer` would lose source-specific signal. Keep them parallel; the routing dispatcher reads only `values` from either type for the dispatch decision.

```python
def _fetch_fmp_concept_buffer(
    fmp_data: dict,
    concept_ids: set[str],
    taxonomy: dict[str, DataSourceMapping],
    historical_periods: list[int],
) -> dict[str, FmpConceptFetchResult]:
    """Pure read — fetch FMP per concept, return buffer. NO model mutation."""
    ...

def _fetch_edgar_concept_buffer(
    ticker: str,
    concept_ids: set[str],
    taxonomy: dict[str, DataSourceMapping],
    historical_periods: list[int],
    edgar_fetcher: EdgarFetcher,
) -> dict[str, EdgarConceptFetchResult]:
    """Pure read — wraps existing _fetch_edgar_concept_result; NO model mutation."""
    ...

def _write_routed_historicals(
    model: FinancialModel,
    routes: dict[str, ConceptSourceRoute],
    fmp_buffer: dict[str, FmpConceptFetchResult],
    edgar_buffer: dict[str, EdgarConceptFetchResult],
    taxonomy: dict[str, DataSourceMapping],
) -> tuple[PopulateStats, list[SourceResolutionEntry]]:
    """Per concept: walk fallback_order; first non-empty buffer wins; write to model.

    THIS is the only function in the new code path that may call
    _set_imported_value / _set_constant_override (per Codex overwrite-correctness fix).
    Buffer fetchers above must not mutate the model.
    """
    ...
```

### 5.4 Public API — legacy / routed code-path split (R4)
```python
def populate_historicals(
    model: FinancialModel,
    source: str = "fmp",                                     # KEPT — legacy single-source mode
    historical_sources: HistoricalSources | None = None,     # NEW — routed mode
    *,
    ticker: str,
    taxonomy: dict[str, DataSourceMapping],
    most_recent_fy: int,
    n_historical: int = 5,
    fmp_data: dict | None = None,
    edgar_fetcher: EdgarFetcher | None = None,
) -> PopulateStats:
    """Dispatch to legacy single-source path OR routed path based on whether
    historical_sources is supplied. R4 — back-compat is identity-preserving:
    legacy callers do NOT touch the resolver or taxonomy routing."""

    if historical_sources is not None:
        # Routed path — new behavior
        if source != "fmp":
            _logger.debug(
                "populate_historicals: both source=%s and historical_sources passed; using routed",
                source,
            )
        return _populate_routed(
            model, historical_sources, ticker=ticker, taxonomy=taxonomy,
            most_recent_fy=most_recent_fy, n_historical=n_historical,
            fmp_data=fmp_data, edgar_fetcher=edgar_fetcher,
        )

    # Legacy path — today's behavior, identical
    if source == "fmp":
        if fmp_data is None:
            raise ValueError("fmp_data is required when source='fmp'")
        return populate_from_fmp(model, fmp_data, taxonomy)
    if source == "edgar":
        if edgar_fetcher is None:
            raise ValueError("edgar_fetcher is required when source='edgar'")
        return populate_from_edgar(model, ticker, taxonomy, edgar_fetcher)
    raise ValueError(f"Unsupported source: {source}")


def _populate_routed(
    model, historical_sources, *, ticker, taxonomy, most_recent_fy, n_historical,
    fmp_data, edgar_fetcher,
) -> PopulateStats:
    # 1. Walk model items, build {concept_id: route} via resolver
    # 2. Determine union of sources actually needed (primary OR fallback per route)
    # 3. Fetch only required source(s) into buffers — buffer fetchers are pure read
    # 4. _write_routed_historicals — per concept, walk fallback_order
    # 5. Return PopulateStats(source="routed", source_resolution=[...])
```

**`populate_from_fmp` and `populate_from_edgar` are kept as today** (no changes to their internals) — the legacy path calls them directly. They are NOT wrappers around the new buffer fetchers; the new buffer fetchers are separate code that uses different telemetry shapes. This keeps regression risk for legacy callers at zero.

### 5.5 Fallback execution
For each concept in routes:
1. Walk `fallback_order` in order (full ordered list, `[0] == primary` per §4.5b).
2. For each source in the list at position `i`: read buffer entry for the concept. If non-empty, write to model, set `served_by = source`, `fallback_used = (i > 0)`. Stop.
3. If all entries empty: `served_by = None`, concept added to `missing_concepts`.

### 5.6 PopulateStats shape change (R3 — keeps dataclass form)
```python
@dataclass
class PopulateStats:
    source: str  # NEW value "routed" when historical_sources used; else "fmp"|"edgar" (back-compat)
    items_populated: int
    items_skipped: int
    periods_populated: int
    missing_concepts: list[str]
    source_resolution: list[SourceResolutionEntry] = field(default_factory=list)
    # ... existing EDGAR-mode fields preserved (edgar_api_calls, etc.)
```

### 5.7 Validator addition (R3 — Codex blocker #2 fix)
On `HistoricalSourceOverride` in `schema/model_build_context.py`:
```python
@model_validator(mode="after")
def _enforce_fallback_order_head(self) -> "HistoricalSourceOverride":
    if self.fallback_order[0] != self.preferred:
        raise ValueError(...)
    return self
```

This is the SHIPPED contract; addition is additive — existing valid instances keep working, invalid instances now fail loud at construction.

### 5.8 Files to create / modify (R4 — populate_from_fmp/edgar untouched)
- `AI-excel-addin/schema/source_routing.py` — new
- `AI-excel-addin/tests/test_source_routing.py` — new
- `AI-excel-addin/schema/build.py` — split-dispatch in `populate_historicals` (R4 §5.4); new `_populate_routed`, `_fetch_*_concept_buffer`, `_write_routed_historicals` helpers; `FmpConceptFetchResult` dataclass. **`populate_from_fmp` and `populate_from_edgar` themselves are NOT changed** — legacy path calls them as-is.
- `AI-excel-addin/schema/model_build_context.py` — Pydantic validator on `HistoricalSourceOverride`
- `AI-excel-addin/tests/test_build.py` — no test changes for legacy `source=` kwarg (behavior preserved); add tests for routed path
- `AI-excel-addin/tests/schema/test_model_build_context_types.py` — validator enforcement tests

### 5.9 Tests (~33)

**Resolver tests (~10):**
- Override beats taxonomy and default
- Taxonomy concept default beats MBC build-wide default
- MBC default applies when no taxonomy default and no override
- `fallback_order` from override layer = full ordered list (preserved)
- `fallback_order` from taxonomy/default layer = `[primary]` (single-source)
- Resolver is pure
- Resolver gracefully handles concepts absent from taxonomy
- Taxonomy `preferred_source` with unrecognized string → raises clear `ValueError`
- Layer 2 (taxonomy) skipped when `taxonomy_concept.preferred_source` is None
- Override + ineligible primary → raises `UnsupportedSourceForConcept` from `validate_route_eligibility`

**Validator tests (~5):**
- `HistoricalSourceOverride(preferred="edgar", fallback_order=["edgar","fmp"])` accepted
- `HistoricalSourceOverride(preferred="edgar", fallback_order=["fmp","edgar"])` raises ValueError
- `HistoricalSourceOverride(preferred="fmp", fallback_order=["fmp"])` accepted (single-element)
- Existing service test fixture (`fallback_order=["edgar","fmp"]` with `preferred="edgar"`) still passes
- Validator raises a clear message naming both fields

**Eligibility validator tests (~5):**
- Explicit override + ineligible primary → raises `UnsupportedSourceForConcept`
- Explicit override + ineligible fallback entry → raises
- Default-mode (`is_explicit_override=False`) + ineligible source → does NOT raise
- FMP-only concept (no edgar_tags) + override to EDGAR → raises
- EDGAR-only concept (no fmp_endpoint) + override to FMP → raises

**Populate refactor tests (~13 — R4: legacy/routed split):**
- Legacy path: `populate_historicals(source="fmp", historical_sources=None)` → identical to today's `populate_from_fmp` (snapshot-stable)
- Legacy path: `populate_historicals(source="edgar", historical_sources=None)` → identical to today's `populate_from_edgar` (snapshot-stable; warning at build.py:356 still fires)
- Routed path: `historical_sources` with `default_source="fmp"` and zero overrides → fetches FMP only (no EDGAR fetch)
- Routed path: mixed routing (3 concepts FMP, 2 concepts EDGAR) → both buffers fetched, correct concepts written
- Routed path: fallback — primary FMP empty for concept X, fallback EDGAR has value → EDGAR wins, telemetry `fallback_used=true`
- Routed path: fallback — primary EDGAR empty, fallback FMP has value → FMP wins
- Routed path: both sources empty for concept → marked missing, telemetry `served_by=None`
- Routed path: EDGAR within-source multi-tag fallback still works (preserved via `EdgarConceptFetchResult`)
- Routed path: FMP per-year `fallback_fmp_field` still works (preserved via `FmpConceptFetchResult.field_used_by_year`)
- Buffer fetchers do NOT call `_set_imported_value` / `_set_constant_override` (asserted via mock; only `_write_routed_historicals` does)
- `_write_routed_historicals` is the only mutation entry point in the routed code path (asserted via mock)
- `EdgarConceptFetchResult` partial-failure preserved into telemetry (`served_year_count` reflects partial)
- `FmpConceptFetchResult.field_used_by_year` correctly reports per-year provenance when primary serves some years and fallback serves others

### 5.10 Acceptance gate
- All A-tests pass
- All existing `test_build.py` tests still pass (regression guard)
- Codex confirms buffer/write split for overwrite-correctness AND validator enforcement
- Telemetry shape locked

### 5.11 Rollback
Revert `build.py` changes; revert validator addition; delete `source_routing.py` and tests.

---

## 6. Sub-phase B — MBC wiring + service-payload fix + eligibility

### 6.1 Goal
`build_model_from_mbc()` consults `mbc.historical_sources` and threads it through. `mbc_service._build_base_payload()` stops injecting `historical_sources` defaults so reconciliation works. Eligibility validation runs at service entry + build entry.

### 6.2 `build_model()` signature change (additive, non-breaking) — R5 fix: NO promotion
```python
def build_model(
    ...
    source: str = "fmp",                                  # KEPT — legacy single-source mode
    historical_sources: HistoricalSources | None = None,  # NEW — routed mode
    ...
):
    # R5 fix — DO NOT promote None to HistoricalSources here. Pass through unchanged so
    # populate_historicals' legacy/routed dispatch (§5.4) sees the caller's actual intent.
    return _build_model_impl(
        ...,
        source=source,
        historical_sources=historical_sources,  # None preserved → legacy path
        ...,
    )
```

This preserves the legacy/routed split end-to-end. R3/R4 had this section accidentally re-introducing the promotion that R4 §4.4 explicitly removed (Codex R4 blocker).

### 6.3 `build_model_from_mbc()` change at `build.py:809-841` — legacy / routed dispatch per §4.4 (R4)

```python
from schema.templates import load_data_taxonomy
from schema.source_routing import (
    ConceptSourceRoute,
    UnsupportedSourceForConcept,
    validate_route_eligibility,
)

def build_model_from_mbc(mbc: ModelBuildContext, ...):
    # R4 — branch by whether historical_sources was supplied by caller
    is_default_hs = "historical_sources" not in mbc.model_fields_set

    if is_default_hs:
        # LEGACY PATH — today's behavior, no routing, no taxonomy override
        return build_model(
            ...
            source=mbc.source,
            historical_sources=None,  # legacy single-source mode
            ...
        )

    # ROUTED PATH — eligibility check + threaded routing
    taxonomy = load_data_taxonomy()
    for override in mbc.historical_sources.overrides:
        taxonomy_concept = taxonomy.get(override.concept_id)
        route = ConceptSourceRoute(
            concept_id=override.concept_id,
            primary=override.preferred,
            fallback_order=list(override.fallback_order),
            layer_decided="mbc_override",
        )
        validate_route_eligibility(route, taxonomy_concept, is_explicit_override=True)
        # Raises UnsupportedSourceForConcept on ineligible primary OR fallback entry

    return build_model(
        ...
        source=mbc.source,                               # ignored when historical_sources passed
        historical_sources=mbc.historical_sources,
        ...
    )
```

**R4 simplification**: no `_reconcile_mbc_routing` helper needed. Legacy callers go straight through; routed callers go through routing. The dependency on §6.4's service-payload fix remains: `mbc.model_fields_set` must accurately reflect caller intent for the dispatch to work.

### 6.4 `mbc_service._build_base_payload()` change (R3 — Codex blocker #1 fix)

**Today** (`mbc_service.py:193`): the service injects `historical_sources` into the base payload before `ModelBuildContext.model_validate()`. Result: `model_fields_set` always contains `"historical_sources"` for service-created MBCs, and reconciliation never triggers for service callers passing only `source="edgar"`.

**Fix**: remove `historical_sources` from `_build_base_payload()` unless an override supplies it. Pydantic provides the default, and `model_fields_set` no longer reports it as caller-supplied.

```python
# In mbc_service._build_base_payload(), the change is:
# REMOVE: payload["historical_sources"] = {...}
# Caller-supplied overrides still flow through:
if "historical_sources" in overrides:
    payload["historical_sources"] = overrides["historical_sources"]
```

This is the central blocker fix from Codex R2 review. Without it, R3's reconciliation logic is dead.

### 6.5 Warning at `build.py:356` — keep for legacy mode (R4 — refined from Codex Q4)

The `"Concept '%s' prefers FMP but source='edgar' was requested"` warning lives inside `populate_from_edgar()`. R4 keeps `populate_from_edgar()` unchanged (legacy path), so this warning **stays** for legacy callers — it's still useful diagnostic signal when someone forces the global source against taxonomy preference.

In the routed path, the warning is structurally absent because per-concept routing replaces the global-source-vs-preference conflict. Routed callers see `SourceResolutionEntry.layer_decided` + `requested_primary` vs `served_by` instead.

`test_populate_edgar_preferred_source_warning` at `test_build.py:1622` stays green unchanged.

### 6.6 Files to modify (R4)
- `AI-excel-addin/schema/build.py` — `build_model_from_mbc` legacy/routed dispatch (R4 §6.3); `build_model` signature `historical_sources` param. Warning at `build.py:356` UNCHANGED (R4 §6.5).
- `AI-excel-addin/api/research/mbc_service.py` — `_build_base_payload()` change (do not inject `historical_sources` defaults); `get_model_build_context()` runs eligibility validation when overrides supply `historical_sources`
- `AI-excel-addin/tests/test_build.py` — add legacy-path snapshot regression tests confirming `populate_historicals(source="edgar")` is bit-identical pre-/post-refactor; add routed-path tests
- `AI-excel-addin/tests/api/research/test_mbc_service.py` — update tests asserting service payload shape (existing tests may rely on `historical_sources` being injected)

### 6.7 Tests (~12 — R4: legacy/routed dispatch)
- `build_model_from_mbc` with default `historical_sources` AND `source="fmp"` → legacy path, identical to today
- `build_model_from_mbc` with default `historical_sources` AND `source="edgar"` → legacy path, identical to today (NO routing, NO taxonomy override of `gross_profit`)
- Service-created MBC: `get_model_build_context(overrides={"source": "edgar"})` → `MBC.model_fields_set` does NOT contain "historical_sources" → legacy path picks `mbc.source`
- Service-created MBC with `overrides={"historical_sources": {...}}` → routed path
- `build_model_from_mbc` routed path: FMP-default + EDGAR-override on `segment_revenue` routes that one concept to EDGAR
- `build_model_from_mbc` routed path: `fallback_order=["edgar", "fmp"]` triggers FMP fallback when EDGAR returns no data
- `build_model(source="fmp")` without `historical_sources` keyword → legacy path
- `build_model(historical_sources=...)` overrides `source` arg if both passed → routed path
- Service `get_model_build_context()` rejects MBC with ineligible explicit override
- `build_model_from_mbc()` rejects MBC with ineligible explicit override (defense in depth)
- Legacy path snapshot: `populate_historicals(source="edgar")` byte-identical PopulateStats pre-/post-refactor
- Dispatch coverage: all four cases (default both, source set only, hs set only, both set) reach the correct code path

### 6.8 Acceptance gate
- All B-tests pass
- All existing `build_model_from_mbc` integration tests still pass
- All existing `mbc_service` tests still pass (or are updated for the payload shape change)
- Codex confirms reconciliation logic + service-payload fix interaction

### 6.9 Rollback
Revert plumbing; revert service-payload change; `historical_sources` returns to dead-code state.

---

## 7. Sub-phase C — Request-time surface: MCP only (R3 — CLI dropped)

### 7.1 Goal
Expose routing input on `model_build` MCP tool. Ensure EDGAR fetcher creation triggers whenever routing touches EDGAR (per §4.6 segment-mode coupling).

### 7.2 MCP tool — `model_build` at `mcp_servers/model_engine_mcp_server.py:344`
```python
def model_build(
    ...
    source: str = "fmp",                          # existing — KEPT
    historical_sources: dict | None = None,       # new — typed dict matching HistoricalSources shape
    ...
):
    # If historical_sources provided, parse into HistoricalSources Pydantic model
    # If both source and historical_sources passed: historical_sources wins; log warning
    # EDGAR fetcher creation: trigger when source=="edgar" OR routing touches EDGAR
```

**EDGAR fetcher trigger fix** (per §4.6): existing logic at `model_engine_mcp_server.py:370-372` creates the EDGAR fetcher only when `source == "edgar"` (or segment discovery requested). New rule: also create when `historical_sources` routing touches EDGAR (`default_source == "edgar"` OR any override mentions EDGAR OR any `fallback_order` mentions EDGAR).

Schema for the new param documented inline in the tool's docstring + wherever the agent-facing schema lives (Codex confirms during impl).

### 7.3 Files to modify
- `AI-excel-addin/mcp_servers/model_engine_mcp_server.py`

### 7.4 Tests (~6)
- MCP `model_build` with `historical_sources` dict produces same routing as direct MBC construction
- MCP `model_build` with both `source` and `historical_sources` → `historical_sources` wins, warning logged
- MCP creates EDGAR fetcher when routing touches EDGAR even with `source="fmp"` (segment-mode coupling fix)
- MCP creates EDGAR fetcher when only `fallback_order` mentions EDGAR (not primary)
- MCP segment-discovery + per-concept routing co-exist (segment-discovery still forces global `source="edgar"`; per-concept routing for non-segment concepts respected)
- MCP rejects `historical_sources` with `fallback_order[0] != preferred` (validator surfaces at MCP boundary)

### 7.5 Acceptance gate
All C-tests pass; Codex confirms MCP tool-schema surface; segment-mode regression tests pass.

### 7.6 Rollback
Remove the param; existing `source` continues to work.

---

## 8. Sub-phase D — Integration tests

### 8.1 Goal
End-to-end tests across the full stack: MBC with mixed routing → `build_model_from_mbc` → BuildResult with telemetry. Includes back-compat parity (including service-created MBCs) + segment-mode coexistence.

### 8.2 Tests (~10)
- E2E: MBC with FMP-default + 2 EDGAR overrides on a real-ish ticker fixture → BuildResult shows correct values from each source, telemetry correct
- E2E: MBC with `fallback_order` triggers FMP fallback when EDGAR returns no data → telemetry shows `fallback_used=true`
- E2E: MBC with ineligible explicit override → service entry raises `UnsupportedSourceForConcept`
- E2E: MBC with `source="edgar"` + default `historical_sources` (service-created) → legacy dispatch kicks in, build matches today's EDGAR behavior
- E2E: legacy `build_model(source="fmp")` produces identical result pre-/post-refactor (snapshot diff = empty)
- E2E: `model_build` MCP tool with `historical_sources` produces same BuildResult as direct MBC construction
- E2E: segment-mode build (`source="edgar"` forced + segment_config populated) still works — segment forcing untouched per §1 out-of-scope
- E2E: segment-mode + per-concept override on a non-segment concept (e.g., income statement line item routed to FMP) → FMP serves that concept, segment data still EDGAR
- E2E: validator rejection — `model_build` MCP call with `historical_sources` containing `{"preferred":"edgar","fallback_order":["fmp","edgar"]}` raises clear error
- Regression: full `tests/test_build.py` + `tests/test_source_routing.py` + `tests/api/research/test_mbc_service.py` green

### 8.3 Acceptance gate
All D-tests pass; Codex final pass.

### 8.4 Rollback
Phase-by-phase rollback already covered.

---

## 9. R1 → R2 → R3 question resolutions (was R1 §12)

| # | R1 question | R2 stake | R3 final |
|---|---|---|---|
| 1 | Taxonomy concept-level beats MBC build-wide default? | Yes | **Yes** — R3 §4.1 codifies as explicit precedence chain |
| 2 | Hard-fail or soft-skip on ineligible source? | Hard-fail explicit; soft-skip default | **Same** — R3 §4.2 |
| 3 | Eligibility validation location? | Service entry + build entry | **Same** — R3 §4.2, §6.3, §6.4 |
| 4 | Existing warning at `build.py:356`? | Delete | **Refined R4** — keep for legacy mode (still useful when `source="edgar"` chosen against taxonomy preference); routed mode replaces with `SourceResolutionEntry` telemetry (§6.5) |
| 5 | MCP both `source` and `historical_sources`? | `historical_sources` wins; warning | **Same** — R3 §4.4 |
| 6 | Phase F (HandoffArtifact routing) in scope? | Punt to v1.2 | **Same** — R3 §1 |
| 7 | Phase collapse? | A+B+E collapsed; F dropped | **Same** — R3 §2 |
| 8 (R3) | CLI surface? | n/a | **Dropped** — no CLI exists; MCP is the surface; future plan if needed |

---

## 10. Acceptance summary (parent doc V2.P9 status)

When all phases land:
- G8 closed — `historical_sources` field is live, mixed-source builds work, fallback executes, MCP request-time surface exists, telemetry observable
- V2.P9 status updated: 9 SHIPPED / 2 DESIGNED (plans #7, #10 remaining)
- Parent doc R3 ship-state row for plan #8 marked SHIPPED with commit refs

---

## 11. Risks

- **`mbc_service` payload change** — removing `historical_sources` default-injection touches the service hot path. Mitigated by the additive Pydantic default (no semantic change to instantiated MBC; only `model_fields_set` semantics change). Existing service tests may need adjustment if they assert payload shape directly — phase B includes those test updates.
- **Refactor of `populate_historicals`** — touches build hot path. Mitigated by back-compat wrappers, snapshot-test diff, and pure-read assertion on buffer fetchers.
- **Validator addition on shipped contract** — the new `_enforce_fallback_order_head` raises on existing-but-malformed instances. Verified the existing service test (`fallback_order=["edgar","fmp"]` with `preferred="edgar"`) is conformant. Any persisted MBCs with non-conformant `fallback_order` would fail to load — phase B grep sweep checks for this in fixtures + tests.
- **Segment-mode coupling** — two source-force sites must not overwrite or bypass routing. Phase C handles MCP entry; phase B verifies `build.py:680`. Tested in phase D regression.
- **API cost** — bulk-both means every build with non-trivial routing pays for both fetches. Decision on record (§1 headline). Future demand-driven optimization is contract-preserving.
- **`model_fields_set` reliability** — back-compat reconciliation in §6.3 depends on it being a meaningful signal. R3's §6.4 service-payload fix is what makes it meaningful for service callers. Tested in phase B with all four cases (default both, source set, hs set, both set).
