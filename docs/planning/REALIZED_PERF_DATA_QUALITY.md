# Realized Performance: Data Quality Investigation

## Problem

`get_performance(mode="realized", format="agent")` shows poor data quality across all providers. Coverage is low, most positions are synthetic (inferred from current holdings with no opening trade), and return metrics are unreliable as a result.

**Impact:** The agent can't trust realized performance numbers for investment decisions. Metrics like total return, Sharpe ratio, and alpha are distorted by fabricated cost basis on synthetic positions.

## Current State (2026-02-25)

## Statement Baseline (Extracted 2026-02-25)

Ground-truth broker statement extracts for investigation now live in:

- `docs/planning/performance-actual-2025/BASELINE_EXTRACTED_2025.md` (human-readable summary)
- `docs/planning/performance-actual-2025/baseline_account_summary.csv`
- `docs/planning/performance-actual-2025/baseline_schwab_returns.csv`
- `docs/planning/performance-actual-2025/baseline_merrill_year_breakdown.csv`
- `docs/planning/performance-actual-2025/baseline_ibkr_pnl_totals.csv`
- `docs/planning/performance-actual-2025/baseline_ibkr_trade_counts.csv`
- `docs/planning/performance-actual-2025/baseline_ibkr_open_positions.csv`
- `docs/planning/performance-actual-2025/baseline_extracted_data.json`

Regenerate these files with:

```bash
python3 scripts/extract_performance_actual_baseline.py
```

### Per-Provider Breakdown

| Provider | Source | Txn Count | Coverage | Synthetic | Total Return | Sharpe | Notes |
|---|---|---|---|---|---|---|---|
| **Schwab** | `source="schwab"` | 88 | 37.5% | 19 | 176% | 1.60 | Only equity trades; dividends/interest present |
| **Plaid** (Merrill) | `source="plaid"` | 54 | 12.5% | 24 | 8% | 0.04 | Mostly dividend/interest txns, few actual trades |
| **SnapTrade** | `source="snaptrade"` | 0 | 0% | 24 | 0% flat | 0.00 | Zero transactions. Completely dead |
| **Combined** | `source="all"` | 142 | 37.5% | 17 | 138% | 1.59 | Schwab dominates; dedup reduces synthetic count |

### Synthetic Positions (Combined, 17 positions, $57,517 market value)

These positions exist in current brokerage holdings but have no opening trade in transaction history:

```
AT.L, CPPMF, EQT, FIG, GLBE, IGIC, IT, KINS, LIFFF, MSCI,
NVDA, PCTY, RNMBY, SFM, SLV, TKO, V
```

Several of these are major holdings (NVDA, V, IT, MSCI) — their fabricated cost basis significantly distorts return calculations.

### Other Data Quality Flags

- **Unpriceable**: `US Treasury Note - 4.25% 15/10/2025 USD 100` (bond_missing_con_id)
- **NAV metrics estimated**: true (not all cash flows observed)
- **Synthetic NAV impact**: -$1,384 (observed-only NAV is $9,886 vs synthetic-enhanced $8,502)
- **Reconciliation gap**: -$3,415 between NAV-based and lot-based P&L
- **IBKR pricing**: 0 symbols priced via IBKR (TWS likely offline)
- **14 data quality warnings** on combined run

### Monthly Returns (Combined)

Early months show extreme returns suggesting position inception distortion:
- 2024-05: +20.8% (possible synthetic entry month)
- 2024-07: +40.9% (extreme — likely NVDA or similar entering at wrong cost basis)
- 2024-08: +19.5%

Later months stabilize to normal range (-3% to +3%), suggesting the synthetic distortion is concentrated in early periods.

## Investigation Questions

### Q1: Why is Schwab coverage only 37.5%?

Schwab provides 88 transactions. Are these 88 txns covering only ~9 of 24 positions (37.5%)? Or is coverage calculated differently?

**Files to check:**
- `core/realized_performance_analysis.py` — how `data_coverage` is computed
- `trading_analysis/data_fetcher.py` — `fetch_transactions_for_source("schwab")` — what's actually returned
- `providers/normalizers/schwab.py` — are some transaction types being dropped during normalization?

**Specific checks:**
- How many unique tickers appear in Schwab's 88 transactions?
- Are the 19 synthetic positions (NVDA, V, IT, etc.) actually held at Schwab? Or at other brokerages?
- Does Schwab's API provide full trade history or only recent trades? Is there a lookback limit?

### Q2: Why does Plaid (Merrill) have 54 transactions but only 12.5% coverage?

54 transactions sounds like enough to cover several positions. But if most are dividend/interest transactions rather than BUY/SELL trades, they don't establish position cost basis.

