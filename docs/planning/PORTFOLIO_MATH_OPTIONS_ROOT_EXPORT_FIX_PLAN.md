# portfolio_math — Un-curate Options Payoff Root Exports

**Status**: ✅ SHIPPED 2026-04-22 — commits `b77b9252` / `f795a485` / `d1e9127d`. See §9 ship log.
**Date**: 2026-04-22
**Predecessor**: `PORTFOLIO_MATH_OPTIONS_PAYOFF_EXTRACTION_PLAN.md` (Phase 3D, shipped 2026-04-22 — commits `f73c02ef` / `ec9bd7b0` / `684d5ec1` / `c712da3b` / `7bd43d56`)

---

## 1. Goal

Add the 6 payoff functions currently reachable only via `from portfolio_math.options import ...` to the `portfolio_math.*` root export surface, matching the Phase 2 pattern (all pricing primitives at root, no curation).

Functions to promote to root:
- `max_profit`
- `max_loss`
- `intrinsic_value`
- `extrinsic_value`
- `cost_of_leverage_annualized`
- `pnl_per_dollar_move`

After this change, all 10 public payoff functions + 5 pricing primitives + `OptionLeg` + `OptionStrategy` live at `portfolio_math.*` root, symmetric with Phase 2.

---

## 2. Why (reversing a prior Codex recommendation)

Phase 3D shipped with root exports curated to 4 payoff helpers per Codex R1 recommend #4 ("only expose the 4 workflow helpers at root: `leg_payoff`, `strategy_payoff`, `find_breakevens`, `payoff_table`"). That recommendation was accepted under the "accept Codex scope reduction early" rule.

Three reasons the curation was wrong:

1. **Wrong rule applied.** "Accept Codex scope reduction early" is for implementation scope — deciding what to build. Curating re-exports is zero marginal work either way; it's an API surface decision, which requires its own principled justification. Applying a scope-reduction rule to an API surface decision is a category error.

2. **Usage-prediction anti-pattern.** Selecting the "4 most-used" at root is the same workflow-predict framing rejected by the revised-framing section of `docs/planning/AGENT_SURFACE_AUDIT.md` (2026-04-21 decision to move Phase 3C/3D from deferred to actionable). That decision's three evaluation criteria — (a) asymmetry, (b) composition value, (c) scope cost — explicitly reject "workflow demand" as a gate for capability work. Choosing 4 of 10 functions at root based on expected usage is the same gate applied at the export level. We don't know in advance which functions the agent will reach for; capability extraction is about enabling composition, not forecasting patterns.

3. **Inconsistent with Phase 2.** Phase 2 shipped all 5 pricing primitives (`black_scholes_price`, `black_scholes_greeks`, `black76_price`, `black76_greeks`, `implied_volatility`) at root with no curation. Phase 3D exporting 4 of 10 payoff primitives is asymmetric for no principled reason. Default for capability packages is mirror-the-peer.

Dogfood confirmation (live test 2026-04-22): building a 50-candidate strategy screener required `from portfolio_math.options import max_profit, max_loss` — root `from portfolio_math import max_profit` fails with `AttributeError`. The curation introduced real friction.

---

## 3. Non-goals

- **No code changes to `portfolio_math/options.py`.** The functions themselves are already in place; only the `__init__.py` re-export surface changes.
- **No shim changes in `options/data_objects.py` or `options/payoff.py`.** They already re-export all 10 payoff functions; no change needed.
- **No change to existing test files from Phase 3D.** Only `tests/test_portfolio_math_sandbox_usage.py` extends to verify the 6 newly-promoted exports.
- **No README rewrite.** README "Public Surface" list already enumerates all 10 payoff functions; the correction is a one-line edit to reflect the root promotion.

---

## 4. Scope — exact changes

### 4.1 `portfolio_math/__init__.py`

Add the 6 functions to both the `from .options import (...)` block and the `__all__` list. Final state exports all 10 payoff functions at root, matching Phase 2's pricing pattern.

**Before** (current, curated — 4 payoff + 6 hidden):
```python
from .options import (
    OptionLeg, OptionStrategy,
    black76_greeks, black76_price,
    black_scholes_greeks, black_scholes_price,
    find_breakevens, implied_volatility,
    leg_payoff, payoff_table, strategy_payoff,
)
```

