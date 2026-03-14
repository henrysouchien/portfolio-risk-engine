# Plan: IBKR Gateway Direct Position Provider

## Context

SnapTrade doesn't expose IBKR's USD margin balance (~-$8,727 real vs ~-$3,649 reported). This is the dominant gap in realized performance accuracy. IBKR Gateway API via `ib.portfolio()` and `ib.accountValues()` provides accurate market values and per-currency cash balances including margin. This plan adds IBKR as a direct position provider, following the existing Schwab provider pattern.

The routing infrastructure already supports this: `POSITION_ROUTING` has a commented-out `"interactive_brokers": "ibkr"` entry. When enabled, `partition_positions()` automatically routes IB-institution rows to the `ibkr` provider and excludes them from SnapTrade/Plaid. If Gateway is down, routing falls back to aggregators automatically.

**Known issues addressed in this plan** (from Codex review round 1):
- **`"ib"` alias false positive**: `INSTITUTION_SLUG_ALIASES` has `"ib": "interactive_brokers"` with substring matching. `"ib" in "citibank"` → True. Fix: remove the `"ib"` alias; `"interactive brokers"` and `"ibkr"` cover real cases.
- **Probe-per-row**: `is_provider_available()` called per row in `partition_positions()`. Fix: cache probe result with 60s TTL.
- **Multi-account**: `_resolve_account_id()` raises if multiple accounts and no `account_id`. Fix: iterate `IBKR_AUTHORIZED_ACCOUNTS` explicitly.
- **TOCTOU**: If Gateway available during partition but down during fetch, IB rows lost. Fix: probe cache makes this window extremely unlikely (same cached result used for both partition and fetch within a call). Self-heals on next call.

## Step 1: Add `fetch_portfolio_items()` and `fetch_cash_balances()` to `ibkr/account.py`

**Why `ib.portfolio()` over `ib.reqPositions()`**: `reqPositions()` returns only `avgCost` (no market price/value). `ib.portfolio()` returns `marketPrice`, `marketValue`, `unrealizedPNL`, `realizedPNL` — everything we need.

```python
_PORTFOLIO_COLUMNS = [
    "account", "symbol", "sec_type", "currency", "exchange", "con_id",
    "local_symbol", "last_trade_date", "strike", "right", "multiplier",
    "position", "avg_cost", "market_price", "market_value",
    "unrealized_pnl", "realized_pnl",
]

def fetch_portfolio_items(ib, account_id: str | None = None) -> pd.DataFrame:
    """Fetch portfolio items with market values via reqAccountUpdates."""
    items = list(ib.portfolio() or [])
    if not items:
        ib.reqAccountUpdates(account=account_id or "")
        items = list(ib.portfolio() or [])

    rows: list[dict[str, Any]] = []
    for item in items:
        acct = getattr(item, "account", None)
        if account_id and acct != account_id:
            continue
        contract = getattr(item, "contract", None)
        rows.append({
            "account": acct,
            "symbol": getattr(contract, "symbol", None) if contract else None,
            "sec_type": getattr(contract, "secType", None) if contract else None,
            "currency": getattr(contract, "currency", None) if contract else None,
            "exchange": getattr(contract, "exchange", None) if contract else None,
            "con_id": getattr(contract, "conId", None) if contract else None,
            "local_symbol": getattr(contract, "localSymbol", None) if contract else None,
            "last_trade_date": getattr(contract, "lastTradeDateOrContractMonth", None) if contract else None,
            "strike": _safe_float(getattr(contract, "strike", None)) if contract else None,
            "right": getattr(contract, "right", None) if contract else None,
            "multiplier": getattr(contract, "multiplier", None) if contract else None,
            "position": _safe_float(getattr(item, "position", None)),
            "avg_cost": _safe_float(getattr(item, "averageCost", None)),
            "market_price": _safe_float(getattr(item, "marketPrice", None)),
            "market_value": _safe_float(getattr(item, "marketValue", None)),
            "unrealized_pnl": _safe_float(getattr(item, "unrealizedPNL", None)),
            "realized_pnl": _safe_float(getattr(item, "realizedPNL", None)),
        })
    if not rows:
        return pd.DataFrame(columns=_PORTFOLIO_COLUMNS)
    return pd.DataFrame(rows).sort_values(["account", "symbol"], na_position="last").reset_index(drop=True)


def fetch_cash_balances(ib, account_id: str | None = None) -> dict[str, float]:
    """Fetch per-currency cash balances from accountValues (CashBalance tag)."""
    account_values = list(ib.accountValues(account=account_id) or [])
    if not account_values:
        ib.reqAccountUpdates(account=account_id or "")
        account_values = list(ib.accountValues(account=account_id) or [])

    balances: dict[str, float] = {}
    for av in account_values:
        if account_id and getattr(av, "account", None) not in (None, "", account_id):
            continue
        if getattr(av, "tag", None) != "CashBalance":
            continue
        currency = getattr(av, "currency", None)
        if not currency or currency == "BASE":
            continue
        val = _safe_float(getattr(av, "value", None))
        if val is not None:
            balances[currency] = val
    return balances
```

