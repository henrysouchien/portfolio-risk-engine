# F85c-followup — Resilient canonicalizer (retry-once-then-escalate-to-Opus)

**Status**: R4 — Codex R3 FAIL (0 P1 + 2 P2). Removed unsourced "CLAUDE.md 4.X" quote (R2 now points to Anthropic docs / Codex config as source of truth); test-count consistency synced to 9 across S5/§6/checklist.
**Date**: 2026-05-15
**Owner**: Henry
**Repo scope**: AI-excel-addin (canonicalizer module + tests). risk_module = plan + TODO update only.
**Parent**: F85c live-verify open follow-up (`project_f85c_canonical_bucket_helper_shipped.md` §"Open follow-up").

---

## 1. Purpose

Close the canonicalizer-reliability gap surfaced by F85c live-verify on 2026-05-15: at `temperature=0`, Haiku 4.5 occasionally returns a `duplicate_member_phrase` proposal (one input phrase placed in two buckets), which D4 validation correctly rejects → `canonicalize_kpi_observations` returns `failed_passthrough`. Production skill methodology currently aborts on `failed_passthrough` — correct for safety but brittle. The verify driver retried once on Haiku and succeeded; production has no such retry.

F85c-followup ships a new `resilient_llm_canonicalizer` factory that wraps Haiku-then-Opus with bounded retry. `default_llm_canonicalizer` stays unchanged (preserves existing-test back-compat per Codex R0 P1). The skill markdown flips its Step 3.5 call site to the new factory and updates 2 doc-clarification lines; no behavior contract change for skill consumers.

---

## 2. Audit findings

### 2.1 Current canonicalizer factory (`api/agent/skills/_industry_onboarding_canonicalizer.py:95-111`)

```python
def default_llm_canonicalizer(*, model: str | None = None) -> LLMCanonicalizer:
    resolved = resolve_auth_config(read_env_auth_mode=True, raise_on_missing=True)
    # ... OAuth assertions ...
    client = CanonicalizerClient(
        auth_mode="oauth",
        auth_token=auth_token,
        model=_resolve_model_alias(model),
    )
    return client.canonicalize
```

Single-shot — returns the bound `client.canonicalize` async method. No retry, no escalation.

### 2.2 Validation surface (`api/agent/skills/industry_onboarding.py:983`)

`_validate_canonical_proposal(proposal, contexts) -> tuple[dict[str, Any], ...]` is the **cross-validation** D4 validator (called from `canonicalize_kpi_observations` at line 317). Returns empty tuple when valid; non-empty list of structured rejection reasons when not. Possible reasons returned by THIS function: `duplicate_member_phrase`, `duplicate_canonical_name`, `hallucinated_member_phrase`, `canonical_name_collision_outside_member_set`, `canonical_name_collision_class_mismatch`. **Currently module-private**; needs to be reachable from the canonicalizer module.

**Important distinction**: `invalid_class_hint` is NOT returned by `_validate_canonical_proposal`. Bad class hints are rejected earlier by the Pydantic field validator on `CanonicalBucketProposal` (`industry_onboarding.py:131`), surfaced via `CanonicalizationResult.rejection_reasons` with reason code `proposal_schema_invalid` (see `test_industry_onboarding_canonicalization.py:273`). **Schema-validation failures are NOT retryable** (D2); only cross-validation failures from `_validate_canonical_proposal` trigger retry.

### 2.3 Live-verify evidence (`investment_tools/analyst_dev/reports/2026-05-15-grocers-F85C-live-verify.md:44`)

Per the F85c verify report: first Haiku call produced a `duplicate_member_phrase` violation (`"fuel gallons sold year-over-year change"` placed in two buckets); retry-once on Haiku succeeded cleanly with a 29-bucket valid proposal. Temperature=0 on Haiku 4.5 OAuth is "mostly but not perfectly deterministic" per the run report. (The `decisions_log.yaml` in the staging dir captures only the second-attempt success at lines 21-25; the report MD has the full attempt-by-attempt audit at `:44`.)

### 2.4 Cost envelope

