# Plan: Per-Holding Risk Enrichment in Monitor View

_Created: 2026-02-18_
_Last updated: 2026-02-18 (v2 — addresses Codex review)_

## Context

The position monitor view (`get_positions(format="monitor")`) returns per-holding P&L, exposure, and direction. The risk analysis engine (`get_risk_analysis()`) computes per-holding volatility, beta, max drawdown, risk contribution, etc. — but these live in separate result objects and are never joined together.

This change adds an `include_risk=True` flag to the monitor view that stitches risk metrics onto each position, giving a unified position + risk view in a single call.

## What Already Exists

### Positions side (`get_positions(format="monitor")`)
- Per-holding: ticker, name, type, direction, quantity, entry_price, current_price, cost_basis, gross/net exposure, P&L (dollar + %), weight

### Risk side (`RiskAnalysisResult` internals)
- `asset_vol_summary` — per-holding: `Vol A`, `Max Drawdown` (+ Sharpe, Sortino, Calmar, etc.)
- `stock_betas` — per-holding factor betas including `market`
- `euler_variance_pct` — per-holding % of total portfolio risk (sums to 100%)
- `correlation_matrix` — full cross-holding correlations

All computed today but not surfaced per position.

## Approach: Compose at the PortfolioService Layer

The join happens in `services/portfolio_service.py`, **not** in `core/result_objects.py` or `mcp_tools/`. This keeps:
- `PositionResult` as a pure position transport object (no risk coupling)
- `RiskAnalysisResult` unchanged
- MCP tools as thin pass-throughs

`PortfolioService` already owns both `analyze_portfolio()` and has access to `PositionService` — it's the natural orchestration point for combining position + risk data.

### Data flow

```
MCP tool: get_positions(format="monitor", include_risk=True)
  → PortfolioService.get_monitor_with_risk(position_result, portfolio_name, user_id)
    → 1. position_result.to_monitor_view()                    # existing, unchanged
    → 2. Build portfolio_data from position_result.data       # reuse already-fetched positions
    → 3. Load factor proxies (allow_gpt=False)                # no GPT side effect
    → 4. self.analyze_portfolio(portfolio_data)                # existing, cached
    → 5. Extract per-ticker risk from RiskAnalysisResult
    → 6. Patch each position dict with "risk" key
    → 7. Add portfolio-level risk to summary
  → Return enriched monitor dict
```

No new data objects. The enrichment is a dict-level patch on the monitor output.

### Key design decisions (from Codex review)

1. **No double position fetch.** We build `portfolio_data` from the already-fetched `position_result.data.to_portfolio_data()` instead of calling `_load_portfolio_for_analysis` (which would re-fetch positions from providers). This avoids a redundant provider call and prevents snapshot drift between the positions shown and the risk computed.

2. **No GPT side effects.** We call `ensure_factor_proxies(allow_gpt=False)` so the monitor path never triggers GPT calls for missing factor proxies. If proxies are missing (new ticker added), risk analysis may be slightly less precise but the monitor query stays fast and predictable. The full `get_risk_analysis()` path still uses `allow_gpt=True`.

3. **Service cache is per-instance.** `PortfolioService` creates a new cache per instantiation, so the within-request cache only helps if we call `analyze_portfolio()` multiple times in the same request. Cross-request caching comes from lower-level caches (PositionService 24h TTL, factor proxy DB cache). This is acceptable.

4. **Cash proxy gap in risk_pct.** Monitor excludes cash positions, but risk analysis maps cash aliases to proxies like SGOV which get an `euler_variance_pct`. The displayed `risk_pct` values won't sum to 100% if SGOV (or other cash proxies) are excluded from monitor. We document this: add `risk_pct_note` to the summary explaining the gap.

5. **By-account mode.** When `by_account=True`, un-consolidated monitor rows show multiple entries per ticker. Each gets the same `risk` dict (risk metrics are portfolio-level, not account-level). We add a note that `risk_pct` is portfolio-relative, not per-account. For the initial implementation this is acceptable — pro-rating by account weight is a future enhancement.

## Risk fields to attach (per position)

| Field | Source | Description |
|-------|--------|-------------|
| `volatility` | `asset_vol_summary["Vol A"]` | Annual volatility |
| `beta` | `stock_betas["market"]` | Market factor beta |
| `risk_pct` | `euler_variance_pct` × 100 | % of portfolio risk (sums to ~100%) |
| `max_drawdown` | `asset_vol_summary["Max Drawdown"]` | Worst peak-to-trough decline |

Sharpe/Sortino excluded from default — noisy at individual position level and available in full risk analysis if needed.

## Files to Modify

### 1. `services/portfolio_service.py` — New method

**`get_monitor_with_risk(position_result, portfolio_name, user_id, all_positions=None)`**
- Calls `position_result.to_monitor_view()` for the base monitor dict
- Builds `portfolio_data` using `all_positions` if provided (unfiltered snapshot for full-portfolio risk context), otherwise falls back to `position_result.data.positions`
- Converts to PortfolioData via `PositionsData` → `.to_portfolio_data(portfolio_name=portfolio_name)` (keyword arg — first positional is `start_date`)
- Loads factor proxies via `ensure_factor_proxies(user_id, portfolio_name, tickers, allow_gpt=False)`
- Calls `self.analyze_portfolio(portfolio_data)` for `RiskAnalysisResult`
- Extracts per-ticker risk metrics into a lookup dict
- Patches each position dict: `pos["risk"] = {volatility, beta, risk_pct, max_drawdown}` or `None`
- Adds `summary["portfolio_risk"]` with portfolio-level volatility + herfindahl
- On failure: returns base monitor dict unchanged with `metadata["risk_error"]` set
- Returns the enriched monitor dict

