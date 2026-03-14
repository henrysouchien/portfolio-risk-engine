# Centralized FMP Ticker Resolution

**Status:** COMPLETE (commit `40b41dc2`)
**Goal:** Fix AT. ($2K NAV gap) and prevent future international symbol pricing failures
**Depends on:** Trailing-dot fix (commit `867b46fd`) COMPLETE

## Problem

IBKR positions have `fmp_ticker: null`. When the realized performance engine
prices AT. (Ashtead Technology, LSE, GBP), it sends raw "AT." to FMP instead
of "AT.L" → gets empty data → valued at $0 → persistent ~$2K NAV gap.

**Root cause:** `providers/ibkr_positions.py` doesn't call `resolve_fmp_ticker()`.
SnapTrade and Plaid loaders each call it independently. Any new provider would
also need to remember to add the call.

**Secondary root cause:** `ibkr_positions.py` drops the `exchange` field from
`ibkr/account.py:143` when building position rows. Without `exchange_mic`,
`SymbolResolver.resolve()` cannot route to the MIC→suffix path and returns the
base ticker unchanged.

**Current state (fragmented):**
```
snaptrade_loader.py:961  → resolve_fmp_ticker()  ✓
plaid_loader.py:114      → resolve_fmp_ticker()  ✓
ibkr/flex.py:33          → resolve_fmp_ticker()  ✓ (for trades)
ibkr_positions.py        → (nothing)             ✗ ← BUG
```

**Existing infrastructure:**
- `providers/symbol_resolution.py` — `SymbolResolver.resolve()` wraps
  `resolve_fmp_ticker()` with instrument-type routing, trailing-dot strip,
  and futures map. Already built for this purpose but unused for positions.
- `utils/ticker_resolver.py` — `resolve_fmp_ticker()` with exchange_mic
  lookup, FMP name search, and TTL cache.
- `ibkr/exchange_mappings.yaml` — `ibkr_exchange_to_mic` section maps IBKR
  exchange codes to ISO MICs (e.g., `LSE: XLON`, `IBIS: XETR`).
- `ibkr/flex.py:275-277` — already loads and uses `ibkr_exchange_to_mic` for
  trade normalization. Pattern to follow.

## Design

Two changes:
1. Propagate `exchange` → `exchange_mic` in `ibkr_positions.py` (data fix)
2. Add centralized resolution pass in `position_service.py` (safety net)

```
ibkr/account.py                  ibkr_positions.py
  exchange: "LSE"  ──────────►  exchange_mic: "XLON"  (NEW)
                                        │
                                        ▼
                              position_service.py
                              _resolve_missing_fmp_tickers()
                                        │
                    SymbolResolver.resolve("AT", exchange_mic="XLON", currency="GBP")
                                        │
                    resolve_fmp_ticker("AT", exchange_mic="XLON")
                                        │
                    mic_to_fmp_suffix["XLON"] = ".L"  →  "AT.L"
                                        │
                                        ▼
                              fmp_ticker = "AT.L"  (persisted to DB)
```

### Change 1: Propagate exchange metadata in IBKR positions

**File:** `providers/ibkr_positions.py`

**Why needed:** `SymbolResolver.resolve()` at line 66-67 returns the base ticker
unchanged when `currency == "USD" and not exchange_mic`. For non-USD equities
with no `exchange_mic`, it falls through to `resolve_fmp_ticker()` which also
needs `exchange_mic` for the fast MIC→suffix path (ticker_resolver.py:220-224).
Without `exchange_mic`, the only path is FMP name search — but IBKR sets
`name = str(item.get("symbol"))` = `"AT."`, which is useless for search.

With `exchange_mic="XLON"`, `resolve_fmp_ticker()` hits the deterministic
MIC→suffix path: `"AT" + ".L" = "AT.L"`. No FMP API call needed.

**Change in `fetch_positions()` (line ~148-162):**

