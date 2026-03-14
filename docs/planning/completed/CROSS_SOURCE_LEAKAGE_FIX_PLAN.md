# Plan: Fix Cross-Source Holding Leakage for Multi-Brokerage Symbols

**Status:** IMPLEMENTED
**Goal:** Stop excluding legitimate positions when the same symbol is held at different brokerages

## Context

The realized performance engine uses `_build_source_scoped_holdings()` to determine
which positions belong to a given source (e.g., `source="plaid"`). It has a
"cross-source leakage" detection that excludes symbols appearing in multiple sources.

**Problem:** The leakage detection is **symbol-level**, not **account-level**. When
DSU is genuinely held in both a Schwab account and a Merrill account (via Plaid),
the engine sees `symbol_to_sources["DSU"] = {"schwab", "plaid"}` and excludes DSU
from the Plaid scope — because schwab (native) takes precedence over plaid (aggregator).

This is wrong. These are separate positions at different brokerages. The Schwab DSU
and the Merrill DSU are not duplicates — they're different holdings.

**Impact:** When all Plaid/Merrill holdings (DSU, MSCI, STWD) are excluded, the engine
has 0 holdings for Plaid, creates synthetic positions, and produces garbage returns
(177% instead of the correct ~2%).

## Root Cause

`holdings.py:270` builds `symbol_to_sources` keyed by symbol only:
```python
symbol_to_sources: Dict[str, set[str]] = defaultdict(set)
```

Lines 323-338 then check if a symbol appears in multiple sources — but this conflates
genuinely separate positions at different brokerages with duplicate reporting of the
same position.

## When Leakage Detection Was Needed (Historical)

The leakage detection was added when position data could come from overlapping sources
for the **same** underlying brokerage account:
- SnapTrade reports Schwab positions (aggregator mirror)
- Schwab API also reports the same positions (native)
- Same symbol, same account, two reporting paths → genuine duplicate

Now that each account has a clear authoritative source:
- IBKR → `ibkr_flex` (native via Flex Query or IBKR API)
- Schwab → `schwab` (native API)
- Merrill → `plaid` (aggregator, only path available)

...the symbol-level check is too aggressive. It catches cross-brokerage holdings
that are NOT duplicates.

## Fix

### Approach: Institution-Aware Leakage Detection with Row-Scoped Exclusion

Replace the symbol-level `symbol_to_sources` map with an institution-aware check.
A symbol should only be flagged as leaking if the **same institution/brokerage**
reports it through multiple provider sources. Crucially, exclusion is **row-scoped**
— only rows belonging to the ambiguous `(symbol, institution)` bucket are excluded,
not rows from other institutions holding the same symbol.

**File:** `core/realized_performance/holdings.py` — `_build_source_scoped_holdings()`

### Step 1: Add `_resolve_institution_slug()` helper (module-level)

Add a canonical institution slug resolver that uses `INSTITUTION_SLUG_ALIASES` — the
same alias table used by `match_institution()`. This ensures "Charles Schwab",
"schwab", and "SCHWAB" all resolve to the canonical slug `"charles_schwab"`.

```python
def _resolve_institution_slug(raw_value: str) -> str:
    """Resolve a brokerage/institution name to a canonical slug.

    Uses INSTITUTION_SLUG_ALIASES for normalization (same alias table as
    match_institution()). Returns "unknown" if the value is empty. For
    non-empty values with no alias match, returns a slugified version of
    the raw value (preserves uniqueness for unknown brokerages).

    Note: This duplicates some logic from match_institution() in
    data_fetcher.py. Kept separate to avoid circular imports (holdings.py
    is imported by engine.py which is imported early in the stack).
    """
    from settings import INSTITUTION_SLUG_ALIASES

    text = str(raw_value or "").lower().replace("_", " ").replace("-", " ").strip()
    text = " ".join(text.split())
    if not text:
        return "unknown"

    def _slugify(v: str) -> str:
        return v.lower().replace("-", "_").replace(" ", "_").strip("_")

    aliases = {
        " ".join(str(k).lower().replace("_", " ").replace("-", " ").split()): str(v).lower().strip()
        for k, v in INSTITUTION_SLUG_ALIASES.items()
    }
    canonical_slugs = {slug for slug in aliases.values() if slug}

    # Direct slug match (e.g., "charles_schwab" → "charles_schwab")
    text_slug = _slugify(text)
    if text_slug in canonical_slugs:
        return text_slug

    # Alias lookup (e.g., "charles schwab" → "charles_schwab")
    for alias, slug in aliases.items():
        if alias and alias in text:
            return slug

    # No alias match — use slugified raw value (preserves uniqueness)
    return text_slug or "unknown"
```

