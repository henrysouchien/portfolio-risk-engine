> **✅ DONE — Premise verification complete; moved during 2026-05-28 docs cleanup.**

# F135 — Load-Bearing Premise Verification Report

**Status:** Verified 2026-05-20. F135 work complete.
**Scope:** Verify the 12 load-bearing premises (V1-V12) in [`RESEARCH_ARTIFACT_LAYERS.md`](RESEARCH_ARTIFACT_LAYERS.md) "Verification" section against the actual `AI-excel-addin/` implementation, since those claims live outside the risk_module sandbox and were not auto-verifiable during the design pass.
**Outcome:** 10 of 12 confirmed clean. 2 minor doc-corrections required (V5 name, V12 schema_version). No design adjustments needed — load-bearing assumptions hold.

---

## Verification table

| # | Premise | Status | Evidence |
|---|---|---|---|
| V1 | `register_sources` runs under single-register-per-batch lock | ✅ **CONFIRMED** | `api/research/patch_engine.py:304-306`: `register_ops = [op for op in batch.ops if isinstance(op, RegisterSourcesOp)]; if len(register_ops) > 1: raise ValueError("multiple register_sources ops not supported")`. Explicit enforcement at batch validation. |
| V2 | `add_differentiated_view_claim` is the only patch op that hard-rejects empty evidence | ✅ **CONFIRMED** | `schema/handoff_patch.py:149`: `AddClaimValue.evidence: list[SourceId] = Field(min_length=1)` — Pydantic-level rejection. Grep across all `Add*Value` classes (`AddAssumptionValue`, `AddRiskValue`, `AddCatalystValue`, `AddTriggerValue`, `AddHistoricalCoincidenceValue`, `AddDataGapValue`, `AddEditorialPeerValue`) confirms none of them apply `min_length=1` to `source_refs` / `evidence`. R1 generalization is the right move — V2 holds, and R1 extends the pattern. |
| V3 | `source_refs` is on Assumption, Risk, Catalyst, Valuation, BusinessOverview, IndustryLandscape, MacroOverlayDriver, StructuralTrend, GaapNonGaapBridge, HistoricalCoincidence, MaterialityThreshold, Peer, Ownership, Monitoring, QualitativeFactor | ✅ **CONFIRMED** | `schema/thesis_shared_slice.py` + `schema/thesis.py`: every listed nested model carries `source_refs: list[SourceId] = Field(default_factory=list)` or `citations: list[SourceId] = Field(default_factory=list)`. Also confirmed on `ConsensusView`, `DifferentiatedViewClaim`, `EditorialPeer`. |
| V4 | `iter_source_refs` walks the full payload validating `src_N` resolution | ✅ **CONFIRMED** | `api/research/handoff.py:238`: `def iter_source_refs(payload: Any) -> Iterator[str]` recursively walks dicts and lists, yielding normalized source-id strings from `_SOURCE_REF_LIST_KEYS` and `_SOURCE_REF_SCALAR_KEYS`. Paired with `_validate_source_refs_resolve` (handoff.py:271) which compares against known source IDs. |
| V5 | Source identity-hash dedup across snapshots | ✅ **CONFIRMED — minor name correction** | `api/research/handoff.py:138` actual class name is `_SourceRefRegistry` (not `_SourceRegistry` as the design doc says). Identity-hash dedup confirmed at `_ids_by_identity: dict[tuple[Any, ...], str]` map; `register_source` checks `existing_id = self._ids_by_identity.get(identity)` and reuses if found. **Doc fix:** rename `_SourceRegistry` → `_SourceRefRegistry` in `RESEARCH_ARTIFACT_LAYERS.md` "Already enforced" table. |
| V6 | `decisions_log` auto-appended on every patch batch | ✅ **CONFIRMED** | `api/research/repository.py:2304`: `def append_decisions_log_entry(self, thesis_id: str, entry: DecisionsLogEntry | dict[str, Any])`. Called from `api/research/handoff.py:510-512` post-patch-apply with a `DecisionsLogEntry` constructor. Auto-append pattern holds. |
| V7 | `monitoring.watch_list` schema-free per ADR | ✅ **CONFIRMED** | `docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md:355-357` literally shows `"monitoring": { "watch_list": [...] }` with no typed shape. The deferred-to-usage punt is in the doc. D3 (typing it now) closes this debt. |
| V8 | `critical-factors` Step 9 emits `add_historical_coincidence` | ✅ **CONFIRMED** | `AI-excel-addin/api/memory/workspace/notes/skills/critical-factors.md:299`: `- op: add_historical_coincidence`. Verified during initial design-pass. D2 already incorporates this. |
| V9 | `position-initiation` chains to `execute_trade` | ✅ **CONFIRMED — and gate already exists** | `AI-excel-addin/api/memory/workspace/notes/skills/position-initiation.md:166-167`: `preview_trade` → `execute_trade(preview_id="...")` only after user confirms. The portfolio-write human-gate is already a precedent in `position-initiation`, not new policy. D10 + R7 generalize this pattern; F134 enforcement work has a working template. |
| V10 | HandoffArtifact `_assemble_artifact` re-derives shared slice from Thesis verbatim on finalize | ✅ **CONFIRMED** | `api/research/handoff.py:449`: `def _assemble_artifact_locked` resolves thesis_row via `_resolve_thesis_row`, then calls `_build_validated_artifact(file_row, handoff_row, draft_artifact, thesis_row)` which re-derives the shared slice. R8 invariant (HandoffArtifact immutability) is consistent with this re-derive-on-finalize pattern. |
| V11 | `register_sources` rewrites `source_refs` recursively via `_rewrite_source_refs_recursive` | ✅ **CONFIRMED** | `api/research/patch_engine.py:763`: `def _rewrite_source_refs_recursive(value: Any, mapping: dict[str, str]) -> Any` walks dicts/lists, rewrites `_SOURCE_REF_LIST_KEYS` and `_SOURCE_REF_SCALAR_KEYS` entries through the `mapping`. Used post-`register_sources` to translate caller-predicted `src_N` to canonical IDs. |
| V12 | HandoffArtifact `schema_version` current production value | ⚠️ **ADJUSTMENT** | `schema/handoff.py:155`: `schema_version: Literal["1.1", "1.2"] = "1.2"`. **Production default is v1.2** (with v1.1 read compatibility). **Doc fix:** layers doc says "HandoffArtifactV1_2 Pydantic (schema v1.1 + v1.2 supported)" — clarify that v1.2 is the canonical write/finalize shape; v1.1 is read-only legacy. |

