# SPEC: Earnings Transcript Parser ✅ Completed

> **Status:** Fully implemented. `mcp_tools/transcripts.py` (843 lines), registered as `get_earnings_transcript` on fmp-mcp server.

## Goal

Make earnings call transcripts readable by an AI agent. Raw transcripts are 15-28KB of unstructured text — too large to dump into context and reason over effectively. The parser's job is **context management**: split the blob into navigable, filterable chunks (prepared remarks vs Q&A, per-speaker segments, individual Q&A exchanges) so an agent can scout, select, and read only what it needs.

## New File

`mcp_tools/transcripts.py`

## Files to Modify

- `fmp_mcp_server.py` — import and register `get_earnings_transcript` tool
- `mcp_tools/__init__.py` — add export

## Raw Data Format (from FMP)

Single-row DataFrame: `symbol, quarter, year, date, content`
- `content` field: full text, ~15-28KB, format is `"Speaker Name: their text..."` repeated
- Cached as Parquet in `cache/transcripts/` with `HASH_ONLY` refresh (immutable)

## MCP Tool Signature

```python
def get_earnings_transcript(
    symbol: str,
    year: int,
    quarter: int,
    section: Literal["prepared_remarks", "qa", "all"] = "all",
    filter_speaker: str | None = None,
    filter_role: Literal["CEO", "CFO", "COO", "CTO", "Analyst", "IR", "Operator"] | None = None,
    format: Literal["full", "summary"] = "full",
) -> dict:
    # Returns:
    # {
    #     "status": "success",
    #     "symbol": str, "year": int, "quarter": int, "date": str,
    #     "prepared_remarks": [{"speaker": str, "role": str, "text": str, "word_count": int}, ...],
    #     "qa": [{"speaker": str, "role": str, "text": str, "word_count": int}, ...],
    #     "qa_exchanges": [
    #         {"analyst": str, "question": str,
    #          "answers": [{"speaker": str, "role": str, "text": str}]},
    #     ],
    #     "metadata": {
    #         "total_word_count": int,
    #         "prepared_remarks_word_count": int,
    #         "qa_word_count": int,
    #         "speaker_list": [{"name": str, "role": str, "word_count": int}],
    #         "num_qa_exchanges": int,
    #         "num_speakers": int,
    #     },
    # }
```

## Core Functions

```python
def parse_transcript(content: str) -> dict:
    """Main parser. Returns prepared_remarks, qa, qa_exchanges, metadata."""

def parse_speakers(content: str) -> list[dict]:
    """Split raw text into speaker segments. Pattern: 'Name - Title: text...'"""

def classify_speaker_role(speaker_name, speaker_title, is_qa_section: bool) -> str:
    """Classify from title string + position. Q&A non-management = Analyst."""

def find_qa_boundary(segments: list[dict]) -> int | None:
    """Find segment index where Q&A begins."""
```

## Algorithm: Speaker Segmentation

```
Pattern: r'^([A-Z][a-zA-Z.\'-]+(?:\s+[A-Z][a-zA-Z.\'-]+){0,4})\s*(?:-\s*(.+?))?\s*:'

For each line:
    If matches pattern AND not a false positive (not "Note:", "Source:", etc.):
        Save previous segment, start new one
        Parse speaker name and optional title from "Name - Title:" format
    Else:
        Append to current segment's text
```

## Algorithm: Role Classification

Title-based + positional. Keep it simple — the parser's job is labeling for navigation, not analysis.

**From title string:**
- CEO: `\bCEO\b`, `Chief Executive Officer`, `President`
- CFO: `\bCFO\b`, `Chief Financial Officer`
- COO/CTO: same pattern
- IR: `Investor Relations`, `Director.*Investor`
- Operator: name is literally `"Operator"`

**Positional fallback (after Q&A boundary is found):**
- Any speaker in the Q&A section who isn't management or Operator → `"Analyst"`
- Analyst firm name is available in the title string if present (e.g., "John Smith - Morgan Stanley") — no need for a hardcoded firm list, the agent can read the title directly

