# Claude Portfolio CRUD Implementation Plan

## 🎯 Overview

Add portfolio management capabilities to Claude by creating wrapper functions for the existing PortfolioManager CRUD methods. This enables Claude to list, create, update, and delete portfolios in the database.

**Implementation Note**: This plan has been updated to align with the current codebase architecture, including proper user_id field usage, secure file paths, and appropriate error handling.

## 📋 Current State

### Existing Infrastructure:
- ✅ PortfolioManager has all CRUD methods implemented
- ✅ Database-first architecture with user isolation
- ✅ API endpoints exist for web interface
- ❌ Claude cannot access these capabilities

### Current Claude Functions:
- `create_portfolio_scenario` - Creates temporary YAML files only
- `run_portfolio_analysis` - Analyzes portfolios but can't manage them
- No functions for listing, creating, updating, or deleting database portfolios

## 🛠️ Implementation Plan

### Phase 1: Add Function Definitions to Registry

**File:** `ai_function_registry.py`

Add these function definitions to the `AI_FUNCTIONS` dictionary:

```python
"list_portfolios": {
    "name": "list_portfolios",
    "description": "List all portfolios saved for the current user. Shows portfolio names and helps users see what portfolios they have available. Use when users ask 'what portfolios do I have?', 'show my portfolios', or want to see their saved portfolio list.",
    
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": []
    },
    
    "executor": "_execute_list_portfolios",
    "underlying_function": "PortfolioManager.get_portfolio_names()",
    
    "output_schema": {
        "type": "object",
        "properties": {
            "portfolios": {"type": "array", "items": {"type": "string"}},
            "count": {"type": "integer"},
            "current_portfolio": {"type": "string"}
        }
    }
},

"create_portfolio": {
    "name": "create_portfolio",
    "description": "Create a new portfolio in the database with specified holdings. This saves the portfolio permanently for future use. Use when users want to create and save a new portfolio (not just a temporary scenario). Different from create_portfolio_scenario which only creates temporary YAML files.",
    
    "input_schema": {
        "type": "object",
        "properties": {
            "portfolio_name": {
                "type": "string",
                "description": "Name for the new portfolio (e.g., 'Retirement', 'Growth Portfolio', 'Conservative Mix'). Must be unique for this user."
            },
            "holdings": {
                "type": "object",
                "description": "Holdings with shares or dollar amounts. Format: {'AAPL': {'shares': 100}, 'GOOGL': {'shares': 50}} or {'AAPL': {'dollars': 15000}, 'MSFT': {'dollars': 10000}}. For cash positions use 'CUR:USD', 'CUR:EUR', etc."
            },
            "start_date": {
                "type": "string",
                "description": "Optional start date for analysis period (YYYY-MM-DD format). Defaults to settings if not provided."
            },
            "end_date": {
                "type": "string",
                "description": "Optional end date for analysis period (YYYY-MM-DD format). Defaults to settings if not provided."
            }
        },
        "required": ["portfolio_name", "holdings"]
    },
    
    "executor": "_execute_create_portfolio",
    "underlying_function": "PortfolioManager.create_portfolio()",
    
    "output_schema": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "portfolio_name": {"type": "string"}
        }
    }
},

"delete_portfolio": {
    "name": "delete_portfolio",
    "description": "Delete a portfolio from the database permanently. This cannot be undone. Use when users want to remove a saved portfolio they no longer need.",
    
    "input_schema": {
        "type": "object",
        "properties": {
            "portfolio_name": {
                "type": "string",
                "description": "Name of the portfolio to delete. Must be an existing portfolio name."
            },
            "confirm": {
                "type": "boolean",
                "description": "Set to true to confirm deletion. This is a safety check since deletion cannot be undone."
            }
        },
        "required": ["portfolio_name", "confirm"]
    },
    
    "executor": "_execute_delete_portfolio",
    "underlying_function": "PortfolioManager.delete_portfolio()",
    
    "output_schema": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"}
        }
    }
},

"update_portfolio_holdings": {
    "name": "update_portfolio_holdings",
    "description": "Update holdings in an existing portfolio. Can add new positions, update existing positions, or remove positions. Use when users want to modify their saved portfolio holdings without creating a new portfolio.",
    
    "input_schema": {
        "type": "object",
        "properties": {
            "portfolio_name": {
                "type": "string",
                "description": "Name of the portfolio to update. Must be an existing portfolio."
            },
            "holdings_updates": {
                "type": "object",
                "description": "Holdings to add or update. Format: {'AAPL': {'shares': 150}, 'TSLA': {'shares': 25}}. These will be added or will replace existing positions."
            },
            "remove_tickers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tickers to remove from the portfolio. E.g., ['GOOGL', 'META'] to remove these positions."
            }
        },
        "required": ["portfolio_name"]
    },
    
    "executor": "_execute_update_portfolio_holdings",
    "underlying_function": "PortfolioManager.update_portfolio_holdings()",
    
    "output_schema": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "updated_holdings": {"type": "object"}
        }
    }
},

"switch_portfolio": {
    "name": "switch_portfolio",
    "description": "Switch the active portfolio for analysis. Changes which portfolio will be used for subsequent analysis commands. Use when users want to analyze a different portfolio than the current one.",
    
    "input_schema": {
        "type": "object",
        "properties": {
            "portfolio_name": {
                "type": "string",
                "description": "Name of the portfolio to switch to. Use 'CURRENT_PORTFOLIO' to switch to the default portfolio."
            }
        },
        "required": ["portfolio_name"]
    },
    
    "executor": "_execute_switch_portfolio",
    "underlying_function": "Sets active portfolio in context",
    
    "output_schema": {
        "type": "object",
        "properties": {
            "success": {"type": "boolean"},
            "message": {"type": "string"},
            "active_portfolio": {"type": "string"}
        }
    }
}
```

### Phase 2: Implement Executor Methods

**File:** `services/claude/function_executor.py`

Add these methods to the `ClaudeFunctionExecutor` class:

```python
def _execute_list_portfolios(self, parameters):
    """List all portfolios for current user"""
    if not self.user:
        return {
            "success": False,
            "error": "Authentication required",
            "type": "list_portfolios",
            "portfolios": [],
            "count": 0
        }
    
    try:
        pm = PortfolioManager(use_database=True, user_id=self.user['user_id'])
        portfolios = pm.get_portfolio_names()
        
        # Get current active portfolio from context
        active_portfolio = self.active_portfolio_name or "CURRENT_PORTFOLIO"
        
        return {
            "portfolios": portfolios,
            "count": len(portfolios),
            "current_portfolio": active_portfolio,
            "message": f"Found {len(portfolios)} portfolio(s)"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to list portfolios: {str(e)}",
            "type": "list_portfolios",
            "portfolios": [],
            "count": 0
        }

def _execute_create_portfolio(self, parameters):
    """Create new portfolio in database"""
    if not self.user:
        return {
            "success": False,
            "error": "Authentication required",
            "type": "create_portfolio"
        }
    
    portfolio_name = parameters.get("portfolio_name")
    holdings = parameters.get("holdings")
    start_date = parameters.get("start_date")
    end_date = parameters.get("end_date")
    
    if not portfolio_name:
        return {
            "success": False,
            "error": "portfolio_name is required",
            "type": "create_portfolio"
        }
    
    if not holdings:
        return {
            "success": False,
            "error": "holdings cannot be empty",
            "type": "create_portfolio"
        }
    
    try:
        pm = PortfolioManager(use_database=True, user_id=self.user['user_id'])
        portfolio_data = pm.create_portfolio(
            portfolio_name=portfolio_name,
            holdings=holdings,
            start_date=start_date,
            end_date=end_date
        )
        
        return {
            "success": True,
            "message": f"Successfully created portfolio '{portfolio_name}' with {len(holdings)} positions",
            "portfolio_name": portfolio_name,
            "holdings_count": len(holdings)
        }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e),
            "type": "create_portfolio"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to create portfolio: {str(e)}",
            "type": "create_portfolio"
        }

def _execute_delete_portfolio(self, parameters):
    """Delete portfolio from database"""
    if not self.user:
        return {
            "success": False,
            "error": "Authentication required",
            "type": "delete_portfolio"
        }
    
    portfolio_name = parameters.get("portfolio_name")
    confirm = parameters.get("confirm", False)
    
    if not portfolio_name:
        return {
            "success": False,
            "error": "portfolio_name is required",
            "type": "delete_portfolio"
        }
    
    if not confirm:
        return {
            "success": False,
            "error": "Please set confirm=true to delete the portfolio",
            "type": "delete_portfolio"
        }
    
    try:
        pm = PortfolioManager(use_database=True, user_id=self.user['user_id'])
        success = pm.delete_portfolio(portfolio_name)
        
        if success:
            # If deleted portfolio was active, switch to default
            if self.active_portfolio_name == portfolio_name:
                self.active_portfolio_name = "CURRENT_PORTFOLIO"
            
            return {
                "success": True,
                "message": f"Successfully deleted portfolio '{portfolio_name}'"
            }
        else:
            return {
                "success": False,
                "error": f"Portfolio '{portfolio_name}' not found",
                "type": "delete_portfolio"
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to delete portfolio: {str(e)}",
            "type": "delete_portfolio"
        }

def _execute_update_portfolio_holdings(self, parameters):
    """Update holdings in existing portfolio"""
    if not self.user:
        return {
            "success": False,
            "error": "Authentication required",
            "type": "update_portfolio_holdings"
        }
    
    portfolio_name = parameters.get("portfolio_name")
    holdings_updates = parameters.get("holdings_updates", {})
    remove_tickers = parameters.get("remove_tickers", [])
    
    if not portfolio_name:
        return {
            "success": False,
            "error": "portfolio_name is required",
            "type": "update_portfolio_holdings"
        }
    
    if not holdings_updates and not remove_tickers:
        return {
            "success": False,
            "error": "No updates provided (need holdings_updates or remove_tickers)",
            "type": "update_portfolio_holdings"
        }
    
    try:
        pm = PortfolioManager(use_database=True, user_id=self.user['user_id'])
        portfolio_data = pm.update_portfolio_holdings(
            portfolio_name=portfolio_name,
            holdings_updates=holdings_updates,
            remove_tickers=remove_tickers
        )
        
        message_parts = []
        if holdings_updates:
            message_parts.append(f"updated {len(holdings_updates)} position(s)")
        if remove_tickers:
            message_parts.append(f"removed {len(remove_tickers)} position(s)")
        
        return {
            "success": True,
            "message": f"Successfully {' and '.join(message_parts)} in portfolio '{portfolio_name}'",
            "updated_holdings": portfolio_data.portfolio_input,
            "total_positions": len(portfolio_data.portfolio_input)
        }
    except PortfolioNotFoundError:
        return {
            "success": False,
            "error": f"Portfolio '{portfolio_name}' not found",
            "type": "update_portfolio_holdings"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to update portfolio: {str(e)}",
            "type": "update_portfolio_holdings"
        }

def _execute_switch_portfolio(self, parameters):
    """Switch active portfolio for analysis"""
    if not self.user:
        return {
            "success": False,
            "error": "Authentication required",
            "type": "switch_portfolio"
        }
    
    portfolio_name = parameters.get("portfolio_name")
    
    if not portfolio_name:
        return {
            "success": False,
            "error": "portfolio_name is required",
            "type": "switch_portfolio"
        }
    
    try:
        # Verify portfolio exists
        pm = PortfolioManager(use_database=True, user_id=self.user['user_id'])
        
        # Try to load it to verify it exists
        portfolio_data = pm.load_portfolio_data(portfolio_name)
        
        # Update active portfolio in context
        self.active_portfolio_name = portfolio_name
        
        # Clear any cached context for the user
        # Note: Context caching is handled by PortfolioContextService which will
        # automatically detect portfolio changes on next request
        
        return {
            "success": True,
            "message": f"Switched to portfolio '{portfolio_name}'",
            "active_portfolio": portfolio_name
        }
    except PortfolioNotFoundError:
        return {
            "success": False,
            "error": f"Portfolio '{portfolio_name}' not found",
            "type": "switch_portfolio"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to switch portfolio: {str(e)}",
            "type": "switch_portfolio"
        }
```

