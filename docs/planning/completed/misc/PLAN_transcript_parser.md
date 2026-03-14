# PLAN: Earnings Transcript Parser Implementation ✅ Completed

> **Status:** Fully implemented. `mcp_tools/transcripts.py` (843 lines), registered as `get_earnings_transcript` on fmp-mcp server.

## Codebase Findings

Before detailing the plan, here are critical findings from exploring all 15 cached transcripts that differ from assumptions in the spec:

**1. Format is simpler than the spec assumes.** Every FMP transcript across all 15 cached files uses a strict one-line-per-speaker format: `Name: text...`. There is NO `Name - Title:` pattern. Each speaker segment is exactly one newline-delimited line. Verified across AAPL, AMZN, GOOGL, TTD, CRTO, ROKU, DSP, DV, FIG, IAS, IT, MGNI, PUBM, RAMP, APP -- zero exceptions, zero diff between line count and speaker count.

**2. Role identification requires parsing the introductory remarks.** The IR speaker's opening segment (typically line 0 or line 1) contains role-name mappings like `"Apple CEO, Tim Cook, and CFO, Luca Maestri"`. The Operator lines contain analyst-firm mappings like `"Our next question is from Erik Woodring with Morgan Stanley."` There is no structured title field.

**3. No multi-line segments exist.** The regex-based "accumulate lines into current segment" logic from the spec is unnecessary. Parsing is a simple line split + regex match on each line. However, the implementation should still handle multi-line as a defensive measure in case FMP changes format.

**4. `FMPClient.fetch()` returns a single-row DataFrame** with columns `[symbol, quarter, year, date, content]`. The `content` column is a string of 30-65KB. Use `fetch()` not `fetch_raw()` to benefit from existing Parquet caching in `cache/transcripts/`.

**5. Existing caching is Parquet-only** via `fmp/cache.py`. The spec calls for a JSON parsed-result cache in `cache/transcripts_parsed/`. This is a new pattern not used elsewhere in mcp_tools. The `cache/transcripts/` directory already exists with 15 cached parquet files.

---

## Implementation Order

Three files to create/modify:

1. **New file**: `mcp_tools/transcripts.py` (core logic -- all parsing + MCP tool function)
2. **Modify**: `mcp_tools/__init__.py` (add export)
3. **Modify**: `fmp_mcp_server.py` (register MCP tool)

Dependencies: File 2 and 3 depend on File 1 existing. File 2 and 3 are independent of each other.

---

## File 1: `mcp_tools/transcripts.py` (NEW)

### Module-Level Structure

```python
"""
MCP Tool: get_earnings_transcript

Parses earnings call transcripts into navigable, filterable chunks.
Raw transcripts are 15-65KB of unstructured text. This tool splits them
into prepared remarks, Q&A segments, and individual Q&A exchanges so
an agent can scout, select, and read only what it needs.

Follows the agent-tool response protocol (see PROTOCOL_agent_tool_responses.md):
- Default format="summary" returns metadata only (speaker list, word counts,
  exchange count). No text content. Costs ~1 KB of context.
- format="full" returns text content, with each text field truncated to
  max_words (default 3000) to protect the agent's context window.
- Truncated fields include a continuation marker:
  "...[truncated — N more words remaining]"

Architecture note:
- Fetches raw transcript via FMPClient.fetch() (returns single-row DataFrame)
- Parses into speaker segments, classifies roles, detects Q&A boundary
- Caches parsed result as JSON in cache/transcripts_parsed/
- Registered on fmp-mcp server
- stdout is redirected to stderr to protect MCP JSON-RPC channel from stray prints
"""

import html
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fmp.client import FMPClient
from fmp.exceptions import FMPEmptyResponseError
```

### Constants

```python
# Parser version for cache invalidation. Bump when parsing logic changes.
# Included in cache filename so old caches are naturally bypassed.
PARSER_VERSION = 1

# False positive speaker names to ignore (these appear as "Note:", "Source:", etc.)
FALSE_POSITIVE_SPEAKERS = frozenset({
    "Note", "Source", "Disclaimer", "Company", "Forward",
    "Safe", "Harbor", "Important", "Copyright",
})

# Speaker regex: captures "Name:" at start of line
# FMP transcripts use "Name: text..." format (one line per speaker)
SPEAKER_PATTERN = re.compile(
    r'^([A-Z][a-zA-Z.\'\-]+(?:\s+[A-Z][a-zA-Z.\'\-]+){0,4})\s*:'
)

# Patterns to detect Q&A boundary in speaker text
QA_BOUNDARY_PATTERNS = [
    re.compile(r'open.*(?:call|line).*(?:question|Q&A)', re.IGNORECASE),
    re.compile(r'(?:first|begin|start)\s+(?:the\s+)?question', re.IGNORECASE),
    re.compile(r'Q\s*&\s*A\s+(?:session|portion|segment)', re.IGNORECASE),
    re.compile(r'open\s+(?:it\s+)?up\s+(?:for|to)\s+question', re.IGNORECASE),
    re.compile(r'take\s+(?:our\s+)?(?:first\s+)?question', re.IGNORECASE),
]

# Role detection patterns (applied to intro text to build name->role mapping)
ROLE_PATTERNS = {
    "CEO": re.compile(
        r'\bCEO\b|Chief\s+Executive\s+Officer|'
        r'(?<!\bVice\s)(?<!\bSenior\s)\bPresident\b(?!\s+of\s+(?:Investor|IR|Finance|Financial))',
        re.IGNORECASE,
    ),
    "CFO": re.compile(r'\bCFO\b|Chief\s+Financial\s+Officer', re.IGNORECASE),
    "COO": re.compile(r'\bCOO\b|Chief\s+Operating\s+Officer', re.IGNORECASE),
    "CTO": re.compile(r'\bCTO\b|Chief\s+Technology\s+Officer', re.IGNORECASE),
    "IR": re.compile(
        r'Investor\s+Relations|Director.*Investor|Head\s+of\s+Investor',
        re.IGNORECASE,
    ),
}

# Analyst introduction patterns in Operator text
# Multiple patterns tried in order (first match wins). Covers observed Operator phrasings:
#   "question from Name with Firm"
#   "question comes from Name with Firm"
#   "is from Name with Firm"
#   "line of Name with Firm"
#   "will come from Name with Firm"
#   "Name from Firm" (simpler fallback)
ANALYST_INTRO_PATTERNS = [
    # Primary: "question from/comes from/is from Name with/from/of Firm"
    re.compile(
        r'(?:question\s+(?:from|comes\s+from|is\s+from)|turn.*over\s+to)\s+'
        r'([A-Z][a-zA-Z.\'\-]+(?:\s+[A-Z][a-zA-Z.\'\-]+){0,3})'
        r'\s+(?:with|from|of|at)\s+(.+?)(?:\.|Please|$)',
        re.IGNORECASE,
    ),
    # "line of Name with Firm"
    re.compile(
        r'line\s+of\s+'
        r'([A-Z][a-zA-Z.\'\-]+(?:\s+[A-Z][a-zA-Z.\'\-]+){0,3})'
        r'\s+(?:with|from|of|at)\s+(.+?)(?:\.|Please|$)',
        re.IGNORECASE,
    ),
    # "will come from Name with/of Firm"
    re.compile(
        r'will\s+come\s+from\s+'
        r'([A-Z][a-zA-Z.\'\-]+(?:\s+[A-Z][a-zA-Z.\'\-]+){0,3})'
        r'\s+(?:with|from|of|at)\s+(.+?)(?:\.|Please|$)',
        re.IGNORECASE,
    ),
    # Simple fallback: "Name from Firm" (only in Operator segments)
    re.compile(
        r'([A-Z][a-zA-Z.\'\-]+(?:\s+[A-Z][a-zA-Z.\'\-]+){0,3})'
        r'\s+(?:from|with)\s+(.+?)(?:\.|Please|Your|$)',
        re.IGNORECASE,
    ),
]

# Cache directory for parsed results (JSON, not Parquet)
PARSED_CACHE_DIR = Path(__file__).parent.parent / "cache" / "transcripts_parsed"
```

