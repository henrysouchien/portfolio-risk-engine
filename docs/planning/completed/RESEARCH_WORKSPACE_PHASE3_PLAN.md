# Research Workspace — Phase 3 Implementation Plan: Diligence Checklist + Synthesis

**Status:** DRAFT — Codex reviewed (multiple rounds R1-R5 + cross-doc sync). Findings fixed.
**Date:** 2026-04-13 (R2 fixes: 2026-04-11, R3 fixes: 2026-04-11, R4 fixes: 2026-04-11, R5 fixes: 2026-04-11)
**Anchor:** `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE.md` (locked system frame)
**Decisions:** `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md` (Decisions 2A, 4 are centerpiece)
**Depends on:** Phase 1 (conversation + threads), Phase 2 (document reading + annotations)
**Product spec:** `docs/planning/EQUITY_RESEARCH_WORKSPACE_SPEC.md` (UX authoritative; architecture superseded)

---

## What Phase 3 Delivers

- **Diligence tab** — special tab type in the reader area, activated when thesis forms. Not closeable once opened.
- **9 universal core sections** rendered as accordion-style checklist: Business Overview, Thesis, Catalysts & Timing, Valuation, Assumptions, Risks, Peer Comps, Ownership & Flow, Monitoring.
- **Dynamic Qualitative Factors section** — below the 9 core sections. Free-form `category` strings. Style-scoped suggestions based on `research_files.strategy`. Schema-free `data` blobs.
- **Per-section completion state**: `empty → draft → confirmed`. Stored in draft `research_handoffs` row's `artifact.metadata.diligence_completion`. Finalization NEVER blocked on state (Invariant 14).
- **Server-side pre-population** — parallel initial data pull across auto-populatable sections (Business Overview, Catalysts, Valuation, Assumptions, Risks, Peers, Ownership). Thesis and Monitoring start empty.
- **`fetch_data_for(category, ticker)` registry** — per-category data pullers for structured qualitative factor data (start with `short_interest`, `street_view`, `positioning`).
- **Style-aware factor suggestions** — agent surfaces different categories based on `research_files.strategy` (value / special_situation / macro / compounder).
- **Opening take synthesis** — agent-generated synthesis from threads + diligence state, rendered as insight section at top of diligence tab.
- **Diligence-aware context** — `build_research_context()` includes draft diligence state in the agent's prompt block.

## What is NOT in Phase 3

- Handoff finalization (`research_handoffs.status='finalized'`) — Phase 4
- `annotate_model_with_research()` tool + BuildModelOrchestrator — Phase 4
- Report rendering view — Phase 4
- SIA template driver-name → cell-address mapping — Phase 4
- PDF/markdown export — Phase 5 (JSON export is Phase 4)
- Multi-ticker theme research — Phase 5
- Web search integration — Phase 5
- Thread-to-diligence auto-mapping (open question 2) — deferred; users manually link via `diligence_ref`

---

## Investigation Findings

### Finding 1: MCP Tool Surface for Pre-Population

| # | Section | Primary MCP Tool(s) | Auto-populatable? |
|---|---------|---------------------|-------------------|
| 1 | Business Overview | `fmp_profile`, `get_stock_fundamentals`, langextract `segment_discussion` (Phase 2) | Mostly |
| 2 | Thesis | None — requires user judgment | No |
| 3 | Catalysts & Timing | `get_events_calendar`, `get_news`, langextract `forward_guidance` | Partially |
| 4 | Valuation | `get_stock_fundamentals(include=["valuation"])`, `compare_peers`, `fmp_fetch("discounted_cash_flow")` | Partially |
| 5 | Assumptions | `get_stock_fundamentals(include=["financials"])`, langextract `forward_guidance`, `get_estimate_revisions` | Partially |
| 6 | Risks | langextract `risk_factors` (existing schema) | Yes |
| 7 | Peer Comps | `compare_peers`, `get_sector_overview` | Yes |
| 8 | Ownership & Flow | `get_institutional_ownership`, `get_insider_trades` | Yes |
| 9 | Monitoring | Agent suggests based on thesis dependencies | Partially |

### Finding 2: Handoff Artifact Schema Mapping (Decision 2A)

| Diligence Section | Artifact Field(s) |
|---|---|
| Business Overview | `company.*`, `business_overview.*`, `business_overview.source_refs[]` |
| Thesis | `thesis.*`, `thesis.source_refs[]` |
| Catalysts & Timing | `catalysts[]` (each entry has `source_ref`) |
| Valuation | `valuation.*`, `valuation.source_refs[]` |
| Assumptions | `assumptions[]` (driver keys → SIA template, each has `source_refs[]`) |
| Risks | `risks[]` (each entry has `source_ref`) |
| Peer Comps | `peers[]` |
| Ownership & Flow | `ownership.*`, `ownership.source_refs[]` |
| Monitoring | `monitoring.watch_list[]` |
| Qualitative Factors | `qualitative_factors[]` (each entry has `id`, `source_refs[]`) |

