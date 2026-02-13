# SnapTrade Integration - Implementation Plan

## 🎯 **Executive Summary**

**Objective**: Integrate SnapTrade API to expand broker coverage (Fidelity, Schwab) alongside existing Plaid integration.

**Key Finding**: Your existing architecture is **perfectly designed** for multi-provider integration. Minimal changes needed.

**Timeline**: 15-18 days for full production-ready integration.

---

## 🔍 **Architecture Analysis Results**

### ✅ **What Works Perfectly (No Changes Needed)**
- **Database Schema**: Existing `positions` table with `position_source` field supports multi-provider
- **Risk Analysis Engine**: Already provider-agnostic, reads consolidated positions
- **Cash Mapping**: Existing `CUR:USD → SGOV` mapping works for SnapTrade cash
- **Factor Proxies**: Assigned by ticker (AAPL from any provider gets same proxies)
- **Frontend UI**: Institution selection already built and ready

### 🔍 **Complete Consolidation Analysis**

**We need THREE separate consolidation steps:**

#### **1. Plaid Internal Consolidation** ✅ **Already Exists**
```python
# routes/plaid.py - EXISTING
holdings_df = load_all_user_holdings(user_id, region_name, client)  # Multiple Plaid accounts
holdings_df = consolidate_holdings(holdings_df)  # ← Sums duplicates across Plaid accounts
# Result: Database gets ONE position per ticker from Plaid (already consolidated)
```

#### **2. SnapTrade Internal Consolidation** ❌ **Need to Create**
```python
# routes/snaptrade.py - NEEDED
holdings_df = load_all_user_snaptrade_holdings(user_id, region_name)  # Multiple SnapTrade accounts  
holdings_df = consolidate_snaptrade_holdings(holdings_df)  # ← Sum duplicates across SnapTrade accounts
# Result: Database gets ONE position per ticker from SnapTrade (consolidated)
```

#### **3. Multi-Provider Consolidation** ❌ **Need to Create**
```python
# portfolio_manager.py - NEEDED
raw_positions = db_client.get_portfolio_positions()  # Gets positions from ALL providers
# Example: AAPL from Plaid (100 shares) + AAPL from SnapTrade (50 shares) + AAPL manual (25 shares)
consolidated_positions = self._consolidate_positions(raw_positions)  # ← Sum across providers
# Result: AAPL 175 shares total (no data loss)
```

**The Problem**: Without step 3, `_apply_cash_mapping()` dictionary overwrites cause data loss.
**The Solution**: Add multi-provider consolidation to `PortfolioManager` (Phase 2).

---

## 🚀 **Implementation Plan**

### **Phase 1: Core SnapTrade Integration** (5-6 days)

#### **1.1 Create `snaptrade_loader.py`** (3 days)
**Pattern**: Mirror `plaid_loader.py` exactly - proven architecture.

**Complete snaptrade_loader.py Implementation Scaffolding**:
```python
#!/usr/bin/env python
# file: snaptrade_loader.py

import os
import boto3
import json
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional
from botocore.exceptions import ClientError
from snaptrade_client import SnapTrade
from snaptrade_client.api_client import ApiException

# ═══════════════════════════════════════════════════════════════════════════════
# 🔧 SNAPTRADE SDK CLIENT SETUP
# ═══════════════════════════════════════════════════════════════════════════════

def get_snaptrade_client(region_name: str) -> SnapTrade:
    """Initialize SnapTrade SDK client with credentials from AWS Secrets Manager"""
    app_credentials = get_snaptrade_app_credentials(region_name)
    
    return SnapTrade(
        consumer_key=app_credentials['consumer_key'],
        client_id=app_credentials['client_id']
    )

# ═══════════════════════════════════════════════════════════════════════════════
# 🔐 AWS SECRETS MANAGER FUNCTIONS (Copy from plaid_loader.py pattern)
# ═══════════════════════════════════════════════════════════════════════════════

def store_snaptrade_app_credentials(client_id: str, consumer_key: str, environment: str, region_name: str):
    """Store SnapTrade app-level credentials in AWS Secrets Manager"""
    # TODO: Implement similar to store_plaid_credentials()
    pass

def get_snaptrade_app_credentials(region_name: str) -> Dict[str, str]:
    """Get SnapTrade app-level credentials from AWS Secrets Manager"""
    # TODO: Implement similar to get_plaid_credentials()
    pass

def store_snaptrade_user_secret(user_id: str, user_secret: str, region_name: str):
    """Store SnapTrade user secret in AWS Secrets Manager"""
    # TODO: Implement similar to store_plaid_token()
    pass

def get_snaptrade_user_secret(user_id: str, region_name: str) -> str:
    """Get SnapTrade user secret from AWS Secrets Manager"""
    # TODO: Implement similar to get_plaid_token()
    pass

# ═══════════════════════════════════════════════════════════════════════════════
# 🔐 CORE SNAPTRADE SDK FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def register_snaptrade_user(user_id: str, region_name: str) -> str:
    """Register a new user with SnapTrade and store user secret"""
    snaptrade = get_snaptrade_client(region_name)
    
    try:
        register_response = snaptrade.authentication.register_snap_trade_user(
            body={"userId": user_id}
        )
        user_secret = register_response.body["userSecret"]
        
        # Store user secret in AWS Secrets Manager
        store_snaptrade_user_secret(user_id, user_secret, region_name)
        
        print(f"✅ Registered SnapTrade user: {user_id}")
        return user_secret
        
    except ApiException as e:
        print(f"❌ Error registering SnapTrade user {user_id}: {e}")
        raise e

def generate_connection_portal_url(user_id: str, user_secret: str, region_name: str) -> str:
    """Generate SnapTrade connection portal URL"""
    snaptrade = get_snaptrade_client(region_name)
    
    try:
        redirect_uri = snaptrade.authentication.login_snap_trade_user(
            query_params={"userId": user_id, "userSecret": user_secret}
        )
        portal_url = redirect_uri.body["redirectURI"]
        
        print(f"✅ Generated SnapTrade portal URL for user: {user_id}")
        return portal_url
        
    except ApiException as e:
        print(f"❌ Error generating portal URL for {user_id}: {e}")
        raise e

def list_user_accounts(user_id: str, user_secret: str, region_name: str) -> List[Dict]:
    """List all SnapTrade accounts for a user"""
    snaptrade = get_snaptrade_client(region_name)
    
    try:
        accounts = snaptrade.account_information.list_user_accounts(
            user_id=user_id,
            user_secret=user_secret
        )
        
        print(f"✅ Retrieved {len(accounts.body)} SnapTrade accounts for user: {user_id}")
        return accounts.body
        
    except ApiException as e:
        print(f"❌ Error listing accounts for {user_id}: {e}")
        raise e

def get_user_account_positions(user_id: str, user_secret: str, account_id: str, region_name: str) -> List[Dict]:
    """Get positions for a specific SnapTrade account"""
    snaptrade = get_snaptrade_client(region_name)
    
    try:
        positions = snaptrade.account_information.get_user_account_positions(
            user_id=user_id,
            user_secret=user_secret,
            account_id=account_id
        )
        
        print(f"✅ Retrieved {len(positions.body)} positions for account: {account_id}")
        return positions.body
        
    except ApiException as e:
        print(f"❌ Error getting positions for account {account_id}: {e}")
        raise e

# ═══════════════════════════════════════════════════════════════════════════════
# 📊 DATA PROCESSING & CONSOLIDATION FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def load_all_user_snaptrade_holdings(user_id: str, region_name: str) -> pd.DataFrame:
    """Load holdings from ALL SnapTrade accounts for a user and return as DataFrame"""
    user_secret = get_snaptrade_user_secret(user_id, region_name)
    
    # Get all accounts
    accounts = list_user_accounts(user_id, user_secret, region_name)
    
    # Get positions for each account
    all_positions = []
    for account in accounts:
        positions = get_user_account_positions(user_id, user_secret, account['id'], region_name)
        
        # Add account metadata to each position
        for position in positions:
            position['account_id'] = account['id']
            position['institution_name'] = account.get('institution_name', 'Unknown')
        
        all_positions.extend(positions)
    
    # Convert to DataFrame and normalize
    holdings_df = normalize_snaptrade_holdings(all_positions)
    
    print(f"✅ Loaded {len(holdings_df)} holdings from {len(accounts)} SnapTrade accounts")
    return holdings_df

def normalize_snaptrade_holdings(holdings_response: List[Dict]) -> pd.DataFrame:
    """Convert SnapTrade holdings format to DataFrame matching Plaid format"""
    if not holdings_response:
        return pd.DataFrame()
    
    normalized_holdings = []
    for holding in holdings_response:
        # Map SnapTrade fields to our standard format (MATCH PLAID STRUCTURE)
        normalized = {
            'ticker': holding.get('symbol', {}).get('symbol', ''),
            'quantity': float(holding.get('units', 0)),
            'value': float(holding.get('price', 0)) * float(holding.get('units', 0)),
            'cost_basis': float(holding.get('average_purchase_price', 0)),
            'currency': holding.get('currency', 'USD'),
            'type': _map_snaptrade_security_type(holding.get('instrument_type', '')),
            'account_id': holding.get('account_id', ''),
            'institution_name': holding.get('institution_name', ''),
            'last_updated': pd.Timestamp.now(),
            'position_source': 'snaptrade'  # KEY: This identifies SnapTrade positions
        }
        normalized_holdings.append(normalized)
    
    df = pd.DataFrame(normalized_holdings)
    print(f"✅ Normalized {len(df)} SnapTrade holdings")
    return df

def _map_snaptrade_security_type(snaptrade_type: str) -> str:
    """Map SnapTrade security types to our standard types"""
    type_mapping = {
        'EQUITY': 'equity',
        'ETF': 'etf',
        'MUTUAL_FUND': 'mutual_fund',
        'BOND': 'bond',
        # Map option-like instruments to 'derivative' so shared filtering excludes them
        'OPTION': 'derivative',
        'WARRANT': 'derivative',
        'RIGHT': 'derivative',
        'FUTURE': 'derivative',
        'SWAP': 'derivative',
        'FORWARD': 'derivative',
        'CFD': 'derivative',
        'CRYPTOCURRENCY': 'crypto',
        'CASH': 'cash',
    }
    return type_mapping.get(snaptrade_type.upper(), 'other')

def consolidate_snaptrade_holdings(holdings_df: pd.DataFrame) -> pd.DataFrame:
    """Consolidate holdings across multiple SnapTrade accounts (STEP 2 of 3 consolidation)"""
    if holdings_df.empty:
        return holdings_df
    
    # Group by ticker and sum quantities/values (SAME AS PLAID consolidate_holdings)
    consolidated = holdings_df.groupby('ticker').agg({
        'quantity': 'sum',
        'value': 'sum', 
        'cost_basis': 'mean',  # Average cost basis across accounts
        'currency': 'first',
        'type': 'first',
        'institution_name': lambda x: ', '.join(x.unique()),
        'last_updated': 'max',
        'position_source': 'first'  # Keep 'snaptrade'
    }).reset_index()
    
    # Create consolidated account_id
    consolidated['account_id'] = f"snaptrade_consolidated"
    
    print(f"✅ Consolidated {len(holdings_df)} holdings into {len(consolidated)} unique positions")
    return consolidated

def convert_snaptrade_holdings_to_portfolio_data(holdings_df: pd.DataFrame, user_email: str, portfolio_name: str):
    """Convert SnapTrade holdings DataFrame to PortfolioData format (MIRROR PLAID PATTERN)"""
    from core.data_objects import PortfolioData
    from datetime import datetime
    
    if holdings_df.empty:
        return PortfolioData(
            user_email=user_email,
            portfolio_name=portfolio_name,
            positions=[],
            metadata={'provider': 'snaptrade', 'last_sync': datetime.now()}
        )
    
    # Create portfolio input dictionary (SAME FORMAT AS PLAID)
    portfolio_input = {}
    
    # Process each SnapTrade holding (MIRROR plaid_loader.py conversion)
    for _, row in holdings_df.iterrows():
        ticker = row.get('ticker', '')
        quantity = row.get('quantity', 0)
        value = row.get('value', 0)
        currency = row.get('currency', 'USD')
        cost_basis = row.get('cost_basis')
        account_id = row.get('account_id')
        position_type = row.get('type', 'equity')
        
        # CRITICAL: Use same field names as Plaid for database compatibility
        portfolio_input[ticker] = {
            'shares': quantity,                    # SAME as Plaid: quantity stored as 'shares'
            'currency': currency,                  # SAME as Plaid: currency field
            'type': position_type,                 # SAME as Plaid: position type
            'cost_basis': cost_basis,              # SAME as Plaid: cost basis
            'account_id': account_id,              # SAME as Plaid: account identifier
            'value': value,                        # SAME as Plaid: market value
            'position_source': 'snaptrade'         # DIFFERENT: SnapTrade vs 'plaid'
        }
    
    # Create PortfolioData object (SAME STRUCTURE AS PLAID)
    portfolio_data = PortfolioData(
        user_email=user_email,
        portfolio_name=portfolio_name,
        positions=list(portfolio_input.values()),
        metadata={
            'provider': 'snaptrade',
            'total_positions': len(portfolio_input),
            'total_value': holdings_df['value'].sum(),
            'last_sync': datetime.now(),
            'accounts_consolidated': len(holdings_df['account_id'].unique()) if 'account_id' in holdings_df.columns else 1
        }
    )
    
    # Set portfolio_input for database saving (CRITICAL FOR DATABASE CLIENT)
    portfolio_data.portfolio_input = portfolio_input
    
    print(f"✅ Converted {len(portfolio_input)} SnapTrade holdings to PortfolioData")
    return portfolio_data

# ═══════════════════════════════════════════════════════════════════════════════
# 🧪 TESTING FUNCTION
# ═══════════════════════════════════════════════════════════════════════════════

def test_snaptrade_connection(region_name: str = "us-east-1") -> bool:
    """Test SnapTrade API connection and credentials"""
    try:
        snaptrade = get_snaptrade_client(region_name)
        status = snaptrade.api_status.check()
        
        if status.body.get('online'):
            print("✅ SnapTrade API connection successful")
            return True
        else:
            print("❌ SnapTrade API is offline")
            return False
            
    except Exception as e:
        print(f"❌ SnapTrade connection test failed: {e}")
        return False
```

**SnapTrade API Endpoints** (verified against documentation):
- `POST /api/v1/snapTrade/registerUser` → register user, get userSecret
- `POST /api/v1/snapTrade/login` → generate connection portal URL  
- `GET /api/v1/accounts` → list user accounts (requires userId + userSecret)
- `GET /api/v1/accounts/{accountId}/holdings` → get account holdings
- `GET /api/v1/activities` → get transaction history (optional for future)

**SnapTrade Internal Consolidation Flow** (mirrors Plaid exactly):
```python
# routes/snaptrade.py - Mirror Plaid pattern exactly
holdings_df = load_all_user_snaptrade_holdings(user_id, region_name)  # Multiple SnapTrade accounts
holdings_df = consolidate_snaptrade_holdings(holdings_df)  # ← STEP 2: Consolidate within SnapTrade
portfolio_data = convert_snaptrade_holdings_to_portfolio_data(holdings_df, user_email, portfolio_name)
# Result: Database gets ONE consolidated position per ticker from SnapTrade
```

