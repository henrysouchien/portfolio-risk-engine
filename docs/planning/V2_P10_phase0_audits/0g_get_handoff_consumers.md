# V2.P10 Phase 0g - `get_handoff` Consumers

## Scope Summary

This artifact classifies existing `get_handoff` callers before the Phase 2c split:

- Summary consumers move to `mcp__research-mcp__get_handoff_summary`.
- Full-artifact consumers move to `mcp__portfolio-mcp__get_handoff_full`.
- Tests that assert artifact presence need to become summary/full-specific tests.
- `_normalize_handoff_summary` / `_normalize_handoff_artifact_summary` need a new projected summary helper that strips `artifact`.

The audit covers `~/Documents/Jupyter` with the required exclusions plus manual review of persisted records, scripts, repo-local skill evals, and frontend hooks. It is investigation-only; no code was changed.

## Methodology

Required discovery grep:

```bash
rg -n "get_handoff|get_handoff_summary|get_handoff_full|mcp__.*get_handoff|artifact_summary|artifactSummary" \
  ~/Documents/Jupyter \
  --glob '!**/.claude/**' --glob '!**/agents/**' --glob '!**/__pycache__/**' \
  --glob '!**/node_modules/**' --glob '!**/.git/**' --glob '!**/-dist/**'
```

Manual review commands/surfaces:

```bash
rg -n "get_handoff|get_handoff_summary|get_handoff_full|artifact_summary|artifactSummary" \
  ~/Documents/Jupyter/AI-excel-addin/api/memory/workspace/notes/skills \
  ~/Documents/Jupyter/AI-excel-addin/tests/skill_evals \
  --glob '!**/.claude/**' --glob '!**/agents/**' --glob '!**/__pycache__/**' \
  --glob '!**/node_modules/**' --glob '!**/.git/**' --glob '!**/-dist/**'

rg -n "get_handoff|filings_search|transcripts_search|filings_list|transcripts_list|mcp__portfolio-mcp__" \
  ~/Documents/Jupyter/AI-excel-addin/scripts ~/Documents/Jupyter/risk_module/scripts \
  --glob '!**/.claude/**' --glob '!**/agents/**' --glob '!**/__pycache__/**' \
  --glob '!**/node_modules/**' --glob '!**/.git/**' --glob '!**/-dist/**'

sqlite3 ~/Documents/Jupyter/AI-excel-addin/api/logs/cost.db \
  "SELECT server, tool, COUNT(*) FROM tool_timing WHERE tool='get_handoff' GROUP BY server, tool;"
```

Targeted file reads used `nl -ba`/`sed` around key matches in `risk_module/actions/research.py`, `risk_module/mcp_server.py`, `risk_module/mcp_tools/research.py`, AI-excel research services/routes, and frontend handoff views.

## Findings

1. The current MCP `get_handoff` shape is mixed: list mode returns summaries, while single mode returns a normalized payload that includes the full `artifact` body when present.
2. `risk_module/tests/test_research_mcp.py:884+` and `:1195+` are confirmed full-artifact consumers.
3. AI-excel HTTP routes, model-build services, editorial context, annotation, and frontend review views are full-artifact consumers of repository/API handoffs. These are not all MCP cutover sites, but they prove full body access must continue somewhere.
4. `risk_module/core/research_flags.py` is a summary-tolerant consumer: it prefers `artifact_summary` and falls back to `artifact` only when summary fields are absent.
5. Persisted JSONL records include actual `get_handoff` calls, and `tool_timing` has 6 `portfolio-mcp/get_handoff` rows. These cannot be fully classified from timing rows alone.
6. No `get_handoff` references were found in `AI-excel-addin/scripts/`, `risk_module/scripts/`, repo-local skill notes, or skill evals.

## Master Table

| Type | Meaning | Count / surfaces | Phase 2c action |
|---|---|---:|---|
| (a) Summary consumer | Needs metadata and projected `artifact_summary`, not full body | `risk_module/actions/research.py` list mode; `risk_module/core/research_flags.py`; some status checks | Migrate MCP usage to `mcp__research-mcp__get_handoff_summary`; use new projection helper. |
| (b) Full-artifact consumer | Needs actual `artifact` body | MCP single mode, HTTP/API handoff detail/download, model build, editorial, frontend review | Migrate MCP tool callers to `mcp__portfolio-mcp__get_handoff_full`; leave repository/API internals full. |
| (c) Test asserting artifact presence | Tests shape or body access | `risk_module/tests/test_research_mcp.py`; AI-excel research tests; frontend tests | Split into summary/full tests or update to the appropriate variant. |
| (d) Documentation reference | Docs/plans only | Risk docs, AI docs, out-of-scope workspace docs | Update active design/reference docs; preserve archive docs unless intentionally backfilled. |
| (e) Normalization helper | Current helper includes `artifact`; artifact-summary helper derives counts from full body | `risk_module/actions/research.py:1148,1180` | Add `_project_handoff_summary` with whitelist/caps and no `artifact`. |
| AMBIGUOUS / false positive | Grep matched helper names or records without enough shape info | `_get_handoff_id`, `tool_timing`, some persisted records | Human review or migration-script classification by payload/input. |

## Per-Caller Classification Table

