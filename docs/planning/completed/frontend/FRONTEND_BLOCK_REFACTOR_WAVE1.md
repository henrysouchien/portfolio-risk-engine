# Wave 1: Block Component Adoption — AssetAllocation + FactorRiskModel

## Context

Phase 1 block components are built (`b7988154`). This is the first refactoring wave — two easy views adopting `GradientProgress` and `PercentageBadge` blocks. No MetricCard or children slot needed yet.

Parent plan: `docs/planning/FRONTEND_BLOCK_REFACTOR_PLAN.md`

## Changes

### 1. AssetAllocation.tsx

**File**: `frontend/packages/ui/src/components/portfolio/AssetAllocation.tsx`

#### 1a. Replace change indicator (lines 286-298)

Current inline pattern — TrendingUp/TrendingDown icon + colored text:
```tsx
<div className="flex items-center space-x-1">
  {allocation.changeType === 'positive' ? (
    <TrendingUp className="w-3 h-3 text-emerald-600" />
  ) : (
    <TrendingDown className="w-3 h-3 text-red-600" />
  )}
  <span className={`text-xs font-medium ${
    allocation.changeType === 'positive' ? 'text-emerald-600' : 'text-red-600'
  }`}>
    {allocation.change}
  </span>
</div>
```

Replace with:
```tsx
<PercentageBadge
  value={parseFloat(allocation.change)}
  showIcon={true}
  variant="inline"
  size="xs"
/>
```

Notes:
- `allocation.change` is a string like `"+2.3%"` or `"-0.8%"`. `parseFloat("+2.3%")` returns `2.3`.
- PercentageBadge handles sign, icon direction, and color automatically from the numeric value.
- `TrendingUp` and `TrendingDown` imports can be removed if no longer used elsewhere in the file.

#### 1b. Replace Progress bar (lines 305-308)

Current:
```tsx
<Progress
  value={allocation.percentage}
  className="h-2"
/>
```

Replace with:
```tsx
<GradientProgress
  value={allocation.percentage}
  colorScheme={colorSchemeFromBg(allocation.color)}
  showPercentage={false}
  size="sm"
/>
```

This requires a local helper to map existing Tailwind `bg-*` classes to colorScheme keys:

```tsx
function colorSchemeFromBg(bgClass: string): "emerald" | "blue" | "purple" | "amber" | "red" | "indigo" | "neutral" {
  if (bgClass.includes("blue")) return "blue"
  if (bgClass.includes("emerald")) return "emerald"
  if (bgClass.includes("amber")) return "amber"
  if (bgClass.includes("purple")) return "purple"
  if (bgClass.includes("orange")) return "amber"  // orange maps to amber
  if (bgClass.includes("red")) return "red"
  if (bgClass.includes("indigo")) return "indigo"
  return "neutral"
}
```

#### 1c. Import changes

Remove (if no longer used elsewhere in file):
```tsx
import { Progress } from "../ui/progress"
import { TrendingUp, TrendingDown } from "lucide-react"
```

Add:
```tsx
import { PercentageBadge, GradientProgress } from "../blocks"
```

Note: `TrendingUp` and `TrendingDown` are NOT used elsewhere in AssetAllocation.tsx — safe to remove. `PieChart` and `BarChart3` are still used.

---

### 2. FactorRiskModel.tsx

**File**: `frontend/packages/ui/src/components/portfolio/FactorRiskModel.tsx`

#### 2a. Replace factor contribution Progress (lines 450-453)

Current:
```tsx
<Progress
  value={Math.abs(factor.contribution)}
  className="h-2"
/>
```

Replace with:
```tsx
<GradientProgress
  value={Math.abs(factor.contribution)}
  colorScheme="purple"
  showPercentage={false}
  size="sm"
/>
```

Color rationale: The Factor Exposure tab uses purple theming (header icon is purple gradient, R² badge is purple). Use `"purple"` for consistency.

#### 2b. Replace risk attribution Progress (line 505)

Current:
```tsx
<Progress value={Math.min(100, Math.abs(item.percentage))} className="h-2" />
```

Replace with:
```tsx
<GradientProgress
  value={Math.min(100, Math.abs(item.percentage))}
  colorScheme="indigo"
  showPercentage={false}
  size="sm"
/>
```

Color rationale: Risk Attribution tab is a separate analytical context. Use `"indigo"` to visually distinguish from the Factor Exposure tab's purple.

#### 2c. Import changes

Remove:
```tsx
import { Progress } from "../ui/progress"
```

Add:
```tsx
import { GradientProgress } from "../blocks"
```

Note: `Progress` is NOT used elsewhere in FactorRiskModel.tsx after these two replacements — safe to remove.

---

## Files Modified

| File | Changes | Blocks Used |
|------|---------|-------------|
| `AssetAllocation.tsx` | Replace change indicator + progress bar | PercentageBadge, GradientProgress |
| `FactorRiskModel.tsx` | Replace 2 progress bars | GradientProgress |

## NOT Changed

- `PerformanceChart.tsx` — deferred (badges are pre-formatted strings, poor PercentageBadge fit)
- No MetricCard usage in Wave 1
- No children slot needed
- No block component modifications

## Verification

1. `cd frontend && pnpm typecheck` — no TypeScript errors
2. `cd frontend && pnpm build` — Vite build succeeds
3. `cd frontend && pnpm eslint packages/ui/src/components/portfolio/AssetAllocation.tsx packages/ui/src/components/portfolio/FactorRiskModel.tsx --ext .ts,.tsx` — no lint errors in modified files
4. Verify removed imports (`Progress`, `TrendingUp`, `TrendingDown`) are not used elsewhere in the modified files
5. Verify `../blocks` import path resolves correctly (barrel export in `blocks/index.ts`)
