> **✅ SHIPPED — SnapTrade orders sync live + worker tests. Moved during 2026-05-26 docs cleanup.**

# V4b.1 — SnapTrade Orders Sync: Webhook-Driven + Daily Catch-All (R5 — V4b.1.0 forward-secret coupling)

## §0.-1 R4.1 → R5 — V4b.1.0 prerequisite addendum

R4.1.1 PASSed Codex review. R2 dashboard verification (2026-04-28) revealed the prerequisite: SnapTrade has NO webhook listener configured and Edgar_updater (the public webhook ingress) has NO SnapTrade handler. V4b.1.0 was filed to add the Edgar_updater ingress (mirror of Plaid pattern). V4b.1.0 R1 review surfaced an additional coupling: Edgar_updater forwards with header `X-SnapTrade-Forward-Secret` (mirror of Plaid pattern), so risk_module's webhook handler must verify this header to prevent direct-hit attacks bypassing the Edgar_updater edge.

R5 changes from R4.1.1:

- **NEW Phase 0** in §5 (BEFORE existing Phase 1): forward-secret verification at the top of `routes/snaptrade.py:1418` webhook handler. Check `request.headers.get("X-SnapTrade-Forward-Secret") == os.getenv("SNAPTRADE_WEBHOOK_FORWARD_SECRET")` BEFORE `_verify_snaptrade_webhook`. If env var set and mismatch → 403. If env var unset → skip check (dev-friendly default, matches Plaid pattern at Edgar_updater `webhook_routes.py:99-101`).
- **§4 Resolved Questions** adds Q4: forward-secret naming + value coordination with Edgar_updater env var `SNAPTRADE_WEBHOOK_FORWARD_SHARED_SECRET`. Both sides MUST share the same value via deployment-time env var.
- **§3.1 secret semantics** clarification: `SNAPTRADE_WEBHOOK_SECRET` (existing, used for HMAC `Signature` verification) and `SNAPTRADE_WEBHOOK_FORWARD_SECRET` (NEW, for edge-to-backend authentication) are TWO different secrets. The first is the SnapTrade client/consumer-key secret (verified by `_verify_snaptrade_webhook`). The second is a Edgar_updater↔risk_module shared secret (verified by NEW Phase 0 check).
- **§6 Sequencing** updated: V4b.1.0 R5 (SnapTrade dashboard config) MUST land before V4b.1 R5 (smoke test); V4b.1 R3 impl now includes the new Phase 0.

R5 supersedes R4.1.1. Prior trace history at §10.

---

## §0.0 R4 → R4.1 — Codex review fixes

R4 review FAILED with 6 findings. R4.1 fixes:

- **[1] Order enqueue gate** — `enqueue_order_sync` has no internal enable check; existing manual-refresh route (`routes/sync_jobs.py:42`) gates on `ORDERS_VIA_CELERY`. R4.1 adds the same gate in the webhook handler before calling `enqueue_order_sync` (Phase 1 updated).
- **[2] Freshness claims softened** — SnapTrade docs describe `ACCOUNT_HOLDINGS_UPDATED` as a holdings-refresh-completed event (daily account syncs + manual refreshes), NOT a granular broker-side push. App-placed trades produce the webhook via `refresh_after_trade` → Manual Refresh, so freshness IS near-realtime for those. External broker-side activity is daily-bounded unless manually refreshed. R4 over-claimed "sub-second from broker action." Corrected throughout §2 and §7.
- **[3] Re-entrancy claim corrected** — `enqueue_order_sync` returns `already_running` IMMEDIATELY (does NOT wait for in-flight). Concurrent triggers coalesce/no-op within the 150s Redis lock window. The catch-all/next-webhook recovers any skipped work. §4.3 corrected.
- **[4] Health-monitor fallback added** — daily catch-all assumes webhooks ARE arriving. R4.1 adds a `last_holdings_webhook_received_at` monitor + 12h aggressive fallback when no `ACCOUNT_HOLDINGS_UPDATED` has arrived for an extended window (new Phase 6).
- **[5] Test scope expanded** — Phase 3 now includes: (a) both syncs enqueue on ACCOUNT_HOLDINGS_UPDATED, (b) owner-missing returns 200 and enqueues neither, (c) order sync skipped when gate disabled, (d) enqueue failures log but still ack webhook.
- **[6] Sequencing reordered** — dashboard webhook config verification moved BEFORE impl (was post-impl).

