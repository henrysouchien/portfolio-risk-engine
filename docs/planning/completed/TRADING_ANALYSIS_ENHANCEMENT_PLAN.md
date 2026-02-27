# Trading Analysis Enhancement Plan

> **Status:** ✅ COMPLETE
>
> | Component | Status | Description |
> |-----------|--------|-------------|
> | Positions Monitor | ✅ | Open positions with unrealized P&L (`run_positions.py --pnl`) |
> | Trade Tracking Enhancements | ✅ | Company name resolution (provider → FMP → ticker fallback) |
> | Realized Performance Summary | ✅ | Win/loss stats, profit factor, expectancy, by-currency |
> | Distribution of Returns | ✅ | 10-bucket histogram with cumulative frequency |
> | Returns per Trade Stats | ✅ | % and $ returns, skewness, kurtosis |

## Overview

Enhance the existing trading analysis infrastructure to provide comprehensive position monitoring and trade tracking metrics. All outputs should be available in both CLI and JSON formats.

**Existing Infrastructure:**
- `run_trading_analysis.py` - CLI entry point
- `trading_analysis/data_fetcher.py` - Live transaction fetching (Plaid + SnapTrade)
- `trading_analysis/fifo_matcher.py` - FIFO lot matching with cost basis
- `trading_analysis/models.py` - `TradeResult`, `FullAnalysisResult`
- `trading_analysis/metrics.py` - Win score, grades
- `run_positions.py` - Current positions with `cost_basis` field

**Key Insight:** Entry price ≈ cost basis (see caveats below)

---

## Conventions & Edge Cases

### Sign Convention for Positions

All quantities and values use a **consistent sign convention**:

| Position Type | quantity | cost_basis | entry_price | current_value |
|---------------|----------|------------|-------------|---------------|
| Long (own shares) | **+positive** | +positive | +positive | +positive |
| Short (owe shares) | **-negative** | -negative | +positive | -negative |

**Key rules:**
- `quantity` is the source of truth for direction: positive = long, negative = short
- `cost_basis` = total $ invested (positive for long, negative for short)
- `entry_price` = `abs(cost_basis) / abs(quantity)` — **always positive**
- `current_value` = `quantity * current_price` (inherits sign from quantity)

**P&L Calculation (unified for long and short):**
```python
# Works for both long and short positions
pnl_dollars = current_value - cost_basis
pnl_percent = pnl_dollars / abs(cost_basis) * 100
```

**Example - Long position:**
- quantity = +100, cost_basis = +$5,000, entry_price = $50
- current_price = $60, current_value = +$6,000
- pnl_dollars = $6,000 - $5,000 = +$1,000 ✓

**Example - Short position:**
- quantity = -100, cost_basis = -$5,000, entry_price = $50
- current_price = $40, current_value = -$4,000
- pnl_dollars = -$4,000 - (-$5,000) = +$1,000 ✓ (profit when price drops)

### Division by Zero Guards

All calculations must handle zero denominators:

| Calculation | Guard | Fallback |
|-------------|-------|----------|
| `entry_price = cost_basis / quantity` | `quantity == 0` | Return `None`, skip position |
| `pnl_percent = pnl / cost_basis` | `cost_basis == 0 or None` | Return `None` (display as "N/A") |
| `win_rate = wins / total` | `total == 0` | Return `0.0` |
| `avg_win = win_dollars / num_wins` | `num_wins == 0` | Return `0.0` |
| `avg_loss = loss_dollars / num_losses` | `num_losses == 0` | Return `0.0` |
| `win_loss_ratio = wins / losses` | `losses == 0` | Return `None` |
| `profit_factor = gross_profit / gross_loss` | `gross_loss == 0` | Return `None` |

**Note:** We use `None` (not `float('inf')`) for undefined ratios because:
- JSON doesn't support infinity natively
- CLI can display "N/A" consistently
- Avoids downstream math errors

**Implementation patterns:**
```python
from typing import Optional

def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Use for metrics that default to 0.0 (e.g., win_rate, avg_win)."""
    if denominator == 0:
        return default
    return numerator / denominator

def safe_divide_optional(numerator: float, denominator: Optional[float]) -> Optional[float]:
    """Use for Optional fields that should be None when undefined (e.g., pnl_percent, entry_price, win_loss_ratio, profit_factor)."""
    if denominator is None or denominator == 0:
        return None
    return numerator / denominator
```

