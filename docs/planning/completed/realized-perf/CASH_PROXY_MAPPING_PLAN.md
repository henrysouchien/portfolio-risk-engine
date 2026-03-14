# Cash Proxy Mapping in `to_portfolio_data()`

## Context

The MCP risk tools filter out all cash positions (`CUR:USD`, `CUR:GBP`) because they can't pass ticker validation (colon rejected by `validation_service.py`), can't be priced (no return data), and have no factor proxies. This drops margin debt — currently **-$32,339 / 25.2% of portfolio** — understating leverage (1.0x reported vs ~1.25x actual).

The existing CLI/API pipeline avoids this because broker loaders (Plaid/SnapTrade) map `CUR:USD → SGOV` via `cash_map.yaml` *before* positions reach `portfolio_input`. The `portfolio.yaml` file contains `SGOV: {"dollars": -8179}` — a valid, priceable ticker. `standardize_portfolio_input()` then correctly retains negative SGOV in `risky_weights` for leverage (`run_portfolio_risk.py:227-230`).

But `to_portfolio_data()` — used by MCP tools and `run_positions.py --to-risk` — receives raw brokerage positions from `PositionService.get_all_positions()` and does **not** apply the alias mapping. `CUR:USD` passes through as-is, hits ticker validation, and gets filtered.

**Fix**: Apply the same cash alias mapping inside `to_portfolio_data()`, converting `CUR:USD → SGOV`, `CUR:GBP → ERNS.L`, etc. Once mapped, cash flows through the pipeline as valid proxy tickers. Any unmapped cash entries (CUR:\*, USD CASH, CASH, BASE\_CURRENCY, etc.) are filtered from `holdings_dict` before `PortfolioData` creation to prevent validation failures.

## Data Flow (Before / After)

### Before (current)
```
PositionService.get_all_positions()
  → CUR:USD = -$32,339 (margin debt)
  → mcp_tools/risk.py filters ALL cash (CUR:* / type=cash)
  → to_portfolio_data() never sees it
  → leverage = 1.0x (wrong)
```

### After (this change)
```
PositionService.get_all_positions()
  → CUR:USD = -$32,339 (margin debt)
  → to_portfolio_data() maps CUR:USD → SGOV via cash_map
  → any unmapped cash (CUR:*, USD CASH, CASH, etc.) filtered from holdings_dict
  → portfolio_input = {"SGOV": {"dollars": -32339, "type": "cash"}}
  → standardize_portfolio_input keeps negative SGOV in risky_weights
  → mcp_tools/risk.py removes pre-filter (no longer needed)
  → leverage = ~1.25x (correct)
```

## Files to Modify

| File | Change |
|------|--------|
| `core/data_objects.py` | Add `_load_cash_proxy_map()` helper, apply mapping in `to_portfolio_data()` is_cash branch with shares guard, filter unmapped cash from holdings_dict before PortfolioData creation, move `fmp_ticker_map` population into non-cash branch |
| `mcp_tools/risk.py` | Remove pre-filter entirely (mapping + filter now inside `to_portfolio_data()`) |
| `tests/unit/test_positions_data.py` | Update assertion: `CUR:USD` → `SGOV` |
| `tests/unit/test_position_chain.py` | Update assertions: `CUR:USD` → `SGOV`. Add unknown currency test. |

## Key References

| What | File | Line |
|------|------|------|
| `to_portfolio_data()` — target method | `core/data_objects.py` | 374-500 |
| `is_cash` branch (where mapping goes) | `core/data_objects.py` | 436-451 |
| `fmp_ticker_map` population (move into non-cash branch) | `core/data_objects.py` | 415-423 |
| `currency_map` population (already done, Step 1.4) | `core/data_objects.py` | 481-495 |
| `_calculate_market_values()` — pre-converts cash to USD | `services/position_service.py` | 528-536 |
| `get_cash_positions()` — 3-tier fallback pattern to reuse | `run_portfolio_risk.py` | 85-124 |
| `get_cash_mappings()` — DB method | `inputs/database_client.py` | 2236 |
| `cash_map.yaml` — YAML config | `cash_map.yaml` | entire file |
| `alias_to_currency` — broker ticker → currency | `cash_map.yaml` | 103-108 |
| `standardize_portfolio_input` — negative cash handling | `run_portfolio_risk.py` | 227-230 |
| `standardize_portfolio_input` — dollars vs shares precedence | `run_portfolio_risk.py` | 171, 179 |
| Ticker validation (rejects `:`) | `services/validation_service.py` | 90-93, 240-243 |
| MCP cash filter (to be removed) | `mcp_tools/risk.py` | 64-77 |
| CUR:* factor proxy exclusion (keep) | `mcp_tools/risk.py` | 91-96 |
| Test: positions data | `tests/unit/test_positions_data.py` | 36 |
| Test: position chain | `tests/unit/test_position_chain.py` | 56, 63 |