**SnapTrade API Authentication Flow**:
```python
# All SnapTrade API calls require userId + userSecret authentication
# userSecret stored in AWS Secrets Manager per user

def _authenticate_snaptrade_request(user_id, region_name):
    user_secret = get_snaptrade_user_secret(user_id, region_name)
    app_credentials = get_snaptrade_app_credentials(region_name)
    
    return {
        'userId': user_id,
        'userSecret': user_secret,
        'clientId': app_credentials['client_id'],
        'consumerKey': app_credentials['consumer_key']
    }
```

**Complete API Integration Flow**:
```python
# SnapTrade Python SDK Integration Flow
from snaptrade_client import SnapTrade

# Initialize client
snaptrade = SnapTrade(
    consumer_key=app_credentials['consumer_key'],
    client_id=app_credentials['client_id']
)

# 1. User Registration (one-time per user)
register_response = snaptrade.authentication.register_snap_trade_user(
    body={"userId": "user123"}
)
user_secret = register_response.body["userSecret"]  # Store in AWS Secrets Manager

# 2. Generate Connection Portal (when user wants to connect account)
redirect_uri = snaptrade.authentication.login_snap_trade_user(
    query_params={"userId": "user123", "userSecret": user_secret}
)
portal_url = redirect_uri.body["redirectURI"]

# 3. List Connected Accounts (after user connects)
accounts = snaptrade.account_information.list_user_accounts(
    user_id="user123",
    user_secret=user_secret
)

# 4. Get Account Positions (for each account)
positions = snaptrade.account_information.get_user_account_positions(
    user_id="user123",
    user_secret=user_secret,
    account_id="acc1"
)
```

**Deliverable**: Working `snaptrade_loader.py` with verified API endpoints and internal consolidation (Step 2 of 3 consolidation steps).

#### **1.2 SnapTrade SDK Setup** (0.5 day)
**Implementation**: Initialize SnapTrade Python SDK client with credentials from AWS Secrets Manager.

```python
def get_snaptrade_client(region_name: str) -> SnapTrade:
    """Initialize SnapTrade SDK client with credentials from AWS Secrets Manager"""
    app_credentials = get_snaptrade_app_credentials(region_name)
    
    return SnapTrade(
        consumer_key=app_credentials['consumer_key'],
        client_id=app_credentials['client_id']
    )
```

**Deliverable**: SnapTrade SDK client initialization working with AWS credentials.

#### **1.3 Data Normalization** (1-2 days)
**Function**: `normalize_snaptrade_holdings()` - convert SnapTrade API response to DataFrame matching Plaid format.

**Key Mappings**:
- SnapTrade position types → standard types (`cash`, `equity`, `etf`)
- Currency handling (match existing multi-currency support)
- Account ID mapping

**Deliverable**: SnapTrade data in same format as Plaid data.

### **Phase 2: Multi-Provider Consolidation** (2-3 days)

#### **2.1 Create Multi-Provider Consolidation** (2 days)
**This is STEP 3 of 3 consolidation steps** - consolidating across providers.

**Current Database State** (after Steps 1 & 2):
```sql
-- Each provider already consolidated internally before database storage
ticker='AAPL', quantity=100, position_source='plaid'     -- Sum of all Plaid accounts
ticker='AAPL', quantity=50,  position_source='snaptrade' -- Sum of all SnapTrade accounts  
ticker='AAPL', quantity=25,  position_source='manual'    -- Manual entry
```

**Problem**: `_apply_cash_mapping()` dictionary overwrites → only gets 25 shares (data loss)
**Solution**: Add multi-provider consolidation before cash mapping.

**Solution**: Add consolidation to `PortfolioManager` that works with positions from **any source** (Plaid, SnapTrade, Manual), with strict currency guards:

```python
# portfolio_manager.py - Add to existing class
def _consolidate_positions(self, positions: list) -> list:
    """
    Consolidate positions across providers with strict guards:
    - Cash: consolidate by canonical ticker 'CUR:<CCY>' (currency defines identity)
    - Non-cash: consolidate by ticker ONLY if currencies match; otherwise do NOT merge
    Always sum quantities; metadata taken from higher-priority provider on ties.
    """
    if not positions:
        return positions

    from utils.logging import portfolio_logger

    consolidated = {}

    for pos in positions:
        ticker = (pos.get("ticker") or "").upper()
        currency = pos.get("currency", "USD")
        ptype = pos.get("type", "equity")

        # Keying strategy
        is_cash = (ptype == "cash") or ticker.startswith("CUR:")
        key = ticker if is_cash else ticker  # cash is already CUR:<CCY>

        if key not in consolidated:
            consolidated[key] = pos.copy()
            continue

        # Guard: for non-cash, only merge if currency matches
        if not is_cash and consolidated[key].get("currency", "USD") != currency:
            portfolio_logger.warning(
                f"mixed_currency_same_ticker: refusing merge for {ticker} — existing {consolidated[key].get('currency')} vs new {currency}")
            # Keep as separate entry by suffixing key to avoid overwrite
            alt_key = f"{ticker}__{currency}"
            if alt_key not in consolidated:
                consolidated[alt_key] = pos.copy()
            else:
                consolidated[alt_key]["quantity"] += pos.get("quantity", 0) or 0
            continue

        # Safe to merge: sum quantities
        consolidated[key]["quantity"] += pos.get("quantity", 0) or 0

        # Provider priority: SnapTrade > Plaid > Manual
        current_priority = self._get_provider_priority(consolidated[key].get("position_source"))
        new_priority = self._get_provider_priority(pos.get("position_source"))
        if new_priority > current_priority:
            consolidated[key].update({
                "account_id": pos.get("account_id"),
                "position_source": pos.get("position_source"),
                "cost_basis": pos.get("cost_basis"),
                "currency": currency,
                "type": ptype,
            })

    return list(consolidated.values())

def _get_provider_priority(self, source: str) -> int:
    """Provider priority for metadata (quantities always summed)"""
    return {"snaptrade": 3, "plaid": 2, "manual": 1}.get(source, 0)

# Update existing function
def _load_portfolio_from_database(self, portfolio_name: str) -> PortfolioData:
    raw_positions = db_client.get_portfolio_positions(self.internal_user_id, portfolio_name)
    filtered_positions = self._filter_positions(raw_positions)
    consolidated_positions = self._consolidate_positions(filtered_positions)  # NEW
    mapped_portfolio_input = self._apply_cash_mapping(consolidated_positions)
    # ... rest unchanged
```

**Result After Step 3**:
```python
# Before consolidation: 3 separate AAPL positions
# After consolidation: 1 AAPL position with 175 shares total
consolidated_positions = [
    {"ticker": "AAPL", "quantity": 175, "position_source": "snaptrade", ...}  # SnapTrade metadata wins
]
```

**Key Benefits**:
- **✅ STEP 3 of 3**: Final consolidation across all providers  
- **✅ Provider priority** (SnapTrade > Plaid > Manual) for metadata
- **✅ Currency guard**: Only merge non-cash when currencies match; otherwise log and keep separate
- **✅ Always sums quantities** (175 shares total, no data loss)
- **✅ Clean integration** with existing `_apply_cash_mapping()`

**Deliverable**: Complete 3-step consolidation system working end-to-end.

#### **2.2 Testing Consolidation Logic** (1 day)
**Test Cases**:
- Same ticker from different providers → quantities summed
- Cash positions from different providers → properly aggregated
- Provider priority for metadata → SnapTrade wins over Plaid
- Single-provider portfolios → unchanged behavior

**Deliverable**: Comprehensive test coverage for consolidation logic.

#### **2.4 Phase 2 Testing** (0.5 day)
**Test Case**: Multi-provider consolidation with test data

**Test Setup**:
```python
# Create test positions in database
test_positions = [
    {"ticker": "AAPL", "quantity": 100, "position_source": "plaid"},
    {"ticker": "AAPL", "quantity": 50, "position_source": "snaptrade"}, 
    {"ticker": "MSFT", "quantity": 75, "position_source": "snaptrade"},
    {"ticker": "CUR:USD", "quantity": 5000, "position_source": "plaid"},
    {"ticker": "CUR:USD", "quantity": 3000, "position_source": "snaptrade"}
]
```

**Test Verification**:
```python
# Run consolidation
portfolio_manager = PortfolioManager(use_database=True, user_id=test_user_id)
consolidated = portfolio_manager._consolidate_positions(test_positions)

# Verify results
assert consolidated["AAPL"]["quantity"] == 150  # 100 + 50
assert consolidated["MSFT"]["quantity"] == 75   # Only SnapTrade
assert consolidated["CUR:USD"]["quantity"] == 8000  # 5000 + 3000
assert consolidated["AAPL"]["position_source"] == "snaptrade"  # Higher priority
```

**Success Criteria**: ✅ Positions consolidated correctly with proper provider priority

### Normalization and Consolidation Contract (Authoritative)

- Cash normalization: cash MUST be represented as `CUR:<CCY>` (e.g., `CUR:USD`, `CUR:EUR`).
- Non-cash normalization: tickers must be uppercase canonical listing symbols; each non-cash ticker MUST be reported in a single currency after normalization.
- Consolidation rules:
  - Cash: consolidate by `CUR:<CCY>` key (currency defines identity).
  - Non-cash: consolidate by ticker ONLY if currencies match; if a currency mismatch occurs for the same ticker, DO NOT MERGE. Emit a `mixed_currency_same_ticker` warning via `portfolio_logger` and keep separate entries.
  - Metadata tie-breaks use provider priority (SnapTrade > Plaid > Manual); quantities are always summed when a merge occurs.

Additional instrument semantics:
- Derivatives: All option-like instruments (options, warrants, rights, futures, swaps, forwards, CFDs) MUST be mapped to `type='derivative'` so shared filtering (`PortfolioManager._filter_positions`) excludes them for analysis.
- Shorts and fractionals: Non-cash `quantity` may be negative (short) and/or fractional; adapters MUST preserve this as `shares=float(quantity)` in the DB path.
- Cash rows: When present from the provider, use `type='cash'` and `ticker='CUR:<CCY>'`. Synthetic cash injection is adapter-specific (Plaid uses balance gap patching); SnapTrade should only inject if the provider omits cash entirely.

Currency semantics (note):
- Store the instrument's listing/native currency as the canonical `currency` field for non‑cash positions. Use this for identity and consolidation.
- Optionally store a separate `valuation_currency` if the provider reports values in account/reporting currency; use it for display/math as needed.
- If only a valuation currency is available, set it as `currency` (temporary stand‑in) and log a warning; treat it as listing until true listing currency is known.

---

## Error Handling and Observability

### Exception Mapping and Retry Policy

Define a deterministic mapping from SDK/API errors to domain exceptions and actions.

- 401/403 → SnapTradeAuthenticationError: do not retry; prompt re-auth/register; alert if repeated.
- 429 → SnapTradeRateLimitError: retry with exponential backoff + jitter; cap attempts; increment `rate_limit_429_total` metric.
- 408/timeouts/connect errors → SnapTradeConnectionError: retry with backoff; circuit-break after N failures.
- 5xx → SnapTradeTransientError: retry with backoff; escalate if persistent.
- Other 4xx → SnapTradeValidationError: do not retry; log payload/schema issue; track occurrences.

Example adapter pattern:
```python
from snaptrade_client import ApiException
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class SnapTradeAPIError(Exception): pass
class SnapTradeAuthenticationError(SnapTradeAPIError): pass
class SnapTradeRateLimitError(SnapTradeAPIError): pass
class SnapTradeConnectionError(SnapTradeAPIError): pass
class SnapTradeTransientError(SnapTradeAPIError): pass
class SnapTradeValidationError(SnapTradeAPIError): pass

def _map_sdk_exception(e: ApiException) -> Exception:
    if e.status in (401, 403):
        return SnapTradeAuthenticationError(str(e))
    if e.status == 429:
        return SnapTradeRateLimitError(str(e))
    if e.status and e.status >= 500:
        return SnapTradeTransientError(str(e))
    return SnapTradeValidationError(str(e))

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((SnapTradeRateLimitError, SnapTradeConnectionError, SnapTradeTransientError)),
    reraise=True,
)
def call_with_retry(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ApiException as e:
        raise _map_sdk_exception(e)
    except (TimeoutError, ConnectionError) as e:
        raise SnapTradeConnectionError(str(e))
```

Retry policy: 3 attempts; exponential backoff with jitter; per-call timeout 30s; no retry for auth/validation.

### Structured Logging (via utils.logging)

Log all provider operations with structured fields. Never log secrets or PII.

- Required fields: `timestamp`, `level`, `user_id`, `provider='snaptrade'`, `event` (e.g., `refresh_holdings`), `endpoint`, `status_code`, `latency_ms`, `request_id`, `portfolio_id`, `account_id`, `retry_count`, `error_class`, `message`.
- Redaction: do not log tokens, user emails, or secrets; use stable IDs and opaque `request_id`.

Example:
```json
{ "level": "info", "provider": "snaptrade", "event": "refresh_holdings", "user_id": 123, "accounts": 2, "positions": 47, "latency_ms": 1820, "request_id": "ab12..." }
```

### Metrics and Alerts (per provider)

- Counters: `api_calls_total`, `api_errors_total{status_class}`, `rate_limit_429_total`, `retries_total`, `webhooks_received_total{event_type}`.
- Timers: `api_latency_ms` (p50/p95), `refresh_holdings_duration_ms`.
- Gauges: `last_success_sync_timestamp`, `accounts_connected`, `positions_loaded`.

Alert examples:
- 429 spike: `rate_limit_429_total` > threshold/min for 5 minutes.
- Error rate: `api_errors_total / api_calls_total` > 5% for 10 minutes.
- Stale sync: `last_success_sync_timestamp` older than 24h for active users.
- Webhook failures: webhook 4xx/5xx above threshold for 10 minutes.

---

## Disconnect Flow (Connection and User Deletion)

### Overview

Provide users with the ability to disconnect a specific SnapTrade connection (brokerage authorization) or delete their SnapTrade user entirely. These actions cleanly remove access, update our database, and reflect the state change in the UI.

Two levels:
- Connection-level disconnect: Removes a single brokerage authorization (accounts + holdings under that authorization). 204 on success.
- User-level deletion: Deletes the SnapTrade user and all associated data at SnapTrade. Asynchronous; 200 means accepted and a `USER_DELETED` webhook will follow.

### SDK Endpoints (from SnapTrade Python SDK README)

- Delete connection (authorization):
  ```python
  snaptrade.connections.remove_brokerage_authorization(
      authorization_id="<authorizationId>",
      user_id="<userId>",
      user_secret="<userSecret>",
  )
  # Endpoint: DELETE /authorizations/{authorizationId} (synchronous; 204)
  ```

