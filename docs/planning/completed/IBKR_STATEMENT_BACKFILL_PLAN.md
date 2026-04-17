# IBKR Statement Backfill + MTM Metadata Fix

**Status:** Part 1 COMPLETE (`c0ec8697`), Part 2 PLANNING
**Goal:** Close the $7,653 start-cash gap in IBKR realized performance
**Depends on:** Fix 1 (statement cash anchor) COMPLETE, Fix 2a (MTM ingestion) COMPLETE, AT. pricing (`40b41dc2`) COMPLETE
**Backlog ref:** `BACKLOG.md` → "IBKR Realized Performance — Fix 2"

## Current State

| Metric | Engine (post-Fix 2b) | IBKR Statement | Gap |
|--------|---------------------|---------------|-----|
| End cash | -$8,727 | -$8,727 | **$0** |
| Back-solved start cash | -$18,750 | -$11,097 (April 1) | $7,653 |
| TWR | +3.1% | +0.29% | 2.8 pp |
| Data coverage | 50% | — | — |
| MTM in replay | -$3,955 (91 events) | -$3,589 | Applied correctly |
| `futures_cash_policy` reported | `fee_and_mtm` | — | Fixed (`c0ec8697`) |
| Unpriceable symbols | 0 | — | Fixed (`40b41dc2`) |

**Key finding:** MTM is already being applied in the cash replay (-$3,955 impact).
The `fee_only` label and missing `futures_mtm_event_count`/`futures_mtm_cash_impact_usd`
in the output metadata are cosmetic bugs — the actual computation is correct.

The entire $8,610 gap is from **19 first-exit positions** whose SELL proceeds flow
through the cash replay with no offsetting BUY outflow (buys happened before the
Flex query window). Synthetic entries are correctly excluded from cash replay, but
this means the replay has one-sided sell cash, inflating the back-solved start cash.

## Gap Driver: First-Exit One-Sided Sells

19 positions have their first observed transaction as an exit. The engine creates
synthetic position entries (for NAV tracking) but excludes them from cash replay
(correct for Modified Dietz). The SELL side adds cash, the BUY side is missing.

**Why start NAV is reasonable but start cash is wrong:**
- Synthetic positions make `start_positions` too HIGH (position value added)
- Missing buy outflows make `start_cash` too LOW (negative)
- These errors partially cancel in NAV = positions + cash
- But the individual components are each wrong, distorting cash-based metrics

## Statement Data Available

Two materialized IBKR statement SQLite files exist:

| Statement | Period | Trades | Path |
|-----------|--------|--------|------|
| **Realized Summary** | Dec 31, 2024 – Dec 31, 2025 | 157 | `ibkr_statement_frames/U2471778_20241231_20251231/` |
| Activity | Apr 1, 2025 – Mar 3, 2026 | 90 | `ibkr_statement_frames/U2471778_20250401_20260303/` |

The Realized Summary statement (157 trades) is the better source — it covers the
full period including pre-Flex-window opens. The `trades__all` table has columns:

```
symbol, date_time, quantity, t_price, proceeds, comm_fee, basis, realized_p_l,
code, asset_category, currency, datadiscriminator, notional_value
```

The `code` field contains `O` (open), `C` (close), `L` (long-term), `P` (partial).

### Pre-Flex Opening Trades Found (before March 5, 2025)

These opening trades in the statement would replace synthetic entries:

| Symbol | Date | Qty | Price | Cost | Category |
|--------|------|-----|-------|------|----------|
| IGIC | 2024-12-31 | 100 | $23.75 | $2,375 | Stocks |
| NMM | 2024-12-31 | 20 | $43.46 | $869 | Stocks |
| KINS | 2024-12-31 | 100 | $14.79 | $1,479 | Stocks |
| V | 2025-01-03 | 3 | $314.18 | $943 | Stocks |
| CUBI | 2025-01-03 | 50 | $47.00 | $2,350 | Stocks |
| AT. | 2025-01-07 | 100 | £5.55 | £555 | Stocks |
| KINS | 2025-01-08 | 150 | $14.63 | $2,195 | Stocks |
| NVDA | 2025-01-27 | 5 | $124.94 | $625 | Stocks |
| VBNK | 2025-02-10 | 145 | $13.93 | $2,020 | Stocks |
| TKO | 2025-02-10 | 12 | $173.10 | $2,077 | Stocks |
| SE | 2025-02-11 | 16 | $127.30 | $2,037 | Stocks |
| EQT | 2025-02-21 | 40 | $50.00 | $2,000 | Stocks |
| PDD options | 2025-02-14–26 | various | various | ~$5,000 | Options |
| PLTR options | 2025-02-21–24 | various | various | ~$1,000 | Options |
| MHI futures | 2025-02-24 | 1 | 22,770 | — | Futures |
| MGC futures | 2025-01-31 | 1 | 2,847.5 | — | Futures |

