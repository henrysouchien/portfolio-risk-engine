# Futures Daily MTM Settlement for IBKR Realized Performance — COMPLETE

**Status**: Implemented in `3ce88f1c`. IBKR gap closed from 25pp to 2pp (-11.37% vs broker -9.35%).

## Context

IBKR realized performance shows +15.71% vs broker -9.35% (~25pp gap). Root cause: futures P&L is almost entirely missing from the NAV calculation.

**How IBKR actually works** (confirmed via new Flex StmtFunds data + EquitySummaryInBase):
- Futures positions have **$0 notional** in IBKR's equity summary (`commodities` column = 0 always)
- All futures P&L flows through **daily cash MTM settlement** (mark-to-market)
- Opening a futures position does NOT cost notional — it's margin-based
- Each day, the P&L difference settles directly into cash

**What our system currently does**:
1. Pre-multiplies futures qty by multiplier in `ibkr/flex.py:347` (ZF: 1 contract → qty=1000)
2. Suppresses futures notional from cash replay — fee-only (`realized_performance_analysis.py:1714-1725`)
3. Filters futures from position timeline (`realized_performance_analysis.py:1395`)
4. **Result**: Only commissions (~$40 total) flow through. Actual futures P&L (e.g., MHI -$30K Hang Seng crash on Apr 7) is completely lost.

**Fix**: Parse StmtFunds daily MTM settlements from Flex report, feed them into the cash replay as a new `FUTURES_MTM` event type. This replicates IBKR's own accounting: futures value through cash settlement, not position valuation.

**Key trades in this account**: MES (Feb-Mar), MGC (multiple round-trips Feb-May), ZF (Mar-Apr), MHI (Mar-Apr, massive -$34K loss).

## Architecture

IBKR-specific parsing in `ibkr/flex.py` → normalized MTM events flow through provider-agnostic pipeline → core `derive_cash_and_external_flows()` handles new `FUTURES_MTM` event type. Core engine stays provider-agnostic. Position timeline exclusion stays as-is (correct).

## Files to Modify

| File | Change |
|------|--------|
| `ibkr/flex.py` | Parse StmtFunds, add `normalize_flex_futures_mtm()`, update payload |
| `trading_analysis/data_fetcher.py` | Thread `ibkr_flex_futures_mtm` through payload |
| `trading_analysis/analyzer.py` | Accept + store new key |
| `providers/ibkr_transactions.py` | Forward `ibkr_flex_futures_mtm` + `stmtfunds_section_present` |
| `core/realized_performance_analysis.py` | Add `FUTURES_MTM` event type to cash replay, thread through 9 call sites with partitioning |
| `tests/ibkr/test_flex_futures_mtm.py` | Unit tests for StmtFunds parsing |
| `tests/core/test_realized_perf_futures_mtm.py` | Integration tests for cash replay with MTM |

## Codex Review Findings (incorporated below)

1. **Event routing**: FUTURES_MTM events must NOT have `is_futures=True` — otherwise they hit the futures trade branch (lines 1714-1725) and get misclassified. Set `is_futures=False` and handle via dedicated `elif event_type == "FUTURES_MTM"` in the non-futures else block.
2. **TYPE_ORDER**: Must add `"FUTURES_MTM"` to the sort-priority dict (same priority as INCOME).
3. **Call sites**: 9 (not 10) — all 9 should receive MTM events.
4. **Dedup key**: Strengthen to include raw symbol (contract-month form like "ZFM5") to avoid collapsing legitimate same-day entries.
5. **Missing StmtFunds diagnostics**: Propagate `stmtfunds_section_present` through fetch metadata and emit warning when section missing but futures trades exist.

## Change 1: Parse StmtFunds in `ibkr/flex.py`

### 1a: `normalize_flex_futures_mtm(raw_stmtfunds_rows)` — new function

Extract `assetCategory=FUT` rows with "Position MTM" in `activityDescription`. Skip commission/trade rows (already captured via Trade section).

**Input**: raw StmtFunds rows from `_extract_rows(report, "StmtFunds")`
**Output**: list of normalized dicts:
```python
{
    "provider": "ibkr_flex",
    "institution": "ibkr",
    "account_id": str,
    "date": datetime,              # from reportDate
    "symbol": str,                 # futures root (e.g., "ZF", "MHI", "MGC")
    "description": str,            # raw activityDescription
    "amount": float,               # signed MTM P&L
    "currency": str,               # settlement currency (USD, HKD, etc.)
    "transaction_id": str,         # synthetic dedup key
}
```

