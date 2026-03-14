# Agent-Driven Dynamic UI Generation

**Date:** 2026-03-07
**Status:** PLANNING
**Codex Review:** R1-R7 FAIL (25 findings, all addressed), **R8 PASS**
**Depends on:** Frontend Redesign Phase 1d (in review), Phase 5 (not started)
**Related:** `FRONTEND_REDESIGN_PLAN.md` (block library), TODO item "Agent-Driven Dynamic UI Generation"

---

## Context

The AI chat assistant currently receives rich structured data from MCP tools (snapshots with scores, breakdowns, flags with severity/metadata) and converts it to prose text. The frontend then keyword-parses that text to guess message types and generate action buttons. This is lossy in both directions. Instead, the AI should emit structured UI block specifications that the frontend renders as real React components inline with the chat stream.

The block component library (Phase 1b/1c of the frontend redesign) provides 12 production-ready components with consistent CVA variants, a 7-color scheme system, and dark mode support. These blocks are the natural component registry candidates.

**Outcome**: The chat becomes a rich, interactive canvas — metrics render as real MetricCards, warnings as InsightBanners, holdings as DataTables, all composed into layouts the AI chooses at runtime.

### Relationship to broader frontend architecture

The block library is the foundation for both the static dashboard AND AI-driven chat rendering. Same components, two consumption paths:

```
Block Library (MetricCard, DataTable, InsightBanner, etc.)
    ├── Dashboard views — imported directly, wired to SDK hooks (live data)
    └── Chat blocks — resolved dynamically from AI JSON specs (snapshot data)
```

Future phases could add data-binding (blocks wired to SDK hooks for live refresh), but this plan covers the snapshot-rendering layer first.

---

## Protocol Design

### Why text-stream delimiters (not new SSE events)

The gateway (`routes/gateway_proxy.py`) is a raw SSE passthrough — it forwards bytes verbatim. Adding new event types requires external gateway changes. The `ClaudeStreamChunk` union drops unknown types (`default: return null` in `mapEvent()` in `GatewayClaudeService.ts`). Text-stream delimiters require **zero backend changes**.

### Format

The AI embeds JSON block specs within fenced delimiters in its text response:

```
Here's your portfolio risk summary:

:::ui-blocks
[
  { "block": "metric-card", "props": { "label": "Risk Score", "value": "72/100", "colorScheme": "amber", "icon": "Shield" } },
  { "block": "insight-banner", "props": { "title": "High Concentration", "subtitle": "Top 3 = 68%", "colorScheme": "red", "icon": "AlertTriangle" } }
]
:::

The elevated score is driven by concentration in your top holdings...
```

Multiple `:::ui-blocks` sections can appear in a single message, interleaved with text.

### Streaming behavior

During streaming, block content is **buffered, not displayed**. When `usePortfolioChat` detects `:::ui-blocks` in the accumulating text, it hides that region from the rendered `content` (replacing it with a placeholder like `[loading blocks...]`). On stream completion, `parseMessageContent()` extracts block sections and upgrades them to rendered components.

**Stop/error cleanup**: `usePortfolioChat` checks `abortController.signal.aborted` on each chunk (line 603) and breaks out of its stream loop. Post-loop (whether normal completion, abort, or catch), `parseMessageContent()` is called on the accumulated content — any `:::ui-blocks` section missing its closing `:::` delimiter is treated as incomplete and stripped (the parser only yields blocks from fully-delimited sections). This ensures partial JSON is never shown to users.

**Known limitation**: `GatewayClaudeService.sendMessageStream()` does not currently accept an `AbortSignal` — the `fetch()` at line 115 is unsignaled. On abort, `usePortfolioChat` breaks out of its consumer loop, but the underlying HTTP stream may continue until the gateway's server-side timeout. This is a pre-existing limitation (not introduced by this feature). A follow-up task should thread `AbortSignal` through `sendMessageStream()` → `fetch({ signal })` to enable clean HTTP cancellation and avoid the gateway's stream-lock 409 on rapid stop+resend.

### Content history handling

`GatewayClaudeService.sendMessageStream()` sends `m.content` back to the AI on future turns. To avoid polluting conversation history with protocol noise, `ChatMessage` stores two content fields:
- `content` — clean text with `:::ui-blocks` sections stripped (used for history/display)
- `rawContent` — original text including blocks (preserved for debugging, not sent to AI)

