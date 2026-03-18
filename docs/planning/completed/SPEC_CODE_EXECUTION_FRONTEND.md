# SPEC: Code Execution Frontend — Web App

**Depends on**: Gateway code execution support (landed in `AI-excel-addin` repo)

## Overview

The gateway now emits two new SSE event types for server-side code execution:
- `code_execution_start` — Claude began executing code in the sandbox
- `code_execution_result` — execution completed with stdout, stderr, files, or errors

The web frontend needs to map these events, process them in the streaming loop, and render the results. This is straightforward plumbing — follow the existing patterns for `tool_call_start` / `tool_result`.

---

## Changes

### 1. `frontend/packages/chassis/src/services/ClaudeStreamTypes.ts`

**Current type (lines 1-9):**
```typescript
export type ClaudeStreamChunk =
  | { type: 'text_delta'; content: string }
  | { type: 'tool_call_start'; tool_name: string; tool_input?: unknown }
  | { type: 'tool_call_delta'; content?: string; tool_input?: unknown }
  | { type: 'tool_call_end' }
  | { type: 'tool_result'; tool_call_id?: string; tool_name?: string; result?: unknown; error?: unknown }
  | { type: 'tool_approval_request'; tool_call_id: string; nonce: string; tool_name: string; tool_input: Record<string, unknown> }
  | { type: 'error'; content: string; error_type?: string; retry_suggested?: boolean }
  | { type: 'done' };
```

**Add two new union members** before the `error` line:
```typescript
  | { type: 'code_execution_start'; tool_call_id: string; name: string; code: string }
  | { type: 'code_execution_result'; tool_call_id: string; result_type: string; stdout: string; stderr: string; return_code?: number; error_code?: string; files: CodeExecutionFile[]; text_editor_output?: string }
```

**Add a new interface** after the `ClaudeStreamChunk` type:
```typescript
export interface CodeExecutionFile {
  file_id: string;
  media_type?: string;
  data_base64?: string;
  filename?: string;
  error?: string;
}
```

---

### 2. `frontend/packages/chassis/src/services/GatewayClaudeService.ts`

**In the `mapEvent()` method (lines 183-217),** add two new cases before the `case 'stream_complete':` line:

```typescript
    case 'code_execution_start':
      return {
        type: 'code_execution_start',
        tool_call_id: String(event.tool_call_id ?? ''),
        name: String(event.name ?? ''),
        code: String(event.code ?? ''),
      };
    case 'code_execution_result':
      return {
        type: 'code_execution_result',
        tool_call_id: String(event.tool_call_id ?? ''),
        result_type: String(event.result_type ?? ''),
        stdout: String(event.stdout ?? ''),
        stderr: String(event.stderr ?? ''),
        return_code: typeof event.return_code === 'number' ? event.return_code : undefined,
        error_code: typeof event.error_code === 'string' ? event.error_code : undefined,
        files: Array.isArray(event.files)
          ? (event.files as Record<string, unknown>[])
              .filter((f): f is Record<string, unknown> => f != null && typeof f === 'object')
              .map(f => ({
                file_id: String(f.file_id ?? ''),
                media_type: typeof f.media_type === 'string' ? f.media_type : undefined,
                data_base64: typeof f.data_base64 === 'string' ? f.data_base64 : undefined,
                filename: typeof f.filename === 'string' ? f.filename : undefined,
                error: typeof f.error === 'string' ? f.error : undefined,
              }))
          : [],
        text_editor_output: typeof event.text_editor_output === 'string' ? event.text_editor_output : undefined,
      };
```

