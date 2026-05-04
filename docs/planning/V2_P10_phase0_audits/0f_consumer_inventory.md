# V2.P10 Phase 0f - Consumer Inventory

## Scope Summary

This artifact inventories consumers of the V2.P10 Phase 1 moved corpus tools:

- `filings_search`
- `transcripts_search`
- `filings_list`
- `transcripts_list`

It also inventories direct references to old MCP namespaced tool names such as `mcp__portfolio-mcp__filings_search`. The audit covers `~/Documents/Jupyter` with the required exclusions, then separately documents non-workspace surfaces that were not read. This is investigation-only; no code was changed.

## Methodology

Required greps run first:

```bash
rg -n "mcp__portfolio-mcp__filings_|mcp__portfolio-mcp__transcripts_|mcp__portfolio-mcp__get_handoff|mcp__portfolio-mcp__filings|mcp__portfolio-mcp__transcripts" \
  ~/Documents/Jupyter \
  --glob '!**/.claude/**' --glob '!**/agents/**' --glob '!**/__pycache__/**' \
  --glob '!**/node_modules/**' --glob '!**/.git/**' --glob '!**/-dist/**'

rg -n "filings_search|transcripts_search|filings_list|transcripts_list" \
  ~/Documents/Jupyter \
  --glob '!**/.claude/**' --glob '!**/agents/**' --glob '!**/__pycache__/**' \
  --glob '!**/node_modules/**' --glob '!**/.git/**' --glob '!**/-dist/**'
```

Follow-up targeted audits:

```bash
rg -n "_MCP_META_INJECT_SERVERS|_RESEARCH_AUTO_LOAD_SERVERS" \
  ~/Documents/Jupyter/AI-excel-addin ~/Documents/Jupyter/agent-gateway-dist \
  --glob '!**/.claude/**' --glob '!**/agents/**' --glob '!**/__pycache__/**' \
  --glob '!**/node_modules/**' --glob '!**/.git/**' --glob '!**/-dist/**'

rg -n "filings_search|transcripts_search|filings_list|transcripts_list|mcp__portfolio-mcp__" \
  ~/Documents/Jupyter/AI-excel-addin/scripts ~/Documents/Jupyter/risk_module/scripts \
  --glob '!**/.claude/**' --glob '!**/agents/**' --glob '!**/__pycache__/**' \
  --glob '!**/node_modules/**' --glob '!**/.git/**' --glob '!**/-dist/**'

sqlite3 ~/Documents/Jupyter/AI-excel-addin/api/logs/cost.db \
  "SELECT server, tool, COUNT(*) FROM tool_timing WHERE tool IN ('filings_search','transcripts_search','filings_list','transcripts_list','get_handoff') GROUP BY server, tool ORDER BY server, tool;"
```

The exact namespaced grep produced 19 lines across 5 files. The broader grep produced 355 lines across 43 files. Line counts below are grep lines, not unique semantic consumers.

## Findings

1. Direct old namespaced references are sparse and mostly documentation. Only one non-doc test directly names `mcp__portfolio-mcp__filings_search`.
2. Bare-name references are common because risk_module owns the actual corpus tools and tests. These are not all rename sites; many remain bare local functions after the server split.
3. `AI-excel-addin/api/agent/registry.py` does not exist in the current checkout. The registry category is represented by `risk_module/agent/registry.py`.
4. No Phase 1 tool references were found in `agent-gateway-dist/agent_gateway/tool_dispatcher.py`, `AI-excel-addin/packages/agent-gateway/tests/`, `agent-gateway-dist/tests/`, repo-local skill profiles, or skill evals.
5. Persisted records are a real migration surface even though the required workspace grep does not surface them. The durable logs use structured fields (`server`, `tool`, `tool_name`) rather than old namespaced strings.
6. `AI-excel-addin/api/logs/cost.db` has `tool_timing` rows for the moved tools under `portfolio-mcp`, plus 4 `filings_search` rows with blank/null server.

