# F7: Hedge Driver Labels Fix Plan

**Status**: READY FOR REVIEW (v4 — addresses Codex round 3 findings F1/F2/F3)
**Bug**: Driver labels show raw proxy ticker ("DSU") instead of human-readable label like "DSU (BlackRock Debt Strategies)"
**Severity**: Display-only — hedging logic works correctly, only labels are wrong

---

## Root Cause

Two independent label-resolution paths both fail for **self-proxy tickers** — tickers where `portfolio.yaml` sets `industry: <same ticker>` (e.g., DSU uses `industry: DSU` instead of a sector ETF like KCE).

### Path 1: `_build_risk_drivers()` in `core/result_objects/risk.py:1022-1051`

```
industry_betas = self._build_industry_group_betas_table()
# ↓ calls _build_industry_group_betas_table() which calls:
#   get_etf_to_industry_map() → reverses industry_to_etf.yaml: {ETF: Industry}
#   format_ticker_with_label(ticker, cash_positions, industry_map)
# DSU is not an ETF *value* in industry_to_etf.yaml → not in reverse map → returns raw "DSU"
```

At line 1046: `info["label"] if info else industry_key` — since `labeled_etf` is just "DSU" (no parenthetical), the label falls through as the raw ticker.

**Critical bug in this path**: The YAML fallback in `get_etf_to_industry_map()` (line 32) does `{etf: industry for industry, etf in industry_to_etf.items()}`. For structured YAML entries like `Silver: {etf: SLV, asset_class: commodity}`, the value is a dict (not a string), so using it as a dict key raises `TypeError: unhashable type: 'dict'`. The bare `except:` at line 33 silently catches this, meaning the **entire YAML fallback path is broken** — it always falls through to the 14-entry hardcoded fallback. Any ETF not in those 14 entries (SLV, REM, IGV, KIE, XOP, ITA, DSU, etc.) gets a raw ticker label when DB is unavailable.

### Path 2: `_etf_to_sector_label()` in `services/factor_intelligence_service.py:1563-1571`

```python
_etf_to_sector: Dict[str, List[str]] = {}
# Built by reversing industry_map via _extract_proxy_ticker() — handles structured entries correctly
# DSU not found → _etf_to_sector_label("DSU") returns "DSU" (the raw key)
```

This path feeds `driver.label` into the hedge tool frontend via `HedgeTool.tsx:337` (`driverLabel: driver.label`). It uses `load_industry_etf_map()` from `core/proxy_builder.py` and correctly handles structured YAML entries via `_extract_proxy_ticker()`. However, it does **not** consult `cash_positions` — unlike Path 1 which calls `format_ticker_with_label(ticker, cash_positions, industry_map)`. If SGOV surfaces as a driver in the hedge tool (via `industry_variance.percent_of_portfolio`), it would get the raw label "SGOV" instead of "Cash Proxy".

### Why self-proxy tickers exist

DSU is a BlackRock Debt Strategies Fund (closed-end bond fund). Its FMP industry is "Asset Management - Bonds", which maps to KCE in `industry_to_etf.yaml`. But `portfolio.yaml` assigns `industry: DSU` (self-proxy) because the proxy builder determined DSU's returns are better modeled by its own price history than by KCE. The label system doesn't know what "DSU" means as an industry — it only knows the reverse of `industry_to_etf.yaml`.

---

## Affected Tickers Audit

Cross-referencing all `industry:` values in `config/portfolio.yaml` against `config/industry_to_etf.yaml` ETF values.

**Important**: The YAML reversal in `get_etf_to_industry_map()` is broken for structured entries (see Root Cause above). "In YAML as ETF value?" only matters for Path 2 (`_etf_to_sector_label`), which handles structured entries correctly. For Path 1, any ETF not in the 14-entry hardcoded fallback is broken when DB is unavailable.

