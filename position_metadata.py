#!/usr/bin/env python3
"""
Position Metadata Utility

Provides reference data helpers for position labeling in display functions.
Focuses on cash position detection and simple formatting utilities.
"""

from typing import Dict, Optional, Set, Any
from run_portfolio_risk import get_cash_positions


# Note: The user-specific metadata function is kept for potential future use
# but is not used in the current reference-data-only implementation

def get_position_metadata(user_id: Optional[int] = None, portfolio_name: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """
    [CURRENTLY NOT USED - Kept for future expansion]
    Get position metadata from database for specific user/portfolio.
    
    Args:
        user_id: User ID for database lookup
        portfolio_name: Portfolio name for database lookup
        
    Returns:
        Dict mapping ticker -> {"type": str, "source": str}
    """
    metadata = {}
    
    if user_id and portfolio_name:
        try:
            from inputs.database_client import DatabaseClient
            db_client = DatabaseClient()
            metadata = db_client.get_position_metadata(user_id, portfolio_name)
        except Exception:
            pass
    
    return metadata


def enrich_with_cash_fallbacks(metadata: Dict[str, Dict[str, str]], tickers: Set[str]) -> Dict[str, Dict[str, str]]:
    """
    Add cash position metadata for tickers not in database using get_cash_positions().
    
    Args:
        metadata: Existing metadata from database
        tickers: All tickers in portfolio
        
    Returns:
        Enhanced metadata dictionary
    """
    cash_positions = get_cash_positions()
    
    for ticker in tickers:
        if ticker not in metadata:
            if ticker in cash_positions:
                metadata[ticker] = {"type": "cash", "source": "calculated"}
            else:
                metadata[ticker] = {"type": "equity", "source": "unknown"}
    
    return metadata


def is_cash_position(ticker: str, cash_positions: Set[str]) -> bool:
    """
    Simple helper to check if a ticker is a cash position.
    
    Args:
        ticker: Stock ticker symbol
        cash_positions: Set of known cash proxy tickers
        
    Returns:
        True if ticker is a cash position
    """
    return ticker in cash_positions


# Simplified formatting helpers for future use if needed

def get_metadata_for_portfolio(cfg: Dict[str, Any], 
                              user_id: Optional[int] = None, 
                              portfolio_name: Optional[str] = None) -> Dict[str, Dict[str, str]]:
    """
    [CURRENTLY NOT USED - Kept for reference]
    Get metadata for the portfolio currently being analyzed.
    
    In the simplified implementation, we use reference data only,
    so this function is not needed but kept for potential future use.
    """
    tickers = set(cfg.get("weights", {}).keys())
    
    if user_id and portfolio_name:
        metadata = get_position_metadata(user_id, portfolio_name)
    else:
        metadata = {}
    
    return enrich_with_cash_fallbacks(metadata, tickers) 