### Phase 3: Update Executor Initialization

**File:** `services/claude/function_executor.py`

Update the `__init__` method to track active portfolio:

```python
def __init__(self):
    # Existing initialization
    self.portfolio_service = PortfolioService()
    self.stock_service = StockService()
    self.optimization_service = OptimizationService()
    self.scenario_service = ScenarioService()
    
    # User context support
    self.user = None
    
    # NEW: Track active portfolio
    self.active_portfolio_name = "CURRENT_PORTFOLIO"
```

### Phase 4: Update Context Service Integration

**File:** `services/portfolio/context_service.py`

Note: The context service already has the correct method signature `get_cached_context(self, user=None, portfolio_name="CURRENT_PORTFOLIO")` and uses `user['user_id']` properly. The executor can pass the `portfolio_name` parameter directly when calling this method.

The current implementation in context_service.py (line 138) already handles this correctly:
- Takes `portfolio_name` as a parameter (defaults to "CURRENT_PORTFOLIO")
- Uses `user['user_id']` for authentication (line 164)
- Loads portfolio from database with proper user isolation
- Falls back to secure user-specific YAML paths using `get_user_fallback_path()`

### Phase 5: Add Import Statements

**File:** `services/claude/function_executor.py`

Add these imports at the top:

```python
from inputs.exceptions import PortfolioNotFoundError
from inputs.file_manager import get_user_fallback_path
from inputs.portfolio_manager import PortfolioManager
```

