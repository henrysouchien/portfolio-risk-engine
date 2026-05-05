# V4d — Provider Rate + Billing-Model Verification (R2 — VERIFIED + SHIPPED 2026-04-25)

> Archived 2026-05-04 under `docs/planning/completed/` after shipped status verification.

## §0 Verified Outcome (R2 addendum)

| Provider / Op | Config (was) | Verified rate | Source | Action |
|---|---|---|---|---|
| `claude-sonnet-4-6` input | $3.50/1M | **$3.00/1M** | claude.com/pricing | UPDATED |
| `claude-sonnet-4-6` output | $18.00/1M | **$15.00/1M** | claude.com/pricing | UPDATED |
| `claude-haiku-4-5` input/output | $1.00/$5.00 | $1.00/$5.00 | claude.com/pricing | confirmed |
| `schwab` `get_account` / `get_accounts` | $0.0200/call | **$0.0000/call** | developer.schwab.com (rate-limit only: 120 req/min GET, 2-4 req/s orders) | UPDATED |
| `ibkr` `reqPositions` / `reqAccountSummary` | $0.0200/call | **$0.0000/call** | ibkr.com/en/trading/ib-api.php + market-data-pricing.php (rate-limit only: 50 msg/sec; cost is market-data subs, not API ops) | UPDATED |
| `fmp` `fetch` / `fmp_estimates` `get` | $0.0000/call | $0.0000/call | site.financialmodelingprep.com/developer/docs/pricing (flat-sub: Basic free / Starter $19 / Premium $49 / Ultimate $99; no premium-endpoint surcharge) | confirmed |

**Code edits**: `config/api_budget_costs.py` updated with verification-date comments inline.

**New gap surfaced (V4e candidate, not part of V4d)**: Anthropic prompt caching (cache writes = 25% of base input rate, cache reads = 10%) and Batch API (50% discount) are NOT representable in current `LLMUsage` schema (`app_platform/api_budget/llm_cost.py:10-14` only tracks `input_tokens`/`output_tokens`). Real Anthropic spend can diverge 15-90% from estimate depending on cache hit rate. Schema additions needed: `cache_creation_tokens`, `cache_read_tokens`, `is_batch` flag. Lower priority than V4a — current Anthropic volume is low.

**IBKR snapshot exception (no action)**: `reqMktData` snapshots cost $0.01/req (US equities) or $0.03/req (other instruments). We use streaming, not snapshots, so no config entry needed unless that changes.

---

---

## §1 Problem (original R1 — preserved for trace)

V4b's billing-model-aware audit (call-frequency vs. Item-count vs. flat-sub vs. tokens) assumes every entry in `config/api_budget_costs.py` has the correct rate AND the correct billing model. V4 (Plaid) and V4c (SnapTrade) already get explicit verification tasks. V4d covers the remaining four: **IBKR, Schwab, FMP, Anthropic**.

Without this, V4b's reduction recommendations are built on starter guesses for 4 of 6 providers.

**Correction to V4d's original framing**: token-priced billing is already representable end-to-end. `LLM_PRICES` (`config/api_budget_costs.py:33-54`) → `estimate_cost_usd(LLMUsage)` (`app_platform/api_budget/llm_cost.py:59-71`) → consumed in `guard.py:72-73` when callers wire `cost_fn=anthropic_usage`. So V4a does NOT need a token-budget dimension — that work is done. The real V4d code-side check is whether Anthropic call sites actually use the correct `cost_fn`.

## §2 Current State (traced)

### Token-pricing wiring — VERIFIED CORRECT
- `LLM_PRICES` keys (config/api_budget_costs.py:46-53): `claude-sonnet-4-6` ($3.50 in / $18.00 out per 1M tokens), `claude-haiku-4-5` ($1.00 / $5.00). Need to confirm vs. current Anthropic public rates.
- Default Anthropic model in code (providers/completion.py:356): `claude-sonnet-4-6` — matches LLM_PRICES key exactly.
- `lookup_model_pricing` does prefix-match fallback (llm_cost.py:53-55) — handles versioned model IDs.

### Anthropic guard call site — VERIFIED CORRECT
- Single guard_call site for Anthropic (providers/completion.py:403-410): wires `cost_fn=anthropic_usage` correctly.
- No bypass paths found via `grep_anthropic + guard_call` audit.

### OpenAI guard call site — VERIFIED CORRECT
- providers/completion.py:238 wires `cost_fn=openai_usage`. Same pattern.

### Per-call schema (config/api_budget_costs.py:17-30) — STARTER VALUES, NOT VERIFIED

| Entry | Current rate | Hypothesis | Verification source |
|---|---|---|---|
| `("ibkr", "reqPositions")` | $0.0200 | Likely $0 marginal — IBKR data API is bundled with TWS/Gateway monthly fee | IBKR public market-data subscription page + your account billing |
| `("ibkr", "reqAccountSummary")` | $0.0200 | Same | Same |
| `("schwab", "get_account")` | $0.0200 | Likely $0 — Schwab Trader API is free/broker-tied, rate-limited not metered | Schwab developer portal terms + your developer account |
| `("schwab", "get_accounts")` | $0.0200 | Same | Same |
| `("fmp", "fetch")` | $0.0000 | Flat subscription — confirm no per-call premium-endpoint surcharge on current plan | FMP pricing page + `account.financialmodelingprep.com` |
| `("fmp_estimates", "get")` | $0.0000 | Same | Same |

### Aggregation pipeline — `today_cost_by_provider` (app_platform/api_budget/cli.py:40-47, routes/admin_api_budget.py:76)
Sums `api_call_log.estimated_cost_usd` GROUP BY provider, last 24h. Per-call rate × count for non-LLM providers; token-priced USD for LLM providers via `estimate_cost_usd`. Both flow into the same column — no schema change needed for token-priced providers.

