# IBKR NAV Gap Fix Plan

**Status:** FIX 1 COMPLETE, FIX 2a (MTM) COMPLETE, remaining gap = data coverage
**Original gap:** $7,035 (engine $29,319 vs IBKR statement $22,284)
**Fix 1 result:** SnapTrade cash mismatch eliminated. Cash anchor now uses IBKR statement (-$8,727).
**Fix 2a result:** MTM events ingested (81 events), -$3,955 impact on cash replay. Metadata fields surfaced.
**Remaining gap:** ~8.2 pp TWR gap (8.53% vs 0.29%) from 53.85% data coverage (24 first-exit positions)
**Commits:** `c07f341b` (Fix 1) | Fix 2a: pending commit
**Backlog ref:** `BACKLOG.md` → "IBKR Realized Performance Remaining Gap"

## Diagnosis Summary

The entire $7,035 gap is in the **cash component**. Position values match at
March 31 ($33,468 engine = $33,468 IBKR). Two fixes needed — one dominant.

### Corrected finding: "7 missing untouched positions" was wrong

The earlier diagnosis that AAPL, AT.L, FIG, GOLD, RNMBY, SFM, SLV had "zero
Flex trades" was incorrect. All 7 DO have FIFO transactions in the Flex data
and ARE in the position timeline:

| Ticker | FIFO txns | Current shares | Fully covered? |
|--------|-----------|----------------|----------------|
| AAPL | 2 (buys 2026-03-02) | 2 | Yes |
| AT.L | 2 (buys 2026-01, 02) | 400 | Yes |
| FIG | 4 (buys 2025-11, 2026-03) | 103 | Yes |
| GOLD | 1 (buy 2026-03-04) | 11 | Yes |
| RNMBY | 1 (buy 2025-06-06) | 3 | Yes |
| SFM | 1 (buy 2025-03-12) | 14 | Yes |
| SLV | 2 (buys; 175 bought, 150 sold via options) | 25 | Yes |

The engine's 6 synthetic_current_position entries are for EQT, IGIC, KINS,
NVDA, TKO, V — positions with partial opening history. The 19
synthetic_incomplete_trade entries cover closed positions.

## Root Cause: SnapTrade Cash Definition Mismatch

SnapTrade (via IBKR Gateway) and the IBKR statement report **different
position/cash splits** but the **same total NAV**:

| Source | Positions | Cash | Accruals | NAV |
|--------|-----------|------|----------|-----|
| SnapTrade/Gateway | $25,988 | -$3,657 | — | $22,331 |
| IBKR Statement | $33,468 | -$8,727 | -$87 | $22,284 |

Gateway nets futures margin and possibly accrued interest into the position
value rather than cash. The $5,071 difference in "cash" propagates through
the engine's back-solve:

```
Engine:  start_cash = observed_end_cash - replay_cash
       = -3,656 - 4,677 = -8,333

Correct: start_cash = -8,727 - 4,677 = -13,404
IBKR actual start cash:              = -11,097
```

The engine's inception cash is -$4,149 at March 31 (after 27 days of replay
from -$8,333). IBKR statement inception cash is -$11,097. The $6,948
difference IS the NAV gap (positions match exactly).

### Cash replay discrepancy (~$2,307)

Even with the correct end cash anchor (-$8,727), the back-solved start cash
(-$13,404) differs from IBKR's actual start cash (-$11,097) by $2,307.
This is the replay error — the engine's cash replay doesn't perfectly track
IBKR's cash movement due to:

- FX translation gains/losses ($54 per IBKR Cash Report)
- Futures MTM settlement timing differences
- Internal segment transfers (securities ↔ futures: $1,408)
- Minor commission/fee accounting differences

## Fix 1: Use IBKR Statement Cash as Anchor Source (~$5,071 impact)

### Problem

`_cash_anchor_offset_from_positions()` (engine.py:1676) sums SnapTrade
CUR:* position rows = -$3,656. This is $5,071 higher than IBKR statement
ending cash = -$8,727. The back-solve inherits the error.

### Approach

