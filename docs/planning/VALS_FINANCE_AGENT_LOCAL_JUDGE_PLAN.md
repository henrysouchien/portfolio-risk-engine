# Vals Finance Agent — Local-Judge Bypass Plan (Option B)

**Created:** 2026-05-05
**Revised:** 2026-05-05 (r2) — Codex r1 FAIL → fixed 4 blockers + 5 should-fixes + nits. New file `harness/output_object_compat.py` (runtime shim for missing `OutputObject.from_agent_result` in installed valsai 0.3.9 — affects BOTH this runner AND the shipped `run_vals_suite.py`); `local_judge.py` rewritten to parse actual rubric JSON (`[{operator: correctness|contradiction, criteria}]`) instead of bogus "must/required/key" heuristic; judge infra errors now distinguished from rubric failures (preflight + per-call `_kind` discriminator + abort-on-mass-judge-failure); `run_local_suite.py` adds error-rate guard (default 50%, override `--allow-error-rate`); `run_local_pair.sh` passes through `--judge-model` / `--heavyweight-factor`; `--limit` argument validated as positive integer; `heavyweight_factor>=1` enforced; `judge_path` surfaced in summary.json.
**Revised:** 2026-05-05 (r3) — Codex r2 FAIL → fixed 3 remaining blockers + 5 should-fixes + nits. Shim's `cost` now `Optional[float]` (was dict — would crash pydantic on real cost data); shim populates `output_context` with `success`/`stop_reason`/`final_error` so `AgentResult.success=False` (agent failures, not exceptions) is detectable downstream; `process_one` reads `output_context.success` and converts agent failures into `run_error` BEFORE judging; `judge_with_heavyweight` now enforces minimum rubric-call quorum (`heavyweight_factor//2+1`) — partial infra failures bubble up as `infra_error` instead of getting silently overweighted; `JudgeResult.skipped` field separates run-failure-skips from real judge infra errors; `_enforce_error_rate_guards` counts only true `infra_error` (not `skipped`); Python `--limit` validates positive; `run_local_pair.sh` exposes `--allow-error-rate` / `--allow-judge-error-rate`; rubric fallback now warns loudly with `print(WARN: ...)`; `judge_one` validates per-check `index`/`operator`/`passed` types; `preflight` validates `ok is True`.
**Revised:** 2026-05-05 (r4) — Codex r3 PASS → applied 3 should-fixes + 3 nits. Aggregator now surfaces per-config `run_errors` / `judge_skipped` / `judge_infra_errors` counts in `summary.{md,json}` (Codex r3 should-fix #1); `process_one` treats empty `llm_output` as `run_error` BEFORE judging (Codex r3 should-fix #2); Python validates `--parallelism >= 1` (Codex r3 should-fix #3); `parse_rubric` warning emitted via `print(..., file=sys.stderr)` not stdout (Codex r3 nit #1); shim wraps `getattr(result, "success")` in try/except so property-raise can't break the shim (Codex r3 nit #2); Decision §4 wording corrected to count the shim module (Codex r3 nit #3).
**Status:** ✅ **CODEX PASS (r3, 2026-05-05); r4 polish applied** — ready for implementation per CLAUDE.md plan-first workflow.
**Implements:** `docs/planning/VALS_FINANCE_AGENT_IMPL_PLAN.md` §3.4.1 fallback path (local-judge stub when Vals platform is unavailable)
**Sibling:** `docs/planning/VALS_FINANCE_AGENT_PRODUCTION_RUN_PLAN.md` (the official Vals-platform path; SHIPPED 2026-05-05 commits a4fe61f3 + 94ddcfb5 + d2284b01 + 4acf3ca0)
**Upstream:**
- Sprint envelope: `docs/planning/VALS_FINANCE_AGENT_RUN_PLAN.md`
- Locked impl plan: `docs/planning/VALS_FINANCE_AGENT_IMPL_PLAN.md`
- Day-1 verifications: `docs/research/vals-finance-agent-day1-verifications.md`

---

## Context

Vals platform access is sales-gated (no self-serve API key) with multi-day SLA. The shipped production-run pipeline (`harness/run_vals_suite.py`) is structurally complete and verified by dry-run smoke (4/6 keys live-tested), but **`bash scripts/run_pair.sh`** hard-fails on the missing `VALS_API_KEY` + `VALS_SUITE_ID_PUBLIC_50`.

**Goal:** unblock internal Hank-vs-Opus-4.7 measurement on the public-50 questions WITHOUT Vals platform access, by replacing the hosted GPT-5.2 mode-of-3 judge with a local OpenAI gpt-5.2 judge calling the same model family the Vals platform uses. Plan §3.4.1 of the impl plan explicitly contemplates this fallback ("only case for a local judge is if we run out of VALS_API_KEY quota or the platform is slow").

**What we have:** the 50 public questions + rubrics in `vendor/finance-agent/data/public.csv` (fully open per Vals's own design), Hank wrapper code, normalized `run.json` schema + aggregator, vendor venv with `openai==2.29.0` already installed.

**What we don't:** a runner that bypasses `Suite.from_id`, and a judge that bypasses Vals's hosted scoring.

**Defensibility caveat (NOT a blocker):** results from this path are usable for internal failure-mode analysis (impl plan Goal #3), informal blog framing ("Hank scored X on Vals public-50, judged locally"), and architectural iteration. They are NOT defensible for external publish claims like "we scored X on the Vals leaderboard" — different judge methodology = suspect headline number. If Vals platform access ever lands, swap in `run_vals_suite.py` and re-run; the aggregator output schema is identical.

**In scope:** **4** new files + surgical edits to `aggregate_results.py` + `.env.example` + `README.md`. **NO** changes to existing wrapper code (`hank_model.py`, tool adapters, configs). r2 added `harness/output_object_compat.py` to fix a latent valsai-version-skew bug both runners hit at runtime.

**Affects production runner too:** the `OutputObject.from_agent_result` shim (`output_object_compat.py`) is a real bug fix, not a local-judge-only concern. The shipped `run_vals_suite.py` would crash at the same call site once it actually invokes a model. Production-runner adoption of the shim is filed as a follow-up commit (out of this plan's scope, since it'd require re-running Codex review on `VALS_FINANCE_AGENT_PRODUCTION_RUN_PLAN.md`).

**Out of scope:**
- Modifying `run_vals_suite.py` (it stays as the official-mode driver for when Vals key lands)
- Cost optimizations beyond defaults (e.g. cheaper judge model — surfaced as override env var, not changed)
- Tests (impl-plan-§5.1 follow-up)
- Codex CLI as judge (rejected per pre-plan discussion: parse-fragile, slow)

---

## Decisions made (call out for Codex review)

1. **Judge: OpenAI gpt-5.2 (matches Vals's `eval_model` exactly)** via `openai` SDK installed in vendor venv. User has `OPENAI_API_KEY`. Override via `HANK_VALS_LOCAL_JUDGE_MODEL` env var if user wants cheaper (e.g. gpt-5-mini for dev).
2. **Heavyweight = 3 (mode-of-3 majority vote, matches Vals methodology).** CLI flag `--heavyweight-factor` allows override (default 3); set to 1 for fast/cheap dev iteration.
3. **B variance pair retained (B×2).** Per impl plan §5.2, variance check is methodology-consistent. Costs ~$6 extra for the second B run. Drop only if user explicitly wants single-B mode (NOT planned for v1).
4. **THREE new harness modules + one new orchestrator script** (r4 — Codex r3 nit #3 corrected wording):
   - `harness/output_object_compat.py` — runtime shim for missing `OutputObject.from_agent_result` (per Decision §7)
   - `harness/local_judge.py` — judge utility (testable, reusable)
   - `harness/run_local_suite.py` — local equivalent of `run_vals_suite.py`; reads `public.csv`, runs each question through `custom_call`, judges, writes the same normalized `run.json`
   - `scripts/run_local_pair.sh` — orchestrator analogous to `run_pair.sh`; reuses existing `run_config_a.sh` / `run_config_b.sh` shells indirectly by NOT reusing them — local path skips the env-assertion fail-fast on `VALS_API_KEY` / `VALS_SUITE_ID_PUBLIC_50` since we don't need them
5. **Aggregator surface change is minimal:** `aggregate_results.py` reads `run_metadata.eval_model` (already exists) and surfaces a prominent banner in `summary.md` when value contains `"local"` (e.g. `openai/gpt-5.2 (local judge)`) so internal vs external-claim distinction is loud. This is the ONLY existing-code edit.
6. **Run dirs use the same layout as production** (`results/<ts>/config_a/`, `config_b_run1/`, `config_b_run2/`) so the existing aggregator works unchanged. The `eval_model` banner is the only renderable difference.
7. **REVISED r2: `vals.sdk` IS imported indirectly + needs a runtime compatibility shim.** `run_local_suite.py` invokes `custom_call(test_input, files={}, context={"question_type": ...}, question_id, run_id)` directly — same callable contract Vals would use, just orchestrated locally. The existing `OutputObject.from_agent_result(...)` in `hank_model.py:170` runs inside `custom_call` and **the installed `valsai==0.3.9` does NOT provide `from_agent_result`** (Codex r1 blocker #1; verified: `OutputObject` only exposes `llm_output, output_context, duration, in_tokens, out_tokens, cost`). Fix: new `harness/output_object_compat.py` module monkey-patches `OutputObject.from_agent_result = classmethod(_shim)` at import time, before configs load. We extract `output_obj.llm_output` (the only attr that exists) for the answer string. Other speculative attrs (`output`, `model_output`, `answer`) dropped from `_extract_answer` per Codex r1 should-fix #5.
8. **Stub judge mode for dev: `--dry-judge` flag** on `run_local_suite.py` returns a deterministic fake (e.g. `passed = (len(model_answer) > 100)`). Keeps OpenAI bill at $0 during runner-loop iteration. Used by Codex implementer + soft-test before the first real run.

---

## File-by-file design

### 0. `evals/vals-finance-agent/harness/output_object_compat.py` (NEW — Codex r1 blocker #1)

Runtime monkey-patch of `vals.sdk.types.OutputObject.from_agent_result`. The classmethod is invoked by both `hank_model.py:170` (Config A) and vendor `finance_agent/custom_model.py:47` (Config B), but installed `valsai==0.3.9` doesn't provide it. Without this shim, **every** `custom_call` invocation crashes — this is the same latent bug `run_vals_suite.py` (production) hits.

```python
"""Compatibility shim for valsai==0.3.9: OutputObject.from_agent_result.

Vendor finance_agent/custom_model.py:47 and harness/hank_model.py:170 both call
OutputObject.from_agent_result(result, count_tool_metadata=True), but the
classmethod is missing in the installed valsai release. We monkey-patch it on
import to construct OutputObject directly from AgentResult fields.

Idempotent: skips patching if the method already exists (e.g. future valsai
versions that ship it natively).
"""
from __future__ import annotations
from typing import Any


def _from_agent_result_shim(cls, result: Any, *, count_tool_metadata: bool = False) -> Any:
    """Build OutputObject from model_library.agent.AgentResult.

    NOTE (Codex r2 nit): this is NOT metadata-equivalent to Vals's intended
    `from_agent_result` helper; we ignore `count_tool_metadata` and only
    populate the fields needed for local scoring + downstream failure detection.
    """
    aggregated = getattr(result, "final_aggregated_metadata", None)
    # Codex r2 blocker #1: valsai OutputObject.cost is Optional[float], not dict.
    cost_total: float | None = None
    if aggregated is not None:
        cost_obj = getattr(aggregated, "cost", None)
        if cost_obj is not None:
            raw_total = getattr(cost_obj, "total", None)
            if raw_total is None and isinstance(cost_obj, (int, float)):
                raw_total = cost_obj
            if raw_total is not None:
                try:
                    cost_total = float(raw_total)
                except (TypeError, ValueError):
                    cost_total = None
    # Codex r2 blocker #3: surface agent-level failure metadata so the local
    # runner can convert AgentResult.success=False into a run_error before judging.
    final_error = getattr(result, "final_error", None)
    stop_reason_obj = getattr(result, "stop_reason", None)
    # Codex r3 nit #2: success can be a property; getattr default doesn't catch
    # property-raise. Wrap in try/except to keep the shim resilient under future
    # AgentResult shape changes.
    try:
        success_value = bool(getattr(result, "success", final_error is None))
    except Exception:
        success_value = final_error is None
    output_context = {
        "success": success_value,
        "stop_reason": getattr(stop_reason_obj, "value", str(stop_reason_obj) if stop_reason_obj else None),
        "final_error": (
            {"type": getattr(final_error, "type", None),
             "message": getattr(final_error, "message", None)}
            if final_error is not None else None
        ),
        "total_turns": getattr(result, "total_turns", None),
    }
    return cls(
        llm_output=result.final_answer or "",
        output_context=output_context,
        duration=float(getattr(result, "final_duration_seconds", 0.0) or 0.0),
        in_tokens=int(getattr(aggregated, "in_tokens", 0) or 0) if aggregated else 0,
        out_tokens=int(getattr(aggregated, "out_tokens", 0) or 0) if aggregated else 0,
        cost=cost_total,
    )


def patch_output_object_compat() -> None:
    """Install from_agent_result on vals.sdk.types.OutputObject if missing."""
    from vals.sdk.types import OutputObject
    if hasattr(OutputObject, "from_agent_result"):
        return  # native impl present (newer valsai)
    OutputObject.from_agent_result = classmethod(_from_agent_result_shim)
```

**Caller invariant:** `run_local_suite.py` (and eventually `run_vals_suite.py`) MUST call `patch_output_object_compat()` AFTER `ensure_runtime_paths()` and BEFORE importing any config module (which transitively imports `hank_model`, which captures the OutputObject reference at module load time? No — it imports OutputObject inside the `custom_call` closure at line 133, so patching anytime before invocation is fine). Patch can be called repeatedly (idempotent).

### 1. `evals/vals-finance-agent/harness/local_judge.py` (NEW — REVISED r2 for Codex r1 blockers #3 + #4)

Parses actual rubric JSON `[{"operator": "correctness"|"contradiction", "criteria": "..."}]` instead of bogus heuristic. Distinguishes judge infrastructure errors (bad model name, parse failures, API errors) from rubric failures so the run can abort loudly when judging is broken rather than silently scoring everything 0%.

```python
"""OpenAI gpt-5.2 local judge — replaces Vals hosted scoring.

Methodology: parses Vals's per-check rubric JSON (correctness + contradiction
operators), runs mode-of-N majority vote per check (default N=3 per Vals's
heavyweight_factor), aggregates deterministically: pass iff every check passes.
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI


JUDGE_PROMPT = """You are evaluating a model's answer against specific criteria from a financial benchmark rubric.

QUESTION:
{question}

GOLD-STANDARD ANSWER:
{gold_answer}

MODEL ANSWER:
{model_answer}

CRITERIA TO EVALUATE (one per line, with operator):
{criteria_block}

For EACH criterion above, decide pass or fail according to its operator:
- `correctness`: Does the model answer correctly state or include this fact?
  - PASS = the answer correctly conveys this information.
  - FAIL = the answer is missing or wrong on this point.
- `contradiction`: Does the model answer DIRECTLY contradict this fact?
  - PASS = the answer does NOT contradict this. (Good for the model.)
  - FAIL = the answer states something contrary. (Bad for the model.)

Return JSON only — no prose. Output one entry per criterion in the same order:
{{
  "results": [
    {{"index": 0, "operator": "correctness", "passed": true|false, "rationale": "<1 sentence>"}},
    ...
  ]
}}
"""

PREFLIGHT_PROMPT = """Return JSON only: {"ok": true}"""


@dataclass
class JudgeResult:
    passed: bool
    vote_count: str  # "2/3" — counts of successful rubric calls / total
    per_check: list[dict[str, Any]] = field(default_factory=list)
    raw_judgements: list[dict[str, Any]] = field(default_factory=list)
    infra_error: str | None = None  # set when judge calls failed (incl partial-quorum-miss)
    skipped: str | None = None  # set when judging was SKIPPED (e.g. run failed); separate from infra_error

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "vote_count": self.vote_count,
            "per_check": self.per_check,
            "raw_judgements": self.raw_judgements,
            "infra_error": self.infra_error,
            "skipped": self.skipped,
        }


def parse_rubric(raw: str, *, question_id: str = "?") -> list[dict[str, str]]:
    """Vals public.csv rubric is JSON list. Free-form fallback for malformed rows.

    Codex r2 verified all 50 current rows parse cleanly (200 correctness + 50
    contradiction). Fallback should not trigger in practice; if it does, we
    print a loud WARN so the operator knows the rubric file shape may have
    changed and per-check semantics no longer apply for that question.
    """
    try:
        parsed = json.loads(raw or "")
        if isinstance(parsed, list) and all(
            isinstance(c, dict) and "operator" in c and "criteria" in c for c in parsed
        ):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    print(
        f"WARN: rubric for {question_id} is not parseable JSON list; "
        f"falling back to single correctness criterion (per-check semantics lost)",
        file=sys.stderr,  # Codex r3 nit #1
        flush=True,
    )
    return [{"operator": "correctness", "criteria": (raw or "<empty rubric>").strip()}]


def render_criteria_block(rubric: list[dict[str, str]]) -> str:
    return "\n".join(f"[{i}] {c['operator']}: {c['criteria']}" for i, c in enumerate(rubric))


async def judge_one(
    client: AsyncOpenAI,
    *,
    question: str,
    gold_answer: str,
    rubric: list[dict[str, str]],
    model_answer: str,
    judge_model: str,
) -> dict[str, Any]:
    """Single judge call. Returns {"_kind": "rubric", "results": [...]} or {"_kind": "infra_error", "error": "..."}."""
    try:
        resp = await client.chat.completions.create(
            model=judge_model,
            messages=[
                {"role": "user", "content": JUDGE_PROMPT.format(
                    question=question,
                    gold_answer=gold_answer,
                    model_answer=model_answer,
                    criteria_block=render_criteria_block(rubric),
                )},
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        content = resp.choices[0].message.content
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            return {"_kind": "infra_error", "error": f"JSON parse: {exc}; content[:200]={content[:200]}"}
        results = parsed.get("results")
        if not isinstance(results, list) or len(results) != len(rubric):
            return {"_kind": "infra_error", "error": f"results malformed (expected len={len(rubric)}, got {results!r})"}
        # Codex r2 should-fix #5: validate each entry's shape.
        for idx, entry in enumerate(results):
            if not isinstance(entry, dict):
                return {"_kind": "infra_error", "error": f"results[{idx}] not dict"}
            if entry.get("index") not in (idx, str(idx)):  # tolerate string indices
                return {"_kind": "infra_error", "error": f"results[{idx}].index expected {idx}, got {entry.get('index')!r}"}
            if entry.get("operator") != rubric[idx]["operator"]:
                return {"_kind": "infra_error", "error": f"results[{idx}].operator expected {rubric[idx]['operator']!r}, got {entry.get('operator')!r}"}
            if not isinstance(entry.get("passed"), bool):
                return {"_kind": "infra_error", "error": f"results[{idx}].passed not bool: {entry.get('passed')!r}"}
        return {"_kind": "rubric", "results": results}
    except Exception as exc:
        return {"_kind": "infra_error", "error": f"{type(exc).__name__}: {exc}"}


async def judge_with_heavyweight(
    client: AsyncOpenAI,
    *,
    question: str,
    gold_answer: str,
    rubric_raw: str,
    model_answer: str,
    judge_model: str,
    heavyweight_factor: int = 3,
    question_id: str = "?",
) -> JudgeResult:
    """Per-check mode-of-N majority. Aggregate: pass iff EVERY check passes."""
    if heavyweight_factor < 1:
        raise ValueError(f"heavyweight_factor must be >= 1 (got {heavyweight_factor})")
    rubric = parse_rubric(rubric_raw, question_id=question_id)

    judgements = await asyncio.gather(*[
        judge_one(
            client, question=question, gold_answer=gold_answer,
            rubric=rubric, model_answer=model_answer, judge_model=judge_model,
        )
        for _ in range(heavyweight_factor)
    ])

    rubric_judgements = [j for j in judgements if j["_kind"] == "rubric"]
    infra_errors = [j for j in judgements if j["_kind"] == "infra_error"]

    # Codex r2 blocker #2: enforce minimum quorum of original N. If only 1 of 3
    # judge calls succeeds, we should NOT score the question on that single vote.
    min_quorum = (heavyweight_factor // 2) + 1  # majority of original N (2 of 3, 1 of 1, 2 of 2)
    if len(rubric_judgements) < min_quorum:
        sample = "; ".join(j["error"][:100] for j in infra_errors[:2]) or "n/a"
        return JudgeResult(
            passed=False,
            vote_count=f"{len(rubric_judgements)}/{heavyweight_factor}",
            raw_judgements=judgements,
            infra_error=(
                f"only {len(rubric_judgements)}/{heavyweight_factor} judge calls succeeded "
                f"(need >={min_quorum}); first errors: {sample}"
            ),
        )

    # Per-check majority across the surviving rubric_judgements. Threshold is
    # against ORIGINAL N (not surviving count) so a 2/3 quorum still requires
    # 2 yes votes to pass a check.
    per_check: list[dict[str, Any]] = []
    for idx, criterion in enumerate(rubric):
        votes = [j["results"][idx].get("passed") is True for j in rubric_judgements]
        passed_votes = sum(votes)
        per_check.append({
            "index": idx,
            "operator": criterion["operator"],
            "criteria": criterion["criteria"],
            "passed": passed_votes >= min_quorum,
            "vote_count": f"{passed_votes}/{heavyweight_factor}",
        })

    overall_passed = all(c["passed"] for c in per_check)
    return JudgeResult(
        passed=overall_passed,
        vote_count=f"{len(rubric_judgements)}/{heavyweight_factor}",
        per_check=per_check,
        raw_judgements=judgements,
    )


def stub_judge(model_answer: str) -> JudgeResult:
    """Deterministic stub for --dry-judge mode. No OpenAI cost. Loudly labeled."""
    passed = bool(model_answer and len(model_answer.strip()) > 100)
    return JudgeResult(
        passed=passed,
        vote_count="stub",
        per_check=[{"index": 0, "operator": "stub", "criteria": "len>100", "passed": passed, "vote_count": "stub"}],
    )


def make_client() -> AsyncOpenAI:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set for local judge")
    return AsyncOpenAI(api_key=api_key)


async def preflight(client: AsyncOpenAI, judge_model: str) -> None:
    """One-call sanity check before agent runs. Codex r1 blocker #3."""
    try:
        resp = await client.chat.completions.create(
            model=judge_model,
            messages=[{"role": "user", "content": PREFLIGHT_PROMPT}],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=20,
        )
        content = resp.choices[0].message.content
        parsed = json.loads(content)  # must parse
        # Codex r2 nit: validate `ok is True`, not just "some JSON parsed".
        if parsed.get("ok") is not True:
            raise RuntimeError(
                f"Judge preflight returned unexpected payload: {parsed!r} "
                f"(expected {{'ok': true}}). Model may be ignoring the prompt."
            )
    except Exception as exc:
        raise RuntimeError(
            f"Judge preflight failed for model={judge_model!r}: {type(exc).__name__}: {exc}. "
            f"Fix the model name (HANK_VALS_LOCAL_JUDGE_MODEL env var) or your OPENAI_API_KEY before "
            f"spending money on agent runs."
        ) from exc
```

### 2. `evals/vals-finance-agent/harness/run_local_suite.py` (NEW)

```python
"""Local-judge equivalent of run_vals_suite.py.

Reads public.csv, runs each question through the config's custom_call,
judges with local OpenAI gpt-5.2, writes normalized run.json
(in the same layout aggregator already consumes).
"""
from __future__ import annotations
# ruff: noqa: E402

import argparse
import asyncio
import csv
import json
import os
from pathlib import Path
from typing import Any

from .runtime_paths import ensure_runtime_paths, public_csv_path
ensure_runtime_paths()

# Codex r1 blocker #1: install OutputObject.from_agent_result before configs load.
from .output_object_compat import patch_output_object_compat
patch_output_object_compat()

from . import local_judge

NORMALIZED_SCHEMA_VERSION = "1"
REQUIRED_FIELDS = ("question_id", "passed", "final_answer")
DEFAULT_ALLOW_ERROR_RATE_PCT = 50.0
DEFAULT_ALLOW_JUDGE_ERROR_RATE_PCT = 20.0


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the Vals Finance Agent suite locally (no Vals platform)."
    )
    parser.add_argument(
        "--config", required=True,
        choices=["config_a_hank", "config_b_raw_opus"],
    )
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--parallelism", type=int, default=5)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--judge-model",
        default=os.environ.get("HANK_VALS_LOCAL_JUDGE_MODEL", "gpt-5.2"),
    )
    parser.add_argument("--heavyweight-factor", type=int, default=3)
    parser.add_argument(
        "--dry-judge", action="store_true",
        help="Use deterministic stub judge (no OpenAI cost, for dev iteration)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Limit to first N questions (smoke testing)",
    )
    parser.add_argument(
        "--allow-error-rate", type=float, default=DEFAULT_ALLOW_ERROR_RATE_PCT,
        help="Max %% of questions that may have run errors before run is failed (default 50)",
    )
    parser.add_argument(
        "--allow-judge-error-rate", type=float, default=DEFAULT_ALLOW_JUDGE_ERROR_RATE_PCT,
        help="Max %% of questions that may have judge infra errors before run is failed (default 20)",
    )
    args = parser.parse_args()
    if args.heavyweight_factor < 1:
        parser.error("--heavyweight-factor must be >= 1")
    # Codex r2 should-fix #2: validate --limit in Python (shell wrapper validates too).
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be a positive integer")
    # Codex r3 should-fix #3: asyncio.Semaphore(0) hangs forever; reject early.
    if args.parallelism < 1:
        parser.error("--parallelism must be >= 1")

    # Import the config's custom_model
    if args.config == "config_a_hank":
        from configs.config_a_hank import MODEL_NAME, get_custom_model
    else:
        from configs.config_b_raw_opus import MODEL_NAME, get_custom_model

    custom_call = await get_custom_model(
        MODEL_NAME,
        {"temperature": 0.0, "max_tokens": 32000},
    )

    # Read public.csv
    rows: list[dict[str, str]] = []
    with public_csv_path().open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(row)
            if args.limit and len(rows) >= args.limit:
                break
    if not rows:
        raise RuntimeError(f"public.csv at {public_csv_path()} is empty")

    # Run each question through custom_call (parallelized)
    semaphore = asyncio.Semaphore(args.parallelism)
    judge_client = None
    if not args.dry_judge:
        judge_client = local_judge.make_client()
        # Codex r1 blocker #3: preflight before spending money on agent runs.
        await local_judge.preflight(judge_client, args.judge_model)
        print(f"Judge preflight OK (model={args.judge_model})", flush=True)

    async def process_one(idx: int, row: dict[str, str]) -> dict[str, Any]:
        async with semaphore:
            qid = f"q{idx:03d}"
            question = row["Question"]
            gold = row["Answer"]
            rubric = row.get("Rubric", "")
            question_type = row.get("Question Type", "")

            # 1. Run agent. Codex r2 blocker #3: AgentResult.success=False is a
            # legitimate failure mode that doesn't raise; treat it as run_error.
            try:
                output_obj = await custom_call(
                    test_input=question,
                    files={},
                    context={"question_type": question_type},
                    question_id=qid,
                    run_id=args.run_name,
                )
                model_answer = _extract_answer(output_obj)
                ctx = getattr(output_obj, "output_context", None) or {}
                if ctx.get("success") is False:
                    fe = ctx.get("final_error") or {}
                    run_error = (
                        f"agent failure: [{fe.get('type')}] {(fe.get('message') or '')[:200]}"
                    )
                elif not model_answer.strip():
                    # Codex r3 should-fix #2: empty answer is a real failure even
                    # if the agent reported success. Don't waste judge calls on it.
                    run_error = "empty llm_output (no answer to judge)"
                else:
                    run_error = None
            except Exception as exc:
                model_answer = ""
                run_error = f"{type(exc).__name__}: {exc}"

            # 2. Judge (or stub). NB: rubric_raw is the JSON string from public.csv;
            # local_judge.parse_rubric handles both JSON and free-form fallback.
            if args.dry_judge:
                judge_result = local_judge.stub_judge(model_answer)
            elif run_error:
                # Codex r2 should-fix #1: use `skipped` (not `infra_error`) so the
                # judge-error guard isn't tripped by run failures.
                judge_result = local_judge.JudgeResult(
                    passed=False, vote_count="0/0",
                    skipped=f"skipped (run failed: {run_error})",
                )
            else:
                judge_result = await local_judge.judge_with_heavyweight(
                    judge_client,
                    question=question, gold_answer=gold, rubric_raw=rubric,
                    model_answer=model_answer,
                    judge_model=args.judge_model,
                    heavyweight_factor=args.heavyweight_factor,
                    question_id=qid,
                )

            return {
                "question_id": qid,
                "question": question,
                "context": {"question_type": question_type},
                "tags": [],
                "category": question_type,
                "final_answer": model_answer,
                "passed": judge_result.passed,
                "score": 1.0 if judge_result.passed else 0.0,
                "checks": judge_result.to_dict(),
                "error": run_error,
                "duration_seconds": None,  # could capture but skip for v1
                "tokens": {},  # captured in traces.jsonl for Config A
                "cost": None,
            }

    print(f"Running {len(rows)} questions on {args.config} (judge={args.judge_model}, heavyweight={args.heavyweight_factor}, dry_judge={args.dry_judge})", flush=True)
    tasks = [process_one(i + 1, row) for i, row in enumerate(rows)]
    results = await asyncio.gather(*tasks)

    # Codex r1 blocker #2: error-rate guards. Refuse to write a run.json that
    # masquerades as a real result when most questions crashed at the run step
    # or judge step.
    _enforce_error_rate_guards(results, args)

    # Validate + write (mirrors run_vals_suite.py conventions)
    _validate_required_fields(results)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    eval_model_label = (
        f"{args.judge_model} (local judge)"
        if not args.dry_judge
        else "stub-judge (dry-run, len>100)"
    )

    normalized = {
        "schema_version": NORMALIZED_SCHEMA_VERSION,
        "run_metadata": {
            "config": args.config,
            "run_name": args.run_name,
            "model_name": MODEL_NAME,
            "suite_id": "local-public-50",
            "eval_model": eval_model_label,
            "heavyweight_factor": args.heavyweight_factor,
            "parallelism": args.parallelism,
            "run_id": args.run_name,
            "judge_path": "local",  # NEW field — aggregator uses this for banner
        },
        "results": results,
    }
    (output_dir / "run.json").write_text(
        json.dumps(normalized, indent=2, default=str), encoding="utf-8",
    )
    # No vals_raw.json in local mode (we don't have a Vals export)
    print(f"Wrote {output_dir / 'run.json'}")
    print(f"Pass rate: {sum(1 for r in results if r['passed'])}/{len(results)}")
    return 0


def _extract_answer(output_obj: Any) -> str:
    """vals.sdk.types.OutputObject — only `llm_output` exists in valsai==0.3.9."""
    value = getattr(output_obj, "llm_output", None)
    if value:
        return str(value)
    return ""  # caller treats empty as a run failure if `error` not set


def _enforce_error_rate_guards(results: list[dict[str, Any]], args: argparse.Namespace) -> None:
    """Fail-fast if too many run errors or judge infra errors.

    Without these guards, a broken vendor venv or wrong judge-model name
    silently produces a 0% pass-rate run.json (Codex r1 blocker #2).
    """
    total = len(results)
    run_errors = sum(1 for r in results if r.get("error"))
    # Codex r2 should-fix #1: count only true judge infra failures, NOT
    # judging-skipped-because-run-failed. The latter is already counted as
    # run_errors and would double-count if both flags are tripped.
    judge_errors = sum(
        1 for r in results
        if isinstance(r.get("checks"), dict)
        and r["checks"].get("infra_error")
        and not r["checks"].get("skipped")
    )
    run_pct = 100.0 * run_errors / total
    judge_pct = 100.0 * judge_errors / total
    if run_pct > args.allow_error_rate:
        raise RuntimeError(
            f"Run aborted: {run_errors}/{total} ({run_pct:.0f}%) questions had run-step errors "
            f"(threshold {args.allow_error_rate}%). Inspect first error: "
            f"{next((r['error'] for r in results if r.get('error')), 'n/a')}"
        )
    if judge_pct > args.allow_judge_error_rate:
        raise RuntimeError(
            f"Run aborted: {judge_errors}/{total} ({judge_pct:.0f}%) questions had judge "
            f"infra errors (threshold {args.allow_judge_error_rate}%). Likely model name or "
            f"OpenAI quota issue. Inspect first error: "
            f"{next((r['checks']['infra_error'] for r in results if isinstance(r.get('checks'), dict) and r['checks'].get('infra_error')), 'n/a')}"
        )


def _validate_required_fields(records: list[dict[str, Any]]) -> None:
    if not records:
        raise RuntimeError("Local run returned 0 results")
    issues: list[str] = []
    for index, record in enumerate(records):
        for field in REQUIRED_FIELDS:
            value = record.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                # final_answer can be empty if the run errored — allow IF error is set
                if field == "final_answer" and record.get("error"):
                    continue
                issues.append(f"row[{index}].{field} missing/blank")
        if not isinstance(record.get("passed"), bool):
            issues.append(f"row[{index}].passed is not bool")
    if issues:
        raise RuntimeError(
            f"Local run output validation failed ({len(issues)} issue(s)): "
            + "; ".join(issues[:5])
        )


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

### 3. `evals/vals-finance-agent/scripts/run_local_pair.sh` (NEW)

```bash
#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Flags (mutually exclusive for mode flags, mirrors run_pair.sh)
MODE="full"
DRY_JUDGE=""
LIMIT_ARG=""
JUDGE_MODEL_ARG=""
HEAVYWEIGHT_ARG=""
ALLOW_ERROR_RATE_ARG=""
ALLOW_JUDGE_ERROR_ARG=""
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
    --dry-judge) DRY_JUDGE="--dry-judge"; shift ;;
    --allow-error-rate)
      if [ -z "${2:-}" ]; then echo "--allow-error-rate requires a number" >&2; exit 1; fi
      ALLOW_ERROR_RATE_ARG="--allow-error-rate $2"; shift 2 ;;
    --allow-judge-error-rate)
      if [ -z "${2:-}" ]; then echo "--allow-judge-error-rate requires a number" >&2; exit 1; fi
      ALLOW_JUDGE_ERROR_ARG="--allow-judge-error-rate $2"; shift 2 ;;
    --limit)
      # Codex r1 should-fix #2: validate presence + positive integer.
      if [ -z "${2:-}" ] || ! [[ "$2" =~ ^[0-9]+$ ]] || [ "$2" -le 0 ]; then
        echo "--limit requires a positive integer (got: ${2:-<missing>})" >&2; exit 1
      fi
      LIMIT_ARG="--limit $2"; shift 2 ;;
    --judge-model)
      if [ -z "${2:-}" ]; then
        echo "--judge-model requires a model name" >&2; exit 1
      fi
      JUDGE_MODEL_ARG="--judge-model $2"; shift 2 ;;
    --heavyweight-factor)
      if [ -z "${2:-}" ] || ! [[ "$2" =~ ^[0-9]+$ ]] || [ "$2" -lt 1 ]; then
        echo "--heavyweight-factor requires a positive integer" >&2; exit 1
      fi
      HEAVYWEIGHT_ARG="--heavyweight-factor $2"; shift 2 ;;
    *) echo "Unknown flag: $1" >&2; exit 1 ;;
  esac