---

## Findings summary

**No design adjustments needed.** The 12 premises are load-bearing for D1-D10, R1-R12, and the success criteria, and all 12 are accurate at the level the design depends on them.

**Two doc-text corrections** (cosmetic, no semantics change):
1. **V5:** Rename `_SourceRegistry` → `_SourceRefRegistry` in `RESEARCH_ARTIFACT_LAYERS.md` "Already enforced" table.
2. **V12:** Clarify in layers doc that v1.2 is the production default (write/finalize shape) and v1.1 is read-only legacy.

**One bonus finding from V9** — strengthens D10/R7:
- `position-initiation` already implements the "portfolio-affecting writes need human gate" pattern (`execute_trade` is gated on user confirmation post-`preview_trade`). F134 (W3 enforcement) work has a working in-repo precedent to generalize from, not a from-scratch design.

---

## Next steps

1. Apply the V5 + V12 doc corrections to `RESEARCH_ARTIFACT_LAYERS.md` (small Edits).
2. Mark F135 complete in TODO and move row to `TODO_COMPLETED.md`.
3. Proceed with parallel workstreams per recommended start order: F124 (W1) / F125 (W2) / F127 (position lifecycle) / F133 (ModelInsights+PriceTarget Thesis integration). F126 (W3 policy) gates F134 (W3 enforcement); F129 (monitoring agent) gates on all of those.

---

## Provenance

Verification commands used (all from `/Users/henrychien/Documents/Jupyter/AI-excel-addin/`):
- `sed -n '730,780p' api/research/patch_engine.py` — V1, V11
- `grep -nE "class Add.*Op|raise.*evidence" schema/handoff_patch.py` + `sed -n '145,185p' schema/handoff_patch.py` — V2
- `grep -nE "class (Assumption|Risk|...)" schema/thesis_shared_slice.py` — V3
- `sed -n '234,275p' api/research/handoff.py` — V4
- `sed -n '135,195p' api/research/handoff.py` — V5
- `grep -nE "append_decisions_log_entry" api/research/repository.py api/research/handoff.py` — V6
- `sed -n '350,365p' docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE_DECISIONS.md` — V7
- `sed -n '449,485p' api/research/handoff.py` — V10
- `grep -nE "execute_trade" api/memory/workspace/notes/skills/position-initiation.md` — V9
- `grep -n "schema_version" schema/handoff.py` — V12
- V8 verified during initial design-pass conversation.