| Path | Line | Type | Rationale | Phase 2c action |
|---|---:|---|---|---|
| `risk_module/actions/research.py` | 573-604 | AMBIGUOUS (a/b) | Action function serves both list-summary and single-full modes. | Split or wrap into `get_handoff_summary` and `get_handoff_full`; avoid one projected function accidentally serving full artifacts. |
| `risk_module/actions/research.py` | 589 | (b) | Single mode returns normalized payload, currently including `artifact` if present. | Use for full variant only. |
| `risk_module/actions/research.py` | 597-604 | (a) | List mode returns normalized summaries for all handoffs. | Use projected summary helper and route to research-mcp summary variant. |
| `risk_module/actions/research.py` | 1148 | (e) | `_normalize_handoff_summary` currently includes `artifact` at line 1173. | Add `_project_handoff_summary` that strips artifact and applies whitelist/caps. |
| `risk_module/actions/research.py` | 1180 | (e) | `_normalize_handoff_artifact_summary` derives compact fields from full artifact. | Reuse for summary projection only after enforcing safe output shape. |
| `risk_module/actions/research.py` | 407,460,871 | false positive | `_get_handoff_id` helper resolves active handoff id; not a `get_handoff` consumer. | No Phase 2c rename. |
| `risk_module/mcp_tools/research.py` | 310,318,920 | (b) | MCP wrapper forwards current mixed `get_handoff` action and exports the tool. | Replace/split exports into summary/full wrappers. |
| `risk_module/mcp_server.py` | 130,2778,2784 | (b) | Portfolio-mcp imports/registers `get_handoff` today. | Rename portfolio tool to `get_handoff_full`; add research-mcp summary registration in research server. |
| `risk_module/agent/registry.py` | 1073,1079,1445 | AMBIGUOUS | Agent registry exposes the current mixed action. | Decide whether registry exposes both variants or remains a full-only local helper. |
| `risk_module/core/research_flags.py` | 268,287,311 | (a) | Reads `artifact_summary` first and falls back to `artifact`. | Summary variant should include these whitelisted summary fields so flags do not need body access. |
| `AI-excel-addin/api/agent/shared/server_policies.py` | 229 | (b) | Current portfolio-mcp policy exposes `get_handoff`. | Replace with `get_handoff_full` in portfolio policy and add `get_handoff_summary` to research-mcp policy. |
| `AI-excel-addin/tests/test_server_policy_drift.py` | 390 | (c) | Expected policy list includes current `get_handoff`. | Update expected policy lists for both new variants. |
| `risk_module/tests/test_research_mcp.py` | 842,862,875 | (c)/(a) | List-mode normalization test expects summaries. | Convert to summary-variant test and assert no `artifact`. |
| `risk_module/tests/test_research_mcp.py` | 884,893,905,906,909,918 | (c)/(b) | Confirmed full-artifact action consumer; asserts artifact and snapshot fields. | Convert to `get_handoff_full` test. |
| `risk_module/tests/test_research_mcp.py` | 947,948 | (c)/(e) | Tests derived `artifact_summary` counts. | Cover both projected summary caps and full-derived summary. |
| `risk_module/tests/test_research_mcp.py` | 1195,1199,1203 | (c)/(b) | Confirmed full-artifact MCP consumer. | Rename expected MCP tool to `get_handoff_full`. |
| `risk_module/tests/test_research_mcp.py` | 1443,1447 | (c) | Error-path test for MCP infrastructure handling. | Duplicate or parameterize across summary/full variants if both use same error path. |
| `risk_module/tests/test_research_mcp.py` | 1512,1515,1519,1533 | (c) | Registry forwarding tests for current mixed action. | Update once registry variant decision is made. |
| `risk_module/tests/routes/test_research_content.py` | 410,437 | (c)/(b) | Route tests for research content handoff handling. | Keep full API expectation unless route intentionally uses summary projection. |
| `risk_module/tests/test_risk_client.py` | 23 | (c) | Client surface imports/uses handoff tooling. | Update only if client exposes MCP variants. |
| `AI-excel-addin/api/research/routes.py` | 247-272 | (b) | `_serialize_handoff` includes `artifact` and `artifactSummary`. | Leave full for HTTP detail/download routes. |
| `AI-excel-addin/api/research/routes.py` | 1485 | (a) | Editorial brief endpoint checks existence/status only. | Could use summary/status shape; no MCP rename unless converted to MCP. |
| `AI-excel-addin/api/research/routes.py` | 1536,1541 | (b) | HTTP `GET /handoffs/{handoff_id}` returns serialized full artifact. | Preserve full API behavior. |
| `AI-excel-addin/api/research/routes.py` | 1624 | (b) | Download route needs the full artifact/model export context. | Preserve full behavior. |
| `AI-excel-addin/api/research/repository.py` | 2631,2687,2995,3366,3390 | (b) | Repository storage access returns full handoff rows including artifact. | No MCP rename; ensure callers choose summary/full at boundary. |
| `AI-excel-addin/api/research/build_model_orchestrator.py` | 106,219,310 | (b) | Model build/annotation needs full handoff artifact. | Keep full artifact path; if MCP-backed, use `get_handoff_full`. |
| `AI-excel-addin/api/research/diligence_service.py` | 181 | (b) | Diligence updates mutate full handoff artifact state. | Keep full. |
| `AI-excel-addin/api/research/editorial/context.py` | 45 | (b) | Editorial context builds from full artifact. | Keep full. |
| `AI-excel-addin/api/research/handoff.py` | 565,797 | (b) | Handoff export/serialization includes full artifact and summary. | Keep full for service internals. |
| `AI-excel-addin/api/research/mbc_service.py` | 131 | (b) | Model-build context loads finalized full handoff. | Keep full. |
| `AI-excel-addin/api/research/model_insights_service.py` | 53 | (b) | Model insights extracts artifact from handoff row. | Keep full. |
| `AI-excel-addin/schema/annotate.py` | 59 | (b) | Annotation context loads handoff and extracts full artifact. | Keep full. |
| `AI-excel-addin/tests/api/research/test_handoff_migration.py` | 38,123,143,160,239,259,313 | (c)/(b) | Repository migration tests assert artifact/full storage behavior. | No MCP rename unless fixtures mention tool names; keep full artifact assertions. |
| `AI-excel-addin/tests/api/research/test_handoff_service.py` | 270 | (c)/(b) | Handoff service full-artifact behavior. | Keep full. |
| `AI-excel-addin/tests/api/research/test_model_insights_service.py` | 243 | (c)/(b) | Model insights requires artifact. | Keep full. |
| `AI-excel-addin/tests/api/research/test_repository_handoff_builders.py` | 87,256 | (c)/(b) | Repository handoff builder artifact fixtures. | Keep full. |
| `AI-excel-addin/tests/api/research/test_start_research_from_idea.py` | 336 | (c)/(b) | Research start flow validates handoff artifact path. | Keep full. |
| `AI-excel-addin/tests/api/research/test_update_handoff_section.py` | 73 | (c)/(b) | Section update test needs artifact state. | Keep full. |
| `AI-excel-addin/tests/integration/test_investment_schema_spine_e2e.py` | 215,257 | (c)/(b) | Integration test uses repository and MCP `get_handoff`; the MCP call is full-artifact. | MCP call should migrate to `get_handoff_full`. |
| `AI-excel-addin/tests/research/editorial/test_context.py` | 66,88,98,106,125,142,153 | (c)/(b) | Editorial context fixture uses full artifact. | Keep full. |
| `AI-excel-addin/tests/research/editorial/test_service.py` | 143 | (c)/(b) | Editorial service fixture uses full handoff. | Keep full. |
| `AI-excel-addin/tests/test_annotate.py` | 75 | (c)/(b) | Annotation test needs artifact. | Keep full. |
| `AI-excel-addin/tests/test_build_model_orchestrator.py` | 96 | (c)/(b) | Build model orchestrator requires full artifact. | Keep full. |
| `AI-excel-addin/tests/test_research_handoff.py` | 118,135,160,161 | (c)/(b) | Handoff service/export tests use artifact and summary. | Keep full; add summary projection tests separately if needed. |
| `AI-excel-addin/tests/test_research_prepopulate.py` | 39 | (c) | Prepopulate test touches handoff summary/artifact fixture. | Classify by fixture use before editing. |
| `AI-excel-addin/tests/test_research_routes.py` | 382 | (c)/(b) | Route test for handoff payload. | Preserve full API behavior. |
| `risk_module/frontend/packages/connectors/src/features/external/hooks/useHandoff.ts` | 53 | (b) | Normalizer stores `artifact` and `artifactSummary`. | Keep full API hook for handoff review. |
| `risk_module/frontend/packages/connectors/src/stores/researchStore.ts` | 171 | (b) | Store type includes `artifact` and `artifactSummary`. | Keep full API shape. |
| `risk_module/frontend/packages/ui/src/components/research/HandoffReviewView.tsx` | 106,107,131,134 | (b) | UI reads full artifact fields including sources/assumptions/thesis. | Keep full route. |
| `risk_module/docs/interfaces/mcp.md` | 104 | (d) | MCP documentation lists current `get_handoff`. | Update active interface docs with summary/full split. |
| `risk_module/docs/research/hank-capabilities-inventory.md` | 131,260,483,487 | (d) | Capability inventory references current tool. | Update if active; otherwise archive. |
| `risk_module/docs/planning/V2_P10_RESEARCH_MCP_SPLIT_PLAN.md` | multiple | (d) | Active split plan. | Keep aligned with final cutover design. |
| Other `risk_module/docs/planning/*.md` hits | multiple | (d) | Older design/planning references. | Update active docs only; preserve completed docs unless backfilling. |
| `AI-excel-addin/docs/design/completed/todo-40i-server-policy-drift-task.md` | 71 | (d) | Completed design note. | Preserve unless historical docs are being backfilled. |
| `risk_module-editorial-pipeplan/docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE.md` | 281,432 | (d), out-of-scope | Parallel/archive planning workspace documentation. | Preserve unchanged. |
| `risk_module-equity-workspace/docs/planning/RESEARCH_WORKSPACE_ARCHITECTURE.md` | 281,432 | (d), out-of-scope | Parallel/archive planning workspace documentation. | Preserve unchanged. |