| Stock | Industry Proxy | In YAML as ETF value? | Structured entry? | In hardcoded fallback? | In cash_positions? | Path 1 Label (no DB) | Path 2 Label |
|-------|---------------|----------------------|-------------------|----------------------|-------------------|---------------------|-------------|
| SGOV  | SGOV          | No                   | N/A               | No                   | Yes               | OK — "Cash Proxy" | **BROKEN — raw "SGOV"** (no cash check) |
| DSU   | DSU           | No                   | N/A               | No                   | No                | **BROKEN** | **BROKEN** |
| SLV   | SLV           | Yes (Silver)         | Yes (structured)  | No                   | No                | **BROKEN** (YAML reversal crashes on structured entries) | OK — "Silver" |
| EQT   | XOP           | Yes                  | Yes (structured)  | No                   | No                | **BROKEN** (same) | OK |
| IGIC  | KIE           | Yes                  | No (simple)       | No                   | No                | **BROKEN** (not in 14-entry fallback) | OK |
| IT    | XLK           | Yes                  | No (simple)       | Yes (XLK→Technology) | No                | OK | OK |
| KINS  | KIE           | Yes                  | No (simple)       | No                   | No                | **BROKEN** | OK |
| MSCI  | KCE           | Yes                  | No (simple)       | Yes (KCE→Capital Markets) | No           | OK | OK |
| NVDA  | SOXX          | Yes                  | No (simple)       | Yes (SOXX→Semiconductors) | No           | OK | OK |
| RNMBY | ITA           | Yes                  | No (simple)       | No                   | No                | **BROKEN** | OK |
| SFM   | XLP           | Yes                  | No (simple)       | Yes (XLP→Consumer Staples) | No          | OK | OK |
| STWD  | REM           | Yes                  | Yes (structured)  | No                   | No                | **BROKEN** | OK |
| TKO   | XLC           | Yes                  | No (simple)       | Yes (XLC→Communication Services) | No   | OK | OK |
| V     | KCE           | Yes                  | No (simple)       | Yes (KCE→Capital Markets) | No           | OK | OK |
| MSFT  | IGV           | Yes                  | No (simple)       | No                   | No                | **BROKEN** | OK |
| AAPL  | XLK           | Yes                  | No (simple)       | Yes (XLK→Technology) | No                | OK | OK |

**Currently broken in production (both paths, DB available)**: DSU is the only ticker currently displaying a raw code — it is not in the `industry_proxies` DB table, so both DB-first lookups return no match. (SGOV is an edge case — see below.)

**Broken in no-DB mode (Path 1)**: DSU, SLV, KIE, IGV, ITA, XOP, REM, and any future self-proxy or ETF not in the 14-entry hardcoded fallback (7+ tickers). The YAML fallback at `get_etf_to_industry_map()` line 32 uses a bare dict comprehension `{etf: industry for industry, etf in industry_to_etf.items()}` that assumes every YAML value is a scalar ticker string. But the YAML has structured entries (dicts with `etf`/`asset_class`/`group` keys) at lines 150 (XOP), 260 (KCE for Asset Management - Bonds), 364 (IGV is simple but surrounded by structured entries), etc. When the value is a dict, using it as a dict key raises `TypeError: unhashable type: 'dict'`. The bare `except:` at line 33 catches this silently, meaning the **entire YAML fallback path is broken** for any file containing structured entries — it always falls through to the 14-entry hardcoded fallback. Any proxy ETF not in those 14 entries gets a raw ticker label.

**Additionally affected portfolio proxies missing from fallback**: SLV (Silver), REM (Financial - Mortgages), IGV (Software - Services), KIE (Insurance - Specialty), XOP (Oil & Gas E&P), ITA (Aerospace & Defense) — all used in `config/portfolio.yaml` but absent from the hardcoded fallback at `utils/etf_mappings.py:35`.

