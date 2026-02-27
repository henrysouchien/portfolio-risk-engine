# Fix Cash Replay: UNKNOWN Filter + Futures Margin Awareness

## Context

The realized performance engine reports **+86.61%** when actual broker returns are **-8% to -12%** (~100pp off). Root cause: `derive_cash_and_external_flows()` replays ALL transactions as cash events with full notional, but `build_position_timeline()` already filters UNKNOWN/fx_artifact from positions. This asymmetry creates phantom cash volume that triggers the inference engine to inject fake contributions/withdrawals into the Modified Dietz denominator.

Three independent bugs compound in `derive_cash_and_external_flows()` (lines 1220-1333 of `core/realized_performance_analysis.py`):

| Bug | Phantom Volume | Priority | This Plan? |
|---|---|---|---|
| Plaid UNKNOWN trades (unresolved bonds/funds) | $4,032,733 | P1 | Yes |
| Futures notional amplification (MHI, ZF, MGC) | $475,000 | P1 | Yes |
| Synthetic position cash inflation | $85,000 | P2 | No (follow-up) |

Portfolio size is ~$160K. The phantom volume dwarfs real capital, causing massive false contributions/withdrawals in Modified Dietz.

## Root Cause Detail

### Bug 1: UNKNOWN-symbol transactions

The Plaid normalizer (`providers/normalizers/plaid.py:250`) fails to resolve `security_id` for bonds and funds, producing 54 transactions with `symbol="UNKNOWN"`. These include U.S. Treasury Notes ($1M+ notional) and BlackRock fund reinvestments.

`build_position_timeline()` already filters these at line 982:
```python
if instrument_type in {"fx_artifact", "unknown"}:
    filtered_keys.add(key)
    continue
```

But `derive_cash_and_external_flows()` replays ALL transactions — it never checks `symbol` or `instrument_type`. The $4M phantom volume triggers the inference engine (line 1317) to inject fake contributions.

### Bug 2: Futures notional amplification

Futures trades use full notional value in the cash replay, but futures are margined instruments — a BUY doesn't withdraw cash. Specific trades:
- **MHI** (Mini Hang Seng): 10 contracts = $236,950
- **ZF** (5-Year Treasury): $108,164
- **MGC** (Micro Gold): ~$30K per round trip

The cash replay at lines 1296-1303 treats all instrument types identically:
```python
if event_type == "BUY":
    cash -= (event["price"] * event["quantity"] + event["fee"]) * fx
```

This causes March 2025 (+30.9%) and April 2025 (+31.8%) — nearly all of the reported +86.61%.

**Critical constraints (from Codex review):**
1. Futures P&L flows *only* through the cash replay via BUY/SELL price differences. Cannot zero out notional — would lose P&L.
2. Futures and equity events are interleaved on the same day (5 of 26 trade days). Cannot simply skip inference per-event — need to gate inference while futures exposure is open.

### Actual futures trade data (from IBKR Flex)

```
2025-02-25  MHI   BUY   10 @ 22,770
2025-02-27  MHI   SELL  10 @ 23,687    ← round-trip, +$9,170
2025-03-10  MES   SELL   5 @ 5,678     ← opening short (no close in window)
2025-03-13  MHI   BUY   10 @ 23,695
2025-03-21  ZF    BUY 1000 @ 108.16
2025-03-27  MGC   SELL  10 @ 3,046.50
2025-04-01  MGC   BUY   10 @ 3,151.20
2025-04-04  MGC   SELL  10 @ 3,041.20  ← interleaved with equity on same day
2025-04-07  MHI   SELL  10 @ 20,632    ← interleaved with equity on same day
2025-04-09  ZF    SELL 1000 @ 108.20   ← interleaved with 13 equity trades
2025-04-14  MGC   BUY   10 @ 3,225.90
2025-05-28  MGC   SELL  10 @ 3,298     ← round-trip complete
```

5 dates have both futures and non-futures trades. This confirms we need the gated inference approach.

## Changes

### File 1: `core/realized_performance_analysis.py`

#### A. Event builder loop (lines 1238-1251) — filter UNKNOWN/fx_artifact/empty-symbol

In `derive_cash_and_external_flows()`, modify the `for txn in fifo_transactions:` loop:

1. Call existing `_infer_instrument_type_from_transaction(txn)` (line 84) on each transaction
2. If instrument type is `"unknown"` → `continue` (skip entirely)
3. If instrument type is `"fx_artifact"` → `continue` (skip — symmetry with `build_position_timeline`)
4. If `symbol` key is present but empty → `continue` (mirrors timeline filtering)
5. Carry `is_futures` flag and `symbol` into the event dict
6. Track counts for optional warnings

