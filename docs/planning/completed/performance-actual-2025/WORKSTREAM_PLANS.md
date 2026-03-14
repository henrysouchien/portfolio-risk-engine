# Realized Performance Data Quality — Workstream Plans

## Overview

Three parallel workstreams to fix the realized performance data quality problem.
Every account lost money in 2025, but the system reports gains:

| Account | Actual TWR | System Reports | Gap |
|---|---|---|---|
| IBKR | -9.35% | 0% flat (0 txns) | completely missing |
| Schwab (acct 165) | -8.29% | +176% | +184pp |
| Merrill (Plaid) | -12.49% | +8% | +20pp |

Root cause: 17 of ~24 positions are synthetic (no opening trade), with fabricated cost basis.

---

## Stream A: Diagnostics (Codex)

**Goal:** Build a complete diagnostic picture comparing system output vs. broker actuals, and convert the extracted baseline into a reusable test fixture.

### Tasks

#### A1. Run system output for all sources, capture full results
```bash
python3 -c "
from mcp_tools.performance import get_performance
import json

for source in ['all', 'schwab', 'plaid', 'snaptrade', 'ibkr_flex']:
    try:
        result = get_performance(mode='realized', source=source, format='agent')
        with open(f'docs/planning/performance-actual-2025/system_output_{source}.json', 'w') as f:
            json.dump(result, f, indent=2, default=str)
        print(f'{source}: OK')
    except Exception as e:
        print(f'{source}: ERROR - {e}')
"
```

#### A2. Map each synthetic position to its broker
For each of the 17 synthetic positions, determine:
- Which broker account actually holds it (IBKR vs Schwab vs Merrill)
- Whether it appears in the IBKR open positions baseline (`baseline_ibkr_open_positions.csv`)
- Whether it appears in Schwab/Merrill holdings

Cross-reference `baseline_ibkr_open_positions.csv` symbols (EQT, FIG, IGIC, KINS, NVDA, RNMBY, SFM, SLV, TKO, V) against the synthetic list (AT.L, CPPMF, EQT, FIG, GLBE, IGIC, IT, KINS, LIFFF, MSCI, NVDA, PCTY, RNMBY, SFM, SLV, TKO, V).

Expected finding: 10 of 17 synthetics are IBKR positions (matching the open positions CSV).

#### A3. Compare system cost basis vs. actual broker cost basis
For each IBKR position with known cost basis from `baseline_ibkr_open_positions.csv`:
- What cost basis does the system assign (from system output)?
- What's the delta?
- How much does the delta distort the total return?

#### A4. Build comparison report
Create `docs/planning/performance-actual-2025/DIAGNOSTIC_COMPARISON.md`:
- Per-position table: symbol, broker, actual cost basis, system cost basis, delta
- Per-account table: actual TWR, system TWR, root cause
- Monthly return comparison where possible

#### A5. Convert baseline to test fixture
Create `tests/fixtures/performance_baseline_2025.json` with:
- Expected account-level metrics (TWR per account)
- Expected per-position cost basis (from IBKR CSV)
- Coverage expectations per source
- This enables future regression testing

### Codex Prompt (copy-paste ready)

```
## Task: Realized Performance Diagnostics

You're investigating data quality issues in the realized performance analysis system.
The system reports wildly wrong returns (e.g., +176% when actual is -8.29%).

### Context Files
- Issue doc: `docs/planning/REALIZED_PERF_DATA_QUALITY.md`
- Extracted broker baselines: `docs/planning/performance-actual-2025/BASELINE_EXTRACTED_2025.md`
- Machine-readable baseline: `docs/planning/performance-actual-2025/baseline_extracted_data.json`
- IBKR open positions: `docs/planning/performance-actual-2025/baseline_ibkr_open_positions.csv`
- Main analysis engine: `core/realized_performance_analysis.py`
- MCP tool: `mcp_tools/performance.py`
- Data fetcher: `trading_analysis/data_fetcher.py`

### What to do

1. **Run system output**: Execute `get_performance(mode='realized', source=X, format='agent')` for sources: all, schwab, plaid, snaptrade, ibkr_flex. Save each result as JSON to `docs/planning/performance-actual-2025/system_output_{source}.json`.

2. **Map synthetic positions to brokers**: From the system output (source="all"), extract the synthetic position list. Cross-reference each against `baseline_ibkr_open_positions.csv` to identify which are IBKR positions.

3. **Compare cost basis**: For each position that appears in both the system output and `baseline_ibkr_open_positions.csv`, compare the system's cost basis vs. IBKR's actual cost basis.

4. **Write comparison report**: Create `docs/planning/performance-actual-2025/DIAGNOSTIC_COMPARISON.md` with:
   - Per-position table (symbol, broker, actual cost basis, system cost basis, delta)
   - Per-account summary (actual TWR vs system TWR, root cause explanation)
   - Identify the top 3-5 positions causing the most distortion

5. **Create test fixture**: Create `tests/fixtures/performance_baseline_2025.json` containing the broker-reported ground truth values from `baseline_extracted_data.json`, structured for use in future regression tests.

### Important
- Do NOT modify any production code. This is read-only diagnostics.
- If `get_performance()` calls fail, capture the error and note it.
- The IBKR source may return 0 transactions — that's a known issue, document it.
```

