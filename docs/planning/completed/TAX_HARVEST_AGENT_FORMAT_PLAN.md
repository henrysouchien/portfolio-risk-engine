# Tax-Loss Harvest Agent Format Plan

_Status: **APPROVED** (Codex R2 PASS)_

## Scope

Add `format="agent"` + `output="file"` to `suggest_tax_loss_harvest()`. Same three-layer pattern. No dedicated result class — tool returns a raw dict. The snapshot and flags operate on this dict directly.

**Problem**: The current `format="summary"` returns 84KB for a real portfolio (79 lots with full per-lot detail, wash sale transaction lists, etc.). This is far too large for agent context. Agent format provides a compact snapshot with the top candidates and actionable flags.

## Layer 1: `_build_tax_harvest_snapshot()` (standalone function in `mcp_tools/tax_harvest.py`)

```python
def _build_tax_harvest_snapshot(result: dict) -> dict:
    """Compact decision-oriented snapshot from tax harvest result dict."""
    import math

    def _safe_float(val, default=0.0):
        if val is None:
            return default
        try:
            f = float(val)
            if f != f or math.isinf(f):
                return default
            return f
        except (TypeError, ValueError):
            return default

    status = result.get("status", "error")

    if status != "success":
        return {
            "status": status,
            "verdict": f"Tax harvest analysis failed: {result.get('error', 'unknown error')}",
            "total_harvestable_loss": 0,
            "short_term_loss": 0,
            "long_term_loss": 0,
            "candidate_count": 0,
            "top_candidates": [],
            "wash_sale_ticker_count": 0,
            "wash_sale_tickers": [],
            "data_coverage_pct": 0,
            "positions_analyzed": 0,
            "positions_with_lots": 0,
        }

    total_loss = _safe_float(result.get("total_harvestable_loss"))
    st_loss = _safe_float(result.get("short_term_loss"))
    lt_loss = _safe_float(result.get("long_term_loss"))
    candidate_count = result.get("candidate_count", 0)
    coverage = _safe_float(result.get("data_coverage_pct"))
    metadata = result.get("metadata", {})
    positions_analyzed = metadata.get("positions_analyzed", 0)
    positions_with_lots = metadata.get("positions_with_lots", 0)

    wash_warnings = result.get("wash_sale_warnings", [])
    wash_tickers = [w.get("ticker", "") for w in wash_warnings]

    # Verdict
    if candidate_count == 0:
        verdict = f"No tax-loss harvesting candidates found ({positions_analyzed} positions analyzed)"
    else:
        abs_loss = abs(total_loss)
        lt_pct = (abs(lt_loss) / abs_loss * 100) if abs_loss > 0 else 0
        verdict = (
            f"${abs_loss:,.0f} harvestable losses across {candidate_count} lots "
            f"({lt_pct:.0f}% long-term), "
            f"{coverage:.0f}% data coverage"
        )
        if wash_tickers:
            verdict += f", wash sale risk on {len(wash_tickers)} ticker{'s' if len(wash_tickers) != 1 else ''}"

    # Top candidates: consolidate by ticker (sum losses, take max lot info)
    candidates = result.get("candidates", [])
    ticker_agg: dict = {}
    for c in candidates:
        ticker = str(c.get("ticker") or "").strip() or "unknown"
        if ticker not in ticker_agg:
            ticker_agg[ticker] = {
                "ticker": ticker,
                "total_loss": 0.0,
                "lot_count": 0,
                "largest_lot_loss": 0.0,
                "wash_sale_risk": False,
                "holding_periods": set(),
            }
        agg = ticker_agg[ticker]
        lot_loss = _safe_float(c.get("unrealized_loss"))
        agg["total_loss"] += lot_loss
        agg["lot_count"] += 1
        if abs(lot_loss) > abs(agg["largest_lot_loss"]):
            agg["largest_lot_loss"] = lot_loss
        if c.get("wash_sale_risk"):
            agg["wash_sale_risk"] = True
        hp = c.get("holding_period", "unknown")
        agg["holding_periods"].add(hp)

    top_candidates = []
    for agg in sorted(ticker_agg.values(), key=lambda a: abs(a["total_loss"]), reverse=True)[:5]:
        periods = sorted(agg["holding_periods"])
        top_candidates.append({
            "ticker": agg["ticker"],
            "total_loss": round(agg["total_loss"], 2),
            "lot_count": agg["lot_count"],
            "holding_periods": periods,
            "wash_sale_risk": agg["wash_sale_risk"],
        })

    return {
        "status": status,
        "verdict": verdict,
        "total_harvestable_loss": round(total_loss, 2),
        "short_term_loss": round(st_loss, 2),
        "long_term_loss": round(lt_loss, 2),
        "candidate_count": candidate_count,
        "top_candidates": top_candidates,
        "wash_sale_ticker_count": len(wash_tickers),
        "wash_sale_tickers": wash_tickers[:5],
        "data_coverage_pct": round(coverage, 1),
        "positions_analyzed": positions_analyzed,
        "positions_with_lots": positions_with_lots,
    }
```

