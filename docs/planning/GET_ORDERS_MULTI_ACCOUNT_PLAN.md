# GET_ORDERS Multi-Account Fix

**Status:** DRAFT v4 (post Codex review R3 — 6 findings addressed)
**Bug:** `get_orders` MCP tool fails with "Multiple tradeable accounts found" on multi-account portfolios. Persistent across 5+ analyst sessions.
**Date:** 2026-04-07

---

## 1. Root Cause

`TradeExecutionService.get_orders()` (line 2093) calls `_resolve_target_account(account_id)` (line 2101). When `account_id=None` and 2+ tradeable accounts survive `_filter_for_auto_select()` (dedup + dormancy filtering), `_resolve_target_account` raises at line 2911:

```
"Multiple tradeable accounts found. Please specify account_id. Available: ..."
```

This error is correct for *write* operations (preview, execute, cancel) where ambiguity is dangerous. But for *read-only* operations like `get_orders`, the expected behavior is to return orders from **all** accounts merged together — the same way `get_positions` works across all providers.

The `_resolve_target_account()` method was designed for the order-placement path (ticker + side heuristics for SELL/COVER auto-select). `get_orders` was bolted onto the same resolution path despite being read-only.

### Call chain

```
MCP: get_orders(account_id=None)                  # mcp_tools/trading.py:87
  -> TradeExecutionService.get_orders(None)        # services/trade_execution_service.py:2093
    -> _resolve_target_account(None)               # line 2101 -> line 2838
      -> _filter_for_auto_select(accounts)         # line 2874
      -> len(filtered) > 1 -> RAISES               # line 2911
```

---

## 2. Fix Approach

**When `account_id=None` and multiple tradeable accounts exist, iterate all of them, fetch orders from each via the appropriate broker adapter, and merge results with account attribution.** Each order already carries `account_id` in both `_map_local_order_row` (line 3771) and can be added to `_map_remote_order_row`.

This is scoped to `get_orders` only. All write paths (`preview_order`, `execute_and_reconcile`, `cancel_order`) continue to require explicit account selection.

### Key design decisions (from Codex review feedback)

1. **Use `list_tradeable_accounts()` directly — skip `_filter_for_auto_select()` for the multi-account read path.** The dormant-filtering in `_filter_for_auto_select()` (line 3704: `active = [a for a in deduped if not _is_dormant(a)]`) drops zero-cash accounts when any active account exists. A zero-cash account can still have recent orders worth reading. SnapTrade dedup (lines 3698-3701) IS still applied because those are true duplicates, but dormant filtering is not. The dedup-only logic is extracted into a new `_dedup_snaptrade_accounts()` helper.

2. **Pass resolved `BrokerAccount` objects — never re-resolve inside the loop.** The original plan had `_get_orders_for_account(aid)` calling `_resolve_target_account(account_id)`, which calls `list_tradeable_accounts()` internally (line 2852). That fans out to every adapter's `list_accounts()` on each iteration — N redundant broker discovery calls for N accounts. Instead, the inner helper `_get_orders_for_resolved_account()` accepts the already-resolved `BrokerAccount` directly and looks up the adapter via `self._adapters[account.provider]` — a pure dict lookup using the `provider` field already present on `BrokerAccount` (line 416 in `trade_objects.py`). This completely avoids `_resolve_broker_adapter()`, which iterates all adapters and calls `owns_account()` on each — and SnapTrade's `owns_account()` (line 62 in `brokerage/snaptrade/adapter.py`) consults `_fetch_accounts()`, a network call. The `self._adapters` dict is keyed by provider name (`"snaptrade"`, `"ibkr"`, `"schwab"` — see lines 169-199 in `trade_execution_service.py`), which matches `BrokerAccount.provider` exactly.

3. **Per-order account attribution in `to_formatted_report()`.** The report format (line 401-406) prints order rows without account identification. A multi-account merged response would be ambiguous — you can't tell which account an order belongs to. Each order row now includes `[account_name]` or `[account_id]` when the value is present.

4. **MCP summary format gets `accounts_queried`.** The `format="summary"` path in `mcp_tools/trading.py` (lines 93-106) also needs multi-account context — `account_id` will be `None` for multi-account responses and callers need to know which accounts were included.

---

## 3. Code Changes

### 3.1 `services/trade_execution_service.py` — `get_orders()` (lines 2093-2194)

Replace the single-account flow with multi-account iteration when `account_id=None`.

**Current flow:**
```python
def get_orders(self, account_id=None, state="all", days=30):
    resolved_account = self._resolve_target_account(account_id)  # RAISES here
    account_id = str(resolved_account.account_id)
    adapter = self._resolve_broker_adapter(account_id)
    # ... fetch + merge for one account ...
```