```python
# Module-level loader. ibkr_positions.py lives at providers/ibkr_positions.py,
# so we go up one level (to repo root) then into ibkr/.
def _load_ibkr_exchange_mappings() -> dict[str, Any]:
    path = Path(__file__).resolve().parent.parent / "ibkr" / "exchange_mappings.yaml"
    try:
        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}

# In fetch_positions(), load once before the account loop:
exchange_mappings = _load_ibkr_exchange_mappings()
ibkr_exchange_to_mic = {
    str(k).strip().upper(): str(v).strip().upper()
    for k, v in (exchange_mappings.get("ibkr_exchange_to_mic", {}) or {}).items()
    if str(k).strip() and str(v).strip()
}

# In the row builder (line ~148), add exchange_mic field:
rows.append(
    {
        ...existing fields...
        "exchange_mic": ibkr_exchange_to_mic.get(
            str(item.get("exchange") or "").strip().upper()
        ),
    }
)
```

**Note:** `_load_ibkr_exchange_mappings()` is a private 3-line YAML loader that
already exists in `ibkr/flex.py:76`, `ibkr/compat.py:37`, and
`ibkr/contracts.py:25` (all identical copies loading `ibkr/exchange_mappings.yaml`).
Add the same private copy in `ibkr_positions.py` — consistent with existing
pattern. No need to expose publicly.

### Change 2: Centralized resolution in position_service.py

**File:** `services/position_service.py`

**Insertion point — BEFORE `df_for_save` copy:**

The current flow at lines 429-436:
```python
# Line 430: df_for_save = df.copy()      ← copy happens HERE
# Line 431: df = self._convert_fresh_to_usd(df)
# Line 436: self._save_positions_to_db(df_for_save, provider)
```

`df_for_save` is the frame saved to DB. Resolution must happen BEFORE this copy
so resolved `fmp_ticker` values persist to DB cache. Otherwise, subsequent cached
reads would still have `fmp_ticker=null`.

**New insertion in `_get_positions_df()` (line ~429):**
```python
df = self._resolve_missing_fmp_tickers(df)    # ← NEW (before copy)
df_for_save = df.copy()
df = self._convert_fresh_to_usd(df)
```

**Also in `refresh_provider_positions()` (line ~1021-1024):**

This is a second fresh-fetch path (used by disconnect/resync flows) that
fetches and saves directly without going through `_get_positions_df()`:
```python
df = self._fetch_fresh_positions(provider)
df = partition_positions(df, provider)
df = self._resolve_missing_fmp_tickers(df)    # ← NEW
self._save_positions_to_db(df, provider)
```

Both paths must apply resolution before save to ensure `fmp_ticker` persists.

This ensures:
1. Resolved `fmp_ticker` is in `df_for_save` → persists to DB cache
2. Cached positions already have `fmp_ticker` populated → no re-resolution
3. Single-provider `get_positions()` calls also benefit
4. Resync flows via `refresh_provider_positions()` also resolve

### New method

```python
def _resolve_missing_fmp_tickers(self, df: pd.DataFrame) -> pd.DataFrame:
    """Fill null fmp_ticker values using SymbolResolver for non-cash equities."""
    if df.empty or "fmp_ticker" not in df.columns:
        return df

    needs_resolution = (
        df["fmp_ticker"].isna()
        & df["type"].isin(["equity", "etf", "mutual_fund"])
        & ~df["ticker"].str.startswith("CUR:", na=False)
    )

    if not needs_resolution.any():
        return df

    from providers.symbol_resolution import SymbolResolver

    df = df.copy()
    resolver = SymbolResolver()

    for idx in df.index[needs_resolution]:
        row = df.loc[idx]
        resolved = resolver.resolve(
            raw_symbol=str(row.get("ticker") or ""),
            provider=str(row.get("position_source") or ""),
            company_name=str(row.get("name") or ""),
            currency=str(row.get("currency") or ""),
            exchange_mic=str(row.get("exchange_mic") or ""),
        )
        raw_ticker = str(row.get("ticker") or "").rstrip(".")
        if resolved and resolved != raw_ticker:
            df.at[idx, "fmp_ticker"] = resolved

    return df
```

