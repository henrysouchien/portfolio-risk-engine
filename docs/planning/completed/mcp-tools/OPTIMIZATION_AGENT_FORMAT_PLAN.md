# Plan: Agent-Optimized Portfolio Optimization Output

_Created: 2026-02-24_
_Status: **COMPLETE** (7 Codex review rounds, 51 new tests, live-tested)_
_Reference: `STOCK_ANALYSIS_AGENT_FORMAT_PLAN.md`, `TRADING_ANALYSIS_AGENT_FORMAT_PLAN.md` (same three-layer pattern)_

## Context

`run_optimization` finds optimal portfolio weights (min variance or max return) subject to risk limits and factor constraints using QP solvers. The current `format="summary"` returns weights and top changes but no interpretation. The agent can't answer "is this optimization worth executing?" or "how much does risk improve?"

The MCP agent audit grades this tool **B-** — has weight changes and top positions but no interpretation. Improvement assessment and trade cost estimation are out of scope for this phase (requires original portfolio metrics for comparison).

Goal: Apply the same `format="agent"` + `output="file"` pattern.

## Current State

### Output formats

| Format | Size | What agent gets |
|--------|------|-----------------|
| `summary` | ~2-4KB | optimization_type, total_positions, largest/smallest_position, portfolio_metrics (max_return only), top_positions (10), weight_changes (5). No interpretation. |
| `full` | ~10-30KB | Everything: all weights, risk_table, beta_table, factor_table, proxy_table, risk_analysis, beta_analysis, formatted_report. Way too much. |
| `report` | ~3-8KB | Human-readable CLI text. Good for display, not for agent reasoning. |

### What the agent actually needs

1. **Verdict** — Is this optimization worth executing? One phrase.
2. **Key metrics** — Number of positions, number of trades, concentration (largest/HHI).
3. **Compliance status** — All risk checks pass? Factor checks pass? Any violations?
4. **Top weight changes** — What needs to change and by how much.
5. **Portfolio metrics** — Optimized portfolio volatility and concentration (max_return only).
6. **Flags** — Many trades required, concentration risk, violations, clean rebalance.

### What the agent does NOT need in-context

- Full optimized_weights dict (can be 20-50 entries)
- Risk table DataFrame rows
- Beta table DataFrame rows
- Factor table, proxy table
- Legacy column-oriented table format
- Risk limits configuration details
- Formatted CLI report

These belong in the file output for deep dives.

## Proposed Design

### Layer 1: Data accessor (on `OptimizationResult` in `core/result_objects.py`)

New `get_agent_snapshot()` method.

