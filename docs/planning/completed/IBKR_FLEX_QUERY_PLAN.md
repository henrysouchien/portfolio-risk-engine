# IBKR Flex Query Trade Tracking Integration ✅ COMPLETED (2026-02-12)

## Context

We need historical IBKR trade data for P&L tracking (immediate use case: SLV June $30/$35 call spread from April-June 2025). Plaid's IBKR integration only returns ~1 week of transactions. IBKR's **Flex Query API** provides up to 2 years of trade history including full options metadata (strike, expiry, put/call, multiplier). `ib_async` (already a dependency) has `FlexReport` built in.

## Prerequisite (User)

Set up a Flex Query template in IBKR Client Portal:
1. Settings > Account > Reporting > Flex Queries
2. Create Activity Flex Query with Trades section selected
3. Enable Flex Web Service, generate a token
4. Note the Query ID and token → add to `.env` as `IBKR_FLEX_TOKEN` and `IBKR_FLEX_QUERY_ID`

## Implementation Steps

### Step 1: Settings (`settings.py`)

Add after existing IBKR block (line ~600):
```python
IBKR_FLEX_TOKEN = os.getenv("IBKR_FLEX_TOKEN", "")
IBKR_FLEX_QUERY_ID = os.getenv("IBKR_FLEX_QUERY_ID", "")
```

### Step 2: Shared Strike Normalization — `trading_analysis/symbol_utils.py` (NEW)

Extract a shared function used by both the Flex client and the existing `_parse_option_symbol()`:

```python
def normalize_strike(strike) -> str:
    """Canonical strike string: 30.0→"30", 2.5→"2p5", 2.50→"2p5".

    Accepts float or string (from regex capture). Strips trailing zeros
    before replacing '.' with 'p' to ensure cross-source consistency.
    """
    val = float(strike)
    if val == int(val):
        return str(int(val))
    # Python's %g format strips trailing zeros: 2.50 → "2.5"
    s = f"{val:g}"
    return s.replace('.', 'p')
```

Then patch `TradingAnalyzer._parse_option_symbol()` (analyzer.py:315-319) to use it:
```python
# Before: strike = strike_match.group(1).replace('.', 'p')
# After:
from trading_analysis.symbol_utils import normalize_strike
strike = normalize_strike(strike_match.group(1))
```

This ensures `$2.50` in a Plaid description and `2.5` from a Flex float both produce `"2p5"`.

### Step 3: Plaid Institution Metadata — `trading_analysis/models.py`

Add `institution` field to `PlaidTransaction` so dedup can scope to IBKR:

```python
@dataclass
class PlaidTransaction:
    # ... existing fields ...
    institution: Optional[str] = None  # NEW: from _institution tag in data_fetcher

    @classmethod
    def from_dict(cls, data):
        return cls(
            # ... existing fields ...
            institution=data.get('_institution'),  # NEW
        )
```

Then in `analyzer.py` Plaid normalization block, propagate to fifo_transactions:
```python
self.fifo_transactions.append({
    # ... existing fields ...
    '_institution': txn.institution,  # NEW: for dedup scoping
})
```

And add to `self.trades` (NormalizedTrade) too — either add `institution` field to NormalizedTrade or use a parallel tracking dict keyed by index.

### Step 4: Flex Client — NEW `services/ibkr_flex_client.py`

Core module:

- **`_build_option_symbol(underlying, put_call, strike, expiry)`** — Uses `normalize_strike()` from `symbol_utils.py` for cross-source consistency
- **`_map_trade_type(buy_sell, open_close)`** — Maps Flex fields to FIFO types:
  - BUY+O → BUY, SELL+O → SHORT, BUY+C → COVER, SELL+C → SELL
  - Stocks without open/close: BUY → BUY, SELL → SELL
- **`normalize_flex_trades(flex_trades)`** — Converts `FlexReport.extract('Trade')` objects to FIFO dicts
- **`fetch_ibkr_flex_trades(token, query_id, path)`** — Downloads via `FlexReport(token=..., queryId=...)` or loads from file. **Fail-open**: returns `[]` if credentials missing or download fails (logged as warning). Only raises on explicit `path` not found.

