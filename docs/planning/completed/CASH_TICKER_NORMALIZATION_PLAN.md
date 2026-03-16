# Cash Ticker Normalization: USD:CASH → CUR:USD

**Status**: READY TO EXECUTE
**Date**: 2026-03-16
**Context**: Found during R6b live testing — Schwab's `USD:CASH` ticker doesn't match the `CUR:<currency>` convention used by IBKR, Plaid, and SnapTrade. 30+ downstream sites check `startswith("CUR:")` to identify cash positions.

---

## Problem

The Schwab direct provider (`providers/schwab_positions.py:104`) emits cash positions with ticker `USD:CASH`. Every other provider uses `CUR:<currency>` (e.g., `CUR:USD`, `CUR:GBP`).

The entire downstream system keys on `CUR:` prefix to identify cash:
- `portfolio_assembler.py:120` — consolidation cash/non-cash split
- `position_service.py:956` — cross-provider consolidation cash split
- `position_flags.py:86` — concentration denominator exclusion
- `data_objects.py:348,369,529` — PortfolioData cash handling
- `mcp_tools/*.py` — 10+ tools filter cash via `startswith("CUR:")`
- `routes/*.py` — onboarding, hedging cash detection
- `core/realized_performance_analysis.py` — performance cash exclusion

Because `USD:CASH` doesn't match `CUR:`, Schwab cash is treated as an investment position in all of these. This causes:
1. Schwab margin debt counted in `gross_exposure` (inflates investment totals)
2. Schwab cash not consolidated with IBKR/Plaid cash (duplicate rows)
3. Schwab cash leaking into factor analysis, tax harvest, rebalance, etc.
4. Two "Margin Debt (USD)" rows in the holdings table instead of one

## Solution

Normalize cash tickers to `CUR:<currency>` in `PositionService._normalize_columns()` — the existing normalization boundary between providers and the rest of the system. This method already handles cross-provider schema differences (`security_type` → `type`, `market_value` → `value`, `institution` → `brokerage_name`). Cash ticker normalization belongs here.

**Do NOT change `providers/schwab_positions.py`** — brokerage providers emit raw data in whatever format the brokerage uses. Normalization happens at the service layer.

**Known gap**: The CSV provider path (`position_service.py:708`) bypasses `_normalize_columns()`. If a CSV import contains `USD:CASH`, it won't be normalized. This is low risk — CSV imports are rare and manual — and can be addressed separately if needed.

---

## Step 1: Add cash ticker normalization to `_normalize_columns()`

**File**: `services/position_service.py` — `_normalize_columns()` (line 888)

After the existing normalizations (around line 916, after required column checks), add:

```python
# Normalize synthetic cash tickers to CUR:<currency> convention.
# Uses alias_to_currency from cash_map.yaml as the canonical set of
# known synthetic cash tickers. This is the same config that
# SecurityTypeService Tier 1 and portfolio cash mapping already use.
#
# NOTE: type == "cash" also includes money market funds (SWVXX, SNAXX)
# from Plaid/Schwab. Those are real holdings — do NOT rewrite them.
# Only normalize tickers found in alias_to_currency.
from config import resolve_config_path
import yaml

try:
    _cash_map_path = resolve_config_path("cash_map.yaml")
    with open(_cash_map_path, "r") as f:
        _cash_aliases = set(yaml.safe_load(f).get("alias_to_currency", {}).keys())
except FileNotFoundError:
    _cash_aliases = {"CUR:USD", "USD CASH", "CASH", "BASE_CURRENCY"}

if "type" in df.columns and "ticker" in df.columns:
    cash_mask = df["type"].astype(str).str.strip().str.lower() == "cash"
    tickers_raw = df["ticker"].astype(str).str.strip()
    is_known_alias = tickers_raw.isin(_cash_aliases) | tickers_raw.str.upper().isin(
        {a.upper() for a in _cash_aliases}
    )
    needs_normalize = cash_mask & is_known_alias & ~tickers_raw.str.startswith("CUR:", na=False)
    if needs_normalize.any():
        def _to_cur_ticker(currency_val):
            if pd.isna(currency_val) or not str(currency_val).strip():
                return "CUR:USD"
            return f"CUR:{str(currency_val).strip().upper()}"
        df.loc[needs_normalize, "ticker"] = df.loc[needs_normalize, "currency"].apply(_to_cur_ticker)
```