```python
def get_agent_snapshot(self, original_weights: dict | None = None) -> dict:
    """Compact metrics for agent consumption."""
    # Position counts
    active_positions = {k: v for k, v in self.optimized_weights.items() if abs(v) > 0.001}
    total_positions = len(active_positions)

    # Concentration (abs for short positions)
    weights_list = list(active_positions.values())
    largest_weight = max(abs(w) for w in weights_list) if weights_list else 0
    hhi = sum(w ** 2 for w in weights_list) if weights_list else 0

    # Trade count (positions that change significantly)
    trades_required = 0
    if original_weights:
        all_tickers = set(list(original_weights.keys()) + list(self.optimized_weights.keys()))
        for ticker in all_tickers:
            orig = original_weights.get(ticker, 0)
            new = self.optimized_weights.get(ticker, 0)
            if abs(new - orig) >= 0.005:  # >= 50bps change = a trade
                trades_required += 1

    # Compliance (None = checks not available, True/False = checked)
    has_risk_checks = not self.risk_table.empty and "Pass" in self.risk_table.columns
    has_factor_checks = not self.beta_table.empty and "pass" in self.beta_table.columns
    has_proxy_checks = not self.proxy_table.empty and "pass" in self.proxy_table.columns

    risk_passes = bool(self.risk_table["Pass"].all()) if has_risk_checks else None
    risk_violation_count = int((~self.risk_table["Pass"]).sum()) if has_risk_checks else 0

    factor_passes = bool(self.beta_table["pass"].all()) if has_factor_checks else None
    factor_violation_count = int((~self.beta_table["pass"]).sum()) if has_factor_checks else 0

    proxy_passes = bool(self.proxy_table["pass"].all()) if has_proxy_checks else None
    proxy_violation_count = int((~self.proxy_table["pass"]).sum()) if has_proxy_checks else 0

    # Weight changes (top 5, filtered to >= 50bps using same raw threshold as trade count)
    weight_changes = []
    if original_weights:
        raw_changes = self.get_weight_changes(original_weights, limit=20)
        # Re-check against raw delta to match trade count threshold exactly
        filtered = []
        for c in raw_changes:
            orig = original_weights.get(c["ticker"], 0)
            new = self.optimized_weights.get(c["ticker"], 0)
            if abs(new - orig) >= 0.005:
                filtered.append(c)
        weight_changes = filtered[:5]

    # Top positions (top 5)
    top_positions = self.get_top_positions(5)

    # Portfolio metrics (max_return only)
    portfolio_metrics = None
    if self.portfolio_summary:
        portfolio_metrics = {
            "volatility_annual_pct": round(self.portfolio_summary.get("volatility_annual", 0) * 100, 2),
            "volatility_monthly_pct": round(self.portfolio_summary.get("volatility_monthly", 0) * 100, 2),
            "herfindahl": round(self.portfolio_summary.get("herfindahl", 0), 4),
        }

    # Verdict (violations override trade-based verdict)
    compliance_known = (risk_passes is not None or factor_passes is not None
                        or proxy_passes is not None)
    if risk_violation_count > 0 or factor_violation_count > 0 or proxy_violation_count > 0:
        verdict = "has violations"
    elif not original_weights:
        verdict = "baseline unavailable"
    elif trades_required == 0 and compliance_known:
        verdict = "already optimal"
    elif trades_required == 0:
        verdict = "no changes needed"
    elif trades_required <= 3:
        verdict = "minor rebalance"
    elif trades_required <= 10:
        verdict = "moderate rebalance"
    else:
        verdict = "major rebalance"

    snapshot = {
        "verdict": verdict,
        "optimization_type": self.optimization_type,
        "positions": {
            "total": total_positions,
            "largest_weight_pct": round(largest_weight * 100, 2),
            "hhi": round(hhi, 4),
        },
        "trades_required": trades_required,
        "compliance": {
            "risk_passes": risk_passes,
            "risk_violation_count": risk_violation_count,
            "factor_passes": factor_passes,
            "factor_violation_count": factor_violation_count,
            "proxy_passes": proxy_passes,
            "proxy_violation_count": proxy_violation_count,
        },
        "top_positions": {k: round(v * 100, 2) for k, v in top_positions.items()},
        "weight_changes": weight_changes,
    }

    if portfolio_metrics is not None:
        snapshot["portfolio_metrics"] = portfolio_metrics

    return snapshot
```

### Layer 2: Flag rules (new — `core/optimization_flags.py`)

