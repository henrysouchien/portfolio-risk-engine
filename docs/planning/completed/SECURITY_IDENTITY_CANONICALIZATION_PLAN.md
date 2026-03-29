# Security Identity Canonicalization — Implementation Plan

## Status

Codex-reviewed PASS (9 review rounds)

## Context

The "zero factor betas" issue is a security-identity problem. The same instrument appears under multiple symbols (`AT.` from IBKR, `AT` normalized, `AT.L` for FMP) and symbol resolution happens independently in 6+ locations. When any path misses, the security drops out of factor modeling and `fillna(0.0)` silently collapses "not modeled" into "zero beta."

All three position sources (IBKR, Plaid, SnapTrade) already carry `exchange_mic` on position dicts, and `config/exchange_mappings.yaml` already has MIC→FMP suffix mappings. The infrastructure exists — it just isn't wired into a single canonical resolution point.

### Current Symbol Resolution Locations (6+)

| Location | Mechanism |
|----------|-----------|
| `utils/ticker_resolver.py:resolve_ticker_from_exchange()` | FMP-based, exchange MIC + company name + currency |
| `utils/ticker_resolver.py:resolve_ticker_alias()` | Strip dots + alias map + FMP profile search |
| `providers/symbol_resolution.py:SymbolResolver` | Type-first facade (futures vs equity-like), used by `PositionService` |
| `providers/ticker_resolver.py:AliasMapResolver` | Provider protocol wrapping alias map |
| `core/proxy_builder.py:541` | Calls `utils.ticker_resolver.resolve_ticker_alias()` |
| `services/security_type_service.py` | DB cache keyed by raw ticker |

### Where Zeros Manifest

- `portfolio_risk.py:1728` — `df_stock_betas.fillna(0.0)` fills missing betas
- `portfolio_risk.py:1778-1785` — `stock_factor_proxies.get(ticker, {}).get("industry")` silently skips tickers missing from proxies dict
- `get_returns_dataframe()` (line ~870) — drops tickers with insufficient history before factor computation

### Agreed Architecture

- **Type-first dispatch** → resolve instrument type, then route to the right provider for canonical key
- **FMP-resolved symbol as `security_key`** for equities/ETFs, constructed keys for non-equities
- **Exchange MIC (ISO 10383)** for international disambiguation — already available from all sources
- **ISIN-backed keying** deferred to a future phase
- **Extend existing `SymbolResolver`** rather than creating a duplicate resolver

---

## Phase 0: Define the Identity Contract (No Behavioral Changes)

**Goal:** Introduce `SecurityIdentity`, coverage tracking, and extend `SymbolResolver` to produce identity objects. No existing behavior changes.

### New Files

**`core/security_identity.py`** — frozen dataclass:
- `security_key: str` — canonical join key (e.g., `"AT.L"`, `"FUT:ES"`, `"CASH:USD"`)
- `source_symbol: str` — raw from provider (e.g., `"AT."`)
- `portfolio_symbol: str` — normalized display (e.g., `"AT"`)
- `data_symbol: str` — FMP/provider lookup (e.g., `"AT.L"`)
- `instrument_category: Literal[...]` — equity, etf, futures, option, cash, bond, fx, etc.
- `exchange_mic: Optional[str]`, `currency: Optional[str]`
- `cusip/isin/figi: Optional[str]` — for future ISIN-backed keying
- `resolution_method: str` — one of: `us_passthrough`, `mic_suffix`, `fmp_search`, `futures_spec`, `option_parse`, `cash_proxy`, `manual`, `unresolved`

**`core/coverage_tracking.py`** — per-factor coverage model:
- `FactorCoverage` per factor dimension: `modeled: bool`, `detail: Optional[str]`
- `SecurityCoverage` per security: `security_key`, `factors: Dict[str, FactorCoverage]`, `overall_status: ModelingStatus`, `excluded_at: Optional[str]` (pipeline stage: `"returns"`, `"proxy"`, `"factor"`, `"cash"`)
- `ModelingStatus` enum: `FULLY_MODELED`, `PARTIALLY_MODELED` (e.g., futures with market but no industry), `UNRESOLVED_IDENTITY` (resolution failed but raw-symbol proxying may work — investigate), `EXCLUDED_NO_PROXY`, `EXCLUDED_NO_HISTORY`, `EXCLUDED_CLASSIFICATION_FAILED`, `EXCLUDED_CASH`
- `PortfolioCoverage` aggregate: `add()`, `modeled_count`, `excluded_count`, `partial_count`, `to_dict()`

### Modified File

