# Dynamic Expected Returns Plan

**Status**: DRAFT (v4 — addresses Codex v3 review findings on semantics regression + dropped param + GET test gaps)
**Type**: Architecture fix — eliminates stale data by computing dynamically
**Replaces**: `docs/planning/EXPECTED_RETURNS_AUDIT_PLAN.md` (one-time fix approach)

## v4 Changelog (Codex v3 review findings addressed)

| # | Finding | Resolution |
|---|---------|------------|
| v3 #1 | `ensure_coverage=False` cold-miss returns partial dict — semantic regression. Current code raises `ValidationError` when tickers are missing | **Preserve raise-on-missing semantics.** When `ensure_coverage=False` AND cache misses AND there are unresolved tickers, raise `ValidationError` (matches current code at line 438-440). Cache stays unpoisoned because no write happens before the raise. |
| v3 #2 | `years_lookback` accepted by `ensure_returns_coverage()` but not forwarded to `estimate_historical_returns()` in Step 3 | Thread `years_lookback` through. `get_complete_returns()` accepts an optional `years_lookback` param; `ensure_returns_coverage()` passes its own param down. |
| v3 #3 | GET `/api/expected-returns` route tests miss `0.0` retrieval case + mixed-source transparency case | Add 2 more route tests: (a) DB has `0.0` user_input row → endpoint returns `{ticker: 0.0}` not empty; (b) DB has both `user_input` (Jan) AND `calculated` (Apr) rows for same ticker → endpoint returns the latest by effective_date regardless of source (transparency invariant). |

## v3 Changelog (Codex v2 review findings addressed)

| # | Finding | Resolution |
|---|---------|------------|
| v2 #2 | **Cache poisoning** — Step 3 design unconditionally writes partial results on `ensure_coverage=False` cache miss, poisoning subsequent `ensure_returns_coverage()` calls | **Only cache fully-resolved sets.** When `ensure_coverage=False` and cache misses, do NOT write to cache. When `ensure_coverage=True`, only write after dynamic resolution completes successfully. See revised Step 3. |
| v2 #6 caveat | `_validate_complete_coverage()` removal drops `cash_proxy_tickers` + `temp_generated_tickers` keys; `tests/core/test_cash_semantics.py:212` reads these | Add `cash_proxy_tickers` to the new `final_coverage` dict for backward compat. Drop `temp_generated_tickers` and update `test_cash_semantics.py:212`. |
| v2 #8 | Test plan gaps — GET `/api/expected-returns` route tests in live verification only; missing real consumer-level MC ensure→get integration test | Move GET tests to automated tests section. Add MC integration test that exercises real `ensure_returns_coverage()` → `get_complete_returns(ensure_coverage=False)` sequence. |

---

## v2 Changelog (Codex review findings addressed)