#### Normalization Rules
```python
quantity   = abs(raw_quantity)          # always positive
fee        = abs(raw_commission)        # IBKR commissions often negative
price      = tradePrice * multiplier    # options only (assetCategory=="OPT" AND multiplier>1)
                                        # stocks: price = tradePrice (no multiplier)
account_id = getattr(trade, 'accountId', '')  # for dedup scoping
```

#### Output Dict Format
```python
{
    'symbol': str,             # canonical option or stock symbol
    'type': str,               # BUY | SELL | SHORT | COVER
    'date': datetime,          # parsed from tradeDate
    'quantity': float,         # abs(raw)
    'price': float,            # per-contract for options, per-share for stocks
    'fee': float,              # abs(commission)
    'currency': str,           # e.g., "USD"
    'source': 'ibkr_flex',
    'transaction_id': str,     # "ibkr_flex_{tradeID}"
    'is_option': bool,
    'account_id': str,         # IBKR account ID
    '_institution': 'ibkr',    # for dedup scoping (matches Plaid pattern)
}
```

### Step 5: Data Fetcher (`trading_analysis/data_fetcher.py`)

- Add `fetch_ibkr_flex_trades()` wrapper. **Fail-open**: if `IBKR_FLEX_TOKEN` or `IBKR_FLEX_QUERY_ID` are empty, return `[]` silently.
- Update `fetch_all_transactions()` to include `ibkr_flex_trades` key (backward compatible)

### Step 6: Analyzer Integration (`trading_analysis/analyzer.py`)

- Add `ibkr_flex_trades` param to `TradingAnalyzer.__init__()` (Optional, default None)
- Add IBKR Flex normalization block in `_normalize_data()` after the Plaid block. Populates **both** `self.trades` and `self.fifo_transactions`.
- Add `_deduplicate_transactions()` at end of `_normalize_data()`.

#### Deduplication Rules

**Scope**: Only dedup Plaid transactions identified as IBKR against IBKR Flex data. IBKR detection uses a normalized allowlist check:
```python
_IBKR_INSTITUTION_NAMES = {"interactive brokers", "ibkr"}

def _is_ibkr_institution(institution: str) -> bool:
    return any(name in (institution or "").lower() for name in _IBKR_INSTITUTION_NAMES)
```
Non-IBKR Plaid transactions (Merrill, etc.) are never touched.

**Match key**: `(symbol, trade_type, date_str, quantity, round(price, 2), currency)` — includes trade type, price, and currency. Uses date string (not full timestamp) since Plaid `transaction_datetime` is often null for IBKR.

**Cardinality-aware matching** (prevents over-removal of legitimate repeated fills):
```python
from collections import Counter

# 1. Build Counter of Flex keys (not a set — preserves multiplicity)
flex_key_counts = Counter()
for txn in self.fifo_transactions:
    if txn.get('source') == 'ibkr_flex':
        flex_key_counts[_make_dedup_key(txn)] += 1

# 2. Walk Plaid-IBKR entries; remove only while counter > 0
indices_to_remove = []
for i, txn in enumerate(self.fifo_transactions):
    if txn.get('source') != 'plaid' or not _is_ibkr_institution(txn.get('_institution', '')):
        continue
    key = _make_dedup_key(txn)
    if flex_key_counts.get(key, 0) > 0:
        flex_key_counts[key] -= 1
        indices_to_remove.append(i)

# 3. Remove from BOTH self.fifo_transactions and self.trades by index
```
This ensures that if Flex has 1 fill at a given key and Plaid has 2, only 1 Plaid row is removed.

**Preference**: Keep IBKR Flex version (has explicit `openCloseIndicator`), remove Plaid version.

### Step 7: Update Callers

Pass `ibkr_flex_trades=data.get('ibkr_flex_trades')` to `TradingAnalyzer()` in all call sites. For each caller, here's the exact change:

#### `run_trading_analysis.py:503`
```python
analyzer = TradingAnalyzer(
    plaid_securities=data.get('plaid_securities'),
    plaid_transactions=data.get('plaid_transactions'),
    snaptrade_activities=data.get('snaptrade_activities'),
    ibkr_flex_trades=data.get('ibkr_flex_trades'),  # NEW
)
```
Also update no-data check (~line 498) to include Flex count, and add `"ibkr_flex"` to `--source` argparse choices.

Add source branch:
```python
elif args.source == "ibkr_flex":
    from trading_analysis.data_fetcher import fetch_ibkr_flex_trades as _fetch_flex
    data = {'plaid_securities': [], 'plaid_transactions': [],
            'snaptrade_activities': [], 'ibkr_flex_trades': _fetch_flex()}
```

#### `mcp_tools/tax_harvest.py:143`
```python
analyzer = TradingAnalyzer(
    plaid_securities=payload.get("plaid_securities", []),
    plaid_transactions=payload.get("plaid_transactions", []),
    snaptrade_activities=payload.get("snaptrade_activities", []),
    ibkr_flex_trades=payload.get("ibkr_flex_trades"),  # NEW
    use_fifo=True,
)
```
Add `"ibkr_flex"` to source param enum in tool description (~line 622).

Add fetch branch in `_fetch_transactions_for_source()`:
```python
elif source == "ibkr_flex":
    from trading_analysis.data_fetcher import fetch_ibkr_flex_trades as _fetch_flex
    return {"plaid_securities": [], "plaid_transactions": [],
            "snaptrade_activities": [], "ibkr_flex_trades": _fetch_flex()}
```

#### `core/realized_performance_analysis.py:612`
Same pattern — add `ibkr_flex_trades` kwarg and `"ibkr_flex"` source branch in its `_fetch_transactions_for_source()`.

#### `mcp_tools/performance.py`
Add `"ibkr_flex"` to the source `Literal` type, help text, and pass it through to the realized-performance path unchanged.

#### `trading_analysis/main.py:288`
Add `ibkr_flex_trades` kwarg if raw-data path is used.

### Step 8: Exploration Script — NEW `scripts/fetch_ibkr_trades.py`

Standalone script (like `explore_transactions.py`) to fetch and display IBKR trades:
- `--path` flag to load from saved XML
- `--save-xml` to cache raw XML
- `--raw` to show raw Flex object attributes
- Tabular output of normalized trades

### Step 9: Unit Tests — NEW `tests/services/test_ibkr_flex_client.py`

Targeted tests (no live IBKR connection needed — use mock/fixture data):
- **`test_build_option_symbol`**: integer strike, decimal strike (`2.5` → `2p5`), missing putCall
- **`test_normalize_strike_parity`**: same strike from Flex float and Plaid description produce identical symbol (e.g., `normalize_strike(2.5)` == regex-captured `"2.50"` after normalization → both `"2p5"`)
- **`test_map_trade_type`**: all 6 combos (BUY/SELL × O/C/empty), unmappable input returns None
- **`test_normalize_pricing`**: stock price passthrough, option price × multiplier, guard against double-multiply when multiplier=1
- **`test_fee_sign_normalization`**: negative commission → positive fee
- **`test_quantity_sign_normalization`**: negative quantity → positive
- **`test_dedup_scoped_to_ibkr_plaid`**: non-IBKR Plaid trades preserved, IBKR Plaid trades deduped
- **`test_dedup_preserves_round_trips`**: same-day BUY+SELL of same symbol not collapsed (different trade_type in key)
- **`test_dedup_preserves_different_currencies`**: same symbol/qty but different currency not collapsed
- **`test_dedup_consistent_across_trades_and_fifo`**: after dedup, `self.trades` and `self.fifo_transactions` have same count
- **`test_fetch_fail_open`**: missing credentials returns `[]`, no exception

## Design Decisions

