# SSM AI Excel Addin Migration Plan

## Status

Not started - placeholder for future scope.

## Motivation

`docs/planning/SSM_APP_SECRETS_MIGRATION_PLAN.md` moved risk_module app
secrets into SSM, but intentionally left AI-excel-addin-specific keys out of
scope. A future plan should decide the addin namespace, IAM boundary, backup
process, and bootstrap mechanism before those secrets move.