**New flow:**
```python
def get_orders(self, account_id=None, state="all", days=30):
    try:
        if account_id:
            # Explicit account — resolve + fetch single account (unchanged behavior)
            resolved = self._resolve_target_account(account_id)
            return self._get_orders_for_resolved_account(resolved, state, days)

        # No account_id — discover once, dedup SnapTrade aliases, iterate ALL
        accounts, discovery_errors = self._list_tradeable_accounts_with_errors()
        deduped = _dedup_snaptrade_accounts(accounts)  # dedup only, NO dormant filter

        if not deduped:
            return OrderListResult(
                status="error",
                user_email=self.config.user_email,
                account_id=None,
                orders=[],
                state=state,
                days=int(days),
                error="No tradeable accounts found",
                provider_errors=discovery_errors,  # surface WHY no accounts found
            )

        if len(deduped) == 1:
            result = self._get_orders_for_resolved_account(deduped[0], state, days)
            if discovery_errors:
                # A provider failed discovery — surface it even in the single-account path.
                # Without this, e.g. Schwab down + 1 IBKR account = silent Schwab loss.
                result.provider_errors = discovery_errors
            return result

        # Multiple accounts — iterate + merge (no re-discovery)
        return self._get_orders_all_accounts(deduped, state, days, discovery_errors)
    except Exception as e:
        log_error("trade_execution", "get_orders", e)
        return OrderListResult(
            status="error",
            user_email=self.config.user_email,
            account_id=account_id,
            orders=[],
            state=state,
            days=int(days),
            error=str(e),
        )
```

**Why `_dedup_snaptrade_accounts()` instead of `_filter_for_auto_select()`:** The existing `_filter_for_auto_select()` (line 3687) has two phases: (1) SnapTrade dedup — correct for read path, (2) dormant filtering — drops zero-cash accounts when any active account exists (line 3704). A zero-cash account with recent orders would be invisible to `get_orders`. For the read-only path we need all accounts, with only the SnapTrade alias dedup applied.

### 3.2 New private method: `_get_orders_for_resolved_account()` (~line 2093)

Extract the existing single-account body into a helper that accepts an **already-resolved `BrokerAccount`** — no `_resolve_target_account` or `_resolve_broker_adapter` call inside. This eliminates all network calls when called in a loop.

```python
def _get_orders_for_resolved_account(
    self, account: BrokerAccount, state: str, days: int
) -> OrderListResult:
    """Fetch + merge local/remote orders for one already-resolved account.

    Accepts a BrokerAccount directly — callers must resolve the account
    before calling. Uses account.provider to look up the adapter via
    self._adapters[provider] (pure dict lookup, zero network calls).
    """
    account_id = str(account.account_id)
    provider = account.provider
    adapter = self._adapters.get(provider)
    if not adapter:
        raise ValueError(
            f"No adapter registered for provider '{provider}' "
            f"(account {account_id})"
        )

    # ... existing lines 2105-2174 unchanged ...
    # (remote fetch, upsert, local DB query, reconcile, dedup, sort)

    return OrderListResult(
        status="success",
        user_email=self.config.user_email,
        account_id=account_id,
        orders=local_payload,
        state=state,
        days=int(days),
    )
```

**Why not `_resolve_target_account()`:** That method (line 2838) calls `self.list_tradeable_accounts()` (line 2852), which fans out to every adapter's `list_accounts()` — a network call per broker. In the multi-account loop, we'd make N redundant discovery calls.

**Why not `_resolve_broker_adapter()`:** Despite appearing to be a dict lookup, `_resolve_broker_adapter()` (line 2915) iterates adapters and calls `owns_account()` on each. SnapTrade's `owns_account()` (line 62 in `brokerage/snaptrade/adapter.py`) calls `_fetch_accounts()` — a network call. Using `self._adapters[account.provider]` instead is a pure dict lookup with zero network overhead. The `self._adapters` dict keys (`"snaptrade"`, `"ibkr"`, `"schwab"`) match the `BrokerAccount.provider` values exactly because each adapter's `list_accounts()` populates `provider=self.provider_name` on the returned `BrokerAccount` objects.

### 3.3 New private method: `_get_orders_all_accounts()`

