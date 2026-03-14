# Plan: Artifact Mode — Side Panel for Visual Reports

**Status:** PLANNING
**Goal:** Add a slide-out side panel where the AI composes full visual reports (dashboards, position reports) separate from the chat flow

## Context

The current UI blocks system (Phases 0-3) renders blocks **inline** in chat messages
via the `:::ui-blocks` protocol. This works well for 2-4 metrics but becomes unwieldy
for full dashboards or structured reports. The chat flow gets cluttered and there's
no way to keep a report visible while continuing the conversation.

**What this adds:** A new `:::artifact` protocol + slide-out side panel. The AI emits
a titled artifact spec; the frontend renders it in a persistent panel alongside chat.
The user can keep chatting while viewing the report.

## Design

### Protocol: `:::artifact`

New delimiter, parallel to `:::ui-blocks`:

```
Here's your risk dashboard:

:::artifact Risk Dashboard
[
  {"layout":"stack","gap":"md","children":[
    {"block":"section-header","props":{"title":"Portfolio Risk","icon":"shield"}},
    {"layout":"grid","columns":3,"children":[
      {"block":"metric-card","props":{"label":"Risk Score","value":"72/100","colorScheme":"amber"}},
      {"block":"metric-card","props":{"label":"Sharpe Ratio","value":"1.24","colorScheme":"emerald"}},
      {"block":"metric-card","props":{"label":"Max Drawdown","value":"-12.3%","colorScheme":"red"}}
    ]},
    {"block":"data-table","props":{"columns":[...],"rows":[...]}}
  ]}
]
:::
```

Key differences from `:::ui-blocks`:
- **Title on opening line**: `:::artifact <title>` (required)
- **Renders in side panel**, not inline in chat
- **Persistent** — stays visible while user continues chatting
- **One artifact at a time** — new artifact replaces the previous one
- **Chat shows a compact reference card** instead of rendering blocks inline

### UX Flow

1. AI streams message with `:::artifact` block
2. During streaming: block JSON hidden (same as ui-blocks)
3. On completion:
   - Chat shows a compact **artifact reference card** (title + "View" button)
   - Side panel slides open from the right with the rendered artifact
4. User can:
   - Close panel (X button or Escape)
   - Reopen from the reference card in chat
   - Continue chatting with panel open
   - New artifact replaces the current one

### Side Panel Specs

- **Width**: 480px (fixed for MVP)
- **Position**: Fixed right, full height
- **Z-index**: 50 (same as modals — panel is a peer, not subordinate)
- **Animation**: Slide in from right (300ms, ease-out)
- **Styling**: Glass morphism consistent with existing chat UI
- **Scrollable**: Content area scrolls independently
- **Header**: Title + close button

**Layout interaction with AIChat (modal mode)**: AIChat is `fixed bottom-6 right-6 w-[550px]
h-[750px] z-50`. When ArtifactPanel opens, AIChat shifts left by 480px (panel width) via
dynamic `right-[510px]` class (480px panel + 30px gap). Both at z-50 as peers.

**Layout interaction with ChatInterface (fullscreen mode)**: ChatInterface fills the
content area via `h-full flex flex-col`. When ArtifactPanel opens, the fullscreen chat
container adds `pr-[480px]` (right padding) so the message area and input shrink to
make room for the fixed-position panel. This prevents overlay.

## Implementation

### Phase 1: Parser + Types (chassis package)

**File: `frontend/packages/chassis/src/types/index.ts`**

Add artifact types:

```typescript
export interface ArtifactSpec {
  title: string;
  blocks: UIRenderableSpec[];
}

// Extend ParsedMessageSegment
export interface ParsedMessageSegment {
  type: 'text' | 'ui-blocks' | 'artifact';
  content?: string;
  blocks?: UIRenderableSpec[];
  artifact?: ArtifactSpec;
}
```

**File: `frontend/packages/chassis/src/services/parse-ui-blocks.ts`**

