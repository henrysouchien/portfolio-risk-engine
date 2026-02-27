# Position Monitor: Local-Currency Display Fix

## Context

After the FX conversion implementation, the position monitor mixes currencies for non-USD positions. `_calculate_market_values()` converts `price`/`value` to USD but leaves `cost_basis` in the broker's original currency. The monitor then computes P&L by subtracting GBP entry from USD current price — producing wildly incorrect results.

**Example — AT (GBP), 300 shares:**
| Field | Currently Shows | Currency | Correct? |
|---|---|---|---|
| entry_price | 4.03 | GBP | — |
| current_price | 5.73 | USD | MISMATCH with entry |
| gross_exposure | 1,719 | USD | — |
| net_exposure | 1,719 | USD | — |
| dollar_pnl | +510 | mixed | WRONG (USD - GBP) |
| pnl_percent | +42.2% | mixed | WRONG (should be ~4.5%) |

**Root cause:** `normalize_fmp_price()` at `position_service.py:545` produces the local-currency price (£4.21 GBP for AT.L after GBX→GBP normalization) but it's immediately FX-converted to USD at line 549 and the local value is discarded. Meanwhile `cost_basis` (£1,209 from the broker) is never FX-converted.

**Data flow causing the bug:**
```
FMP quote: 420.5 GBp
    → normalize_fmp_price(): 4.21 GBP  ← local price (DISCARDED)
    → * get_spot_fx_rate("GBP"): 5.73 USD  ← stored as price
    → value = 300 * 5.73 = 1,719 USD

Broker cost_basis: £1,209 GBP  ← never converted, stays as-is

Monitor: entry = 1209/300 = £4.03 GBP, current = $5.73 USD  ← MIXED
P&L = (5.73 - 4.03) * 300 = 510  ← meaningless cross-currency subtraction
```

## Approach

Ensure **both paths** (cached and fresh) produce the same column structure: `local_price`/`local_value` in local currency, `price`/`value` in USD.

- **Cached path** (`_calculate_market_values()`): Capture `local_price = current_price` before FX conversion, then convert `price`/`value` to USD as before.
- **Fresh path** (`_get_positions_df()`): Plaid/SnapTrade return `price`/`value` in local currency. A new `_convert_fresh_to_usd()` step copies originals to `local_price`/`local_value`, then FX-converts `price`/`value` to USD.

The monitor uses `local_price` for price display and P&L computation (both sides of the P&L subtraction are in the same local currency). Exposure (`gross_exposure`/`net_exposure`) stays in USD — zero breaking change for existing consumers — with local-currency variants added as `_local` suffixed fields. The risk pipeline continues using `price`/`value` in USD unchanged.

**Key property:** For USD positions, `local_price == price` and `local_value == value` — zero visual regression.

**Exposure strategy:** Exposure defaults to USD everywhere (position-level, per-currency summary, portfolio totals). Non-USD currency groups additionally include `*_local` exposure fields and display them in the CLI. A `portfolio_totals_usd` section provides cross-currency USD aggregation.

**Why both paths matter:** `price`/`value` are not stored in the DB (only `cost_basis`, `quantity`, `currency` are persisted). They are in-memory only. Without the fresh-path conversion, the monitor's `portfolio_totals_usd` and `gross_exposure`/`net_exposure` (USD) fields would be wrong — they'd treat GBP values as if they were USD.

---

## Files Modified

| File | Changes |
|------|---------|
| `services/position_service.py` | New `_convert_fresh_to_usd()` for fresh path; add `local_price`/`local_value` in `_calculate_market_values()` (cached path); update `_ensure_cached_columns()`, `_consolidate_cross_provider()`, `_get_positions_df()` |
| `core/result_objects.py` | `_build_monitor_payload()`: use local-currency values for display/P&L, fix `primary_currency` selection; `to_monitor_cli()`: add currency labels, portfolio USD totals |
| `plaid_loader.py` | `consolidate_holdings()`: add `local_value` to sum columns, preserve `local_price` via firsts join |
| `snaptrade_loader.py` | `consolidate_snaptrade_holdings()`: add `local_value` to sum columns (cash + non-cash), preserve `local_price` via firsts join |
| `tests/utils/show_api_output.py` | `_handle_positions_monitor()`: use new field names (`pnl`, `total_pnl`), add currency labels, show local exposure for non-USD groups |

**Not modified:** `run_portfolio_risk.py`, `portfolio_risk.py`, `core/portfolio_analysis.py`, `fmp/fx.py` — the risk pipeline is unaffected.

---