Per F85c plan estimates: Haiku ~$0.05/call, Opus ~$0.30/call. F85c-followup worst case (both Haiku attempts fail, Opus runs) = Haiku × 2 + Opus = ~$0.40 per canonicalization. F85c live-verify total run was $2.52; worst case escalation adds ~$0.30. F85b live-verify ceiling is $5/onboarding — F85c-followup stays comfortably under.

---

## 3. Decisions

### D1 — Architecture: new factory, `default_llm_canonicalizer` unchanged, skill md flips call site

**Decision**: Add `resilient_llm_canonicalizer(*, primary_model="claude-haiku-4-5-20251001", fallback_model="claude-opus-4-7", primary_retries=1, validator=None) -> LLMCanonicalizer` factory in `_industry_onboarding_canonicalizer.py`. The wrapper composes two single-model canonicalizers (via existing `default_llm_canonicalizer(model=...)`) and runs them in sequence per D2/D3 policy.

**`default_llm_canonicalizer(*, model=None)` is UNCHANGED** — same single-shot semantics, same `CanonicalizerClient.canonicalize` bound-method return. All existing F85c tests that introspect `canonicalizer.__self__` (e.g., `test_default_canonicalizer_requires_oauth` at `tests/skills/test_industry_onboarding_canonicalization.py:564,578`) continue to pass without modification.

**Skill markdown changes its call site**: `industry-onboarding.md` Step 3.5 (the `await canonicalize_kpi_observations(...)` wrapper) flips from `default_llm_canonicalizer()` → `resilient_llm_canonicalizer()`. This is the production opt-in path. Single-model `default_llm_canonicalizer(model="haiku")` / `(model="opus")` remains the dev/test escape hatch.

**Rationale**:
- Codex R0 P1: existing tests assume `default_llm_canonicalizer()` returns a bound `CanonicalizerClient.canonicalize` method with `__self__`. The wrapper returns an inner async function. Changing `default_llm_canonicalizer` would break those tests. Cleaner to leave it alone.
- Production opt-in to resilience is explicit (caller picks the factory), which is easier to reason about than a behavioral change inside `default_llm_canonicalizer`.
- Composition pattern; can stub each layer independently in tests.
- The `validator` injection allows tests to deterministically force retry/escalation without spinning up real LLM calls.

### D2 — Retry trigger: cross-validation failure only (not schema / not network)

**Decision**: The wrapper retries/escalates ONLY when `validate_canonical_proposal` (the renamed cross-validator from D5) returns a non-empty rejection list. Other failure categories pass through unchanged:
- **Pydantic `ValidationError`** raised by `CanonicalizerClient.canonicalize` (malformed JSON shape, bad class_hint per field validator at `industry_onboarding.py:131`) → propagates immediately, no retry. These are schema errors, not stochastic LLM glitches.
- **`anthropic.APIError`, network timeouts, etc.** → propagate immediately, no retry. Network errors are a different failure category.

**Concretely, retryable reason codes** (returned by `validate_canonical_proposal`): `duplicate_member_phrase`, `duplicate_canonical_name`, `hallucinated_member_phrase`, `canonical_name_collision_outside_member_set`, `canonical_name_collision_class_mismatch`. These are the cross-validation failures where Haiku produced structurally valid JSON but a semantically-invalid bucket assignment.

**Non-retryable reason code** (surfaced via Pydantic at validation entry, NOT by `validate_canonical_proposal`): `proposal_schema_invalid` (covers invalid class_hint, missing fields, type errors). Behavior depends on call site: **wrapper-direct callers** (e.g., F85c-followup unit tests calling `resilient_llm_canonicalizer()` directly) see the Pydantic exception propagate. **End-to-end callers** going through `canonicalize_kpi_observations` continue to observe today's existing behavior: it catches all `Exception` from the canonicalizer at `industry_onboarding.py:305` and converts to `CanonicalizationResult(status="failed_passthrough", rejection_reasons=[{"reason": "proposal_schema_invalid", ...}])` at `:306`. F85c-followup does not change that catch-and-convert layer.

