# Fix: Back-Solve Diagnostic Script — Date Filtering + FX Conversion

## Context

The back-solve diagnostic script (`scripts/ibkr_cash_backsolve.py`) compares
replayed transaction cash impacts against the IBKR statement to validate our
normalizer output. After the income/fee/MTM dedup fixes, the gap is -$2,695.

We fully decomposed this gap and found it is NOT a normalizer bug — it's caused
by the diagnostic script itself:

1. **No date filtering** (+$3,879): The script sums ALL transactions from the
   DB, including 16 March 2025 trades that fall before the statement period
   (Apr 1 2025). The statement only covers Apr 1 – Mar 3.

2. **No FX conversion** (+$470 / -$30 / -$47 / -$1,621): Non-USD amounts
   (GBP equity trades, HKD futures fees, HKD interest, HKD MTM) are treated
   as USD face values. The `currency` field is available on all event types
   but never read.

3. **Missing FX translation** (-$54): Statement shows +$53.88 "Cash FX
   Translation Gain/Loss" — a holding-period FX gain on non-USD cash balances.
   We have no equivalent. Accept as irreducible.

4. **Withholding tax** (+$125): We report gross dividends, statement nets
   WHTAX. By design — not a bug.

After fixing #1 and #2, expected residual gap should be ~$200-300 (FX
translation + WHTAX + rounding), down from $2,695.

### Full Gap Decomposition (Evidence)

| Category | Delta | Root Cause |
|----------|-------|------------|
| Pre-period trades | +$3,879 | 16 Mar 2025 trades outside statement period |
| MTM FX aggregation | -$1,621 | Daily HKD→USD vs bulk conversion |
| GBP face-value error | +$470 | AT.L buys in GBP treated as USD |
| Withholding tax | +$125 | Gross dividends vs net (by design) |
| Fee residual | -$82 | Likely GBP fees not converted |
| FX translation | -$54 | Statement FX gain not captured |
| Interest FX | -$47 | HKD interest daily vs bulk |
| HKD fee face-value | -$30 | Futures fees in HKD treated as USD |
| Trade rounding | +$55 | Minor FX conversion gain |
| **TOTAL** | **+$2,695** | Matches back-solve gap exactly |

Key validation: In-period USD trade sales match statement to the penny
($22,303.94 = $22,303.94). The normalizers are clean.

## Changes

### 1. Add date filtering — `scripts/ibkr_cash_backsolve.py`

Filter all event types to the statement period before summing.

**Date field names** (from `inputs/transaction_store.py`):
- FIFO transactions: `txn["date"]` — string `"YYYY-MM-DD..."`, slice `[:10]` for comparison
- Income events: `inc["date"]` — `datetime` object (line 1051: aliased from `event_date`)
- Provider flow events: `flow["date"]` — `datetime` object (line 1132: aliased from `event_date`)
- Futures MTM events: `mtm["date"]` — `datetime` object (from raw_data normalization)

**Filtering logic**:
```python
from datetime import date as date_type

period_start = date_type.fromisoformat(STATEMENT_PERIOD[0])
period_end = date_type.fromisoformat(STATEMENT_PERIOD[1])

def _in_period(d) -> bool:
    """Check if a date (str or datetime) falls within statement period."""
    if isinstance(d, str):
        d = date_type.fromisoformat(d[:10])
    elif hasattr(d, 'date'):
        d = d.date()
    return period_start <= d <= period_end
```

Don't modify `load_from_store()` — filter in the script after loading.
This avoids touching shared infrastructure for a diagnostic-only change.

Show pre-period excluded trade count and total impact for transparency.

### 2. Add FX conversion for non-USD amounts — `scripts/ibkr_cash_backsolve.py`

For each event with `currency != "USD"`, convert to USD using the FX rate
for that date.

**FX utilities available** (no new code needed):
- `fmp/fx.py`: `get_daily_fx_series(currency, start_date, end_date)` →
  `pd.Series` with `DatetimeIndex` and rates (currency→USD multiplier)