```python
def generate_optimization_flags(snapshot: dict) -> list[dict]:
    """
    Generate actionable flags from optimization snapshot.

    Input: dict from OptimizationResult.get_agent_snapshot()
    """
    if not snapshot:
        return []

    flags = []
    positions = snapshot.get("positions", {})
    compliance = snapshot.get("compliance", {})
    changes = snapshot.get("weight_changes", [])
    trades = snapshot.get("trades_required", 0)
    metrics = snapshot.get("portfolio_metrics")

    # --- Compliance flags ---

    risk_violations = compliance.get("risk_violation_count", 0)
    if risk_violations > 0:
        flags.append({
            "type": "risk_violations",
            "severity": "warning",
            "message": f"{risk_violations} risk limit violation(s) in optimized portfolio",
            "risk_violation_count": risk_violations,
        })

    factor_violations = compliance.get("factor_violation_count", 0)
    if factor_violations > 0:
        flags.append({
            "type": "factor_violations",
            "severity": "warning",
            "message": f"{factor_violations} factor beta violation(s) in optimized portfolio",
            "factor_violation_count": factor_violations,
        })

    proxy_violations = compliance.get("proxy_violation_count", 0)
    if proxy_violations > 0:
        flags.append({
            "type": "proxy_violations",
            "severity": "warning",
            "message": f"{proxy_violations} proxy constraint violation(s) in optimized portfolio",
            "proxy_violation_count": proxy_violations,
        })

    # --- Trade complexity flags ---

    if trades > 15:
        flags.append({
            "type": "many_trades",
            "severity": "info",
            "message": f"Optimization requires {trades} trades — significant rebalancing effort",
            "trades_required": trades,
        })

    total_violations = (compliance.get("risk_violation_count", 0)
                        + compliance.get("factor_violation_count", 0)
                        + compliance.get("proxy_violation_count", 0))
    # Only flag as "already optimal" when compliance is known-good (not None/unknown)
    compliance_known = (compliance.get("risk_passes") is not None
                        or compliance.get("factor_passes") is not None
                        or compliance.get("proxy_passes") is not None)
    if trades == 0 and total_violations == 0 and compliance_known:
        flags.append({
            "type": "already_optimal",
            "severity": "success",
            "message": "Portfolio is already at or near optimal allocation",
        })

    # --- Concentration flags ---

    largest = positions.get("largest_weight_pct", 0)
    if largest > 30:
        flags.append({
            "type": "concentrated_position",
            "severity": "warning",
            "message": f"Largest position is {largest:.1f}% of optimized portfolio",
            "largest_weight_pct": largest,
        })

    hhi = positions.get("hhi", 0)
    if hhi > 0.15:
        flags.append({
            "type": "high_concentration",
            "severity": "info",
            "message": f"Portfolio concentration is high (HHI: {hhi:.3f})",
            "hhi": hhi,
        })

    # --- Weight change flags ---

    if changes:
        biggest = changes[0]  # already sorted by abs(change)
        change_bps = biggest.get("change_bps", 0)
        if abs(change_bps) > 1000:
            flags.append({
                "type": "large_single_change",
                "severity": "info",
                "message": f"Largest change: {biggest['ticker']} moves {change_bps:+d} bps ({biggest.get('original_weight', 0)*100:.1f}% → {biggest.get('new_weight', 0)*100:.1f}%)",
                "ticker": biggest["ticker"],
                "change_bps": change_bps,
            })

    # --- Position count flags ---

    total = positions.get("total", 0)
    if 0 < total <= 3:
        flags.append({
            "type": "few_positions",
            "severity": "info",
            "message": f"Optimized portfolio has only {total} positions — low diversification",
            "total_positions": total,
        })

    # --- Positive signals ---

    if (compliance.get("risk_passes") is True
            and compliance.get("factor_passes") is True
            and compliance.get("proxy_passes") is not False
            and 0 < trades <= 5):
        flags.append({
            "type": "clean_rebalance",
            "severity": "success",
            "message": f"All checked constraints satisfied with only {trades} trades needed",
            "trades_required": trades,
        })

    # Sort: warnings first, then info, then success
    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda f: severity_order.get(f.get("severity"), 9))

    return flags
```

### Threshold constants

| Rule | Threshold | Rationale |
|------|-----------|-----------|
| Risk violations | > 0 violations | Optimized portfolio doesn't meet constraints |
| Factor violations | > 0 violations | Factor betas exceed limits |
| Proxy violations | > 0 violations | Proxy constraints not met |
| Many trades | > 15 trades | Significant rebalancing effort |
| Already optimal | 0 trades + 0 violations + compliance known | Nothing to do |
| Concentrated position | > 30% single weight (warning) | High single-name risk |
| High concentration | HHI > 0.15 | Portfolio-level concentration |
| Large single change | > 1000 bps (10%) | Most disruptive single rebalance |
| Few positions | <= 3 positions | Low diversification |
| Clean rebalance | risk+factor pass (explicit True), proxy not False, 1-5 trades | Easy, clean optimization |

### Layer 3: Agent format composer (in `mcp_tools/optimization.py`)

```python
from core.result_objects import OptimizationResult

_OPTIMIZATION_OUTPUT_DIR = Path("logs/optimization")


def _build_agent_response(
    result: OptimizationResult,
    original_weights: dict,
    file_path: str | None = None,
) -> dict:
    """Compose decision-oriented optimization result for agent use."""
    from core.optimization_flags import generate_optimization_flags

    snapshot = result.get_agent_snapshot(original_weights)
    flags = generate_optimization_flags(snapshot)

    return {
        "status": "success",
        "format": "agent",
        "snapshot": snapshot,
        "flags": flags,
        "file_path": file_path,
    }
```

### File output

When `output="file"`:

1. Run optimization as normal
2. Write full payload to `logs/optimization/opt_{type}_{YYYYMMDD}_{HHMMSS}.json`
3. Attach `file_path` to whatever format response is returned

