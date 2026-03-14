# Plan: Cash Back-Solve Replay Truncation

**Status:** IMPLEMENTED
**Goal:** Fix ~$4,069 NAV gap by truncating cash replay at statement end date during back-solve

## Context

The cash back-solve computes starting cash as:
```
starting_cash = IBKR_ending_cash - replay_total
```

The IBKR ending cash comes from the statement (measured at Mar 3). But `replay_total`
includes transactions **after** Mar 3 (SLV SELL, GOLD BUY, DHT BUY on Mar 4-6),
adding +$4,069 of post-statement cash flow. This makes the anchor $4,069 too negative,
which propagates to every month's NAV.

**Verified finding (2026-03-08):** Position values match IBKR within 0.1% at every
anchor point. The entire NAV gap is from this cash back-solve date mismatch. Correcting
it brings NAV within $73 of IBKR at all anchor dates.

## Root Cause

`engine.py:2123`:
```python
replay_final_cash = cash_snapshots[-1][1] if cash_snapshots else 0.0
```

This takes the **last** cash snapshot (which includes all transactions through
the latest Flex trade). It should instead use the snapshot at the statement end date.

## Fix

### Step 1: Extract statement end date from DB

**File:** `ibkr/flex.py` — `extract_statement_cash()`

Use pattern-based table discovery (matching the existing `cash_report%` pattern) to
find the statement table, then extract and parse the Period field:

```python
# After the cash_report query + result dict construction, also extract period dates:
# Re-open (or reuse) the connection for statement table lookup
try:
    # Discover statement table name (same pattern as cash_report discovery)
    stmt_tables = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'statement%' ORDER BY name"
        ).fetchall()
    ]
    if stmt_tables:
        stmt_table = next(
            (t for t in stmt_tables if t.endswith("__all")), stmt_tables[0]
        )
        stmt_rows = conn.execute(
            f"SELECT field_value FROM [{stmt_table}] "
            "WHERE field_name = 'Period'"
        ).fetchall()
        if stmt_rows:
            # Period format: "April 1, 2025 - March 3, 2026"
            period_str = str(stmt_rows[0][0]).strip()
            parts = period_str.split(" - ")
            if len(parts) == 2:
                from dateutil.parser import parse as parse_date
                result["period_start"] = parse_date(parts[0]).strftime("%Y-%m-%d")
                result["period_end"] = parse_date(parts[1]).strftime("%Y-%m-%d")
except Exception:
    pass  # period dates are optional; back-solve still works without them
```

The returned dict becomes:
```python
{
    "starting_cash_usd": -11097.13,
    "ending_cash_usd": -8727.25,
    "period_start": "2025-04-01",
    "period_end": "2026-03-03",
    "source": "ibkr_statement",
    "db_path": "..."
}
```

### Step 2: Thread period_end through metadata to engine

**File:** `core/realized_performance/engine.py` — `_statement_cash_from_metadata()`

Currently returns `float | None` (just `ending_cash_usd`). Change to return
a dict so we can access `period_end`:

```python
def _statement_cash_from_metadata() -> dict[str, Any] | None:
    """Extract IBKR statement cash + period dates from fetch_metadata."""
    for row in provider_fetch_metadata:
        if str(row.get("provider") or "").strip().lower() != "ibkr_flex":
            continue
        sc = row.get("statement_cash")
        if isinstance(sc, dict) and sc.get("ending_cash_usd") is not None:
            return sc  # full dict including period_end
    return None
```

### Step 3: Truncate replay at statement end date in back-solve

**File:** `core/realized_performance/engine.py` — lines 2123, 2147-2163

#### 3a: Add module-level helper function for replay truncation

Add a **module-level** function in `engine.py` (outside `_analyze_realized_performance_single_scope`)
so it can be unit-tested directly. This will be reused for both the main back-solve
and the observed-only branch:

```python
def _truncate_replay_at_date(
    cash_snapshots: List[Tuple[datetime, float]],
    cutoff_date: _date_type,
    full_replay: float,
) -> float:
    """Return the replay cash value at or before cutoff_date.

    Iterates through chronologically-sorted cash_snapshots and returns the
    last snapshot value on or before cutoff_date. If NO snapshot is on or
    before the cutoff, returns 0.0 (no replay had occurred yet).

    Parameters
    ----------
    cash_snapshots : list of (datetime, float)
        Chronologically sorted cumulative cash snapshots.
    cutoff_date : date-like
        The statement end date to truncate at.
    full_replay : float
        The untruncated replay total (used only as sanity reference, not returned).

    Returns
    -------
    float
        Truncated replay value.
    """
    if not cash_snapshots:
        return 0.0
    result = 0.0  # if all snapshots are after cutoff, replay at cutoff is 0
    for snap_dt, snap_val in cash_snapshots:
        if snap_dt.date() <= cutoff_date:
            result = snap_val
        else:
            break
    return result
```