## Master Table

| Category | Count | Key paths | Cutover action |
|---|---:|---|---|
| Gateway dispatcher | 0 direct tool hits | `agent-gateway-dist/agent_gateway/tool_dispatcher.py:405-412`; package mirror same lines | No per-tool rename. Dynamic server lookup should route new `research-mcp` tools once policy/catalog/client surfaces are updated. |
| Agent registry | 8 | `risk_module/agent/registry.py:1357,1359,1363,1365,1502,1505,1506,1509` | Bare local registry entries. Do not blindly rename; decide whether local registry remains server-neutral. |
| Server policies | 4 | `AI-excel-addin/api/agent/shared/server_policies.py:217,219,285,287` | Move the four tools from portfolio-mcp policy to new `research-mcp` policy. |
| CHANNEL_TIERS | 0 direct tool hits | `AI-excel-addin/api/agent/shared/tool_catalog.py:41-58` | Add `research-mcp` to always tiers for intended channels. |
| MCP allowlists | 0 direct tool hits | `AI-excel-addin/api/mcp_client.py:17-31` | Add `research-mcp` to `ALLOWED_SERVERS`; consider timeout override if needed. |
| Dev CLI fixtures | 2 | `AI-excel-addin/tests/dev/test_chat_cli_citations.py:36,53` | Bare-name citation fixture. Usually no rename; add research-mcp prefixed case if CLI displays namespaced tools. |
| Repo-local skill profiles + evals | 0 | `AI-excel-addin/api/memory/workspace/notes/skills/`; `AI-excel-addin/tests/skill_evals/` | No Phase 1 hits found. |
| Agent profiles + ProfileConfig | 0 direct tool hits | `AI-excel-addin/api/agent/profiles/analyst.py`; `advisor.py`; `profiles/__init__.py` | Server visibility must be updated by server name, not by per-tool grep. |
| Package mirror tests | 0 direct tool hits | `AI-excel-addin/packages/agent-gateway/tests/`; `agent-gateway-dist/tests/` | No Phase 1 rename. Hidden-dependency meta-injection tests are covered in `0e_hidden_dependencies.md`. |
| Persisted chat/event replay records | Many structured hits | `AI-excel-addin/api/logs/chat.jsonl`; `api/chat_logs/*.jsonl`; `api/sessions/analyst/*.jsonl` | Migration script must rewrite structured `server/tool/tool_name` fields, not just namespaced strings. |
| Sub-agent transcript / `last_tool_name` | No Phase 1-specific literal hit found | `agent-gateway-dist/tests/test_task_registry.py:318,321,344,347`; durable session logs | Migration script should still inspect `last_tool_name` fields in JSONL/task state records. |
| Telemetry dashboards | 0 dashboard files found | `AI-excel-addin/api/dev_monitor.html:103`; `AI-excel-addin/api/main.py:733-738` | Local dev monitor reads tool timing summary. External dashboards require user audit. |
| `tool_timing` SQLite | 177 moved-tool rows plus 4 blank-server caution rows | `AI-excel-addin/api/logs/cost.db` table `tool_timing` | Phase 0h script must update `server='portfolio-mcp'` rows for moved tools to `research-mcp`; handle blank server rows explicitly. |
| Docs | 151 | See documentation inventory below | Update active docs and V2.P10 docs; preserve completed/archive docs unless intentionally backfilled. |
| Test/golden fixtures | 85 | `risk_module/tests/test_mcp_corpus_tools.py`; corpus canary/search/tool tests | Update tests that assert portfolio MCP registration. Bare domain tests should stay server-neutral. |
| Tests + fixtures, general code path | 38 | AI citation, policy, TUI, CLI tests | Update server-policy drift and namespaced citation fixtures; leave bare extractor tests unless behavior changes. |

## Exact Namespaced Grep Inventory

