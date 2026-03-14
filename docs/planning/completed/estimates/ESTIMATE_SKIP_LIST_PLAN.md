# Estimate Collection Skip-List

## Context

The earnings estimate collector records per-ticker failures in the `collection_failures` table but never reads them back to prune the universe on subsequent runs. 142 failures from run 1 — all `no_estimates` (95 tickers) or `no_income_statement` (6 tickers), zero `api_error`. These are warrants, preferred shares, Toronto-listed, and micro-caps with no analyst coverage. They get re-attempted every monthly run with the same result.

The `get_failure_summary(min_runs=N)` method already exists and returns exactly what we need. The plan doc originally said "eventually feeds a skip list" but it was never implemented.

**Repo note:** The live collector runs on EC2 from the `edgar_updater` repo (`~/Documents/Jupyter/edgar_updater/`). The local `fmp/scripts/snapshot_estimates.py` is a deprecated copy — NOT modified by this plan. The `EstimateStore` class exists in both repos and should stay in sync.

---

## Changes

### 1. Add `get_skip_set()` method to `EstimateStore`

**Files:** `edgar_updater/estimates/store.py` + `fmp/estimate_store.py` (sync copy, has "Keep behavior aligned" note)

New method that returns a `set[str]` of tickers to skip:

```python
def get_skip_set(
    self,
    min_runs: int = 2,
    error_types: tuple[str, ...] = ("no_estimates", "no_income_statement"),
    max_age_days: int = 180,
) -> set[str]:
    """Return tickers that have failed with persistent (non-transient) errors across N+ runs within the lookback window."""
```

SQL (cutoff date computed in Python via `timedelta`, matching existing `get_revision_summary()` pattern):

```python
cutoff = _utc_now() - timedelta(days=max_age_days)
```

```sql
SELECT ticker
FROM collection_failures
WHERE error_type = ANY(%s)
  AND created_at >= %s
GROUP BY ticker
HAVING COUNT(DISTINCT run_id) >= %s
ORDER BY ticker
```

Parameters: `(list(error_types), cutoff, min_runs)`

Design decisions:
- **Groups by ticker only** (ignores `period`). A ticker that fails `no_estimates` for `quarter` but succeeds for `annual` still gets skipped — pragmatically correct since these are warrants/preferred/micro-caps that fail across the board. Avoids complexity of period-aware skip tuples.
- **`max_age_days=180` decay window**. Only considers failures from the last 6 months. If a micro-cap gains analyst coverage, old failures age out and the ticker re-enters the universe automatically. No manual reset needed.
- Does NOT skip `api_error` or `unknown` — those are transient and should always be retried.
- Default `min_runs=2` means a ticker must fail on 2+ separate runs before being skipped (gives every ticker a second chance).

### 2. Wire skip-list into `run_collection()`

**File:** `edgar_updater/estimates/collector.py`

Insert after universe build (after `store.create_run()` or resume restoration) and before the freshness check. Applied to the in-memory `universe` list only — the stored `universe_snapshot` in `snapshot_runs` is NOT modified, preserving the original universe for auditability and correct resume behavior (on resume, the full universe is reloaded from DB and skip-list re-filters).

```python
# Skip-list: remove tickers with persistent failures
skip_set = set()
if not args.ignore_skip_list:
    skip_set = store.get_skip_set(min_runs=args.skip_min_runs)
    if skip_set:
        before = len(universe)
        universe = [t for t in universe if t not in skip_set]
        print(
            f"[skip-list] removed {before - len(universe)} tickers "
            f"(persistent failures across {args.skip_min_runs}+ runs)",
            file=sys.stderr,
        )
```

Placement: after both universe-build paths converge (fresh run + resume-completed-start-new-run), before the freshness map build (line ~425). Both code paths end before this point, so the skip-list filter applies regardless of how the universe was constructed.

### 3. Add CLI flags

**File:** `edgar_updater/estimates/collector.py` `build_parser()`

```python
parser.add_argument(
    "--ignore-skip-list", action="store_true",
    help="Ignore persistent failure skip-list (re-attempt all tickers)",
)
parser.add_argument(
    "--skip-min-runs", type=int, default=2,
    help="Min failing runs before a ticker is skipped (default: 2)",
)
```

### 4. Sync `get_skip_set()` to risk_module local copy

**File:** `risk_module/fmp/estimate_store.py`

Both copies of `EstimateStore` have a sync note: "Keep behavior aligned when either side changes." Add the identical `get_skip_set()` method to the risk_module copy. This keeps the two in sync and allows the `/api/estimates/failures` endpoint (which uses the local copy) to potentially expose the skip-set in the future.

**How to sync:** Copy the `get_skip_set()` method verbatim from `edgar_updater/estimates/store.py` to `risk_module/fmp/estimate_store.py`. Place it after `get_failure_summary()`. Verify `_utc_now()` and `timedelta` are already imported (they are — see lines 26-27 and the `datetime` import at line 9).

---

## Files Changed

| Repo | File | Change |
|------|------|--------|
| edgar_updater | `estimates/store.py` | Add `get_skip_set()` method |
| edgar_updater | `estimates/collector.py` | Wire skip-list after universe build, add 2 CLI flags |
| risk_module | `fmp/estimate_store.py` | Add `get_skip_set()` method (sync copy) |

**NOT changed:** `risk_module/fmp/scripts/snapshot_estimates.py` (deprecated local copy, not deployed).

---

## Verification

1. Unit test `get_skip_set()` locally against the risk_module copy: insert failures for same ticker across 2 run_ids → verify in skip set. Insert 1 failure only → verify NOT in skip set. Insert failure older than `max_age_days` → verify NOT in skip set.
2. After deploying to EC2, dry-run: `python -m estimates.collector --universe-limit 10` to verify skip-list log output.
3. Run with `--ignore-skip-list` to confirm bypass works.
4. After run 2 on EC2, the 95 persistent-failure tickers get a second chance. After run 3, they'll be auto-skipped. After 6 months without new failures, they age out and re-enter the universe.

---

## Codex Review Log

| Round | Result | Notes |
|-------|--------|-------|
| R1 | FAIL | Missing explicit SQL, wrong file paths (referenced edgar_updater from risk_module context), no decay/reset mechanism for stale failures |
| R2 | FAIL | SQL `INTERVAL '%s days'` doesn't work with psycopg2 params — use Python `timedelta` instead. Placement description said "after universe_limit" but should say "after resume block converges." `Edgar_updater` → `edgar_updater` case. |
| R3 | PASS | SQL timedelta pattern matches existing code, placement correct at line ~425, all R1/R2 fixes verified |
