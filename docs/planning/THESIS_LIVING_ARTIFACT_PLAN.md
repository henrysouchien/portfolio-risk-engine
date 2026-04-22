# Thesis Living Artifact — Implementation Plan

**Status**: DRAFT R6 — addresses Codex R5 PASS-WITH-CHANGES (2 mediums + 1 low). R1-R5 change logs preserved inline.
**Created**: 2026-04-17
**Design inputs**:
- `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` — contract shapes (PASS R6), §6.6 + §10a (16 locked decisions)
- `AI-excel-addin/docs/design/thesis-as-source-of-truth-skill-architecture.md` — skill triad, THESIS.md pattern
- `AI-excel-addin/docs/design/thesis-linkage-task.md` — F3c (ThesisLink/ThesisScorecard)
- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` — skill integration targets

**R2 change log** (addresses Codex R1):
- Per-user scoping from day 1 (removed v2 punt). Uses `get_workspace_dir(user_id)` from `memory/__init__.py:220`.
- Stable-ID carry-forward via HTML-comment hidden IDs in markdown + semantic matcher fallback.
- Interleaved unknown markdown sections preserved via position-anchored `raw_markdown_extras` list.
- `UNIQUE(user_id, ticker, label)` uses empty-string default for label (SQLite multi-NULL problem resolved).
- MCP tools moved to `risk_module/mcp_tools/thesis.py` + `actions/thesis.py` (the existing research-MCP pattern).
- Thesis tables merged into existing per-user `research.db` (dropped separate thesis.db).
- Sub-phase C split into C1 (pure parser/serializer) and C2 (load/merge/watcher).
- Added `entry_id` with UNIQUE constraint for Decisions Log idempotency.
- v1 scorecard classification rule table added (§11.2).
- Shared-slice count corrected to 16 fields (added `company`).
- Added `thesis_remove_link` MCP tool (11 tools total).
- Acceptance gate lists specific `SKILL_CONTRACT_MAP.md` row changes.
- `ResolvedLink.resolution_strength` derived from anchor order (not fuzzy confidence).
- Boundary test composes stub from shared-slice type modules (not hand-copied).

**Closes**: **G13** (schema side). Unblocks plans #2/#3/#6. Parallel-shippable with thesis-as-SSoT skill triad.

---

## 1. Purpose & non-goals

Ship the `Thesis` Pydantic type + `theses/{TICKER}[__label].md` markdown round-trip + append-only Decisions Log with per-key lock + `ThesisLink`/`ThesisScorecard` with 5-anchor resolver + schema-boundary test enforcing shared-slice isomorphism.

**Non-goals** (deferred):
- HandoffArtifact v1.1 evolution (plan #2). Plan #1 ships `Thesis` standalone; v1.0 handoff unchanged.
- `ModelBuildContext` construction (plan #3).
- `HandoffPatchOp` apply semantics (plan #6). Plan #1 ships typed patch-op receivers (stubs accept + log) but not applier. See §11.2 for v1 scorecard classification rule table.
- `ProcessTemplate` (plan #5). Thesis creation uses hardcoded defaults.
- Frontend rendering beyond the markdown file.
- Migration of existing `notes/tickers/*.md` ticker memory.

---

## 2. Sub-phase summary

| # | Sub-phase | Scope | Duration | Depends on |
|---|---|---|---|---|
| A | Pydantic types | `Thesis`, `ThesisLink`, `ThesisScorecard`, shared-slice module, canonicalizers, stable-ID model | ~2 days | None |
| B | SQLite storage (merged into research.db) | 4 new tables + repository API | ~3 days | A |
| C1 | Markdown serializer + parser (pure) | Hidden-ID carry-forward, position-anchored extras | ~3 days | A |
| C2 | Load/merge/watcher integration | Parsed ⊕ SQLite merge, watcher wiring, round-trip tests | ~2 days | B, C1 |
| D | Decisions Log append helper | Per-(user_id, ticker, label) file lock + entry_id idempotency | ~1 day | B |
| E | ThesisLink 5-anchor resolver | §6.6 order + `resolution_strength` | ~2 days | A |
| F | ThesisScorecard runner | v1 classification rules (§11.2 table) | ~3 days | A, B, E |
| G | MCP tool surface (risk_module) | 11 tools + actions proxy via gateway | ~3 days | B, D, E, F |
| H | Shared-slice boundary test | Composition-based stub (non-tautological) | ~1 day | A |

**Total**: ~20 working days. Parallelism: C1 can run alongside B after A; E alongside B after A; D after B; F after E+B; G after D+E+F; H anytime after A.

---

## 3. Dependency graph

```
A (Pydantic types, shared-slice module)
  ├── B (research.db storage)
  │     ├── C2 (merge/watcher) ◄── C1 (parser/serializer)
  │     ├── D (log helper)
  │     └── F (scorecard) ◄── E (link resolver)
  │
  ├── C1 (parser/serializer, pure)
  ├── E (link resolver, pure)
  ├── H (boundary test)
  │
  └── B + D + E + F ── G (MCP tools)
```

---

## 4. Cross-cutting concerns

### 4.1 User scoping (R2 — per-user from day 1)

Confirmed via `api/memory/__init__.py:220-236`: memory layer is per-user; legacy shared workspace fallback was explicitly removed. Thesis follows the same pattern:

- **Structured data**: per-user SQLite at `data/users/{user_id}/research.db` — **merged into existing research DB** (R1 feedback — better transactional cohesion, shared FK space with `research_files`, `annotations`).
- **Markdown**: per-user workspace at `get_workspace_dir(user_id) / "theses" / {TICKER}.md` (or `{TICKER}__{label_slug}.md` when labeled). Never shared across users.
- **User lookup**: per-tool resolution via existing `X-Research-User-Id` header (`research/routes.py:23-38`) or `user_email` → user_id action layer (existing pattern).

No single-user dev vs multi-user prod fork — both paths use per-user scoping identically.

### 4.2 Markdown format — constrained sections + hidden IDs + position-anchored extras

**Section header → field mapping** (normative):

| Header | Field path | Notes |
|---|---|---|
| `# Thesis — {TICKER}` (optional `: {label}`) | identity | Header row |
| `## Thesis Statement` | `thesis.statement` | Prose body |
| `## Thesis Metadata` | `thesis.{direction, strategy, conviction, timeframe}` | Key-value bullets |
| `## Consensus View` | `consensus_view.{narrative, citations}` | Narrative + `[src_N]` tokens |
| `## Differentiated View` | `differentiated_view[]` | Each `### claim_id:{claim_id}` subsection is one claim |
| `## Invalidation Triggers` | `invalidation_triggers[]` | Bullet list with inline `{trigger_id}` |
| `## Business Overview` | `business_overview.*` | Description + `### Segments` |
| `## Catalysts` | `catalysts[]` | Each `### catalyst_id:{catalyst_id}` subsection |
| `## Risks` | `risks[]` | Each `### risk_id:{risk_id}` subsection |
| `## Valuation` | `valuation.*` | Key-value + rationale prose |
| `## Peers` | `peers[]` | Table form |
| `## Assumptions` | `assumptions[]` | Each `### assumption_id:{assumption_id}` subsection |
| `## Qualitative Factors` | `qualitative_factors[]` | Each `### factor_id:{id}` subsection |
| `## Ownership` | `ownership.*` | Key-value + recent_activity prose |
| `## Monitoring` | `monitoring.watch_list[]` | Bullet list (supports both string and object shapes per §6.2 polymorphism) |
| `## Industry Analysis` | `industry_analysis.*` | Shared-slice (§6.6 R5 change) |
| `## Quantitative Framing` | `quantitative_framing.*` | Thesis-only |
| `## Position Metadata` | `position_metadata.*` | Thesis-only |
| `## Sources` | `sources[]` | Numbered list with `[src_N]` labels |
| `## Model Linkage` | `model_links[]` | Table form (updated via /thesis-link skill) |
| `## Decisions Log` | `decisions_log[]` | Table form (read-only in markdown) |

**Stable-ID carry-forward** (R2 — closes Codex R1 blocker #2):

Stable IDs embedded as `### <role>_id:{uuid}` headers in subsections. Example:

```markdown
### claim_id:c_3a7f0b
**Claim**: Revenue acceleration to 20%
**Rationale**: HCM market expansion ...
```

Parser reads the ID from the `###` header. If absent → **conservative** semantic matcher (R3 — closes Codex R2 blocker #2):

1. **Role-scoped only**: a missing `claim_id` only matches against existing `differentiated_view[]` claims in the same Thesis; `risk_id` only against `risks[]`; etc. Cross-role matching is rejected.
2. **Field-aware comparison**: for each candidate role, a match score combines:
   - Primary-field Jaccard (e.g., claim text for claims; description for risks)
   - Structured-field equality (e.g., severity, type) weighted at 0.3
3. **Strict threshold + margin**: best match must have `combined_score ≥ 0.90` AND exceed second-best by `≥ 0.1`. Ambiguous matches (close top-2) fall through.
4. **One-to-one reservation**: each prior entry can be matched by at most one incoming entry. Once a prior ID is claimed, it's removed from the candidate pool for the rest of the parse.
5. **On ambiguity or no match → new UUID4 + structured warning** (`parse_warning: id_reassigned` with context). Lineage is never silently corrupted — a false-positive match on wrong content is worse than a new ID.

This resists: duplicate-claim edits (top-2 tie → reject), split claims (each half likely below threshold → both get new IDs), role drift (impossible), wholesale ID strip (first pass: no matches except unique content; subsequent edits preserved via the re-emitted IDs).

**Position-anchored extras** (R2 — closes Codex R1 blocker #3):

Unknown sections preserved as positional list:

```python
raw_markdown_extras: list[UnknownSection]
# UnknownSection:
#   anchor_after: str | None    # name of the known section this follows, None = top
#   content: str                # full unknown section text including ## header
```

Parser collects each unknown `##` in order with its positional anchor. Serializer re-interleaves by placing unknown sections immediately after their anchor. Bit-exact preservation under round-trip.

**Citation tokens**: `[src_N]` (per §6.6 stable `src_n` format). Parser resolves to source_id references; serializer emits from `Thesis.sources[].id`.

### 4.3 Memory watcher integration

Watcher already exists (`api/memory/watcher.py`). New handler registered in sub-phase C2: file change at `{workspace}/theses/*.md` triggers a **two-step flow** keyed on research_file_id per R5:

1. **Path → parent resolution**: parse filename → `(ticker, label)`. Look up `research_files` by `(user_id, ticker, label)` → `research_file_id`. This is the ONLY use of `(ticker, label)` as a lookup key in the watcher path.
2. **Parent-id-keyed upsert**: call `thesis_repository.upsert_thesis_from_markdown(research_file_id, parsed_thesis)`. Fails with typed `ResearchFileNotFound` if no matching research_files row (e.g., analyst manually renamed the markdown file without going through the rename path).

Writes emitted by serializer use `writing_path()` context manager to suppress watcher loopback (same pattern as `markdown_sync.py`). Under concurrent parent rename + markdown edit, the watcher retries lookup once after a short delay to let `update_thesis_parent_snapshot()` finish; persistent `ResearchFileNotFound` surfaces as a structured warning in the thesis service log.

### 4.4 Shared-slice isomorphism (§10a.13)

Both `Thesis` and the `HandoffArtifactV1_1Stub` (until plan #2) **import shared-slice field types from a single module** — `schema/thesis_shared_slice.py`. This guarantees the boundary test is non-tautological: the stub has Handoff-only fields (`thesis_ref`, `idea_provenance`, `assumption_lineage`, `scorecard_ref`, Handoff-shaped `model_ref`) that Thesis doesn't have, and the test asserts those do NOT leak into Thesis. Shared-slice fields are asserted structurally equal via Pydantic JSON schema.

### 4.5 Per-key lock (§10a.7)

Unchanged from R1: filesystem lock at `data/users/{user_id}/locks/thesis_{ticker}_{label_slug}.lock` via `fcntl.flock()`. Keeps cross-resource (SQLite + markdown) semantics clean.

### 4.6 Enum canonicalization (§10a.9)

Shared canonicalizer helpers in `schema/enum_canonicalizers.py`. Accepts Title-Case legacy input on write, emits snake_case. Used by `Thesis` and future `HandoffArtifact v1.1`.

---

## 5. Sub-phase A — Pydantic types

### 5.1 Goal

Emit `Thesis`, `ThesisLink`, `ThesisScorecard`, plus the **shared-slice field types** as a separate module (sub-phase H's invariant-preservation mechanism).

### 5.2 Design

**Key module split**:
- `schema/thesis_shared_slice.py` — Pydantic types for 16 shared-slice fields. Imported by both `schema/thesis.py` and `schema/_handoff_v1_1_stub.py` (sub-phase H).
- `schema/thesis.py` — `Thesis` (composes shared-slice + Thesis-only), `ThesisLink`, `ThesisScorecard`, `DecisionsLogEntry`, supporting types.
- `schema/enum_canonicalizers.py` — reused direction/strategy/timeframe canonicalizers.

**Shared-slice fields (16)** — per §6.6 R5: `company`, `thesis`, `consensus_view`, `differentiated_view`, `invalidation_triggers`, `business_overview`, `catalysts`, `risks`, `valuation`, `peers`, `assumptions`, `qualitative_factors`, `ownership`, `monitoring`, `sources`, `industry_analysis`.

**Thesis-only fields**: `decisions_log[]`, `model_links[]`, `scorecard?` (cache), `markdown_path`, `raw_markdown_extras[]`, `quantitative_framing?`, `position_metadata?`, `model_ref?` (Thesis-shaped: `{model_id, version, file_path?, last_updated?, drivers_locked: [driver_key]}`), plus identity (`thesis_id, user_id, ticker, label?, version, created_at, updated_at`).

**Stable-ID model**:
- IDs are strings (UUID4 by default; HTML-comment-readable in markdown). Assigned by backend on first persistence (§10a.16 — backend-assigned).
- `Assumption.assumption_id`, `Risk.risk_id`, `Catalyst.catalyst_id`, `InvalidationTrigger.trigger_id`, `DifferentiatedViewClaim.claim_id`, `QualitativeFactor.id` (existing in v1.0), `DecisionsLogEntry.entry_id` — all typed as `Optional[str]` on Pydantic input, guaranteed non-null after persist.
- Semantic matcher (sub-phase C1) reuses IDs from existing records on parse; falls back to new UUID only when no match.

**`company` field clarification** (R2 — per Codex should-fix):
- `company.ticker` — mirrors thesis identity. Read from markdown `#` header.
- `company.name / sector / industry / fiscal_year_end / most_recent_fy / exchange` — populated from SQLite (synced from `research_files` row or FMP profile fetch). Not markdown-authored. Markdown displays them read-only.

### 5.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `schema/thesis_shared_slice.py` | 16 shared-slice Pydantic types | ~300 |
| `schema/thesis.py` | Thesis composition + link/scorecard types | ~500 |
| `schema/enum_canonicalizers.py` | direction/strategy/timeframe canonicalizers | ~100 |
| `schema/_shared_slice.py` | List of shared-slice field paths (boundary test input) | ~30 |
| `tests/schema/test_thesis_types.py` | Pydantic unit tests | ~450 |

### 5.4 Tests (~45)

- Enum canonicalization (9 tests: each enum × Title-Case + snake_case + invalid)
- ID Optional → assigned-on-persist (5 tests, one per ID field)
- Shared-slice field presence (16 tests, one per field)
- Thesis-only field presence (8 tests)
- `[src_N]` format validation (2 tests)
- `company` field DB-only path (3 tests)
- Validator edge cases (2 tests)

### 5.5 Acceptance gate

- All tests pass.
- `schema/_shared_slice.py` lists exactly 16 fields, matches §6.6 round-trip rule.
- `schema/thesis_shared_slice.py` exports one type per shared-slice field.

### 5.6 Rollback

Delete the four new files. No downstream consumer yet.

---

## 6. Sub-phase B — SQLite storage (merged into research.db)

### 6.1 Goal

Four new tables in existing per-user `research.db`. Repository API with atomic multi-section updates.

### 6.2 Schema (added to `api/research/repository.py` init SQL)

```sql
CREATE TABLE IF NOT EXISTS theses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thesis_id TEXT NOT NULL UNIQUE,                 -- UUID4
  user_id TEXT NOT NULL,
  research_file_id INTEGER NOT NULL,              -- R3: canonical parent identity
  ticker TEXT NOT NULL,                           -- R4: denormalized snapshot of parent (see sync rule)
  label TEXT NOT NULL DEFAULT '',                 -- R4: denormalized snapshot of parent (see sync rule)
  version INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  markdown_path TEXT NOT NULL,                    -- relative to workspace
  artifact_json TEXT NOT NULL,                    -- full Thesis excluding decisions_log
  schema_version TEXT NOT NULL DEFAULT '1.0',
  FOREIGN KEY(research_file_id) REFERENCES research_files(id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_theses_user_ticker_label
  ON theses(user_id, ticker, label);
CREATE UNIQUE INDEX IF NOT EXISTS idx_theses_research_file_id  -- R5: 1:1 parent invariant
  ON theses(research_file_id);
-- R5 canonical-parent rule:
--   research_file_id is the AUTHORITATIVE parent key. UNIQUE(research_file_id)
--   enforces 1:1 parent:thesis relationship at the DB level. The
--   (user_id, ticker, label) UNIQUE is secondary — it prevents the parent-rename
--   race where two rows might otherwise be created before snapshot sync. The
--   strict invariant: exactly one thesis row per research_files row.
--
--   (ticker, label) on theses are denormalized snapshots kept in sync via
--   update_thesis_parent_snapshot(research_file_id, new_ticker, new_label),
--   called whenever research_files.label or .ticker is mutated at
--   api/research/repository.py:543. The rename flow keys on research_file_id,
--   NOT (ticker, label); this prevents the race Codex R4 flagged.
--   Rename of parent updates the theses row AND the markdown file path
--   ({workspace}/theses/{OLD_NAME}.md → {workspace}/theses/{NEW_NAME}.md).
--   Markdown rename happens in the application layer after the DB commit.

CREATE TABLE IF NOT EXISTS thesis_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thesis_link_id TEXT NOT NULL UNIQUE,
  thesis_id TEXT NOT NULL,
  thesis_point_id TEXT NOT NULL,
  link_json TEXT NOT NULL,
  created_at REAL NOT NULL,
  FOREIGN KEY(thesis_id) REFERENCES theses(thesis_id) ON DELETE CASCADE  -- R4
);
CREATE INDEX IF NOT EXISTS idx_thesis_links_thesis ON thesis_links(thesis_id);

CREATE TABLE IF NOT EXISTS thesis_scorecards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scorecard_id TEXT NOT NULL UNIQUE,
  thesis_id TEXT NOT NULL,
  scored_at REAL NOT NULL,
  scorecard_json TEXT NOT NULL,
  summary_status TEXT NOT NULL,
  FOREIGN KEY(thesis_id) REFERENCES theses(thesis_id) ON DELETE CASCADE  -- R4
);
CREATE INDEX IF NOT EXISTS idx_scorecards_thesis_time
  ON thesis_scorecards(thesis_id, scored_at DESC);

CREATE TABLE IF NOT EXISTS thesis_decisions_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  entry_id TEXT NOT NULL UNIQUE,                  -- R2: idempotency key
  thesis_id TEXT NOT NULL,
  appended_at REAL NOT NULL,
  entry_json TEXT NOT NULL,                       -- full DecisionsLogEntry
  FOREIGN KEY(thesis_id) REFERENCES theses(thesis_id) ON DELETE CASCADE  -- R4
);
CREATE INDEX IF NOT EXISTS idx_decisions_log_thesis_time
  ON thesis_decisions_log(thesis_id, appended_at DESC);
```

**R4 cascade rule**: `research_files` deletion (rare) cascades to `theses`, then to all child tables. Markdown cleanup is handled in application layer by `ThesisService.on_research_file_delete()`, which removes `{workspace}/theses/{TICKER}[__label].md` after the DB cascade commits. Tests cover the full cascade path.

**R2 changes**:
- `label TEXT NOT NULL DEFAULT ''` resolves SQLite's multi-NULL non-conflicting behavior in `UNIQUE`. Empty-string means "no label"; non-empty means "labeled".
- `entry_id` on `thesis_decisions_log` with `UNIQUE` enables lock-protected idempotent appends.

Decisions Log is a **separate table** (not in `artifact_json`) for append-only semantics without rewriting the full artifact on each append.

### 6.3 Migration strategy

`repository.py:12` has `CURRENT_SCHEMA_VERSION = 3`. Plan #1 bumps to **4** (3 → 4 upgrade path). Migration:
- Add new branch to the existing `_migrate_schema` chain after the `<3` block (see `repository.py:403`).
- New branch creates 4 thesis tables via `CREATE TABLE IF NOT EXISTS`.
- Fresh-init path (`CREATE_ALL_SQL`) appends the 4 new DDLs verbatim.
- Tests: fresh-init at v4; 3→4 upgrade path; no-op re-migration.

### 6.4 Repository API — extends existing `ResearchRepository`

New methods added to `ResearchRepository` (not a separate class — simpler + shared connection):

```python
class ResearchRepository:
    # ... existing methods ...

    # Thesis CRUD — R5: parent-id-keyed where possible
    def create_thesis(research_file_id, initial_fields=None) -> dict
        # Resolves (ticker, label) from research_files by research_file_id.
        # Raises if a thesis already exists for this research_file_id (1:1 invariant).
    def get_thesis_by_id(thesis_id) -> dict | None
    def get_thesis_by_research_file(research_file_id) -> dict | None     # R5: canonical lookup
    def get_thesis(ticker, label='') -> dict | None                      # Convenience; DOES NOT key creation.
    def list_theses(ticker=None) -> list[dict]
    def update_thesis_artifact(thesis_id, artifact_json) -> dict
    def upsert_thesis_from_markdown(research_file_id, parsed_thesis) -> dict
        # Keys on research_file_id (not ticker/label). If research_file was renamed,
        # parsed markdown header may lag — application layer reconciles.
    def update_thesis_parent_snapshot(research_file_id, new_ticker, new_label) -> None
        # R5: called by research_files rename path. Updates theses.ticker + .label,
        # then triggers markdown path rename in ThesisService.

    # Decisions Log
    def append_decisions_log_entry(thesis_id, entry: DecisionsLogEntry) -> dict
    def list_decisions_log(thesis_id, limit=None) -> list[dict]

    # Links
    def upsert_thesis_link(thesis_id, link: ThesisLink) -> dict
    def list_thesis_links(thesis_id) -> list[dict]
    def remove_thesis_link(thesis_link_id) -> None

    # Scorecards
    def save_scorecard(thesis_id, scorecard: ThesisScorecard) -> dict
    def latest_scorecard(thesis_id) -> dict | None
```

### 6.5 Files to modify

| File | Change |
|---|---|
| `api/research/repository.py` | Add 4 table DDLs + extension methods (~400 new lines) |
| `tests/api/research/test_repository_thesis.py` | New — ~500 lines |

### 6.6 Tests (~40)

- CRUD per table (12 tests)
- `label=''` vs `label='bull'` uniqueness (4 tests) — NULL-safe UNIQUE
- `entry_id` UNIQUE enforcement (3 tests)
- Decisions Log append order + persistence (3 tests)
- Link upsert + resolution-anchor tracking (5 tests)
- Scorecard save + latest (3 tests)
- Migration: schema v3 → v4 path + fresh-init at v4 (3 tests)
- Per-user isolation (3 tests)
- artifact_json round-trips Thesis (4 tests)

### 6.7 Acceptance gate

- All tests pass.
- Existing research-repo tests still green (no regression).
- Tables live in existing `research.db`.

### 6.8 Rollback

Drop the 4 new tables; revert repository extension methods. Existing research workspace unaffected.

---

## 7. Sub-phase C1 — Markdown serializer + parser (pure)

### 7.1 Goal

Round-trippable parser + serializer per §4.2. Includes stable-ID carry-forward via hidden IDs in subsection headers + position-anchored unknown-section preservation.

### 7.2 Design

**Serializer** (`serialize_thesis(thesis: Thesis) -> str`):
- Header: `# Thesis — {ticker}[: {label}]` + sync directive comment (reuses `_SYNC_HEADER_PREFIX` from `markdown_sync.py`)
- Known sections emitted in canonical order per §4.2
- List-item subsections render stable IDs: `### <role>_id:{uuid}` (e.g., `### claim_id:c_3a7f0b`)
- Decisions Log rendered as read-only table
- Unknown sections interleaved per `raw_markdown_extras[*].anchor_after`

**Parser** (`parse_thesis_markdown(content: str, prior: PriorThesisIndex | None = None) -> ParsedThesis`):
- Splits on `##` headers. Each known header dispatches to a section parser.
- Subsection IDs read from `### <role>_id:{uuid}` format. Missing ID → semantic matcher per §4.2.
- **`prior` is injected** (R3 — preserves C1 purity). When `prior` is None, missing IDs always get new UUIDs. When `prior` is provided (populated by C2 from SQLite), the matcher runs against it. C1 has no DB dependency; C2 owns the `prior` lookup.
- `PriorThesisIndex` is a typed value object: `{claims_by_id, risks_by_id, catalysts_by_id, assumptions_by_id, triggers_by_id, factors_by_id}` — each a `dict[str, NormalizedEntry]`.
- Unknown sections collected with positional anchor.
- Returns `ParsedThesis` — fields populated only where markdown provides them (None for absent sections).

### 7.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `schema/thesis_markdown.py` | Pure serializer + parser (no I/O, no DB) | ~700 |
| `tests/schema/test_thesis_markdown.py` | Round-trip tests + fixtures | ~600 |
| `tests/schema/fixtures/thesis_*.md` | 10 round-trip fixtures | ~120 each |

### 7.4 Tests (~40)

- Round-trip on 10 fixtures: empty, minimal, full, all-sections, interleaved-unknown, nested-unknown, stable-IDs-preserved, stable-IDs-missing (matcher), label-scoped, multi-claim differentiated_view (10 tests)
- Per-section parser × 20 known sections (round-trip + bad-input) (40 tests — matches §4.2 section count)
- `[src_N]` tokens: parse, serialize, unknown warning (3 tests)
- Stable-ID carry-forward: explicit ID preserved, missing ID matched via Jaccard, below-threshold gets new ID (6 tests)
- Position-anchored extras: bit-exact preservation under round-trip (3 tests)
- Label-slug filename (2 tests)

### 7.5 Acceptance gate

- `parse(serialize(thesis))` equals `thesis` on all populated fields, across 10 fixtures.
- Hidden IDs round-trip exactly.
- Interleaved unknown sections preserved in order bit-exact.
- No data loss when markdown omits a structured section (ParsedThesis has None for that section).

### 7.6 Rollback

Delete the three new files. B is unaffected (no C1 imports).

---

## 8. Sub-phase C2 — Load/merge/watcher integration

### 8.1 Goal

Wire C1 to B: on markdown edit, parse and merge with SQLite Thesis; on programmatic update, serialize and write. Watcher integrated.

### 8.2 Design

```python
def load_thesis(user_id, research_file_id) -> Thesis:
    # R5: keys on research_file_id (canonical). Resolves markdown path from
    # current (ticker, label) snapshot on the theses row.
    # Parses markdown if file exists; merges with SQLite.
    # Returns merged Thesis.

def load_thesis_by_ticker(user_id, ticker, label='') -> Thesis:
    # Convenience: resolves research_file_id via research_files lookup, then
    # calls load_thesis(). Used by agent tools that key on ticker naturally.

def save_thesis_markdown(thesis: Thesis) -> None:
    # Serialize thesis → markdown.
    # Write via _atomic_write + writing_path suppression.
    # File path from thesis.markdown_path (which was set at create using
    # current ticker/label snapshot).

def on_watcher_markdown_change(user_id, path: Path) -> None:
    # Triggered by memory watcher when {workspace}/theses/*.md changes.
    # R5: two-step flow.
    # 1. Parse filename → (ticker, label). Look up research_file_id via
    #    repo.get_research_file_by_ticker_label(user_id, ticker, label).
    # 2. If found: parse markdown with PriorThesisIndex from current row,
    #    then repo.upsert_thesis_from_markdown(research_file_id, parsed).
    # If not found: emit ResearchFileNotFound warning (see §4.3 retry rule).

def on_parent_rename(research_file_id, old_ticker, old_label,
                     new_ticker, new_label) -> None:
    # R5: called by research_files rename path at repository.py:543.
    # 1. repo.update_thesis_parent_snapshot(research_file_id, new_ticker, new_label)
    # 2. Rename markdown file: {workspace}/theses/{old}.md → {new}.md (atomic).
    # 3. Update theses.markdown_path.
    # Suppressed from watcher via writing_path() during rename.
```

### 8.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `api/research/thesis_service.py` | load/save/merge + watcher handler | ~300 |
| `tests/api/research/test_thesis_service.py` | Integration tests | ~350 |

### 8.4 Files to modify

| File | Change |
|---|---|
| `api/memory/watcher.py` | Register `theses/` handler |

### 8.5 Tests (~20)

- Load: markdown-only, SQLite-only, both (3 tests)
- Save + reload: identity preserved (2 tests)
- Merge: markdown-override-SQLite, SQLite-fill-absent (4 tests)
- Watcher: file change triggers upsert (3 tests)
- Suppression: serializer write doesn't loop (2 tests)
- Concurrent save vs watcher race (2 tests)
- Absent markdown file on load (ok, returns SQLite-only) (2 tests)
- Malformed markdown → structured warning, no data loss (2 tests)

### 8.6 Acceptance gate

- All tests pass.
- Watcher wired without loopback regressions.

### 8.7 Rollback

Delete the two new files; revert watcher handler registration.

---

## 9. Sub-phase D — Decisions Log append helper

### 9.1 Goal

Per-(user_id, ticker, label) locked append. Closes §10a.7. Idempotent via `entry_id` UNIQUE.

### 9.2 Design

```python
def append_decisions_log_entry(
    repo: ResearchRepository,
    thesis_id: str,
    entry: DecisionsLogEntry,      # may have entry_id already
    *,
    timeout_seconds: float = 5.0,
) -> DecisionsLogEntry:
    # 1. If entry.entry_id is None, assign UUID4.
    # 2. Acquire fcntl file lock on
    #    data/users/{user_id}/locks/thesis_{ticker}_{label_slug}.lock
    #    with timeout.
    # 3. INSERT OR IGNORE INTO thesis_decisions_log. If ignored (duplicate entry_id),
    #    return existing row.
    # 4. Release lock.

    # Raises DecisionsLogLockTimeout if lock not acquired in timeout.
```

### 9.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `api/research/thesis_log_helpers.py` | Helper + fcntl primitives | ~180 |
| `tests/api/research/test_thesis_log_helpers.py` | Concurrency tests | ~300 |

### 9.4 Tests (~14)

- Append single → row appears (1)
- Concurrent appends from two processes → ordered, no loss (3, multiprocess harness)
- Lock timeout raises (1)
- Lock release on error (2)
- Idempotent on duplicate entry_id (3)
- Lock-file cleanup (2)
- entry_id assigned when None (2)

### 9.5 Acceptance gate

- Multi-process tests pass on macOS and Linux.
- Idempotency verified via explicit duplicate-append.

### 9.6 Rollback

Delete the two new files; repository-level `append_decisions_log_entry` still works (unlocked, unsafe under concurrency).

---

## 10. Sub-phase E — ThesisLink 5-anchor resolver

### 10.1 Goal

`resolve_link(link, model) -> ResolvedLink` per §6.6 order. Adds `resolution_strength: int` derived from anchor order (Codex R1 consider #2).

### 10.2 Design

```python
@dataclass
class ResolvedLink:
    line_item: LineItem | None
    anchor: Literal["driver_key", "data_concept_id", "structural_fingerprint",
                    "template_version_cache", "model_item_id", "none"]
    resolution_strength: int          # 5=driver_key, 4=concept, 3=fingerprint,
                                       # 2=version_cache, 1=model_item_id, 0=none
    warnings: list[str]

def resolve_link(link: ThesisLink, model: FinancialModel) -> ResolvedLink: ...
```

Reuses `schema/driver_resolver.py::resolve_driver_key()` for step 1.

### 10.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `schema/thesis_link_resolver.py` | Resolver | ~250 |
| `tests/schema/test_thesis_link_resolver.py` | Per-anchor tests + template fixtures | ~450 |

### 10.4 Tests (~26)

- Per-anchor resolve (10: 2 each × 5 anchors)
- Structural fingerprint sub-order 3.1→3.4 (6)
- Template_version-null skip path (2)
- Model_item_id stale warning (2)
- First-hit wins (2)
- Graceful degradation on each failure (2)
- Fixture: pre-expansion model (1)
- Fixture: post-expansion model (1)

### 10.5 Acceptance gate

- Resolution order matches §6.6 exactly.
- `resolution_strength` derived deterministically from anchor used.
- Stale-cache warnings surface in `warnings`.

### 10.6 Rollback

Delete the two new files. F depends on E; roll back F too.

---

## 11. Sub-phase F — ThesisScorecard runner with v1 classification rules

### 11.1 Goal

`score_thesis(thesis, model, actuals?, consensus?) -> ThesisScorecard` per F3c. Explicit v1 classification rule table.

### 11.2 v1 classification rules (R3 — closes Codex R2 should-fix)

**Per-entry classification — comparator matrix by `thesis_direction`** (enum per INVESTMENT_SCHEMA_UNIFICATION_PLAN.md §6.6):

Each `ThesisLink.thesis_direction` maps to a specific comparator:

| thesis_direction | Inputs needed | Confirmed when | Challenged when | Disconfirmed when |
|---|---|---|---|---|
| `above_consensus` | actuals + consensus OR model + consensus | actual/model > consensus × 1.02 | actual/model between ±2% of consensus | actual/model < consensus × 0.95 for ≥3 consecutive periods |
| `below_consensus` | actuals + consensus OR model + consensus | actual/model < consensus × 0.98 | actual/model within ±2% of consensus | actual/model > consensus × 1.05 for ≥3 consecutive periods |
| `specific_value` | actuals OR model + `thesis_value` | |actual − thesis_value| / thesis_value < 0.05 (within 5%) | 5% ≤ deviation < 15% | deviation ≥ 15% for ≥3 consecutive periods, OR sign flipped |
| `directional` | actuals OR model | `sign(actual_trend) == sign(thesis_value)` where `actual_trend = actual[last_period] - actual[first_period]` across `ThesisLink.periods` | opposite sign, any magnitude | opposite sign AND `abs(actual_trend) > 2 × abs(thesis_value)` |

**Resolver-based overrides** (apply first):

| Input | Resulting status |
|---|---|
| `ResolvedLink.anchor == "none"` | `unresolvable` |
| Actuals absent AND model absent for target concept | `tracking` (insufficient signal — not an error, just not yet scorable) |

**Model-only path** (actuals absent, model present) — per-enum (R4, closes Codex R3 medium):

| thesis_direction | Model-only rule |
|---|---|
| `above_consensus` | Need consensus lookup for the metric. If consensus available: apply the `above_consensus` actuals rule with model value in place of actual. If consensus absent: `tracking` (insufficient signal). |
| `below_consensus` | Symmetric to above: consensus-aware comparison with model substituted for actual. If no consensus: `tracking`. |
| `specific_value` | Let `target = thesis_value`, `diff = model_value - target`. **Zero-target guard**: if `abs(target) < 1e-9`, fall back to absolute-diff bands using the **resolved LineItem's `unit`** (`ResolvedLink.line_item.unit`, from the resolver in sub-phase E). Tolerance constants per unit in `ZERO_TARGET_TOLERANCES` (e.g., `Unit.dollars`: `abs_diff < 1_000_000 = confirmed`, etc.). Otherwise (non-zero target): ratio `abs(diff)/abs(target)` with bands: < 5% → `confirmed`, 5-10% → `tracking`, ≥ 10% → `challenged`. |
| `directional` | Needs trend, not percentage. **Target direction derived from `ThesisLink.thesis_value` sign alone** (scalar per schema §6.6): positive `thesis_value` → positive trend expected; negative → negative trend expected; exactly zero (rare) → defer to `specific_value` zero-target rules. **Observed direction from model**: compute `model_trend = sign(model_value[last_period] - model_value[first_period])` across `ThesisLink.periods`. Compare: matching sign → `tracking`; opposite sign → `challenged`; opposite AND `abs(model_delta)` > 2× `abs(thesis_value)` (large-magnitude overshoot in wrong direction) → `disconfirmed`. Percentage bands do NOT apply — only sign + magnitude comparison. No new ThesisLink field required. |

**Data sources** (R5 — no new ThesisLink fields required):
- `unit` comes from `ResolvedLink.line_item.unit` (LineItem already carries `unit: Unit` per `schema/models.py:286`). When the link is unresolvable, `specific_value` with zero target falls back to a default tolerance (`ZERO_TARGET_TOLERANCES["_default"]`).
- `directional` target direction comes from `sign(thesis_value)` alone (thesis_value is scalar per §6.6). Observed trend comes from `sign(value[last_period] - value[first_period])` over `ThesisLink.periods`, where `value` is either `actual` or `model` depending on data availability. No new field required; no per-period thesis series needed.
- `ZERO_TARGET_TOLERANCES` is a constant dict in `api/research/thesis_scorecard.py` keyed by `Unit` enum.

**Summary aggregation (R3 — fixes R2 "all-tracking" bug)**:

| Distribution | summary_status |
|---|---|
| ≥1 `disconfirmed` | `invalidated` |
| ≥1 `disconfirmed` OR ≥30% `challenged` (no disconfirmed) | `at_risk` |
| ≥1 `confirmed` AND 0 challenged AND 0 disconfirmed | `on_track` |
| All `tracking` (no confirmed, no negatives) | `on_track` | ← R3 fix: previously fell to `mixed` |
| ≥1 `confirmed` AND ≥1 `challenged` | `mixed` |
| Only `unresolvable` | `mixed` (scorecard has no data to judge) |
| Otherwise | `mixed` |

All thresholds are v1 constants in `api/research/thesis_scorecard.py` (not magic numbers). Refinement via observed data in follow-on plans.

### 11.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `api/research/thesis_scorecard.py` | Runner + classifier | ~400 |
| `tests/api/research/test_thesis_scorecard.py` | Per-status + fixtures | ~500 |

### 11.4 Tests (~28)

- Per-status classification (5 statuses × 3 scenarios = 15)
- Summary aggregation (4: on_track / mixed / at_risk / invalidated)
- Missing actuals (3)
- Missing consensus (2)
- Mixed set (2)
- Integration with resolver (2, E mocked)

### 11.5 Acceptance gate

- Classification table in §11.2 encoded as code constants (not magic numbers).
- Summary thresholds match §11.2.

### 11.6 Rollback

Delete the two new files. G defers scorecard-related tools.

---

## 12. Sub-phase G — MCP tool surface (11 tools in risk_module)

### 12.1 Goal

Thesis MCP tools in `risk_module/mcp_tools/thesis.py`, registered via `risk_module/mcp_server.py`. Delegate via `risk_module/actions/thesis.py` to the research gateway → AI-excel-addin backend. Matches the existing research-MCP pattern (`mcp_tools/research.py` + `actions/research.py`).

### 12.2 Tool list (11 — R2 adds `thesis_remove_link`)

| Tool | Purpose |
|---|---|
| `thesis_create` | Create new Thesis |
| `thesis_read` | Read Thesis (full or sections[]) |
| `thesis_list` | List theses (optional per-ticker) |
| `thesis_update_section` | Update a Thesis section |
| `thesis_append_decisions_log` | Append log entry (lock-protected) |
| `thesis_list_decisions_log` | List log entries |
| `thesis_upsert_link` | Create/update ThesisLink |
| `thesis_list_links` | List links for a thesis |
| `thesis_remove_link` | **R2 — new.** Remove a ThesisLink by id. |
| `thesis_run_scorecard` | Run scorecard on current model + actuals |
| `thesis_latest_scorecard` | Read latest stored scorecard |

### 12.3 Contract

- Agent format where applicable.
- Typed errors: `ThesisNotFound`, `InvalidSection`, `DecisionsLogLockTimeout`, `LinkResolutionFailed`, `LinkNotFound`.
- Routes through gateway per existing research-MCP pattern.

### 12.4 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `risk_module/mcp_tools/thesis.py` | 11 MCP tool wrappers | ~500 |
| `risk_module/actions/thesis.py` | Action-layer proxy via gateway | ~400 |
| `tests/mcp_tools/test_thesis_tools.py` | Per-tool tests | ~400 |

### 12.5 Files to modify

| File | Change |
|---|---|
| `risk_module/mcp_server.py` | Register 11 thesis tools (mirrors research imports at line ~196) |
| `risk_module/actions/__init__.py` | Export thesis actions |

### 12.6 Tests (~20)

- Happy path × 11 tools (11)
- Error paths: not-found, lock-timeout, invalid-section, link-not-found (4)
- Agent format compliance (3)
- Gateway error propagation (2)

### 12.7 Acceptance gate

- All tools callable from agent loop in smoke test.
- Errors typed + surfaced.
- Tools registered in mcp_server and appear in MCP tool catalog.

### 12.8 Rollback

Delete the three new files; revert registration edits.

---

## 13. Sub-phase H — Shared-slice boundary test

### 13.1 Goal

Non-tautological boundary test enforcing shared-slice isomorphism between `Thesis` and `HandoffArtifact v1.1` (stubbed until plan #2).

### 13.2 Design — composition-based stub (R2 — closes Codex R1 should-fix)

```python
# schema/_handoff_v1_1_stub.py
from schema.thesis_shared_slice import (
    CompanyShape, ThesisHeaderShape, ConsensusViewShape, ...  # 16 imports
)

class HandoffArtifactV1_1Stub(BaseModel):
    # Shared slice (REUSED from thesis_shared_slice)
    company: CompanyShape
    thesis: ThesisHeaderShape
    # ... 14 more shared-slice fields ...

    # HANDOFF-ONLY fields (shapes defined here; plan #2 owns the real versions)
    idea_provenance: IdeaProvenanceShape | None = None
    assumption_lineage: list[AssumptionLineageEntry] | None = None
    process_template_id: str | None = None
    scorecard_ref: ScorecardRef | None = None
    thesis_ref: ThesisRef | None = None
    model_ref: HandoffModelRefShape | None = None         # Handoff-shaped (different from Thesis)
    financials: FinancialsShape | None = None
    metadata: HandoffMetadataShape
```

**Non-tautology**: because Handoff has extra fields (idea_provenance, thesis_ref, etc.) the boundary test actively asserts:
1. Every field in `SHARED_SLICE_FIELDS` is present in BOTH types with identical shape.
2. Every field in `HANDOFF_ONLY_FIELDS` is present ONLY on stub, NOT Thesis.
3. Every field in `THESIS_ONLY_FIELDS` is present ONLY on Thesis, NOT stub.

### 13.3 Files to create

| File | Purpose | Est. lines |
|---|---|---|
| `schema/_handoff_v1_1_stub.py` | Stub composing shared-slice types + Handoff-only | ~250 |
| `tests/integration/test_shared_slice_isomorphism.py` | 3-direction boundary test | ~200 |

### 13.4 Tests (~8, includes golden-snapshot — R3)

- `test_shared_slice_fields_identical` — parametrized over 16 paths. Structural equality via Pydantic JSON schema.
- `test_handoff_only_fields_not_in_thesis` — parametrized over 8 paths (idea_provenance, assumption_lineage, process_template_id, scorecard_ref, thesis_ref, Handoff-shaped model_ref, financials, metadata).
- `test_thesis_only_fields_not_in_handoff` — parametrized over 8 paths (decisions_log, model_links, position_metadata, markdown_path, raw_markdown_extras, quantitative_framing, Thesis-shaped model_ref, scorecard).
- `test_shared_slice_list_matches_spec` — meta-test (list == §6.6 list).
- `test_total_field_count` — sanity.
- **`test_thesis_golden_schema`** (R3 — closes Codex R2 tautology): compares `Thesis.model_json_schema()` output to `tests/schema/snapshots/thesis_v1_0.schema.json`. Detects drift inside shared-slice internals (e.g., a `citations` element type change). On failure: test prints the diff + instructs updating the snapshot file explicitly. Prevents silent internal drift even when both types share a module.
- **`test_handoff_stub_golden_schema`** (R3): same approach for `HandoffArtifactV1_1Stub.model_json_schema()` → `tests/schema/snapshots/handoff_v1_1_stub.schema.json`. Plan #2 replaces the snapshot with `handoff_v1_1.schema.json` at that phase.
- Sanity: snapshots must not both be identical (cross-check they have Handoff-only + Thesis-only fields respectively).

**Why golden snapshots are non-optional**: without them, a shape change inside `CitationList` (or any shared internal type) passes both side-by-side inspection AND the parametrized field-identity test, because both types import the same module. The snapshot is the external source of truth.

**R4 — snapshot refresh policy**: Pydantic version is pinned in `api/requirements.txt:1445` so routine PRs don't touch snapshots. When a dependency bump changes the emitter format:
1. The snapshot tests will fail loudly on CI.
2. Fix is explicit: run `pytest --update-snapshots` (or a dedicated script) to regenerate.
3. Regenerated snapshots MUST be reviewed in PR as a first-class diff (not auto-accepted).
4. A bump that changes shape semantics (not just formatting) is a blocking PR — surface via the review.

Snapshots are stored non-canonicalized (emitter-native output). If non-determinism becomes an issue, switch to a canonicalizer (`json.dumps(schema, sort_keys=True, separators=(',', ':'))`) in a later PR; not v1 scope.

### 13.5 Acceptance gate

- All three directions of invariant hold on the stub.
- When plan #2 lands, stub is replaced with real type, test flips to true cross-type check.

### 13.6 Rollback

Delete the two new files. No runtime effect.

---

## 14. Testing summary

- Unit tests per sub-phase: ~210 total.
- Integration: load-save round-trip (C2), multi-process append (D), MCP smoke (G), 3-direction boundary (H).
- Multi-process test harness: `pytest-forked` or subprocess-based; required by sub-phase D.
- Fixtures: 10 markdown files, 2 FinancialModel snapshots (pre/post-expansion), plus test-user data dirs.

---

## 15. Rollout sequencing

**Week 1**: A (2 days) + H stub (1 day). Total 3.
**Week 2**: B (3 days) + C1 (3 days) in parallel. Plus E (2 days). Total 6.
**Week 3**: C2 (2 days) + D (1 day) + F (3 days). Total 6.
**Week 4**: G (3 days) + integration smoke (2 days). Total 5.

Total: **~20 working days with parallelism**.

Per-sub-phase acceptance gate: tests green at HEAD, committed independently. H test gates every subsequent PR.

---

## 16. Risks

| Risk | Mitigation |
|---|---|
| Markdown parser fragile under analyst edits | Constrained sections + hidden-ID carry-forward + semantic matcher fallback + positional unknown-section preservation + structured parse warnings (no silent loss). |
| Semantic matcher false positives (reuse wrong ID) | Conservative matcher per §4.2: role-scoped, field-aware, threshold ≥0.90 with ≥0.10 margin, one-to-one reservation, new UUID + warning on ambiguity. |
| Concurrent skill writes corrupt Decisions Log | fcntl file lock per (user_id, ticker, label); `entry_id` UNIQUE for idempotency; multiprocess test harness. |
| Shared-slice isomorphism drifts vs plan #2 | Stub composes from `schema/thesis_shared_slice.py`; plan #2 inherits the same module. Single source of truth. |
| ThesisLink resolution breaks under template changes | 5-anchor graceful degradation; `resolution_strength` + warnings surfaced in scorecard. |
| MCP tool surface wrong-located | R2 fix: tools in `risk_module/mcp_tools/thesis.py` matching existing research-MCP pattern. Gateway proxy via `actions/thesis.py`. |
| Per-user scoping regressions on concurrent users | Per-user SQLite + per-user workspace; no shared state. Tests exercise per-user isolation. |

---

## 17. Acceptance gate

- All 9 sub-phases committed, tests green.
- Boundary test H passes in all 3 directions.
- Round-trip test C1 passes on 10 fixtures.
- Multi-process concurrency test D passes.
- Smoke test: `/thesis-consultation` (once shipped in parallel AI-excel-addin work) creates + reads + updates a Thesis via MCP.
- `SKILL_CONTRACT_MAP.md` updated with **specific row/column edits** (R3 — closes Codex R2 should-fix):
  - **§"Primary reference: the investment schema" contracts table** (`SKILL_CONTRACT_MAP.md:61`):
    - Row "Thesis" → column "Location": change `schema/thesis.py (planned)` → `schema/thesis.py` (no "(planned)").
    - Row "Thesis" → column "Status" (if a status column is added): mark ✓ exists.
    - Row "ThesisLink + ThesisScorecard" → column "Location": change to `schema/thesis.py` (built). Drop "(planned)" suffix.
    - Row "HandoffArtifact v1.1" → no change (still planned — plan #2).
  - **§"Thesis lifecycle skills" table**: change Status column for 4 rows:
    - `/thesis-consultation`: ⦿ planned → ~ partial (Thesis contract side shipped; skill prompt authoring parallel work in AI-excel-addin).
    - `/thesis-review`: ⦿ planned → ~ partial (same rationale).
    - `/thesis-pre-mortem`: ⦿ planned → ~ partial (same rationale).
    - `/thesis-link`: ⦿ planned → ~ partial (same rationale; resolver shipped, link-creation skill prompt is parallel work).
  - **§"Analysis skills" table**: no row changes. These skills' migration to typed outputs is out of scope for plan #1.
  - **§"Integration patterns" table**: no changes. Patterns remain correct.
  - **§"Cross-repo references" table**: update `Thesis` types row to remove "(planned)" markers. Add row for `tests/schema/snapshots/thesis_v1_0.schema.json` as boundary-test snapshot location.

These edits must land in the same PR that ships sub-phase G (MCP tools), at which point all listed contract-side work is observable to Claude sessions reading the map.

---

## 18. Out of scope

- HandoffArtifact v1.1 (plan #2)
- ModelBuildContext (plan #3)
- Skill prompt authoring for the triad (parallel AI-excel-addin work)
- Frontend rendering of THESIS.md
- Migration of existing `notes/tickers/*.md` ticker memory
- Editorial research-report pipeline (plan #10 / G10)
- ProcessTemplate (plan #5)
- HandoffPatchOp apply semantics (plan #6)

---

## 19. Follow-on (post-plan-1)

- Plan #2 ships HandoffArtifact v1.1; replaces `_handoff_v1_1_stub.py` with real type; boundary test becomes true cross-type.
- Plan #3 (ModelBuildContext) consumes sub-phase E's resolver.
- Plan #6 (ModelInsights/PriceTarget/HandoffPatchOp) adds patch-op apply semantics; wires into Decisions Log append (patch_ops_applied field).
- Per-skill plans (thesis-consultation, thesis-review, thesis-link, thesis-pre-mortem) ship in parallel AI-excel-addin work using the Thesis MCP surface from plan #1.