**Which to use:**
- `safe_divide` → For stats that make sense as 0 (win_rate, avg_win, avg_loss)
- `safe_divide_optional` → For fields that should be `None`/N/A when undefined (pnl_percent, entry_price, win_loss_ratio, profit_factor)

### Expectancy Formula

**Definition:** Expected profit per trade in dollars.

```python
# Use proportions (0.0 to 1.0), NOT percentages
win_proportion = num_wins / total_trades  # e.g., 0.40, not 40
loss_proportion = num_losses / total_trades  # e.g., 0.55, not 55

expectancy = (win_proportion * avg_win_dollars) - (loss_proportion * abs(avg_loss_dollars))
```

**Example:**
- 40% win rate, avg win = $500, avg loss = $200
- expectancy = (0.40 × $500) - (0.60 × $200) = $200 - $120 = **$80 per trade**

### Multi-Currency Handling

**Decision:** Group by currency, don't convert.

- Each currency is tracked separately in summaries
- No cross-currency aggregation (avoids FX rate assumptions)
- JSON output includes `by_currency` breakdowns

```json
{
  "summary": {
    "by_currency": {
      "USD": {"gross_exposure": 150000, "net_pnl": 5000},
      "CAD": {"gross_exposure": 25000, "net_pnl": -500}
    },
    "primary_currency": "USD"
  }
}
```

### Return Distribution Bucket Boundaries

**Convention:** Lower bound inclusive, upper bound exclusive `[min, max)`

| Bucket Label | Range |
|--------------|-------|
| `< -50%` | `[-∞, -50)` |
| `-50% to -30%` | `[-50, -30)` |
| `-30% to -20%` | `[-30, -20)` |
| `-20% to -10%` | `[-20, -10)` |
| `-10% to 0%` | `[-10, 0)` |
| `0% to 10%` | `[0, 10)` |
| `10% to 20%` | `[10, 20)` |
| `20% to 30%` | `[20, 30)` |
| `30% to 50%` | `[30, 50)` |
| `>= 50%` | `[50, +∞)` |

**Edge case:** Exactly 0% goes in `[0, 10)` bucket, not negative bucket.
**Edge case:** Exactly 50% goes in `>= 50%` bucket (lower bound inclusive).

### Company Name Resolution

**Fallback strategy (in order):**
1. Provider security data (`securities[].name` for Plaid, `symbol.description` for SnapTrade)
2. FMP API lookup (`profile` endpoint) — **only if FMP_API_KEY is configured**
3. Ticker symbol as fallback (uppercase, normalized)

**FMP lookup conditions:**
- Only attempt if `FMP_API_KEY` environment variable is set
- Cache results to avoid repeated API calls
- Fail silently (return ticker) if lookup fails or times out

**Ticker normalization:**
- Uppercase all tickers
- Strip exchange suffixes (`.TO`, `.V` → raw ticker)
- Handle OTC suffixes (`TICKER.OB` → `TICKER`)

```python
def normalize_ticker(ticker: str) -> str:
    ticker = ticker.upper().strip()
    for suffix in ['.TO', '.V', '.OB', '.PK']:
        if ticker.endswith(suffix):
            ticker = ticker[:-len(suffix)]
    return ticker
```

**Duplicate handling:** First match wins (provider data takes precedence).

### Cost Basis Assumptions & Caveats

**Best-effort assumption:** `entry_price ≈ cost_basis / quantity`

This holds for most cases but may be inaccurate for:

| Scenario | Issue | Mitigation |
|----------|-------|------------|
| Margin positions | Cost basis may include margin interest | Flag positions with unusual cost basis |
| Short sales | Brokers report differently | Use sign convention above |
| Corporate actions (splits, mergers) | Adjusted cost basis | Accept broker-reported value |
| Transferred positions | Cost basis may be missing or estimated | Show "N/A" if cost_basis is null |
| Wash sale adjustments | IRS-adjusted cost basis | Accept broker-reported value |

**Guardrail:** If `entry_price` is unreasonably high/low (>10x or <0.1x current price), flag for review.

