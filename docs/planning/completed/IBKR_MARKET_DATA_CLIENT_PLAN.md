# IBKR Market Data Client Plan

> **Status**: Complete (all 8 phases implemented and live-tested)
> **Created**: 2026-02-14
> **Updated**: 2026-02-15
> **Owner**: Codex + Henry
> **Result**: P-002 unpriceable symbols reduced 20 → 4 (80% reduction). All instrument types tested live with TWS.

## Summary

Build a first-class IBKR market data client (similar layering to `fmp/`) so pricing logic is centralized, testable, and easy to evolve for futures/options/bonds/FX.

This plan supports closing `P-002` in `/Users/henrychien/Documents/Jupyter/risk_module/docs/performance-bugs.md` by reducing unpriceable symbols and making instrument handling explicit.

**Key prerequisite (from Codex review):** Instrument metadata (`is_option`, `is_futures`, `is_fx_artifact`, `is_bond`) already exists at transaction ingestion time but is dropped before it reaches the pricing/NAV loop. Before building the market data client, we must thread instrument type through the pipeline so the pricing layer knows what profile to use for each symbol.

## Why Now

Current IBKR pricing code is narrow and scattered:
- `services/ibkr_historical_data.py` only handles futures monthly closes.
- `core/realized_performance_analysis.py` calls IBKR fallback inline.
- No unified contract resolution/fallback policy by instrument type.
- Instrument metadata is lost between transaction ingestion and NAV valuation — the pricing loop sees only `(ticker_string, currency, direction)` with no way to route to the correct provider/profile.

Recent live checks (2026-02-14) show IBKR is viable but instrument-specific:
- Futures: `TRADES` monthly works.
- FX: `MIDPOINT/BID/ASK` works; `TRADES` returns no data.
- Bonds: needs concrete contract identity; `MIDPOINT/BID/ASK` works better than `TRADES`.
- Options: contract qualification works if fully specified; useful history is typically quote-based and often intraday rather than EOD bars.

## Design Decision

Use an FMP-like structure, adapted for IBKR contract semantics:
- Keep layered architecture (`client`, `cache`, `compat`, `exceptions`).
- Replace endpoint registry concept with instrument request profiles (`futures`, `fx`, `bond`, `option`).
- Preserve execution stability via connection isolation:
  - trade execution continues through `services/ibkr_connection_manager.py`
  - market data uses a dedicated read-only IB session/clientId by default
  - Flex remains separate (HTTP/XML path)

### Upstream data contract (prerequisite)

Instrument metadata must flow from ingestion to pricing. Two things are needed:

1. **Instrument type** — so the pricing loop knows which provider profile to use
2. **Contract identity fields** — so the IBKR client can resolve the right contract (conId, expiry, strike, right, multiplier, exchange)

Current state:

| Source | Available at ingestion | Survives to position timeline? |
|--------|----------------------|-------------------------------|
| IBKR Flex | `assetCategory` (STK/OPT/FUT/BOND/CASH), `conid`, `expiry`, `strike`, `putCall`, `multiplier`, `exchange` | `is_futures` used for FMP map augmentation only; everything else dropped at `build_position_timeline()` |
| Plaid | `security_type`, option/bond metadata in raw response | Not tagged; options inferred from description regex |
| SnapTrade | `snaptrade_type_code` (cs, op, etc.) | Not preserved |

**Required changes:**

**A. Add `instrument_type` field** to transaction dicts and position timeline.

Proposed enum values: `equity`, `option`, `futures`, `fx_artifact`, `bond`, `unknown`.

**B. Add `contract_identity` dict** to transaction dicts (optional, populated when available).

```python
"contract_identity": {
    "con_id": 12345,           # IBKR contract ID (most reliable)
    "expiry": "20250815",      # YYYYMMDD
    "strike": 110.0,
    "right": "C",              # C or P
    "multiplier": 100,
    "exchange": "SMART",
}
```

This is only populated by IBKR Flex (which has all fields). Plaid/SnapTrade options will have `instrument_type="option"` but `contract_identity=None` — the IBKR client can attempt contract resolution from the parsed symbol string as a fallback.

**C. Carry metadata via side dict, not by expanding timeline key (decision: Option B).**

The position timeline key stays `(ticker, currency, direction)` — a 3-tuple. Instrument metadata is carried in a separate dict:

```python
instrument_meta: Dict[Tuple[str, str, str], InstrumentMeta]
```

