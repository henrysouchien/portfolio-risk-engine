# Schwab Cross-Source Attribution Fix

## Sequencing Note (2026-02-26)

This document addresses the Schwab +49.76% return distortion (actual: -8.29%). It follows the P3.1 fix which resolved the IBKR regression.

Prior phases:
- **P1-P3** (various commits): Cash replay hardening series
- **P3.1** (`6c2f6e89`): Futures compensating events + incomplete trade synthetics at inception

## Problem

Schwab source-scoped analysis reports **+49.76%** total return vs broker actual of **-8.29%**. The distortion has two compounding causes:

### Cause 1: Cross-source exclusion removes 66% of portfolio value

DSU ($24K in main Schwab acct + $5K in IRA + $15K via Plaid mirror), MSCI ($7.5K Schwab + $11.5K Plaid mirror), and STWD ($9.8K Schwab + $9.2K Plaid mirror) are excluded from Schwab-scoped `current_positions` because they appear in **separate rows** from both the Schwab API (`position_source="schwab"`) and the Plaid API (`position_source="plaid"`).

The symbol-level leakage detection at line 733-737 of `_build_source_scoped_holdings()` sees each symbol reported by multiple sources (`symbol_to_sources[ticker] = {"plaid", "schwab"}`), so `len(sources) > 1` marks them as cross-source leakage → excluded.

These positions represent a large portion of the real Schwab portfolio value. Two of the three are at a loss, so their exclusion creates survivorship bias toward winners.

**Why positions appear in both sources**: The Schwab brokerage account is connected via BOTH the native Schwab API AND Plaid (which connects to Schwab-as-bank via institution "Merrill"). With `consolidate=False` (used by source-scoped performance), the positions appear as **separate rows** — one with `position_source="plaid"` (from the Plaid/Merrill connection) and one with `position_source="schwab"` (from the native Schwab API).

**Key insight**: The Plaid connection (`account_id=16Yk8NJ5E5u3...`, `brokerage_name="Merrill"`) is an **aggregator mirror** of the Schwab account. DSU/MSCI/STWD/IT appear in both because Plaid is mirroring the same underlying Schwab account. This is NOT genuine cross-source exposure (the same stock at two different brokers). The native Schwab API is authoritative.

Evidence that these ARE Schwab positions (not independent Plaid holdings):
- Schwab API returns "System transfer" entries for DSU/MSCI on Aug 24, 2024
- Schwab API returns ongoing dividend reinvestment BUYs for DSU (52 total)
- FIFO transactions include DSU 2551 shares, STWD 548 shares, MSCI 0.24 shares — all source=schwab

### Cause 2: Tiny base in early period amplifies returns

With only 4 synthetic positions in Schwab scope ($6.5K, 90% PCTY), the Apr-Dec 2024 period shows outsized monthly returns:

| Month | V_start | V_end | Return | Driver |
|-------|---------|-------|--------|--------|
| Jul 2024 | $5,515 | $6,166 | +11.80% | PCTY rally |
| Aug 2024 | $6,166 | $6,796 | +10.21% | PCTY rally |
| Oct 2024 | $7,044 | $7,896 | +12.19% | PCTY rally |
| Nov 2024 | $7,896 | $8,949 | +13.34% | PCTY rally |

These returns are mathematically correct for the positions we see, but the real Schwab account was much larger (DSU alone is $24K+). The $65K contribution in Jan 2025 normalizes the base (returns become ±1-3%/month after that), but the compounded early gains dominate the total.

**If DSU/MSCI/STWD were included in scope**, V_start would be ~$50-80K instead of $6.5K, and the PCTY rally would contribute ~1-2%/month instead of 10-13%.

## Fix

**Approach**: Two-layer fix — both at the symbol-level leakage computation and at the row-level matching.

### Semantic: Native source is authoritative over aggregator mirror

When a symbol appears in both a **native API source** (schwab, ibkr_flex) and an **aggregator source** (plaid, snaptrade), the native API is authoritative. The aggregator is just mirroring it. This is NOT cross-source leakage — it's the same position reported twice.

This applies at two levels:
1. **Symbol-level leakage** (lines 733-737): A symbol reported by `{plaid, schwab}` should NOT be treated as leakage when `source="schwab"` — the native source is authoritative. However, it SHOULD still be leakage when `source="plaid"` (the position belongs to schwab, not plaid).
2. **Row-level matching** (line 665): When `position_source="plaid,schwab"` (consolidated rows with `consolidate=True`), narrow to native source only.

### File: `core/realized_performance_analysis.py`

#### Change 1: Row-level tiebreaker in `_provider_matches_from_position_row` — line 665