The current parser uses `remaining.indexOf(BLOCK_OPEN)` where `BLOCK_OPEN = ':::ui-blocks'`.
This will never find `:::artifact` blocks. The parser must search for **both** specific
openers (`:::ui-blocks` and `:::artifact`), NOT scan for bare `:::` (which would break
text containing `:::note`, code samples, etc.).

**Approach**: Find the earliest occurrence of either `:::ui-blocks` or `:::artifact\s`
and branch accordingly. This preserves existing behavior — bare `:::` in text is untouched.

```typescript
const BLOCK_OPEN = ':::ui-blocks';
const ARTIFACT_PREFIX = ':::artifact ';
const ARTIFACT_OPEN_RE = /^:::artifact\s+(.+)$/;

/**
 * Find the earliest recognized block opener in remaining text.
 * Returns { index, type, openerLine } or null if none found.
 */
function findNextOpener(text: string): {
  index: number;
  type: 'ui-blocks' | 'artifact';
  openerLine: string;
} | null {
  const uiIdx = text.indexOf(BLOCK_OPEN);
  const artIdx = text.indexOf(ARTIFACT_PREFIX);
  // No openers found
  if (uiIdx === -1 && artIdx === -1) return null;
  // Pick the earliest
  if (artIdx === -1 || (uiIdx !== -1 && uiIdx <= artIdx)) {
    return { index: uiIdx, type: 'ui-blocks', openerLine: BLOCK_OPEN };
  }
  // Artifact found first — extract the full opener line for title parsing
  const lineEnd = text.indexOf('\n', artIdx);
  const openerLine = lineEnd === -1 ? text.slice(artIdx) : text.slice(artIdx, lineEnd);
  return { index: artIdx, type: 'artifact', openerLine };
}

export function parseMessageContent(content: string): {
  cleanContent: string;
  segments: ParsedMessageSegment[];
} {
  const segments: ParsedMessageSegment[] = [];
  let remaining = content;
  const textParts: string[] = [];

  while (remaining.length > 0) {
    const opener = findNextOpener(remaining);

    if (!opener) {
      const text = remaining.trim();
      if (text) {
        segments.push({ type: 'text', content: text });
        textParts.push(text);
      }
      break;
    }

    // Text before the block
    const before = remaining.slice(0, opener.index).trim();
    if (before) {
      segments.push({ type: 'text', content: before });
      textParts.push(before);
    }

    const openerLen = opener.openerLine.length;
    const afterOpen = opener.index + openerLen;

    // Find closing delimiter: \n::: followed by newline or end-of-string
    // Must be a standalone ::: line, not :::ui-blocks or :::artifact
    let closeIdx = -1;
    let searchFrom = afterOpen;
    while (true) {
      const candidate = remaining.indexOf('\n:::', searchFrom);
      if (candidate === -1) break;
      const afterDelim = candidate + 4; // length of '\n:::'
      const nextChar = remaining[afterDelim];
      // Standalone ::: if followed by newline, end-of-string, or undefined
      if (!nextChar || nextChar === '\n') {
        closeIdx = candidate;
        break;
      }
      // Not standalone — skip past this occurrence
      searchFrom = afterDelim;
    }

    if (closeIdx === -1) {
      // Unclosed block — strip it (partial/incomplete during streaming)
      break;
    }

    // Extract JSON between delimiters
    const jsonStr = remaining.slice(afterOpen, closeIdx).trim();
    try {
      const parsed = JSON.parse(jsonStr) as UIRenderableSpec[];
      if (Array.isArray(parsed) && parsed.length > 0) {
        if (opener.type === 'artifact') {
          const titleMatch = opener.openerLine.match(ARTIFACT_OPEN_RE);
          const title = titleMatch ? titleMatch[1].trim() : 'Report';
          segments.push({
            type: 'artifact',
            artifact: { title, blocks: parsed }
          });
        } else {
          segments.push({ type: 'ui-blocks', blocks: parsed });
        }
      }
    } catch {
      // Invalid JSON — silently drop the block section
    }

    // Move past the closing delimiter (\n:::)
    remaining = remaining.slice(closeIdx + 4); // +4 for '\n:::'
  }

  // Generate cleanContent — count both ui-blocks and artifact segments
  let cleanContent = textParts.join('\n\n');
  if (!cleanContent.trim()) {
    const blockSegments = segments.filter(s => s.type === 'ui-blocks');
    const artifactSegments = segments.filter(s => s.type === 'artifact');
    const blockCount = blockSegments.reduce(
      (sum, s) => sum + (s.blocks?.length ?? 0), 0
    );
    const artifactCount = artifactSegments.length;
    const parts: string[] = [];
    if (blockCount > 0) {
      parts.push(`${blockCount} UI block${blockCount > 1 ? 's' : ''}`);
    }
    if (artifactCount > 0) {
      const title = artifactSegments[artifactSegments.length - 1].artifact?.title;
      parts.push(`artifact: ${title || 'Report'}`);
    }
    if (parts.length > 0) {
      cleanContent = `[Displayed: ${parts.join(' + ')}]`;
    }
  }

  return { cleanContent, segments };
}
```