- Delete user:
  ```python
  delete_snap_trade_user_response = snaptrade.authentication.delete_snap_trade_user(
      user_id="<userId>",
  )
  # Endpoint: DELETE /snapTrade/deleteUser (async; 200 accepted; USER_DELETED webhook)
  ```

### Backend Routes (FastAPI)

```python
# file: routes/snaptrade.py

@snaptrade_router.delete("/connections/{authorization_id}")
async def disconnect_connection(authorization_id: str, user: dict = Depends(get_current_user)):
    """Disconnect a specific SnapTrade connection (brokerage authorization)."""
    snaptrade = get_snaptrade_client("us-east-1")
    user_secret = get_snaptrade_user_secret(user['user_id'], "us-east-1")

    # 1) Delete the authorization at SnapTrade (synchronous)
    snaptrade.connections.remove_brokerage_authorization(
        authorization_id=authorization_id,
        user_id=str(user['user_id']),
        user_secret=user_secret,
    )

    # 2) Refresh our database state by reloading holdings for provider 'snaptrade'
    #    Using provider-specific re-sync so deleted accounts are removed from DB
    consolidated_df = refresh_all_snaptrade_holdings(user['user_id'])  # helper that normalizes + consolidates
    db_save_positions_by_provider(
        user_id=user['user_id'],
        portfolio_name="CURRENT_PORTFOLIO",
        positions=convert_df_to_positions(consolidated_df),
        provider='snaptrade'
    )

    return {"status": "disconnected", "authorization_id": authorization_id}


@snaptrade_router.delete("/user")
async def delete_snaptrade_user(user: dict = Depends(get_current_user)):
    """Delete the SnapTrade user and all SnapTrade data (irreversible)."""
    snaptrade = get_snaptrade_client("us-east-1")

    # 1) Request deletion at SnapTrade (async accepted)
    resp = snaptrade.authentication.delete_snap_trade_user(user_id=str(user['user_id']))

    # 2) Local cleanup: remove SnapTrade positions and user secret
    with get_db_session() as conn:
        db_client = DatabaseClient(conn)
        portfolio_id = db_client.get_portfolio_id(user['user_id'], "CURRENT_PORTFOLIO")
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM positions WHERE portfolio_id = %s AND position_source = %s",
            (portfolio_id, 'snaptrade')
        )
        conn.commit()

    delete_snaptrade_user_secret(user['user_id'], "us-east-1")  # remove from Secrets Manager

    return {"status": "user_deletion_requested", "accepted": True}
```

Notes:
- The connection-level route performs a provider-specific re-sync after deletion so DB reflects remaining accounts.
- The user-level deletion route drops all SnapTrade positions locally immediately; SnapTrade will later emit a `USER_DELETED` webhook we can log/idempotently ignore.

### Frontend Integration

- Add a “Disconnect” action per SnapTrade connection in Account Connections UI.
  - On click: show confirmation modal.
  - Call `DELETE /api/snaptrade/connections/{authorizationId}`.
  - On success: `refreshConnections()` and `refreshHoldings()` via `useSnapTrade()`.

- Add “Delete SnapTrade User” (danger zone) under account settings.
  - On click: show strong confirmation (irreversible).
  - Call `DELETE /api/snaptrade/user`.
  - On success: clear SnapTrade connections/holdings from UI; surface status message.

### Concurrency, Idempotency, and Observability

- Idempotency: Back-end routes are idempotent at our layer — repeated delete requests after deletion do not error; re-sync produces the same DB state.
- Locking: Frontend disables buttons during requests; React Query dedupes refetches. Optionally add a per-user/provider in-flight guard in the route to avoid overlapping refreshes.
- Logging & Metrics: Log `disconnect_connection` and `delete_user` events with `user_id`, `authorization_id` (if applicable), latency, and outcome. Increment counters `disconnects_total`, `user_deletions_total`.

### Tests

- Unit tests (adapter): Ensure the SDK calls are made with correct params and handle 204/200 responses.
- API tests: Hitting disconnect should remove only the specified authorization’s accounts after re-sync. Hitting delete user should remove all SnapTrade positions.
- UI tests: Disconnect button triggers API, refreshes connections/holdings, and updates the view accordingly.


### **Phase 3: Backend API Integration** (3-4 days)

#### **3.1 Add SnapTrade Routes** (2 days)
**File**: `routes/snaptrade.py` (new file, mirror `routes/plaid.py`)

**Our API → SnapTrade API Integration**:

| Our Endpoint | Purpose | SnapTrade API Called |
|--------------|---------|---------------------|
| `POST /api/snaptrade/register-user` | Register user with SnapTrade | `POST /api/v1/snapTrade/registerUser` |
| `POST /api/snaptrade/create-connection-url` | Get connection portal URL | `POST /api/v1/snapTrade/login` |
| `POST /api/snaptrade/refresh-holdings` | Load all holdings from all accounts | `GET /api/v1/accounts` + `GET /api/v1/accounts/{id}/holdings` |
| `GET /api/snaptrade/accounts` | List connected accounts | `GET /api/v1/accounts` |

**Complete routes/snaptrade.py Implementation**:
```python
#!/usr/bin/env python
# file: routes/snaptrade.py

from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, List
import logging
from datetime import datetime

from snaptrade_loader import (
    get_snaptrade_client,
    register_snaptrade_user,
    generate_connection_portal_url,
    get_snaptrade_user_secret,
    load_all_user_snaptrade_holdings,
    consolidate_snaptrade_holdings,
    convert_snaptrade_holdings_to_portfolio_data,
    normalize_snaptrade_holdings
)
from inputs.portfolio_manager import PortfolioManager
from auth import get_current_user  # Import your auth dependency

router = APIRouter(prefix="/api/snaptrade", tags=["snaptrade"])
logger = logging.getLogger(__name__)

@router.post("/register-user")
async def register_snaptrade_user_endpoint(user: dict = Depends(get_current_user)):
    """Register user with SnapTrade and store user secret"""
    try:
        user_secret = register_snaptrade_user(user['user_id'], "us-east-1")
        
        logger.info(f"✅ Registered SnapTrade user: {user['user_id']}")
        return {
            "status": "registered",
            "userId": user['user_id'],
            "message": "User successfully registered with SnapTrade"
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to register SnapTrade user {user['user_id']}: {e}")
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")

@router.post("/create-connection-url")
async def create_connection_url_endpoint(user: dict = Depends(get_current_user)):
    """Generate SnapTrade connection portal URL"""
    try:
        user_secret = get_snaptrade_user_secret(user['user_id'], "us-east-1")
        portal_url = generate_connection_portal_url(user['user_id'], user_secret, "us-east-1")
        
        logger.info(f"✅ Generated SnapTrade portal URL for user: {user['user_id']}")
        return {
            "portalUrl": portal_url,
            "expiresIn": 300,  # SnapTrade URLs expire in 5 minutes
            "message": "Connection portal URL generated successfully"
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to generate portal URL for {user['user_id']}: {e}")
        raise HTTPException(status_code=500, detail=f"Portal URL generation failed: {str(e)}")

@router.post("/refresh-holdings")
async def refresh_snaptrade_holdings(user: dict = Depends(get_current_user)):
    """Fetch holdings from all SnapTrade accounts and save to database"""
    try:
        # 1. Load holdings from ALL SnapTrade accounts using snaptrade_loader.py
        holdings_df = load_all_user_snaptrade_holdings(user['user_id'], "us-east-1")
        
        if holdings_df.empty:
            return {
                "status": "success",
                "message": "No SnapTrade holdings found",
                "accounts_connected": 0,
                "positions_loaded": 0,
                "total_value": 0
            }
        
        # 2. Consolidate holdings across SnapTrade accounts (STEP 2 of 3 consolidation)
        consolidated_df = consolidate_snaptrade_holdings(holdings_df)
        
        # 3. Convert to portfolio format and save to database
        portfolio_data = convert_snaptrade_holdings_to_portfolio_data(
            consolidated_df,
            user['email'],
            "CURRENT_PORTFOLIO"
        )
        
        # 4. Save to database using provider-specific method (CRITICAL FOR RE-SYNC)
        from database import get_db_session
        from inputs.database_client import DatabaseClient
        
        with get_db_session() as conn:
            db_client = DatabaseClient(conn)
            
            # Get or create portfolio
            portfolio_id = db_client.get_portfolio_id(user['user_id'], "CURRENT_PORTFOLIO")
            if portfolio_id is None:
                db_client.create_portfolio(user['user_id'], "CURRENT_PORTFOLIO", {
                    'start_date': '2020-01-01',
                    'end_date': '2030-12-31'
                })
                portfolio_id = db_client.get_portfolio_id(user['user_id'], "CURRENT_PORTFOLIO")
            
            # CRITICAL: Delete ONLY SnapTrade positions (keep Plaid/Manual intact)
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM positions WHERE portfolio_id = %s AND position_source = %s",
                (portfolio_id, 'snaptrade')
            )
            
            # Insert new SnapTrade positions
            for ticker, position_data in portfolio_data.portfolio_input.items():
                cursor.execute(
                    """
                    INSERT INTO positions 
                    (portfolio_id, user_id, ticker, quantity, currency, type, account_id, cost_basis, position_source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (portfolio_id, user['user_id'], ticker,
                     position_data['shares'], position_data['currency'], position_data['type'],
                     position_data['account_id'], position_data['cost_basis'], 'snaptrade')
                )
            
            conn.commit()
        
        logger.info(f"✅ Refreshed SnapTrade holdings for user: {user['user_id']}")
        return {
            "status": "success",
            "message": "SnapTrade holdings refreshed successfully",
            "positions_loaded": len(consolidated_df),
            "total_value": float(consolidated_df['value'].sum()),
            "last_updated": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to refresh SnapTrade holdings for {user['user_id']}: {e}")
        raise HTTPException(status_code=500, detail=f"Holdings refresh failed: {str(e)}")

@router.get("/accounts")
async def list_snaptrade_accounts(user: dict = Depends(get_current_user)):
    """List all connected SnapTrade accounts"""
    try:
        snaptrade = get_snaptrade_client("us-east-1")
        user_secret = get_snaptrade_user_secret(user['user_id'], "us-east-1")
        
        accounts = snaptrade.account_information.list_user_accounts(
            user_id=user['user_id'],
            user_secret=user_secret
        )
        
        # Format accounts for frontend
        formatted_accounts = []
        for account in accounts.body:
            formatted_accounts.append({
                "id": account['id'],
                "name": account.get('name', 'Unknown Account'),
                "institution_name": account.get('institution_name', 'Unknown'),
                "account_type": account.get('type', 'investment'),
                "provider": "snaptrade",
                "status": "active",
                "capabilities": ["holdings", "transactions"]
            })
        
        logger.info(f"✅ Listed {len(formatted_accounts)} SnapTrade accounts for user: {user['user_id']}")
        return {
            "accounts": formatted_accounts,
            "total_accounts": len(formatted_accounts)
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to list SnapTrade accounts for {user['user_id']}: {e}")
        raise HTTPException(status_code=500, detail=f"Account listing failed: {str(e)}")

@router.post("/webhook")
async def snaptrade_webhook(webhook_data: dict):
    """Handle SnapTrade webhooks (USER_REGISTERED, CONNECTION_DELETED, etc.)"""
    try:
        event_type = webhook_data.get('type')
        user_id = webhook_data.get('userId')
        
        logger.info(f"📨 Received SnapTrade webhook: {event_type} for user: {user_id}")
        
        if event_type == "CONNECTION_DELETED":
            # Handle connection deletion - could trigger data cleanup
            logger.info(f"🗑️ SnapTrade connection deleted for user: {user_id}")
            
        elif event_type == "CONNECTION_BROKEN":
            # Handle broken connection - could trigger user notification
            logger.warning(f"⚠️ SnapTrade connection broken for user: {user_id}")
            
        elif event_type == "CONNECTION_FIXED":
            # Handle fixed connection - could trigger data refresh
            logger.info(f"🔧 SnapTrade connection fixed for user: {user_id}")
            
        elif event_type == "ACCOUNT_HOLDINGS_UPDATED":
            # Handle holdings update - could trigger automatic refresh
            logger.info(f"📊 SnapTrade holdings updated for user: {user_id}")
        
        return {"status": "received", "event_type": event_type}
        
    except Exception as e:
        logger.error(f"❌ Failed to process SnapTrade webhook: {e}")
        raise HTTPException(status_code=500, detail=f"Webhook processing failed: {str(e)}")

# Health check endpoint
@router.get("/health")
async def snaptrade_health_check():
    """Check SnapTrade API connectivity"""
    try:
        snaptrade = get_snaptrade_client("us-east-1")
        status = snaptrade.api_status.check()
        
        if status.body.get('online'):
            return {"status": "healthy", "snaptrade_api": "online"}
        else:
            return {"status": "unhealthy", "snaptrade_api": "offline"}
            
    except Exception as e:
        logger.error(f"❌ SnapTrade health check failed: {e}")
        return {"status": "unhealthy", "error": str(e)}
```
#### **3.2 Configuration & Dependencies** (0.5 day)

**Add to requirements.txt**:
```txt
# SnapTrade Integration
snaptrade-python-sdk==11.0.126
```

**Add to settings.py**:
```python
# SnapTrade Configuration
SNAPTRADE_CLIENT_ID = os.getenv("SNAPTRADE_CLIENT_ID", "")
SNAPTRADE_CONSUMER_KEY = os.getenv("SNAPTRADE_CONSUMER_KEY", "")
SNAPTRADE_BASE_URL = os.getenv("SNAPTRADE_BASE_URL", "https://api.snaptrade.com/api/v1")
SNAPTRADE_ENVIRONMENT = os.getenv("SNAPTRADE_ENVIRONMENT", "production")  # or "sandbox"
ENABLE_SNAPTRADE = os.getenv("ENABLE_SNAPTRADE", "false").lower() == "true"

# SnapTrade Rate Limits
SNAPTRADE_RATE_LIMIT = int(os.getenv("SNAPTRADE_RATE_LIMIT", "250"))  # requests per minute
SNAPTRADE_HOLDINGS_DAILY_LIMIT = int(os.getenv("SNAPTRADE_HOLDINGS_DAILY_LIMIT", "4"))  # per user per day

# SnapTrade Webhook Configuration
SNAPTRADE_WEBHOOK_SECRET = os.getenv("SNAPTRADE_WEBHOOK_SECRET", "")
SNAPTRADE_WEBHOOK_URL = os.getenv("SNAPTRADE_WEBHOOK_URL", "")

# Multi-Provider Configuration
PROVIDER_PRIORITY_CONFIG = {
    # Provider priority for metadata (quantities always summed)
    # Higher number = higher priority for cost_basis, account_id, etc.
    "snaptrade": int(os.getenv("SNAPTRADE_PRIORITY", "3")),  # Highest - real-time brokerage data
    "plaid": int(os.getenv("PLAID_PRIORITY", "2")),          # Medium - aggregated data  
    "manual": int(os.getenv("MANUAL_PRIORITY", "1")),        # Lowest - user input
    "csv_import": int(os.getenv("CSV_IMPORT_PRIORITY", "1")), # Same as manual
    "api": int(os.getenv("API_PRIORITY", "2"))               # Same as plaid
}

# Provider Display Configuration
PROVIDER_DISPLAY_CONFIG = {
    "snaptrade": {
        "name": "SnapTrade",
        "description": "Real-time brokerage connections",
        "color": "blue",
        "icon": "building-2"
    },
    "plaid": {
        "name": "Plaid", 
        "description": "Bank and investment account aggregation",
        "color": "green",
        "icon": "credit-card"
    },
    "manual": {
        "name": "Manual Entry",
        "description": "User-entered positions",
        "color": "gray", 
        "icon": "edit"
    }
}
```