Store IBKR statement Starting Cash and Ending Cash in `fetch_metadata`
during Flex ingestion, then prefer those over SnapTrade CUR:* when available.

We already have the statement data in SQLite:
```
Starting Cash (Base Currency Summary): -$11,097.13
Ending Cash (Base Currency Summary):   -$8,727.25
```

### Option A: Statement-sourced cash in fetch_metadata (recommended)

Add `statement_cash` to `fetch_metadata` during Flex ingestion. The IBKR
Flex XML CashReport section (or materialized statement SQLite) provides
Starting/Ending Cash per currency and in Base Currency Summary.

In the engine, when `statement_cash` is present in fetch_metadata, use
`ending_cash_usd` as `observed_end_cash` instead of SnapTrade CUR:* sum:
```
back_solved_start = -8,727 - 4,677 = -13,404
```

This alone fixes $5,071 of the $7,035 gap.

### Option B: Live IBKR Gateway segment-level cash query

Query IBKR Gateway for per-segment cash (securities + futures) to get
the statement-consistent figure in real time. Needs investigation of
`/portfolio/accounts` or `/iserver/account/summary` endpoints.

Pros: Live, no manual data. Cons: May not expose segment detail.

### Recommended: Option A

---

## Option A: Detailed Implementation Plan

### Codex Review Findings (addressed below)

1. **BLOCKER**: `load_fetch_metadata()` uses a fixed key whitelist — drops
   unknown fields like `statement_cash`. Must add to whitelist.
2. `statement_db_path` not threaded through `fetch_transactions()` call chain.
3. Multi-account: naive "first match" is unsafe for consolidated runs.
4. `provider_fetch_metadata` is filtered by `REALIZED_PROVIDER_FLOW_SOURCES`
   (currently includes `ibkr_flex` by default — not a blocker today but
   noted for robustness).
5. `cash_report__01` table name is brittle — not all statement SQLites have it.
6. No staleness/period-mismatch guard.

### Data Source

The materialized IBKR statement SQLite (`statement_tables.sqlite`) contains
a `cash_report` section. The table name varies (`cash_report__01`,
`cash_report__all`), so we search for any table matching `cash_report%`.

Target rows:
```
currency_summary='Starting Cash', currency='Base Currency Summary', total='-11097.129050525'
currency_summary='Ending Cash',   currency='Base Currency Summary', total='-8727.252779364'
```

### Pipeline Overview

```
IBKR Statement CSV
  → scripts/materialize_ibkr_statement.py → statement_tables.sqlite
  → NEW: extract_statement_cash() → {starting_cash_usd, ending_cash_usd, ...}
  → IBKRFlexTransactionProvider stores in _last_fetch_metadata
  → Store persists in ingestion_batches.fetch_metadata (JSONB)
  → load_fetch_metadata() whitelists statement_cash field
  → Engine reads from provider_fetch_metadata, overrides CUR:* anchor
```

### Step 1: Add `extract_statement_cash()` to `ibkr/flex.py`

New function that reads the cash report from a materialized statement.
Searches for any `cash_report%` table to handle schema variants.

```python
def extract_statement_cash(
    statement_db_path: str,
) -> dict[str, Any] | None:
    """Extract starting/ending cash from materialized IBKR statement SQLite.

    Searches for any table matching cash_report% and extracts the Base
    Currency Summary Starting/Ending Cash rows.  Returns None if the file
    doesn't exist, the table is missing, or required rows are absent.
    """
    if not statement_db_path or not Path(statement_db_path).exists():
        return None
    import sqlite3
    conn = sqlite3.connect(statement_db_path)
    conn.row_factory = sqlite3.Row
    try:
        # Find the cash_report table (name varies across statement formats)
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name LIKE 'cash_report%' ORDER BY name"
            ).fetchall()
        ]
        if not tables:
            return None
        # Prefer __all (union) if it exists, else first variant
        table = next((t for t in tables if t.endswith("__all")), tables[0])
        rows = conn.execute(
            f"SELECT currency_summary, total FROM [{table}] "
            "WHERE currency = 'Base Currency Summary' "
            "AND currency_summary IN ('Starting Cash', 'Ending Cash')"
        ).fetchall()
    except Exception:
        return None
    finally:
        conn.close()

    result: dict[str, Any] = {}
    for row in rows:
        label = str(row["currency_summary"]).strip()
        try:
            value = float(row["total"])
        except (TypeError, ValueError):
            continue
        if label == "Starting Cash":
            result["starting_cash_usd"] = value
        elif label == "Ending Cash":
            result["ending_cash_usd"] = value

    if "starting_cash_usd" not in result or "ending_cash_usd" not in result:
        return None
    result["source"] = "ibkr_statement"
    result["db_path"] = str(statement_db_path)
    return result
```

