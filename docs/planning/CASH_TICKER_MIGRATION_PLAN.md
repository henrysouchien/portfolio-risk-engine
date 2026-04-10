# Cash Ticker Migration Plan

**Status**: APPROVED — Codex PASS R5 (2026-04-10)
**Last updated**: 2026-04-10
**Review history**: R1 FAIL (5 blocking + 2 non-blocking) → R2 FAIL (5 + 1) → R3 FAIL (4 + 2) → R4 FAIL (2 + 1) → **R5 PASS**
**Source signal**: A5arch.2 (Lane A architectural follow-up from A5 compare eval)
**Related prior work**:
- `b5ff9122` — Cash Semantics Optimizer Fix (covered main optimizer path)
- `5d615e18` — A5.2 (min_variance/max_return `CUR:USD` KeyError) and A5.10 (beta limits NaN guard)
- Plan: `docs/planning/completed/CASH_SEMANTICS_OPTIMIZER_FIX_PLAN.md`
- Plan: `docs/planning/COMPARE_A5_2_10_CASH_TICKER_GUARDS_PLAN.md`

---

## Problem

Cash ticker detection and handling is scattered across dozens of files with many competing patterns. Measured 2026-04-10 via `git grep` (excluding tests/docs/e2e/frontend):
- ~104 `CUR:` references across ~44 Python files
- ~54 `.startswith("CUR:")` call sites across ~33 files (the most common inline pattern)
- 7 competing predicate functions with inconsistent logic

Each `CUR:USD` bug that surfaces (A5.2, A5.10, and counting) patches one callsite while leaving the rest unchanged.

### Scatter evidence (verified 2026-04-10)

| Predicate | File:Line | Logic | Notes |
|-----------|-----------|-------|-------|
| `is_cash_ticker(ticker)` | `portfolio_risk_engine/portfolio_config.py:72` | `ticker.startswith("CUR:")` OR `ticker in cash_positions` (YAML-backed lazy set) | **Canonical** — but only 7 files use it |
| `_is_cash_position(ticker, position_type, is_cash_equivalent)` | `portfolio_risk_engine/data_objects.py:85` | `position_type == "cash"` OR `ticker.upper().startswith("CUR:")` OR `is_cash_equivalent is True` | **Uses `.upper()` — inconsistent with canonical** |
| `_is_cash_proxy(ticker)` | `services/returns_service.py:531` | `ticker.startswith("CUR:")` OR loads `cash_map.yaml` on every call (no caching) | **Name misleading** — matches both CUR:* and proxy ETFs |
| `_is_cash_coverage_ticker(ticker, security_identities)` | `portfolio_risk_engine/portfolio_risk.py:117` | Checks `security_identities[ticker].instrument_category == "cash"`, falls back to `is_cash_ticker()` | **Legitimately different** — security-identity path |
| `_is_cash_position(position, ticker)` | `routes/hedging.py:55` | `position_type == "cash"` OR `ticker.startswith("CUR:")` | Duplicate of data_objects version, no `.upper()` |
| `_is_cash_position(position, ticker)` | `mcp_tools/rebalance.py:36` | Same pattern, no `.upper()` | Duplicate |
| `_is_cash_like_position(position)` | `mcp_tools/positions.py:201` | Same pattern, no `.upper()` | Duplicate with different name |

**Inline patterns**: ~54 direct `.startswith("CUR:")` sites across ~33 files (plus ~50 more `CUR:`-related calls in non-`.startswith` forms including pandas `.str.startswith("CUR:", na=False)` and single-quoted variants). Some use `.upper()`, some don't. Some also check `position_type == "cash"`, some don't. Some check `is_cash_equivalent`, some don't.

### Structural finding (from A5arch.2 investigation)

Cash handling is **architecturally irreducible** — cash must flow through risk matrices for variance calculations, so there is no single upstream chokepoint where cash could be filtered out. This plan does NOT attempt to centralize cash enforcement. Instead it:

1. Consolidates predicates to a small canonical set
2. Migrates inline callsites to use them
3. Adds a drift-prevention test so new inline checks fail at PR time

### Bug pattern this prevents

The recurring pattern is: a new constraint loop or validation path is added, copies the inline `ticker.startswith("CUR:")` style from neighboring code, forgets some edge case (`.upper()`, `math.isfinite`, `.get(t, {})`), and breaks on `CUR:USD` portfolios. Each fix addresses one site. This plan makes the canonical path easier to use than the wrong path.

---

## Goal

Collapse cash-ticker handling to a canonical surface (4 predicates + 2 helpers) with clear per-callsite routing guidance, migrate the ~44 files and their inline checks, and install drift prevention so the scatter can't regrow.

## Non-goals