**Key design**: Candidates are **consolidated by ticker** in the snapshot (sum losses across lots for the same ticker, count lots). The full per-lot detail is in the file output. This is the main size reduction — 79 lots → 5 ticker summaries.

## Layer 2: `core/tax_harvest_flags.py`

```python
def generate_tax_harvest_flags(snapshot: dict) -> list[dict]:
    """Generate severity-tagged flags from tax harvest snapshot."""
    flags = []

    status = snapshot.get("status", "error")
    if status != "success":
        flags.append({
            "flag": "harvest_error",
            "severity": "error",
            "message": snapshot.get("verdict", "Tax harvest analysis failed"),
        })
        return _sort_flags(flags)

    candidate_count = snapshot.get("candidate_count", 0)
    total_loss = snapshot.get("total_harvestable_loss", 0)
    st_loss = snapshot.get("short_term_loss", 0)
    coverage = snapshot.get("data_coverage_pct", 0)
    wash_count = snapshot.get("wash_sale_ticker_count", 0)
    positions_analyzed = snapshot.get("positions_analyzed", 0)
    positions_with_lots = snapshot.get("positions_with_lots", 0)

    # No candidates
    if candidate_count == 0:
        flags.append({
            "flag": "no_candidates",
            "severity": "success",
            "message": "No unrealized losses to harvest — all lots are at a gain or break-even",
        })
        return _sort_flags(flags)

    # Significant harvesting opportunity (> $3,000 = annual deduction limit)
    abs_loss = abs(total_loss)
    if abs_loss >= 3000:
        flags.append({
            "flag": "significant_harvest",
            "severity": "info",
            "message": f"${abs_loss:,.0f} harvestable losses exceed $3,000 annual deduction limit",
        })

    # Short-term losses are more valuable (taxed at ordinary income rates)
    abs_st = abs(st_loss)
    if abs_st > 0 and abs_loss > 0:
        st_pct = abs_st / abs_loss * 100
        if st_pct >= 50:
            flags.append({
                "flag": "mostly_short_term",
                "severity": "info",
                "message": f"{st_pct:.0f}% of losses are short-term (higher tax offset value)",
            })

    # Wash sale risk
    if wash_count > 0:
        tickers = snapshot.get("wash_sale_tickers", [])
        ticker_str = ", ".join(tickers[:3])
        suffix = f" + {wash_count - 3} more" if wash_count > 3 else ""
        flags.append({
            "flag": "wash_sale_risk",
            "severity": "warning",
            "message": f"Wash sale risk on {wash_count} ticker{'s' if wash_count != 1 else ''}: {ticker_str}{suffix}",
        })

    # Low data coverage
    if coverage < 50:
        flags.append({
            "flag": "low_coverage",
            "severity": "warning",
            "message": f"Only {coverage:.0f}% of positions have FIFO lot data — losses may be understated",
        })
    elif coverage < 75:
        flags.append({
            "flag": "moderate_coverage",
            "severity": "info",
            "message": f"{coverage:.0f}% lot coverage — {positions_analyzed - positions_with_lots} positions missing transaction history",
        })

    # Clean if no flags yet
    if not flags:
        flags.append({
            "flag": "harvest_available",
            "severity": "info",
            "message": f"${abs_loss:,.0f} in harvestable losses across {candidate_count} lots",
        })

    return _sort_flags(flags)


def _sort_flags(flags):
    order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    return sorted(flags, key=lambda f: order.get(f.get("severity", "info"), 2))
```

