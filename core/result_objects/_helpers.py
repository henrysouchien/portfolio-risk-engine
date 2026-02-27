"""Shared helpers for result object serialization and formatting."""

from typing import Dict, Optional, List, Tuple
import pandas as pd
import numpy as np
from datetime import datetime

def _convert_to_json_serializable(obj):
    """Convert pandas objects to JSON-serializable format."""
    if isinstance(obj, pd.DataFrame):
        # Convert DataFrame with timestamp handling
        df_copy = obj.copy()
        
        # Convert any datetime indices to strings - use ISO format for API consistency
        if hasattr(df_copy.index, 'strftime'):
            df_copy.index = df_copy.index.map(lambda x: x.isoformat() if hasattr(x, 'isoformat') else str(x))
        
        # Convert to dict and clean NaN values
        result = df_copy.to_dict()
        return _clean_nan_values(result)
    
    elif isinstance(obj, pd.Series):
        # Convert Series with timestamp handling
        series_copy = obj.copy()
        
        # Convert any datetime indices to strings - use ISO format for API consistency
        if hasattr(series_copy.index, 'strftime'):
            series_copy.index = series_copy.index.map(lambda x: x.isoformat() if hasattr(x, 'isoformat') else str(x))
        
        # Convert to dict and clean NaN values
        result = series_copy.to_dict()
        return _clean_nan_values(result)
    
    elif isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    
    elif isinstance(obj, (np.integer, np.floating)):
        if np.isnan(obj):
            return None
        value = obj.item()
        # Format floats to fixed decimal to prevent scientific notation
        if isinstance(value, float):
            # Use 8 decimal places for precision while avoiding scientific notation
            return round(value, 8)
        return value
    
    elif isinstance(obj, (np.bool_, pd.BooleanDtype, bool)):
        # Handle numpy/pandas booleans by converting to Python bool
        return bool(obj)
    
    elif isinstance(obj, dict):
        return {k: _convert_to_json_serializable(v) for k, v in obj.items()}
    
    elif isinstance(obj, list):
        return [_convert_to_json_serializable(item) for item in obj]
    
    elif isinstance(obj, float):
        # Handle regular Python floats to prevent scientific notation
        if np.isnan(obj):
            return None
        return round(obj, 8)
    
    return obj