- **Refactoring `cash_map.yaml` structure** — the YAML is already the source of truth; this plan only consolidates the Python helpers that read it.
- **Type-level distinction** (e.g., `CashTicker` vs `EquityTicker` subclass) — Python `str` subclassing is too expensive for this repo's hot paths.
- **Upstream cash filtering** — cash must flow through risk matrices; any attempt to filter upstream breaks variance calculations.
- **Changing ingestion cash detection** in `inputs/position_schema.py` — working correctly, out of scope.
- **Touching `_is_cash_coverage_ticker`** beyond confirming it delegates to canonical `is_cash_ticker()` for the string check — the security-identity path is legitimately different and should stay.

---

## Design

### Canonical surface

**New module**: `core/cash_helpers.py` — owns all 6 public functions directly. The implementation moves from `portfolio_risk_engine/portfolio_config.py:72`, but the old location stays as a thin shim (`from core.cash_helpers import is_cash_ticker`) during the migration window. Phase 5 deletes the shim after the drift test passes on clean state.

**Phase 1 gate (pre-verified by Codex review 2026-04-10)**: `resolve_config_path` lives at `config/__init__.py:7` and is importable from `core/` without creating a cycle with `portfolio_risk_engine/`. No prerequisite work needed.

**Public predicates (4)**:

```python
def is_cur_ticker(ticker: str) -> bool:
    """True if the ticker is a CUR:* synthetic currency ticker (case-insensitive).

    NARROW: matches only the CUR:USD-style prefix format. Does NOT match
    proxy ETFs (SGOV, ERNS.L, IBGE.L) or broker-format aliases (CASH, USD:CASH).

    Use this for raw-format detection at providers, inputs, symbol resolution,
    and anywhere you want to distinguish "is this a synthetic currency ticker"
    from "is this any kind of cash representation".
    """


def is_cash_proxy_ticker(ticker: str) -> bool:
    """True if the ticker is a CUR:* OR a currency proxy ETF (SGOV, ERNS.L, IBGE.L).

    MEDIUM: matches CUR:* prefix AND the values of cash_map.yaml's
    `proxy_by_currency` map. Does NOT match broker-format aliases like CASH.

    Use this in the returns-generation pipeline where we want to synthesize
    cash-like returns for both raw CUR:* positions and the ETFs that proxy
    them. Preserves the exact semantics of the old `_is_cash_proxy` helper.
    """


def is_cash_ticker(ticker: str) -> bool:
    """True if the ticker represents any form of cash/cash-equivalent.

    BROAD: matches CUR:* prefix (case-insensitive), proxy ETFs from
    `proxy_by_currency`, AND broker-format aliases from `alias_to_currency`
    (CASH, USD:CASH, etc.). This is the widest of the three ticker predicates.

    Use this for display labeling, ingestion-time detection, and any callsite
    that needs to recognize cash-like symbols regardless of format.
    """


def is_cash_position(position: Mapping[str, Any]) -> bool:
    """True if a position dict represents a cash holding.

    Checks (in order): position['type'] == 'cash', is_cur_ticker(ticker).

    **Two-way check** (type + CUR:*), NOT three-way. Does NOT check the
    `is_cash_equivalent` field. This preserves the semantics of the 3 old
    majority callsites (routes/hedging.py:55, mcp_tools/rebalance.py:36,
    mcp_tools/positions.py:201) which were all 2-way.

    The one old callsite that WAS 3-way (portfolio_risk_engine/data_objects.py:85)
    migrates to `is_cash_position(p) or p.get("is_cash_equivalent") is True` —
    an explicit extra check at that one site only. Uses strict `is True`
    (NOT `bool(...)`) to match the old `data_objects.py:91` behavior exactly.
    Truthy non-bool values like `"false"`, `"yes"`, or `1` must NOT be treated
    as cash. This avoids a behavior expansion at the 3 majority sites (where
    proxies marked `is_cash_equivalent=True` at routes/positions.py:572 would
    newly be classified as cash).

    Uses is_cur_ticker (narrow) NOT is_cash_ticker (broad) — same rationale:
    broadening would newly match SGOV/CASH at migrated paths.

    Use this at position-level callsites (MCP tools, routes, rebalance,
    hedging). For ticker-only callsites, use the appropriate ticker predicate
    above (is_cur_ticker / is_cash_proxy_ticker / is_cash_ticker).
    """
```

**Public helpers (2)**:

```python
def cash_proxy_for_currency(currency: str) -> str | None:
    """Return the proxy ETF ticker for a given ISO currency (USD → SGOV,
    GBP → ERNS.L, EUR → IBGE.L), or None if not mapped. YAML-backed."""


def currency_for_ticker(ticker: str) -> str | None:
    """Return the ISO currency code for a cash ticker (CUR:USD → USD),
    or None if the ticker is not a cash representation. Uses the CUR:*
    prefix and YAML alias_to_currency map."""
```

**Picking the right ticker predicate**:

| Question the callsite is answering | Use |
|-------------------------------------|-----|
| Is this specifically a `CUR:*` synthetic currency ticker? | `is_cur_ticker` (narrow) |
| Should the returns service synthesize cash-like returns for this? | `is_cash_proxy_ticker` (medium) |
| Is this any kind of cash representation (for display, ingestion, UI)? | `is_cash_ticker` (broad) |
| Is this dict a cash position (type + `CUR:*` format, 2-way check)? | `is_cash_position` |

### Deprecation map

| Old predicate / pattern | New | Notes |
|-------------------------|-----|-------|
| `portfolio_risk_engine.portfolio_config.is_cash_ticker` | `core.cash_helpers.is_cash_ticker` (broad) | Same semantics as today; `.upper()` added for case-insensitivity. Phase 1 adds a thin re-export shim at the old location; Phase 5 deletes the shim after the drift test passes. |
| `portfolio_risk_engine.data_objects._is_cash_position` | `core.cash_helpers.is_cash_position` (dict) | Public API. Single-argument (position dict) version, **2-way check** (type + `is_cur_ticker`). The old 3-way semantics at this one callsite is preserved by adding an explicit `or p.get("is_cash_equivalent") is True` at the 3 migrated call sites in data_objects.py (see Phase 2 notes for the strict `is True` rationale). |
| `services.returns_service._is_cash_proxy` | `core.cash_helpers.is_cash_proxy_ticker` (medium) | **Preserves exact semantics** — matches `CUR:*` + proxy ETFs from `proxy_by_currency`, does NOT expand to broker-format aliases. Also drops the per-call YAML reload (uses the cached lazy set). |
| `services.position_metadata.is_cash_position(ticker, cash_positions)` | `core.cash_helpers.is_cash_ticker` (**broad**) | **Name collision + semantic routing**. The old service helper delegated to broad `is_cash_ticker` at `services/position_metadata.py:78`, so its callers expect broad semantics (proxies + aliases). Callers at `services/position_metadata.py:58` (in-module fallback), `services/portfolio_service.py:2288` (debug), `services/portfolio_service.py:2291` (price-refresh skip), `app.py:4560` (import), `app.py:4566` (display labeling) all migrate to **`is_cash_ticker(ticker)`**, NOT dict `is_cash_position`. Resolves name collision by deleting the old 2-arg function atomically in Phase 1. |
| `routes.hedging._is_cash_position` | `core.cash_helpers.is_cash_position` (dict) | Drop local helper. |
| `mcp_tools.rebalance._is_cash_position` | `core.cash_helpers.is_cash_position` (dict) | Drop local helper. |
| `mcp_tools.positions._is_cash_like_position` | `core.cash_helpers.is_cash_position` (dict) | Drop local helper (including the misleading `_like_` naming). |
| Raw `ticker.startswith("CUR:")` in providers / inputs / symbol resolution | `core.cash_helpers.is_cur_ticker` (narrow) | Callsites like `providers/plaid_loader.py:113`, `providers/symbol_resolution.py:106`, `inputs/position_schema.py:185`, `services/factor_proxy_service.py:363` want "raw `CUR:*` format" semantics, NOT "any cash". Migrating them to the broad `is_cash_ticker` would change behavior (SGOV would start matching). |
| Raw `ticker.startswith("CUR:")` in display / flag-generation / UI code | `core.cash_helpers.is_cash_ticker` (broad) | These callsites want "is this any kind of cash" — the broad predicate is correct. Spot-check each during migration to confirm intent. |
| `portfolio_risk_engine.portfolio_risk._is_cash_coverage_ticker` | **KEEP** | Legitimately different — uses security_identities first. Internally delegates to `is_cash_ticker` for the fallback string check (already does). |

### Case-sensitivity decision

**Resolution**: `is_cash_ticker` currently uses bare `startswith("CUR:")`; `_is_cash_position` uses `.upper().startswith("CUR:")`. The canonical format is `CUR:USD` (upper), but defensive matching prevents bugs from broker feed casing drift.

**Decision**: Canonical `is_cash_ticker` gains `.upper()` for defensive matching. Existing callsites that already use bare `startswith` get stricter-compatible behavior (upper-match is a superset of bare-match).

### Constraint loop hardening

Separate but adjacent: the pattern `proxies[t].get("industry")` crashes on `CUR:USD` because `t` isn't in `proxies`. The A5.2 fix uses `proxies.get(t, {}).get("industry")` at `portfolio_optimizer.py:321`. **Codex review (2026-04-10) pre-verified**: no remaining unsafe bracket patterns in `portfolio_optimizer.py`, `efficient_frontier.py`, or `scenario_analysis.py`. Phase 2 includes a final grep-based confirmation pass but zero fixes are expected.

---

## Phased implementation

### Phase 1 — Canonical helpers + name-collision fix (~1 day)