**Flag format:**
- CLI: Append `⚠` to the row and add footnote "Entry price may be inaccurate"
- JSON: Add `"entry_price_warning": true` field to the position object

---

## Component 1: Positions Monitor (Open Positions)

**Goal:** Show current open positions with unrealized P&L

### Required Fields

| Field | Source | Calculation |
|-------|--------|-------------|
| Ticker | Positions API | Direct |
| Company Name | Positions API | `name` field (with fallback strategy) |
| Long/Short | Positions API | `'LONG' if quantity > 0 else 'SHORT'` |
| Shares | Positions API | `abs(quantity)` for display |
| Weighted Entry Price | Positions API / FIFO | `abs(cost_basis) / abs(quantity)` (always positive) |
| Current Price | Positions API | `price` |
| Gross Exposure | Calculated | `abs(quantity * price)` |
| Net Exposure | Calculated | `quantity * price` (sign from quantity) |
| $ P&L | Calculated | `(quantity * price) - cost_basis` (see Sign Convention) |
| % P&L | Calculated | `pnl_dollars / abs(cost_basis) * 100` |

**Note:** See "Conventions & Edge Cases" section for sign convention and division-by-zero guards.

### Implementation

**Option A: Enhance `run_positions.py`**
Add `--pnl` flag to show unrealized P&L columns.

```bash
python run_positions.py --pnl
python run_positions.py --pnl --format json --output positions_pnl.json
```

**Option B: Add to `run_trading_analysis.py`**
Add `--open-positions` flag to show current positions with P&L.

```bash
python run_trading_analysis.py --open-positions
```

**Recommendation:** Option A - keep position monitoring in `run_positions.py`

### Data Model Addition

```python
@dataclass
class PositionPnL:
    """Open position with unrealized P&L"""
    ticker: str
    name: str
    direction: str  # 'LONG' or 'SHORT'
    quantity: float  # Raw signed quantity (positive=long, negative=short)
    shares: float  # abs(quantity) for display
    entry_price: Optional[float]  # None if cost_basis missing
    current_price: float
    gross_exposure: float
    net_exposure: float
    pnl_dollars: float
    pnl_percent: Optional[float]  # None if cost_basis missing (display as "N/A")
    currency: str = 'USD'
    entry_price_warning: bool = False  # True if entry_price looks suspect
```

### CLI Output

```
POSITIONS MONITOR
═══════════════════════════════════════════════════════════════════════════════
Ticker     Name                    Dir    Shares    Entry    Current    $ P&L    % P&L
───────────────────────────────────────────────────────────────────────────────────────
NVDA       NVIDIA Corp             LONG      25.0   115.36    125.00    241.00    8.4%
MSCI       MSCI Inc                LONG      33.5   543.75    544.00      8.38    0.0%
ENB        Enbridge Inc            LONG     227.0    40.00     40.00      0.00    0.0%
...

SUMMARY
───────────────────────────────────────────────────────────────────────────────────────
Gross Exposure:  $XXX,XXX.XX
Net Exposure:    $XXX,XXX.XX
Total Unrealized P&L: $X,XXX.XX (X.X%)
```

### JSON Output

```json
{
  "positions": [
    {
      "ticker": "NVDA",
      "name": "NVIDIA Corp",
      "direction": "LONG",
      "quantity": 25.0,
      "shares": 25.0,
      "entry_price": 115.36,
      "current_price": 125.00,
      "gross_exposure": 3125.00,
      "net_exposure": 3125.00,
      "pnl_dollars": 241.00,
      "pnl_percent": 8.4,
      "currency": "USD",
      "entry_price_warning": false
    }
  ],
  "summary": {
    "by_currency": {
      "USD": {
        "gross_exposure": 150000.00,
        "net_exposure": 145000.00,
        "unrealized_pnl_dollars": 5000.00
      },
      "CAD": {
        "gross_exposure": 25000.00,
        "net_exposure": 24000.00,
        "unrealized_pnl_dollars": -500.00
      }
    },
    "primary_currency": "USD"
  }
}
```

---

## Component 2: Trade Tracking Enhancements

**Goal:** Add company name to realized trade results

### Changes Required

