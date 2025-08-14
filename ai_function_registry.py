"""
AI Function Registry - Centralized source of truth for all Claude function definitions.

This registry provides a single source of truth for all 14 Claude AI functions, eliminating
the need to maintain function definitions in multiple files.

ARCHITECTURE:
- AI_FUNCTIONS dictionary contains complete metadata for all Claude functions
- Context service imports function definitions for Claude API
- Function executor uses registry for dynamic routing (eliminating hardcoded if/elif chains)
- All function schemas, descriptions, and routing centralized here

AI_FUNCTIONS STRUCTURE:
Each function entry contains:
- "name": Claude function name (matches key)
- "description": Detailed function description for Claude API
- "input_schema": JSON schema for Claude API parameter validation
- "executor": Method name in FunctionExecutor class (e.g., "_execute_portfolio_analysis")
- "underlying_function": Actual function(s) called by executor (METADATA ONLY - not used programmatically)
- "output_schema": Expected return format (optional, for documentation)
- "examples": Sample inputs for error handling (optional)
- "example_input": Complete example for testing (optional)

USAGE:
- get_function_definitions(): Returns Claude API format for all functions
- get_function_executor(name): Returns executor method name for dynamic routing
- get_function_examples(name): Returns examples for error handling
- get_all_function_names(): Returns list of all available function names
"""

# LOGGING: Add function registration logging
# LOGGING: Add function call timing
# LOGGING: Add function result validation
# LOGGING: Add error handling logging