| Path | Lines | Classification | Description |
|---|---:|---|---|
| `AI-excel-addin/tests/agent/shared/test_citations.py` | 176 | Tests + fixtures, general code path | Tests `canonical_tool_name("mcp__portfolio-mcp__filings_search") -> "filings_search"`. Phase 1 should add or replace with `mcp__research-mcp__filings_search`. |
| `risk_module/docs/TODO.md` | 228 | Docs | Historical F47/F-corpus repro with `mcp__portfolio-mcp__filings_search`. Documentation reference. |
| `risk_module/docs/planning/CORPUS_PHASE1_PLAN.md` | 16 | Docs | Completed corpus rollout note referencing `mcp__portfolio-mcp__filings_search`. |
| `risk_module/docs/planning/V2_P10_RESEARCH_MCP_SPLIT_PLAN.md` | 134,211,751,769,777,960,976,1023,1030,1167,1226,1227,1257,1261,1270 | Docs | The active V2.P10 design/acceptance reference. Keep aligned with final migration semantics. |
| `risk_module/docs/planning/V2_P2_SLICE_A_PLAN.md` | 494 | Docs | Older citation-first plan example using portfolio-mcp namespaced filing tool. |

## Broad Grep Consumer Inventory

| Path | Lines | Classification | Description |
|---|---:|---|---|
| `AI-excel-addin/api/agent/interactive/runtime.py` | 462 | Hidden dependency / runtime | Comment for F56 workaround mentions `filings_search` availability. Covered in 0e. |
| `AI-excel-addin/api/agent/shared/citations.py` | 317,319,321,323 | Tests + fixtures, general code path | Bare tool-name citation extractors for the four moved tools. No server-specific rename. |
| `AI-excel-addin/api/agent/shared/server_policies.py` | 217,219,285,287 | Server policies | Current portfolio-mcp policy entries for moved tools. Phase 1 move to research-mcp. |
| `AI-excel-addin/api/research/policy.py` | 52,55 | Agent profiles + ProfileConfig | Research citation policy prompt lists corpus tools by bare name. No direct server rename; review prompt wording. |
| `AI-excel-addin/docs/TODO.md` | 665,675,680,684,687,714,715,733,735 | Docs | AI-excel planning/status references to corpus tools. |
| `AI-excel-addin/packages/agent-gateway-tui/tests/sources.test.ts` | 30,41 | Tests + fixtures, general code path | TUI source-rendering fixtures use bare `filings_search`. No server rename unless event shape changes. |
| `AI-excel-addin/tests/agent/interactive/test_citation_integration.py` | 126,134,151,174,199,225,246 | Tests + fixtures, general code path | Citation integration fixtures use bare corpus tool names. |
| `AI-excel-addin/tests/agent/shared/test_citation_validation_event_log.py` | 53 | Tests + fixtures, general code path | Event-log citation validation fixture. |
| `AI-excel-addin/tests/agent/shared/test_citation_validator.py` | 50 | Tests + fixtures, general code path | Citation validator fixture. |
| `AI-excel-addin/tests/agent/shared/test_citations.py` | 109,117,175,176,177,178,188,189,190,191,238,239,240,252,258,263,316,338,340 | Tests + fixtures, general code path | Canonicalization and extractor tests for moved tools. Namespaced case needs research-mcp coverage. |
| `AI-excel-addin/tests/dev/test_chat_cli_citations.py` | 36,53 | Dev CLI fixtures | CLI fixture uses `filings_search` in tool event/result records. |
| `AI-excel-addin/tests/test_research_context_policy.py` | 76,79 | Tests + fixtures, general code path | Verifies research context policy tool handling. |
| `AI-excel-addin/tests/test_server_policy_drift.py` | 377,379,473,475 | Server policies / tests | Expected portfolio-mcp policy lists include moved tools. Phase 1 update required. |
| `Edgar_updater/docs/TODO.md` | 230 | Out-of-scope docs | Documentation example, not consumer code. |
| `Edgar_updater/docs/plans/PLAN-section-parser-quick-wins.md` | 104 | Out-of-scope docs | Local variable `filings_list[0]`, not MCP consumer code. |
| `risk_module/CHANGELOG.md` | 43,56 | Docs | Historical release notes for corpus tools. |
| `risk_module/agent/registry.py` | 1357,1359,1363,1365,1502,1505,1506,1509 | Agent registry | Imports/registers moved corpus tools by bare name. |
| `risk_module/core/corpus/filings.py` | 51,259,323,448,450 | In-repo implementation | Core implementation internals. Not a consumer rename site. |
| `risk_module/core/corpus/merge.py` | 9 | In-repo implementation | Merge helper imports/list text; not a server consumer. |
| `risk_module/core/corpus/transcripts.py` | 33,177,314,316 | In-repo implementation | Core implementation internals. Not a consumer rename site. |
| `risk_module/docs/TODO.md` | 65,79,221,222,224,227,228,238,240,242,246,977,979,981,983,988,996,997,1015 | Docs | Mixed historical and active TODO references. Update only active V2.P10-relevant sections. |
| `risk_module/docs/interfaces/mcp.md` | 22,25,26,29 | Docs | MCP interface reference. Phase 1 should document research-mcp ownership. |
| `risk_module/docs/planning/CORPUS_ARCHITECTURE.md` | 361,399,410,446,475,518,519,566,570,593,597,613,628,631,654,782,791,815,844,850,879,885,910,1076,1383,1460,1463 | Docs | Corpus architecture references. |
| `risk_module/docs/planning/CORPUS_IMPL_PLAN.md` | 13,14,15,18,1205,1304,1317,1322,1327,1337,1363,1415,1458,1684,1689,1691,1695,1702,1703,1713,1720,1728,1746 | Docs | Original corpus implementation plan. |
| `risk_module/docs/planning/CORPUS_PHASE0_CANARY.md` | 152,158,182 | Docs | Corpus canary documentation. |
| `risk_module/docs/planning/CORPUS_PHASE0_CHECKPOINT.md` | 122,123,272,273 | Docs | Corpus checkpoint documentation. |
| `risk_module/docs/planning/CORPUS_PHASE1_PLAN.md` | 16 | Docs | Corpus Phase 1 plan reference. |
| `risk_module/docs/planning/CORPUS_PHASE1_VALIDATION_REPORT.md` | 130,146,148,153,159 | Docs | Corpus validation report references. |
| `risk_module/docs/planning/CORPUS_PHASE2_REPORT.md` | 187 | Docs | Corpus Phase 2 report reference. |
| `risk_module/docs/planning/CORPUS_PHASE3_REPORT.md` | 110 | Docs | Corpus Phase 3 report reference. |
| `risk_module/docs/planning/V2_P10_RESEARCH_MCP_SPLIT_PLAN.md` | 27,134,180,417,425,502,611,630,631,636,639,640,641,751,769,777,846,847,848,849,954,960,1020,1023,1167,1252,1256,1257,1261,1270,1347 | Docs | Active V2.P10 split plan. |
| `risk_module/docs/planning/V2_P2_CITATION_FIRST_QA_PLAN.md` | 18,49 | Docs | Citation-first QA plan references. |
| `risk_module/docs/planning/V2_P2_SLICE_A_PLAN.md` | 17,55,67,78,96,291,292,293,294,350,364,400,401,406,472,494 | Docs | V2.P2 Slice A plan references. |
| `risk_module/docs/planning/V2_P2_SLICE_B_PLAN.md` | 937 | Docs | V2.P2 Slice B reference. |
| `risk_module/mcp_server.py` | 179,181,183,185,1676,1699,1700,1745,1768,1781,1813,1849,1859,1879,1887,1905,1910,1911,1951,1975,1987,2021,2054,2063,2078 | In-repo implementation / server registration | Portfolio-mcp imports and exposes moved tools today. Phase 1 removes moved registrations from portfolio-mcp and re-registers on research-mcp. |
| `risk_module/mcp_tools/corpus/filings.py` | 8,10,19,58,59,103,131,144,180,229,240,246,270 | In-repo implementation | Tool wrapper implementation. Phase 1 may move registration, not necessarily implementation. |
| `risk_module/mcp_tools/corpus/transcripts.py` | 8,10,19,49,54,55,97,126,138,176,215,225,231,248 | In-repo implementation | Tool wrapper implementation. Phase 1 may move registration, not necessarily implementation. |
| `risk_module/tests/canary/test_corpus_canary.py` | 22,23,75,94,110,119,144,147,161 | Test/golden fixtures | Corpus canary tests. Update only server-registration expectations. |
| `risk_module/tests/test_corpus_search.py` | 12,13,83,94,568,575 | Test/golden fixtures | Core corpus search tests. Likely stay bare. |
| `risk_module/tests/test_filings_tools.py` | 10,12,19,22,28,31,36,39,40,374,377,423,430,434,441,445,452 | Test/golden fixtures | Filing wrapper/core tests. Likely stay bare unless tied to server registration. |
| `risk_module/tests/test_mcp_corpus_tools.py` | 13,15,17,19,45,46,47,49,50,51,52,58,59,62,63,66,67,85,86,87,92,97,101,103,104,110,113,118,121,218,221,222,229,240,243,244,247 | Test/golden fixtures | MCP corpus tool registration and behavior tests. Phase 1 update required for server split. |
| `risk_module/tests/test_risk_client.py` | 17,19,52,54 | Test/golden fixtures | Client wrapper tests for corpus tool methods. |
| `risk_module/tests/test_transcripts_tools.py` | 9,11,18,21,134,137,188,195,199,206,210,217 | Test/golden fixtures | Transcript wrapper/core tests. Likely stay bare unless tied to server registration. |

