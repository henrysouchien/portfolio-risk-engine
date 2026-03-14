# Modular CLI Architecture Plan

## Overview

Refactor the risk module into standalone, composable CLI modules that can be orchestrated by AI assistants or chained together in pipelines. Each module has clear inputs/outputs and produces machine-readable JSON compatible with the existing API/frontend data contracts.

## Goals

1. **AI-Friendly**: Each module is a tool an AI can invoke independently
2. **Composable**: Modules can be chained (output of one feeds input of another)
3. **Consistent**: All modules follow the same interface pattern
4. **Compatible**: JSON output matches existing Result Objects / API responses
5. **Cacheable**: Outputs serve as "memory" for multi-step workflows
6. **MCP-Ready**: CLI modules can be wrapped as MCP tools for direct AI invocation

## Relationship to MCP

CLI modules and MCP tools are complementary:

| Mode | Consumer | Use Case |
|------|----------|----------|
| **CLI** | Shell scripts, AI via bash | Chaining, file I/O, scripting |
| **MCP** | AI directly (Claude Code) | Conversational, no file overhead |

Both call the same service layer and use the same Result Objects. The MCP implementation
(`mcp_server.py`, `mcp_tools/`) wraps CLI functionality for direct AI invocation.

See: `mcp_tools/README.md` for adding MCP tools from CLI modules.

## Current State

### Existing CLI Entry Points

| File | Lines | What It Does | Status |
|------|-------|--------------|--------|
| `run_positions.py` | ~200 | Fetch/consolidate positions from Plaid/SnapTrade | ✅ **Complete** - Has `--format json/cli`, `--output`, `PositionResult`, MCP tool |
| `run_factor_intelligence.py` | 495 | Factor correlations, performance, offsets | ✅ Already standalone |
| `run_risk.py` | 896 | 8 functions bundled together | ❌ Needs extraction |
| `run_portfolio_risk.py` | 932 | Support utilities (not a CLI) | N/A |

### Existing Result Objects (in `core/result_objects.py`)

All have `to_api_response()` and `to_cli_report()` methods:

- `RiskAnalysisResult`
- `RiskScoreResult`
- `OptimizationResult`
- `PerformanceResult`
- `WhatIfResult`
- `StockAnalysisResult`
- `InterpretationResult`
- `FactorCorrelationResult`
- `FactorPerformanceResult`
- `OffsetRecommendationResult`
- `PortfolioOffsetRecommendationResult`

### Existing Services Layer

- `PortfolioService` - Risk analysis orchestration
- `PositionService` - Position aggregation
- `OptimizationService` - Min-var/max-return solving
- `ScenarioService` - What-if execution
- `StockService` - Single stock analysis
- `ReturnsService` - Performance calculation
- `FactorIntelligenceService` - Factor analysis
- `SecurityTypeService` - Asset classification

## Target Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLI MODULES (AI Tools)                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  run_positions.py    Fetch & consolidate positions                   │
│         │                                                            │
│         ▼                                                            │
│  run_classify.py     Classify security types, detect cash            │
│         │                                                            │
│         ▼                                                            │
│  run_analyze.py      Full risk analysis (factor exposures, etc.)     │
│         │                                                            │
│         ├──────────────────┬──────────────────┐                      │
│         ▼                  ▼                  ▼                      │
│  run_score.py       run_optimize.py    run_whatif.py                 │
│  Risk scoring       Min-var/Max-ret    Scenario analysis             │
│                                                                      │
│  run_stock.py       run_performance.py   run_interpret.py            │
│  Single stock       Performance metrics  GPT interpretation          │
│                                                                      │
│  run_factor_intelligence.py (already standalone)                     │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         JSON OUTPUT                                  │
├─────────────────────────────────────────────────────────────────────┤
│  • Uses existing Result Object .to_api_response() format             │
│  • Compatible with frontend TypeScript types                         │
│  • Saved to cache directory as AI "working memory"                   │
└─────────────────────────────────────────────────────────────────────┘
```

## Standard Interface Pattern

Every module follows this pattern:

```python
#!/usr/bin/env python3
"""
Module: run_score.py
Purpose: Calculate portfolio risk score (0-100)

Input:  Portfolio data (from DB, file, or stdin)
Output: RiskScoreResult as JSON
"""

