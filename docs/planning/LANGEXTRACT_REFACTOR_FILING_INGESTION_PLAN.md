# Plan: Langextract Refactor + Filing Ingestion Wiring

> **Codex review**: R1 — 6 findings (3H, 3M), addressed v2. R2 — 2 findings (1H, 1M), addressed v3. R3 — 1 finding (1H), addressed v4.

## Context

The research workspace has a document viewer that renders extraction highlights on filing text. The frontend code (`useExtractions`, `FilingSection`, `HighlightLayer`) is wired up and the backend extraction endpoint exists — but it has never worked in practice because:

1. The `GET /extractions` endpoint calls langextract via a **direct Python import** of `server.py`, which triggers module-level side effects (`GOOGLE_API_KEY` check, `FastMCP()` instantiation) that crash in the gateway process.
2. Filing markdown files were never being ingested to disk — no filing data existed for the extraction endpoint to operate on.
3. When the agent calls `get_filing_sections(output="file")`, the resulting `file_path` is never surfaced as `sourcePath` in tool call metadata, so the frontend "Open in reader" button never appears.

### What we verified via curl testing (2026-04-14)

| Step | Result |
|------|--------|
| `get_filing_sections(output="file")` produces compatible markdown | ✓ `## SECTION:` headers, correct title format for `_parse_filing_identity` |
| `POST /documents/ingest` copies to persistent storage | ✓ → `data/filings/{filing_id}.md` |
| `GET /documents` returns sections with char offsets | ✓ 6 sections, valid start/end offsets |
| `GET /extractions` returns langextract highlights | ✓ 9 grounded extractions (after env + path fix) |
| Langextract MCP tool directly | ✓ 12 grounded extractions from Risk Factors section |
| `get_filing_sections` as alternative | Section text only — no sub-passage classification. Complementary, not a replacement. |

### Quick fixes applied during testing (to be superseded by this plan)
- Added `GOOGLE_API_KEY` to `AI-excel-addin/.env` for the gateway process
- Added `Path.cwd() / "data" / "filings"` to `text_utils.py:_allowed_output_roots()`

All changes in this plan are in the **AI-excel-addin** repo (`/Users/henrychien/Documents/Jupyter/AI-excel-addin/`).

---

## Part 1: Refactor langextract extraction logic

### Problem

`api/research/document_service.py:55` does:
```python
from mcp_servers.langextract_mcp.server import extract_filing_file
```

This triggers `server.py`'s module-level code:
- Line 49: `GOOGLE_API_KEY = _require_google_api_key()` — crashes if env var missing
- Line 52: `mcp = FastMCP(...)` — unnecessary MCP server instantiation

The gateway process and the langextract MCP server are separate processes with different env vars. The direct import is architecturally wrong.

### Solution

Move the core extraction functions out of `server.py` into a new `mcp_servers/langextract_mcp/extraction.py` module that:
- Takes `api_key` as a function parameter (not module-level global)
- Has no MCP server boilerplate (`FastMCP`, `@mcp.tool()`)
- Has no module-level side effects
- Preserves the `{status: "ok"|"error", ...}` return contract (no raw exceptions leak out)

**New file: `mcp_servers/langextract_mcp/extraction.py`**

Move these functions from `server.py`:
- `_coerce_mapping()` (line 63)
- `_attr_or_key()` (line 68)
- `_extract_interval()` (line 75)
- `_iter_documents()` (line 92)
- `_extract_text()` (line 102) — change to accept `api_key` parameter instead of using global `GOOGLE_API_KEY`
- `_normalize_extractions()` (line 122)
- `_extract_section()` (line 162)
- Constants: `DEFAULT_EXTRACTION_PASSES`, `DEFAULT_MAX_WORKERS`, `DEFAULT_MAX_CHAR_BUFFER`, `DEFAULT_MODEL_ID`, `SECTION_PARALLELISM`

Add a public entry point:
```python
def extract_filing(
    file_path: str,
    schema_name: str,
    sections_filter: list[str] | None = None,
    api_key: str | None = None,
) -> dict:
```
This is the body of the current `extract_filing_file` MCP tool (server.py lines 179-260), but:
- Takes `api_key` as a param with fallback to `os.getenv("GOOGLE_API_KEY")`
- **Wraps the entire body in try/except and returns `{status: "error", error: str(exc)}` on failure** — preserving the same error contract as the current MCP tool (server.py line 259-260). This ensures `document_service.get_extractions()` continues to see `{status: "error"}` dicts rather than raw exceptions, and the REST endpoint's `ValueError` handling (routes.py:378) keeps working.

**Dependency isolation**: `extraction.py` must NOT import `langextract` or `schemas` at module level. Both `langextract.extraction.extract` (the Gemini call) and `schemas.get_schema` (which imports `langextract.data` at module level in `schemas.py`) must be **lazy-imported inside the `extract_filing()` function body**:

```python
def extract_filing(file_path, schema_name, sections_filter=None, api_key=None):
    try:
        from langextract.extraction import extract as lx_extract
        from mcp_servers.langextract_mcp.schemas import get_schema
        ...
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
```

This means `extraction.py` has **zero module-level imports of `langextract`**. The `langextract` package is only needed when `extract_filing()` is actually called, not when the module is imported.

**Declare the dependency**: Add `langextract` to `api/requirements.in` so clean installs include it. Without this, `/extractions` would fail at request time with `ModuleNotFoundError` on a fresh environment. Run `make deps-lock` after adding it to regenerate `api/requirements.txt`.

Similarly, `document_service.py` keeps its lazy import inside `_extract_filing_file()`:
```python
def _extract_filing_file(*, file_path, schema_name, sections_filter):
    from mcp_servers.langextract_mcp.extraction import extract_filing
    return extract_filing(file_path=file_path, schema_name=schema_name, sections_filter=sections_filter)
```

The gateway `.env` already has `GOOGLE_API_KEY` (added during testing).

**Modify `mcp_servers/langextract_mcp/server.py`:**
- Import from `extraction.py` instead of defining the functions inline
- Remove the moved functions (keep `_require_google_api_key`, `GOOGLE_API_KEY`, `mcp` setup, `list_extraction_schemas`)
- `extract_filing_file` MCP tool becomes a thin wrapper: `return extract_filing(file_path, schema_name, sections_filter, api_key=GOOGLE_API_KEY)`

**Modify `api/research/document_service.py`:**
- Change line 55 from `from mcp_servers.langextract_mcp.server import extract_filing_file` to `from mcp_servers.langextract_mcp.extraction import extract_filing`
- Update `_extract_filing_file()` to call `extract_filing(file_path=file_path, schema_name=schema_name, sections_filter=sections_filter)` — no `api_key` param needed since `extract_filing` falls back to `os.getenv("GOOGLE_API_KEY")`

### Files changed

| File | Action |
|------|--------|
| `mcp_servers/langextract_mcp/extraction.py` | **New** — extraction logic extracted from server.py, `{status: error}` contract preserved |
| `mcp_servers/langextract_mcp/server.py` | Slim down — import from extraction.py, MCP tool becomes thin wrapper |
| `api/research/document_service.py` | Change lazy import target from server.py to extraction.py |
| `api/requirements.in` | Add `langextract` dependency |

---

## Part 2: Wire filing ingestion into agent tool call metadata

### Problem

When the research agent calls `get_filing_sections(output="file")`, the result includes `{file_path: "/path/to/MSFT_2Q25_sections.md"}`. But this `file_path` never gets attached to message metadata as `source_path`. The frontend looks for `metadata.tool_calls[].sourcePath` on messages to show the "Open in reader" button — so the button never appears.

### How tool results are stored today

`api/research/runtime.py:persist_research_tool_result()` (lines 61-96) saves each tool call as a `content_type="tool_call"` message with metadata:
```python
metadata = {
    "tool_name": str(...),
    "tool_input": dict(...),
    "tool_call_id": str(...),
    "duration_ms": int(...),
    "server": ...,
    "is_error": ...,
}
```

No `tool_calls` array. No `source_path` extraction.

### What the frontend expects

`useResearchContent.ts:normalizeMetadata()` (risk_module frontend) looks for `metadata.tool_calls` (an array) on messages. `normalizeToolCall()` (line 84) maps:
- `tool_name` → `toolName`
- `source_path` → `sourcePath`  
- `source_type` → `sourceType`

`ConversationFeed.tsx` iterates ALL messages including `content_type="tool_call"` ones (line 92 renders them as "Used {tool_name}"). Line 106 checks `message.metadata?.toolCalls?.length` — if a `toolCall` has `sourcePath`, the "Open in reader" button renders below the "Used ..." label. So adding `tool_calls` to the tool_call message metadata works — the button will appear on the tool call row in the conversation feed.

### Solution

In `persist_research_tool_result()`, after building the metadata dict, check if this is a filing-producing tool and extract reader metadata.