**Key**: `CashBalance` tag gives per-currency breakdown. Filter out `currency == "BASE"` (total in base currency). Negative USD = margin debit.

## Step 2: Add facade methods to `ibkr/client.py`

```python
def get_portfolio_with_cash(self, account_id: str | None = None) -> tuple[pd.DataFrame, dict[str, float]]:
    """Fetch portfolio items and cash balances in single connection session."""
    with ibkr_shared_lock:
        with self._conn_manager.connection() as ib:
            resolved_account = self._resolve_account_id(ib, account_id)
            portfolio_df = fetch_portfolio_items(ib, account_id=resolved_account)
            cash = fetch_cash_balances(ib, account_id=resolved_account)
            return portfolio_df, cash
```

Single connection, single `reqAccountUpdates()` subscription populates both `portfolio()` and `accountValues()`.

Also add `get_managed_accounts()` for account discovery:
```python
def get_managed_accounts(self) -> list[str]:
    """Return list of managed account IDs from Gateway."""
    with ibkr_shared_lock:
        with self._conn_manager.connection() as ib:
            return list(ib.managedAccounts() or [])
```

**Multi-account handling**: `_resolve_account_id()` raises `IBKRAccountError` when multiple accounts exist and no `account_id` specified. The position provider (Step 3) handles this by:
1. Using `IBKR_AUTHORIZED_ACCOUNTS` if configured (explicit account list)
2. Falling back to `get_managed_accounts()` for account discovery
3. Last resort: `[None]` (single-account default)

## Step 3: Create `providers/ibkr_positions.py` (NEW)

Follow `providers/schwab_positions.py` pattern exactly.

```python
class IBKRPositionProvider:
    provider_name = "ibkr"

    def fetch_positions(self, user_email: str, **kwargs) -> pd.DataFrame:
        from ibkr.client import IBKRClient
        from ibkr.config import IBKR_AUTHORIZED_ACCOUNTS

        try:
            client = IBKRClient()
        except Exception as exc:
            raise RuntimeError(f"IBKR Gateway unavailable: {exc}") from exc

        # Multi-account: iterate authorized accounts explicitly
        # to avoid _resolve_account_id() raising on ambiguity.
        # When IBKR_AUTHORIZED_ACCOUNTS is empty, discover accounts
        # via get_managed_accounts(). If that also fails, try without
        # account_id (works for single-account setups).
        accounts_to_fetch = list(IBKR_AUTHORIZED_ACCOUNTS)
        if not accounts_to_fetch:
            try:
                accounts_to_fetch = client.get_managed_accounts()
            except Exception:
                accounts_to_fetch = [None]  # single-account fallback

        rows = []
        for acct in accounts_to_fetch:
            try:
                portfolio_df, cash_balances = client.get_portfolio_with_cash(account_id=acct)
            except Exception as exc:
                portfolio_logger.warning(f"IBKR position fetch failed for {acct}: {exc}")
                continue

            account_id = acct or ""

            # Securities from portfolio()
            for _, item in portfolio_df.iterrows():
                account_id = str(item.get("account") or account_id)
                sec_type = str(item.get("sec_type") or "").upper()
                if sec_type == "CASH":  # FX pairs — handled by cash_balances
                    continue
                ticker = _build_ticker(item, sec_type)
                rows.append({
                    "ticker": ticker,
                    "name": str(item.get("symbol") or ""),
                    "quantity": _to_float(item.get("position")),
                    "price": _to_float(item.get("market_price")),
                    "value": _to_float(item.get("market_value")),
                    "cost_basis": abs(_to_float(item.get("avg_cost")) * _to_float(item.get("position"))),
                    "currency": str(item.get("currency") or "USD"),
                    "type": _SEC_TYPE_MAP.get(sec_type, "equity"),
                    "account_id": account_id,
                    "account_name": account_id,
                    "brokerage_name": "Interactive Brokers",
                    "position_source": "ibkr",
                })

            # Per-currency cash from accountValues()
            for currency, balance in cash_balances.items():
                if balance == 0.0:
                    continue
                rows.append({
                    "ticker": f"CUR:{currency}",
                    "name": f"Cash ({currency})",
                    "quantity": balance, "price": 1.0, "value": balance,
                    "cost_basis": abs(balance),
                    "currency": currency, "type": "cash",
                    "account_id": account_id, "account_name": account_id,
                    "brokerage_name": "Interactive Brokers",
                    "position_source": "ibkr",
                })

        # Return empty DataFrame if no rows — let position_service raise
        # (consistent with Schwab/SnapTrade/Plaid providers)
        return pd.DataFrame(rows) if rows else pd.DataFrame()
```