Where `InstrumentMeta` is a lightweight dataclass/TypedDict with `instrument_type` and optional `contract_identity`. This avoids churn across the many functions that destructure the 3-tuple key (`build_position_timeline`, `compute_monthly_nav`, `_create_synthetic_cash_events`, `compute_monthly_returns`, reconciliation logic, etc.).

**D. Where tagging happens:**
- **IBKR Flex** (`ibkr_flex_client.py:226-242`): add `instrument_type` + `contract_identity` to normalized output
- **Plaid** (`analyzer.py`): infer `instrument_type` from `is_option` flag, `security_type`, symbol patterns (`GBP.HKD` → `fx_artifact`)
- **SnapTrade** (`analyzer.py`): map `snaptrade_type_code` → `instrument_type`
- **Backfill** (`realized_performance_analysis.py:1143`): default to `equity` unless overridden in backfill JSON
- **Synthetic entries** (`build_position_timeline:567-609`): inherit `instrument_type` from `current_positions` metadata
- **`current_positions`** (`_build_current_positions:110-164`): needs `instrument_type` derived from position data (Plaid `security_type`, SnapTrade type code, or default `equity`)

**E. Where routing happens:**

The **price-fetch loop** (`realized_performance_analysis.py:1572-1614`) is where provider selection occurs — NOT inside `compute_monthly_nav()` (which just multiplies qty × price). The loop currently iterates tickers; it will use `instrument_meta[key].instrument_type` to decide: FMP for equities, IBKR profiles for futures/FX/bonds/options.

### Symbol filtering (pre-pricing)

Before pricing, filter out non-investable symbols that should never enter the NAV. Filtering is driven by `instrument_type`, not by hardcoded symbol names:

- `instrument_type == "fx_artifact"` → filter (e.g., `GBP.HKD`, `USD.HKD` — Plaid cash-conversion records)
- `instrument_type == "unknown"` → filter (e.g., `Unknown_C2_230406` — unresolvable)
- Filter at `build_position_timeline()` stage with explicit warnings listing each filtered symbol and reason

## Target Structure

Create:
- `services/ibkr_data/__init__.py`
- `services/ibkr_data/client.py`
- `services/ibkr_data/contracts.py`
- `services/ibkr_data/profiles.py`
- `services/ibkr_data/cache.py`
- `services/ibkr_data/exceptions.py`
- `services/ibkr_data/compat.py`

Keep existing modules initially; migrate callers gradually.

Connection policy (explicit):
- `trading_session`: `IBKRConnectionManager.ensure_connected()` (existing behavior)
- `market_data_session`: dedicated read-only connection with worker-safe clientId assignment
- `flex_session`: `ibkr_flex_client` (statement/report ingestion)
- Optional future mode: shared session for low-volume environments, disabled by default
- New env var `IBKR_MARKET_DATA_CLIENT_ID` (optional; falls back to `IBKR_CLIENT_ID + 1` for local dev)

Async/event-loop safety (from Codex review):
- Current IBKR historical path requires `nest_asyncio.apply()` because FastMCP runs an asyncio event loop and `ib_async` calls `loop.run_until_complete()` internally.
- New client must explicitly define loop/thread safety: `nest_asyncio.apply()` at module level, thread lock around IB calls (matching existing `_ibkr_request_lock` pattern in `services/ibkr_historical_data.py`).
- Document in client module docstring.

Production config hardening (multi-worker, endpoint mode, `WEB_CONCURRENCY` parsing, `RISK_APP_ENV` detection) is **deferred to a separate plan** — zero market data capability impact, and we're not deploying to multi-worker production yet.

## Client API (Proposed)

### Core entrypoint

`IBKRMarketDataClient.fetch_series(...)`

Inputs:
- instrument type (`futures|fx|bond|option`)
- symbol or contract spec
- date range
- frequency (`daily|monthly`)
- preferred price source (`TRADES|MIDPOINT|BID|ASK|AUTO`)

Behavior:
- resolve/qualify contract
- get IB session using connection policy (`market_data_session` by default)
- apply instrument-specific fallback profile
- fetch bars
- normalize timezone/index
- resample to requested frequency
- return `pd.Series` (matching existing `fetch_monthly_close()` return type for drop-in compatibility)

Metadata (warnings, provider, whatToShow used) logged at DEBUG/WARNING level, not embedded in return value. This keeps the return contract identical to FMP's `fetch_monthly_close()` so callers don't need changes.

