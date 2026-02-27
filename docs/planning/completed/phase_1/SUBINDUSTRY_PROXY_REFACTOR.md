# Sub-Industry Proxy Refactor

Implementing Global Sub-Industry Proxy Cache & Incremental Portfolio-Level Proxy Generation

---

## 1  Background

* Each stock needs a set of factor proxies (market, momentum, value, industry, sub-industry peers).
* Exchange- and industry-level proxies are already stored in reference tables. Sub-industry peers are generated on-the-fly via GPT and stored only in the per-portfolio `factor_proxies` table.
* First analysis of every **new** portfolio pays GPT cost for every ticker—even if another portfolio already produced those peers.
* Multiple API routes contain ad-hoc logic that re-runs `inject_all_proxies`, duplicating work.

## 2  Objectives

1. Introduce a **global reference table** `subindustry_peers` storing peer lists keyed by ticker.
2. Provide a single helper `ensure_factor_proxies` that
   * reads existing rows from `factor_proxies`;
   * for missing tickers, looks up global reference data and, only if necessary, calls GPT;
   * persists any new data to both reference and per-portfolio tables.
3. Replace all direct `inject_all_proxies` calls in API routes and managers with the helper.
4. Preserve analyser logic (still reads `portfolio_data.stock_factor_proxies`).
5. Guarantee no duplicate GPT call for the same ticker across portfolios or users.

## 3  Scope / Deliverables

### A. Database migration
```sql
CREATE TABLE subindustry_peers (
    ticker        VARCHAR(20) PRIMARY KEY,
    peers         JSONB     NOT NULL,
    source        VARCHAR(30) DEFAULT 'gpt',
    generated_at  TIMESTAMP  DEFAULT NOW(),
    updated_at    TIMESTAMP  DEFAULT NOW()
);

CREATE INDEX idx_sub_peers_generated_at ON subindustry_peers(generated_at);
```

### B. Data-access layer (`inputs/database_client.py`)
* `get_subindustry_peers(ticker) -> list[str] | None`
* `save_subindustry_peers(ticker, peers, source='gpt') -> None` (UPSERT)

### C. Service helper

The helper is the single gatekeeper. For every ticker it will:
1. Check if a per-portfolio row already exists in `factor_proxies`. If so, reuse it.
2. Otherwise query the **global** `subindustry_peers` table.
3. If peers are missing and `allow_gpt` is true, call GPT once, then immediately:
   • `save_subindustry_peers` → persist globally so all future portfolios benefit.
   • `save_factor_proxies`   → persist to this portfolio so analysis has a complete set.

This guarantees any brand-new ticker incurs at most one GPT call, and the result is cached at both scopes.

 (`services/factor_proxy_service.py`)
```python
def ensure_factor_proxies(user_id: int,
                          portfolio_name: str,
                          tickers: set[str],
                          allow_gpt: bool = True) -> dict[str, dict]:
    """Return complete proxy dict for portfolio, generating rows only for
    missing tickers.  Persists new data to both subindustry_peers and
    factor_proxies tables."""
```

### D. Code-base integration
1. `PortfolioManager.create_portfolio` – call helper after saving positions.
2. `PortfolioManager.update_portfolio_holdings` – call helper with updated ticker set.
3. Routes `api_analyze_portfolio`, `api_risk_score` – replace legacy `inject_all_proxies` block with helper call.
4. Remove other redundant `inject_all_proxies` calls (keep for CLI/tools only).

### E. Optional maintenance script
* `tools/backfill_subindustry_peers.py` – nightly job filling missing peer lists.

### F. Tests
* Unit tests for helper (cached, partially missing, GPT disabled).
* Integration tests verifying single GPT call per ticker across portfolios.

## 4  Implementation Steps

1. **Migration** – add new table.
2. **DatabaseClient** – implement get/save peer methods.
3. **Helper module** – add `ensure_factor_proxies` with unit tests.
4. **Refactor flows** – portfolio create/update and analysis routes use helper.
5. **Cleanup** – delete legacy proxy code.
6. **Back-fill script** (optional).
7. **Tests** – ensure `pytest -q` passes.
8. **Phased deploy** – migrate DB, then roll out code changes gradually.

## 5  Edge-Cases / Risk Mitigation
* **Concurrency** – use UPSERT (`ON CONFLICT`) to avoid duplicate inserts.
* **DB outage** – helper falls back to GPT path so analysis still works.
* **Manual overrides** – store with `source='manual'`; helper never overwrites manual rows.
* **Ticker removals** – leave rows, soft-delete, or hard-delete via cleanup job.

## 6  Success Criteria
* No API route calls GPT more than once per unique ticker.
* Analysis latency drops after initial run.
* Unit & integration tests pass.
* GPT token spend reduced.
