# Fix: Schwab Dividend Description → Ticker Resolution (Bug 23)

## Context

Schwab `DIVIDEND_OR_INTEREST` transactions have **no instrument/symbol field** — only a company name in `description` (e.g., "ENBRIDGE INC F"). The current two-pass resolution in `_resolve_income_symbol()` does exact matching only:
1. Trade description map — fails when no matching trade exists in lookback window
2. Position name lookup — fails because Schwab positions report `name='ENB'` (ticker), not "Enbridge Inc"

Result: 4 ENB dividends ($612) appear as `UNRESOLVED_DIVIDEND`.

### Root Cause Investigation

Schwab's positions API returns `instrument.description = None` for all `EQUITY` type instruments. Only `COLLECTIVE_INVESTMENT` types (funds/ETFs like DSU, SPY) get a description. So `build_schwab_security_lookup()` ends up with `'enb' → ENB` instead of `'enbridge inc' → ENB`.

However, Schwab's **quote API** (`get_quotes()`) returns `reference.description` with the full company name for all instrument types:
```json
{
  "reference": {
    "description": "ENBRIDGE INC",
    "exchange": "N",
    "exchangeName": "NYSE"
  }
}
```

## Fix

Use Schwab's `get_quotes()` API to fetch `reference.description` (company name) for each position ticker, enrich the security lookup, and add prefix matching for dividend descriptions.

## Changes

### 1. Encapsulated contract — no caller changes needed
**File**: `providers/normalizers/schwab.py`

`get_schwab_security_lookup()` continues to return `dict[str, str] | None` to external callers. No caller updates needed — the enrichment is fully internal to the module.

`get_schwab_security_lookup()` returns the merged `dict[str, str]` with quote-derived company name keys included alongside existing position-derived ticker keys. No side-channels, no TypedDict, no tuple.

