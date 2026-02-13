# Database Migration Implementation Plan

## Overview
Transform the risk analysis system from single-user file-based to multi-user database architecture by **extending the existing inputs/ layer** with database support. This preserves all existing functionality while adding multi-user capabilities through a dual-mode approach.

## Key Architectural Insight
The existing architecture is perfectly designed for this migration:
- **inputs/ layer** - Already provides data abstraction (perfect for dual-mode)
- **services/ layer** - Works with typed data objects (no changes needed)
- **core risk engine** - Reads YAML files via temporary files (no changes needed)

## Core Architecture Changes

### 1. Database Schema Design
**Goal:** Mirror existing YAML structure with user ID and temporal tracking

**PostgreSQL Schema:**
```sql
-- Users table
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    google_user_id VARCHAR(255) UNIQUE NOT NULL,  -- Google 'sub' field
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    tier VARCHAR(50) DEFAULT 'public',           -- 'public', 'registered', 'paid'
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Portfolios table (maps to PortfolioData)
CREATE TABLE portfolios (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    name VARCHAR(255) NOT NULL,
    start_date DATE NOT NULL,              -- From portfolio.yaml
    end_date DATE NOT NULL,                -- From portfolio.yaml
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, name)
);

-- Store original cash identifiers
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id),
    user_id INTEGER REFERENCES users(id),
    ticker VARCHAR(50) NOT NULL,           -- Original: "CUR:USD", "NVDA"
    shares DECIMAL(15,6),                  -- NULL for cash
    dollars DECIMAL(15,2),                 -- NULL for shares
    position_type VARCHAR(20),             -- "cash", "stock", "etf"
    cash_currency VARCHAR(3),              -- "USD" for cash positions
    expected_return DECIMAL(8,4),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Scenarios table (user-created what-if scenarios)
CREATE TABLE scenarios (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    base_portfolio_id INT REFERENCES portfolios(id),  -- Which real portfolio this is based on
    name VARCHAR(100) NOT NULL,                       -- "Aggressive Growth", "Tech Focus", etc.
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    last_accessed TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, name)
);

-- Scenario positions table (target weights for scenarios)
CREATE TABLE scenario_positions (
    id SERIAL PRIMARY KEY,
    scenario_id INT REFERENCES scenarios(id),
    user_id INT REFERENCES users(id),
    ticker VARCHAR(10) NOT NULL,
    target_weight DECIMAL(8,6) NOT NULL,              -- Target allocation weights
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Risk limits table (maps to risk_limits.yaml structure)
CREATE TABLE risk_limits (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    portfolio_id INT REFERENCES portfolios(id),
    
    -- Portfolio limits
    max_volatility DECIMAL(5,4),              -- portfolio_limits.max_volatility
    max_loss DECIMAL(5,4),                    -- portfolio_limits.max_loss
    
    -- Concentration limits
    max_single_stock_weight DECIMAL(5,4),     -- concentration_limits.max_single_stock_weight
    
    -- Variance limits
    max_factor_contribution DECIMAL(5,4),     -- variance_limits.max_factor_contribution
    max_market_contribution DECIMAL(5,4),     -- variance_limits.max_market_contribution
    max_industry_contribution DECIMAL(5,4),   -- variance_limits.max_industry_contribution
    
    -- Factor limits
    max_single_factor_loss DECIMAL(5,4),      -- max_single_factor_loss
    
    -- Additional settings (flexible storage)
    additional_settings JSONB,
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Factor proxies table (maps to stock_factor_proxies in YAML)
CREATE TABLE factor_proxies (
    id SERIAL PRIMARY KEY,
    portfolio_id INT REFERENCES portfolios(id),
    user_id INT REFERENCES users(id),
    ticker VARCHAR(10) NOT NULL,
    market_proxy VARCHAR(10),                 -- stock_factor_proxies.ticker.market
    momentum_proxy VARCHAR(10),               -- stock_factor_proxies.ticker.momentum
    value_proxy VARCHAR(10),                  -- stock_factor_proxies.ticker.value
    industry_proxy VARCHAR(10),               -- stock_factor_proxies.ticker.industry
    subindustry_peers JSONB,                  -- stock_factor_proxies.ticker.subindustry (array)
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(portfolio_id, ticker)
);

-- User session management table
CREATE TABLE user_sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    last_accessed TIMESTAMP DEFAULT NOW()
);

-- Indexes for session management performance
CREATE INDEX idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX idx_user_sessions_expires ON user_sessions(expires_at);

-- AI Context/Memory tables
CREATE TABLE user_preferences (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    preference_type VARCHAR(50), -- 'risk_tolerance', 'goals', 'constraints'
    preference_value TEXT,
    confidence_level DECIMAL(3,2), -- 0.0 to 1.0
    source VARCHAR(50), -- 'direct_input', 'inferred', 'conversation'
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE conversation_history (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    topic VARCHAR(100),
    key_insights TEXT,
    action_items TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Temporal tracking (experimental)
CREATE TABLE portfolio_changes (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id),
    portfolio_id INT REFERENCES portfolios(id),
    change_type VARCHAR(50), -- 'position_added', 'position_removed', 'weight_changed'
    old_value JSONB,
    new_value JSONB,
    reason TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### 2. Extend Existing inputs/ Layer with Database Support
**Goal:** Add dual-mode capability to existing Manager classes

**Architecture Flow:**
```
Database/Files → inputs/managers → PortfolioData objects → services/ → temp YAML → core engine
                 (dual-mode)         (unchanged)        (unchanged)    (existing pattern)
```

**Enhanced inputs/portfolio_manager.py:**
```python
class PortfolioManager:
    def __init__(self, base_dir: str = ".", validate_on_create: bool = True, 
                 use_database: bool = False, user_id: str = None):
        self.base_dir = base_dir
        self.validate_on_create = validate_on_create
        self.use_database = use_database
        self.user_id = user_id
        self.db_client = DatabaseClient() if use_database else None
    
    def create_what_if_yaml(self, target_weights: Dict[str, float], scenario_name: str) -> str:
        """Create portfolio scenario - works with files OR database"""
        if self.use_database:
            return self._create_portfolio_in_database(target_weights, scenario_name)
        else:
            return self._create_what_if_yaml_file(target_weights, scenario_name)  # Existing logic
    
    def load_portfolio_data(self, portfolio_name: str = "default") -> PortfolioData:
        """Load portfolio data with cash mapping applied at analysis time"""
        if self.use_database:
            return self._load_portfolio_from_database(portfolio_name)
        else:
            return self._load_portfolio_from_yaml(portfolio_name)
    
    def save_portfolio_data(self, portfolio_data: PortfolioData, portfolio_name: str = "default"):
        """Save portfolio data - works with files OR database"""
        if self.use_database:
            return self._save_portfolio_to_database(portfolio_data, portfolio_name)
        else:
            return self._save_portfolio_to_yaml(portfolio_data, portfolio_name)
    
    def _apply_cash_mapping(self, positions: List[Dict]) -> Dict[str, Dict]:
        """Apply cash-to-proxy mapping at analysis time (preserves original data)"""
        import yaml
        
        # Load cash mapping configuration
        try:
            with open("cash_map.yaml", "r") as f:
                cash_map = yaml.safe_load(f)
        except FileNotFoundError:
            print("⚠️ cash_map.yaml not found, using default USD mapping")
            cash_map = {
                "proxy_by_currency": {"USD": "SGOV"},
                "alias_to_currency": {"CUR:USD": "USD", "CASH": "USD"}
            }
        
        proxy_by_currency = cash_map.get("proxy_by_currency", {})
        alias_to_currency = cash_map.get("alias_to_currency", {})
        
        portfolio_input = {}
        
        for pos in positions:
            ticker = pos["ticker"]
            
            # Check if this is a cash position that needs mapping
            if pos.get("position_type") == "cash":
                # Direct currency mapping
                currency = pos.get("cash_currency", "USD")
                proxy_ticker = proxy_by_currency.get(currency, ticker)
                
                # Apply alias mapping if no direct currency match
                if proxy_ticker == ticker and ticker in alias_to_currency:
                    currency = alias_to_currency[ticker]
                    proxy_ticker = proxy_by_currency.get(currency, ticker)
                
                portfolio_input[proxy_ticker] = {"dollars": pos["dollars"]}
                print(f"📊 Cash mapping: {ticker} ({currency}) → {proxy_ticker}")
            else:
                # Regular stock/ETF position - no mapping needed
                if pos.get("shares"):
                    portfolio_input[ticker] = {"shares": pos["shares"]}
                else:
                    portfolio_input[ticker] = {"dollars": pos["dollars"]}
        
        return portfolio_input
    
    # Private database methods (TODO: Implementation needed)
    def _create_portfolio_in_database(self, target_weights, scenario_name):
        """TODO: Create scenario in database (not real portfolio)
        - Calculate deltas from current portfolio (same logic as file version)
        - Insert new scenario record with scenario_name
        - Insert scenario_positions records with target weights
        - Return scenario identifier/path for compatibility
        """
        pass
    
    def _load_portfolio_from_database(self, portfolio_name: str) -> PortfolioData:
        """Load real portfolio from database with cash mapping applied at analysis time"""
        # 1. Load original positions from database (with original cash tickers)
        raw_positions = self.db_client.get_portfolio_positions(self.user_id, portfolio_name)
        
        # 2. Apply cash mapping for analysis (CUR:USD → SGOV)
        mapped_portfolio_input = self._apply_cash_mapping(raw_positions)
        
        # 3. Load metadata and other components
        portfolio_metadata = self.db_client.get_portfolio_metadata(self.user_id, portfolio_name)
        factor_proxies = self.db_client.get_factor_proxies(self.user_id, portfolio_name)
        expected_returns = self.db_client.get_expected_returns(self.user_id, portfolio_name)
        
        # 4. Construct PortfolioData object (same format as YAML)
        portfolio_data = PortfolioData({
            "portfolio_input": mapped_portfolio_input,  # With cash mapping applied
            "start_date": portfolio_metadata["start_date"],
            "end_date": portfolio_metadata["end_date"],
            "expected_returns": expected_returns,
            "stock_factor_proxies": factor_proxies
        })
        
        return portfolio_data
    
    def _save_portfolio_to_database(self, portfolio_data: PortfolioData, portfolio_name: str):
        """Save real portfolio to database (stores original cash identifiers)"""
        # Note: This method should store the ORIGINAL cash identifiers
        # before any mapping is applied. The mapping happens at load time.
        
        # TODO: Implementation needed
        # - Insert/update portfolio record
        # - Insert/update position records with ORIGINAL holdings:
        #   • Stocks/ETFs: store in shares column
        #   • Cash positions: store in dollars column with original ticker (CUR:USD)
        # - Insert/update factor_proxies records
        # - Return success/failure status
        pass
    
    def load_scenario_data(self, scenario_name: str = "default") -> PortfolioData:
        """TODO: Load scenario data - works with files OR database"""
        if self.use_database:
            return self._load_scenario_from_database(scenario_name)
        else:
            return self._load_scenario_from_yaml(scenario_name)
    
    def save_scenario_data(self, scenario_data: Dict, scenario_name: str, base_portfolio_name: str = "default"):
        """TODO: Save scenario data - works with files OR database"""
        if self.use_database:
            return self._save_scenario_to_database(scenario_data, scenario_name, base_portfolio_name)
        else:
            return self._save_scenario_to_yaml(scenario_data, scenario_name)
    
    # Private file methods (existing code unchanged)
    def _create_what_if_yaml_file(self, target_weights, scenario_name):
        # Existing file-based logic unchanged - no changes needed
        pass
    
    def _load_portfolio_from_yaml(self, portfolio_name: str) -> PortfolioData:
        # Existing file-based logic unchanged - no changes needed
        pass
    
    def _save_portfolio_to_yaml(self, portfolio_data: PortfolioData, portfolio_name: str):
        # Existing file-based logic unchanged - no changes needed
        pass