Update `stripUIBlocks()` to also strip artifact blocks during streaming. The closing
`:::` must be standalone (followed by newline or end-of-string), matching the parser:

```typescript
export function stripUIBlocks(text: string): string {
  // Remove completed :::ui-blocks...:::  sections
  // Closing ::: must be on its own line (followed by \n or end-of-string)
  let result = text.replace(/:::ui-blocks\n[\s\S]*?\n:::(?=\n|$)/g, '');
  // Remove completed :::artifact...:::  sections
  result = result.replace(/:::artifact\s+.+\n[\s\S]*?\n:::(?=\n|$)/g, '');

  // Remove any trailing unclosed block section (ui-blocks or artifact)
  // Only look for recognized openers, not bare :::
  const lastUIBlockOpen = result.lastIndexOf(':::ui-blocks');
  const lastArtifactOpen = result.lastIndexOf(':::artifact ');
  const lastOpen = Math.max(lastUIBlockOpen, lastArtifactOpen);

  if (lastOpen !== -1) {
    // Find where the opener line ends
    const openerEnd = result.indexOf('\n', lastOpen);
    const afterOpen = openerEnd !== -1 ? openerEnd : result.length;

    // Look for a standalone closing ::: after the opener
    let hasClose = false;
    let searchFrom = afterOpen;
    while (true) {
      const candidate = result.indexOf('\n:::', searchFrom);
      if (candidate === -1) break;
      const afterDelim = candidate + 4;
      const nextChar = result[afterDelim];
      if (!nextChar || nextChar === '\n') {
        hasClose = true;
        break;
      }
      searchFrom = afterDelim;
    }

    // If no standalone closing ::: found, strip from opener to end
    if (!hasClose) {
      result = result.slice(0, lastOpen);
    }
  }

  return result.trim();
}
```

### Phase 2: Artifact State in ChatContext (connectors package)

**Key design decision**: Artifact state (current artifact, panel open/closed) lives in
`ChatContext` alongside the existing chat state — NOT threaded via props. This is correct
because:
1. `ChatProvider` wraps all of `ModernDashboardApp`'s children (lines 544-933)
2. `ArtifactPanel` needs `sendMessage` for action buttons — available from `useSharedChat()`
3. Avoids prop threading through 3 layers (ChatCore → AIChat/ChatInterface → Dashboard)
4. Any component inside `ChatProvider` can open/close the panel

**File: `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts`**

Update the `UsePortfolioChatReturn` interface (line 113) to include artifact state:

```typescript
export interface UsePortfolioChatReturn {
  // ... existing fields ...

  // Artifact panel state
  currentArtifact: ArtifactSpec | null;
  artifactPanelOpen: boolean;
  openArtifact: (artifact: ArtifactSpec) => void;
  closeArtifactPanel: () => void;
}
```

Add artifact state to the hook's return value:

```typescript
// New state in usePortfolioChat:
const [currentArtifact, setCurrentArtifact] = useState<ArtifactSpec | null>(null);
const [artifactPanelOpen, setArtifactPanelOpen] = useState(false);

const openArtifact = useCallback((artifact: ArtifactSpec) => {
  setCurrentArtifact(artifact);
  setArtifactPanelOpen(true);
}, []);

const closeArtifactPanel = useCallback(() => {
  setArtifactPanelOpen(false);
}, []);

const resetArtifact = useCallback(() => {
  setCurrentArtifact(null);
  setArtifactPanelOpen(false);
}, []);
```

**Clear artifact state on conversation reset/rewind**: The hook has 4 paths that
truncate or clear message history (`clearMessages`, `reload`, `regenerate`,
`retryMessage`). Each must call `resetArtifact()` to prevent a stale artifact
panel persisting after the conversation changes:

```typescript
// In clearMessages (line ~858):
resetArtifact();

// In reload (line ~787):
resetArtifact();

// In regenerate (line ~811):
resetArtifact();

// In retryMessage (line ~844):
resetArtifact();
```

In the streaming completion block (after line 678), add artifact handling:

```typescript
// Parse UI blocks from completed response
const { cleanContent, segments } = parseMessageContent(accumulatedContent);
const hasBlocks = segments.some(s => s.type === 'ui-blocks');
const hasArtifact = segments.some(s => s.type === 'artifact');

if (hasBlocks || hasArtifact) {
  setMessages(prev => prev.map(msg =>
    msg.id === assistantMessageId
      ? { ...msg, content: cleanContent, rawContent: accumulatedContent, uiBlocks: segments }
      : msg
  ));
}

// Auto-open artifact panel with the LAST artifact in the message
if (hasArtifact) {
  const artifactSegments = segments.filter(s => s.type === 'artifact');
  const lastArtifact = artifactSegments[artifactSegments.length - 1].artifact;
  if (lastArtifact) {
    openArtifact(lastArtifact);
  }
}
```

Return the new state from the hook:

```typescript
return {
  // ... existing returns ...
  currentArtifact,
  artifactPanelOpen,
  openArtifact,
  closeArtifactPanel,
};
```

**File: `frontend/packages/chassis/src/types/index.ts`**

Export `ArtifactSpec` (same as Phase 1 above).

### Phase 3: ArtifactPanel + ArtifactCard Components (ui package)

**File: `frontend/packages/ui/src/components/chat/ArtifactPanel.tsx`**

New component using existing BlockRenderer + LayoutRenderer:

```typescript
interface ArtifactPanelProps {
  isOpen: boolean;
  artifact: ArtifactSpec | null;
  onClose: () => void;
  onNavigate?: (view: string) => void;
  onSendMessage?: (message: string) => void;
}
```

Renders:
- Slide-out panel (`fixed top-0 right-0 h-full w-[480px] z-50`)
- Header with artifact title + close button
- Scrollable content area
- Each block rendered via `BlockRenderer` / `LayoutRenderer`

**File: `frontend/packages/ui/src/components/chat/ArtifactCard.tsx`**

Compact inline card shown in chat where the artifact was emitted:

```typescript
interface ArtifactCardProps {
  title: string;
  blockCount: number;
  onClick: () => void;
}
```

Renders a small card with icon + title + "View" button. Clicking opens the panel.

### Phase 4: ChatCore Integration (ui package)

**File: `frontend/packages/ui/src/components/chat/shared/ChatCore.tsx`**

In the segment rendering loop, handle `type: 'artifact'`:

```typescript
// When rendering segments:
case 'artifact':
  // Render compact ArtifactCard inline in chat
  return (
    <ArtifactCard
      key={`artifact-${idx}`}
      title={segment.artifact?.title ?? 'Report'}
      blockCount={segment.artifact?.blocks?.length ?? 0}
      onClick={() => {
        if (segment.artifact) {
          openArtifact(segment.artifact);
        }
      }}
    />
  );
```