### Symbols Still Missing (no opening in ANY statement)

These positions were opened before Dec 31, 2024 — no statement covers them:

| Symbol | Category | Trades in Statement |
|--------|----------|-------------------|
| CBL | Stocks | 1 (closing only) |
| MSCI | Stocks | 1 (closing only) |
| NXT 15AUG25 30 C | Options | 2 (closing only) |

For these 3, we'd still need synthetic entries or a longer-lookback statement.

---

## Plan

### Part 1: MTM Metadata Cosmetic Fix (quick)

**Problem:** `futures_cash_policy` hardcoded to `"fee_only"`, MTM fields missing from dataclass.

#### 1a. Add MTM fields to `RealizedMetadata`

**File:** `core/result_objects/realized_performance.py`

Add after `futures_missing_fx_count` (~line 167):
```python
futures_mtm_event_count: int = 0
futures_mtm_cash_impact_usd: float = 0.0
```

Add to `to_dict()` after `futures_missing_fx_count`:
```python
"futures_mtm_event_count": self.futures_mtm_event_count,
"futures_mtm_cash_impact_usd": self.futures_mtm_cash_impact_usd,
```

Add to `from_dict()`:
```python
futures_mtm_event_count=int(_helpers._as_float(d.get("futures_mtm_event_count"), 0.0)),
futures_mtm_cash_impact_usd=float(_helpers._as_float(d.get("futures_mtm_cash_impact_usd"), 0.0)),
```

#### 1b. Make `futures_cash_policy` dynamic

**File:** `core/realized_performance/engine.py` (~line 2657)

Replace:
```python
"futures_cash_policy": "fee_only",
```

With:
```python
"futures_cash_policy": (
    "fee_and_mtm"
    if int(_helpers._as_float(cash_replay_diagnostics.get("futures_mtm_event_count"), 0.0)) > 0
    else "fee_only"
),
```

#### 1c. Add to agent snapshot

**File:** `core/result_objects/realized_performance.py` — `get_agent_snapshot()` method.

Add MTM fields to the `metadata` section of the snapshot:
```python
"futures_mtm_event_count": meta.futures_mtm_event_count,
"futures_mtm_cash_impact_usd": meta.futures_mtm_cash_impact_usd,
```

#### Tests

- Existing test coverage for `RealizedMetadata.to_dict()`/`from_dict()` round-trip should catch missing fields.
- Add test: `test_futures_cash_policy_dynamic` — verify `fee_and_mtm` when MTM events processed.

---

### Part 2: Statement Trade Backfill

Ingest trades from the materialized IBKR statement SQLite into the transaction
store as a new provider (`ibkr_statement`). These replace synthetic entries for
positions opened before the Flex query window.

#### 2a. Statement trade normalizer

**File:** `providers/normalizers/ibkr_statement.py` (NEW)

Normalize `trades__all` rows into the standard FIFO transaction format:

```python
def normalize_statement_trades(
    db_path: str,
    *,
    account_id: str = "U2471778",
) -> list[dict[str, Any]]:
    """Read trades from materialized IBKR statement SQLite and normalize to FIFO format."""
```

**Mapping:**

| Statement Field | FIFO Field | Notes |
|----------------|-----------|-------|
| `symbol` | `symbol` | Strip futures expiry suffix for root (MESH5→MES) |
| `date_time` | `date` | Parse "YYYY-MM-DD, HH:MM:SS" |
| `quantity` | `quantity` | Absolute value; sign determines action |
| `t_price` | `price` | Parse, strip commas |
| `comm_fee` | `commission` | Absolute value |
| `currency` | `currency` | Direct |
| `asset_category` | `instrument_type` | Stocks→equity, Futures→futures, Options→option, Forex→fx_artifact |
| `code` | — | `O`=opening, `C`=closing. Derive action: qty>0+O=BUY, qty<0+O=SHORT, qty>0+C=COVER, qty<0+C=SELL |
| `proceeds` | — | Cross-check only (= -qty * price for buys) |
| — | `source` | `"ibkr_statement"` |
| — | `account_id` | From parameter |
| — | `institution` | `"ibkr"` |

**Symbol normalization for options:** Statement uses `"PDD 16JAN26 110 C"` format.
Convert to our canonical `"PDD_C110_260116"` format using existing
`parse_option_contract_identity_from_symbol()` or a new helper.

**Symbol normalization for futures:** Statement uses `"MESH5"` (root + month code + year).
Extract root symbol (MES, MGC, MHI, ZF) by stripping the expiry suffix.
Map via `get_contract_spec()` to validate.

**Filter:** Only emit rows where `datadiscriminator = 'Order'` and `row_kind = 'Data'`.
Skip subtotal/header rows.

#### 2b. Ingestion into transaction store

**File:** `inputs/transaction_store.py`

Add `ibkr_statement` as a recognized provider. The `ingest()` method already
handles arbitrary providers — just need to ensure the dedup logic works.

