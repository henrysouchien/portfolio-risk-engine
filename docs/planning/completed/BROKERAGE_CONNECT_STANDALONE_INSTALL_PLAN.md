# Brokerage-connect — close standalone-install gaps

## Status: v5 — **SHIPPED 2026-05-01**. `brokerage-connect 0.4.0` published to PyPI; Class A surface (`brokerage.config` + `brokerage.futures` core) now standalone-importable; Class B (provider subpackages) remains monorepo-only per the deferred `BROKERAGE_CONNECT_VENDOR_API_BUDGET_PLAN.md`. Plan history v1-v4 below preserved for context.

## Ship Summary

**PyPI:** https://pypi.org/project/brokerage-connect/0.4.0/ (was 0.3.0; 0.4.0 closes the standalone-import gaps for `brokerage.config` and `brokerage.futures` core).

**Source-repo commits on origin/main:**
- `3d4ed5df` `fix(brokerage): make core futures imports standalone` — the 3 source edits (config.py inline + lazy yaml + TYPE_CHECKING pandas).
- `d5c270d6` `chore(brokerage): release standalone import fixes` — version bump 0.3.0 → 0.4.0 + CHANGELOG entry.
- `8d349dc5` `chore(brokerage): update rule_b_baseline for standalone-install changes` — `tests/api_budget/rule_b_baseline.json` cleanup after removing `from ibkr.config import` from config.py.

**Dist-repo commit:** `031f333` `sync: update from source repo` (in `~/Documents/Jupyter/brokerage-connect-dist/`).

**Verification (Phase A clean-install matrix, all passed):**
- Build: `brokerage_connect-0.4.0.tar.gz` + `.whl` built via hatchling.
- No-extras import probe: `OK 127.0.0.1 7496` (dotenv inline + 4 IBKR_* reads work).
- Lazy yaml probe: `ModuleNotFoundError(yaml)` raises as expected after DB fallback.
- With pyyaml + pandas installed: `load_contract_specs()` returned dict with 27 entries.

**Verification (Phase B monorepo parity, all passed):**
- Dotenv probe: `.env` loaded post-import, `SCHWAB_APP_KEY: True`, all 4 IBKR_* names with correct types.
- Malformed `IBKR_GATEWAY_PORT=not_a_number` falls back to 7496 (`_int_env` semantics preserved).
- Targeted pytest (9 files): 9→9 failed (no NEW brokerage-path failures).
- Full pytest: 77→17 failed (60 fewer — collateral benefit from installing `fakeredis`/`boto3`/`cvxpy`/etc. test deps during baseline capture).

**Verification (live runtime):**
- `risk_module` service restart: healthy on first try.
- `/api/positions/holdings` HTTP 200, sources `[plaid, schwab, snaptrade]` returning real data.
- `/api/snaptrade/connections` HTTP 200, 3 active Schwab connections.

**What now works for external users:**
```python
# In a fresh `pip install brokerage-connect` venv:
import brokerage                            # ✅
import brokerage.config                     # ✅ (IBKR_GATEWAY_HOST, etc. with defaults)
import brokerage.futures                    # ✅
import brokerage.futures.notional           # ✅
import brokerage.futures.contract_spec      # ✅ (load_contract_specs needs pyyaml at call time)
import brokerage.futures.pricing            # ✅ (Protocol class — sources need pandas)
```

**What still doesn't (Class B, deferred to vendoring plan):**
- `brokerage.snaptrade.*`, `brokerage.plaid.*`, `brokerage.schwab.*` — need `app_platform.api_budget.guard_call` + `config.api_budget_costs.COST_PER_CALL` vendored.
- `brokerage.ibkr.*` — needs `BudgetExceededError` + sibling `ibkr.*` modules vendored (different shape from the other three).
- `brokerage.futures.sources.*` — needs pandas + `portfolio_risk_engine.*` resolution.

See `BROKERAGE_CONNECT_VENDOR_API_BUDGET_PLAN.md` for the deferred work.

## Problem

The published `brokerage-connect 0.3.0` wheel (PyPI) installs cleanly but several public submodules **import-fail in a clean venv** because of undeclared dependencies. This was carry-forward from 0.2.2 — explicitly named out of scope in the layout-convergence PR's v3 review and the v6 ship doc — but it means the published package only really works for monorepo consumers, defeating part of the point of publishing.

**Scope clarification (v2):** there are TWO classes of monorepo coupling in the published package, and this plan only addresses the first.

### Class A — Trivial coupling (THIS PR fixes)