### Step 2: Track sources per (symbol, institution_slug) with candidate row tagging

Replace the `symbol_to_sources` accumulation (lines 270, 298-315). Store
`candidate_rows` as `(row, institution_slug)` tuples so exclusion can be row-scoped.

```python
# OLD:
symbol_to_sources: Dict[str, set[str]] = defaultdict(set)
candidate_rows: List[Dict[str, Any]] = []

# NEW:
symbol_institution_sources: Dict[Tuple[str, str], set[str]] = defaultdict(set)
symbol_to_sources: Dict[str, set[str]] = defaultdict(set)  # kept for diagnostics
candidate_rows: List[Tuple[Dict[str, Any], str]] = []  # (row, institution_slug)
```

For each position row, resolve the canonical institution slug:
```python
row_institution = _resolve_institution_slug(
    pos.get("brokerage_name") or pos.get("institution") or ""
)
symbol_institution_sources[(symbol, row_institution)].update(sources_for_symbol)
symbol_to_sources[symbol].update(sources_for_symbol)

if source in matches:
    candidate_rows.append((pos, row_institution))
```

### Step 3: Rewrite leakage check to produce `(symbol, institution)` pairs

Build `leakage_pairs: set[Tuple[str, str]]` instead of `symbol_level_leakage: set[str]`.
Only the specific `(symbol, institution)` buckets that are ambiguous get flagged.

```python
_NATIVE_SOURCES = {"schwab", "ibkr_flex"}
_AGGREGATOR_SOURCES = {"plaid", "snaptrade"}

# Only check (symbol, institution) buckets that have candidate rows.
# This prevents non-candidate buckets (where sources_for_symbol includes raw
# tokens filtered out by _provider_matches_from_position_row) from producing
# leakage diagnostics that describe exclusions that never happened.
candidate_pairs = {
    (str(row.get("ticker") or "").strip(), inst)
    for row, inst in candidate_rows
}

leakage_pairs: set[Tuple[str, str]] = set()
for (symbol, inst), sources in symbol_institution_sources.items():
    if (symbol, inst) not in candidate_pairs:
        continue  # no candidate rows for this exact bucket → skip
    if source not in sources or len(sources) <= 1:
        continue
    # Unknown institution: always treat as leakage (conservative).
    # We can't determine if native+aggregator sources refer to the same
    # account or different accounts, so exclude to be safe.
    if inst == "unknown":
        leakage_pairs.add((symbol, inst))
        continue
    # Known institution reported by multiple providers = genuine duplicate
    native_in = sources & _NATIVE_SOURCES
    aggregator_in = sources & _AGGREGATOR_SOURCES
    unknown_sources = sources - _NATIVE_SOURCES - _AGGREGATOR_SOURCES
    # Native source takes precedence for same-institution duplicates
    if (
        native_in
        and aggregator_in
        and len(native_in) == 1
        and not unknown_sources
        and source in native_in
    ):
        continue  # native wins, no leakage for this bucket
    leakage_pairs.add((symbol, inst))

# Row-level ambiguity: tag the specific (symbol, institution) of the ambiguous row
# (not bare symbols) so other institutions' rows for the same symbol are untouched
row_level_ambiguous_pairs: set[Tuple[str, str]] = set()
# ... (populated during the main loop when len(matches) > 1)

all_leakage_pairs = leakage_pairs | row_level_ambiguous_pairs

# Compute which candidate rows survive (for partial-leakage diagnostics)
survived_symbols: set[str] = set()
for row, inst in candidate_rows:
    sym = str(row.get("ticker") or "").strip()
    if (sym, inst) not in all_leakage_pairs:
        survived_symbols.add(sym)

# All symbols with any leakage pair
all_leakage_symbols = {sym for sym, _inst in all_leakage_pairs}
# Symbols fully excluded (no surviving rows) — used for reliability gate
fully_excluded = sorted(all_leakage_symbols - survived_symbols)
# Symbols partially excluded (some rows survived) — informational only
partially_excluded = sorted(all_leakage_symbols & survived_symbols)
```