---

## Stream B: IBKR Data Gap Investigation (Us)

**Goal:** Understand and fix why IBKR returns 0 transactions despite being connected.

### Root Cause Found

The issue is the **direct-first routing** interaction:

1. `TRANSACTION_FETCH_POLICY` defaults to `"direct_first"` (settings.py:764)
2. When `source="all"`, direct providers (ibkr_flex, schwab) are fetched first
3. If ibkr_flex is registered as "healthy" (even with 0 results), SnapTrade then **skips** IBKR-associated institutions via `_should_skip_aggregator_institution_for_direct_first()`
4. Result: SnapTrade drops its IBKR transactions, and ibkr_flex returned nothing → 0 total

### Investigation Steps

#### B1. Verify IBKR Flex credentials are configured
```bash
# Check if IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID are set
python3 -c "from settings import IBKR_FLEX_TOKEN, IBKR_FLEX_QUERY_ID; print(f'token={bool(IBKR_FLEX_TOKEN)}, query_id={bool(IBKR_FLEX_QUERY_ID)}')"
```

#### B2. Test IBKR Flex directly
```bash
python3 -c "
from trading_analysis.data_fetcher import fetch_ibkr_flex_payload
result = fetch_ibkr_flex_payload()
print(f'trades: {len(result.get(\"ibkr_flex_trades\", []))}')
print(f'cash_rows: {len(result.get(\"ibkr_flex_cash_rows\", []))}')
print(f'error: {result.get(\"fetch_error\", \"none\")}')
"
```

#### B3. Test SnapTrade for IBKR transactions (bypassing direct-first)
```bash
python3 -c "
from mcp_tools.performance import get_performance
result = get_performance(mode='realized', source='snaptrade', format='agent')
snap = result.get('snapshot', {})
dq = snap.get('data_quality', {})
print(f'coverage={dq.get(\"coverage_pct\")}%, txns={dq.get(\"transaction_count\")}, synthetic={dq.get(\"synthetic_count\")}')
"
```

#### B4. Check "healthy" definition for ibkr_flex
The direct-first routing marks ibkr_flex as "healthy" even if it returns 0 trades.
Check `data_fetcher.py` lines 760-770 — does `_fetch_provider` return True on empty results?

#### B5. Fix: Either fix ibkr_flex or fix the "healthy" gate
- **Option 1**: If Flex credentials work, ensure Flex returns trade history (it may only return recent trades)
- **Option 2**: Fix the "healthy" gate to require > 0 transactions before marking as healthy
- **Option 3**: If Flex is not configured, ensure it's not registered, so SnapTrade picks up IBKR

---

## Stream C: Output Gating (Codex/Third Claude)

**Goal:** When data quality is poor, prevent the agent from seeing misleading headline metrics.

### Context

The system already has some quality infrastructure:
- `data_quality_flags` list with severity levels
- `nav_metrics_estimated` boolean
- Dual NAV tracks (synthetic-enhanced vs observed-only)
- `SYNTHETIC_PNL_SENSITIVITY` flag triggers at $5K impact
- When triggered, return metrics already switch to observed-only NAV series

But the agent still sees headline numbers like "+176% return" without clear gating.

