# Security Identifier Capture & Currency Classification Plan

## Context

Two related data quality gaps:

1. **Bond/Treasury pricing fails** — Plaid sends bond positions with description strings as tickers (e.g., `"US Treasury Note - 4.25% 15/10/2025 USD 100"`). No pricing source can resolve this → $0 NAV. The IBKR bond pricing infrastructure exists (`resolve_bond_contract()` → `fetch_ibkr_bond_monthly_close()`) but requires a `con_id`. Investigation shows **Plaid provides CUSIP and ISIN** (nullable) on the Security object, **Schwab provides CUSIP** on the Instrument object, and **SnapTrade provides FIGI** — but we capture none of these. These fields are nullable and may be absent for some securities, but when present they unlock standard identifier resolution.

2. **CUR:XXX currency positions** — Brokerage imports include `CUR:CAD`, `CUR:HKD`, etc. The `to_portfolio_data()` path correctly converts these to cash proxy ETFs (SGOV, etc.) via `cash_map.yaml`. But if a CUR: ticker reaches `SecurityTypeService` through any other path, it falls through to FMP lookup → fails → defaults to "equity" (wrong). Need explicit CUR: → cash classification.

**Package boundary constraint**: `brokerage/`, `ibkr/`, `providers/` are self-contained packages. No cross-package imports. Identifier fields flow as data through existing normalization contracts, not as package dependencies.

## Phase 1: Capture Security Identifiers from Provider APIs

**Goal**: Pass through CUSIP, ISIN, FIGI, and `is_cash_equivalent` from broker APIs into position data.

### 1a. Plaid — capture `cusip`, `isin`, `is_cash_equivalent`

**File: `trading_analysis/models.py`** (lines 90–114)

Add fields to `PlaidSecurity` dataclass after `market_identifier_code` (line 94):
- `cusip: Optional[str] = None`
- `isin: Optional[str] = None`
- `is_cash_equivalent: Optional[bool] = None`

Update `from_dict()` (lines 103–114) to extract these fields.

**File: `plaid_loader.py`** (lines 123–135)

In `normalize_plaid_holdings()`, the security dict `s` comes from the raw Plaid API response (line 92: `s = sec_map.get(h["security_id"], {})`). Add to the row dict at lines 123–135:
```python
"cusip": s.get("cusip"),
"isin": s.get("isin"),
"is_cash_equivalent": s.get("is_cash_equivalent"),
```

### 1b. Schwab — capture `cusip`

**File: `providers/schwab_positions.py`** (lines 129–143)

The `instrument` dict (line 120: `instrument = position.get("instrument") or {}`) from Schwab API contains `cusip`. Add to the position row dict:
```python
"cusip": instrument.get("cusip"),
```

### 1c. SnapTrade — capture `figi_code`

**File: `snaptrade_loader.py`** (lines 920, 970–986)

`inner_symbol` (line 920) from SnapTrade API has `figi_code`. Add to `position_data` dict at line 970:
```python
"figi": inner_symbol.get("figi_code"),
```

### 1d. Thread identifiers through PositionService

**File: `services/position_service.py`**

**`_normalize_columns()`** (~line 382–412): Add optional column defaults following the same pattern as `fmp_ticker` (line 393):
```python
for col in ["cusip", "isin", "figi", "is_cash_equivalent"]:
    if col not in df.columns:
        df[col] = None
```

**`_consolidate_cross_provider()`** (~line 414–522): The consolidation groupby drops columns not in the `agg_dict`. Add identifier columns to both cash and non-cash aggregation dicts using `"first"` aggregation (identifiers are per-ticker, not summable):
```python
# Add to both cash agg_dict (line 457) and non-cash agg_dict (line 500):
"cusip": "first",
"isin": "first",
"figi": "first",
"is_cash_equivalent": lambda x: any(v is True for v in x),  # True if ANY position is cash-equivalent
```

Also ensure these columns exist before groupby (same pattern as `fmp_ticker` at line 452/482):
```python
for col in ["cusip", "isin", "figi", "is_cash_equivalent"]:
    if col not in positions.columns:
        positions[col] = None
```

### 1e. Thread into PortfolioData

**File: `portfolio_risk_engine/data_objects.py`** (NOT `core/data_objects.py` — that file is a shim that re-exports from `portfolio_risk_engine/data_objects.py`)

Add a new optional field to `PortfolioData` dataclass (~line 698, after `instrument_types`):
```python
security_identifiers: Optional[Dict[str, Dict[str, str]]] = None
# e.g., {"AAPL": {"cusip": "037833100"}, "BOND_POS": {"cusip": "912810...", "isin": "US912810..."}}
```

In `PositionsData.to_portfolio_data()` (~line 439–617), build `security_identifiers` dict alongside `fmp_ticker_map`. In the position loop (~line 475), extract identifiers:
```python
# Collect security identifiers (cusip, isin, figi) when available
cusip = position.get("cusip")
isin = position.get("isin")
figi = position.get("figi")
ids = {}
if cusip: ids["cusip"] = cusip
if isin: ids["isin"] = isin
if figi: ids["figi"] = figi
if ids:
    security_identifiers[ticker] = ids
```

