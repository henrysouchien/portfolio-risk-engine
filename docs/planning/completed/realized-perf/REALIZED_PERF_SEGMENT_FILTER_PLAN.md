# Realized Performance: Segment Filter by Asset Category

## Context
Realized performance currently shows combined results across all asset types. Users need the ability to see performance for specific categories (equities, options, futures, bonds, real estate) independently. The trading_analysis tool already has a `segment` parameter — this extends the same pattern to realized performance.

## Approach
Add a `segment` parameter (`"all"` | `"equities"` | `"options"` | `"futures"` | `"bonds"` | `"real_estate"` | `"commodities"` | `"crypto"`) threaded through the full call stack. Filter transactions, positions, and MTM events in the engine **after** fetch + institution/account filtering, **before** timeline building.

## Classification Architecture — Hybrid Model

Two orthogonal classification systems exist and both are needed:

1. **Instrument type** (how you're exposed): `equity`, `option`, `futures`, `bond`
   - Source: `_infer_instrument_type_from_transaction()` in `core/realized_performance/_helpers.py:79`
   - Reliable from transaction metadata — `is_option`, `is_futures` flags, symbol patterns

2. **Asset class** (what you're exposed to): `equity`, `bond`, `real_estate`, `commodity`, `crypto`, `cash`
   - Source: `SecurityTypeService.get_asset_classes()` in `services/security_type_service.py:791`
   - 5-tier classification: cash proxy → DB cache → FMP industry → security type → AI fallback
   - Classifies the **underlying security** (e.g., BND → bond, SPG → real_estate, AAPL → equity)

**Why both?** An AAPL option has instrument_type=`option` but underlying asset_class=`equity`. When the user asks "show me my options performance," they want all options regardless of underlying. When they ask "show me my bonds performance," they want BND/AGG (instrument_type=`equity` but asset_class=`bond`). These are orthogonal dimensions — extending `SecurityTypeService` to also return option/futures would conflate "what is this security?" with "how are you holding it?"

### Category Mapping

| Segment | How classified | What matches |
|---------|---------------|-------------|
| `equities` | instrument_type == `equity` AND asset_class == `equity` | Stocks (not REITs, not bond ETFs) |
| `options` | instrument_type == `option` | All options regardless of underlying |
| `futures` | instrument_type == `futures` | All futures contracts |
| `bonds` | instrument_type == `bond` OR asset_class == `bond` | Individual bonds AND bond ETFs (BND, AGG) |
| `real_estate` | asset_class == `real_estate` | REITs (SPG, VNQ, PLD) |
| `commodities` | asset_class == `commodity` | Commodity ETFs (GLD, USO, DBA) |
| `crypto` | asset_class == `crypto` | Crypto ETFs/funds (BITO, GBTC) |

Key rules:
- instrument_type `fx`, `fx_artifact`, `unknown` excluded from all segments (portfolio-level artifacts or unclassifiable)
- asset_class `unknown` or `mixed` routes to `equities` segment (these are SecurityTypeService fallback values for unresolvable tickers, distinct from instrument_type `unknown`)
- Income transactions follow their symbol's category (AAPL dividend → equities)
- For options/futures, instrument_type takes precedence (an AAPL option is "options" not "equities")
- `SecurityTypeService.get_asset_classes()` is called once for all unique symbols to disambiguate equities vs bonds vs real_estate vs commodities vs crypto
- Symbols with asset_class `mixed` or `unknown` fall into `equities` as the default bucket (most mixed ETFs behave like equity exposure)
- `CUR:XXX` tickers: instrument_type inferred as `fx` or `fx_artifact` → excluded from all segments. Cash positions don't belong to any asset segment.
- Income-only symbols (symbols with only dividend/interest rows, no trade rows): must be included in `segment_keep_symbols` if the income's symbol was previously classified. If symbol has no trade rows at all, skip it (cannot classify).
- `segment="all"` preserves existing behavior exactly: provider flows enabled, cash anchor enabled, no filtering.
- Add `excluded_symbols` list to `realized_metadata` for symbols that didn't match any segment, so users can see why a segment is empty

### Codex Review Findings (addressed)

1. **Commodity/mixed ETF gap (HIGH)**: Added `commodities` segment. Symbols with asset_class=`mixed` or `unknown` default to `equities` bucket since most mixed ETFs have equity-like behavior. `realized_metadata` will include `excluded_symbols` list for transparency.

2. **Trading analysis `equities` behavioral break (HIGH)**: Current `equities` in trading_analysis means "not futures" (includes options). We will NOT change trading_analysis semantics. The shared `SEGMENT_INSTRUMENT_TYPES` constant is only used by the new realized performance filter. Trading analysis keeps its existing binary filter but gains an additional `"options"` segment value that splits options out of equities when explicitly requested.

3. **Provider flow/cash anchor disabling (MEDIUM)**: Correct to disable — provider flows are portfolio-level cash flows (deposits/withdrawals) not attributable to any asset segment. Documented with explicit warning in `realized_metadata`.

4. **Position/transaction classification divergence (MEDIUM)**: Use `segment_keep_symbols` (derived from transactions) as the authoritative symbol set for filtering `current_positions` too, rather than independently classifying positions. This ensures consistency.

5. **SecurityTypeService performance (MEDIUM)**: Call `get_asset_classes()` once at the top of segment filtering with all unique symbols. Memoize the result dict and reuse across income/position filtering. For account-aggregated runs, the DB cache layer handles cross-call dedup (90-day TTL).

## Avoiding Duplication with Trading Analysis

`mcp_tools/trading_analysis.py:213-228` already has a segment filter (futures/equities binary). The filtering logic operates on different data shapes (analyzer objects vs raw dicts), so a shared function would need too many params. Instead, extract the **segment-to-types mapping** as a shared constant in `trading_analysis/instrument_meta.py`, then update trading_analysis to use it and add `"options"` support there too.

## Files to Modify (in order)

### 0. Shared Constant — `trading_analysis/instrument_meta.py`
Add `SEGMENT_INSTRUMENT_TYPES` mapping used by both trading_analysis and realized perf:
```python
# Instrument-type level mapping (first pass). Segments needing asset_class
# refinement are marked with _ASSET_CLASS_SEGMENTS.
SEGMENT_INSTRUMENT_TYPES: Dict[str, set[str]] = {
    "equities": {"equity"},
    "options": {"option"},
    "futures": {"futures"},
    "bonds": {"bond"},
    "real_estate": {"equity"},   # REITs have equity instrument_type
    "commodities": {"equity"},   # Commodity ETFs have equity instrument_type
    "crypto": {"equity"},         # Crypto ETFs have equity instrument_type
}

# Segments that require SecurityTypeService.get_asset_classes() for disambiguation
_ASSET_CLASS_SEGMENTS: set[str] = {"equities", "bonds", "real_estate", "commodities", "crypto"}

# Maps segment → required asset_class value from SecurityTypeService
SEGMENT_ASSET_CLASS_MAP: Dict[str, set[str]] = {
    "equities": {"equity", "mixed", "unknown"},  # mixed/unknown default to equities
    "bonds": {"bond"},
    "real_estate": {"real_estate"},
    "commodities": {"commodity"},
    "crypto": {"crypto"},
}
# Excluded sets
_EXCLUDED_INSTRUMENT_TYPES: set[str] = {"fx", "fx_artifact", "unknown"}
_EXCLUDED_ASSET_CLASSES: set[str] = {"cash", "derivative"}
#
# Per-symbol canonical segment assignment (pseudocode):
#
# def assign_canonical_segment(symbol, instrument_type, asset_class):
#     # Step 1: Exclude by instrument_type
#     if instrument_type in _EXCLUDED_INSTRUMENT_TYPES:
#         return None  # excluded from all segments
#
#     # Step 2: Instrument-type segments (no asset_class needed)
#     if instrument_type == "option":
#         return "options"
#     if instrument_type == "futures":
#         return "futures"
#     if instrument_type == "bond":
#         return "bonds"
#
#     # Step 3: Exclude by asset_class
#     if asset_class in _EXCLUDED_ASSET_CLASSES:
#         return None  # excluded from all segments
#
#     # Step 4: Asset-class segments (lookup in SEGMENT_ASSET_CLASS_MAP)
#     for seg, allowed_classes in SEGMENT_ASSET_CLASS_MAP.items():
#         if asset_class in allowed_classes:
#             return seg
#
#     # Step 5: Fallback — unrouted asset_class → "equities"
#     # (covers edge cases where SecurityTypeService returns an unexpected value)
#     return "equities"
#
# Then: segment_keep_symbols = {sym for sym if assign_canonical_segment(sym) == requested_segment}
#
# Note on "unknown":
# - instrument_type "unknown" → excluded (Step 1). These are unclassifiable transactions.
# - asset_class "unknown" → routed to "equities" (Step 4, via SEGMENT_ASSET_CLASS_MAP).
#   This is intentional: SecurityTypeService returns "unknown" for rare unresolvable tickers,
#   and grouping them with equities is the safest default for performance reporting.
```

### 0b. Extend Trading Analysis — `mcp_tools/trading_analysis.py`
**Important**: Do NOT change existing `equities` semantics (currently = "not futures", includes options). Only add new segment values.
- Add `"options"` to the segment Literal: `Literal["all", "equities", "options", "futures"]`
- Add an `elif segment == "options"` branch that filters to `instrument_type == "option"` only
- Existing `equities` branch stays as-is (not-futures). Existing `futures` branch stays as-is.
- Update `mcp_server.py` wrapper for `get_trading_analysis` to match new Literal type
- Note: `bonds`, `real_estate`, `commodities` not added to trading_analysis for now — trading_analysis is trade-focused (P&L per lot) and these categories have minimal trade volume

### 1. Engine — `core/realized_performance/engine.py`
Core filtering logic in `_analyze_realized_performance_single_scope()`.

- Add `segment: str = "all"` to function signature
- Import `SEGMENT_INSTRUMENT_TYPES` from `trading_analysis.instrument_meta`
- Insert filter block after institution/account filtering (~line 430), before inception computation:
  - Build `symbol → instrument_type` map from non-income transactions using `_helpers._infer_instrument_type_from_transaction()`
  - For segments in `_ASSET_CLASS_SEGMENTS` (`equities`, `bonds`, `real_estate`, `commodities`, `crypto`): call `SecurityTypeService.get_asset_classes()` on equity/bond-instrument-type symbols to distinguish stocks vs bonds vs REITs vs commodity ETFs vs crypto ETFs
  - Build `segment_keep_symbols` set: options/futures use instrument_type only; segments in `_ASSET_CLASS_SEGMENTS` (equities, bonds, real_estate, commodities, crypto) use instrument_type + asset_class
  - Filter `fifo_transactions`: non-income txns match by instrument_type (and asset_class for `_ASSET_CLASS_SEGMENTS`). Income txns are kept if their symbol is in `segment_keep_symbols`. Income-only symbols (no trade rows) are NOT classified and are excluded — they cannot be attributed to a segment without a trade to infer instrument type from.
  - Filter `futures_mtm_events` → `[]` unless segment is `"futures"` or `"all"`
  - Filter `current_positions` using `segment_keep_symbols` as the authoritative set (NOT independent classification via `_infer_position_instrument_type()`). This ensures positions and transactions use the same symbol set, avoiding classification drift for bond ETFs, REITs, and other asset-class-dependent segments.
  - **Disable provider flows** (`provider_first_mode = False`, clear `provider_flow_events_raw`) — provider flows are portfolio-level cash flows, not attributable to a segment
  - **Disable cash anchor** (`cash_anchor_requested = False`) — cash positions don't belong to any segment
  - Add warning: `f"Segment filter '{segment}': {len(fifo_transactions)}/{pre_count} transactions matched."`
- After `income_with_currency` is built and institution/account-filtered (~line 506): filter to `segment_keep_symbols`
- Add `"segment": segment` to `realized_metadata` dict in the result

### 2. Aggregation — `core/realized_performance/aggregation.py`
Pass-through only, no filtering logic.

- Add `segment: str = "all"` to `analyze_realized_performance()` signature
- Add `segment: str = "all"` to `_analyze_realized_performance_account_aggregated()` signature
- Pass `segment=segment` to all `engine._analyze_realized_performance_single_scope()` call sites (5 total: 2 in `analyze_realized_performance`, 3+ in `_analyze_realized_performance_account_aggregated`)

### 3. Service — `services/portfolio_service.py`
- Add `segment: str = "all"` to `analyze_realized_performance()` signature
- Append `_{segment}` to `cache_key` string
- Pass `segment=segment` to `_analyze_realized_performance()` call

### 4. MCP Tool — `mcp_tools/performance.py`
- Add `segment: Literal["all", "equities", "options", "futures", "bonds", "real_estate", "commodities", "crypto"] = "all"` to `get_performance()` after `account` param
- Add docstring entries + examples
- Pass `segment=segment` to `_run_realized_with_service()` (only when mode="realized")
- Add `segment` param to `_run_realized_with_service()` and pass through to `PortfolioService`

### 5. MCP Server — `mcp_server.py`
- Add `segment: Literal["all", "equities", "options", "futures", "bonds", "real_estate", "commodities", "crypto"] = "all"` to wrapper `get_performance()` after `account`
- Add docstring entry
- Pass `segment=segment` to `_get_performance()` call
- Update `get_trading_analysis()` wrapper segment Literal to include `"options"`

### 6. REST Endpoint — `routes/realized_performance.py`
- Add `segment: Literal["all", "equities", "options", "futures", "bonds", "real_estate", "commodities", "crypto"] = "all"` to `RealizedPerformanceRequest`
- Pass `segment=body.segment` to `PortfolioService.analyze_realized_performance()`

### 7. Tests — `tests/core/test_realized_performance_segment.py` (new file)
Follow existing pattern from `test_realized_performance_analysis.py` (monkeypatch shims, fake analyzer).

Key tests:
- `test_segment_equities_filters_transactions` — mixed txns, only equity pass (not bond ETFs, not REITs)
- `test_segment_options_filters_transactions` — only option txns pass
- `test_segment_futures_filters_transactions` — only futures txns pass, MTM events kept
- `test_segment_bonds_includes_bond_etfs` — BND classified as bond via SecurityTypeService
- `test_segment_real_estate_matches_reits` — SPG/VNQ classified as real_estate via SecurityTypeService
- `test_segment_futures_mtm_excluded_for_non_futures` — MTM events cleared for equities/options
- `test_segment_income_follows_symbol` — dividend for equity symbol stays in equities segment
- `test_segment_filters_current_positions` — positions filtered by inferred type
- `test_segment_disables_provider_flows` — provider_first_mode forced False
- `test_segment_commodities_matches_gld` — GLD classified as commodity via SecurityTypeService
- `test_segment_mixed_etf_defaults_to_equities` — mixed asset_class falls into equities bucket
- `test_segment_excluded_symbols_in_metadata` — uncategorized symbols listed in realized_metadata
- `test_segment_position_filtering_uses_keep_symbols` — positions filtered by txn-derived symbol set, not independent classification
- `test_segment_crypto_matches_bito` — BITO classified as crypto via SecurityTypeService
- `test_segment_option_futures_precedence` — txn with is_option=True + is_futures=True → classified as option
- `test_segment_cur_xxx_excluded` — CUR:USD, CUR:EUR excluded from all segments
- `test_segment_fx_artifact_excluded` — FX artifact transactions excluded from all segments
- `test_segment_income_only_symbol_skipped` — symbol with only income rows (no trades) not included
- `test_segment_all_preserves_provider_flows` — segment="all" keeps provider flows + cash anchor
- `test_segment_all_unchanged` — default behavior preserved
- `test_segment_no_matches_returns_error` — empty after filter → error dict
- `test_segment_position_symbol_consistency` — filtered positions match exactly `segment_keep_symbols` from transactions (no drift)
- `test_segment_passthrough_aggregation` — segment parameter threaded through aggregation → engine calls
- `test_segment_cache_key_includes_segment` — different segments produce different cache keys in PortfolioService

## Key Reusable Functions (no modifications needed)
- `_helpers._infer_instrument_type_from_transaction()` — `core/realized_performance/_helpers.py:79`
- `_helpers._infer_position_instrument_type()` — `core/realized_performance/_helpers.py:100`
- `coerce_instrument_type()` — `trading_analysis/instrument_meta.py`
- `SecurityTypeService.get_asset_classes(tickers)` — `services/security_type_service.py:791` — 5-tier classification (cash proxy → DB cache → FMP industry → security type → AI). Returns `{ticker: asset_class}` where asset_class is one of: equity, bond, real_estate, commodity, crypto, cash, mixed, unknown
- `VALID_ASSET_CLASSES`, `SECURITY_TYPE_TO_ASSET_CLASS` — `portfolio_risk_engine/constants.py`

## Verification
1. Run existing realized perf tests: `pytest tests/core/test_realized_performance_analysis.py -x`
2. Run new segment tests: `pytest tests/core/test_realized_performance_segment.py -x`
3. Run MCP performance tests: `pytest tests/mcp_tools/test_performance.py -x`
4. Live MCP smoke test: `get_performance(mode="realized", segment="futures")` and `get_performance(mode="realized", segment="equities")`
