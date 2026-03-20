# Portfolio Date Decoupling — Plan

**Status**: DEFERRED — investigation complete, not pursuing. See "Decision" section below.
**Severity**: Low (architectural cleanup)
**Scope**: `PortfolioData` model, brokerage import paths, callers
**Prerequisite**: Supersedes the hypothetical-mode portions of `HARDCODED_DATE_AUDIT_PLAN.md`. The direct-endpoint fixes (Category B) and copyright fix (Category C) in that plan remain valid and independent.

---

## Background

`PortfolioData` always carries `start_date` and `end_date` fields, but these have fundamentally different meanings depending on the mode:

- **Hypothetical mode** (backtest weights over a date range): Dates define the analysis window. They matter.
- **Realized mode** (actual brokerage positions): Dates are meaningless placeholders stamped from `PORTFOLIO_DEFAULTS`. They get overridden by every consumer, or ignored entirely.

The current design forces every code path — even brokerage imports — to stamp dates, leading to stale defaults, confusion, and the hardcoded-date problems documented in `HARDCODED_DATE_AUDIT_PLAN.md`.

### Evidence: nobody uses these dates for realized mode

| Usage pattern | Sites | What happens |
|---------------|-------|-------------|
| Overridden immediately | app.py:1729, metric_insights.py:221, app.py:4074 | Caller sets own dates |
| Passed through to config dict | config_adapters.py:65, portfolio_service.py:775 | Just forwarding |
| Validated for format | validation_service.py:141-144 | Checks non-empty + parseable |
| Persisted to DB | portfolio_repository.py:140-141 | Stored but not used by realized path |
| Backtest MAX fallback | backtest.py:171 | Hypothetical-only |
| Echoed in API responses | app.py response payloads | Informational |
| **Drives actual computation** | **None** | **Zero sites** |

---

## Design

### Make `start_date` / `end_date` optional on `PortfolioData`

**Current** (`portfolio_risk_engine/data_objects.py`):
```python
@dataclass
class PortfolioData:
    ...
    start_date: str
    end_date: str
```

**After**:
```python
@dataclass
class PortfolioData:
    ...
    start_date: str | None = None
    end_date: str | None = None
```

Dates are only populated when the caller explicitly provides them (hypothetical mode). Realized-mode paths leave them as `None`.

### Consumer changes

Each consumer of `portfolio_data.start_date` / `portfolio_data.end_date` needs to handle `None`. Categorized by effort:

#### Already safe (no change needed)

These sites override the dates or don't rely on them:

| Site | Why safe |
|------|----------|
| app.py:1729-1732 (performance API) | Overrides with `end_date or date.today().isoformat()` — already handles None |
| mcp_tools/metric_insights.py:221-224 | Overrides both dates unconditionally |
| app.py:4074-4077 (prewarm) | Overrides both dates unconditionally |
| app.py response payloads | Just echoes — `None` is fine in JSON |

#### Small changes needed

