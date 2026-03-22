# Performance Optimization Playbook

This document captures the high-level process that worked well during the March 2026 backend and Performance-view optimization pass. The goal is to preserve the method, not just the fixes, so the same playbook can be reused for future frontend or backend performance work.

## Primary Idea

Use a tight loop:

1. measure the real user workflow
2. instrument before guessing
3. remove duplicated work first
4. verify correctness in the actual UI
5. remeasure after every meaningful slice

This worked better than starting with isolated micro-optimizations or broad speculative cache changes.

## Operating Principles

- Optimize the real product path, not an abstract code path.
- Prefer exact-result reuse over approximations.
- Remove duplicated work before tuning leaf functions.
- Do not hide correctness problems with fallbacks.
- If two routes describe the same thing, they should share the same source of truth.
- Treat false empty states as bugs.
- Rebaseline often enough that the active plan always reflects reality.

## Recommended Workflow

### 1. Start With A Real Baseline

Define the user workflow first.

Examples from this pass:

- overview bootstrap plus dashboard burst
- Performance view load
- selected-account switch

Record both:

- cold behavior
- warm behavior

Capture:

- wall time
- endpoint timings
- payload size if relevant
- exact measurement conditions

Write the result down in a dated baseline doc before changing code.

### 2. Add Workflow-Level Timing

Before changing behavior, add enough timing detail to answer:

- which route is actually slow
- which step inside that route is slow
- whether the cost is local compute, duplicate work, or external/provider latency

In this repo, the useful level was:

- per-route workflow timers
- per-step breakdowns like `load_portfolio_data`, `get_all_positions`, `analyze_portfolio`, `enrich_attribution`, `fetch_dividend_history`

This step prevents chasing the wrong bottleneck.

### 3. Attack Duplicate Work First

The first major pass should focus on waste, not leaf tuning.

Typical questions:

- are we pricing twice during bootstrap?
- are multiple endpoints rebuilding the same portfolio context?
- are multiple routes calling `get_all_positions()` independently?
- are two endpoints calculating the same analysis or performance result separately?
- is sync work running directly inside an async route?

During the March 2026 pass, the biggest wins came from:

- bootstrap dedupe
- shared workflow snapshots
- shared position snapshots
- shared result snapshots
- threadpool cleanup for blocking route work

This usually produces bigger and safer gains than immediately optimizing a single math function.

### 4. Reuse Exact Results Before Changing Behavior

When a route is expensive, prefer:

- compute once
- cache briefly
- reuse the exact same result

before:

- returning reduced-fidelity data
- adding fallback logic
- changing financial behavior

Good examples:

- reuse `analyze` for `risk-score`
- reuse summary-only performance where the UI does not need attribution
- reuse realized-performance payloads across adjacent requests

Only introduce a cheaper mode if the caller truly does not need the expensive fields.

### 5. Rebaseline After Each Meaningful Slice

After every substantial change:

- run focused tests
- rerun the live measurements
- compare against the previous baseline
- update the active planning doc

This keeps the work grounded. It also prevents continuing a broad optimization campaign after the real problem has already moved.

### 6. Check The Real UI

Do not stop at API timings.

For each major slice, spot-check the actual frontend flow:

- initial load
- hard refresh
- selected-account changes
- relevant view navigation
- loading states versus false "no data" states

This pass found several real issues only through live UI checks:

- false empty states
- selected-account summary drift
- `$0` IBKR selector regression
- missing realized-performance attribution content

The rule is simple:

- if the UI is wrong, the optimization is not done

### 7. Fix Correctness Regressions Immediately

Optimization work can expose or create correctness problems.

When that happens:

- stop and fix the regression
- verify the actual UI
- only then continue optimizing

Important rule from this pass:

- no fallback that masks real data issues

If the value is wrong, make the routes agree. Do not invent a display-only fallback to hide the discrepancy.

### 8. Narrow The Scope Once The Big Wins Land

After the broad duplicate-work pass, the remaining work should become narrower.

Typical next-stage targets:

- one cold route
- one enrichment stage
- one provider fetch path
- one view-specific endpoint

At this point, avoid reopening another broad caching initiative unless the measurements clearly justify it.

### 9. Know When To Stop

Stop the broad pass when:

- warm path is healthy
- cold path is acceptable or mostly external-latency-bound
- remaining issues are narrow and tactical
- correctness is stable

At that point, future work should be:

- small follow-on slices
- separate optional-route tuning
- or a new baseline after another structural change

## Repo-Specific Playbook

If another Codex continues this work, the recommended order is:

1. read the active baseline doc
2. read the active perf plan
3. reproduce the current user-visible slowdown
4. check `/api/debug/timing` and route-level workflow timings
5. identify whether the cost is:
   - duplicate local work
   - leaf compute
   - external/provider latency
   - frontend startup/query gating
6. make one contained change
7. run focused tests
8. rerun live timings
9. verify the real UI
10. update docs if the numbers materially changed

## Decision Rules

Use these rules when choosing the next change:

- If two routes disagree on values, fix correctness before more optimization.
- If warm is fine but cold is bad, focus on cold-path setup and first-hit external work.
- If the route timing is low but the request wall is high, suspect contention or server-state issues.
- If the expensive part is optional UI data, consider a summary-only mode instead of full removal.
- If the cost is duplicated setup, share snapshots.
- If the cost is repeated computation over the same inputs, cache the computation itself.
- If the cost is provider latency, stop pretending it is an orchestration problem.

## Artifacts To Keep Updated

Keep these current during the work:

- dated baseline docs
- active perf plan
- focused regression tests
- any new smoke or Playwright checks added to guard regressions

## Good Handoff Format

A useful perf handoff should state:

- current source-of-truth baseline doc
- latest measured cold and warm numbers
- top 3 remaining bottlenecks
- what already landed
- what was tried and reverted
- whether the remaining cost is local compute or external latency

That format made this optimization pass much easier to continue across turns.
