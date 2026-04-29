# V4b.1.0 — Edgar_updater SnapTrade Webhook Ingress (R1.2)

## §0 R1 → R1.1 → R1.2 — Codex review fixes

R1 → R1.1 fixed 5 blockers + 3 stale-text findings; R1.1 review surfaced 5 residual contradictions (Phase 3 trace_id wording, Phase 6 still-framed-as-tail, dashboard "shared secret" wording, V4b.1 §8 stale dashboard-secret line, V4b.1.0 still referencing V4b.1 R4.1.1). R1.2 cleans those up + updates plan version label + drops stale "MUST be revised" pointer.

R1 fixes (preserved):

- **[1] V4b.1 plan needs forward-secret addendum** — V4b.1.0 introduces a `X-SnapTrade-Forward-Secret` header that V4b.1's risk_module-side handler must check. V4b.1's R4.1.1 plan currently has no such requirement. R1.1 §10 hand-off section now flags this as a REQUIRED V4b.1 plan revision (R5) BEFORE V4b.1 R3 impl. Cleanest path: when V4b.1.0 ships, simultaneously bump V4b.1 to R5 with the verification addendum, re-Codex-review V4b.1 R5, then proceed.
- **[2] Dedup identity is `webhookId` not Plaid-style `request_id`** — verified in `risk_module/routes/snaptrade.py:232` (`WebhookRequest.webhookId: Optional[str] = None`). R1.1 §3 column rename: outbox column `webhook_id` (was `request_id` in mirror), parsed from payload at ingress. `trace_id` stays generated (or copied from `webhookId` if present, with fallback to `secrets.token_hex(8)`). NOT derived from `Signature`.
- **[3] Per-symbol map adds two missing helpers** — `_get_plaid_outbox_summary` (`webhook_routes.py:492`) and `_requeue_stuck_processing_events` (`:521`) ARE production helpers used by Edgar_updater admin routes (`admin_routes.py:49, 109`). R1.1 §3 adds `_get_snaptrade_outbox_summary` + `_requeue_stuck_snaptrade_processing_events` to the in-scope mirror list. Phase 6 promotes the dashboard surface from "tail/optional" to in-scope.
- **[4] Unset forward URL test expectation corrected** — Plaid pattern (verified at `webhook_routes.py:407-410`) RAISES `forward_target_not_configured` → schedules retry with backoff (`:366`) → dead-letters after `max_attempts`. Test #6 in §5 Phase 5 corrected: assert scheduled retry + eventual dead-letter, NOT "indefinite pending."
- **[5] Dashboard secret language corrected** — SnapTrade webhook secrets in dashboard are deprecated. The HMAC `Signature` uses the CLIENT SECRET (the consumer-key shared secret already shared between SnapTrade and our app). risk_module's `SNAPTRADE_WEBHOOK_SECRET` env var must equal the SnapTrade consumer-key secret. R1.1 §3.1 / §4 / §10 updated.

Stale text fixes:
- §2 typo: "/plaid/webhook receives SnapTrade events" → "receives Plaid events"
- §4.4 moved out of §5 to §4 (decisions section); reframed as DECIDED, not OPEN
- §7.3 "if worker dies, next ingress restarts it" — false (boolean guard `_plaid_outbox_worker_started` is once-set; if loop dies the boolean stays True). Corrected to acknowledge this gap as inherited from Plaid pattern + tracked as V4b.1.0-tail.

---



## §1 Problem

V4b.1 (R4.1.1, Codex PASS) plans webhook-driven SnapTrade orders sync in `risk_module`. R2 dashboard verification (2026-04-28) revealed: **no webhook listener configured at SnapTrade** — and no SnapTrade webhook handler exists at the Edgar_updater edge (which fronts `https://www.financialmodelupdater.com` and is the public webhook ingress for our system; Plaid webhooks are wired there at `webhook_routes.py:589` `/plaid/webhook`).

V4b.1 is BLOCKED on V4b.1.0 — adding the SnapTrade equivalent at Edgar_updater so SnapTrade events have a place to land in production.

V4b.1.0 mirrors the existing Plaid outbox pattern in Edgar_updater. Single-repo PR. Pure ingress + forwarding plumbing; no business logic.

## §2 Plaid Pattern (traced — what we mirror)

File: `~/Documents/Jupyter/Edgar_updater/webhook_routes.py` (839 lines, sections 19-621 are Plaid-specific).

