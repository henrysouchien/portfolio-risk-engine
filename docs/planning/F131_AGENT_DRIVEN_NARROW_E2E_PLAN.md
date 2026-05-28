# F131 Agent-Driven Narrow E2E Plan

**Status:** PARTIALLY IMPLEMENTED 2026-05-27 — enablement + harness shipped in `AI-excel-addin`; a GREEN live run is blocked on the autonomous-approval pass-through fix.
  - **Enablement** (the permission infra F131 needed): `portfolio_config` class split `cfd8ef4e`; unified `research_producer` profile + skill-server denylist `c4d268dc`.
  - **Harness:** PR-0 auditor `31d13601`, PR-1 live runner `fd95a8ec`, PR-2 live-gated pytest `8b2233d8`, preflight fix `9b61d560`.
  - **First live PCTY run executed** — validated the harness end-to-end and caught the real blocker: the autonomous approval gate auto-denies `state_write` in headless mode (tools granted/visible but `headless_auto_deny`). Fix spec: `AI-excel-addin/docs/design/tool-policy-autonomous-approval-passthrough-task.md` (DRAFT, needs Codex review → implement). Bug + repro: `AI-excel-addin/docs/TODO.md`.
  - **Remaining:** the approval-passthrough fix (blocker) → PR-3 (green live run + replay fixtures) → PR-4 (this closeout). Strict-audit half `blocked_on_F125`. Runbook: `AI-excel-addin/docs/F131_E2E_TEST_RUNBOOK.md`.
  - Codex review history (R1 BLOCK → R2 BLOCK → R3 PASS) preserved below.
**Date:** 2026-05-26
**Owner:** Thesis & Research Artifact autonomous-loop workstream
**Primary implementation repo:** `/Users/henrychien/Documents/Jupyter/AI-excel-addin`
**Tracking repo:** `/Users/henrychien/Documents/Jupyter/risk_module`

## Revision Log

- **R1 (2026-05-26):** Initial draft, sent to Codex for plan review.
- **R2 (2026-05-26):** Incorporated Codex R1 BLOCK findings. Changes:
  1. Claim-handle / excerpt-link semantics pinned to the *actual* `evidence_audit.py`
     behavior. The auditor now adds a hard "cited source_ref resolves to a SourceRecord"
     check (the existing `validate_excerpt_links` ignores missing refs), and splits
     `claim_ids` matching into stable-ID sections (strict) vs path-derived sections
     (warn until F125 emits stable handles).
  2. Added `## Storage And Identity Boundary` - the runner must seed and read through
     the *same* resolved user + storage + MCP/API path the autonomous agent uses; no
     in-process test repository for the F131 container.
  3. Added a pre-launch MCP tool-availability preflight before spending a live run.
  4. Demoted F125-dependent acceptance items (path-derived `claim_ids` matching, R6
     same-target claim/data-gap detection) from hard gates to `blocked_on_f125`
     warnings - the current `DataGap` schema has no target field to compare on.
  5. Strengthened the workbook assertion from sheet-names-only to sheet-names + at
     least one populated value per required sheet.
  6. Clarified the zero-patch/insufficient-data criterion as conditional, and split
     fixtures into a success-path and an insufficient-data-path case.
  7. Fixture replay must assert round-trip through `Thesis.model_validate` + strict
     audit + handoff finalization status + workbook manifest checks.
- **R3 (2026-05-26):** Incorporated Codex R2 BLOCK findings (2 must-fixes). Changes:
  1. Resolved an internal contradiction R2 introduced: `validate_excerpt_links(require_excerpts=True)`
     raises uniformly on `claim_ids` mismatch (evidence_audit.py:85-88), so it cannot serve
     as a hard gate while path-derived mismatches stay warn-only. The auditor now runs its own
     **classified citation walk** instead, and PR-0 adds an additive `handle_is_stable_id` flag
     to `ClaimCitation` to route stable-ID vs path-derived deterministically. No change to
     `validate_excerpt_links` behavior for existing callers.
  2. Pinned the `--task` **dev-mode requirement**: `entry.py:1010-1011` rejects `--task`
     unless `ANALYST_DEV_MODE=true` (read at import, `analyst.py:62`). The runner sets it,
     the preflight asserts it, and the preflight resolves the catalog under the dev-mode
     profile config (dev mode can exclude tools).

## Executive Summary

F131 is not another direct integration test. It closes the test gap between "the APIs work when called in the right order" and "an autonomous LLM agent can discover the right tools, call them in the right order, write a defensible Thesis, finalize a handoff, and build a workbook."

The current repo has useful API-level and MCP-level tests:

- `AI-excel-addin/tests/integration/test_investment_schema_spine_e2e.py` proves the direct spine can seed research, finalize handoff, build a model, read model insights, and patch Thesis state.
- `AI-excel-addin/scripts/live_autonomous_thesis_read_smoke.py` proves a live autonomous agent can call `thesis_read` with the correct user identity.
- `AI-excel-addin/api/research/evidence_audit.py` already has the core claim-to-excerpt validator, including `validate_excerpt_links(..., require_excerpts=True)`.

What is missing is a live, bounded, LLM-in-the-loop run that exercises the wired write surface from the agent side and then runs strict post-run audits over the resulting artifacts.

The fix is a two-tier harness:

1. A live-gated F131 runner that launches the real autonomous analyst path against an isolated ticker/label and captures the full transcript plus artifact IDs.
2. A deterministic auditor that can validate the live output and replay/sanitized fixtures in default CI.

F131 is allowed to ship the harness before every F125 strict write-path gate lands. A live run is "hard-gate green" when every positive Layer 2 claim traces `Thesis.sources[] -> SourceRecord.excerpts[]` and stable-ID sections also resolve `Excerpt.claim_ids`. F131 is **not** marked *fully* complete until the F125-dependent checks (path-derived `claim_ids`, R6 same-target, carry-forward rationale) also pass; until then those are tracked as `blocked_on_f125` warnings. See `## Strict Acceptance Criteria` for the hard-gate vs blocked-on-F125 split.

## Root Issue

The current tests verify the API contracts and model-build spine directly. They do not verify the agent contract.

Direct tests bypass the fragile parts that matter for the autonomous loop:

- Tool discovery and tool selection.
- Prompt and skill instructions.
- Turn sequencing across research, Thesis writes, handoff finalization, and model build.
- User identity propagation through autonomous MCP/gateway paths.
- Decisions-log discipline, including zero-patch verdicts.
- Evidence discipline when the agent must decide whether to write a claim or a data gap.

That means the current suite can pass while a real agent still fails the demo path.

## Current-State Findings

### Existing spine coverage

`AI-excel-addin/tests/integration/test_investment_schema_spine_e2e.py` calls MCP/API helpers directly:

- `mcp_research.start_research`
- repository handoff mutation/finalization
- `mcp_model_build_context.get_model_build_context`
- `mcp_research.build_model`
- `mcp_research.apply_patch_ops`
- `mcp_thesis.thesis_read`

This is valuable, but it is not LLM-in-the-loop.

### Existing live autonomous smoke

`AI-excel-addin/scripts/live_autonomous_thesis_read_smoke.py` already shows the correct pattern for live verification:

- Load environment from AI-excel-addin, `api/.env`, and risk_module.
- Resolve the gateway MCP user entry.
- Confirm the session token maps to the numeric `risk_user_id`.
- Optionally run `python -m agent.autonomous --profile analyst --task ...`.

That script proves one read path. F131 should reuse its environment/identity pattern, but broaden the task and post-run audits.

### Agent entry points exist

The autonomous path is available through:

- Direct subprocess: `python -m agent.autonomous --profile analyst --task "..."`
- Wrapper: `scripts/run_analyst.py --profile analyst --task "..."`
- MCP sidecar: `agents-mcp.agent_run_start/status/wait/logs/cancel`

For F131, the harness should use the subprocess path as the canonical live test runner. The sidecar can be documented as an operator-friendly alternate launch path, but the pytest wrapper should not depend on a separately running MCP server.

### Strict evidence audit already has a base helper

`AI-excel-addin/api/research/evidence_audit.py` provides:

- `iter_claim_citations(payload)`
- `validate_excerpt_links(thesis, require_excerpts=True)`

`require_excerpts=True` defines the strict semantics F131 reproduces (no-excerpt = failure).
But the auditor does **not** call `validate_excerpt_links` directly as the hard gate - see
finding #3 below and the classified citation walk in the auditor section.

**Two behaviors of the existing helper that F131 must account for (Codex R1):**

1. `validate_excerpt_links(..., require_excerpts=True)` does **not** fail on a citation
   whose `source_ref` resolves to no `SourceRecord`; it silently skips unresolved refs.
   So "every cited source exists" is NOT enforced by this helper. The F131 auditor must
   add a **separate hard check** that every `source_ref` emitted by `iter_claim_citations`
   resolves to an entry in `Thesis.sources[]`.

