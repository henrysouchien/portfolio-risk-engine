# FMP Endpoint Expansion: Institutional Ownership, Insider Trades, ETF Holdings

**Status:** COMPLETE

## Context
The FMP MCP server currently exposes 40 registered endpoints across 16 categories. With a premium FMP subscription, three high-value endpoint categories are available but not yet implemented: institutional ownership (Form 13F), insider trading, and ETF/fund holdings.

## Scope
- **14 new endpoints** registered in `fmp/registry.py` across 3 new categories
- **3 new higher-level MCP tools** (one per category) in dedicated tool files
- **MCP server registration** for the 3 new tools in `fmp_mcp_server.py`
- **Tests** for each tool module + registry-level tests for new endpoint definitions

---

## 1. Register Endpoints in `fmp/registry.py`

All endpoints use `api_version="stable"`, `response_type="list"`. Each registration includes `cache_dir` and `fmp_docs_url` per existing conventions.

### Category: `institutional` (5 endpoints)
| Endpoint Name | Path | Key Params | Cache |
|---|---|---|---|
| `institutional_holders` | `/institutional-ownership/extract-analytics/holder` | `symbol` (req), `year`, `quarter`, `page`, `limit` | TTL 24h, `cache/institutional` |
| `institutional_positions_summary` | `/institutional-ownership/symbol-positions-summary` | `symbol` (req), `year`, `quarter` | TTL 24h, `cache/institutional` |
| `institutional_holder_performance` | `/institutional-ownership/holder-performance-summary` | `cik` (req), `page` | TTL 24h, `cache/institutional` |
| `institutional_industry_breakdown` | `/institutional-ownership/holder-industry-breakdown` | `cik` (req), `year`, `quarter` | TTL 24h, `cache/institutional` |
| `institutional_filings_dates` | `/institutional-ownership/dates` | `cik` (req) | TTL 24h, `cache/institutional` |

FMP docs URLs:
- `institutional_holders`: `https://site.financialmodelingprep.com/developer/docs/stable/institutional-ownership-by-holder`
- `institutional_positions_summary`: `https://site.financialmodelingprep.com/developer/docs/stable/institutional-ownership-positions-summary`
- `institutional_holder_performance`: `https://site.financialmodelingprep.com/developer/docs/stable/holder-performance-summary`
- `institutional_industry_breakdown`: `https://site.financialmodelingprep.com/developer/docs/stable/holder-industry-breakdown`
- `institutional_filings_dates`: `https://site.financialmodelingprep.com/developer/docs/stable/institutional-ownership-dates`

> Using the analytics-enriched endpoint (`extract-analytics/holder`) as the primary holder lookup — it includes share changes and portfolio weight, which is more useful than the raw filing extract.

### Category: `insider` (3 endpoints)
| Endpoint Name | Path | Key Params | Cache |
|---|---|---|---|
| `insider_trades_search` | `/insider-trading/search` | `symbol` (opt), `page`, `limit` | TTL 6h, `cache/insider` |
| `insider_trade_statistics` | `/insider-trading/statistics` | `symbol` (req) | TTL 6h, `cache/insider` |
| `insider_transaction_types` | `/insider-trading-transaction-type` | (none) | HASH_ONLY, `cache/insider` |

FMP docs URLs:
- `insider_trades_search`: `https://site.financialmodelingprep.com/developer/docs/stable/insider-trading-search`
- `insider_trade_statistics`: `https://site.financialmodelingprep.com/developer/docs/stable/insider-trading-statistics`
- `insider_transaction_types`: `https://site.financialmodelingprep.com/developer/docs/stable/insider-trading-transaction-types`

> **Note**: `symbol` is optional at the registry level for `insider_trades_search` (FMP supports paginated browsing without it). The higher-level `get_insider_trades()` tool enforces `symbol` as required.
>
> The `latest` endpoint (market-wide firehose) and `reporting-name` search are lower priority and can be accessed via `fmp_fetch` if needed later.

