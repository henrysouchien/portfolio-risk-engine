# F124 — Thesis `monitoring.watch_list` Typing + `ownership` / `monitoring` Patch Ops + Producer Skills

**Status:** Completed 2026-05-23. Created 2026-05-20, rewritten 2026-05-22 (v20-v24 iterations) per user direction (no legacy/deprecation paths), implemented by AI-excel-addin `50e786c4` and risk_module `fcf1a727`.
**Closes:** Matrix gaps G5 (ownership) + G6 (monitoring.watch_list); layers doc D3.
**Unblocks:** F129 (monitoring/exit reassessment agent — needs typed reads on both fields).
**Verification:** 2026-05-23 focused AI-excel-addin F124 schema/patch/migration/integration tests passed 218/218; focused risk_module typed renderer test passed 36/36.
**Design inputs:**
- [`RESEARCH_ARTIFACT_LAYERS.md`](RESEARCH_ARTIFACT_LAYERS.md) §D3 (type both), §R11 (source conflict / dedup), §R12 (skill classification)
- [`THESIS_WRITE_SURFACE_COVERAGE.md`](THESIS_WRITE_SURFACE_COVERAGE.md) Stages G + K (industry / position / monitoring)
- [`F135_PREMISE_VERIFICATION_REPORT.md`](F135_PREMISE_VERIFICATION_REPORT.md) V1/V11 (patch engine pattern confirmed)
- `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` G9/G15 (the polymorphism this plan closes)

**Cross-repo touchpoints:**
- `AI-excel-addin/schema/thesis_shared_slice.py` — typed `WatchItem` + typed `Ownership` with R1; delete legacy classes/aliases
- `AI-excel-addin/schema/handoff_patch.py` — add `UpdateOwnershipOp` + `UpdateMonitoringOp` + `MonitoringWriteValue`
- `AI-excel-addin/api/research/patch_engine.py` — dispatch + apply functions + descriptor entries
- `AI-excel-addin/scripts/migrate_monitoring_ownership_v124.py` (new — §5.X migration script)
- `AI-excel-addin/api/memory/workspace/notes/skills/` — 2 new producer skills (`ownership-refresh.md`, `monitoring-init.md`)
- `risk_module/frontend/packages/ui/src/components/research/HandoffSectionRenderer.tsx` — typed-only renderer (no legacy branches)
- `fmp-mcp` already exposes `get_institutional_ownership` + `get_insider_trades` — read-side, no changes

---

## 1. Purpose & scope

### 1.1 In scope (v1) — FULL CUTOVER

**No legacy / deprecation paths.** v20 rewrite per user direction: typed-only writes, typed-only reads, no feature flags, no legacy compat shims. One-shot data migration converts all production rows; rollback is by deploy revert + DB restore.

1. **`Monitoring.watch_list: list[WatchItem]` — typed only.** No `str` arm, no `LegacyMonitoringWatchItemObject` arm, no polymorphism. Pre-migration data with legacy entries is converted by §5.X migration before the new code activates.
2. **Define typed `WatchItem`**: `{watch_item_id, description, metric, threshold, threshold_direction, last_checked, source_refs}` with `model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)`. Stable ID is **content-fingerprint deterministic** (see §4.3) so OCC retries are idempotent.
3. **`Ownership` — typed with R1 enforcement directly on the model.** No `Ownership` (read-permissive) / `OwnershipWriteValue` (write-strict) split. The single `Ownership` model has `_validate_evidence` `@model_validator(mode="after")` that enforces R1 unconditionally. Pre-migration `Ownership` rows with populated fields but empty `source_refs` are normalized by §5.X migration.
4. **Add `UpdateMonitoringOp` + `UpdateOwnershipOp` patch ops** in `handoff_patch.py` mirroring the `UpdateMacroOverlayOp` shape (single op replaces whole nested value).
5. **Op-level evidence validators.** `UpdateOwnershipOp.value: Ownership` — `Ownership._validate_evidence` runs at op construction (no read/write split). `UpdateMonitoringOp.value: MonitoringWriteValue` — write-only Pydantic model with `watch_list: list[WatchItem]` (typed-only; defense in depth — schema also rejects polymorphism post-migration). Each `WatchItem.source_refs: list[SourceId] = Field(min_length=1)` enforces R1 at item level. Patch engine calls `_validate_source_refs_resolve` to verify `src_N` references resolve against `Thesis.sources[]`, wrapping dangling refs as `InvalidTargetError`.
6. **Two specific apply functions** in `patch_engine.py`: `_apply_ownership_patch` and `_apply_monitoring_patch`. No generic `_apply_top_level_patch` helper.
7. **No feature flags.** New ops apply unconditionally once landed. Staged rollout is at the deploy layer (canary deploy → full deploy), not in code. Removed: `OWNERSHIP_REFRESH_ENABLED`, `MONITORING_V1_3_ENABLED`.
8. **Two producer skills (per R12 `producer` classification):**
   - `ownership-refresh.md` — consumes `fmp-mcp.get_institutional_ownership` + `get_insider_trades`, emits one `register_sources` + one `update_ownership` op.
   - `monitoring-init.md` — derives `WatchItem` candidates only from near-term `Thesis.catalysts[]` (catalysts have `source_ref`; `InvalidationTrigger` schema has no `source_refs` field so triggers are out of scope — see §5.F + §7.1.4). Reuses existing catalyst `source_ref` values; does NOT call `register_sources`. Emits `update_monitoring` plus zero-or-more `add_data_gap` ops (one per skipped catalyst).
9. **One-shot data migration script (§5.X).** Walks all production `theses` + `research_handoffs` rows; converts legacy `MonitoringWatchItemObject` entries with source_refs to typed `WatchItem`; drops legacy `str` watch entries (no source citation → not migratable under R1); normalizes/backfills `Ownership` rows with populated fields but empty `source_refs`. Fails loudly on un-migratable rows so no silent data loss. Runs in PR 3 deploy step BEFORE new code activates. Dry-run mode validates first.
10. **Frontend renderer (risk_module)** — single typed-WatchItem path. No legacy branches. Post-migration there are no legacy entries to render.
11. **Test matrix** — typed write path, content-fingerprint OCC retry stability, source-ref rewrite-before-validation, dangling-source-ref rejection, descriptor conflict detection within batch, duplicate fingerprint collisions, generated-vs-caller ID collision, source-ref resolution wrap as `InvalidTargetError`, migration round-trip (pre-migration legacy → post-migration typed), build_model unaffected.

### 1.2 Out of scope (v1)

- **R6 cross-type validation** (claim + same-target `data_gap` pair forbidden, per layers doc R6). F124 declares `WatchItem` subject to R6 but the cross-type audit validator lands with **F125 (W2 audit backbone)**. F124's per-op validators only enforce R1 (non-empty source_refs).
- **`add_watch_item` / `remove_watch_item` granular patch ops.** F124 ships only `update_monitoring` (full replace). Granular ops added later if F129 monitoring agent shows churn on individual items.
- **`update_ownership` fine-grained variants** (e.g., `update_institutional_pct`). Full-replace via `update_ownership` is sufficient.
- **Monitoring agent driving the watch list** — F129, gated on F124.
- **InvalidationTrigger source_refs schema** — separate workstream, see §7.1.4.

### 1.3 Non-goals

- New typed slots beyond what's already in `Ownership` / `Monitoring`. No expanding scope into adjacent fields.
- Touching `peers[]` legacy deprecation — that's F130.

---

## 2. Sub-phase summary

| # | Sub-phase | Scope | Duration | Depends on |
|---|---|---|---|---|
| A | Schema (`thesis_shared_slice.py`) — typed `WatchItem` + typed `Ownership` with R1 model_validator; **delete** `LegacyMonitoringWatchItemObject`, `MonitoringWatchItemObject` alias, three-way union, `OwnershipWriteValue` | ~1 day | — |
| B | Patch ops: `UpdateOwnershipOp` + `UpdateMonitoringOp` | Add op classes to `handoff_patch.py` + Union + `__all__`; add `MonitoringWriteValue` value model; re-export in `schema/__init__.py` | ~0.5 day | A |
| C | Apply functions + dispatch (no flags) | New `_apply_monitoring_patch`, `_apply_ownership_patch`; dispatch entries in `_apply_op_to_virtual` + `_describe_op` for `_dry_fold_detailed` parity | ~1 day | A, B |
| D | Patch engine tests | Unit tests for both ops: happy path, schema validation rejection, idempotent replay, dup-ID collision, source-ref resolution, fingerprint stability | ~1 day | C |
| E | `ownership-refresh` producer skill | Skill prose + `producer` classification + dispatch shape test | ~1 day | C |
| F | `monitoring-init` producer skill | Skill prose + `producer` classification + dispatch shape test; reads from Thesis catalysts only (triggers unsourced per §7.1.4) | ~1 day | C |
| G | Frontend renderer (risk_module) — typed-only, no legacy branches | `HandoffSectionRenderer.tsx` typed-shape rendering; visual snapshot tests | ~0.5 day | A |
| H | Integration test (end-to-end against post-migration data) | Producer skill smoke against real FMP data; finalize + re-derive; build_model unaffected | ~1 day | C, E, F, G |
| X | One-shot data migration script (`scripts/migrate_monitoring_ownership_v124.py`) — walks production `theses` + `research_handoffs`; converts legacy entries; dry-run + live modes; pre-migration audit + post-migration verification | ~1.5 days | A, B (schema must be defined to validate post-migration shape) |

**Total:** ~8.5 working days. Parallelism: E/F/G/X can run alongside D after C. PR 3 deploys migration first, then activates new code.

---

## 3. Dependency graph