```python
def _save_full_optimization(result: OptimizationResult, opt_type: str) -> str:
    """Save full optimization data to disk and return absolute path."""
    output_dir = _OPTIMIZATION_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    file_path = output_dir / f"opt_{opt_type}_{timestamp}.json"

    try:
        payload = result.to_api_response()
    except Exception:
        # Fallback if tables lack expected columns
        payload = {"optimized_weights": result.optimized_weights, "optimization_type": result.optimization_type}
    payload["status"] = "success"

    with file_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    return str(file_path.resolve())
```

## Files to Modify

### 1. Modify: `core/result_objects.py`

**Add `get_agent_snapshot(original_weights)` to `OptimizationResult`:**
- Returns compact dict: verdict, optimization_type, positions, trades_required, compliance, top_positions, weight_changes, portfolio_metrics (optional)
- Accepts `original_weights` to compute trade count and weight changes
- Verdict derived from violations + trade count
- Portfolio metrics only for max_return (from portfolio_summary)
- Weights converted to percentages in top_positions
- Uses existing `get_weight_changes()` and `get_top_positions()`

### 2. New: `core/optimization_flags.py`

- `generate_optimization_flags(snapshot) -> list[dict]`
- All flag rules from the threshold table
- Accepts snapshot dict (decoupled from result object)
- No minimum count gates (optimization always has data)
- Sorted by severity

### 3. Modify: `mcp_tools/optimization.py`

**Add `_build_agent_response(result, original_weights, file_path)`:**
- Passes `original_weights` to `get_agent_snapshot()`
- Calls `generate_optimization_flags()` from `core/optimization_flags.py`

**Add `_save_full_optimization(result, opt_type)`:**
- Writes `to_api_response()` to `_OPTIMIZATION_OUTPUT_DIR`

**Update `run_optimization()` signature:**
- Add `format="agent"` to the Literal enum
- Add `output: Literal["inline", "file"] = "inline"` parameter
- File write happens BEFORE format dispatch
- Pass `original_weights` from `optimization_metadata` to agent builder
- Wrap `format="full"` dispatch `to_api_response()` in try/except with same minimal fallback payload as file save

### 4. Modify: `mcp_server.py`

- Add "agent" to the format enum for run_optimization
- Add output parameter
- Pass through to underlying function

## Agent format example output

```json
{
  "status": "success",
  "format": "agent",

  "snapshot": {
    "verdict": "moderate rebalance",
    "optimization_type": "min_variance",
    "positions": {
      "total": 12,
      "largest_weight_pct": 18.50,
      "hhi": 0.0920
    },
    "trades_required": 7,
    "compliance": {
      "risk_passes": true,
      "risk_violation_count": 0,
      "factor_passes": true,
      "factor_violation_count": 0,
      "proxy_passes": null,
      "proxy_violation_count": 0
    },
    "top_positions": {
      "SGOV": 18.50,
      "AAPL": 12.30,
      "MSFT": 10.80,
      "GOOGL": 9.50,
      "BND": 8.20
    },
    "weight_changes": [
      {"ticker": "SGOV", "original_weight": 0.05, "new_weight": 0.185, "change": 0.135, "change_bps": 1350},
      {"ticker": "TSLA", "original_weight": 0.15, "new_weight": 0.03, "change": -0.12, "change_bps": -1200},
      {"ticker": "AAPL", "original_weight": 0.20, "new_weight": 0.123, "change": -0.077, "change_bps": -770}
    ]
  },

  "flags": [
    {
      "type": "large_single_change",
      "severity": "info",
      "message": "Largest change: SGOV moves +1350 bps (5.0% → 18.5%)",
      "ticker": "SGOV",
      "change_bps": 1350
    }
  ],

  "file_path": null
}
```

### What each section answers for the agent:

| Section | Agent question |
|---------|---------------|
| `snapshot.verdict` | "Should I rebalance?" |
| `snapshot.optimization_type` | "What was the objective?" |
| `snapshot.positions` | "How many positions and how concentrated?" |
| `snapshot.trades_required` | "How many trades needed?" |
| `snapshot.compliance` | "Does this meet all constraints?" |
| `snapshot.top_positions` | "What are the biggest allocations?" |
| `snapshot.weight_changes` | "What are the biggest changes?" |
| `snapshot.portfolio_metrics` | "What's the expected portfolio risk?" (max_return only) |
| `flags` | "What deserves attention?" |
| `file_path` | "Where's the full optimization for deep dives?" |

