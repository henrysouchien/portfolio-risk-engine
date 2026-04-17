# IBKR Statement CSV Import — Comprehensive Plan

**Status:** PLANNED (v6 — addresses five rounds of Codex review findings)
**Priority:** High — closes the TWR gap (5.76% vs IBKR's 0.29%)
**Created:** 2026-03-07
**Related:** `DUAL_CASH_ANCHOR_PLAN.md`, `STATEMENT_START_CASH_FIX_PLAN.md`, `IBKR_NAV_GAP_FIX_PLAN.md`

---

## 1. Problem Statement

The realized performance engine TWR is 5.76% vs IBKR's official 0.29% (gap = 5.47pp). Two root causes:

**A. Missing non-trade cash events ($3,789):**

| Event Type | Amount | Source |
|-----------|--------|--------|
| Cash Settling MTM (futures) | -$3,588.60 | `cash_report__all.csv` |
| Broker Interest | -$261.84 | `interest__all.csv` |
| Other Fees | -$164.00 | `fees__all.csv` |
| Dividends | +$168.47 | `dividends__all.csv` |
| Payment In Lieu | +$13.94 | `dividends__all.csv` |
| Transaction Fees | -$11.04 | Commissions (already in trades) |
| Cash FX Gain/Loss | +$53.88 | Accounting adjustment |
| **Net missing** | **-$3,789.19** | |

**B. Trade cash calculation discrepancy (~$4,821):**
Engine's replay derives trade cash from `price × quantity` (nav.py:317). The statement CSV provides `proceeds` which is the IBKR-authoritative trade cash amount. However, if our normalized prices are correct (per-contract for options, per-share for stocks), `price × quantity` should reproduce `proceeds` exactly. The discrepancy comes from incorrect option multiplier handling and futures notional, which statement data with correct `t_price` values fixes. We do NOT need a separate `proceeds` field — correct prices and multipliers are sufficient.

**C. Cash anchor drift ($8,611):**
Back-solving inception cash from ending cash minus 12-month replay accumulates $8,611 of drift. The DUAL_CASH_ANCHOR_PLAN addresses this separately but depends on complete replay from statement data.

## 2. Data Source

IBKR Activity Statement CSV, pre-materialized at:
```
docs/planning/performance-actual-2025/ibkr_statement_frames/
  U2471778_20250401_20260303/tables/
    trades__all.csv          # 51 Order rows (stocks, options, futures, forex)
    interest__all.csv        # 23 rows (HKD + USD debit interest)
    dividends__all.csv       # 27 rows (dividends + payment in lieu)
    fees__all.csv            # 27 rows (data subscription fees)
    cash_report__all.csv     # 40 rows (start/end balances per currency)
    financial_instrument_information__all.csv  # ~37 rows (exchange, underlying, multiplier per instrument)
```

**Verified CSV formats** (from actual file inspection):

| CSV | Key Columns | Row Filter | Notes |
|-----|------------|------------|-------|
| `trades__all.csv` | `datadiscriminator, asset_category, currency, symbol, date_time, quantity, t_price, proceeds, comm_fee, code, notional_value` | `row_kind=Data AND datadiscriminator=Order` | quantity is signed; code: O/C/Ep/Ex; date_time: `"YYYY-MM-DD, HH:MM:SS"` |
| `interest__all.csv` | `currency, date, description, amount` | `row_kind=Data AND currency NOT IN (Total, Total in USD, Total Interest in USD)` | Negative = debit; HKD + USD |
| `dividends__all.csv` | `currency, date, description, amount` | `row_kind=Data AND currency != Total` | Description has `SYMBOL(CUSIP)` prefix; "Payment in Lieu" in description |
| `fees__all.csv` | `subtitle, currency, date, description, amount` | `row_kind=Data AND subtitle != Total` | Negative amounts; data subscriptions |
| `cash_report__all.csv` | `currency_summary, currency, total, securities, futures` | `row_kind=Data` | "Starting Cash" / "Ending Cash" rows |

**Trade type derivation** (verified against actual data):

| Quantity | Code | Meaning | TradeType | Example |
|----------|------|---------|-----------|---------|
| > 0 | O | Buy to open | BUY | AAPL +1 O |
| < 0 | O | Sell to open (short) | SHORT | SLV 35C -1 O |
| < 0 | C | Sell to close | SELL | CBL -100 C |
| > 0 | C | Buy to close (cover) | COVER | EL +3 C |
| < 0 | C;Ep | Long option expired | SELL (option_expired) | NMM C70 -1 C;Ep |
| > 0 | C;Ep | Short option expired | COVER (option_expired) | SLV 35C +1 C;Ep |
| < 0 | C;O;P | Sell+reopen partial | SELL | CUBI -100 C;O;P |
| > 0 | C | Buy to close | COVER | CUBI +50 C |
| +100 | Ex;O | Exercise into stock | BUY (is_exercise) | SLV +100 Ex;O |
| -1 | C;Ex | Assignment out | SELL (is_exercise) | SLV C30 -1 C;Ex |

**Option symbol format** (statement vs canonical):
```
Statement:  "NMM 16JAN26 70 C"
Canonical:  "NMM_C70_260116"     (matches ibkr_flex)
Regex:      ^(?P<underlying>[A-Z0-9.]+)\s+(?P<day>\d{2})(?P<month>[A-Z]{3})(?P<year>\d{2})\s+(?P<strike>[\d.]+)\s+(?P<right>[CP])$
```

**Option price convention** (verified):
- `t_price` = per-share (e.g., NXT C30: t_price=11.51)
- `proceeds` = per-contract = qty × t_price × 100 (NXT: proceeds=-1151)
- ibkr_flex stores prices per-contract (×100 at `flex.py:356`)
- Statement normalizer must multiply t_price × 100 to match ibkr_flex convention

## 3. Architecture

### 3.1 Existing Flow (ibkr_flex)

```
┌─────────────────────────────────────────────────────────────────────┐
│ IBKR Flex API                                                       │
│   → fetch_ibkr_flex_payload() in data_fetcher.py                    │
│   → Returns: ibkr_flex_trades, ibkr_flex_cash_rows,                │
│              ibkr_flex_futures_mtm, ibkr_flex_option_prices         │
└──────────────────────┬──────────────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ _ingest_transactions_inner() in mcp_tools/transactions.py           │
│   provider_rows["ibkr_flex"] = ibkr_flex_trades + ibkr_flex_cash   │
│   → store.store_raw_transactions()                                  │
│   → store.normalize_batch() → IBKRFlexNormalizer                    │
└──────────────────────┬──────────────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ load_from_store() in transaction_store.py                            │
│   → load_fifo_transactions()     (normalized_transactions table)    │
│   → load_income_events()         (normalized_income table)          │
│   → load_provider_flow_events()  (provider_flow_events table)       │
│   → load_futures_mtm()           (raw ibkr_flex_mtm rows)           │
│   → load_fetch_metadata()        (ingestion_batches table)          │
│   Returns: {fifo_transactions, income_provider, flow_events, ...}   │
└──────────────────────┬──────────────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ _analyze_realized_performance_single_scope() in engine.py           │
│   → derive_cash_and_external_flows(fifo_txns, income, flows, mtm)  │
│   → compute_monthly_nav(position_timeline, cash_snapshots)          │
│   → compute_twr_monthly_returns()                                   │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 New Flow (ibkr_statement)

```
┌─────────────────────────────────────────────────────────────────────┐
│ IBKR Activity Statement CSVs (local files)                          │
│   → parse_ibkr_statement(csv_dir) in inputs/importers/              │
│   → Returns: {trades, interest, dividends, fees, cash_report,       │
│               account_id, period}                                   │
└──────────────────────┬──────────────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ fetch_provider_transactions(provider="ibkr_statement", csv_dir=...)         │
│   OR _ingest_transactions_inner() (programmatic)                    │
│                                                                      │
│   Flatten parsed data into raw rows (ALL under one provider):       │
│     provider_rows["ibkr_statement"] = [                             │
│       {_row_type: "trade", ...t} for t in trades                    │
│     ] + [                                                            │
│       {_row_type: "interest"|"dividend"|"fee", ...r} for cash rows  │
│     ]                                                                │
│   → store.store_raw_transactions()    (single provider key)         │
│   → store.normalize_batch() → IBKRStatementNormalizer               │
│     outputs: fifo_transactions + income_events                      │
│   (NO provider flow events — income path only)                      │
│                                                                      │
│   → Store cash_report as statement_cash in ibkr_statement batch     │
│     metadata (engine reads from ibkr_statement metadata rows too)   │
└──────────────────────┬──────────────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ load_from_store(source="ibkr_flex")                                  │
│   → provider IN ("ibkr_flex", "ibkr_statement") for FIFO + income  │
│   → fifo_transactions: flex + statement rows merged from DB         │
│   → Cross-provider dedup applied post-load                          │
│   → Income: ibkr_flex + ibkr_statement merged (deduped dividends)  │
│   → fetch_metadata: load BOTH ibkr_flex AND ibkr_statement batches │
│   → Provider flows: load ibkr_flex ONLY (statement has none)        │
│   → Futures MTM: from ibkr_flex_mtm only (unchanged)               │
└──────────────────────┬──────────────────────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│ Engine gets complete data:                                           │
│   - All trades (flex + statement gap-fill, deduped)                 │
│   - Interest/fees as income events → INCOME in cash replay          │
│   - Statement dividends fill income gaps (deduped vs flex divs)     │
│   - Futures MTM from ibkr_flex_mtm (daily granularity)             │
│   - Cash anchor from statement_cash in ibkr_statement metadata      │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.3 Key Design Decisions

**D1: ibkr_statement is a SEPARATE provider in the DB, not a replacement for ibkr_flex.**
- ALL rows (trades + interest + dividends + fees) stored as `provider="ibkr_statement"` in raw/normalized tables
- **Single provider key** — no split into `ibkr_statement_cash`. Rows carry a `_row_type` field to distinguish trades from cash events during normalization
- ibkr_flex continues to work independently
- Statement supplements flex (fills gaps, adds non-trade events)
- This preserves all existing ibkr_flex functionality and allows independent testing

**D2: load_from_store uses `provider IN ("ibkr_flex", "ibkr_statement")` when source="ibkr_flex".**
- `_normalized_provider_filter("ibkr_flex")` currently returns `"ibkr_flex"`, filtering to flex-only
- **Change**: Return `("ibkr_flex", "ibkr_statement")` when source is `"ibkr_flex"`, then apply cross-provider dedup post-load
- DB queries modified to accept `tuple[str, ...]` providers: `provider IN %s` instead of `provider = %s`
- This scopes to exactly the two IBKR providers — does NOT widen to Plaid/Schwab/SnapTrade
- When `source=None/"all"`, `provider=None` (existing behavior, loads all — includes statement automatically)
- **ibkr_statement is NOT a valid standalone source** — it always loads alongside ibkr_flex. No `source="ibkr_statement"` in performance/analysis tools

**D3: Non-trade cash events go through income path ONLY — no provider flows.**
- Interest → `NormalizedIncome(income_type="interest")` → `income_with_currency` in cash replay → `INCOME` event
- Fees → `NormalizedIncome(income_type="fee")` → same path (negative amounts)
- Dividends → `NormalizedIncome(income_type="dividend")` → same path
- Payment in lieu → `NormalizedIncome(income_type="payment_in_lieu")` → same path
- **NO provider flow events from statement** — this avoids triggering provider-flow authority mode which could suppress external-flow inference (Codex finding #2)
- The `INCOME` event handler in `derive_cash_and_external_flows()` (nav.py:196-207) adds to cash with FX

**D4: Futures MTM continues from ibkr_flex_mtm, not from statement.**
- Statement cash report shows cumulative MTM (-$3,588.60) but NOT daily breakdowns
- ibkr_flex_mtm already has daily MTM events (used via `FUTURES_MTM` event type in nav.py:226-244)
- No changes needed to futures MTM pipeline

**D5: Cash anchor metadata is stored on the ibkr_statement batch's own metadata row.**
- During ibkr_statement ingestion, `statement_cash` is stored in the ibkr_statement batch's `fetch_metadata` field
- **Critical:** `_statement_cash_from_metadata()` (engine.py:1899) reads from `provider_fetch_metadata`, but this variable is filtered to `enabled_provider_flow_sources` at engine.py:651-654. Since `ibkr_statement` is NOT a flow source, its metadata gets dropped before reaching the cash anchor function
- **Fix:** Save unfiltered metadata (`all_fetch_metadata = provider_fetch_metadata`) BEFORE the provider-flow-source filter. Pass `all_fetch_metadata` to `_statement_cash_from_metadata()` instead of the filtered list. Then broaden the provider check to include `"ibkr_statement"`
- This is durable: a later ibkr_flex auto-refresh cannot overwrite or hide the statement metadata since it lives on a different provider's batch
- No need for `update_ibkr_flex_statement_cash()` — standard `update_batch_status(fetch_metadata=...)` on the ibkr_statement batch is sufficient

**D6: Forex trades are filtered out (not normalized).**
- `asset_category="Forex"` trades (GBP.HKD, USD.HKD) are FX artifacts
- Normalizer skips them entirely

**D7: The normalizer receives flat rows with `_row_type` discriminator.**
- All rows stored under `provider="ibkr_statement"` carry `_row_type` (one of: `"trade"`, `"interest"`, `"dividend"`, `"fee"`)
- `normalize_batch()` loads raw rows for the batch, passes them to `IBKRStatementNormalizer.normalize()` which separates by `_row_type`
- This matches the existing pattern: ibkr_flex uses `_looks_like_ibkr_cash_row()` to split trade vs cash rows within one provider

**D8: ibkr_statement is NOT added to `_CONCRETE_PROVIDERS` or `_REFRESH_PROVIDERS`.**
- `ensure_store_fresh()` iterates `_CONCRETE_PROVIDERS` and calls `_ingest_transactions_inner()` for each
- ibkr_statement requires a `csv_dir` parameter — auto-refresh without it would fail
- ibkr_statement is manual-ingest only (via MCP tool with explicit csv_dir)
- This avoids the auto-refresh crash (Codex finding #7)

**D9: Income-income dedup for dividends across flex and statement.**
- Both ibkr_flex and ibkr_statement may produce dividend income for the same payment
- Dedup at load time via `(symbol, date, abs(amount), currency, account_id)` key — 5 fields
- `account_id` included to prevent false-matches across multi-account setups
- Flex income wins on overlap (richer metadata)
- This prevents double-counting (Codex finding #5)

**D10: Fee amounts preserve CSV sign — no forced negative.**
- `fees__all.csv` contains both debits (negative) and credits/reversals (positive)
- Example: `US Securities Snapshot...for Apr 2025` has both `-10` (charge) and `+10` (reversal)
- The normalizer preserves the sign from the CSV as-is
- Forcing all fees negative would overstate fee drag

## 4. Phases

### Phase 1: CSV Parser + Normalizer

**Goal:** Parse materialized IBKR statement CSVs and normalize into canonical structures. Standalone — no database or engine changes.

#### 4.1 New Files

**`inputs/importers/__init__.py`** — Package init

**`inputs/importers/ibkr_statement.py`** — CSV parser

```python
def parse_ibkr_statement(csv_dir: str) -> dict[str, Any]:
    """Parse materialized IBKR statement CSV directory.

    Args:
        csv_dir: Path to directory containing *__all.csv files

    Returns dict with keys:
        trades: list[dict]           — from trades__all.csv (Data+Order rows only)
        interest: list[dict]         — from interest__all.csv (Data rows, valid dates only)
        dividends: list[dict]        — from dividends__all.csv (Data rows, symbol extracted)
        fees: list[dict]             — from fees__all.csv (Data rows, non-total only)
        cash_report: list[dict]      — from cash_report__all.csv (Data rows)
        instrument_info: dict        — from financial_instrument_information__all.csv
                                       keyed by symbol → {listing_exch, underlying, multiplier, conid, ...}
        account_id: str              — from directory name (e.g., "U2471778")
        period: dict                 — {start_date, end_date} from directory name
    """
```

Implementation details:
- `_read_csv(csv_dir, filename)` — Read CSV with `csv.DictReader`
- `_is_data_row(row)` — Filter `row_kind == "Data"`
- `_parse_trades(csv_dir)` — Filter `datadiscriminator == "Order"`, parse datetime/quantity/prices
- `_parse_interest(csv_dir)` — Skip "Total" currency rows, parse dates, skip zero amounts
- `_parse_dividends(csv_dir)` — Extract symbol from description, flag payment-in-lieu
- `_parse_fees(csv_dir)` — Skip total subtitle rows
- `_parse_cash_report(csv_dir)` — Return all data rows
- `_parse_instrument_info(csv_dir)` — Parse `financial_instrument_information__all.csv` into `{symbol: {listing_exch, underlying, multiplier, conid, asset_category, ...}}`. Handles comma-separated multipliers (e.g., `"1,000"` → 1000)
- `_parse_directory_name(csv_dir)` — Extract account_id and date range from path
- `_parse_datetime(value)` — Handle `"YYYY-MM-DD, HH:MM:SS"` format
- `_safe_float(value)` — Handle commas in numbers

**`providers/normalizers/ibkr_statement.py`** — Normalizer

```python
class IBKRStatementNormalizer:
    provider_name = "ibkr_statement"

    def normalize(
        self,
        raw_data: Any,                               # list[dict] — flat rows with _row_type
        security_lookup: dict[str, Any] | None = None,
    ) -> tuple[list[NormalizedTrade], list[NormalizedIncome], list[dict[str, Any]]]:
        """→ (trades, income_events, fifo_transactions)

        Each row has _row_type: "trade"|"interest"|"dividend"|"fee".
        Separates by _row_type internally, then normalizes each group.
        """
```

**`inputs/importers/ibkr_statement.py`** — also provides a flatten helper:

```python
def flatten_for_store(parsed: dict, account_id: str) -> list[dict]:
    """Convert parse_ibkr_statement() output into flat rows with _row_type.

    Used by _ingest_transactions_inner() to prepare rows for raw storage.
    The same flat format is what IBKRStatementNormalizer.normalize() receives.
    Trade rows get _instrument_info injected for symbol resolution.
    """
    instrument_info = parsed.get("instrument_info") or {}
    trade_rows = []
    for t in parsed["trades"]:
        sym = t.get("symbol", "")
        info = instrument_info.get(sym, {})
        trade_rows.append({
            "_row_type": "trade", "_account_id": account_id,
            "_instrument_info": info, **t,
        })
    return (
        trade_rows
        + [{"_row_type": "interest", "_account_id": account_id, **r} for r in parsed["interest"]]
        + [{"_row_type": "dividend", "_account_id": account_id, **r} for r in parsed["dividends"]]
        + [{"_row_type": "fee", "_account_id": account_id, **r} for r in parsed["fees"]]
    )
```

Trade normalization (`_normalize_trade()`):
- Determine trade type from `quantity` sign + `code` field (see table in §2)
- Build instrument lookup from `financial_instrument_information__all.csv` (parsed in `parse_ibkr_statement()`):
  - This CSV has `listing_exch`, `underlying`, `multiplier`, `conid` for every instrument
  - Parser builds `instrument_info: dict[str, dict]` keyed by symbol → `{listing_exch, underlying, multiplier, ...}`
  - Normalizer uses this lookup for exact Flex-compatible symbol resolution:
- Normalize symbol:
  - Stocks: strip trailing `.`, look up `listing_exch` from instrument info, map to MIC via `ibkr_exchange_to_mic` (same mapping ibkr_flex uses), call `resolve_fmp_ticker(base_symbol, currency, exchange_mic)`. Example: `AT.` + `listing_exch=LSE` → `exchange_mic=XLON` → `AT.L`. This is exactly the ibkr_flex path (flex.py:331-346).
  - Options: regex parse `"NMM 16JAN26 70 C"` → `"NMM_C70_260116"`
  - Futures: use `underlying` from instrument info (e.g., `MGCM5` → `MGC`), matching flex.py:320-321 which resolves to `underlyingSymbol`
  - Forex: return None (filtered)
- Price:
  - Stocks: `t_price` as-is (per-share)
  - Options: `t_price × 100` (per-share → per-contract to match ibkr_flex)
  - Futures: `t_price` as-is (notional handling done by engine)
- Build `contract_identity` for options: `{underlying, expiry, strike, right, multiplier: 100}`
- Build `contract_identity` for futures: `{symbol, multiplier}` — multiplier from instrument info CSV (`financial_instrument_information__all.csv` has `multiplier` column). Fallback: `abs(notional_value) / (abs(quantity) * t_price)`. Example: MGCM5 instrument info has `multiplier=10`
- Futures quantity: multiply by contract multiplier to match ibkr_flex convention (`flex.py:348-350` does `quantity *= multiplier` for futures)
- Set `source="ibkr_statement"`, `_institution="ibkr"`
- Output: `NormalizedTrade` + FIFO dict (same shape as ibkr_flex output)

Income normalization:
- `_normalize_interest()` → `NormalizedIncome(symbol="CASH", income_type="interest", amount=signed_amount)`
- `_normalize_dividend()` → `NormalizedIncome(symbol=extracted_ticker, income_type="dividend"|"payment_in_lieu")`
- `_normalize_fee()` → `NormalizedIncome(symbol="CASH", income_type="fee", amount=csv_sign_preserved)` — positive credits/reversals kept as-is (D10)

#### 4.2 Modified Files

**`providers/normalizers/__init__.py`** — Register `IBKRStatementNormalizer` in exports

#### 4.3 Tests

**`tests/importers/__init__.py`** — Package init

**`tests/importers/test_ibkr_statement.py`** — Tests against real CSV data

Parser tests (~13):
- `test_parse_returns_expected_keys` — All required keys present
- `test_account_id_parsed` — "U2471778"
- `test_period_parsed` — start=2025-04-01, end=2026-03-03
- `test_trades_parsed` — Non-empty, required fields, datetime not None
- `test_trades_no_subtotal_or_total` — Only Order rows
- `test_stock_trades_present` — At least one Stocks trade
- `test_option_trades_present` — At least one option trade
- `test_futures_trades_present` — At least one Futures trade
- `test_interest_parsed` — Non-empty, includes USD rows
- `test_dividends_parsed` — Non-empty, NVDA symbol extracted
- `test_dividends_payment_in_lieu_flagged` — At least one PIL row
- `test_fees_parsed` — Non-empty, total ≈ -$164
- `test_cash_report_parsed` — Starting Cash base currency ≈ -$11,097.13
- `test_instrument_info_parsed` — AT. has listing_exch=LSE, MGCM5 has underlying=MGC and multiplier=10

Normalizer tests (~14):
- `test_normalize_returns_three_lists`
- `test_trades_and_fifo_same_length` — len(trades) == len(fifo)
- `test_stock_symbol_resolved_via_instrument_info` — AT. with listing_exch=LSE → AT.L (matches ibkr_flex canonical)
- `test_option_symbol_normalized` — NMM_C70_260116
- `test_option_price_per_contract` — NXT C30 t_price=11.51 → price=1151
- `test_option_contract_identity` — Has underlying, multiplier=100
- `test_futures_symbol_resolved_to_underlying` — MGCM5 → MGC (from instrument info)
- `test_futures_multiplier_from_instrument_info` — MGCM5 multiplier=10 (from instrument info)
- `test_forex_trades_filtered`
- `test_income_events_include_interest` — Present, total < 0
- `test_income_events_include_dividends` — Present, total > 0
- `test_income_events_include_fees` — Present, total ≈ -$164
- `test_trade_types_correct` — CBL=SELL, AAPL=BUY
- `test_expired_option_type` — option_expired=True for Ep codes
- `test_all_trades_have_source` — source="ibkr_statement" everywhere

**Expected counts from real data:**
- Parser: 51 raw trades, 23 interest, 27 dividends, 27 fees, 40 cash report
- Normalizer: 49 trades (2 forex filtered), 77 income events, 49 FIFO transactions
- Trade type breakdown: BUY=16, SELL=18, COVER=11, SHORT=4
- Instrument breakdown: equity=24, option=19, futures=6

#### 4.4 Phase 1 Acceptance Criteria

- [ ] Parser handles all 5 CSV files correctly
- [ ] Normalizer produces trades/income/fifo matching expected counts
- [ ] Option symbols match ibkr_flex canonical format
- [ ] Option prices are per-contract (×100)
- [ ] Trade types derived correctly from quantity + code
- [ ] Forex trades filtered
- [ ] Interest/dividends/fees produce NormalizedIncome events
- [ ] All outputs have source="ibkr_statement"
- [ ] 27 tests passing

---

### Phase 2: Transaction Store Integration

**Goal:** Wire ibkr_statement into the ingestion pipeline so data flows into the database. Add cross-provider dedup at the load path.

#### 5.1 Ingestion Path

**`mcp_tools/transactions.py`** — Add ibkr_statement provider

Changes to `Provider` type:
```python
Provider = Literal["all", "plaid", "schwab", "ibkr_flex", "snaptrade", "ibkr_statement"]
```

**Do NOT add `"ibkr_statement"` to `_REFRESH_PROVIDERS`** — it is manual-ingest only.

**Guard `refresh_transactions()` against ibkr_statement:**
```python
# In refresh_transactions(), before the provider loop:
if provider and str(provider).strip().lower() == "ibkr_statement":
    raise ValueError("ibkr_statement requires csv_dir; use fetch_provider_transactions instead")
```
This prevents the footgun of calling `refresh_transactions(provider="ibkr_statement")` which would fail at `_ingest_transactions_inner()` without csv_dir.

Changes to `_ingest_transactions_inner()`:
- Add `csv_dir: Optional[str] = None` parameter
- When `provider == "ibkr_statement"`:
  - Skip `fetch_transactions_for_source()` (no API to call)
  - Require `csv_dir` parameter (raise ValueError if missing)
  - Call `parse_ibkr_statement(csv_dir)` instead
  - Flatten ALL rows into a SINGLE provider key via `flatten_for_store()`:
    ```python
    parsed = parse_ibkr_statement(csv_dir)
    provider_rows["ibkr_statement"] = flatten_for_store(parsed, parsed["account_id"])
    ```
    ```
  - `allowed_providers` check passes because `provider="ibkr_statement"` → `allowed_providers = {"ibkr_statement"}`
  - Store cash_report as `statement_cash` in the ibkr_statement batch's own `fetch_metadata` (see §6.3)

Changes to MCP tool `fetch_provider_transactions()`:
```python
@handle_mcp_errors
def fetch_provider_transactions(
    user_email: Optional[str] = None,
    provider: Provider = "all",
    csv_dir: Optional[str] = None,  # NEW: required for ibkr_statement
) -> dict:
```

**`inputs/transaction_store.py`** — Add ibkr_statement to normalize_batch

Changes to `normalize_batch()` — add `ibkr_statement` partition in the row routing loop (after ibkr_flex block):
```python
ibkr_statement_rows: list[dict[str, Any]] = []

# In the partition loop, add:
elif row_provider == "ibkr_statement":
    ibkr_statement_rows.append(raw)

# After existing normalizer calls, add:
if ibkr_statement_rows:
    _, stmt_income, stmt_fifo = IBKRStatementNormalizer().normalize(
        ibkr_statement_rows,
        security_lookup={},
    )
    income_events.extend(stmt_income)
    fifo_transactions.extend(stmt_fifo)
```

The normalizer receives the flat list of all raw rows (trades + cash) and uses `_row_type` to separate them internally. This matches `_load_raw_batch_rows()` behavior: all rows are stored under `provider="ibkr_statement"`, so a single `normalize_batch(provider="ibkr_statement")` call finds them all.

**Do NOT add `"ibkr_statement"` to `_CONCRETE_PROVIDERS`.**
The `_CONCRETE_PROVIDERS` list drives `ensure_store_fresh()` auto-refresh.
Adding ibkr_statement would cause `_ingest_transactions_inner(provider="ibkr_statement")` calls without `csv_dir`, which would fail.

Add `IBKRStatementNormalizer` import to transaction_store.py:
```python
from providers.normalizers import (
    IBKRFlexNormalizer,
    IBKRStatementNormalizer,  # NEW
    PlaidNormalizer,
    SchwabNormalizer,
    SnapTradeNormalizer,
)
```

Changes to `_infer_provider_from_row()`:
- Add ibkr_statement detection: look for `_row_type` key (present on all statement rows)

Changes to `_dedup_key()`:
- Add ibkr_statement dedup key generation (keyed on `_row_type` + discriminating fields)

#### 5.2 Dedup Strategy

**Problem:** Statement and Flex overlap for ~12 months. The same trade appears in both sources.

**Approach: Load ibkr_flex + ibkr_statement via scoped `provider IN (...)`, then dedup post-load.**

**`inputs/transaction_store.py`** — Changes to `load_from_store()`

Current behavior: `provider = _normalized_provider_filter(source)` → when `source="ibkr_flex"`, queries filter to `provider="ibkr_flex"` only.

New behavior:
```python
_IBKR_PROVIDERS = ("ibkr_flex", "ibkr_statement")

def load_from_store(user_id, source=None, institution=None, account=None):
    provider = TransactionStore._normalized_provider_filter(source)

    # When loading ibkr_flex, also load ibkr_statement for supplementary data
    load_provider = _IBKR_PROVIDERS if provider == "ibkr_flex" else provider

    with get_db_session() as conn:
        store = TransactionStore(conn)
        fifo_transactions = store.load_fifo_transactions(
            user_id=user_id, provider=load_provider, ...)
        income_events = store.load_income_events(
            user_id=user_id, provider=load_provider, ...)
        # Provider flows: load for ibkr_flex ONLY (statement has none — D3)
        provider_flow_events = store.load_provider_flow_events(
            user_id=user_id, provider="ibkr_flex" if provider == "ibkr_flex" else provider, ...)
        # Fetch metadata: load BOTH ibkr_flex AND ibkr_statement
        fetch_metadata = store.load_fetch_metadata(
            user_id=user_id, provider=load_provider, ...)
        ...

    # Apply cross-provider dedup when statement data present
    if provider == "ibkr_flex" or provider is None:
        fifo_transactions = _dedup_flex_statement(fifo_transactions)
        income_events = _dedup_income_across_providers(income_events)

    return {...}
```

**DB query changes** — `load_fifo_transactions()`, `load_income_events()`, `load_fetch_metadata()`:
- Accept `provider: Optional[str | tuple[str, ...]]`
- When `provider` is a tuple: `WHERE provider IN %s` (PostgreSQL supports `IN %s` with a tuple param)
- When `provider` is a string: `WHERE provider = %s` (existing behavior)
- When `provider` is None: no filter (existing behavior)

This scopes to exactly `("ibkr_flex", "ibkr_statement")` — does NOT widen to Plaid/Schwab/SnapTrade.
When `source=None`/`"all"`, `provider` is already None, so all providers load (existing behavior) — ibkr_statement is included automatically.

**Cross-provider FIFO dedup** (`_dedup_flex_statement()`):

```python
def _dedup_flex_statement(fifo_transactions: list[dict]) -> list[dict]:
    """Remove ibkr_statement rows that duplicate ibkr_flex rows."""
    # Build keys from ibkr_flex rows
    flex_keys: Counter = Counter()
    for txn in fifo_transactions:
        if txn.get("source") == "ibkr_flex":
            flex_keys[_cross_provider_dedup_key(txn)] += 1

    if not flex_keys:
        return fifo_transactions  # No flex data, keep all

    result = []
    for txn in fifo_transactions:
        if txn.get("source") == "ibkr_statement":
            key = _cross_provider_dedup_key(txn)
            if flex_keys.get(key, 0) > 0:
                flex_keys[key] -= 1
                continue  # Skip — flex has this trade
        result.append(txn)
    return result

def _cross_provider_dedup_key(txn: dict) -> tuple:
    """7-field dedup key for matching trades across ibkr_flex and ibkr_statement."""
    return (
        str(txn.get("symbol") or "").upper(),
        str(txn.get("type") or "").upper(),
        str(txn.get("date") or "")[:10],          # YYYY-MM-DD only
        round(abs(float(txn.get("quantity") or 0)), 4),
        round(abs(float(txn.get("price") or 0)), 2),
        str(txn.get("currency") or "USD").upper(), # Codex finding #3: add currency
        str(txn.get("account_id") or "").lower(),  # Codex finding #3: add account_id
    )
```

**Cross-provider income dedup** (`_dedup_income_across_providers()`):

```python
def _dedup_income_across_providers(income_events: list[dict]) -> list[dict]:
    """Remove ibkr_statement income that duplicates ibkr_flex income."""
    # Build keys from ibkr_flex income (dividends only — interest/fees are statement-exclusive)
    flex_keys: Counter = Counter()
    for inc in income_events:
        if inc.get("source") == "ibkr_flex" and inc.get("income_type") in ("dividend", "payment_in_lieu"):
            flex_keys[_income_dedup_key(inc)] += 1

    if not flex_keys:
        return income_events

    result = []
    for inc in income_events:
        if (inc.get("source") == "ibkr_statement"
                and inc.get("income_type") in ("dividend", "payment_in_lieu")):
            key = _income_dedup_key(inc)
            if flex_keys.get(key, 0) > 0:
                flex_keys[key] -= 1
                continue  # Flex has this dividend
        result.append(inc)
    return result

def _income_dedup_key(inc: dict) -> tuple:
    """5-field dedup key for matching income across ibkr_flex and ibkr_statement."""
    return (
        str(inc.get("symbol") or "").upper(),
        str(inc.get("date") or "")[:10],
        round(abs(float(inc.get("amount") or 0)), 2),
        str(inc.get("currency") or "USD").upper(),
        str(inc.get("account_id") or "").lower(),  # multi-account safety
    )
```

#### 5.3 Tests

**`tests/importers/test_ibkr_statement_store.py`** — Store integration tests (~14 tests)

- `test_ingest_creates_batch` — Batch status progresses to "complete"
- `test_ingest_requires_csv_dir` — Raises ValueError when csv_dir missing
- `test_raw_rows_stored` — Correct count in raw_transactions table
- `test_normalize_produces_fifo` — normalized_transactions populated
- `test_normalize_produces_income` — normalized_income populated
- `test_load_from_store_ibkr_flex_includes_statement` — source=ibkr_flex returns merged data
- `test_load_from_store_source_all_no_double_merge` — source=None loads all once (no duplicates)
- `test_dedup_flex_wins` — Overlapping trades kept from flex, dropped from statement
- `test_dedup_statement_fills_gaps` — Non-overlapping statement trades included
- `test_dedup_key_7_fields` — currency and account_id in key prevent false matches
- `test_income_dedup_dividends` — Overlapping dividends deduped (flex wins)
- `test_income_dedup_key_includes_account_id` — Same dividend in different accounts NOT deduped
- `test_income_no_dedup_interest_fees` — Interest/fees from statement always kept (no flex equivalent)
- `test_ensure_store_fresh_skips_statement` — Auto-refresh does NOT attempt ibkr_statement
- `test_load_from_store_scoped_to_ibkr` — source=ibkr_flex loads only ibkr_flex+ibkr_statement (NOT plaid/schwab/snaptrade)
- `test_refresh_transactions_rejects_statement` — refresh_transactions(provider="ibkr_statement") raises ValueError

#### 5.4 Phase 2 Acceptance Criteria

- [ ] `fetch_provider_transactions(provider="ibkr_statement", csv_dir=...)` works end-to-end
- [ ] `fetch_provider_transactions(provider="ibkr_statement")` without csv_dir raises error
- [ ] Raw rows stored with provider="ibkr_statement" (single provider, `_row_type` discriminator)
- [ ] Normalization produces correct FIFO + income rows in DB
- [ ] `load_from_store(source="ibkr_flex")` loads provider IN ("ibkr_flex", "ibkr_statement") — NOT all providers
- [ ] `load_from_store(source=None)` includes statement (already loads all)
- [ ] Overlapping FIFO trades deduped (flex wins, 7-field key)
- [ ] Overlapping dividend income deduped (flex wins)
- [ ] Interest/fees always kept (no flex equivalent to dedup against)
- [ ] `ensure_store_fresh()` does NOT auto-ingest ibkr_statement
- [ ] No provider flow events generated for statement (income path only)
- [ ] 14 new tests passing

---

### Phase 3: Engine Integration + Option Multiplier Fix

**Goal:** Ensure the engine correctly consumes new income events, fix the option multiplier double-application risk, wire cash anchor metadata, and validate TWR.

#### 6.1 Income Events in Cash Replay

The engine's `derive_cash_and_external_flows()` in `nav.py` already handles `INCOME` events (lines 196-207). Interest (negative), fees (negative), and dividends (positive) all flow correctly through their signed amounts. No nav.py changes needed for the income path.

The `income_with_currency` list is built from `StoreBackedIncomeProvider`. `load_income_events()` loads all rows from `normalized_income` regardless of `income_type`, and preserves `currency`. This works out of the box.

#### 6.2 Option Multiplier Fix (3 locations)

The engine applies ×100 for options where `source != "ibkr_flex"`. Since statement trades have `source="ibkr_statement"` and the normalizer already multiplied ×100, the engine would apply ×100 AGAIN without this fix.

**Location 1: nav.py line 303-306** (unpriceable suppression path):
```python
# Before:
and event.get("source") != "ibkr_flex"
# After:
and event.get("source") not in ("ibkr_flex", "ibkr_statement")
```

**Location 2: nav.py line 318-321** (main trade cash replay path):
```python
# Before:
and event.get("source") != "ibkr_flex"
# After:
and event.get("source") not in ("ibkr_flex", "ibkr_statement")
```

**Location 3: engine.py line 964-968** (FIFO terminal option pricing):
```python
# Before:
if fifo_source != "ibkr_flex":
# After:
if fifo_source not in ("ibkr_flex", "ibkr_statement"):
```

**Design note:** Using provider name to encode per-share vs per-contract semantics is acknowledged as brittle. A better long-term approach would be a `price_convention` field on the FIFO dict ("per_share" vs "per_contract"). However, that's a larger refactor outside the scope of this plan. The provider-name check is consistent with the existing pattern and sufficient for now.

#### 6.3 Cash Anchor from Statement CSV

**Problem:** `_statement_cash_from_metadata()` (engine.py:1899) reads `statement_cash` from `fetch_metadata` rows where `provider == "ibkr_flex"`. Statement data lives on a separate provider.

**Solution:** Store `statement_cash` on the ibkr_statement batch's own metadata, and modify `_statement_cash_from_metadata()` to also check `provider == "ibkr_statement"` rows. This is durable — later ibkr_flex auto-refreshes cannot overwrite it.

In `_ingest_transactions_inner()` for ibkr_statement:
```python
# Extract cash report values
cash_report = parsed["cash_report"]
starting_cash = next(
    (r["total"] for r in cash_report
     if r["currency_summary"] == "Starting Cash"
     and r["currency"] == "Base Currency Summary"),
    None,
)
ending_cash = next(
    (r["total"] for r in cash_report
     if r["currency_summary"] == "Ending Cash"
     and r["currency"] == "Base Currency Summary"),
    None,
)
statement_cash = {
    "starting_cash_usd": starting_cash,
    "ending_cash_usd": ending_cash,
    "period_start": parsed["period"]["start_date"],
    "period_end": parsed["period"]["end_date"],
    "source": "ibkr_statement_csv",
}

# Store in ibkr_statement batch metadata (standard update_batch_status path)
# account_id/institution stored for future multi-account scoping and per-row engine checks
fetch_metadata = [{
    "provider": "ibkr_statement",
    "statement_cash": statement_cash,
    "account_id": parsed["account_id"],
    "institution": "ibkr",
}]
store.update_batch_status(
    batch_id=batch_id, status="complete", user_id=user_id,
    fetch_metadata=fetch_metadata, ...
)
# Note: load_fetch_metadata() partitions by provider only, not account.
# Single-account IBKR is the current supported case. Multi-account would
# need account-level metadata filtering (out of scope).
```

**Engine changes** — 2 modifications in `_analyze_realized_performance_single_scope()`:

1. **Save unfiltered metadata before provider-flow-source filter** (engine.py:~645):
```python
# BEFORE the provider_flow_sources filter:
all_fetch_metadata = list(provider_fetch_metadata)  # preserve for cash anchor

# Existing filter (unchanged):
provider_fetch_metadata = [
    row for row in provider_fetch_metadata
    if str(row.get("provider") or "").strip().lower() in enabled_provider_flow_sources
]
```

2. **`_statement_cash_from_metadata()` reads unfiltered list and accepts ibkr_statement** (engine.py:1919-1920):
```python
# Before:
for row in provider_fetch_metadata:
    if str(row.get("provider") or "").strip().lower() != "ibkr_flex":
        continue
# After:
for row in all_fetch_metadata:  # unfiltered — includes ibkr_statement
    if str(row.get("provider") or "").strip().lower() not in ("ibkr_flex", "ibkr_statement"):
        continue
```

3. **Broaden the source guard for cash anchor invocation** (engine.py:1967-1970):
```python
# Before:
statement_end_cash = (
    _statement_cash_from_metadata()
    if source == "ibkr_flex"
    else None
)
# After:
statement_end_cash = (
    _statement_cash_from_metadata()
    if source in ("ibkr_flex", "all")  # "all" is the default source
    else None
)
```
Note: the engine normalizes `source` to a lowercase string (never `None`). Default is `"all"`, not `None`. This ensures the cash anchor works for both explicit `source="ibkr_flex"` AND the default `source="all"` path (which is what performance tools use).

`load_from_store()` loads ibkr_statement metadata (via `provider IN ("ibkr_flex", "ibkr_statement")`), so the metadata rows are available. The `all_fetch_metadata` variable preserves them through the provider-flow-source filter.

#### 6.4 Multi-Currency Handling

Interest rows exist in both HKD and USD. The engine handles multi-currency income via FX conversion:
```python
fx = fx_module._event_fx_rate(event.get("currency", "USD"), event["date"], fx_cache)
cash += amount * fx
```

The normalizer preserves the `currency` field on each `NormalizedIncome`. Works correctly.

#### 6.5 Tests

**`tests/importers/test_ibkr_statement_engine.py`** — Engine integration tests (~12 tests)

- `test_income_events_in_cash_replay` — Interest/fees reduce cash in replay
- `test_income_events_with_fx` — HKD interest correctly FX-converted
- `test_statement_cash_in_ibkr_statement_metadata` — cash_report stored in ibkr_statement batch metadata
- `test_cash_anchor_from_statement_csv` — Engine reads statement_cash from ibkr_statement metadata
- `test_cash_anchor_survives_flex_refresh` — New ibkr_flex ingest does NOT hide statement_cash
- `test_cash_anchor_works_for_source_all` — Default source=None/all fires cash anchor
- `test_metadata_has_account_and_institution` — ibkr_statement metadata carries account_id + institution
- `test_no_double_count_dividends` — Dividends from statement vs flex deduped
- `test_option_multiplier_not_double_applied_nav_main` — nav.py:318 skips ibkr_statement
- `test_option_multiplier_not_double_applied_nav_suppress` — nav.py:303 skips ibkr_statement
- `test_option_multiplier_not_double_applied_fifo_terminal` — engine.py:964 skips ibkr_statement
- `test_no_provider_flows_from_statement` — Statement doesn't inject provider flows
- `test_provider_flow_authority_not_triggered` — External flow inference not suppressed
- `test_full_pipeline_runs` — End-to-end: ingest → load → analyze without crash
- `test_twr_direction` — TWR after statement import closer to 0.29% than before

**`scripts/validate_statement_twr.py`** — TWR validation script
```python
"""Validate TWR after statement import by comparing engine vs IBKR."""
# 1. Ingest ibkr_statement
# 2. Run realized performance analysis
# 3. Compare TWR with IBKR's 0.29%
# 4. Print diagnostic: monthly returns, cash replay totals, anchor values
```

#### 6.6 Phase 3 Acceptance Criteria

- [ ] Interest/fee income events appear in cash replay
- [ ] HKD interest FX-converted correctly
- [ ] Cash anchor metadata stored on ibkr_statement batch (engine modified to read ibkr_statement too)
- [ ] Cash anchor survives subsequent ibkr_flex auto-refresh
- [ ] No double-counting of dividends
- [ ] Option multiplier ×100 NOT double-applied (3 locations fixed)
- [ ] Provider flow authority mode not triggered by statement data
- [ ] External flow inference still works when statement data present
- [ ] Full pipeline runs without errors
- [ ] TWR moves toward IBKR's 0.29%
- [ ] 12 new tests passing

---

## 7. Complete File Change Summary

### New Files (Phase 1)
| File | Description |
|------|------------|
| `inputs/importers/__init__.py` | Package init |
| `inputs/importers/ibkr_statement.py` | CSV parser — `parse_ibkr_statement(csv_dir)` |
| `providers/normalizers/ibkr_statement.py` | Normalizer — `IBKRStatementNormalizer` |
| `tests/importers/__init__.py` | Test package init |
| `tests/importers/test_ibkr_statement.py` | Parser + normalizer tests (27 tests) |

### New Files (Phase 2)
| File | Description |
|------|------------|
| `tests/importers/test_ibkr_statement_store.py` | Store integration tests (14 tests) |

### New Files (Phase 3)
| File | Description |
|------|------------|
| `scripts/validate_statement_twr.py` | TWR validation script |
| `tests/importers/test_ibkr_statement_engine.py` | Engine integration tests (12 tests) |

### Modified Files (Phase 1)
| File | Change |
|------|--------|
| `providers/normalizers/__init__.py` | Add `IBKRStatementNormalizer` to exports |

### Modified Files (Phase 2)
| File | Change |
|------|--------|
| `mcp_tools/transactions.py` | Add `ibkr_statement` to `Provider` type, `csv_dir` param, bypass API fetch for CSV, `statement_cash` in batch metadata |
| `inputs/transaction_store.py` | `normalize_batch()` routing for ibkr_statement, `IBKRStatementNormalizer` import, `_dedup_flex_statement()`, `_dedup_income_across_providers()`, `load_from_store()` merge logic (`provider IN (...)` when source=ibkr_flex), `load_fifo_transactions()`/`load_income_events()`/`load_fetch_metadata()` accept tuple providers, `_infer_provider_from_row()`, `_dedup_key()` |

### Modified Files (Phase 3)
| File | Change |
|------|--------|
| `core/realized_performance/nav.py` | Add `"ibkr_statement"` to option multiplier skip list (2 locations: lines 305, 321) |
| `core/realized_performance/engine.py` | Add `"ibkr_statement"` to FIFO terminal option pricing skip (line 968) + save `all_fetch_metadata` before provider-flow filter (line ~645) + `_statement_cash_from_metadata()` reads `all_fetch_metadata` and accepts ibkr_statement (line 1919-1920) |

### Files NOT Modified (by design)
| File | Reason |
|------|--------|
| `providers/flows/extractor.py` | No provider flows from statement (D3) |
| `providers/flows/__init__.py` | No statement flow extractor needed |
| `settings.py` | No new env vars; ibkr_statement not in `REALIZED_PROVIDER_FLOW_SOURCES` |
| `mcp_tools/performance.py` | ibkr_statement NOT a valid standalone source — no validator changes needed |
| `services/performance_helpers.py` | Same — ibkr_statement loads automatically with ibkr_flex |

---

## 8. Open Questions (Resolved)

| # | Question | Resolution |
|---|---------|------------|
| 1 | Option price convention? | Per-share in CSV. Multiply ×100 for per-contract to match ibkr_flex. Verified: NXT C30 t_price=11.51, proceeds=-1151. |
| 2 | Futures MTM handling? | Keep ibkr_flex_mtm for daily MTM events. Statement has only cumulative total. |
| 3 | FX translation gain/loss ($53.88)? | Accounting adjustment, not a real cash flow. Excluded. |
| 4 | Raw CSV vs materialized? | Phase 1 supports materialized only. Raw CSV is a future enhancement. |
| 5 | How do interest/fees flow to cash replay? | As `NormalizedIncome` only. No provider flows from statement. Engine's `INCOME` event handler adds to cash with FX. |
| 6 | Where does dedup happen? | At `load_from_store()` post-load, not `normalize_batch()`. Both normalize independently. |
| 7 | Does nav.py need changes? | Yes — option multiplier skip list needs `"ibkr_statement"` (2 locations). No changes for income path. |
| 8 | How does ibkr_statement interact with existing dedup? | Independent. Plaid-vs-Flex via `DEDUP_LEGACY_ENABLED`. Flex-vs-Statement via `_dedup_flex_statement()`. |
| 9 | How does cash anchor connect? | Statement cash_report stored on ibkr_statement batch metadata. Engine's `_statement_cash_from_metadata()` modified to also check `provider="ibkr_statement"` (2-line change). Survives later flex auto-refreshes. |
| 10 | Will auto-refresh break? | No — ibkr_statement NOT in `_CONCRETE_PROVIDERS` or `_REFRESH_PROVIDERS`. Manual-ingest only. |
| 11 | Do we need a `proceeds` field? | No. Correct `price × quantity` (with proper multiplier) reproduces proceeds. Verified against real data. |
| 12 | Income-income dedup? | Yes — dividends may appear in both flex and statement. Dedup via `(symbol, date, amount, currency, account_id)` at load time — 5-field key. |
| 13 | How are futures multipliers derived? | `abs(notional_value) / (abs(quantity) * t_price)`. MGCM5: `31512 / (1 × 3151.2) = 10`. NOT `notional / quantity` which gives wrong result. |
| 14 | Can fee amounts be positive? | Yes — fees__all.csv has credits/reversals (positive). Preserve CSV sign as-is; do NOT force negative. |
| 15 | Is ibkr_statement a valid standalone source? | No. It always loads alongside ibkr_flex. Not added to source validators in performance.py etc. |
| 16 | Split vs single provider for ingestion? | Single provider `"ibkr_statement"` for ALL rows. `_row_type` field discriminates trade/interest/dividend/fee. Avoids `allowed_providers` filtering issue. |
| 17 | Does `provider=None` scope correctly? | No — it widens to all providers. Use `provider IN ("ibkr_flex", "ibkr_statement")` tuple for scoped loading. DB queries updated to accept `tuple[str, ...]`. |
| 18 | Does `_statement_cash_from_metadata()` see ibkr_statement metadata? | Not without fix — `provider_fetch_metadata` is filtered to `enabled_provider_flow_sources` at engine.py:651-654. Fix: save unfiltered `all_fetch_metadata` before filter, read from it in the cash anchor function. |
| 19 | How are foreign stock symbols resolved without exchange metadata? | `financial_instrument_information__all.csv` provides `listing_exch` for every instrument. Parser builds instrument_info lookup. Normalizer uses `ibkr_exchange_to_mic` + `resolve_fmp_ticker()` — same path as ibkr_flex. |
| 20 | Is normalizer input a parsed dict or flat rows? | Flat rows with `_row_type` discriminator (consistent across Phase 1 tests and Phase 2 store). Parser returns structured dict; `flatten_for_store()` converts to flat rows before storage and normalization. |
| 21 | Does cash anchor work for `source="all"` (default)? | Yes — engine source guard broadened from `source == "ibkr_flex"` to `source in ("ibkr_flex", "all")`. Engine normalizes source to lowercase string (`"all"`, never `None`). Default performance path now fires the cash anchor. |
| 22 | Does metadata carry account/institution for scoped queries? | Partially. `account_id` and `institution` are stored in metadata JSON for future use and per-row engine checks. However, `load_fetch_metadata()` only partitions by `provider` (not account). For the current single-account IBKR setup, provider-level scoping is sufficient. Multi-account would need account-level metadata filtering (out of scope). |
| 23 | Can `refresh_transactions()` be called with ibkr_statement? | Guarded — explicit ValueError if provider="ibkr_statement". Must use `fetch_provider_transactions(csv_dir=...)` instead. |
| 24 | Where do futures multipliers come from? | Primary: `financial_instrument_information__all.csv` `multiplier` column. Fallback: `abs(notional_value) / (abs(quantity) * t_price)`. |

## 9. Risk Assessment

| Risk | Mitigation | Status |
|------|-----------|--------|
| Double-counting trades across flex + statement | 7-field dedup key (symbol, type, date, quantity, price, currency, account_id) | Addressed |
| Double-counting dividends | Income-income dedup with 5-field key (symbol, date, amount, currency, account_id) at load_from_store | Addressed |
| Option multiplier ×100 applied twice | Add ibkr_statement to skip list in 3 locations (nav.py ×2, engine.py ×1) | Addressed |
| Provider flow authority suppressing inference | NO provider flows from statement — income path only | Addressed |
| Auto-refresh crash without csv_dir | ibkr_statement NOT in `_CONCRETE_PROVIDERS` or `_REFRESH_PROVIDERS` | Addressed |
| Cash anchor metadata not found | Stored on ibkr_statement batch; engine reads ibkr_statement too (2-line change) | Addressed |
| Cash anchor hidden by later flex refresh | ibkr_statement metadata on separate provider partition — survives flex refresh | Addressed |
| source=ibkr_flex widening to all providers | Use `provider IN ("ibkr_flex", "ibkr_statement")` tuple — scoped, not `None` | Addressed |
| Split provider not reaching normalize_batch | Single provider key `"ibkr_statement"` with `_row_type` discriminator | Addressed |
| Fee sign overstatement | Preserve CSV sign as-is; positive credits/reversals kept | Addressed |
| Futures multiplier wrong formula | `abs(notional) / (abs(qty) × t_price)`, not `notional / qty` | Addressed |
| Metadata filtered before cash anchor reads it | Save `all_fetch_metadata` before provider-flow filter; cash anchor reads unfiltered list | Addressed |
| Foreign stock symbol mismatch (AT. → AT vs AT.L) | Instrument info CSV provides `listing_exch`; uses same `ibkr_exchange_to_mic` + `resolve_fmp_ticker()` path as flex | Addressed |
| Futures symbol mismatch (MGCM5 vs MGC) | Instrument info CSV provides `underlying`; normalizer resolves to root symbol matching flex | Addressed |
| Normalizer input contract mismatch (dict vs flat rows) | Consistent flat-row API; `flatten_for_store()` helper bridges parser → store | Addressed |
| Cash anchor not firing for source="all" (default) | Engine source guard broadened to `source in ("ibkr_flex", "all")` — engine normalizes source to string, never None | Addressed |
| Metadata scoping for multi-account | Provider-level scoping sufficient for single-account. `account_id`/`institution` stored in metadata JSON for future use. Multi-account metadata filtering out of scope | Acknowledged |
| `refresh_transactions()` footgun for ibkr_statement | Explicit ValueError guard — must use `fetch_provider_transactions` | Addressed |
| HKD interest not FX-converted | Normalizer preserves currency; engine's FX cache handles | Works |
| Breaking existing ibkr_flex behavior | Separate provider; flex path unchanged; no provider flows | Low risk |

## 10. Relationship to Other Plans

| Plan | Relationship | Dependency |
|------|-------------|------------|
| `DUAL_CASH_ANCHOR_PLAN.md` | Consumes statement starting/ending cash from metadata | Statement import stores the data; dual anchor applies it. Independent implementation. |
| `STATEMENT_START_CASH_FIX_PLAN.md` | Superseded by dual anchor | Both use same data. |
| `IBKR_NAV_GAP_FIX_PLAN.md` | Statement import is the next step | NAV gap fix (cash anchor from SQLite) already implemented. CSV import completes the picture. |

## 11. Execution Order

1. **Phase 1** — Standalone: parser + normalizer + tests (no DB/engine changes)
2. **Phase 2** — Store integration: ingestion, normalize_batch routing, load_from_store merge + dedup
3. **Phase 3** — Engine: option multiplier fix (3 locations), cash anchor metadata, validation

Total new/modified files: 8 new, 5 modified
Total new tests: ~55