### Architecture
1. **Public ingress** — `POST /plaid/webhook` (`webhook_routes.py:589`) receives Plaid events. Computes `trace_id`, logs the event for audit, checks anti-loop marker header, enqueues to local SQLite outbox, ensures the worker is running, returns 200. (V4b.1.0 mirrors this for SnapTrade at a parallel `/snaptrade/webhook` route.)
2. **SQLite outbox** — `plaid_webhook_outbox` table (`:185-217`). Schema: `id, created_at, trace_id, request_id, raw_body, headers_json, webhook_type, webhook_code, item_id, status, attempt_count, next_attempt_at, last_error`. Indexed on `request_id` (dedup) + `(status, next_attempt_at, id)` (claim-next ordering).
3. **Background worker** — `_plaid_outbox_worker_loop` (`:461`) polls every 1s (configurable), claims next event with row-level lock semantics, forwards to `PLAID_WEBHOOK_FORWARD_URL` env var via `requests.post`, retries with exponential backoff on failure (default max 25 attempts, 300s max backoff).
4. **Forward headers** — allowlist (`Plaid-Verification`, `Plaid-Request-Id`, `User-Agent`) + anti-loop marker (`X-Plaid-Forwarded: 1`) + shared secret (`X-Plaid-Forward-Secret` from env). Implementation at `_build_plaid_forward_headers` (`:89`).
5. **Configuration** — `flask_config.py:26,34-58` for defaults; env vars override at runtime.

### Key features to preserve
- **Reliable delivery**: outbox + worker handles risk_module backend being temporarily down without losing events
- **Idempotent retry**: backoff with attempt cap; events that exhaust retries become dead-letter (visible via `_get_plaid_outbox_summary`)
- **Anti-loop marker**: prevents the case where risk_module forwards back through Edgar_updater
- **Header allowlist**: don't leak sensitive vendor headers
- **Per-event trace_id**: debuggability across the chain

## §3 What V4b.1.0 Mirrors (per-symbol map)

| Plaid (existing) | SnapTrade (new) |
|---|---|
| `flask_config.PLAID_OUTBOX_DEFAULT_DB_PATH` | `flask_config.SNAPTRADE_OUTBOX_DEFAULT_DB_PATH` |
| `flask_config.PLAID_FORWARD_HEADER_ALLOWLIST` | `flask_config.SNAPTRADE_FORWARD_HEADER_ALLOWLIST` (= `("Signature", "User-Agent")` — see §3.1) |
| `flask_config.PLAID_FORWARD_MARKER_HEADER` / `_VALUE` | `flask_config.SNAPTRADE_FORWARD_MARKER_HEADER` / `_VALUE` |
| `flask_config.PLAID_FORWARD_SECRET_HEADER` | `flask_config.SNAPTRADE_FORWARD_SECRET_HEADER` |
| `flask_config.PLAID_OUTBOX_DEFAULT_*` (poll/batch/attempts/backoff) | `flask_config.SNAPTRADE_OUTBOX_DEFAULT_*` |
| `flask_config.PLAID_KNOWN_WEBHOOK_CODES` | `flask_config.SNAPTRADE_KNOWN_WEBHOOK_TYPES` (= the 14 events from `docs.snaptrade.com/docs/webhooks`; see §3.2) |
| `_build_plaid_forward_headers` | `_build_snaptrade_forward_headers` |
| `_get_plaid_outbox_db_path` and `_get_plaid_outbox_*` getters | mirror per-name |
| `_open_plaid_outbox_connection` / `_init_plaid_outbox_schema` | mirror — table `snaptrade_webhook_outbox`. Column rename per Codex R1 finding [2]: `request_id` → `webhook_id` (= SnapTrade payload field `webhookId`, see `risk_module/routes/snaptrade.py:232`); `webhook_code` → `event_type` (SnapTrade has flat event types). Other columns identical. |
| `_enqueue_plaid_webhook_outbox_event` / `_claim_next_plaid_outbox_event` / `_mark_plaid_outbox_delivered` / `_schedule_plaid_outbox_retry` | mirror per-name |
| `_forward_plaid_webhook_once` | `_forward_snaptrade_webhook_once` (env var `SNAPTRADE_WEBHOOK_FORWARD_URL`) |
| `_process_plaid_outbox_batch` / `_plaid_outbox_worker_loop` / `_ensure_plaid_outbox_worker_running` | mirror per-name |
| `_log_plaid_webhook_event` | `_log_snaptrade_webhook_event` |
| `_get_plaid_outbox_summary` (`webhook_routes.py:492`) | `_get_snaptrade_outbox_summary` (NEW per Codex R1 finding [3]) — used by admin status endpoint |
| `_requeue_stuck_processing_events` (`webhook_routes.py:521`) | `_requeue_stuck_snaptrade_processing_events` (NEW per Codex R1 finding [3]) — used by admin replay endpoint |
| `@webhook_bp.route("/plaid/webhook", methods=["POST"])` `def plaid_webhook_ingress()` | `@webhook_bp.route("/snaptrade/webhook", methods=["POST"])` `def snaptrade_webhook_ingress()` |

### §3.1 SnapTrade signature header + secret semantics (corrected per Codex R1 finding [5])

Verified from `risk_module/routes/snaptrade.py:514`: `expected_sig = request.headers.get("Signature", "")`. SnapTrade sends the HMAC-SHA256 signature in a header called `Signature` (not `X-SnapTrade-Signature`). Allowlist must include `Signature` so the forwarded request still verifies at risk_module. Edgar_updater does NOT verify the signature — same pattern as Plaid (Edgar_updater is the dumb edge; risk_module is the verifier).

**Secret semantics (corrected R1.1):** SnapTrade's `Signature` HMAC is computed using the SnapTrade **client secret** (consumer-key shared secret) — NOT a separate dashboard-configured webhook secret. Per current SnapTrade docs (verified 2026-04-28), webhook secrets in the dashboard are deprecated. risk_module's env var `SNAPTRADE_WEBHOOK_SECRET` (`routes/snaptrade.py:510`) MUST equal the SnapTrade client secret in use. Open: confirm whether `SNAPTRADE_WEBHOOK_SECRET` and `SNAPTRADE_CONSUMER_KEY` (or whatever the client-secret env var is named) are the same value in our `.env` — V4b.1's R5 plan revision should verify and possibly rename for clarity.

### §3.2 SnapTrade event types (for `SNAPTRADE_KNOWN_WEBHOOK_TYPES`)

Per `docs.snaptrade.com/docs/webhooks` (verified 2026-04-27 during V4b.1 R4 investigation):
```python
SNAPTRADE_KNOWN_WEBHOOK_TYPES = frozenset({
    "USER_REGISTERED",
    "USER_DELETED",
    "CONNECTION_ATTEMPTED",
    "CONNECTION_ADDED",
    "CONNECTION_DELETED",
    "CONNECTION_BROKEN",
    "CONNECTION_FIXED",
    "CONNECTION_UPDATED",
    "CONNECTION_FAILED",
    "NEW_ACCOUNT_AVAILABLE",
    "ACCOUNT_TRANSACTIONS_INITIAL_UPDATE",
    "ACCOUNT_TRANSACTIONS_UPDATED",
    "ACCOUNT_REMOVED",
    "ACCOUNT_HOLDINGS_UPDATED",
})
```

Used only for log-classification (Edgar_updater logs unknown types as warnings). Doesn't filter forwarding — all events go to risk_module regardless of type.

## §4 Open Decisions

### §4.1 DRY refactor vs straight mirror

**Question**: extract the outbox pattern into a shared `webhook_outbox.py` module that both Plaid and SnapTrade use, OR mirror the Plaid code inline?

**Decision: mirror inline** (defer DRY refactor).
- The Plaid implementation is already in production, working. Refactoring it AND adding SnapTrade in one PR doubles the blast radius.
- Per CLAUDE.md "Don't add features, refactor, or introduce abstractions beyond what the task requires. Three similar lines is better than a premature abstraction."
- File V4b.1.0-tail = "DRY refactor: extract `webhook_outbox` shared module" as a follow-up if a third webhook source ever needs the pattern.

### §4.2 Replay-window edge case

`risk_module/routes/snaptrade.py:528` rejects events outside `REPLAY_WINDOW_S`. If Edgar_updater's outbox retries push an event past that window during a downstream outage, risk_module returns 403 and Edgar_updater's worker treats it as a delivery failure → keeps retrying → eventually dead-letters.

**Decision: accept**. Outbox first-attempt latency is sub-second on the happy path. Retries past replay window mean a genuine extended outage; dropping the stale event is correct behavior. Document in §7.

