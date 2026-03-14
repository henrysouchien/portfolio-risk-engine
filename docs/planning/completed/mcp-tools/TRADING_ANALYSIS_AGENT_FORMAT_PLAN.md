# Plan: Agent-Optimized Trading Analysis Output

_Created: 2026-02-24_
_Status: **COMPLETE** (live-tested)_
_Reference: `PERFORMANCE_AGENT_FORMAT_PLAN.md`, `POSITIONS_AGENT_FORMAT_PLAN.md` (same three-layer pattern)_

## Context

`get_trading_analysis` evaluates trading quality from transaction history — FIFO lot matching, timing analysis, conviction sizing, behavioral patterns, and income. The current `format="summary"` returns grades and top winners/losers but no interpretive flags. The agent can't quickly answer "is this user a good trader?" or "what trading behaviors should they change?"

The `format="full"` response includes full trade scorecards, timing analysis per trade, return distribution histograms, and behavioral pattern details — 20-50KB+ depending on trade count.

Goal: Apply the same `format="agent"` + `output="file"` pattern proven in positions and performance.

## Current State

### Output formats

| Format | Size | What agent gets |
|--------|------|-----------------|
| `summary` | ~2-5KB | Grades, top 5 winners/losers, realized perf stats, win rate, PnL. Usable but no interpretation. |
| `full` | ~20-50KB | Everything: all trade scorecards, timing, income, behavioral, return stats. Way too much. |
| `report` | ~3-8KB | Human-readable text. Good for display, not for agent reasoning. |

### What the agent actually needs

1. **Verdict** — Is this user a skilled trader? One-word + supporting grades.
2. **Key metrics** — Total PnL, win rate, profit factor, expectancy, trade count.
3. **Grades** — Conviction, timing, position sizing, averaging down, overall.
4. **Flags** — Poor timing, excessive losses, revenge trading, averaging down failures, low win rate.
5. **Top trades** — Best/worst trades for context.
6. **Income summary** — Total income, projected annual rate.
7. **Behavioral signals** — Revenge trades detected? Position sizing erratic?

### What the agent does NOT need in-context

- Full trade scorecard (every lot with entry/exit/timing)
- Per-trade timing analysis (regret for each position)
- Return distribution histogram buckets
- Monthly/quarterly income breakdowns by symbol
- High activity day details
- Averaging down per-position details

These belong in the file output for deep dives.

## Proposed Design

### Layer 1: Data accessor (on `FullAnalysisResult` in `trading_analysis/models.py`)

New `get_agent_snapshot()` method that returns a compact, structured dict.

