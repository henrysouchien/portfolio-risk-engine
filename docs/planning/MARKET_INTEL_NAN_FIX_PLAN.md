# Plan: Fix NaN Serialization in Market-Intelligence Descriptions

**Bug**: Market-intelligence descriptions render raw `nan` values in Overview Market Context.
**Severity**: Medium (user-facing cosmetic corruption).
**Status**: Plan draft.

---

## Root Cause

FMP economic calendar data arrives via `fmp/tools/market.py:_fetch_calendar()` (line 453), which calls `df.to_dict("records")` directly on a pandas DataFrame **without** NaN sanitization. Compare with `fmp/tools/news_events.py:_fetch_calendar()` which routes through `_clean_record()` to convert NaN to None. The economic calendar path skips this.

A second consumer, `scripts/chartbook/data_fetcher.py:199`, calls `get_economic_data(mode="calendar", format="full")` and passes the response to `scripts/chartbook/charts_events.py:_build_economic_table()`. The `_fmt_numeric()` helper (line 22) calls `_to_float()` on `estimate`/`actual` — `float('nan')` passes through `_to_float()` (it's already a float), and `f"{nan:,.2f}"` renders literal `"nan"` in the HTML table.

Additionally, while the FMP API returns dates as strings, `pd.NaT` can appear if pandas infers a datetime column with missing values. The scrub must handle NaT alongside NaN — `isinstance(val, float) and math.isnan(val)` does NOT catch `pd.NaT` (it's not a float). Using `pd.isna()` handles both.

In `mcp_tools/news_events.py:_build_economic_events()` (lines 769-777), the code does:

```python
prev = row.get("previous")
est = row.get("estimate")
raw_unit = row.get("unit") or ""
unit = "" if str(raw_unit).lower() == "nan" else str(raw_unit)
if est is not None and prev is not None:
    desc += f" (est: {est}{unit}, prev: {prev}{unit})"
elif est is not None:
    desc += f" (est: {est}{unit})"
```

- Line 773 guards `unit` against NaN via string comparison — works but inconsistent with `math.isnan()` pattern used elsewhere in the codebase.
- Lines 774-777 guard `est`/`prev` with `is not None` — `float('nan')` passes this check, rendering literal `"nan"` in the description.

## NaN Leak Points Found

### Confirmed (economic calendar path)

| # | File | Line(s) | Field(s) | Impact |
|---|------|---------|----------|--------|
| L1 | `mcp_tools/news_events.py` | 770 | `prev = row.get("previous")` | `float('nan')` passes `is not None` guard at L774, renders as `"nan"` in description |
| L2 | `mcp_tools/news_events.py` | 771 | `est = row.get("estimate")` | Same — passes `is not None` guard at L774/L776 |
| L3 | `mcp_tools/news_events.py` | 772-773 | `unit = row.get("unit")` | Already guarded via string comparison — works but inconsistent style |

### Upstream root (why NaN arrives at all)

| # | File | Line(s) | Issue |
|---|------|---------|-------|
| U1 | `fmp/tools/market.py` | 453 | `records = df.to_dict("records")` — no `_clean_record()` pass, unlike `fmp/tools/news_events.py:_fetch_records()` |

### Chartbook consumer (same upstream, different rendering path)

| # | File | Line(s) | Field(s) | Impact |
|---|------|---------|----------|--------|
| L4 | `scripts/chartbook/data_fetcher.py` | 199-204 | Calendar response (all fields) | Calls `get_economic_data(mode="calendar", format="full")` — receives unsanitized records from U1. Passes response dict to chartbook rendering. |
| L5 | `scripts/chartbook/charts_events.py` | 22-28, 55-56 | `estimate`, `actual` | `_fmt_numeric()` calls `_to_float(value)` which returns `float('nan')` for NaN inputs (it's already a float, passes the `float()` cast). Then `f"{numeric:,.2f}"` renders literal `"nan"` in the HTML table. Both `estimate` (line 55) and `actual` (line 56) go through this path unsanitized. |

**Coverage note**: Both L4 and L5 are fully fixed by Change 1 (upstream scrub in `_fetch_calendar()`). The chartbook receives records *after* NaN has been scrubbed to `None`, so `_to_float(None)` returns `None` and `_fmt_numeric` correctly renders `"-"`. Test T9 (below) verifies this explicitly.

### Secondary site (same upstream, different consumer)

| # | File | Line(s) | Issue |
|---|------|---------|-------|
| S4a | `fmp/tools/market.py` | 187-189 | `_format_calendar_summary()` → `upcoming_high_impact` passes through raw `previous`/`estimate`/`actual` from unsanitized records. NaN values leak into the summary dict as `float('nan')`. |
| S4b | `fmp/tools/market.py` | 200-208 | `_format_calendar_summary()` → `recent_surprises`: `actual is not None` and `estimate is not None` both pass for `float('nan')`, producing a NaN `surprise_pct` (e.g. `(nan - nan) / abs(nan) * 100` → `nan`). However, the subsequent filter `abs(surprise_pct) > 0.01` evaluates to `False` for NaN (since all NaN comparisons are False), so NaN rows are silently dropped from `recent_surprises` rather than leaking into output. This is a NaN arithmetic path that happens to be masked by the comparison, not a confirmed output leak. |

**Coverage note**: S4a is a real leak (NaN values pass through to `upcoming_high_impact` dicts). S4b is a masked arithmetic path — NaN `surprise_pct` gets dropped by `abs(surprise_pct) > 0.01` (all NaN comparisons are False), so it never reaches output, but the NaN arithmetic itself is still wrong. Both are fully fixed by Change 1 (upstream scrub). `_format_calendar_summary()` receives records *after* the NaN scrub in `_fetch_calendar()`, so all NaN values are already `None` before reaching lines 187-208. The `is not None` guards at lines 204-206 then correctly exclude NaN-origin fields. Test T8 (below) verifies this end-to-end.

### Market-context events path (separate `to_dict` call, currently masked)

| # | File | Line(s) | Issue |
|---|------|---------|-------|
| S5 | `fmp/tools/market.py` | 1105 | `_safe_fetch_records()` does `df.to_dict("records")` without NaN scrub — a second unsanitized `to_dict` path independent of `_fetch_calendar()`. Records flow through `_normalize_events()` (line 1416), which passes `rec.get("estimate")` through raw. |

**Masking bug**: This path is currently inert because `_normalize_events()` (line 1215) strips the `country` field from records, but the subsequent country filter at line 1418-1421 (`e.get("country").upper() == "US"`) requires it — filtering out ALL events. If/when the country-filter bug is fixed, NaN `estimate` values will leak into the market-context response.

**Fix**: Add the same NaN/NaT scrub to `_safe_fetch_records()` (Change 3 below). Even though S5 is currently masked by the country-filter bug, fixing the NaN leak now prevents it from surfacing when the masking bug is eventually fixed.

### Low-risk (already protected by upstream sanitization)

| # | File | Line(s) | Field | Why safe |
|---|------|---------|-------|---------|
| S1 | `mcp_tools/news_events.py` | 697-698 | `eps_estimated` | Earnings path goes through `fmp/tools/news_events.py:_clean_record()` — NaN converted to None before reaching here |
| S2 | `mcp_tools/news_events.py` | 833-834 | `div_amount` | Dividend path goes through `_clean_record()`. Guard is `if div_amount:` which is falsy for None |
| S3 | `mcp_tools/news_events.py` | 905-906 | `eps_delta` | Estimate revisions come from HTTP JSON API, not pandas — JSON has no NaN type |

## Proposed Fix — Defense in Depth

Fix both the upstream source and the consumption site.

### Change 1: Upstream — sanitize economic calendar records in `fmp/tools/market.py` (U1, S4a, S4b)

Add NaN/NaT scrub after `df.to_dict("records")` in `_fetch_calendar()`. `pandas` is already imported as `pd` at line 1.

**Why `pd.isna()` instead of `isinstance(val, float) and math.isnan(val)`**: `pd.isna()` catches both `float('nan')` AND `pd.NaT` (pandas Not-a-Time). While the economic calendar `date` field is a string from the FMP API, pandas can produce `NaT` if a datetime column has missing values — and `isinstance(val, float) and math.isnan(val)` would NOT catch `NaT` (it's not a float). Using `pd.isna()` is the canonical pandas approach and makes the scrub future-proof against column type changes.

Note: `pd.isna(None)` returns `True`, but since we're scrubbing to `None`, that's a no-op (None→None). We add an explicit `val is not None` guard to avoid the overhead and make the intent clear.

This single fix covers all downstream consumers of the calendar records, including:
- `format="full"` callers (market intelligence) — records in the `data` list are clean (U1)
- `format="full"` callers (chartbook) — `_fmt_numeric()` receives `None` not `float('nan')`, renders `"-"` (L4, L5)
- `_format_calendar_summary()` → `upcoming_high_impact` — `previous`/`estimate`/`actual` fields are `None` not `float('nan')` (S4a)
- `_format_calendar_summary()` → `recent_surprises` — `actual is not None` correctly excludes scrubbed-to-None values, preventing NaN arithmetic in `surprise_pct` (S4b; pre-fix the NaN was masked by `abs(nan) > 0.01 → False`, but the arithmetic was still wrong)

**Before** (line 453):
```python
    records = df.to_dict("records") if not df.empty else []
```

**After**:
```python
    records = df.to_dict("records") if not df.empty else []
    # Scrub NaN/NaT values from pandas serialization (matches fmp/tools/news_events.py _clean_record pattern)
    for rec in records:
        for key, val in rec.items():
            if val is not None and pd.isna(val):
                rec[key] = None
```

### Change 2: Consumption-site — guard `est`/`prev` formatting in `mcp_tools/news_events.py` (L1, L2, L3)

Add a helper near existing `_coerce_symbol()` (line 86). `math` is already imported at line 7.

**Note**: This helper is defense-in-depth only (Change 1 scrubs NaN/NaT at the source). At the call sites, values from pandas `to_dict("records")` are already typed (`int`, `float`, or `None`) — we don't need full type validation, just a None/NaN presence check. The name `_not_nan_or_none` makes this semantic clear.

```python
def _not_nan_or_none(value: object) -> bool:
    """Return True if *value* is present (not None and not float NaN).

    Defense-in-depth guard for values arriving from pandas to_dict("records"),
    where missing data appears as None or float('nan').
    """
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    return True
```

Update `_build_economic_events()` lines 774-777:

**Before**:
```python
                    if est is not None and prev is not None:
                        desc += f" (est: {est}{unit}, prev: {prev}{unit})"
                    elif est is not None:
                        desc += f" (est: {est}{unit})"
```

**After**:
```python
                    if _not_nan_or_none(est) and _not_nan_or_none(prev):
                        desc += f" (est: {est}{unit}, prev: {prev}{unit})"
                    elif _not_nan_or_none(est):
                        desc += f" (est: {est}{unit})"
```

No changes needed for the `unit` guard on line 773 — it already works. Could optionally be migrated to use `_not_nan_or_none` for consistency, but not required.

### Change 3: Upstream — sanitize `_safe_fetch_records()` in `fmp/tools/market.py` (S5)

`_safe_fetch_records()` at line 1105 is a second unsanitized `to_dict("records")` path, independent of `_fetch_calendar()`. Even though S5 is currently masked by the country-filter bug, fix it now to prevent NaN leaks when the masking bug is resolved.

**Before** (line 1105):
```python
            return {"ok": True, "data": df.to_dict("records"), "error": None}
```

**After**:
```python
            records = df.to_dict("records")
            for rec in records:
                for key, val in rec.items():
                    if val is not None and pd.isna(val):
                        rec[key] = None
            return {"ok": True, "data": records, "error": None}
```

Same pattern as Change 1. `pd` is already imported at line 1.

## Test Plan

### Tests in `tests/mcp_tools/test_news_events_builder.py`

Follow the file's existing pattern: `_patch_empty_sources()` + monkeypatch `get_economic_data` + assert on event descriptions.

**T1: NaN estimate and previous are stripped from description**

```python
def test_build_market_events_economic_nan_estimate_and_previous(monkeypatch):
    """float('nan') estimate/previous must not leak into description."""
    _patch_empty_sources(monkeypatch)
    monkeypatch.setattr(
        news_events,
        "get_economic_data",
        lambda **kwargs: {
            "status": "success",
            "data": [
                {
                    "event": "CPI",
                    "date": _future_date(1),
                    "impact": "High",
                    "estimate": float("nan"),
                    "previous": float("nan"),
                    "unit": "%",
                },
            ],
        },
    )

    events = news_events.build_market_events()

    assert len(events) == 1
    assert events[0]["description"] == "CPI"
    assert "nan" not in events[0]["description"].lower()
```

**T2: NaN estimate only (previous is valid) — no parenthetical**

```python
def test_build_market_events_economic_nan_estimate_valid_previous(monkeypatch):
    """When only estimate is NaN, no parenthetical should appear."""
    _patch_empty_sources(monkeypatch)
    monkeypatch.setattr(
        news_events,
        "get_economic_data",
        lambda **kwargs: {
            "status": "success",
            "data": [
                {
                    "event": "Nonfarm Payrolls",
                    "date": _future_date(1),
                    "impact": "High",
                    "estimate": float("nan"),
                    "previous": 227,
                    "unit": "K",
                },
            ],
        },
    )

    events = news_events.build_market_events()

    assert len(events) == 1
    assert events[0]["description"] == "Nonfarm Payrolls"
    assert "nan" not in events[0]["description"].lower()
```

**T3: Valid estimate and previous render correctly (regression guard)**

```python
def test_build_market_events_economic_valid_estimate_and_previous(monkeypatch):
    """Valid numeric estimate/previous should still appear in description."""
    _patch_empty_sources(monkeypatch)
    monkeypatch.setattr(
        news_events,
        "get_economic_data",
        lambda **kwargs: {
            "status": "success",
            "data": [
                {
                    "event": "CPI",
                    "date": _future_date(1),
                    "impact": "High",
                    "estimate": 3.1,
                    "previous": 2.9,
                    "unit": "%",
                },
            ],
        },
    )

    events = news_events.build_market_events()

    assert len(events) == 1
    assert "(est: 3.1%, prev: 2.9%)" in events[0]["description"]
```

**T4: NaN unit is stripped (with valid est/prev)**

```python
def test_build_market_events_economic_nan_unit(monkeypatch):
    """NaN unit should not appear between value and parenthesis."""
    _patch_empty_sources(monkeypatch)
    monkeypatch.setattr(
        news_events,
        "get_economic_data",
        lambda **kwargs: {
            "status": "success",
            "data": [
                {
                    "event": "GDP",
                    "date": _future_date(1),
                    "impact": "High",
                    "estimate": 200,
                    "previous": 195,
                    "unit": float("nan"),
                },
            ],
        },
    )

    events = news_events.build_market_events()

    assert len(events) == 1
    assert "(est: 200, prev: 195)" in events[0]["description"]
    assert "nan" not in events[0]["description"].lower()
```

**T5: NaN previous only (estimate is valid) — show estimate without previous**

```python
def test_build_market_events_economic_nan_previous_valid_estimate(monkeypatch):
    """When only previous is NaN, description should show (est: X) without previous."""
    _patch_empty_sources(monkeypatch)
    monkeypatch.setattr(
        news_events,
        "get_economic_data",
        lambda **kwargs: {
            "status": "success",
            "data": [
                {
                    "event": "Initial Jobless Claims",
                    "date": _future_date(1),
                    "impact": "High",
                    "estimate": 215,
                    "previous": float("nan"),
                    "unit": "K",
                },
            ],
        },
    )

    events = news_events.build_market_events()

    assert len(events) == 1
    assert "(est: 215K)" in events[0]["description"]
    assert "prev" not in events[0]["description"]
    assert "nan" not in events[0]["description"].lower()
```

**T6: Unit-level `_not_nan_or_none` helper coverage**

The helper is a None/NaN presence check — it returns `True` for any value that is not `None` and not `float('nan')`. It does NOT validate type (strings, bools, etc. are considered "present"). This matches its purpose: guarding pandas `to_dict("records")` output where missing data is `None` or `float('nan')`.

```python
def test_not_nan_or_none_helper():
    """Direct coverage of the _not_nan_or_none helper."""
    from mcp_tools.news_events import _not_nan_or_none

    # Present values (not None, not NaN)
    assert _not_nan_or_none(3.14) is True
    assert _not_nan_or_none(0) is True
    assert _not_nan_or_none(0.0) is True
    assert _not_nan_or_none(-1.5) is True
    assert _not_nan_or_none(42) is True
    assert _not_nan_or_none(float("inf")) is True  # inf is a valid float, not NaN
    assert _not_nan_or_none("some string") is True  # present (not None/NaN)
    assert _not_nan_or_none(True) is True            # present

    # Absent values (None or NaN)
    assert _not_nan_or_none(None) is False
    assert _not_nan_or_none(float("nan")) is False
```

### Tests in `tests/mcp_tools/test_market.py`

This file already imports `get_economic_data` and other `fmp.tools.market` internals. `_fetch_calendar` is a private function that returns a response dict (not a bare list), so tests should go through `get_economic_data` or test `_format_calendar_summary` directly.

**T7: `_fetch_calendar` scrubs NaN from records (via `get_economic_data`)**

```python
def test_get_economic_data_calendar_scrubs_nan(monkeypatch):
    """NaN values in economic calendar DataFrame should become None in response."""
    import pandas as pd
    from fmp.tools.market import get_economic_data

    df = pd.DataFrame([{
        "event": "CPI",
        "date": "2026-04-10",
        "country": "US",
        "impact": "High",
        "estimate": float("nan"),
        "previous": float("nan"),
        "actual": float("nan"),
        "unit": float("nan"),
    }])
    monkeypatch.setattr(
        "fmp.tools.market.FMPClient.fetch",
        lambda self, *a, **kw: df,
    )

    result = get_economic_data(mode="calendar", format="full")

    assert result["status"] == "success"
    rec = result["data"][0]
    assert rec["estimate"] is None
    assert rec["previous"] is None
    assert rec["actual"] is None
    assert rec["unit"] is None
```

**T7b: `_fetch_calendar` scrubs `pd.NaT` from records**

Verifies that `pd.NaT` values (which can appear when pandas parses datetime columns with missing values) are also scrubbed to `None`. This is the key reason for using `pd.isna()` instead of `isinstance(val, float) and math.isnan(val)`.

```python
def test_get_economic_data_calendar_scrubs_nat(monkeypatch):
    """pd.NaT values in economic calendar DataFrame should become None in response."""
    import pandas as pd
    from fmp.tools.market import get_economic_data

    df = pd.DataFrame([{
        "event": "CPI",
        "date": pd.NaT,  # NaT in date column
        "country": "US",
        "impact": "High",
        "estimate": 3.1,
        "previous": float("nan"),
        "actual": pd.NaT,  # NaT in a non-date column (edge case)
        "unit": "%",
    }])
    monkeypatch.setattr(
        "fmp.tools.market.FMPClient.fetch",
        lambda self, *a, **kw: df,
    )

    result = get_economic_data(mode="calendar", format="full")

    assert result["status"] == "success"
    rec = result["data"][0]
    assert rec["date"] is None    # NaT → None
    assert rec["actual"] is None  # NaT → None
    assert rec["previous"] is None  # NaN → None
    assert rec["estimate"] == 3.1  # valid value preserved
    assert rec["unit"] == "%"      # valid value preserved
```

**T8: End-to-end summary path scrubs NaN before `_format_calendar_summary`**

T7 proves the scrub fires for `format="full"`. T8 proves the *same scrub* fires for the `format="summary"` code path — i.e., the NaN-bearing DataFrame goes through `_fetch_calendar()` → scrub → `_format_calendar_summary()` end-to-end. This is important because calling `_format_calendar_summary()` directly with pre-scrubbed records (as a unit test) would not prove the scrub actually runs in the summary path.

```python
def test_get_economic_data_summary_scrubs_nan(monkeypatch):
    """End-to-end: NaN in DataFrame must be scrubbed before reaching _format_calendar_summary."""
    import pandas as pd
    from datetime import date, timedelta
    from fmp.tools.market import get_economic_data

    future = (date.today() + timedelta(days=2)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    df = pd.DataFrame([
        {
            "event": "CPI",
            "date": future,
            "country": "US",
            "impact": "High",
            "estimate": float("nan"),
            "previous": float("nan"),
            "actual": float("nan"),
        },
        {
            "event": "GDP",
            "date": yesterday,
            "country": "US",
            "impact": "High",
            "estimate": 2.5,
            "previous": 2.3,
            "actual": float("nan"),
        },
    ])
    monkeypatch.setattr(
        "fmp.tools.market.FMPClient.fetch",
        lambda self, *a, **kw: df,
    )

    result = get_economic_data(mode="calendar", format="summary")

    assert result["status"] == "success"
    # Note: format="summary" returns summary fields at top level (not under "data")
    # per market.py:472-478 — _format_calendar_summary() returns a dict, then
    # status/mode/period/country are added at the same level.

    # Upcoming event should have None, not NaN (S4a)
    assert len(result["upcoming_high_impact"]) == 1
    upcoming = result["upcoming_high_impact"][0]
    assert upcoming["previous"] is None
    assert upcoming["estimate"] is None
    assert upcoming["actual"] is None

    # GDP had NaN actual → scrubbed to None → `actual is not None` is False
    # → excluded from recent_surprises (S4b: NaN arithmetic path never reached)
    assert len(result["recent_surprises"]) == 0
```

### Tests in `tests/scripts/test_chartbook_events.py` (new file if no existing test file for chartbook)

**T9: `_fmt_numeric` renders `"-"` for None (post-scrub), not `"nan"` for NaN**

This is a unit test for the chartbook rendering path. It verifies that after the upstream scrub converts NaN to None, `_fmt_numeric` correctly renders `"-"` instead of literal `"nan"`.

```python
def test_fmt_numeric_none_renders_dash():
    """_fmt_numeric(None) should render '-', not 'nan'."""
    from scripts.chartbook.charts_events import _fmt_numeric

    assert _fmt_numeric(None) == "-"
    assert _fmt_numeric("") == "-"
    assert _fmt_numeric(3.14) == "3.14"
    assert _fmt_numeric(0) == "0.00"


def test_fmt_numeric_nan_renders_nan_string():
    """_fmt_numeric(float('nan')) renders 'nan' — this is the bug that the upstream scrub prevents.

    This test documents the current behavior of _fmt_numeric: it does NOT guard against NaN
    because it relies on the upstream scrub in _fetch_calendar() to convert NaN to None before
    data reaches the chartbook rendering path. If the upstream scrub is ever removed, this test
    will serve as a canary.
    """
    from scripts.chartbook.charts_events import _fmt_numeric

    result = _fmt_numeric(float("nan"))
    # float('nan') passes _to_float() (it's already a float), then f"{nan:,.2f}" → "nan"
    assert result == "nan"  # Documents the unguarded behavior — upstream scrub prevents this
```

**T10: `_build_economic_table` renders clean HTML with scrubbed (None) values**

End-to-end test: simulates post-scrub calendar response flowing through the chartbook table builder.

```python
def test_build_economic_table_with_scrubbed_values():
    """Economic table should render '-' for None estimate/actual (post-scrub)."""
    from scripts.chartbook.charts_events import _build_economic_table

    response = {
        "data": [
            {
                "event": "CPI",
                "date": "2026-04-10",
                "country": "US",
                "impact": "High",
                "estimate": None,  # scrubbed from NaN
                "actual": None,    # scrubbed from NaN
            },
        ],
    }

    html = _build_economic_table(response)

    assert "nan" not in html.lower()
    assert ">-</td>" in html  # None → "-" via _fmt_numeric
    assert "CPI" in html
```

## Files Changed

| File | Change |
|------|--------|
| `fmp/tools/market.py` | NaN/NaT scrub via `pd.isna()` in `_fetch_calendar()` (~line 453) AND `_safe_fetch_records()` (~line 1105) |
| `mcp_tools/news_events.py` | Add `_not_nan_or_none()` helper (~line 96) as a None/NaN presence check; replace `is not None` guards with `_not_nan_or_none()` calls (lines 774, 776) |
| `tests/mcp_tools/test_news_events_builder.py` | Tests T1-T6 (6 tests) |
| `tests/mcp_tools/test_market.py` | Tests T7, T7b, T8 (3 tests) |
| `tests/scripts/test_chartbook_events.py` | Tests T9, T10 (3 test functions) |

## Scope and Risk

- **~30 lines of production code** across 2 files (3 change sites). Minimal mechanical fix.
- **No behavioral change** for well-formed data — NaN/NaT was never intentional; converting to None matches the existing `_clean_record` convention in `fmp/tools/news_events.py`.
- **No API contract change** — event dicts keep the same keys; `None` replaces `float('nan')` and `pd.NaT`.
- **Existing tests unaffected** — no test currently relies on NaN values passing through.
- **12 tests total** (T1-T10, with T7b as a separate test function and T9 containing 2 test functions): 6 in `test_news_events_builder.py`, 3 in `test_market.py`, 3 in `test_chartbook_events.py`.

## Out of Scope

- **S5 country-filter masking bug**: `_normalize_events()` strips `country` from records, so `e.get("country").upper() == "US"` at line 1418 filters out ALL events. This separate bug means S5's NaN values never reach output today — but the NaN scrub in Change 3 fixes the NaN leak proactively. The country-filter bug itself is a separate fix.
- Auditing all `df.to_dict("records")` calls across the FMP client for NaN leaks (e.g., `fmp/tools/fmp_core.py:159`). Those paths return JSON dicts consumed by AI agents that handle NaN gracefully. A broader audit could be done separately.
- Adding NaN guards to the low-risk secondary sites (S1-S3) — already protected by upstream `_clean_record` or JSON serialization.
- Extracting a shared `_clean_record` utility between `fmp/tools/market.py` and `fmp/tools/news_events.py`. The inline scrub is sufficient for this fix; a shared utility is a separate cleanup task.
