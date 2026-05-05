# Brokerage-connect — vendor api-budget infra into the published wheel

> Archived 2026-05-04 under `docs/planning/completed/` after shipped status verification.

## Status: v4.1 — **SHIPPED 2026-05-03** (v4 Codex PASS R3 → v4.1 patch + impl + monorepo parity test + clean-wheel verification + push + PyPI publish all completed in one session)

PyPI: https://pypi.org/project/brokerage-connect/0.5.0/
Source commit: `d03a6c05` (risk_module main)
Dist commit: `a01937d` (brokerage-connect main)

## Problem

The published `brokerage-connect` wheel's provider subpackages all import monorepo helpers at the top level — but in TWO distinct shapes that this plan must address separately:

**Shape 1 — SnapTrade / Plaid / Schwab use `guard_call` + `COST_PER_CALL`:**
- `from app_platform.api_budget import guard_call` (the throttle/budget primitive)
- `from config.api_budget_costs import COST_PER_CALL` (the cost dictionary that `guard_call` reads)

Verified locations:
- `brokerage/snaptrade/client.py:8,19`
- `brokerage/plaid/client.py:10,18`, `brokerage/plaid/connections.py:5,8`
- `brokerage/schwab/adapter.py:17,28`, `brokerage/schwab/client.py:17,27`

**Shape 2 — IBKR uses `BudgetExceededError` + sibling `ibkr.*` modules + monorepo-only deps:**
- `brokerage-connect/brokerage/ibkr/adapter.py:23` — `from app_platform.api_budget import BudgetExceededError` (just the exception, not `guard_call`)
- `brokerage-connect/brokerage/ibkr/adapter.py:40-48` — sibling `ibkr.config`, `ibkr.connection`, `ibkr._budget`, `ibkr.locks`, `ibkr.contracts`
- `brokerage-connect/brokerage/ibkr/adapter.py:49` — `from options import OptionLeg, OptionStrategy` (monorepo-only, **not flagged in v1**)
- `brokerage-connect/brokerage/ibkr/adapter.py:50` — `from providers.routing_config import TRADE_ACCOUNT_MAP` (monorepo-only, **not flagged in v1**)

The IBKR adapter has deep coupling into the sibling `ibkr/` package's connection/lock/contract/budget machinery PLUS pulls in `options/` and `providers/routing_config` — both monorepo-only and unrelated to the api-budget vendoring problem. **Investigation verdict (v2):** IBKR cannot fit this plan's solution. Documented as monorepo-only for 0.5.0; separate plan needed to refactor the `options`/`providers` coupling and decide whether to take a runtime dep on the published `ibkr-mcp` PyPI package for the sibling machinery.

External users running `pip install brokerage-connect[snaptrade]` (or `[plaid]`/`[schwab]`) and trying `from brokerage.snaptrade.client import ...` hit `ModuleNotFoundError: No module named 'app_platform'`. The provider extras only pull the SDK packages (snaptrade-python-sdk, plaid-python, schwab-py); they don't pull the api-budget infrastructure those provider modules require.

This means the published `brokerage-connect` wheel is currently a **monorepo companion package**, not a standalone library. The `STANDALONE_INSTALL_PLAN.md` (shipped 2026-05-01) closes the surface for `brokerage.config` and `brokerage.futures` core; this plan closes it for SnapTrade / Plaid / Schwab providers. **IBKR is out of scope** — see Shape 2 above.

## Pattern to follow — ibkr-mcp's vendoring (mirror exactly)

CLAUDE.md "Cross-package vendoring rule" already documents the pattern. Existing whitelist:

| Source | Vendored into ibkr-mcp |
|---|---|
| `app_platform/api_budget/exceptions.py` | ✓ (as `_shared/budget_exceptions.py`) |
| `config/api_budget_costs.py` | ✓ |
| `utils/timeseries_store.py` | ✓ |

`ibkr-mcp`'s `_shared/` is built by `scripts/sync_ibkr_mcp.sh`: copy the source files, sed-rewrite imports to point at the vendored paths.

**brokerage-connect needs the SAME minimal vendor set** (revised from v1):

