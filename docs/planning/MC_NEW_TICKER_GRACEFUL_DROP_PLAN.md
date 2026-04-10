# Monte Carlo — Graceful Drop for Unknown Tickers

## Problem

When What-If adds a new ticker (e.g. AGG via `delta_changes`), `resolved_weights` includes it. Passing those weights to Monte Carlo causes a 500 error: `"resolved_weights contains tickers not in covariance matrix: AGG"`. The covariance matrix is built from historical returns, which only covers the original portfolio's tickers. New tickers have no return history in the current risk run, so they cannot appear in the matrix.

## Root Cause

`_validate_resolved_weights()` (`monte_carlo.py:99-142`) treats missing-from-covariance tickers as a hard error (line 136-138). This is overly strict for the What-If -> MC exit ramp, where the user's hypothetical weights legitimately contain tickers absent from the portfolio's covariance universe.

## Downstream behavior — NOT fully graceful

`_resolve_tickers_and_covariance()` (line 145-167) handles **partial** overlap correctly — it intersects weights with the covariance matrix and only uses overlapping tickers (line 157). However, if **ALL** override tickers are missing from the covariance matrix, line 157 falls back to `candidate_tickers` (the full covariance universe) via the `or` clause, which would simulate the wrong portfolio entirely. The validator must preserve the all-missing error to prevent this.

## Fix Strategy

Change `_validate_resolved_weights()` from raise-on-missing to warn-and-drop for partial overlap. Do NOT renormalize — let `_resolve_weight_vector()` (line 170-192) handle normalization, as it already handles zero-net, negative, and hedged weight vectors correctly. Adding renormalization in the validator would double-normalize and could break hedged/net-zero overrides.

1. Remove the `ValueError` for `missing_tickers` (partial overlap case)
2. Drop those tickers from `normalized_weights` (they already are — the `continue` on line 121 skips them)
3. Return the dropped ticker list alongside the weights so the caller can surface it
4. Add a warning string to `distribution_metadata["warnings"]` via the existing `warnings` list on the result dict
5. Add a dedicated `tickers_dropped` flag in `monte_carlo_flags.py`, and **exclude** dropped-ticker warnings from the generic `engine_warnings` loop to prevent duplicate flags

Do NOT expand the covariance matrix — that would require fetching historical data mid-simulation, which is infeasible and architecturally wrong.

## Implementation Steps

### Step 1: `portfolio_risk_engine/monte_carlo.py:99-142` — Validator change

Change `_validate_resolved_weights()` return type from `Dict[str, float]` to `tuple[Dict[str, float], list[str]]`. Remove lines 136-138 (the `ValueError` raise for `missing_tickers`). After the loop, if `missing_tickers` is non-empty: log at WARNING level. Do NOT renormalize — return `normalized_weights` as-is with the missing tickers already excluded by the `continue` on line 121. `_resolve_weight_vector()` (line 170) handles all normalization including zero-net and negative weights. If ALL tickers were missing (empty `normalized_weights` after the loop), still raise `ValueError` — the existing check on line 139-140 handles this.

**Numeric validation BEFORE universe check (HIGH)**: The current loop order is: (1) normalize ticker, (2) universe membership check with `continue` on miss, (3) numeric validation. This means a malformed weight value (e.g. `"oops"`, `None`) on a ticker that is NOT in the covariance universe gets silently dropped — the `continue` at line 121 skips the `float()` cast and `isfinite` check at lines 122-131. Fix: restructure the loop to validate ALL values numerically BEFORE checking universe membership. The new loop body order must be:

1. Normalize ticker (uppercase, strip) — lines 115-117, unchanged
2. Numeric validation (`float()` cast + `isfinite` check) — move lines 122-131 here, BEFORE the universe check
3. Universe membership check — if not in universe, append to `missing_tickers` and `continue` (line 119-121, moved after numeric validation)
4. Assign to `normalized_weights` — line 132, unchanged

This guarantees that `{"AAPL": 0.6, "NVDA": "oops"}` raises `ValueError("Invalid resolved weight for ticker 'NVDA': oops")` even when NVDA is not in the covariance matrix. Every input value is type-checked regardless of whether its ticker survives the universe filter.

