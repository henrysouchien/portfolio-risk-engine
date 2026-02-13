# Portfolio CRUD Implementation Plan V2

## 🎯 Overview

This updated plan addresses key implementation questions and provides step-by-step instructions to implement the missing portfolio CREATE and UPDATE functionality in the Risk Module.

## ✅ Key Implementation Questions Answered

### 1. **PortfolioData.from_holdings() - EXISTS**
- Located in `core/data_objects.py` (lines 508-535)
- Signature: `from_holdings(holdings, start_date, end_date, portfolio_name, expected_returns=None, stock_factor_proxies=None)`
- Already supports flexible input formats

### 2. **Database-First with YAML Fallback**
- Follow existing pattern: Database-first with YAML fallback
- PortfolioManager already supports dual-mode operation
- API endpoints should work with both modes

### 3. **Claude AI Integration - Separate Task**
- Claude functions currently use file-based system
- Refactoring needed but documented in `CLAUDE_SERVICE_DATABASE_REFACTOR.md`
- New CRUD endpoints will work immediately for web interface
- Claude integration is a separate future task

### 4. **Multi-Currency Support - READY**
- Database fully supports multi-currency positions
- Format: `CUR:USD`, `CUR:EUR`, `CUR:GBP`, etc.
- Each currency stored as separate position
- Cash-to-proxy mapping happens at analysis time

### 5. **Error Handling - EXISTS**
- `PortfolioNotFoundError` exists in `inputs/exceptions.py`
- Inherits from `DatabaseError` base class
- Use existing error patterns

### 6. **PORTFOLIO_DEFAULTS - EXISTS**
- Located in `settings.py`
- Contains default dates and configuration

## 🔧 Implementation Steps

### Step 1: Add PortfolioManager Methods

**File**: `inputs/portfolio_manager.py`

Add these methods to the `PortfolioManager` class:

```python
def create_portfolio(self, portfolio_name: str, holdings: Dict[str, Dict], 
                    start_date: str = None, end_date: str = None,
                    stock_factor_proxies: Dict[str, Dict] = None) -> PortfolioData:
    """
    Create a new portfolio in database or file mode.
    
    Args:
        portfolio_name: Name for the new portfolio
        holdings: Dictionary of holdings in format:
                 {"AAPL": {"shares": 100}, "GOOGL": {"dollars": 5000}}
                 Multi-currency cash: {"CUR:USD": {"dollars": 1000}, "CUR:EUR": {"dollars": 500}}
        start_date: Analysis start date (defaults to PORTFOLIO_DEFAULTS)
        end_date: Analysis end date (defaults to PORTFOLIO_DEFAULTS)
        stock_factor_proxies: Optional factor proxy configuration
        
    Returns:
        PortfolioData: Created portfolio data object
        
    Raises:
        ValueError: If portfolio already exists
    """
    
    # Check if portfolio already exists
    if self.use_database:
        existing_id = self.db_client.get_portfolio_id(self.internal_user_id, portfolio_name)
        if existing_id:
            raise ValueError(f"Portfolio '{portfolio_name}' already exists for this user")
    else:
        # File mode check
        yaml_path = os.path.join(self.base_dir, f"{portfolio_name}.yaml")
        if os.path.exists(yaml_path):
            raise ValueError(f"Portfolio file '{portfolio_name}.yaml' already exists")
    
    # Use existing from_holdings method
    portfolio_data = PortfolioData.from_holdings(
        holdings=holdings,
        start_date=start_date or PORTFOLIO_DEFAULTS["start_date"],
        end_date=end_date or PORTFOLIO_DEFAULTS["end_date"],
        portfolio_name=portfolio_name,
        expected_returns={}
    )
    
    # Set factor proxies if provided
    if stock_factor_proxies:
        portfolio_data.stock_factor_proxies = stock_factor_proxies
    
    # Save the portfolio
    self.save_portfolio_data(portfolio_data)
    
    print(f"✅ Portfolio '{portfolio_name}' created successfully")
    return portfolio_data

def update_portfolio_holdings(self, portfolio_name: str, 
                            holdings_updates: Dict[str, Dict],
                            remove_tickers: List[str] = None) -> PortfolioData:
    """
    Update specific holdings in an existing portfolio.
    
    Args:
        portfolio_name: Name of portfolio to update
        holdings_updates: Dictionary of holdings to add/update:
                         {"AAPL": {"shares": 150}, "TSLA": {"shares": 50}}
                         Multi-currency: {"CUR:EUR": {"dollars": 2000}}
        remove_tickers: List of tickers to remove from portfolio
        
    Returns:
        PortfolioData: Updated portfolio data object
        
    Raises:
        PortfolioNotFoundError: If portfolio doesn't exist
    """
    
    # Load existing portfolio (will raise PortfolioNotFoundError if not found)
    portfolio_data = self.load_portfolio_data(portfolio_name)
    
    # Remove tickers if specified
    if remove_tickers:
        for ticker in remove_tickers:
            portfolio_data.portfolio_input.pop(ticker, None)
    
    # Update/add holdings
    for ticker, updates in holdings_updates.items():
        if ticker in portfolio_data.portfolio_input:
            # Update existing position
            portfolio_data.portfolio_input[ticker].update(updates)
        else:
            # Add new position
            portfolio_data.portfolio_input[ticker] = updates
    
    # Save updated portfolio
    self.save_portfolio_data(portfolio_data)
    
    print(f"✅ Portfolio '{portfolio_name}' updated successfully")
    return portfolio_data

def update_portfolio_dates(self, portfolio_name: str,
                          start_date: str = None,
                          end_date: str = None) -> PortfolioData:
    """
    Update portfolio dates without changing holdings.
    
    Args:
        portfolio_name: Name of portfolio to update
        start_date: New start date (optional)
        end_date: New end date (optional)
        
    Returns:
        PortfolioData: Updated portfolio data object
        
    Raises:
        PortfolioNotFoundError: If portfolio doesn't exist
    """
    # Load existing portfolio (will raise PortfolioNotFoundError if not found)
    portfolio_data = self.load_portfolio_data(portfolio_name)
    
    # Update metadata
    if start_date:
        portfolio_data.start_date = start_date
    if end_date:
        portfolio_data.end_date = end_date
    
    # Save updated portfolio
    self.save_portfolio_data(portfolio_data)
    
    print(f"✅ Portfolio '{portfolio_name}' dates updated successfully")
    return portfolio_data
```

