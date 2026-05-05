# V2.P2 — Citation-First Filing Q&A — MVP Scoping

**Status:** SLICES A+B+C SHIPPED 2026-05-01..02 + F55+F56 closed — Slice D (React) next
**Spec source:** `docs/planning/BETA_RELEASE_GAP_AUDIT.md` §T1.1
**Depends on:** V2.P1 corpus (PHASES 0+1+2+3 SHIPPED, gate-coverage PASS, live-validated through Hank)
**Effort:** 2-3 weeks total across slices; ~1.5 weeks for MVP cut (A+B+C)
**Cross-repo:** Mostly lives in `AI-excel-addin/` (gateway runtime + frontend). Some risk_module-side hooks possible.
**Post-V2.P10 note:** Citation-envelope corpus tools are served from `research-mcp` by default. `portfolio-mcp` no longer hosts the corpus read/search surface.

## Slice ship status

| Slice | Status | Plan / commits | Notes |
|---|---|---|---|
| **A** — Backend citation envelope | **SHIPPED 2026-05-01** | Plan: `completed/V2_P2_SLICE_A_PLAN.md` (R7 PASS after 7 Codex review rounds). Commits: AI-excel-addin `e14f5e9` (gateway) + `d71ab75` (app); agent-gateway-dist `df24be3` (`ai-agent-gateway==0.14.0` on PyPI); risk_module `cac57f92` (plan doc + F55). | Ships `_event_only` SSE block sentinel + per-runtime `SourceRegistry` + 4-tool extractors (search + list, filings + transcripts; post-V2.P10 source server is `research-mcp`) + cached citation-discipline prompt with worked example. Live-verified via dev_chat_cli — `[S1]`-`[S10]` referenced correctly across cross-tool parallel calls. Also fixes a latent runner bug where hook-returned text blocks interleaved between `tool_result`s, violating Anthropic's tool-use→tool-result-immediate-after constraint. **A.5 deferred**: read/excerpt tools + `load_document` + sub-agent registry propagation + SDK live corpus path (each gated on real prereqs Codex identified). **F55 filed**: corpus list-arg Pydantic schema rejects bare-string inputs from LLM, ~1-2h fix. |
| **B** — Server-side validator gate | **SHIPPED 2026-05-02** | Plan: `completed/V2_P2_SLICE_B_PLAN.md` (R10 PASS after 10 Codex review rounds + R11 OAuth amendment). Commits: AI-excel-addin `523bb6d` (gate impl: citation_judge, validation_event_log, validation_runner, citations.py extensions, runtime.py wire-in, 55 tests) + `92830bc` (F56 auto-load + OAuth Claude Code header fingerprint fix); risk_module `4683c8ed` (plan doc + F56 followup) + `be734491` (F56 closed: corpus tool description rewrites). | Ships hybrid validator: regex floor (currency/percent/multiples/spelled-units/bps/ratios) + LLM-judge ceiling (Haiku Path 2 confirm + Path 3 qualitative full_scan), all wrapped via two-layer `CitationValidationEventLog` + `RunnerWithCitationValidation` so terminal `stream_complete` is buffered until pending validation drains. Soft mode default — emits `citation_validation` SSE event with violations as overlay; never blocks user response. Anthropic-only provider gate; SDK + OpenAI/Codex AgentRunner paths skipped. Operator-credentialed judge with daily $5 budget cap, graceful regex-only fallback when auth missing/budget exhausted. Drain timeout (5s) emits `validation_timeout` event for observability. Live-verified all 3 paths: Path 1 clean × 10, Path 2 confirm × 2, Path 3 full_scan × 6; 20 fabricated_index violations caught when LLM emitted `[S1]`/`[S2]` without populating registry. **R11 amendment** (post-R10-PASS): live verification revealed dev gateway uses `ANTHROPIC_AUTH_MODE=oauth`. JudgeClient extended to support OAuth via Claude Code CLI fingerprint (`X-Api-Key=Omit()`, `anthropic-beta` slugs, `user-agent=claude-cli/...`, `x-app=cli` headers + "You are Claude Code" system prompt) — mirrors `agent_gateway/providers/anthropic.py:336-348,422-423`. Verified live: zero 401 errors in gateway logs after fingerprint fix. **F56 closed** (during Slice B verification): two fixes — (d) auto-load `portfolio-mcp` when research mode detected (removes `load_tools` round-trip friction), (c) corpus tool descriptions rewritten to lead with citation-grade value prop. Original "LLM never picks corpus tools" framing was partly wrong; LLM correctly routes structured-numeric queries to `get_metric` and narrative queries to corpus search. Live-verified with corpus-flavored query: 21 distinct `[S1]`–`[S21]` references emitted, all clean, zero violations. |
| **C** — Dev CLI source chips | **SHIPPED 2026-05-02** (parallel with Slice B) | Plan: in-conversation Codex R2 PASS. Commit: AI-excel-addin `f980b39`. | Three additions to `api/dev/chat_cli.py` (~1492 LOC including the previously-untracked CLI itself): per-stream `SourceRegistry` from `source_envelope.registry_snapshot` (server-authoritative dedup), inline `[Sn]` ANSI styling (bright yellow + bold) with chunk-boundary lookahead buffering, end-of-turn Sources footer with full document_id + section + URL + snippet preview (HTML-stripped). Plus `--no-citations` flag. 8 unit tests + live-verified on cross-source MSFT vs GOOG cloud query (30 styled `[Sn]` tokens inline + Sources footer with SEC URLs). Codex R1 caught wrong assumption — source_envelope is nested wrapper (`sources_for_call` + `fresh_sources` + `registry_snapshot`), not flat. R2 fix: use `registry_snapshot` from server as authoritative, no client-side dedup. |
| **C.1** — TUI source chips | **SHIPPED 2026-05-02** (Stage 1 only) — commit AI-excel-addin `2eb1ceb` + version bump @henrychien/agent-gateway-tui 0.1.0 → 0.1.1 | Plan: in-conversation Codex R1 FAIL → R2 FAIL → R3 PASS. Catches across rounds: source_envelope is nested wrapper not flat (R1), agent-gateway-tui uses pi-tui not Ink (R2), turn-end is `terminal_complete` from `stream_complete` not `turn_complete` (R2), `EventAdapter.handleEvent()` is the right anchor not `tui.ts` (R1.P2 #1), don't break `normalizeBackendEvent()` signature (R1.P2 #2). | **MVP scope (Stage 1 only)**: end-of-turn Sources footer in `packages/agent-gateway-tui` (TypeScript + `@mariozechner/pi-tui`, NOT Ink). Adds `SourceRegistry` class + `SourcesFooter` pi-tui Container + `EventAdapter.extractSources()` hook from raw `tool_call_complete.final_tool_result_blocks` + `ChatLog.addSourcesFooter()` method. Footer renders on `terminal_complete`, registry resets per turn. ~200-300 LOC + 8 unit tests via Node native test runner. **Stage 2 (inline `[Sn]` markdown bolding)** deferred to C.2 — Markdown component constraints + per-line color callback make per-substring styling non-trivial. **History persistence gap** (footer not reconstructed on reload) accepted as C.1 scope; persistence in `persistCompletedRun` deferred to C.2. Patch version bump 0.1.0 → 0.1.1 (signature unchanged = no break). |
| **C.3** — TUI citation_validation event handling | OPTIONAL — file for future | TBD plan | TUI emits "Unknown SSE event" warning per turn for Slice B's `citation_validation` events because the event-adapter wasn't taught about this type. **Surfaced 2026-05-02** during C.2 live test — every Hank turn writes a console warning with `{type: 'citation_validation', schema_version: 1, turn, violations[], violation_count, total_claims_detected, total_sources_in_registry, judge_called, ...}`. **Three scope levels**: (1) **Minimal** — register as known event so warning silences (~15 LOC, half-hour); (2) **Useful** — render validation summary in Sources footer ("validated ✓ N claims · M sources" or "⚠ K violations"), ~50 LOC, half-day. Surfaces institutional-trust signal directly in citation render; (3) **Rich** — separate validation panel with claim-by-claim violation details + judge reasoning, 1-2 days. **Lean #2** — visible institutional-trust win; #1 is just hiding the warning. Filed per user request 2026-05-02. |
| **C.4** — Cross-MCP citation discipline (edgar-financials extractors) | **CLOSED AS MOOT 2026-05-04 via V2.P10** | Plan: `V2_P10_RESEARCH_MCP_SPLIT_PLAN.md` R21 | Original issue: Slice A extractors covered corpus tools while those tools were hidden behind deferred `portfolio-mcp`, so the agent often routed to always-loaded `edgar-financials` and produced zero `[Sn]` citations. V2.P10 moved the corpus citation-envelope tools to always-tier `research-mcp` across all channels. Citation discipline for corpus answers is now the default path; edgar-financials remains a live-fetch fallback, not the primary corpus Q&A surface. |
| **D** — React research chat page | **NEXT** | TBD plan | Net-new page at `frontend/packages/ui/src/pages/`. Uses existing `useResearchChat` hook extended to surface `source_envelope` blocks from the SSE stream. Renders inline `[Sn]` chips with hover-able document_id + section + URL; sidebar source list aggregating per-turn registry snapshots. Validator overlay — render violations from `citation_validation` events as inline yellow underlines + tooltips on flagged spans. 1-2 weeks. Foundation work (citation envelope + validator) all live; D is the user-visible product surface. |
| **E** — Span-scroll iframe | After D + F44 | TBD plan | Fintool-style "click chip → highlighted source." Blocked on F44 (markdown↔HTML offset map). 1+ week. |

**Sequencing call** (locked 2026-05-01): Path 2 — B before C. Slice A's mechanism only matters if the validator enforces it; without B, citation discipline is suggestion not contract.

---

## Why this matters

V2.P1 corpus is producing analyst-grade output through Hank dev chat — verbatim quotes, table citations, multi-source synthesis. **But that capability only exists in the dev CLI today.** V2.P2 wraps it in a user-facing surface with citation discipline (every claim → source span). Per gap audit T1.1: this is the #1 institutional-credibility gate ("the difference between 'impressive prototype' and 'we could sell this alongside what Fintool sold'"). Blocks v2 launch.

---

## Discovery findings (2026-05-01 session)

### Gateway runtime lives in AI-excel-addin

- `AI-excel-addin/api/agent/interactive/runtime.py` — main runtime with `on_tool_result` hooks where source data flows
- `AI-excel-addin/api/agent/interactive/tool_dispatcher.py` — tool call dispatch
- `AI-excel-addin/api/agent/profiles/prompts/analyst.md:106` — existing analyst prompt; says "cite the source/tool in concise form" but no structured envelope contract
- `persist_research_tool_result` (imported in runtime.py:76) already captures tool results — existing scaffolding to hook into

### Current response shape (no citation envelope)

- LLM streams `text_delta` events with citations embedded as text (`[transcript: MSFT_2026-Q3]`, `[10-Q link]`, etc.)
- Final `stream_complete` event carries usage but no structured sources
- Frontend (`frontend/packages/connectors/src/features/external/hooks/useResearchChat.ts`) reads the stream

### Corpus tool side is already citation-ready

Every `filings_search` / `transcripts_search` `SearchHit` already returns:
- `document_id` (deterministic, re-resolvable)
- `source_url_deep` (direct authoritative link)
- `section` + `char_start` + `char_end` (byte-precise location)
- `filing_date`, `fiscal_period`, `ticker`

The data exists. The gap is plumbing it to a structured `sources[]` envelope on the response side.

### Existing UX scaffolding

- `useResearchChat` hook exists (`frontend/packages/connectors/src/features/external/hooks/useResearchChat.ts`) — already consumed by some frontend
- `ResearchStreamContext` exists — citation chips could plug in here
- F25 handoff report renderer has source chips — pattern reference, not directly reusable

### What does NOT exist

- Any structured `sources[]` field in the response envelope
- Server-side citation validation gate (claims-without-sources block)
- Click-to-source span iframe (Fintool span-iframe pattern) — also blocked by F44 (markdown↔HTML offset map)
- A research chat page in `frontend/packages/ui/src/pages/` (the existing pages are PlaidSuccess, SnapTradeSuccess, LandingPage, InstantTryPage)

---

## MVP slicing

| Slice | Scope | Effort | Repo | What it validates |
|---|---|---|---|---|
| **A — Backend citation envelope** | Add structured `sources[]` to Hank's response (every tool result that returns source data → entry in sources). LLM continues emitting inline `[Sn]` references where `Sn` indexes into the array. Server-side, no UI work. | 3-5 days | AI-excel-addin | Sets up the data shape for everything downstream. Ships discipline before UX. |
| **B — Citation validator gate** | Server-side validation that blocks Hank responses if claims lack matching source entries. Builds on A. Per gap audit: "Missing or malformed citations BLOCK render, not degrade silently." | +3-5 days | AI-excel-addin | Enforces the "no claim without source" contract. Load-bearing for institutional trust. |
| **C — Source chips in dev CLI** | Render inline `[Sn]` chips with hover-able document_id in the existing `chat_cli.py` dev tool. No web UI. Validates the citation render pattern in tools we already use. | 1-2 days | AI-excel-addin | Proves the UX pattern in our existing tooling before sinking time into React. |
| **D — Research chat page** | Net-new React page in `frontend/packages/ui/src/pages/` (e.g., `ResearchPage.tsx`). Renders citation chips + sidebar source list. Uses existing `useResearchChat` hook. | 1-2 weeks | risk_module (frontend) | The real product surface. |
| **E — Span-scroll iframe** | Fintool-style "click chip → highlighted source." Per spec, needs F44 prereq (markdown↔HTML offset map). | +1 week | Mostly risk_module + a renderer service | Polished click-through UX. Final piece of T1.1 spec. |

### Recommended sequencing

1. **Slice A → B → C** as the MVP cut (~1.5 weeks). Backend citation discipline + dev CLI render. Gets the load-bearing primitive shipped before sinking time into React. If A+B reveal data-shape problems, no React rewrite needed.
2. **Slice D** as Phase 2 of T1.1 once A+B+C are battle-tested.
3. **Slice E** when F44 is implemented (markdown↔HTML offset map currently backlog) — Fintool-grade polish, lower priority than D.

### Alternative: jump straight to D

Trade-off — faster demo-able UX, more rework risk if A/B reveal data-shape issues. Pick this if a demo deadline drives the call.

---

## What a fresh-session pickup looks like

The next session should:

1. **Re-verify V2.P1 corpus state** — `python3 scripts/corpus_health_report.py --gate-coverage` should still PASS (post-soak this should also include OPERATIONAL SHIPPED state if we're past 2026-05-14)
2. **Read the gateway runtime** (`AI-excel-addin/api/agent/interactive/runtime.py`) — particularly the `on_tool_result` flow and the SSE event types emitted to `useResearchChat`. Cross-repo, unfamiliar code — budget time.
3. **Investigate the SSE event shape** — what events does the gateway emit? `tool_call_start`, `tool_call_complete`, `text_delta`, `turn_complete`, `stream_complete` are visible in the dev CLI output. Slice A would add a new `sources_update` event (or include sources in existing events).
4. **Draft Slice A plan** — should include:
   - Exact SSE event additions (new event type? extend existing?)
   - Source-tracking data structure (how to track per-session sources, dedupe, index for `[Sn]`)
   - LLM prompt updates — analyst prompt at `AI-excel-addin/api/agent/profiles/prompts/analyst.md` likely needs to teach Hank to use `[Sn]` syntax referencing the structured array
   - `dev/chat_cli.py` updates to render the new event
   - Backward compat — does the existing frontend break if new event arrives? Probably not (unknown events ignored), but verify
5. **Codex-review Slice A plan** before implementation per the standard plan-first workflow
6. **Implement via Codex** with cross-repo `cwd` set to AI-excel-addin

---

## Files to read for context (in order)

1. `docs/planning/BETA_RELEASE_GAP_AUDIT.md:100-115` — T1.1 spec
2. `docs/planning/V2_P2_CITATION_FIRST_QA_PLAN.md` — this doc
3. `AI-excel-addin/api/agent/interactive/runtime.py` — gateway runtime (cross-repo)
4. `AI-excel-addin/api/agent/profiles/prompts/analyst.md` — current analyst prompt
5. `AI-excel-addin/api/dev/chat_cli.py` — current dev CLI rendering for Slice C
6. `core/corpus/types.py::SearchHit` — already-citation-ready data shape
7. `frontend/packages/connectors/src/features/external/hooks/useResearchChat.ts` — frontend stream consumer (for Slice D)

---

## Open questions for the next session

1. **SSE event shape** — new `sources_update` event vs include sources in `stream_complete`? Streaming vs final-only?
2. **Source dedup** — same `document_id` cited multiple times — single `S1` entry or sequential `S1`, `S2`?
3. **Section vs document grain** — does `[S1]` reference a (document_id, char_range) or just document_id? Section-grain is more useful for click-through but costs schema complexity.
4. **Validation gate strictness** (Slice B) — block on ANY unsourced claim, or only quantitative claims (numbers, dates, percentages)? Hard-mode is "every assertion needs a source"; pragmatic mode is "every number needs a source."
5. **Cross-repo coordination** — should Slice A live in AI-excel-addin only, or split between risk_module (corpus tool envelope extension) + AI-excel-addin (gateway plumbing)? Lean Slice A in AI-excel-addin only since the corpus tools already return all the data needed.

---

## Why we stopped here today

V2.P1 corpus is shipped and producing real value. The next obvious move was V2.P2 to make it user-visible. But:

1. V2.P2 lives mostly in AI-excel-addin (cross-repo, unfamiliar)
2. Slice A alone is 3-5 days of careful work, not a single-session implementation
3. The current session is already very long (18+ corpus commits today)
4. Diving in cold without proper plan-first scoping would be cowboy coding (forbidden per CLAUDE.md)

The right move: capture the discovery + scoping in this doc, pick it up fresh tomorrow with proper plan-first discipline.
