# Planning Cleanup Audit — 2026-03-03

## Scope
Reviewed top-level `docs/planning/*PLAN*.md` files and verified completion against commit/code evidence.

Per request, files currently being edited (modified or untracked in git status) were not audited/moved.

## Completed and Moved to `docs/planning/completed/`

| Plan | Evidence |
|---|---|
| `ACCOUNT_ALIAS_RESOLUTION_PLAN.md` | Commit `f1161d0b` (`fix: canonical account alias resolution across all 7 matching sites`) |
| `AI_INSIGHTS_METRICS_PLAN.md` | Commit `14f795bd` |
| `AI_RECOMMENDATIONS_WAVE3D_PLAN.md` | Commit `aae47747` |
| `DATAFRAME_SERIALIZATION_FIX_PLAN.md` | Commit `f2a48bcc` |
| `FACTOR_PERFORMANCE_TAB_PLAN.md` | Commit `dbcee8c9` |
| `HOLDINGS_ENRICHMENT_WAVE2_5_PLAN.md` | Commit `06e8759b` |
| `MARKET_INTELLIGENCE_WAVE3A_PLAN.md` | Commit `5151dd0a` |
| `NOTIFICATION_CENTER_WIRING_PLAN.md` | Commit `1505c1f1` |
| `PERFORMANCE_ANALYST_DATA_PLAN.md` | Commit `3f14a56b` |
| `PER_POSITION_ALERTS_PLAN.md` | Commit `f3b15bd9` |
| `PROVIDER_ROUTING_GAPS_FIX_PLAN.md` | Commit `66e85369` |
| `SILENT_PROVIDER_FAILURE_PLAN.md` | Commits `1dc1c8b8`, `277cbc40`, `2e76d26f` |
| `SMART_ALERTS_WAVE3B_PLAN.md` | Commit `1dea17ba` |
| `STOCK_ENRICHMENT_REFACTOR_PLAN.md` | Commit `941c92e0` |
| `STOCK_RESEARCH_FMP_WIRING_PLAN.md` | Commits `4ae8115f`, `941c92e0` |
| `STOCK_RESEARCH_WAVE2_6_PLAN.md` | Commit `03f010ea` |
| `WHATIF_SCENARIO_METRICS_PLAN.md` | Commit `937bc9e2` |
| `LIVE_OPTIONS_PRICING_PLAN.md` | Commit `3ed26f80` |
| `PLAID_CUSIP_BOND_PRICING_PLAN.md` | Commit `2baba27f` |
| `WORKFLOW_SKILLS_PLAN.md` | Workflow completion tracked in `completed/TODO_COMPLETED.md` (2026-03-01: all 7 complete) |
| `WORKFLOW_SKILLS_PHASE4_PLAN.md` | Workflow completion tracked in `completed/TODO_COMPLETED.md` (2026-03-01: all 7 complete) |
| `WORKFLOW_SKILLS_STOCK_RESEARCH_PLAN.md` | Workflow completion tracked in `completed/TODO_COMPLETED.md` (2026-03-01: all 7 complete) |
| `PERFORMANCE_MOCK_REMOVAL_PLAN.md` | Commit `52c6d95a` |
| `PRICING_PROVIDER_REFACTOR_PLAN.md` | Refactor completion tracked in `completed/TODO_COMPLETED.md` + Phase 4 docs/tests closed |
| `METRIC_INSIGHTS_WAVE3E_PLAN.md` | Commit `bc107e04` |

## Remaining Active Plans (Status)

| Plan | Status |
|---|---|
| `CASH_REPLAY_P5_VSTART_SEEDING_PLAN.md` | Planned (design complete; no implementation commit tied to this phase yet) |
| `COMPOSABLE_APP_FRAMEWORK_PLAN.md` | Draft |
| `FLOW_DATE_SNAPPING_FIX_PLAN.md` | Planned |
| `FRONTEND_COMPONENT_BLOCKS_PLAN.md` | Planned |
| `FRONTEND_REDESIGN_PLAN.md` | Planned |
| `FRONTEND_SDK_PLAN.md` | Draft |
| `PER_SYMBOL_INCEPTION_PLAN.md` | Planned |
| `REMOVE_INCEPTION_NAV_FILTER_PLAN.md` | Planned |
| `SYNTHETIC_INCEPTION_FLOW_FIX_PLAN.md` | Planned |
| `SYNTHETIC_TWR_FLOW_FIX_PLAN.md` | Planned |
| `TRANSACTION_STORE_PLAN.md` | In progress |
| `TWR_TINY_BASE_DEFERRAL_PLAN.md` | Planned |

## Skipped (Currently Being Edited)

These were intentionally excluded from this cleanup pass:

- `ACCOUNT_INSTITUTION_FILTERING_PLAN.md`
- `completed/PER_POSITION_RISK_SCORE_PLAN.md`
- `SCHWAB_RECEIVE_DELIVER_FIX_PLAN.md`
- `SYNTHETIC_TWR_PRICE_ALIGNMENT_HANDOFF.md`
- `SYNTHETIC_TWR_PRICE_ALIGNMENT_PLAN.md`