**Rationale**: The observed failure mode is "structurally valid JSON, semantically invalid bucket assignment." Retrying solves that. Schema errors and network errors are different categories; retrying them blindly hides bugs and burns budget. F85c-followup matches recommendation scope to problem scope per `feedback_no_structural_recs_without_context`. Future plan can add network-error retry if observed in production.

### D3 — Retry policy: 1 Haiku retry + 1 Opus attempt; bounded `primary_retries`

**Decision**: Total LLM calls = `(primary_retries + 1) + 1` (primary attempts including initial + one fallback attempt). Default `primary_retries=1` → up to 3 LLM calls worst case.

- Attempt 1 (Haiku) → validate → return on success.
- Attempt 2 (Haiku) → validate → return on success.
- Attempt 3 (Opus) → validate → return on success OR return last-attempt proposal regardless.

**`primary_retries` bounds** (Codex R0 P1): factory raises `ValueError` when `primary_retries < 0`. Hard upper bound NOT enforced in code (power users may want higher; misconfiguration risk is low for an internal-only factory), but the wrapper documents the cost formula explicitly: worst-case cost = `(primary_retries + 1) × haiku_call_cost + opus_call_cost`. At default (1), worst case ~$0.40 per canonicalization.

**Rationale**: F85c verify ran retry-once on Haiku and succeeded; that's the proven floor. Escalation to Opus handles the rare case where Haiku consistently fails (e.g., a tricky industry the smaller model can't reason through). One Opus attempt is enough — if Opus also fails, `canonicalize_kpi_observations` will return `failed_passthrough` via D4 just as today, and the skill methodology can surface the error.

**Tunable**: `primary_retries` exposed as a kwarg (default 1) for power users / future increases. Validated at construction time.

### D4 — Failure-mode contract: wrapper returns last-attempt proposal

**Decision**: When all attempts fail D4 validation, the wrapper returns the LAST attempt's proposal (Opus's). `canonicalize_kpi_observations` runs `_validate_canonical_proposal` again and produces `status="failed_passthrough"` with the canonical rejection-reason list.

**Rationale**: Wrapper's return type is `Awaitable[CanonicalBucketProposal]`; raising on failure breaks the contract. Letting `canonicalize_kpi_observations` make the final call keeps validation in one canonical place. Tests still observe `failed_passthrough` end-to-end when all attempts fail.

**Side effect**: the FINAL `_validate_canonical_proposal` call by `canonicalize_kpi_observations` runs at the same cost as the wrapper's internal validation (pure function, no LLM). Acceptable double-check.

### D5 — Validator promotion: `_validate_canonical_proposal` → `validate_canonical_proposal`

**Decision**: Rename `_validate_canonical_proposal` to `validate_canonical_proposal` (drop the leading underscore) in `industry_onboarding.py` and export it. The wrapper imports it from `industry_onboarding`. Add a brief docstring.

**Rationale**: The validator now has a legitimate external caller (the wrapper in the sibling module). The underscore prefix signals "module-private" which is no longer accurate. Per `feedback_data_config_not_code` and general "public when actually public" hygiene.

**Migration**: 1 rename in `industry_onboarding.py` + N call-site updates (the function is called from one place inside `canonicalize_kpi_observations`; tests may also reference it).

### D6 — Logging: structured per-attempt logs

**Decision**: Wrapper emits structured single-line logs at INFO level per attempt:
```
canonicalizer.attempt | role=primary attempt=1 model=claude-haiku-4-5-20251001 outcome=ok buckets=12
canonicalizer.attempt | role=primary attempt=2 model=claude-haiku-4-5-20251001 outcome=invalid reasons=["duplicate_member_phrase"]
canonicalizer.attempt | role=fallback attempt=1 model=claude-opus-4-7 outcome=ok buckets=12
```

**Rationale**: Production debugging needs to surface "did we silently escalate?" without instrumenting the agent reasoning loop. Single-line structured logs are grep-friendly and live-verify reports can summarize them.

**No new dataclass field** on `CanonicalizationResult` — keep the surface stable. Logs are the audit trail.

### D7 — Skill markdown: minimal opt-in change + doc clarification