```

**Enhanced inputs/risk_config.py:**
```python
class RiskConfigManager:
    def __init__(self, base_dir: str = ".", config_file: str = "risk_limits.yaml",
                 use_database: bool = False, user_id: str = None):
        self.base_dir = base_dir
        self.config_file = config_file
        self.use_database = use_database
        self.user_id = user_id
        self.db_client = DatabaseClient() if use_database else None
    
    def view_current_risk_limits(self) -> str:
        """View risk limits - works with files OR database"""
        if self.use_database:
            return self._view_risk_limits_from_database()
        else:
            return self._view_risk_limits_from_yaml()  # Existing logic
    
    def update_risk_limits(self, limits_dict: Dict[str, Any], portfolio_name: str = "default"):
        """Update risk limits - works with files OR database"""
        if self.use_database:
            return self._update_risk_limits_in_database(limits_dict, portfolio_name)
        else:
            return self._update_risk_limits_in_yaml(limits_dict)  # Existing logic
    
    # Private database methods (TODO: Implementation needed)
    def _view_risk_limits_from_database(self) -> str:
        """TODO: View risk limits from database
        - Query risk_limits table for user_id
        - Reconstruct risk_limits.yaml structure
        - Format for display (same as file version)
        """
        pass
    
    def _update_risk_limits_in_database(self, limits_dict: Dict[str, Any], portfolio_name: str):
        """TODO: Update risk limits in database
        - Get or create portfolio_id for user
        - Insert/update risk_limits table records
        - Return success/failure status
        """
        pass
```

**Create new file:** `inputs/database_client.py`
```python
import psycopg2
import psycopg2.extras
from typing import Dict, List, Optional
import json
from core.data_objects import PortfolioData, Position, RiskLimits

class DatabaseClient:
    """Database client for multi-user portfolio data storage"""
    
    def __init__(self):
        self.connection = self._connect()
    
    def _connect(self):
        """TODO: Connect to PostgreSQL database using environment variables
        - Use DATABASE_URL or individual DB config from environment
        - Handle connection pooling
        - Return connection object
        """
        pass
    
    def get_or_create_user_id(self, google_user_id: str) -> int:
        """TODO: Convert Google user ID to internal user ID, create if not exists
        - Query users table for google_user_id
        - If not found, create new user record
        - Return internal user_id (primary key)
        """
        pass
    
    def get_portfolio_id(self, user_id: int, portfolio_name: str) -> int:
        """TODO: Get portfolio ID for user and portfolio name
        - Query portfolios table for user_id + name
        - Return portfolio_id or None if not found
        """
        pass
    
    def get_portfolio(self, user_id: int, portfolio_name: str) -> Dict:
        """TODO: Retrieve real portfolio data from database
        - Query portfolios table for metadata (start_date, end_date)
        - Query positions table for holdings (ticker, shares/dollars)
        - Query factor_proxies table for stock_factor_proxies
        - Reconstruct exact portfolio.yaml structure with real holdings:
          • {"shares": 1410.9007} for stocks/ETFs
          • {"dollars": -5078.62} for cash positions
        - Return dict that can be passed to PortfolioData constructor
        """
        pass
    
    def get_scenario(self, user_id: int, scenario_name: str) -> Dict:
        """TODO: Retrieve scenario data from database
        - Query scenarios table for metadata and base_portfolio_id
        - Query scenario_positions table for target weights
        - Query base portfolio for start_date, end_date, factor_proxies
        - Reconstruct portfolio.yaml structure with scenario weights:
          • {"weight": 0.30} for all positions
        - Return dict that can be passed to PortfolioData constructor
        """
        pass
    
    def save_portfolio(self, portfolio_data: PortfolioData, user_id: int, portfolio_name: str):
        """TODO: Save real portfolio to database
        - Insert/update portfolios table
        - Insert/update positions table (delete old, insert new):
          • For stocks/ETFs: store in shares column
          • For cash positions: store in dollars column
        - Insert/update factor_proxies table
        - Handle transaction rollback on error
        """
        pass
    
    def save_scenario(self, scenario_data: Dict, user_id: int, scenario_name: str, base_portfolio_id: int):
        """TODO: Save scenario to database
        - Insert/update scenarios table (name, description, base_portfolio_id)
        - Insert/update scenario_positions table (delete old, insert new):
          • Store target_weight for each ticker
        - Handle transaction rollback on error
        """
        pass
    
    def get_risk_limits(self, user_id: int, portfolio_id: int = None) -> Dict:
        """TODO: Retrieve risk limits from database
        - Query risk_limits table for user_id (and optional portfolio_id)
        - Reconstruct exact risk_limits.yaml structure
        - Return dict matching YAML structure
        """
        pass
    
    def save_risk_limits(self, risk_limits: Dict, user_id: int, portfolio_id: int = None):
        """TODO: Save risk limits to database
        - Insert/update risk_limits table records
        - Map each field from risk_limits.yaml to database columns
        - Handle portfolio-specific vs user-default limits
        """
        pass
    
    def get_user_context(self, user_id: int) -> Dict:
        """TODO: Get user preferences and conversation history for AI context
        - Query user_preferences table
        - Query conversation_history table (recent entries)
        - Return structured context for AI memory
        """
        pass
    
    def store_conversation(self, user_id: int, topic: str, insights: str, action_items: str = None):
        """TODO: Store conversation for AI memory
        - Insert into conversation_history table
        - Include timestamp and context
        """
        pass
    
    def create_session(self, session_id: str, user_id: int, expires_at: datetime):
        """TODO: Create user session in database
        - Insert into user_sessions table
        - Return session_id for cookie
        """
        pass
    
    def get_user_by_session(self, session_id: str) -> Dict:
        """TODO: Get user by session ID
        - Query user_sessions table for valid session
        - Join with users table for user info
        - Update last_accessed timestamp
        - Return user dict or None if invalid/expired
        """
        pass
    
    def delete_expired_sessions(self):
        """TODO: Clean up expired sessions
        - Delete sessions where expires_at < NOW()
        - Run periodically via cron job or background task
        """
        pass
    
    def update_user_info(self, user_id: int, user_info: Dict):
        """TODO: Update user information
        - Update email, name, last_login in users table
        - Handle partial updates (only provided fields)
        """
        pass
```

## Cash Mapping Architecture: Store Original, Map at Analysis Time

### Design Philosophy
**Store what users actually have, map what analysis needs**

The database stores original cash identifiers (e.g., `CUR:USD`, `USD CASH`) exactly as they appear in broker statements. Cash-to-proxy mapping is applied at analysis time through the `inputs/portfolio_manager.py` layer, preserving data integrity while enabling flexible analysis.

### Benefits of This Approach

#### 1. **Data Integrity & Auditability**
```python
# Database stores what user ACTUALLY has
positions = [
    {"ticker": "CUR:USD", "dollars": -5078.62, "position_type": "cash", "cash_currency": "USD"},
    {"ticker": "NVDA", "shares": 25.0, "position_type": "stock"}
]

# User can see original broker data
# Analysis gets properly mapped proxies
```

#### 2. **Flexible Proxy Management**
```python
# Change proxy mapping without affecting stored data
# cash_map.yaml: USD: SGOV → USD: USFR
# All existing portfolios automatically use new proxy
```

#### 3. **Transparent Data Flow**
```python
# Clear separation of concerns
Original Data (Database) → Cash Mapping (Analysis Time) → Risk Engine (Mapped Proxies)
     CUR:USD           →        SGOV                →      Portfolio Analysis