**Flag summary:**

| Flag | Severity | Condition |
|------|----------|-----------|
| `harvest_error` | error | `status != "success"` |
| `wash_sale_risk` | warning | wash_sale_ticker_count > 0 |
| `low_coverage` | warning | data_coverage_pct < 50 |
| `moderate_coverage` | info | 50 <= data_coverage_pct < 75 |
| `significant_harvest` | info | abs(total_loss) >= $3,000 |
| `mostly_short_term` | info | short-term >= 50% of total losses |
| `harvest_available` | info | Candidates exist, no other flags |
| `no_candidates` | success | candidate_count == 0 |

## Layer 3: MCP Composition in `mcp_tools/tax_harvest.py`

### Helpers

```python
_TAX_HARVEST_OUTPUT_DIR = Path("logs/tax_harvest")

def _save_full_tax_harvest(result):
    """Save full tax harvest results to disk and return absolute path, or None on failure."""
    import json

    _TAX_HARVEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = _TAX_HARVEST_OUTPUT_DIR / f"tax_harvest_{timestamp}.json"

    try:
        with file_path.open("w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, default=str)
        return str(file_path.resolve())
    except Exception:
        return None


def _build_tax_harvest_agent_response(result, file_path=None):
    """Compose decision-oriented tax harvest result for agent use."""
    from core.tax_harvest_flags import generate_tax_harvest_flags

    snapshot = _build_tax_harvest_snapshot(result)
    flags = generate_tax_harvest_flags(snapshot)

    response_status = "success" if result.get("status") == "success" else "error"

    return {
        "status": response_status,
        "format": "agent",
        "snapshot": snapshot,
        "flags": flags,
        "file_path": file_path,
    }
```

### Modified `suggest_tax_loss_harvest()` function

- Add `"agent"` to format Literal: `Literal["full", "summary", "report", "agent"]`
- Add `output: Literal["inline", "file"] = "inline"` parameter
- After building the `response` dict (before format dispatch), add file save:
  ```python
  file_path = _save_full_tax_harvest(response) if output == "file" else None
  ```
- Add agent format branch **before** the existing format dispatch:
  ```python
  if format == "agent":
      return _build_tax_harvest_agent_response(response, file_path=file_path)
  ```
- For existing summary/full/report branches, propagate `file_path` if set
- **Error handling**: The except block must also handle agent format:
  ```python
  except Exception as e:
      error_result = {"status": "error", "error": str(e)}
      if format == "agent":
          return _build_tax_harvest_agent_response(error_result, file_path=None)
      return error_result
  ```

### `mcp_server.py` changes

- Add `"agent"` to format Literal for `suggest_tax_loss_harvest`
- Add `output` parameter
- Pass through

## Test Plan

### `tests/mcp_tools/test_tax_harvest_agent_snapshot.py`

1. **test_snapshot_success** — Valid harvest → verdict has dollar amount, lot count, coverage
2. **test_snapshot_no_candidates** — candidate_count=0 → verdict "No tax-loss harvesting candidates"
3. **test_snapshot_error** — status="error" → verdict mentions failure, consistent keys with success path
4. **test_snapshot_ticker_consolidation** — 5 lots for 2 tickers → 2 entries in top_candidates with summed losses
5. **test_snapshot_top_candidates_capped** — 10 tickers → 5 in top_candidates
6. **test_snapshot_wash_sale_in_verdict** — wash_sale_warnings present → verdict mentions wash sale risk
7. **test_snapshot_safe_float** — None/NaN/inf → default 0.0
8. **test_snapshot_error_key_consistency** — Error snapshot has same top-level keys as success snapshot
9. **test_snapshot_holding_periods** — Mixed ST/LT lots for same ticker → both periods in holding_periods list
10. **test_snapshot_ticker_normalization** — Candidate with None/empty ticker → consolidated under "unknown"