**Environment Variables (.env)**:
```bash
# SnapTrade Configuration
SNAPTRADE_CLIENT_ID=your_client_id_here
SNAPTRADE_CONSUMER_KEY=your_consumer_key_here
SNAPTRADE_ENVIRONMENT=sandbox  # or production
ENABLE_SNAPTRADE=true

# SnapTrade Webhooks (optional)
SNAPTRADE_WEBHOOK_SECRET=your_webhook_secret_here
SNAPTRADE_WEBHOOK_URL=https://yourdomain.com/api/snaptrade/webhook

# Multi-Provider Priority Configuration (optional - defaults provided)
SNAPTRADE_PRIORITY=3    # Highest priority for metadata
PLAID_PRIORITY=2        # Medium priority  
MANUAL_PRIORITY=1       # Lowest priority
CSV_IMPORT_PRIORITY=1   # Same as manual
API_PRIORITY=2          # Same as plaid
```

#### **3.3 Portfolio Manager Consolidation** (1 day)

**Add to inputs/portfolio_manager.py**:
```python
# Add these methods to the existing PortfolioManager class

def _consolidate_positions(self, positions: list) -> list:
    """
    STEP 3 of 3: Consolidate positions by ticker from multiple providers
    Sums quantities, uses provider priority for metadata (SnapTrade > Plaid > Manual)
    """
    if not positions:
        return positions
    
    consolidated = {}
    
    for pos in positions:
        ticker = pos["ticker"]
        
        if ticker not in consolidated:
            # First occurrence of this ticker
            consolidated[ticker] = pos.copy()
        else:
            # Duplicate ticker - sum quantities and use provider priority for metadata
            consolidated[ticker]["quantity"] += pos["quantity"]
            
            # Provider priority: SnapTrade > Plaid > Manual
            current_priority = self._get_provider_priority(consolidated[ticker]["position_source"])
            new_priority = self._get_provider_priority(pos["position_source"])
            
            if new_priority > current_priority:
                # Use higher priority provider's metadata
                consolidated[ticker].update({
                    "account_id": pos["account_id"],
                    "position_source": pos["position_source"],
                    "cost_basis": pos["cost_basis"],
                    "currency": pos["currency"],
                    "type": pos["type"],
                    "last_updated": pos.get("last_updated", datetime.now())
                })
    
    return list(consolidated.values())

def _get_provider_priority(self, source: str) -> int:
    """Provider priority for metadata (quantities always summed)"""
    from settings import PROVIDER_PRIORITY_CONFIG
    return PROVIDER_PRIORITY_CONFIG.get(source, 0)

# CRITICAL: Update existing _load_portfolio_from_database method
def _load_portfolio_from_database(self, portfolio_name: str) -> PortfolioData:
    """Load portfolio from database with multi-provider consolidation"""
    # Get raw positions from database
    raw_positions = self.db_client.get_portfolio_positions(self.internal_user_id, portfolio_name)
    
    # Apply existing filters
    filtered_positions = self._filter_positions(raw_positions)
    
    # NEW: Consolidate positions across providers (STEP 3 of 3)
    consolidated_positions = self._consolidate_positions(filtered_positions)
    
    # Apply existing cash mapping (unchanged)
    mapped_portfolio_input = self._apply_cash_mapping(consolidated_positions)
    
    # Rest of method unchanged
    portfolio_data = PortfolioData(
        user_email=self.user_email,
        portfolio_name=portfolio_name,
        positions=mapped_portfolio_input,
        metadata={
            'source': 'database',
            'consolidation_applied': True,
            'providers_consolidated': list(set([pos['position_source'] for pos in consolidated_positions])),
            'total_positions': len(consolidated_positions),
            'loaded_at': datetime.now().isoformat()
        }
    )
    
    return portfolio_data
```

#### **3.4 AWS Secrets Manager Integration** (0.5 day)

**Add to snaptrade_loader.py** (complete the TODO sections):
```python
def store_snaptrade_app_credentials(client_id: str, consumer_key: str, environment: str, region_name: str) -> None:
    """Store SnapTrade app-level credentials in AWS Secrets Manager"""
    secret_name = f"snaptrade-app-credentials-{environment}"
    secret_value = {
        "client_id": client_id,
        "consumer_key": consumer_key,
        "environment": environment,
        "created_at": datetime.now().isoformat()
    }
    
    secrets_client = boto3.client('secretsmanager', region_name=region_name)
    try:
        secrets_client.create_secret(
            Name=secret_name,
            SecretString=json.dumps(secret_value),
            Description=f"SnapTrade app credentials for {environment} environment"
        )
        print(f"✅ Stored SnapTrade app credentials for {environment}")
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceExistsException':
            secrets_client.update_secret(
                SecretId=secret_name,
                SecretString=json.dumps(secret_value)
            )
            print(f"✅ Updated SnapTrade app credentials for {environment}")
        else:
            raise e

def get_snaptrade_app_credentials(region_name: str) -> Dict[str, str]:
    """Get SnapTrade app-level credentials from AWS Secrets Manager"""
    environment = os.getenv("SNAPTRADE_ENVIRONMENT", "production")
    secret_name = f"snaptrade-app-credentials-{environment}"
    
    secrets_client = boto3.client('secretsmanager', region_name=region_name)
    try:
        response = secrets_client.get_secret_value(SecretId=secret_name)
        return json.loads(response['SecretString'])
    except ClientError as e:
        print(f"❌ Error retrieving SnapTrade app credentials: {e}")
        raise e

def store_snaptrade_user_secret(user_id: str, user_secret: str, region_name: str) -> None:
    """Store SnapTrade user secret in AWS Secrets Manager"""
    secret_name = f"snaptrade-user-{user_id}"
    secret_value = {
        "user_id": user_id,
        "user_secret": user_secret,
        "created_at": datetime.now().isoformat(),
        "provider": "snaptrade"
    }
    
    secrets_client = boto3.client('secretsmanager', region_name=region_name)
    try:
        secrets_client.create_secret(
            Name=secret_name,
            SecretString=json.dumps(secret_value),
            Description=f"SnapTrade user secret for user {user_id}"
        )
        print(f"✅ Stored SnapTrade user secret for {user_id}")
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceExistsException':
            secrets_client.update_secret(
                SecretId=secret_name,
                SecretString=json.dumps(secret_value)
            )
            print(f"✅ Updated SnapTrade user secret for {user_id}")
        else:
            raise e

def get_snaptrade_user_secret(user_id: str, region_name: str) -> str:
    """Get SnapTrade user secret from AWS Secrets Manager"""
    secret_name = f"snaptrade-user-{user_id}"
    
    secrets_client = boto3.client('secretsmanager', region_name=region_name)
    try:
        response = secrets_client.get_secret_value(SecretId=secret_name)
        secret_data = json.loads(response['SecretString'])
        return secret_data['user_secret']
    except ClientError as e:
        print(f"❌ Error retrieving SnapTrade user secret for {user_id}: {e}")
        raise e


async def refresh_snaptrade_holdings(user: dict = Depends(get_current_user)):
    """Fetch holdings from all SnapTrade accounts and save to database"""
    
    # 1. Initialize SnapTrade SDK client
    snaptrade = get_snaptrade_client("us-east-1")
    user_secret = get_snaptrade_user_secret(user['user_id'], "us-east-1")
    
    # 2. Get all user accounts using SDK
    accounts = snaptrade.account_information.list_user_accounts(
        user_id=user['user_id'],
        user_secret=user_secret
    )
    
    # 3. Get positions for each account using SDK
    all_positions = []
    for account in accounts.body:
        positions = snaptrade.account_information.get_user_account_positions(
            user_id=user['user_id'],
            user_secret=user_secret,
            account_id=account['id']
        )
        
        # Add account metadata to each position
        for position in positions.body:
            position['account_id'] = account['id']
            position['institution'] = account['institution_name']
        
        all_positions.extend(positions.body)
    
    # 4. Process using snaptrade_loader.py functions
    holdings_df = normalize_snaptrade_holdings(all_positions)
    consolidated_df = consolidate_snaptrade_holdings(holdings_df)
    
    # 5. Convert to portfolio format and save to database
    portfolio_data = convert_snaptrade_holdings_to_portfolio_data(
        consolidated_df,
        user['email'],
        "CURRENT_PORTFOLIO"
    )
    
    portfolio_manager = PortfolioManager(use_database=True, user_id=user['user_id'])
    portfolio_manager.save_portfolio_data(portfolio_data)
    
    return {
        "status": "success",
        "accounts_connected": len(accounts.body),
        "positions_loaded": len(consolidated_df),
        "total_value": consolidated_df['value'].sum()
    }
```
```

**Key Integration Points**:
- **✅ AWS Secrets Manager**: Secure credential storage per user
- **✅ Multi-Account Support**: Fetches from all connected SnapTrade accounts
- **✅ Internal Consolidation**: Step 2 consolidation within SnapTrade
- **✅ Database Integration**: Saves with `position_source='snaptrade'`
- **✅ Error Handling**: Proper HTTP status codes and error messages
```
#### **3.5 Database Re-sync & Field Mapping** (CRITICAL)

**Problem**: Database `save_portfolio()` does **DELETE + INSERT** which wipes ALL positions, not just the provider being refreshed.

**CRITICAL**: This affects **BOTH Plaid AND SnapTrade** - any refresh wipes all other providers' data!

**Current Database Behavior**:
```python
# database_client.py line 1023
cursor.execute("DELETE FROM positions WHERE portfolio_id = %s", (portfolio_id,))
# ☠️ This deletes ALL positions (Plaid + SnapTrade + Manual)
```

**Solution**: Modify database operations for provider-specific re-sync:

**Option A: Provider-Specific Delete (RECOMMENDED)**:
```python
# In routes/snaptrade.py - refresh-holdings endpoint
def refresh_snaptrade_holdings(user: dict = Depends(get_current_user)):
    # ... get SnapTrade data ...
    
    # CRITICAL: Only delete SnapTrade positions, keep Plaid/Manual
    with db_session.get_db_session() as conn:
        db_client = DatabaseClient(conn)
        
        # Get portfolio ID
        portfolio_id = db_client.get_portfolio_id(user['user_id'], "CURRENT_PORTFOLIO")
        
        # Delete ONLY SnapTrade positions (not all positions)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM positions WHERE portfolio_id = %s AND position_source = %s",
            (portfolio_id, 'snaptrade')
        )
        
        # Insert new SnapTrade positions
        for ticker, position_data in portfolio_input.items():
            cursor.execute(
                """
                INSERT INTO positions 
                (portfolio_id, user_id, ticker, quantity, currency, type, account_id, cost_basis, position_source)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (portfolio_id, user['user_id'], ticker, 
                 position_data['shares'], position_data['currency'], position_data['type'],
                 position_data['account_id'], position_data['cost_basis'], 'snaptrade')
            )
        
        conn.commit()
```

**Option B: Add provider-specific save method to DatabaseClient**:
```python
# Add to database_client.py
def save_positions_by_provider(self, user_id: int, portfolio_name: str, positions: Dict, provider: str):
    """Save positions for specific provider, keeping other providers intact"""
    with self.get_connection() as conn:
        cursor = conn.cursor()
        
        try:
            conn.autocommit = False
            
            # Get portfolio ID
            portfolio_id = self.get_portfolio_id(user_id, portfolio_name)
            
            # Delete only positions from this provider
            cursor.execute(
                "DELETE FROM positions WHERE portfolio_id = %s AND position_source = %s",
                (portfolio_id, provider)
            )
            
            # Insert new positions for this provider
            for ticker, position_data in positions.items():
                cursor.execute(
                    """
                    INSERT INTO positions 
                    (portfolio_id, user_id, ticker, quantity, currency, type, account_id, cost_basis, position_source)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (portfolio_id, user_id, ticker,
                     position_data.get('shares', 0), position_data.get('currency', 'USD'),
                     position_data.get('type', 'equity'), position_data.get('account_id'),
                     position_data.get('cost_basis'), provider)
                )
            
            conn.commit()
            logger.info(f"Saved {len(positions)} {provider} positions for user {user_id}")
            
        except Exception as e:
            conn.rollback()
            raise TransactionError(f"Failed to save {provider} positions", original_error=e)
        finally:
            conn.autocommit = True
```

**Field Mapping Verification**:
```python
# SnapTrade → Database Field Mapping (MUST MATCH PLAID)
snaptrade_position = {
    'shares': 100,           # → positions.quantity
    'currency': 'USD',       # → positions.currency  
    'type': 'equity',        # → positions.type
    'cost_basis': 150.50,    # → positions.cost_basis
    'account_id': 'acc123',  # → positions.account_id
    'position_source': 'snaptrade'  # → positions.position_source
}

# Database INSERT uses these exact field names:
# quantity = position_data.get('shares') or position_data.get('dollars') or position_data.get('quantity', 0)
```

**BOTH Plaid AND SnapTrade Need Provider-Specific Database Operations**:

**Current Broken Flow**:
- ❌ Plaid refresh → `portfolio_manager.save_portfolio_data()` → **DELETES ALL POSITIONS**
- ❌ SnapTrade refresh → `portfolio_manager.save_portfolio_data()` → **DELETES ALL POSITIONS**

**Fixed Re-sync Flow**:
1. **Plaid refresh** → Delete `position_source='plaid'` → Insert new Plaid positions
2. **SnapTrade refresh** → Delete `position_source='snaptrade'` → Insert new SnapTrade positions  
3. **Manual entry** → Delete `position_source='manual'` → Insert manual positions
4. **Multi-provider consolidation** → Happens in `PortfolioManager._consolidate_positions()`

**Required Changes**:

**1. Fix routes/plaid.py (CRITICAL - Currently Broken)**:
```python
# BEFORE (BROKEN) - routes/plaid.py lines 645 & 1770:
portfolio_manager.save_portfolio_data(portfolio_data)  # ☠️ Deletes ALL positions

# AFTER (FIXED) - Replace with provider-specific operations:
from database import get_db_session
from inputs.database_client import DatabaseClient

with get_db_session() as conn:
    db_client = DatabaseClient(conn)
    
    # Get or create portfolio
    portfolio_id = db_client.get_portfolio_id(user['user_id'], "CURRENT_PORTFOLIO")
    if portfolio_id is None:
        db_client.create_portfolio(user['user_id'], "CURRENT_PORTFOLIO", {
            'start_date': '2020-01-01',
            'end_date': '2030-12-31'
        })
        portfolio_id = db_client.get_portfolio_id(user['user_id'], "CURRENT_PORTFOLIO")
    
    # CRITICAL: Delete ONLY Plaid positions (keep SnapTrade/Manual intact)
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM positions WHERE portfolio_id = %s AND position_source = %s",
        (portfolio_id, 'plaid')
    )
    
    # Insert new Plaid positions
    for ticker, position_data in portfolio_data.portfolio_input.items():
        cursor.execute(
            """
            INSERT INTO positions 
            (portfolio_id, user_id, ticker, quantity, currency, type, account_id, cost_basis, position_source)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (portfolio_id, user['user_id'], ticker,
             position_data['shares'], position_data['currency'], position_data['type'],
             position_data['account_id'], position_data['cost_basis'], 'plaid')
        )
    
    conn.commit()
```