**Scope**: Create `core/cash_helpers.py` with all 6 public functions (4 predicates + 2 helpers). Install a thin re-export shim at `portfolio_risk_engine/portfolio_config.py`. Resolve the name collision at `services/position_metadata.py:66` by migrating it and its caller atomically so there's no period where two `is_cash_position` functions coexist.

**Files touched**:
- **New**: `core/cash_helpers.py` (owns the implementation)
- **New**: `tests/core/test_cash_helpers.py`
- `portfolio_risk_engine/portfolio_config.py` — replace existing `is_cash_ticker` body with `from core.cash_helpers import is_cash_ticker` shim. Preserves imports at `services/position_metadata.py:10`, `portfolio_risk_engine/portfolio_risk.py:125`, and other current consumers during the migration window.
- `services/position_metadata.py` — delete the existing `is_cash_position(ticker, cash_positions)` 2-arg public function AND migrate the in-module fallback caller at line 58 to use `core.cash_helpers.is_cash_ticker(ticker)` (**broad**, not dict helper). R3 Codex finding: the old service helper delegated to broad `is_cash_ticker` at line 78, so callers expect broad semantics (proxies + aliases), not narrow dict check.
- `services/portfolio_service.py` — migrate the import at line 2257 (R4 Codex finding) AND **both callers** at lines 2288 (debug call) and 2291 to use `core.cash_helpers.is_cash_ticker(ticker)` (**broad**). Line 2291 is a price-refresh skip, which needs broad semantics to correctly skip proxy ETFs.
- `app.py` — migrate the import at line 4560 and the caller at line 4566 to use `core.cash_helpers.is_cash_ticker(ticker)` (**broad**). Line 4566 is display labeling, which needs broad semantics to label proxy ETFs as cash.
- `tests/services/test_portfolio_service_futures.py` — migrate monkeypatch targets at lines 21 and 51 (**R3 Codex finding**: these tests monkeypatch `services.position_metadata.is_cash_position`, which is being deleted; update to patch `core.cash_helpers.is_cash_ticker` or restructure the tests).

**Deliverables**:
- `core/cash_helpers.py` with 4 predicates + 2 helpers (`is_cur_ticker`, `is_cash_proxy_ticker`, `is_cash_ticker`, `is_cash_position`, `cash_proxy_for_currency`, `currency_for_ticker`)
- Shim re-export at `portfolio_risk_engine/portfolio_config.py`
- `tests/core/test_cash_helpers.py` — ~25 tests covering:
  - `is_cur_ticker`: `CUR:USD`, `cur:usd`, `CUR:EUR`, `CUR:GBP` → True; `SGOV`, `CASH`, `AAPL` → False
  - `is_cash_proxy_ticker`: `CUR:USD`, `SGOV`, `ERNS.L`, `IBGE.L` → True; `CASH`, `USD:CASH`, `AAPL` → False
  - `is_cash_ticker`: `CUR:USD`, `SGOV`, `CASH`, `USD:CASH` → True; `AAPL` → False
  - `is_cash_position` with position dicts — 2-way check only: `type="cash"` matches, `CUR:*` ticker matches, `is_cash_equivalent=True` does **NOT** match (R4 Codex finding: the helper is 2-way; the 3-way behavior only applies at the data_objects.py callsite via an explicit `or p.get("is_cash_equivalent") is True`)
  - `cash_proxy_for_currency("USD")` → `"SGOV"`, unknown currency → `None`
  - `currency_for_ticker("CUR:USD")` → `"USD"`, non-cash → `None`
- `services/position_metadata.is_cash_position` deleted; all live callers + both import sites migrated: `position_metadata.py:58` (call), `portfolio_service.py:2257` (import), `portfolio_service.py:2288,2291` (calls), `app.py:4560` (import), `app.py:4566` (call) — all to broad `is_cash_ticker`
- `tests/services/test_portfolio_service_futures.py` monkeypatch targets at lines 21 and 51 updated
- Existing tests for `position_metadata.py` and `portfolio_service.py` still pass

**Exit criteria**: All new tests pass. `is_cur_ticker("cur:usd")` returns True. Name collision resolved: `git grep 'def is_cash_position'` shows only the `core/cash_helpers.py` definition. Existing imports of `is_cash_ticker` from `portfolio_risk_engine.portfolio_config` still work via shim.

### Phase 2 — Migrate risk-critical paths (~1 day)

**Scope**: Migrate the 3 risk-engine/service files where cash bugs have actually surfaced. Constraint loop audit downscoped to verification only (Codex pre-verified no remaining unsafe patterns).