This handles the `consolidate=True` case where `position_source="plaid,schwab"` appears in a single merged row.

**Before (lines 663-668):**
```python
    if primary_matches:
        return primary_matches, "primary"
    if secondary_matches:
        return secondary_matches, "secondary"
    if tertiary_matches:
        return tertiary_matches, "tertiary"
    return set(), "none"
```

**After:**
```python
    if primary_matches:
        return primary_matches, "primary"
    if secondary_matches:
        # When a position is reported by both a native API (schwab, ibkr_flex)
        # and an aggregator (plaid, snaptrade), the native API is authoritative.
        # Narrow to native sources to avoid false cross-source ambiguity.
        _NATIVE_SOURCES = {"schwab", "ibkr_flex"}
        _AGGREGATOR_SOURCES = {"plaid", "snaptrade"}
        native_in = secondary_matches & _NATIVE_SOURCES
        aggregator_in = secondary_matches & _AGGREGATOR_SOURCES
        if native_in and aggregator_in:
            secondary_matches = native_in
        return secondary_matches, "secondary"
    if tertiary_matches:
        return tertiary_matches, "tertiary"
    return set(), "none"
```

**NOTE**: This change was already implemented by Codex and is already in the codebase. No additional change needed.

#### Change 2: Symbol-level leakage native-over-aggregator exemption — line 733

This is the **main fix** for the `consolidate=False` case. When separate rows create symbol-level leakage (`symbol_to_sources[DSU] = {"plaid", "schwab"}`), exempt the symbol from leakage if the overlap is ONLY between native and aggregator sources AND the requested scope is a native source.

**Before (lines 733-737):**
```python
    symbol_level_leakage = {
        symbol
        for symbol, sources in symbol_to_sources.items()
        if source in sources and len(sources) > 1
    }
```

**After:**
```python
    _NATIVE_SOURCES = {"schwab", "ibkr_flex"}
    _AGGREGATOR_SOURCES = {"plaid", "snaptrade"}

    symbol_level_leakage = set()
    for symbol, sources in symbol_to_sources.items():
        if source not in sources or len(sources) <= 1:
            continue
        # When the overlap is only native + aggregator and the requested scope
        # is a native source, the native API is authoritative — not leakage.
        native_in = sources & _NATIVE_SOURCES
        aggregator_in = sources & _AGGREGATOR_SOURCES
        if native_in and aggregator_in and not (sources - native_in - aggregator_in):
            # Pure native-vs-aggregator overlap. The native source is authoritative.
            if source in _NATIVE_SOURCES:
                # Requesting native scope → NOT leakage (position belongs to native)
                continue
            elif source in _AGGREGATOR_SOURCES:
                # Requesting aggregator scope → still leakage (native is authoritative,
                # so the aggregator should not claim this position)
                pass
        symbol_level_leakage.add(symbol)
```

**Why this is correct:**
- `symbol_to_sources[DSU] = {"plaid", "schwab"}`, `source="schwab"`: native_in=`{"schwab"}`, aggregator_in=`{"plaid"}`, no unknown sources, source is native → `continue` → NOT leakage. DSU stays in Schwab scope.
- `symbol_to_sources[DSU] = {"plaid", "schwab"}`, `source="plaid"`: same overlap but source is aggregator → `pass` → IS leakage. DSU excluded from Plaid scope (correct: schwab is authoritative).
- `symbol_to_sources[SPY] = {"schwab", "ibkr_flex"}`, `source="schwab"`: native_in=`{"schwab", "ibkr_flex"}`, aggregator_in=`{}` → aggregator_in is empty → no exemption → IS leakage. Genuinely cross-source.
- `symbol_to_sources[AAPL] = {"plaid", "snaptrade"}`, `source="plaid"`: native_in=`{}` → no exemption → IS leakage. Both aggregators, genuinely ambiguous.
- `symbol_to_sources[XYZ] = {"plaid", "schwab", "ibkr_flex"}`, `source="schwab"`: `sources - native_in - aggregator_in = {}` (all categorized), but native_in has two elements (`{"schwab", "ibkr_flex"}`) → still exempted because the only "cross" is native-vs-aggregator. However, the symbol IS at two native brokerages... Actually, in this case the position IS genuinely at schwab and ibkr, so leakage detection at the native-vs-native level is handled separately by the fact that both native sources contribute rows. Let me think about this edge case...

Actually, this edge case is safe: if `symbol_to_sources[XYZ] = {"plaid", "schwab", "ibkr_flex"}`, the exemption fires (sources = native + aggregator, source is native). But the symbol IS at both schwab and ibkr — that's genuine cross-source. We need to check that the native sources alone have `len > 1`:

**Revised After:**
```python
    _NATIVE_SOURCES = {"schwab", "ibkr_flex"}
    _AGGREGATOR_SOURCES = {"plaid", "snaptrade"}

    symbol_level_leakage = set()
    for symbol, sources in symbol_to_sources.items():
        if source not in sources or len(sources) <= 1:
            continue
        # When the overlap is only native + aggregator and there is exactly one
        # native source, the native API is authoritative — not leakage for native scope.
        native_in = sources & _NATIVE_SOURCES
        aggregator_in = sources & _AGGREGATOR_SOURCES
        unknown_sources = sources - _NATIVE_SOURCES - _AGGREGATOR_SOURCES
        if (
            native_in
            and aggregator_in
            and len(native_in) == 1
            and not unknown_sources
            and source in native_in
        ):
            # Single native source + aggregator mirror(s). Native is authoritative.
            # Exempt from leakage when requesting native scope.
            continue
        symbol_level_leakage.add(symbol)
```

**Why this revised version is correct:**
- `sources = {"plaid", "schwab"}`, `source="schwab"`: native_in=`{"schwab"}` (len=1), aggregator_in=`{"plaid"}`, no unknowns, source in native_in → `continue` → NOT leakage. **DSU/MSCI/STWD included in Schwab scope.**
- `sources = {"plaid", "schwab"}`, `source="plaid"`: native_in=`{"schwab"}` (len=1), aggregator_in=`{"plaid"}`, no unknowns, but source NOT in native_in → falls through → IS leakage. **DSU excluded from Plaid scope (correct).**
- `sources = {"schwab", "ibkr_flex"}`, `source="schwab"`: native_in=`{"schwab", "ibkr_flex"}` (len=2) → `len(native_in) == 1` fails → falls through → IS leakage. **Genuinely cross-source.**
- `sources = {"plaid", "snaptrade"}`, `source="plaid"`: native_in=`{}` → first condition fails → IS leakage. **Both aggregators, genuinely ambiguous.**
- `sources = {"plaid", "schwab", "ibkr_flex"}`, `source="schwab"`: native_in=`{"schwab", "ibkr_flex"}` (len=2) → `len(native_in) == 1` fails → IS leakage. **Correct — genuinely at two brokers.**
- `sources = {"plaid", "schwab", "manual"}`, `source="schwab"`: unknown_sources=`{"manual"}` → `not unknown_sources` fails → IS leakage. **Unknown source type, stay conservative.**

### File: `tests/core/test_realized_performance_analysis.py`

#### Existing test unchanged: `test_source_scoped_holdings_excludes_cross_source_leakage_symbols`

This test (line ~6384) uses TWO separate rows — one with `position_source="snaptrade"` and one with `position_source="plaid"` — for the same symbol (AAPL). Both are aggregators, so the exemption does NOT fire (native_in is empty). AAPL remains excluded. **No change needed.**

#### New Test 1: Native+aggregator symbol overlap — native scope includes position

```python
def test_source_scoped_native_over_aggregator_symbol_leakage():
    """When separate rows report the same symbol from both a native source
    (schwab) and an aggregator (plaid), the native scope should INCLUDE
    the position — the aggregator is mirroring the native account."""
    positions = SimpleNamespace(data=SimpleNamespace(positions=[
        # Plaid mirror row
        {"ticker": "DSU", "quantity": 4500, "value": 15000,
         "position_source": "plaid", "type": "equity", "currency": "USD",
         "cost_basis": 17000, "account_id": "plaid_acct_123",
         "brokerage_name": "Merrill"},
        # Native Schwab row
        {"ticker": "DSU", "quantity": 2551, "value": 24000,
         "position_source": "schwab", "type": "equity", "currency": "USD",
         "cost_basis": 26000, "account_id": "schwab_acct_456",
         "brokerage_name": "Charles Schwab"},
        # Pure schwab position (no leakage)
        {"ticker": "BXMT", "quantity": 580, "value": 11000,
         "position_source": "schwab", "type": "equity", "currency": "USD",
         "cost_basis": 12000, "account_id": "schwab_acct_456",
         "brokerage_name": "Charles Schwab"},
    ]))

    warnings: List[str] = []
    result = rpa._build_source_scoped_holdings(positions, source="schwab", warnings=warnings)

    # DSU should be INCLUDED in Schwab scope (native is authoritative over aggregator)
    assert "DSU" in result.current_positions
    assert "BXMT" in result.current_positions
    # DSU should NOT be in leakage symbols
    assert "DSU" not in result.cross_source_holding_leakage_symbols
```