`SchwabNormalizer.__init__` identifies prefix-eligible keys using a heuristic: keys that contain a space and are at least 4 characters long are treated as company-name keys eligible for prefix matching. This is pragmatically reliable — quote-derived entries like `"enbridge inc"` always have spaces, while most position-derived entries are single-word tickers like `"enb"`. In the rare case a position name is also multi-word (e.g., DSU's `"blackrock debt strat fd inc com new"`), it simply becomes prefix-eligible too — this is safe and correct behavior since those are legitimate company names.

No changes to any callers or existing tests.

### 2. Enrich `get_schwab_security_lookup()` with quote descriptions
**File**: `providers/normalizers/schwab.py`

Add a helper `_fetch_schwab_descriptions(tickers: list[str]) -> dict[str, str]` that:
- Pre-filters tickers: exclude any containing `:` (e.g., `USD:CASH`, `CUR:GBP`) — not quotable
- Also exclude empty strings and tickers shorter than 1 char
- Deduplicates the filtered list
- Calls `client.get_quotes(filtered_tickers)` (single batch call, ~13 tickers — well within limits)
- Extracts `reference.description` for each ticker
- Returns `{normalized_description: ticker}` map (e.g., `{'enbridge inc': 'ENB'}`)
- Ambiguity handling: if two tickers map to the same normalized description, drop the key and log a warning (same policy as existing `build_schwab_security_lookup`)
- Fail-open: catches all exceptions, logs warning, returns empty dict
- Uses local response parsing (not `_load_json_response` from `schwab_client.py` — keeps module boundary clean)

In `get_schwab_security_lookup()`, after building the position-based lookup:
1. Call `_fetch_schwab_descriptions()` with the position tickers
2. Merge quote-derived entries into the lookup:
   - If a quote key already exists in the position lookup with the **same** ticker → skip (already covered)
   - If a quote key already exists with a **different** ticker → log a warning, don't overwrite (position wins)
   - Otherwise → add the quote entry

### 3. Add prefix matching fallback in `_resolve_income_symbol()`
**File**: `providers/normalizers/schwab.py`

`_resolve_income_symbol()` already accepts `category` as a parameter.

After exact match on `description_map` and `self._schwab_security_lookup` both fail, add a prefix match pass with these safeguards:

- **Only match against multi-word keys** (keys containing a space and length >= 4) — these are quote-derived company names, not ticker-only position keys. This prevents false matches like "CASH IN LIEU..." → USD:CASH
- **Only apply for dividend/reinvest categories** — skip for INTEREST and TAX_WITHHOLDING
- **Matching**: for each qualifying key, check if `description_key.startswith(key + " ")` or `description_key == key` (word-boundary aware)
- **Tie-breaking**: if multiple keys match, pick the longest (most specific). If same-length tie, fall back to unresolved and log warning

This handles "ENBRIDGE INC F" → starts with "enbridge inc " → ENB.

Note: exact matching (passes 1 and 2) continues to run for all categories unchanged.

### 4. Tests
**File**: `tests/providers/test_schwab_normalizer.py`

- Test `_fetch_schwab_descriptions` returns normalized description→ticker map from mock quote response
- Test `_fetch_schwab_descriptions` pre-filters `USD:CASH` and other non-quotable tickers
- Test `_fetch_schwab_descriptions` fail-open on exception (returns empty dict)
- Test `_fetch_schwab_descriptions` drops ambiguous quote descriptions (two tickers → same name)
- Test enriched lookup merges quote descriptions with position names (position keys take precedence)
- Test merge logs warning when quote key conflicts with position key (different ticker)
- Test prefix matching resolves "ENBRIDGE INC F" → ENB via "enbridge inc" key
- Test prefix matching picks longest key on multiple matches
- Test prefix matching does NOT match single-word/short keys
- Test prefix matching does NOT apply for INTEREST category
- Test prefix matching returns fallback when no prefix matches
- Test prefix matching returns fallback on same-length tie

## Key Files
- `providers/normalizers/schwab.py` — main changes (quote enrichment, prefix matching)
- `schwab_client.py` — `get_schwab_client()` (reuse, no changes)
- `tests/providers/test_schwab_normalizer.py` — new tests
- No changes needed to callers (`trading_analysis/analyzer.py`, `run_trading_analysis.py`, `mcp_tools/trading_analysis.py`, `mcp_tools/tax_harvest.py`, `core/realized_performance_analysis.py`)

## Codex Review Feedback (3 rounds)

### Round 1
1. **Prefix matching scope** — restricted to quote-derived keys only and dividend/reinvest categories
2. **Invalid symbols in batch** — pre-filter `USD:CASH` and `:` symbols before `get_quotes()`
3. **Ambiguity handling** — same dedup policy as existing position lookup for quote-derived keys
4. **Latency** — single batch call, fail-open
5. **Key quality** — min length + must contain space to avoid ambiguous single-word prefix matches
6. **Word boundary** — use `startswith(key + " ")` not bare `startswith(key)` to prevent partial-word matches

### Round 2
1. **Return contract** — use typed container instead of ambiguous tuple/dict overloading
2. **Module boundary** — local response parsing instead of importing private `_load_json_response`
3. **`quote_keys` provenance** — defined as keys present in final merged lookup and sourced from quotes
4. **Exact match unchanged** — continues to run for all categories; only prefix matching is category-scoped

### Round 3
1. **Caller-update scope** — encapsulate within normalizer module; don't push TypedDict awareness to callers
2. **Merge conflict logging** — log warning when quote key maps to different ticker than position key
3. **Backward compat** — `SchwabNormalizer.__init__` keeps existing `dict[str, str] | None` param; quote-key identification via heuristic (multi-word = quote-derived)

### Round 4
1. **Contract finalized** — single approach chosen: heuristic identification of prefix-eligible keys (no side-channels, no TypedDict, no caller changes)
2. **`category` parameter** — already exists on `_resolve_income_symbol()`, no change needed
3. **Heuristic reliability** — accepted as pragmatic; multi-word position names (e.g., DSU) becoming prefix-eligible is safe/correct
4. **Batch robustness** — ~13 tickers is well within limits; fail-open covers edge cases; no chunking needed

## Verification
1. Run `python3 -m pytest tests/providers/test_schwab_normalizer.py -v`
2. Test via MCP: `get_trading_analysis(source=schwab)` — confirm `UNRESOLVED_DIVIDEND` is gone, ENB appears in income breakdown
3. Run full suite: `python3 -m pytest tests/providers/ tests/trading_analysis/ -v`