**Files to check:**
- `providers/normalizers/plaid.py` — what transaction types are normalized
- `trading_analysis/data_fetcher.py` — `fetch_transactions_for_source("plaid")`
- Check the 54 Plaid transactions: how many are BUY/SELL vs DIVIDEND/INTEREST?

### Q3: Why does SnapTrade have zero transactions?

SnapTrade is connected (it returns positions) but provides zero transaction history. Is this:
- A SnapTrade API limitation (positions-only, no trades)?
- A configuration issue (transactions not being fetched)?
- A normalization issue (transactions fetched but dropped)?

**Files to check:**
- `brokerage/snaptrade/` — does the SnapTrade client fetch transactions?
- `providers/normalizers/` — is there a SnapTrade transaction normalizer?
- `trading_analysis/data_fetcher.py` — is `snaptrade` a registered source?

### Q4: How are synthetic positions created and what cost basis do they use?

When a position exists in current holdings but has no opening trade, the system creates a "synthetic" position. What entry price does it use? If it uses current price, returns would be ~0%. If it uses some historical price, returns could be wildly wrong.

**Files to check:**
- `core/realized_performance_analysis.py` — synthetic position creation logic
- Search for `synthetic` in that file — how is `entry_price` / `cost_basis` set?

### Q5: Can we improve coverage without new data sources?

- **Schwab**: Does the Schwab API support fetching older transactions? Is there a `start_date` parameter we're not using?
- **Plaid**: Does Plaid's investment transactions endpoint return trade history or just recent activity?
- **Backfill**: The `backfill_path` parameter exists on `get_performance()` — can we manually provide opening trades for known positions?

### Q6: Should we gate or qualify the output when coverage is low?

Currently the system returns metrics with flags but doesn't prevent the agent from seeing misleading numbers. Options:
- Return `null` for metrics when coverage < threshold (e.g., 50%)
- Add a top-level `reliable: false` field
- Show observed-only metrics instead of synthetic-enhanced when synthetic impact is large
- Truncate analysis period to start from first real transaction (skip synthetic inception)

## Key Files

| File | Role |
|---|---|
| `core/realized_performance_analysis.py` | Main analysis engine — NAV reconstruction, synthetic positions, coverage calc |
| `trading_analysis/data_fetcher.py` | Transaction fetching — `fetch_all_transactions()`, per-source fetching |
| `trading_analysis/analyzer.py` | TradingAnalyzer — normalization, FIFO matching, dedup |
| `trading_analysis/fifo_matcher.py` | FIFO lot matching, synthetic position inference |
| `providers/normalizers/schwab.py` | Schwab transaction normalization |
| `providers/normalizers/plaid.py` | Plaid transaction normalization |
| `providers/normalizers/snaptrade.py` | SnapTrade normalization (if exists) |
| `providers/flows/` | Provider-native cash flow extraction |
| `mcp_tools/performance.py` | MCP tool — `get_performance()` with format/source params |
| `core/result_objects/realized_performance.py` | `RealizedPerformanceResult` — data_quality fields, agent snapshot |

## Reproduction

```bash
# Combined — shows 37.5% coverage, 17 synthetic
python3 tests/utils/show_api_output.py "get_performance(mode='realized', format='agent')"

# Per-provider isolation
python3 -c "
from mcp_tools.performance import get_performance
import json

for source in ['schwab', 'plaid', 'snaptrade']:
    result = get_performance(mode='realized', source=source, format='agent')
    snap = result.get('snapshot', {})
    dq = snap.get('data_quality', {})
    print(f'{source}: coverage={dq.get(\"coverage_pct\")}%, synthetic={dq.get(\"synthetic_count\")}, return={snap.get(\"returns\", {}).get(\"total_return_pct\")}%')
"
```

Or via MCP:
```
get_performance(mode="realized", format="agent")
get_performance(mode="realized", source="schwab", format="agent")
get_performance(mode="realized", source="plaid", format="agent")
get_performance(mode="realized", source="snaptrade", format="agent")
```

## Root Cause Analysis (2026-02-25, Stream B Investigation)

Detailed investigation traced the return distortion through the full NAV reconstruction pipeline.
The system reports **+86.61%** (observed-only track) vs actual broker returns of **-8% to -12%**.

### Three Independent Distortion Sources

#### 1. Synthetic Position Cash Inflation (affects synthetic-enhanced NAV)

When positions exist in current holdings but have no opening BUY trade, the engine:
1. Creates a synthetic BUY at `inception_date - 1 second`
2. The synthetic BUY enters `derive_cash_and_external_flows()` cash replay
3. Cash goes negative by the full notional (e.g., -$85K for 15 synthetic positions)
4. Lines 1317-1321: inference engine detects negative cash → injects fake **contribution** of +$85K
5. Modified Dietz denominator (`V_start + weighted_flows`) is inflated by this fake contribution
6. Returns are distorted because the denominator doesn't reflect real invested capital

