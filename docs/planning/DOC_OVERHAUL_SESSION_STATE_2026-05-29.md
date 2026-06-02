# Doc Overhaul — Session State (2026-05-29)

Resumption handoff for the documentation overhaul. **Nothing is committed** — all edits/new docs are uncommitted drafts in the working tree for review via `git diff`.

## Goal
Make the codebase friendlier for a new dev (and us): fix doc↔code drift, fill gaps, establish canonical "how it works" docs. AI-coded repo → docs had drifted. Read/write docs only; code defects are filed to TODO for plan→Codex (no code changes made directly).

## Durable artifacts (read these to reconstruct everything)
- `docs/DOC_HEALTH_AUDIT_2026-05-29.md` — the audit (109 canonical docs; 62 surgically edited; drift table; gaps; target architecture; 18-item queue).
- `docs/DOC_REWRITE_BATCH1_2026-05-29.md` — Batch 1 report (11 items; review checklist).
- `docs/DOC_REWRITE_BATCH2_2026-05-29.md` — Batch 2 report (will exist once Batch 2 finishes).
- `docs/planning/MCP_TOOLING_MAP_REWRITE_PLAN_2026-05-29.md` — R3 re-author contract (grep-verified facts + outline).
- `docs/TODO.md` `## Bugs` — filed: (a) 3 code↔doc drift defects, (b) security item (validation handler echoes error detail in all envs; `sanitize_error_message` never built).

## Done
- **Audit workflow** (doc-health-reconcile): 62 docs surgically corrected vs live code (uncommitted).
- **RELEASE_SCRUB_FINDINGS.md** — reverted to HEAD (audit over-edited a dated 2026-03-12 snapshot; restored).
- **Batch 1** (doc-rewrite-batch1): 11 items. 4 solid / 6 minor-fixed / 1 needs-rework. Triages all → RETIRE (AWS_SECRETS_MANAGER_MIGRATION_GUIDE, SECURITY_IMPLEMENTATION_PLAN, GATEWAY_MULTI_USER_ACTIVATION — banners added, files left in place for human archiving). New: AGENT_RUNTIME_AGENT_MAP, DATA_INGESTION_AGENT_MAP, DATABASE_REFERENCE additions, provider 4-gate routing model. All drafts in tree.
- **R3 (MCP_TOOLING_AGENT_MAP)** — Batch 1 FABRICATED a 4-tier system; **reverted to HEAD**. Being re-authored via plan→Codex.

## Running / in-flight
- **Batch 2 workflow** — Task `w9zu0tpec` / run `wf_f2cd2892-19e`. 16 docs (CORPUS map+arch, OVERVIEW_EDITORIAL, RISK_ENGINE, CONFIG_DATA_TABLES, IBKR_TRANSPORT, FUTURES_PRICING, NEW_BROKERAGE_PROVIDER + FRONTEND_DATA_SOURCE playbooks, SCHEDULED_JOBS, api.md + MCP_SERVERS augments, 4 frontend READMEs) through author→verify→**fabrication-hunter**, then docs/README.md index refresh → report. Drafts only.
- **R3 plan→Codex** — plan written. Codex review call **TIMED OUT at the MCP layer** (may still be running). Codex OAuth had been invalidated mid-session; user reconnected via `/mcp`. NEXT: re-run the review (or `codex resume`); iterate to PASS; then **implement via `mcp__codex__codex`** (sandbox `workspace-write`, `approval-policy:"never"`, cwd repo root, do NOT pass model/reasoning — inherit config.toml).