**Scoping to filing tools only** (Codex R1 finding #2): Multiple tools return `file_path` in their results (`file_read`, `file_write`, `file_edit` in `api/local_tools.py`). A generic `file_path` check would surface bogus "Open in reader" links. Scope to an allowlist of known filing-producing tool names:

```python
_FILING_TOOL_NAMES = frozenset({
    "get_filing_sections",
})
```

Only `get_filing_sections` is included. `extract_filing_file` (langextract) is excluded because its result shape differs — it returns `sections_processed` instead of `sections_found`/`section_count`, and its output is extraction data, not a document file to open in the reader. If langextract results should be openable in the future, add it with a separate branch that checks `sections_processed`.

**Headerless file guard** (Codex R1 finding #5): Some edgar output files (e.g., `AAPL_4Q25_Item-1A.md`) have a valid `file_path` but zero content — no `## SECTION:` headers. `parse_filing_sections()` will raise `ValueError` when the user clicks "Open in reader". Guard by checking `sections_found` in the tool result before promoting to `tool_calls`. The `get_filing_sections` result always includes `sections_found` (a list of section keys) and `metadata.section_count`:

```python
tool_name = metadata["tool_name"]
tool_result = getattr(ctx, "result", None) or {}
if not metadata["is_error"] and tool_name in _FILING_TOOL_NAMES and isinstance(tool_result, dict):
    file_path = tool_result.get("file_path")
    sections_found = tool_result.get("sections_found") or []
    if file_path and isinstance(file_path, str) and len(sections_found) > 0:
        metadata["tool_calls"] = [{
            "tool_name": tool_name,
            "source_type": "filing",
            "source_path": file_path,
        }]
```

**Error state propagation** (Codex R1 finding #6): The `is_error` check at the top of the conditional already excludes hard errors. For soft errors (`{status: "error"}` in the result), the `sections_found`/`section_count` check handles it — error results won't have sections, so `has_sections` will be False and no `tool_calls` entry is added.

### Files changed

| File | Action |
|------|--------|
| `api/research/runtime.py` | Add scoped `tool_calls` metadata extraction in `persist_research_tool_result()` |

---

## Verification

### Part 1 verification
1. Restart the gateway after changes
2. `curl -s -b /tmp/hank_cookies.txt 'http://localhost:5001/api/research/content/extractions?filing_id=MSFT_10Q_2025_6f90a2a7&section=Part+II%2C+Item+1A.+Risk+Factors&schemas=risk_factors'` — should return extractions with `{status: ok}` shape
3. Test error path: request with invalid `schema_name` — should return 400, not 500
4. MCP tool still works: `mcp__langextract-mcp__extract_filing_file` with a real filing path (verifies server.py thin wrapper)

### Part 2 verification
1. Start a research conversation, ask the agent to pull MSFT filing sections
2. Check the conversation feed — the `get_filing_sections` tool call message should show "Open in reader" button
3. Click it — should ingest → open document viewer → extraction highlights render on Risk Factors section
4. Verify that `file_read`/`file_write` tool calls do NOT show "Open in reader" (scoping check)
5. Verify that a tool call returning empty sections (e.g., failed EDGAR lookup) does NOT show the button (headerless guard)

### Fallback curl test for Part 2
Query the research messages API and verify `tool_calls` metadata is present on `get_filing_sections` tool call messages but not on `file_read` messages.

---

## Codex R1 findings addressed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | `tool_calls` on tool_call row vs assistant message | High | Verified: `ConversationFeed.tsx` checks `metadata?.toolCalls?.length` on ALL messages including `content_type="tool_call"` (line 106). Adding to tool_call row works. |
| 2 | Generic `file_path` check promotes non-filing tools | High | Scoped to `_FILING_TOOL_NAMES` allowlist (`get_filing_sections` only). `extract_filing_file` excluded — different result shape. |
| 3 | `langextract` not in gateway's `requirements.in` | High | **v3 fix**: Two layers. (1) `extraction.py` lazy-imports `langextract` inside function body — no startup crash. (2) Add `langextract` to `api/requirements.in` and run `make deps-lock` — clean installs include it. |
| 4 | Error normalization regression | Medium | `extract_filing()` wraps in try/except, returns `{status: "error", error: str(exc)}`. Same contract as current MCP tool. |
| 5 | Headerless/empty filing files | Medium | Guard: check `len(sections_found) > 0` before adding `tool_calls`. Empty files won't get the "Open in reader" button. |
| 6 | Soft error propagation | Medium | `is_error` check excludes hard errors. `sections_found` check excludes soft errors (`{status: "error"}` results have no sections). |

## Codex R2 findings addressed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | Lazy import still hits `langextract` at import time via `schemas.py` | High | Fixed: `extraction.py` lazy-imports both `langextract.extraction.extract` AND `schemas.get_schema` inside the function body. Zero module-level deps on `langextract`. |
| 2 | `extract_filing_file` in allowlist but result shape mismatch | Medium | Removed `extract_filing_file` from `_FILING_TOOL_NAMES`. Only `get_filing_sections` remains. Guard uses `sections_found` which matches `get_filing_sections` result shape. |

## Codex R3 findings addressed

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | Clean install still fails at request time — `langextract` not declared | High | Fixed: add `langextract` to `api/requirements.in`, run `make deps-lock`. Lazy import prevents startup crash; declared dep prevents runtime `ModuleNotFoundError`. |

---

## Files summary

| File | Repo | Action |
|------|------|--------|
| `mcp_servers/langextract_mcp/extraction.py` | AI-excel-addin | **New** — core extraction logic, error-safe |
| `mcp_servers/langextract_mcp/server.py` | AI-excel-addin | Slim down to thin MCP wrapper |
| `api/research/document_service.py` | AI-excel-addin | Change lazy import target |
| `api/requirements.in` | AI-excel-addin | Add `langextract` dependency |
| `api/research/runtime.py` | AI-excel-addin | Add scoped `tool_calls` metadata |