`brokerage.config`, `brokerage.futures` (package init + `contract_spec.py` + `pricing.py`) couple to monorepo only via:
- 4 trivial env-var reads from `ibkr.config` (no real package logic involved)
- yaml used inside one function (lazy-importable)
- pandas used purely for type annotations under `from __future__ import annotations` (TYPE_CHECKING-able)

These are fixable with surgical edits and zero new declared deps.

### Class B — Deep coupling (NOT addressed; separate plan filed)

After v2 review surfaced more coupling, the actual Class B surface is broader than initially scoped:

- **Three of four provider subpackages** (`brokerage.snaptrade`, `brokerage.plaid`, `brokerage.schwab`) import `app_platform.api_budget.guard_call` and `config.api_budget_costs.COST_PER_CALL` at the top level. Verified via grep: `snaptrade/client.py:8,19`, `plaid/client.py:10,18`, `plaid/connections.py:5,8`, `schwab/adapter.py:17,28`, `schwab/client.py:17,27`.
- **`brokerage.ibkr.adapter`** has a different but equally blocking coupling: imports `app_platform.api_budget.BudgetExceededError` (`ibkr/adapter.py:23`) AND 5+ sibling `ibkr.*` modules (`from ibkr.config`, `from ibkr.connection`, `from ibkr._budget`, `from ibkr.locks`, plus inline `from ibkr.contracts` at lines 184/291). No `COST_PER_CALL` here — IBKR uses a different api-budget surface than the other three providers.
- `brokerage/futures/sources/fmp.py` and `sources/ibkr.py` top-level `import pandas` + `portfolio_risk_engine.*` imports.

**This means**: even after this PR, `from brokerage.snaptrade import ...` (or plaid/schwab) fails on `ModuleNotFoundError: No module named 'app_platform'`. `from brokerage.ibkr.adapter import ...` fails the same way on `BudgetExceededError`, plus separately on the sibling `ibkr.*` imports. The published wheel's provider extras (`schwab`, `snaptrade`, `ibkr`, `plaid`) only pull the SDK packages, not the api-budget infrastructure or the IBKR sibling modules.

The two helpers used by SnapTrade/Plaid/Schwab (`guard_call`, `COST_PER_CALL`) follow a pattern CLAUDE.md already documents for `ibkr-mcp`: vendor `app_platform/api_budget/exceptions.py` → `budget_exceptions.py` and `config/api_budget_costs.py` via the sync script. The IBKR provider's coupling is deeper (sibling `ibkr.*` modules), and may need either separate vendoring of those modules OR acceptance as monorepo-only. Brokerage-connect doesn't have any vendoring set up today. **Filed separately as `BROKERAGE_CONNECT_VENDOR_API_BUDGET_PLAN.md`.**

