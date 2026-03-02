# Plan: Frontend Component Block Library

## Context

The frontend UI package has a gap between its 49 low-level shadcn/ui primitives (`/components/ui/`) and its 14 large monolithic portfolio views (`/components/portfolio/`, 60-100KB each). The views inline repeated patterns — metric cards, section headers, sparklines, progress bars, percentage badges — that appear 10-25+ times across views but aren't extracted as reusable components.

This plan creates a `/components/blocks/` directory containing self-contained, typed, presentation-only "block" components that sit between primitives and views. No existing views are refactored — blocks are additive only. Views can adopt them incrementally later.

## Architecture

```
components/
  ui/           ← 49 shadcn primitives (atoms)
  blocks/       ← NEW: 13 block components (molecules)
  shared/       ← 4 utility components (loading, error, status)
  portfolio/    ← 14 view files (organisms/pages) — NOT touched
```

## Phase 1: HIGH Priority Blocks (5 components)

Build in this order (simplest → most complex):

### 1. `percentage-badge.tsx`
Color-coded percentage with sign and optional arrow icon. Appears 15+ times across views.

```typescript
interface PercentageBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  value: number;
  decimals?: number;           // default 2
  showSign?: boolean;          // default true
  showIcon?: boolean;          // arrow up/down icon
  size?: "xs" | "sm" | "md" | "lg";
  variant?: "inline" | "badge"; // inline text vs pill background
  forceColor?: "positive" | "negative" | "warning" | "neutral";
  neutralThreshold?: number;   // default 0.01
}
```

### 2. `gradient-progress.tsx`
Labeled progress bar with gradient fill and percentage text. Wraps existing Radix Progress. Appears 12+ times.

```typescript
// Renders ProgressPrimitive.Root directly (not wrapping the existing Progress component)
// to allow full control over the Indicator's className for gradient colors.
interface GradientProgressProps extends React.ComponentPropsWithoutRef<typeof ProgressPrimitive.Root> {
  value: number;               // 0-100
  label?: string;
  showPercentage?: boolean;
  colorScheme?: "emerald" | "blue" | "purple" | "amber" | "red" | "indigo" | "neutral";
  autoColor?: boolean;         // red < 33, amber < 66, emerald >= 66
  size?: "sm" | "md" | "lg";
}
```

### 3. `section-header.tsx`
Icon with gradient background + title + subtitle + optional badge/actions. Appears 8+ times.

```typescript
interface SectionHeaderProps extends React.HTMLAttributes<HTMLDivElement> {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  subtitle?: string;
  colorScheme?: "emerald" | "blue" | "purple" | "amber" | "red" | "indigo" | "neutral";
  badge?: React.ReactNode;
  actions?: React.ReactNode;
  size?: "sm" | "md" | "lg";  // icon container size
}
```

### 4. `sparkline-chart.tsx`
Mini SVG area chart with gradient fill. Pure SVG, no Recharts. Appears 20+ times.

```typescript
interface SparklineChartProps extends React.HTMLAttributes<HTMLDivElement> {
  data: number[];
  colorScheme?: "emerald" | "blue" | "purple" | "amber" | "red" | "indigo" | "neutral";
  showFill?: boolean;          // gradient fill under line
  showDots?: boolean;          // dots on hover
  strokeWidth?: number;        // default 2
  height?: number;             // px, default 40
  animate?: boolean;
}
```

Uses `React.useId()` for unique SVG gradient IDs (avoids collision). Guard against short arrays (`data.length < 2` → render nothing or flat line). View-specific features (volatility, isLive, correlations from PortfolioOverview) are intentionally excluded — this block captures the core sparkline pattern only.

### 5. `metric-card.tsx`
Status-colored card with icon, label, value, change indicator, badge. Most complex — may compose SparklineChart and PercentageBadge. Appears 25+ times.

```typescript
interface MetricCardProps extends React.HTMLAttributes<HTMLDivElement> {
  icon?: React.ComponentType<{ className?: string }>;
  label: string;
  value: string;               // pre-formatted ("$1.2M", "1.67")
  description?: string;        // descriptive text below value (e.g. "vs. previous day")
  change?: string;             // change text (e.g. "+12.8% YTD", "Medium Risk", "Excellent")
  changeType?: "positive" | "negative" | "warning" | "neutral";
  badge?: React.ReactNode;     // ReactNode — supports string, JSX badges, or multiple badges
  colorScheme?: "emerald" | "blue" | "purple" | "amber" | "red" | "indigo" | "neutral";
  subtitle?: string;
  isLoading?: boolean;
  sparklineData?: number[];    // optional mini chart
}
```

Uses CVA for `colorScheme` variant mapping.

## Phase 2: MEDIUM Priority Blocks (8 components)

After Phase 1 is stable:

| Component | Props Summary | Source Pattern |
|-----------|--------------|----------------|
| `status-badge.tsx` | `severity, label, size, pulse` | Extends Badge with error/warning/info/success presets |
| `data-table.tsx` | `columns[], data[], sortKey, onSort, onRowClick` | Generic typed sortable table from HoldingsView |
| `conditional-text.tsx` | `value, invert, neutralThreshold, bold` | Colored span by positive/negative |
| `risk-indicator.tsx` | `level, label, score, showDot` | 3-level dot + label from RiskAnalysis |
| `comparison-pair.tsx` | `primaryLabel/Value, secondaryLabel/Value, diff, diffType` | Portfolio vs benchmark side-by-side |
| `collapsible-panel.tsx` | `title, defaultOpen, icon, badge, children` | Wraps Radix Collapsible |
| `key-value-display.tsx` | `label, value, direction, size` | Horizontal/vertical label:value pair |
| `contributor-row.tsx` | `rank, symbol, name, weight, contribution, returnPct, type ("contributor"\|"detractor"), badge?, subtitle?, expandContent?` | Contributor/detractor row card from PerformanceView. Core row structure only — view-specific decorations (analyst ratings, AI insights) remain in views. |

## File Structure

```
frontend/packages/ui/src/components/blocks/
  index.ts                  ← barrel export
  metric-card.tsx           ← Phase 1
  section-header.tsx        ← Phase 1
  sparkline-chart.tsx       ← Phase 1
  gradient-progress.tsx     ← Phase 1
  percentage-badge.tsx      ← Phase 1
  status-badge.tsx          ← Phase 2
  data-table.tsx            ← Phase 2
  conditional-text.tsx      ← Phase 2
  risk-indicator.tsx        ← Phase 2
  comparison-pair.tsx       ← Phase 2
  collapsible-panel.tsx     ← Phase 2
  key-value-display.tsx     ← Phase 2
  contributor-row.tsx       ← Phase 2
```

## Wiring

1. `blocks/index.ts` exports all components + prop types
2. `components/index.ts` adds `export * from './blocks'`
3. Available as `import { MetricCard } from '@risk/ui'`

## Conventions (from existing codebase)

- Import `cn` from `@risk/chassis`
- Use CVA for multi-variant components (per `button.tsx`, `badge.tsx`)
- Use `React.forwardRef` for components wrapping Radix primitives or that need ref forwarding (per `card.tsx`, `progress.tsx`). Simple presentational components can use plain functions (per `badge.tsx`).
- Set `.displayName` on forwardRef components
- Accept `className` prop, merge via `cn()`
- Use Tailwind color families for `colorScheme` prop: emerald, blue, purple, amber, red, indigo, neutral
- For risk-level coloring, reference semantic tokens from `theme/colors.ts` (`riskColors.excellent/good/poor`, `componentColors.success/warning/danger`) where appropriate — the `colorScheme` prop maps to Tailwind classes, but risk-specific helpers like `getRiskColor(score)` should be used for score-based coloring
- Export both component and props type
- Icons passed as `React.ComponentType<{ className?: string }>` — blocks don't import icons directly
- Do NOT modify existing `MetricsCard` in `dashboard/shared/ui/`

## Critical Source Files

These files contain the inline patterns being extracted. Codex should read them to match the existing visual style:

- `frontend/packages/ui/src/components/ui/badge.tsx` — CVA variant pattern to follow
- `frontend/packages/ui/src/components/ui/card.tsx` — forwardRef + cn() pattern to follow
- `frontend/packages/ui/src/components/ui/progress.tsx` — Radix Progress to wrap for GradientProgress
- `frontend/packages/ui/src/components/portfolio/PortfolioOverview.tsx` — MetricCard, SparklineChart, SectionHeader source patterns (lines 894-1400)
- `frontend/packages/ui/src/components/portfolio/PerformanceView.tsx` — MetricCard, SectionHeader, GradientProgress source patterns
- `frontend/packages/ui/src/theme/colors.ts` — Risk color tokens
- `frontend/packages/ui/src/components/index.ts` — Wire barrel export here

## Verification

1. `pnpm typecheck` — no TypeScript errors
2. `pnpm lint` — no ESLint errors
3. `pnpm build` — Vite build succeeds
4. Visual check: import a block component into an existing view and render it alongside the existing inline pattern to confirm they match
