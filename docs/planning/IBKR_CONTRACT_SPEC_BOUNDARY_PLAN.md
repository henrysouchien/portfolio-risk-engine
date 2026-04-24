# IBKR Contract Spec Boundary — V5 Plan

**Parent:** `docs/TODO.md` V5 · Vendor SDK Boundary Refactor Lane 2
**Date:** 2026-04-23
**Status:** Draft (v5 — fixes one residual stale-JSON line-number reference flagged by Codex R4)

---

## 1. Problem

`IBKRClient.fetch_snapshot(contracts=list["Contract"])` and its delegate `IBKRMarketDataClient.fetch_snapshot()` accept raw vendor `Contract`/`Stock`/`Option`/`Future` objects as input. External callers must either import `ib_async` directly, invoke an `ibkr.contracts` resolver that returns a raw vendor object, or construct a duck-typed `SimpleNamespace` with the magic marker `_ibkr_contract_spec=True`.

This was surfaced during V2 verification (2026-04-23). Four external callsites leak:

| Caller | Construct | How | Raw vendor coupling |
|---|---|---|---|
| `options/portfolio_greeks.py:163,181` | Option | `from ib_async import Option as IBOption; IBOption(...)` | **Direct SDK import** (Rule A — exempt via `VENDOR_BOUNDARY_ALLOWLIST["ib_async"]` and `["ib_insync"]` in `tests/api_budget/_lint.py:134-161`). Also imports `from ibkr.market_data import IBKRMarketDataClient` (Rule B internal-module access, exempt via `_BOUNDARY_INTERNAL_RULES["ibkr"/"ibkr.compat"].files` at lines 253, 257). **Both** allowlists must be cleared to take this file off. |
| `options/analyzer.py:157-161` | Option | `resolve_option_contract(symbol, contract_identity=dict)` → raw `Option` | **Indirect** — file receives vendor object |
| `services/trade_execution_service.py:546-552` | Future | `resolve_futures_contract(symbol, contract_month)` → raw `Future` | **Indirect** — file receives vendor object |
| `mcp_tools/chain_analysis.py:102-122,382-395` | STK/FUT/OPT | `SimpleNamespace(_ibkr_contract_spec=True, ...)` | **Duck-typed marker** — no vendor import, but undiscoverable API |

V2 audit (return-type correctness) passed. V5 closes the symmetric gap on inputs. Return-side safety without input-side safety leaves the boundary half-porous.

---

## 2. Goal

Introduce a typed, discoverable, vendor-neutral way to describe a contract to `fetch_snapshot` so external callers never need to import `ib_async` or rely on duck-typed markers. Migrate the four known callsites.

Target outcome:

- `fetch_snapshot` accepts `list[IBKRContractSpec]` as the primary, documented input type
- `options/portfolio_greeks.py` drops **both** its `ib_async.Option` import (Rule A) and its `ibkr.market_data` internal import (Rule B) in favor of the public `ibkr` boundary, and comes off the `ibkr` / `ibkr.compat` allowlists
- `mcp_tools/chain_analysis.py` stops relying on the undocumented `_ibkr_contract_spec` marker
- `options/analyzer.py` and `services/trade_execution_service.py` build specs directly instead of calling resolvers that return vendor objects — this also shrinks the Rule B baseline (their current `from ibkr.contracts import resolve_*` imports go away)
- Existing raw-vendor and legacy-marker (`_ibkr_contract_spec=True` + camelCase fields) paths inside `_coerce_snapshot_contract` remain as shims during migration, removed after all callers land

---

## 3. Non-Goals

