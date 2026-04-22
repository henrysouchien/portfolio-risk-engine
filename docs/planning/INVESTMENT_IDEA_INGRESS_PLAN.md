# InvestmentIdea Ingress — Implementation Plan

**Status**: ✅ **PASS (Codex R11)** — implementation-ready
**Created**: 2026-04-21
**Last revised**: 2026-04-22 (R11 PASS + 3 nit cleanups; see §15 for full R1-R11 disposition)
**Design inputs**:
- `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` — contract shapes (PASS R6), esp. §6.1 (InvestmentIdea) and §6.2 (HandoffArtifact v1.1 `idea_provenance` field)
- `docs/planning/THESIS_LIVING_ARTIFACT_PLAN.md` — plan #1 (PASS R7) for the Thesis bootstrap path
- `docs/planning/HANDOFF_ARTIFACT_V1_1_PLAN.md` — plan #2 (PASS R5) for the `idea_provenance` acceptance surface
- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md`

**Closes**: **G1** (typed investment_tools → AI-excel-addin ingress) and **G14** (idea provenance carried through into Thesis + HandoffArtifact). Unblocks plan #5 (ProcessTemplate selection hint via `suggested_process_template_id`).

**Hard prereqs**:
- Plan #2 implemented (HandoffArtifact v1.1 must already accept `idea_provenance` for Thesis → HandoffArtifact derivation to preserve it). Plan #1 co-required (Thesis shared-slice `thesis.{direction,strategy,conviction,timeframe}` are the bootstrap target).

---

## 1. Purpose & scope

Ship typed ingress from `investment_tools` into AI-excel-addin's research workspace. Specifically:

1. Pydantic `InvestmentIdea v1.0` in `AI-excel-addin/schema/investment_idea.py` as a 100% backward-compatible superset of today's `IdeaPayload` dataclass.
2. Enum canonicalizer extensions (`schema/enum_canonicalizers.py`) — accept Title Case input from legacy connectors and emit snake_case canonical form.
3. DB migration — `research_files` adds `idea_id TEXT`, `idea_provenance JSON`, `source_ref JSON` columns. Schema version bump to v6. Partial UNIQUE index on `idea_id WHERE idea_id IS NOT NULL` enforces "one idea_id → one research_file" identity invariant (see §6.2).
4. `ingest_idea()` migration — accepts either legacy `IdeaPayload` or new `InvestmentIdea`; auto-upcasts legacy at the boundary. Preserves the existing file-write ingest path to `tickers/{TICKER}.md` (memory-sync markdown format, NOT YAML frontmatter — see §7.2). Extends the file with three new memory-sync attribute bullets (`ingested_idea_ids`, `source_refs`, `idea_provenance_summary`) idempotently keyed by `idea_id`.
5. `start_research(idea: InvestmentIdea)` variant — new overload in AI-excel-addin REST + service layer. Seeds `research_files.{idea_id, idea_provenance, source_ref}` columns with idea metadata. Bootstraps Thesis draft with **shared-slice `thesis.{direction,strategy,conviction,timeframe}`** (on `ThesisField`, not `PositionMetadata`) + `from_idea` provenance seeded from idea. Legacy `start_research(ticker, label)` signature preserved.
6. Connector migration — 8 connectors in `AI-excel-addin/api/memory/connectors/` + 1 inline builder (`earnings_transcript`) in `investment_tools/scripts/ingest.py` emit `InvestmentIdea` with deterministic `idea_id` (UUIDv5) + populated `source_ref`. `analyst_grades` stub in same file gets shape-only update. `oi_analysis` unchanged (enrichment-only). `IdeaPayload` dataclass kept as thin shim until exit gate in §4.1 holds.
7. risk_module MCP surface — existing `start_research` MCP tool accepts optional `idea: dict` kwarg; action layer validates + dispatches. New agent-format flag set for idea-seeded research.

**Non-goals** (deferred):
- `ProcessTemplate` auto-selection from `suggested_process_template_id` — plan #5 owns the template catalog.
- Deduplication of research_files by heuristics OTHER than `idea_id` identity (e.g., semantic similarity, fuzzy ticker matching) — out of scope. **In scope** (as of R7): the partial UNIQUE index on `research_files.idea_id` in §6.2 enforces the "one idea_id → one research_file" invariant at the DB layer. `(ticker, label)` uniqueness stays as-is (already enforced by live schema).
- Unifying `tickers/*.md` ideas-inbox workspace with `research_files` DB — they stay separate (inbox = triage, research_files = committed work). Linked by `idea_id`.
- Frontend UI for idea-seeded research — deferred to research workspace follow-up.
- Removing `IdeaPayload` dataclass — shim stays until the §4.1 exit gate holds; plan #4 ships the bridge, not the removal.

---

## 2. Sub-phase summary

| # | Sub-phase | Scope | Duration | Depends on |
|---|---|---|---|---|
| A | `InvestmentIdea` Pydantic type + canonicalizers | Shape per design §6.1 + canonicalizer extensions for Title Case → snake_case | ~2 days | None (self-contained) |
| B | DB migration — `research_files` provenance columns | `idea_id TEXT`, `idea_provenance JSON`, `source_ref JSON` + partial UNIQUE index on `idea_id` + `research_handoffs` partial unique draft index + duplicate-draft sweep + schema v5→v6 | ~1.5 days | None (independent of A) |
| C | `ingest_idea()` migration — accept both IdeaPayload + InvestmentIdea | Boundary upcast + 3 new memory-sync attribute bullets in ticker markdown; idempotency via idea_id | ~2 days | A |
| D | `start_research(idea)` backend variant | AI-excel-addin REST + service + repository writes (idea_id/provenance/source_ref); Thesis bootstrap of shared-slice `thesis.{direction,strategy,conviction,timeframe}` + `from_idea`; draft handoff provenance seeding | ~3 days | A, B, plan #1, plan #2 |
| E | Connector migration — emit `InvestmentIdea` | 8 connectors in AI-excel-addin + earnings_transcript inline in investment_tools + analyst_grades stub shape update (see §9.2 live inventory); oi_analysis unchanged (enrichment-only) | ~3 days | A, C |
| F | risk_module MCP tool surface | `start_research` MCP tool accepts `idea` kwarg; actions proxy + gateway + agent flags | ~1.5 days | A, D |
| G | Tests — end-to-end provenance + round-trip | JSON round-trip, canonicalizer tests, REST integration, markdown memory-sync attribute preservation, provenance propagation to Thesis + HandoffArtifact | ~2.5 days | A, B, C, D, E, F |
| H | `SKILL_CONTRACT_MAP.md` + doc updates | InvestmentIdea row (drop "planned"); screening-skill rows annotated as idea producers; cross-repo refs | ~0.5 day | G |

**Total**: ~16 working days. Parallelism: A/B parallel; C after A; D after A+B + plan #1/#2 (Thesis + HandoffArtifact must exist to bootstrap); E after A+C; F after A+D; G after A–F; H after G.

---

## 3. Dependency graph

```
Plan #1 + Plan #2 (implemented)   ◄── hard prereqs for D
   │
   ▼
┌───────┬─────────────┐
│   A   │      B      │  A = Pydantic type + canonicalizers
│       │             │  B = DB migration (research_files cols + v5→v6)
└───┬───┴──────┬──────┘
    │          │
    ▼          ▼
    C          D          C = ingest_idea accepts both types
    │          │          D = start_research(idea) backend
    ▼          │
    E          │          E = connector migration (8 connectors + 1 inline + stub — see §9)
    │          │
    │          ▼
    │          F          F = risk_module MCP surface
    │          │
    └──────┬───┘
           ▼
           G              G = end-to-end tests + round-trip
           │
           ▼
           H              H = SKILL_CONTRACT_MAP + docs
```

D requires plan #1 (Thesis bootstrap) and plan #2 (HandoffArtifact v1.1 `idea_provenance` field) to already be implemented. A/B/C/E can drop earlier against the schema design doc alone.

---

## 4. Cross-cutting concerns

### 4.1 Backward compatibility — IdeaPayload shim

Plan #4 does NOT remove `IdeaPayload` (`AI-excel-addin/api/memory/ingest.py:20-93`). It introduces `InvestmentIdea` as a superset and converts legacy payloads at the `ingest_idea()` boundary:

```python
def ingest_idea(payload: IdeaPayload | InvestmentIdea, workspace_dir: Path) -> dict:
    if isinstance(payload, IdeaPayload):
        idea = InvestmentIdea.from_idea_payload(payload)  # upcasts, mints idea_id
    else:
        idea = payload
    # ... existing file-write logic, extended with three new memory-sync bullets
    # (ingested_idea_ids, source_refs, idea_provenance_summary) rendered under
    # `## {TICKER}` per the live format at markdown_sync.py:36. See §7 for detail.
```

`InvestmentIdea.from_idea_payload(payload)` handles:
- Enum canonicalization (Title Case → snake_case)
- Deterministic `idea_id` minting (see §4.2)
- Empty-but-required `source_ref` fallback (`type="manual"`, `source_repo="manual"`, `source_id=f"legacy:{payload.source}:{payload.ticker}:{payload.source_date.isoformat()}:{sha256(payload.thesis || payload.catalyst || payload.strategy)[:8]}"` — see §4.2 for the exact `_legacy_content_hash()` helper and the rationale for the content-hash discriminator)

Connectors keep calling `ingest_idea(payload)` unchanged; migration to native `InvestmentIdea` happens incrementally in sub-phase E. Plan #4 ships both paths working.

**Shim exit gate** (concrete, testable): the shim is retired when

Working directory: **this repo's root** (`~/Documents/Jupyter/risk_module/`, where this plan lives). The `../` prefixes resolve to the sibling repos from here. Command:

```
rg "IdeaPayload" \
  --glob '!**/chat_logs/**' \
  --glob '!**/*.jsonl' \
  ../AI-excel-addin/api ../AI-excel-addin/tests ../investment_tools/scripts/ingest.py