Also — `docs/planning/V4B_BASELINE.md` still describes the R3.1 interval-reduction direction. Updated as a sibling task in the impl PR.



## §0 R4 pivot rationale

**R3.1 (PASS)** proposed reducing the orders-sync beat from 5min → 30min for ~83% savings. Before sending to Codex for impl, the user surfaced an architectural question: SnapTrade has webhooks — why are we polling at all?

**Investigation answered the question:** SnapTrade's `ACCOUNT_HOLDINGS_UPDATED` event (per `docs.snaptrade.com/docs/webhooks`) covers orders ("Triggered when holdings data including positions, balances, **orders**, account value is refreshed"). **Important nuance** (Codex R4 finding [2]): this event fires when SnapTrade COMPLETES a holdings refresh (daily account syncs + manual refreshes), NOT on every broker-side order transition. App-placed trades produce the webhook via `refresh_after_trade` → Manual Refresh (near-realtime for those). External broker-side activity is bounded by SnapTrade's daily refresh cadence unless manually refreshed. Our webhook handler at `routes/snaptrade.py:1456-1467` already RECEIVES this event but only triggers a position sync — ignoring the orders dimension of the same signal.

**The right lever is webhook-driven orders sync, not interval reduction.** R3.1 was a band-aid; R4 fixes the architectural mismatch. ~99% savings on the orders-sync per-call cost (one daily catch-all + webhook-triggered syncs vs. 288 unconditional polls/day). Effective freshness: near-realtime for app-placed trades; daily-bounded for external broker activity (still better than current 5-min polling for app-placed; same as current for external).

**R4 supersedes R2/R3/R3.1.** Prior trace history preserved in §10 for context.

## §1 Problem (R4)

`workers/beat_schedule.py:47-52` polls SnapTrade orders every 300s default — 288 runs/user/day × 2 accounts × $0.002/call = **$34.50/user/month**, 22× the $1.50 Connected User subscription floor. R4's pivot: SnapTrade already pushes order updates via `ACCOUNT_HOLDINGS_UPDATED` webhook, but our handler ignores the orders signal. Fix the handler to enqueue an orders sync alongside the position sync, and drop the beat to a daily catch-all.

## §2 Source-of-Truth Layout

### Webhook event coverage (verified 2026-04-27 from `docs.snaptrade.com/docs/webhooks`)

| Event | What it covers | Our current handler |
|---|---|---|
| `ACCOUNT_HOLDINGS_UPDATED` | positions, balances, **orders**, account value | Triggers position sync ONLY (`routes/snaptrade.py:1459-1464`) — orders dimension ignored |
| `ACCOUNT_TRANSACTIONS_INITIAL_UPDATE` | initial transaction sync after new connection | Not handled (logged + ignored) |
| `ACCOUNT_TRANSACTIONS_UPDATED` | incremental transaction updates (daily checks) | Not handled |
| `CONNECTION_BROKEN`/`CONNECTION_FAILED` | broken/failed brokerage connections | Logged warning |
| `USER_REGISTERED`/`USER_DELETED`/`CONNECTION_*`/`NEW_ACCOUNT_AVAILABLE`/`ACCOUNT_REMOVED` | various lifecycle events | Not handled |

**Note: SnapTrade does NOT publish a granular order-state-transition event** (PENDING → FILLED). Order-related changes are bundled in `ACCOUNT_HOLDINGS_UPDATED`. So the right play is to consume that event, not look for a separate one.

### Existing wiring (traced)

- Webhook handler: `routes/snaptrade.py:1418-1490` (POST `/api/snaptrade/webhook`)
- Signature verification: `_verify_snaptrade_webhook` (`:502+`) — wired and working
- Position sync enqueue: `enqueue_provider_sync_if_enabled` (`routes/_sync_helpers.py:155`) → `services.sync_runner.enqueue_sync`
- Orders sync enqueue: `services.sync_runner.enqueue_order_sync` (`:337`) — exists, used by manual-refresh route at `routes/sync_jobs.py:43-47`. NOT currently called from the webhook handler.
- Beat schedule: `workers/beat_schedule.py:47-52` — `sync_all_users_for_orders` every 300s, gated on `CELERY_ENABLED && ORDERS_VIA_CELERY`
- Frontend: `frontend/.../useOrders.ts` polls `/api/orders` every 30s; backend reads local `trade_orders` (Codex finding [9] from R2 — webhook + daily catch-all keeps the local DB fresh, so the 30s poll continues to surface near-real-time data)

