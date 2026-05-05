# V2.P10 — Research MCP Server Split

**Status:** SCOPED 2026-05-02 → R2..R17 → R18 PASSED Codex review 2026-05-03 → R19 revised 2026-05-04 → **R20 2026-05-04 mid-Phase-0 — PR0a/b/c shipped; cross-session conflict with parallel A6e session resolved by user (PR0a/c manual edits); investment_tools server tool-surfacing in Claude Code catalog flagged as pre-existing issue, separate diagnostic deferred to follow-up session, does NOT block V2.P10 Phase 1**
**Trigger:** Surfaced during V2.P2 Slice C.2 live testing — citation discipline machinery (Slices A+B+C+C.1+C.2) all shipped, but routinely fails to fire because corpus tools live in deferred-tier `portfolio-mcp` server.
**Effort:** **R18: ~6-8 weeks full split, ~4-5 weeks Phase-1-only** (Codex sizing stable since R7).
**Next step (post-R19):** Phase 0b + 0c shipped 2026-05-04 (commits `fdb00f67` + `5f0c7329`). Remaining Phase 0: PR0 catalog-key rename (PR0a manual `~/.claude.json` edit + PR0b Codex AI-excel-addin code edit + PR0c manual cleanup), Phase 0d/e/f/g/h audits + migration script. PR0 frees the `research-mcp` name for V2.P10 use.

> **READER GUIDE:** This doc has 12 rounds of Codex review. The **Current Implementation Contract** section below (after the Decisions log) is the authoritative quick reference. The Decisions log preserves history — when in doubt, the highest-numbered decision wins, and the Current Implementation Contract is the source of truth for handoff.
**Cross-repo:** AI-excel-addin (gateway, MCP catalog, channel tiers, dispatcher routing, citation extractor) + risk_module (second FastMCP entrypoint + `mcp_tools/` source + middleware) + agent-gateway-dist (PyPI publish) + **investment_tools (rename existing `research-mcp` → `research-workbench-mcp` — see §"Naming + cross-repo dependency")**

---

## Decisions log

**2026-05-02 (R1 — initial scoping):**

1. **Scope:** full split (all 4 phases) chosen up front. The "Quick-win alternative — Phase 1 only" subsection below is retained as a fallback if scope contracts during impl, but Phase 1 is no longer the primary recommendation.
2. **Server name:** new server is **`research-mcp`** (matches the plan as drafted). Requires renaming the existing investment_tools `research-mcp` (signals/findings/studies tracker) to **`research-workbench-mcp`** first — see §"Naming + cross-repo dependency".
3. **F56 status:** the F56 auto-load workaround (`api/agent/interactive/runtime.py:87, 461-481`) **already SHIPPED 2026-05-02** in commit `92830bc`. The split retires the workaround retroactively (auto-load block becomes dead code post-split).
4. **F62 status:** filed 2026-05-04 (was incorrectly referenced as F59 in earlier drafts of this plan; F59 is the unrelated Alphabet 10-Q delta-ingest bug). F62 captures the TUI-mode-flag gap with full diagnostic. With V2.P10 Phase 1 split, the underlying gap that triggered F62 is rendered moot — F62 is preempted, not closed.

**2026-05-03 (R2 — Codex review FAIL → scope tightened):**

5. **risk_module is hard-coded to a single FastMCP server** (`mcp_server.py:303`). Split is NOT a `mcp_tools/` move — it requires a second FastMCP entrypoint (process model TBD: same-process-two-servers vs separate-process-second-entrypoint). See new §"risk_module server architecture".
6. **`_MCP_META_INJECT_SERVERS` is a hidden user-identity dependency** (`mcp_server.py:357-376` UserIdMiddleware; AI-excel-addin runtime.py:97 declares `_MCP_META_INJECT_SERVERS = frozenset({"portfolio-mcp"})`). If research-mcp tools need user-scoped behavior, gateway meta injection must be extended. See new §"Hidden dependencies".
7. **Tool inventory tightened** — always-tier eligibility = read-only AND citation-envelope-attachable OR foundational research workflow. Removed from "should move": `build_model` (mutating, returns flags not citation-shape per `mcp_tools/research.py:441-462`), `compare_scenarios` (risk/portfolio per `mcp_tools/compare.py:176`), `analyze_stock` (risk/market analysis per `mcp_tools/stock.py:65`), `industry_peer_comparison` (FMP-derived, returns `source_refs: []` per `mcp_tools/industry.py:11`). Inventory deduplicated: `list_research_files` (was listed twice), `list_ingestion_batches` (was in two buckets).
8. **Slice A extractor coverage is partial, not blanket** — only 4 tools (`filings_search`, `transcripts_search`, `filings_list`, `transcripts_list`) have envelope extractors per `api/agent/shared/citations.py:310-325`. Read/excerpt/load_document tools do NOT inherit citation discipline by moving servers. Plan no longer claims "whole research server inherits envelope."
9. **Aliasing moved from Phase 3 to Phase 1** — back-compat is required at Phase 1 cutover, not deferred. Phase 3 reframed as "deprecation timeline + alias removal," not "introduce aliasing."
10. **PR0 atomic-land replaced with dual-registration compatibility window** — investment_tools dual-registers under both old+new names; AI-excel-addin migrates catalog; investment_tools removes old registration. Three-step sequence with explicit rollback per step. See revised §"Cross-repo sequencing." **`[SUPERSEDED by R19 — see Decisions #112-#116]`**: investigation revealed the `research-mcp` name lives in `~/.claude.json` catalog key (not investment_tools repo). PR0 simplified to catalog-key rename only — no investment_tools commit; PR0a/c are manual `~/.claude.json` user-edits.
11. **F56 retirement gated on two audits**: (a) all research-mode entrypoints actually load research-mcp, (b) `_MCP_META_INJECT_SERVERS` updated coherently. Until both pass, F56 block stays as belt-and-suspenders.

**2026-05-03 (R3 — Codex R2 review FAIL → transport + alias surface + enrichment fixed):**

12. **Default process model flipped from A to B** — Codex R2 verified FastMCP 3.2.4: `mcp.run()` runs one server per process; `mount()`/`import_server()` mount tools INTO the parent server, not as separate independently-named MCP servers. Option A (same-process two FastMCP instances) requires a transport-level spike to prove two `tools/list` endpoints reachable concurrently under the actual gateway transport. R3 default: **Option B (separate process, second entrypoint)**. A is a Phase 0 spike, not a default.
13. **Alias canonicalization surface broadened** — *(R4 note: this scaffolding is REMOVED in R4 — see Decision #19. R3 was solving for a transition window that doesn't need to exist for an internal refactor.)*
14. **Phase 2 payload enrichment added as prerequisite** — Codex R2 verified `mcp_tools/corpus/filings.py:122` and `transcripts.py:116` read/excerpt tools return `{status, content}` only — no `document_id`, section, offsets, URL. Extending `extract_sources` is not a switch addition; it requires payload enrichment in risk_module corpus tools first. Phase 2 now has two sub-stages: enrichment then extractor.
15. **Phase 1 user-scoping acceptance reframed** — the 4 Phase 1 corpus tools don't take `user_email`. Phase 1 verifies user-scoping via a middleware transport test (meta-injection contract round-trip with a canary fake tool), not against a real user-owned tool. Real user-owned tool verification deferred to the first phase that moves one.
16. **"Foundational research workflow read" replaced with explicit criteria** — Codex R2 verified `start_research` is mutating (`mcp_tools/research.py:96`) and `activate_diligence` is write-side in existing policy. R3 replaces the elastic "foundational" criterion with: read-only AND user-owned AND bounded output AND no artifact creation AND no side effects AND named justification for always-tier. Removed from R2 "should move" list (now stay in portfolio-mcp): `start_research`, `activate_diligence`.
17. **Phase 0d consumer inventory expanded** — Codex R2 found additional sites: `ALLOWED_SERVERS` at `api/mcp_client.py:12`, skill frontmatter references, package mirror tests, persisted chat/event replay records, `AGENT_INFRASTRUCTURE.md`, telemetry dashboards. R3 adds these to the Phase 0d inventory.
18. **Effort revised up to ~3-5 weeks** — *(R4 note: revised back DOWN to 2-3 weeks once cross-listing scaffolding removed.)*

**2026-05-03 (R4 — straight refactor reframing, scope dramatically simplified):**

19. **Cross-listing strategy abandoned** — Codex R3 verified two structural blockers: `agent_gateway/mcp_client.py:386-399` `_apply_collision_filtering` keeps only the FIRST registered server when two servers advertise the same tool name (the LLM never sees both copies); `server_policies.py:431-435` builds a unique `_TOOL_TO_SERVER` map and **raises** if the same tool appears in two policies. Cross-listing is structurally impossible. **But the deeper question is: why was cross-listing in the plan at all?** It was justifying transition-window concerns (persisted records, external consumers, mid-deploy session continuity) that don't apply to Hank's stage:
    - **Persisted records** (chat logs, event replay): Hank is pre-launch internal-debugging artifacts. A one-time migration script handles records that need to replay; old logs that don't replay cleanly are acceptable.
    - **External consumers** (Cursor, custom agents, third parties): none exist. Hank is single-user (Henry) plus dev/test surface.
    - **Mid-deploy session continuity**: single-user dev. Sessions are restartable. Not a multi-tenant production concern.
    The cross-listing was solving a published-API-migration problem on what is actually an internal refactor.

20. **R4 simplification — "straight refactor" framing:**
    - Each move is a **single cutover PR per tool group** that updates ALL consumers atomically (CHANNEL_TIERS, ServerPolicy, tests, fixtures, prompts, docs, MCP client configs).
    - **No transition window.** No "both prefixes work simultaneously."
    - **No long-lived alias map.** The "alias canonicalization scope" R3 invented evaporates because there's no parallel-naming period to canonicalize across.
    - **No Phase 3 deprecation timeline.** Nothing to deprecate — the refactor is complete at cutover.
    - **One-time migration script** for persisted records that need to replay through the rename (chat logs, event store fixtures).
    - **PR0 cross-repo dance for investment_tools rename STAYS** — that's a different problem (genuine 2-repo coordination because AI-excel-addin's catalog references `research-mcp` today, which must move to `research-workbench-mcp` before V2.P10 can claim the name).

