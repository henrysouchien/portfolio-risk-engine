# System Prompt Update for UI Blocks Protocol

## Context

Phase 0 of the Dynamic UI Generation feature is implemented and committed (`694b8c2c`). The frontend rendering pipeline works end-to-end:
- `parseMessageContent()` in `@risk/chassis` extracts `:::ui-blocks` sections from AI text
- `stripUIBlocks()` hides raw JSON during streaming
- ChatCore's segment walker renders MetricCard components inline in chat
- Verified via console-injected test message (3 MetricCards rendered in grid)

**The missing piece:** the AI doesn't know about the `:::ui-blocks` protocol. We need to add a system prompt section to the gateway so the web-channel AI emits block specs in its responses.

## What Changes

**One file:** `AI-excel-addin/api/tools.py`

### Change 1: Add `_build_ui_blocks_section()` function

New section builder function (alongside existing `_build_general_rules_section()`, `_build_edgar_section()`, etc.). Returns prompt text teaching the AI the protocol.

Insert near line 1430 (after `_build_knowledge_sources_section`, before `_build_deferred_tools_section`).

### Change 2: Wire into `build_system_prompt()` for web channel only

In `build_system_prompt()` (~line 1550), add:

```python
if channel_context == "web":
    sections.append(_build_ui_blocks_section())
```

After the knowledge sources section, before the deferred tools section.

## Channel Gating

| Channel | Renders blocks? | Gets prompt section? |
|---------|----------------|---------------------|
| `None` (Excel add-in) | No — plain text in Excel cells | No |
| `"web"` (React frontend) | Yes — MetricCard React components | Yes |
| `"telegram"` (Telegram bot) | No — Telegram markdown only | No |

The frontend sends `channel: 'web'` in `GatewayClaudeService.ts:122`. The gateway reads it from `body.context.channel` in `main.py:342-343`.

## Prompt Content

```python
def _build_ui_blocks_section() -> str:
    return """\
## Rich UI Blocks
When presenting quantitative metrics or scores, you can emit structured UI blocks
that the frontend renders as styled card components. Wrap a JSON array in delimiters:

:::ui-blocks
[{"block":"metric-card","props":{"label":"Risk Score","value":"72/100","colorScheme":"amber"}}]
:::

Available block: metric-card
  Props: label (required), value (required), description, change, colorScheme
  Color schemes: emerald (positive/good), blue (neutral/info), amber (caution),
                 red (negative/alert), purple, indigo, neutral

Rules:
- Always include explanatory text before or after blocks. Never emit blocks alone.
- Use blocks only for numeric metrics, scores, and ratios. Not for prose or lists.
- Group 2-4 related metrics in one :::ui-blocks section (renders as a responsive grid).
- Use colorScheme to convey meaning: emerald=good, amber=caution, red=alert, blue=info.
- Do NOT wrap :::ui-blocks in Markdown code fences or backticks. Emit the delimiters raw.
- Each delimiter must be on its own line. Opening :::ui-blocks on one line, JSON on the next, closing ::: on its own line. Never inline them.
- The JSON array must be valid. Single-line preferred but multi-line is also accepted.
- Multiple :::ui-blocks sections can appear in one message, interleaved with text.
"""
```

## Key Design Decisions

1. **Concise prompt (~15 lines):** The AI doesn't need verbose instructions. One example, the prop list, and clear rules.
2. **Single block type for now:** Only `metric-card` is registered in Phase 0. More types (insight-banner, status-cell, etc.) will be added in Phase 1 and the prompt updated accordingly.
3. **No code fences rule:** Models default to wrapping JSON in ` ```json ``` ` fences. The parser only strips `:::ui-blocks...:::` regions, so fenced output would leave stray backticks in chat. Explicit prohibition required.
4. **Single-line JSON preferred, not required:** The parser (`JSON.parse` on trimmed content between fences) handles multi-line JSON fine. Single-line is recommended for compactness but not a parser constraint.
5. **Color scheme semantics:** Giving the AI semantic guidance (emerald=good, red=alert) produces better color choices than just listing names.

## Verification

### Automated Tests (in `AI-excel-addin/tests/test_web_channel.py`)

Add tests alongside existing channel/prompt tests:

1. `test_web_channel_includes_ui_blocks_section` — `build_system_prompt(context={}, channel_context="web")` output contains `"Rich UI Blocks"` and `":::ui-blocks"`
2. `test_excel_channel_excludes_ui_blocks_section` — `build_system_prompt(context={}, channel_context=None)` output does NOT contain `":::ui-blocks"`
3. `test_telegram_channel_excludes_ui_blocks_section` — `build_system_prompt(context={}, channel_context="telegram")` output does NOT contain `":::ui-blocks"`
4. `test_ui_blocks_prompt_contains_safety_rules` — web prompt contains key parser-safety strings: `"Do NOT wrap"`, `"own line"`, `"code fences"` (ensures critical rules survive future edits)

### Manual Verification

1. Restart the gateway service
2. Open AI Assistant (web frontend, localhost:3000)
3. Ask "What is my risk score?" — AI should emit `:::ui-blocks` with MetricCards for key metrics
4. Ask "What does leverage mean?" — AI should respond with text only, no blocks
5. Verify MetricCards render as styled components in the chat (not raw JSON)
6. Check that streaming works — raw JSON should be hidden during stream, cards appear on completion

## Files

| File | Change | Lines |
|------|--------|-------|
| `AI-excel-addin/api/tools.py` | Add `_build_ui_blocks_section()` | ~15 new |
| `AI-excel-addin/api/tools.py` | Add `if channel_context == "web":` gate in `build_system_prompt()` | 2 new |
| `AI-excel-addin/tests/test_web_channel.py` | Add 4 channel-gating + content tests | ~25 new |