## Decisions locked (user)
- Editorial observability (#1): DOC is the issue → rewrite doc to real sink, not code.
- tests/README → rewrite; CLAUDE_ORCHESTRATION map → rewrite to live `agent/` runtime; 3 plan docs → retire-or-rewrite; **BRAND.md → DO NOT touch (actively used for UI work)**.
- RELEASE_SCRUB_FINDINGS → keep as dated snapshot (reverted).
- R3 → revert + plan→Codex (NOT autonomous).
- Batch 2 → launch with fabrication-hunter gate.

## Next steps (after Batch 2 lands + Codex review returns)
1. Re-run/finish Codex review of the R3 plan → PASS → implement MCP_TOOLING_AGENT_MAP via Codex.
2. Summarize Batch 2 (fabrication-hunter results; any fail/needs-rework; what needs user eyes).
3. Surface for user review: full `git diff` of all drafts (audit 62 + Batch 1 + Batch 2); the review checklists are in each report.
4. User reviews + commits doc paths (path-scoped; keep clear of the parallel session's `frontend/packages/*` changes).
5. Open user decisions: security item (#T2 accept-vs-fix); physical archiving of the 3 RETIRE'd plan docs; T3 gateway boot-crash claim needs AI-excel-addin confirmation.

## UPDATE — later 2026-05-29

- **R3 DONE.** `MCP_TOOLING_AGENT_MAP.md` re-authored via plan→Codex: plan Codex-reviewed (FAIL→fixed→PASS), Codex implemented, 2 stale `MCP_SERVERS.md` cites corrected (smoke `:147-162`→`:208-238`; restart `:169`→`:195/:245`). Fabrication check clean (0 tier symbols; `INTERNAL_ONLY_PORTFOLIO_TOOLS`/`UserIdMiddleware`/`resolve_user_email` all present). 171-line draft, uncommitted. (Plan doc still has 3 cosmetic stale cites at lines 28/44/64 — doc is correct, plan is spent; ignore.)
- **BATCH 2 FAILED on the Anthropic session limit (resets 1:20am America/New_York).** All 16 pipeline items errored ("subagent completed without calling StructuredOutput"); synth returned "You've hit your session limit." 46 agents / ~4.2M tokens burned, no valid structured output.
  - **BUT 10 author-stage drafts WERE written to disk before the limit hit — UNVERIFIED (never went through verify or fabrication-hunter). DO NOT TRUST until audited.** Untracked: `docs/architecture/CORPUS_ARCHITECTURE.md`, `docs/architecture/IBKR_TRANSPORT_AND_RELAY.md`, `docs/architecture/agent-maps/{CORPUS_AGENT_MAP,OVERVIEW_EDITORIAL_AGENT_MAP,RISK_ENGINE_AGENT_MAP}.md`, `docs/reference/{CONFIG_DATA_TABLES,FUTURES_PRICING_CHAIN}.md`, `docs/guides/{NEW_BROKERAGE_PROVIDER_PLAYBOOK,FRONTEND_DATA_SOURCE_PLAYBOOK}.md`, `docs/ops/SCHEDULED_JOBS.md`. (May be complete or truncated — unknown.)
  - **NOT created (limit hit first):** 4 frontend package READMEs (A3-A6), `api.md` augment (A1), `MCP_SERVERS.md` augment (A2), `docs/README.md` index refresh.
  - **STRAY FILE:** `docs/PLANNING_SQL_REVIEW.md` appeared — NOT one of the Batch-2 items. Left untouched; flag to user (confused agent or parallel session?).
  - `docs/DOC_REWRITE_BATCH2_2026-05-29.md` report = useless (stats all 0; limit error).
- **RESUME PLAN (after 1:20am reset):** one consolidated workflow → (a) fabrication-hunt the 10 existing drafts (keep/fix/redo per result), (b) author+verify+fab-hunt the 6 not-created items, (c) index refresh. Lower concurrency to avoid re-tripping the limit.

- **RESUME SCHEDULED.** (Aside: I briefly launched the resume at 23:49 ET — *before* the 01:20 reset — then stopped it; it left no partial writes.) Created a one-time scheduled run `doc-batch2-resume` (scheduler-mcp / launchd) for **2026-05-30 01:30 ET** that fires `…/workflows/scripts/doc-rewrite-batch2-resume-wf_01a19427-d93.js` and appends results here. ⚠️ The launchd spec (`Month=5 Day=30 Hour=1 Minute=30`) recurs yearly — **delete it after it runs**: scheduler-mcp `schedule_delete doc-batch2-resume`.

## Gotchas this session
- Bash/Read returned corrupted/stale output for `app.py` and `docs/TODO.md` at points (cache) — re-verify suspicious reads with a fresh call.
- Workflow `args` did not pass through — embed constants in the script instead.
- `docs/TODO.md` tail had pre-existing duplicate-looking entries from a parallel session; left untouched.