#### 3b: Apply truncation in main back-solve path

Initialize `_period_end_str` and `_stmt_end_date` before the if/else block so they
are accessible in both the main back-solve and the observed-only branch (Step 3c).
Parse `_stmt_end_date` eagerly (outside any `cash_snapshots` guard) so the
observed-only branch shares the exact same cutoff regardless of main-path state:

```python
# Initialize period tracking (before the if/else block)
_period_end_str: Optional[str] = None
_stmt_end_date: Optional[_date_type] = None

# ...existing futures branch unchanged...

else:
    # Legacy observed-cash anchor path (non-futures only)
    statement_info = (
        _statement_cash_from_metadata()
        if source == "ibkr_flex" and not disable_statement_cash
        else None
    )
    if statement_info is not None:
        observed_end_cash = float(statement_info["ending_cash_usd"])
        _cash_anchor_matched_rows = 1
        cash_anchor_source = "ibkr_statement"

        # Parse statement end date eagerly (shared with observed-only branch)
        _period_end_str = statement_info.get("period_end")
        if _period_end_str:
            _stmt_end_date = pd.Timestamp(_period_end_str).date()

        # Truncate replay at statement end date for back-solve
        if _stmt_end_date and cash_snapshots:
            replay_final_cash = _truncate_replay_at_date(
                cash_snapshots, _stmt_end_date, replay_final_cash
            )
    else:
        observed_end_cash, _cash_anchor_matched_rows = _cash_anchor_offset_from_positions()
        cash_anchor_source = "snaptrade_cur"
    back_solved_start_cash = observed_end_cash - replay_final_cash
    raw_observed_cash_anchor_offset = back_solved_start_cash
    cash_anchor_available = abs(raw_observed_cash_anchor_offset) > 1e-9
```

#### 3c: Apply same truncation in observed-only branch

The engine computes a second back-solve for the observed-only NAV track at line 2255.
This must use the same cutoff, otherwise the observed-only diagnostics
(`observed_only_cash_anchor_offset_usd`, `nav_pnl_observed_only_usd`) will remain
polluted by post-statement cash flow:

```python
# Current (line 2255):
observed_replay_final = observed_cash_snapshots[-1][1] if observed_cash_snapshots else 0.0

# New:
observed_replay_final = observed_cash_snapshots[-1][1] if observed_cash_snapshots else 0.0
if _stmt_end_date and observed_cash_snapshots:
    observed_replay_final = _truncate_replay_at_date(
        observed_cash_snapshots, _stmt_end_date, observed_replay_final
    )
```

### Step 4: Update diagnostics metadata

**File:** `core/realized_performance/engine.py` — metadata dict (around line 2795)

Add `cash_anchor_statement_period_end` to the diagnostics:

```python
"cash_anchor_statement_period_end": _period_end_str if cash_anchor_source == "ibkr_statement" else None,
```

### Step 5: Update `RealizedMetadata` dataclass

**File:** `core/result_objects/realized_performance.py`

Add the new field to the dataclass, `to_dict()`, and `from_dict()` so it survives
round-trip serialization:

```python
# In the dataclass fields (after cash_anchor_source, line ~137):
cash_anchor_statement_period_end: Optional[str] = None

# In to_dict() (after "cash_anchor_source" entry):
"cash_anchor_statement_period_end": self.cash_anchor_statement_period_end,

# In from_dict() (after cash_anchor_source= line):
cash_anchor_statement_period_end=d.get("cash_anchor_statement_period_end"),
```

## Files Modified

| File | Change |
|------|--------|
| `ibkr/flex.py:1511` | `extract_statement_cash()` — add period date extraction using pattern-based `statement%` table discovery |
| `core/realized_performance/engine.py:2081` | `_statement_cash_from_metadata()` — return full dict instead of float |
| `core/realized_performance/engine.py:2123+2147` | Back-solve — add `_truncate_replay_at_date()` helper; truncate `replay_final_cash` at statement end date |
| `core/realized_performance/engine.py:~2255` | Observed-only branch — apply same truncation to `observed_replay_final` |
| `core/realized_performance/engine.py:~2795` | Add `cash_anchor_statement_period_end` to metadata dict |
| `core/result_objects/realized_performance.py` | Add `cash_anchor_statement_period_end` field + `to_dict()`/`from_dict()` |

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| No `period_end` in statement_cash | `_period_end_str` is None → no truncation → fallback to existing behavior (last snapshot) |
| All transactions before statement end | `_truncate_replay_at_date()` returns last snapshot value → same as untruncated (no-op) |
| **All transactions after statement end** | `_truncate_replay_at_date()` returns `0.0` (correct: no replay had occurred at statement date) |
| Empty `cash_snapshots` | Returns `0.0` (existing behavior preserved) |
| Only `statement__all` table (no `statement__01`) | Pattern-based discovery finds it via `LIKE 'statement%'` + `__all` preference |
| Multi-account IBKR | Known limitation: single-account only (first-match returns same value). Documented in existing code. |