**Net-sum sign guard (computed from NORMALIZED weights, not raw input) (MEDIUM)**: After dropping missing tickers, check whether the sign of the net weight sum flipped. The engine uppercases tickers and overwrites duplicate normalized keys (last-write-wins at line 132), so `original_net` must be computed from the normalized weights AFTER the loop completes but conceptually BEFORE dropping missing tickers. Specifically: compute `all_valid_weights` — a dict that includes BOTH the surviving `normalized_weights` entries AND the numeric values for `missing_tickers` entries. To do this, collect the validated numeric value for every ticker (both universe-hit and universe-miss) in a temporary `all_normalized: Dict[str, float]` dict during the loop, then compute `original_net = sum(all_normalized.values())`. This avoids the raw-input mismatch: e.g. `{"aapl": 0.6, "AAPL": -0.7, "NVDA": 0.2}` raw sum = 0.1, but after normalization `all_normalized = {"AAPL": -0.7, "NVDA": 0.2}` and `original_net = -0.5` — which correctly reflects the post-dedup intent.

Compute `surviving_net = sum(normalized_weights.values())` (universe-hit entries only). If `original_net` and `surviving_net` have opposite signs (i.e. `original_net * surviving_net < 0`), raise `ValueError` — dropping those tickers inverted the portfolio's long/short intent, so the simulation would be meaningless. Example: `AAPL=0.2, MSFT=-0.5, NVDA=0.4` → normalized net=+0.1, drop NVDA → surviving net=-0.3, sign flipped → error. This guard prevents `_resolve_weight_vector()` from normalizing a net-negative survivor set by its sum and flipping all signs (line 190: `weight_vector / total`). Skip the guard when `abs(original_net) < 1e-12` (net-zero/hedged portfolios have no sign to preserve). Error message: `"Dropping {tickers} from resolved_weights would flip the portfolio's net long/short direction; cannot simulate"`.

**Concrete loop pseudocode** (replaces lines 111-132):
```python
normalized_weights: Dict[str, float] = {}
all_normalized: Dict[str, float] = {}  # both universe-hit and universe-miss
invalid_tickers: list[str] = []
missing_tickers: list[str] = []
for ticker, raw_value in resolved_weights.items():
    normalized_ticker = str(ticker or "").strip().upper()
    if not normalized_ticker:
        invalid_tickers.append(str(ticker))
        continue
    # Numeric validation FIRST — catches bad values regardless of universe membership
    try:
        numeric_value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid resolved weight for ticker '{normalized_ticker}': {raw_value}"
        ) from exc
    if not math.isfinite(numeric_value):
        raise ValueError(
            f"Invalid resolved weight for ticker '{normalized_ticker}': {raw_value}"
        )
    all_normalized[normalized_ticker] = numeric_value  # last-write-wins for case dupes
    # Universe membership check AFTER numeric validation
    if universe and normalized_ticker not in universe:
        missing_tickers.append(normalized_ticker)
        continue
    normalized_weights[normalized_ticker] = numeric_value
```

**Deduplicate `missing_tickers`**: The existing error path dedupes via `set()` (line 137), but with warn-and-drop the list is returned to callers. Apply `sorted(set(missing_tickers))` before returning, so duplicate input keys like `{"agg": ..., "AGG": ...}` (both normalize to `AGG`) produce a single entry in `dropped_tickers`.

Return `(normalized_weights, missing_tickers)`.

### Step 2: `portfolio_risk_engine/monte_carlo.py:591-594` — Call site update + all result paths

Update the call site. Unpack the new return: `raw_weights, dropped_tickers = _validate_resolved_weights(...)`. Initialize `dropped_tickers = []` at the top of the resolved-weights branch so it is available to all downstream result construction paths.

**Main result path (~line 718)**: After the result dict is built, if `dropped_tickers` is non-empty: append a warning string to the warnings list: `f"Dropped {len(dropped_tickers)} ticker(s) not in covariance matrix: {', '.join(sorted(dropped_tickers))}"`. Add `"dropped_tickers": sorted(dropped_tickers)` to the result dict. When `dropped_tickers` is empty, still add `"dropped_tickers": []` for consistent shape.

**`_build_flat_result()` path (line 378, called at ~line 649)**: Add `dropped_tickers: Optional[list[str]] = None` parameter to `_build_flat_result()`. Include `"dropped_tickers": list(dropped_tickers or [])` in its returned dict. Update the call site at line 649 to pass `dropped_tickers=dropped_tickers`. This ensures the flat/degenerate result (empty tickers, zero covariance) also carries the field.

**All result construction paths must include `dropped_tickers`**. There are exactly three: (1) `_build_flat_result` at line 649, (2) the main dict at line 718, and (3) `_build_flat_result` is the only helper — no other helper builds result dicts. Verify at implementation time that no additional result construction paths exist.

### Step 3: `core/result_objects/monte_carlo.py` — Result object field