Uses `cash_map.yaml` `alias_to_currency` as the single source of truth for synthetic cash tickers. Adding a new broker's cash format is a config change, not a code change. Money market fund tickers (SWVXX, SNAXX) are preserved — they're not in the alias map. Safe for `NaN`/empty currency (falls back to `CUR:USD`).

## Step 2: Update cash_map.yaml aliases

**File**: `cash_map.yaml` (project root — `resolve_config_path("cash_map.yaml")` finds this before `config/cash_map.yaml`)

Add `USD:CASH` to `alias_to_currency`. This is now the **single source of truth** — Step 1 reads this map to decide what to normalize. Adding a new broker's cash format is a one-line config change. Update BOTH copies (`cash_map.yaml` and `config/cash_map.yaml`) to keep them in sync.

```yaml
alias_to_currency:
  CUR:USD: USD
  USD CASH: USD
  USD:CASH: USD          # Schwab direct provider format
  CASH: USD
  BASE_CURRENCY: USD
  CUR:EUR: EUR
```

## Step 3: Purge stale DB rows

Schwab positions with ticker `USD:CASH` may be persisted in the `positions` table from previous syncs. These won't be re-normalized until the next Schwab sync.

Run a one-time SQL update (can be done in a migration or manually):

```sql
UPDATE positions p
SET ticker = 'CUR:' || COALESCE(NULLIF(UPPER(TRIM(p.currency)), ''), 'USD')
FROM portfolios pf
WHERE p.portfolio_id = pf.id
  AND p.type = 'cash'
  AND p.ticker NOT LIKE 'CUR:%'
  AND p.ticker IN ('USD:CASH', 'USD CASH', 'CASH', 'BASE_CURRENCY')
  AND pf.portfolio_type != 'manual';
```

Uses the same explicit alias list as `cash_map.yaml` — no regex. Money market fund tickers (SWVXX, etc.) are preserved. `NULLIF` handles empty currencies. Join to `portfolios` excludes manual portfolio rows.

## Step 4: Tests

**File**: `tests/services/test_position_service_provider_registry.py` (or new test file)

- Test: Schwab cash `ticker="USD:CASH"` → normalized to `CUR:USD`
- Test: IBKR cash `ticker="CUR:GBP"` → unchanged (already normalized)
- Test: `ticker="CASH"`, `type="cash"` → normalized to `CUR:USD`
- Test: `ticker="BASE_CURRENCY"`, `type="cash"` → normalized to `CUR:USD`
- Test: Money market `ticker="SWVXX"`, `type="cash"` → ticker PRESERVED (real holding, not synthetic)
- Test: Non-cash position `ticker="USD:CASH"`, `type="equity"` → NOT normalized (type != cash)
- Test: Cash with `currency=NaN` or `currency=""` → normalized to `CUR:USD` (fallback)

## Step 5: Verify consolidation

After normalization, Schwab `CUR:USD` and IBKR `CUR:USD` will consolidate into a single row in `_consolidate_cross_provider()`. Verify:
- Single "Margin Debt (USD)" row in holdings table
- Combined value = Schwab margin + IBKR margin
- `gross_exposure` no longer includes Schwab margin debt

---

## Verification

1. Holdings table shows ONE "Margin Debt (USD)" row (not two)
2. `portfolio_totals_usd.gross_exposure` decreases by ~$16.5k (Schwab cash no longer counted as investment)
3. Position weights shift slightly (denominator decreased)
4. No Schwab cash in factor analysis, tax harvest, rebalance outputs
5. Alert percentages recalculate correctly with clean denominator