**Decision**: `api/memory/workspace/notes/skills/industry-onboarding.md` gets two surgical changes (no behavior contract change for the skill, but the call site flips and doc lines need to match new reality):
1. **Step 3.5 call site (`industry-onboarding.md:168`)** — flip `default_llm_canonicalizer()` → `resilient_llm_canonicalizer()`. (The surrounding `canonicalize_kpi_observations(...)` block starts at `:166`; the factory literal is on `:168`.) This is the production opt-in to resilience.
2. **MODEL=haiku|opus doc lines (`:69` and `:162`)** — update from "default is Haiku" to "default is `resilient_llm_canonicalizer` (Haiku with one retry, escalating to Opus on persistent D4 validation failure). `MODEL=haiku` or `MODEL=opus` forces single-shot behavior via `default_llm_canonicalizer(model=...)`."

**Rationale**: Per Codex R0 P1 — leaving the doc lines as "default is Haiku" would be misleading after F85c-followup ships. Acceptance language updated accordingly (§9): "no behavior contract change; doc clarification and call-site flip required."

**Blast radius**: 3 line-edits in one skill md file. Skill consumers (other skills that call into industry-onboarding) see no API change.

### D8 — Cost ceiling impact: tracked, not gated

**Decision**: No cost-cap enforcement in the wrapper. Worst case is ~$0.40 / canonicalization vs ~$0.05 baseline (8x increase on the bad path; absolute is still trivial vs the $5 onboarding ceiling).

**Rationale**: Per `feedback_treat_user_concerns_as_urgent`: cost is worth surfacing in the plan but not gating in code. The OAuth lockdown is the real spend guard; per-call ceilings would just add brittleness.

**If observed worst-case escalation rate is high** (e.g., >20% of onboardings escalate to Opus): revisit with prompt-tightening or alternative primary model in a follow-up.

---

## 4. Out of scope

- **Network-error retry** — different failure category (D2). Plan if observed.
- **Exponential backoff** — single retry is sufficient given the stochastic-not-rate-limited nature of the failure.
- **Switching default primary model to Opus** — Haiku is the right cost/quality tradeoff per F85c plan §D3; followup doesn't revisit it.
- **Prompt engineering to reduce dup-phrase risk** — the wrapper handles the symptom; prompt tweaks can ship separately if telemetry shows residual rate.
- **Telemetry / cost-cap envelope work** — out of scope; logs are the audit trail.
- **F85 third-reference-industry onboarding** — separate ship; F85c-followup is its blocker.

---

## 5. Steps

### S1 — Promote `_validate_canonical_proposal` → `validate_canonical_proposal`

File: `api/agent/skills/industry_onboarding.py`
- Rename function (`industry_onboarding.py:983`).
- Update its caller in the same file (`canonicalize_kpi_observations` body — exact call at `:317`).
- Add a one-line docstring: `"""D4 cross-validation of an LLM canonicalization proposal against the input observations. Returns a tuple of structured rejection reasons; empty tuple when valid. Does NOT validate proposal schema — that's Pydantic's job at construction time."""`
- No other behavioral change.

### S2 — Add `resilient_llm_canonicalizer` factory

