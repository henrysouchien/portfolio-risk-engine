# V4b — Baseline (Dashboard + Code Reconciliation)

**Date pulled:** 2026-04-27
**Status:** Pre-launch. Spend = development + dogfood traffic only.
**Sources:** Plaid + Anthropic dashboards (current 2026-04-27); SnapTrade dashboard (V4c-tail 2026-04-25); code paths from R1 audit agents.

## §1 Current Monthly Spend (Dashboard Reality)

| Provider | Latest billed month | Amount | Recent trend | Source |
|---|---|---|---|---|
| **Plaid** | March 2026 | $343.45 (incident — Balance polling spike) | Feb $48.10, Jan $14.70, Oct $0.60, Sep $28.10 | dashboard.plaid.com/settings/team/billing |
| **Plaid** (recent normal) | Feb 2026 | $48.10 | Pre-incident baseline ~$15-50/month | same |
| **SnapTrade** | (current month, pay-as-you-go) | TBD when bill closes | $1.50/Connected User/month + $0.05/refresh + $0.002/order call | dashboard.snaptrade.com/settings/billing (V4c-tail) |
| **Anthropic** | Pre-paid credit-grants (API key path) | ~$22/month avg over 9 mo | $196 cumulative grants since Jul 2025 | platform.claude.com/settings/billing |
| **Anthropic** (OAuth path) | Unknown — billed elsewhere | UNDER-COUNTED in this baseline | Production may use OAuth tokens (per `service-mcp` ANTHROPIC_AUTH_MODE convention); spend would land on the user's Claude subscription, NOT the API credit balance | OAuth account billing (not API console) |
| IBKR | $0 marginal | $0 | Rate-limited only, not metered | V4d — confirmed |
| Schwab | $0 marginal | $0 | Free for account holders | V4d — confirmed |
| FMP | Flat-sub | (unchanged) | Subscription only, no per-call | V4d — confirmed |

**Aggregate pre-launch monthly run-rate (excluding incidents): ~$70-90/month** across all paid providers.

## §2 Plaid Contracted Rates (verified 2026-04-27 — match config exactly)

| Product | Rate | Cost model |
|---|---|---|
| Balance | $0.10/call | per_call |
| Investments Refresh | $0.12/call | per_call |
| Transactions | $0.30/connected account/month | per_item_month |
| Investments Holdings | $0.18/connected account/month | per_item_month |
| Investments Transactions | $0.35/connected account/month | per_item_month |
| Liabilities | $0.20/connected account/month | per_item_month |

Master Agreement created April 25, 2025. **No drift from `config/api_budget_costs.py:32-64`.**

## §3 Code-Derived Spend Predictions (R1 findings)

### SnapTrade — `accounts.orders` is the dominant cost lever

`workers/beat_schedule.py:47-52` (orders sync, 5-min default interval) → `workers/tasks/orders.py:59-72` (per-user iteration of all tradeable accounts) → `brokerage/snaptrade/adapter.py:202-208` (one `accounts.orders` call per account).

| Variable | Value |
|---|---|
| Default interval | 300s (5 min) |
| Runs/day per user | 288 |
| Accounts per user (assumed) | 2 |
| `accounts.orders` rate | $0.002/call |
| **Per-user-per-day** | **$1.15** |
| **Per-user-per-month** | **$34.50** |
| **Subscription floor** | **$1.50/Connected User/month** |
| **Excess over subscription** | **22× (~$33/user/month)** |

**Gating**: orders sync only fires if `CELERY_ENABLED=true` AND `ORDERS_VIA_CELERY=true` env vars. Pre-launch env state unknown — lever applies whenever the gate flips on.

### Plaid — subscription cost is dominated by Item count, not call cadence

R1 agent's "freshness gate" lever (#1 in their recommendations) was conceptually wrong — per-Item-month subscription means cadence doesn't multiply cost. **Real Plaid lever:** dead-Item cleanup. `cleanup_stale_data_sources.py:59-69` deactivates DB rows when a user disconnects, but **never calls `item_remove`** (`brokerage/plaid/connections.py:20-56`). The Item stays alive in Plaid's inventory and continues to be billed.

Per-Item-month cost (if all 4 ops triggered): $0.18 + $0.35 + $0.30 + $0.20 = **$1.03/Item/month if dead Item touches all sub ops in any month**.

### Anthropic — token-priced, no caching wired

Single guard call site at `providers/completion.py:403-410`. All callers default to `claude-sonnet-4-6`. No `cache_control` anywhere. Production callers:
- `core/overview_editorial/memory_seeder.py:144` (editorial memory, max_tokens=1200)
- `core/overview_editorial/llm_arbiter.py:145` (editorial arbiter, max_tokens=1600)
- `utils/gpt_helpers.py:36` (interpretation, system prompt "You are a portfolio risk analysis expert.", max_tokens=2000)

Excluded after root-cause review: `utils/gpt_helpers.py:131` (peers helper, max_tokens=200) intentionally stays on OpenAI via `LLM_PROVIDER=openai`; `LLM_PEERS_MODEL` is only an optional model override, not a provider selector.

Pre-launch monthly spend ~$22 — the levers shift the % cost but absolute savings are small until launch.

## §4 Reconciliation Gap (Prediction vs. Reality)

