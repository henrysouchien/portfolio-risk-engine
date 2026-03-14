# Backlog

**STATUS:** REFERENCE

## UI Blocks: Structured Layouts & Stretch Goals

**Priority:** Medium
**Added:** 2026-03-07 | **Updated:** 2026-03-12

Phase 0-3 Dynamic UI Generation + Phase 4 Artifact Mode are **DONE** (commits `694b8c2c`→`a538ff65`, `f9a728e2`). `ArtifactPanel` 480px slide-out, auto-open on stream, Escape/X/View toggle.

**Remaining stretch goals:**
- Layout templates — predefined named patterns (`risk-dashboard`, `position-report`) for consistent output
- Scrollable/collapsible sections for long block sequences
- Save/export rendered artifacts
- Block interactivity beyond CTA buttons (sort tables, toggle chart views)

## Investigate Schwab provider alternatives (SnapTrade or Plaid)

**Priority:** Medium
**Added:** 2026-03-02

The direct Schwab API OAuth token expires every 7 days and requires manual re-auth via browser flow (`python3 -m scripts.run_schwab login --manual`). The `schwab-py` library (v1.5.1) also now restricts `client_from_login_flow` to `127.0.0.1` callback URLs only.

**Evaluate:**
1. Does SnapTrade support Schwab accounts with transaction history?
2. Does Plaid already have Schwab transaction data (we have Plaid connected)?
3. Compare data quality/coverage vs direct Schwab API (currently 346 cached transactions, normalizer handles cash-direction fallback + income two-pass resolution)

**Goal:** Eliminate manual 7-day re-auth cycle while maintaining transaction data quality.

## PostgreSQL Connection Pool — Root Cause Investigation

**Priority:** Medium
**Added:** 2026-03-09 | **Updated:** 2026-03-12

Cascading failure fix **DONE** (`2dca72fd`). Plan: `completed/infrastructure/PG_POOL_EXHAUSTION_FIX_PLAN.md`.

Remaining: investigate root cause of connection leak that triggers pool exhaustion in the first place. The cascading failure fix prevents crashes but doesn't fix the leak itself.

## IBKR Statement Trade Backfill (Optional)

**Priority:** Low (IBKR gap already at 0.48pp without backfill)
**Added:** 2026-03-05 | **Updated:** 2026-03-08
**Plan:** `IBKR_STATEMENT_BACKFILL_PLAN.md`

Would improve IBKR data coverage from 57% to ~95% by ingesting pre-Flex-window
trades from materialized IBKR statement SQLite files. With the gap already at
0.48pp, this is a nice-to-have for data coverage completeness rather than a
return accuracy fix.
