# Implementation Plan – Typed Slot Registry Architecture

_Migrating the Risk-Dashboard front-end to a strongly-typed, registry-based slot system_

---

## 0 · Objectives

1. **Remove legacy fields** – no `risk_results.*` references above the adapter layer.
2. **Single-source data contracts** – canonical `types/*.ts` shared across hooks, adapters, and slots.
3. **Zero prop-plumbing** – introduce a compile-time-checked `SlotConnector` HOC and `slotRegistry`.
4. **Preserve runtime behaviour** – keep TanStack Query caching, SessionManager calls, etc.
5. **Guard-rails** – ESLint + CI rules prevent regressions.

---

## 1 · Work-breakdown & Milestones

| Phase | Goal | Key Tasks | Owner | Target Date |
|-------|------|-----------|-------|-------------|
| 1 | **Type Foundations** | • Add interfaces in `frontend/src/types/`.<br>• Update hook return types (no logic changes). | FE Team | **Week 1** |
| 2 | **Adapter Audit** | • Search & remove `risk_results\.` under `components/` & `features/`.<br>• Patch `adaptVarianceDecompositionData`.<br>• Remove noisy `console.log`. | FE Team | **Week 1** |
| 3 | **SlotConnector & Registry** | • Implement `utils/SlotConnector.tsx`.<br>• Create `registry/slotRegistry.ts` with one wrapped slot.<br>• Add generic `<SlotRenderer>`.<br>• Render old & new side-by-side behind feature flag. | FE Team | **Week 2** |
| 4 | **Progressive Conversion** | Convert remaining slots 1-by-1:<br>add to registry → replace JSX → delete plumbing → update docs. | Rotating | Week 2-3 |
| 5 | **Guard-rails** | • ESLint rule forbids `risk_results.` outside `adapters/`.<br>• CI grep step.<br>• Enable `strictNullChecks` & `noImplicitAny`.<br>• Add adapter unit tests. | Dev Exp | **Week 3** |
| 6 | **Cleanup & Docs** | • Delete manual slot variants.<br>• Run AI doc-sync prompt.<br>• Update onboarding docs. | Tech Writer | Week 4 |
| 7 | **Backend v2 readiness** | Remove legacy parsing from `RiskAnalysisAdapter` once backend flattens schema. | FE + BE | TBD |

---

## 2 · Detailed Task Descriptions

### Phase 1 — Type Foundations
1. **Create `types/analysis.ts`**
   ```ts
   export interface RiskAnalysisData {
     variance_decomposition: { factor_variance: number; idiosyncratic_variance: number };
     correlation_matrix: Record<string, Record<string, number>>;
     risk_contributions: RiskContribution[];
     factor_exposures: Record<'market' | 'value' | 'momentum', FactorExposure>;
     stockExposures: StockExposure[];
   }
   ```
2. Replace every `any` touching risk-analysis data with `RiskAnalysisData`.
3. Run `tsc --noEmit` to list remaining untyped spots.

### Phase 2 — Adapter Audit
```bash
# find bad references
rg "risk_results\." frontend/src/components frontend/src/features
```
Fixes:
* `adaptVarianceDecompositionData` → use `factorData.variance_decomposition`.
* Mark intentional legacy fallbacks with `TODO: remove post-v2`.

### Phase 3 — SlotConnector & Registry
```tsx
// utils/SlotConnector.tsx
export function connectSlot<HookRet extends { data: HD|null; loading: boolean; error: string|null }, HD,
                            SlotProps extends { factorData: SD } & SlotCommonProps, SD>
  (useHook: () => HookRet, adapter: (raw: HD|null) => SD,
   SlotComponent: React.ComponentType<SlotProps>) {
  return function Connected(props: Omit<SlotProps, keyof SlotCommonProps | 'factorData'>) {
    const { data, loading, error } = useHook();
    const slotData = React.useMemo(() => adapter(data as HD | null), [data]);
    // @ts-expect-error factorData is injected
    return <SlotComponent {...props as SlotProps} factorData={slotData} loading={loading} error={error} />;
  };
}
```

```ts
// registry/slotRegistry.ts
import { connectSlot } from '@/utils/SlotConnector';
export const slotRegistry = {
  riskContribution: connectSlot(
    useRiskAnalysis,
    adaptRiskContributionData,
    RiskContributionSlot
  )
} as const;
export type SlotKey = keyof typeof slotRegistry;
```

### Phase 4 — Progressive Conversion
1. Wrap `VarianceDecompositionSlot` → add to registry.
2. Replace in view:
   ```tsx
   <SlotRenderer slots={[ 'riskContribution', 'varianceDecomposition' ]} />
   ```
3. Delete manual prop wiring.
4. Verify visual parity → merge.

### Phase 5 — Guard-rails
`eslintrc.js`
```js
{
  "overrides": [
    {
      "files": ["frontend/src/components/**/*.ts*", "frontend/src/features/**/*.ts*"],
      "rules": {
        "no-restricted-syntax": [ "error",
          { "selector": "Literal[value=/risk_results\\./]", "message": "legacy backend path" }
        ]
      }
    }
  ]
}
```
CI step:
```bash
if grep -R --line-number "risk_results\." frontend/src/components frontend/src/features; then
  echo "Legacy field detected"; exit 1; fi
```

### Phase 6 — Docs & Cleanup
* Run AI “doc-sync” prompt on `components/dashboard/shared/charts/**/*` and `features/**/*`.
* Add “Slot Architecture” page to internal wiki.

---

## 3 · Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Slot refactor breaks charts | Deploy new & old slots side-by-side until validated. |
| Unexpected backend schema change | `RiskAnalysisAdapter` shields UI; adapter unit tests cover output. |
| ESLint rule blocks hot-fix | Allow local override via `/* eslint-disable legacy-backend-path */`. |
| TypeScript strictness slows velocity | Enable `noImplicitAny` first, then `strictNullChecks`. |

---

## 4 · Success Criteria

1. `rg "risk_results\." frontend/src/components frontend/src/features` returns **0** lines.
2. `npm run type-check` passes with strict mode enabled.
3. All slot JSX replaced by `<SlotRenderer>` calls.
4. Adding a new chart requires ≤ 10 lines (slot + registry entry).
5. CI guards prevent re-introduction of legacy fields.

---

## 5 · Timeline Snapshot
```
Week 1  — Type interfaces + Adapter audit
Week 2  — SlotConnector & registry + first chart
Week 3  — Convert remaining slots, add guard-rails
Week 4  — Docs, cleanup, final harden & tag
```

Total effort: **~4 weeks** with 1–2 engineers part-time plus 1 tech-writer in week 4.

---

*Document generated on {{DATE}} by Documentation Sync AI.*