Note: `asset_vol_summary` is serialized as `{metric: {ticker: value}}` (transposed from DataFrame). But inside the method we work with the raw `RiskAnalysisResult` object (DataFrames), not the serialized API response. So we access `result.asset_vol_summary.loc[ticker, "Vol A"]` directly — no transposition issue.

### 2. `mcp_tools/positions.py` — Wire up

- Add `include_risk: bool = False` and `portfolio_name: str = "CURRENT_PORTFOLIO"` parameters
- **Before brokerage filter (line 132)**: if `include_risk=True`, snapshot unfiltered positions: `all_positions = list(result.data.positions)`
- Brokerage filter runs as normal (mutates `result.data.positions`)
- When `format="monitor"` and `include_risk=True`:
  - Resolve user_id (reuse existing pattern from `mcp_tools/risk.py`)
  - Instantiate `PortfolioService` and call `get_monitor_with_risk(result, portfolio_name, user_id, all_positions=all_positions)`
  - The service method uses `all_positions` to build `portfolio_data` for risk analysis (full portfolio context)
  - The monitor view is built from the (possibly filtered) `result` as today
  - Return the enriched dict (with cache_info attached)
- When `include_risk=False` (default): existing behavior, no change
- `include_risk` with non-monitor formats: silently ignored
- Update `TOOL_METADATA` with new parameters

### 3. `mcp_server.py` — Expose parameters

- Add `include_risk: bool = False` and `portfolio_name: str = "CURRENT_PORTFOLIO"` to the `get_positions()` MCP wrapper
- Pass through to `_get_positions()`

## Output Shape

Each position dict gains a `risk` key when `include_risk=True`:

```json
{
  "ticker": "STWD",
  "direction": "LONG",
  "current_price": 18.155,
  "gross_exposure": 19320.84,
  "pnl_percent": -4.29,
  "risk": {
    "volatility": 0.1126,
    "beta": 1.5614,
    "risk_pct": 16.45,
    "max_drawdown": -0.081
  }
}
```

Summary gains `portfolio_risk`:
```json
{
  "summary": {
    "portfolio_risk": {
      "volatility_annual": 0.0937,
      "volatility_monthly": 0.0270,
      "herfindahl": 0.290,
      "risk_pct_coverage": 99.87,
      "risk_pct_note": "risk_pct sums to ~100% across all holdings including cash proxies; monitor view excludes cash positions so displayed values may sum to less"
    }
  }
}
```

Positions without risk data (options, unmapped tickers): `"risk": null`

## Edge Cases

- **Risk analysis fails**: Monitor view returns normally without risk fields; `metadata["risk_error"]` set
- **Positions without risk data** (options, recent IPOs, unmapped tickers): `risk: null`
- **Cash positions**: Excluded from monitor view. Their `risk_pct` (e.g. SGOV ~0.13%) is "missing" from the displayed positions. `risk_pct_coverage` in summary shows how much of the 100% is represented.
- **Brokerage filter**: The MCP tool mutates `result.data.positions` in-place at line 138 before the monitor branch. For risk enrichment, we need the **unfiltered** positions to build `portfolio_data` so risk_pct reflects full portfolio context. Implementation: when `include_risk=True`, snapshot the unfiltered positions (`all_positions = list(result.data.positions)`) **before** the brokerage filter runs (line 132). Pass this snapshot to `get_monitor_with_risk()` to build `portfolio_data`. The brokerage filter then proceeds as normal, producing a filtered monitor view. The risk enrichment step matches on ticker within the (filtered) monitor positions — positions excluded by the filter simply don't appear, but their risk_pct values remain portfolio-relative. Summary totals are computed by `_build_monitor_payload()` over the filtered set as today — no recomputation needed.
- **By-account / unconsolidated mode**: Duplicate ticker rows can occur whenever consolidation is disabled (by-account, brokerage filter, explicit `consolidate=False`). Each duplicate row gets the same `risk` dict — risk metrics are portfolio-relative, not per-account. When computing `risk_pct_coverage`, **always** deduplicate by ticker (use a set) regardless of mode to avoid summing >100%.
- **`include_risk` with non-monitor format**: Silently ignored
- **Missing factor proxies**: `allow_gpt=False` means new tickers without cached proxies may have less precise factor decomposition. Risk analysis still runs with available data.
- **Performance**: First call adds ~2-3s for risk analysis; subsequent calls benefit from lower-level caches (PositionService, factor proxy DB).

## Ticker Matching

Direct string match on `ticker` field. Both the monitor view and risk analysis use the same raw ticker from `PositionsData.positions`. The `fmp_ticker_map` is used internally by risk analysis but the result DataFrames are indexed by the original ticker.

Important: inside `get_monitor_with_risk()` we work with the raw `RiskAnalysisResult` object (pandas DataFrames/Series), not the serialized API dict. So ticker matching is via DataFrame index, not dict keys.

## Verification

1. `get_positions(format="monitor", include_risk=True)` via MCP — confirm risk fields on each position
2. `include_risk=False` (default) — no change to existing behavior
3. Brokerage filter — risk data still present for filtered positions
4. Positions with no risk match get `risk: null`
5. By-account mode — each row gets risk, documented as portfolio-relative
6. Verify no double provider fetch — position_result reused, not re-fetched
7. Verify no GPT calls triggered — `allow_gpt=False` in factor proxy loading
