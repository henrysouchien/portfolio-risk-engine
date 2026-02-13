# Per-Account DB Storage Plan

## Problem Statement

Currently, when saving positions to the database, we consolidate by ticker first:

```
API Fetch → DataFrame (19 rows, 3 DSU entries across accounts)
    │
    └─► convert_to_portfolio_data() → Consolidated (1 DSU entry)
            │
            └─► save_portfolio_data() → DB (1 DSU row)
```

This loses per-account metadata:
- `account_name` - only keeps first account
- `account_id` - only keeps first account
- `brokerage_name` - only keeps first (though often same)
- Per-account breakdown of quantity/value/cost_basis

**Example:** DSU held in 3 Schwab accounts:
```
Before consolidation:
  DSU @ Schwab Rollover IRA:   517 shares, $5,638 cost
  DSU @ Schwab Individual:     2,427 shares, $26,010 cost
  DSU @ Schwab Contributory:   20 shares, $219 cost

After consolidation (current DB state):
  DSU @ Schwab Rollover IRA:   2,965 shares, $31,868 cost
  └─ account_name is misleading - only 517 shares are actually in Rollover IRA
```

## Requirements

1. **Cache/Display**: Need per-account breakdown
   - "Show me my positions by account"
   - "How much DSU do I have in my IRA?"

2. **Analysis**: Need consolidated totals
   - Risk analysis doesn't care which account holds shares
   - PortfolioData expects one entry per ticker

## Proposed Solution

Store per-account rows in DB, consolidate only when creating PortfolioData:

```
API Fetch → DataFrame (19 rows, 3 DSU entries)
    │
    ├─► DB Save: 19 rows preserved (per-account)
    │       └─ save_positions_from_dataframe(df)
    │
    └─► PortfolioData: consolidated (for analysis)
            └─ to_portfolio_data() consolidates
```

## Implementation Plan

### 1. Schema + Migration (unique constraint update) ✅ DONE

The current constraint blocks per-account rows:
```
UNIQUE(portfolio_id, ticker, position_source)
```

Update the constraint to allow multiple rows per ticker **per account** (and per currency if needed):
```
UNIQUE(portfolio_id, position_source, account_id, ticker, currency)
```

Notes:
- If `account_id` can be NULL, Postgres allows multiple NULLs; this is fine for manual rows.
- Include `currency` if multi-currency positions can exist within the same account.

Migration tasks:
- Drop old unique constraint.
- Add new unique constraint with account_id (+ currency).

### 2. DatabaseClient - Add `save_positions_from_dataframe()` ✅ DONE

**File:** `inputs/database_client.py`

```python
def save_positions_from_dataframe(
    self,
    user_id: int,
    portfolio_name: str,
    df: pd.DataFrame,
    position_source: str
) -> None:
    """
    Save DataFrame rows directly to positions table.

    Preserves per-account breakdown - no consolidation.
    Each DataFrame row becomes one DB row.

    Args:
        user_id: User's internal ID
        portfolio_name: Portfolio name (e.g., "CURRENT_PORTFOLIO")
        df: Normalized DataFrame with columns:
            - ticker, quantity, value, currency, type
            - account_id, account_name, brokerage_name
            - cost_basis, name, position_source
        position_source: Provider name for scoped deletion ("plaid", "snaptrade")
    """
    with self.get_connection() as conn:
        cursor = conn.cursor()
        conn.autocommit = False

        try:
            # Get or create portfolio
            portfolio_id = self.get_or_create_portfolio_id(user_id, portfolio_name)

            # Provider-scoped deletion (existing pattern)
            cursor.execute(
                "DELETE FROM positions WHERE portfolio_id = %s AND position_source = %s",
                (portfolio_id, position_source)
            )

            # Insert each row
            for _, row in df.iterrows():
                cursor.execute(
                    """
                    INSERT INTO positions
                    (portfolio_id, user_id, ticker, quantity, currency, type,
                     account_id, cost_basis, position_source, name, brokerage_name, account_name)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        portfolio_id,
                        user_id,
                        row.get('ticker'),
                        row.get('quantity') if row.get('quantity') is not None else row.get('value'),
                        row.get('currency', 'USD'),
                        row.get('type') or row.get('security_type', 'equity'),
                        row.get('account_id'),
                        row.get('cost_basis') if pd.notna(row.get('cost_basis')) else None,
                        row.get('position_source', position_source),
                        row.get('name'),
                        row.get('brokerage_name'),
                        row.get('account_name')
                    )
                )

            conn.commit()
            logger.info(f"💾 Saved {len(df)} positions for {position_source} (per-account)")

        except Exception as e:
            conn.rollback()
            raise
        finally:
            conn.autocommit = True
```

### 3. PositionService - Update save path ✅ DONE

Added `refresh_provider_positions()` and `delete_provider_positions()` to handle per-account saves.

**File:** `services/position_service.py`