| # | Finding | Resolution |
|---|---------|------------|
| 1 | SQL filter bug — outer `data_source='user_input'` filter without subquery filter returns nothing when newer `calculated` row exists | Filter `data_source='user_input'` in BOTH outer query AND `MAX(effective_date)` subquery |
| 2 | Missed consumers — app.py:3314/3750/3899/4006/4114, mcp_tools/monte_carlo.py:141, mcp_tools/risk.py:607 | Resolution caching strategy (see v2 design) eliminates need for caller surgery — all sites work unchanged. Listed for verification. |
| 3 | `_temp_generated_returns` cleanup includes admin docs/tests | Update tests/core/test_cash_semantics.py:204; admin docs are non-blocking |
| 4 | `ensure_returns_coverage` shape — broader callers read `final_coverage`/`warnings`/`generated`, not just `success` | Preserve full dict shape exactly. Documented in Step 4. |
| 5 | `ensure_coverage=False` semantic change is unsafe — MC silently uses 0 drift | **Do NOT redefine `ensure_coverage=False`.** Keep `_resolved_returns_cache` (renamed `_temp_generated_returns`) so `ensure_returns_coverage()` populates it and `get_complete_returns(ensure_coverage=False)` reads from it. No caller surgery. No semantic change. |
| 6 | Derivatives + per-portfolio proxies — `estimate_historical_returns()` reads global YAML, not user's per-portfolio proxies; `instrument_types` not threaded through | Add `stock_proxies` and `instrument_types` parameters to `estimate_historical_returns()`. Pass user's `factor_proxies` (from `PortfolioManager`) and `instrument_types` (from `PortfolioData`) at the ReturnsService call site. |
| 7 | 60-90s cold latency unacceptable — flows would double-compute after Step 4 | Resolution caching (see #5) prevents double computation. Cold-path is single dynamic-resolution pass per request. Document worst-case but eliminate the duplicate-work source. |
| 8 | Test plan gaps — mixed-source SQL, file-mode override preservation, MC `ensure_coverage=False`, cash-proxy override precedence, instrument_types propagation, GET endpoint under both modes | Test plan rewritten with all listed cases |
| 9 | File-fallback GET breaks if Step 5 returns `{}` from YAML | **Reverse Step 5.** Keep `get_expected_returns_file()` reading from YAML. Instead, EMPTY the existing `expected_returns:` block in `config/portfolio.yaml` as the data fix. Future file-mode users can add their own overrides to YAML. |
| 10 | 0.0 truthiness fix is correct, with intentional behavior change for all-zero override sets | Documented in risk table. No code change. |

---

## 1. Context

Expected returns in `config/portfolio.yaml` and the DB are severely stale. SFM=43.8% (should be 7.5% via XLP), NVDA=74.9% (should be 30.2% via SOXX). The computation pipeline (`ReturnsCalculator.estimate_historical_returns()`) is correct — the problem is values are stored once and never refreshed. `ensure_returns_coverage()` returns early when all tickers have *any* value.

**Old plan** proposed a one-time data fix + staleness guard. **This plan** eliminates the problem structurally: compute dynamically every time, except user-set overrides. Warm cache latency is ~100-150ms for 15 tickers (Parquet-backed), so this is viable.

### Current stored vs pipeline values (confirmed 2026-04-09)

| Ticker | Stored | Pipeline | Delta | Proxy |
|--------|--------|----------|-------|-------|
| SFM | 43.8% | 7.5% | -36.3pp | XLP |
| NVDA | 74.9% | 30.2% | -44.7pp | SOXX |
| RNMBY | 84.8% | 15.5% | -69.3pp | ITA |
| EQT | 29.1% | 3.8% | -25.3pp | XOP |
| IGIC | 29.9% | 11.4% | -18.5pp | KIE |
| KINS | 24.1% | 11.4% | -12.7pp | KIE |
| TKO | 29.5% | 12.3% | -17.2pp | XLC |
| IT | 23.5% | 22.3% | -1.2pp | XLK |
| MSCI | 7.8% | 16.2% | +8.4pp | KCE |
| V | 13.4% | 16.2% | +2.8pp | KCE |
| AAPL | 12.5% | 22.3% | +9.8pp | XLK |
| MSFT | 10.0% | 14.7% | +4.7pp | IGV |
| SLV | 8.9% | 14.9% | +6.0pp | SLV |
| DSU | 1.5% | 8.0% | +6.5pp | DSU |
| STWD | 5.9% | 3.3% | -2.6pp | REM |

At least 7 of 16 values appear to use individual stock CAGR rather than industry ETF CAGR. Root cause unverified (values entered in squash commit `c73b2866`).

---

## 2. Design

**New precedence in `get_complete_returns()`:**
1. **User overrides** — DB rows with `data_source='user_input'` (DB mode) OR YAML `expected_returns` entries (file mode). User intent always wins.
2. **Cash proxy tickers** (SGOV, CUR:*, ERNS.L, IBGE.L) → Treasury rate
3. **Everything else** → compute dynamically via `estimate_historical_returns()`, passing user's per-portfolio `stock_proxies` and `instrument_types`

**Resolution caching (key v2 design)**: ReturnsService keeps a per-instance cache `_temp_generated_returns: Dict[portfolio_name, Dict[ticker, float]]`. The `ensure_returns_coverage()` call populates this cache by calling `get_complete_returns(ensure_coverage=True)` once. Subsequent `get_complete_returns(ensure_coverage=False)` calls read from the cache. This:
- Preserves all existing call sites unchanged (app.py:3314/3750/3899/4006/4114, MC, agent_building_blocks)
- Prevents double computation
- Keeps `ensure_coverage=False` semantics: "use whatever has been resolved already"
- The cache lives only for the lifetime of the ReturnsService instance (per-request, not global)

**What goes away:**
- Reading **stale calculated values** from `expected_returns` table (`data_source != 'user_input'` rows ignored)
- Existing inflated `expected_returns` values in `config/portfolio.yaml` (block emptied; YAML reading code preserved for future overrides)
- `_validate_complete_coverage()` method (replaced by simpler logic in `get_complete_returns`)
- The "stale-present" gap where existing values are never refreshed
- The DB-required guard on max_sharpe/max_return optimization in `mcp_tools/optimization.py` (dynamic computation works in no-DB mode)

**What stays:**
- `get_expected_returns_file()` and the YAML read path (file-mode override mechanism)
- `_temp_generated_returns` (renamed semantically to "resolved returns cache" but kept as the same per-instance dict)
- `ensure_returns_coverage()` interface and full return-dict shape (`success`, `final_coverage`, `coverage_pct`, `generated`, `warnings`, `action_taken`)
- All call site code in app.py, monte_carlo.py, agent_building_blocks.py — unchanged
- DB schema, triggers, `save_expected_returns()`, GET/POST `/api/expected-returns` endpoints

---

## 3. Code Path Analysis

### Current flow
```
config/portfolio.yaml  OR  DB expected_returns table
         │                           │
         v                           v
PortfolioRepository.get_expected_returns_file()  /  .get_expected_returns()
         │                           │
         └──────────┬────────────────┘
                    v
         PortfolioManager.get_expected_returns()
                    │
                    v
         ReturnsService.ensure_returns_coverage()   ← only fills MISSING tickers
                    │
                    v
         ReturnsService.get_complete_returns()      ← merges DB + temp + cash
                    │
                    v
         PortfolioData.expected_returns             ← consumed by optimizer, MC
```

### New flow
```
         DB expected_returns WHERE data_source='user_input'
                    │
                    v
         PortfolioManager.get_user_return_overrides()
                    │
                    v
         ReturnsService.get_complete_returns()
                    │
          ┌─────────┼─────────────────┐
          v         v                 v
     cash proxy   user override   dynamic computation
     (Treasury)   (from DB)       (estimate_historical_returns)
          │         │                 │
          └─────────┼─────────────────┘
                    v
         complete_returns dict → optimizer, MC, etc.
```

### Key files

| File | Role | Lines of interest |
|------|------|-------------------|
| `inputs/returns_calculator.py` | `estimate_historical_returns()` — correct pipeline | 53-208 |
| `inputs/database_client.py` | `get_expected_returns()` — reads ALL from DB | 1640-1683 |
| `inputs/database_client.py` | `save_expected_returns()` — hardcodes `'user_input'` | 1814-1857 |
| `inputs/portfolio_repository.py` | `get_expected_returns_file()` — reads YAML | 236-258 |
| `inputs/portfolio_repository.py` | `get_expected_returns()` — DB passthrough | 85-87 |
| `inputs/portfolio_manager.py` | `get_expected_returns()` — DB with YAML fallback | 542-560 |
| `services/returns_service.py` | `get_complete_returns()` — merge logic, core rewrite target | 356-459 |
| `services/returns_service.py` | `ensure_returns_coverage()` — simplification target | 225-351 |
| `services/returns_service.py` | `_validate_complete_coverage()` — removal target | 552-604 |
| `mcp_tools/optimization.py` | Direct DB read for max_return/max_sharpe | 217-240 |
| `mcp_tools/compare.py` | Direct DB read in `_load_expected_returns()` | 156-165 |

### DB schema (already supports this change)

```sql
CREATE TABLE expected_returns (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker VARCHAR(100) NOT NULL,
    expected_return DECIMAL(8,4) NOT NULL,
    effective_date DATE NOT NULL,
    data_source VARCHAR(50) DEFAULT 'calculated',  -- 'user_input', 'calculated', 'market_data'
    confidence_level DECIMAL(3,2),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(user_id, ticker, effective_date)
);
CREATE INDEX idx_expected_returns_data_source ON expected_returns(data_source);
```

`data_source` column and index already exist. UPDATE/DELETE triggers prevent row modification (insert-only versioning).

### Known bugs to fix as part of this work

1. **0.0 truthiness bug** (`database_client.py:1677`): `if row['expected_return']:` drops legitimate 0.0 values. Fix: `if row['expected_return'] is not None:`
2. **`ON CONFLICT DO NOTHING`** (`database_client.py:1848`): Same-day re-saves silently dropped. Note: UPDATE trigger prevents UPSERT, so this is an accepted limitation (one save per ticker per day). Not blocking.

---

## 4. Implementation Steps

### Step 1: DB layer — `get_user_return_overrides()` + 0.0 fix

**File**: `inputs/database_client.py`

**1a.** Add `get_user_return_overrides()` after line 1683. Filter `data_source='user_input'` in BOTH the outer query AND the `MAX(effective_date)` subquery (Codex finding #1). ~30 lines:

```python
@log_errors("high")
@log_operation("user_return_overrides_retrieval")
@log_timing(1.0)
@handle_database_error
def get_user_return_overrides(self, user_id: int, portfolio_name: str) -> Dict[str, float]:
    """Get user-set expected return overrides only (data_source='user_input')."""
    with self.get_connection() as conn:
        cursor = conn.cursor()
        try:
            # Get portfolio tickers
            query1 = """
                SELECT DISTINCT p.ticker
                FROM positions p
                JOIN portfolios port ON p.portfolio_id = port.id
                WHERE port.user_id = %s AND port.name = %s
            """
            cursor = self._execute_with_timing(cursor, query1, (user_id, portfolio_name),
                                               context="get_user_return_overrides_tickers")
            portfolio_tickers = [row['ticker'] for row in cursor.fetchall()]
            if not portfolio_tickers:
                return {}

            # Latest user_input override per ticker — filter applied in BOTH queries
            query2 = """
                SELECT er.ticker, er.expected_return
                FROM expected_returns er
                WHERE er.user_id = %s
                AND er.ticker = ANY(%s)
                AND er.data_source = 'user_input'
                AND er.effective_date = (
                    SELECT MAX(effective_date)
                    FROM expected_returns
                    WHERE user_id = er.user_id
                    AND ticker = er.ticker
                    AND data_source = 'user_input'
                )
            """
            cursor = self._execute_with_timing(cursor, query2, (user_id, portfolio_tickers),
                                               context="get_user_return_overrides_values")

            returns = {}
            for row in cursor.fetchall():
                if row['expected_return'] is not None:  # 0.0 fix
                    returns[row['ticker']] = float(row['expected_return'])
            return returns
        except Exception as e:
            raise DatabaseError(f"Failed to get user return overrides: {portfolio_name}", original_error=e)
```

**1b.** Fix 0.0 truthiness bug in existing `get_expected_returns()` at line 1677:
```python
# Before:
if row['expected_return']:
# After:
if row['expected_return'] is not None:
```

Leave existing `get_expected_returns()` query structure unchanged — still used by GET API endpoint for transparency (returns ALL stored values regardless of data_source).

### Step 2: Thread through Repository + Manager

**File**: `inputs/portfolio_repository.py` — add `get_user_return_overrides()` passthrough after line 87:
```python
def get_user_return_overrides(self, user_id: int, portfolio_name: str) -> Dict[str, float]:
    with self._db_client() as db_client:
        return db_client.get_user_return_overrides(user_id, portfolio_name)
```

**File**: `inputs/portfolio_manager.py` — add `get_user_return_overrides()` after line 560. Same pattern as existing `get_expected_returns()` (DB-first with file fallback) BUT in file mode falls back to reading the YAML `expected_returns:` block (file-mode override mechanism — Codex finding #9):

```python
def get_user_return_overrides(self, portfolio_name: str) -> Dict[str, float]:
    """Get only user-set expected return overrides.

    DB mode: rows with data_source='user_input' only.
    File mode: contents of YAML 'expected_returns:' block (treated as user-set).
    """
    try:
        if self.use_database and self.internal_user_id:
            try:
                scope = resolve_portfolio_scope(self.internal_user_id, portfolio_name)
                return self.repository.get_user_return_overrides(
                    self.internal_user_id,
                    scope.expected_returns_portfolio_name,
                )
            except Exception as exc:
                portfolio_logger.warning("⚠️ User overrides DB retrieval failed: %s", exc)
                if self._should_fallback_to_file():
                    return self.repository.get_expected_returns_file(portfolio_name)
                return {}
        return self.repository.get_expected_returns_file(portfolio_name)
    except Exception as exc:
        portfolio_logger.error("❌ Failed to get user return overrides: %s", exc)
        return {}
```

### Step 3: Rewrite `get_complete_returns()` (core change)

**File**: `services/returns_service.py` — replace lines 385-455

New logic with **safe** resolution caching (v3 cache fix) and **preserved raise-on-missing semantics** (v4 fix):

```python
def get_complete_returns(self, portfolio_name, ensure_coverage=True, years_lookback=None):
    # Cache lookup: only consult cache, never poison it.
    # Cache contains FULLY RESOLVED sets only (populated by ensure_coverage=True paths).
    cache = getattr(self, '_temp_generated_returns', {})
    cached = cache.get(portfolio_name)
    if cached is not None:
        return cached

    portfolio_tickers = self.portfolio_manager.get_portfolio_tickers(portfolio_name)
    user_overrides = self.portfolio_manager.get_user_return_overrides(portfolio_name)

    # Bucket tickers
    complete_returns = {}
    tickers_to_compute = []
    cash_proxies_handled = []
    overrides_used = []

    for ticker in portfolio_tickers:
        if ticker in user_overrides and user_overrides[ticker] is not None:
            # Priority 1: user override wins (even for cash proxies)
            complete_returns[ticker] = user_overrides[ticker]
            overrides_used.append(ticker)
        elif self._is_cash_proxy(ticker):
            # Priority 2: cash proxy → Treasury rate (preserve existing logic from lines 412-434)
            ...  # (CUR:USD → Treasury, CUR:non-USD → 0.0, fallback to cash_proxy_fallback_return)
            cash_proxies_handled.append(ticker)
        else:
            # Priority 3: dynamic computation candidate
            tickers_to_compute.append(ticker)

    if ensure_coverage and tickers_to_compute:
        # Pull per-portfolio context for the calculator
        portfolio_data = self.portfolio_manager.load_portfolio_data(portfolio_name)
        stock_proxies = getattr(portfolio_data, 'stock_factor_proxies', None)
        instrument_types = getattr(portfolio_data, 'instrument_types', None)

        dynamic_returns = self.returns_calculator.estimate_historical_returns(
            tickers_to_compute,
            years_lookback=years_lookback,       # v4 fix: forward param (Codex v3 #2)
            stock_proxies=stock_proxies,         # Per-portfolio proxies (v2 #6)
            instrument_types=instrument_types,   # Derivatives routing (v2 #6)
        )
        complete_returns.update(dynamic_returns)

        # Cache only when fully resolved (ensure_coverage=True path completed dynamic resolution)
        # Determine "fully resolved" = every portfolio_ticker is in complete_returns
        if all(t in complete_returns for t in portfolio_tickers):
            self._temp_generated_returns = cache
            self._temp_generated_returns[portfolio_name] = complete_returns
    elif ensure_coverage and not tickers_to_compute:
        # No dynamic computation needed (all overrides + cash). Still fully resolved → cache it.
        self._temp_generated_returns = cache
        self._temp_generated_returns[portfolio_name] = complete_returns
    elif not ensure_coverage and tickers_to_compute:
        # ensure_coverage=False AND cache missed AND unresolved tickers exist.
        # PRESERVE current semantic: raise ValidationError (matches existing line 438-440).
        # No cache write — cache stays clean.
        # v4 fix (Codex v3 #1): no behavioral regression
        raise ValidationError(
            f"Expected returns missing for tickers: {tickers_to_compute}"
        )

    portfolio_logger.info(
        "✅ Complete returns: %d user overrides + %d dynamically computed + %d cash proxies",
        len(overrides_used), len(tickers_to_compute) if ensure_coverage else 0, len(cash_proxies_handled),
    )
    return complete_returns
```

**Key changes from v3 (semantic regression fix):**
- `ensure_coverage=False` cold-miss now RAISES `ValidationError` (matches current code at line 438-440)
- The cache stays clean either way: raise happens BEFORE any cache write
- `years_lookback` parameter added to `get_complete_returns()` and forwarded to `estimate_historical_returns()` (v4 fix for v3 #2)

**Cache poisoning protection (v3 design):**
- Cache writes ONLY happen when the result is fully resolved
- `ensure_coverage=False` raises (or returns from cache) — never writes partial state

**Other key behaviors:**
- User-override-first precedence (overrides win over cash proxies)
- `stock_proxies` and `instrument_types` threaded into calculator
- `_temp_generated_returns` is `Dict[portfolio_name, Dict[ticker, return]]` (per-portfolio scoping)
- The cache lifetime is the `ReturnsService` instance — instances are constructed fresh per request

**Remove**: `_validate_complete_coverage()` method (lines 552-604) — no longer needed. Note: this drops the `temp_generated_tickers` key from coverage dicts. `cash_proxy_tickers` is preserved (see Step 4).

**Update `ReturnsPortfolioAccessor` Protocol** (lines 56-64): Add the new methods to reflect the runtime contract:
```python
@runtime_checkable
class ReturnsPortfolioAccessor(Protocol):
    """Minimal contract ReturnsService needs from portfolio dependency."""

    def get_portfolio_tickers(self, portfolio_name: str) -> List[str]:
        ...

    def get_expected_returns(self, portfolio_name: str) -> Dict[str, float]:
        ...

    def get_user_return_overrides(self, portfolio_name: str) -> Dict[str, float]:  # NEW (v4)
        ...

    def load_portfolio_data(self, portfolio_name: str) -> "PortfolioData":  # NEW (v4)
        ...
```
This keeps the Protocol honest with the new code paths that read `PortfolioData.stock_factor_proxies` and `get_user_return_overrides()`.

### Step 4: Simplify `ensure_returns_coverage()`

**File**: `services/returns_service.py` — simplify lines 225-351

New logic: thin wrapper that calls `get_complete_returns()` and reshapes to legacy dict. Preserves ALL keys from current return shape (Codex finding #4): `success`, `initial_coverage`, `final_coverage` (with `coverage_pct`, `missing_tickers`, etc.), `generated`, `generated_returns`, `warnings`, `action_taken`.

```python
def ensure_returns_coverage(self, portfolio_name, years_lookback=None, auto_generate=True):
    try:
        # Initial coverage = what's available BEFORE dynamic computation
        # (overrides + cash proxies). Used by callers for diagnostics.
        initial_coverage = self.validate_returns_coverage(portfolio_name)

        if not auto_generate:
            return {
                "success": initial_coverage["complete"],
                "initial_coverage": initial_coverage,
                "final_coverage": initial_coverage,
                "generated": [],
                "generated_returns": {},
                "warnings": ([] if initial_coverage["complete"]
                            else [f"Coverage incomplete ({initial_coverage['coverage_pct']:.1%}) but auto_generate=False"]),
                "action_taken": "warning_only" if not initial_coverage["complete"] else "no_action_needed",
            }

        # Single dynamic resolution pass — populates _temp_generated_returns cache
        # v4 fix (Codex v3 #2): forward years_lookback to dynamic computation
        complete_returns = self.get_complete_returns(
            portfolio_name,
            ensure_coverage=True,
            years_lookback=years_lookback,
        )
        portfolio_tickers = self.portfolio_manager.get_portfolio_tickers(portfolio_name)
        missing = [t for t in portfolio_tickers if t not in complete_returns]

        # Final coverage = after dynamic resolution
        # Preserve cash_proxy_tickers key for backward compat with test_cash_semantics.py
        cash_proxy_tickers = [t for t in complete_returns.keys() if self._is_cash_proxy(t)]
        final_coverage = {
            "complete": len(missing) == 0,
            "coverage_pct": (len(portfolio_tickers) - len(missing)) / max(len(portfolio_tickers), 1),
            "missing_tickers": missing,
            "available_tickers": list(complete_returns.keys()),
            "cash_proxy_tickers": cash_proxy_tickers,  # backward compat (v2 #6 caveat)
            "total_tickers": len(portfolio_tickers),
            "missing_count": len(missing),
            "portfolio_name": portfolio_name,
        }
        # 'generated' = tickers that needed dynamic computation (initial missing - final missing)
        initial_missing = set(initial_coverage.get("missing_tickers", []))
        generated = [t for t in initial_missing if t not in missing]

        return {
            "success": final_coverage["complete"],
            "initial_coverage": initial_coverage,
            "final_coverage": final_coverage,
            "generated": generated,
            "generated_returns": {t: complete_returns[t] for t in generated},
            "warnings": [] if final_coverage["complete"] else [f"Still missing: {missing}"],
            "action_taken": "auto_generated" if generated else "no_action_needed",
        }
    except Exception as e:
        portfolio_logger.error(f"Ensure returns coverage failed for {portfolio_name}: {e}")
        raise ValidationError(f"Returns coverage operation failed: {e}") from e
```

**Update `validate_returns_coverage()` (lines 139-220)**: Currently treats any ticker in `get_expected_returns()` as covered. Update to use `get_user_return_overrides()` + cash proxy detection so "missing" reflects "needs dynamic computation."

### Step 5: Calculator — accept `stock_proxies` parameter

**File**: `inputs/returns_calculator.py` — modify `estimate_historical_returns()` (lines 53-208)

Add a `stock_proxies` parameter (Codex finding #6). When provided, use it instead of reading global `config/portfolio.yaml`:

```python
def estimate_historical_returns(
    self,
    tickers: List[str],
    years_lookback: int = None,
    instrument_types: Dict[str, str] | None = None,
    stock_proxies: Dict[str, Dict[str, Any]] | None = None,  # NEW
) -> Dict[str, float]:
    ...
    # Existing global YAML read becomes a fallback when stock_proxies not passed
    if stock_proxies is None:
        try:
            with open(self.portfolio_path, "r") as f:
                portfolio_config = yaml.safe_load(f) or {}
            stock_proxies = portfolio_config.get("stock_factor_proxies", {})
            ...
        except Exception:
            stock_proxies = {}
    ...
```

The `instrument_types` parameter already exists (line 57). Just ensure callers pass it.

### Step 6: Empty stale YAML data + preserve override mechanism

**File**: `config/portfolio.yaml` — DELETE the `expected_returns:` block (lines 32-48). The 16 stale values are removed entirely.

**File**: `inputs/portfolio_repository.py` — DO NOT modify `get_expected_returns_file()` (lines 236-258). The YAML read code stays so file-mode users can add their own override entries to YAML in the future. With the block emptied, it returns `{}` until someone explicitly adds entries.

**Reversal of v1 Step 5**: v1 said "make `get_expected_returns_file()` return `{}`". v2 says "leave the code alone, just empty the data." This preserves the file-mode override mechanism (Codex finding #9).

### Step 7: Route compare through ReturnsService

**File**: `mcp_tools/compare.py` — replace `_load_expected_returns()` (lines 156-165)

```python
def _load_expected_returns(user_id: int, portfolio_name: str) -> dict:
    from inputs.portfolio_manager import PortfolioManager
    from services.returns_service import ReturnsService
    pm = PortfolioManager(use_database=is_db_available() and bool(user_id), user_id=user_id)
    returns_service = ReturnsService(portfolio_manager=pm)
    return returns_service.get_complete_returns(portfolio_name) or {}
```

### Step 8: Route optimization through ReturnsService

**File**: `mcp_tools/optimization.py` — replace lines 217-240

Remove the `is_db_available()` guard. max_sharpe/max_return now work in no-DB mode via dynamic computation:
```python
if optimization_type in ("max_return", "max_sharpe", "target_volatility"):
    from inputs.portfolio_manager import PortfolioManager
    from services.returns_service import ReturnsService
    pm = PortfolioManager(use_database=is_db_available() and bool(user_id), user_id=user_id)
    returns_service = ReturnsService(portfolio_manager=pm)
    expected_returns = returns_service.get_complete_returns(scope.expected_returns_portfolio_name)
    if not expected_returns:
        return {"status": "error", "error": "No expected returns available."}
    portfolio_data.expected_returns = expected_returns
```

### Step 9: Verify untouched call sites

These sites call `ensure_returns_coverage()` then `get_complete_returns()`. Two patterns exist:

**Pattern A**: `ensure_returns_coverage()` → `get_complete_returns(ensure_coverage=False)` (explicit skip-compute). Relies on the resolution cache populated by step 1. Raises `ValidationError` if cache empty.

| File | Ensure call | Get call |
|------|-------------|----------|
| `app.py` | 3314 | 3320 (`ensure_coverage=False`) |
| `mcp_tools/monte_carlo.py` | 141 | 147 (`ensure_coverage=False`) |
| `services/agent_building_blocks.py` | 534 | 540 (`ensure_coverage=False`) |

**Pattern B**: `ensure_returns_coverage()` → `get_complete_returns(...)` with default `ensure_coverage=True`. Cache is hit on second call (already populated by first), avoiding double-compute.

| File | Ensure call | Get call |
|------|-------------|----------|
| `app.py` | 3750 | 3757 (default) |
| `app.py` | 3899 | 3921 (default) |
| `app.py` | 4006 | 4028 (default) |
| `app.py` | 4114 | 4136 (default) |
| `app.py` | 3650 | 3672 (default) |

Both patterns work unchanged under the Step 3 cache design. No caller surgery required. Codex verified these sites in v4 review.

`mcp_tools/risk.py:607` is **not** a consumer — comment says "Expected returns NOT loaded — not needed for risk analysis/scoring". Verified.

### Step 10: Test updates

See Section 8 for the full test plan including all gaps Codex flagged.

---

## 5. Files Modified

| File | Change | Lines |
|------|--------|-------|
| `inputs/database_client.py` | New `get_user_return_overrides()` (filter in BOTH outer + subquery) + 0.0 fix in existing method | ~35 |
| `inputs/portfolio_repository.py` | New passthrough method | ~5 |
| `inputs/portfolio_manager.py` | New `get_user_return_overrides()` (DB user_input + file-mode YAML fallback) | ~20 |
| `inputs/returns_calculator.py` | Add `stock_proxies` parameter to `estimate_historical_returns()` | ~10 |
| `services/returns_service.py` | Rewrite `get_complete_returns()` with resolution caching, simplify `ensure_returns_coverage()`, update `validate_returns_coverage()`, remove `_validate_complete_coverage()`. Keep `_temp_generated_returns` (rename semantics, change to per-portfolio scoping). | ~120 net |
| `mcp_tools/optimization.py` | Route through ReturnsService, drop is_db_available guard | ~15 |
| `mcp_tools/compare.py` | Route through ReturnsService | ~10 |
| `config/portfolio.yaml` | Delete `expected_returns:` block (16 stale values) | -17 |
| `tests/core/test_cash_semantics.py` | Update `_temp_generated_returns` reference at line 204 | ~3 |

**No changes** to: `app.py` (5 callsites), `mcp_tools/monte_carlo.py:141`, `services/agent_building_blocks.py:534`, `mcp_tools/risk.py:607`, DB schema, GET/POST `/api/expected-returns` endpoints, `save_expected_returns()`.

## 6. What NOT to Change

- `save_expected_returns()` — still saves with `data_source='user_input'`, correct for user overrides
- `get_expected_returns()` in DB client (existing method) — keep for GET API endpoint transparency (returns ALL stored values regardless of data_source)
- DB triggers (UPDATE/DELETE prevention) — insert-only model is correct
- `POST /api/expected-returns` endpoint — still works, saves user overrides
- `get_expected_returns_file()` in repository — code unchanged; only the YAML data is cleaned
- The 4 YAML-data file mode users (none currently in production, but mechanism preserved)
- `_temp_generated_returns` attribute name — keep, just change scoping to per-portfolio
- App-level callsite code (5 sites in app.py + monte_carlo.py + agent_building_blocks.py) — preserved by resolution caching design

## 7. Existing Utilities to Reuse

- `ReturnsCalculator.estimate_historical_returns()` at `inputs/returns_calculator.py:53-208`
- `_is_cash_proxy()` at `services/returns_service.py:530-550`
- `_get_current_treasury_rate()` in ReturnsService
- `resolve_portfolio_scope()` at `inputs/portfolio_manager.py`
- `is_db_available()` at `core/db_utils.py`

---

## 8. Test Plan

### New tests (~26, addressing all Codex v1 #8 + v2 #2/#8 + v3 #1/#3 gaps)

**Core resolution logic (~6)**
- `test_get_complete_returns_computes_dynamically` — no overrides, all tickers get dynamic values
- `test_get_complete_returns_user_override_wins` — DB `user_input` row beats dynamic
- `test_get_complete_returns_user_override_beats_cash_proxy` — explicit SGOV=0.05 override beats Treasury rate
- `test_get_complete_returns_cash_proxy_treasury_default` — SGOV with no override gets Treasury rate
- `test_get_complete_returns_mixed_sources` — overrides + cash + dynamic in same call
- `test_get_complete_returns_passes_per_portfolio_proxies` — verify `stock_proxies` from PortfolioData reaches calculator (not global YAML)

**SQL filter correctness (~3, Codex #1)**
- `test_get_user_return_overrides_filters_user_input_only` — DB has `user_input` and `calculated` rows for same ticker, only `user_input` returned
- `test_get_user_return_overrides_picks_latest_user_input_when_calculated_is_newer` — `user_input` from Jan, `calculated` from Apr → returns Jan value (the v1 SQL bug)
- `test_get_user_return_overrides_zero_value` — 0.0 override preserved (not dropped by truthiness)

**Resolution caching (~6, Codex v1 #5/#7 + v2 #2 cache poisoning + v3 #1 raise semantic)**
- `test_ensure_coverage_then_get_complete_no_double_compute` — patch `estimate_historical_returns`, assert called exactly once across the two-call sequence
- `test_get_complete_ensure_coverage_false_uses_cache` — pre-populate cache via `ensure_returns_coverage()`, then `ensure_coverage=False` returns cached set
- `test_get_complete_ensure_coverage_false_cold_raises` — call `get_complete_returns(ensure_coverage=False)` cold (no cache, no overrides) — must raise `ValidationError` matching current behavior at returns_service.py:438. v4 fix for v3 #1 semantic regression.
- `test_get_complete_ensure_coverage_false_raise_does_not_poison` — call `get_complete_returns(ensure_coverage=False)` cold (raises), catch the exception, then call `ensure_returns_coverage()` on same instance — verify it DOES dynamic computation (raise path didn't poison cache)
- `test_cache_only_writes_fully_resolved_sets` — verify cache is empty when no portfolio_tickers can be resolved without dynamic compute, populated only after `ensure_coverage=True` completes
- `test_cache_per_portfolio_isolation` — `ensure_returns_coverage("portfolio_a")` does not affect `get_complete_returns("portfolio_b")`
- `test_ensure_coverage_forwards_years_lookback` — call `ensure_returns_coverage(years_lookback=5)`, patch `estimate_historical_returns`, assert it received `years_lookback=5` (v4 fix for v3 #2)

**File mode + override preservation (~2, Codex #9)**
- `test_file_mode_yaml_expected_returns_treated_as_overrides` — file mode with `expected_returns: {SFM: 0.10}` in YAML → SFM uses 0.10 (override path), other tickers dynamic
- `test_file_mode_empty_yaml_falls_through_to_dynamic` — YAML has no `expected_returns:` block → all tickers dynamic computation, no errors

**Derivatives / instrument_types (~2, Codex #6)**
- `test_get_complete_returns_passes_instrument_types` — futures ticker hits `should_skip_profile_lookup` path → fallback_return (6%), not own-CAGR
- `test_estimate_historical_returns_accepts_stock_proxies_param` — calling calculator directly with `stock_proxies={SFM: {industry: XLP}}` uses XLP regardless of global YAML

**Consumer routing (~2)**
- `test_optimization_max_sharpe_works_no_db` — max_sharpe in no-DB mode succeeds via dynamic computation
- `test_compare_uses_dynamic_returns` — compare scenarios get dynamic values

**GET /api/expected-returns route tests (~5, Codex v2 #8 + v3 #3)**
- `test_get_expected_returns_endpoint_db_user_input_only` — DB has user_input rows for SFM=0.10 and AAPL=0.12 — endpoint returns both with effective_dates
- `test_get_expected_returns_endpoint_db_no_user_input` — DB has only legacy `data_source='calculated'` rows — endpoint returns those (transparency invariant)
- `test_get_expected_returns_endpoint_file_mode_empty` — file mode with empty YAML expected_returns block — endpoint returns `{}` with empty effective_dates, no error
- `test_get_expected_returns_endpoint_zero_value` — DB has user_input row with `expected_return=0.0` — endpoint returns `{ticker: 0.0}` (verifies the v3 truthiness fix at line 1677). Without the fix, this would return empty dict.
- `test_get_expected_returns_endpoint_mixed_source_latest_wins` — DB has SFM `user_input=0.10` (Jan) AND SFM `calculated=0.075` (Apr). GET endpoint returns 0.075 (latest by effective_date, regardless of data_source). This verifies the existing `get_expected_returns()` method retains transparency semantics — it does NOT use `get_user_return_overrides()`. Also assert `effective_dates["SFM"] == "2026-04-XX"` (the latest date).

**Monte Carlo integration test (~1, Codex v2 #8)**
- `test_monte_carlo_industry_etf_drift_real_ensure_get_sequence` — call `mcp_tools/monte_carlo.py:run_monte_carlo` with `drift_model="industry_etf"`. Patch `estimate_historical_returns` to return known values. Verify (a) it's called exactly once during the sequence, (b) MC engine receives the resolved expected_returns dict, (c) drift values match overrides + dynamic + cash priority order.

### Existing tests to update
- `tests/core/test_cash_semantics.py:199-214` — calls `_validate_complete_coverage()` which is removed. Rewrite to call `ensure_returns_coverage()` and read `final_coverage["cash_proxy_tickers"]`. Drop the `temp_generated_tickers` assertion (key removed in v3). Per-ticker `_temp_generated_returns = {"CUR:GBP": 0.12}` shape changes to per-portfolio `{"CURRENT_PORTFOLIO": {"CUR:GBP": 0.12}}`.
- `tests/core/test_cash_semantics.py:15` — `_PortfolioManagerStub` has `get_portfolio_tickers` and `get_expected_returns` but NOT `get_user_return_overrides`. Add a stub method returning `{}` (or `self._expected_returns` if that's the intent) since `validate_returns_coverage()` will switch to using overrides instead of `get_expected_returns()` after Step 4.
- `tests/mcp_tools/test_monte_carlo_mcp.py:341` — likely mocks `ensure_returns_coverage`. Verify shape compat with new dict.
- `tests/services/test_agent_building_blocks.py:555` — same.
- `tests/mcp_tools/test_optimization_new_types.py` — direct DB read mock no longer relevant; mock ReturnsService.
- `tests/mcp_tools/test_optimization_risk_context.py` — same.
- `tests/mcp_tools/test_compare_scenarios.py` — `_load_expected_returns` now goes through ReturnsService.

### Live verification (smoke tests, post-deploy)
- `POST /api/expected-returns` for SFM=0.08 → next `run_optimization` call uses 0.08 for SFM, dynamic for others
- `run_optimization(optimization_type="max_sharpe")` — confirm it produces more balanced results (less NVDA/RNMBY skew vs old stale-data baseline)
- `run_monte_carlo(drift_model="industry_etf")` — confirm drift values match fresh pipeline computation

---

## 9. Verification

1. Run `estimate_historical_returns()` for all portfolio tickers — confirm values match investigation table above
2. Run existing test suite — confirm no regressions
3. Live test: call `run_optimization(optimization_type="max_sharpe")` — confirm it uses dynamic values and produces more balanced results (less NVDA/RNMBY skew)
4. Live test: call `run_monte_carlo(drift_model="industry_etf")` — confirm drift uses fresh values
5. Set a manual override via `POST /api/expected-returns` for one ticker — confirm it takes precedence in next optimization

---

## 10. Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Cold cache latency (first run ~60-90s for 15 tickers) | Medium | Parquet cache persists across sessions. Resolution caching (per-instance) eliminates double-compute within a single request. Only affects first-ever run or cache expiry. Acceptable for optimization/MC paths which already have multi-second baseline latency. |
| Dynamic values change between runs as market moves | Expected | This is correct behavior — returns should reflect current data, not stale snapshots. |
| Tests that hardcode expected return values | Low | Update test fixtures to mock at ReturnsService level. |
| max_sharpe / max_return results will change (less NVDA/RNMBY skew) | Expected | Whole point of the fix. |
| All-zero override set fails optimizer with explicit error instead of silent fallback | Low (intentional, Codex #10) | The 0.0 truthiness fix means a user setting all returns to 0.0 now reaches the optimizer, which can't find positive max-return weights. This was previously masked by the bug. Document in error message. |
| ON CONFLICT DO NOTHING same-day limitation | Low | DB trigger prevents UPDATE. Accepted: one user override per ticker per day. Not a practical limitation. |
| Resolution cache stale across `ReturnsService` instance lifetime | Low | Cache is per-instance, instances are created fresh per request. No cross-request leakage. Multiple `get_complete_returns()` calls within one request return consistent values. |
| `validate_returns_coverage()` semantic shift — "missing" now means "needs dynamic computation" instead of "absent from DB" | Low | Update method to compute coverage from `get_user_return_overrides()` + cash proxy detection. Tests cover this. |
| Per-portfolio proxy fix uncovers stocks that previously fell back to global YAML proxy | Low/Medium | Some tickers may now use a different (more correct) proxy than before. Verified via live test that portfolio-tier proxies match expectations. |