Add field `dropped_tickers: List[str] = field(default_factory=list)` to `MonteCarloResult` (after `warnings`). Wire in `from_engine_output()`: `dropped_tickers=list(data.get("dropped_tickers", []) or [])`. Include in:
- `get_agent_snapshot()` under `conditioning` dict: `"dropped_tickers": self.dropped_tickers`
- `get_summary()`: `"dropped_tickers": self.dropped_tickers`
- `to_api_response()`: `"dropped_tickers": self.dropped_tickers`

### Step 4: `core/monte_carlo_flags.py` — Dedicated flag with dedup

Add a `tickers_dropped` flag. Read `dropped_tickers` from `snapshot["conditioning"]["dropped_tickers"]`. If non-empty, emit a warning flag: `"Simulation excluded {n} ticker(s) not in covariance matrix: {tickers}. Weights were redistributed by the simulation engine."`.

To prevent duplicate flags: modify the `engine_warnings` loop (line 159) to skip warning strings that start with `"Dropped "` (the prefix from step 2). This way the dropped-ticker event produces exactly one flag (`tickers_dropped`), not both `tickers_dropped` AND `engine_warnings`.

### Step 5: `tests/test_monte_carlo.py:642-650` — Update existing test

Rename `test_resolved_weights_missing_ticker_raises` to `test_resolved_weights_missing_ticker_dropped`. Assert it no longer raises. Assert the returned result contains `dropped_tickers == ["NVDA"]` and a corresponding warning string containing "Dropped 1 ticker(s)". Assert remaining weight for AAPL is present (do not assert a specific renormalized value — `_resolve_weight_vector` handles normalization downstream). The fixture `_build_three_asset_result()` builds AAPL/MSFT/TLT, and the test passes `resolved_weights={"AAPL": 0.6, "NVDA": 0.4}` — NVDA is not in the covariance universe so it gets dropped.

### Step 6: `tests/test_monte_carlo.py` — All-missing test + sign-flip + dedup + numeric-before-universe tests

**All-missing test**: Add new test: all tickers missing from covariance still raises `ValueError`. Use `resolved_weights={"NVDA": 0.5, "XYZ": 0.5}` with `_build_three_asset_result()` (covariance covers AAPL/MSFT/TLT). Assert `ValueError` with match "resolved_weights must contain at least one valid ticker".

**Sign-flip test**: Add new test: dropping tickers that flip the net-sum sign raises `ValueError`. Use `resolved_weights={"AAPL": 0.2, "MSFT": -0.5, "NVDA": 0.4}` with `_build_three_asset_result()` (covariance covers AAPL/MSFT/TLT but NOT NVDA). Normalized (post-dedup) net = +0.1, surviving net = -0.3 — signs differ. Assert `ValueError` with match "would flip the portfolio's net long/short direction".

**Sign-flip OK for net-zero**: Add new test: hedged/net-zero portfolios skip the sign guard. Use `resolved_weights={"AAPL": 0.5, "MSFT": -0.5, "NVDA": 0.0}` → normalized net = 0.0, which is below the 1e-12 threshold. Assert no error — the guard is skipped for near-zero original net.

**Sign-flip uses normalized net, not raw**: Add new test verifying the sign guard uses post-normalization net, not raw input sum. Use `resolved_weights={"aapl": 0.6, "AAPL": -0.7, "NVDA": 0.2}` with `_build_three_asset_result()` (covariance covers AAPL/MSFT/TLT but NOT NVDA). Raw sum = 0.6 + (-0.7) + 0.2 = 0.1 (positive). After normalization (last-write-wins): `all_normalized = {"AAPL": -0.7, "NVDA": 0.2}`, so `original_net = -0.5`. Surviving (universe-hit only): `{"AAPL": -0.7}`, `surviving_net = -0.7`. Both negative — same sign, so the guard should NOT trip. Assert no `ValueError` (graceful drop of NVDA). If the implementation incorrectly used raw input sum (+0.1), it would see a sign flip from +0.1 to -0.7 and erroneously raise.

**Dedup test**: Add new test: duplicate normalized tickers produce a single `dropped_tickers` entry. Use `resolved_weights={"agg": 0.3, "AGG": 0.3, "AAPL": 0.4}` — both `agg` and `AGG` normalize to `AGG`, which is not in the covariance universe. Assert `dropped_tickers == ["AGG"]` (one entry, not two).

**Numeric validation before universe check**: Add new test: malformed weight value on a missing-from-universe ticker still raises `ValueError`. Use `resolved_weights={"AAPL": 0.6, "NVDA": "oops"}` with `_build_three_asset_result()` (NVDA is not in the covariance universe). Assert `ValueError` with match "Invalid resolved weight for ticker 'NVDA': oops". This verifies that numeric validation runs BEFORE the universe membership check — if validation were still after the `continue`, the "oops" value would be silently skipped.

