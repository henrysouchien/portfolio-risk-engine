# Codex Spec: Factor Risk Model Card CSS Fix (T2 #29)

**Goal:** Fix fixed height truncation and sloppy hover outline on Factor Risk Model card.

---

## Step 1: Remove fixed card height

**File:** `frontend/packages/ui/src/components/portfolio/FactorRiskModel.tsx`

**Line 300:** Change `h-[600px]` to `min-h-[400px]`

```
// Before:
<Card className={`w-full h-[600px] flex flex-col ...`}>

// After:
<Card className={`w-full min-h-[400px] flex flex-col ...`}>
```

This lets the card expand to fit content while maintaining a minimum height.

## Step 2: Increase ScrollArea height (keep explicit)

**Same file, line 420:** Change `h-[300px]` to `h-[400px]`

```
// Before:
<ScrollArea className="h-[300px]">

// After:
<ScrollArea className="h-[400px]">
```

**Why explicit height is required:** The Radix `ScrollArea` viewport (`scroll-area.tsx` line 15) uses `h-full w-full`, which resolves against the Root element's computed height. Using `max-h-*` or removing the height entirely causes the viewport to collapse to zero because `h-full` has no parent height to resolve against. The fix is to keep an explicit height but increase it from 300px to 400px so the Risk Attribution list has enough room.

## Step 3: Fix hover outline on factor cards

**Same file, line 354:** Replace shadow-only hover with border-based hover

```
// Before:
className="p-4 border border-neutral-200/60 rounded-xl bg-gradient-to-r from-white to-neutral-50/50 hover:shadow-md transition-all duration-200"

// After:
className="p-4 border border-neutral-200/60 rounded-xl bg-gradient-to-r from-white to-neutral-50/50 hover:border-purple-300 hover:shadow-sm transition-all duration-200"
```

Changes: `hover:shadow-md` to `hover:border-purple-300 hover:shadow-sm` (cleaner border-based focus indicator using the component's accent color).

## Verification

```bash
cd frontend && npx tsc --noEmit
```

Visual check: Factor Risk Model card should expand to fit all factors, Risk Attribution tab scrolls with more visible area, and factor cards have a clean purple border on hover.

## Summary

1 file, 3 line changes. Pure CSS — no logic changes.
