# Estimate Collection Failure Tracking

## Context

The estimate collection script processes ~4,900 tickers per monthly run. Some tickers consistently fail (no income statement, no estimates, API errors). Currently failures are:
- Collected in a `failures` list during the run
- Joined into a single `error_message` TEXT field on `snapshot_runs` (capped at 20 entries)

This is not queryable — you can't ask "which tickers have failed across multiple runs?" or "what's the most common failure reason?" We want a structured `collection_failures` table that:
1. Records every failure with ticker, error type, and message
2. Enables auditing across runs (which tickers consistently fail and why)
3. Eventually feeds a skip list to pre-filter the universe (if a ticker fails N consecutive runs, stop trying)

## Changes

### 1. Schema: `collection_failures` table

Add to `fmp/scripts/create_fmp_data_schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS collection_failures (
    id SERIAL PRIMARY KEY,
    run_id INTEGER REFERENCES snapshot_runs(id),
    ticker TEXT NOT NULL,
    period TEXT CHECK (period IS NULL OR period IN ('annual', 'quarter')),
    error_type TEXT NOT NULL CHECK (error_type IN ('no_income_statement', 'no_estimates', 'api_error', 'unknown')),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cf_ticker ON collection_failures(ticker);
CREATE INDEX IF NOT EXISTS idx_cf_run_id ON collection_failures(run_id);
CREATE INDEX IF NOT EXISTS idx_cf_error_type ON collection_failures(error_type);
```

Error types (canonical values, enforced by CHECK constraint):
- `no_income_statement` — `_ReportedDateLookupFailed` (ticker has no income statement data)
- `no_estimates` — estimate fetch returned zero forward rows (ticker has no analyst coverage for this period)
- `api_error` — `FMPAPIError` or `FMPRateLimitError` from the FMP client
- `unknown` — any other exception type (non-API errors)

`period` is nullable (with CHECK constraint) — `no_income_statement` failures happen before we get to periods.

### 2. EstimateStore: `record_failure()` and `get_failure_summary()` methods

In `fmp/estimate_store.py`:

```python
def record_failure(self, run_id: int, ticker: str, error_type: str,
                   period: str | None = None, error_message: str | None = None) -> None:
    """Record a per-ticker collection failure."""

def get_failure_summary(self, min_runs: int = 1) -> list[dict[str, Any]]:
    """Return tickers with failures grouped by (ticker, period, error_type), ordered by distinct run count.

    Returns per row: ticker, period, error_type, distinct_run_count, total_failure_count,
                     latest_run_id, latest_error_message
    Filters to groups that have failed in at least min_runs distinct runs.

    Grouping includes period so skip-list logic can evaluate annual vs quarter
    independently (e.g. a ticker might have quarterly estimates but not annual).
    The primary metric is distinct_run_count (how many separate runs a ticker/period
    failed in), which is the relevant signal for skip-list decisions.
    """
```

### 3. Snapshot script: record failures as they happen

In `fmp/scripts/snapshot_estimates.py`, at the failure points:

**Ticker-level exception handler (line ~478)** — split into specific and generic cases. The outer `except Exception` currently catches both `_ReportedDateLookupFailed` and any other unexpected error. Refactor to handle both:
```python
except _ReportedDateLookupFailed as exc:
    failed += 1
    failures.append(f"{ticker}: {exc}")
    store.record_failure(run_id, ticker, "no_income_statement", error_message=str(exc))
except Exception as exc:
    failed += 1
    failures.append(f"{ticker}: {exc}")
    error_type = "api_error" if isinstance(exc, (FMPAPIError, FMPRateLimitError)) else "unknown"
    store.record_failure(run_id, ticker, error_type, error_message=str(exc))
```

This ensures every ticker-level failure is recorded — `_ReportedDateLookupFailed` as `no_income_statement`, FMP errors as `api_error`, anything else as `unknown`.

**Per-period estimate failure (line ~465)** — classify by exception type:
```python
except Exception as exc:
    error_type = "api_error" if isinstance(exc, (FMPAPIError, FMPRateLimitError)) else "unknown"
    period_failures.append(f"{ticker}/{period}: {exc}")
    store.record_failure(run_id, ticker, error_type, period=period, error_message=str(exc))
```

**Zero forward estimates** — after a successful fetch, if no forward estimates exist. Covers both the case where the API returned estimates but none are forward, AND the case where the API returned empty data:
```python
if not forward:
    store.record_failure(run_id, ticker, "no_estimates", period=period,
                         error_message=f"0 forward estimates (total={len(estimates)})")
```

This captures:
- `total=0`: API returned nothing (no analyst coverage at all)
- `total=12`: API returned estimates but all are historical (no forward periods)

### 4. Keep existing `error_message` on `snapshot_runs`

The `failures` list and `error_message` field on `snapshot_runs` remain as-is for quick run-level summaries. The new table provides the queryable detail.

## Files to modify

| File | Change |
|---|---|
| `fmp/scripts/create_fmp_data_schema.sql` | Add `collection_failures` table with CHECK constraints + indexes |
| `fmp/estimate_store.py` | Add `record_failure()` and `get_failure_summary()` methods |
| `fmp/scripts/snapshot_estimates.py` | Call `store.record_failure()` at all three failure points with proper error_type classification |
| `tests/fmp/test_estimate_store.py` | Test `record_failure()` insert + `get_failure_summary()` grouping by (ticker, period, error_type), verify `period` is returned in output, test min_runs filtering distinguishes annual vs quarter failures |
| `tests/fmp/test_snapshot_estimates_script.py` | Add mocked-store test for `run_collection` failure paths verifying `record_failure()` is called with correct error_type and period |

## Verification

1. Apply schema: `_ensure_schema()` runs on write-mode init, so the table is created automatically
2. Run tests: `python3 -m pytest tests/fmp/test_estimate_store.py tests/fmp/test_snapshot_estimates_script.py -v`
3. Run a small collection: `python3 fmp/scripts/snapshot_estimates.py --universe-limit 20 --force --no-resume`
4. Query failures: `SELECT ticker, period, error_type, count(DISTINCT run_id) AS runs, count(*) AS total FROM collection_failures GROUP BY ticker, period, error_type ORDER BY runs DESC;`