**2. Update routes/snaptrade.py** - Use provider-specific database operations (already done above)

**3. Add DatabaseClient.save_positions_by_provider()** method for reusability (Option B above)

#### **3.6 Provider Priority Configuration Management** (0.5 day)

**Dynamic Configuration API** (optional for runtime changes):
```python
# Add to routes/admin.py or routes/config.py
@router.get("/api/admin/provider-priority")
async def get_provider_priority_config(user: dict = Depends(get_admin_user)):
    """Get current provider priority configuration"""
    from settings import PROVIDER_PRIORITY_CONFIG, PROVIDER_DISPLAY_CONFIG
    
    return {
        "priority_config": PROVIDER_PRIORITY_CONFIG,
        "display_config": PROVIDER_DISPLAY_CONFIG,
        "description": "Higher numbers = higher priority for metadata (cost_basis, account_id, etc.)"
    }

@router.post("/api/admin/provider-priority")
async def update_provider_priority_config(
    config: dict,
    user: dict = Depends(get_admin_user)
):
    """Update provider priority configuration (runtime changes)"""
    import settings
    
    # Validate config
    for provider, priority in config.items():
        if not isinstance(priority, int) or priority < 0:
            raise HTTPException(status_code=400, detail=f"Invalid priority for {provider}: {priority}")
    
    # Update runtime configuration
    settings.PROVIDER_PRIORITY_CONFIG.update(config)
    
    logger.info(f"Updated provider priority config: {config}")
    return {
        "status": "updated",
        "new_config": settings.PROVIDER_PRIORITY_CONFIG
    }
```

**Configuration Examples**:
```bash
# Example 1: Default (SnapTrade highest priority)
SNAPTRADE_PRIORITY=3
PLAID_PRIORITY=2  
MANUAL_PRIORITY=1

# Example 2: Plaid-first organization
PLAID_PRIORITY=3
SNAPTRADE_PRIORITY=2
MANUAL_PRIORITY=1

# Example 3: Manual override priority
MANUAL_PRIORITY=5      # Highest - trust user input most
SNAPTRADE_PRIORITY=3
PLAID_PRIORITY=2

# Example 4: All equal (first-come-first-served)
SNAPTRADE_PRIORITY=1
PLAID_PRIORITY=1
MANUAL_PRIORITY=1
```

**Configuration Validation**:
```python
# Add to settings.py
def validate_provider_priority_config():
    """Validate provider priority configuration on startup"""
    required_providers = ['snaptrade', 'plaid', 'manual']
    
    for provider in required_providers:
        if provider not in PROVIDER_PRIORITY_CONFIG:
            logger.warning(f"Missing provider priority config for: {provider}")
            PROVIDER_PRIORITY_CONFIG[provider] = 1  # Default priority
        
        priority = PROVIDER_PRIORITY_CONFIG[provider]
        if not isinstance(priority, int) or priority < 0:
            logger.error(f"Invalid priority for {provider}: {priority}")
            PROVIDER_PRIORITY_CONFIG[provider] = 1  # Safe default
    
    logger.info(f"Provider priority config validated: {PROVIDER_PRIORITY_CONFIG}")

# Call on app startup
validate_provider_priority_config()
```

**Frontend Configuration UI** (optional):
```typescript
// Admin settings component
const ProviderPrioritySettings: React.FC = () => {
  const [config, setConfig] = useState<Record<string, number>>({});
  
  const updatePriority = async (provider: string, priority: number) => {
    await api.post('/api/admin/provider-priority', {
      [provider]: priority
    });
    // Refresh config
  };
  
  return (
    <div className="provider-priority-settings">
      <h3>Provider Priority Configuration</h3>
      <p>Higher numbers = higher priority for metadata (cost basis, account ID, etc.)</p>
      
      {Object.entries(config).map(([provider, priority]) => (
        <div key={provider} className="provider-setting">
          <label>{provider.toUpperCase()}</label>
          <input
            type="number"
            min="0"
            max="10"
            value={priority}
            onChange={(e) => updatePriority(provider, parseInt(e.target.value))}
          />
        </div>
      ))}
    </div>
  );
};
```

**Deliverable**: Complete SnapTrade API integration with secure credential management, provider-specific database re-sync, and field mapping compatibility.

#### **3.4 Phase 3 Testing** (0.5 day)
**Test Case**: End-to-end SnapTrade API integration with your Schwab account

**Test Setup**:
1. **SnapTrade App Credentials**: Store in AWS Secrets Manager
2. **Test User**: Your account (new test user ID)
3. **Target Institution**: Schwab via SnapTrade

**Test Steps**:
```bash
# 1. Test user registration
curl -X POST http://localhost:5001/snaptrade/register-user \
  -H "Cookie: session_id=your_session" \
  -d '{}'

# Expected: {"status": "registered", "userId": "your_user_id"}

# 2. Test connection portal creation
curl -X POST http://localhost:5001/snaptrade/create-connection-url \
  -H "Cookie: session_id=your_session" \
  -d '{}'

# Expected: {"portalUrl": "https://...", "expiresIn": 300}

# 3. Manual connection test
# Open portalUrl → Connect your Schwab account → Portal closes

# 4. Test holdings refresh
curl -X POST http://localhost:5001/snaptrade/refresh-holdings \
  -H "Cookie: session_id=your_session" \
  -d '{}'

# Expected: {"status": "success", "accounts_connected": 1, "positions_loaded": X}
```

**Database Verification**:
```sql
-- Check positions were saved with correct source
SELECT ticker, quantity, position_source, account_id 
FROM positions 
WHERE user_id = your_user_id AND position_source = 'snaptrade';

-- Should show your Schwab holdings with position_source='snaptrade'
```

**Success Criteria**: 
- ✅ User registered successfully
- ✅ Portal URL generated 
- ✅ Schwab account connected via portal
- ✅ Holdings retrieved and saved to database
- ✅ Positions have `position_source='snaptrade'`

#### **3.2 Database Integration** (1-2 days)
**Integration Point**: Use existing `DatabaseClient.save_portfolio()` with `position_source='snaptrade'`.

**Function**: Create `convert_snaptrade_holdings_to_portfolio_data()` mirroring Plaid version.

**Database State After Integration**:
```sql
-- positions table after SnapTrade refresh
INSERT INTO positions (
    ticker, quantity, currency, type, account_id, 
    position_source, user_id, portfolio_id
) VALUES 
-- SnapTrade positions (consolidated within SnapTrade)
('AAPL', 50, 'USD', 'equity', 'fidelity_401k', 'snaptrade', 123, 456),
('MSFT', 75, 'USD', 'equity', 'schwab_ira', 'snaptrade', 123, 456),
('CUR:USD', 3000, 'USD', 'cash', 'fidelity_401k', 'snaptrade', 123, 456),

-- Existing Plaid positions (consolidated within Plaid)
('AAPL', 100, 'USD', 'equity', 'chase_checking', 'plaid', 123, 456),
('MSFT', 200, 'USD', 'equity', 'vanguard_401k', 'plaid', 123, 456),
('CUR:USD', 5000, 'USD', 'cash', 'chase_checking', 'plaid', 123, 456),

-- Manual positions
('AAPL', 25, 'USD', 'equity', 'manual_entry', 'manual', 123, 456);
```

**Portfolio Analysis Integration**:
```python
# When user runs risk analysis
# 1. PortfolioManager loads all positions
raw_positions = db_client.get_portfolio_positions(user_id, "CURRENT_PORTFOLIO")
# Returns: 7 positions (3 SnapTrade + 3 Plaid + 1 Manual)

# 2. Multi-provider consolidation (Step 3)
consolidated_positions = self._consolidate_positions(raw_positions)
# Result: 3 positions (AAPL: 175 total, MSFT: 275 total, Cash: $8000 total)

# 3. Risk analysis proceeds normally
mapped_portfolio = self._apply_cash_mapping(consolidated_positions)
# Result: Unified portfolio ready for risk analysis
```

**Complete Data Flow Summary**:
```
Frontend → Our API → SnapTrade API → Database → PortfolioManager → Risk Analysis

1. User connects Fidelity via SnapTrade portal
2. Our API fetches holdings from all SnapTrade accounts  
3. Internal consolidation (Step 2) within SnapTrade
4. Save to database with position_source='snaptrade'
5. PortfolioManager consolidates across providers (Step 3)
6. Risk analysis runs on unified portfolio
```

**Requirements Update**:
```
# Add to requirements.txt
snaptrade-python-sdk==11.0.126
```

**Deliverable**: Complete end-to-end SnapTrade SDK integration from user registration to risk analysis.

### **Frontend Architecture Analysis**

**Current Plaid Flow**:
```
usePlaid() → useConnectAccount() → PlaidLinkButton → Popup → API calls → Database
```

**SnapTrade Flow (With React SDK)**:
```
useSnapTrade() → useConnectSnapTrade() → SnapTradeReact Modal → API calls → Database
```

**Key Findings**:
- Institution selection UI already exists and supports provider routing
- **SnapTrade React SDK** provides modal instead of popup (better UX)
- Same React Query caching strategy (session-long)
- Same service layer architecture (APIService → SnapTradeService)
- **No polling needed** - React SDK handles connection events

**Required Frontend Changes**:
1. `useSnapTrade()` hook (mirrors `usePlaid()`)
2. `useConnectSnapTrade()` hook (simplified with React SDK)
3. `SnapTradeService` class (mirrors `PlaidService`)
4. Provider routing in `handleConnectAccount()`
5. **NEW**: SnapTrade React SDK integration for connection modal

**Frontend Dependencies**:
```json
// package.json additions
{
  "snaptrade-react": "^3.2.4"
}
```

### **Phase 4: Frontend Integration** (4-5 days)

#### **4.1 Frontend Dependencies** (0.5 day)

**Add to frontend/package.json**:
```json
{
  "dependencies": {
    "snaptrade-react": "^1.0.0"
  }
}
```

**Install command**:
```bash
cd frontend && npm install snaptrade-react
```

#### **4.2 Dynamic Provider Routing** (1 day)

**Backend Institution Support API**:
```python
# snaptrade_loader.py - Add institution support checking
from functools import lru_cache
from datetime import datetime, timedelta

@lru_cache(maxsize=1)
def get_supported_institutions():
    """Get list of SnapTrade-supported institutions (cached for 24h)"""
    snaptrade = get_snaptrade_client(region_name)
    try:
        brokerages = snaptrade.reference_data.list_all_brokerages()
        supported = []
        for brokerage in brokerages:
            supported.append({
                'slug': brokerage.slug,
                'name': brokerage.display_name,
                'id': brokerage.id
            })
        logger.info(f"Retrieved {len(supported)} SnapTrade-supported institutions")
        return supported
    except Exception as e:
        logger.error(f"Failed to get SnapTrade institutions: {e}")
        return []

def is_institution_supported_by_snaptrade(institution_slug: str) -> bool:
    """Check if institution is supported by SnapTrade"""
    supported = get_supported_institutions()
    return institution_slug.lower() in [inst['slug'].lower() for inst in supported]

def clear_institution_cache():
    """Clear cached institution data (for testing/admin)"""
    get_supported_institutions.cache_clear()
```

**Provider Routing API Routes**:
```python
# routes/provider_routing.py (new file)
from fastapi import APIRouter, HTTPException
from snaptrade_loader import is_institution_supported_by_snaptrade, get_supported_institutions

router = APIRouter(prefix="/api/provider-routing", tags=["provider-routing"])

@router.get("/institution-support/{institution_slug}")
async def check_institution_support(institution_slug: str):
    """Check which providers support an institution - SnapTrade first, Plaid fallback"""
    snaptrade_supported = is_institution_supported_by_snaptrade(institution_slug)
    
    return {
        "institution": institution_slug,
        "snaptrade_supported": snaptrade_supported,
        "plaid_supported": True,  # Assume Plaid supports most institutions
        "recommended_provider": "snaptrade" if snaptrade_supported else "plaid"
    }

@router.get("/supported-institutions")
async def get_all_supported_institutions():
    """Get all institutions supported by SnapTrade (dynamic from API)"""
    snaptrade_institutions = get_supported_institutions()
    
    return {
        "snaptrade": snaptrade_institutions,
        "total_snaptrade": len(snaptrade_institutions),
        "last_updated": datetime.now().isoformat()
    }

@router.post("/admin/clear-institution-cache")
async def clear_institution_cache_endpoint():
    """Clear institution cache (admin only)"""
    from snaptrade_loader import clear_institution_cache
    clear_institution_cache()
    return {"status": "cache_cleared", "timestamp": datetime.now().isoformat()}
```

**Frontend Provider Routing Service**:
```typescript
// frontend/src/chassis/services/ProviderRoutingService.ts (new file)
export class ProviderRoutingService {
  private static baseUrl = '/api/provider-routing';
  
  static async checkInstitutionSupport(institutionSlug: string) {
    const response = await fetch(`${this.baseUrl}/institution-support/${institutionSlug}`);
    if (!response.ok) throw new Error('Failed to check institution support');
    return await response.json();
  }
  
  static async getSupportedInstitutions() {
    const response = await fetch(`${this.baseUrl}/supported-institutions`);
    if (!response.ok) throw new Error('Failed to get supported institutions');
    return await response.json();
  }
  
  static async routeConnection(institutionSlug: string): Promise<{provider: string, data?: any}> {
    try {
      // Check which provider to use (SnapTrade first, Plaid fallback)
      const support = await this.checkInstitutionSupport(institutionSlug);
      
      if (support.snaptrade_supported) {
        // Use SnapTrade
        console.log(`Routing ${institutionSlug} to SnapTrade`);
        return { provider: 'snaptrade' };
      } else {
        // Fallback to Plaid
        console.log(`Routing ${institutionSlug} to Plaid (SnapTrade not supported)`);
        return { provider: 'plaid' };
      }
    } catch (error) {
      console.error('Provider routing failed:', error);
      // Default fallback to Plaid
      return { provider: 'plaid' };
    }
  }
}
```

