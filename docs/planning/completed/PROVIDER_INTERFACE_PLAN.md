# Plan: Common Provider Interface

**Status:** IMPLEMENTED

## Context

The codebase has three brokerage providers (Plaid, SnapTrade, IBKR) and two market data providers (FMP, IBKR). Each is wired in directly — the `TradingAnalyzer` has 530 lines of provider-specific normalization, the pricing loop has 130 lines of hardcoded if/else routing, and `PositionService` has hardcoded two-provider dispatch. Adding a new brokerage (e.g., Schwab) or market data source (e.g., Polygon) would require touching many files. This plan introduces a common provider interface so providers are pluggable.

**Design choice: Python Protocols** (not ABCs). Existing code (module-level functions in `plaid_loader.py`, `snaptrade_loader.py`) can satisfy Protocols via structural typing without inheritance. Incremental adoption — existing code works unchanged until explicitly migrated.

---

## Phase 1: Define Interfaces + Registry

**New files** (pure addition, zero risk):

### `providers/__init__.py`
Re-exports from `interfaces.py` and `registry.py`.

### `providers/interfaces.py`
Four Protocol classes:

```python
@runtime_checkable
class PositionProvider(Protocol):
    provider_name: str
    def fetch_positions(self, user_email: str, **kwargs) -> pd.DataFrame: ...

@runtime_checkable
class TransactionProvider(Protocol):
    provider_name: str
    def fetch_transactions(self, user_email: str, **kwargs) -> dict[str, Any]: ...

@runtime_checkable
class TransactionNormalizer(Protocol):
    provider_name: str
    def normalize(self, raw_data: Any, security_lookup: dict | None = None
    ) -> tuple[list[NormalizedTrade], list[NormalizedIncome], list[dict]]: ...

@runtime_checkable
class PriceSeriesProvider(Protocol):
    provider_name: str
    def can_price(self, instrument_type: str) -> bool: ...
    def fetch_monthly_close(self, symbol: str, start_date, end_date, *,
        instrument_type: str = "equity",
        contract_identity: dict | None = None,
        fmp_ticker_map: dict | None = None,
    ) -> pd.Series: ...
```

### `providers/registry.py`
Simple dict-based `ProviderRegistry`:
- `register_position_provider(provider)` / `get_position_providers() -> dict`
- `register_transaction_provider(provider)` / `get_transaction_providers() -> dict`
- `register_normalizer(normalizer)` / `get_normalizer(name) -> TransactionNormalizer`
- `register_price_provider(provider, priority)` / `get_price_chain(instrument_type) -> list`

Priority-ordered price chain: lower priority = tried first. `can_price()` filters.

### Tests
`tests/providers/test_interfaces.py` — verify Protocol structural typing works with mock providers.
`tests/providers/test_registry.py` — register/lookup/chain ordering.

---

## Phase 2: Provider Adapter Wrappers

Thin adapter classes that delegate to existing functions. No logic changes.

### Market Data Adapters

#### `providers/fmp_price.py` — `FMPPriceProvider`
- Wraps `fmp.compat.fetch_monthly_close()`
- `can_price()`: True for `equity`, `futures` (FMP attempts via commodity symbols)
- `provider_name = "fmp"`

#### `providers/ibkr_price.py` — `IBKRPriceProvider`
- Wraps `ibkr.compat.fetch_ibkr_monthly_close()`, `fetch_ibkr_fx_monthly_close()`, `fetch_ibkr_bond_monthly_close()`, `fetch_ibkr_option_monthly_mark()`
- Routes by `instrument_type` parameter
- `can_price()`: True for `futures`, `fx`, `bond`, `option`. **Not equity** — IBKR contract resolver rejects equity contracts (`ibkr/contracts.py:197-200`), so including equity would create noisy failed attempts
- `provider_name = "ibkr"`

### Position Adapters

#### `providers/plaid_positions.py` — `PlaidPositionProvider`
- Wraps `plaid_loader.load_all_user_holdings()` (returns per-account rows, NOT consolidated)
- `provider_name = "plaid"`

#### `providers/snaptrade_positions.py` — `SnapTradePositionProvider`
- Wraps `snaptrade_loader.fetch_snaptrade_holdings()` + `normalize_snaptrade_holdings()` (NOT `load_all_user_snaptrade_holdings()` which consolidates and loses account-level granularity)
- Must preserve per-account rows — `PositionService` depends on account-level data for DB storage (`services/position_service.py:729-743`) and `_get_positions_df` (`services/position_service.py:219-221`)
- `provider_name = "snaptrade"`

### Transaction Adapters

#### `providers/plaid_transactions.py` — `PlaidTransactionProvider`
- Wraps `trading_analysis.data_fetcher.fetch_plaid_transactions()`
- Includes `should_skip_plaid_institution()` routing — Plaid IBKR transactions are filtered at fetch time (preserves existing behavior from `data_fetcher.py:278-280`)
- `provider_name = "plaid"`

#### `providers/snaptrade_transactions.py` — `SnapTradeTransactionProvider`
- Wraps `trading_analysis.data_fetcher.fetch_snaptrade_activities()`
- `provider_name = "snaptrade"`

#### `providers/ibkr_transactions.py` — `IBKRFlexTransactionProvider`
- Wraps `trading_analysis.data_fetcher.fetch_ibkr_flex_trades()` (NOT `ibkr.compat` directly — the data_fetcher wrapper handles env credential reading at `data_fetcher.py:95-108` and returns `[]` when credentials are not configured)
- `provider_name = "ibkr_flex"`

### Refactor `data_fetcher.py`

Update `fetch_all_transactions()` and `fetch_transactions_for_source()` to use `TransactionProvider` from registry:
- `fetch_all_transactions(user_email, registry=None)` → iterates `registry.get_transaction_providers()`. **Default registry** (when `registry=None`): auto-build from Plaid + SnapTrade + IBKR Flex providers. This preserves backward compat — no callers break.
- `fetch_transactions_for_source(user_email, source, registry=None)` → looks up single provider. Same default.
- **Callers** (all use `fetch_transactions_for_source`, none need changes if registry defaults):
  - `run_trading_analysis.py:120`
  - `mcp_tools/trading_analysis.py:24`
  - `mcp_tools/tax_harvest.py:108`
  - `core/realized_performance_analysis.py:1610`
- **Adding a new provider**: register in the default registry builder — all callers pick it up automatically without changes
- **Tests to update**: `tests/mcp_tools/test_trading_analysis.py` (monkeypatches `fetch_transactions_for_source`), `tests/trading_analysis/test_provider_routing.py`

### Tests
`tests/providers/test_fmp_price.py`, `tests/providers/test_ibkr_price.py` — mock underlying functions, verify delegation + `can_price()` behavior.
`tests/providers/test_transaction_providers.py` — verify each transaction adapter delegates correctly; verify Plaid adapter applies institution routing.

---

## Phase 3: Extract Transaction Normalizers

Extract the three blocks from `TradingAnalyzer._normalize_data()` (~530 lines) into separate classes satisfying `TransactionNormalizer`.

### `providers/normalizers/__init__.py`

