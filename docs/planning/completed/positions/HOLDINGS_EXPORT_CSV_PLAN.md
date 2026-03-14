# Holdings Export CSV — Backend + Frontend

**Date:** 2026-03-05
**Status:** ✅ COMPLETE (2026-03-05, commit `ebb71edf`)

## Context

The Holdings table has no export capability. User wants export available everywhere: frontend UI button, MCP tool for Claude agent, and direct REST API. The `/api/positions/holdings` endpoint already returns enriched position data (sectors, risk metrics, alerts). We add a sibling endpoint that returns the same data as a downloadable CSV, plus an MCP tool that writes to disk.

## Architecture

```
Frontend button → GET /api/positions/export?format=csv → StreamingResponse (file download)
MCP tool        → export_holdings(format='csv')        → writes file, returns file_path
Both reuse      → build_export_rows(positions)          → shared CSV row builder in services/
```

---

## Phase 1: Backend

### 1a. Shared CSV builder — `services/position_service.py`

Place in `services/position_service.py` (importable by both `routes/` and `mcp_tools/`).

**Corrected field names** from actual `to_monitor_view()` output (`core/result_objects/positions.py:415`) + enrichment fields from `portfolio_service.py`:

```python
EXPORT_COLUMNS = [
    ("Ticker", "ticker"),
    ("Name", "name"),
    ("Type", "type"),
    ("Sector", "sector"),
    ("Asset Class", "asset_class"),
    ("Currency", "currency"),
    ("Shares", "shares"),                   # abs(quantity), set at line 422
    ("Entry Price", "entry_price"),          # weighted entry price
    ("Current Price", "current_price"),      # display price
    ("Cost Basis", "cost_basis"),            # total cost basis USD
    ("Market Value", "gross_exposure"),      # abs(value)
    ("Weight %", "_weight"),                 # computed: gross_exposure / total * 100
    ("P&L $", "pnl_usd"),                   # USD P&L
    ("P&L %", "pnl_percent"),               # percentage P&L
    ("Day Change $", "day_change"),          # from enrich_positions_with_market_data
    ("Day Change %", "day_change_percent"),  # from enrich_positions_with_market_data
    ("Volatility %", "volatility"),          # from enrich_positions_with_risk
    ("Beta", "beta"),                        # from enrich_positions_with_risk
    ("Risk Score", "risk_score"),            # from enrich_positions_with_risk
    ("Max Drawdown %", "max_drawdown"),      # from enrich_positions_with_risk
]

def build_export_rows(positions: list[dict]) -> tuple[list[str], list[list]]:
    """Build CSV-ready (headers, rows) from enriched position dicts."""
    headers = [col[0] for col in EXPORT_COLUMNS]
    total_exposure = sum(abs(p.get("gross_exposure") or 0) for p in positions)
    rows = []
    for p in positions:
        row = []
        for _, key in EXPORT_COLUMNS:
            if key == "_weight":
                ge = p.get("gross_exposure") or 0
                row.append(round(ge / total_exposure * 100, 2) if total_exposure else "")
            else:
                val = p.get(key, "")
                row.append(val if val is not None else "")
        rows.append(row)
    return headers, rows
```

### 1b. Extract shared position loading — `routes/positions.py`

Refactor existing `get_position_holdings()` (lines 138-237):
- Extract the enrichment pipeline (PositionService → sectors → market data → risk → flags → cash proxy) into `_load_enriched_positions(user: dict) -> tuple[PositionResult, dict]`
- Both `/holdings` (returns JSON) and `/export` (returns CSV) call this helper
- Include the `ValueError("consolidation input is empty")` handling → return `(None, _empty_monitor_payload())` for empty portfolios

### 1c. REST endpoint — `GET /api/positions/export`

Add to `routes/positions.py`:

```python
import csv
import io
from fastapi.responses import StreamingResponse

@positions_router.get("/export")
async def export_positions(request: Request, format: str = Query("csv")):
    """Download holdings as CSV file."""
    if format != "csv":
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}. Use 'csv'.")

    session_id = request.cookies.get("session_id")
    user = auth_service.get_user_by_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        result, payload = _load_enriched_positions(user)
        positions = payload.get("positions", [])

        headers, rows = build_export_rows(positions)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(rows)

        date_str = datetime.now().strftime("%Y-%m-%d")
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="holdings_{date_str}.csv"'},
        )
    except ValueError as ve:
        if str(ve) == "consolidation input is empty":
            # Empty portfolio — return CSV with headers only
            headers, _ = build_export_rows([])
            return StreamingResponse(
                iter([",".join(headers) + "\n"]),
                media_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="holdings_empty.csv"'},
            )
        raise HTTPException(status_code=500, detail="Position data error")
    except Exception as e:
        portfolio_logger.error(f"Position export failed: {e}")
        log_error("positions_api", "export", e)
        raise HTTPException(status_code=500, detail="Failed to export holdings")
```

### 1d. MCP tool — `export_holdings` in `mcp_tools/positions.py`

