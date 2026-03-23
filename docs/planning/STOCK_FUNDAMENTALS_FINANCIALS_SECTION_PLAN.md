# Add Financials Section to get_stock_fundamentals

## Context

`get_stock_fundamentals` has valuation ratios, profitability margins, and balance sheet ratios — but no absolute financial figures (Revenue, EBITDA, Net Income, FCF). Adding a "financials" section gives the AI the full picture, consistent with the peer comparison's TTM financials.

## Changes

### 1. Backend: `fmp/tools/stock_fundamentals.py` — new section

**Add "financials" to `VALID_SECTIONS`** (line 29):

```python
VALID_SECTIONS = [
    "profile",
    "quote",
    "financials",    # NEW — TTM absolute figures
    "valuation",
    "profitability",
    "balance_sheet",
    "quality",
    "technicals",
    "chart",
]
```

**Add fetch specs** for quarterly income_statement and cash_flow (limit=4 for TTM):

```python
needs_financials = "financials" in requested_sections
```

```python
if needs_financials:
    fetch_specs.append((
        "quarterly_income",
        "income_statement",
        {"symbol": normalized_symbol, "limit": 4, "period": "quarter"},
    ))
    fetch_specs.append((
        "quarterly_cash_flow",
        "cash_flow",
        {"symbol": normalized_symbol, "limit": 4, "period": "quarter"},
    ))
```

Note: quality section already fetches annual income/cash_flow (limit=3) for YoY trends. The quarterly fetches are separate and don't conflict.

**Add `_build_financials()` builder function:**

```python
def _build_financials(
    quarterly_income: Any,
    quarterly_cash_flow: Any,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Build the financials section with TTM absolute figures."""
    try:
        income_rows = _records_from_payload(quarterly_income)
        cash_flow_rows = _records_from_payload(quarterly_cash_flow)

        section: dict[str, Any] = {}

        # Use parse_fmp_float for safe numeric parsing (handles strings, non-finite, etc.)
        def _ttm_sum(rows: list[dict], field: str) -> float | None:
            """Sum 4 parsed quarterly values. Returns None if fewer than 4 valid."""
            values = []
            for r in rows:
                parsed = parse_fmp_float(r.get(field))
                if parsed is not None and math.isfinite(parsed):
                    values.append(parsed)
            return sum(values) if len(values) == 4 else None

        # TTM Income Statement metrics
        rev = _ttm_sum(income_rows, "revenue")
        if rev is not None:
            section["revenue_ttm"] = rev

        ebitda = _ttm_sum(income_rows, "ebitda")
        if ebitda is not None:
            section["ebitda_ttm"] = ebitda

        ni = _ttm_sum(income_rows, "netIncome")
        if ni is not None:
            section["net_income_ttm"] = ni

        # TTM Cash Flow metrics
        fcf = _ttm_sum(cash_flow_rows, "freeCashFlow")
        if fcf is not None:
            section["free_cash_flow_ttm"] = fcf

        ocf = _ttm_sum(cash_flow_rows, "operatingCashFlow")
        if ocf is not None:
            section["operating_cash_flow_ttm"] = ocf

        capex = _ttm_sum(cash_flow_rows, "capitalExpenditure")
        if capex is not None:
            section["capex_ttm"] = capex

        if not section:
            return None, ["financials: no usable quarterly data returned."]

        # Reporting currency as auxiliary metadata (added after the empty check
        # so currency alone doesn't count as a successful section)
        if income_rows:
            currency = income_rows[0].get("reportedCurrency")
            if currency:
                section["reported_currency"] = currency

        return section, []
    except Exception as exc:
        return None, [f"financials: failed to build section: {exc}"]
```

**Wire into section dispatch** (in the `for section_name in requested_sections` loop):

```python
elif section_name == "financials":
    if fetch_errors.get("quarterly_income"):
        section_warnings.append(
            "financials: failed to fetch quarterly income: "
            + fetch_errors["quarterly_income"]
        )
    if fetch_errors.get("quarterly_cash_flow"):
        section_warnings.append(
            "financials: failed to fetch quarterly cash flow: "
            + fetch_errors["quarterly_cash_flow"]
        )
    section_data, builder_warnings = _build_financials(
        raw_results.get("quarterly_income"),
        raw_results.get("quarterly_cash_flow"),
    )
    section_warnings.extend(builder_warnings)
```

### 2. Tests: `tests/mcp_tools/test_stock_fundamentals.py`

- Add quarterly income/cash_flow mock data (4 quarters)
- Test mock dispatcher must distinguish annual vs quarterly `income_statement`/`cash_flow` calls (different period/limit params) since quality section also fetches these endpoints with annual params
- Test financials section returns TTM sums with correct values
- Test partial quarters (< 4) → field omitted
- Test financials section included in default sections
- Test `include=["financials"]` works standalone (function accepts list[str], not string)
- Test string/non-finite values handled gracefully (via parse_fmp_float)

### 3. Update tool description in two places

**`fmp/tools/stock_fundamentals.py`** — update the function docstring's section list.

**`fmp/server.py`** — update the MCP tool registration description (~line 925) and the top-level server instruction string (~line 67) to include "financials" in the valid section list:
```
- "financials": TTM revenue, EBITDA, net income, FCF, operating cash flow, CapEx
```

## Edge Cases

- Fewer than 4 quarters → field omitted (shows as absent, not zero)
- Negative values preserved (pre-revenue companies, unprofitable companies)
- Currency included for context (`reported_currency`)
- quality section's annual income fetch is unaffected (separate fetch key)

## What Does NOT Change

- Valuation section — unchanged
- Profitability section — unchanged (margins from ratios_ttm)
- Quality section — unchanged (uses annual income for YoY trends)
- Balance sheet — unchanged
- Peer comparison — unchanged (has its own TTM path)

## Files to Modify

| File | Change |
|------|--------|
| `fmp/tools/stock_fundamentals.py` | Add financials to VALID_SECTIONS, add fetch specs, add `_build_financials()`, wire into dispatch |
| `tests/mcp_tools/test_stock_fundamentals.py` | Quarterly mock data + financials assertions |

## Verification

1. `pytest tests/mcp_tools/test_stock_fundamentals.py -q` — passes
2. MCP tool: `get_stock_fundamentals(symbol="AAPL", include="financials")` → returns TTM revenue, EBITDA, net income, FCF
3. MCP tool: `get_stock_fundamentals(symbol="AAPL")` → financials section included in defaults