Make sure to import `CodeExecutionFile` from `ClaudeStreamTypes` if needed (it's referenced by the chunk type).

#### 2b. History serialization — strip data URIs

**Problem:** `sendMessageStream()` (lines 107-113) replays `m.content` verbatim as chat history on every subsequent turn. Code execution image output embeds base64 data URIs (100-500 KB each) in `message.content`. Without stripping, every follow-up request carries the full base64 payload, causing token/perf regression.

**In `sendMessageStream()`,** update the `messages` construction (lines 107-113) to strip data URIs from history:

```typescript
    const messages = [
      ...history.map((m) => ({
        role: m.role ?? (m.type === 'assistant' ? 'assistant' : 'user'),
        content: typeof m.content === 'string'
          ? m.content.replace(/!\[([^\]]*)\]\(data:[^)]+\)/g, '[$1 image]')
          : m.content,
      })),
      { role: 'user', content: message },
    ];
```

This replaces `![Code output](data:image/png;base64,...)` with `[Code output image]` only in the serialized history sent to the gateway. The original `message.content` in React state is untouched, so images remain visible in the rendered chat transcript.

---

### 3. `frontend/packages/connectors/src/features/external/hooks/usePortfolioChat.ts`

**Add a helper function** at the top of the file (after imports, before the hook):

```typescript
/**
 * Sanitize code execution output before injecting into accumulatedContent.
 * Three concerns:
 * 1. stripUIBlocks() / parseMessageContent() match :::ui-blocks, :::artifact, and
 *    closing ::: via indexOf and regex. Any run of 3+ colons is broken by inserting
 *    zero-width spaces between EVERY character in the run (e.g. ::: → :\u200B:\u200B:,
 *    :::: → :\u200B:\u200B:\u200B:). No substring of the result can form 3 consecutive
 *    colons, so all parser patterns are neutralized.
 * 2. Output containing ``` or longer backtick runs would break out of the markdown
 *    code fence. Same treatment: insert ZWS between every character in runs of 3+
 *    backticks, preventing any valid fence delimiter from surviving.
 */
function sanitizeCodeOutput(text: string): string {
  return text
    .replace(/:{3,}/g, m => m.split('').join('\u200B'))
    .replace(/`{3,}/g, m => m.split('').join('\u200B'));
}

/** Raster image MIME types safe for data: URI rendering. */
const SAFE_IMAGE_MIMES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'] as const;

/**
 * Sanitize a short metadata field (name, filename, error, error_code) for safe
 * interpolation into ANY markdown context — code fence info strings, inline code
 * spans, emphasis, link labels, and plain text.
 *
 * Strategy: strip characters that are structurally meaningful in markdown rather
 * than trying to escape them (backslash escaping is unreliable in info strings
 * and inline code spans per CommonMark spec).
 */
function sanitizeInline(text: string): string {
  return text
    .replace(/[\r\n]+/g, ' ')        // flatten to single line
    .replace(/[`*_~\[\]()\\]/g, '')  // strip markdown-structural chars
    .replace(/:{3,}/g, m => m.split('').join('\u200B')); // break block markers
}

```

**In the streaming loop (around line 663),** add two new `else if` blocks after the `tool_call_start` handler and before the `tool_approval_request` handler:

```typescript
else if (chunk.type === 'code_execution_start') {
    // Show the code being executed so the user knows what ran
    const lang = sanitizeInline(chunk.name || 'python');
    accumulatedContent += `\n\`\`\`${lang}\n${sanitizeCodeOutput(chunk.code)}\n\`\`\`\n`;
    const displayContent = stripUIBlocks(accumulatedContent);
    setMessages(prev => prev.map(msg =>
        msg.id === assistantMessageId
            ? { ...msg, content: displayContent }
            : msg
    ));
    setChatStatus({
        state: 'tool-executing',
        message: `Running ${lang} code...`,
        progress: { currentTool: chunk.name || 'code_execution' },
    });
}
else if (chunk.type === 'code_execution_result') {
    // Render stdout as code block (sanitize to prevent parser/fence breakout)
    if (chunk.stdout) {
        accumulatedContent += `\n\`\`\`\n${sanitizeCodeOutput(chunk.stdout)}\n\`\`\`\n`;
    }
    if (chunk.stderr) {
        accumulatedContent += `\n**stderr:**\n\`\`\`\n${sanitizeCodeOutput(chunk.stderr)}\n\`\`\`\n`;
    }
    // Render error_code (sanitize inline to prevent markdown breakout)
    if (chunk.error_code) {
        accumulatedContent += `\n**Error:** \`${sanitizeInline(chunk.error_code)}\`\n`;
    }
    // Render non-zero return code when no error_code already covers it
    if (chunk.return_code != null && chunk.return_code !== 0 && !chunk.error_code) {
        accumulatedContent += `\n**Exited with code ${chunk.return_code}**\n`;
    }
    if (chunk.text_editor_output) {
        accumulatedContent += `\n\`\`\`\n${sanitizeCodeOutput(chunk.text_editor_output)}\n\`\`\`\n`;
    }
    // Render file outputs — only raster images via data: URIs
    // SVG (script-capable) and non-image types show as text placeholders
    for (const file of chunk.files) {
        const safeLabel = sanitizeInline(file.filename || file.file_id);
        if (file.error) {
            accumulatedContent += `\nFailed to load file ${safeLabel}: ${sanitizeInline(file.error)}\n`;
        } else if (
            file.data_base64
            && file.media_type
            && (SAFE_IMAGE_MIMES as readonly string[]).includes(file.media_type)
        ) {
            // media_type is validated against allowlist — safe to interpolate
            accumulatedContent += `\n![Code output](data:${file.media_type};base64,${file.data_base64})\n`;
        } else if (file.data_base64 && file.media_type) {
            // Non-raster or unsafe MIME — show as labeled placeholder
            accumulatedContent += `\nFile: ${safeLabel} (${sanitizeInline(file.media_type)})\n`;
        } else {
            // File with no data and no error — show placeholder
            accumulatedContent += `\nFile: ${safeLabel}\n`;
        }
    }
    // Update display
    const displayContent = stripUIBlocks(accumulatedContent);
    setMessages(prev => prev.map(msg =>
        msg.id === assistantMessageId
            ? { ...msg, content: displayContent }
            : msg
    ));
}
```

No changes needed at the streaming completion block — images persist in `message.content` for display. Data URIs are stripped at the serialization boundary in `GatewayClaudeService` (see Section 2b below).

---

### 4. `frontend/packages/ui/src/components/chat/shared/MarkdownRenderer.tsx`

**Problem:** react-markdown v10's default `urlTransform` strips `data:` URLs. Code execution file output uses `data:` URIs for inline images and downloads.

**Add a custom `urlTransform`** that allows raster `data:image/` URLs alongside the default safe protocols:

```typescript
import { defaultUrlTransform } from 'react-markdown';