```python
    _skipped_unknown = 0
    _skipped_fx = 0
    _futures_count = 0

    for txn in fifo_transactions:
        date = _to_datetime(txn.get("date"))
        if date is None:
            continue

        inst_type = _infer_instrument_type_from_transaction(txn)

        if inst_type == "unknown":
            _skipped_unknown += 1
            continue
        if inst_type == "fx_artifact":
            _skipped_fx += 1
            continue

        symbol = str(txn.get("symbol") or "").strip()
        if "symbol" in txn and not symbol:
            _skipped_unknown += 1
            continue

        is_futures = inst_type == "futures"
        if is_futures:
            _futures_count += 1

        events.append(
            {
                "date": date,
                "event_type": str(txn.get("type", "")).upper(),
                "price": _as_float(txn.get("price"), 0.0),
                "quantity": abs(_as_float(txn.get("quantity"), 0.0)),
                "fee": abs(_as_float(txn.get("fee"), 0.0)),
                "currency": str(txn.get("currency") or "USD").upper(),
                "is_futures": is_futures,
                "symbol": symbol,
            }
        )
```

#### B. Cash replay loop (lines 1285-1331) — gated inference while futures exposure is open

**Design: Track open futures exposure per-symbol. Suppress inference while any futures position is open.**

Futures BUY/SELL still affect `cash` normally (preserving P&L via price differences). But the inference engine (lines 1317-1321) is suppressed whenever the portfolio has open futures notional. Once all futures round-trips close (total open quantity = 0), inference resumes and sees the true cash balance including net futures P&L.

```python
    cash = 0.0
    outstanding_injections = 0.0
    cash_snapshots: List[Tuple[datetime, float]] = []
    external_flows: List[Tuple[datetime, float]] = []
    provider_mode = bool(provider_flow_events)
    inference_enabled = ((not provider_mode) or (not disable_inference_when_provider_mode)) and not force_disable_inference

    # Track open futures exposure to gate inference.
    # Key: symbol, Value: net signed quantity (BUY positive, SELL/SHORT negative).
    _futures_positions: Dict[str, float] = {}

    for event in events:
        fx = _event_fx_rate(event.get("currency", "USD"), event["date"], fx_cache)
        event_type = event["event_type"]
        is_futures = event.get("is_futures", False)

        # --- Cash impact (UNCHANGED from current code) ---
        if event_type == "BUY":
            cash -= (event["price"] * event["quantity"] + event["fee"]) * fx
        elif event_type == "SELL":
            cash += (event["price"] * event["quantity"] - event["fee"]) * fx
        elif event_type == "SHORT":
            cash += (event["price"] * event["quantity"] - event["fee"]) * fx
        elif event_type == "COVER":
            cash -= (event["price"] * event["quantity"] + event["fee"]) * fx
        elif event_type == "INCOME":
            cash += event.get("amount", 0.0) * fx
        elif event_type == "PROVIDER_FLOW":
            signed_amount = event.get("amount", 0.0) * fx
            cash += signed_amount
            if bool(event.get("is_external_flow")):
                external_flows.append((event["date"], signed_amount))

        # --- Track open futures positions ---
        if is_futures:
            sym = event.get("symbol", "")
            qty = event["quantity"]
            if event_type in ("BUY", "COVER"):
                _futures_positions[sym] = _futures_positions.get(sym, 0.0) + qty
            elif event_type in ("SELL", "SHORT"):
                _futures_positions[sym] = _futures_positions.get(sym, 0.0) - qty
            # Clean up flat positions
            if sym in _futures_positions and abs(_futures_positions[sym]) < 1e-9:
                del _futures_positions[sym]

        # --- Inference: gated while futures exposure is open ---
        apply_inferred_adjustments = inference_enabled
        has_open_futures = bool(_futures_positions)

        if apply_inferred_adjustments and not has_open_futures and cash < 0:
            injection = abs(cash)
            external_flows.append((event["date"], injection))
            outstanding_injections += injection
            cash = 0.0

        if apply_inferred_adjustments and not has_open_futures and cash > 0 and outstanding_injections > 0:
            withdrawal = min(cash, outstanding_injections)
            if withdrawal > 0:
                external_flows.append((event["date"], -withdrawal))
                cash -= withdrawal
                outstanding_injections -= withdrawal

        cash_snapshots.append((event["date"], cash))
```

**Walk-through with actual data:**

| Date | Event | cash | _futures_positions | has_open? | Inference? |
|---|---|---|---|---|---|
| 2025-02-25 | MHI BUY 10@22770 | -$227,700 | {MHI: 10} | Yes | Suppressed |
| 2025-02-27 | MHI SELL 10@23687 | -$227,700 + $236,870 = +$9,170 | {} | No | Cash > 0, no injection needed. $9,170 P&L preserved. |
| 2025-03-10 | MES SELL 5@5678 | +$9,170 + $28,390 = +$37,560 | {MES: -5} | Yes | Suppressed |
| 2025-03-10 | GLBE SELL (equity) | +$37,560 + proceeds | {MES: -5} | Yes | Suppressed (MES still open) |
| 2025-03-13 | MHI BUY 10@23695 | -$199,390 | {MES:-5, MHI:10} | Yes | Suppressed |
| ... | (more events) | ... | ... | ... | ... |
| 2025-05-28 | MGC SELL 10@3298 | ... | {} | No | Inference resumes. Sees true cash with all P&L. |

