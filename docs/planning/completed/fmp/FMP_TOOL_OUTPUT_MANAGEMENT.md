# FMP Tool Output Management — Implementation Plan

**Status:** Completed 2026-02-23
**Commit:** `8ad5cc24` feat(fmp): add output management for AI-friendly tool responses

## Goal

Add `output="file"`, column filtering, and auto-summary capabilities to 4 FMP tools so large datasets go to disk instead of overwhelming the AI agent's context window. Also add `limit` and `last_n` params where missing.

## Design Principle

**Give the agent computed facts inline, raw data in files.**

When row count exceeds ~50, the agent tends to "scan and guess" rather than precisely compute. The tool output shape should steer the agent toward:
1. Trusting precise summary stats (computed by code)
2. Using file output + Read/Grep for deeper analysis

## Reference Implementation

`fmp/tools/transcripts.py` already implements the file-write pattern. Key pieces to reuse:

- **`_transcript_cache_base()`** (line 122) — resolves `FMP_CACHE_DIR` env var → project root fallback → `~/.cache/fmp-mcp/`. Extract this into a shared helper.
- **`FILE_OUTPUT_DIR`** (line 135) — `_CACHE_BASE / "cache" / "file_output"`. All tools should write to the same directory.
- **`_atomic_write_text()`** (line 645) — atomic write using tempfile + `os.replace()`. Extract for reuse.
- **Return shape for file mode** (line 1066-1076) — strip large data from response, add `file_path`, `hint`, keep metadata inline.

### Shared Utility: `fmp/tools/_file_output.py` (NEW)

Create this file to hold shared file-write helpers. All 4 tools will import from here.

```python
"""Shared file-output utilities for FMP tools."""
import csv
import os
import tempfile
from pathlib import Path

def _cache_base() -> Path:
    """Resolve the base cache directory."""
    env = os.getenv("FMP_CACHE_DIR")
    if env:
        return Path(env).expanduser().resolve()
    project_root = Path(__file__).parent.parent.parent
    if (project_root / "settings.py").exists():
        return project_root
    xdg = os.getenv("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))
    return Path(xdg) / "fmp-mcp"

FILE_OUTPUT_DIR = _cache_base() / "cache" / "file_output"

def atomic_write_text(path: Path, content: str) -> None:
    """Write content to path atomically (tempfile + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False,
        ) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

def write_csv(records: list[dict], path: Path) -> None:
    """Write list of dicts to CSV atomically."""
    if not records:
        atomic_write_text(path, "")
        return
    fieldnames = list(records[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            delete=False, newline="",
        ) as tmp:
            writer = csv.DictWriter(tmp, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

def auto_summary(records: list[dict], date_col: str = "date") -> dict:
    """Generate summary stats for a list of record dicts.

    Returns dict with: row_count, date_range, column_stats (min, max, latest,
    pct_change for numeric columns).
    """
    summary = {"row_count": len(records)}
    if not records:
        return summary

    # Date range
    dates = [r.get(date_col) for r in records if r.get(date_col)]
    if dates:
        summary["date_range"] = {"earliest": min(dates), "latest": max(dates)}

    # Numeric column stats
    numeric_cols = {}
    for key, val in records[0].items():
        if key == date_col:
            continue
        if isinstance(val, (int, float)) and val is not None:
            numeric_cols[key] = True

    col_stats = {}
    for col in numeric_cols:
        values = [r[col] for r in records if r.get(col) is not None and isinstance(r[col], (int, float))]
        if not values:
            continue
        stats = {
            "min": min(values),
            "max": max(values),
            "latest": values[0],  # records typically ordered newest-first
        }
        if len(values) >= 2 and values[-1] != 0:
            stats["pct_change"] = round((values[0] - values[-1]) / abs(values[-1]) * 100, 2)
        col_stats[col] = stats

    if col_stats:
        summary["column_stats"] = col_stats
    return summary
```

Also refactor `transcripts.py` to import `_cache_base` and `atomic_write_text` from `_file_output.py` instead of defining its own copies. Keep `FILE_OUTPUT_DIR` and `PARSED_CACHE_DIR` in transcripts.py but derive them from the shared `_cache_base()`.

---

## Tool 1: `fmp_fetch` — HIGH priority

**File:** `fmp/tools/fmp_core.py` (function `fmp_fetch`, line 75)

### Current behavior
- Takes `endpoint`, `symbol`, `period`, `limit`, `use_cache`, `**kwargs`
- Returns `{"status": "success", "endpoint", "params", "row_count", "columns", "data": [records]}`
- All records returned inline, no column filtering, no file output

### Changes

#### 1a. Add `columns` parameter (list[str] | None)
- New optional param: `columns: list[str] | None = None`
- After fetching DataFrame (line 132), if `columns` is provided, filter: `df = df[[c for c in columns if c in df.columns]]`
- Include a `filtered_columns` field in response listing which columns were kept
- If none of the requested columns exist, return all columns with a warning