**`providers/symbol_resolution.py`** — extend existing `SymbolResolver`:
- Add method `resolve_identity()` with signature matching existing `resolve()` params plus identity-specific extras:
  ```python
  def resolve_identity(
      self,
      raw_symbol: str,
      *,
      provider: str,                         # kept from resolve() — required for futures routing
      company_name: str | None = None,        # kept from resolve()
      currency: str | None = None,            # kept from resolve()
      exchange_mic: str | None = None,         # kept from resolve()
      instrument_type: str = "equity",         # kept from resolve() — NOT position_type
      ticker_alias: str | None = None,         # pre-resolved FMP symbol (highest priority)
      # Identity-specific extras:
      position_type: str | None = None,        # for cash detection (position_type == "cash")
      is_option: bool = False,
      option_parse_failed: bool = False,
      underlying: str | None = None,
      strike: float | None = None,
      expiry: str | None = None,
      option_type: str | None = None,
      is_cash_equivalent: bool = False,
      cusip: str | None = None,
      isin: str | None = None,
      figi: str | None = None,
  ) -> SecurityIdentity:
  ```
- Implementation delegates to `self.resolve()` for the `data_symbol` string, then packages into `SecurityIdentity`:
  - **Non-equity types checked FIRST** (before alias): constructed keys for cash, futures, and options take priority over `ticker_alias`. This prevents a futures position with `ticker_alias="ESUSD"` (from contract-spec backfill at `data_objects.py:702`) from getting `security_key="ESUSD"` instead of `"FUT:ES"`.
  - **Cash detection** (`position_type == "cash"`, `CUR:` prefix, `is_cash_equivalent`) → cash key. No provider resolution needed.
  - **Futures detection** (`instrument_type == "futures"`) → `security_key = "FUT:{root}"`. `data_symbol` = `ticker_alias` if set (preserves existing contract-spec alias from `data_objects.py:702` and price-service usage), otherwise `self.resolve()` (which handles IBKR futures map). This matches current behavior where futures `ticker_alias`/`data_symbol` is used for price fetching (`price_service.py:26`, `portfolio_risk.py:592`). `resolution_method = "futures_spec"` if `provider in {"ibkr", "ibkr_flex"}`, else `"unresolved"`.
  - **Option detection** (`is_option=True` and not `option_parse_failed`) → `security_key = "OPT:{underlying}_{right}{strike}_{expiry}"`. `data_symbol = underlying`.
  - **Equity-like types** (equity, etf, mutual_fund, bond, etc.):
    - If `ticker_alias` is set → use as `data_symbol` and `security_key` with `resolution_method="manual"`. This is the primary path for Plaid and SnapTrade positions. IBKR live positions may NOT have `ticker_alias` — they have `exchange_mic` instead.
    - Otherwise call `self.resolve(raw_symbol, provider=provider, ...)` to get `data_symbol`, then determine `resolution_method`:
      - If `exchange_mic in us_mics` → `"us_passthrough"`
      - If `exchange_mic in mic_to_suffix` → `"mic_suffix"`
      - If `data_symbol != base_symbol` (FMP search changed it) → `"fmp_search"`
      - Else → `"unresolved"`
- Load `_us_mics` and `_mic_to_suffix` from `utils.ticker_resolver.load_exchange_mappings()` in `__init__()` (lazy, alongside existing `_futures_map`)
- The existing `resolve() -> str` method is **completely unchanged**

### Tests
- `tests/core/test_security_identity.py` — construction, immutability, equality, hashing, `to_dict()`
- `tests/providers/test_symbol_resolution_identity.py`:
  - US passthrough: `("AAPL", provider="ibkr", mic="XNYS")` → key=`"AAPL"`, method=`"us_passthrough"`
  - MIC suffix: `("AT.", provider="ibkr", mic="XLON")` → key=`"AT.L"`, method=`"mic_suffix"`
  - Pre-resolved (ticker_alias in existing `resolve()` path): verify consistency
  - Futures: `("ES", provider="ibkr", instrument_type="futures")` → key=`"FUT:ES"`
  - Option: `(is_option=True, underlying="AAPL", ...)` → key starts with `"OPT:"`
  - Cash: `("CUR:USD", position_type="cash")` → key=`"CASH:USD"`
  - Fallback: `("MYSTERY", provider="unknown")` → key=`"MYSTERY"`, method=`"unresolved"`
  - Futures with ticker_alias: `("ES", provider="ibkr", instrument_type="futures", ticker_alias="ESUSD")` → key=`"FUT:ES"` (NOT `"ESUSD"`), data_symbol=`"ESUSD"` (alias preserved for price fetching), method=`"futures_spec"`
  - **Consistency**: `resolve_identity(X).data_symbol == resolve(X)` for equity-like inputs
  - **`provider` required for `resolution_method`**: all futures get `security_key="FUT:{root}"`, but `resolution_method="futures_spec"` only when `provider in {"ibkr", "ibkr_flex"}` (matching existing `_resolve_futures()`). Non-IBKR futures get `resolution_method="unresolved"`.
- `tests/core/test_coverage_tracking.py` — add, counts, partial vs full, per-factor coverage, serialization

### Exit Criteria
- All new modules import cleanly
- `SymbolResolver.resolve()` behavior unchanged (existing tests pass)
- `SymbolResolver.resolve_identity()` returns `SecurityIdentity` consistent with `resolve()`
- All 3000+ existing tests pass unchanged

---

## Phase 1: Thread Identity Through Portfolio State

**Goal:** Build `SecurityIdentity` objects during position ingestion and attach to `PortfolioData`. Legacy fields continue to work — this is additive only.