```

#### 4. **Multi-Currency Support**
```python
# Support multiple currencies with clear mapping
positions = [
    {"ticker": "CUR:USD", "dollars": -5000, "cash_currency": "USD"},
    {"ticker": "CUR:EUR", "dollars": -3000, "cash_currency": "EUR"},
    {"ticker": "CUR:GBP", "dollars": -2000, "cash_currency": "GBP"}
]

# Maps to: USD→SGOV, EUR→ESTR, GBP→IB01
```

### Implementation Details

#### Enhanced Database Schema
```sql
-- Store original cash identifiers with clear metadata
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id),
    user_id INTEGER REFERENCES users(id),
    ticker VARCHAR(50) NOT NULL,           -- Original: "CUR:USD", "NVDA"
    shares DECIMAL(15,6),                  -- NULL for cash
    dollars DECIMAL(15,2),                 -- NULL for shares
    position_type VARCHAR(20),             -- "cash", "stock", "etf"
    cash_currency VARCHAR(3),              -- "USD" for cash positions
    expected_return DECIMAL(8,4),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Example data
INSERT INTO positions (portfolio_id, user_id, ticker, dollars, position_type, cash_currency)
VALUES (1, 1, 'CUR:USD', -5078.62, 'cash', 'USD');

INSERT INTO positions (portfolio_id, user_id, ticker, shares, position_type)
VALUES (1, 1, 'NVDA', 25.0, 'stock');
```

#### Updated Plaid Integration
```python
def convert_plaid_df_to_database(
    df: pd.DataFrame,
    user_id: str,
    portfolio_name: str = "main",
    dates: dict = None
) -> None:
    """Convert Plaid holdings directly to database (stores ORIGINAL cash identifiers)"""
    
    # Store ORIGINAL cash identifiers (NO mapping applied)
    positions = []
    for _, row in df.iterrows():
        ticker = row["ticker"]
        qty = row.get("quantity")
        val = row.get("value")
        
        position = {
            "ticker": ticker,  # Keep original "CUR:USD"
            "position_type": "cash" if ticker.startswith("CUR:") or "CASH" in ticker else "stock"
        }
        
        # Determine cash currency from ticker
        if position["position_type"] == "cash":
            if ":" in ticker:
                position["cash_currency"] = ticker.split(":")[-1]  # "CUR:USD" → "USD"
            else:
                position["cash_currency"] = "USD"  # Default fallback
            position["dollars"] = float(val)
        elif pd.notna(qty) and qty > 0:
            position["shares"] = float(qty)
        else:
            position["dollars"] = float(val)
        
        positions.append(position)
    
    # Save to database with original identifiers
    portfolio_manager = PortfolioManager(use_database=True, user_id=user_id)
    portfolio_data = PortfolioData({
        "portfolio_input": self._build_portfolio_input_from_positions(positions),
        "start_date": dates["start_date"],
        "end_date": dates["end_date"],
        "expected_returns": {},
        "stock_factor_proxies": {}
    })
    
    portfolio_manager.save_portfolio_data(portfolio_data, portfolio_name)
    print(f"✅ Portfolio with original cash identifiers saved to database for user {user_id}")

def _build_portfolio_input_from_positions(self, positions: List[Dict]) -> Dict:
    """Build portfolio_input dict from position records for database storage"""
    portfolio_input = {}
    
    for pos in positions:
        ticker = pos["ticker"]
        
        if pos.get("shares"):
            portfolio_input[ticker] = {"shares": pos["shares"]}
        else:
            portfolio_input[ticker] = {"dollars": pos["dollars"]}
    
    return portfolio_input
```

### Data Flow Comparison

#### Current File-Based Flow
```
Plaid API → DataFrame → map_cash_to_proxy() → convert_plaid_df_to_yaml_input() → portfolio.yaml
                              ↓
                        CUR:USD → SGOV (mapping applied at storage)
```

#### New Database Flow
```
Plaid API → DataFrame → convert_plaid_df_to_database() → Database (original: CUR:USD)
                                                            ↓
Portfolio Load → _apply_cash_mapping() → Analysis (mapped: SGOV)
```

### Analysis Time Mapping Process

```python
# 1. Load original positions from database
raw_positions = [
    {"ticker": "CUR:USD", "dollars": -5078.62, "position_type": "cash", "cash_currency": "USD"},
    {"ticker": "NVDA", "shares": 25.0, "position_type": "stock"}
]

# 2. Apply cash mapping at analysis time
mapped_portfolio_input = {
    "SGOV": {"dollars": -5078.62},  # CUR:USD → SGOV
    "NVDA": {"shares": 25.0}        # No mapping needed
}

# 3. Risk analysis proceeds normally
portfolio_data = PortfolioData({
    "portfolio_input": mapped_portfolio_input,  # Analysis-ready format
    "start_date": "2024-01-01",
    "end_date": "2024-12-31",
    "expected_returns": {},
    "stock_factor_proxies": {}
})
```

### Benefits Summary

✅ **Data Integrity**: Store what user actually has (`CUR:USD`)
✅ **Flexibility**: Change proxy mappings without affecting stored data
✅ **Transparency**: Clear separation between "user holdings" vs "analysis format"
✅ **Audit Trail**: Can see original broker data and applied mappings
✅ **Consistency**: Same cash mapping logic, just applied at analysis time
✅ **Future-Proof**: Easy to add new cash proxies or change existing ones
✅ **Multi-Currency**: Clear currency identification and mapping
✅ **No Breaking Changes**: Risk engine gets same format as before

## Plaid Integration Compatibility

### Current Plaid Flow Analysis ✅
The database migration plan is **fully compatible** with the existing Plaid integration:

**Current Flow:**
```python
# 1. User authenticated via Google OAuth (gets google_user_id)
# 2. Plaid token stored in AWS Secrets Manager
store_plaid_token(user_id="google_sub_12345", institution="Interactive Brokers", ...)

# 3. Holdings fetched and converted to YAML
df = load_all_user_holdings(user_id="google_sub_12345", region_name="us-east-1", client)
convert_plaid_df_to_yaml_input(df, output_path="portfolio.yaml")  # Applies cash mapping

# 4. Portfolio analysis
run_portfolio("portfolio.yaml")
```

**Key Compatibility Points:**
- ✅ **Google user ID alignment** - Current system already uses this as primary identifier
- ✅ **AWS Secrets Manager** - No changes needed to token storage pattern
- ✅ **Cash mapping improvement** - Database migration actually solves existing transparency issues
- ✅ **User isolation** - Plaid data will be properly isolated per user in database

### Required Plaid Updates for Database Mode

**1. Update Plaid Routes for Dual-Mode Support:**
```python
# routes/plaid.py
@plaid_bp.route('/import', methods=['POST'])
def import_portfolio():
    user_id = request.json.get('user_id')  # Google user ID
    
    # Load holdings from Plaid
    df = load_all_user_holdings(user_id, region_name, client)
    
    # Choose storage method based on database mode
    if USE_DATABASE:
        # NEW: Store to database with original cash identifiers
        convert_plaid_df_to_database(
            df, 
            user_id=user_id,
            portfolio_name="plaid_import",
            dates={"start_date": "2020-01-01", "end_date": "2024-12-31"}
        )
    else:
        # EXISTING: Store to YAML with cash mapping
        convert_plaid_df_to_yaml_input(df, output_path="portfolio.yaml")
    
    return {"status": "success", "message": "Portfolio imported"}
```

**2. Enhanced Error Handling with Fallback:**
```python
def convert_plaid_df_to_database(df, user_id, portfolio_name, dates):
    """Enhanced with fallback to YAML if database fails"""
    try:
        # Store to database with original cash identifiers
        portfolio_manager = PortfolioManager(use_database=True, user_id=user_id)
        # ... database storage logic
        
    except DatabaseError as e:
        logger.warning(f"Database storage failed, falling back to YAML: {e}")
        # Fallback to existing YAML storage
        convert_plaid_df_to_yaml_input(df, output_path=f"portfolio_{user_id}.yaml")
        raise UserWarning("Data saved to file mode due to database error")
```

**3. Benefits of Database Migration for Plaid:**
- ✅ **Preserves original cash identifiers** for transparency (`CUR:USD` vs `SGOV`)
- ✅ **Enables multi-user support** with proper isolation
- ✅ **Provides better audit trail** of what users actually own
- ✅ **Supports flexible cash proxy changes** without data loss

## Performance Considerations

### Connection Pooling Strategy
```python
# inputs/database_client.py
import psycopg2.pool

class DatabaseClient:
    def __init__(self):
        self.connection_pool = self._create_connection_pool()
    
    def _create_connection_pool(self):
        """Create connection pool sized for expected usage"""
        return psycopg2.pool.SimpleConnectionPool(
            2, 10,  # Development: 2-10 connections
            # Production: scale based on concurrent users
            # Recommended: 1-2 connections per concurrent user
            DATABASE_URL
        )
    
    def get_connection(self):
        """Get connection from pool"""
        return self.connection_pool.getconn()
    
    def put_connection(self, conn):
        """Return connection to pool"""
        self.connection_pool.putconn(conn)
```

### Caching Strategy Integration
**Ensure database mode doesn't break existing price caching:**
```python
# data_loader.py integration
def fetch_monthly_close(ticker, start_date=None, end_date=None):
    """Existing cache_read functionality works identically in database mode"""
    # Current cache system (cache_prices/) continues to work
    # Database only affects portfolio data, not price data
    return cache_read(
        key=[ticker, start_date, end_date],
        loader=lambda: _api_pull(),
        cache_dir="cache_prices",
        prefix=ticker
    )