Pass to `PortfolioData.from_holdings()` at line 608. Requires adding `security_identifiers` parameter to `from_holdings()` as well.

### 1f. Database position cache (optional columns)

**File: `inputs/database_client.py`**

The DB position save/load paths (`save_positions_from_dataframe()` ~line 1640, position read queries) do not include identifier columns. Two options:

**Option A (recommended)**: Add `cusip`, `isin`, `figi` as nullable columns to the positions table via migration. Include in save/load queries.

**Option B (simpler, deferred)**: Accept that identifiers are only available on fresh fetches, not cached reads. The `to_portfolio_data()` path handles None gracefully. Document this limitation.

Recommend Option B for Phase 1 — identifiers are most useful for bonds (rare, low count), and live fetches are the primary path where we need them. DB persistence can come later.

## Phase 2: CUR:XXX Detection in SecurityTypeService

**Goal**: Explicit cash classification for CUR: tickers so they're never misclassified.

### 2a. Add CUR: detection in `get_security_types()`

**File: `services/security_type_service.py`** (after line 259)

After the existing cash preservation block (lines 252–259), add:
```python
# CUR:XXX tickers are currency positions → classify as cash
# (Defensive — normally converted to proxy ETFs in to_portfolio_data())
for ticker in tickers:
    if ticker not in security_types and str(ticker or "").startswith("CUR:"):
        security_types[ticker] = "cash"
```

### 2b. Add CUR: detection in `get_asset_classes()`

**File: `services/security_type_service.py`** (after line 817)

After Tier 1 cash proxy detection, before Tier 2 DB cache:
```python
# CUR:XXX tickers → cash asset class (parallel to Tier 1 proxy detection)
for ticker in tickers:
    if ticker not in asset_classes and str(ticker or "").startswith("CUR:"):
        asset_classes[ticker] = "cash"
```

### 2c. Use `is_cash_equivalent` from provider data

**Note**: `PortfolioData.standardized_input` only carries `shares`/`dollars`/`weight`/`type`/`currency` — it does NOT carry `is_cash_equivalent`. The `is_cash_equivalent` field lives on the raw position dicts in `PositionsData.positions`, not in `PortfolioData`.

Two integration options:

**Option A (recommended)**: Use `is_cash_equivalent` in `to_portfolio_data()` alongside the existing `is_cash` check (line 494):
```python
is_cash = (position_type == "cash"
           or ticker.startswith("CUR:")
           or position.get("is_cash_equivalent") is True)
```
This is the right place — it's where cash detection already happens, before SecurityTypeService is ever called.

**Option B**: Thread `is_cash_equivalent` into `PortfolioData` as a separate dict and consume in SecurityTypeService. Over-engineering for this use case — Option A is simpler.

## Phase 3: Bond Identity Foundation (Wire Through Only)

**Goal**: With CUSIP/ISIN now available in `PortfolioData.security_identifiers`, make them accessible to the pricing layer for bond positions. No CUSIP → con_id resolver built yet — that's a separate future step.

**Important**: `holdings_dict` metadata (beyond shares/dollars/weight/currency/type) does NOT flow through `PortfolioData.standardized_input` to the pricing layer. The pricing layer in `get_returns_dataframe()` and `realized_performance_analysis.py` uses `instrument_types` and per-ticker `contract_identity` dicts that are threaded separately.

### 3a. Store identifiers in `security_identifiers` field

The `security_identifiers` field added in Phase 1e already carries CUSIP/ISIN/FIGI per ticker on `PortfolioData`. This is sufficient — downstream code that needs bond identifiers can access `portfolio_data.security_identifiers.get(ticker)`.

No need to put `contract_identity` into `holdings_dict` — that path gets dropped during standardization anyway.

### 3b. Log bond identifier availability

In `to_portfolio_data()`, when processing bond positions, log what identifiers are available:
```python
if position_type == "bond":
    ids = security_identifiers.get(ticker, {})
    if ids:
        logger.info("Bond %s: identifiers=%s", ticker, list(ids.keys()))
    else:
        logger.warning("Bond %s: no standard identifiers (CUSIP/ISIN/FIGI) available", ticker)
```

### 3c. Future: pricing layer integration

When a CUSIP → IBKR con_id resolver is built, it would consume `portfolio_data.security_identifiers` in the realized performance analysis layer (`_fetch_price_from_chain()`) or in `IBKRPriceProvider.fetch_monthly_close()`. This is out of scope for this plan.

## Verification

### Phase 1:
- `pytest tests/` — full test suite passes
- Manually verify: Plaid positions DataFrame includes `cusip`/`isin` columns
- Manually verify: Schwab positions DataFrame includes `cusip` column
- Manually verify: SnapTrade positions DataFrame includes `figi` column
- Confirm `PortfolioData.security_identifiers` populated for a live portfolio