**Content guarantee**: The system prompt instructs the AI to always include meaningful prose alongside blocks. As a runtime safety net, `parseMessageContent()` checks if `cleanContent` is empty/whitespace-only after stripping blocks. If so, it generates a summary line from the block specs (e.g. `"[Displayed: 3 metric cards, 1 insight banner]"`) and uses that as `cleanContent`. This ensures history replay always has semantic context for the next turn, even if the AI violates the prompt instruction.

### End-to-end data flow

```
User: "What's my risk?"
  → AI calls get_risk_score() MCP tool
  → Tool returns {status, format: "agent", snapshot: {score: 72, ...}, flags: [...]}
  → AI reads snapshot, writes prose + :::ui-blocks with MetricCard spec
  → Gateway passes text through as text_delta SSE events (no changes)
  → usePortfolioChat accumulates content (block regions buffered, not displayed)
  → On stream completion: parseMessageContent() extracts :::ui-blocks sections
  → ChatCore renders: text as markdown, blocks via BlockRenderer → real React components
```

---

## Phased Implementation

### Phase 0: End-to-End Proof of Concept

**Goal**: One block type (MetricCard) rendering in chat. Hardcoded, no registry. Proves the protocol works.

| File | Change |
|------|--------|
| `chassis/src/types/index.ts` | Add `UIBlockSpec`, `UILayoutSpec`, `UIRenderableSpec`, `UIBlockAction`, `ParsedMessageSegment` types. Add `rawContent?: string` and `uiBlocks?: ParsedMessageSegment[]` to `ChatMessage`. (`MessagePart` unchanged — blocks use a separate field, not the Vercel AI SDK parts system.) |
| `connectors/src/features/external/hooks/usePortfolioChat.ts` | **During streaming** (~line 614): before writing `accumulatedContent` to the message via `setMessages`, call `stripUIBlocks(accumulatedContent)` — a lightweight function (also exported from `parse-ui-blocks.ts`) that removes **all** completed `:::ui-blocks...:::` sections AND any trailing unclosed `:::ui-blocks` section from the string. This ensures neither completed block JSON nor partial block JSON is ever visible in the streaming UI. **After stream loop exits** (~line 674): call `parseMessageContent(accumulatedContent)` for full parsing. Store `segments` as `uiBlocks` on the message, set `content` to `cleanContent`, set `rawContent` to original `accumulatedContent`. |
| `ui/src/components/chat/shared/ChatCore.tsx` | Add `uiBlocks?: ParsedMessageSegment[]` to `ExtendedChatMessage` (~line 187). In `extendedMessages` mapping (~line 539), flow `uiBlocks` from `ChatMessage`. Replace the single text `<div>` at ~line 1022 with a **segment walker**: if `uiBlocks` is present, iterate segments in order — render `'text'` segments as markdown and `'ui-blocks'` segments as components (hardcode `<MetricCard>` in Phase 0). If no `uiBlocks`, fall back to existing text-only rendering. This preserves text→blocks→text ordering for interleaved messages. |

**New types** (in `chassis/src/types/index.ts`):
```typescript
interface UIBlockSpec {
  block: string;
  props: Record<string, unknown>;
  key?: string;
  action?: UIBlockAction;
}

interface UILayoutSpec {
  layout: 'grid' | 'stack' | 'row';
  columns?: number;
  gap?: 'sm' | 'md' | 'lg';
  children: UIRenderableSpec[];  // Supports nested layouts
}

type UIRenderableSpec = UIBlockSpec | UILayoutSpec;

interface UIBlockAction {
  type: 'send-message';
  payload: string;
  label?: string;
} | {
  type: 'navigate';
  payload: string;  // view name
  label?: string;
}
```

**ChatMessage extension** (in `chassis/src/types/index.ts`):
```typescript
interface ParsedMessageSegment {
  type: 'text' | 'ui-blocks';
  content?: string;          // For 'text' segments
  blocks?: UIRenderableSpec[];  // For 'ui-blocks' segments
}

interface ChatMessage {
  // ... existing fields (id, type, role, content, timestamp, files, parts)
  rawContent?: string;           // Original text including :::ui-blocks (for debugging)
  uiBlocks?: ParsedMessageSegment[];  // Parsed block segments (canonical transport field)
  // content remains the clean/stripped version (used for history + display)
}
```

**New utility** (can live inline in usePortfolioChat for Phase 0):
```typescript
function parseMessageContent(content: string): {
  cleanContent: string;          // Text with :::ui-blocks sections stripped
  segments: ParsedMessageSegment[];  // Interleaved text + block segments
}
```

