# Trading Scorecard Redesign

## Problem

The current scoring model has conceptual overlaps and wrong incentives:
- **Conviction** measures sizing quality (bigger bets → better returns), not actual conviction
- **Sizing** rewards consistency (CV%) which penalizes traders who correctly size to edge
- **Averaging Down** defaults to F on no data, dragging overall grade down
- **Timing** is frequently N/A due to missing price data

## Unit of Analysis

**Thesis-level round-trips, not FIFO lots.**

The current FIFO matcher produces one `ClosedTrade` per lot. A single position scaled into 3 times produces 3 lots — but to a PM this is one trade. Scoring each lot independently overweights scaled-in positions and breaks the assumption of independent observations.

**Aggregation rule:** Group `ClosedTrade` lots by `(symbol, currency, direction)` — matching the FIFO matcher's keying. Split into separate round-trips when the position goes fully flat (all lots for that key are closed before the next entry). This matches the PM definition of "a trade": buy AAPL, maybe scale in more, sell it all = one round-trip. Buy AAPL again later after being flat = new round-trip.

Per round-trip:
- **Return %** = total P&L USD / total cost basis USD (weighted by lot size)
- **Position size (USD)** = total cost basis converted to USD. Derivation: `abs(pnl_dollars_usd) / abs(pnl_percent)` when pnl_percent ≠ 0, else sum of `cost_basis × fx_rate`. This avoids needing a separate FX conversion for cost basis since USD P&L is already computed.
- **Hold duration** = earliest entry → latest exit
- **Win/loss** = P&L USD > 0 → win, else loss
- **Instrument type** = from the underlying lots (equity, option, futures)

This gives fewer but more meaningful observations. The minimum sample thresholds (10 for Edge, 15 for Sizing) apply to round-trips, not lots.

**Implementation:** Add `aggregate_to_round_trips(closed_trades: list[ClosedTrade]) -> list[RoundTrip]` in `trading_analysis/analyzer.py`. New scoring functions operate on `RoundTrip` objects. Old lot-level scoring continues for v1 grades (dual-write).

## New Scoring Dimensions

Four clean, non-overlapping dimensions:

### 1. Edge (Trade Selection Quality) — size-neutral

**What it measures:** If you put $1 into every trade, how would you do? Pure stock-picking skill, stripped of position sizing effects.

**Core metric:** Simple (equal-weighted) average return per round-trip (%).

This is intentionally NOT dollar-weighted. Dollar-weighted metrics (like profit factor) combine selection + sizing — we want just selection here. Sizing gets its own grade.

**Grade thresholds — instrument-aware:**

Returns have very different scales across instrument types. A 50% return on options is normal; on equities it's exceptional. Futures sit between (leveraged but more moderate than options).

| Grade | Equity | Options | Futures | Interpretation |
|-------|--------|---------|---------|----------------|
| A | ≥ 5% | ≥ 20% | ≥ 8% | Strong selection |
| B | ≥ 2% | ≥ 8% | ≥ 3% | Good selection |
| C | ≥ 0% | ≥ 0% | ≥ 0% | Break-even |
| D | ≥ -3% | ≥ -10% | ≥ -5% | Poor selection |
| F | < -3% | < -10% | < -5% | Bad selection |

These are starting heuristics — calibrate against real portfolio data.

For mixed portfolios: compute separate Edge grades per instrument class, then weight by round-trip count.

**Edge cases:**
- All winners / all losers: grade based on magnitude of avg return
- Minimum sample: ≥ 10 round-trips. Below that → N/A.

**Note:** Profit factor (dollar-weighted) is still shown on the card as a headline metric — it's the *combined outcome* of Edge + Sizing. But it's not a grade input.

### 2. Sizing (Bet Sizing Relative to Outcome)

**What it measures:** Are you betting more on your better trades? Does position size correlate with return?

**Core metric:** Spearman rank correlation between position size and trade return (%), computed on round-trips.

**Position size normalization:** Use USD cost basis (derived from round-trip aggregation — see Unit of Analysis). Spearman operates on ranks, so the exact USD amount matters less than the ordering — but using USD ensures cross-currency positions rank correctly (a £5K trade and a $5K trade need to be in the same currency to rank meaningfully).

For derivatives: use cost basis in USD (premium paid for options, margin posted for futures). This is what the trader actually risked, not the notional exposure.

**Grade thresholds:**
| Grade | Correlation | Interpretation |
|-------|------------|----------------|
| A | ≥ 0.25 | Strong — bigger bets clearly outperform |
| B | ≥ 0.10 | Good — some edge in sizing decisions |
| C | ≥ -0.05 | Neutral — sizing mostly unrelated to outcome |
| D | ≥ -0.20 | Poor — inverse relationship emerging |
| F | < -0.20 | Bad — bigger bets actively underperform |

**Statistical gating:** At n=15, ρ=0.25 has a two-tailed p-value of ~0.37 — not significant. Rather than requiring significance, treat the thresholds as directional indicators and label the grade with a confidence qualifier:
- ≥ 20 round-trips: "high confidence"
- 15-19 round-trips: "moderate confidence" (append to tooltip)

**Edge cases:**
- All trades same size (zero variance in ranks — tied ranks): → N/A
- All trades same return: → N/A
- Minimum sample: ≥ 15 round-trips with ≥ 4 distinct size ranks (after tie-collapsing). Below that → N/A.

### 3. Timing (Entry/Exit Efficiency)

**What it measures:** Are you exiting at good prices relative to what was available?

**Core metric:** Keep current timing score — exit price vs optimal exit within holding period. Computed per symbol, aggregated.

