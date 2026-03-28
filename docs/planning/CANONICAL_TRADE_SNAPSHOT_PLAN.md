# F12b: Architecture Status

## Status: PAUSED — Dollar Beta Matching supersedes PortfolioState for hedge use case

## What happened

14 Codex review rounds on PortfolioState Phase 1, plus 12 rounds on earlier snapshot fix approaches, converged on an insight: **the hedge sizing model itself is the root cause, not the portfolio snapshot**.

The hedge tool uses `suggested_weight × portfolio_total` to convert factor-beta-derived recommendations into trade legs. This weight percentage is a lossy intermediate representation — it requires a portfolio_total denominator that becomes ambiguous when shorts are present (net vs gross).

**Dollar beta matching** eliminates the denominator entirely:
- Factor service computes `portfolio_dollar_beta = portfolio_value × portfolio_beta`
- Hedge shares = `portfolio_dollar_beta / (hedge_price × hedge_beta)`
- No intermediate weight percentage, no portfolio_total, no net vs gross debate

## What we're doing instead

**F12b-alt: Dollar Beta Hedge Sizing** — change the hedge execute path to compute trade quantities directly from the factor analysis output, bypassing the weight → portfolio_total → dollars conversion. This unblocks existing-short accounts without any PortfolioState changes.

See `DOLLAR_BETA_HEDGE_PLAN.md` (to be created).

## PortfolioState — still valuable, separate project

The PortfolioState architecture (from Codex consultation) is still the right long-term solution for:
- Rebalance tool (needs consistent weights across preview/execute)
- Basket trading (needs consistent portfolio_total)
- `_compute_weight_impact` (needs correct denominator for concentration checks)

But it's NOT needed to unblock the immediate hedge use case. Defer to a separate project when rebalance/basket short support is needed.

## Learnings

- 26+ Codex review rounds across all approaches
- Every weight-percentage-based approach hits the denominator problem
- The denominator problem is inherent to the weight representation, not a bug
- Dollar beta matching is the standard approach in risk models — bypasses the problem entirely
- PortfolioState is an infrastructure improvement, not a hedge-tool fix
