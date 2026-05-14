# Vals Finance Agent — Config C Plan (Hank-via-Dev-CLI)

Status: **R9** — addresses Codex R8 findings on stdout parsing, parallelism, session-id sanitization, preflight. Pending Codex R9 review.

This plan adds a third configuration to the Vals Finance Agent benchmark suite:
**Config C — Hank-via-Dev-CLI**, which runs the user's already-running Hank
gateway (full product, full tool surface) by invoking the existing
`agent_gateway_cli` per question.

| Config | What it isolates |
|---|---|
| B (raw Opus) | Raw model on the vendor harness |
| A (Hank tools, vendor loop) | Vendor agent loop with Hank's curated tool set |
| **C (Hank-via-dev-CLI)** | **Hank-the-product, end-to-end, via the same CLI you already use to chat with it** |

---

## 0. Iteration Changelog

R1–R7.4 (deleted): tried to build our own gateway runtime — factory functions, `McpClientManager` subclasses, `submit_final_result` IPC, process-group teardown, code-execution config, identity-boundary preflight, ~900 lines.

R8 (replaced): thin wrapper around the existing dev CLI. Architecture sound but had 4 Codex blockers:

| # | R8 finding | R9 fix |
|---|---|---|
| 1 | Stdout parser used divider blocks; CLI default render is event-log style (`[text]` streaming, interleaved `[tool_call_start]`/`[tool_complete]`/`[done]`), no divider-bounded final block | Use CLI's `--raw` mode and parse the `[raw] {...json...}` lines for `assistant_text_append` normalized events. Concatenate `payload.text` from those events. Phase 1 PASS gate verifies on a real run. |
| 2 | Parallelism=3 unsafe — gateway uses a per-(user, conversation_id) stream lock at `proxy.py:223-225` and CLI doesn't set `conversation_id`, so concurrent calls from same dev user 409 with "A chat stream is already active" | Default parallelism=1. Consistent across §4.2 and §7.R3. |
| 3 | `--session <question_id>` may fail — CLI session names must match `[A-Za-z0-9_-]{1,64}`; Vals question IDs may not | Sanitize: `re.sub(r'[^A-Za-z0-9_-]', '_', qid)[:64]` |
| 4 | "import preflight" is too weak — verifies the module imports but not that the gateway is actually reachable | `run_config_c.sh` now smoke-runs `agent_gateway_cli chat --new --session vals_smoke "hi"` and asserts exit 0 + non-empty answer. Real connectivity check. |

Architecture (subprocess the CLI per question) unchanged — only the four mechanics fixed.

---

## 1. Framing

Config A asks: "do Hank's tools beat raw Opus when you keep the loop fixed?"
Config C asks: "does Hank-as-product beat raw Opus end-to-end?"

C tests **literally the running Hank** — same gateway, same MCP servers from
the user's `~/.claude.json`, same dev user, same auth, same model the
gateway is configured for. If you can chat with Hank locally, you can run
Config C.

---

## 2. Architecture

Per-question runtime, repeated for each of the 50 questions:

```
Vals SDK Suite.run(model=custom_call_c, ...)
  └─ for each test_input (question):
       custom_call_c(test_input, files, context, question_id, run_id)
         ├─ subprocess.run([
         │      sys.executable, "-m", "agent_gateway_cli", "chat",
         │      "--session", _sanitize_session_id(question_id),  # safe per CLI session-name regex
         │      "--new",                     # truncate session before send
         │      "--raw",                     # emit "[raw] {json}" SSE events alongside render
         │      "--auto-approve", "*",       # no human-in-the-loop
         │      test_input,                  # question text as positional arg
         │   ], capture_output=True, timeout=20*60)
         ├─ parse "[raw] {json}" lines from stdout, concatenate text from
         │    assistant_text_append events
         ├─ write trace row → traces.jsonl
         └─ return OutputObject(llm_output=final_answer, ...)
```