```
A (schema tightening)
  ├── B (patch op definitions)
  │     └── C (apply + dispatch — no flags)
  │           ├── D (patch engine tests)
  │           ├── E (ownership-refresh skill)
  │           ├── F (monitoring-init skill)
  │           └── H (integration test)
  └── G (frontend renderer — typed-aware read)
```

**Hard prereqs (external):** None. F135 (premise verification) confirmed the patch engine + schema patterns referenced here are accurate.

---

## 4. Cross-cutting concerns

### 4.1 Full-cutover rollout (no feature flags, no sunset)

**No feature flags.** New ops apply unconditionally once landed. The user has explicitly directed: no legacy / deprecation paths. Staged rollout happens at the deploy layer (canary → full), not in code.

**Deploy sequence:**
1. **PR 1** lands schema + patch ops + apply functions + producer skills + tests. Tests pass against current production data because §5.X migration runs first in PR 3.
2. **PR 2** lands frontend renderer (typed-only) + visual snapshot tests.
3. **PR 3** is deploy-only — runs §5.X migration script in dry-run mode first (validates all rows are migratable), then live (rewrites production data). After migration succeeds, the new code activates against fully-migrated data.

**Rollback:** Deploy revert + DB restore from pre-migration snapshot. There is no "soft rollback" via feature flag toggle. Acceptance is "the migration is correct and we trust it"; otherwise we don't deploy.

**Pre-cutover audit — quick magnitude check (before PR 3):**

The migration script (§5.X) does comprehensive per-category accounting in dry-run mode (recommended for full ops review). These SQL queries are the cheap pre-flight check — if counts are zero or near-zero, cutover is low-risk; if non-trivial, run §5.X dry-run for detailed category breakdown before scheduling the read-only window.

```sql
-- Quick magnitude: malformed watch_list (non-array) — guard before iterating.
SELECT COUNT(*) AS malformed_watch_list_count
FROM theses
WHERE artifact -> 'monitoring' -> 'watch_list' IS NOT NULL
  AND jsonb_typeof(artifact -> 'monitoring' -> 'watch_list') <> 'array';

-- Quick magnitude: malformed ownership.source_refs (non-array) — guard the array_length check below (v23-P3 fix).
SELECT COUNT(*) AS malformed_ownership_source_refs_count
FROM theses
WHERE artifact -> 'ownership' -> 'source_refs' IS NOT NULL
  AND jsonb_typeof(artifact -> 'ownership' -> 'source_refs') <> 'array';

-- Quick magnitude: legacy str watch entries (will be dropped). Array-guarded.
SELECT COUNT(*) AS legacy_str_count
FROM (
  SELECT jsonb_array_elements(artifact -> 'monitoring' -> 'watch_list') AS elem
  FROM theses
  WHERE jsonb_typeof(artifact -> 'monitoring' -> 'watch_list') = 'array'
) AS entries WHERE jsonb_typeof(elem) = 'string';

-- Quick magnitude: ownership with populated content but no source_refs (will be nulled).
-- Use a CTE to materialize the array-or-null filter before calling jsonb_array_length
-- (v24-P2.A fix — Postgres can reorder WHERE conditions, so even with the type
-- guard in the same clause, jsonb_array_length on a non-array value may execute
-- and throw; CTE forces evaluation order).
WITH filtered AS MATERIALIZED (
  SELECT artifact
  FROM theses
  WHERE artifact -> 'ownership' IS NOT NULL
    AND (artifact -> 'ownership' ->> 'institutional_pct' IS NOT NULL
         OR artifact -> 'ownership' ->> 'insider_pct' IS NOT NULL
         OR artifact -> 'ownership' ->> 'recent_activity' IS NOT NULL)
    AND (
      artifact -> 'ownership' -> 'source_refs' IS NULL
      OR jsonb_typeof(artifact -> 'ownership' -> 'source_refs') = 'array'
    )
)
SELECT COUNT(*) AS ownership_unsourced_count
FROM filtered
WHERE jsonb_array_length(COALESCE(artifact -> 'ownership' -> 'source_refs', '[]'::jsonb)) = 0;
```

Same queries against `research_handoffs.artifact`. If non-trivial, run `python scripts/migrate_monitoring_ownership_v124.py --dry-run` for the full per-category breakdown (object-unsourced drops, extras drops, direction coercions, dangling source_refs, malformed shapes) — see §5.X. Then surface results to user before scheduling cutover.

### 4.2 Source linkage per R1 + R11

`update_ownership` follows R1 via `Ownership._validate_evidence` model_validator (single typed model post-cutover; no read/write split — see §5.A): any populated pct/activity field requires non-empty `source_refs`. `update_monitoring` follows R1 at the `WatchItem` level: each typed `WatchItem` has `source_refs: list[SourceId] = Field(min_length=1)`. Per-op patch engine validator additionally calls `_validate_source_refs_resolve` (V4) to confirm `src_N` references resolve against `Thesis.sources[]`, wrapping dangling refs as `InvalidTargetError`.

R11 source identity is unaffected — `update_ownership` may emit alongside `register_sources` in the same batch; `update_monitoring` reuses existing source_refs and does not register new ones (P2.9).

### 4.3 Stable IDs via canonical-JSON content fingerprint (v3-P1 fix)

`WatchItem.watch_item_id: str | None = None` is allocated **deterministically via canonical JSON content fingerprint** inside the patch apply function, AFTER canonical source-ref rewrite. F-string fingerprints are unsafe across `int`/`float`/`Decimal` representations and dict-vs-object thresholds — canonical JSON via Pydantic `model_dump(mode="json")` + sorted keys + compact separators + Unicode NFC is the only robust form:

```python
import hashlib, json, unicodedata

_FINGERPRINT_FIELDS = ("description", "metric", "threshold", "threshold_direction")

def _canonicalize_threshold(value: object) -> object:
    """Normalize numeric thresholds so 1 and 1.0 produce the same fingerprint.
    Strings stay strings (semantic levels like 'low'/'medium'/'high')."""
    if isinstance(value, bool):
        return value  # bool is subclass of int but semantically distinct
    if isinstance(value, (int, float)):
        return repr(float(value))  # float repr stable for finite values
    return value


def _allocate_watch_item_id(item: WatchItem, ticker: str) -> str:
    if item.watch_item_id:
        return item.watch_item_id  # caller-provided; dispatch handles dedup (see §5.C)
    canonical = item.model_dump(mode="json", include=set(_FINGERPRINT_FIELDS), exclude_none=False)
    # Threshold canonicalization (v6-P2 fix): int 1 and float 1.0 must hash identically.
    if "threshold" in canonical:
        canonical["threshold"] = _canonicalize_threshold(canonical["threshold"])
    # NFC-normalize string fields BEFORE json.dumps so composed/decomposed Unicode
    # collapses to the same canonical form. Doing NFC AFTER json.dumps with
    # ensure_ascii=True would be a bug — \\u escapes would be ASCII no-ops.
    normalized_fields: dict[str, object] = {"ticker": unicodedata.normalize("NFC", ticker.strip().upper())}
    for key, value in canonical.items():
        normalized_fields[key] = (
            unicodedata.normalize("NFC", value) if isinstance(value, str) else value
        )
    payload = json.dumps(
        normalized_fields,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,  # preserve already-NFC-normalized Unicode in the hash input
    )
    return f"watch_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"
```

**Roundtrip-stability tests (§5.D additions):**
- **Threshold canonicalization (v6-P2 fix):** `ThresholdValue: TypeAlias = str | int | float` does NOT auto-normalize int vs float in Pydantic JSON mode. Fingerprint canonicalizes numeric thresholds via `repr(float(value))` if `isinstance(value, (int, float)) and not isinstance(value, bool)`; str passes through unchanged. Apply inside `_allocate_watch_item_id` after `model_dump(...)` and before NFC normalization.
- `threshold=1` vs `threshold=1.0` produce same fingerprint (both canonicalized to `"1.0"`).
- `threshold=1` vs `threshold="1"` produce DIFFERENT fingerprints (int vs str semantically distinct — caller chose representation).
- `threshold="low"` vs `threshold="medium"` produce different fingerprints (string semantic levels).
- `model_dump_json()` → reload → re-fingerprint == original fingerprint.
- Ticker `"PCTY"` vs `"pcty"` produces the same fingerprint (normalization via `.strip().upper()`).
- `description="café"` (composed) vs `"café"` (decomposed) produce same fingerprint via NFC normalization.

**OCC retry safety:** same logical watch_item → same canonical payload → same fingerprint → same ID. The submitted op is not mutated; allocation happens on a local copy via `item.model_copy(update={"watch_item_id": ...})`.

**Hash collisions** are extremely unlikely with 12-hex SHA-256: the ID namespace is 16^12 = ~2.8 × 10^14 values, and the birthday-collision threshold is ~16M IDs (~2^24 = sqrt of 2^48). For our scale (single-digit watch_items per Thesis × low-thousands of Thesis rows), the probability is effectively zero. If they occur, a `_NN` suffix is appended in batch apply (covered by §5.D test).

Mirrors the `risk_id` / `catalyst_id` content-stable pattern from HandoffArtifact v1.1 plan §5.

### 4.4 Producer skill classification (R12)

Both new skills declare `classification: producer` in frontmatter (per F130 work).
- `ownership-refresh`: emits `register_sources` + `update_ownership` + `decisions_log` entry.
- `monitoring-init`: emits `update_monitoring` plus zero-or-more `add_data_gap` ops (one per skipped catalyst) plus `decisions_log` entry — **reuses existing Thesis.sources[] entries**, does NOT call `register_sources` (P2.9 fix; v10 partial-path clarification).

Both eligible for autonomous-scheduled execution (F129 monitoring agent will dispatch `ownership-refresh` on cadence).

### 4.5 R6 deferral