## 🧪 Testing Plan

### 1. Test Portfolio Listing
```
User: "What portfolios do I have?"
Claude: [Calls list_portfolios()]
Expected: Returns list of user's portfolios
```

### 2. Test Portfolio Creation
```
User: "Create a new portfolio called 'Tech Growth' with 100 shares of AAPL and 50 shares of GOOGL"
Claude: [Calls create_portfolio()]
Expected: Creates portfolio in database
```

### 3. Test Portfolio Switching
```
User: "Switch to my Tech Growth portfolio"
Claude: [Calls switch_portfolio()]
Expected: Changes active portfolio for analysis
```

### 4. Test Portfolio Updates
```
User: "Add 25 shares of MSFT to my current portfolio"
Claude: [Calls update_portfolio_holdings()]
Expected: Updates portfolio holdings
```

### 5. Test Portfolio Deletion
```
User: "Delete my test portfolio"
Claude: [Calls delete_portfolio()]
Expected: Removes portfolio from database
```

## 📝 Implementation Notes

1. **Authentication Required**: All functions check for user context
2. **Error Handling**: Graceful handling of missing portfolios, duplicate names, etc.
3. **Active Portfolio Tracking**: The executor maintains which portfolio is currently active
4. **Cache Clearing**: When switching portfolios, cached analysis is cleared
5. **Safety Checks**: Delete requires confirmation parameter

## 🎯 Success Criteria

1. ✅ Claude can list all user portfolios
2. ✅ Claude can create new portfolios in database
3. ✅ Claude can switch between portfolios for analysis
4. ✅ Claude can update portfolio holdings
5. ✅ Claude can delete portfolios (with confirmation)
6. ✅ All operations respect user isolation
7. ✅ Proper error messages for all failure cases

## 🚀 Next Steps

After implementation:
1. Update Claude's system prompt to mention portfolio management capabilities
2. Add examples to Claude's training/context about portfolio operations
3. Test with real user scenarios
4. Document the new capabilities for users