```

(If running from a different cwd, swap the `../` prefixes for the absolute paths: `~/Documents/Jupyter/AI-excel-addin/api`, etc. The rule is to scan the three live-code trees wherever they live.)

The gate holds when the output returns ONLY: (a) the dataclass definition itself in `api/memory/ingest.py`, (b) `InvestmentIdea.from_idea_payload` classmethod + its tests, (c) the `ingest_idea()` upcast branch that accepts legacy `IdeaPayload` (the boundary adapter is explicitly in scope until retirement — it's the rollback mechanism per §9.5), (d) an external-compatibility re-export banner if any. Exclude `chat_logs/*.jsonl` from the check scope — those are historical conversation transcripts, not live code. After sub-phase E commits, this gate should hold; open a follow-up `IDEAPAYLOAD_RETIREMENT_PLAN.md` only if other hits remain. No calendar-driven "one release cycle" language.

**Rollout strategy for sub-phase E** (aligned with §9.5): per-site commits, reviewer-inspectable individually. Half-migrated states are explicitly valid — the `from_idea_payload()` upcast at the `ingest_idea()` boundary keeps ingestion working whether a given connector has migrated or not. Per-source feature flags are NOT needed because the boundary upcast already absorbs call-site compatibility. If a specific connector breaks during migration, revert only that connector's commit; the shim picks up the slack. No single atomic commit across 9 sites is required, and no staged-rollout flag system is added.

### 4.2 Deterministic idea_id minting

`idea_id` is UUIDv5. Namespace is a **pinned committed UUID constant**. Name derives from the stable origin reference the plan already tracks (`source_ref.source_repo` + `source_ref.source_id`), NOT from `{source|ticker|source_date}` (which would collide when two distinct ideas share source/ticker/date but come from different rows — quality screen top-100 on the same day, for example).

```python
# AI-excel-addin/schema/investment_idea.py
_IDEA_NAMESPACE = uuid.UUID("21befb5d-e5c9-4800-ae8c-e3dcc595b17e")  # pinned 2026-04-21

class InvestmentIdea(BaseModel):
    @classmethod
    def mint_idea_id(cls, source_repo: str, source_id: str) -> str:
        """Deterministic UUIDv5 minted from stable origin reference.

        Same (source_repo, source_id) → same idea_id across all runs and processes.
        Callers supply source_id that uniquely identifies the origin row
        (e.g., "screen:quality:2026-04-21:0" — the exact source_ref.source_id
        the connector will emit).
        """
        name = f"{source_repo.strip().lower()}|{source_id.strip()}"
        return str(uuid.uuid5(_IDEA_NAMESPACE, name))
```

**Why `source_ref.source_id` not `{source|ticker|source_date}`**: the design doc §6.1 already commits connectors to a per-row stable `source_id` format (see §9.2 table — e.g., `screen:quality:2026-04-21:17` for row 17 of quality screen on that date). `source_id` is already unique by construction. Using it eliminates collision risk from multiple ideas sharing (source, ticker, date).

**Legacy IdeaPayload upcast — deterministic fallback with per-payload discriminator**: when `from_idea_payload(payload)` upcasts legacy (no `source_ref` yet), it synthesizes a source_id that includes a content-addressed discriminator so multi-idea-per-key emitters (e.g., `earnings_transcript` at `investment_tools/scripts/ingest.py:946` which iterates catalysts and emits multiple payloads sharing `(source, ticker, date)`) don't collide:

```python
import hashlib

def _legacy_content_hash(payload: IdeaPayload) -> str:
    # Stable content hash over payload fields that distinguish multi-idea-per-key
    # emitters. `thesis` is the strongest discriminator (per-catalyst text in the
    # earnings_transcript case); `catalyst` + `strategy` are secondary.
    payload_body = "\x1f".join([
        (payload.thesis or "").strip(),
        (payload.catalyst or "").strip(),
        (payload.strategy or "").strip(),
    ])
    return hashlib.sha256(payload_body.encode("utf-8")).hexdigest()[:8]

source_ref = SourceRef(
    type="manual",
    source_repo="manual",
    source_id=f"legacy:{payload.source}:{payload.ticker}:{payload.source_date.isoformat()}:{_legacy_content_hash(payload)}",
)
idea_id = InvestmentIdea.mint_idea_id("manual", source_ref.source_id)
```

**Collision semantics after discriminator**:
- Same payload (same thesis + catalyst + strategy) re-upcast → same source_id → same idea_id (idempotent). Matches test expectation in §5.4 + Scenario 4 in §11.
- Two distinct catalyst-derived payloads from one `earnings_transcript` run → different `thesis` text → different content hash → different idea_ids. No collapse.
- Payload with identical thesis/catalyst/strategy across two legacy emitters of the same (source, ticker, date) is a pathological dup — collapses to one idea, which is correct by de facto identity.
- Different connectors emitting same ticker/date legacy-style → distinct via the embedded `source` string.

Cost of the discriminator: the legacy idea_id is a deterministic function of payload BODY, not just identity metadata. If a legacy connector edits the thesis text between runs, the idea_id changes. This is ACCEPTABLE because (a) the sub-phase E migration replaces legacy emitters with native InvestmentIdea that carries a stable `source_ref.source_id` independent of body text, and (b) edit-the-thesis-and-re-emit is not a supported legacy workflow (the connector would write a new row, not mutate an old one). Flag for monitoring only; no additional mitigation in plan #4.

**API alignment**: `mint_idea_id()` is a `@classmethod` on `InvestmentIdea`. Both §5.2 (schema) and §9.2 (connector migration) reference this exact signature.

### 4.3 Thesis + HandoffArtifact provenance propagation

When `start_research(idea)` runs:

1. **research_files row** — `idea_id`, `idea_provenance` (JSON: full `InvestmentIdea` snapshot), `source_ref` (JSON: the `source_ref` sub-object for query-side lookup) are written. See §4.4 for why both columns exist.
2. **Thesis draft** (via `thesis_service.bootstrap_from_idea(research_file_id, idea)`) — if no Thesis exists for this research_file, one is bootstrapped with the idea's analyst-facing header fields seeded onto `Thesis.thesis` (the `ThesisField` at `AI-excel-addin/schema/thesis_shared_slice.py:90-95`):
   - `thesis.statement = ""` (user authors during thesis-consultation; idea.thesis is NOT auto-written into the SoT to avoid putting unvetted prose there)
   - `thesis.direction = idea.direction` (shared-slice, canonicalized)
   - `thesis.strategy = idea.strategy` (shared-slice, canonicalized)
   - `thesis.conviction = idea.conviction` (shared-slice)
   - `thesis.timeframe = idea.timeframe` (shared-slice, canonicalized)
   - `from_idea = {idea_id, thesis_hypothesis: idea.thesis, seeded_at}` — a NEW top-level Thesis field (see §4.6) that parks the idea's initial hypothesis for analyst reference without writing it into the SoT text.

   **Target fields are the existing shared-slice `ThesisField` members**, not `PositionMetadata` (which has only `{position_size, date_initiated, portfolio_fit}`). `timeframe` already exists on `ThesisField`; plan #4 does NOT introduce it. This also means the seeded enum fields propagate to `HandoffArtifact.thesis.{direction,strategy,conviction,timeframe}` naturally via the existing shared-slice derivation (`_shared_slice_from_payload` at `api/research/handoff.py:716`) — no extra handoff wiring needed for these fields.

3. **HandoffArtifact.idea_provenance — projection, not copy**. The live handoff-side type is:
   ```python
   class IdeaProvenance(_ContractModel):  # AI-excel-addin/schema/handoff.py:42-49
       idea_id: str
       source_summary: str
   ```
   — two fields, NOT a full `InvestmentIdea` snapshot. Plan #4 defines a projection function `project_to_handoff_idea_provenance(idea: InvestmentIdea) → IdeaProvenance` that computes:
   ```python
   IdeaProvenance(
       idea_id=idea.idea_id,
       source_summary=f"{idea.source_ref.type}:{idea.source_ref.source_repo}:{idea.source_ref.source_id}",
   )
   ```
   The projection lives in `AI-excel-addin/schema/investment_idea.py` next to the canonical type.

4. **Draft handoff seeding hook**. Live draft-artifact creation at `api/research/repository.py:389` (`_build_initial_handoff_artifact`) sets `idea_provenance = None`, and the finalize path at `api/research/handoff.py:718` pass-through copies `draft_artifact.idea_provenance` as-is. Plan #4 sub-phase D bridges the gap by calling `repository.update_idea_provenance(handoff_id, projection.model_dump())` (live method at `repository.py:2320`) after `start_research(idea)` seeds the research_file. Flow:
   - `start_research(idea)` → `get_or_create_draft_handoff(research_file_id)` (existing) → `update_idea_provenance(handoff_id, projection)` (existing). No new draft-builder logic — just the new call.
   - When the first handoff artifact is finalized later, the pass-through at `handoff.py:718` carries the provenance into the final artifact. Closes G14 end-to-end with NO change to the finalize path.

5. **Invariant**: `research_files.idea_provenance` carries the full `InvestmentIdea` snapshot (for audit, plan #5 template selection, etc.). `HandoffArtifact.idea_provenance` carries the 2-field projection (for snapshot-bound handoff consumption). They are NOT the same shape — plan #4 is explicit about this and adds a schema test (sub-phase G) asserting the projection invariant.

### 4.4 `idea_provenance` vs `source_ref` — why both columns on `research_files`

Design §6.1 puts `source_ref` as a nested field on `InvestmentIdea`. Storing BOTH a full-idea snapshot (`idea_provenance` TEXT/JSON) and a separated `source_ref` column (TEXT/JSON) on `research_files` enables:

- **`research_files.idea_provenance`** — full `InvestmentIdea` snapshot. Never mutates after seed. Used by audit trails and plan #5 template-selection logic (which reads `suggested_process_template_id`, `related`, `metadata` sub-fields).
- **`research_files.source_ref`** — convenience column exposing the `source_ref` sub-object without requiring consumers to parse the full `idea_provenance` JSON blob. NOT indexed for hot-path lookup in plan #4 (SQLite TEXT + no expression index on `source_repo`/`source_id`). If a later plan needs indexed lookup by `source_repo|source_id`, it can add generated columns or an expression index; plan #4 does not.

**Consistency invariant**: `research_files.source_ref` == `research_files.idea_provenance.source_ref` (the sub-object). Sub-phase D enforces via a single write path (`repository.seed_research_file_from_idea`) that splits the canonical `InvestmentIdea` into both columns atomically.

**Distinction from `HandoffArtifact.idea_provenance`** (per §4.3 finding #2): the research_files table stores the full snapshot; the HandoffArtifact stores the projection (`{idea_id, source_summary}`). Different shapes, different layers, different purposes. Projection happens at draft-handoff seed time via `project_to_handoff_idea_provenance()`.

### 4.5 Enum canonicalization — new canonicalizers

Plan #1's `schema/enum_canonicalizers.py` defined canonicalizers for Thesis/HandoffArtifact fields (direction/strategy/timeframe). Plan #4 extends the same module with input-side canonicalizers that accept the Title Case literals connectors emit today:

| Field | Accepted input (case-insensitive) | Canonical output |
|---|---|---|
| `direction` | `Long`, `Short`, `Hedge`, `Pair` | `long`, `short`, `hedge`, `pair` |
| `strategy` | `Value`, `Special Situation`, `Macro`, `Compounder` | `value`, `special_situation`, `macro`, `compounder` |
| `timeframe` | `Near-term`, `Medium`, `Long-term` | `near_term`, `medium`, `long_term` |

The canonicalizers are idempotent — passing `"long"` in yields `"long"`, passing `"Long"` in yields `"long"`. Whitespace and case are tolerant. Invalid inputs raise `InvalidEnumValueError` (existing plan #1 type).

**Why extend plan #1's module, not a new module**: Thesis and InvestmentIdea share these enum shapes. Single source of truth avoids drift. Plan #1's module has room (it's ~150 lines today) and the test suite naturally extends.

### 4.6 Thesis `from_idea` field — NEW top-level addition

Plan #4 adds one NEW field to `Thesis` (beyond what plan #1 shipped):

```python
class ThesisFromIdea(_ContractModel):
    idea_id: str
    thesis_hypothesis: str       # copy of InvestmentIdea.thesis at seed time — analyst reference
    seeded_at: str               # ISO-format timestamp (matches existing Thesis timestamp convention)
    schema_version: Literal["1.0"] = "1.0"

class Thesis(_ContractModel):
    # ... existing fields from plan #1
    from_idea: ThesisFromIdea | None = None
```

This is NOT shared-slice (HandoffArtifact has its own `idea_provenance` IdeaProvenance field — see §4.3 finding #2 — with a different 2-field shape). `from_idea` is Thesis-local, optional, written once at seed time, never updated. The `_shared_slice.SHARED_SLICE_FIELD_PATHS` registry is NOT amended — the isomorphism invariant holds.

**Blast radius — must be updated in sub-phase D, not post-hoc** (R1 blocker #7):

1. **`schema/thesis.py`** — add `ThesisFromIdea` class + `from_idea: ThesisFromIdea | None = None` on `Thesis`. ~20 lines.
2. **`schema/__init__.py`** — re-export `ThesisFromIdea`. ~1 line.
3. **`tests/integration/test_shared_slice_isomorphism.py`**:
   - Add `"from_idea"` to `THESIS_ONLY_FIELD_PATHS` at line 42 (keeps the boundary test passing: from_idea is thesis-only, not shared-slice).
   - Update `test_total_field_count` at line 190: `len(Thesis.model_fields) == 32 → 33`. HandoffArtifact field count unchanged at 28.
4. **`tests/schema/snapshots/thesis_v1_0.schema.json`** — regenerate to include `from_idea` and `ThesisFromIdea`. Plan #1's snapshot-update workflow applies (`pytest --update-snapshots`); the snapshot delta is reviewable (single additive field + one nested type).
5. **`schema/thesis_markdown.py`** — plan #1's markdown serializer/parser. `from_idea` round-trips using the same pattern plan #1 established for `model_ref` (thesis markdown is its own format distinct from the memory-sync ticker-inbox markdown in §7). ~30 lines of serializer + parser symmetry, plus round-trip fixture.
6. **`tests/schema/test_thesis_markdown.py`** — add markdown round-trip test for `from_idea`. ~40 lines.

**Sub-phase D file list in §8.3 includes all six items.** No schema version bump: `from_idea` is additive-optional — Thesis stays at schema_version `"1.0"` per plan #1's additive-compat rule.

**Alternative considered, rejected**: store `{idea_id, thesis_hypothesis, seeded_at}` on `research_files` instead of `Thesis`. Loses the "thesis carries its origin" ergonomic — analyst/skill surfaces would need to cross-join research_files to read the idea hypothesis while composing thesis text. The Thesis-local approach keeps the relevant context next to the composition target at the cost of the boundary-test update above.

### 4.7 Cross-plan alignment

- **Plan #1**: plan #4 sub-phase D writes to shared-slice `Thesis.thesis.{direction,strategy,conviction,timeframe}` (via `thesis_service.bootstrap_from_idea`) and Thesis-local `Thesis.from_idea` (new field). `PositionMetadata` is NOT touched. No other plan #1 surfaces touched.
- **Plan #2**: plan #4 sub-phase D seeds `research_files.idea_provenance` (full snapshot) AND the draft handoff's `idea_provenance` (2-field projection via existing `repository.update_idea_provenance` at `repository.py:2320`). Plan #2's finalize pass-through at `handoff.py:718` then carries the projection into the finalized artifact unchanged. Plan #4 does NOT re-define the `IdeaProvenance` shape — plan #2's `{idea_id, source_summary}` spec is authoritative.
- **Plan #3**: no interaction. ModelBuildContext is downstream of HandoffArtifact; idea provenance flows through to MBC only via the HandoffArtifact pass-through (MBC does not read idea fields directly).
- **Plan #5 (future)**: `suggested_process_template_id` on `InvestmentIdea` is a hint consumed by ProcessTemplate selection. Plan #4 persists it in `idea_provenance` but does NOT act on it — acting is plan #5's scope.
- **Plan #6 (future)**: `ModelInsights` / `PriceTarget` — no direct interaction. Idea provenance sits upstream of the model layer.

---

## 5. Sub-phase A — `InvestmentIdea` Pydantic type + canonicalizer extensions

### 5.1 Goal

Pydantic v2 type in `AI-excel-addin/schema/investment_idea.py` matching design §6.1 shape. Plus canonicalizer extensions for Title Case → snake_case input tolerance.

### 5.2 Design

```python
class SourceRef(BaseModel):
    type: Literal["screen", "finding", "manual", "newsletter", "research_note", "external"]
    source_id: str                      # stable ref back to origin row
    source_repo: Literal["investment_tools", "manual", "external"]
    source_payload: dict[str, Any] | None = None  # raw-ish original payload (typed where possible)
    model_config = ConfigDict(frozen=True)

class InvestmentIdeaRelated(BaseModel):
    findings: list[str] = Field(default_factory=list)      # finding_ids
    screen_hits: list[str] = Field(default_factory=list)   # screen_hit_ids
    annotations: list[str] = Field(default_factory=list)   # annotation_ids
    model_config = ConfigDict(frozen=True)

class InvestmentIdea(BaseModel):
    # Required baseline
    ticker: str                          # [A-Z]{1,6}, normalized via validator
    thesis: str                          # prose — initial hypothesis; non-empty after strip
    source: str                          # pipeline identifier (e.g., "screen:quality")
    source_date: date                    # ISO date

    # Optional baseline (existed on IdeaPayload)
    company_name: str | None = None
    strategy: Literal["value", "special_situation", "macro", "compounder"] | None = None
    direction: Literal["long", "short", "hedge", "pair"] = "long"
    catalyst: str | None = None
    timeframe: Literal["near_term", "medium", "long_term"] | None = None
    conviction: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] = Field(default_factory=list)

    # NEW — provenance
    idea_id: str                         # stable UUIDv5; minted deterministically (§4.2)
    surfaced_at: datetime                # ≥ source_date (as datetime)
    source_ref: SourceRef

    # NEW — cross-linkage
    related: InvestmentIdeaRelated = Field(default_factory=InvestmentIdeaRelated)

    # NEW — process linkage
    suggested_process_template_id: str | None = None
    label: str | None = None             # for multi-thesis concurrency: research_files.label

    # NEW — metadata
    metadata: dict[str, Any] = Field(default_factory=dict)

    schema_version: Literal["1.0"] = "1.0"

    @field_validator("ticker", mode="before")
    @classmethod
    def _normalize_ticker(cls, v: object) -> str:
        # Use the canonical normalizer already in use for IdeaPayload / Thesis /
        # HandoffArtifact (strips .L/.TO/.A/etc., enforces ^[A-Z]{1,6}$).
        from api.memory.ticker_utils import TICKER_RE, normalize_ticker
        cleaned = normalize_ticker(str(v or ""))
        if not TICKER_RE.match(cleaned):
            raise ValueError(f"invalid ticker after normalization: {v!r} -> {cleaned!r}")
        return cleaned

    @field_validator("thesis", "source")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("must be non-empty")
        return v

    @field_validator("strategy", mode="before")
    @classmethod
    def _canonicalize_strategy(cls, v: Any) -> Any:
        return canonicalize_strategy(v) if v is not None else None  # from enum_canonicalizers

    @field_validator("direction", mode="before")
    @classmethod
    def _canonicalize_direction(cls, v: Any) -> Any:
        return canonicalize_direction(v) if v is not None else "long"

    @field_validator("timeframe", mode="before")
    @classmethod
    def _canonicalize_timeframe(cls, v: Any) -> Any:
        return canonicalize_timeframe(v) if v is not None else None

    @model_validator(mode="after")
    def _surfaced_at_ge_source_date(self) -> "InvestmentIdea":
        if self.surfaced_at.date() < self.source_date:
            raise ValueError("surfaced_at must be on or after source_date")
        return self

    @classmethod
    def mint_idea_id(cls, source_repo: str, source_id: str) -> str:
        """Deterministic UUIDv5 from (source_repo, source_id). See §4.2."""
        ...

    @classmethod
    def from_idea_payload(cls, payload: "IdeaPayload", source_payload: dict | None = None) -> "InvestmentIdea":
        """Upcast legacy IdeaPayload to InvestmentIdea. Synthesizes source_ref
        with a content-hash discriminator so multi-idea-per-key emitters (e.g.,
        earnings_transcript) don't collapse:
          type=manual, source_repo=manual,
          source_id=f"legacy:{payload.source}:{payload.ticker}:{payload.source_date.isoformat()}:{_legacy_content_hash(payload)}"
        where _legacy_content_hash() is sha256(thesis || catalyst || strategy)[:8]
        per §4.2. Mints deterministic idea_id from that source_ref; sets
        surfaced_at = now (UTC)."""
        ...

    model_config = ConfigDict(frozen=True)
```

**Freezing**: `InvestmentIdea` and all nested types are `frozen=True` — once constructed, immutable. Same policy as plan #1's `Thesis` immutable header types.

### 5.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `AI-excel-addin/schema/investment_idea.py` | `InvestmentIdea` + `SourceRef` + `InvestmentIdeaRelated` | ~220 |
| `AI-excel-addin/schema/enum_canonicalizers.py` | **Extend** — add input-tolerant canonicalizers | ~+80 lines to existing file |
| `AI-excel-addin/tests/schema/test_investment_idea.py` | Pydantic unit tests | ~280 |

### 5.4 Tests (~28)

- Required-field validation (ticker, thesis, source, source_date, idea_id, surfaced_at, source_ref) — happy path + each missing (~8)
- Ticker normalization delegates to `normalize_ticker()` — `BP.L → BP`, `BRK.A → BRKA`, `AAPL → AAPL`. Uppercase, suffix strip, share-class flatten all tested via the existing utility's contract (3 cases + 1 invalid post-normalization input).
- `thesis`/`source` strip + non-empty enforcement (2)
- Enum canonicalizer tolerance: each of strategy/direction/timeframe accepts Title Case + snake_case + lowercase (9)
- `conviction` range [1,5] (2)
- `surfaced_at >= source_date` (2, positive + negative)
- `from_idea_payload()` upcast preserves all fields + mints deterministic idea_id (same inputs → same id) (2)

### 5.5 Risks

- **Canonicalizer edge cases**: "Long-Term" (capital T) vs "Long-term" — must be case-insensitive across hyphens. Test matrix explicit. Live `canonicalize_optional_direction/strategy/timeframe` already handle some cases (see `schema/enum_canonicalizers.py` from plan #1); plan #4 extends to cover the full Title Case → snake_case matrix connectors emit.
- **`source_payload: dict[str, Any]`**: Pydantic freezes dicts by default when frozen=True — but `dict[str, Any]` is NOT frozen. Accept MappingProxyType or convert to frozendict? Decision: accept dict, rely on Pydantic's "don't mutate after validation" convention. Not load-bearing for correctness.
- **Namespace UUID lock-in**: `_IDEA_NAMESPACE` is committed at `21befb5d-e5c9-4800-ae8c-e3dcc595b17e` (minted 2026-04-21 for plan #4). Any change to this constant post-merge invalidates all existing idea_ids. Treat as immutable. If a collision or security issue ever requires rotation, that's a data migration, not a constant update.

---

## 6. Sub-phase B — DB migration + schema v5→v6

### 6.1 Goal

Extend `research_files` table to carry idea provenance. Bump per-user SQLite schema version from v5 (plan #3's bump) to v6.

### 6.2 Design

Three new columns on `research_files`:

```sql
ALTER TABLE research_files ADD COLUMN idea_id TEXT;
ALTER TABLE research_files ADD COLUMN idea_provenance TEXT;     -- JSON blob
ALTER TABLE research_files ADD COLUMN source_ref TEXT;          -- JSON blob (source_ref sub-object)
CREATE UNIQUE INDEX idx_research_files_idea_id_unique ON research_files(idea_id) WHERE idea_id IS NOT NULL;
```

**Why UNIQUE, not just indexed** (R7 finding #1): §8.2's identity-resolution invariant is "one `idea_id` → at most one `research_file`". Live table already enforces `UNIQUE(ticker, label)`, which is insufficient — two concurrent `start_research(idea)` calls for the SAME `idea_id` but DIFFERENT labels would both miss the step 3.1 lookup and each succeed at creating a distinct `research_files` row (different `(ticker, label)`). The partial UNIQUE index on non-null `idea_id` closes this race at the DB level: one of the two inserts wins, the other raises a constraint violation, which the service layer maps to the idempotent "reuse existing" branch (step 3.1). Partial (`WHERE idea_id IS NOT NULL`) keeps legacy idea-less rows unaffected.

SQLite does NOT have JSON column type — we use TEXT with JSON-serialized content (matches plan #3 precedent at `model_build_contexts.mbc_json TEXT`). Validation + serialization happens in the repository layer (sub-phase D).

**Partial index** on `idea_id` — only rows with populated `idea_id` are indexed. Existing pre-v6 rows (no idea_id) are excluded. Keeps index compact.

**Schema version table**: existing `schema_version` row updated v5 → v6. Migration is idempotent — running twice is a no-op (check column existence before `ALTER TABLE`).

### 6.3 Files to modify

| File | Change | Est. lines |
|---|---|---|
| `AI-excel-addin/api/research/repository.py` | Migration logic in `_maybe_migrate()` at `repository.py:917` (v5 → v6 branch); new repo methods `update_research_file_provenance(...)` + `get_research_file_by_idea_id(...)`; partial unique index on `research_handoffs(research_file_id) WHERE status='draft'` (see §8.5) | ~+140 |
| `AI-excel-addin/tests/api/research/test_repository_schema.py` | Migration round-trip + new method tests (matches live test tree at `tests/api/research/`) | ~+150 |

### 6.4 Tests (~18)

- Fresh v6 schema creation: columns present, `idx_research_files_idea_id_unique` (partial UNIQUE) + `idx_research_handoffs_unique_draft` indexes present (3)
- **Partial UNIQUE on `idea_id` blocks duplicate insertion**: seed a row with `idea_id='X'`; attempt INSERT of another row with `idea_id='X'` (different ticker/label) → assert `IntegrityError`. Rows with `idea_id IS NULL` remain unaffected (insert two NULL-idea-id rows with distinct ticker/label succeeds). (1)
- v5 → v6 migration: fixture DB seeded at v5, migration runs, columns added, existing rows have NULL provenance (2)
- Idempotent migration: run migration twice, no error, no duplicate columns, no duplicate indexes (1)
- `update_research_file_provenance()` round-trip: write then read, JSON fidelity preserved (2)
- `get_research_file_by_idea_id()` happy path + miss (2)
- Partial `idea_id` index actually filters NULL `idea_id` (sanity via `EXPLAIN QUERY PLAN`) (1)
- **TOCTOU duplicate-draft sweep** (new, per R5 finding #3):
  - Seed pre-v6 fixture with N duplicate `research_handoffs` rows having `(research_file_id=X, status='draft')`; run migration; assert oldest-id draft survives, newer duplicates status-transitioned to `'superseded'`, and exactly one new `research_file_history` row exists with `event_type='migration_duplicate_draft_sweep'`, `research_file_id=X`, and `changes={"kept_handoff_id": <min_id>, "superseded_handoff_ids": [<other_ids>...]}`. (1)
  - After migration, attempt `INSERT INTO research_handoffs (..., status='draft', research_file_id=X)` with X already having a draft → assert unique-index constraint violation. (1)
  - Edge case: pre-v6 fixture with ZERO duplicates → migration runs clean, no status transitions, no log entries. (1)
- Schema version row updated to v6 (1)
- Rollback behavior — migration failure mid-flight leaves schema_version at v5 (transaction) (2)

### 6.5 Risks

- **Alter-add column on large tables**: SQLite `ALTER TABLE ADD COLUMN` is O(1) in modern SQLite. Non-issue for per-user DBs (small row counts).
- **Partial index syntax**: `CREATE INDEX ... WHERE` is supported from SQLite 3.8+. All target environments are well past. Assert version in migration or rely on failure surfacing.

---

## 7. Sub-phase C — `ingest_idea()` accepts both types

### 7.1 Goal

`ingest_idea()` accepts `IdeaPayload | InvestmentIdea`. Upcasts legacy at the boundary. Extends the existing **file-write** ingest path at `api/memory/ingest.py:95` with three new memory-sync attribute bullets in the ticker markdown. Idempotent on same `idea_id`.

### 7.2 Storage model — stay on the live file-write path

Ticker files are memory-sync markdown per `AI-excel-addin/api/memory/markdown_sync.py:16`. Format:

```
<!-- memory-sync: {sync_key} -->
<!-- edit freely - changes sync on server restart -->
<!-- format: ## entity header, then - **attribute**: value bullets -->
<!-- multi-line: indent continuation lines with 2 spaces -->

## {TICKER}

- **thesis** (updated 2026-04-21): ...
- **source** (updated 2026-04-21): screen:quality
- **direction** (updated 2026-04-21): long
- ...
```

**Live data flow is file-first, watcher imports to store — not the other way around**. `api/memory/watcher.py:214` imports ticker markdown into `MemoryStore` via `import_markdown()`. `markdown_sync.export_markdown()` (at `markdown_sync.py:64`) renders the store back to markdown, but is only called explicitly (e.g., from admin flows), not as a live watcher. Current `ingest_idea()` at `api/memory/ingest.py:95` writes the markdown file directly. Plan #4 stays on that path — we append/update bullets in the file, the watcher imports to the store, and downstream consumers (e.g., memory tools, chat context) see the new attributes via the store naturally.

`MemoryStore`'s live API only exposes `store_memory / delete_memory / get_memories / get_all_memories` (see `api/memory/store.py:316`). Plan #4 does NOT assume per-attribute helpers (`get_attribute/set_attribute` are NOT in the live API). Sub-phase C touches `ingest.py` only — no store API additions, no new export step.

**New bullets appended by `ingest_idea()` on each call**:

| Attribute bullet (rendered as `- **{name}** (updated YYYY-MM-DD): {value}`) | Value format | Semantics |
|---|---|---|
| `ingested_idea_ids` | sorted, comma-joined: `id1,id2,id3` | append-on-ingest, deduped by set membership; new value emitted only if set actually changes (avoids no-op `updated_at` bumps) |
| `source_refs` | multi-line attribute value — one JSON object per line; each line = `{"type": ..., "source_repo": ..., "source_id": ..., "source_payload": {...}}` (continuation lines indented per `markdown_sync.py:48`); `source_payload` is preserved verbatim from the connector-emitted `SourceRef.source_payload` | append-on-ingest, dedup by `source_repo+source_id` (payloads from the first-seen copy win; no merging of duplicate source_payloads) |
| `idea_provenance_summary` | multi-line attribute — one line per ingested idea; each line = `"{idea_id} : Seeded from {source_ref.type}:{source_ref.source_id} on {source_date}"` (continuation lines indented per `markdown_sync.py:48`). Append-on-ingest, dedup by `idea_id`. | parallels `source_refs` / `ingested_idea_ids`; re-ingest of same idea_id short-circuits before any write (§7.3), so no duplicate lines; distinct ideas for the same ticker append new lines |

`ingested_idea_ids` is the primary idempotency key — the existing `source_log_*` attribute family stays as the audit trail (per `tests/test_connectors.py` and ingest tests). Plan #4 does NOT alter `source_log_*` behavior.

### 7.3 Ingest function signature

```python
def ingest_idea(
    payload: IdeaPayload | InvestmentIdea,
    workspace_dir: Path,
) -> dict:
    """Ingest an idea into the memory-sync ticker markdown file."""
    if isinstance(payload, IdeaPayload):
        idea = InvestmentIdea.from_idea_payload(payload)
    else:
        idea = payload

    ticker_md = workspace_dir / "tickers" / f"{idea.ticker}.md"

    # Parse existing bullets (via BULLET_RE at markdown_sync.py:14) if file exists
    existing_attrs = _parse_existing_ticker_bullets(ticker_md) if ticker_md.exists() else {}
    existing_idea_ids = _split_comma_list(existing_attrs.get("ingested_idea_ids"))
    if idea.idea_id in existing_idea_ids:
        return {"status": "success", "action": "skipped_duplicate", "idea_id": idea.idea_id}

    # Merge the three new attribute bullets into the existing attribute set
    new_attrs = dict(existing_attrs)
    new_attrs["ingested_idea_ids"] = ",".join(sorted(existing_idea_ids | {idea.idea_id}))
    new_attrs["source_refs"] = _merge_source_refs(existing_attrs.get("source_refs"), idea.source_ref)
    new_attrs["idea_provenance_summary"] = _merge_provenance_summary_line(
        existing_attrs.get("idea_provenance_summary"),
        idea_id=idea.idea_id,
        source_ref=idea.source_ref,
        source_date=idea.source_date,
    )  # returns multi-line string; appends new line dedup-by-idea_id

    # Plus existing per-attribute writes (thesis, source, direction, strategy, ...)
    # — unchanged from today's ingest behavior, still written in the same call.
    new_attrs.update(_idea_to_attr_dict(idea))

    # Append a timestamped source_log entry (existing behavior, unchanged)
    new_attrs.update(_new_source_log_entry(idea, existing_attrs))

    # Atomic file write via the live helper used by existing ingest:
    # _plain_atomic_write() at AI-excel-addin/api/memory/ingest.py:244.
    # Reuse verbatim. Do NOT introduce markdown_sync._atomic_write (different
    # call sites) or a new primitive.
    _render_and_write_ticker_markdown(ticker_md, idea.ticker, new_attrs)

    return {"status": "success", "action": "ingested", "idea_id": idea.idea_id}
```

**No new store API**. The watcher picks up the file write and imports to `MemoryStore` on its own cadence — that path already exists. No explicit `export_markdown()` call.

**Concurrency**: today's ingest uses `_plain_atomic_write()` at `AI-excel-addin/api/memory/ingest.py:244` (tmpfile + rename). Two concurrent ingests of the same ticker serialize through the filesystem rename. Race between read-existing-bullets and write-new-file can lose an idempotency check for same-idea concurrent ingests — but that's the identity case where both writes produce the same final attribute set (stable idea_id, same source_refs merge outcome). Not load-bearing. Sub-phase C reuses `_plain_atomic_write()` verbatim; do NOT introduce a lock primitive or switch to `markdown_sync._atomic_write` (those are different call sites).

### 7.4 Files to modify

| File | Change | Est. lines |
|---|---|---|
| `AI-excel-addin/api/memory/ingest.py` | Accept union type, route through upcast, extend file-write with three new bullets (idempotent merge) | ~+100 |
| `AI-excel-addin/api/memory/markdown_sync.py` | No changes | 0 |
| `AI-excel-addin/api/memory/store.py` | No changes (no new API surface) | 0 |
| `AI-excel-addin/tests/test_ingest.py` | Dual-type tests + idempotency; new bullet assertions; atomic-write regression | ~+150 |

### 7.5 Tests (~18)

- Ingest `IdeaPayload` (legacy): markdown file gains three new bullets (`ingested_idea_ids`, `source_refs`, `idea_provenance_summary`) with auto-minted values (3)
- Ingest `InvestmentIdea` (new): same three bullets populated from idea's own fields (3)
- Idempotency: ingest same idea_id twice → second call returns `skipped_duplicate`, bullet set unchanged, no new source_log entry, no file touch (2)
- Ingest two ideas same ticker different sources: both idea_ids present in `ingested_idea_ids` (sorted, comma-joined); both `source_refs` preserved as separate JSON lines (2)
- Legacy markdown with no `ingested_idea_ids` bullet: first re-ingest adds the three new bullets without disturbing existing bullets (1)
- Connector-emitted `source_ref.source_payload` preserved in `source_refs` JSON line (1)
- `from_idea_payload()` canonicalizes Title Case enums on upcast path (2)
- Empty `thesis` on IdeaPayload raises (validation) — upcast surfaces `ValueError` pre-ingest (1)
- `source_date` preserved through upcast (1)
- Atomic write verification: simulate crash mid-write → partial tmp file left, final `.md` unchanged (regression on the existing `_plain_atomic_write` contract at `ingest.py:244`) (1)
- Regression: existing `source_log_*` attribute behavior unchanged (1)
- Watcher round-trip: after file write, watcher's `import_markdown()` parses the new bullets successfully into `MemoryStore` without error (1)

### 7.6 Risks

- **Bullet value length**: `ingested_idea_ids` as comma-joined has a practical length concern if one ticker accumulates many ideas. Memory-sync attributes are text lines — the bullet parser (`BULLET_RE` at `markdown_sync.py:14`) treats trailing content as the value verbatim. Plan for up to 100 idea_ids per ticker (37 chars × 100 + commas = ~4KB per bullet). No pathological breakage expected; flag for monitoring.
- **Markdown diff noise on re-ingest**: even idempotent ingests could touch `updated_at` on `ingested_idea_ids` if not gated. Gate: skip the file write when the merged bullet set equals the parsed existing bullet set (string-equality check on the rendered attribute values).
- **Watcher parse of new bullets**: verify `import_markdown()` (`watcher.py:214`) doesn't reject the new attribute names (they should be accepted because `BULLET_RE` matches any `- **{name}** (...): value` shape). Sub-phase C test covers.

---

## 8. Sub-phase D — `start_research(idea)` backend variant

### 8.1 Goal

AI-excel-addin backend accepts an `InvestmentIdea` payload on the research-start path. Seeds `research_files.{idea_id, idea_provenance, source_ref}` + bootstraps Thesis draft with shared-slice `thesis.{direction,strategy,conviction,timeframe}` + `from_idea` (per §4.3). Does NOT touch `PositionMetadata`.

### 8.2 Design

**REST surface** — extend existing `POST /files` endpoint (the one `actions/research.py:start_research` already hits). Request body:

```json
{
  "ticker": "MSFT",
  "label": "",
  "idea": { ...full InvestmentIdea... }    // NEW, optional
}
```

**Top-level vs nested ticker/label rule** (R1 blocker #6): if `idea` is present, top-level `ticker`/`label` MUST match `idea.ticker`/`idea.label` (after normalization) OR one side must be omitted. Mismatch → HTTP 422 with `{error: "ticker_label_mismatch", expected: {ticker, label}, got: {ticker, label}}`. Clients SHOULD omit top-level fields when passing an idea; the endpoint accepts either form but rejects disagreement.

When `idea` is absent, endpoint behavior is unchanged (legacy `(ticker, label)` path). When `idea` is present, backend:

1. Validates `idea` → `InvestmentIdea` (422 on invalid).
2. Enforces the top-level vs nested consistency rule above.
3. **Identity resolution order** (R1 blocker #6 — single invariant, stated once):
   1. **Lookup by `(user_id, idea.idea_id)`** (exact idea_id match). If found: return the existing research_file. `existing_file_reused=true`, `idea_seeded=false` (already seeded). Do NOT re-run Thesis bootstrap. Do NOT re-update draft handoff.
   2. Else **lookup by `(user_id, ticker, label)`**:
      - If found AND `row.idea_id IS NULL`: **backfill** — set `idea_id`, `idea_provenance`, `source_ref` on the row via `update_research_file_provenance()`. Seed draft handoff `idea_provenance` (projection) via `update_idea_provenance()`. `existing_file_reused=true`, `idea_seeded=true`, `idea_backfilled=true`. Run Thesis bootstrap only if no Thesis exists yet.
      - If found AND `row.idea_id IS NOT NULL` AND `row.idea_id != idea.idea_id`: **conflict** — return HTTP 409 with `{error: "idea_conflict", existing_idea_id: row.idea_id, requested_idea_id: idea.idea_id, research_file_id: row.id}`. Do NOT overwrite, do NOT create. Caller must explicitly resolve (new label for the alternate thesis, or acknowledge + reuse the existing file without idea).
   3. Else: **create** new research_file with provenance (via `seed_research_file_from_idea`). Create draft handoff via existing flow, immediately update its `idea_provenance` to the projection. `existing_file_reused=false`, `idea_seeded=true`. Run Thesis bootstrap.
4. **Thesis bootstrap** (§4.3) runs only in steps 3.2 (backfill-and-no-thesis-yet) and 3.3 (new file). Never overwrites existing Thesis. Seeds `thesis.{direction,strategy,conviction,timeframe}` + `from_idea`.
5. **Explore/panel thread creation is NOT part of the `/files` call** — live backend at `AI-excel-addin/api/research/routes.py:476` is file-scoped. Threads are created by separate `POST /threads` calls composed in `risk_module/actions/research.py:52` today. Plan #4 preserves this — backend `/files` returns only file-scoped fields; the MCP/action layer (§10) composes file + thread fields into its unified response.

**Service layer** — new function `research_service.start_research_from_idea(user_id, idea)` does the orchestration. Repository writes via new methods `seed_research_file_from_idea()` and `update_research_file_provenance()` (sub-phase B). Draft-handoff provenance via existing `repository.update_idea_provenance(handoff_id, projection)` at `repository.py:2320`.

**Backend `POST /files` response shape — file-scoped only** (no thread fields; threads are separate calls):

```json
{
  "status": "success",
  "file": {
    "id": ..., "ticker": "MSFT", "label": "", "created_at": ...,
    "idea_id": "21befb5d-...",
    "idea_provenance": {...full InvestmentIdea snapshot...},
    "source_ref": {...source_ref sub-object...}
  },
  "idea_seeded": true,
  "idea_backfilled": false,                    // true if an existing file was backfilled (3.2)
  "existing_file_reused": false,
  "thesis_bootstrapped": true,                 // true if a new Thesis draft was created in this call
  "draft_handoff_provenance_seeded": true      // true when update_idea_provenance was called
}
```

**MCP/action-layer response** (composed after `POST /files` + `POST /threads` × 2; see §10 for action flow): adds `explore_thread_id`, `panel_thread_id`, `research_started`, `existing_file_reused` bookkeeping per live pattern at `actions/research.py:90-97`. Plan #4 threads the new idea-seeded fields through without touching thread creation.

### 8.3 Files to modify

| File | Change | Est. lines |
|---|---|---|
| `AI-excel-addin/api/research/routes.py` | `POST /files` accepts `idea` field; 422 on schema/mismatch; 409 on idea_conflict | ~+40 |
| `AI-excel-addin/api/research/research_service.py` (new or existing) | `start_research_from_idea` orchestration | ~+120 |
| `AI-excel-addin/api/research/repository.py` | `seed_research_file_from_idea()` + `update_research_file_provenance()` methods (extend sub-phase B cols) | ~+80 |
| `AI-excel-addin/api/research/thesis_service.py` | `bootstrap_from_idea(research_file_id, idea)` — idempotent (no-op if Thesis exists); seeds `thesis.{direction,strategy,conviction,timeframe}` + `from_idea` | ~+100 |
| `AI-excel-addin/schema/thesis.py` | Add `ThesisFromIdea` class + `from_idea: ThesisFromIdea | None` on `Thesis` (R1 should-fix #7 — blast radius §4.6) | ~+30 |
| `AI-excel-addin/schema/__init__.py` | Re-export `ThesisFromIdea` | ~+1 |
| `AI-excel-addin/schema/thesis_markdown.py` | `from_idea` serializer + parser (pattern match plan #1's `model_ref` handling) | ~+40 |
| `AI-excel-addin/tests/integration/test_shared_slice_isomorphism.py` | Add `"from_idea"` to `THESIS_ONLY_FIELD_PATHS`; bump `len(Thesis.model_fields) == 33` | ~+3 |
| `AI-excel-addin/tests/schema/snapshots/thesis_v1_0.schema.json` | Regenerated via `pytest --update-snapshots` | diff-reviewable |
| `AI-excel-addin/tests/schema/test_thesis_markdown.py` | `from_idea` markdown round-trip | ~+40 |
| `AI-excel-addin/tests/api/research/test_start_research_from_idea.py` | End-to-end integration tests (see §8.4); lives under live `tests/api/research/` tree | ~+260 |

### 8.4 Tests (~24)

- `start_research(idea)` creates new research_file with provenance + draft handoff idea_provenance (projection) populated (3)
- Same idea twice (exact idea_id match at step 3.1): second call returns `existing_file_reused=true, idea_seeded=false`, no re-seed, no duplicate Thesis, draft handoff provenance unchanged (2)
- Existing research_file without idea_id (step 3.2): backfill succeeds; `idea_id/idea_provenance/source_ref` columns populated; draft handoff `idea_provenance` updated via `update_idea_provenance`. `idea_backfilled=true`. (3)
- Backfill-and-Thesis-exists: backfill provenance on research_file row, but Thesis bootstrap is skipped (no overwrite). `thesis_bootstrapped=false`. (1)
- **Conflict path (step 3.2 with idea_id mismatch)**: existing file has `idea_id=A`; call with idea_id=B for same (ticker,label) → HTTP 409 with both idea_ids in response; no row mutation; no handoff mutation. (2)
- Thesis bootstrap on fresh file: Thesis exists with `from_idea` populated + `thesis.{direction,strategy,conviction,timeframe}` seeded from idea. `thesis.statement` remains empty. (2)
- Thesis bootstrap: existing Thesis + idea-seeded new file would never happen under step 3.3 (Thesis bootstrap runs AFTER file creation for new files) — but the idempotency check in `thesis_service.bootstrap_from_idea` is tested in isolation: Thesis exists → no write. (1)
- Top-level vs nested mismatch: `{ticker: "MSFT", idea: {ticker: "AAPL", ...}}` → 422 `ticker_label_mismatch` (2)
- Idea-only request body (no top-level `ticker`/`label`, idea fields fully derive both): `{idea: {ticker: "MSFT", label: "", ...}}` → 200 with research_file seeded from `idea.ticker`/`idea.label`. Sub-phase D may need to relax the existing `routes.py:313` request body model (`ticker` currently required at top-level) to make `ticker` optional when `idea` is present; if not relaxed, this test asserts 422 and the alternative pattern documented (caller must duplicate ticker/label at top level even with `idea` payload). (1)
- Invalid idea payload (missing required field) → 422 (1)
- Legacy `(ticker, label)` path unchanged (regression) (1)
- `research_files.idea_provenance` column matches `idea.model_dump()` shape — round-trip JSON parse equal (1)
- `research_files.source_ref` column matches `idea.source_ref.model_dump()` — consistency invariant with idea_provenance sub-object (1)
- **HandoffArtifact projection invariant**: after `start_research(idea)`, the draft handoff's `idea_provenance` equals `project_to_handoff_idea_provenance(idea).model_dump()` — 2 fields only, not full snapshot (2)
- **Finalized artifact propagation**: finalize the handoff → new `HandoffArtifact v1.1` has `idea_provenance` matching the projection (via pass-through at `handoff.py:718`). (1)
- Enum canonicalization: idea with Title Case enums gets normalized in `idea_provenance` column + Thesis seeds + HandoffArtifact thesis fields (shared-slice propagation) (2)
- **from_idea markdown round-trip**: bootstrap Thesis from idea → export to markdown → re-parse → `from_idea` equal (1)
- **Same-idea/different-label concurrent race** (R7 finding #1): two `start_research(idea)` calls with same `idea.idea_id` but different `idea.label` run via `concurrent.futures` on the same `(user_id)`; assert (a) exactly one `research_files` row exists for that `idea_id` after both complete, (b) the loser call returns the winner's row via the UNIQUE-index fallback (step 3.1-equivalent idempotent reuse), (c) no orphan rows with duplicate `idea_id` remain. Lives in `tests/api/research/test_start_research_from_idea.py`. (1)

### 8.5 Risks

- **Concurrent idea-seeded start_research on same `(ticker, label)`** — race on `(user_id, ticker, label)` lookup at step 3.2. Repository write must be inside an `INSERT OR IGNORE` / `SELECT ... FOR UPDATE` equivalent. SQLite: wrap research_files seed in `BEGIN IMMEDIATE` transaction. Sub-phase D first task verifies the live lookup+insert path is transactional.
- **Concurrent idea-seeded start_research on same `idea_id` but different `label`** (R7 finding #1) — race at step 3.1 where both callers miss the idea_id lookup, then each step through 3.3 and try to INSERT with distinct `(ticker, label)` but same `idea_id`. Without DB-level enforcement this produces two `research_files` sharing `idea_id`, violating the identity invariant. **Resolution**: the partial UNIQUE index from §6.2 (`idx_research_files_idea_id_unique`) rejects the second INSERT with a constraint violation. `seed_research_file_from_idea()` uses an UPSERT that references the partial index by repeating its WHERE predicate (required by SQLite to match a partial unique index), then re-selects by `idea_id`:
  ```sql
  INSERT INTO research_files (...) VALUES (...)
    ON CONFLICT (idea_id) WHERE idea_id IS NOT NULL DO NOTHING;
  SELECT * FROM research_files WHERE idea_id = :idea_id LIMIT 1;
  ```
  The `WHERE idea_id IS NOT NULL` clause is load-bearing — SQLite requires it to target the partial unique index. Sub-phase D implements this path. The UNIQUE index from sub-phase B is the single source of truth for idea_id uniqueness.
- **Draft handoff TOCTOU** (R2 should-fix #7) — live `repository.get_or_create_draft_handoff()` at `repository.py:2122` checks-then-creates across separate transactions. The live **`research_handoffs`** table (at `repository.py:186` — NOT `handoffs`) has no unique constraint on `(research_file_id, status='draft')`. Two concurrent `start_research(idea)` calls on the same research_file could each observe "no draft" and each call `create_handoff()`, producing two drafts. **Fix — single committed approach, no fallback**:
  - **Sub-phase B owns** (part of v5→v6 migration, atomic):
    1. Pre-migration sweep — query for any `(research_file_id)` with `COUNT(*) > 1` WHERE `status='draft'`. If any exist, consolidate by keeping the oldest draft (MIN(id)) per research_file and status-transition the newer duplicates to `'superseded'`. For each research_file touched, insert one row into the existing `research_file_history` table (live at `AI-excel-addin/api/research/repository.py:199`, methods at `repository.py:1345`) with:
       ```
       event_type = 'migration_duplicate_draft_sweep'
       changes    = {"kept_handoff_id": <int>, "superseded_handoff_ids": [<int>, ...]}
       ```
       Migration is reversible only via DB snapshot (documented in the sub-phase B commit).
    2. Create the partial unique index:
       ```sql
       CREATE UNIQUE INDEX IF NOT EXISTS idx_research_handoffs_unique_draft
         ON research_handoffs(research_file_id) WHERE status='draft';
       ```
  - **Sub-phase D owns**: rewrite `get_or_create_draft_handoff()` body to `INSERT ... ON CONFLICT DO NOTHING` followed by `SELECT`. Idempotent + race-safe. The index is the source of truth; the new body is the consumer. Sub-phase D never alters schema.
  - **No `BEGIN IMMEDIATE` fallback** — the pre-migration duplicate sweep in B is the committed path. If B's sweep surfaces a production-blocking volume of duplicates, that's a pre-existing data-quality issue flagged during migration rollout review, not an escape hatch to a different code path.
  - **Parallel-start test**: sub-phase D adds an integration test that spawns N concurrent `start_research(idea)` calls via `concurrent.futures` and asserts exactly one draft handoff exists after all complete. Lives in `tests/api/research/test_start_research_from_idea.py`.
- **Thesis bootstrap vs existing Thesis** — policy is "never overwrite existing Thesis." If a Thesis exists AND idea provides different enum values, we do NOT update `thesis.{direction,strategy,conviction,timeframe}`. Analyst must reconcile manually (via `thesis-consultation`). Test asserts this.

---

## 9. Sub-phase E — Connector migration

### 9.1 Goal

Live inventory (corrected from R1 blocker #4) — 8 idea-emitting connectors in `AI-excel-addin/api/memory/connectors/` + 1 inline idea builder in `investment_tools/scripts/ingest.py`. `analyst_grades` in that same file is a stub returning `[]` (line 1068+) and migrates structurally but no-ops. `oi_analysis` is enrichment-only (no `ingest_idea()` call path; routes through `enrich_ticker()` at `investment_tools/scripts/ingest.py:1549`) and is NOT migrated.

Each migrated site adds `idea_id` minting + `source_ref` construction using `InvestmentIdea.mint_idea_id(source_repo, source_id)`. After the sub-phase, the `IdeaPayload` construction sites are gone from these call paths; `IdeaPayload` remains only as the dataclass + `from_idea_payload()` shim + tests.

### 9.2 Design

For each connector:

```python
# Before
payload = IdeaPayload(
    ticker=ticker,
    thesis=thesis_text,
    source="screen:quality",
    source_date=source_date,
    ...
)

# After — build source_ref FIRST, then mint idea_id from its stable origin
source_ref = SourceRef(
    type="screen",
    source_repo="investment_tools",
    source_id=f"screen:quality:{source_date.isoformat()}:{row_index}",
    source_payload=<connector-specific raw row>,
)
idea = InvestmentIdea(
    ticker=ticker,
    thesis=thesis_text,
    source="screen:quality",
    source_date=source_date,
    idea_id=InvestmentIdea.mint_idea_id(source_ref.source_repo, source_ref.source_id),
    surfaced_at=datetime.now(timezone.utc),
    source_ref=source_ref,
    # existing optional fields unchanged
    ...
)
```

**The `mint_idea_id()` signature is always `(source_repo, source_id)` — a 2-arg classmethod**. Matching §4.2 and §5.2. Connectors must construct `source_ref` before minting so the origin reference is available.

Each migration site's mapping to `SourceRef.type`:

| # | Site | Location | `SourceRef.type` | `SourceRef.source_id` format | Notes |
|---|---|---|---|---|---|
| 1 | quality_screen | `AI-excel-addin/api/memory/connectors/quality_screen.py` | `screen` | `screen:quality:{date}:{row}` | |
| 2 | estimate_revisions | `AI-excel-addin/api/memory/connectors/estimate_revisions.py` | `screen` | `screen:estimate_revisions:{date}:{row}` | |
| 3 | insider_buying | `AI-excel-addin/api/memory/connectors/insider_buying.py` | `screen` | `screen:insider_buying:{date}:{row}` | |
| 4 | ownership | `AI-excel-addin/api/memory/connectors/ownership.py` | `screen` | `screen:ownership:{date}:{row}` | |
| 5 | special_situations | `AI-excel-addin/api/memory/connectors/special_situations.py` | `finding` | `finding:special_situations:{date}:{row}` | |
| 6 | biotech_catalyst | `AI-excel-addin/api/memory/connectors/biotech_catalyst.py` | `finding` | `finding:biotech:{date}:{row}` | |
| 7 | fingerprint_screen | `AI-excel-addin/api/memory/connectors/fingerprint_screen.py` | `screen` | `screen:fingerprint:{date}:{row}` | |
| 8 | newsletter | `AI-excel-addin/api/memory/connectors/newsletter.py` | `newsletter` | `newsletter:{source_newsletter}:{date}:{row}` | |
| 9 | earnings_transcript (inline) | `investment_tools/scripts/ingest.py:946-1006` | `finding` | `finding:earnings:{date}:{row}:{category}` | **inline in investment_tools, not a connector file** |
| — | analyst_grades (stub) | `investment_tools/scripts/ingest.py:1068+` | `finding` | (stub returns `[]`; migrate structurally for when it's filled in) | **stub — no-op today** |
| — | oi_analysis | `AI-excel-addin/api/memory/connectors/oi_analysis.py` + `investment_tools/scripts/ingest.py:1549` (`from_oi_analysis` → `enrich_ticker`) | N/A | — | **enrichment-only, no idea emission, NOT migrated** |

So sub-phase E touches: 8 AI-excel-addin connector files + 1 investment_tools inline builder (site #9) + structural shape update for the analyst_grades stub (no behavior change). Total: **9 migration commits + 1 stub-shape commit**.

**IdeaPayload shim**: after this sub-phase, the only remaining references are the dataclass definition, `from_idea_payload()`, their tests, and the ingest boundary upcast path. The shim exit gate in §4.1 should now trivially hold.

### 9.3 Files to modify

| File | Change | Est. lines |
|---|---|---|
| `AI-excel-addin/api/memory/connectors/*.py` (8 connector files) | Replace `IdeaPayload(...)` construction with `InvestmentIdea(...)` | ~+30 each, ~+240 total |
| `investment_tools/scripts/ingest.py` (earnings_transcript inline, lines 946-1006) | Same replacement at the inline builder | ~+35 |
| `investment_tools/scripts/ingest.py` (analyst_grades stub, line 1068+) | Structural shape matches InvestmentIdea (still returns `[]`) | ~+10 |
| `AI-excel-addin/tests/test_connectors.py` | Extend connector tests to assert idea_id + source_ref presence (live layout — all connector tests in one file) | ~+100 |
| `investment_tools/tests/test_ingest.py` (or equivalent) | earnings_transcript + stub tests | ~+40 |

### 9.4 Tests (~22)

- Per connector (8 AI-excel-addin connectors): output is `InvestmentIdea` instance; `idea_id` is deterministic UUIDv5; `source_ref.type` matches table; `source_payload` preserved from raw row (8)
- earnings_transcript inline builder: same contract verified at the investment_tools call site (1)
- analyst_grades stub: returns `[]` (behavior unchanged) but signature now is `list[InvestmentIdea]` not `list[IdeaPayload]` (1)
- Enum migration: connectors emitting Title Case strategy/direction/timeframe still work (canonicalizer absorbs at InvestmentIdea construction) (3)
- `oi_analysis` enrichment-only path unchanged (regression) (1)
- Integration: `investment_tools/scripts/ingest.py` pipeline run end-to-end produces ideas + ingests them (1)
- Deterministic idea_id across two runs of same connector on same data (2)
- Two different connectors producing same ticker + date mint DIFFERENT idea_ids (different `source_repo|source_id`) (2)
- Connector failure path: if mandatory field missing, `InvestmentIdea(...)` raises at construction, surfaced as ingest error (not silent skip) (3)

### 9.5 Risks

- **Blast radius across 2 repos**: 8 connector files in AI-excel-addin + 1 inline builder in investment_tools. Mitigation: sub-phase E is scripted as per-site commits; reviewer inspects each independently. The shim upcast at ingest boundary means even a half-migrated state is valid — if only 5 connectors migrate and the other 3 continue emitting IdeaPayload, ingestion still works via `from_idea_payload()`.
- **Downstream idempotency**: if connectors are re-run, deterministic idea_id via `source_ref.source_id` ensures ingest is idempotent (sub-phase C tests cover this).
- **External callers of `IdeaPayload`**: 9 internal sites (8 connectors + earnings_transcript inline). External (out-of-repo) callers unknown. Shim is load-bearing for safety until exit gate (§4.1) passes.

---

## 10. Sub-phase F — risk_module MCP tool surface

### 10.1 Goal

Extend `start_research` MCP tool to accept optional `idea` kwarg. Action layer validates, dispatches through gateway. Agent-format flags for idea-seeded responses.

### 10.2 Design

**MCP tool** (`risk_module/mcp_tools/research.py:42`):

```python
@mcp.tool()
def start_research(
    ticker: str,
    label: Optional[str] = None,
    idea: Optional[dict[str, Any]] = None,       # NEW
    format: Literal["summary", "agent"] = "agent",
) -> dict:
    """Start a research workspace; optionally seed from an InvestmentIdea."""
    return _start_research(
        ticker=ticker,
        label=label,
        idea=idea,                                # threaded through
        user_email=None,
        format=format,
    )
```

**Action layer** (`risk_module/actions/research.py:start_research`):

```python
def start_research(
    ticker: str,
    label: str | None = None,
    idea: dict[str, Any] | None = None,          # NEW
    user_email: str | None = None,
) -> dict[str, Any]:
    context = _resolve_research_action_context(user_email)
    file_payload = {"ticker": normalized_ticker}
    if normalized_label:
        file_payload["label"] = normalized_label
    if idea is not None:
        # Thin pass-through — backend validates the idea shape.
        # Action layer only checks idea is a dict (defer full Pydantic to backend).
        if not isinstance(idea, dict):
            raise ActionValidationError("idea must be an object")
        file_payload["idea"] = idea

    file_response = research_gateway.request(
        str(context.user_id), "POST", "files", json_body=file_payload,
    )
    # ... existing flow — UPDATED: _normalize_file_snapshot() must preserve the
    # new idea-seeded fields (see below). Response composed here threads
    # idea_seeded/idea_backfilled/thesis_bootstrapped/draft_handoff_provenance_seeded
    # top-level booleans verbatim from the backend response.
```

**Response-normalization extension (R9 blocker #1)**. Live `_normalize_file_snapshot()` at `actions/research.py:747` whitelists a small fixed field set and would silently DROP the new idea-seeded fields on their way through the action layer. Sub-phase F MUST extend the normalizer to preserve:

- On the `file` sub-object: `idea_id`, `idea_provenance` (full InvestmentIdea snapshot, JSON dict), `source_ref` (JSON dict)
- At the top level of the response: `idea_seeded`, `idea_backfilled`, `thesis_bootstrapped`, `draft_handoff_provenance_seeded` (all booleans)

Without this extension, MCP agent-flag generation at `core/research_flags.py` cannot derive the flags from the live action result, and the response contract in §8.2 is not actually delivered to MCP callers. Sub-phase F tests MUST drive through the action layer with stubbed gateway responses (not just stub `research_actions.start_research()` at the MCP wrapper) to catch this class of regression — see §10.4.

**Gateway 409 mapping — NEW** (R2 blocker #3). Live `services/research_gateway.py:216` only special-cases 404 and 422; 409 falls through as infrastructure error. Plan #4 sub-phase F adds:

- New typed error in `actions/errors.py`: `class IdeaConflictError(ActionValidationError)` with detail fields `{existing_idea_id, requested_idea_id, research_file_id}`.
- Extend gateway's `_classify_and_raise()` (or equivalent — the function that currently handles 404/422): on HTTP 409 with body `{error: "idea_conflict", ...}`, raise `IdeaConflictError` with detail payload preserved. Follows the exact pattern plan #3 G shipped for 404/409/422 MBC errors.
- `mcp_tools/research.py` agent flag: when `IdeaConflictError` is caught at the MCP boundary, emit flag `idea_conflict` (severity `warning`) with detail fields on the response.

**Agent flags** (`risk_module/core/research_flags.py` or equivalent):

| Condition | Flag | Severity |
|---|---|---|
| `idea_seeded=true`, `thesis_bootstrapped=true` | `research_started_from_idea` | info |
| `idea_seeded=true`, `idea_backfilled=true` | `idea_backfilled_to_existing_file` | info |
| `idea_seeded=true`, Thesis already existed | `thesis_preserved_existing` | info |
| Backend 409 (IdeaConflictError) | `idea_conflict` | warning |
| No idea, legacy path | (no flag) | — |

### 10.3 Files to modify

| File | Change | Est. lines |
|---|---|---|
| `risk_module/mcp_tools/research.py` | Add `idea` kwarg to `start_research` MCP tool; catch `IdeaConflictError` → agent flag | ~+20 |
| `risk_module/actions/research.py` | Thread `idea` through action layer; **extend `_normalize_file_snapshot()` at `research.py:747` to preserve `idea_id`, `idea_provenance`, `source_ref` on the file sub-object and `idea_seeded`, `idea_backfilled`, `thesis_bootstrapped`, `draft_handoff_provenance_seeded` top-level booleans in the composed response** (R9 blocker #1) | ~+35 |
| `risk_module/actions/errors.py` | New `IdeaConflictError(ActionValidationError)` with detail payload fields | ~+10 |
| `risk_module/services/research_gateway.py` | Extend 4xx classifier — 409 + body `error=idea_conflict` → `IdeaConflictError` with detail preserved (mirror plan #3 G pattern for MBC 404/409/422) | ~+20 |
| `risk_module/core/research_flags.py` (new or extend existing) | Flag generation for idea-seeded responses + `idea_conflict` warning flag | ~+70 |
| `risk_module/mcp_server.py` | Register the extended `start_research` MCP tool signature | ~+5 |
| `risk_module/agent/registry.py` | **Extend `start_research` registry callable at `registry.py:883-1273` to accept the new `idea` kwarg** (R9 medium #2); ensures `routes/agent_api.py:106` (`GET /api/agent/registry`) schema generation + `routes/agent_api.py:63` (`POST /api/agent/call`) dispatch automatically advertise + accept `idea` | ~+10 |
| `risk_module/tests/mcp_tools/test_research_start_idea.py` | MCP-layer tests (includes 409 mapping) — **tests MUST drive through the action layer with stubbed gateway responses (not just stub `research_actions.start_research()` at the MCP wrapper), so the `_normalize_file_snapshot()` extension is exercised** | ~+260 |
| `risk_module/tests/routes/test_agent_api_idea.py` (new) | Registry/agent-API test — verify `idea` param is advertised via `GET /api/agent/registry` and accepted via `POST /api/agent/call` (live routes per `routes/agent_api.py:63,106`) | ~+60 |

### 10.4 Tests (~22)

- `start_research(ticker, label)` unchanged behavior (regression) (2)
- `start_research(ticker, label, idea={...})` happy path — drives through action layer with a stubbed gateway response that includes `idea_id`, `idea_provenance`, `source_ref`, `idea_seeded=true`, `thesis_bootstrapped=true`, etc.; asserts those fields survive `_normalize_file_snapshot()` and appear in the MCP response (3)
- Gateway validation error on invalid idea shape → `ActionValidationError` (2)
- **Gateway 409 `idea_conflict` → `IdeaConflictError` with `existing_idea_id`, `requested_idea_id`, `research_file_id` preserved in exception detail** (2)
- **Agent format surfaces `idea_conflict` flag with detail fields on the response** (2)
- Agent format includes `flags` with `research_started_from_idea` when seeded (2)
- Agent format includes `idea_backfilled_to_existing_file` when existing file is updated (1)
- **Agent format includes `thesis_preserved_existing` when idea-seeded start_research runs against a research_file that already has a Thesis — flag appears on MCP response alongside `existing_file_reused=true` + `idea_backfilled=true` + `thesis_bootstrapped=false`** (1)
- **Action-layer normalizer preserves new fields** (R9 blocker #1): stub gateway returns a full file snapshot with all new fields populated; assert `_normalize_file_snapshot()` does NOT drop `idea_id`, `idea_provenance`, `source_ref` from the file sub-object, nor `idea_seeded`, `idea_backfilled`, `thesis_bootstrapped`, `draft_handoff_provenance_seeded` from the composed top-level response (2)
- **Agent-API registry advertises `idea` parameter** (R9 medium #2): `GET /api/agent/registry` (live route at `routes/agent_api.py:106`); assert `functions.start_research.params.idea` is present in the returned registry, advertised as optional with the expected schema/description (1)
- **Agent-API accepts `idea` on POST**: `POST /api/agent/call` (live route at `routes/agent_api.py:63`) with body `{"function": "start_research", "params": {"ticker": "...", "idea": {...}}}`; assert the registry dispatch succeeds and the idea-seeded response fields (`idea_id`, `idea_seeded`, etc.) come back. Pattern matches existing route tests at `tests/routes/test_agent_api.py:70` and `:205`. (1)
- Legacy flag set unchanged for non-idea calls (1)
- `idea` kwarg at MCP layer defaults to None (1)
- Backend 422 surfaces as `ActionValidationError` (2)

### 10.5 Risks

- **Gateway contract drift**: if AI-excel-addin backend rejects the new `idea` field (e.g., stricter validation), action layer surfaces 422 as `ActionValidationError`. Action tests cover the error-surface shape.
- **Dict-vs-Pydantic at MCP boundary**: MCP tools accept dicts for JSON transport. The backend does Pydantic validation. Action layer does minimal structural check. This is the same pattern plan #3 G used for MBC overrides — precedent exists.
- **409 handling was missing from R1/R2 v1 plan**: reviewed and patched in R3 v2 (this version). Precedent: plan #3 G's gateway classifier handles exactly this pattern (404/409/422 with typed errors + detail payload).

---

## 11. Sub-phase G — End-to-end tests + round-trip

### 11.1 Goal

Suite-level integration tests validating the full ingress → research → thesis → handoff provenance chain.

### 11.2 Test scenarios

- **Scenario 1** — Connector emits `InvestmentIdea` → `ingest_idea()` writes memory-sync attributes (`ingested_idea_ids`, `source_refs`, `idea_provenance_summary`) → analyst calls `start_research(idea)` → research_file has `{idea_id, idea_provenance, source_ref}` → Thesis draft exists with `from_idea` + seeded `thesis.{direction,strategy,conviction,timeframe}` → draft HandoffArtifact has projected `idea_provenance = {idea_id, source_summary}` → finalized HandoffArtifact v1.1 pass-through preserves it.
- **Scenario 2** — Idempotency end-to-end: Same idea re-ingested at memory-sync layer → `skipped_duplicate`, no store write. Same idea re-called at `start_research` (step 3.1) → returns existing research_file, `idea_seeded=false`, no Thesis bootstrap, no handoff mutation.
- **Scenario 3** — Manual idea (no connector): `InvestmentIdea(..., source_ref=SourceRef(type="manual", source_id="manual:...", source_repo="manual"))` flows same path to full propagation.
- **Scenario 4** — Legacy IdeaPayload path (upcast boundary is `ingest_idea()` ONLY; MCP/REST `start_research(idea)` never accepts legacy): connector emits IdeaPayload → `ingest_idea()` upcasts via `from_idea_payload()` → memory-sync bullets populated with synthesized idea_id. If an analyst later wants to start research from that same origin, they construct/retrieve an `InvestmentIdea` (with the same deterministic idea_id because `(source_repo, source_id)` inputs are stable) and call `start_research(idea=InvestmentIdea)`. Step 3.1 of §8.2 identity resolution finds the existing research_file (if already seeded) or proceeds to step 3.2/3.3 (if the inbox-ingested idea has not yet been promoted to research_files). Upcast does NOT run at `start_research` — the REST endpoint's validator rejects raw IdeaPayload shape with 422.
- **Scenario 5** — Enum canonicalization end-to-end: Title Case `direction`/`strategy`/`timeframe` input at connector → snake_case in the idea's own enum fields (visible in memory-sync ticker markdown bullets for those named attributes, in the `idea_provenance` column as a serialized InvestmentIdea, in the `idea_provenance_summary` bullet's rendered text where applicable), in research_files idea_provenance JSON, in seeded Thesis fields (`thesis.direction` etc.), and in HandoffArtifact `thesis.direction` via shared-slice propagation. `ingested_idea_ids` and `source_refs` bullets are source-identity lists that do NOT carry thesis enum values — scenario 5 does not assert enum presence there.
- **Scenario 6** — Backfill path (step 3.2): pre-existing research_file without idea_id + `start_research(idea)` → row gets idea_id/idea_provenance/source_ref; draft handoff `idea_provenance` updated via `update_idea_provenance()`; no duplicate research_file created; existing Thesis (if any) untouched.
- **Scenario 7** — Conflict path (step 3.2 mismatch), split across two layers:
  - **Backend half** (AI-excel-addin): research_file has `idea_id=A`; call `POST /files` with `idea_id=B` same (ticker,label) → HTTP 409 with body `{error: "idea_conflict", existing_idea_id: "A", requested_idea_id: "B", research_file_id: ...}`. No row mutation. No Thesis bootstrap. No draft-handoff update. Lives in `tests/api/research/test_start_research_from_idea.py`.
  - **Gateway + MCP half** (risk_module): backend 409 → `research_gateway` classifier raises `IdeaConflictError` (subclass of `ActionValidationError`) with detail fields `{existing_idea_id, requested_idea_id, research_file_id}` preserved → MCP agent response includes `idea_conflict` flag (severity `warning`) with those fields. Lives in `risk_module/tests/mcp_tools/test_research_start_idea.py` (already enumerated in §10.4).
- **Scenario 8** — Schema JSON round-trip: `InvestmentIdea.model_dump_json()` → load → `InvestmentIdea.model_validate_json()` → equal. Projection round-trip: `project_to_handoff_idea_provenance(idea)` → `.model_dump()` → `IdeaProvenance.model_validate(...)` → equal.
- **Scenario 9** — Boundary test: snapshot of `InvestmentIdea` JSON schema at `tests/schema/snapshots/investment_idea_v1_0.schema.json`. Committed; changes fail CI unless explicitly regenerated. Thesis snapshot also updated for `from_idea` addition (sub-phase D delivered).

### 11.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `AI-excel-addin/tests/integration/test_idea_end_to_end.py` | Scenarios 1–5 (integration: connector → ingest → start_research → Thesis/handoff) | ~+350 |
| `AI-excel-addin/tests/api/research/test_start_research_from_idea.py` | Scenario 6 (backfill) + Scenario 7 **backend half only** (409 response + no-mutation assertions) — this file is ALSO the home for sub-phase D's end-to-end tests per §8.3. Scenario 7's gateway/MCP half lives in risk_module tests (enumerated in §10.4). | +80 added to the ~+260 already planned in §8.3 |
| `AI-excel-addin/tests/schema/test_investment_idea_boundary.py` | Scenarios 8 + 9 (schema round-trip + boundary) | ~+80 |
| `AI-excel-addin/tests/schema/snapshots/investment_idea_v1_0.schema.json` | Pinned schema | generated |

**Why scenarios 6+7 are NOT in the schema boundary file**: they test backfill/conflict behavior across repository + routes + gateway layers, not schema shape. Schema boundary tests stay dedicated to scenarios 8 + 9 (JSON round-trip + snapshot).

### 11.4 Risks

- **Test flakiness from `datetime.now()`**: all ingest/seed tests must inject a frozen clock. Use existing test infrastructure (plan #1 already has this in `tests/api/research/` helpers).
- **Fixture sprawl**: integration tests need connector-like fixtures. Reuse existing connector test fixtures from `tests/test_connectors.py` rather than fabricate new ones.

---

## 12. Sub-phase H — `SKILL_CONTRACT_MAP.md` + doc updates

### 12.1 Goal

Reflect InvestmentIdea ingress in the authoritative skill↔contract map.

### 12.2 Edits (mechanical)

- **Key contracts table** (line 60 of SKILL_CONTRACT_MAP.md): drop "(planned)" from `InvestmentIdea` row. Update description: "Typed ingress from investment_tools; superset of legacy `IdeaPayload`; deterministic idea_id; carried through to `research_files.idea_provenance` + `Thesis.from_idea` + `HandoffArtifact.idea_provenance`."
- **Screening skill rows** (lines 128): `fingerprint-research`, `special-situations-research`, `biotech-research` → annotate with "emits `InvestmentIdea` via connector pipeline" and reference sub-phase E.
- **Integration pattern 1** — add a new "Pattern 0 — Idea ingress (connector → InvestmentIdea → start_research)" before the existing patterns.
- **Cross-repo references**: add row — "Investment idea ingress: `AI-excel-addin/schema/investment_idea.py`, `api/memory/connectors/*.py`, `api/memory/ingest.py` (legacy `IdeaPayload`)".

### 12.3 Files to modify

| File | Change | Est. lines |
|---|---|---|
| `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` | Mechanical edits per §12.2 | ~+20 |

---

## 13. Success criteria

- All 8 AI-excel-addin connectors + earnings_transcript inline builder emit `InvestmentIdea` at pipeline exit; analyst_grades stub migrated structurally; oi_analysis unchanged.
- `ingest_idea()` accepts `IdeaPayload | InvestmentIdea` (legacy upcast at boundary). `start_research(idea)` — at both the REST endpoint and the risk_module MCP/action surface — accepts ONLY `InvestmentIdea` (legacy shape is rejected with 422 at the endpoint; callers in the MCP layer pass a dict that the backend validates as `InvestmentIdea`).
- `IdeaPayload` shim still accepted on ingest path (backward compat verified by regression tests).
- Shim exit gate (§4.1) holds — `rg "IdeaPayload"` with chat_log exclusions shows only dataclass + `from_idea_payload` + ingest boundary + tests.
- A freshly seeded `research_files` row carries `{idea_id, idea_provenance, source_ref}` populated.
- A freshly bootstrapped `Thesis` has `from_idea` populated + shared-slice `thesis.{direction,strategy,conviction,timeframe}` seeded from idea (NOT `position_metadata`).
- Draft `HandoffArtifact` has `idea_provenance` projection (`{idea_id, source_summary}`) populated immediately after `start_research(idea)`; finalize pass-through preserves it into the finalized artifact.
- Exactly one draft handoff per research_file after parallel idea-seeded calls (concurrency test passes).
- Memory-sync ticker markdown gains three new bullets (`ingested_idea_ids`, `source_refs`, `idea_provenance_summary`) on ingest; watcher re-imports without error.
- Enum canonicalization end-to-end: Title Case input → snake_case storage everywhere.
- Typed `IdeaConflictError` raised on HTTP 409 from backend; MCP surfaces as `idea_conflict` agent flag.
- Schema boundary test pinned at `investment_idea_v1_0.schema.json`; Thesis snapshot regenerated for `from_idea` addition.
- SKILL_CONTRACT_MAP.md reflects shipped state.

Cumulative test count target: ~120 new tests across sub-phases A–G.

---

## 14. Rollback

If a sub-phase fails in flight:
- A/B independent — either can ship alone.
- C requires A. Rollback: revert C commit, restore `ingest.py` to IdeaPayload-only, leave schema v6 in place (forward-compatible, no code references the new columns yet).
- D requires A+B+plan#1+plan#2. Rollback: revert D commit, keep A/B/C. Legacy `start_research(ticker, label)` path unaffected.
- E requires A+C. Rollback: revert E, IdeaPayload shim absorbs — connectors go back to emitting IdeaPayload, ingest still works through upcast.
- F requires A+D. Rollback: revert F, legacy MCP `start_research` signature remains usable.

No DB rollback scripted — v5→v6 is additive. Un-ALTER requires backup restore. Forward-compat only.

---

## 15. Change log

### R1 → R2 (2026-04-21)

Codex R1 verdict: **FAIL**. 6 blockers + 3 should-fix. All resolved in-place; disposition below.

**Blockers (all resolved)**:

1. **Wrong Thesis bootstrap target** — `PositionMetadata` has `{position_size, date_initiated, portfolio_fit}` only; `timeframe` doesn't exist on it. Live bootstrap (`repository.py:974`) seeds shared-slice `thesis.{direction,strategy,conviction}` from the research_file row. **Fix**: §4.3 rewritten — bootstrap target is `Thesis.thesis.{direction,strategy,conviction,timeframe}` on the existing `ThesisField` (`schema/thesis_shared_slice.py:90-95`, all four fields exist). §8.2 + §8.3 + §8.4 updated accordingly. Also avoids needing a new shared-slice addition — propagation to HandoffArtifact happens naturally via existing `_shared_slice_from_payload`.

2. **HandoffArtifact propagation assumed** — `HandoffArtifact.idea_provenance = IdeaProvenance {idea_id, source_summary}` (2 fields, NOT full InvestmentIdea); live draft builder (`repository.py:389`) sets it to `None`; finalize pass-through at `handoff.py:718` copies draft as-is. **Fix**: §4.3 spells out the projection function (`project_to_handoff_idea_provenance(idea) → {idea_id, source_summary=f"{type}:{source_repo}:{source_id}"}`) and the draft-seed hook (call existing `repository.update_idea_provenance(handoff_id, projection)` at `repository.py:2320` from `start_research(idea)`). §4.4 clarifies full-snapshot-on-research_files vs projection-on-handoff. §8.4 adds projection invariant + finalize propagation tests.

3. **Sub-phase C wrong storage model** — ideas-inbox is memory-sync markdown (`<!-- memory-sync: ... -->` header + `## {entity}` + `- **attribute**: value` bullets per `markdown_sync.py:16`), NOT YAML frontmatter. **Fix**: §7 fully rewritten. Plan #4 adds three new memory-sync attributes (`ingested_idea_ids` as sorted-comma-joined, `source_refs` as multi-line JSON-per-line, `idea_provenance_summary` as one-per-idea text). Markdown renders automatically via existing `_render_markdown_file`. No changes to `markdown_sync.py`. Existing `source_log_*` semantics (`tests/test_ingest.py:170`) preserved.

4. **Connector inventory wrong** — live: 8 idea emitters in `api/memory/connectors/` (biotech_catalyst, estimate_revisions, fingerprint_screen, insider_buying, newsletter, ownership, quality_screen, special_situations) + oi_analysis (enrichment-only, no idea emission, uses `enrich_ticker()` not `ingest_idea()`). `earnings_transcript` is inline in `investment_tools/scripts/ingest.py:946-1006`. `analyst_grades` at line 1068+ is a stub returning `[]`. **Fix**: §2 summary table + §9 fully updated — inventory table now lists exact file paths, correct counts, stub/enrichment carve-outs. Sub-phase E migrates 8 connector files + 1 inline builder + 1 stub-shape update. oi_analysis explicitly NOT migrated.

5. **idea_id minting not implementation-ready** — namespace was "example constant"; initial name-composition collapsed distinct same-date-same-source ideas; API mismatch between §5.2 (private helper) and §9.2 (classmethod). **Fix**: §4.2 + §5.2 aligned at that time. Namespace pinned at `21befb5d-e5c9-4800-ae8c-e3dcc595b17e` (minted 2026-04-21 for plan #4, declared immutable). Naming uses `f"{source_repo}|{source_id}"`. Legacy fallback at R2 synthesized a 3-part `source_id`. _(Legacy fallback formula later superseded in R5; current canonical form is the 4-part hash-bearing spec in §4.2 — the entry above is historical.)_ API is classmethod `InvestmentIdea.mint_idea_id(source_repo, source_id) -> str` everywhere.

6. **Research identity/conflict rules contradictory** — §4.2 vs §8.2 vs §8.4 disagreed; no rule for top-level vs nested ticker/label mismatch. **Fix**: single identity invariant declared once in §8.2. Lookup precedence: (1) by idea_id → if found, idempotent reuse; (2) by (ticker, label) with NULL idea_id → backfill; (3) by (ticker, label) with mismatched idea_id → **HTTP 409 conflict**, no mutation; (4) else create. Top-level vs nested mismatch → 422 `ticker_label_mismatch`. §8.4 tests all 4 branches explicitly.

**Should-fix (all resolved)**:

7. **`from_idea` blast radius on Thesis** — adds to `Thesis.model_fields` (32 → 33); isomorphism test pins exact count; snapshot + `THESIS_ONLY_FIELD_PATHS` need updating. **Fix**: §4.6 expanded with a 6-item blast-radius list (thesis.py + __init__.py + isomorphism test + schema snapshot + markdown serializer + markdown test). §8.3 file list includes all six. §4.6 also documents the rejected alternative (research_files-only storage).

8. **Shim lifespan vague** — "one release cycle" not testable. **Fix**: §4.1 replaces with concrete exit gate — `rg "IdeaPayload" <paths>` returns only (a) dataclass def, (b) `from_idea_payload` + tests, (c) external compat banner. Gate should hold immediately after sub-phase E. No per-connector rollout flag — the upcast-at-boundary IS the rollback.

9. **Ticker normalization parallel** — §5.2 invented a regex accepting `BP.L`; live `normalize_ticker()` at `ticker_utils.py:19` strips exchange suffixes. **Fix**: §5.2 `_normalize_ticker` validator now delegates to `api.memory.ticker_utils.normalize_ticker` + enforces `TICKER_RE`. Tests updated in §5.4 (`BP.L → BP`, `BRK.A → BRKA`).

---

### R2 → R3 (2026-04-21)

Codex R2 verdict: **FAIL**. 4 new blockers + 3 new should-fix (distinct from R1 set). R1's §4.3/§4.6/§5.2 fixes verified correct. R2 findings all resolved in-place; disposition below.

**Blockers (all resolved)**:

1. **Sub-phase C store API was fictional** — live `MemoryStore` only exposes `store_memory/delete_memory/get_memories/get_all_memories`; watcher imports markdown → store (one direction). My R2 rewrite invented `get_attribute/set_attribute`. **Fix**: §7 fully rewritten to stay on the existing file-write ingest path at `api/memory/ingest.py:95`. Three new memory-sync bullets appended idempotently via file parse + merge + atomic rewrite. NO store API changes. Watcher's existing import path handles propagation on its own cadence.

2. **`mint_idea_id` signature drift** — §4.2/§5.2 defined 2-arg `(source_repo, source_id)` but §9.2 connector example still showed 3-arg `(source, ticker, source_date)` and pre-computed idea_id before `source_ref`. **Fix**: §9.2 example rewritten — `source_ref` constructed first, then `InvestmentIdea.mint_idea_id(source_ref.source_repo, source_ref.source_id)`. Added explicit line: "The `mint_idea_id()` signature is always `(source_repo, source_id)` — a 2-arg classmethod."

3. **409 gateway mapping missing** — live `services/research_gateway.py:216` only special-cases 404/422; 409 would fall through to infrastructure error, breaking §11.2's claim of structured surfacing. **Fix**: §10.2 adds typed `IdeaConflictError(ActionValidationError)` + gateway 409 classifier extension (mirroring plan #3 G's MBC 404/409/422 pattern). §10.3 file list updated with `actions/errors.py` + `services/research_gateway.py` changes. §10.4 tests added for 409 mapping + agent flag surfacing.

4. **Stale pre-R2 content** — my R2 pass scrubbed deep sections but left stale terms in §1 scope, §1 bootstrap, §4.7 cross-plan, §13 success criteria. Contradicted the fixes. **Fix**: §1, §2 summary table, §4.7, §8.5, §13 all scrubbed. "frontmatter" → memory-sync bullets; "position_metadata" → `thesis.{direction,strategy,conviction,timeframe}`; "11 connectors" → 8 connectors + earnings_transcript inline + analyst_grades stub.

**Should-fix (all resolved)**:

5. **Shim exit gate grep scope** — `rg` hits `chat_logs/*.jsonl` (historical transcripts) + excludes ingest-boundary upcast (the rollback mechanism). **Fix**: §4.1 `rg` command uses `--glob '!**/chat_logs/**'` and `'!**/*.jsonl'` exclusions; allow-list explicitly names the `ingest_idea()` upcast branch as in-scope until retirement.