**IMPORTANT**: NO side effects during render. The `openArtifact()` call is only in the
`onClick` handler (user-triggered), NOT called during rendering. The auto-open on streaming
completion is handled in `usePortfolioChat` (Phase 2), which is the correct place for it.

Get `openArtifact` from context: `const { openArtifact } = useSharedChat();`

No new props needed on ChatCore, AIChat, or ChatInterface — everything goes through context.

### Phase 5: Dashboard Integration

**Files: `ModernDashboardApp.tsx` + `AnalystApp.tsx`**

Both app shells use `ChatProvider` + `ChatInterface`/`AIChat`. Both must mount
`ArtifactPanel` inside their `ChatProvider` scope. Create a shared connected wrapper:

**File: `frontend/packages/ui/src/components/chat/ArtifactPanelConnected.tsx`**

```typescript
// Shared connected wrapper — lives in ui package, used by both app shells
export const ArtifactPanelConnected: FC<{ onNavigate: (view: string) => void }> = ({ onNavigate }) => {
  const { currentArtifact, artifactPanelOpen, closeArtifactPanel, sendMessage } = useSharedChat();

  return (
    <ArtifactPanel
      isOpen={artifactPanelOpen}
      artifact={currentArtifact}
      onClose={closeArtifactPanel}
      onNavigate={onNavigate}
      onSendMessage={sendMessage}
    />
  );
};
```

**File: `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`**

In `ModernDashboardApp` JSX (inside `<ChatProvider>`):

```tsx
<ChatProvider>
  <div className="min-h-screen ...">
    {/* ... existing content ... */}
    <AIChat ... />
    <ArtifactPanelConnected onNavigate={(view) => setActiveView(view)} />
  </div>
</ChatProvider>
```

**File: `frontend/packages/ui/src/components/apps/AnalystApp.tsx`**

In `AnalystApp` JSX (inside `<ChatProvider>`):

```tsx
<ChatProvider>
  <div className="flex h-screen ...">
    <AnalystSidebar ... />
    <main ...>
      {/* ... existing views ... */}
    </main>
    <ArtifactPanelConnected onNavigate={(view) => {
      // AnalystApp maps dashboard views → analyst views via mapChatViewToAnalyst()
      // Unsupported views (score, factors, etc.) are ignored — no crash, just no-op
      const mapped = mapChatViewToAnalyst(view);
      if (mapped) setActiveView(mapped);
    }} />
  </div>
</ChatProvider>
```

**Note**: AnalystApp only supports `chat|holdings|connections` views. Block-level
navigate actions in artifacts emit dashboard views (`score`, `factors`, `performance`,
etc.) which `mapChatViewToAnalyst()` filters — unmapped views are silently ignored.
This is acceptable for MVP; analyst mode is secondary.

**Artifact-aware positioning (modal mode)**:
```tsx
// In AIChat, add artifact-aware positioning:
const { artifactPanelOpen } = useSharedChat();
const rightOffset = artifactPanelOpen ? 'right-[510px]' : 'right-6';
// <div className={`fixed bottom-6 ${rightOffset} w-[550px] h-[750px] ...`}>
```

**Artifact-aware layout (fullscreen mode)**:

**File: `frontend/packages/ui/src/components/layout/ChatInterface.tsx`**

ChatInterface fills the content area. When ArtifactPanel is open, add right padding
so the chat area shrinks to avoid being overlaid by the fixed panel:

```tsx
const { artifactPanelOpen } = useSharedChat();

return (
  <div className={`h-full flex flex-col glass-premium rounded-2xl overflow-auto
    ${artifactPanelOpen ? 'pr-[480px]' : ''}`}>
    <ChatCore ... />
  </div>
);
```

This makes the chat messages and input area shrink by 480px when the panel is open,
keeping the panel "alongside" rather than "overlaying" the chat.

**"Ask AI" button overlap**: The floating "Ask AI" button in `ModernDashboardApp`
is `fixed bottom-6 right-6 z-50`. When ArtifactPanel is open, this button sits
behind/under the panel. Fix: use `ArtifactPanelConnected` to also read
`artifactPanelOpen` and pass it up, or make the button artifact-aware:

```tsx
// In ModernDashboardApp, the Ask AI button shifts left when panel is open:
// Use a small inner component or read from context via ArtifactPanelConnected
<button
  className={`fixed bottom-6 ${artifactPanelOpen ? 'right-[510px]' : 'right-6'} z-50 ...`}
  ...
/>
```

Since `ModernDashboardApp` itself can't call `useSharedChat()` (it's above
`ChatProvider`), the `ArtifactPanelConnected` wrapper can expose `artifactPanelOpen`
via a callback prop, or use a simpler approach: make the "Ask AI" button itself a
small connected component that reads `artifactPanelOpen` from context.

Add keyboard shortcut: Escape closes panel (handled in ArtifactPanel via `useEffect`).

### Phase 6: System Prompt Update

**File: External — `AI-excel-addin/api/tools.py`**

Add artifact section to `_build_ui_blocks_section()`:

```
## Artifacts (Full Reports)
For comprehensive analyses (dashboards, multi-section reports), emit an artifact:

:::artifact Portfolio Risk Dashboard
[{"layout":"stack","children":[...]}]
:::

Rules:
- Title is required on the opening line
- Use for reports with 5+ blocks or structured multi-section layouts
- One artifact per message (last one wins if multiple)
- Always include brief summary text before the artifact
- Use layout specs (grid, stack, row) to organize content
- Artifacts use the same block types as inline :::ui-blocks
```

## Files Modified

| File | Package | Change |
|------|---------|--------|
| `chassis/src/types/index.ts` | @risk/chassis | Add `ArtifactSpec`, extend `ParsedMessageSegment` |
| `chassis/src/services/parse-ui-blocks.ts` | @risk/chassis | Restructure parser to search for `:::ui-blocks` and `:::artifact ` openers (not bare `:::`), handle both types |
| `connectors/src/features/external/hooks/usePortfolioChat.ts` | @risk/connectors | Add artifact state, auto-open on completion, "last one wins" logic |
| `ui/src/components/chat/ArtifactPanel.tsx` | @risk/ui | NEW — slide-out side panel component |
| `ui/src/components/chat/ArtifactCard.tsx` | @risk/ui | NEW — compact inline reference card |
| `ui/src/components/chat/shared/ChatCore.tsx` | @risk/ui | Render `ArtifactCard` for artifact segments, get `openArtifact` from context |
| `ui/src/components/chat/AIChat.tsx` | @risk/ui | Artifact-aware positioning (shift left when panel open) |
| `ui/src/components/layout/ChatInterface.tsx` | @risk/ui | Artifact-aware right padding (shrink chat when panel open) |
| `ui/src/components/chat/ArtifactPanelConnected.tsx` | @risk/ui | NEW — shared connected wrapper for ArtifactPanel (reads context) |
| `ui/src/components/apps/ModernDashboardApp.tsx` | @risk/ui | Mount `ArtifactPanelConnected` inside ChatProvider, Ask AI button artifact-aware |
| `ui/src/components/apps/AnalystApp.tsx` | @risk/ui | Mount `ArtifactPanelConnected` inside ChatProvider |
| External: `AI-excel-addin/api/tools.py` | — | System prompt update |

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| Artifact with invalid JSON | Silently dropped, chat shows text only |
| Artifact with no title | `:::artifact\n` doesn't match `ARTIFACT_OPEN_RE` → skipped by parser, treated as unrecognized `:::` |
| Multiple artifacts in one message | All parsed as segments, all render as ArtifactCards in chat. "Last one wins" for auto-open — `usePortfolioChat` opens the last artifact on streaming completion |
| Artifact during streaming | JSON hidden via `stripUIBlocks()` which now strips both `:::ui-blocks` and `:::artifact` patterns |
| Unclosed artifact during streaming | `stripUIBlocks()` finds last `:::artifact` opener and strips from there to end of text |
| Panel open + new artifact arrives | `openArtifact()` replaces `currentArtifact` state + panel stays open |
| Panel open + user navigates away | Panel stays open (persistent). User can close via X or Escape |
| Artifact in modal chat (AIChat) | Panel opens at z-50 fixed right. AIChat shifts left by panel width to avoid overlap |
| Artifact in fullscreen chat | Panel opens at z-50 fixed right. ChatInterface adds `pr-[480px]` so chat area shrinks (not overlaid) |
| Artifact with unknown block type | BlockRenderer already handles gracefully (renders nothing) |
| Very long artifact (50+ blocks) | Scrollable content area, no truncation |
| ArtifactCard clicked in chat history | `openArtifact(segment.artifact)` called from onClick handler — no render side effect |
| Message with both ui-blocks and artifact | Parser produces correct segment types for each. ui-blocks render inline, artifact renders as ArtifactCard |
| `:::` appears in text/code | Parser only searches for `:::ui-blocks` and `:::artifact ` (with space) as openers. Bare `:::`, `:::note`, `:::warning`, etc. are untouched — never matched by `indexOf(':::ui-blocks')` or `indexOf(':::artifact ')` |
| `cleanContent` with artifact-only response | Fallback shows `[Displayed: artifact: Title]` |

