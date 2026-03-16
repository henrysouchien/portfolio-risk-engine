# Concentration Risk Score Fix Plan

**Status**: TODO
**Created**: 2026-03-15
**Revised**: 2026-03-15 (v2 — addresses Codex review findings)
**Source**: E2E Re-Audit issue N16 — Concentration "100 / Well Diversified" on portfolio with 56% in top 2
**Goal**: Concentration risk score should flag portfolios where cumulative top-N weight is high, not just single-position weight.

---

## Root Cause

`calculate_concentration_risk_loss()` in `portfolio_risk_score.py:455` uses only the **single largest position** weight:

```python
max_position = check_weights.abs().max()
concentration_loss = max_position * crash_scenario * leverage_ratio
```

This misses cumulative concentration. A portfolio with MSFT 30% + AAPL 25.7% (56% in top 2) scores ~80 (safe) because neither individual position exceeds the threshold. But 56% in 2 holdings is clearly concentrated.

**IBKR-only** (few positions, top = 50%+) correctly scores 59. **Combined** (28 positions, top = 30%) incorrectly scores ~100.

Additionally, concentration is computed inline in **3 separate call sites** — all must be updated:
1. `calculate_concentration_risk_loss()` (~line 391) — risk score path
2. `analyze_portfolio_risk_limits()` (~line 760) — compliance/warnings path
3. `calculate_suggested_risk_limits()` (~line 1136, ~line 1207) — suggested limits path

---

## Design

### Approach: Dual-metric concentration (max position + top-N)

Use the **worse of two metrics** to compute concentration loss:

1. **Single-position concentration** (existing): `weight_i × crash_i × leverage`
2. **Top-N concentration** (new): per-position stressed basket with dampening

Take the **maximum** of the two losses as the final concentration_loss.

### Per-position stressed basket (not uniform crash)

The top-N loss must stress each position by its own security-type crash scenario, not multiply the aggregate weight by one crash value. This handles mixed portfolios correctly (e.g., top-3 = equity 30% + fund 25% + etf 15%):

```
top_n_loss = sum(weight_i × crash_i for i in top_N) × leverage × dampening
```

When `security_types` is None, all positions default to equity crash (0.80) — conservative fallback matches existing behavior.

### Why top-3 (not HHI)

- HHI is mathematically rigorous but hard to map to an intuitive loss scenario
- Top-3 cumulative weight is intuitive: "what happens if your 3 biggest bets all crash?"
- Top-3 captures the most common concentration pattern (1-3 large positions dominating)
- Easy to explain to users: "Your top 3 holdings are 68% of your portfolio"

### Dampening factor rationale

- 1 stock crashing 80%: plausible (Enron, Lehman, individual stock event)
- 3 stocks all crashing 80% simultaneously: less likely unless correlated
- Dampening factor of 0.5 means: assume top-3 crash together but at 50% of per-stock severity
- Configurable via `RISK_ANALYSIS_THRESHOLDS["top_n_dampening"]` (not hardcoded)

**Calibration against known portfolios** (with `dampening=0.5`, `max_loss=0.25`):

```
Combined (MSFT 30% + AAPL 25.7% + BXMT 16.3% = 72% in top-3):
  single_loss = 0.30 × 0.80 = 0.24
  top_3_loss  = (0.30+0.257+0.163) × 0.80 × 0.5 = 0.288
  excess_ratio = 0.288 / 0.25 = 1.152
  score ≈ interpolate(1.152, 1.0→75, 1.5→50) ≈ 68   ← flagged as "Fair"

IBKR-only (50%+ in one stock):
  single_loss = 0.50 × 0.80 = 0.40
  top_3_loss  = 0.80 × 0.80 × 0.5 = 0.32
  final = max(0.40, 0.32) = 0.40  ← single dominates, no regression

Well-diversified (20 stocks, max 8%):
  single_loss = 0.08 × 0.80 = 0.064
  top_3_loss  = 0.22 × 0.80 × 0.5 = 0.088
  excess_ratio = 0.088 / 0.25 = 0.352  → score = 100  ← no false positive
```

`dampening=0.5` scores the Combined portfolio at ~68 ("Fair"), clearly flagging the issue without being overly aggressive. `0.6` would yield ~72 which is borderline.

### Shared internal helper

Extract the dual-metric calculation into a helper function `_compute_concentration_loss()` that returns a dict:

```python
def _compute_concentration_loss(
    check_weights: pd.Series,
    leverage_ratio: float,
    security_types: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Compute concentration loss using max(single-position, top-N basket).

    Returns dict with keys:
      loss: float — the final concentration loss value
      top_n_weight: float — cumulative top-N weight (0-1)
      top_n_tickers: list[str] — ticker symbols of top-N positions
      concentration_driver: str — "top_n" or "single_position"
      largest_ticker: str — ticker of largest position
      largest_weight: float — weight of largest position (0-1)
    """
```

