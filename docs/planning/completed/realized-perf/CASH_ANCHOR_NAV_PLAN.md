# Cash Anchor Fix (Issue 1 + Issue 4)

> **Status:** IMPLEMENTED (cash anchor is live and default ON).
> Superseded by `IBKR_NAV_GAP_FIX_PLAN.md` for remaining cash definition
> mismatch and replay discrepancy issues.

## Context

The realized performance engine reconstructs NAV as `positions_value + replayed_cash`, but seeds cash replay at $0. For margin accounts (like IBKR), actual cash is deeply negative (-$8,727 to -$11,097). This inflates NAV by ~$9-15k and distorts every monthly TWR calculation.

**Validation**: A flat offset (observed_end_cash - replayed_end_cash) applied to all snapshots produces cash values within $37 of official IBKR at Dec 2025. This confirms the offset IS mathematically equivalent to seeding the replay at the correct starting value.

**Known limitation**: Applying the anchor alone worsens the headline return (-8.5% → ~-11.24%) because the smaller NAV denominator amplifies position losses from synthetic positions. This is expected and correct — the cash fix is a prerequisite for fixing synthetic position valuation (Issue 2), which is a separate task.

**Known limitation (inferred flows)**: The flat offset is applied post-hoc to cash snapshots. It does NOT re-run `derive_cash_and_external_flows()`. This means the inferred external flow logic (line 2032: inject cash when `cash < 0`) operates on the original $0-seeded replay. With correct negative starting cash, some of those inferred injections would not fire. This is acceptable because: (a) the flag defaults OFF, (b) inferred flows are a fallback mechanism that will be refined separately under Issue 2, and (c) provider-first mode (`REALIZED_USE_PROVIDER_FLOWS=true`) disables inferred adjustments for authoritative partitions.

## Plan

### 1. Add feature flag (default OFF)

**`settings.py` ~line 131:**
```python
REALIZED_CASH_ANCHOR_NAV = os.getenv("REALIZED_CASH_ANCHOR_NAV", "false").lower() == "true"
```

Default false — opt-in until synthetic position fixes (Issue 2) are also done.

### 2. Import flag + add guard

**`core/realized_performance_analysis.py`:**
- Import `REALIZED_CASH_ANCHOR_NAV` from settings (~line 62)
- Compute shared boolean: `anchor_active = bool(REALIZED_CASH_ANCHOR_NAV and cash_anchor_available)` after `observed_cash_end` is computed (~line 3780). Use this single boolean everywhere to avoid divergence.
- Guard the offset computation (~lines 4755, 4849): set offset to 0.0 when no observed cash found
- Add warning when flag is on but no observed cash

### 3. Resolve effective cash snapshots once (not per-site)

Rather than swapping inside 4 individual `compute_monthly_nav()` calls, resolve the effective snapshots once at the top of the computation block (~line 4793):

```python
# Resolve effective cash snapshots based on anchor flag
effective_cash_snapshots = cash_snapshots_anchored if anchor_active else cash_snapshots
effective_observed_cash_snapshots = observed_cash_snapshots_anchored if anchor_active else observed_cash_snapshots
```

Then use `effective_cash_snapshots` / `effective_observed_cash_snapshots` in ALL downstream consumers:
- Synthetic-enhanced monthly NAV (~line 4803)
- Synthetic-enhanced daily NAV (~line 4813)
- Observed-only monthly NAV (~line 4866)
- Observed-only daily NAV (~line 4876)
- `monthly_cash_series` computation (~line 4888) — use `effective_cash_snapshots`
- `observed_only_monthly_cash_series` computation (~line 4889) — use `effective_observed_cash_snapshots`
- `monthly_nav_components` (~line 4904) — already correct because it uses `monthly_nav` + `monthly_cash_series`, both of which now use the effective snapshots

