# Timing Analysis — Shorts + All Instruments via Provider Chain

## Context

Current timing only scores 1 long equity round-trip. Adding short support and all instrument types via the existing provider chain with daily-then-monthly fallback.

## Changes

### 1. Direction-aware timing formula

**LONG**: best = max(closes), worst = min(closes), score = (exit - worst) / (best - worst) * 100
**SHORT**: best = min(closes), worst = max(closes), score = (worst - exit) / (worst - best) * 100

P&L fields direction-aware. `best_price_date` uses idxmax for longs, idxmin for shorts.

### 2. Provider chain — daily then monthly fallback

```python
from providers.bootstrap import get_registry

registry = get_registry()
effective_type = "equity" if instrument_type == "unknown" else instrument_type
chain = registry.get_price_chain(effective_type)

# Resolve FMP ticker for international equities (VOD → VOD.L)
# For futures, FMPProvider handles resolution internally via contracts.yaml
fmp_ticker_map = {}
if effective_type in ("equity", "etf", "fund"):
    company_name = self._get_company_name(symbol)
    resolved = resolve_fmp_ticker(symbol, company_name=company_name, currency=currency)
    if resolved != symbol:
        fmp_ticker_map[symbol] = resolved

closes = None
for provider in chain:
    # Skip providers that can't price without contract_identity:
    # Skip providers that need contract_identity when it's missing/incomplete
    # Option skip: both IBKR and BS need contract_identity (IBKR for marks, BS for underlying/strike/expiry)
    # Bond skip: IBKR needs con_id or cusip
    provider_name = getattr(provider, 'provider_name', '')
    if effective_type == "option" and not contract_identity:
        continue  # all option providers need contract_identity
    if (effective_type == "bond"
        and provider_name == "ibkr"
        and not (contract_identity.get("con_id") or contract_identity.get("cusip"))):
        continue

    try:
        closes = provider.fetch_daily_close(
            symbol, start_date=from_date, end_date=to_date,
            instrument_type=effective_type,
            contract_identity=contract_identity,
            fmp_ticker_map=fmp_ticker_map or None,
        )
        if closes is not None and not closes.empty:
            break
        closes = provider.fetch_monthly_close(
            symbol, start_date=from_date, end_date=to_date,
            instrument_type=effective_type,
            contract_identity=contract_identity,
            fmp_ticker_map=fmp_ticker_map or None,
        )
        if closes is not None and not closes.empty:
            break
    except Exception:
        continue

if closes is None or closes.empty:
    continue  # skip — no provider had data
```

**What this enables:**
- Equities: daily via FMP (international resolved via fmp_ticker_map)
- Futures: daily via FMP (contracts.yaml resolution internal) → monthly via IBKR fallback
- Options: monthly via IBKR marks → monthly via BS theoretical (needs contract_identity)
- Bonds: monthly via IBKR (needs contract_identity)
- Unknown: treated as equity for routing

### 3. Thread contract_identity through FIFO pipeline

**File: `trading_analysis/fifo_matcher.py`**

Add `contract_identity: dict = field(default_factory=dict)` to:
- **OpenLot** — populated in `_process_entry()` from transaction metadata
- **ClosedTrade** — populated in `_process_exit()` from the OpenLot
- **RoundTrip** — populated in `from_lots()` from first lot

### 4. Remove instrument type allowlist

```python
TIMING_EXCLUDED_TYPES = {"mutual_fund", "fx", "fx_artifact", "income"}
eligible_rts = [rt for rt in round_trips if not rt.synthetic and rt.instrument_type not in TIMING_EXCLUDED_TYPES]
```

### 5. Group by (symbol, currency, instrument_type)

Include `instrument_type` in the key — same symbol can be different instruments (e.g., MHI equity vs MHI futures). FMPProvider routes differently by instrument_type.

```python
by_key = defaultdict(list)
for rt in eligible_rts:
    by_key[(rt.symbol, rt.currency, rt.instrument_type)].append(rt)

for (symbol, currency, instrument_type), rts in by_key.items():
    contract_identity = rts[0].contract_identity
    # ... fetch via provider chain, score each round-trip
```

`timing_symbol_count = len({(r.symbol, r.currency, r.instrument_type) for r in timing_results})`

**Important:** This triple-based count must be used in BOTH:
- `analyzer.py run_full_analysis()` when computing `timing_symbol_count` for `compute_timing_grade()`
- `models.py get_agent_snapshot()` when reporting `timing_symbol_count`

**Known limitations:**
- **Same-symbol cross-instrument collision:** FIFO matcher keys by `(symbol, currency, direction)` — not instrument_type. If MHI equity and MHI futures share currency+direction, lots merge upstream before timing runs. This is a pre-existing FIFO design constraint, not fixable in timing alone. In practice, this is rare (equities and futures with the same ticker on the same exchange are uncommon in real portfolios).
- **Bond disambiguation:** Bonds may have non-unique symbols. IBKR resolves bonds via `contract_identity.con_id` or `cusip` (cusip is sufficient). If two bonds share the same `(symbol, currency, "bond")` key but have different identities, they'll get the same price fetch — accepted as v1 limitation.
- **International option underlyings:** BS option fallback uses `contract_identity["underlying"]` which may not be FMP-resolved for international options. Edge case — most options are US-listed.

## Files Changed

| File | Change |
|------|--------|
| `trading_analysis/fifo_matcher.py` | Add `contract_identity` to OpenLot, ClosedTrade, RoundTrip. Populate in _process_entry/_process_exit/from_lots. |
| `trading_analysis/analyzer.py` | Rewrite `analyze_timing()` — provider chain with daily→monthly fallback, direction-aware formula, remove allowlist, fmp_ticker_map for international equities |
| `trading_analysis/models.py` | Add `instrument_type: str = "equity"` and `direction: str = "LONG"` to TimingResult + `to_dict()`. Update `get_agent_snapshot()` timing_symbol_count to count `(symbol, currency, instrument_type)` triples. |
| `tests/trading_analysis/test_scorecard_v2.py` | Update timing tests |
| `tests/trading_analysis/test_analyzer_mutual_funds.py` | Update analyze_timing monkeypatches |
| `tests/trading_analysis/test_agent_snapshot.py` | Update timing_symbol_count assertion |
| `tests/trading_analysis/test_result_serialization.py` | Update TimingResult serialization assertions (new fields) |

## Tests

- Long equity: daily closes from FMP → timing scored
- Short equity: inverted formula, exit at low → ~100%
- Short flat period → score 50
- Futures: FMPProvider resolves via contracts.yaml, daily data
- Futures monthly fallback: FMP empty, IBKR monthly → scored
- Options with contract_identity: IBKR/BS monthly → scored
- Options without contract_identity: all providers skipped (IBKR needs it, BS also needs underlying/right/expiry/strike)
- Bonds without con_id/cusip: IBKR skipped
- Bonds with cusip only (no con_id): IBKR NOT skipped (cusip is sufficient)
- International equity: fmp_ticker_map resolves VOD → VOD.L
- mutual_fund/fx/fx_artifact/income → excluded
- unknown → treated as equity
- No provider data → skipped
- contract_identity threaded through pipeline

## Verification

1. `pytest tests/trading_analysis/ -v` — all tests pass
2. MCP timing_symbol_count > 1
3. Short equity round-trips produce timing scores
4. Futures round-trips produce timing scores
