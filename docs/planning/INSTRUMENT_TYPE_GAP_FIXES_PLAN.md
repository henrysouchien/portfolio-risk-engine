# Instrument Type Routing Gap Fixes — Implementation Plan

> **Date**: 2026-03-22
> **Status**: IMPLEMENTED (`849f4d8d`)
> **Audit**: `docs/planning/INSTRUMENT_TYPE_ROUTING_AUDIT.md` (Codex-reviewed PASS)
> **TODO ref**: `docs/TODO.md` line 87

## Context

The instrument type routing audit identified 8 gaps in how instrument types route through pricing, risk analysis, and normalization. These are all small fixes (mostly S-sized) with no dependencies between them. Pure correctness improvements — no new features.

---

## Step 1: CEF Classification — Verified Correct, No Change Needed

**Status**: DROPPED — not a real gap.

The "disagreement" is intentional by design. The system uses **two separate classification systems**:

1. **`security_type`** (SecurityTypeService) → drives risk scoring. CEFs get `"fund"` / `"mutual_fund"` → **40% crash scenario**. Correct.
2. **`instrument_type`** (normalizers) → drives trading analysis. CEFs get `"equity"` → **timing analysis included** (exchange-traded, intraday pricing). Correct.

SnapTrade maps `cef` → `equity` (correct). Plaid's DSU fixture has `type: "equity"` — already classifies correctly. The existing test `test_infer_position_instrument_type_keeps_cef_as_equity()` explicitly verifies this distinction. Comment in `_helpers.py:147`: *"SnapTrade uses security_type='mutual_fund' for CEFs too; keep them exchange-traded here."*

Changing CEF `instrument_type` to `mutual_fund` would break timing analysis for exchange-traded CEFs. The risk system already handles crash scenarios correctly via `security_type`, which is independent.

**No code changes.**

---

## Step 2: Bond Pricing Filter Fix + Warning Flag

**Files**: `providers/price_service.py`, `core/position_flags.py`

Bonds pass through `filter_price_eligible()` but FMP has no bond pricing data — they hit the QuoteProvider and get empty results. Should be excluded from FMP batch pricing (IBKR handles bonds separately via contract_identity).

**Fix 1** — `providers/price_service.py` line 116: Add `"bond"` to the exclusion set:
```python
if instrument_type in {"futures", "option", "derivative", "bond"}:
    continue
```

**Fix 2** — `core/position_flags.py`: Add a warning flag for bond instrument type. Note: `generate_position_flags()` does not currently receive price-availability or unpriceable metadata, so the flag should be based purely on `instrument_type == "bond"` (static check), not on runtime pricing failure. Flag text: "Bond positions use IBKR pricing — historical analysis may be limited without IBKR connection."

**Note**: When `instrument_types` dict is `None`, `filter_price_eligible()` returns all tickers (line 100 early return). The bond exclusion only takes effect when instrument_types is populated. This is acceptable — the filter is defensive, not the primary routing path.

**Verify**: `pytest tests/ -k "price_service or position_flags" -v`

---

## Step 3: Legacy Price Loaders — Thread instrument_type

**Files**: `portfolio_risk_engine/data_loader.py`, `portfolio_risk_engine/providers.py`, `portfolio_risk_engine/portfolio_config.py`, `portfolio_risk_engine/portfolio_risk.py`

Three call sites pass ticker to price loaders without `instrument_type`, causing the legacy adapter (`providers.py:58`) to default to `equity`. Both `instrument_types` and `contract_identities` dicts are available in scope at all call sites.

**This is more complex than a call-site-only patch.** The actual functions being called are in `data_loader.py` (`fetch_monthly_close` at line 146, `fetch_monthly_total_return_price` at line 180), which do NOT accept `instrument_type` or `contract_identity` params. These must be threaded through:

**Fix 1** — `portfolio_risk_engine/data_loader.py`: Add `instrument_type` and `contract_identity` as optional kwargs to `fetch_monthly_close()` (line 146) and `fetch_monthly_total_return_price()` (line 180). Pass them through to the underlying `_RegistryBackedPriceProvider` calls.

**Fix 2** — `portfolio_risk_engine/providers.py` line 58: Already has `kw.get("instrument_type", "equity")` — this is the adapter that will receive the threaded kwarg.