### `tests/core/test_tax_harvest_flags.py`

10. **test_harvest_error_flag** — status != "success" → "harvest_error" error
11. **test_no_candidates_flag** — candidate_count=0 → "no_candidates" success, early return
12. **test_significant_harvest_flag** — abs(total_loss) >= 3000 → "significant_harvest" info
13. **test_below_significant_threshold** — abs(total_loss) = 2000 → no "significant_harvest" flag
14. **test_mostly_short_term_flag** — st_loss >= 50% of total → "mostly_short_term" info
15. **test_wash_sale_risk_flag** — wash_sale_ticker_count=2 → "wash_sale_risk" warning with ticker names
16. **test_low_coverage_flag** — coverage < 50 → "low_coverage" warning
17. **test_moderate_coverage_flag** — 50 <= coverage < 75 → "moderate_coverage" info
18. **test_good_coverage_no_flag** — coverage >= 75 → no coverage flag
19. **test_harvest_available_fallback** — Candidates exist, no other flags trigger → "harvest_available" info
20. **test_flag_sort_order** — error before warning before info before success
21. **test_boundary_3000** — abs(total_loss) exactly 3000 → "significant_harvest" info
22. **test_boundary_coverage_50** — coverage exactly 50 → no "low_coverage" (uses < 50), gets "moderate_coverage"
23. **test_boundary_coverage_75** — coverage exactly 75 → no "moderate_coverage" (uses < 75)
24. **test_boundary_st_50pct** — short-term exactly 50% → "mostly_short_term" info

### `tests/mcp_tools/test_tax_harvest_agent_format.py`

25. **test_agent_response_structure** — Has status, format, snapshot, flags, file_path
26. **test_file_output_agent** — output="file" creates file, file_path set
27. **test_inline_no_file_path** — output="inline" → file_path is None
28. **test_file_output_report** — format="report", output="file" → file_path in response
29. **test_file_output_full** — format="full", output="file" → file_path in response
30. **test_agent_error_propagation** — Error result → response status="error", flags has "harvest_error"
31. **test_file_save_returns_none_on_failure** — Mock write failure → file_path is None
32. **test_agent_early_return_no_transactions** — No transaction history → agent format still returns proper snapshot/flags (exercises early-return branch at line 694)
33. **test_agent_early_return_no_open_lots** — Transactions exist but no open lots → agent format returns proper snapshot/flags (exercises early-return branch at line 726)

## Implementation Notes

- The current `suggest_tax_loss_harvest()` has **two early-return branches** (no transactions at line 694, no open lots at line 726) that return before the main format dispatch. These must be updated to check `format == "agent"` and route through `_build_tax_harvest_agent_response()`, and `output == "file"` for file save.
- Existing MCP contract tests in `tests/unit/test_mcp_server_contracts.py` should be extended to cover the new `"agent"` format literal and `output` parameter.

## Decisions

1. **Ticker consolidation in snapshot**: The biggest size reduction. 79 individual lots → ~10 unique tickers → top 5 shown. Per-lot detail lives in the file output. This is the key difference from other agent formats — most tools don't have this many repeated entries for the same ticker.
2. **$3,000 threshold**: The IRS annual capital loss deduction limit. Losses above this are meaningful for tax planning.
3. **Short-term flag at 50%**: Short-term losses offset ordinary income (higher tax rate), so they're more valuable. Flagging when they're the majority.
4. **Coverage thresholds**: < 50% warning, 50-75% info, >= 75% no flag. Matches the tool's real-world behavior (54% for this portfolio).
5. **Wash sale tickers capped at 5**: In snapshot for agent readability. Full list in file.
6. **File save returns None on failure**: Consistent with income projection pattern.
7. **Error path wired to agent format**: Exception handler checks format and routes through `_build_tax_harvest_agent_response()`.
8. **Error snapshot key consistency**: Error path returns same top-level keys as success path.
