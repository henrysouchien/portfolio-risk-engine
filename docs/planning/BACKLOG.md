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
- [ ] `get_sector_overview` batch mode — accept `symbols` param for per-stock vs industry P/E comparison
- [ ] `get_news` / `get_events_calendar` — re-add portfolio auto-fill if cross-server chaining proves cumbersome
- [x] `screen_stocks` — add `is_fund` filter, `volume_max` param

## Infrastructure
- [ ] Refactor `analyze_scenario()`, `optimize_min_variance()`, `optimize_max_return()` away from temp-file pattern
- [ ] Refactor risk limits YAML handling (RiskLimitsData exists but still uses temp files)