Out of scope for THIS plan: vendoring infra, sources/* fixes, ibkr/adapter.py fix. This PR ships honest scope: `brokerage.config` + `brokerage.futures` core only.

### Concrete failure surface — what this PR DOES vs DOES NOT change

In a fresh `pip install brokerage-connect` venv (no extras):

| Import | Pre-PR | Post-PR | Notes |
|---|---|---|---|
| `from brokerage import BrokerAdapter, OrderResult, ...` | ✅ works | ✅ works (unchanged) | Already dependency-light. |
| `import brokerage.config` | ❌ `No module named 'ibkr'` | ✅ works | THIS PR — inline 4 env-var reads + dotenv loader. |
| `import brokerage.futures` (package init) | ❌ `No module named 'yaml'` | ✅ works | THIS PR — lazy yaml import. |
| `import brokerage.futures.notional` | ✅ works | ✅ works (unchanged) | No deps. |
| `import brokerage.futures.contract_spec` | ❌ `No module named 'yaml'` | ✅ works (DB probe falls back to YAML; YAML call needs `pip install pyyaml`) | THIS PR — lazy yaml inside `_load_contracts_yaml()`. Note: `load_contract_specs()` first tries an optional monorepo DB read (`from database import ...`, `from inputs.database_client import DatabaseClient`); failure is caught and falls back to YAML. Standalone clean-install hits the YAML fallback path. |
| `import brokerage.futures.pricing` | ❌ `No module named 'pandas'` | ✅ works (Protocol class only; runtime sources need pandas) | THIS PR — TYPE_CHECKING for pandas. |
| `import brokerage.futures.sources.*` | ❌ pandas + portfolio_risk_engine | ❌ same (Class B) | Separate plan. |
| `import brokerage.ibkr.adapter` | ❌ ibkr.* sibling imports | ❌ same (Class B) | Separate plan (vendoring). |
| `pip install brokerage-connect[snaptrade]` then `from brokerage.snaptrade.client import ...` | ❌ `No module named 'app_platform'` | ❌ same (Class B) | Separate plan. Provider subpackages need `guard_call` + `COST_PER_CALL` vendored from `app_platform.api_budget` + `config.api_budget_costs`. Filed as `BROKERAGE_CONNECT_VENDOR_API_BUDGET_PLAN.md`. |
| Same for `brokerage.plaid.*`, `brokerage.schwab.*`, `brokerage.ibkr.*` | ❌ same | ❌ same (Class B) | Same separate plan covers all four providers. |

**Cost surfaced 2026-05-01**: discussed during post-ship walkthrough of the layout convergence PR. Not yet caused a downstream incident, but degrades the integrity of the publish for the Class A surface — every external consumer is one import away from a broken `brokerage.config` or `brokerage.futures.pricing`.

## Why this exists today

The brokerage package was extracted from monorepo code that freely imports siblings (`ibkr.config`) and assumes monorepo deps (`yaml`, `pandas` are top-level deps in the monorepo's other pyprojects: `fmp/pyproject.toml:14` declares `pandas>=3.0,<4`; `ibkr/pyproject.toml:15-17` declares `pandas>=3.0,<4` and `pyyaml>=6.0,<7`).

When `brokerage-connect` was first carved out for publishing, the author kept extras minimal (`schwab`, `snaptrade`, `ibkr`, `plaid` SDKs only) — pandas/yaml never made it into a declared dep. The `ibkr.config` import was likely intentional in-monorepo (single source of truth for IBKR env-var defaults) but missed in the standalone-publish boundary review.

Reading the existing brokerage source shows the author already knows the pattern — `brokerage/_vendor.py:9-15` and `_logging.py` use `try/except` for optional `numpy`/`pandas` imports. The futures and config files just didn't get the same treatment.

## Inspection — what's actually needed at runtime

### `brokerage/config.py` — 4 names from `ibkr.config`

What the imports point to (`ibkr/config.py:41-54`):
- `IBKR_GATEWAY_HOST` — `os.getenv("IBKR_GATEWAY_HOST", "127.0.0.1")`
- `IBKR_GATEWAY_PORT` — `_int_env("IBKR_GATEWAY_PORT", 7496)` (helper just wraps `int(os.getenv(...))` with a default)
- `IBKR_READONLY` — `os.getenv("IBKR_READONLY", "false").lower() == "true"`
- `IBKR_AUTHORIZED_ACCOUNTS` — comma-split env var

All four are **trivial env-var reads with defaults**. No actual coupling to `ibkr` package logic — only to those four constants. Inlining the env-var reads into `brokerage/config.py` eliminates the cross-package import entirely.

### `brokerage/futures/contract_spec.py` — yaml

`import yaml` at line 8 is used only inside `_load_contracts_yaml()` (line 75-79: `yaml.safe_load(f)`). Trivially moved inside the function as a lazy import.

### `brokerage/futures/pricing.py` — pandas

`import pandas as pd` at line 5 is used purely for **type annotations** (`pd.Series` on lines 26, 57). The file already has `from __future__ import annotations` at line 1, which means type hints are deferred strings at runtime — pandas isn't actually needed to import the module. This is a textbook `if TYPE_CHECKING:` candidate.

The runtime path uses `prices.empty` (line ~67) on whatever a price source returns, but pricing.py itself never *constructs* a pandas object. Sources that produce `pd.Series` need pandas, but consumers using their own non-pandas sources don't.

## Options

### Option 1 — Lazy / TYPE_CHECKING imports (RECOMMENDED)

Match the existing pattern in `brokerage/_vendor.py` (try/except) and `brokerage/_logging.py` (graceful degradation). Three concrete edits:

1. **`brokerage/config.py`:** delete `from ibkr.config import (...)` lines 6-11 and inline the four env-var reads directly. (~6 lines added in place of 6 lines deleted; net wash.)
2. **`brokerage/futures/contract_spec.py`:** move `import yaml` (line 8) inside `_load_contracts_yaml()`.
3. **`brokerage/futures/pricing.py`:** convert `import pandas as pd` (line 5) to `if TYPE_CHECKING: import pandas as pd` (with `TYPE_CHECKING` added to the `typing` import).

**Pros:**
- Zero new runtime dependencies. `pip install brokerage-connect` (no extras) makes the Class A surface importable: `brokerage` (top-level), `brokerage.config`, `brokerage.futures` (init + `notional` + `contract_spec` + `pricing`). Provider subpackages and `futures.sources.*` remain Class B (separate vendoring plan).
- Matches existing in-package pattern (`_vendor.py` already does try/except for pandas/numpy).
- No extras complexity for users.
- Sources that *use* pandas at runtime (e.g., a `FuturesPriceSource` implementation that fetches from FMP) bring pandas themselves — consumers self-select.

**Cons:**
- Lazy imports defer ImportError to first use rather than module load. For yaml in `_load_contracts_yaml()` this means calling `load_contract_specs()` without yaml installed errors at the `import yaml` line — clear traceback, good. For pandas-as-type-hint, `TYPE_CHECKING` means no runtime check at all; failure happens when a price source actually returns a `pd.Series` and the consumer calls `.empty` on it.
- Slight behavioral change: today, `import brokerage.config` errors immediately if `ibkr` isn't installed. After the change, it succeeds. Anyone currently relying on that import-time error to detect monorepo absence (unlikely but possible) would lose that signal.

### Option 2 — Add a `futures` extra; keep `ibkr.config` import

Declare `[project.optional-dependencies] futures = ["pyyaml>=6,<7", "pandas>=3,<4"]`. Users opt in via `pip install brokerage-connect[futures]`. Keep `brokerage/config.py` as-is OR also add the futures-extras-style fix for ibkr (which would need a `core` extra or similar — awkward because env-var-with-default isn't really a dependency).

**Pros:**
- Standard Python packaging pattern.
- Explicit dep declaration documents that pandas/yaml are needed.

**Cons:**
- Doesn't fix the `ibkr.config` problem cleanly (you can't pip-install `ibkr` from PyPI; it's monorepo-only).
- Adds extras complexity users have to know about.
- Doesn't match existing in-package pattern (`_vendor.py` doesn't do extras for its optional pandas/numpy).

### Option 3 — Hybrid: inline `ibkr.config` reads + add `futures` extras

Combine. Best of both worlds at the cost of doing two different things for two different problems.

**Pros:**
- Clean for both concerns.

**Cons:**
- Inconsistency: ibkr handled one way, futures another.
- More moving parts than Option 1.

## Recommendation

**Option 1** — lazy + TYPE_CHECKING + inline. Three small surgical edits, zero new declared deps, matches existing in-package patterns, fixes both concerns the same way. Cleanest outcome.

Ship as **0.4.0** (MINOR bump because module-level import behavior changes — `import brokerage.config` succeeds in scenarios where it previously failed; that's a public-surface change).

## Implementation (v3 step sequence)

Single PR. Estimated ~1 hour including verification. Per CLAUDE.md plan-first workflow, send to Codex for review before execution.

1. **Edit `brokerage-connect/brokerage/config.py`.** Replace the `from ibkr.config import (...)` block at lines 6-11 with TWO things, in this order:

   **(a) Preserve the dotenv side effect.** Today, importing `brokerage.config` indirectly imports `ibkr.config`, which at module load runs (paraphrased from `ibkr/config.py:8-14`):
   ```python
   try:
       from pathlib import Path
       from dotenv import load_dotenv
       _pkg_dir = Path(__file__).resolve().parent
       load_dotenv(_pkg_dir.parent / ".env", override=False)
   except Exception:
       pass
   ```
   This means by the time `brokerage/config.py` reads its OWN `os.getenv("SCHWAB_APP_KEY", ...)`, `SNAPTRADE_*`, and `PLAID_*` vars (lines 13-26), `.env` has been loaded. **Removing the `from ibkr.config import` line removes that side effect** — monorepo callers who relied on .env being loaded would silently see empty strings. Inline an equivalent dotenv loader at the TOP of `brokerage/config.py`, before the four IBKR_* assignments AND before the existing `SCHWAB_*`/`SNAPTRADE_*`/`PLAID_*` reads:

   ```python
   try:
       from pathlib import Path
       from dotenv import load_dotenv

       _pkg_dir = Path(__file__).resolve().parent
       load_dotenv(_pkg_dir.parent.parent / ".env", override=False)
   except Exception:
       pass
   ```

   **Path arithmetic:** `brokerage/config.py` lives at `<repo>/brokerage-connect/brokerage/config.py`. `Path(__file__).resolve().parent` = `<repo>/brokerage-connect/brokerage/`. We want `<repo>/.env`, so `_pkg_dir.parent.parent / ".env"` = `<repo>/brokerage-connect/.env`... wait — verify by walking each `.parent`: `_pkg_dir` = `brokerage/`, `.parent` = `brokerage-connect/`, `.parent.parent` = `<repo>/`. So `_pkg_dir.parent.parent / ".env"` IS `<repo>/.env`. Confirmed correct (Codex re-verified this in v2 review). **`from pathlib import Path` MUST be inside the try block** so a missing `python-dotenv` package doesn't accidentally silence a real `NameError`.

   **(b) Inline the four IBKR_* reads with `_int_env`-equivalent behavior.** Plain `int(os.getenv(...))` raises on malformed input; the source's `_int_env` helper catches `TypeError`/`ValueError` and falls back to default. Inline a small helper to preserve that:
   ```python
   def _int_env(name: str, default: int) -> int:
       raw = os.getenv(name)
       if raw is None:
           return default
       try:
           return int(raw)
       except (TypeError, ValueError):
           return default

   IBKR_GATEWAY_HOST: str = os.getenv("IBKR_GATEWAY_HOST", "127.0.0.1")
   IBKR_GATEWAY_PORT: int = _int_env("IBKR_GATEWAY_PORT", 7496)
   IBKR_READONLY: bool = os.getenv("IBKR_READONLY", "false").lower() == "true"
   IBKR_AUTHORIZED_ACCOUNTS: list[str] = [
       account.strip()
       for account in os.getenv("IBKR_AUTHORIZED_ACCOUNTS", "").split(",")
       if account.strip()
   ]
   ```
   Match the source's exact defaults (`127.0.0.1`, `7496`, `false`, empty list) and the malformed-input fallback semantics. Add a comment cross-referencing `ibkr/config.py` for future-drift detection.

   **(c) Final structure of `brokerage/config.py`** after edit:
   - dotenv try/except block (top)
   - `_int_env` helper
   - 4 IBKR_* reads (using helper where needed)
   - existing SCHWAB_*/SNAPTRADE_*/PLAID_* reads (unchanged)
   - No more `from ibkr.config import`.

