# Phase 3D — portfolio_math Options Payoff + Domain Types Extraction

**Status**: DRAFT v3 — revised per Codex R2 (2026-04-21)
**Date**: 2026-04-21
**Predecessor**: `PORTFOLIO_MATH_EXTRACTION_PLAN.md` (Phase 2, shipped 2026-04-17), `BUILDING_BLOCKS_INTERNAL_DELEGATE_PLAN.md` (Phase 3B, shipped 2026-04-21)
**Rationale**: `docs/planning/AGENT_SURFACE_AUDIT.md` revised-framing section (2026-04-21).

**Codex R1 verdict**: FAIL. Two blockers resolved in v2: (1) Option B subpackage conversion breaks `portfolio_math/options.py` sibling-relative imports (`from ._utils`, `from .types import GreeksSnapshot`) — plan now defaults to Option A (flat); (2) tests §7 didn't lock legacy serializer payloads — plan now adds characterization tests for `OptionLeg.to_dict`, `OptionStrategy.to_dict`, and full `StrategyAnalysisResult.to_dict/to_summary/get_agent_snapshot`. Other Codex recommends (curated root exports, corrected consumer list, alias identity tests, rationale fixes) also integrated. See §12 for change log.

---

## 1. Goal

Extract the options **domain types** (`OptionLeg`, `OptionStrategy`) and **pure payoff math** from `options/` into `portfolio_math/`, making them importable inside the agent code-execution sandbox alongside the already-extracted Black-Scholes pricing / Greeks / IV primitives.

**Primary driver**: asymmetric surface. `portfolio_math.options` currently has pricing primitives (`black_scholes_price`, `black_scholes_greeks`, `implied_volatility`) local to the sandbox but no `OptionStrategy` to run them through. Agent has half the kit; this phase finishes the kit.

**Capability unlocks** (emergent, not workflow-gated):
- Local strategy screening (sweep 50 strike combos = ms, not 50 HTTP calls at ~300ms each)
- Composable with existing local Black-Scholes for vol/time surfaces (e.g., price this spread at IV+10 vol, 30 days forward)
- `strategy_payoff(strategy, price_array)` composable with MC terminal-price arrays and stock P&L vectors
- Custom price grids and targeted breakeven analysis without HTTP round-trips

---

## 2. Non-goals

- **No behavior changes.** All existing HTTP/MCP/agent-format/frontend paths through `rc.analyze_option_strategy` + `OptionAnalyzer` must produce byte-identical output.
- **No extraction of analyzer orchestration.** `OptionAnalyzer`, `StrategyAnalysisResult`, `LegAnalysis`, and `analyze_leg` stay in `options/`. Rationale: `LegAnalysis` is an analyzer-output shape (has `market_bid`/`market_ask`/`market_mid`, `price_source`, `greeks_source`) — not a pure-math primitive. Moving it widens the surface into analyzer concerns and invites the "API redesign" criticism Codex R1 flagged during Phase 2.
- **No extraction of chain analytics** (`chain_analysis.py`) or **portfolio Greeks** (`portfolio_greeks.py`). Both depend on IBKR, provider data, and position records — not pure math.
- **No docker-image changes.** Payoff math uses only `numpy`, already in the sandbox image.
- **No new public behaviors.** No new functions beyond what already exists in `options/payoff.py` and `options/data_objects.py`.

---

## 3. Current state (verified 2026-04-21)

### 3.1 What's already in `portfolio_math/options.py`
5 MVP kernels shipped in Phase 2:
- `black_scholes_price`, `black_scholes_greeks`
- `black76_price`, `black76_greeks`
- `implied_volatility`

Re-exported at `portfolio_math/__init__.py:10-16` and mirrored via shim at `options/greeks.py:3-9` (`from portfolio_math.options import ...`).

### 3.2 What `options/data_objects.py` contains (~185 lines)
- `_parse_expiration` (module-private helper, stdlib-only)
- `@dataclass OptionLeg` — single strategy leg (call/put/stock)
  - Fields: `position`, `option_type`, `premium`, `strike`, `size`, `multiplier`, `expiration`, `label`, `con_id`
  - Validation in `__post_init__` (call/put vs stock branching, premium/size/strike/multiplier range checks, con_id int coerce)
  - Properties: `direction`, `expiry_yyyymmdd`, `net_premium`
  - Methods: `notional_exposure(underlying_price)`, `to_dict()`, `to_summary()`
- `@dataclass OptionStrategy` — container for legs + context
  - Fields: `legs: list[OptionLeg]`, `underlying_price`, `underlying_symbol`, `description`
  - Validation in `__post_init__`
  - Methods: `to_dict()`, `to_summary()`

**External deps**: stdlib only (`dataclasses`, `datetime`, `typing`). No numpy, no portfolio_math, no options internals.

### 3.3 What `options/payoff.py` contains (~300 lines)