### Category: `etf` (6 endpoints)
| Endpoint Name | Path | Key Params | Cache |
|---|---|---|---|
| `etf_holdings` | `/etf/holdings` | `symbol` (req) | TTL 24h, `cache/etf` |
| `etf_info` | `/etf/info` | `symbol` (req) | TTL 24h, `cache/etf` |
| `etf_country_weightings` | `/etf/country-weightings` | `symbol` (req) | TTL 24h, `cache/etf` |
| `etf_sector_weightings` | `/etf/sector-weightings` | `symbol` (req) | TTL 24h, `cache/etf` |
| `etf_asset_exposure` | `/etf/asset-exposure` | `symbol` (req) | TTL 24h, `cache/etf` |
| `etf_disclosure` | `/funds/disclosure-holders-latest` | `symbol` (req) | TTL 24h, `cache/etf` |

FMP docs URLs:
- `etf_holdings`: `https://site.financialmodelingprep.com/developer/docs/stable/etf-holdings`
- `etf_info`: `https://site.financialmodelingprep.com/developer/docs/stable/etf-info`
- `etf_country_weightings`: `https://site.financialmodelingprep.com/developer/docs/stable/etf-country-weightings`
- `etf_sector_weightings`: `https://site.financialmodelingprep.com/developer/docs/stable/etf-sector-weightings`
- `etf_asset_exposure`: `https://site.financialmodelingprep.com/developer/docs/stable/etf-asset-exposure`
- `etf_disclosure`: `https://site.financialmodelingprep.com/developer/docs/stable/disclosure-holders-latest`

---

## 2. New MCP Tool Files

### Implementation Conventions (from Codex review)

All three tools follow these patterns established by existing tools:

1. **Caching**: Use `FMPClient().fetch()` (not `fetch_raw()`) to leverage disk cache with the TTLs defined in the registry. Expose `use_cache: bool = True` parameter on each tool.
2. **Partial failure**: Multi-endpoint tools follow `get_market_context()` pattern — per-section `source_status` dict and `warnings` list. Only hard-fail (`status: "error"`) if ALL requested sections fail.
3. **stdout redirect**: Wrap body in `sys.stdout = sys.stderr` / `finally: sys.stdout = _saved` pattern.
4. **Input normalization**: `symbol.upper().strip()` at entry.
5. **Return shape**: Always `{ "status": "success"|"error", ... }`.

### `mcp_tools/institutional.py` — `get_institutional_ownership()`

**Purpose**: Show who's buying/selling a stock institutionally, with portfolio analytics.

**Signature**:
```python
def get_institutional_ownership(
    symbol: str,
    year: Optional[int] = None,
    quarter: Optional[int] = None,
    limit: int = 20,
    format: Literal["summary", "full"] = "summary",
    use_cache: bool = True,
) -> dict
```

**Logic**:
- Parallel fetch via `ThreadPoolExecutor`:
  - `institutional_holders` (analytics endpoint — includes share changes)
  - `institutional_positions_summary` (aggregate stats)
- Per-source `source_status` + `warnings` for partial failures
- Summary format: top holders with name, shares, change, weight, change %
- Full format: all raw data
- Return `{ status, symbol, source_status, warnings, holder_count, top_holders[], positions_summary }`

### `mcp_tools/insider.py` — `get_insider_trades()`

**Purpose**: Show insider buying/selling activity for a stock with summary statistics.

**Signature**:
```python
def get_insider_trades(
    symbol: str,
    limit: int = 20,
    format: Literal["summary", "full"] = "summary",
    use_cache: bool = True,
) -> dict
```

**Logic**:
- Parallel fetch via `ThreadPoolExecutor`:
  - `insider_trades_search` with `symbol` (enforced required here even though registry-optional)
  - `insider_trade_statistics`
- Per-source `source_status` + `warnings` for partial failures
- Summary format: recent trades with date, insider name, title, type (buy/sell), shares, price, value
- Full format: all raw data
- Return `{ status, symbol, source_status, warnings, trade_count, statistics, recent_trades[] }`