**Files touched**:
- `portfolio_risk_engine/data_objects.py` — delete `_is_cash_position`, import `is_cash_position` from `core.cash_helpers`. Update 3 callsites. **Note** (R3 Codex finding): the old `_is_cash_position` here was the ONE 3-way callsite that also checked `is_cash_equivalent`. The new `is_cash_position` helper is 2-way, so the 3 migrated callsites at data_objects.py become `is_cash_position(p) or p.get("is_cash_equivalent") is True` — strict `is True` comparison (NOT `bool(...)`) to preserve the old `data_objects.py:91` behavior exactly (truthy non-bool values like `"false"`, `"yes"`, `1` must NOT be treated as cash). Add a regression test asserting this.
- `portfolio_risk_engine/portfolio_risk.py` — confirm `_is_cash_coverage_ticker` delegates to canonical `is_cash_ticker` (already does). Remove inline `startswith` at line 856. Migrate the `is_cash_ticker` import from `portfolio_risk_engine.portfolio_config` to `core.cash_helpers`.
- `services/returns_service.py` — delete `_is_cash_proxy`, use `is_cash_proxy_ticker` (medium predicate — **preserves exact semantics**, does NOT expand to broker-format aliases). **Drop the per-call YAML reload** — latent perf bug.
- `portfolio_risk_engine/portfolio_optimizer.py`, `efficient_frontier.py`, `scenario_analysis.py` — **verification pass only**: grep for `proxies[t]`, `stock_factor_proxies[t]`, `beta_mat.loc[t` without safe guards. Expected: zero fixes needed (Codex pre-verified 2026-04-10).

**Deliverables**:
- 3 files migrated (data_objects, portfolio_risk, returns_service)
- Constraint loop verification report (appended to PR description) confirming zero unsafe bracket patterns in optimizer/frontier/scenario files
- Existing tests pass (no regression)
- New integration test: `tests/core/test_cash_semantics_integration.py` — runs a portfolio with `CUR:USD` + `CUR:EUR` through `min_variance`, `max_return`, `target_volatility`, `max_sharpe`, beta limits validation, risk analysis. Single test exercising the full cash-through-pipeline path.

**Exit criteria**: All existing tests pass. New integration test passes. `git grep -nE '\.startswith\(["\x27][Cc][Uu][Rr]:["\x27](,|\))' -- 'portfolio_risk_engine/' 'services/returns_service.py'` (broad regex matching Phase 4 drift test — R3 Codex non-blocking finding) returns empty. Constraint loop verification report shows zero issues.

### Phase 3 — Migrate remaining callsites (split into 3 sub-phases)

Split into 3 PRs for reviewable footprint. Each sub-phase gets its own Codex review round, tests run, and grep-based exit check scoped to its subtree. Risk isolation: if 3a breaks something, 3b/3c are unaffected.

#### Phase 3a — MCP tools (~9 files, ~1-1.5 days)

**Files touched**: `mcp_tools/positions.py`, `rebalance.py`, `tax_harvest.py`, `transactions.py`, `baskets.py`, `basket_trading.py`, `factor_intelligence.py`, `news_events.py` (**added after R1 Codex review — Codex found `news_events.py:267`**), `risk.py` (**added after R1 Codex review — Codex found `risk.py:406`**). Also delete private helpers: `_is_cash_like_position` (positions.py), `_is_cash_position` (rebalance.py).

Each callsite uses the per-callsite routing guidance in the Deprecation Map: raw-format callsites get `is_cur_ticker`, display/flag callsites get `is_cash_ticker`, dict-level checks get `is_cash_position`.

**Deliverables**:
- Inline `startswith("CUR:")` replaced with the appropriate `core.cash_helpers` predicate across MCP tools
- Private `_is_cash_*` helpers deleted from `mcp_tools/`
- Existing MCP tool tests pass

**Exit criteria**: `git grep -nE '\.startswith\(["\x27][Cc][Uu][Rr]:["\x27](,|\))' -- 'mcp_tools/'` returns empty. `git grep 'def _is_cash_' -- 'mcp_tools/'` returns empty.

#### Phase 3b — Routes, inputs, actions (~6 files, ~0.5 day)

**Files touched**: `routes/hedging.py`, `routes/onboarding.py`, `inputs/position_schema.py`, `inputs/portfolio_assembler.py`, `actions/portfolio_management.py`, `actions/income_projection.py`. Also delete `_is_cash_position` from `routes/hedging.py`.

**Deliverables**:
- Inline checks replaced across routes + inputs + actions
- Private `_is_cash_*` helpers deleted from `routes/`
- Existing route/input tests pass

**Exit criteria**: `git grep -nE '\.startswith\(["\x27][Cc][Uu][Rr]:["\x27](,|\))' -- 'routes/' 'inputs/' 'actions/'` returns empty (broad regex matching the Phase 4 drift-test form — R2 Codex finding: previous narrow regex missed pandas and single-quoted variants). `git grep 'def _is_cash_' -- 'routes/'` returns empty.

#### Phase 3c — Services, providers, utils, core (~17 files, ~1-1.5 days)