### Design Requirements

1. **Coverage gate**: When `coverage_pct < 50%`, suppress or clearly qualify headline return metrics
2. **Synthetic dominance gate**: When synthetic positions represent > 50% of portfolio value, mark metrics unreliable
3. **Agent format changes**: The `format="agent"` snapshot should include a top-level `reliable: bool` field
4. **Metric suppression vs qualification**: Prefer qualification (show metrics but with warning) over suppression (returning null), because the agent can make its own judgment

### Codex Prompt (copy-paste ready)

```
## Task: Design and Implement Output Gating for Realized Performance

When data quality is poor, the realized performance system reports misleading metrics.
Design and implement gating that prevents the agent from trusting bad numbers.

### Context Files
- Issue doc: `docs/planning/REALIZED_PERF_DATA_QUALITY.md`
- Result objects: `core/result_objects.py` (RealizedPerformanceResult, RealizedMetadata)
- Agent snapshot builder: `core/realized_performance_analysis.py` (search for "agent_snapshot" or "format_agent")
- MCP tool: `mcp_tools/performance.py` (get_performance with format="agent")
- Existing quality infra: search for "data_quality_flags", "nav_metrics_estimated", "SYNTHETIC_PNL_SENSITIVITY"

### What exists today
- `data_quality_flags` list with SYNTHETIC_OPENING_POSITIONS, SYNTHETIC_PNL_SENSITIVITY flags
- Dual NAV tracks: synthetic-enhanced vs observed-only
- When SYNTHETIC_PNL_SENSITIVITY fires (impact > $5K), headline metrics already switch to observed-only
- But there's no top-level "reliable" indicator and no coverage-based gating

### Requirements

1. Add a `reliable: bool` field to the agent snapshot (top level, next to `returns`)
2. `reliable = False` when ANY of:
   - `coverage_pct < 50`
   - `synthetic_current_market_value > 50%` of total portfolio market value
   - `nav_metrics_estimated == True`
3. When `reliable == False`, add a `reliability_note: str` explaining why (one sentence)
4. Do NOT suppress metrics (don't return null) — just add the flag and note
5. Add `coverage_pct` and `synthetic_pct` to the agent snapshot `data_quality` section if not already there

### Implementation approach
- Modify `core/result_objects.py` to add `reliable` and `reliability_note` fields to the appropriate dataclass
- Modify the agent snapshot builder in `core/realized_performance_analysis.py` to compute and set these fields
- Add unit tests in `tests/` that verify:
  - `reliable=True` when coverage >= 50% and synthetic < 50%
  - `reliable=False` with appropriate note when coverage < 50%
  - `reliable=False` with appropriate note when synthetic dominance > 50%

### Important
- Keep changes minimal — don't refactor surrounding code
- The existing SYNTHETIC_PNL_SENSITIVITY logic should remain unchanged
- Test with: `python3 tests/utils/show_api_output.py "get_performance(mode='realized', format='agent')"`
```

---

## Execution Plan

| Stream | Owner | Dependency | Status (2026-02-27) |
|---|---|---|---|
| **A: Diagnostics** | Codex | None | Complete — `DIAGNOSTIC_COMPARISON.md` written |
| **B: IBKR Data Gap** | Us (main Claude) | None | Resolved via P3.1 (compensating events + inception placement) |
| **C: Output Gating** | Codex / Third Claude | After A | Design spec written (Stream C above), not yet implemented |

### Status Update (2026-02-27)

Streams A and B are complete. 8 fix phases (P1→P3.2) have been implemented:

| Source | Pre-P1 | Post-P3.2 (current) | Broker Actual |
|---|---|---|---|
| Combined | -64.37% | +34.66% | -8 to -12% |
| IBKR | (in combined) | +10.45% | -9.35% |
| Schwab | (in combined) | +33.13% | -8.29% |
| Plaid | (in combined) | -7.96% | -12.49% |

See `RETURN_PROGRESSION_BY_FIX.md` for full phase-by-phase progression.

**Next**: P5 (V_start seeding + budget-based incomplete trade suppression) targets the remaining Schwab +33% and IBKR +10% distortions. Plan: `docs/planning/CASH_REPLAY_P5_VSTART_SEEDING_PLAN.md`.