## Server-Name Surfaces Without Direct Tool Hits

| Surface | Lines | Category | Phase 1 action |
|---|---:|---|---|
| `AI-excel-addin/api/agent/shared/tool_catalog.py` | 41-58 | CHANNEL_TIERS | Add `research-mcp` to always tiers per the Current Implementation Contract. |
| `AI-excel-addin/api/mcp_client.py` | 17-31 | MCP allowlists | Add `research-mcp` to `ALLOWED_SERVERS`. |
| `AI-excel-addin/api/agent/profiles/analyst.py` | 68-71,105,119,139,553-572,575+ | Agent profiles + ProfileConfig | Add/position `research-mcp` in profile server lists/tool-pack text where the analyst profile should expose moved tools. |
| `AI-excel-addin/api/agent/profiles/advisor.py` | 37,50,74,160,195 | Agent profiles + ProfileConfig | Review portfolio-mcp wording; add `research-mcp` only if advisor profile should see corpus tools. |
| `AI-excel-addin/api/agent/profiles/__init__.py` | 18-23,43,45-49,62-65,69-83 | Agent profiles + ProfileConfig | ProfileConfig has six server/tool/prompt surfaces that need explicit server-aware review. |

## Persisted Records

Required workspace grep did not find old namespaced strings in persisted logs, but manual review found structured records.

