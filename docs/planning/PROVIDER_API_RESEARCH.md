# Provider API Research: FetchMetadata Feasibility

Date: 2026-02-17
Status: Complete
Purpose: Confirm API-level assumptions for the Provider-Native Flows Expansion Plan

---

## 1. Plaid

### API Model

Plaid uses **two different endpoints** for investment transactions:

- `/investments/transactions/get` — offset-based pagination (what our code currently uses)
- `/transactions/sync` — cursor-based pagination (for banking transactions, not investments)

**Our code** (`trading_analysis/data_fetcher.py:179-261`) uses `/investments/transactions/get` with `offset` + `count` pagination, NOT `/transactions/sync`.

### Pagination Exhaustion → `pagination_exhausted`

The response includes `total_investment_transactions` (integer). Our existing fetch loop already uses this:
```python
total = response_dict.get('total_investment_transactions', 0)
# ...
offset += len(transactions)
# loop exits when offset >= total or empty page
```

**Mapping**: `pagination_exhausted = True` when the loop exits normally (offset >= total).  
If an empty page occurs before `offset >= total`, treat as non-exhausted/partial (`pagination_exhausted=False`, `partial_data=True`) rather than authoritative exhaustion.

### Coverage Window → `payload_coverage_start` / `payload_coverage_end`

- `start_date` and `end_date` are **request parameters** we control (set from `days_back`).
- Individual transactions have a `date` field (YYYY-MM-DD).
- **Best approach**: Use the request `start_date`/`end_date` as `fetch_window_start`/`fetch_window_end`. Derive `payload_coverage_start`/`payload_coverage_end` from `min(tx['date'])` / `max(tx['date'])` of returned transactions.

### Account Metadata

Already available in our code (`data_fetcher.py:228-251`):
- `account_id` → `tx['account_id']` (from Plaid response)
- `account_name` → derived from `accounts` array (`official_name` or `name`)
- `institution` → derived from secret path: `secret_path.split("/")[-1]`

Our code already stamps each transaction with `_institution`, `_account_id`, `_account_name`.

### Gaps / Risks

- **Metadata must be per-institution + per-account**, not per-provider. Our fetch loop iterates over tokens (one per institution), then paginates within each. Metadata should be emitted as one row per account slice within each token loop (not token-aggregate rows).
- The `total_investment_transactions` count is reliable for pagination exhaustion.
- No explicit "partial data" signal from Plaid — if a page returns fewer than `page_size` records AND offset < total, that's ambiguous. Conservative: only mark exhausted when offset >= total.

### Documentation

- [Plaid Investments Transactions API](https://plaid.com/docs/api/products/transactions/)
- [Plaid Transactions Sync (banking, not investments)](https://plaid.com/docs/transactions/sync-migration/)

---

## 2. SnapTrade

### API Model

SnapTrade uses **offset/limit pagination** on the account-level activities endpoint:
```
GET /api/v1/accounts/{accountId}/activities?offset=0&limit=1000
```

Our code (`data_fetcher.py:89-176`) already implements this correctly:
- Lists all accounts via `list_user_accounts()`
- Fetches activities per account with offset/limit loop
- Response shape: `{'data': [...], 'pagination': {'total': N}}`

### Pagination Exhaustion → `pagination_exhausted`

The response includes `pagination.total` (integer). Our code already checks:
```python
offset += len(activities)
if offset >= total:
    break
```

**Mapping**: `pagination_exhausted = True` when `offset >= total` for the account. No explicit `has_more` field — exhaustion is derived from `offset >= total`.
If an empty page occurs before `offset >= total`, treat as non-exhausted/partial (`pagination_exhausted=False`, `partial_data=True`).

### Coverage Window → `payload_coverage_start` / `payload_coverage_end`

- `startDate` and `endDate` are request parameters we control.
- Individual activities can expose `trade_date`, `settlement_date`, or generic `date` depending on brokerage/source shape.
- **Best approach**: Same as Plaid — `fetch_window_*` from request params, `payload_coverage_*` from min/max of extractor-equivalent date fallback (`trade_date` OR `settlement_date` OR `date`) in returned data.

### Account Metadata

Already available in our code (`data_fetcher.py:124-168`):
- `account_id` → `account.get('id')` (UUID)
- `account_name` → `account.get('name')`
- `institution` → `account.get('institution_name')` (brokerage name)

Our code stamps each activity with `_account_id`, `_account_name`, `_brokerage_name`.

### Gaps / Risks

- **10,000 row cap per request**. If an account has >10K activities in the date window, even with pagination the API may not return all. However, per-account with 1000 limit + offset loop should handle this since the `total` field reflects the full count.
- `trade_date` granularity varies by brokerage — some only report date, not datetime.
- SnapTrade caches data and refreshes daily. `partial_data` should be `False` under normal conditions, but there's no explicit signal for stale cache vs fresh data.

### Documentation

- [SnapTrade Account Activities](https://docs.snaptrade.com/reference/Account%20Information/AccountInformation_getAccountActivities)
- [SnapTrade Transaction History (deprecated)](https://docs.snaptrade.com/reference/Transactions%20And%20Reporting/TransactionsAndReporting_getActivities)

---

## 3. IBKR Flex Query

### API Model

IBKR Flex is **not an API with pagination** — it's a batch XML report download. The `ib_async.FlexReport` class downloads the entire report in one shot via a two-step process (SendRequest → GetStatement).

Our code (`ibkr/flex.py:346-382`) currently only extracts the `Trade` section:
```python
flex_trades = report.extract("Trade")
```

### Available Sections for Cash Flows

Runtime extraction in this repo is via `ib_async.FlexReport.extract(topic)` (tag-based, case-sensitive).  
The ibflex type docs are useful reference material for likely fields/actions, but are not the runtime dependency.

Likely relevant sections:

| Section | Relevant for Cash Flows? |
|---------|--------------------------|
| **CashTransactions** | Yes — primary target |
| **Transfers** | Yes — deposits/withdrawals/ACATS |
| CashReport | Summary only (balances, not individual events) |
| Trades | Already extracted |
| OpenPositions | No |
| CorporateActions | Potentially (mergers, spinoffs) |
| InterestAccruals | Accrual-based, not cash events |

### CashTransactions Fields

From [IBKR's official documentation](https://www.ibkrguides.com/reportingreference/reportguide/cash%20transactionsfq.htm):

| Field | Maps To |
|-------|---------|
| `accountId` (Account ID) | `account_id` |
| `currency` (Currency) | flow event currency |
| `amount` (Amount) | flow amount (positive = inflow, negative = outflow) |
| `type` (Type) | flow classification — see CashAction enum below |
| `dateTime` (Date/Time) | event date |
| `description` (Description) | human-readable description |
| `symbol` (Symbol) | associated security (if any) |
| `conid` (Conid) | contract ID |
| `assetCategory` (Asset Class) | asset class of related security |
| `fxRateToBase` (FX Rate to Base) | FX conversion rate |
| `securityID` / `isin` / `cusip` | security identification |
| `underlyingSymbol` / `underlyingConid` | for derivatives |
| `tradeID` (Trade ID) | linked trade (for trade-related cash) |
| `code` (Code) | IBKR code abbreviations |
| `accountAlias` (Account Alias) | → `account_name` |

### CashAction Types (reference mapping)

| Enum Value | Description | Flow Classification |
|------------|-------------|---------------------|
| `DEPOSITWITHDRAW` | Deposits & Withdrawals | `contribution` or `withdrawal` (by amount sign) |
| `BROKERINTPAID` | Broker Interest Paid | `fee` / `is_external_flow=false` |
| `BROKERINTRCVD` | Broker Interest Received | `interest` / `is_external_flow=false` |
| `WHTAX` | Withholding Tax | `tax` / `is_external_flow=false` |
| `BONDINTRCVD` | Bond Interest Received | `interest` / `is_external_flow=false` |
| `BONDINTPAID` | Bond Interest Paid | `fee` / `is_external_flow=false` |
| `FEES` | Other Fees | `fee` / `is_external_flow=false` |
| `DIVIDEND` | Dividends | `dividend` / `is_external_flow=false` |
| `PAYMENTINLIEU` | Payment In Lieu Of Dividends | `dividend` / `is_external_flow=false` |
| `COMMADJ` | Commission Adjustments | `fee` / `is_external_flow=false` |
| `ADVISORFEES` | Advisor Fees | `fee` / `is_external_flow=false` |

**Key insight**: Only `DEPOSITWITHDRAW` maps to `is_external_flow=true`. All others are internal account events.

### Transfers Section Fields

The `Transfer` type in ibflex includes:
- `accountId`, `currency`, `quantity`, `transferPrice`, `positionAmount`
- `direction` (IN/OUT)
- `type` (e.g., ACATS)
- `date`, `dateTime`, `reportDate`
- `cashTransfer` (boolean — distinguishes cash transfers from position transfers)
- `transactionID`

**Transfers with `cashTransfer=True`** are cash movements that should map to external flows (deposits/withdrawals).

### Pagination Exhaustion → `pagination_exhausted`

Flex reports are **complete by definition** — the entire report for the configured date range is returned in one XML document.

**Mapping**:
- `pagination_exhausted = True` only when report download + parse succeeded.
- If credentials/download/parse fails, do **not** mark exhausted; emit failure metadata (`fetch_error` and/or `partial_data=True`) with `pagination_exhausted=False`.
- The report's `fromDate`/`toDate` attributes on the `FlexStatement` element define the coverage window when parse succeeds.

### Coverage Window

Available directly from the FlexStatement:
- `fromDate` → `payload_coverage_start`
- `toDate` → `payload_coverage_end`

These are also the `fetch_window_*` values since the query defines the range.

### Account Metadata

- `accountId` → per-row on CashTransactions and Transfers
- `accountAlias` → `account_name` (per-row)
- `institution` → hardcoded `"ibkr"` (single provider)

For multi-account Flex reports, rows are already tagged with `accountId`, so per-slice metadata is straightforward.

### Gaps / Risks

- **CashTransactions must be enabled in the Flex Query configuration**. If the user's Flex Query only includes Trades, the `CashTransactions` section will be absent. Need graceful handling.
- **`DEPOSITWITHDRAW` conflates deposits and withdrawals** — must use amount sign to distinguish (positive = deposit, negative = withdrawal).
- **Transfers with `cashTransfer=True`** overlap with `DEPOSITWITHDRAW` in CashTransactions. Need explicit precedence + overlap dedup policy.
- **No unique transaction ID guaranteed** across sections. `tradeID` on CashTransactions may be empty for non-trade cash events. May need to synthesize IDs from `dateTime` + `amount` + `type`.
- `FlexReport.extract(topic)` is topic/tag-name based and case-sensitive in runtime (`ib_async`). Validate exact topic names against a real report before implementation.
- `extract()` numeric parsing can coerce numeric-looking IDs. Preserve IDs as strings for stable dedup keys.

### Documentation

- [IBKR Cash Transactions Flex Fields](https://www.ibkrguides.com/reportingreference/reportguide/cash%20transactionsfq.htm)
- [IBKR Flex Web Service API](https://www.interactivebrokers.com/campus/ibkr-api-page/flex-web-service/)
- [ibflex Python library (Types.py)](https://github.com/csingley/ibflex/blob/master/ibflex/Types.py)
- [ibflex enums (CashAction)](https://github.com/csingley/ibflex/blob/master/ibflex/enums.py)

---

## Summary: FetchMetadata Mapping by Provider

| FetchMetadata Field | Plaid | SnapTrade | IBKR Flex |
|---------------------|-------|-----------|-----------|
| `pagination_exhausted` | `offset >= total_investment_transactions` (only when proven; empty-page-before-total is non-exhausted/partial) | `offset >= pagination.total` (only when proven; empty-page-before-total is non-exhausted/partial) | `True` only on successful report download + parse; otherwise `False` with failure metadata |
| `fetch_window_start` | Request `start_date` | Request `startDate` | FlexStatement `fromDate` |
| `fetch_window_end` | Request `end_date` | Request `endDate` | FlexStatement `toDate` |
| `payload_coverage_start` | `min(tx.date)` | `min(activity.trade_date/settlement_date/date fallback)` | FlexStatement `fromDate` |
| `payload_coverage_end` | `max(tx.date)` | `max(activity.trade_date/settlement_date/date fallback)` | FlexStatement `toDate` |
| `account_id` | `tx.account_id` | `account.id` (UUID) | Row-level `accountId` |
| `account_name` | `account.official_name \|\| name` | `account.name` | Row-level `accountAlias` |
| `institution` | From secret path | `account.institution_name` | Hardcoded `"ibkr"` |
| `row_count` | `len(transactions)` per account slice (within token loop) | `len(activities)` per account | `len(cash_rows)` per account (`0` on failed fetch with failure metadata) |

## Recommendations for the Expansion Plan

1. **Phase 1 is straightforward** — both Plaid and SnapTrade already have the necessary fields in our existing fetch code. The metadata construction is mostly bookkeeping around existing loops.

2. **Phase 3 IBKR field map is confirmed** — CashTransactions section has all needed fields. Use `report.extract("CashTransaction")` alongside existing `report.extract("Trade")`.

3. **IBKR precedence/dedup policy**: Use CashTransactions as primary source. Use `Transfer(cashTransfer=true)` only as secondary gap-fill path with overlap dedup.

4. **IBKR Flex Query config dependency**: Document that users must enable CashTransactions section in their Flex Query. Add a warning log if `report.extract("CashTransaction")` returns empty.

5. **Extract call naming**: Validate exact `ib_async.FlexReport.extract()` topic names and case against a real report before implementation.

6. **IBKR metadata trust signal**: Treat exhaustion as true only on successful download/parse; failed fetches must surface failure metadata, not empty-success metadata.