**Engine's existing mitigation:** The sensitivity gate fires (`SYNTHETIC_PNL_SENSITIVITY`) and switches to the observed-only NAV track. But that track has its own problems (see #2 and #3).

**10 synthetic positions in `source=all`:** CPPMF, EQT, IGIC, IT, KINS, LIFFF, NVDA, PCTY, TKO, V.
- 6 are IBKR (bought before Flex 1-year window): EQT, IGIC, KINS, NVDA, TKO, V
- 4 are Schwab/Merrill (bought before API lookback): CPPMF, IT, LIFFF, PCTY

**Key finding:** The brokerage holdings DO have correct cost basis (verified against IBKR CSV, delta = $3.57 total). The problem is purely in how synthetic entries interact with the cash replay / flow inference engine.

#### 2. Futures Notional Amplification (affects observed-only NAV)

Futures trades use full notional value in the cash replay, but futures are margined instruments — a BUY doesn't withdraw full notional from cash.

Specific trades causing distortion:
- **MHI** (Mini Hang Seng): 10 contracts × HK$23,695 = **$236,950** BUY in Mar 2025, SELL $206,320 in Apr
- **ZF** (5-Year Treasury): **$108,164** BUY in Mar 2025, SELL $108,203 in Apr
- **MGC** (Micro Gold): ~$30K per round trip, multiple trades

Total: **~$475K notional** flowing through a **$160K portfolio**.

Impact on Modified Dietz:
- March: $350K BUYs → cash = -$350K → inferred contribution of $350K → return = (V_end - 0 - 350K) / 350K = **+30.9%**
- April: $385K SELLs → cash floods positive → inferred withdrawal → return = **+31.8%**
- These two months account for nearly all of the reported +86.61% total return

**Fix needed:** `derive_cash_and_external_flows()` should use margin-based cash impact for futures, not full notional. Or exclude futures from cash replay entirely.

#### 3. Plaid UNKNOWN Bond/Fund Trades ($4M phantom volume)

The Plaid normalizer produces **54 transactions** all with `symbol="UNKNOWN"`:
- **U.S. Treasury Note** 4.25% Oct 15 2025: 10,000 par × $100 = **$1,000,600** BUY, 20,000 par SELL
- **BlackRock Debt Strategies Fund**: multiple reinvestment buys
- Total UNKNOWN notional: **$4,032,733** — in a $160K portfolio

These trades go through the cash replay creating massive phantom flows that distort the flow inference and Modified Dietz calculation.

**Fix needed:** Filter UNKNOWN-symbol trades from cash replay, or resolve the symbols via Plaid security_id lookup.

### Data Flow Verification

| Check | Result |
|---|---|
| IBKR Flex credentials | Set and working (token=24 chars, query_id=7 chars) |
| IBKR Flex data | 139 trades, 50 cash rows, window 2025-02-25 to 2026-02-24 |
| IBKR Flex BUY symbols | AT.L, FIG, MHI, MGC, RNMBY, SFM, SLV, ZF (+ options, FX) |
| SnapTrade | 0 activities (dead — all IBKR data via Flex) |
| Schwab normalizer | 88 FIFO txns (85 BUY, 3 SELL) across 10 symbols |
| Plaid normalizer | 54 FIFO txns, ALL symbol=UNKNOWN |
| Brokerage cost basis | Correct — matches IBKR CSV within $3.57 |
| `brokerage_name` on positions | ALL are `None` — institution filter cannot work |
| `TRANSACTION_FETCH_POLICY` | `direct_first` — ibkr_flex runs, then SnapTrade skips IBKR |

### Fix Priority (Revised)

| Fix | Impact | Difficulty | Priority |
|---|---|---|---|
| **Futures margin-aware cash replay** | Eliminates +62% of fake return (Mar+Apr spikes) | Medium | **P1** |
| **Filter UNKNOWN from cash replay** | Removes $4M phantom volume | Easy | **P1** |
| **Synthetic-as-starting-capital** | Fixes synthetic-enhanced NAV track | Medium | **P2** |
| **Extend IBKR Flex lookback** | Fixes 6 of 10 synthetics | Config change (IBKR website) | **P2** |
| **Output gating (`reliable` flag)** | Defensive — prevents agent from trusting bad numbers | Easy | **P2** |
| **Resolve Plaid security_ids** | Proper symbol resolution for bonds/funds | Medium | **P3** |
| **Populate `brokerage_name`** | Enables per-institution filtering | Medium | **P3** |

## Priority

**High** — the system produces returns 100pp off in the wrong direction. Three independent bugs compound: synthetic cash inflation, futures notional amplification, and Plaid phantom volume. The fixes are well-scoped and independent of each other.
