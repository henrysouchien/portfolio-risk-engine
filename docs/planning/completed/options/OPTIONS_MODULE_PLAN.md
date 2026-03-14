# Options Analysis Module

## Context

Option payoff analysis is currently scattered across three places:

1. **Google Sheets** ("SIA Option Payoff Calculator" — HC, PLTR, base versions) — the richest analytics: 4-leg strategies, intrinsic/extrinsic decomposition, cost of leverage, risk:reward, breakevens, P&L per $1 move
2. **Jupyter notebook** (`~/Documents/Jupyter/investment_system/to-port/Option-calculator.ipynb`) — basic `OptionLeg`/`OptionStrategy` classes with expiration payoff curves
3. **IBKR infrastructure** already in risk_module — chain fetching, live Greeks (delta/gamma/theta/vega/IV via `modelGreeks`), option contract resolution, symbol parsing

Goal: Consolidate into a proper `options/` module that the agent can use day-to-day for strategy evaluation, with live IBKR data enrichment and eventual portfolio risk integration.

## Scope & Limitations

**Phase 1 scope**: Same-expiry European-style expiration payoff analysis only. This covers the vast majority of day-to-day strategy evaluation (spreads, straddles, condors at a single expiry).

**Known limitations (documented, addressed in later phases)**:
- **American options**: Black-Scholes assumes European exercise. US equity options are American — early exercise risk (especially short ITM calls near ex-div) is not modeled in Phase 1. IBKR's `modelGreeks` (Phase 2) accounts for this via their proprietary model. Phase 1 documents this assumption clearly in code and output.
- **Multi-expiry strategies** (calendars, diagonals): Require a defined evaluation horizon and marking rules since there's no single "expiration payoff." Deferred to a future phase — would need a time-value model (BS at horizon date) rather than pure expiration payoff.

## Use Cases

### 1. Compare strategy structures
"Show me the bull call spread 30/35 vs the outright 30 call vs a 28/32 spread on SLV."

Run the analyzer on different leg combinations and compare cost, max P/L, risk:reward, and breakevens side by side.

### 2. Explore how legs change a strategy
"What if I add a short call at 40 to widen the spread?"

Add/remove legs, re-analyze, and see how payoff table, breakevens, and risk:reward shift.

### 3. Hedging cost analysis
"I own 500 shares of XYZ at $80 — how much does it cost to protect against a 10% decline?"

Model the stock position as a `stock` leg type (linear payoff), then add a protective put. The engine computes the combined P&L including the stock's linear contribution, showing the effective floor, premium cost, and breakeven relative to the total position.

### 4. OI cluster analysis (with live IBKR data)
"Where is the market positioned on AAPL Jan expiry?"

Pull OI/volume by strike from IBKR, show put/call walls, max pain, and overlay strategy breakevens on the OI distribution. E.g., "my breakeven is at 155 and there's a massive call wall at 160."

### 5. Research: momentum impact vs options pricing (future)
For stocks with heavy ETF/index ownership, estimate rebalancing momentum impact and compare to what's priced into options (implied vol, skew). Combines `get_institutional_ownership()` / `get_etf_holdings()` from fmp-mcp with the options module's IV analysis. This is a research workflow that builds on top of Phases 1-3.

## Existing Infrastructure

| File | What it provides |
|------|-----------------|
| `ibkr/metadata.py::fetch_option_chain()` | Chain metadata: expirations, strikes, multiplier for STK/FUT underlyings |
| `ibkr/market_data.py::fetch_snapshot()` | Live option pricing + Greeks (delta, gamma, theta, vega, IV) via generic ticks 100,101,106 |
| `ibkr/contracts.py::resolve_option_contract()` | Builds IBKR Option contracts from conId or (expiry, strike, right, underlying) |
| `trading_analysis/symbol_utils.py` | Option symbol parsing — canonical (`AAPL_C150_260117`) and OCC formats |
| `trading_analysis/instrument_meta.py` | `InstrumentType = "option"` already in the type system |
| `ibkr_mcp_server.py` | MCP tools: `get_ibkr_contract(info_type="option_chain")`, `get_ibkr_option_prices(symbol, expiry, strikes, right)` |
| `fmp/client.py::FMPClient` | Underlying price lookup for auto-fill |