- `portfolio_risk_engine/providers.py`: `get_fx_provider()` → `FXProvider`
  with `get_daily_fx_series()` method

**Implementation pattern**:
```python
import pandas as pd
from fmp.fx import get_daily_fx_series

fx_cache: dict[str, pd.Series] = {}

def _fx_rate(currency: str, d) -> float:
    """Look up currency→USD rate for a given date.

    Args:
        currency: ISO currency code (e.g. "GBP", "HKD")
        d: date as str ("YYYY-MM-DD"), datetime, or date object
    """
    if currency == "USD":
        return 1.0
    if currency not in fx_cache:
        fx_cache[currency] = get_daily_fx_series(
            currency, STATEMENT_PERIOD[0], STATEMENT_PERIOD[1]
        )
    series = fx_cache[currency]
    # Normalize to pd.Timestamp
    if isinstance(d, str):
        ts = pd.Timestamp(d[:10])
    elif hasattr(d, 'date'):
        ts = pd.Timestamp(d.date())
    else:
        ts = pd.Timestamp(d)

    if ts in series.index:
        return float(series.loc[ts])
    # Forward-fill: use most recent available rate before this date
    idx = series.index.get_indexer([ts], method="ffill")
    if idx[0] >= 0:
        return float(series.iloc[idx[0]])
    # Pre-start fallback: use earliest available rate (back-fill)
    idx_bfill = series.index.get_indexer([ts], method="bfill")
    if idx_bfill[0] >= 0:
        return float(series.iloc[idx_bfill[0]])
    return 1.0  # absolute fallback — treat as USD with warning
```

**Edge case handling**:
- Weekends/holidays: `ffill` uses most recent prior trading day's rate
- Pre-start dates (before FX series begins): `bfill` uses first available rate
  (safe for this diagnostic — pre-start events are already filtered out by
  date filtering, so this is defensive only)
- Missing currency field: `.get("currency", "USD")` defaults to USD

**Apply to each event type**:

| Event Type | Currency Source | Date Source | Amount to Convert |
|------------|---------------|-------------|-------------------|
| FIFO trades | `txn.get("currency", "USD")` | `txn["date"]` (str) | `cash_impact` (qty*price ± fee) |
| Income | `inc.get("currency", "USD")` | `inc["date"]` (datetime) | `amount` |
| Provider flows | `flow.get("currency", "USD")` | `flow["date"]` (datetime) | `amount` |
| Futures MTM | `mtm.get("currency", "USD")` | `mtm["date"]` (datetime) | `amount` |

For trades, the entire cash impact is in the trade's currency (qty, price,
and fee are all in the same currency), so multiply the whole cash impact by
the FX rate.

### 3. Add per-currency breakdown to output

Show FX conversion summary so the impact is transparent:
```
FX conversion applied:
  GBP: 2 events, local -1,621.50 → USD -2,091.74 (delta -470.24)
  HKD: 87 events, local -25,424.41 → USD -3,308.39 (delta +22,116.02)
```

### 4. Show date-filter impact

Print both filtered and unfiltered totals for trades:
```
Date filter impact:
  Pre-period trades excluded: 16 trades, cash impact $3,878.79
  In-period trades: 48 trades, cash impact $6,716.59
```

## Files Modified

| File | Change |
|------|--------|
| `scripts/ibkr_cash_backsolve.py` | Add date filtering + FX conversion + per-currency breakdown |

No production code changes. No test changes. Diagnostic script only.

## Codex Review

- Round 1: **FAIL** (3 issues — wrong date field names, type handling, FX fallback)
- Round 2: **PASS** (all 3 issues fixed)

## Verification

1. `python3 scripts/ibkr_cash_backsolve.py` — runs without error
2. Approach 1 gap should drop from -$2,695 to ~$200-300
3. Per-currency breakdown should show GBP and HKD conversions
4. Pre-period exclusion should show ~$3,879 excluded
5. In-period USD trade totals should still match statement exactly ($22,303.94 sales)