### Convenience methods

- `fetch_monthly_close_futures(...)`
- `fetch_monthly_close_fx(...)`
- `fetch_monthly_close_bond(...)`
- `fetch_monthly_close_option(...)`

### Compatibility wrapper

`services/ibkr_data/compat.py` exports drop-in helpers to minimize caller churn:
- `fetch_ibkr_monthly_close(...)` (futures-compatible alias)
- `fetch_ibkr_fx_monthly_close(...)`
- `fetch_ibkr_bond_monthly_close(...)`
- `fetch_ibkr_option_monthly_mark(...)`
- `fetch_ibkr_series(...)` generic adapter for migration call sites

## Fallback Profiles (Key Behavior)

### Futures
1. `TRADES` monthly (current behavior)
2. fallback `MIDPOINT` monthly (if needed for sparse contracts)

### FX
1. `MIDPOINT` daily -> resample to month-end
2. fallback `BID`, then `ASK`
3. never prefer `TRADES`

### Bonds
1. resolve concrete contract (conId/cusip/isin mapping where available)
2. `MIDPOINT` daily -> month-end
3. fallback `BID`, then `ASK`

Bond contract normalization policy (v1 — minimal):
- If conId is available (e.g., from IBKR Flex `conid` field), use it directly.
- Otherwise, warn and skip. ISIN/CUSIP resolution deferred until real bond positions exist to test against.
- Ambiguous matches are treated as unresolved (warning + no silent guess).

### Options (stub — flesh out after confirming entitlements)
1. resolve fully specified contract (expiry/strike/right/multiplier) — metadata must flow from upstream instrument tagging
2. fetch quote history (`MIDPOINT`/`BID`/`ASK`)
3. if unresolved/unavailable, return empty Series + log structured warning
4. **Expired options**: For options that expired before the pricing window, use the FIFO close price (already captured at trade time) as terminal value. No IBKR fetch needed — the transaction data is sufficient.

Detailed option mark derivation (exchange calendars, intraday cutoffs, stale-mark labeling, NBBO midpoint derivation) deferred until IBKR option data entitlements are confirmed and tested live.

## Caching Strategy

Disk cache under `cache/ibkr` (Parquet + zstd), with deterministic keys including:
- contract fingerprint (conId if known, else normalized spec)
- `whatToShow`, bar size, RTH flag
- date range
- frequency/resample mode

Rules:
- cache successful responses
- do not cache hard failures
- cache empty responses briefly only when explicitly configured
- **Freshness for current-month requests**: If the requested date range includes the current month, apply a short TTL (e.g., 4 hours) so intra-month re-runs pick up updated prices. Match the FMP client's freshness token pattern (`fmp/client.py` uses month-based cache busting).

## Migration Plan

## Phase 0: Baseline and Safety

1. Add integration smoke script (non-production) for IBKR instrument checks.
2. Capture baseline on current realized performance run:
   - unpriceable symbol count (currently 20)
   - `official_metrics_estimated`
   - `high_confidence_realized`

## Phase 1: Upstream Instrument Tagging & Symbol Filtering

**This is the prerequisite for all subsequent phases.** Without instrument type and contract identity flowing through to pricing, the market data client can't route symbols or resolve contracts correctly.

1. Define `InstrumentMeta` dataclass/TypedDict with `instrument_type` (enum) and optional `contract_identity` dict.
2. Add `instrument_type` + `contract_identity` fields to transaction dicts at each source:
   - `ibkr_flex_client.py` `normalize_flex_trades()` — map `assetCategory` → `instrument_type`; populate `contract_identity` from `conid`, `expiry`, `strike`, `putCall`, `multiplier`, `exchange`
   - `TradingAnalyzer._process_plaid()` — infer `instrument_type` from `security_type`, description regex, symbol patterns (e.g., `X.Y` with FX currencies → `fx_artifact`)
   - `TradingAnalyzer._process_snaptrade()` — map `snaptrade_type_code` → `instrument_type`
   - `TradingAnalyzer._process_ibkr_flex()` — forward from flex normalization
   - Backfill loader (`_load_and_inject_backfill`) — default `instrument_type="equity"` unless overridden in backfill JSON
