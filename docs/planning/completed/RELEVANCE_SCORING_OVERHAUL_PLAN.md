# Market Intelligence — Relevance Scoring Overhaul

## Context
Portfolio relevance scores in Market Intelligence are inconsistent and confusing:
1. **Economic events hardcoded at 70** — all show identical relevance regardless of portfolio composition
2. **Different multipliers per event type** (200-300x) create inconsistent scales
3. **`actionRequired` conflated with event type** — dividends/earnings always ACTION regardless of weight; news gated by relevance > 60

**Relevance should answer: "How much does this event affect MY portfolio?"**
**actionRequired should answer: "Do I need to act before a deadline?"**

## Codex Review Findings (Round 1 — all addressed)
1. **Fixed:** Builders are nested closures inside `build_market_events()` — compute `asset_class_weights` in the parent scope, closures access it directly (no parameter passing)
2. **Fixed:** Asset class weights normalized to sum to 1.0 using absolute values. Cash is included. No negative weights — `abs(value) / total_abs_value`
3. **Fixed:** `asset_class` can be None — use `(pos.get("asset_class") or "unknown").lower()`
4. **Fixed:** Absolute values appropriate here — we want total market exposure, not net. A leveraged portfolio IS more macro-sensitive
5. **Fixed:** Keyword taxonomy expanded with CPI, GDP, retail sales, PCE, consumer sentiment, auctions, etc. Priority-ordered matching
6. **Fixed:** Economic events sorted by relevance (not date) inside builder, then capped at 3 — highest-relevance events win
7. **Fixed:** Action text removed from descriptions when `actionRequired` becomes False
8. **Fixed:** Tests updated — existing assertions + new tests for asset class computation, keyword priority, edge cases
9. **Accepted:** Keep 5% threshold for earnings/dividends (not lowering to 3%)
10. **Accepted:** Materiality base saturation at 90 for large positions is fine
11. **Fixed:** General macro fallback lowered to `min(65, ...)` instead of 80
12. **Accepted:** Frontend badge count naturally updates
13. **Fixed:** Snapshot sharing — separate `_compute_asset_class_weights_from_snapshot()` function, does NOT modify `_load_portfolio_weights()` return type

## Codex Review Findings (Round 2 — all addressed)
14. **Fixed:** Loader contract — do NOT modify `_load_portfolio_weights()`. Add a separate `_compute_asset_class_weights_from_snapshot()` that calls `get_position_result_snapshot()` independently (snapshot is cached, no double-load)
15. **Fixed:** Economic builder sort — change from date sort to relevance sort before cap at 3, so portfolio-relevant events aren't dropped
16. **Fixed:** actionRequired imminence — add date proximity check: dividends ACTION only if ex-date within 14 days AND weight > 5%. Earnings ACTION only if earnings date within 14 days AND weight > 5%
17. **Fixed:** Asset class label normalization — add `_ASSET_CLASS_ALIASES` mapping to normalize raw labels before formula lookup
18. **Fixed:** Test section expanded — new tests for asset class weight computation, label normalization, keyword priority, cash-heavy portfolios, imminence gating

## Codex Review Findings (Round 3 — all addressed)
19. **Fixed:** Empty asset class data fallback — if asset class weights is empty dict, all economic events get neutral relevance of 50
20. **Fixed:** Margin/cash handling — two-pass: filter out negative-value cash (margin debt) rows first, THEN compute denominator from remaining positions. Weights sum to 1.0
21. **Fixed:** Macro slot guarantee — reduce reserved macro slots from 2 to 1 when cash >60%
22. **Fixed:** Asset class source — use `SECURITY_TYPE_TO_ASSET_CLASS` from `portfolio_risk_engine/constants.py` as fallback when `pos.get("asset_class")` is None
23. **Fixed:** Test patching — add stub to BOTH `_patch_loader_deps()` AND `_patch_empty_sources()` fixtures
24. **Fixed:** No separate snapshot call — `_compute_asset_class_weights()` takes a positions list, called from `build_market_events()` using positions already in scope
25. **Fixed:** Margin normalization — two-pass ensures weights sum to 1.0

## Codex Review Findings (Round 5 — all addressed)
26. **Clarified:** `_compute_asset_class_weights_from_snapshot()` is a separate function that calls cached snapshot independently. On `use_cache=True` (default), returns instantly from cache. On `use_cache=False`, performs second load — accepted tradeoff for keeping `_load_portfolio_weights()` contract untouched
27. **Clarified:** Test boundary unchanged — `_load_portfolio_weights()` NOT modified. Only new stub needed is `_compute_asset_class_weights_from_snapshot` in both fixtures
28. **Fixed:** Economic sort tiebreaker — sort by `(-relevance, date)` so date breaks ties within same relevance score

