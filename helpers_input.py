#!/usr/bin/env python
# coding: utf-8

# In[2]:


# ─── File: helpers_input.py ──────────────────────────────────
"""
Helpers for ingesting *what-if* portfolio changes.

parse_delta(...)
    • Accepts a YAML file path (optional) and/or an in-memory shift dict.
    • Returns a tuple: (delta_dict, new_weights_dict_or_None).

Precedence rules
----------------
1. If YAML contains `new_weights:` → treat as full replacement; shift_dict ignored.
2. Else, build a *delta* dict:     YAML `delta:` first, then merge/override
   any overlapping keys from `shift_dict`.
3. YAML missing or empty           → use shift_dict alone.
"""

import yaml
from pathlib import Path
from typing import Dict, Tuple, Optional

# Import logging decorators for input validation and parsing
from utils.logging import (
    log_error_handling,
    log_performance,
    log_portfolio_operation_decorator
)

@log_error_handling("medium")
@log_portfolio_operation_decorator("input_parse_shift")
@log_performance(0.1)
def _parse_shift(txt: str) -> float:
    """
    Convert a human-friendly shift string to decimal.

    "+200bp", "-75bps", "1.5%", "-0.01"  →  0.02, -0.0075, 0.015, -0.01
    """
    # LOGGING: Add input validation logging with original and parsed values
    t = txt.strip().lower().replace(" ", "")
    if t.endswith("%"):
        return float(t[:-1]) / 100
    if t.endswith(("bp", "bps")):
        return float(t.rstrip("ps").rstrip("bp")) / 10_000
    return float(t)                       # already decimal

@log_error_handling("medium")
@log_portfolio_operation_decorator("input_parse_delta")
@log_performance(0.5)
def parse_delta(
    yaml_path: Optional[str] = None,
    literal_shift: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, float], Optional[Dict[str, float]]]:
    """
    Parse a what-if scenario from YAML file or inline shift dictionary.

    Supports two input modes:
    1. Full portfolio replacement: YAML contains 'new_weights' with complete decimal allocations
    2. Incremental changes: YAML contains 'delta' with shift strings ("+500bp", "1.5%", etc.)

    Parameters
    ----------
    yaml_path : str | None
        Path to a YAML file that may contain:
        - 'new_weights': Dict with decimal weights (e.g., {'AAPL': 0.25, 'SGOV': 0.15} for 25% AAPL, 15% SGOV)
        - 'delta': Dict with shift strings (e.g., {'AAPL': '+200bp', 'SGOV': '-0.05'})
    literal_shift : dict | None
        In-memory dict of {ticker: shift_string}. Format: {"TICKER": "+500bp"} or {"TICKER": "1.5%"}
        Overrides YAML deltas if both are provided.

    Returns
    -------
    (delta_dict, new_weights_dict_or_None) : Tuple[Dict[str, float], Optional[Dict[str, float]]]
        - delta_dict: Parsed shift amounts as decimals (empty if new_weights provided)
        - new_weights_dict_or_None: Normalized decimal weights if 'new_weights' found, None otherwise
        
    Examples
    --------
    YAML with full replacement:
        new_weights:
            AAPL: 0.25    # 25%
            SGOV: 0.15    # 15%
        Returns: ({}, {'AAPL': 0.625, 'SGOV': 0.375})  # Normalized to sum=1.0
    
    YAML with incremental changes:
        delta:
            AAPL: "+200bp"  # +2%
            SGOV: "-0.05"   # -5%
        Returns: ({'AAPL': 0.02, 'SGOV': -0.05}, None)
    """
    # LOGGING: Log function entry with parameters yaml_path and literal_shift type/presence
    delta: Dict[str, float] = {}
    new_w: Optional[Dict[str, float]] = None

    # ── YAML branch (only if file is present) ─────────────────────────
    if yaml_path and Path(yaml_path).is_file():
        # LOGGING: Log YAML file loading attempt with file path
        cfg = yaml.safe_load(Path(yaml_path).read_text()) or {}
        
        # 1) full-replacement portfolio
        if "new_weights" in cfg:               
            # LOGGING: Log full portfolio replacement mode with new_weights count
            w = {k: float(v) for k, v in cfg["new_weights"].items()}
            from portfolio_risk import normalize_weights
            new_w = normalize_weights(w)
            # LOGGING: Log successful portfolio replacement with normalized weights summary
            return {}, new_w

        # 2) incremental tweaks
        if "delta" in cfg:                     
            # LOGGING: Log incremental delta parsing with delta keys
            delta.update({k: _parse_shift(v) for k, v in cfg["delta"].items()})

    # ── literal shift branch (CLI / notebook) ────────────────────────
    if literal_shift:
        # LOGGING: Log literal shift processing with ticker count and shift values
        delta.update({k: _parse_shift(v) for k, v in literal_shift.items()})

    # ── sanity check -------------------------------------------------------
    if not delta and new_w is None:
        # LOGGING: Log error condition - no valid input provided
        raise ValueError(
            "No delta or new_weights provided (YAML empty and literal_shift is None)"
        )

    # LOGGING: Log successful delta parsing with final delta dict summary
    return delta, new_w


# In[ ]:




