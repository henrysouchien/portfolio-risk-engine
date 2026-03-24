# C1: Remove Per-Message AI Chat Action Buttons

**Status**: TODO
**Created**: 2026-03-24
**Reviewed**: Codex round 1 — FAIL (5 findings), round 2 — FAIL (2 findings), all addressed below
**File**: `frontend/packages/ui/src/components/chat/shared/ChatCore.tsx`

## Context

The AI chat appends keyword-matched action buttons (e.g. "View Risk Details", "Portfolio Overview") to every AI response >100 chars. These are naive heuristic matches — any mention of "risk" triggers a button. They add clutter without value. The welcome message starter prompts (4 hardcoded buttons shown when no messages exist) should be kept.

Complication: the Regenerate/Retry buttons are currently nested inside the same `actionable && actions` guard as the per-message action buttons. Removing action generation would also hide Regenerate/Retry. Fix: move Regenerate/Retry out of that guard, with proper scoping.

## Changes

### 1. Delete `shouldAddActions()` (lines 350-361)

Remove the function and its JSDoc comment entirely. It's a naive `content.length > 100` heuristic.

### 2. Delete `generateActionsForMessage()` (lines 363-398)

Remove the function and its JSDoc comment entirely. It keyword-matches "risk", "portfolio", "performance", "factor" and maps each to a hardcoded button.

### 3. Remove action generation from message processing (lines 558-559)

Change:
```tsx
actionable: !msg.uiBlocks && shouldAddActions(msg.content),              // Skip heuristic actions when blocks present
actions: !msg.uiBlocks ? generateActionsForMessage(msg.content, msg.role || 'assistant') : undefined,
```
To:
```tsx
actionable: false,
actions: undefined,
```

This keeps the welcome message (lines 531-548) untouched — it sets `actionable: true` and `actions: [...]` directly.

### 4. Update `useMemo` dependency comment (line 524)

Change:
```tsx
// (Functions like parseMessageType, shouldAddActions are pure and don't need to be dependencies)
```
To:
```tsx
// (Functions like parseMessageType are pure and don't need to be dependencies)
```

### 5. Restructure action button rendering block (lines 1108-1158)

Move Regenerate/Retry buttons **outside** the `message.actionable && message.actions` guard so they render independently. The action buttons container becomes welcome-message-only.

**Guards for moved buttons:**
- **Regenerate**: Add `message.id !== "welcome"` guard — the welcome message is a synthetic assistant message; `regenerate()` is a no-op when there are no real messages. Without this guard, Regenerate would appear on the welcome screen doing nothing.
- **Retry**: Keep existing `message.role === 'user'` guard. Retry was previously only visible on user messages that happened to match the action keyword heuristic. Making it visible on ALL user messages is the correct UX — users should always be able to retry any message they sent.

Before:
```tsx
{message.actionable && message.actions && (
  <div>
    {message.actions.map(...)}     // action buttons
    {status === 'ready' && (       // Regenerate/Retry — trapped inside
      ...
    )}
  </div>
)}
```

After:
```tsx
{message.actionable && message.actions && (
  <div className="flex flex-wrap gap-2 pt-4 mt-4 border-t border-current/10 animate-stagger-fade-in">
    {message.actions.map(...)}     // welcome starter buttons only
  </div>
)}

{status === 'ready' && (
  (message.role === 'assistant' && message.id !== "welcome" && index === extendedMessages.length - 1) ||
  message.role === 'user'
) && (
  <div className="flex flex-wrap gap-2 pt-2 mt-2">
    {message.role === 'assistant' && message.id !== "welcome" && index === extendedMessages.length - 1 && (
      <Button ...>Regenerate</Button>
    )}
    {message.role === 'user' && (
      <Button ...>Retry</Button>
    )}
  </div>
)}
```

### 6. Keep `handleActionClick()` (lines 707-753)

Still used by the welcome message starter buttons. No changes needed.

### 7. Clean up stale comments

Update file-header and section comments that still describe heuristic per-message action generation:

- **Line 24**: `6. ACTION BUTTONS: Smart action suggestions based on message content` → `6. ACTION BUTTONS: Welcome starter prompts for new conversations`
- **Lines 92-105**: Remove the entire `SMART ACTIONS SYSTEM` doc block (describes keyword→button mapping that no longer exists). Replace with brief note: `ACTION BUTTONS: Welcome message provides starter prompts; per-message actions removed.`
- **Line 518**: `3. ACTION DETECTION: Analyze content for actionable buttons and visual theming` → `3. TYPE PARSING: Determine message type for appropriate styling`  (renumber step 4 accordingly)
- **Lines 1108-1111**: Remove the `SMART ACTION BUTTONS` section comment block (the 4-line banner). Replace with brief comment: `{/* Welcome starter buttons (only rendered when actionable) */}`

### 8. Clean up imports (line 163)

Remove `TrendingUp` from the lucide-react import. It is only used in `generateActionsForMessage()` (line 391 — "Performance Analysis" button). The welcome message uses `Eye`, `Shield`, `BarChart3`, `Search` — not `TrendingUp`.

```tsx
// Before:
import { AlertTriangle,BarChart3,Bot,Eye,File,FileText,Image,RefreshCw,Search,Send,Shield,TrendingUp,Upload,User,X } from "lucide-react";

// After:
import { AlertTriangle,BarChart3,Bot,Eye,File,FileText,Image,RefreshCw,Search,Send,Shield,Upload,User,X } from "lucide-react";
```

## What's preserved

- Welcome message with 4 starter buttons (Portfolio Overview, Risk Analysis, Factor Models, Stock Lookup)
- `handleActionClick()` for welcome button navigation + follow-up messages
- `ExtendedChatMessage` interface (still used by welcome message)
- Regenerate button (moved out, guarded against welcome message)
- Retry button (moved out, now visible on all user messages — correct UX)

## Verification

1. `cd frontend && npx tsc --noEmit` — no type errors
2. Open AI chat — welcome message shows 4 starter buttons, NO Regenerate button
3. Send a message — AI response has NO action buttons
4. AI response shows Regenerate button on last assistant message
5. All user messages show Retry button
6. Existing chat tests still pass
