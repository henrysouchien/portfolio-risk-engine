# Brokerage Aggregator Architecture — Design Brief

> **Status:** Design brief, not an implementation plan. Intended as the input artifact for a future session that will produce a phased implementation plan.
> **Created:** 2026-04-08
> **Originating bug:** `get_positions` hangs 17+ minutes when Schwab/IBKR are offline.
> **Tabled patch attempt:** `POSITIONS_FETCH_TIMEOUT_PLAN.md` (12 Codex review rounds, deferred).

---

## Executive Summary

The originating bug exposed a deeper architectural flaw: **the system performs live calls to external brokerages on the user request path**. With 5 brokers each at ~99% uptime, system uptime degrades to ~95% (≈36 hours/month down). Every "fix" we attempted (timeouts, gates, thread accumulation prevention) was a workaround for a constraint that shouldn't exist on the request path at all.

The right architecture is the **aggregator pattern** used by every major fintech aggregator (Plaid, Yodlee, Mint, Personal Capital, Wealthfront): decouple data collection from data serving via background sync workers writing to a positions store with first-class freshness metadata. User requests read from the store, never block on external services.

This brief documents the problem class, why naive fixes fail, the target architecture, what we already have, and the open decisions a future implementation plan needs to resolve.

---

## Problem Class

### The User-Facing Symptom
`get_positions` hangs for 17+ minutes when Schwab or IBKR is offline. The MCP tool, REST endpoints, and dashboard all become unusable until TCP sockets eventually time out.

### The Underlying Constraint
Python has **no way to cancel a running thread**. When `future.result(timeout=30)` raises `TimeoutError`, the worker thread is still running. There's no `thread.terminate()`. Daemon threads only die at interpreter shutdown. Cancellation has to be cooperative — and the brokerage SDKs (`snaptrade-python-sdk`, `plaid-python`, `schwab-py`, `ib_async`) are sync libraries we don't control. They block on socket reads with their own timeout semantics that may or may not be configurable.

### Why Every Naive Fix Fails

Twelve rounds of Codex review on the timeout patch revealed the layered failure modes:

| Workaround | Failure mode |
|------------|--------------|
| `as_completed(futures, timeout=30)` + `future.cancel()` | `cancel()` is a no-op once a task starts. `with ThreadPoolExecutor` calls `shutdown(wait=True)` which still blocks on hung workers. |
| Per-provider socket timeouts | Plaid/SnapTrade go through SDKs we don't control. `signal.alarm` is unsafe in threads. IBKR has timeouts but they don't cover all paths. Schwab has 30s default but it's per-HTTP-call, not per-orchestrator-deadline. |
| Inner executor + `shutdown(wait=False, cancel_futures=True)` | Doesn't actually stop the worker — just lets the calling function return promptly. Worker keeps running indefinitely in the background. |
| "It's harmless on the API server" | Repeated outages **accumulate threads**. Each timed-out request leaves a zombie thread. Eventually exhausts the thread pool. |
| Per-`(user, provider)` gate to cap abandoned threads | Tracks thread liveness via `executor._threads[0]` — but ThreadPoolExecutor workers stay alive after futures complete, false-rejecting fast paths. |
| `future.add_done_callback()` for self-cleaning gate | Deadlocks if registered under a lock when the future is already done (callback fires synchronously on the calling thread and reacquires the lock). |
| Wrapper that converts socket timeouts to a sentinel exception | Now ~250 lines of pseudocode for what started as "add a timeout." Still doesn't address CLI hangs at interpreter shutdown. |

**Each fix uncovers an edge case at a deeper layer of "what if the workaround for the workaround fails."** The findings are real, but they're fighting Python's threading model. We're optimizing a workaround for a constraint that the right architecture eliminates entirely.

### What Makes This a Class, Not a Single Bug

The same root cause shows up in many places:
- `get_positions` hang (this bug)
- `get_orders` "Multiple tradeable accounts found" (related: live multi-broker fanout)
- `useSnapTrade` query racing on page load (related: blocking on connection state)
- `force_refresh=True` returning 0 positions (related: no separation of "fetch" from "read")
- Cross-source holding leakage (related: no canonical store of truth)
- Any future "data is stale" or "data is partial" UX requirement

All of these symptoms share the same architectural cause: **the system has no separation between "fetch from external service" and "serve to user request."**

---

## Target Architecture

### The Core Shift

**Never let a user request block on a live external service call.** Once you accept this, the threading/cancellation problem dissolves because nothing on the request path needs to be cancelled.