## Tests

### New test file: `tests/core/test_cash_backsolve_truncation.py`

Tests are in a **separate file** to avoid interference with the 20 existing tests in
`test_realized_cash_anchor.py` (16 of which currently fail due to `cash_anchor_mode` /
`cash_anchor_observed_start_usd` fields from the deferred DUAL_CASH_ANCHOR_PLAN).

#### Unit tests for `_truncate_replay_at_date()`:

1. **`test_truncate_replay_at_cutoff_date`** — 3 snapshots (day 1, day 5, day 10).
   Cutoff = day 5. Assert returns day 5 value.

2. **`test_truncate_replay_all_before_cutoff`** — 3 snapshots all before cutoff.
   Assert returns last snapshot value (same as untruncated).

3. **`test_truncate_replay_all_after_cutoff`** — 3 snapshots all after cutoff.
   Assert returns `0.0` (not the full replay value).

4. **`test_truncate_replay_empty_snapshots`** — Empty list. Assert returns `0.0`.

#### Integration tests (mock `_analyze_realized_performance_single_scope`):

5. **`test_backsolve_truncated_at_statement_end`** — Build statement_cash with
   `period_end`, cash_snapshots with post-statement trades. Verify
   `cash_backsolve_replay_final_usd` uses truncated value and
   `cash_backsolve_start_usd` reflects the truncation.

6. **`test_backsolve_no_truncation_without_period_end`** — Same setup but
   statement_cash has no `period_end` key. Verify fallback to last snapshot.

7. **`test_backsolve_no_post_statement_trades`** — All transactions before
   statement end date. Verify truncation is a no-op.

8. **`test_observed_only_branch_uses_same_truncation`** — Verify
   `observed_only_cash_anchor_offset_usd` also reflects the truncated replay
   (not the full post-statement replay).

#### `extract_statement_cash()` tests:

9. **`test_extract_statement_cash_includes_period`** — Mock SQLite DB with
   `statement__01` table containing Period field. Verify returns `period_start`
   and `period_end`.

10. **`test_extract_statement_cash_statement_all_table`** — Mock SQLite DB with
    `statement__all` table (no `statement__01`). Verify discovery finds it and
    returns period dates.

11. **`test_extract_statement_cash_no_statement_table`** — Mock SQLite DB without
    any `statement%` table. Verify graceful fallback (no period fields, cash still
    returned).

#### `_statement_cash_from_metadata()` test:

12. **`test_statement_metadata_returns_dict`** — Verify returns the full dict
    (not just the float) when statement_cash has period dates.

#### `RealizedMetadata` round-trip test:

13. **`test_realized_metadata_period_end_round_trip`** — Create `RealizedMetadata`
    with `cash_anchor_statement_period_end="2026-03-03"`. Verify `to_dict()`
    includes it and `from_dict(to_dict())` preserves it.

### Regression:

```bash
# New truncation tests (should all pass):
pytest tests/core/test_cash_backsolve_truncation.py -x -q

# Existing performance tests (should remain green):
pytest tests/core/test_realized_performance_analysis.py -x -q

# Note: test_realized_cash_anchor.py has 16 pre-existing failures from the
# deferred DUAL_CASH_ANCHOR_PLAN (cash_anchor_mode / cash_anchor_observed_start_usd
# fields). Those failures are unrelated to this change and should NOT block this PR.
```

## Verification

After implementation, re-run:
```
get_performance(mode="realized", source="ibkr_flex", format="full", debug_inference=True)
```

Check:
- `cash_anchor_statement_period_end` = "2026-03-03"
- `cash_backsolve_start_usd` ≈ -$11,024 (was -$18,732)
- Dec 31 NAV ≈ $22,001 (within $75 of IBKR's $21,926)
- Monthly returns shift (e.g., April from -37% to ~-31%)

## Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| Cash anchor | -$18,732 | ~-$11,024 |
| NAV gap vs IBKR | ~$4,069 | ~$73 |
| April return | -37.5% | ~-30.7% |
| TWR | -0.23% | closer to IBKR's +0.29% |