### Design Decision: Where Identity Resolution Happens

`PortfolioData` is constructed via many paths (30+ `from_holdings()` call sites). Wiring identity resolution into every construction path is impractical in one phase.

**Approach: Lazy resolution on `PortfolioData` with eager override from `PositionsData`.**

- `PortfolioData` gets a `security_identities: Optional[Dict[str, SecurityIdentity]]` field (default `None`)
- `get_data_symbol(ticker)` resolves lazily: identity → `ticker_alias_map` → raw ticker
- `PositionsData.to_portfolio_data()` eagerly populates `security_identities` (has richest metadata)
- Other `from_holdings()` callers work unchanged with `security_identities=None`
- Per-position resolution failures produce `resolution_method="unresolved"` identities (visible in coverage tracking), not silent skips

### Cache Coherence

`security_identities` is **excluded from `_generate_cache_key()`**. The reasoning depends on the position source:

- **Plaid & SnapTrade positions:** Provider normalizers call `resolve_ticker_from_exchange()` during ingestion and set `ticker_alias` on each position dict BEFORE `to_portfolio_data()` runs (`plaid_loader.py:112`, `snaptrade_loader.py:981`). This alias populates `ticker_alias_map`. `resolve_identity()` with `ticker_alias` set uses `resolution_method="manual"` and `data_symbol=ticker_alias` — deterministic from `ticker_alias_map`.
- **IBKR live positions:** Do NOT have `ticker_alias` (`ibkr_positions.py:166` — no alias field). They DO have `exchange_mic`. For these, `resolve_identity()` falls through to the MIC-suffix or FMP-search path. The result is NOT captured in `ticker_alias_map`. **This is a gap.** Mitigation: Phase 1 adds a step in `to_portfolio_data()` that, after identity resolution for IBKR positions without `ticker_alias`, backfills `ticker_alias_map[ticker] = identity.data_symbol`. This ensures the cache key reflects the resolved symbol going forward.
- **IBKR Flex positions:** The IBKR Flex normalizer (`normalizers/ibkr_statement.py:299`) does resolve `exchange_mic` → FMP symbol and sets it as `ticker_alias`. So Flex positions behave like Plaid/SnapTrade.
- **DB-cached positions:** `database_client.py` persists `ticker_alias` but not `exchange_mic`. Positions loaded from DB carry `ticker_alias` → deterministic.

With the IBKR-live backfill step, `ticker_alias_map` always captures the resolved symbol, making `security_identities` deterministic from cache key fields.

### Changes

**`portfolio_risk_engine/data_objects.py`:**
- Add field on `PortfolioData` (after `contract_identities` at line ~840):
  ```python
  security_identities: Optional[Dict[str, "SecurityIdentity"]] = None
  ```
- In `to_portfolio_data()` (after line ~717, after instrument_types + contract_identities are built):
  - Instantiate `SymbolResolver()` from `providers/symbol_resolution.py`
  - For each position that has a corresponding `holdings_dict` entry, call `resolver.resolve_identity()` with:
    - `provider=position.get("position_source", "unknown")`
    - `ticker_alias=position.get("ticker_alias") or position.get("fmp_ticker")` (highest priority)
    - `exchange_mic=position.get("exchange_mic")`
    - `currency`, `company_name`, `cusip`, `isin`, `figi`, `is_option`, etc.
  - Per-position try/except: on failure, log at WARNING level with ticker and exception, then produce a fallback identity:
    - `data_symbol` = `ticker_alias` if one was provided for this position (preserves known-good alias), otherwise `ticker.rstrip(".")` (normalized raw ticker)
    - `resolution_method = "unresolved"`
    - This ensures every position gets an identity. Transient resolver failures cannot override a correct `ticker_alias`.
  - **`unresolved` identities are non-authoritative**: they do NOT drive IBKR backfill (skip the `ticker_alias_map` backfill step when `resolution_method == "unresolved"`), and Phase 2 stale-proxy invalidation ignores them (only compares `data_symbol` from identities with `resolution_method != "unresolved"`).
  - **IBKR backfill:** if `ticker_alias` was None but identity resolved to a different `data_symbol`, backfill `ticker_alias_map[ticker] = identity.data_symbol` so cache key reflects the resolution
  - **Cash identity keying:** Cash positions keep their original key (e.g., `CUR:USD`) in `holdings_dict` — existing cash semantics are preserved. The identity is keyed by BOTH the proxy ticker (`SGOV`) AND the original ticker (`CUR:USD`), pointing to the same `SecurityIdentity` object. Identity fields: `instrument_category="cash"`, `source_symbol="CUR:USD"`, `portfolio_symbol="SGOV"`, `data_symbol="SGOV"`, `security_key="CASH:USD"`. This ensures `get_security_identity("SGOV")`, `get_security_identity("CUR:USD")`, and `get_data_symbol("CUR:USD")` all work correctly.
  - Store in `security_identities[holdings_key] = identity`
- Add `security_identities` to `from_holdings()` signature (line ~1177) — optional, default `None`
- Add to `clone()` (line ~896) — deep copy the dict
- **Exclude from `_generate_cache_key()`** (line ~1112) — see Cache Coherence section above
- **Exclude from `to_yaml()`** — reconstructed from position data; YAML/DB round-trips use `get_data_symbol()` fallback
- Add accessor methods:
  - `get_security_identity(ticker) -> Optional[SecurityIdentity]`
  - `get_data_symbol(ticker) -> str` — identity-first, `ticker_alias_map` fallback, raw ticker fallback. Logs at DEBUG level when falling back so legacy code paths are traceable.
- `add_ticker()` (line ~1289): when `security_identities` is not None, attempt to resolve identity for the new ticker

### Tests
- `tests/portfolio_risk_engine/test_security_identity_threading.py`:
  - US equity position → identity with correct method
  - International equity (`AT.`, `exchange_mic="XLON"`) → `security_key="AT.L"`
  - Futures position → `security_key="FUT:ES"`
  - Option position → `security_key` starts with `"OPT:"`
  - Cash position (`CUR:USD` → `SGOV` proxy) → identity keyed by BOTH `SGOV` and `CUR:USD`, `source_symbol="CUR:USD"`, `security_key="CASH:USD"`
  - IBKR position without `ticker_alias` but with `exchange_mic="XLON"` → identity resolved via MIC-suffix, `ticker_alias_map` backfilled
  - Position with `ticker_alias` set → identity uses `resolution_method="manual"`, consistent with `ticker_alias_map`
  - Legacy fields still populated correctly
  - `get_data_symbol()` returns identity's data_symbol when available, falls back to ticker_alias_map
  - Single-position resolution failure → identity with `resolution_method="unresolved"` (not skipped), WARNING logged
  - `from_holdings()` without `security_identities` → `get_data_symbol()` falls back to `ticker_alias_map`, logs at DEBUG
  - `add_ticker()` on portfolio with identities → new ticker gets identity
  - `clone()` preserves identities
  - `_generate_cache_key()` unchanged (does not include `security_identities`)

### Exit Criteria
- `PortfolioData` built from `PositionsData` carries `security_identities`
- `PortfolioData` built from other paths works unchanged with `security_identities=None`
- `get_data_symbol()` works in all cases
- All existing tests pass unchanged

### Files
| Action | Path |
|--------|------|
| MODIFY | `portfolio_risk_engine/data_objects.py` |
| CREATE | `tests/portfolio_risk_engine/test_security_identity_threading.py` |

---

## Phase 2: Migrate Factor Proxy Service to Canonical Keys

**Goal:** Factor proxy generation uses `data_symbol` from `SecurityIdentity` when available, eliminating the divergent resolution in `core/proxy_builder.py:541`.

### Changes

**`core/proxy_builder.py`:**
- Add optional `data_symbol: Optional[str] = None` param to `build_proxy_for_ticker()` (line ~479)
- At line 541 (which calls `utils.ticker_resolver.resolve_ticker_alias()`): if `data_symbol` is provided, skip the internal resolution call
- Thread `data_symbol` to subindustry peer generation so peer lookup uses the same resolved symbol
- `build_proxy_for_ticker()` stores `data_symbol` in the returned proxy dict: `proxies["_data_symbol"] = data_symbol`. This is how the value gets persisted — `ensure_factor_proxies()` passes the dict to `save_factor_proxies()` which writes `_data_symbol` to the new DB column. The `_` prefix follows the existing `_futures_skip` convention for metadata fields.

**`services/factor_proxy_service.py`:**
- Add optional `security_identities` param to `ensure_factor_proxies()` (line ~60)
- In the proxy-building loop (line ~165-181): if `security_identities` has that ticker, pass `data_symbol=identity.data_symbol` to `build_proxy_for_ticker()`
- `get_stock_factor_proxies()` (line ~273): this is a single-ticker convenience function that builds proxies independently. Add optional `data_symbol` param so callers can pass through the resolved symbol.

**All `ensure_factor_proxies()` call sites** (complete inventory):

| File | Lines | Count | Notes |
|------|-------|-------|-------|
| `services/portfolio_service.py` | ~294, ~1199 | 2 | Has `portfolio_data` with identities |
| `services/portfolio/workflow_cache.py` | ~180, ~219 | 2 | Has `portfolio_data` |
| `services/scenario_service.py` | ~256, ~304 | 2 | Has `portfolio_data` |
| `inputs/portfolio_manager.py` | ~188, ~232, ~395 (via `_ensure_factor_proxies` ~675) | 3 | ~395 has only local `ticker_alias_map`/`instrument_types`, no `portfolio_data` — pass `security_identities=None` |
| `app.py` | ~2110, ~2297, ~3583, ~3706, ~3853, ~3955, ~4058, ~5417, ~5536 | 9 | Most build `PortfolioData` via `from_holdings()` — identities=None |
| `routes/hedging.py` | ~90 | 1 | |
| `mcp_tools/risk.py` | ~526, ~537 | 2 | Plus fallback path at ~543 |
| `scripts/run_positions.py` | ~93 | 1 | CLI script, has `portfolio_data` |

**Total: 22 call sites.** All pass `security_identities` when available from `portfolio_data`, or `None` when no `portfolio_data` context exists (e.g., `portfolio_manager.py:395`). When `None`, legacy `ticker_alias_map` resolution is used (existing behavior).

**`get_stock_factor_proxies()` callers** (single-ticker paths, no portfolio context):

| File | Line | Notes |
|------|------|-------|
| `portfolio_risk_engine/stock_analysis.py` | ~195, ~203 | Stock lookup — no portfolio, no identities available |
| `services/stock_service.py` | ~215 | Same |
| `services/agent_building_blocks.py` | ~595 | Builds ad-hoc proxy dict from ticker list |

4 call sites across 3 files. These single-ticker callers do not have `PortfolioData` context, so they use the existing `ticker_alias_map`-based resolution. No change needed — `get_stock_factor_proxies()` with no `data_symbol` param falls back to existing behavior.

**Direct `build_proxy_for_ticker()` callers** (outside `ensure_factor_proxies`):

| File | Line | Notes |
|------|------|-------|
| `services/factor_intelligence_service.py` | ~1501 | Add `data_symbol` param |
| `app.py` direct peer lookups | ~6971, ~7123, ~7417 | Add `data_symbol` param if portfolio_data available |
| `mcp_tools/risk.py` fallback path | ~560 | Fallback when `ensure_factor_proxies` fails. Add `data_symbol` from `ticker_alias_map` |

### Stale Proxy Invalidation

`ensure_factor_proxies()` returns existing cached rows unchanged if they are complete (line ~103). This means already-cached wrong proxy rows (e.g., `AT` resolved to wrong industry because profile fetch used raw ticker) survive Phase 2.

**Approach:** After loading existing cached proxy rows (line ~103), compare each row's `data_symbol` metadata against the resolved symbol. The resolved symbol comes from:
- `security_identities[ticker].data_symbol` when identities are available
- `ticker_alias_map.get(ticker) or ticker_alias_map.get(ticker.rstrip(".")) or ticker.rstrip(".")` as fallback when identities are absent (covers DB-load and `from_holdings()` paths). The `rstrip(".")` matches legacy `resolve_ticker_alias()` normalization (`utils/ticker_resolver.py:119`) to avoid treating dotted symbols as perpetually stale.

If they differ, mark that ticker for rebuild. This is targeted — only rebuilds mismatched rows, not a full cache wipe.

**DB schema change (Phase 2, not deferred):** Add `data_symbol VARCHAR(200)` column to `factor_proxies` table. Update `save_factor_proxies()` and `get_factor_proxies()` in `inputs/database_client.py` to read/write it. New rows store the `data_symbol` used for profile fetch. Existing rows without `data_symbol` are treated as potentially stale (rebuilt on first identity-aware call).

### DB Schema and Persistence

All `factor_proxies` persistence paths must handle `data_symbol`:

**Write paths** (must store `_data_symbol` from proxy dict):
| File | Lines | Path |
|------|-------|------|
| `database/schema.sql` | ~255 | Base table definition — add `data_symbol VARCHAR(200)` column |
| `inputs/database_client.py` | ~3464 | Manual portfolio save (used by `portfolio_repository.py:157`) |
| `inputs/database_client.py` | ~4167 | `save_factor_proxies()` — primary write from `ensure_factor_proxies()` |

**Read paths** (must return `data_symbol` for stale-row comparison):
| File | Lines | Path |
|------|-------|------|
| `inputs/database_client.py` | ~4234 | `get_factor_proxies()` — primary read |
| `inputs/database_client.py` | ~4744 | `list_factor_proxies_for_ticker()` — single-ticker read |

Migration: `database/migrations/add_data_symbol_to_factor_proxies.sql`
- `ALTER TABLE factor_proxies ADD COLUMN IF NOT EXISTS data_symbol VARCHAR(200);`
- Existing rows without `data_symbol` → treated as potentially stale (rebuilt on first identity-aware or alias-aware call)

Full key migration (`security_key` as primary key) deferred to Phase 4.

### Tests
- `tests/services/test_factor_proxy_identity.py`:
  - `build_proxy_for_ticker` with explicit `data_symbol` → skips internal resolution
  - `build_proxy_for_ticker` without `data_symbol` → calls `resolve_ticker_alias()` as before
  - `ensure_factor_proxies` with `security_identities` for `AT.` → proxy builder receives `AT.L`
  - `ensure_factor_proxies` with `security_identities=None` → legacy path unchanged
  - Subindustry peer generation uses resolved `data_symbol`
  - `get_stock_factor_proxies()` with explicit `data_symbol` → uses it
  - `get_stock_factor_proxies()` without → legacy path
  - Stale proxy invalidation: cached proxy built from raw `AT` → identity resolves to `AT.L` → proxy rebuilt with correct profile
  - Stale proxy fallback with dotted symbol: `AT.` in `ticker_alias_map` as `AT.` key → fallback strips dot, finds alias → no false stale detection
  - End-to-end: `AT.`/`AT`/`AT.L` all produce the same proxy result