#### 1b. Add `output` parameter ("inline" | "file")
- New optional param: `output: Literal["inline", "file"] = "inline"`
- When `output="file"`:
  - Write records to CSV using `write_csv()` from `_file_output.py`
  - File path: `FILE_OUTPUT_DIR / f"{endpoint}_{symbol or 'no_symbol'}_{timestamp}.csv"` (use ISO timestamp for uniqueness)
  - Return: `{"status": "success", "endpoint", "params", "row_count", "columns", "file_path": str, "hint": "Use Read tool with file_path, or Grep to search columns."}`
  - Do NOT include `data` in file mode response (that's the whole point)

#### 1c. Add auto-summary for large results
- When `row_count > 50` (regardless of output mode), include a `summary` field using `auto_summary()` from `_file_output.py`
- Summary provides: row_count, date_range, numeric column stats (min, max, latest, pct_change)
- Agent gets enough context to decide if it needs the raw data

#### Updated signature
```python
def fmp_fetch(
    endpoint: str,
    symbol: Optional[str] = None,
    period: Optional[str] = None,
    limit: Optional[int] = None,
    columns: Optional[list[str]] = None,
    output: Literal["inline", "file"] = "inline",
    use_cache: bool = True,
    **kwargs: Any,
) -> dict:
```

#### Updated return shape (file mode)
```python
{
    "status": "success",
    "endpoint": "income_statement",
    "params": {"symbol": "AAPL", "period": "annual"},
    "row_count": 25,
    "columns": ["date", "revenue", "netIncome"],
    "summary": {
        "row_count": 25,
        "date_range": {"earliest": "2000-01-01", "latest": "2024-12-31"},
        "column_stats": {
            "revenue": {"min": 8279, "max": 394328, "latest": 394328, "pct_change": 4661.2},
        }
    },
    "output": "file",
    "file_path": "/Users/.../.cache/fmp-mcp/cache/file_output/income_statement_AAPL_20260223T.csv",
    "hint": "Use Read tool with file_path, or Grep to search columns."
}
```

#### Updated return shape (inline mode, large result)
```python
{
    "status": "success",
    "endpoint": "historical_price_adjusted",
    "params": {"symbol": "AAPL"},
    "row_count": 252,
    "columns": ["date", "open", "high", "low", "close", "volume"],
    "summary": { ... },  # auto-included because row_count > 50
    "data": [ ... ],      # still inline
}
```

### Register in `fmp/server.py`
Update the `fmp_fetch` tool registration to include the new `columns` and `output` parameters in the FastMCP tool schema.

---

## Tool 2: `get_technical_analysis` — MEDIUM priority

**File:** `fmp/tools/technical.py`

### Current behavior
- `format="summary"`: Returns current signals, composite score, support/resistance. Compact. **No changes needed.**
- `format="full"`: Appends `time_series` with raw data for 7 indicators × 100+ candles. 1,000+ data points inline.

### Changes

#### 2a. Add `output` parameter ("inline" | "file")
- New optional param: `output: Literal["inline", "file"] = "inline"`
- Only relevant when `format="full"` — summary mode ignores it (always inline, already compact)
- When `format="full"` and `output="file"`:
  - Write time_series data to CSV: `FILE_OUTPUT_DIR / f"technical_{symbol}_{timestamp}.csv"`. Flatten the time_series dict into rows — each row has: `date`, `indicator`, `value` (or one column per indicator if that's cleaner for the data shape).
  - Return the summary signals inline (everything except `time_series`) + `file_path` + `hint`
  - Strip `time_series` from inline response

#### 2b. Add `last_n` parameter (int | None)
- New optional param: `last_n: int | None = None`
- When provided, slice time_series to last N data points per indicator before returning (whether inline or file)
- Example: `last_n=20` returns only the 20 most recent candles per indicator
- Useful when agent needs recent history without the full 100+ candle dump

#### Updated signature
```python
def get_technical_analysis(
    symbol: str,
    format: Literal["summary", "full"] = "summary",
    indicators: list[str] | None = None,
    output: Literal["inline", "file"] = "inline",
    last_n: int | None = None,
) -> dict:
```

### Register in `fmp/server.py`
Update the tool registration to include `output` and `last_n` parameters.

---

## Tool 3: `get_economic_data` — MEDIUM priority

**File:** `fmp/tools/market.py`

### Current behavior
- Two modes: `mode="indicator"` (time series) and `mode="calendar"` (upcoming events)
- Summary mode: computed facts (latest, previous, change, trend). **No changes needed.**
- Full mode for indicators: returns full time series (2-year default lookback). Weekly data = 100+ rows.
- Calendar full mode: bounded at 90 days. **No changes needed.**

### Changes

#### 3a. Add `limit` parameter for indicator mode (int | None)
- New optional param: `limit: int | None = None`
- When `mode="indicator"` and `limit` is provided, slice the time series to the last N data points
- Does NOT apply to calendar mode
- Example: `limit=12` for last 12 monthly readings

#### 3b. Add `output` parameter ("inline" | "file")
- New optional param: `output: Literal["inline", "file"] = "inline"`
- Only applies to indicator mode with `format="full"`
- When `output="file"`:
  - Write time series to CSV: `FILE_OUTPUT_DIR / f"economic_{indicator_name}_{timestamp}.csv"`
  - Return summary stats inline (same as summary mode output) + `file_path` + `hint`
  - Strip the raw time series from inline response
- Calendar mode and summary mode always stay inline

#### Updated signature
```python
def get_economic_data(
    mode: Literal["indicator", "calendar"] = "indicator",
    indicator: str | None = None,
    format: Literal["summary", "full"] = "summary",
    lookback_years: int = 2,
    limit: int | None = None,
    output: Literal["inline", "file"] = "inline",
    country: str = "US",
    use_cache: bool = True,
) -> dict:
```

### Register in `fmp/server.py`
Update the tool registration to include `limit` and `output` parameters.

---

## Tool 4: `get_etf_holdings` — LOW-MEDIUM priority

**File:** `fmp/tools/etf_funds.py`

### Current behavior
- 6 sections: holdings, sectors, countries, info, exposure, disclosure
- `include` filter to select sections. `limit` param caps list lengths (default 25, max 200).
- Summary mode extracts key fields. Full mode returns all raw fields.
- Live test: SPY full mode holdings = 89,919 characters (504 holdings × many fields)

### Changes

#### 4a. Add `output` parameter ("inline" | "file")
- New optional param: `output: Literal["inline", "file"] = "inline"`
- Only applies to **full mode holdings section** — sectors, countries, info, exposure, disclosure are small enough to stay inline always
- When `format="full"` and holdings are included and `output="file"`:
  - Write complete holdings list to CSV: `FILE_OUTPUT_DIR / f"etf_holdings_{symbol}_{timestamp}.csv"`
  - Replace holdings in inline response with summary stats: `{"holdings_count": N, "top_5": [...], "weight_coverage_top_25": "X%", "file_path": "...", "hint": "..."}`
  - Other sections stay inline as-is

#### Updated signature
```python
def get_etf_holdings(
    symbol: str,
    include: str = "holdings,sectors,countries",
    format: Literal["summary", "full"] = "summary",
    limit: int = 25,
    output: Literal["inline", "file"] = "inline",
    use_cache: bool = True,
) -> dict:
```

### Register in `fmp/server.py`
Update the tool registration to include `output` parameter.

---

## Tool 5: `get_events_calendar` — LOW priority (minimal change)

**File:** `fmp/tools/news_events.py`

### Current behavior
- Has limit (default 50, max 500), event_type filter, symbol filter, date range, format modes
- Already well-designed with truncation indicators

### Change

#### 5a. Lower default limit when `event_type="all"` and no symbol filter
- When `event_type="all"` and `symbols` is empty/None, use default limit=20 instead of 50
- Rationale: 50 mixed events with no symbol filter is noise. Agent should filter by type or symbol.
- Implementation: at the top of the function, after param validation:
  ```python
  if event_type == "all" and not symbols and limit is None:
      limit = 20
  ```
  (Only override if caller didn't explicitly pass a limit)
- No file-write needed — events are naturally narrowed by filters

---

## Tool 6: `screen_estimate_revisions` — DEFERRED

**File:** `fmp/tools/estimates.py`

Low priority — dataset is still being built. When universe grows to 500+:
- Add `limit` param (default 50)
- Add `format` param (summary/full)

**Do not implement now.**

---

## Implementation Order

1. **Create `fmp/tools/_file_output.py`** — shared utilities (cache base, atomic write, write_csv, auto_summary)
2. **Refactor `fmp/tools/transcripts.py`** — import shared helpers from `_file_output.py` instead of local copies
3. **`fmp_fetch`** — add `columns`, `output`, auto-summary (Tool 1)
4. **`get_technical_analysis`** — add `output`, `last_n` (Tool 2)
5. **`get_economic_data`** — add `limit`, `output` (Tool 3)
6. **`get_etf_holdings`** — add `output` (Tool 4)
7. **`get_events_calendar`** — lower default limit for unfiltered `all` mode (Tool 5)
8. **Update `fmp/server.py`** — update tool registrations with new parameters
9. **Test** — run existing tests, verify new params work, verify file output writes to correct location

## Testing

- Existing tests in `tests/mcp_tools/` should still pass (new params are all optional with backward-compatible defaults)
- For each tool, verify:
  - Default behavior unchanged (no params = same output as before)
  - `columns` filtering works and handles missing columns gracefully
  - `output="file"` writes CSV and returns file_path without data
  - Auto-summary fires when row_count > 50
  - `last_n` / `limit` correctly slices results
  - File paths resolve correctly in both monorepo and standalone installs