| Function | Purity | Notes |
|---|---|---|
| `_is_scalar`, `_to_array` | Pure helpers | numpy only |
| `leg_payoff(leg, price)` | Pure math | Takes `OptionLeg` + float/array → float/array |
| `strategy_payoff(strategy, price)` | Pure math | Aggregates `leg_payoff` |
| `intrinsic_value(leg, s)` | Pure math | Scalar |
| `extrinsic_value(leg, s)` | Pure math | Scalar |
| `cost_of_leverage_annualized(leg, s, dte)` | Pure math | Scalar |
| `_option_strikes`, `_slope_at_price`, `_compute_segments`, `_dedupe_sorted` | Pure helpers | Internal to piecewise-linear segment decomposition |
| `find_breakevens(strategy)` | Pure math | Returns sorted list of floats |
| `max_profit(strategy)` | Pure math | float \| None |
| `max_loss(strategy)` | Pure math | float \| None |
| `pnl_per_dollar_move(strategy, at_price)` | Pure math | Finite-difference scalar |
| `payoff_table(strategy, lo, hi, steps)` | Pure math | Returns list[dict] — per-leg + net over grid |
| **`analyze_leg(leg, s, dte)`** | **Mixed** | Returns `LegAnalysis` (from `options.result_objects`). **Stays in risk_module** (not a pure-math primitive). |

**External deps**:
- `numpy` (already sandbox-local)
- `.data_objects` (moves with this phase)
- `.result_objects` (stays — used only by `analyze_leg`)

### 3.4 Consumers of the moving surface

Traced via grep for `OptionLeg`, `OptionStrategy`, `options.data_objects`, `options.payoff`:

**`OptionLeg` / `OptionStrategy` imports** (verified via grep; Codex R1 #8 correction — `options/portfolio_greeks.py` only imports greeks, not domain types):
- `options/__init__.py:5-8` — package re-export
- `options/analyzer.py:11` — from `.data_objects`
- `options/payoff.py:10` — from `.data_objects`
- `options/result_objects.py:12` — from `.data_objects`
- `options/models.py:3-6` — compat shim re-export
- `mcp_tools/options.py:11` — `from options import OptionAnalyzer, OptionLeg, OptionStrategy`
- `mcp_tools/multi_leg_options.py:10` — `from options import OptionStrategy`
- `services/trade_execution_service.py:38` — `from options import OptionStrategy`
- `brokerage/ibkr/adapter.py:47` — `from options import OptionLeg, OptionStrategy`
- `scripts/run_options.py:15`
- Tests in `tests/options/`, `tests/services/`, `tests/brokerage/ibkr/`, `tests/mcp_tools/`

**`options.payoff` imports**:
- `options/analyzer.py:10` — `from . import payoff`
- `tests/options/test_payoff.py:6` — direct import of `find_breakevens`, `leg_payoff`, `max_loss`, `max_profit`, `payoff_table`, `strategy_payoff`

**Boundary**: None of these imports need to change if the shim pattern holds. All consumers import from `options.*`, which becomes a transparent re-export.

### 3.5 Phase 2 shim pattern (to replicate)

`options/greeks.py` (post-Phase-2):
```python
"""Legacy import surface for local option pricing and Greeks."""
from portfolio_math.options import (
    black76_greeks, black76_price,
    black_scholes_greeks, black_scholes_price,
    implied_volatility,
)
__all__ = [...]
```

9 lines of code. All existing `from options.greeks import black_scholes_price` callers unchanged. `options/__init__.py` still works. This is the exact template.

---

## 4. Design — flat module (Option A)

**Codex R1 blocker #1 / recommend #3**: Option B (subpackage conversion) is broken as originally specified. `portfolio_math/options.py:7-8` uses sibling-relative imports `from ._utils import _norm_cdf, _norm_pdf` and `from .types import GreeksSnapshot` that resolve to `portfolio_math._utils` and `portfolio_math.types`. After `git mv portfolio_math/options.py portfolio_math/options/pricing.py`, those relative imports would resolve to `portfolio_math.options._utils` (doesn't exist) and `portfolio_math.options.types` (collides with the new OptionLeg/OptionStrategy module). Fixable only by rewriting pricing imports to `from .._utils` + `from ..types import GreeksSnapshot` — which is uglier than Option A and adds risk for no incremental value. The Phase 2 R1 objection was about surface-widening, not subpackage structure.

**Chosen shape**: keep `portfolio_math/options.py` flat. Append `OptionLeg`, `OptionStrategy`, and the 10 pure payoff functions to the existing module. Net file size ~750 lines. Organize in sections:

```
portfolio_math/options.py
  ├─ (existing) _validate_option_type, _safe_sqrt_t, _d1_d2
  ├─ (existing) black_scholes_price, black76_price
  ├─ (existing) black_scholes_greeks, black76_greeks
  ├─ (existing) _arbitrage_bounds, implied_volatility
  ├─ (NEW section header: Domain types)
  ├─ (NEW) _parse_expiration
  ├─ (NEW) OptionLeg dataclass
  ├─ (NEW) OptionStrategy dataclass
  ├─ (NEW section header: Payoff math)
  ├─ (NEW) _Segment, _is_scalar, _to_array
  ├─ (NEW) leg_payoff, strategy_payoff
  ├─ (NEW) intrinsic_value, extrinsic_value, cost_of_leverage_annualized
  ├─ (NEW) _option_strikes, _slope_at_price, _compute_segments, _dedupe_sorted
  ├─ (NEW) find_breakevens, max_profit, max_loss
  └─ (NEW) pnl_per_dollar_move, payoff_table
```

Existing `from ._utils import ...` and `from .types import GreeksSnapshot` at the top of the file remain untouched. `numpy` import added.

**`portfolio_math/__init__.py`** (Codex R1 recommend #4 — curated root exports):
```python
from .options import (
    # existing pricing surface
    black76_greeks, black76_price,
    black_scholes_greeks, black_scholes_price,
    implied_volatility,
    # NEW domain types (full root exposure)
    OptionLeg, OptionStrategy,
    # NEW curated payoff surface — 4 most-used at root
    leg_payoff, strategy_payoff,
    find_breakevens, payoff_table,
    # Other payoff functions accessible via `from portfolio_math.options import ...`:
    # intrinsic_value, extrinsic_value, cost_of_leverage_annualized,
    # max_profit, max_loss, pnl_per_dollar_move
)
```

The `portfolio_math/options.py` `__all__` still exports all 10 payoff functions — the root curation is only about sandbox ergonomics (`from portfolio_math import leg_payoff` works; `from portfolio_math import max_profit` requires `from portfolio_math.options import max_profit`).

**Why flat (reaffirmed)**:
- Zero risk of import-path breakage (Codex blocker #1 → moot).
- Smaller diff → faster review, easier revert.
- The semantic grouping concern is solved by section headers + `__all__`, not directory structure.
- Future-proofing: if we later extract optimizer kernels, their module can be `portfolio_math/optimizer.py` at the same flat level.

**Rejected: subpackage (Option B)**: see blocker #1 above. Can revisit if/when `portfolio_math/options.py` genuinely outgrows a single file.

---

## 5. Re-export shim changes in `options/`

### 5.1 `options/data_objects.py` — becomes shim (~7 lines)
```python
"""Legacy import surface for options domain types."""
from portfolio_math.options import OptionLeg, OptionStrategy

__all__ = ["OptionLeg", "OptionStrategy"]
```

Current `_parse_expiration` helper moves with `OptionLeg` (it's module-private; not re-exported).

### 5.2 `options/payoff.py` — becomes shim + `analyze_leg` keeper (~30 lines)

Codex R1 recommend #5 — `analyze_leg` stays in `options/payoff.py`. It preserves the analyzer call path (`options/analyzer.py:295,324`) with minimal churn. Real coverage is `tests/options/test_analyzer.py` (not `tests/options/test_payoff.py`, which covers only the pure functions).

```python
"""Legacy import surface for options payoff math + analyze_leg wrapper."""
from portfolio_math.options import (
    leg_payoff, strategy_payoff,
    intrinsic_value, extrinsic_value, cost_of_leverage_annualized,
    find_breakevens, max_profit, max_loss,
    pnl_per_dollar_move, payoff_table,
    OptionLeg, OptionStrategy,  # for type hints below
)

from .result_objects import LegAnalysis


def analyze_leg(
    leg: OptionLeg,
    underlying_price: float,
    days_to_expiry: int,
) -> LegAnalysis:
    """Analyzer-facing leg wrapper — composes pure-math primitives into LegAnalysis."""
    # body from current options/payoff.py:267-299 (calls intrinsic_value,
    # extrinsic_value, cost_of_leverage_annualized — all now imported above
    # from portfolio_math.options)
    ...


__all__ = [
    "leg_payoff", "strategy_payoff",
    "intrinsic_value", "extrinsic_value", "cost_of_leverage_annualized",
    "find_breakevens", "max_profit", "max_loss",
    "pnl_per_dollar_move", "payoff_table",
    "analyze_leg",
]
```

### 5.3 Files **not** changed

- `options/__init__.py` — no change; it re-exports from `.data_objects` and `.analyzer` which still work via shims.
- `options/result_objects.py` — already imports `GreeksSnapshot` from `portfolio_math.types` (Phase 2). `LegAnalysis` and `StrategyAnalysisResult` unchanged.
- `options/analyzer.py` — no change; still does `from . import payoff` and `from .data_objects import OptionLeg, OptionStrategy` via shims.
- `options/greeks.py` — no change (Phase 2 shim).
- `options/chain_analysis.py`, `options/portfolio_greeks.py` — no change.
- `options/models.py` — no change (compat shim that imports from data_objects + result_objects).
- All consumers (`mcp_tools/`, `services/`, `brokerage/`, tests) — no change.

---

## 6. Step-by-step implementation

### Step 1 — Pin legacy serializer payloads with characterization tests (Codex R1 blocker #2)

**Before any code moves**, add characterization tests that lock current `OptionLeg.to_dict()`, `OptionStrategy.to_dict()`, `OptionLeg.to_summary()`, `OptionStrategy.to_summary()`, `StrategyAnalysisResult.to_dict()`, `StrategyAnalysisResult.to_summary()`, and `StrategyAnalysisResult.get_agent_snapshot()` payloads for a representative set of strategies. Tests live at `tests/options/test_serialization_contract.py` and must pass on `main` **before** the move, establishing the invariant.

**Fixture matrix** (minimum — Codex R2 nit #5):
- Long call (single leg, finite max loss, unlimited profit)
- Debit call spread (finite max profit and max loss)
- Iron condor (defined-risk, defined-reward both sides)
- Naked short call (**explicit unlimited-loss fixture**, finite max profit)
- Stock-only leg (premium-as-price, `multiplier=1.0`, no `expiration`)

**Determinism requirement** (Codex R2 recommend #2): `StrategyAnalysisResult.to_dict()` at `options/result_objects.py:129` emits `"generated_at": datetime.now().isoformat()`. Freeze time via `monkeypatch` on the `datetime` class used inside `to_dict()` — concretely, monkeypatch `options.result_objects.datetime` to a fixture subclass whose `.now()` returns a fixed `datetime(2026, 4, 21, 12, 0, 0)`. Same treatment inside `to_api_response()` if covered. All `to_dict()` assertions then use full `dict` equality with explicit key enumeration — no partial-field assertions.

`get_agent_snapshot()` does **not** emit a timestamp (verified at `options/result_objects.py:162-246`), so no freeze needed for that path.

**Exit criteria**: New characterization tests pass against unmodified `main`. These become the regression oracle for every subsequent step.

### Step 2 — Append domain types to `portfolio_math/options.py`

- Append `_parse_expiration`, `OptionLeg`, `OptionStrategy` (exact copy from `options/data_objects.py`) into `portfolio_math/options.py` under a `# === Domain types ===` section header.
- Update `portfolio_math/options.py` `__all__` to include `OptionLeg`, `OptionStrategy`.
- Add `OptionLeg`, `OptionStrategy` to `portfolio_math/__init__.py` top-level re-exports.
- Create `tests/test_portfolio_math_options_types.py` — unit tests covering every validation branch in `OptionLeg.__post_init__` and `OptionStrategy.__post_init__`, every property (`direction`, `expiry_yyyymmdd`, `net_premium`), `notional_exposure`, `to_dict`, `to_summary`. Include stock-leg path and string-expiration parsing (YYYYMMDD and ISO).

**Exit criteria**: New tests green. Phase 2 pricing tests unchanged. `options/*` consumers still import from `options.data_objects` (shim not yet in place → still pointing at original file; next step flips that).

### Step 3 — Append pure payoff functions to `portfolio_math/options.py`

- Append `_Segment`, `_is_scalar`, `_to_array`, and the 10 public payoff functions (exact copy from `options/payoff.py`) under a `# === Payoff math ===` section header.
- `analyze_leg` is **not** moved — it returns `LegAnalysis` which stays in `options/result_objects.py`.
- Update `portfolio_math/options.py` `__all__` to include all 10 public payoff names.
- Add root-level curated exports to `portfolio_math/__init__.py`: `leg_payoff`, `strategy_payoff`, `find_breakevens`, `payoff_table`. Other 6 payoff functions accessible via `from portfolio_math.options import ...` only (Codex R1 recommend #4).
- Create `tests/test_portfolio_math_options_payoff.py`:
  - Vectorized `leg_payoff` (scalar + array) parity
  - `strategy_payoff` aggregation
  - `find_breakevens` — single-strike, debit spread, iron condor, bounded-tail cases
  - `max_profit` / `max_loss` — unlimited tails return `None`
  - `payoff_table` — grid shape, per-leg label dedup, `steps < 2` error
  - `pnl_per_dollar_move` — analytic slope match at linear regions
  - `intrinsic_value`, `extrinsic_value`, `cost_of_leverage_annualized` — spot-on-strike, ITM, OTM, stock legs, dte<=0 None returns
- **Extend `tests/test_portfolio_math_sandbox_usage.py`** (Codex R2 recommend #3): the existing Phase 2 root-surface smoke covers only `compute_performance_metrics`, `black_scholes_greeks`, `compute_correlation_matrix`. Add a block that imports `OptionLeg`, `OptionStrategy`, `leg_payoff`, `strategy_payoff`, `find_breakevens`, `payoff_table` directly from `portfolio_math`, builds a simple debit spread, and asserts `strategy_payoff(strategy, lower_strike + spread_cost) ≈ 0`. This is the repo-local guardrail for the new curated root exports — catches `portfolio_math/__init__.py` omissions that the cross-repo AI-excel-addin smoke (Step 6) would only catch later.

**Exit criteria**: New tests green. Extended sandbox_usage test green. Existing `tests/options/test_payoff.py` still green (imports unchanged).

### Step 4 — Convert `options/data_objects.py` + `options/payoff.py` to re-export shims

- Replace `options/data_objects.py` with the 7-line shim from §5.1.
- Replace `options/payoff.py` with the ~30-line shim from §5.2 — 10 payoff re-exports + `analyze_leg` wrapper whose body is unchanged from current `options/payoff.py:267-299` (the pure-math primitives it calls — `intrinsic_value`, `extrinsic_value`, `cost_of_leverage_annualized` — now resolve through the re-export import at the top of the shim).
- Run the full characterization test suite from Step 1 — must pass byte-identically.
- Run full regression:
  - `tests/options/test_payoff.py` (shim-path pure functions)
  - `tests/options/test_result_objects.py`
  - `tests/options/test_analyzer.py` (real `analyze_leg` coverage per Codex R1 recommend #5)
  - `tests/options/test_live_pricing.py`
  - `tests/options/test_option_strategy_agent_snapshot.py`
  - `tests/options/test_mcp_options.py`
  - `tests/options/test_trade_preview_pricing.py` (Codex R1 recommend #8)
  - `tests/services/test_trade_execution_service_multileg.py`
  - `tests/brokerage/ibkr/test_adapter_multileg.py`
  - `tests/mcp_tools/test_multi_leg_options.py` (Codex R1 recommend #8)
  - `tests/mcp_tools/test_option_strategy_agent_format.py` (Codex R1 recommend #8)

**Exit criteria**: All tests green, including Step 1 characterization tests.

### Step 5 — Alias identity tests (Codex R1 recommend #7)

Add `tests/options/test_alias_identity.py` with explicit class-identity assertions:

```python
def test_option_leg_alias_identity():
    import options.data_objects
    import portfolio_math.options
    assert options.data_objects.OptionLeg is portfolio_math.options.OptionLeg

def test_option_strategy_alias_identity():
    import options.data_objects
    import portfolio_math.options
    assert options.data_objects.OptionStrategy is portfolio_math.options.OptionStrategy

def test_payoff_function_alias_identity():
    from options.payoff import find_breakevens as shim_fn
    from portfolio_math.options import find_breakevens as canonical_fn
    assert shim_fn is canonical_fn
```

Mirrors the shim-alias pattern validated by `options/greeks.py` in Phase 2.

**Exit criteria**: Alias tests green. No duplicate class definitions in the import graph.

### Step 6 — Sandbox subprocess integration smoke test (AI-excel-addin repo)

- Add a pinned subprocess-mode integration test mirroring PM1A's `portfolio_math.black_scholes_price` smoke test (AI-excel-addin `cf1b726`).
- Test imports `portfolio_math.OptionLeg`, `portfolio_math.OptionStrategy`, `portfolio_math.strategy_payoff` via subprocess; constructs a long call; asserts `strategy_payoff(strategy, strike + premium) == 0.0` within tolerance.
- Cross-repo — lives in AI-excel-addin. File companion task.

**Exit criteria**: Sandbox subprocess can `import portfolio_math; s = portfolio_math.OptionStrategy([portfolio_math.OptionLeg(...)]); portfolio_math.strategy_payoff(s, prices)` without HTTP.

### Step 7 — Agent system prompt update (AI-excel-addin repo)

- Update agent system prompt to enumerate new local primitives alongside existing pricing ones. Same routing bullet as PM1A — "use `host='subprocess'` for `portfolio_math.OptionStrategy` / `strategy_payoff` / `find_breakevens` / `payoff_table`."
- Cross-repo — lives in AI-excel-addin. File companion task.

**Exit criteria**: Agent prompt enumerates the full `portfolio_math.options` surface.

### Step 8 — Ship + update docs

- Commit: `feat(portfolio_math): extract options domain types + pure payoff math (Phase 3D)`.
- Update `docs/planning/AGENT_SURFACE_AUDIT.md` Phase 3D row: 🟢 ACTIONABLE → ✅ SHIPPED.
- Update `docs/TODO.md` PM3 entry: mark 3D DONE, leave 3C actionable, optimizer/PM1B deferred.
- **Update `portfolio_math/README.md`** (Codex R2 recommend #4): the current "Deferred Scope" block at `portfolio_math/README.md:114-118` lists "option payoff helpers plus `OptionLeg` and `OptionStrategy`" as deferred. Remove that line from the deferred list and add the new surface to the package description / usage section. Public `portfolio_math` docs must reflect shipped reality.
- Ship log appended at bottom of this plan doc.

---

## 7. Test plan (summary)

| Test | What it covers | Status |
|---|---|---|
| `tests/options/test_serialization_contract.py` | **New (Step 1)** — locks `OptionLeg.to_dict/to_summary`, `OptionStrategy.to_dict/to_summary`, `StrategyAnalysisResult.to_dict/to_summary/get_agent_snapshot` payloads byte-for-byte across representative strategies | Add |
| `tests/test_portfolio_math_options_types.py` | **New (Step 2)** — all `OptionLeg`/`OptionStrategy` validation branches + properties + serialization | Add |
| `tests/test_portfolio_math_options_payoff.py` | **New (Step 3)** — all 10 pure payoff functions, including edge cases (stock legs, unlimited tails, `dte<=0`) | Add |
| `tests/options/test_alias_identity.py` | **New (Step 5)** — `options.data_objects.OptionLeg is portfolio_math.options.OptionLeg`, same for `OptionStrategy` and a payoff function | Add |
| `tests/options/test_payoff.py` | Existing — exercises shim path after Step 4 | Must pass unchanged |
| `tests/options/test_result_objects.py` | Existing — `LegAnalysis` / `StrategyAnalysisResult` | Must pass unchanged |
| `tests/options/test_analyzer.py` | Existing — real `analyze_leg` coverage (Codex R1 correction) | Must pass unchanged |
| `tests/options/test_live_pricing.py` | Existing — IBKR enrichment path | Must pass unchanged |
| `tests/options/test_option_strategy_agent_snapshot.py` | Existing — agent-format output | Must pass unchanged |
| `tests/options/test_trade_preview_pricing.py` | Existing — OptionStrategy consumer (Codex R1 recommend #8) | Must pass unchanged |
| `tests/services/test_trade_execution_service_multileg.py` | Existing — OptionStrategy consumer | Must pass unchanged |
| `tests/brokerage/ibkr/test_adapter_multileg.py` | Existing — OptionStrategy consumer | Must pass unchanged |
| `tests/mcp_tools/test_multi_leg_options.py` | Existing — MCP consumer (Codex R1 recommend #8) | Must pass unchanged |
| `tests/mcp_tools/test_option_strategy_agent_format.py` | Existing — MCP agent-format (Codex R1 recommend #8) | Must pass unchanged |
| AI-excel-addin subprocess integration smoke | New (cross-repo) — sandbox import | Add in AI-excel-addin repo |

---

## 8. Dependencies / risks

### 8.1 Python import layering
`portfolio_math/options.py` (flat module) imports `from ._utils import _norm_cdf, _norm_pdf` and `from .types import GreeksSnapshot` — both pre-existing, unchanged. The appended Domain-types section uses stdlib only. The appended Payoff-math section imports `numpy` (top-of-module) and references `OptionLeg`/`OptionStrategy` defined above it in the same module. No new cross-module imports inside `portfolio_math/`. No cycle.

### 8.2 `LegAnalysis` coupling
`analyze_leg` in `options/payoff.py` returns a `LegAnalysis` that stays in `options/result_objects.py`. If `LegAnalysis` ever gains purity (no `market_bid`/`market_ask`/`price_source`/`greeks_source` fields), it could move later. Not in scope.

### 8.3 Serialization byte-identity
Codex R1 nit #9 correction — actual runtime coupling is narrower than the earlier draft claimed:
- `OptionLeg.to_dict()` → called by `OptionStrategy.to_dict()` → called by `StrategyAnalysisResult.to_dict()` at `options/result_objects.py:130`. This is the one live serialization path.
- `OptionStrategy.to_summary()` has **no current runtime caller** (verified via grep). Preserved for parity.
- `OptionLeg.to_summary()` is called by `OptionStrategy.to_summary()` only.
- `StrategyAnalysisResult.get_agent_snapshot()` builds its payload directly from `strategy.underlying_symbol`, `strategy.underlying_price`, and field values from `self.leg_analysis` — it does **not** call `to_dict()` or `to_summary()` on the domain types, and does **not** include a `generated_at` timestamp.
- `StrategyAnalysisResult.to_dict()` at `options/result_objects.py:129` **does** include `"generated_at": datetime.now().isoformat()`. Characterization must freeze time (see Step 1 for the monkeypatch mechanism).

**Mitigation**: mechanical copy-paste only; no field reordering. **Verification**: Step 1 adds a characterization test (`test_serialization_contract.py`) that locks the full `to_dict()` / `to_summary()` / `get_agent_snapshot()` payloads across representative strategies before any code moves. This is the Codex R1 blocker #2 fix — "mechanical copy" is process discipline; characterization tests are verification.

### 8.4 Docker image
Payoff math uses `numpy` only. Already in `ai-excel-addin-code-exec:latest`. No image rebuild.

### 8.5 Circular import with `options/__init__.py`
`options/__init__.py` does `from .data_objects import OptionLeg, OptionStrategy`. After Step 4, `options/data_objects.py` does `from portfolio_math.options import OptionLeg, OptionStrategy`. `portfolio_math/options.py` and `portfolio_math/__init__.py` do not import from `options/`, so no cycle.

### 8.6 `_parse_expiration` helper
Module-private in `options/data_objects.py`. Moves with `OptionLeg` to `portfolio_math/options.py` (flat-module Domain-types section). No external callers (verified via grep).

### 8.7 Dataclass re-export identity
`from options.data_objects import OptionLeg` and `from portfolio_math.options import OptionLeg` resolve to the **same class object** because `options/data_objects.py` becomes a pure alias shim that `from portfolio_math.options import OptionLeg, OptionStrategy` (no re-declaration). `isinstance(leg, OptionLeg)` works with either import path. Step 5 adds an explicit alias identity test to lock this invariant.

---

## 9. Rollback plan

If any step 2-4 fails a test and the cause isn't obvious within one debugging pass:

- Revert the portfolio_math additions (`git diff -R` the Domain types and Payoff math sections in `portfolio_math/options.py`; remove added top-level re-exports in `portfolio_math/__init__.py`).
- Restore `options/data_objects.py` and `options/payoff.py` from git if shims were already written.
- Step 1 characterization tests remain (low-risk, pure addition; they characterize `main` behavior regardless of extraction state).
- Ship log notes partial completion; 3D remains actionable.

Risk is low — Option A is a pure append + shim flip; no refactor of existing code.

---

## 10. Codex R1 resolutions (2026-04-21)

All R1 findings resolved in v2:

1. **Blocker #1 (Option B breaks imports)** → Plan now defaults to **Option A (flat module)**. Subpackage conversion rejected with explicit reason: `portfolio_math/options.py:7-8` uses sibling-relative imports to `portfolio_math._utils` and `portfolio_math.types`; subpackage move breaks both. §4 rewritten.
2. **Blocker #2 (no characterization tests)** → Step 1 (new, run before any code moves) adds `tests/options/test_serialization_contract.py` locking full `to_dict` / `to_summary` / `get_agent_snapshot` payloads across representative strategies (long call, debit spread, iron condor, stock leg).
3. **Recommend #3 (use Option A)** → Accepted. See §4.
4. **Recommend #4 (curate root payoff exports)** → Accepted at ship time. Reversed 2026-04-22 by `PORTFOLIO_MATH_OPTIONS_ROOT_EXPORT_FIX_PLAN.md`; see §13. Only `leg_payoff`, `strategy_payoff`, `find_breakevens`, `payoff_table` + `OptionLeg`, `OptionStrategy` shipped at root in v3. The other 6 payoff functions were later promoted to `portfolio_math.*` root to match Phase 2's un-curated pricing-primitive pattern.
5. **Recommend #5 (keep `analyze_leg` in `options/payoff.py` shim)** → Accepted. Rationale tightened: real coverage is `tests/options/test_analyzer.py`, not `tests/options/test_payoff.py`. See §5.2 and Step 4.
6. **Recommend #6 (keep `LegAnalysis` out of scope)** → Confirmed. No change needed.
7. **Recommend #7 (explicit alias identity tests)** → Step 5 added: `tests/options/test_alias_identity.py`.
8. **Recommend #8 (fix consumer list)** → §3.4 corrected: `options/portfolio_greeks.py` removed from `OptionLeg`/`OptionStrategy` consumer list (verified — only imports greeks). §7 and Step 4 now include `tests/mcp_tools/test_multi_leg_options.py`, `tests/mcp_tools/test_option_strategy_agent_format.py`, `tests/options/test_trade_preview_pricing.py`.
9. **Nit #9 (serialization coupling overstated)** → §8.3 rewritten: `get_agent_snapshot()` does not call `to_dict`/`to_summary`; `OptionStrategy.to_summary()` has no runtime caller; only `StrategyAnalysisResult.to_dict()` consumes `OptionStrategy.to_dict()`. Characterization test scope still covers all three for parity.

---

## 11. Ship log

**Implementation note**: Codex harness rejected git mutation commands during implementation; code was verified locally (206 tests pass) then staged and committed from Claude per explicit user approval. Per-step scoping preserved except Steps 2 + 3 which are entangled on `portfolio_math/options.py` / `portfolio_math/__init__.py` (same files appended in both steps) — combined into one commit.

- 2026-04-22 — Step 1 complete (`f73c02ef`). `tests/options/test_serialization_contract.py` added; characterization oracle for `to_dict`/`to_summary`/`get_agent_snapshot` across long call, debit spread, iron condor, naked short call, stock-only leg fixtures with monkeypatched `datetime` for timestamp determinism. Required regression suite: `171 passed`.
- 2026-04-22 — Steps 2 + 3 complete (`ec9bd7b0`). `OptionLeg`, `OptionStrategy`, `_parse_expiration`, and 10 pure payoff functions appended to `portfolio_math/options.py` under section headers. `portfolio_math/__init__.py` adds root exports for domain types + 4 curated payoff helpers (`leg_payoff`, `strategy_payoff`, `find_breakevens`, `payoff_table`); other 6 via `from portfolio_math.options import ...`. New tests `tests/test_portfolio_math_options_types.py` + `tests/test_portfolio_math_options_payoff.py`; extended `tests/test_portfolio_math_sandbox_usage.py` with curated-root debit-spread smoke. Required regression suite: `203 passed`. Later reversed by `PORTFOLIO_MATH_OPTIONS_ROOT_EXPORT_FIX_PLAN.md` — see §13.
- 2026-04-22 — Step 4 complete (`684d5ec1`). `options/data_objects.py` → 7-line alias shim; `options/payoff.py` → thin shim re-exporting 10 payoff functions with `analyze_leg` preserved locally (returns `LegAnalysis` which stays in `options/result_objects.py`). Full regression suite including Step 1 serialization oracle passed byte-identically. All consumer imports (`mcp_tools/`, `services/`, `brokerage/`, tests) unchanged.
- 2026-04-22 — Step 5 complete (`c712da3b`). `tests/options/test_alias_identity.py` added: `options.data_objects.OptionLeg is portfolio_math.options.OptionLeg` and parallel assertions for `OptionStrategy` and a payoff function (`find_breakevens`). Required regression suite: `206 passed`.
- 2026-04-22 — Step 8 complete (this commit). `portfolio_math/README.md` Deferred-Scope block updated (option payoff helpers + domain types removed from deferred list). `docs/planning/AGENT_SURFACE_AUDIT.md` Phase 3D row flipped to ✅ SHIPPED. `docs/TODO.md` PM3 entry reflects 3D DONE, 3C ACTIONABLE, optimizer + PM1B DEFERRED. Ship log finalized with real commit SHAs.
- 2026-04-22 — Steps 6 + 7 complete (AI-excel-addin cross-repo, commits `021e8c0` + `9d30875` on branch `feat/investment-idea-plan-4`). Plan: `docs/planning/PORTFOLIO_MATH_OPTIONS_AI_EXCEL_ADDIN_PLAN.md`. Step 6 added `test_code_execute_subprocess_imports_portfolio_math_options` to AI-excel-addin `tests/test_code_execute.py` — mirrors the PM1A template (same `register_docker=False` + `PORTFOLIO_MATH_PATH` env override), pins four canonical values (`pnl=0.0`, `breakevens=[102.0]`, `max_profit=None`, `max_loss=-200.0`) for a long 100 call at $2 premium evaluated at $102; test count went 11 → 12. Step 7 extended `api/agent/shared/system_prompt.py` Portfolio & Risk Data section with explicit root-surface enumeration (pricing / domain types / 10 payoff functions / correlation+stats) so agents don't have to discover `OptionLeg`'s strict constructor signature via `dir()`; existing `tests/test_system_prompt.py:test_code_execution_guidance_includes_risk_section` pinned with 4 new substring assertions (`OptionLeg`, `OptionStrategy`, `strategy_payoff`, `find_breakevens`). AI-excel-addin prompt suite: `3 passed`; broader sweep: `93 passed`. Agent-surface exposure for Phase 3D now end-to-end live — sandbox can `import portfolio_math as pm` and compose `pm.OptionStrategy` + payoff primitives locally without HTTP. Commits land on `main` when `feat/investment-idea-plan-4` merges.

---

## 12. Change log

**v3 (2026-04-21)**: Revised per Codex R2 FAIL. One blocker + three recommends + one nit integrated:
- §8 rewritten to reflect Option A (flat `portfolio_math/options.py`) throughout — removed all stale references to `portfolio_math.options.pricing` / `portfolio_math.options.types` / `portfolio_math.options.payoff` / `portfolio_math/options/types.py` from §8.1, §8.5, §8.6, §8.7.
- Step 1 now specifies explicit `datetime` monkeypatch mechanism for `StrategyAnalysisResult.to_dict()` timestamp freeze.
- Step 1 fixture matrix now names explicit unlimited-loss fixture (naked short call).
- Step 3 extended to cover `tests/test_portfolio_math_sandbox_usage.py` for new curated root exports.
- Step 8 now includes `portfolio_math/README.md` deferred-scope update.

**v2 (2026-04-21)**: Revised per Codex R1 FAIL. Two blockers fixed (Option B → Option A; characterization tests added as Step 1). Seven recommends integrated (curated root exports, `analyze_leg` placement rationale, `LegAnalysis` scope confirmed, alias identity tests, consumer list correction, serialization coupling clarification). Implementation expanded from 7 steps to 8 (Step 1 is new characterization phase).

**v1 (2026-04-21)**: Initial draft. FAIL at Codex R1.

---

## 13. Post-ship correction (2026-04-22)

`PORTFOLIO_MATH_OPTIONS_ROOT_EXPORT_FIX_PLAN.md` reversed the curated root-export decision from Step 3 and promoted the remaining 6 payoff functions (`max_profit`, `max_loss`, `intrinsic_value`, `extrinsic_value`, `cost_of_leverage_annualized`, `pnl_per_dollar_move`) to `portfolio_math.*` root.

Rationale for the reversal:
1. The "accept Codex scope reduction early" rule was applied to an API-surface decision rather than to implementation scope. Re-exporting the full payoff surface has effectively zero marginal implementation cost, so the curation needed its own justification and did not have one.
2. Curating the "4 most-used" payoff helpers at root repeated the same workflow-prediction anti-pattern rejected in `docs/planning/AGENT_SURFACE_AUDIT.md` on 2026-04-21. Capability extraction is about enabling local composition, not predicting in advance which helpers the agent will prefer.
3. The curated payoff surface was inconsistent with Phase 2, which exported all 5 pricing primitives at `portfolio_math.*` root without curation. The default for peer capability packages is symmetry unless there is a concrete collision or maintenance cost.

Historical note: this section records the reversal only. §4 and §6 Step 3 remain historically accurate descriptions of what v3 shipped on 2026-04-22 before the follow-up root-export correction landed.