6. **Test file paths wrong** — plan cited `tests/memory/connectors/*` but live tree is `tests/test_connectors.py` (single file); cited `tests/research/*` but live tree is `tests/api/research/*`. **Fix**: §6.3, §8.3, §9.3 file-to-modify tables corrected to match live layout.

7. **Draft-handoff TOCTOU** — live `get_or_create_draft_handoff()` at `repository.py:2122` does check-then-create across separate transactions; no unique `(research_file_id, status='draft')` constraint at `repository.py:186`. **Fix**: §8.5 now specifies two candidate approaches (preferred: partial unique index + `ON CONFLICT DO NOTHING` at sub-phase B/D; acceptable fallback: `BEGIN IMMEDIATE` transaction). Sub-phase D first-task spike decides; documented in commit message. Parallel-start integration test asserts exactly-one-draft invariant.

---

### R3 → R4 (2026-04-22)

Codex R3 verdict: **FAIL**. 4 blockers + 3 should-fix — all mechanical consistency issues surviving my R2 scrub. Resolved via a systematic grep-and-fix sweep (not just the pointed-at lines).

**Blockers (all resolved)**:

1. **Stale terms survived R2 scrub in main body** — "frontmatter" at line 101, "position_metadata" at lines 15 and 575, "11 connectors" at line 72. **Fix**: targeted edits — line 15 (§hard prereqs), line 72 (§3 dep graph), line 101 (§4.1 code comment), line 575 (§8.1). Also swept for similar drift; line 434's `_ensure_schema` → `_maybe_migrate` per should-fix #5.

