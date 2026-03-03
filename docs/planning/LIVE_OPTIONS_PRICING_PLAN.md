# Live Options Pricing Plan

## Context
`analyze_option_strategy()` currently uses Black-Scholes with a hardcoded 30% vol when IBKR isn't used. `analyze_option_chain()` already fetches live bid/ask/mid from IBKR via `fetch_snapshot()` but **drops those prices** — only OI and volume are surfaced. The infrastructure for live pricing exists; it just needs to be wired through.

## Phase 1 — Strategy Tool: Surface Live Market Prices

### 1a. Add market price fields to `LegAnalysis` (`options/result_objects.py`)
- Add `market_bid`, `market_ask`, `market_mid` (all `float | None = None`)
- Add `price_source: Literal["ibkr", "input"] = "input"` (semantics: `"input"` = caller-supplied premium, `"ibkr"` = live IBKR market data)
- Update `to_dict()` to include the new fields

### 1b. Capture bid/ask/mid in `enrich_with_ibkr()` (`options/analyzer.py`)
**Critical fix from Codex review:** The current code at line 195 does `if all(value is None for value in ib_values): continue` — this skips the entire leg when Greeks are all None, which would also skip price capture. Must extract bid/ask/mid **before** the continue guard:

```python
for contract_idx, strategy_leg_idx in enumerate(leg_indexes):
    snapshot = snapshots[contract_idx] if contract_idx < len(snapshots) else {"error": "timeout"}
    analysis = result.leg_analysis[strategy_leg_idx]

    if not isinstance(snapshot, dict) or "error" in snapshot:
        # existing warning logic unchanged
        continue

    # === NEW: Capture market prices BEFORE Greeks check ===
    ib_bid = snapshot.get("bid")
    ib_ask = snapshot.get("ask")
    ib_mid = snapshot.get("mid")
    if ib_mid is None and ib_bid is not None and ib_ask is not None:
        ib_mid = (ib_bid + ib_ask) / 2.0
    analysis.market_bid = ib_bid
    analysis.market_ask = ib_ask
    analysis.market_mid = ib_mid
    if ib_mid is not None or ib_bid is not None or ib_ask is not None:
        analysis.price_source = "ibkr"

    # === Existing Greeks extraction (unchanged) ===
    existing = analysis.greeks or GreeksSnapshot(source="none")
    ib_delta = snapshot.get("delta")
    ...
    if all(value is None for value in ib_values):
        continue  # skip Greeks merge, but prices already captured above
    ...
```

### 1c. Add `net_market_premium` to `StrategyAnalysisResult` (`options/result_objects.py`)
- Property that sums `-direction * market_mid * size * multiplier` across legs
- Returns `None` if any leg lacks `market_mid`

### 1d. Surface live prices in agent snapshot AND summary (`options/result_objects.py`)
In `get_agent_snapshot()`:
- Add `net_market_premium` field
- Add per-leg `live_prices` dict (bid/ask/mid/source) — only when IBKR prices exist
- Add `price_source: "ibkr" | "input"` field (do NOT mutate the verdict string — avoid breaking consumers)

In `to_summary()`:
- Add `net_market_premium` and `price_source` fields so the default `format="summary"` response also surfaces live pricing

### 1e. Update assumption note (`options/analyzer.py`)
At end of `enrich_with_ibkr()`, if any leg has `price_source == "ibkr"`, append assumption: `"Live IBKR bid/ask/mid used for market value"`

## Phase 2 — Chain Tool: Surface Pricing by Strike

### 2a. Extend per-strike row structure (`options/chain_analysis.py`)
In `_ensure_row()`, add `call_bid`, `call_ask`, `call_mid`, `call_iv`, `put_bid`, `put_ask`, `put_mid`, `put_iv` (all `None`).

In `_ingest_side_values()`, capture `bid`, `ask`, `mid`, `implied_vol` from the snapshot payload into the side-prefixed fields.

**Critical fix from Codex review:** In `_normalize_snapshots()`, the `right`-path at line 70-76 currently constructs a minimal `payload` dict with only `open_interest` and `volume`. Must extend this to also pass through `bid`, `ask`, `mid`, `implied_vol` from the raw snapshot:

```python
right = str(snap.get("right") or "").strip().upper()
if right in {"C", "P"}:
    payload = {
        "open_interest": snap.get("open_interest"),
        "volume": snap.get("volume"),
        "bid": snap.get("bid"),       # NEW
        "ask": snap.get("ask"),       # NEW
        "mid": snap.get("mid"),       # NEW
        "implied_vol": snap.get("implied_vol"),  # NEW
    }
    _ingest_side_values(row, "call" if right == "C" else "put", payload)
```

### 2b. Add `pricing_by_strike` to `analyze_chain()` output (`options/chain_analysis.py`)
Build `pricing_by_strike` dict keyed by strike, with `call: {bid, ask, mid, iv}` and `put: {bid, ask, mid, iv}` sub-dicts. Only include strikes with at least one price present.

### 2c. Surface in MCP tool (`mcp_tools/chain_analysis.py`)
- Include `pricing_by_strike` in `full_response`
- Add `atm_pricing` to summary: nearest-ATM strike's call+put bid/ask/mid/iv
- Add to agent snapshot

### 2d. Add `wide_atm_spread` flag (`core/chain_analysis_flags.py`)
Warning flag when ATM bid-ask spread > 20% — signals illiquid market.

## Phase 3 — Optional Auto-Fetch for Trade Preview

### 3a. Make `underlying_price` optional in `preview_option_trade()` (`mcp_tools/multi_leg_options.py` AND `mcp_server.py`)
**Critical fix from Codex review:** Must update BOTH the inner function AND the MCP wrapper in `mcp_server.py` (line 1678-1688). The MCP wrapper currently declares `underlying_price: float` as required. Change to `underlying_price: Optional[float] = None` in both places.

- If not provided, call `_resolve_underlying_price(underlying_symbol)` (already exists in `mcp_tools/options.py`)
- Raise clear error if auto-fetch also fails

## Files to Modify
- `options/result_objects.py` — LegAnalysis fields, net_market_premium, agent snapshot, to_summary
- `options/analyzer.py` — enrich_with_ibkr() price capture BEFORE Greeks check + assumption
- `options/chain_analysis.py` — _ensure_row, _ingest_side_values, _normalize_snapshots right-path, pricing_by_strike output
- `mcp_tools/chain_analysis.py` — surface pricing + atm_pricing + agent snapshot
- `core/chain_analysis_flags.py` — wide_atm_spread flag
- `mcp_tools/multi_leg_options.py` — optional underlying_price
- `mcp_server.py` — update preview_option_trade wrapper signature (underlying_price → Optional)

## Tests (~16)
- Phase 1:
  - enrich captures bid/ask/mid when Greeks present
  - enrich captures bid/ask/mid when ALL Greeks are None (the continue-guard edge case)
  - fallback: no prices in snapshot → market_mid stays None, price_source stays "input"
  - net_market_premium math (multi-leg, mixed directions)
  - net_market_premium returns None when any leg lacks market_mid
  - agent snapshot includes live_prices dict when IBKR prices exist
  - agent snapshot price_source="input" when no IBKR
  - to_summary includes net_market_premium and price_source
- Phase 2:
  - _normalize_snapshots right-path carries bid/ask/mid/iv through payload
  - pricing_by_strike populated correctly from strike_snapshots
  - pricing_by_strike empty when no price data in snapshots
  - atm_pricing selects nearest-ATM strike
  - wide_atm_spread flag fires at >20% spread
- Phase 3:
  - auto-fetch called when underlying_price omitted
  - explicit underlying_price skips auto-fetch
  - MCP wrapper accepts None for underlying_price

## Verification
1. Run existing options tests: `python -m pytest tests/options/ -x`
2. Run new tests
3. Live test (market hours): `analyze_option_strategy(legs=..., use_ibkr_greeks=true)` — verify `live_prices` in response
4. Live test: `analyze_option_chain(symbol="AAPL", expiry="...")` — verify `pricing_by_strike` + `atm_pricing`