**Source refs flow:** Each section carries raw `source_refs[]` entries (tool provenance + annotation back-links). Phase 4 assembles the final indexed `sources[]` array from all sections' `source_refs` + all annotations with `diligence_ref` set. Phase 3 is responsible for populating the raw refs; Phase 4 owns deduplication and indexing.

### Finding 3: Langextract Schema → Diligence Section Mapping

| Schema | Diligence Section(s) Fed |
|---|---|
| `risk_factors` (existing) | Risks |
| `forward_guidance` (existing) | Catalysts & Timing, Assumptions |
| `capital_allocation` (existing) | Qualitative Factors (`capital_structure`, `financing`) |
| `liquidity_leverage` (existing) | Qualitative Factors (`capital_structure`, `financing`) |
| `management_commentary` (Phase 2) | Qualitative Factors (`management_team`, `management_quality`) |
| `competitive_positioning` (Phase 2) | Qualitative Factors (`competitive_moat`) |
| `segment_discussion` (Phase 2) | Business Overview (`segments[]`) |

### Finding 4: Frontend Patterns

Existing prior art: `@radix-ui/react-accordion` already wrapped. `NamedSectionBreak` for section headers, `InsightSection` for opening insight, `MetricStrip` for compact data, `Badge` for status indicators, `GeneratedArtifact` for agent-generated content blocks.

### Finding 5: Diligence State Storage

Phase 3 creates a `research_handoffs` row with `status='draft'` when diligence activates. Per-section state lives in `artifact.metadata.diligence_completion`. Section data lives in corresponding artifact fields. No new table needed.

### Finding 6: Strategy-Based Routing

Prompt-based, not code-enforced. Agent sees strategy in context block + seed category lists from Decision 4. UI reads strategy from `researchStore.activeFile.strategy` to order suggestions in "Add Factor" modal.

---

## Step 1 — Diligence State Service + Repository Extensions

**Owner:** ai-excel-addin
**New file:** `api/research/diligence_service.py`
**Extended file:** `api/research/repository.py`

```python
def get_or_create_draft_handoff(self, research_file_id: int) -> dict:
    """Get latest draft handoff, or create one with empty artifact.""" ...

def update_handoff_section(self, handoff_id: int, section_key: str,
                           section_data: dict, completion_state: str,
                           source_refs: list[dict] | None = None) -> dict:
    """Update a specific section in the draft artifact.
    
    section_data is the section content dict.
    source_refs (optional) are provenance entries attached to the section,
    each shaped: {"tool": "...", "fetched_at": "...", "ticker": "...", ...}.
    Phase 4 assembles the final indexed sources[] from these raw refs.
    """
    ...

def batch_update_handoff_sections(
    self, handoff_id: int,
    section_updates: dict[str, dict],
    factor_entries: list[dict] | None = None,
) -> dict:
    """Atomic batch update: read artifact once, merge all section updates
    + factor entries, write once. Skips confirmed sections.
    Used by prepopulate to avoid concurrent-write race conditions."""
    ...

def get_latest_handoff(self, research_file_id: int,
                       status: str = 'draft') -> Optional[dict]: ...

def add_qualitative_factor(self, handoff_id: int, factor: dict) -> dict:
    """Add a qualitative factor entry. Generates a stable factor_id
    (auto-incrementing integer scoped to the handoff artifact).
    Returns the created factor dict including its id."""
    ...

def remove_qualitative_factor(self, handoff_id: int, factor_id: int) -> dict:
    """Remove a qualitative factor by factor_id (not category).""" ...

def upsert_artifact_message(self, thread_id: int, artifact_type: str,
                            content: str, metadata: dict) -> dict:
    """Insert-or-update a message with content_type='artifact' and
    metadata.type=artifact_type in the given thread.

    Finds the latest message in the thread with content_type='artifact'
    and metadata->type == artifact_type. If found, UPDATEs its content
    and metadata in place (same message ID). If not found, INSERTs a
    new message. This prevents duplicate artifacts on regeneration
    (e.g., opening take replace-latest semantics, P3-F4 fix).""" ...
```

**DiligenceService** orchestrates section operations with validation.

**Source refs contract:** Every puller in Step 3 returns `source_refs` alongside section data (e.g., `{"tool": "get_institutional_ownership", "fetched_at": "2026-04-13T...", "ticker": "VALE"}`). When a user edits a section and links an annotation (via `diligence_ref` on the annotation), the annotation's ID flows into the section's `source_refs[]`. Phase 4 owns the final `sources[]` assembly: it collects all `source_refs` from all sections + all annotations with `diligence_ref` set, builds the indexed `sources[]` array with `annotation_id` back-links per Decision 2A.