3. Thread metadata through pipeline via side dict (Option B — timeline key stays 3-tuple):
   - `build_position_timeline()` returns additional `instrument_meta: Dict[Tuple[str,str,str], InstrumentMeta]`
   - Built from first transaction seen for each key (instrument type doesn't change mid-timeline)
   - **Conflict handling:** If a later transaction has a different `instrument_type` for the same 3-tuple key, log a warning and keep the first tag (no silent override). This should be rare — it would mean e.g. the same `(AAPL, USD, LONG)` is tagged as both `equity` and `option`, which indicates a normalization bug upstream.
   - Synthetic entries inherit `instrument_type` from `current_positions` metadata
4. Add `instrument_type` to `_build_current_positions()` output — derive from position data (Plaid `security_type`, SnapTrade type code, or default `equity`).
5. Add symbol filtering in `build_position_timeline()`:
   - Filter based on `instrument_type` (not hardcoded symbol names)
   - `fx_artifact` and `unknown` → exclude from timeline
   - Emit explicit warning per filtered symbol with reason
6. Price-fetch loop (`realized_performance_analysis.py:1572`) uses `instrument_meta` to select provider — no changes to `compute_monthly_nav()` itself (it just multiplies qty × price).
7. Add tests:
   - `tests/trading_analysis/test_instrument_tagging.py` — verify `instrument_type` + `contract_identity` from each source
   - `tests/core/test_symbol_filtering.py` — verify filtering by type with warnings
   - Regression on existing realized performance tests
   - Collision test: same ticker string across different instrument types

**Expected P-002 impact:** Removes 3 unpriceable symbols (2 FX artifacts + 1 unknown) immediately, and enables all subsequent phases with proper routing.

## Phase 2: Scaffold IBKR Data Package

1. Create `services/ibkr_data/*` package with:
   - typed request/response objects
   - exceptions
   - client skeleton + profiles
   - cache helper
   - connection adapter for `market_data_session` (dedicated clientId, `nest_asyncio`, thread lock)
2. Add unit tests for profile selection and cache key generation.
3. Introduce provider protocol shape (thin interface matching `fetch_monthly_close()` signature) for future composite provider.

## Phase 3: Migrate Existing Futures Path (No Behavior Change)

1. Re-implement current futures logic through new client.
2. Update `services/ibkr_historical_data.py` to delegate to new compat wrapper.
3. Verify outputs are unchanged for `MGC`, `ZF`.

## Phase 4: Add FX Support

1. Implement FX profile (`MIDPOINT` first, fallback `BID` then `ASK`).
2. Wire into realized performance pricing loop: when `instrument_type == "fx_artifact"` is already filtered, this phase targets any remaining FX pairs that are actual positions.
3. Add tests for `whatToShow` fallbacks and empty-result behavior.

**Expected P-002 impact:** Highest practical impact — FX pricing was previously impossible via FMP.

## Phase 5: Add Bond Support (if needed)

1. Implement bond profile with conId-based contract resolution (v1 minimal).
2. For Plaid bond names (`US Treasury Bill - 5.35% 08/08/2024 USD 100`): attempt to extract maturity/coupon for contract search, warn and skip if unresolvable.
3. Add tests for contract resolution and empty-result behavior.

**Expected P-002 impact:** Could resolve 2 treasury symbols, but depends on contract identifiability.

## Phase 6: Add Option Support (after confirming entitlements)

1. Add option contract resolver using metadata from upstream instrument tagging (expiry, strike, right already encoded in IBKR-format symbols like `PDD_C110_250815`).
2. For **expired options**: use FIFO close price as terminal value — no IBKR fetch needed.
3. For **open options**: fetch quote history from IBKR if entitlements allow.
4. Add warnings for entitlement/availability gaps.

**Expected P-002 impact:** Could resolve up to 13 option symbols (11 IBKR + 2 Plaid format).

## Phase 7: Integrate into Realized Performance

1. Replace inline IBKR fallback block in `core/realized_performance_analysis.py`.
2. Route pricing by `instrument_type` from position timeline.
3. Add metadata fields for IBKR pricing coverage:
   - priced via IBKR count
   - unresolved/unpriceable with reason categories
4. Measure against Phase 0 baseline.

## Phase 8: Retire Legacy Paths

1. Keep `services/ibkr_historical_data.py` as thin compatibility layer or remove after migration.
2. Update docs.
3. Remove duplicated ad-hoc connection/fallback logic.

## Deferred: Production Config Hardening

Separate plan for when multi-worker production deployment is needed:
- Multi-worker detection (`IBKR_MULTI_WORKER`, `WEB_CONCURRENCY`)
- `RISK_APP_ENV`/`APP_ENV` production mode detection
- Endpoint mode config (`tws|gateway`, `live|paper`)
- Partial `IBKR_HOST`/`IBKR_PORT` override rejection
- Startup diagnostics and guardrails

## Test Plan

Phase 1 (upstream tagging + filtering):
- `tests/trading_analysis/test_instrument_tagging.py` — verify `instrument_type` propagated from each source
- `tests/core/test_symbol_filtering.py` — verify FX artifacts and unresolvable symbols filtered with warnings
- Regression: `tests/core/test_realized_performance_analysis.py` — existing tests still pass with new timeline key shape

Phase 2 (IBKR data package):
- `tests/services/test_ibkr_data_client.py` — profile selection, contract resolution
- `tests/services/test_ibkr_data_cache.py` — cache key generation, freshness TTL
- Deterministic unit fixtures for IB error-code mapping and contract-resolution decision trees (no IBKR Gateway required)

Compatibility tests:
- keep/extend `tests/services/test_ibkr_historical_data.py`

Integration tests (gated by IBKR availability):
- futures monthly (`MGC`, `ZF`)
- FX daily→monthly (`USDHKD`, `GBPHKD`)
- bond by concrete contract (when applicable)
- option contract (after confirming entitlements)

Failure-mode tests (unit):
- IB pacing / throttling errors (retry/backoff behavior)
- entitlement error handling (reason-coded warning output)
- contract ambiguity (no silent selection)
- cache behavior for empty responses vs hard failures
- isolation: market-data session does not disrupt trade-execution session

Realized performance regression:
- `tests/core/test_realized_performance_analysis.py`

## Acceptance Criteria

1. `instrument_type` flows from transaction ingestion through position timeline to pricing loop.
2. `contract_identity` (when available from IBKR Flex) survives ingestion → timeline metadata → option/bond resolver input.
3. FX artifacts and unresolvable symbols are filtered before NAV with explicit warnings.
4. New IBKR market data client package exists with tests.
5. Current futures behavior is preserved (`MGC`, `ZF` unchanged).
6. FX pricing available through the client with `MIDPOINT` fallback chain.
7. `core/realized_performance_analysis.py` no longer contains ad-hoc IBKR fetch logic (after Phase 8).
8. `P-002` unpriceable count decreases from 20 to a measurable target:
   - Phase 1: 20 → 17 (filter 2 FX artifacts + 1 unknown)
   - Phase 4+: further reductions based on FX/bond/option pricing capability
9. Trade execution session remains isolated from market-data session by default.
10. Return type is `pd.Series` matching existing FMP contract — no caller changes needed.

## Risks and Mitigations

- **Upstream tagging blast radius**: Adding instrument metadata touches multiple pipeline stages.
  - Mitigation: Side dict approach (Option B) keeps timeline key as 3-tuple, avoiding churn across ~10 functions that destructure it. Phase 1 is isolated and testable before any IBKR client work.
- **Entitlement gaps in IBKR account** (options, bonds):
  - Mitigation: profile-level fallbacks + reason-coded warnings. Options/bonds deferred until confirmed.
- **Async/event-loop regression**: New client must work inside FastMCP's asyncio loop.
  - Mitigation: Explicit `nest_asyncio.apply()` + thread lock, matching proven pattern in `ibkr_historical_data.py`.
- **Contract ambiguity** (especially bonds):
  - Mitigation: v1 uses conId only; warn and skip if unavailable.
- **Refactor blast radius**:
  - Mitigation: compat wrappers + phased migration.
- **Connection contention** between historical data pulls and order flow:
  - Mitigation: dedicated market-data clientId/session.

## Out of Scope (This Plan)

- Replacing FMP globally for all equity pricing.
- Multi-provider smart-routing beyond IBKR/FMP in one pass (provider protocol is introduced but CompositeProvider is future work).
- Full fixed-income analytics stack (curve building, spreads, risk Greeks).
- Production config hardening (multi-worker, endpoint mode, guardrails) — separate plan.
- Detailed option mark derivation (exchange calendars, intraday cutoffs, stale labeling) — deferred until entitlements confirmed.

## Execution Order Recommendation

1. **Phase 0 + 1 first** — baseline capture + upstream instrument tagging. This is the critical prerequisite that unblocks everything else and delivers immediate P-002 wins (3 symbols filtered).
2. **Phase 2 + 3** — scaffold + migrate futures (low risk, preserves behavior).
3. **Phase 4** — FX support (highest practical P-002 impact after filtering).
4. **Phase 5-6** — bonds and options, after confirming data availability.
5. **Phase 7-8** — integration + legacy retirement.

---

## Codex Review #2 (2026-02-15)

### HIGH findings

1. **Contract identity still not propagated** — v2 only added `instrument_type` but later phases (bonds, options) need `conId`, `expiry`, `strike`, `right` etc. **Resolution:** Added `contract_identity` dict to upstream data contract. IBKR Flex populates fully; Plaid/SnapTrade leave as `None` with fallback to symbol-string parsing.

### MED findings

1. **Routing point misidentified** — Plan said update `compute_monthly_nav()` but routing happens in price-fetch loop (line 1572). **Resolution:** Corrected — `compute_monthly_nav()` unchanged, routing via `instrument_meta` in price-fetch loop.
2. **Timeline key design undecided** — Option A vs B left open. **Resolution:** Decided Option B (side dict). Key stays 3-tuple, avoids churn across ~10 functions that destructure it.
3. **Missing tagging sources** — Backfill loader and `current_positions` / synthetic entries had no instrument metadata. **Resolution:** Added explicit tagging for backfill (default `equity`), `_build_current_positions()`, and synthetic entry inheritance.
4. **Filter rule was symbol-literal, not type-driven** — **Resolution:** Filtering now keyed off `instrument_type` enum, not hardcoded symbol names.

### LOW findings

1. **Same-ticker collision across instrument types** — **Resolution:** Added collision test to Phase 1 test plan.

---

## Codex Review #1 (2026-02-15)

### HIGH findings (addressed in v2)

1. **Contract identity gap** — Instrument metadata (conId, expiry, strike, right) exists at ingestion but is dropped before pricing. **Resolution:** Added Phase 1 (upstream instrument tagging) as prerequisite.
2. **No symbol→instrument map in NAV build** — Pricing loop iterates flat ticker keys with no routing info. **Resolution:** `instrument_type` threaded through position timeline.
3. **Missing filter phase** — FX artifacts and unresolvable symbols should be filtered, not priced. **Resolution:** Added symbol filtering to Phase 1.
4. **Expired options feasibility gap** — Plan tried to price expired options via IBKR fetch when FIFO close price already exists. **Resolution:** Use trade-time close price as terminal value for expired options.
5. **Async/nest_asyncio risk** — Not explicitly addressed. **Resolution:** Added async safety requirements to connection policy section.

### MED findings (addressed in v2)

- Config hardening too early → deferred to separate plan
- Cache freshness incomplete → added current-month TTL rule
- Session lifecycle ambiguous → clarified in connection policy
- Return contract mismatch → specified `pd.Series` return, metadata via logging
- Test plan too integration-heavy → added deterministic unit fixture requirement

### LOW findings (accepted)

- Cache key endpoint fingerprint fragmentation — acceptable for correctness
- Option calendar strict-fail — deferred with the option phase
- Baseline→target numbers — added concrete targets to acceptance criteria

---

## Review Notes (2026-02-15, pre-Codex)

Structural review comparing against the working FMP client (`fmp/client.py`, `registry.py`, `cache.py`, `compat.py`, `exceptions.py`).

### What's sound

- **FMP-mirroring layering is correct.** The `client / cache / compat / exceptions` separation matches what works in FMP.
- **Profiles replacing registry is the right IBKR analog.** FMP has flat REST endpoints (all same shape: HTTP GET → JSON). IBKR varies by instrument type (contract resolution, `whatToShow` fallback chains, bar semantics). Instrument profiles (`futures`, `fx`, `bond`, `option`) map the same "declarative metadata" idea onto IBKR's contract world.
- **Connection isolation** is well thought through — dedicated clientIds, compat layer preserving current behavior during migration.
- **Phased migration** with compat wrappers is the right blast-radius strategy.

### Simplifications applied (v2)

1. **Phase 1a config hardening deferred** — zero market data capability, ~40% of plan by line count. Moved to separate plan.
2. **Option path simplified** — exchange calendar providers, intraday mark derivation, NBBO midpoint kept as placeholder. Flesh out after confirming entitlements.
3. **Bond contract normalization simplified** — v1 uses conId only; ISIN/CUSIP resolution deferred.
4. **Provider protocol introduced** — thin interface shape in Phase 2 for future composite provider.