```python
def _get_orders_all_accounts(
    self,
    accounts: List[BrokerAccount],
    state: str,
    days: int,
    discovery_errors: Optional[Dict[str, str]] = None,
) -> OrderListResult:
    """Iterate all deduped tradeable accounts, merge orders, attribute per-account.

    Each account is already resolved — no broker re-discovery inside the loop.
    ``discovery_errors`` captures providers that failed during account discovery
    (from ``_list_tradeable_accounts_with_errors``). These are merged into the
    response's ``provider_errors`` so callers see which providers are missing.
    """
    all_orders: List[Dict[str, Any]] = []
    errors: List[str] = []
    accounts_queried: List[str] = []

    for account in accounts:
        aid = str(account.account_id)
        try:
            # Pass resolved BrokerAccount — no list_tradeable_accounts() re-call
            result = self._get_orders_for_resolved_account(account, state, days)
            if result.status == "success":
                # Ensure each order carries its account_id + display fields
                for order in result.orders:
                    order.setdefault("account_id", aid)
                    order.setdefault("account_name", account.account_name)
                    order.setdefault("provider", account.provider)
                all_orders.extend(result.orders)
                accounts_queried.append(aid)
            else:
                errors.append(f"{aid}: {result.error or 'unknown error'}")
        except Exception as e:
            errors.append(f"{aid}: {type(e).__name__}: {e}")

    # Sort merged orders by created_at descending (same as single-account)
    all_orders.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)

    # Merge discovery-phase errors (provider couldn't list accounts)
    # with per-account fetch errors into a unified provider_errors dict.
    # Matches the get_positions pattern (position_service.py:577,805).
    provider_errors: Dict[str, str] = dict(discovery_errors or {})
    for err_msg in errors:
        # errors list has "account_id: ExcType: message" strings
        # Also capture as provider-keyed if we can extract the provider
        pass  # provider_errors already has discovery failures;
              # per-account errors go into the error string below

    # Partial success: at least one account returned orders
    merged_status = "success" if accounts_queried else "error"
    all_error_parts = list(errors)
    for prov, err in (discovery_errors or {}).items():
        all_error_parts.append(f"{prov} (discovery): {err}")
    merged_error = "; ".join(all_error_parts) if all_error_parts else None

    return OrderListResult(
        status=merged_status,
        user_email=self.config.user_email,
        account_id=None,  # multi-account — no single account_id
        orders=all_orders,
        state=state,
        days=int(days),
        error=merged_error,
        accounts_queried=accounts_queried,
        provider_errors=provider_errors,  # NEW — discovery failures surfaced
    )
```

### 3.3a New module-level helper: `_dedup_snaptrade_accounts()`

Extracted from the first half of `_filter_for_auto_select()` (lines 3689-3702). Applies SnapTrade alias dedup **without** dormant filtering.

```python
def _dedup_snaptrade_accounts(accounts: List[BrokerAccount]) -> List[BrokerAccount]:
    """Dedup SnapTrade aliases that map to native broker accounts.

    Unlike _filter_for_auto_select(), does NOT filter dormant accounts.
    Used by the read-only get_orders path where zero-cash accounts
    may still have recent orders worth returning.
    """
    native_ids_present = {
        str(account.account_id)
        for account in accounts
        if account.provider != "snaptrade"
    }

    deduped: List[BrokerAccount] = []
    for account in accounts:
        account_id = str(account.account_id)
        if account.provider == "snaptrade" and account_id in TRADE_ACCOUNT_MAP:
            native_id = TRADE_ACCOUNT_MAP[account_id]
            if native_id in native_ids_present:
                continue
        deduped.append(account)

    return deduped
```

### 3.3b New private method: `_list_tradeable_accounts_with_errors()` (~line 252)

`list_tradeable_accounts()` (line 252) silently drops `adapter.list_accounts()` failures — only logs a warning. A provider can disappear from the merged result with no surfaced error. This conflicts with the `get_positions` pattern, which explicitly carries provider failures forward via `provider_errors: Dict[str, str]` (line 577) and attaches them to the result object (line 805).

New method returns both the account list and any discovery-phase errors:

```python
def _list_tradeable_accounts_with_errors(
    self,
) -> Tuple[List[BrokerAccount], Dict[str, str]]:
    """List tradeable accounts, capturing per-provider discovery failures.

    Unlike list_tradeable_accounts() which silently drops failures,
    this returns a (accounts, provider_errors) tuple so callers can
    surface which providers failed and why — matching the get_positions
    pattern at position_service.py:577,805.
    """
    all_accounts: List[BrokerAccount] = []
    provider_errors: Dict[str, str] = {}
    for adapter in self._adapters.values():
        try:
            all_accounts.extend(adapter.list_accounts())
        except Exception as e:
            portfolio_logger.warning(
                f"Failed to list accounts from {adapter.provider_name}: "
                f"{type(e).__name__}: {e}",
                exc_info=True,
            )
            provider_errors[adapter.provider_name] = f"{type(e).__name__}: {e}"
    return all_accounts, provider_errors
```