## Step 1: Add `local_price`/`local_value` columns in `_calculate_market_values()`

**File:** `services/position_service.py` (lines 502-560)

**1a. Initialize columns** (after line 520, near the existing `original_currency` initialization):
```python
if "local_price" not in df.columns:
    df["local_price"] = None
if "local_value" not in df.columns:
    df["local_value"] = None
```

**1b. Cash path** (lines 531-539 — the `if position_type == "cash":` block):

Add `local_price = None` and `local_value = shares` (the pre-FX cash value):
```python
if position_type == "cash":
    value = shares
    local_cash_value = shares       # preserve pre-FX
    currency = normalize_currency(row.get("currency"))
    if currency and currency.upper() != "USD":
        value = value * get_spot_fx_rate(currency)
        df.at[idx, "currency"] = "USD"
    df.at[idx, "value"] = value
    df.at[idx, "price"] = None
    df.at[idx, "local_price"] = None
    df.at[idx, "local_value"] = local_cash_value
    continue
```

**1c. Equity path** (lines 541-558 — the `try:` block):

Capture local price **before** FX conversion. The key insertion is `local_price = current_price` right after `normalize_fmp_price()` and before the FX multiplication:
```python
try:
    raw_price, fmp_currency = fetch_fmp_quote_with_currency(fmp_symbol)
    if raw_price is None:
        raise ValueError("FMP returned no price")
    current_price, base_currency = normalize_fmp_price(raw_price, fmp_currency)
    base_currency = normalize_currency(base_currency)

    local_price = current_price           # ← NEW: preserve before FX

    if base_currency and base_currency.upper() != "USD":
        fx_rate = get_spot_fx_rate(base_currency)
        current_price = current_price * fx_rate

    df.at[idx, "price"] = current_price           # USD (unchanged)
    df.at[idx, "value"] = shares * current_price   # USD (unchanged)
    df.at[idx, "local_price"] = local_price        # ← NEW
    df.at[idx, "local_value"] = shares * local_price  # ← NEW
except Exception as price_error:
    portfolio_logger.warning(f"⚠️ Failed to get price for {ticker}: {price_error}")
    df.at[idx, "price"] = 0.0
    df.at[idx, "value"] = 0.0
    df.at[idx, "local_price"] = 0.0               # ← NEW
    df.at[idx, "local_value"] = 0.0                # ← NEW
```

For USD positions, the FX branch is skipped → `local_price == price` automatically.

---

## Step 1.5: Add `_convert_fresh_to_usd()` for the fresh path

**File:** `services/position_service.py`

The fresh path (`_fetch_fresh_positions()`) returns positions with `price`/`value` in local currency (e.g., GBP for AT). We need to preserve these as `local_price`/`local_value` and convert `price`/`value` to USD so both paths produce identical column structure.

**1.5a. New method** — add after `_calculate_market_values()`:
```python
def _convert_fresh_to_usd(self, positions: pd.DataFrame) -> pd.DataFrame:
    """Convert fresh provider positions from local currency to USD.

    Fresh positions from Plaid/SnapTrade arrive with price/value in local
    currency.  This method preserves the originals as local_price/local_value
    and converts price/value to USD using spot FX, mirroring the column
    structure produced by _calculate_market_values() for cached positions.
    """
    from fmp.fx import get_spot_fx_rate
    from utils.ticker_resolver import normalize_currency

    if positions is None or positions.empty:
        return positions

    df = positions.copy()
    if "original_currency" not in df.columns:
        df["original_currency"] = df["currency"] if "currency" in df.columns else None

    df["local_price"] = df["price"]
    df["local_value"] = df["value"]

    for idx, row in df.iterrows():
        currency = normalize_currency(row.get("currency"))
        position_type = row.get("type") or row.get("security_type") or "equity"

        if not currency or currency.upper() == "USD":
            continue  # already USD — local == USD

        fx_rate = get_spot_fx_rate(currency)

        if position_type == "cash":
            df.at[idx, "value"] = float(row.get("value") or 0) * fx_rate
            df.at[idx, "currency"] = "USD"
        else:
            local_p = float(row.get("price") or 0)
            local_v = float(row.get("value") or 0)
            df.at[idx, "price"] = local_p * fx_rate
            df.at[idx, "value"] = local_v * fx_rate   # use provider value, not qty*price
```

For USD positions the loop body is skipped → `local_price == price`, `local_value == value`.

**1.5b. Call from `_get_positions_df()`** (line 239-250):

