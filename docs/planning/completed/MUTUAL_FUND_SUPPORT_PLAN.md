# Mutual Fund Support — Gap Remediation Plan

**Status:** READY TO EXECUTE | **Date:** 2026-03-12
**Context:** E2E verification (1C.3) passed — mutual funds work through pricing, risk, and performance pipelines. This plan addresses the gaps found during verification.
**Codex review:** R1-R9 FAIL (scope drift, wrong names, Grade.NA complexity). R10 = clean rewrite (no Grade.NA). R10-R11 minor fixes. R12 FAIL (CEF with security_type="mutual_fund" falls through to "mutual" keyword). R13: added snaptrade_code=="cef" early return before keyword check.
**Publish plan ref:** 1C.3b

---

## Verification Results (for context)

| Area | Result |
|------|--------|
| FMP pricing (VFIAX, FXAIX, SWPPX, VBTLX) | PASS — isFund=true, full history |
| SecurityTypeService classification | PASS — all → "fund" |
| Crash scenario (40%) | PASS — correctly applied in concentration risk |
| analyze_stock() | PASS — sensible vol/beta/R² |
| build_portfolio_view() | PASS — returns/correlations/vol |
| get_risk_analysis / get_risk_score / get_performance | PASS — no crashes |
| IBKR position normalizer | PASS — maps "mutual funds" → MUTUAL_FUND |
| Schwab position normalizer | GAP — does not exist |
| InstrumentType for trading analysis | GAP — silently coerced to "equity" |
| Factor proxy mappings | GAP — empty for fund-only portfolios |

---

## Gap 1: InstrumentType Silent Coercion + Pricing Chain

### Problem
`coerce_instrument_type("mutual_fund")` silently returns `"equity"` because `"mutual_fund"` is not in `_VALID_INSTRUMENT_TYPES`. This means:
- Mutual fund identity is lost in the trading analysis pipeline
- Timing analysis (exit timing vs. price range) is computed but meaningless for open-ended mutual funds (NAV-only, end-of-day settlement)

### Design Decisions

**D1: Keep FIFO and win_scores for mutual funds.** FIFO lot matching IS valid — you buy/sell shares at NAV, cost basis tracking matters for taxes. Win scores (P&L% relative to holding period) are also valid — you made/lost X% over Y days.

**D2: Skip timing analysis only for open-ended mutual funds.** `analyze_timing()` compares exit prices against post-exit price ranges, which requires intraday price discovery. CEFs (closed-end funds) trade on exchanges — timing IS meaningful for CEFs. Only `"mutual_fund"` (OEF) skips timing; CEFs stay as `"equity"`.

**D3: `FMPProvider.can_price()` must include `"mutual_fund"`.** Without this, mutual funds hit the no-price path in `core/realized_performance/engine.py:1218`.

### Step 1a: Add `"mutual_fund"` to InstrumentType (10 min)

TWO files must stay in sync:

**File: `trading_analysis/instrument_meta.py`**
```python
InstrumentType = Literal["equity", "option", "futures", "fx", "fx_artifact", "bond", "income", "mutual_fund", "unknown"]

_VALID_INSTRUMENT_TYPES = {
    "equity", "option", "futures", "fx", "fx_artifact", "bond", "income", "mutual_fund", "unknown",
}
```

**File: `ibkr/_types.py`** (vendored copy)
```python
InstrumentType = Literal["equity", "option", "futures", "fx", "fx_artifact", "bond", "income", "mutual_fund", "unknown"]

_VALID_INSTRUMENT_TYPES = {
    "equity", "option", "futures", "fx", "fx_artifact", "bond", "income", "mutual_fund", "unknown",
}
```

**File: `trading_analysis/instrument_meta.py` — segment map:**
```python
SEGMENT_INSTRUMENT_TYPES: Dict[str, Set[str]] = {
    "equities": {"equity", "mutual_fund"},  # mutual funds in equities segment
    ...
}
```

**Run full test suite after this step before proceeding.**

### Step 1b: Fix pricing chain (5 min)

**File: `providers/fmp_price.py:37-40`**
```python
def can_price(self, instrument_type: str) -> bool:
    return instrument_type in {"equity", "futures", "mutual_fund"}
```

FMP already prices mutual funds correctly (verified: VFIAX/FXAIX/SWPPX/VBTLX all return daily/monthly prices). This just adds the routing so `ProviderRegistry.get_price_chain("mutual_fund")` (see `providers/registry.py:116`) returns FMP.

