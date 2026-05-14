# Vals Finance Agent — Production Run Wiring Plan

**Created:** 2026-05-04
**Revised:** 2026-05-04 (r2) — Codex review FAIL → fixed 4 blockers + 5 should-fixes + nits. New file `scripts/run_pair.sh` added; `run.json` contract switched to `await run.fetch_json()` + normalized schema; aggregator made Vals-authoritative w/ left-joined traces; tier function encodes full delta-gated table from run plan §3.4; per-config env assertions; per-category source from `public.csv` not traces.
**Revised:** 2026-05-05 (r3) — Codex r2 FAIL → fixed Decision §4 staleness, added strict normalized-schema validation (fail-fast on missing required fields), corrected `public.csv` join (no `question_id` column — join by normalized question text), unstale'd Verification §3, defined B-variance head-to-head semantics, renamed Config B "stop reason" → "error/status", added `--b-only` opt-out on `run_pair.sh`, validated `HANK_VALS_CONFIG_B_RUN` ∈ {1,2}, parsed `VENDOR_SHA` `sha=` line.
**Revised:** 2026-05-05 (r4) — Codex r3 FAIL → fixed `_safe_attr` `value not in sentinels` set-membership bug (would raise TypeError on dict/list fields like `context`/`tags`/`checks`/`tokens`); added explicit per-type checks + identity check on `dataclasses.MISSING` + `PydanticUndefinedType` name match; added `--skip-b` flag to `run_pair.sh` for correct resume after `--b-only`; specified exact `_normalize` reuse from `scoring_stub.py:24`; added `passed` is `bool` + non-empty `results` validation; updated Decision §5 wording to match r3 error/status rename; Verification §3 now mentions both run1 and run2 dirs; Decision §4 wording clarified to include blank-string treatment.
**Revised:** 2026-05-05 (r5) — Codex r4 FAIL on one should-fix → `--skip-b` preflight gap. Added requirements: `HANK_VALS_RUN_TIMESTAMP` is required (not auto-generated) when `--skip-b`; both `config_b_run{1,2}/{run.json,vals_raw.json}` must exist before launching Config A. Enforced flag mutual exclusion. Added `bash -n scripts/run_pair.sh` to Verification §1.
**Status:** ✅ **CODEX PASS (r5, 2026-05-05)** — ready for implementation per CLAUDE.md plan-first workflow. 5 review rounds across 4 days (r1 FAIL → r5 PASS).
**Implements:** `docs/planning/VALS_FINANCE_AGENT_IMPL_PLAN.md` r5 §4.5 (scripts) + §4.6 (docs)
**Upstream:**
- Sprint envelope: `docs/planning/VALS_FINANCE_AGENT_RUN_PLAN.md`
- Locked impl plan: `docs/planning/VALS_FINANCE_AGENT_IMPL_PLAN.md`
- Day-1 verifications: `docs/research/vals-finance-agent-day1-verifications.md`

---

## Context

The Vals AI Finance Agent benchmark wrapper (`evals/vals-finance-agent/`) was paused 2026-04-23 with the Hank wrapper code shipped (5 commits, Apr 22-23) but the **production run pipeline never built**. Per the impl plan §4.5 + §4.6, the missing pieces are:

- `harness/run_vals_suite.py` — Vals SDK driver: `Suite.from_id` → `suite.run` → persist `await run.fetch_json()` raw + normalized schema
- `scripts/run_config_a.sh` + `scripts/run_config_b.sh` — single-config run wrappers (Config B supports variance-run suffix)
- `scripts/run_pair.sh` — orchestrator that pins one timestamp, runs Config B twice (variance check, impl plan §5.2) + Config A once + aggregates
- `scripts/aggregate_results.py` — Vals `run.json` is authoritative for scoring; left-joins Config A `traces.jsonl` for Hank telemetry; emits `summary.{md,json}` + `run_log.md` skeleton per §3.4.4 + §3.6.2
- `evals/vals-finance-agent/README.md` — operating doc

Without these, the wrapper can only stub-score against gold-answer text similarity (`scoring_stub.py`), which is not the benchmark. The goal of this plan is the minimum addition that lets us execute the Day-4 baseline runs once `VALS_API_KEY`, `TAVILY_API_KEY`, and `SEC_EDGAR_API_KEY` are provisioned and `vendor/finance-agent/` is re-cloned at the pinned SHA (`82337852…`).

**In scope:** 7 files (6 production + 1 doc) + surgical `.env.example` edit. No changes to existing wrapper code.

**Out of scope:**
- Test scaffolding (impl plan §5.1) — follow-up
- Makefile / automation for vendor re-clone — README documents manual steps
- Modeling-studio integration (deferred per impl plan §3.2.8)
- Vals registration / key procurement (operational, not code)
- Re-cloning vendor (operational, README documents)

---

## Decisions made (call out for Codex review)