1. **Enhance `TradeResult`** - Add `name` field
2. **Update `TradingAnalyzer`** - Populate name from securities data
3. **Update CLI output** - Show name in trade scorecard

### Data Sources for Company Names

- **Plaid:** `securities[].name` (already fetched in `data_fetcher.py`)
- **SnapTrade:** `symbol.description` or fetch from FMP

### Implementation

```python
# In trading_analysis/models.py
@dataclass
class TradeResult:
    symbol: str
    name: str = ""  # ADD: Company name
    # ... rest unchanged
```

```python
# In trading_analysis/analyzer.py
# Build symbol → name mapping from securities
self.symbol_to_name = {}
for sec in plaid_securities:
    ticker = sec.get('ticker_symbol')
    if ticker:
        self.symbol_to_name[ticker] = sec.get('name', '')
```

---

## Component 3: Realized Performance Summary

**Goal:** Comprehensive win/loss statistics

### Required Fields

| Field | Calculation | Guard |
|-------|-------------|-------|
| Number of Wins | `count(pnl_dollars > 0)` | — |
| Number of Losses | `count(pnl_dollars < 0)` | — |
| Number of Breakeven | `count(pnl_dollars == 0)` | — |
| Total Trades | `len(trade_results)` | — |
| Win % | `num_wins / total_trades * 100` | Return 0 if total=0 |
| Loss % | `num_losses / total_trades * 100` | Return 0 if total=0 |
| Win $ | `sum(pnl where pnl > 0)` | — |
| Loss $ | `abs(sum(pnl where pnl < 0))` | Always positive |
| Win/Loss Ratio | `total_win_dollars / total_loss_dollars` | Return `None` if loss=0 |
| Avg Win | `total_win_dollars / num_wins` | Return 0 if wins=0 |
| Avg Loss | `total_loss_dollars / num_losses` | Return 0 if losses=0 |
| Expectancy | `(win_prop * avg_win) - (loss_prop * avg_loss)` | See formula below |
| Profit Factor | `total_win_dollars / total_loss_dollars` | Return `None` if loss=0 |

**Expectancy formula (uses proportions, not percentages):**
```python
win_proportion = num_wins / total_trades  # e.g., 0.40
loss_proportion = num_losses / total_trades  # e.g., 0.55
expectancy = (win_proportion * avg_win) - (loss_proportion * avg_loss)
# Result is in dollars per trade
```

**Note:** See "Conventions & Edge Cases" section for division guards.

### Data Model Addition

```python
@dataclass
class RealizedPerformanceSummary:
    """Detailed win/loss statistics"""
    num_wins: int
    num_losses: int
    num_breakeven: int
    total_trades: int

    win_percent: float  # 0-100
    loss_percent: float  # 0-100

    total_win_dollars: float  # Sum of positive P&L
    total_loss_dollars: float  # Absolute sum of negative P&L (always positive)
    net_pnl: float

    win_loss_ratio: Optional[float]  # None if no losses
    profit_factor: Optional[float]  # None if no losses
    avg_win: float  # 0 if no wins
    avg_loss: float  # 0 if no losses (stored as positive)

    expectancy: float  # Expected $ per trade

    # Per-currency breakdown (for multi-currency portfolios)
    by_currency: Dict[str, Dict[str, float]] = field(default_factory=dict)
```

### CLI Output

```
REALIZED PERFORMANCE
═══════════════════════════════════════════════════════════════════════════════
Trades:     45 total (18 wins, 25 losses, 2 breakeven)
Win Rate:   40.0%
Loss Rate:  55.6%

Win $:      $12,500.00
Loss $:     $8,200.00
Net P&L:    $4,300.00

Avg Win:    $694.44
Avg Loss:   $328.00
Win/Loss:   1.52x

Expectancy: $95.56 per trade
Profit Factor: 1.52
```

### JSON Output

```json
{
  "realized_performance": {
    "num_wins": 18,
    "num_losses": 25,
    "num_breakeven": 2,
    "total_trades": 45,
    "win_percent": 40.0,
    "loss_percent": 55.6,
    "total_win_dollars": 12500.00,
    "total_loss_dollars": 8200.00,
    "net_pnl": 4300.00,
    "avg_win": 694.44,
    "avg_loss": 328.00,
    "win_loss_ratio": 1.52,
    "expectancy": 95.56,
    "profit_factor": 1.52
  }
}
```