Insert the call **after** `_fetch_fresh_positions()` and **before** `_save_positions_to_db()`. **Critical: set `df_for_save` BEFORE conversion** so the database stores provider-native (local currency) values:
```python
df = self._fetch_fresh_positions(provider)
df_for_save = df.copy()                    # ← preserve provider-native data for DB
df = self._convert_fresh_to_usd(df)        # ← NEW: local→USD + preserve local_price/local_value
if consolidate:
    df = self._consolidate_provider_positions(df, provider)

try:
    self._save_positions_to_db(df_for_save, provider)  # saves original local-currency data
except Exception as save_error:
    ...
```

**Why `df_for_save` before conversion:** `_convert_fresh_to_usd()` sets `currency="USD"` for non-USD cash positions. If we saved after conversion, the DB would lose the original currency. Setting `df_for_save` before conversion preserves provider-native currency for all position types.

**Data flow after fix (fresh path, AT):**
```
Plaid returns:
    price = 4.21 GBP, value = 1,263 GBP, cost_basis = 1,209 GBP

_convert_fresh_to_usd():
    local_price = 4.21 GBP       ← preserved (copy of price)
    local_value = 1,263 GBP      ← preserved (copy of value)
    price = 4.21 × 1.361 = 5.73 USD   ← local_price × fx_rate
    value = 1,263 × 1.361 = 1,719 USD  ← local_value × fx_rate (NOT qty*price)

DB save: cost_basis=1209, currency=GBP, quantity=300 (unchanged — uses df_for_save)
```

---

## Step 2: Add to `_ensure_cached_columns()`

**File:** `services/position_service.py` (lines 562-595)

After the existing `price` and `fmp_ticker` column checks (around line 588):
```python
if "local_price" not in df.columns:
    df["local_price"] = df["price"] if "price" in df.columns else None
if "local_value" not in df.columns:
    df["local_value"] = df["value"] if "value" in df.columns else None
```

This backfills missing columns for legacy cached data. Since `_calculate_market_values()` runs first (line 227) and sets the real values, this fallback only triggers if market values is somehow bypassed.

---

## Step 3: Add to `_consolidate_cross_provider()`

**File:** `services/position_service.py` (lines 337-381)

The cross-provider consolidation uses `groupby().agg()` which drops columns not in the aggregation dict. Add the new columns.

**3a. Cash section** (lines 319-335) — add `local_value` to cash `agg_dict`:

```python
# Defensive column init (after line 321):
if "local_value" not in cash_positions.columns:
    cash_positions["local_value"] = cash_positions.get("value")

# Add to agg_dict (line 323):
agg_dict = {
    "quantity": "sum",
    "value": "sum",
    "local_value": "sum",          # ← NEW
    "name": "first",
    "currency": "first",
    "type": "first",
    "account_id": "first",
    "cost_basis": "sum",
    "position_source": lambda x: ",".join(sorted(set([v for v in x if v]))),
    "fmp_ticker": lambda x: next((v for v in x if isinstance(v, str) and v.strip()), None),
}
```

**3b. Non-cash section** (lines 345-372) — add both `local_value` and `local_price`:

```python
# Defensive column init (after line 347):
if "local_price" not in non_cash_positions.columns:
    non_cash_positions["local_price"] = non_cash_positions.get("price")
if "local_value" not in non_cash_positions.columns:
    non_cash_positions["local_value"] = non_cash_positions.get("value")

# Add to agg_dict (line 360):
agg_dict = {
    "quantity": "sum",
    "value": "sum",
    "local_value": "sum",          # ← NEW: sum like value
    "name": "first",
    "type": "first",
    "account_id": "first",
    "cost_basis": "sum",
    "position_source": lambda x: ",".join(sorted(set([v for v in x if v]))),
    "fmp_ticker": lambda x: next((v for v in x if isinstance(v, str) and v.strip()), None),
    "local_price": "first",        # ← NEW: same FMP quote for same ticker
}
```

`local_price` uses `"first"` because same-ticker positions have the same FMP quote. `local_value` uses `"sum"` because it's quantity-weighted like `value`. Cash doesn't need `local_price` (cash has no price) but does need `local_value` to preserve the pre-FX cash amount.

---

## Step 3.5: Add `local_price`/`local_value` to provider-level consolidators

Provider-level consolidation (`_consolidate_provider_positions()` at line 383) dispatches to `plaid_loader.consolidate_holdings()` and `snaptrade_loader.consolidate_snaptrade_holdings()`. Both use a **sums + firsts join pattern** (not `groupby().agg()` with a dict). The pattern is:

1. `sums = groupby(key)[sum_cols].sum()` — aggregates numeric columns
2. `firsts = drop_duplicates(key, keep="first")` — preserves metadata
3. `sums.join(firsts.drop(columns=sum_cols))` — merges them

Without this fix, `local_value` would land in `firsts` (taking only the first row's value instead of summing), and `local_price` would also be in `firsts` (correct by accident, but only because the join happens to include it). We must explicitly add `local_value` to `sum_cols` and drop it from `firsts` to prevent duplicate columns on join.

**File: `plaid_loader.py`** — `consolidate_holdings()` (lines 1022-1038)

Currently sums `["quantity", "value"]` (line 1025). Change to include `local_value`, and drop it from `firsts`:

```python
# 1. Defensive column init (before the sums groupby):
if "local_price" not in df.columns:
    df["local_price"] = df.get("price")
if "local_value" not in df.columns:
    df["local_value"] = df.get("value")

# 2. Add local_value to sum_cols (line 1025):
sums = (
    df.dropna(subset=["ticker"])
      .groupby("ticker", as_index=False)[["quantity", "value", "local_value"]]  # ← added
      .sum()
)

# 3. Drop local_value from firsts alongside quantity/value (line 1038):
return sums.set_index("ticker").join(
    firsts.drop(columns=["quantity", "value", "local_value"]),  # ← added
    how="left"
).reset_index()
```

`local_price` is preserved via `firsts` (same FMP quote for same ticker — `"first"` is correct).

**File: `snaptrade_loader.py`** — `consolidate_snaptrade_holdings()` (lines 921-1003)

This function has two consolidation sections: cash (line 930) and non-cash (line 963). Both use the sums+firsts pattern.

**Non-cash section** (lines 963-992):

Currently sums `['quantity', 'value']` + optionally `cost_basis` (line 966-968). Add `local_value`:

```python
# 1. Defensive column init (before sum_cols, after line 963):
if "local_price" not in non_cash_positions.columns:
    non_cash_positions["local_price"] = non_cash_positions.get("price")
if "local_value" not in non_cash_positions.columns:
    non_cash_positions["local_value"] = non_cash_positions.get("value")

# 2. Add local_value to sum_cols (line 966):
sum_cols = ['quantity', 'value', 'local_value']  # ← added
if 'cost_basis' in non_cash_positions.columns:
    sum_cols.append('cost_basis')

# 3. Drop local_value from firsts (line 989):
# firsts already drops quantity, value; also drop local_value + cost_basis:
firsts.drop(columns=['quantity', 'value', 'local_value'], errors='ignore')  # ← added
```

`local_price` is preserved via `firsts` (same ticker = same FMP quote).

**Cash section** (lines 930-959):

Add `local_value` to cash sums too (see Step 3.5b below for cash consolidation consistency):

```python
# 1. Defensive column init:
if "local_value" not in cash_positions.columns:
    cash_positions["local_value"] = cash_positions.get("value")

# 2. Add local_value to sum_cols (line 932):
sum_cols = ['quantity', 'value', 'local_value']  # ← added
if 'cost_basis' in cash_positions.columns:
    sum_cols.append('cost_basis')

# 3. Drop local_value from firsts alongside other sum cols (line 949):
drop_cols = ['quantity', 'value', 'local_value']  # ← added
if 'cost_basis' in firsts.columns:
    drop_cols.append('cost_basis')
```

---

## Step 4: Update `_build_monitor_payload()` to use local-currency values

**File:** `core/result_objects.py` (lines 588-782)

**4a. Read local values** (around lines 610-628):

Change the source of price and value used for display/P&L:
```python
for position in monitor_positions:
    quantity = self._safe_float(position.get("quantity"))
    value = self._safe_float(position.get("value"))                # USD — kept for portfolio totals
    local_value = self._safe_float(position.get("local_value"))    # ← NEW: local currency
    cost_basis = position.get("cost_basis")
    raw_price_input = position.get("local_price")                  # ← CHANGED from "price"
    currency = position.get("original_currency") or position.get("currency")

    # Fallback for positions without local_price (backward compat only —
    # both cached and fresh paths now set local_price, but legacy data may not have it)
    if raw_price_input is None:
        raw_price_input = position.get("price")
        local_value = value
```

**4b. P&L computation** (lines 640-647): **No formula change needed.** Both `entry_price` (from `cost_basis / quantity`) and `raw_price` (now from `local_price`) are in the same currency. The existing formula produces correct local-currency P&L:
```python
dollar_pnl = (raw_price - entry_price) * quantity   # both local currency now ✓
pnl_percent = (dollar_pnl / abs(float(cost_basis))) * 100  # local / local ✓
```

**4c. Exposure fields — keep USD as default, add local variants** (lines 658-674):
```python
entry = {
    ...
    "gross_exposure": abs(value) if value is not None else None,               # USD (UNCHANGED)
    "net_exposure": value,                                                      # USD (UNCHANGED)
    "gross_exposure_local": abs(local_value) if local_value is not None else None,  # ← NEW: local currency
    "net_exposure_local": local_value,                                               # ← NEW: local currency
    ...
}
```

`gross_exposure`/`net_exposure` default to USD — zero breaking change for existing consumers. Local-currency variants use the `_local` suffix.

**4d. Per-currency summary — accumulate both USD and local exposure** (lines 682-737):

Keep existing USD exposure accumulation unchanged. Add parallel local-currency accumulators:
```python
# USD exposure (UNCHANGED — existing code):
if value is not None:
    summary["gross_exposure"] += abs(value)
    summary["net_exposure"] += value
    if quantity > 0:
        summary["long_exposure"] += abs(value)
    elif quantity < 0:
        summary["short_exposure"] += abs(value)

# Local-currency exposure (NEW):
if local_value is not None:
    summary["gross_exposure_local"] += abs(local_value)
    summary["net_exposure_local"] += local_value
    if quantity > 0:
        summary["long_exposure_local"] += abs(local_value)
    elif quantity < 0:
        summary["short_exposure_local"] += abs(local_value)
```

Initialize the `_local` fields to `0.0` in the summary dict alongside the existing ones.

**4e. `primary_currency` selection** (lines 739-744):

Since `gross_exposure` stays as USD, the existing code works correctly — no change needed:
```python
primary_currency = max(
    summary_by_currency.items(),
    key=lambda item: item[1]["gross_exposure"],  # already USD ✓
)[0]
```

**4g. Add `portfolio_totals_usd`** (after per-currency summaries, before payload construction):

Since `gross_exposure`/`net_exposure` are already USD on each position, we can sum them directly:
```python
portfolio_totals_usd = {
    "gross_exposure": 0.0,
    "net_exposure": 0.0,
    "long_exposure": 0.0,
    "short_exposure": 0.0,
    "total_pnl_usd": 0.0,
}
for position in processed_positions:
    gross = position.get("gross_exposure")          # already USD
    net = position.get("net_exposure")              # already USD
    qty = position.get("quantity")
    if gross is not None:
        portfolio_totals_usd["gross_exposure"] += gross
    if net is not None:
        portfolio_totals_usd["net_exposure"] += net
        if qty is not None and qty > 0:
            portfolio_totals_usd["long_exposure"] += abs(net)
        elif qty is not None and qty < 0:
            portfolio_totals_usd["short_exposure"] += abs(net)
    pnl_usd_val = position.get("pnl_usd")
    if pnl_usd_val is not None:
        portfolio_totals_usd["total_pnl_usd"] += pnl_usd_val
```

**4h. Update payload** (lines 755-770):
```python
"exposure_currency": "USD",                            # ← NEW: exposure fields are USD
"price_pnl_currency": "local",                         # ← NEW: prices/PnL use position's currency field
"values_currency": "USD",                              # ← KEPT as alias for backward compat
"summary": {
    "by_currency": summary_by_currency,
    "portfolio_totals_usd": portfolio_totals_usd,      # ← NEW
    ...
}
```

---

## Step 5: Update CLI display in `to_monitor_cli()`

**File:** `core/result_objects.py` (lines 809-992)

**5a. Column header** (line 872): Change `"$ PnL"` → `"PnL"` (not always dollars).

**5b. Section headers** (line 904): Annotate with currency for P&L (prices/P&L are local), exposure defaults to USD:
```python
lines.append(f"{currency} POSITIONS ({len(currency_positions)}) [prices/PnL in {currency}, exposure in USD]")
```

**5c. Per-currency summary**: Show USD exposure by default, then local-currency exposure underneath for non-USD groups:
```python
lines.append(f"{currency} SUMMARY")
lines.append(f"  Long Exposure:    ${_format_number(currency_summary.get('long_exposure'), 2)}")
lines.append(f"  Short Exposure:   ${_format_number(currency_summary.get('short_exposure'), 2)}")
lines.append(f"  Gross Exposure:   ${_format_number(currency_summary.get('gross_exposure'), 2)}")
lines.append(f"  Net Exposure:     ${_format_number(currency_summary.get('net_exposure'), 2)}")

# Show local-currency exposure for non-USD groups
if currency != "USD":
    lines.append(f"  Gross Exposure ({currency}): {_format_number(currency_summary.get('gross_exposure_local'), 2)}")
    lines.append(f"  Net Exposure ({currency}):   {_format_number(currency_summary.get('net_exposure_local'), 2)}")
```

**5d. Portfolio USD totals** (after the currency loop, around line 984): When multiple currencies exist, add aggregate section:
```python
if summary.get("has_multiple_currencies"):
    portfolio_totals = summary.get("portfolio_totals_usd", {})
    lines.append("")
    lines.append("PORTFOLIO TOTALS (USD)")
    lines.append("-" * table_width)
    lines.append(f"  Long Exposure:    ${_format_number(portfolio_totals.get('long_exposure'), 2)}")
    lines.append(f"  Short Exposure:   ${_format_number(portfolio_totals.get('short_exposure'), 2)}")
    lines.append(f"  Net Exposure:     ${_format_number(portfolio_totals.get('net_exposure'), 2)}")
    lines.append(f"  Gross Exposure:   ${_format_number(portfolio_totals.get('gross_exposure'), 2)}")
    lines.append(f"  Total PnL:        ${_format_number(portfolio_totals.get('total_pnl_usd'), 2)}")
```

---

## Step 6: Currency clarity across all data and visual outputs

Both the API (data) and CLI (visual) outputs must make it unambiguous what currency every value is in.

### 6a. API field renaming and additions (in `_build_monitor_payload()`)

**Per-position entry dict** (line 658-674) — rename and add USD counterparts:

| Current Field | Change | Rationale |
|---|---|---|
| `currency` | Keep — already present | Tells API consumer what local currency this position is in |
| `entry_price` | Keep as-is | Always local currency (from `cost_basis / quantity`) |
| `current_price` | Keep as-is | Now local currency (from `local_price`) |
| `dollar_pnl` | **Add `pnl`** (keep `dollar_pnl` as alias) | Not always dollars; keep old name for backward compat |
| — | **Add `pnl_usd`** | USD-equivalent P&L for cross-currency aggregation |
| `gross_exposure` | Keep as-is | USD (unchanged — zero breaking change) |
| `net_exposure` | Keep as-is | USD (unchanged — zero breaking change) |
| `gross_exposure_local` | **NEW** (Step 4c) | Local currency equivalent |
| `net_exposure_local` | **NEW** (Step 4c) | Local currency equivalent |
| `cost_basis` | Keep as-is | Always local currency (from broker) |

**Compute `pnl_usd`** — after the existing P&L calculation (line 640-647):
```python
pnl_usd = None
if dollar_pnl is not None and value is not None and local_value is not None and local_value != 0:
    # Scale local P&L by the same FX ratio as value/local_value
    fx_ratio = value / local_value
    pnl_usd = dollar_pnl * fx_ratio
```

For USD positions, `fx_ratio == 1.0` → `pnl_usd == pnl`.

**Updated entry dict:**
```python
entry = {
    "ticker": ...,
    "name": ...,
    "type": ...,
    "currency": normalized_currency,             # ← what currency local values are in
    "direction": direction,
    "quantity": quantity,
    "shares": abs(quantity) if quantity is not None else None,
    "entry_price": entry_price,                  # local
    "weighted_entry_price": entry_price,         # local
    "current_price": display_price,              # local
    "cost_basis": float(cost_basis) if valid_cost_basis else None,  # local
    "gross_exposure": abs(value) ...,             # USD (UNCHANGED)
    "net_exposure": value,                        # USD (UNCHANGED)
    "gross_exposure_local": abs(local_value) ..., # NEW: local currency
    "net_exposure_local": local_value,            # NEW: local currency
    "pnl": dollar_pnl,                          # local (NEW canonical name)
    "dollar_pnl": dollar_pnl,                    # local (KEPT for backward compat)
    "pnl_percent": pnl_percent,                 # unitless
    "pnl_usd": pnl_usd,                         # NEW: USD equivalent
    "entry_price_warning": entry_price_warning,
}
```

### 6b. Summary field renaming (in `_build_monitor_payload()`)

**Per-currency summary dict** (lines 682-737):

| Current Field | Change | Rationale |
|---|---|---|
| `total_pnl_dollars` | **Add `total_pnl`** (keep `total_pnl_dollars` as alias) | Not always dollars; keep old name for backward compat |
| `unrealized_pnl_dollars` | **Add `unrealized_pnl`** (keep `unrealized_pnl_dollars` as alias) | Same |
| — | **Add `total_pnl_usd`** | Sum of `pnl_usd` across positions in this currency group |

Add `total_pnl_usd` accumulation alongside existing `total_pnl_dollars` (now `total_pnl`):
```python
if dollar_pnl is not None:
    summary["total_pnl"] += dollar_pnl          # local currency
    summary["pnl_contributing_cost_basis"] += abs(float(cost_basis))
if pnl_usd is not None:
    summary["total_pnl_usd"] += pnl_usd         # USD
```

**`portfolio_totals_usd`** (Step 4g) — also add `total_pnl_usd`:
```python
portfolio_totals_usd = {
    "gross_exposure": 0.0,
    "net_exposure": 0.0,
    "long_exposure": 0.0,
    "short_exposure": 0.0,
    "total_pnl_usd": 0.0,                       # ← explicit _usd suffix for clarity
}
# ... accumulate from pnl_usd across all positions
```

### 6c. CLI display updates (in `to_monitor_cli()`)

**Column header** (line 872):
```python
("PnL", 12, "right"),         # was "$ PnL"
```

**Section header** (line 904):
```python
lines.append(f"{currency} POSITIONS ({len(currency_positions)}) [prices/PnL in {currency}, exposure in USD]")
```

**Per-position rows** (line 927): Use `pnl` instead of `dollar_pnl`:
```python
_format_number(position.get("pnl"), 2),        # was "dollar_pnl"
```

**Per-currency summary** (lines 946-972): Show USD exposure (default) + local exposure for non-USD groups:
```python
lines.append(f"{currency} SUMMARY")
lines.append(f"  Total PnL ({currency}): {_format_number(currency_summary.get('total_pnl'), 2)}")  # local
lines.append(f"  Total PnL (USD):  ${_format_number(currency_summary.get('total_pnl_usd'), 2)}")   # USD

# Exposure defaults to USD
lines.append(f"  Gross Exposure:   ${_format_number(currency_summary.get('gross_exposure'), 2)}")

# Show local-currency exposure for non-USD groups
if currency != "USD":
    lines.append(f"  Gross Exposure ({currency}): {_format_number(currency_summary.get('gross_exposure_local'), 2)}")
```

### 6d. Summary of currency contract

After these changes, the API contract is:

| Fields | Currency | How to tell |
|---|---|---|
| **Payload-level keys** | | |
| `exposure_currency` | — | Always `"USD"` — documents that exposure fields are USD |
| `price_pnl_currency` | — | Always `"local"` — documents that prices/PnL use position's `currency` |
| `values_currency` | — | **Kept as alias** = `"USD"` for backward compat (matches `exposure_currency`) |
| **Per-position fields** | | |
| `entry_price`, `current_price`, `cost_basis`, `pnl` | Local (position's `currency` field) | `position["currency"]` = "GBP", "USD", etc. |
| `gross_exposure`, `net_exposure` | Always USD | Default exposure is USD (unchanged from current behavior) |
| `gross_exposure_local`, `net_exposure_local` | Local (position's `currency` field) | `_local` suffix |
| `pnl_usd` | Always USD | `_usd` suffix |
| `pnl_percent` | Unitless | Percentage |
| **Summary fields** | | |
| `portfolio_totals_usd.*` (includes `total_pnl_usd`) | Always USD | Top-level key name + `_usd` suffix on P&L |
| Per-currency summary: `total_pnl`, `*_local` | That currency group's currency | Key in `by_currency` dict = "GBP", "USD" |
| Per-currency summary: exposure, `total_pnl_usd` | USD | Default summary exposure is USD |

---

## Edge Cases

1. **USD-only portfolios**: `local_price == price`, `local_value == value`. Identical display. No regression.

2. **Cached positions without `local_price`**: `_ensure_cached_columns()` backfills from `price`/`value`. Monitor builder also falls back to `"price"` if `"local_price"` is None.

3. **Fresh positions (non-cached path)**: `_convert_fresh_to_usd()` (Step 1.5) now runs on the fresh path. It copies `price`/`value` (local currency from Plaid) to `local_price`/`local_value`, then FX-converts `price`/`value` to USD. Both paths produce identical column structure. The DB save is unaffected because it only writes schema columns (`cost_basis`, `quantity`, `currency`, etc.) — `price`/`value`/`local_price`/`local_value` are in-memory only.

4. **Risk pipeline**: Untouched. `to_portfolio_data()`, `analyze_portfolio()`, etc. use `price`/`value` (USD).

5. **Entry price warning ratio** (lines 634-638): The `entry_price / display_price` ratio now compares same-currency values, which is correct. Previously it compared GBP vs USD.

6. **API consumers**: `gross_exposure`/`net_exposure` remain USD — zero breaking change. Old P&L field names kept as aliases for backward compat: `dollar_pnl` (= `pnl`), `total_pnl_dollars` (= `total_pnl`), `unrealized_pnl_dollars` (= `unrealized_pnl`). New fields: `pnl_usd`, `gross_exposure_local`/`net_exposure_local` per position, `total_pnl_usd` + `*_local` exposure per currency summary, `portfolio_totals_usd` in summary. Every position carries a `currency` field identifying its local currency. `show_api_output.py` should be updated to use the new canonical names (`pnl`, `total_pnl`) and display currency labels — but old field names will still work.

---

## Step 7: Update `show_api_output.py` monitor display

**File:** `tests/utils/show_api_output.py` — `_handle_positions_monitor()` (lines 1455-1492)

This testing utility reads monitor API output and displays it. Update to use new field names and add currency labels:

**7a. Per-position display** (line 1483): Use `pnl` with currency label instead of `dollar_pnl` with `$`:
```python
pnl = p.get("pnl")                             # was: p.get("dollar_pnl")
currency = p.get("currency", "USD")
pnl_s = f"{pnl:,.2f} {currency}" if pnl is not None else "N/A"
```

**7b. Per-currency summary** (line 1468): Use `total_pnl` with currency label:
```python
pnl_d = stats.get("total_pnl")                 # was: stats.get("total_pnl_dollars")
currency = currency_key                          # the dict key from by_currency
print(f"  P&L:   {pnl_d:,.2f} {currency} ({pnl_p:.2f}%)")  # was: ${pnl_d:,.2f}
```

**7c. Exposure display** (lines 1464-1467): These read `gross_exposure`/`net_exposure` which remain USD — no change needed. They can continue using `$` prefix.

**7d. Show local exposure for non-USD groups**: After the USD exposure line, optionally show local:
```python
if currency_key != "USD":
    local_gross = stats.get("gross_exposure_local")
    if local_gross is not None:
        print(f"  Gross ({currency_key}): {local_gross:,.2f}")
```

---

## Expected Result After Fix

**AT (GBP), 300 shares:**
| Field | After Fix | Currency | Notes |
|---|---|---|---|
| currency | GBP | — | Identifies local currency |
| entry_price | 4.03 | GBP | from cost_basis/qty |
| current_price | 4.21 | GBP | from local_price |
| cost_basis | 1,209 | GBP | from broker |
| gross_exposure | 1,719 | USD | from value (unchanged) |
| net_exposure | 1,719 | USD | from value (unchanged) |
| gross_exposure_local | 1,263 | GBP | from local_value |
| net_exposure_local | 1,263 | GBP | from local_value |
| pnl | +54 | GBP | (4.21-4.03)×300 |
| pnl_percent | +4.5% | — | unitless |
| pnl_usd | +73 | USD | pnl × FX rate |

## Verification

1. **Cached path** — `python3 run_positions.py --user-email hc@henrychien.com --monitor`
   - AT: entry £4.03, current £4.21, P&L ~£54 (~4.5%) — same currency, correct P&L
   - USD positions: unchanged
   - Portfolio USD totals section appears at bottom

2. **Fresh path** — Clear cache first, then re-run monitor to trigger fresh Plaid fetch:
   ```bash
   python3 -c "
   from database import get_pool
   pool = get_pool()
   conn = pool.getconn()
   cur = conn.cursor()
   cur.execute('''
       DELETE FROM positions
       WHERE portfolio_id IN (SELECT id FROM portfolios WHERE user_id = 1 AND name = 'CURRENT_PORTFOLIO')
       AND position_source = 'plaid'
   ''')
   conn.commit()
   print(f'Cleared {cur.rowcount} plaid positions')
   pool.putconn(conn)
   "
   python3 run_positions.py --user-email hc@henrychien.com --monitor
   ```
   - Same results as cached path: AT shows GBP values, correct P&L
   - Portfolio USD totals match cached path (within FX rate variance)

3. **API** — `python3 tests/utils/show_api_output.py positions/monitor`
   - `exposure_currency: "USD"` and `price_pnl_currency: "local"` in response
   - `portfolio_totals_usd` in summary
   - AT position: prices/PnL in GBP, `gross_exposure`/`net_exposure` in USD, `*_local` variants in GBP

4. **Risk pipeline regression** — `python3 tests/utils/show_api_output.py analyze` — no change expected
