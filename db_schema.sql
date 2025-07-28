-- ============================================================================
-- RISK MODULE DATABASE SCHEMA
-- ============================================================================
-- 
-- Database schema for multi-user portfolio risk analysis system
-- Supports dual-mode operation (database + file fallback)
-- 
-- Key Design Principles:
-- - Store original cash identifiers (CUR:USD), convert to proxies at analysis time
-- - Store quantities (shares for stocks/ETFs, cash amounts for cash) AND currency for all positions
-- - User isolation via user_id foreign keys
-- - Temporal tracking for audit trails
-- - Performance optimized with proper indexing
-- 
-- ============================================================================

-- Drop existing tables if they exist (for clean reinstall)
DROP TABLE IF EXISTS portfolio_changes CASCADE;
DROP TABLE IF EXISTS conversation_history CASCADE;
DROP TABLE IF EXISTS user_preferences CASCADE;
DROP TABLE IF EXISTS user_sessions CASCADE;
DROP TABLE IF EXISTS factor_proxies CASCADE;
DROP TABLE IF EXISTS risk_limits CASCADE;
DROP TABLE IF EXISTS scenario_positions CASCADE;
DROP TABLE IF EXISTS scenarios CASCADE;
DROP TABLE IF EXISTS positions CASCADE;
DROP TABLE IF EXISTS portfolios CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Users table - stores multi-provider authentication information
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255),
    tier VARCHAR(50) DEFAULT 'public',           -- 'public', 'registered', 'paid'
    
    -- Multi-provider auth support
    google_user_id VARCHAR(255) UNIQUE,          -- Google 'sub' field
    github_user_id VARCHAR(255) UNIQUE,          -- GitHub user ID
    apple_user_id VARCHAR(255) UNIQUE,           -- Apple Sign-In user ID
    auth_provider VARCHAR(50) NOT NULL DEFAULT 'google',  -- 'google', 'github', 'apple', 'api_key'
    
    -- API access support
    api_key_hash VARCHAR(255) UNIQUE,            -- For programmatic access
    api_key_expires_at TIMESTAMP,                -- API key expiration
    
    -- System fields
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Portfolios table - maps to PortfolioData structure
CREATE TABLE portfolios (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    start_date DATE NOT NULL,              -- From portfolio.yaml
    end_date DATE NOT NULL,                -- From portfolio.yaml
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, name)
);

-- Positions table - stores quantities with currency for all positions
-- 
-- Multi-currency design:
-- - Each position maintains its own currency (USD, EUR, GBP, etc.)
-- - Cash positions use standardized ticker format: CUR:USD, CUR:EUR, etc.
-- - No currency consolidation - each currency stored as separate position
-- - Database client extracts currency from ticker if missing (CUR:USD → USD)
--
-- Storage model:
-- - quantity field holds share count for equities, cash amount for cash positions
-- - type field determines how quantity is interpreted ("cash" vs "equity")
-- - Multiple sources can provide same ticker (Plaid + manual entry)
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    portfolio_id INTEGER REFERENCES portfolios(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(100) NOT NULL,          -- Stock symbol or cash identifier (CUR:USD, CUR:EUR)
    quantity DECIMAL(20,8) NOT NULL,       -- Shares for stocks/ETFs, cash amount for cash positions
    currency VARCHAR(10) NOT NULL,         -- Position currency (USD, EUR, GBP, JPY, etc.)
    type VARCHAR(20),                      -- Position type: "cash", "equity", "etf", "crypto", "bond"
    
    -- Cost basis and tax tracking
    cost_basis DECIMAL(20,8),              -- Average cost per share (NULL for cash positions)
    purchase_date DATE,                    -- For tax lot tracking
    
    -- Position metadata
    account_id VARCHAR(100),               -- Broker account identifier
    position_source VARCHAR(50),           -- Data source: "plaid", "manual", "csv_import", "api"
    position_status VARCHAR(20) DEFAULT 'active',  -- Status: "active", "closed", "pending"
    
    -- Analysis fields moved to separate tables for dynamic data
    
    -- System fields
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Constraints
    UNIQUE(portfolio_id, ticker, position_source)  -- Same ticker allowed from different sources
    -- Example: AAPL from Plaid + AAPL from manual entry = separate positions
);

