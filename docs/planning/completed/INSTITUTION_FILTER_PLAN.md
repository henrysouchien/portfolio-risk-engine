# Plan: Add Institution Filter to Realized Performance (Full Solution)

## Context

Account-level metadata (`_institution`, `account_id`, `account_name`) now flows through all `fifo_transactions` dicts. This plan adds an `institution` parameter to filter realized performance by brokerage/institution — transactions, positions, AND income.

## Changes (8 files)

### 1. Institution matching utility: `trading_analysis/data_fetcher.py`

Add a reusable function that leverages existing `INSTITUTION_SLUG_ALIASES` (settings.py:602):

```python
def match_institution(institution_value: str, filter_query: str) -> bool:
    """Case-insensitive institution match using alias resolution."""
```

Logic:
1. Normalize both to lowercase, replace `_` and `-` with spaces, strip
2. Resolve both through `INSTITUTION_SLUG_ALIASES` to canonical slugs
3. If both resolve to a slug, compare slugs (exact match)
4. If the filter query IS a canonical slug (e.g., `interactive_brokers`), also check if the value resolves to it
5. Fall back to substring match (either direction) if no alias found
6. This handles: `"ibkr"` matching `"Interactive Brokers LLC"` (both resolve to `interactive_brokers`), `"interactive_brokers"` as slug input, `"interactive-brokers"` with dash

### 2. Income events: `trading_analysis/models.py`

Add `institution` field to `NormalizedIncome` (line 221):
```python
institution: Optional[str] = None
```

### 3. Income events: `trading_analysis/analyzer.py`

Thread `_institution` through income event construction:

**SnapTrade** (line 705-713): `institution=act.brokerage_name or ''`
**Plaid** (line 901-908): `institution=txn.institution or ''`
**IBKR Flex**: Add income handling if applicable, with `institution='ibkr'`

### 4. Core: `core/realized_performance_analysis.py`

Add `institution: Optional[str] = None` to `analyze_realized_performance()` (line 1554).

**Filter transactions** — after line 1589, AFTER backfill injection (so backfill is also filtered):
```python
if institution:
    from trading_analysis.data_fetcher import match_institution
    pre_count = len(fifo_transactions)
    fifo_transactions = [
        t for t in fifo_transactions
        if match_institution(t.get('_institution') or '', institution)
    ]
    warnings.append(f"Institution filter '{institution}': {len(fifo_transactions)}/{pre_count} transactions matched.")
```

**No early return on zero transactions** — the core logic already handles "no txns + current positions" flows (line 1634, 1645). Zero matched transactions is valid when positions exist.

**Filter income** — in `_income_with_currency()` (line 1223), emit the `institution` field from `NormalizedIncome`, then filter in the caller:
```python
# In _income_with_currency, add to each dict:
"institution": inc.institution or '',

# After calling _income_with_currency, filter:
if institution:
    income_list = [i for i in income_list if match_institution(i.get('institution') or '', institution)]
```

**Filter positions** — pass `institution` to `_build_current_positions()`:
```python
def _build_current_positions(positions, institution=None):
    ...
    for pos in positions.data.positions:
        if institution:
            from trading_analysis.data_fetcher import match_institution
            if not match_institution(pos.get('brokerage_name') or '', institution):
                continue
        ...
```

### 5. Position loading: `mcp_tools/performance.py`

In `_load_portfolio_for_performance()` (line 32), add `institution` param. When set, use `consolidate=False` to preserve `brokerage_name`:

```python
def _load_portfolio_for_performance(user_email, portfolio_name, use_cache=True,
                                     start_date=None, end_date=None, institution=None):
    ...
    position_result = position_service.get_all_positions(
        use_cache=use_cache,
        force_refresh=not use_cache,
        consolidate=(institution is None),  # Skip consolidation when filtering by institution
    )
```

Thread `institution` through `get_performance()` → `_run_realized_with_service()` → service → core.

Add `institution` to `get_performance()` signature (line 461):
```python
institution: Optional[str] = None,
```