2. **Legacy `source_ref.source_id` formula drift** — §4.1 had a 2-part formula; §4.2/§5.2 had a 3-part formula. Different inputs to `mint_idea_id` → different ids. **Fix**: all three sections unified on the 3-part form at that time. _(Formula later superseded in R5 — current canonical form is the 4-part hash-bearing spec documented in main body §4.2. Both intermediate forms described here are historical only.)_

3. **Draft-handoff SQL wrong + ownership vague** — SQL targeted `handoffs`, live table is `research_handoffs` at `repository.py:186`. Migration ownership unclear (B or D?). **Fix**: §8.5 rewritten — (a) SQL uses `research_handoffs`; (b) sub-phase B owns the index + schema change as part of v5→v6 migration; (c) sub-phase D owns only the query rewrite to `INSERT ... ON CONFLICT DO NOTHING` + `SELECT`; (d) fallback `BEGIN IMMEDIATE` is D-only if B spike finds pre-existing duplicates blocking the index. Decision recorded in sub-phase B commit message.

4. **§10 vs §11 vs §13 contract contradictions** —
   - Scenario 7 (§11) said plain `ActionValidationError` but §10 defines typed `IdeaConflictError` with `idea_conflict` flag.
   - Scenario 4 (§11) + success criteria (§13) implied `start_research(idea)` accepts `IdeaPayload` via upcast; actually upcast boundary is `ingest_idea()` ONLY. §10 MCP signature is `idea: dict` validated by backend as `InvestmentIdea`.
   **Fix**: Scenario 7 rewritten — explicit `IdeaConflictError` + `idea_conflict` agent flag with detail fields. Scenario 4 rewritten — upcast happens at `ingest_idea()`; `start_research(idea)` rejects legacy shape with 422 at the REST endpoint. Success criteria §13 rewritten — `ingest_idea()` accepts both; `start_research(idea)` at REST + MCP/action surface accepts ONLY `InvestmentIdea`.