2. **Edit `brokerage-connect/brokerage/futures/contract_spec.py`.** Delete `import yaml` at line 8 (top-level). Add `import yaml` as the first line inside `_load_contracts_yaml()` (line 75). Yaml is only used at that call site (`yaml.safe_load(f)` on line 79).

3. **Edit `brokerage-connect/brokerage/futures/pricing.py`.** Replace `import pandas as pd` at line 5 with:
   ```python
   from typing import TYPE_CHECKING, List, Optional, Protocol

   if TYPE_CHECKING:
       import pandas as pd
   ```
   (i.e., add `TYPE_CHECKING` to the existing typing import and gate pandas under it). Type annotations `Optional[pd.Series]` and `pd.Series` continue to work at static-analysis time because of `from __future__ import annotations` at line 1; runtime evaluation is never triggered.

4. **Bump version in `brokerage-connect/pyproject.toml`** from `0.3.0` to `0.4.0`.

5. **Update CHANGELOG entry** (will be added at release time per the publish-script flow). Wording must be precise about scope — explicitly enumerate what does AND does NOT become standalone-importable:

   > **Standalone-install gaps closed for `brokerage.config` and `brokerage.futures` core.** In a clean `pip install brokerage-connect` venv (no extras), the following now import successfully: `import brokerage.config`, `import brokerage.futures`, `import brokerage.futures.notional`, `import brokerage.futures.contract_spec` (DB probe falls back gracefully to YAML), and `import brokerage.futures.pricing` (Protocol class only). Achieved via inlining 4 IBKR_* env-var reads (preserving `_int_env` fallback semantics + dotenv loader), lazy `import yaml` inside `_load_contracts_yaml()`, and `TYPE_CHECKING`-gated pandas in pricing.py. **Not addressed in this release:** provider subpackages and price-source adapters retain monorepo coupling. SnapTrade/Plaid/Schwab depend on `app_platform.api_budget.guard_call` + `config.api_budget_costs.COST_PER_CALL`. IBKR depends on `app_platform.api_budget.BudgetExceededError` + sibling `ibkr.*` modules (config, connection, _budget, locks, contracts). `brokerage.futures.sources.*` additionally imports `pandas` + `portfolio_risk_engine.*`. Filed separately as `BROKERAGE_CONNECT_VENDOR_API_BUDGET_PLAN.md` for future vendoring work.