AI_FUNCTIONS = {
    "create_portfolio_scenario": {
        "name": "create_portfolio_scenario",
        "description": "Create a new portfolio scenario YAML file with specified holdings and allocations. Supports flexible input formats including percentages, weights, dollar amounts, and share counts with automatic format detection. Returns the created scenario file path for further analysis. Use this when users want to test new portfolio allocations, create 'what if' scenarios, or set up portfolios for analysis.",
        
        # Claude API format
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_description": {
                    "type": "string",
                    "description": "Clear description of the new portfolio strategy (e.g., 'Conservative portfolio with 40% treasury bonds, 30% utilities, 30% consumer staples')"
                },
                "holdings": {
                    "type": "object",
                    "description": "Complete allocation percentages for all positions in the new portfolio OR holdings in shares/dollars. For percentages: must sum to 100% (e.g., {'SGOV': 40, 'XLU': 30, 'XLP': 30}). For holdings: provide shares or dollar amounts (e.g., {'AAPL': 100, 'MSFT': 50} for 100 shares AAPL, 50 shares MSFT or {'AAPL': 15000, 'MSFT': 12000} for $15k AAPL, $12k MSFT). System auto-detects format.",
                    "additionalProperties": {"type": "number"}
                },
                "scenario_name": {
                    "type": "string",
                    "description": "Name for this portfolio scenario (optional, defaults to 'scenario')"
                },
                "custom_risk_limits": {
                    "type": "object",
                    "description": "Optional custom risk tolerance for this scenario only (e.g., {'max_volatility': 0.6, 'max_single_stock_weight': 0.45})",
                    "additionalProperties": {"type": "number"}
                }
            },
            "required": ["portfolio_description", "holdings"]
        },
        
        # Function executor information
        "executor": "_execute_create_scenario",
        "underlying_function": ["create_portfolio_yaml", "create_risk_limits_yaml", "inject_all_proxies", "run_portfolio"],
        
        # Expected output format
        "output_schema": {
            "success": {"type": "boolean"},
            "result": {"type": "string"},
            "type": {"type": "string", "enum": ["portfolio_scenario"]},
            "scenario_name": {"type": "string"},
            "scenario_file": {"type": "string"},
            "risk_file": {"type": "string", "nullable": True},
            "description": {"type": "string"},
            "holdings": {"type": "object"},
            "custom_risk_limits": {"type": "object", "nullable": True}
        },
        
        # Examples for error messages and documentation
        "examples": {
            "percentages": {"AAPL": 25, "MSFT": 30, "SGOV": 45},
            "decimal_weights": {"AAPL": 0.25, "MSFT": 0.30, "SGOV": 0.45},
            "shares_dollars": {"AAPL": 100, "MSFT": 50, "SPY": 15000}
        },
        
        # Complete example for testing
        "example_input": {
            "portfolio_description": "Tech growth portfolio with defensive cash position",
            "holdings": {"AAPL": 25, "MSFT": 30, "SGOV": 45},
            "scenario_name": "tech_growth",
            "custom_risk_limits": {"max_volatility": 0.35}
        }
    },
    
    "run_portfolio_analysis": {
        "name": "run_portfolio_analysis",
        "description": "Execute comprehensive portfolio risk analysis including multi-factor decomposition, variance attribution, risk metrics, and factor exposure analysis. Returns detailed breakdown of portfolio components, factor betas, risk contributions, and risk limit compliance. Automatically analyzes the user's current portfolio unless a specific portfolio is requested. Use this when users request full portfolio analysis or want to understand overall portfolio risk structure.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_name": {
                    "type": "string",
                    "description": "Name of the portfolio to analyze. Optional - defaults to user's current portfolio. Only specify if user asks to analyze a specific named portfolio (e.g., 'Conservative_Portfolio', 'Tech_Growth_Strategy')."
                }
            },
            "required": []
        },
        "executor": "_execute_portfolio_analysis",
        "underlying_function": "run_portfolio"
    },
    
    "analyze_stock": {
        "name": "analyze_stock",
        "description": "Perform detailed individual stock risk analysis including factor exposures, beta calculations, and risk profile assessment. Returns stock-specific risk metrics, factor sensitivities, and peer comparisons. Automatically includes comprehensive factor analysis for stocks that have factor proxies defined in the portfolio configuration. Use when users ask about specific stock risk characteristics or want to understand how a particular stock contributes to portfolio risk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol (e.g., 'AAPL', 'MSFT'). Must be a valid ticker symbol."
                },
                "start_date": {
                    "type": "string",
                    "description": "Analysis start date in YYYY-MM-DD format. Optional - defaults to 5 years ago."
                },
                "end_date": {
                    "type": "string",
                    "description": "Analysis end date in YYYY-MM-DD format. Optional - defaults to current date."
                },

                "factor_proxies": {
                    "type": "object",
                    "description": "Direct factor proxy mapping for custom factor analysis (e.g., {'market': 'SPY', 'momentum': 'MTUM', 'value': 'IWD', 'industry': 'XLF'}). Optional - if omitted, auto-generates intelligent factor proxies for comprehensive analysis.",
                    "additionalProperties": {"type": "string"}
                }
            },
            "required": ["ticker"]
        },
        "executor": "_execute_stock_analysis",
        "underlying_function": "run_stock"
    },
    
    "run_what_if_scenario": {
        "name": "run_what_if_scenario",
        "description": "Execute scenario analysis to test portfolio allocation changes and their impact on risk metrics, factor exposures, and performance characteristics. Shows before/after comparison with detailed impact analysis. Supports both absolute target weights and relative changes (deltas). IMPORTANT: Use delta_changes for language like 'add more', 'increase by', 'reduce by', 'add X%'. Use target_weights for language like 'set to', 'allocate exactly', 'target weight of'. Use when users want to test specific rebalancing ideas or explore 'what if' portfolio changes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_weights": {
                    "type": "object",
                    "description": "ABSOLUTE target allocation weights as decimals for specific tickers you want to set to exact values. Use when user says 'set SPY to 10%', 'allocate exactly 15%', 'target weight of 5%'. Only include tickers being modified - others remain unchanged. Format: {'TICKER': decimal_weight} (e.g., {'AAPL': 0.15, 'SGOV': 0.10} to set AAPL to exactly 15% and SGOV to exactly 10%).",
                    "additionalProperties": {"type": "number"}
                },
                "delta_changes": {
                    "type": "object", 
                    "description": "RELATIVE changes to add/subtract from current weights. Use when user says 'add more SPY', 'increase SPY by 5%', 'reduce tech exposure', 'add another 10%'. Format: {'TICKER': 'change_string'} where change_string can be: '+5%' (add 5%), '-200bp' (subtract 2%), '+0.05' (add 5%), etc. Examples: {'SPY': '+10%', 'AAPL': '-5%'} to add 10% SPY and reduce AAPL by 5%.",
                    "additionalProperties": {"type": "string"}
                },
                "scenario_name": {
                    "type": "string", 
                    "description": "Descriptive name for this scenario (e.g., 'Add More SPY', 'Reduce Tech Exposure', 'Risk Reduction'). Optional but helpful for context."
                }
            },
            "required": []
        },
        "executor": "_execute_what_if_scenario",
        "underlying_function": ["create_what_if_yaml", "run_what_if"]
    },
    
    "optimize_minimum_variance": {
        "name": "optimize_minimum_variance",
        "description": "Execute algorithmic optimization to find the portfolio allocation with the lowest possible risk (variance) while respecting all current risk limits and constraints. Returns specific recommended allocations and expected risk reduction. Automatically optimizes the user's current portfolio unless a specific portfolio is requested. Use when users want to minimize portfolio risk or ask how to reduce risk optimally.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_name": {
                    "type": "string",
                    "description": "Name of the portfolio to optimize. Optional - defaults to user's current portfolio. Only specify if user asks to optimize a specific named portfolio."
                }
            },
            "required": []
        },
        "executor": "_execute_min_variance",
        "underlying_function": "run_min_variance"
    },
    
    "optimize_maximum_return": {
        "name": "optimize_maximum_return",
        "description": "Execute algorithmic optimization to find the portfolio allocation with the highest expected return while staying within all risk constraints. Automatically handles missing expected returns by generating temporary estimates using industry ETF methodology and Treasury rates for cash proxies - no manual intervention required. Returns specific recommended allocations and expected return improvement. Automatically optimizes the user's current portfolio unless a specific portfolio is requested. Use when users want to maximize returns within their risk tolerance.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_name": {
                    "type": "string",
                    "description": "Name of the portfolio to optimize. Optional - defaults to user's current portfolio. Only specify if user asks to optimize a specific named portfolio."
                }
            },
            "required": []
        },
        "executor": "_execute_max_return",
        "underlying_function": "run_max_return"
    },
    
    "get_risk_score": {
        "name": "get_risk_score",
        "description": "Calculate comprehensive portfolio risk score (0-100 scale, like a credit score) with detailed breakdown of all risk components: volatility, concentration, factor exposure, and systematic risk. Includes specific risk factors identified, actionable recommendations, and interpretation guide. Automatically analyzes the user's current portfolio unless a specific portfolio is requested. Use this for any risk assessment request, risk score questions, or when users want to understand their overall risk profile.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_name": {
                    "type": "string", 
                    "description": "Name of the portfolio to analyze. Optional - defaults to user's current portfolio. Only specify if user asks to analyze a specific named portfolio."
                }
            },
            "required": []
        },
        "executor": "_execute_risk_score",
        "underlying_function": "run_risk_score_analysis"
    },
    
    "setup_new_portfolio": {
        "name": "setup_new_portfolio",
        "description": "Initialize factor proxy setup for new portfolio configurations by generating market, momentum, value, industry, and subindustry factor proxies. Required before running analysis on newly created portfolios. Use when setting up analysis for a new portfolio or when factor proxies are missing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "use_gpt_subindustry": {
                    "type": "boolean",
                    "description": "Whether to use AI to generate intelligent subindustry peer groups (recommended for better analysis accuracy). Default: true."
                }
            },
            "required": []
        },
        "executor": "_execute_setup_portfolio",
        "underlying_function": "inject_all_proxies"
    },
    
    "estimate_expected_returns": {
        "name": "estimate_expected_returns",
        "description": "Generate expected return estimates for portfolio tickers using industry ETF historical performance as baseline with intelligent cash proxy handling. Uses 10-year lookback period by default (configurable). Cash proxies (like SGOV) use Treasury rates while equities use industry ETF CAGR methodology. Provides systematic return expectations for optimization functions. Note: Based on industry ETF data - users with individual stock research may have higher expectations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tickers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of ticker symbols to estimate returns for. Optional - defaults to current portfolio holdings."
                },
                "method": {
                    "type": "string",
                    "enum": ["historical_average", "capm"],
                    "description": "Estimation methodology. 'historical_average' uses industry ETF CAGR (recommended). Default: historical_average."
                },
                "years_lookback": {
                    "type": "integer",
                    "description": "Years of historical data to analyze for estimates. Default: 10 years (from settings configuration)."
                }
            },
            "required": []
        },
        "executor": "_execute_estimate_returns",
        "underlying_function": "estimate_historical_returns"
    },
    
    "set_expected_returns": {
        "name": "set_expected_returns",
        "description": "Set custom expected return assumptions for specific tickers based on user research and analysis. Overrides automatic return estimation for optimization functions. Use when users have specific return expectations for their holdings or want to override system-generated estimates with their own research.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expected_returns": {
                    "type": "object",
                    "description": "Expected annual returns as percentages for specific tickers. Format: {'TICKER': percentage} (e.g., {'AAPL': 12.5, 'SGOV': 4.2} for 12.5% AAPL, 4.2% SGOV)",
                    "additionalProperties": {"type": "number"}
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "If true, replaces all existing expectations. If false, merges with existing expectations (default: false)."
                }
            },
            "required": ["expected_returns"]
        },
        "executor": "_execute_set_returns",
        "underlying_function": "update_portfolio_expected_returns"
    },
    
    "view_current_risk_limits": {
        "name": "view_current_risk_limits",
        "description": "Display current risk tolerance and limit settings including maximum volatility, concentration limits, and factor exposure constraints. Shows all active risk parameters that govern portfolio analysis and optimization. CRITICAL: Use this function when users ask about risk tolerance, risk limits, acceptable risk levels, current settings, or when comparing portfolio risk to their tolerance/limits. Use for any question about 'how much risk am I willing to take' or 'what are my risk settings'. Essential before making risk adjustments or when assessing if portfolio risk is appropriate.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "executor": "_execute_view_risk_limits",
        "underlying_function": "view_current_risk_limits"
    },
    
    "update_risk_limits": {
        "name": "update_risk_limits",
        "description": "Update portfolio risk tolerance and limit settings to match user's preferred risk level. Allows customization of maximum volatility, concentration limits, and factor exposure constraints. Use when users want to adjust their risk tolerance, make portfolio analysis more or less conservative, or when their risk preferences change. Updates the risk limits that govern portfolio analysis and optimization.",
        "input_schema": {
            "type": "object",
            "properties": {
                "risk_limits": {
                    "type": "object",
                    "description": "Dictionary of risk limits to update. Available keys: 'max_volatility' (annualized portfolio volatility, e.g., 0.4 for 40%), 'max_loss' (portfolio loss tolerance, e.g., -0.25 for 25%), 'max_single_stock_weight' (maximum position size, e.g., 0.4 for 40%), 'max_factor_contribution' (factor variance contribution, e.g., 0.3 for 30%), 'max_market_contribution' (market factor variance contribution, e.g., 0.5 for 50%), 'max_industry_contribution' (industry factor variance contribution, e.g., 0.3 for 30%), 'max_single_factor_loss' (single factor loss limit, e.g., -0.1 for 10%). Only include limits you want to change.",
                    "additionalProperties": {"type": "number"}
                },
                "reason": {
                    "type": "string",
                    "description": "Reason for updating risk limits (e.g., 'Changed risk tolerance', 'Market conditions', 'Portfolio rebalancing'). Optional."
                }
            },
            "required": ["risk_limits"]
        },
        "executor": "_execute_update_risk_limits",
        "underlying_function": "update_risk_limits"
    },
    
    "reset_risk_limits": {
        "name": "reset_risk_limits",
        "description": "Reset portfolio risk tolerance and limit settings to system defaults. Restores conservative default risk parameters including moderate volatility limits, concentration constraints, and factor exposure limits. Use when users want to return to default risk settings or when current risk limits are causing optimization issues.",
        "input_schema": {
            "type": "object", 
            "properties": {},
            "required": []
        },
        "executor": "_execute_reset_risk_limits",
        "underlying_function": "reset_risk_limits"
    },
    
    "calculate_portfolio_performance": {
        "name": "calculate_portfolio_performance",
        "description": "Calculate comprehensive portfolio performance metrics including risk-adjusted returns, alpha, beta, Sharpe ratio, Sortino ratio, maximum drawdown, and benchmark comparison. Provides historical performance data rather than estimates. Automatically analyzes the user's current portfolio unless a specific portfolio is requested. Use when users ask about portfolio performance, returns, risk-adjusted metrics, or how the portfolio has performed historically.",
        "input_schema": {
            "type": "object",
            "properties": {
                "portfolio_name": {
                    "type": "string",
                    "description": "Name of the portfolio to analyze. Optional - defaults to user's current portfolio. Only specify if user asks to analyze a specific named portfolio."
                },
                "start_date": {
                    "type": "string",
                    "description": "Analysis start date in YYYY-MM-DD format. Optional - defaults to 5 years ago."
                },
                "end_date": {
                    "type": "string", 
                    "description": "Analysis end date in YYYY-MM-DD format. Optional - defaults to current date."
                },
                "benchmark_ticker": {
                    "type": "string",
                    "description": "Benchmark ticker for comparison (e.g., 'SPY', 'QQQ', 'IWM'). Default: SPY."
                },
                "risk_free_rate": {
                    "type": "number",
                    "description": "Risk-free rate as decimal (e.g., 0.04 for 4%). Optional - defaults to 3-month Treasury rate."
                }
            },
            "required": []
        },
        "executor": "_execute_portfolio_performance",
        "underlying_function": ["calculate_portfolio_performance_metrics", "load_portfolio_config", "standardize_portfolio_input", "display_portfolio_performance_metrics"]
    },

    "list_portfolios": {
        "name": "list_portfolios",
        "description": "List all portfolios saved for the current user. Shows portfolio names and helps users see what portfolios they have available. Use when users ask 'what portfolios do I have?', 'show my portfolios', or want to see their saved portfolio list.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        },
        "executor": "_execute_list_portfolios",
        "underlying_function": "PortfolioManager.get_portfolio_names()"
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
        "underlying_function": "Sets active portfolio in context"
    }
}

def get_function_definitions():
    """Get all function definitions in Claude API format."""
    return [
        {
            "name": func["name"],
            "description": func["description"],
            "input_schema": func["input_schema"]
        }
        for func in AI_FUNCTIONS.values()
    ]

def get_function_examples(function_name):
    """Get examples for a specific function."""
    return AI_FUNCTIONS.get(function_name, {}).get("examples", {})

def get_function_executor(function_name):
    """Get the executor method name for a function."""
    return AI_FUNCTIONS.get(function_name, {}).get("executor")

def get_all_function_names():
    """Get list of all available function names."""
    return list(AI_FUNCTIONS.keys()) 