Key point: All option Greeks currently come from IBKR's models — there is no local Black-Scholes calculation in the codebase. The new module adds a local BS calculator for offline/scenario use.

## Architecture

New `options/` package at project root, mirroring the `trading_analysis/` structure: models + pure math engines + orchestrator + MCP tool surface.

```
options/
  __init__.py          # Package exports
  models.py            # Dataclasses: OptionLeg, OptionStrategy, GreeksSnapshot, LegAnalysis, StrategyAnalysisResult
  payoff.py            # Pure payoff math engine (no I/O, no IBKR dependency)
  greeks.py            # Local Black-Scholes/Black-76 Greeks calculator
  analyzer.py          # OptionAnalyzer orchestrator
  chain_analysis.py    # OI/volume chain analysis (Phase 2)

mcp_tools/
  options.py           # MCP tool: analyze_option_strategy()

tests/options/
  test_payoff.py
  test_greeks.py
  test_analyzer.py
  test_mcp_options.py  # MCP tool behavior + registration tests
```

## Phase 1: Core Payoff Engine + Models

Pure math, works offline. Same-expiry strategies only. Dependencies: `numpy` (already in project requirements) for vectorized payoff computation in `payoff_table()` and `leg_payoff()` array mode. The `greeks.py` module uses only `math` stdlib.

### `options/models.py`

Dataclasses with `to_dict()`, `to_summary()`, `to_api_response()`, and `to_cli_report()` following `trading_analysis/models.py` conventions.

**`OptionLeg`**
- Fields: `position` (long/short), `option_type` (call/put/stock), `strike` (ignored for stock), `premium` (per-share, or cost basis for stock), `size` (contracts for options, shares for stock), `multiplier` (default 100 for options, 1 for stock), `expiration` (required `date` object for option legs — needed for Greeks/DTE/same-expiry validation; not applicable for stock legs), `label`, `con_id` (optional IBKR contract ID for Phase 2)
- **Expiry normalization**: `OptionLeg` stores expiration as a Python `date` object internally (for DTE math). A helper `expiry_yyyymmdd` property formats it as `"YYYYMMDD"` string for IBKR contract resolution. MCP tool parses `"YYYYMMDD"` string input → `date` object at the boundary.
- The `stock` type enables covered calls, protective puts, and collars — its payoff is linear: `direction * size * (price - premium)`
- **Input constraints** (enforced in `__post_init__` validation on the dataclass):
  - `premium >= 0` always (premium is the absolute per-share price paid/received)
  - `size > 0` always
  - `strike > 0` for call/put legs (raises `ValueError` if strike <= 0 for option types)
  - Direction comes solely from `position` (long/short)
- Properties: `direction` (+1/-1), `notional_exposure` (method that requires `underlying_price` arg: returns `underlying_price * size` for stock legs, `strike * multiplier * size` for options), `net_premium` (signed total premium: negative for debits/long, positive for credits/short)

**`OptionStrategy`**
- Fields: `legs` (list), `underlying_price` (must be > 0 when provided, validated in `__post_init__`), `underlying_symbol`, `description`

**`GreeksSnapshot`**
- Fields: `delta`, `gamma`, `theta`, `vega`, `implied_vol`, `source` (local|ibkr|mixed). Source is `mixed` when field-level merge produces a blend of local and IBKR values (e.g., IBKR returned delta but not gamma).
- **Canonical unit conventions** (all values stored in these units, both local and IBKR):
  - `delta`: per share (0 to 1 for calls, -1 to 0 for puts)
  - `gamma`: per share per $1 move
  - `theta`: per day (negative for long options) — IBKR `modelGreeks.theta` is already per-day
  - `vega`: per 1 percentage-point volatility move (i.e., per 0.01 sigma) — local BS computes as `S * N'(d1) * sqrt(T) * 0.01`. IBKR `modelGreeks.vega` is also per 1 percentage-point move (per IBKR documentation), so **no normalization needed** — both local and IBKR vega are in the same units and can be merged/aggregated directly. This should be validated with a live IBKR snapshot in Phase 2 testing.
  - `implied_vol`: annualized decimal (e.g., 0.30 for 30%)
- Tests should validate unit alignment: compute local Greeks, mock IBKR snapshot with known values, verify merge produces consistent aggregates.