---

## Component 4: Distribution of Returns

**Goal:** Histogram analysis of trade returns

### Required Fields

| Field | Description |
|-------|-------------|
| Range | Return bucket (e.g., "-20% to -10%") |
| Count | Number of trades in bucket |
| Frequency | `count / total_trades * 100` |
| Cumulative Frequency | Running total of frequency |

### Implementation

**Bucket boundary convention:** Lower bound inclusive, upper bound exclusive `[min, max)`

See "Conventions & Edge Cases" section for full bucket definitions.

```python
@dataclass
class ReturnBucket:
    """A bucket in the return distribution"""
    range_min: Optional[float]  # Lower bound (%), None for unbounded
    range_max: Optional[float]  # Upper bound (%), None for unbounded
    range_label: str  # e.g., "-20% to -10%"
    count: int
    frequency: float  # Percentage of total (0-100)
    cumulative_frequency: float  # Running total (0-100)

@dataclass
class ReturnDistribution:
    """Distribution of trade returns"""
    buckets: List[ReturnBucket]
    total_trades: int
    min_return: float  # Actual min return in data
    max_return: float  # Actual max return in data
```

**Bucket assignment logic:**
```python
def assign_bucket(return_pct: float) -> str:
    # Lower bound inclusive, upper bound exclusive
    if return_pct < -50: return "< -50%"
    if return_pct < -30: return "-50% to -30%"
    if return_pct < -20: return "-30% to -20%"
    if return_pct < -10: return "-20% to -10%"
    if return_pct < 0:   return "-10% to 0%"
    if return_pct < 10:  return "0% to 10%"  # Includes exactly 0%
    if return_pct < 20:  return "10% to 20%"
    if return_pct < 30:  return "20% to 30%"
    if return_pct < 50:  return "30% to 50%"
    return ">= 50%"
```

### CLI Output

```
RETURN DISTRIBUTION
═══════════════════════════════════════════════════════════════════════════════
Range              Count    Freq     Cumul
─────────────────────────────────────────────
< -50%                 2    4.4%      4.4%
-50% to -30%           3    6.7%     11.1%
-30% to -20%           5   11.1%     22.2%
-20% to -10%           8   17.8%     40.0%
-10% to 0%             7   15.6%     55.6%
0% to 10%              6   13.3%     68.9%
10% to 20%             5   11.1%     80.0%
20% to 30%             4    8.9%     88.9%
30% to 50%             3    6.7%     95.6%
>= 50%                 2    4.4%    100.0%
─────────────────────────────────────────────
Total                 45

Range: -65.2% to +82.4%
```

### JSON Output

```json
{
  "return_distribution": {
    "buckets": [
      {"range_label": "< -50%", "count": 2, "frequency": 4.4, "cumulative_frequency": 4.4},
      {"range_label": "-50% to -30%", "count": 3, "frequency": 6.7, "cumulative_frequency": 11.1}
    ],
    "total_trades": 45,
    "min_return": -65.2,
    "max_return": 82.4
  }
}
```

---

## Component 5: Returns per Trade Statistics

**Goal:** Statistical summary of returns

### Required Fields

| Field | Calculation |
|-------|-------------|
| Average Return (%) | Mean of `pnl_percent` |
| Median Return (%) | Median of `pnl_percent` |
| Std Dev (%) | Standard deviation |
| Average Positive (%) | Mean of positive returns |
| Average Negative (%) | Mean of negative returns |
| Best Trade (%) | Max return |
| Worst Trade (%) | Min return |
| Skewness | Distribution skew |

### Data Model Addition

```python
@dataclass
class ReturnStatistics:
    """Statistical summary of trade returns"""
    # Percentage returns
    avg_return_percent: float
    median_return_percent: float
    std_dev_percent: float
    avg_positive_percent: float
    avg_negative_percent: float
    best_return_percent: float
    worst_return_percent: float

    # Dollar returns
    avg_return_dollars: float
    median_return_dollars: float
    std_dev_dollars: float
    avg_positive_dollars: float
    avg_negative_dollars: float
    best_return_dollars: float
    worst_return_dollars: float

    # Additional stats
    skewness: float
    kurtosis: float
```