**After** (un-curated — all 10 payoff at root):
```python
from .options import (
    OptionLeg, OptionStrategy,
    black76_greeks, black76_price,
    black_scholes_greeks, black_scholes_price,
    implied_volatility,
    # All 10 payoff functions
    cost_of_leverage_annualized,
    extrinsic_value,
    find_breakevens,
    intrinsic_value,
    leg_payoff,
    max_loss,
    max_profit,
    payoff_table,
    pnl_per_dollar_move,
    strategy_payoff,
)
```

`__all__` list extended correspondingly — add the 6 names in the same block as the other payoff entries.

### 4.2 `tests/test_portfolio_math_sandbox_usage.py`

Extend the existing test to:
- Add the 6 new names to the root-import statement.
- Add assertions exercising each one at least once (e.g., `max_profit(spread)`, `intrinsic_value(call_leg, spot)`, `pnl_per_dollar_move(spread, anchor)`). Uses the existing debit spread fixture from the Phase 3D extension — no new fixtures needed.
- Add a small `portfolio_math.__all__` contract assertion (Codex R1 recommend #3): `assert set(EXPECTED_EXPORTS).issubset(set(portfolio_math.__all__))` where `EXPECTED_EXPORTS` lists all 10 payoff functions. Explicit root imports only catch binding omissions — an `__all__` assertion catches drift between the import block and the `__all__` list.

This catches `__init__.py` omissions at both the binding layer and the `__all__` contract layer.

### 4.3 `portfolio_math/README.md`

One-line correction at line 115. Before:
```
- additional payoff helpers in `portfolio_math.options`: `intrinsic_value`, `extrinsic_value`, `cost_of_leverage_annualized`, `max_profit`, `max_loss`, `pnl_per_dollar_move`
```

After — promote the 6 into the main Public Surface list as top-level bullets (alongside `leg_payoff`, `strategy_payoff`, etc.), and delete the "additional helpers in `portfolio_math.options`" line. README now enumerates all 10 payoff functions at root.

### 4.4 `docs/planning/AGENT_SURFACE_AUDIT.md`

Update Phase 3D row at line 16. Current text lists only the 4 curated exports. Replace with "`portfolio_math` now exports `OptionLeg`, `OptionStrategy`, and all 10 pure payoff functions at root, matching Phase 2's pricing-primitive pattern."

### 4.5 `docs/planning/PORTFOLIO_MATH_OPTIONS_PAYOFF_EXTRACTION_PLAN.md`

Three in-place edits so a ship-log reader lands on the correction, not the stale 4-export summary:

- **Ship log entry for Steps 2+3** (the commit that introduced curation): append an inline *"later reversed by `PORTFOLIO_MATH_OPTIONS_ROOT_EXPORT_FIX_PLAN.md` — see §13"* note so anyone scanning the ship log sees the reversal immediately.
- **§10 item 4 "Recommend #4 (curate root payoff exports)"**: mark as **reversed 2026-04-22** with pointer to §13 and to this follow-up plan doc.
- **Append §13 Post-ship correction** block explaining the reversal with rationale (points 1-3 from §2 above).

Do NOT rewrite §4 or §6 Step 3 — keep them historically accurate to what v3 shipped.

---

## 5. Test plan

- `python3 -m pytest -q tests/test_portfolio_math_sandbox_usage.py` — must include assertions for all 10 payoff functions imported from root + the `__all__` contract check. Baseline: 2 tests pass (one typed-sandbox-usage, one payoff-root smoke from the Phase 3D extension). After change: same 2 tests pass with extended assertions. No new test file — extending the existing one is the whole point (catches `__init__.py` omissions without needing separate regression).
- Run the Phase 3D regression suite to confirm no behavior regression:
  ```
  python3 -m pytest -q tests/options/ tests/test_portfolio_math_*.py \
    tests/services/test_trade_execution_service_multileg.py \
    tests/brokerage/ibkr/test_adapter_multileg.py \
    tests/mcp_tools/test_multi_leg_options.py \
    tests/mcp_tools/test_option_strategy_agent_format.py \
    tests/options/test_trade_preview_pricing.py
  ```
  Expect 206 passed (same as Phase 3D ship). This change only adds to the root import surface; it doesn't alter any function behavior, so no test-count change.

---

## 6. Risks

- **None material.** This is a re-export surface expansion — functions already exist in `portfolio_math/options.py`, already tested. Adding to `__init__.py` is a literal 6-line append.
- **Potential namespace collision at root**: check that none of the 6 names collide with anything already at `portfolio_math.*`. Verified via the current `__init__.py` — no conflicts with `correlation`, `stats`, `types` exports.
- **`__all__` ordering**: match the existing convention in `__init__.py` (grouped by subpackage, alphabetized within). No stylistic changes.

---

## 7. Step-by-step implementation

### Step 1 — Extend `portfolio_math/__init__.py`
Add 6 names to the `.options` import and to `__all__`. Verify `python3 -c "from portfolio_math import max_profit, max_loss, intrinsic_value, extrinsic_value, cost_of_leverage_annualized, pnl_per_dollar_move"` runs cleanly. Commit.

### Step 2 — Extend `tests/test_portfolio_math_sandbox_usage.py`
Add 6 names to the import; add ~6 lines of assertions using the existing debit spread fixture. Run the test. Commit.

### Step 3 — Docs update
Correct `portfolio_math/README.md` Public Surface list. Update `docs/planning/AGENT_SURFACE_AUDIT.md` Phase 3D row. Append §13 post-ship correction block to the extraction plan doc. Commit.

One commit per step — same discipline as Phase 3D.

---

## 8. Commit message templates

1. `feat(portfolio_math): un-curate options payoff root exports — add max_profit, max_loss, intrinsic_value, extrinsic_value, cost_of_leverage_annualized, pnl_per_dollar_move`
2. `test(portfolio_math): verify all 10 payoff functions reachable from root`
3. `docs(planning): record options payoff root-export uncuration + update README/audit`

---

## 9. Ship log

**Implementation note**: Codex harness rejected git mutation commands (same as Phase 3D); code was verified locally (206 regression tests pass, 2 sandbox_usage tests pass) then staged and committed from Claude per explicit user approval. One commit per step, scoped staging.

- 2026-04-22 — Step 1 complete (`b77b9252`). `portfolio_math/__init__.py` extended to export `max_profit`, `max_loss`, `intrinsic_value`, `extrinsic_value`, `cost_of_leverage_annualized`, `pnl_per_dollar_move` at root (added to both the `.options` import block and `__all__`). Import smoke: `python3 -c "from portfolio_math import max_profit, ..."` passed.
- 2026-04-22 — Step 2 complete (`f795a485`). `tests/test_portfolio_math_sandbox_usage.py` extended with 6 new root-import names, per-function assertions using the existing debit spread / call leg fixtures, and a `portfolio_math.__all__` contract assertion. Full Phase 3D regression suite: `206 passed`. Sandbox_usage: `2 passed`.
- 2026-04-22 — Step 3 complete (`d1e9127d`). Docs updated: `portfolio_math/README.md` promoted 6 helpers to top-level Public Surface bullets; `docs/planning/AGENT_SURFACE_AUDIT.md` Phase 3D row now describes all 10 payoff functions at root; `docs/planning/PORTFOLIO_MATH_OPTIONS_PAYOFF_EXTRACTION_PLAN.md` got inline "later reversed by …" note on Steps 2+3 ship entry, §10 item 4 marked reversed 2026-04-22, and new §13 Post-ship correction block. This fix plan doc also committed with the docs.

**Live verification**: agent sandbox now reaches all 10 payoff functions from `portfolio_math.*` root — confirmed via 50-candidate strategy screen with zero subpackage imports (4.4ms, matches pre-fix 4.6ms). The friction that triggered this fix is gone.

---

## 10. Change log

**v2 (2026-04-22)**: Codex R1 PASS with 3 recommends + 1 nit. All integrated:
- §2 points 1-2: removed private-memory citations (`~/.claude/...`), replaced with inline rationale and repo-local reference to `docs/planning/AGENT_SURFACE_AUDIT.md` revised-framing section.
- §4.5 expanded: now specifies in-place edits to the predecessor plan's ship log + §10 item 4 + new §13, so a ship-log reader lands on the correction, not the stale 4-export summary.
- §4.2 extended with `portfolio_math.__all__` contract assertion.
- §5 nit fixed: baseline is 2 tests (not 1).

**v1 (2026-04-22)**: Initial draft.