| Site | Current | Change |
|------|---------|--------|
| `config_adapters.py:65-66` | `config["start_date"] = portfolio_data.start_date` | Skip or set to `None` — downstream engines accept date params separately |
| `validation_service.py:141-144` | Checks `not portfolio_data.start_date` → error | Skip date validation when both are `None` (realized mode doesn't need it) |
| `validation_service.py:201-202` | Parses dates, checks range | Guard with `if portfolio_data.start_date and portfolio_data.end_date:` |
| `portfolio_service.py:775-776` | Passes dates to `calculate_suggested_risk_limits()` | Pass `None` — function needs to accept optional dates |
| `portfolio_repository.py:140-141` | Extracts dates for DB insert | Store `None` — DB column should be nullable |
| `portfolio_manager.py:244-246` | `update_portfolio_dates()` setter | Still works — can set dates on hypothetical portfolios |
| `backtest.py:171` | Uses `portfolio_data.start_date` as fallback | Already guarded: `default_start_date=portfolio_data.start_date` → resolver handles `None` by falling back to `end - 10 years` |

#### Brokerage import paths — stop stamping dates

| Site | Current | Change |
|------|---------|--------|
| `routes/plaid.py:1079-1080` | Stamps `PORTFOLIO_DEFAULTS` dates into fallback YAML | Remove `dates=` param — let it be `None` |
| `providers/plaid_loader.py:483` | `convert_plaid_df_to_yaml_input()` accepts `dates` dict | Make `dates` optional, skip date keys in YAML when absent |
| `providers/snaptrade_loader.py:1317,1453` | Stamps `PORTFOLIO_DEFAULTS` dates on PortfolioData | Don't pass `start_date`/`end_date` — leave as `None` |
| `inputs/portfolio_assembler.py:318-319` | Falls back to `PORTFOLIO_DEFAULTS` when metadata lacks dates | Fall back to `None` instead — let downstream decide |

#### Hypothetical paths — keep dates

These callers explicitly provide dates and should continue to:

| Site | Behavior |
|------|----------|
| `inputs/portfolio_manager.py:174` — `create_portfolio()` | Caller provides dates or uses defaults for proxy calibration |
| `inputs/legacy_portfolio_file_service.py:77` | Legacy hypothetical YAML generation |
| `app.py` direct endpoints (Category B) | Explicit date params with `_resolve_direct_dates()` |
| `portfolio.yaml` / `config/portfolio.yaml` | Hypothetical portfolio config files |

### Database schema

`start_date` and `end_date` columns in the portfolios table should be nullable:
```sql
ALTER TABLE portfolios ALTER COLUMN start_date DROP NOT NULL;
ALTER TABLE portfolios ALTER COLUMN end_date DROP NOT NULL;
```

Existing rows keep their stored dates. New realized-mode portfolios get `NULL`.

### `PORTFOLIO_DEFAULTS` — keep but narrow scope

`PORTFOLIO_DEFAULTS["start_date"]` and `PORTFOLIO_DEFAULTS["end_date"]` stay in `settings.py` but their role narrows to:
- Default analysis window for **hypothetical portfolios** when the caller doesn't specify dates
- Factor proxy calibration window (`proxy_builder.py:729`)

They should still be made dynamic (per the date audit plan), but they're no longer stamped onto every portfolio.

---

## Relationship to HARDCODED_DATE_AUDIT_PLAN.md

This plan **supersedes Category A** (PORTFOLIO_DEFAULTS root fix) by removing the need for defaults on realized paths entirely. The remaining items from that plan are still valid:

| Item | Status |
|------|--------|
| Category A (PORTFOLIO_DEFAULTS dynamic) | Partially superseded — still make defaults dynamic for hypothetical mode, but they no longer affect realized mode |
| Category A2 (portfolio YAML dates) | Still valid — remove hardcoded dates from YAML files |
| Category A3 (engine config.py) | Still valid — make standalone fallbacks dynamic |
| Category B (direct endpoints) | Independent — still needs `_resolve_direct_dates()` helper |
| Category C (copyright) | Independent — one-line fix |

---

## Tests

1. **PortfolioData with None dates**: Create `PortfolioData` without dates, verify it works through config_adapters, validation (skips date checks), persistence (stores NULL)
2. **Brokerage import no dates**: Plaid/SnapTrade import → PortfolioData has `start_date=None, end_date=None`
3. **Hypothetical with dates**: `create_portfolio()` with explicit dates → PortfolioData has dates populated
4. **Performance API with None dates**: Load realized portfolio (None dates) → performance endpoint overrides with dynamic dates → analysis succeeds
5. **Risk analysis with None dates**: Load realized portfolio → risk score computation handles None dates gracefully
6. **Backtest MAX fallback**: PortfolioData with None dates → backtest resolver falls back to `end - 10 years`
7. **DB round-trip**: Save portfolio with None dates → load → dates are still None

---

## Decision: Deferred

Codex review (v1 FAIL) revealed this is a much larger refactor than scoped:
- Core analysis engines (`build_portfolio_view`, `scenario_analysis`, `portfolio_optimizer`, `efficient_frontier`) require concrete `str` dates — they'd all break on `None`.
- Many more realized-mode writers stamp dates than initially identified (`PositionsData.to_portfolio_data`, `position_service`, `database_client`, `account_registry`).
- DB read path calls `.isoformat()` on dates — NULLs crash load.
- Dataclass field ordering prevents making dates optional without reordering all fields.
- YAML loader hard-indexes `config['start_date']`.

**Root cause**: The dates on `PortfolioData` are a structural requirement of the analysis engine contract, not a meaningful portfolio property. The engines don't have "figure out dates yourself" logic — they expect concrete strings. The current pattern (stamp defaults → override at call site) is pragmatic and already works.

**Action**: Proceed with `HARDCODED_DATE_AUDIT_PLAN.md` instead — make `PORTFOLIO_DEFAULTS` dynamic so the stamped values are always fresh. This solves the staleness problem without touching the engine contract. If the engine contract is ever refactored to accept optional dates, this plan can be revisited.

---

## Original implementation order (not executing)

1. Make `start_date`/`end_date` optional on `PortfolioData` (+ `from_holdings`, `from_yaml`)
2. Update validation_service to skip date checks when both are None
3. Update config_adapters, portfolio_service, portfolio_repository to handle None
4. Remove date stamping from brokerage import paths (Plaid, SnapTrade, assembler)
5. DB migration (nullable columns)
6. Run full test suite