### 3-axis billing context

SnapTrade has $1.50/Connected User/month subscription (covers 16 of 18 ops including positions/balance/list) + per-call carve-outs for `connections.refresh_brokerage_authorization` ($0.05) and `accounts.orders` ($0.002). Beat polling ONLY hits the per-call axis. Removing the polling does NOT touch the subscription bill.

## §3 Decision (R4)

### Option A (recommended) — Webhook-driven primary + daily catch-all

When `ACCOUNT_HOLDINGS_UPDATED` arrives at the webhook handler, enqueue BOTH a position sync AND an orders sync. Drop the beat default to **86400s (daily)** as a catch-all for missed webhooks (network failures, broker-side latency, etc).

- Savings: ~99% of orders-sync cost (1 beat run/day + N webhook-triggered syncs ≈ N+1 syncs/day vs. 288)
- Effort: ~30 LoC. Three changes: (1) extend webhook handler to call `enqueue_order_sync`, (2) change beat default 300s → 86400s, (3) tests + .env.example
- Risk: webhook delivery failure → orders fall up to 24hr behind. Mitigated by: (a) on-demand sync via `sync_jobs` route (user-initiated), (b) `execute_and_reconcile` 2s polling for trades placed through that path, (c) daily catch-all guarantees eventual consistency
- Reversibility: env-var override `SYNC_ORDERS_INTERVAL_SECONDS` can drop back to any value without code change

### Option B (rejected) — Webhook-driven primary, NO catch-all
Same as A but disable the beat entirely. Saves another ~$0.05/user/month. **Rejected**: removes the safety net for webhook delivery failures. SnapTrade webhook delivery is best-effort; daily catch-all is cheap insurance.

### Option C (R3.1's approach, demoted) — Interval reduction only
5min → 30min default. Saves ~83%. **Rejected** in favor of A: leaves the architectural mismatch in place (we already RECEIVE the order-update signal via webhook and discard it). A fixes the right thing.

## §4 Resolved Questions

1. **Does SnapTrade have an order-state webhook event?** RESOLVED: NO granular event, but `ACCOUNT_HOLDINGS_UPDATED` bundles order updates. Our existing handler consumes the event but ignores the orders dimension.
2. **Does our webhook handler need infrastructure changes (signature verification, replay protection)?** RESOLVED in R4: signature/replay already wired. **R5 update**: forward-secret verification is NEW (Phase 0 added) per V4b.1.0 coupling. So infra change IS needed in V4b.1's R5+ scope.
3. **Is `enqueue_order_sync` re-entrant from the webhook context?** RESOLVED via §2 trace: YES — Redis-locked at 150s (`services/sync_runner.py:20`); concurrent webhook + manual refresh + daily beat return `already_running` IMMEDIATELY (does NOT wait for in-flight to complete — Codex R4 finding [3]). Concurrent triggers coalesce/no-op within the lock window; the catch-all beat OR the next webhook recovers any skipped work. Acceptable: a single signal in the lock window is sufficient since the eventual sync pulls full state anyway.
4. **Forward-secret naming + value coordination with Edgar_updater?** (NEW R5) — Edgar_updater env var: `SNAPTRADE_WEBHOOK_FORWARD_SHARED_SECRET`. risk_module env var: `SNAPTRADE_WEBHOOK_FORWARD_SECRET`. Both MUST hold the same value at deploy time. Naming asymmetry is intentional: Edgar_updater's name says "what to inject as outgoing"; risk_module's says "what to require as incoming." Consider unifying naming convention at deploy-time runbook step (set both from a single source).

## §5 Implementation Plan (Option A)

### Phase 0 — forward-secret verification (NEW per R5 / V4b.1.0 coupling)
File: `routes/snaptrade.py:1418` (top of webhook handler, BEFORE `_verify_snaptrade_webhook`)

