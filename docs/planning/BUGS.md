# Open Bugs & Known Issues

**STATUS:** REFERENCE

Track only active bugs in this file. Resolved bugs archived in `completed/BUGS_COMPLETED.md`.

---

## Current Status
- 1 active bug.

---

## Bug 03: `get_risk_score` returns "consolidation input is empty"

**Status:** Open
**Severity:** Medium
**Date:** 2026-03-12

**Symptom:**
`get_risk_score(format="summary")` returns `{"status":"error","error":"consolidation input is empty"}` even though `get_positions(format="summary")` succeeds with 18 positions (15 equities, 3 cash).

**Root cause:**
`_load_portfolio_for_analysis()` → `PositionService.get_all_positions(consolidate=True)` → `consolidate_positions()` receives an empty DataFrame. The positions load succeeds via the MCP `get_positions` tool (which has its own empty-guard returning `row_count: 0`), but the risk score path hits `consolidate_positions()` which raises `ValueError` on empty input. Likely a filtering or provider-availability issue — e.g., only IBKR returned data but the risk path may apply stricter filters, or positions were cached stale.

**Reproduction:**
- MCP tool: `get_risk_score(format="summary")`
- Result: `{"status":"error","error":"consolidation input is empty"}`
- Note: `get_positions(format="summary")` works fine (18 positions, $21k)

**Fix plan:**
Investigate why `_load_portfolio_for_analysis()` gets an empty position set when the positions tool succeeds. Possible causes: (1) provider error filtering differs between the two paths, (2) cache staleness, (3) user_email resolution mismatch.

**Files:**
- `services/position_service.py:604` — raises the error
- `mcp_tools/risk.py:566` — `_load_portfolio_for_analysis()` call site

---

## Template For New Issues

## Bug XX: <short title>

**Status:** Open
**Severity:** Blocker | High | Medium | Low
**Date:** YYYY-MM-DD

**Symptom:**

**Root cause:**

**Reproduction:**
- Command(s):
- Result:

**Fix plan:**

**Files:**

**Validation:**
- Command(s):
- Result:
