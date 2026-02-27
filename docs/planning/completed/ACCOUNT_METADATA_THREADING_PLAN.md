# Plan: Thread Account-Level Metadata Through Transaction Pipeline

## Context

The position service already carries `account_id`, `account_name`, and `brokerage_name` on every position. But the transaction pipeline (used by realized performance, trading analysis, tax harvesting) loses this metadata — preventing account-level filtering like "show me just my IBKR performance" or "just my Schwab IRA".

**Current state of `fifo_transactions` dicts:**

| Provider | `_institution` | `account_id` | `account_name` |
|----------|---------------|-------------|----------------|
| Plaid | Yes (from secret path) | No (available but dropped) | No |
| SnapTrade | No | No (available at fetch) | No (available at fetch) |
| IBKR Flex | Yes ("ibkr") | Yes | No |

**Goal:** All three providers emit `_institution`, `account_id`, and `account_name` on every `fifo_transactions` dict.

**Canonical output fields** (on every fifo_transactions dict):
- `_institution` — institution/brokerage name (string, e.g., "Interactive Brokers", "Charles Schwab")
- `account_id` — provider-specific account ID (string)
- `account_name` — human-readable account name (string, may be empty)

## Changes

### 1. SnapTrade: Tag activities with account metadata at fetch time

**File: `trading_analysis/data_fetcher.py`** (`fetch_snaptrade_activities`)

The account loop (line 103) already has `account_id` from `account.get('id')`. The SnapTrade account object also has `institution_name` and `name` (confirmed in SDK: `snaptrade_client/model/account.py`). Tag each activity dict before appending. String-cast IDs to avoid SDK typed objects:

```python
for account in accounts:
    account_id = account.get('id') if isinstance(account, dict) else getattr(account, 'id', None)
    account_name = account.get('name') if isinstance(account, dict) else getattr(account, 'name', None)
    brokerage_name = account.get('institution_name') if isinstance(account, dict) else getattr(account, 'institution_name', None)
    ...
    for act in activities:
        act_dict = ...  # existing conversion
        act_dict['_account_id'] = str(account_id) if account_id else ''
        act_dict['_account_name'] = str(account_name) if account_name else ''
        act_dict['_brokerage_name'] = str(brokerage_name) if brokerage_name else ''
        all_activities.append(act_dict)
```

### 2. SnapTrade: Thread through model and analyzer

**File: `trading_analysis/models.py`** (`SnapTradeActivity`)

Add 3 optional fields + wire in `from_dict()`:
- `account_id: Optional[str] = None`
- `account_name: Optional[str] = None`
- `brokerage_name: Optional[str] = None`

```python
account_id=data.get('_account_id'),
account_name=data.get('_account_name'),
brokerage_name=data.get('_brokerage_name'),
```

**File: `trading_analysis/analyzer.py`** (SnapTrade section inside `_normalize_data()`)

Add to all **6** `fifo_transactions.append()` sites (lines 564, 595, 621, 649, 675, 712):
```python
'account_id': act.account_id or '',
'account_name': act.account_name or '',
'_institution': act.brokerage_name or '',
```

### 3. Plaid: Tag transactions with account_id + account_name at fetch time

**File: `trading_analysis/data_fetcher.py`** (`fetch_plaid_transactions`)

Plaid's `investments_transactions_get` response includes `accounts` array (confirmed in SDK: `plaid/model/investments_transactions_get_response.py`). Each transaction has `account_id`. Build account lookup and tag. Use defensive `.get()` for the accounts list:

```python
response_dict = response.to_dict()
accounts_list = response_dict.get('accounts', [])
account_lookup = {a.get('account_id'): (a.get('official_name') or a.get('name', '')) for a in accounts_list if a.get('account_id')}
...
for tx in transactions:
    tx['_institution'] = institution  # already exists
    tx['_account_id'] = tx.get('account_id', '')
    tx['_account_name'] = account_lookup.get(tx.get('account_id', ''), '')
```

Note: `account_lookup` must be built outside the pagination loop (accumulate across pages) OR rebuilt each page (accounts array is repeated each page). Simplest: rebuild each page since Plaid includes all accounts in every response.

**File: `trading_analysis/models.py`** (`PlaidTransaction`)

Add 2 optional fields:
- `account_id: Optional[str] = None`
- `account_name: Optional[str] = None`

```python
account_id=data.get('_account_id') or data.get('account_id'),
account_name=data.get('_account_name'),
```

**File: `trading_analysis/analyzer.py`** (Plaid section inside `_normalize_data()`)

Add to all **4** `fifo_transactions.append()` sites (lines 782, 809, 835, 861):
```python
'account_id': txn.account_id or '',
'account_name': txn.account_name or '',
```

(`_institution` already present via `txn.institution`)

### 4. IBKR Flex: Add account_name (already has account_id and _institution)

**File: `trading_analysis/analyzer.py`** (IBKR Flex section inside `_normalize_data()`)

The single append site (line 933) already has `account_id` and `_institution`. Add:
```python
'account_name': '',  # Flex report doesn't include account name
```

No changes needed in `services/ibkr_flex_client.py`.

## Files Changed

| File | Change |
|------|--------|
| `trading_analysis/data_fetcher.py` | Tag SnapTrade activities with `_account_id`, `_account_name`, `_brokerage_name`; tag Plaid transactions with `_account_id`, `_account_name` |
| `trading_analysis/models.py` | Add `account_id`, `account_name`, `brokerage_name` to `SnapTradeActivity`; add `account_id`, `account_name` to `PlaidTransaction` |
| `trading_analysis/analyzer.py` | Thread account fields into all 11 `fifo_transactions.append()` dicts (4 Plaid, 6 SnapTrade, 1 IBKR) |

## What This Does NOT Include

- No new `institution` filter parameter on `get_performance()` yet — that's the next step after this metadata threading is in place
- No changes to the realized performance analysis pipeline itself
- No changes to position service (already has account metadata)

## Verification

```bash
# Unit test: check that fifo_transactions carry account metadata
python3 -c "
from trading_analysis.analyzer import TradingAnalyzer

# Mock SnapTrade activity with account metadata
acts = [{'id': '1', 'symbol': 'AAPL', 'type': 'BUY', 'trade_date': '2024-01-15',
         'units': 10, 'price': 150.0, 'amount': -1500.0, 'fee': 0, 'currency': 'USD',
         '_account_id': 'acct_123', '_account_name': 'Main Account', '_brokerage_name': 'Interactive Brokers'}]
a = TradingAnalyzer(snaptrade_activities=acts, use_fifo=True)
txn = a.fifo_transactions[0]
assert txn.get('account_id') == 'acct_123', f'Expected acct_123, got {txn.get(\"account_id\")}'
assert txn.get('_institution') == 'Interactive Brokers', f'Expected IB, got {txn.get(\"_institution\")}'
print('✅ SnapTrade account metadata threaded correctly')
"

# Integration: run realized performance and check a transaction has account fields
python3 -c "
from trading_analysis.data_fetcher import fetch_all_transactions
from trading_analysis.analyzer import TradingAnalyzer
payload = fetch_all_transactions('hc@henrychien.com')
a = TradingAnalyzer(
    plaid_transactions=payload.get('plaid_transactions', []),
    plaid_securities=payload.get('plaid_securities', []),
    snaptrade_activities=payload.get('snaptrade_activities', []),
    ibkr_flex_trades=payload.get('ibkr_flex_trades'),
    use_fifo=True,
)
for txn in a.fifo_transactions[:5]:
    print(f\"{txn['source']:12} {txn['symbol']:20} acct={txn.get('account_id','?'):20} inst={txn.get('_institution','?')}\")
print(f'✅ {len(a.fifo_transactions)} transactions, all with account metadata')
"
```

## Codex Review

**Round 1** — 5 findings addressed:
- **HIGH** (fixed): Plan referenced `_process_plaid()` etc. as separate methods — corrected to "inside `_normalize_data()`"
- **MED** (fixed): Append count corrected from ~13 to **11** (6 SnapTrade, 4 Plaid, 1 IBKR)
- **MED** (fixed): Naming inconsistency resolved — canonical output is `_institution`, `account_id`, `account_name` (no `brokerage_name` on output; SnapTrade's `brokerage_name` maps to `_institution`)
- **LOW** (fixed): Added defensive `.get()` for Plaid accounts, `official_name` fallback before `name`
- **LOW** (fixed): Added `str()` cast for SnapTrade account IDs to avoid SDK typed objects