That's it. No subprocess for the gateway (already running). No HTTP wiring
on our side (the CLI does it). No MCP curation (the gateway already has
the user's full surface). No IPC (CLI prints the answer to stdout).
No process cleanup (CLI exits when done).

---

## 3. Driver Implementation

### 3.1 Config module — `configs/config_c_hank_gateway.py`

```python
from harness.hank_devcli_model import get_custom_model

# Vals metadata uses the provider-prefixed name for run-name labeling.
# The gateway model is whatever the running gateway is configured for —
# we don't override it.
MODEL_NAME = "anthropic/claude-opus-4-7"
RUN_NAME_PREFIX = "hank_vals_run_config_c"

__all__ = ["MODEL_NAME", "RUN_NAME_PREFIX", "get_custom_model"]
```

### 3.2 Driver — `harness/hank_devcli_model.py`

Single file. Implements the Vals SDK custom-model contract:

```python
import asyncio
import sys
import time
from typing import Any

from . import trace_logger
from .output_object_compat import build_output_object_from_text


CLI_TIMEOUT_SECONDS = 20 * 60   # 20-minute hard cap per question
CLI_MODULE = "agent_gateway_cli"


async def get_custom_model(model_name: str, parameters: dict[str, Any], *_args, **_kwargs):
    """Return a Vals SDK custom-call coroutine that invokes the dev CLI per question."""

    async def custom_call(
        test_input: str,
        files: dict[str, Any],
        context: dict[str, Any],
        question_id: str,
        run_id: str,
    ):
        _ = files, run_id
        start = time.monotonic()

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", CLI_MODULE, "chat",
            "--session", _sanitize_session_id(str(question_id)),
            "--new",
            "--raw",                                     # R9: emit raw SSE events for parsing
            "--auto-approve", "*",
            test_input,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=CLI_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            stdout_bytes, stderr_bytes = b"", b"timeout"

        duration = time.monotonic() - start
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        final_answer = _extract_final_answer(stdout)

        trace_logger.write_devcli(
            question_id=str(question_id),
            question=test_input,
            question_type=context.get("question_type"),
            duration_seconds=duration,
            cli_exit_code=proc.returncode,
            stdout_bytes=len(stdout_bytes),
            stderr_tail=stderr[-2000:],
            final_answer_chars=len(final_answer),
        )

        if proc.returncode != 0:
            print(f"FAIL {question_id}: CLI exit {proc.returncode}\n{stderr[-2000:]}\n")

        return build_output_object_from_text(
            text=final_answer,
            duration=duration,
            success=proc.returncode == 0,
        )

    return custom_call
```

### 3.3 Final-answer extraction — `_extract_final_answer(stdout)` (R9)

The CLI in `--raw` mode emits a `[raw] {json}` line per SSE event alongside
the rendered output (`cli.py:489-491`). The driver parses `[raw]` lines,
JSON-decodes, normalizes via the CLI's own `dispatch_event`, and
concatenates text from `assistant_text_append` events (the streaming
text deltas the CLI accumulates into `assistant_parts` at `cli.py:522-525`).

```python
import json
import re
from agent_gateway_cli.sse import dispatch_event

_RAW_PREFIX = "[raw] "

def _extract_final_answer(stdout: str) -> str:
    parts: list[str] = []
    for line in stdout.splitlines():
        if not line.startswith(_RAW_PREFIX):
            continue
        try:
            event = json.loads(line[len(_RAW_PREFIX):])
        except json.JSONDecodeError:
            continue
        normalized = dispatch_event(event)
        if normalized is None:
            continue
        if normalized.name == "assistant_text_append":
            text = str(normalized.payload.get("text", "") or "")
            if text:
                parts.append(text)
    return "".join(parts).strip()
```

This is the same code path the CLI itself uses to render `[text]` lines —
we just consume the parsed events instead of letting the CLI render them.
If the CLI's SSE event normalization changes, both render and parse break
together (no extra coupling).

Phase 1 PASS gate: extraction returns non-empty text matching a known
expected answer for one canned question.

### 3.3a Session-ID sanitization (R9)

```python
import re
_SESSION_RE = re.compile(r"[^A-Za-z0-9_-]")

def _sanitize_session_id(qid: str) -> str:
    safe = _SESSION_RE.sub("_", qid)
    return safe[:64] or "vals_unknown"
```

CLI requires session names match `[A-Za-z0-9_-]{1,64}` (`agent_gateway_cli/session.py:validate_session_name`); Vals question IDs may include `:` / `/` / spaces / etc.

### 3.4 OutputObject shim — `harness/output_object_compat.py`

Add a `build_output_object_from_text(text, *, duration, success)` helper using the verified `valsai` constructor signature:

```python
OutputObject(
    *,
    llm_output: str,
    output_context: dict | None = None,
    duration: float | None = None,
    in_tokens: int | None = None,
    out_tokens: int | None = None,
    cost: float | None = None,
)
```

Token / cost fields are not available from the dev CLI's stdout, so we
omit them. Duration is wall-clock from the driver. `output_context`
gets `{"success": success, "source": "hank_devcli"}`.

### 3.5 Trace logger — `harness/trace_logger.py` (new helper)

Add `write_devcli(...)` that appends a JSONL row to
`results/<ts>/config_c/traces.jsonl` with:
- `question_id`, `question`, `question_type`
- `duration_seconds`
- `cli_exit_code`
- `stdout_bytes`, `stderr_tail`
- `final_answer_chars`
- (No tokens / cost — not available from CLI stdout. Aggregator's
  `_run_telemetry` will see those as None, which it already handles.)

---

## 4. Vals Integration

### 4.1 Extend `harness/run_vals_suite.py` AND `harness/run_local_suite.py`

Both files add `config_c_hank_gateway` to the `--config` choices. Existing
`_normalize_result` and `_validate_required_fields` paths require no
change — Config C's `OutputObject` provides `final_answer`, `passed`,
`question_id` via the standard contract.

### 4.2 New script — `scripts/run_config_c.sh`

Mirror of `run_config_a.sh` minus the per-config env hardening:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

: "${HANK_VALS_RUN_TIMESTAMP:?must be exported}"

RESULTS_DIR="results/${HANK_VALS_RUN_TIMESTAMP}/config_c"
mkdir -p "$RESULTS_DIR"

# shellcheck disable=SC1091
source vendor/finance-agent/.venv/bin/activate

# Vals platform creds
: "${VALS_API_KEY:?must be set}"
: "${VALS_SUITE_ID_PUBLIC_50:?must be set}"

# Confirm the CLI module is importable in this venv (else the subprocess will fail).
python3 -c "import agent_gateway_cli" || {
  echo "agent_gateway_cli not installed in vendor venv; run: uv pip install agent-gateway-cli" >&2
  exit 1
}

# R9: real connectivity smoke — verify Hank is running AND reachable AND answers.
echo "Smoke-testing connection to Hank gateway..."
SMOKE_OUT=$(python3 -m agent_gateway_cli chat \
  --new --session vals_smoke --raw --auto-approve "*" \
  "Reply with a single word: ready" 2>&1) || {
    echo "Smoke test FAILED. Is Hank running and is the CLI configured to reach it?" >&2
    echo "Re-run 'python -m agent_gateway_cli login' if config is missing." >&2
    echo "$SMOKE_OUT" | tail -50 >&2
    exit 1
}
if ! echo "$SMOKE_OUT" | grep -q '"type":"text_delta"\|\[text\]'; then
    echo "Smoke test produced no assistant text. Run aborted." >&2
    echo "$SMOKE_OUT" | tail -50 >&2
    exit 1
fi
echo "Smoke test passed."

python3 -m harness.run_vals_suite \
  --config config_c_hank_gateway \
  --run-name "hank_vals_${HANK_VALS_RUN_TIMESTAMP}_config_c" \
  --parallelism "${HANK_VALS_PARALLELISM:-1}" \
  --output-dir "${RESULTS_DIR}"
```

Note (R9): parallelism is **1**. The gateway proxy uses a per-(user, conversation_id) stream lock at `app_platform/gateway/proxy.py:223-225` and the CLI does not set `conversation_id` (only `context.purpose=="research_workspace"` paths do, per `proxy.py:200-205`). Concurrent calls from the same dev user 409 with "A chat stream is already active." If Phase 4 measures unsafe contention, follow-up either bumps to 1 permanently or extends the CLI/driver to set per-question `thread_id`.

### 4.3 Extend `scripts/run_pair.sh` → optional `--with-c`

Add an opt-in flag `--with-c` that runs Config C after Config A. Default
behavior unchanged so existing runs and CI keep working.

```bash
bash scripts/run_pair.sh --with-c       # B run1, B run2, A, C, aggregate
bash scripts/run_pair.sh --c-only       # presumes prior B×2 + A artifacts
```

Mutually exclusive with `--b-only` / `--skip-b` (validated up front).

---

## 5. Aggregator Extension

`scripts/aggregate_results.py` extends backward-compatibly: if
`config_c/run.json` is absent, behavior is identical to today.

Functions to extend (gated on `config_c is not None`):

| Function | Extension |
|---|---|
| `_load_run` → new helper `_load_run_optional` | Returns None if file missing |
| `_with_categories` | Also for C records |
| `_records_by_qid` | Also for C |
| `_traces_by_qid` | Also for C-traces |
| `_score_summary`, `_local_judge_counts` | Also for C |
| `_per_category` | Add `config_c_pass_rate_pct`, `delta_c_minus_b_mean_pp`, `delta_c_minus_a_pp` |
| `_head_to_head_3way` (new) | C↔A and C↔B-mean buckets |
| `_run_telemetry` for C | Tokens/cost fields absent — uses what's there |
| `histograms` | C `cli_exit_code` distribution |
| `trace_coverage` | C trace coverage rendered alongside A |
| `_render_summary_md`, `_render_run_log_md` | Each section gated on C presence |
| `is_local_judge` | Reads C metadata too |
| `_has_health_warning` | Iterate over `("config_a_health", "config_b_run1_health", "config_b_run2_health", "config_c_health")` |

`tier()` is **NOT** extended — A-anchored, see §5.4.

### 5.4 Tier-table boundary (DEFERRED)

Keep tier as a single A-anchored metric. C is reported as additional
context (deltas A-C, B-C). C-anchored tier is a separate decision if
needed for product PR.

### 5.5 Backward-compat gate

Phase 3 PASS gate runs `aggregate_results.py` against an existing 2-way
fixture and asserts byte-identical output.

---

## 6. Implementation Phases

### Phase 1 — Driver + extraction + OutputObject shim
- Implement `harness/hank_devcli_model.py` (the driver per §3.2).
- Implement `_extract_final_answer(stdout)` per §3.3.
- Extend `harness/output_object_compat.py` with `build_output_object_from_text` per §3.4.
- Extend `harness/trace_logger.py` with `write_devcli` per §3.5.
- Implement `configs/config_c_hank_gateway.py`.
- Smoke: invoke `custom_call` directly with one canned question while Hank is running. Assert (a) CLI exits 0, (b) `OutputObject.llm_output` is non-empty, (c) trace row written.
- **PASS gate**: 1-question end-to-end smoke green.

### Phase 2 — Vals + local-suite integration
- Extend `harness/run_vals_suite.py` and `harness/run_local_suite.py` with `config_c_hank_gateway` choice.
- Add `scripts/run_config_c.sh` per §4.2.
- Smoke: `--dry-judge --limit 3` via `run_local_suite.py` produces a Config-C `run.json` that loads in `aggregate_results.py` shape.
- **PASS gate**: 3-question dry run yields valid `run.json` + `traces.jsonl`.

### Phase 3 — Aggregator extension + pipeline
- Extend `scripts/aggregate_results.py` per §5.
- Backward-compat snapshot test on existing 2-way fixture: byte-identical output.
- 3-way fixture renders C-aware summary cleanly.
- Extend `scripts/run_pair.sh` with `--with-c` and `--c-only`.
- Update `evals/vals-finance-agent/README.md`: prereq is "Hank gateway running locally; `agent_gateway_cli` importable in vendor venv."
- **PASS gate**: `bash scripts/run_pair.sh --with-c` end-to-end on 5-question subset succeeds.

### Phase 4 — Production smoke + first real run
- Verify Hank is running; run the 50-question full suite with Vals platform judge.
- Inspect `summary.md`: assert C ran 50/50, `cli_exit_code` distribution dominated by 0, no obvious extraction failures (final_answer_chars > 0 for all rows).
- **PASS gate**: first production-judged Config C result published.

---

## 7. Risks & Open Questions

### R1 — Gateway must be running
If Hank isn't started, the run fails immediately. The script preflight
prints a hint (§4.2) but doesn't try to start it. User responsibility.
Acceptable since it's a one-time start before the run.

### R2 — Final-answer extraction is regex-fragile
`_extract_final_answer` parses CLI stdout. If `agent_gateway_cli`
changes its render format (currently dividers + assistant blocks), the
parser breaks. Mitigation: small parser, smoke-tested in Phase 1.
Fix-on-break is one function. Also: Phase 4 audit checks
`final_answer_chars > 0` for every row.

### R3 — Single-gateway parallelism
Multiple per-question CLI calls running concurrently share one gateway,
which uses a per-(user, conversation_id) stream lock (`app_platform/gateway/proxy.py:223-225`)
— concurrent requests for the same dev user with no `conversation_id` 409
with "A chat stream is already active." (`conversation_id` is only set
for `context.purpose=="research_workspace"`, which the CLI does not use.)
Mitigation: parallelism=1 default in §4.2 (R9). Raising parallelism would
require either threading per-question `purpose`/`thread_id` through the CLI
or running multiple dev users — out of scope.

### R4 — Per-question session isolation
`--new` truncates the named session's history before each send. As long
as `--session <question_id>` is unique per question and `--new` works as
documented, no cross-question contamination. Smoke-verify in Phase 1.

### R5 — Editorial memory / thesis state pollution
The dev user's editorial memory and thesis records do persist across
runs. If Hank's behavior is meaningfully driven by accumulated state,
multiple Config C runs are not clean-slate. Surface in trace + Phase 4
notes; if score drift is observed across runs, follow-up plan adds a
per-run user reset.

### R6 — Token / cost telemetry absent
The CLI doesn't expose tokens / cost on stdout. C run telemetry rows
will have `None` for these fields. `_run_telemetry` already handles
None, but the Telemetry table will show "N/A" for C cost / tokens.
Acceptable for V1; future extension could parse the CLI's `--raw` SSE
events for usage info.

### R7 — Trade-execution tools dispatchable but inert
Same as R3 in prior iterations: dev user has no preview rows; trade
tools fail-fast at preview lookup. If Phase 4 shows >5% wasted turns on
`execute_*`, follow-up adds a server-side denylist (not in this plan).

---

## 8. Out of Scope

- Spawning the gateway ourselves (R1–R7.4 — done with that).
- Per-tool curation / allowlisting / deny-listing.
- Identity preflight against `data_sources` / `accounts` etc. (you control the running Hank's identity; we don't double-check).
- Token / cost telemetry from CLI stdout (R6).
- C-anchored tier table.
- Full warm-pool / production-fidelity multi-user runs.

---

## 9. Acceptance Criteria

This plan is COMPLETE when:

- [ ] `bash scripts/run_pair.sh --with-c` runs end-to-end on 50 questions
- [ ] `results/<ts>/summary.md` shows A, B run1, B run2, **and C** scores in the same table, with deltas A-B, C-B, C-A
- [ ] `results/<ts>/config_c/traces.jsonl` has 50 rows
- [ ] `results/<ts>/config_c/run.json` passes `_validate_required_fields`
- [ ] All 50 rows have `final_answer_chars > 0` (no extraction failures), or extraction failures are logged with stdout dumps for inspection
- [ ] Backward-compat snapshot test on existing 2-way fixture is byte-identical

---

## 10. References

- `app.py:7789` — `/api/gateway` mount
- `app_platform/gateway/proxy.py:192` — gateway chat proxy handler (frontend uses this)
- `app_platform/gateway/proxy.py:223` — per-user stream lock (R3)
- `app_platform/gateway/models.py:10` — `GatewayChatRequest` shape
- `~/Documents/Jupyter/AI-excel-addin/packages/agent-gateway-cli/agent_gateway_cli/cli.py` — dev CLI source
  - `cli.py:37` — `DIVIDER = "-" * 60` (used by stdout extraction §3.3)
  - `cli.py:783` — actual flags: `--raw`, `--session`, `--new`, `--auto-approve`
- `evals/vals-finance-agent/README.md` — runbook (Phase 3 updates this)
- `evals/vals-finance-agent/scripts/aggregate_results.py` — aggregator (Phase 3 extends this)