### Function 0 (preprocessing): `_normalize_content`

```python
def _normalize_content(content: str) -> str:
    """
    Normalize raw transcript text before speaker parsing.

    Handles edge cases from the spec that can appear in FMP data:
    - Markdown bold speaker names: **Speaker**: -> Speaker:
    - Bracketed speaker names: [Speaker]: -> Speaker:
    - Unicode dashes (em-dash, en-dash) -> ASCII hyphen
    - Unicode quotes (curly single/double) -> ASCII quotes
    - Common HTML entities: &amp; -> &, &quot; -> ", &#39; -> ', etc.
    """
```

**Implementation:** A few simple regex/string replacements, applied once before `parse_speakers`:
```python
import html

def _normalize_content(content: str) -> str:
    # Decode HTML entities (&amp; &quot; &#39; etc.)
    content = html.unescape(content)
    # Strip markdown bold from line starts: **Name**: -> Name:
    content = re.sub(r'^\*\*(.+?)\*\*\s*:', r'\1:', content, flags=re.MULTILINE)
    # Strip brackets from line starts: [Name]: -> Name:
    content = re.sub(r'^\[(.+?)\]\s*:', r'\1:', content, flags=re.MULTILINE)
    # Normalize unicode dashes to ASCII hyphen
    content = content.replace('\u2013', '-').replace('\u2014', '-')
    # Normalize unicode quotes to ASCII
    content = content.replace('\u2018', "'").replace('\u2019', "'")
    content = content.replace('\u201c', '"').replace('\u201d', '"')
    return content
```

### Function 1: `parse_speakers`

```python
def parse_speakers(content: str) -> list[dict]:
    """
    Split raw transcript text into speaker segments.

    Args:
        content: Raw transcript text from FMP (one speaker per line).
                 Should be pre-normalized via _normalize_content().

    Returns:
        List of dicts: [{"speaker": str, "text": str, "line_index": int}, ...]
        Each dict represents one speaker turn.
    """
```

**Implementation details:**
- Split content on `\n`.
- For each non-empty line, apply `SPEAKER_PATTERN` regex.
- If match found and name not in `FALSE_POSITIVE_SPEAKERS`, create a new segment dict with `speaker`, `text` (everything after the `Name:` prefix, stripped), and `line_index`.
- If no match (should be rare/impossible given findings, but defensive), append text to previous segment's `text` field with a space separator.
- Return the list of segment dicts.

**Key detail:** Strip the `Name:` prefix from the text. The colon and any leading whitespace after it should be removed. Use `line[match.end():].strip()` to get the text.

### Function 2: `find_qa_boundary`

```python
def find_qa_boundary(segments: list[dict]) -> int | None:
    """
    Find the segment index where Q&A begins.

    Strategy (in priority order):
    1. Explicit text markers in literal "Operator" segments ONLY ("open the call
       to questions", "Q&A session"). Only segments where speaker == "Operator"
       are eligible. This avoids false-firing on IR hosts who use similar language
       in prepared remarks.
    2. Literal "Operator" segment containing "question" at segment index >= 3, AND
       at least 2 unique non-Operator speakers must have appeared before. Prevents
       false-firing on opening Operator instructions (DSP, IT, RAMP).
    3. Heuristic fallback (handles transcripts WITHOUT literal "Operator", e.g. PUBM):
       First NEW speaker after >=3 unique non-Operator speakers, where the
       immediately preceding segment (i-1 only) contains an explicit Q&A
       transition cue (regex: "first question", "next question",
       "ask a question", "go ahead", "line is open"). Broad cues like "q&a"
       and "question(s)" are intentionally excluded — they appear in early
       intro segments and cause false triggers. The 3-speaker threshold ensures
       the management block has completed; the narrow cue check prevents
       triggering on new management speakers.

    Returns:
        Index into segments list where Q&A starts, or None if no Q&A found.
    """
```

