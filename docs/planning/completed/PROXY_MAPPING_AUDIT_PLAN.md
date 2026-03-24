# Proxy Mapping Audit & Fixes

## Context

Industry/sector → ETF proxy mappings drive factor analysis, risk decomposition, and stress tests. 174 industry mappings + 14 exchange mappings (42 exchange-factor rows) in YAML/DB. The system uses a 3-tier fallback: DB → YAML → hardcoded. Mappings were built incrementally and hadn't been audited systematically.

---

## Audit Findings

### Industry Coverage: CLEAN
Tested 100+ tickers (large-cap, small-cap, international ADRs, REITs, energy, biotech, utilities) — **zero unmapped industries**. All FMP industry strings have corresponding YAML/DB entries. Many-to-one mappings (e.g., 15 industrials → XLI) are intentional sub-industry rollups, not duplicates.

### Exchange Proxy ETFs: ONE STALE, FIVE LATE-START

| ETF | Exchange | Factor | Data Points | Last Date | Status |
|-----|----------|--------|-------------|-----------|--------|
| SPY, MTUM, IWD | US | market/mom/val | 1254 | 2026-03-20 | OK |
| ACWX, IMTM, EFV | Intl | market/mom/val | 1254 | 2026-03-20 | OK |
| EWJ, EWJV | Japan | market/val | 1254 | 2026-03-20 | OK |
| VGK, EWU | Europe/UK | market | 1254 | 2026-03-20 | OK |
| EEM | EM | market | 1254 | 2026-03-20 | OK |
| **EMFM** | **HKEX** | **momentum** | **803** | **2025-06-11** | **STALE** |
| EEMO | SSE/SZSE/NSE/TADAWUL | momentum | 1254 | 2026-03-20 | OK |
| DGS | HKEX | value | 1254 | 2026-03-20 | OK |
| EMVL.L | SSE/SZSE/NSE/TADAWUL | value | 1260 | 2026-03-23 | OK |
| INDA, KSA | India/Saudi | market | 1254 | 2026-03-20 | OK |

**EMFM** (Global X MSCI Next EM & Frontier Momentum) stopped getting FMP data after June 2025. Used for HKEX momentum. Replace with **EEMO** (Invesco S&P EM Momentum) which has full coverage and is already used for SSE/SZSE/NSE/TADAWUL.

**Late-start proxies** (flagged by `verify_proxies.py`, low priority — limited history but not stale): BITQ, ETHA, IBIT, SEA, SGOV. These are newer ETFs with shorter histories. No action needed now — they'll accumulate more history over time.

### Cache Invalidation: NEEDED
Changing HKEX momentum proxy affects two caches:
1. **`factor_proxies` DB table** — per-portfolio cached proxy rows. `ensure_factor_proxies()` only rebuilds missing/incomplete rows; existing complete rows with EMFM are returned untouched. Need to delete affected rows so they regenerate with EEMO.
2. **Workflow snapshot cache** — 30s TTL in-memory cache in `services/portfolio/workflow_cache.py`. The admin sync path clears service caches via `ServiceManager`, but `clear_workflow_snapshot_caches()` is not registered there. Practically low-risk (30s TTL auto-expires), but should be noted in the maintenance doc.

### Stale Peer Lists: NEEDS MECHANISM
GPT-generated peers in `subindustry_peers` table have no TTL or refresh mechanism. `ensure_factor_proxies()` reuses cached peers without age check. Peers generated once are cached forever.

### Process Documentation: MISSING
No documented workflow for how to update mappings, when to review them, or how to sync YAML → DB.

---

## Implementation Plan

### Step 1: Fix EMFM → EEMO in exchange proxies

**File: `config/exchange_etf_proxies.yaml`**

Change HKEX momentum from EMFM to EEMO:
```yaml
HKEX:
  market: EEM
  momentum: EEMO    # was EMFM (stale, no data after 2025-06)
  value: DGS
```