### Why not also fix the per-loader calls?

Leave them as-is. They pre-populate the resolution cache, so the central
pass hits the cache for tickers already resolved. Removing them would be a
larger refactor with no functional benefit. The central pass is the safety
net that catches gaps.

## Files Modified

| File | Change |
|------|--------|
| `providers/ibkr_positions.py` | Add `_load_ibkr_exchange_mappings()`, add `exchange_mic` field to position rows using `ibkr_exchange_to_mic` mapping |
| `services/position_service.py` | Add `_resolve_missing_fmp_tickers()` method; call BEFORE `df_for_save` copy in `_get_positions_df()` AND before save in `refresh_provider_positions()` |

## Tests

**File:** `tests/services/test_position_fmp_resolution.py` (NEW)

1. `test_resolve_fills_null_fmp_ticker_for_ibkr_lse_equity` — position with
   `ticker="AT.", fmp_ticker=None, currency="GBP", exchange_mic="XLON",
   position_source="ibkr"` → `fmp_ticker` set to `"AT.L"`
   (mock `SymbolResolver.resolve` returns `"AT.L"`)

2. `test_resolve_skips_already_populated` — position with
   `fmp_ticker="AT.L"` already set → not overwritten

3. `test_resolve_skips_cash_positions` — `type="cash"` positions → skipped

4. `test_resolve_skips_derivatives` — `type="derivative"` positions → skipped
   (futures have their own resolution path)

5. `test_resolve_handles_usd_equities` — `currency="USD"` equity with no
   `exchange_mic` → `SymbolResolver.resolve()` returns base ticker (no suffix
   needed), `fmp_ticker` stays null (resolver returns same as input → no
   assignment)

6. `test_resolve_empty_df` — empty DataFrame → returned unchanged

7. `test_resolve_persists_to_db_save_frame` — integration test: mock
   `PositionService._save_positions_to_db` and `_fetch_fresh_positions` (returns
   df with `fmp_ticker=None, exchange_mic="XLON", currency="GBP"`), mock
   `SymbolResolver.resolve` to return `"AT.L"`. Call `_get_positions_df()`.
   Assert that `_save_positions_to_db` was called with a df where `fmp_ticker`
   is `"AT.L"` — proving the resolution happens before `df_for_save` copy.

**File:** `tests/providers/test_ibkr_positions.py` (NEW or extend existing)

8. `test_ibkr_position_row_includes_exchange_mic` — mock IBKR portfolio item
   with `exchange="LSE"` → position row has `exchange_mic="XLON"`

9. `test_ibkr_position_row_exchange_mic_none_when_missing` — mock IBKR item
   with no `exchange` → `exchange_mic` is None (not error)

## Verification

### Unit tests
```bash
pytest tests/services/test_position_fmp_resolution.py -v
pytest tests/providers/test_ibkr_positions.py -v
pytest tests/services/ -v  # regression
```

### Live test
```
get_positions(use_cache=false)
```
- AT. position should now have `fmp_ticker="AT.L"` and `exchange_mic="XLON"`

```
get_performance(mode="realized", source="ibkr_flex", format="agent", use_cache=false)
```
- AT. should no longer appear in `unpriceable_symbols`
- `unpriceable_symbol_count` should drop from 1 to 0
- NAV gap at end (~Feb 28) should shrink by ~$2K (from $2,977 to ~$900)

## Expected Impact

- **AT. priced correctly:** ~$2,064 added to NAV → closes ~70% of end-point NAV gap
- **Future international symbols:** Any provider that returns non-USD equities
  without `fmp_ticker` will be auto-resolved by the central pass
- **IBKR positions enriched:** `exchange_mic` propagated from IBKR API, enabling
  deterministic MIC→suffix resolution (no FMP API call needed for known MICs)
- **No breaking changes:** Existing per-loader resolution is redundant but harmless