All 3 call sites use this helper, ensuring consistency. No mutable `out_metadata` pattern.

---

## Implementation

### Step 1: Add configurable dampening threshold

**File**: `settings.py`

Add to `RISK_ANALYSIS_THRESHOLDS`:

```python
"top_n_dampening": 0.5,  # Multi-position simultaneous crash dampening
"top_n_count": 3,        # Number of top positions to consider
```

### Step 2: Create shared `_compute_concentration_loss()` helper

**File**: `portfolio_risk_engine/portfolio_risk_score.py`

Add new helper function (near existing `_get_single_issuer_weights`):

```python
def _compute_concentration_loss(
    check_weights: pd.Series,
    leverage_ratio: float,
    security_types: Optional[Dict[str, str]] = None,
    portfolio_data=None,
) -> Dict[str, Any]:
    """Compute concentration loss using max(single-position, top-N basket)."""
    if check_weights.empty:
        return {"loss": 0.0, "top_n_weight": 0.0, "top_n_tickers": [],
                "concentration_driver": "single_position",
                "largest_ticker": "", "largest_weight": 0.0}

    top_n_count = RISK_ANALYSIS_THRESHOLDS.get("top_n_count", 3)
    dampening = RISK_ANALYSIS_THRESHOLDS.get("top_n_dampening", 0.5)

    sorted_weights = check_weights.abs().sort_values(ascending=False)
    largest_ticker = sorted_weights.index[0]
    max_position = sorted_weights.iloc[0]

    # Single-position loss (existing logic)
    single_crash = _resolve_crash_scenario(largest_ticker, security_types, portfolio_data)
    single_position_loss = max_position * single_crash * leverage_ratio

    # Top-N per-position stressed basket
    top_n_series = sorted_weights.head(top_n_count)
    top_n_tickers = top_n_series.index.tolist()
    top_n_weight = top_n_series.sum()

    top_n_stressed_sum = sum(
        w * _resolve_crash_scenario(t, security_types, portfolio_data)
        for t, w in top_n_series.items()
    )
    top_n_loss = top_n_stressed_sum * leverage_ratio * dampening

    concentration_loss = max(single_position_loss, top_n_loss)

    return {
        "loss": concentration_loss,
        "top_n_weight": float(top_n_weight),
        "top_n_tickers": top_n_tickers,
        "concentration_driver": "top_n" if top_n_loss > single_position_loss else "single_position",
        "largest_ticker": largest_ticker,
        "largest_weight": float(max_position),
    }
```

Also extract crash scenario resolution into `_resolve_crash_scenario()`:

```python
def _resolve_crash_scenario(
    ticker: str,
    security_types: Optional[Dict[str, str]],
    portfolio_data=None,
) -> float:
    """Resolve crash scenario for a single ticker via security type."""
    if security_types and ticker in security_types:
        security_type = security_types[ticker]
    elif SecurityTypeService and ticker:
        try:
            type_lookup = SecurityTypeService.get_security_types([ticker], portfolio_data)
            security_type = type_lookup.get(ticker, "equity")
        except Exception:
            security_type = "equity"
    else:
        security_type = "equity"

    if security_type not in SECURITY_TYPE_CRASH_MAPPING:
        security_type = "equity"
    return WORST_CASE_SCENARIOS[SECURITY_TYPE_CRASH_MAPPING[security_type]]
```

### Step 3: Refactor `calculate_concentration_risk_loss()` to use helper

**File**: `portfolio_risk_engine/portfolio_risk_score.py` (~line 391-481)

Replace the function body to delegate to `_compute_concentration_loss()`:

```python
def calculate_concentration_risk_loss(
    summary, leverage_ratio, portfolio_data=None, security_types=None,
) -> float:
    weights = summary["allocations"]["Portfolio Weight"]
    check_weights = _get_single_issuer_weights(weights, security_types)
    result = _compute_concentration_loss(check_weights, leverage_ratio, security_types, portfolio_data)
    return result["loss"]
```

Return type stays `float` — no signature change, fully backward compatible.

### Step 4: Update `calculate_portfolio_risk_score()` to surface metadata

**File**: `portfolio_risk_engine/portfolio_risk_score.py` (~line 1510)

Call `_compute_concentration_loss()` directly instead of `calculate_concentration_risk_loss()`:

```python
weights = summary["allocations"]["Portfolio Weight"]
check_weights = _get_single_issuer_weights(weights, security_types)
conc_result = _compute_concentration_loss(check_weights, leverage_ratio, security_types, portfolio_data)
concentration_loss = conc_result["loss"]
```

Add metadata to the return dict under `details`:

```python
"details": {
    ...existing fields...,
    "concentration_metadata": {
        "top_n_weight": round(conc_result["top_n_weight"] * 100, 1),
        "top_n_tickers": conc_result["top_n_tickers"],
        "concentration_driver": conc_result["concentration_driver"],
        "largest_ticker": conc_result["largest_ticker"],
        "largest_weight": round(conc_result["largest_weight"] * 100, 1),
    },
}
```

### Step 5: Update `analyze_portfolio_risk_limits()` (~line 760)

**File**: `portfolio_risk_engine/portfolio_risk_score.py`

Replace inline single-position check with helper-aware logic:

```python
# Current (line 760-780):
check_weights = _get_single_issuer_weights(weights, security_types)
max_weight = check_weights.abs().max()

# Updated:
check_weights = _get_single_issuer_weights(weights, security_types)
conc_result = _compute_concentration_loss(check_weights, 1.0, security_types)
max_weight = conc_result["largest_weight"]
top_n_weight = conc_result["top_n_weight"]

# Flag both single-position and top-N concentration:
if max_weight > weight_limit:
    risk_factors.append(f"High concentration: {max_weight:.1%} vs {weight_limit:.1%} limit")
    ...
elif top_n_weight > weight_limit * 2:  # Top-3 at 2× single limit is concentrated
    risk_factors.append(f"High cumulative concentration: top {len(conc_result['top_n_tickers'])} positions = {top_n_weight:.1%}")
    recommendations.append("Reduce position sizes in largest holdings to improve diversification")
elif max_weight > weight_limit * concentration_warning_ratio:
    risk_factors.append(f"High concentration: {max_weight:.1%} in single position")
    ...
```

### Step 6: Update `calculate_suggested_risk_limits()` (~line 1136, ~1207)

**File**: `portfolio_risk_engine/portfolio_risk_score.py`

Replace inline concentration calculations with helper:

```python
# At ~line 1136 (concentration limit section):
conc_result = _compute_concentration_loss(concentration_weights, current_leverage, security_types)
max_position = conc_result["largest_weight"]
concentration_loss_unleveraged = conc_result["loss"] / current_leverage if current_leverage else 0

# Suggested limit based on single-position (user-actionable):
suggested_max_position = max_loss / (concentration_crash * current_leverage)

suggestions["concentration_limit"] = {
    "current_max_position": max_position,
    "suggested_max_position": suggested_max_position,
    "needs_reduction": max_position > suggested_max_position,
    "top_n_weight": round(conc_result["top_n_weight"] * 100, 1),
    "top_n_tickers": conc_result["top_n_tickers"],
}

# At ~line 1207 (leverage limit section):
# Use the dual-metric loss instead of single-position:
concentration_loss = conc_result["loss"] / current_leverage  # unleveraged
worst_unleveraged_loss = max(worst_unleveraged_loss, concentration_loss)
```

### Step 7: Update `risk_score_flags.py` for concentration detail

**File**: `core/risk_score_flags.py`

Add a concentration-specific flag when the component score is weak AND metadata is available:

```python
# After the generic component_scores loop:
conc_meta = snapshot.get("concentration_metadata", {})
if conc_meta:
    driver = conc_meta.get("concentration_driver")
    conc_score = component_scores.get("concentration_risk", 100)
    if isinstance(conc_score, (int, float)) and conc_score < 75:
        if driver == "top_n":
            tickers = ", ".join(conc_meta.get("top_n_tickers", []))
            weight = conc_meta.get("top_n_weight", 0)
            flags.append({
                "flag": "concentration_top_n",
                "severity": "warning" if conc_score < 60 else "info",
                "message": f"Top positions ({tickers}) represent {weight}% of portfolio",
            })
        else:
            ticker = conc_meta.get("largest_ticker", "?")
            weight = conc_meta.get("largest_weight", 0)
            flags.append({
                "flag": "concentration_single",
                "severity": "warning" if conc_score < 60 else "info",
                "message": f"Largest position ({ticker}) is {weight}% of portfolio",
            })
```

No frontend adapter changes needed — the new flags use the existing `{flag, severity, message}` contract.

### Step 7b: Update `RiskScoreResult.get_agent_snapshot()` to lift concentration metadata

**File**: `core/result_objects/risk.py` (~line 1968)

The flag function `generate_risk_score_flags()` receives the agent snapshot dict, NOT the raw `risk_score.details`. Currently `get_agent_snapshot()` only lifts `raw_score`, `compliance_penalty_points`, and `compliance_ceiling_applied` from `details`. We must also lift `concentration_metadata`:

```python
# In get_agent_snapshot(), after existing details extraction (~line 1975-1981):
"concentration_metadata": (
    details.get("concentration_metadata", {}) if isinstance(details, dict) else {}
),
```

