# Open Bugs & Known Issues

**STATUS:** REFERENCE

Track only active bugs in this file. Resolved bugs archived in `completed/BUGS_COMPLETED.md`.

---

## Current Status
- 0 active bugs. All resolved 2026-03-17.

---

## Bug 03: `get_risk_score` returns "consolidation input is empty" — RESOLVED

**Status:** Fixed — `d6ce4dc6` (2026-03-17)
**Fix**: Original crash fixed earlier at `position_service.py:584` (empty guard). Remaining VIRTUAL_FILTERED correctness gap fixed by adding `rebuild_position_result()` after `filter_position_result()` in `_load_portfolio_for_analysis()` and `load_portfolio_for_performance()`. Moved rebuild logic to service layer.

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