**Why a new method instead of modifying `list_tradeable_accounts()`:** The existing method is called from many sites (preview_order, execute, cancel, MCP list_accounts). Changing its return type would be a breaking change. The new method is only called from the `get_orders` multi-account path.

### 3.4 `_map_remote_order_row()` — add `account_id` (line 3735)

Currently `_map_remote_order_row` hardcodes `"account_id": None` (line 3750). Update to accept and pass through the account_id:

```python
def _map_remote_order_row(remote: OrderStatus, provider: str, account_id: str | None = None) -> Dict[str, Any]:
    # ...
    return {
        "id": None,
        "preview_id": None,
        "account_id": account_id,  # was: None
        # ... rest unchanged ...
    }
```

Update the call site at line 2172 inside `_get_orders_for_resolved_account` (formerly in `get_orders`):

```python
local_payload.append(_map_remote_order_row(remote, provider=adapter.provider_name, account_id=account_id))
```

### 3.5 `brokerage/trade_objects.py` — `OrderListResult` response shape (line 357)

The `account_id` field is already `Optional[str]`, so `None` is valid for multi-account responses. Add an `accounts_queried` field to the metadata so callers know which accounts were included:

```python
@dataclass
class OrderListResult:
    status: str
    user_email: str
    account_id: Optional[str]
    orders: List[Dict[str, Any]] = field(default_factory=list)
    state: str = "all"
    days: int = 30
    error: Optional[str] = None
    accounts_queried: List[str] = field(default_factory=list)  # NEW
    provider_errors: Dict[str, str] = field(default_factory=dict)  # NEW — discovery failures
```

Update `to_api_response()` metadata to include `accounts_queried`:

```python
"metadata": {
    "user_email": self.user_email,
    "account_id": self.account_id,  # None for multi-account
    "accounts_queried": self.accounts_queried,  # NEW — list of account_ids
    "provider_errors": self.provider_errors or None,  # NEW — which providers failed discovery
    "state": self.state,
    "days": self.days,
    "order_count": len(self.orders),
},
```

Update `to_formatted_report()` to show multi-account context in the header AND per-order account attribution in each row:

```python
def to_formatted_report(self) -> str:
    lines = [
        "Order List",
        f"- status: {self.status}",
        f"- account_id: {self.account_id or 'all (' + str(len(self.accounts_queried)) + ' accounts)'}",
        f"- state: {self.state}",
        f"- days: {self.days}",
        f"- count: {len(self.orders)}",
    ]
    if self.accounts_queried:
        lines.append(f"- accounts: {', '.join(self.accounts_queried)}")
    if self.provider_errors:
        for prov, err in self.provider_errors.items():
            lines.append(f"- ⚠ {prov} discovery failed: {err}")
    if self.error:
        lines.append(f"- error: {self.error}")
    for order in self.orders[:25]:
        # Per-order account label — critical for multi-account disambiguation
        acct_label = order.get("account_name") or order.get("account_id") or ""
        acct_prefix = f"[{acct_label}] " if acct_label else ""
        lines.append(
            f"  - {acct_prefix}"
            f"{order.get('status') or order.get('order_status')} "
            f"{order.get('action') or order.get('side')} "
            f"{order.get('units') or order.get('quantity')} "
            f"{order.get('ticker') or order.get('symbol')} "
            f"(id={order.get('brokerage_order_id') or order.get('id')})"
        )
    return "\n".join(lines)
```

**Why per-order attribution matters (Finding 3):** The current `to_formatted_report()` (line 388) prints order rows as `"  - FILLED BUY 100 AAPL (id=123)"` with no account context. When `format="report"` is used on a multi-account response, the agent cannot distinguish which account owns which order — making it impossible to issue cancel/follow-up commands. The `acct_prefix` adds `[Interactive Brokers]` or `[DU1234567]` to each row.

### 3.6 `mcp_tools/trading.py` — MCP tool `get_orders()` (lines 76-115)

**Minor update to the `summary` format.** The existing function signature already accepts `account_id: Optional[str] = None` and passes it through. The service-layer fix handles `full` and `report` formats automatically (additive fields). However, the `summary` format (lines 93-106) constructs its own response dict and needs `accounts_queried`:

```python
if format == "summary":
    status_counts = {}
    for order in result.orders:
        status = order.get("order_status") or "UNKNOWN"
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "status": result.status,
        "account_id": result.account_id,  # None for multi-account
        "accounts_queried": result.accounts_queried,  # NEW
        "provider_errors": result.provider_errors or None,  # NEW
        "state": state,
        "days": days,
        "order_count": len(result.orders),
        "status_counts": status_counts,
        "error": result.error,
    }
```

This is a one-line addition. The `full` format uses `to_api_response()` (updated in 3.5) and the `report` format uses `to_formatted_report()` (updated in 3.5), so those paths need no MCP-level changes.

### 3.7 `routes/trading.py` — REST endpoint `get_orders_endpoint()` (lines 199-229)

**No changes required.** The endpoint already passes `account_id=None` when not provided (line 219). The `to_api_response()` output is additive-only.

### 3.8 Frontend — `OrdersCard.tsx`

**No changes required for basic functionality.** The frontend `OrdersCard` already requires an account selection before showing orders (line 469-476: "Select an account to view orders" prompt when `!selectedAccountId`). The `useOrders` hook passes `accountId` to the API.

The MCP tool is the primary consumer that calls without `account_id`. The frontend always selects an account first.

**Optional future enhancement (out of scope):** An "All accounts" option in the account selector dropdown.

### 3.9 Frontend TypeScript types — `OrderListEnvelope` (line 353)

Add `accounts_queried` to the metadata type. This is additive and non-breaking:

```typescript
export interface OrderListEnvelope {
  // ... existing fields ...
  metadata: {
    user_email: string;
    account_id: string | null;  // was: string — update to allow null
    accounts_queried?: string[];  // NEW — optional for backward compat
    provider_errors?: Record<string, string> | null;  // NEW — discovery failures
    state: string;
    days: number;
    order_count: number;
  };
  // ...
}
```

---

## 4. Account Attribution on Merged Orders

Each order dict in the merged response will carry:

| Field | Source | Notes |
|-------|--------|-------|
| `account_id` | Already on local rows (from DB column). Added to remote rows via `_map_remote_order_row` param. | Required for cancel operations. |
| `account_name` | Set in `_get_orders_all_accounts()` from `BrokerAccount.account_name`. | Display label for agent/UI. |
| `provider` | Set in `_get_orders_all_accounts()` from `BrokerAccount.provider`. | Distinguishes IBKR vs SnapTrade vs Schwab. |

The `OrderRow` TypeScript interface already has `account_id: string | null` (line 337). The `account_name` and `provider` fields are new additions to the order dict but are not in the TypeScript type. They can be added as optional fields without breaking existing consumers:

```typescript
export interface OrderRow {
  // ... existing fields ...
  account_name?: string;  // NEW
  provider?: string;      // NEW
}
```

---

## 5. Error Handling — Partial Failures

The `_get_orders_all_accounts` method uses **best-effort iteration** with two error tiers:

### Tier 1: Discovery errors (provider-level)

`list_tradeable_accounts()` (line 252) silently drops `adapter.list_accounts()` failures — only logs a warning. One provider can disappear from the merged result with no surfaced error. This conflicts with the `get_positions` pattern, which explicitly collects `provider_errors: Dict[str, str]` (line 577) and attaches them to the result (line 805).

**Fix:** `_list_tradeable_accounts_with_errors()` (section 3.3b) returns a `(accounts, provider_errors)` tuple. Discovery failures are carried forward on `OrderListResult.provider_errors` — surfaced in `to_api_response()` metadata, `to_formatted_report()` header, and MCP summary format. The agent sees "schwab discovery failed: ConnectionError: ..." instead of silently missing Schwab accounts.

This matches the `get_positions` pattern:
- `position_service.py:577` — collects `provider_errors: Dict[str, str]`
- `position_service.py:628,665` — catches per-provider exceptions into the dict
- `position_service.py:805` — attaches `result.provider_errors = dict(provider_errors)` to the result
- `mcp_tools/positions.py:104-125` — extracts auth warnings from provider_errors for agent flags

### Tier 2: Per-account fetch errors

1. **All accounts succeed:** `status="success"`, `error=None`, `provider_errors={}`.
2. **Some accounts succeed, some fail:** `status="success"`, `error="acct-2: ConnectionError: ..."`. Orders from successful accounts are returned. The `accounts_queried` list shows which ones contributed. Any discovery errors appear in `provider_errors`.
3. **All accounts fail:** `status="error"`, `error` contains all error messages joined by `;`.
4. **Zero filtered accounts:** Handled before `_get_orders_all_accounts` is called — returns `status="error"` with "No tradeable accounts found".
5. **Discovery failure + some accounts succeed:** `status="success"` (partial data available), `provider_errors` shows which providers failed discovery, `error` string includes "provider (discovery): reason" entries alongside any per-account fetch errors.