**Should-fix (all resolved)**:

5. **§6.3 repository method name** — `_ensure_schema()` → `_maybe_migrate()` at `repository.py:917`. Fixed in the sub-phase B file table at line 434.

6. **§7 atomic-write helper hedging** — plan said "markdown_sync._atomic_write or ingest.py equivalent". Live helper is `_plain_atomic_write()` at `ingest.py:244`. **Fix**: §7.3 + §7.5 + §7.5 tests all pin `_plain_atomic_write` explicitly; explicit do-NOT against confusing it with `markdown_sync._atomic_write` (different call sites).

7. **`thesis_preserved_existing` flag lacked MCP test** — only backend-side assertion existed. **Fix**: §10.4 added a dedicated test item asserting the flag appears on MCP agent response alongside `existing_file_reused=true + idea_backfilled=true + thesis_bootstrapped=false`.

**Diagnosis of R3 slow convergence**: R2 revision was reactive (fix what Codex pointed at) instead of systematic (grep whole doc for stale terms + cross-ref all signatures). R3 pass used `grep -n` sweeps before editing; remaining hits are all intentional disambiguation ("NOT frontmatter", "do NOT use markdown_sync._atomic_write").

---

### R4 → R5 (2026-04-22)

Codex R4 verdict: **FAIL**. 2 high + 2 medium + 1 medium — smaller, more surgical than R3. All anchors in live code verified by Codex R4 as correct.