1. **Single shared `.env`** at `evals/vals-finance-agent/vendor/finance-agent/.env` (existing `.env.example` location), **NOT** per-config `.env.config_a` / `.env.config_b` as drafted in impl plan §4.5.1.
   - **Rationale:** both configs need the same 4 keys (`ANTHROPIC`, `TAVILY`, `SEC_EDGAR`, `VALS`). Config A also needs `FMP`. Setting `FMP_API_KEY` while running Config B is harmless because no Hank tools are loaded in Config B's path. The "keys don't leak" rationale in impl plan §3.5.1 is engineering hygiene with no security delta in our case.
   - **What we add to `.env.example`:** `VALS_API_KEY` (uncomment) + `VALS_SUITE_ID_PUBLIC_50`.
   - If Codex disagrees, switch to per-config files is mechanical (sed-rename + duplicate the example). Flag for review.

2. **CLI shape: `--config <name>` only, no `--model` / `--suite-id` flags.** The config module already pins `MODEL_NAME`; suite ID comes from env var `VALS_SUITE_ID_PUBLIC_50`. Reduces drift between shell args and Python configs (vs the impl plan §4.5.1 sketch which threaded `--model` through the shell).

3. **Vals SDK API uses `Suite.from_id(...)` + `suite.run(...)`.** Day-1 verifications doc Q1 = PASS confirmed these are the documented entry points. `RunParameters` field names (`eval_model`, `heavyweight_factor`, `parallelism`) are still impl-time TBD against installed `vals.sdk` — the Codex implementer is instructed to verify against the actually-installed package and adjust.