## Verification

Two-phase gate: (A) clean-install matrix proves the fix works for external users; (B) monorepo parity proves no regression for existing callers.

### Phase A — Clean-install matrix (reuses layout PR's step-9 pattern)

Run from `brokerage-connect/`:

```bash
python3 -m build
VENV=/tmp/brokerage-standalone-$(date +%s)
python3 -m venv "$VENV"

# 1. Install WITHOUT any extras
"$VENV/bin/pip" install dist/brokerage_connect-0.4.0-py3-none-any.whl

# 2. Verify the Class A surface (brokerage top-level, .config, .futures init, .futures.notional, .futures.contract_spec, .futures.pricing) imports cleanly
"$VENV/bin/python" -c "
import brokerage
import brokerage.config
import brokerage.broker_adapter
import brokerage.trade_objects
import brokerage.futures
import brokerage.futures.pricing
import brokerage.futures.contract_spec
from brokerage import BrokerAdapter, OrderResult, OrderPreview, TradePreviewResult
from brokerage.config import IBKR_GATEWAY_HOST, IBKR_GATEWAY_PORT, IBKR_READONLY, IBKR_AUTHORIZED_ACCOUNTS
print('OK', IBKR_GATEWAY_HOST, IBKR_GATEWAY_PORT)
"
# Expected: prints 'OK 127.0.0.1 7496'

# 3. Verify lazy imports raise clear errors when actually used
"$VENV/bin/python" -c "
from brokerage.futures.contract_spec import load_contract_specs
try:
    load_contract_specs()
    print('UNEXPECTED: load_contract_specs() succeeded without yaml installed')
except ModuleNotFoundError as e:
    if 'yaml' in str(e):
        print('OK: load_contract_specs raises ModuleNotFoundError(yaml) as expected')
    else:
        raise
"

# 4. Install yaml + pandas, verify futures functions actually work
"$VENV/bin/pip" install pyyaml pandas
"$VENV/bin/python" -c "
from brokerage.futures.contract_spec import load_contract_specs
result = load_contract_specs()
print('OK load_contract_specs returned:', type(result).__name__, 'with', len(result), 'entries')
"
```

Hard gates: steps 2 and 4 must print `OK`. Step 3 must demonstrate the deferred-error behavior (clear ModuleNotFoundError when yaml is genuinely missing).

### Phase B — Monorepo parity (proves no regression for existing callers)

Inside the monorepo's `.venv` (where `ibkr` is importable):

```bash
# 1. Verify brokerage.config still loads .env exactly as it did before
.venv/bin/python -c "
import os
from pathlib import Path
# Snapshot SCHWAB_APP_KEY before import (should be unset or whatever's in env)
before = os.environ.get('SCHWAB_APP_KEY', '<unset>')
import brokerage.config as bc
# After import, .env should have been loaded. SCHWAB_* should match what's in .env.
after = os.environ.get('SCHWAB_APP_KEY', '<unset>')
print('before:', '<set>' if before != '<unset>' else '<unset>', '/ after:', '<set>' if after != '<unset>' else '<unset>')
print('SCHWAB_APP_KEY loaded from .env:', bool(bc.SCHWAB_APP_KEY))
print('IBKR_GATEWAY_HOST:', bc.IBKR_GATEWAY_HOST)
print('IBKR_GATEWAY_PORT:', bc.IBKR_GATEWAY_PORT, type(bc.IBKR_GATEWAY_PORT).__name__)
print('IBKR_READONLY:', bc.IBKR_READONLY, type(bc.IBKR_READONLY).__name__)
print('IBKR_AUTHORIZED_ACCOUNTS:', bc.IBKR_AUTHORIZED_ACCOUNTS, type(bc.IBKR_AUTHORIZED_ACCOUNTS).__name__)
"

# 2. Verify _int_env malformed-input fallback (THE behavioral diff Codex flagged)
IBKR_GATEWAY_PORT=not_a_number .venv/bin/python -c "
import brokerage.config as bc
assert bc.IBKR_GATEWAY_PORT == 7496, f'Expected fallback to 7496, got {bc.IBKR_GATEWAY_PORT!r}'
print('OK: malformed IBKR_GATEWAY_PORT falls back to 7496')
"

# 3. Targeted pytest gate — re-run the test directories that touch brokerage.config, brokerage.futures, and provider subpackages
.venv/bin/python -m pytest tests/brokerage/ tests/api_budget/ tests/providers/ tests/snaptrade/ tests/api/ tests/services/ tests/options/ tests/trading_analysis/ tests/test_startup_validation.py -q --no-header
# PASS condition: parity vs current main baseline. No NEW failure names.

# 4. Full pytest run — required hard gate (config.py is too widely imported to skip)
.venv/bin/python -m pytest tests/ -q --no-header
# PASS condition: parity vs current main baseline. Capture failure nodeids to /tmp/v3-post-failures.txt and diff against /tmp/pre-move-failures.txt (or a freshly captured pre-PR baseline). No NEW failure names introduced by the edits.
```