```

**Database Query Optimization:**
```sql
-- Add indexes for common queries
CREATE INDEX idx_positions_user_portfolio ON positions(user_id, portfolio_id);
CREATE INDEX idx_portfolios_user_name ON portfolios(user_id, name);
CREATE INDEX idx_user_sessions_token ON user_sessions(session_token);
CREATE INDEX idx_user_sessions_expires ON user_sessions(expires_at);

-- Additional performance indexes
CREATE INDEX idx_positions_ticker ON positions(ticker);
CREATE INDEX idx_positions_created_at ON positions(created_at);
CREATE INDEX idx_portfolios_updated_at ON portfolios(updated_at);
CREATE INDEX idx_conversation_history_user_created ON conversation_history(user_id, created_at);

-- Composite indexes for complex queries
CREATE INDEX idx_positions_user_ticker ON positions(user_id, ticker);
CREATE INDEX idx_risk_limits_user_portfolio ON risk_limits(user_id, portfolio_id);
```

### Database Size Estimation & Capacity Planning
```python
# Expected database size calculations
"""
Estimated storage per user:
- Portfolios: ~1KB per portfolio × 5 portfolios = 5KB
- Positions: ~200 bytes per position × 50 positions = 10KB  
- Risk limits: ~5KB per user
- User sessions: ~500 bytes per session × 5 sessions = 2.5KB
- Conversation history: ~1KB per conversation × 100 conversations = 100KB

Total per user: ~122KB
For 1,000 users: ~122MB
For 10,000 users: ~1.2GB
For 100,000 users: ~12GB

Recommended PostgreSQL instance sizing:
- Development: 1GB RAM, 10GB storage
- Production (1K users): 2GB RAM, 50GB storage  
- Production (10K users): 4GB RAM, 100GB storage
- Production (100K users): 8GB RAM, 500GB storage
"""
```

### Query Performance Benchmarks
```python
# Expected query performance targets
"""
Performance targets (95th percentile):
- Portfolio load: < 100ms
- Position save: < 50ms  
- User authentication: < 25ms
- Risk limits load: < 50ms
- Cash mapping: < 10ms (in-memory)

Connection pool sizing guidelines:
- Development: 2-5 connections (single developer)
- Staging: 5-10 connections (testing load)
- Production: 10-25 connections (concurrent users)
- Scale: +2 connections per 10 concurrent users

Memory usage per connection: ~8MB
Total pool memory: connections × 8MB
Example: 20 connections = 160MB memory
"""
```

### Concurrent User Handling
```python
# Concurrent user capacity planning
class DatabaseClient:
    def __init__(self):
        # Dynamic pool sizing based on environment
        pool_size = self._calculate_pool_size()
        self.connection_pool = psycopg2.pool.SimpleConnectionPool(
            1, pool_size, DATABASE_URL
        )
    
    def _calculate_pool_size(self):
        """Calculate optimal pool size based on expected load"""
        env = os.getenv("ENVIRONMENT", "development")
        
        pool_sizes = {
            "development": 5,
            "staging": 10, 
            "production": 20
        }
        
        # Allow override via environment variable
        override = os.getenv("DB_POOL_SIZE")
        if override:
            return int(override)
            
        return pool_sizes.get(env, 5)
    
    def get_connection_with_timeout(self, timeout=30):
        """Get connection with timeout to prevent hanging"""
        try:
            return self.connection_pool.getconn()
        except psycopg2.pool.PoolError:
            raise DatabaseError("Connection pool exhausted - too many concurrent users")
```

### Network Latency & Geographic Considerations
```python
# Database latency optimization
"""
Network latency mitigation strategies:

1. Connection Keep-Alive:
   - Use persistent connections via connection pooling
   - Avoid connection overhead for each query

2. Query Batching:
   - Batch multiple position inserts into single transaction
   - Use prepared statements for repeated queries

3. Geographic Deployment:
   - Database in same region as application server
   - Expected latency: < 1ms (same AZ), < 5ms (same region)

4. Read Replicas (future enhancement):
   - Read-only queries to replica database
   - Write queries to primary database
   - Eventual consistency acceptable for portfolio reads
"""

# Connection optimization
class DatabaseClient:
    def __init__(self):
        self.connection_pool = psycopg2.pool.SimpleConnectionPool(
            2, 20,
            DATABASE_URL,
            # Optimization parameters
            options="-c default_transaction_isolation=read_committed "
                   "-c timezone=UTC "
                   "-c statement_timeout=30000"  # 30 second timeout
        )
    
    def batch_save_positions(self, positions, portfolio_id):
        """Batch save positions for better performance"""
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                # Use copy_from for bulk inserts (10x faster than individual inserts)
                from io import StringIO
                import csv
                
                # Create CSV data in memory
                csv_data = StringIO()
                writer = csv.writer(csv_data)
                for pos in positions:
                    writer.writerow([
                        portfolio_id, pos["user_id"], pos["ticker"],
                        pos.get("shares"), pos.get("dollars"),
                        pos.get("position_type"), pos.get("cash_currency")
                    ])
                
                csv_data.seek(0)
                cur.copy_from(
                    csv_data, 'positions',
                    columns=['portfolio_id', 'user_id', 'ticker', 'shares', 'dollars', 'position_type', 'cash_currency'],
                    sep=','
                )
```

### Monitoring & Performance Alerting
```python
# Performance monitoring setup
"""
Key metrics to monitor:

1. Database Performance:
   - Query response time (95th percentile)
   - Connection pool utilization
   - Active connections count
   - Database CPU/memory usage

2. Application Performance:
   - Portfolio load time
   - Cash mapping execution time
   - API response times
   - Error rates

3. User Experience:
   - Time to first portfolio load
   - Plaid import completion time
   - Analysis result delivery time

Alerting thresholds:
- Query time > 500ms (warning)
- Query time > 1000ms (critical)
- Connection pool > 80% (warning)
- Connection pool > 95% (critical)
- Error rate > 1% (warning)
- Error rate > 5% (critical)
"""

# Performance monitoring code
import time
import logging
from functools import wraps

def monitor_performance(operation_name):
    """Decorator to monitor database operation performance"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = time.time() - start_time
                
                # Log slow queries
                if duration > 0.1:  # 100ms threshold
                    logging.warning(f"Slow {operation_name}: {duration:.3f}s")
                
                # Track metrics (integrate with your monitoring system)
                track_metric(f"database.{operation_name}.duration", duration)
                track_metric(f"database.{operation_name}.success", 1)
                
                return result
            except Exception as e:
                duration = time.time() - start_time
                logging.error(f"Failed {operation_name}: {duration:.3f}s - {e}")
                track_metric(f"database.{operation_name}.error", 1)
                raise
        return wrapper
    return decorator

# Usage in DatabaseClient
class DatabaseClient:
    @monitor_performance("portfolio_load")
    def get_portfolio_positions(self, user_id, portfolio_name):
        # ... existing implementation
        pass
    
    @monitor_performance("portfolio_save")
    def save_portfolio_positions(self, positions, portfolio_id):
        # ... existing implementation
        pass
```

### Backup & Recovery Performance
```python
# Backup strategy for production
"""
Backup & Recovery Strategy:

1. Automated Backups:
   - Daily full backups (low usage hours)
   - Hourly incremental backups during business hours
   - Point-in-time recovery capability

2. Backup Performance:
   - Expected backup time: ~2 minutes per GB
   - Compression: ~60% size reduction
   - Parallel backup streams for large databases

3. Recovery Testing:
   - Monthly recovery tests to staging environment
   - Recovery time target: < 30 minutes for 10GB database
   - Data integrity validation post-recovery

4. Disaster Recovery:
   - Cross-region backup replication
   - Automated failover capabilities
   - RPO: 1 hour (max data loss)
   - RTO: 2 hours (max downtime)