import argparse
import json
import sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description='Calculate portfolio risk score')

    # === INPUT OPTIONS (mutually exclusive) ===
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument('--user-email', help='Fetch portfolio from DB by user email')
    input_group.add_argument('--input', '-i', help='Read portfolio data from JSON file')
    input_group.add_argument('--stdin', action='store_true', help='Read from stdin')

    # === CONTEXT OPTIONS ===
    parser.add_argument('--portfolio', '-p', default='CURRENT_PORTFOLIO',
                        help='Portfolio name (when using --user-email)')

    # === OUTPUT OPTIONS ===
    parser.add_argument('--output', '-o', help='Write output to file (default: stdout)')
    parser.add_argument('--format', '-f', choices=['json', 'cli'], default='json',
                        help='Output format: json (machine) or cli (human)')
    parser.add_argument('--pretty', action='store_true', help='Pretty-print JSON')

    args = parser.parse_args()

    # --- Load Input ---
    if args.input:
        portfolio_data = load_from_file(args.input)
    elif args.stdin:
        portfolio_data = load_from_stdin()
    else:
        portfolio_data = load_from_db(args.user_email, args.portfolio)

    # --- Execute ---
    result = run_risk_score(portfolio_data, return_data=True)

    # --- Format Output ---
    if args.format == 'json':
        output = result.to_api_response()
        output = json.dumps(output, indent=2 if args.pretty else None, default=str)
    else:
        output = result.to_cli_report()

    # --- Write Output ---
    if args.output:
        Path(args.output).write_text(output)
        print(f"Output written to {args.output}", file=sys.stderr)
    else:
        print(output)

if __name__ == '__main__':
    main()
```

## Output JSON Schema

All modules output a consistent envelope:

```json
{
  "module": "risk_score",
  "version": "1.0",
  "timestamp": "2026-01-29T16:30:00Z",
  "status": "success",
  "metadata": {
    "user_email": "user@example.com",
    "portfolio_name": "CURRENT_PORTFOLIO",
    "execution_time_ms": 1250,
    "cache_valid_until": "2026-01-29T17:30:00Z"
  },
  "data": {
    // Result Object's to_api_response() content
  }
}
```

## Cache Directory Structure

```
~/.risk_module/cache/
├── positions_user@example.com_20260129_163000.json
├── classified_user@example.com_20260129_163005.json
├── analysis_user@example.com_20260129_163030.json
├── score_user@example.com_20260129_163045.json
└── ...
```

## Modules to Create

> **Prerequisite Complete:** The conceptual architecture and target folder structure have been defined in [MODULAR_ARCHITECTURE_REFACTOR_PLAN.md](./MODULAR_ARCHITECTURE_REFACTOR_PLAN.md). CLI modules will live in `modules/<domain>/` after migration.

### Phase 1: Add Input/Output to Existing Commands

Modify `run_risk.py` to accept `--input` and `--output` flags on existing subcommands without breaking current behavior.

**Changes:**
- Add `--input` flag to read portfolio from JSON instead of DB
- Add `--output` flag to write result to file
- Add `--format json|cli` flag
- Maintain backward compatibility (no flags = current behavior)

**Files Modified:**
- `run_risk.py`

### Phase 2: Extract First Standalone Module

Create `run_score.py` as proof of concept for the pattern.

**New File:** `run_score.py`

| Aspect | Detail |
|--------|--------|
| Source | Extract from `run_risk.py:run_risk_score()` |
| Service | `PortfolioService` |
| Result Object | `RiskScoreResult` |
| Input | Portfolio JSON or DB fetch |
| Output | Risk score JSON |

### Phase 3: Extract Remaining Modules

| Module | Source | Result Object | Priority |
|--------|--------|---------------|----------|
| `run_analyze.py` | `run_risk.py:run_portfolio()` | `RiskAnalysisResult` | High |
| `run_optimize.py` | `run_risk.py:run_min_variance()`, `run_max_return()` | `OptimizationResult` | High |
| `run_whatif.py` | `run_risk.py:run_what_if()` | `WhatIfResult` | Medium |
| `run_stock.py` | `run_risk.py:run_stock()` | `StockAnalysisResult` | Medium |
| `run_performance.py` | `run_risk.py:run_portfolio_performance()` | `PerformanceResult` | Medium |
| `run_interpret.py` | `run_risk.py:run_and_interpret()` | `InterpretationResult` | Low |
| `run_classify.py` | New (wraps SecurityTypeService) | New `ClassificationResult` | Low |

### Phase 4: Create Classification Module

New module for security type classification (currently embedded in analysis flow).

**New File:** `run_classify.py`

| Aspect | Detail |
|--------|--------|
| Purpose | Classify securities, detect cash, identify derivatives |
| Service | `SecurityTypeService` |
| Result Object | New `ClassificationResult` |
| Input | Positions JSON |
| Output | Classified positions with types |

### Phase 5: Refactor run_risk.py

After extraction, `run_risk.py` becomes a thin wrapper that:
1. Provides backward compatibility for existing users
2. Internally calls the new standalone modules
3. Eventually deprecated in favor of individual modules

## AI Workflow Example

```bash
# AI fetches positions
python3 run_positions.py --user-email user@example.com \
  --output ~/.risk_module/cache/positions.json