Key difference from v1: `leakage_pairs` contains `(symbol, institution)` tuples.
DSU at Schwab → `("DSU", "charles_schwab"): {"schwab"}` (1 source → skip).
DSU at Merrill → `("DSU", "merrill"): {"plaid"}` (1 source → skip).
Neither is in `leakage_pairs`. Both rows pass through.

The genuine duplicate case (Schwab + SnapTrade mirror):
- SnapTrade row with `brokerage_name="Charles Schwab"`: `_provider_matches_from_position_row`
  resolves to primary match `{"schwab"}` (from brokerage_name). The row is a
  `source="schwab"` candidate, NOT a `source="snaptrade"` candidate.
- Both rows are schwab candidates. `("DSU", "charles_schwab"): {"schwab", "snaptrade"}`
  (from raw `position_source` tokens in `sources_for_symbol`).
- For `source="schwab"`: native-wins exemption fires → both rows survive
  (pre-existing behavior, documented in Known Limitations).
- For `source="snaptrade"`: the SnapTrade row is NOT a candidate (matches={"schwab"}),
  so `candidate_pairs` doesn't include `("DSU", "charles_schwab")` for snaptrade.
  No leakage check, no candidate rows → empty result.

### Step 4: Row-scoped `strict_rows` filtering

Replace the symbol-level exclusion with pair-scoped exclusion. Each candidate row
was tagged with its `institution_slug` in Step 2, so we check against `all_leakage_pairs`:

```python
# OLD: symbol-level — one ambiguous institution wipes ALL rows for that symbol
strict_rows = [
    row for row in candidate_rows
    if str(row.get("ticker") or "").strip() not in set(cross_source_leakage_symbols)
]

# NEW: row-scoped — only exclude rows whose (symbol, institution) bucket is ambiguous
strict_rows = [
    row for row, inst in candidate_rows
    if (str(row.get("ticker") or "").strip(), inst) not in all_leakage_pairs
]
```

This is the critical fix: DSU from Merrill (Plaid) passes through even if DSU from
an "unknown" institution is flagged as leakage. Only the specific `(symbol, institution)`
rows that are genuinely ambiguous are excluded.

### Step 5: Handle missing institution ("unknown") conservatively

When `brokerage_name` and `institution` are both empty, `_resolve_institution_slug()`
returns `"unknown"`. In the leakage check (Step 3), `inst == "unknown"` buckets
are **always** flagged as leakage when they have multiple sources — the native-wins
exemption is skipped. This is because we can't determine whether the native and
aggregator sources refer to the same underlying account or different accounts.

Only the "unknown"-institution rows are excluded. Rows for DSU from known
institutions (Merrill, Schwab) are untouched via row-scoped filtering (Step 4).

This handles the "mixed known/unknown" edge case: some rows have `brokerage_name`
set (e.g., from Plaid) and some don't (e.g., from a legacy import). The known rows
are preserved; only the unattributable ones are excluded.

### Step 6: Update row-level ambiguity tracking

The row-level ambiguity check (line 314) currently populates `row_level_ambiguous_symbols`.
Change to populate `row_level_ambiguous_pairs`:

```python
# OLD:
if len(matches) > 1 and source in matches:
    row_level_ambiguous_symbols.add(symbol)

# NEW:
if len(matches) > 1 and source in matches:
    row_level_ambiguous_pairs.add((symbol, row_institution))
```