**Test**: Ask "What's my risk score?" → AI calls `get_risk_score`, emits text + `:::ui-blocks` with a MetricCard spec → chat renders a real MetricCard inline.

---

### Phase 1: Component Registry + Multi-Block Renderer

**Goal**: Type-safe registry mapping block names → React components. Icon resolution. 6 initial block types.

| New File | Purpose | ~Lines |
|----------|---------|--------|
| `ui/src/components/chat/blocks/block-registry.ts` | `Map<string, { component, sanitizeProps }>`, `registerBlock()`, `resolveBlock()`. Each block's `sanitizeProps` function performs **three-layer validation**: (1) **key whitelist** — unknown keys dropped (prevents `className`/`style`/`dangerouslySetInnerHTML` injection via component prop spreading), (2) **type checking** — each whitelisted prop validated against expected type (string, number, array, enum), wrong types dropped, (3) **required field check** — if required props missing after sanitization, returns `null` (block falls back to "Unknown block" rendering). Enum props (e.g. `colorScheme`, `size`) validated against allowed values. | ~60 |
| `ui/src/components/chat/blocks/icon-registry.ts` | Maps string names → Lucide icons (~20 curated icons) | ~30 |
| `ui/src/components/chat/blocks/block-renderer.tsx` | `<BlockRenderer spec={...} />` — resolves component, calls `sanitizeProps()` to whitelist props, resolves icons, renders. **Never forwards raw `spec.props`** to components. | ~50 |
| `ui/src/components/chat/blocks/register-defaults.ts` | Registers 6 blocks with prop validators. Called once at module scope (top-level side-effect) — imported by `block-renderer.tsx` which triggers registration on first import. Idempotent: `registerBlock()` skips if key already exists, safe under `React.StrictMode` double-render. | ~60 |
| `chassis/src/services/parse-ui-blocks.ts` | Extracted parsing logic: `parseMessageContent()` → interleaved text + block segments. Lives in chassis (not ui) so connectors can import it. Must be re-exported from `chassis/src/services/index.ts` (add to barrel) so `@risk/connectors` can import via `@risk/chassis`. | ~50 |
| `ui/src/components/chat/blocks/index.ts` | Barrel export | ~10 |

**Initial 6 blocks** (all serializable props, no render functions):

| Registry Key | Component | Key Props (AI-serializable) |
|---|---|---|
| `metric-card` | MetricCard | label, value, description, change, changeType, colorScheme, icon, sparklineData |
| `stat-pair` | StatPair | label, value, valueColor, bold, size |
| `status-cell` | StatusCell | label, value, description, icon, colorScheme |
| `insight-banner` | InsightBanner | title, subtitle, icon, colorScheme |
| `gradient-progress` | GradientProgress | value, label, colorScheme, autoColor, size |
| `section-header` | SectionHeader | title, subtitle, icon, colorScheme, size |

**Icon registry** (~20 icons covering financial/portfolio domain):
Shield, TrendingUp, TrendingDown, AlertTriangle, BarChart3, Target, DollarSign, Percent, Activity, PieChart, ArrowUpDown, Eye, Search, Info, CheckCircle, XCircle, Clock, Zap, Layers, Scale

**Modified files**:
- `ChatCore.tsx`: Replace Phase 0 hardcoded MetricCard with `<BlockRenderer>`. Extend `ExtendedChatMessage` (~line 187) to include `uiBlocks?: ParsedMessageSegment[]`. **Split the action footer** (~line 1028): currently `Regenerate`/`Retry` are nested inside the `message.actionable && message.actions` gate. Refactor to separate the two concerns: (a) **content-derived action buttons** (from `generateActionsForMessage()`) — skipped when `uiBlocks` is present (blocks provide their own actions via `UIBlockAction`), (b) **message-management controls** (`Regenerate`/`Retry`) — always rendered regardless of `uiBlocks`, moved outside the `actionable` gate.
- `usePortfolioChat.ts`: Use extracted `parseMessageContent()` from `chassis/src/services/parse-ui-blocks.ts`

**Icon fallback handling**: `InsightBanner` and `SectionHeader` require `icon` props. The `BlockRenderer` injects a default icon (`Info` from Lucide) when `resolveIcon()` returns undefined. This prevents runtime errors from unrecognized icon names. The `icon-registry.ts` exports an `IconName` string literal union for documentation/validation.