**Key logic**:
- Filter: `assetCategory == "FUT"` AND `activityDescription` contains "Position MTM"
- Skip: Buy/Sell rows (commission entries — already in Trade section)
- Dedup: StmtFunds has duplicate rows (one per currency segment). Use `(account_id, reportDate, raw_symbol, amount, currency)` as dedup key (raw_symbol = contract-month form like "ZFM5", NOT the stripped root), keep first occurrence.
- Symbol extraction: `symbol` field has contract-month format like "ZFM5" — strip to underlying root using existing futures contract spec lookup or regex (strip trailing month code + year digit).

### 1b: Update `fetch_ibkr_flex_payload()`

After existing CashTransaction/Transfer extraction (~line 840):
```python
raw_stmtfunds = _extract_rows(report, "StmtFunds") if "StmtFunds" in topics else []
payload["futures_mtm"] = normalize_flex_futures_mtm(raw_stmtfunds)
payload["stmtfunds_section_present"] = "StmtFunds" in topics
```

## Change 2: Thread through pipeline

### 2a: `trading_analysis/data_fetcher.py`

In the `fetch_ibkr_flex_payload()` wrapper (~line 136), add to return dict:
```python
"ibkr_flex_futures_mtm": list(payload.get("futures_mtm") or []),
```

Also add to `_empty_transaction_payload()` and `TransactionPayload` type.

### 2b: `providers/ibkr_transactions.py`

Forward the new keys from `fetch_ibkr_flex_payload()` return dict:
```python
"ibkr_flex_futures_mtm": list(payload.get("ibkr_flex_futures_mtm") or []),
```
Also forward `stmtfunds_section_present` into fetch metadata.

### 2c: `trading_analysis/analyzer.py`

Add `ibkr_flex_futures_mtm` parameter to `TradingAnalyzer.__init__()`. Store as `self.ibkr_flex_futures_mtm`.

## Change 3: Cash replay — `FUTURES_MTM` event type

### 3a: `derive_cash_and_external_flows()` — new parameter + event type

Add `futures_mtm_events: Optional[List[Dict[str, Any]]] = None` parameter.

Add `"FUTURES_MTM"` to TYPE_ORDER dict (~line 69). Priority 5 — **after BUY/COVER** so that same-day futures opens update `_futures_positions` before MTM processes (avoids false inferred flows when futures positions suppress inference):
```python
TYPE_ORDER = {
    "SELL": 0, "SHORT": 1, "INCOME": 2, "PROVIDER_FLOW": 2,
    "BUY": 3, "COVER": 4,
    "FUTURES_MTM": 5,  # After BUY/COVER — positions must be open before MTM settles
}
```

Build FUTURES_MTM events in the event list (alongside existing INCOME, PROVIDER_FLOW):
```python
for mtm in (futures_mtm_events or []):
    date = _to_datetime(mtm.get("date"))
    if date is None:
        continue
    amount = _as_float(mtm.get("amount"), 0.0)
    if amount == 0:
        continue
    events.append({
        "date": date,
        "event_type": "FUTURES_MTM",
        "amount": amount,
        "currency": str(mtm.get("currency") or "USD").upper(),
        "symbol": str(mtm.get("symbol") or "").strip().upper(),
        "is_futures": False,  # CRITICAL: must be False to avoid hitting futures trade branch
    })
```

Handle in the event processing loop — in the **non-futures else block** (lines 1726+) alongside INCOME and PROVIDER_FLOW. Since `is_futures=False`, it naturally falls into the else branch:
```python
elif event_type == "FUTURES_MTM":
    fx, missing_fx = _fx_with_futures_default(event.get("currency", "USD"), event["date"])
    if missing_fx:
        futures_missing_fx_count += 1
    cash += event["amount"] * fx
    futures_mtm_cash_impact_usd += event["amount"] * fx
```

**Critical**: FUTURES_MTM events must have `is_futures=False` to bypass the futures trade-processing block (lines 1714-1725). They are cash settlement events, not trade events. FX uses `_fx_with_futures_default()` (closure in scope) since currency may be HKD/EUR.

### 3b: New diagnostics

Add to replay_diagnostics:
- `futures_mtm_event_count`: count of MTM events processed
- `futures_mtm_cash_impact_usd`: total cash impact in base currency

### 3c: Thread `futures_mtm_events` to all 10 call sites

