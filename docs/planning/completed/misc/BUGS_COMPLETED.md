# Resolved Bugs

Bugs moved from `docs/planning/BUGS.md` as they were resolved. Most recent first.

---

## Bug B-016: Risk score methodology review — RESOLVED (2026-02-19)

**Resolution:**
1. Fund exemption extended to `calculate_suggested_risk_limits()` — keyword-only `security_types` param, input guards
2. Piecewise linear scoring curve replaces step function — configurable `risk_score_critical_threshold` added
3. Risk profile interaction validated — 18 tests covering monotonicity, tolerance sensitivity, leverage amplification
See: `docs/planning/completed/RISK_SCORE_METHODOLOGY_REVIEW_PLAN.md`

---

## Bug B-015: Single-stock weight limit treats funds/ETFs as single stocks — RESOLVED (2026-02-19)

See: `docs/planning/completed/FUND_WEIGHT_EXEMPTION_PLAN.md`