### Step 2: Add API Endpoints

**File**: `routes/api.py`

Add these imports at the top if not already present:

```python
from inputs.exceptions import PortfolioNotFoundError
from typing import List
```

Add these endpoints after the existing portfolio endpoints (around line 971):

```python
@api_bp.route("/portfolios", methods=["POST"])
@log_portfolio_operation_decorator("api_portfolio_create")
@log_performance(1.0)
@log_error_handling("high")
def api_create_portfolio():
    """Create a new portfolio"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        # Extract request data
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Validate required fields
        portfolio_name = data.get('portfolio_name')
        holdings = data.get('holdings', {})
        
        if not portfolio_name:
            return jsonify({'error': 'portfolio_name is required'}), 400
        
        if not holdings:
            return jsonify({'error': 'holdings cannot be empty'}), 400
        
        
        # Optional fields
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        stock_factor_proxies = data.get('stock_factor_proxies', {})
        
        # Create portfolio using database-first approach
        pm = PortfolioManager(use_database=True, user_id=user['id'])
        portfolio_data = pm.create_portfolio(
            portfolio_name=portfolio_name,
            holdings=holdings,
            start_date=start_date,
            end_date=end_date,
            stock_factor_proxies=stock_factor_proxies
        )
        
        
        return jsonify({
            'success': True,
            'message': f'Portfolio "{portfolio_name}" created successfully',
            'portfolio_data': portfolio_data.to_dict()
        }), 201
        
    except ValueError as e:
        # Portfolio already exists or validation error
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        log_error_json("create_portfolio", "API execution", e, user['id'], "authenticated")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@api_bp.route("/portfolios/<portfolio_name>", methods=["PUT"])
@log_portfolio_operation_decorator("api_portfolio_update")
@log_performance(1.0)
@log_error_handling("high")
def api_update_portfolio(portfolio_name):
    """Update an existing portfolio"""
    user = get_current_user()
    if not user:
        return jsonify({'error': 'Authentication required'}), 401
    
    try:
        # Extract request data
        data = request.json
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # Use database-first approach
        pm = PortfolioManager(use_database=True, user_id=user['id'])
        
        # Determine update type
        holdings_updates = data.get('holdings_updates', {})
        remove_tickers = data.get('remove_tickers', [])
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        # Validate remove_tickers is a list
        if not isinstance(remove_tickers, list):
            return jsonify({'error': 'remove_tickers must be a list'}), 400
        
        # Perform appropriate update
        if holdings_updates or remove_tickers:
            # Update holdings
            portfolio_data = pm.update_portfolio_holdings(
                portfolio_name=portfolio_name,
                holdings_updates=holdings_updates,
                remove_tickers=remove_tickers
            )
        elif start_date or end_date:
            # Update dates only
            portfolio_data = pm.update_portfolio_dates(
                portfolio_name=portfolio_name,
                start_date=start_date,
                end_date=end_date
            )
        else:
            return jsonify({'error': 'No updates provided'}), 400
        
        
        return jsonify({
            'success': True,
            'message': f'Portfolio "{portfolio_name}" updated successfully',
            'portfolio_data': portfolio_data.to_dict()
        })
        
    except PortfolioNotFoundError:
        return jsonify({'error': f'Portfolio "{portfolio_name}" not found'}), 404
    except ValueError as e:
        # Validation error
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        log_error_json("update_portfolio", "API execution", e, user['id'], "authenticated")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@api_bp.route("/portfolios/<portfolio_name>", methods=["PATCH"])
@log_portfolio_operation_decorator("api_portfolio_patch")
@log_performance(1.0)
@log_error_handling("high")
def api_patch_portfolio(portfolio_name):
    """
    Partial update of a portfolio (alias for PUT).
    Supports the same operations as PUT endpoint.
    """
    return api_update_portfolio(portfolio_name)
```