## Codex Review Findings (Round 7 — all addressed)
29. **Fixed:** Action text for dividends/earnings gated on same imminence boolean as `actionRequired`. Compute `is_imminent = within_14_days and weight > 0.05` once, use for BOTH `actionRequired` and the description append. A 20-day dividend no longer says "Review position" when `actionRequired=False`
30. **Fixed:** `mixed` asset class handling — treat `mixed` (ETFs/funds with unknown underlying) as 50/50 equity/bond split in macro formulas
31. **Fixed:** Economic sort preserves Fed-first priority via tertiary tiebreaker: `(-relevance, 0 if fed else 1, timeframe)`
32. **Fixed:** Imminence date parsing explicitly defined — `strptime("%Y-%m-%d")`, default `is_imminent=False` on parse failure

## Codex Review Findings (Final round — all addressed)
33. **Accepted:** Snapshot consistency on `use_cache=False` — both calls happen in the same request, portfolio changes mid-request are not realistic. The asset class helper is called FIRST so both see identical state. Negligible risk accepted
34. **Fixed:** Sort key cleaned up — economic builder's `timeframe` IS a date string (`"2026-03-19"`) from `row.get("date").split(" ")[0]`, so it sorts correctly. Prose updated for consistency. Sort order: relevance desc → date asc → Fed-first on same day
35. **Fixed:** Derivatives/unknown excluded from denominator entirely (like margin debt). Prevents dilution of macro sensitivity scores for derivative-heavy portfolios. Filter: `if ac in ("unknown", "derivative"): continue`
36. **Fixed:** Date parsing reuses the date string already extracted in each builder's flow (e.g., `row.get("date")`), not a second parse of a different field. FMP calendar uses consistent `YYYY-MM-DD` format. `is_imminent` defaults to `False` on any parse exception

## Plan

**File:** `mcp_tools/news_events.py` (single file, all changes)

### Change 1: Asset class weight computation (separate module-level function)

Does NOT modify `_load_portfolio_weights()` — that function, its return type, and all its callers remain unchanged. Instead, add a new `_compute_asset_class_weights_from_snapshot()` function that calls `get_position_result_snapshot()` independently. The snapshot is cached (TTL-based deep-copy cache in `position_snapshot_cache.py`), so the second call returns instantly from cache on the default `use_cache=True` path. On `use_cache=False`, it performs a second load — accepted tradeoff for keeping the loader contract untouched.

**New module-level constants:**
```python
_ASSET_CLASS_ALIASES: dict[str, str] = {
    "fixed_income": "bond",
    "equity_index": "equity",
    "metals": "commodity",
    "energy": "commodity",
    "agricultural": "commodity",
    "derivative": "unknown",
}
```

**New module-level function** (loads its own snapshot — cached, no contract change to `_load_portfolio_weights`):
```python
def _compute_asset_class_weights_from_snapshot(
    user_email: Optional[str] = None,
    account: Optional[str] = None,
    use_cache: bool = True,
) -> dict[str, float]:
    """Compute normalized asset class weights from ALL positions.

    Calls get_position_result_snapshot() which is TTL-cached — returns
    instantly if _load_portfolio_weights() already loaded the same snapshot.
    Two-pass: filter out margin debt, then normalize. Sums to 1.0.
    """
    from settings import get_default_user
    from portfolio_risk_engine.constants import SECURITY_TYPE_TO_ASSET_CLASS

    user = user_email or get_default_user()
    if not user:
        return {}
    try:
        snapshot = get_position_result_snapshot(
            user_email=user, use_cache=use_cache, force_refresh=False,
            consolidate=not bool(account),
        )
    except (ValueError, ConnectionError, OSError):
        return {}
    positions = snapshot.data.positions
    if account:
        positions = [p for p in positions if match_brokerage(account, p.get("brokerage_name"))]

    # Pass 1: classify and filter out margin debt
    classified: list[tuple[str, float]] = []
    for pos in positions:
        raw_ac = (pos.get("asset_class") or "").lower()
        if not raw_ac:
            ptype = (pos.get("type") or "unknown").lower()
            raw_ac = SECURITY_TYPE_TO_ASSET_CLASS.get(ptype, "unknown")
        ac = _ASSET_CLASS_ALIASES.get(raw_ac, raw_ac)
        val = float(pos.get("value") or 0)
        if ac == "cash" and val < 0:
            continue  # Exclude margin debt
        if ac in ("unknown", "derivative"):
            continue  # Exclude unclassifiable — prevents dilution
        classified.append((ac, abs(val)))

    # Pass 2: normalize
    total = sum(v for _, v in classified) or 1.0
    weights: dict[str, float] = {}
    for ac, val in classified:
        weights[ac] = weights.get(ac, 0.0) + val / total
    return weights
```