**Qualitative factor identity:** Each factor entry in `qualitative_factors[]` gets a stable `id` field (auto-incrementing integer scoped to the artifact, tracked via `artifact.metadata.next_factor_id`). All mutation operations (edit, delete) use `factor_id`, not `category` — two factors can share a category.

**Tests (13):**
- `test_get_or_create_draft_creates_on_first_call`
- `test_get_or_create_draft_idempotent`
- `test_update_section_sets_data_and_completion`
- `test_update_section_with_source_refs`
- `test_update_section_invalid_state_raises`
- `test_update_section_draft_only`
- `test_add_qualitative_factor_gets_stable_id`
- `test_add_qualitative_factor_duplicate_category_allowed`
- `test_remove_qualitative_factor_by_id`
- `test_remove_qualitative_factor_nonexistent_raises`
- `test_get_latest_handoff_version_ordering`
- `test_upsert_artifact_message_insert` — first call creates new artifact message
- `test_upsert_artifact_message_update` — second call with same artifact_type updates in place (same message ID, new content)

---

## Step 2 — Diligence REST Endpoints

**Owner:** ai-excel-addin
**Extended file:** `api/research/routes.py`

```
POST   /diligence/activate                — { research_file_id }
GET    /diligence/state                   — ?research_file_id=...
PATCH  /diligence/sections/{key}          — { handoff_id, section_data, completion_state, source_refs? }
POST   /diligence/factors                 — { handoff_id, factor } → returns created factor with id
PATCH  /diligence/factors/{factor_id}     — { handoff_id, updates } (category, label, assessment, rating, data)
DELETE /diligence/factors/{factor_id}     — ?handoff_id=...
POST   /diligence/prepopulate             — { research_file_id, sections? }
POST   /diligence/opening-take            — { research_file_id }
```

Factor endpoints use `factor_id` (stable auto-incrementing integer), NOT category string. Two factors can share a category (e.g., two separate `management_quality` entries for different aspects).

**Tests (8):**
- `test_activate_creates_draft`
- `test_activate_idempotent`
- `test_get_diligence_state`
- `test_update_section_persists`
- `test_update_section_with_source_refs`
- `test_add_factor_returns_id`
- `test_delete_factor_by_id`
- `test_user_isolation`

---

## Step 3 — Server-Side Pre-Population Orchestration

**Owner:** ai-excel-addin
**New file:** `api/research/prepopulate.py`

Server-side orchestration (direct tool calls, NOT agent-mediated). **Fetch-parallel, merge-once pattern** — parallelism is in the DATA FETCHING, not the WRITING. All 7 section pullers fetch data concurrently via `asyncio.gather`, results are merged into a single artifact dict in memory, then persisted with one `batch_update_handoff_sections()` call. This avoids the last-write-wins race condition that would occur if 7 parallel tasks each called `update_handoff_section()` independently under a connection-per-operation model.

After core sections are fetched, qualitative factors are also pre-populated:
1. Read `research_files.strategy` for the active file
2. Look up style-scoped suggested categories from `STRATEGY_FACTOR_SUGGESTIONS`
3. For each suggested category that has a registered puller, call `fetch_data_for(category, ticker)`
4. Create draft qualitative factor entries with `data` populated and `assessment` empty
5. Also include style-independent factors that have registered pullers (e.g., `short_interest`)
6. Factor entries are included in the same batch write alongside core sections