### Exit Criteria
- Factor proxy generation uses canonical `data_symbol` from identity when available
- All 22 `ensure_factor_proxies` call sites pass `security_identities` through (or `None`)
- Stale proxy rows with mismatched `data_symbol` are rebuilt (uses `ticker_alias_map` fallback when identities absent)
- Single-ticker paths (`get_stock_factor_proxies`, `stock_analysis.py`) work unchanged
- Legacy path (identities=None) identical to current behavior
- All existing tests pass

### Files
| Action | Path |
|--------|------|
| MODIFY | `core/proxy_builder.py` |
| MODIFY | `services/factor_proxy_service.py` |
| MODIFY | `services/portfolio_service.py` |
| MODIFY | `services/portfolio/workflow_cache.py` |
| MODIFY | `services/scenario_service.py` |
| MODIFY | `inputs/portfolio_manager.py` |
| MODIFY | `services/factor_intelligence_service.py` |
| MODIFY | `app.py` (9 `ensure_factor_proxies` sites + 3 direct peer lookup sites) |
| MODIFY | `routes/hedging.py` |
| MODIFY | `mcp_tools/risk.py` (2 `ensure_factor_proxies` sites + 1 direct `build_proxy_for_ticker` fallback) |
| MODIFY | `scripts/run_positions.py` |
| MODIFY | `inputs/database_client.py` (save/get factor_proxies — add `data_symbol` read/write) |
| MODIFY | `database/schema.sql` (add `data_symbol` column to `factor_proxies` table) |
| CREATE | `database/migrations/add_data_symbol_to_factor_proxies.sql` |
| CREATE | `tests/services/test_factor_proxy_identity.py` |

---

## Phase 3: Fix Output Semantics (Coverage Tracking)

**Goal:** Risk outputs distinguish "not modeled" from "true zero beta" with per-factor granularity, wired through the actual result construction path.

### Design: Two-Stage Coverage Without Breaking Return Types

Coverage is populated at two pipeline stages. **Critical constraint:** `get_returns_dataframe()` returns `pd.DataFrame` and has 10+ callers — its return type must NOT change.

**Approach: Build coverage as a side-channel, not a return-type change.**

1. **Returns stage:** `build_portfolio_view()` (line ~1849) already calls `get_returns_dataframe()`. After the call returns, `build_portfolio_view()` compares the DataFrame columns against the input tickers to identify which tickers were dropped for insufficient history. This is a **post-hoc comparison** — no change to `get_returns_dataframe()` signature or return type.

2. **Factor stage:** `compute_factor_exposures()` (line ~1502) receives `stock_factor_proxies` and optionally `security_identities`. As it processes each ticker, it records:
   - Missing from `stock_factor_proxies` → `EXCLUDED_NO_PROXY`
   - Present but with `_futures_skip=True` → `PARTIALLY_MODELED` (market/momentum/value modeled, industry/subindustry not)
   - Identity has `resolution_method="unresolved"` → `UNRESOLVED_IDENTITY` (new status). The position may still produce valid betas if raw-symbol proxying happens to work, but the identity resolution itself failed — this is a signal to investigate, not a guarantee of bad data.
   - Successfully modeled across all factors with resolved identity → `FULLY_MODELED`

`build_portfolio_view()` creates the `PortfolioCoverage`, populates it from both stages, and includes it in the `portfolio_summary` dict it returns.

### Changes

**`portfolio_risk_engine/portfolio_risk.py`:**
- In `build_portfolio_view()` / `_build_portfolio_view_computation()` (line ~1906):
  - After `get_returns_dataframe()` returns, compare DataFrame columns vs input ticker set → identify returns-stage exclusions
  - Create `PortfolioCoverage`, add returns-stage exclusions as `EXCLUDED_NO_HISTORY`
  - Pass `coverage` to `compute_factor_exposures()` as optional param
- In `compute_factor_exposures()` (line ~1502): accept optional `coverage: PortfolioCoverage`, augment with factor-stage status per ticker
- Keep `fillna(0.0)` for aggregation math — internal only
- Include `coverage` in the dict returned by `build_portfolio_view()`

**`core/result_objects/risk.py`:**
- Add `coverage: Optional[PortfolioCoverage] = None` field on `RiskAnalysisResult`
- Populate in `from_core_analysis()` (line ~1781) from `portfolio_summary.get("coverage")`
- Include in `to_api_response()` and `get_agent_snapshot()`

### Tests
- `tests/core/test_coverage_integration.py`:
  - 3 tickers, 1 missing proxy → 2 modeled + 1 excluded_no_proxy
  - 3 tickers, 1 with insufficient history → returns-stage exclusion with `excluded_at="returns"`
  - Futures ticker → `PARTIALLY_MODELED` with per-factor flags (market=True, industry=False)
  - Cash ticker → `EXCLUDED_CASH`
  - `get_returns_dataframe()` return type unchanged (bare `pd.DataFrame`)
  - `RiskAnalysisResult.from_core_analysis()` includes coverage from `portfolio_summary`
  - `to_api_response()` and `get_agent_snapshot()` include coverage dict
  - Position with `resolution_method="unresolved"` that happens to produce valid betas → `UNRESOLVED_IDENTITY` status (not `FULLY_MODELED`)
  - Filled betas still 0.0 for math; coverage metadata distinguishes them