```python
def get_agent_snapshot(self) -> dict:
    """Compact metrics for agent consumption."""
    perf = self.realized_performance
    income = self.income_analysis
    behavioral = self.behavioral_analysis
    return_stats = self.return_statistics

    # Top winners/losers — uses _effective_pnl_usd() for correct USD ranking
    # (falls back to pnl_dollars when pnl_dollars_usd is 0.0)
    closed_trades = [t for t in self.trade_results if t.status == "CLOSED"]
    sorted_by_pnl = sorted(closed_trades, key=lambda t: self._effective_pnl_usd(t), reverse=True)
    top_winners = [
        {"symbol": t.symbol, "pnl_usd": round(self._effective_pnl_usd(t), 2),
         "pnl_pct": round(t.pnl_percent, 2), "direction": t.direction}
        for t in sorted_by_pnl[:5] if self._effective_pnl_usd(t) > 0
    ]
    top_losers = [
        {"symbol": t.symbol, "pnl_usd": round(self._effective_pnl_usd(t), 2),
         "pnl_pct": round(t.pnl_percent, 2), "direction": t.direction}
        for t in sorted_by_pnl[-5:] if self._effective_pnl_usd(t) < 0
    ]
    top_losers.reverse()  # worst first

    # Trade counts by status
    status_counts = {}
    for t in self.trade_results:
        status_counts[t.status] = status_counts.get(t.status, 0) + 1

    # Verdict: maps overall grade to a one-word assessment
    _GRADE_VERDICT = {
        "A+": "excellent", "A": "strong", "A-": "good",
        "B+": "good", "B": "decent", "B-": "decent",
        "C+": "mediocre", "C": "mediocre", "C-": "mediocre",
        "D": "poor", "F": "failing",
    }

    snapshot = {
        "verdict": _GRADE_VERDICT.get(self.overall_grade, "unknown"),
        "trades": {
            "total": len(self.trade_results),
            "by_status": status_counts,
            "total_pnl_usd": round(sum(self._effective_pnl_usd(t) for t in self.trade_results), 2),
            "win_rate_pct": round(self.win_rate, 1),
        },
        "grades": {
            "overall": self.overall_grade,
            "conviction": self.conviction_grade,
            "timing": self.timing_grade,
            "position_sizing": self.position_sizing_grade,
            "averaging_down": self.averaging_down_grade,
        },
        "performance": {
            "net_pnl": round(perf.net_pnl, 2) if perf else None,
            "profit_factor": round(perf.profit_factor, 2) if perf and perf.profit_factor is not None else None,
            "expectancy": round(perf.expectancy, 2) if perf else None,
            "avg_win": round(perf.avg_win, 2) if perf else None,
            "avg_loss": round(perf.avg_loss, 2) if perf else None,
            "num_wins": perf.num_wins if perf else 0,
            "num_losses": perf.num_losses if perf else 0,
        },
        "timing": {
            "avg_timing_score_pct": round(self.avg_timing_score, 1),
            "total_regret": round(self.total_regret, 2),
        },
        "conviction": {
            "high_conviction_win_rate_pct": round(self.high_conviction_win_rate, 1),
            "low_conviction_win_rate_pct": round(self.low_conviction_win_rate, 1),
            "conviction_aligned": self.conviction_aligned,
        },
        "income": {
            "total": round(income.total_income, 2) if income else None,
            "dividends": round(income.total_dividends, 2) if income else None,
            "interest": round(income.total_interest, 2) if income else None,
            "projected_annual": round(income.projected_annual, 2) if income else None,
        },
        "behavioral": {
            "revenge_trade_count": len(behavioral.revenge_trades) if behavioral else 0,
            "averaging_down_count": len(behavioral.averaging_down_results) if behavioral else 0,
            "averaging_down_completed_count": (
                len([r for r in behavioral.averaging_down_results if r["outcome"] != "HOLDING"])
                if behavioral else 0
            ),
            "averaging_down_success_rate_pct": (
                round(behavioral.averaging_down_success_rate, 1)
                if behavioral and behavioral.averaging_down_success_rate is not None
                and any(r["outcome"] != "HOLDING" for r in (behavioral.averaging_down_results or []))
                else None
            ),
            "position_size_cv": round(behavioral.position_size_cv, 2) if behavioral else None,
        },
        "top_winners": top_winners,
        "top_losers": top_losers,
    }

    return snapshot
```

### Layer 2: Flag rules (new — `core/trading_flags.py`)

Domain-level interpretive logic, following the `core/position_flags.py` and `core/performance_flags.py` pattern.