**Integration in `build_market_events()`**: Call `_compute_asset_class_weights_from_snapshot()` with same `user_email`, `account`, `use_cache` args alongside the existing `_load_portfolio_weights()` call. Store result as `asset_class_weights` in parent scope — nested closures access it directly.

**Macro slot adjustment** (~line 812): Reduce reserved macro slots from 2 to 1 when `asset_class_weights.get("cash", 0) > 0.6`.

**Test patching:** Add `_compute_asset_class_weights_from_snapshot` stub to BOTH `_patch_loader_deps()` AND `_patch_empty_sources()` fixtures. Default returns `{"equity": 0.5, "bond": 0.3, "real_estate": 0.15, "cash": 0.05}`.

### Change 2: Keyword constants for economic event classification

```python
_RATE_EVENT_KEYWORDS = frozenset({
    "interest rate", "fed", "fomc", "federal funds", "treasury",
    "mortgage rate", "10-year", "bond auction", "t-bill", "t-note",
    "monetary policy", "discount rate", "prime rate",
})
_EMPLOYMENT_EVENT_KEYWORDS = frozenset({
    "jobless", "employment", "nonfarm", "payroll", "unemployment",
    "jobs", "labor", "adp", "job openings", "jolt",
})
_HOUSING_EVENT_KEYWORDS = frozenset({
    "home sales", "housing", "building permits", "home price",
    "mortgage application", "housing starts",
})
_INFLATION_EVENT_KEYWORDS = frozenset({
    "cpi", "ppi", "pce", "inflation", "consumer price", "producer price",
    "core inflation",
})
_GROWTH_EVENT_KEYWORDS = frozenset({
    "gdp", "retail sales", "consumer sentiment", "consumer confidence",
    "ism", "pmi", "industrial production", "durable goods",
})
```

Priority order for matching: rate → inflation → employment → housing → growth → fallback. First match wins.

### Change 3: Unified company event formula

Replace the 6 different multipliers in nested builders with one consistent formula:
```python
relevance = min(90, max(15, int(weight * 250 + materiality_base)))
```

Materiality bases:
- Earnings: 30 | Analyst ratings: 25 | Estimate revisions: 25
- Dividends: 20 | Insider trades: 20 | News/sentiment: 15

### Change 4: Portfolio-aware economic event relevance

Inside `_build_economic_events()` (nested closure), access `asset_class_weights` from parent scope.

**Fallback:** If `asset_class_weights` is empty (snapshot failed), all economic events get neutral relevance of 50 — skip keyword formulas entirely.

```python
event_name_lower = event_name.lower()

# Fallback for unavailable asset class data
if not asset_class_weights:
    relevance = 50
# Priority-ordered keyword match
el    # Compute effective weights — treat "mixed" as 50/50 equity/bond
    mixed_half = asset_class_weights.get("mixed", 0) * 0.5
    eff_equity = asset_class_weights.get("equity", 0) + mixed_half
    eff_bond = asset_class_weights.get("bond", 0) + mixed_half
    eff_re = asset_class_weights.get("real_estate", 0)

if any(kw in event_name_lower for kw in _RATE_EVENT_KEYWORDS):
    relevance = min(85, max(20, int((eff_bond + eff_re) * 100 + 15)))
elif any(kw in event_name_lower for kw in _INFLATION_EVENT_KEYWORDS):
    invested = 1.0 - asset_class_weights.get("cash", 0)
    relevance = min(85, max(25, int(invested * 70 + 20)))
elif any(kw in event_name_lower for kw in _EMPLOYMENT_EVENT_KEYWORDS):
    relevance = min(85, max(20, int(eff_equity * 80 + 20)))
elif any(kw in event_name_lower for kw in _HOUSING_EVENT_KEYWORDS):
    relevance = min(85, max(20, int(eff_re * 120 + 20)))
elif any(kw in event_name_lower for kw in _GROWTH_EVENT_KEYWORDS):
    relevance = min(85, max(20, int(eff_equity * 75 + 20)))
else:
    # General macro fallback
    invested = 1.0 - asset_class_weights.get("cash", 0)
    relevance = min(65, max(20, int(invested * 50 + 15)))
```

### Change 5: `actionRequired` = date-driven deadlines with imminence check

`actionRequired` is true only when there's a deadline AND it's imminent (within 14 days):