**Default:** `"Other"` (pre-Q&A speakers without recognizable titles)

## Algorithm: Q&A Boundary Detection

1. Check for explicit markers: `"open.*question"`, `"Q&A"`, `"first question"` in QA_BOUNDARY_PATTERNS
2. Check for Operator segment containing "question"
3. Heuristic fallback: first Analyst speaker after ≥2 management speakers

## Algorithm: Q&A Exchange Structuring

Each exchange is a self-contained chunk: one analyst question + management response(s). This is the most useful unit for an agent — small enough to read in one shot, complete enough to reason over.

```
For each segment in Q&A:
    If role == Analyst: start new exchange (analyst name, question text)
    If role != Operator: append as answer to current exchange
    If role == Operator: treat as exchange separator
```

## Caching

- Parsed results cached as JSON in `cache/transcripts_parsed/`
- Cache key: `{SYMBOL}_{Q}Q{YY}_transcript_parsed.json`
- Raw transcript already cached by FMP client in `cache/transcripts/` (Parquet)

## MCP Registration Pattern

```python
# In fmp_mcp_server.py:
from mcp_tools.transcripts import get_earnings_transcript as _get_earnings_transcript

@mcp.tool()
def get_earnings_transcript(...) -> dict:
    """[docstring with examples for Claude]"""
    return _get_earnings_transcript(...)
```

Follow the existing pattern in `fmp_mcp_server.py`: import with underscore prefix, thin `@mcp.tool()` wrapper, docstring becomes AI instructions.

## Reuse from Existing Code

- `fmp.client.FMPClient().fetch("earnings_transcript", ...)` — fetches raw transcript
- `fmp/registry.py` line 482-498 — endpoint definition
- `mcp_tools/news_events.py` — reference pattern for stdout redirect, try/except, dict return
- `mcp_tools/fmp.py` — reference for error handling pattern (`_error_response`, `_map_exception_to_error`)

## Edge Cases

1. Speaker name variations mid-transcript ("Tim Cook" vs "Timothy D. Cook") — compare first + last name
2. No explicit Q&A boundary — fall back to first non-management, non-Operator speaker after ≥2 management speakers
3. Operator interjections — treat as exchange separators, not answers
4. Analyst follow-ups — separate exchanges per analyst turn
5. "Name - Title:" format — parse title separately from name, keep title as-is (agent can read firm name from it)
6. Non-standard formats: `**Speaker**:`, `[Speaker]:` — handle in regex
7. Short/empty transcripts (<500 chars) — return error
8. Unicode and HTML entities in speaker names — normalize before parsing
9. Metadata lines ("Company Participants:", "Disclaimer:") — filter out, not speaker segments

## Test Strategy

**Tickers:** AAPL (clean, well-known speakers), MSFT, NVDA (long Q&A), META, JPM (financial vocab)

**Tests:**
1. Speaker segmentation — all speakers identified, word counts sum correctly
2. Role classification — CEO/CFO correctly identified per ticker, analysts detected
3. Q&A boundary — prepared_remarks has no analysts, Q&A has analysts
4. Q&A exchanges — each has analyst question + management answer(s)
5. Filtering — `filter_role="CFO"` returns only CFO, `filter_speaker="Cook"` returns only Cook
6. Section filtering — `section="qa"` excludes prepared remarks
7. Summary mode — metadata only, no full text
8. Cache — first call writes JSON, second reads from cache
9. Error cases — invalid symbol, future quarter, empty content

## Verification

```bash
cd /Users/henrychien/Documents/Jupyter/risk_module
python -c "from mcp_tools.transcripts import get_earnings_transcript; import json; print(json.dumps(get_earnings_transcript('AAPL', 2024, 4, format='summary'), indent=2))"
```
Then test via MCP: restart fmp-mcp server, call `get_earnings_transcript(symbol="AAPL", year=2024, quarter=4, section="qa", filter_role="CFO")`
