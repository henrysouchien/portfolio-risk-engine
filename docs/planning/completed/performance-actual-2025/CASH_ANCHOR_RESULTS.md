# Cash Anchor NAV — Results & Changes Log

**Plan**: `docs/planning/completed/CASH_ANCHOR_NAV_PLAN.md`
**Working Doc**: `docs/planning/performance-actual-2025/IBKR_REALIZED_RECON_WORKING_DOC_2026-03-04.md`
**Date Started**: 2026-03-04

## Baseline (Pre-Change)

| Metric | Value |
|--------|-------|
| Engine headline return | -8.5% |
| IBKR official TWR | +0.29% |
| Cash replay end (unanchored) | ~$0 seeded |
| Observed cash end (IBKR) | -$8,727 to -$11,097 |
| Cash anchor offset | ~-$8,495 |
| Anchored cash vs IBKR Dec 2025 | Within $37 |

## Changes

### Step 1: Feature flag
- [x] `settings.py` — `REALIZED_CASH_ANCHOR_NAV` (default OFF)
- Commit: _pending_

### Step 2: Engine — anchor_active boolean + guard
- [x] `core/realized_performance_analysis.py` — import flag, compute `anchor_active`
- [x] Guard offset computation when no observed cash
- Commit: _pending_

### Step 3: Effective cash snapshot resolution
- [x] Resolve `effective_cash_snapshots` / `effective_observed_cash_snapshots` once
- [x] Use in 4 NAV calls, 2 cash series computations
- Commit: _pending_

### Step 4: Diagnostic flag updates
- [x] `cash_anchor_applied_to_nav` → `anchor_active` at both metadata sites (~5502, ~5581)
- Commit: _pending_

### Step 5: RealizedMetadata field + aggregation
- [x] `cash_anchor_available` field in `RealizedMetadata`
- [x] Set in both metadata build sites
- [x] `any()` override in aggregated mode
- Commit: _pending_

### Step 6: Tests
- [x] `tests/core/test_realized_cash_anchor.py` — 4 engine-level cases
- [x] `tests/mcp_tools/test_performance.py` — 2 MCP-layer cases
- Commit: _pending_

## Verification Results

### Flag OFF (should be unchanged)
- Return: _pending_
- `cash_anchor_applied_to_nav`: _pending_

### Flag ON
- Return: _pending_
- `cash_anchor_applied_to_nav`: _pending_
- `cash_anchor_offset_usd`: _pending_
- Component consistency (positions + cash = NAV): _pending_

### Test Suite
- `pytest tests/core/test_realized_cash_anchor.py`: ✅ pass
- `pytest tests/mcp_tools/test_performance.py`: ✅ pass