### `providers/normalizers/common.py` — Shared helpers
- `parse_date()`, `safe_float()` — already used by all three blocks
- FX pair detection regex `_FX_PAIR_SYMBOL_RE` and unknown symbol filtering
- These are pure utilities, NOT `_build_symbol_name_lookup` (which stays in `TradingAnalyzer` — it's analyzer-level reporting state consumed by name resolution at `analyzer.py:326-341`, not part of normalization)

### `providers/normalizers/snaptrade.py` — `SnapTradeNormalizer`
- Extract lines 483-746 from `analyzer.py`
- Carries over: FX pair detection, option parsing from description, OPTIONEXPIRATION handling, REI events, type_code extraction
- Helper methods moved: `_parse_option_symbol()`, `_infer_snaptrade_instrument_type()`, `_extract_snaptrade_type_code()`
- Input: `raw_data = list[SnapTradeActivity]`

### `providers/normalizers/plaid.py` — `PlaidNormalizer`
- Extract lines 749-927 from `analyzer.py`
- Carries over: security lookup, `resolve_fmp_ticker()` call, subtype-based short detection, instrument type inference
- Helper methods moved: `_infer_plaid_instrument_type()`
- Input: `raw_data = list[PlaidTransaction]`, `security_lookup = dict[str, PlaidSecurity]`

### `providers/normalizers/ibkr_flex.py` — `IBKRFlexNormalizer`
- Extract lines 929-1008 from `analyzer.py`
- Simplest — IBKR Flex data is already pre-normalized by `ibkr/flex.py`
- Input: `raw_data = list[dict]`

### `TradingAnalyzer` changes (`trading_analysis/analyzer.py`)
- Add optional `normalizers: list[TransactionNormalizer] | None` param to `__init__`
- New `_normalize_data()`:
  ```python
  for normalizer in self._normalizers:
      raw = self._raw_data_for(normalizer.provider_name)
      if not raw:
          continue
      trades, income, fifo = normalizer.normalize(raw, security_lookup=self.security_lookup)
      self.trades.extend(trades)
      self.income_events.extend(income)
      self.fifo_transactions.extend(fifo)
  self._deduplicate_transactions()
  ```
- `_raw_data_for(name)` maps provider_name → the correct raw data list
- **Backward compat**: When `normalizers` is None, default to `[SnapTradeNormalizer(), PlaidNormalizer(), IBKRFlexNormalizer()]`
- **`_build_symbol_name_lookup` stays in `TradingAnalyzer`** — it's analyzer-level reporting state, not normalization logic. Each normalizer's `normalize()` can optionally accept a `symbol_name_callback` or the analyzer calls `_build_symbol_name_lookup()` after all normalizers run, scanning the populated `self.trades`.

### Critical invariant: trades/fifo index alignment for dedup

**Problem**: `_deduplicate_transactions()` (`analyzer.py:1063-1067`) pops by index from both `self.trades` and `self.fifo_transactions` in lockstep. Current code appends trade+fifo as pairs. The normalizer extraction must preserve this.

**Solution**: Each normalizer's `normalize()` returns `(trades, income, fifo)` where `trades` and `fifo` are **1:1 aligned by index** — the i-th trade corresponds to the i-th fifo dict. Income events are separate (no dedup concern). The `TradingAnalyzer` extends both lists in the same call, preserving alignment. Document this invariant in the `TransactionNormalizer` Protocol docstring.

**Verification**: Add a test that asserts `len(trades) == len(fifo)` for each normalizer output, and that dedup produces identical results to the current inline implementation.

### Tests
- `tests/providers/normalizers/test_snaptrade.py` — verify output matches current behavior with known fixture data
- `tests/providers/normalizers/test_plaid.py` — same, including international ticker resolution
- `tests/providers/normalizers/test_ibkr_flex.py` — same
- **Dedup regression**: run `tests/ibkr/test_flex.py:295-387` (existing dedup tests) to verify alignment invariant holds
- Run existing `tests/trading_analysis/` suite to verify no regressions

---

## Phase 4: Pricing Loop Refactor

Replace the hardcoded 130-line instrument-type waterfall in `core/realized_performance_analysis.py` (~line 1870-2010) with a provider-chain loop.

### New helper function
```python
@dataclass
class PriceResult:
    series: pd.Series
    success_provider: str | None = None  # Which provider returned data
    attempts: list[tuple[str, str, Exception | None]] = field(default_factory=list)
    # Each attempt: (provider_name, outcome, exception_or_None)
    # outcome is "success", "empty", or "error"

def _fetch_price_from_chain(
    providers: list[PriceSeriesProvider],
    symbol: str, start_date, end_date,
    instrument_type: str,
    contract_identity: dict | None,
    fmp_ticker_map: dict | None,
) -> PriceResult:
    """Try providers in order until one returns non-empty data.

    Returns PriceResult with:
    - series: the price data (empty Series if all failed)
    - success_provider: name of provider that returned data (None if all failed)
    - attempts: full audit trail of every provider tried and outcome

    The caller uses `attempts` to emit the SAME diagnostic warnings as current code:
    - Success-path: "Priced futures {ticker} via IBKR Gateway fallback ({n} bars)"
      → detected via success_provider == "ibkr" + instrument_type == "futures"
    - Empty-path: "IBKR fallback returned no data for FX {ticker} (Gateway may not be running)"
      → detected via ("ibkr", "empty", None) in attempts
    - Error-path: "IBKR fallback also failed for futures {ticker}: {exc}"
      → detected via ("ibkr", "error", exc) in attempts, str(exc) for message
    """
    result = PriceResult(series=pd.Series(dtype=float))
    for provider in providers:
        try:
            series = provider.fetch_monthly_close(
                symbol, start_date, end_date,
                instrument_type=instrument_type,
                contract_identity=contract_identity,
                fmp_ticker_map=fmp_ticker_map,
            )
            if not series.empty and not series.dropna().empty:
                result.series = series
                result.success_provider = provider.provider_name
                result.attempts.append((provider.provider_name, "success", None))
                return result
            result.attempts.append((provider.provider_name, "empty", None))
        except Exception as exc:
            result.attempts.append((provider.provider_name, "error", exc))
            continue
    return result
```

**Key difference from v1**: `PriceResult` provides a full audit trail — which providers were tried, which succeeded, which failed and why (including original exception objects). The `success_provider` field enables success-path warnings (e.g., "Priced futures ES via IBKR Gateway fallback (12 monthly bars)" when `success_provider == "ibkr"` and `instrument_type == "futures"`). The `attempts` list enables failure-path warnings with verbatim exception messages.

The caller (pricing loop) uses a `_emit_pricing_diagnostics(symbol, instrument_type, result: PriceResult)` helper that maps `PriceResult` to the exact same warning strings the current waterfall produces, including:
- Success via fallback: `"Priced {instrument_type} {ticker} via IBKR Gateway fallback ({n} monthly bars)."` (line 1947)
- Empty from IBKR: `"IBKR fallback returned no data for {instrument_type} {ticker} (Gateway may not be running)."` (line 1952)
- Error from IBKR: `"IBKR fallback also failed for {instrument_type} {ticker}: {exc}"` (line 1956)
- Coverage stats: `ibkr_priced_symbols[instrument_type].add(ticker)` when `success_provider == "ibkr"` (line 1949)

### Chain configuration (replaces hardcoded if/else)
```python
# Default chains by instrument type:
# equity:  [FMP]           (no IBKR — contract resolver rejects equity)
# futures: [FMP, IBKR]
# fx:      [IBKR]
# bond:    [IBKR]
# option:  [IBKR]  (with FIFO terminal heuristic as pre-chain step)
```

Built from registry: `registry.get_price_chain(instrument_type)`.

### `analyze_realized_performance()` changes
- Accept optional `price_registry: ProviderRegistry` param (default: build from FMP + IBKR)
- Replace the instrument-type waterfall with `_fetch_price_from_chain()`
- **Keep** the option FIFO terminal heuristic as a pre-chain step (it's local computation, not a provider)
- **Keep** the `fmp_ticker_map` augmentation for futures (IBKR → FMP commodity symbols)
- **Keep** diagnostic warning emission — parse failure reasons from chain to emit provider-specific warnings matching current behavior

### Tests
- Mock both providers, verify chain ordering, fallback behavior, and **failure reason accumulation**
- Run existing `tests/core/test_realized_performance_analysis.py` for regression (especially `test_*_unpriceable_*` tests at lines 3141-3208)

---

## Phase 5: PositionService Provider Registry

Replace hardcoded two-provider dispatch in `services/position_service.py`.

### Changes to `PositionService`

All provider-specific dispatch points to update:

- `__init__` accepts optional `position_providers: dict[str, PositionProvider]`
- Default: register Plaid + SnapTrade providers
- `_fetch_fresh_positions(provider_name)` → lookup from registry instead of if/else
- `_get_positions_df(provider)` (`position_service.py:219-221`) → registry lookup
- `refresh_provider_positions(provider)` (`position_service.py:763-765`) → registry lookup
- `_consolidate_provider_positions()` (`position_service.py:404`) → iterate registered providers instead of hardcoded list
- Client bootstrap methods (`position_service.py:449`, `position_service.py:460`) — move provider-specific client initialization into each `PositionProvider` adapter (each adapter owns its own client setup)
- `get_all_positions()` iterates registered providers
- Cache metadata keys (`position_service.py:199-207`) → derived from `provider_name` instead of hardcoded strings

### Adding IBKR positions
Once refactored, adding IBKR live positions is just:
```python
registry.register_position_provider(IBKRPositionProvider())
```

### Tests
- Mock providers, verify dispatch + consolidation
- Run existing `tests/services/test_position_service_consolidation_cost_basis_usd.py` for regression (correct test file path)

---

## Phase 6: Centralize Symbol Resolution

### `providers/symbol_resolution.py` — `SymbolResolver`
Wraps `utils/ticker_resolver.py` with provider-awareness:

```python
class SymbolResolver:
    def resolve(self, raw_symbol: str, *, provider: str,
                company_name: str | None = None,
                currency: str | None = None,
                exchange_mic: str | None = None,
                instrument_type: str = "equity") -> str:
        """Resolve provider-native symbol to market-data-compatible format."""
        if instrument_type == "futures":
            return self._resolve_futures(raw_symbol, provider)
        # Strip trailing dots (IBKR/Plaid convention)
        base = raw_symbol.rstrip(".")
        if not base:
            return raw_symbol
        return resolve_fmp_ticker(base, company_name, currency, exchange_mic)
```

- Does NOT replace `utils/ticker_resolver.py` — wraps it
- Callers migrate incrementally (normalizers use it first, then positions)
- Futures resolution uses `ibkr/exchange_mappings.yaml` lookup

### Tests
`tests/providers/test_symbol_resolution.py` — international tickers, futures, domestic passthrough.

---

## File Summary

| Phase | Action | File |
|-------|--------|------|
| 1 | New | `providers/__init__.py` |
| 1 | New | `providers/interfaces.py` |
| 1 | New | `providers/registry.py` |
| 2 | New | `providers/fmp_price.py` |
| 2 | New | `providers/ibkr_price.py` |
| 2 | New | `providers/plaid_positions.py` |
| 2 | New | `providers/snaptrade_positions.py` |
| 2 | New | `providers/plaid_transactions.py` |
| 2 | New | `providers/snaptrade_transactions.py` |
| 2 | New | `providers/ibkr_transactions.py` |
| 2 | Edit | `trading_analysis/data_fetcher.py` (use TransactionProvider registry) |
| 2 | Edit | `trading_analysis/data_fetcher.py` — default registry builder; callers (`run_trading_analysis.py:120`, `mcp_tools/trading_analysis.py:24`, `mcp_tools/tax_harvest.py:108`, `core/realized_performance_analysis.py:1610`) use defaults and need no changes |
| 3 | New | `providers/normalizers/__init__.py` |
| 3 | New | `providers/normalizers/common.py` (shared helpers) |
| 3 | New | `providers/normalizers/snaptrade.py` |
| 3 | New | `providers/normalizers/plaid.py` |
| 3 | New | `providers/normalizers/ibkr_flex.py` |
| 3 | Edit | `trading_analysis/analyzer.py` (replace `_normalize_data()`) |
| 4 | Edit | `core/realized_performance_analysis.py` (pricing loop) |
| 5 | Edit | `services/position_service.py` (provider dispatch) |
| 6 | New | `providers/symbol_resolution.py` |

## What Adding a New Provider Looks Like After This

**New brokerage (e.g., Schwab):**
1. `providers/schwab_positions.py` — implements `PositionProvider`
2. `providers/schwab_transactions.py` — implements `TransactionProvider`
3. `providers/normalizers/schwab.py` — implements `TransactionNormalizer`
4. Register all three in the default registry builder (`providers/registry.py`)
5. Add `"schwab"` to the `source` Literal in `data_fetcher.py:fetch_transactions_for_source()` and `mcp_tools/trading_analysis.py:get_trading_analysis()`
6. Done — TradingAnalyzer, PositionService, and the pricing loop require no changes

**New market data source (e.g., Polygon):**
1. `providers/polygon_price.py` — implements `PriceSeriesProvider`
2. Register with priority
3. Done — pricing chain picks it up automatically

## Verification

Per phase:
1. `pytest tests/providers/test_interfaces.py tests/providers/test_registry.py -v`
2. `pytest tests/providers/test_fmp_price.py tests/providers/test_ibkr_price.py tests/providers/test_transaction_providers.py -v`
3. `pytest tests/providers/normalizers/ -v && pytest tests/trading_analysis/ -v && pytest tests/ibkr/test_flex.py -v` (regression including dedup)
4. `pytest tests/core/test_realized_performance_analysis.py -v` (regression, especially unpriceable tests)
5. `pytest tests/services/test_position_service_consolidation_cost_basis_usd.py -v` (regression)
6. `pytest tests/providers/test_symbol_resolution.py -v`

End-to-end: `python run_trading_analysis.py --source ibkr_flex --summary` should produce identical output before/after.

## Codex Review Log

### Round 1 (9 findings)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | HIGH | TransactionProvider not wired — Phase 2 has no transaction adapters, callers remain hardcoded | Added 3 transaction adapters (Plaid, SnapTrade, IBKR Flex) + `data_fetcher.py` refactor + caller update list |
| 2 | HIGH | SnapTrade position adapter wraps `load_all_user_snaptrade_holdings()` which consolidates — breaks PositionService per-account needs | Changed to wrap `fetch_snaptrade_holdings()` + `normalize_snaptrade_holdings()` (preserves per-account rows) |
| 3 | HIGH | `_fetch_price_from_chain()` swallows exceptions, losing diagnostic warnings/coverage stats that tests assert | Rewrote to accumulate per-provider failure reasons; caller parses to emit same warnings as current code |
| 4 | MED | IBKR equity fallback unsupported — contract resolver rejects equity at `ibkr/contracts.py:197-200` | Removed equity from IBKR `can_price()`, removed IBKR from equity chain |
| 5 | HIGH | Dedup index alignment — `_deduplicate_transactions()` pops by same index from trades + fifo; normalizer extraction could break | Added explicit 1:1 alignment invariant in Protocol docstring + verification test |
| 6 | MED | `should_skip_plaid_institution()` fetch-time routing not placed | Placed in `PlaidTransactionProvider` adapter — routing happens at fetch time as today |
| 7 | MED | PositionService has more hardcoded gates than Phase 5 covered | Added `_get_positions_df`, `refresh_provider_positions`, and cache metadata keys to scope |
| 8 | MED | Test plan references wrong file paths, misses dedup regression | Fixed test file path, added dedup regression tests from `tests/ibkr/test_flex.py:295-387` |
| 9 | LOW | `_build_symbol_name_lookup` placement ambiguous | Clarified: stays in TradingAnalyzer (analyzer-level reporting state, not normalization) |

### Round 2 (5 findings)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | HIGH | Phase 4 failure accumulation drops exception messages — current diagnostics/tests rely on message text | Changed from string format to structured tuples `(provider_name, failure_type, exception_or_None)` preserving original exception objects. Added `_emit_pricing_warnings()` helper spec |
| 2 | HIGH | Phase 2 data_fetcher refactor caller list incomplete/inaccurate — misses `mcp_tools/trading_analysis.py:24`, lists non-direct callers | Fixed caller list to actual `fetch_transactions_for_source` call sites. Made registry param optional with default builder for backward compat — no callers break |
| 3 | HIGH | "Zero existing file changes" for new provider not credible — source Literal and registry builder need updates | Corrected: new provider requires registering in default builder + adding to source Literal in 2 files. Core logic (TradingAnalyzer, PositionService, pricing loop) still untouched |
| 4 | MED | IBKR transaction adapter wraps `ibkr.compat` directly but data_fetcher handles env credentials | Changed to wrap `data_fetcher.fetch_ibkr_flex_trades()` which handles credential reading and returns `[]` when unconfigured |
| 5 | MED | PositionService Phase 5 scope still incomplete — `_consolidate_provider_positions` and client bootstrap methods | Added both to Phase 5 scope; client bootstrap moves into PositionProvider adapters |

### Round 3 (3 findings)

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | HIGH | Phase 4 helper returns `None` on success, dropping which provider succeeded — can't emit success-path warnings like "Priced futures via IBKR Gateway fallback" | Replaced with `PriceResult` dataclass: `success_provider` field + full `attempts` audit trail. Added `_emit_pricing_diagnostics()` helper spec mapping to exact current warning strings |
| 2 | MED | File Summary caller list inconsistent with Phase 2 section — lists non-direct callers, omits `mcp_tools/trading_analysis.py` | Fixed File Summary to match Phase 2 caller list; noted callers need no changes due to default registry |
| 3 | MED | Phase 4 return type annotation inconsistent (said `str | None` but returned tuples) | Fixed: return type is now `PriceResult` dataclass, internally consistent |
