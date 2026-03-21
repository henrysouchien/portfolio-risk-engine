# Unify Volatility Metrics Access on StockAnalysisResult

## Context
`StockAnalysisResult` has two ways to access volatility data:
- `get_volatility_metrics()` — returns only 2 fields with renamed keys (`monthly_volatility`, `annual_volatility`), drops sharpe/sortino/drawdown
- `result.volatility_metrics` — raw dict with all 5 fields under original keys (`monthly_vol`, `annual_vol`, `sharpe_ratio`, `sortino_ratio`, `max_drawdown`)

This forces callers like `mcp_tools/stock.py` to use BOTH paths to get the full picture. The accessor should be the single source of truth.

## Fix

### Step 1: Update `get_volatility_metrics()` to include all 5 fields
**File:** `core/result_objects/stock_analysis.py` (lines 107-112)

```python
# Before
def get_volatility_metrics(self) -> Dict[str, float]:
    return {
        "monthly_volatility": self.volatility_metrics.get("monthly_vol", 0),
        "annual_volatility": self.volatility_metrics.get("annual_vol", 0)
    }

# After
def get_volatility_metrics(self) -> Dict[str, float]:
    return {
        "monthly_volatility": self.volatility_metrics.get("monthly_vol", 0),
        "annual_volatility": self.volatility_metrics.get("annual_vol", 0),
        "sharpe_ratio": self.volatility_metrics.get("sharpe_ratio", 0),
        "sortino_ratio": self.volatility_metrics.get("sortino_ratio", 0),
        "max_drawdown": self.volatility_metrics.get("max_drawdown", 0),
    }
```

### Step 2: Update `mcp_tools/stock.py` — use accessor only
**File:** `mcp_tools/stock.py` (lines 109-135)

Remove `raw_vol = result.volatility_metrics or {}` and read everything from `vol_metrics`:

```python
vol_metrics = result.get_volatility_metrics()
# No more raw_vol needed

summary = {
    ...
    "annual_volatility": vol_metrics.get("annual_volatility", 0),
    "monthly_volatility": vol_metrics.get("monthly_volatility", 0),
    "sharpe_ratio": vol_metrics.get("sharpe_ratio", 0),
    "sortino_ratio": vol_metrics.get("sortino_ratio", 0),
    "max_drawdown": vol_metrics.get("max_drawdown", 0),
    ...
}
```

### Step 3: Update test mock
**File:** `tests/mcp_tools/test_stock_agent_format.py` (lines 41-42)

Update the `DummyResult.get_volatility_metrics()` mock to return all 5 fields:
```python
def get_volatility_metrics(self):
    return {
        "annual_volatility": 0.24,
        "monthly_volatility": 0.069,
        "sharpe_ratio": 0.5,
        "sortino_ratio": 0.6,
        "max_drawdown": -0.2,
    }
```

### Step 4: Add summary-content test assertion
**File:** `tests/mcp_tools/test_stock_agent_format.py`

Add a test that verifies the summary format includes sharpe/sortino/drawdown keys and that they come from `get_volatility_metrics()` (not raw dict):
```python
def test_summary_includes_performance_metrics():
    result = DummyResult()
    response = _build_summary(result)  # or call analyze_stock with mock
    assert "sharpe_ratio" in response
    assert "sortino_ratio" in response
    assert "max_drawdown" in response
    assert response["sharpe_ratio"] == 0.5  # matches mock
```

### Step 5: Add direct unit test for real StockAnalysisResult accessor
**File:** `tests/core/test_stock_analysis_result.py` (new or add to existing test file for StockAnalysisResult)

Test the real `get_volatility_metrics()` method — not a mock:
```python
def test_get_volatility_metrics_returns_all_five_keys():
    result = StockAnalysisResult(
        ticker="TEST",
        volatility_metrics={"monthly_vol": 0.07, "annual_vol": 0.24, "sharpe_ratio": 0.5, "sortino_ratio": 0.6, "max_drawdown": -0.2},
        ...
    )
    vol = result.get_volatility_metrics()
    assert set(vol.keys()) == {"monthly_volatility", "annual_volatility", "sharpe_ratio", "sortino_ratio", "max_drawdown"}
    assert vol["sharpe_ratio"] == 0.5

def test_get_volatility_metrics_defaults_missing_performance_fields():
    result = StockAnalysisResult(
        ticker="TEST",
        volatility_metrics={"monthly_vol": 0.07, "annual_vol": 0.24},  # no sharpe/sortino/drawdown
        ...
    )
    vol = result.get_volatility_metrics()
    assert vol["sharpe_ratio"] == 0
    assert vol["sortino_ratio"] == 0
    assert vol["max_drawdown"] == 0
```

### What NOT to change
- `get_agent_snapshot()` — reads raw `self.volatility_metrics` directly (internal to the class). Tests expect missing Sharpe to stay `None` (test_stock_agent_snapshot.py line 154-156).
- `to_api_response()` — returns raw dict as-is for backward compat. Fine to keep.
- `to_cli_report()` / `_format_volatility_metrics()` — internal formatting, reads raw dict. Fine to keep.
- Other raw internal readers in stock_analysis.py (lines 228-235, 546-554) — internal to the class, no migration needed.
- `compute_volatility()` in `factor_utils.py` — source function, only produces `monthly_vol`/`annual_vol`. Sharpe/sortino/drawdown are added downstream in `risk_summary.py`. No change needed.

**Note:** The 3 new fields (`sharpe_ratio`, `sortino_ratio`, `max_drawdown`) may be absent from the raw dict if `compute_stock_performance_metrics()` fails (wrapped in try/except in risk_summary.py). The `.get(key, 0)` default in the accessor handles this gracefully — callers get 0, not a KeyError.

## Files Changed

| File | Changes |
|------|---------|
| `core/result_objects/stock_analysis.py` | Add 3 fields to `get_volatility_metrics()` |
| `mcp_tools/stock.py` | Remove `raw_vol`, use accessor only |
| `tests/mcp_tools/test_stock_agent_format.py` | Update mock to return all 5 fields + add summary-content test |
| `tests/core/test_stock_analysis_result.py` (new or existing) | Direct unit test for real `StockAnalysisResult.get_volatility_metrics()` — assert all 5 keys present, assert 0 defaults when sharpe/sortino/drawdown absent |

## Verification
1. Verify `get_volatility_metrics()` returns all 5 keys (values may be 0 if performance metrics computation fails): `python3 -c "from portfolio_risk_engine.data_objects import StockData; from services.stock_service import StockService; r = StockService().analyze_stock(StockData.from_ticker('AAPL')); print(list(r.get_volatility_metrics().keys()))"`
2. Verify MCP summary propagates the keys: `python3 -c "from mcp_tools.stock import analyze_stock; r = analyze_stock(ticker='AAPL', format='summary'); print('sharpe_ratio' in r, 'sortino_ratio' in r, 'max_drawdown' in r)"` — should print `True True True`
3. Run tests: `pytest tests/mcp_tools/test_stock_agent_format.py -q`
