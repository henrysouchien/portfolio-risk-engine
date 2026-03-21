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

`timing_symbol_count = len({(r.symbol, r.currency) for r in timing_results})`

**Bond disambiguation:** Bonds may have non-unique symbols (e.g., "UNKNOWN" from Plaid). IBKR resolves bonds via `contract_identity.con_id` or `cusip`. If two bonds share the same `(symbol, currency, "bond")` key but have different `contract_identity`, they'll get the same price fetch — accepted as a v1 limitation. Proper fix would add contract_identity hashing to the group key.

## Files Changed

| File | Change |
|------|--------|
| `trading_analysis/fifo_matcher.py` | Add `contract_identity` to OpenLot, ClosedTrade, RoundTrip. Populate in _process_entry/_process_exit/from_lots. |
| `trading_analysis/analyzer.py` | Rewrite `analyze_timing()` — provider chain with daily→monthly fallback, direction-aware formula, remove allowlist, fmp_ticker_map for international equities |
| `tests/trading_analysis/test_scorecard_v2.py` | Update timing tests |
| `tests/trading_analysis/test_analyzer_mutual_funds.py` | Update analyze_timing monkeypatches |

## Tests

- Long equity: daily closes from FMP → timing scored
- Short equity: inverted formula, exit at low → ~100%
- Short flat period → score 50
- Futures: FMPProvider resolves via contracts.yaml, daily data
- Futures monthly fallback: FMP empty, IBKR monthly → scored
- Options with contract_identity: IBKR/BS monthly → scored
- Options without contract_identity: skipped
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