**Important**: `institution` param is only meaningful for `mode="realized"`. For hypothetical mode, `institution` is ignored and `consolidate` stays `True`. The `institution` param gates the consolidation change — `_load_portfolio_for_performance()` receives `institution=None` for hypothetical calls, so `consolidate=True` is preserved:
```python
# In get_performance():
if mode == "realized":
    return _run_realized_with_service(..., institution=institution)
else:
    # hypothetical path — institution=None, consolidate=True
    ...
```

### 6. Service layer: `services/portfolio_service.py`

Add `institution: Optional[str] = None` to `analyze_realized_performance()` (line 610).

Include in cache key (normalized — strip + lowercase):
```python
inst_key = (institution or '').strip().lower() or 'all'
```

Pass through to core.

### 7. MCP wrapper: `mcp_server.py`

Add `institution: Optional[str] = None` to `get_performance()` (line 205). FastMCP auto-detects parameters. Pass through to `_get_performance()`.

Update docstring with examples:
```
institution: Filter by institution/brokerage (realized mode only).
    Uses alias matching: "ibkr", "interactive brokers", "schwab" etc.
    Ignored when mode="hypothetical".
```

### 8. CLI: `run_risk.py`

Add `--institution` argument (line 926):
```python
parser.add_argument("--institution", default=None,
                    help="Filter by institution name (realized performance only)")
```

Add `institution` param to `run_realized_performance()` (line 835). When set, use `consolidate=False`:
```python
def run_realized_performance(user_email=None, benchmark_ticker="SPY", source="all",
                             return_data=False, institution=None):
    ...
    position_result = position_service.get_all_positions(
        consolidate=(institution is None),  # Skip consolidation when filtering by institution
    )
    ...
    result = PortfolioService(cache_results=True).analyze_realized_performance(
        position_result=position_result,
        user_email=user,
        benchmark_ticker=benchmark_ticker,
        source=source,
        institution=institution,
    )
```

Thread `--institution` through in the CLI dispatch (line 952):
```python
run_realized_performance(
    user_email=args.user_email,
    benchmark_ticker=args.benchmark,
    source=args.source,
    institution=args.institution,
)
```

## Files Changed

| File | Change |
|------|--------|
| `trading_analysis/data_fetcher.py` | Add `match_institution()` utility |
| `trading_analysis/models.py` | Add `institution` field to `NormalizedIncome` |
| `trading_analysis/analyzer.py` | Thread `_institution` through income event construction (~3 sites) |
| `core/realized_performance_analysis.py` | Add `institution` param, filter transactions + positions + income |
| `mcp_tools/performance.py` | Add `institution` param to `get_performance()`, `_load_portfolio_for_performance()`, `_run_realized_with_service()` |
| `services/portfolio_service.py` | Add `institution` param, include in cache key |
| `mcp_server.py` | Add `institution` param to MCP wrapper |
| `run_risk.py` | Add `--institution` CLI arg |

## Edge Cases

- **Backfill transactions**: Filter applied AFTER backfill injection. Backfill entries without `_institution` won't match any filter → excluded (conservative, avoids cross-institution leakage).
- **Zero matched transactions**: NOT an error — core logic supports "no txns + current positions" flows. Warning logged.
- **`institution=None`**: No filtering — existing behavior unchanged. All `Optional[str] = None` defaults preserve existing call signatures.
- **Unconsolidated positions**: When `institution` is set, positions fetched with `consolidate=False`. `_build_current_positions` handles duplicates by summing (line 237), so same-ticker positions from the target institution still consolidate correctly within that institution.
- **Slug/dash/underscore inputs**: `match_institution()` normalizes `_` and `-` to spaces before alias lookup. `"interactive_brokers"`, `"interactive-brokers"`, `"interactive brokers"` all resolve correctly.
- **Test compatibility**: All new params are `Optional[str] = None` — existing test calls and monkeypatched signatures pass without changes. If any test mocks have explicit `**kwargs` rejection, they need `institution=None` added.
- **Source-aligned holdings**: `_build_source_aligned_holdings()` uses raw `position_result` (unfiltered) — acceptable because it's about provider alignment for short-inference, not institution filtering. The institution filter on `_build_current_positions()` is the correct layer for institution-level position filtering.
- **Hypothetical mode**: `institution` param is only meaningful for `mode="realized"`. In hypothetical mode, `institution` is `None` → `consolidate=True` preserved → no behavior change.