-- Scenarios table - user-created what-if scenarios
CREATE TABLE scenarios (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    base_portfolio_id INT REFERENCES portfolios(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,                       -- "Aggressive Growth", "Tech Focus", etc.
    description TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    last_accessed TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, name)
);

-- Scenario positions table - target weights for scenarios
CREATE TABLE scenario_positions (
    id SERIAL PRIMARY KEY,
    scenario_id INT REFERENCES scenarios(id) ON DELETE CASCADE,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(100) NOT NULL,
    target_weight DECIMAL(8,6) NOT NULL,              -- Target allocation weights
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Risk limits table - maps to risk_limits.yaml structure
CREATE TABLE risk_limits (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    portfolio_id INT REFERENCES portfolios(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,                -- "Conservative", "Aggressive", "Custom_2024", etc.
    
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
    updated_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(user_id, portfolio_id, name)
);

-- Factor proxies table - maps to stock_factor_proxies in YAML (stock-specific)
-- 
-- Risk analysis uses factor models to decompose stock returns into systematic factors.
-- Each stock gets assigned proxy ETFs for different factor exposures:
-- - market_proxy: Broad market exposure (SPY, ACWX)
-- - momentum_proxy: Momentum factor exposure (MTUM, IMTM)  
-- - value_proxy: Value factor exposure (VTV, VLUE)
-- - industry_proxy: Industry-specific exposure (XLK, XLV, etc.)
-- - subindustry_peers: Array of similar companies for peer analysis
--
-- These proxies are used in factor regression: Stock_Return = α + β₁*Market + β₂*Momentum + β₃*Value + β₄*Industry + ε
CREATE TABLE factor_proxies (
    id SERIAL PRIMARY KEY,
    portfolio_id INT REFERENCES portfolios(id) ON DELETE CASCADE,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(100) NOT NULL,             -- Stock ticker this proxy set applies to
    market_proxy VARCHAR(20),                 -- Market factor proxy (SPY, ACWX)
    momentum_proxy VARCHAR(20),               -- Momentum factor proxy (MTUM, IMTM)
    value_proxy VARCHAR(20),                  -- Value factor proxy (VTV, VLUE)
    industry_proxy VARCHAR(20),               -- Industry factor proxy (XLK, XLV, XLF)
    subindustry_peers JSONB,                  -- Array of peer tickers for sub-industry analysis
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(portfolio_id, ticker)             -- One proxy set per stock per portfolio
);

-- Factor tracking table - defines which factors to analyze for each position
CREATE TABLE factor_tracking (
    id SERIAL PRIMARY KEY,
    portfolio_id INT REFERENCES portfolios(id) ON DELETE CASCADE,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(100),                      -- NULL for portfolio-level factor tracking
    factor_type VARCHAR(50) NOT NULL,         -- 'duration', 'rate_sensitivity', 'currency', 'commodity', 'volatility'
    factor_name VARCHAR(100) NOT NULL,        -- '10Y_treasury_duration', 'USD_exposure', 'oil_beta', 'VIX_sensitivity'
    
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- One tracking entry per position per factor
    UNIQUE(portfolio_id, ticker, factor_type, factor_name)
);

-- Expected returns table - for dynamic analysis parameters (insert-only versioning)
-- 
-- Stores expected return forecasts for portfolio optimization (max-return sizing, min-variance, etc.)
-- Uses insert-only versioning to preserve historical expectations for backtesting.
-- 
-- Versioning model:
-- - Updates create new records with updated effective_date, old records preserved
-- - Deletes are not allowed - preserves historical data for backtesting
-- - Query latest expectations: SELECT * FROM expected_returns WHERE effective_date = (SELECT MAX(effective_date) FROM expected_returns WHERE ticker = ?)
-- - Query historical expectations: Filter by effective_date range
--
-- Usage in optimization:
-- - Portfolio optimization uses latest expected returns for each ticker
-- - Backtesting compares actual vs expected returns using historical data
-- - Confidence levels help weight expectations in optimization algorithms
CREATE TABLE expected_returns (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(100) NOT NULL,             -- Stock ticker
    expected_return DECIMAL(8,4) NOT NULL,    -- Annual return as decimal (0.12 = 12%)
    effective_date DATE NOT NULL,             -- When this expectation was set (for versioning)
    data_source VARCHAR(50) DEFAULT 'calculated',  -- Source: 'user_input', 'calculated', 'market_data'
    confidence_level DECIMAL(3,2),           -- Confidence in forecast (0.0-1.0)
    created_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(ticker, effective_date)            -- One expectation per ticker per date
);

-- ============================================================================
-- AUTHENTICATION & SESSION MANAGEMENT
-- ============================================================================

-- User session management table
CREATE TABLE user_sessions (
    session_id VARCHAR(255) PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    last_accessed TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- AI CONTEXT & PREFERENCES
-- ============================================================================

-- User preferences table - for AI context and user settings
CREATE TABLE user_preferences (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    preference_type VARCHAR(50), -- 'risk_tolerance', 'goals', 'constraints'
    preference_value TEXT,
    confidence_level DECIMAL(3,2), -- 0.0 to 1.0
    source VARCHAR(50), -- 'direct_input', 'inferred', 'conversation'
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Conversation history table - for AI memory and context
CREATE TABLE conversation_history (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    topic VARCHAR(100),
    key_insights TEXT,
    action_items TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- AUDIT & TEMPORAL TRACKING
-- ============================================================================

-- Portfolio changes table - temporal tracking with position linking
CREATE TABLE portfolio_changes (
    id SERIAL PRIMARY KEY,
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    portfolio_id INT REFERENCES portfolios(id) ON DELETE CASCADE,
    position_id INT REFERENCES positions(id) ON DELETE SET NULL,  -- Direct link to position
    change_type VARCHAR(50), -- 'position_added', 'position_removed', 'shares_changed', 'cost_basis_updated'
    old_value JSONB,         -- Previous position state
    new_value JSONB,         -- New position state
    reason TEXT,             -- Why the change was made
    changed_by VARCHAR(50),  -- 'user', 'plaid_sync', 'system', 'api'
    created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- PERFORMANCE INDEXES
-- ============================================================================

-- User-related indexes
CREATE INDEX idx_users_google_user_id ON users(google_user_id);
CREATE INDEX idx_users_github_user_id ON users(github_user_id);
CREATE INDEX idx_users_apple_user_id ON users(apple_user_id);
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_auth_provider ON users(auth_provider);
CREATE INDEX idx_users_api_key_hash ON users(api_key_hash);
CREATE INDEX idx_users_api_key_expires ON users(api_key_expires_at);
CREATE INDEX idx_users_created_at ON users(created_at);

-- Portfolio-related indexes
CREATE INDEX idx_portfolios_user_id ON portfolios(user_id);
CREATE INDEX idx_portfolios_user_name ON portfolios(user_id, name);
CREATE INDEX idx_portfolios_updated_at ON portfolios(updated_at);

-- Position-related indexes
CREATE INDEX idx_positions_user_id ON positions(user_id);
CREATE INDEX idx_positions_portfolio_id ON positions(portfolio_id);
CREATE INDEX idx_positions_user_portfolio ON positions(user_id, portfolio_id);
CREATE INDEX idx_positions_ticker ON positions(ticker);
CREATE INDEX idx_positions_currency ON positions(currency);
CREATE INDEX idx_positions_type ON positions(type);
CREATE INDEX idx_positions_account_id ON positions(account_id);
CREATE INDEX idx_positions_source ON positions(position_source);
CREATE INDEX idx_positions_status ON positions(position_status);
CREATE INDEX idx_positions_purchase_date ON positions(purchase_date);
CREATE INDEX idx_positions_created_at ON positions(created_at);

-- Scenario-related indexes
CREATE INDEX idx_scenarios_user_id ON scenarios(user_id);
CREATE INDEX idx_scenarios_base_portfolio ON scenarios(base_portfolio_id);
CREATE INDEX idx_scenarios_last_accessed ON scenarios(last_accessed);

CREATE INDEX idx_scenario_positions_scenario_id ON scenario_positions(scenario_id);
CREATE INDEX idx_scenario_positions_user_id ON scenario_positions(user_id);

-- Risk limits indexes
CREATE INDEX idx_risk_limits_user_id ON risk_limits(user_id);
CREATE INDEX idx_risk_limits_portfolio_id ON risk_limits(portfolio_id);
CREATE INDEX idx_risk_limits_user_portfolio ON risk_limits(user_id, portfolio_id);
CREATE INDEX idx_risk_limits_name ON risk_limits(name);

-- Factor proxies indexes
CREATE INDEX idx_factor_proxies_portfolio_id ON factor_proxies(portfolio_id);
CREATE INDEX idx_factor_proxies_user_id ON factor_proxies(user_id);
CREATE INDEX idx_factor_proxies_ticker ON factor_proxies(ticker);

-- Factor tracking indexes
CREATE INDEX idx_factor_tracking_portfolio_id ON factor_tracking(portfolio_id);
CREATE INDEX idx_factor_tracking_user_id ON factor_tracking(user_id);
CREATE INDEX idx_factor_tracking_ticker ON factor_tracking(ticker);
CREATE INDEX idx_factor_tracking_factor_type ON factor_tracking(factor_type);
CREATE INDEX idx_factor_tracking_factor_name ON factor_tracking(factor_name);
CREATE INDEX idx_factor_tracking_portfolio_factor ON factor_tracking(portfolio_id, factor_type);
CREATE INDEX idx_factor_tracking_ticker_factor ON factor_tracking(ticker, factor_type);

-- Expected returns indexes
CREATE INDEX idx_expected_returns_ticker ON expected_returns(ticker);
CREATE INDEX idx_expected_returns_effective_date ON expected_returns(effective_date);
CREATE INDEX idx_expected_returns_ticker_date ON expected_returns(ticker, effective_date);
CREATE INDEX idx_expected_returns_data_source ON expected_returns(data_source);

-- Session management indexes
CREATE INDEX idx_user_sessions_user_id ON user_sessions(user_id);
CREATE INDEX idx_user_sessions_expires ON user_sessions(expires_at);
CREATE INDEX idx_user_sessions_last_accessed ON user_sessions(last_accessed);

-- AI context indexes
CREATE INDEX idx_user_preferences_user_id ON user_preferences(user_id);
CREATE INDEX idx_user_preferences_type ON user_preferences(preference_type);
CREATE INDEX idx_conversation_history_user_id ON conversation_history(user_id);
CREATE INDEX idx_conversation_history_user_created ON conversation_history(user_id, created_at);

-- Audit trail indexes
CREATE INDEX idx_portfolio_changes_user_id ON portfolio_changes(user_id);
CREATE INDEX idx_portfolio_changes_portfolio_id ON portfolio_changes(portfolio_id);
CREATE INDEX idx_portfolio_changes_position_id ON portfolio_changes(position_id);
CREATE INDEX idx_portfolio_changes_change_type ON portfolio_changes(change_type);
CREATE INDEX idx_portfolio_changes_changed_by ON portfolio_changes(changed_by);
CREATE INDEX idx_portfolio_changes_created_at ON portfolio_changes(created_at);

-- ============================================================================
-- UTILITY FUNCTIONS
-- ============================================================================

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers for automatic updated_at updates
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_portfolios_updated_at BEFORE UPDATE ON portfolios
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_positions_updated_at BEFORE UPDATE ON positions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_scenario_positions_updated_at BEFORE UPDATE ON scenario_positions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_risk_limits_updated_at BEFORE UPDATE ON risk_limits
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_factor_proxies_updated_at BEFORE UPDATE ON factor_proxies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_factor_tracking_updated_at BEFORE UPDATE ON factor_tracking
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_preferences_updated_at BEFORE UPDATE ON user_preferences
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Note: expected_returns table uses insert-only versioning by effective_date, no updated_at needed

-- Enforce insert-only behavior for expected_returns table
CREATE OR REPLACE FUNCTION prevent_expected_returns_modifications()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'Updates not allowed on expected_returns table. Insert new record with updated effective_date instead.';
    END IF;
    
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Deletes not allowed on expected_returns table. This preserves historical expectations for backtesting.';
    END IF;
    
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER prevent_expected_returns_updates
    BEFORE UPDATE ON expected_returns
    FOR EACH ROW EXECUTE FUNCTION prevent_expected_returns_modifications();

CREATE TRIGGER prevent_expected_returns_deletes
    BEFORE DELETE ON expected_returns
    FOR EACH ROW EXECUTE FUNCTION prevent_expected_returns_modifications();

-- ============================================================================
-- SAMPLE DATA FOR TESTING
-- ============================================================================

-- Insert sample user (matches the current user from logs)
INSERT INTO users (google_user_id, email, name, tier, auth_provider) VALUES
('google_sub_hc', 'hc@henrychien.com', 'Henry Chien', 'registered', 'google');

-- Insert sample portfolio
INSERT INTO portfolios (user_id, name, start_date, end_date) VALUES
(1, 'main', '2020-01-01', '2024-12-31');

-- Insert sample positions (based on current portfolio.yaml structure)
INSERT INTO positions (portfolio_id, user_id, ticker, quantity, currency, type, position_source, account_id, cost_basis, purchase_date) VALUES
(1, 1, 'NVDA', 25.0, 'USD', 'equity', 'plaid', 'account_main', 850.50, '2023-01-15'),
(1, 1, 'DSU', 1410.9007, 'USD', 'etf', 'plaid', 'account_main', 12.75, '2023-02-01'),
(1, 1, 'EQT', 84.6885, 'USD', 'equity', 'plaid', 'account_main', 32.25, '2023-03-10'),
(1, 1, 'IGIC', 6.0, 'USD', 'equity', 'plaid', 'account_main', 145.00, '2023-01-20'),
(1, 1, 'IT', 19.7951, 'USD', 'equity', 'plaid', 'account_main', 285.75, '2023-04-05'),
(1, 1, 'KINS', 32.0, 'USD', 'equity', 'plaid', 'account_main', 15.25, '2023-02-15'),
(1, 1, 'MSCI', 8.0, 'USD', 'equity', 'plaid', 'account_main', 520.00, '2023-01-30'),
(1, 1, 'RNMBY', 36.0, 'USD', 'equity', 'plaid', 'account_main', 78.50, '2023-03-20'),
(1, 1, 'SFM', 70.0, 'USD', 'equity', 'plaid', 'account_main', 42.00, '2023-02-28'),
(1, 1, 'STWD', 133.0, 'USD', 'equity', 'plaid', 'account_main', 18.75, '2023-04-10'),
(1, 1, 'TKO', 40.0, 'USD', 'equity', 'plaid', 'account_main', 65.25, '2023-01-25'),
(1, 1, 'V', 9.0, 'USD', 'equity', 'plaid', 'account_main', 245.00, '2023-03-15');

-- Insert sample cash position (original identifier preserved)
INSERT INTO positions (portfolio_id, user_id, ticker, quantity, currency, type, position_source, account_id) VALUES
(1, 1, 'CUR:USD', -5078.62, 'USD', 'cash', 'plaid', 'account_main');  -- Stored as cash amount in quantity field

-- Insert sample SLV position (converted to share equivalent)
INSERT INTO positions (portfolio_id, user_id, ticker, quantity, currency, type, position_source, account_id, cost_basis, purchase_date) VALUES
(1, 1, 'SLV', 240.0, 'USD', 'etf', 'plaid', 'account_main', 25.00, '2023-02-10');  -- Assuming ~$25/share for SLV

-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================

-- Verify schema creation
SELECT 'Schema created successfully' as status;

-- Count tables
SELECT COUNT(*) as table_count FROM information_schema.tables 
WHERE table_schema = 'public' AND table_type = 'BASE TABLE';

-- Count indexes
SELECT COUNT(*) as index_count FROM pg_indexes 
WHERE schemaname = 'public';

-- Show sample data
SELECT 
    u.email,
    p.name as portfolio_name,
    COUNT(pos.id) as position_count,
    SUM(CASE WHEN pos.type = 'cash' THEN pos.quantity ELSE 0 END) as cash_total,
    COUNT(CASE WHEN pos.type != 'cash' THEN 1 END) as holdings_count
FROM users u
JOIN portfolios p ON u.id = p.user_id
JOIN positions pos ON p.id = pos.portfolio_id
GROUP BY u.email, p.name;

-- ============================================================================
-- REFERENCE DATA TABLES
-- ============================================================================

-- Cash currency to ETF proxy mappings
CREATE TABLE cash_proxies (
    currency VARCHAR(3) PRIMARY KEY,
    proxy_etf VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cash broker aliases to currency mappings
CREATE TABLE cash_aliases (
    broker_alias VARCHAR(50) PRIMARY KEY,
    currency VARCHAR(3) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Exchange to factor proxy mappings
CREATE TABLE exchange_proxies (
    exchange VARCHAR(10) NOT NULL,
    factor_type VARCHAR(20) NOT NULL,  -- 'market', 'momentum', 'value'
    proxy_etf VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (exchange, factor_type)
);

-- Industry to ETF proxy mappings
CREATE TABLE industry_proxies (
    industry VARCHAR(100) PRIMARY KEY,
    proxy_etf VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- REFERENCE DATA INDEXES
-- ============================================================================

-- Cash mapping indexes
CREATE INDEX idx_cash_aliases_currency ON cash_aliases(currency);

-- Exchange mapping indexes
CREATE INDEX idx_exchange_proxies_exchange ON exchange_proxies(exchange);
CREATE INDEX idx_exchange_proxies_factor_type ON exchange_proxies(factor_type);

-- Industry mapping indexes
CREATE INDEX idx_industry_proxies_industry ON industry_proxies(industry);

-- ============================================================================
-- REFERENCE DATA SEED DATA
-- ============================================================================

-- Default cash proxy mappings
INSERT INTO cash_proxies (currency, proxy_etf) VALUES
    ('USD', 'SGOV'),
    ('EUR', 'ESTR'),
    ('GBP', 'IB01')
ON CONFLICT (currency) DO NOTHING;

-- Default cash alias mappings
INSERT INTO cash_aliases (broker_alias, currency) VALUES
    ('CUR:USD', 'USD'),
    ('USD CASH', 'USD'),
    ('CASH', 'USD'),
    ('CUR:EUR', 'EUR'),
    ('EUR CASH', 'EUR'),
    ('CUR:GBP', 'GBP'),
    ('GBP CASH', 'GBP')
ON CONFLICT (broker_alias) DO NOTHING;

-- Default exchange proxy mappings
INSERT INTO exchange_proxies (exchange, factor_type, proxy_etf) VALUES
    ('NASDAQ', 'market', 'SPY'),
    ('NASDAQ', 'momentum', 'MTUM'),
    ('NASDAQ', 'value', 'IWD'),
    ('NYSE', 'market', 'SPY'),
    ('NYSE', 'momentum', 'MTUM'),
    ('NYSE', 'value', 'IWD'),
    ('DEFAULT', 'market', 'ACWX'),
    ('DEFAULT', 'momentum', 'IMTM'),
    ('DEFAULT', 'value', 'EFV')
ON CONFLICT (exchange, factor_type) DO NOTHING;

-- Default industry proxy mappings  
INSERT INTO industry_proxies (industry, proxy_etf) VALUES
    ('Technology', 'XLK'),
    ('Healthcare', 'XLV'),
    ('Financial Services', 'XLF'),
    ('Consumer Discretionary', 'XLY'),
    ('Consumer Staples', 'XLP'),
    ('Energy', 'XLE'),
    ('Industrials', 'XLI'),
    ('Materials', 'XLB'),
    ('Real Estate', 'XLRE'),
    ('Utilities', 'XLU'),
    ('Communication Services', 'XLC')
ON CONFLICT (industry) DO NOTHING;

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================ 