**Enhanced useConnectAccount Hook with Dynamic Routing**:
```typescript
// frontend/src/features/external/hooks/useConnectAccount.ts - Updated
import { ProviderRoutingService } from '../../../chassis/services/ProviderRoutingService';

export const useConnectAccount = () => {
  const [isConnecting, setIsConnecting] = useState(false);
  const snapTradeConnect = useConnectSnapTrade();
  const plaidConnect = usePlaid();
  
  const connectAccount = useCallback(async (institutionSlug: string) => {
    setIsConnecting(true);
    
    try {
      // Dynamic provider routing - SnapTrade first, Plaid fallback
      const routing = await ProviderRoutingService.routeConnection(institutionSlug);
      
      if (routing.provider === 'snaptrade') {
        return await snapTradeConnect.connectAccount(institutionSlug);
      } else {
        return await plaidConnect.connectAccount(institutionSlug);
      }
    } catch (error) {
      console.error(`Failed to connect ${institutionSlug}:`, error);
      throw error;
    } finally {
      setIsConnecting(false);
    }
  }, [snapTradeConnect, plaidConnect]);
  
  return { connectAccount, isConnecting };
};
```

#### **4.3 SnapTrade Service Layer** (1 day)

**Create frontend/src/chassis/services/SnapTradeService.ts** (mirror PlaidService):
```typescript
// file: frontend/src/chassis/services/SnapTradeService.ts

import { APIService } from './APIService';

export interface SnapTradeAccount {
  id: string;
  name: string;
  institution_name: string;
  account_type: string;
  provider: 'snaptrade';
  status: 'active' | 'inactive' | 'error';
  capabilities: string[];
}

export interface SnapTradeConnectionResponse {
  portalUrl: string;
  expiresIn: number;
  message: string;
}

export interface SnapTradeHoldingsResponse {
  status: string;
  message: string;
  positions_loaded: number;
  total_value: number;
  last_updated: string;
}

export class SnapTradeService {
  private apiService: APIService;

  constructor(apiService: APIService) {
    this.apiService = apiService;
  }

  /**
   * Register user with SnapTrade
   */
  async registerUser(): Promise<{ status: string; userId: string; message: string }> {
    return this.apiService.post('/api/snaptrade/register-user', {});
  }

  /**
   * Create SnapTrade connection portal URL
   */
  async createConnectionUrl(): Promise<SnapTradeConnectionResponse> {
    return this.apiService.post('/api/snaptrade/create-connection-url', {});
  }

  /**
   * Refresh holdings from all SnapTrade accounts
   */
  async refreshHoldings(): Promise<SnapTradeHoldingsResponse> {
    return this.apiService.post('/api/snaptrade/refresh-holdings', {});
  }

  /**
   * List all connected SnapTrade accounts
   */
  async listAccounts(): Promise<{ accounts: SnapTradeAccount[]; total_accounts: number }> {
    return this.apiService.get('/api/snaptrade/accounts');
  }

  /**
   * Check SnapTrade API health
   */
  async healthCheck(): Promise<{ status: string; snaptrade_api: string }> {
    return this.apiService.get('/api/snaptrade/health');
  }
}

// Export singleton instance
export const snapTradeService = new SnapTradeService(new APIService());
```

#### **4.3 SnapTrade Hook Layer** (1.5 days)

**Create frontend/src/features/external/hooks/useSnapTrade.ts** (mirror usePlaid):
```typescript
export const useSnapTrade = () => {
  const { api } = useSessionServices()
  const { user } = useAuthStore()
  
  // Get SnapTrade connections - SESSION-LONG CACHE (same as Plaid)
  const {
    data: connections,
    isLoading: connectionsLoading,
    refetch: refetchConnections,
  } = useQuery({
    queryKey: snaptradeConnectionsKey(user?.id),
    queryFn: async () => {
      const response = await api.getSnapTradeConnections()
      return response.connections ?? []
    },
    enabled: !!user && !!api,
    staleTime: Infinity, // SESSION-LONG: Same as Plaid
    gcTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
  
  // Get SnapTrade holdings - SESSION-LONG CACHE (same as Plaid)
  const {
    data: holdings,
    isLoading: holdingsLoading,
    refetch: refetchHoldings,
  } = useQuery({
    queryKey: snaptradeHoldingsKey(user?.id),
    queryFn: async () => api.getSnapTradeHoldings(),
    enabled: !!user && !!api && (connections?.length ?? 0) > 0,
    staleTime: Infinity,
    gcTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })

  return {
    connections, holdings, 
    loading: connectionsLoading || holdingsLoading,
    refreshConnections: refetchConnections,
    refreshHoldings: refetchHoldings,
    hasConnections: (connections?.length ?? 0) > 0,
  }
}
```

**Deliverable**: SnapTrade data management hook following existing Plaid patterns.

#### **4.1.5 SnapTrade Connection Detection** (0.5 day) 
**✅ NO POLLING NEEDED**: SnapTrade portal auto-closes on completion

**Simplified Connection Flow**:
```typescript
// useConnectSnapTrade.ts - SIMPLIFIED (no polling)
export const useConnectSnapTrade = () => {
  const connectAccount = useCallback(async (institution) => {
    try {
      // 1. Register user with SnapTrade
      await api.registerSnapTradeUser()
      
      // 2. Create connection portal URL
      const { portalUrl } = await api.createSnapTradeConnectionUrl()
      
      // 3. Open SnapTrade portal
      const popup = window.open(portalUrl, 'snaptrade-connect', 'width=500,height=600')
      
      // 4. Simple popup monitoring (no API polling)
      return await monitorPopupClosure(popup)
      
    } catch (error) {
      return { success: false, error: error.message }
    }
  }, [])

  // Simple popup monitoring (no polling)
  const monitorPopupClosure = async (popup) => {
    return new Promise((resolve) => {
      const checkClosed = () => {
        if (popup.closed) {
          // Portal closed - connection likely complete
          // Refresh connections to get latest state
          setTimeout(async () => {
            await refreshConnections()
            resolve({ success: true, hasNewConnection: true })
          }, 2000) // Brief delay for backend sync
        }
      }
      
      const interval = setInterval(checkClosed, 1000)
      
      // Cleanup after 10 minutes
      setTimeout(() => {
        clearInterval(interval)
        if (!popup.closed) popup.close()
        resolve({ success: false, hasNewConnection: false })
      }, 600000)
    })
  }

  return { connectAccount }
}
```

**Key Difference from Plaid**:
- **No API polling** - SnapTrade portal handles completion
- **Simple popup monitoring** - Just detect when popup closes
- **Webhooks handle real-time updates** - No need for connection status polling

**Deliverable**: Simplified SnapTrade connection flow without polling infrastructure.

#### **4.2 SnapTrade Connection Hook** (1 day)
**File**: `frontend/src/features/auth/hooks/useConnectSnapTrade.ts` (NEW)

**Mirror `useConnectAccount()` Architecture**:
```typescript
export const useConnectSnapTrade = () => {
  const [state, setState] = useState<ConnectAccountState>({
    isConnecting: false,
    error: null,
  })

  const { refreshConnections, connections } = useSnapTrade()
  const queryClient = useQueryClient()

  const connectAccount = useCallback(async (institution) => {
    try {
      setState(prev => ({ ...prev, isConnecting: true }))
      const initialConnectionCount = connections?.length || 0
      
      // Step 1: Register user with SnapTrade
      await api.registerSnapTradeUser()
      
      // Step 2: Create connection portal URL  
      const { portalUrl } = await api.createSnapTradeConnectionUrl()
      
      // Step 3: Open SnapTrade portal (same popup pattern as Plaid)
      const popup = window.open(
        portalUrl, 
        'snaptrade-connect', 
        'width=500,height=600,scrollbars=yes,resizable=yes'
      )
      
      if (!popup) {
        throw new Error('Failed to open SnapTrade portal. Check popup blocker.')
      }
      
      // Step 4: Monitor popup closure (same pattern as Plaid)
      return await monitorPopupClosure(popup, initialConnectionCount)
      
    } catch (error) {
      setState(prev => ({ ...prev, isConnecting: false, error: error.message }))
      return { success: false, hasNewConnection: false, error }
    }
  }, [connections, api])

  // Same popup monitoring logic as Plaid
  const monitorPopupClosure = async (popup, initialConnectionCount) => {
    return new Promise((resolve) => {
      const checkClosed = () => {
        if (popup.closed) {
          setTimeout(async () => {
            await refreshConnections()
            const finalConnectionCount = connections?.length || 0
            const hasNewConnection = finalConnectionCount > initialConnectionCount
            
            if (hasNewConnection) {
              // Trigger portfolio refresh (same as Plaid)
              await IntentRegistry.triggerIntent('refresh-holdings', {
                source: 'snaptrade-connection-success'
              })
              
              // Invalidate React Query caches (same as Plaid)
              await queryClient.invalidateQueries({ queryKey: portfolioSummaryKey() })
              
              resolve({ success: true, hasNewConnection: true })
            } else {
              resolve({ success: false, hasNewConnection: false })
            }
          }, 3000) // Same 3 second delay as Plaid
        }
      }
      
      const interval = setInterval(checkClosed, 1000)
      checkClosed()
    })
  }

  return { state, connectAccount }
}
```

**Deliverable**: SnapTrade connection flow following existing Plaid popup management patterns.

#### **4.2.5 SnapTrade React SDK Component Implementation** (1 day)

**Complete React SDK Integration with Frontend Architecture**:

**Install SnapTrade React SDK**:
```bash
cd frontend && npm install snaptrade-react@^1.0.0
```

#### **A. Core React SDK Component** (`frontend/src/components/snaptrade/SnapTradeLaunchButton.tsx`)

```typescript
// file: frontend/src/components/snaptrade/SnapTradeLaunchButton.tsx
import React, { useState, useCallback } from 'react';
import { SnapTradeLaunch } from 'snaptrade-react';
import { useSnapTrade } from '../../features/external/hooks/useSnapTrade';
import { useSessionServices } from '../../providers/SessionServicesProvider';
import { frontendLogger } from '../../services/frontendLogger';
import { IntentRegistry } from '../../utils/NavigationIntents';
import { useQueryClient } from '@tanstack/react-query';
import { portfolioSummaryKey } from '../../queryKeys';

interface SnapTradeLaunchButtonProps {
  institution: {
    id: string;
    name: string;
    slug: string;
  };
  onSuccess?: (result: any) => void;
  onError?: (error: any) => void;
  className?: string;
  disabled?: boolean;
}

export const SnapTradeLaunchButton: React.FC<SnapTradeLaunchButtonProps> = ({
  institution,
  onSuccess,
  onError,
  className = "bg-green-600 hover:bg-green-700 text-white font-bold py-3 px-6 rounded-lg disabled:opacity-50 flex items-center gap-2",
  disabled = false
}) => {
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const { refreshConnections, connections } = useSnapTrade();
  const { api } = useSessionServices();
  const queryClient = useQueryClient();

  // Get SnapTrade credentials for React SDK
  const [snapTradeConfig, setSnapTradeConfig] = useState<{
    clientId: string;
    userId: string;
    userSecret: string;
  } | null>(null);

  // Initialize SnapTrade connection
  const initializeConnection = useCallback(async () => {
    try {
      setIsConnecting(true);
      setConnectionError(null);

      frontendLogger.user.action('snapTrade-connection-initiated', 'SnapTradeLaunchButton', {
        institutionId: institution.id,
        institutionName: institution.name
      });

      // Step 1: Register user with SnapTrade (gets userSecret)
      const registerResponse = await api.registerSnapTradeUser();
      
      // Step 2: Get clientId from backend
      const configResponse = await api.getSnapTradeConfig();

      // Step 3: Set up React SDK configuration
      setSnapTradeConfig({
        clientId: configResponse.clientId,
        userId: registerResponse.userId,
        userSecret: registerResponse.userSecret
      });

      return true;
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      setConnectionError(`Failed to initialize SnapTrade connection: ${errorMessage}`);
      
      frontendLogger.error('SnapTrade initialization failed', 'SnapTradeLaunchButton', error as Error);
      
      onError?.(error);
      return false;
    } finally {
      setIsConnecting(false);
    }
  }, [institution, api, onError]);

  // Handle successful connection
  const handleConnectionSuccess = useCallback(async (data: any) => {
    try {
      frontendLogger.user.action('snapTrade-connection-success', 'SnapTradeLaunchButton', {
        institutionId: institution.id,
        institutionName: institution.name,
        accountsConnected: data.accounts?.length || 0
      });

      // Refresh SnapTrade connections
      await refreshConnections();

      // Trigger portfolio refresh via intent system
      await IntentRegistry.triggerIntent('refresh-holdings', {
        source: 'snaptrade-connection-success',
        institution: institution.name
      });

      // Invalidate React Query caches for immediate UI updates
      await queryClient.invalidateQueries({ queryKey: portfolioSummaryKey() });

      // Brief delay for backend sync
      setTimeout(() => {
        onSuccess?.(data);
      }, 2000);

    } catch (error) {
      frontendLogger.error('SnapTrade post-connection processing failed', 'SnapTradeLaunchButton', error as Error);
      onError?.(error);
    }
  }, [institution, refreshConnections, queryClient, onSuccess, onError]);

  // Handle connection error
  const handleConnectionError = useCallback((error: any) => {
    const errorMessage = error.message || 'Connection failed';
    setConnectionError(errorMessage);
    
    frontendLogger.user.error('snapTrade-connection-failed', 'SnapTradeLaunchButton', {
      institutionId: institution.id,
      institutionName: institution.name,
      error: errorMessage
    });
    
    onError?.(error);
  }, [institution, onError]);

  // Render loading state
  if (isConnecting) {
    return (
      <button disabled className={className}>
        <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
        Initializing {institution.name} connection...
      </button>
    );
  }

  // Render error state
  if (connectionError) {
    return (
      <div className="text-red-600 text-sm">
        <p>{connectionError}</p>
        <button 
          onClick={() => {
            setConnectionError(null);
            initializeConnection();
          }}
          className="text-blue-600 hover:text-blue-800 underline mt-1"
        >
          Retry
        </button>
      </div>
    );
  }

  // Render SnapTrade React SDK component
  if (snapTradeConfig) {
    return (
      <SnapTradeLaunch
        config={snapTradeConfig}
        onSuccess={handleConnectionSuccess}
        onError={handleConnectionError}
        className={className}
      >
        <div className="flex items-center gap-2">
          <div className="w-5 h-5 bg-green-500 rounded-full flex items-center justify-center">
            <span className="text-white text-xs font-bold">ST</span>
          </div>
          Connect {institution.name}
        </div>
      </SnapTradeLaunch>
    );
  }

  // Render initialization button
  return (
    <button
      onClick={initializeConnection}
      disabled={disabled}
      className={className}
    >
      <div className="flex items-center gap-2">
        <div className="w-5 h-5 bg-green-500 rounded-full flex items-center justify-center">
          <span className="text-white text-xs font-bold">ST</span>
        </div>
        Connect {institution.name}
      </div>
    </button>
  );
};

export default SnapTradeLaunchButton;
```

#### **B. SnapTrade Configuration Service** (`frontend/src/chassis/services/SnapTradeConfigService.ts`)

