# F7: Self-Proxy Label Resolution (On-Demand)

**Status**: REVIEW v11 — rename helper to remove FMP from name

## Context

Bug F7: self-proxied tickers whose ticker equals its data_symbol (DSU, and similar non-aliased ETFs/funds) show raw ticker codes as driver labels. Root cause: `build_proxy_for_ticker()` assigns `industry: DSU` (self-proxy) based on the `isEtf`/`isFund` flags from the profile provider, but discards `companyName` from the same profile. The label system has no entry for DSU in the canonical map, so both display paths return raw `"DSU"`.

**Scope note**: for non-aliased tickers (ticker == data_symbol), `fetch_profile(ticker)` hits the cache populated during proxy build. For aliased tickers (e.g., `AT.` → `AT.L`), the label fallback would miss cache and either fail gracefully or incur one fresh API call. DSU is the reported bug and has no alias.

## Design

**Pure read-side fix at specific call sites.** Does NOT modify `format_ticker_with_label()` (which is used for generic position rendering — any AAPL stock would incorrectly get labeled `"AAPL (Apple Inc.)"`).

Instead, add a profile-provider fallback at call sites that specifically deal with **industry driver labels**. Both call sites know the context is industry drivers (not arbitrary positions).

### Provider abstraction (important)

The fallback uses `fetch_profile()` at `core/proxy_builder.py:305`, which is the **provider-agnostic wrapper** that routes through `ProviderRegistry.get_profile_provider()` (`providers/registry.py:127`) and calls whatever `ProfileMetadataProvider` is registered (Protocol at `providers/interfaces.py:154`). Today that provider happens to be FMP (`FMPProfileProvider` at `providers/fmp_metadata.py:54`), but tomorrow it could be swapped for Yahoo, Polygon, IBKR, or a mock in tests — without changing this label code.

**No FMP coupling**: this plan does NOT import from `providers/fmp_metadata.py` or any FMP-specific module. It uses `core.proxy_builder.fetch_profile`, the same provider-agnostic entry point used by the proxy builder itself. If a future change swaps the profile provider, the label fallback automatically uses the new one.

### Step 1: Add a shared industry-label helper at module level

**File**: `core/result_objects/risk.py`

Add a private module-level helper near the top of the file (after imports):

```python
def _industry_label_with_profile_fallback(
    ticker: str,
    cash_positions: set,
    industry_map: Dict[str, str],
    formatter=None,
) -> str:
    """Label an industry-driver ticker with profile-provider fallback.
    
    Used exclusively by industry-driver rendering paths (risk drivers,
    per-industry group betas, CLI report). Not for generic position labels.
    """
    # `formatter` is injected to preserve the existing ImportError fallback
    # in callers — if format_ticker_with_label was not imported, formatter=None.
    if formatter is None:
        return ticker
    labeled = formatter(ticker, cash_positions, industry_map)
    if labeled != ticker:
        return labeled
    # Fallback: profile provider company name for self-proxied ETFs/funds
    # Uses provider-agnostic fetch_profile() at core/proxy_builder.py:305
    # which routes through the registered ProfileMetadataProvider.
    try:
        from core.proxy_builder import fetch_profile
        profile = fetch_profile(ticker)
        company_name = (
            (profile or {}).get("companyName")
            or (profile or {}).get("name")
            or ""
        ).strip()
        if company_name:
            return f"{ticker} ({company_name})"
    except Exception:
        pass
    return ticker
```

**Callsite 1**: `_build_industry_group_betas_table()` at lines 793 and 806. Replace `format_ticker_with_label(ticker, cash_positions, industry_map)` with `_industry_label_with_profile_fallback(ticker, cash_positions, industry_map, format_ticker_with_label)`.

The existing `except ImportError` at lines 783-786 sets `cash_positions = {}`, `industry_map = {}`. In that state, `format_ticker_with_label` may not be defined. The helper handles this by accepting a `formatter=None` parameter — when the import failed, callers pass `formatter=None` and the helper returns the raw ticker (preserving current behavior).

Adjust callsite 1 to pass `formatter`:

```python
try:
    from utils.etf_mappings import get_etf_to_industry_map, format_ticker_with_label
    from portfolio_risk_engine.portfolio_config import get_cash_positions
    cash_positions = get_cash_positions()
    industry_map = get_etf_to_industry_map()
    formatter = format_ticker_with_label
except ImportError:
    cash_positions = {}
    industry_map = {}
    formatter = None

# ... then at lines 793 and 806:
labeled_etf = _industry_label_with_profile_fallback(ticker, cash_positions, industry_map, formatter)
```

**Callsite 2**: `to_cli_report()` at line 1657-1680 — the CLI report path that embeds into `formatted_report`. Same pattern: import `format_ticker_with_label`, pass as `formatter`. Replace both `format_ticker_with_label()` calls in that block with `_industry_label_with_profile_fallback()`.

### Step 2: Hedge-tool label — `services/factor_intelligence_service.py`

**File**: `services/factor_intelligence_service.py`, inside `_etf_to_sector_label()` closure (~line 1571)

Add profile-provider fallback before returning raw `label_key`:

```python
    if sector_names:
        return sector_names[0]
    # Fallback: profile provider company name for self-proxied ETFs/funds
    try:
        from core.proxy_builder import fetch_profile
        profile = fetch_profile(label_key)
        company_name = (
            (profile or {}).get("companyName")
            or (profile or {}).get("name")
            or ""
        ).strip()
        if company_name:
            return company_name
    except Exception:
        pass
    return label_key
```