### The Aggregator Pattern

```
┌─────────────────────┐         ┌─────────────────────┐
│ Background sync     │  poll   │  External APIs      │
│ workers (per broker)│────────▶│  (Schwab, IBKR,     │
│                     │         │   Plaid, SnapTrade) │
└──────────┬──────────┘         └─────────────────────┘
           │ writes
           ▼
┌─────────────────────────────────────────────────────┐
│  Positions store (single source of truth)          │
│  ─────────────────────────────────────────────     │
│  positions:        last successful snapshot        │
│  as_of:            freshness timestamp             │
│  source_status:    OK / DEGRADED / OFFLINE         │
│  last_attempt:     when sync last ran              │
│  last_error:       what failed, if anything        │
└──────────┬──────────────────────────────────────────┘
           │ reads (always fast, never block)
           ▼
┌─────────────────────┐         ┌─────────────────────┐
│  API server         │ ──────▶ │  User / agent       │
│  (request path)     │         │  (UI, MCP, REST)    │
└─────────────────────┘         └─────────────────────┘
```

Three things to note:
1. **The arrow from API server back to External APIs is gone.** That's the whole architectural change.
2. **Freshness is a first-class field.** Consumers know when the data is from and decide whether it's fresh enough for their use case.
3. **`force_refresh` becomes an enqueue operation, not a synchronous fetch.** It returns immediately; completion arrives via websocket/SSE/polling.

### Layered Patterns That Make This Work

**Layer 1 — Decouple collection from serving** (the core)
- Background workers per provider, each writing to the shared store
- API reads from the store; never calls a provider directly
- `force_refresh` enqueues a sync job, returns a job ID, completes async

**Layer 2 — Bulkhead isolation** (Hystrix pattern)
- Each provider gets its own worker pool / queue / process
- Schwab being down can't block Plaid syncing
- In Python: separate Celery queues per provider, or separate worker processes

**Layer 3 — Circuit breakers**
- After N failures in window M, stop calling the provider for time T
- Mark provider OFFLINE in the store immediately
- Half-open: one canary request decides whether to close the circuit
- This is what eliminates the 17-minute hang at the *system* level — you stop calling the dead provider entirely

**Layer 4 — Deadline propagation**
- Every job carries an absolute `expires_at`, not a relative timeout
- When a worker picks up a job, if `now() > expires_at`, it discards immediately
- Prevents stale work from monopolizing workers during recovery waves

**Layer 5 — Process isolation for cancellable timeouts**
- Sync workers run broker calls in **subprocess pools**, not thread pools
- Subprocesses you can `kill()` — the SDK's blocking socket call dies with the process
- This is where Python's only real cancellation primitive lives (`SIGKILL` to a worker process)
- Celery's `time_limit` does exactly this
- Cost is fork overhead and IPC serialization, which is fine for sync workers (latency-insensitive) and unacceptable for request handlers (latency-sensitive). The architecture puts the slow stuff exactly where the cost is acceptable.

**Layer 6 — Idempotency keys**
- Every sync attempt carries a unique key
- Retries don't double-count
- Critical for financial data

### Freshness Becomes a Contract

Once positions have provenance (`as_of`, `source`, `status`), every consumer makes its own policy decision:

| Consumer | Freshness requirement | Stale behavior |
|----------|----------------------|----------------|
| Risk engine | ≤ 4 hours | Return PARTIAL with stale providers flagged |
| Trading | ≤ 30 seconds for the trading account | Block trade, prompt refresh |
| Dashboard | ≤ 24 hours | Show with stale badge |
| Reports / backtests | EOD snapshot, freshness irrelevant | N/A |
| Alerts / monitoring | ≤ 5 minutes for live monitoring | Alert "data stale" |

The current code can't make these distinctions because there's no place in the response where the consumer learns *how fresh the data is*. Today every consumer chooses between "live call (might hang)" and "cached (no idea how old)." Freshness as a value, not a binary, unlocks a lot of UX.

---

## What We Already Have

The migration is staged because much of the substrate exists:

| Existing piece | Role in target architecture |
|----------------|----------------------------|
| `services/position_service.py` | Becomes a thin reader over the positions store |
| Provider adapters in `providers/` | Move from inline-call to background-worker invocation |
| Existing position cache in DB | Becomes the canonical store (with schema additions for freshness) |
| `data_sources` table | Already the right place to track per-source status (currently a ghost column — see F17) |
| Stale-cache fallback at `position_service.py:1114` | Becomes the *primary* path, not a fallback |
| `force_refresh=True` flag | Becomes "enqueue sync job" semantics |
| SnapTrade webhook receiver | Already the right pattern — push-based updates write to store |
| Schwab webhook (if available) | Same pattern |
| `services/position_snapshot_cache.py` | Already a snapshot abstraction; needs freshness fields |
| `mcp_tools/positions.py` agent format with flags | Already has the structure to surface staleness as a flag |

The data layer is mostly there. What's missing is:
1. The **background worker layer** (sync jobs, scheduling, retry, circuit breakers)
2. The **freshness contract** in the API response shape
3. The **UX for async refresh** (job status, polling/websocket, skeleton UI)
4. The **policy layer** (each consumer's freshness requirements)

---

## Migration Strategy (5 Phases)

The migration is staged so each phase ships independently and is reversible. This is *not* the implementation plan — it's a sketch of what the implementation plan should produce.

### Phase 1 — Freshness Contract (no behavior change)
Add `as_of`, `source_status`, `last_attempt`, `last_error` fields to position responses. Populate from existing cache metadata where it exists, `null` otherwise. Update consumers to honor freshness when present (best-effort). Doesn't change data flow — just exposes what's already implicit.

**Deliverables:** schema migration, response shape change, type definitions, consumer-side optional handling.
**Risk:** low — additive only.
**Unblocks:** Phase 2 has somewhere to write to.

### Phase 2 — Background Sync for One Provider
Pick the worst offender (probably Schwab or IBKR). Build the sync worker pattern: scheduled job, writes to positions store, populates freshness fields, marks status. API server starts reading from store for that one provider. Live-call code path remains as fallback.

**Deliverables:** Celery (or equivalent) worker setup, one provider's sync job, store schema additions, dual-read path with feature flag.
**Risk:** medium — new infrastructure, but isolated to one provider.
**Unblocks:** validates the pattern end-to-end before broad rollout.

### Phase 3 — Migrate Remaining Providers
One at a time. Each migration is independently shippable. Old live-call path is deleted only after all consumers verified.

**Deliverables:** sync jobs for Plaid, SnapTrade, IBKR, CSV. Store-only read path. Live-call code removed.
**Risk:** medium — broader rollout, but proven pattern.

### Phase 4 — Async Refresh UX
`force_refresh` becomes async. Build the UX: job submission returns ID, frontend polls or subscribes via SSE, skeleton state in UI, completion notification. Update agent tools to handle the async pattern (return job ID, recommend `wait_for_sync` follow-up call).

**Deliverables:** job submission/status REST, SSE channel, frontend hooks, MCP tool wrapping.
**Risk:** medium — UX shift, requires user education.

### Phase 5 — Production Hardening
Add circuit breakers, deadline propagation, process isolation for workers, observability dashboards (per-provider freshness, sync success rate, circuit state), alerting.

**Deliverables:** circuit breaker library integration, subprocess workers, Grafana dashboards, alert rules.
**Risk:** low — refinements once architecture is in place.

---

## Open Decisions for the Implementation Plan

These are the decisions a future implementation session needs to resolve before writing the actual plan:

### Worker Infrastructure
- **Celery, RQ, Dramatiq, custom?** Existing repo conventions vs. new infra. Celery is the industry default and has mature time_limit/process-isolation, but it's heavy.
- **Where do workers run?** Same process as API (separate threads), separate process via supervisord, separate container, separate machine?
- **Scheduling — cron-style or interval-based or event-driven?** Webhooks where available, polled fallback elsewhere.

### Store Schema
- **Reuse existing positions cache table** with schema additions, or new table?
- **How to represent partial state?** When 4 of 5 providers are fresh and 1 is stale, what does the read API return?
- **Per-account freshness or per-provider?** Some users have multiple accounts at one broker.
- **Retention?** How long do we keep historical snapshots? (Probably forever for audit, but query patterns matter.)

### Freshness Contract
- **Where in the response shape?** Top-level `meta` block, per-position field, per-provider summary?
- **What's the default freshness requirement** for a consumer that doesn't specify? (Probably "any non-null", but explicit is better.)
- **How does the agent format expose this?** New flag types (`stale_data`, `partial_data`), new snapshot field?

### Backwards Compatibility
- **Feature flag the rollout?** Per-user, per-provider, or global toggle.
- **What about `force_refresh=True` callers?** Sync→async is a contract change. Offer a `wait=True` parameter for transition.
- **MCP tool consumers** — do agents need a new tool, or does the existing one return a job ID?

### Sync Triggers
- **Pure scheduled** (every N minutes), or **on-demand** (user-triggered), or **event-driven** (webhook)?
- Most realistic: **all three**. Webhooks where available (SnapTrade has them, Plaid has them, Schwab unclear), scheduled fallback for everything, on-demand via `force_refresh` enqueue.

### Failure Modes
- **What does the API return** when ALL providers are offline/stale?
- **What's the SLA** for stale data acceptance? (1 hour? 24 hours? Configurable per consumer?)
- **Alerting threshold** — when does ops get paged?

### Observability
- Per-provider sync success rate
- Per-provider freshness P50/P99
- Circuit breaker state per provider
- Worker queue depth per provider
- Stale-data-served counter

### Migration Risk
- **How to validate** the new path matches the old before flipping the flag? Shadow-mode comparison? Canary users?
- **Rollback procedure** if something is wrong?

---

## Why This Matters Beyond the Bug

The current N-of-N reliability model (your uptime = product of all upstream uptimes) is the deeper flaw. Every ambitious feature in your roadmap depends on fixing it:

- **Multi-user / public release** — every request being a live fanout to N brokers doesn't scale. Server thread exhaustion is one bad-day broker outage away.
- **Mobile** — mobile clients can't tolerate 17-minute hangs. They expect either fast responses or graceful staleness.
- **Push notifications / scheduled reports** — these need a reliable read path that doesn't depend on broker liveness.
- **Cross-broker reconciliation** — comparing positions across brokers requires a canonical store, not point-in-time fanout.
- **Backtesting and historical analysis** — already needs a store; right now it's bolted on after the fact.
- **Audit trail / compliance** — positions store with full history is the substrate for "what did the user see at time T?"

The aggregator pattern isn't just a bug fix — it's the architectural precondition for everything else. **Every major fintech eventually builds this.** Doing it now, while the system is still small enough to refactor, is materially cheaper than doing it after launch.

---

## Reference Material

### What other fintechs do
- **Plaid** — pure aggregator pattern. Never blocks on banks. Webhook-driven where possible.
- **Yodlee / Envestnet** — same, with pluggable scrapers as fallback.
- **Mint (RIP)** — scheduled background scraping, freshness shown in UI.
- **Personal Capital / Empower** — webhook + scheduled refresh.
- **Wealthfront / Betterment** — they own the brokerage, so different model, but still cache positions.
- **Robinhood / Carta / Pulley** — internal positions store as source of truth.

### Industry patterns
- **Hystrix** (Netflix, deprecated but conceptually canonical) — bulkheads, circuit breakers, fallbacks.
- **Resilience4j** (Java successor) — same patterns, modular.
- **Envoy** (sidecar proxy) — pushes circuit breaking and timeouts to the network layer.
- **Google "Tail at Scale"** paper — hedging, deadline propagation, why you can't avoid talking about p99.

### Python-specific
- **Celery** with `time_limit` and `--max-tasks-per-child=1` is the realistic implementation path.
- **`asyncio.wait_for`** has the right semantics but doesn't help with sync SDKs (still need `to_thread` which inherits the cancellation problem).
- **`multiprocessing` / `ProcessPoolExecutor`** is the only Python primitive that supports real cancellation (kill the process).

---

## What This Brief Is Not

- **Not an implementation plan.** Producing one is the goal of the next session that picks this up.
- **Not committed scope.** The 5-phase migration is one possible path; the implementation plan may choose a different staging.
- **Not a no-op for the originating bug.** While this is being designed, users can hit the 17-minute hang. Mitigations: (a) take affected providers offline at the connection level, (b) add a low-effort frontend timeout that surfaces a "broker offline" message even though the backend hangs, (c) disable problematic providers in `data_sources`.

---

## Next Session Inputs

When picking this up to produce an implementation plan, bring:
1. This brief
2. `POSITIONS_FETCH_TIMEOUT_PLAN.md` (the tabled patch — useful for what NOT to do)
3. The current state of `services/position_service.py`, `services/position_snapshot_cache.py`, `providers/`, and `data_sources` table schema
4. Any existing webhook receivers (SnapTrade, Plaid, Schwab if it exists)
5. Decisions on the open questions above (worker infra, schema, freshness contract, migration order)

The implementation plan should produce: phased deliverables, schema migrations, file-by-file changes, test strategy, rollout plan, observability spec, rollback procedure.