| Source | Vendor target |
|---|---|
| `app_platform/api_budget/exceptions.py` | `brokerage-connect/brokerage/_shared/budget_exceptions.py` |
| `config/api_budget_costs.py` | `brokerage-connect/brokerage/_shared/api_budget_costs.py` |

**Why not vendor `guard_call` itself (v2 scope reduction):** the investigation block found that vendoring `guard_call` drags Redis + Postgres + a `lua/` scripts directory + `database.session` + `utils.logging` into the standalone-install dep surface. The cleaner pattern — adapted from `ibkr/_budget.py:8-13` but **narrowed (v3)** to avoid silently masking transitive monorepo import breaks — is to wrap the `guard_call` import in a try/except fallback that only catches the missing-`app_platform` case:

```python
try:
    from app_platform.api_budget import guard_call
except ModuleNotFoundError as e:
    # Only fall back when app_platform itself or its api_budget submodule is unavailable
    # (dist runtime). Re-raise if a transitive import inside app_platform.api_budget fails —
    # those represent monorepo bugs that must surface, not silently disable budget enforcement.
    if e.name not in {"app_platform", "app_platform.api_budget"}:
        raise
    def guard_call(*, fn, args=(), kwargs=None, **_):
        """No-op fallback when app_platform.api_budget isn't installed (dist runtime)."""
        return fn(*args, **(kwargs or {}))
```