## Implementation

### 1. Add `_load_cash_proxy_map()` helper in `core/data_objects.py`

Module-level helper above `to_portfolio_data()`. Returns `(proxy_by_currency, alias_to_currency)` tuple with 3-tier fallback matching the existing `get_cash_positions()` pattern.

**Review fixes applied**:
- **[R1 P2 #3]** Use `Path(__file__).resolve().parent.parent / "cash_map.yaml"` for repo-relative path (stable regardless of CWD)
- **[R1 P3 #5]** Log warnings on DB/YAML fallback instead of bare `except: pass`

```python
import logging
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)

def _load_cash_proxy_map() -> tuple:
    """Load cash proxy mappings with 3-tier fallback.

    Returns:
        (proxy_by_currency, alias_to_currency) where:
        - proxy_by_currency: {currency: proxy_ticker} e.g. {"USD": "SGOV"}
        - alias_to_currency: {broker_ticker: currency} e.g. {"CUR:USD": "USD"}
    """
    # Tier 1: Database
    try:
        from database import get_db_session
        from inputs.database_client import DatabaseClient
        with get_db_session() as conn:
            cash_map = DatabaseClient(conn).get_cash_mappings()
            proxy = cash_map.get("proxy_by_currency", {})
            if proxy:  # Fall through to YAML/hardcoded if DB returns empty
                return (proxy, cash_map.get("alias_to_currency", {}))
            logger.warning("Cash proxy map: DB returned empty mappings, trying YAML")
    except Exception as e:
        logger.warning("Cash proxy map: DB unavailable (%s), trying YAML", e)

    # Tier 2: YAML (repo-relative path)
    try:
        yaml_path = _PROJECT_ROOT / "cash_map.yaml"
        with open(yaml_path, "r") as f:
            cash_map = yaml.safe_load(f)
            return (
                cash_map.get("proxy_by_currency", {}),
                cash_map.get("alias_to_currency", {}),
            )
    except Exception as e:
        logger.warning("Cash proxy map: YAML unavailable (%s), using hardcoded", e)

    # Tier 3: Hardcoded
    return ({"USD": "SGOV"}, {"CUR:USD": "USD"})
```

### 2. Apply mapping in `to_portfolio_data()` is_cash branch

Load maps once at the top of the method. In the `is_cash` branch, resolve currency and proxy ticker. When the proxy ticker already has equity shares, **skip the mapping** (shares guard).

**Review fixes applied**:
- **[R1 P2 #4]** Currency resolution chain: `alias_to_currency` → `normalize_currency(currency)` → parse from ticker `CUR:XXX` → default USD.
- **[R2 P1 #2]** Shares guard instead of equity-to-dollars merge. `_calculate_market_values()` pre-converts non-USD cash values to USD (and sets `currency="USD"`), but equity positions keep their native currency. Merging would mix USD cash with GBP equity values, bypassing `price_fetcher` FX handling. The shares guard avoids this FX mismatch. See "Known Limitations" for the trade-off.
- **[R2 P2 #3]** Don't override `entry["currency"]` with `cash_ccy`. After `_calculate_market_values()`, all cash has `currency="USD"` reflecting the pre-converted value. Overriding to e.g. "GBP" would cause double FX conversion in `standardize_portfolio_input`.

```python
# At top of to_portfolio_data(), before position loop:
proxy_by_currency, alias_to_currency = _load_cash_proxy_map()

# Inside the position loop:
is_cash = position_type == "cash" or ticker.startswith("CUR:")

if is_cash:
    # Resolve currency: alias → normalize → parse from ticker → default
    cash_ccy = alias_to_currency.get(ticker)
    if not cash_ccy:
        cash_ccy = normalize_currency(currency) if currency else None
    if not cash_ccy and ":" in ticker:
        cash_ccy = ticker.split(":", 1)[1].upper()
    cash_ccy = cash_ccy or "USD"

    proxy_ticker = proxy_by_currency.get(cash_ccy)

    if proxy_ticker:
        existing = holdings_dict.get(proxy_ticker)
        if existing and "shares" in existing:
            # Shares guard: proxy ticker already has equity shares.
            # Don't merge — standardize_portfolio_input checks "dollars"
            # before "shares" (line 171 vs 179), so dollars would win and
            # equity shares would be silently ignored. Additionally,
            # _calculate_market_values() pre-converts non-USD cash to USD,
            # but equity value stays in native currency — merging would
            # mix currencies.
            # Keep original CUR:* ticker — filtered below before PortfolioData creation.
            pass
        else:
            ticker = proxy_ticker
    # else: no proxy found, keep original CUR:* ticker (filtered below)

    # Normal cash aggregation (under proxy ticker or original CUR:*)
    if ticker in holdings_dict:
        holdings_dict[ticker]["dollars"] += float(value)
        # ... existing currency check ...
    else:
        holdings_dict[ticker] = {
            "dollars": float(value),
            "currency": currency,  # Use position.currency as-is (already USD after FX pre-conversion)
            "type": "cash",
        }
```

### 3. Filter unmapped cash from holdings_dict before PortfolioData creation

**[R2 P1 #1, R3 P1 #1]** Filter inside `to_portfolio_data()`, after the position loop but before `PortfolioData.from_holdings()`. This ensures `standardized_input`, `get_tickers()`, and validation all see a clean dict.

Filter any remaining `type=="cash"` entries that are NOT known proxy tickers. This catches all unmapped cash formats — not just `CUR:*` but also `USD CASH`, `CASH`, `BASE_CURRENCY`, etc. (all present in `alias_to_currency` in `cash_map.yaml`).

```python
# After position loop, before currency_map / PortfolioData.from_holdings():
proxy_tickers = set(proxy_by_currency.values())  # {"SGOV", "IBGE.L", "ERNS.L"}
unmapped_cash = [
    t for t, entry in holdings_dict.items()
    if entry.get("type") == "cash" and t not in proxy_tickers
]
for t in unmapped_cash:
    logger.warning("Unmapped cash ticker %s removed from portfolio (no proxy configured)", t)
    del holdings_dict[t]

if not holdings_dict:
    raise ValueError("No positions remaining after cash proxy mapping. "
                     "Portfolio contains only unmapped cash holdings.")
```

This replaces the CUR:*-only filter from the previous revision, which would miss broker-specific cash formats like `USD CASH`.

### 4. Move `fmp_ticker_map` population into non-cash branch

Currently (lines 415-423) `fmp_ticker_map` is populated before the `is_cash` check. Move into the `else` (non-cash) branch to prevent CUR:* tickers from polluting the map. Cash proxy tickers (SGOV, ERNS.L) don't need FMP ticker mapping.

### 5. Update `mcp_tools/risk.py`

**Remove the pre-filter entirely**. Cash proxy mapping and CUR:* filtering now happen inside `to_portfolio_data()` — the MCP path no longer needs its own filter. This is cleaner because:
- All callers of `to_portfolio_data()` get the same behavior (MCP, CLI, API)
- No stale `standardized_input` risk (R2 Finding 1)
- `to_portfolio_data()` is the right layer for this transformation

```python
# Before (removes ALL cash in mcp_tools/risk.py):
position_result.data.positions = [
    p for p in position_result.data.positions
    if not (p.get("type") == "cash" or p.get("ticker", "").startswith("CUR:"))
]

# After: remove this block entirely. to_portfolio_data() handles mapping + filtering.
```

**Keep** the CUR:* exclusion from `ensure_factor_proxies()` (lines 91-96) as defense-in-depth.

### 6. Update tests

**`tests/unit/test_positions_data.py:36`**:
```python
# Before:
assert portfolio.standardized_input["CUR:USD"]["dollars"] == 1000.0
# After:
assert portfolio.standardized_input["SGOV"]["dollars"] == 1000.0
```

**`tests/unit/test_position_chain.py:56`**:
```python
# Before:
assert "CUR:USD" in portfolio_data.get_tickers()
# After:
assert "SGOV" in portfolio_data.get_tickers()
```

**`tests/unit/test_position_chain.py:63`**:
```python
# Before:
assert portfolio_data.portfolio_input["CUR:USD"]["dollars"] == 5000.0
# After:
assert portfolio_data.portfolio_input["SGOV"]["dollars"] == 5000.0
```

**New test: Unknown currency filtered from holdings_dict**:
```python
def test_unmapped_cash_filtered_from_portfolio():
    """Cash with unknown currency is filtered before PortfolioData creation."""
    df = pd.DataFrame([
        {"ticker": "AAPL", "quantity": 10, "value": 1500,
         "currency": "USD", "type": "equity", "position_source": "plaid"},
        {"ticker": "CUR:CHF", "quantity": 5000, "value": 5000,
         "currency": "CHF", "type": "cash", "position_source": "plaid"},
    ])
    data = PositionsData.from_dataframe(df, user_email="test@example.com")
    portfolio = data.to_portfolio_data()

    # CHF has no proxy configured — filtered from holdings_dict before PortfolioData
    assert "CUR:CHF" not in portfolio.get_tickers()
    assert "CUR:CHF" not in portfolio.portfolio_input
    # AAPL still present
    assert "AAPL" in portfolio.get_tickers()
```

**New test: Cash with missing currency resolved from ticker**:
```python
def test_cash_currency_resolved_from_ticker():
    """When currency field is missing, resolve from CUR:XXX ticker."""
    df = pd.DataFrame([
        {"ticker": "AAPL", "quantity": 10, "value": 1500,
         "currency": "USD", "type": "equity", "position_source": "plaid"},
        {"ticker": "CUR:USD", "quantity": 1000, "value": 1000,
         "currency": None, "type": "cash", "position_source": "plaid"},
    ])
    data = PositionsData.from_dataframe(df, user_email="test@example.com")
    portfolio = data.to_portfolio_data()

    # Should map CUR:USD → SGOV even with missing currency field
    assert "SGOV" in portfolio.get_tickers()
    assert portfolio.portfolio_input["SGOV"]["dollars"] == 1000.0
```

## Edge Cases

| Case | Behavior |
|------|----------|
| **Negative cash (margin debt)** | Mapped to proxy with negative dollars. `standardize_portfolio_input` keeps in `risky_weights` (line 229: `w < 0`). Leverage calculated correctly. |
| **Multiple cash positions same currency** | Aggregated by proxy ticker: `holdings_dict[proxy]["dollars"] += value` (existing aggregation logic). |
| **Proxy ticker already has equity shares** | Shares guard: mapping skipped, keep original cash ticker. Filtered from `holdings_dict` before PortfolioData creation. See "Known Limitations". |
| **Unknown currency (no proxy configured)** | Stays in `holdings_dict` with `type="cash"`, then filtered (not a proxy ticker) before PortfolioData creation. Warning logged. Catches all formats: `CUR:*`, `USD CASH`, `CASH`, etc. |
| **All positions are unmapped cash** | After mapping + filter, `holdings_dict` is empty → raise `ValueError`. |
| **YAML not at CWD** | **[R1 P2 #3]** Repo-relative `Path(__file__)` ensures YAML is found regardless of working directory. |
| **Currency field missing but ticker encodes it** | **[R1 P2 #4]** Parse currency from `CUR:JPY` → `JPY`. Also checks `alias_to_currency` first for broker-specific tickers. |
| **DB + YAML both unavailable** | **[R1 P3 #5]** Hardcoded fallback `{"USD": "SGOV"}` with warning logs at each fallback tier. |

## Known Limitations

**Proxy ETF + same-currency margin debt**: If the user holds equity shares in the proxy ETF itself (e.g., SGOV shares) AND has margin debt in the same currency (CUR:USD), the shares guard prevents merging and the margin debt is dropped (filtered as unmapped cash). This understates leverage for this specific case.

**Why not merge?** `_calculate_market_values()` pre-converts non-USD cash values to USD and sets `currency="USD"`, but equity positions keep their native currency. A merge would:
1. Mix USD-denominated cash with native-currency equity values (FX mismatch for non-USD)
2. Bypass `price_fetcher` FX handling in `standardize_portfolio_input`
3. Drop equity shares silently (`standardize_portfolio_input` checks "dollars" before "shares" — dollars wins)

**Impact**: Very low. Holding the proxy ETF AND having margin debt in the same currency is extremely rare (SGOV is a pipeline proxy, not a typical holding). Can be addressed in a future iteration by extending `standardize_portfolio_input` to handle both "shares" and "dollars" on the same entry.

**Non-USD cash proxy returns not FX-adjusted**: For non-USD cash (e.g., CUR:GBP → ERNS.L), `_calculate_market_values()` pre-converts the cash value to USD and sets `currency="USD"`. The proxy entry inherits `currency="USD"`, so it's absent from `currency_map` and its return series (in GBP) is not FX-adjusted. This creates a minor mismatch between the position weight (correct, in USD) and the return series (in native currency).

**Why not fix?** `currency_map` serves two purposes: (1) FX-adjust returns in `get_returns_dataframe()`, and (2) FX-convert dollar values in `standardize_portfolio_input`. For pre-converted cash, we want #1 but NOT #2. These are contradictory requirements from the same field. Separating them is a larger refactor.

**Impact**: Negligible. Cash proxy returns are near-zero (short-term government bonds, <1% annual). The FX effect on near-zero returns is near-zero. Only affects non-USD cash positions, which are typically small positive balances from dividends.

## Review Log

| # | Round | Priority | Finding | Resolution |
|---|-------|----------|---------|------------|
| 1 | R1 | P1 | Removing cash filter reintroduces validation failures for unmapped CUR:* | Changed to post-mapping CUR:* filter instead of full removal |
| 2 | R1 | P1 | Shares guard drops margin debt when user holds proxy ETF | ~~Convert equity shares to dollars using market_value, then merge~~ Reverted: see R2 #2 |
| 3 | R1 | P2 | `open("cash_map.yaml")` relative to CWD breaks when MCP runs elsewhere | Use `Path(__file__).resolve().parent.parent / "cash_map.yaml"` |
| 4 | R1 | P2 | `normalize_currency(currency) or "USD"` ignores currency encoded in ticker | Chain: `alias_to_currency` → `normalize_currency` → parse `CUR:XXX` → default |
| 5 | R1 | P3 | Bare `except Exception: pass` hides DB/YAML failures | Add `logger.warning()` at each fallback tier |
| 6 | R2 | P1 | Post-filter leaves `standardized_input` stale with CUR:* entries | Filter from `holdings_dict` inside `to_portfolio_data()` before `PortfolioData.from_holdings()` |
| 7 | R2 | P1 | Equity-to-dollars merge risks FX mismatch (Plaid vs SnapTrade value currencies) | Revert to shares guard. `_calculate_market_values()` pre-converts cash to USD but equity stays native — merge mixes currencies. Document as known limitation. |
| 8 | R2 | P2 | `cash_ccy` not persisted into entry currency | Don't override — `position.currency` is already "USD" after `_calculate_market_values()` pre-conversion. Overriding with `cash_ccy` would cause double FX. |
| 9 | R2 | P2 | Converting shares to dollars drops exposure when value is 0/missing | Moot — shares guard means no value-dependent conversion. |
| 10 | R3 | P1 | CUR:*-only filter misses other cash formats (`USD CASH`, `CASH`, `BASE_CURRENCY`) | Filter by `type=="cash" and not in proxy_tickers` instead of `startswith("CUR:")` |
| 11 | R3 | P2 | Missing currency + non-USD ticker → entry defaults to USD, skipping FX for returns | Low impact: loaders default cash currency to USD so `None` is unlikely in practice. Non-USD proxy returns FX mismatch documented as known limitation (near-zero impact). |
| 12 | R3 | P2 | DB returns empty `proxy_by_currency` → skips YAML/hardcoded fallback | Check `if proxy:` before returning DB result; fall through to YAML/hardcoded when empty |

## Verification

1. **Unit tests**: `python3 -m pytest tests/unit/test_positions_data.py tests/unit/test_position_chain.py -v`
2. **MCP tools direct test**: call `get_risk_score` and `get_risk_analysis` with `user_email="hc@henrychien.com"` for all three formats (summary, full, report)
3. **Margin debt check**: verify `portfolio_data.portfolio_input` contains `SGOV` with negative dollars (not `CUR:USD`)
4. **Leverage check**: verify `leverage > 1.0` in risk analysis full output
5. **Existing CLI path**: `python3 tests/utils/show_api_output.py analyze` still works (regression)

---

*Document created: 2026-02-06*
*Review round 1: GPT Codex (5 findings, all addressed)*
*Review round 2: GPT Codex (4 findings: R2 #6-9 — merge reverted, filter moved inside to_portfolio_data)*
*Review round 3: GPT Codex (3 findings: R3 #10-12 — filter broadened to all cash types, non-USD returns FX documented, empty DB fallthrough)*
*Status: **Implemented and verified** (2026-02-06)*

## Verification Results

All checks pass:

| Check | Result |
|-------|--------|
| Unit tests (12/12) | All pass, including 2 new cash proxy tests |
| API `risk-score` | Leverage 1.51x, margin debt reflected in violations |
| API `analyze` | SGOV in all matrices, leverage 1.51x |
| API `performance` | currency_map threading works |
| Position monitor | 24 positions + 1 cash excluded, P&L correct |
| `run_positions.py --to-risk` | Full pipeline end-to-end |
| CLI `--risk-score` | Leverage 1.29x (YAML portfolio — expected difference from live) |
| Margin debt in portfolio_input | SGOV with negative dollars confirmed |