def _clean_nan_values(obj):
    """Recursively convert NaN values to None and handle boolean serialization for JSON."""
    if isinstance(obj, dict):
        return {k: _clean_nan_values(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_clean_nan_values(item) for item in obj]
    elif isinstance(obj, float) and (np.isnan(obj) or obj != obj):  # NaN check
        return None
    elif isinstance(obj, (np.bool_, pd.BooleanDtype)):  # Handle pandas/numpy booleans
        return bool(obj)
    elif hasattr(obj, 'item'):  # numpy scalar
        val = obj.item()
        if isinstance(val, float) and (np.isnan(val) or val != val):
            return None
        elif isinstance(val, (bool, np.bool_)):  # Handle boolean numpy scalars
            return bool(val)
        return val
    else:
        return obj

def _format_df_as_text(df: pd.DataFrame,
                       title: Optional[str] = None,
                       max_rows: int = 10,
                       max_cols: Optional[int] = None,
                       row_label_min: int = 10,
                       row_label_max: int = 20,
                       col_min: int = 8,
                       col_max: int = 16,
                       wrap_header: bool = False) -> List[str]:
    """Format a correlation-like DataFrame as aligned text for CLI.

    The formatter auto-adjusts column and row-label widths (within limits) so most
    labels can be shown without truncation while keeping the table compact.

    Parameters
    ----------
    df : pd.DataFrame
        Matrix to render.
    title : Optional[str]
        Optional section title.
    max_rows : int
        Maximum number of rows to display.
    max_cols : Optional[int]
        Maximum number of columns to display (defaults to max_rows if None).
    row_label_min, row_label_max : int
        Min/max width for row labels.
    col_min, col_max : int
        Min/max width for column headers and numeric cells.

    Returns
    -------
    List[str]
        Lines of text ready for printing.
    """
    lines: List[str] = []
    if title:
        lines.append(f"\n{title}")

    if df is None or getattr(df, 'empty', True):
        lines.append("(empty)")
        return lines

    if max_cols is None:
        max_cols = max_rows

    cols_full = list(df.columns)
    rows_full = list(df.index)
    cols = [str(c) for c in cols_full[:max_cols]]
    rows = [str(r) for r in rows_full[:max_rows]]

    sub = df.reindex(index=rows_full[:max_rows], columns=cols_full[:max_cols]).copy()

    # Auto widths within limits
    max_col_label_len = max((len(str(c)) for c in cols), default=col_min)
    col_w = max(col_min, min(col_max, max_col_label_len))

    max_row_label_len = max((len(str(r)) for r in rows), default=row_label_min)
    row_label_w = max(row_label_min, min(row_label_max, max_row_label_len))

    # Header
    header_indent = " " * (row_label_w + 2)
    # Build one or two header lines
    def _split_header(label: str) -> Tuple[str, str]:
        s = str(label)
        # Prefer splitting tokens before ticker in parentheses
        pos = s.find(" (")
        if pos != -1:
            first = s[:pos].strip()
            second = s[pos:].strip()
        else:
            first = s
            second = s[col_w:]
        return first, second

    if wrap_header:
        first_line_parts: List[str] = []
        second_line_parts: List[str] = []
        any_second = False
        for c in cols:
            f1, f2 = _split_header(c)
            f1 = f1[:col_w]
            f2 = f2[:col_w]
            if f2.strip():
                any_second = True
            first_line_parts.append(f1.rjust(col_w))
            second_line_parts.append(f2.rjust(col_w) if f2 else "".rjust(col_w))
        lines.append(header_indent + " ".join(first_line_parts))
        if any_second:
            lines.append(header_indent + " ".join(second_line_parts))
    else:
        header = header_indent + " ".join([str(c)[:col_w].rjust(col_w) for c in cols])
        lines.append(header)

    # Rows
    for r in rows:
        row_label = str(r)[:row_label_w].ljust(row_label_w)
        row_vals: List[str] = []
        for c in cols:
            try:
                v = float(sub.loc[r, c])
                cell = f"{v:+0.2f}".rjust(col_w)
            except Exception:
                cell = "nan".rjust(col_w)
            row_vals.append(cell)
        lines.append(f"{row_label}  " + " ".join(row_vals))

    if df.shape[0] > max_rows or df.shape[1] > max_cols:
        lines.append(
            f"… showing {min(df.shape[0], max_rows)} of {df.shape[0]} rows, "
            f"{min(df.shape[1], max_cols)} of {df.shape[1]} columns"
        )

    return lines

_DEFAULT_INDUSTRY_ABBR_MAP = {
    "Consumer Discretionary": "Cons Disc",
    "Consumer Staples": "Cons Stap",
    "Financial Services": "Fin Services",
    "Communication Services": "Comm Serv",
    "Information Technology": "Info Tech",
}

def _abbreviate_label(label: str, max_width: int, mapping: Optional[Dict[str, str]] = None) -> str:
    """Abbreviate a single label to fit within max_width using mapping and heuristics."""
    s = str(label)
    if mapping and s in mapping:
        s = mapping[s]
    if len(s) <= max_width:
        return s
    words = s.split()
    if not words:
        return s[:max_width]
    if len(words) == 1:
        return s[:max_width]
    # Iteratively reduce the per-word segment length
    for seg in (4, 3, 2):
        parts = [w[:seg] if len(w) > seg else w for w in words]
        candidate = " ".join(parts)
        if len(candidate) <= max_width:
            return candidate
    return s[:max_width]

def _abbreviate_labels(labels: List[str], max_width: int, mapping: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Return a mapping of original → abbreviated labels constrained to max_width."""
    out: Dict[str, str] = {}
    for lab in labels:
        out[str(lab)] = _abbreviate_label(str(lab), max_width, mapping)
    return out