| Event Type | actionRequired | Change |
|---|---|---|
| Dividends | `weight > 0.05 AND ex-date within 14 days` | Added imminence gate. The ex-date is already parsed in the builder (~line 540). Compare to `today`. |
| Earnings | `weight > 0.05 AND earnings date within 14 days` | Added imminence gate. The earnings date is already parsed in the builder (~line 430). Compare to `today`. |
| News/sentiment | `False` | Was: `relevance > 60` |
| Economic | `False` | No change (already False) |
| Estimate revisions | `False` | Was: `direction == "down" and weight > 0.05` |
| Insider trades | `False` | Was: `weight > 0.05` |
| Analyst ratings | `False` | Was: `action == "downgrade" and weight > 0.05` |

**Date parsing for imminence check:** Both builders carry raw date strings (e.g., `"2026-04-15"` from `row.get("date")`). Parse with `datetime.strptime(date_str, "%Y-%m-%d").date()` and compare to `datetime.now().date()`. If parsing fails (malformed/missing date), default `is_imminent = False`.

Note: The dividend builder already filters to next 30 days and the earnings builder to next 14 days. So the imminence check is largely redundant for earnings (already within window) but meaningful for dividends (narrows 30-day window to 14 days).

### Change 6: Remove action text from non-action events

Remove the conditional description appends that imply action when `actionRequired` is now False:

- **News** (~line 396-397): Remove `if portfolio_relevance > 60: desc += "- Review {ticker} position..."`
- **Estimate revisions** (~line 627-628): Remove `if direction == "down" and weight > 0.05: desc += "- Review {ticker} thesis..."`
- **Insider trades** (~line 694-695): Remove `if weight > 0.05: desc += "- Monitor {ticker}..."`
- **Analyst ratings** (~line 766-767): Remove `if action == "downgrade" and weight > 0.05: desc += "- Review {ticker} thesis..."`

**Dividends and earnings:** Gate action text on the SAME `is_imminent` boolean used for `actionRequired`. Compute once:
```python
is_imminent = weight > 0.05 and days_until_event <= 14
```
Use for both `"actionRequired": is_imminent` and the conditional description append. A dividend 20 days away with weight > 5% will NOT get action text or `actionRequired=True`.

### Change 7: Economic builder sort order

In `_build_economic_events()`, change the internal sort from date-first to relevance-first before capping at 3:
```python
# BEFORE: source_events.sort(key=lambda e: e.get("date", ""), ...)
# AFTER: relevance first, then Fed-first, then date as tiebreaker
source_events.sort(key=lambda e: (
    -e.get("portfolioRelevance", 0),
    e.get("timeframe", ""),              # Date second (nearest first within same relevance)
    0 if e.get("type") == "fed" else 1,  # Fed wins same-day ties
))
```
This preserves the existing Fed-first priority within same-relevance events.
This ensures the most portfolio-relevant economic events survive the cap, rather than just the nearest ones.

### Change 8: Update tests

**File:** `tests/mcp_tools/test_news_events_builder.py`

**Update existing assertions:**
- **Line ~229**: Dividend relevance values change (new formula: `weight * 250 + 20`)
- **Line ~279**: News `actionRequired` → `False` (was True when relevance > 60)
- **Line ~420**: Insider `actionRequired` → `False`
- **Line ~679**: News max relevance changes from 95 to 90
- **Line ~707**: Dividend `actionRequired` stays True (kept 5% threshold, within 14-day window)
- Any assertion on estimate revision or analyst rating `actionRequired` → `False`
- **Line ~591**: Economic sort assertion — update to reflect relevance-based sort instead of date sort

**Add new tests:**
- `test_asset_class_weight_computation` — verify `_compute_asset_class_weights_from_snapshot()` normalizes labels, handles None asset_class, sums to ~1.0
- `test_asset_class_label_normalization` — verify `_ASSET_CLASS_ALIASES` maps `fixed_income→bond`, `equity_index→equity`, `metals→commodity`, etc.
- `test_economic_relevance_rate_event` — rate event with bond-heavy portfolio gets high relevance, equity-only portfolio gets low
- `test_economic_relevance_employment_event` — employment event with equity-heavy portfolio gets high relevance
- `test_economic_relevance_fallback` — uncategorized event uses general macro formula
- `test_dividend_action_imminence` — dividend >14 days away does NOT get ACTION even if weight > 5%
- `test_news_no_action_text` — news events don't include "Review position" in description

## Verification
1. `pytest tests/mcp_tools/test_news_events_builder.py -v` — all tests pass with updated + new assertions
2. Restart backend, reload Overview
3. Company events: relevance varies by portfolio weight on a consistent 250x scale
4. Economic events: rate events show ~84% (bond+REIT heavy portfolio), employment ~60%, housing ~61%
5. ACTION tags only on dividends and earnings for positions >5% weight AND within 14 days
6. No "Review position" / "Monitor" text on non-action events
7. "Action Items" badge shows smaller, more meaningful count