Note: `_etf_to_sector_label()` is specifically for industry driver labels in the hedge tool — its scope is already narrow, so an in-function fallback is safe.

### Why this works

- **Scoped to industry drivers only**: both call sites know the context is industry/driver labels. Generic position rendering via `format_ticker_with_label()` is unchanged.
- **Cache hit via `fetch_profile`**: `@cache_company_profile`-decorated. The profile was fetched during `build_proxy_for_ticker()` using the same `data_symbol` (the proxy builder stores `_data_symbol` in the proxy dict). For the common case where `data_symbol == ticker` (no alias), it's a cache hit. For aliased tickers, it's a fresh fetch — acceptable since it only fires when the label would otherwise be raw.
- **Graceful degradation**: if the profile provider is unavailable or the profile has no name, falls through to raw ticker. Same as today. No regression.
- **Lazy import**: `from core.proxy_builder import fetch_profile` inside the try block — avoids circular imports.

## Files changed

| File | Change |
|---|---|
| `core/result_objects/risk.py` | Add module-level `_industry_label_with_profile_fallback()`; use it in `_build_industry_group_betas_table()` (2 callsites) and `to_cli_report()` (2 callsites) |
| `services/factor_intelligence_service.py` | Add profile-provider fallback to `_etf_to_sector_label()` closure |

## Tests

1. **`test_label_industry_ticker_fmp_fallback`**: Unknown ticker in industry driver table. Mock `fetch_profile` returns `{companyName: "BlackRock Debt Strategies"}`. Assert returned label is `"DSU (BlackRock Debt Strategies)"`.
2. **`test_label_industry_ticker_known_etf_no_fmp_call`**: XLK in industry_map. Assert `fetch_profile` NOT called, returns `"XLK (Technology)"`.
3. **`test_label_industry_ticker_fmp_unavailable`**: Mock `fetch_profile` raises. Assert returns raw ticker.
4. **`test_label_industry_ticker_fmp_no_name`**: Mock returns `{}`. Assert returns raw ticker.
5. **`test_etf_to_sector_label_fmp_fallback`**: Ticker not in canonical map. Mock `fetch_profile`. Assert returns company name.
6. **`test_etf_to_sector_label_fmp_unavailable`**: Mock raises. Assert returns raw ticker.
7. **`test_format_ticker_with_label_unchanged`**: Regression test — call `format_ticker_with_label("AAPL", cash_positions, industry_map)` directly. Assert returns raw `"AAPL"` (no provider fallback on generic helper).
8. **`test_industry_label_preserves_import_error_fallback`**: Call `_industry_label_with_profile_fallback("DSU", set(), {}, formatter=None)`. Assert returns raw `"DSU"` (no crash, no provider lookup).
10. **`test_provider_abstraction`**: Register a mock `ProfileMetadataProvider` (not FMP) via the provider registry. Call the helper for an unknown ticker. Assert the mock's `fetch_profile` is called — proving the fallback uses the abstract provider, not a hardcoded FMP path.
9. **`test_to_cli_report_industry_labels`**: Call `to_cli_report()` on a result with DSU in per_group_beta. Mock `fetch_profile`. Assert report contains `"DSU (BlackRock Debt Strategies)"`.

## Verification

Restart service. Use MCP tools:

```
get_risk_analysis(format="agent", include="industry")
# DSU entry should show "DSU (BlackRock Debt Strategies Fund, Inc.)"

get_factor_recommendations(mode="portfolio", format="agent")
# DSU driver should show "BlackRock Debt Strategies Fund, Inc." (no raw ticker)
```

## F7 resolution

| Original F7 step | Status |
|---|---|
| Step 1 (YAML reversal fix) | Done — `906c27aa` |
| Step 2 (DSU YAML entry) | **Superseded** — resolved on-demand via profile provider |
| Step 3 (hardcoded fallback) | **Superseded** — provider fallback handles unknown tickers |
| Step 4 (SGOV cash guard) | Done — `906c27aa` |
| Step 5 (DB INSERT for DSU) | **Superseded** — no DB write needed |

## Codex review history

| Round | Result | Key finding | Fix |
|---|---|---|---|
| R1 | FAIL (4) | Wrong layer, idempotency, name quality, silent fail | v2: orchestrator approach |
| R2 | FAIL (2) | _company_name leaks; fallback path uncovered | v3: pop before any branch |
| R3 | FAIL (1) | Cached proxies skip registration | v4: force cached into missing |
| R4 | FAIL (1) | Other build_proxy_for_ticker callers don't pop _company_name | v5: don't modify proxy dict |
| R5 | FAIL (3) | Check wrong control-flow branch; wrong symbol for profile lookup | v6: unconditional check, _cached_data_symbol |
| R6 | FAIL (2) | industry_proxies is a factor table, not a label store | v7: pure read-side provider-based fallback |
| R7 | FAIL (3) | format_ticker_with_label is generic — would mislabel every stock | v8: scope to industry-driver call sites only |
| R8 | FAIL (3) | to_cli_report still uses raw helper; ImportError fallback not preserved; aliased tickers miss cache | v9: module-level helper covers report path, formatter=None handles import failure, scope claim narrowed to non-aliased self-proxies |
| R9 | PASS | — | — |
| R10 | User concern | "FMP fallback" phrasing implied coupling to FMP | v10: clarified that `fetch_profile()` is provider-agnostic (routes via `ProviderRegistry.get_profile_provider()` → `ProfileMetadataProvider` Protocol). Added test 10 to verify provider abstraction. Phrasing updated throughout. |