Hard gates for Phase B: ALL FOUR steps are blocking. Steps 1 and 2 must produce expected output (dotenv loaded SCHWAB_*; malformed IBKR_GATEWAY_PORT falls back to 7496). Steps 3 and 4 must show parity (no NEW failure names). If a NEW failure appears in tests that import `brokerage.config` or `brokerage.futures`, STOP — the inline likely diverged from `ibkr.config` semantics in a way the unit tests catch. If a NEW failure appears in provider tests (snaptrade/plaid/schwab/ibkr), STOP and verify it's not a side effect of the dotenv inline (e.g., monorepo-only test fixture that previously got `.env` via the `ibkr.config` import chain and now sees a different load order).

## Risks

- **Step 1 inline drift.** If `ibkr/config.py` changes its default values, `_int_env` parsing logic, or dotenv loading behavior for the IBKR_* env vars, `brokerage/config.py` won't auto-track. Mitigation: env var names are an external contract that rarely changes; the four defaults (127.0.0.1, 7496, false, empty list) are stable IBKR-gateway conventions; the malformed-input fallback semantics are preserved by inlining `_int_env`; the dotenv loader path is preserved by direct inline. Add a `# Cross-reference: ibkr/config.py:41-58` comment in both files for future-drift detection. Optional: a CI/lint step that diff-checks the four env-var read lines could harden this further (out of scope for this PR).
- **dotenv path regression.** The inline dotenv loader resolves `.env` relative to `brokerage/config.py`'s parent. The current `ibkr/config.py` resolves to `ibkr/__file__.parent.parent / ".env"` = `<repo>/.env`. The new inline must resolve to the SAME `<repo>/.env` from `brokerage-connect/brokerage/config.py` — that's `_pkg_dir.parent.parent / ".env"` (one extra level up because of the nested layout). Verify in Phase B step 1 that SCHWAB_APP_KEY (or any other .env-only var) is loaded post-import.
- **TYPE_CHECKING fragility.** If a future change to `pricing.py` adds runtime pandas use (e.g., constructing a `pd.Series` directly), `TYPE_CHECKING` would let the change land without ImportError until that code runs. Mitigation: add a comment near the TYPE_CHECKING import explicitly stating "pandas is type-only here; if you add runtime use, declare pandas as a real dependency or move it to a futures extra."
- **Behavioral change to import semantics.** Today, `import brokerage.config` errors immediately when `ibkr` isn't installed. After this PR, it succeeds. Anyone (very unlikely) using the import-time error as a monorepo-presence detector would lose that signal. Acceptable: the documented contract of `import brokerage.config` doesn't promise anything about `ibkr`.
- **Pre-existing `_vendor.py` pandas/numpy try/except interaction.** `_vendor.py` already gracefully degrades when pandas is missing (`np = None` / `pd = None`). After this PR, `_vendor.py` still imports cleanly without pandas — no change. Verify in the smoke matrix that `import brokerage._vendor` works in the no-extras venv.
- **Class B coupling unchanged.** This PR does NOT fix `brokerage.ibkr.adapter` or `brokerage.futures.sources.*`. External consumers attempting to `import brokerage.ibkr` or `import brokerage.futures.sources` after this PR will still hit ImportError. The narrowed scope claim in §Problem table makes this explicit; CHANGELOG/release-notes wording must match.

## Out of scope

- Adding `futures` or `data` extras for users who *want* declared dependencies. Optionally add later if user feedback requests it; for now, lazy/TYPE_CHECKING is the minimal change.
- Refactoring `_vendor.py` for consistency. It already uses try/except — fine as-is.
- Vendoring `ibkr/config.py` into brokerage-connect via the sync script (Option B in earlier analysis). Inlining 4 env-var reads is simpler than introducing a vendoring layer.
- Splitting `brokerage.futures` into a separate optional subpackage. The current package shape is fine after the lazy-import fix.
- Adding integration tests for the standalone-install scenario. The verification matrix in this plan is a one-shot gate; long-term CI for clean-install would be a separate quality-engineering effort.

## Decisions log