**SGOV edge case**: SGOV is handled by `cash_positions` in Path 1 (risk table), but Path 2 (hedge tool's `_etf_to_sector_label`) does not consult cash positions. If SGOV appears as an industry driver in the hedge tool, it shows the raw ticker. Fix: add a cash-position guard to `_etf_to_sector_label`.

**Future-proofing**: Any new holding that gets a self-proxy assignment in `portfolio.yaml` will hit the same bug. The fix should handle the general case, not just DSU.

---

## Fix Strategy

Per project rule ("add the variant to the existing DB table and YAML config — NOT by writing Python alias dicts"):

### Step 1: Fix YAML reversal in `utils/etf_mappings.py`

The YAML fallback at line 32 crashes on structured entries. Fix the reversal to handle both formats:

```python
# Current (broken):
return {etf: industry for industry, etf in industry_to_etf.items()}

# Fixed:
etf_to_industry = {}
for industry, mapping in industry_to_etf.items():
    if isinstance(mapping, dict):
        etf_ticker = mapping.get("etf", "")
    else:
        etf_ticker = mapping
    etf_ticker = str(etf_ticker or "").strip().upper()
    if etf_ticker:
        # First industry wins (don't overwrite with subindustry)
        etf_to_industry.setdefault(etf_ticker, industry)
return etf_to_industry
```

Note: `setdefault` ensures the first (broadest) industry name wins when multiple industries map to the same ETF. For example, KIE maps from "Insurance - Specialty", "Insurance - Reinsurance", etc. — the first one encountered in YAML order wins. This matches the behavior of Path 2's `_etf_to_sector_label`, which prefers broad labels (ones without " - " in the name) when available. Since the YAML doesn't have a bare "Insurance" entry for KIE, the first sub-entry ("Insurance - Specialty") will be used, which is more specific than generic "Insurance" but accurately reflects the YAML data.

**Known pre-existing limitation (duplicate-ETF ordering in DB path)**: The `setdefault` fix only addresses the YAML fallback path. The DB path has a separate, pre-existing ordering issue: `get_etf_to_industry_map()` at `utils/etf_mappings.py:17` queries `industry_proxies` via an unordered query (`inputs/database_client.py:2971`), and the bulk migrator (`admin/migrate_reference_data.py:113`) writes every YAML row into the DB, so duplicate ETFs (KCE, KIE, REM, IGV) are collapsed with last-write-wins semantics — which industry label "wins" depends on arbitrary row ordering. This is NOT introduced by this fix and is NOT in scope here. The DSU fix only adds a single new row with a unique ETF ticker, so it is unaffected by the duplicate-ETF ordering problem. The broader duplicate-ETF label stability issue should be tracked separately (e.g., deterministic ordering via `ORDER BY` + `setdefault` on the DB path, or a priority column).

### Step 2: Add self-proxy entries to `config/industry_to_etf.yaml`

Add DSU as an ETF value so both reverse lookup paths find it. The `group:` field is **mandatory** — every ETF in this map enters the industry universe at `core/factor_intelligence.py:573` (via `load_industry_etf_map()`). Omitting `group:` would change factor-intelligence behavior: DSU would appear in the industry set without a grouping classification, potentially altering hedge candidates and grouping. Related bond entries (e.g., `Asset Management - Bonds` at line 260) use `group: sensitive`.

```yaml
# Self-proxy labels — closed-end funds that serve as their own industry proxy
BlackRock Debt Strategies:
  etf: DSU
  asset_class: bond
  group: sensitive
```

This gives the reverse lookup: `DSU → "BlackRock Debt Strategies"`. Through `format_ticker_with_label()`, the displayed label becomes `"DSU (BlackRock Debt Strategies)"`.

### Step 3: Update hardcoded fallback in `utils/etf_mappings.py:35-50`

With the YAML reversal fixed (Step 1), the hardcoded fallback should rarely be reached. But it should still cover all proxy ETFs used in `portfolio.yaml` as a safety net. Add missing entries with labels that match what the YAML actually maps them to (first entry wins in YAML order):

Current fallback has 14 entries. Missing proxy ETFs used in `portfolio.yaml`:
- `SLV` → "Silver" (YAML: `Silver: {etf: SLV, asset_class: commodity}`)
- `REM` → "Financial - Mortgages" (YAML: `Financial - Mortgages: REM` at line 249; `REIT - Mortgage: {etf: REM, ...}` at line 332 comes later)
- `IGV` → "Software - Services" (YAML: `Software - Services: IGV` at line 364; `Software - Infrastructure: IGV` at line 365)
- `KIE` → "Insurance - Specialty" (YAML: first KIE entry is `Insurance - Specialty: KIE` at line 243)
- `XOP` → "Oil & Gas Exploration & Production" (YAML: `Oil & Gas Exploration & Production: {etf: XOP, ...}` at line 149)
- `ITA` → "Aerospace & Defense" (YAML: `Aerospace & Defense: ITA` at line 287)
- `DSU` → "BlackRock Debt Strategies" (from new YAML entry in Step 2)

Add these 7 entries (including SLV) to the hardcoded fallback dict.

**Label rationale**: Fallback labels use the first YAML entry that maps to each ETF, matching the `setdefault` behavior in the fixed YAML reversal (Step 1). These are the specific industry names from the YAML, not generic summaries. If broader labels were used instead (e.g., "Software" for IGV, "Insurance" for KIE), they would diverge from what the fixed YAML path returns, causing inconsistent labels depending on whether DB/YAML/fallback was used.

### Step 4: Add SGOV guard to hedge-tool label path

In `services/factor_intelligence_service.py`, the `_etf_to_sector_label` function (line 1563) does not consult `cash_positions` (unlike Path 1 which uses `format_ticker_with_label`). Add a cash-position check so SGOV gets "Cash Proxy" instead of raw "SGOV" if it surfaces as a driver:

```python
def _etf_to_sector_label(etf_ticker: Any) -> str:
    label_key = str(etf_ticker or "").strip().upper()
    # Check cash proxy first
    if is_cash_ticker(label_key):
        return "Cash Proxy"
    sector_names = _etf_to_sector.get(label_key, [])
    broad = [s for s in sector_names if " - " not in s]
    if broad:
        return broad[0]
    if sector_names:
        return sector_names[0]
    return label_key
```

Uses `is_cash_ticker()` from `portfolio_risk_engine.portfolio_config` (line 72, the shared predicate established in the Cash Semantics Optimizer Fix, `b5ff9122`). This avoids importing `get_cash_positions()` and its heavy dependency chain.

### Step 5: Database sync (MANDATORY — NOT OPTIONAL)

Both label paths are DB-first:
- **Path 1**: `get_etf_to_industry_map()` at `utils/etf_mappings.py:17` queries the DB and only falls to YAML/hardcoded if the DB call raises.
- **Path 2**: `load_industry_etf_map()` at `core/proxy_builder.py:406` queries the DB identically.

In any environment with a working `industry_proxies` table, YAML-only changes are **IGNORED**. The DB is the primary runtime source — Steps 1-3 (YAML reversal fix, YAML entry, hardcoded fallback) are safety nets for no-DB mode only. Without this DB INSERT, the production hedge tool will still return raw "DSU".

**This step MUST be executed as part of implementation, not deferred.**

```sql
INSERT INTO industry_proxies (industry, proxy_etf, asset_class, sector_group)
VALUES ('BlackRock Debt Strategies', 'DSU', 'bond', 'sensitive')
ON CONFLICT (industry) DO UPDATE SET
  proxy_etf = EXCLUDED.proxy_etf,
  asset_class = EXCLUDED.asset_class,
  sector_group = EXCLUDED.sector_group,
  updated_at = CURRENT_TIMESTAMP;
```

Uses UPSERT (not DO NOTHING) so an existing incomplete row is repaired. The `asset_class` and `sector_group` columns are required — `NULL sector_group` causes the row to be omitted from sector bucket grouping in `core/factor_intelligence.py:119` and `inputs/database_client.py:3253`.

**Note**: After raw SQL changes, restart the `risk_module` service to clear cached sector buckets — `load_industry_buckets()` at `core/factor_intelligence.py:117` caches at process level, and only the managed update paths (`manage_reference_data.py:169`, `migrate_reference_data.py:333`) invalidate caches programmatically.

Or via admin tool (which supports `--asset-class` and `--group` flags per `admin/manage_reference_data.py:321`):
```bash
python admin/manage_reference_data.py industry add "BlackRock Debt Strategies" DSU --asset-class bond --group sensitive
```

**Implementation note**: Add a migration script or startup check that ensures this row exists. Do not rely on manual SQL execution.

---

## Files Changed

| File | Change |
|------|--------|
| `utils/etf_mappings.py` | Fix YAML reversal to handle structured entries (Step 1); add 7 missing ETFs to hardcoded fallback (Step 3) |
| `config/industry_to_etf.yaml` | Add `BlackRock Debt Strategies: { etf: DSU, asset_class: bond, group: sensitive }` entry (Step 2) |
| `services/factor_intelligence_service.py` | Add `is_cash_ticker()` guard to `_etf_to_sector_label()` (Step 4) |

**Python logic changes ARE needed** (correcting v1 claim of "no Python logic changes"):
1. `utils/etf_mappings.py`: YAML reversal dict comprehension must be replaced with a loop that extracts ETF tickers from structured entries
2. `services/factor_intelligence_service.py`: `_etf_to_sector_label()` needs a cash-proxy guard

---

## What This Does NOT Change

- **No code aliases or Python dicts** — follows project rule (the fallback dict is existing, we're adding missing entries)
- **No changes to `portfolio.yaml`** — DSU's self-proxy assignment is correct for risk modeling
- **No changes to `_build_risk_drivers()` logic** — the fallback to `industry_key` is the right behavior for truly unknown tickers; we're just making DSU known and fixing the YAML reversal
- **No changes to hedge recommendation logic** — hedges are already returned correctly (the `_resolve_industry_proxy_ticker` function maps driver labels to proxy tickers separately)

**Note on factor-intelligence impact**: Adding DSU to `industry_to_etf.yaml` means it enters the industry ETF universe at `core/factor_intelligence.py:573` (via `load_industry_etf_map()`). The `group: sensitive` field ensures DSU is classified consistently with related bond entries (e.g., `Asset Management - Bonds` at YAML line 260). Without `group:`, DSU would enter the universe unclassified, which could alter hedge candidate grouping behavior. The `group: sensitive` classification is correct for a closed-end bond fund.

---

## Verification

1. **Unit test — YAML reversal**: Load `industry_to_etf.yaml` directly and call the fixed reversal logic. Assert structured-entry ETFs (SLV, REM, XOP) are present in the result with correct industry labels.
2. **Unit test — fallback**: Mock both DB and YAML to fail, verify the hardcoded fallback includes all 21 entries (14 original + 7 new).
3. **Unit test — get_etf_to_industry_map**: Call `get_etf_to_industry_map()` and assert `"DSU"` is in the returned dict with value `"BlackRock Debt Strategies"`.
4. **Unit test — format_ticker_with_label for DSU**: Call `format_ticker_with_label("DSU", set(), industry_map)` and assert it returns `"DSU (BlackRock Debt Strategies)"` (note: `format_ticker_with_label` at line 76 formats as `"TICKER (Label)"`, NOT bare label).
5. **Integration test — SGOV in hedge path**: `_etf_to_sector_label` is a nested local function inside `_detect_portfolio_risk_drivers()` at `services/factor_intelligence_service.py:1563` and cannot be called directly. Test via the public method: call `FactorIntelligenceService.recommend_portfolio_offsets()` (or equivalent) with a portfolio containing SGOV and verify the returned driver label is `"Cash Proxy"`, not raw `"SGOV"`. Alternatively, refactor `_etf_to_sector_label` to a module-level private function `_etf_to_sector_label()` to enable direct testing — this is a small scope change but makes the guard testable.
6. **Integration test**: Run risk analysis on current portfolio, check `risk_drivers` output — DSU entry should have `label: "DSU (BlackRock Debt Strategies)"` instead of `label: "DSU"`. Note: Path 1 uses `format_ticker_with_label()` which outputs `"TICKER (Label)"` format. Path 2 (`_etf_to_sector_label`) returns the bare industry name — so the hedge tool will show `"BlackRock Debt Strategies"` as the driver label.
7. **Visual check — frontend surfaces**: All driver labels flow from the backend `label` field. This fix is backend-only (YAML + DB). No frontend code changes are needed. Verification: visually confirm "DSU" no longer appears as a raw ticker code in these three surfaces:
   - **Risk view** — risk drivers list, "Top Driver" metric tile
   - **Hedge Analysis** — driver section headers, strategy summaries, "Top Driver" tile
   - **Hedge Workflow Dialog** — "Risk Driver" field, strategy summary

   The key frontend files that consume driver labels are `RiskAnalysis.tsx`, `HedgeTool.tsx`, `HedgeWorkflowDialog.tsx`, `HedgingAdapter.ts`, and `StressTestTool.tsx`. All render the backend-provided `label`/`driverLabel` field — none perform their own label resolution. Exhaustive line-number enumeration is unnecessary for a data-layer fix.
8. **Regression**: Verify existing labels (KCE → "Capital Markets", SLV → "Silver", etc.) are unchanged.

### Manual verification commands

**Production path (DB-first)** — this is the primary runtime path. After Step 5 (DB INSERT), this should return "BlackRock Debt Strategies" for DSU:
```bash
python3 -c "
from utils.etf_mappings import get_etf_to_industry_map
m = get_etf_to_industry_map()
for t in ['DSU', 'KCE', 'SLV', 'REM', 'IGV', 'KIE', 'XOP', 'ITA']:
    print(f'{t}: {m.get(t, \"MISSING\")}')
"
```

**YAML fallback path** — exercises the fixed YAML reversal logic (Step 1) independently of the DB. This verifies the no-DB safety net works for structured YAML entries:
```bash
python3 -c "
from pathlib import Path
import yaml
yaml_path = Path('config/industry_to_etf.yaml')
raw = yaml.safe_load(yaml_path.read_text())
etf_to_industry = {}
for industry, mapping in raw.items():
    if isinstance(mapping, dict):
        etf_ticker = mapping.get('etf', '')
    else:
        etf_ticker = mapping
    etf_ticker = str(etf_ticker or '').strip().upper()
    if etf_ticker:
        etf_to_industry.setdefault(etf_ticker, industry)
for t in ['DSU', 'KCE', 'SLV', 'REM', 'IGV', 'KIE', 'XOP', 'ITA']:
    print(f'{t}: {etf_to_industry.get(t, \"MISSING\")}')
"
```

Note: The DB path is what matters in production. The YAML fallback is a safety net for no-DB mode (Phase A Step 1). Both paths should be tested, but DB verification is the primary gate.

---

## Scope & Risk

- **Scope**: Small — 3 files + 1 DB migration, ~15 lines of Python logic + ~4 lines of YAML + ~7 lines of fallback dict + 1 SQL INSERT
- **Risk**: Low — YAML reversal fix is a targeted loop replacement; SGOV guard uses existing `is_cash_ticker()` predicate; DB sync is a single INSERT; `group: sensitive` matches existing bond entry classification
- **DB step is mandatory**: Without the DB INSERT, the production fix does not work (both label paths are DB-first)
- **Frontend verification**: Backend-only data fix — all frontend surfaces consume the backend `label` field. Visual spot-check on Risk view, Hedge Analysis, and Hedge Workflow Dialog is sufficient
- **Pre-existing limitation acknowledged**: Duplicate-ETF label ordering in DB path (KCE, KIE, REM, IGV) is a separate issue not introduced or addressed by this fix
- **Estimated Codex rounds**: 2-3