"""

# Database maintenance commands
maintenance_commands = {
    "vacuum": "VACUUM ANALYZE;",  # Weekly maintenance
    "reindex": "REINDEX DATABASE risk_module_db;",  # Monthly maintenance
    "stats": "SELECT schemaname, tablename, n_tup_ins, n_tup_upd, n_tup_del FROM pg_stat_user_tables;",
    "connections": "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';",
    "slow_queries": """
        SELECT query, mean_time, calls, total_time 
        FROM pg_stat_statements 
        ORDER BY mean_time DESC 
        LIMIT 10;
    """
}
```

## Error Handling & Migration State Detection

### Migration State Detection
```python
class PortfolioManager:
    def __init__(self, base_dir=".", use_database=None, user_id=None):
        if use_database is None:
            # Auto-detect based on user data availability
            use_database = self._should_use_database(user_id)
        self.use_database = use_database
        self.user_id = user_id
        self.db_client = DatabaseClient() if use_database else None
    
    def _should_use_database(self, user_id):
        """Determine if user should use file or database mode"""
        if user_id is None:
            return False  # CLI mode, use files
        
        try:
            # Check if user has database data
            if self._user_has_database_data(user_id):
                return True
            # Check if user has file data
            elif self._user_has_file_data(user_id):
                return False
            else:
                return True  # New users default to database
        except Exception:
            return False  # Fallback to file mode on errors
    
    def _user_has_database_data(self, user_id):
        """Check if user has any data in database"""
        try:
            db_client = DatabaseClient()
            internal_user_id = db_client.get_user_id(user_id)
            return internal_user_id is not None
        except:
            return False
    
    def _user_has_file_data(self, user_id):
        """Check if user has file-based data"""
        user_portfolio_path = f"portfolio_{user_id}.yaml"
        return os.path.exists(user_portfolio_path) or os.path.exists("portfolio.yaml")
```

### Enhanced Error Handling
```python
def load_portfolio_data(self, portfolio_name: str = "default") -> PortfolioData:
    """Load portfolio with graceful fallback between modes"""
    try:
        if self.use_database:
            return self._load_portfolio_from_database(portfolio_name)
        else:
            return self._load_portfolio_from_yaml(portfolio_name)
    except DatabaseError as e:
        logger.warning(f"Database load failed, falling back to files: {e}")
        return self._load_portfolio_from_yaml(portfolio_name)
    except FileNotFoundError as e:
        if self.use_database:
            logger.info(f"File not found, this is expected in database mode: {e}")
            return self._load_portfolio_from_database(portfolio_name)
        else:
            raise e
```

## Data Validation & Consistency

### Migration Data Validation
```python
def validate_portfolio_data_consistency(file_data, db_data):
    """Ensure file->database migration preserves data integrity"""
    assert file_data.portfolio_input.keys() == db_data.portfolio_input.keys(), \
        "Portfolio tickers must match between file and database"
    
    assert file_data.start_date == db_data.start_date, \
        "Start dates must match"
    
    assert file_data.end_date == db_data.end_date, \
        "End dates must match"
    
    # Validate total portfolio value (within 1 cent tolerance)
    file_total = sum(
        pos.get("dollars", 0) for pos in file_data.portfolio_input.values()
    )
    db_total = sum(
        pos.get("dollars", 0) for pos in db_data.portfolio_input.values()
    )
    assert abs(file_total - db_total) < 0.01, \
        f"Total portfolio values must match: file={file_total}, db={db_total}"
```

### Cash Mapping Validation
```python
def _load_cash_proxies(yaml_path="cash_map.yaml"):
    """Load cash proxy tickers dynamically from cash_map.yaml"""
    try:
        # Option 1: Reuse existing function from plaid_loader.py
        from plaid_loader import _load_maps
        proxy_by_currency, _ = _load_maps(yaml_path)
        return set(proxy_by_currency.values())
        
    except ImportError:
        # Option 2: Standalone implementation if plaid_loader not available
        try:
            import yaml
            from pathlib import Path
            
            if Path(yaml_path).is_file():
                with open(yaml_path, "r") as f:
                    cash_map = yaml.safe_load(f)
                
                # Get all proxy tickers from the cash_map configuration
                return set(cash_map.get("proxy_by_currency", {}).values())
            else:
                # Fallback if cash_map.yaml not found
                return {"SGOV", "ESTR", "IB01"}
                
        except Exception:
            # Fallback on any error
            return {"SGOV", "ESTR", "IB01"}

def _validate_cash_mapping(self, original_positions, mapped_input, yaml_path="cash_map.yaml"):
    """Ensure cash mapping preserves total dollar values"""
    original_cash_total = sum(
        pos["dollars"] for pos in original_positions
        if pos.get("position_type") == "cash"
    )
    
    # Load cash proxies dynamically from cash_map.yaml
    cash_proxies = _load_cash_proxies(yaml_path)
    
    mapped_cash_total = sum(
        data["dollars"] for ticker, data in mapped_input.items()
        if ticker in cash_proxies
    )
    
    assert abs(original_cash_total - mapped_cash_total) < 0.01, \
        f"Cash mapping must preserve total value: original={original_cash_total}, mapped={mapped_cash_total}"
```

### Runtime Data Validation
```python
class DatabaseClient:
    def save_portfolio_positions(self, positions, portfolio_id):
        """Save portfolio positions with validation"""
        # Validate data before saving
        self._validate_positions_data(positions)
        
        # Use transaction for atomic operations
        with self.get_connection() as conn:
            with conn.cursor() as cur:
                try:
                    # Delete existing positions
                    cur.execute("DELETE FROM positions WHERE portfolio_id = %s", (portfolio_id,))
                    
                    # Insert new positions
                    for pos in positions:
                        cur.execute("""
                            INSERT INTO positions (portfolio_id, user_id, ticker, shares, dollars, position_type, cash_currency)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """, (portfolio_id, pos["user_id"], pos["ticker"], pos.get("shares"), pos.get("dollars"), pos.get("position_type"), pos.get("cash_currency")))
                    
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    raise DatabaseError(f"Failed to save portfolio positions: {e}")
    
    def _validate_positions_data(self, positions):
        """Validate positions data before database save"""
        for pos in positions:
            assert "ticker" in pos, "Position must have ticker"
            assert "user_id" in pos, "Position must have user_id"
            assert pos.get("shares") or pos.get("dollars"), "Position must have shares or dollars"
            
            # Validate cash positions have currency
            if pos.get("position_type") == "cash":
                assert pos.get("cash_currency"), "Cash positions must have currency"
```

## Implementation Scope

### What's Provided in This Plan:
- ✅ **Complete database schema** with exact field mappings to YAML structure
- ✅ **Clear architecture approach** - extend existing inputs/ managers with dual-mode
- ✅ **Method signatures** for all dual-mode functionality
- ✅ **Detailed TODO comments** explaining what each method should do
- ✅ **Cash mapping architecture** with store-original-map-at-analysis-time approach
- ✅ **Migration strategy** and testing approach
- ✅ **User authentication integration** with Google OAuth
- ✅ **Data flow examples** and implementation patterns

### What Needs to be Implemented:
- ❌ **Database connection logic** in `DatabaseClient._connect()` with connection pooling
- ❌ **SQL queries** in all DatabaseClient methods with proper indexing
- ❌ **Database CRUD operations** in manager private methods with transactions
- ❌ **Data transformation** between database rows and YAML structure
- ❌ **Error handling** and transaction management with fallback mechanisms  
- ❌ **Environment variable configuration** for database connection
- ❌ **Migration scripts** to convert existing YAML/parquet data to database
- ❌ **Testing suite** for dual-mode functionality with validation
- ❌ **Plaid integration updates** for database storage mode
- ❌ **Migration state detection** for automatic mode switching
- ❌ **Data validation layer** for migration consistency checks

### Implementation Guidance:
Each TODO method includes:
- **Purpose** - What the method should accomplish
- **Data flow** - What tables to query/update
- **Expected output** - What format to return
- **Key requirements** - Critical functionality to preserve

## Implementation Steps

### Phase 1: Database Setup
1. **Install PostgreSQL** (local development)
   ```bash
   # macOS
   brew install postgresql
   brew services start postgresql
   
   # Create database
   createdb risk_module_db
   ```

2. **Create database schema** using SQL script from this plan
   ```bash
   psql risk_module_db < db_schema.sql
   ```

3. **Set up environment variables**
   ```bash
   # .env file
   USE_DATABASE=false              # Start with file mode
   DATABASE_URL=postgresql://user:pass@localhost:5432/risk_module_db
   ```

4. **Create basic DatabaseClient** in `inputs/database_client.py`
   - Implement `_connect()` method using DATABASE_URL
   - Add connection pooling with dynamic sizing (dev: 5, staging: 10, prod: 20)
   - Add error handling for connection failures with timeout protection
   - Add database indexes for query optimization
   - **Add performance monitoring** with query timing and metrics
   - **Add batch operations** for bulk inserts (10x performance improvement)
   - **Add connection optimization** parameters (timezone, timeouts)

### Phase 2: Extend inputs/ Managers & Authentication
1. **Add database parameters** to existing Manager constructors
   - Update `__init__` methods to accept `use_database` and `user_id`
   - Initialize `DatabaseClient` conditionally
   - **Add migration state detection** (`_should_use_database()` method)
   - Keep existing file-based logic unchanged

2. **Implement database operations** in DatabaseClient
   - Start with basic CRUD operations with transaction support
   - Focus on `get_portfolio()` and `save_portfolio()` first
   - Add connection pooling and proper resource management
   - **Add authentication methods** (`create_session`, `get_user_by_session`, `delete_expired_sessions`)
   - **Add data validation layer** for all database operations

3. **Update authentication system**
   - Create `DatabaseAuthManager` class
   - Replace in-memory `USERS` and `USER_SESSIONS` with database calls
   - Update `routes/auth.py` to use database-backed authentication
   - Add session cleanup background task

4. **Add dual-mode methods** to each manager
   - Portfolio loading with cash mapping and fallback mechanisms
   - Risk limits management with database/file fallback
   - Returns calculation with database support
   - File management with database fallback

5. **Update Plaid integration for database mode**
   - Modify `routes/plaid.py` to detect database mode
   - Implement `convert_plaid_df_to_database()` function
   - Add fallback to YAML mode on database errors
   - Update user_id handling for database user mapping

6. **Test file mode** - ensure no regressions
   - All existing tests should pass
   - No changes to existing functionality
   - **Add data validation tests** for migration consistency

### Phase 3: Update Manager Initialization
1. **Update global manager instances** in `inputs/__init__.py`
   ```python
   # Old
   portfolio_manager = PortfolioManager()
   
   # New
   USE_DATABASE = os.getenv("USE_DATABASE", "false").lower() == "true"
   portfolio_manager = PortfolioManager(use_database=USE_DATABASE)
   ```

2. **Add user_id parameter** to manager functions
   - Optional parameter, defaults to None for file mode
   - Pass through from Flask routes when available

3. **Update Flask routes** to pass user_id when in database mode
   - Extract user_id from authentication context
   - Pass to all manager function calls

4. **Test database mode** - ensure same data objects returned
   - Compare PortfolioData objects from both modes
   - Ensure identical risk analysis results

### Phase 4: AI Context Features
1. **Add user preferences** storage and retrieval
   - Store risk tolerance, investment goals, constraints
   - Retrieve for AI context in recommendations

2. **Add conversation history** storage
   - Track key insights and action items
   - Provide context for future conversations

3. **Create AI context functions**
   - Aggregate user preferences and history
   - Format for Claude function context

4. **Test AI integration** with memory/context
   - Verify personalized recommendations
   - Test conversation continuity

## Key Implementation Details

### Environment Configuration
```bash
# Development (files)
USE_DATABASE=false

# Production (database)
USE_DATABASE=true
DATABASE_URL=postgresql://user:pass@host:5432/risk_db
# or individual components:
DB_HOST=localhost
DB_PORT=5432
DB_NAME=risk_module_db
DB_USER=risk_user
DB_PASSWORD=your_password
```

### Function Updates
**Before:**
```python
def run_portfolio_analysis():
    portfolio_manager = PortfolioManager()
    portfolio = portfolio_manager.load_portfolio_data("default")
    return analyze_risk(portfolio)
```

**After:**
```python
def run_portfolio_analysis(user_id=None):
    # Initialize manager with dual-mode support
    portfolio_manager = PortfolioManager(use_database=USE_DATABASE, user_id=user_id)
    portfolio = portfolio_manager.load_portfolio_data("default")
    return analyze_risk(portfolio)  # Same analysis function!
```

### Architecture Preservation
- **PortfolioData, Position, RiskLimits objects stay identical**
- **All business logic functions unchanged**
- **services/ layer unchanged** - continues to work with data objects and create temporary YAML files
- **Core risk engine unchanged** - continues to read YAML files (via existing service layer pattern)
- **Only inputs/ managers get dual-mode capability**

### Service Layer Integration (Existing Pattern Preserved)
The current service layer already handles the PortfolioData → YAML conversion perfectly:

```python
# Current Pattern (services/portfolio_service.py):
def analyze_portfolio(self, portfolio_data: PortfolioData) -> RiskAnalysisResult:
    # 1. Create temporary YAML file from PortfolioData object
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as temp_file:
        portfolio_data.to_yaml(temp_file.name)  # Convert data object to YAML
        temp_portfolio_file = temp_file.name
    
    # 2. Call core function with temp file path
    result_data = run_portfolio(temp_portfolio_file, return_data=True)
    
    # 3. Clean up temp file
    os.unlink(temp_portfolio_file)
```

**Database Migration Data Flow:**
```
Database → inputs/portfolio_manager → PortfolioData → services/portfolio_service → temp YAML → core functions
```

**Why This Works Perfectly:**
✅ **No core function changes** - they continue to work with YAML files
✅ **Service layer abstraction preserved** - it handles PortfolioData → YAML conversion
✅ **Database migration is isolated** - only affects the inputs/ layer
✅ **Existing caching and validation work** - service layer features unchanged
✅ **Temporary files are stateless** - no conflicts between concurrent analyses
✅ **Clean and isolated** - files are automatically cleaned up after each analysis

### Input Format Support
The system handles **two distinct data types** with separate storage:

**1. Real Portfolios (from Plaid/brokers) → Database:**
```yaml
portfolio_input:
  NVDA:
    shares: 25.0        # Stored in positions.shares
  DSU:
    shares: 1410.9007   # Stored in positions.shares
  CUR:USD:
    dollars: -5078.62   # Stored in positions.dollars (original ticker)
```

**2. Scenarios (what-if analysis) → Database:**
```yaml
portfolio_input:
  AAPL:
    weight: 0.30        # Stored in scenario_positions.target_weight
  MSFT:
    weight: 0.25        # Stored in scenario_positions.target_weight
```

**Processing Flow:**
1. **Real portfolios**: shares/dollars → database → cash mapping → `standardize_portfolio_input()` → weights
2. **Scenarios**: weights → database → direct use in analysis
3. **Risk engine processes normalized weights**
4. **User sees original format** preserved in appropriate table

### Database Connection Best Practices
```python
import psycopg2
from psycopg2 import pool
import os

class DatabaseClient:
    def __init__(self):
        self.connection_pool = self._create_connection_pool()
    
    def _create_connection_pool(self):
        """Create connection pool for performance"""
        return psycopg2.pool.SimpleConnectionPool(
            1, 20,  # min=1, max=20 connections
            host=os.getenv("DB_HOST", "localhost"),
            database=os.getenv("DB_NAME", "risk_module_db"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD"),
            port=os.getenv("DB_PORT", 5432)
        )
    
    def get_connection(self):
        """Get connection from pool"""
        return self.connection_pool.getconn()
    
    def return_connection(self, connection):
        """Return connection to pool"""
        self.connection_pool.putconn(connection)
```

## Testing Strategy

### Unit Tests
```python
# Test dual-mode functionality
def test_portfolio_manager_dual_mode():
    # Test file mode
    file_manager = PortfolioManager(use_database=False)
    file_portfolio = file_manager.load_portfolio_data("test")
    
    # Test database mode
    db_manager = PortfolioManager(use_database=True, user_id=1)
    db_portfolio = db_manager.load_portfolio_data("test")
    
    # Should return identical PortfolioData objects
    assert file_portfolio.portfolio_input == db_portfolio.portfolio_input
    assert file_portfolio.start_date == db_portfolio.start_date

# Test migration state detection
def test_migration_state_detection():
    # Test auto-detection works correctly
    manager = PortfolioManager(user_id="test_user")
    assert manager.use_database == expected_mode
    
    # Test CLI mode defaults to files
    cli_manager = PortfolioManager(user_id=None)
    assert cli_manager.use_database == False

# Test error handling and fallback
def test_database_fallback():
    manager = PortfolioManager(use_database=True, user_id=1)
    
    # Mock database failure
    with patch.object(manager.db_client, 'get_portfolio', side_effect=DatabaseError):
        # Should fallback to file mode
        portfolio = manager.load_portfolio_data("test")
        assert portfolio is not None
```

### Integration Tests
- Test existing functions work with updated managers
- Test services/ layer unchanged with dual-mode managers
- Test AI context retrieval through managers
- Test conversation storage through managers

### Migration Tests
```python
# Test data consistency validation
def test_migration_data_consistency():
    # Load same data from both sources
    file_data = load_from_file("test_portfolio.yaml")
    db_data = load_from_database("test_portfolio", user_id=1)
    
    # Validate consistency
    validate_portfolio_data_consistency(file_data, db_data)

# Test cash mapping validation
def test_cash_mapping_validation():
    original_positions = [
        {"ticker": "CUR:USD", "dollars": 1000, "position_type": "cash", "cash_currency": "USD"},
        {"ticker": "NVDA", "shares": 10, "dollars": 2000}
    ]
    
    # Mock cash_map.yaml content
    import tempfile
    import yaml
    
    cash_map_content = {
        "proxy_by_currency": {"USD": "SGOV", "EUR": "ESTR", "GBP": "IB01"},
        "alias_to_currency": {"CUR:USD": "USD", "USD CASH": "USD"}
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(cash_map_content, f)
        temp_yaml_path = f.name
    
    try:
        # Test that cash mapping preserves total dollar values
        mapped_input = {"SGOV": {"dollars": 1000}, "NVDA": {"dollars": 2000}}
        validate_cash_mapping(original_positions, mapped_input, yaml_path=temp_yaml_path)
        
        # Test validation catches mismatched totals
        invalid_mapped = {"SGOV": {"dollars": 999}, "NVDA": {"dollars": 2000}}
        with pytest.raises(AssertionError):
            validate_cash_mapping(original_positions, invalid_mapped, yaml_path=temp_yaml_path)
    finally:
        os.unlink(temp_yaml_path)

# Test user isolation
def test_user_isolation():
    # User A creates portfolio
    manager_a = PortfolioManager(use_database=True, user_id="user_a")
    manager_a.save_portfolio_data(portfolio_data, "test")
    
    # User B should not see User A's data
    manager_b = PortfolioManager(use_database=True, user_id="user_b")
    with pytest.raises(PortfolioNotFoundError):
        manager_b.load_portfolio_data("test")
```

### Plaid Integration Tests
```python
# Test Plaid database integration
def test_plaid_database_integration():
    # Mock Plaid data with original cash identifiers
    mock_df = pd.DataFrame([
        {"ticker": "CUR:USD", "value": 1000, "quantity": 1000},
        {"ticker": "NVDA", "value": 2000, "quantity": 10}
    ])
    
    # Test database storage preserves original identifiers
    convert_plaid_df_to_database(mock_df, user_id="test_user")
    
    # Load and verify original identifiers stored
    manager = PortfolioManager(use_database=True, user_id="test_user")
    raw_positions = manager.db_client.get_portfolio_positions("test_user", "plaid_import")
    
    # Should have original CUR:USD, not mapped SGOV
    assert any(pos["ticker"] == "CUR:USD" for pos in raw_positions)
    
    # Test cash mapping applied at analysis time
    portfolio_data = manager.load_portfolio_data("plaid_import")
    assert "SGOV" in portfolio_data.portfolio_input  # Should be mapped
    assert "CUR:USD" not in portfolio_data.portfolio_input  # Should be mapped away

# Test Plaid route dual-mode switching
def test_plaid_route_database_mode():
    # Test database mode
    with patch.dict(os.environ, {"USE_DATABASE": "true"}):
        response = client.post("/plaid/import", json={"user_id": "test_user"})
        assert response.status_code == 200
        
        # Verify data stored in database
        manager = PortfolioManager(use_database=True, user_id="test_user")
        portfolio = manager.load_portfolio_data("plaid_import")
        assert portfolio is not None
```

### Performance Tests
```python
# Test database query performance benchmarks
def test_database_query_performance():
    start_time = time.time()
    
    # Test portfolio loading performance
    manager = PortfolioManager(use_database=True, user_id="test_user")
    portfolio = manager.load_portfolio_data("test")
    
    load_time = time.time() - start_time
    assert load_time < 0.1  # Should load within 100ms (95th percentile target)
    
# Test batch operations performance
def test_batch_operations_performance():
    # Test bulk insert performance
    positions = [
        {"user_id": 1, "ticker": f"STOCK_{i}", "shares": 100, "position_type": "stock"}
        for i in range(1000)
    ]
    
    start_time = time.time()
    db_client = DatabaseClient()
    db_client.batch_save_positions(positions, portfolio_id=1)
    
    batch_time = time.time() - start_time
    assert batch_time < 1.0  # 1000 positions should save in < 1 second
    
    # Compare with individual inserts (should be much slower)
    individual_start = time.time()
    for pos in positions[:10]:  # Test smaller sample
        db_client.save_single_position(pos, portfolio_id=1)
    individual_time = time.time() - individual_start
    
    # Batch should be significantly faster per position
    assert batch_time / len(positions) < individual_time / 10

# Test connection pool efficiency and limits
def test_connection_pool_efficiency():
    # Test connection pool doesn't exceed limits
    db_client = DatabaseClient()
    connections = []
    
    try:
        # Try to exhaust connection pool
        for i in range(25):  # More than pool size
            try:
                conn = db_client.get_connection_with_timeout(timeout=1)
                connections.append(conn)
            except DatabaseError as e:
                # Should get pool exhausted error
                assert "Connection pool exhausted" in str(e)
                break
    finally:
        # Clean up connections
        for conn in connections:
            db_client.put_connection(conn)
    
    # Should not be able to get more connections than pool size
    assert len(connections) <= 20  # Production pool size

# Test concurrent user handling
def test_concurrent_user_handling():
    import threading
    import concurrent.futures
    
    def load_portfolio(user_id):
        manager = PortfolioManager(use_database=True, user_id=user_id)
        start_time = time.time()
        portfolio = manager.load_portfolio_data("test")
        load_time = time.time() - start_time
        return load_time, portfolio is not None
    
    # Test 10 concurrent users
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(load_portfolio, f"user_{i}")
            for i in range(10)
        ]
        
        results = [future.result() for future in futures]
    
    # All should succeed
    assert all(success for _, success in results)
    
    # All should meet performance targets
    load_times = [load_time for load_time, _ in results]
    assert max(load_times) < 0.5  # Even under load, should be < 500ms
    assert sum(load_times) / len(load_times) < 0.2  # Average < 200ms

# Test performance monitoring
def test_performance_monitoring():
    # Test that monitoring decorator works
    db_client = DatabaseClient()
    
    with patch('your_monitoring_system.track_metric') as mock_track:
        portfolio = db_client.get_portfolio_positions("test_user", "test_portfolio")
        
        # Should track both duration and success metrics
        mock_track.assert_any_call("database.portfolio_load.duration", mock.ANY)
        mock_track.assert_any_call("database.portfolio_load.success", 1)

# Test memory usage under load
def test_memory_usage():
    import psutil
    import gc
    
    # Get baseline memory usage
    gc.collect()
    baseline_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
    
    # Create multiple managers (simulating concurrent users)
    managers = []
    for i in range(50):
        manager = PortfolioManager(use_database=True, user_id=f"user_{i}")
        managers.append(manager)
    
    # Check memory usage
    current_memory = psutil.Process().memory_info().rss / 1024 / 1024  # MB
    memory_increase = current_memory - baseline_memory
    
    # Should not use excessive memory (each connection ~8MB)
    expected_memory = 50 * 8  # 50 users × 8MB per connection
    assert memory_increase < expected_memory * 1.5  # 50% buffer for overhead

# Test caching effectiveness and integration
def test_cache_integration():
    # Ensure database mode doesn't break price caching
    start_time = time.time()
    price_data = fetch_monthly_close("AAPL")
    first_fetch_time = time.time() - start_time
    
    # Test cache hit (should be much faster)
    start_time = time.time()
    cached_price_data = fetch_monthly_close("AAPL")
    cache_hit_time = time.time() - start_time
    
    assert cached_price_data.equals(price_data)
    assert cache_hit_time < first_fetch_time / 10  # Cache should be 10x faster
    
# Test database maintenance performance
def test_database_maintenance():
    db_client = DatabaseClient()
    
    # Test vacuum performance
    start_time = time.time()
    db_client.execute_maintenance("vacuum")
    vacuum_time = time.time() - start_time
    
    # Should complete reasonably quickly
    assert vacuum_time < 30  # 30 seconds for small database
    
    # Test statistics update
    stats = db_client.get_database_stats()
    assert "active_connections" in stats
    assert "slow_queries" in stats
```

### Validation Tests
```python
# Test data validation layer
def test_data_validation_layer():
    # Test invalid position data
    invalid_positions = [
        {"ticker": "AAPL"},  # Missing shares/dollars
        {"user_id": "test"},  # Missing ticker
    ]
    
    with pytest.raises(ValidationError):
        db_client.save_portfolio_positions(invalid_positions, portfolio_id=1)

# Test cash mapping validation with dynamic loading
def test_cash_mapping_validation():
    original_positions = [
        {"ticker": "CUR:USD", "dollars": 1000, "position_type": "cash", "cash_currency": "USD"},
        {"ticker": "CUR:EUR", "dollars": 500, "position_type": "cash", "cash_currency": "EUR"}
    ]
    
    # Use real cash_map.yaml if available, otherwise mock it
    import tempfile
    import yaml
    from pathlib import Path
    
    if Path("cash_map.yaml").is_file():
        yaml_path = "cash_map.yaml"
    else:
        # Mock cash_map.yaml content for testing
        cash_map_content = {
            "proxy_by_currency": {"USD": "SGOV", "EUR": "ESTR", "GBP": "IB01"},
            "alias_to_currency": {"CUR:USD": "USD", "CUR:EUR": "EUR"}
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(cash_map_content, f)
            yaml_path = f.name
    
    try:
        # Test valid mapping (should not raise error)
        mapped_input = {"SGOV": {"dollars": 1000}, "ESTR": {"dollars": 500}}
        validate_cash_mapping(original_positions, mapped_input, yaml_path=yaml_path)
        
        # Test invalid mapping (should raise error for mismatched totals)
        invalid_mapped = {"SGOV": {"dollars": 999}, "ESTR": {"dollars": 500}}
        with pytest.raises(AssertionError):
            validate_cash_mapping(original_positions, invalid_mapped, yaml_path=yaml_path)
    finally:
        # Clean up temporary file if we created one
        if not Path("cash_map.yaml").is_file():
            os.unlink(yaml_path)
```

## Migration Path

### Phase 1: Deploy File Mode (Zero Risk)
1. **Deploy with USE_DATABASE=false** (no changes to users)
2. **Test all existing functionality** works unchanged
3. **Verify no performance regressions**

### Phase 2: Database Infrastructure
1. **Set up production database** (AWS RDS recommended)
2. **Run migration scripts** to convert existing data
3. **Test database mode** with test users

### Phase 3: Gradual User Migration
1. **Migrate power users** to database mode for testing
2. **Monitor performance** and error rates
3. **Gradually migrate all users** once stable

### Phase 4: Cleanup
1. **Remove file mode** after full migration
2. **Clean up temporary migration code**
3. **Optimize database performance**

## Success Criteria

### Functional Requirements
- ✅ All existing functions work unchanged
- ✅ Same data objects returned from both sources
- ✅ Multi-user support enabled
- ✅ AI context/memory functional
- ✅ Cash mapping works correctly
- ✅ User isolation enforced

### Non-Functional Requirements
- ✅ Zero breaking changes during migration
- ✅ Performance maintained or improved
- ✅ Data integrity preserved
- ✅ Error handling robust
- ✅ Rollback capability available

### Technical Requirements
- ✅ Database connection pooling
- ✅ Transaction support
- ✅ Proper indexing for performance
- ✅ Audit trail functionality
- ✅ Backup and recovery procedures

## Critical Implementation Notes

### 1. Data Objects Must Remain Identical
The `PortfolioData`, `StockData`, and `RiskLimits` objects from `core/data_objects.py` must return identical data regardless of source (file vs database). This ensures zero breaking changes.

### 2. Cash Mapping Timing
**Critical**: Cash mapping (`CUR:USD` → `SGOV`) must happen at analysis time, not storage time. Store original identifiers in database, apply mapping in `_apply_cash_mapping()`.

### 3. Database-Backed Authentication System
Replace in-memory user management with database-backed authentication for production scalability:

```python
# Enhanced Database Schema with Session Management
CREATE TABLE user_sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    last_accessed TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX idx_user_sessions_expires ON user_sessions(expires_at);

# Database-Backed Authentication Manager
class DatabaseAuthManager:
    def __init__(self, db_client):
        self.db = db_client
    
    def authenticate_google_user(self, google_user_info):
        """Create or update user in database"""
        google_user_id = google_user_info['user_id']  # Google 'sub' field
        
        # Get or create user in database
        user_id = self.db.get_or_create_user_id(google_user_id)
        
        # Update user info
        self.db.update_user_info(user_id, {
            'email': google_user_info['email'],
            'name': google_user_info['name'],
            'last_login': datetime.now()
        })
        
        return user_id
    
    def create_session(self, user_id):
        """Create persistent session in database"""
        session_id = secrets.token_urlsafe(32)
        expires_at = datetime.now() + timedelta(days=7)
        
        self.db.create_session(session_id, user_id, expires_at)
        return session_id
    
    def get_current_user(self, session_id):
        """Get user from database session"""
        return self.db.get_user_by_session(session_id)
    
    def cleanup_expired_sessions(self):
        """Remove expired sessions (run periodically)"""
        self.db.delete_expired_sessions()

# Updated Authentication Flow
google_user_id = "108234567890123456789"  # From Google 'sub'
user_id = auth_manager.authenticate_google_user(google_user_info)
session_id = auth_manager.create_session(user_id)
portfolio_manager = PortfolioManager(use_database=True, user_id=user_id)
```

**Benefits of Database-Backed Authentication:**
✅ **Persistent sessions** - Users stay logged in across server restarts
✅ **Scalable** - Multiple app instances can share same user database  
✅ **Better UX** - Users don't get logged out unexpectedly
✅ **User history** - Track user behavior, preferences, conversation history
✅ **Production ready** - Standard approach for multi-user systems

### 4. Transaction Management
All database operations that modify multiple tables must use transactions:
```python
with connection.cursor() as cursor:
    try:
        cursor.execute("BEGIN")
        # Multiple operations
        cursor.execute("COMMIT")
    except Exception as e:
        cursor.execute("ROLLBACK")
        raise e
```

### 5. Error Handling Strategy
- **Database unavailable**: Fall back to file mode with warning
- **User not found**: Create new user automatically
- **Data corruption**: Log error, return empty portfolio
- **Connection timeout**: Retry with exponential backoff

## Common Pitfalls to Avoid

1. **Don't modify core risk engine** - it should continue reading YAML files
2. **Don't change data object interfaces** - maintain exact compatibility
3. **Don't apply cash mapping at storage time** - apply at analysis time
4. **Don't skip transaction handling** - data consistency is critical
5. **Don't forget user isolation** - always filter by user_id
6. **Don't ignore performance** - use connection pooling and proper indexing

## Debugging Tips

### Database Connection Issues
```python
# Test connection
try:
    connection = db_client.get_connection()
    cursor = connection.cursor()
    cursor.execute("SELECT 1")
    print("✅ Database connection successful")
except Exception as e:
    print(f"❌ Database connection failed: {e}")
```

### Data Comparison
```python
# Compare file vs database results
file_portfolio = file_manager.load_portfolio_data("test")
db_portfolio = db_manager.load_portfolio_data("test")

print("File portfolio:", file_portfolio.portfolio_input)
print("DB portfolio:", db_portfolio.portfolio_input)
print("Match:", file_portfolio.portfolio_input == db_portfolio.portfolio_input)
```

This implementation plan now provides comprehensive guidance for another Claude to successfully implement the database migration while preserving all existing functionality. 

# Implementation Checklist for Developer

## 🚀 Pre-Implementation Setup

### 1. Environment Setup ✅ **COMPLETED**
```bash
# ✅ PostgreSQL 17.5 is already installed at /Library/PostgreSQL/17/bin/
# ✅ Database 'risk_module_db' is already created
# ✅ Trust authentication is configured (no password required)
# ✅ Python dependencies are already installed:
#     - psycopg2-binary==2.9.10
#     - python-dotenv==1.1.0

# Connection string ready to use:
DATABASE_URL=postgresql://postgres@localhost:5432/risk_module_db
```

**See `DATABASE_SETUP_COMPLETE.md` for full setup details.**

### 2. Database Connection Details for Implementation
```python
# Use this connection configuration in your code:
DATABASE_URL = "postgresql://postgres@localhost:5432/risk_module_db"
DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "risk_module_db"
DB_USER = "postgres"
DB_PASSWORD = None  # Trust authentication - no password required
```

### 3. Create Required Files
- [ ] `db_schema.sql` - Complete database schema
- [x] **Environment variables** ✅ **COMPLETED** - Database config added to existing `.env` file
- [ ] `inputs/database_client.py` - Database client implementation
- [ ] `inputs/exceptions.py` - Custom exception classes

### 4. Update Existing Files
- [ ] `requirements.txt` - Add database dependencies *(psycopg2-binary and python-dotenv already installed)*
- [ ] `inputs/__init__.py` - Update manager initialization
- [ ] `app.py` - Update authentication system

## 🔧 Implementation Order

**🎯 IMPORTANT: Database setup is complete!** PostgreSQL 17.5 is installed, `risk_module_db` database is created, and Python dependencies are installed. You can start directly with code implementation.

### Phase 1: Database Foundation
1. [ ] Create `db_schema.sql` with all tables and indexes
2. [ ] Create `inputs/exceptions.py` with custom exceptions
3. [ ] Create `inputs/database_client.py` skeleton
4. [ ] Implement `DatabaseClient._connect()` method
5. [ ] Add basic connection pooling
6. [x] **Database and dependencies setup** ✅ **COMPLETED**
   - PostgreSQL 17.5 installed and running
   - Database `risk_module_db` created
   - Python dependencies installed
   - Connection tested and working

### Phase 2: Core Database Operations
1. [ ] Implement `DatabaseClient.get_user_id()` method
2. [ ] Implement `DatabaseClient.get_portfolio_positions()` method
3. [ ] Implement `DatabaseClient.save_portfolio_positions()` method
4. [ ] Add transaction support and error handling
5. [ ] Test basic CRUD operations

### Phase 3: Manager Updates
1. [ ] Update `PortfolioManager.__init__()` for dual-mode
2. [ ] Implement `PortfolioManager._should_use_database()` method
3. [ ] Implement `PortfolioManager._load_portfolio_from_database()` method
4. [ ] Add fallback mechanisms and error handling
5. [ ] Test dual-mode functionality

### Phase 4: Authentication System
1. [ ] Create `user_sessions` table
2. [ ] Implement `DatabaseAuthManager` class
3. [ ] Update `routes/auth.py` for database sessions
4. [ ] Add session cleanup mechanisms
5. [ ] Test authentication flow

### Phase 5: Plaid Integration
1. [ ] Update `routes/plaid.py` for database mode
2. [ ] Implement `convert_plaid_df_to_database()` function
3. [ ] Add database/file mode detection
4. [ ] Test Plaid integration with database

## ⚠️ Common Pitfalls to Avoid

### 1. Database Connection Issues
```python
# DON'T: Create new connection each time
conn = psycopg2.connect(DATABASE_URL)

# DO: Use connection pool
conn = self.connection_pool.getconn()
try:
    # Use connection
finally:
    self.connection_pool.putconn(conn)
```

### 2. Transaction Management
```python
# DON'T: Forget to handle transactions
cur.execute("INSERT INTO...")
cur.execute("UPDATE...")  # If this fails, INSERT is still committed

# DO: Use proper transaction blocks
with conn:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO...")
        cur.execute("UPDATE...")
        # Auto-commit on success, rollback on exception
```

### 3. Import Circular Dependencies
```python
# DON'T: Import managers in database_client
from inputs.portfolio_manager import PortfolioManager  # Circular import!

# DO: Use type hints for forward references
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from inputs.portfolio_manager import PortfolioManager
```

### 4. Migration State Conflicts
```python
# DON'T: Assume only one data source exists
def _should_use_database(self, user_id):
    if self._user_has_database_data(user_id):
        return True
    # What if user has BOTH file and database data?

# DO: Handle conflict resolution
def _should_use_database(self, user_id):
    has_db = self._user_has_database_data(user_id)
    has_file = self._user_has_file_data(user_id)
    
    if has_db and has_file:
        # Conflict resolution strategy
        logger.warning(f"User {user_id} has both file and database data")
        return True  # Prefer database
    elif has_db:
        return True
    elif has_file:
        return False
    else:
        return True  # New users → database
```

## 🧪 Testing Strategy

### 1. Unit Tests First
```python
# Test database connection (connection already validated ✅)
def test_database_connection():
    client = DatabaseClient()
    assert client.connection_pool is not None

# Test dual-mode functionality
def test_portfolio_manager_dual_mode():
    # Test both modes return same data
    pass
```

### 2. Integration Tests
```python
# Test complete flow
def test_plaid_to_database_flow():
    # Mock Plaid data → database → portfolio load
    pass
```

### 3. Performance Tests
```python
# Test connection pool limits
def test_connection_pool_exhaustion():
    # Test what happens when pool is exhausted
    pass
```

## 📝 Validation Checklist

### Before Each Phase
- [ ] All tests pass
- [ ] No circular imports
- [ ] No hard-coded values
- [ ] Proper error handling
- [ ] Connection cleanup
- [ ] Transaction management

### Before Final Deployment
- [ ] Performance benchmarks met
- [ ] Migration state detection works
- [ ] Fallback mechanisms tested
- [ ] Data validation passes
- [ ] Authentication system works
- [ ] Plaid integration functional

## 🔍 Debugging Tips

### 1. Database Connection Issues
```python
# Add connection debugging
import logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

def _connect(self):
    logger.debug(f"Connecting to database: {DATABASE_URL}")
    # Connection logic
```

### 2. Migration State Debugging
```python
# Add state detection logging
def _should_use_database(self, user_id):
    has_db = self._user_has_database_data(user_id)
    has_file = self._user_has_file_data(user_id)
    logger.debug(f"User {user_id}: db={has_db}, file={has_file}")
    return has_db or not has_file
```

### 3. Performance Monitoring
```python
# Add timing to critical operations
import time
def load_portfolio_data(self, portfolio_name):
    start_time = time.time()
    try:
        result = self._load_portfolio_from_database(portfolio_name)
        load_time = time.time() - start_time
        logger.info(f"Portfolio load time: {load_time:.3f}s")
        return result
    except Exception as e:
        logger.error(f"Portfolio load failed after {time.time() - start_time:.3f}s: {e}")
        raise
```

## 📋 Final Implementation Validation

### 1. Functional Tests
- [ ] CLI mode still works (files)
- [ ] Web app works (database)
- [ ] Plaid integration works
- [ ] Google OAuth works
- [ ] Risk analysis produces same results

### 2. Performance Tests
- [ ] Portfolio load < 100ms
- [ ] Authentication < 25ms
- [ ] Connection pool efficiency
- [ ] No memory leaks

### 3. Data Integrity Tests
- [ ] Cash mapping preserves totals
- [ ] Migration consistency
- [ ] User data isolation
- [ ] Transaction atomicity

This implementation checklist should help avoid common pitfalls and ensure a smooth migration implementation.