done

if [ "$MODE" = "skip-b" ] && [ -z "${HANK_VALS_RUN_TIMESTAMP:-}" ]; then
  echo "--skip-b requires HANK_VALS_RUN_TIMESTAMP to be exported" >&2
  exit 1
fi
export HANK_VALS_RUN_TIMESTAMP="${HANK_VALS_RUN_TIMESTAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
echo "Run timestamp: ${HANK_VALS_RUN_TIMESTAMP} (mode: $MODE, dry_judge=${DRY_JUDGE:-no})"

# shellcheck disable=SC1091
source vendor/finance-agent/.venv/bin/activate
if [ -f vendor/finance-agent/.env ]; then
  set -a; source vendor/finance-agent/.env; set +a
fi
unset DATABASE_URL || true

# Local path env assertions: need OpenAI for judge + ANTHROPIC for model + Tavily/SEC for native tools.
# Do NOT require VALS_API_KEY / VALS_SUITE_ID_PUBLIC_50.
: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY must be set}"
: "${TAVILY_API_KEY:?TAVILY_API_KEY must be set}"
: "${SEC_EDGAR_API_KEY:?SEC_EDGAR_API_KEY must be set}"
if [ -z "${DRY_JUDGE}" ]; then
  : "${OPENAI_API_KEY:?OPENAI_API_KEY must be set (or use --dry-judge for stub mode)}"