---

## 6. Edge Cases

| Scenario | Behavior |
|----------|----------|
| Single account (current happy path) | `_dedup_snaptrade_accounts` returns 1 account -> single-account path via `_get_orders_for_resolved_account`, identical to today. |
| Explicit `account_id` provided | Bypasses multi-account entirely — resolves via `_resolve_target_account` then goes straight to `_get_orders_for_resolved_account`. |
| Mixed broker types (IBKR + Schwab) | Each account routes to its own adapter via `self._adapters[account.provider]` (pure dict lookup). Merged orders carry `provider` field. |
| SnapTrade dedup (mapped to native IBKR) | `_dedup_snaptrade_accounts` deduplicates — if SnapTrade maps to an IBKR native ID, only the native survives. |
| Dormant accounts (zero-cash) | **Included** in `get_orders` iteration. `_dedup_snaptrade_accounts()` does NOT filter dormant accounts — a zero-cash account may have recent orders. Only `_filter_for_auto_select()` (write paths) drops dormant accounts. |
| Mixed active + dormant | All accounts iterated. A portfolio with 1 active + 1 dormant account returns orders from both. The write-path `_filter_for_auto_select()` is NOT used here. |
| One account returns orders, another returns empty | Both succeed. Merged list just has orders from the non-empty account. |
| One account times out / errors | Partial success. Error recorded in `errors` list, other account's orders returned. |
| DB unavailable (`is_db_available() == False`) | The local-DB portions of `_get_orders_for_resolved_account` will fail. The `try/except` in `_get_orders_all_accounts` catches this per-account. Remote-only orders won't be reconciled but that's the existing no-DB behavior. |
| `account_id` on remote orders | Currently `None` in `_map_remote_order_row`. Fixed by passing `account_id` through (3.4). Critical for cancel operations on merged results. |
| Order dedup across accounts | Not needed — orders are account-scoped (each account has its own order namespace). No cross-account dedup required. |
| Provider discovery failure (e.g., Schwab down) | `_list_tradeable_accounts_with_errors()` catches the exception, records it in `provider_errors`, and continues with accounts from other providers. The failure surfaces in `OrderListResult.provider_errors`, `to_formatted_report()`, and MCP summary — not silently swallowed. Matches `get_positions` pattern. |
| All providers fail discovery | `_list_tradeable_accounts_with_errors()` returns empty accounts + errors. Hits the `if not deduped:` guard — returns `status="error"` with "No tradeable accounts found". Discovery errors still surfaced in the error message. |

---

## 7. Test Cases

### 7.1 Unit tests — `tests/services/test_trade_execution_service_order_sync.py`

**New tests:**

1. **`test_get_orders_multi_account_merges_all`** — Two mock accounts, each returns 2 orders. Verify merged result has 4 orders sorted by `created_at`, `account_id=None`, `accounts_queried` has both IDs, `status="success"`.

2. **`test_get_orders_multi_account_partial_failure`** — Two accounts, first succeeds with 2 orders, second raises. Verify merged result has 2 orders from first account, `status="success"`, `error` contains second account's error message.

3. **`test_get_orders_multi_account_all_fail`** — Two accounts, both raise. Verify `status="error"`, empty orders, error message contains both account errors.

4. **`test_get_orders_multi_account_empty_results`** — Two accounts, both succeed but return 0 orders. Verify `status="success"`, empty orders list, no error.

5. **`test_get_orders_single_account_auto_select_unchanged`** — One filtered account. Verify it still uses the single-account path (no `accounts_queried` in response or `accounts_queried` has 1 entry).

6. **`test_get_orders_explicit_account_bypasses_multi`** — Pass explicit `account_id`. Verify it routes to single-account path regardless of how many accounts exist.

7. **`test_get_orders_multi_account_order_attribution`** — Verify each order in merged result carries correct `account_id`, `account_name`, and `provider`.

8. **`test_get_orders_multi_account_remote_orders_have_account_id`** — Verify `_map_remote_order_row` populates `account_id` when provided.

9. **`test_get_orders_multi_account_state_filter_applied`** — State filter (e.g., `state="open"`) is applied per-account. Verify merged result only contains open orders.

10. **`test_get_orders_multi_account_sort_order`** — Orders from different accounts interleaved by `created_at` descending.

