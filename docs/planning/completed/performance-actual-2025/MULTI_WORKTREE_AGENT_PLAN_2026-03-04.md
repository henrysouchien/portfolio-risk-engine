# Multi-Worktree Agent Plan (2026-03-04)

## Goal
Diagnose and improve realized performance inference so estimated return converges toward official statement return under truncated history, using provider-agnostic logic only.

## Baseline
- Engine total return: `-8.50%`
- Official IBKR TWR: `+0.291921306%`
- Gap: `-8.7919 pp`

## Worktree Layout
- Track A (cash path): `/Users/henrychien/Documents/Jupyter/risk_module/worktrees/track-cash-path`
  - Branch: `wt_realized_cash_path`
  - Task file: `AGENT_TASK.md`
- Track B (opening state): `/Users/henrychien/Documents/Jupyter/risk_module/worktrees/track-opening-state`
  - Branch: `wt_realized_opening_state`
  - Task file: `AGENT_TASK.md`
- Track C (confidence fallback): `/Users/henrychien/Documents/Jupyter/risk_module/worktrees/track-confidence-fallback`
  - Branch: `wt_realized_confidence_fallback`
  - Task file: `AGENT_TASK.md`

## Approach Tracks
1. Cash-path normalization
- Hypothesis: major distortion comes from replayed cash path shape mismatch under truncated history.
- Change type: cash-path schedule correction (flow-weighted or uniform fallback), with strict diagnostic gating.
- Success signal: reduced NAV/return gap without provider hardcoding.

2. Opening-state / lot seeding refinement
- Hypothesis: first-exit synthetic defaults are mis-timing/mis-sizing opening capital for truncated symbols.
- Change type: use normalized holdings/cost-basis evidence to seed opening state before first exits.
- Success signal: lower synthetic dependence and smaller return gap.

3. Confidence-weighted fallback estimate
- Hypothesis: when synthetic impact is large and reliability is low, a second estimate is needed for users.
- Change type: preserve primary return; add fallback estimate from observed-only or blended path with explicit triggers.
- Success signal: transparent, comparable fallback metric for low-confidence cases.

## Evaluation Protocol
1. Run targeted tests in each track.
2. Run one realized performance debug run (`source=ibkr_flex`) in each track.
3. Extract and compare:
- `total_return`
- fallback fields (Track C)
- reliability flags/reason codes
- synthetic counts/impact diagnostics
4. Rank tracks by:
- provider-agnostic defensibility
- measurable gap improvement
- complexity and regression risk

## Decision Rule
- Prefer the smallest change that materially reduces gap and improves explainability.
- If two tracks help, merge additive pieces in sequence (A/B before C, since C is diagnostic fallback).