fi

run_b() {
  local n="$1"
  local results_dir="results/${HANK_VALS_RUN_TIMESTAMP}/config_b_run${n}"
  mkdir -p "$results_dir"
  python3 -m harness.run_local_suite \
    --config config_b_raw_opus \
    --run-name "hank_local_${HANK_VALS_RUN_TIMESTAMP}_config_b_run${n}" \
    --parallelism "${HANK_VALS_PARALLELISM:-5}" \
    --output-dir "$results_dir" \
    ${DRY_JUDGE} ${LIMIT_ARG} ${JUDGE_MODEL_ARG} ${HEAVYWEIGHT_ARG} ${ALLOW_ERROR_RATE_ARG} ${ALLOW_JUDGE_ERROR_ARG}
}

run_a() {
  local results_dir="results/${HANK_VALS_RUN_TIMESTAMP}/config_a"
  : "${FMP_API_KEY:?FMP_API_KEY must be set for Config A}"
  mkdir -p "$results_dir"
  python3 -m harness.run_local_suite \
    --config config_a_hank \
    --run-name "hank_local_${HANK_VALS_RUN_TIMESTAMP}_config_a" \
    --parallelism "${HANK_VALS_PARALLELISM:-5}" \
    --output-dir "$results_dir" \
    ${DRY_JUDGE} ${LIMIT_ARG} ${JUDGE_MODEL_ARG} ${HEAVYWEIGHT_ARG} ${ALLOW_ERROR_RATE_ARG} ${ALLOW_JUDGE_ERROR_ARG}
}

