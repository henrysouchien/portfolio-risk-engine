# Fix: Replace CSS Grid Allocation Table with Table Component

> **Codex review**: R1 FAIL (2). **R2 PASS.**

## Context

The allocation table in WhatIfTool.tsx uses CSS grid (`grid-cols-[...]`) with hardcoded column widths for each row independently. This makes alignment between headers and data impossible to get right — every pixel tweak attempt fails because grid rows don't share column sizing.

Meanwhile, every other table in this tool (Position Changes, Risk Limit Checks, Factor Exposures) uses the `Table`/`TableHeader`/`TableBody`/`TableRow`/`TableHead`/`TableCell` components from `../../ui/table`. These render actual `<table>` HTML elements where the browser automatically aligns columns across all rows. They all look perfectly aligned.

## Fix

Replace lines 843-905 of `WhatIfTool.tsx` — the CSS grid header + data rows — with the same `Table` component pattern used by `PositionChangesSection.tsx:73-99`.

**Before** (CSS grid, broken alignment):
```tsx
<div className="grid grid-cols-[minmax(0,1fr)_4.5rem_4.5rem_2rem] gap-4 bg-muted ...">
  <div>Ticker</div>
  <div className="text-right">Current</div>
  ...
</div>
<div className="divide-y divide-border">
  {entries.map(([ticker, value]) => (
    <div className="grid grid-cols-[minmax(0,1fr)_4.5rem_4.5rem_2rem] ...">
      <Input ... />
      <div className="text-right">2.1%</div>
      <Input ... />
      <Button>×</Button>
    </div>
  ))}
</div>
```

**After** (Table component, auto-aligned):
```tsx
<Table>
  <TableHeader className="bg-muted/30">
    <TableRow className="hover:bg-transparent">
      <TableHead className="px-4 text-[11px] uppercase tracking-[0.18em]">Ticker</TableHead>
      <TableHead className="px-4 text-right text-[11px] uppercase tracking-[0.18em]">Current</TableHead>
      <TableHead className="px-4 text-right text-[11px] uppercase tracking-[0.18em]">
        {inputMode === "weights" ? "Target" : "Delta"}
      </TableHead>
      <TableHead className="w-10 px-2" />
    </TableRow>
  </TableHeader>
  <TableBody>
    {entries.map(([ticker, value]) => (
      <TableRow key={ticker}>
        <TableCell className="px-4">
          <Input value={ticker} ... className="h-8 border-border bg-card" />
        </TableCell>
        <TableCell className="px-4 text-right text-sm text-muted-foreground">
          {currentWeight}%
        </TableCell>
        <TableCell className="px-4">
          <Input ... className="h-8 border-border bg-card text-right" />
        </TableCell>
        <TableCell className="w-10 px-2">
          <Button variant="ghost" size="icon" ...>×</Button>
        </TableCell>
      </TableRow>
    ))}
  </TableBody>
</Table>
```

Key details:
- Import `Table, TableBody, TableCell, TableHead, TableHeader, TableRow` from `../../../ui/table` (WhatIfTool.tsx imports UI primitives from `../../../ui/*`, see lines 18-22)
- Use the EXACT same header styling as PositionChangesSection: `text-[11px] uppercase tracking-[0.18em]` — matching the right-side tables
- Keep `max-w-[10rem]` on the ticker Input to prevent long tickers (e.g., "CPPMF") from blowing out the column. Table columns size from cell content, not just headers — the `Input` component is `w-full` by default (`input.tsx:11`), so without a max-width constraint, the ticker input could stretch the column
- `w-10` on the × column header constrains the remove button column
- Empty state row uses `<TableRow><TableCell colSpan={4}>...</TableCell></TableRow>`
- The `overflow-hidden rounded-2xl border` wrapper div stays as-is (same as PositionChangesSection)

## Files

| File | Change |
|------|--------|
| `WhatIfTool.tsx` lines 843-905 | Replace CSS grid with Table component |

## Verification

1. `cd frontend && pnpm exec tsc --noEmit`
2. `cd frontend && pnpm exec vitest run packages/ui/src/components/portfolio/scenarios/tools/__tests__/WhatIfTool.test.tsx`
3. Browser: headers automatically align with values — no pixel tweaking. Matches visual style of right-side tables.