### Step 7: Update warning text and diagnostics for partial leakage

The existing warning (line 345) says "Excluded N cross-source holding symbol(s)...".
With row-scoped exclusion, some rows for a symbol may survive while others are excluded.
Update the warning to distinguish fully vs partially excluded:

```python
if fully_excluded:
    preview = ", ".join(fully_excluded[:5])
    if len(fully_excluded) > 5:
        preview = f"{preview}, ..."
    warnings.append(
        f"Excluded {len(fully_excluded)} cross-source holding symbol(s) from {source} "
        f"strict holdings scope ({preview}); attribution remained ambiguous after "
        f"institution-aware precedence checks."
    )
if partially_excluded:
    preview = ", ".join(partially_excluded[:5])
    if len(partially_excluded) > 5:
        preview = f"{preview}, ..."
    warnings.append(
        f"Partially excluded {len(partially_excluded)} symbol(s) from {source} scope "
        f"({preview}); some institution rows were ambiguous but other institutions' "
        f"rows were retained."
    )
```

**Reliability gate**: Engine.py line 2745 uses `cross_source_holding_leakage_symbols`
as a hard reliability gate (`reliable = False` if non-empty). With row-scoped
exclusion, partially-excluded symbols have surviving legitimate rows — marking the
result unreliable for those would be overly conservative. The dropped rows were
genuinely ambiguous (unknown institution or multi-source bucket), and keeping them
would risk double-counting.

Use `fully_excluded` (symbols where ALL candidate rows were dropped) for the
reliability gate:

```python
# In SourceScopedHoldings return:
cross_source_holding_leakage_symbols=fully_excluded,  # reliability gate
```

No new fields are added to `SourceScopedHoldings`. Partial leakage info is
communicated only via warning text (Step 7). This avoids threading a new field
through engine.py, aggregation.py, and result_objects serialization.

Partially-excluded symbols are NOT in `cross_source_holding_leakage_symbols` because:
- The dropped rows were genuinely ambiguous (unknown institution → correct exclusion)
- The surviving rows from other institutions are legitimate
- Setting reliable=False would be overly conservative and defeat the purpose of
  institution-aware detection
- Warning text provides sufficient visibility for debugging partial cases

## Files Modified

| File | Change |
|------|--------|
| `core/realized_performance/holdings.py` | Add `_resolve_institution_slug()` helper (module-level) |
| `core/realized_performance/holdings.py:270-377` | Replace symbol-level leakage with institution-aware, row-scoped leakage |

## Known Limitations

**Same-institution multi-account**: If two accounts at the same institution (e.g.,
two Merrill accounts) both hold DSU, and one account is duplicated across providers
while the other is single-sourced, both rows are excluded because the leakage
detection operates at `(symbol, institution)` granularity — not `(symbol, account_id)`.
This is extremely rare in practice (would require two accounts at the same brokerage
holding the same symbol with different provider coverage) and is strictly better than
the current symbol-level approach which excludes ALL rows regardless of institution.
Moving to `(symbol, account_id)` granularity would be a future enhancement if needed.

**Same-institution native+aggregator mirror (PRE-EXISTING)**: When requesting
`source="schwab"`, if both a native Schwab row AND a SnapTrade row (with
`brokerage_name="Charles Schwab"`) exist for DSU, both pass `source in matches`
(because `_provider_matches_from_position_row` resolves "Charles Schwab" to "schwab"
via primary match). The native-wins precedence exempts this from leakage, so both
rows survive → potential double-counting. **This is the existing behavior** in the
current code (lines 330-337) and is NOT introduced or changed by this plan. A
separate row-level authoritative-source dedup would fix it but is out of scope here.

## Edge Cases