**Key property:** When the last futures position closes, inference fires on that event (or the next one), seeing the true cumulative cash balance with all futures P&L baked in.

#### C. Function signature — add optional `warnings` parameter

```python
def derive_cash_and_external_flows(
    ...,
    warnings: Optional[List[str]] = None,
) -> Tuple[...]:
```

After the event builder loop, append warnings if filtering occurred.

#### D. End-of-stream handling

After the main loop, if `_futures_positions` is still non-empty (unclosed futures at end of replay window), emit a warning:

```python
    if warnings is not None and _futures_positions:
        open_syms = ", ".join(sorted(_futures_positions.keys()))
        warnings.append(
            f"Cash replay: {len(_futures_positions)} open futures position(s) at end of "
            f"replay ({open_syms}). Inference was suppressed during open period."
        )
```

### File 2: `tests/core/test_realized_performance_analysis.py`

#### E. New unit tests (12 tests)

| Test | What it verifies |
|---|---|
| `test_derive_cash_skips_unknown_symbol_transactions` | UNKNOWN-symbol txns have zero cash impact; warning emitted |
| `test_derive_cash_skips_empty_symbol_transactions` | Empty-symbol txns (key present, value blank) filtered |
| `test_derive_cash_skips_fx_artifact_transactions` | FX artifact txns (e.g. USD.CAD) filtered |
| `test_derive_cash_futures_suppresses_inference_while_open` | Futures BUY: no injection while position open |
| `test_derive_cash_futures_round_trip_preserves_pnl` | BUY+SELL round-trip: P&L stays in cash, no phantom flows |
| `test_derive_cash_futures_close_resumes_inference` | After futures close, inference fires normally on next event |
| `test_derive_cash_futures_loss_then_equity_buy` | Futures loss: inference catches it on next equity event |
| `test_derive_cash_futures_profit_reduces_equity_injection` | Futures profit offsets equity BUY: smaller injection |
| `test_derive_cash_interleaved_futures_equity_same_day` | Equity event between futures open and close: inference suppressed |
| `test_derive_cash_multi_futures_symbols` | Multiple futures symbols: inference suppressed until ALL close |
| `test_derive_cash_unclosed_futures_end_of_stream` | Warning emitted when futures remain open at end |
| `test_derive_cash_explicit_instrument_type_futures` | Explicit `instrument_type="futures"` field works |

#### ~~F. Fix pre-existing test mock bug~~ — ALREADY DONE

The `"monthly_returns": {}` mock fix is already applied in the uncommitted institution-scoping changes. No action needed.

## Existing tests: why they pass unchanged

The 5 existing `test_derive_cash_*` tests use txn dicts without `symbol`, `instrument_type`, or `is_futures` fields:
- `_infer_instrument_type_from_transaction()` returns `"equity"` (default)
- `"symbol" in txn` is `False` → empty-symbol filter doesn't trigger
- `event.get("is_futures", False)` returns `False` → `_futures_positions` stays empty → inference runs normally
- All existing behavior preserved.

## Key functions reused (no changes needed)

| Function | Location | Role |
|---|---|---|
| `_infer_instrument_type_from_transaction(txn)` | `core/realized_performance_analysis.py:84` | Detects futures, unknown, fx_artifact, options |
| `coerce_instrument_type()` | `trading_analysis/instrument_meta.py` | Normalizes instrument type strings |
| `build_position_timeline()` filtering | `core/realized_performance_analysis.py:982` | Existing UNKNOWN/fx_artifact filter (model) |

## Verification

1. `pytest tests/core/test_realized_performance_analysis.py -v` — all existing + new tests pass
2. `pytest tests/ --ignore=tests/api -q` — full suite green
3. Manual: `python3 tests/utils/show_api_output.py "get_performance(mode='realized', format='agent')"` — confirm returns move toward -8% to -12% range
4. Manual per-source: `source='ibkr_flex'` — confirm Mar/Apr spikes eliminated
5. Verify futures P&L preserved: IBKR Flex should still show ~-$2,050 net futures P&L

## Accepted Limitations

1. **Inference suppressed during open futures period:** While any futures position is open, the inference engine won't inject contributions even if equity trades cause cash to go negative. This means equity-driven capital needs during open-futures periods are deferred until the futures close. In our data, futures are held for days/weeks, and equity events during those windows have small notional relative to futures notional, so the deferral has minimal impact.
2. **Unclosed futures at end of replay:** If futures remain open at the end of the replay window (e.g., MES SHORT from 2025-03-10 has no close), inference stays suppressed for the remainder. A warning is emitted. This is acceptable — the alternative (triggering inference on partial futures notional) is worse.
3. **Options treated as equities:** Options use full notional (premium) in cash replay. Correct — options are fully paid.
4. **Heuristic instrument detection:** Low misclassification risk — normalizers set `instrument_type` explicitly.

## Not in scope

- **P2: Synthetic-as-starting-capital** — separate follow-up
- **P3: Plaid security_id resolution** — proper upstream fix for UNKNOWN
- **P3: `brokerage_name` population** — institution filtering