if [ "$MODE" != "skip-b" ]; then
  run_b 1
  run_b 2
fi

if [ "$MODE" = "b-only" ]; then
  echo "--b-only: skipping Config A + aggregate. Resume with:"
  echo "  HANK_VALS_RUN_TIMESTAMP=${HANK_VALS_RUN_TIMESTAMP} bash scripts/run_local_pair.sh --skip-b ${DRY_JUDGE} ${LIMIT_ARG} ${JUDGE_MODEL_ARG} ${HEAVYWEIGHT_ARG} ${ALLOW_ERROR_RATE_ARG} ${ALLOW_JUDGE_ERROR_ARG}"
  exit 0
fi

# Preflight B artifacts (mirrors run_pair.sh)
for n in 1 2; do
  path="results/${HANK_VALS_RUN_TIMESTAMP}/config_b_run${n}/run.json"
  if [ ! -s "$path" ]; then
    echo "Missing required Config B artifact: $path" >&2
    exit 1
  fi
done

run_a

python3 -m scripts.aggregate_results --run-ts "${HANK_VALS_RUN_TIMESTAMP}"
echo "Done. See results/${HANK_VALS_RUN_TIMESTAMP}/summary.md"
```

### 4. `evals/vals-finance-agent/scripts/aggregate_results.py` (EDIT — surgical)

Three small additions:
1. **Banner in `summary.md`** when any `run_metadata.eval_model` contains `"local"` or `judge_path == "local"`:
   ```markdown
   > ⚠️ **Local-judge run** — judged with `<eval_model>` outside Vals platform.
   > NOT defensible for external "Vals leaderboard" claims; suitable for internal
   > failure-mode analysis and architectural iteration only.
   ```
2. **Top-level `judge_path` field in `summary.json`** (Codex r1 should-fix #4) so machine consumers / CI can branch on judge mode without parsing markdown.
3. **Per-config error/skipped counts in `summary.{md,json}`** (Codex r3 should-fix #1) so sub-threshold judge failures and judge-skipped (run-failed) questions are visible in the summary and don't silently appear as ordinary `failed_no_error` rows. New helper:
   ```python
   def _local_judge_counts(records: list[dict]) -> dict:
       run_errors = sum(1 for r in records if r.get("error"))
       judge_skipped = sum(
           1 for r in records
           if isinstance(r.get("checks"), dict) and r["checks"].get("skipped")
       )
       judge_infra = sum(
           1 for r in records
           if isinstance(r.get("checks"), dict)
           and r["checks"].get("infra_error") and not r["checks"].get("skipped")
       )
       return {"run_errors": run_errors, "judge_skipped": judge_skipped, "judge_infra_errors": judge_infra}
   ```
   Surface in `summary["scores"]["config_a_health"]` / `config_b_run{1,2}_health`. Render in `summary.md` as a small "Run health" table per config; bold a warning if any count > 0.

Implementation: ~25 lines total in `_render_summary_md` (banner near top + health table per config) + 5 lines in `main()` to compute counts + add `summary["judge_path"]`. Helper: `is_local_judge(metadata) -> return "local" in (metadata.get("eval_model") or "").lower() or metadata.get("judge_path") == "local"`. Use Config A's metadata as the source of truth (Config B in local mode also has `judge_path=local`; mixed-mode runs would be weird and worth a warning).

### 5. `evals/vals-finance-agent/.env.example` (EDIT — surgical)

Add one line + comment:
```
# Required for local-judge mode (scripts/run_local_pair.sh).
# Not needed when using scripts/run_pair.sh against the official Vals platform.
OPENAI_API_KEY=
```

### 6. `evals/vals-finance-agent/README.md` (EDIT — surgical)

Add a new section after "Run Modes":
```markdown
## Local-judge mode (no Vals platform required)