**Ticker construction** (helper functions):
- `STK` → symbol directly (e.g., `AAPL`)
- `OPT`/`FOP` → `{SYMBOL}_{C|P}{STRIKE}_{YYMMDD}` (matching `ibkr/flex.py` convention)
- `FUT` → symbol root (e.g., `ES`), NOT `localSymbol` (e.g., `ESH6`). Downstream enrichment (`position_enrichment.py`, `exchange_mappings.yaml`) uses futures root symbols for detection. Store `localSymbol` as supplemental metadata if needed.

**sec_type map**: `STK→equity`, `OPT→option`, `FUT→derivative` (NOT "futures" — `position_enrichment.py:52` checks `type == "derivative"` for futures detection), `BOND→bond`, `FOP→option`, `FUND→mutual_fund`

**Skip `sec_type == "CASH"`** in portfolio items — these are FX pair positions that duplicate the `accountValues()` cash balances.

**Cash ticker**: `CUR:XXX` for all currencies (including USD as `CUR:USD`). This matches the existing `CUR:GBP` convention from SnapTrade. Note: Schwab uses `USD:CASH` but that's Schwab-specific.

## Step 4: Routing config — `providers/routing_config.py`

**4a. Uncomment IBKR position routing** (line 244):
```python
"interactive_brokers": "ibkr",
```

This activates routing: IB-institution rows go to `ibkr` provider, excluded from SnapTrade.

**4b. Remove `"ib"` alias** from `INSTITUTION_SLUG_ALIASES` (~line 336):

The `"ib"` alias uses substring matching (`if alias in name_lower`), which false-positives on "Citibank" (`"ib" in "citibank"` → True). Remove it — `"interactive brokers"` and `"ibkr"` cover all real institution names from SnapTrade/Plaid. This is also a pre-existing bug for transaction routing.

```python
# REMOVE: "ib": "interactive_brokers",
```

## Step 5: Routing module — `providers/routing.py`

**Add `"ibkr"` to `POSITION_PROVIDERS`** (line 39):
```python
POSITION_PROVIDERS = {"plaid", "snaptrade", "schwab", "ibkr"}
```

**Add Gateway reachability to `is_provider_available()`** (after the Schwab token check):

`partition_positions()` calls `institution_belongs_to_provider()` per row, which calls `is_provider_available()`. To avoid probing Gateway on every row, cache the result with a 60-second TTL at module level:

```python
_ibkr_probe_cache: tuple[float, bool] | None = None
_IBKR_PROBE_TTL = 60.0

if provider == "ibkr":
    import time as _time
    global _ibkr_probe_cache
    now = _time.monotonic()
    if _ibkr_probe_cache and (now - _ibkr_probe_cache[0]) < _IBKR_PROBE_TTL:
        if not _ibkr_probe_cache[1]:
            return False
    else:
        try:
            from ibkr.connection import IBKRConnectionManager
            probe = IBKRConnectionManager().probe_connection()
            reachable = probe.get("reachable", False)
            _ibkr_probe_cache = (now, reachable)
            if not reachable:
                return False
        except Exception:
            _ibkr_probe_cache = (now, False)
            return False
```

When Gateway is down, `is_provider_available("ibkr")` returns False → `institution_belongs_to_provider()` at routing.py:362 sees canonical is unavailable → falls back to SnapTrade/Plaid automatically. `probe_connection()` already exists (`ibkr/connection.py:299`): if already connected, returns immediately; otherwise does connect+disconnect.

The 60s cache also mitigates the TOCTOU risk: the same cached result is used during both `partition_positions()` and the actual IBKR fetch within a single `get_all_positions()` call.

**Cache invalidation on fetch failure**: If `IBKRPositionProvider.fetch_positions()` catches a connection error, it sets `_ibkr_probe_cache = (now, False)` so the next routing pass falls back to aggregators immediately rather than waiting for TTL expiry.