4. **REVISED r3 + r4: `run.json` is a normalized schema (not raw Vals serialization).** r2 splits the writer into two files per run: `vals_raw.json` is the lossless `await run.fetch_json()` export (kept for debugging / future re-aggregation if our normalized shape misses a field); `run.json` is a stable v1 schema (`schema_version`, `run_metadata`, `results[]`) that the aggregator depends on. Required fields (`question_id`, `passed`, `final_answer`) are **strict-validated** at write time — `None`, blank/whitespace strings, sentinel values, or wrong-type `passed` (e.g. string `"False"` instead of bool) all abort the run with a clear error rather than serializing silently-bad data. (Codex r2 blocker #2 + r3 should-fix: `_safe_attr` alone could return sentinel/None for required fields and corrupt downstream scoring.)

5. **`aggregate_results.py` slices match impl plan §3.4.4 except filing type:** overall pass rate, per-`Question Type` (9 categories), head-to-head A↔B diff (r3 disambiguates B-variance: `B_pass_stable` / `B_fail_stable` / `B_split`), token/cost/duration distributions, **Config A stop-reason histogram + Config B error/status histogram (renamed r3 — vendor `custom_call` doesn't expose stop_reason for B)**. **Skip filing-type slice** — Q6 unresolved in impl plan; not blocking v1.

6. **Bonus: `aggregate_results.py` also emits `run_log.md` skeleton** per impl plan §3.6.2 (timestamp, Hank repo SHA, vendor SHA, model snapshot, score table). User fills the "delta-from-previous-run" prose section by hand. Optional but cheap and aligns with iteration discipline.

7. **Telemetry asymmetry accepted.** Config A's `custom_call` (`harness/hank_model.py:161`) writes per-question rows to `traces.jsonl`. Config B uses the vendor's vanilla `custom_call` and has no equivalent hook. For v1, `aggregate_results.py` derives Config B per-question telemetry from the Vals `run.json` itself (final answer, judge result, error). The wrapper-comparison story doesn't need full telemetry parity — the value is the score delta, not Config B trace fidelity.

8. **NEW (r2): `run_pair.sh` wrapper added** as the standard one-command Day-4 driver. Codex blocker #1 caught that single-config scripts each generated their own `HANK_VALS_RUN_TIMESTAMP`, scattering output across multiple result dirs. Fix: pin one timestamp in the wrapper, export it, and have single-config scripts **require** it to be pre-exported (fail-fast via `: "${HANK_VALS_RUN_TIMESTAMP:?...}"`). Also adds `HANK_VALS_CONFIG_B_RUN={1,2}` env support so variance reruns land at `config_b_run1/` and `config_b_run2/` (impl plan §5.2 variance check) instead of overwriting.

9. **NEW (r2): Vals SDK import try-order: `from vals import Suite, RunParameters` first, fall back to `vals.sdk.{suite,types}`** (Codex should-fix #4). Newer flatter import path is the documented one per current Vals docs; older `vals.sdk.*` retained for the installed package shape. Codex implementer drops whichever the installed `vals-sdk` version doesn't support.

---

## File-by-file design

### 1. `evals/vals-finance-agent/harness/run_vals_suite.py` (NEW)

Async CLI that drives `vals.sdk.suite.Suite` end-to-end with one of the two configs. Persists **two** files: `vals_raw.json` (whatever `await run.fetch_json()` returns, untouched) and `run.json` (a normalized schema the aggregator depends on).

**Shape:**
```python
# Pseudocode — verify Vals SDK names against vendor venv at impl time
import argparse, asyncio, json, os
from pathlib import Path

from .runtime_paths import ensure_runtime_paths
ensure_runtime_paths()

# Try the newer flat import first, fall back to vals.sdk.* for older installs.
try:
    from vals import Suite, RunParameters  # newer SDK
except ImportError:
    from vals.sdk.suite import Suite
    from vals.sdk.types import RunParameters

NORMALIZED_SCHEMA_VERSION = "1"

async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True,
                        choices=["config_a_hank", "config_b_raw_opus"])
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--parallelism", type=int, default=5)
    parser.add_argument("--output-dir", required=True,
                        help="Directory to write vals_raw.json + run.json")
    parser.add_argument("--eval-model", default="openai/gpt-5.2")
    parser.add_argument("--heavyweight-factor", type=int, default=3)
    args = parser.parse_args()

    suite_id = os.environ["VALS_SUITE_ID_PUBLIC_50"]

    if args.config == "config_a_hank":
        from configs.config_a_hank import get_custom_model, MODEL_NAME
    else:
        from configs.config_b_raw_opus import get_custom_model, MODEL_NAME

    custom_call = await get_custom_model(
        MODEL_NAME,
        {"temperature": 0.0, "max_tokens": 32000},
    )

    suite = await Suite.from_id(suite_id)
    run = await suite.run(
        model=custom_call,
        model_name=args.config,
        run_name=args.run_name,
        parameters=RunParameters(
            eval_model=args.eval_model,
            heavyweight_factor=args.heavyweight_factor,
            parallelism=args.parallelism,
        ),
        wait_for_completion=True,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1) Raw Vals export — authoritative source of truth, no schema drift risk.
    raw = await run.fetch_json()
    (output_dir / "vals_raw.json").write_text(json.dumps(raw, indent=2, default=str))

    # 2) Normalized schema — what the aggregator consumes. Stable across SDK versions.
    test_results = await run.test_results  # documented attribute (verify at impl time)
    normalized_results = [_normalize_result(tr) for tr in test_results]
    _validate_required_fields(normalized_results)  # fail-fast per Codex r2 blocker #2
    normalized = {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "run_metadata": {
            "config": args.config,
            "run_name": args.run_name,
            "model_name": MODEL_NAME,
            "suite_id": suite_id,
            "eval_model": args.eval_model,
            "heavyweight_factor": args.heavyweight_factor,
            "parallelism": args.parallelism,
            "run_id": getattr(run, "id", None),
        },
        "results": normalized_results,
    }
    (output_dir / "run.json").write_text(json.dumps(normalized, indent=2, default=str))
    return 0

REQUIRED_FIELDS = ("question_id", "passed", "final_answer")

def _normalize_result(tr) -> dict:
    return {
        # Vals docs show test_result.input_under_test (Codex r2 blocker #2 — was missing).
        "question_id": _safe_attr(tr, "test_id", "id", "question_id"),
        "question": _safe_attr(tr, "input_under_test", "input", "test_input"),
        "context": _safe_attr(tr, "context", default={}),
        "tags": _safe_attr(tr, "tags", default=[]),
        "category": _safe_attr(tr, "category", "question_type"),
        "final_answer": _safe_attr(tr, "llm_output", "output", "model_output"),
        "passed": _safe_attr(tr, "passed", "pass"),
        "score": _safe_attr(tr, "score"),
        "checks": _safe_attr(tr, "eval_results", "checks", default=[]),
        "error": _safe_attr(tr, "error"),
        "duration_seconds": _safe_attr(tr, "duration_seconds", "duration"),
        "tokens": _safe_attr(tr, "tokens", "token_usage", default={}),
        "cost": _safe_attr(tr, "cost"),
    }

def _validate_required_fields(records: list[dict]) -> None:
    """Fail-fast if records empty, any required field is missing, or `passed` is non-bool.

    Keeps run.json scoring-authoritative (Codex r2 blocker #2 + r3 should-fix).
    """
    if not records:
        raise RuntimeError(
            "Vals run returned 0 results — suite empty or SDK call failed silently. "
            "Inspect vals_raw.json."
        )
    issues: list[str] = []
    for idx, rec in enumerate(records):
        for field in REQUIRED_FIELDS:
            value = rec.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                issues.append(f"row[{idx}].{field} missing/blank")
        # `passed` must be bool, not str like "False" (would corrupt pass-rate math)
        if not isinstance(rec.get("passed"), bool):
            issues.append(f"row[{idx}].passed is not bool (got: {type(rec.get('passed')).__name__})")
    if issues:
        sample = "; ".join(issues[:5])
        raise RuntimeError(
            f"Vals run output validation failed ({len(issues)} issue(s)) — "
            f"e.g. {sample}. Inspect vals_raw.json and update _normalize_result "
            f"field-name candidates or coerce types."
        )

def _safe_attr(obj, *names, default=None):
    """Try multiple attribute/key names (SDK shape varies); fall back to default.

    r4 fix (Codex r3 blocker): use explicit per-type checks rather than `value not in sentinels`,
    which raises TypeError when value is dict/list (e.g. `context`, `tags`, `checks`, `tokens`).
    """
    try:
        from dataclasses import MISSING as _DC_MISSING
    except ImportError:
        _DC_MISSING = object()  # safe fallback; identity check below will never match

    _SENTINEL_TYPE_NAMES = {
        "MissingType", "_MISSING_TYPE",       # dataclasses
        "PydanticUndefinedType", "UndefinedType",  # pydantic v1/v2
    }

    def _is_present(value) -> bool:
        if value is None:
            return False
        if value is _DC_MISSING:
            return False
        if type(value).__name__ in _SENTINEL_TYPE_NAMES:
            return False
        if isinstance(value, str) and not value.strip():
            return False
        # dict/list/tuple/bool/int/float/etc. — present if not None/sentinel
        return True

    for name in names:
        value = None
        if isinstance(obj, dict):
            value = obj.get(name)
        elif hasattr(obj, name):
            value = getattr(obj, name)
        if _is_present(value):
            return value
    return default

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

**Notes:**
- Reuses existing `runtime_paths.ensure_runtime_paths()` to pick up vendor `.venv/site-packages`, repo root, Edgar_updater, agent_gateway.
- Trace logging happens automatically — Config A's `custom_call` already calls `trace_logger.write(...)` per `harness/hank_model.py:161`.
- Question-ID surfaces: the Vals SDK call signature `custom_call(test_input, files, context, question_id, run_id)` already passes `question_id` into our trace; aggregate joins on this.
- **Two files written per run, not one.** `vals_raw.json` is the lossless Vals export (kept for debugging / future re-aggregation if our normalized shape misses a field). `run.json` is the stable contract for `aggregate_results.py`.
- **Output is `--output-dir`, not `--output`.** Both files write under it. Shell scripts pass `${RESULTS_DIR}` not `${RESULTS_DIR}/run.json`.

**Risks (Codex implementer must verify against installed `vals.sdk`):**
- `from vals import Suite, RunParameters` is the newer documented import; `vals.sdk.suite.Suite` + `vals.sdk.types.RunParameters` is the fallback. Drop whichever the installed package doesn't have.
- `await run.fetch_json()` and `await run.test_results` per current Vals docs (https://docs.vals.ai/sdk/running_suites). If async-vs-sync differs, adjust.
- `RunParameters` field names (`eval_model`, `heavyweight_factor`, `parallelism`) and which level (`RunParameters` vs `suite.run` kwarg) — verify, adjust.
- `_safe_attr` defends against attribute-name drift across SDK versions; keep it even if v1 SDK shape is known.

### 2. `evals/vals-finance-agent/scripts/run_config_b.sh` (NEW)

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# HANK_VALS_RUN_TIMESTAMP must be exported by the caller (run_pair.sh) to keep
# Config A and Config B in the same results dir. Standalone use: pre-export it.
: "${HANK_VALS_RUN_TIMESTAMP:?Must be exported by caller (e.g. run_pair.sh) or pre-exported}"

# Variance-run suffix: 1 for first run, 2 for second per impl plan §5.2 variance check.
# Defaults to 1; set HANK_VALS_CONFIG_B_RUN=2 for the second variance run.
RUN_NUM="${HANK_VALS_CONFIG_B_RUN:-1}"
case "$RUN_NUM" in
  1|2) ;;  # validated per Codex r2 nit #2
  *)
    echo "HANK_VALS_CONFIG_B_RUN must be 1 or 2 (got: $RUN_NUM)" >&2
    exit 1
    ;;
esac
CONFIG_DIR="config_b_run${RUN_NUM}"
RESULTS_DIR="results/${HANK_VALS_RUN_TIMESTAMP}/${CONFIG_DIR}"
mkdir -p "$RESULTS_DIR"

# Activate vendor venv (has vals.sdk + finance_agent + model_library)
# shellcheck disable=SC1091
source vendor/finance-agent/.venv/bin/activate

# Load env (single shared .env at vendor location)
if [ -f vendor/finance-agent/.env ]; then
  set -a
  # shellcheck disable=SC1091
  source vendor/finance-agent/.env
  set +a
fi
unset DATABASE_URL || true

# Fail-fast on missing keys. Config B does NOT need FMP.
: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY must be set}"
: "${TAVILY_API_KEY:?TAVILY_API_KEY must be set}"
: "${SEC_EDGAR_API_KEY:?SEC_EDGAR_API_KEY must be set}"
: "${VALS_API_KEY:?VALS_API_KEY must be set}"
: "${VALS_SUITE_ID_PUBLIC_50:?VALS_SUITE_ID_PUBLIC_50 must be set}"

python3 -m harness.run_vals_suite \
    --config config_b_raw_opus \
    --run-name "hank_vals_${HANK_VALS_RUN_TIMESTAMP}_${CONFIG_DIR}" \
    --parallelism "${HANK_VALS_PARALLELISM:-5}" \
    --output-dir "${RESULTS_DIR}"
```

### 3. `evals/vals-finance-agent/scripts/run_config_a.sh` (NEW)

Same shape as `run_config_b.sh` with these deltas:
- `--config config_a_hank`
- `RESULTS_DIR="results/${HANK_VALS_RUN_TIMESTAMP}/config_a"` (no variance suffix; Config A runs once per cycle)
- Adds Config A only env assertion: `: "${FMP_API_KEY:?FMP_API_KEY must be set}"`
- `--run-name "hank_vals_${HANK_VALS_RUN_TIMESTAMP}_config_a"`
- No `HANK_VALS_CONFIG_B_RUN` handling

Two near-identical files (vs DRY into `_run_common.sh`) is clearer for v1; the variance-suffix logic only applies to B.

### 3b. `evals/vals-finance-agent/scripts/run_pair.sh` (NEW)

Orchestrator. Pins one timestamp, runs the impl plan §5.2 variance pair (B×2) + Config A + aggregator. The standard one-command Day-4 run.

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Flags (mutually exclusive — enforced)
MODE="full"  # full | b-only | skip-b
SAW_FLAG=0
while [ $# -gt 0 ]; do
  case "$1" in
    --b-only|--skip-b)
      if [ "$SAW_FLAG" -eq 1 ]; then
        echo "Flags --b-only and --skip-b are mutually exclusive" >&2
        exit 1
      fi
      SAW_FLAG=1
      MODE="${1#--}"
      shift
      ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

# r5 (Codex r4 should-fix): --skip-b requires an explicit HANK_VALS_RUN_TIMESTAMP
# pointing at a prior --b-only run. Auto-generating one would always fail the
# B-artifact preflight below, but only after wasting a Config A run if we
# generated first then checked.
if [ "$MODE" = "skip-b" ] && [ -z "${HANK_VALS_RUN_TIMESTAMP:-}" ]; then
  echo "--skip-b requires HANK_VALS_RUN_TIMESTAMP to be exported (the timestamp from the prior --b-only run)" >&2
  exit 1
fi
export HANK_VALS_RUN_TIMESTAMP="${HANK_VALS_RUN_TIMESTAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
echo "Run timestamp: ${HANK_VALS_RUN_TIMESTAMP} (mode: $MODE)"

if [ "$MODE" != "skip-b" ]; then
  # Config B variance pair (impl plan §5.2)
  HANK_VALS_CONFIG_B_RUN=1 bash scripts/run_config_b.sh
  HANK_VALS_CONFIG_B_RUN=2 bash scripts/run_config_b.sh
fi

if [ "$MODE" = "b-only" ]; then
  echo "--b-only: skipping Config A + aggregate. Inspect Config B fidelity first."
  echo "Resume with: HANK_VALS_RUN_TIMESTAMP=${HANK_VALS_RUN_TIMESTAMP} bash scripts/run_pair.sh --skip-b"
  exit 0
fi

# r5 (Codex r4 should-fix): preflight Config B artifacts BEFORE running Config A
# so we don't waste ~$260 on a doomed run.
for n in 1 2; do
  for f in run.json vals_raw.json; do
    path="results/${HANK_VALS_RUN_TIMESTAMP}/config_b_run${n}/${f}"
    if [ ! -s "$path" ]; then
      echo "Missing required Config B artifact: $path" >&2
      echo "(--skip-b assumes a prior --b-only run produced both config_b_run{1,2} dirs.)" >&2
      exit 1
    fi
  done
done

# Config A (per impl plan §3.5.1: B before A; operator inspects variance result
# before trusting the A delta. --b-only above lets the operator gate explicitly.)
bash scripts/run_config_a.sh

# Aggregate (uses both config_b_run{1,2}/ from the original timestamped run + new config_a/)
python3 -m scripts.aggregate_results --run-ts "${HANK_VALS_RUN_TIMESTAMP}"

echo "Done. See results/${HANK_VALS_RUN_TIMESTAMP}/summary.md"
```

**Three modes (Codex r3 should-fix #2 — `--skip-b` added because plain re-invocation re-runs B1/B2):**
- **Default** (no flags): runs B×2 + A + aggregate. Standard Day-4 cycle.
- **`--b-only`**: runs B×2 only. Use to inspect Config B fidelity before committing to Config A spend (~$260). Stops cleanly; prints the exact resume command.
- **`--skip-b`**: skips B (assumes B already ran for this `HANK_VALS_RUN_TIMESTAMP`); runs A + aggregate. The correct resume after `--b-only`.

The aggregator at the end reads from whatever `config_b_run{1,2}/` and `config_a/` directories exist under the timestamp — `--skip-b` works because the prior `--b-only` already populated the B dirs.

### 4. `evals/vals-finance-agent/scripts/aggregate_results.py` (NEW)

Reads:
- `results/<ts>/config_a/run.json` — Config A normalized output (authoritative for Config A scoring)
- `results/<ts>/config_b_run1/run.json` + `results/<ts>/config_b_run2/run.json` — Config B variance pair (Codex blocker #1 fix — variance runs go to distinct dirs, not same dir)
- `results/<ts>/config_a/traces.jsonl` — Config A Hank telemetry, **left-joined** as enrichment (Codex blocker #3 fix)
- `vendor/finance-agent/data/public.csv` — `Question` + `Question Type` columns (category fallback only; r3 join by normalized question text since `public.csv` has no `question_id` column — Codex r2 should-fix #1)

Emits:
- `results/<ts>/summary.md` (human)
- `results/<ts>/summary.json` (machine)
- `results/<ts>/run_log.md` skeleton (per impl plan §3.6.2)

**CLI:**
```
python3 -m scripts.aggregate_results --run-ts 20260504T123000Z
                                      [--baseline-pct 64.4]
```

Tier thresholds are hard-coded from sprint plan §3.4 — not CLI flags (the table is the contract).

**Authority + join semantics (Codex blocker #3 fix):**
- **Vals `run.json` is authoritative for scoring.** Pass rates derive from `result["passed"]` count / total. Never silently dropped.
- **`traces.jsonl` is left-joined** onto Config A `run.json` by `question_id` for telemetry enrichment (token/cost/duration/stop_reason/tool_usage/warnings). Missing trace rows do NOT remove the question from scoring.
- Aggregator reports **trace coverage**: `<matched>/<total>` rows; warns if coverage < 100% with the missing `question_id`s listed in `summary.md` and `summary.json`.
- Per-category bucketing: prefer `category` from Vals `run.json` (per normalized schema field in §1). Fall back to `public.csv` `Question Type` looked up by **normalized question text** (Codex r2 should-fix #1: `public.csv` columns are `Question, Answer, Question Type, Expert time (mins), Rubric` — there is NO `question_id` column, so cannot join by ID). **Normalization (r4 — Codex r3 should-fix #2): reuse the exact `_normalize` from `evals/vals-finance-agent/harness/scoring_stub.py:24` — lowercase, replace non-alphanumeric chars with spaces, collapse whitespace.** Import directly: `from harness.scoring_stub import _normalize`. If a question is in `run.json` but not in `public.csv`, log warning and bucket as "Uncategorized". (Risk: if `input_under_test` from Vals SDK has different whitespace/punctuation than what's in `public.csv`, normalization handles it; if Vals trims/transforms more aggressively, the join may fail and Uncategorized rate will signal this.)

**Slices (per impl plan §3.4.4 — match all except filing type, Q6 unresolved):**
- Overall pass rate per config (Config B = mean of variance pair; report run1, run2, mean, |diff|)
- Delta = A − B(mean)
- Tier label per **full** delta-gated table (Codex blocker #4 fix — see below)
- Per-`Question Type` table: 9 rows × {A pass-rate, B pass-rate, delta}
- Head-to-head **(r3 — disambiguate B-variance per Codex r2 should-fix #4)**: classify each `question_id` for Config B as one of {`B_pass_stable` (both runs pass), `B_fail_stable` (both runs fail), `B_split` (one pass, one fail)}. Then:
  - `A_wins`: A passed AND `B_fail_stable`
  - `B_wins`: A failed AND `B_pass_stable`
  - `B_unstable`: questions in `B_split` — reported as a separate list, NOT counted in either head-to-head bucket
- **Error/status histogram (renamed from "stop-reason" per Codex r2 should-fix #5)**: Config A reports a true stop-reason histogram from `traces.jsonl` (`stop_reason` field, e.g. `done_tool` / `max_turns` / `error`). Config B reports an error/status histogram from Vals `run.json` `error` field; "stop reason" is N/A for Config B because the vendor `custom_call` doesn't expose it.
- Token/cost/duration totals: Config A from `traces.jsonl` aggregated metadata; Config B from `run.json` `tokens`/`cost`/`duration_seconds` fields if Vals exposes them, else explicitly marked "N/A — vendor `custom_call` lacks trace hook" (per Decision §7).

**Tier function (full table from `VALS_FINANCE_AGENT_RUN_PLAN.md` §3.4 lines 107-115 — Codex blocker #4 fix):**
```python
def tier(score_a_pct: float, delta_pp: float) -> str:
    """Sprint plan §3.4 publish-tier table.

    Committed floor: score_a < 80 OR delta < 15 -> hold (line 115 of run plan).
    """
    if score_a_pct < 80 or delta_pp < 15:
        return "hold"  # committed floor — never publish
    # delta >= 15 here
    if delta_pp < 25:
        # 80-95% with delta 15-25pp -> can only claim delta narrative
        return "delta-only"
    # delta >= 25
    if score_a_pct >= 95:
        return "hero"          # ≥95% AND ≥25pp = Dominant-SOTA
    if score_a_pct >= 92:
        return "sota-claim"    # ≥92% AND ≥25pp = SOTA-claim
    if score_a_pct >= 88:
        return "approach-sota" # 88-92% AND ≥25pp = Approach-SOTA
    return "delta-only"        # 80-88% AND ≥25pp = pure delta narrative
```

**`run_log.md` skeleton (Codex should-fix #3 — capture both expected and actual vendor SHA):**
```markdown
# Run Log — <run_ts>

- Run timestamp: <ISO>
- Hank repo SHA: <git rev-parse HEAD>
- Vendor harness SHA (expected, parsed from `VENDOR_SHA` `sha=…` line — Codex r2 nit #3): <pinned-sha>
- Vendor harness SHA (actual, from `git -C vendor/finance-agent rev-parse HEAD`): <actual-sha>
  - DRIFT WARNING (rendered only if mismatch)
- Model: anthropic/claude-opus-4-7  (resolved snapshot: <if exposed by model_library>)
- Judge: openai/gpt-5.2 (heavyweight=3)
- Suite: <VALS_SUITE_ID_PUBLIC_50>
- Trace coverage (Config A): <matched>/<total>

## Scores
- Config A: <%>
- Config B run1: <%>
- Config B run2: <%>
- Config B mean: <%>
- Config B variance |run1 − run2|: <pp>  (impl plan §5.2: ≤3pp expected)
- Delta (A − B_mean): <pp>
- Tier: <hold|delta-only|approach-sota|sota-claim|hero>

## Per-category
<table>

## Delta-from-previous-run
TODO — fill in by hand per impl plan §3.6.2 discipline:
- What changed since the last run?
- Specific question_ids that flipped (pass↔fail)?
- Architectural attribution?
```

### 5. `evals/vals-finance-agent/README.md` (NEW)

~2 pages covering:
- **What this is** — link to `docs/planning/VALS_FINANCE_AGENT_RUN_PLAN.md` and the impl plan
- **Setup (one-time)**:
  ```bash
  # 1. Re-clone vendor at pinned SHA (gitignored)
  git clone https://github.com/vals-ai/finance-agent.git vendor/finance-agent
  cd vendor/finance-agent
  git checkout 82337852884d19017154f21bf8d7a4ae09e9896b
  # 2. Apply VENDOR_PATCHES.md Patch 1 (model-library 0.1.19 → 0.1.23)
  sed -i.bak 's/model-library==0.1.19/model-library==0.1.23/' pyproject.toml && rm pyproject.toml.bak
  # 3. Install
  uv sync --dev
  # 4. Smoke
  uv run finance-agent --help
  # 5. Env file
  cd ../..
  cp .env.example vendor/finance-agent/.env
  # then edit and fill in keys
  ```
- **Required env vars** — table referencing `.env.example`
- **Dry-run** (no Vals key needed): `bash scripts/dry_run.sh`
  - Dry-run sources the **repo** `.env` (`/Users/henrychien/Documents/Jupyter/risk_module/.env`) for FMP/Anthropic keys — Hank wrapper smoke only, no Vals platform call. Production runs source the **vendor** `.env` (see Setup step 5).
- **Production run** (single command, recommended): `bash scripts/run_pair.sh`
  - This is the standard Day-4 cycle. Pins one timestamp, runs Config B twice (variance check, impl plan §5.2), runs Config A once, runs the aggregator. Outputs land at `results/<ts>/summary.md` + `run_log.md`.
- **Production run (manual / advanced)**:
  ```bash
  export HANK_VALS_RUN_TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
  HANK_VALS_CONFIG_B_RUN=1 bash scripts/run_config_b.sh
  HANK_VALS_CONFIG_B_RUN=2 bash scripts/run_config_b.sh
  bash scripts/run_config_a.sh
  python3 -m scripts.aggregate_results --run-ts $HANK_VALS_RUN_TIMESTAMP
  ```
  Single-config scripts require `HANK_VALS_RUN_TIMESTAMP` to be exported by the caller (otherwise variance runs and Config A would land in different dirs).
- **Reading results** — pointer to `results/<ts>/summary.md`, `summary.json`, `run_log.md`, `config_a/traces.jsonl`, `config_*/vals_raw.json` (raw Vals export for re-aggregation if needed)
- **Known gotchas:**
  - `DATABASE_URL` MUST be unset (Hank registry tools fall back to no-DB mode)
  - **Vendor `.env`** (`vendor/finance-agent/.env`) is the single source of truth for **production runs**. Dry-run uses the **repo** `.env` (FMP-only smoke).
  - First Config B run should be done twice for variance check (impl plan §5.2) — `run_pair.sh` does this automatically
  - Order: B before A (impl plan §3.5.1) — `run_pair.sh` enforces this
  - If `vals_raw.json` and `run.json` disagree, `run.json` is the contract; `vals_raw.json` is for debugging only

### 6. `evals/vals-finance-agent/.env.example` (EDIT)

Surgical changes only:
- **Uncomment `VALS_API_KEY=`** and reframe comment from "optional for v1, defer until publish-ready" → "**required for production runs**; optional only when running `dry_run.sh` (which uses repo `.env` and the local stub judge)" (Codex nit)
- **Add `VALS_SUITE_ID_PUBLIC_50=`** with a comment pointing to platform.vals.ai for suite-creation steps if not provided pre-baked

No other changes.

---

## Critical files referenced (read-only)

- `docs/planning/VALS_FINANCE_AGENT_IMPL_PLAN.md` — §4.5 (scripts), §4.6 (docs), §3.4.3 (trace schema), §3.4.4 (aggregation slices), §3.5.1 (env strategy), §3.6.2 (run log discipline)
- `docs/planning/VALS_FINANCE_AGENT_RUN_PLAN.md` — §3.4 publish-tier thresholds (drives aggregate output)
- `docs/research/vals-finance-agent-day1-verifications.md` — Q1 (Suite.from_id PASS), Q5 (model snapshot), Q15/Q16 (registry adapter contracts)
- `evals/vals-finance-agent/harness/hank_model.py` — Config A `get_custom_model` and `custom_call` shape (lines 127-172)
- `evals/vals-finance-agent/harness/trace_logger.py` — `write()` signature + JSON row schema (lines 45-86), already wired into Config A's `custom_call`
- `evals/vals-finance-agent/harness/runtime_paths.py` — `ensure_runtime_paths()`, `results_root()`, vendor venv discovery
- `evals/vals-finance-agent/harness/scoring_stub.py` — pattern reference for env loading + CSV reading
- `evals/vals-finance-agent/harness/hank_tools.py:48-54` — confirms 19 wrapped + 1 code + 1 submit + 4 native = 25 tool classes
- `evals/vals-finance-agent/configs/config_a_hank.py` + `config_b_raw_opus.py` — both pin `MODEL_NAME = "anthropic/claude-opus-4-7"` and export `get_custom_model`
- `evals/vals-finance-agent/scripts/dry_run.sh` — env-loading and `unset DATABASE_URL` pattern reused by production scripts
- `evals/vals-finance-agent/.env.example` — schema to extend
- `evals/vals-finance-agent/VENDOR_SHA` + `VENDOR_PATCHES.md` — README references

---

## Verification

After Codex implements, before Day-4 baseline runs:

1. **Static**:
   - `python3 -c "import ast; ast.parse(open('evals/vals-finance-agent/harness/run_vals_suite.py').read())"` (parse check)
   - `python3 -c "import ast; ast.parse(open('evals/vals-finance-agent/scripts/aggregate_results.py').read())"` (parse check)
   - `bash -n evals/vals-finance-agent/scripts/run_config_a.sh && bash -n evals/vals-finance-agent/scripts/run_config_b.sh && bash -n evals/vals-finance-agent/scripts/run_pair.sh` (parse check, all shell)

2. **Wrapper sanity (no Vals key needed)**:
   - Re-clone vendor + apply Patch 1 + `uv sync --dev` per README
   - `bash evals/vals-finance-agent/scripts/dry_run.sh` — confirm wrapper still imports cleanly post-12-day pause; tool smoke writes to `results/.../stub_summary.json`

3. **Vals API surface verification (with key, on 1 question — Codex r2 should-fix #2 unstale'd):**
   - Create a 1-question test suite at platform.vals.ai (or pass `VALS_SUITE_ID_PUBLIC_50` of a small suite)
   - From `evals/vals-finance-agent/`:
     ```bash
     export HANK_VALS_RUN_TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
     HANK_VALS_PARALLELISM=1 bash scripts/run_pair.sh --b-only
     ```
   - Confirm BOTH `results/<HANK_VALS_RUN_TIMESTAMP>/config_b_run1/{run.json,vals_raw.json}` AND `config_b_run2/{run.json,vals_raw.json}` are created and well-formed (`--b-only` runs B twice — Codex r3 nit)
   - Spot-check that `run.json` has `schema_version: "1"` and `results[0]` has non-null `question_id`, `passed` (bool), `final_answer` (strict-validation pass)
   - If `RunParameters` / `Suite.from_id` API differs from pseudocode, adjust `harness/run_vals_suite.py` and re-verify
   - If strict-validation aborts with "missing required field(s)", inspect `vals_raw.json` to find the actual SDK field name and add it to `_normalize_result`'s `_safe_attr` candidate list

4. **End-to-end (Day 4 — single command):**
   - `bash scripts/run_pair.sh` (one timestamp; runs B×2 + A + aggregate)
   - `cat results/<ts>/summary.md` — sanity check Config B mean ≈ 64.4% ± 5pp + |run1 − run2| ≤ 3pp; Config A baseline number is the input to Day 5 failure-mode analysis
   - If B fidelity is out of band, re-run Config B per impl plan §5.2 debug steps before trusting Config A delta

5. **Reproducibility (impl plan §5.5)**:
   - `git ls-files evals/vals-finance-agent/` — confirm no secrets in committed files
   - `cat evals/vals-finance-agent/VENDOR_SHA` matches what was checked out

---

## Sequencing

1. **Codex review of this plan** → iterate to PASS (this step)
2. Codex implements via `mcp__codex__codex` per CLAUDE.md conventions (no `model` override, `approval-policy: "never"`, `sandbox: "workspace-write"`, `cwd: /Users/henrychien/Documents/Jupyter/risk_module`)
3. User runs Verification §1 + §2 (no key needed)
4. User runs Verification §3 (1-question smoke, key needed) — Codex iterates if Vals SDK details differ
5. User runs Verification §4 (full Day-4 baseline) once §3 passes
6. Day-5 failure-mode analysis per impl plan §7