- **Not** refactoring `resolve_option_contract` / `resolve_futures_contract` internals — they still produce vendor `Option`/`Future` for IBKR's internal qualifyContracts() path.
- **Not** changing `fetch_snapshot` return shape (V2 confirmed it's already dict list).
- **Not** touching `mcp_tools/options.py`, `server.py`, or other in-boundary callers.
- **Not** changing the vendor-SDK allowlist mechanics (Rule A/B lint stays as-is).

---

## 4. Target architecture

### 4.1 New type: `IBKRContractSpec`

Location: `ibkr/contract_spec.py` (new module; kept separate from `ibkr/contracts.py` which owns vendor-resolving helpers).

```python
from dataclasses import dataclass
from typing import Literal, Optional, Union

SecType = Literal["STK", "FUT", "OPT"]  # narrowed — market_data.py:199 only supports these
OptionRight = Literal["C", "P"]

@dataclass(frozen=True)
class IBKRContractSpec:
    """Vendor-neutral description of a contract for boundary-crossing calls.

    Keep this a plain dataclass — no vendor imports. Fields mirror the
    subset of ib_async.Contract attributes that _coerce_snapshot_contract
    reads today (see ibkr/market_data.py:148-199).

    Resolution policy in _resolve_spec (ibkr/market_data.py):
    - OPT: always routes through resolve_option_contract(contract_identity=...).
      con_id alone is sufficient when the contract is already qualified in the
      DB — expiry/strike/right may be None in that case. For ad-hoc option
      lookups without a con_id, provide expiry + strike + right.
    - FUT: contract_month is optional; missing month + SMART exchange uses
      resolve_futures_contract's continuous-contract default.
    - STK: only symbol/exchange/currency are required.
    """
    sec_type: SecType
    symbol: str
    exchange: str = "SMART"
    currency: str = "USD"
    # Option fields (expiry/strike/right all optional so con_id-only options work)
    expiry: Optional[str] = None          # YYYYMMDD
    strike: Optional[float] = None
    right: Optional[OptionRight] = None
    multiplier: Optional[Union[str, int, float]] = None  # ib_async accepts str/int; OptionLeg normalizes to float — accept all three
    # Futures fields
    contract_month: Optional[str] = None  # YYYYMM or YYYYMMDD
    # Universal (sufficient-on-its-own for options already in DB)
    con_id: Optional[int] = None

    @classmethod
    def stock(cls, symbol: str, *, exchange: str = "SMART", currency: str = "USD") -> "IBKRContractSpec":
        return cls(sec_type="STK", symbol=symbol, exchange=exchange, currency=currency)

    @classmethod
    def option(cls, symbol: str, *, expiry: str, strike: float, right: OptionRight,
               exchange: str = "SMART", currency: str = "USD",
               multiplier: Optional[Union[str, int, float]] = None) -> "IBKRContractSpec":
        """Ad-hoc option lookup by (expiry, strike, right)."""
        return cls(sec_type="OPT", symbol=symbol, expiry=expiry, strike=strike,
                   right=right, exchange=exchange, currency=currency, multiplier=multiplier)

    @classmethod
    def option_by_con_id(cls, symbol: str, *, con_id: int,
                         exchange: str = "SMART", currency: str = "USD") -> "IBKRContractSpec":
        """Pre-qualified option lookup — requires the con_id already in DB.

        Used by options/analyzer.py when it has a contract_identity with
        only con_id (no expiry/strike/right). resolve_option_contract will
        resolve via the stored row rather than rebuilding from scratch.
        """
        return cls(sec_type="OPT", symbol=symbol, con_id=con_id,
                   exchange=exchange, currency=currency)

    @classmethod
    def future(cls, symbol: str, *, contract_month: Optional[str] = None,
               exchange: str = "SMART", currency: str = "USD") -> "IBKRContractSpec":
        return cls(sec_type="FUT", symbol=symbol, contract_month=contract_month,
                   exchange=exchange, currency=currency)
```

Exported from `ibkr/__init__.py` so callers use `from ibkr import IBKRContractSpec`.

### 4.2 `_coerce_snapshot_contract` extension

Current (`ibkr/market_data.py:148-199`):

```python
def _coerce_snapshot_contract(self, contract: Any):
    if isinstance(contract, dict):
        contract = type("IBKRContractSpec", (), contract)()
    if not getattr(contract, "_ibkr_contract_spec", False):
        return contract   # raw vendor Contract passes through
    # ... resolves sec_type/symbol/... and builds vendor Contract
```

Add one branch: recognize the new dataclass by `isinstance(contract, IBKRContractSpec)`, translate the dataclass fields into the same `sec_type`/`symbol`/... resolution flow. Dict and duck-typed paths stay for backward compat.

```python
def _coerce_snapshot_contract(self, contract: Any):
    if isinstance(contract, IBKRContractSpec):
        return self._resolve_spec(contract)
    if isinstance(contract, dict):
        contract = type("IBKRContractSpec", (), contract)()
    if not getattr(contract, "_ibkr_contract_spec", False):
        return contract
    # existing duck-typed path stays
    ...
```

`_resolve_spec` routes to `resolve_option_contract`/`resolve_futures_contract`/`Stock()` based on `sec_type`, identical to the existing duck-typed branch but reading typed fields instead of `getattr`.

### 4.3 `fetch_snapshot` signature

```python
def fetch_snapshot(
    self,
    contracts: list[IBKRContractSpec | Any],  # Any = legacy raw-vendor / marker-dict shim
    timeout: float = ...,
    ...
) -> list[dict[str, Any]]:
```

Type annotation signals the preferred input. Runtime behavior unchanged: the `Any` branch covers both raw vendor `Contract` objects (pass-through) and legacy marker dicts/`SimpleNamespace` with `_ibkr_contract_spec=True` + camelCase fields. Plain snake_case dicts are **not** accepted today (the coercer's `dict` branch synthesizes a namespace only from marker-dicts, not from arbitrary shape). If we later want a true dict-input path, that's Phase 6 scope.

---

## 5. Phased migration

### Phase 1: Introduce spec + coercer branch

1. Add `ibkr/contract_spec.py` with `IBKRContractSpec` dataclass.
2. Export from `ibkr/__init__.py` (add to `_LAZY_EXPORTS` + `__all__`).
3. Extend `_coerce_snapshot_contract` with the `IBKRContractSpec` branch + `_resolve_spec` helper.
4. Update `fetch_snapshot` parameter type annotation (runtime unchanged).
5. Unit tests for all three coercer paths (dataclass, legacy marker-dict, raw vendor Contract) against Stock/Future/Option. Include con_id-only option via `option_by_con_id(...)`.

**Exit criteria**: all three input shapes produce identical downstream `qualifyContracts` inputs. Existing tests unchanged (pass). 5-7 new tests for the dataclass path (stock, option by strike/expiry/right, option by con_id, future with explicit month, **future with non-SMART exchange** — exercises the `ib_async.Future(...)` direct branch at `ibkr/market_data.py:183`, future continuous-contract).

### Phase 2: Migrate `mcp_tools/chain_analysis.py`

Lowest risk — it's already boundary-clean (no `ib_async` import), just needs to stop using `SimpleNamespace`.

1. Replace `_build_underlying_contract()` body to return `IBKRContractSpec.stock(...)` / `IBKRContractSpec.future(...)`.
2. Replace the OPT `SimpleNamespace(...)` literal at line 382-395 with `IBKRContractSpec.option(...)`.
3. Remove `from types import SimpleNamespace` if no other uses.

**Exit criteria**: `fetch_snapshot` called with typed specs. Boundary tests still green. chain_analysis MCP smoke test still returns valid option chain.

### Phase 3: Migrate `options/analyzer.py`

1. Drop the `resolve_option_contract(...)` call at line 157-161.
2. Build the appropriate `IBKRContractSpec` variant from the `identity` dict:
   - If `identity` has `con_id` (the existing code path at line 144): `IBKRContractSpec.option_by_con_id(symbol=..., con_id=...)`
   - If `identity` has `expiry + strike + right` (the ad-hoc path): `IBKRContractSpec.option(symbol=..., expiry=..., strike=..., right=..., multiplier=identity.get("multiplier"))`. **Do not drop `multiplier`** — `options/analyzer.py:149` currently passes `int(leg.multiplier)`; `ibkr/contracts.py:224` stringifies at the vendor boundary, so `IBKRContractSpec.multiplier: Optional[Union[str, int, float]]` accepts it unchanged. Non-default multipliers (e.g., 10-share option contracts) would break silently otherwise.
3. `from ibkr import IBKRContractSpec` (replaces `from ibkr.contracts import resolve_option_contract`).

The resolver still runs — but inside `_coerce_snapshot_contract` → `_resolve_spec`. Net: same behavior, caller doesn't hold a vendor object.

**Rule B baseline delta**: this phase removes `options/analyzer.py:8` from `tests/api_budget/rule_b_baseline.json`. Regenerate via `scripts/generate_rule_b_baseline.py` at phase close.

**Exit criteria**: `analyze_option_strategy` MCP tool still returns Greeks. No `from ibkr.contracts` import remains. Both con_id-only and (expiry, strike, right) code paths regression-tested, including **one test with a non-default `multiplier`** (e.g., 10) to guard against silent multiplier-dropping regressions.

### Phase 4: Migrate `services/trade_execution_service.py`

This file has **two** Rule B internal imports at lines 546-547 (per current working tree):
```python
from ibkr.contracts import resolve_futures_contract
from ibkr.market_data import IBKRMarketDataClient
```

Both must go for the baseline entries to shrink.

1. Replace `from ibkr.contracts import resolve_futures_contract` with `from ibkr import IBKRContractSpec, get_ibkr_client`.
2. Replace `from ibkr.market_data import IBKRMarketDataClient` — delete this line; use `get_ibkr_client()` at call time.
3. Replace the contract construction:
   ```python
   front_contract = resolve_futures_contract(symbol, contract_month=front_month)
   back_contract = resolve_futures_contract(symbol, contract_month=back_month)
   snapshots = IBKRMarketDataClient().fetch_snapshot(contracts=[front_contract, back_contract])
   ```
   with:
   ```python
   front_spec = IBKRContractSpec.future(symbol, contract_month=front_month)
   back_spec = IBKRContractSpec.future(symbol, contract_month=back_month)
   snapshots = get_ibkr_client().fetch_snapshot(contracts=[front_spec, back_spec])
   ```
4. Verify `IBKRClient.fetch_snapshot` (delegate in `ibkr/client.py:165`) is behaviorally equivalent to `IBKRMarketDataClient().fetch_snapshot()` for this use case — same shared lock + budget plumbing + error shape. (Codex R2 confirmed this is true as of 2026-04-23.)

**Rule B baseline delta**: the checked-in `rule_b_baseline.json:31` is **stale** — it says `services/trade_execution_service.py:202, 544, 545` (stale line numbers from a prior tree state), but the live linter against today's working tree produces `services/trade_execution_service.py:16, 204, 546, 547` (Codex R2 confirmation). Ignore the stale `:202, 544, 545` when reading the JSON — implementation work targets the live `:546, 547` imports. The two entries Phase 4 removes correspond to the current `:546` (`resolve_futures_contract`) and `:547` (`IBKRMarketDataClient`) imports inside `_fetch_roll_market_data`. The out-of-scope entries at `:16` (`from ibkr._budget import guard_ib_call`) and `:204` (`from brokerage.schwab.adapter import SchwabBrokerAdapter`) are unrelated and stay. After regeneration, this file's baseline entry becomes `services/trade_execution_service.py:16, 204`.

**Exit criteria**: `execute_futures_roll` preview still returns front/back leg prices; `_fetch_roll_market_data` has zero remaining `from ibkr.*` internal-module imports; baseline entry for this file shrinks to `services/trade_execution_service.py:16, 204`.

### Phase 5: Migrate `options/portfolio_greeks.py` + remove from both allowlists

**This phase ships as a separate PR** (PR B), after Phases 1-4 land in PR A. Codex R1+R2 correctly flagged that the allowlist removal has additional scope: both Rule A (vendor package) and Rule B (internal module) allowlists exempt this file today, and both must be cleared.

1. Replace `from ib_async import Option as IBOption` + `IBOption(underlying, expiry_str, strike, right, "SMART")` with `from ibkr import IBKRContractSpec` + `IBKRContractSpec.option(...)`.
2. Replace `from ibkr.market_data import IBKRMarketDataClient` + `client = IBKRMarketDataClient()` with `from ibkr import get_ibkr_client` + `client = get_ibkr_client()`. Codex R2 confirmed `IBKRClient.fetch_snapshot` (`ibkr/client.py:165`) is a straight delegate to `IBKRMarketDataClient.fetch_snapshot` with identical shared-lock + budget + error semantics. No new boundary helper needed.
3. Verify no other `ib_async` / `ibkr.compat` / `ibkr.*` internal-module usage in the file remains (grep sweep — mandatory, not optional). Expected zero hits for `from ib_async`, `from ibkr.market_data`, `from ibkr.client`, `from ibkr.contracts`.
4. **Rule A** (vendor package) — remove `options/portfolio_greeks.py` from both:
   - `VENDOR_BOUNDARY_ALLOWLIST["ib_async"]` at `tests/api_budget/_lint.py:145`
   - `VENDOR_BOUNDARY_ALLOWLIST["ib_insync"]` at `tests/api_budget/_lint.py:159`
5. **Rule B** (internal module) — remove `options/portfolio_greeks.py` from both:
   - `_BOUNDARY_INTERNAL_RULES["ibkr"]["files"]` at `tests/api_budget/_lint.py:253`
   - `_BOUNDARY_INTERNAL_RULES["ibkr.compat"]["files"]` at `tests/api_budget/_lint.py:257`
6. Regenerate `tests/api_budget/rule_b_baseline.json` via `scripts/generate_rule_b_baseline.py`.

**Note on baseline provenance** (Codex R1+R2 correction): `options/portfolio_greeks.py` is **not** in `rule_b_baseline.json` today — its leaks are exempted by Rule A (vendor-package allowlist) and Rule B (internal-module allowlist). After PR B, the regenerated baseline may be unchanged for this file if the internal imports are fully cleaned up in step 2 (no new baseline entry introduced) — the allowlist diff is the primary signal, not the baseline diff.

**Exit criteria**:
- Rule A: file no longer in `VENDOR_BOUNDARY_ALLOWLIST["ib_async"]` / `["ib_insync"]`; reintroducing `from ib_async import Option` into this file fails lint.
- Rule B: file no longer in `_BOUNDARY_INTERNAL_RULES["ibkr"/"ibkr.compat"].files`; reintroducing `from ibkr.market_data import ...` fails lint (even for the currently-baselined patterns).
- Greeks computation matches pre-migration on a live spot-check — numeric diff = 0.0 for at least one option position.

### Phase 6: Deprecate duck-typed / legacy-marker paths (FUTURE — separate PR)

Once all known callers migrate, `_coerce_snapshot_contract` can drop:
- The `getattr(contract, "_ibkr_contract_spec", False)` duck-typed branch
- The `isinstance(contract, dict)` marker-dict → `SimpleNamespace` synthesis

Trigger for this PR (stricter than "grep + one week" per Codex R1):
1. Zero `_ibkr_contract_spec` hits outside `ibkr/market_data.py`
2. Zero external `fetch_snapshot` callers constructing raw vendor `Contract`/`Stock`/`Option`/`Future` objects
3. Zero external imports of `ibkr.contracts.resolve_*` for snapshot input construction (remaining uses only permitted inside `ibkr/`)
4. At least one production dogfood window (≥1 release cycle, ≥1 week) with PR A + PR B live

Tracked as V5b in TODO (to file on PR A ship).

---

## 6. Test strategy

### New tests
- `tests/ibkr/test_contract_spec.py` — dataclass construction, factory methods, frozen-ness, `__hash__` (for caller caching).
- `tests/ibkr/test_market_data.py::test_fetch_snapshot_accepts_contract_spec[stock|option|future]` — pass typed spec, assert coercer produces same vendor Contract shape as duck-typed equivalent.

### Existing tests to update
- `tests/ibkr/test_market_data.py` has ≥8 callsites using raw Stock/Option literals in tests. Keep *at least one test per sec_type* exercising the legacy raw-vendor input path (coverage for `_coerce_snapshot_contract`'s pass-through branch). Migrate the remaining ones to `IBKRContractSpec` for realism.

### Regression guards
- `mcp_tools/chain_analysis` MCP test covering full chain fetch flow stays untouched; runs against new spec path.
- `analyze_option_strategy` MCP test covering Greeks fetch stays untouched.

---

## 7. Rule A / Rule B allowlist + baseline provenance

| File | Current Rule A allowlist? | Current Rule B baseline? | Post-V5 | Plan step |
|---|---|---|---|---|
| `options/portfolio_greeks.py` | **Yes** — `VENDOR_BOUNDARY_ALLOWLIST["ib_async"]` (`_lint.py:145`) + `["ib_insync"]` (`_lint.py:159`) + `_BOUNDARY_INTERNAL_RULES["ibkr"/"ibkr.compat"].files` (`_lint.py:253, 257`) | No (leaks exempted by allowlist) | **All four** allowlist entries removed | PR B (Phase 5) |
| `options/analyzer.py` | No | **Yes** — `options/analyzer.py:8` | Entry removed from baseline | PR A (Phase 3) |
| `services/trade_execution_service.py` | No | **Yes** — checked-in JSON says `:202, 544, 545`; live linter produces `:16, 204, 546, 547` (stale JSON, Codex R2 confirmed). Phase 4 removes current `:546` + `:547`; baseline entry shrinks to `:16, 204`. | Entries removed from baseline | PR A (Phase 4) |
| `mcp_tools/chain_analysis.py` | No | No (uses neutral `SimpleNamespace` duck-type today) | Unchanged in lint; behavioral cleanup only | PR A (Phase 2) |
| `ibkr/contract_spec.py` (new) | — | — | Not on either — pure Python, no vendor import | — |

### Baseline JSON deltas

**PR A regenerates `rule_b_baseline.json`** at the end of Phases 3 and 4 — removing `options/analyzer.py:8` (Phase 3) and the `from ibkr.*` entries for `services/trade_execution_service.py` (Phase 4; current live-linter lines `:546, :547`; stale checked-in JSON shows the obsolete `:544, 545`). After regeneration, the trade_execution_service entry shrinks to `:16, 204` (out-of-scope imports that stay). Codex R1 catch: these are **not** `options/portfolio_greeks.py` entries as the v1 plan claimed.

**PR B regenerates again** for Phase 5, removing any residual `ibkr.market_data` / internal-module entries that still trace back to `portfolio_greeks.py` after step 5.2 lands.

Reviewers diff both regenerated baselines against the previous commit — strict-equality assertion means stale entries fail the suite.

---

## 8. Rollout order + reviewer checkpoints

**Two PRs** (Codex R1 recommendation):

### PR A — Contract-spec migration (Phases 1-4)

1. After Phase 1: "does the coercer round-trip for dataclass, legacy marker-dict, and raw vendor Contract inputs? Include con_id-only option."
2. After Phase 2: "grep `_ibkr_contract_spec` outside `ibkr/market_data.py` → expect only `mcp_tools/chain_analysis.py` removed from the hit list."
3. After Phase 3: "`options/analyzer.py:8` removed from `rule_b_baseline.json`; both con_id-only and (expiry, strike, right) code paths regression-tested."
4. After Phase 4: baseline entry for `services/trade_execution_service.py` shrinks from `:16, 204, 546, 547` (live linter output on today's tree) to `:16, 204` after regeneration.
5. PR-close: regenerated baseline passes strict-equality assertion; no test skips added.

### PR B — Allowlist cleanup (Phase 5)

Smaller, mechanical, isolated risk. Lands after PR A proves the migration on the three non-allowlisted callsites.

1. After step 5.1: `ib_async.Option` import removed.
2. After step 5.2: `ibkr.market_data` internal import removed; file uses public `ibkr` entry point only.
3. After step 5.4: Rule A allowlist entries at `_lint.py:145, 159` gone.
4. After step 5.5: Rule B allowlist entries at `_lint.py:253, 257` gone.
5. PR-close: regenerated baseline **may be unchanged for this file** (portfolio_greeks.py is not in `rule_b_baseline.json` today — its leaks are allowlist-exempted, not baseline entries; the primary signal is the allowlist diff, not a baseline shrink). Rule A lint strictly rejects a re-added `ib_async` import into this file; Greeks diff vs pre-migration = 0.0 on live spot-check.

---

## 9. Risk and mitigation

| Risk | Mitigation |
|---|---|
| Spec fields drift from what `_coerce_snapshot_contract` reads | Phase 1 tests assert byte-equal downstream vendor Contract for all three input shapes against same inputs |
| `resolve_option_contract` / `resolve_futures_contract` contract_identity dict has fields not in spec | Enumerate their signatures in Phase 1; extend dataclass if gap exists |
| Existing duck-typed path breaks when dataclass is substituted in one arm | Keep all three paths live until Phase 6; dual-path is intentional |
| Greeks computation differs after spec migration | Spot-check one live option position: before/after numeric diff must be 0.0 |
| `portfolio_greeks.py` has MORE than just the `ib_async` import to fix (also `ibkr.market_data` internal access) | Phase 5 step 5.2 explicitly covers the public-boundary switch; grep in Phase 5 is mandatory, not optional; Codex R1 caught this in v1 of the plan |

---

## 10. Decisions (resolved in Codex R1)

1. **Dataclass vs Pydantic** → **Plain dataclass**. Internal boundary type, not user-input parsing. Pydantic adds runtime deps + cost without solving the actual problem. `__post_init__` can add lightweight field-combination validation if needed (e.g., enforce `right ∈ {"C", "P"}` when `sec_type == "OPT"` and `con_id` absent).
2. **`_resolve_spec` placement** → **Private method on `IBKRMarketDataClient`** (stays in `ibkr/market_data.py`). Resolution policy is snapshot-specific and already depends on market-data quirks like the `FUT + exchange == SMART` branch. Putting it in `contract_spec.py` couples the pure-type module back to vendor-resolution behavior.
3. **Should `ibkr.contracts.resolve_*` become private** → **Not in this PR**. First eliminate external use (Phases 3 + 4 do that). After V5 lands, only boundary-internal callers remain, so a later follow-up can privatize / deprecate with much lower risk. Adding it here doubles scope for no boundary gain.
4. **Phase 6 trigger** → four criteria (see §5 Phase 6): zero external `_ibkr_contract_spec` hits + zero raw-vendor-contract external callers + zero external `ibkr.contracts.resolve_*` usage for snapshot input + ≥1 production dogfood window.

---

## 11. Size estimate

**PR A (Phases 1-4)**:
- Phase 1: ~140 LoC new (dataclass with two option factories + coercer branch + `_resolve_spec` helper + tests)
- Phases 2-4: ~40 LoC across three callsites + test updates + baseline regeneration
- **Subtotal**: ~180 LoC net

**PR B (Phase 5)**:
- Callsite migration to `get_ibkr_client()` (no new helper needed — `IBKRClient.fetch_snapshot` is already a straight delegate per Codex R2): ~20 LoC
- Allowlist diff (4 entries across 2 rules) + baseline regeneration: ~15 LoC
- **Subtotal**: ~35 LoC net

**Total across both PRs**: ~215 LoC net, ~5-7 hour implementation, 1-2 Codex review rounds per PR expected.