```python
async def prepopulate_diligence(
    repo: ResearchRepository,
    handoff_id: int,
    research_file_id: int,
    ticker: str,
    strategy: str | None,
    sections: list[str] | None = None,
) -> dict:
    """Fetch all populatable sections + factors in parallel, merge, write once."""

    # Step 1: Fetch all core sections in parallel
    targets = _get_section_targets(sections)  # 7 auto-populatable section pullers
    fetch_tasks = {key: puller_fn(ticker) for key, puller_fn in targets.items()}
    results = await asyncio.gather(*fetch_tasks.values(), return_exceptions=True)

    # Step 2: Merge results into single artifact update (skip failures)
    section_updates = {}
    for key, result in zip(fetch_tasks.keys(), results):
        if not isinstance(result, Exception):
            section_updates[key] = result

    # Step 3: Fetch qualitative factor data in parallel
    factor_entries = await _fetch_suggested_factors(ticker, strategy)

    # Step 4: Single transactional write — core sections + factors
    repo.batch_update_handoff_sections(
        handoff_id, section_updates, factor_entries=factor_entries
    )
    return {"updated_sections": list(section_updates.keys()),
            "factors_created": len(factor_entries),
            "errors": [k for k, r in zip(fetch_tasks.keys(), results)
                       if isinstance(r, Exception)]}


async def _fetch_suggested_factors(
    ticker: str, strategy: str | None
) -> list[dict]:
    """Build draft qualitative factor entries from strategy + registry.

    Each puller returns {data: {...}, source_refs: [...]}.
    Factor entries get stable IDs assigned during the merge step
    in batch_update_handoff_sections() (P3-F1 fix).
    """
    categories = set()
    if strategy and strategy in STRATEGY_FACTOR_SUGGESTIONS:
        categories.update(STRATEGY_FACTOR_SUGGESTIONS[strategy])
    # Always include style-independent factors with registered pullers
    categories.update(get_available_categories())

    factor_tasks = {cat: fetch_data_for(cat, ticker) for cat in categories
                    if has_puller(cat)}
    results = await asyncio.gather(*factor_tasks.values(), return_exceptions=True)

    entries = []
    for cat, result in zip(factor_tasks.keys(), results):
        if not isinstance(result, Exception) and result is not None:
            # Each puller returns {data: {...}, source_refs: [...]}
            # Unpack both fields (P3-F2 fix)
            puller_result = result if isinstance(result, dict) else {"data": result}
            entries.append({
                "category": cat,
                "label": default_label_for(cat),
                "assessment": "",   # empty — analyst fills this in
                "rating": None,
                "data": puller_result.get("data", {}),
                "source_refs": puller_result.get("source_refs", []),
            })
    # NOTE: factor_id is NOT assigned here. IDs are assigned during the
    # merge step in batch_update_handoff_sections() which reads
    # artifact.metadata.next_factor_id, assigns IDs, and writes back.
    # See P3-F1 fix below.
    return entries
```

**Repository addition** — `batch_update_handoff_sections()` in `repository.py`:
- Reads the artifact JSON once
- Checks per-section completion state: skips `confirmed` sections (preserves sticky), overwrites `draft`/`empty`
- Merges all `section_updates` into the artifact dict
- For `factor_entries`: assigns stable `factor_id` values during merge (P3-F1 fix):
  1. Reads current `artifact.metadata.next_factor_id` counter (initialized to 1 on handoff creation)
  2. For initial pre-population (all factors are new): assign new IDs. For refresh: match by `factor_id` if the factor already has one (preserved from previous activation). If a pre-populated factor has no matching ID in the existing list, it's treated as new and gets a new ID. Category is NOT used as a merge key — two factors with the same category coexist independently.
  3. Writes the updated `next_factor_id` back to `artifact.metadata`
- Writes the artifact once
- Updates `diligence_completion` metadata for all touched sections to `draft`

**Refresh semantics:** Confirmed sections preserved, draft sections overwritten, empty sections get fresh data.

**Tests (12):**
- `test_prepopulate_all_sections_parallel`
- `test_prepopulate_preserves_confirmed`
- `test_prepopulate_overwrites_draft`
- `test_prepopulate_section_failure_isolated`
- `test_pull_business_overview_shape`
- `test_pull_ownership_shape`
- `test_pull_risks_with_filing`
- `test_batch_update_single_write` — verify `batch_update_handoff_sections` reads+writes artifact exactly once (mock DB to count calls)
- `test_batch_update_concurrent_safety` — two concurrent `prepopulate_diligence` calls on same handoff do not lose sections (sequential write ordering)
- `test_prepopulate_creates_strategy_factors` — activation with `strategy='value'` creates factors from value suggestions
- `test_prepopulate_factor_data_populated` — factor entries have `data` blob from registry, `assessment` is empty string
- `test_prepopulate_without_phase2_schemas` — verifies all sections and factors populate with graceful fallback when langextract schemas are unavailable (see Phase 2 fallback handling)

---

## Step 4 — `fetch_data_for(category, ticker)` Registry

**Owner:** ai-excel-addin
**New file:** `api/research/factor_data_registry.py`

Decorator-based registry. 3 seed pullers: `short_interest`, `street_view`, `positioning`. Also exposes `has_puller(category)` and `get_available_categories()` for use by prepopulate flow.

**Puller return contract (P3-F2 fix):** Each puller returns `{"data": {...}, "source_refs": [...]}`. The `data` field contains the category-specific structured blob (e.g., `{"short_pct_float": 22.1, "days_to_cover": 7, "borrow_rate": 15.3}`). The `source_refs` field contains provenance entries (e.g., `[{"tool": "get_insider_trades", "fetched_at": "2026-04-13T...", "ticker": "VALE"}]`). Both fields are unpacked by `_fetch_suggested_factors()` in Step 3 and flow into the factor entry.

