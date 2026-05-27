> **✅ SHIPPED — V4b R1+R2+R3 reduction shipped. Moved during 2026-05-26 docs cleanup.**

# V4b — Billing-Model-Aware Cost Reduction Audit (R2)

## §1 Problem

The cost-guard now writes accurate dollar attribution per billing model (V4a P3 shipped 2026-04-26 `483374be`, P4 closed 2026-04-26 `d532cc8e`). V4b uses that accurate attribution to find and remove waste.

**R1 → R2 pivot:** R1 assumed `api_call_log` 30-day SQL queries would baseline current spend. Investigation surfaced (a) the system is pre-launch (no prod traffic data exists), (b) `api_call_log` is sampled 10% with 30-day retention — designed for forensics, not billing rollups, (c) `api_call_counters` (Redis-snapshotted, unsampled) IS the right table but is also empty in dev. Per the updated CLAUDE.md "Don't defer to dodge friction" guidance, "wait for usage signal" is forbidden — V4b proceeds without traffic data, sourcing truth from **dashboards + code**.

## §2 Source-of-Truth Layout (R2)

| Source | Authority for | Access |
|---|---|---|
| **Vendor dashboards** (Plaid / SnapTrade / Anthropic Console) | **Reality** — current-month bill, active Items/Users, token volume | User logs in via Chrome MCP (Plaid + Anthropic), or read-only on already-known SnapTrade data (V4c-tail pull) |
| **`workers/beat_schedule.py` + per-provider sync code** | **Prediction** — given N active users at interval I, predicted $/day per provider | Code analysis (this session) |
| **`item_remove` callsite + user-deletion paths** | **Lever 1** — is dead-Item / dead-User cleanup wired to any trigger? | Code grep (this session) |
| **`providers/completion.py` `cache_control` usage** | **Lever 2** — Anthropic prompt-caching gap; sizes V4e impact | Code grep (this session) |
| `api_call_counters` (post-launch, future) | Validation — actuals vs. predictions | Defer to post-launch; do NOT block V4b on it |

V4a P3's correct dollar attribution + the dashboard reality + code-derived predictions = enough to size every lever V4b cares about.

## §3 What V4a P3 Locked In

`get_cost_model_and_rate(provider, operation)` (`config/api_budget_costs.py:97-111`) returns one of:
- `('per_call', rate)` — Plaid Balance/Investments-Refresh, SnapTrade Manual Refresh/Recent Orders, IBKR/Schwab (now $0), FMP ($0)
- `('per_item_month', rate)` — Plaid Holdings $0.18, Inv-Tx $0.35, Tx $0.30, Liabilities $0.20
- `('per_connected_user_month', rate)` — SnapTrade $1.50/user covers 16 of 18 wrapped ops
- LLM providers: handled separately via `LLMUsage` → `estimate_cost_usd` → token math

This is the per-op rate book. V4b consumes it; no further attribution work needed.

## §4 Audit Scope (per billing model)

### Per-call providers — audit polling cadence + redundancy
- **Plaid Balance** ($0.10/call) and **Investments Refresh** ($0.12/call): how often are they called per user per day? Triggered by user action or background sync? Caching opportunity?
- **SnapTrade Manual Refresh** ($0.05/call): does anything auto-trigger this, or only user-initiated?
- **SnapTrade Recent Orders** ($0.002/call): if orders sync runs at 5min default per user, that's 288 calls/user/day = $0.58/user/day = **$17.30/user/month** for orders alone — already higher than the $1.50 Connected User subscription. This is the highest-impact lever.
- **Anthropic** (token-priced): token volume per use case + missing prompt caching = V4e gap.

### Per-Item-month subscription (Plaid Holdings, Inv-Tx, Tx, Liabilities)
- **Dead-Item census**: Items charged a subscription but with no calls = pure waste at $0.18-$0.35/Item/month.
- **Auto-cleanup wiring**: does `item_remove` (`brokerage/plaid/connections.py:20-56`) get called from any deactivation path, or do dead Items accumulate forever?
- **User-initiated lifecycle**: when a user disconnects a Plaid Item, is the subscription stopped immediately?

