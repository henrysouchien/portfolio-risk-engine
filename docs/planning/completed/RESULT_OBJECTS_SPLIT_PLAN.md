# Plan: Split `core/result_objects.py` into Domain Modules

## Context

`core/result_objects.py` is 8,342 lines with 17 classes and 5 shared helper functions. It's the largest file in the codebase (355KB) and covers 5 unrelated domains. Classes within each domain have zero cross-references to other domains, making this a clean structural split. The goal is to improve navigability and reduce cognitive load without changing any class interfaces.

## Approach

Convert `core/result_objects.py` into a package `core/result_objects/` with domain-specific submodules. A top-level `__init__.py` re-exports everything so all existing `from core.result_objects import X` statements continue to work unchanged.

## Module Structure

```
core/result_objects/
├── __init__.py                  # Re-exports all classes + helpers for backward compat
├── _helpers.py                  # Shared utilities (lines 63-294, ~230 lines)
├── positions.py                 # PositionResult (~980 lines)
├── risk.py                      # RiskAnalysisResult + RiskScoreResult (~2,430 lines)
├── performance.py               # PerformanceResult (~690 lines)
├── realized_performance.py      # RealizedPerformanceResult + RealizedMetadata + RealizedIncomeMetrics + RealizedPnlBasis (~520 lines)
├── optimization.py              # OptimizationResult (~620 lines)
├── whatif.py                     # WhatIfResult (~923 lines)
├── stock_analysis.py            # StockAnalysisResult (~544 lines)
├── interpretation.py            # InterpretationResult (~174 lines)
└── factor_intelligence.py       # FactorCorrelationResult + FactorPerformanceResult + FactorReturnsResult + OffsetRecommendationResult + PortfolioOffsetRecommendationResult (~1,078 lines)
```

## Internal Dependencies

Only two cross-domain references exist:
1. `WhatIfResult` uses `RiskAnalysisResult` (composition: `current_metrics`, `scenario_metrics`) → `whatif.py` imports from `risk.py`
2. `RealizedPerformanceResult` contains `RealizedMetadata` which contains `RealizedIncomeMetrics` + `RealizedPnlBasis` → all in same file `realized_performance.py`

All other modules are fully independent.

## Implementation Steps

### Step 1: Create `core/result_objects/` package directory

Rename the existing file out of the way (or work alongside it), create the directory structure.

### Step 2: Extract `_helpers.py` (lines 63-294)

Move these shared functions:
- `_convert_to_json_serializable()` (63-118)
- `_clean_nan_values()` (121-139)
- `_format_df_as_text()` (142-254)
- `_DEFAULT_INDUSTRY_ABBR_MAP` (258-264)
- `_abbreviate_label()` (267-285)
- `_abbreviate_labels()` (288-294)

Imports needed: `pandas`, `numpy`, `typing`, `datetime`

### Step 3: Extract each domain module

For each module, move the class(es) with their imports. Line ranges are approximate (include the `@dataclass` decorator line preceding each class). The implementer should use `class ClassName` and `@dataclass` boundaries as the actual cut points.

| Module | Classes | Approx Lines | Imports from _helpers |
|--------|---------|-------------|---------------------|
| `positions.py` | PositionResult | ~296-1273 | `_convert_to_json_serializable`, `_clean_nan_values` |
| `risk.py` | RiskAnalysisResult, RiskScoreResult | ~1276-2818, ~4635-5523 | `_convert_to_json_serializable`, `_clean_nan_values`, `_format_df_as_text`, `_abbreviate_labels`, `_DEFAULT_INDUSTRY_ABBR_MAP` |
| `performance.py` | PerformanceResult | ~3437-4127 | `_convert_to_json_serializable`, `_clean_nan_values` |
| `realized_performance.py` | RealizedIncomeMetrics, RealizedPnlBasis, RealizedMetadata, RealizedPerformanceResult | ~4127-4636 | `_convert_to_json_serializable`, `_clean_nan_values` |
| `optimization.py` | OptimizationResult | ~2818-3437 | `_convert_to_json_serializable`, `_clean_nan_values` |
| `whatif.py` | WhatIfResult | ~5523-6446 | `_convert_to_json_serializable`, `_clean_nan_values` + imports `RiskAnalysisResult` from `.risk` |
| `stock_analysis.py` | StockAnalysisResult | ~6446-6989 | `_convert_to_json_serializable`, `_clean_nan_values` |
| `interpretation.py` | InterpretationResult | ~6989-7164 | `_convert_to_json_serializable` |
| `factor_intelligence.py` | 5 factor/offset classes | ~7164-8342 | `_convert_to_json_serializable`, `_clean_nan_values`, `_format_df_as_text`, `_abbreviate_labels`, `_DEFAULT_INDUSTRY_ABBR_MAP` |

Per-module shared imports (copy to each as needed):
- `from typing import Dict, Any, Optional, List, Union, Tuple`
- `import numbers, math, json`
- `import pandas as pd, numpy as np`
- `from datetime import datetime, UTC`
- `from dataclasses import dataclass, field`
- `from utils.serialization import make_json_safe`

Module-specific imports:
- `positions.py`: `from core.data_objects import PositionsData`
- `risk.py`: `from core.constants import get_asset_class_color, get_asset_class_display_name`
- `whatif.py`: `from core.result_objects.risk import RiskAnalysisResult`

