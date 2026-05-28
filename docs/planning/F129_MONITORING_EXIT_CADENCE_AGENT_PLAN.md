# F129 — Monitoring / Exit Reassessment Cadence Agent

**Status:** PLAN DRAFT — CODEX ROUND 1 FIXES APPLIED; RE-REVIEW PENDING
**Unblocks:** the autonomous monitoring/exit leg of the agent-driven loop (research → thesis → model → position → **monitor/exit**). Closes matrix gaps L1 + L4.

> **Codex round 1 (2026-05-26) — blocking fixes folded in:** (1) `thesis_read`/`thesis_list` are on **research-corpus-mcp**, not portfolio-mcp → skill declares both servers (§4.D); and `thesis_read` currently filters out `model_insights`/`price_target` → PR0 extends its readable-section allowlist (§5). (2) `--context` ticker extraction is unreliable with a `MODE=…` prefix → ticker-first context + explicit `KEY=VALUE` parsing (§2, §4.D, PR0). (3) `notify_send` requires a `confirm_token` (previews otherwise) → headless-safe operational send path (§4.F). (4) `decisions_log` dedupes by `entry_id` only → deterministic `entry_id` derived from `run_id` (§3 #15). (5) Tier-2 reported-metric source resolved: **v1 auto-evaluates Tier-1 only; Tier-2/3 surface as manual-review** (§0 D-I, §2, §7). (6) Cadence selector defined: `thesis_list ∩ get_positions`, per `research_file_id` (§4.G). (7) `last_checked` R1-exemption requires F125 **mutation-aware** validation (§3 #14). (8) `check_exit_signals` returns error for unconfigured tickers → mapped to non-fatal not-applicable (§4.C). Factual corrections: alerts server is **`alerts`/`notify_send`**.
**Hard dependencies (must ship first):** see the reconciliation note below — the F125 + F134 framing predates the F2j tool-policy refactor and is now partly superseded.
**Verification:** _(populate after implementation — focused tests + a live cadence dry-run against a real Thesis)_

> **⚠️ Dependency reconciliation (2026-05-26, post-F2j) — supersedes the original F125+F134 framing.**
> The F2j tool-policy refactor (master arch: `AI-excel-addin/docs/design/agent-tool-policy-architecture.md`, Round 8 PASS; PR1+PR2 **shipped** in `66c8395a`) reshaped the autonomous-write model and partly subsumes F134:
> - **6-class taxonomy** (`read`/`pure_transform`/`artifact_write`/`state_write`/`external_write`/`irreversible`) replaces F134's 4 blast-radius classes. `irreversible` is **forbidden in any autonomous profile** (config-load assertion) — this is F134's "portfolio_affecting always blocked," already shipped and stronger.
> - **Autonomous gating is STATIC profile-class exclusion at startup, NOT a runtime gate** (arch §4.1 — no mid-stream approval, ever). So F134's "autonomous gate interceptor" and "thesis_only allowed after F125 gates" framing **do not describe how the runtime actually works**. There is no runtime gate to depend on.
> - **The analyst/advisor autonomous profiles allow classes `{read, pure_transform, artifact_write}`** (arch §3.2) plus a narrow `allowed_extra_tools = {record_workflow_action, update_action_status}` escape hatch (`analyst.py:207`, `advisor.py:145`) — but NOT F129's tools. F129's writes are `state_write` (`apply_patch_ops`/`thesis_append_decisions_log`; `update_watch_item` will be classified `state_write` in PR2) and `external_write` (`notify_send`, `server_policies.py:217`) — **all excluded from autonomous today.** F2j deliberately only unblocked `artifact_write` (model-build skills); there is **no path for an autonomous skill to perform `state_write`/`external_write`**, and **no per-skill class-grant exists** (skill frontmatter has no class field; none of F2j PR1–PR4 add one).
> - F134's **build-follow-through hook** is **orphaned** (not in F2j) — and F129 doesn't need it (decision D-G keeps F129 off model-bound writes, so it never does `build_affecting`).
>
> **F129's ACTUAL prerequisites (revised):**
> 1. **F125** mutation-aware audit validation — unchanged, still required for F129's `state_write` thesis writes to pass the audit gate (§3 #14).
> 2. **A scoped autonomous grant for F129 — via the SHARED `research_producer` profile** (updated 2026-05-27; supersedes the earlier bespoke `monitor` profile). The autonomous-`state_write` need is shared by F128 (idea→thesis; live smoke 2026-05-27 hit the exact same gate, blocked on `start_research` ingress + thesis writes), F129, and F131 (e2e). The F131 enablement plan (`AI-excel-addin/docs/design/f131-research-producer-enablement-plan.md`, DRAFT R3) converges all three onto ONE autonomous producer role: revive the PR5 **`portfolio_config` class split** (move capital writes — `set_target_allocation`/`set_risk_profile`/brokerage routing/portfolio+basket mutation — out of `state_write` into an autonomous-forbidden class), then define **`api/agent/profiles/research_producer.py`** = `allowed_classes={read, pure_transform, artifact_write, state_write}` + `allowed_extra_tools={notify_send}` (F129 alert; the one `external_write` tool a producer needs) + server-set discipline (omit finance-cli/drive/gsheets/roam/gmail/social). F129's cadence driver dispatches `--profile research_producer`. **F129's earlier `monitor` profile (plan-only — commit `2394e414` was a plan edit, no `monitor.py` was built) is retired; nothing to delete.** Trade-off accepted: F129's grant broadens from 4 tools to the full `state_write` class — but capital (`portfolio_config`), trades (`irreversible`), and comms/Drive (`external_write` class + server-omission) all stay barred; the residual is reversible, versioned, same-user thesis writes that F126 already sanctions. F129's `update_watch_item` (PR2-classified `state_write`) is covered by the class grant; `notify_send` by the escape hatch. **Caveat retained:** F2j classifies `apply_patch_ops` as a single class (not input-aware) → the grant admits model-bound ops too; F129 only emits monitoring ops (D-G), so acceptable.
> 3. F134 as originally planned is **NOT** a prerequisite — its classification half shipped via F2j; its gate half doesn't match the runtime; its surviving "scoped autonomous grant" intent is now delivered by the shared `research_producer` profile (F131 enablement, item 2), not a bespoke F129 profile.
>
> **Sequencing now:** F2j PR1+PR2 (done) → F125 mutation-aware validation **+ F131-enablement Part 1 (`portfolio_config` split) + Part 2 (`research_producer` profile)** → F129 PR0 / PR1 / PR2 (PR2 creates+classifies `update_watch_item` as `state_write`) → PR-A (consume `research_producer`) → PR3+. This replaces the old "F125 → F134 → F129" chain. (Full PR ordering + dependencies in §5.)

## Linked docs
- [`RESEARCH_ARTIFACT_LAYERS.md`](RESEARCH_ARTIFACT_LAYERS.md) — D6 (`PositionSnapshot`), D8, D10, R5/R6/R8/R12, Success Criteria 1/3/4/6/8/9
- [`F125_EVIDENCE_LAYER_AUDIT_BACKBONE_PLAN.md`](F125_EVIDENCE_LAYER_AUDIT_BACKBONE_PLAN.md) — the write contract (§6.2 validation, §8 zero-patch decisions_log)
- [`F134_AUTONOMOUS_WRITE_ENFORCEMENT_PLAN.md`](F134_AUTONOMOUS_WRITE_ENFORCEMENT_PLAN.md) + [`F126_AUTONOMOUS_WRITE_GATING_POLICY.md`](F126_AUTONOMOUS_WRITE_GATING_POLICY.md) — write classification (`thesis_only` / `operational` / `portfolio_affecting`)
- [`THESIS_WRITE_SURFACE_COVERAGE.md`](THESIS_WRITE_SURFACE_COVERAGE.md) — L1 (monitoring/exit driving skill), L4 (reassessment cadence)
- [`F124_THESIS_WATCHLIST_OWNERSHIP_WIRING_PLAN.md`](F124_THESIS_WATCHLIST_OWNERSHIP_WIRING_PLAN.md) — the typed `WatchItem` / `Monitoring` / `update_monitoring` substrate F129 consumes

---

## 0. Decisions locked (with user, 2026-05-26)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| **D-A** | Breach write model | **Runtime-first + decisions_log** | Breaches computed live into an **ephemeral** `PositionSnapshot`. F129 does NOT write a sourced "breached" claim to Thesis on cadence. It only (a) stamps `last_checked` (neutral metadata, R1-exempt), (b) writes a `decisions_log` verdict every run (incl. no-op), (c) alerts. A breach that warrants a thesis change escalates to a human / producer skill. |
| **D-B** | Skill structure | **New standalone scheduled skill** | New `position-reassess` producer skill (`scope: ticker`), modeled on `monitoring-init` / `ownership-refresh`. Not folded into `morning-briefing` (class + scope mismatch). |
| **D-C** | v1 scope | **Broader v1** | In scope: (1) dedicated `notify_send` breach alerts → requires editing **both** cron MCP templates + an `operational` registry entry in F134; (2) Layer-3 snapshot-diff reassessment ("what changed since finalize"); (3) a granular `update_watch_item` patch op. |

Smaller decisions committed in this plan (not deferred):

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D-D | `PositionSnapshot` persistence | **Ephemeral, never stored** | D6 frames it as a read shape. Assembled live per run from Thesis + `get_quote`/`get_positions`; never written to Thesis or Handoff (R8 immutability). |
| D-E | Breach-evaluation arithmetic | **Deterministic, not LLM mental-math** | Threshold coercion + numeric comparison runs through a deterministic step (new read-only tool `evaluate_thesis_monitoring`, §4.C), mirroring the `ownership-refresh` "compute via run_bash, never mental math" discipline. |
| D-F | `InvalidationTrigger` source gap (F152) | **Do not gate on F152** | Triggers lack `source_refs` only for *claim-writing*; F129's runtime-first model (D-A) doesn't write sourced breach claims, so it can evaluate + alert on triggers today. F152 remains an independent enhancement. |
| D-G | Model-staleness handling | **Advisory only** | If reassessment finds the model stale, F129 *recommends* a rebuild in its verdict/alert — it never calls `build_model` (would escalate to `build_affecting`). Keeps every F129 write `thesis_only`. |
| D-H | Multi-user target resolution | **Scoped `research_file_id`** | Never infer target Thesis from ticker-global memory (F134 §3.4). The cadence driver passes an explicit `research_file_id` per run. |
| D-I | Tier-2/3 auto-evaluation in v1 | **Tier-1 only auto-evaluates; Tier-2/3 = manual-review** | v1 has NO wired source for live fundamental-metric observed values (e.g. "Azure CC growth %") — `WatchItem`/`InvalidationTrigger` carry `metric`+`threshold` but no observed-value field, and there's no real-time fundamental feed. So v1 auto-breach-detects ONLY Tier-1 (price_target ranges + `check_exit_signals`). Tier-2 (fundamental) + Tier-3 (qualitative prose) items are **surfaced for manual review** with their linked catalyst's `expected_date` for context — never auto-evaluated, never false-NO_BREACH. Live fundamental evaluation (edgar/fmp on earnings events) is an explicit F129 fast-follow, not v1. |
| D-J | `decisions_log` idempotency | **Deterministic `entry_id` from `run_id`** | The append helper (`thesis_log_helpers.py`) dedupes by `entry_id` only, not `run_id`. F129 sets `entry_id = stable_hash(run_id + skill + research_file_id)` so a replayed cadence run dedupes cleanly through the existing path. |

---

## 1. Scope

### 1.1 In scope (v1)

0. **Prerequisite fixes (PR0)** — small but REQUIRED before the cadence loop works: (a) extend `thesis_read`'s readable-section allowlist (`actions/thesis.py`) to return `model_insights` + `price_target` (they exist in schema but are filtered out today — Success Criterion 6 is unmeetable otherwise); (b) make `extract_ticker_from_context` (`loader.py`) parse explicit `TICKER=` / `RESEARCH_FILE_ID=` key-value tokens so the `MODE=…` prefix doesn't get mis-read as the ticker; (c) map `check_exit_signals` "no exit rules configured for {ticker}" to a non-fatal not-applicable result instead of a hard error.
1. **New schema: `PositionSnapshot` + `PositionRuntimeState` + `InvalidationBreach`** (AI-excel-addin `schema/`). Minimal contract per D6.
2. **New read-only tool `evaluate_thesis_monitoring`** (portfolio-mcp) — deterministic breach evaluation (threshold coercion, tiered inputs, qualitative-skip). Returns the breach set + the assembled `PositionRuntimeState`.
3. **New granular patch op `update_watch_item`** (AI-excel-addin `schema/handoff_patch.py` + `patch_engine.py`) — single-item update by `watch_item_id`; the `last_checked`-only path is an R1-exempt neutral-metadata update.
4. **New producer skill `position-reassess`** (`api/memory/workspace/notes/skills/position-reassess.md`) — the scheduled cadence driver-of-record.
5. **Snapshot-diff reassessment** — diff current Thesis Layer-2 conclusions vs the latest finalized `HandoffArtifact` (Layer 3); surface "what changed since finalize."
6. **Dedicated breach alerting via `notify_send`** — add the `alerts`/`notify` server to **both** cron templates (`deploy/mcp.local-cron.template.json`, `deploy/mcp.production-cron.template.json`) + an `operational`-allowed entry in F134's classification registry.
7. **Cadence scheduling wrapper** — a scheduled driver that enumerates active theses (`thesis_list`) and fans out `position-reassess` per ticker with a scoped `research_file_id`.
8. **Test matrix** — breach tiering, threshold coercion, qualitative-skip, `update_watch_item` neutral-metadata exemption, zero-patch decisions_log idempotency, snapshot-diff, autonomous-gate classification of `notify_send`, multi-user scoping.

### 1.2 Out of scope (v1)

- **Rich `PositionSnapshot` fields** (cost basis, realized/unrealized PnL, tax-lot, hedge linkage, sector exposure) — that's **F132** (PARKED, post-F129). v1 ships ONLY the minimal contract.
- **Trade execution / portfolio mutation** — F129 never calls `execute_trade` or any `portfolio_affecting` tool (F126 §2.3 / Success Criterion 4). It recommends; a human executes.
- **Model rebuild** — advisory only (D-G).
- **Any Tier-2 fundamental-metric auto-evaluation** — v1 does NOT consume reported metric values for breach/no-breach decisions and does NOT build fundamental data feeds. Tier-2 (and Tier-3) items are routed to `manual_review[]` only (D-I). Live fundamental evaluation is an explicit fast-follow.
- **`InvalidationTrigger.source_refs` schema** — F152, independent.

### 1.3 Non-goals
- Re-typing `WatchItem` / `Monitoring` (F124 owns the substrate).
- Re-deriving `model_insights` / `price_target` (F133 owns those Thesis fields; F129 reads them).

---

## 2. Architecture & runtime data flow

F129 runs **non-interactively** in the autonomous `--skill` path (`api/agent/autonomous/entry.py:784 run_skill`). The cadence driver invokes it per ticker with **ticker-first** context: `--context "TICKER=<sym> RESEARCH_FILE_ID=<id> MODE=autonomous CALLER=<sched>"`. Ticker-first + the PR0 `extract_ticker_from_context` fix together ensure `run_skill`'s `context_ticker` resolves to the real ticker (not `MODE`), which drives the output filename and skill system prompt. The skill ALSO parses `TICKER=`/`RESEARCH_FILE_ID=` itself (Autonomous Mode contract) and treats `RESEARCH_FILE_ID` as authoritative for Thesis resolution (D-H).

Per-run sequence:

```
1. Parse args (MODE/CALLER/TICKER/RESEARCH_FILE_ID). Resolve Thesis by RESEARCH_FILE_ID (scoped; never ticker-global).
2. thesis_read → monitoring.watch_list, invalidation_triggers, model_insights[], price_target,
   position_metadata. (model_insights/price_target require the PR0 readable-section fix.)
2b. [snapshot-diff only] retrieve the latest finalized HandoffArtifact via the SEPARATE handoff surface
    (get_handoff_full / list handoffs → select latest finalized → fetch artifact). thesis_read does NOT
    return handoffs. If snapshot-diff defers to PR5b, this step is skipped entirely.
3. evaluate_thesis_monitoring(research_file_id) [NEW TOOL, deterministic]:
     - fetch live price (get_quote) + position (get_positions format=monitor)
     - TIER 1 (live, AUTO-EVALUATED in v1): price_target ranges vs live price; check_exit_signals(ticker)
       momentum/regime. If check_exit_signals returns "no rules configured" → not-applicable, NOT an error.
     - TIER 2 (reported fundamental, MANUAL-REVIEW in v1): fundamental-metric thresholds (e.g. Azure CC <28%)
       have no wired live observed-value source → surface for manual review with the linked catalyst's
       expected_date. NOT auto-evaluated in v1 (D-I); never emits a NO_BREACH. (Live fundamental eval = fast-follow.)
     - TIER 3 (qualitative prose): non-numeric / unparseable thresholds → manual-review, never auto-evaluated
     - coerce ThresholdValue (32 / 32.0 / "32.0") deterministically for Tier-1; route prose/unparseable to manual-review
     - assemble PositionRuntimeState{current_price, position_size, holding_period_days, recent_invalidation_breaches[]}
       (recent_invalidation_breaches = Tier-1 confirmed breaches only; Tier-2/3 go in manual_review[], not breaches[])
4. Compose ephemeral PositionSnapshot{handoff_artifact, runtime}.  (never persisted — D-D)
5. Snapshot-diff reassessment: diff Thesis Layer-2 conclusions vs HandoffArtifact (Layer 3).
6. Writes (all thesis_only, F125-compliant):
     a. update_watch_item per evaluated item → stamp last_checked  (NEUTRAL METADATA, R1-exempt)
     b. decisions_log verdict (EVERY run, idempotent by run_id):
          NO_BREACH | BREACH_DETECTED | MANUAL_REVIEW_PENDING | INSUFFICIENT_DATA | MODEL_STALE_ADVISORY
          (NO_BREACH/BREACH_DETECTED reflect Tier-1 only; MANUAL_REVIEW_PENDING = Tier-1 clean but Tier-2/3
           items exist for human follow-up. Tier-2/3 are never auto-evaluated, so they never drive NO_BREACH.)
     c. NO sourced "breached" claim written (D-A runtime-first)
7. Alert (on BREACH_DETECTED or MODEL_STALE_ADVISORY): notify_send(breach summary)  [operational]
     + always surface the breach in the final response (send_telegram_summary redundancy).
8. Persist deliverable markdown + memory_store(monitoring_run).
```

**Tiering is the load-bearing insight:** in v1, only Tier-1 (price / exit-signal) items breach-evaluate each cadence run. Tier-2 (fundamental-metric) and Tier-3 (qualitative prose) items are **never auto-evaluated and never consume reported values** — they always route to `manual_review[]`, annotated with the linked catalyst's `expected_date` for human follow-up. This is the explicit guard against false NO_BREACH on metrics F129 cannot observe live. (Live Tier-2 evaluation is a post-v1 fast-follow; until then there is no Tier-2 breach path at all.)

---

## 3. Hard constraints from dependencies

(Extracted from F125 / F134 / F126 / RESEARCH_ARTIFACT_LAYERS.md — F129 must satisfy all.)

1. **Minimal `PositionSnapshot`** = `{handoff_artifact: HandoffArtifact, runtime: PositionRuntimeState}`, `PositionRuntimeState = {current_price, position_size, holding_period_days, recent_invalidation_breaches[]}`. No richer fields (F132). [D6, R8]
2. **Read-only via Thesis + PositionSnapshot** — no detours to `model_insights`/`price_target` side tables; read off Thesis. [Success Criterion 6, D8]
3. **HandoffArtifact immutable** — runtime state lives only in `PositionSnapshot`; new conclusions go to Layer 2, re-snapshot only via `new_handoff_version`. [R8]
4. **All F129 Thesis writes are F125-era** → strict gate. But under D-A the only writes are (a) `last_checked` stamps (neutral metadata, R1-exempt per F125 §6.2) and (b) `decisions_log` verdicts (not positive claims). **No positive-claim writes → no source/excerpt registration on cadence.** [F125 §6.2]
5. **Materially updating a pre-F125 claim** is avoided by design — F129 never mutates sourced claim content on cadence (D-A). [R9, F125 §6.3]
6. **No same-target claim + data_gap** — if a breach can't be confirmed (missing data), emit `MANUAL_REVIEW_PENDING`/`INSUFFICIENT_DATA` verdict; never a claim. [R6]
7. **Every run leaves a decisions_log trace incl. no-ops**, idempotent by `run_id`. Never `advisor-no-state`. [R5, R12, Success Criterion 3, F125 §8]
8. **`state_class: producer`** (writes Thesis state + decision logs). [R12]
9. **Monitoring writes stay `thesis_only`** — keep off model-bound fields (else escalates to `build_affecting`, highest-blast-radius rule). [F134 §2/§3.1]
10. **`notify_send` must be explicitly `operational`-allowed** in F134's registry, or the autonomous gate fails it closed (`autonomous_write_unclassified`). [F134 §2/§3.2]
11. **Never execute trades / never touch `portfolio_affecting`.** Read-only exit-signal/quote/position tools are pre-gate-allowed. [F126 §2.3, Success Criterion 4]
12. **Multi-user discipline** — resolve target Thesis from scoped `research_file_id`, never ticker-global memory. [F134 §3.4]
13. **Threshold coercion + qualitative-skip** — `ThresholdValue = str|int|float` (`thesis_shared_slice.py:37`), non-normalized; deterministic coercion of all numeric forms + skip unparseable prose. [TODO F129 row, this session's F124/F152 test]
14. **F125 must ship mutation-aware (per-op) audit validation** — the current validator (`evidence_audit.py`) does whole-thesis excerpt validation; a neutral `last_checked`-only update could be blocked by unrelated historical unsourced claims. F129's R1-exemption for `last_checked` REQUIRES F125 to validate only the claims touched by the current patch batch (already implied by F125 §6.3 "claims created/materially updated by the current batch" — F129 depends on that behavior shipping, with a test). [F125 §6.3, evidence_audit.py:67, patch_engine.py:437]
15. **`decisions_log` idempotency** — set deterministic `entry_id` from `run_id` (D-J); the append helper dedupes by `entry_id` only. [thesis_log_helpers.py]
16. **`thesis_read` must return `model_insights` + `price_target`** — currently filtered out by the action-layer readable-section allowlist (`actions/thesis.py`); PR0 adds them, else Success Criterion 6 (read off Thesis) is unmeetable. [actions/thesis.py, schema/thesis.py:424]

---

## 4. Component breakdown

### 4.A Schema: `PositionSnapshot` (AI-excel-addin — greenfield)
- New module `schema/position_snapshot.py` (or fold into `schema/handoff.py` if preferred — Codex call).
- `class PositionRuntimeState(_ContractModel)`: `current_price: float`, `position_size: PositionSize | None`, `holding_period_days: int | None`, `recent_invalidation_breaches: list[InvalidationBreach]`.
- `class InvalidationBreach(_ContractModel)`: `{ source_kind: Literal["watch_item","invalidation_trigger","price_target","exit_signal"], ref_id: str, metric: str|None, threshold: ThresholdValue|None, threshold_direction: Literal["above","below"]|None, observed_value: float|str|None, breached: bool, tier: Literal["live","reported","qualitative"], evaluated_at: str, note: str|None }`.
- `class PositionSnapshot(_ContractModel)`: `{ handoff_artifact: HandoffArtifactV1_1, runtime: PositionRuntimeState }`.
- **Ephemeral** — no patch op writes it, no Thesis field holds it.
- **Acceptance:** round-trips through Pydantic; `recent_invalidation_breaches` accepts all three tiers; rejects rich F132 fields (extra="forbid").

### 4.B Granular patch op: `update_watch_item` (AI-excel-addin — greenfield)
- `schema/handoff_patch.py`: `class UpdateWatchItemOp(_PatchOpBase)` with `op: Literal["update_watch_item"]`, `target: {watch_item_id: str}`, `value: WatchItemWriteValue` (partial: at minimum `last_checked`; optionally `description`/`metric`/`threshold`/`threshold_direction`/`source_refs`).
- `api/research/patch_engine.py`: `_apply_update_watch_item_patch` — locate watch item by `watch_item_id`, apply field updates, preserve untouched fields (esp. `source_refs`), descriptor + within-batch conflict detection (mirror `_apply_monitoring_patch` from F124).
- **R1 rule:** a value touching ONLY `last_checked` (and/or other neutral metadata) is exempt from R1. A value that changes `description`/`metric`/`threshold`/`threshold_direction` is a claim change → R1 applies (must carry resolving `source_refs`). Encode this in the op validator.
- **Acceptance:** `last_checked`-only update on an existing item succeeds with no source registration; claim-field update without `source_refs` is rejected; unknown `watch_item_id` → `InvalidTargetError`; two same-batch updates to one item → `_divergent_update_conflict`.

### 4.C Read-only tool: `evaluate_thesis_monitoring` (portfolio-mcp — greenfield)
- Signature: `evaluate_thesis_monitoring(research_file_id: int, user_email: str|None=None, format="agent") -> dict`.
- Reads Thesis (watch_list, invalidation_triggers, price_target, position_metadata), fetches live price (`get_quote`) + position (`get_positions` format=monitor), calls `check_exit_signals(ticker)`.
- Returns `{ runtime_state: PositionRuntimeState, breaches: list[InvalidationBreach], manual_review: [...] }` — **deterministic** (no LLM arithmetic; this is the D-E enforcement point). `breaches` = Tier-1 confirmed only; `manual_review` = all Tier-2/3 items with their linked catalyst `expected_date`.
- Tiering logic per §2 + D-I. `holding_period_days` derived from `position_metadata.date_initiated` — `None` if unset AND `None`/flagged if the stored value is present-but-unparseable (handle invalid dates, not just missing).
- `check_exit_signals` integration: treat its "no exit rules configured for {ticker}" error as a **not-applicable** signal (the common case — only SLV is configured today), not a fatal error. The tool proceeds with price_target evaluation.
- **Register in server policy** as a read tool (`server_policies.py` known_read_tools) so tool-policy-drift tests pass and the autonomous gate doesn't treat it as unknown.
- **Acceptance:** numeric thresholds in `32`/`32.0`/`"32.0"` forms all coerce + compare identically; prose thresholds land in `manual_review`, never `breaches`; Tier-2 fundamental items land in `manual_review` (v1, D-I), never a false NO_BREACH; unconfigured `check_exit_signals` ticker → not-applicable, not error; invalid `date_initiated` handled; read-only (no Thesis mutation); per-user scoped.

### 4.D Skill: `position-reassess.md` (AI-excel-addin — greenfield)
- Frontmatter: `scope: ticker`, `state_class: producer`, `agent_callable: true`, `resumable: true`, `persist_state: true`, `max_turns: 12`, `max_budget_usd: 2.0`, `mcp_servers: [research-corpus-mcp, portfolio-mcp, alerts]` (aligned 2026-05-27 to the shipped `research_producer` always-on server set). `research-corpus-mcp` hosts `thesis_read`/`thesis_list` (NOT portfolio-mcp); `portfolio-mcp` provides `apply_patch_ops`, `check_exit_signals`, `get_quote`, `get_positions`, `evaluate_thesis_monitoring`; `alerts` provides `notify_send`. **`fmp-mcp` is NOT needed in v1** — Tier-1 price comes from portfolio-mcp `get_quote`; Tier-2 fundamentals are manual-review, not fetched (add fmp-mcp only if live Tier-2 eval ships post-v1). `research-corpus-mcp`/`portfolio-mcp` are in `USER_EMAIL_REQUIRED_MCP_SERVERS`.
- **Autonomous Mode arg parsing:** parse explicit `KEY=VALUE` tokens (`TICKER=`, `RESEARCH_FILE_ID=`, `MODE=`, `CALLER=`) from the `--context` string — do not rely on positional/first-token heuristics. `RESEARCH_FILE_ID` is authoritative for Thesis resolution; if absent in autonomous mode, stop with `INSUFFICIENT_ARGS`.
- Body: When/When-NOT, Response Posture, **Iron Laws** ("NEVER overwrite a watch item's `source_refs` when stamping `last_checked`", "ALERT ONLY ON A CONFIRMED CROSSED THRESHOLD", "NEVER execute trades — recommend only"), **Autonomous Mode** section (verbatim `MODE=autonomous`/`CALLER=`/`TICKER=` contract + add `RESEARCH_FILE_ID=`), phased Workflow with `⛔ GATE`s, the deterministic `evaluate_thesis_monitoring` call, the `update_watch_item` ops block + "Apply via `apply_patch_ops`", decisions_log YAML (`patch_ops_applied: list[dict]`, `verdict` field — per this session's F151/F154 fix), and the `notify_send`-if-breach + final-response-redundancy step.
- **Acceptance:** dispatch-shape regression test (parse the embedded `ops:` YAML against live Pydantic models, à la F145); skill-validation guard passes; autonomous-mode arg parsing covered.

### 4.E Snapshot-diff reassessment (AI-excel-addin — skill-driven, reads existing schema)
- Retrieve the latest finalized `HandoffArtifact` via the **separate handoff surface** (`get_handoff_full` / list handoffs → select latest finalized) — `thesis_read` does NOT return handoffs (Codex round 1). If no finalized handoff exists, snapshot-diff reports "no prior finalize to diff against" and skips (not an error).
- Diff current Thesis Layer-2 conclusions (`thesis.statement`, `valuation`, `differentiated_view[]`, key `assumptions[]`) vs that latest finalized `HandoffArtifact` (Layer 3 frozen snapshot).
- Output: a "changed since finalize" summary → folded into the decisions_log rationale + alert body. No new schema, no Thesis write beyond the verdict.
- **Acceptance:** given a Thesis whose statement/valuation changed vs its last handoff, the diff surfaces the deltas; given no change, reports "no drift since finalize."

### 4.F Alerting: `alerts` MCP + cron template + F134 registry (AI-excel-addin + alerts MCP — config + headless path)
- The server is **`alerts`** exposing **`notify_send`** (not a `notify` server). Add it to `deploy/mcp.local-cron.template.json` AND `deploy/mcp.production-cron.template.json` (absent from both today).
- **`notify_send` requires a `confirm_token`** (Codex round 1) — it returns `confirmation_required` and previews unless the exact token is supplied, so a naive single `notify_send(summary)` will NOT alert. F129 needs a **headless-safe operational send**. Spec: add an autonomous/pre-authorized send path to the `alerts` MCP (e.g. a `confirm_token`-bypass for callers the operational registry has allow-listed, or a two-call preview→confirm the headless skill performs deterministically). This is alerts-MCP work, in F129 scope.
- **Guaranteed fallback:** always also surface the breach in the skill's final response so the post-run `send_telegram_summary` (`delivery.py:87`, already wired in `run_skill`) delivers it even if the dedicated `notify_send` path is unavailable. The dedicated path is the enhancement; the summary is the floor.
- Add `notify_send` (and the headless variant) to F134's classification registry as `operational`-allowed, with a gate test.
- **Sequencing:** couples F129 to F134 — the registry entry lands in F134's enforcement layer. Recommended order F134-before-F129; PR4's gate test is the canary.
- **Acceptance:** an autonomous `position-reassess` run delivers a breach alert end-to-end (dedicated path OR summary fallback); the dedicated `notify_send` call does NOT stall on `confirmation_required` in headless mode; removing the F134 registry entry makes the gate fail closed (negative test).

### 4.G Cadence scheduling wrapper (AI-excel-addin / risk_module — config + thin driver)
- **Selector (Codex round 1):** `thesis_list` supports only `ticker`+`limit` — there is no active-position filter. The driver computes the run set deterministically by **intersecting `thesis_list` (all theses) with `get_positions` (currently-held tickers)** → theses for held positions. For a ticker with **multiple Thesis rows**, dispatch one run **per `research_file_id`** (each is independently scoped, D-H). Define a stable ordering (e.g. by `research_file_id`) for reproducibility.
- Dispatch `position-reassess` per `research_file_id` via `agent_run_start mode='skill'` (or `agent.autonomous --skill`), passing ticker-first context `TICKER=<sym> RESEARCH_FILE_ID=<id> MODE=autonomous CALLER=cadence`.
- Cadence: daily for the Tier-1 price/exit-signal checks. (Tier-2 fundamental items are manual-review in v1 per D-I, so there's no Tier-2 schedule to run yet — when live fundamental eval ships as a fast-follow, add an earnings-event-driven schedule.) Reuse the existing launchd/`run_analyst.sh` mechanism.
- **Acceptance:** driver fans out exactly one run per held-position Thesis row with correct per-`research_file_id` scoping; a ticker with two Thesis rows yields two scoped runs; a held ticker with no monitoring content yields a clean `INSUFFICIENT_DATA` verdict, not an error; an unheld ticker's Thesis is skipped.

---

## 5. Implementation sequence (PR plan)

Prerequisites: **F125** (mutation-aware audit validation, for PR2) + the **`research_producer` profile** (owned by the F131 enablement plan — `portfolio_config` split + `research_producer` definition; F129 PR-A just consumes it). F134-as-planned is NOT a prerequisite (see reconciliation banner). Within F129:

| PR | Scope | Repo | Depends |
|---|---|---|---|
| **PR0** | Prereq fixes: `thesis_read` returns `model_insights`+`price_target` (`actions/thesis.py`); `extract_ticker_from_context` parses `TICKER=`/`RESEARCH_FILE_ID=` KV tokens (`loader.py`); `check_exit_signals` unconfigured-ticker → non-fatal not-applicable (`signals.py`) | risk_module + AI-excel-addin | — |
| PR1 | `PositionSnapshot`/`PositionRuntimeState`/`InvalidationBreach` schema + tests | AI-excel-addin | — |
| PR2 | `update_watch_item` patch op + engine apply/conflict + `last_checked` R1-exemption (requires F125 mutation-aware validation) **+ classify `update_watch_item` as `state_write` in F2j `server_policies.py`** (else it's an unknown write — fails the gate AND any profile that lists it) + tests | AI-excel-addin | F125 shipped (mutation-aware validation) |
| **PR-A** | **Consume the shared `research_producer` profile** (defined by the F131 enablement plan — NOT built here). F129's work: (1) re-point the cadence driver to `--profile research_producer`; (2) confirm `update_watch_item` is classified `state_write` (PR2) so the class grant covers it; (3) confirm `research_producer`'s server-set covers F129's servers (research-corpus-mcp / portfolio-mcp / alerts — already shipped; fmp-mcp not needed v1) **AND add F129's new tools `update_watch_item` + `evaluate_thesis_monitoring` to `RESEARCH_PRODUCER_CORE_MCP_TOOLS["portfolio-mcp"]`** (cross-repo, AI-excel-addin — the class grant covers permission but that curated per-server core manifest doesn't list them yet; F161 4a); (4) a no-regression test that `research_producer` materializes F129's tools (`apply_patch_ops`, `thesis_append_decisions_log`, `update_watch_item`, `notify_send`, `evaluate_thesis_monitoring`, reads) and excludes capital/trade/comms. The bespoke `monitor` profile is retired (was plan-only; nothing to delete). | AI-excel-addin (F2j profile layer, F131-enablement-owned) | F131 enablement Part 1+2 (`portfolio_config` split + `research_producer`); PR2 (`update_watch_item` classified `state_write`) |
| PR3 | `evaluate_thesis_monitoring` tool (deterministic Tier-1 breach engine, coercion, manual-review routing) + server-policy read-tool entry (F2j 6-class: read) + tests | portfolio-mcp (risk_module) | PR0, PR1 |
| PR4 | `alerts` server in both cron templates + headless-safe `notify_send` path (alerts MCP) + gate tests (`notify_send` is already classified `external_write`, `server_policies.py:217`; granted to `research_producer` via its `allowed_extra_tools={notify_send}`) | AI-excel-addin + alerts MCP | **PR-A** (`research_producer` grants `notify_send`) |
| PR5 | `position-reassess.md` skill (incl. snapshot-diff; deterministic `entry_id`; KV arg parse) + dispatch-shape test | AI-excel-addin | PR1–PR4 |
| PR6 | Cadence scheduling wrapper (`thesis_list ∩ get_positions`, per-`research_file_id` fan-out, dispatch `--profile research_producer`) + live dry-run | AI-excel-addin / risk_module | PR5 |

**Note:** snapshot-diff (§4.E) rides PR5 but can split to a PR5b fast-follow if it threatens to delay the core last_checked/verdict/alert cadence — the L1/L4 gap closes on the cadence loop, not the diff.

Each PR: plan-conformance check → Codex review → implement via Codex.

---

## 6. Test matrix
- PR0: `thesis_read` returns `model_insights`+`price_target`; `extract_ticker_from_context("TICKER=MSFT MODE=autonomous …")` → `MSFT` (not `MODE`); `check_exit_signals("AAPL")` (unconfigured) → not-applicable, not error.
- ThresholdValue coercion: `32`, `32.0`, `"32.0"` → identical comparison; `"below 8%"` / `"investment-grade"` → `manual_review`.
- Tier routing (D-I): price_target/exit-signal → auto-evaluated `live` breaches; fundamental metric → `manual_review` (NOT auto-evaluated, NOT NO_BREACH) with catalyst `expected_date`; prose → `manual_review`.
- `update_watch_item`: `last_checked`-only = R1-exempt success **even when the thesis has unrelated historical unsourced claims** (proves F125 mutation-aware validation); claim-field change without `source_refs` rejected; unknown id → `InvalidTargetError`; same-batch dup → conflict; untouched `source_refs` preserved.
- decisions_log: NO_BREACH run still logs a verdict; replay with same `run_id` → deterministic `entry_id` dedupes (no dup entry).
- Snapshot-diff: detects statement/valuation drift vs last finalized HandoffArtifact; reports clean when none.
- Autonomous gate: `notify_send` allowed with registry entry; fails closed without it; headless `notify_send` does not stall on `confirmation_required`; `execute_trade` always blocked; monitoring batch stays `thesis_only` (negative: a model-bound field escalates to `build_affecting`).
- Multi-user / cadence selector: target Thesis resolved from `research_file_id`, never ticker-global memory; `thesis_list ∩ get_positions` yields one run per held Thesis row; two Thesis rows for one held ticker → two scoped runs; unheld ticker skipped.
- PositionSnapshot: minimal contract round-trips; rich F132 fields rejected; `holding_period_days` None on unset AND on invalid `date_initiated`.

## 7. Risk register
| Risk | Mitigation |
|---|---|
| False NO_BREACH on un-observable fundamental metrics | Tiering + D-I (§2) — Tier-2/3 always route to `manual_review[]`, never auto-evaluated, so they can never produce a NO_BREACH. v1 has no Tier-2 breach path. |
| `notify_send` not in cron surface → silent alert loss | PR4 adds it to both templates + declares in skill `mcp_servers` (hard-gate via `_require_skill_declared_mcp_servers`); + final-response redundancy via `send_telegram_summary`. |
| Full-replace clobber of watch_list on `last_checked` stamp | Granular `update_watch_item` (PR2) avoids full-replace; preserves `source_refs`. |
| Autonomous gate fails F129's writes | All writes are `thesis_only` (D-G keeps model-bound fields out); `notify_send` registered `operational` (PR4). |
| F134 not shipped when F129 lands | Hard dependency; PR4 gate test is the canary. Do not ship F129 cadence runs until F134 enforcement is merged. |
| LLM arithmetic errors on thresholds | D-E — comparison is deterministic in `evaluate_thesis_monitoring`, not LLM mental-math. |

## 8. Open decisions for Codex / impl-plan level (narrow)
1. `PositionSnapshot` module location (`schema/position_snapshot.py` vs fold into `schema/handoff.py`).
2. `evaluate_thesis_monitoring` home server — portfolio-mcp (proposed). Confirm the portfolio-mcp process can read the Thesis server-side (via the research repository/gateway) AND fetch live quotes in one process; if not, the tool may need to live where both reaches exist, or compose two calls.
3. Headless `notify_send` mechanism — `confirm_token`-bypass for operational-allowed callers vs a deterministic two-call preview→confirm in the skill. (alerts-MCP impl detail; either satisfies the acceptance test.)
4. Snapshot-diff granularity — which Layer-2 fields are in the v1 diff set (statement, valuation, differentiated_view, assumptions proposed).

_Resolved since round 1:_ Tier-2 reported-metric source → **manual-review in v1, live eval is fast-follow** (D-I). Cadence → **Tier-1 daily only** in v1 (no Tier-2 schedule until live fundamental eval ships).