This ensures NAV, cash series, and component decomposition are ALL consistent. The delta-based `monthly_nav_cash_anchored` (line 4898) and `monthly_nav_components_cash_anchored` (line 4908) continue to exist as diagnostic variants — they are always computed from the unanchored baseline regardless of the flag, so there is no double-application risk.

### 4. Update diagnostic flags (2 sites)

Change `"cash_anchor_applied_to_nav": False` → `anchor_active` at ~lines 5502 and 5581. Both sites use the same shared boolean from step 2.

### 5. Add `cash_anchor_available` field to `RealizedMetadata`

**`core/result_objects/realized_performance.py` ~line 148:** New bool field, wired in `from_dict`/`to_dict`.

**`core/realized_performance_analysis.py`:** Set `cash_anchor_available` in the `realized_metadata` dict at both build sites (~lines 5493, 5571), alongside the existing `cash_anchor_applied_to_nav` field.

**Aggregated mode** (~line 6593): `realized_metadata = dict(first_meta)` copies from the first account. The existing aggregation loop uses `meta_dicts` (the list of per-account metadata dicts, built at ~line 6253). For `cash_anchor_available` and `cash_anchor_applied_to_nav`, override with `any()` across all account results — anchor is available/applied if ANY account had it. Add to the `realized_metadata.update({...})` block at ~line 6594:
```python
"cash_anchor_available": any(
    m.get("cash_anchor_available", False) for m in meta_dicts
),
"cash_anchor_applied_to_nav": any(
    m.get("cash_anchor_applied_to_nav", False) for m in meta_dicts
),
```

### 6. Tests

**Engine-level tests** in `tests/core/test_realized_cash_anchor.py` (new file):
- Build minimal position timeline + cash snapshots with known offset
- Flag OFF → `compute_monthly_nav()` receives unanchored cash, returns unanchored NAV
- Flag ON + observed cash → `compute_monthly_nav()` receives anchored cash, NAV shifts by expected offset, component decomposition (positions_value + cash = NAV) is internally consistent
- Flag ON + no observed cash → offset is 0.0, warning emitted, NAV unchanged
- Verify `monthly_cash_series` and `monthly_nav_components` use the same cash path (no double-shift)

**MCP-layer tests** in `tests/mcp_tools/test_performance.py` (existing):
- Flag OFF → response contains `cash_anchor_applied_to_nav=False`
- Flag ON → response contains `cash_anchor_applied_to_nav=True`
- These validate response shaping only (engine is stubbed)

## Files Modified

| File | Change |
|------|--------|
| `settings.py` | Add `REALIZED_CASH_ANCHOR_NAV` flag |
| `core/realized_performance_analysis.py` | Import, `anchor_active` boolean, effective cash resolution, 4 NAV call swaps, cash series swaps, 2 diagnostic flag updates, 2 metadata field additions, aggregated mode override |
| `core/result_objects/realized_performance.py` | Add `cash_anchor_available` field |
| `tests/core/test_realized_cash_anchor.py` | Engine-level tests (4 cases) |
| `tests/mcp_tools/test_performance.py` | MCP-layer tests (2 cases) |

## Verification

1. Run with flag OFF → return should be unchanged at -8.5%
2. Run with `REALIZED_CASH_ANCHOR_NAV=true` → return changes, `cash_anchor_applied_to_nav=True` in output
3. Check diagnostics: `cash_anchor_offset_usd` should be ~-8,495, anchored end cash should match observed
4. Verify component consistency: for each month-end, `positions_value_usd + cash_value_usd == nav_usd` in both `monthly_nav_components` and `monthly_nav_components_cash_anchored`
5. Run engine tests: `python -m pytest tests/core/test_realized_cash_anchor.py -x`
6. Run existing test suite: `python -m pytest tests/mcp_tools/test_performance.py -x`

## Reference

- Working doc: `docs/planning/performance-actual-2025/IBKR_REALIZED_RECON_WORKING_DOC_2026-03-04.md`
- Issues 1-8 cataloged there with full diagnosis and evidence