### Phase 2:
- Unit test: `SecurityTypeService.get_security_types(["CUR:CAD", "AAPL"])` → `{"CUR:CAD": "cash", ...}`
- Unit test: `SecurityTypeService.get_asset_classes(["CUR:USD", "CUR:HKD"])` → both "cash"
- Confirm no FMP API calls made for CUR: tickers (check logs)

### Phase 3:
- For a portfolio with a bond position from Plaid, confirm `portfolio_data.security_identifiers` contains the bond's CUSIP/ISIN
- Confirm bond identifier logging appears in `to_portfolio_data()` output

## Key Files

| File | Change | Phase |
|------|--------|-------|
| `trading_analysis/models.py` (line 90) | Add `cusip`, `isin`, `is_cash_equivalent` to PlaidSecurity | 1a |
| `plaid_loader.py` (line 123) | Extract cusip, isin, is_cash_equivalent from security dict | 1a |
| `providers/schwab_positions.py` (line 129) | Extract cusip from instrument dict | 1b |
| `snaptrade_loader.py` (line 970) | Extract figi_code from inner_symbol | 1c |
| `services/position_service.py` (~line 382, 414) | Column defaults + consolidation preservation | 1d |
| `portfolio_risk_engine/data_objects.py` (~line 698, 439) | Add `security_identifiers` to PortfolioData; populate in to_portfolio_data() | 1e, 3a, 3b |
| `services/security_type_service.py` (lines 259, 817) | CUR: detection in get_security_types() and get_asset_classes() | 2a, 2b |

## Scope Notes

**Bypass routes not covered**: There are code paths that load positions without going through `PositionService` (e.g., `plaid_loader.py` line 803, `snaptrade_loader.py` line 1276, `routes/provider_routing.py` line 420). These are legacy or admin paths. Since they call the same underlying loader functions (which we're modifying in 1a–1c), the identifier columns will be present in the DataFrames, but they won't be consumed by those paths. This is acceptable — identifiers are only consumed by `to_portfolio_data()` which runs through `PositionService`.

**DB cache**: Identifier columns are NOT persisted to the positions DB cache in Phase 1. They are only available on live fetches. This is acceptable for now — bonds are rare, and live fetch is the path where we need identifiers. DB persistence can be added later.

## Design Decisions

1. **Identifiers as optional pass-through data** — No validation, no required fields. If a provider doesn't give CUSIP, the field is None. Downstream consumers check presence before use.
2. **`security_identifiers` as a separate PortfolioData field** — Parallel to `currency_map`, `instrument_types`, `fmp_ticker_map`. Doesn't pollute `standardized_input` (which only carries shares/dollars/weight/type/currency).
3. **CUR: detection is defensive, not primary** — The main CUR: → proxy conversion stays in `to_portfolio_data()`. SecurityTypeService detection catches edge cases only.
4. **`is_cash_equivalent` consumed in `to_portfolio_data()`** — NOT in SecurityTypeService. This is where cash detection already happens (line 494), and `standardized_input` doesn't carry this field.
5. **No package boundary violations** — All identifier data flows as dict fields through existing normalization contracts. `brokerage/`, `ibkr/`, `providers/` packages unchanged.
6. **Bond con_id resolution deferred** — Phase 3 only stores identifiers on `PortfolioData.security_identifiers`. Actual CUSIP → IBKR con_id mapping is a separate future task.
7. **Phase 3 is optional** — Phases 1–2 are self-contained and valuable independently.

## Live Test Results (2026-02-26)

All 3 phases implemented and verified against live brokerage data (1794 tests passing).

**Identifier capture (fresh fetch):**
- **Plaid (Merrill)**: Fields present in API response but institution returns `cusip=None`, `isin=None` for all securities. `is_cash_equivalent` works (4 values, all `False`). Data completeness is institution-dependent.
- **SnapTrade (IBKR)**: **11 of 17 positions have FIGI** (6 without are CUR: cash positions). Example: `AT.L → BBG013F3CG73`, `NVDA → BBG000BBK0R0`.
- **Schwab**: **16 of 17 positions have CUSIP** (1 without is `USD:CASH`). Example: `STWD → 85571B105`, `ENB → 29250N105`.

**`PortfolioData.security_identifiers`** populated with 23 entries (11 FIGI + 12 CUSIP) on live portfolio.

**CUR: classification**: `SecurityTypeService.get_security_types(["CUR:CAD", "CUR:HKD"])` → `{"CUR:CAD": "cash", "CUR:HKD": "cash"}`. No FMP/DB lookups triggered.

**CUR: → proxy conversion**: All 7 CUR: tickers (USD, MXN, JPY, GBP, HKD, CAD from SnapTrade + USD from Plaid) converted to SGOV in `to_portfolio_data()`. Zero CUR: tickers in `standardized_input`.
