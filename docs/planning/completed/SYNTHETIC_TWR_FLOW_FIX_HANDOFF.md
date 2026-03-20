# Handoff: Synthetic TWR Flow Fix Implementation

## Status: PLAN COMMITTED, READY FOR IMPLEMENTATION

## What's the problem?

IBKR realized performance shows **-32.53%** vs broker actual **-9.35%**. The gap is caused by 19 synthetic positions whose values appear in NAV but whose cash events are excluded from TWR external flows. The GIPS formula interprets NAV jumps as returns (+490% in March) instead of contributions.

## What's been done

1. **Root cause identified and documented** — synthetic positions appear in NAV but `_create_synthetic_cash_events()` output is excluded from TWR `external_flows` (correct for Modified Dietz, wrong for TWR)
2. **Prior fixes already committed:**
   - `fe297eda` — StmtFunds topic name fix
   - `264c2940` — Ghost account filtering in `_discover_account_ids()`
   - `d9a9f886` — Per-symbol inception (attempted & reverted, caused +3,934% regression)
3. **Plan written and committed** as `28d54017` — went through 3 Codex review cycles (all issues resolved)
4. **Return progression doc updated** as `b6d61b82` — benchmarks documented

## What needs to happen next

### Step 1: Implement the plan

The complete implementation spec is at: **`docs/planning/SYNTHETIC_TWR_FLOW_FIX_PLAN.md`**

Three code changes in `core/realized_performance_analysis.py`:

1. **New helper function** `_synthetic_events_to_flows()` — converts synthetic cash events to TWR flow tuples. BUY → positive inflow, SHORT → negative outflow.

2. **Wire into TWR path** (after line 4437):
   ```python
   synthetic_twr_flows = _synthetic_events_to_flows(synthetic_cash_events, fx_cache)
   twr_external_flows = external_flows + synthetic_twr_flows
   ```
   Then pass `twr_external_flows` (not `external_flows`) to `compute_twr_monthly_returns()` at line 4549.

3. **Store in `_postfilter`** (line 5144): Change `_flows_to_dict(external_flows)` → `_flows_to_dict(twr_external_flows)` so aggregation path picks up synthetic flows.

### Step 2: Write tests

New file: `tests/core/test_synthetic_twr_flows.py` — 11 tests specified in the plan (helper unit tests, TWR integration, wiring/aggregation).

### Step 3: Run tests

```bash
python3 -m pytest tests/core/test_synthetic_twr_flows.py -v
python3 -m pytest tests/core/test_realized_performance_analysis.py -v --tb=short
```

### Step 4: Live verification

```
get_performance(mode="realized", source="ibkr_flex", use_cache=false)
```

Expect: March extreme month reduced from +490%, total return closer to -9.35%.

## Key files

| File | What | Lines |
|------|------|-------|
| `docs/planning/SYNTHETIC_TWR_FLOW_FIX_PLAN.md` | Full implementation spec | all |
| `core/realized_performance_analysis.py` | Where all 3 changes go | 4437, 4549, 5144 |
| `core/realized_performance_analysis.py` | `_create_synthetic_cash_events()` | 1469-1544 |
| `core/realized_performance_analysis.py` | `compute_twr_monthly_returns()` | 2074-2150 |
| `core/realized_performance_analysis.py` | `_postfilter` construction | 5107-5157 |
| `core/realized_performance_analysis.py` | `_build_aggregated_result` | 5585-5650 |
| `docs/planning/performance-actual-2025/RETURN_PROGRESSION_BY_FIX.md` | Benchmark tracking | all |
| `docs/planning/performance-actual-2025/BASELINE_EXTRACTED_2025.md` | Broker actuals | all |

## Current benchmarks (pre-fix)

| Source | Our Number | Broker Actual | Gap |
|--------|-----------|---------------|-----|
| IBKR | -32.53% | -9.35% | -23.18pp |
| Schwab | +17.53% | varies by acct | TBD |
| Plaid | +1.21% | -12.49% | +13.70pp |

## Codex command to implement

```bash
codex exec --dangerously-bypass-approvals-and-sandbox "Implement the synthetic TWR flow fix exactly as specified in docs/planning/SYNTHETIC_TWR_FLOW_FIX_PLAN.md. Make all 3 changes to core/realized_performance_analysis.py (new helper, TWR wiring, postfilter storage). Create tests/core/test_synthetic_twr_flows.py with all 11 tests. Run pytest on both test files. All tests must pass."
```

## Sign conventions (critical)

- TWR: `amt > 0` → inflow (cf_in, denominator), `amt < 0` → outflow (cf_out, numerator)
- Synthetic BUY → **positive** (NAV increases by long position value)
- Synthetic SHORT → **negative** (NAV decreases by short position liability)
- Modified Dietz path is **unaffected** — exclusion of synthetic events was correct for that formula