File: `api/agent/skills/_industry_onboarding_canonicalizer.py`
- New top-level `resilient_llm_canonicalizer(*, primary_model=CANONICALIZER_MODEL, fallback_model=CANONICALIZER_FALLBACK_MODEL, primary_retries=1, validator=None) -> LLMCanonicalizer`.
- Constants: add `CANONICALIZER_FALLBACK_MODEL = "claude-opus-4-7"` next to `CANONICALIZER_MODEL`. Confirm exact Opus model ID at impl per `/Users/henrychien/.codex/config.toml` or env conventions; the constant tracks.
- Validate `primary_retries >= 0` at construction time; raise `ValueError` otherwise (Codex R0 P1).
- Internal logic per D2-D4:
  - Build `primary` and `fallback` `LLMCanonicalizer` from single-model `default_llm_canonicalizer(model=primary_model)` / `default_llm_canonicalizer(model=fallback_model)`.
  - If `validator` is None, import `validate_canonical_proposal` from `industry_onboarding`.
  - Async inner function loops attempts: primary × (primary_retries+1) → fallback × 1.
  - On each attempt: `await proposal_callable(observations, industry_name)`; structured log per D6; if `validator(proposal, observations)` empty → return proposal; else continue.
  - After all attempts exhausted → return last proposal (caller's `canonicalize_kpi_observations` runs the same validator and produces `failed_passthrough`).
- **`default_llm_canonicalizer` is UNCHANGED** — no edits to it in this step.

### S3 — (removed in R1)

Original S3 was "update `default_llm_canonicalizer` to delegate." Per Codex R0 P1, that approach broke existing tests. R1 keeps `default_llm_canonicalizer` unchanged; production opt-in to resilience moves to the skill markdown call site (see S4).

### S4 — Skill markdown call-site flip + doc clarification

File: `api/memory/workspace/notes/skills/industry-onboarding.md`
- **Step 3.5 factory literal at `industry-onboarding.md:168`** — flip the canonicalizer factory call from `default_llm_canonicalizer()` → `resilient_llm_canonicalizer()`. (The surrounding `canonicalize_kpi_observations(...)` block starts at `:166`; the factory literal itself is on `:168`.)
- **MODEL=haiku|opus doc lines (`:69` and `:162`)** — update from "default is Haiku" to: "Default canonicalizer (`resilient_llm_canonicalizer()`) runs Haiku with one retry on D4 validation failure, then escalates to Opus once. `MODEL=haiku` and `MODEL=opus` force single-shot behavior via `default_llm_canonicalizer(model=...)`."

### S5 — Tests

File: `tests/skills/test_industry_onboarding_canonicalization.py` (extend) OR new sibling `test_industry_onboarding_resilient_canonicalizer.py` (TBD at impl — Codex's call which is cleaner).

New tests (9):
- `test_resilient_succeeds_first_attempt` — stub primary returns valid; assert single primary call, no fallback call, status="canonicalized". (Cost-budget test — fallback NEVER fires when primary succeeds.)
- `test_resilient_succeeds_on_haiku_retry` — stub primary returns invalid then valid (sequence-stub); assert 2 primary calls, no fallback call, status="canonicalized".
- `test_resilient_escalates_to_fallback_after_primary_exhausted` — stub primary always invalid; stub fallback valid; assert primary called `primary_retries+1` times, fallback called once, status="canonicalized".
- `test_resilient_all_attempts_fail_returns_passthrough` — stub primary + fallback both invalid; assert `canonicalize_kpi_observations` ends in `failed_passthrough` with reasons from `validate_canonical_proposal` running on the final fallback attempt's proposal. End-to-end through `canonicalize_kpi_observations`, not just at wrapper boundary.
- `test_resilient_pydantic_error_propagates_no_retry` — **wrapper-direct test** (calls `resilient_llm_canonicalizer()` directly, NOT through `canonicalize_kpi_observations`). Stub primary raises `pydantic.ValidationError`; assert exception bubbles up from the wrapper; NO retry attempt; NO fallback call. End-to-end behavior through `canonicalize_kpi_observations` is different: it catches all `Exception` from the canonicalizer at `industry_onboarding.py:305` and converts to `failed_passthrough` / `proposal_schema_invalid` at `:306` — that's existing F85c behavior, not retested here.
- `test_resilient_network_error_propagates_no_retry` — **wrapper-direct test** (same scope as above). Stub primary raises `anthropic.APIError` (or whatever the equivalent exception class in the SDK is); assert exception bubbles up from the wrapper; NO retry attempt; NO fallback call.
- `test_validator_injection_works` — wrapper accepts custom validator callable; verify it's used instead of the default-imported one (deterministic stub returns "always fail" → assert escalation happens).
- `test_logs_emitted_per_attempt` — capture log records, assert one `canonicalizer.attempt` log line per attempt with expected `role`/`attempt`/`model`/`outcome` fields.
- `test_resilient_primary_retries_validation` — `resilient_llm_canonicalizer(primary_retries=-1)` raises `ValueError`; `primary_retries=0` works and produces exactly 1 primary attempt + 1 fallback attempt (covers the boundary).

Existing tests: must remain green (no behavior change to single-model `default_llm_canonicalizer(model="haiku")` path; the test at `:564`/`:578` that introspects `__self__` continues to pass).

Existing tests: must remain green (no behavior change to single-model `default_llm_canonicalizer(model="haiku")` path).

### S6 — Docs + TODO updates (post-impl)

- `risk_module/docs/TODO.md`: F85c-followup row → SHIPPED.
- Memory: update `project_f85c_canonical_bucket_helper_shipped.md` to note F85c-followup closed.
- Move plan to `risk_module/docs/planning/completed/`.
- No SKILL_CONTRACT_MAP update (no external behavior change).

---

## 6. Tests (consolidated)

See S5. Total new: 9 tests. Existing 14 F85c canonicalization tests must stay green.

---

## 7. Risks and open questions

### R1 — Validator import becomes a cycle risk

`_industry_onboarding_canonicalizer.py` already imports types from `industry_onboarding`. Adding `validate_canonical_proposal` to that import set should be safe. If a cycle does appear at impl time, the validator can move into a shared private module — but D5's promotion is the cleaner first attempt.

### R2 — Opus model ID may need updating

Plan uses `claude-opus-4-7` as `CANONICALIZER_FALLBACK_MODEL`. If the Anthropic model ID changes between plan and impl, the constant tracks. Confirm at impl against Anthropic's current model overview docs (or against the project's `~/.codex/config.toml` model setting if it pins one) — F85c's primary `claude-haiku-4-5-20251001` provides a good cross-check on the current naming pattern.

### R3 — Test-suite organization

Whether to extend `test_industry_onboarding_canonicalization.py` or add a new sibling file is a stylistic call. Both are valid; Codex implementation can choose. ≥80% of new tests are wrapper-specific, so a sibling file may be marginally cleaner.

### R4 — Logger name choice

The existing canonicalizer module uses no logger today. Suggest `logging.getLogger("agent.skills.industry_onboarding.canonicalizer")` for the wrapper logs. Confirm at impl that this aligns with the project's logger naming convention.

### Open Q1 — Does the wrapper need to support `temperature` adjustment on retry?

E.g., bump temperature from 0 to 0.1 on the second Haiku attempt. The F85c plan kept temp=0 deliberately. Bumping it on retry could reduce dup-phrase risk but introduces a different non-determinism. **My take**: keep temp=0 across all attempts in v1. If Haiku-only failure rate persists, revisit.

### Open Q2 — Should the wrapper log to a structured event store (vs just stdlib logging)?

Per `feedback_workbench_scope`, engineering events go to logs / TODO, not the workbench. Logger is the right channel for v1.

---

## 8. Verification checklist (pre-commit)

- [ ] All 9 new wrapper tests pass.
- [ ] All 14 F85c canonicalization tests still pass.
- [ ] Full `tests/skills/test_industry_onboarding_*.py` suite green.
- [ ] `default_llm_canonicalizer()` UNCHANGED — still returns bound `CanonicalizerClient.canonicalize` method; existing `test_default_canonicalizer_requires_oauth` (`__self__` access at `:564`/`:578`) passes without modification.
- [ ] `resilient_llm_canonicalizer()` returns the retry/escalation wrapper (callable async function, not a bound method).
- [ ] Skill markdown Step 3.5 factory literal at `industry-onboarding.md:168` flipped from `default_llm_canonicalizer()` → `resilient_llm_canonicalizer()`.
- [ ] `_validate_canonical_proposal` rename complete (grep for old name).
- [ ] No new dependencies added.
- [ ] Plan-doc grep sweep before commit (per `feedback_plan_grep_sweep_before_commit`).

---

## 9. Acceptance

F85c-followup is accepted when:
1. Re-run Grocers live-verify (S7 of F85c) and observe one of two outcomes:
   - **First-attempt succeed** — Haiku gets it right; no escalation; no behavior change vs today.
   - **Transparent retry/escalate** — wrapper logs show retry-on-Haiku and/or escalate-to-Opus; final `canonicalize_kpi_observations` returns `status="canonicalized"`; skill methodology does NOT abort.
2. Unit test suite confirms all retry paths fire correctly.
3. Skill markdown call-site flip + 2 doc-clarification lines updated (3-line edit total); no behavior contract change for skill consumers.

Once accepted, **F85 third reference industry** can run with one fewer brittleness vector.

---

## 10. Changelog

- **R0 (2026-05-15)** — initial draft.
- **R4 (2026-05-15)** — Codex R3 FAIL (0 P1 + 2 P2) addressed:
  - **R3.P2 (unsourced CLAUDE.md quote in R2)** — removed the "Most recent Claude model family is 4.X" CLAUDE.md citation; replaced with "confirm at impl against Anthropic's current model overview docs or `~/.codex/config.toml`."
  - **R3.P2 (test count inconsistency)** — synced S5/§6/checklist all to "9 tests" (was mixed `~8`/`~9`).
- **R3 (2026-05-15)** — Codex R2 FAIL (0 P1 + 2 P2) addressed:
  - **R2.P2 (final cite drift at S4 line 186 + changelog line 289)** — both now say "factory literal at `:168`; surrounding block at `:166`."
  - **R2.P2 (D2 non-retryable wording)** — line 77 rewritten to distinguish wrapper-direct callers (Pydantic exception propagates) from end-to-end callers via `canonicalize_kpi_observations` (catches and converts to `failed_passthrough` / `proposal_schema_invalid` per existing `industry_onboarding.py:305-306` behavior, unchanged by F85c-followup).
- **R2 (2026-05-15)** — Codex R1 FAIL (1 P1 + 2 P2) addressed:
  - **R1.P1 (stale R0 leftovers)** — purpose-statement line 15 and verification-checklist line 256 reworked to match R1 architecture (`default_llm_canonicalizer` UNCHANGED; new `resilient_llm_canonicalizer` factory; skill-md call-site flip).
  - **R1.P2 (skill-md cite `:166` → `:168`)** — corrected all occurrences. Factory literal lives at `:168`; block starts at `:166`. Both citations included where helpful.
  - **R1.P2 (D2/S5 exception-propagation test scope)** — Pydantic/network-error retry tests are explicitly scoped as **wrapper-direct** (call `resilient_llm_canonicalizer()` directly, bypass `canonicalize_kpi_observations`). End-to-end behavior through `canonicalize_kpi_observations` retains today's catch-all-Exception → `failed_passthrough` / `proposal_schema_invalid` semantics (not retested in F85c-followup).
- **R1 (2026-05-15)** — Codex R0 FAIL (5 P1) addressed:
  - **R0.P1.1 (`default_llm_canonicalizer` back-compat)** — D1 + S2 + S3 reworked. `default_llm_canonicalizer` is now UNCHANGED. New `resilient_llm_canonicalizer` factory is the production opt-in. Skill markdown flips call site (D7 + S4). Existing tests at `:564`/`:578` continue to pass without modification.
  - **R0.P1.2 (validator failure taxonomy)** — §2.2 + D2 + S1 clarified. `_validate_canonical_proposal` returns only 5 cross-validation reasons (not `invalid_class_hint` — that's a Pydantic field-validator error surfaced as `proposal_schema_invalid`). Schema errors are non-retryable; only cross-validation failures trigger retry.
  - **R0.P1.3 (`primary_retries` bounds)** — D3 + S2 + S5 add `ValueError` when `primary_retries < 0` and a new boundary test `test_resilient_primary_retries_validation`. Cost formula documented explicitly.
  - **R0.P1.4 (skill md doc scope)** — D7 + S4 + §9 acknowledge the 3-line skill-md edit (factory literal flip at `:168` + 2 doc-clarification lines at `:69` and `:162`; surrounding block starts at `:166`). Acceptance language updated from "skill markdown unchanged" to "skill markdown call-site flip + 2 doc-clarification lines; no behavior contract change."
  - **R0.P1.5 (cite drift)** — §2.3 cites `investment_tools/analyst_dev/reports/2026-05-15-grocers-F85C-live-verify.md:44` (the report MD with full attempt audit) instead of `decisions_log.yaml` (which only captures the second-attempt success). S1 cites the validator call site at `industry_onboarding.py:317` (not "near :312").