### Step 2: Invalidate cached factor_proxies for HKEX tickers

After YAML edit, existing `factor_proxies` DB rows for HKEX-listed tickers will still have `momentum_proxy = 'EMFM'`. Two options:

**Option A (recommended)**: Add a note in the maintenance doc that after changing an exchange proxy, affected `factor_proxies` rows should be deleted so they regenerate:
```sql
DELETE FROM factor_proxies WHERE momentum_proxy = 'EMFM';
```

**Option B**: If DB is accessible, run the SQL directly. If not, document as a manual post-deploy step.

The 30s workflow snapshot cache auto-expires and doesn't need manual invalidation.

### Step 3: Sync YAML to DB

Use the bulk sync command (preferred over per-row add):
```
PYTHONPATH=/path/to/risk_module python admin/manage_reference_data.py exchange sync-from-yaml
```

Or document as a manual step if DB is not accessible in this session.

### Step 4: Add peer staleness check to `verify_proxies.py`

Add a `--check-peers` flag that:
- Queries `subindustry_peers` table for entries older than N months (default 12)
- Reports count and oldest entries
- Suggests regeneration for stale peers

Small addition (~30 lines) to the existing verification script.

### Step 5: Document `verify_proxies.py` PYTHONPATH requirement

The script fails because `fmp.cache` resolves from the sibling `-dist` package instead of the local source. The script already has `sys.path.append` at line 46-47, but this doesn't override the dist package already on the shell profile's path. This is a PYTHONPATH issue, not a code fix — run as:
```
PYTHONPATH=/path/to/risk_module python admin/verify_proxies.py --detailed
```
Document this in the maintenance guide.

### Step 6: Document proxy maintenance process

Add `docs/guides/PROXY_MAPPING_MAINTENANCE.md` with:
- When to review mappings (quarterly, or when adding new exchanges/industries)
- How to add a new industry mapping (edit YAML → sync to DB → verify)
- How to add a new exchange mapping (edit YAML → `exchange sync-from-yaml` → verify)
- How to verify coverage (`PYTHONPATH=. python admin/verify_proxies.py --detailed`)
- How to check for stale peers (`admin/verify_proxies.py --check-peers`)
- How to regenerate stale peers (delete from `subindustry_peers` table → auto-regenerate on next analysis)
- How to invalidate cached factor_proxies after proxy changes (`DELETE FROM factor_proxies WHERE momentum_proxy = 'OLD_ETF'`)
- Note about late-start ETFs (BITQ, ETHA, IBIT, SEA, SGOV) — no action needed, they accumulate history over time

### Step 7: Update TODO

Mark audit items as done, note EMFM fix and documentation.

---

## File Change Summary

| File | Change |
|------|--------|
| `config/exchange_etf_proxies.yaml` | EMFM → EEMO for HKEX momentum |
| `admin/verify_proxies.py` | Add `--check-peers` flag (~30 lines) |
| `docs/guides/PROXY_MAPPING_MAINTENANCE.md` | New — maintenance process documentation |
| `docs/TODO.md` | Update audit status |

---

## Verification

1. Verify EEMO has data: confirmed 1254 data points via FMP
2. `pytest tests/services/test_factor_proxies.py -x -q` — no regressions from YAML change
3. Run `PYTHONPATH=. python admin/verify_proxies.py --detailed` — all ETFs should show OK (EMFM gone)
4. Full suite: `pytest -x -q` — no regressions

---

## What's NOT needed (audit confirmed clean)

- Industry coverage gaps — zero gaps across 100+ tickers
- Duplicate industry entries — many-to-one is intentional
- Mapping quality — ETFs are reasonable choices for their sectors
- Geographic proxy granularity — A-shares using EEM is coarse but standard for factor models at this scale
- Late-start ETF replacements — BITQ, ETHA, IBIT, SEA, SGOV will accumulate history naturally