- **Legs stay separate** — each option leg is a separate FIFO transaction. The SLV spread produces `SLV_C30_250620` (LONG) and `SLV_C35_250620` (SHORT), tracked independently. Spread-level P&L = sum of legs.
- **No new DB tables** — transactions stay ephemeral (re-fetchable from Flex Query)
- **No new packages** — `ib_async.FlexReport` handles download + XML parsing
- **Fail-open** — missing Flex credentials or download errors return `[]` with a warning log. Existing flows unaffected.
- **Shared strike normalization** — single `normalize_strike()` function used by both Flex builder and existing `_parse_option_symbol()`. Strips trailing zeros so `$2.50` and `2.5` both produce `"2p5"`.
- **Deduplication scoped to IBKR** — only Plaid transactions with `_institution` containing "Interactive Brokers" are candidates. Match key includes `(symbol, trade_type, date_str, quantity, round(price,2), currency)`. Operates on both `self.trades` and `self.fifo_transactions` for consistency.

## Files Modified/Created

| File | Action |
|------|--------|
| `settings.py` | Add 2 env vars |
| `trading_analysis/symbol_utils.py` | **NEW** — shared `normalize_strike()` |
| `trading_analysis/models.py` | Add `institution` field to `PlaidTransaction` |
| `services/ibkr_flex_client.py` | **NEW** — core Flex download + normalization |
| `trading_analysis/data_fetcher.py` | Add `fetch_ibkr_flex_trades()`, update `fetch_all_transactions()` |
| `trading_analysis/analyzer.py` | Add `ibkr_flex_trades` param, normalization block, dedup, use `normalize_strike()` |
| `run_trading_analysis.py` | Pass `ibkr_flex_trades`, update source choices + no-data check |
| `mcp_tools/tax_harvest.py` | Pass `ibkr_flex_trades`, add source filter branch |
| `core/realized_performance_analysis.py` | Pass `ibkr_flex_trades`, add source filter branch |
| `mcp_tools/performance.py` | Add `"ibkr_flex"` to source Literal + pass-through |
| `scripts/fetch_ibkr_trades.py` | **NEW** — exploration script |
| `tests/services/test_ibkr_flex_client.py` | **NEW** — 11 unit tests |

## Verification

1. Run `python3 -m pytest tests/services/test_ibkr_flex_client.py -v` — all unit tests pass
2. Run `python3 scripts/fetch_ibkr_trades.py --path <saved_flex_xml>` to test with real data
3. Verify SLV spread produces two symbols: `SLV_C30_250620` (BUY) and `SLV_C35_250620` (SHORT)
4. Run `python3 run_trading_analysis.py` with Flex data — confirm FIFO matches and P&L
5. Run existing tests: `python3 -m pytest tests/test_fmp_migration.py tests/core/test_realized_performance_analysis.py -v` — no regressions

## Codex Review History

### Review 1 (2026-02-10)
Verdict: **REVISE** — 4 HIGH, 3 MED, 1 LOW

### Review 2 (2026-02-10)
Verdict: **REVISE** — 2 HIGH, 2 MED

Issues addressed in this revision:
- [HIGH] Plaid institution metadata lost in PlaidTransaction → Added `institution` field to PlaidTransaction, propagated through normalization
- [HIGH] Strike normalization inconsistency → Created shared `normalize_strike()` in `symbol_utils.py`, patches both Flex builder and existing parser
- [MED] Dedup key missing account/currency → Added `currency` to match key
- [MED] Per-caller fetch logic unspecified → Added exact branch code for each caller (run_trading_analysis.py, tax_harvest.py, realized_performance_analysis.py)

### Review 3 (2026-02-10)
Verdict: **REVISE** — 1 HIGH, 2 MED

Issues addressed in this revision:
- [HIGH] Dedup not cardinality-aware → Changed from set to Counter; decrement on each removal so repeated legitimate fills preserved
- [MED] Institution match brittle → Added normalized allowlist (`{"interactive brokers", "ibkr"}`) with lowered comparison
- [MED] performance.py source validation omitted → Added `"ibkr_flex"` to source Literal + pass-through + file list
