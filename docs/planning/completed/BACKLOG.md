# Backlog — Future Improvements

## CLI / Display Polish
- [x] Add `Wt%` column to CLI monitor view (`run_portfolio_risk.py` monitor output)
- [x] Add `Wt%` column to CLI positions view
- [x] Add `weight` field to API response (already done in MCP `get_positions`)
- [x] Add `weight` to `show_api_output.py` positions display

## MCP Tools — Tier 3
- [x] `get_market_context` — composite macro narrative (indices + sectors + movers + calendar in one call)
- [x] `suggest_tax_loss_harvest` — FIFO lot analysis for unrealized loss candidates, wash sale detection

## MCP Tools — Enhancements
- [x] `get_sector_overview` batch mode — accept `symbols` param for per-stock vs industry P/E comparison
- [x] `get_news` / `get_events_calendar` — portfolio auto-fill via `get_portfolio_news` / `get_portfolio_events_calendar` on portfolio-mcp
- [x] `screen_stocks` — add `is_fund` filter, `volume_max` param

## Infrastructure
- [x] Refactor `analyze_scenario()`, `optimize_min_variance()`, `optimize_max_return()` away from temp-file pattern
- [x] Refactor risk limits YAML handling — unified resolvers in `core/config_adapters.py`, temp files eliminated
