# Expose Full Audit Trail in Realized Performance debug_inference

**Status:** IMPLEMENTED (2026-03-05)

## Context

We're reconciling IBKR realized performance (engine: +6.37% vs statement:
+0.29%). The cash back-solve is implemented and working. To diagnose the
remaining +6.08pp gap (synthetic positions, truncated history, futures MTM),
we need the **full event stream** visible in the `debug_inference` output.

Currently `debug_inference=True` exposes NAV series, flows, and cash anchor
diagnostics — but NOT the raw building blocks: synthetic entries, position
timeline, cash snapshots, FIFO transactions, futures MTM events, or the full
cash replay diagnostics. Without these, every audit session requires ad-hoc
scripts.

**Goal**: Add all raw audit variables to the `_postfilter` dict in engine.py,
then expose them in `_build_inference_diagnostics()` in mcp_tools/performance.py.

**Verified**: `get_performance(mode="realized", source="ibkr_flex", debug_inference=True)`
returns `inference_diagnostics.audit_trail` with all 8 data categories populated.
Used to diagnose and fix the NMM C70/C85 option expiration flag bug.

## Data Inventory

| Variable | Type | Engine line | Currently exposed? |
|----------|------|------------|-------------------|
| `synthetic_entries` | `List[Dict]` | 612 | Count only (2231) |
| `position_timeline` | `Dict[Tuple, List[Tuple]]` | 612 | No |
| `cash_snapshots` | `List[Tuple[dt, float]]` | 1512 | Indirectly via monthly_nav_components |
| `observed_cash_snapshots` | `List[Tuple[dt, float]]` | 1662 | Same |
| `fifo_transactions` | `List[Dict]` | 209-308 | No |
| `futures_mtm_events` | `List[Dict]` | 210-339 | Count only (in cash_replay_diagnostics) |
| `synthetic_twr_flows` | `List[Tuple[dt, float]]` | 1523 | Merged into external_flows |
| `cash_replay_diagnostics` | `Dict[str, Any]` | 1516 | Aggregate counts only |
| `external_flows` | `List[Tuple[dt, float]]` | 1514 | Yes (via _flows_to_dict) |

## Changes

### 1. Add `_serialize_audit_trail()` helper — `engine.py`

Add a new helper function (near top of file, after imports) that builds the
audit dict **only when called**. This avoids serialization cost on every run:

```python
def _serialize_audit_trail(
    synthetic_entries, position_timeline, cash_snapshots,
    observed_cash_snapshots, fifo_transactions, futures_mtm_events,
    synthetic_twr_flows, cash_replay_diagnostics,
):
    """Serialize raw audit variables to JSON-safe dicts. Only called for _postfilter."""

    def _safe_val(v):
        """Convert a single value to JSON-safe form."""
        if v is None:
            return None
        if hasattr(v, "isoformat"):
            return v.isoformat()
        if isinstance(v, float) and (v != v):  # NaN check
            return None
        return v

    def _safe_dict(d, exclude_keys=frozenset()):
        return {k: _safe_val(v) for k, v in d.items() if k not in exclude_keys}

    return {
        "synthetic_entries": [
            {**_safe_dict(entry), "date": _safe_val(entry.get("date"))}
            for entry in (synthetic_entries or [])
        ],
        "position_timeline": {
            f"{ticker}|{ccy}|{direction}": [
                {"date": _safe_val(dt), "quantity": float(qty)}
                for dt, qty in events
            ]
            for (ticker, ccy, direction), events in (position_timeline or {}).items()
        },
        "cash_snapshots": [
            {"date": _safe_val(dt), "cumulative_usd": round(float(val), 2)}
            for dt, val in (cash_snapshots or [])
        ],
        "observed_cash_snapshots": [
            {"date": _safe_val(dt), "cumulative_usd": round(float(val), 2)}
            for dt, val in (observed_cash_snapshots or [])
        ],
        "fifo_transactions": [
            _safe_dict(txn, exclude_keys={"_raw"})
            for txn in (fifo_transactions or [])
        ],
        "futures_mtm_events": [
            _safe_dict(evt)
            for evt in (futures_mtm_events or [])
        ],
        "synthetic_twr_flows": _helpers._flows_to_dict(synthetic_twr_flows or []),
        "cash_replay_diagnostics_full": {
            k: _safe_val(v) if not isinstance(v, (dict, list)) else v
            for k, v in (cash_replay_diagnostics or {}).items()
        },
    }
```

