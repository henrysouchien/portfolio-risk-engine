# Code TODO Triage - 2026-05-04

## Scope

Inventory command:

```bash
rg -n "\b(TODO|FIXME)\b" \
  --glob '!docs/**' \
  --glob '!data/**' \
  --glob '!brokerage-connect/dist/**' \
  --glob '!node_modules/**' \
  --glob '!frontend/node_modules/**' \
  --glob '!venv/**' \
  --glob '!*.jsonl' \
  --glob '!*.log'
```

The broad `TODO|FIXME|XXX|HACK` scan was intentionally narrowed because it picked up ticker-like strings such as `CUR:XXX` and the `HACK` ETF symbol.

## Outcome

- Started with 57 source-tree `TODO`/`FIXME` markers outside the `docs/` and generated-data exclusions above.
- Removed or resolved 12 stale/noisy markers in this pass.
- Left 45 markers in place because they describe real feature gaps, external dependency constraints, or historical changelog context.

## Removed Or Resolved In This Pass

| File | Disposition |
|---|---|
| `frontend/packages/chassis/src/services/ClaudeService.ts` | Removed raw streaming `console.log` traces and the stale debug-logging TODO. |
| `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts` | Removed raw stream-chunk `console.log` traces and the stale debug-logging TODO. |
| `frontend/packages/ui/src/pages/InstantTryPage.tsx` | Removed placeholder TODO labels and the unused `_analysisData` placeholder. |
| `frontend/packages/connectors/src/stores/uiStore.ts` | Reframed view-data/error compatibility hooks without TODO markers. |
| `frontend/packages/connectors/src/features/auth/hooks/useAuthFlow.ts` | Implemented `clearViewError()` through `setViewError(viewId, null)` and removed placeholder auth-state TODO labels. |

## Keep As Intentional Constraints

| File | Bucket | Notes |
|---|---|---|
| `requirements.txt` | External dependency | `cryptography==46.0.5` remains pinned above SnapTrade's conservative upper bound; remove note only when SnapTrade loosens its cap. |
| `ibkr/pyproject.toml` | Deferred packaging cleanup | Source/dist convergence is intentionally deferred until there is a forcing function. |
| `CHANGELOG.md` | Historical record | Known-gaps entries remain historical release context, not active code comments. |

## Real Follow-Up Work

| Area | Files | Follow-up shape |
|---|---|---|
| Backend migration/deprecation | `scripts/run_positions.py`, `services/position_service.py`, `core/risk_orchestration.py`, `core/result_objects/whatif.py` | Treat as feature/refactor work. Do not delete comments without the corresponding migration or API decision. |
| Chat architecture | `frontend/packages/chassis/src/services/ClaudeService.ts`, `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts`, `frontend/packages/ui/src/components/chat/shared/ChatCore.tsx`, `frontend/packages/ui/src/components/chat/CHAT_ARCHITECTURE.md` | File upload ownership, backend structured responses, and artifact integration need an implementation slice. |
| Performance/chart data | `frontend/packages/ui/src/components/portfolio/PerformanceChart.tsx`, `frontend/packages/ui/src/components/dashboard/shared/charts/adapters/chartDataAdapters.ts`, `frontend/packages/connectors/src/adapters/RiskAnalysisAdapter.ts` | Replace mock performance data and request missing backend weight/leverage fields. |
| Account connections | `frontend/packages/ui/src/components/settings/AccountConnectionsContainer.tsx` | Backend schema/endpoints for status metadata, logos/account type, per-account sync, and disconnect. |
| Intent handlers and utilities | `frontend/packages/connectors/src/providers/SessionServicesProvider.tsx`, `frontend/packages/connectors/src/features/optimize/hooks/useOptimizationWorkflow.ts`, `frontend/packages/ui/src/components/ui/notification-center.tsx`, `frontend/packages/ui/src/components/ui/command-palette.tsx`, `frontend/packages/ui/src/components/dashboard/shared/ErrorBoundary.tsx` | Export, optimization, scenario, notification, command, and logging integrations remain product work. |

## Next Rule

Only remove a remaining TODO when the matching behavior is implemented, clearly superseded, or moved to a named active backlog item in `docs/TODO.md`.