#### New Test 2: Native+aggregator symbol overlap — aggregator scope excludes position

```python
def test_source_scoped_aggregator_excluded_when_native_present():
    """When separate rows report DSU from both plaid and schwab, requesting
    source='plaid' should EXCLUDE DSU — schwab is authoritative."""
    positions = SimpleNamespace(data=SimpleNamespace(positions=[
        {"ticker": "DSU", "quantity": 4500, "value": 15000,
         "position_source": "plaid", "type": "equity", "currency": "USD",
         "cost_basis": 17000, "account_id": "plaid_acct_123"},
        {"ticker": "DSU", "quantity": 2551, "value": 24000,
         "position_source": "schwab", "type": "equity", "currency": "USD",
         "cost_basis": 26000, "account_id": "schwab_acct_456"},
        # Pure plaid position (should be included)
        {"ticker": "IT", "quantity": 50, "value": 5000,
         "position_source": "plaid", "type": "equity", "currency": "USD",
         "cost_basis": 5500, "account_id": "plaid_acct_123"},
    ]))

    warnings: List[str] = []
    result = rpa._build_source_scoped_holdings(positions, source="plaid", warnings=warnings)

    # DSU should be EXCLUDED from plaid scope (schwab is authoritative)
    assert "DSU" not in result.current_positions
    assert "DSU" in result.cross_source_holding_leakage_symbols
    # IT should be INCLUDED (pure plaid, no overlap)
    assert "IT" in result.current_positions
```

#### New Test 3: Two native sources — still excluded

```python
def test_source_scoped_two_native_sources_still_leakage():
    """When the same symbol is reported by two native APIs (schwab + ibkr_flex),
    it IS genuine cross-source — should be excluded."""
    positions = SimpleNamespace(data=SimpleNamespace(positions=[
        {"ticker": "SPY", "quantity": 10, "value": 6000,
         "position_source": "schwab", "type": "equity", "currency": "USD",
         "cost_basis": 5800, "account_id": "schwab_acct_456"},
        {"ticker": "SPY", "quantity": 5, "value": 3000,
         "position_source": "ibkr_flex", "type": "equity", "currency": "USD",
         "cost_basis": 2900, "account_id": "ibkr_acct_789"},
    ]))

    warnings: List[str] = []
    result = rpa._build_source_scoped_holdings(positions, source="schwab", warnings=warnings)

    # SPY should be EXCLUDED — genuinely cross-source (two native brokerages)
    assert "SPY" not in result.current_positions
    assert "SPY" in result.cross_source_holding_leakage_symbols
```

#### New Test 4: Two aggregators — still excluded (existing behavior)

```python
def test_source_scoped_two_aggregators_still_leakage():
    """Two aggregator sources for the same symbol — genuinely ambiguous."""
    positions = SimpleNamespace(data=SimpleNamespace(positions=[
        {"ticker": "AAPL", "quantity": 10, "value": 2000,
         "position_source": "plaid", "type": "equity", "currency": "USD",
         "cost_basis": 1800, "account_id": "plaid_acct_A"},
        {"ticker": "AAPL", "quantity": 10, "value": 2000,
         "position_source": "snaptrade", "type": "equity", "currency": "USD",
         "cost_basis": 1800, "account_id": "snap_acct_B"},
    ]))

    warnings: List[str] = []
    result = rpa._build_source_scoped_holdings(positions, source="plaid", warnings=warnings)

    # AAPL should be excluded — both sources are aggregators, genuinely ambiguous
    assert "AAPL" not in result.current_positions
    assert "AAPL" in result.cross_source_holding_leakage_symbols
```

#### New Test 5: One native + two aggregators — exempt for native scope

```python
def test_source_scoped_native_plus_two_aggregators_exempt():
    """When a symbol is reported by one native (schwab) and two aggregators
    (plaid + snaptrade), native scope should still be exempt — all non-native
    sources are aggregator mirrors."""
    positions = SimpleNamespace(data=SimpleNamespace(positions=[
        {"ticker": "DSU", "quantity": 4500, "value": 15000,
         "position_source": "plaid", "type": "equity", "currency": "USD",
         "cost_basis": 17000, "account_id": "plaid_acct_A"},
        {"ticker": "DSU", "quantity": 4500, "value": 15000,
         "position_source": "snaptrade", "type": "equity", "currency": "USD",
         "cost_basis": 17000, "account_id": "snap_acct_B"},
        {"ticker": "DSU", "quantity": 2551, "value": 24000,
         "position_source": "schwab", "type": "equity", "currency": "USD",
         "cost_basis": 26000, "account_id": "schwab_acct_456"},
    ]))

    warnings: List[str] = []
    result = rpa._build_source_scoped_holdings(positions, source="schwab", warnings=warnings)

    # DSU should be INCLUDED in schwab scope (one native + aggregator mirrors)
    assert "DSU" in result.current_positions
    assert "DSU" not in result.cross_source_holding_leakage_symbols
```