21. **Architectural floor unchanged from R3:**
    - Second FastMCP entrypoint (Option B default per Decision #12)
    - `_MCP_META_INJECT_SERVERS` extension for research-mcp
    - Per-tool read/write/bounded justification rule (R3 eligibility from Decision #16)
    - Phase 2 payload enrichment in core/corpus + mcp_tools/corpus (Decision #14)
    - Consumer-site inventory still real (Phase 0d) — but now it's a one-time sweep + update list, not a forever-alias spec.

22. **R3 blockers that become non-issues under R4:**
    - **Cross-listing collision** (`_apply_collision_filtering`) — non-issue (no cross-listing).
    - **ServerPolicy `_TOOL_TO_SERVER` uniqueness** — non-issue (each tool has one home; constraint is satisfied trivially).
    - **10-layer alias canonicalization scope** — non-issue (no transition window means no live alias resolution required).
    - **Drift tests across alias layers** — non-issue (consumers updated in the move PR; no drift surface).
    - **"Both prefixes work" Phase 1/2 acceptance criteria** — replaced with "all consumers updated in the cutover PR; old prefixes return errors as expected."

23. **R3 blockers that remain valid under R4:**
    - **Option B launch contract** (Decision #12) — still need to specify package layout, entrypoint launch, services.yaml entry, `.claude.json` config.
    - **Phase 2a core-corpus changes** — Codex R3 verified `core/corpus/filings.py:83-105` returns plain `str`; enrichment requires core-corpus metadata lookup, not just MCP wrapper edits. R4 keeps this scope.
    - **Borderline tool boundedness** — `read_research_thread` has `limit` but no max cap; `thesis_read` no explicit limit; `get_diligence_state` needs upstream verification of read-only.
    - **A-validation harness** — if attempting Option A, harness still applies.

**2026-05-03 (R5 — Codex R4 review FAIL → reframe accepted, refinements applied):**

Codex R4 verdict: "the straight-refactor reframe is basically correct. For Hank's current pre-launch/single-user state, no live alias layer is justified." Framing locked. Remaining 7 blockers all refinements:

24. **Option B launch contract concretized** — R4 left this as Phase 0 deliverable; Codex R4 said the plan-doc itself needs a target launch contract. R5 specifies in §"risk_module server architecture": new entrypoint module name (`mcp_server_research.py` at repo root), launch command (`python -m mcp_server_research` or equivalent script), `services.yaml` entry shape, MCP client config snippet for `~/.claude.json`, health/smoke command, and shared middleware/lifespan import pattern. Phase 0 acceptance now requires the contract to be designed (the actual values can be finalized during the spike).

25. **Consumer sweep expanded with agent profiles + repo-local skill evals** — Codex R4 found `api/agent/profiles/analyst.py` and advisor profile have hard-coded `portfolio-mcp` tool pack assignments; tests under `api/memory/workspace/notes/skills` and `tests/skill_evals` assert server semantics. R4's "skill frontmatter is out of scope" was too broad. R5 splits the row: external Claude skill dirs (out of scope) vs repo-local skill profiles/evals (in scope, must update in cutover PR).

26. **Persisted-record migration enumerated by class** — R4 named "chat logs, event store, replay fixtures" generically; Codex R4 enumerated 8 record classes that retain `tool_name` or `server` fields. R5 adds a per-class table with disposition (rewrite / leave historical / cannot cleanly migrate) covering: `AgentSessionLog` JSONL, durable `tool_call_start/tool_call_complete` events, SDK runner event logs (with `mcp__server__tool` prefixes), context-builder replay summaries, task registry `last_tool_name`, research tool-result persistence, telegram/tool-only summaries, test/golden fixtures.

27. **Active-session behavior promoted from release-note footnote to explicit cutover step** — Phase 1 acceptance now requires a clean new-session test (post-cutover session sees research-mcp tools correctly) AND a stale-session visible-error test (session loaded before cutover gets clear "tool not found" errors on old prefixes, not silent failures).

28. **Phase 2 boundedness rule generalized** — R4 named `read_research_thread` and `thesis_read` for max-cap addition; Codex R4 verified `thesis_list_decisions_log(limit=None)` can also be unbounded. R5 generalizes: every always-tier list/read tool with user-sized collections must have a max cap before cutover, not just the named ones.

29. **Effort revised to ~3-4 weeks** — Codex R4 sizing.

**2026-05-03 (R6 — Codex R5 review FAIL → 6 specific refinements applied):**

30. **Option B factoring made MANDATORY, not optional** — Codex R5 verified that importing `mcp_server.py` from `mcp_server_research.py` would re-instantiate `portfolio-mcp` as an import side effect (current `mcp_server.py:301` registers tools at module-import time). R6 elevates "factor middleware to shared module if needed" to a hard requirement: create `mcp_middleware.py` (or equivalent) as a shared module that BOTH `mcp_server.py` and `mcp_server_research.py` import from. Pool/lifespan cleanup also moves to a shared module. Importing one server file from the other is explicitly forbidden.

31. **`tool_timing` SQLite telemetry table added to persisted-record migration** — Codex R5 found this real persisted record class at `AI-excel-addin/api/logs/cost_tracker.py:66, 375, 495`. The table persists both `server` and `tool` fields; skill telemetry reads from the same table. R6 adds it to the migration table as a "rewrite" disposition.

32. **Group B boundedness audit results enumerated** — Codex R5 verified specific unbounded paths:
    - `list_research_files` — no limit at MCP, action, OR repository layer (`actions/research.py:36`, `routes.py:784`, `repository.py:1693`)
    - `list_process_templates` — fetches all user-created templates (`actions/research.py:49`, `repository.py:1799`)
    - `get_handoff` list mode — no limit (`actions/research.py:573`, `routes.py:1547`)
    - `thesis_list` — no limit (`actions/thesis.py:111`, `repository.py:2299`)
    - `thesis_list_links` — no limit (`actions/thesis.py:223`, `repository.py:2541`)
    - `get_diligence_state` — returns all sections + all qualitative factors; needs proof of natural boundedness OR explicit cap (`actions/research.py:361`)
    - `get_action_history` — already bounded (DatabaseClient clamps to 200; MCP exposes `limit`). OK as-is.
    R6 adds these explicitly to the "needs cap" list (was just 3 in R5, now 9 with Codex R5 audit).

33. **Agent profile row broadened** — Codex R5 found references go beyond tool packs: always/deferred server sets (`analyst.py:68`, `advisor.py:37`), core tool maps, prompt text, profile tests. R6 widens the consumer-sweep row wording.

34. **Active-session test fixture infrastructure called out as Phase 1 scope** — Codex R5 verified no existing fixture models "session created before MCP catalog cutover." Phase 1 needs new fixture infra: two fake MCP catalogs or a restartable fake `McpClientManager`, plus a session whose prompt/tool list is stale while dispatcher routing is current.

35. **Skill-eval cutover requires classified replacement, not blind find-and-replace** — Codex R5 verified `tests/skill_evals` and `api/memory/workspace/notes/skills` contain BOTH old investment_tools `research-mcp.*` references AND portfolio research/thesis references. Cutover script must distinguish: old investment_tools `research-mcp.*` → `research-workbench-mcp.*` (PR0); moved portfolio research reads → new V2.P10 `research-mcp.*` (V2.P10 cutover PR).

36. **Effort revised to ~4-5 weeks** — Codex R5 sizing accounts for mandatory factoring, telemetry migration, broader cap audit, active-session test infra.

**2026-05-03 (R7 — Codex R6 review FAIL → 5 specific refinements applied):**

Codex R6 verdict: R6 closed R5 blockers structurally; fresh code review found 5 more specific gaps. R7 applies them.

37. **Shared-module factoring scope expanded** — Codex R6 found `mcp_middleware.py` + `mcp_lifecycle.py` cover only middleware/lifespan but miss bootstrap/lifecycle plumbing:
    - `_stop_order_watcher` depends on module-global `_order_watcher` set in `_run_server()` at `mcp_server.py:4015`. Splitting middleware without owning the watcher state breaks shutdown silently.
    - `mcp_server.py:18` has stdout-to-stderr prelude, `.env` loading, `_validate_environment()`, `nest_asyncio.apply()` — all needed by the new entrypoint too.
    R7 expands the shared-module scope to include: stdout/env/validation prelude, `_order_watcher` state with explicit `start_order_watcher_if_enabled()` / `stop_order_watcher()` API, `nest_asyncio.apply()` policy. Decision: portfolio-only watcher startup stays in `mcp_server.py` BUT cleanup is injected via the shared lifecycle module so both servers can call it.

38. **Group B boundedness expanded to payload-size, not just row counts** — Codex R6 found:
    - `read_research_thread` caps message count only; each message returns raw `content` (`actions/research.py:1062`) with no per-message or total char cap.
    - `get_handoff` single mode (not just list mode) includes full `artifact` (`actions/research.py:1155`).
    - `get_research_brief` returns entire upstream brief object (`actions/research.py:626`); needs boundedness proof or projection.
    - `thesis_latest_scorecard` returns opaque scorecard dict (`actions/thesis.py:290`); needs boundedness proof or projection (scorecard internals could carry unbounded evidence/source/decision detail).
    R7 expands Phase 2c boundedness rule to require BOTH row-count caps AND payload-size caps where applicable.

39. **`tool_timing` migration concurrency + validation tightened** — Codex R6 verified `tool` column is bare runner tool name (not server-prefixed); no FK/composite key but it's a global SQLite DB. Concurrent writes are the migration risk. R7 tightens: use `BEGIN IMMEDIATE` transaction, stop/drain gateway writers during migration window, post-migration validation includes `get_tool_timing_summary` and `get_skill_tool_timing` queries returning consistent results. Migration script's `tool IN (...)` clause uses bare tool names ('filings_search' etc.), not `mcp__portfolio-mcp__filings_search`.

40. **Agent profile row adds ProfileConfig fifth surface** — Codex R6 found beyond always/deferred/core/prompt/tool packs, ProfileConfig runtime fields affect tool visibility: `excluded_tools`, `run_once_excluded_tools`, `dev_excluded_tools`, `channel_context`, `build_*_system_prompt` builders, dev-mode prompt builders. These affect run-once/skill/dev/sub-agent contexts where moved tools may need distinct treatment. R7 expands the profile sweep row.

41. **Active-session test fixture API sketched + grounded in existing patterns** — Codex R6 named adjacent existing patterns: `tests/mcp/test_mcp_meta_transport.py` (fake MCP/dispatcher meta injection), `tests/test_autonomous_mcp_session_injection.py` (fake `McpClientManager`), `tests/test_create_agent_mcp_gateway_changes.py` (manager/dispatcher wiring). R7 defines the new fixture's interface: `catalog_v1` (pre-cutover tool registry), `catalog_v2` (post-cutover), stale prompt tool list (frozen at session start), current dispatcher routing (uses v2), reload recovery API (`load_tools` re-reads catalog).

42. **Effort revised up to ~5-6 weeks** — Codex R6 sizing. Phase 1-only fits ~4-5 weeks if Phase 2 Group B is split into a later tranche.

**2026-05-03 (R8 — Codex R7 review FAIL → 6 specific refinements applied):**

43. **Bootstrap ordering specified** — Codex R7 found R7 said "call `bootstrap()` before FastMCP instantiation" but the stdout-to-stderr redirection must cover noisy *imports* too, not just FastMCP construction. R8 specifies: `bootstrap()` runs as the first executable statement in each server file, BEFORE any repo-local imports that may print/log. Includes a clear stdout restore point before `mcp.run()` for any post-startup logging that should reach the client.

44. **Tool registration extraction policy** — Codex R7 noted moved tool wrapper functions are currently decorator-bound in `mcp_server.py`. R8 specifies: moved tools are physically defined in `mcp_tools/<module>.py` (where they already live for corpus); registration on the new server happens via `@mcp_research.tool()` decorators inside `mcp_server_research.py`, calling the imported tool functions. No wrapper code lives in `mcp_server_research.py` itself; the file is registration-only. This avoids the temptation to import `mcp_server.py`.

45. **Payload-size projection contract added** — Codex R7 verified per-message char truncation alone is "semantically dangerous" — truncating mid-sentence loses meaning. R8 requires a projection contract for every payload-cap tool:
    - `truncated: bool` flag
    - `original_char_count: int`
    - Stable `message_id` or ordinal for continuation
    - `offset`/`cursor` for paginated re-fetch
    - Either a continuation tool (e.g., `read_research_thread_continuation`) OR a "summary + excerpts" response shape
    - ~~For `get_handoff`: default returns `artifact_summary` (snapshot/projection); full `artifact` only via explicit `include_full=True` flag, gated to defer-tier or sub-agent contexts.~~ **`[SUPERSEDED by R9/R10/R11 — see Decision #52/#59/#64]`** — replaced with split tools (`get_handoff_summary` always-tier on research-mcp, `get_handoff_full` defer-tier on portfolio-mcp); see boundedness section for `_project_handoff_summary` whitelist contract.
    - For `get_research_brief`: schema-bounded proof OR projection (return brief metadata + linked sections, not full body inline).
    - For `thesis_latest_scorecard`: scorecard internals projected (top-N evidence/sources/decisions, with `truncated` + `original_count` + continuation pattern).

46. **`tool_timing` writer-drain mechanism specified** — Codex R7 verified there's no writer queue to drain; writes go through `record_tool_timing()` in `cost_tracker.py:375`, called by `tool_timing_hook` in `hooks.py:457`, from both `runner.py:2216` and `sdk_runner.py:630`. R8 specifies the mechanism: **maintenance-lock pattern** — set a flag (env var or sentinel file) that `tool_timing_hook` checks before writing; when flag is set, hook becomes a no-op. Migration script: (a) set maintenance-lock; (b) wait for in-flight tool calls to complete (15-30s grace, or check via gateway health endpoint); (c) `BEGIN IMMEDIATE` UPDATE; (d) clear maintenance-lock. During the lock window (~1-2 min), tool timing is not recorded — acceptable for a one-time migration.

47. **ProfileConfig enumeration completed** — Codex R7 found additional fields R7 missed: `format_tool_catalog`, `build_tool_packs_section`, `run_once_use_tool_packs`, `local_tool_names`, dev env/write-dir fields. `format_tool_catalog` and `build_tool_packs_section` directly shape what the model sees about active/deferred tools. R8 expands the profile sweep row to include these.

48. **Active-session fixture reload-recovery grounded in actual session APIs** — Codex R7 verified `load_tools` does NOT reload the MCP manager — it reads current `mcp_clients.get_server_catalog()` and marks servers as loaded (`tool_handlers.py:672`, `mcp_client.py:263`). R8 resolves: the fixture injects `catalog_v2` by swapping the fake `McpClientManager`'s catalog directly (production code calls `get_server_catalog()` against the swapped manager). The "stale prompt tool list" + "current dispatcher routing" model still holds; reload-recovery in the fixture is "fixture swaps catalog mid-test, then session calls `load_tools` to refresh its tool list against the new catalog." This requires NO new production session/catalog API — the fixture mirrors how a real deploy works (gateway client connects to a new server registration).

49. **Group B count typo fixed** — Codex R7 found Phase 2c "Group B — foundational reads (12 tools)" but the listed tools are 13. R8 corrects the count to 13.

50. **Effort revised up to ~6-8 weeks full split (~4-5 weeks Phase-1-only)** — Codex R7 sizing.

**2026-05-03 (R9 — Codex R8 review FAIL → 6 narrow refinements applied):**

51. **`mcp_bootstrap.py` import-safety carveout** — Codex R8 noted R8's pattern violates its own "first executable" rule because `from mcp_bootstrap import bootstrap` IS a repo-local import. R9 adds: `mcp_bootstrap.py` MUST import only stdlib + import-silent dependencies at module level; all repo-local/env/logging work happens INSIDE `bootstrap()` after stdout redirection. If `mcp_bootstrap.py` cannot be made import-silent, fall back to keeping the stdout redirect block inline at the top of each server file (R8's pattern) BEFORE importing `mcp_bootstrap`.

52. **`include_full=True` gating made enforceable** — Codex R8 noted R8's "gated to defer-tier or sub-agent contexts" was prose, not enforceable. R9 specifies a concrete mechanism: **split the tool into two MCP-registered tools** — `get_handoff_summary` (always-tier, returns projection) and `get_handoff_full` (defer-tier or sub-agent only, returns full artifact). ~~ServerPolicy declares `get_handoff_full` as defer-tier with explicit context guard.~~ **`[SUPERSEDED by R10/R11 — see Decision #59]`**: ServerPolicy has no per-tool tier or context-guard field; tiering is at server-level via `CHANNEL_TIERS`. Current resolution: `get_handoff_full` lives on `portfolio-mcp` (defer-tier), visible only after explicit `load_tools(["portfolio-mcp"])`. Eliminates ambiguity; the LLM can't bypass the gate via flag.

53. **`tool_timing_hook` maintenance-lock read-point specified** — Codex R8 traced the call paths; hooks fire at tool COMPLETION (`runner.py:1559`, `sdk_runner.py:275`), not start. R9 specifies: hook checks maintenance-lock flag ONCE at hook entry, BEFORE calling `record_tool_timing`. Writes that beat the check are allowed to finish (acceptable — they reflect pre-migration state). `BEGIN IMMEDIATE` serializes the migration UPDATE behind any active SQLite writer. Net behavior: ~1-2 minute window where some completions are dropped (set-flag-after-tool-start case) — acceptable for one-time migration, documented in release notes.

54. **`build_initial_user_message` added as 6th ProfileConfig surface** — Codex R8 found `advisor.py:195` initial message says "portfolio state from portfolio-mcp" — a server-name reference R8 missed. R9 adds `build_initial_user_message` to the profile sweep row (and any other `build_*` profile method that emits server names in prompt text).

55. **Active-session fake-manager extension explicit** — Codex R8 verified existing `_FakeMcpClientManager` (`test_autonomous_mcp_session_injection.py:46`) exposes `inline_servers`, `get_server_names()`, `get_tool_definitions()` but NO `get_server_catalog()` or catalog setter. R9 specifies the extension Phase 1 adds: `catalog` field, `set_catalog(catalog)` method, `get_server_catalog()` method (matches production API), and `get_server_tool_definitions()` for the catalog-swap mechanism. Test fixture work is bounded — extend the existing fake, don't build a new one.

56. **Registration-only wrapper schema-drift policy** — Codex R8 noted R8's example `@mcp_research.tool() def filings_search(...): return _corpus_filings_search(...)` is still wrapper code; manual forwarding risks schema drift. R9 specifies: prefer FastMCP-native registration of the imported function directly (`mcp_research.tool()(_corpus_filings_search)` or equivalent registration that preserves signature/docstring/schema from the source function). If FastMCP requires a decorator wrapper, the wrapper MUST use `functools.wraps` AND a single source of truth for the signature (e.g., a typed `Protocol` or generated stub) so old/new registrations can't drift. Phase 0b spike includes verifying the chosen pattern preserves schema across the move.

57. **Effort estimate stable at ~6-8 weeks full / ~4-5 weeks Phase-1-only** — Codex R8 confirmed estimate stability.

**2026-05-03 (R10 — Codex R9 review FAIL → 4 narrow refinements applied):**

Codex R9 closed 3 of 6 R8 blockers (bootstrap carveout, `build_initial_user_message`, schema drift). 4 remain:

58. **`get_handoff` → `get_handoff_summary` reference sweep** — Codex R9 noted Phase 2 Group B and acceptance still reference `get_handoff` move, but R9 introduced `get_handoff_summary`/`get_handoff_full` split. Plan must replace every Phase 2/acceptance/inventory reference to moved `get_handoff` with `get_handoff_summary` (always-tier on research-mcp). Codex R9 also verified `actions/research.py:1148` `_normalize_handoff_artifact_summary` includes `artifact` whenever upstream returns it — so `get_handoff_summary` is NOT a renamed wrapper around current `get_handoff`; it requires its own projection helper that strips the full `artifact` field. R10 makes this explicit.

59. **ServerPolicy "context guard" claim corrected** — Codex R9 verified `server_policies.py:12` only classifies read/write/predicate; tiering is at server-level in `tool_catalog.py:667`, not per-tool; no context guard mechanism exists. R9's "ServerPolicy declares `get_handoff_full` as defer-tier with explicit context guard" was inaccurate. **R10 corrects:** the only enforceable gate is server-tier visibility. `get_handoff_full` lives on `portfolio-mcp`, which is defer-tier across all channels per `CHANNEL_TIERS`. Visibility = "whenever `portfolio-mcp` is loaded" (which is when the LLM explicitly `load_tools(["portfolio-mcp"])` for portfolio operations). This is sufficient — research-mode by default never sees `get_handoff_full`. If a stronger guard is needed in the future, it would require new ServerPolicy/tier infrastructure (out of V2.P10 scope). R10 documents this as the chosen mechanism, not "context guard."

60. **`tool_timing` post-UPDATE catch-up loop** — Codex R9 found a residual race: hook reads unlocked → migration sets lock + commits UPDATE → hook's INSERT (with stale `server='portfolio-mcp'`) commits AFTER migration. `BEGIN IMMEDIATE` only serializes behind active writers, not hooks-that-beat-the-check. **R10 adds:** AFTER the migration UPDATE commits and BEFORE clearing the maintenance-lock, run a catch-up `SELECT` validation: `SELECT COUNT(*) FROM tool_timing WHERE server = 'portfolio-mcp' AND tool IN (moved tool list) AND ts > <migration_start_ts>`. If non-zero, run a second UPDATE in the same maintenance window to fix any stale rows that beat the flag check. Repeat the SELECT/UPDATE cycle (max 3 iterations) until SELECT returns 0. Then clear the lock.

61. **Fake-manager `set_catalog()` propagation** — Codex R9 found `load_tools` calls `get_server_names()` BEFORE reading catalog (in `tool_handlers.py:680`+ region). R9's `set_catalog()` only updated catalog field; it didn't make `get_server_names()` return the catalog's server keys. **R10 specifies:** `set_catalog(catalog)` MUST also update internal state read by `get_server_names()` and any tool-definition methods used by active tool discovery (`get_tool_definitions()`, `inline_servers`, etc. — verify the full set during the fixture extension). Failing to propagate causes the fixture to report servers as not-found.

62. **Effort stable at ~6-8 weeks full / ~4-5 weeks Phase-1-only** — Codex R9 confirmed.

**2026-05-03 (R11 — Codex R10 review FAIL → 6 specific refinements applied):**

63. **Stale `get_handoff` references annotated as superseded** — Codex R10 found stale text in (a) the `get_handoff` payload-cap row (still references `include_full=True` flag), (b) the `get_handoff` row-count row, (c) the R8 decision-log entry referencing "ServerPolicy ... explicit context guard." R11 annotates each in-place: stale lines marked **`[SUPERSEDED by R10/R11 — see Decision #58/#59]`** rather than rewriting (decision-log entries preserve history; payload-cap section gets corrected text). Forward-readers see the current resolution.

64. **`_project_handoff_summary` whitelist with caps** — Codex R10 verified `_normalize_handoff_artifact_summary` (`actions/research.py:1148`) copies upstream `artifact_summary` verbatim before adding bounded counts. `artifact` is the main oversized field, but `artifact_summary` itself can be unbounded (not just `artifact`). R11 specifies the projection helper:
    - `_project_handoff_summary(payload)` returns `{handoff_id, ts, status, source, artifact_summary_projected, decisions_log_count, links_count, sections_count, ...metadata}`
    - **Whitelist:** ONLY metadata fields + bounded counts.
    - `artifact_summary_projected`: per-field caps (e.g., title ≤200 chars, abstract ≤500 chars, top-N items each capped); reject unknown fields rather than passing through.
    - `artifact` field stripped entirely.
    - Fail closed if upstream sends fields not on the whitelist (caller must extend whitelist explicitly when new fields are added).

65. **Consumer-classification step added before cutover** — Codex R10 found existing `get_handoff` callers depend on full `artifact` (tests at `tests/test_research_mcp.py:884`). Blind consumer-sweep to `get_handoff_summary` would silently break artifact consumers. R11 adds Phase 0d sub-deliverable: classify each `get_handoff` caller as either:
    - **Summary consumer** (only needs metadata + projected summary) → migrate to `mcp__research-mcp__get_handoff_summary`
    - **Full-artifact consumer** (needs actual artifact body) → migrate to `mcp__portfolio-mcp__get_handoff_full`
    - **Tests** (assert artifact presence) → either updated to test the appropriate variant, or split into summary-test + full-test pair.
    Document the classification per caller; cutover PR uses the classified mapping, not blind find-and-replace.

66. **Research-mode access to `get_handoff_full` decision** — Codex R10 verified research-mode has no `load_tools` per `system_prompt.py:1185`. So `get_handoff_full` is unreachable from research-mode. R11 documents this as **intentional**: research-mode is a citation-disciplined surface; full handoff artifacts are model-build context, not narrative research. If a research workflow needs full artifact access (e.g., to inspect a prior model build), the user explicitly transitions to portfolio-mode (`load_tools(["portfolio-mcp"])`) which exposes `get_handoff_full`. **No scoped access path needed for V2.P10.** Documented in V2.P10 release notes.

67. **`tool_timing` migration fail-closed recovery** — Codex R10 noted R10's "max 3 iterations" didn't say what happens if iteration 3 still finds stale rows. R11 specifies: loop until zero OR configurable timeout (default 60s) / max iterations (default 5). If still nonzero at exit:
    - **FAIL the migration script** (non-zero exit code).
    - Keep maintenance-lock SET (do NOT clear).
    - Print exact recovery command: `python3 scripts/migrate_tool_timing.py --resume --since=<migration_start_ts>` to retry.
    - Print stale-row count and IDs for operator inspection.
    - Do not declare success or run post-migration validation.

68. **Fake-manager surface enumerated now, not punted** — Codex R10 enumerated production `McpClientManager` API: `get_tool_definitions`, `get_server_tool_definitions`, `get_server_names`, `get_server_catalog`, `is_mcp_tool`, `get_server_for_tool`, `resolve_tool_name`. R11 specifies `set_catalog(catalog)` MUST update internal state read by ALL of: `get_server_names`, `get_server_catalog`, `get_tool_definitions`, `get_server_tool_definitions`, `is_mcp_tool` (returns True for tool names in any catalog server's tool list), `get_server_for_tool` (returns server name for a given tool), `resolve_tool_name` (canonicalizes prefixed names). Bounded test-helper extension; finite enumeration.

69. **Effort stable** — Codex R10 confirmed estimate stability.

**2026-05-03 (R12 — Codex R11 review FAIL → 6 specific refinements + meta-fix):**

70. **Decision #52 supersession annotated** — Codex R11 found Decision #52 still said "ServerPolicy declares `get_handoff_full` as defer-tier with explicit context guard" despite R10's correction. R12 adds inline `[SUPERSEDED]` annotation pointing to Decision #59.

71. **`_project_handoff_summary` whitelist grounded in real fields** — Codex R11 verified the actual `artifact_summary` shape from `_normalize_handoff_artifact_summary` (`actions/research.py:1180`+) and upstream emitters: `thesis_statement`, `assumptions`, `qualitative_factors`, `sources`, `differentiated_view_count`, `invalidation_trigger_count`, `industry_analysis_present`, `scorecard_summary_status` (snake_case from action layer); upstream `routes.py:247` emits camelCase variants (`thesisStatement`, etc.); `handoff.py:797` adds full `artifact`. R12 replaces R11's invented examples with real-field whitelist + camelCase normalization spec.

72. **Consumer-classification grep command specified** — Codex R11 noted "every existing caller classified" lacked discovery method. R12 adds Phase 0g concrete command:
    ```
    rg -n "get_handoff|get_handoff_summary|get_handoff_full|mcp__.*get_handoff|artifact_summary|artifactSummary" \
      risk_module AI-excel-addin agent-gateway-dist \
      --glob '!**/.claude/**' --glob '!**/agents/**' --glob '!**/__pycache__/**'
    ```
    Required artifact: classification table per caller (path + line + classification: summary/full/test). Includes mandatory review of persisted prompt/event stores (chat logs, replay fixtures) for hard-coded `get_handoff` references that grep doesn't catch.

73. **Research-mode UX corrected — restricted vs analyst profile** — Codex R11 verified shared restricted research mode (`system_prompt.py:1185`) has NO `load_tools` mid-conversation; analyst profile (`analyst.py:68`) has `portfolio-mcp` always-on AND prompt guidance to call `load_tools` for deferred. R12 distinguishes:
    - **Restricted research mode (no `load_tools`):** `get_handoff_full` is genuinely unreachable mid-conversation. User must start a new session in analyst-profile mode (or other profile that loads portfolio-mcp). UX cost: explicit profile transition; documented in release notes.
    - **Analyst profile (has portfolio-mcp always-on or via `load_tools`):** `get_handoff_full` is reachable normally. No new infra needed.
    - **Sub-agents triggered from research mode:** depends on sub-agent profile; if sub-agent uses analyst profile, full handoff accessible via that path.

74. **`migrate_tool_timing.py` interface contract specified** — Codex R11 verified `scripts/migrate_tool_timing.py` doesn't exist; R11's recovery command was aspirational. R12 specifies as Phase 0e deliverable:
    - **Path:** `risk_module/scripts/migrate_tool_timing.py` (new) — coordinates with the AI-excel-addin SQLite db path.
    - **DB path resolution:** reads `COST_TRACKER_DB_PATH` env var or default `~/.gstack/cost_tracker.db` (matches `cost_tracker.py` resolution).
    - **Args:** `--dry-run` (default OFF), `--since=<ISO_TS>` for resume, `--max-iter=<N>` (default 5), `--timeout=<seconds>` (default 60), `--verbose`.
    - **Exit codes:** 0 = success (lock cleared); 1 = fail-closed (lock retained, stale rows remain); 2 = config error.
    - **Lock behavior:** sets `TOOL_TIMING_MAINTENANCE=1` env var (or sentinel file `~/.gstack/.tool_timing_lock`); clears on success only.
    - **`--resume` semantics:** rerun the catch-up loop with provided `--since` timestamp, reusing existing lock; if lock not set, set it; if catch-up succeeds, clear lock.
    - **Idempotent:** safe to rerun on already-migrated state (UPDATE matches zero rows; SELECT returns 0; immediately clears lock).

75. **Fake-manager `call_tool()` added** — Codex R11 noted production `McpClientManager.call_tool()` uses `_tool_to_server`, `_servers`, `_prefixed_to_original` for routing; stale-session test depends on dispatch behavior post-catalog-swap, not just discovery. R12 adds `call_tool()` to the fake-manager extension list. `set_catalog()` MUST update routing state used by `call_tool()` (the internal `_tool_to_server` map equivalent in the fake) so tests can verify "old prefix returns tool-not-found" via the actual dispatch path, not just discovery.

76. **NEW Current Implementation Contract section** — Codex R11 meta-flagged that 12 rounds of decision-log + supersession annotations + repeated "framing preserved" blocks make it hard for reviewers to determine current intent. R12 adds an authoritative quick-reference section right after the Decisions log: "Current Implementation Contract" — a compact summary of all current decisions/contracts/scope without historical evolution. Forward-readers consume that; the Decisions log remains as audit trail.

77. **Effort stable** — Codex R11 didn't push effort up; estimate unchanged at ~6-8 weeks full / ~4-5 weeks Phase-1-only.

**2026-05-03 (R13 — Codex R12 review FAIL → 7 specific refinements):**

78. **`_project_handoff_summary` whitelist grounded in actual code** — Codex R12 verified the real `_normalize_handoff_summary` returns OUTER fields R12 omitted (`version`, `ticker`, optional `research_file_id`/`created_at`/`finalized_at`, optional `artifact`, plus snapshot fields when artifact present). `_normalize_handoff_artifact_summary` returns `assumptions`/`qualitative_factors`/`sources` as COUNTS (not top-N lists) when artifact is present (`actions/research.py:1201-1206`). R13 corrects: see updated Current Implementation Contract for the faithful projection.

79. **CamelCase claim narrowed** — Codex R12 verified `routes.py:247` only emits `thesisStatement`, `assumptions`, `sources` as upstream fallback (NOT `differentiatedViewCount`, `invalidationTriggerCount`, etc.). Also `_normalize_handoff_artifact_summary:1188-1189` only renames `thesisStatement` → `thesis_statement`. R13 narrows: projection helper only handles the 1 known camelCase variant (`thesisStatement`), or applies a generic camelCase-to-snake_case normalizer if implementer prefers.

80. **`scorecard_summary_status` location resolved** — Codex R12 found this field appears BOTH inside `artifact_summary` (when artifact has `scorecard_ref.summary_status`, set in `_normalize_handoff_artifact_summary:1210-1211`) AND top-level via `_build_handoff_snapshot_fields` when called from `_normalize_handoff_summary:1174`. R13 resolves: `_project_handoff_summary` puts it at one location only (inside `artifact_summary_projected`); strips top-level snapshot duplicate.

81. **Consumer-grep expanded across full Hank workspace** — Codex R12 found `risk_module-equity-workspace` and `risk_module-editorial-pipeplan` repos contain relevant references; also frontend hooks like `risk_module/frontend/.../HandoffReviewView.tsx`. R13 expands the grep:
    ```
    rg -n "get_handoff|get_handoff_summary|get_handoff_full|mcp__.*get_handoff|artifact_summary|artifactSummary" \
      ~/Documents/Jupyter \
      --glob '!**/.claude/**' --glob '!**/agents/**' --glob '!**/__pycache__/**' \
      --glob '!**/node_modules/**' --glob '!**/.git/**' \
      --glob '!**/-dist/**'
    ```
    Or, explicitly limit V2.P10 classification to: `risk_module`, `risk_module-equity-workspace`, `risk_module-editorial-pipeplan`, `AI-excel-addin`, `agent-gateway-dist`, plus any frontend hooks under `risk_module/frontend/`. Other workspace repos (web-app-platform-dist, app-platform-dist, brokerage-connect, etc.) explicitly out of scope unless Codex review surfaces hits.

82. **Profile access matrix for `get_handoff_full`** — Codex R12 found advisor profile (`advisor.py:37`) ALSO has `portfolio-mcp` always-on, not just analyst. R13 adds matrix:
    | Profile | `portfolio-mcp` always-on? | `load_tools` available? | `get_handoff_full` reachable? |
    |---|---|---|---|
    | Restricted research mode | No | No | No (mid-conversation; user starts new session in another profile) |
    | Analyst | Yes (always-on per `analyst.py:68`) | Yes | Yes |
    | Advisor | Yes (always-on per `advisor.py:37`) | Yes | Yes |
    | Dev/admin | TBD per profile config | Likely yes | Likely yes |
    | Sub-agents | Inherits from sub-agent profile selection | Depends | Depends |
    Documented in V2.P10 release notes.

83. **Sentinel file mandatory for migration lock** — Codex R12 noted env-var-only lock can't affect already-running gateway processes. R13 makes sentinel file `~/.gstack/.tool_timing_lock` MANDATORY (not OR env-var). Existing gateway processes check the file at hook entry; new processes inherit env state. Drain semantics specified: (a) fixed grace window (15-30s default, configurable via `--timeout`) AND (b) optional gateway health-check endpoint poll (e.g., `GET /health/in-flight-tool-calls` returns 0). Whichever finishes first proceeds. If neither finishes by `--timeout` and stale rows remain post-update-loop, fail-closed.

84. **Fake-manager scope: minimal `_ServerState`/routing model** — Codex R12 noted existing fake (`test_autonomous_mcp_session_injection.py:46`) only has `inline_servers`/`get_server_names()`/`get_tool_definitions()` — no internal routing state. R13 specifies Phase 1 introduces:
    - Minimal `_ServerState` per-server record (server name, tool list, tool→server mapping)
    - `set_catalog(catalog)` rebuilds all `_ServerState` records and the routing maps
    - Fake's `call_tool(prefixed_tool_name)` dispatches via routing map; returns `ToolNotFoundError` if name not in current catalog
    - Bounded NEW state, not just propagation to existing fields. Phase 1 scope reflects this.

85. **Current Implementation Contract corrected per actual code** — R13 rewrites the handoff projection schema in the Current Implementation Contract section to faithfully reflect the actual `_normalize_handoff_summary` shape (outer metadata + artifact_summary with counts + optional snapshot fields). Removes invented top-N caps for fields that are already bounded counts.

**2026-05-03 (R14 — Codex R13 review FAIL → 5 specific refinements):**

86. **Handoff projection `artifact is None` branch fixed** — Codex R13 verified `_normalize_handoff_artifact_summary` returns `normalized or None` when `artifact is None` (`actions/research.py:1192`). So `artifact_summary` can be `None` or only upstream pass-through fields (no count guarantees). R14 corrects: counts (`assumptions`, `qualitative_factors`, `sources`) are bounded ONLY in artifact-present path; in artifact-absent path, projection helper validates upstream pass-through fields against the same whitelist OR projects to `{}` if `None`. Allow `artifact_summary: null` in response.

87. **Tool-timing DB/lock contract grounded in actual `cost_tracker.py`** — Codex R13 verified `cost_tracker.py:12` uses `_DB_PATH = Path(__file__).parent / "cost.db"` (NOT `~/.gstack/cost_tracker.db` and NOT `COST_TRACKER_DB_PATH` env var). R14 specifies shared config contract: `TOOL_TIMING_DB_PATH` env var (defaults to `<AI-excel-addin>/api/logs/cost.db`); `TOOL_TIMING_LOCK_PATH` env var (defaults to `<DB_PATH dir>/.tool_timing_lock` so lock lives next to DB on same filesystem, addressing Docker/remote concerns). Migration script fails with config-error (exit 2) if lock path is not visible to the running gateway process (verified via env probe or operator declaration). Both gateway and migration script read these env vars from a shared `.env` or service config.

88. **Profile matrix uses actual surfaces, not invented ones** — Codex R13 verified `api/agent/profiles/` has only `analyst.py` and `advisor.py` ProfileConfig modules; sub-agent/skill profiles loaded via frontmatter through `api/agent/skills/profiles.py`; run-once/skill/dev are MODES inside ProfileConfig, not separate profiles. Web/telegram/excel are CHANNEL tiers (per `CHANNEL_TIERS`), not profile types. R14 replaces R13's invented "Dev/admin" with actual surfaces:
    - **Profile types:** analyst, advisor (the only two `ProfileConfig` modules).
    - **Modes (within each profile):** main, run-once, skill, dev — each can have distinct excluded_tools / prompts that affect tool visibility.
    - **Sub-agent / skill profiles:** loaded via skill frontmatter; inherit from a parent profile's tool surface unless overridden in frontmatter.
    - **Channels:** web, telegram, cli, excel-add-in (None) — per `CHANNEL_TIERS`, affect which servers are always-tier vs deferred. `get_handoff_full` reachability follows server-tier per channel.

89. **Fake-manager unknown_tool error matches production structure** — Codex R13 verified production `mcp_client.py:293` returns `(None, {"code": "unknown_tool", "message": "Unknown tool: ..."})` — there is no `ToolNotFoundError` exception. R14 corrects: fake's `call_tool(prefixed_tool_name, args)` returns the same `(None, {"code": "unknown_tool", "message": ...})` tuple shape for unknown tools post-catalog-swap, not an exception. Tests assert on the structured error, not exception type.

90. **Full workspace grep mandatory** — Codex R13 found `agent-orchestrator` and `risk_module-big-impl` in workspace contain `portfolio-mcp` references. Some may be docs/archive/mirrors, but Phase 0g cannot skip them by default. R14 mandates: **run the full `~/Documents/Jupyter` grep FIRST**; THEN classify out-of-scope hits explicitly with rationale (e.g., "archive — preserved unchanged" / "deployment mirror — synced from source repo, no action needed"). The classification artifact lists in-scope vs out-of-scope per repo.

91. **Naming reconciled — single canonical field name `artifact_summary`** — Codex R13 noted Decision #80 says `artifact_summary_projected`; Current Contract says `artifact_summary`. Pick one for compatibility with existing callers. R14 chooses **`artifact_summary`** as the response field name (preserves existing callers); the projection HELPER is named `_project_handoff_summary` (the function), and applies its whitelist to produce the `artifact_summary` field. Decision #80's `_projected` suffix dropped; references aligned.

92. **Effort stable** — Codex R13 didn't push effort up.

**2026-05-03 (R15 — Codex R14 review FAIL → 4 narrow refinements):**

93. **Current Implementation Contract `artifact_summary` text synced** — Codex R14 found Contract still says `artifact_summary` is dict + counts ALREADY bounded; that's only true in artifact-present branch. R15 syncs Contract to match R14's Phase 2 fix: `artifact_summary` is `dict | null`; counts guaranteed only when artifact present.

94. **Migration script DB discovery spec finalized** — Codex R14 noted `risk_module/scripts/migrate_tool_timing.py` doesn't auto-discover `<AI-excel-addin>/api/logs/cost.db` without help. R15 requires `TOOL_TIMING_DB_PATH` env var with exit-2 if absent (no sibling-repo guessing). Documented in shared `.env`. Both gateway and migration script read same env var.

95. **"Modes" reworded as runtime contexts** — Codex R14 verified `ProfileConfig` has no `mode` field/enum. R15 changes wording: NOT "modes are main, run-once, skill, dev" (implies enum); INSTEAD "runtime contexts to audit per profile: default/main, run-once, skill, dev" (entrypoint contexts that affect tool visibility via excluded_tools fields). No "autonomous" / "sub-agent" / "compaction" modes — those are config or routing concerns.

96. **Non-workspace config audit added** — Codex R14 found `~/.claude.json`, Cursor/Codex configs, deployed/remote checkouts can live OUTSIDE `~/Documents/Jupyter`. R15 adds explicit Phase 0d audit targets:
    - `~/.claude.json` (user-global MCP config)
    - Project-local `.claude/settings*.json` outside main workspace
    - Cursor / Codex / Cline / Windsurf / Gemini MCP configs (`~/.cursor/...`, `~/.codex/...`, etc.)
    - Service deployment configs (Fly.io, Render, GitHub Actions, etc. — wherever V2.P10 servers might be deployed)
    - Remote/team checkouts of any of the workspace repos
    These are NOT covered by the workspace grep; require separate manual audit or per-tool config-aware discovery.

97. **Effort stable** — Codex R14 didn't push effort up.

**2026-05-03 (R16 — Codex R15 review FAIL → 2 narrow blockers + 2 minor):**

Codex R15 confirmed all 4 R14 blockers GENUINELY addressed; Contract / Phase 2 / Decisions log are internally consistent on handoff projection. Remaining narrow:

98. **SkillProfile audit fields enumerated** — Codex R15 verified `SkillProfile` (`agent-gateway-dist/agent_gateway/skills.py:51`) exposes tool-visibility-adjacent fields beyond the analyst/advisor `ProfileConfig`: `extra_excluded_tools`, `mcp_servers`, `session_inject_servers`, `tool_packs_enabled`, plus coordinator/worker excluded tools in gateway runner code. R16 adds these as a NEW row in the §"Consumer-site sweep" table — skill-frontmatter consumers must classify against these fields, not just `ProfileConfig`.

99. **Non-workspace audit expanded for env-var-required design** — Codex R15 noted that `TOOL_TIMING_DB_PATH` being REQUIRED makes shell startup files / LaunchAgents / service launch definitions critical (the env var must be propagated to gateway processes). R16 expands Phase 0d non-workspace audit:
    - **Shell startup files:** `~/.zshrc`, `~/.zprofile`, `~/.bashrc`, `~/.bash_profile`, `~/.config/fish/config.fish` — search for any `TOOL_TIMING_*` / `COST_TRACKER_*` / MCP-related env-var declarations.
    - **macOS LaunchAgents/Daemons:** `~/Library/LaunchAgents/*.plist`, `/Library/LaunchAgents/*.plist`, `/Library/LaunchDaemons/*.plist` — services that launch gateway/MCP processes need env propagation.
    - **systemd units** if any Linux/remote deployment exists.
    - **Secret managers** that store env file references (NOT just API tokens): 1Password env injection, Keychain Access entries with env-file content, Doppler, `.envrc` / direnv.
    - Browser extension settings: lower priority (only if an extension directly launches MCP servers).

100. **`ALLOWED_SERVERS` already-present `research-mcp` reference treated as classified rename** — Codex R15 found `AI-excel-addin/api/mcp_client.py:12` `ALLOWED_SERVERS` already contains `research-mcp` today (for the investment_tools server). R16 explicitly classifies: PR0 (cross-repo investment_tools rename) treats this entry as a rename to `research-workbench-mcp`, NOT a blind "add research-mcp" later. V2.P10 cutover then ADDS the new V2.P10 `research-mcp` entry once PR0 has freed the name.

101. **Decisions-log dedup of "R4 framing preserved" blocks** — Codex R15 noted duplicated framing-preservation paragraphs near the end of the doc. Not a blocker but noisy. R16 collapses to single paragraph in Sequencing call section; remove from Decisions-log entries 22, 36, 49, etc. where it's repeated.

102. **Effort stable** — Codex R15 didn't push effort up.

**2026-05-03 (R17 — Codex R16 review FAIL → 3 narrow blockers + 1 non-blocking):**

103. **`SkillProfile.tool_packs` added + exact sub-agent/coordinator surfaces named** — Codex R16 found R16's `SkillProfile` row missed `tool_packs` field (`skills.py:33`); also vague "coordinator/worker excluded tools" needs exact enumeration. R17 expands the row to include: `tool_packs` (visibility-adjacent — shapes deferred tool loading), `CoordinatorConfig.worker_excluded_tools` (`task_registry.py:101`), runner `excluded_tools` (`runner.py:223`), `skills_excluded_tools` (`easy.py:58`), sub-agent `excluded_tools` (`sub_agent.py:71`), inherited/default sub-agent exclusions.

104. **Phase 0d skill-frontmatter scope reconciled** — Codex R16 found Phase 0d still says audit `~/.claude/skills/` AND project-local `.claude/skills/` while consumer table marks external Claude skill dirs out of scope (and the user's instruction prohibits reading those paths). R17 removes `~/.claude/skills/` and project-local `.claude/skills/` from Phase 0d audit targets; explicitly marks them "out of scope; PR0 handles investment_tools rename via separate cross-repo work; V2.P10 cutover does NOT read these paths." Repo-local `api/memory/workspace/notes/skills/` and `tests/skill_evals/` remain in scope.

105. **"Framing preserved" duplicates actually deleted** — Codex R16 found R16 claimed dedup but the doc still has 5 repeats of the framing-preservation block. R17 actually deletes them, leaving one paragraph in the Sequencing call.

106. **Dev-laptop env propagation surfaces added (non-blocking but recommended)** — Codex R16 suggested: VS Code/Cursor workspace `.vscode/settings.json`/`tasks.json`/`launch.json`; devcontainer configs; JetBrains run configs; tmux env propagation; Homebrew services; cron; pm2/supervisor; asdf/nvm. R17 adds these to Phase 0d non-workspace audit as additional surfaces.

107. **Effort stable** — Codex R16 didn't push effort up.

**2026-05-03 (R18 — Codex R17 review FAIL → 1 narrow + 2 cleanup):**

108. **`tool_packs` overclaim corrected** — Codex R17 verified `SkillProfile.tool_packs` is parsed (`skills.py:33, 228, 342`) but no runtime use; only `tool_packs_enabled` is consumed (`tool_handlers.py:908`). R18 changes wording: `tool_packs` is "parsed skill-frontmatter metadata; audit because skill files may encode deferred pack names/server assumptions, but verify whether runtime currently consumes it." Not "shapes deferred tool loading."

109. **Stale "back-compat alias" reference removed** — Codex R17 found Files preview at line 1292 still says "Gateway dispatcher routing — new server name + back-compat alias," contradicting R4+ no-alias framing. R18 changes to "Gateway dispatcher routing — new server name registration (no alias layer; old prefixes return tool-not-found post-cutover per straight-refactor framing)."

110. **Phase 0 criterion count synced** — Codex R17 found "canonical 7-criterion list (0a-0g)" but list now runs 0a-0h (8 criteria after R12 added 0g consumer-classification step). R18 corrects to "canonical 8-criterion list (0a-0h)."

111. **Effort stable** — Codex R17 confirmed.

**2026-05-04 (R19 — mid-Phase-0 naming correction; PR0 scope simplified):**

Phase 0b + 0c shipped (commits `fdb00f67` + `5f0c7329`). When investigating PR0 dispatch, Claude inspected the actual `investment_tools/research/server.py:53-54` and `~/.claude.json` and found the plan's naming model was wrong throughout R1–R18:

112. **Investment_tools server's actual FastMCP name is `research-workbench-mcp`** — not `research-mcp` as assumed in R1–R18. The plan repeatedly framed PR0 as "rename the investment_tools `research-mcp` server" but the server already names itself `FastMCP("research-workbench-mcp", ...)` at `investment_tools/research/server.py:54`. The `research-mcp` string lives only in user-global `~/.claude.json` (catalog key) and AI-excel-addin's `tool_catalog.py` + `server_policies.py` (catalog references). Gateway addresses servers by catalog key, not by `serverInfo.name`, so the names have always been mismatched and worked fine.

113. **R19 naming decision: keep `research-workbench-mcp`, do NOT introduce `research-workbench-mcp`.** Three reasons:
    - Aligns the catalog key to the FastMCP name the server already reports (`serverInfo.name`).
    - "Research workbench" is descriptively accurate for the studies/findings/signals/screens scope (Codex R1 noted `research-workbench-mcp` "undersells the findings/studies/actions surface" — the same critique applies in reverse to ANY narrower name; "workbench" captures all of it).
    - **Zero investment_tools commit required.** No `FastMCP()` rename, no investment_tools repo work in PR0.

114. **PR0 scope simplified — catalog-key rename only:**
    - **PR0a (manual, user — `~/.claude.json`):** add second catalog entry `research-workbench-mcp` pointing at the same `python3 -m research.server` command. Existing `research-mcp` entry stays during transition. (Cannot delegate to Codex — file contains user-secret tokens.)
    - **PR0b (Codex, AI-excel-addin):** rename `research-mcp` → `research-workbench-mcp` in `tool_catalog.py:48,52,56` + `server_policies.py:350-375` (and any other AI-excel-addin code references). This is the only code-change PR in PR0.
    - **PR0c (manual, user — `~/.claude.json`):** remove old `research-mcp` entry once PR0b verified working.
    - **PR0d (no longer applicable):** investment_tools FastMCP rename is no-op since the server already reports `research-workbench-mcp`.

115. **Plan-doc replace-all `research-workbench-mcp` → `research-workbench-mcp`** — 17 references swept in this revision.

116. **Effort impact: ~0.5–1 week saved** in Phase 0 — investment_tools dual-registration / publish / re-publish work no longer required. Full split now ~5.5–7.5 weeks; Phase 1-only ~3.5–4.5 weeks.

**2026-05-04 (R20 — mid-Phase-0 cross-session resolution + tool-surfacing finding):**

117. **PR0 shipped end-to-end:**
    - PR0a (manual user-edit, 2026-05-04): added `research-workbench-mcp` catalog entry to `~/.claude.json`. Backup at `~/.claude.json.bak.20260504-121210`.
    - PR0b (commit `f7971e4` in AI-excel-addin, 2026-05-04): renamed catalog references in 29 AI-excel-addin code/test/doc files.
    - PR0c (manual user-edit, 2026-05-04): removed old `research-mcp` catalog entry from `~/.claude.json`. Backup at `~/.claude.json.bak.20260504-133458`. Name `research-mcp` now free for V2.P10's new server.

118. **Cross-session conflict with parallel A6e dev-CLI session resolved.** The parallel A6e session (commit `cc32382` plan doc + uncommitted impl in worktree) had begun a reverse-rename `research-workbench-mcp` → `research-mcp` after diagnosing "load_tools rejected by gating" in AI-excel-addin runtime. PR0a's `~/.claude.json` add of `research-workbench-mcp` resolves their original blocker — `research-workbench-mcp` is now a valid catalog key. Their pending uncommitted reverse-rename can be `git restore`'d by them since the underlying gating issue is gone. V2.P10 won this naming question by shipping first; coordination handled by user.

119. **Tool-surfacing investigation deferred to follow-up session (NOT blocking V2.P10).** Post-PR0a/c verification revealed: investment_tools research server's tools (`add_finding`, `search_findings`, `screen_hit_stats`, `submit_research_task`, etc.) do NOT surface in Claude Code's tool catalog under either `research-mcp` (pre-PR0c) or `research-workbench-mcp` (post-PR0a). Server boots fine standalone (`python3 -m research.server` from investment_tools cwd starts cleanly). Pre-existing issue (tools were also absent from the disconnect list at session start, so weren't loading pre-edit). User will diagnose with separate Claude session. Does NOT block V2.P10 Phase 1 cutover — V2.P10's catalog-name rename is independent of whether the server surfaces tools to Claude Code.

    **2026-05-04 follow-up — diagnosed + workaround applied (filed as F63):** Claude Code's stdio spawn did not apply the `cwd` field for any of 5 servers rooted at `cwd=/Users/henrychien/Documents/Jupyter/investment_tools` (`research-workbench-mcp`, `jobs-mcp`, `options-mcp`, `fred-mcp`, `macro-mcp`). Per-server logs all showed `ModuleNotFoundError: No module named '<subpkg>'` — Python correctly fails when cwd isn't applied. Servers with cwds that lack a root `__init__.py` (`finance-cli`, `fmp-mcp`) work fine; `investment_tools/__init__.py` is the only structural difference. Manual `subprocess.run([...], cwd=investment_tools)` works → not a Python issue. Workaround: added `PYTHONPATH=/Users/henrychien/Documents/Jupyter/investment_tools` to the env block of all 5 entries in `~/.claude.json` (backup `~/.claude.json.bak.20260504-135344`). Restart Claude Code to pick up. Bug filed at `docs/planning/completed/F63_CLAUDE_CODE_MCP_CWD_BUG.md`; upstream bug to file with Anthropic separately.

120. **Phase 0 risk_module/AI-excel-addin work complete:**
    - `f3420a47` plan R18 PASS
    - `fdb00f67` Phase 0b shared-module refactor
    - `5f0c7329` Phase 0c second FastMCP entrypoint
    - `ebdae66c` plan R19 naming correction
    - `f7971e4` (AI-excel-addin) PR0b catalog rename
    - `f915eb76` Phase 0e/0f/0g audit artifacts
    - `5adf7fdd` Phase 0h migration script + tests + runbook
    - `1a1f444` (AI-excel-addin) tool_timing_hook sentinel + cost_tracker DB-path env support
    - PR0a/c manual user-edits to `~/.claude.json`

121. **Ready for Phase 1 cutover** — atomic PR moving the 4 corpus tools (`filings_search`, `transcripts_search`, `filings_list`, `transcripts_list`) from `mcp_server.py` (portfolio-mcp) registration to `mcp_server_research.py` (research-mcp) registration, plus consumer sweep + migration script run.

---

## Current Implementation Contract (R19 — authoritative quick reference, Codex R18 PASS + R19 naming correction)

**This section is the source of truth for impl handoff. The Decisions log above preserves history; if any historical statement contradicts this section, this section wins.**

### Architectural shape
- **Strategy:** straight refactor (NOT cross-listing). Each tool group ships in one cutover PR; no transition window. Old prefixes return tool-not-found errors at cutover.
- **Process model:** Option B default (separate process, second FastMCP entrypoint at `mcp_server_research.py`). Option A (same-process two instances) requires Phase 0 spike with 5-criterion harness PASS.
- **Effort:** ~6-8 weeks full split / ~4-5 weeks Phase-1-only.

### Naming
- New V2.P10 server: **`research-mcp`** (always-tier across all 4 channels).
- Existing investment_tools server: catalog key renamed `research-mcp` → **`research-workbench-mcp`** via PR0 (R19 — `~/.claude.json` user-edits + AI-excel-addin code edit; no investment_tools commit). The server's FastMCP name was already `research-workbench-mcp`; only catalog references move.
- portfolio-mcp keeps its name; loses the moved tools.

### Tools moving (Phase 1: 4 envelope-keyed; Phase 2c: 13 foundational reads)
- **Phase 1 (4):** `filings_search`, `transcripts_search`, `filings_list`, `transcripts_list`
- **Phase 2a/2b:** payload enrichment in core/corpus + mcp_tools/corpus + extractor extension
- **Phase 2c Group A (4):** `filings_read`, `transcripts_read`, `filings_source_excerpt`, `transcripts_source_excerpt`
- **Phase 2c Group B (13):** `list_research_files`, `read_research_thread`, `get_research_brief`, `get_handoff_summary` (NEW projection tool), `thesis_list`, `thesis_read`, `thesis_latest_scorecard`, `thesis_list_decisions_log`, `thesis_list_links`, `get_diligence_state`, `list_process_templates`, `get_process_template`, `get_action_history`
- **Stays on portfolio-mcp:** `get_handoff_full` (NEW for full-artifact callers), `start_research`, `activate_diligence`, `build_model`, `compare_scenarios`, `analyze_stock`, `industry_peer_comparison`, `get_model_insights`, `get_price_target`, `get_model_build_context`, all editorial/thesis WRITES, all diligence WRITES.

### Phase 0 deliverables (5 things must land before Phase 1)
1. **3-module shared refactor:** `mcp_middleware.py` (UserIdMiddleware + ContextVars), `mcp_lifecycle.py` (pool + watcher + atexit), `mcp_bootstrap.py` (stdout/.env/validation/nest_asyncio). `mcp_bootstrap.py` MUST be import-silent (stdlib + dotenv + nest_asyncio only at module level); fallback: inline stdout redirect at top of each server file.
2. **Option B launch contract verified:** `mcp_server_research.py` boots independently; `services.yaml` entry registered; MCP client config snippet for `~/.claude.json` validated; `services-mcp` `service_status("risk_module_research_mcp")` healthy. Tool registration via direct decorator (`mcp_research.tool()(_corpus_filings_search)`) preferred to preserve schema; fallback uses `functools.wraps`.
3. **Cross-repo PR0 sequence landed (R19):** PR0a (`~/.claude.json` adds `research-workbench-mcp` catalog entry — manual user-edit) → PR0b (AI-excel-addin renames `research-mcp` → `research-workbench-mcp` in `tool_catalog.py` + `server_policies.py` — Codex) → PR0c (`~/.claude.json` removes old `research-mcp` entry — manual). No investment_tools commit.
4. **Consumer-site inventory frozen** per §"Consumer-site sweep" + §"`get_handoff` consumer classification" (with grep command + classification table).
5. **`migrate_tool_timing.py` script designed:** path = `risk_module/scripts/migrate_tool_timing.py`, exit codes 0/1/2, `--dry-run`/`--since`/`--max-iter`/`--timeout`/`--resume` flags, fail-closed recovery (catch-up loop until zero or timeout/max iter; if nonzero, FAIL + keep lock + print recovery command).

### Phase 1 cutover (single PR)
- Cutover PR moves the 4 Phase 1 tools from portfolio-mcp registration to research-mcp registration.
- Same PR sweeps ALL consumer sites per §"Consumer-site sweep" (CHANNEL_TIERS, ServerPolicy, ALLOWED_SERVERS, agent profiles incl. ProfileConfig 6 surfaces, repo-local skill evals with classified replacement, tests, fixtures, prompts, telemetry queries).
- Same PR runs persisted-record migration script for the 9 record classes (incl. `tool_timing` SQLite with maintenance-lock + post-UPDATE catch-up loop + fail-closed recovery).
- Phase 1 acceptance verifies: middleware transport test (canary fake tool); Slice A envelope fires; new-session sees tools correctly; stale-session gets visible tool-not-found errors; `_MCP_META_INJECT_SERVERS` extended; ServerPolicy entries with `known_read_tools` + empty `known_write_tools`.

### Phase 2 (split into 2a → 2b → 2c)
- **2a:** Payload enrichment in `core/corpus/*` + `mcp_tools/corpus/*` (echo `document_id`, `section`, `char_start`, `char_end`, `url`).
- **2b:** Slice A `extract_sources` extended for `filings_read`/`transcripts_read`/`*_source_excerpt`.
- **2c:** Cutover Group A (4 corpus read/excerpt) + Group B (13 foundational reads). Per-tool boundedness verified (row-count caps for 9 tools per R6 audit + payload-size projection contract for 4 tools per R7/R10/R11 — `read_research_thread`, `get_handoff_summary`, `get_research_brief`, `thesis_latest_scorecard`).

### Boundedness rule
- Always-tier eligibility: read-only AND user-owned AND bounded output AND no artifact creation AND no side effects AND named justification.
- Bounded output = both row-count cap AND payload-size cap (with projection contract: `truncated`/`original_char_count`/`message_id`/`offset`/`cursor` + continuation tool or summary+excerpts shape).
- **`_project_handoff_summary` whitelist (R15 — fully grounded in actual code, both branches):**
  - **Outer metadata fields (always present, all bounded):** `handoff_id` (int), `version` (int), `ticker` (string), `status` (string), `artifact_summary` (**`dict | null`** — R15 fix per Codex R14)
  - **Outer optional fields (when present, all bounded):** `research_file_id` (int), `created_at` (ISO string), `finalized_at` (ISO string)
  - **STRIPPED:** `artifact` field (full body — only available via `get_handoff_full` on portfolio-mcp)
  - **Snapshot fields stripped from top-level** (currently added by `_normalize_handoff_summary:1174` when artifact present): `schema_version`, `_original_schema_version`, `thesis_strategy`, `model_ref_present`, plus duplicate `differentiated_view_count`/`invalidation_trigger_count`/`industry_analysis_present`/`scorecard_summary_status`. These ride along inside `artifact_summary` (single canonical location); strip the top-level duplicates.
  - **`artifact_summary` content** (per `_normalize_handoff_artifact_summary:1188-1212`, BOTH branches):
    - **When `artifact is None`:** helper returns `normalized or None` (`:1192`); R15 projection passes through upstream pass-through dict (with `thesisStatement` → `thesis_statement` rename) validated against whitelist, OR returns `null`. Counts NOT guaranteed in this path.
    - **When `artifact present`:** all whitelist fields populated via `setdefault` + count derivations (`:1200-1206`).
    - **Whitelisted fields:**
      - `thesis_statement` (string, **CAP at 1000 chars** with `truncated` flag if exceeded)
      - `assumptions` (int count — bounded only when artifact present)
      - `qualitative_factors` (int count — bounded only when artifact present)
      - `sources` (int count — bounded only when artifact present)
      - `differentiated_view_count` (int)
      - `invalidation_trigger_count` (int)
      - `industry_analysis_present` (bool)
      - `scorecard_summary_status` (optional string, **CAP at 200 chars**)
  - **CamelCase normalization:** only `thesisStatement` → `thesis_statement` (per `actions/research.py:1188-1189` actual rename); upstream `routes.py:247` fallback also emits `thesisStatement`/`assumptions`/`sources` as fallback fields. R15 implementer either (a) handles the 1 known camelCase variant explicitly, OR (b) implements a generic camelCase→snake_case normalizer for forward-compat.
  - **Fail closed:** if upstream sends snake_case fields not on the whitelist (after camelCase normalization), projection helper rejects with explicit error (caller must extend whitelist).

### `get_handoff_full` access UX (R14 — actual surfaces per Codex R13)

**Profiles** (the only two `ProfileConfig` modules per `api/agent/profiles/`):
- **Analyst** (`analyst.py:68`): `portfolio-mcp` always-on; `load_tools` flow available; `get_handoff_full` reachable.
- **Advisor** (`advisor.py:37`): `portfolio-mcp` always-on; `load_tools` flow available; `get_handoff_full` reachable.

**Runtime contexts to audit per profile** (R15 — Codex R14 verified `ProfileConfig` has no `mode` enum; these are entrypoint contexts that affect tool visibility via `excluded_tools` fields):
- default/main, run-once (`run_once_excluded_tools`), skill (`skill_session_id_template`-loaded), dev (`dev_excluded_tools`) — for both analyst and advisor profiles. Verify each context's exclusion list does not unexpectedly hide `get_handoff_full` for in-scope cases.

**Restricted research system prompt** (`system_prompt.py:1185`): no `load_tools` mid-conversation; `get_handoff_full` NOT reachable. User must start a new session in analyst or advisor profile to access full artifact.

**Sub-agent / skill profiles** (loaded via skill frontmatter through `api/agent/skills/profiles.py`): inherit parent profile's tool surface unless overridden in frontmatter. Reachability depends on parent.

**Channels** (per `CHANNEL_TIERS`, NOT profile types — Codex R13 clarification):
- web, telegram, cli, excel-add-in (None) — affect which servers are always-tier vs deferred. `get_handoff_full` reachability follows server-tier per channel.

Documented in V2.P10 release notes.

### Fake-manager extension (Phase 1 fixture work)
- Extend `_FakeMcpClientManager` (`tests/test_autonomous_mcp_session_injection.py:46`).
- `set_catalog(catalog)` MUST update internal state read by ALL of: `get_server_names`, `get_server_catalog`, `get_tool_definitions`, `get_server_tool_definitions`, `is_mcp_tool`, `get_server_for_tool`, `resolve_tool_name`, `call_tool` (routing path: `_tool_to_server`, `_servers`, `_prefixed_to_original` equivalents in fake).
- Tests verify both discovery (server-list, tool-list) AND dispatch (`call_tool` returns "tool not found" for old-prefix names post-swap).

### Phase 4 cleanup
- F56 audit (a) + (b); retire `_RESEARCH_AUTO_LOAD_SERVERS` block.
- Living-docs sweep: CLAUDE.md, AGENTS.md, README.md, `docs/interfaces/mcp.md`, `docs/reference/MCP_SERVERS.md`, `docs/planning/CORPUS_ARCHITECTURE.md`, `AGENT_INFRASTRUCTURE.md`, V2_P2_*.
- Close F56 + F62 + C.4 follow-ups as moot.

---

## Why now

Across today's Slice C.2 testing + the F56 fix history, a clear pattern emerged: **the corpus tools' "deferred-tier" status is the bottleneck for citation discipline**, and stacking workarounds (F56 auto-load, prompt nudges, C.4) treats the symptom rather than the architectural cause.

**Symptom stack tracing back to one root cause:**

| Symptom | Workaround | What it really wants |
|---|---|---|
| Hank routes corpus queries to `get_filings` (edgar-financials) instead of `filings_search` (portfolio-mcp) | F56 auto-load + tool description rewrites (**SHIPPED 2026-05-02, commit `92830bc` — workaround the split retires retroactively**) | corpus tools always-loaded |
| F56 doesn't fire in TUI because it requires `mode=research` flag the TUI doesn't pass | **F62** (filed 2026-05-04; preempted by V2.P10 Phase 1) | corpus tools always-loaded |
| Slice A's citation envelope only fires for portfolio-mcp tools, not edgar-financials | **C.4** (cross-MCP citation discipline) | corpus tools always-loaded with envelope contract universal |
| F58 (entity resolution): BM25 misses euphemistic disclosures — needs query-expansion logic | F58 fix paths | unrelated (real corpus search gap) |
| F57 (universe alias gap): GOOG/GOOGL share-class aliasing | F57 fix | unrelated (universe selection gap) |

**Three of those four wants the same thing**: corpus tools should be in the always-tier so the LLM picks them by default. The current architecture co-locates corpus tools with portfolio-management tools in `portfolio-mcp`, forcing the entire server into deferred-tier (because portfolio-management tools are large, expensive, mutating, and shouldn't all be loaded by default). The corpus tools — small, narrative, read-only — get pulled into deferred-tier as collateral damage.

**The architectural correction**: separate corpus tools (and other research-workflow tools currently in portfolio-mcp) into their own MCP server. Make that server always-tier across all channels. Eliminate the workarounds.

---

## Naming + cross-repo dependency

The name `research-mcp` is currently taken by a **different** MCP server in the `investment_tools` repo. That server tracks research outputs (findings/signals/studies/screen-hits/actions) — its tools include `add_finding`, `create_study`, `submit_research_task`, `link_signal`, `screen_hit_stats`, `search_findings`. Mental model: screens → **signals** → findings → actions → studies. Already registered in `CHANNEL_TIERS` defer-tier for `web`/`telegram`/`cli` channels (`api/agent/shared/tool_catalog.py:48,52,56`) and policy-listed at `api/agent/shared/server_policies.py:350-375`.

**Resolution chosen 2026-05-02:**

- **R19 update:** the investment_tools server's actual `FastMCP("research-workbench-mcp", ...)` name (per `investment_tools/research/server.py:54`) is unchanged — only the catalog key referring to it changes. The `research-mcp` string lives only in user-global `~/.claude.json` and AI-excel-addin's `tool_catalog.py` + `server_policies.py`. Renaming the catalog key everywhere it references the investment_tools server frees the name `research-mcp` for V2.P10.
- **New V2.P10 server** keeps the name **`research-mcp`** as drafted in this plan. Tool inventory is genuine research workflow — corpus search/read, briefs, threads, diligence, theses, editorial — and matches the brand-locked "Personal AI investment analyst" framing without overreaching like `analyst-mcp` would.

**Out of scope of this plan:** the investment_tools repo itself does NOT need code changes. PR0a/c are user-config edits; PR0b is an AI-excel-addin code change. No investment_tools commit, no PyPI/dist publish.

### Cross-repo sequencing (R19 — catalog-key rename only, no investment_tools commit)

PR0 lands as a **three-step catalog-key compatibility window** in user-global config + AI-excel-addin code. R19 simplification: the investment_tools repo is untouched; only the catalog key referencing the investment_tools server is renamed.

1. **PR0a — `~/.claude.json` (manual, user-edit):** add a SECOND catalog entry `research-workbench-mcp` pointing at the same `python3 -m research.server` command (cwd=investment_tools). Existing `research-mcp` entry stays. Both names route to the same investment_tools server. **Cannot delegate to Codex** — `~/.claude.json` contains user-secret tokens (e.g., `ANTHROPIC_AUTH_TOKEN`). User edits manually.
2. **PR0b — AI-excel-addin (Codex):** rename `research-mcp` → `research-workbench-mcp` in `tool_catalog.py:48,52,56` + `server_policies.py:350-375`. Sweep any other AI-excel-addin code referencing the old catalog name (full repo grep). Update gateway dispatcher routing if it has its own catalog references. Update any test fixtures asserting on the old catalog key. Ship + verify.
3. **PR0c — `~/.claude.json` (manual, user-edit):** remove old `research-mcp` catalog entry once PR0b is verified working. Now `research-mcp` name is free for V2.P10 use.
4. **Phase 1+ of this plan** then proceeds.

**Rollback per step:**
- PR0a fails (e.g., JSON syntax error) → user reverts `~/.claude.json` manually; original `research-mcp` entry intact; gateway loads as before.
- PR0b fails → revert AI-excel-addin commit; both catalog entries still in `~/.claude.json` so old AI-excel-addin code still works.
- PR0c fails → user re-adds the old entry to `~/.claude.json`; restores dual-registration.

**Active session behavior:** clients with already-loaded `research-mcp` tool surface continue to work through PR0a + PR0b (both catalog keys route to the same server). Sessions that connect during PR0c → Phase 1 see the new V2.P10 `research-mcp` server and may need to call `load_tools` once. Document this in release notes.

**No investment_tools commit / no PyPI/dist publish.** R19 simplification: the FastMCP name `research-workbench-mcp` was already the server's actual identity; the `research-mcp` mismatch was always at the catalog layer.

---

## risk_module server architecture (R2 — new section)

`mcp_server.py:303` instantiates a single `FastMCP("portfolio-mcp", ...)` with shared middleware (`UserIdMiddleware` at line 357-376) and shared tool registration via `@mcp.tool()` decorators on functions imported across `mcp_tools/*`. The split is NOT a directory move — it requires a second FastMCP entrypoint that:

1. **Owns its own server instance** — `FastMCP("research-mcp", ...)` declared in either the same module (two `mcp` instances) or a sibling module (`mcp_server_research.py`).
2. **Shares the same middleware stack** — `UserIdMiddleware` and any future middleware MUST attach to both servers; user-identity propagation cannot diverge.
3. **Shares the same lifespan/db pool** — corpus reads and portfolio reads use the same connection pool. Two FastMCP instances can register the same `lifespan=pool_cleanup` callback if same-process; if separate-process, pool initialization must be coordinated.
4. **Is reachable by the gateway** — agent-gateway-dist must be configured (env vars, MCP client config) to connect to BOTH servers. This is a config + packaging change, not just code.

### Process model — R3 default: Option B

| Option | Tradeoffs | R3 status |
|---|---|---|
| **A. Same-process, two FastMCP instances** | Simpler deployment, shared db pool + middleware automatic. **Risk verified by Codex R2:** FastMCP 3.2.4's `mcp.run()` runs one server per process; `mount()`/`import_server()` mount tools INTO the parent server, not as independently-named MCP servers. | Requires Phase 0 spike to prove. NOT default. |
| **B. Separate process, second entrypoint** | Clean isolation; each process runs its own `mcp.run()`. Doubles infra (two PIDs, two pool inits, two health checks). Service catalog (`services-mcp`) needs second entry. Middleware must be kept in lockstep across both entrypoints (shared module). | **R3 default.** |
| **C. Single process, single FastMCP, server-name aliasing at registration** | FastMCP accepts server name at instance level only, not per-tool. Not viable. | Eliminated. |

**R3 default: Option B.** A is achievable only if a Phase 0 spike proves two FastMCP instances expose two independently-reachable MCP server endpoints under the actual gateway transport.

### Phase 0 spike — A-validation harness (if attempting Option A)

To prove A viable, the spike must demonstrate ALL of:

1. **Two named server endpoints reachable concurrently:** `tools/list` calls return distinct tool sets per server name.
2. **Middleware fires per instance:** `UserIdMiddleware` attached to both servers handles requests independently; user-identity propagation works for tools on either server.
3. **Lifespan fires per instance:** `lifespan=pool_cleanup` registered on both; pool init/teardown coordinates correctly.
4. **Gateway routing resolves correctly:** `get_server_for_tool()` (per `agent-gateway-dist/agent_gateway/tool_dispatcher.py:405`) returns the expected server for tools registered on each instance.
5. **MCP client config registers both:** `~/.claude.json` (or equivalent) lists both `portfolio-mcp` and `research-mcp` with the same stdio transport command.

If ANY of these fails, fall back to B.

### Option B target launch contract (R5 — concrete spec for handoff)

Per Codex R4: the plan-doc itself needs a concrete launch contract, not just "Phase 0 will figure it out." R5 specifies the target shape; values can be finalized during Phase 0 spike.

**Module + entrypoint:**
- New file at repo root: `mcp_server_research.py` (mirror of `mcp_server.py` shape).
- Instantiates `mcp_research = FastMCP("research-mcp", instructions="Research workflow + corpus tools for Hank", lifespan=pool_cleanup)`.
- **MANDATORY (R6 — per Codex R5):** `mcp_server_research.py` MUST NOT import from `mcp_server.py`. Doing so would re-instantiate `portfolio-mcp` as a module-import side effect (current `mcp_server.py:301` registers tools at import time). Instead, both server files import shared middleware/lifespan from a NEW shared module: `mcp_middleware.py` at repo root.
- Tool registration via `@mcp_research.tool()` on the moved tool functions imported from `mcp_tools/corpus/*` (Phase 1) and additional moved tools (Phase 2c).
- `if __name__ == "__main__": mcp_research.run()` at the bottom (mirror of `mcp_server.py:4037`).

**Mandatory shared-module refactor (R7 — expanded from R6 per Codex R6):**

Three shared modules at repo root, each `mcp_server.py` and `mcp_server_research.py` imports from them; neither imports from the other.

**1. `mcp_middleware.py`** — middleware + identity:
- `UserIdMiddleware`, `_resolve_email_for_user_id`, `_email_cache`, `_USER_EMAIL_CTX`, `_GATEWAY_REQUEST_ACTIVE` (currently at `mcp_server.py:317-376`)

**2. `mcp_lifecycle.py`** — lifespan + cleanup + watcher state:
- `pool_cleanup` lifespan, `_atexit_cleanup`, `_close_pool` (currently at `mcp_server.py:283-299`)
- **`_order_watcher` state + explicit start/stop API** (R7 added per Codex R6): `_order_watcher` module global currently set in `_run_server()` at `mcp_server.py:4015`; expose `start_order_watcher_if_enabled()` and `stop_order_watcher()` so portfolio-only watcher startup can stay in `mcp_server.py` while cleanup is callable from either server's atexit.

**3. `mcp_bootstrap.py`** (R7 added per Codex R6; R8 ordering specified per Codex R7) — server bootstrap prelude:
- stdout-to-stderr redirection (currently at `mcp_server.py:18`-area)
- `.env` loading
- `_validate_environment()`
- `nest_asyncio.apply()` policy
- **Ordering policy (R8 + R9 import-safety carveout per Codex R8):** `bootstrap()` runs as the FIRST executable statement in each server file, BEFORE any repo-local imports (`from mcp_tools...`, `from actions...`, etc.). Stdout redirection must cover noisy import-time prints, not just FastMCP construction. **R9 carveout:** `mcp_bootstrap.py` itself MUST import only stdlib + import-silent dependencies at module level; all repo-local/env/logging work happens INSIDE `bootstrap()` after stdout redirection. If `mcp_bootstrap.py` cannot be made import-silent (e.g., needs to import a noisy logging-config module), fall back to keeping the stdout redirect block inline at the top of each server file (current `mcp_server.py:18` pattern) BEFORE importing `mcp_bootstrap`. Pattern in `mcp_server_research.py`:
  ```python
  # mcp_server_research.py
  from mcp_bootstrap import bootstrap; bootstrap()  # MUST be first executable line
  # mcp_bootstrap.py imports ONLY stdlib at module level; bootstrap() does the rest
  # Now safe to import the rest
  from mcp_middleware import UserIdMiddleware
  from mcp_lifecycle import pool_cleanup
  from mcp_tools.corpus.filings import filings_search
  ...
  mcp_research = FastMCP("research-mcp", lifespan=pool_cleanup)
  ```
- Clear stdout restore point before `mcp.run()` for any post-startup logging that should reach the client (current `mcp_server.py` pattern preserved).

**Refactor sequencing:**
- Phase 0b deliverable: all three shared modules created. Existing `mcp_server.py` refactored to import from them. Tests pass with single-server unchanged behavior.
- THIS LANDS BEFORE the second entrypoint stands up (Phase 0c).
- Tests pass after the refactor with the existing single-server still working before second entrypoint introduced.

**Tool registration extraction policy (R8; R9 schema-drift policy per Codex R8):**

Moved tool wrapper functions are physically defined in `mcp_tools/<module>.py` (where they already live for corpus tools). Registration on the new server happens inside `mcp_server_research.py`. **`mcp_server_research.py` is registration-only** — no tool wrapper logic lives in this file. This avoids the temptation to `import mcp_server` (which would re-instantiate `portfolio-mcp`).

**Schema-drift prevention (R9 — Codex R8):** prefer FastMCP-native registration of the imported function directly to preserve signature/docstring/schema from the single source. Two acceptable patterns:

1. **Direct registration (preferred if FastMCP supports):**
   ```python
   from mcp_tools.corpus.filings import filings_search as _corpus_filings_search
   mcp_research.tool()(_corpus_filings_search)  # registers in place; schema from source
   ```
2. **Wrapper with `functools.wraps` (fallback if FastMCP needs a wrapper):**
   ```python
   import functools
   from mcp_tools.corpus.filings import filings_search as _corpus_filings_search

   @mcp_research.tool()
   @functools.wraps(_corpus_filings_search)  # preserves __wrapped__, __doc__, signature
   def filings_search(*args, **kwargs):
       return _corpus_filings_search(*args, **kwargs)
   ```

**Forbidden:** redeclaring the function signature/docstring inline in `mcp_server_research.py`. Manual duplication risks silent drift between old (portfolio-mcp pre-cutover) and new (research-mcp post-cutover) registrations.

**Phase 0b spike includes:** verify which pattern FastMCP supports correctly across `tools/list` schema serialization, MCP client tool-call dispatch, and Slice A `canonical_tool_name` resolution. Document the chosen pattern as repo convention.

**Launch command:**
- `python3 mcp_server_research.py` (mirror of how `mcp_server.py` runs today).
- Same cwd as risk_module repo root; same env vars (`.env` loaded by FastMCP/middleware path).

**`services.yaml` entry** (new entry alongside existing `risk_module` service):
```yaml
risk_module_research_mcp:
  command:
    - python3
    - mcp_server_research.py
  description: Research MCP server (corpus + research workflow tools)
  env_file: .env
  env:
    PYTHONPATH: brokerage-connect
  expected_cmd:
    - python3
    - mcp_server_research.py
```

**MCP client config snippet** (added to `~/.claude.json` and any team `.claude.json` that registers `portfolio-mcp` today — exact existing path TBD in Phase 0d inventory):
```json
"research-mcp": {
  "command": "python3",
  "args": ["mcp_server_research.py"],
  "cwd": "/Users/henrychien/Documents/Jupyter/risk_module",
  "env": {
    "PYTHONPATH": "brokerage-connect"
  }
}
```

**Health/smoke command** (added to a Phase 0 deliverable script):
- `python3 -c "import asyncio; from mcp_server_research import mcp_research; ..."` to verify server boots and `tools/list` returns expected tool set.
- Or invoke via `services-mcp` `service_status` once registered.

**Shared middleware import pattern:**
- Factor `UserIdMiddleware`, `_resolve_email_for_user_id`, `_email_cache` etc. from `mcp_server.py:317-376` into a shared module (`mcp_middleware.py` at repo root).
- Both `mcp_server.py` and `mcp_server_research.py` import from there.
- Avoids drift; one source of truth for middleware logic.

**Process model — same db pool?**
- Each process initializes its own pool via `lifespan=pool_cleanup`. Two processes = two pools. Acceptable for read-heavy research-mcp workload; pool-size tuning per process if needed.
- If pool contention observed, consider PgBouncer (already in services.yaml) absorbing the second process's connections.

**Phase 0 acceptance for the launch contract:**
- `mcp_server_research.py` boots independently and serves `tools/list` (even with zero tools registered initially is OK — verifying transport).
- `services.yaml` entry registered; `services-mcp` `service_start("risk_module_research_mcp")` succeeds.
- MCP client config shape verified against `~/.claude.json` schema; can be added without breaking existing `portfolio-mcp` registration.
- Shared middleware module factored; both servers import + attach successfully.

### Diagnostics + identity surface

`get_mcp_context` at `mcp_server.py:380-409` hard-codes `"server": "portfolio-mcp"` in its response (line 396). After the split, this tool either (i) becomes per-server with each instance returning its own name, or (ii) is moved to research-mcp and reports both servers' status. Decide during Phase 0.

---

## Hidden dependencies (R2 — new section)

Codex review surfaced two hidden dependencies that must be addressed before retiring F56 or claiming the split is complete:

### 1. `_MCP_META_INJECT_SERVERS` (AI-excel-addin/api/agent/interactive/runtime.py:97)

```python
_MCP_META_INJECT_SERVERS = frozenset({"portfolio-mcp"})
```

This frozenset declares which servers receive `meta.user_id` injection from the gateway. It pairs with risk_module's `UserIdMiddleware` (`mcp_server.py:357-376`), which reads `meta.user_id` to resolve `users.email` for tools that need user-scoped DB access (research files, theses, diligence sections, portfolios).

**Implication:** if research-mcp tools need user-scoping (they do — research files, theses, diligence are all user-owned), `_MCP_META_INJECT_SERVERS` must be extended to include `research-mcp`, AND risk_module's research-mcp instance must attach the same `UserIdMiddleware`. Skipping this breaks user identity propagation silently — tools fall back to env-var resolution or fail with `UserContextError`.

**Acceptance addition:** explicitly verify user-scoped tools in research-mcp resolve `users.email` correctly across all channels (Excel/web/telegram/cli/TUI).

### 2. F56 auto-load (`_RESEARCH_AUTO_LOAD_SERVERS`)

Per Decision #11, F56 retirement requires:

- **Audit (a):** all research-mode entrypoints actually load `research-mcp` (always-tier registration in `tool_catalog.py` is necessary but not sufficient — verify the LLM sees research-mcp tools in its catalog without a `load_tools` call).
- **Audit (b):** `_MCP_META_INJECT_SERVERS` updated coherently (per dependency #1 above) — otherwise auto-loading research-mcp without meta injection produces a worse failure mode than the current F56 workaround.

Until both audits pass, the F56 block at `runtime.py:87, 461-481` stays in place as belt-and-suspenders. Removal becomes a dedicated post-split commit, not part of the split itself.

### 3. `get_mcp_context` server-name hardcoding

Per §"risk_module server architecture", `mcp_server.py:396` returns `"server": "portfolio-mcp"`. Any consumer asserting on this field needs updating when the diagnostic moves or splits.

---

## Consumer-site sweep + persisted-record migration (R4 — replaces "Alias canonicalization scope")

> **R4 reframe:** R3 designed a long-lived alias map across 10 layers because it assumed a transition window where old + new prefixes co-exist. R4 abandons that. Each cutover PR updates ALL consumers atomically; old prefixes simply stop working at cutover (return tool-not-found errors, which are visible failures, not silent drift). Persisted records that need to replay through the rename get a one-time migration script. This is standard refactor mechanics, not a published-API migration.

### Cutover-PR consumer sweep

When a tool moves from `portfolio-mcp` to `research-mcp`, the cutover PR updates every site referencing the old `mcp__portfolio-mcp__<tool>` prefix in one atomic change. Sites to sweep (the Phase 0d inventory; same list R3 had, now treated as a one-time update target rather than a forever-alias spec):

| Site | Action in cutover PR |
|---|---|
| `agent_gateway/mcp_client.py:386-399` (`_apply_collision_filtering`) | No code change; the tool simply registers on research-mcp instead of portfolio-mcp |
| `agent_gateway/tool_dispatcher.py:405` (`get_server_for_tool`) | No code change; resolves to research-mcp by virtue of registration |
| `AI-excel-addin/api/agent/shared/server_policies.py` | Move tool entry from `portfolio-mcp` policy's `known_read_tools` to `research-mcp` policy's `known_read_tools` |
| `AI-excel-addin/api/agent/shared/tool_catalog.py:39-58` (CHANNEL_TIERS) | Add `research-mcp` to always-tier across all 4 channels (one-time addition, not per-tool) |
| `AI-excel-addin/api/mcp_client.py:12` (`ALLOWED_SERVERS`) | Add `research-mcp` to allowed (one-time addition) |
| `AI-excel-addin/api/agent/shared/citations.py:302-325` (extractor) | No code change for Phase 1's 4 envelope-keyed tools; `canonical_tool_name` already strips `mcp__server__` prefix. Phase 2 extends `extract_sources` for read/excerpt tools. |
| Tests + fixtures (across all 3 repos) | Find-and-replace `mcp__portfolio-mcp__filings_search` → `mcp__research-mcp__filings_search` etc. |
| Prompt examples + persisted prompt fixtures | Find-and-replace as above |
| Docs (`docs/interfaces/mcp.md`, `docs/reference/MCP_SERVERS.md`, `AGENT_INFRASTRUCTURE.md`, V2_P2_*, CORPUS_ARCHITECTURE.md) | Update server-name references; defer for living-docs sweep at Phase 4 if scope tight |
| Telemetry dashboards | Update queries keyed on `portfolio-mcp.<tool>` to `research-mcp.<tool>` |
| MCP client configs (`~/.claude.json`, `.cursor/...`, etc.) | Add `research-mcp` server entry pointing at the new entrypoint per Phase 0 process model |
| **External Claude skill dirs** (`~/.claude/skills/`, project `.claude/skills/`) | Out of scope for V2.P10 — those reference investment_tools `research-mcp`, handled by PR0 (rename to `research-workbench-mcp`) |
| **Repo-local skill profiles + evals** (`AI-excel-addin/api/memory/workspace/notes/skills/...`, `AI-excel-addin/tests/skill_evals/...`) | **In scope (R5 — Codex R4 caught this).** **R6 (Codex R5) — classified replacement required, NOT blind find-and-replace:** these files contain BOTH old investment_tools `research-mcp.*` references AND portfolio research/thesis references that will move to V2.P10's `research-mcp`. Cutover script must distinguish: (a) investment_tools `research-mcp.<signals_tracker_tool>` → `research-workbench-mcp.<tool>` (handled by PR0); (b) portfolio research/thesis tools → V2.P10 `research-mcp.<tool>` (handled by V2.P10 cutover PR). Mixed find-and-replace will corrupt files. |
| **Agent profiles + ProfileConfig** (R7→R8→R9 — 6th surface added per Codex R8) | `AI-excel-addin/api/agent/profiles/analyst.py` (`:68`) and `advisor.py` (`:37`) have references in: (1) **always/deferred server sets**, (2) **core tool maps**, (3) **prompt text**, (4) **tool packs**, (5) **ProfileConfig runtime fields**, AND (6) **`build_initial_user_message` + any other `build_*` profile method that emits server names in prompt text** (R9 — `advisor.py:195` initial message says "portfolio state from portfolio-mcp"). R8/R9 complete enumeration of (5)+(6): `excluded_tools`, `run_once_excluded_tools`, `dev_excluded_tools`, `channel_context`, `build_*_system_prompt` builders, dev-mode prompt builders, `build_initial_user_message`, `format_tool_catalog`, `build_tool_packs_section`, `run_once_use_tool_packs`, `local_tool_names`, dev env/write-dir fields. `format_tool_catalog` and `build_tool_packs_section` directly shape what the model sees about active/deferred tools (`profiles/__init__.py:45,62`, `analyst.py:575`). Update ALL 6 surfaces during cutover PR. Profile tests (`AI-excel-addin/tests/test_advisor_profile.py` and similar) assert server semantics — update assertions. |
| **`SkillProfile` (skill frontmatter) + sub-agent visibility** (R18 — Codex R17 corrected `tool_packs` claim) | `agent-gateway-dist/agent_gateway/skills.py` exposes tool-visibility fields beyond `ProfileConfig`: **`extra_excluded_tools`**, **`mcp_servers`**, **`session_inject_servers`**, **`tool_packs_enabled`** (consumed at `tool_handlers.py:908` to enable/disable pack-capable `load_tools`), **`tool_packs`** (`skills.py:33`, parsed at `:228, :342` — **R18: parsed metadata only; no demonstrated runtime use today; audit because skill files may encode deferred pack names/server assumptions, but verify whether runtime currently consumes it during impl**). PLUS exact coordinator/sub-agent excluded-tools surfaces in gateway runner code: **`CoordinatorConfig.worker_excluded_tools`** (`task_registry.py:101`), runner **`excluded_tools`** (`runner.py:223`), **`skills_excluded_tools`** (`easy.py:58`), sub-agent **`excluded_tools`** (`sub_agent.py:71`), inherited/default sub-agent exclusions. Skill-frontmatter consumers must be classified against ALL these fields, not just `SkillProfile`. Update all skill frontmatter that references `portfolio-mcp` or moved tools during cutover PR. |
| **`ALLOWED_SERVERS` `research-mcp` entry** (R16 — Codex R15 — classified rename) | `AI-excel-addin/api/mcp_client.py:12` already contains `research-mcp` today, referring to the EXISTING investment_tools server (about to be renamed to `research-workbench-mcp` via PR0). R16 explicit classification: **PR0 renames** the existing entry to `research-workbench-mcp`. **V2.P10 cutover then ADDS** a new `research-mcp` entry for the V2.P10 server. NOT a blind "add research-mcp" — the existing entry must be RENAMED first to free the name. |
| Sub-agent transcript / `last_tool_name` fields in conversation summarization | Audit for hard-coded `portfolio-mcp` strings; update if any |

### One-time persisted-record migration (R5 — record-class table per Codex R4)

Codex R4 enumerated 8 record classes that retain `tool_name` or `server` fields. R5 disposes each class explicitly: **rewrite** (active replay path; migration script must update), **leave historical** (audit-only, acceptable as "won't replay cleanly"), or **cannot cleanly migrate** (flag + accept loss).

| Record class | Source | Fields with server/tool prefix | Disposition | Action |
|---|---|---|---|---|
| `AgentSessionLog` JSONL | gateway-side session logs | `tool_name` (often `mcp__portfolio-mcp__filings_search`) | Rewrite | Migration script rewrites prefixes; tested against fixture |
| Durable `tool_call_start` / `tool_call_complete` events | event store | `tool_name`, `server` (separate field) | Rewrite | Migration script updates BOTH `tool_name` prefix AND `server` field for moved tools |
| SDK runner event logs | `agent-gateway-dist/agent_gateway/sdk_runner.py` | `mcp__server__tool` prefixed names in event payloads | Rewrite | Migration script handles |
| Context-builder replay summaries | conversation summarization | `tool_name` references in summary text | Leave historical | Summaries are descriptive; rewriting risks corrupting natural-language content. Accept that replays of old conversations show old names. |
| Task registry `last_tool_name` | task tracking | `tool_name` field | Rewrite | Single field per task record; trivial migration |
| Research tool-result persistence | `persist_research_tool_result` (research workspace) | `tool_name` in metadata | Rewrite | Migration script handles |
| Telegram / tool-only summaries | telegram bot persistence | `tool_name` in summary metadata | Rewrite | Migration script handles |
| Test/golden fixtures | `tests/fixtures/...`, golden snapshots | hard-coded `mcp__portfolio-mcp__*` | Rewrite (in-place find-and-replace as part of cutover PR) | Treated as code, not data; updated during cutover PR sweep |
| **`tool_timing` SQLite telemetry** (R6→R10 — catch-up loop per Codex R9) | `AI-excel-addin/api/logs/cost_tracker.py:66, 375, 495` | Separate columns: `server TEXT` and `tool TEXT NOT NULL`; `tool` stores BARE runner tool name (e.g., `filings_search`), NOT `mcp__portfolio-mcp__filings_search`. Indexes only, no FK, no composite key. Global SQLite DB. | Rewrite | **Drain mechanism (R10 — maintenance-lock + post-UPDATE catch-up loop):** writes go through `record_tool_timing()` (`cost_tracker.py:375`) called by `tool_timing_hook` (`hooks.py:457`), invoked by both `runner.py:2216` and `sdk_runner.py:630`. Hooks fire at tool COMPLETION, not start. **(a)** Set maintenance-lock via **sentinel file** `~/.gstack/.tool_timing_lock` (R13 — Codex R12 noted env-var-only doesn't affect already-running gateway processes; sentinel file is the only cross-process mechanism without restart). **(b)** `tool_timing_hook` checks sentinel file ONCE at hook entry BEFORE calling `record_tool_timing`. Writes that beat the check are allowed to finish; writes after are no-op'd. **(c)** Drain in-flight tool calls (R13 specifies semantics): EITHER (i) fixed grace window (default 15s, configurable via `--timeout`) OR (ii) gateway health-endpoint poll (e.g., `GET /health/in-flight-tool-calls` returns 0). Whichever finishes first proceeds. If neither finishes by `--timeout` AND post-update SELECT still shows stale rows, fail-closed. **(d)** Record migration start timestamp `migration_start_ts`. **(e)** `BEGIN IMMEDIATE; UPDATE tool_timing SET server = 'research-mcp' WHERE server = 'portfolio-mcp' AND tool IN ('filings_search', 'transcripts_search', ...); COMMIT;` — `BEGIN IMMEDIATE` serializes behind any active SQLite writer. **(f) Catch-up loop (R10/R11 — fail-closed recovery per Codex R10):** WHILE maintenance-lock still set, run `SELECT COUNT(*) FROM tool_timing WHERE server = 'portfolio-mcp' AND tool IN (...) AND ts > migration_start_ts`. If non-zero, run a second UPDATE for the late writers, repeat SELECT. **Loop termination:** until zero OR configurable timeout (default 60s) / max iterations (default 5). **Fail-closed (R11):** if still nonzero at exit, FAIL the migration script (non-zero exit), keep maintenance-lock SET (do NOT clear), print exact recovery command (`python3 scripts/migrate_tool_timing.py --resume --since=<migration_start_ts>`), print stale-row count + IDs for operator inspection. Do not declare success. **(g)** On success: clear maintenance-lock once SELECT returns 0. **Net behavior:** stale rows from beat-the-check race are caught + corrected before lock clears, OR migration fails-closed and operator retries. **Post-migration validation:** `get_tool_timing_summary` and `get_skill_tool_timing` queries return consistent results. Migration script idempotent. |

Compressed event archives, backup snapshots, third-party logs (if any exist) are **out of scope** for migration. They're cold storage; if read in the future, will reference old names. Documented in release notes.

**Migration script (Phase 0e):**
- Designed Phase 0e; tested against fixtures pre-merge.
- Run as part of cutover PR (or immediately before/after deploy).
- Per-class dry-run mode + count of records affected before commit.
- Idempotent (re-running on already-migrated records is a no-op).

**Acceptance:** post-migration replay tests pass on rewritten records for all "Rewrite" classes; "Leave historical" classes documented; release notes name affected classes.

### Why no live alias layer

Codex R3's R3-blocker analysis found that maintaining a live alias layer requires:
- Canonicalization at MCP client routing, ServerPolicy lookup, permission/approval classification, telemetry attribution, deprecation logging, citation `produced_by_tool`, persisted replay
- Single source of truth + drift tests at each layer
- Forever-maintenance burden after Phase 4

R4 trades that for: **one-time atomic update + one-time migration script**. The alternative is structurally cleaner and matches the actual refactor's nature.

### What this leaves on the table

- **No graceful rollback if cutover PR breaks consumers post-merge.** Mitigation: cutover PR is small (one tool group), reviewed pre-merge, tested in dev before deploy. If a consumer is missed, fix-forward in a follow-up PR. Same risk profile as any internal refactor.
- **External consumers** (none exist today) would need to update on rename. Acceptable for Hank pre-launch.

---

## Current state — `portfolio-mcp` is a catch-all

`portfolio-mcp` currently serves ~120 tools spanning multiple concerns. Inventory by category:

### R3 eligibility rule for always-tier `research-mcp` (replaces "foundational" elasticity)

A tool moves to `research-mcp` always-tier ONLY if it satisfies ALL of:

1. **Read-only** — no DB writes, no model builds, no artifact creation, no external-system mutations, no side effects beyond logging.
2. **User-owned scope (where applicable)** — if the tool returns user-private data, it correctly resolves user identity via `UserIdMiddleware` (i.e., `_MCP_META_INJECT_SERVERS` extension is in place for research-mcp).
3. **Bounded output** — payload size predictable; not unbounded list/scan operations.
4. **Citation-envelope-attachable OR named justification** — either (a) returns `hits`/`documents` shape that Slice A's `extract_sources` consumes per `api/agent/shared/citations.py:310-325`, OR (b) has an explicit named reason it must be always-tier (e.g., "the LLM needs this in catalog to construct corpus queries"). "Research-flavored" alone is NOT a named justification.

Per-tool: each candidate for always-tier needs a one-line justification recorded in this plan or in `ServerPolicy.known_read_tools` comments. No tool moves on vibes.

Anything that mutates state, builds artifacts, returns unbounded output, or fails the named-justification test stays in `portfolio-mcp` defer-tier.

### Should stay in `portfolio-mcp` (R2 — expanded list)

Mutating, expensive, or not citation-envelope-attachable:

- **Portfolio mgmt**: create_portfolio, list_portfolios, list_accounts, account_activate, account_deactivate, list_baskets, get_basket, create_basket, update_basket, delete_basket, create_basket_from_etf
- **Risk analysis**: get_risk_analysis, get_risk_profile, get_risk_score, set_risk_profile, run_stress_test, run_optimization, run_monte_carlo, run_whatif, run_backtest, get_efficient_frontier, get_factor_analysis, get_factor_recommendations, manage_qualitative_factor, manage_stress_scenarios
- **Trading**: preview_trade, execute_trade, cancel_order, get_orders, preview_basket_trade, execute_basket_trade, preview_option_trade, execute_option_trade, preview_rebalance_trades, preview_futures_roll, execute_futures_roll, preview_patch_ops, apply_patch_ops, suggest_tax_loss_harvest
- **Position mgmt**: get_positions, get_quote, get_performance, get_income_projection, get_leverage_capacity, get_target_allocation, set_target_allocation, get_allocation_presets, monitor_hedge_positions, check_exit_signals
- **Brokerage**: initiate_brokerage_connection, complete_brokerage_connection, list_supported_brokerages, list_connections, manage_brokerage_routing, fetch_provider_transactions, refresh_transactions, wait_for_sync, list_transactions, inspect_transactions, transaction_coverage, list_flow_events, list_income_events
- **Document ingest** (portfolio-side): import_portfolio, delete_portfolio, update_portfolio_accounts, import_transaction_file, manage_instrument_config, manage_ticker_config, manage_proxy_cache, list_ingestion_batches
- **Stock/option/futures analysis**: analyze_stock, analyze_option_chain, analyze_option_strategy, analyze_basket, get_futures_curve, industry_peer_comparison, compare_scenarios, get_trading_analysis, get_price_target
- **Model build / insights** (R2 reclassified — were briefly in research-mcp, removed): `build_model` (mutating per `mcp_tools/research.py:441-462`), `get_model_insights` (read-only but not envelope-attachable; doesn't justify always-tier token cost), `get_model_build_context` (orchestration metadata, not citation surface)
- **Editorial mutations** (R2 reclassified — were in research-mcp, removed): `create_annotation`, `update_action_status`, `record_workflow_action`, `update_editorial_memory`, `update_diligence_section`, `set_process_template`, `prepopulate_diligence` — all mutating
- **Thesis mutations** (R2 reclassified — were in research-mcp, removed): `thesis_create`, `thesis_run_scorecard`, `thesis_update_section`, `thesis_upsert_link`, `thesis_remove_link`, `thesis_append_decisions_log` — all mutating
- **Handoff mutations** (R2 reclassified): `finalize_handoff`, `new_handoff_version` — mutating

### Should move to `research-mcp` always-tier (R3 — per-tool justified)

Each tool below has a named justification per the R3 eligibility rule. No tool moves on vibes.

**Phase 1 (4 tools — envelope-keyed today):**

| Tool | Read-only? | Bounded? | Envelope today? | Named justification |
|---|---|---|---|---|
| `filings_search` | ✓ | ✓ (limit param) | ✓ Slice A keyed | Returns ranked corpus hits with `[Sn]` citations; LLM picks edgar over corpus without always-tier |
| `transcripts_search` | ✓ | ✓ | ✓ Slice A keyed | Same as above for transcripts |
| `filings_list` | ✓ | ✓ | ✓ Slice A keyed | Returns documents list shape consumed by extractor |
| `transcripts_list` | ✓ | ✓ | ✓ Slice A keyed | Same |

**Phase 2 (4 corpus read/excerpt — require payload enrichment first per R3 fix #14):**

| Tool | Read-only? | Bounded? | Envelope today? | R3 status |
|---|---|---|---|---|
| `filings_read` | ✓ | depends on doc | ✗ returns `{status, content}` only | Needs enrichment (document_id, section, offsets, URL) before extractor extension |
| `transcripts_read` | ✓ | depends on doc | ✗ same | Same |
| `filings_source_excerpt` | ✓ | ✓ (excerpt span) | ✗ same | Same |
| `transcripts_source_excerpt` | ✓ | ✓ | ✗ same | Same |

**Phase 2+ (foundational reads — per-tool justified):**

| Tool | Read-only? | User-owned? | Justification | R3 status |
|---|---|---|---|---|
| `list_research_files` | ✓ | ✓ | LLM needs to discover available research files for the user before reading them | Move |
| `read_research_thread` | ✓ | ✓ | Returns thread messages; foundational for LLM to load research context | Move (verify bounded — pagination/limit needed) |
| `get_research_brief` | ✓ | ✓ | LLM uses brief to ground analysis | Move |
| `get_handoff_summary` (NEW — R10 projection tool replacing whole-`get_handoff` move) | ✓ | ✓ | Read of handoff metadata + snapshot; LLM consumes for model build context. Full `artifact` field stripped; available via `get_handoff_full` (stays portfolio-mcp). | Move (NEW projection tool on research-mcp) |
| `thesis_list` | ✓ | ✓ | Discovery of user's theses | Move |
| `thesis_read` | ✓ | ✓ | Returns thesis content; LLM consumes for analysis | Move (verify bounded) |
| `thesis_latest_scorecard` | ✓ | ✓ | Read of latest scorecard | Move |
| `thesis_list_decisions_log` | ✓ | ✓ | Read of decisions log | Move |
| `thesis_list_links` | ✓ | ✓ | Read of links | Move |
| `get_diligence_state` | ✓ | ✓ | Read of current diligence state | Move (verify read-only — Codex flagged `activate_diligence` as write-side; verify `get_diligence_state` is genuine read) |
| `list_process_templates` | ✓ | ✗ (catalog) | Discovery of available templates | Move |
| `get_process_template` | ✓ | ✗ | Read template content | Move |
| `get_action_history` | ✓ | ✓ | Read of action history | Move |

**R3 explicit removals from R2's "should move" list (now stay in portfolio-mcp):**

- `start_research` — verified mutating per `mcp_tools/research.py:96` (creates research file). Stays in portfolio-mcp.
- `activate_diligence` — verified write-side in existing ServerPolicy. Stays in portfolio-mcp.

**Tools needing per-tool read/write classification before any move (R3 deferred):**

- `ingest_document`, `load_document` — likely write-side (ingest mutates DB, load may cache). Defer to per-tool review; default = stay in portfolio-mcp.
- `normalizer_*` — `normalizer_activate` and `normalizer_stage` are writes; `normalizer_list` and `normalizer_sample_csv` are reads. Defer the read-side ones to a future phase; writes stay in portfolio-mcp.

**Estimated count after R3:** Phase 1 = 4 tools; Phase 2 = 8 tools (4 corpus read/excerpt + 4 foundational read), plus per-tool review of 8 more foundational reads after enrichment + classification. Token cost: Phase 1 ~1-2K, Phase 2 cumulative ~4-6K per session. R2's "~15-20 tools" estimate revised: total ~12-16 tools across all phases combined, with explicit per-tool justification.

### Tools NOT moving (R2 explicit exclusions)

Per the eligibility rule above:

- `build_model` — mutating, no envelope shape
- `compare_scenarios` — risk/portfolio domain, no envelope
- `analyze_stock` — risk/market analysis, no envelope, returns `source_refs: []` for portfolio analysis
- `industry_peer_comparison` — FMP-derived peer metrics, no envelope
- `get_model_insights`, `get_price_target`, `get_model_build_context` — read-only but non-envelope; defer-tier acceptable
- All thesis/diligence/editorial WRITES — mutating, defer-tier required
- `get_portfolio_news`, `get_portfolio_events_calendar`, `export_holdings` — portfolio-flavored, not corpus; stay in portfolio-mcp

---

## Target architecture

### Three MCP servers (instead of two)

| Server | Tier | Purpose |
|---|---|---|
| **portfolio-mcp** | defer | Portfolio mgmt + risk + trading + brokerage + position mgmt + mutating editorial/thesis/diligence + non-envelope analysis tools (analyze_stock, compare_scenarios, build_model, etc.). ~100 tools after R2 split. |
| **research-mcp** (NEW) | **always** | Citation-envelope-attachable corpus tools + foundational read-only research workflow tools. ~15-20 tools after R2 narrowing. |
| **edgar-financials, fmp-mcp, model-engine** | unchanged | External data + modeling. |

### CHANNEL_TIERS update (per `tool_catalog.py:39-58`)

```python
CHANNEL_TIERS: Dict[Optional[str], Dict[str, Set[str]]] = {
  None: {  # Excel add-in
    "always": {"model-engine", "edgar-financials", "research-mcp"},  # ADD research-mcp
    "defer": {"portfolio-mcp", "fmp-mcp", "roam-research", "drive-mcp", ...},
  },
  "web": {
    "always": {"fmp-mcp", "edgar-financials", "research-mcp"},  # ADD research-mcp
    "defer": {"model-engine", "portfolio-mcp", ...},
  },
  "telegram": {
    "always": {"fmp-mcp", "edgar-financials", "research-mcp"},  # ADD research-mcp
    "defer": {"model-engine", "portfolio-mcp", ...},
  },
  "cli": {
    "always": {"fmp-mcp", "edgar-financials", "research-mcp"},  # ADD research-mcp
    "defer": {"model-engine", "portfolio-mcp", ...},
  },
}
```

Result: corpus tools (and the rest of research-mcp) are universally always-loaded. F56 auto-load no longer needed; F62 (TUI mode flag) becomes moot; C.4 (cross-MCP citation discipline) becomes optional.

### Token cost analysis

`research-mcp`'s ~15-20 R2-narrowed tools should add roughly:
- ~15-20 tools × ~250-400 tokens per tool schema = ~4-8K tokens added to system prompt always-loaded
- That's a 1-time cache write per session for clients using Anthropic prompt caching; cached on subsequent turns
- Caveat: not every channel/client uses Anthropic prompt caching identically; first-turn UX/cost still pays the schema-load even if subsequent turns are free

Compare to the cost of having Hank skip corpus tools (citation envelope never fires → analyst-grade output without citations → V2.P2 product value lost).

**Token cost of always-loading research-mcp is acceptable** even on a per-turn basis without caching. The cost of NOT always-loading it is V2.P2 product value being unreliable.

R1 estimated ~10K tokens for ~40 tools; R2's narrower inventory cuts the floor by ~50%.

### Slice A citation envelope contract (R2 — corrected scope)

Slice A's `extract_sources` (`api/agent/shared/citations.py:310-325`) keys on canonical tool name (server prefix stripped via `canonical_tool_name` at `:302-307`). It currently covers ONLY 4 tools: `filings_search`, `transcripts_search`, `filings_list`, `transcripts_list`. Read/excerpt tools (`filings_read`, `transcripts_read`, `*_source_excerpt`), `load_document`, and all research-workflow tools are NOT extracted today.

**Implications for the split:**

1. **The 4 envelope-keyed tools survive the move with no extractor change** — preserve names, update server hosting. Confirmed by reading `citations.py:302-325`.
2. **Read/excerpt tools moving in Phase 2 do NOT inherit envelope automatically** — Phase 2 must add explicit extractor coverage. Otherwise they emit no `source_envelope`, defeating the citation-discipline goal for those tools.
3. **Cross-listing (Phase 1) does not double-fire the extractor for one tool result.** The extractor runs on a single called-tool result; duplication would only happen if the LLM calls both `mcp__portfolio-mcp__filings_search` AND `mcp__research-mcp__filings_search` in the same turn. Verify `SourceRegistry` dedup behavior (likely keyed on `(document_id, section, char_start, char_end)` per V2.P2 Slice A spec) handles this case.

**The plan no longer claims "the whole research server inherits citation discipline"** — only the 4 currently-keyed tools do, and Phase 2 must extend coverage explicitly for additional tools.

---

## Migration plan (R2 — restructured)

Phased rollout. Aliasing is now a **Phase 1 prerequisite**, not deferred to Phase 3.

### Phase 0 — Architectural prerequisites

- **Process model:** Default to **Option B** per R3. If Option A is preferred, run the A-validation harness (per §"risk_module server architecture") — all 5 criteria must pass; otherwise fall back to B.
- **Land PR0a/PR0b/PR0c (R19 — catalog-key rename only):** `~/.claude.json` adds `research-workbench-mcp` entry (manual) → AI-excel-addin code rename (Codex) → `~/.claude.json` removes old `research-mcp` entry (manual). No investment_tools commit. See §"Cross-repo sequencing (R19)."
- **Audit `_MCP_META_INJECT_SERVERS` consumers** (AI-excel-addin runtime, agent-gateway-dist dispatcher) — design the extension to include `research-mcp`.
- **Design persisted-record migration script** (per §"Consumer-site sweep + persisted-record migration"). Decide which record classes need replay-through-rename and which are acceptable as "won't replay cleanly." Test script against fixtures pre-merge.
- **Phase 0d — consumer-site inventory** (R3 expanded): produce a master list of every site referencing `mcp__portfolio-mcp__filings_*`, `mcp__portfolio-mcp__transcripts_*`, or the existing investment_tools `research-mcp` name. Required coverage:
  - Gateway dispatcher (`agent-gateway-dist/agent_gateway/tool_dispatcher.py`)
  - Agent registry (`AI-excel-addin/api/agent/registry.py` and `risk_module/agent/registry.py`)
  - MCP client configs (`~/.claude.json`, any team `.claude.json`, Cursor/Codex configs)
  - **MCP allowlists** (R3 added): `AI-excel-addin/api/mcp_client.py:12` `ALLOWED_SERVERS`
  - Server policies (`AI-excel-addin/api/agent/shared/server_policies.py`)
  - CHANNEL_TIERS (`AI-excel-addin/api/agent/shared/tool_catalog.py:39-58`)
  - Dev CLI fixtures (`AI-excel-addin/api/dev/chat_cli.py` + tests)
  - **External Claude skill dirs (R17 — Codex R16 reconciled): OUT OF SCOPE for V2.P10.** `~/.claude/skills/` and project-local `.claude/skills/` are explicitly excluded from Phase 0d audit per user instruction (do NOT read those paths). Investment_tools rename to `research-workbench-mcp` propagates via PR0 cross-repo work; V2.P10 cutover does NOT touch these directories.
  - **Skill evals** (R3 added): test files exercising skills against MCP tool names
  - **Package mirror tests** (R3 added): `AI-excel-addin/packages/agent-gateway/tests/...`, `agent-gateway-dist/tests/...`
  - **Persisted chat/event replay records** (R3 added): chat-log replay code + event-store records that retain `tool_name`
  - Prompt examples + persisted prompt fixtures
  - **Telemetry dashboards** (R3 added): any dashboard query/metric keyed on tool name or server name
  - Docs: `docs/interfaces/mcp.md`, `docs/reference/MCP_SERVERS.md`, `docs/planning/CORPUS_ARCHITECTURE.md`, `docs/planning/V2_P2_*`, **`AGENT_INFRASTRUCTURE.md`** (R3 added)
  - CI smoke tests + golden-snapshot fixtures
  - User-facing release notes templates
  - **Non-workspace config audit (R16 — expanded per Codex R15 for env-var-required design):** these live OUTSIDE `~/Documents/Jupyter` and are NOT covered by the workspace grep:
    - `~/.claude.json` (user-global MCP config)
    - Project-local `.claude/settings*.json` outside main workspace (if any)
    - Cursor / Codex / Cline / Windsurf / Gemini MCP configs (`~/.cursor/...`, `~/.codex/...`, etc.)
    - Service deployment configs (Fly.io, Render, GitHub Actions, etc. — wherever V2.P10 servers may be deployed)
    - Remote/team checkouts of any workspace repos
    - **Shell startup files** (R16 — required because `TOOL_TIMING_DB_PATH` env var must propagate): `~/.zshrc`, `~/.zprofile`, `~/.bashrc`, `~/.bash_profile`, `~/.config/fish/config.fish` — search for any `TOOL_TIMING_*` / `COST_TRACKER_*` / MCP-related env-var declarations.
    - **macOS LaunchAgents/Daemons** (R16): `~/Library/LaunchAgents/*.plist`, `/Library/LaunchAgents/*.plist`, `/Library/LaunchDaemons/*.plist` — services that launch gateway/MCP processes need env propagation.
    - **systemd units** if any Linux/remote deployment exists.
    - **Secret managers that store env file references** (R16 — only if storing MCP server config or env files, not just API tokens): 1Password env injection, Keychain Access entries with env-file content, Doppler, `.envrc` / direnv.
    - **Dev-laptop env propagation surfaces (R17 — Codex R16 non-blocking suggestion):** VS Code/Cursor workspace `.vscode/settings.json`/`tasks.json`/`launch.json`; devcontainer configs; JetBrains run configs; tmux env propagation; Homebrew services; cron; pm2/supervisor; asdf/nvm (less about `TOOL_TIMING_DB_PATH` directly, but affects which process environment launches Python/node services).
    - Browser extension settings (lower priority — only if an extension directly launches MCP servers).
    Phase 0d MUST audit these separately (per-tool config-aware search; cannot be a single grep). Critical because R15 made `TOOL_TIMING_DB_PATH` required env var — gateway processes MUST inherit it correctly via these surfaces.

**Phase 0 acceptance:** see §"Phase 0 acceptance (R7)" below for the canonical 8-criterion list (0a–0h). Includes: process model decision, mandatory shared-module refactor, Option B launch contract verification, PR0 cross-repo sequence, hidden-dep audit, consumer-site inventory + non-workspace config audit, `get_handoff` consumer classification, persisted-record migration script.

### Phase 1 — Stand up `research-mcp` + cutover the 4 envelope-keyed corpus tools (R4)

**Architectural setup (one-time):**
- Add second FastMCP entrypoint per Phase 0 process model decision (default Option B: separate process). Attach `UserIdMiddleware` and any shared middleware to the new server.
- Update `CHANNEL_TIERS` (`tool_catalog.py:39-58`): add `research-mcp` to always-tier across all 4 channels.
- Update `_MCP_META_INJECT_SERVERS` (`runtime.py:97`): include `research-mcp`.
- Update `ALLOWED_SERVERS` (`api/mcp_client.py:12`): add `research-mcp`.
- Update MCP client configs (`~/.claude.json` etc.) to register the second server per the chosen process-model launch contract.
- Add `ServerPolicy` for `research-mcp` in `server_policies.py` with empty `known_read_tools` initially (filled by the cutover PR) + empty `known_write_tools`.

**Cutover PR (4 envelope-keyed corpus tools):**
- Move `filings_search`, `transcripts_search`, `filings_list`, `transcripts_list` from portfolio-mcp registration to research-mcp registration. Single canonical home — no cross-listing.
- In the same PR, sweep all consumer sites per §"Consumer-site sweep" table:
  - Move tool entries in `ServerPolicy.known_read_tools` from portfolio-mcp → research-mcp
  - Find-and-replace `mcp__portfolio-mcp__filings_search` → `mcp__research-mcp__filings_search` (and the other 3) across tests, fixtures, prompts, docs, telemetry queries
- Run one-time migration script for persisted records (chat logs, event store, replay fixtures) that retain old prefixes and need to replay post-rename.

**Phase 1 acceptance (R4):**
1. Second FastMCP entrypoint (`research-mcp`) registered + reachable per Phase 0 process model decision; same middleware stack as portfolio-mcp.
2. **Middleware transport test:** meta-injection contract round-trip with a canary fake tool that asserts on `_USER_EMAIL_CTX`. Real user-owned-tool verification deferred to Phase 2c.
3. The 4 envelope-keyed corpus tools registered on research-mcp (not portfolio-mcp). They produce `source_envelope` (Slice A extractor unchanged — `canonical_tool_name` strips server prefix per `citations.py:302-307`, so move is a no-op for the extractor).
4. **All consumer sites updated atomically** in the cutover PR (per §"Consumer-site sweep" table). Old `mcp__portfolio-mcp__filings_*` calls return tool-not-found errors (visible failures, not silent drift). New `mcp__research-mcp__filings_*` calls work.
5. **Persisted-record migration script** ran successfully; replay tests pass on rewritten records.
6. F56 audit (a) + (b) status documented: F56 block stays in place this phase; retirement scheduled for Phase 4.
7. TUI test (no `mode=research` flag, no prompt nudge): natural-language corpus query produces `[Sn]` citations + Sources footer.
8. Existing V2.P2 + V2.P9 tests pass.

### Phase 2 — Corpus read/excerpt: payload enrichment + extractor + cutover (R4)

Phase 2 splits into 2a/2b/2c because Codex R2+R3 verified extractor extension is not a switch addition — corpus read/excerpt tools return `{status, content}` only, and the upstream `core/corpus/*` functions return plain `str` (per Codex R3 verification at `core/corpus/filings.py:83-105`).

**Phase 2a — Payload enrichment (risk_module changes, both core and mcp_tools layers):**
- Extend `core/corpus/filings.py` and `core/corpus/transcripts.py` read/excerpt functions to expose `document_id`, `section`, `char_start`, `char_end`, `url` (or whatever the canonical citation primitives are per Slice A spec). Add `DocumentMetadata` lookup helper if not present (coordinate with V2.P2 Slice A.5 deferred work — same gap).
- Update `mcp_tools/corpus/filings.py` and `transcripts.py` read/excerpt MCP wrappers to echo enriched fields in their response payloads.
- Local fixture-based tests verify enriched payloads against canonical fixture filings/transcripts.

**Phase 2b — Slice A extractor extension (AI-excel-addin):**
- Extend `api/agent/shared/citations.py:extract_sources` with new branches for `filings_read`, `transcripts_read`, `filings_source_excerpt`, `transcripts_source_excerpt`.
- Extractor consumes the Phase 2a enriched payloads.
- Tests verify `[Sn]` citations emit for read/excerpt tool results.

**Phase 2c — Cutover the next batch of tools to research-mcp:**

Per-tool batch cutover, one PR per group (or one PR for all if small). For each tool: move registration from portfolio-mcp to research-mcp, update consumer sites per §"Consumer-site sweep" table, run migration script for persisted records.

**Group A — Corpus read/excerpt (4 tools):**
- `filings_read`, `transcripts_read`, `filings_source_excerpt`, `transcripts_source_excerpt`
- Phase 2b extractor coverage required first.

**Group B — Foundational reads (R10 — `get_handoff` split into summary/full per Codex R9):**
- `list_research_files`, `read_research_thread`, `get_research_brief`, **`get_handoff_summary`** (NEW projection tool on research-mcp; replaces moving `get_handoff` whole — see boundedness section), `thesis_list`, `thesis_read`, `thesis_latest_scorecard`, `thesis_list_decisions_log`, `thesis_list_links`, `get_diligence_state`, `list_process_templates`, `get_process_template`, `get_action_history`. **`get_handoff_full`** stays on portfolio-mcp (defer-tier; full artifact retained for portfolio-loaded contexts).

**R7 boundedness rule (row counts AND payload size):**

Every always-tier list/read tool with user-sized collections MUST have a server-enforced cap before cutover, covering BOTH:

- **Row count cap:** number of records returned (lists, sections, factors, decisions log entries).
- **Payload size cap (R7 added per Codex R6):** total + per-record character/byte size of returned content. Row caps don't help if a single record contains an unbounded `content` blob.

**Per-tool audit results (R7 — Codex R5 + R6 verified each by reading repository code):**

Row-count caps required:
- `read_research_thread`: has `limit` but only clamps lower bound — **add row-count cap** (e.g., 100). [Codex R4]
- `thesis_read`: section filtering exists but no explicit limit; full thesis can be returned — **add explicit row cap** or paginate sections. [Codex R4]
- `thesis_list_decisions_log(limit=None)`: can be unbounded — **add row cap**. [Codex R4]
- `list_research_files`: no limit at any layer — **add cap at action or repository layer**. [Codex R5 — `actions/research.py:36`, `routes.py:784`, `repository.py:1693`]
- `list_process_templates`: fetches all user-created templates — **add cap or document natural smallness**. [Codex R5 — `actions/research.py:49`, `repository.py:1799`]
- `get_handoff` list mode: no limit — **add row cap**. [Codex R5 — `actions/research.py:573`, `routes.py:1547`] **R11:** `get_handoff_summary` (research-mcp) inherits row cap for list mode; `get_handoff_full` (portfolio-mcp defer-tier) keeps existing behavior — defer-tier visibility is the gate.
- `thesis_list`: no limit — **add cap**. [Codex R5 — `actions/thesis.py:111`, `repository.py:2299`]
- `thesis_list_links`: no limit — **add cap**. [Codex R5 — `actions/thesis.py:223`, `repository.py:2541`]
- `get_diligence_state`: returns all sections + all qualitative factors — **prove boundedness OR add factor/source-ref cap**. [Codex R5 — `actions/research.py:361`]

Payload-size caps required (R8 — projection contract per Codex R7):

**Projection contract for every payload-cap tool** (per Codex R7 — naive truncation is semantically dangerous):
- `truncated: bool` flag
- `original_char_count: int`
- Stable `message_id` or ordinal for continuation
- `offset` / `cursor` for paginated re-fetch
- Either a continuation tool (e.g., `read_research_thread_continuation`) OR a "summary + excerpts" response shape

Per-tool application:

- `read_research_thread`: each message returns raw `content` with no per-message or total char cap. **Apply projection contract**: per-message cap (e.g., 4K chars) AND total response cap (e.g., 50K chars), both with `truncated`/`original_char_count`/`message_id` fields. Continuation via `read_research_thread(thread_id, after_message_id=X)` to fetch next page. [Codex R6 — `actions/research.py:1062`; Codex R7 — projection contract required]
- `get_handoff` single mode: returns full `artifact` payload. **R13 enforcement (final, per Codex R12 code verification):** **split into two MCP-registered tools** — `get_handoff_summary` (always-tier on research-mcp; returns projection) and `get_handoff_full` (stays on portfolio-mcp as defer-tier; returns full artifact). **Server-tier visibility is the gate** via `CHANNEL_TIERS`. See profile access matrix (Decision #82) for which profiles can reach `get_handoff_full`. **`_project_handoff_summary` whitelist contract** (R13 — grounded in actual code at `actions/research.py:1148-1212`):
    - **Outer fields preserved** (all bounded by source): `handoff_id` (int), `version` (int), `ticker` (string), `status` (string), `artifact_summary` (dict OR null — see below). Optional: `research_file_id`, `created_at`, `finalized_at`.
    - **`artifact_summary` content (R14 — handles both branches per Codex R13):**
      - **`artifact is None` branch:** `_normalize_handoff_artifact_summary` returns `normalized or None` (`actions/research.py:1192`); upstream pass-through fields with `thesisStatement` rename. Counts (`assumptions`/`qualitative_factors`/`sources`) are NOT guaranteed in this path. Projection helper validates upstream pass-through fields against the whitelist; if `None`, project to `{}` or pass through `null`.
      - **`artifact present` branch:** counts ARE returned via `len()` (`:1201-1206`).
      - **Whitelisted fields** (per actual `_normalize_handoff_artifact_summary:1188-1212`):
        - `thesis_statement` (string, **CAP at 1000 chars** with `truncated` flag if exceeded)
        - `assumptions` (int count — bounded only when artifact present)
        - `qualitative_factors` (int count — bounded only when artifact present)
        - `sources` (int count — bounded only when artifact present)
        - `differentiated_view_count` (int)
        - `invalidation_trigger_count` (int)
        - `industry_analysis_present` (bool)
        - `scorecard_summary_status` (optional string, **CAP at 200 chars**)
    - **STRIPPED entirely:** `artifact` field (full body); top-level snapshot duplicates (`schema_version`, `_original_schema_version`, `thesis_strategy`, `model_ref_present`, and the count duplicates added by `_normalize_handoff_summary:1174`). `scorecard_summary_status` lives ONLY inside `artifact_summary` (R13 resolves the dual-location ambiguity Codex R12 flagged).
    - **CamelCase normalization:** only `thesisStatement` → `thesis_statement` is in current code (`:1188-1189`); upstream `routes.py:247` fallback emits `thesisStatement`/`assumptions`/`sources`. R13 implementer either handles this 1 explicit rename, OR implements a generic camelCase→snake_case normalizer for forward-compat.
    - **Fail closed** if upstream sends snake_case fields not on the whitelist after normalization (caller must extend whitelist explicitly).
    - `_normalize_handoff_artifact_summary` (current `actions/research.py:1148`) is NOT reused as-is. R13 requires a NEW `_project_handoff_summary` helper that enforces the whitelist + caps.
[Codex R6/R7/R8/R9/R10/R11/R12 — full evolution]
- `get_research_brief`: returns entire upstream brief object. **Either** prove schema-bounded (brief size capped at upstream) **OR** project: return brief metadata + linked sections (not full body inline); body fetched via subsequent tool call if needed. [Codex R6 — `actions/research.py:626`; Codex R7 — projection contract required]
- `thesis_latest_scorecard`: returns opaque scorecard dict. **Project**: top-N evidence/sources/decisions per section, with `truncated`/`original_count` fields and continuation pattern; OR prove scorecard internals are schema-bounded by structure. [Codex R6 — `actions/thesis.py:290`; Codex R7 — projection contract required]

Tools already bounded (OK as-is):
- `get_action_history`: `DatabaseClient` clamps to 200; MCP exposes `limit`. [Codex R5]

Other verifications:
- `get_diligence_state`: confirm read-only end-to-end (no lazy backfill, no audit-write side effects, no last-accessed timestamp updates).
- Codex R3 found `start_research` and `activate_diligence` are write-side — these stay in portfolio-mcp.

**If a tool can't be cleanly bounded** (e.g., open-ended free-form return), it stays in portfolio-mcp defer-tier rather than always-tier.

**Phase 2 acceptance (R4):**
9. **Phase 2a:** corpus read/excerpt tools echo `document_id`, `section`, `char_start`, `char_end`, `url` (via core-corpus + mcp_tools layer changes); fixture tests pass.
10. **Phase 2b:** `citations.py:extract_sources` extended for the 4 read/excerpt tools; `[Sn]` citations emit on live test.
11. **Phase 2c Group A:** 4 corpus read/excerpt tools registered on research-mcp (not portfolio-mcp); consumer sites updated; persisted-record migration script run.
12. **Phase 2c Group B:** foundational reads moved per per-tool table; bounded-output and read-only verifications documented per tool; `start_research` and `activate_diligence` confirmed staying in portfolio-mcp.
13. No regression in V2.P9 plan tests; `[Sn]` envelope fires for newly-moved-and-extracted tools.

### Phase 3 — REMOVED in R4

R3's Phase 3 was "deprecation timeline + cross-listing removal." With straight refactor, there's no transition window to deprecate and no cross-listing to remove. **Phase 3 is gone in R4.** Renumbering: R4 has Phases 0, 1, 2, 4.

### Phase 4 — Cleanup + F56 retirement (R4)

- **F56 audit:** verify Audit (a) + (b) per Decision #11. If both pass, remove `_RESEARCH_AUTO_LOAD_SERVERS` block at `runtime.py:87, 461-481`.
- **Living-docs sweep:** update CLAUDE.md, AGENTS.md, README.md, `docs/interfaces/mcp.md`, `docs/reference/MCP_SERVERS.md`, `docs/planning/CORPUS_ARCHITECTURE.md`, `docs/planning/V2_P2_*`, `AGENT_INFRASTRUCTURE.md`. Distinguish living docs (rewrite for new naming) from archived/historical (do NOT rewrite — they are point-in-time records).
- **File deferred items as closed:** F56 (auto-load) retired; F62 (TUI mode) preempted; C.4 (cross-MCP citations) becomes optional.

**Phase 4 acceptance:** F56 retired (or explicitly kept as belt-and-suspenders); docs sweep complete; closure-line entries filed.

---

## Fallback path — Phase 1 only (NOT chosen, retained for reference)

> **Decision 2026-05-02:** full split chosen up front (see Decisions log at top). R4 retains this subsection only as a fallback if scope contracts during Codex review or impl.

If the full split is too much scope, Phase 1 alone (just the 4 envelope-keyed corpus tools moved to `research-mcp`, leave the rest in portfolio-mcp) delivers the V2.P2 unblock:

- Citation envelope tools always-loaded
- LLM picks them by default
- F56 (already shipped) stays in place as belt-and-suspenders; F62 / C.4 workarounds unblocked
- Phase 0 architectural floor (FastMCP entrypoint, PR0, hidden-dep audit, consumer-site inventory) is the same regardless
- Phase 2 (read/excerpt enrichment + extractor + foundational reads) and Phase 4 (cleanup) deferred

Tradeoff: read/excerpt corpus tools, research workflow reads, thesis reads, diligence reads stay in portfolio-mcp's deferred tier. The 4 envelope-keyed tools handle most V2.P2 traffic but the rest of citation-flavored research stays defer-tier.

**Why we did NOT choose this path:** per the project's "don't defer to dodge friction" principle (see CLAUDE.md), banking the read/excerpt tools' tier status on "less hot use cases" is the kind of pre-launch deferral the principle forbids. Phase 0's architectural cost is the same floor either way, so Phase 1-only doesn't actually save much wall-clock once Phase 0 is amortized.

---

## Backwards compatibility (R4 — straight refactor)

### What might break

- **Code referencing `mcp__portfolio-mcp__filings_search`** etc. across all consumers — handled by atomic cutover-PR sweep per §"Consumer-site sweep" table
- **Persisted records** (chat logs, event store, replay fixtures) referencing old prefixes — handled by one-time migration script
- **MCP client connections** — clients connect to `portfolio-mcp` by name; new `research-mcp` requires explicit registration in MCP config files (Phase 1 setup)
- **Tests + fixtures** — find-and-replace in cutover PR; ~50-100 sites estimated; pre-merge tests catch misses

### Mitigation

- **Cutover PR is small + reviewed** — one tool group per PR; reviewer checklist verifies all consumer-site categories swept; pre-merge dev test exercises the moved tools end-to-end
- **Persisted-record migration script** designed + tested against fixtures pre-merge
- **Pre-deploy grep** to find any missed references before merge
- **Restart sessions** post-deploy to refresh tool catalogs (single-user dev — sessions are restartable)

### What can't break (load-bearing)

- Citation envelope contract (Slice A schema) — must preserve `source_envelope` block shape
- Slice A extractor logic — must continue to fire on the 4 corpus tools post-move (verified: `canonical_tool_name` strips server prefix so move is a no-op for the extractor)
- Agent registry tool definitions — tool names + categories preserved across move

---

## Risk register (R4 — straight refactor)

| Risk | Severity | Mitigation |
|---|---|---|
| FastMCP doesn't support same-process two-server cleanly | **High** | R4 default is Option B (separate process). A only if Phase 0 spike's 5-criterion harness passes |
| `_MCP_META_INJECT_SERVERS` not extended → user-identity propagation breaks for research-mcp | **High** | Phase 1 explicitly extends; middleware transport test (canary fake tool) in Phase 1 acceptance |
| Cutover PR misses a consumer site → that site silently breaks at deploy | **High** (R4 elevated, was "Medium" under cross-listing) | Phase 0d consumer-site inventory (16 categories per R3 list); cutover PR reviewer checklist; pre-merge dev test exercises the moved tools end-to-end |
| Persisted-record migration script misses a record class → replay tests fail post-rename | Medium | Phase 0d inventory enumerates record classes; migration script is testable against fixtures pre-merge |
| Cross-repo PR0 partial-land (R19 — catalog-key rename only) | Low (revised down from Medium per R19) | Three-step sequence: PR0a `~/.claude.json` adds new entry (manual) → PR0b AI-excel-addin rename (Codex) → PR0c `~/.claude.json` removes old entry (manual). Explicit per-step rollback. NO investment_tools commit. |
| Token cost of always-loading research-mcp inflates input cost | Low (R3 narrowed) | ~12-16 tools × ~250-400 tokens = ~3-6K per session at full Phase 2 completion; Anthropic prompt caching covers steady state |
| Slice A extractor breaks on tool-name resolution | Low | Verified: `canonical_tool_name` strips `mcp__server__` prefix; the 4 Phase 1 envelope tools survive move unchanged |
| Phase 2 read/excerpt tools moved without extractor coverage → silent envelope gap | Medium | Phase 2 sequence enforces 2a (enrichment) → 2b (extractor) → 2c (cutover); acceptance gates on envelope firing |
| Phase 2a core-corpus enrichment is bigger than mcp_tools layer | Medium | R4 explicitly scopes `core/corpus/*` changes per Codex R3 finding; budget reflected in Phase 2a acceptance |
| Borderline tools (`read_research_thread`, `thesis_read`, `get_diligence_state`) ship to always-tier with unbounded payloads or hidden side effects | Medium | Per-tool verification BEFORE Phase 2c inclusion (max-cap on `read_research_thread`, `thesis_read`; read-only audit on `get_diligence_state`) |
| Mutating tools accidentally added to research-mcp always-tier (security/cost) | **High** | R3 eligibility rule explicit (read-only + user-owned + bounded + no side effects + named justification); explicit exclusion list; `ServerPolicy.known_write_tools` defaults to empty for research-mcp |
| `get_mcp_context` server-name hardcoding breaks downstream consumers | Low | Phase 0 audit; either per-server response or moved to research-mcp; consumers asserting on field updated in cutover |
| Package version skew between agent-gateway-dist + AI-excel-addin during deploy | Medium | Pin minimum `ai-agent-gateway` version in AI-excel-addin pyproject; CI enforces; document in release notes |
| Active MCP sessions break mid-deploy (cached tool catalog from before rename) | Low (R4 — single-user pre-launch) | Restart session; document in release notes. Not a multi-tenant production concern at Hank's stage. |

---

## Out of scope

- Migrating other MCP servers (edgar-financials, fmp-mcp) — those are external; not our concern
- Re-architecting the MCP protocol or tool catalog format — only changing server categorization
- Adding new tools — pure refactor of existing tool homes
- Changing tool implementations — only their server-of-residence

---

## Acceptance

### Phase 0 acceptance (R7)

0a. Process model decided (default Option B per R3 Decision #12; A only if 5-criterion harness passes)
0b. **Mandatory 3-module shared-module refactor landed (R7 — Codex R6 expanded scope):** `mcp_middleware.py` (UserIdMiddleware + ContextVars + identity), `mcp_lifecycle.py` (pool_cleanup + atexit + `_order_watcher` state with `start_order_watcher_if_enabled`/`stop_order_watcher` API), AND `mcp_bootstrap.py` (stdout-to-stderr prelude, `.env` load, `_validate_environment`, `nest_asyncio.apply()`) all created at repo root; existing single-server `mcp_server.py` refactored to import from them; tests pass with single-server unchanged behavior. **This MUST land before Phase 0c.**
0c. **Option B launch contract verified end-to-end:** `mcp_server_research.py` boots independently and imports from shared modules (NOT from `mcp_server.py`); calls `bootstrap()` from `mcp_bootstrap.py` before instantiating FastMCP; `services.yaml` entry registered; MCP client config snippet validated against `~/.claude.json` schema; both servers attach middleware via shared module successfully; smoke command in place; `services-mcp` `service_status("risk_module_research_mcp")` returns healthy.
0d. PR0a + PR0b + PR0c sequence landed (R19 catalog-key rename — `~/.claude.json` user-edits + AI-excel-addin code rename); `research-workbench-mcp` is the canonical catalog key for the investment_tools server; `research-mcp` name is free for V2.P10 use
0e. Hidden-dependency audit complete: `_MCP_META_INJECT_SERVERS`, `_RESEARCH_AUTO_LOAD_SERVERS`, `get_mcp_context` server-name hardcoding all documented with planned changes
0f. Consumer-site inventory frozen (per §"Consumer-site sweep" table) — every site referencing `mcp__portfolio-mcp__filings_*` or `mcp__portfolio-mcp__transcripts_*` is on the master list with planned cutover-PR action; agent profiles (6 surfaces incl. `build_initial_user_message`) + repo-local skill evals explicitly included with classified-replacement strategy
0g. **`get_handoff` consumer classification (R14 — full workspace grep mandatory per Codex R13):** every existing `get_handoff` caller classified as: (a) summary consumer → migrate to `mcp__research-mcp__get_handoff_summary`; (b) full-artifact consumer → migrate to `mcp__portfolio-mcp__get_handoff_full`; (c) tests asserting artifact presence → updated to test the appropriate variant or split into summary-test + full-test pair. **Discovery command (R14 — full workspace first):**
   ```
   rg -n "get_handoff|get_handoff_summary|get_handoff_full|mcp__.*get_handoff|artifact_summary|artifactSummary" \
     ~/Documents/Jupyter \
     --glob '!**/.claude/**' --glob '!**/agents/**' --glob '!**/__pycache__/**' \
     --glob '!**/node_modules/**' --glob '!**/.git/**' --glob '!**/-dist/**'
   ```
   Required artifact: classification table per caller (path + line + classification: summary/full/test/out-of-scope). **R14 mandate:** run the full workspace grep FIRST; THEN explicitly classify out-of-scope hits with rationale per repo. Examples of valid out-of-scope rationales: "archive — preserved unchanged"; "deployment mirror (`-dist` repo) — synced from source repo, no action needed"; "documentation reference, not consumer code". Codex R13 found `agent-orchestrator` and `risk_module-big-impl` may contain references — explicit classification required, not skipped by default.
   MUST also include manual review of: (a) persisted prompt/event store records (chat logs, replay fixtures) for hard-coded `get_handoff` references that grep doesn't catch — query event store for `tool_name='get_handoff'`; (b) cron jobs / scripts under `risk_module/scripts/` and `AI-excel-addin/scripts/`; (c) repo-local skill evals (`api/memory/workspace/notes/skills/`); (d) frontend hooks (`risk_module/frontend/.../HandoffReviewView.tsx`+ similar). Cutover PR uses the classified mapping (NOT blind find-and-replace). Verified against tests at `tests/test_research_mcp.py:884` (full-artifact consumer pattern exists).
0h. Persisted-record migration script(s) designed + tested against fixtures pre-merge per the §"persisted-record migration" record-class table (9 classes incl. `tool_timing` SQLite). **`migrate_tool_timing.py` interface contract (R14 — grounded in actual `cost_tracker.py:12` per Codex R13):**
   - Path: `risk_module/scripts/migrate_tool_timing.py` (new)
   - **DB path resolution (R15 — REQUIRED env var per Codex R14):** reads `TOOL_TIMING_DB_PATH` env var (REQUIRED — exit-2 if absent). NO sibling-repo discovery / no default fallback. Operator sets via shared `.env` (gateway + migration script read same file). Production path: `<AI-excel-addin>/api/logs/cost.db` per `cost_tracker.py:11` `_DB_PATH = Path(__file__).parent / "cost.db"`. Both `gateway` service and `migrate_tool_timing.py` MUST set the env var to the same absolute path.
   - **Lock path resolution (R14):** reads `TOOL_TIMING_LOCK_PATH` env var; defaults to `<DB_PATH dir>/.tool_timing_lock` so lock lives next to DB on same filesystem (addresses Docker/remote concerns).
   - Args: `--dry-run` (default OFF), `--since=<ISO_TS>` for resume, `--max-iter=<N>` (default 5), `--timeout=<seconds>` (default 60), `--verbose`
   - Exit codes: 0 = success (lock cleared); 1 = fail-closed (lock retained, stale rows remain); **2 = config error** (lock path not visible to gateway process — script fails fast before locking)
   - **Lock mechanism (R14, mandatory):** sentinel file at `TOOL_TIMING_LOCK_PATH`. Both gateway `tool_timing_hook` and migration script read same path from env var (shared `.env` or service config). Env-var-only lock is FORBIDDEN (can't propagate to running gateway).
   - `--resume` semantics: rerun catch-up loop with provided `--since` timestamp; reuse existing lock; if lock not set, set it; if catch-up succeeds, clear lock.
   - Idempotent: safe to rerun on already-migrated state (UPDATE matches zero rows; SELECT returns 0; immediately clears lock).
   - **Pre-flight check:** script verifies `TOOL_TIMING_LOCK_PATH` is writable AND that gateway can read same path (operator confirmation OR env probe). Fails exit-2 if unverified.
   Per-class disposition documented; post-migration validation queries defined

### Phase 1 acceptance (R5 — single cutover, no cross-listing)

1. Second FastMCP entrypoint (`research-mcp`) registered + reachable per Phase 0 launch contract; same middleware stack as portfolio-mcp; `services-mcp` `service_status("risk_module_research_mcp")` returns healthy.
2. **Middleware transport test:** meta-injection contract round-trip with a canary fake tool that asserts on `_USER_EMAIL_CTX`. Real user-owned-tool verification deferred to Phase 2c.
3. The 4 envelope-keyed corpus tools (`filings_search`, `transcripts_search`, `filings_list`, `transcripts_list`) registered ONLY on research-mcp (removed from portfolio-mcp). They produce `source_envelope` (Slice A extractor unchanged — `canonical_tool_name` strips server prefix per `citations.py:302-307`).
4. **All consumer sites updated atomically in the cutover PR** per §"Consumer-site sweep" table — including agent profiles (`api/agent/profiles/analyst.py`, `advisor.py`) and repo-local skill evals (`AI-excel-addin/api/memory/workspace/notes/skills/...`, `AI-excel-addin/tests/skill_evals/...`).
5. **Persisted-record migration script ran successfully** per record-class table dispositions; replay tests pass on rewritten records; "Leave historical" classes documented in release notes.
6. **Active-session cutover behavior verified** (R5 — Codex R4 added; R6 expanded with test infra requirement):
   - **New-session test:** session opened post-cutover sees research-mcp tools correctly via `tools/list`; `filings_search` etc. callable.
   - **Stale-session test:** session loaded BEFORE cutover, calling `mcp__portfolio-mcp__filings_search` post-cutover, gets a clear "tool not found" error (visible failure, not silent drift). Stale-session re-`load_tools` recovers.
   - **Test fixture infrastructure (R8 — reload-recovery grounded in actual session APIs per Codex R7):** Phase 1 builds new fixture infrastructure to model "session created before MCP catalog cutover, then server catalog changes." Adjacent existing patterns to extend: `tests/mcp/test_mcp_meta_transport.py` (fake MCP/dispatcher meta injection), `tests/test_autonomous_mcp_session_injection.py` (fake `McpClientManager`), `tests/test_create_agent_mcp_gateway_changes.py` (manager/dispatcher wiring). **Fixture API:**
     - `catalog_v1` — pre-cutover tool registry (corpus tools on `portfolio-mcp`)
     - `catalog_v2` — post-cutover tool registry (corpus tools on `research-mcp`)
     - **Stale prompt tool list** — frozen at session start; references `mcp__portfolio-mcp__filings_search` etc.
     - **Current dispatcher routing** — uses `catalog_v2` for live calls
     - **Reload recovery (R13 — minimal `_ServerState`/routing model per Codex R12):** Codex R7 verified `load_tools` reads current `mcp_clients.get_server_catalog()` (`tool_handlers.py:672`, `mcp_client.py:263`). The fixture injects `catalog_v2` by swapping the fake's catalog directly. **R13 fake-manager extension scope:** Codex R12 verified existing `_FakeMcpClientManager` (`test_autonomous_mcp_session_injection.py:46`) only has `inline_servers`/`get_server_names()`/`get_tool_definitions()` — NO internal routing state. R13 specifies Phase 1 introduces NEW state, not just propagation:
       - **Minimal `_ServerState` per-server record** (server_name, tool_list, plus tool→server routing entries)
       - `set_catalog(catalog)` rebuilds all `_ServerState` records AND the routing maps (tool→server, prefixed→original)
       - Production methods `set_catalog()` must satisfy: `get_server_names`, `get_server_catalog`, `get_tool_definitions`, `get_server_tool_definitions`, `is_mcp_tool`, `get_server_for_tool`, `resolve_tool_name`, **`call_tool`**
       - Fake's `call_tool(prefixed_tool_name, args)` dispatches via the routing map; **returns `(None, {"code": "unknown_tool", "message": "Unknown tool: <name>"})` tuple** matching production `mcp_client.py:293` (R14 — Codex R13 verified there is no `ToolNotFoundError` exception; production returns structured error)
       - Tests verify both **discovery** (server-list, tool-list) AND **dispatch** (`call_tool` returns the `unknown_tool` structured error for old-prefix names post-swap)
       - Bounded NEW state; Phase 1 scope reflects this (not a "propagate to existing" task — it's "introduce minimal routing model in fake").
     Tests exercise: stale-session call to `mcp__portfolio-mcp__filings_search` returns clear "tool not found" error; new-session sees `catalog_v2` correctly; stale-session post-`load_tools` works.
   - **Cutover step is explicit:** restart all relevant services (`risk_module`, `risk_module_research_mcp`, agent-gateway clients) as part of the deploy procedure; documented in release notes, not inferred.
7. `CHANNEL_TIERS` updated (research-mcp always-tier across all 4 channels); `_MCP_META_INJECT_SERVERS` extended to include research-mcp; `ALLOWED_SERVERS` updated; `ServerPolicy` for research-mcp added with explicit `known_read_tools` (the 4 envelope-keyed tools, with one-line justification per R3 eligibility rule) + empty `known_write_tools`.
8. F56 audit (a) + (b) status documented: F56 block stays in place this phase; retirement scheduled for Phase 4.
9. TUI test (no `mode=research` flag, no prompt nudge): natural-language corpus query produces `[Sn]` citations + Sources footer.
10. Existing V2.P2 + V2.P9 tests pass; middleware transport test added.

### Phase 2 acceptance (R4 — 2a/2b/2c sub-stages)

**Phase 2a (payload enrichment, both core/corpus and mcp_tools/corpus layers):**
10. `core/corpus/filings.py` and `transcripts.py` read/excerpt functions expose `document_id`, `section`, `char_start`, `char_end`, `url` (or canonical citation primitives per Slice A spec); `DocumentMetadata` lookup helper present.
11. `mcp_tools/corpus/filings.py` and `transcripts.py` read/excerpt MCP wrappers echo enriched fields in response payloads (additive, no back-compat break).
12. Local fixture-based tests verify enriched payloads against canonical fixture filings/transcripts.

**Phase 2b (extractor extension, AI-excel-addin):**
13. `citations.py:extract_sources` extended for `filings_read`, `transcripts_read`, `filings_source_excerpt`, `transcripts_source_excerpt`.
14. `[Sn]` citations emit for read/excerpt tool results in live test.

**Phase 2c (cutover the next batch — straight refactor, no cross-listing):**
15. **Group A — corpus read/excerpt (4 tools):** registered ONLY on research-mcp (removed from portfolio-mcp); consumer sites updated; persisted-record migration script run.
16. **Group B — foundational reads (13 tools, R10 with `get_handoff` split per Codex R9):** `list_research_files`, `read_research_thread`, `get_research_brief`, **`get_handoff_summary`** (NEW — projection tool replacing whole-`get_handoff` move; on research-mcp), `thesis_list`, `thesis_read`, `thesis_latest_scorecard`, `thesis_list_decisions_log`, `thesis_list_links`, `get_diligence_state`, `list_process_templates`, `get_process_template`, `get_action_history`. **`get_handoff_full` stays on portfolio-mcp** (defer-tier). Moved per per-tool table; **R10 boundedness rule applied** (row-count caps + payload-size projection contract); `get_handoff_summary` requires its own `_project_handoff_summary` helper that strips `artifact` (current `_normalize_handoff_artifact_summary` includes it); `get_diligence_state` read-only verified end-to-end; `start_research` and `activate_diligence` confirmed staying in portfolio-mcp.
17. **Active-session cutover behavior verified for Phase 2c batch:** new-session sees moved tools; stale-session gets clear "tool not found" errors on old prefixes; restart procedure documented per Phase 1 acceptance #6 pattern.
18. No regression in V2.P9 plan tests; envelope fires for newly-moved-and-extracted tools.

### Phase 4 acceptance (R5)

19. F56 audit (a) + (b) passed; `_RESEARCH_AUTO_LOAD_SERVERS` block removed (or explicitly kept as belt-and-suspenders with rationale).
20. Docs sweep complete: living docs updated (CLAUDE.md, AGENTS.md, README.md, `docs/interfaces/mcp.md`, `docs/reference/MCP_SERVERS.md`, `docs/planning/CORPUS_ARCHITECTURE.md`, `AGENT_INFRASTRUCTURE.md`, V2_P2_*); archived/historical docs preserved unchanged.
21. F56 + F62 + C.4 follow-ups closed as moot.

---

## What this enables

- **V2.P2 reaches its target audience** — citation discipline is the default, not an opt-in
- **Future research tools** (any new corpus surface, transcript layer, deck integration) inherit always-tier by default
- **F56/F62/C.4 retire** — the workaround stack collapses
- **Cleaner mental model** — portfolio-mcp = portfolio operations; research-mcp = research workflow
- **Path forward for other categorization corrections** — if `model-engine` should split, or `fmp-mcp` should split, the precedent is set

---

## Files this plan would touch (preview)

### risk_module
- `mcp_tools/corpus/` → `mcp_tools/research/` (or new sibling `mcp_tools/research_mcp/`)
- `mcp_server.py` — server registration, tool advertisement
- `agent/registry.py:1500-1507` — corpus tool category (already research)
- `docs/planning/CORPUS_ARCHITECTURE.md` — server name updates
- `docs/planning/V2_P2_CITATION_FIRST_QA_PLAN.md` — server name updates
- `docs/planning/V2_P10_RESEARCH_MCP_SPLIT_PLAN.md` — this file (status updates as phases ship)

### AI-excel-addin
- `api/agent/shared/tool_catalog.py:39-58` — CHANNEL_TIERS update
- `api/agent/shared/server_policies.py` — registered tool list update
- `api/agent/interactive/runtime.py` — F56 fix block can be retired post-Phase-1
- Gateway dispatcher routing — new server name registration (no alias layer; old prefixes return tool-not-found post-cutover per straight-refactor framing)
- TUI / dev CLI consumers — update server name references

### agent-gateway-dist
- New version published if MCP-side changes (likely yes for tool catalog updates)

---

## Sequencing call (R18)

**Full split (Phases 0, 1, 2, 4 — Phase 3 removed in R4) as straight refactor, ~6-8 weeks.** Phase 1-only fits ~4-5 weeks and delivers the V2.P2 unblock goal. **See §"Current Implementation Contract" above for the authoritative quick reference.**

R18 changes from R17 (1 narrow blocker + 2 cleanup applied):
- **`tool_packs` runtime claim corrected** — `SkillProfile.tool_packs` is parsed metadata only (`skills.py:33, 228, 342`); no demonstrated runtime use; only `tool_packs_enabled` is consumed (`tool_handlers.py:908`). Plan reframes as "audit because skill files may encode deferred pack names/server assumptions, but verify whether runtime currently consumes it during impl."
- **Stale "back-compat alias" reference removed** — Files preview corrected to "Gateway dispatcher routing — new server name registration (no alias layer; old prefixes return tool-not-found post-cutover)."
- **Phase 0 criterion count synced** — "8-criterion list (0a–0h)" matches actual list (R12 added 0g consumer-classification).

R9 changes preserved:
- `mcp_bootstrap.py` import-safety carveout
- `tool_timing_hook` flag-check at hook entry
- `build_initial_user_message` as 6th ProfileConfig surface
- Direct registration (`mcp_research.tool()(_corpus_filings_search)`) preferred for schema preservation

**Core framing (Codex R4 verified: "the straight-refactor reframe is basically correct"; preserved through R5–R17):**
- Cross-listing structurally impossible AND solving wrong problem for Hank's stage. Each tool group ships in one cutover PR.
- No live alias canonicalization layer.
- Phase 3 (deprecation timeline + cross-listing removal) eliminated.
- Persisted records use one-time migration script, not forever-alias.
- Effort stable at ~6-8 weeks full / ~4-5 weeks Phase-1-only.

**Cross-repo prerequisites (Phase 0):**
- Catalog-key rename `research-mcp` → `research-workbench-mcp` (R19 — `~/.claude.json` user-edits + AI-excel-addin code rename only; no investment_tools commit). PR0a/b/c three-step.
- AI-excel-addin catalog migration to `research-workbench-mcp`
- FastMCP process model decided (default Option B; A only if 5-criterion harness passes)
- Hidden-dependency audit (`_MCP_META_INJECT_SERVERS`, `_RESEARCH_AUTO_LOAD_SERVERS`, `get_mcp_context`)
- Consumer-site inventory frozen
- Persisted-record migration script designed + tested

After Phase 0, Phase 1+ proceed.

**Why R4 is Codex-review-friendly:** the framing now matches the actual nature of the work — internal refactor on pre-launch product, not API migration with consumer back-compat. Architectural complexity (transport, payload enrichment, eligibility rule) is preserved; transition-window scaffolding is dropped because the transition window doesn't exist.
