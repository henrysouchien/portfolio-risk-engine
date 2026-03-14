# Schwab Normalizer Fix Plan

**Status**: COMPLETE
**Date**: 2026-02-16
**Tests**: 25 in schwab normalizer tests
**Key file**: `providers/normalizers/schwab.py`

---

## Bug 1: Non-trade transactions processed as trades

**Location**: `providers/normalizers/schwab.py:210-224`

Schwab API returns ALL account activity in one endpoint -- trades, dividends, cash transfers, journals, etc. The normalizer has no transaction-type gating. Non-trade types (JOURNAL, CASH_DISBURSEMENT, ACH_*, WIRE_*, etc.) fall through to a cash-direction fallback that creates fake BUY/SELL entries with `symbol=CURRENCY_USD`.

**Impact**:
- Fake CURRENCY_USD trades in trade scorecards, win rates, behavioral metrics (`TradingAnalyzer`)
- CURRENCY_USD enters position timeline -> pricing loop tries to price it -> unpriceable (`analyze_realized_performance()`)
- Fake FIFO lots appear as harvestable positions (`suggest_tax_loss_harvest()`)
- Corrupts `derive_cash_and_external_flows()` -- fake BUY/SELL events distort inferred cash balance and external flow inference -> wrong NAV-adjusted returns

**Fix**: Gate on Schwab transaction family while preserving explicit trade-action rows.
- Process trade rows when either:
  1. transaction family indicates trade (`type=TRADE`), **or**
  2. action-style trade type is already explicit (see shared trade-action enum below), with subtype/activity fallback.