## Tests

1. **Parser: `test_parse_artifact_block`** — `:::artifact Title\n[...]\n:::` produces
   segment with `type: 'artifact'`, correct title and blocks.

2. **Parser: `test_strip_artifact_during_stream`** — `stripUIBlocks()` removes
   completed artifact blocks from streaming text.

3. **Parser: `test_strip_unclosed_artifact_during_stream`** — `stripUIBlocks()` removes
   unclosed `:::artifact Title\n{partial JSON...` from streaming text (no closing `:::`).

4. **Parser: `test_artifact_missing_title`** — `:::artifact\n[...]\n:::` (no title)
   is NOT parsed as artifact (skipped as unrecognized delimiter).

5. **Parser: `test_mixed_uiblocks_and_artifact`** — Message with both `:::ui-blocks`
   and `:::artifact` produces correct segment types for each.

6. **Parser: `test_multiple_artifacts_all_parsed`** — Message with two `:::artifact`
   blocks produces two artifact segments (both parseable).

7. **Parser: `test_cleanContent_artifact_only`** — Message with only artifact block
   produces `cleanContent` fallback mentioning the artifact title.

8. **Parser: `test_general_delimiter_scan`** — Parser correctly finds `:::artifact`
   blocks that the old `indexOf(':::ui-blocks')` approach would have missed.

9. **Parser: `test_bare_colons_not_consumed`** — Text containing `:::note` or `:::warning`
   is passed through as text content, not consumed or stripped by the parser.

10. **Component: `test_artifact_panel_renders_blocks`** — ArtifactPanel with a
    metric-card spec renders the block via BlockRenderer.

11. **Component: `test_artifact_card_click_opens_panel`** — Clicking ArtifactCard
    triggers the onClick handler (no side effects during render).

12. **Hook: `test_usePortfolioChat_opens_last_artifact`** — After streaming completes
    with two artifact segments, `currentArtifact` is set to the last one and
    `artifactPanelOpen` is true.

13. **Hook: `test_artifact_reset_on_clear`** — After an artifact is open, calling
    `clearMessages()` resets `currentArtifact` to null and `artifactPanelOpen` to false.
    Same for `reload()`, `regenerate()`, and `retryMessage()`.

14. **Integration: `test_chatcore_renders_artifact_card`** — ChatCore with an artifact
    segment renders an ArtifactCard (not BlockRenderer inline), and does NOT call
    `openArtifact` during render.

## Future Enhancements (Out of Scope)

- **Resizable panel**: Use existing `ResizablePanelGroup` for drag-resize
- **Artifact history**: Tab bar at top of panel for multiple artifacts
- **Export**: Save artifact as PDF/PNG
- **Editable**: User can modify artifact (adjust parameters, re-run)
- **Template library**: Predefined artifact layouts ("risk-dashboard", "position-report")