No changes to `IBKRPriceProvider.can_price()` (`providers/ibkr_price.py:47`) or `OptionBSPriceProvider.can_price()` — they don't handle mutual funds.

### Step 1c: Update normalizers to preserve `"mutual_fund"` identity (20 min)

Five sites that currently coerce funds → equity:

**1. `providers/normalizers/schwab.py`** (line 105): `_instrument_type_for()` maps `MUTUAL_FUND → "mutual_fund"` then calls `coerce_instrument_type()`. After Step 1a, coercion passes through as-is. **No code change needed** — just verify.

**2. `providers/normalizers/snaptrade.py`** (lines 43-44):
```python
# BEFORE
"oef": "equity",   # Open-ended fund
"cef": "equity",   # Closed-ended fund

# AFTER
"oef": "mutual_fund",  # Open-ended fund → skip timing analysis
"cef": "equity",        # Closed-end fund → trades on exchange, timing IS meaningful
```

**Also: `providers/snaptrade_loader.py`** (line 804): The holdings loader has a SEPARATE mapping comment that says `oef/cef → "mutual_fund"` and stores `our_security_type` at line 984. This is the `security_type` field (used by SecurityTypeService for risk scoring), NOT `instrument_type` (used by trading analysis). The `security_type: "mutual_fund"` for both oef and cef is CORRECT for risk scoring (both get fund_crash=40%). The `instrument_type` distinction (oef→"mutual_fund", cef→"equity") is what controls timing analysis. These are separate classification systems — no conflict.

**3. `providers/normalizers/plaid.py`** (~line 70-100): No explicit mutual fund path. Add before the default `return "equity"`:
```python
if security_type in {"mutual fund", "fund", "mutual_fund"}:
    return "mutual_fund"
```

**4. `providers/normalizers/ibkr_statement.py`** (line 99/131): Has `asset_category` available. Add mutual fund check:
```python
is_fund = asset_category.lower() in {"mutual funds", "mutual fund"}
...
default="mutual_fund" if is_fund else ("option" if is_option else ("futures" if is_futures else "equity")),
```

**5. `core/realized_performance/_helpers.py`** (~line 124-160): `_infer_position_instrument_type()` — add mutual fund checks. The existing function checks `snaptrade_code` at lines 136-144 (for options, futures, bonds, cash) and `joined` type strings at lines 146-158 (for options, futures, bonds, cash). Add OEF to the existing `snaptrade_code` block and MF keywords to the `joined` block.

**Important**: plain substring `"fund"` is too broad — it would match "closed-end fund" which per D2 should stay `"equity"`. Use narrower matching:
```python
# Add to existing snaptrade_code block (after line 144, before type_tokens):
if snaptrade_code == "oef":
    return "mutual_fund"
if snaptrade_code == "cef":
    return "equity"  # CEFs trade on exchanges — must NOT fall through to "mutual" keyword

# Add to existing joined checks (after line 158, before default return "equity" at line 160):
# IMPORTANT: SnapTrade stores security_type="mutual_fund" for BOTH oef AND cef.
# Since "joined" includes security_type, "mutual" in joined would match CEFs too.
# The snaptrade_code="cef" early return above prevents this. For non-SnapTrade positions
# (no snaptrade_code), the keyword check is safe because only OEF-like strings contain "mutual".
if "mutual" in joined:  # "mutual fund", "mutual_fund"
    return "mutual_fund"
if "open" in joined and "fund" in joined:  # "open-ended fund", "open end fund"
    return "mutual_fund"
# Do NOT match bare "fund" — catches "closed-end fund" (CEFs stay as equity)
```

Note: The `UNKNOWN` short-circuit at line 131-132 and `fx_artifact` check at line 133-134 come BEFORE these insertion points. This is correct — UNKNOWN symbols should not be classified as mutual_fund.

### Step 1d: Skip timing analysis for mutual funds (30 min)

**Scope**: Only timing analysis is skipped. Win scores, grades (A+ through F), FIFO matching, conviction, behavioral analysis — ALL stay for mutual funds. This is correct because win_score measures P&L quality (valid for MF), while timing analysis measures exit price vs. price range (requires intraday trading, not meaningful for NAV-only instruments).

**Where timing happens**: `run_full_analysis()` at `analyzer.py:973` calls `self.analyze_timing()`. This method reads `self.trades` (line 755, `List[NormalizedTrade]`) and groups by symbol (line 771), emitting one `TimingResult` per symbol (line 788). It uses attribute access (e.g., `trade.symbol`, `trade.price`), NOT dict access.