### Exit Criteria
- Every risk analysis run produces `PortfolioCoverage` via `build_portfolio_view()`
- `get_returns_dataframe()` signature and return type unchanged — no callers broken
- Coverage flows through `portfolio_summary` → `from_core_analysis()`
- Per-factor granularity distinguishes partial modeling (futures) from full exclusion
- All existing tests pass

### Files
| Action | Path |
|--------|------|
| MODIFY | `portfolio_risk_engine/portfolio_risk.py` |
| MODIFY | `core/result_objects/risk.py` |
| CREATE | `tests/core/test_coverage_integration.py` |

---

## Phase 4: Migrate Caches and Backfill (Future)

- Add `security_key` column to `factor_proxies` and `security_types` DB tables
- Update `SecurityTypeService` to use identity when available
- Backfill script: `scripts/backfill_security_keys.py`
- Uniqueness constraint migration

## Phase 5: Remove Legacy Symbol-Based Joins (Future)

- Remove `ticker_alias_map` from `PortfolioData`
- Consolidate remaining resolution locations into `SymbolResolver.resolve_identity()`
- Drop legacy DB constraints

---

## Dependency Graph

```
Phase 0 (Contract — no behavior change)
    ↓
Phase 1 (Thread identity through PortfolioData)
    ↓
Phase 2 (Factor proxy gen uses identity)
    ↓
 ┌──┴──┐
 P3    P4  (parallel after P2)
 ↓
 P5 (deferred)
```

## Risk Mitigation

1. **Loud failures, not silent degradation:** Per-position resolution failures produce `resolution_method="unresolved"` identities with `UNRESOLVED_IDENTITY` status in Phase 3 coverage tracking — not silent skips. Unresolved identities are non-authoritative: they preserve known `ticker_alias` as `data_symbol`, skip IBKR backfill, and are ignored by stale-proxy invalidation. `get_data_symbol()` logs at DEBUG when falling back to `ticker_alias_map`, making legacy code paths traceable. `security_identities=None` on non-PositionsData paths is the expected state for Phase 1 — not a degradation.
2. **No duplicate resolver:** Extends existing `providers/symbol_resolution.py:SymbolResolver` with `resolve_identity()`. Signature preserves `provider` and `instrument_type` params. `resolve()` is unchanged. `resolve_identity().data_symbol == resolve()` for identical inputs.
3. **Cache coherence:** `security_identities` excluded from cache key. For Plaid/SnapTrade/IBKR Flex: `ticker_alias` pre-resolved by normalizers, captured in `ticker_alias_map` (already in cache key). For IBKR live positions (no `ticker_alias`): Phase 1 backfills `ticker_alias_map` from resolved identity, so cache key reflects the resolution.
4. **`get_returns_dataframe()` unchanged:** Coverage for returns-stage exclusions is built post-hoc in `build_portfolio_view()` by comparing DataFrame columns vs input tickers. No return-type change, no caller breakage.
5. **Two-stage coverage:** Returns-stage + factor-stage. Per-factor flags for partial modeling.
6. **Correct result wiring:** Coverage flows through `build_portfolio_view()` → `portfolio_summary` → `from_core_analysis()`.
7. **Complete call-site inventory:** 22 `ensure_factor_proxies` sites, 4 `get_stock_factor_proxies` call sites (3 files), 5 direct `build_proxy_for_ticker` sites — all accounted for.
8. **Stale proxy invalidation:** Phase 2 compares cached proxy `data_symbol` against resolved symbol (from identity or `ticker_alias_map` fallback) and rebuilds mismatched rows. Works for both identity-aware and identity-absent paths. Not a full cache wipe — targeted rebuild only. DB schema: `data_symbol` column added to `factor_proxies` table in Phase 2.

## Codex Review Findings Addressed