**`LegAnalysis`** — per-leg analytics (mirrors spreadsheet columns):
- `intrinsic_value`, `extrinsic_value`, `net_time_value`, `cost_of_leverage_annualized`, `breakeven`, `greeks`
- `greeks_source`: tracks provenance (local vs ibkr) — never silently overwrite on partial failure

**`StrategyAnalysisResult`** — full analysis output:
- `max_profit` (positive number or None = unlimited), `max_loss` (negative number representing worst P&L, or None = unlimited), `risk_reward_ratio`, `total_risk_capital`, `net_premium`
- **Sign convention**: `max_profit` is always ≥ 0, `max_loss` is always ≤ 0. This matches the payoff function output directly (profit is positive, loss is negative). `risk_reward_ratio` uses absolute values: `abs(max_profit) / abs(max_loss)` when both are finite and max_loss != 0.
- `breakevens` (list of prices), `payoff_table` (per-leg + net at price steps), `pnl_per_dollar_move`
- `aggregate_greeks` (sum across legs, weighted by direction * size * multiplier)
- `assumptions`: list of strings noting model limitations (e.g., "European exercise model", "constant vol")
- Serialization: `to_dict()`, `to_summary()`, `to_api_response()`, `to_cli_report()`

### `options/payoff.py`

Pure math engine — stateless, no I/O.

**Analytic piecewise-linear approach**: At expiration, option payoff is piecewise-linear with breakpoints at strikes. Rather than numerical scanning, we evaluate the payoff analytically at each strike breakpoint and at the tails (price → 0 and price → large). This gives exact breakevens (solve linear segments for zero-crossings) and exact max/min without resolution artifacts. **Stock-only strategies** (no option legs) degenerate to a single linear segment `[0, +∞)` with no strike breakpoints — breakeven/max P&L computed directly from the single segment's slope and intercept.

- `leg_payoff(leg, price)` — P&L at expiration, supports numpy arrays for vectorized computation. Handles call, put, and stock leg types.
- `strategy_payoff(strategy, price)` — sum of leg payoffs
- `intrinsic_value(leg, underlying_price)` / `extrinsic_value(leg, underlying_price)`
- `cost_of_leverage_annualized(leg, underlying_price, days_to_expiry)` — spreadsheet formula: `(extrinsic / underlying_price) * (365 / DTE)`
- `find_breakevens(strategy)` — **analytic**: evaluate payoff across all segments of the piecewise-linear payoff function, including the outer segments `[0, first_strike]` and `[last_strike, +∞)`. For each segment, solve for zero-crossing if one exists. This catches breakevens below the first strike (e.g., single long call) and above the last strike.
- `max_profit(strategy)` / `max_loss(strategy)` — **analytic**: evaluate payoff at each strike breakpoint and at the tails (price = 0 and price → ∞). Tail behavior is determined by the net slope of all legs beyond the extreme strikes:
  - **Slope > 0 as price → ∞**: profit is unlimited (e.g., naked long call, short put, long stock)
  - **Slope < 0 as price → ∞**: loss is unlimited (e.g., naked short call, short stock)
  - **At price = 0**: evaluate payoff directly — this is always finite (e.g., naked short put max loss = strike × multiplier × size - premium received)
  - Otherwise: max/min occurs at one of the strike breakpoints
- `pnl_per_dollar_move(strategy, at_price)` — finite difference approximation
- `payoff_table(strategy, price_min, price_max, steps)` — per-leg + net P&L at evenly-spaced price steps
- `analyze_leg(leg, underlying_price, days_to_expiry)` → `LegAnalysis`

### `options/greeks.py`

Local pricing and Greeks calculator using only `math` stdlib (no scipy).

**Two models**:
- `black_scholes_price(S, K, T, r, sigma, option_type, q=0.0)` — Generalized Black-Scholes with continuous dividend yield `q`. When `q=0`, reduces to standard BS. Covers equity options with known dividend yield.
- `black76_price(F, K, T, r, sigma, option_type)` — Black-76 model for futures options, where `F` is the futures price. Reuses existing IBKR chain infra which already supports STK/FUT underlyings.