**Files touched**:
- Services: `services/position_service.py`, `portfolio_service.py` (remaining callsites beyond the Phase 1 migration), `validation_service.py`, `security_type_service.py`, `factor_proxy_service.py`, `trade_execution_service.py` (**added after R1 Codex review**), `factor_intelligence_service.py` (**added after R2 Codex review — imports shim at line 24, uses it at line 1568**).
- Providers: `providers/snaptrade_loader.py`, `plaid_loader.py`, `symbol_resolution.py` (**added after R1 Codex review**), `normalizers/plaid.py` (**added after R2 Codex review — has equality check `ticker in {"CUR:USD", "DEPOSIT"}` at line 222, migrate to `is_cur_ticker(ticker) or ticker == "DEPOSIT"`**).
- Utils: `utils/ticker_resolver.py` (**added after R1 Codex review**).
- Core: `core/position_flags.py`, `core/result_objects/positions.py` (**added after R1 Codex review**), `core/realized_performance/*` (~5 files).

Each callsite uses the per-callsite routing guidance in the Deprecation Map.

**Deliverables**:
- Inline checks replaced across services + providers + utils + remaining core
- Existing service/provider tests pass
- All callsites of the temporary `portfolio_risk_engine.portfolio_config.is_cash_ticker` shim migrated to `core.cash_helpers.is_cash_ticker` (enables Phase 5 cleanup)

**Exit criteria**: `git grep -nE '\.startswith\(["\x27][Cc][Uu][Rr]:["\x27](,|\))' -- 'services/' 'providers/' 'utils/' 'core/' ':!core/cash_helpers.py'` returns empty. **Equality/substring checks** (not caught by the drift regex) are tracked separately in this phase's PR description — including `providers/normalizers/plaid.py:222` and any others surfaced during migration. The external import check uses a multi-import-aware regex: `git grep -nE 'from portfolio_risk_engine\.portfolio_config import .*\bis_cash_ticker\b'` returns empty across all external files (R3 Codex finding: plain string match misses multi-import forms like `from X import (a, b, is_cash_ticker)` at `services/position_metadata.py:10`). The shim import inside `portfolio_config.py` itself is allowed — see Phase 5 for the cleanup. Repo-wide Phase 4 drift test passes on clean state.

### Phase 4 — Drift-prevention test (~2 hours)