Then in Step 7 (flags), read from `snapshot.get("concentration_metadata", {})` instead of `snapshot.get("details", {}).get("concentration_metadata", {})`.

### Step 8: Tests

**File**: `tests/core/test_portfolio_risk_score_fund_weight_exemption.py` (extend existing)

**New test cases:**

1. **Single large position preserved** — 50% in one equity: `_compute_concentration_loss()` returns `concentration_driver == "single_position"`, loss matches existing behavior
2. **Top-3 concentrated equities** — 30% + 25% + 20% = 75%: driver = "top_n", loss > single_position_loss
3. **Well diversified** — 20 positions, max 8%: top-3 sum ≈ 22%, loss stays below safe threshold
4. **Mixed security types in top-3** — equity 30% + fund 25% + etf 15%: per-position stressed, not uniform crash
5. **Fewer than 3 positions after filtering** — 2 equities + 1 ETF (filtered): top-N uses available positions only
6. **All diversified fallback** — all fund/ETF portfolio: `_get_single_issuer_weights` returns raw weights, top-N applies with fund crash scenarios
7. **Edge case: exactly 3 equal positions** — 33.3% × 3: verify both metrics, driver should be top_n
8. **`calculate_concentration_risk_loss()` backward compat** — existing tests still pass, return type is float
9. **`analyze_portfolio_risk_limits()` alignment** — top-N concentrated portfolio triggers risk_factor warning
10. **`calculate_suggested_risk_limits()` alignment** — suggested limits include top_n_weight, leverage limit uses dual-metric loss
11. **Snapshot propagation** (`tests/core/test_risk_score_agent_snapshot.py`) — `get_agent_snapshot()` includes `concentration_metadata` with expected keys (`top_n_weight`, `top_n_tickers`, `concentration_driver`, `largest_ticker`, `largest_weight`)
12. **Flag emission: top_n driver** (`tests/core/test_risk_score_flags.py`) — when snapshot has `concentration_metadata.concentration_driver == "top_n"` and concentration_risk score < 75, `concentration_top_n` flag is emitted with correct message
13. **Flag emission: single_position driver** — when driver == "single_position" and score < 75, `concentration_single` flag is emitted
14. **Flag not emitted when score is safe** — when concentration_risk score >= 75, no concentration-specific flag is emitted

### Step 9: Verify with real data

After implementing, run risk score on:
- **Combined portfolio** (MSFT 30%, AAPL 25.7%, etc.): should score ~65-70 (Fair), not 100
- **IBKR-only** (top = 50%+): should still score ~59 or lower (no regression)
- **Well-diversified 20-stock portfolio**: should still score 80+ (no false positives)

---

## Files Changed

| File | Change | Effort |
|------|--------|--------|
| `settings.py` | Add `top_n_dampening`, `top_n_count` to thresholds | Trivial |
| `portfolio_risk_engine/portfolio_risk_score.py` | Add `_resolve_crash_scenario()`, `_compute_concentration_loss()` helper; refactor 3 call sites | Medium |
| `core/result_objects/risk.py` | Lift `concentration_metadata` into agent snapshot | Trivial |
| `core/risk_score_flags.py` | Add concentration-specific flag with top-N detail | Quick |
| `tests/core/test_portfolio_risk_score_fund_weight_exemption.py` | Add 10 concentration calculation test cases | Medium |
| `tests/core/test_risk_score_agent_snapshot.py` | Add snapshot propagation test | Quick |
| `tests/core/test_risk_score_flags.py` | Add 3 flag emission tests (top_n, single, safe) | Quick |

---

## Risk / Backwards Compatibility

- **Score changes**: All portfolios with significant top-3 concentration will see lower (worse) scores. This is intentional — the old scores were misleadingly optimistic.
- **Alert changes**: More concentration alerts will fire in `analyze_portfolio_risk_limits()`. This is correct behavior.
- **Additive API fields**: `concentration_metadata` added to `details` dict. No existing fields removed or renamed. Frontend adapter already passes `details` through — no adapter changes needed.
- **New flag types**: `concentration_top_n` and `concentration_single` flags added to `risk_score_flags.py`. These use the existing `{flag, severity, message}` contract. No new adapter work.
- **Return type preserved**: `calculate_concentration_risk_loss()` still returns `float`. No signature change.
- **Dampening factor configurable**: Via `RISK_ANALYSIS_THRESHOLDS["top_n_dampening"]`, adjustable without code change.
- **Existing test contracts**: All existing tests in `test_portfolio_risk_score_fund_weight_exemption.py` must still pass — the `calculate_concentration_risk_loss()` return values will change but existing assertions should be updated to match the new (correct) behavior.