**Wired into Step 3:** The registry is called during pre-population/refresh (not just on-demand). After core sections are fetched, `_fetch_suggested_factors()` reads the strategy, looks up style-scoped suggestions from `STRATEGY_FACTOR_SUGGESTIONS`, and calls `fetch_data_for()` for every suggested category that has a registered puller. Style-independent factors with registered pullers (e.g., `short_interest`) are always included. Results land as draft qualitative factor entries with `data` and `source_refs` populated from the puller return value, and `assessment` empty.

**Tests (6):**
- `test_registry_returns_data`
- `test_registry_returns_none_for_unknown`
- `test_available_categories`
- `test_has_puller`
- `test_puller_error_handling`
- `test_puller_returns_source_refs`

---

## Step 5 — Agent Context Extension for Diligence

**Owner:** ai-excel-addin
**Extended files:** `api/research/context.py`, `api/research/policy.py`

Context includes diligence completion summary + strategy-scoped factor suggestions.

```python
STRATEGY_FACTOR_SUGGESTIONS = {
    "value": ["competitive_moat", "capital_structure", "management_quality",
              "cyclicality", "capital_allocation", "book_value_quality"],
    "special_situation": ["catalyst_mechanics", "activist_setup",
                          "financing_structure", "deal_terms",
                          "arbitrage_spread", "legal_risk"],
    "macro": ["macro_exposure", "geographic_exposure", "currency_exposure",
              "regulatory_exposure", "supply_chain", "commodity_linkage"],
    "compounder": ["brand_strength", "long_term_growth_drivers",
                    "management_quality", "capital_allocation",
                    "tam_expansion", "reinvestment_runway"],
}
```

**Tests (4):**
- `test_context_includes_diligence_state`
- `test_context_no_diligence`
- `test_context_strategy_factor_suggestions`
- `test_context_null_strategy`

---

## Step 6 — Opening Take Synthesis

**Owner:** ai-excel-addin
**New file:** `api/research/synthesis.py`
**Extended file:** `api/research/routes.py`

Stored as panel thread message with `content_type='artifact'` and `metadata.type='opening_take'` (avoids extending handoff schema).

**Replace-latest semantics:** `generate_opening_take()` calls `repo.upsert_artifact_message(thread_id, artifact_type='opening_take', content=..., metadata=...)` (Step 1 repository extension, P3-F4 fix). This finds any existing message with `metadata.type='opening_take'` in the panel thread and replaces it (update in place, same message ID). If none exists, creates a new one. This prevents duplicate opening takes on regeneration.

**Tests (5):**
- `test_opening_take_includes_findings`
- `test_opening_take_includes_diligence`
- `test_opening_take_no_findings`
- `test_opening_take_replace_latest` — regenerating replaces the old message, not duplicates it
- `test_opening_take_idempotent_when_unchanged` — if diligence state hasn't changed, replacement still produces exactly one opening take message

---

## Step 7 — Frontend: `researchStore` Extensions

**Owner:** frontend (risk_module)
**Extended file:** `researchStore.ts`

```typescript
interface DiligenceState {
  handoffId: number | null;
  version: number;
  sections: DiligenceSection[];
  qualitativeFactors: QualitativeFactor[];  // each has stable `id: number`
  openingTake: string | null;
  isPrePopulating: boolean;
}

interface QualitativeFactor {
  id: number;              // stable identity — all mutations by id, not category
  category: string;
  label: string;
  assessment: string;
  rating: 'high' | 'medium' | 'low' | null;
  data: Record<string, unknown> | null;
  source_refs: SourceRef[];
}
```

**Tests (5):**
- `test_activateDiligence_opens_tab`
- `test_updateSection_changes_state`
- `test_confirmSection`
- `test_addQualitativeFactor`
- `test_hydrateDigilence`

---

## Step 8 — Frontend: React Query Hooks

**Owner:** frontend (risk_module)
**New file:** `useResearchDiligence.ts`

```typescript
useDiligenceState(researchFileId)
useActivateDiligence()
useUpdateSection()                        // PATCH /diligence/sections/{key}
useAddQualitativeFactor()                 // POST /diligence/factors → returns { id, ... }
useUpdateQualitativeFactor(factorId)      // PATCH /diligence/factors/{factor_id}
useRemoveQualitativeFactor(factorId)      // DELETE /diligence/factors/{factor_id}
useRequestOpeningTake()
useTriggerPrePopulation()
```

**Tests (3):**
- `test_useDiligenceState_fetches`
- `test_useActivateDiligence_invalidates`
- `test_useUpdateSection_sends_patch`

---

## Step 9 — Frontend: Diligence Tab Component Tree