**Shared Schwab trade-action enum** (Codex R5#5): Define a single set of recognized trade actions used by both the normalizer and the flow extractor (to exclude from external flows). Must include option open/close variants from `docs/reference/schwab_transaction_api.md`:
```python
SCHWAB_TRADE_ACTIONS = {
    "BUY", "SELL", "SHORT", "COVER",
    "BUY_TO_COVER", "SELL_SHORT", "SHORT_SALE",
    "BUY_TO_OPEN", "SELL_TO_OPEN",
    "BUY_TO_CLOSE", "SELL_TO_CLOSE",
    "EXCHANGE",
}
```
Check `type` field against this enum (case-insensitive). This prevents option open/close actions from being misclassified as non-trade families.

**Action-to-TradeType mapping** (Codex R6#1): Each action must map explicitly to a `TradeType` (`BUY/SELL/SHORT/COVER`). No action should fall through to sign-based fallback:
```
BUY             -> BUY
BUY_TO_COVER    -> COVER
BUY_TO_OPEN     -> BUY       (open long option)
BUY_TO_CLOSE    -> COVER     (close short option)
SELL            -> SELL
SELL_SHORT      -> SHORT
SHORT_SALE      -> SHORT
SELL_TO_OPEN    -> SHORT     (open short option)
SELL_TO_CLOSE   -> SELL      (close long option)
EXCHANGE        -> BUY       (security conversion -- treat as acquisition)
```
Define this as a shared `SCHWAB_ACTION_TO_TRADE_TYPE` dict alongside `SCHWAB_TRADE_ACTIONS`. The normalizer must use this mapping instead of the current cascading if/elif chain. Tests must cover every action in the enum.
- Process income rows for `DIVIDEND_OR_INTEREST`.
- Skip non-trade/non-income families for trade normalization (`JOURNAL`, `CASH_DISBURSEMENT`, `ACH_*`, `WIRE_*`, etc.).
- Cash-direction fallback should apply only inside trade-family/action-trade scope, never for generic cash movement families.
- **Asset-type guard** (Codex R1#8): Additionally, within trade-family scope, skip rows where `instrument.assetType == CURRENCY` (or symbol starts with `CURRENCY_`). These represent cash legs of transactions, not tradeable instruments. This prevents `CURRENCY_USD` from leaking into trades even for `TRADE`-family rows that have both a security leg and a cash leg.
- **Non-currency leg selection for ALL trades** (Codex R9#2): The current normalizer extracts quantity/price from the first non-zero `transferItems[].amount`/`price` without filtering currency legs (`providers/normalizers/schwab.py:38-79`). If a trade row has both security and cash legs and the cash leg appears first, units are interpreted as dollars (wrong quantity/price → FIFO drift). Apply the same non-currency-leg selection rule from Bug 5 (REINVEST) to **all** trade normalization paths: iterate `transferItems`, select the entry where `instrument.assetType != CURRENCY` and `instrument.symbol` does not start with `CURRENCY_`. Fall back to first non-zero entry only when no non-currency leg is found. Add tests for cash-leg-first ordering.

**Reference**: `docs/reference/schwab_transaction_api.md` -- full list of Schwab transaction types.

**Status gating** (Codex R1#5): Before any type-based processing, filter on `status` field. Only process rows with `status=VALID` (or missing status, for backward compat). Skip `PENDING`, `CANCELED`, `INVALID` rows with a debug log. This applies to both trade normalization and income extraction.

---

## Bug 2: Dividend income attributed to CURRENCY_USD

**Location**: `providers/normalizers/schwab.py:169-196`

For DIVIDEND_OR_INTEREST transactions, the Schwab API puts `CURRENCY_USD` as the instrument (the cash leg). The actual stock name is only in the `description` field -- there is NO ticker field on dividend transactions.

Current code extracts the instrument symbol (line 170) which is always CURRENCY_USD for dividends, then writes that into the income event (line 188).

**Impact**:
- All Schwab dividend income attributed to CURRENCY_USD instead of the actual stock
- Income projection per-symbol is broken
- Income analysis in trading scorecard is wrong

**Fix**: Two-pass approach:
1. First pass: scan all trade-eligible rows using the **same predicate as normalization** -- `status=VALID` + (`type=TRADE` OR `type in SCHWAB_TRADE_ACTIONS`) + non-currency asset-type guard (Codex R7#1). Build a `description -> ticker` map (e.g., "BLACKROCK DEBT STRAT FD" -> "DSU") from these rows' `instrument.symbol` and `description` fields.
2. Second pass: for DIVIDEND_OR_INTEREST, resolve symbol via the description->ticker map
3. Bank interest / margin interest with no matching trade description stays as generic interest

**Description matching** (Codex R1#10): Normalize descriptions before matching -- lowercase, collapse whitespace, strip punctuation. Track ambiguity: if multiple tickers map to the same normalized description, keep symbol unresolved with a warning (don't silently pick one). Log diagnostics for unresolved dividend symbols.

**Fallback hierarchy** (Codex R1#6, R2#2): The description->ticker map from in-window trades won't cover long-held positions with no trades in the analysis window. Resolution order:
1. Description->ticker map from TRADE transactions in the raw payload
2. Schwab-specific position lookup (see Bug 4) -- a dedicated `schwab_security_lookup` dict mapping `normalized_description -> ticker`, built from `SchwabPositionProvider` data. This is separate from the Plaid `security_lookup` (which is keyed by `security_id` and often empty for Schwab-only runs).
3. If no match: classify as unresolved. For rows where the resolved subtype indicates interest (`INTEREST`, `CREDIT_INTEREST`), classify as interest. Otherwise emit income with `symbol="UNRESOLVED_DIVIDEND"` and a warning. Never force-classify as interest just because resolution failed.

**Data evidence** (from `/tmp/schwab_txns.json`):
- TRADE: `description="BLACKROCK DEBT STRAT FD"`, `instrument.symbol="DSU"`
- DIVIDEND: `description="BLACKROCK DEBT STRAT FD"`, `instrument.symbol="CURRENCY_USD"`
- Descriptions match exactly between TRADE and DIVIDEND for the same stock.

---

## Bug 3: Interest misclassified as dividend

**Location**: `providers/normalizers/schwab.py:110-114`

`_event_type()` checks for "DIVIDEND" in the combined type+subtype+description string. Since the top-level type is `DIVIDEND_OR_INTEREST`, the word "DIVIDEND" always matches first, so margin interest and bank interest are classified as dividends.

**Fix**: Restructure `_event_type()` for `DIVIDEND_OR_INTEREST` rows to use a shared normalized subtype as the primary discriminator.

**Shared subtype resolver** (Codex R2#4): Schwab schema has both `transactionSubType` and `activityType` fields. Classification must check both:
```python
resolved_subtype = (txn.get("transactionSubType") or txn.get("activityType") or "").upper().strip()
```
Then apply rules on `resolved_subtype` in **priority order** (Codex R3#1 -- `REINVEST_DIVIDEND` contains "DIVIDEND", so REINVEST must be checked first):
1. Starts with or equals `REINVEST` (matches `REINVEST_SHARES`, `REINVEST_DIVIDEND`) -> return `"REINVEST"` (see Bug 5)
2. Contains `INTEREST` or `CREDIT_INTEREST` -> return `"INTEREST"`
3. Contains `DIVIDEND`, `QUALIFIED_DIVIDEND`, `NON_QUALIFIED_DIVIDEND`, `CAPITAL_GAIN` -> return `"DIVIDEND"`
4. Contains `TAX_WITHHOLDING` or `CASH_IN_LIEU` -> return `"FEE"` (debit-like, not positive income -- Codex R8#4)
5. Fallback for unknown subtypes: check description for "INTEREST" patterns -> interest; otherwise -> dividend
- Do NOT check the `type` field text ("DIVIDEND_OR_INTEREST") in the combined string -- it always contains "DIVIDEND" and poisons the check.

**Debit subtype policy** (Codex R8#4): Shared policy for debit-like subtypes under `DIVIDEND_OR_INTEREST`, used by both normalizer and flow extractor:
- `TAX_WITHHOLDING`: emit as negative income adjustment (reduces income amount for the associated symbol) or as `flow_type=fee` in flow extractor. Never convert to positive income via `abs()`.
- `CASH_IN_LIEU`: emit as income (cash received for fractional share) with correct positive sign.
- Negative `INTEREST`/`CREDIT_INTEREST` (margin interest debits): flow extractor emits as `flow_type=fee`, `is_external_flow=false`. Normalizer classifies as interest income with negative amount (not abs'd).
- General rule: the normalizer must preserve the sign of `netAmount` for debit-like subtypes. The current `abs(netAmount)` pattern in `schwab.py:180` is incorrect for these cases and must be gated on the resolved subtype.
- Prefer exact enum matching (e.g., `resolved_subtype in {"REINVEST_SHARES", "REINVEST_DIVIDEND"}`) over substring contains where possible, to avoid false positives. Use contains only as fallback for unexpected subtype variants.

This same `resolved_subtype` pattern must also be used in the provider flow extractor (`providers/flows/schwab.py`) for consistent classification of margin interest as fee events.

---

## Bug 4: `security_lookup` parameter ignored

**Location**: `providers/normalizers/schwab.py:148`

The normalizer accepts `security_lookup` but immediately does `del security_lookup`. This parameter could be used as a fallback for dividend symbol resolution (e.g., passing Schwab position data with real tickers).

**Fix** (Codex R2#2, R3#3): The existing `security_lookup` parameter is wired from `TradingAnalyzer` which passes Plaid's `security_id`-keyed lookup (`analyzer.py:406`). This is not useful for Schwab dividend resolution.

Instead, inject a dedicated **`schwab_security_lookup`** via the normalizer constructor (keeps the `TransactionNormalizer` Protocol stable -- no signature changes to `normalize()`):
1. `SchwabPositionProvider.fetch_positions()` already returns rows with `ticker` and `name` fields.
2. Build a `normalized_description -> ticker` map from Schwab position data (normalize descriptions same as Bug 2).
3. Pass this map to `SchwabNormalizer.__init__(schwab_security_lookup=None)` at construction time, before `TradingAnalyzer` runs normalization.
4. The normalizer stores it as `self._schwab_security_lookup` and uses it in the Bug 2 fallback hierarchy during `normalize()`.
5. The existing `security_lookup` parameter in `normalize()` remains deleted (Plaid-only, not useful for Schwab).
6. The `TransactionNormalizer` Protocol is unchanged -- constructor args are not part of the Protocol contract.

**Canonical wiring path** (Codex R4#2): One canonical path, not "or":
1. **Shared builder** in `providers/normalizers/schwab.py`:
   ```python
   def build_schwab_security_lookup(positions_df: pd.DataFrame) -> dict[str, str]:
       """Build normalized_description -> ticker map from Schwab positions."""
   ```
   Normalize descriptions (lowercase, collapse whitespace, strip punctuation -- same as Bug 2). Skip rows with missing ticker or name. Track ambiguity (multiple tickers for same normalized description -> warn and exclude).

2. **`TradingAnalyzer.__init__()`** accepts optional `schwab_security_lookup: dict[str, str] | None = None` and passes it to `SchwabNormalizer(schwab_security_lookup=...)` during normalizer construction. This is the single injection point -- normalizers are constructed once in `__init__`.

3. **All callers** build the lookup before constructing `TradingAnalyzer` and pass it through. Exhaustive caller list:

   | Caller | File | How to build lookup |
   |--------|------|---------------------|
   | `main()` | `run_trading_analysis.py` | Call `SchwabPositionProvider().fetch_positions(user_email=user_email)` if `is_provider_available("schwab")`, then `build_schwab_security_lookup()` |
   | `get_trading_analysis()` | `mcp_tools/trading_analysis.py` | Same pattern (user_email from MCP context) |
   | `suggest_tax_loss_harvest()` | `mcp_tools/tax_harvest.py` | Same pattern (user_email from MCP context) |
   | `analyze_realized_performance()` | `core/realized_performance_analysis.py` | Same pattern; already has `user_email` param |

   **Note** (Codex R9#1): `SchwabPositionProvider.fetch_positions(user_email=...)` requires a `user_email` argument (even though Schwab ignores it internally -- `del user_email` at line 46). The `get_schwab_security_lookup()` helper must accept `user_email` and pass it through. All callers already have `user_email` in scope.

4. **Shared helper** (recommended DRY): Extract `get_schwab_security_lookup() -> dict | None` in `providers/normalizers/schwab.py` that does the `is_provider_available` check + position fetch + map build in one call. Callers reduce to `schwab_lookup = get_schwab_security_lookup()`.

5. **Lazy guard** (Codex R5#6): The shared helper must be lazy -- only fetch Schwab positions when Schwab transactions are actually present in the payload (or when `source in {"schwab", "all"}` and Schwab is available). Do NOT prefetch unconditionally when Schwab is enabled but the user requested `source="plaid"` or `source="snaptrade"`. This prevents unnecessary external API calls and potential failures for unrelated analyses. In `TradingAnalyzer.__init__()`, if `schwab_security_lookup` is not passed by the caller, the SchwabNormalizer gets `None` and the fallback hierarchy simply skips step 2.

6. **Fail-open on errors** (Codex R7#2): `get_schwab_security_lookup()` must catch and log any exceptions from `SchwabPositionProvider.fetch_positions()` and return `None`. A position-fetch failure must not abort the entire analysis. Normalization proceeds with the trade-description map (step 1) and unresolved fallback (step 3) -- both work without the position lookup.

---

## Bug 5: Reinvestment subtypes not handled (Codex R1#3)

**Location**: `providers/normalizers/schwab.py` -- new handling needed

Schwab `DIVIDEND_OR_INTEREST` rows with `transactionSubType` (or `activityType`) of `REINVEST_SHARES` or `REINVEST_DIVIDEND` represent dividend reinvestment -- they are both an income event AND a buy. Currently these fall through to the dividend path (income only), which means:
- The buy leg is lost -> position/FIFO drift over time
- Holdings diverge from actual account state

**Fix**: Follow the SnapTrade `REI` pattern (`providers/normalizers/snaptrade.py:296-328`):
1. Emit a `NormalizedIncome` event (dividend, resolved symbol via Bug 2 hierarchy). **Income amount extraction order** (Codex R8#3): cash-leg `transferItems` entry `amount` (absolute value) -> non-currency leg `price * quantity` -> `abs(netAmount)` as fallback. If all sources are zero/missing, emit warning and skip both income and buy legs consistently (do not emit one without the other).
2. Emit a `NormalizedTrade` (BUY) + aligned `fifo_transaction` for the share acquisition
3. **Multi-leg transferItems handling** (Codex R2#5): REINVEST rows may have multiple `transferItems` entries (cash leg + security leg). Explicitly select the non-currency leg for quantity/price extraction:
   - Iterate `transferItems` and select the entry where `instrument.assetType != CURRENCY` and `instrument.symbol` does not start with `CURRENCY_`
   - Extract quantity from the selected entry's `amount` field, price from `price` field
   - If no non-currency leg found, derive from top-level `netAmount / quantity` as fallback
   - If ambiguous (multiple non-currency legs), emit warning and skip the buy leg (income-only, safe fallback)
4. Preserve trade/FIFO 1:1 index alignment invariant

---

## Broader Issue: Flow-adjusted returns use inferred (not actual) cash flows

**Location**: `core/realized_performance_analysis.py:1104-1184`

`derive_cash_and_external_flows()` infers deposits/withdrawals by replaying trades and watching when cash goes negative. This is an approximation with known weaknesses:

1. **Timing mismatch**: deposits sitting as cash before a buy are invisible until the buy happens
2. **Can't detect real withdrawals**: only "repays" previously inferred deposits
3. **Cash drag invisible**: uninvested cash isn't tracked

Schwab actually provides real deposit/withdrawal data (JOURNAL, ACH_RECEIPT, ACH_DISBURSEMENT, CASH_RECEIPT, CASH_DISBURSEMENT, WIRE_IN, WIRE_OUT). Other providers (Plaid, SnapTrade, IBKR Flex) may also have this data -- **needs research**.

**Question**: Can we use actual cash flow data from providers that supply it, while keeping inference as fallback for providers that don't?

**Answer**: Yes -- addressed by the Provider Native Flows Implementation Plan (`docs/planning/PROVIDER_NATIVE_FLOWS_IMPLEMENTATION_PLAN.md`). The rows this normalizer fix drops from trade processing (non-trade families) are exactly the rows the flow extractor needs.

---

## Normalizer interface contract

Per `providers/interfaces.py`, `TransactionNormalizer.normalize()` returns:
```
tuple[list[NormalizedTrade], list[NormalizedIncome], list[dict[str, Any]]]
```
- `trades` and `fifo_transactions` must be 1:1 index-aligned
- Any fix must preserve this invariant

## How other normalizers handle this

- **Plaid** (`providers/normalizers/plaid.py`): explicit type gating, unknown types dropped
- **SnapTrade** (`providers/normalizers/snaptrade.py`): explicit activity-type branching, income separated, REINVEST produces income + BUY
- **IBKR Flex** (`providers/normalizers/ibkr_flex.py`): explicit trade/income types only, unknown dropped
- None use a global cash-direction fallback for non-trade transaction families

---

## Codex Review

### Round 1 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 3 | HIGH | Reinvestment subtypes (`REINVEST_SHARES`, `REINVEST_DIVIDEND`) not handled -- drops buy leg, causes FIFO/position drift | Added Bug 5: emit income + BUY/FIFO pair following SnapTrade `REI` pattern |
| 5 | HIGH | No status gating (`VALID` vs `PENDING/CANCELED/INVALID`) -- pending rows pollute trades and income | Added status filter in Bug 1: only process `VALID` or missing-status rows; skip others with debug log |
| 6 | HIGH | Description->ticker map fails for long-held positions with no trades in window | Added fallback hierarchy in Bug 2: trades map -> security_lookup -> unresolved with warning |
| 8 | MED | Family gating alone doesn't exclude `CURRENCY_*` asset-type symbols from trades | Added asset-type guard in Bug 1: skip `assetType=CURRENCY` / `CURRENCY_*` symbols within trade scope |
| 10 | MED | Exact-string description matching is fragile (case, punctuation, ambiguity) | Added description normalization + ambiguity tracking in Bug 2 |

### Round 2 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 2 | HIGH | security_lookup fallback expects Schwab positions but current analyzer passes Plaid security_id-keyed lookup (often empty for Schwab) | Added dedicated `schwab_security_lookup` input in Bug 4, separate from Plaid security_lookup; wired through TradingAnalyzer from Schwab positions |
| 4 | MED | Subtype logic uses only `transactionSubType` but Schwab also has `activityType`; can miss REINVEST/INTEREST classification | Added shared resolved_subtype pattern (`transactionSubType or activityType`) in Bug 3; same pattern required in flow extractor |
| 5 | MED | REINVEST buy-leg extraction under-specified for multi-leg transferItems | Added explicit non-currency leg selection in Bug 5 with ambiguity fallback |

### Round 3 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Subtype classification order: `REINVEST_DIVIDEND` contains "DIVIDEND" so REINVEST can be misclassified | Made priority order explicit in Bug 3: REINVEST checked first, prefer exact enum matching over substring contains |
| 3 | MED | schwab_security_lookup as new normalize() kwarg changes TransactionNormalizer Protocol contract | Changed to constructor injection in Bug 4: `SchwabNormalizer.__init__(schwab_security_lookup=None)`; Protocol unchanged |

### Round 4 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 2 | HIGH | schwab_security_lookup wiring ambiguous ("or TradingAnalyzer.__init__()") -- which callers build/pass it? | Specified one canonical path: shared `build_schwab_security_lookup()` builder + `TradingAnalyzer.__init__()` as single injection point + exhaustive caller table (4 sites) + optional `get_schwab_security_lookup()` DRY helper |

### Round 5 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 5 | MED | Trade-action allowlist incomplete -- missing option open/close variants (`BUY_TO_OPEN`, `SELL_TO_OPEN`, etc.) and `EXCHANGE` | Added shared `SCHWAB_TRADE_ACTIONS` enum in Bug 1 with all variants from Schwab API docs; used by both normalizer and flow extractor |
| 6 | MED | schwab_security_lookup prefetch over-eager -- fails unrelated non-Schwab analyses | Added lazy guard in Bug 4: only fetch when Schwab transactions present or source includes Schwab |

### Round 6 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Missing explicit action-to-TradeType mapping for newly allowed trade actions -- sign-based fallback misclassifies options | Added `SCHWAB_ACTION_TO_TRADE_TYPE` dict in Bug 1 with explicit mapping for all 11 actions; tests must cover every action |

### Round 7 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | Description->ticker map built only from `type=TRADE` rows, misses action-style trade rows | Fixed Bug 2: map uses same trade predicate as normalization (status + family/action enum + non-currency guard) |
| 2 | MED | `get_schwab_security_lookup()` failure aborts analysis | Added fail-open in Bug 4: catch/log errors, return `None`; normalization proceeds with trade-description map + unresolved fallback |

### Round 8 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 3 | MED | REINVEST income amount unspecified when `netAmount` is zero | Added extraction order in Bug 5: cash-leg -> price*qty -> abs(netAmount); zero = skip both legs with warning |
| 4 | HIGH | Negative DIVIDEND_OR_INTEREST subtypes (TAX_WITHHOLDING, margin interest) converted to positive income via abs() | Added shared debit-subtype policy in Bug 3: TAX_WITHHOLDING/CASH_IN_LIEU classification; preserve sign for debits; gate abs() on resolved subtype |

### Round 9 -- Issues Found

| # | Severity | Issue | Resolution |
|---|----------|-------|------------|
| 1 | HIGH | `SchwabPositionProvider.fetch_positions()` requires `user_email` arg but plan omits it | Fixed caller table: all sites pass `user_email`; `get_schwab_security_lookup()` accepts and passes `user_email` |
| 2 | HIGH | Non-currency leg selection only for REINVEST -- all trades vulnerable to cash-leg-first ordering | Extended same rule to all trade normalization paths in Bug 1; added tests for cash-leg-first |