### 2. Add audit trail to `_postfilter` — `engine.py` (~line 2360)

Add inside the existing `_postfilter` dict (before the closing `}`):

```python
"audit_trail": _serialize_audit_trail(
    synthetic_entries, position_timeline, cash_snapshots,
    observed_cash_snapshots, fifo_transactions, futures_mtm_events,
    synthetic_twr_flows, cash_replay_diagnostics,
),
```

**Why `_postfilter`**: This dict is stripped by `to_api_response()` in
`realized_performance.py:655`. Only surfaced when `debug_inference=True`
reads it in mcp_tools/performance.py. `from_dict` preserves it at line 341.

### 3. Thread audit trail through aggregation — `aggregation.py` (~line 1082)

The aggregation path at line 1048 rebuilds `_postfilter` from scratch,
dropping per-account audit data. After the existing `_postfilter` block
(~line 1082), add:

```python
# Merge per-account audit trails into aggregated _postfilter
per_account_audit = {}
for account_id, result in account_items:
    pf = getattr(getattr(result, "realized_metadata", None), "_postfilter", None) or {}
    if "audit_trail" in pf:
        per_account_audit[account_id] = pf["audit_trail"]
if per_account_audit:
    realized_metadata["_postfilter"]["audit_trail_by_account"] = per_account_audit
```

This nests per-account audit data under `audit_trail_by_account.{account_id}`
rather than trying to merge/aggregate raw events.

### 4. Expose in `_build_inference_diagnostics()` — `mcp_tools/performance.py` (~line 293)

Add before the closing `}` of the return dict:

```python
# Full audit trail (single-scope or per-account)
"audit_trail": dict(postfilter.get("audit_trail") or {}),
"audit_trail_by_account": dict(postfilter.get("audit_trail_by_account") or {}),
```

### 5. Serialization safety

The `_safe_val()` helper handles:
- `datetime`/`date` objects → `.isoformat()`
- `NaN` floats → `None` (JSON null)
- `None` → `None` (not `"None"` string)
- `_raw` keys excluded from fifo_transactions via `exclude_keys`

The `_safe_dict()` helper applies `_safe_val()` to all values recursively
for dicts that may contain mixed types.

## Files Modified

| File | Change |
|------|--------|
| `core/realized_performance/engine.py` | `_serialize_audit_trail()` helper + add `audit_trail` to `_postfilter` |
| `core/realized_performance/aggregation.py` | Merge per-account audit trails into `audit_trail_by_account` |
| `mcp_tools/performance.py` | Add `audit_trail` + `audit_trail_by_account` to diagnostics |

## Serialization Notes

- **Datetime handling**: `_safe_val()` converts all datetime/date → `.isoformat()`, NaN → None.
- **Tuple keys**: `(ticker, ccy, direction)` → pipe-delimited string `"AAPL|USD|LONG"`.
- **Reuse**: `_helpers._flows_to_dict()` for `List[Tuple[dt, float]]` → `Dict[str, float]`.
- **Size**: ~30-80KB per account. Debug-only, gated by `_postfilter` stripping.
- **Aggregation**: Per-account data nested under `audit_trail_by_account.{account_id}` — no merge complexity.

## Verification

1. `python3 -m pytest tests/mcp_tools/test_performance.py -v` — no regressions
2. `python3 -m pytest tests/core/test_realized_cash_anchor.py -v` — still pass
3. MCP: `get_performance(mode="realized", source="ibkr_flex", debug_inference=True)`
   - Verify `inference_diagnostics.synthetic_entries` is a non-empty list
   - Verify `inference_diagnostics.position_timeline` has keys like `"AAPL|USD|LONG"`
   - Verify `inference_diagnostics.cash_snapshots` is a list of `{date, cumulative_usd}`
   - Verify `inference_diagnostics.fifo_transactions` is a non-empty list
   - Verify `inference_diagnostics.futures_mtm_events` is a list
   - Verify `inference_diagnostics.synthetic_twr_flows` is a dict
   - Verify `inference_diagnostics.cash_replay_diagnostics_full` has full breakdown keys
4. Normal (non-debug) calls should be unchanged — `_postfilter` is stripped