### Step 7: `tests/test_monte_carlo_flags.py` — Dedicated flag test

Note: file is at `tests/test_monte_carlo_flags.py` (NOT `tests/core/test_monte_carlo_flags.py`).

Add test: pass a snapshot with `conditioning` containing `dropped_tickers: ["AGG"]`. Assert a flag with `type == "tickers_dropped"` and `severity == "warning"` is generated.

Add test: same snapshot with a warning string starting with `"Dropped "` in `warnings`. Assert that the `engine_warnings` loop does NOT produce a flag for that warning string (dedup guard from step 4).

### Step 8: `tests/test_monte_carlo_result.py` — Result object tests

Update `_engine_output()` fixture to include `"dropped_tickers": []` in the base output and a variant with `["AGG"]` for dropped-ticker tests.

Update `test_get_agent_snapshot_matches_documented_shape` (line 99): add `"dropped_tickers": []` to the expected `conditioning` dict assertion.

Add new tests:
- `test_from_engine_output_includes_dropped_tickers`: build with `dropped_tickers=["AGG"]`, assert `result.dropped_tickers == ["AGG"]`
- `test_dropped_tickers_in_agent_snapshot`: build with `dropped_tickers=["AGG"]`, assert `snapshot["conditioning"]["dropped_tickers"] == ["AGG"]`
- `test_dropped_tickers_in_summary`: assert `summary["dropped_tickers"] == ["AGG"]`
- `test_dropped_tickers_in_api_response`: assert `payload["dropped_tickers"] == ["AGG"]`
- `test_dropped_tickers_defaults_to_empty_list`: build without `dropped_tickers` key, assert `result.dropped_tickers == []`

## Testing

- **Unit**: Steps 5-8 above (minimum 14 tests: 1 updated, 1 all-missing, 1 sign-flip error, 1 sign-flip net-zero OK, 1 sign-flip normalized-net-not-raw, 1 dedup, 1 numeric-validation-before-universe, 2 flag tests, 5 result-object tests)
- **Integration**: Manually run What-If with `delta_changes` adding AGG, then chain to MC via `resolved_weights` — confirm 200 response with `dropped_tickers: ["AGG"]` in result and a `tickers_dropped` warning flag (no duplicate `engine_warnings` flag for the same event)
- **Regression**: Existing MC tests must still pass (no behavioral change for weights fully within the covariance universe)

## Risks & Rollback

- **Low risk**: The change relaxes a validation that is too strict. For partial overlap, `_resolve_tickers_and_covariance()` correctly intersects weights with the covariance matrix. The all-missing case remains a hard error.
- **Numeric validation ordering**: Numeric validation (type check, NaN/inf) now runs BEFORE the universe membership check, so malformed values on missing-from-universe tickers are caught instead of silently dropped. This closes a hole where `{"AAPL": 0.6, "NVDA": "oops"}` would succeed if NVDA was not in the covariance matrix.
- **Sign guard correctness**: The sign-flip guard computes `original_net` from the post-normalization `all_normalized` dict (after uppercasing + last-write-wins dedup), NOT from the raw `resolved_weights.values()`. This prevents false triggers when case-duplicate keys have different signs (e.g. `{"aapl": 0.6, "AAPL": -0.7}` — raw sum is -0.1 but normalized dict only contains `AAPL: -0.7`).
- **Normalization safety**: By NOT renormalizing in the validator, we avoid interfering with `_resolve_weight_vector()`'s handling of hedged/net-zero/negative weight vectors. This is critical for short position support (F12). The net-sum sign guard (Step 1) catches the dangerous case where dropping long-leg tickers leaves a net-negative survivor set — `_resolve_weight_vector()` line 190 would divide by the negative sum and flip all signs, turning longs into shorts. The guard converts this to a hard error instead of a silently inverted simulation.
- **Edge case**: If the dropped tickers represent a large weight fraction (e.g. 80%), the simulation may be misleading because `_resolve_weight_vector` will redistribute all weight to the remaining tickers. The warning flag + `dropped_tickers` list lets the agent/frontend surface this. A future enhancement could add a threshold flag (e.g. "dropped tickers represented >30% of portfolio weight").
- **All-missing edge case**: If ALL override tickers are missing, the validator raises `ValueError` (preserved). Without this guard, `_resolve_tickers_and_covariance()` line 157 would fall back to the full covariance universe (`candidate_tickers`), simulating the wrong portfolio entirely.
- **Rollback**: Revert the single commit. The only behavioral change is ValueError -> warn-and-continue for partial overlap, so reverting restores the original strict validation.
