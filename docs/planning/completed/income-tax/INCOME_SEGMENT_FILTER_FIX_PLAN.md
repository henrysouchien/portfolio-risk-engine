# Income Segment Filter Fix Plan (v7)

## Problem

The realized performance engine reports **$0 income** for `segment="equities"` despite the transaction store containing 46 correct income events.

**Root cause**: `segment_keep_symbols` (engine.py:477-520) is built exclusively from **trade transactions** (BUY/SELL/SHORT/COVER). Stocks that paid dividends but were never traded within the Flex window (NVDA, V, TKO, EQT, IGIC, KINS) have no trade rows, so they're absent from `segment_keep_symbols`. The segment filter at line 636-641 then drops all their income.

**Impact**: Of 9 income symbols, only CBL (which had trades) survives. ~$307 of dividends/interest is silently zeroed out.

## Fix

### Location: `engine.py` lines 509-520

After building `segment_keep_symbols` from trade transactions, classify income-only symbols from `analyzer.income_events` and add them to `segment_keep_symbols` if they belong to the requested segment.

**This block must run BEFORE lines 512-520 and BEFORE lines 528-538.**

### Symbol Classification Rules

1. **Real tickers** (NVDA, V, TKO, etc.) — Use position `instrument_type` if available, else default to equity → STS `get_asset_classes()` → `_assign_canonical_segment()`. **No futures catalog fallback** (avoids MHI/Z collisions).

2. **Pseudo/placeholder symbols** — Account-level income. Directly included in `segment_keep_symbols` for equities only. No STS lookup.

3. **Non-segment symbols** — Go to `excluded_symbols_set`.

### Implementation

Replace lines 512-520 with:

```python
# --- Classify income-only symbols (positions that paid dividends/interest
# --- but had no trades within the analysis window).
_income_only_symbols: set[str] = set()
for inc in getattr(analyzer, "income_events", []):
    sym = _normalize_symbol(getattr(inc, "symbol", ""))
    if sym and sym not in symbol_instrument_types:
        _income_only_symbols.add(sym)

if _income_only_symbols:
    # Build a normalized-key lookup for current_positions instrument_type.
    _pos_itype_map: Dict[str, str] = {}
    for pos_key, pos_val in current_positions.items():
        norm_key = _normalize_symbol(pos_key)
        if norm_key:
            itype = str((pos_val or {}).get("instrument_type", "")).strip().lower()
            if itype and itype not in {"", "unknown"}:
                _pos_itype_map[norm_key] = itype

    _income_instrument_types: Dict[str, str] = {}
    _pseudo_income_symbols: set[str] = set()
    for sym in _income_only_symbols:
        # 1. Position metadata always wins (real instrument_type)
        if sym in _pos_itype_map:
            _income_instrument_types[sym] = _pos_itype_map[sym]
            continue
        # 2. Pseudo/placeholder symbols: direct include for equities, skip STS
        if _helpers._is_pseudo_symbol(sym):
            _pseudo_income_symbols.add(sym)
            continue
        # 3. Default to equity
        _income_instrument_types[sym] = "equity"

    # Pseudo symbols go directly to equities segment (account-level income)
    if segment == "equities":
        segment_keep_symbols.update(_pseudo_income_symbols)
    else:
        excluded_symbols_set.update(_pseudo_income_symbols)

    # STS lookup for real equity/bond income symbols
    _real_income_equity_syms = sorted(
        s for s, t in _income_instrument_types.items()
        if t in (SEGMENT_INSTRUMENT_TYPES["equities"] | SEGMENT_INSTRUMENT_TYPES["bonds"])
    )
    if _real_income_equity_syms and segment in _ASSET_CLASS_SEGMENTS:
        _income_asset_classes = SecurityTypeService.get_asset_classes(
            _real_income_equity_syms
        )
        segment_asset_classes.update(_income_asset_classes)

    for sym, itype in _income_instrument_types.items():
        canonical = _assign_canonical_segment(sym, itype, segment_asset_classes)
        if canonical == segment:
            segment_keep_symbols.add(sym)
        elif canonical is not None:
            excluded_symbols_set.add(sym)

# Exclude income-only FIFO symbols not already classified
for txn in fifo_transactions:
    symbol = _normalize_symbol(txn.get("symbol"))
    if not symbol:
        continue
    if (
        _helpers._infer_instrument_type_from_transaction(txn) == "income"
        and symbol not in symbol_instrument_types
        and symbol not in segment_keep_symbols
    ):
        excluded_symbols_set.add(symbol)
```