**Implementation details:**
- **Strategy 1:** Iterate all segments. For each, test `segment["text"]` against each pattern in `QA_BOUNDARY_PATTERNS` — but ONLY if `segment["speaker"].strip().lower() == "operator"` (literal match). No moderator heuristic — only the literal "Operator" name. This avoids the regression where IR hosts (e.g., Suhasini Chandramouli in AAPL) use similar language and get misclassified as moderators, causing Strategy 1 to fire on their prepared remarks. If a match is found, return `i + 1`. Clamp to len(segments).
- **Strategy 2:** Find the first literal "Operator" segment whose text contains the word "question", subject to two guards: (a) segment index >= 3, and (b) at least 2 unique non-Operator speakers before this segment. Return `i`.
- **Strategy 3 (fallback — handles no-Operator transcripts like PUBM):** Track `seen_speakers: set[str]` (excluding "Operator"). After 3+ unique speakers have appeared, for each subsequent NEW speaker, check whether the immediately preceding segment (i-1 only) contains an explicit Q&A transition cue (regex: "first question", "next question", "ask a question", "go ahead", "line is open"). Broad cues like "q&a" and "question(s)" are intentionally excluded — they appear in early intro segments (e.g., PUBM's Stacie at index 1 says "live Q&A") and cause false triggers. This two-part check (3+ prior speakers + narrow cue in i-1) prevents false-firing on new management speakers (e.g., PUBM's Steven at index 3, where i-1 has no transition cue) while correctly identifying the first analyst (e.g., PUBM's Andrew Boone at index 5, where i-1 has explicit transition language).
- Return `None` if none of the strategies find a boundary (transcript may have no Q&A).

**Key detail:** Strategy 1 returns `i + 1` (the segment after the marker). Strategy 2 returns `i` (the Operator segment itself is the start of Q&A). This distinction matters because the IR speaker who says "open to questions" is still part of prepared remarks, but the Operator who says "first question from..." is part of Q&A.

### Function 3: `classify_roles`

```python
def classify_roles(
    segments: list[dict],
    qa_boundary: int | None,
) -> None:
    """
    Classify each speaker's role. Mutates segments in place, adding
    'role' and 'firm' keys to each segment dict.

    Strategy:
    1. "Operator" name -> role="Operator"
    2. Parse early segments (IR intro text) for "CEO, Name" / "Name, CEO" patterns
       to build a name->role mapping for management speakers
    3. Parse Operator text for analyst introductions
       ("question from Name with Firm") to build analyst->firm mapping
    4. Apply known mappings to all segments
    5. After Q&A boundary: remaining unknown speakers -> "Analyst"
    6. Before Q&A boundary: remaining unknown speakers -> "Other"
    """
```

**Implementation details:**

- **Step 1 -- Operator detection:** If `segment["speaker"].strip().lower() == "operator"`, set `role = "Operator"`, `firm = ""`.

- **Step 2 -- Management role extraction from intro text:**
  Scan ALL segments in the first half of the transcript (up to the Q&A boundary if known, otherwise first 50% of segments) for role mappings. Include Operator segments — some transcripts (e.g., DSP) have CEO/COO/CFO role mappings in the opening Operator text. Stop scanning at the Q&A boundary to avoid picking up false role references from analyst questions (e.g., an analyst quoting "the CEO said..." should not create a role mapping).

  The text of early segments often contains patterns like:
  - `"Apple CEO, Tim Cook, and CFO, Luca Maestri"` (Role, Name pattern)
  - `"CEO and Co-Founder, Jeff Green; and Chief Financial Officer, Alex Kayyal"` (Role, Name pattern)
  - `"Chief Executive Officer, Michael Komasinski; and Chief Financial Officer, Sarah Glickman"` (Role, Name pattern)
  - `"My name is Suhasini Chandramouli, Director of Investor Relations"` (self-identification)

  Use regex to extract these. For each ROLE_PATTERNS key, search the intro text. When a role keyword is found, look for the nearest proper-noun name (capitalized words) adjacent to it. Build a `name_to_role: dict[str, str]` mapping.

  **Specific regex approach:** For each segment's text (all segments, not just first 3-4), try these patterns:
  - `r'(CEO|CFO|COO|CTO|Chief\s+\w+\s+Officer)[,\s]+(?:and\s+)?(?:Co-Founder[,\s]+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})'` -- Role then Name
  - `r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})[,\s]+(?:our\s+)?(?:the\s+)?(CEO|CFO|COO|CTO)'` -- Name then Role
  - Also check for self-identification: if the segment speaker's own text contains "Director of Investor Relations" or "Investor Relations", map that speaker to "IR".

- **Step 3 -- Analyst identification from Operator lines:**
  For each Operator segment, try each pattern in `ANALYST_INTRO_PATTERNS` (in order) against the segment text. Use the first match. Extract analyst name + firm. Build an `analyst_firms: dict[str, str]` mapping (analyst_name -> firm_name).

- **Step 4 -- Apply mappings:** For each segment:
  - If speaker is "Operator", already handled.
  - If speaker name matches a key in `name_to_role` (use `_names_match()` helper for fuzzy matching), set role.
  - If speaker name matches a key in `analyst_firms`, set `role = "Analyst"` and `firm = analyst_firms[name]`.
  - If the speaker's own text in an early segment contains an IR-related keyword and the speaker hasn't been classified yet, set `role = "IR"`.

- **Step 5 -- Positional fallback (with management guard):**
  Before applying the fallback, build a `known_management_speakers: set[str]` containing all speaker names that appeared in segments before `qa_boundary` (excluding "Operator"). Any speaker who spoke during prepared remarks is presumed to be management, even if their explicit role wasn't identified by Step 2.

  For segments at or after `qa_boundary`:
  - If role is still unset and speaker is not "Operator":
    - **If the speaker is in `known_management_speakers`** (they spoke in prepared remarks), set `role = "Other"`, `firm = ""`. Do NOT default them to "Analyst" -- they are management returning to answer questions.
    - **If the speaker is NOT in `known_management_speakers`** and not in `name_to_role`, set `role = "Analyst"`, `firm = ""`.

  This prevents unknown post-boundary management speakers from being misclassified as "Analyst", which would corrupt exchange structure (they'd start new question turns instead of being grouped as answerers).

- **Step 6 -- Default:** Any remaining unclassified segments (before Q&A boundary) get `role = "Other"`, `firm = ""`.

**Name matching helper:**
```python
def _names_match(name_a: str, name_b: str) -> bool:
    """
    Fuzzy name match. Returns True if last names match and first names
    share a 3+ character prefix. Handles "Tim Cook" vs "Timothy Cook".
    """
```
Split each name into words. Compare last words (last name). If they match, compare first words: if one is a prefix of the other (min 3 chars), return True. Also return True on exact full-string match.

### Function 4: `build_qa_exchanges`

```python
def build_qa_exchanges(qa_segments: list[dict]) -> list[dict]:
    """
    Group Q&A segments into analyst question + management answer exchanges.

    Each exchange: one analyst asks, one or more management respond.
    Operator segments act as exchange separators (not included in exchanges).

    Returns:
        List of exchange dicts:
        [{"analyst": str, "firm": str, "question": str,
          "answers": [{"speaker": str, "role": str, "text": str}]}, ...]
    """
```

**Implementation details:**
- Initialize `current_exchange = None` and `exchanges = []`.
- Iterate over `qa_segments`:
  - If `role == "Operator"`: if `current_exchange` is not None and has content, append it to `exchanges`. Set `current_exchange = None`. Continue.
  - If `role == "Analyst"`:
    - If `current_exchange` is not None and `current_exchange` already has answers (meaning an analyst is asking a follow-up after management answered), finalize the current exchange and start a new one.
    - If `current_exchange` is not None and has NO answers yet (same analyst continuing their question), append this text to the current exchange's question.
    - If `current_exchange` is None, start a new exchange: `{"analyst": speaker, "firm": firm, "question": text, "answers": []}`.
  - If any other role (CEO, CFO, IR, Other, etc.): if `current_exchange` is not None, append `{"speaker": speaker, "role": role, "text": text}` to `current_exchange["answers"]`.
- After loop: if `current_exchange` is not None and has content, append to `exchanges`.
- Return `exchanges`.

**Edge case -- analyst follow-ups:** If the same analyst speaks twice in a row (no Operator in between, no management answer in between), concatenate into the same question. If the analyst speaks again AFTER management answered, that starts a new exchange.

### Function 5: `parse_transcript`

```python
def parse_transcript(content: str) -> dict:
    """
    Main parser. Splits transcript into structured sections.

    Args:
        content: Raw transcript text from FMP.

    Returns:
        Dict with keys: prepared_remarks, qa, qa_exchanges, metadata.
    """
```

**Implementation details -- call order matters:**
1. `content = _normalize_content(content)` -- preprocess: strip markdown bold/brackets, normalize unicode, decode HTML entities
2. `segments = parse_speakers(content)` -- split into speaker turns
3. `qa_boundary = find_qa_boundary(segments)` -- detect where Q&A starts
4. `classify_roles(segments, qa_boundary)` -- add role/firm to each segment (needs boundary for positional fallback)
5. Split segments: `prepared_remarks = segments[:qa_boundary]`, `qa = segments[qa_boundary:]` (if boundary is None, everything is prepared_remarks, qa is empty)
6. `qa_exchanges = build_qa_exchanges(qa)` -- group Q&A into exchanges
7. Format output segments: for each segment in prepared_remarks and qa, produce `{"speaker": str, "role": str, "text": str, "word_count": len(text.split())}`
8. Compute metadata:
   - `total_word_count`: sum of all word_counts
   - `prepared_remarks_word_count`: sum of prepared_remarks word_counts
   - `qa_word_count`: sum of qa word_counts
   - `speaker_list`: aggregate by unique speaker name, include role and total word_count across all appearances. Sort by word_count descending.
   - `num_qa_exchanges`: `len(qa_exchanges)`
   - `num_speakers`: count of unique speaker names (excluding "Operator")
9. Return the full dict.

### Function 6: `_get_cache_path`

```python
def _get_cache_path(symbol: str, year: int, quarter: int) -> Path:
    """
    Build path for parsed transcript JSON cache.

    Format: cache/transcripts_parsed/{SYMBOL}_{Q}Q{YY}_v{VERSION}_transcript_parsed.json
    Example: cache/transcripts_parsed/AAPL_4Q24_v1_transcript_parsed.json

    The PARSER_VERSION is embedded in the filename so that when parsing logic
    changes (bump PARSER_VERSION), old caches are naturally bypassed without
    needing explicit invalidation.
    """
```

**Implementation:**
- Return `PARSED_CACHE_DIR / f"{symbol.upper()}_{quarter}Q{year % 100:02d}_v{PARSER_VERSION}_transcript_parsed.json"`
- Do NOT mkdir here; the caller (`get_earnings_transcript`) handles directory creation.

### Function 7: `_truncate`

```python
def _truncate(text: str, max_words: int | None) -> str:
    """
    Truncate text to max_words, appending continuation marker.

    Follows the agent-tool response protocol (PROTOCOL_agent_tool_responses.md):
    prevents any single text field from exceeding the agent's reasoning budget.

    Args:
        text: The text to truncate.
        max_words: Maximum number of words to keep. None = unlimited.

    Returns:
        Original text if within limit, otherwise truncated text with marker.
    """
    if max_words is None:
        return text
    words = text.split()
    if len(words) <= max_words:
        return text
    remaining = len(words) - max_words
    return " ".join(words[:max_words]) + f"\n\n...[truncated — {remaining:,} more words remaining]"
```

### Function 8: `_apply_filters`

```python
def _apply_filters(
    parsed: dict,
    section: str,
    filter_speaker: str | None,
    filter_role: str | None,
    format: str,
    max_words: int | None,
) -> dict:
    """
    Apply section/speaker/role/format filters to a parsed transcript,
    then apply max_words truncation to all text fields.

    Args:
        parsed: Full parsed transcript dict (from parse_transcript or cache).
        section: "prepared_remarks", "qa", or "all".
        filter_speaker: Substring match on speaker name (case-insensitive).
        filter_role: Exact match on role string.
        format: "full" or "summary".
        max_words: Max words per text field. None = unlimited.

    Returns:
        Filtered dict ready for MCP response (without "status" key -- caller adds that).
    """
```

**Implementation details:**
- Deep-copy `parsed` to avoid mutating the cached version.
- **Section filter:** If `section == "prepared_remarks"`, set `qa = []` and `qa_exchanges = []`. If `section == "qa"`, set `prepared_remarks = []`.
- **Speaker filter:** If `filter_speaker` is provided, filter `prepared_remarks` and `qa` to only segments where `filter_speaker.lower() in segment["speaker"].lower()`. Filter `qa_exchanges` to exchanges where analyst name matches OR any answer speaker matches. For exchanges, keep the full exchange if any participant matches.
- **Role filter:** If `filter_role` is provided, filter `prepared_remarks` and `qa` to only segments where `segment["role"] == filter_role`. Filter `qa_exchanges`: if `filter_role == "Analyst"`, keep exchanges where analyst exists; otherwise, keep exchanges where any answer has the matching role. For kept exchanges, filter answers to only those with matching role (but always keep the analyst question).
- **Filtering consistency note (intentional design):** When filtering by speaker/role, `qa_exchanges` are included if ANY participant in the exchange matches (analyst or any answerer). This is intentional -- an exchange is a self-contained unit and must be kept whole to be useful. However, metadata word counts (`prepared_remarks_word_count`, `qa_word_count`, `total_word_count`) should count only the matching segments from `prepared_remarks` and `qa` lists, NOT the exchange text. The `speaker_list` word counts also derive from the filtered segment lists only. This means metadata counts may be less than the total text returned in `qa_exchanges`, and that is expected.
- **Recompute metadata** after filtering: word counts, speaker_list, num_qa_exchanges, num_speakers should reflect only what remains after filtering (segment lists for word counts, exchange list for num_qa_exchanges).
- **Apply `max_words` truncation** (after filtering, before format check): When `format == "full"`, apply `_truncate()` to each segment's `text` field in `prepared_remarks` and `qa`, and to each Q&A exchange's `question` text and each answer's `text` field. This ensures truncation respects the filtered result, not the full transcript. Do NOT truncate in summary mode (no text fields are returned).
- **Bounded preview for unfiltered full mode:** When `format == "full"` and NO narrowing filters are active (section is "all", filter_speaker is None, filter_role is None), return a bounded preview instead of the full dump. This matches the protocol's "require specificity for full text" principle. Implementation:
  - Keep `prepared_remarks` and `qa` as normal segment-dict lists (`[{speaker, role, text, word_count}, ...]`) — do NOT change the response schema.
  - **Limit to first 3 segments per section** (prepared_remarks[:3], qa[:3]). This caps the total response to ~6 segments max.
  - Apply `_truncate(text, 500)` to each of those segments' `text` fields. Preview always caps at 500 regardless of user-provided `max_words`. Total max response ~5000 words (6 segments x 500 + 2 exchanges x ~1000).
  - Set `qa_exchanges` to the first 2 exchanges only (as a preview), with their text also truncated to 500.
  - Add `hint`: `"Showing preview (first 3 segments per section, 500 words each). Use section, filter_role, or filter_speaker to get specific full content."`.
  - Keep full metadata (untruncated counts) so the agent can see the real size.
  This prevents an unfiltered `format="full"` call from returning both `qa` segments and `qa_exchanges` (duplicated text) at full size.
- **Format:** If `format == "summary"`, remove `prepared_remarks`, `qa`, and `qa_exchanges` keys from the result. Keep only `symbol`, `year`, `quarter`, `date`, and `metadata`. Also add a `hint` key: `"Use format='full' with filters (section, filter_role, filter_speaker) to read specific content."`. If `format == "full"` (with filters), keep everything.
- Return the result dict (caller adds `"status": "success"`).

### Function 9: `get_earnings_transcript` (MCP Tool)

```python
def get_earnings_transcript(
    symbol: str,
    year: int,
    quarter: int,
    section: Literal["prepared_remarks", "qa", "all"] = "all",
    filter_speaker: str | None = None,
    filter_role: Literal["CEO", "CFO", "COO", "CTO", "Analyst", "IR", "Operator"] | None = None,
    format: Literal["full", "summary"] = "summary",
    max_words: int | None = 3000,
) -> dict:
    """Fetch, parse, and filter an earnings call transcript.

    Default format is "summary" (metadata only: speaker list, word counts,
    exchange count). Use format="full" with filters to read text content.
    When format="full", each text field is truncated to max_words (default 3000).
    """
```

**Implementation -- follow the `news_events.py` pattern exactly:**

```python
_saved = sys.stdout
sys.stdout = sys.stderr
try:
    # 1. Validate inputs
    symbol = symbol.strip().upper()
    if max_words is not None and max_words < 1:
        return {"status": "error", "error": "max_words must be >= 1 or None"}
    if quarter not in (1, 2, 3, 4):
        return {"status": "error", "error": "quarter must be 1-4"}
    _year_max = datetime.now().year + 2
    if year < 2000 or year > _year_max:
        return {"status": "error", "error": f"year must be between 2000 and {_year_max}"}

    # 2. Check parsed cache first
    cache_path = _get_cache_path(symbol, year, quarter)
    if cache_path.is_file():
        with open(cache_path) as f:
            parsed = json.load(f)
    else:
        # 3. Fetch raw transcript via FMPClient
        #    FMPClient.fetch() raises FMPEmptyResponseError on empty data
        #    (not df.empty -- the exception fires before a DataFrame is built).
        fmp = FMPClient()
        try:
            df = fmp.fetch("earnings_transcript", symbol=symbol, year=year, quarter=quarter)
        except FMPEmptyResponseError:
            return {
                "status": "error",
                "error": f"No transcript found for {symbol} Q{quarter} {year}",
            }

        # Safety net: df.empty check (unlikely to trigger since FMPClient
        # raises FMPEmptyResponseError first, but defensive)
        if df.empty:
            return {
                "status": "error",
                "error": f"No transcript found for {symbol} Q{quarter} {year}",
            }

        content = str(df["content"].iloc[0])

        if len(content) < 500:
            return {
                "status": "error",
                "error": f"Transcript too short ({len(content)} chars) for "
                         f"{symbol} Q{quarter} {year}. May be incomplete.",
            }

        # 4. Parse
        parsed = parse_transcript(content)
        parsed["symbol"] = symbol
        parsed["year"] = year
        parsed["quarter"] = quarter
        # date may be a Timestamp -- coerce to string safely
        parsed["date"] = str(df["date"].iloc[0])[:10] if "date" in df.columns else ""

        # 5. Write to cache
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(parsed, f)

    # 6. Apply filters, truncation, and format
    result = _apply_filters(parsed, section, filter_speaker, filter_role, format, max_words)
    result["status"] = "success"
    return result

except Exception as e:
    return {"status": "error", "error": str(e)}
finally:
    sys.stdout = _saved
```

---

## File 2: `mcp_tools/__init__.py` (MODIFY)

Three changes:

**Change 1 -- Add docstring entry** in the "FMP data tools" section of the module docstring, after the `get_technical_analysis` line:
```
- get_earnings_transcript: Parse and filter earnings call transcripts
```

**Change 2 -- Add import** after the `from mcp_tools.technical import get_technical_analysis` line:
```python
from mcp_tools.transcripts import get_earnings_transcript
```

**Change 3 -- Add to `__all__`** list, after `"get_technical_analysis"`:
```python
"get_earnings_transcript",
```

---

## File 3: `fmp_mcp_server.py` (MODIFY)

Three changes:

**Change 1 -- Add import** after the existing `from mcp_tools.technical import ...` line:
```python
from mcp_tools.transcripts import get_earnings_transcript as _get_earnings_transcript
```

**Change 2 -- Add to `mcp` instructions string** in the FastMCP constructor, after the `get_events_calendar` line:
```
- get_earnings_transcript: Parse and navigate earnings call transcripts (prepared remarks, Q&A, per-speaker)
```

**Change 3 -- Add `@mcp.tool()` wrapper** before `if __name__ == "__main__":`:

```python
@mcp.tool()
def get_earnings_transcript(
    symbol: str,
    year: int,
    quarter: int,
    section: Literal["prepared_remarks", "qa", "all"] = "all",
    filter_speaker: Optional[str] = None,
    filter_role: Optional[Literal["CEO", "CFO", "COO", "CTO", "Analyst", "IR", "Operator"]] = None,
    format: Literal["full", "summary"] = "summary",
    max_words: Optional[int] = 3000,
) -> dict:
    """
    Parse and navigate an earnings call transcript.

    Splits the raw transcript into structured sections: prepared remarks
    and Q&A with per-speaker segments and grouped Q&A exchanges.

    IMPORTANT — default mode is summary (metadata only). This protects
    your context window. Full text is returned only when you explicitly
    request format="full".

    Recommended workflow:
    1. Call with default format="summary" to see the speaker list,
       word counts, and exchange count (costs ~1 KB of context)
    2. Identify the section or speaker you need
    3. Call again with format="full" and specific filters
       (section, filter_role, filter_speaker) to read only that content
    4. Each text field is capped at max_words (default 3000). Set
       max_words=None to remove the cap (use with caution).
    Note: If format="full" is used WITHOUT any filters (no section,
    filter_role, or filter_speaker), a bounded preview is returned
    instead (first 3 segments per section, 500 words each, 2 exchanges).
    Add at least one filter to get full content with max_words control.

    Args:
        symbol: Stock symbol (e.g., "AAPL", "MSFT", "NVDA").
        year: Fiscal year of the earnings call (e.g., 2024).
        quarter: Quarter 1-4.
        section: Which section to return:
            - "all": Both prepared remarks and Q&A (default)
            - "prepared_remarks": Management presentations only
            - "qa": Q&A session only
        filter_speaker: Filter to segments by this speaker (substring match,
            e.g., "Cook" matches "Tim Cook"). Case-insensitive.
        filter_role: Filter to segments by role:
            - "CEO", "CFO", "COO", "CTO": C-suite executives
            - "Analyst": Sell-side analysts asking questions
            - "IR": Investor Relations host
            - "Operator": Call operator
        format: Output format:
            - "summary": Metadata only — speaker list, word counts, exchange
              count. No text content. This is the DEFAULT. Use this first to
              scout the transcript before reading full text.
            - "full": Text content for all matching segments, truncated to
              max_words per field.
        max_words: Maximum words per text field when format="full".
            Default 3000. Set to None for unlimited (use with caution —
            CEO prepared remarks can exceed 5K words). Ignored when
            format="summary".

    Returns:
        dict with status and metadata. When format="full", also includes
        prepared_remarks, qa, and qa_exchanges with text content.

    Examples:
        # Step 1: Scout the transcript structure (default — summary mode)
        get_earnings_transcript(symbol="AAPL", year=2024, quarter=4)

        # Step 2: Drill into the CEO's prepared remarks
        get_earnings_transcript(symbol="AAPL", year=2024, quarter=4,
                                section="prepared_remarks", filter_role="CEO",
                                format="full")

        # Read the full Q&A session (truncated to 3000 words per field)
        get_earnings_transcript(symbol="AAPL", year=2024, quarter=4,
                                section="qa", format="full")

        # Find what the CFO said everywhere
        get_earnings_transcript(symbol="NVDA", year=2024, quarter=3,
                                filter_role="CFO", format="full")

        # Find a specific analyst's exchange
        get_earnings_transcript(symbol="MSFT", year=2024, quarter=4,
                                section="qa", filter_speaker="Nadella",
                                format="full")

        # Get full text without truncation (caution: may be very large)
        get_earnings_transcript(symbol="AAPL", year=2024, quarter=4,
                                section="prepared_remarks", filter_role="CEO",
                                format="full", max_words=None)
    """
    return _get_earnings_transcript(
        symbol=symbol,
        year=year,
        quarter=quarter,
        section=section,
        filter_speaker=filter_speaker,
        filter_role=filter_role,
        format=format,
        max_words=max_words,
    )
```

---

## Key Gotchas and Implementation Notes

1. **stdout redirect is mandatory.** Follow the `news_events.py` pattern exactly: `_saved = sys.stdout; sys.stdout = sys.stderr` at the top of `get_earnings_transcript`, restore in `finally`. Any stray `print()` in parsing helpers will corrupt MCP JSON-RPC. Only the top-level tool function needs the redirect -- internal helpers are called within its scope.

2. **Use `FMPClient.fetch()` not `fetch_raw()`.** `fetch()` returns a DataFrame AND benefits from the existing Parquet caching in `cache/transcripts/`. The raw transcript is already cached as immutable data (`HASH_ONLY` refresh). Using `fetch_raw()` would bypass caching and hit the API every time.

3. **The date column from FMP may be a Timestamp, not a string.** Use `str(df["date"].iloc[0])[:10]` to safely extract the date string for the response.

4. **JSON serialization of the cache.** Use `json.dump` with no special options. All values in the parsed dict are basic types (str, int, list, dict). No numpy/pandas types will be present since we extract content as a plain string and compute word counts as plain ints.

5. **Role classification call order matters.** The sequence MUST be: `_normalize_content` -> `parse_speakers` -> `find_qa_boundary` -> `classify_roles`. The boundary is needed so `classify_roles` can apply the positional fallback (unknown speakers after boundary -> "Analyst"). Do NOT try to classify roles before finding the boundary.

6. **The CEO regex must exclude "Vice President" and "President of Investor Relations".** Use negative lookbehind `(?<!\bVice\s)` and negative lookahead `(?!\s+of\s+(?:Investor|IR|Finance))` to prevent misclassifying VPs and IR directors as CEO. Test against AAPL transcript where "Vice President of Financial Planning and Analysis" appears in the IR intro.

7. **Analyst name in Operator text vs. actual speaker name may differ.** For example, AMZN Operator says "Mark Stephen Mahaney" but the speaker line says "Mark Stephen Mahaney" (consistent in this case). But it could be "Jim Friedland" in Operator vs "James Friedland" as speaker (GOOGL). Use `_names_match()` with last-name comparison + first-name prefix matching (3+ chars).

8. **Empty qa_exchanges list is valid.** Some transcripts might not have a clear Q&A section (though all 15 cached ones do). Return an empty list rather than erroring.

9. **`filter_speaker` should be a substring match, not exact.** `"Cook"` should match `"Tim Cook"`. Use `filter_speaker.lower() in segment["speaker"].lower()`.

10. **Recompute metadata after filtering.** When filters are applied, the word counts and speaker list in metadata must reflect only the filtered segments, not the full transcript. This prevents confusing the agent with stale counts.

11. **Deep-copy before filtering.** The parsed dict may come from cache and be reused across calls with different filters. Always deep-copy before mutating with filters. Use `import copy; copy.deepcopy(parsed)` or manually reconstruct.

12. **Word count computation.** Use `len(text.split())` for word count. This is simple and sufficient -- the agent uses word counts for size estimation, not exact NLP analysis.

13. **Default format is "summary", not "full".** Per the agent-tool response protocol (`PROTOCOL_agent_tool_responses.md`), tools that return variable-length text must default to summary mode. This prevents an unfiltered call from dumping 50K+ words into the agent's context. The agent must explicitly opt into `format="full"`.

14. **`max_words` truncation is applied after filtering, not before.** The `_apply_filters()` function applies `_truncate()` to text fields after section/speaker/role filters have narrowed the result. This ensures that if you filter to a single speaker, you get up to `max_words` of that speaker's text -- not a truncated slice of the full transcript that might not even contain your target speaker.

15. **`max_words` applies per text field, not per response.** Each speaker segment's `text` field and each Q&A exchange's `question`/`answer` text is independently truncated to `max_words`. A response with 5 segments could contain up to 5x `max_words` words total. This is by design -- individual segments are the natural unit of reasoning.

16. **`_truncate()` is a pure function with no side effects.** It takes a string and returns a string. It does not modify the input. This is important because `_apply_filters()` operates on a deep-copy, and `_truncate()` is called on individual fields within that copy.

17. **Summary mode returns a `hint` key.** When `format="summary"`, the response includes a `hint` string that coaches the agent to use `format="full"` with filters. This follows the protocol's principle that docstrings and responses should coach the agent on the recommended workflow.

18. **`max_words=None` disables truncation entirely.** This is intentional for cases where the agent has already narrowed to a small section and needs the complete text (e.g., a single analyst exchange that's 500 words). However, the default is 3000, so an agent that forgets to specify gets protected automatically.

19. **`max_words` must be >= 1 if provided.** Validation at the top of `get_earnings_transcript()` rejects `max_words=0` and negative values with an error response. `None` means unlimited.

20. **FMPClient.fetch() raises `FMPEmptyResponseError`, not returning an empty DataFrame.** The exception fires inside the client before a DataFrame is built. Catch `FMPEmptyResponseError` explicitly (imported from `fmp.exceptions`) and return a clear error. Keep a secondary `df.empty` check as a safety net.

21. **Q&A boundary strategies 1-2 must only match literal "Operator" segments.** No moderator heuristic — the heuristic caused regressions when IR hosts used similar language. Strategy 3 handles no-Operator transcripts via a "new speaker after 3+ unique speakers + explicit transition cue in immediately preceding segment" fallback. Exchange building also uses literal "Operator" check for separators — in no-Operator transcripts, non-Operator moderator turns are classified as "Other" and don't create exchange separators, which is acceptable since the content is still accessible in the segment lists.

22. **Q&A boundary Strategy 2 requires minimum segment index >= 3 and >= 2 prior management speakers.** Several cached transcripts (DSP, IT, RAMP) have operator instructions with "question" at segment index 0. Without guards, Strategy 2 would fire immediately and place the Q&A boundary at the start of the transcript.

23. **Post-boundary Analyst fallback must respect `known_management_speakers`.** If a speaker appeared in prepared remarks, they are management regardless of whether their role was identified. Defaulting them to "Analyst" would create false question turns and break exchange structure.

24. **Scan ALL segments for role mappings.** Some transcripts (DSP) have CEO/COO/CFO mappings in Operator text, not in management speaker intro text. The role extraction regex must process all segments including Operator.

25. **Unfiltered `format="full"` returns a bounded preview.** When no filters are active (section="all", no filter_speaker, no filter_role), `format="full"` returns the first 3 segments per section (each truncated to 500 words) and 2 sample exchanges, with a hint to narrow. Total max ~5000 words. This prevents duplicated text between `qa` segments and `qa_exchanges` from consuming excessive context.

26. **`PARSER_VERSION` controls cache invalidation.** When parsing logic changes, bump `PARSER_VERSION` and old caches are naturally bypassed via the versioned filename. No need for explicit cache cleanup.

27. **Content normalization runs before speaker parsing.** `_normalize_content()` handles markdown bold (`**Name**:`), brackets (`[Name]:`), unicode dashes/quotes, and HTML entities. This must run before `SPEAKER_PATTERN` is applied.

---

## Testing Plan

### Test 1: Smoke test with summary mode (default)
```bash
cd /Users/henrychien/Documents/Jupyter/risk_module
python3 -c "
from mcp_tools.transcripts import get_earnings_transcript
import json
# format='summary' is now the default -- no need to specify it
result = get_earnings_transcript('AAPL', 2024, 4)
print(json.dumps(result, indent=2))
# Verify: no text content in response (no prepared_remarks, qa, qa_exchanges keys)
assert 'prepared_remarks' not in result, 'summary should not include prepared_remarks'
assert 'qa' not in result, 'summary should not include qa'
assert 'qa_exchanges' not in result, 'summary should not include qa_exchanges'
assert 'hint' in result, 'summary should include a hint for the agent'
print('PASS: summary mode is default, no text content returned')
"
```
**Verify:** `status == "success"`, metadata has speaker_list with Tim Cook (CEO), Luca Maestri (CFO), Suhasini Chandramouli (IR), Operator (Operator), and multiple analysts. `num_speakers` should be ~15+ (excluding Operator). Word counts should sum correctly. Response should NOT contain `prepared_remarks`, `qa`, or `qa_exchanges` keys. Should contain a `hint` key.

### Test 2: Speaker segmentation accuracy
```bash
python3 -c "
from mcp_tools.transcripts import parse_transcript
import pandas as pd
df = pd.read_parquet('cache/transcripts/AAPL_c805dcae.parquet')
result = parse_transcript(df['content'].iloc[0])
pr_words = sum(s['word_count'] for s in result['prepared_remarks'])
qa_words = sum(s['word_count'] for s in result['qa'])
total = pr_words + qa_words
print(f'PR words: {pr_words}, QA words: {qa_words}, total: {total}')
print(f'metadata total: {result[\"metadata\"][\"total_word_count\"]}')
assert total == result['metadata']['total_word_count'], 'Word counts mismatch!'
assert pr_words == result['metadata']['prepared_remarks_word_count'], 'PR word count mismatch!'
assert qa_words == result['metadata']['qa_word_count'], 'QA word count mismatch!'
print('PASS: word counts match')
print(f'Segments: {len(result[\"prepared_remarks\"])} prepared, {len(result[\"qa\"])} Q&A')
"
```

### Test 3: Q&A boundary correctness
```bash
python3 -c "
from mcp_tools.transcripts import parse_transcript
import pandas as pd
df = pd.read_parquet('cache/transcripts/AAPL_c805dcae.parquet')
result = parse_transcript(df['content'].iloc[0])
pr_roles = set(s['role'] for s in result['prepared_remarks'])
qa_roles = set(s['role'] for s in result['qa'])
print(f'Prepared remarks roles: {pr_roles}')
print(f'Q&A roles: {qa_roles}')
assert 'Analyst' not in pr_roles, f'Analyst found in prepared_remarks!'
assert 'Analyst' in qa_roles, f'No Analyst found in Q&A!'
print('PASS: Q&A boundary correct')
"
```

### Test 4: Q&A exchanges structure
```bash
python3 -c "
from mcp_tools.transcripts import get_earnings_transcript
# Must specify format='full' to get text content (default is now summary)
result = get_earnings_transcript('AAPL', 2024, 4, section='qa', format='full')
assert result['status'] == 'success'
print(f'Total Q&A exchanges: {len(result[\"qa_exchanges\"])}')
for i, ex in enumerate(result['qa_exchanges'][:3]):
    print(f'Exchange {i+1}: {ex[\"analyst\"]} ({ex.get(\"firm\", \"?\")})')
    print(f'  Q: {ex[\"question\"][:100]}...')
    for a in ex['answers']:
        print(f'  A ({a[\"speaker\"]}, {a[\"role\"]}): {a[\"text\"][:80]}...')
    print()
assert all(ex.get('analyst') for ex in result['qa_exchanges']), 'Exchange missing analyst!'
assert all(len(ex.get('answers', [])) > 0 for ex in result['qa_exchanges'][:5]), 'Exchange missing answers!'
print('PASS: Q&A exchanges well-formed')
"
```

### Test 5: Filtering (requires format="full" for text content)
```bash
python3 -c "
from mcp_tools.transcripts import get_earnings_transcript

# Filter by role (need format='full' to get segment data)
r = get_earnings_transcript('AAPL', 2024, 4, filter_role='CFO', format='full')
assert r['status'] == 'success'
all_speakers = set(s['speaker'] for s in r.get('prepared_remarks', []) + r.get('qa', []))
print(f'CFO filter speakers: {all_speakers}')
# Should only contain CFO speakers (Luca Maestri or Kevan Parekh)
for s in all_speakers:
    assert 'Maestri' in s or 'Parekh' in s, f'Unexpected non-CFO speaker: {s}'

# Filter by speaker name
r2 = get_earnings_transcript('AAPL', 2024, 4, filter_speaker='Cook', format='full')
assert r2['status'] == 'success'
all_speakers2 = set(s['speaker'] for s in r2.get('prepared_remarks', []) + r2.get('qa', []))
print(f'Cook filter speakers: {all_speakers2}')
for s in all_speakers2:
    assert 'Cook' in s, f'Unexpected non-Cook speaker: {s}'

# Section filter
r3 = get_earnings_transcript('AAPL', 2024, 4, section='prepared_remarks', format='full')
assert r3['status'] == 'success'
assert len(r3.get('qa', [])) == 0, 'Q&A should be empty for prepared_remarks section'
assert len(r3.get('qa_exchanges', [])) == 0, 'qa_exchanges should be empty'
assert len(r3.get('prepared_remarks', [])) > 0, 'prepared_remarks should not be empty'

print('PASS: all filters work')
"
```

### Test 6: Cache hit
```bash
python3 -c "
from mcp_tools.transcripts import get_earnings_transcript, _get_cache_path
import time

# First call (parses and caches) -- summary is default
t0 = time.time()
r1 = get_earnings_transcript('AAPL', 2024, 4)
t1 = time.time()

# Second call (should hit JSON cache)
r2 = get_earnings_transcript('AAPL', 2024, 4)
t2 = time.time()

print(f'First call: {t1-t0:.3f}s')
print(f'Second call: {t2-t1:.3f}s')
print(f'Cache file exists: {_get_cache_path(\"AAPL\", 2024, 4).is_file()}')
assert r1['metadata'] == r2['metadata'], 'Cache result mismatch!'
print('PASS: cache works')
"
```

### Test 7: Error cases
```bash
python3 -c "
from mcp_tools.transcripts import get_earnings_transcript

# Invalid quarter
r = get_earnings_transcript('AAPL', 2024, 5)
assert r['status'] == 'error', 'Should error on quarter=5'
print(f'Quarter 5 error: {r[\"error\"]}')

# Invalid year
r = get_earnings_transcript('AAPL', 1999, 1)
assert r['status'] == 'error', 'Should error on year=1999'
print(f'Year 1999 error: {r[\"error\"]}')

# Invalid max_words (0 and negative)
r = get_earnings_transcript('AAPL', 2024, 4, max_words=0)
assert r['status'] == 'error', 'Should error on max_words=0'
print(f'max_words=0 error: {r[\"error\"]}')

r = get_earnings_transcript('AAPL', 2024, 4, max_words=-5)
assert r['status'] == 'error', 'Should error on max_words=-5'
print(f'max_words=-5 error: {r[\"error\"]}')

# Nonexistent symbol (should fail at FMP level with FMPEmptyResponseError)
r = get_earnings_transcript('ZZZZZZ', 2024, 1)
assert r['status'] == 'error', 'Should error on invalid symbol'
print(f'Bad symbol error: {r[\"error\"]}')

print('PASS: error cases handled')
"
```

### Test 8: Cross-ticker validation
```bash
python3 -c "
from mcp_tools.transcripts import get_earnings_transcript
import json

# These match the cached transcripts (all are Q3 2025 except AAPL which is Q4 2024)
# Default is summary mode -- no need to specify format
tests = [
    ('GOOGL', 2025, 3),
    ('AMZN', 2025, 3),
    ('TTD', 2025, 3),
    ('ROKU', 2025, 3),
    ('CRTO', 2025, 3),
    ('PUBM', 2025, 3),  # No literal 'Operator' — tests Strategy 3 fallback boundary detection
]
for sym, yr, q in tests:
    r = get_earnings_transcript(sym, yr, q)
    if r['status'] == 'success':
        m = r['metadata']
        print(f'{sym} Q{q} {yr}: {m[\"num_speakers\"]} speakers, '
              f'{m[\"num_qa_exchanges\"]} exchanges, '
              f'{m[\"total_word_count\"]} words')
    else:
        print(f'{sym} Q{q} {yr}: ERROR - {r[\"error\"]}')
"
```

### Test 9: Truncation behavior
```bash
python3 -c "
from mcp_tools.transcripts import get_earnings_transcript

# Full text with default max_words=3000
r = get_earnings_transcript('AAPL', 2024, 4, section='prepared_remarks',
                            filter_role='CEO', format='full')
assert r['status'] == 'success'
for seg in r.get('prepared_remarks', []):
    words = seg['text'].split()
    print(f'{seg[\"speaker\"]}: {len(words)} words')
    if len(words) >= 3000:
        assert 'truncated' in seg['text'], 'Long text should have truncation marker'
        print('  -> truncation marker present')

# Full text with max_words=None (unlimited)
r2 = get_earnings_transcript('AAPL', 2024, 4, section='prepared_remarks',
                             filter_role='CEO', format='full', max_words=None)
assert r2['status'] == 'success'
for seg in r2.get('prepared_remarks', []):
    assert 'truncated' not in seg['text'], 'max_words=None should not truncate'
    print(f'{seg[\"speaker\"]}: {len(seg[\"text\"].split())} words (no truncation)')

# Full text with small max_words to verify truncation works
r3 = get_earnings_transcript('AAPL', 2024, 4, section='prepared_remarks',
                             filter_role='CEO', format='full', max_words=50)
assert r3['status'] == 'success'
for seg in r3.get('prepared_remarks', []):
    # Text before the marker should be ~50 words
    text_before_marker = seg['text'].split('...[truncated')[0]
    word_count = len(text_before_marker.split())
    print(f'{seg[\"speaker\"]}: {word_count} words before truncation marker')
    assert word_count <= 51, f'Expected ~50 words, got {word_count}'

print('PASS: truncation works correctly')
"
```

### Test 10: MCP integration (manual)
After implementation, restart the fmp-mcp server and test via Claude:
```
# Step 1: Scout (default -- returns summary only)
get_earnings_transcript(symbol="AAPL", year=2024, quarter=4)

# Step 2: Drill in with full text
get_earnings_transcript(symbol="AAPL", year=2024, quarter=4, section="qa", filter_role="CFO", format="full")
```

---

## Verification Commands

```bash
# Summary mode (default -- no format arg needed)
cd /Users/henrychien/Documents/Jupyter/risk_module
python3 -c "from mcp_tools.transcripts import get_earnings_transcript; import json; print(json.dumps(get_earnings_transcript('AAPL', 2024, 4), indent=2))"

# Full text with truncation (must explicitly request format='full')
python3 -c "from mcp_tools.transcripts import get_earnings_transcript; import json; print(json.dumps(get_earnings_transcript('AAPL', 2024, 4, section='prepared_remarks', filter_role='CEO', format='full'), indent=2))"
```

---

## Review History

### Round 1 — Codex Review (2026-02-07)
- 5 HIGH, 5 MED, 2 LOW findings
- All addressed in plan update

### Round 2 — Codex Review (2026-02-07)
- 1 HIGH, 4 MED remaining findings
- All addressed:
  1. HIGH: Transcripts without literal "Operator" break boundary detection — added moderator detection (heuristic: speaker with 2+ call-management phrases)
  2. MED: Preview output shape ambiguous — clarified schema stays as segment-dict lists, no schema change
  3. MED: max_words vs preview overlap — preview always caps at 500, ignores user max_words; user must add filter for larger view
  4. MED: Role scanning false mappings from Q&A — constrained scanning to pre-boundary segments only
  5. MED: Missing PUBM in test list — added with note about no-Operator edge case

### Round 3 — Codex Review (2026-02-07)
- 2 HIGH, 2 MED remaining findings
- All addressed:
  1. HIGH: Moderator heuristic regression — dropped text-based moderator detection entirely. Strategies 1-2 use literal "Operator" only. Strategy 3 handles no-Operator transcripts via "new speaker after 3+ unique speakers + nearby Q&A cue" fallback.
  2. HIGH: Unbounded preview — limited to first 3 segments per section (max ~6 segments), each truncated to 500 words, plus 2 exchanges. Total max ~5000 words.
  3. MED: Moderator concept not propagated — removed moderator concept. Exchange building uses literal "Operator" for separators. No-Operator transcripts get segment-level content without perfect exchange structuring.
  4. MED: Preview behavior ambiguous in docs — added explicit note in MCP docstring about preview mode when no filters active.

### Round 4 — Codex Review (2026-02-07)
- 1 HIGH, 1 LOW
- All addressed:
  1. HIGH: Strategy 3 threshold of 3 still fires too early on PUBM (Steven Pantelick at index 3 is 4th unique but still management). Added Q&A transition cue check in preceding 1-2 segments as second gate. Now requires BOTH 3+ prior speakers AND nearby Q&A cue language.
  2. LOW: Fixed stale wording in Gotcha #21 and review history to match current Strategy 3 algorithm.