If you don't have `VALS_API_KEY`, run with the local OpenAI gpt-5.2 judge:

bash scripts/run_local_pair.sh

Requires `OPENAI_API_KEY` in vendor `.env` instead of `VALS_API_KEY`. Replicates
Vals methodology approximately (same judge model family, same heavyweight=3
mode-of-3 vote, same prompt shape) but is NOT a substitute for official Vals
scoring for external claims. Outputs land at `results/<ts>/summary.md` with a
prominent local-judge banner.

For dev iteration without OpenAI cost: `bash scripts/run_local_pair.sh --dry-judge --limit 3`.
```

---

## Critical files referenced (read-only)

- `docs/planning/VALS_FINANCE_AGENT_IMPL_PLAN.md` §3.4.1 — local-judge fallback explicitly contemplated
- `docs/planning/VALS_FINANCE_AGENT_PRODUCTION_RUN_PLAN.md` — sibling plan for the official path
- `evals/vals-finance-agent/harness/run_vals_suite.py` — `_safe_attr`, `_validate_required_fields`, `_normalize_result` patterns reused
- `evals/vals-finance-agent/harness/hank_model.py:127-172` — `get_custom_model` signature; `custom_call(test_input, files, context, question_id, run_id)` is the contract our local runner invokes
- `evals/vals-finance-agent/harness/runtime_paths.py` — `ensure_runtime_paths()`, `public_csv_path()`
- `evals/vals-finance-agent/scripts/run_pair.sh` — orchestrator pattern (mutex flags, preflight loop, mode handling) reused in `run_local_pair.sh`
- `evals/vals-finance-agent/scripts/aggregate_results.py:18-30` — `tier()` function unaffected; `_render_summary_md` gets a banner-prepending edit
- `evals/vals-finance-agent/vendor/finance-agent/data/public.csv` — input data (Question, Answer, Question Type, Expert time, Rubric)
- `evals/vals-finance-agent/vendor/finance-agent/finance_agent/run_agent.py:18-64` — vendor's `run_tests_parallel` is the orchestration pattern reference

**Pre-installed in vendor venv (no `uv pip install` needed):** `openai==2.29.0`, `valsai==0.3.9` (for OutputObject), `model_library==0.1.23`.

---

## Verification

1. **Static**:
   - `python3 -c "import ast; [ast.parse(open(p).read()) for p in ['evals/vals-finance-agent/harness/local_judge.py', 'evals/vals-finance-agent/harness/run_local_suite.py', 'evals/vals-finance-agent/scripts/aggregate_results.py']]"` (parse)
   - `bash -n evals/vals-finance-agent/scripts/run_local_pair.sh`

2. **Stub-judge end-to-end smoke (no OpenAI cost):**
   ```bash
   bash scripts/run_local_pair.sh --dry-judge --limit 3
   ```
   - Confirms wrapper still imports, custom_call works, normalized run.json is well-formed, aggregator produces summary.md with local-judge banner.
   - Cost: ~$3 (3 questions × 2 configs × ~$0.20 each Hank Opus call). Stub judge = $0.

3. **Real-judge spot-check (1 question, real OpenAI call):**
   ```bash
   bash scripts/run_local_pair.sh --limit 1
   ```
   - Confirms OpenAI client works, judge prompt produces parseable JSON, mode-of-3 vote aggregates correctly.
   - Cost: ~$2.

4. **End-to-end full run (all 50 questions):**
   ```bash
   bash scripts/run_local_pair.sh
   ```
   - Cost estimate: ~$40 (~$15 Config A Hank + ~$6 Config B×2 + ~$11 OpenAI judge × 600 calls).
   - Outputs: `results/<ts>/summary.md` with local-judge banner + Config A pass rate + Config B mean + delta + per-category breakdown + head-to-head A/B classification.

5. **Cross-check sanity:** Config B mean should still land in the ballpark of Anthropic's published 64.4% (within ±10pp tolerance — wider than official-mode ±5pp because local judge introduces methodology variance). If Config B drops dramatically (e.g. 30%), the local judge prompt is too strict and needs prompt-tuning before trusting Config A delta.

---

## Sequencing

1. **Codex review of THIS plan** → iterate to PASS (next step in this session)
2. Codex implements via `mcp__codex__codex` per CLAUDE.md conventions (no `model` override, `approval-policy: "never"`, `sandbox: "workspace-write"`, `cwd: /Users/henrychien/Documents/Jupyter/risk_module`)
3. Verification §1 + §2 (no OpenAI cost, ~$3 Hank cost) — soft test
4. Provision OPENAI_API_KEY in vendor .env (operational — user action)
5. Verification §3 (1-question real-judge spot-check)
6. Verification §4 (full 50-question baseline) — first real Hank-vs-Opus delta number