**Owner:** frontend (risk_module)
**New files (7 components):**
- `DiligenceTab.tsx` — main container
- `DiligenceSection.tsx` — per-section accordion with completion badge
- `DiligenceSectionHeader.tsx` — `NamedSectionBreak` + `Badge`
- `QualitativeFactorsSection.tsx` — dynamic factors list
- `QualitativeFactorCard.tsx` — factor with data strip + narrative textarea + rating
- `AddFactorModal.tsx` — category picker (style-suggested → full seed → custom)
- `DiligenceOpeningTake.tsx` — `InsightSection` wrapper

**Completion badges:** `EMPTY` (default border), `DRAFT` (gold `--accent`), `CONFIRMED` (green). Geist Mono 9px uppercase.

**Two-author distinction:** Server-pre-populated content: gold `--accent` left rail. User edits: dim `--text-dim` left rail. Both 13px.

**Tests (5):**
- `test_DiligenceTab_renders_all_sections`
- `test_DiligenceSection_empty_state`
- `test_DiligenceSection_draft_state`
- `test_DiligenceSection_confirmed_state`
- `test_AddFactorModal_strategy_suggestions`

---

## Step 10 — Frontend: Integration Wiring

**Owner:** frontend (risk_module)

Tab bar: diligence tab with completion indicator. "Form thesis →" exit ramp activates diligence. Strategy change triggers agent suggestion message (non-destructive).

**Tests (4):**
- `test_form_thesis_activates_diligence`
- `test_diligence_tab_not_closeable`
- `test_diligence_tab_completion_indicator`
- `test_strategy_change_prompt`

---

## Step 11 — Risk_module Proxy Extension

**Owner:** risk_module (backend)
**Extended file:** `routes/research_content.py`

Add 8 diligence endpoint forwarding rules (activate, state, sections, factors CRUD, prepopulate, opening-take). Same tier gate + user_id injection pattern.

**Tests (2):**
- `test_diligence_proxy_tier_gate`
- `test_diligence_proxy_forwards_all_methods`

---

## Dependency Batches

```
Batch 0 (backend foundation, parallel):
  Step 1: Diligence state service + repository
  Step 4: fetch_data_for registry

Batch 1 (depends on Batch 0):
  Step 2: Diligence REST endpoints (needs Step 1)
  Step 3: Pre-population orchestration (needs Steps 1, 4)
  Step 5: Agent context extension (needs Step 1)

Batch 2 (depends on Batch 1, frontend parallel):
  Step 6: Opening take synthesis
  Step 7: researchStore extensions (contract-first from Step 2)
  Step 8: React Query hooks (needs Step 7)
  Step 11: Risk_module proxy (needs Step 2)

Batch 3 (depends on Batch 2):
  Step 9: Diligence Tab component tree (needs Steps 7, 8)

Batch 4 (depends on Batch 3):
  Step 10: Integration wiring
```

**Estimated duration:** ~7-11 days single developer, plus review rounds.

---

## Test Summary

| Step | Tests |
|------|-------|
| Step 1 — Diligence state + repo | 13 |
| Step 2 — REST endpoints | 8 |
| Step 3 — Pre-population | 12 |
| Step 4 — Factor data registry | 6 |
| Step 5 — Agent context | 4 |
| Step 6 — Opening take | 5 |
| Step 7 — researchStore | 5 |
| Step 8 — React Query hooks | 3 |
| Step 9 — Diligence components | 5 |
| Step 10 — Integration | 4 |
| Step 11 — Proxy | 2 |
| **Total** | **67** |

---

## Cross-Repo Change Summary

| Repo | Changes |
|---|---|
| **ai-excel-addin** | Extended `repository.py` (6 new methods incl. `batch_update_handoff_sections` with ID-assigning merge, `add_qualitative_factor` with ID generation, `remove_qualitative_factor` by ID, `upsert_artifact_message` for replace-latest). New `diligence_service.py`, `prepopulate.py` (7 section pullers + factor pre-population, fetch-parallel-merge-once pattern), `factor_data_registry.py` (3 pullers returning `{data, source_refs}` + `has_puller`/`get_available_categories`), `synthesis.py` (replace-latest opening take via `upsert_artifact_message`). Extended `routes.py` (8 endpoints incl. factor CRUD by ID), `context.py`, `policy.py`. ~1400 lines new + ~250 lines extensions. |
| **risk_module (backend)** | Extended `research_content.py` (8 proxy routes). ~45 lines. |
| **risk_module (frontend)** | Extended `researchStore.ts`. New `useResearchDiligence.ts`. 7 new components. Extended `ResearchTabBar.tsx`, `ResearchWorkspace.tsx`. ~1800 lines new + ~150 lines extensions. |

---

## Flags