### CLI Output

```
RETURN STATISTICS
═══════════════════════════════════════════════════════════════════════════════
                    % Return      $ Return
────────────────────────────────────────────
Average               +5.2%        $245.00
Median                +2.1%        $120.00
Std Dev               18.4%        $890.00

Avg Positive         +22.5%        $694.44
Avg Negative         -12.8%       -$328.00

Best Trade           +82.4%      $3,200.00
Worst Trade          -65.2%     -$2,100.00

Skewness: 0.45 (slightly right-skewed)
```

### JSON Output

```json
{
  "return_statistics": {
    "avg_return_percent": 5.2,
    "median_return_percent": 2.1,
    "std_dev_percent": 18.4,
    "avg_positive_percent": 22.5,
    "avg_negative_percent": -12.8,
    "best_return_percent": 82.4,
    "worst_return_percent": -65.2,
    "avg_return_dollars": 245.00,
    "median_return_dollars": 120.00,
    "std_dev_dollars": 890.00,
    "avg_positive_dollars": 694.44,
    "avg_negative_dollars": -328.00,
    "best_return_dollars": 3200.00,
    "worst_return_dollars": -2100.00,
    "skewness": 0.45
  }
}
```

---

## Implementation Phases

### Phase 1: Realized Performance Summary ✅
**Priority:** High - Quick win, all data already available

- [x] Add `RealizedPerformanceSummary` to `models.py`
- [x] Add calculation in `analyzer.py` or `metrics.py`
- [x] Add CLI output in `run_trading_analysis.py`
- [x] Add to JSON output (`_results_to_dict`)

### Phase 2: Return Statistics ✅
**Priority:** High - All data available, simple calculations

- [x] Add `ReturnStatistics` to `models.py`
- [x] Implement using statistics module (% and $ returns, skewness, kurtosis)
- [x] Add CLI and JSON output

### Phase 3: Return Distribution ✅
**Priority:** Medium - Requires bucketing logic

- [x] Add `ReturnBucket`, `ReturnDistribution` to `models.py`
- [x] Implement histogram bucketing (10 buckets, `[min, max)` convention)
- [x] Add CLI and JSON output

### Phase 4: Trade Tracking Enhancements ✅
**Priority:** Medium - Need to wire up company names

- [x] Add `name` field to `TradeResult`
- [x] Build symbol → name mapping from securities (provider → FMP → ticker)
- [x] Update CLI trade scorecard

### Phase 5: Positions Monitor ✅
**Priority:** Medium - Needs integration with positions

- [x] Add `PositionPnL` model
- [x] Add `--pnl` flag to `run_positions.py` (alias for `--monitor`)
- [x] Calculate unrealized P&L from cost_basis
- [x] Add CLI and JSON output (with by-account and by-currency breakdowns)

---

## Files to Modify

| File | Changes |
|------|---------|
| `trading_analysis/models.py` | Add new dataclasses |
| `trading_analysis/analyzer.py` | Add calculation methods |
| `trading_analysis/metrics.py` | Add statistical calculations |
| `run_trading_analysis.py` | Add new CLI output sections |
| `run_positions.py` | Add `--pnl` flag and output |
| `core/result_objects.py` | Consider adding `TradingAnalysisResult` |

---

## Testing

```bash
# Test realized performance
python run_trading_analysis.py --user-email user@example.com

# Test positions with P&L
python run_positions.py --pnl --user-email user@example.com

# Test JSON output
python run_trading_analysis.py --user-email user@example.com --output results.json
```

---

## Related Documents

- [Position Module Plan](./POSITION_MODULE_PLAN.md) - Position service implementation
- [Trade Tracking Plan](./TRADE_TRACKING_PLAN.md) - Original trade tracking design
- [Modular Architecture](./MODULAR_ARCHITECTURE_REFACTOR_PLAN.md) - Where trading module fits

**Implementation Files:**
- `run_trading_analysis.py` - Main CLI
- `trading_analysis/models.py` - Data models
- `trading_analysis/analyzer.py` - Analysis logic
- `trading_analysis/metrics.py` - Metric calculations
- `run_positions.py` - Position CLI

---

*Document created: 2026-02-02*
*Status: Complete (2026-02-03)*