### §4.3 Same SQLite DB or separate?

**Question**: store SnapTrade outbox in the same SQLite file as Plaid (different table) or separate file?

**Decision: separate file** (`snaptrade_webhook_outbox.sqlite`, configurable via `SNAPTRADE_WEBHOOK_OUTBOX_DB_PATH`). Mirrors Plaid's pattern exactly. Avoids cross-table lock contention. Simpler to back up / restore independently.

### §4.4 Shared-secret coordination (DECIDED — moved here from §5 per Codex R1)

Edgar_updater forwards with header `X-SnapTrade-Forward-Secret` (mirrors Plaid's `X-Plaid-Forward-Secret` at `flask_config.py:41`). Allows risk_module to authenticate that the inbound POST genuinely came from Edgar_updater (not an attacker hitting the risk_module endpoint directly).

**Coupling with V4b.1**: risk_module's `routes/snaptrade.py:1418-1490` webhook handler does NOT currently check for a forward secret. V4b.1 has been bumped from R4.1.1 to R5 (DONE) with a new Phase 0 forward-secret check landing BEFORE V4b.1 R3 impl. §10 hand-off below references V4b.1 R5 throughout.

**Decision (R1.1)**:
- Edgar_updater (V4b.1.0): set `X-SnapTrade-Forward-Secret` header in outgoing forward, value from env var `SNAPTRADE_WEBHOOK_FORWARD_SHARED_SECRET`.
- risk_module (V4b.1 R5 addendum): in webhook handler at `routes/snaptrade.py:1418`, BEFORE `_verify_snaptrade_webhook`, check `request.headers.get("X-SnapTrade-Forward-Secret") == os.getenv("SNAPTRADE_WEBHOOK_FORWARD_SECRET")`. If mismatch, reject 403. Skip when env var unset (dev-friendly default — same pattern as Plaid).
- Both sides share the same secret value via env vars in their respective deployments.

## §5 Implementation Plan

### Phase 1 — `flask_config.py` constants
Add SnapTrade constants mirroring Plaid (see §3 table). ~25 LoC.

### Phase 2 — `webhook_routes.py` outbox + worker
Add SnapTrade equivalents of all Plaid private helpers (§3 table). ~280 LoC (mirrors the 89-621 range of Plaid code, minus the Plaid-specific code-classification logic which simplifies for SnapTrade's flat event types).

### Phase 3 — `webhook_routes.py` ingress route
Add `@webhook_bp.route("/snaptrade/webhook", methods=["POST"])` `def snaptrade_webhook_ingress()`. Body parses JSON, persists payload `webhookId` field (when present) as the outbox `webhook_id` column for dedup; computes `trace_id` as `payload.get("webhookId") or secrets.token_hex(8)` per R1.1 finding [2] (NOT derived from `Signature`); logs, checks anti-loop marker, enqueues, ensures worker, returns 200. ~30 LoC.

### Phase 4 — Env config + deployment
- New env vars in Edgar_updater prod env (no code change in this phase, just runbook):
  - `SNAPTRADE_WEBHOOK_FORWARD_URL` = pointer to risk_module's prod backend `/api/snaptrade/webhook` route
  - `SNAPTRADE_WEBHOOK_FORWARD_SHARED_SECRET` = matches risk_module's expected forward-secret (see §4.4 in §4)
  - `SNAPTRADE_WEBHOOK_OUTBOX_DB_PATH` (optional override; defaults from `flask_config.py`)
  - `SNAPTRADE_WEBHOOK_FORWARD_TIMEOUT_SECONDS` (optional override; default 5s)
- Document in Edgar_updater's deployment runbook / README.

### Phase 5 — Tests

New test file: `~/Documents/Jupyter/Edgar_updater/tests/test_snaptrade_webhook_ingress.py` (or wherever Edgar_updater tests live — verify during impl).

Test cases:
1. POST `/snaptrade/webhook` with valid JSON → 200, event enqueued to outbox
2. POST with anti-loop marker `X-SnapTrade-Forwarded: 1` → 200, event NOT enqueued (already-forwarded path)
3. POST with malformed JSON → 200 still returned (we don't reject bad payloads at the edge; risk_module is the verifier)
4. Outbox worker forwards event → marks delivered, payload reaches `SNAPTRADE_WEBHOOK_FORWARD_URL`
5. Forward returns 5xx → outbox event scheduled for retry with backoff
6. Forward URL unset → worker raises `forward_target_not_configured` per Plaid pattern (`webhook_routes.py:407-410`); event scheduled for retry; AFTER `max_attempts` (default 25) hit, event moves to `dead_letter` status. Test asserts: scheduled retry on first failure, dead-letter after attempt cap (corrected per Codex R1 finding [4])
7. Allowlist headers (`Signature`, `User-Agent`) forwarded; non-allowlist headers stripped
8. Forward-secret header `X-SnapTrade-Forward-Secret` injected when `SNAPTRADE_WEBHOOK_FORWARD_SHARED_SECRET` env var set; absent when unset (dev-friendly default)
9. `webhookId` from payload persisted as `webhook_id` column for dedup; trace_id falls back to `secrets.token_hex(8)` if `webhookId` absent

LoC: ~150.

### Phase 6 — Admin endpoints + dashboard surface (in-scope per R1.1 finding [3])

The `_get_snaptrade_outbox_summary` and `_requeue_stuck_snaptrade_processing_events` helpers added in Phase 2 (per §3 mirror map) are USED by Edgar_updater admin routes (`admin_routes.py:49, 109` for Plaid). Phase 6 wires the SnapTrade equivalents:
- New admin status endpoint that returns `_get_snaptrade_outbox_summary` output (mirror Plaid pattern at `admin_routes.py:49`)
- New admin replay endpoint that calls `_requeue_stuck_snaptrade_processing_events` (mirror `admin_routes.py:109`)
- Dashboard view (`dashboard_routes.py`): if Plaid outbox summary is rendered there today, add a parallel SnapTrade card. Verify during impl.

Without Phase 6, admin lacks visibility into SnapTrade outbox health — same observability surface as Plaid is required for parity. ~50-80 LoC depending on dashboard rendering scope.

## §6 Sequencing + Codex Review Gates

| Phase | Work | LoC | Gate |
|---|---|---|---|
| **R0** | This plan (R1 → R1.1) | 0 | `/codex review` — iterating |
| **R1** | Codex impl Phases 1-3 + 5 + 6 (single PR in Edgar_updater) | ~535-565 LoC (incl. Phase 6 admin wiring per R1.1 finding [3]) | `/codex review` of diff |
| **R2** | Phase 4: deploy + env config in Edgar_updater prod | 0 (config) | manual deployment runbook |
| **R3** | Smoke test: POST a fake event to `https://www.financialmodelupdater.com/snaptrade/webhook` → confirm outbox persists + worker forwards | 0 (smoke) | manual verify |
| **R4** | SnapTrade dashboard: configure webhook URL `https://www.financialmodelupdater.com/snaptrade/webhook` + subscribe `ACCOUNT_HOLDINGS_UPDATED`. NOTE per R1.1 finding [5]: SnapTrade dashboard webhook secrets are deprecated — the HMAC `Signature` uses the SnapTrade client secret (already in our `SNAPTRADE_WEBHOOK_SECRET` env var); separately, `SNAPTRADE_WEBHOOK_FORWARD_SHARED_SECRET` is a Edgar_updater↔risk_module env-only secret, NOT entered in the SnapTrade dashboard. | 0 (dashboard) | dashboard pull |
| **R5** | Hand off to V4b.1 R5: prerequisite satisfied, V4b.1 R5 impl unblocked (NOT R4.1.1 — V4b.1 was bumped to R5 with Phase 0 forward-secret check) | 0 | confirms |

V4b.1.0 → SHIPPED in TODO.md after R5.

## §7 Edge Cases & Decisions

1. **Replay-window during retry storms** (per §4.2) — accept; outbox dead-lettering after extended outage is correct behavior.

2. **Outbox SQLite locked** — `WAL` journal mode + 30s busy_timeout (matching Plaid pattern at `webhook_routes.py:177-178`). Multi-worker safe.

3. **Worker thread crash** — `_ensure_snaptrade_outbox_worker_running` (mirror of `_ensure_plaid_outbox_worker_running:473`) lazily starts on first ingress via a once-set boolean guard. **Pre-existing pattern limitation (per Codex R1 finding):** if the worker thread dies (uncaught exception breaks out of `while True`), the boolean stays `True` and subsequent ingresses do NOT restart it — events accumulate in `pending` until process restart. The `_plaid_outbox_worker_loop` does have try/except around the batch processing so normal errors don't kill the loop, but worst-case crash is unrecovered. R1.1 inherits this limitation from the Plaid pattern; documented as **V4b.1.0-tail: worker auto-restart / heartbeat monitoring**.

4. **Edgar_updater process restart** — outbox is on-disk SQLite, so unprocessed events survive restarts; worker resumes claim-next on startup.

5. **Disk full** — SQLite write fails, ingress returns 200 still (we don't fail the SnapTrade ack), error logged. Event lost. Document in §9 V4b.1.0-tail: "monitor outbox disk usage."

6. **risk_module backend down for >24hr** — outbox retry backoff caps at 300s; events remain in `pending` state until `max_attempts` (default 25) hit, then move to `dead_letter`. Operator visibility via `_get_snaptrade_outbox_summary` (Phase 6, in-scope per R1.1 finding [3]).

7. **Anti-loop marker cycling** — risk_module's webhook handler does NOT forward webhooks anywhere downstream, so the loop concern is purely defensive. Marker still added per Plaid convention.

8. **SnapTrade signature header pass-through** — `Signature` header included in `SNAPTRADE_FORWARD_HEADER_ALLOWLIST`. Risk_module verifies; Edgar_updater does not. If signature wrong, risk_module returns 403; Edgar_updater retries; event dead-letters. Acceptable — bad sig = real attack or misconfig, dropping is right.

9. **Shared-secret rotation** — env var change on both sides (Edgar_updater + risk_module) requires brief window of overlap. Document in deployment runbook.

10. **Test app vs prod app coexistence** — SnapTrade dashboard separates client_id `HENRY-CHIEN-LLC-RTXYG` (prod) and `HENRY-CHIEN-LLC-TEST-GCXHL` (test). V4b.1.0 ingress doesn't care; same URL serves both. risk_module's `_set_snaptrade_pending_updates_for_webhook_user` resolves owner via DB lookup — works for both.

## §8 Plan Workflow (per CLAUDE.md)

1. R0 — this plan → user approval → `/codex review`.
2. R1 — Codex impl in Edgar_updater repo via `mcp__codex__codex` (workspace-write, inherit model, approval-policy: never, `cwd=~/Documents/Jupyter/Edgar_updater`).
3. R2 — manual deployment of Edgar_updater + env config.
4. R3 — smoke test.
5. R4 — SnapTrade dashboard config.
6. R5 — hand off to V4b.1 R5 (NOT R4.1.1 — V4b.1 was bumped per R1.1 finding [1] forward-secret coupling).

V4b.1.0 → SHIPPED. V4b.1 → R5 → R3 (Codex impl in risk_module, includes Phase 0 forward-secret check).

## §9 Out-of-scope / V4b.1.0-tail items (named, not deferred per CLAUDE.md)

- **DRY refactor**: extract shared `webhook_outbox` module if a third webhook source is added later (§4.1).
- **Worker auto-restart / heartbeat**: Plaid pattern's once-set boolean guard means a crashed worker doesn't restart. Inherited limitation; address in a shared improvement (§7.3).
- **Disk-usage monitor**: alert if outbox SQLite grows beyond N MB (§7.5).
- **Telemetry**: emit Datadog/Prometheus counters for ingress-received / forwarded / dead-lettered (Plaid likely doesn't have these either; out of V4b.1.0 scope unless trivial).

## §10 Hand-off to V4b.1 R5

When V4b.1.0 ships (R5 of this plan), V4b.1 R5 impl can proceed with the following inputs known:

- Webhook URL at SnapTrade dashboard: `https://www.financialmodelupdater.com/snaptrade/webhook` (already configured at V4b.1.0 R4)
- risk_module backend will receive forwarded requests at `<risk_module_prod_url>/api/snaptrade/webhook` (URL TBD pending risk_module deployment)
- Forward-secret header `X-SnapTrade-Forward-Secret` set by Edgar_updater per env var `SNAPTRADE_WEBHOOK_FORWARD_SHARED_SECRET`; must be verified by risk_module's webhook handler at the new Phase 0 step in V4b.1 R5 against env var `SNAPTRADE_WEBHOOK_FORWARD_SECRET`. Both env vars share the same value via deployment runbook coordination.
- HMAC `Signature` continues to use existing `SNAPTRADE_WEBHOOK_SECRET` env var (= SnapTrade client secret); no change to existing signature verification path.

V4b.1.0 → V4b.1 R5 chain visible in TODO.md.