```python
def _save_positions_to_db(self, df: pd.DataFrame, provider: str) -> None:
    """Save positions to DB - preserves per-account rows."""
    from inputs.database_client import DatabaseClient
    from database import get_db_session

    user_id = self._get_user_id()

    with get_db_session() as conn:
        db_client = DatabaseClient(conn)
        db_client.save_positions_from_dataframe(
            user_id=user_id,
            portfolio_name="CURRENT_PORTFOLIO",
            df=df,
            position_source=provider
        )
```

**Removed:** Calls to `convert_plaid_holdings_to_portfolio_data()` and `convert_snaptrade_holdings_to_portfolio_data()` in the save path.

### 4. Verify Consolidation for Analysis ✅ DONE

Fixed `to_portfolio_data()` in `core/data_objects.py` to properly sum cost_basis during consolidation, with NaN/None handling.

The `to_portfolio_data()` method must consolidate when creating PortfolioData.

**Current flow (should still work):**
```python
# PositionService.to_portfolio_data()
def to_portfolio_data(self, ...) -> PortfolioData:
    result = self.get_all_positions(consolidate=True)  # ← consolidates
    # Convert to PortfolioData format
```

**Verify:** `_consolidate_cross_provider()` is called and sums cost_basis correctly.

## Files Modified

| File | Change | Status |
|------|--------|--------|
| `database/migrations/20260130_update_positions_unique_constraint.sql` | Drop old unique constraint, add new one | ✅ |
| `inputs/database_client.py` | Add `save_positions_from_dataframe()`, `delete_positions_by_provider()` | ✅ |
| `services/position_service.py` | Add `refresh_provider_positions()`, `delete_provider_positions()`, architecture docs | ✅ |
| `core/data_objects.py` | Fix `to_portfolio_data()` to sum cost_basis with NaN handling | ✅ |
| `routes/plaid.py` | Use PositionService for disconnect/delete flows | ✅ |
| `routes/snaptrade.py` | Use PositionService for disconnect/delete flows | ✅ |
| `tests/unit/test_positions_data.py` | Add tests for per-account consolidation, NaN/None cost_basis | ✅ |

## DataFrame Column Mapping

| DataFrame Column | DB Column | Notes |
|-----------------|-----------|-------|
| `ticker` | `ticker` | Required |
| `quantity` | `quantity` | For securities (cash already uses quantity=value) |
| `value` | `quantity` | Only used if quantity is missing |
| `currency` | `currency` | Default: USD |
| `type` / `security_type` | `type` | equity, cash, etf, etc. |
| `account_id` | `account_id` | Broker's account ID |
| `account_name` | `account_name` | Human-friendly name |
| `brokerage_name` | `brokerage_name` | Institution name |
| `cost_basis` | `cost_basis` | Handle NaN → NULL |
| `name` | `name` | Security display name |

## Verification Steps

### 1. DB Storage (per-account)
```bash
python3 -c "
from services.position_service import PositionService
svc = PositionService(user_email='hc@henrychien.com')
svc.get_all_positions(force_refresh=True)
"

# Check DB has multiple rows per ticker:
psql -c "
SELECT ticker, account_name, quantity, cost_basis
FROM positions p
JOIN portfolios port ON p.portfolio_id = port.id
WHERE port.user_id = 1 AND p.ticker = 'DSU'
ORDER BY account_name;
"
# Expected: 3 rows (Rollover IRA, Individual, Contributory)
```

### 2. PortfolioData (consolidated)
```python
from services.position_service import PositionService
svc = PositionService(user_email='hc@henrychien.com')
portfolio_data = svc.to_portfolio_data()

dsu = portfolio_data.portfolio_input.get('DSU', {})
print(f"DSU shares: {dsu.get('shares')}")      # Should be ~2965 (summed)
print(f"DSU cost_basis: {dsu.get('cost_basis')}")  # Should be ~31868 (summed)
```

### 3. MCP Tool (per-account display)
```python
from mcp_tools.positions import get_positions

# Use by_account format to see per-account breakdown
result = get_positions(user_email='hc@henrychien.com', format='by_account')
# Returns: {"accounts": [{"brokerage": "Schwab", "account_name": "Rollover IRA", ...}, ...]}

# Each account shows its own DSU position with correct quantity/cost_basis
for account in result["accounts"]:
    dsu = [p for p in account["positions"] if p["ticker"] == "DSU"]
    if dsu:
        print(f"{account['account_name']}: {dsu[0]['quantity']} shares, ${dsu[0].get('cost_basis', 0):.0f} cost")
# Expected output:
#   Rollover IRA: 517 shares, $5638 cost
#   Individual: 2427 shares, $26010 cost
#   Contributory IRA: 20 shares, $219 cost
```

## Rollback Plan

If issues arise, revert to using convert functions:
```python
# In _save_positions_to_db:
portfolio_data = convert_snaptrade_holdings_to_portfolio_data(df, ...)
portfolio_manager.save_portfolio_data(portfolio_data)
```

## Future Considerations

1. **Cache invalidation**: When a user adds/removes accounts, need to handle partial updates
2. **DB size**: More rows per ticker - monitor storage growth
3. **Query performance**: May need index on (portfolio_id, ticker, account_name)

---

*Created: 2025-01-30*
*Completed: 2025-01-30*
*Status: ✅ COMPLETE*