| Scenario | Old Behavior | New Behavior |
|----------|-------------|--------------|
| DSU in Schwab + DSU in Merrill/Plaid | **EXCLUDED** from plaid (leakage) | **INCLUDED** in both scopes (separate institutions) |
| DSU in Schwab + DSU via SnapTrade (same Schwab account) | Schwab wins (native precedence) | Same — schwab wins (same institution, native precedence) |
| DSU from single source only | No leakage | No leakage (unchanged) |
| SPY in Schwab + SPY in IBKR | Excluded from both (two natives) | **INCLUDED** in both (different institutions) |
| Unknown institution, multiple sources | N/A | Only "unknown" rows excluded; known-institution rows preserved |
| Mixed known/unknown for same symbol | N/A | "unknown" rows excluded; "merrill" rows kept |
| Institution alias variation ("Schwab" vs "Charles Schwab") | Treated as different → false split | Same canonical slug `charles_schwab` → correctly grouped |
| Plaid rate-limited (0 positions) | 0 holdings, synthetic garbage | 0 holdings (but no leakage to make it worse) |

**Note on SPY case:** SPY held at both Schwab and IBKR is a genuine holding at
each brokerage. The old behavior excluded it from both scopes, which was incorrect.
The new behavior includes it in each source's scope — matching the actual portfolio.

**Note on institution aliasing:** `_resolve_institution_slug("Charles Schwab")` and
`_resolve_institution_slug("schwab")` both return `"charles_schwab"` via
`INSTITUTION_SLUG_ALIASES`. This prevents accidental bucket splits from name variations.

## Tests

### Updated tests (expectations change):

1. **`test_source_scoped_aggregator_excluded_when_native_present`** — DSU from Plaid
   account_id + DSU from Schwab account_id. **OLD:** DSU excluded from plaid.
   **NEW:** DSU INCLUDED in plaid (different institutions → not leakage).
   Need to add `brokerage_name` to test rows.

2. **`test_source_scoped_holdings_two_aggregators_still_ambiguous`** — AAPL from
   plaid + snaptrade with same position row `position_source: "plaid,snaptrade"`.
   **OLD:** AAPL excluded. **NEW:** Still excluded if same institution (single row
   with ambiguous source). But if different accounts at different brokerages → included.

3. **`test_source_scoped_two_native_sources_still_leakage`** — SPY from schwab +
   ibkr_flex with different account_ids and different brokerage_names.
   **OLD:** Excluded. **NEW:** INCLUDED (different institutions).

### New tests:

4. **`test_cross_brokerage_same_symbol_not_leakage`** — DSU from Schwab
   (brokerage_name="Charles Schwab") + DSU from Plaid (brokerage_name="Merrill").
   Request source="plaid". Verify DSU is INCLUDED, not in leakage list.

5. **`test_same_brokerage_native_scope_no_regression`** — DSU from schwab API
   (brokerage_name="Charles Schwab", position_source="schwab") + DSU from snaptrade
   mirror (brokerage_name="Charles Schwab", position_source="snaptrade"). Request
   source="schwab". Both rows match via `_provider_matches_from_position_row` (primary
   match from brokerage_name). The `("DSU", "charles_schwab"): {"schwab", "snaptrade"}`
   bucket has native+aggregator → native-wins exemption → NOT leakage. This is the
   existing behavior and should be preserved (non-regression). Verify DSU is in
   `source_holding_symbols` and `cross_source_holding_leakage_symbols` is empty.

6. **`test_unknown_institution_with_multiple_sources_is_leakage`** — Position with
   no brokerage_name, position_source="plaid,schwab". Test both scopes:
   - `source="plaid"`: row is NOT a candidate (native-wins in secondary match
     reduces matches to {"schwab"}). No candidate rows → candidate_symbols guard
     skips leakage check → `cross_source_holding_leakage_symbols` is empty.
     DSU absent from holdings (not a candidate).
   - `source="schwab"`: row IS a candidate. `("DSU", "unknown")` has {"plaid",
     "schwab"} → `inst == "unknown"` → always leakage. Verify DSU excluded from
     strict_rows and appears in `cross_source_holding_leakage_symbols`.

7. **`test_plaid_merrill_symbols_included_when_schwab_also_holds`** — Real-world
   case: DSU, MSCI, STWD each from Schwab (brokerage="Charles Schwab") AND from
   Plaid (brokerage="Merrill"). Request source="plaid". Verify all 3 included.