| Surface | Finding | Phase 1 / Phase 0h action |
|---|---|---|
| `AI-excel-addin/api/logs/chat.jsonl` | 1874 matches for moved bare tool names in manual persisted-record search. | Migration must rewrite structured `server` plus `tool`/`tool_name` fields. |
| `AI-excel-addin/api/sessions/analyst/agentsess_analyst_henry.jsonl` | 54 matches for moved bare tool names. | Include durable `AgentSessionLog` JSONL in migration fixtures. |
| `AI-excel-addin/api/chat_logs/*.jsonl` | Multiple session logs contain moved bare tool names and portfolio server attribution. | Migration script should walk chat log directories, not one file. |
| `risk_module/logs/*.jsonl` and `risk_module/logs/app.log*` | Small number of moved-tool log references. | Decide whether these are operational logs to migrate or append-only diagnostics to preserve. |
| Exact old namespaced persisted strings | No `mcp__portfolio-mcp__filings_*` or `mcp__portfolio-mcp__transcripts_*` found in the persisted log scan. | Do not rely on namespaced-string replacement alone. |

## `tool_timing` SQLite

Database checked: `AI-excel-addin/api/logs/cost.db`.

Schema:

```text
tool_timing(id, ts, session_id, server, tool, duration_ms, error, result_bytes)
```