**Greeks for both models**:
- `black_scholes_greeks(S, K, T, r, sigma, option_type, q=0.0)` → `GreeksSnapshot` — dividend-adjusted Greeks (delta includes `e^(-qT)` factor, etc.)
- `black76_greeks(F, K, T, r, sigma, option_type)` → `GreeksSnapshot` — futures option Greeks

**IV solver**: `implied_volatility(market_price, S, K, T, r, option_type, q=0.0)` — **hybrid solver**:
1. Check dividend-adjusted arbitrage bounds: call ≤ S·e^(-qT), put ≤ K·e^(-rT), both ≥ max(0, intrinsic_discounted)
2. Newton-Raphson with vega as derivative (fast convergence in normal regime)
3. If Newton fails to converge or vega is near-zero (deep ITM/OTM), fall back to Brent's method (bisection-like, guaranteed convergence on [0.001, 5.0])

Uses `math.erf` for normal CDF — no external dependencies. `math.erf` provides full double precision (~15 digits), which is more than sufficient.

### `options/analyzer.py`

Orchestrator combining payoff analysis with Greeks.

**`OptionAnalyzer.analyze(strategy, *, price_range, payoff_steps, risk_free_rate, dividend_yield, model, reference_date)`** → `StrategyAnalysisResult`
- Auto-computes price range from strikes if not provided. **Stock-only fallback**: when no option legs exist (no strikes), center range on `underlying_price` with ±30% band. Raises `ValueError` if neither strikes nor `underlying_price` are available for range computation.
- `model` parameter: `"bs"` (default, generalized Black-Scholes with dividend yield) or `"black76"` (for futures options). Determines which pricing/Greeks function is called per option leg.
- Runs `analyze_leg()` for each leg:
  - **Option legs (call/put)**: local BS or Black-76 Greeks depending on `model` param (uses `dividend_yield`, default 0.0; default vol 30% when IV unavailable)
  - **Stock legs**: raw delta=1.0 (unsigned), all other Greeks=0 — no pricing model needed. The `direction` sign is applied during aggregation (just like option legs), so stock leg delta is stored as `1.0` regardless of long/short.
- Validates expiration requirements: all option legs (call/put) must have an expiration date and must share the same expiry. Stock legs (no expiry) are exempt. Raises `ValueError` if option legs are missing expiration or have mixed expiries.
- **DTE validation**: Computes `DTE = (expiration - reference_date).days` for each option leg.
  - `DTE < 0` (expired): raises `ValueError` — expired options cannot be analyzed.
  - `DTE == 0` (expiration day): payoff-only mode — Greeks set to None, cost_of_leverage skipped. Payoff table and breakevens still computed (pure expiration payoff).
  - `DTE >= 1`: full analysis with Greeks. Requires `underlying_price` on the strategy (raises `ValueError` if None — Greeks need spot price).
- Computes strategy-level breakevens, max P/L, risk:reward, payoff table via analytic piecewise approach
- Aggregates Greeks across legs: `sum(greek * direction * size * multiplier)`
- `risk_reward_ratio`: None when either max_profit or max_loss is None (unlimited) or when max_loss is 0 (zero-risk edge case, e.g., arbitrage). When both are finite and max_loss != 0, `abs(max_profit / max_loss)`.
- Populates `assumptions` field with model limitations

## Phase 2: IBKR Data Enrichment

### `OptionAnalyzer.enrich_with_ibkr(strategy, result, ibkr_client, model="bs")`

Takes the original `OptionStrategy` (which carries full leg definitions including expiration, strike, option_type, con_id) alongside the analysis result. The `model` parameter determines behavior: `"bs"` runs IBKR enrichment for equity options; `"black76"` skips enrichment entirely (deferred, see below). This avoids needing to reconstruct contract identity from result objects.

- **Stock legs are skipped** — only call/put legs are resolved to IBKR contracts. Stock legs retain raw delta=1.0 (unsigned, same as Phase 1) with no IBKR call.
- **Equity options (model="bs")**: Resolves each option leg to an IBKR Option contract via existing `resolve_option_contract()` — supports both `con_id` (if provided on the leg) and field-based resolution. Maps `OptionLeg` fields to `contract_identity` dict: `leg.expiry_yyyymmdd` → `expiry` (already YYYYMMDD string, matching IBKR convention), `option_type` → `right` ("call"→"C", "put"→"P"), `strike` → `strike`, `underlying_symbol` from strategy.
- **Futures options (model="black76")**: IBKR enrichment for futures options is **deferred beyond Phase 2**. The existing `resolve_option_contract()` builds `OPT` contracts (not `FOP`), and `fetch_snapshot()` only requests option generic ticks for `secType == "OPT"` — qualified `FOP` contracts would likely return empty Greeks. Phase 2 enrichment targets equity options only. Black-76 local Greeks remain the source for futures options until a dedicated FOP resolver + snapshot path is added.
- Calls existing `IBKRClient.fetch_snapshot()` directly (not the MCP tool wrapper) for live Greeks + bid/ask/mid + OI
- **Partial failure handling**: Two levels of fallback:
  1. **Leg-level failure** (snapshot returns error): keep the existing local Greeks (BS or Black-76, whichever model was used) for that leg, log a warning.
  2. **Field-level None** (snapshot succeeds but individual Greek fields are None, e.g., IBKR returns bid/ask but no `modelGreeks`): merge per-field — keep local value for any IBKR field that is None, only overwrite with non-None IBKR values.
  - Each `LegAnalysis.greeks_source` tracks provenance independently. Never silently discard working Greeks.
- Recomputes aggregate Greeks from whatever mix of local/ibkr Greeks are available (stock legs always contribute delta only)

### `options/chain_analysis.py`

OI/volume analysis for option chains. Uses `IBKRClient` / `fetch_snapshot()` directly — does NOT call MCP tool wrappers from internal module code.

**`analyze_chain(chain_data, strike_snapshots, strategy=None)`** → dict with:
- `oi_by_strike`: {strike: {call_oi, put_oi, total}}
- `volume_by_strike`: similar
- `put_call_ratio`: aggregate ratio
- `max_pain`: strike that **minimizes aggregate payout** to all option holders (ITM call + put value summed across all OI at each candidate strike). This is the standard max-pain definition, not simply the strike with most OI.
- `strategy_overlay`: breakevens positioned against OI distribution

Data flow: caller fetches chain via `ibkr/metadata.py::fetch_option_chain()`, then prices/OI via `IBKRClient.fetch_snapshot()`, and passes both into `analyze_chain()`. The function itself is pure computation.

## Phase 3: MCP Tool

### `mcp_tools/options.py`

Follows the `mcp_tools/trading_analysis.py` pattern: stdout redirect, try/except, status envelope.

**`analyze_option_strategy(legs, underlying_symbol=None, underlying_price=None, description=None, price_range=None, use_ibkr_greeks=False, dividend_yield=0.0, risk_free_rate=0.05, model="bs", format="summary")`** → dict

All parameters except `legs` are optional with sensible defaults.

- `legs`: list of dicts (MCP-friendly), each with:
  - `position`: "long" or "short" (required)
  - `option_type`: "call", "put", or "stock" (required)
  - `strike`: float, must be > 0 for call/put legs (required). Omit or 0 for stock legs only.
  - `premium`: float per-share, must be >= 0 (required). Direction comes from `position`, not premium sign.
  - `size`: int, must be > 0 (default 1)
  - `expiration`: "YYYYMMDD" string (required for option legs — needed for Greeks, DTE, same-expiry validation, and IBKR contract resolution; matches existing IBKR convention in `ibkr/contracts.py::resolve_option_contract()` which forwards expiry as-is). Not applicable for stock legs.
  - `con_id`: int (optional, IBKR contract ID for direct resolution)
- Input validation: reject unknown `option_type`, missing required fields, non-positive strikes for option legs, option legs missing `expiration`, mismatched expiries across option legs (Phase 1 same-expiry only) with clear error messages.
- IBKR validation: When `use_ibkr_greeks=True` and `model="bs"`: require either `underlying_symbol` on the tool call or `con_id` on every option leg — if neither is available, return a clear error (not a silent fallback) since the user explicitly opted into live data. When `use_ibkr_greeks=True` and `model="black76"`: ignore the flag and include a `warnings` entry in the response dict (e.g., `"warnings": ["IBKR Greeks not available for futures options yet — using local Black-76 model"]`) so the caller sees it in the API response, not just in server logs.
- Auto-fetches underlying price from FMP if symbol given but price omitted
- `use_ibkr_greeks`: opt-in to live IBKR Greeks (requires gateway)
- `dividend_yield`: float (default 0.0)
- `model`: "bs" (default) or "black76" (for futures options) — passed through to `OptionAnalyzer.analyze()`. When `model="black76"`, `underlying_price` is required and must be > 0 (no FMP auto-fetch — FMP is equity-oriented and not a reliable futures price source). `underlying_price > 0` is also validated when provided for any model (prevents invalid range/BS computation).
- `risk_free_rate`: float (default 0.05) — passed through to analyzer for BS/Black-76 Greeks
- `format`: "full" | "summary" | "report"

