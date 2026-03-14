# Options Module: Data Objects / Result Objects Split

## Context

The `options/models.py` file mixes input config objects (what the user wants to analyze) with output result objects (what came back from analysis) in a single file. The rest of the codebase separates these concerns: `core/data_objects.py` for inputs and `core/result_objects.py` for outputs. Splitting aligns the options module with this convention and makes each file focused.

Additionally, `StrategyAnalysisResult.to_api_response()` currently just aliases `to_dict()` — it should use `make_json_safe()` and return a proper envelope like the rest of the codebase.

## Changes

### 1. Create `options/data_objects.py` — Input config objects

Move from `models.py`:
- `_POSITION_VALUES`, `_OPTION_TYPE_VALUES` constants
- `_parse_expiration()` helper
- `OptionLeg` — unchanged
- `OptionStrategy` — unchanged

These are "what the user wants to analyze" — validation, format standardization, computed properties.

### 2. Create `options/result_objects.py` — Output/transport objects

Move from `models.py`:
- `_GREEKS_SOURCE_VALUES` constant
- `GreeksSnapshot` — unchanged
- `LegAnalysis` — unchanged (imports `OptionLeg` from `data_objects`)
- `StrategyAnalysisResult` — enhanced:
  - `to_api_response()` returns proper envelope: `{"module": "options", "version": "1.0", "timestamp": ..., "status": "success", "data": self.to_dict()}`, wrapped with `make_json_safe()` from `utils/serialization.py`
  - Add optional `status` field (default `"success"`) and `error` field (default `None`) to `StrategyAnalysisResult`
  - `to_api_response()` branches on status: success → `{"module", "version", "timestamp", "status": "success", "data": self.to_dict()}`; error → `{"module", "version", "timestamp", "status": "error", "error": self.error}`
  - Add `@classmethod from_error(cls, error_msg, strategy=None, warnings=None)` factory — if no strategy provided, constructs a sentinel `OptionStrategy` with a single dummy `OptionLeg(position="long", option_type="call", premium=0, strike=1, expiration=date.today())`. Sets `status="error"` and `error=error_msg`. Numeric defaults: `net_premium=0.0`, all other analysis fields `None` or empty list. Sentinel data is never serialized since `to_api_response()` uses the error branch.
  - Imports `OptionLeg`, `OptionStrategy` from `data_objects`

### 3. Replace `options/models.py` with compatibility shim

Replace contents with re-exports from the new files so any external `from options.models import ...` continues to work:

```python
"""Compatibility shim — import from options.data_objects / options.result_objects instead."""
from options.data_objects import *  # noqa: F401,F403
from options.result_objects import *  # noqa: F401,F403
```

Note: Define explicit `__all__` in both `options/data_objects.py` and `options/result_objects.py` to control what `import *` re-exports. Public classes only — private helpers (`_parse_expiration`, `_POSITION_VALUES`, etc.) are excluded.

### 4. Update `options/__init__.py`

Change imports from `options.models` → `options.data_objects` and `options.result_objects`.

### 5. Update internal imports

Files that import directly from `options.models`:
- `options/payoff.py` — imports `OptionLeg`, `OptionStrategy`, `LegAnalysis` → split across `data_objects` and `result_objects`
- `options/greeks.py` — imports `GreeksSnapshot` → from `result_objects`
- `options/analyzer.py` — imports everything → split across both files

Files that do NOT need import changes (already import from package or sibling):
- `options/chain_analysis.py` — imports from `.payoff`, not `.models`
- `mcp_tools/options.py` — imports from `options` package, not `options.models`

### 6. Update test imports

Only these two files import directly from `options.models`:
- `tests/options/test_payoff.py`
- `tests/options/test_analyzer.py`

These files import from `options` package (no change needed):
- `tests/options/test_greeks.py`
- `tests/options/test_mcp_options.py`

## Files Modified

| File | Action |
|------|--------|
| `options/data_objects.py` | **New** — OptionLeg, OptionStrategy |
| `options/result_objects.py` | **New** — GreeksSnapshot, LegAnalysis, StrategyAnalysisResult |
| `options/models.py` | **Replace** with compatibility re-export shim |
| `options/__init__.py` | Update imports |
| `options/payoff.py` | Update imports |
| `options/greeks.py` | Update imports |
| `options/analyzer.py` | Update imports |
| `run_options.py` | **New** — CLI runner (argparse, JSON input, report/summary/full/json output) |
| `mcp_tools/options.py` | Remove double-status wrapping for full format |
| `tests/options/test_payoff.py` | Update imports |
| `tests/options/test_analyzer.py` | Update imports |
| `tests/options/test_mcp_options.py` | Add full-format envelope test |

### 7. Add `run_options.py` CLI runner

New file following the pattern of `run_trading_analysis.py` / `run_risk.py`. Argparse-based CLI that:

- Strategy input (mutually exclusive required argparse group — one of these must be provided):
  - `--json <file>` — reads a JSON strategy definition (legs array + optional underlying_symbol, underlying_price, description). Primary input method for multi-leg strategies.
  - `--legs <json_string>` — inline JSON array of leg dicts for quick one-liners. Shell quoting can be fragile for complex payloads — prefer `--json` for multi-leg.