**Scope**: Add a pytest that runs in CI and fails when new inline `CUR:` checks or new private cash predicates appear. Regex catches both quote styles, pandas `.str.startswith(..., na=False)` form, and case-insensitive `CUR:` prefix (addresses R1 Codex finding #2).

**Deliverable**: `tests/test_cash_ticker_discipline.py`:

```python
"""Prevent regression of A5arch.2 — no inline CUR: checks outside core/cash_helpers."""

import subprocess
from pathlib import Path

WHITELIST = {
    "core/cash_helpers.py",                         # canonical home
    "tests/",                                        # test fixtures
    "docs/",                                         # plan docs, examples
    "portfolio_risk_engine/portfolio_config.py",    # temporary shim (deleted in Phase 5)
}

# Matches both .startswith("CUR:") and .str.startswith("CUR:", na=False),
# both single and double quotes, case-insensitive CUR prefix.
STARTSWITH_PATTERN = r'\.startswith\(["\x27][Cc][Uu][Rr]:["\x27](,|\))'

def _is_whitelisted(path: str) -> bool:
    return any(path.startswith(w) for w in WHITELIST)

def test_no_inline_cur_prefix_checks():
    """New code must use the appropriate core.cash_helpers predicate.

    Catches:
    - .startswith("CUR:")    (standard form)
    - .startswith('CUR:')    (single-quoted)
    - .str.startswith("CUR:", na=False)  (pandas form, via the optional comma)
    - Case variations: "cur:", "Cur:", etc.
    """
    result = subprocess.run(
        ["git", "grep", "-nE", STARTSWITH_PATTERN],
        capture_output=True, text=True, cwd=Path(__file__).parent.parent,
    )
    violations = [
        line for line in result.stdout.splitlines()
        if line and not _is_whitelisted(line.split(":", 1)[0])
    ]
    assert not violations, (
        f"Found {len(violations)} inline CUR: check(s) outside core/cash_helpers.py:\n"
        + "\n".join(violations)
        + "\n\nUse is_cur_ticker / is_cash_proxy_ticker / is_cash_ticker / is_cash_position "
        + "from core.cash_helpers instead (see Deprecation Map for per-callsite guidance)."
    )

def test_no_private_cash_helpers():
    """Private cash ticker/position helpers should live only in core/cash_helpers.py.

    Regex narrowed (R2 Codex finding): only matches the specific helper names
    this migration owns. Does NOT match unrelated helpers like
    `_is_cash_equivalent_round_trip` in trading_analysis/analyzer.py:139.
    """
    result = subprocess.run(
        ["git", "grep", "-nE", r'def _is_cash_(ticker|position|proxy|like_position|coverage_ticker)\b'],
        capture_output=True, text=True, cwd=Path(__file__).parent.parent,
    )
    # _is_cash_coverage_ticker is legitimately different (security-identity path)
    ALLOWED = {"portfolio_risk_engine/portfolio_risk.py"}
    violations = [
        line for line in result.stdout.splitlines()
        if line and not _is_whitelisted(line.split(":", 1)[0])
        and not any(line.startswith(a) for a in ALLOWED)
    ]
    assert not violations, (
        f"Found {len(violations)} private cash ticker/position helper(s):\n"
        + "\n".join(violations)
        + "\n\nUse is_cash_position() from core.cash_helpers instead."
    )

def test_no_regression_on_pandas_form():
    """Explicit test: pandas .str.startswith form must be caught by the regex."""
    import re
    assert re.search(STARTSWITH_PATTERN, 'df["ticker"].str.startswith("CUR:", na=False)')
    assert re.search(STARTSWITH_PATTERN, "df['ticker'].str.startswith('CUR:', na=False)")
    assert re.search(STARTSWITH_PATTERN, 't.startswith("cur:")')  # case-insensitive
    assert not re.search(STARTSWITH_PATTERN, 'ticker == "CUR:USD"')  # equality not caught
```

**Exit criteria**: All 3 tests pass on clean repo. Artificial regression (add `.startswith("CUR:")` or `.str.startswith("CUR:", na=False)` inline anywhere) triggers test failure.

**Known gap — equality and substring checks are NOT caught automatically**: The drift regex only matches `.startswith(...)` patterns. Other cash-detection forms must be identified manually during migration and covered in phase PR descriptions:
- Equality: `ticker == "CUR:USD"`, `ticker in {"CUR:USD", ...}` (see `providers/normalizers/plaid.py:222` — migrated in Phase 3c)
- Substring: `"CUR:" in ticker`
- Slice: `ticker[:4] == "CUR:"`

Adding regex patterns for these would produce too many false positives (any `== "CUR:..."` comparison for documentation or logging). Per-phase manual review is the required discipline.

### Phase 5 — Delete temporary shim (~15 min)

**Scope**: After Phase 3c migrates all callsites to `core.cash_helpers` directly, delete the temporary shim at `portfolio_risk_engine/portfolio_config.py` (addresses R1 Codex finding #5 — resolves the "delete vs re-export" contradiction).

**Files touched**:
- `portfolio_risk_engine/portfolio_config.py` — convert the public re-export `from core.cash_helpers import is_cash_ticker` to a private alias `from core.cash_helpers import is_cash_ticker as _is_cash_ticker`, then update the 2 internal callers in `standardize_portfolio_input` (lines 221, 245) to use `_is_cash_ticker`. This breaks the external import path `from portfolio_risk_engine.portfolio_config import is_cash_ticker` while keeping `standardize_portfolio_input` working. R2 Codex finding: `portfolio_config.py:221,245` uses `is_cash_ticker` internally — we can't just delete the import.
- Clean up any related lazy proxies (`_LazyCashPositions`, `cash_positions`) if they become orphaned. Keep `get_cash_positions()` and other unrelated functions untouched.
- Remove `portfolio_risk_engine/portfolio_config.py` from the Phase 4 drift-test WHITELIST.

**Deliverables**:
- Shim converted to private alias; `standardize_portfolio_input` callers updated
- Drift test whitelist updated
- Full test suite passes (confirms no latent external imports from the old location)

**Exit criteria**: Drift test passes. All other tests pass. `git grep -nE 'from portfolio_risk_engine\.portfolio_config import .*\bis_cash_ticker\b'` (multi-import-aware regex, R3 Codex finding) returns empty across all files **except** `portfolio_risk_engine/portfolio_config.py` itself (which uses the private alias form `as _is_cash_ticker`). The textual reference inside `portfolio_config.py` is expected and correct — we only care that external callers can no longer import the public name.

---

## Test strategy

- **Phase 1**: Unit tests for all 4 canonical functions (~20 tests)
- **Phase 2**: Integration test that runs a CUR:* portfolio through the full risk pipeline (min_variance, max_return, target_volatility, max_sharpe, beta limits, risk analysis)
- **Phase 3**: Existing tests must pass (behavior-preserving migration). Spot-check 2-3 randomly chosen migrated sites manually for semantic equivalence.
- **Phase 4**: Drift test + artificial regression test
- **Full suite**: Run `pytest tests/` after each phase

---

## Risk assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Subtle behavioral difference from `.upper()` addition to `is_cash_ticker` | Low | Upper-match is a strict superset of bare-match. Codex R1 pre-verified no lowercase `"cur:"` string literals exist in the codebase. |
| Missed inline callsite during migration (pandas or single-quoted forms) | Medium | Phase 4 drift test uses a broader regex catching `.startswith("CUR:")`, `.startswith('CUR:')`, and `.str.startswith("CUR:", na=False)`. Plus grep-based confirmation at exit of each sub-phase. |
| Wrong predicate chosen at a callsite (e.g., using broad `is_cash_ticker` where `is_cur_ticker` is semantically correct) | Medium | Per-callsite guidance in the Deprecation Map routes each category to the right predicate. Codex review of each sub-phase PR catches semantic misroutings. Integration test covers risk-critical paths. |
| `_is_cash_coverage_ticker` accidentally changed | Low | Explicit non-goal; keeper annotated in plan. |
| Removing `_is_cash_proxy` YAML per-call reload introduces cache staleness | Low | Cache is already in place via `_get_cash_positions_cached()` (lazy-loaded, process-lifetime stable). No race found by Codex R1. Document the staleness window (YAML changes require process restart) in the new helper docstring. |
| `is_cash_position` dict-only signature incompatible with existing callsites | Low | Phase 1 migrates the 5 live callers of the old 2-arg `services.position_metadata.is_cash_position` (all route to **broad** `is_cash_ticker`, not dict helper — old helper had broad semantics). Future new callsites that genuinely need the dict helper pass a position dict directly. |
| Name collision with existing `services.position_metadata.is_cash_position(ticker, cash_positions)` | Medium | Resolved in Phase 1 by deleting the old 2-arg function and migrating its caller atomically with the new helper introduction. No period where two `is_cash_position` functions coexist. |
| Temporary shim at `portfolio_risk_engine/portfolio_config.py` outliving its purpose | Low | Phase 5 explicitly deletes it with a grep-based exit check. Not part of the permanent architecture. |

## Rollback

- **Phase 1**: revertable — the shim + name-collision fix is one commit. Revert restores both sides.
- **Phase 2**: revertable per-file if a migration breaks something
- **Phase 3a/3b/3c**: revertable per sub-phase or per-file
- **Phase 4**: drift test can be skipped via pytest marker if it produces false positives
- **Phase 5**: revert the shim deletion if any latent import is discovered post-merge

No data migrations, no schema changes, no runtime behavior changes (except the latent perf fix in returns_service and the `.upper()` case-insensitivity addition which is a pure superset).

---

## Codex review checklist (R2)

Previously answered in R1 and now locked:
- ✅ `resolve_config_path` is importable from `core/` without cycle (lives at `config/__init__.py:7`)
- ✅ No lowercase `"cur:"` string literals in codebase — `.upper()` addition is safe
- ✅ A5.2 `.get(t, {})` fix is in place at `portfolio_optimizer.py:321`; no remaining unsafe bracket patterns in `portfolio_optimizer.py`, `efficient_frontier.py`, or `scenario_analysis.py`

Remaining for R2 review:
- [ ] Is the 4-predicate canonical API (`is_cur_ticker` / `is_cash_proxy_ticker` / `is_cash_ticker` / `is_cash_position`) the right granularity, or should any be merged or split further?
- [ ] Does the Deprecation Map correctly route each callsite category to the right predicate? Are there specific files where the routing guidance is ambiguous or wrong?
- [ ] Is the drift-test regex `\.startswith\(["\x27][Cc][Uu][Rr]:["\x27](,|\))` comprehensive enough? Are there other cash-detection patterns not caught (e.g., `ticker == "CUR:USD"` equality, `"CUR:" in ticker` substring, `ticker[:4] == "CUR:"` slice)? Should any of these be added?
- [ ] Is the Phase 1 name-collision fix (atomic migration of all 5 live callers of `services.position_metadata.is_cash_position` plus the test monkeypatch updates, bundled with new helper introduction) the right scope, or should it be its own prerequisite phase?
- [ ] Is Phase 5 cleanup necessary, or could the shim at `portfolio_risk_engine/portfolio_config.py` stay indefinitely? (Trade-off: permanent backwards-compat surface vs repo cleanliness.)
- [ ] Is the Phase 3 split (3a MCP tools ~9 files / 3b routes+inputs+actions ~6 files / 3c services+providers+utils+core ~17 files) balanced correctly after adding the R1-found missing files? Should any file move between sub-phases?
- [ ] Does removing `_is_cash_proxy`'s per-call YAML reload introduce any cache-staleness issues that the existing `_get_cash_positions_cached` doesn't already handle? Is the docstring disclosure sufficient?
- [ ] Any files still missing from Phase 3 that didn't turn up in R1's grep (e.g., in `backtest/`, `reporting/`, `admin/`, or other subtrees not explicitly audited)?
- [ ] Any specific migration from R1 finding #1 (raw-prefix → `is_cur_ticker` vs broad `is_cash_ticker`) where the chosen routing is still wrong after R2?