Current counts:

| Server | Tool | Rows | Phase 0h handling |
|---|---|---:|---|
| blank/null | `filings_search` | 4 | AMBIGUOUS - inspect rows before migration; likely older local/unattributed calls. |
| `portfolio-mcp` | `filings_list` | 37 | Rewrite `server` to `research-mcp`. |
| `portfolio-mcp` | `filings_search` | 103 | Rewrite `server` to `research-mcp`. |
| `portfolio-mcp` | `transcripts_list` | 8 | Rewrite `server` to `research-mcp`. |
| `portfolio-mcp` | `transcripts_search` | 29 | Rewrite `server` to `research-mcp`. |
| `portfolio-mcp` | `get_handoff` | 6 | Covered in `0g_get_handoff_consumers.md`; split semantics are ambiguous from timing rows alone. |

Total moved-tool `portfolio-mcp` rows: 177.

## Out-of-Scope Workspace Repositories

Per Decision #90/R14, out-of-scope hits were classified explicitly instead of skipped.

| Repository | Hits | Classification | Rationale |
|---|---:|---|---|
| `Edgar_updater` | 2 | documentation reference, not consumer code | One docs/TODO example mentions `filings_search`; one parser plan uses local variable `filings_list[0]`. No V2.P10 runtime consumer. |

No Phase 1 tool hits were found in out-of-scope repos that qualify as "IN SCOPE - V2.P10 cutover must update".

Canonical note: `agent-gateway-dist` is a canonical V2.P10 repo despite its `-dist` suffix; the required grep excluded sibling `*-dist` mirrors but direct canonical reads of `agent-gateway-dist` were performed where relevant.

## Non-Workspace Surfaces

These surfaces live outside `~/Documents/Jupyter` and were not read in this session.

| Surface | Audit status | Required owner/action |
|---|---|---|
| `~/.claude.json` | Not read. User-edit only; Codex skipped. Plan state to confirm: post-PR0a, pre-PR0c. User has read access. | User must verify MCP entries and ensure `research-mcp`/`research-workbench-mcp` naming matches the current cutover plan. |
| Cursor / Codex / Cline / Windsurf / Gemini MCP configs | Not read. | User audit required for any MCP server-name allowlists or tool-prefix examples. |
| Service deployment configs, including Fly.io, Render, GitHub Actions, launch wrappers | Workspace grep found no authoritative external service config for this change. Non-workspace configs were not read. | User audit required if any gateway/research service is launched outside the repo. |
| Shell startup files (`~/.zshrc`, `~/.zprofile`, `~/.bashrc`, etc.) | Not read. | User audit required because `TOOL_TIMING_DB_PATH` and `TOOL_TIMING_LOCK_PATH` must propagate to gateway and migration processes. |
| macOS LaunchAgents/Daemons | Not read. | User audit required for env propagation and service restart behavior. |
| VS Code/Cursor workspace settings, devcontainer, JetBrains, tmux, Homebrew services, cron, pm2/supervisor, asdf/nvm | Not read unless inside workspace grep results. | User audit required for service environment propagation. |
| Secret managers: 1Password, Keychain, Doppler, direnv | Not read. | User audit required if env file paths or MCP config fragments are stored there. |

## Master Checklist