/** Raster MIME prefixes safe for data: URI rendering (no SVG — script-capable). */
const SAFE_DATA_PREFIXES = [
  'data:image/png',
  'data:image/jpeg',
  'data:image/gif',
  'data:image/webp',
] as const;

/**
 * Extend react-markdown's default URL sanitizer to also allow raster data: URIs
 * (used for inline code execution file output — charts, plots).
 * Only raster image types are allowed; SVG and non-image types are blocked.
 */
function urlTransform(url: string): string | null {
  if (SAFE_DATA_PREFIXES.some(prefix => url.startsWith(prefix))) {
    return url;
  }
  return defaultUrlTransform(url);
}
```

**Update the `<Markdown>` component** to pass this prop:

```diff
-      <Markdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>{content}</Markdown>
+      <Markdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]} urlTransform={urlTransform}>{content}</Markdown>
```

---

### 5. `frontend/packages/ui/src/components/onboarding/NormalizerBuilderPanel.tsx`

**Context:** This component also consumes `GatewayClaudeService.sendMessageStream()`. It will compile unchanged but silently ignore code execution events.

**In the streaming loop (around line 168, after the `tool_call_start` handler),** add a minimal handler so the user sees status:

```typescript
if (chunk.type === 'code_execution_start') {
  setStatusText('Running code...');
  continue;
}
```

No output rendering needed here — the normalizer builder workflow is text-focused.

---

### 6. `frontend/packages/chassis/src/services/index.ts`

**Add `CodeExecutionFile` to the type re-export** on line 71 so downstream packages can import it from `@risk/chassis`:

```diff
-export type { ClaudeStreamChunk } from './ClaudeStreamTypes';
+export type { ClaudeStreamChunk, CodeExecutionFile } from './ClaudeStreamTypes';
```

---

## Verification

1. `npm run typecheck` should pass (no type errors from new chunk types)
2. `npm run build` should succeed
3. Manual test: open the web chat, send "use code execution to compute 2+2" — should see "Running python code..." status, the code block, and the result rendered
4. Verify inline image rendering: send a prompt that triggers matplotlib output — image should render inline
5. Verify block marker safety: send a prompt whose code prints `:::ui-blocks` to stdout — should render as plain text, not trigger UI block parsing

## Do NOT

- Change any backend/gateway files (already done in `AI-excel-addin` repo)
- Add tests (separate task)
- Change ChatCore or other chat components beyond MarkdownRenderer