**DataTable deferred** — requires `render` functions in column specs, which can't be serialized. Solved in Phase 2.

---

### Phase 2: Layout System + DataTable

**Goal**: AI can compose blocks into grid/stack layouts. DataTable via declarative column DSL.

| New File | Purpose | ~Lines |
|----------|---------|--------|
| `ui/src/components/chat/blocks/layout-renderer.tsx` | `<LayoutRenderer spec={...} />` — grid/stack/row with gap control. **Responsive clamping**: columns are clamped based on container width — `≤640px`: max 1 column (stack), `≤1024px`: max 2 columns, `>1024px`: up to 4 columns. Uses CSS `grid-template-columns: repeat(min(columns, clamp), minmax(0, 1fr))` or equivalent Tailwind responsive classes. This ensures 3/4-column layouts degrade gracefully inside the chat bubble on mobile. | ~80 |
| `ui/src/components/chat/blocks/data-table-adapter.tsx` | Converts declarative column specs → DataTable `render` functions | ~80 |

**Layout spec** (extends the block protocol, uses `UIRenderableSpec` from Phase 0 types):
```typescript
interface UILayoutSpec {
  layout: 'grid' | 'stack' | 'row';
  columns?: number;     // grid: 1-4
  gap?: 'sm' | 'md' | 'lg';
  children: UIRenderableSpec[];  // Supports nested layouts
}
```

Example AI output — 3-metric dashboard:
```json
[{
  "layout": "grid", "columns": 3, "gap": "md",
  "children": [
    { "block": "metric-card", "props": { "label": "Total Value", "value": "$1.2M", "colorScheme": "emerald" }},
    { "block": "metric-card", "props": { "label": "Risk Score", "value": "72", "colorScheme": "amber" }},
    { "block": "metric-card", "props": { "label": "Sharpe", "value": "1.24", "colorScheme": "blue" }}
  ]
}]
```

**DataTable block spec** (declarative, no render functions):
```typescript
interface DataTableBlockProps {
  columns: DataTableColumnSpec[];
  data: Record<string, unknown>[];
  rowKey: string;  // Key field in each row object used for keyExtractor (required by DataTable)
  emptyMessage?: string;
}

interface DataTableColumnSpec {
  key: string;
  label: string;
  align?: 'left' | 'center' | 'right';
  format?: 'text' | 'number' | 'currency' | 'percent' | 'badge';
}
```

The adapter synthesizes `render` functions from `format` specs using existing formatters (`formatCurrency`, `formatPercent` from `lib/chart-theme.ts`, `PercentageBadge` component). It also synthesizes `keyExtractor` from the `rowKey` field: `(row) => String(row[rowKey])`.

**Modified files**:
- `block-renderer.tsx`: Dispatch to `LayoutRenderer` when spec has `layout` field
- `register-defaults.ts`: Add `data-table` registration with adapter
- `parse-ui-blocks.ts`: Handle `UILayoutSpec` in parsing

---

### Phase 3: Interactivity + System Prompt

**Goal**: Blocks can trigger chat actions. AI consistently produces good block specs.

**Action spec** (optional on any block):
```typescript
interface UIBlockAction {
  type: 'send-message' | 'navigate';
  payload: string;   // message text or view name
  label?: string;    // CTA button label
}
```

Example — clickable risk score card:
```json
{
  "block": "metric-card",
  "props": { "label": "Risk Score", "value": "72", "colorScheme": "amber" },
  "action": { "type": "send-message", "payload": "Show detailed risk analysis", "label": "Details" }
}
```

**Modified files**:
- `block-renderer.tsx`: Wrap blocks with click handler / append action button when `spec.action` present. Action handler receives both `sendMessage` and `onNavigate` callbacks.
- `ChatCore.tsx`: Pass `sendMessage` and `onChatNavigation` callbacks into block rendering pipeline. For `send-message` actions, call `sendMessage(payload)`. For `navigate` actions, call `onChatNavigation(payload)` directly — block actions use view IDs as payloads, bypassing `navigationMap` (which maps action types to view IDs for the legacy heuristic buttons). Context-aware: navigation only fires in modal chat context (matching existing `chatContext === 'modal'` guard at ~line 709). Valid `navigate` payloads (view IDs): `score`, `factors`, `performance`, `research`, `scenarios`.
- System prompt additions (gateway config): Document available blocks, when to use them, icon names, valid navigate targets, rules (always include text alongside blocks, only use for quantitative data)

