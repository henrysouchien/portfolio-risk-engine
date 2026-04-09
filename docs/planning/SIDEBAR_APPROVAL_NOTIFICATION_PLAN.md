# Sidebar Approval Notification — ChatMargin Badge

## Context

When a tool-call approval is pending and the user is on a non-chat view, there's no visual indicator on the sidebar. The approval card only renders in the full chat view (`ChatCore.tsx`). Users don't know to navigate to the chat to approve, causing the AI to stall silently.

**TODO item**: "Add a notification badge or pulse on the ChatMargin chat icon when `pendingApproval` is set, so users know to navigate to the chat view."

## Approach

Single-file change to `ChatMargin.tsx`. Two visual additions matching existing codebase patterns.

### File: `frontend/packages/ui/src/components/design/ChatMargin.tsx`

#### 1. Destructure `pendingApproval` from `useSharedChat()`

Line 1317 — add `pendingApproval` to the existing destructure:

```tsx
const {
  messages,
  sendMessage,
  status,
  chatStatus,
  canSend,
  currentArtifact,
  artifactPanelOpen,
  artifactDisplayMode,
  openArtifact,
  pendingApproval,   // ← add
} = useSharedChat();
```

#### 2. Narrow sidebar (lg–xl): amber dot badge on chat icon

Lines 1436–1456. Add `relative` to the button, overlay a small amber dot when approval is pending. Pattern reuses notification-center badge positioning (`absolute -top-1 -right-1`).

```tsx
<aside className="hidden min-h-0 w-8 shrink-0 flex-col items-center gap-3 border-l border-border-subtle bg-background py-4 lg:flex xl:hidden">
  <button
    type="button"
    onClick={onOpenFullChat}
    className="relative flex h-8 w-8 items-center justify-center rounded-md text-[hsl(var(--text-muted))] transition-colors hover:text-foreground"
    aria-label={pendingApproval ? 'Approval needed — open chat' : 'Open full chat'}
  >
    <MessageSquare className="h-4 w-4" />
    {pendingApproval && (
      <span aria-hidden="true" className="absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border border-background bg-amber-500" />
    )}
  </button>
  {/* dots unchanged */}
</aside>
```

Changes:
- Add `relative` to button class (for absolute badge positioning)
- `aria-label` for accessibility (not `title` — screen readers need a proper accessible name)
- Dot is `aria-hidden="true"` (decorative; the label carries the semantics)
- Conditional amber dot badge (`h-2.5 w-2.5`, amber-500, border matches background for cutout effect)

#### 3. Wide sidebar (xl+): compact approval prompt banner

Lines 1458–1503. Add a fixed (non-scrolling) banner between the aside open and the scroll area when approval is pending. Clicking it opens the full chat.

```tsx
<aside className="hidden h-full min-h-0 flex-col border-l border-border-subtle bg-background xl:flex">
  {pendingApproval && (
    <button
      type="button"
      onClick={onOpenFullChat}
      className="flex shrink-0 items-center gap-2 border-b border-border-subtle px-[14px] py-2.5 text-left transition-colors hover:bg-surface-2"
    >
      <span aria-hidden="true" className="h-2 w-2 shrink-0 rounded-full bg-amber-500" />
      <span className="text-[12px] font-medium text-foreground">
        Tool approval needed
      </span>
    </button>
  )}
  <div className="scroll-shell min-h-0 flex-1 overflow-y-auto px-[14px] py-4">
    {/* existing rail content unchanged */}
  </div>
  <ChatMarginComposer ... />
</aside>
```

This banner:
- Stays fixed at top (not in scroll area) — always visible
- Has amber dot + text for clarity
- Clicking navigates to full chat where the approval card lives
- Subtle border-bottom separates it from rail content
- Collapses automatically when `pendingApproval` clears (null)

## Files touched

| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/design/ChatMargin.tsx` | Destructure `pendingApproval`, add badge + banner |
| `frontend/packages/ui/src/components/design/ChatMargin.test.tsx` | Add `pendingApproval` to mock, add 2 test cases |

## Tests

**File:** `frontend/packages/ui/src/components/design/ChatMargin.test.tsx`

The existing mock at line 10 needs `pendingApproval: null` added. The `beforeEach` block (line 33) needs `mockChatState.pendingApproval = null` to prevent leakage between tests. Two new test cases:

1. `shows amber badge on narrow sidebar when approval is pending` — set `mockChatState.pendingApproval = { toolCallId: 'tc1', nonce: 'n1', toolName: 'run_optimization', toolInput: {} }`, render with `activeView="score"`, assert the button's `aria-label` is `'Approval needed — open chat'`.

2. `shows approval banner on wide sidebar when approval is pending` — same mock setup, assert text "Tool approval needed" is in the document.

## Known limitation

ChatMargin is hidden when `activeView === 'settings'` (`showChatMargin = activeView !== 'chat' && activeView !== 'settings'`). Approvals during settings view remain silent. This is acceptable — settings is rarely active during AI conversations, and fixing it would require changes to `ModernDashboardApp.tsx` layout (out of scope).

## Verification

1. **Visual**: Start dev server (`services-mcp`). Trigger a tool call that requires approval in chat. Navigate to a non-chat view. Confirm:
   - Narrow sidebar (resize to lg–xl): amber dot appears on chat icon, aria-label says "Approval needed"
   - Wide sidebar (xl+): "Tool approval needed" banner appears at top of rail
   - Both: clicking opens full chat where approval card is rendered
   - After approving/denying: indicators disappear immediately

2. **Frontend tests**: `cd frontend && npx vitest run --reporter=verbose` — existing tests pass, new approval tests pass.

## Codex Review History

**R1 — FAIL (3 actionable findings)**:
1. `border-background` is valid (custom color in tailwind config) — no change needed. Not a blocker.
2. Wide sidebar banner: add `shrink-0` for layout robustness → **Fixed**.
3. Settings view gap: ChatMargin hidden on settings → **Acknowledged** as known limitation (out of scope).
4. Accessibility: use `aria-label` instead of `title`, mark dot `aria-hidden="true"` → **Fixed**.
5. ChatMargin.test.tsx exists (plan incorrectly claimed it didn't) → **Fixed**: added test section with 2 test cases.

**R2 — FAIL (1 finding)**:
1. Test hygiene: `beforeEach` must reset `mockChatState.pendingApproval = null` to prevent leakage → **Fixed**.