| Category | Hits | Phase 1 rename strategy | Fixture/test updates | Caution |
|---|---:|---|---|---|
| Gateway dispatcher | 0 direct | No in-place rename; dynamic routing | Add coverage only if routing/meta behavior changes | Verify package mirror stays synced. |
| Agent registry | 8 | Per-tool classified review; likely bare names stay | `risk_module` registry tests may need split-server expectations | `AI-excel-addin/api/agent/registry.py` not present. |
| Server policies | 4 | Rename/move in place from portfolio policy to research policy | `test_server_policy_drift.py` required | High-priority Phase 1 surface. |
| CHANNEL_TIERS | 0 direct | Server-name add, not per-tool rename | Tool catalog tests if present | Required for restricted research mode. |
| MCP allowlists | 0 direct | Server-name add | MCP client tests if present | Required before runtime can call research-mcp. |
| Dev CLI fixtures | 2 | Usually no rename | Optional namespaced research fixture | Citation display may stay bare. |
| Repo-local skill profiles + evals | 0 | No Phase 1 action | None found | Re-audit for Phase 2c handoff split. |
| Agent profiles + ProfileConfig | 0 direct | Server-name classified update | Profile prompt/golden tests if present | Avoid blindly moving all portfolio-mcp references. |
| Package mirror tests | 0 | No Phase 1 tool rename | Meta-injection tests in 0e | Keep source/dist sync policy clear. |
| Persisted chat/event replay records | Many | Migration script, structured fields | Build fixtures from real JSONL shapes | Namespaced string replacement is insufficient. |
| Sub-agent transcript / `last_tool_name` | 0 Phase1-specific | Migration script should inspect generic fields | Add fixture if `last_tool_name` stores moved tools | Hard to find with simple grep if embedded in JSON. |
| Telemetry dashboards | 0 local dashboards | User audit for external dashboards | Local dev monitor smoke check | Dashboards keyed by `server/tool` may split history. |
| `tool_timing` SQLite | 177 plus 4 caution | SQL update with maintenance lock | Migration script unit/integration tests | Blank server rows require explicit decision. |
| Docs | 151 | Update active docs; preserve archives | None unless docs tests exist | Separate active vs completed docs. |
| Test/golden fixtures | 85 | Per-test classified replacement | Yes | Do not rename core implementation tests unnecessarily. |
| Tests + fixtures, general code path | 38 | Classified replacement | Yes | Citation canonicalization can keep old prefix as generic regression plus add new prefix. |

## Open Questions For User

| Question | Why it matters |
|---|---|
| Should historical/completed docs be backfilled, or only active interface/reference/V2.P10 docs? | There are many documentation hits where changing history may be noise. |
| Should the 4 blank-server `tool_timing` rows for `filings_search` be migrated, left unchanged, or quarantined? | They are not provably portfolio-mcp rows from the timing table alone. |
| Should AI-excel advisor profile expose research-mcp corpus tools, or only analyst/research profiles? | Profile server visibility is not discoverable from per-tool grep. |

## Phase 1+ Implications

1. Phase 1 needs coordinated edits across server policy, MCP allowlist, channel tiers, meta injection, and risk_module server registration.
2. Phase 0h migration scripts must operate on structured JSONL and SQLite fields. Old namespaced-string search is not enough.
3. Tests should be split between server-location assertions and server-neutral bare-name behavior. Most risk_module corpus tests should not be renamed just because the MCP server changes.

## In-Scope But Flagged For Caution

| Item | Caution |
|---|---|
| Persisted JSONL logs | Many records store bare tool names with separate server fields. Migration must parse JSON, not use raw string replace. |
| `tool_timing` rows with blank server | Ambiguous. These need a deliberate migration policy before Phase 0h. |
| Agent profile surfaces | Tool grep misses server-only changes; ProfileConfig has several separate server and prompt fields. |
| `AI-excel-addin/api/agent/registry.py` missing | The plan names a file that is not present in this checkout; avoid assuming it exists during Phase 1. |