`WatchItem` is a positive analytical claim and is subject to layers doc R6 (claim + same-target data_gap pair forbidden). F124 declares this in skill prose ("a watch_item and a same-target data_gap MUST NOT be emitted in the same producer-skill output"), but **does not implement cross-type validation**. The validator that enforces R6 across all Thesis mutation paths lands with **F125 (W2 audit backbone)**. F124-only enforcement: per-op `source_refs: Field(min_length=1)` (R1 floor; insufficient for R6 but a precondition).

### 4.6 Cross-repo coordination

Changes split: AI-excel-addin owns schema/patch ops/skills; risk_module owns frontend renderer. **Frontend decoupled from `@risk/connectors` for v1** (P2.7 fix):
- Sub-phase G uses local structural TS type defined inside the risk_module frontend (interface mirrors WatchItem fields). Avoids npm sync timing dependency.
- Once AI-excel-addin → web-app-platform sync ships the connector type, frontend can refactor to import the typed shape directly. That's a follow-up, not gating.

PR sequence:
- **PR 1 (AI-excel-addin):** sub-phases A-F, H, X (schema + patch ops + apply + skills + tests + migration script). Tests run against post-migration shape.
- **PR 2 (risk_module):** sub-phase G + H-client. **Uses local TS interface defined in `frontend/packages/ui/src/components/research/_watchItemTypes.ts`** — no `@risk/connectors` import. Independent of PR 1 npm publication; can merge before, after, or simultaneously. Any future refactor to consume `@risk/connectors` is a separate PR with explicit grep proof of zero local-type callers remaining.
- **PR 3 (deploy):** §5.X migration dry-run → live → activate new code. See §6 for detailed step-by-step.

---

## 5. Detailed sub-phases

### 5.A — Schema (`thesis_shared_slice.py`) — full cutover, typed-only

**Changes:**

```python
class WatchItem(BaseModel):
    """Typed watch list entry. Subject to R1 + R6 (R6 enforcement deferred to F125
    audit validator)."""
    watch_item_id: str | None = None
    description: str = Field(min_length=1)
    metric: str | None = None
    threshold: ThresholdValue | None = None
    threshold_direction: Literal["above", "below"] | None = None
    last_checked: str | None = None
    source_refs: list[SourceId] = Field(min_length=1)  # R1: positive claim requires evidence

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    @field_validator("watch_item_id", mode="before")
    @classmethod
    def _normalize_watch_item_id(cls, value: object | None) -> str | None:
        return _normalize_optional_identifier(value)


class Monitoring(_ContractModel):
    """Typed-only. No polymorphism. Pre-cutover data is migrated by §5.X before
    this code activates."""
    watch_list: list[WatchItem] = Field(default_factory=list)
    source_refs: list[SourceId] = Field(default_factory=list)


class Ownership(_ContractModel):
    """Typed ownership with R1 enforcement directly. No read/write split — all
    callers (reads and writes) go through this model. Pre-cutover rows with
    populated fields but empty source_refs are normalized by §5.X migration
    BEFORE this code activates, so the validator never sees pre-cutover data."""
    institutional_pct: float | None = None
    insider_pct: float | None = None
    recent_activity: str | None = None
    source_refs: list[SourceId] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_evidence(self) -> "Ownership":
        """R1: any populated content requires non-empty source_refs."""
        has_content = (
            self.institutional_pct is not None
            or self.insider_pct is not None
            or (self.recent_activity is not None and self.recent_activity.strip())
        )
        if has_content and not self.source_refs:
            raise ValueError("Ownership with populated fields requires non-empty source_refs (R1)")
        return self
```

**Removed (full cutover):** `LegacyMonitoringWatchItemObject` class, the `MonitoringWatchItem: TypeAlias = str | WatchItem | LegacyMonitoringWatchItemObject` three-way union, the `MonitoringWatchItemObject = LegacyMonitoringWatchItemObject` alias, the `Ownership` (permissive) / `OwnershipWriteValue` (strict) split. All gone.

**Removed-legacy verification grep (v20-P2.C — broaden):** before PR 1 lands, grep both repos for ALL deleted symbols and resolve any remaining references:
```bash
# Run in both AI-excel-addin and risk_module
for term in MonitoringWatchItemObject LegacyMonitoringWatchItemObject MonitoringWatchItem OwnershipWriteValue OWNERSHIP_REFRESH_ENABLED MONITORING_V1_3_ENABLED is_monitoring_v1_3_enabled is_ownership_refresh_enabled require_monitoring_v1_3_enabled require_ownership_refresh_enabled; do
  echo "=== $term ==="
  rg -n "$term" .
done
```
Expected post-cleanup: zero hits in non-archival, non-historical-changelog locations. Document any remaining call-site changes in PR description.

**Audit other modules for legacy watch_list assumptions (v20-P2.C):**
- `AI-excel-addin/api/research/handoff.py` `_assemble_artifact_locked` (around line 449) — confirm it doesn't special-case polymorphic watch_list shapes.
- `AI-excel-addin/schema/thesis_markdown.py` — markdown serializer/parser may have special-case handling for legacy str watch entries. Audit + remove.
- `AI-excel-addin/api/research/editorial/*` — any renderer that touches monitoring should be checked.
- `frontend/packages/ui/src/components/research/HandoffSectionRenderer.tsx` — see §5.G existing-code cleanup callout.

**Acceptance:**
- New tests: `WatchItem` Pydantic round-trip; `description` empty rejection; `source_refs` empty rejection per R1; `watch_item_id` normalization; `Ownership._validate_evidence` rejection when content populated without source_refs.
- `Monitoring.model_validate({"watch_list": ["legacy str"]})` raises `ValidationError` (no `str` arm in the typed list).
- `Monitoring.model_validate({"watch_list": [{"description": "x", "extras": "old"}]})` raises `ValidationError` (no `extra="allow"` shape).
- Migration tests in §5.X verify pre-cutover legacy data is rewritten correctly.

### 5.B — Patch ops (`handoff_patch.py`)

```python
class MonitoringWriteValue(BaseModel):
    """UpdateMonitoringOp value shape. Same Pydantic shape as Monitoring
    (typed-only post-cutover); kept as a separate model only to add the
    cross-item _no_duplicate_caller_ids validator at op-construction."""
    watch_list: list[WatchItem] = Field(default_factory=list)
    source_refs: list[SourceId] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    @model_validator(mode="after")
    def _no_duplicate_caller_ids(self) -> "MonitoringWriteValue":
        """Reject duplicate caller-provided watch_item_id at Pydantic validation,
        before reaching patch engine. Earlier rejection than apply-time."""
        provided_ids: list[str] = [w.watch_item_id for w in self.watch_list if w.watch_item_id]
        if len(provided_ids) != len(set(provided_ids)):
            raise ValueError(
                f"MonitoringWriteValue.watch_list has duplicate caller-provided "
                f"watch_item_id(s): {[i for i in provided_ids if provided_ids.count(i) > 1]}"
            )
        return self


class UpdateMonitoringOp(_PatchOpBase):
    op: Literal["update_monitoring"] = "update_monitoring"
    target: None = None
    value: MonitoringWriteValue


class UpdateOwnershipOp(_PatchOpBase):
    op: Literal["update_ownership"] = "update_ownership"
    target: None = None
    value: Ownership  # Single typed model — R1 enforced via Ownership._validate_evidence.
```

Add both to `HandoffPatchOp` Annotated[Union[...], Field(discriminator="op")] tag union + `__all__` exports in `handoff_patch.py`.

**Public API re-exports in `schema/__init__.py`.** `schema/__init__.py` maintains an explicit `__all__` + named imports for downstream callers (`from schema import ...`); new symbols must be added:
```python
from .thesis_shared_slice import (
    # ...existing names...
    WatchItem,
)
from .handoff_patch import (
    # ...existing names...
    UpdateOwnershipOp,
    UpdateMonitoringOp,
    MonitoringWriteValue,
)
```
Add each name to `__all__`. Verify with `python -c "from schema import WatchItem, UpdateMonitoringOp"` post-merge.