8. **`test_mixed_known_unknown_institution_merrill_survives`** — DSU from Plaid
   (brokerage_name="Merrill", position_source="plaid") + DSU from unknown source
   (no brokerage_name, position_source="plaid,schwab"). Request source="plaid".
   The unknown row's matches={"schwab"} (native-wins in secondary), so it is NOT
   a plaid candidate. `candidate_pairs` only contains `("DSU", "merrill")`.
   `("DSU", "unknown")` is NOT checked (not in candidate_pairs). The Merrill row's
   `("DSU", "merrill")` has single source {"plaid"} → no leakage.
   Verify: DSU in `source_holding_symbols`, `cross_source_holding_leakage_symbols`
   is empty, no leakage warnings.

9. **`test_institution_alias_variation_groups_correctly`** — DSU from
   brokerage_name="schwab" + DSU from brokerage_name="Charles Schwab". Both should
   resolve to `charles_schwab` slug and be in the same bucket (not treated as
   different institutions).

10. **`test_resolve_institution_slug_canonical`** — Unit test for the helper:
    - `"Charles Schwab"` → `"charles_schwab"`
    - `"schwab"` → `"charles_schwab"`
    - `"Merrill"` → `"merrill"`
    - `"Interactive Brokers LLC"` → `"interactive_brokers"`
    - `"ibkr"` → `"interactive_brokers"`
    - `""` → `"unknown"`
    - `"Some New Broker"` → `"some_new_broker"` (slugified fallback)

11. **`test_partial_leakage_not_in_reliability_list`** — Holdings-level test.
    Two schwab candidate rows for DSU: one with brokerage_name="Charles Schwab"
    (position_source="schwab"), one with no brokerage_name and
    position_source="schwab,plaid" (ambiguous). Request source="schwab".
    Both are schwab candidates. `candidate_pairs` includes `("DSU", "charles_schwab")`
    and `("DSU", "unknown")`. The Schwab row's `("DSU", "charles_schwab")` has
    single source {"schwab"} → no leakage. The unknown row's `("DSU", "unknown")`
    has {"schwab", "plaid"} → inst=="unknown" → leakage. Row-scoped exclusion drops
    only the unknown row; Schwab row survives. `fully_excluded` is empty (DSU has
    a surviving row). Verify:
    - `cross_source_holding_leakage_symbols` does NOT include DSU
    - `warnings` list contains a "Partially excluded" message mentioning DSU
      (from Step 7 warning text)

12. **`test_partial_leakage_engine_reliable`** — Engine-level integration test.
    Same setup as test 11 (partial leakage with one surviving institution row).
    Run through `_analyze_realized_performance_single_scope` (or mock context).
    Verify:
    - `CROSS_SOURCE_HOLDING_LEAKAGE` is NOT in `data_quality_flags`
    - `reliable` is not set to False due to leakage
    - The surviving DSU row contributes to NAV
    This validates that the `fully_excluded` list (used in SourceScopedHoldings)
    correctly gates the engine.py reliability check at line 2745.

### Regression:

```bash
pytest tests/core/test_realized_performance_analysis.py -x -q -k "source_scoped"
pytest tests/core/test_realized_performance_analysis.py -x -q
```

## Verification

After implementation, re-run:
```
get_performance(mode="realized", source="plaid", format="summary", use_cache=false)
```

Check:
- `data_coverage` > 0 (was 0)
- `cross_source_holding_leakage_symbols` is empty or doesn't include DSU/MSCI/STWD
- `total_return` is ~2% (not 177%)
- `source_holding_symbols` includes DSU, MSCI, STWD

## Expected Impact

| Metric | Before | After |
|--------|--------|-------|
| Plaid source_holding_count | 0 (all leaked) | 3+ (DSU, MSCI, STWD) |
| Plaid data_coverage | 0% | ~100% |
| Plaid total_return | 177% (garbage) | ~2% (correct) |
| Combined total_return | Unstable | Stable regardless of source |