| Provider | Prediction (from code) | Reality (dashboard) | Gap explanation |
|---|---|---|---|
| Plaid | Item-count × per-Item-month rates + Balance call frequency | Feb $48.10 → maps to ~46 Item-months at $1.03 each, OR 481 Balance calls × $0.10. Likely a mix. | Cannot decompose without `api_call_log` query. Confirmed: March $343.45 spike was Balance calls (V4 TODO note). |
| SnapTrade | $34.50/user/month if orders sync enabled, else ~$1.50/user | ~$0 dev (no Connected Users billed yet to my account?) | Agent verified `budget_user_id` wiring; but actual subscription charges depend on whether real users are connected. |
| Anthropic (API-key path) | ~$22/month avg | $22/month avg from credit-grants | Matches FOR API-key callers only. |
| Anthropic (OAuth path) | Token-driven, predicted via `LLMUsage` | Not visible in API console — billed against the OAuth-account's Claude subscription | **Undercount risk**: any caller using OAuth (per `ANTHROPIC_AUTH_MODE=oauth`) does NOT show up in the credit-grant history. Our `api_call_log.estimated_cost_usd` is still correct (token math is the same), but the dashboard reconciliation undercounts unless OAuth-account billing is also pulled. |

**Note**: post-launch validation against `api_call_counters` (V4 PR4 + accumulated traffic) is in scope but not on V4b's critical path. Filed as future validation work in §6.

## §5 Cross-Provider Lever Ranking

Sorted by `$ savings/effort ratio`. Effort: trivial (env var) < small (1-2 days) < medium (3-5 days).

| # | Lever | Provider | Savings (est) | Effort | Plan-PR target |
|---|---|---|---|---|---|
| 1 | **Drop orders sync interval 300s → 1800s (or on-demand only)** | SnapTrade | ~$28/active user/month (if sync enabled) | Trivial — `SYNC_ORDERS_INTERVAL_SECONDS=1800` env var | **V4b.1** |
| 2 | ~~**Wire `item_remove` into stale-data-source cleanup**~~ | ~~Plaid~~ | Shipped 2026-05-04 — admin cleanup now revokes selected Plaid items with stored tokens before local deactivation | Done | ~~**V4b.2**~~ |
| 3 | **Orphan SnapTrade-user cleanup task** | SnapTrade | $1.50/orphan/month | Small — sweep + delete users with no `data_sources` | **V4b.3** |
| 4 | ~~**Haiku downshift for `peers_helper`**~~ | ~~Anthropic~~ | Closed as misfiled 2026-05-04 — peers should remain OpenAI, not Anthropic/Haiku | No action | ~~**V4b.4**~~ |
| 5 | **Wire prompt caching for editorial system prompts + tool schemas** | Anthropic | 25-90% input-token reduction (~$5-15/month current; scales with launch) | Medium — V4e schema is shipped 2026-04-27; needs caller-side `cache_control` wiring | **V4b.5** (V4e schema ready) |
| 6 | ~~**Plaid dead-Item detection from webhooks (PENDING_DISCONNECT, ITEM_LOGIN_REQUIRED)**~~ | ~~Plaid~~ | Patched 2026-05-04 — webhook lifecycle state plus delayed `item_remove` sweep | Done | ~~**V4b.6**~~ |

**Headline**: Lever #1 is the dominant single intervention (env-var change for ~$28/user/month). Levers #2-#3 are housekeeping (small per-instance, accumulative). Levers #4-#6 are launch-scaling preparation.

## §6 Future Work (Explicit, Not Deferred)

Per CLAUDE.md "Don't defer to dodge friction" guidance — items below are NAMED with explicit rationale, not parked-pending-signal.

1. **Post-launch `api_call_counters` validation pass** — once accumulated production traffic exists, query `api_call_counters` (unsampled, Redis-snapshotted) to validate Half §3 predictions. Rationale: needs traffic data that doesn't yet exist; not blocking V4b's lever filing. Filed as **V4b.7**.

2. **Multi-Connection-per-user cost dynamics** — agent assumed 2 SnapTrade accounts/user; real ratio depends on user behavior post-launch. Validate after first 30 days of users. Filed under V4b.7 sub-task.

3. **SnapTrade Connected User definition edge cases** — V4c open questions (mid-month deletion proration, Custom Plan volume breakpoints). Out of V4b scope; track via SnapTrade contact when it matters at scale.

4. **Anthropic OAuth-vs-API auth-mode audit** — confirm which production callers use OAuth (`ANTHROPIC_AUTH_MODE=oauth`) vs API key, and pull the OAuth-account billing for the missing half of Anthropic spend. The token-cost math in `LLMUsage → estimate_cost_usd` is correct regardless of auth mode (tokens × rate is the same), but dashboard reconciliation needs both billing surfaces. Filed as **V4b.8**.

## §7 V4b Status

R0 (this plan), R1 (code analysis), R2 (dashboard pulls), R3 (this baseline + audit), R4 (this lever ranking) → **all complete in this doc**. R5 = file V4b.1–V4b.7 in `docs/TODO.md`. Per-lever PRs (R6+) follow standard plan-first → Codex review → impl pipeline.

This baseline doc consolidates V4B_BASELINE + V4B_AUDIT_<provider> + V4B_PRIORITIZED_LEVERS into one document — pragmatic given pre-launch scale.