### `mcp_tools/etf_funds.py` — `get_etf_holdings()`

**Purpose**: Break down an ETF's composition — holdings, sector weights, country allocation.

**Signature**:
```python
def get_etf_holdings(
    symbol: str,
    include: Optional[list[str]] = None,  # ["holdings", "sectors", "countries", "info", "exposure", "disclosure"]
    limit: int = 25,
    format: Literal["summary", "full"] = "summary",
    use_cache: bool = True,
) -> dict
```

**Logic**:
- Parallel fetch of selected sections (default all) via `ThreadPoolExecutor`:
  - `etf_holdings`, `etf_sector_weightings`, `etf_country_weightings`, `etf_info`, `etf_asset_exposure`, `etf_disclosure`
- Per-source `source_status` + `warnings` for partial failures (follows `get_market_context()` pattern)
- Summary format: top N holdings (asset, weight%), sector pie, country pie, fund metadata (expense ratio, AUM, inception), top disclosure holders
- Full format: all raw data
- Return `{ status, symbol, source_status, warnings, sections: { holdings[], sectors[], countries[], info{}, exposure[], disclosure[] } }`

---

## 3. MCP Server Registration (`fmp_mcp_server.py`)

Add 3 new imports and `@mcp.tool()` wrapper functions following the existing pattern:
- `get_institutional_ownership` — import from `mcp_tools.institutional`
- `get_insider_trades` — import from `mcp_tools.insider`
- `get_etf_holdings` — import from `mcp_tools.etf_funds`

Each `@mcp.tool()` wrapper must expose and forward the `use_cache: bool = True` parameter to the underlying tool function (consistent with `get_economic_data`, `get_sector_overview`, `get_market_context`, `get_technical_analysis`).

Update the `instructions` string to list the 3 new tools.

---

## 4. Files to Create/Modify

| File | Action |
|---|---|
| `fmp/registry.py` | Add 14 new endpoint registrations (3 new categories) |
| `mcp_tools/institutional.py` | **New** — `get_institutional_ownership()` |
| `mcp_tools/insider.py` | **New** — `get_insider_trades()` |
| `mcp_tools/etf_funds.py` | **New** — `get_etf_holdings()` |
| `fmp_mcp_server.py` | Add 3 new tool imports + `@mcp.tool()` wrappers + update instructions |
| `tests/mcp_tools/test_institutional.py` | **New** — tool tests |
| `tests/mcp_tools/test_insider.py` | **New** — tool tests |
| `tests/mcp_tools/test_etf_funds.py` | **New** — tool tests |
| `tests/fmp/test_registry_expansion.py` | **New** — registry-level tests for new endpoint definitions |

---

## 5. Verification

1. **Registry tests**: `python3 -m pytest tests/fmp/test_registry_expansion.py -v`
2. **Tool tests**: `python3 -m pytest tests/mcp_tools/test_institutional.py tests/mcp_tools/test_insider.py tests/mcp_tools/test_etf_funds.py -v`
3. **Endpoint discovery**: After restart, `fmp_list_endpoints(category="institutional")`, `fmp_list_endpoints(category="insider")`, `fmp_list_endpoints(category="etf")` should show new endpoints
4. **Existing tests pass**: `python3 -m pytest tests/ -x --timeout=30` (no regressions)

### Required Test Coverage

Each tool test file must include cases for:
- **Cache pass-through**: Verify `use_cache` is forwarded to `FMPClient().fetch()` calls (mock and assert `use_cache` kwarg).
- **Partial failure**: One sub-fetch fails while others succeed — tool returns `status: "success"` with `source_status` showing the failure and `warnings` populated. All sub-fetches fail → `status: "error"`.
- **Insider symbol enforcement**: `get_insider_trades()` raises/returns error when called without `symbol`, even though the registry endpoint allows it.
- **Input normalization**: Lowercase/whitespace symbols are uppercased and stripped.
- **Summary vs full format**: Both output shapes are exercised.