- Underlying context:
  - `--symbol <ticker>` — underlying symbol. If `--price` not given, fetches spot price via FMP profile + `normalize_fmp_price()` from `utils/ticker_resolver.py` (same profile-based pattern used across the codebase).
  - `--price <float>` — explicit underlying price (overrides FMP fetch)
  - CLI flags `--symbol`/`--price` override any values in the JSON file when both are present.
- Analysis options:
  - `--model <bs|black76>` — pricing model (default: `bs`)
  - `--risk-free-rate <float>` — default 0.05
  - `--dividend-yield <float>` — default 0.0
  - `--ibkr` — flag to enable IBKR Greeks enrichment. Validates: symbol or per-leg con_id required; black76 model prints warning and skips enrichment (matching MCP behavior).
  - `--price-range <low,high>` — override payoff chart range
  - `--steps <int>` — payoff table resolution (default 50)
- Output format:
  - `--format <report|summary|full|json>` — `report` (default) uses `to_cli_report()` text output; `summary` uses `to_summary()` (compact JSON); `full` uses `to_dict()` (complete JSON without envelope); `json` uses `to_api_response()` (full envelope with module/version/status)
  - `--output <file>` — write output to file. If `--format report` is combined with `--output`, write `full` JSON to file AND print report to stdout. Otherwise write the selected JSON format to file.
- Flow: parse args → build `OptionLeg`/`OptionStrategy` → call `OptionAnalyzer.analyze()` → optionally `enrich_with_ibkr()` → print/write result
- Error handling: catch `ValueError` (validation), `FileNotFoundError` (`--json`), `json.JSONDecodeError` (malformed input), and generic `Exception` as fallback. Print to stderr, exit 1.

Example usage:
```bash
# Quick bull call spread
python3 run_options.py --symbol AAPL --legs '[
  {"position":"long","option_type":"call","strike":220,"premium":5.50,"expiration":"20260320"},
  {"position":"short","option_type":"call","strike":230,"premium":2.00,"expiration":"20260320"}
]'

# From JSON file with IBKR Greeks
python3 run_options.py --json strategy.json --ibkr --format full

# Protective put with explicit price
python3 run_options.py --symbol TSLA --price 250 --legs '[
  {"position":"long","option_type":"stock","premium":250,"size":100},
  {"position":"long","option_type":"put","strike":240,"premium":8.50,"expiration":"20260320"}
]' --format report
```

### 8. MCP tool compatibility

`mcp_tools/options.py` currently wraps results as `{"status": "success", **result.to_api_response()}`. Since `to_api_response()` will now include its own `status` field in the envelope, the MCP tool should just return `result.to_api_response()` directly for the "full" format (no manual status wrapping). The "summary" and "report" formats remain unchanged — they don't use `to_api_response()`.

The MCP tool's `except` block (`mcp_tools/options.py:176`) continues to return the generic `{"status": "error", "error": str(exc)}` shape — this is the tool-level error envelope, not the result-level one. `from_error()` is for callers that want a typed result object (e.g., future programmatic use), not for MCP exception paths.

## Key Reuse

- `utils/serialization.py::make_json_safe()` — wraps `to_api_response()` output for NaN/numpy safety
- Envelope pattern from `core/result_objects.py::PositionResult` — `module`, `version`, `timestamp` are top-level (flat, not nested in metadata). Success shape includes `data`; error shape includes `error`. Options follows the same flat pattern.

## Verification

1. `python3 -m pytest tests/options/ -v` — all tests pass (existing 21 + new ones)
2. `from options import OptionLeg, OptionStrategy, StrategyAnalysisResult` works
3. `from options.data_objects import OptionLeg` works
4. `from options.result_objects import StrategyAnalysisResult` works
5. `from options.models import OptionLeg` works (compatibility shim)
6. `StrategyAnalysisResult.from_error("test")` returns result with `status="error"`
7. `from_error("test").to_api_response()` returns `{"module": "options", "status": "error", "error": "test", ...}` (no dummy data)
8. Success `result.to_api_response()` returns envelope with `module`, `version`, `timestamp`, `status`, `data` keys
9. Add test in `test_mcp_options.py` for full-format response verifying envelope shape (no double `status`)
10. Add unit tests in `tests/options/test_analyzer.py` (or new `test_result_objects.py`) for:
    - `StrategyAnalysisResult.from_error("msg")` — returns `status="error"`, `error="msg"`
    - `from_error(...).to_api_response()` — returns error envelope (no `data` key)
    - Success `to_api_response()` — returns `module`, `version`, `timestamp`, `status="success"`, `data`
11. `python3 run_options.py --symbol AAPL --price 220 --legs '[{"position":"long","option_type":"call","strike":220,"premium":5.50,"expiration":"20260320"}]'` prints CLI report
12. `python3 run_options.py --help` shows usage
13. `python3 run_options.py` with no `--json`/`--legs` exits with argparse error (required group)
14. `python3 run_options.py --json strategy.json --symbol OVERRIDE` uses OVERRIDE symbol over JSON value
15. `python3 run_options.py --symbol AAPL --legs '[{"position":"long","option_type":"call","strike":220,"premium":5.50,"expiration":"20260320"}]'` without `--price` fetches spot via FMP profile
16. `python3 run_options.py --format report --output /tmp/test.json --legs '[{"position":"long","option_type":"call","strike":220,"premium":5.50,"expiration":"20260320"}]' --symbol AAPL --price 220` prints report to stdout AND writes full JSON to file
17. `python3 run_options.py --format json ...` output contains `module`, `version`, `timestamp`, `status` envelope keys