## Manual Review Beyond Grep

| Surface checked | Result | Phase 2c / Phase 0h action |
|---|---|---|
| Persisted prompt/event store: `AI-excel-addin/api/logs/chat.jsonl` | Manual search found 18 `tool_name`/`tool` records for `get_handoff`. | Migration must inspect `tool_input`: no `handoff_id` implies summary/list; explicit `handoff_id` implies full. |
| Persisted session logs: `AI-excel-addin/api/chat_logs/*.jsonl` | Several sessions contain `get_handoff` records: counts observed included 4, 2, 4, and 2 across matching session files. | Include representative fixtures for both start and complete events. |
| Persisted `AgentSessionLog`: `AI-excel-addin/api/sessions/analyst/agentsess_analyst_henry.jsonl` | Phase 1 tool records exist; `get_handoff` should be covered by the same structured migration approach. | Walk durable session logs, not only chat logs. |
| SQLite `tool_timing`: `AI-excel-addin/api/logs/cost.db` | `portfolio-mcp|get_handoff|6` rows. | Timing rows lack input/result shape, so migration is AMBIGUOUS. Recommended policy: either keep as historical `get_handoff`, or map to `get_handoff_full` with release-note caveat. |
| `risk_module/scripts/` and `AI-excel-addin/scripts/` | Targeted grep found no `get_handoff` hits. | No script caller action found. |
| Repo-local skill notes/evals: `AI-excel-addin/api/memory/workspace/notes/skills/`, `AI-excel-addin/tests/skill_evals/` | Targeted grep found no `get_handoff` / `artifact_summary` / `artifactSummary` hits. | No skill/eval action found. |
| Frontend hooks and views | `useHandoff.ts`, `researchStore.ts`, and `HandoffReviewView.tsx` are full-artifact consumers. | Do not migrate these to summary unless a separate summary-only UI is designed. |

## Persisted-Record Migration Notes

The migration cannot be a flat `get_handoff -> get_handoff_summary` rename.

Suggested classifier:

| Record shape | Migration |
|---|---|
| `tool_name == "get_handoff"` and `tool_input.handoff_id` is absent/null | `get_handoff_summary` on `research-mcp`, if the result is list/summary-shaped. |
| `tool_name == "get_handoff"` and `tool_input.handoff_id` is present | `get_handoff_full` on `portfolio-mcp`. |
| `tool_call_complete` result contains top-level `artifact` | `get_handoff_full` on `portfolio-mcp`. |
| `tool_call_complete` result contains `handoffs` list and no full `artifact` entries | `get_handoff_summary` on `research-mcp`. |
| `tool_timing` row only has `server/tool` | AMBIGUOUS. Needs policy because input/result are unavailable. |

## Open Questions For User

| Question | Why it matters |
|---|---|
| For `tool_timing` rows with only `portfolio-mcp/get_handoff`, should Phase 0h rewrite to `get_handoff_full`, preserve historical `get_handoff`, or split only when paired JSONL evidence exists? | The timing table alone cannot distinguish summary/list from full/single calls. |
| Should `risk_module/agent/registry.py` expose both new handoff variants, or only the full variant? | Registry behavior determines tests and local agent surface. |
| Should completed docs be preserved as historical snapshots or backfilled to new names? | There are many completed planning docs that reference old `get_handoff`. |

## Phase 1+ Implications

1. Phase 2c must introduce a true summary projection helper, not reuse `_normalize_handoff_summary` as-is. The current helper includes `artifact` when present.
2. Full artifact behavior must remain available through `get_handoff_full` and existing HTTP/repository/frontend paths.
3. Migration fixtures should include both list-mode and single-mode `get_handoff` records, plus a timing-only row to validate the ambiguous policy.
4. Server policies and drift tests need coordinated updates with the MCP wrapper split.

## In-Scope But Flagged For Caution

| Item | Caution |
|---|---|
| `_normalize_handoff_summary` name | It sounds summary-only but currently includes the full artifact. The new projected helper should be visibly distinct. |
| Persisted timing rows | They lack enough data to classify summary vs full. Do not silently rewrite without an explicit policy. |
| Frontend handoff review | It is full-artifact by design. Moving it to summary would break expected UI behavior. |
| `_get_handoff_id` grep hits | These are false positives from the discovery regex and should not drive rename work. |