**Building `mf_symbols`**: The `instrument_type_by_symbol` dict is currently a local inside `_analyze_trades_averaged()` (line 666). For `run_full_analysis()`, build it from `self.fifo_transactions` (dicts). Add before line 966:
```python
instrument_type_by_symbol = {}
for txn in self.fifo_transactions:
    sym = self._normalize_ticker(str(txn.get("symbol") or ""))
    if sym and sym not in instrument_type_by_symbol:
        instrument_type_by_symbol[sym] = str(txn.get("instrument_type") or "equity").strip().lower() or "equity"
mf_symbols = {sym for sym, it in instrument_type_by_symbol.items() if it == "mutual_fund"}
```

**Filter before `analyze_timing()` call** (line 973): Temporarily swap `self.trades` with try/finally:
```python
original_trades = self.trades
try:
    self.trades = [t for t in self.trades if self._normalize_ticker(t.symbol) not in mf_symbols]
    timing_results = self.analyze_timing() if self.trades else []
finally:
    self.trades = original_trades  # always restore, even on exception
```
Thread safety: `TradingAnalyzer` is single-threaded (one instance per MCP call). Safe.

**Aggregate timing guards** (lines 974, 1012, 1037):
```python
# avg_timing — unchanged computation, but timing_results now excludes MF symbols
avg_timing = (sum(t.timing_score for t in timing_results) / len(timing_results)) if timing_results else 0

# timing_grade — "N/A" when no timing data
timing_grade = self._get_timing_grade(avg_timing) if timing_results else "N/A"

# overall_grade — _calculate_overall_grade() (line 1078) maps unknown strings to 2.0 via
# grade_points.get(g, 2.0). Filter "N/A" before passing:
gradeable = [g for g in [conviction_grade, timing_grade, sizing_grade, avg_down_grade] if g != "N/A"]
overall_grade = self._calculate_overall_grade(*gradeable) if gradeable else "N/A"
```

**All-mutual-fund behavior**: Only `timing_grade` becomes `"N/A"`. The other 3 grades (conviction, sizing, averaging_down) are still computed — they use P&L/position data, which is valid for MF trades. `overall_grade` is computed from those 3.

**Snapshot timing output** — `get_agent_snapshot()` at `models.py:789`:
Guard with `self.timing_results` (handles both "N/A" from run_full_analysis and "" from filter_by_date_range reset at line 694):
```python
"timing": {
    "avg_timing_score_pct": round(self.avg_timing_score, 1) if self.timing_results else None,
    "timing_symbol_count": len(self.timing_results),  # symbols with timing data
    "total_regret": round(self.total_regret, 2) if self.timing_results else None,
},
```

Note: `timing_results` is per-symbol (one `TimingResult` per symbol, not per trade), so this is a symbol count. Named `timing_symbol_count` for clarity.

**Trading flags** — `core/trading_flags.py:57-58`:
The `poor_timing` flag gates on `total >= 5` (total trades). In a mixed portfolio (1 equity + 9 MF), total=10 but only 1 symbol has timing data. Fix: use `timing_symbol_count`:
```python
timing_count = timing.get("timing_symbol_count", 0)
if avg_timing is not None and timing_count >= 3 and avg_timing < 40:
```
(Changed threshold to 3 since this is symbol count not trade count.)

