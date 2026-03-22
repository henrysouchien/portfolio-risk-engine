# Add Tooltip to Quality Card Header

## Context

The Quality card shows our 6-signal fundamental quality methodology but doesn't explain what it is. Adding a tooltip to the "Quality" header explains the methodology to users.

## Changes — Single File

**`frontend/packages/ui/src/components/portfolio/stock-lookup/SnapshotTab.tsx`**

Add Info icon + Tooltip to the signal-based "Quality" `<h3>` header only (line 398). The fallback card (line 446) shows ratio-based scoring with different methodology — adding the 6-signal tooltip there would be inaccurate. Same cursor-help pattern used throughout the codebase.

Tooltip text: "Fundamental quality score based on 6 operational signals: revenue growth, cash flow generation, capital investment, margin trends, capital returns, and balance sheet strength. Each signal is pass/fail based on the company's financial statements."

Tooltip imports (`Tooltip`, `TooltipContent`, `TooltipTrigger`) already exist. Two additions needed:
1. Add new import: `import { Info } from "lucide-react"` (no existing lucide import in this file)
2. The Quality card headers are outside the existing `TooltipProvider` (which only wraps the Valuation card). Either wrap each tooltip in its own `<TooltipProvider>` or wrap the entire Quality card section. `TooltipProvider` is already imported.

## Verification

1. `cd frontend && npx tsc --noEmit --project packages/ui/tsconfig.json` — full tsc (only pre-existing errors in unrelated files, none in SnapshotTab)
2. Browser: Research → AAPL → Snapshot tab → hover Quality header on signal card → tooltip appears with methodology description
3. Code review: confirm fallback card header (line 446) does NOT have Info icon or tooltip — only the signal card gets it.