## §3 Verification Scope per Provider

### IBKR
- **Billing model question**: Is data API per-call, per-message-rate-limit, or bundled in monthly TWS/Gateway fee?
- **Public-doc research**: IBKR Pro account fees, market-data subscription tiers, API documentation rate-limit pages.
- **Dashboard-only**: Your actual account billing — `Account Management → Reports → Activity Statement`. Confirms whether data API calls show as line items or are bundled.
- **Other ops to verify in scope**: `reqHistoricalData`, `reqMktData`, `qualifyContracts` — if billable separately, add entries.
- **Expected outcome**: $0 marginal (bundled) OR per-call rate (verified). Schema impact: likely keep entries but adjust rates.

### Schwab
- **Billing model question**: Is Schwab Trader API metered per-call or rate-limited only?
- **Public-doc research**: Schwab developer portal docs, Trader API pricing terms.
- **Dashboard-only**: Your Schwab developer account — confirm no usage charges, only rate caps.
- **Other ops to verify**: any positions / order endpoints currently called.
- **Expected outcome**: Likely $0 marginal, rate-limited. Schema impact: keep entries at $0 for visibility (call counts still useful), or remove.

### FMP
- **Billing model question**: Confirm flat-subscription on current plan tier; check if any premium endpoints (e.g., institutional ownership, transcripts) have per-call surcharge.
- **Public-doc research**: FMP pricing page (financialmodelingprep.com/developer/docs/pricing), tier comparison.
- **Dashboard-only**: `account.financialmodelingprep.com` — current plan tier, any usage-based add-ons.
- **Expected outcome**: Confirmed flat $0/call OR list of premium endpoints needing separate entries.

### Anthropic
- **Billing model question**: Token rates per current model (claude-sonnet-4-6, claude-haiku-4-5) — confirm `LLM_PRICES` matches public pricing.
- **Public-doc research**: Anthropic pricing page (anthropic.com/pricing).
- **Dashboard-only**: Your Anthropic Console — confirm no per-call fees on top of token billing.
- **Code-side check (DONE in §2)**: Single guard_call site, `cost_fn=anthropic_usage` wired correctly.
- **Expected outcome**: Updated rates in `LLM_PRICES` if drift OR confirmation that current rates match.

## §4 Research Plan — Parallel Execution

**Step 1 (parallel)** — fan out 4 Explore agents, one per provider, for public-doc verification:
- Agent prompt template: "Research current public pricing + billing model for [provider]. Specifically: (a) is [provider]'s [API/data subscription] per-call, per-Item-month, flat-subscription, or token-priced? (b) what are the current contracted rates? (c) are there premium endpoints with separate billing? Return a one-page summary with source URLs and date verified. Under 400 words."
- Agents work independently; ~15-30 min wall time total.

**Step 2 (user, parallel)** — you verify dashboard-only items:
- IBKR: account billing line items
- Schwab: developer portal terms
- FMP: account.financialmodelingprep.com plan tier
- Anthropic: Console for any non-token charges

**Step 3 (Claude)** — reconcile public docs vs. user dashboard findings into a confirmed table.

**Step 4 (Claude → Codex review → Codex impl)** — propose edits to `config/api_budget_costs.py` based on verified rates. Per CLAUDE.md plan-first workflow: any code change goes through Codex review before edit.

## §5 Output Deliverables

1. **Verified rate table** appended to this plan doc (§2 with status: VERIFIED + source).
2. **Updated `config/api_budget_costs.py`** (via Codex implementation) with confirmed rates — or explicit no-op note if rates unchanged.
3. **Schema gap list** for V4a:
   - Token-priced billing: ALREADY HANDLED (no V4a work needed).
   - Subscription-per-Item-month (Plaid): the only real schema gap — V4a's existing scope.
   - Any new gap discovered during verification (e.g., tiered per-call pricing, request-volume discounts).
4. **TODO.md update**: V4d → SHIPPED with verification date, V4a scope confirmed (no token dimension needed).

## §6 Edge Cases & Decisions

1. **$0 marginal entries** — for IBKR/Schwab if confirmed bundled/free: keep entries at $0 (preserves call-count visibility in `api_call_log`) rather than removing. Removing would silence the per-call observability path that V4b's frequency audit needs.
2. **Tiered per-call pricing** — if any provider has volume discounts (e.g., $0.05/call below 10K, $0.03 above), current schema can't represent this. Document as new V4a sub-gap; do not block V4d on it.
3. **LLM_PRICES key drift** — if Anthropic publishes a new model after the verification (e.g., `claude-sonnet-4-7`), prefix-match in `lookup_model_pricing` (llm_cost.py:53-55) handles it via `claude-sonnet-4` prefix. Confirm prefix-match coverage in plan output.
4. **Estimate-only billing models** — Schwab and IBKR may have no public per-call rate at all. Acceptable to leave starter $0.02 with explicit "starter — no public rate available, used for relative comparison only" comment in config file.
5. **Verification date in code** — add inline comment in `config/api_budget_costs.py` next to each entry: `# Verified YYYY-MM-DD against [source]`. Future drift detectable.

## §7 Plan Workflow (per CLAUDE.md)

1. This plan → user approval (R1 ready for review).
2. User approves → Codex review of plan.
3. Codex PASS → Step 1 research agents fan out.
4. Verification table compiled → user reviews.
5. Code changes (if any) drafted → Codex review of impl plan → Codex executes via `mcp__codex__codex`.
6. TODO.md updated → V4d SHIPPED.

No code is edited before Codex review.