In `_analyze_realized_performance_single_scope()`, extract MTM events from payload:
```python
futures_mtm_events = list(payload.get("ibkr_flex_futures_mtm") or [])
```

Apply institution/account filters (same pattern as fifo_transactions filtering at lines 3161-3179).

**Partitioning for mixed-authority mode**: In the authoritative/out-of-window/fallback split (~lines 3890-3960), MTM events must be partitioned the same way as transactions and income. Since all MTM events come from `ibkr_flex`, partition by date against provider flow coverage windows:
- `authoritative_mtm`: MTM events within IBKR's authoritative window
- `out_of_window_mtm`: MTM events outside the window
- `fallback_mtm`: MTM events when IBKR has no coverage (shouldn't happen if StmtFunds present)

For the partition-per-slice fallback path (lines 4064-4073), add `"mtm": []` to partition rows and partition MTM events using the same `_partition_key_for_transaction()` logic (all MTM events are ibkr_flex provider).

Pass `futures_mtm_events=<appropriate_partition>` to all 9 `derive_cash_and_external_flows()` call sites:
- Line 3753 (inference-only): full `futures_mtm_events`
- Line 3819 (no-inference diagnostic): full `futures_mtm_events`
- Line 3843 (fallback): `fallback_mtm` only
- Line 3870 (composed simple): full `futures_mtm_events`
- Line 3963 (composed no-fallback): full `futures_mtm_events`
- Line 4042 (authoritative): `authoritative_mtm` only
- Line 4050 (out-of-window): `out_of_window_mtm` only
- Line 4067 (partition): partition-specific MTM events
- Line 4246 (observed-only): full `futures_mtm_events`

### 3e: Propagate `stmtfunds_section_present` through fetch metadata

Thread `stmtfunds_section_present` from `fetch_ibkr_flex_payload()` through `data_fetcher.py` and `providers/ibkr_transactions.py` into fetch metadata. In `_analyze_realized_performance_single_scope()`, emit warning when:
- `stmtfunds_section_present == False` AND futures trades exist in fifo_transactions
- This alerts users with older Flex query configs that futures P&L is missing

### 3d: Add MTM currencies to FX cache

In the currency collection section (~line 3200), add:
```python
for mtm in futures_mtm_events:
    ccy = str(mtm.get("currency") or "USD").upper()
    if ccy != "USD":
        currencies.add(ccy)
```

## Change 4: Tests

### 4a: `tests/ibkr/test_flex_futures_mtm.py`
- Parse StmtFunds rows with Position MTM → normalized output
- Skip Buy/Sell commission rows
- Dedup duplicate currency-segment rows
- Handle HKD/EUR currencies
- Handle missing/malformed rows gracefully

### 4b: `tests/core/test_realized_perf_futures_mtm.py`
- `derive_cash_and_external_flows()` with FUTURES_MTM events → cash balance changes correctly
- FX conversion for non-USD MTM events
- MTM events are NOT external flows (no contribution/withdrawal inference)
- Existing futures fee-only behavior unchanged for trade events
- Diagnostics populated correctly

## Verification

```bash
# 1. Unit + integration tests
python3 -m pytest tests/ibkr/test_flex_futures_mtm.py tests/core/test_realized_perf_futures_mtm.py -x -v

# 2. IBKR 2025 — should close the ~25pp gap significantly
python3 -c "
from mcp_tools.performance import _load_portfolio_for_performance
from core.realized_performance_analysis import analyze_realized_performance
user, uid, pd_, pr = _load_portfolio_for_performance(None, 'CURRENT_PORTFOLIO', use_cache=False, source='ibkr_flex', mode='realized')
r = analyze_realized_performance(pr, str(user), source='ibkr_flex')
twr = 1.0
for dt, v in sorted(r.monthly_returns.items()):
    if '2025' in str(dt):
        twr *= (1+v)
        print(f'  {dt}: {v*100:+.2f}%')
print(f'  2025 TWR: {(twr-1)*100:+.2f}% (broker: -9.35%)')
"

# 3. Schwab unchanged (no futures, no StmtFunds)

# 4. Full test suite
python3 -m pytest tests/ -x -q 2>&1 | tail -5
```

## Acceptance Gates

- IBKR March 2025: no longer +308%
- IBKR 2025 TWR: closer to broker -9.35% (within ±5pp = strong progress)
- Schwab accounts: unchanged
- All tests pass
- New diagnostics show futures_mtm_event_count > 0 and futures_mtm_cash_impact_usd matching expected P&L