**Other output paths** — guard timing-derived values when timing_results is empty:
- `to_api_response()` (line 869): Guard both `avg_timing_score` AND `total_regret`: `self.avg_timing_score if self.timing_results else None` and `self.total_regret if self.timing_results else None`
- `to_summary()` (line 935): Only has `avg_timing_score` (NOT `total_regret` — summary payload doesn't include regret). Guard: `self.avg_timing_score if self.timing_results else None`
- `to_cli_report()` (line 1021-1022): Guard both timing score and regret lines: `"  Avg Timing Score: N/A"` and `"  Total Regret: N/A"` when `not self.timing_results`

**Tests**: ~8-10 new tests:
- Timing: mutual fund symbols filtered from `analyze_timing()` via self.trades swap
- self.trades swap exception safety: original restored on error (try/finally)
- Mixed portfolio: equity trades have timing, mutual fund trades do not
- All-mutual-fund portfolio: `timing_grade="N/A"`, `avg_timing_score_pct=None` in snapshot
- `_calculate_overall_grade()` never receives `"N/A"` (pre-filtered)
- `poor_timing` flag uses `timing_symbol_count`, NOT total trade count
- `poor_timing` flag NOT triggered when `avg_timing_score_pct` is `None`
- **Existing test fixture updates**: `tests/core/test_trading_flags.py` and `tests/mcp_tools/test_trading_analysis_agent_format.py` must add `timing_symbol_count` to timing dict

---

## Gap 2: No Schwab Position Normalizer

### Problem
`inputs/normalizers/` only has `ibkr.py`. Users with Schwab position CSVs cannot import them.

### Real Schwab CSV Format
Source: `docs/Individual-Positions-2026-03-10-171456.csv`

```
"Positions for account Individual ...252 as of 05:14 PM ET, 2026/03/10"

"Symbol","Description","Qty (Quantity)","Price","Price Chng % (...)","Price Chng $ (...)","Mkt Val (Market Value)","Day Chng % (...)","Day Chng $ (...)","Cost Basis","Gain % (...)","Gain $ (...)","Ratings","Reinvest?","Reinvest Capital Gains?","% of Acct (% of Account)","Asset Type",
"BXMT","BLACKSTONE MTG TR INC REIT","580.6414","19.2961","...","...","$11,204.11","...","...","$9,751.63","14.89%","$1,452.48","-","Yes","N/A","15.77%","Equity",
"DSU","BLACKROCK DEBT STRATEGIE","2,475.4712","9.85","...","...","$24,383.39","...","...","$25,538.19","-4.52%","-$1,154.80","--","Yes","N/A","34.33%","ETFs & Closed End Funds",
"Futures Cash","--","--","--","--","--","$0.00","--","--","--","--","--","--","--","--","0","Schwab Futures",
"Futures Positions Market Value","--","--","--","--","--","$0.00","--","--","--","--","--","--","--","--","0","Schwab Futures",
"Cash & Cash Investments","--","--","--","--","--","-$16,531.98","0%","$0.00","--","--","--","--","--","--","-","Cash and Money Market",
"Account Total","","--","--","--","--","$54,495.97","...","...","...","...","...","--","--","--","--","--",
```

### Key format details:
- **Preamble**: Line 0 is `"Positions for account ..."`, line 1 is blank
- **Header**: Line 2, with **trailing comma** producing an empty 18th column. All data rows also have trailing commas — consistent across the file. `csv.reader` produces an extra empty field per row; ignore it.
- **Column names**: `"Qty (Quantity)"`, `"Mkt Val (Market Value)"`, `"Asset Type"` (NOT `"Quantity"`, `"Market Value"`, `"Security Type"`)
- **Asset types**: `"Equity"`, `"ETFs & Closed End Funds"`, `"Cash and Money Market"`, `"Schwab Futures"`
- **Non-position rows**: `"Futures Cash"`, `"Futures Positions Market Value"` — skip these
- **Cash row**: `"Cash & Cash Investments"` with negative value, `"--"` for qty/price
- **Summary row**: `"Account Total"` — skip (same trailing comma pattern as other rows)
- **Numbers**: `$11,204.11` format (strip `$` and `,`), negatives as `-$16,531.98`

### Step 2: Write Schwab position normalizer (1.5-2 hours)

**File: `inputs/normalizers/schwab.py`** (new)

**Module-level metadata** (required for `import_portfolio` alias resolution — see `mcp_tools/import_portfolio.py:56-67`):
```python
BROKERAGE_NAME = "Charles Schwab"  # matches providers/schwab_positions.py:114
```

**`detect(lines)`**:
- Look for `"Positions for account"` in first line (preamble), OR
- Look for `"Qty (Quantity)"` AND `"Mkt Val (Market Value)"` in first 5 lines (header)

**Account metadata**: Parse account info from preamble line (e.g., `"Positions for account Individual ...252 as of 05:14 PM ET, 2026/03/10"`). Extract account suffix (e.g., `"...252"`) and account type (e.g., `"Individual"`). Set `PositionRecord.account_id` to the suffix and `account_name` to the type (see `position_schema.py:126-127`).

**`normalize(lines, filename)`** → `NormalizeResult`:

1. Find header row: scan for line containing `"Symbol"` AND `"Qty (Quantity)"`
2. Parse CSV from header row onward via `csv.reader` (trailing commas produce an extra empty field per row — ignore it)
3. Build column index from header row (map column name → index)
4. For each data row:

   **Skip rows**:
   - Symbol is `"Account Total"`, `"Futures Cash"`, `"Futures Positions Market Value"`, or empty
   - Symbol is `"--"`

   **Cash row** (Symbol == `"Cash & Cash Investments"`):
   - `ticker = "CUR:USD"`
   - `quantity = value` (same as value for cash — PositionRecord requires quantity)
   - `value` = parse `"Mkt Val (Market Value)"` column (strip `$`, `,`, handle negative)
   - `type = PositionType.CASH`
   - `currency = "USD"`

   **Normal position rows**:
   - `ticker` = `"Symbol"` column
   - `name` = `"Description"` column
   - `quantity` = parse `"Qty (Quantity)"` column (strip `,`)
   - `price` = parse `"Price"` column
   - `value` = parse `"Mkt Val (Market Value)"` column (strip `$`, `,`)
   - `cost_basis` = parse `"Cost Basis"` column (strip `$`, `,`)
   - `type` = map from `"Asset Type"` column:

     | Asset Type | PositionType |
     |-----------|-------------|
     | `"Equity"` | `PositionType.EQUITY` |
     | `"ETFs & Closed End Funds"` | `PositionType.ETF` |
     | `"Cash and Money Market"` | `PositionType.CASH` |
     | `"Schwab Futures"` | skip row |
     | `"Mutual Fund"` | `PositionType.MUTUAL_FUND` |
     | `"Fixed Income"` | `PositionType.BOND` |
     | default | `PositionType.OTHER` |

   - `currency = "USD"` (Schwab is USD-only)
   - `brokerage_name = "Charles Schwab"` (matches `providers/schwab_positions.py:114`)
   - `position_source = "csv_charles_schwab"`
   - `account_id` / `account_name` = from preamble parsing

5. Parse numbers: strip `$` and `,`, handle `"--"` as None, handle `-$X` as negative
6. Return `NormalizeResult(positions=..., brokerage_name=BROKERAGE_NAME, errors=[...], warnings=[...])`

**Error handling**: Use `try_build_position()` per row (see `position_schema.py`). Per-row failures go into `NormalizeResult.errors` — import is all-or-nothing per the schema contract. `warnings` collects non-fatal issues (e.g., skipped rows, unparseable fields).

**File: `inputs/normalizers/__init__.py`** — register the normalizer:
```python
from . import ibkr, schwab  # add schwab import

BUILT_IN: list[NormalizerModule] = [ibkr, schwab]  # add to list
```

**`import_portfolio` alias resolution**: `mcp_tools/import_portfolio.py:56-67` resolves brokerage names via `_normalizer_aliases()`, which reads `BROKERAGE_NAME` (line 61) and module name (line 59). With `BROKERAGE_NAME = "Charles Schwab"`, the normalizer will match `brokerage="schwab"` or `brokerage="charles_schwab"`. The existing `_resolve_requested_normalizer()` handles the lookup.

**Reference**: `providers/schwab_positions.py` (API-based, for field handling patterns)
**Test fixture**: `docs/Individual-Positions-2026-03-10-171456.csv` (real export)

**Tests**: ~20 tests in `tests/inputs/test_schwab_position_normalizer.py`:
- `detect()` positive (real preamble), negative (IBKR format)
- `normalize()` with real sample data (use fixture)
- Equity rows (BXMT, CBL, ENB, MRP, STWD)
- ETF/CEF row (DSU → PositionType.ETF)
- Cash row with negative value (quantity=value, CUR:USD)
- Futures rows skipped
- Account Total skipped
- Numeric parsing (`$11,204.11` → 11204.11, `"--"` → None, `-$16,531.98` → -16531.98)
- Trailing comma on all rows handled (extra empty field ignored)
- Synthetic mutual fund row (add to test data)
- Account metadata parsed from preamble (account_id, account_name)
- Empty/missing columns gracefully handled
- BROKERAGE_NAME matches `providers/schwab_positions.py:114`
- `import_portfolio` alias resolution: `brokerage="schwab"` resolves correctly

**Integration with existing tests**: Verify new normalizer doesn't break `tests/inputs/test_normalizers.py` (registry-level tests).

---

## Gap 3: Factor Proxy Mappings (Deferred)

Not a blocker. System works without them. Users can add via `manage_ticker_config`.

---

## Execution Order

| Step | Task | Effort | Dependencies |
|------|------|--------|-------------|
| 1a | Add `"mutual_fund"` to InstrumentType (both files) + segment map | 10 min | None |
| 1b | Fix `FMPProvider.can_price()` to include `"mutual_fund"` | 5 min | Step 1a |
| 1c | Update 5 normalizer sites (snaptrade oef, plaid, ibkr_statement, realized perf helper) | 20 min | Step 1a |
| 1d | Skip timing analysis for mutual funds (filter + guards + output paths) | 30 min | Step 1a |
| 2 | Schwab position normalizer + registry + tests | 1.5-2 hrs | None (parallel with 1) |

**Total**: ~3 hours. Steps 1 and 2 can be done in parallel.

---

## Files Changed

| File | Change |
|------|--------|
| `trading_analysis/instrument_meta.py` | Add `"mutual_fund"` to Literal, valid set, segment map |
| `ibkr/_types.py` | Add `"mutual_fund"` to vendored Literal + valid set |
| `providers/fmp_price.py` | Add `"mutual_fund"` to `can_price()` set (line 40) |
| `providers/normalizers/snaptrade.py` | `"oef"` → `"mutual_fund"` (line 43). Keep `"cef"` → `"equity"` |
| `providers/normalizers/plaid.py` | Add mutual fund keyword check before default return |
| `providers/normalizers/ibkr_statement.py` | Add `asset_category` check for mutual funds |
| `core/realized_performance/_helpers.py` | Add fund keyword + oef code to `_infer_position_instrument_type()` |
| `trading_analysis/analyzer.py` | Build `mf_symbols` in `run_full_analysis()`. Filter `self.trades` at line 973 (try/finally). Guard timing_grade/overall_grade. |
| `trading_analysis/models.py` | Guard `get_agent_snapshot()` timing (line 789, use `self.timing_results`). Add `timing_symbol_count`. Guard `to_api_response()` (869), `to_summary()` (935), `to_cli_report()` (1021). |
| `core/trading_flags.py` | Change `poor_timing` gate to use `timing_symbol_count` instead of total trade count |
| `inputs/normalizers/schwab.py` | New — Schwab position CSV normalizer with BROKERAGE_NAME + account metadata |
| `inputs/normalizers/__init__.py` | Import schwab, add to `BUILT_IN` list |

## Test Files

| File | Tests |
|------|-------|
| `tests/trading_analysis/test_instrument_meta.py` | `coerce_instrument_type("mutual_fund")` passthrough |
| `tests/trading_analysis/test_analyzer_mutual_funds.py` | Timing filter, self.trades swap safety, mixed portfolio, all-MF portfolio |
| `tests/inputs/test_schwab_position_normalizer.py` | detect, normalize, all asset types, cash, futures skip, account metadata, alias resolution |
| `tests/providers/test_snaptrade_normalizer.py` | oef → "mutual_fund", cef → "equity" (unchanged) |
| `tests/providers/test_plaid_normalizer.py` | mutual fund keyword → "mutual_fund" |
| `tests/core/test_trading_flags.py` | Update fixtures: add `timing_symbol_count` to timing dict |
| `tests/mcp_tools/test_trading_analysis_agent_format.py` | Update fixtures: add `timing_symbol_count` to snapshot |

## Risk Mitigations

| Risk | Mitigation |
|------|-----------|
| InstrumentType change breaks existing tests | Run full suite after Step 1a before proceeding |
| `"N/A"` timing_grade passed to `_calculate_overall_grade()` → 2.0 default | Filter `"N/A"` out BEFORE calling. Only pass scoreable grades. |
| `avg_timing_score=0.0` triggers poor_timing flag | Guard all output paths with `self.timing_results`. Emit `None` when empty. |
| `poor_timing` flag fires on low timing sample (mixed portfolio) | Use `timing_symbol_count >= 3` instead of `total >= 5` |
| `self.trades` swap not exception-safe | `try/finally` ensures restoration |
| `_helpers.py` "fund" substring matches CEFs | Narrower matching: `"mutual"` or `"open"+"fund"`, never bare `"fund"` |
| SnapTrade `security_type` vs `instrument_type` confusion | These are separate systems. `security_type: "mutual_fund"` (risk scoring) is correct for both OEF/CEF. `instrument_type` (trading) distinguishes: oef→"mutual_fund", cef→"equity" |
| Schwab CSV trailing comma | All rows have trailing comma. `csv.reader` extra field — ignore |
| Schwab normalizer not found by `import_portfolio` | `BROKERAGE_NAME = "Charles Schwab"` enables alias resolution |