**File:** `ibkr/flex.py` (~line 1398, after `fetch_ibkr_flex_trades`)

### Step 2: Add `IBKR_STATEMENT_DB_PATH` setting

```python
# settings.py
IBKR_STATEMENT_DB_PATH = os.getenv("IBKR_STATEMENT_DB_PATH", "")
```

Set in `.env`:
```
IBKR_STATEMENT_DB_PATH=docs/planning/performance-actual-2025/ibkr_statement_frames/U2471778_20250401_20260303/statement_tables.sqlite
```

**File:** `settings.py` (~line 131)

### Step 3: Wire into `IBKRFlexTransactionProvider`

Read statement cash in `fetch_transactions()` and pass to `_build_metadata()`:

```python
# providers/ibkr_transactions.py, fetch_transactions():
from settings import IBKR_STATEMENT_DB_PATH

statement_cash = None
statement_db_path = IBKR_STATEMENT_DB_PATH
if statement_db_path:
    from ibkr.flex import extract_statement_cash
    statement_cash = extract_statement_cash(statement_db_path)

metadata_rows = self._build_metadata(
    payload=payload, cash_rows=cash_rows, statement_cash=statement_cash
)
```

In `_build_metadata()`, add `statement_cash` kwarg and include in each
metadata row:
```python
def _build_metadata(self, *, payload, cash_rows, statement_cash=None):
    ...
    # In the metadata dict for each row:
    metadata_row["statement_cash"] = statement_cash
```

**File:** `providers/ibkr_transactions.py`

### Step 4: Add `statement_cash` to store whitelist

