# Brokerage-connect — IBKR provider standalone install (Class B-IBKR)

## Status: v2.1 — **CODEX PASS** 2026-05-03 (filed v1 → Codex FAIL R1 → v2 polish → Codex PASS R2 with minor edits → v2.1 cleanup applied. Ready to schedule for implementation.)

## Problem

`brokerage-connect 0.5.0` (shipped 2026-05-03) made SnapTrade/Plaid/Schwab providers standalone-installable in clean venvs. IBKR was deliberately scoped out — `brokerage-connect[ibkr]` extra installs `ib-async` but `from brokerage.ibkr.adapter import IBKRBrokerAdapter` fails with cryptic `ModuleNotFoundError: app_platform` because the adapter imports 3 distinct shapes of monorepo couplings:

**Shape 1 — `app_platform.api_budget.BudgetExceededError`** (line 23). Same shape as V6's `guard_call` shim. The `_shared/budget_exceptions.py` module already exists in `brokerage-connect/brokerage/_shared/` from V6 — just needs a sed-rewrite or shim at the import site.

**Shape 2 — 5 sibling `ibkr.*` modules** (lines 40-48): `ibkr.config`, `ibkr.connection`, `ibkr._budget`, `ibkr.locks`, `ibkr.contracts`. These live in monorepo `ibkr/` package, which is **already published on PyPI as `interactive-brokers-mcp`** (NOT `ibkr-mcp` — that's just the repo dir name; verified via `~/Documents/Jupyter/ibkr-mcp-dist/pyproject.toml:5`). The published wheel exposes the `ibkr` import namespace and includes all 5 sibling files with internal vendoring (`ibkr/_shared/{budget_exceptions,api_budget_costs,timeseries_store}.py`) that resolves their own monorepo couplings.

**Shape 3 — Cross-provider monorepo abstractions that leaked into the IBKR adapter** (lines 49-50):
- `from options import OptionLeg, OptionStrategy` — actually re-exports from `portfolio_math.options` (legacy 5-line shim at `options/data_objects.py`). `portfolio_math/` is part of `portfolio-risk-engine` PyPI package (0.2.1).
- `from providers.routing_config import TRADE_ACCOUNT_MAP` — env-derived dict (`os.getenv("TRADE_ACCOUNT_MAP", "")` parsed into `{agg_id: native_id}`). Used at adapter `:121,:125` for a single directional aggregator-id → native-id lookup.

External users running `pip install brokerage-connect[ibkr]` should be able to `from brokerage.ibkr.adapter import IBKRBrokerAdapter` in a clean venv with no monorepo on path. v0.5.0 documents this as monorepo-only across both READMEs + CHANGELOG; this plan removes that limitation.

## Pattern to follow

V6 established the canonical shim pattern (narrowed `except ModuleNotFoundError` with exact-match `e.name` check). V7 reuses it for Shape 1 and adds two new patterns for Shapes 2 and 3:

**Shape 2 pattern — depend on the published PyPI package**
Add `interactive-brokers-mcp>=0.2.4` to `brokerage-connect`'s `[ibkr]` extra. The 5 sibling imports at adapter lines 40-48 resolve through the published wheel's `ibkr/` package. The wheel internally uses `ibkr/_shared/budget_exceptions.py` (rewritten via `sync_ibkr_mcp.sh`) so it doesn't drag `app_platform` along.

**Shape 3 pattern — define minimal shapes inside brokerage-connect**
Create `brokerage-connect/brokerage/options_types.py` with field-compatible `OptionLeg` and `OptionStrategy` dataclasses (mirror `portfolio_math.options` shape). Adapter imports from there. For `TRADE_ACCOUNT_MAP`, refactor adapter constructor to accept `account_map: dict[str, str] | None = None` kwarg with env-parsing fallback at instance time — drop the `providers.routing_config` import entirely.

## Options

### Option 1 — PyPI dep for `ibkr.*` siblings + minimal types in `brokerage.options_types` + constructor kwarg for account_map (RECOMMENDED)

What this section above describes. Pros: matches existing PyPI ecosystem (interactive-brokers-mcp is already published and standalone-installable); minimal new code (~75 LoC for options_types.py + ~15 LoC for adapter constructor refactor); IBKR users get a real standalone install. Cons: heavy `[ibkr]` dep tree (interactive-brokers-mcp pulls pandas, pyarrow, fastmcp, numpy, etc. — opt-in via the extra so external users accept this); release-cycle coupling between brokerage-connect and interactive-brokers-mcp; minor drift discipline for the dataclass shapes.

### Option 2 — Vendor 5 sibling modules into `brokerage-connect/brokerage/_shared/ibkr/`

Same approach as ibkr-mcp's `_shared/` but expanded. Pros: no external runtime dep. Cons: duplicates 800+ LoC + a YAML data file (`exchange_mappings.yaml`) + transitive deps (`_logging.py`, `_types.py`, `exceptions.py`, `asyncio_compat.py`); opposes CLAUDE.md's local-first rule; drift discipline against monorepo `ibkr/` source-of-truth grows large.

### Option 3 — Refactor adapter to take all dependencies via constructor injection

Move `IBKRConnectionManager`, `guard_ib_call`, etc. to constructor kwargs. Adapter doesn't import siblings at all; caller wires them. Pros: zero coupling. Cons: huge refactor; awkward API for external users who don't have those dependencies; pattern doesn't match the rest of the package.

### Option 4 — Refactor adapter to take `OptionLeg` as plain dicts instead of dataclasses

Variant of Option 1 that eliminates `brokerage.options_types`. Pros: zero new types. Cons: every monorepo caller wraps `portfolio_math.options.OptionLeg` instances into dicts before calling the adapter — touches ~7 caller sites; loses type safety.

## Recommendation

**Option 1.** Mirrors how V6 leveraged ibkr-mcp's existing `_shared/` pattern. Reuses the published PyPI package as a runtime dep — exactly what PyPI deps are FOR. Minimal new code. Drift surface is small (just two dataclass field lists).

## Implementation

### Step 1 — `BudgetExceededError` shim at adapter line 23

In monorepo, edit `brokerage-connect/brokerage/ibkr/adapter.py:23`. Replace `from app_platform.api_budget import BudgetExceededError` with the same narrowed shim pattern V6 uses for `guard_call`:

```python
try:
    from app_platform.api_budget import BudgetExceededError
except ModuleNotFoundError as e:
    if e.name not in {"app_platform", "app_platform.api_budget"}:
        raise
    from brokerage._shared.budget_exceptions import BudgetExceededError
```

Note: the dist-runtime fallback imports from the **already-vendored** `brokerage._shared.budget_exceptions` (V6 vendored it for the SnapTrade/Plaid/Schwab providers). No new vendoring needed.

### Step 2 — Add `interactive-brokers-mcp` to `[ibkr]` extra

Edit `brokerage-connect/pyproject.toml:23`:

```toml
[project.optional-dependencies]
schwab = ["schwab-py>=1.5,<2"]
snaptrade = ["snaptrade-python-sdk>=11.0,<12"]
ibkr = ["ib-async>=2.1,<3", "interactive-brokers-mcp>=0.2.4"]
plaid = ["plaid-python>=38.0,<39", "certifi>=2024.0.0"]
```

Note: keep `ib-async>=2.1,<3` for clarity even though `interactive-brokers-mcp` already pulls it transitively. Future-proofs against `interactive-brokers-mcp` ever changing its IB SDK choice.

The 5 sibling imports at adapter lines 40-48 resolve through the PyPI package's `ibkr/` namespace. No code change needed at those lines.

### Step 3 — Minimal `brokerage.options_types` module

Create `brokerage-connect/brokerage/options_types.py` with field-compatible dataclasses. Mirror `portfolio_math.options.OptionLeg` and `OptionStrategy` field shapes exactly so monorepo callers can pass `portfolio_math` instances and external users can construct `brokerage.options_types` instances — both work via Python's structural attribute access.

```python
"""Minimal option-leg/strategy dataclasses for the brokerage adapter.

Field shapes mirror portfolio_math.options exactly so monorepo callers can pass
portfolio_math instances interchangeably (Python's duck-typing on dataclass
fields). External standalone users construct brokerage.options_types instances.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal

_POSITION_VALUES = {"long", "short"}
_OPTION_TYPE_VALUES = {"call", "put", "stock"}


def _parse_expiration(value: Any) -> date | None:
    """Accept date, datetime, ISO-8601 string, YYYYMMDD string, or any
    str()-coercible value. Body copied exactly from
    portfolio_math/options.py:363-375 to preserve duck-typed
    interchangeability between brokerage.options_types.OptionLeg and
    portfolio_math.options.OptionLeg in monorepo callers. Drift discipline
    enforced by parity tests (see Q-A)."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        return datetime.strptime(text, "%Y%m%d").date()
    return datetime.fromisoformat(text).date()


@dataclass
class OptionLeg:
    position: Literal["long", "short"]
    option_type: Literal["call", "put", "stock"]
    premium: float
    strike: float | None = None
    size: float = 1.0
    multiplier: float | None = None
    expiration: date | None = None
    label: str | None = None
    con_id: int | None = None

    def __post_init__(self) -> None:
        # Validation MUST mirror portfolio_math.options.OptionLeg.__post_init__
        # byte-for-byte. See parametrized parity tests in tests/brokerage/options_types/.
        self.position = str(self.position).strip().lower()
        self.option_type = str(self.option_type).strip().lower()
        if self.position not in _POSITION_VALUES:
            raise ValueError("position must be 'long' or 'short'")
        if self.option_type not in _OPTION_TYPE_VALUES:
            raise ValueError("option_type must be 'call', 'put', or 'stock'")
        self.premium = float(self.premium)
        self.size = float(self.size)
        if self.premium < 0:
            raise ValueError("premium must be >= 0")
        if self.size <= 0:
            raise ValueError("size must be > 0")
        if self.option_type == "stock":
            self.strike = None
            self.expiration = None
            if self.multiplier is None:
                self.multiplier = 1.0
        else:
            if self.strike in (None, ""):
                raise ValueError("strike is required for call/put legs")
            self.strike = float(self.strike)
            if self.strike <= 0:
                raise ValueError("strike must be > 0 for call/put legs")
            try:
                self.expiration = _parse_expiration(self.expiration)
            except ValueError as exc:
                raise ValueError(f"invalid expiration: {self.expiration}") from exc
            if self.expiration is None:
                raise ValueError("expiration is required for call/put legs")
            if self.multiplier is None:
                self.multiplier = 100.0
        self.multiplier = float(self.multiplier)
        if self.multiplier <= 0:
            raise ValueError("multiplier must be > 0")
        if self.con_id in (None, ""):
            self.con_id = None
        elif isinstance(self.con_id, bool):
            raise ValueError("con_id must be an integer")
        else:
            try:
                self.con_id = int(self.con_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("con_id must be an integer") from exc

    @property
    def direction(self) -> int:
        """+1 for long, -1 for short. Used by adapter pricing math at adapter.py:508-512."""
        return 1 if self.position == "long" else -1

    @property
    def expiry_yyyymmdd(self) -> str | None:
        if self.expiration is None:
            return None
        return self.expiration.strftime("%Y%m%d")


@dataclass
class OptionStrategy:
    legs: list[OptionLeg]
    underlying_price: float | None = None
    underlying_symbol: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.legs:
            raise ValueError("strategy must include at least one leg")
        if self.underlying_price in (None, ""):
            self.underlying_price = None
        else:
            self.underlying_price = float(self.underlying_price)
            if self.underlying_price <= 0:
                raise ValueError("underlying_price must be > 0 when provided")
        if self.underlying_symbol is not None:
            self.underlying_symbol = str(self.underlying_symbol).strip().upper() or None


__all__ = ["OptionLeg", "OptionStrategy"]
```

Then edit `brokerage-connect/brokerage/ibkr/adapter.py:49`:

```python
# Before:
from options import OptionLeg, OptionStrategy

# After:
from brokerage.options_types import OptionLeg, OptionStrategy
```

**What the adapter actually uses** (verified via Codex R1 grep sweep, v1 was incomplete):
- `OptionLeg` fields: `position`, `option_type`, `strike`, `premium`, `size`, `multiplier`, `label`, `con_id`, `expiration` (truthiness)
- `OptionLeg` properties: `expiry_yyyymmdd` AND **`direction`** (used at `adapter.py:508-512` in pricing math — v1 plan missed this)
- `OptionStrategy` fields: `legs`, `underlying_symbol`, **`underlying_price`** (stored in order params at `adapter.py:540-545`), **`description`** (stored in broker preview data at `adapter.py:559-564`)

NOT used: `OptionLeg.net_premium`, `OptionLeg.notional_exposure()`, `OptionLeg.to_dict()`, `OptionLeg.to_summary()`, `OptionStrategy.to_dict()`, `OptionStrategy.to_summary()` — those stay in `portfolio_math.options` only and are not mirrored.

### Step 4 — `account_map` constructor kwarg

Edit `brokerage-connect/brokerage/ibkr/adapter.py`. Drop line 50 (`from providers.routing_config import TRADE_ACCOUNT_MAP`). Update `IBKRBrokerAdapter.__init__` (current signature at `adapter.py:102-107` is `def __init__(self, user_email: str, on_refresh: Callable[[str], None] | None = None)`):

```python
def __init__(
    self,
    user_email: str,
    on_refresh: Callable[[str], None] | None = None,
    *,
    account_map: dict[str, str] | None = None,
) -> None:
    self._user_email = user_email
    self._conn_manager = _get_trading_conn_manager()
    self._on_refresh = on_refresh or (lambda _account_id: None)
    self._warned_empty_authorized_accounts = False
    self._account_map = account_map if account_map is not None else self._parse_env_account_map()

@staticmethod
def _parse_env_account_map() -> dict[str, str]:
    raw = os.getenv("TRADE_ACCOUNT_MAP", "")
    out: dict[str, str] = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            agg_id, native_id = pair.split(":", 1)
            out[agg_id.strip()] = native_id.strip()
    return out
```

The `*,` separator after `on_refresh` makes `account_map` keyword-only, preserving the existing positional/optional behavior of `user_email` and `on_refresh`. Existing callers (`services/trade_execution_service.py:220-224`, `tests/services/test_ibkr_broker_adapter.py:22-26`, `tests/brokerage/ibkr/test_adapter_multileg.py:75-79`) pass kwargs and continue to work without modification.

Update lines `:121,:125` to use `self._account_map.get(account_id, account_id)` instead of `TRADE_ACCOUNT_MAP.get(...)`.

Monorepo callers either pass `account_map=providers.routing_config.TRADE_ACCOUNT_MAP` explicitly (single source of truth preserved), or rely on the env-fallback (which matches `providers.routing_config.py:405-411` parsing semantically — same delimiters, same trim, same `agg:native` shape).

**Timing note (Codex R1 finding):** monorepo `providers/routing_config.py` parses `TRADE_ACCOUNT_MAP` env var at **module import time**. Plan's adapter fallback parses at **instance construction time**. This means: (a) if the env var changes between module import and adapter instantiation, monorepo's `TRADE_ACCOUNT_MAP` reflects the OLD value, adapter's `account_map` reflects the NEW value. In practice env vars are set at process startup and don't change mid-process, so this is a theoretical-only difference. (b) For monorepo callers who explicitly pass `account_map=providers.routing_config.TRADE_ACCOUNT_MAP`, behavior is byte-identical to v0.5.0. Recommendation: monorepo callers should pass explicitly to preserve current semantics. Document in adapter docstring.

**`IBKRBrokerAdapter` keyword-only verification (Codex R1 finding):** Class is `IBKRBrokerAdapter` (not `IBKRAdapter`). Existing call sites use keyword args (`services/trade_execution_service.py:220-224`, `tests/services/test_ibkr_broker_adapter.py:22-26`, `tests/brokerage/ibkr/test_adapter_multileg.py:75-79`). Adding `account_map` as a keyword-only kwarg with a default doesn't break any existing call site.

### Step 5 — Sync script: re-include `brokerage/ibkr/`

Edit `scripts/sync_brokerage_connect.sh` Step 2 (added in V6). Re-include `brokerage/ibkr/` in the sed-rewrite scope and drift check:

```bash
# Rewrite imports across ALL provider subpackages (V7: brokerage/ibkr/ now included)
find "$TARGET/brokerage/snaptrade" "$TARGET/brokerage/plaid" "$TARGET/brokerage/schwab" "$TARGET/brokerage/ibkr" \
    -name '*.py' -exec sed -i '' \
    -e 's|from app_platform\.api_budget import BudgetExceededError|from brokerage._shared.budget_exceptions import BudgetExceededError|g' \
    -e 's|from config\.api_budget_costs|from brokerage._shared.api_budget_costs|g' \
    {} \;

# Drift check (V7: also scan brokerage/ibkr/; catch OptionStrategy too — Codex R1 finding)
DRIFT=$(rg -n \
    -e 'from app_platform\.api_budget import BudgetExceededError' \
    -e 'from config\.api_budget_costs' \
    -e 'from options import (OptionLeg|OptionStrategy)' \
    -e 'from providers\.routing_config' \
    "$TARGET/brokerage/snaptrade" "$TARGET/brokerage/plaid" "$TARGET/brokerage/schwab" "$TARGET/brokerage/ibkr" 2>/dev/null || true)
if [ -n "$DRIFT" ]; then
    echo "ERROR: monorepo imports remain in dist provider dirs after vendoring:" >&2
    echo "$DRIFT" >&2
    exit 1
fi
```

**Important:** the V6 drift check only checked SnapTrade/Plaid/Schwab. V7 expands to all four AND adds two new patterns (`from options import OptionLeg`, `from providers.routing_config`) so any future leak gets caught. The V7 source-side edits to adapter.py change the imports to `brokerage.options_types` and drop `providers.routing_config` entirely — drift check fires only if a regression reintroduces them.

### Step 6 — Verify (clean-wheel test, all four extras)

Build the wheel and test against the published artifact:

```bash
cd ~/Documents/Jupyter/brokerage-connect-dist
python -m build --wheel
WHEEL=$(ls dist/brokerage_connect-0.6.0-*.whl | head -n1)
[ -z "$WHEEL" ] && { echo "ERROR: no wheel built"; exit 1; }

for extra in snaptrade plaid schwab ibkr; do
    python -m venv "/tmp/bc-test-${extra}"
    "/tmp/bc-test-${extra}/bin/pip" install "${WHEEL}[${extra}]"
    "/tmp/bc-test-${extra}/bin/python" -c "from brokerage.${extra} import client" || exit 1
done

# Specifically verify IBKR adapter import succeeds (V7 deliverable)
python -m venv /tmp/bc-test-ibkr-adapter
/tmp/bc-test-ibkr-adapter/bin/pip install "${WHEEL}[ibkr]"
/tmp/bc-test-ibkr-adapter/bin/python -c "from brokerage.ibkr.adapter import IBKRBrokerAdapter; print('OK:', IBKRBrokerAdapter.__name__)"
```

Monorepo parity: full pytest at parity. Special attention to test files exercising IBKR option-trade flows. The narrowed `BudgetExceededError` shim is a no-op when `app_platform` is on path; the `OptionLeg` import change should be transparent to monorepo callers (Python duck-types between `portfolio_math.options.OptionLeg` and `brokerage.options_types.OptionLeg` — same field shape).

### Step 7 — Bump pyproject + update READMEs + CHANGELOG

- `brokerage-connect/pyproject.toml:7`: `0.5.0` → `0.6.0`
- `brokerage-connect/README.md:11` (install table): change IBKR row Status from "Monorepo-only — adapter requires risk_module monorepo (...)" to standalone description (e.g., "Trade adapter via `interactive-brokers-mcp`")
- `brokerage-connect/README.md:21`: re-enable `[schwab,ibkr]` install example (no longer broken)
- `brokerage-connect/brokerage/README.md:28`: drop the "(monorepo-only — see top-level README)" caveat from IBKR row
- `brokerage-connect/brokerage/README.md:36`: re-enable `[schwab,ibkr]` install example
- `brokerage-connect/CHANGELOG.md`: add 0.6.0 entry noting IBKR is now standalone-installable; users should `pip install brokerage-connect[ibkr]` and pass `account_map=` if they want non-default routing.

### Step 8 — Ship

Run sync script; verify dist git status; commit + push monorepo + dist; publish 0.6.0 to PyPI per `scripts/publish_brokerage_connect.sh --use-source-version --yes`.

## Open questions (must answer before scheduling)

- **Q-A** (resolved in v2): drift discipline strengthened. `dataclasses.fields()` equality alone doesn't catch validation/property/error-message drift. v2 plan adds a parity test suite at `tests/brokerage/options_types/test_parity_with_portfolio_math.py`:
  - **Field-tuple equality:** `[(f.name, f.default, f.default_factory, f.type) for f in dataclasses.fields(X)]` matches between `brokerage.options_types.OptionLeg` and `portfolio_math.options.OptionLeg` (and same for OptionStrategy).
  - **Behavioral parametrized tests:** for each known valid/invalid payload (stock leg, call/put leg with various expiration formats, missing strike, negative premium, invalid con_id, etc.), construct both classes and assert: same exception type raised OR same normalized field values. Cover `position`, `option_type`, `premium`, `strike`, `size`, `multiplier`, `expiration` (date/datetime/ISO/YYYYMMDD/int-coercion), `con_id` (None/bool/int/string/non-coercible).
  - **Property tests:** `direction`, `expiry_yyyymmdd` — assert both classes produce identical results across legs.
  - **OptionStrategy parity:** field tuples + behavioral tests for `legs` validation, `underlying_price`/`underlying_symbol`/`description` normalization.
  When these tests fail, the failure points at the exact discrepancy. Tests live in monorepo (where both classes are importable). External standalone users don't run these tests but inherit the safety because we re-run the parity suite before every brokerage-connect release.
- **Q-B**: monorepo type annotations on the adapter currently say `OptionLeg` (now resolving to `brokerage.options_types.OptionLeg`), but monorepo callers pass `portfolio_math.options.OptionLeg`. Static type checkers (mypy) will flag the mismatch. Acceptable since runtime is fine, but Codex may want a Protocol or a `OptionLegLike = Union[brokerage.OptionLeg, portfolio_math.OptionLeg]` alias.
- **Q-C** (resolved in v2): `interactive-brokers-mcp 0.2.4` heavy deps. Codex verified `fastmcp` is **not** loaded by normal sibling imports (`ibkr.config`, `ibkr.connection`, `ibkr._budget`, `ibkr.locks`, `ibkr.contracts`) — only loaded by `ibkr.server` entrypoint (`ibkr-mcp-dist/ibkr/server.py:18-19`). Adapter doesn't import `ibkr.server` so fastmcp is dead weight at runtime. **However:** fastmcp is still a hard dep in the package's pyproject so external users still pip-install it (~50MB+ with sub-deps). Two paths:
  - (i) Accept and document. README's IBKR install row notes the dep tree size. Filed as a separate followup if it becomes a real concern.
  - (ii) Upstream fix: split `interactive-brokers-mcp` to move `fastmcp` (and likely `pandas`/`pyarrow`) to a `[server]` extra so `pip install interactive-brokers-mcp` (no extras) is a lighter library install. **Out of scope for V7** — would require changes in the ibkr-mcp source repo + a new release. File as `V7-tail` if shipped.
  - **v2 picks (i).** Document the dep size in CHANGELOG + README. Future V7-tail can pursue (ii).
- **Q-D**: should `brokerage-connect`'s `[ibkr]` extra also pin a minimum `portfolio-risk-engine` version? **No** — adapter no longer imports `portfolio_math.options` directly. Monorepo callers depend on it through their own pyproject. External users construct `brokerage.options_types.OptionLeg` directly.

## Out of scope

- Anything covered by V6 (`brokerage-connect 0.5.0` ship — SnapTrade/Plaid/Schwab standalone). Already shipped.
- Refactoring `portfolio_math.options.OptionLeg` to import its base from `brokerage.options_types` (would create publish-cycle dependency between `brokerage-connect` and `portfolio-risk-engine`). Not worth it for two dataclasses.
- Spinning out `OptionLeg`/`OptionStrategy` into their own tiny `option-types` PyPI package consumed by both `brokerage-connect` and `portfolio-risk-engine`. Possibly correct long-term answer, but ships scope creep for V7.
- Dropping the `[ibkr]` heavy-dep tax by depending on a smaller subset of `interactive-brokers-mcp`'s wheel. Would require splitting that package.
- Removing `account_map` env-fallback after a deprecation cycle. Adapter currently supports BOTH explicit kwarg and env-parsing; both paths stay.

## Decisions log

- **2026-05-03 (v1)** — Filed as the V7 followup to V6/0.5.0 ship. Investigation block (read-only, by Claude post-V6) answered the 3 open questions: (Q1) depend on `interactive-brokers-mcp` PyPI 0.2.4 for the 5 sibling `ibkr.*` modules; (Q2) define minimal `brokerage.options_types` for OptionLeg/OptionStrategy; (Q3) refactor adapter to take `account_map` constructor kwarg with env fallback. Q4 comprehensive sweep confirmed no additional couplings beyond the three known shapes. Recommendation: Option 1. Sent to Codex consult (session `019deed9-72a1-7a72-83a9-b79bc8013241`) — **FAIL** R1 with 5 REVISE + 1 REJECT findings.
- **2026-05-03 (v2)** — Polish after Codex FAIL R1. Six targeted fixes:
  1. **REJECT C — Adapter usage sweep was incomplete.** Codex grep found `leg.direction` (used in pricing math at `adapter.py:508-512`), `strategy.underlying_price` (stored in order params at `adapter.py:540-545`), `strategy.description` (stored in broker preview data at `adapter.py:559-564`). v2 adds `direction` property to minimal `OptionLeg`. `OptionStrategy.underlying_price`/`description` were already in the dataclass — narrative was wrong, not the code; narrative corrected.
  2. **REVISE D — Class name was wrong throughout v1.** Plan said `IBKRAdapter`; actual class is `IBKRBrokerAdapter` (`brokerage-connect/brokerage/ibkr/adapter.py:99-106`). Fixed via global replace.
  3. **REVISE B — `_parse_expiration` divergence.** v1's helper rejected datetime ISO strings, rejected int values, used different error messages. v2 replaces with byte-for-byte copy of `portfolio_math/options.py:360-374`. Adds the `try/except` wrap in `__post_init__` for `invalid expiration: ...` error message and the `con_id` `try/except` for `con_id must be an integer` error wrapping.
  4. **REVISE E — Q-A drift discipline strengthened.** v1 proposed only `dataclasses.fields()` equality. v2 specifies a full parametrized parity test suite at `tests/brokerage/options_types/test_parity_with_portfolio_math.py` covering field tuples, behavioral validation parity (valid/invalid payloads, exception types, normalized values), property parity (`direction`, `expiry_yyyymmdd`), and OptionStrategy parity. Tests run pre-release against both classes side-by-side.
  5. **REVISE F — Q-C heavy dep tree.** Codex confirmed `fastmcp` is lazy (server entrypoint only, not loaded by sibling imports). v2 picks "accept and document" path; upstream `[server]` extra split filed as `V7-tail` followup if it becomes a real concern.
  6. **REVISE G — Drift check + timing note.** v2 drift check now catches `from options import OptionStrategy` (was just OptionLeg). Added timing note explaining env-parse-at-instance vs env-parse-at-import semantic difference (theoretical only; recommendation is for monorepo callers to pass `account_map=` explicitly to preserve byte-identical semantics).
  Sent to Codex (resumed session) — **PASS WITH MINOR EDITS** R2. Two cleanup items: (1) `_parse_expiration` docstring said "byte-for-byte" but file had a docstring vs. source had none — wording updated to "body copied exactly from portfolio_math/options.py:363-375"; (2) constructor snippet was ambiguous about kwarg ordering — v2.1 shows the explicit signature with `*,` separator after `on_refresh` so `account_map` is keyword-only and existing positional callers don't break.
- **2026-05-03 (v2.1)** — Two minor cleanup edits applied per Codex R2 PASS-with-edits. No structural changes; plan content equivalent to v2 PASS verdict. **Ready to schedule for implementation.**