1. **Pre-population: server-side, not agent-mediated** — simpler MVP. Agent intelligence layers on later.
2. **Opening take stored as message, not handoff field** — avoids extending Decision 2A schema. **Replace-latest semantics:** when regenerated, the old `opening_take` artifact message is replaced (not duplicated). The `upsert_artifact_message()` method finds the existing message by `metadata.type='opening_take'` and overwrites it.
3. **Factor registry pulled from Phase 4 to Phase 3** — qualitative factors need data to be useful. Starting with 3 pullers.
4. **Phase 2 langextract dependency** — explicit fallback handling for all 3 Phase 2 schemas:
   - `segment_discussion` missing → Business Overview segments from FMP profile only (company description, no segment breakdown)
   - `management_commentary` missing → management qualitative factors (`management_team`, `management_quality`) get `data` from FMP profile (CEO name, tenure from profile if available) but `assessment` stays empty
   - `competitive_positioning` missing → competitive moat factor gets no `data`, only a suggested `label` with "Pending filing analysis"
5. **Fetch-parallel, merge-once write pattern** — all 7 section fetches + factor data fetches run concurrently via `asyncio.gather`, but the artifact is written exactly once via `batch_update_handoff_sections()`. No concurrent writes to the same JSON row.
6. **Stable factor identity** — each qualitative factor entry has an `id` (auto-incrementing integer scoped to artifact). All mutations by `factor_id`, not category. Two factors can share a category.

---

## Review History

### R1 — Codex Review (2026-04-13)

**5 findings, all applied:**

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | Critical | Pre-population concurrent writes unsafe — 7 parallel pullers writing to same JSON row = last-write-wins race | Changed to fetch-parallel-merge-once pattern: `asyncio.gather` for data fetching, single `batch_update_handoff_sections()` write. Added `batch_update_handoff_sections` to repository. Added 3 tests (batch write, concurrent safety, Phase 2 fallback). |
| 2 | High | Qualitative factor initial pull not wired — registry exists (Step 4) but not called during activation/refresh | Wired factor registry into Step 3 prepopulate flow. After core section fetches, reads strategy → looks up `STRATEGY_FACTOR_SUGGESTIONS` → calls `fetch_data_for()` for style-scoped + style-independent categories → creates draft factor entries with `data` populated, `assessment` empty. Added 2 tests (strategy factors, factor data populated). |
| 3 | High | Qualitative factors have no stable identity — DELETE by category breaks on rename/duplicate | Added `factor_id` (auto-incrementing integer scoped to artifact) to each factor entry. Changed `DELETE /diligence/factors/{cat}` to `DELETE /diligence/factors/{factor_id}`. Added `PATCH /diligence/factors/{factor_id}` for editing. Updated repository methods to generate/match by ID. Added 3 tests (stable ID, duplicate category, nonexistent raises). |
| 4 | High | Source refs / sources[] / annotation back-links not specified — no citation index per Decision 2A | Added `source_refs` to `update_handoff_section()` contract. Each puller returns `source_refs` alongside data. Annotation `diligence_ref` flows into section `source_refs[]`. Phase 4 owns final `sources[]` assembly from all raw refs + annotations. Updated Finding 2 table, Step 1 contract, Step 4 puller output. Added 2 tests (section source_refs, puller source_refs). |
| 5 | Medium | Phase 2 fallback incomplete — only covers `segment_discussion`, not `management_commentary` or `competitive_positioning` | Added explicit fallback for all 3 Phase 2 schemas in Flag 4. Added replace-latest/idempotency for opening take (Flag 2). Added 3 tests (Phase 2 fallback, opening take replace-latest, opening take idempotent). |

**Test count:** 51 → 65 (+14 tests from R1 fixes).

### R2 — Codex Review (2026-04-11)

**4 findings, all applied:**

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | High | Pre-populated factors don't get stable IDs — `_fetch_suggested_factors()` builds factor entries without IDs, and `batch_update_handoff_sections` has no ID assignment. | Updated `batch_update_handoff_sections()` to assign `factor_id` during the merge step: reads `artifact.metadata.next_factor_id`, assigns IDs to new factors, ID-preserving merge on refresh (match by `factor_id`, not category). Removed ID assignment from `_fetch_suggested_factors()` — entries arrive without IDs, IDs assigned at merge time. (Category-based matching initially proposed here was corrected to factor_id-based in R4.) |
| 2 | High | Factor `source_refs` dropped in pseudocode — Step 4 says pullers return `source_refs` but `_fetch_suggested_factors()` hardcodes `source_refs: []` and stores raw result as `data`. | Updated puller return contract: each puller returns `{"data": {...}, "source_refs": [...]}`. Updated `_fetch_suggested_factors()` to unpack both fields: `puller_result.get("data", {})` and `puller_result.get("source_refs", [])`. Updated Step 4 puller interface documentation. |
| 3 | High | Architecture docs not updated for Phase 3 scope changes — phase map says "No handoff", Decision 2A missing `factor_id`, factor registry listed as Phase 4. | Updated architecture doc: Section 9 phase map clarifies draft handoffs in Phase 3 (no finalized handoff). Added `factor_id` note to Invariant 13. Updated decisions doc: Decision 2A adds `"id": integer` to factor entry shape. Decision 4 notes factor data registry ships in Phase 3. |
| 4 | Medium | Opening-take replace-latest needs repository method — Step 6 requires updating an existing message in place, but repository only has insert/list. | Added `upsert_artifact_message(thread_id, artifact_type, content, metadata)` to Step 1 repository contract. Method finds latest artifact message by type and updates in place, or inserts new. Step 6 now references this method. Added 2 tests. |

**Test count:** 65 → 67 (+2 tests: upsert_artifact_message insert + update).

### R3 — Codex Review (2026-04-11)

**4 findings, all applied (2 in anchor docs, 1 in decisions doc, 1 in plan body):**

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | High | Architecture doc and decisions doc still say "agent initial pull" but Phase 3 plan uses server-side orchestration. | Updated architecture doc Phase 3 description: "server-side parallel data pull (direct MCP tool calls, not agent-mediated)". Updated decisions doc Decision 4 pre-population flow: "Server-side orchestrator runs initial pull sequence in parallel (direct tool calls)". Updated all "agent pre-populates/fetches" language to "pre-population orchestrator fetches data". |
| 2 | Medium | Decisions doc says draft handoff "created implicitly when Phase 3 diligence section is touched" — contradicts plan (created on diligence activation). Architecture doc labels `research_handoffs` table as Phase 4 only. | Updated decisions doc lifecycle: "created when diligence tab activates (Phase 3). Updated progressively as sections are populated." Updated architecture doc storage topology: `research_handoffs [Phase 3 draft, Phase 4 finalize]`. |
| 3 | Medium | Decision 4 "Factor entry shape" summary omits `id` field that Decision 2A includes. | Added `id` — integer, auto-assigned, stable identity for CRUD operations — as first field in the Factor entry shape list. |
| 4 | Low | Flags section still says `replace_opening_take()` but Steps 1 and 6 use `upsert_artifact_message()`. | Updated Flag 2 to reference `upsert_artifact_message()` instead of `replace_opening_take()`. |

**Test delta:** No change (67 tests). Fixes were consistency/propagation corrections.

### R4 — Codex Review (2026-04-11)

**2 findings, both applied:**

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | Medium | `batch_update_handoff_sections()` factor merge still matches by `category` — ambiguous when two factors share a category. | Changed to factor_id-based matching: for initial pre-population (all new), assign new IDs. For refresh, match by `factor_id` if the factor already has one. Category is NOT used as a merge key — two factors with the same category coexist independently. |
| 2 | Medium | "Agent pre-population" wording still appears in Phase 3 deliverables (line 18), Step 3 heading, two-author distinction, and decisions doc (lines 576, 581). | Changed all instances: "Agent pre-population" → "Server-side pre-population", "Agent Pre-Population Orchestration" → "Server-Side Pre-Population Orchestration", "Agent pre-populated content" → "Server-pre-populated content", decisions doc "Pre-populated by agent" → "Pre-populated by server-side orchestrator", "Agent pre-population flow" → "Server-side pre-population flow". |

**Test delta:** No change (67 tests). Fixes were stale wording/logic corrections.

### R5 — Codex Review (2026-04-11)

**2 findings, both applied:**

| # | Severity | Finding | Fix |
|---|----------|---------|-----|
| 1 | Medium | Phase 4 plan Step 7 says `api/research/factor_pullers.py` with seeds `short_interest, street_view, ownership` — conflicts with Phase 3's `api/research/factor_data_registry.py` with seeds `short_interest, street_view, positioning`. | Updated Phase 4 Step 7 to be conditional: if Phase 3 already shipped `factor_data_registry.py`, Phase 4 skips and extends. File name is `factor_data_registry.py` (matching Phase 3), NOT `factor_pullers.py`. Updated cross-repo summary to mark factor registry as conditional. |
| 2 | Low | R2 review history entry says "de-duplicates by category" describing what R2 fixed, but R4 later corrected this to factor_id-based matching — history text was misleading. | Updated R2-F1 description to reference ID-preserving merge and note that category-based matching was corrected in R4. Also fixed Step 1 test count header: "Tests (11)" → "Tests (13)" (13 tests listed). Fixed "NOT in Phase 3" list: removed "JSON/" from "JSON/PDF/markdown export" since JSON export is Phase 4. |

**Test delta:** No change (67 tests). Fixes were propagation/consistency corrections.