**Acceptance:**
- Discriminated-union dispatch resolves both ops by `op` literal.
- `UpdateOwnershipOp.value: Ownership` rejects populated-without-source_refs at op-validation time via `Ownership._validate_evidence`.
- `UpdateMonitoringOp.value: MonitoringWriteValue` rejects non-`WatchItem` entries at op-validation time — Pydantic rejects the construction before any apply runs (the schema doesn't model any non-typed shapes post-cutover).
- Test that `UpdateMonitoringOp(value=MonitoringWriteValue(watch_list=["str"]))` raises `ValidationError` at construction.

### 5.C — Apply + dispatch (`patch_engine.py`) — no feature flags

**Two specific apply functions, NO generic helper.** No feature flag gating (v20 cutover). Add the new ops' imports + dispatch entries:

```python
# Add to top of patch_engine.py
from research.handoff import (
    _known_source_ids_from_sources,
    _validate_source_refs_resolve,
)


def _apply_ownership_patch(
    payload: dict[str, Any],
    op: UpdateOwnershipOp,
) -> Thesis:
    """Replace Thesis.ownership with the validated new value.
    R1 enforcement happens at Ownership._validate_evidence (model_validator on
    the single typed Ownership model — see §5.A; no read/write split post-cutover).
    Source-ref resolution checked explicitly because _validate_thesis_payload
    only Pydantic-validates; doesn't verify src_N references resolve."""
    payload["ownership"] = op.value.model_dump(mode="json")
    known_ids = _known_source_ids_from_sources(payload.get("sources") or [])
    try:
        _validate_source_refs_resolve(payload["ownership"], known_source_ids=known_ids)
    except ValueError as exc:
        raise InvalidTargetError(op_id=op.op_id, reason=str(exc)) from exc
    return _validate_thesis_payload(payload, op)


def _apply_monitoring_patch(
    payload: dict[str, Any],
    op: UpdateMonitoringOp,
    *,
    ticker: str,
) -> Thesis:
    """Replace Thesis.monitoring with the validated typed-only new value.
    Post-cutover, schema-level Monitoring is already typed-only; pre-migration
    legacy data does not exist at apply time (§5.X migration ran first).

    Allocates deterministic watch_item_id (content fingerprint) for any
    WatchItem missing one. Rejects duplicate caller-provided IDs explicitly.
    Mutates a local copy of value, not the op."""
    write_value = op.value.model_copy(deep=True)
    new_watch_list: list[WatchItem] = []
    # Precompute caller-provided IDs in a first pass so collision detection
    # is order-independent (v16-P1 fix). Without this, a caller-provided
    # `watch_X` appearing BEFORE a no-ID item whose fingerprint is also
    # `watch_X` would silently suffix-the-later one instead of raising.
    caller_provided_ids: set[str] = {
        w.watch_item_id for w in write_value.watch_list if w.watch_item_id
    }
    seen_ids: set[str] = set(caller_provided_ids)
    for item in write_value.watch_list:
        # MonitoringWriteValue.watch_list is typed-only; isinstance check redundant
        # but kept as defensive assertion.
        assert isinstance(item, WatchItem), "MonitoringWriteValue invariant violated"
        if item.watch_item_id:
            # Caller-provided ID. Note seen_ids was prepopulated with ALL caller
            # IDs in the precompute step, so we check against the original
            # caller-ID set minus what we've already consumed (to detect dup
            # caller IDs) rather than re-adding here. But MonitoringWriteValue
            # validator already rejects dup caller IDs at construction, so
            # this branch only handles the no-collision case.
            assert item.watch_item_id in seen_ids, (
                "invariant: caller_provided_ids precompute should have populated seen_ids"
            )
            new_watch_list.append(item)
            continue
        # Allocate deterministic fingerprint ID. Note seen_ids already contains
        # all caller-provided IDs (precomputed), so a generated fingerprint
        # colliding with ANY caller ID is detected via the collision path below.
        base_id = _allocate_watch_item_id(item, ticker)
        if base_id in caller_provided_ids:
            # Generated fingerprint matches a caller-provided ID — order-independent
            # collision (v16-P1 fix). Raise typed error so dispatch surfaces it as
            # a conflict via _dry_fold_detailed (v17-P1 signature fix: actual
            # DuplicateStableIdError ctor takes stable_id, target_collection, op_id).
            raise DuplicateStableIdError(
                stable_id=base_id,
                target_collection="monitoring.watch_list",
                op_id=op.op_id,
            )
        # Hash-collision suffix (extremely rare; only fires between two generated IDs).
        candidate = base_id
        suffix = 0
        while candidate in seen_ids:
            suffix += 1
            candidate = f"{base_id}_{suffix:02d}"
        seen_ids.add(candidate)
        new_watch_list.append(item.model_copy(update={"watch_item_id": candidate}))
    write_value = write_value.model_copy(update={"watch_list": new_watch_list})
    # Persist as Monitoring read shape (watch_list field names match).
    payload["monitoring"] = {
        "watch_list": [w.model_dump(mode="json") for w in new_watch_list],
        "source_refs": list(write_value.source_refs),
    }
    # Source-ref resolution check (v7-P1 fix — same reason as ownership above).
    known_ids = _known_source_ids_from_sources(payload.get("sources") or [])
    # Same wrap as ownership (v12-P2 fix).
    try:
        _validate_source_refs_resolve(payload["monitoring"], known_source_ids=known_ids)
    except ValueError as exc:
        raise InvalidTargetError(op_id=op.op_id, reason=str(exc)) from exc
    return _validate_thesis_payload(payload, op)
```

Dispatch additions in `_apply_op_to_virtual` (alongside line 607-624 industry block) — no flag gating:
```python
if isinstance(op, UpdateOwnershipOp):
    return _apply_ownership_patch(payload, op)
if isinstance(op, UpdateMonitoringOp):
    return _apply_monitoring_patch(payload, op, ticker=thesis.ticker)
```

**`_describe_op` descriptor entries (v7-P1 fix).** Apply flow calls `_describe_op(op)` at `patch_engine.py:318` BEFORE dispatch. `_dry_fold_detailed` only tracks `"add"` / `"update"` / `"remove"` kinds for OCC conflict detection — `"replace"` would not collide. Mirror the existing top-level-singleton pattern from `UpdateConsensusViewOp` / `UpdatePortfolioFitOp` / `UpdateMacroOverlayOp` exactly: use `"update"` with `_SINGLETON_TARGET` and field-level value tuples:

```python
# Inside _describe_op() — patch_engine.py around line 1019 (alongside UpdatePortfolioFitOp)
if isinstance(op, UpdateOwnershipOp):
    return _OpDescriptor(
        "update",
        "ownership",
        _SINGLETON_TARGET,
        [
            ((field_name,), field_value)
            for field_name, field_value in op.value.model_dump(
                mode="json", exclude_none=False  # v14-P1: include None so disjoint full-replaces collide on the singleton target
            ).items()
        ],
    )
if isinstance(op, UpdateMonitoringOp):
    return _OpDescriptor(
        "update",
        "monitoring",
        _SINGLETON_TARGET,
        [
            ((field_name,), field_value)
            for field_name, field_value in op.value.model_dump(
                mode="json", exclude_none=False  # v14-P1: include None so disjoint full-replaces collide on the singleton target
            ).items()
        ],
    )
```

`"update"` kind matches the conflict-detection vocabulary already in `_dry_fold_detailed`. `_SINGLETON_TARGET` mirrors `consensus_view` / `portfolio_fit` / `macro_overlay` (top-level non-list fields). Field-level value tuples enable the existing divergent-update conflict check to fire when two concurrent ops touch overlapping fields.

**Acceptance:** `_describe_op(UpdateOwnershipOp(value=Ownership(institutional_pct=0.42, source_refs=["src_1"])))` returns `_OpDescriptor(kind="update", collection="ownership", stable_id=_SINGLETON_TARGET, field_updates=[(("institutional_pct",), 0.42), (("source_refs",), ["src_1"])])`. Test in §5.D verifies descriptor lookup AND that two `update_ownership` ops in the same batch touching `institutional_pct` trigger `_divergent_update_conflict` (existing `_dry_fold_detailed` mechanism — within-batch only; cross-session OCC out of scope).

**Required imports for the new apply functions** (v18-P1 fix — `_known_source_ids_from_sources` + `_validate_source_refs_resolve` currently live in `research.handoff`, not `patch_engine`):
```python
# Add to top of patch_engine.py
from research.handoff import (
    _known_source_ids_from_sources,
    _validate_source_refs_resolve,
)
```

**Order of operations within a batch (per P2.10 missing test):**
`register_sources` runs first (already enforced via existing single-register-per-batch lock per V1). `_rewrite_op_source_refs` rewrites `src_N` mappings on all subsequent ops (V11) — including ops carrying `Ownership` / `MonitoringWriteValue` values. THEN `_apply_ownership_patch` / `_apply_monitoring_patch` run with canonical IDs. This means `Ownership._validate_evidence` runs at op-construction time (BEFORE rewrite, on caller's predicted IDs) AND `_validate_source_refs_resolve` runs at apply time (AFTER rewrite, on canonical IDs). Both checks reinforce R1: empty source_refs blocked at construction, dangling source_refs blocked at apply.

`_dry_fold_detailed` mirrors the same dispatch (used for preview / OCC validation).

**Acceptance:**
- No flag gating: ops apply unconditionally post-merge (full-cutover model).
- Full Thesis re-validates via `_validate_thesis_payload`; source_refs resolution via `iter_source_refs` per V4.
- OCC retry: same logical WatchItem yields same fingerprint ID across replays (test in §5.D).
- Op is not mutated; ID allocation happens on a local copy.

### 5.D — Patch engine tests (`tests/api/research/test_patch_engine.py` + `tests/research/`)

**Expanded matrix (P2.10 + P3 fixes):**

*Schema-level (`tests/schema/test_handoff_patch.py`):*
- `WatchItem(description="")` rejected by Pydantic `min_length=1`.
- `WatchItem(description="x", source_refs=[])` rejected by Pydantic `Field(min_length=1)` (R1 floor).
- `Ownership(institutional_pct=0.5)` (no source_refs) rejected by `_validate_evidence` model_validator (R1 enforcement on the single typed model).
- `Ownership(institutional_pct=None, insider_pct=None, recent_activity=None, source_refs=[])` (fully empty) accepted — no populated content means R1 has nothing to enforce.
- `Monitoring.model_validate({"watch_list": ["legacy str"]})` raises ValidationError (no `str` arm).
- `Monitoring.model_validate({"watch_list": [{"description": "x", "extras": "old"}]})` raises ValidationError (no `extra="allow"` shape).

*Patch engine apply (`tests/api/research/test_patch_engine.py`):*
- **Happy ownership:** `register_sources` + `update_ownership` in one batch — sources register first, ownership.source_refs reference rewritten canonical IDs.
- **Happy monitoring:** `update_monitoring` with 2 typed WatchItem (no caller-provided IDs) → both get content-fingerprint IDs.
- **Source rewrite before validation order:** `update_monitoring.value.watch_list[0].source_refs = ["src_99"]` (caller's predicted ID) + `register_sources` with a `SourceRecord(id="src_99", …)` that identity-hash-dedupes to existing `src_5` — `_rewrite_source_refs_recursive` rewrites the watch_list's `src_99` → `src_5` BEFORE `_validate_thesis_payload` runs. Placeholder uses valid `^src_[1-9]\d*$` format per `SourceId` regex.
- **Removed:** feature-flag-OFF rejection tests (no flags exist post-cutover).
- **Typed-only enforcement at op construction:** `UpdateMonitoringOp(value=MonitoringWriteValue(watch_list=["legacy str"]))` raises `ValidationError` at Pydantic-validation time. Same for any non-WatchItem entry (schema doesn't model legacy shapes post-cutover).
- **Duplicate caller-provided IDs rejected at construction (v4 fix):** `MonitoringWriteValue(watch_list=[WatchItem(watch_item_id="x", description="a", source_refs=["src_1"]), WatchItem(watch_item_id="x", description="b", source_refs=["src_1"])])` raises Pydantic `ValidationError` at model construction via the `_no_duplicate_caller_ids` model_validator (see §5.B). Apply-time duplicate check in `_apply_monitoring_patch` is defensive and unreachable for valid `MonitoringWriteValue` instances.
- **Generated-then-caller ID collision rejected (v14-P1 + v15-P1 + v17-P1 fix):** `MonitoringWriteValue(watch_list=[WatchItem(description="x", source_refs=["src_1"]), WatchItem(watch_item_id="watch_<fingerprint_of_first>", description="y", source_refs=["src_2"])])` — first item has no ID, gets fingerprint `watch_X`; second item is caller-provided with same `watch_X` literal. `_apply_monitoring_patch` raises `DuplicateStableIdError(stable_id="watch_X", target_collection="monitoring.watch_list", op_id=op.op_id)` — typed error so `_dry_fold_detailed` surfaces it as a conflict, not raw `ValueError`. Construct the test using a known fingerprint (compute it once, hardcode the collision) and assert preview/apply returns the conflict.
- **Idempotent replay:** same op applied twice = same Thesis state (typed equality on Monitoring/Ownership).
- **OCC retry ID stability:** same `WatchItem(description="X", metric="Y")` applied twice through retry → same `watch_item_id`. Op not mutated between attempts.
- **Duplicate fingerprint collision:** two `WatchItem`s with identical content in one batch → second gets `_01` suffix; both end up in `watch_list`.
- **`_dry_fold_detailed` parity:** preview yields the same Thesis state as apply for identical batches (covers both new ops).
- **Same-batch full-replace conflict:** two `update_monitoring` ops in the **same batch** touching overlapping fields → `_dry_fold_detailed` returns `_divergent_update_conflict` per existing mechanism. Cross-session stale-replace is NOT F124 scope (existing top-level full-replace ops have the same property; uniformly fixed by a separate workstream if it becomes a problem).
- **Empty source_refs at op level:** `UpdateMonitoringOp(value=MonitoringWriteValue(watch_list=[WatchItem(description="x", source_refs=[])]))` rejected at Pydantic op-validation by `WatchItem.source_refs: Field(min_length=1)` (R1 floor).
- **Migration test:** pre-cutover Thesis with `watch_list: ["legacy str", {"description": "x", "extras": "old"}]` → §5.X migration script normalizes/drops entries → post-migration Thesis loads via new typed `Monitoring(watch_list=list[WatchItem])` without error.
- **Removed (legacy-only tests no longer apply):** feature-flag-OFF rejection tests, three-way read union tests, legacy renderer-fallback tests, mixed-shape preservation tests. None of those paths exist post-cutover.

### 5.E — `ownership-refresh.md` producer skill

**Skill frontmatter:**
```yaml
description: Refresh Thesis.ownership from FMP institutional + insider data.
classification: producer
mcp_servers:
  - fmp-mcp
  - portfolio-mcp
```

**Skill flow (one phase, no gating):**
1. Read current `Thesis.ownership` (for diff).
2. Call `fmp-mcp.get_institutional_ownership(ticker)` + `get_insider_trades(ticker, lookback_days=90)`.
3. Construct `Ownership(institutional_pct=..., insider_pct=..., recent_activity=<3-5 sentence prose summary>, source_refs=[<src_N from register_sources>])`.
4. Emit `ops:` block:
   ```yaml
   - op: register_sources
     value: [<FMP-derived SourceRecord rows>]
   - op: update_ownership
     value: <Ownership shape from step 3>
   ```
5. Decisions log rationale: `"Refreshed ownership from FMP {date}. Diff: institutional {old}%→{new}%; insider {old}%→{new}%."`

**Verdict:** `OWNERSHIP_REFRESHED` / `INSUFFICIENT_DATA` (FMP returned null pcts).

### 5.F — `monitoring-init.md` producer skill (v6-P2 fix — InvalidationTrigger has no source_refs)

**Skill frontmatter:**
```yaml
description: Initialize Thesis.monitoring.watch_list from existing Thesis catalysts.
classification: producer
mcp_servers:
  - portfolio-mcp
```

**Important schema constraint (v6-P2):** Current `InvalidationTrigger` schema (`thesis_shared_slice.py:229-239`) has NO `source_refs` field. Triggers cannot be cited as evidence for `WatchItem.source_refs` (required non-empty per R1). v1 monitoring-init therefore **derives only from `Thesis.catalysts[]`** (which have `source_ref`). Trigger-based derivation is **out of scope for F124** until a separate workstream adds `source_refs` to `InvalidationTrigger` — see new open decision §7.1.4.

**Skill flow:**
1. Read `Thesis.catalysts[]` + `Thesis.sources[]` (for source-ref validation) + **`Thesis.monitoring.watch_list[]`** (for existing-item dedup).
2. **Initial-state precondition (v22-P2.B fix).** This skill is named `monitoring-init` — it initializes a new watch_list, not edits an existing one. If `Thesis.monitoring.watch_list` is non-empty (post-migration), the skill bails out with verdict `WATCH_LIST_ALREADY_INITIALIZED` and no-op (no patch ops emitted). Editing an existing watch_list is a separate workflow (F129 monitoring agent or future granular `add_watch_item` ops per §7.1.1). Loud bail-out prevents silent overwrite of curated watch items.
3. **Source-ref reuse contract (P2.9):** This skill does NOT call `register_sources`. It reuses existing source IDs from the catalysts it derives from. Validate every reused `src_N` resolves against current `Thesis.sources[]`; if a referenced source isn't registered, **skip** that derivation and emit `add_data_gap`.
4. Build `WatchItem` candidates (only reached if step 2 precondition passed — `watch_list` was empty):
   - Per catalyst with `expected_date` within 90 days AND non-null `source_ref`: `WatchItem(description=f"Catalyst: {catalyst.description}", source_refs=[catalyst.source_ref])`.
   - Skip catalysts with `source_ref=None` (R1 floor; emit `add_data_gap` naming the catalyst).
   - **Triggers are NOT derived** in v1 (see schema constraint above).
   - Assumptions / materiality / risks not in scope (out-of-band for v1).
4. Emit `ops:` block (no `register_sources`; includes zero-or-more `add_data_gap` for skipped catalysts — v11-P2 fix):
   ```yaml
   ops:
     - op: update_monitoring
       op_id: "monitoring_init_{ticker}_{YYYYMMDD}"
       value:
         watch_list: [<typed WatchItem list — only catalysts with valid source_ref>]
         source_refs: [<deduped union of WatchItem source_refs>]
     # One add_data_gap per skipped catalyst (zero entries if all catalysts had source_refs).
     - op: add_data_gap
       op_id: "gap_monitoring_skipped_catalyst_{catalyst_id}_{YYYYMMDD}"
       value:
         gap_id: "gap_monitoring_skipped_catalyst_{catalyst_id}_{YYYYMMDD}"
         description: "Catalyst {catalyst_id} ({catalyst.description}) skipped from monitoring derivation — missing source_ref."
         severity: "minor"  # R1 floor not met; not blocking, just not derivable
         workaround: "Backfill catalyst.source_ref via fundamental-research or register a citing source manually."
   ```
   Deterministic `op_id` / `gap_id` slugs ensure idempotent replay (same catalyst on same date produces same op).
5. Decisions log rationale: `"Initialized {N} watch items from near-term catalysts. Skipped {S} candidates with missing/unresolvable source_refs."`

**Verdict:** `WATCH_LIST_INITIALIZED` / `WATCH_LIST_ALREADY_INITIALIZED` (v22-P2.B fix — existing watch_list non-empty; no-op) / `INSUFFICIENT_DATA` (empty watch_list AND no near-term catalysts with sources) / `RESEARCH_PARTIAL` (empty watch_list, some candidates skipped due to source-ref issues).

**Coordination with `ownership-refresh`:** They write to different Thesis fields; safe to run in same orchestration batch. If running together, the orchestrator should sequence `ownership-refresh` (registers sources + writes ownership) BEFORE `monitoring-init` so any FMP source that monitoring-init wants to cite is already registered.

### 5.G — Frontend renderer (typed-only, no legacy branches)

**Define local TS interface in `frontend/packages/ui/src/components/research/_watchItemTypes.ts`** — local structural type, decoupled from `@risk/connectors` npm sync timing:

```typescript
// Local structural type, mirrors AI-excel-addin WatchItem.
// TODO: once web-app-platform npm sync ships the typed shape, swap to import from @risk/connectors.
interface WatchItem {
  // Backend uses `model_dump(mode="json")` — Optional[T] fields emit as T | null in JSON.
  watch_item_id?: string | null;
  description: string;
  metric?: string | null;
  threshold?: number | string | null;  // Mirrors backend ThresholdValue = str | int | float
  threshold_direction?: 'above' | 'below' | null;
  last_checked?: string | null;
  source_refs: string[];  // Required non-empty per R1; never null
}
```

**`renderMonitoring` — typed-only path (no legacy branches):**

```tsx
const renderMonitoring: SectionRenderer = (value, sourcesById) => {
  if (!isPlainObject(value)) {
    return renderEmptyState('No monitoring items recorded.');
  }
  const watchList = Array.isArray(value.watch_list) ? value.watch_list as WatchItem[] : [];
  if (watchList.length === 0) {
    return renderEmptyState('No monitoring items recorded.');
  }
  return (
    <ul className="...">
      {watchList.map((item, idx) => (
        <WatchItemRow
          key={item.watch_item_id ?? idx}
          item={item}
          sourcesById={sourcesById}
        />
      ))}
    </ul>
  );
};
```

Post-migration there are no legacy entries to render. The renderer assumes typed shape; malformed data crashes the row (loud-failure mode for typed contract).

**Existing-code cleanup required (v20-P2.C — surfaced in codex review):** the current `HandoffSectionRenderer.tsx` (around line 1362) still has `renderMonitoring` branches handling legacy `str` and generic objects from the pre-cutover era. PR 2 must:
- Delete legacy branches in `renderMonitoring` (collapse to the typed-only path above).
- Delete legacy fixture rows from `frontend/packages/ui/src/components/research/__tests__/HandoffSectionRenderer.test.tsx` (around line 787) — these tests assert legacy rendering behavior that won't exist post-cutover.
- Update `frontend/packages/ui/src/components/research/HandoffReviewView.test.tsx` (around line 136) — the mixed legacy fixture in that test must be replaced with a typed `WatchItem` fixture.

Pre-PR-2 grep:
```bash
rg -n 'MonitoringWatchItemObject|LegacyMonitoringWatchItemObject|MonitoringWatchItem|OwnershipWriteValue|OWNERSHIP_REFRESH_ENABLED|MONITORING_V1_3_ENABLED' frontend/
```
Should return zero hits before merge.

**Acceptance:**
- Snapshot: typed `WatchItem` renders with metric + threshold + last_checked badges + clickable source_refs.
- `renderOwnership` minor update: surface `source_refs` chips (R1 makes them required on populated content; UI should show them).
- Removed: legacy snapshot tests, mixed-row snapshot, legacy direction handling.

### 5.X — One-shot data migration (`scripts/migrate_monitoring_ownership_v124.py`)

**Purpose:** convert pre-cutover `monitoring.watch_list` polymorphism and unsourced `Ownership` rows to the post-cutover typed shape. Runs once at deploy time, before new code activates.

**Failure semantics — all-or-nothing live (v20-P1.B):** Live mode runs the entire migration in a **single transaction**. Any row failure (Pydantic validation or source-ref resolution) aborts the transaction and rolls back the entire migration. Dry-run mode is the per-row failure surface — it collects ALL failures across all rows so operators can see the full damage before deciding to (a) fix data and retry, (b) extend the migration logic to handle the failure category, or (c) abort cutover. After dry-run is clean, live must run cleanly to completion or roll back entirely. **No partial-state outcome.**

**Algorithm (per row, both `theses` and `research_handoffs` tables):**

1. Read `artifact` JSON (jsonb column in Postgres / TEXT in SQLite).
2. **Monitoring migration:**
   - Validate `artifact.monitoring` exists and `watch_list` is an array. If `monitoring` missing → skip cleanly. If `watch_list` is non-array → category `MALFORMED_WATCH_LIST_NON_ARRAY`, log + fail row.
   - For each entry in `artifact.monitoring.watch_list`:
     - **Entry edge cases (v20-P3 + v21-P2 — classify explicitly):**
       - Non-string, non-object entry (null, number, boolean, array, etc.) → category `MALFORMED_WATCH_ENTRY_TYPE`, fail row (data corruption — no defined semantics for these types in any pre-cutover shape).
       - String entry → category `LEGACY_STR_DROP`, drop with log (not migratable under R1).
       - Object that **is already a valid typed `WatchItem`** (Pydantic-parseable as `WatchItem`: has `description: str` non-empty, `source_refs: list[str]` non-empty, optional fields match the WatchItem schema, no unknown keys) → category `ALREADY_TYPED_PASSTHROUGH`, preserve unchanged. **`watch_item_id` can be null OR a string** — both are valid (v23-P2 fix). If null, the migration assigns a content-fingerprint ID in place (see step 2.5 below) so re-runs are no-op.
       - Object with `description` empty/None/blank → category `OBJECT_MISSING_DESCRIPTION`, drop with log.
       - Object with `source_refs` non-list → category `MALFORMED_SOURCE_REFS_NONLIST`, fail row (data corruption, not a drop).
       - Object with non-empty `source_refs` AND non-blank `description` → **convert** to typed `WatchItem` shape (see below). Category `OBJECT_CONVERT`.
       - Object with empty/missing `source_refs` → category `OBJECT_UNSOURCED_DROP`, drop with log.
       - Object with invalid `threshold` (not str/int/float/null) → category `INVALID_THRESHOLD`, fail row.
     - **WatchItem conversion** (`OBJECT_CONVERT` path): `{watch_item_id: _allocate_watch_item_id(WatchItem(...), ticker), description: entry["description"], metric: entry.get("metric"), threshold: entry.get("threshold"), threshold_direction: _coerce_threshold_direction(entry), last_checked: entry.get("last_checked"), source_refs: entry["source_refs"]}`. **Migration allocates content-fingerprint IDs in place** (v23-P2 fix) using the same `_allocate_watch_item_id` helper from §4.3, with ticker from `artifact.company.ticker`. Result: post-migration entries always have a string `watch_item_id`, making subsequent migration runs idempotent (those entries match `ALREADY_TYPED_PASSTHROUGH`). Extras dropped + logged per drop (category `EXTRAS_DROP`).

  **2.5. Allocate IDs for any ALREADY_TYPED_PASSTHROUGH entries with `watch_item_id: null`** (post-cutover edge case: migration was previously partial-run with null IDs). Use the same `_allocate_watch_item_id` helper. Category: `ALREADY_TYPED_ID_BACKFILL`. After step 2.5 completes, every entry has a string `watch_item_id`.

  **2.6. Uniqueness pass (v24-P2.B + v26-P2 fix — mirrors `_apply_monitoring_patch` collision handling).** After steps 2-2.5 assign all `watch_item_id`s, run the uniqueness check using a **`Counter` over the full final watch_list IDs** (not a `set`, which silently deduplicates):
  ```python
  from collections import Counter
  final_ids = [entry["watch_item_id"] for entry in final_watch_list]
  id_counts = Counter(final_ids)
  duplicates = [(wid, count) for wid, count in id_counts.items() if count > 1]
  if duplicates:
      raise RowMigrationError(MIGRATION_ID_COLLISION, duplicates=duplicates)
  ```
  This catches all four collision shapes:
  - Two `OBJECT_CONVERT` entries with identical fingerprint (same description+metric+threshold+direction → same hash).
  - Caller-provided ID (on an `ALREADY_TYPED_PASSTHROUGH` entry) that matches a generated fingerprint of another entry.
  - **Two `ALREADY_TYPED_PASSTHROUGH` entries sharing the same caller-provided ID** (legacy data corruption — set would lose this, Counter catches it).
  - `ALREADY_TYPED_ID_BACKFILL` allocating an ID that collides with an existing caller-provided ID elsewhere in the row.

  On collision, **fail the row** with category `MIGRATION_ID_COLLISION` (lists the colliding IDs + counts + entries). Do NOT silently suffix in migration — collisions in archival data indicate ambiguity that operators must review (vs the apply path where suffix is acceptable because input is one batch from a single skill). Op-time collision handling (suffixing) is for new writes; migration is archival and suffixing would hide data-quality issues.
   - `_coerce_threshold_direction` helper: if entry has `threshold_direction` ∈ `{"above", "below"}`, use it. Else if entry has legacy `direction` field, check if it's `"above"`/`"below"` — use it if so (some legacy data may have used `direction` for threshold comparator); if it's a position-side (`long`/`short`/`hedge`/`pair`) or anything else, set `null` (these are position-side semantics that don't apply to monitoring thresholds). Log category `DIRECTION_COERCED` per row that exercises this path.
3. **Ownership migration:**
   - If `artifact.ownership` exists and any of `institutional_pct` / `insider_pct` / `recent_activity` is populated AND `source_refs` is empty: **null-out the populated fields**. Set `artifact.ownership = {institutional_pct: null, insider_pct: null, recent_activity: null, source_refs: []}`. Category `OWNERSHIP_NULLED`.
   - If `artifact.ownership.source_refs` is non-list → category `MALFORMED_OWNERSHIP_SOURCE_REFS`, fail row.
   - If R1-clean (populated → has source_refs OR fully empty), pass through unchanged.
4. **Validate post-migration shape (v20-P1.C — strengthen):**
   - (a) Parse rewritten `artifact` via the new `Thesis` / `HandoffArtifact` Pydantic models. Fail row on ValidationError with category `PYDANTIC_VALIDATION`.
   - (b) **Resolve every source_ref in monitoring + ownership against `artifact.sources[]`** using the same `_known_source_ids_from_sources` + `_validate_source_refs_resolve` helpers the patch engine uses post-cutover. Any `src_N` reference in `artifact.monitoring.*.source_refs` or `artifact.ownership.source_refs` that doesn't resolve → fail row with category `DANGLING_SOURCE_REF` (lists the unresolved ID + which field). This catches pre-cutover data where source registrations and watch_list source_refs drifted out of sync — would crash post-cutover apply.
5. Write the migrated `artifact` JSON back to the row (inside the single live-mode transaction).

**Loss accounting (v20-P2.A — strengthen):** Dry-run output JSONL records per-row category counts + a row-level summary. Verify mode (run post-migration) re-validates every row's post-state (Pydantic parse + source-ref resolution) and produces a separate `verify.jsonl` summary; it does NOT expect migration categories to reappear (rows are already migrated). The verify-vs-dry-run cross-check is: dry-run aggregate counts of categories applied should match live mode's applied counts (logged from the live transaction), AND verify mode should find zero failures across all rows. Summary fields:
- `row_id`, `row_table`, `result` (`migrated` / `failed` / `unchanged`)
- `categories_applied` (dict): `{LEGACY_STR_DROP: N, OBJECT_CONVERT: N, OBJECT_UNSOURCED_DROP: N, EXTRAS_DROP: N, DIRECTION_COERCED: N, OWNERSHIP_NULLED: N, ...}`
- `failure_category` (if failed) + `failure_detail`
- `artifact_before_hash`, `artifact_after_hash` (sha256 of canonical JSON before/after)
- `sample_dropped` (list of up to 3 dropped-entry snippets, for ops review)

Per-table aggregates (printed to stderr at end of run):
```
=== theses ===
  rows: 1234 / failures: 0
  LEGACY_STR_DROP: 0
  OBJECT_CONVERT: 5
  OBJECT_UNSOURCED_DROP: 2
  OWNERSHIP_NULLED: 0
  EXTRAS_DROP: 1 (across 1 row)
  ...
=== research_handoffs ===
  ...
```

**CLI modes:**

```bash
# Dry-run: per-row validation, no writes, collects ALL failures across all rows for ops review.
python scripts/migrate_monitoring_ownership_v124.py --dry-run --db-url $DB_URL --log-path dry-run.jsonl

# Live: single transaction across all rows. ANY failure aborts + rolls back the whole transaction.
# Operator must re-run dry-run first to verify zero failures before this is safe.
python scripts/migrate_monitoring_ownership_v124.py --live --db-url $DB_URL --log-path live.jsonl

# Verify: re-reads all rows post-migration, re-runs full validator pipeline (Pydantic + source-ref resolution).
python scripts/migrate_monitoring_ownership_v124.py --verify --db-url $DB_URL --log-path verify.jsonl
```

**Acceptance:**
- Dry-run on production snapshot completes with zero `result=failed` rows.
- Live run: either succeeds entirely (transaction commits) or rolls back entirely (transaction aborts). Per-row aggregate summary matches the dry-run output exactly.
- Verify pass: every row post-migration parses via new Pydantic types AND all `source_refs` resolve; zero `result=failed` rows in verify.jsonl. Cross-check: dry-run aggregate category-applied counts equal live-mode category-applied counts (catches drift between the two runs).
- Idempotency: re-running on already-migrated data is a no-op (all rows are `result=unchanged`).

**Test fixtures in §5.D:**
- Golden file with one pre-migration thesis containing each entry category (string, object-convert, object-unsourced, object-with-extras) + one Ownership row needing nulling. Migration produces deterministic typed JSON output.
- Failure-path golden: thesis with `MALFORMED_WATCH_LIST_NON_ARRAY` → row fails with named category.
- Source-ref drift golden: thesis with `monitoring.watch_list[0].source_refs = ["src_99"]` but no `src_99` in `artifact.sources[]` → row fails with `DANGLING_SOURCE_REF`.
- **Collision golden — duplicate OBJECT_CONVERT fingerprints (v25-P3 fix):** thesis with two `OBJECT_CONVERT` candidates having identical `description` + `metric` + `threshold` + `threshold_direction` → identical canonical-JSON → identical SHA-256 prefix → row fails with `MIGRATION_ID_COLLISION` (lists both colliding entries).
- **Collision golden — caller-vs-generated (v26-P3 fix):** test fixture is built dynamically: first compute the generated fingerprint for a known content tuple (e.g., `WatchItem(description="X", metric="Y", source_refs=["src_1"])` against `ticker="ABC"`) via the actual `_allocate_watch_item_id` helper; then construct a fixture thesis with (a) one `OBJECT_CONVERT` entry matching that exact content tuple, AND (b) one `ALREADY_TYPED_PASSTHROUGH` entry with `watch_item_id` set to the precomputed fingerprint. Test exercises the real collision. Do NOT use a hardcoded ID like `watch_abc123def456` — that won't actually collide.
- **Collision golden — duplicate caller-provided IDs (v26-P2 fix):** thesis with two `ALREADY_TYPED_PASSTHROUGH` entries sharing the same `watch_item_id` (legacy data corruption that `set`-based dedup would hide) → row fails with `MIGRATION_ID_COLLISION`.

---

### 5.H — Integration test (end-to-end, post-cutover)

**File:** `tests/integration/test_f124_monitoring_ownership_e2e.py` (new).

**Scenarios (post-cutover):**
1. **Greenfield monitoring:** New Thesis → `monitoring-init` runs → typed watch_list lands with deterministic IDs → finalize → HandoffArtifact preserves typed shape.
2. **Migration round-trip (validates §5.X):** Pre-migration Thesis with `watch_list: ["str", {"description": "x", "extras": "old"}]` + ownership populated without source_refs → run §5.X migration → resulting Thesis loads cleanly via new `Monitoring` + `Ownership` types; finalize succeeds.
3. **Producer skill chain — ownership:** `ownership-refresh` → `register_sources` (FMP-derived) + `update_ownership` → assert FMP-derived source_refs resolve via `iter_source_refs`; resulting `Ownership.source_refs` references canonical `src_N` IDs.
4. **Producer skill chain — monitoring catalyst-reuse:** `monitoring-init` running against a Thesis with near-term catalysts that have valid `source_ref` → emits `update_monitoring` only (no `register_sources`); resulting `WatchItem.source_refs` references each catalyst's existing `src_N`. Triggers excluded per §5.F.
5. **Producer skill chain — monitoring catalyst-skip:** `monitoring-init` against a Thesis where one near-term catalyst has `source_ref=None` → that catalyst is skipped, `add_data_gap` emitted, verdict is `RESEARCH_PARTIAL`.
6. **Build orchestrator unaffected:** `build_model` over a Thesis with typed monitoring still produces .xlsx; `research_handoffs` row preserves typed monitoring shape.
7. **Same-batch conflict:** Two `update_monitoring` ops in the same batch with overlapping field updates → `_dry_fold_detailed` returns `_divergent_update_conflict`.
8. **Source rewrite-before-validation order:** Batch with `register_sources` (caller-predicted `src_99` → canonical `src_5` via identity-hash dedup) + `update_ownership.value.source_refs=["src_99"]` → final `ownership.source_refs == ["src_5"]` post-apply.
9. **Cross-skill orchestration:** `ownership-refresh` + `monitoring-init` in one orchestration batch — sources from FMP register first, then both writes apply correctly.
10. **Removed (legacy-only scenarios no longer apply):** flag-OFF reader compat, legacy rendering of archived handoffs, flag-combination permutations, legacy-string preservation under unrelated write.

---

## 6. Cross-repo PR sequence

| Order | Repo | PR scope | Gate |
|---|---|---|---|
| 1 | AI-excel-addin | Sub-phases A, B, C, D, E, F, H, X (schema + patch ops + apply + skills + tests + migration script). Tests run against post-migration shape; CI also runs migration round-trip test. | Codex review PASS; pre-cutover audit SQL run on staging shows expected legacy counts (near-zero); migration dry-run succeeds on staging snapshot. |
| 2 | risk_module | Sub-phase G — typed-only frontend renderer + snapshot tests. Uses local TS interface in `frontend/packages/ui/src/components/research/_watchItemTypes.ts`. | Tests pass. Independent of PR 1 npm publication. |
| 3 | AI-excel-addin deploy | **Step a:** dry-run migration against staging snapshot (early signal). **Step b:** take pre-migration logical backup of production DB. **Step c:** stop writes (read-only window starts). **Step d:** run §5.X dry-run against LIVE production DB (no race — old code can't write during the window). **Step e:** if dry-run shows zero failures, run §5.X live (single transaction, all-or-nothing). **Step f:** verify pass against migrated DB. **Step g:** activate new code (PR 1 + PR 2 deploy). **Step h:** end read-only window. **Step i:** post-activation smoke (run `monitoring-init` on staging Thesis; assert typed watch_list landed). | Each step gates the next. If step (d) shows any failure rows, abort cutover and investigate (old data is still safely under read-only). If step (e) transaction aborts, the DB is unchanged (transaction rollback). If step (g) activation fails post-migration, restore from step (b) backup. |
| 4 | Rollback path (only if PR 3 fails post-step-e) | Deploy revert + DB restore from pre-migration backup taken in step (b). | Production data restored to pre-migration state; root-cause investigation before re-attempt. |

---

## 7. Risks & open decisions

### 7.1 Open decisions for Codex review (post-cutover rewrite)

1. **Granular ops vs single replace.** Plan ships `update_monitoring` as full-replace. Granular `add_watch_item` / `remove_watch_item` / `update_watch_item` could reduce conflict surface for monitoring agent (F129). *Recommendation:* defer to F129 when concrete usage shows full-replace causing real conflicts.
2. **`recent_activity` shape.** `Ownership.recent_activity: str | None` is freeform prose. Should it be structured (e.g., `list[InsiderActivityEntry]`)? *Recommendation:* keep prose in v1; structure if monitoring agent (F129) needs to act on it programmatically.
3. **Migration handling of unsourced ownership.** §5.X migration finds Thesis rows with populated `Ownership` fields but no `source_refs`. Three options: (a) null-out the populated fields (lose data, but R1-clean); (b) backfill source_refs via re-running ownership-refresh against FMP at migration time (slow but preserves data); (c) fail loudly and force operator decision per row. *Recommendation:* (a) by default — pre-cutover audit query in §4.1 surfaces counts; if non-trivial, operator can decide to add a backfill pass to the migration. Migration script logs each null-out for audit.
4. **`InvalidationTrigger` source_refs schema gap.** `InvalidationTrigger` schema has NO `source_refs` field, so F124 `monitoring-init` cannot derive `WatchItem` entries from triggers (R1 evidence requirement). v1 derives only from catalysts. Options: (a) add `source_refs` to `InvalidationTrigger` + migration; (b) link triggers to owning assumption via `assumption_id`; (c) leave unsourced. *Recommendation:* (a) as separate follow-up. Out of F124 scope.

### 7.2 Risks (post-cutover rewrite)

| # | Risk | Mitigation |
|---|---|---|
| R1 | Production data has legacy `MonitoringWatchItemObject` entries with extras that lose information on cutover | §5.X migration converts entries with `source_refs` to typed `WatchItem` (preserving description + threshold + direction); extras are explicitly dropped because the new typed schema doesn't model them. Pre-cutover audit in §4.1 surfaces counts so user can review what's lost. Per design doc, legacy was schema-free "deferred-to-usage" punt — usage never came, so loss is expected to be near-zero. |
| R2 | Legacy `str` watch entries cannot be migrated (no source citation) | §5.X migration drops them with explicit log entry per drop. Pre-cutover audit warns; operator decides whether to accept drop or pre-run `monitoring-init` to populate typed entries before cutover. |
| R3 | `_apply_ownership_patch` / `_apply_monitoring_patch` helpers regress when refactored later | Kept specific — no generic `_apply_top_level_patch`. Any future top-level field gets its own explicit helper. |
| R4 | `monitoring-init` references source_refs that aren't registered, breaking R1 | Skill validates source_ref resolution before emitting; unresolvable refs trigger `add_data_gap` + skip instead of an invalid `update_monitoring`. Integration test §5.H scenario 5. |
| R5 | Migration script fails partway through (e.g., one un-migratable row halts the transaction) | Dry-run mode collects ALL failures across all rows so operators see the full damage before any write. Live mode is single-transaction all-or-nothing — any failure rolls back the entire migration; operator fixes data and retries dry-run. No partial-state outcome (v20-P1.B). |
| R6 | OCC retry re-allocates new `watch_item_id` on each attempt, breaking idempotent replay | Content-fingerprint allocation: same logical item → same ID. Op is not mutated; allocation happens on a local copy. Test §5.D OCC-retry case. |
| R7 | R6 (claim + same-target data_gap forbidden) declared but not enforced; producer skills could emit both | F124 only declares R6 applies to WatchItem; full cross-type validator lands with F125 (W2 audit backbone). Producer-skill prose is the only guard until F125 ships. |
| R8 | Rollback requires DB restore from snapshot — feature flag toggle not available | Acceptable per user direction. PR 3 step (a) takes the snapshot; PR 3 step (c) is the irreversible-without-restore commit. Take an additional logical backup before step (c). |

---

## 8. Plan history

**v1-v19 — staged-rollout design with legacy compat (superseded).** Plan iterated 19 codex review rounds at the staged-rollout / legacy-compat design. Final v19 reached PASS but carried significant complexity: three-way read union (`str | WatchItem | LegacyMonitoringWatchItemObject`), `MonitoringWatchItemObject` alias kept indefinitely, two feature flags (`OWNERSHIP_REFRESH_ENABLED` + `MONITORING_V1_3_ENABLED`), separate `Ownership` (read-permissive) / `OwnershipWriteValue` (write-strict) split, legacy renderer branches preserved indefinitely.

**v20-v21 — full cutover (current).** User direction 2026-05-22: no legacy / deprecation paths. v21 = v20 + post-codex-review hardening (malformed-entry-type category, verify-mode clarification, all-or-nothing migration semantics). All staged-rollout machinery removed in favor of one-shot data migration. Affected:
- Schema: deleted `LegacyMonitoringWatchItemObject`, three-way `MonitoringWatchItem` TypeAlias, `MonitoringWatchItemObject = LegacyMonitoringWatchItemObject` alias, `OwnershipWriteValue`. `Monitoring.watch_list: list[WatchItem]` typed-only. `Ownership` carries R1 validator directly.
- Patch ops: kept `MonitoringWriteValue` (for cross-item dup-ID validator); `UpdateOwnershipOp.value: Ownership` (no read/write split).
- Feature flags: deleted both. `feature_flags.py` changes removed entirely.
- Dispatch: no flag gates.
- Frontend: typed-only renderer; no legacy branches; no three-way TS union.
- Migration: NEW §5.X script — one-shot data migration runs in PR 3 deploy step before new code activates.
- Tests: removed flag-OFF, mixed-shape, archived-handoff-legacy scenarios; added migration round-trip scenario.

This rewrite preserves the load-bearing technical content from v1-v19 (canonical-JSON content fingerprint, DuplicateStableIdError signature, descriptor exclude_none=False, source-ref InvalidTargetError wrap, schema/__init__.py re-exports, `_known_source_ids_from_sources` import note, R6 deferral to F125, InvalidationTrigger source_refs gap in §7.1.4) while removing all staged-rollout overhead.

## 8.5 — F125 integration contract

F124 writes `Ownership.source_refs` + `WatchItem.source_refs` that point at `SourceRecord` rows. Those rows fall in two categories:
1. **F124-registered:** rows newly registered by `ownership-refresh` via `register_sources` (FMP-derived).
2. **Pre-existing:** rows already on `Thesis.sources[]` from earlier producer skills (e.g., `identifying-risk` registered the source supporting an invalidation_trigger; `monitoring-init` reuses it without re-registering — see §5.F P2.9 fix).

**Neither category carries `Excerpt` atoms** — D1's `Excerpt` typing is F125 (W2) scope, not F124.

F125 will extend `SourceRecord` with `excerpts: list[Excerpt]`. **Compatibility contract:**
- F125 MUST accept **any pre-F125 `SourceRecord`** with empty/null `excerpts` — covers F124-registered rows AND pre-existing rows referenced by F124 outputs AND rows registered by any other pre-F125 producer skill. Pre-F125 sources are not malformed; they predate F125's stricter validation.
- F125 may surface them as a "needs excerpt backfill" diagnostic but MUST NOT reject them outright.
- A separate backfill workstream (not F124, not F125 core) walks production `theses` + `research_handoffs` rows and back-fills `Excerpt` atoms for pre-F125 sources from existing annotation data (or marks as `data_gap` if no annotation exists).
- F124 producer skills (`ownership-refresh`, `monitoring-init`) do NOT need to anticipate F125's excerpt schema — they emit current `SourceRecord` shape. When F125 lands, both skills will be updated in the F125 plan to emit Excerpt atoms.

This boundary is documented in this section so F125's plan inherits it.

## 8.codex-review-brief — v21

Send v21 to Codex with focus on the cutover-specific concerns (the v1-v19 technical content was already PASS-verified at v19):

1. **§5.X migration script correctness** — does the per-row algorithm correctly handle all pre-cutover shapes? Any edge case (e.g., `LegacyMonitoringWatchItemObject` entries where `description` is None? Ownership with partial population — `institutional_pct` set but `insider_pct` null?) missed?
2. **Migration loss accounting** — pre-cutover audit (§4.1 SQL) + drop-logging design adequate for ops to vet what's being lost? Or should we add a snapshot/diff verification step?
3. **Removed-legacy verification** — is the schema rewrite (§5.A) truly free of residual legacy references? Any other module (`api/research/handoff.py` `_assemble_artifact`, `schema/thesis_markdown.py`) that still expects polymorphic watch_list shapes and would crash post-cutover?
4. **PR sequence safety** — PR 3 step ordering correct? Should pre-migration snapshot be a separate step before step (a) dry-run, or is the dry-run safe enough to not require a pre-dry-run snapshot?
5. **Backward-compat tests** — are any existing tests in `tests/integration/test_*_e2e.py` or `tests/schema/test_thesis_types.py` going to break on the legacy-shape removal? Plan §5.D notes test removal but doesn't enumerate which existing tests need updating.

Iterate until PASS per `feedback_codex_review_pass_loop.md`. Address all findings including non-blocking.

---

## 9. Acceptance criteria (closeout)

- [x] PR 1 (AI-excel-addin) merged with focused tests green.
- [x] PR 2 (risk_module) merged with focused frontend tests green.
- [x] §5.X migration script landed with focused migration coverage.
- [ ] §5.X migration dry-run on production snapshot completes with zero `result=failed` rows before production cutover.
- [ ] PR 3 deploy executes per §6: snapshot → dry-run → live migration → activate new code → verification.
- [ ] Live smoke: `monitoring-init` runs on real Thesis (e.g., PCTY) and produces typed `watch_list`; `ownership-refresh` produces typed `Ownership`.
- [ ] `build_model` over the resulting Thesis produces `.xlsx` without schema-version regression.
- [x] F124 row moved from `docs/TODO.md` to `docs/TODO_COMPLETED.md` with shipped notes.
- [x] Matrix doc Stage G (ownership) + Stage K (monitoring.watch_list) rows updated from "Unwired" → producer skill name.
- [x] Layers doc D3 status flipped to "Resolved".

---

## Related

- [`RESEARCH_ARTIFACT_LAYERS.md`](RESEARCH_ARTIFACT_LAYERS.md) — design authority (D3, R10, R11, R12)
- [`THESIS_WRITE_SURFACE_COVERAGE.md`](THESIS_WRITE_SURFACE_COVERAGE.md) — matrix (Stages G, K)
- [`F135_PREMISE_VERIFICATION_REPORT.md`](F135_PREMISE_VERIFICATION_REPORT.md) — patch engine + schema patterns verified
- `HANDOFF_ARTIFACT_V1_1_PLAN.md` — Pydantic typing + stable ID precedent
- `INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` G9/G15 — the polymorphism this plan closes