```python
def generate_trading_flags(snapshot: dict) -> list[dict]:
    """
    Generate actionable flags from trading analysis snapshot.

    Input: dict from FullAnalysisResult.get_agent_snapshot()
    Each flag: {type, severity, message, ...contextual_data}
    """
    flags = []
    trades = snapshot.get("trades", {})
    grades = snapshot.get("grades", {})
    performance = snapshot.get("performance", {})
    timing = snapshot.get("timing", {})
    conviction = snapshot.get("conviction", {})
    behavioral = snapshot.get("behavioral", {})

    # --- Performance flags ---

    # Low win rate
    win_rate = trades.get("win_rate_pct")
    total = trades.get("total", 0)
    if win_rate is not None and total >= 5 and win_rate < 40:
        flags.append({
            "type": "low_win_rate",
            "severity": "warning",
            "message": f"Win rate is {win_rate:.0f}% across {total} trades",
            "win_rate_pct": win_rate,
        })

    # Negative expectancy
    expectancy = performance.get("expectancy")
    if expectancy is not None and total >= 5 and expectancy < 0:
        flags.append({
            "type": "negative_expectancy",
            "severity": "warning",
            "message": f"Negative expectancy: losing {abs(expectancy):.0f} per trade on average",
            "expectancy": expectancy,
        })

    # Low profit factor (< 1.0 means losses > wins in dollar terms)
    profit_factor = performance.get("profit_factor")
    if profit_factor is not None and total >= 5 and profit_factor < 1.0:
        flags.append({
            "type": "low_profit_factor",
            "severity": "warning",
            "message": f"Profit factor is {profit_factor:.2f} (losses exceed wins in dollar terms)",
            "profit_factor": profit_factor,
        })

    # --- Timing flags ---

    # Poor timing (< 40% of optimal exit)
    avg_timing = timing.get("avg_timing_score_pct")
    if avg_timing is not None and total >= 5 and avg_timing < 40:
        flags.append({
            "type": "poor_timing",
            "severity": "warning",
            "message": f"Exit timing score is {avg_timing:.0f}% (capturing less than half of available gains)",
            "avg_timing_score_pct": avg_timing,
        })

    # High regret (> 1000 left on table)
    total_regret = timing.get("total_regret")
    if total_regret is not None and total_regret > 1000:
        flags.append({
            "type": "high_regret",
            "severity": "info",
            "message": f"{total_regret:,.0f} left on table vs optimal exit timing",
            "total_regret": total_regret,
        })

    # --- Behavioral flags ---

    # Revenge trading detected
    revenge_count = behavioral.get("revenge_trade_count", 0)
    if revenge_count > 0:
        flags.append({
            "type": "revenge_trading",
            "severity": "warning",
            "message": f"{revenge_count} potential revenge trade(s) detected (rapid re-entry after loss)",
            "revenge_trade_count": revenge_count,
        })

    # Averaging down with poor success rate (gate on completed, not total)
    avg_down_completed = behavioral.get("averaging_down_completed_count", 0)
    avg_down_rate = behavioral.get("averaging_down_success_rate_pct")
    if avg_down_completed >= 3 and avg_down_rate is not None and avg_down_rate < 50:
        flags.append({
            "type": "poor_averaging_down",
            "severity": "warning",
            "message": f"Averaging down succeeded only {avg_down_rate:.0f}% of the time ({avg_down_completed} resolved instances)",
            "averaging_down_success_rate_pct": avg_down_rate,
        })

    # Erratic position sizing (CV > 80% — corresponds to grade D or worse)
    cv = behavioral.get("position_size_cv")
    if cv is not None and cv > 80:
        flags.append({
            "type": "erratic_position_sizing",
            "severity": "info",
            "message": f"Position sizing is inconsistent (CV: {cv:.0f}%) — may indicate lack of a sizing framework",
            "position_size_cv": cv,
        })

    # --- Conviction flags ---

    # Conviction misaligned (bigger bets don't perform better)
    conviction_aligned = conviction.get("conviction_aligned", True)
    high_cr = conviction.get("high_conviction_win_rate_pct")
    low_cr = conviction.get("low_conviction_win_rate_pct")
    if not conviction_aligned and high_cr is not None and low_cr is not None and total >= 10:
        flags.append({
            "type": "conviction_misaligned",
            "severity": "info",
            "message": f"Larger positions win {high_cr:.0f}% vs {low_cr:.0f}% for smaller ones — bigger bets aren't performing better",
            "high_conviction_win_rate_pct": high_cr,
            "low_conviction_win_rate_pct": low_cr,
        })

    # --- Grade flags ---

    # Poor overall grade
    overall = grades.get("overall", "")
    if overall and overall in ("D", "F"):
        flags.append({
            "type": "poor_overall_grade",
            "severity": "warning",
            "message": f"Overall trading grade is {overall} — significant room for improvement",
            "overall_grade": overall,
        })

    # --- Positive signals ---

    # Strong overall grade (overall calc returns A/B/C/D/F only — no A+)
    if overall and overall == "A":
        flags.append({
            "type": "strong_trading",
            "severity": "success",
            "message": f"Overall trading grade is {overall} — disciplined and effective",
            "overall_grade": overall,
        })

    # High profit factor
    if profit_factor is not None and profit_factor >= 2.0:
        flags.append({
            "type": "strong_profit_factor",
            "severity": "success",
            "message": f"Profit factor is {profit_factor:.2f} — wins significantly outweigh losses",
            "profit_factor": profit_factor,
        })

    # Sort: warnings first, then info, then success
    severity_order = {"error": 0, "warning": 1, "info": 2, "success": 3}
    flags.sort(key=lambda f: severity_order.get(f.get("severity"), 9))

    return flags
```

### Threshold constants

| Rule | Threshold | Rationale |
|------|-----------|-----------|
| Low win rate | < 40% with >= 5 trades | Losing majority of trades |
| Negative expectancy | < 0 per trade with >= 5 trades | Losing money per trade on average |
| Low profit factor | < 1.0 with >= 5 trades | Dollar losses exceed dollar wins |
| Poor timing | < 40% timing score with >= 5 trades | Capturing less than half of available gains |
| High regret | > 1,000 total regret | Significant money left on table |
| Revenge trading | > 0 revenge trades detected | Emotional re-entry after losses |
| Poor averaging down | < 50% success rate with >= 3 **completed** instances | Adding to losers isn't working |
| Erratic position sizing | CV > 80 (percentage units, grade D boundary) | No consistent sizing framework |
| Conviction misaligned | not aligned with >= 10 trades | Bigger bets don't perform better |
| Poor overall grade | D or F | Significant trading quality issues |
| Strong trading | A (overall calc doesn't produce A+) | Disciplined and effective trading |
| Strong profit factor | >= 2.0 | Wins significantly outweigh losses |

### Layer 3: Agent format composer (in `mcp_tools/trading_analysis.py`)

Thin composition layer — calls Layer 1 getter and Layer 2 flags, shapes response. No domain logic.

```python
from trading_analysis.models import FullAnalysisResult

_TRADING_OUTPUT_DIR = Path("logs/trading")


def _build_agent_response(
    results: FullAnalysisResult,
    file_path: str | None = None,
) -> dict:
    """Compose decision-oriented trading analysis for agent use."""
    from core.trading_flags import generate_trading_flags

    # Layer 1: Data accessor
    snapshot = results.get_agent_snapshot()

    # Layer 2: Interpretive flags
    flags = generate_trading_flags(snapshot)

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

1. Run trading analysis as normal
2. Write full payload to `logs/trading/trading_{source}_{YYYYMMDD}_{HHMMSS}.json`
3. Attach `file_path` to whatever format response is returned

```python
def _save_full_trading(results: FullAnalysisResult, source: str) -> str:
    """Save full trading data to disk and return absolute path."""
    output_dir = _TRADING_OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    file_path = output_dir / f"trading_{source}_{timestamp}.json"

    payload = results.to_api_response()

    with file_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)

    return str(file_path.resolve())
```

## Files to Modify

### 1. Modify: `trading_analysis/models.py`

**Add `get_agent_snapshot()` to `FullAnalysisResult`:**
- Returns compact dict: verdict, trades, grades, performance, timing, conviction, income, behavioral, top_winners, top_losers
- Reads fields directly from dataclass attributes (no None-to-0 defaulting)
- Self-contained top winners/losers logic (sorted by pnl_dollars_usd)

### 2. New: `core/trading_flags.py`

- `generate_trading_flags(snapshot) -> list[dict]`
- All flag rules from the threshold table above
- Accepts the snapshot dict (not the result object) — keeps it decoupled
- Minimum trade count gates (>= 5 or >= 10) to avoid flagging noise from tiny sample sizes
- Sorted by severity (warning > info > success)

### 3. Modify: `mcp_tools/trading_analysis.py`

**Add `_build_agent_response(results, file_path)`:**
- Calls `results.get_agent_snapshot()` (Layer 1)
- Calls `generate_trading_flags()` from `core/trading_flags.py` (Layer 2)
- Nests snapshot under `"snapshot"` key (Layer 3)

**Add `_save_full_trading(results, source)`:**
- Writes `to_api_response()` to `_TRADING_OUTPUT_DIR`
- Returns absolute path

**Update `get_trading_analysis()` signature:**
- Add `format="agent"` to the Literal enum
- Add `output: Literal["inline", "file"] = "inline"` parameter
- File write happens BEFORE format dispatch (matching positions/performance pattern)

**Update format dispatch:**
```python
# File write before format dispatch
file_path = _save_full_trading(results, source) if output == "file" else None