## Step 6: Position service registration — `services/position_service.py`

After the Schwab registration block (~line 125):
```python
if is_provider_enabled("ibkr"):
    if is_provider_available("ibkr"):
        from providers.ibkr_positions import IBKRPositionProvider
        position_providers["ibkr"] = IBKRPositionProvider()
    else:
        portfolio_logger.info(
            "IBKR provider enabled but Gateway unavailable; "
            "IBKR positions will come from aggregator providers."
        )
```

## Step 7: Cache TTL — `settings.py:438`

Add to `PROVIDER_CACHE_HOURS`:
```python
"ibkr": int(os.getenv("IBKR_CACHE_HOURS", "1")),  # Live data, short cache
```

## Step 8: Tests

**`tests/providers/test_ibkr_positions.py`** (NEW):
1. Basic equity position mapping (ticker, price, value, type, position_source)
2. Negative USD margin cash row (the whole point)
3. Multi-currency cash → separate `CUR:XXX` rows, zero-balance excluded
4. Option ticker construction (`AAPL_C200_260320`)
5. Futures ticker uses root symbol, type is "derivative"
6. Gateway down → RuntimeError
7. `sec_type == "CASH"` portfolio items skipped (no double-count with cash balances)
8. Multi-account iteration (2 accounts, positions from both)
9. Multi-account with empty IBKR_AUTHORIZED_ACCOUNTS → discovers via get_managed_accounts()
10. Fetch failure invalidates probe cache (sets _ibkr_probe_cache to False)

**`tests/ibkr/test_account_portfolio.py`** (NEW):
1. `fetch_portfolio_items()` basic extraction + account filtering
2. `fetch_cash_balances()` multi-currency, BASE excluded
3. Empty results

**`tests/providers/test_routing_ibkr.py`** (NEW):
1. IB rows routed to ibkr provider when available
2. IB rows excluded from snaptrade when ibkr is canonical
3. Fallback: ibkr unavailable → IB rows stay with snaptrade
4. Probe cache: `is_provider_available()` caches result (not re-probed per row)
5. "ib" alias removal: "Citibank" does NOT resolve to interactive_brokers
6. "IBKR" and "Interactive Brokers" still resolve correctly
7. Provider registration: ibkr not registered when Gateway unavailable

## Known Limitations

**Same-request TOCTOU**: If Gateway is available during `partition_positions()` (probe cache True) but goes down before `_fetch_fresh_positions("ibkr")`, IB positions are lost for that single request. This is an accepted tradeoff:
- Window is negligible (probe and fetch happen within the same HTTP request, typically <1s apart)
- Fetch failure invalidates the probe cache, so the next request falls back to SnapTrade
- Full solution (re-partition on failure) adds significant complexity for near-zero practical benefit
- The position service already handles provider failures gracefully (logs warning, continues)

## Files Modified

| File | Change |
|------|--------|
| `ibkr/account.py` | Add `fetch_portfolio_items()`, `fetch_cash_balances()` |
| `ibkr/client.py` | Add `get_portfolio_with_cash()`, `get_managed_accounts()` |
| `providers/ibkr_positions.py` (NEW) | `IBKRPositionProvider` class |
| `providers/routing_config.py:244` | Uncomment `"interactive_brokers": "ibkr"` |
| `providers/routing_config.py:336` | Remove `"ib"` alias (false-positive fix) |
| `providers/routing.py:39` | Add `"ibkr"` to `POSITION_PROVIDERS` |
| `providers/routing.py` (~line 278) | Gateway probe with 60s TTL in `is_provider_available()` |
| `services/position_service.py` (~line 125) | Register IBKR provider |
| `settings.py:441` | Add `"ibkr"` to `PROVIDER_CACHE_HOURS` |
| `tests/providers/test_ibkr_positions.py` (NEW) | 10 tests |
| `tests/ibkr/test_account_portfolio.py` (NEW) | 3 tests |
| `tests/providers/test_routing_ibkr.py` (NEW) | 7 tests |

## Verification

```bash
# Unit tests
pytest tests/providers/test_ibkr_positions.py -x -q
pytest tests/ibkr/test_account_portfolio.py -x -q
pytest tests/providers/test_routing_ibkr.py -x -q

# Existing tests (no regressions)
pytest tests/providers/ -x -q
pytest tests/ibkr/ -x -q

# Live test (Gateway must be running)
# MCP: get_positions(format="by_account") — verify IBKR positions with position_source="ibkr"
# MCP: get_performance(mode="realized", source="ibkr_flex") — verify cash anchor uses IBKR cash
```