**High (resolved)**:

1. **§8.5 TOCTOU fix hedged between B-owned index + D-only `BEGIN IMMEDIATE` fallback**. **Fix**: committed to single approach — sub-phase B normalizes pre-existing duplicates (sweep + status-transition to `'superseded'` with migration-log JSON entry) AND adds the partial unique index, both atomic in v5→v6 migration. Sub-phase D rewrites `get_or_create_draft_handoff()` as `INSERT ... ON CONFLICT DO NOTHING` + `SELECT`. No fallback. If B's sweep surfaces a production-blocking volume of duplicates, that's a migration rollout review decision, not an escape hatch.

2. **§8.2 conflated backend and action-layer response shape**. Live `POST /files` at `AI-excel-addin/api/research/routes.py:476` is file-scoped; threads are separate `POST /threads` calls composed in `risk_module/actions/research.py:52`. **Fix**: §8.2 step 5 explicitly notes thread creation is NOT part of `/files`; backend response redrawn as file-scoped only; action/MCP-layer response flagged as composed in §10 from multiple backend calls.

**Medium-High (resolved)**:

3. **§7 ticker-markdown contract self-inconsistent** — `source_refs` JSON lines missing `source_payload` (tests required it); `idea_provenance_summary` claimed "overwrites on re-ingest" but §7.3 duplicate short-circuit exits with no file touch; Scenario 5 claimed enum canonicalization surfaces in `ingested_idea_ids`/`source_refs` bullets (which carry no thesis enums). **Fix**: §7.2 table updated — `source_refs` JSON line now includes `source_payload`; `idea_provenance_summary` documented as written on first ingest, skipped (not overwritten) on re-ingest via the existing short-circuit. Scenario 5 clarified — enum canonicalization surfaces in idea's own enum fields (`direction`/`strategy`/`timeframe`) at both memory-sync-bullet and research_files-column layers, NOT in source-identity list bullets.

