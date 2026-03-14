# Handoff: Synthetic TWR Price Alignment — Verify & Commit

## Status: IMPLEMENTED BY CODEX, NEEDS LIVE VERIFICATION + COMMIT

## What happened this session

### Fix #17: Synthetic TWR Flow Fix (COMMITTED as `12966d69`)
- Added `_synthetic_events_to_flows()` helper — synthetic cash events now generate TWR external flows
- IBKR improved: **-32.53% → -24.80%** (broker actual: -9.35%)
- Schwab unchanged at +17.53%
- Docs updated and committed as `6ceec83e`

### Fix #18: Synthetic TWR Price Alignment (IMPLEMENTED, NOT COMMITTED)
- **Root cause of remaining 15pp gap:** synthetic TWR flows used sell prices from incomplete trades, but NAV values positions at market prices from `price_cache`. Verified $3,042 mismatch (12.2% of portfolio) across 7 stock tickers.
- **Example:** CBL sell price $22.87 vs March 3 market price $31.27. Flow = $2,287 but NAV = $3,127. The $840 gap shows as artificial return.
- **Fix:** `_synthetic_events_to_flows()` now accepts optional `price_cache` param, uses `_value_at_or_before()` for NAV-aligned pricing (same function used by `compute_monthly_nav()`). Falls back to event price if no cache entry.
- **Codex implemented + tests pass:** 15/15 new tests + 145/145 regression tests
- **Plan doc:** `docs/planning/SYNTHETIC_TWR_PRICE_ALIGNMENT_PLAN.md`
- **Codex review:** PASS (no blocking issues)

## What needs to happen

### 1. Live verification
MCP tool calls were failing (rejected without showing approval prompt — unknown Claude Code bug). Need to verify the fix works:

```bash
# Option A: via MCP after /mcp reconnect
get_performance(mode="realized", source="ibkr_flex", format="summary", use_cache=false)

# Option B: direct Python (~90 seconds)
RISK_MODULE_USER_EMAIL=hc@henrychien.com python3 -c "
import sys, json; sys.stdout = sys.stderr
from mcp_tools.performance import get_performance
r = get_performance(mode='realized', source='ibkr_flex', format='summary', use_cache=False)
sys.stdout = sys.__stdout__
print(json.dumps({k: r[k] for k in ['total_return','monthly_returns'] if k in r}, indent=2, default=str))
" 2>/dev/null
```

**Expected:** April -39% moderates significantly. Total return closer to -9.35%.

Also check Schwab is unchanged:
```
get_performance(mode="realized", source="schwab", format="summary", use_cache=false)
```

### 2. Commit (if verification passes)
```bash
git add core/realized_performance_analysis.py tests/core/test_synthetic_twr_flows.py
git commit -m "fix: align synthetic TWR flow prices with NAV prices (price_cache lookup)

Synthetic flows for incomplete trades used sell prices, but NAV values
positions at market prices from price_cache. The $3K mismatch (12% of
portfolio) created artificial +12% March / -12% April paired distortion.
Now uses _value_at_or_before(price_cache) for NAV-aligned pricing.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

### 3. Update docs
- Update `docs/planning/performance-actual-2025/RETURN_PROGRESSION_BY_FIX.md` with fix #18 results
- Add column to progression table

## Key files modified (uncommitted)

| File | Change |
|------|--------|
| `core/realized_performance_analysis.py:868` | `_synthetic_events_to_flows()` now accepts `price_cache`, uses `_value_at_or_before()` |
| `core/realized_performance_analysis.py:4499` | Call site passes `price_cache=price_cache` |
| `tests/core/test_synthetic_twr_flows.py` | 4 new tests (15 total) |

## Period mismatch note

Important context discovered this session: the broker's -9.35% covers **Dec 31 2024 → Dec 31 2025**, but our system measures **March 3 2025 → Feb 28 2026** (different periods). Some gap is expected from this alone. The price alignment fix addresses the artificial distortion within our measurement period; the period mismatch is a separate (and possibly acceptable) issue.

## Commits this session
- `12966d69` — fix: synthetic TWR flow fix (IBKR -32.53% → -24.80%)
- `6ceec83e` — docs: return progression with fix #17
