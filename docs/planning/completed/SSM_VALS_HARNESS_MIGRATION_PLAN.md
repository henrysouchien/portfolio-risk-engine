> **✅ SHIPPED — SSM Vals harness migration shipped. Moved during 2026-05-26 docs cleanup.**

# SSM Vals Harness Migration Plan

## Status

Not started - placeholder for future scope.

## Motivation

`docs/planning/SSM_APP_SECRETS_MIGRATION_PLAN.md` scoped out the
`evals/vals-finance-agent/` harness because it is operator-launched bash tooling,
not a production Python entry point. A future plan should decide whether the
harness should keep sourcing local env files or gain a small SSM-aware bootstrap
wrapper.