**Why the narrowing matters:** `app_platform/api_budget/__init__.py` imports `guard.py` eagerly, and `guard.py` imports monorepo deps like `database.session` and `utils.logging`. If a refactor breaks `database.session`, the v2 blanket `except ImportError` would silently swallow it and replace `guard_call` with the no-op — disabling budget enforcement repo-wide with no signal. The narrowed predicate (v4) catches only `ModuleNotFoundError` (a strict subclass of `ImportError` — won't catch `ImportError("cannot import name 'guard_call'")` failures from refactor breaks) and matches `e.name` against the exact set `{"app_platform", "app_platform.api_budget"}` so any other module's failure surfaces loudly.

This means external `pip install brokerage-connect[snaptrade]` users get unguarded provider calls (which is fine — they're not in the monorepo's billing context anyway), and monorepo callers still hit the real `guard_call`. `BudgetExceededError` and the entire `config/api_budget_costs.py` module (which includes `COST_PER_CALL` *and* helper functions like `get_cost_model_and_rate` at `config/api_budget_costs.py:99`) are stdlib-only and vendor cleanly via the ibkr-mcp pattern.

## Options

### Option 1 — Vendor via sync script + try/except shim at use-sites (RECOMMENDED, mirrors ibkr-mcp)

Extend `scripts/sync_brokerage_connect.sh` (currently 41 lines, pure rsync — no `_shared/` stage today) to add a vendoring stage:
1. Copy `app_platform/api_budget/exceptions.py` → `brokerage/_shared/budget_exceptions.py` and `config/api_budget_costs.py` → `brokerage/_shared/api_budget_costs.py`.
2. Sed-rewrite imports in provider files:
   - `from app_platform.api_budget import BudgetExceededError` → `from brokerage._shared.budget_exceptions import BudgetExceededError`
   - `from config.api_budget_costs import COST_PER_CALL` → `from brokerage._shared.api_budget_costs import COST_PER_CALL`
3. Wrap `guard_call` imports in try/except no-op fallback at the 5 source sites in monorepo (`brokerage-connect/brokerage/snaptrade/client.py:8`, `brokerage-connect/brokerage/plaid/client.py:10`, `brokerage-connect/brokerage/plaid/connections.py:5`, `brokerage-connect/brokerage/schwab/adapter.py:17`, `brokerage-connect/brokerage/schwab/client.py:17`) — pattern from `ibkr/_budget.py:8-13`. No sed needed for this; edit source directly.
4. Update CLAUDE.md vendoring table to add brokerage-connect column for `exceptions.py` + `api_budget_costs.py`.

Mirrors the existing ibkr-mcp pattern exactly. **No new runtime deps needed in pyproject** — exceptions/cost-dict are stdlib-only.

### Option 1b — Also vendor `guard_call` machinery (REJECTED in v2)

Investigation block found this drags Redis + Postgres + `lua/` resources + `database.session` + `utils.logging` into standalone-install. External users without Redis/Postgres can't run it. Rejected; try/except shim achieves same outcome with zero runtime infra obligation.

### Option 2 — Extract `app_platform.api_budget` into its own published PyPI package

Make `app-platform-api-budget` (or similar) a real PyPI package. brokerage-connect declares it as a regular dependency. ibkr-mcp does the same.

**Pros:** No vendoring duplication; single source of truth; standard package management.
**Cons:** Significant scope — new PyPI publish workflow, version bumps coordinated across consumers, license/URL/branding decisions for the spun-out package. May force additional refactoring of `app_platform.api_budget` to make it cleanly separable. **Same Redis/Postgres dep problem as Option 1b** — making it a real dep doesn't make external users have Redis.

### Option 3 — Refactor providers to take `guard_call` and `COST_PER_CALL` as injected dependencies

Change provider class constructors to accept `guard_call` and cost dict as parameters. Monorepo callers wire the real ones; standalone external users wire stubs or no-ops.

**Pros:** Eliminates the import coupling; lets external users opt into a no-budget-tracking mode.
**Cons:** Touches every provider class signature. Bigger refactor. Pattern doesn't match the rest of the package.

## Recommendation

**Option 1 (v2 reduced scope).** Matches existing in-repo pattern (ibkr-mcp) exactly — same 2-file vendor whitelist, same sed-rewrite shape, same drift discipline. Defer Option 2 until/unless multiple monorepos need the helpers.

## Implementation (concrete — v2 ready for Codex review polish)

### Step 1a — Wrap `guard_call` imports at 5 source sites with narrowed try/except shim

In monorepo, edit each file directly (no sed; this is a one-time source change):

| File | Line |
|---|---|
| `brokerage-connect/brokerage/snaptrade/client.py` | 8 |
| `brokerage-connect/brokerage/plaid/client.py` | 10 |
| `brokerage-connect/brokerage/plaid/connections.py` | 5 |
| `brokerage-connect/brokerage/schwab/adapter.py` | 17 |
| `brokerage-connect/brokerage/schwab/client.py` | 17 |

Replace `from app_platform.api_budget import guard_call` with the **narrowed** try/except block shown in "Pattern to follow" above — *not* the blanket `except ImportError:` form used in `ibkr/_budget.py:8-13` (that pattern is too broad; v3+v4 narrows it to `except ModuleNotFoundError` with exact `e.name` matching). All 5 sites use the exact same block; consider extracting to `brokerage-connect/brokerage/_shared/budget_shim.py` if duplication bothers you, but inline is fine and matches existing conventions.

### Step 1b — Wrap `FRONTEND_BASE_URL` import at 1 source site (NEW in v4.1)

Replace `from settings import FRONTEND_BASE_URL` at `brokerage-connect/brokerage/snaptrade/connections.py:27` with:

```python
try:
    from settings import FRONTEND_BASE_URL
except ModuleNotFoundError as e:
    if e.name != "settings":
        raise
    import os
    FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")
```

**Why:** monorepo `settings.py:19` is just `os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")` — pure env-var passthrough. The shim falls back to the same env-var read with the same default in dist (no `settings` module). In monorepo, the import succeeds and we get the value via `settings.py` (which also triggers `.env` loading via `dotenv` at `settings.py:11-16`, though by the time provider code runs that's already happened upstream). The `e.name != "settings"` check re-raises any other ImportError for loud surfacing.

**Why this was missed in v1→v4:** investigation block grepped for `app_platform.*` and `config.*` couplings (the two known shapes from the original problem framing) but did not sweep for arbitrary monorepo top-level imports like `settings`. v4.1 sweep confirmed `settings` is the only remaining gap; all other in-scope provider imports (snaptrade/plaid/schwab) are either covered by v4 or stdlib/PyPI.

### Step 2 — Extend `scripts/sync_brokerage_connect.sh`

Currently 41 lines, pure rsync. Add a vendoring stage after the rsync block, plus a post-sync drift check:

```bash
# Vendor app_platform.api_budget exceptions (BudgetExceededError + BudgetGuardUnavailable)
mkdir -p "$TARGET/brokerage/_shared"
cp "$MONOREPO/app_platform/api_budget/exceptions.py" "$TARGET/brokerage/_shared/budget_exceptions.py"

# Vendor config.api_budget_costs (full module — COST_PER_CALL + helper fns like get_cost_model_and_rate)
cp "$MONOREPO/config/api_budget_costs.py" "$TARGET/brokerage/_shared/api_budget_costs.py"

# Add __init__.py marker if not present
touch "$TARGET/brokerage/_shared/__init__.py"

# Rewrite imports across provider subpackages (excludes brokerage/ibkr/ — monorepo-only)
find "$TARGET/brokerage/snaptrade" "$TARGET/brokerage/plaid" "$TARGET/brokerage/schwab" \
    -name '*.py' -exec sed -i '' \
    -e 's|from app_platform\.api_budget import BudgetExceededError|from brokerage._shared.budget_exceptions import BudgetExceededError|g' \
    -e 's|from config\.api_budget_costs|from brokerage._shared.api_budget_costs|g' \
    {} \;

# Belt-and-suspenders drift check: fail loudly if any monorepo imports remain in dist providers.
# Note: `from app_platform.api_budget import guard_call` is INTENTIONALLY allowed to remain
# (it lives inside the try/except shim — the dist runtime catches the ImportError there).
# We grep specifically for BudgetExceededError + COST_PER_CALL imports, which sed must rewrite.
DRIFT=$(rg -n \
    -e 'from app_platform\.api_budget import BudgetExceededError' \
    -e 'from config\.api_budget_costs' \
    "$TARGET/brokerage/snaptrade" "$TARGET/brokerage/plaid" "$TARGET/brokerage/schwab" 2>/dev/null || true)
if [ -n "$DRIFT" ]; then
    echo "ERROR: monorepo imports remain in dist provider dirs after vendoring:" >&2
    echo "$DRIFT" >&2
    exit 1
fi
```

Note: `brokerage/ibkr/` is **excluded** from both the sed `find` and the drift check — IBKR is monorepo-only in 0.5.0 (see Out of scope and Step 5b).

### Step 3 — pyproject.toml

Bump version `0.4.0` → `0.5.0` at `brokerage-connect/pyproject.toml:7`. No new runtime deps. `exceptions.py` is stdlib-only; `api_budget_costs.py` is a `dict` literal plus a small helper function — both stdlib-only.

### Step 4 — Verify (clean-wheel test, not just source)

Build the wheel and test against the **published artifact**, not just monorepo source imports. Note the wheel-glob expansion is brittle — capture the path explicitly via `ls | head` (zsh-and-bash safe) before passing to pip with the bracketed extra:

```bash
# Build the wheel from the dist target
cd ~/Documents/Jupyter/brokerage-connect-dist
python -m build --wheel

# Capture the built wheel path (handles arbitrary build tag/python tag suffixes)
WHEEL=$(ls dist/brokerage_connect-0.5.0-*.whl | head -n1)
[ -z "$WHEEL" ] && { echo "ERROR: no wheel built"; exit 1; }

# In a fresh venv, verify each provider extra succeeds (or fails-as-documented for IBKR)
for extra in snaptrade plaid schwab; do
    python -m venv "/tmp/bc-test-${extra}"
    "/tmp/bc-test-${extra}/bin/pip" install "${WHEEL}[${extra}]"
    "/tmp/bc-test-${extra}/bin/python" -c "from brokerage.${extra} import client" || exit 1
done

# IBKR extra: SDK installs but adapter import is expected to fail with ModuleNotFoundError.
# The first failure point is `app_platform` (IBKR is excluded from the sed rewrite, so the
# monorepo import remains intact in the dist file). It will NOT reach the deeper
# `options` / `providers.routing_config` failures — that's expected and acceptable.
python -m venv /tmp/bc-test-ibkr
/tmp/bc-test-ibkr/bin/pip install "${WHEEL}[ibkr]"
/tmp/bc-test-ibkr/bin/python -c "from brokerage.ibkr.adapter import IBKRAdapter" 2>&1 | grep -q "ModuleNotFoundError" || exit 1
```

Also extend `BROKERAGE_CONNECT_STANDALONE_INSTALL_PLAN.md`'s clean-install matrix to record these results.

Monorepo parity: full pytest must pass at parity. The narrowed try/except shim is a no-op when `app_platform` is on sys.path (monorepo case), so semantics should be unchanged.

### Step 5 — Docs

Update CLAUDE.md vendoring table:

| Source | Vendored into fmp-mcp | Vendored into ibkr-mcp | Vendored into brokerage-connect |
|---|---|---|---|
| `utils/timeseries_store.py` | ✓ | ✓ | — |
| `utils/fmp_helpers.py` | ✓ | — | — |
| `app_platform/api_budget/exceptions.py` | — | ✓ (as `budget_exceptions.py`) | ✓ (as `budget_exceptions.py`) |
| `config/api_budget_costs.py` | — | ✓ | ✓ |

### Step 5b — IBKR docs/pyproject cleanup (NEW in v3, expanded in v4)

Codex flagged that `brokerage-connect/pyproject.toml:23` and `README.md:11,21` currently advertise `[ibkr]` as installable. Without changes, external users `pip install brokerage-connect[ibkr]` succeeds (installs `ib-async`) but `from brokerage.ibkr.adapter import IBKRAdapter` fails cryptically on `app_platform` / `options` / `providers.routing_config`. **v4 adds:** a second README at `brokerage-connect/brokerage/README.md` (titled "risk-module-brokerage" but ships in the wheel via rsync) also advertises IBKR. Fix all of these:

1. **Edit `brokerage-connect/README.md` install table** (line 11) — change IBKR row Status to: `"Monorepo-only — adapter requires risk_module monorepo (app_platform, options, providers.routing_config). [ibkr] extra installs the SDK but the adapter is not standalone-importable."`
2. **Edit `brokerage-connect/README.md` install example block** (line 21) — drop `[schwab,ibkr]` example or replace with `[schwab,plaid]`.
3. **Edit `brokerage-connect/brokerage/README.md` (v4 NEW)** — three locations advertise IBKR:
   - Line 28 — "Supported Integrations" table IBKR row: append "(monorepo-only — see top-level README)" to the "What it covers" cell.
   - Line 36 — install example: replace `pip install "risk-module-brokerage[schwab,ibkr]"` with `pip install "risk-module-brokerage[schwab,plaid]"`.
   - Line 51 — "How It Fits The Repo" entry already correctly notes IBKR sibling package; leave as-is or align wording with new top-level README copy if helpful.
4. **Keep `[ibkr]` extra in `pyproject.toml:23`** — removing breaks monorepo callers who install via the same wheel. Just document the limitation in README + CHANGELOG.
5. **Add CHANGELOG entry** at `brokerage-connect/CHANGELOG.md` (or create if absent): note 0.5.0 makes SnapTrade/Plaid/Schwab standalone, IBKR remains monorepo-only, link to the eventual follow-up plan.
6. **Add follow-up TODO marker** — already covered in Out of scope section's IBKR bullet.

### Step 6 — Ship

Bump to 0.5.0 (MINOR — surface expansion: 3 of 4 providers become standalone-installable). Run sync script, verify dist git status, commit + push dist repo, publish to PyPI per `docs/DEPLOY_CHECKLIST.md`.

## Open questions

All v1 open questions resolved by the 2026-05-01 investigation block:

- ~~`guard_call`'s API surface and dep tree~~ — Mapped. `guard_call` lives in `app_platform/api_budget/guard.py:386-399`; transitive closure includes `database.session`, `utils.logging`, `lua/` Lua scripts, optional `redis` + `celery`. **Resolution:** don't vendor `guard_call`; use try/except shim instead.
- ~~Redis/Postgres infra requirement~~ — Confirmed hard-required for `guard_call` machinery (Redis via `store.py`; Postgres via `api_call_log` writes). **Resolution:** moot under v2 reduced scope — only exception class + cost dict are vendored, both stdlib-only.
- ~~Drift check pattern~~ — Pure human discipline today (CLAUDE.md "re-run every sync script that whitelists it"). No automated check exists. **Resolution:** reuse same discipline; add brokerage-connect column to CLAUDE.md vendoring table.
- ~~IBKR adapter treatment~~ — Adapter has worse coupling than v1 flagged: also imports `options.OptionLeg/OptionStrategy` (line 49) and `providers.routing_config.TRADE_ACCOUNT_MAP` (line 50), both monorepo-only. **Resolution:** IBKR out of scope for 0.5.0; documented as monorepo-only; separate plan needed.

## Out of scope

- Anything `BROKERAGE_CONNECT_STANDALONE_INSTALL_PLAN.md` covers (`brokerage.config` + `brokerage.futures` core; shipped 2026-05-01 as 0.4.0).
- **`brokerage-connect[ibkr]` standalone install** — adapter pulls in `options/` + `providers/` + 5 sibling `ibkr.*` modules. Documented as monorepo-only in 0.5.0 (Step 5b); README + CHANGELOG flag the limitation. **Follow-up plan needed** (file in TODO.md as a separate row when scheduled): refactor `options/` + `providers.routing_config` couplings out of the IBKR adapter, then decide between (a) taking a runtime dep on the published `ibkr-mcp` PyPI package for the sibling `ibkr.*` machinery or (b) vendoring those siblings into `brokerage-connect/brokerage/_shared/ibkr/`.
- Vendoring `guard_call` itself (Option 1b — rejected; drags Redis + Postgres into the standalone-install dep surface).
- Spinning out `app_platform.api_budget` into its own PyPI package (Option 2).
- Refactoring providers to dependency-inject the budget primitives (Option 3).
- Fixing `brokerage.futures.sources.*` (`pandas` + `portfolio_risk_engine.*` coupling). Separate scope.

## Decisions log

- **2026-05-01 (v1)** — Filed as followup to STANDALONE_INSTALL_PLAN v3. Recommendation: Option 1 (vendor via sync script, mirror ibkr-mcp pattern). Held in DRAFT until scheduled — needs one block of investigation (read `app_platform/api_budget/` source, map runtime deps) before it's ready for Codex review.
- **2026-05-01 (v2)** — Investigation block complete. Four scope changes vs. v1:
  1. **Drop `guard_call` vendoring.** Investigation found it transitively pulls Redis + Postgres + `lua/` resources + `database.session` + `utils.logging`. Use try/except no-op shim at the 5 source sites instead — pattern already proven at `ibkr/_budget.py:8-13`.
  2. **Drop IBKR from scope.** Adapter imports `options/` + `providers.routing_config` (not flagged in v1) on top of the 5 sibling `ibkr.*` modules. Document `brokerage-connect[ibkr]` as monorepo-only in 0.5.0; separate plan handles it later.
  3. **Vendor whitelist matches ibkr-mcp exactly:** just `exceptions.py` + `api_budget_costs.py`. No third-vendor-target row.
  4. **Concrete `sync_brokerage_connect.sh` diff in Step 2** (script is 41 lines pure rsync today; v1 understated as "extend" — it's adding a vendoring stage from zero).
  Sent to Codex consult (session `019de614-57e1-7dd2-9ace-d60e01eccb7a`) — **FAIL** verdict with three release blockers.
- **2026-05-02 (v3)** — Polish after Codex review FAIL. Four targeted fixes:
  1. **Narrow the try/except shim** (Codex finding A). v2's `except ImportError:` was too broad — would silently swallow transitive monorepo import breaks (e.g., a bad refactor in `database.session`) and disable budget enforcement repo-wide with no signal. v3 narrows to `if e.name and not e.name.startswith("app_platform"): raise` so only the dist-runtime "app_platform missing" case falls back; any other import failure surfaces loudly.
  2. **Add post-sync drift check to `sync_brokerage_connect.sh`** (Codex finding B). Belt-and-suspenders `rg` that fails the script if `BudgetExceededError` or `COST_PER_CALL` imports remain in dist provider dirs after sed. (`guard_call` import is intentionally allowed inside the try/except shim — the drift check skips it.)
  3. **IBKR docs/pyproject cleanup** (Codex finding C, new Step 5b). v2 dropped IBKR from scope but didn't update `brokerage-connect/pyproject.toml:23` or `README.md:11,21`, both of which still advertise `[ibkr]` as installable. Step 5b updates README install table to mark IBKR as monorepo-only, drops the `[schwab,ibkr]` example, and adds a CHANGELOG entry. Pyproject `[ibkr]` extra stays (monorepo callers still need it).
  4. **Clean-wheel test, not just source imports** (Codex finding D). Step 4 now builds the wheel and tests against the published artifact in fresh venvs for each provider extra (snaptrade/plaid/schwab succeed; ibkr expected to fail-as-documented). Pyproject version bump made explicit (`0.4.0` → `0.5.0` at line 7). Note clarified that vendoring `config/api_budget_costs.py` covers the full module, including `get_cost_model_and_rate` at `:99` (Codex flagged this; verified — function lives in the vendored file, not in `app_platform/api_budget/guard.py`).
  Sent to Codex (resumed session) — **FAIL** with three concrete blockers (shim too loose, second README missed, wheel-install glob brittle).
- **2026-05-02 (v4)** — Polish after Codex review FAIL R2. Three targeted fixes:
  1. **Tighten shim predicate** (Codex finding 1). v3's `e.name.startswith("app_platform")` could swallow transitive `app_platform.something_else` failures. v4 uses exact set match `{"app_platform", "app_platform.api_budget"}` and switches `except ImportError` → `except ModuleNotFoundError` so `ImportError("cannot import name 'guard_call'")` from a refactor break also surfaces.
  2. **Add second README to Step 5b** (Codex finding 3). v3 missed `brokerage-connect/brokerage/README.md` (titled "risk-module-brokerage" but ships in the wheel via rsync). Three IBKR mentions there too — lines 28, 36, 51 — added to cleanup target list.
  3. **Fix wheel-install glob** (Codex finding 4). v3's `dist/brokerage_connect-0.5.0-*.whl"[${extra}]"` is a brittle quoted-glob form (zsh fails as unmatched glob; bash unreliable expansion). v4 captures the wheel path explicitly via `WHEEL=$(ls ... | head -n1)` first, then references `"${WHEEL}[${extra}]"`. Also clarified the IBKR test failure point will be `app_platform` (sed-excluded), not `options`/`providers` — accepted.
  Sent to Codex (resumed session) — **PASS** R3. All three findings verified FIXED, no new blockers. Plan ready to schedule.
- **2026-05-03 (v4.1)** — Implementation paused mid-flight. Codex (`mcp__codex__codex` impl session, threadId `019dee28-69df-70b1-97ac-41d23f4b4397`) applied Steps 1a/2/3/5/5b, ran sync script, built wheel, then stopped per the plan's STOP rules at the Step 4 SnapTrade smoke-import check: `brokerage-connect/brokerage/snaptrade/connections.py:27` imports `from settings import FRONTEND_BASE_URL` — a coupling the v1→v4 investigation missed. Comprehensive sweep confirmed `settings` is the ONLY additional gap (all other in-scope provider imports are either v4-covered, stdlib, or PyPI). v4.1 adds Step 1b with a shim that mirrors the v4 pattern — `except ModuleNotFoundError as e: if e.name != "settings": raise; import os; FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://localhost:3000")`. Default matches `settings.py:19` exactly so monorepo and dist behavior are identical. Codex resumed impl in second session (threadId `019dee32-aeb4-75e2-94dd-bf5a33accfd2`) — applied Step 1b, re-ran sync + wheel build, completed all four extras' clean-wheel tests, monorepo pytest at parity (434 passed), and committed source `d03a6c05` + dist `a01937d`. **Live monorepo parity test (Option A)**: restarted `risk_module` service to load new code, hit `GET /api/snaptrade/connections` + `POST /api/snaptrade/holdings/refresh` — Redis counters `budget:counter:snaptrade:accounts.list:*` incremented +1 (6→7 monthly + new daily counter), api_call_log row sampled (`accounts.list cost=$0 dry_run=True decision=ok`) — guard side effects fire end-to-end, shim confirmed pure no-op in monorepo. Pushed both repos to GitHub. Published 0.5.0 to PyPI via `scripts/publish_brokerage_connect.sh --use-source-version --yes`. **SHIPPED**.