```python
# Edge authentication: when running behind Edgar_updater edge, verify the forward
# secret to prevent direct-hit attacks. Skip when env var unset (dev default).
forward_secret_expected = os.getenv("SNAPTRADE_WEBHOOK_FORWARD_SECRET", "").strip()
if forward_secret_expected:
    forward_secret_provided = request.headers.get("X-SnapTrade-Forward-Secret", "")
    if not hmac.compare_digest(forward_secret_provided, forward_secret_expected):
        portfolio_logger.warning("Rejecting SnapTrade webhook: forward-secret mismatch")
        raise HTTPException(status_code=403, detail="Forbidden")
```

The Edgar_updater edge sets the matching header from its env var `SNAPTRADE_WEBHOOK_FORWARD_SHARED_SECRET` per V4b.1.0 §4.4. When BOTH env vars are unset (local dev), the check is skipped — matching Plaid's pattern at `flask_config.py:99-101`. ~10 LoC.

### Phase 1 — webhook handler: enqueue orders sync alongside position sync
File: `routes/snaptrade.py:1456-1467` (the `ACCOUNT_HOLDINGS_UPDATED` branch)

Add `enqueue_order_sync` call alongside existing `enqueue_provider_sync_if_enabled`, **gated on `ORDERS_VIA_CELERY` env flag** (Codex R4 finding [1] — `enqueue_order_sync` itself has no internal enable check; existing manual-refresh route at `routes/sync_jobs.py:42` gates the same way). Conceptually:

```python
if webhook_type == "ACCOUNT_HOLDINGS_UPDATED":
    owner = _set_snaptrade_pending_updates_for_webhook_user(webhook_user_id)
    if isinstance(owner, dict):
        _enqueue_provider_sync_if_enabled(  # existing — position sync
            user_id=owner["user_id"],
            user_email=owner["email"],
            provider="snaptrade",
            trigger="webhook",
        )
        # NEW — orders sync (orders are bundled in ACCOUNT_HOLDINGS_UPDATED per SnapTrade docs).
        # Gated on the same flag manual-refresh uses (routes/sync_jobs.py:42).
        if _env_flag("ORDERS_VIA_CELERY", False):
            try:
                from services.sync_runner import enqueue_order_sync
                result = enqueue_order_sync(
                    user_id=owner["user_id"],
                    user_email=owner["email"],
                    provider="snaptrade",
                    trigger="webhook",
                    deadline_seconds=60,
                )
                state = result.get("state")
                if state in {"redis_unavailable", "enqueue_failed"}:
                    portfolio_logger.warning(
                        "Could not enqueue snaptrade orders sync trigger=webhook user_id=%s: %s",
                        owner["user_id"], result.get("error") or state,
                    )
            except Exception as exc:
                portfolio_logger.warning(
                    "Failed to enqueue snaptrade orders sync trigger=webhook user_id=%s: %s",
                    owner["user_id"], exc,
                )
```

