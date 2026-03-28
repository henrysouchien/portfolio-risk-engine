# Cash Semantics Fix for Core Risk and Optimization

## Status: DESIGN READY

## Context

The repo currently has two conflicting representations of cash:

1. **Provider / holdings layer** keeps currency cash as `CUR:XXX`.
2. **Core analysis layer** rewrites that cash to a proxy ETF via `cash_map.yaml`.

That rewrite was introduced to make cash positions priceable in the risk pipeline, but it creates a semantic bug for optimization:

- `CUR:GBP` is preserved in the positions layer
- `to_portfolio_data()` converts it to `ERNS.L`
- `SecurityTypeService` later labels `ERNS.L` as `"cash"`
- `build_portfolio_view()` still fetches real `ERNS.L` market history
- `min_variance` / `max_sharpe` then optimize against bond-fund risk, not cash

This is the root cause of the open bug in `docs/TODO.md`: **GBP cash mapped to `ERNS.L` distorts optimizer output**.

## Relationship to Prior Work

This plan partially supersedes the core assumption in:

- `docs/planning/completed/CASH_PROXY_MAPPING_PLAN.md`
- `docs/planning/completed/realized-perf/CASH_PROXY_MAPPING_PLAN.md`

Those plans solved an earlier problem: raw `CUR:*` cash could not pass through the risk stack because it had no price series. Converting cash to proxy ETFs fixed validation and leverage dilution, but it also imported ETF duration / credit / market behavior into the optimizer.

That tradeoff is no longer acceptable for the core solver path.

## Desired Invariant

For core analysis, `CUR:*` remains synthetic cash all the way through:

- **Portfolio input**: `CUR:GBP`
- **Exposure math**: treated as cash
- **Historical return series**: synthetic cash series, not ETF history
- **Expected return**: cash-like return
- **Optimization output**: still `CUR:GBP`

If a UI or execution flow needs a tradable instrument, that translation happens **after** optimization, at the edge.

## Scope

In scope:

- Live positions → `PortfolioData` path
- Core risk / performance / optimization flows that consume `PortfolioData`
- Cash detection helpers used for leverage / labeling / metadata
- Regression tests for optimizer behavior

Out of scope for the first implementation:

- Reworking realized-performance cash replay
- Per-user cash proxy overrides
- Introducing new market-data providers for non-USD overnight cash rates

## Root Cause Detail

### Current flow

1. `PositionService` normalizes broker cash tickers to `CUR:XXX`.
2. `PositionsData.to_portfolio_data()` detects cash and rewrites it through `proxy_by_currency`.
3. For GBP, `cash_map.yaml` maps to `ERNS.L`.
4. `config_adapters.py` feeds the rewritten ticker into core analysis.
5. `portfolio_risk.py::_fetch_ticker_returns()` treats `ERNS.L` as a normal instrument and fetches its real monthly history.
6. `efficient_frontier.py` uses that covariance matrix directly.

### Why classification does not save us

`SecurityTypeService` and `ReturnsService` may call `ERNS.L` "cash", but those are downstream labels and expected-return conveniences. They do **not** stop the core return engine from using bond-fund price history.

## Proposed Fix

### Phase 1: Restore cash semantics in the core pipeline

#### 1. Add a shared cash-ticker predicate

Introduce a small shared helper for "cash-like ticker" checks:

- `ticker.startswith("CUR:")`
- or ticker appears in the YAML-driven cash proxy / alias sets

Use this predicate instead of raw set membership where the code currently assumes cash is only a known proxy ticker.

Primary targets:

- `portfolio_risk_engine/portfolio_config.py`
- `services/position_metadata.py`
- any helper that currently does `ticker in cash_positions`

This is required because `CUR:GBP` is not listed in `alias_to_currency` today, so it can be missed by set-only checks.

#### 2. Preserve `CUR:*` in `to_portfolio_data()`

Change the live positions path so synthetic cash is no longer rewritten to proxy ETFs before core analysis.

Primary target:

- `portfolio_risk_engine/data_objects.py`

Behavior after the change:

- `CUR:GBP` stays `CUR:GBP`
- the holding still enters `standardized_input` as a `"dollars"` position
- the dollar amount remains the already-converted USD value from `PositionService`
- `proxy_by_currency` is no longer used to substitute the ticker in the core analysis path

Important detail:

- Do **not** thread `CUR:GBP` into `currency_map`, because `standardize_portfolio_input()` treats non-USD `currency_map` entries on `"dollars"` positions as local-currency values and would double-convert the USD cash value.

#### 3. Synthesize cash return series for `CUR:*`

Teach the core return loader to produce synthetic monthly returns for currency cash tickers.

Primary target:

- `portfolio_risk_engine/portfolio_risk.py::_fetch_ticker_returns()`

Phase-1 behavior:

- `CUR:USD`: zero local monthly returns
- `CUR:GBP`: zero local monthly returns, then apply existing FX adjustment logic using the currency parsed from the ticker
- `CUR:EUR`: same pattern

This gives:

- no bond-fund duration / credit contamination
- no missing-data exclusion
- correct USD-base risk for non-USD cash via FX moves

This phase intentionally models cash as:

- **local cash return = 0**
- **USD investor return = FX translation of that flat local balance**

That is not a perfect carry model, but it is a correct semantic upgrade over using a bond ETF.

#### 4. Extend expected-return handling to `CUR:*`

The optimizer also needs cash-like expected returns for `max_sharpe`.

Primary target:

- `services/returns_service.py`

Change the cash detection used for expected-return coverage so that `CUR:*` tickers receive the same treatment now given to cash proxies:

- Treasury-derived expected return when available
- existing cash fallback otherwise

This ensures:

- `CUR:USD` does not default to "missing expected return"
- `CUR:GBP` also behaves like cash in expected-return coverage

### Phase 2: Align leverage / labeling / reporting helpers

#### 5. Update risky-exposure calculations to use the shared cash predicate

Primary target:

- `portfolio_risk_engine/portfolio_config.py`

Current logic excludes positive cash from risky exposure using a static set of known cash tickers. Once core inputs keep `CUR:*`, that logic must recognize `CUR:GBP`, `CUR:CAD`, etc. by prefix rather than YAML alias membership alone.

Required behaviors:

- positive `CUR:*` excluded from risky exposure
- negative `CUR:*` retained as margin debt / liability

#### 6. Update metadata / labeling helpers

Primary targets:

- `services/position_metadata.py`
- result-object formatting helpers that currently use only `get_cash_positions()`

Goal:

- `CUR:*` should display and classify as cash even when the ticker is not present in the static YAML alias list

### Phase 3: Remove legacy reintroduction paths

#### 7. Audit the legacy `PortfolioAssembler` / `PortfolioManager` mapping path

Primary targets:

- `inputs/portfolio_assembler.py`
- `inputs/portfolio_manager.py`

Those paths still convert cash through `proxy_by_currency`. If left unchanged, they remain a second route that can reintroduce `ERNS.L` into optimization.

Recommended approach:

- either preserve `CUR:*` there as well
- or add an explicit edge-only mode such as `map_cash_to_tradeable_proxy=False` for analysis callers

The end state should be:

- core risk / optimization callers preserve `CUR:*`
- only execution / display / trading helpers opt into proxy translation

## Cash-Rate Enhancement (Deferred)

The repo currently has a canonical USD Treasury source, but no canonical SONIA / ESTR / other local overnight-rate source for synthetic non-USD cash carry.

So Phase 1 deliberately uses:

- zero local carry
- existing FX translation for non-USD cash

Future enhancement:

1. Add a per-currency short-rate source
2. Replace zero local carry with currency-specific monthly cash carry
3. Keep the same synthetic-cash architecture

This is an enhancement, not a blocker for fixing the optimizer bug.

## File Plan

### Core implementation

- `portfolio_risk_engine/data_objects.py`
  Preserve `CUR:*` tickers in `to_portfolio_data()` for the live positions path.

- `portfolio_risk_engine/portfolio_risk.py`
  Generate synthetic return series for `CUR:*` and bypass ETF price fetching.

- `services/returns_service.py`
  Treat `CUR:*` as cash-like for expected-return coverage.

### Exposure / helper alignment

- `portfolio_risk_engine/portfolio_config.py`
  Replace set-only cash checks with a shared cash predicate.

- `services/position_metadata.py`
  Classify `CUR:*` as cash even when not listed in the static cash set.

### Follow-up / convergence

- `inputs/portfolio_assembler.py`
- `inputs/portfolio_manager.py`

Remove or gate proxy substitution so the legacy path cannot reintroduce the same bug.

## Tests

### Unit tests

- `PositionsData.to_portfolio_data()` preserves `CUR:GBP` instead of emitting `ERNS.L`
- existing assertions expecting `ERNS.L` / `SGOV` from raw cash inputs are updated where appropriate
- `standardize_portfolio_input()` excludes positive `CUR:*` from risky exposure
- `standardize_portfolio_input()` keeps negative `CUR:*` in risky exposure
- `_fetch_ticker_returns("CUR:USD", ...)` returns a non-empty synthetic series without price fetching
- `_fetch_ticker_returns("CUR:GBP", ...)` uses FX-adjusted synthetic cash returns without ETF fetching
- expected-return coverage treats `CUR:*` as cash

### Integration / regression tests

- optimization path with GBP cash no longer injects `ERNS.L`
- `min_variance` with GBP cash allocates to synthetic cash, not a bond proxy
- `max_sharpe` with GBP cash keeps cash-like expected return handling
- risk summary / labeling still show `CUR:*` as cash

## Rollout Notes

1. Land the core semantic fix first (`to_portfolio_data` + synthetic cash returns + expected returns).
2. Update leverage / metadata helpers in the same patch or immediately after.
3. Audit legacy proxy-mapping paths before treating the issue as fully closed.

## Success Criteria

The bug is fixed when all of the following are true:

- `CUR:GBP` reaches optimization unchanged
- `ERNS.L` is no longer introduced by the live positions analysis path
- cash no longer contributes bond-fund covariance to `min_variance` / `max_sharpe`
- positive cash still dilutes risky exposure
- negative cash still counts as debt / leverage
- `CUR:*` remains labeled and handled as cash across risk outputs