**Medium (resolved)**:

4. **§11.3 test file layer mismatch** — scenarios 6+7 (backfill/conflict) placed in `test_investment_idea_boundary.py`, but those are research-API integration scenarios. **Fix**: §11.3 file table re-assigns scenarios 6+7 to `tests/api/research/test_start_research_from_idea.py` (same file as sub-phase D's end-to-end tests). Schema boundary file hosts scenarios 8+9 only.

5. **§4.1 exit gate path unrunnable from risk_module cwd** — plan used `AI-excel-addin/...` which doesn't resolve from that directory. **Fix**: §4.1 now documents working directory as workspace root (`~/Documents/Jupyter/`) and uses `../AI-excel-addin/...` + `../investment_tools/...` paths with a note about adjusting prefixes per cwd.

---

### R5 → R6 (2026-04-22)

Codex R5 verdict: **FAIL**. 1 high + 3 medium. Trend continues: R1=9 → R2=7 → R3=7 → R4=5 → R5=4. R5 confirmed all R4 fixes hold + live anchors correct.

**High (resolved)**:

1. **Legacy `idea_id` collision on multi-idea-per-key emitters** — `earnings_transcript` at `investment_tools/scripts/ingest.py:946` iterates catalysts and emits multiple `IdeaPayload`s sharing `(source, ticker, date)`. The pre-R5 3-part legacy fallback (historical only; superseded — current spec in §4.2) would mint identical idea_ids → false `skipped_duplicate`. **Fix**: §4.2 legacy fallback now includes a content-hash discriminator `sha256(thesis || catalyst || strategy)[:8]` — this is the current canonical form; see main body §4.2 for the exact literal. §4.1 legacy fallback text + §5.2 `from_idea_payload` docstring updated consistently. Trade-off documented: idea_id becomes a function of payload BODY (acceptable because (a) sub-phase E replaces legacy emitters with native `InvestmentIdea` carrying stable `source_id`, (b) edit-then-re-emit isn't a legacy workflow).

**Medium (resolved)**:

2. **§4.4 hot-lookup claim not backed by §6.2 schema** — SQLite TEXT column + no expression index means `source_ref` isn't actually indexable by `source_repo|source_id`. **Fix**: §4.4 downgraded to "convenience column" (no indexed hot-path claim); plan notes a later plan can add generated columns/expression indexes if needed.

3. **Missing migration test for TOCTOU duplicate sweep** — §8.5 assigns the sweep to sub-phase B's migration, but §6.4 never tested it. **Fix**: §6.4 adds 3 new tests — (a) pre-v6 duplicate drafts → post-migration oldest survives + newer status-transitioned to 'superseded' + migration-log JSON entry, (b) unique draft index blocks second-draft insert, (c) zero-duplicate edge case runs clean. Test count bumped 14 → 18.

4. **`idea_provenance_summary` inconsistent for multi-idea tickers** — was spec'd as scalar "written once, not overwritten" but §7.3 unconditionally reassigned it on every non-duplicate ingest, meaning later ideas overwrite the summary for the same ticker. **Fix**: converted to multi-line attribute (parallel with `source_refs` and `ingested_idea_ids`). Each line keyed by idea_id; re-ingest of same idea_id short-circuits before any write; distinct ideas append new lines. §7.2 table + §7.3 pseudocode now consistent.

---

### R6 → R7 (2026-04-22)

Codex R6 verdict: **FAIL**. 1 blocker + 3 should-fix. Trend R1=9 → R2=7 → R3=7 → R4=5 → R5=4 → R6=4.

**Blocker (resolved)**:

1. **Legacy discriminator drift across §4.1/§4.2/§5.2 AGAIN** — same adjacent-section drift pattern. R5 pass updated §4.2 but left §4.1 line 109 with old no-hash formula and §5.2 `from_idea_payload` docstring with old formula + §4.1 incorrectly asserted "matches §4.2 exactly". **Fix**: grep-sweep pass — §4.1 now cites the exact hash-bearing formula + references §4.2 for the helper; §5.2 docstring rewritten to mention `_legacy_content_hash()` helper explicitly.

**Should-fix (resolved)**:

2. **§4.1 shim exit gate path unrunnable** — documented cwd as workspace root but kept `../` prefixes. **Fix**: cwd now documented as **this repo's root** (`~/Documents/Jupyter/risk_module/`), `../` prefixes resolve correctly from there.

3. **§4.1 vs §9.5 rollout story contradiction** — §4.1 said "single atomic commit, no staged rollout"; §9.5 said "scripted as per-site commits, half-migrated state valid". **Fix**: §4.1 aligned with §9.5 — per-site commits are the strategy; `from_idea_payload()` upcast at ingest boundary is the rollback mechanism; half-migrated states are explicitly valid. No atomic-commit claim; no staged-rollout flag system.

4. **Migration log surface + JSON shape underspecified** — §6.4 + §8.5 referred to "migration-log JSON entry" without naming the surface. **Fix**: use the existing `research_file_history` table (live at `repository.py:199`, methods at `repository.py:1345`) with `event_type='migration_duplicate_draft_sweep'` and `changes={"kept_handoff_id": <int>, "superseded_handoff_ids": [<int>, ...]}`. §8.5 + §6.4 test assertion aligned.

---

### R7 → R8 (2026-04-22)

Codex R7 verdict: **FAIL**. 1 high + 2 medium. Trend: R1=9 → R2=7 → R3=7 → R4=5 → R5=4 → R6=4 → R7=3.

**High (resolved)**:

1. **`idea_id` uniqueness not enforced at DB level** — §6.2 shipped only a non-unique index on `idea_id`. Live `research_files` enforces `UNIQUE(ticker, label)`; same-idea/different-label concurrent start_research calls could both miss step 3.1 and create distinct research_files rows, violating the "one idea_id → one research_file" invariant. **Fix**: §6.2 index changed to partial UNIQUE (`idx_research_files_idea_id_unique ON research_files(idea_id) WHERE idea_id IS NOT NULL`). §8.5 adds the same-idea race case, resolved at DB level via `INSERT ... ON CONFLICT (idea_id) DO NOTHING; SELECT`. §8.4 adds a same-idea/different-label concurrent test. §6.4 adds a direct uniqueness-constraint test.

**Medium (resolved)**:

2. **Stale no-hash formulas in §15 changelog** — R1/R2/R3 entries cited literal pre-R5 formulas that a doc-wide grep would surface as inconsistent with the canonical §4.2 spec. **Fix**: those entries now include explicit "_(formula later superseded; current canonical form in §4.2)_" markers; the literal stale formulas removed or annotated as historical.

3. **Scenario 7 cross-layer test placement** — §11.2 described the full backend → gateway → MCP flag chain, but §11.3 assigned the entire scenario to AI-excel-addin. The gateway/MCP half belongs to risk_module (and was already in §10.4). **Fix**: §11.2 explicitly splits Scenario 7 into "backend half" (AI-excel-addin: 409 + no-mutation) and "gateway + MCP half" (risk_module: IdeaConflictError + idea_conflict flag). §11.3 updated to reflect the split.

---

### R8 → R9 (2026-04-22)

Codex R8 verdict: **FAIL**. 1 blocker + 1 should-fix + 1 nit. Codex actually ran the proposed SQLite UPSERT locally and confirmed it would fail at runtime — most rigorous finding of the review series.

**Blocker (resolved)**:

1. **SQLite UPSERT syntax invalid for partial unique index** — R7's `INSERT ... ON CONFLICT (idea_id) DO NOTHING` doesn't match a partial unique index (`WHERE idea_id IS NOT NULL`) without repeating the predicate. Would raise `OperationalError`. **Fix**: §8.5 SQL updated to `INSERT ... ON CONFLICT (idea_id) WHERE idea_id IS NOT NULL DO NOTHING; SELECT ... WHERE idea_id = :idea_id`. WHERE clause is explicitly documented as load-bearing.

**Should-fix (resolved)**:

2. **§1 non-goals contradicted §6.2/§8.5 uniqueness change** — scope said "no new uniqueness constraint" but R7 made the partial UNIQUE idea_id index load-bearing. **Fix**: §1 non-goal narrowed — "Deduplication by heuristics OTHER than idea_id identity" is out of scope; DB-level dedup on `idea_id` is explicitly IN scope (load-bearing). `(ticker, label)` uniqueness unchanged (already enforced).

**Nit (resolved)**:

3. **§15 R1→R2 entry still had `legacy:{source}:{ticker}:{source_date}` without historical marker** — R7 grep used `{date}` placeholder and missed the `{source_date}` variant. **Fix**: entry rewritten to describe the historical 3-part form narratively + explicit "superseded in R5" marker pointing to §4.2 canonical form.

---

### R9 → R10 (2026-04-22)

Codex R9 verdict: **FAIL**. 1 high + 1 medium. Codex re-verified R8's SQL fix works (ran it locally again).

**High (resolved)**:

1. **`actions/research.py` response normalization drops new fields** — live `_normalize_file_snapshot()` at `actions/research.py:747` whitelists a small fixed field set; new idea-seeded fields (`idea_id`, `idea_provenance`, `source_ref`, `idea_seeded`, `idea_backfilled`, `thesis_bootstrapped`, `draft_handoff_provenance_seeded`) would be silently DROPPED on their way through the action layer. MCP-layer flags would have nothing to derive from. **Fix**: §10.2 explicitly calls out the normalizer extension as load-bearing in sub-phase F. §10.3 file-list entry for `actions/research.py` upgraded — names the exact `_normalize_file_snapshot()` extension required + bumps line estimate. §10.4 adds a dedicated test driving through the action layer with stubbed gateway responses (not just MCP wrapper stubs) to catch this regression class.

**Medium (resolved)**:

2. **`agent/registry.py` not in sub-phase F file list** — `start_research` is also exposed via the agent registry at `registry.py:883-1273`; `routes/agent_api.py:114` builds schemas directly from the registry callable signature. Without registry update, the HTTP agent API would still reject `idea`. **Fix**: §10.3 adds `agent/registry.py` to file list with explicit reference to `routes/agent_api.py` schema-generation dependency. §10.3 also adds a new test file (`tests/routes/test_agent_api_idea.py`); §10.4 adds two tests — schema advertisement + POST acceptance.

---

### R10 → R11 (2026-04-22)

Codex R10 verdict: **FAIL**. 1 blocker only — all other prior fixes confirmed coherent. Trend now R10=1.

**Blocker (resolved)**:

1. **Wrong agent API endpoint paths** — R9's `tests/routes/test_agent_api_idea.py` test description invented `/agent/v1/tools/start_research`. Live endpoints are `POST /api/agent/call` (`routes/agent_api.py:63`) and `GET /api/agent/registry` (`routes/agent_api.py:106`); existing tests at `tests/routes/test_agent_api.py:70,205` use those exact paths. **Fix**: §10.4 test descriptions corrected to `GET /api/agent/registry` (assert `functions.start_research.params.idea` in returned schema) + `POST /api/agent/call` with `{"function": "start_research", "params": {"ticker": "...", "idea": {...}}}`. §10.3 `agent/registry.py` entry updated to cite both real route paths.

---

### R11 → ✅ **PASS** (2026-04-22)

Codex R11 verdict: **PASS**. Plan #4 is implementation-ready.

Codex independently verified all live-code anchors match plan: `ThesisField` bootstrap target, `IdeaProvenance` 2-field projection, `update_idea_provenance` hook, finalize pass-through, `_normalize_file_snapshot()` extension target, gateway classifier point, agent registry path. Listed 3 non-gating nits (since cleaned up post-PASS):

1. §10.3 file-table row for `tests/routes/test_agent_api_idea.py` still cited stale `/agent/v1/tools/start_research` even though §10.4 was corrected. Fixed.
2. §1 + §2 high-level summary said "index on idea_id" without "UNIQUE" qualifier; load-bearing design is partial UNIQUE per §6.2. Fixed.
3. REST contract for "idea-only" requests (omitted top-level `ticker`/`label`) — `routes.py:313` currently requires `ticker` at top-level. Sub-phase D first task: decide whether to relax that body model OR document caller-must-duplicate semantic. §8.4 test added covering both outcomes.

---

## Convergence summary

| Round | Findings | Notes |
|---|---|---|
| R1 | 6 blockers + 3 should-fix | Wrong Thesis target, wrong handoff shape, wrong storage model, wrong connector count, unready minting, ambiguous conflicts |
| R2 | 4 blockers + 3 should-fix | Fictional MemoryStore API, mint_idea_id signature drift, missing 409 gateway, stale prose, exit-gate scope, test paths, TOCTOU |
| R3 | 4 blockers + 3 should-fix | Surviving stale terms, source_id formula drift, wrong SQL table, contract contradictions §10/§11/§13, method names, atomic-write name, missing MCP test |
| R4 | 2 high + 2 medium + 1 medium | TOCTOU hedging, backend/action conflation, §7 contract self-inconsistency, test file layer, exit-gate path |
| R5 | 1 high + 3 medium | Legacy idea_id collision (multi-catalyst), §4.4 hot-lookup overclaim, missing TOCTOU migration test, idea_provenance_summary scalar/multi conflict |
| R6 | 1 blocker + 3 should-fix | Adjacent-section drift on legacy formula (§4.1/§5.2 missed by R5 grep), exit-gate path again, rollout-story contradiction §4.1 vs §9.5, migration log surface unspecified |
| R7 | 1 high + 2 medium | Stale "frontmatter"/"position_metadata"/"11 connectors" surviving R3 grep, legacy formula drift §4.1 vs §4.2 (R3-style), wrong SQL table `handoffs` vs `research_handoffs`, §10/§11/§13 IdeaConflictError vs ActionValidationError + IdeaPayload-via-upcast scope creep |
| R8 | 1 blocker + 1 should-fix + 1 nit | SQLite UPSERT syntax invalid for partial unique index (Codex ran SQL locally), §1 non-goals contradicted §6.2/§8.5, R7 grep missed `{source_date}` placeholder variant |
| R9 | 1 high + 1 medium | `actions/research.py:_normalize_file_snapshot()` field-whitelisting drops new fields, `agent/registry.py` + agent-API surface missing from §10.3 |
| R10 | 1 blocker | Wrong agent API endpoint paths in §10.4 (invented `/agent/v1/tools/...`; live is `/api/agent/call` + `/api/agent/registry`) |
| R11 | **PASS** | All anchors verified. 3 non-gating nits cleaned up post-PASS. |

**Pattern observed across R3-R7**: adjacent-section drift was the recurring failure mode — fixing pointed-at lines without grepping the doc for similar wording in other sections. R7+ used systematic grep-sweep before revising, dramatically reducing finding counts (R5=4, R6=4, R7=3, R8=3, R9=2, R10=1, R11=PASS).

**Highest-value Codex finding**: R8's catch of the invalid SQLite partial-index UPSERT syntax — found by actually running the SQL locally. Would have been a runtime bug at sub-phase D implementation.

---

Plan #4 ready for sub-phase A implementation. Recommend stacking implementation on either main or `feat/handoff-artifact-v1-1-plan-2` (per dependency: D requires plans #1+#2 implemented; A/B/C/E/F can drop earlier).