```typescript
// file: frontend/src/chassis/services/SnapTradeConfigService.ts
export interface SnapTradeConfig {
  clientId: string;
  environment: 'sandbox' | 'production';
  isEnabled: boolean;
}

export interface SnapTradeUserRegistration {
  userId: string;
  userSecret: string;
  message: string;
}

export class SnapTradeConfigService {
  private apiService: any;

  constructor(apiService: any) {
    this.apiService = apiService;
  }

  /**
   * Get SnapTrade public configuration (clientId, environment)
   */
  async getConfig(): Promise<SnapTradeConfig> {
    return this.apiService.get('/api/snaptrade/config');
  }

  /**
   * Register user with SnapTrade and get userSecret
   */
  async registerUser(): Promise<SnapTradeUserRegistration> {
    return this.apiService.post('/api/snaptrade/register-user', {});
  }

  /**
   * Check if SnapTrade is available and configured
   */
  async healthCheck(): Promise<{ status: string; available: boolean }> {
    return this.apiService.get('/api/snaptrade/health');
  }
}
```

#### **C. Enhanced useConnectSnapTrade Hook** (`frontend/src/features/auth/hooks/useConnectSnapTrade.ts`)

```typescript
// file: frontend/src/features/auth/hooks/useConnectSnapTrade.ts
import { useState, useCallback } from 'react';
import { useSnapTrade } from '../../external/hooks/useSnapTrade';
import { useSessionServices } from '../../../providers/SessionServicesProvider';
import { frontendLogger } from '../../../services/frontendLogger';

export interface SnapTradeConnectionState {
  isConnecting: boolean;
  isInitializing: boolean;
  error: string | null;
  config: {
    clientId: string;
    userId: string;
    userSecret: string;
  } | null;
}

export const useConnectSnapTrade = () => {
  const [state, setState] = useState<SnapTradeConnectionState>({
    isConnecting: false,
    isInitializing: false,
    error: null,
    config: null
  });

  const { refreshConnections } = useSnapTrade();
  const { api } = useSessionServices();

  const initializeSnapTrade = useCallback(async (institution: { id: string; name: string }) => {
    setState(prev => ({ ...prev, isInitializing: true, error: null }));

    try {
      frontendLogger.user.action('snapTrade-initialization', 'useConnectSnapTrade', {
        institutionId: institution.id,
        institutionName: institution.name
      });

      // Get SnapTrade configuration
      const configResponse = await api.getSnapTradeConfig();
      
      // Register user and get userSecret
      const userResponse = await api.registerSnapTradeUser();

      const config = {
        clientId: configResponse.clientId,
        userId: userResponse.userId,
        userSecret: userResponse.userSecret
      };

      setState(prev => ({ 
        ...prev, 
        config, 
        isInitializing: false,
        error: null
      }));

      return { success: true, config };

    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Initialization failed';
      
      setState(prev => ({ 
        ...prev, 
        isInitializing: false,
        error: errorMessage,
        config: null
      }));

      frontendLogger.error('SnapTrade initialization failed', 'useConnectSnapTrade', error as Error);
      
      return { success: false, error: errorMessage };
    }
  }, [api]);

  const handleConnectionSuccess = useCallback(async (data: any, institution: { name: string }) => {
    setState(prev => ({ ...prev, isConnecting: false }));

    try {
      // Refresh connections to get updated state
      await refreshConnections();

      frontendLogger.user.action('snapTrade-connection-completed', 'useConnectSnapTrade', {
        institutionName: institution.name,
        accountsConnected: data.accounts?.length || 0
      });

      return { success: true, data };
    } catch (error) {
      frontendLogger.error('SnapTrade post-connection processing failed', 'useConnectSnapTrade', error as Error);
      return { success: false, error };
    }
  }, [refreshConnections]);

  const clearState = useCallback(() => {
    setState({
      isConnecting: false,
      isInitializing: false,
      error: null,
      config: null
    });
  }, []);

  return {
    state,
    initializeSnapTrade,
    handleConnectionSuccess,
    clearState
  };
};
```

#### **D. Updated Component Export** (`frontend/src/components/snaptrade/index.ts`)

```typescript
// file: frontend/src/components/snaptrade/index.ts
export { default as SnapTradeLaunchButton } from './SnapTradeLaunchButton';
export { default as ConnectedSnapTradeAccounts } from './ConnectedSnapTradeAccounts';

// Export React SDK wrapper for consistent usage
export { SnapTradeLaunchButton as SnapTradeReactButton };

// Types
export type { SnapTradeLaunchButtonProps } from './SnapTradeLaunchButton';
```

#### **E. Backend Configuration Endpoint** (add to existing routes)

```python
# Add to routes/snaptrade.py
@router.get("/config")
async def get_snaptrade_config():
    """Get SnapTrade public configuration for React SDK"""
    return {
        "clientId": settings.SNAPTRADE_CONFIG['client_id'],
        "environment": settings.SNAPTRADE_CONFIG['environment'],
        "isEnabled": True
    }
```

#### **F. Integration with Account Connections UI**

```typescript
// Update AccountConnections.tsx to use SnapTrade React SDK
import { SnapTradeLaunchButton } from '../snaptrade';

// In provider routing logic:
if (institution.preferredProvider === 'snaptrade') {
  return (
    <SnapTradeLaunchButton
      institution={institution}
      onSuccess={(data) => {
        showSuccessNotification(`Successfully connected ${institution.name}`);
        onSuccess?.(data);
      }}
      onError={(error) => {
        showErrorNotification(`Failed to connect ${institution.name}: ${error.message}`);
      }}
    />
  );
}
```

**Deliverable**: Complete SnapTrade React SDK integration with frontend architecture, providing native modal experience instead of popup handling.

#### **4.3 SnapTrade Service Layer** (1 day)
**File**: `frontend/src/chassis/services/SnapTradeService.ts` (NEW)

**Mirror `PlaidService` Architecture**:
```typescript
export class SnapTradeService {
  constructor(private options: SnapTradeServiceOptions) {}

  async getConnections(): Promise<SnapTradeConnectionApiResponse> {
    return this.options.request('/snaptrade/connections')
  }

  async registerUser(): Promise<{ status: string, userId: string }> {
    return this.options.request('/snaptrade/register-user', { method: 'POST' })
  }

  async createConnectionUrl(): Promise<{ portalUrl: string, expiresIn: number }> {
    return this.options.request('/snaptrade/create-connection-url', { method: 'POST' })
  }

  async getHoldings(): Promise<HoldingsApiResponse> {
    return this.options.request('/snaptrade/refresh-holdings', { method: 'POST' })
  }
}
```

**Update `APIService.ts`**:
```typescript
// Add SnapTrade service initialization
this.snaptradeService = new SnapTradeService({
  baseURL: this.baseURL,
  request: this.request.bind(this)
})

// Add SnapTrade methods
async getSnapTradeConnections() {
  return this.snaptradeService.getConnections()
}

async registerSnapTradeUser() {
  return this.snaptradeService.registerUser()
}

async createSnapTradeConnectionUrl() {
  return this.snaptradeService.createConnectionUrl()
}

async getSnapTradeHoldings() {
  return this.snaptradeService.getHoldings()
}
```

#### **4.4 Institution Selection UI** (1 day)
**Files**: `AccountConnections.tsx`, `AccountConnectionsContainer.tsx`

**Current Flow Change**:
```typescript
// BEFORE: Direct Plaid Link
"Add Account" → Plaid Link popup

// AFTER: Institution selection → Provider routing  
"Add Account" → Institution Selection Modal → SnapTrade/Plaid routing
```

**Update `AccountConnections.tsx`**:
```typescript
// Add state for institution selection modal
const [showInstitutionSelector, setShowInstitutionSelector] = useState(false);

// Update "Add Account" button to show institution selector
<Button onClick={() => setShowInstitutionSelector(true)}>
  <Plus className="w-4 h-4 mr-2" />
  Add Account
</Button>

// Add Institution Selection Modal
{showInstitutionSelector && (
  <InstitutionSelectorModal
    institutions={availableProviders}
    onSelect={handleInstitutionSelect}
    onClose={() => setShowInstitutionSelector(false)}
  />
)}
```

**Update `getAvailableProviders()`**:
```typescript
const getAvailableProviders = () => [
  // SnapTrade institutions (geographic filtering handled by SnapTrade API)
  { id: "fidelity", name: "Fidelity", preferredProvider: "snaptrade", type: "brokerage", logo: "🟢", popular: true },
  { id: "schwab", name: "Charles Schwab", preferredProvider: "snaptrade", type: "brokerage", logo: "🔵", popular: true },
  { id: "etrade", name: "E*TRADE", preferredProvider: "snaptrade", type: "brokerage", logo: "🟡", popular: true },
  { id: "td_ameritrade", name: "TD Ameritrade", preferredProvider: "snaptrade", type: "brokerage", logo: "🟠", popular: false },
  { id: "interactive_brokers", name: "Interactive Brokers", preferredProvider: "snaptrade", type: "brokerage", logo: "🔴", popular: false },
  { id: "robinhood", name: "Robinhood", preferredProvider: "snaptrade", type: "brokerage", logo: "🟢", popular: true },
  
  // Plaid institutions (banking focus)
  { id: "chase", name: "Chase", preferredProvider: "plaid", type: "bank", logo: "🔷", popular: true },
  { id: "bofa", name: "Bank of America", preferredProvider: "plaid", type: "bank", logo: "🔴", popular: true },
  { id: "wells_fargo", name: "Wells Fargo", preferredProvider: "plaid", type: "bank", logo: "🟡", popular: true },
  
  // Dual-support institutions (fallback logic)
  { id: "vanguard", name: "Vanguard", preferredProvider: "snaptrade", fallbackProvider: "plaid", type: "brokerage", logo: "🔴", popular: true },
]
```

**🌍 Geographic Handling Strategy**: 
1. **SnapTrade handles geographic filtering automatically** - users only see available institutions in their region
2. **Our frontend shows all institutions** - SnapTrade portal will filter appropriately  
3. **Fallback logic**: If SnapTrade connection fails, try Plaid for dual-support institutions
4. **No location detection needed** - SnapTrade API handles this server-side

**Add Institution Selection Modal Component**:
```typescript
// New component: InstitutionSelectorModal.tsx
const InstitutionSelectorModal = ({ institutions, onSelect, onClose }) => (
  <Modal isOpen onClose={onClose} title="Select Your Financial Institution">
    <div className="institution-grid">
      {institutions
        .filter(inst => inst.popular) // Show popular first
        .map(institution => (
          <InstitutionCard
            key={institution.id}
            institution={institution}
            onClick={() => onSelect(institution)}
          />
        ))}
    </div>
    
    <Collapsible title="More Institutions">
      <div className="institution-grid">
        {institutions
          .filter(inst => !inst.popular)
          .map(institution => (
            <InstitutionCard
              key={institution.id}
              institution={institution}
              onClick={() => onSelect(institution)}
            />
          ))}
      </div>
    </Collapsible>
  </Modal>
);
```

**Update `handleInstitutionSelect()` in Container**:
```typescript
const handleInstitutionSelect = async (institution) => {
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState('');

  frontendLogger.user.action('connectAccount', 'AccountConnectionsContainer', {
    institutionId: institution.id,
    preferredProvider: institution.preferredProvider,
    hasExistingConnections: !!hasConnections
  });

  setIsConnecting(true);
  setConnectionStatus(`Connecting to ${institution.name}...`);

  try {
    if (institution.preferredProvider === 'snaptrade') {
      // 🚀 SnapTrade connection flow
      setConnectionStatus(`Opening ${institution.name} via SnapTrade...`);
      const result = await connectSnapTradeAccount(institution);
      
      if (!result.success && institution.fallbackProvider === 'plaid') {
        // 🔄 Fallback to Plaid with user notification
        setConnectionStatus(`${institution.name} not available via SnapTrade. Trying Plaid...`);
        
        frontendLogger.user.action('providerFallback', 'AccountConnectionsContainer', {
          institutionId: institution.id,
          fromProvider: 'snaptrade',
          toProvider: 'plaid',
          error: result.error
        });
        
        // Show brief notification to user about fallback
        showNotification({
          type: 'info',
          message: `${institution.name} not available via SnapTrade in your region. Trying alternative connection...`,
          duration: 3000
        });
        
        const fallbackResult = await connectAccount(); // Existing Plaid flow
        setIsConnecting(false);
        return fallbackResult;
      }
      
      setIsConnecting(false);
      return result;
    } else {
      // 🏦 Plaid connection flow (existing)
      setConnectionStatus(`Opening ${institution.name} via Plaid...`);
      const result = await connectAccount();
      setIsConnecting(false);
      return result;
    }
  } catch (error) {
    setIsConnecting(false);
    setConnectionStatus('');
    
    frontendLogger.user.error('connectionFailed', 'AccountConnectionsContainer', {
      institutionId: institution.id,
      provider: institution.preferredProvider,
      error: error.message
    });
    throw error;
  }
};
```

**🎯 Key Geographic Handling Points**:

1. **User clicks "Fidelity"** → Routes to SnapTrade
2. **SnapTrade portal opens** → Automatically shows only Fidelity if available in user's region
3. **If Fidelity not available** → SnapTrade portal shows "Institution not supported in your region"
4. **User sees clear feedback** → No confusing empty lists or broken connections

**🔄 Fallback Strategy**:
- Some institutions (like Vanguard) support both SnapTrade and Plaid
- If SnapTrade connection fails → automatically try Plaid
- User gets seamless experience regardless of geographic availability

**🎨 UI Components for Fallback**:

```typescript
// Connection Status Component
const ConnectionStatus = ({ isConnecting, status, institution }) => {
  if (!isConnecting) return null;
  
  return (
    <div className="connection-status">
      <div className="spinner" />
      <div className="status-text">
        {status || `Connecting to ${institution.name}...`}
      </div>
      {status.includes('Trying Plaid') && (
        <div className="fallback-notice">
          <InfoIcon />
          <span>Using alternative connection method</span>
        </div>
      )}
    </div>
  );
};

// Institution Card with Provider Badges
const InstitutionCard = ({ institution, onConnect }) => (
  <div className="institution-card" onClick={() => onConnect(institution)}>
    <div className="institution-info">
      <span className="logo">{institution.logo}</span>
      <span className="name">{institution.name}</span>
    </div>
    
    <div className="provider-badges">
      <span className={`badge primary ${institution.preferredProvider}`}>
        {institution.preferredProvider === 'snaptrade' ? 'Trading' : 'Banking'}
      </span>
      {institution.fallbackProvider && (
        <span className={`badge fallback ${institution.fallbackProvider}`}>
          + Backup
        </span>
      )}
    </div>
  </div>
);
```

**📱 User Experience Flow**:

1. **Initial Click**: User sees "Connecting to Vanguard..." with spinner
2. **SnapTrade Attempt**: Status updates to "Opening Vanguard via SnapTrade..."
3. **Geographic Failure**: SnapTrade popup shows "Not available in your region"
4. **User Closes Popup**: Frontend detects failure automatically
5. **Fallback Notification**: Toast shows "Vanguard not available via SnapTrade in your region. Trying alternative connection..."
6. **Status Update**: "Vanguard not available via SnapTrade. Trying Plaid..."
7. **Plaid Success**: Plaid popup opens with Vanguard available
8. **Completion**: "Successfully connected to Vanguard via Plaid"
  }
}
```
```
#### **4.3.5 SnapTrade Manager Class** (0.5 day)
**File**: `frontend/src/chassis/managers/SnapTradeManager.ts` (NEW)