# AI classifies securities
python3 run_classify.py --input ~/.risk_module/cache/positions.json \
  --output ~/.risk_module/cache/classified.json

# AI runs risk analysis
python3 run_analyze.py --input ~/.risk_module/cache/classified.json \
  --output ~/.risk_module/cache/analysis.json

# User asks: "What's my risk score?"
python3 run_score.py --input ~/.risk_module/cache/analysis.json \
  --format cli

# User asks: "Optimize for minimum variance"
python3 run_optimize.py --input ~/.risk_module/cache/analysis.json \
  --mode min-variance --format cli
```

## Testing Strategy

Each module gets:
1. **Unit tests** for the module logic
2. **Integration test** that runs the CLI with test fixtures
3. **Entry in TESTING_COMMANDS.md** with example usage

Add to `tests/TESTING_COMMANDS.md`:
```markdown
## Position Module Testing
python3 run_positions.py --user-email test@example.com --format json

## Score Module Testing
python3 run_score.py --input fixtures/portfolio.json --format json
python3 run_score.py --user-email test@example.com --format cli
```

## Migration Path

1. **Phase 1**: Non-breaking - adds flags to existing commands
2. **Phase 2-4**: New files - doesn't change existing behavior
3. **Phase 5**: Deprecation warnings in `run_risk.py`, docs updated
4. **Phase 6**: Remove deprecated code (optional, can keep for compatibility)

## Success Criteria

- [ ] All modules follow standard interface pattern
- [ ] JSON output matches existing API response format
- [ ] AI can chain modules without human intervention
- [ ] Existing `run_risk.py` users unaffected during transition
- [ ] TESTING_COMMANDS.md updated with all new modules
- [ ] Each module has integration test

## Open Questions

1. **Cache location**: `~/.risk_module/cache/` or project-local `.cache/`?
2. **Cache expiration**: How long before cached data is stale?
3. **Stdin support**: Do we need piping support (`|`) between modules?
4. **Error format**: Standardize error JSON schema?

---

## Related Documents

- [Modular Architecture Refactor Plan](./MODULAR_ARCHITECTURE_REFACTOR_PLAN.md) - Conceptual architecture & folder structure (✅ complete)
- [Position Module MCP Spec](./completed/POSITION_MODULE_MCP_SPEC.md) - MCP implementation (✅ complete)
- [MCP Extensions Plan](./MCP_EXTENSIONS_PLAN.md) - Future MCP enhancements
- [Position Service Refactor Plan](./POSITION_SERVICE_REFACTOR_PLAN.md) - Cache integration (✅ complete)
- [Position Module Plan](./POSITION_MODULE_PLAN.md) - Position module (✅ complete, transactions pending)
- [MCP Tools README](../../mcp_tools/README.md) - Adding new MCP tools

---

*Document created: 2026-01-29*
*Updated: 2026-02-02*
*Status: Active - Conceptual architecture complete, CLI extraction pending*
