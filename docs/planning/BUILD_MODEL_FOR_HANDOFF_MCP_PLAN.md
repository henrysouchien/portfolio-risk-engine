# Build-Model Skill — Wire to Existing `build_model` MCP Tool

**Status**: ✅ R4 PASS — ready for implementation
**Last revised**: 2026-04-28
**Closes**: AI-excel-addin TODO #22 — `build-model` skill cannot trigger MI/PT emission today.

---

## 0. Review history

**R0 → R1 pivot**: R0 caught a load-bearing premise error — risk_module already ships a `build_model(research_file_id, handoff_id?, model_build_context_id?)` MCP tool at `actions/research.py:709` + `mcp_tools/research.py:441` + `mcp_server.py:2633`. v0 proposed a duplicate. R1 pivoted scope to skill prose + frontmatter rewire only.

**R1 → R2 tightening**: R1 found 2 blockers + 5 should-fixes:
- **B1**: §3.2/§3.3 dispatch logic could silently bypass MI/PT if memory_recall missed a finalized handoff. R2 collapses to a single delegation contract: skill always passes `research_file_id` to `build_model` and trusts the tool's auto-resolution; handles `no_finalized_handoff` response for the not-finalized case.
- **B2**: claim of "atomic emission" overstated. Plan #6 §11.1 Scenario 10: emit failure is non-fatal — build succeeds, MI/PT row may be absent. R2 §3.5 + §4 + §10 describe MI/PT as orchestrator-side, non-critical side effects with read-side error handling required.
- **S1**: error path ordering — `no_finalized_handoff` set `status: "error"` so the generic check shadowed it. R2 §3.3 reorders.
- **S2**: AI-excel-addin skill loader frontmatter format unverified. R2 §3.1 adds an explicit pre-ship verification gate.
- **S3**: `assumptions_skipped` not in existing response (action drops it at `actions/research.py:759-777`). R2 §3.4 removes the reference.
- **S4**: concurrency language conflated MI/PT storage shapes. ModelInsights = append (`insert_model_insights`); PriceTarget = upsert (`upsert_price_target`). R2 §4 corrected.
- **S5**: smoke test floor too weak. R2 §6.2 adds a harness-discovery step.
- **N1**: §3.5 placeholder `RESEARCH_FILE_ID` should reference `result["research_file_id"]`. R2 §3.5 fixed.

R0 findings B1–B5 + S1–S5 + N1 (R0) and B1–B2 + S1–S5 + N1 (R1) are all addressed below.

---

## 1. Goal

Rewire AI-excel-addin's `build-model.md` skill to dispatch through the existing `portfolio-mcp.build_model(research_file_id, handoff_id?, model_build_context_id?)` tool when a finalized research handoff is in scope. Existing `model-engine.model_build(...)` raw-build path stays as the fallback for handoff-less builds.