## Compatibility

- All existing formats (`full`, `summary`, `report`) unchanged
- `format="agent"` is purely additive
- `output="file"` works with any format
- Default format stays `"summary"` (no breaking change)
- `output` defaults to `"inline"` (no breaking change)

## Decisions

1. **Snapshot nested under `"snapshot"` key.** Consistent with all other agent formats.
2. **`get_agent_snapshot()` accepts `original_weights`.** Trade count and weight changes require the original weights. These come from `optimization_metadata["original_weights"]` (set during optimization).
3. **Flags take the snapshot dict.** Same decoupled pattern.
4. **Trade threshold: >= 50bps change counts as a trade.** 0.5% weight change is the minimum to constitute a meaningful rebalance action. Both trade counting and weight_changes filtering use the same >= 50bps boundary.
5. **Verdict is action-oriented.** "already optimal" / "no changes needed" / "minor rebalance" / "moderate rebalance" / "major rebalance" / "has violations" / "baseline unavailable". "already optimal" requires compliance known; "no changes needed" is 0 trades but compliance unknown.
6. **Portfolio metrics only for max_return.** min_variance doesn't have portfolio_summary (no performance metrics). Section is conditional.
7. **Weights in top_positions as percentages.** Converted from decimal (0.185) to percent (18.50) for readability.
8. **Weight changes use existing getter then re-filter.** Reuses `get_weight_changes()` for formatting (change_bps, rounding), then re-checks against raw float threshold for consistency with trade counting.
9. **`_OPTIMIZATION_OUTPUT_DIR` module constant.** Testable via `monkeypatch`.
10. **Compliance uses DataFrame boolean columns.** `risk_table["Pass"]` and `beta_table["pass"]` — note different capitalization (legacy issue). Guards with `.empty` and column existence checks.
11. **Empty compliance tables → None (not True).** When risk/beta tables are empty or missing expected columns, `risk_passes` and `factor_passes` are None (unknown), not True. This prevents falsely reporting compliance when checks weren't available.
12. **Weight changes filtered using same raw threshold as trade count.** Both trade counting and weight_changes filtering recompute `abs(new - orig) >= 0.005` from raw float values (not from rounded `change` or `change_bps` fields). This ensures exact consistency at the 50bps boundary.
13. **Concentrated position is warning.** Consistent with `core/position_flags.py` which treats concentration as warning severity. > 30% single position is a significant risk.
14. **File save has fallback.** If `to_api_response()` fails (e.g., tables lack expected columns), falls back to minimal weights-only payload.
15. **`baseline unavailable` verdict when no original_weights.** Without original weights, trade count is meaningless (0 by default). Verdict becomes "baseline unavailable" to prevent false "already optimal". The agent should still get the optimized weights and compliance but knows trade count is not meaningful.
16. **`format="full"` uses same fallback pattern.** The full format dispatch wraps `to_api_response()` in try/except with the same minimal weights-only fallback as file save. In both cases the fallback payload is `{"optimized_weights": ..., "optimization_type": ..., "status": "success"}`.

## Test Plan

### `core/result_objects.py` — get_agent_snapshot tests

- `test_agent_snapshot_keys` — all expected top-level keys present (verdict, optimization_type, positions, trades_required, compliance, top_positions, weight_changes)
- `test_agent_snapshot_verdict_already_optimal` — 0 trades → "already optimal"
- `test_agent_snapshot_verdict_minor_rebalance` — 2 trades → "minor rebalance"
- `test_agent_snapshot_verdict_moderate_rebalance` — 7 trades → "moderate rebalance"
- `test_agent_snapshot_verdict_major_rebalance` — 20 trades → "major rebalance"
- `test_agent_snapshot_verdict_has_violations` — risk violation present → "has violations"
- `test_agent_snapshot_trades_required_count` — counts positions with >= 50bps change
- `test_agent_snapshot_top_positions_as_pct` — weights converted to percentages
- `test_agent_snapshot_portfolio_metrics_present` — max_return has portfolio_metrics
- `test_agent_snapshot_portfolio_metrics_absent` — min_variance has no portfolio_metrics
- `test_agent_snapshot_no_original_weights_none` — None original_weights → 0 trades, empty changes, verdict "baseline unavailable"
- `test_agent_snapshot_no_original_weights_empty_dict` — empty dict `{}` → same as None: verdict "baseline unavailable"
- `test_agent_snapshot_short_position_concentration` — large short weight triggers correct largest_weight_pct (uses abs)
- `test_agent_snapshot_compliance_all_pass` — all checks pass
- `test_agent_snapshot_compliance_with_violations` — counts violations correctly
- `test_agent_snapshot_compliance_includes_proxy` — proxy_passes and proxy_violation_count in compliance
- `test_agent_snapshot_verdict_proxy_violations` — proxy violation → "has violations"
- `test_agent_snapshot_verdict_no_changes_unknown_compliance` — 0 trades + compliance unknown → "no changes needed"