**Fix 3** — Call sites (3 total):
- `portfolio_risk_engine/portfolio_config.py` line 303 (has `instrument_types` at line 263, `contract_identities` at line 264)
- `portfolio_risk_engine/portfolio_risk.py` line 718 (has `instrument_types` at line 689, `contract_identities` at line 691)
- `portfolio_risk_engine/portfolio_risk.py` line 628 (additional missed passthrough)

Pass `instrument_type=instrument_types.get(ticker, "equity")` and `contract_identity=contract_identities.get(ticker)` at each call site.

**Note**: The total-return path (`providers.py:91`) always prefers the dividend provider (FMP), so `instrument_type="bond"` would still route to FMP for dividend data. This is acceptable — bonds won't have FMP dividend data, so the fallback to `fetch_monthly_close` will activate.

**Verify**: `pytest tests/ -k "portfolio_risk or portfolio_config or data_loader" -v`

---

## Step 4: Plaid ISIN Bond Resolution

**Files**: `ibkr/contracts.py`

Plaid emits bond `contract_identity` with `isin` field (line 192), but IBKR's `resolve_bond_contract()` only tries `con_id` and `cusip` (line 129). Add ISIN fallback.

**Fix** — `ibkr/contracts.py` after the CUSIP check block (~line 150): Add ISIN fallback:
```python
isin = identity.get("isin")
if isinstance(isin, str) and isin.strip():
    bond = Bond()
    bond.secIdType = "ISIN"
    bond.secId = isin.strip()
    bond.currency = str(identity.get("currency") or "USD").upper()
    return bond
```

**Note**: This is IBKR-specific — only works when IBKR Gateway is connected. `ib_async.Bond` does support `secIdType`/`secId` kwargs (verified). However, other code paths also check for bond identity and only accept `con_id`/`cusip`: `trading_analysis/analyzer.py:1158`, `core/realized_performance/engine.py:1254`, `ibkr/market_data.py:160` (CUSIP-only qualification). These secondary sites should be updated to also check `isin` for completeness, or at minimum not fail when ISIN is the only identifier.

**Verify**: `pytest tests/ -k "bond or contracts" -v`

---

## Step 5: "unknown" Consistent Treatment — Phased Approach

**Risk**: Unknown positions come from normalizer failures on unclassifiable Plaid securities. Some may be options, futures, or exotic derivatives. A blanket remap to equity could inflate equity segment weight, cause proxy builder failures on non-equity tickers, and distort realized returns via incorrect cash replay.

### Phase 5a: Warning Flag + Telemetry (ship now)

**Files**: `core/position_flags.py`, `core/realized_performance/engine.py`

Add visibility into unknown positions WITHOUT changing their treatment:

**Fix 1** — `core/position_flags.py`: Add warning flag when positions have `unknown` instrument type. Flag text: "Position {symbol} has unrecognized instrument type and is excluded from analysis. Verify classification in your brokerage." Severity: `warning`.

**Fix 2** — `core/realized_performance/engine.py` line 273: Add a logged warning when excluding unknown positions (currently silent). Use `portfolio_logger.warning(f"Excluding {symbol}: unknown instrument_type")` so we get visibility in logs.

No behavior change — unknown positions stay excluded. Users and logs now surface what's being dropped.

**Verify**: `pytest tests/ -k "position_flags or realized_performance" -v`

### Phase 5b: Audit Unknown Positions (investigation, before remap)

**Action**: Query production data to understand what's actually "unknown":
- How many unknown positions exist?
- Which brokers/normalizers produce them?
- What are the actual security types from the source (Plaid `type` field, SnapTrade `security_type`)?
- Can they be manually classified (options, derivatives, weird ETFs)?

This determines whether remap-to-equity is safe or whether specific unknown subtypes need different handling.

### Phase 5c: Guarded Remap (after audit confirms safety)

Only proceed if Phase 5b shows unknowns are mostly equities. Changes needed across 6 skip sites + canonical exclusion set:

1. `trading_analysis/instrument_meta.py` — remove `"unknown"` from `_EXCLUDED_INSTRUMENT_TYPES`
2. `core/realized_performance/engine.py:273` — remap instead of exclude
3. `core/realized_performance/engine.py:1142` — remap instead of skip
4. `core/realized_performance/timeline.py:450` — remap instead of filter
5. `core/realized_performance/timeline.py:496` — remap instead of filter
6. `core/realized_performance/timeline.py:586` — remap instead of filter
7. `core/realized_performance/nav.py:149` — remap instead of skip in cash replay
8. `core/proxy_builder.py` — add explicit skip for `instrument_type == "unknown"` (prevent failed FMP lookups on unclassifiable tickers)

Feature-flag the remap (`UNKNOWN_REMAP_TO_EQUITY_ENABLED`, default false) for rollback safety.

**Verify**: Run realized performance on sample portfolios, verify NAV/returns are reasonable with unknown positions included.

---

## Step 6: Add `crypto` to InstrumentType Enum

**Files**: `trading_analysis/instrument_meta.py`

Crypto is missing from the enum. There's already an orphaned `SEGMENT_ASSET_CLASS_MAP` entry for `"crypto"` at line 58.

**Fix** — 2 additions in `instrument_meta.py`:
1. Add `"crypto"` to the `InstrumentType` Literal (line 7)
2. Add `"crypto"` to the `_VALID_INSTRUMENT_TYPES` set (line 27)

`SEGMENT_INSTRUMENT_TYPES` already has a `"crypto"` key at line 48, currently mapped to `{"equity"}`. Update it to `{"crypto"}` so crypto positions route to the crypto segment instead of equities.

`SEGMENT_ASSET_CLASS_MAP` already has `"crypto": {"crypto"}` at line 58 — no change needed there.

No normalizer changes needed yet — crypto detection in normalizers is a separate task when users actually have crypto positions.

**Verify**: `pytest tests/ -k instrument -v`

---

## Step 7: Option contract_identity Audit (Investigation Only)

**Files**: `providers/normalizers/schwab.py`, `providers/normalizers/snaptrade.py`

The audit identified that non-IBKR options may lack full `contract_identity` for B-S pricing. This step is investigation only — verify what each normalizer produces and document gaps.

**Preliminary finding**: Schwab already has option `contract_identity` logic at lines 848, 954, and 1064 — it populates `underlying`, `expiry`, `strike`, `right`, and `multiplier` via symbol parsing. SnapTrade also parses option symbols (lines 59-81). The gap is NOT absence of logic — it's that symbol-based parsing returns `None` when the format is unparseable.

**Action**: Verify what percentage of real option positions have parseable symbols. If >95%, the gap is low-severity. Document findings and add defensive logging when parsing fails.

This is S-sized (documentation + defensive logging).

**Verify**: N/A (investigation)

---

## Commit Grouping

| Commit | Steps | Description |
|--------|-------|-------------|
| — | 1 | DROPPED — CEF classification is intentional design, no change needed |
| 1 | 2 | Bond pricing filter + warning flag |
| 2 | 3 | Thread instrument_type through legacy price loaders |
| 3 | 4 | ISIN bond resolution fallback in IBKR contracts |
| 4 | 5a | "unknown" warning flag + telemetry (visibility, no behavior change) |
| 5 | 6 | Add crypto to InstrumentType enum |
| 6 | 7 | Option contract_identity audit (investigation, no code) |
| — | 5b | "unknown" audit (investigation, deferred until 5a surfaces data) |
| — | 5c | "unknown" guarded remap (deferred until 5b confirms safety) |

Steps 2-6 (commits 1-6) can ship independently in any order. Steps 5b/5c are deferred — 5a gives us the visibility to decide if/when to proceed.

---

## Verification

After all steps: `pytest tests/ -x -q` (full suite, fail-fast). Expected: 0 regressions, ~10 new tests.

## Key Files

- `providers/price_service.py` — Bond exclusion from filter
- `core/position_flags.py` — Warning flags for bond/unknown positions
- `portfolio_risk_engine/portfolio_config.py` — instrument_type passthrough
- `portfolio_risk_engine/portfolio_risk.py` — instrument_type passthrough
- `ibkr/contracts.py` — ISIN bond resolution
- `core/realized_performance/engine.py` — unknown remap
- `trading_analysis/instrument_meta.py` — crypto enum addition
