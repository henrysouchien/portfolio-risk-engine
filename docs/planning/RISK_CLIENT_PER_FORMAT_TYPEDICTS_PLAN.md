# risk_client — Per-Format TypedDict Split (Deferred Plan)

**Status:** Deferred outline — not scheduled. Spawned from `RISK_CLIENT_AGENT_ERGONOMICS_PLAN.md` (the parent plan's R-006, deferred 2026-05-21 after two Codex review rounds).
**Date:** 2026-05-21
**Mode:** Plan-first per CLAUDE.md.

---

## What this plan would do

Today, the `risk_client/types.py` TypedDicts that cover format-discriminated wrappers (`get_positions`, `get_risk_analysis`, `run_whatif`, `get_performance`, ...) are **aggregate** — one TypedDict per wrapper with ~all fields `NotRequired` because the runtime shape varies by `format=` value (`'agent' / 'summary' / 'full' / 'report' / ...`).

The aggregate-TypedDict pattern is what costs the parent plan its `output_parseability` score (~550/1000). The fix is to split each aggregate into per-format variants, then make the wrapper's overload return type narrow correctly:

```python
# Today:
class PositionsResult(TypedDict):
    status: str
    format: NotRequired[Literal['agent']]
    snapshot: NotRequired[dict[str, Any]]
    positions: NotRequired[list[dict[str, Any]]]
    total_value: NotRequired[float]
    # ... ~25 NotRequired fields covering all six formats
    ...

# After this plan:
class PositionsAgentResult(TypedDict):
    status: str
    format: Literal['agent']
    snapshot: dict[str, Any]      # required because every 'agent' runtime emits it
    flags: list[dict[str, Any]]   # ditto

class PositionsFullResult(TypedDict):
    status: str
    positions: list[dict[str, Any]]
    total_value: float
    position_count: int
    # ... required keys verified against the 'full' runtime fixture

class PositionsSummaryResult(TypedDict): ...
class PositionsListResult(TypedDict): ...
class PositionsByAccountResult(TypedDict): ...
class PositionsMonitorResult(TypedDict): ...

PositionsResult = (
    PositionsAgentResult | PositionsFullResult | PositionsSummaryResult
    | PositionsListResult | PositionsByAccountResult | PositionsMonitorResult
)
```

Combined with the **parent plan's R-004 auto-overload**, the generator can then emit overloads per format that narrow to the *specific* variant (e.g., `get_positions(format='summary')` → `PositionsSummaryResult`, not `PositionsResult`).

This finally lets the parent plan's deferred **R-010 (`__required_keys__` promotion)** ship safely — each variant's required keys are the ones unconditionally emitted by *that format's* runtime, no longer the empty intersection across all formats.

---

## The gating constraint (why this is deferred)

The contract test (`tests/test_risk_client_contract.py`) currently asserts `__required_keys__` are present in the runtime payload. With aggregate TypedDicts and almost all fields `NotRequired`, this is a weak contract. Tightening it requires:

1. **A runtime fixture per format per wrapper.** Today's `tests/mcp_tools/test_*_agent_format.py` helpers only cover `format='agent'`. Splitting `PositionsResult` into 6 variants means 6 runtime shapes to verify. Currently 8 aggregate TypedDicts have `non-agent` contract cases at all (per Codex v3 review); none have all formats covered uniformly.
2. **Confidence the runtime shape is stable.** A field being "always present" in three sample runtimes isn't proof. We need either (a) cross-checking the server code that builds each format, or (b) an N-week observation window where we observe live runtime payloads via instrumentation before promoting fields to required.

Without (1) + (2), promoting fields to required would cause spurious contract-test failures whenever a non-agent runtime omits a field the test now expects.

---

## Trigger condition (when to revisit)

This plan becomes actionable when **any one** of:

- A second agent-ergonomics audit pass scores `output_parseability < 600` and the bottleneck is traced to aggregate TypedDicts (i.e., we hit the ceiling of what the parent plan's R-004/R-009 can lift).
- A specific incident where an agent picked a field that "looked required" from the TypedDict but the runtime didn't emit it, causing a downstream failure that took noticeable debugging time.
- We add a new wrapper whose Tier-A treatment requires per-format types from the start (greenfield is easier than refactor).
- **All runtime fixtures for one Tier-A wrapper's formats already exist or are being touched anyway** (per Codex v3.2 NB) — i.e., the audit cost is already sunk by some other initiative, so capturing the per-format split is incremental.

Until one of those, the parent plan's R-004 + R-009 + R-010 contract-test extension is the right level of investment.

---

## Scope sketch (when this plan activates)

1. **Inventory** — for each aggregate TypedDict in `risk_client/types.py`, list every `format=` Literal value the corresponding wrapper accepts (auto-extractable from `agent.registry` callable signatures).
2. **Runtime fixture audit** — for each (wrapper, format) pair, find or create the runtime fixture in `tests/mcp_tools/test_*_agent_format.py` (or new sibling files for non-agent formats).
3. **Split** — generate per-format TypedDicts. Names: `<Wrapper><Format>Result` (`PositionsSummaryResult`, `RiskAnalysisFullResult`, etc.). Union type keeps the aggregate name for backwards-compat: `PositionsResult = ...Union[...]`.
4. **Generator overload extension** — modify `_autodiscover_overload` in `scripts/generate_risk_client.py` to look up per-format types from a `PER_FORMAT_RETURNS: dict[str, dict[str, str]]` map; fall through to the parent plan's `AgentEnvelope | aggregate` rule for wrappers without per-format coverage.
5. **Required-key promotion** — for each new per-format TypedDict, promote fields verified as unconditionally emitted in step 2. Conservative bar: when in doubt, keep `NotRequired`.
6. **Contract test extension** — parametrize `test_risk_client_contract.py` so every per-format TypedDict has at least one runtime case asserting its required keys.
7. **Codex review.** Iterate until PASS.
8. **Generator regen + sync test check.** Land per wave (one Tier-A wrapper at a time to keep diffs reviewable).
9. **Wiring updates** (per Codex v3.2 NB): update `_collect_type_exports()` in the generator + `__all__` in the generated `__init__.py` to include each new per-format TypedDict; add `assert_type` cases in `risk_client/_typecheck_overloads.py` for each converted wrapper.
10. **Reuse existing per-format variants where they already exist** — `run_whatif` / `run_backtest` / `get_income_projection` already have hand-curated per-format TypedDicts (`WhatIfSummaryResult`, `BacktestFullResult`, etc.). Don't duplicate; integrate them into the new pattern.

---

## Out of scope (file as follow-ups even when this plan activates)

- Server-side changes to make runtime emissions more uniform (e.g., always emit `version` everywhere). That's a registry-side initiative, separate plan.
- Splitting `ToolResult` (the catch-all for ~60 non-Tier-A wrappers). Per-format TypedDicts for those is a much larger undertaking.

---

## Risks

| Risk | Mitigation |
|---|---|
| Runtime shape changes between observation and promotion | Land per-wrapper, not all-at-once; one regression at a time is recoverable. |
| Aggregate TypedDict union becomes painful for downstream consumers | The union keeps the historical name; existing `dict.get(...)` patterns continue working. Per-variant access requires `isinstance`-style narrowing or the wrapper overload. |
| Generator complexity blow-up | The `PER_FORMAT_RETURNS` map is a few hundred lines of curated data, lookup is constant-time. No structural rewrite of the generator. |

---

## See also

- **Parent plan:** `RISK_CLIENT_AGENT_ERGONOMICS_PLAN.md` — explains why this is deferred and how R-004's fallback rule lets the parent ship without this work.
- **Contract test:** `tests/test_risk_client_contract.py` — the harness this plan extends.
- **agent-format runtime helpers:** `tests/mcp_tools/test_*_agent_format.py` — the seed fixtures for step-2 audit.