### Per-Connected-User subscription (SnapTrade $1.50)
- **Dead-User census**: SnapTrade Connected Users billed but with no recent activity.
- **Test users on prod billing**: any leaked test/throwaway users?

### Flat-subscription (FMP)
**SKIP for cost.** Note any near-tier-cap concerns separately; not a $-savings lever.

## §5 Output Deliverables

1. **`docs/planning/V4B_BASELINE.md`** — dashboard-pulled current-month bills (Plaid + SnapTrade + Anthropic) + code-derived spend predictions per provider, with reconciliation gap analysis.
2. **`docs/planning/V4B_AUDIT_<provider>.md`** — Plaid, SnapTrade, Anthropic. Each one-page, with:
   - Current monthly spend (from dashboard)
   - Code-derived spend prediction (cadence × users × rates)
   - Top reduction levers ranked by $-saved/effort
3. **`docs/planning/V4B_PRIORITIZED_LEVERS.md`** — cross-provider rollup, sorted by `$savings/effort`.
4. **TODO.md** — file each high-priority lever as V4b.1 / V4b.2 / … sub-tasks (`ACTIONABLE — NEEDS PLAN`). Each follows standard plan-first → Codex review → impl.

## §6 Sequencing

| Phase | Work | LoC | Gate |
|---|---|---|---|
| **R0** | This plan (R2 → user → start work) | 0 (docs) | User approval |
| **R1** | Code analysis — 4 parallel Explore agents (Plaid path, SnapTrade path, Anthropic path, cleanup-wiring grep) | ~150 (docs aggregating findings) | none — research |
| **R2** | Dashboard pulls — Plaid (Chrome login), SnapTrade (already pulled, refresh if stale), Anthropic Console (Chrome login) | ~50 (docs) | none — read-only |
| **R3** | Reconciliation + per-provider audit docs | ~150 each (docs) | `/codex review` each audit doc — sanity-check savings math |
| **R4** | Cross-provider `V4B_PRIORITIZED_LEVERS.md` | ~50 (docs) | none — derived |
| **R5** | File V4b.1 / V4b.2 / … in TODO.md | ~30 (docs) | none |
| **R6+** | Each high-priority lever → standard plan-first → Codex review → impl PR | varies | per-PR |

V4b "complete" condition: R0–R5 shipped (audit done, levers prioritized, sub-tasks filed). Implementing levers is downstream V4b.N work.

## §7 Edge Cases & Decisions

1. **Pre-launch state**: V4b operates on predicted spend (code analysis) reconciled against vendor dashboard reality. Post-launch validation against `api_call_counters` is **future work** but explicitly NOT a V4b dependency. Documented per CLAUDE.md "Don't defer" guidance — this is "in scope, not in this plan" framing for the validation step.

2. **Active-user count input**: cadence predictions need "N active users". Source: `users` table query for users with at least one connected provider (Plaid Item or SnapTrade Connected User). Will be small (pre-launch) — that's fine, the per-user $/day forecast scales linearly.

3. **Recent Orders attribution**: confirm during R1 that `accounts.orders` is wired through the orders-sync task and writes `cost_model='per_call'` rows (verifying V4a P3 attribution rather than blocking on traffic).

4. **`cache_control` already absent**: confirmed in earlier investigation — zero references in `providers/completion.py`. R1 quantifies the impact (which prompts are repeated calls = high cache hit potential), not whether the feature is missing.

5. **SnapTrade dashboard data freshness**: V4c-tail (yesterday) pulled rates. R2 only re-pulls if user count or active connections have changed. Not a fresh dashboard sweep.

6. **Audit-doc Codex review**: only at R3 (per-provider audit math sanity-check), not at R0 (this plan) or R1 (raw code findings). Lever-impl PRs (R6+) get full plan-first → Codex review.

## §8 Plan Workflow

This plan is research/audit scope (no code edits). Proceed to R1 immediately upon user approval. Codex review at R3 (audit-math sanity-check) and per-lever in R6+.

R1 fanout: 4 parallel Explore agents kick off simultaneously, ~30-min wall time.