Result: skill-driven builds for finalized handoffs go through `BuildModelOrchestrator.build_and_annotate` server-side, which (a) runs build + annotation atomically and (b) attempts ModelInsights + PriceTarget emission as a non-critical post-build side effect (per Plan #6 §11.1 Scenario 10 — emit failure does not fail the build, MI/PT rows may be absent on success).

### 1.1 In scope (v1)
- Skill frontmatter: add `portfolio-mcp` to `mcp_servers` list.
- Skill prose: Phase 1 step 2 `research_file_id` detection only (handoff finalization delegated to `build_model`'s auto-resolve); Phase 2 step 4 dispatch branch keyed on `research_file_id` presence; Phase 3 step 6 conditional skip; Phase 4 step 7b post-build MI/PT surfacing using the `research_file_id` from the build response.
- `SKILL_CONTRACT_MAP.md` `build-model` row flip from `~ partial` to `✓ built`.
- Both `TODO.md` files marked complete.

### 1.2 Out of scope (v1)
- New MCP tools (the read-side + build-side tools all already ship in portfolio-mcp).
- New typed error classes (existing `build_model` returns response-side `{status: "error", error: "..."}` — that IS the contract, not raised exceptions).
- `re_annotate` exposure — no MCP wrapper today; skill must NOT instruct analyst to "re_annotate later" (R0 S2).
- Frontend "build for handoff" UI.
- Auto-finalize-then-build (handoff present but not finalized → surface error and stop).

---

## 2. Architecture decision

**Use existing tool: portfolio-mcp `build_model`** at `risk_module/actions/research.py:709` + `mcp_tools/research.py:441`.

Confirmed shape (read 2026-04-28):
- **Input**: `research_file_id: int`, `handoff_id: int | None = None` (auto-resolves finalized handoff if omitted), `model_build_context_id: str | None = None`.
- **Server-side**: POSTs to `handoffs/{handoff_id}/build-model` with optional `{model_build_context_id}` body. Server runs `BuildModelOrchestrator.build_and_annotate` or `build_and_annotate_from_mbc_id` per the existing HTTP route at `AI-excel-addin/api/research/routes.py:1568`.
- **Output**: `{status, research_file_id, model_path, handoff_id, build_status, annotation_status, model_build_context_id?, error?, annotation_error?}` plus `flags` from `generate_research_flags(result, context="build")` (existing flag context — R0 S1 fix).
- **Error contract**: response-side fields. `status: "error"` + `error: "..."` for build/orchestrator failures; `annotation_status: "error"` + `annotation_error: "..."` for non-fatal annotation failures (build still succeeded). No raised typed exceptions for these — gateway only typed-maps codes in `_THESIS_ERROR_TYPES` (R0 B2 fix).

**Why this works**: Plan #6 sub-phase G read tools (`get_model_insights`, `get_price_target`, `preview_patch_ops`, `apply_patch_ops`) are already wired through `research_gateway.request(...)` from portfolio-mcp. The build-side tool predates Plan #6 and uses the same gateway pattern.

---

## 3. Skill update spec (`AI-excel-addin/api/memory/workspace/notes/skills/build-model.md`)

### 3.1 Frontmatter (R1 S2 fix — verification gate)

The existing `build-model.md` frontmatter uses bare `mcp_servers: [model-engine, edgar-financials]`. **Pre-ship verification gate**: confirm the AI-excel-addin skill loader treats `mcp_servers` as full-server access (no per-tool allowlist required) by inspecting the loader (`AI-excel-addin/api/agent/skills/loader.py` and adjacent files). If allowlists ARE required, the frontmatter must explicitly list `build_model`, `get_model_insights`, `get_price_target` (and possibly `get_handoff`, `apply_patch_ops` if they appear in step 7b). If `mcp_servers` is server-level only, no allowlist needed.

After verification, add `portfolio-mcp` to `mcp_servers`:
```yaml
mcp_servers:
  - model-engine
  - edgar-financials
  - portfolio-mcp  # NEW — provides build_model (handoff path), get_model_insights, get_price_target
# allowed-tools (only if loader requires per-tool allowlist):
#   - portfolio-mcp.build_model
#   - portfolio-mcp.get_model_insights
#   - portfolio-mcp.get_price_target
```
Bump `version: '1.1'`.

### 3.2 Phase 1 step 2 — research-file detection (R1 B1 fix — collapse to delegation)

After the existing parallel pulls, the skill needs to know whether a research handoff is in scope. **Trust the tool, not memory**: do not branch the dispatch on memory_recall. Branch only on whether `research_file_id` is in scope at all.

> From `memory_recall` (and any handoff thread metadata returned), determine the **research_file_id** in scope.
> - **research_file_id present** → orchestrator path (step 4 calls `build_model(research_file_id=...)`). The tool auto-resolves the latest finalized handoff and surfaces `no_finalized_handoff` in the response if none exists.
> - **No research_file_id** → legacy raw build path (step 4 calls `model-engine.model_build(...)` with the full param assembly). Skip step 7b.

This eliminates the silent-bypass case where memory_recall missed a finalized handoff that exists server-side. It also drops the now-unnecessary `get_handoff` confirm call.

### 3.3 Phase 2 step 4 — dispatch (R1 S1 fix — error path ordering)

**Orchestrator path (research_file_id in scope)**:
```
build_model(
  research_file_id=<from step 2>,
  handoff_id=<optional; tool auto-resolves latest finalized if omitted>,
  model_build_context_id=<optional; orchestrator constructs fresh otherwise>,
)
```
Skill must inspect the response in this order (the order matters — `no_finalized_handoff` ALSO carries `status: "error"`, so it would be shadowed by a generic status check):

1. **`result.get("no_finalized_handoff")` truthy** → no finalized handoff exists for this research_file. Surface: *"No finalized handoff for research_file_id={rfi}. Run `finalize_handoff(research_file_id={rfi})` before building, or build outside the handoff via the legacy raw path explicitly."* Stop. Do NOT silently fall through to legacy.
2. **`result["status"] == "error"`** (other reasons) → surface `result["error"]` verbatim and stop. (Includes deleted/expired MBC, build failures, gateway errors.)
3. **`result["build_status"] == "success" && result["annotation_status"] == "error"`** → build succeeded; flag `result["annotation_error"]` in the Phase 4 summary as a known gap. Do NOT instruct the analyst to "re_annotate later" — no MCP tool exposes that today.
4. **`result["status"] == "success" && result["build_status"] == "success"`** → proceed to validation.

**Legacy path (no research_file_id)**: keep existing `model-engine.model_build(...)` 12-param call unchanged. Add a one-line note in skill prose: *"Without a research handoff, MI/PT are not emitted; subsequent `get_model_insights` / `get_price_target` calls will return not-found responses."*

### 3.4 Phase 3 step 6 — annotation
- **Orchestrator path**: skip — annotation already happened inside `build_model`. Surface `result["annotation_status"]` + `result.get("annotation_error")` in the Phase 4 summary. (Note: existing tool response does NOT carry `assumptions_skipped` — `actions/research.py:759-777` drops it. Do not reference that field in the summary unless the response contract is later expanded.)
- **Legacy path**: skip — no handoff means no annotation context.

Drop the existing `annotate_model_with_research(...)` call entirely. (It's redundant on the orchestrator path and inert on the legacy path.) Document that `annotate_model_with_research` MCP is reserved for re-annotation flows that don't have a skill wrapper yet.

### 3.5 Phase 4 step 7b — post-build typed-channel surface (R1 B2 fix — non-critical side effect, R1 N1 fix — placeholder)

Only on the orchestrator path. **MI/PT emission is a non-critical orchestrator side effect** per Plan #6 §11.1 Scenario 10 — a build can succeed with no MI or PT row written if the emit hook raised internally. The skill must handle empty/not-found responses gracefully and surface the gap, not silently omit.

Use `research_file_id` returned in the build response:
```
rfi = result["research_file_id"]
mi = get_model_insights(research_file_id=rfi, format="agent")
pt = get_price_target(research_file_id=rfi, format="agent")
```
- `get_model_insights` returns the latest snapshot when `model_insights_id` is omitted — no `latest=true` param exists.
- `get_price_target` returns the upserted PT for the latest finalized handoff or a typed not-found response.

Note on response shapes (verified against `mcp_tools/research.py:466-525,609-624,758-806`):
- **Success** (snapshot returned): `{status: "success", format: "agent", snapshot: {...}, flags: [{"flag": "...", "severity": "...", "message": "..."}, ...]}` — `flags` is `list[dict]`, NOT a list of strings or an object.
- **MI not-found** (`get_model_insights` `format="agent"`): typed error envelope from `_map_action_error` — `{status: "error", not_found: true, error_type: "model_insights_not_found", ...}`. No `format` or `flags` field (asymmetry vs. PT).
- **PT not-found** (`get_price_target` `format="agent"`): typed error envelope WITH `format: "agent"` + `flags` list containing `{"flag": "price_target_missing", "severity": "warning", ...}`.

Flag-membership pattern (use this exact form in the skill prose):
```
flag_names = {f.get("flag") for f in result.get("flags", []) if isinstance(f, dict)}
if "model_insights_fresh" in flag_names:
    ...
```

Surface in the build summary:
- **MI success + `"model_insights_fresh"` in `flag_names`**: list `snapshot.handoff_patch_suggestions[]` as proposed `HandoffPatchOp`s the analyst can review. **Never auto-apply.** If `"patch_suggestions_pending"` in `flag_names`, prompt the analyst.
- **MI success + `"model_insights_stale"` in `flag_names`**: surface the staleness directly with a note pointing at when `snapshot.as_of` was emitted.
- **MI not-found** (`result["status"] == "error"` and `result.get("error_type") == "model_insights_not_found"`): surface as a build summary note — *"ModelInsights emit returned no snapshot for this build. Orchestrator emit may have failed silently — check server logs for `model_insights_emit_failed`. Build itself succeeded."*
- **PT success**: display `snapshot.ranges.{low, mid, high}`, `snapshot.confidence`, `snapshot.implied_return_pct` in the summary table.
- **PT not-found** (`result["status"] == "error"` and (`result.get("error_type") == "price_target_not_found"` OR `"price_target_missing"` in `flag_names`)): surface as a build summary note — *"PriceTarget not present for this handoff. May indicate emit failure or no scenario data."*

### 3.6 New "## Typed Outputs" section (R1 B2 fix — accurate atomicity claim)

Single short paragraph after Phase 4:
> The orchestrator path is the typed feedback channel. Build + annotate run atomically server-side. ModelInsights + PriceTarget emission is a **non-critical orchestrator side effect** — the build succeeds even if emit fails, and the skill surfaces missing MI/PT as build summary notes (per step 7b). `ModelInsights` rows are appended (many-per-handoff snapshots, latest-read selects); `PriceTarget` is upserted (one per handoff). `Thesis.model_ref` updates server-side on every successful build. `handoff_patch_suggestions` surfaced in step 7b are proposals only — analyst reviews and runs `apply_patch_ops(research_file_id, ops=[...])` to commit them. Without a handoff, none of this applies.

---

## 4. Concurrency + storage shape (R1 S4 fix — corrected MI vs PT semantics)

Three writes happen on every orchestrator-path build:
- **Workbook**: overwrite at `repo.exports_dir() / model_{research_file_id}_v{version}.xlsx`. Last-writer-wins openpyxl write; concurrent processes race on the .xlsx file.
- **PriceTarget**: `upsert_price_target(research_file_id, handoff_id, pt)` at `model_insights_service.py:51` — single row per handoff, last-writer-wins on field values (the `price_target_id` UUIDv5 is stable, so the row identity doesn't change).
- **ModelInsights**: `record_insights(...)` → `repo.insert_model_insights(...)` at `model_insights_service.py:30,36` — **append**, many snapshots per handoff. Latest-read selection (`latest_insights_for_handoff(handoff_id)`) is race-sensitive: two concurrent emits both insert rows; the read picks whichever has the later timestamp. Prior snapshots persist, NOT overwritten.

Plan #6 §11.1 Scenario 6 covers idempotent MI/PT REPLAY (same payload re-emitted); Scenario 9 covers OCC interleaving with `apply_patch_ops`. Neither covers concurrent rebuilds for the same handoff.

**Decision (v1)**: ship as documented, no advisory lock.
- Workbook race: last process to close the file wins. Acceptable since the build is deterministic given the same MBC + financials snapshot.
- PriceTarget upsert: trivially convergent.
- ModelInsights append: both rows persist; the latest-read consumer (`get_model_insights`) returns whichever row has the later `as_of`. No data loss.

Skill prose adds a one-line warning: *"Concurrent builds for the same handoff race on the .xlsx write and append two ModelInsights snapshots. The latest snapshot wins for read consumers, but both persist. Coordinate sessions or use a fresh handoff version if you need a clean snapshot."*

If product evidence later shows races causing real loss, file a follow-on for a per-handoff build advisory lock. Out of scope here — behavior is documented and convergent, not silent.

---

## 5. SKILL_CONTRACT_MAP.md update

Flip `build-model` row from `~ partial` to `✓ built`. New cell text:
> When a finalized research handoff is in memory: dispatches via `portfolio-mcp.build_model(research_file_id, handoff_id?, model_build_context_id?)` — orchestrator handles build + annotation atomically server-side, then attempts ModelInsights + PriceTarget emission as a non-critical post-build side effect (per Plan #6 §11.1 Scenario 10). Skill surfaces emitted MI suggestions + PT ranges in step 7b, or the missing-MI/PT gap if emit failed. Without handoff: legacy `model-engine.model_build(...)` raw-engine path; no typed-channel emission. Updates `Thesis.model_ref` server-side on every successful build.

---

## 6. Tests (R1 S5 fix — harness discovery first)

### 6.1 risk_module
The portfolio-mcp `build_model` tool already has unit + integration coverage. No new tests needed — no code changes here.

### 6.2 AI-excel-addin (harness-tiered)

**Step 1 — discover existing skill-test harness**: before authoring, check `AI-excel-addin/tests/skill_evals/` and `tests/test_skills*` for prior patterns. If a static loader test exists (parses skill frontmatter and asserts MCP server access via the actual loader), use it. If a runtime harness exists (loads the skill, sends a synthetic memory_recall payload, asserts the right MCP tool was called), use it.

**Step 2 — write the strongest test the available harness supports**:
- **Best (runtime harness available)**: a skill-runner test that seeds a fake memory_recall returning `research_file_id=42`, runs the skill's Phase 1+2, and asserts `portfolio-mcp.build_model` was invoked with `research_file_id=42`. Asserts on the orchestrator-vs-legacy dispatch decision.
- **Mid (static loader test pattern exists)**: parse the actual skill frontmatter through the loader; assert the loader exposes `portfolio-mcp.build_model` to this skill. Stronger than prose-shape because it goes through the real loader contract.
- **Floor (no harness)**: prose-shape test at `tests/skill_evals/test_build_model_handoff_dispatch.py` — assert frontmatter parses with `portfolio-mcp` in `mcp_servers`; assert prose contains `portfolio-mcp.build_model` token; assert the no-fallback rule string is present for non-finalized case. Cheap, catches regressions in the rewire.

The implementation sub-phase A includes the harness-discovery step before authoring the test.

---

## 7. Files to touch

### 7.1 AI-excel-addin
- `api/memory/workspace/notes/skills/build-model.md` — frontmatter + Phase 1 step 2 + Phase 2 step 4 + Phase 3 step 6 + Phase 4 step 7b + Typed Outputs section + version bump
- `docs/SKILL_CONTRACT_MAP.md` — flip `build-model` row to `✓ built`
- `docs/TODO.md` — mark item #22 complete
- new or updated skill-level test at the strongest tier the AI-excel-addin harness supports — exact file path and tier chosen during sub-phase A's harness discovery (§6.2). Floor: prose-shape test; ceiling: runtime dispatch test.

### 7.2 risk_module
- `docs/planning/BUILD_MODEL_FOR_HANDOFF_MCP_PLAN.md` (this doc, R4 PASS)
- `docs/planning/INVESTMENT_SCHEMA_UNIFICATION_PLAN.md` — one-line follow-on note pointing to this plan

### 7.3 No changes needed
- `risk_module/actions/research.py` (existing `build_model` ships)
- `risk_module/mcp_tools/research.py` (existing wrapper ships)
- `risk_module/mcp_server.py` (already registered at line 2633)
- `risk_module/services/research_gateway.py` (no new typed errors)
- `AI-excel-addin/mcp_servers/model_engine_mcp_server.py` (legacy `model_build` stays untouched)
- `AI-excel-addin/api/research/build_model_orchestrator.py` (orchestrator already does the work)
- `AI-excel-addin/api/research/routes.py` (HTTP route exists)

---

## 8. Sub-phase breakdown

| # | Sub-phase | Scope | Estimate | Depends on |
|---|-----------|-------|----------|------------|
| A | Skill prose + frontmatter | `build-model.md` Phase 1-4 changes; smoke test | ~0.4 day | — |
| B | Doc alignment | `SKILL_CONTRACT_MAP.md` row flip; TODO #22 close; master plan follow-on note; ship-doc commit | ~0.1 day | A |

Total: ~0.5 day.

---

## 9. Risks + non-goals

### 9.1 Risks
- **MBC freshness**: orchestrator constructs a fresh MBC inline via `get_model_build_context(research_file_id)` on every build call. If analyst patched the handoff between builds, the rebuild picks up the patched state automatically (matches Plan #5 §3 / Plan #6 §11.1 Scenario 9).
- **Deleted/expired MBC**: if the analyst pins `model_build_context_id` and that row was reaped by `delete_expired_mbcs`, the existing `build_model` tool returns `{status: "error", error: "..."}` from the gateway pass-through. Skill prose §3.3 ordered-check #2 surfaces the error and stops; user retries without `model_build_context_id` to let the orchestrator construct fresh.
- **Annotation failure on orchestrator path**: build still succeeds; `annotation_status: "error"` + `annotation_error` field are non-fatal and surfaced in Phase 4 summary. No "re_annotate later" recommendation in v1 — no MCP tool to call.
- **MI emit failure (non-critical)**: per Plan #6 §11.1 Scenario 10, the orchestrator's emit hook is wrapped in try/except and logs `model_insights_emit_failed` without failing the build. Skill prose §3.5 surfaces the missing-MI case in the build summary explicitly so the gap isn't silent.
- **Concurrent rebuilds**: documented as last-writer-wins on workbook + PT, append on MI (§4). Convergent, no data loss. Acceptable for v1.
- **Stale MI/PT after off-skill mutations**: `apply_patch_ops` does not invalidate MI snapshots — they persist with `as_of` timestamps. Surface staleness by detecting `"model_insights_stale"` in the `flag_names` set (per §3.5 — flags are `list[dict]` keyed by `"flag"`). Skill respects the flag.

### 9.2 Non-goals
- New MCP tools, new typed errors, new HTTP routes (none needed — full path exists).
- Frontend "build for handoff" trigger button.
- Cross-user handoff sharing.
- Auto-finalize-then-build flow.
- `re_annotate` MCP exposure (file separately if a frontend button or skill needs it).
- Per-handoff build advisory lock (file separately if real races are observed).

---

## 10. Success criteria

1. `build-model.md` frontmatter lists `portfolio-mcp` (with allowlist if loader requires); smoke test asserts presence at the strongest tier the AI-excel-addin harness supports.
2. Given a `research_file_id` in memory with a finalized handoff, skill calls `portfolio-mcp.build_model(research_file_id=...)` and surfaces post-build MI suggestions + PT ranges in the summary. If MI or PT is absent (emit failed), the gap is surfaced as a build summary note, not silently omitted.
3. Given a `research_file_id` in memory with NO finalized handoff, skill stops with the finalize hint — no fallback to legacy raw build.
4. Given no `research_file_id` in memory, skill calls legacy `model-engine.model_build(...)` with the full param assembly and skips the MI/PT surfacing in step 7b.
5. Skill response handling order matches §3.3 (no_finalized_handoff → status==error → annotation_status==error → success).
6. `SKILL_CONTRACT_MAP.md` `build-model` row reads `✓ built`; AI-excel-addin TODO item #22 closed.
7. Real-ticker E2E run (e.g., AAPL with finalized handoff) confirms MI + PT visible via subsequent `get_model_insights` / `get_price_target` calls; concurrent rebuilds produce two MI snapshots without data loss.

---

## 11. Open questions for Codex R3 review

1. §3.1 frontmatter verification gate — is naming the loader file inline (`AI-excel-addin/api/agent/skills/loader.py`) sufficient, or does the plan need to commit to a specific format (`mcp_servers` vs `servers + allowed-tools`) without inspecting the loader first?
2. §6.2 harness-tiered tests — the discovery step adds dependence on what's in AI-excel-addin tests today. If discovery turns up nothing, is the prose-shape floor good enough to ship, or does the plan need to require a runtime harness be authored as part of this work?

---

*Authored 2026-04-28. R0: 5B/5S/1N → R1 pivot. R1: 2B/5S/1N → R2 tightened. R2: 0B/4S/0N → R3 polished. R3: 0B/1S/2N → R4 corrected flag shape. R4 PASS 2026-04-28.*