**Dedup strategy:** Statement trades overlap with Flex trades for dates within the
Flex window. Use `transaction_id` matching:
- Statement: generate ID as `stmt:{account_id}:{date}:{symbol}:{qty}:{price}`
- Flex: existing IDs from Flex XML
- These won't collide (different format), so we need date+symbol+qty dedup.

Alternative (simpler): Only ingest statement trades that are **before** the Flex
window start date. The Flex data is authoritative for its own window.

```python
flex_start_date = min(date for txn in existing_flex_txns)  # ~2025-03-05
statement_trades = [t for t in all_statement_trades if t["date"] < flex_start_date]
```

This avoids dedup entirely — no overlap by construction.

#### 2c. Wire into the engine

**File:** `core/realized_performance/engine.py`

After loading FIFO transactions from the store (line 344), also load statement
backfill trades if available:

```python
if provider in {None, "ibkr_flex"} and IBKR_STATEMENT_DB_PATH:
    from providers.normalizers.ibkr_statement import normalize_statement_trades
    backfill = normalize_statement_trades(IBKR_STATEMENT_DB_PATH, account_id=...)
    # Filter to before first Flex transaction date
    if fifo_transactions:
        flex_start = min(t["date"] for t in fifo_transactions if t.get("date"))
        backfill = [t for t in backfill if t["date"] < flex_start]
    fifo_transactions = backfill + fifo_transactions
```

Or, if we ingest into the store (2b), the store's `load_fifo_transactions()` would
return both providers together and the engine wouldn't need special handling.

**Preferred approach:** Ingest into store (2b). Simpler, uses existing infrastructure,
and the trades persist across runs.

#### 2d. Settings

**File:** `settings.py`

Reuse existing `IBKR_STATEMENT_DB_PATH` (already set for Fix 1). If the Realized
Summary statement is the source, update `.env`:

```
IBKR_STATEMENT_DB_PATH=docs/planning/performance-actual-2025/ibkr_statement_frames/U2471778_20241231_20251231/statement_tables.sqlite
```

Note: currently points to `U2471778_20250401_20260303`. The Dec-Dec statement has
more coverage (157 trades including pre-Flex opens). Either support multiple paths
or switch to the Dec-Dec one.

#### 2e. MCP tool for one-time ingestion

Add a one-time ingestion command or extend `fetch_provider_transactions`:

```python
fetch_provider_transactions(provider="ibkr_statement")
```

This triggers the normalizer → store pipeline. Run once to populate.

---

### Part 3: Verify

After backfill ingestion:

1. `get_performance(mode="realized", source="ibkr_flex", format="full")`
2. Check `data_coverage` — should increase from 42.86% (more positions have opening trades)
3. Check `first_transaction_exit_count` — should decrease from 19
4. Check `cash_backsolve_start_usd` — should be closer to -$11,097
5. Check `synthetic_current_position_count` — should decrease from 8
6. Check `futures_cash_policy` — should show `fee_and_mtm`
7. Check `futures_mtm_event_count` — should show 91

---

## Expected Impact

### Part 1 (MTM metadata): Cosmetic only
- No change to numbers
- `futures_cash_policy` correctly reports `fee_and_mtm`
- MTM event count and cash impact visible in metadata

### Part 2 (Statement backfill): Structural

The 25 pre-Flex opening trades add ~$20K of buy-side cash outflows to the replay.
This should:

- Reduce `cash_backsolve_replay_final_usd` by ~$20K (buys subtract from cash)
- Make `cash_backsolve_start_usd` less negative (closer to IBKR's -$11,097)
- Reduce `first_transaction_exit_count` from 19 to ~3 (CBL, MSCI, NXT remain)
- Increase `data_coverage` substantially
- Reduce TWR gap from 8.2pp toward 0

**Remaining after backfill:** CBL, MSCI, NXT 15AUG25 30 C have no opening trade
in any statement. These contribute a smaller portion of the gap. Would need either:
- A longer-lookback statement (pre-Dec 2024)
- Manual backfill entries
- Accept the residual gap (~$2K-3K from these 3 positions)

---

## Files Modified

| File | Change | Part |
|------|--------|------|
| `core/result_objects/realized_performance.py` | Add MTM fields to `RealizedMetadata` + `to_dict()`/`from_dict()` + snapshot | 1 |
| `core/realized_performance/engine.py` | Dynamic `futures_cash_policy` | 1 |
| `providers/normalizers/ibkr_statement.py` | NEW: statement trade normalizer | 2 |
| `inputs/transaction_store.py` | Support `ibkr_statement` provider (may be zero-change if generic enough) | 2 |
| `.env` | Update `IBKR_STATEMENT_DB_PATH` to Dec-Dec statement | 2 |

## Priority

Part 1 first (quick, unblocks correct reporting). Part 2 next (structural fix).