### `core/optimization_flags.py` tests

- `test_risk_violations_flag` — violations > 0 triggers warning
- `test_factor_violations_flag` — factor violations > 0 triggers warning
- `test_many_trades_flag` — > 15 trades triggers info
- `test_already_optimal_flag` — 0 trades + 0 violations + compliance known → success
- `test_already_optimal_suppressed_with_violations` — 0 trades but violations exist → no already_optimal flag
- `test_already_optimal_suppressed_unknown_compliance` — 0 trades + 0 violations but all compliance None → no already_optimal flag
- `test_already_optimal_with_proxy_only_compliance_known` — proxy_passes not None but risk/factor None → already_optimal fires
- `test_concentrated_position_flag` — > 30% largest weight triggers warning
- `test_high_concentration_flag` — HHI > 0.15 triggers info
- `test_large_single_change_flag` — > 1000 bps change triggers info
- `test_few_positions_flag` — <= 3 positions triggers info
- `test_clean_rebalance_flag` — all pass + <= 5 trades triggers success
- `test_proxy_violations_flag` — proxy violations > 0 triggers warning
- `test_flags_sorted_by_severity` — warnings before info before success
- `test_empty_snapshot_no_crash` — empty dict produces no flags

### `mcp_tools/optimization.py` agent format tests

- `test_agent_format_structure` — top-level keys: status, format, snapshot, flags, file_path
- `test_agent_format_calls_getter` — verify delegation to get_agent_snapshot()
- `test_agent_format_passes_original_weights` — original_weights passed to getter
- `test_agent_format_has_flags` — flags list present
- `test_agent_format_snapshot_nested` — snapshot is nested dict

### File output tests

- `test_file_output_creates_file` — file written to logs/optimization/
- `test_file_output_includes_type_in_filename` — filename contains optimization type
- `test_file_output_returns_file_path` — file_path is valid path
- `test_inline_output_no_file` — output="inline" does not create file
- `test_file_output_attaches_path_to_summary` — format="summary" + output="file" includes file_path
- `test_file_output_attaches_path_to_report` — format="report" + output="file" includes file_path
- `test_file_output_attaches_path_to_agent` — format="agent" + output="file" includes file_path
- `test_file_output_attaches_path_to_full` — format="full" + output="file" includes file_path
- `test_exact_50bps_boundary` — exactly 50bps change counted as trade and included in weight_changes
- `test_full_format_fallback_on_error` — format="full" returns minimal payload when to_api_response() fails
- `test_file_save_fallback_on_error` — file save produces minimal payload when to_api_response() fails

### MCP server registration tests

- `test_mcp_server_format_enum_includes_agent` — verify "agent" in format enum
- `test_mcp_server_output_param_exists` — verify output parameter registered

## Implementation Order

1. Add `get_agent_snapshot(original_weights)` to `OptimizationResult` in `core/result_objects.py`
2. Create `core/optimization_flags.py` with `generate_optimization_flags()`
3. Add `_build_agent_response()` and `_save_full_optimization()` to `mcp_tools/optimization.py`
4. Add `format="agent"` and `output` parameter to `run_optimization()` in `mcp_tools/optimization.py`
5. Update format dispatch (extract `original_weights` from `result.optimization_metadata`)
6. Update `mcp_server.py` registration (add agent to format enum, add output param)
7. Write tests (getters → flags → composer)
8. Verify via MCP live call: `run_optimization(format="agent")`