```python
@handle_mcp_errors
def export_holdings(
    user_email: Optional[str] = None,
    format: Literal["csv"] = "csv",
    output: Literal["inline", "file"] = "file",
    institution: Optional[str] = None,
    account: Optional[str] = None,
) -> dict:
    """Export portfolio holdings to CSV file.

    Generates a CSV with ticker, name, sector, shares, prices, P&L,
    risk metrics (volatility, beta, risk score), and weight for all
    current positions.
    """
    user, user_context = resolve_user_email(user_email)
    if not user:
        return {"status": "error", "error": format_missing_user_error(user_context)}

    # Resolve user_id for risk enrichment
    user_id = user_context.get("user_id") or 0

    service = PositionService(user)
    try:
        result = service.get_all_positions(consolidate=True)
    except ValueError as ve:
        if str(ve) == "consolidation input is empty":
            headers, _ = build_export_rows([])
            return {"status": "success", "row_count": 0, "columns": headers, "data": []}
        raise

    # Filter by institution/account if requested
    if institution or account:
        from mcp_tools.aliases import match_brokerage
        filtered = result.data.positions
        if institution:
            filtered = [p for p in filtered if match_brokerage(institution, p.get("brokerage_name"))]
        if account:
            acct_upper = account.strip().upper()
            filtered = [p for p in filtered
                        if acct_upper in (str(p.get("account_name", "")).strip().upper(),
                                          str(p.get("account_id", "")).strip().upper())]
        result.data.positions = filtered

    # Build monitor view + enrich (same pipeline as REST /holdings)
    payload = result.to_monitor_view(by_account=False)
    portfolio_svc = PortfolioService()
    payload = portfolio_svc.enrich_positions_with_sectors(payload)
    payload = portfolio_svc.enrich_positions_with_market_data(payload)
    try:
        portfolio_svc.enrich_positions_with_risk(result, payload, "CURRENT_PORTFOLIO", user_id)
    except Exception:
        pass

    positions = payload.get("positions", [])
    headers, rows = build_export_rows(positions)

    if output == "file":
        export_dir = Path("logs/exports")
        export_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        file_path = export_dir / f"holdings_{timestamp}.csv"
        with file_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(rows)
        return {
            "status": "success",
            "file_path": str(file_path.resolve()),
            "row_count": len(rows),
            "columns": headers,
        }
    else:
        # Inline: return as list of dicts
        return {
            "status": "success",
            "row_count": len(rows),
            "columns": headers,
            "data": [dict(zip(headers, row)) for row in rows],
        }
```

### 1e. MCP registration — `mcp_server.py`

Follow existing pattern: import as `_export_holdings`, wrap with `@mcp.tool()`:

```python
# At top (imports):
from mcp_tools.positions import export_holdings as _export_holdings

# Registration (alongside get_positions):
@mcp.tool()
def export_holdings(
    format: Literal["csv"] = "csv",
    output: Literal["inline", "file"] = "file",
    institution: Optional[str] = None,
    account: Optional[str] = None,
) -> dict:
    """Export portfolio holdings to CSV file. ..."""
    return _export_holdings(user_email=None, format=format, output=output, institution=institution, account=account)
```

---

## Phase 2: Frontend

### 2a. Export CSV button — `HoldingsView.tsx`

**File:** `frontend/packages/ui/src/components/portfolio/HoldingsView.tsx`

- Add `Download` to lucide-react imports (line 168)
- Add button in card header (line ~631), after sector filter dropdown:
  ```tsx
  <Button variant="outline" size="sm" onClick={handleExportCsv} className="h-9 text-sm">
    <Download className="w-4 h-4 mr-1.5" />
    Export
  </Button>
  ```
- Use `fetch` + Blob with `loadRuntimeConfig().apiBaseUrl` to handle both dev proxy and production deployments:
  ```tsx
  import { loadRuntimeConfig } from "@risk/chassis"

  const handleExportCsv = async () => {
    try {
      const { apiBaseUrl } = loadRuntimeConfig();
      const response = await fetch(`${apiBaseUrl}/api/positions/export?format=csv`, {
        credentials: 'include',  // Send session cookie
      });
      if (!response.ok) throw new Error('Export failed');
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `holdings_${new Date().toISOString().split('T')[0]}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // Silently fail — could add toast notification later
    }
  };
  ```

Note: `loadRuntimeConfig().apiBaseUrl` resolves to `VITE_API_URL` (or `http://localhost:5001` default). This matches how `APIService` constructs URLs, ensuring correct routing in both dev and production.

No container changes, no new props.

---

## Files Modified

| File | Changes |
|------|---------|
| `services/position_service.py` | Add `EXPORT_COLUMNS` and `build_export_rows()` |
| `routes/positions.py` | Extract `_load_enriched_positions()`, add `GET /export` endpoint, add `csv`/`io`/`StreamingResponse` imports |
| `mcp_tools/positions.py` | Add `export_holdings()` function |
| `mcp_server.py` | Import + register `export_holdings` tool |
| `frontend/.../HoldingsView.tsx` | Add `Download` import + Export button + `handleExportCsv` |

## Verification

1. `pytest tests/` — existing position tests still pass
2. `cd frontend && pnpm typecheck` — must pass
3. `curl -b cookies.txt http://localhost:5001/api/positions/export?format=csv` — returns CSV with correct headers
4. `curl http://localhost:5001/api/positions/export?format=json` — returns 400 "Unsupported format"
5. MCP: Call `export_holdings(output="file")` → file written to `logs/exports/`, verify CSV contents
6. MCP: Call `export_holdings(output="inline")` → returns data as list of dicts
7. Chrome: Holdings → Export button → CSV downloads with correct data