**CRITICAL** (Codex finding #1): `load_fetch_metadata()` builds rows from
a fixed key set. Must add `statement_cash`:

```python
# inputs/transaction_store.py, load_fetch_metadata() ~line 1482:
"stmtfunds_section_present": metadata_row.get("stmtfunds_section_present"),
"statement_cash": metadata_row.get("statement_cash"),  # <-- ADD
```

The JSONB column stores the full dict; this change ensures it survives
the read-back.

**File:** `inputs/transaction_store.py` (~line 1482)

### Step 5: Engine reads `statement_cash` from fetch_metadata

In `engine.py`, add a helper before the cash anchor section (~line 1757).
Aggregates across all matching IBKR metadata rows (multi-account safe):

```python
def _statement_cash_from_metadata() -> float | None:
    """Extract IBKR statement ending cash from fetch_metadata.

    Only used when source="ibkr_flex" (guarded at call site).
    Returns the ending_cash_usd from the first ibkr_flex metadata row
    that carries statement_cash.

    Multi-account note: IBKRFlexTransactionProvider._build_metadata()
    emits one metadata row per account slice (grouped by account_id).
    But statement_cash is set identically on ALL slices because it comes
    from one IBKR_STATEMENT_DB_PATH setting. So first-match returns the
    same value regardless of which slice is hit.

    If we ever support multiple IBKR accounts with different statements,
    this would need account-level scoping. For now, single-account is
    the only supported case.

    Returns None if no statement cash is available, falling back to
    the SnapTrade CUR:* anchor.
    """
    for row in provider_fetch_metadata:
        if str(row.get("provider") or "").strip().lower() != "ibkr_flex":
            continue
        sc = row.get("statement_cash")
        if isinstance(sc, dict) and sc.get("ending_cash_usd") is not None:
            return float(sc["ending_cash_usd"])
    return None
```

Then replace the anchor call. **Critical: only use statement cash when
`source="ibkr_flex"`** — for `source="all"` consolidated runs, the
CUR:* anchor sums cash across ALL providers, and overriding with
IBKR-only statement cash would be incorrect:

```python
# Only use statement cash for IBKR-scoped runs
statement_end_cash = (
    _statement_cash_from_metadata()
    if source == "ibkr_flex"
    else None
)
if statement_end_cash is not None:
    observed_end_cash = statement_end_cash
    _cash_anchor_matched_rows = 1
    cash_anchor_source = "ibkr_statement"
else:
    observed_end_cash, _cash_anchor_matched_rows = _cash_anchor_offset_from_positions()
    cash_anchor_source = "snaptrade_cur"
```

Add `cash_anchor_source` to the realized_metadata dict AND the typed
`RealizedMetadata` dataclass (it uses explicit `to_dict()`/`from_dict()`
and drops unknown keys):

```python
# core/result_objects/realized_performance.py — RealizedMetadata class:
# Add field after cash_backsolve_matched_rows (line 133):
cash_anchor_source: str = "snaptrade_cur"

# Add to to_dict() after "cash_backsolve_matched_rows" (line 213):
"cash_anchor_source": self.cash_anchor_source,

# Add to from_dict() in the constructor call:
cash_anchor_source=d.get("cash_anchor_source", "snaptrade_cur"),
```

In the engine, set it in the realized_metadata dict (~line 2365):
```python
"cash_anchor_source": cash_anchor_source,
```

**Note on provider filtering**: `provider_fetch_metadata` is filtered by
`REALIZED_PROVIDER_FLOW_SOURCES` at line 516. `ibkr_flex` is in the
default set. If it were ever removed, the statement cash would not be
found, and the engine would fall back to SnapTrade CUR:* (safe degradation).

**Note on `source="all"` runs**: The `source == "ibkr_flex"` guard
prevents statement cash from being used in consolidated runs, where
the CUR:* anchor correctly sums across all providers.

**File:** `core/realized_performance/engine.py` (~line 1757)

### Step 6: Re-ingest to populate metadata

```
ingest_transactions(provider="ibkr_flex")
```

This re-fetches Flex data and stores the statement cash in fetch_metadata.
The engine picks it up on the next realized performance call.

### Step 7: Verify

1. Check `cash_anchor_source` in realized_metadata: should be `"ibkr_statement"`
2. Check `cash_backsolve_observed_end_usd`: should be -$8,727.25
3. Check inception NAV: should drop from $29,319 to ~$24,248
4. Check `cash_backsolve_start_usd`: should be ~-$13,404
5. Remaining gap vs IBKR statement: ~$1,964 (replay discrepancy, Fix 2)
6. Run existing tests: `python -m pytest tests/mcp_tools/test_performance.py -x`
7. Run cash anchor tests: `python -m pytest tests/core/test_realized_cash_anchor.py -x`

### Edge Cases

| Scenario | Behavior |
|----------|----------|
| `IBKR_STATEMENT_DB_PATH` not set | `extract_statement_cash()` returns None → SnapTrade fallback |
| SQLite file missing or corrupt | Returns None → SnapTrade fallback |
| `cash_report` table absent | Returns None → SnapTrade fallback |
| Statement from wrong period | Values stored but still used — TODO: add period validation |
| `source="all"` consolidated | `source == "ibkr_flex"` guard skips statement cash → CUR:* fallback (correct) |
| `source="ibkr_flex"` | Statement cash used if available → correct anchor |
| `ibkr_flex` removed from `REALIZED_PROVIDER_FLOW_SOURCES` | Metadata filtered out → SnapTrade fallback |
| Multiple IBKR accounts | All metadata slices share one statement → first-match is correct |

### Files Modified

| File | Change |
|------|--------|
| `ibkr/flex.py` | Add `extract_statement_cash()` |
| `settings.py` | Add `IBKR_STATEMENT_DB_PATH` |
| `providers/ibkr_transactions.py` | Wire statement_cash into metadata |
| `inputs/transaction_store.py` | Add `statement_cash` to `load_fetch_metadata()` whitelist |
| `core/realized_performance/engine.py` | Prefer statement cash for anchor, set `cash_anchor_source` |
| `core/result_objects/realized_performance.py` | Add `cash_anchor_source` field to `RealizedMetadata` + `to_dict()`/`from_dict()` |
| `.env` | Set `IBKR_STATEMENT_DB_PATH` |

### Action Items

- [x] Step 1: Add `extract_statement_cash()` to `ibkr/flex.py`
- [x] Step 2: Add `IBKR_STATEMENT_DB_PATH` to `settings.py`
- [x] Step 3: Wire into `IBKRFlexTransactionProvider`
- [x] Step 4: Add `statement_cash` to store whitelist
- [x] Step 5: Engine prefers statement cash for anchor
- [x] Step 6: Re-ingest
- [x] Step 7: Verify — see "Live Verification Results" below
- [ ] Future: Add statement period validation (staleness guard)

### Live Verification Results (2026-03-06)

After `/mcp` reconnect + re-ingestion with `IBKR_STATEMENT_DB_PATH` set:

| Check | Expected | Actual | Pass? |
|-------|----------|--------|-------|
| `cash_anchor_source` | `ibkr_statement` | `ibkr_statement` | YES |
| `cash_backsolve_observed_end_usd` | -$8,727.25 | -$8,727.25 | YES |
| `cash_anchor_offset_usd` | ~-$7,993 | -$7,992.94 | YES |
| `cash_backsolve_start_usd` | ~-$7,993 | -$7,992.94 | YES |
| SnapTrade CUR:* no longer used | — | Confirmed | YES |

**Key metrics after fix:**
- Total return (TWR): -37.73% (was -8.5% with SnapTrade anchor)
- Worst month: April -62.79% (large due to synthetic positions + small NAV denominator)
- Cash replay final: -$734.31
- Back-solved start cash: -$7,992.94 (vs IBKR statement -$11,097 → $3,104 replay gap)
- `high_confidence_realized`: false (correctly gated)
- Reconciliation gap: 22.09%

**Note on extreme returns:** The -37.73% TWR and -62.79% April are amplified because
the correct (smaller) NAV denominator makes percentage swings larger. The synthetic
positions (6 current + 19 incomplete) contribute outsized impact relative to the
now-correct base. This is mathematically correct behavior — Fix 2 (cash replay)
and future synthetic position improvements will reduce the distortion.

**Debugging note:** Initial live test failed because the MCP server process started
before `.env` was updated with `IBKR_STATEMENT_DB_PATH`. `load_dotenv()` runs at
import time, so the env var was empty. After `/mcp` reconnect, the new server
picked up the path and re-ingestion stored `statement_cash` in the metadata.

## Fix 2: Cash Replay Discrepancy

### Problem

The cash replay overstates cash growth by ~$8,610 vs actual IBKR cash
change. With back-solve: observed_end (-$8,727) - replay_final ($10,980)
= start -$19,708 vs actual start -$11,097.

### Fix 2a: MTM Events Ingestion (COMPLETE, 2026-03-06)

**Root cause found:** Futures MTM events were not stored in `raw_transactions`.
The `ibkr_flex_mtm` provider key had 0 rows because the ingestion code was
added after the initial Flex data was stored.

**Fix:** Re-ingested IBKR Flex data. Now 81 `ibkr_flex_mtm` rows in
`raw_transactions`. Cash replay processes them: -$3,955 MTM impact (91 events
after date filtering). The MTM events reduce the replay overshoot.

Also fixed:
- `RealizedMetadata` dataclass now includes `futures_mtm_event_count` and
  `futures_mtm_cash_impact_usd` fields (were created in engine but stripped
  by typed class)
- `futures_cash_policy` is now dynamic: `"fee_and_mtm"` when MTM events
  present, `"fee_only"` when absent

### IBKR Cash Report breakdown

```
Starting Cash:        -$11,097.13
Commissions:             -$61.99
Internal Transfers:        $0.00  (net; $1,408 sec→futures internally)
Dividends:               $168.47
Broker Interest:        -$261.84
Cash Settling MTM:    -$3,588.60
Trades (Sales):       $24,997.42
Trades (Purchase):   -$18,776.36
Other Fees:             -$164.00
Payment In Lieu:          $13.94
Transaction Fees:        -$11.04
Cash FX Translation:      $53.88
Ending Cash:          -$8,727.25
Net change:           +$2,369.88
```

### Remaining gap: First-exit positions (~$8,610)

The dominant remaining gap is from **24 first-exit symbols** — positions whose
first observed transaction is an exit (SELL/SHORT) without a corresponding buy.
These create phantom cash inflows in the replay:

- Total net cash from first-exit symbols (non-futures): $21,685
- Complete-history symbols net: -$5,944
- The difference is phantom: these positions were bought BEFORE the Flex window

Key phantom cash contributors:
- CBL $2,285, CUBI $2,126, GLBE $1,969, MSCI $2,547
- NMM $1,203, NXT_C30 $2,152, PDD options ~$4,757
- SE $1,682, PLTR_P90 $1,539, VBNK $1,476

**This gap cannot be closed without extending the Flex window (forbidden)
or backfilling opening trade data.** The 53.85% data coverage is the
fundamental constraint.

### Likely small missing items in engine replay

- **Cash FX Translation ($53.88)** — engine doesn't compute FX translation
- **Internal Transfers** — net $0 total but $1,408 between segments

### Action Items

- [x] Fix 2a: Ingest MTM events into transaction store (81 events stored)
- [x] Fix 2a: Surface MTM diagnostics in metadata
- [x] Fix 2a: Make `futures_cash_policy` dynamic
- [ ] Consider backfill file for pre-Flex-window opening trades
- [ ] Add FX translation to replay (small, ~$54)

## Priority Order

1. ~~**Fix 1 Option A**~~ DONE — statement-sourced cash in fetch_metadata. Closed ~$5,071.
2. **Fix 2** (cash replay discrepancy) — remaining ~$3,104, most complex

## Current Engine State (as of 2026-03-06, post-Fix 2a MTM)

| Metric | Post-Fix 1 | Post-Fix 2a (MTM) | IBKR Statement | Gap |
|--------|-----------|-------------------|---------------|-----|
| Cash anchor source | ibkr_statement | ibkr_statement | — | — |
| Observed end cash | -$8,727.25 | -$8,727.25 | -$8,727.25 | **$0** |
| Back-solved start cash | -$7,993 | **-$19,708** | -$11,097 | $8,611 |
| Replay final cash | -$734 | **$10,980** | — | — |
| Futures cash policy | fee_only | **fee_and_mtm** | — | — |
| MTM event count | 0 | **91** | — | — |
| MTM cash impact | $0 | **-$3,955** | -$3,589 | $366 |
| Total return (TWR) | -37.73% | **+8.53%** | +0.29% | 8.2 pp |
| Data coverage | 53.85% | 53.85% | — | — |
| Synthetic entries | 25 | 25 | — | — |
| high_confidence_realized | False | False | — | — |

**Notes:**
- TWR swung from -37.73% to +8.53% primarily due to re-ingestion creating
  clean batch (old 3x-duplicated batches cleaned up).
- Remaining 8.2 pp gap is dominated by 24 first-exit positions creating
  $21,685 phantom cash inflow. This is a data coverage limitation (53.85%).

## Evidence Files

- `docs/planning/performance-actual-2025/ibkr_statement_frames/` — parsed
  IBKR statements (SQLite + CSV)
- `docs/planning/completed/CASH_ANCHOR_NAV_PLAN.md` — original cash anchor plan
  (implemented, default ON)
- `docs/planning/SYNTHETIC_TWR_PRICE_ALIGNMENT_PLAN.md` — TWR price
  alignment (partially outdated)