### Step 4: Create `__init__.py` with full re-exports

```python
"""Result objects for structured service layer responses.

This package provides typed result objects for all service-layer outputs.
Classes are organized by domain in submodules, but all are re-exported
here for backward compatibility — existing imports continue to work:

    from core.result_objects import RiskAnalysisResult, PositionResult
"""

from core.result_objects._helpers import (
    _convert_to_json_serializable,
    _clean_nan_values,
    _format_df_as_text,
    _abbreviate_label,
    _abbreviate_labels,
    _DEFAULT_INDUSTRY_ABBR_MAP,
)
from core.result_objects.positions import PositionResult
from core.result_objects.risk import RiskAnalysisResult, RiskScoreResult
from core.result_objects.performance import PerformanceResult
from core.result_objects.realized_performance import (
    RealizedIncomeMetrics,
    RealizedPnlBasis,
    RealizedMetadata,
    RealizedPerformanceResult,
)
from core.result_objects.optimization import OptimizationResult
from core.result_objects.whatif import WhatIfResult
from core.result_objects.stock_analysis import StockAnalysisResult
from core.result_objects.interpretation import InterpretationResult
from core.result_objects.factor_intelligence import (
    FactorCorrelationResult,
    FactorPerformanceResult,
    FactorReturnsResult,
    OffsetRecommendationResult,
    PortfolioOffsetRecommendationResult,
)

__all__ = [
    "PositionResult",
    "RiskAnalysisResult",
    "RiskScoreResult",
    "PerformanceResult",
    "RealizedIncomeMetrics",
    "RealizedPnlBasis",
    "RealizedMetadata",
    "RealizedPerformanceResult",
    "OptimizationResult",
    "WhatIfResult",
    "StockAnalysisResult",
    "InterpretationResult",
    "FactorCorrelationResult",
    "FactorPerformanceResult",
    "FactorReturnsResult",
    "OffsetRecommendationResult",
    "PortfolioOffsetRecommendationResult",
]
```

### Step 5: Delete old `core/result_objects.py`

After the package is in place, the old file must be removed (Python can't have both `core/result_objects.py` and `core/result_objects/` — the package takes precedence but the file should be cleaned up).

## Edge Cases

- **`from core.result_objects import *`**: The new `__all__` explicitly lists 17 classes. The old module implicitly exported some non-underscore imports too. No code in the repo uses `import *` from this module, so this is a non-issue.
- **Pickle/module paths**: After split, new pickles would encode classes under submodule paths (e.g. `core.result_objects.risk.RiskAnalysisResult`). We don't pickle result objects, so this is a non-issue.
- **`@dataclass` decorators**: Line ranges are approximate. The implementer must include the `@dataclass` decorator line (typically 1 line before `class`) when extracting each class.

## Test Patch Fix

`tests/core/test_factor_agent_snapshot.py` line 61 patches `core.result_objects.datetime`. After split, `datetime` lives in the submodule, so update the patch target:
```python
# Before:
patch("core.result_objects.datetime", _FrozenDateTime)
# After:
patch("core.result_objects.factor_intelligence.datetime", _FrozenDateTime)
```

Grep for any other `patch("core.result_objects.` references and update similarly.

## What Does NOT Change

- No class interfaces change
- No method signatures change
- No import statements in consuming code need to change (all re-exported from `__init__.py`)

## Files Modified

| File | Action |
|------|--------|
| `core/result_objects.py` | DELETE (replaced by package) |
| `core/result_objects/__init__.py` | NEW — re-exports |
| `core/result_objects/_helpers.py` | NEW — shared utilities |
| `core/result_objects/positions.py` | NEW — PositionResult |
| `core/result_objects/risk.py` | NEW — RiskAnalysisResult, RiskScoreResult |
| `core/result_objects/performance.py` | NEW — PerformanceResult |
| `core/result_objects/realized_performance.py` | NEW — Realized perf classes |
| `core/result_objects/optimization.py` | NEW — OptimizationResult |
| `core/result_objects/whatif.py` | NEW — WhatIfResult |
| `core/result_objects/stock_analysis.py` | NEW — StockAnalysisResult |
| `core/result_objects/interpretation.py` | NEW — InterpretationResult |
| `core/result_objects/factor_intelligence.py` | NEW — Factor classes |

## Verification

1. **Import check**: `python3 -c "from core.result_objects import PositionResult, RiskAnalysisResult, PerformanceResult, RealizedPerformanceResult, RealizedMetadata, RealizedIncomeMetrics, RealizedPnlBasis, OptimizationResult, WhatIfResult, StockAnalysisResult, InterpretationResult, FactorCorrelationResult, FactorPerformanceResult, FactorReturnsResult, OffsetRecommendationResult, PortfolioOffsetRecommendationResult, RiskScoreResult; print('All 17 classes imported OK')"`
2. **Full test suite**: `python3 -m pytest tests/ --ignore=tests/api -x`
3. **Verify no stale references**: `python3 -c "import core.result_objects; print(dir(core.result_objects))"` — should list all 17 classes
4. **Spot-check domain imports**: `python3 -c "from core.result_objects.factor_intelligence import FactorCorrelationResult; print('Direct import OK')"`