11. **`test_get_orders_mixed_active_dormant_includes_all`** — Two accounts: one active (cash=$50k), one dormant (cash=$0, funds=$0) with 3 recent orders. Mock `list_tradeable_accounts()` to return both. Verify merged result includes orders from **both** accounts — the dormant account is NOT filtered out. This directly validates Finding 1: `_filter_for_auto_select()` would drop the dormant account, but `_dedup_snaptrade_accounts()` does not.

12. **`test_get_orders_no_redundant_account_discovery`** — Two accounts (one IBKR, one Schwab). Mock `list_tradeable_accounts()` with a side_effect counter. Mock `_resolve_broker_adapter` with a side_effect counter. Spy on each adapter's `owns_account` method. Call `get_orders(account_id=None)`. Verify: (a) `list_tradeable_accounts()` called **exactly once** (in `get_orders`), not N+1 times; (b) `_resolve_target_account()` is **never called**; (c) `_resolve_broker_adapter()` is **never called** — the adapter is obtained via `self._adapters[account.provider]` instead; (d) no adapter's `owns_account()` is called — this is the method that triggers SnapTrade's `_fetch_accounts()` network call. This directly validates Findings 2 and 5.

13. **`test_get_orders_report_format_has_per_order_account_label`** — Two accounts with different `account_name` values, each returning 1 order. Call `get_orders()`, then `result.to_formatted_report()`. Verify each order line contains `[Account Name]` prefix. Verify the header shows `account_id: all (2 accounts)`. This directly validates Finding 3.

14. **`test_get_orders_dedup_snaptrade_but_keep_dormant`** — Three accounts: 1 native IBKR, 1 SnapTrade alias of that IBKR account (in `TRADE_ACCOUNT_MAP`), 1 dormant Schwab. Verify: SnapTrade alias is deduped out (2 accounts iterated), dormant Schwab is included. This validates both the dedup correctness and the dormant-inclusion behavior.

15. **`test_get_orders_multi_account_discovery_error_surfaced`** — Mock `_list_tradeable_accounts_with_errors()` to return 1 IBKR account successfully + `{"schwab": "ConnectionError: timeout"}` in `provider_errors`. Verify: (a) merged result has `status="success"` with orders from IBKR, (b) `result.provider_errors == {"schwab": "ConnectionError: timeout"}`, (c) `result.error` contains `"schwab (discovery)"`, (d) `to_formatted_report()` output contains the schwab discovery failure line. This directly validates Finding 6.

16. **`test_get_orders_multi_account_all_discovery_fail`** — Mock `_list_tradeable_accounts_with_errors()` to return empty accounts + errors for both providers. Verify: `status="error"`, `error="No tradeable accounts found"`, empty orders.

17. **`test_get_orders_multi_account_provider_errors_in_api_response`** — Mock a discovery error. Call `result.to_api_response()`. Verify `metadata["provider_errors"]` contains the provider name and error string.

### 7.2 Existing tests — no regressions

- `test_resolve_target_account_cover_auto_selects_single_short_holder` — Unchanged, cover path still works.
- `test_resolve_target_account_explicit_lookup_unaffected_by_auto_filter` — Unchanged, explicit path untouched.
- `test_order_list_result_to_api_response_and_report_truncates_rows` — Should pass with new `accounts_queried` field (it's additive).

### 7.3 MCP tool test

18. **`test_mcp_get_orders_no_account_id_multi_account`** — Call MCP `get_orders()` with no `account_id`, mock 2 tradeable accounts. Verify response contains merged orders, no error.

19. **`test_mcp_get_orders_summary_format_has_accounts_queried`** — Call MCP `get_orders(format="summary")` with no `account_id`, mock 2 tradeable accounts. Verify response dict contains `accounts_queried` list with both account IDs. This validates the MCP summary format update from 3.6.

20. **`test_mcp_get_orders_summary_format_has_provider_errors`** — Call MCP `get_orders(format="summary")` with a discovery failure mocked. Verify response dict contains `provider_errors` with the failed provider. This validates Finding 6 at the MCP layer.

---

## 8. Files Changed

| File | Change |
|------|--------|
| `services/trade_execution_service.py` | Refactor `get_orders()` into multi-account-aware flow. Extract `_get_orders_for_resolved_account()` (accepts `BrokerAccount`, no re-discovery). Add `_get_orders_all_accounts()`. Add `_dedup_snaptrade_accounts()`. Add `_list_tradeable_accounts_with_errors()` (error-surfacing variant of `list_tradeable_accounts()`). Update `_map_remote_order_row` signature. |
| `brokerage/trade_objects.py` | Add `accounts_queried` and `provider_errors` fields to `OrderListResult`. Update `to_api_response()` and `to_formatted_report()` (per-order account labels, provider error lines). |
| `mcp_tools/trading.py` | Add `accounts_queried` to `summary` format response dict (1 line). |
| `frontend/packages/chassis/src/services/APIService.ts` | Add optional `accounts_queried` to `OrderListEnvelope.metadata`, optional `account_name`/`provider` to `OrderRow`. Make `metadata.account_id` nullable. |
| `tests/services/test_trade_execution_service_order_sync.py` | 17 new test cases (tests 1-17). |
| `tests/mcp_tools/test_trading_mcp.py` (or similar) | 3 new MCP-level tests (tests 18-20). |

**Not changed:** `routes/trading.py`, `OrdersCard.tsx`, broker adapters. `_filter_for_auto_select()` is NOT modified — it continues to serve the write paths unchanged.

---

## 9. Rollout Risk

**Low.** This is a backward-compatible change:
- Single-account users see identical behavior (auto-select path is unchanged).
- Explicit `account_id` callers see identical behavior.
- The response envelope adds optional fields only.
- The frontend `OrdersCard` always passes an explicit `account_id`, so it is unaffected.
- The only consumer hitting the bug is the MCP tool with no `account_id` — and it currently gets an error, so any valid response is an improvement.

---

## 10. Codex Review Finding Resolution

| # | Finding | Resolution | Plan section |
|---|---------|-----------|-------------|
| 1 | **Dormant filtering contradicts "all accounts" goal**: `_filter_for_auto_select()` drops zero-cash accounts when any active account exists. A dormant account with recent orders becomes invisible. | Replaced `_filter_for_auto_select()` with `_dedup_snaptrade_accounts()` in the `get_orders` path. Dedup-only, no dormant filtering. `_filter_for_auto_select()` unchanged for write paths. | 3.1, 3.3a, edge cases |
| 2 | **Helper re-discovers accounts on every iteration**: `_get_orders_for_account(aid)` called `_resolve_target_account()` which calls `list_tradeable_accounts()` (N fan-out calls). | Renamed to `_get_orders_for_resolved_account(account: BrokerAccount)`. Accepts already-resolved account object. Uses `self._adapters[account.provider]` (pure dict lookup) instead of `_resolve_broker_adapter()` which calls `owns_account()` per adapter (SnapTrade's is a network call). `list_tradeable_accounts()` called once in `get_orders()`. | 3.2, 3.3 |
| 3 | **MCP report format needs per-order account attribution**: `to_formatted_report()` prints order rows without account context. Multi-account response is ambiguous. | Added `[account_name]` prefix to each order row in `to_formatted_report()`. Added `accounts_queried` to summary format in MCP tool. | 3.5, 3.6 |
| 4 | **Missing test cases**: Mixed active+dormant and repeated-account-discovery not covered. | Added tests 11-14: mixed active+dormant inclusion, no-redundant-discovery counter, report format account labels, dedup-but-keep-dormant. Added test 16: MCP summary format. | 7.1 (tests 11-14), 7.3 (test 16) |
| 5 | **`_resolve_broker_adapter()` is not a pure dict lookup**: It iterates adapters and calls `owns_account()`, and SnapTrade's `owns_account()` (line 62 in `brokerage/snaptrade/adapter.py`) calls `_fetch_accounts()` — a network call. So the loop still does per-account ownership-resolution work. | Replaced `_resolve_broker_adapter(account_id)` with `self._adapters[account.provider]` — a pure dict lookup using the `provider` field already on `BrokerAccount`. The `self._adapters` dict keys match `BrokerAccount.provider` values exactly. `_resolve_broker_adapter()` is no longer called anywhere in the multi-account path. Test 12 updated to verify `_resolve_broker_adapter` and `owns_account` are never called. | 3.2, 7.1 (test 12) |
| 6 | **`list_tradeable_accounts()` silently drops provider failures**: `adapter.list_accounts()` failures are only logged (line 258-262). One provider can disappear from the merged result with no surfaced error. This conflicts with the `get_positions` pattern where `provider_errors` are explicitly carried forward (position_service.py:577,805). | Added `_list_tradeable_accounts_with_errors()` — returns `(accounts, provider_errors)` tuple. Discovery errors flow into `OrderListResult.provider_errors` dict, `to_api_response()` metadata, `to_formatted_report()` header, and MCP summary format. Matches the `get_positions` pattern exactly. Original `list_tradeable_accounts()` unchanged (used by write paths). Tests 15-17 and 20 validate. | 3.3b, 3.5, 3.6, 5, 7.1 (tests 15-17), 7.3 (test 20) |