#### New Test 6: Unknown source blocks exemption

```python
def test_source_scoped_unknown_source_blocks_exemption():
    """When sources include an unrecognized provider alongside native+aggregator,
    the exemption should NOT fire — stay conservative."""
    positions = SimpleNamespace(data=SimpleNamespace(positions=[
        {"ticker": "DSU", "quantity": 4500, "value": 15000,
         "position_source": "plaid", "type": "equity", "currency": "USD",
         "cost_basis": 17000, "account_id": "plaid_acct_A"},
        {"ticker": "DSU", "quantity": 2551, "value": 24000,
         "position_source": "schwab", "type": "equity", "currency": "USD",
         "cost_basis": 26000, "account_id": "schwab_acct_456"},
        {"ticker": "DSU", "quantity": 100, "value": 1000,
         "position_source": "manual", "type": "equity", "currency": "USD",
         "cost_basis": 1100, "account_id": "manual_acct"},
    ]))

    warnings: List[str] = []
    result = rpa._build_source_scoped_holdings(positions, source="schwab", warnings=warnings)

    # DSU should be EXCLUDED — unknown source "manual" blocks exemption
    assert "DSU" not in result.current_positions
    assert "DSU" in result.cross_source_holding_leakage_symbols
```

### Test helper pattern

The existing tests use `SimpleNamespace` to create mock position results (see line 6385). All new tests use the same pattern.

## Why existing tests pass unchanged

- `test_source_scoped_holdings_excludes_cross_source_leakage_symbols` (line ~6384): Uses two separate rows (`position_source="snaptrade"` and `position_source="plaid"`) for the same symbol — both aggregators, so the native exemption does NOT fire. AAPL remains excluded. **Unchanged.**
- `test_cross_source_leakage_downgrades_reliability` (line ~6588): Uses `position_source="snaptrade"` and separate plaid rows — both aggregators, native exemption doesn't fire. **Unchanged.**
- All P3.1 tests: Don't touch source-scoped holdings. **Unchanged.**
- All `test_derive_cash_*` tests: Don't call `_build_source_scoped_holdings`. **Unchanged.**
- The 4 existing tests from Change 1 (row-level tiebreaker, lines ~7039-7153): Use single merged rows (`position_source="plaid,schwab"`, `"plaid,snaptrade"`, `"schwab,ibkr_flex"`) — only row-level matching, no symbol-level leakage. The plaid-scope test uses a merged row so the tiebreaker narrows to schwab before symbol_to_sources even sees it. **All still pass.**

## Expected Impact

| Source | Post-P3.1 (current) | Expected Post-Fix | Broker Actual |
|--------|---------------------|-------------------|---------------|
| **Schwab** | +49.76% | Significantly lower (DSU/MSCI/STWD add ~$82K to base) | -8.29% |
| **IBKR** | +10.45% | Unchanged (no plaid overlap) | -9.35% |
| **Plaid** | -7.96% | May change slightly (DSU/MSCI/STWD removed from Plaid scope) | -12.49% |
| **Combined** | +34.66% | Improved (Schwab no longer +50%) | -8 to -12% |

## Verification

1. `pytest tests/core/test_realized_performance_analysis.py -v` — all existing + new tests pass
2. `pytest tests/ --ignore=tests/api -q` — full suite green
3. Manual per-source check:
   ```
   python3 -c "
   from mcp_tools.performance import get_performance
   for source in ['all', 'plaid', 'schwab', 'ibkr_flex']:
       r = get_performance(mode='realized', source=source, format='agent', use_cache=False)
       ret = r['snapshot']['returns']
       print(f'{source}: {ret[\"total_return_pct\"]}%')
   "
   ```
4. Schwab `cross_source_holding_leakage_symbols` should be empty (DSU/MSCI/STWD now attributed to Schwab)
5. Schwab V_start should be ~$50-80K (not $6.5K)
6. Update `RETURN_PROGRESSION_BY_FIX.md` with post-fix measurements

## Not in scope

- Adjusting synthetic inception to "System transfer" date (Aug 24, 2024) instead of global inception — would further improve accuracy but is a separate change
- Plaid institution identification (determining which Plaid connections map to which brokerages)
- Position consolidation deduplication (preventing the merged `position_source` in the first place)