### `mcp_server.py` registration

Import + `@mcp.tool()` wrapper, same pattern as all other tools.

### `mcp_tools/__init__.py` update

Add `analyze_option_strategy` to the import list and `__all__` exports, following the existing pattern (every tool is exported here).

### `tests/options/test_mcp_options.py`

MCP tool behavior tests + `mcp_server.py` registration/signature checks, following the pattern in `tests/mcp_tools/` and `tests/unit/test_mcp_server_contracts.py`.

## Phase 4: Portfolio Risk Integration (future)

- Delta-equivalent exposure for option positions in `core/portfolio_analysis.py`
- Aggregate options Greeks table in `RiskAnalysisResult`
- Deferred until Phases 1-3 are proven in daily use

## Existing Code Reused

| File | What | Phase |
|------|------|-------|
| `ibkr/contracts.py::resolve_option_contract()` | Contract construction from conId or fields | 2 |
| `ibkr/market_data.py::IBKRMarketDataClient.fetch_snapshot()` | Live Greeks via generic ticks 100,101,106 | 2 |
| `ibkr/metadata.py::fetch_option_chain()` | Chain discovery (expirations, strikes) | 2 |
| `ibkr/client.py::IBKRClient` | Facade for all IBKR calls (NOT MCP wrappers) | 2 |
| `trading_analysis/symbol_utils.py` | Option symbol parsing if needed | 1-2 |
| `fmp/client.py::FMPClient` | Auto-fetch underlying price in MCP tool | 3 |
| `mcp_tools/trading_analysis.py` | Pattern: stdout redirect, try/except, status envelope | 3 |
| `trading_analysis/models.py` | Pattern: dataclass + to_dict/to_summary/to_api_response/to_cli_report | 1 |

## Implementation Order

| Step | What | Files | Effort |
|------|------|-------|--------|
| 1 | Models + package init | `options/__init__.py`, `options/models.py` | Small |
| 2 | Payoff engine (analytic piecewise) | `options/payoff.py` | Medium |
| 3 | Local BS/Black-76 Greeks + hybrid IV solver | `options/greeks.py` | Medium |
| 4 | Analyzer orchestrator | `options/analyzer.py` | Medium |
| 5 | Tests (payoff, greeks, analyzer) | `tests/options/test_payoff.py`, `test_greeks.py`, `test_analyzer.py` | Medium |
| 6 | IBKR enrichment with partial-failure handling | `options/analyzer.py` additions | Small |
| 7 | Chain analysis with correct max-pain | `options/chain_analysis.py` | Medium |
| 8 | MCP tool + registration + MCP tests | `mcp_tools/options.py`, `mcp_server.py`, `tests/options/test_mcp_options.py` | Small |

## Verification

1. **Unit tests**: `python -m pytest tests/options/ -v`
2. **Spreadsheet parity**: Analyze the SLV 30C/35C bull call spread and compare output to the Google Sheet (HC version) — breakevens, max P/L, risk:reward, time value should match
3. **Stock+option overlay**: Verify protective put on 100 shares produces correct combined payoff (linear stock + put floor)
4. **Greeks validation**: Put-call parity (C - P = S·e^(-qT) - K·e^(-rT)), delta bounds, IV round-trip
5. **MCP tool**: Call `analyze_option_strategy` via portfolio-mcp, verify response structure + registration
6. **IBKR live** (Phase 2): With gateway running, `use_ibkr_greeks=True` should populate real Greeks; verify partial failure at both levels:
   - Leg-level: one leg's snapshot fails entirely → local Greeks preserved for that leg
   - Field-level: snapshot succeeds but e.g. `delta=None` with other fields present → local delta preserved, IBKR values used for non-None fields, source marked as `mixed`