**Mirror `PlaidManager` Architecture**:
```typescript
// SnapTradeManager.ts - Mirror PlaidManager
export class SnapTradeManager {
  private apiService: APIService
  private snaptradePolling: SnapTradePollingService

  constructor(apiService: APIService) {
    this.apiService = apiService
  }

  /**
   * Initialize SnapTrade manager with state setters
   */
  public initialize(
    setConnections: (connections: any[]) => void,
    setPortfolio: (portfolio: any) => void
  ): void {
    // Initialize SnapTrade manager state
  }

  /**
   * Create SnapTrade connection flow
   */
  public async createConnection(institution: any): Promise<{ 
    success: boolean; 
    portalUrl?: string; 
    connectionId?: string;
    error?: string 
  }> {
    try {
      // 1. Register user with SnapTrade
      await this.apiService.registerSnapTradeUser()
      
      // 2. Create connection portal URL
      const { portalUrl } = await this.apiService.createSnapTradeConnectionUrl()
      
      return { success: true, portalUrl, connectionId: `st_${Date.now()}` }
    } catch (error) {
      return { success: false, error: error.message }
    }
  }

  /**
   * Load SnapTrade portfolio holdings
   */
  public async loadSnapTradePortfolio(): Promise<{ 
    portfolio: any; 
    error: string | null 
  }> {
    try {
      const response = await this.apiService.getSnapTradeHoldings()
      return { portfolio: response.holdings, error: null }
    } catch (error) {
      return { portfolio: null, error: error.message }
    }
  }

  /**
   * Refresh all SnapTrade accounts and portfolio data
   */
  public async refreshAccountsAndPortfolio(): Promise<{ 
    success: boolean; 
    error: string | null 
  }> {
    try {
      await this.apiService.getSnapTradeHoldings() // Triggers refresh + save
      return { success: true, error: null }
    } catch (error) {
      return { success: false, error: error.message }
    }
  }
}
```

#### **4.4.5 Remove Unnecessary Polling Endpoint**
**✅ NOT NEEDED**: No polling required for SnapTrade connection detection

**Reason**: SnapTrade portal auto-closes on completion, eliminating need for:
- Connection status polling endpoint
- Rate-limited polling infrastructure  
- Complex polling state management

**Instead**: Use existing `/snaptrade/connections` endpoint for post-connection refresh only.

**Deliverable**: Complete frontend integration following existing Plaid architecture patterns with all supporting infrastructure.

#### **4.5 Phase 4 Testing** (0.5 day)
**Test Case**: End-to-end frontend SnapTrade integration with your Schwab account

**Test Setup**:
1. **Frontend Environment**: Local development server running
2. **Backend**: SnapTrade routes deployed and tested (Phase 3)
3. **Test Account**: Your user account
4. **Target**: Connect Schwab via SnapTrade in UI

**Manual UI Testing Steps**:

**Step 1: Provider Routing Test**
```typescript
// Navigate to Account Connections page
// Verify Schwab shows with SnapTrade badge/logo
// Verify "Connect Schwab" button routes to SnapTrade (not Plaid)
```

**Step 2: Connection Flow Test**
```typescript
// Click "Connect Schwab" 
// ✅ useConnectSnapTrade() hook triggered
// ✅ SnapTrade portal opens in popup
// ✅ Connect your actual Schwab account
// ✅ Portal closes automatically
// ✅ UI shows "Connected" status
// ✅ Account appears in connected accounts list
```

**Step 3: Data Integration Test**
```typescript
// Navigate to Holdings/Portfolio view
// ✅ Schwab holdings appear in portfolio
// ✅ Holdings show SnapTrade provider badge
// ✅ Risk analysis works with SnapTrade data
// ✅ Multi-provider consolidation works (if you have Plaid accounts too)
```

**Frontend Console Verification**:
```javascript
// Check browser console for:
// ✅ No polling-related errors (since we removed polling)
// ✅ Successful API calls to /snaptrade/* endpoints
// ✅ React Query cache updates properly
// ✅ No rate limit warnings
```

**Success Criteria**:
- ✅ Schwab appears with SnapTrade routing
- ✅ Connection flow completes successfully  
- ✅ Your Schwab holdings appear in UI
- ✅ Provider badges show correctly
- ✅ Portfolio analysis includes SnapTrade data
- ✅ No console errors or warnings

### **Phase 5: Production Features** (2-3 days)

#### **5.1 Error Handling** (1 day)
**Implementation**: SnapTrade-specific exception classes and retry logic mirroring Plaid patterns.

**Required Error Handling**:
```python
# SnapTrade-specific exceptions
class SnapTradeAPIError(Exception): pass
class SnapTradeRateLimitError(Exception): pass  
class SnapTradeAuthenticationError(Exception): pass
class SnapTradeConnectionError(Exception): pass

# Retry logic for rate limits (429 errors)
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
    retry=retry_if_exception_type(SnapTradeRateLimitError)
)
def snaptrade_api_call_with_retry():
    # API call implementation
    pass
```

**Error Scenarios to Handle**:
- Rate limit exceeded (429) → Exponential backoff
- Authentication failures → Re-register user
- Connection timeouts → Retry with circuit breaker
- Invalid user secrets → Refresh credentials
- Malformed API responses → Data validation errors

#### **5.1.5 SnapTrade Webhook Support** (1 day)
**✅ CONFIRMED**: SnapTrade supports webhooks for real-time updates
**Events**: `USER_REGISTERED`, `CONNECTION_DELETED`, `CONNECTION_BROKEN`, `CONNECTION_FIXED`

**Implementation**: Add `/snaptrade/webhook` endpoint:
```python
@snaptrade_router.post("/webhook")
async def snaptrade_webhook(webhook_data: dict):
    """
    Handle SnapTrade webhook events
    
    Events:
    - USER_REGISTERED: User completed registration
    - CONNECTION_DELETED: User deleted a connection
    - CONNECTION_BROKEN: Connection needs re-authentication  
    - CONNECTION_FIXED: Connection restored
    """
    try:
        event_type = webhook_data.get('eventType')
        user_id = webhook_data.get('userId')
        webhook_secret = webhook_data.get('webhookSecret')
        
        # Verify webhook authenticity using webhookSecret
        if not verify_webhook_secret(webhook_secret):
            raise HTTPException(status_code=401, detail="Invalid webhook secret")
        
        if event_type == 'CONNECTION_DELETED':
            # Handle connection deletion
            pass
        elif event_type == 'CONNECTION_BROKEN':
            # Notify user of broken connection
            pass
        elif event_type == 'CONNECTION_FIXED':
            # Connection restored - refresh holdings
            pass
            
        return {"status": "success"}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

**Benefits**: 
- Real-time connection status updates
- Reduces need for polling
- Better user experience

#### **5.2 Monitoring & Logging** (1 day)
**Implementation**: `SnapTradeMonitor` class for API call tracking, latency, success rates.

#### **5.3 Security & Testing** (1 day)
**Security**: Rate limiting, data sanitization, credential rotation.
**Testing**: Integration tests, end-to-end tests.

#### **5.4 Phase 5 Testing** (0.5 day)
**Test Case**: Production readiness and multi-provider portfolio analysis

**Final Integration Test with Your Schwab Account**:

**Step 1: Multi-Provider Portfolio Test**
```python
# Assuming you have both Plaid and SnapTrade accounts connected
# Run complete portfolio analysis

portfolio_manager = PortfolioManager(use_database=True, user_id=your_user_id)
portfolio_data = portfolio_manager._load_portfolio_from_database("CURRENT_PORTFOLIO")

# Verify consolidation worked
print("Consolidated Portfolio:")
for position in portfolio_data.positions:
    print(f"{position.ticker}: {position.quantity} shares")
    
# Should show combined positions from both providers
```

**Step 2: Risk Analysis Test**
```bash
# Run risk analysis on consolidated portfolio
curl -X POST http://localhost:5001/api/risk-score \
  -H "Cookie: session_id=your_session" \
  -d '{"portfolio_name": "CURRENT_PORTFOLIO"}'

# Should return risk analysis including both Plaid + SnapTrade positions
```

**Step 3: Webhook Test** (if implemented)
```python
# Simulate SnapTrade webhook
curl -X POST http://localhost:5001/snaptrade/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "eventType": "CONNECTION_FIXED",
    "userId": "your_user_id",
    "webhookSecret": "test_secret"
  }'

# Should handle webhook without errors
```

**Step 4: Rate Limit Compliance Test**
```python
# Test rate limiting compliance
# Make multiple API calls and verify we respect limits
import time

for i in range(5):
    response = requests.get("/snaptrade/connections")
    print(f"Rate limit remaining: {response.headers.get('X-RateLimit-Remaining')}")
    time.sleep(1)  # Ensure we don't exceed 250/minute
```

**Final Success Criteria**:
- ✅ Your Schwab account connected via SnapTrade
- ✅ Holdings appear in database with `position_source='snaptrade'`
- ✅ Multi-provider consolidation works correctly
- ✅ Risk analysis includes SnapTrade positions
- ✅ No rate limit violations
- ✅ Webhooks handle events properly
- ✅ Error handling works for edge cases
- ✅ UI shows provider badges correctly
- ✅ Portfolio analysis produces accurate results

---

## 📊 **Implementation Timeline**

| Phase | Duration | Parallel Work | Dependencies |
|-------|----------|---------------|--------------|
| **Phase 1** | 5-6 days | Can start immediately | None |
| **Phase 2** | 2-3 days | Can start immediately | None |
| **Phase 3** | 3-4 days | After Phase 1 complete | Phase 1 |
| **Phase 4** | 3-4 days | Can start after Phase 1 | Phase 1 |
| **Phase 5** | 2-3 days | After all core phases | Phases 1-4 |

**Total: 15-18 days** with parallel work streams.

---

## 🎯 **Success Criteria**

### **Functional Requirements**
- [ ] Users can connect Fidelity/Schwab accounts via SnapTrade
- [ ] Positions from both Plaid and SnapTrade appear in portfolio analysis
- [ ] Multi-provider positions properly consolidated (no data loss)
- [ ] Risk analysis works identically regardless of data source
- [ ] Cash positions from both providers use same proxy mapping

### **Technical Requirements**
- [ ] Zero changes to risk analysis engine
- [ ] Clean separation of concerns (consolidation vs cash mapping)
- [ ] Comprehensive error handling and monitoring
- [ ] Full test coverage for multi-provider scenarios
- [ ] Production-ready security and performance

### **User Experience**
- [ ] Seamless institution selection (user doesn't care about provider)
- [ ] Clear provider indicators in account management
- [ ] Consistent performance across providers

---

## 🚨 **Critical Success Factors**

1. **Follow Existing Patterns**: Mirror `plaid_loader.py` exactly - proven architecture
2. **Clean Architecture**: Separate consolidation logic from cash mapping
3. **No Risk Engine Changes**: Existing analysis engine must work unchanged
4. **Comprehensive Testing**: Multi-provider scenarios thoroughly tested
5. **Provider Agnostic UX**: Users shouldn't need to understand provider differences

---

## 🔧 **Development Environment Setup**

### **Prerequisites**
- SnapTrade API credentials (client_id, consumer_key)
- AWS Secrets Manager access
- Test accounts with supported institutions

### **Configuration Management**
**Environment Variables Needed**:
```bash
# SnapTrade API Configuration
SNAPTRADE_CLIENT_ID=your_client_id
SNAPTRADE_CONSUMER_KEY=your_consumer_key
SNAPTRADE_BASE_URL=https://api.snaptrade.com/api/v1
SNAPTRADE_ENVIRONMENT=sandbox  # or production

# AWS Configuration (existing)
AWS_REGION=us-east-1
AWS_SECRETS_MANAGER_ENABLED=true

# Rate Limiting
SNAPTRADE_RATE_LIMIT=250  # requests per minute
SNAPTRADE_HOLDINGS_DAILY_LIMIT=4  # per user per day
```

**Settings Integration**:
```python
# Add to settings.py
SNAPTRADE_CONFIG = {
    'client_id': os.getenv('SNAPTRADE_CLIENT_ID'),
    'consumer_key': os.getenv('SNAPTRADE_CONSUMER_KEY'),
    'base_url': os.getenv('SNAPTRADE_BASE_URL', 'https://api.snaptrade.com/api/v1'),
    'environment': os.getenv('SNAPTRADE_ENVIRONMENT', 'sandbox'),
    'rate_limit': int(os.getenv('SNAPTRADE_RATE_LIMIT', '250')),
    'holdings_daily_limit': int(os.getenv('SNAPTRADE_HOLDINGS_DAILY_LIMIT', '4'))
}
```

### **Testing Strategy**
1. **Unit Tests**: Individual functions (consolidation, normalization)
2. **Integration Tests**: Full data flow (SnapTrade → Database → Analysis)
3. **End-to-End Tests**: User connection flow through UI
4. **Multi-Provider Tests**: Positions from both Plaid and SnapTrade

---

## 📋 **Implementation Checklist**

### **Phase 1: Core Integration**
- [ ] `snaptrade_loader.py` created with all core functions
- [ ] AWS Secrets Manager integration working
- [ ] SnapTrade authentication (userId + userSecret) implemented
- [ ] Data normalization to DataFrame format
- [ ] Basic API calls working (register, connect, fetch positions)

### **Phase 2: Consolidation**
- [ ] `_consolidate_positions()` function added to PortfolioManager
- [ ] `_load_portfolio_from_database()` updated to use consolidation
- [ ] Provider priority logic implemented
- [ ] Multi-provider test cases passing

### **Phase 3: Backend API**
- [ ] SnapTrade routes created (`routes/snaptrade.py`)
- [ ] API endpoints working and tested
- [ ] Database integration via existing `save_portfolio()`
- [ ] Error handling implemented

### **Phase 4: Frontend**
- [ ] Provider routing logic updated
- [ ] SnapTrade connection flow working
- [ ] Account management UI enhanced
- [ ] Provider badges and indicators added

### **Phase 5: Production**
- [ ] Comprehensive error handling
- [ ] Monitoring and logging  
- [ ] Security hardening
- [ ] Full test suite
- [ ] Documentation updated

### **Deployment Checklist**
- [ ] Environment variables configured in production
- [ ] SnapTrade webhook URL registered in SnapTrade Dashboard
- [ ] AWS Secrets Manager permissions configured
- [ ] Rate limiting middleware deployed
- [ ] Monitoring dashboards configured
- [ ] Error alerting set up
- [ ] Database migrations applied (if any)
- [ ] Frontend build includes new SnapTrade components

---

**Ready to begin implementation!** 🚀

The plan is comprehensive, realistic, and perfectly aligned with your existing architecture. Start with Phase 1 and Phase 2 in parallel for fastest progress.