Webhook MUST ALWAYS return success to SnapTrade (don't fail the ack). Catch-all beat + next webhook recover any skipped enqueue.

**Cleaner refactor option (preferred if scope permits):** add a sibling helper `enqueue_order_sync_if_enabled` to `routes/_sync_helpers.py` mirroring `enqueue_provider_sync_if_enabled` (same gate-check + warn-log structure). Webhook handler calls the helper; manual-refresh route at `routes/sync_jobs.py:42-51` ALSO refactors to use it (eliminates duplicate gate logic). Decided in PR review.

### Phase 2 — beat default: 300s → 86400s (daily catch-all)
File: `workers/beat_schedule.py:50`

```diff
-        "schedule": _interval("SYNC_ORDERS_INTERVAL_SECONDS", 300),
+        "schedule": _interval("SYNC_ORDERS_INTERVAL_SECONDS", 86400),
```

Env-var override preserved. Local dev can keep faster cadence by setting `SYNC_ORDERS_INTERVAL_SECONDS=300`.

### Phase 3 — test updates (expanded per Codex R4 finding [5])
- `tests/workers/test_celery_app_config.py:97-110` — ADD `assert config["schedule"] == 86400` for the `sync-orders` entry.
- `tests/api/test_snaptrade_webhook.py` — ADD four cases:
  1. `ACCOUNT_HOLDINGS_UPDATED` with valid signature + owner mapping → BOTH `enqueue_provider_sync_if_enabled` (position) AND `enqueue_order_sync` (orders) called, with `provider="snaptrade"` + `trigger="webhook"`.
  2. Owner mapping missing (`_set_snaptrade_pending_updates_for_webhook_user` returns `None`) → webhook returns 200, NEITHER sync enqueued.
  3. `ORDERS_VIA_CELERY=false` (gate disabled) → position sync still enqueued, orders sync NOT enqueued.
  4. `enqueue_order_sync` returns `redis_unavailable` or `enqueue_failed` → webhook still returns 200, warning logged.
- Verify existing webhook tests (signature verification, replay protection, unsigned-when-secret-disabled at `tests/api/test_snaptrade_webhook.py:20+`) still pass without changes.
- `tests/conftest.py:143` — already monkeypatches `ORDERS_VIA_CELERY=false`; need to ensure new tests that exercise the order-enqueue branch override to `true` locally (per-test monkeypatch).
- Run `rg -n '\b300\b' tests/ workers/ services/ brokerage/ routes/` to surface any stale assertions.

### Phase 4 — env doc + .env.example
File: `.env.example:98`

```diff
-SYNC_ORDERS_INTERVAL_SECONDS=300
+SYNC_ORDERS_INTERVAL_SECONDS=86400
```

Add adjacent comment: `# Webhook-driven primary path (V4b.1); beat is daily catch-all only`.

### Phase 5 — OrderWatcher decision (unchanged from R3)
- `services/order_watcher.py:16` `poll_seconds=300` and `mcp_server.py:3586` `ORDER_WATCHER_POLL_SECONDS=300` — separate fallback path active only when `ORDERS_VIA_CELERY=false` (dev/CI).
- **Decision: leave at 300s.** Dev/CI environments value snappy feedback over cost; webhook path doesn't fire in those environments anyway.
- Add code comment at `services/order_watcher.py:16`: `# 300s default for non-Celery (dev/CI) environments — Celery path is webhook-driven with daily catch-all per V4b.1`.

### Phase 6 — Webhook health monitor + 12hr aggressive fallback (NEW per Codex R4 finding [4])
The daily catch-all assumes `ACCOUNT_HOLDINGS_UPDATED` webhooks ARE arriving. If SnapTrade stops delivering (account-level webhook failure, signature secret rotation gone wrong, our endpoint returning 5xx, etc.), staleness silently grows to 24hr. R4.1 adds:

1. **`last_holdings_webhook_received_at` tracking** — narrowly scoped to `ACCOUNT_HOLDINGS_UPDATED` ONLY (per Codex R4.1 finding — connection/lifecycle webhooks must NOT mask missing holdings webhooks). Implementation: inside the `if webhook_type == "ACCOUNT_HOLDINGS_UPDATED":` branch at `routes/snaptrade.py:1456`, after owner is resolved, write `(provider="snaptrade", user_id, last_holdings_received_at=NOW())` to a small `webhook_health` table. Schema: `CREATE TABLE webhook_health (provider TEXT NOT NULL, user_id INT NOT NULL, last_holdings_received_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (provider, user_id))`. Upsert on every ACCOUNT_HOLDINGS_UPDATED.

2. **Health-check task** — new lightweight Celery beat task `check_snaptrade_webhook_health` running hourly. Query: LEFT JOIN active SnapTrade `data_sources` against `webhook_health`. For each user where `webhook_health.last_holdings_received_at IS NULL` (never received) OR `< NOW() - INTERVAL '12 hours'` (stale), log warning + enqueue an immediate orders sync + position sync as aggressive fallback. Treats both never-received and stale as "degraded." First-run users (no row yet) trigger the fallback after the 12hr threshold from their `data_sources.created_at`, NOT immediately on connection — implementation gates the fallback on `data_sources.created_at < NOW() - INTERVAL '12 hours'` to avoid pre-launch-storm on freshly-onboarded users.

3. **Telemetry surface** — log_event for `webhook_health_degraded` (when fallback fires per user) + `webhook_health_recovered` (when ACCOUNT_HOLDINGS_UPDATED arrives after a degraded period) so admin can see/alert.

LoC estimate: ~50 (migration for webhook_health table, helper, beat task, 2-3 tests covering: never-received → fires after 12hr-from-onboard; stale → fires; recently-received → does not fire). If scope-tightening, Phase 6 can ship as a follow-up V4b.1.tail and the initial PR ships Phases 1-5 only — but health monitor is RECOMMENDED for the same PR since it's the primary safety net. Decided in PR review.

## §6 Sequencing + Codex Review Gates

| Phase | Work | LoC | Gate |
|---|---|---|---|
| **R0** | This plan (R4 → R4.1 → R5) | 0 | DONE; iterating |
| **R1** | Codex review of R5 plan | 0 | `/codex review` — required before impl |
| **R2** | **PREREQ: V4b.1.0 (Edgar_updater SnapTrade ingress) shipped + SnapTrade dashboard webhook URL configured** — without this, V4b.1's webhook-driven path receives nothing. R2 is satisfied when V4b.1.0 R5 completes. | 0 (gated by V4b.1.0) | V4b.1.0 ship gate |
| **R3** | Codex impl §5 Phase 0 + Phases 1-5 + 6 (single PR; or 1-5 + Phase 6 follow-up if scope-trimmed) | ~40-90 LoC (incl. ~10 for Phase 0 forward-secret check) | `/codex review` of diff |
| **R4** | Live verification — place a test trade, confirm Edgar_updater receives webhook + forwards with `X-SnapTrade-Forward-Secret` + risk_module accepts + orders sync runs + `last_holdings_webhook_received_at` updates | 0 (smoke test) | manual verify |
| **R5** | Commit + ship | 0 | per-PR review |
| **R6** | Update `docs/planning/V4B_BASELINE.md` to reflect R5 webhook-driven approach (was describing R3.1 interval reduction) | ~20 LoC docs | none |

## §7 Edge Cases & Decisions

1. **Webhook delivery failure** — SnapTrade may fail to deliver a webhook (network, retry exhaustion, signature mismatch). Daily catch-all (86400s beat) bounds staleness to ≤24hr. User can also force a sync via the manual refresh route for immediate freshness.

2. **Webhook arrival latency** — for app-placed trades (which trigger Manual Refresh via `refresh_after_trade`), webhook arrival is typically seconds (Manual Refresh + delivery roundtrip). For external broker activity (orders placed outside our app), freshness is bounded by SnapTrade's holdings-refresh cadence — typically daily, sometimes more frequent. Effective summary: app-placed trades go from "up to 5 minutes" → "seconds-to-minutes"; external orders stay roughly at the existing "daily" floor. Net: better for app-placed, neutral for external.

3. **Webhook-not-configured** — pre-launch, SnapTrade dashboard webhook URL must be configured AND `ACCOUNT_HOLDINGS_UPDATED` event subscribed. R3 phase verifies this in dashboard before R5 ship.

4. **Frontend `useOrders` 30s poll** (Codex R2 finding [9]) — under R4.1, local DB is updated via webhook for app-placed trades (seconds-to-minutes) and via daily catch-all + 12hr health-fallback for external activity. The 30s frontend poll surfaces whatever the local DB has. The R3.1 concern about "UI looks live but data is 30min stale" is materially improved for app-placed trades; for external broker activity, the experience is roughly equivalent to current production (daily-bounded). V4b.1-tail (per-row freshness UI) becomes optional polish, not a regression mitigation.

5. **Direct `execute_order` callers** (basket via `mcp_tools/basket_trading.py:500-540`, hedge via `routes/hedging.py:420-465`) — bypass `execute_and_reconcile`'s 2s polling. Under R4.1, the post-trade `refresh_after_trade` path triggers SnapTrade's Manual Refresh which produces an `ACCOUNT_HOLDINGS_UPDATED` webhook back to us. So basket/hedge get post-trade freshness via the webhook → orders-sync chain (typically within seconds of webhook delivery, NOT sub-second from broker fill). Pre-existing gap from R3.1 is materially improved.

6. **`_reconcile_order_status` exception swallowing** (Codex R2 finding [2]) — pre-existing bug; out of V4b.1 scope. Webhook path doesn't go through `_reconcile_order_status`, so this bug is less hit under R4.

7. **Circuit-breaker additive staleness** (Codex R2 finding [6]) — if orders circuit opens during a webhook-triggered sync, it skips. Daily catch-all recovers. Acceptable.

8. **Redis lock collision** (Codex R2 finding [7]) — webhook + manual refresh + daily beat may all converge on the 150s Redis lock. First wins, others return `already_running`. Existing semantics; not a regression.

9. **Beat env reload requires worker restart** (Codex R2 finding [8]) — `workers/beat_schedule.py` reads env at import. Changing `SYNC_ORDERS_INTERVAL_SECONDS` requires Celery beat process restart, not hot reload. Document in deployment runbook.

10. **OrderWatcher fallback path** (Codex R2 finding [5]) — separate from V4b.1's Celery beat. Stays at 300s for dev/CI. Documented per Phase 5.

11. **Webhook user-id mapping failure** — `_set_snaptrade_pending_updates_for_webhook_user` returns `None` if no owner mapping (orphan event). Existing code logs warning + skips. Daily catch-all still picks up changes for properly-mapped users on next run.

12. **Reversibility** — if webhook approach causes issues in prod, env-var override `SYNC_ORDERS_INTERVAL_SECONDS=300` instantly restores 5min polling (the daily 86400 default applies only when env var is unset). Code change in webhook handler also reversible by single revert.

## §8 Plan Workflow (per CLAUDE.md) — sequence matches §6

1. R0 — this plan drafted → Codex review.
2. R1 — Codex review must PASS before any subsequent step.
3. R2 — PREREQ: V4b.1.0 (Edgar_updater SnapTrade ingress) shipped + SnapTrade dashboard webhook URL configured + `ACCOUNT_HOLDINGS_UPDATED` event subscribed. NOTE: SnapTrade dashboard webhook secrets are deprecated — HMAC `Signature` uses the SnapTrade client secret already in `SNAPTRADE_WEBHOOK_SECRET`. The forward-secret coordination (`SNAPTRADE_WEBHOOK_FORWARD_SECRET` ← env-var only, NOT dashboard) is a SEPARATE secret per Q4. MUST be confirmed before R3 impl, otherwise the webhook-driven path is dead-code.
4. R3 — Codex impl via `mcp__codex__codex` (workspace-write, inherit model from `~/.codex/config.toml`, approval-policy: never).
5. R4 — live smoke test (place a test trade, watch logs for webhook fire + orders sync + `last_holdings_webhook_received_at` write).
6. R5 — commit + ship.
7. R6 — update `docs/planning/V4B_BASELINE.md` to reflect webhook-driven approach (was R3.1 interval reduction).

V4b.1 → SHIPPED in TODO.md after R6.

## §9 Out-of-scope / V4b.1-tail items (named, not deferred)

- **Extend `ACCOUNT_TRANSACTIONS_UPDATED` handling** — currently ignored; could trigger transaction sync (separate from orders sync). Files as separate task.
- **Frontend per-row `last_synced_at` UI** — was a R3.1 mitigation; under R4 less urgent (data is near-realtime). Optional polish.
- **Extend `execute_and_reconcile` to basket+hedge** — pre-existing gap from R3.1 §0.1. Less urgent under R4 because webhooks cover post-trade freshness.
- **`_reconcile_order_status` exception handling** — pre-existing bug; not introduced by V4b.1.
- **`days=365` window narrowing** in beat sync — payload optimization, doesn't affect cost.

## §10 Revision history (preserved for trace)

- **R1 (initial)** — researched problem, identified beat at 5min as cost driver, decision shape laid out. §4.1 open question on `refresh_after_trade`.
- **R2** — traced `refresh_after_trade` (only Manual Refresh + cache callback), `execute_and_reconcile` 2s polling backstop. Concluded interval reduction safe. Greenlit Option A (300s → 1800s).
- **R2 review (Codex FAIL, 9 findings)** — narrowed safety claim, expanded test scope, surfaced edge cases.
- **R3** — folded all 9 findings into the document. Codex review FAIL — 4 residual contradictions (stale text in §2.3, §3 Option B, §4.1, §7.11).
- **R3.1** — fixed contradictions. Codex review PASS.
- **User question pre-impl: "why are we polling if SnapTrade has webhooks?"** — investigation surfaced that `ACCOUNT_HOLDINGS_UPDATED` covers orders, our handler ignores half the signal. Pivoted to webhook-driven primary + daily catch-all.
- **R4 (this version)** — clean rewrite, supersedes R3.1 entirely. Larger architectural fix (~30 LoC vs ~15), bigger savings (~99% vs 83%), addresses root cause.