if format == "agent":
    return _build_agent_response(results, file_path=file_path)
elif format == "summary":
    response = {"status": "success", **results.to_summary()}
    if file_path:
        response["file_path"] = file_path
    return response
# ... other formats: attach file_path if present
```

### 4. Modify: `mcp_server.py`

- Add "agent" to the format enum for get_trading_analysis
- Add output parameter
- Pass through to underlying function

## Agent format example output

```json
{
  "status": "success",
  "format": "agent",

  "snapshot": {
    "verdict": "decent",
    "trades": {
      "total": 42,
      "by_status": {"CLOSED": 35, "PARTIAL": 4, "OPEN": 3},
      "total_pnl_usd": 8420.50,
      "win_rate_pct": 54.3
    },
    "grades": {
      "overall": "B",
      "conviction": "B+",
      "timing": "C",
      "position_sizing": "B",
      "averaging_down": "C"
    },
    "performance": {
      "net_pnl": 8420.50,
      "profit_factor": 1.85,
      "expectancy": 200.49,
      "avg_win": 680.25,
      "avg_loss": 420.10,
      "num_wins": 19,
      "num_losses": 16
    },
    "timing": {
      "avg_timing_score_pct": 48.2,
      "total_regret": 3250.00
    },
    "conviction": {
      "high_conviction_win_rate_pct": 62.5,
      "low_conviction_win_rate_pct": 45.0,
      "conviction_aligned": true
    },
    "income": {
      "total": 2840.00,
      "dividends": 2640.00,
      "interest": 200.00,
      "projected_annual": 1920.00
    },
    "behavioral": {
      "revenge_trade_count": 2,
      "averaging_down_count": 5,
      "averaging_down_completed_count": 4,
      "averaging_down_success_rate_pct": 40.0,
      "position_size_cv": 85.0
    },
    "top_winners": [
      {"symbol": "NVDA", "pnl_usd": 3400.25, "pnl_pct": 42.5, "direction": "LONG"},
      {"symbol": "AAPL", "pnl_usd": 1820.00, "pnl_pct": 15.3, "direction": "LONG"}
    ],
    "top_losers": [
      {"symbol": "INTC", "pnl_usd": -1250.00, "pnl_pct": -28.5, "direction": "LONG"},
      {"symbol": "BA", "pnl_usd": -890.00, "pnl_pct": -18.2, "direction": "LONG"}
    ]
  },

  "flags": [
    {
      "type": "revenge_trading",
      "severity": "warning",
      "message": "2 potential revenge trade(s) detected (rapid re-entry after loss)",
      "revenge_trade_count": 2
    },
    {
      "type": "poor_averaging_down",
      "severity": "warning",
      "message": "Averaging down succeeded only 40% of the time (4 resolved instances)",
      "averaging_down_success_rate_pct": 40.0
    },
    {
      "type": "high_regret",
      "severity": "info",
      "message": "3,250 left on table vs optimal exit timing",
      "total_regret": 3250.0
    }
  ],

  "file_path": null
}
```

### What each section answers for the agent:

| Section | Agent question |
|---------|---------------|
| `snapshot.verdict` | "Is this user a good trader?" (one word) |
| `snapshot.trades` | "How many trades and what's the overall P&L?" |
| `snapshot.grades` | "What letter grades does this trader get?" |
| `snapshot.performance` | "What's the expected value per trade?" |
| `snapshot.timing` | "How well does this user time exits?" |
| `snapshot.conviction` | "Do bigger bets perform better?" |
| `snapshot.income` | "How much income from dividends/interest?" |
| `snapshot.behavioral` | "Any bad trading habits?" |
| `snapshot.top_winners` | "What were the best trades?" |
| `snapshot.top_losers` | "What were the worst trades?" |
| `flags` | "What deserves attention?" |
| `file_path` | "Where's the full trade scorecard for deep dives?" |

## Compatibility

- All existing formats (`full`, `summary`, `report`) unchanged
- `format="agent"` is purely additive
- `output="file"` works with any format
- Default format stays `"summary"` (no breaking change)
- `output` defaults to `"inline"` (no breaking change)

## Decisions

1. **Snapshot nested under `"snapshot"` key.** Consistent with positions, performance, and risk agent formats.
2. **`get_agent_snapshot()` lives on `FullAnalysisResult`.** Only one result class (unlike performance which has two). Method is on the model in `trading_analysis/models.py` (not `core/result_objects.py`) because that's where `FullAnalysisResult` is defined.
3. **Flags take the snapshot dict, not the result object.** Same decoupling pattern. Tested with plain dicts.
4. **Minimum trade count gates on flags.** Most flags require >= 5 trades to fire. Conviction alignment requires >= 10. Prevents noisy flags from tiny sample sizes.
5. **Top winners/losers self-contained.** The getter computes its own sorted list from `trade_results` rather than delegating to `to_summary()`. Avoids coupling to summary format internals.
6. **Income section included.** Trading analysis includes dividend/interest income from the same transaction data. Agent needs this for "how much income am I generating?" questions.
7. **Behavioral section is compact.** Only counts and rates, not per-position details. Full behavioral analysis goes to the file output.
8. **`_TRADING_OUTPUT_DIR` module constant.** Testable via `monkeypatch`, defaults to `Path("logs/trading")`.
9. **Source in filename.** `trading_all_20260224_*.json` vs `trading_schwab_20260224_*.json` — agent can tell which provider was analyzed.
10. **Grades surfaced as-is.** Sub-grades use mixed ranges (conviction: B+/C; timing/sizing/averaging-down: A/B/C/D/F). Overall grade: A/B/C/D/F only. No need to re-derive — just surface them in the snapshot and let flags interpret the extremes (D/F = warning, A = success for overall).
11. **Revenge trades not yet implemented.** The analyzer hardcodes `revenge_trades=[]` (line ~869 of `trading_analysis/analyzer.py`). The snapshot field and flag rule are included now so the agent format is future-proof — when the analyzer implements detection, the flag will fire automatically. No special handling needed.
12. **Verdict field derived from overall grade.** Maps letter grade to one-word assessment (excellent/strong/good/decent/mediocre/poor/failing). Lives in the snapshot so the agent can quickly answer "is this user a good trader?" without interpreting grades.
13. **Currency-agnostic field names for performance/timing.** `net_pnl`, `expectancy`, `avg_win`, `avg_loss`, `total_regret` — NOT `_usd` suffixed. The underlying `RealizedPerformanceSummary` computes from `pnl_dollars` (local currency), not `pnl_dollars_usd`. Only `trades.total_pnl_usd` uses `_effective_pnl_usd()` (the per-trade USD fallback). When true USD normalization is added to the performance metrics engine, field names can be updated.
14. **Flag messages are currency-neutral.** No `$` symbols in flag messages since the underlying values may be local currency (not USD). The agent can format with currency context from the portfolio.
15. **`avg_loss` is positive magnitude.** Matches `RealizedPerformanceSummary` convention from `metrics.py` (line 281): `avg_loss = total_loss_dollars / num_losses` (always positive).
16. **Overall grade only produces A/B/C/D/F.** Sub-grades use varying ranges (conviction: B+/C; timing/sizing/avg-down: A/B/C/D/F). `_calculate_overall_grade()` maps the average to A/B/C/D/F only. Strong trading flag checks for A only.
17. **`averaging_down_results` are plain dicts at runtime.** Despite the `List[AveragingDownResult]` type annotation on `BehavioralAnalysis`, `detect_averaging_down()` in `metrics.py` returns `List[Dict]`. Use `r["outcome"]` dict access.
18. **Averaging down flag gates on completed count.** `averaging_down_completed_count` (resolved WIN/LOSS only, excludes HOLDING) is used for the flag gate instead of total instances. The analyzer sets `success_rate = 0` when nothing has resolved (all HOLDING), which would falsely trigger the "poor averaging down" flag. The snapshot reports `success_rate_pct = None` when no outcomes have completed.

## Test Plan

### `trading_analysis/models.py` — get_agent_snapshot tests

- `test_agent_snapshot_keys` — all expected top-level keys present (verdict, trades, grades, performance, timing, conviction, income, behavioral, top_winners, top_losers)
- `test_agent_snapshot_verdict` — verdict maps overall grade correctly (A→"strong", B→"decent", F→"failing", etc.)
- `test_agent_snapshot_trades_section` — total, by_status, total_pnl_usd, win_rate_pct
- `test_agent_snapshot_grades_section` — all 5 grades present
- `test_agent_snapshot_top_winners_sorted` — winners sorted by pnl_usd descending, max 5
- `test_agent_snapshot_top_losers_sorted` — losers sorted by pnl_usd ascending (worst first), max 5
- `test_agent_snapshot_empty_result` — handles empty trade list without crash
- `test_agent_snapshot_no_income` — income fields are None when no income data
- `test_agent_snapshot_no_behavioral` — behavioral fields default to 0/None when no behavioral data
- `test_agent_snapshot_averaging_down_all_holding` — success_rate_pct is None when all instances are HOLDING
- `test_agent_snapshot_performance_fields_not_usd_suffixed` — field names are `net_pnl`, `expectancy`, etc. (no `_usd` suffix)

### `core/trading_flags.py` tests

- `test_low_win_rate_flag` — win rate < 40% with >= 5 trades triggers warning
- `test_win_rate_not_flagged_few_trades` — win rate < 40% with < 5 trades does NOT trigger
- `test_negative_expectancy_flag` — negative expectancy triggers warning
- `test_low_profit_factor_flag` — profit factor < 1.0 triggers warning
- `test_poor_timing_flag` — timing score < 40% triggers warning
- `test_high_regret_flag` — regret > 1000 triggers info
- `test_revenge_trading_flag` — revenge_trade_count > 0 triggers warning
- `test_poor_averaging_down_flag` — < 50% success with >= 3 completed instances triggers warning
- `test_averaging_down_flag_not_triggered_all_holding` — 0 completed instances with 5 total does NOT trigger
- `test_erratic_position_sizing_flag` — CV > 80 triggers info
- `test_conviction_misaligned_flag` — not aligned with >= 10 trades triggers info
- `test_poor_overall_grade_flag` — D or F triggers warning
- `test_strong_trading_flag` — A triggers success (overall calc doesn't produce A+)
- `test_strong_profit_factor_flag` — >= 2.0 triggers success
- `test_flags_sorted_by_severity` — warnings before info before success
- `test_empty_snapshot_no_crash` — empty dict produces no flags

### `mcp_tools/trading_analysis.py` agent format tests

- `test_agent_format_structure` — top-level keys: status, format, snapshot, flags, file_path
- `test_agent_format_calls_getter` — verify delegation to get_agent_snapshot()
- `test_agent_format_has_flags` — flags list present in response
- `test_agent_format_snapshot_nested` — snapshot is nested dict (not spread at top level)

### File output tests

- `test_file_output_creates_file` — file written to logs/trading/
- `test_file_output_includes_source_in_filename` — filename contains source
- `test_file_output_returns_file_path` — file_path in response is valid path
- `test_inline_output_no_file` — output="inline" does not create file
- `test_file_output_attaches_path_to_summary` — format="summary" + output="file" includes file_path
- `test_file_output_attaches_path_to_report` — format="report" + output="file" includes file_path

### MCP server registration tests

- `test_mcp_server_format_enum_includes_agent` — verify mcp_server.py tool registration includes "agent" in format enum
- `test_mcp_server_output_param_exists` — verify output parameter registered for get_trading_analysis

## Implementation Order

1. Add `get_agent_snapshot()` to `FullAnalysisResult` in `trading_analysis/models.py`
2. Create `core/trading_flags.py` with `generate_trading_flags()`
3. Add `_build_agent_response()` and `_save_full_trading()` to `mcp_tools/trading_analysis.py`
4. Add `format="agent"` and `output` parameter to `get_trading_analysis()` in `mcp_tools/trading_analysis.py`
5. Update format dispatch
6. Update `mcp_server.py` registration (add agent to format enum, add output param)
7. Write tests (getters → flags → composer)
8. Verify via MCP live call: `get_trading_analysis(format="agent")`