### Helper: `_is_pseudo_symbol()` in `_helpers.py`

```python
_PSEUDO_SYMBOL_EXACT = frozenset({
    "MARGIN_INTEREST",
    "INTEREST",
    "UNRESOLVED_DIVIDEND",
    "DEPOSIT",
    "USD",
})

def _is_pseudo_symbol(symbol: str) -> bool:
    """Return True for synthetic/placeholder symbols that should not hit STS.

    Covers normalizer-emitted placeholders:
    - Exact: MARGIN_INTEREST, INTEREST, UNRESOLVED_DIVIDEND, DEPOSIT, USD
    - Prefix: UNKNOWN* (common.py), CUR:* (Schwab/Plaid cash)
    - Suffix: *IBKR MANAGED SECURITIES
    """
    s = str(symbol or "").strip().upper()
    if not s:
        return True
    if s in _PSEUDO_SYMBOL_EXACT:
        return True
    if s.startswith("UNKNOWN"):
        return True
    if s.startswith("CUR:"):
        return True
    if s.endswith("IBKR MANAGED SECURITIES"):
        return True
    return False
```

Why `USD` is in the exact set: IBKR Flex BROKERINTRCVD rows can have `symbol="USD"` when the symbol field is populated (flex.py:724 preserves it). The IBKRFlexNormalizer passes it through to income_events (ibkr_flex.py:60). STS would try to classify "USD" as a stock via FMP/AI — wrong and cache-polluting.

### Changes from v6 (Codex findings)

1. **Added `USD` to pseudo exact set** (Finding #1 — High): Bare currency symbol from IBKR BROKERINTRCVD rows now caught.

2. **Added test for ordering** (Finding #2 — Medium): Test 1 now asserts `timeline_symbols` includes the income-only position, proving it survived the `current_positions` filter.

3. **Added MHI collision regression test** (Finding #3 — Medium): Test 9 exercises MHI as income-only equity with no position metadata → should classify as equity (not futures).

4. **Removed DEPOSIT rationale** (Finding #4 — Low): DEPOSIT doesn't actually reach income events in current Plaid normalizer (rejected by `_is_income_security()`). Kept in pseudo set defensively — zero cost, protects against future normalizer changes.

### Known Limitation: Plaid descriptive bond names

Plaid can emit bond interest with descriptive names (e.g., `US Treasury Note - 4.25%`) instead of standard tickers. The upstream data quality issue (Plaid normalizer emits names, not tickers) is pre-existing. However, this fix changes behavior for income-only descriptive symbols that have **no matching trade row AND no position metadata**, on non-`all` segmented runs:

- **Before**: dropped entirely (excluded from all segments) — income lost
- **After**: defaults to `instrument_type="equity"` → runs through STS `get_asset_classes()`. If STS returns a cached/AI bond classification, routes correctly to bonds. If STS returns unknown/equity, routes to equities as fallback.

The typical outcome is misrouting to equities (STS unlikely to classify a descriptive name correctly), which is a marginal improvement over dropping entirely. The proper fix is in the Plaid normalizer (resolve to CUSIP-based tickers) — out of scope here. Test 11 documents the fallback behavior as a regression guard.

### Known Limitation: Bare non-USD currency symbols

The pseudo exact set only includes `USD`. IBKR flex.py:724 preserves whatever raw symbol is present, so bare `EUR`, `GBP`, etc. could theoretically appear on interest rows and fall through to STS. In practice, IBKR interest rows are either blank (→ MARGIN_INTEREST) or USD. If other bare currencies are observed in production, add them to `_PSEUDO_SYMBOL_EXACT`.

### Edge Cases

| Symbol | Path | Result |
|---|---|---|
| NVDA, V, TKO | Position itype or default equity → STS → equities | Included |
| MHI (equity) | No position itype → default equity → STS → equities | Correct (not futures) |
| MARGIN_INTEREST | Pseudo → direct include | Equities only |
| INTEREST | Pseudo → direct include | Equities only |
| USD (bare) | Pseudo → direct include | Equities only |
| CUR:USD | Pseudo (prefix) → direct include | Equities only |
| DEPOSIT | Pseudo → direct include | Equities only |
| UNKNOWN_XYZ | Pseudo (prefix) → direct include | Equities only |
| USD IBKR MANAGED SECURITIES | Pseudo (suffix) → direct include | Equities only |
| Bond (income only) | `_pos_itype_map` → "bond" → bonds segment | Correct |
| Futures (income only) | `_pos_itype_map` → "futures" → futures segment | Correct |
| BRK B | Not pseudo → STS → classified normally | Correct |

## Files Modified

1. **`core/realized_performance/engine.py`** — Replace lines 512-520 (~35 lines)
2. **`core/realized_performance/_helpers.py`** — Add `_is_pseudo_symbol()` (~20 lines)

## Tests

**Harness changes** to `_run_realized_segment_case()`:
- New `analyzer_income_events` param (default `[]`). Must be `NormalizedIncome` objects (the engine reads attributes like `.symbol` via `getattr()`). `FakeAnalyzer.__init__` sets `self.income_events = analyzer_income_events`.
- New helper `_ni(symbol, income_type="dividend")` → returns `NormalizedIncome(symbol=symbol, income_type=income_type, date=..., amount=5.0, ...)`.
- When `income_with_currency` is not explicitly provided, auto-derive from `analyzer_income_events` (each NormalizedIncome → dict with symbol/amount/income_type/currency).
- STS spy: `captured.setdefault("asset_class_calls", []).append(list(symbols))` (accumulate all calls).

### Test 1: `test_segment_income_only_equity_included`
- FIFO: AAPL (anchor). `analyzer_income_events`: AAPL + NVDA dividends.
- `current_positions`: {AAPL: equity, NVDA: equity}. `asset_classes`: both equity.
- `income_with_currency`: both.
- Assert: income total includes both. derive_calls income_symbols includes both.
- **Assert: `timeline_symbols` includes NVDA** (proves current_positions survived filter).

### Test 2: `test_segment_income_futures_excluded_from_equities`
- FIFO: AAPL (anchor). `analyzer_income_events`: AAPL + ES.
- `current_positions`: {AAPL: equity, ES: futures}.
- `income_with_currency`: [AAPL income, ES income].
- `asset_classes`: {AAPL: equity}.
- Assert: ES income excluded. Only AAPL in derive_calls income_symbols.

### Test 3: `test_segment_pseudo_symbols_direct_include_equities`
- FIFO: AAPL (anchor). `analyzer_income_events`: AAPL + MARGIN_INTEREST + INTEREST + CUR:USD + USD + UNKNOWN_XYZ.
- `income_with_currency`: rows for all above. `asset_classes`: {AAPL: equity}.
- Assert: all pseudo income included.
- Assert: no `asset_class_calls` entry contains any pseudo symbol.

### Test 4: `test_segment_pseudo_symbols_excluded_from_non_equities`
- FIFO: ES (futures anchor, is_futures=True). `analyzer_income_events`: ES + MARGIN_INTEREST.
- `current_positions`: {ES: futures}.
- `income_with_currency`: [ES income, MARGIN_INTEREST income].
- Assert `segment="futures"`: ES income in derive_calls, MARGIN_INTEREST excluded.

### Test 5: `test_segment_income_only_bond_routed_to_bonds`
- FIFO: BOND_A (bond trade, instrument_type="bond") — anchor.
- `analyzer_income_events`: BOND_A + BOND_X interest.
- `current_positions`: {BOND_A: bond, BOND_X: bond}.
- `income_with_currency`: [BOND_A income, BOND_X income].
- `asset_classes`: {BOND_A: bond, BOND_X: bond}.
- Assert `segment="bonds"`: both income rows in derive_calls.

### Test 6: `test_segment_income_position_key_case_insensitive`
- FIFO: AAPL (anchor). `analyzer_income_events`: [_ni(AAPL), _ni(AT.L)].
- `current_positions`: {AAPL: equity, "at.l": equity}.
- `income_with_currency`: auto-derived from analyzer_income_events.
- `asset_classes`: {AAPL: equity, AT.L: equity}.
- Assert `segment="equities"`: AT.L income included in derive_calls.

### Test 7: Update `test_segment_income_only_symbol_skipped` → `test_segment_income_only_equity_symbol_now_included`
- Add IBM to `analyzer_income_events`, `current_positions` (equity), `asset_classes`, `income_with_currency`.
- Assert: income total = AAPL + IBM. derive_calls income_symbols includes IBM.

### Test 8: `test_is_pseudo_symbol` (unit test in `_helpers`)
- True: MARGIN_INTEREST, INTEREST, UNRESOLVED_DIVIDEND, DEPOSIT, USD, CUR:USD, CUR:EUR, UNKNOWN, UNKNOWN_XYZ, USD IBKR MANAGED SECURITIES, EUR IBKR MANAGED SECURITIES, ""
- False: NVDA, AAPL, BRK B, MHI, AT.L, ES

### Test 9: `test_segment_income_mhi_collision_not_routed_to_futures`
- FIFO: AAPL (anchor). `analyzer_income_events`: [_ni(AAPL), _ni(MHI)].
- `current_positions`: {AAPL: equity} (MHI NOT in positions).
- `income_with_currency`: auto-derived from analyzer_income_events.
- `asset_classes`: {AAPL: equity, MHI: equity}.
- Assert `segment="equities"`: MHI income included (defers to STS, not futures catalog).
- Assert `segment="futures"`: MHI income NOT included (proves no futures misrouting).

### Test 10: `test_segment_pseudo_symbol_with_position_uses_instrument_type`
- FIFO: AAPL (anchor). `analyzer_income_events`: [_ni(AAPL), _ni(USD, interest)].
- `current_positions`: {AAPL: equity, USD: {instrument_type: "bond"}}.
- `income_with_currency`: auto-derived.
- `asset_classes`: {AAPL: equity, USD: bond}.
- Assert `segment="bonds"`: USD income included (position metadata "bond" takes precedence over pseudo).
- Assert `segment="equities"`: USD income excluded (not pseudo-routed to equities).
- Proves: position metadata wins over pseudo blocklist.

### Test 11: `test_segment_income_plaid_descriptive_bond_defaults_to_equities`
- FIFO: AAPL (anchor). `analyzer_income_events`: [_ni(AAPL), _ni("US Treasury Note - 4.25%", interest)].
- `current_positions`: {AAPL: equity} (no entry for descriptive name).
- `income_with_currency`: auto-derived from analyzer_income_events.
- `asset_classes`: {AAPL: equity, "US TREASURY NOTE - 4.25%": unknown}.
- Assert `segment="equities"`: descriptive bond income included (equity fallback).
- Assert `segment="bonds"`: descriptive bond income excluded (STS returns unknown → equity path).
- Documents: pre-existing Plaid normalizer issue. Behavior changed from "dropped" to "fallback to equities".

## Verification

1. `pytest tests/core/test_realized_performance_segment.py -x`
2. `pytest tests/core/test_realized_performance_analysis.py -x`
3. Live: `get_performance(mode="realized", source="ibkr_flex", segment="equities")` → income > $0