- **2026-05-01 (v1)** — Recommendation: Option 1 (lazy + TYPE_CHECKING + inline). Filed as follow-up to layout-convergence ship the previous day. Inspection confirmed: `ibkr.config` import is just 4 trivial env-var reads (inline-able), yaml is only used inside `_load_contracts_yaml()` (lazy-import-able), pandas in `pricing.py` is purely type annotations (TYPE_CHECKING-able since `from __future__ import annotations` is already in use). Existing in-package pattern in `_vendor.py` is try/except for optional deps — Option 1 is consistent with that. Ship as 0.4.0 (MINOR bump for public-surface behavior change).
- **2026-05-01 (v4)** — Codex review of v3 returned FAIL with 2 small required changes. Both addressed:
  1. **Residual "every/all public submodules" overclaim.** v3's §Option 1 (line 93) and Phase A step 2 header still used absolute language. v4 narrowed both to "Class A surface" with explicit enumeration: `brokerage` (top-level), `brokerage.config`, `brokerage.futures` (init + `notional` + `contract_spec` + `pricing`).
  2. **IBKR's distinct monorepo coupling.** v3 conflated all four providers under `guard_call` + `COST_PER_CALL`, but `brokerage/ibkr/adapter.py:23` imports `app_platform.api_budget.BudgetExceededError` (different surface), and has no `COST_PER_CALL`. v4 §Problem now distinguishes: SnapTrade/Plaid/Schwab use `guard_call` + `COST_PER_CALL`; IBKR uses `BudgetExceededError` + sibling `ibkr.*` modules. CHANGELOG step-5 wording, status line, and §Problem all updated.
- **2026-05-01 (v3)** — Codex review of v2 returned FAIL with 4 required changes (deeper scope correction + 2 small fixes). All addressed:
  1. **All provider subpackages are Class B**, not just `brokerage.ibkr.adapter`. Verified via grep: `snaptrade/client.py:8,19`, `plaid/client.py:10,18`, `plaid/connections.py:5,8`, `schwab/adapter.py:17,28`, `schwab/client.py:17,27` import `app_platform.api_budget.guard_call` + `config.api_budget_costs.COST_PER_CALL`. `ibkr/adapter.py:23` imports `app_platform.api_budget.BudgetExceededError` (different api-budget surface) plus 5+ sibling `ibkr.*` modules. v3 §Problem narrows Class A surface to `brokerage.config` + `brokerage.futures` core only; provider subpackages and `futures/sources/*` move to Class B with explicit "filed separately" pointer to a vendoring plan.
  2. **`contract_spec.py:147-153`** has a lazy DB probe (`from database import ...`, `from inputs.database_client import DatabaseClient`) wrapped in try/except with YAML fallback. Doesn't block clean-install (clean venv hits the YAML path), but the file isn't purely yaml-coupled. v3 import-surface table notes this explicitly.
  3. **`from pathlib import Path` import in step 1.** v2 showed the dotenv block but didn't explicitly call out the `Path` import inside the try block. v3 step 1 now shows the full inline including the `from pathlib import Path` line, and notes it must be inside the try block so missing python-dotenv doesn't cause `NameError` to silently masquerade as the legitimate failure mode.
  4. **Phase B test-gate contradiction.** v2 said full pytest is "optional but recommended" then named it as a hard gate. v3 makes it explicitly hard, expands the targeted-pytest list to include `tests/snaptrade/`, `tests/api/`, `tests/services/`, `tests/options/`, `tests/trading_analysis/`, `tests/test_startup_validation.py` (per Codex's grep of config-touching test files).
- **2026-05-01 (v2)** — Codex review of v1 returned FAIL with 4 required changes. All addressed:
  1. **`_int_env` semantics preserved.** v1's `int(os.getenv(...))` would raise on malformed input; ibkr/config.py's `_int_env` falls back to default. v2 step 1 now inlines an equivalent `_int_env` helper. Phase B verification step 2 explicitly tests `IBKR_GATEWAY_PORT=not_a_number` falls back to 7496.
  2. **dotenv side effect preserved.** v1 missed that `from ibkr.config import` triggers `load_dotenv("<repo>/.env")` at module load, which is what makes brokerage.config's own `SCHWAB_*`/`SNAPTRADE_*`/`PLAID_*` reads see populated values. v2 step 1 now inlines the same dotenv try/except block at the top of `brokerage/config.py`, with the path adjusted for the nested layout (`_pkg_dir.parent.parent / ".env"` resolves to the same `<repo>/.env`).
  3. **Scope claims corrected.** v1 claimed "every public submodule importable in clean-install" — wrong. `brokerage.ibkr.adapter` and `brokerage.futures.sources.*` have deep monorepo coupling beyond what this PR fixes. v2 §Problem now distinguishes Class A (this PR) from Class B (separate plan), with a precise pre-PR/post-PR import surface table. CHANGELOG wording in step 5 also tightened.
  4. **Monorepo parity verification added.** v1 only covered clean-install. v2 now has a Phase B that runs targeted pytest + full pytest against monorepo with parity-vs-baseline gates, plus explicit dotenv and malformed-int probes.