2. `iter_claim_citations` only emits a stable explicit claim ID for a fixed key list
   (`_CLAIM_ID_KEYS`: `claim_id`, `assumption_id`, `risk_id`, `catalyst_id`, `trigger_id`,
   `coincidence_id`, `factor_id`, `watch_item_id`, `driver_id`, `id`); for all other
   sections it emits a **path-derived handle** (e.g. `business_overview...`, from the dotted
   path in `_claim_handle`). Path-derived sections do not expose stable IDs the agent can
   reliably echo into `Excerpt.claim_ids`. (Note: the existing `validate_excerpt_links`
   helper *does* enforce `claim_ids` matching for path-derived handles too - see finding #3 -
   but the F131 audit **policy** intentionally relaxes that to warn-only, because the agent
   cannot satisfy it before F125.) So the F131 auditor enforces strict `claim_ids` matching
   only for stable-ID sections; for path-derived sections it is a **warning until F125**
   makes the write path emit (or generate) stable handles. This is the same F125 dependency
   as the R6 detector below - do not invent a permanent F131-only handle scheme.

3. **`validate_excerpt_links` raises uniformly on a `claim_ids` mismatch** (evidence_audit.py
   lines 85-88), for stable-ID *and* path-derived handles alike, and it does so regardless
   of `require_excerpts` (that flag only controls the separate "resolved source has zero
   excerpts" branch). Consequence (Codex R2): the auditor **cannot** call
   `validate_excerpt_links(require_excerpts=True)` wholesale as a single hard check while
   treating path-derived mismatches as warnings - the helper would hard-fail the
   path-derived case too. The F131 auditor must instead run its **own classified citation
   walk** (reusing `iter_claim_citations` + the `sources_by_id` map) so it can route
   stable-ID mismatches to errors and path-derived mismatches to warnings. `evidence_audit.py`
   itself is NOT modified except for one additive change (a stable-vs-path flag on
   `ClaimCitation`, see PR-0) - existing production callers of `validate_excerpt_links`
   keep their current strict behavior.

### Model-build output can be asserted directly

`BuildModelOrchestrator` writes model files to:

```text
repo.exports_dir() / f"model_{research_file_id}_v{handoff_version}.xlsx"
```

The current generic template expects these sheets:

- `Assumptions`
- `Financial_model`
- `Valuation`
- `Scenarios`

The F131 auditor should open the built `.xlsx` with `openpyxl` and assert (a) at least those
sheet names exist, and (b) each required sheet is **non-empty** - at least one populated
(non-None, non-blank) cell value per sheet. Sheet-names-only would pass a structurally
correct but empty workbook (Codex R1, finding 6), which does not prove the build succeeded.

## Desired Outcome

One command can run the live F131 check:

```bash
RUN_F131_LIVE=1 pytest tests/integration/test_f131_agent_driven_narrow_e2e.py -q -s
```

The test:

1. Creates or reserves an isolated research file for a real ticker, default `PCTY`.
2. Launches the autonomous analyst as a subprocess with a structured task.
3. Lets the agent call tools freely inside its configured profile.
4. Collects run metadata, transcript tail, research file ID, thesis ID, handoff ID, model path, and decisions-log IDs.
5. Runs strict post-run assertions over the durable Thesis, handoff, and workbook.
6. Writes a local run report under an ignored operational output directory.

Default CI should not run the live LLM path. It should run the deterministic audit helpers and a sanitized fixture replay.

## Non-Goals

- Do not turn paid LLM calls into default CI.
- Do not mock the LLM and call that F131 complete.
- Do not count a direct API sequence as success.
- Do not require F128 idea-to-thesis automation for this slice. The harness may create the isolated research container; the agent must perform the research/Thesis/handoff/model loop.
- Do not execute trades or portfolio-affecting operations.
- Do not loosen evidence acceptance for the live gate. Existing excerptless rows can remain readable, but the F131 artifact must pass strict audit.

## Storage And Identity Boundary

This is the single highest-risk integration gap (Codex R1, finding 4). The two patterns F131 borrows from resolve storage differently:

- `test_investment_schema_spine_e2e.py` uses scoped, in-process repository factories and direct helpers.
- `live_autonomous_thesis_read_smoke.py` uses env-loaded gateway identity and a real subprocess.

If F131 seeds the research container through an in-process repository but the autonomous subprocess reads/writes through the live gateway MCP path under a different resolved user or storage root, the run fails as `artifact_id_missing` or silently mutates the wrong workspace.

**Binding rule:** the F131 runner MUST seed and audit through the **same resolved user identity and the same storage/MCP-API path** that the autonomous subprocess uses. Concretely:

- Resolve the autonomous user identity first (the numeric `risk_user_id` the gateway maps the session token to), exactly as `live_autonomous_thesis_read_smoke.py` does. Use that identity for the seed, the post-run reads, and the audit. Never hard-code a user.
- Seed the isolated research container via the same live MCP/API surface the agent will use, not via an in-process test repository factory. The seed creates only the empty container; the agent owns all substantive writes.
- Post-run artifact lookup (Thesis, handoff, model path) must query the same storage the agent wrote to, keyed by the resolved user + (ticker, label).
- Record the resolved user ID and the storage root in `run_report.json` so a mismatch is diagnosable.
- A mismatch between seed-path storage and agent-read storage is its own failure category: `seed_storage_mismatch`.

### Dev-mode requirement for `--task` (Codex R2, finding 2)

The canonical `python -m agent.autonomous --profile analyst --task ...` path is **dev-mode
gated**: `entry.py:1010-1011` raises `ValueError("--task requires ANALYST dev mode to be
enabled")` unless `profile.dev_mode_enabled` is true, and the analyst profile reads that from
`ANALYST_DEV_MODE` at import time (`analyst.py:62`, accepts `1`/`true`/`yes`). So the F131
runner MUST set `ANALYST_DEV_MODE=true` in the subprocess environment **before** the
subprocess starts Python (the flag is read at module import, not per-call). If it is unset,
the run dies instantly with a `ValueError` (surfaced as `agent_nonzero_exit`). The runner
sets it explicitly and the preflight asserts it is set.

Two consequences for the preflight:

- Resolve the MCP catalog under the **dev-mode profile config**, not the default profile.
  Dev mode can exclude tools (`dev_excluded_tools` / `dev_mode_excluded_tools`,
  `entry.py:613`); the preflight must check the catalog the dev-mode run will actually use,
  or it can pass while the live run is missing a tool.

### Pre-launch MCP tool preflight

Before spending a live run, assert (under the resolved autonomous identity, with
`ANALYST_DEV_MODE=true`) that the analyst profile's **dev-mode** MCP catalog actually exposes
the mutating/deferred tools the task requires - at minimum the research/thesis write tools,
`finalize_handoff`, and `build_model`. The analyst profile must be able to *discover and
invoke* these, not just have them defined somewhere. If any required tool is absent from the
resolved catalog, fail fast as `preflight_tool_unavailable` before launching the subprocess.
This converts a multi-hour silent live failure into a fast preflight error (seconds; MCP
client startup is not necessarily sub-second, but it is bounded and runs before the agent loop).

## Architecture

### 1. Live runner

Add a small runner module in AI-excel-addin:

```text
tests/integration/f131_agent_loop.py
```

Responsibilities:

- Resolve repo paths and environment, and set `ANALYST_DEV_MODE=true` in the subprocess
  environment (required for `--task`; read at import - see Dev-mode requirement above).
- Resolve the autonomous user identity (numeric `risk_user_id`) and storage root first,
  per `## Storage And Identity Boundary`. All seeding, reads, and audits use this identity.
- Run the pre-launch MCP tool preflight (under dev-mode config); fail fast as
  `preflight_tool_unavailable` if a required write tool is missing from the resolved catalog.
- Create a unique run label, for example `F131 live 2026-05-26 <shortid>`.
- Create or locate the research file for `(ticker, label)` under the resolved user, via the
  same live MCP/API path the agent uses (not an in-process test repository).
- Build the agent task prompt.
- Launch the autonomous analyst subprocess.
- Stream/capture stdout and stderr to a run artifact directory.
- Return structured metadata to the pytest wrapper.

The subprocess should run (with `ANALYST_DEV_MODE=true` in its environment):

```bash
ANALYST_DEV_MODE=true python -m agent.autonomous --profile analyst --task "$F131_TASK"
```

Use the real autonomous profile and tool routing. Do not call `apply_patch_ops`, `finalize_handoff`, or `build_model` from the test harness until after the agent run finishes.

### 2. Agent task prompt

The prompt should be bounded, explicit, and artifact-oriented:

```text
F131 live e2e. Ticker: PCTY. Research label: <label>.

Use the portfolio/research MCP tools to run a narrow research-to-model loop.
Use public filing/transcript/company/market sources as needed. Do not fabricate.

Required durable outputs:
- A Thesis for the specified research file with company, thesis statement,
  differentiated view, business overview, risks, catalysts or invalidation
  triggers, assumptions or valuation, sources with excerpts, and decisions_log.
- Positive factual/analytical claims must cite source_refs that resolve to
  SourceRecord.excerpts with matching claim_ids.
- If evidence is missing, write a data_gap and do not write the unsupported
  positive claim.
- Finalize handoff.
- Build a model to file.
- In the final answer, report research_file_id, thesis_id, handoff_id,
  model_path, and decisions_log entry IDs.
```

The prompt should tell the agent what success looks like, but not hard-code the exact tool sequence. F131 is testing whether the agent can use the tool surface.

### 3. Deterministic auditor

Add a pure audit helper in AI-excel-addin:

```text
api/research/thesis_e2e_audit.py
```

This helper should be independent from the live runner and usable by tests, scripts, and future production diagnostics.

Minimum API:

```python
@dataclass(frozen=True)
class ThesisE2EAuditReport:
    ok: bool
    errors: list[str]
    warnings: list[str]
    claim_count: int
    source_count: int
    excerpt_count: int
    decisions_log_count: int

def audit_f131_thesis(thesis: Thesis) -> ThesisE2EAuditReport: ...
def assert_f131_thesis(thesis: Thesis) -> None: ...
```

The auditor classifies each check as **hard** (failure blocks the F131 gate) or
**warn-until-F125** (reported in `warnings`, does not block, tracked as `blocked_on_f125`).
This split is what makes the strict acceptance criteria actually verifiable today; see
`## Current-State Findings` for why path-derived handles and R6 cannot be hard gates yet.

The auditor does **not** call `validate_excerpt_links(require_excerpts=True)` as the single
hard gate (it raises uniformly on path-derived mismatches; see Current-State Findings #3).
Instead it runs its **own classified citation walk** over `iter_claim_citations(payload)`
against `sources_by_id`, applying the matrix below. This reproduces the helper's strictness
for everything verifiable today while routing path-derived mismatches to warnings.

Hard checks (block the gate):

- Required sections are present and non-empty:
  - `company`
  - `thesis.statement`
  - `differentiated_view`
  - `business_overview` or `industry_analysis`
  - `risks` or `invalidation_triggers`
  - `assumptions` or `valuation` or `quantitative_framing`
  - `sources`
  - `decisions_log`
- **Source resolution (hard):** every `source_ref` emitted by `iter_claim_citations`
  resolves to an entry in `Thesis.sources[]`. (`validate_excerpt_links` silently `continue`s
  on unresolved refs at evidence_audit.py:77-78, so this is a net-new check.)
- **Excerpt presence (hard):** every resolved cited source has at least one excerpt
  (equivalent to the `require_excerpts=True` no-excerpt branch).
- **`claim_ids` match for stable-ID sections (hard):** when the citing `claim_handle` came
  from `_CLAIM_ID_KEYS` (stable ID), at least one excerpt on the resolved source lists that
  handle in `claim_ids`.

Warn-until-F125 checks (reported, do not block; surface as `blocked_on_f125`):

- **`claim_ids` mismatch for path-derived handles.** The classified walk routes these to
  warnings, not errors. Path-derived handles are not stable until F125 makes the write path
  emit them. (This is exactly the case where calling `validate_excerpt_links` wholesale
  would have wrongly hard-failed.)
- No same-target claim/data-gap conflicts. The current `DataGap` schema
  (`gap_id`, `description`, `workaround`, `severity`) has **no target/path/claim-handle
  field** to compare against claims, so R6 cannot be evaluated. Call the F125 detector once
  it exists.
- Every material update in `decisions_log.patch_ops_applied` has fresh source refs or an
  explicit carry-forward rationale. Promote to hard once F125 exposes the carry-forward helper.

Important dependency note: R6 same-target validation and stable claim handles are owned by
F125 write-time enforcement. F131 calls the same helpers once they exist; it must never be
marked complete on a weaker, permanent F131-only approximation. Until F125 lands, a live run
that passes all hard checks but still carries `blocked_on_f125` warnings is recorded as
"harness green, strict gate blocked on F125" - not as F131 complete.

### 4. Pytest wrapper

Add:

```text
tests/integration/test_f131_agent_driven_narrow_e2e.py
```

Behavior:

- Skip unless `RUN_F131_LIVE=1`.
- Require live provider credentials and a configured autonomous user.
- Use a long but bounded subprocess timeout from `F131_TIMEOUT_SECONDS`, default 7200.
- Fail with a concise transcript tail and path to the full run report.
- Never print API keys, session tokens, or raw environment.

Suggested marker addition:

```ini
markers =
  eval: external eval tests that use the judge model and may require ANTHROPIC_API_KEY
  live_llm: live LLM tests that may spend money and call external tools
```

### 5. Fixture replay

After the first green live run, add sanitized fixtures for **two paths** (Codex R1, finding 7):

```text
# success path: agent produced a fully evidence-backed thesis + finalized handoff + model
tests/integration/fixtures/f131_agent_loop/pcty_green_thesis.json
tests/integration/fixtures/f131_agent_loop/pcty_green_handoff.json
tests/integration/fixtures/f131_agent_loop/pcty_green_model_manifest.json

# insufficient-data path: agent correctly wrote data_gaps + a zero-patch decisions-log entry
tests/integration/fixtures/f131_agent_loop/pcty_insufficient_thesis.json
tests/integration/fixtures/f131_agent_loop/pcty_insufficient_decisions_log.json
```

The two-path split resolves the ambiguity in the acceptance criteria: a *positive* live run
is not expected to contain a zero-patch entry, but the auditor must still prove the
insufficient-data branch is logged correctly when it occurs. The insufficient-data fixture
exercises that branch deterministically without a second live run.

Fixture replay must do more than parse JSON. For each fixture the replay test must assert
(Codex R1, finding 8):

- The fixture round-trips through `Thesis.model_validate` (catches schema drift).
- `assert_f131_thesis` produces the expected report (hard checks pass for the green fixture;
  the insufficient fixture shows the data_gap + zero-patch decisions-log entry).
- Handoff fixture reflects finalized status for the green case.
- Model manifest fixture reflects the expected sheet set and non-empty markers.

Default CI should run:

```bash
pytest tests/integration/test_f131_agent_driven_narrow_e2e.py -q
```

Without `RUN_F131_LIVE=1`, the test runs fixture replay only. That keeps the strict audit
helper from drifting while avoiding paid live runs by default.

## Implementation Plan

### PR-0 - Shared audit helper

Repo: `AI-excel-addin`

Files:

- `api/research/thesis_e2e_audit.py`
- `tests/api/research/test_thesis_e2e_audit.py`

Tasks:

1. Create `ThesisE2EAuditReport` with separate `errors` (hard) and `warnings`
   (`blocked_on_f125`) lists.
2. Implement required-section checks.
3. **Additive change to `evidence_audit.py`:** add a `handle_is_stable_id: bool` field to
   `ClaimCitation` and set it in `iter_claim_citations` (True when `_claim_handle` resolved
   from `_CLAIM_ID_KEYS`, False when it fell back to the dotted path). This is purely
   additive - it does not change `validate_excerpt_links` behavior, so existing callers are
   unaffected. Verify `test_evidence_audit.py` still passes.
4. Implement the **classified citation walk** in the auditor (do NOT call
   `validate_excerpt_links` as the hard gate - it raises uniformly on path-derived
   mismatches). Reuse `iter_claim_citations` + a `sources_by_id` map and apply:
   - `source_ref` resolves to no source -> hard error (`audit_source_unresolved`).
   - resolved source has no excerpts -> hard error (`audit_excerpt_missing`).
   - `claim_ids` mismatch and `handle_is_stable_id` -> hard error (`audit_claim_id_mismatch`).
   - `claim_ids` mismatch and NOT `handle_is_stable_id` -> warning (`blocked_on_f125`).
5. Confirm the classified walk reproduces `validate_excerpt_links`'s strict outcome for the
   stable-ID + no-excerpt cases (regression parity), differing only by routing path-derived
   mismatches to warnings.
6. Add source/excerpt count diagnostics.
7. Add a placeholder adapter for F125 R6/R9 helpers:
   - If helper exists, call it.
   - If helper is absent, return a warning (`blocked_on_f125`) and keep F131 TODO open.
   - Do NOT implement a weaker permanent R6 against the current `DataGap` schema.
8. Add unit tests for:
   - Fully valid excerpt-backed Thesis (hard checks pass, no warnings).
   - Missing required section.
   - Cited `source_ref` that resolves to no source (hard error - the new check).
   - Source with no excerpt.
   - Stable-ID excerpt with mismatched `claim_ids` (hard error).
   - Path-derived section with unmatched `claim_ids` (warning, not error).
   - Empty decisions log.

Acceptance:

- `pytest tests/api/research/test_thesis_e2e_audit.py -q`
- Existing `tests/api/research/test_evidence_audit.py` still passes.

### PR-1 - Live runner

Repo: `AI-excel-addin`

Files:

- `tests/integration/f131_agent_loop.py`
- `scripts/live_f131_agent_driven_e2e.py`
- `tests/scripts/test_live_f131_agent_driven_e2e.py`

Tasks:

1. Resolve the autonomous identity and storage root first (per `## Storage And Identity
   Boundary`): numeric `risk_user_id` from the gateway session-token mapping, plus the
   storage root the autonomous MCP tools read/write. This identity is used for seed, reads,
   and audit.
2. Set `ANALYST_DEV_MODE=true` in the subprocess env (required for `--task`), then run the
   MCP tool preflight under the resolved identity **and dev-mode profile config** (dev mode
   can exclude tools). If a required write tool (`finalize_handoff`, `build_model`,
   thesis/research write tools) is missing from the resolved dev-mode catalog, abort as
   `preflight_tool_unavailable` before launching.
3. Build an isolated run context:
   - ticker default `PCTY`
   - unique label
   - resolved user ID (not env-guessed)
   - artifact directory under an ignored output path
4. Seed only the empty research container, via the same live MCP/API path the agent uses
   (not an in-process test repository). Verify the seed is readable under the resolved
   identity before launch; mismatch is `seed_storage_mismatch`.
5. Launch `ANALYST_DEV_MODE=true python -m agent.autonomous --profile analyst --task ...`.
6. Capture subprocess stdout/stderr and normalized metadata.
7. Parse or recover artifact IDs (querying the same storage the agent wrote to):
   - Prefer final-answer IDs.
   - Fall back to repository lookup by resolved-user + ticker/label.
8. Write `run_report.json` with:
   - run ID
   - resolved user ID and storage root (for mismatch diagnosis)
   - command shape without secrets
   - elapsed seconds
   - subprocess return code
   - preflight result
   - research file ID
   - thesis ID
   - handoff ID
   - model path
   - decisions-log count
   - audit report (errors + `blocked_on_f125` warnings)
9. Keep operational output out of git.

Acceptance:

- Unit tests prove command construction (incl. `ANALYST_DEV_MODE=true` in the subprocess
  env), secret redaction, final-answer ID parsing, repository fallback, identity resolution,
  and the preflight abort path (missing tool -> `preflight_tool_unavailable`, no subprocess
  launched).
- Script `--dry-run` prints the prompt/command metadata and the resolved identity/storage
  root without starting the LLM or spending budget.

### PR-2 - Live-gated pytest

Repo: `AI-excel-addin`

Files:

- `tests/integration/test_f131_agent_driven_narrow_e2e.py`
- `pytest.ini`

Tasks:

1. Add `live_llm` marker.
2. Add fixture-replay test that always runs if fixture files exist.
3. Add live test skipped unless `RUN_F131_LIVE=1`.
4. For live mode, call the PR-1 runner and then:
   - Load final Thesis.
   - Run `assert_f131_thesis`.
   - Confirm latest handoff is finalized.
   - Confirm model path exists and has `.xlsx` suffix.
   - Open workbook with `openpyxl`.
   - Assert sheets include `Assumptions`, `Financial_model`, `Valuation`, `Scenarios`,
     and that each required sheet has at least one populated cell (non-empty workbook).
5. Make failure messages point to the run report and transcript file.

Acceptance:

- Default command does not call the LLM:
  ```bash
  pytest tests/integration/test_f131_agent_driven_narrow_e2e.py -q
  ```
- Live command is explicit:
  ```bash
  RUN_F131_LIVE=1 pytest tests/integration/test_f131_agent_driven_narrow_e2e.py -q -s
  ```

### PR-3 - First live run and fixture capture

Repo: `AI-excel-addin`

Tasks:

1. Run the live test against `PCTY`.
2. If strict audit fails because current write paths still create excerptless claims, record the exact failing write path and link it back to F125. Do not downgrade F131 acceptance.
3. If strict audit passes, sanitize fixture outputs and commit replay fixtures.
4. Update runbook docs with:
   - env vars
   - command
   - expected runtime/cost class
   - where reports are written
   - how to interpret failure categories

Acceptance:

- One green live report exists locally.
- Fixture replay passes in default CI.

### PR-4 - Risk-module TODO closeout

Repo: `risk_module`

Tasks:

1. Update `docs/TODO.md` F131 from plan drafted to implementation status.
2. Link the final AI-excel-addin commit(s) and live report summary.
3. Move F131 to completed only after the strict live run passes.

Acceptance:

- F131 TODO status reflects reality:
  - plan drafted
  - harness implemented
  - live run blocked on F125
  - or strict live pass

## Strict Acceptance Criteria

The criteria split into a **hard gate** (all must pass for a live PASS) and a
**blocked-on-F125** set (reported as warnings; F131 cannot be marked *fully* complete while
any remain open, but a hard-gate-green run is a valid, recorded milestone).

### Hard gate (must all pass for a live PASS)

1. The runner resolved the autonomous identity and storage root, and seeded through the
   same live path the agent reads (no storage mismatch).
2. The MCP tool preflight passed (required write tools present in the resolved catalog).
3. The agent ran through the real autonomous entry point.
4. The agent created or updated the target Thesis.
5. Required Thesis sections are populated.
6. Every cited `source_ref` resolves to a `SourceRecord` in `Thesis.sources[]`
   (the dedicated hard check, not just `validate_excerpt_links`).
7. Every cited `SourceRecord` that resolves contains at least one `Excerpt`.
8. For stable-ID sections, at least one `Excerpt.claim_ids` entry matches each citing claim.
9. `decisions_log` has at least one entry and captures the run path.
10. **If** the agent hit an insufficient-data / zero-patch outcome, it is visible as a
    decisions-log entry. (A positive run need not contain one; the insufficient-data fixture
    proves the branch is logged when it occurs.)
11. `finalize_handoff` succeeds and the latest handoff is finalized.
12. `build_model` succeeds.
13. The produced `.xlsx` exists, contains `Assumptions`, `Financial_model`, `Valuation`,
    and `Scenarios`, and each required sheet has at least one populated cell.
14. The run report is secret-redacted (incl. resolved user ID / storage root, not tokens)
    and includes enough detail to reproduce failures.

### Blocked-on-F125 (warn now, required for *full* completion)

15. Path-derived sections: `Excerpt.claim_ids` matches the citing path handle. Requires
    F125 stable handles.
16. No same-target claim/data-gap pairs. Requires a `DataGap` target field + the F125 R6
    detector; not evaluable against the current schema.
17. Every material `decisions_log.patch_ops_applied` update has fresh source refs or an
    explicit carry-forward rationale. Requires the F125 carry-forward helper.

## Failure Categories

The runner should classify failures so the next owner knows where to work:

- `preflight_tool_unavailable` - a required write tool is absent from the resolved MCP
  catalog; aborted before launch (no budget spent).
- `seed_storage_mismatch` - the seeded research container is not readable under the
  resolved identity/storage the agent uses.
- `agent_timeout` - subprocess exceeded the live run budget.
- `agent_nonzero_exit` - autonomous subprocess exited nonzero.
- `artifact_id_missing` - agent completed but artifact IDs could not be recovered.
- `thesis_missing` - no Thesis exists for the target research file.
- `audit_required_section_missing` - durable Thesis is structurally incomplete.
- `audit_source_unresolved` - a cited `source_ref` resolves to no `SourceRecord` (hard).
- `audit_excerpt_missing` - a resolved source has no excerpt (hard).
- `audit_claim_id_mismatch` - a stable-ID section's excerpt `claim_ids` do not match the
  citing claim (hard). Path-derived mismatches are `blocked_on_f125`, not this.
- `decisions_log_missing` - no decisions-log entry recorded.
- `handoff_not_finalized` - latest handoff absent or not finalized.
- `build_model_failed` - build tool failed or did not produce a file.
- `workbook_shape_invalid` - workbook missing expected sheets, or a required sheet is empty.
- `blocked_on_f125` - a warn-tier audit gap maps to a known F125 write-path dependency
  (path-derived `claim_ids`, R6 same-target, carry-forward rationale).

## Multi-User Requirements

F131 must be safe to run on a shared machine:

- Use the configured autonomous user identity, not a hard-coded user.
- Include the resolved user ID in the run report.
- Use a unique label per run.
- Never reuse another run's research label by default.
- Never write into another user's workspace or database.
- Keep all operational artifacts under an ignored run-output directory.
- Redact API keys, JWTs, session tokens, and signed claim headers from logs.

## Open Questions for Codex Review

1. Should the live runner seed the empty research file itself, or should the agent call `start_research` from scratch?
   - Recommendation: seed only the isolated research container so the test can recover artifact IDs reliably. The agent still owns all substantive writes.
   - **Codex R1 resolution (RESOLVED):** seed it, but only via the same live MCP/API path and resolved user the agent uses. The original recommendation was unsafe without the storage/identity boundary now pinned in `## Storage And Identity Boundary`.
2. Should the canonical launch path be direct subprocess or `agents-mcp.agent_run_start`?
   - Recommendation: direct subprocess for pytest reliability; document `agents-mcp` as an operator path.
   - **Codex R1 resolution (RESOLVED):** agreed. CLI entry confirmed at `api/agent/autonomous/entry.py` (`python -m agent.autonomous --profile ... --task ...`).
3. Should F131 introduce the R6 claim/data-gap detector, or wait for F125?
   - Recommendation: call the F125 detector when available. Do not invent a weaker permanent F131-only definition.
   - **Codex R1 resolution (RESOLVED):** wait for F125. The current `DataGap` schema has no target field, so R6 is not evaluable today. F131 reports it as `blocked_on_f125` only.
4. Should fixture replay commit source excerpt text?
   - Recommendation: yes for public-company filings/transcripts only, with a minimal sanitized fixture and no secrets/session data.
   - **Codex R1 resolution (RESOLVED):** agreed, with the constraint that the excerpt text be large enough to make strict replay meaningful (round-trip + audit), and never include session logs, tokens, private notes, or full transcripts.

## Recommended Next Step

Implement PR-0 and PR-1 together in AI-excel-addin. That creates the strict audit surface and a dry-runnable live harness without yet spending LLM budget. After that, run PR-2 default tests, then schedule the first explicit live F131 run.