### Round 1 (v1 → v2)
| # | Finding | Resolution |
|---|---------|------------|
| 1 | Phase 1 misses 30+ construction paths | Lazy `get_data_symbol()` fallback; only `to_portfolio_data()` populates eagerly |
| 2 | Phase 2 call-site coverage incomplete | Complete 21-site inventory |
| 3 | Coverage model too late and too coarse | Two-stage, per-factor coverage |
| 4 | Phase 3 wired to `from_portfolio_analysis()` (doesn't exist) | Wired to `from_core_analysis()` via `build_portfolio_view()` |
| 5 | Duplicate resolver | Extends existing `SymbolResolver` |
| 6 | Cache coherence undefined | Explicit exclusion with determinism argument |

### Round 2 (v2 → v3)
| # | Finding | Resolution |
|---|---------|------------|
| 1 | Cache coherence: `provider`, `company_name`, `exchange_mic` not in cache key | `ticker_alias_map` captures the resolved result from provider normalization; `security_identities` adds metadata only. Explicit reasoning added. |
| 2 | `resolve_identity()` missing `provider`, conflates `position_type`/`instrument_type` | Signature now preserves `provider` and `instrument_type` from `resolve()`. Adds `position_type` as separate param for cash detection only. Implementation delegates to `self.resolve()`. |
| 3 | Phase 2 still missing call sites | Added `mcp_tools/risk.py:526,537` + fallback ~543, `get_stock_factor_proxies()` callers (stock_analysis, stock_service, agent_building_blocks), direct peer lookups in app.py. |
| 4 | `get_returns_dataframe()` return type change breaks callers | Coverage built post-hoc in `build_portfolio_view()` by comparing DataFrame columns vs input tickers. `get_returns_dataframe()` signature unchanged. |

### Round 3 (v3 → v4)
| # | Finding | Resolution |
|---|---------|------------|
| 1 | Cache coherence still not proven — IBKR live positions lack `ticker_alias`, resolution depends on `exchange_mic` not in cache key | Added `ticker_alias` param to `resolve_identity()`. IBKR live positions resolved via MIC-suffix, then `ticker_alias_map` backfilled so cache key reflects resolution. Per-source analysis documented. |
| 2 | Phase 2 doesn't fix already-cached bad proxy rows | Added targeted stale proxy invalidation: compare cached `data_symbol` against identity `data_symbol`, rebuild mismatched rows. `data_symbol` metadata column added in Phase 2. |
| 3 | Inventory still incomplete: `scripts/run_positions.py:93`, `app.py:7417` | Added to inventory. Total: 22 `ensure_factor_proxies` + 4 `get_stock_factor_proxies` (3 files) + 5 direct `build_proxy_for_ticker`. `portfolio_manager.py:395` documented as having no `portfolio_data` (passes `None`). |
| 4 | Cash identity keying: proxy remapping changes key before identity loop | Identity keyed by BOTH proxy ticker AND original ticker (same object). `holdings_dict` keys unchanged. Source symbol preserved in `source_symbol` field. |

### Round 4 (v4 revisions)
| # | Finding | Resolution |
|---|---------|------------|
| 1 | Stale proxy invalidation misses alias-only portfolio loads; missing DB persistence for `data_symbol` | Added all factor_proxies write paths: `schema.sql`, `database_client.py` (~3464, ~4167). Read paths: ~4234, ~4744. Migration SQL included. |
| 2 | `resolution_method` decision order: `fmp_search` check before `futures` makes `futures_spec` unreachable | Reordered: `instrument_type == "futures"` checked FIRST, before `data_symbol != base_symbol`. |
| 3 | Inventory says "3 get_stock_factor_proxies sites" but there are 4 call sites in 3 files | Corrected to "4 call sites across 3 files". |

### Round 5 (v4 continued)
| # | Finding | Resolution |
|---|---------|------------|
| 1 | `data_symbol` never attached to proxy dict — DB writers have nothing to persist | `build_proxy_for_ticker()` stores `proxies["_data_symbol"] = data_symbol` in returned dict (follows `_futures_skip` convention). `save_factor_proxies()` writes it to DB column. |
| 2 | `futures_spec` should be gated on `provider in {"ibkr", "ibkr_flex"}` to match existing resolver | All futures get `security_key="FUT:{root}"`. Provider gate only applies to `resolution_method`: `"futures_spec"` for IBKR, `"unresolved"` for others. |
| 3 | Read vs write paths mislabeled in persistence table | Split into separate write (3 paths) and read (2 paths) tables with correct labels. |

### Round 6 (v4 continued)
| # | Finding | Resolution |
|---|---------|------------|
| 1 | Alias-first `resolve_identity()` conflicts with constructed keys for non-equities (futures with `ticker_alias="ESUSD"` → wrong key) | Non-equity types (cash, futures, options) checked BEFORE alias branch. Futures always get `FUT:{root}` key regardless of `ticker_alias`. `ticker_alias` only used as `data_symbol`/`security_key` for equity-like types. Test added for `instrument_type="futures", ticker_alias="ESUSD"`. |
| 2 | Verification references nonexistent `scripts/run_risk_cli.py` | Changed to `scripts/run_positions.py`. |

### Round 7 (v4 continued)
| # | Finding | Resolution |
|---|---------|------------|
| 1 | Futures `data_symbol` should still use `ticker_alias` for price fetching, not just `resolve()` | Futures: `security_key = "FUT:{root}"` always, `data_symbol = ticker_alias or self.resolve()`. Preserves existing price-service and portfolio-risk usage. Test updated. |
| 2 | Smoke test command not runnable — needs `--user-email` and `--to-risk` flags | Fixed to `python scripts/run_positions.py --user-email <email> --to-risk`. |

## Verification

After each phase:
1. Run full test suite: `pytest tests/ -x --timeout=60`
2. Smoke test with real portfolio: `python scripts/run_positions.py --user-email <email> --to-risk` — verify factor betas for international equities are non-zero
3. Phase 3+: check API response includes `coverage` field with per-factor granularity; verify no `UNRESOLVED_IDENTITY` statuses for known portfolio securities; verify AT-class securities show `FULLY_MODELED` (not `EXCLUDED_NO_PROXY`)