## Verification

```bash
# Existing tests still pass
python3 -m pytest tests/trading_analysis/ tests/services/test_ibkr_flex_client.py tests/core/test_realized_performance_analysis.py -v

# MCP: no filter (baseline)
# get_performance(mode="realized")

# MCP: filter by IBKR
# get_performance(mode="realized", institution="ibkr")

# MCP: filter by non-existent (warning, not error — may have positions but no txns)
# get_performance(mode="realized", institution="nonexistent")

# CLI
python3 run_risk.py --realized-performance --user-email hc@henrychien.com --institution "ibkr"
```

## Codex Review History

### Round 1 — 7 issues (4 HIGH)

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | MCP server layer drops param | Added `mcp_server.py` to changes |
| 2 | HIGH | Position consolidation drops brokerage_name | Pass `consolidate=False` when institution filter active |
| 3 | HIGH | Income events lack institution metadata | Thread `_institution` through `NormalizedIncome` |
| 4 | HIGH | Substring matching insufficient | Use `match_institution()` with `INSTITUTION_SLUG_ALIASES` resolution |
| 5 | MED | Backfill bypasses filter | Backfill without `_institution` excluded when filter active |
| 6 | MED | Test signatures may break | New param is `Optional[str] = None` — all existing calls unchanged |
| 7 | LOW | Cache key normalization | Strip + lowercase before keying |

### Round 2 — 6 issues (3 HIGH)

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Zero-txn early return is a regression | Removed early return — core handles zero txns + positions |
| 2 | HIGH | Backfill filter applied before injection | Moved filter to AFTER backfill injection |
| 3 | HIGH | Income filtering path incomplete — `_income_with_currency` doesn't emit institution | Emit `institution` field in income dict, filter in caller |
| 4 | MED | `match_institution()` too weak for slug/dash inputs | Added `_`/`-` to space normalization before alias lookup |
| 5 | MED | Test monkeypatched signatures may break | Noted — `Optional[str] = None` default should be compatible |
| 6 | LOW | File count mismatch in plan header | Fixed: 8 files |

### Round 3 — 4 issues (1 HIGH, 2 MED, 1 LOW)

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | CLI path (`run_risk.py:882`) hardcodes `consolidate=True` — needs same fix as MCP path | Added `institution` param to `run_realized_performance()`, `consolidate=(institution is None)` |
| 2 | MED | `consolidate=False` applied even for hypothetical mode | `institution` only passed for realized mode; hypothetical path sends `institution=None` → `consolidate=True` preserved |
| 3 | MED | `_build_source_aligned_holdings` uses raw positions, bypassing institution filter | Accepted limitation — source-aligned holdings is about provider alignment for short-inference, not institution filtering |
| 4 | LOW | Test monkeypatched signatures may need `institution=None` | All new params are `Optional[str] = None` — compatible |

### Round 4 — 5 issues (0 HIGH, 2 MED, 3 LOW) — APPROVED

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | MED | Silent position drop when `brokerage_name` missing | Add diagnostic warning counting filtered/dropped positions |
| 2 | MED | `_build_source_aligned_holdings` with unconsolidated rows | Pre-existing, won't regress — accepted limitation |
| 3 | LOW | `--source` choices missing `ibkr_flex` | Pre-existing, out of scope |
| 4 | LOW | `match_institution()` vs `should_skip_plaid_institution()` algorithm divergence | Nice-to-have, not blocking |
| 5 | LOW | `NormalizedIncome.institution` field ordering | Place after `source` field (has default) |