## 📝 API Documentation

### POST /api/portfolios - Create Portfolio

**Request Body**:
```json
{
  "portfolio_name": "my_global_portfolio",
  "holdings": {
    "AAPL": {"shares": 100},
    "GOOGL": {"shares": 50},
    "MSFT": {"dollars": 10000},
    "CUR:USD": {"dollars": 5000},    // US Dollar cash
    "CUR:EUR": {"dollars": 2000},    // Euro cash (in dollar value)
    "CUR:GBP": {"dollars": 1500}     // British Pound cash (in dollar value)
  },
  "start_date": "2020-01-01",      // Optional, defaults to PORTFOLIO_DEFAULTS
  "end_date": "2024-12-31",        // Optional, defaults to PORTFOLIO_DEFAULTS
  "stock_factor_proxies": {}        // Optional
}
```

**Response (201 Created)**:
```json
{
  "success": true,
  "message": "Portfolio \"my_global_portfolio\" created successfully",
  "portfolio_data": {
    "portfolio_name": "my_global_portfolio",
    "portfolio_input": {
      "AAPL": {"shares": 100},
      "GOOGL": {"shares": 50},
      "MSFT": {"dollars": 10000},
      "CUR:USD": {"dollars": 5000},
      "CUR:EUR": {"dollars": 2000},
      "CUR:GBP": {"dollars": 1500}
    },
    "start_date": "2020-01-01",
    "end_date": "2024-12-31",
    "expected_returns": {},
    "stock_factor_proxies": {}
  }
}
```

**Error Responses**:
- 400 Bad Request: Invalid portfolio name, missing fields, or portfolio already exists
- 401 Unauthorized: Not authenticated
- 500 Internal Server Error: Database or other errors

### PUT/PATCH /api/portfolios/{name} - Update Portfolio

**Request Body** (Update Holdings):
```json
{
  "holdings_updates": {
    "AAPL": {"shares": 150},         // Update existing
    "TSLA": {"shares": 25},          // Add new stock
    "CUR:JPY": {"dollars": 3000}     // Add Japanese Yen position
  },
  "remove_tickers": ["GOOGL", "CUR:GBP"]  // Remove positions
}
```

**Request Body** (Update Dates):
```json
{
  "start_date": "2021-01-01",
  "end_date": "2024-12-31"
}
```

**Response (200 OK)**:
```json
{
  "success": true,
  "message": "Portfolio \"my_global_portfolio\" updated successfully",
  "portfolio_data": {...}
}
```

**Error Responses**:
- 400 Bad Request: Invalid data format or validation error
- 401 Unauthorized: Not authenticated
- 404 Not Found: Portfolio doesn't exist
- 500 Internal Server Error: Database or other errors

## 🔍 Key Implementation Details

### Multi-Currency Support

1. **Currency Format**: `CUR:XXX` where XXX is 3-letter currency code
2. **Validation**: Enforce 3-letter alphabetic currency codes
3. **Storage**: Stored as-is in database, mapped to proxy ETFs at analysis time
4. **Examples**:
   - `CUR:USD` → SGOV (US Treasury)
   - `CUR:EUR` → ESTR (Euro Treasury)
   - `CUR:GBP` → GBIL (UK Treasury)

### Database-First Pattern

```python
# All endpoints use database-first approach
pm = PortfolioManager(use_database=True, user_id=user['id'])

# PortfolioManager handles fallback internally if database fails
# This maintains consistency with the authentication pattern
```

### Error Handling

```python
# Use existing exception classes
from inputs.exceptions import PortfolioNotFoundError, DatabaseError

# Standard error response pattern
try:
    # Operation
except PortfolioNotFoundError:
    return jsonify({'error': f'Portfolio "{name}" not found'}), 404
except ValueError as e:
    return jsonify({'error': str(e)}), 400
except DatabaseError as e:
    # Log and potentially fallback
    return jsonify({'error': 'Database error occurred'}), 500
```

## 🧪 Testing Plan

### 1. Unit Tests for PortfolioManager

Create `tests/test_portfolio_crud.py`:

```python
import pytest
from inputs.portfolio_manager import PortfolioManager
from inputs.exceptions import PortfolioNotFoundError
from core.data_objects import PortfolioData
from settings import PORTFOLIO_DEFAULTS

def test_create_portfolio_with_multi_currency():
    """Test portfolio creation with multi-currency positions"""
    pm = PortfolioManager(use_database=False)
    
    holdings = {
        "AAPL": {"shares": 100},
        "CUR:USD": {"dollars": 5000},
        "CUR:EUR": {"dollars": 2000},
        "CUR:JPY": {"dollars": 1000}
    }
    
    portfolio_data = pm.create_portfolio(
        portfolio_name="test_multi_currency",
        holdings=holdings
    )
    
    assert portfolio_data.portfolio_name == "test_multi_currency"
    assert "CUR:USD" in portfolio_data.portfolio_input
    assert "CUR:EUR" in portfolio_data.portfolio_input
    assert portfolio_data.start_date == PORTFOLIO_DEFAULTS["start_date"]

def test_create_portfolio_invalid_currency():
    """Test that invalid currency format raises error"""
    pm = PortfolioManager(use_database=False)
    
    holdings = {
        "AAPL": {"shares": 100},
        "CUR:US": {"dollars": 5000}  # Invalid: only 2 letters
    }
    
    with pytest.raises(ValueError, match="Invalid currency format"):
        pm.create_portfolio("test_invalid", holdings)

def test_update_portfolio_not_found():
    """Test updating non-existent portfolio raises error"""
    pm = PortfolioManager(use_database=False)
    
    with pytest.raises(PortfolioNotFoundError):
        pm.update_portfolio_holdings(
            "non_existent_portfolio",
            holdings_updates={"AAPL": {"shares": 100}}
        )
```

### 2. API Integration Tests

Create `tests/test_portfolio_api_crud.py`:

```python
import json
import pytest
from app import app

@pytest.fixture
def authenticated_headers(mocker):
    """Mock authenticated user headers"""
    mocker.patch('routes.api.get_current_user', return_value={'id': 123, 'email': 'test@example.com'})
    return {'Content-Type': 'application/json'}

def test_create_portfolio_multi_currency(client, authenticated_headers):
    """Test creating portfolio with multiple currencies"""
    response = client.post('/api/portfolios', 
        json={
            "portfolio_name": "test_global",
            "holdings": {
                "AAPL": {"shares": 100},
                "CUR:USD": {"dollars": 5000},
                "CUR:EUR": {"dollars": 2000}
            }
        },
        headers=authenticated_headers
    )
    
    assert response.status_code == 201
    data = json.loads(response.data)
    assert data['success'] is True
    assert "CUR:EUR" in data['portfolio_data']['portfolio_input']

def test_portfolio_name_validation(client, authenticated_headers):
    """Test portfolio name validation"""
    # Invalid characters
    response = client.post('/api/portfolios',
        json={
            "portfolio_name": "test@portfolio!",
            "holdings": {"AAPL": {"shares": 100}}
        },
        headers=authenticated_headers
    )
    
    assert response.status_code == 400
    assert "Invalid portfolio name" in json.loads(response.data)['error']
```

## 🚀 Implementation Checklist

- [ ] Add List to the typing imports in PortfolioManager (currently has Dict, Any, Optional, Union)
- [ ] Add `create_portfolio()` method
- [ ] Add `update_portfolio_holdings()` method
- [ ] Add `update_portfolio_dates()` method
- [ ] Add imports to routes/api.py:
  - [ ] from inputs.exceptions import PortfolioNotFoundError
  - [ ] from typing import List
- [ ] Add POST `/api/portfolios` endpoint
- [ ] Add PUT `/api/portfolios/<name>` endpoint
- [ ] Add PATCH `/api/portfolios/<name>` endpoint (alias)
- [ ] Create unit tests for PortfolioManager methods
- [ ] Create integration tests for API endpoints
- [ ] Test multi-currency support (CUR:USD, CUR:EUR, etc.)
- [ ] Test with both database and file modes
- [ ] Update API documentation

## 📌 Important Notes

1. **Claude AI Integration**: Will need separate refactoring per `CLAUDE_SERVICE_DATABASE_REFACTOR.md`
2. **Multi-Currency**: Cash positions stored as `CUR:XXX`, mapped to proxies at analysis time
3. **Database-First**: All endpoints use database mode with automatic fallback
4. **Existing Components**: All required classes and errors already exist

## 🎯 Success Criteria

1. ✅ Users can create portfolios with multi-currency support
2. ✅ Users can update portfolios (add/remove/modify holdings)
3. ✅ Users can update portfolio dates separately
4. ✅ All operations properly handle database/file dual-mode
5. ✅ Currency format validation (CUR:XXX)
6. ✅ Proper error messages and HTTP status codes
7. ✅ Integration with existing authentication system

This completes the portfolio CRUD implementation plan V2 with all questions addressed.