**Grade thresholds (keep current):**
| Grade | Avg Timing Score | Interpretation |
|-------|-----------------|----------------|
| A | ≥ 70% | Excellent — capturing most available gains |
| B | ≥ 55% | Good — solid timing |
| C | ≥ 40% | Average — room for improvement |
| D | ≥ 25% | Poor — leaving significant money on table |
| F | < 25% | Very poor — consistently bad timing |

**Minimum sample:** ≥ 3 symbols with price data. Below that → N/A.

### 4. Discipline (Behavioral Process Quality)

**What it measures:** Are you following a disciplined process, or trading emotionally? Purely process metrics — no P&L outcomes.

**Single metric: Patience**

Metric: median hold duration (winners) / median hold duration (losers), computed on round-trips.
- Ratio > 1.0 = good (holding winners longer than losers)
- Ratio = 1.0 = neutral
- Ratio < 1.0 = bad (holding losers longer)

Score mapping (ratio → 0-100, log-scale):
```
score = 50 + 36 × ln(ratio)
```
- Ratio clamped to [0.2, 5.0] before applying
- 1.0 → 50 (C), 2.0 → 75 (A), 0.5 → 25 (D)
- Symmetric: doubling and halving the ratio move the score equally

**Why single metric:** Revenge trading detection isn't implemented yet (hardcoded empty). Averaging down success is an outcome metric (not process). Keep it simple — one clean metric. Add revenge trading as a sub-metric when detection is built.

**Edge cases:**
- No winners or no losers: → N/A
- Zero-duration round-trips (all day trades with days_in_trade = 0): use hours if available, else exclude. If all round-trips are zero-duration → N/A.
- Minimum sample: ≥ 5 round-trips with both wins and losses. Below that → N/A.

**Grade thresholds:**
| Grade | Score | Patience Ratio | Interpretation |
|-------|-------|---------------|----------------|
| A | ≥ 75 | ~2.0x | Patient — winners held much longer than losers |
| B | ≥ 55 | ~1.15x | Good — slight patience advantage |
| C | ≥ 35 | ~0.65x | Average — roughly equal hold durations |
| D | ≥ 20 | ~0.4x | Impatient — cutting winners, holding losers |
| F | < 20 | < 0.4x | Very impatient |

## Overall Grade

Grade-point average of available (non-N/A) dimensions:

| Grade | Points |
|-------|--------|
| A | 4.0 |
| B | 3.0 |
| C | 2.0 |
| D | 1.0 |
| F | 0.0 |

Overall GPA = sum of points / count of non-N/A dimensions

| GPA | Overall Grade |
|-----|--------------|
| ≥ 3.5 | A |
| ≥ 2.5 | B |
| ≥ 1.5 | C |
| ≥ 0.5 | D |
| < 0.5 | F |

**Minimum:** At least 2 dimensions must have data. If fewer → Overall = N/A.

## Known Limitations (Accepted)

**Timing operates on a different universe than other grades.** Timing uses the raw trade/symbol-level data and current price-history analysis, not round-trips. This is by design — timing efficiency is fundamentally a per-symbol question ("how well did you exit AAPL?"), not a per-lot or per-round-trip question.

**Edge embeds timing quality.** A round-trip's return includes the effect of exit timing — if you sold at a bad price, your return suffers and Edge grades lower. Fully decomposing selection quality from timing quality would require counterfactual analysis ("what would the return have been with perfect timing?"), which is a separate feature beyond this redesign.

## Migration

### Approach: Dual-write with parallel computation

Backend runs BOTH old (v1) and new (v2) scoring algorithms. Old grades use existing lot-level logic unchanged. New grades use round-trip aggregation. API response includes both under separate keys.

```python
grades = {
    # New dimensions (v2 scorecard)
    "overall_v2": "B",
    "edge": "C",
    "sizing": "B",
    "timing": "N/A",
    "discipline": "B",
    # Old dimensions (v1, unchanged computation)
    "overall": "C",
    "conviction": "C",
    "position_sizing": "A",
    "timing_v1": "N/A",
    "averaging_down": "F",
}
```

Frontend reads v2 keys when available, falls back to v1. Old keys removed in a cleanup pass.

All existing serialization paths emit both: `to_api_response()`, `get_agent_snapshot()`, `to_summary()`.

## Files to Change

### Backend:
| File | Change |
|------|--------|
| `trading_analysis/analyzer.py` | `aggregate_to_round_trips()`, `compute_edge_grade()`, `compute_sizing_grade()`, `compute_discipline_grade()` |
| `trading_analysis/models.py` | `RoundTrip` dataclass, dual-write v1+v2 grades in all emission paths |
| `trading_analysis/main.py` | Update JSON serializer for new grade keys |
| `core/trading_flags.py` | Add v2-aware flags |
| `trading_analysis/interpretation_guide.md` | Add v2 metric interpretations |

### Frontend:
| File | Change |
|------|--------|
| `frontend/packages/ui/src/components/portfolio/performance/TradingPnLCard.tsx` | Read v2 grade keys, update labels/descriptions/tooltips |
| `frontend/packages/chassis/src/catalog/types.ts` | Add v2 grade keys to type |

### Tests:
| File | Change |
|------|--------|
| `tests/trading_analysis/test_analyzer.py` | Tests for round-trip aggregation + new scoring functions |
| `tests/trading_analysis/test_result_serialization.py` | Assert v2 grade keys in API response |
| `tests/trading_analysis/test_agent_snapshot.py` | Assert v2 grade keys in snapshot |
| `tests/core/test_trading_flags.py` | Update flag tests for v2 dimensions |
