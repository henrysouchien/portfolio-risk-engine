# Use Custom Peers for Stock Lookup Peer Comparison

## Context
The Stock Lookup's peer comparison (Snapshot valuation bars + vs Peers tab) uses FMP's `stock_peers` endpoint for peer discovery. We have our own curated peer system (`get_subindustry_peers_from_ticker()` in `core/proxy_builder.py`) that uses GPT-generated peers cached in the `subindustry_peers` DB table. Our peers are more relevant, validated for data availability, and consistent across sessions.

## Approach
Call `get_subindustry_peers_from_ticker()` directly in `compare_peers()` for auto-generation + caching, with FMP `stock_peers` as a fallback if the custom path returns empty (GPT unavailable, OPENAI_API_KEY unset, or generation fails). This builds up the peer cache over time while preserving FMP as a safety net.

To avoid the OpenAI eager-import problem, make `core/proxy_builder.py`'s import of `generate_subindustry_peers` lazy (move from module-level to inside the function that uses it).

**Behavior by path:**
- **DB cache hit:** Instant, no GPT, no FMP call. Most common path for previously-analyzed tickers.
- **DB cache miss + GPT succeeds:** ~3-5s for generation + validation + DB cache write. Peers are cached for future lookups.
- **DB cache miss + GPT fails** (OPENAI_API_KEY unset, quota, etc.): `get_subindustry_peers_from_ticker()` returns `[]`. Falls back to FMP `stock_peers`. Same as current behavior — no regression.
- **Both fail:** "No peers found" error with manual override suggestion.

## Implementation

### Step 1: Make GPT import lazy in proxy_builder.py
**File:** `core/proxy_builder.py`

Move the module-level import (line 6) to inside the function that uses it (line 846):

```python
# Remove from line 6:
# from utils.gpt_helpers import generate_subindustry_peers

# Add at line 846 (inside get_subindustry_peers_from_ticker, right before usage):
from utils.gpt_helpers import generate_subindustry_peers
raw_peers_text = generate_subindustry_peers(ticker=ticker, name=name, industry=industry)
```

This means `import core.proxy_builder` no longer triggers `openai.OpenAI()` construction. The OpenAI client is only created when GPT peer generation actually runs (DB cache miss path).

### Step 2: Swap peer discovery in `compare_peers()`
**File:** `fmp/tools/peers.py` (lines 144-176)

Replace the FMP `stock_peers` auto-discovery block:

```python
# Current (lines 144-176):
else:
    try:
        peers_data = fmp.fetch_raw("stock_peers", symbol=symbol)
    except Exception as e:
        return {"status": "error", "error": f"Failed to fetch peers for {symbol}: {e}"}
    # ... 20+ lines of FMP response parsing ...

# New — custom peers with FMP fallback:
else:
    peer_list = []
    # Try custom curated peers first (DB cache + GPT auto-generation)
    try:
        from core.proxy_builder import get_subindustry_peers_from_ticker
        peer_list = get_subindustry_peers_from_ticker(symbol)
        peer_list = list(dict.fromkeys(peer_list))  # dedup
    except Exception:
        peer_list = []  # GPT/import failed, fall through to FMP

    # Fallback to FMP stock_peers if custom path returned empty
    if not peer_list:
        try:
            peers_data = fmp.fetch_raw("stock_peers", symbol=symbol)
            # ... existing FMP response parsing (lines 156-166, kept as-is) ...
        except Exception as e:
            return {
                "status": "error",
                "error": f"Failed to fetch peers for {symbol}: {e}",
            }

    if not peer_list:
        return {
            "status": "error",
            "error": (
                f"No peers found for {symbol}. Try providing peers manually with "
                "the 'peers' parameter (e.g., peers='MSFT,GOOGL,META')."
            ),
        }
```

Everything after line 178 (dedup subject, limit, ratio fetching, comparison table) stays exactly the same.

**Notes:**
- Custom peers tried first, FMP is the safety net — no regression if GPT/OpenAI is unavailable
- Import is inline (inside the `else` block) to avoid module-level dependency
- `get_subindustry_peers_from_ticker()` returns `list[str]` — same shape as current `peer_list`. Returns `[]` on failure (doesn't raise).
- Added `dict.fromkeys()` dedup since GPT may return duplicates
- FMP fallback preserves the current explicit error message for FMP fetch failures
- ETF/fund tickers → custom returns empty → FMP fallback → likely empty → "no peers" error
- Manual `peers` parameter (line 141-143) is unaffected
- **Known limitation:** Custom peers pass price-history validation but could still fail `ratios_ttm` fetches downstream. This is NOT a regression — the same issue exists with FMP peers today (any peer can fail ratio fetch). The existing `failed_tickers` handling in `compare_peers()` (line 187-213) already handles this gracefully.

### Step 3: Update peer tests
**File:** `tests/mcp_tools/test_peers.py`

Tests that mock `FMPClient.fetch_raw("stock_peers")` need updating:
- **Cache hit test:** Mock `get_subindustry_peers_from_ticker` returning peers. Assert FMP `stock_peers` is NOT called.
- **Cache miss → FMP fallback test:** Mock `get_subindustry_peers_from_ticker` returning `[]`. Mock FMP `stock_peers` returning peers. Assert FMP peers are used.
- **Custom fails → FMP fallback test:** Mock `get_subindustry_peers_from_ticker` raising. Mock FMP returning peers. Assert FMP peers used, no crash.
- **Both fail test:** Mock custom returning `[]`, mock FMP returning empty. Assert "no peers" error.
- **Import regression test (subprocess-based):** Run `python3 -c "import core.proxy_builder"` in a subprocess with `OPENAI_API_KEY` unset. Must succeed (proves lazy import works). Cannot be an in-process test because `sys.modules` caching may hide the eager-import bug.
- Tests for manual peers (`peers="MSFT,GOOGL"`) are unaffected.

## Files Changed

| File | Changes |
|------|---------|
| `core/proxy_builder.py` | Move `from utils.gpt_helpers import generate_subindustry_peers` from line 6 to inside function (lazy import) |
| `fmp/tools/peers.py` | Replace FMP `stock_peers` auto-discovery (lines 144-176) with `get_subindustry_peers_from_ticker()` call |
| `tests/mcp_tools/test_peers.py` | Update auto-discovery tests to mock `get_subindustry_peers_from_ticker` instead of `FMPClient.fetch_raw("stock_peers")` |

## Verification
1. Run peer tests: `pytest tests/mcp_tools/test_peers.py -q` — must pass
2. Verify lazy import works: `python3 -c "import core.proxy_builder; print('import OK')"` — should succeed without OPENAI_API_KEY
3. Manual warm-cache test: `compare_peers('AAPL')` — should return peers from DB cache (or generate + cache if first time)
4. Manual override test: `compare_peers('AAPL', peers='MSFT,GOOGL')` — should use provided peers