---

## Package Boundaries

Per project rules (`@risk/ui` → chassis+connectors, `@risk/connectors` → chassis only, `@risk/chassis` → no workspace imports):

| Package | Owns |
|---------|------|
| `@risk/chassis` | `UIBlockSpec` type, `ParsedMessageSegment` type, `parseMessageContent()` utility (pure string→data, no UI imports) |
| `@risk/connectors` | Parsing call in `usePortfolioChat` (imports types + parser from `@risk/chassis`) |
| `@risk/ui` | Block registry, icon registry, renderers, layout system (all in `components/chat/blocks/`) |

---

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| AI produces invalid JSON | try/catch around JSON.parse in `parseMessageContent()`; on failure, the entire `:::ui-blocks...:::` section is stripped from `content` (blocks silently dropped, surrounding text preserved). No raw JSON ever shown to user or sent back to AI in history. |
| Unknown block name | BlockRenderer shows graceful "Unknown block" fallback |
| AI over-uses blocks | System prompt rules: only for quantitative data, always include text |
| Delimiter conflicts | `:::ui-blocks` is unlikely in natural text; easily detectable |
| Icon name mismatch | resolveIcon returns undefined → BlockRenderer injects default `Info` icon (see Phase 1 icon fallback handling) |
| Streaming visibility of blocks | Block regions buffered during streaming (replaced with placeholder); rendered on completion |
| Block-only responses lose history context | `parseMessageContent()` generates summary text when `cleanContent` is empty (see Content history handling) |
| Retry/regenerate stale history | Pre-existing issue: `sendMessage` closes over stale `messages` state, so retry/regenerate may replay discarded turns. Not introduced by this feature, but block messages make it more visible. **Follow-up task**: refactor `sendMessage` to read from a `messagesRef` (current transcript) rather than stale closure. |

---

## Key Files

### Existing (to modify)
- `frontend/packages/chassis/src/types/index.ts` — ChatMessage, MessagePart types (lines 561-611)
- `frontend/packages/chassis/src/services/GatewayClaudeService.ts` — SSE parsing, mapEvent (219 lines, confirms passthrough works unchanged)
- `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts` — Stream processing loop (lines 596-678)
- `frontend/packages/ui/src/components/chat/shared/ChatCore.tsx` — Message rendering (line ~1022)
- `frontend/packages/ui/src/components/blocks/index.ts` — Block library barrel (12 components)

### New (to create)
- `frontend/packages/chassis/src/services/parse-ui-blocks.ts` — Parser utility (exported via `services/index.ts` barrel so connectors can import from `@risk/chassis`)
- `frontend/packages/ui/src/components/chat/blocks/` — Registry, renderer, icon resolution, layout system

### Backend (no changes required)
- `routes/gateway_proxy.py` — Raw SSE passthrough, works as-is
- MCP tools — Return structured data as-is, AI decides when to emit blocks

---

## Verification

### Phase 0
1. `cd frontend && pnpm typecheck` — new types compile
2. `cd frontend && pnpm build` — no bundle errors
3. Manual test: hardcode a `:::ui-blocks` section in a mock message, verify MetricCard renders in chat
4. **Streaming safety test**: Verify that during active streaming (before completion), `:::ui-blocks` content is hidden from the rendered message. Simulate mid-stream abort and verify incomplete block sections are stripped. Test: mock `usePortfolioChat` streaming with partial `:::ui-blocks` content (no closing `:::`), abort, verify `content` shows no raw JSON.

### Phase 1
1. TypeScript: registry + renderer + parser all type-check
2. Unit tests: `parseMessageContent()` correctly splits text/blocks, handles edge cases (no blocks, multiple blocks, invalid JSON)
3. Unit tests: `BlockRenderer` renders correct component for each registered block, shows fallback for unknown
4. Visual: run dev server, send chat message with blocks, verify 6 block types render

### Phase 2
1. Layout grids render correctly at 1/2/3/4 columns on desktop
2. **Responsive test**: 3/4-column layouts clamp to 1 column on mobile viewport (≤640px) and 2 columns on tablet (≤1024px)
3. DataTable renders from column specs with currency/percent formatting, `rowKey` produces stable React keys
4. Nested layouts work (grid containing blocks)

### Phase 3
1. Click action on block sends follow-up message
2. Navigate action switches dashboard view
3. AI reliably produces valid block specs (test with common queries)
