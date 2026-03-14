# Fix Duplicate Position from FMP Ticker Mismatch (AT vs AT.L)

## Context

The realized performance engine has a $2,187 NAV gap caused by double-counting the Ashtead Group (AT.) position. The position snapshot uses raw IBKR ticker `AT.` (stripped to `AT`), while Flex transactions use the FMP-resolved ticker `AT.L`. The engine creates two timeline entries for the same 400 shares:
- `("AT", "GBP", "LONG")` — synthetic entry from position snapshot (400 shares)
- `("AT.L", "GBP", "LONG")` — from Flex buy transactions (300 + 100 shares)

## Root Cause

`_build_current_positions()` in `holdings.py` uses raw `ticker` as the dict key (line 83-86). Transaction symbols are FMP-resolved when exchange_mic is available. The engine never reconciles these two namespaces — `build_position_timeline` receives `fmp_ticker_map` but discards it (line 379). The `fmp_ticker_map` already contains `AT → AT.L` (set by holdings.py:148 from the position's `fmp_ticker` field).

## Fix (1 change in 1 file)

### Engine-level reconciliation pass

**File: `core/realized_performance/engine.py`** — insert at line ~478 (after institution/account filtering of `fifo_transactions`, before segment filtering begins at line 479)

At this point `current_positions`, `fmp_ticker_map`, and `fifo_transactions` are all shaped (store fetch + backfill + institution + account filtering done). Segment filtering (line 479+) further prunes `fifo_transactions` and `current_positions`, but the reconciliation must run first so segment filtering sees consistent keys.

The pass remaps `current_positions` keys in-place using `fmp_ticker_map` (forward: raw → FMP), only when the mapped FMP symbol has evidence in actual trade-level transaction symbols.

```python
# --- Reconcile position keys against transaction symbols via fmp_ticker_map ---
# Position snapshots use raw tickers (e.g. "AT") while Flex transactions use
# FMP-resolved symbols (e.g. "AT.L").  fmp_ticker_map has {raw: fmp} entries.
# Remap position keys to match transaction symbols when the alias confirms.
#
# Evidence is net trade delta keyed by (symbol, currency), not mere symbol presence.
# Only position-affecting trade types (BUY/SELL/SHORT/COVER) count.
# Income rows (DIVIDEND, INTEREST, etc.) may carry a different symbol variant
# and must not serve as evidence.
# A remap fires only when ALL conditions hold:
#   1. The FMP candidate has net-open same-currency trade volume (abs(delta) > 0.01)
#   2. The raw position key does NOT have net-open same-currency trade volume
#   3. Direction alignment: position shares sign matches candidate delta sign
# This prevents: false positives from old closed trades, cross-direction remaps
# (SHORT onto BUY evidence), and cross-currency remaps (GBP position onto USD trades).
_TRADE_TYPES = {"BUY", "SELL", "SHORT", "COVER"}
if fmp_ticker_map and current_positions and fifo_transactions:
    # Compute net trade delta per symbol from position-affecting trades only.
    # Positive = net long buys, negative = net short sells.
    # Only symbols with abs(delta) > 0.01 have open-position evidence.
    # Key by (symbol, currency) so evidence is currency-specific.
    # Timeline keys are (symbol, currency, direction) — same-symbol trades in a
    # different currency are NOT evidence for a position in another currency.
    _trade_delta: Dict[Tuple[str, str], float] = defaultdict(float)
    for _t in fifo_transactions:
        _sym = str(_t.get("symbol", "")).strip()
        _ttype = str(_t.get("type", "")).upper()
        if not _sym or _ttype not in _TRADE_TYPES:
            continue
        _tccy = str(_t.get("currency", "USD")).upper()
        _qty = abs(_helpers._as_float(_t.get("quantity"), 0.0))
        _key = (_sym, _tccy)
        if _ttype in ("BUY", "COVER"):
            _trade_delta[_key] += _qty
        elif _ttype in ("SELL", "SHORT"):
            _trade_delta[_key] -= _qty

    # Phase 1: Collect candidate remaps and detect multi-source collisions.
    # A "collision" is when two or more raw keys would remap to the same FMP target.
    # We count sources per target upfront so the result is iteration-order-independent.
    _candidates: Dict[str, str] = {}       # {pos_key: candidate}
    _target_sources: Dict[str, list] = {}   # {candidate: [pos_key, ...]}
    for _pos_key in list(current_positions.keys()):
        _candidate = fmp_ticker_map.get(_pos_key)
        if not _candidate or _candidate == _pos_key:
            continue
        _pos_data = current_positions[_pos_key]
        _pos_shares = _helpers._as_float(_pos_data.get("shares"), 0.0)
        _pos_ccy = str(_pos_data.get("currency", "USD")).upper()
        _cand_delta = _trade_delta.get((_candidate, _pos_ccy), 0.0)
        _raw_delta = _trade_delta.get((_pos_key, _pos_ccy), 0.0)
        if (abs(_cand_delta) > 0.01                              # candidate has same-ccy open trades
            and abs(_raw_delta) < 0.01                           # raw key: closed/no same-ccy trades
            and _pos_shares * _cand_delta > 0                    # direction alignment
            and _candidate not in current_positions):
            _candidates[_pos_key] = _candidate
            _target_sources.setdefault(_candidate, []).append(_pos_key)

    # Phase 2: Build final remap, skipping ALL sources that collide on the same target.
    _remapped: Dict[str, str] = {}
    for _pos_key, _candidate in _candidates.items():
        if len(_target_sources[_candidate]) > 1:
            continue  # Multiple raw keys → same target: skip all, don't pick a winner
        _remapped[_pos_key] = _candidate

    if _remapped:
        for _old_key, _new_key in _remapped.items():
            current_positions[_new_key] = current_positions.pop(_old_key)
        source_holding_symbols = sorted(current_positions.keys())
        warnings.append(
            f"Reconciled {len(_remapped)} position key(s) to match transaction symbols: "
            + ", ".join(f"{k} → {v}" for k, v in sorted(_remapped.items()))
        )
```

**Guards:**
- `_TRADE_TYPES` filter → only position-affecting trades (BUY/SELL/SHORT/COVER) feed into `_trade_delta`. Income rows (DIVIDEND, INTEREST, WITHHOLDING) may carry a different symbol variant and must not serve as evidence. This aligns with downstream consumers: `visible_delta` (line 841-844) filters to BUY/COVER/SELL/SHORT, segment classification (line 482-485) excludes income rows, and `build_position_timeline` (timeline.py:423) ignores non-trade types
- `_candidate != _pos_key` → identity mapping (e.g., AAPL→AAPL) skipped — no remap needed
- `abs(_cand_delta) > 0.01` where `_cand_delta = _trade_delta[(_candidate, _pos_ccy)]` → the FMP candidate has net-open trade volume **in the same currency** as the position. `_trade_delta` is keyed by `(symbol, currency)` so evidence is currency-specific. A GBP position requires GBP trade evidence; USD trades under the same symbol don't count. This aligns with timeline construction which keys by `(symbol, currency, direction)` (timeline.py:439, 491). Mere presence of old closed trades is insufficient — only a non-zero net delta counts
- `abs(_raw_delta) < 0.01` where `_raw_delta = _trade_delta[(_pos_key, _pos_ccy)]` → the raw position key does NOT have net-open same-currency trade volume. If the raw key has current open trades (delta > 0.01), the position genuinely trades under the raw key and must not be remapped. This prevents the reverse false positive (current open under raw, old closed under FMP)
- `_pos_shares * _cand_delta > 0` → direction alignment: LONG positions (shares > 0) only remap to candidates with net buys (delta > 0), SHORT positions (shares < 0) only remap to candidates with net shorts (delta < 0). Without this, a short position could be remapped onto a symbol with only BUY evidence, and `build_position_timeline` (timeline.py:439, 492) would create both `("AT.L", "GBP", "LONG")` and `("AT.L", "GBP", "SHORT")` keys. Zero-share positions (shouldn't occur in practice) also fail the check safely (product = 0)
- `_candidate not in current_positions` → prevent overwriting an existing position
- `len(_target_sources[_candidate]) > 1` → multi-source collision: skip ALL raw keys targeting the same candidate (order-independent — no key "wins" based on iteration order)

**Net-delta vs presence-set rationale:**
An earlier draft used `_txn_symbols` (a presence set) to check whether symbols appeared in trades. This has two failure modes:
1. **Suppression**: Raw key has old closed trades (BUY 100 + SELL 100, net 0) → found in presence set → remap wrongly suppressed, duplicate survives
2. **False evidence**: FMP candidate has old closed trades (net 0) → found in presence set → remap fires without current-position evidence

Net delta keyed by `(symbol, currency)` eliminates all three: only symbol+currency pairs with net-open trade volume (|delta| > 0.01) count as carrying a current position. This is consistent with `visible_delta` (engine.py:836-844) which uses the same net-delta logic, and with `build_position_timeline` (timeline.py:439, 491) which keys by `(symbol, currency, direction)`.

**Why this location (line ~478):**
- `fifo_transactions` is shaped (store/backfill/institution/account filtering complete)
- Segment filtering (line 479+) runs AFTER and further prunes both `fifo_transactions` and `current_positions` — but it needs consistent keys to do so correctly
- Runs BEFORE: segment filtering (479), visible_delta (827), seed open lots (863), timeline (893), pricing (970+)

**Why forward-only (no reverse map):**
`_build_current_positions()` keys off the `ticker` field (holdings.py:83-86) after stripping the trailing dot. For IBKR positions, this is always the raw exchange ticker (e.g., `AT`), and `fmp_ticker_map` maps `{raw: fmp}`. The forward lookup (`fmp_ticker_map.get(raw_key)`) handles this case.

**Known limitation — reverse case:** Non-IBKR providers (SnapTrade, Plaid, Schwab) may store canonical symbols as the `ticker` field. If a position key is already canonical (e.g., `AT.L`) but transactions use the raw symbol (`AT`), the forward lookup won't find a mapping (fmp_ticker_map has `{AT.L: AT.L}` = identity → skipped). This reverse case would require a separate fix (inverse fmp_ticker_map lookup). It does not occur in the current IBKR Flex data flow that causes the $2,187 bug and is deferred.

## Cascade

After reconciliation, all downstream consumers see consistent keys:
- `visible_delta[sym]` matches `current_positions.get(sym)` (engine.py:839)
- Segment filtering: `_normalize_symbol(symbol)` matches (engine.py:583-586)
- `_build_seed_open_lots`: `lot_key` matches observed_open_lots (timeline.py:274)
- `build_position_timeline`: key matches opening_qty (timeline.py:486-509)
- Pricing: `current_positions.get(ticker)` matches timeline-derived tickers (engine.py:1011, 1084)
- `source_holding_symbols` (engine.py:2728) uses reconciled symbol

## Sites Currently Broken (Fixed by This Change)

| File | Line | Issue |
|------|------|-------|
| `engine.py` | 839 | `current_positions.get("AT.L")` returns None (key is "AT") |
| `engine.py` | 1011, 1084 | Same — ticker from timeline doesn't match position key |
| `engine.py` | 583-586 | Segment filter: `_normalize_symbol("AT")` ≠ `"AT.L"` in segment_keep_symbols |
| `timeline.py` | 486-509 | Synthetic created for "AT" because opening_qty["AT"] = 0 (buys under "AT.L") |
| `timeline.py` | 261-277 | `lot_key = ("AT", ...)` doesn't match observed_open_lots `("AT.L", ...)` |

## Edge Cases

- **fmp_ticker == raw_ticker** (e.g., `AAPL`): `_candidate != _pos_key` check fails → skipped. If AAPL not in fmp_ticker_map at all, `fmp_ticker_map.get()` returns None → skipped
- **fmp_ticker missing/None**: No entry in fmp_ticker_map → no remap
- **Candidate has no trades**: `_trade_delta[("AT.L", "GBP")]` = 0 → `abs(0) > 0.01` fails → no remap. Position keeps raw key, synthetic entry created as before
- **Candidate has only closed trades** (net zero delta): e.g., BUY 100 AT.L + SELL 100 AT.L in GBP. `_trade_delta[("AT.L", "GBP")]` = 0 → no remap. Old closed same-currency FMP trades are not evidence of a current position
- **Candidate has only income rows**: DIVIDEND/INTEREST rows under AT.L excluded by `_TRADE_TYPES` filter → `_trade_delta[("AT.L", "GBP")]` = 0 → no remap
- **Raw key has current open trades** (the reverse case): Current position genuinely trades under AT (BUY 400 AT in GBP), old closed AT.L trades exist. `_trade_delta[("AT", "GBP")]` = 400 → abs > 0.01 → raw-key guard fails → no remap. This is correct: the position IS under the raw key
- **Raw key has closed trades, candidate has open trades** (the forward case — our bug): BUY 100 AT + SELL 100 AT in GBP (delta=0) plus BUY 400 AT.L in GBP (delta=400). `_trade_delta[("AT", "GBP")]`=0, `_trade_delta[("AT.L", "GBP")]`=400 → remap proceeds (AT → AT.L). Old raw closed trades form their own timeline entry showing a completed round-trip. No duplication
- **Raw key has no trades at all**: `_trade_delta[("AT", "GBP")]` = 0 → raw guard passes. If candidate has open same-currency trades → remap proceeds. This is the primary AT/AT.L scenario
- **Raw symbol only on income rows**: DIVIDEND row under AT excluded by `_TRADE_TYPES` → `_trade_delta[("AT", "GBP")]` = 0. If AT.L has GBP BUY trades → remap proceeds correctly
- **Both raw and FMP have open trades**: Both `_trade_delta[("AT", "GBP")]` and `_trade_delta[("AT.L", "GBP")]` > 0.01 → neither guard passes → no remap. Positions kept separate (both genuinely have open positions). If both are in `current_positions`, the `_candidate not in current_positions` guard also blocks
- **Direction mismatch (SHORT pos, LONG candidate)**: Position has shares=-100 (SHORT), candidate has net BUY delta=+400. `_pos_shares * _cand_delta = -100 * 400 = -40000 < 0` → no remap. Prevents creating both LONG and SHORT timeline keys for the same ticker
- **Direction mismatch (LONG pos, SHORT candidate)**: Position has shares=+400 (LONG), candidate has net SHORT delta=-100. Product < 0 → no remap
- **Currency mismatch**: Position is GBP, candidate trades are USD only. `_trade_delta[("AT.L", "GBP")]` = 0 (no GBP trades) → `abs(0) > 0.01` fails → no remap. USD trades under AT.L don't count as evidence for a GBP position
- **Mixed-currency candidate**: AT.L has GBP open trades AND an old USD closed round-trip. `_trade_delta[("AT.L", "GBP")]` = 400 (open), `_trade_delta[("AT.L", "USD")]` = 0 (closed). A GBP position checks only `("AT.L", "GBP")` → delta 400 → remap proceeds correctly. A USD position would check `("AT.L", "USD")` → delta 0 → no remap
- **Collision (existing key)**: `_candidate not in current_positions` prevents overwriting an existing position entry
- **Collision (multi-source)**: If two raw keys both map to the same FMP target (e.g., `X → Z.L` and `Y → Z.L`), `_target_sources["Z.L"]` has length 2 → BOTH are skipped. Order-independent. Unresolvable duplicate positions persist (no silent merge)
- **No transactions** (holdings-only run): `fifo_transactions` is empty → `_trade_delta` is empty → no remap
- **Alias scoped away**: If `fmp_ticker_map` has `AT → AT.L` and transactions contain `AT.L` before institution/account filtering but NOT after, then `_trade_delta` (built from the already-filtered `fifo_transactions`) won't have AT.L → candidate delta = 0 → no remap. Correct: alias-bearing transactions don't belong to current scope

## Test Plan

### New tests

1. **`test_engine_reconcile_raw_to_fmp`**: `current_positions={"AT": {...}}`, `fmp_ticker_map={"AT": "AT.L"}`, BUY transactions under `"AT.L"` (net delta > 0). Verify:
   - `current_positions` key remapped to `"AT.L"`
   - `source_holding_symbols` updated
   - Warning emitted with `"AT → AT.L"`

2. **`test_engine_no_remap_identity_mapping`**: `current_positions={"AAPL": {...}}`, `fmp_ticker_map={"AAPL": "AAPL"}`, BUY transactions under `"AAPL"`. Verify no remap (identity mapping — `_candidate == _pos_key`).

3. **`test_engine_no_remap_when_candidate_not_in_txns`**: `current_positions={"AT": {...}}`, `fmp_ticker_map={"AT": "AT.L"}`, but BUY transactions only under `"AAPL"` (no AT.L trades). Verify no remap — raw key preserved (candidate delta = 0).

4. **`test_engine_remap_with_closed_raw_trades`**: `current_positions={"AT": {...}}`, `fmp_ticker_map={"AT": "AT.L"}`, `fifo_transactions` contains BUY 100 `"AT"` + SELL 100 `"AT"` (fully closed, net delta=0) AND BUY 400 `"AT.L"` (net delta=400). Verify remap proceeds (AT → AT.L) — raw delta=0, candidate delta=400.

5. **`test_engine_no_remap_reverse_case`**: `current_positions={"AT": {...}}`, `fmp_ticker_map={"AT": "AT.L"}`, `fifo_transactions` contains BUY 400 `"AT"` (net delta=400, current open position) AND BUY 100 + SELL 100 `"AT.L"` (fully closed, net delta=0). Verify NO remap — raw key has open trades (delta > 0.01), so position genuinely trades under the raw key.

6. **`test_engine_no_remap_collision`**: `current_positions={"AT": {...}, "AT.L": {...}}`, `fmp_ticker_map={"AT": "AT.L"}`, BUY transactions under `"AT.L"`. Verify `"AT"` is NOT remapped (target already exists in current_positions).

7. **`test_engine_no_remap_no_transactions`**: `current_positions={"AT": {...}}` with empty `fifo_transactions`. Verify no remap (delta dict empty).

8. **`test_engine_no_remap_duplicate_target`**: Two position keys (`"X"`, `"Y"`) that would both remap to the same target `"Z.L"` via `fmp_ticker_map={"X": "Z.L", "Y": "Z.L"}`, BUY transactions under `"Z.L"`. Verify NEITHER key is remapped (both skipped — multi-source collision). `current_positions` retains both `"X"` and `"Y"`.

9. **`test_engine_no_remap_alias_scoped_away`**: `current_positions={"AT": {...}}`, `fmp_ticker_map={"AT": "AT.L"}`, but `fifo_transactions` (after institution/account filtering) contains NO `"AT.L"` transactions. Verify no remap — candidate delta = 0 → raw key preserved.

10. **`test_engine_remap_when_raw_only_on_income`**: `current_positions={"AT": {...}}`, `fmp_ticker_map={"AT": "AT.L"}`, `fifo_transactions` contains a DIVIDEND row with symbol `"AT"` AND a BUY row with symbol `"AT.L"`. Verify remap proceeds — DIVIDEND excluded by `_TRADE_TYPES`, so raw delta=0, candidate delta > 0.

11. **`test_engine_no_remap_candidate_only_on_income`**: `current_positions={"AT": {...}}`, `fmp_ticker_map={"AT": "AT.L"}`, `fifo_transactions` contains only a DIVIDEND row with symbol `"AT.L"` (no BUY/SELL). Verify no remap — candidate delta = 0 (income excluded by `_TRADE_TYPES`).

12. **`test_engine_no_remap_candidate_closed_trades`**: `current_positions={"AT": {...}}`, `fmp_ticker_map={"AT": "AT.L"}`, `fifo_transactions` contains BUY 100 `"AT.L"` + SELL 100 `"AT.L"` (fully closed, net delta=0). No trades under `"AT"`. Verify no remap — candidate delta=0 (net-zero closed trades are not evidence of a current position). This is the second failure mode that net-delta prevents vs a presence-set.

13. **`test_engine_no_remap_both_open`**: `current_positions={"AT": {...}}`, `fmp_ticker_map={"AT": "AT.L"}`, `fifo_transactions` contains BUY 200 `"AT"` (net delta=200) AND BUY 300 `"AT.L"` (net delta=300). Verify NO remap — both raw and candidate have net-open trades (both deltas > 0.01), so the remap is ambiguous and must not fire.

14. **`test_engine_no_remap_direction_mismatch`**: `current_positions={"AT": {"shares": -100, ...}}` (SHORT position), `fmp_ticker_map={"AT": "AT.L"}`, `fifo_transactions` contains BUY 400 `"AT.L"` (net delta=+400, LONG evidence). Verify NO remap — position is SHORT but candidate evidence is LONG (`_pos_shares * _cand_delta < 0`). Without this guard, `build_position_timeline` would create both `("AT.L", "GBP", "LONG")` and `("AT.L", "GBP", "SHORT")` keys.

15. **`test_engine_no_remap_currency_mismatch`**: `current_positions={"AT": {"shares": 400, "currency": "GBP", ...}}`, `fmp_ticker_map={"AT": "AT.L"}`, `fifo_transactions` contains BUY 400 `"AT.L"` with `currency="USD"`. Verify NO remap — `_trade_delta[("AT.L", "GBP")]` = 0 (no GBP trades for AT.L). The USD trades don't count as evidence for a GBP position.

16. **`test_engine_reconcile_source_scoped_metadata`**: Same as test 1 but with `source != "all"` (e.g., `source="ibkr_flex"`). Verify `source_holding_symbols` is updated after remap and persists through the source-scoped code path (engine.py does not recompute `source_holding_symbols` for non-"all" sources at line 2243).

17. **`test_end_to_end_no_duplicate_timeline`**: Full integration: position with `ticker="AT."`, `fmp_ticker="AT.L"`, Flex BUY transactions under `AT.L` in GBP. Run through the engine path. Verify:
   - Single timeline key `("AT.L", "GBP", "LONG")`
   - No synthetic entry for `"AT"`
   - `source_holding_symbols` contains `"AT.L"`

18. **`test_segment_filter_sees_reconciled_keys`**: Position `"AT"` with BUY transactions under `"AT.L"`, segment="equities". Verify position passes segment filter (would fail without reconciliation since `_normalize_symbol("AT")` ≠ `"AT.L"` in segment_keep_symbols).

### Regression

19. `python3 -m pytest tests/core/test_realized_performance_analysis.py -x -q` (178 tests)
20. `python3 -m pytest tests/core/test_realized_cash_anchor.py -x -q`
21. `python3 -m pytest tests/core/test_realized_performance_segment.py -x -q` (reconciliation runs immediately before segment filtering)

### Manual verification

22. Run realized performance for IBKR Flex and confirm:
    - Position timeline has `AT.L|GBP|LONG` only (no `AT|GBP|LONG`)
    - Ending NAV gap narrows by ~$2,187
