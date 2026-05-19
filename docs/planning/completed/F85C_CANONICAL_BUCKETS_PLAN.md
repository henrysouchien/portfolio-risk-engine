# F85c — Canonical-bucket helper for cross-peer KPI alignment

**Status**: R3 — **Codex PASS** (zero P1/P2). Ready for implementation handoff.
**Date**: 2026-05-13
**Owner**: Henry
**Repo scope**: AI-excel-addin (skill primitive + skill markdown) + risk_module (plan + TODO updates only)
**Parent**: F85b live-verify P1.1 (`data/users/henry/workspace/notes/skills/industry-onboarding/2026-05-09-grocers-LIVE-VERIFY.md:100-111`)

---

## 1. Purpose

Ship an LLM-backed canonicalization primitive so `industry-onboarding` produces useful KPI candidates **without requiring a hand-authored bucket dict per industry**. F85b's strict-match aggregator emits 1 candidate at floor=2 against real EDGAR data (123 distinct `metric_name_normalized` across 4 grocers); only by hand-authoring a 6-bucket `CANONICAL_BUCKETS` tuple in `investment_tools/analyst_dev/scripts/run_industry_onboarding_grocers.py:85-148` did the agent lift survivors to 6 and produce a shippable registry. F85c automates that editorial step so every future industry onboards in one pass.

F85c bundles a fix for F85b P1.2 (label drift — peer-specific phrasing leaking into the canonical `label` field). The LLM emits a neutral `canonical_label` per bucket, which `build_registry_kpis` uses instead of the alphabetic-exemplar-derived label.

**Inputs**: peer-keyed `metric_name_normalized` observations (current `aggregate_kpi_observations` input shape) + optional `LLMCanonicalizer` callable.

**Output**: same peer-keyed observations with `metric_name_normalized` rewritten to canonical bucket names + a new `canonical_label` field per row; aggregator runs unchanged downstream.

This is a **design-time** helper, not a runtime extraction change. F86 (runtime LLM-based KPI extraction) remains out of scope.

---

## 2. Audit findings

### 2.1 Current aggregator (`api/agent/skills/industry_onboarding.py:215-316`)

```python
def aggregate_kpi_observations(
    peer_observations: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    floor: int | None = None,
    per_class_k: int = 3,
    max_total_k: int | None = None,
) -> AggregationResult:
```

- Grouping key: `(metric_name_normalized.strip().lower(), class_hint.strip())` — exact string match.
- Frequency floor (default `max(2, ceil(N_peers/2))`), per-class top-K (default 3), optional max-total cap.
- Emits `KpiCandidate` rows + `RejectedKpi` rows; `_select_exemplar` picks the alphabetically-first grounded observation as `exemplar_metric_name`, which `build_registry_kpis` (label assignment around `:485`) then uses to derive the registry `label`.

### 2.2 Hand-authored grocers workaround (`investment_tools/analyst_dev/scripts/run_industry_onboarding_grocers.py:85-170`)

```python
CANONICAL_BUCKETS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("total stores in operation", "footprint_metric",
     ("total supermarkets operated", "total stores operated",
      "total stores in operation", "total retail stores in operation",
      "total store count")),
    ("loyalty program members", "user_metric",
     ("loyalty program members enrolled", "loyalty member count",
      "annual households served",  # KR uses households-served as loyalty proxy
      "loyalty member count and growth rate")),
    # ... 4 more buckets
)

def _canonicalize_observations(rows: list[dict]) -> list[dict]:
    """Replace metric_name_normalized with a canonical bucket name when the
    extracted phrase is a recognized variant. Preserves original metric_name."""
    for r in rows:
        original_normalized = str(r.get("metric_name_normalized") or "").lower()
        original_class = str(r.get("class_hint") or "")
        new_row = dict(r)
        for canonical, class_hint, phrases in CANONICAL_BUCKETS:
            if any(p in original_normalized for p in phrases):
                if not original_class or class_hint == original_class:
                    new_row["metric_name_normalized"] = canonical
                    new_row["class_hint"] = class_hint
                    break
```

Key characteristics — and the **R1 divergence from substring-based grocers logic**:
- **Substring match was acceptable for the hand-authored map** because the human editor enumerated phrase prefixes deliberately (e.g., `"gross margin rate"` covered both "gaap gross margin rate" and "gross profit rate" by sharing the keyword "margin rate"). With LLM-emitted buckets, substring matching becomes a **footgun**: an LLM that explicitly excludes "fifo gross margin rate change ex-fuel ex-labor dispute" from the `gross margin rate` bucket (because it's a delta, not a level) would have that exclusion silently overridden by substring containment. **F85c uses explicit membership match** instead — `metric_name_normalized.lower() in {member.lower() for member in bucket.member_phrases}` — and rejects any observation that would be rewritten by two or more buckets at runtime. See D6 + D4 for details.
- **Class-hint compatibility gate** — preserved. Refuses to collapse semantically different metrics that happen to share `metric_name_normalized` strings.
- **Original `metric_name` preserved** — only `metric_name_normalized` is rewritten; original feeds back into `_collect_aliases` (function at `industry_onboarding.py:905`, called from `aggregate_kpi_observations:277`) for alias capture.

### 2.2.1 Grocers fixture stats (re-counted from saved extractions)

From `extractions/{KR,ACI,SFM,WMK}.json` in the 2026-05-09-grocers staging dir: **119 distinct non-empty `metric_name_normalized` values** across 123 total extraction rows. Strict-match aggregation at floor=2 produces 1 survivor; hand-authored 6-bucket map lifts to 6 survivors. F85c must reproduce the lift automatically.

### 2.3 Existing injectable-callable precedent (`derive_pattern_hints:319`)

F85b already uses an injected-callable pattern for LLM-tier logic:

```python
PatternProvider = Callable[[KpiCandidate], Iterable[str]]

def derive_pattern_hints(
    candidate: KpiCandidate,
    *,
    llm_pattern_provider: PatternProvider | None = None,
    target_llm_patterns: int = 2,
) -> PatternHintResult:
```

The skill harness wires a real LLM-backed provider; tests inject stubs. F85c follows this shape exactly.

### 2.4 Existing LLM infrastructure (AI-excel-addin)

- `packages/agent-gateway/agent_gateway/providers/anthropic.py:302::AnthropicProvider` — multi-turn agent provider handling `ANTHROPIC_AUTH_TOKEN` + `ANTHROPIC_AUTH_MODE=oauth` per the OAuth-only rule (`feedback_anthropic_oauth_only`). Re-exported via `packages/agent-gateway/agent_gateway/providers/__init__.py:2`.
- `bootstrap_env` Phase 2 hydrates Anthropic credentials from SSM at process start.
- **One-shot OAuth helper precedent — `JudgeClient` (`api/agent/shared/citation_judge.py:37`)**: existing single-prompt Anthropic helper used by the citation judge. Async-by-design (uses `AsyncAnthropic`; `judge` method async at `:82`). Handles OAuth fingerprint headers (`anthropic-beta` slugs, `user-agent` claude-cli/X, `X-Api-Key: Omit()`), the OAuth system-block requirement, and `_temporarily_unset_env("ANTHROPIC_API_KEY")` to defeat silent fallback. F85c's `default_llm_canonicalizer` mirrors this pattern (D3 + S3).
- Auth resolver `resolve_auth_config` lives at `packages/agent-gateway/agent_gateway/_provider_utils.py:72` (NOT `api/credentials.py`). It ignores `ANTHROPIC_AUTH_MODE` by default and chooses `api` when both API key and OAuth token are set (`packages/agent-gateway/tests/test_resolve_auth_config.py:113-128`). Returns a dict with `auth_mode`, `api_key`, and `auth_token` keys (NOT an `active_credential` object). F85c MUST call it with `read_env_auth_mode=True` and `raise_on_missing=True` to honor the OAuth-only rule.

### 2.5 Cross-repo loader/wire-up

- `risk_module/utils/kpi_registry_loader.py` and `risk_module/mcp_tools/industry.py:233-241` consume registries cross-repo. **Unchanged by F85c** — the schema of registries emitted is unchanged; only the bucket-naming and label-quality improve.

---

## 3. Decisions

### D1 — Architecture: new module function, aggregator unchanged

**Decision**: Add `canonicalize_kpi_observations(peer_observations, *, llm_canonicalizer=None)` to `api/agent/skills/industry_onboarding.py`, sibling to `aggregate_kpi_observations`. The new function:
- Takes the current `aggregate_kpi_observations` input shape (peer-keyed observation lists).
- Returns the same shape with `metric_name_normalized` rewritten to canonical-bucket names, and a new `canonical_label` field added per row.
- The existing `aggregate_kpi_observations` signature is **unchanged**; it just consumes nicer input.

**Rationale**: Single-responsibility decomposition. Aggregator stays a deterministic frequency-counter. Canonicalization is the LLM-touching layer. Tests, mocks, and migration are scoped to the new function only.

**Pipeline shape** (skill orchestration):
```
fetch_extractions(peers)
  → canonicalize_kpi_observations(peer_observations, llm_canonicalizer=...)
  → aggregate_kpi_observations(canonical_observations)
  → derive_pattern_hints(...)
  → build_registry_kpis(...)
```

### D2 — LLM contract

**Input** (one batch, sent as the user prompt):
```
Industry: <industry_name>
Class hints in play: <comma-separated set from observations>

Raw phrases observed across peers:
- "<metric_name_normalized>" [<class_hint>] (<PEER_TICKER>) — exemplar: "<exemplar_metric_name>" = "<exemplar_value_raw>"
- ...
```

**Output** (JSON, strict-schema validated):
```json
{
  "buckets": [
    {
      "canonical_name": "total stores in operation",
      "canonical_label": "Total Stores in Operation",
      "class_hint": "footprint_metric",
      "member_phrases": ["total supermarkets operated", "total stores operated", "total stores in operation", "total retail stores in operation"]
    }
  ]
}
```

**Rationale**: The LLM's only job is editorial grouping + neutral naming. Pattern hints, frequency thresholding, schema emission, and aggregation remain deterministic. Strict JSON schema makes the rewrite step a pure function over verified data.

### D3 — Default model: Claude Haiku 4.5 via OAuth (JudgeClient-style helper)

**Decision**: Default canonicalizer model = `claude-haiku-4-5-20251001` via a JudgeClient-style `AsyncAnthropic` OAuth helper, using `agent_gateway.resolve_auth_config(read_env_auth_mode=True, raise_on_missing=True)` for credential resolution. NOT `AnthropicProvider` (which is the multi-turn agent provider; F85c is one-shot stateless). Opus override available via skill arg (`MODEL=opus`).

**Rationale**:
- Per `feedback_anthropic_oauth_only`: NEVER pay-as-you-go API key. OAuth or nothing.
- Per memory cost rule: F85b's $5 ceiling shouldn't expand. Haiku 4.5 estimate: ~$0.05 / call, ~5s. Opus estimate: ~$0.30, ~15s. Haiku is more than capable of this task (editorial grouping over ≤200 short phrases) — it's not a reasoning-heavy task.
- Opus override exists because some hard industries (e.g., specialty chemicals, complex segments) may benefit from deeper editorial judgment.

**Impl detail**: Step S3 specifies the JudgeClient-style helper. It MUST use the `AsyncAnthropic` + OAuth-fingerprint-headers pattern; MUST call `resolve_auth_config(read_env_auth_mode=True, raise_on_missing=True)` to honor `ANTHROPIC_AUTH_MODE`; MUST NOT instantiate a raw `Anthropic()` client that could fall back to `ANTHROPIC_API_KEY`. Test coverage asserts the OAuth path is used in the mixed-credentials env scenario.

### D4 — Fail-loud schema validation; passthrough on failure

**Decision**: The deterministic rewrite step validates LLM output against a strict schema (Pydantic model `CanonicalBucketProposal`). Validation rules:
- `buckets[]` is a non-empty list.
- Each bucket has all 4 fields present and non-empty (`canonical_name`, `canonical_label`, `class_hint`, `member_phrases[]`).
- `class_hint` is one of the seven KPI classes in the local constant `KPI_CLASSES` (`api/agent/skills/industry_onboarding.py:42-50`).
- Every `member_phrases[i]` must exist verbatim (lowercased + whitespace-stripped) in the input observation set (refuses LLM hallucination).
- **Input-side**: no input phrase appears in `member_phrases` of more than one bucket in the LLM proposal (refuses ambiguous LLM assignment).
- **Runtime cross-check (post-rewrite)**: as the deterministic rewrite walks observations, build a `phrase → bucket_id` map. If any observation matches `member_phrases` of more than one bucket at runtime (e.g., due to a subtle bug in the matching logic), reject the entire batch as `failed_passthrough` and log a structured P1 with the conflicting buckets. This is belt-and-suspenders defense against future regressions in the matching primitive.
- `canonical_name` is unique across buckets.
- **`canonical_name` collision rule**: if a bucket's `canonical_name` (normalized: lowercased + whitespace-stripped) equals any input observation's `metric_name_normalized`, then that input phrase MUST appear in the same bucket's `member_phrases` AND that observation's `class_hint` MUST be compatible with the bucket's `class_hint` (matching D6 gate). Otherwise reject — this prevents the failure mode where the LLM intentionally excludes a phrase from membership but post-rewrite aggregation merges the excluded phrase with rewritten rows on string equality of `metric_name_normalized`. (Codex R1 P1.1.)
- `canonical_name` and `canonical_label` MAY coincide with an existing input phrase if-and-only-if the above collision rule is satisfied (Open Q3 from R0; this is now the explicit valid sub-case).

On any validation failure:
1. Log a structured P1 warning with the failing rule + bucket index + (where applicable) the conflicting phrase.
2. Return `peer_observations` UNCHANGED (passthrough behavior — degenerates to current strict-match aggregator).
3. Set `CanonicalizationResult.status = "failed_passthrough"` so the skill harness can decide whether to abort or proceed.

When `llm_canonicalizer=None`:
1. Return passthrough with `status = "no_llm_provider"`. No warning logged.
2. Skill orchestration treats this as expected for dev-mode runs without LLM wiring.

**Rationale**: Silent partial canonicalization would produce subtly broken registries. Pre-F85c behavior is recoverable as the failure mode. P1 warning ensures the failure is observable. NO embedding fallback v1 — premature.

### D5 — Label-drift fix bundled (P1.2)

**Decision**: `build_registry_kpis` (label assignment around line 485) switches from `candidate.label` (derived from `exemplar_metric_name`) to a new `candidate.canonical_label` field when the `canonicalize_kpi_observations` step produced one. Falls back to current behavior when canonicalization didn't run (e.g., `llm_canonicalizer=None`).

**Rationale**: Same LLM call already emits a neutral label per bucket. Splitting label-drift into a separate plan would require a second LLM round-trip per onboarding — wasteful. One commit fixes both P1.1 and P1.2 atomically.

**Impl**: extend `KpiCandidate` with an optional `canonical_label: str | None = None`. `aggregate_kpi_observations` propagates this field from the first canonicalized observation in each bucket (all observations in a bucket share the same `canonical_label` post-canonicalization, so the choice is trivial).

### D6 — Explicit membership match + class_hint compatibility gate

**Decision**: The deterministic rewrite step uses **explicit-membership match** (not substring, per §2.2 divergence rationale) + **class-hint compatibility gate** mirroring the hand-authored grocers logic on the latter:

```python
# Pre-pass: build phrase → bucket lookup (lowercase + whitespace-stripped keys).
# If LLM proposal validation (D4) passed, every member appears in exactly one bucket.
phrase_to_bucket: dict[str, CanonicalBucket] = {}
for bucket in proposal.buckets:
    for member in bucket.member_phrases:
        phrase_to_bucket[member.strip().lower()] = bucket

# Rewrite walk.
for obs in observations:
    norm = str(obs.get("metric_name_normalized") or "").strip().lower()
    bucket = phrase_to_bucket.get(norm)
    if bucket is None:
        continue  # observation not in any bucket's members — leave as-is
    obs_class = str(obs.get("class_hint") or "").strip()
    if obs_class and obs_class != bucket.class_hint:
        continue  # class-hint compat gate — refuse rewrite
    obs["metric_name_normalized"] = bucket.canonical_name
    obs["class_hint"] = bucket.class_hint
    obs["canonical_label"] = bucket.canonical_label
```

**Rationale**:
- **Explicit membership** is safer than substring when an LLM authors the bucket: the LLM's exclusions (e.g., omitting "fifo gross margin rate change ex-fuel ex-labor dispute" from the `gross margin rate` bucket because it's a delta-of-margin) are respected. Substring match would silently override them.
- **Class-hint compat gate** is preserved — the grocers workaround discovered through real data that without it, "store" substrings could collapse footprint and pricing metrics. The constraint protects against well-intentioned LLM proposals that group cross-class metrics.
- **Per-phrase-uniqueness in `phrase_to_bucket`** is structurally guaranteed by D4 input-side validation; the runtime cross-check (D4 final bullet) confirms it at rewrite time.

### D7 — Original `metric_name` preserved for alias capture

**Decision**: Only `metric_name_normalized` and `class_hint` (and the new `canonical_label`) are rewritten. The original `metric_name` field on each observation is left untouched.

**Rationale**: `_collect_aliases` (function at `api/agent/skills/industry_onboarding.py:905`, called from `aggregate_kpi_observations:277`) walks observations grouped by `(metric_name_normalized, class_hint)` and extracts the peer-specific original `metric_name` per row to produce the `aliases[]` list. Preserving original `metric_name` keeps the aliases capture working — and the grocers verify confirmed aliases were the cross-peer-equivalence signal that made the registry usable.

### D8 — Out-of-band cleanup of analyst_dev driver

**Decision**: The grocers driver script (`investment_tools/analyst_dev/scripts/run_industry_onboarding_grocers.py`) stays as a historical artifact. NOT deleted, NOT promoted. F85b live-verify already documents it as the workaround it was.

**Rationale**: It's a fully-functional one-off in an analyst-dev sandbox. Removing it loses the audit trail of what the manual workaround looked like; promoting it conflicts with F85c's whole-pipeline design. Leave it alone.

### D9 — Cross-repo split

**Decision**:
- Plan doc: `risk_module/docs/planning/F85C_CANONICAL_BUCKETS_PLAN.md` (this file)
- Implementation: AI-excel-addin only (skill primitive + skill markdown + tests)
- TODO updates: both repos (risk_module rollup row + AI-excel-addin SKILL_CONTRACT_MAP — definite, per S8)
- `risk_module/utils/kpi_registry_loader.py` and `risk_module/mcp_tools/industry.py` unchanged

**Rationale**: Mirrors F85b. Plans live in risk_module; skill code lives in AI-excel-addin.

---

## 4. Out of scope

- **Embedding-based clustering fallback** — premature. LLM-only v1; revisit if cost/latency becomes a constraint.
- **Cross-industry KPI mapping** — operating comps are industry-keyed by design (per `project_canonical_comps_framework`).
- **Quarterly KPI granularity** — out of scope per F85b (still annual-only).
- **Runtime KPI extraction via LLM** — out of scope per F85b (still regex via `transcript_kpi.pattern_hints`); revisit in F86.
- **Per-bucket K override** — current default (`per_class_k=3`) stays as-is; not relevant to canonicalization gap.
- **F85 third reference industry** — UNBLOCKED by F85c but not in this plan; separate ship.
- **Promoting/deleting the analyst_dev grocers driver script** — per D8.

---

## 5. Steps

### S1 — Add `LLMCanonicalizer` Protocol + canonical-bucket types

File: `api/agent/skills/industry_onboarding.py`

- Add `CanonicalBucketProposal` Pydantic model (validated LLM output shape — D4 rules).
- Add `LLMCanonicalizer = Callable[[list[ObservationContext], str | None], Awaitable[CanonicalBucketProposal]]` — **async** callable contract, mirroring `JudgeClient.judge` (`citation_judge.py:82`). Second arg is the optional `industry_name`. Tests inject async stub fns. (Codex R1 P1.3.)
- `ObservationContext` is a frozen dataclass with `metric_name_normalized`, `class_hint`, `peer`, `exemplar_metric_name`, `exemplar_value_raw`.
- Add `CanonicalizationResult` dataclass: `status` (Literal `["canonicalized", "no_llm_provider", "failed_passthrough"]`), `peer_observations` (rewritten or passthrough), `buckets` (the validated proposal or empty tuple), `rejection_reasons` (tuple of structured P1 warnings).
- `class_hint` validation: must be one of the **local** `KPI_CLASSES` constant already defined at `api/agent/skills/industry_onboarding.py:42-50` (7 classes). No cross-repo import needed.

### S2 — `canonicalize_kpi_observations` function (async)

File: `api/agent/skills/industry_onboarding.py`

```python
async def canonicalize_kpi_observations(
    peer_observations: Mapping[str, Iterable[Mapping[str, Any]]],
    *,
    llm_canonicalizer: LLMCanonicalizer | None = None,
    industry_name: str | None = None,
) -> CanonicalizationResult:
```

**Async** to match `LLMCanonicalizer`'s `Awaitable` return contract (S1, Codex R1 P1.3). The deterministic rewrite logic inside is sync; only the LLM call awaits.

Internal flow:
1. Flatten observations to `ObservationContext` list (preserving peer identity).
2. If `llm_canonicalizer is None` → return passthrough with `status="no_llm_provider"` (no `await` needed; early return).
3. `proposal = await llm_canonicalizer(observations, industry_name)`.
4. Run D4 schema validation on the response. On failure → log + return passthrough with `status="failed_passthrough"`.
5. Run D6 deterministic rewrite over input rows, producing new `peer_observations` dict.
6. Return `CanonicalizationResult(status="canonicalized", peer_observations=..., buckets=..., rejection_reasons=())`.

Important: each observation row is shallow-copied before mutation; original input must not be mutated in place.

### S3 — Anthropic-OAuth-backed default canonicalizer (mirrors `JudgeClient`)

File: new module `api/agent/skills/_industry_onboarding_canonicalizer.py` (separate file so the LLM-touching code stays decoupled from the deterministic pipeline; mirrors `api/agent/shared/citation_judge.py` shape).

**Required pattern (mirrors `JudgeClient`, `citation_judge.py:37-94`)**:
- `class CanonicalizerClient` with `__init__(*, auth_mode: Literal["oauth"], auth_token: str, model: str = "claude-haiku-4-5-20251001", timeout: float = 30.0)`.
- **Reject `auth_mode="api"`** entirely (`JudgeClient` accepts both modes; F85c does not — per `feedback_anthropic_oauth_only`). Raise `ValueError` if `auth_mode != "oauth"`.
- Use `AsyncAnthropic` with `auth_token=...`, `api_key=""`, and the same OAuth fingerprint headers `JudgeClient` uses: `X-Api-Key: Omit()`, `anthropic-beta: <slugs>`, `user-agent: claude-cli/<version>`, `x-app: cli`.
- Wrap client construction in `_temporarily_unset_env("ANTHROPIC_API_KEY")` context manager (copy or import from `citation_judge.py`) to defeat silent fallback.
- Prepend the OAuth identity system block `"You are Claude Code, Anthropic's official CLI for Claude."` to every `messages.create` call (required for OAuth, per `citation_judge.py:91-93`).

**Factory `default_llm_canonicalizer(*, model=None) -> LLMCanonicalizer`** resolving credentials:
- Import `resolve_auth_config` from `agent_gateway._provider_utils` (defined at `:72`).
- Call `resolve_auth_config(read_env_auth_mode=True, raise_on_missing=True)` (so `ANTHROPIC_AUTH_MODE=oauth` is honored — default behavior ignores it; see `tests/test_resolve_auth_config.py:113-128`).
- The resolver returns a dict. Assert `resolved["auth_mode"] == "oauth"` AND `resolved["auth_token"]` is non-empty AND `resolved["api_key"] == ""`. Raise `RuntimeError(f"F85c requires OAuth; got auth_mode={resolved['auth_mode']}")` otherwise. NEVER silently fall back to API key.
- Build `CanonicalizerClient(auth_mode="oauth", auth_token=resolved["auth_token"], model=model or "claude-haiku-4-5-20251001")`.
- Return the bound `client.canonicalize` **async** method typed as `LLMCanonicalizer`.

**Prompt contract**:
- System block: OAuth identity (required) + canonicalization task description + strict JSON schema + class-hint constraint (must be in `KPI_CLASSES`) + "every `member_phrases[i]` must appear verbatim in the input phrase list" rule + "no phrase in two buckets" rule + "target 4-12 buckets, merge aggressively" instruction.
- User block: the observation list (per D2).
- Use `response_format` / tool-use structured output if `AsyncAnthropic` exposes it; otherwise plain JSON parsing with strict post-hoc Pydantic validation per D4. Decide at impl time which is cleaner.

**Why not `AnthropicProvider`**: `AnthropicProvider` (`packages/agent-gateway/agent_gateway/providers/anthropic.py:302`) is built around the multi-turn `AgentRunner` loop. F85c is one-shot stateless. `JudgeClient` already proved out the one-shot pattern; reuse it. Justification documented here per Codex R0 P2.

### S4 — Wire canonicalization into skill orchestration

File: `api/memory/workspace/notes/skills/industry-onboarding.md`

- Add a new step between "Phase 3 — fetching extractions" and "Phase 3 — aggregating cross-peer observations":

> **Step 3.5 — canonicalize KPI phrasing across peers**
> Insertion point: between the existing extraction-fan-out step and the aggregation step in `industry-onboarding.md` (Phase 2 Step 5 / Step 6 area, around `:145`-`:157`).
>
> ```python
> canonicalization = await canonicalize_kpi_observations(
>     peer_observations,
>     llm_canonicalizer=default_llm_canonicalizer(),
>     industry_name=industry_name,
> )
> ```
>
> On `canonicalization.status == "canonicalized"`: proceed with `canonicalization.peer_observations` as input to `aggregate_kpi_observations`.
> On `"failed_passthrough"`: abort the onboarding, surface `canonicalization.rejection_reasons`; do NOT silently fall through to strict-match aggregation in production runs.
> On `"no_llm_provider"`: dev-mode only; warn and continue with passthrough observations.

- Document the `MODEL=haiku|opus` skill arg (default haiku).
- Document that `LLM_CANONICALIZER=skip` arg bypasses canonicalization entirely (escape hatch for parity testing or dev iteration).

### S5 — Plumb `canonical_label` through `build_registry_kpis`

File: `api/agent/skills/industry_onboarding.py`

- Add `canonical_label: str | None = None` to `KpiCandidate` dataclass.
- In `aggregate_kpi_observations` (around line 280, the `KpiCandidate(...)` construction), propagate `canonical_label` from the first row in the bucket (all rows share the same canonical_label post-S2; defensive: assert uniqueness within the bucket).
- In `build_registry_kpis` (label assignment around line 485), prefer `candidate.canonical_label` when present; fall back to current `candidate.label` derivation otherwise.

### S6 — Tests

File: `tests/skills/test_industry_onboarding_canonicalization.py` (NEW)

**Unit** (11):
- `test_passthrough_when_no_llm_provider` — no rewrite, status="no_llm_provider".
- `test_canonicalize_with_stub_llm` — stub returns 6 grocer-shaped buckets; verify rewrite applied + class_hint compat enforced + `canonical_label` populated on every rewritten row.
- `test_rejects_hallucinated_member_phrase` — stub returns a bucket with a phrase not in input; status="failed_passthrough", warning logged.
- `test_rejects_duplicate_phrase_in_two_buckets` — LLM proposal-side check (D4 input-side validation).
- `test_rejects_invalid_class_hint` — stub returns class_hint="random_metric"; rejected.
- `test_rejects_duplicate_canonical_name` — same name across two buckets; rejected.
- `test_class_hint_compat_gate` — bucket's class_hint mismatches observation's class_hint; observation NOT rewritten (preserves D6 behavior).
- `test_preserves_original_metric_name` — observation's original `metric_name` unchanged through rewrite (D7).
- `test_runtime_collision_rejected` — D4 final-bullet belt-and-suspenders check: construct a stub proposal that passes D4 input-side validation but where a future matching-primitive regression would assign one observation to multiple buckets at runtime; assert the runtime cross-check catches it and returns `failed_passthrough` (this test is intentionally hard to trigger via the legitimate code path; tests the defensive guard exists and fires).
- `test_canonical_name_collides_with_input_phrase` — Open Q3 case from R0: a bucket's `canonical_name` is verbatim equal to one of its `member_phrases`. Assert the rewrite is a no-op for that row (identity rewrite) and no error is raised.
- `test_rejects_canonical_name_collision_outside_member_set` — D4 canonical-name-collision rule (Codex R1 P1.1): a bucket's `canonical_name` equals an input observation's `metric_name_normalized` but that observation is NOT in the bucket's `member_phrases`. Assert `status="failed_passthrough"` and the rejection reason cites the collision rule.

**Integration** (2):
- `test_grocers_fixture_end_to_end` — feed fixture extractions from `/Users/henrychien/Documents/Jupyter/investment_tools/analyst_dev/output/industry_onboarding/2026-05-09-grocers/extractions/{KR,ACI,SFM,WMK}.json` through the full pipeline: `canonicalize_kpi_observations` → `aggregate_kpi_observations` → `derive_pattern_hints` → `build_registry_kpis` → `build_emission_artifacts` → `KPIRegistry.model_validate(...)` → `CompsTemplateManifest.model_validate(...)`. Stub canonicalizer returns the **D4-valid grocers proposal below** (constructed from verbatim observed `metric_name_normalized` strings drawn from the fixture extractions; NOT the §2.2 hand-authored map, which uses substring prefixes that fail D4's verbatim-member rule per Codex R1 P1.2). Assertions: ≥6 surviving KPI candidates at floor=2; all KPIs have neutral `label` (no peer-specific phrasing); both schema validations pass; emitted registry shape matches the existing `config/industry_kpis/grocers.yaml` structure (key-by-key — labels may differ since they're now neutral).

**D4-valid grocers proposal (test fixture)** — each `member_phrases[i]` MUST appear verbatim in raw fixture `metric_name_normalized` (NOT registry aliases — `grocers.yaml` aliases include the manual-rewrite canonical names like "total employees" / "loyalty program members" / "comparable sales growth" / "gross margin rate", which are agent-introduced and NOT in raw fixtures). The stub must be cite-checked against the actual extractions:

```python
GROCERS_STUB_BUCKETS = [
    {
        "canonical_name": "total stores in operation",
        "canonical_label": "Total Stores in Operation",
        "class_hint": "footprint_metric",
        "member_phrases": [
            "total supermarkets operated",
            "total stores in operation",  # collision-rule allowed: appears in members
            "total stores operated",
            "total stores operating",
            "total store count",
            "total retail stores in operation",
        ],
    },
    {
        "canonical_name": "new store openings",
        "canonical_label": "New Store Openings",
        "class_hint": "footprint_metric",
        "member_phrases": [
            "new store openings",  # collision-rule allowed: appears in members
            "new store openings and remodels (fiscal 2025)",
            "new store openings and remodels (fiscal 2024)",
            "cumulative new store openings",
            "new store activity",
        ],
    },
    {
        "canonical_name": "total employees",
        "canonical_label": "Total Employees",
        "class_hint": "user_metric",
        "member_phrases": [
            "total workforce headcount",
            "total associates employed",
            "total team member headcount",
            "employee headcount",
            # NOTE: "total employees" canonical_name is NOT a raw fixture phrase;
            # not included as a member. No collision-rule trigger needed.
        ],
    },
    {
        "canonical_name": "loyalty program members",
        "canonical_label": "Loyalty Program Members",
        "class_hint": "user_metric",
        "member_phrases": [
            "loyalty program members enrolled",
            "annual households served",
            "loyalty member count and growth rate",
            # NOTE: "loyalty program members" canonical_name is NOT a raw
            # fixture phrase; not included as a member.
        ],
    },
    {
        "canonical_name": "comparable sales growth",
        "canonical_label": "Comparable Sales Growth",
        "class_hint": "comp_metric",
        "member_phrases": [
            "identical sales growth ex-fuel ex-labor dispute",
            "identical sales growth (ex-fuel)",
            "identical sales growth",
            "comparable store sales growth",
            "comparable store sales growth (excluding and including fuel)",
            # NOTE: "comparable sales growth" canonical_name is NOT a raw
            # fixture phrase; not included as a member.
        ],
    },
    {
        "canonical_name": "gross margin rate",
        "canonical_label": "Gross Margin Rate",
        "class_hint": "comp_metric",
        "member_phrases": [
            "gaap gross margin rate",
            "gross profit rate",
            # NOTE: "gross margin rate" canonical_name is NOT a raw fixture
            # phrase; not included as a member. Single-level deltas like
            # "fifo gross margin rate change ex-fuel ex-labor dispute" are
            # intentionally EXCLUDED — D4 collision rule + class-hint gate
            # would catch any drift here.
        ],
    },
]
```

Notes:
- **Only `"total stores in operation"` and `"new store openings"` are canonical_names that coincide with raw fixture phrases**; both appear in their own bucket's `member_phrases`, satisfying D4's collision rule.
- The other 4 canonical_names (`total employees`, `loyalty program members`, `comparable sales growth`, `gross margin rate`) are agent-introduced neutral labels not found in raw fixture extractions — no collision-rule trigger.
- **Expected peer-count distribution at floor=2** (computed from raw fixture phrases): `total stores in operation` 4, `new store openings` 3, `total employees` 4, `loyalty program members` 2, `comparable sales growth` 4, `gross margin rate` 2. All 6 buckets survive floor=2.
- **Test invariant**: `test_grocers_fixture_end_to_end` MUST assert that every `member_phrases[i]` across all buckets appears as a raw `metric_name_normalized` value in the loaded fixture JSONs (NOT in `grocers.yaml` aliases). Encode this as a setup-time assertion, NOT just a runtime D4 check.
- `test_grocers_fixture_passthrough_yields_one_kpi` — same fixtures, `llm_canonicalizer=None` (passthrough). Assert strict-match aggregation produces exactly 1 surviving candidate (the floor=2 baseline F85b ships today). Documents the gap F85c closes.

**OAuth-mode assertion** (1):
- `test_default_canonicalizer_requires_oauth` — mirror `JudgeClient`'s OAuth tests at `tests/agent/shared/test_citation_judge.py:67`. Three scenarios:
  1. `ANTHROPIC_AUTH_MODE=oauth` + `ANTHROPIC_AUTH_TOKEN=xxx` only → succeeds, client constructed with OAuth headers.
  2. `ANTHROPIC_AUTH_MODE=oauth` + `ANTHROPIC_AUTH_TOKEN=xxx` + `ANTHROPIC_API_KEY=yyy` (BOTH set — the load-bearing case Codex flagged: default resolver picks API mode here, F85c MUST pick OAuth). Assert OAuth wins, `client._auth_mode == "oauth"`, `api_key=""` on the underlying `AsyncAnthropic` client.
  3. `ANTHROPIC_AUTH_MODE=api` + `ANTHROPIC_API_KEY=yyy` only → `default_llm_canonicalizer()` raises `RuntimeError` before any client construction. No network call attempted.

**Total: 14 tests (11 unit + 2 integration + 1 OAuth)**.

### S7 — Live verify on Grocers (acceptance gate)

Re-run F85b end-to-end on Grocers (`PEER_TICKERS=KR,ACI,SFM,WMK`, autonomous mode), this time WITHOUT the analyst_dev driver. Acceptance criteria:
- Cost ≤ $5 (re-target $0.50 incremental for canonicalization).
- Wall time ≤ 10 min (F85b plan ceiling).
- ≥6 KPI candidates at floor=2 (matches manual-bucket grocers.yaml).
- Neutral labels emitted (no "Identical Sales Growth Ex-fuel Ex-Labor Dispute" — should read "Comparable Sales Growth" or similar).
- Anthropic-auth env-var trace shows `OAUTH` mode used.

Output staging: `data/users/henry/workspace/notes/skills/industry-onboarding/2026-05-13-grocers-F85C-LIVE-VERIFY.md`.

### S8 — Docs + TODO + SKILL_CONTRACT_MAP updates

- `AI-excel-addin/docs/SKILL_CONTRACT_MAP.md` — update the `industry-onboarding` row (currently at `:136`): add the new `MODEL=haiku|opus` and `LLM_CANONICALIZER=skip` args; add the canonicalization step to the workflow description; bump version if the row tracks one. (Codex R0 P2: definite update, NOT "if needed".)
- `AI-excel-addin/docs/TODO.md`: F85c row → SHIPPED + LIVE-VERIFIED 2026-05-13.
- `AI-excel-addin/docs/TODO.md`: F85 row → UNBLOCKED for third reference industry (no Grocers re-ship; Grocers already landed via F85 2026-05-12).
- `risk_module/docs/TODO.md`: V2.P11 / canonical-comps row → v1.2 (canonicalization). Update.
- `risk_module/docs/TODO_COMPLETED.md`: F85c block.
- Move this plan to `risk_module/docs/planning/completed/` after live-verify passes.

---

## 6. Tests (consolidated)

See S6 + S7. Total new tests: **14** (11 unit + 2 integration + 1 OAuth assertion).

Existing tests that must remain green:
- `tests/skills/test_industry_onboarding_aggregator.py` — aggregator signature unchanged.
- `tests/skills/test_industry_onboarding_emission.py` — registry emission shape unchanged (canonical_label is additive).
- `tests/skills/test_industry_onboarding_fixture_parity.py` — fixture parity.
- `tests/skills/test_industry_onboarding_pattern_hints.py` — pattern hint derivation unchanged.
- `tests/skills/test_industry_onboarding_taxonomy_patch.py` — taxonomy patch unchanged.
- `tests/skills/test_industry_onboarding_autonomous_contract.py` — autonomous mode contract unchanged.

---

## 7. Risks and open questions

### R1 — LLM proposes too many buckets (one-per-phrase degeneracy)

**Mitigation**: System prompt explicitly instructs "target 4-12 buckets, merge aggressively, prefer fewer broader buckets over many narrow ones." Validation does NOT enforce a hard cap (over-merging is more recoverable than under-merging — power users can re-prompt). Live-verify should observe whether the prompt holds at deploy.

**If R1 fires repeatedly**: extend D4 with `min_phrases_per_bucket` validation; reject single-phrase buckets and re-prompt up to N retries. Defer until observed.

### R2 — LLM proposes semantically wrong groupings

**Mitigation**: The class-hint compatibility gate (D6) prevents the worst cross-class collapses (footprint vs pricing). Explicit-membership match (D6) preserves the safe property that only phrases the LLM explicitly assigned get rewritten. Verbatim member-phrase validation (D4) blocks hallucinated entries. Canonical-name-collision rule (D4) blocks the failure mode where the LLM excludes a phrase but post-rewrite aggregation re-merges it on string equality.

**Residual risk**: within-class semantic confusion (e.g., LLM groups "active users" and "new user signups" as the same bucket). Acceptable — user owns the commit gate; the registry is human-reviewed before merge.

### R3 — Cost growth on hard industries (Opus override)

**Mitigation**: `MODEL=opus` available. If Haiku produces low-quality buckets, the skill harness can fall back to Opus on a single retry. Cost ceiling stays $5/onboarding even with Opus retry.

**Defer until observed**: build the auto-retry-on-Opus logic. v1 = single attempt, user-driven model selection.

### R4 — JSON parse fragility on long phrase lists

**Mitigation**: Anthropic SDK supports tool-use / structured output. S3 should use whatever structured-output primitive is canonical in `AnthropicProvider` to enforce schema rather than parsing free-text JSON. If unavailable, use `response_format={"type": "json_object"}` and validate post-hoc.

### R5 — (obsolete; removed in R1)

The class-hint constant is local at `api/agent/skills/industry_onboarding.py:42-50`. No cross-repo concern. Risk dropped.

### Open Q1 — (resolved in R1)

The one-shot LLM call mirrors `JudgeClient` (`api/agent/shared/citation_judge.py:37`). See S3 for the full pattern. NOT plan-blocking.

### Open Q2 — `industry_name` propagation

The current `aggregate_kpi_observations` signature doesn't take `industry_name`. F85c's `canonicalize_kpi_observations` needs it for the LLM prompt. Skill orchestration already knows the industry name. Threading it through is trivial.

### Open Q3 — Bucket-name collision with existing `metric_name_normalized` in input

**Resolved**: Behavior is well-defined (the original gets rewritten to itself, no-op). D4 explicitly allows it; S6 covers it via `test_canonical_name_collides_with_input_phrase`.

---

## 8. Verification checklist (pre-commit)

- [ ] `tests/skills/test_industry_onboarding_canonicalization.py` — all 14 tests pass.
- [ ] Existing 6 `test_industry_onboarding_*.py` suites still green.
- [ ] `KPIRegistry.model_validate(...)` on Grocers re-emission passes.
- [ ] `CompsTemplateManifest.model_validate(...)` on Grocers manifest passes.
- [ ] Diff vs existing `config/industry_kpis/grocers.yaml`: same 6 keys (or close — minor LLM variation acceptable), neutral labels.
- [ ] No `Anthropic()` raw-client instantiation in F85c code paths (grep + assertion test).
- [ ] No `ANTHROPIC_API_KEY` reads in F85c code paths (grep + env-var assertion).
- [ ] Skill markdown documents `MODEL=haiku|opus` and `LLM_CANONICALIZER=skip` args.
- [ ] Plan-doc grep sweep before commit (per `feedback_plan_grep_sweep_before_commit`): every Codex-named term + class_hint values + KpiCandidate field references + function/method signatures match implementation.

---

## 9. Acceptance

F85c is accepted when:
1. Live-verify on Grocers (S7) lifts strict-match survivors from 1 → ≥6 at floor=2 WITHOUT the analyst_dev driver.
2. Live-verify produces neutral `canonical_label` values (no peer-specific phrasing like "Identical Sales Growth Ex-fuel Ex-Labor Dispute").
3. Cost ≤ $5/onboarding (target $0.50 incremental for canonicalization with Haiku 4.5).
4. OAuth-only mode confirmed via env-var trace.
5. F85 (third reference industry) can be attempted without manual editorial bucketing.

---

## 10. Changelog

- **R0 (2026-05-13)** — initial draft.
- **R3 (2026-05-13)** — Codex R2 FAIL (1 P1 + 2 P2) addressed:
  - **R2.P1 (stub fixture invalid against raw extractions)** — `GROCERS_STUB_BUCKETS` updated to drop 4 canonical-name self-members (`total employees` / `loyalty program members` / `comparable sales growth` / `gross margin rate`) that exist only in `grocers.yaml` aliases (agent-introduced), not in raw fixture `metric_name_normalized`. Added explicit setup-time test invariant: every `member_phrases[i]` must appear in raw fixture, not registry aliases. Expected peer-count distribution documented; all 6 buckets still survive floor=2.
  - **R2.P2 (S4 missing `await`)** — Step 3.5 wrapper now shows `canonicalization = await canonicalize_kpi_observations(...)` with explicit handling of `.status`/`.peer_observations`/`.rejection_reasons`; insertion point cited at `industry-onboarding.md:145-157`.
  - **R2.P2 (Unit-(10) stale label)** — corrected to Unit (11).
- **R2 (2026-05-13)** — Codex R1 FAIL (3 P1 + 4 P2) addressed:
  - **R1.P1.1 (canonical-name collision outside member set)** — D4 adds explicit canonical-name-collision rule: if a bucket's `canonical_name` normalizes to any input phrase, that phrase MUST be in the same bucket's `member_phrases` with compatible class_hint, else reject. S6 adds `test_rejects_canonical_name_collision_outside_member_set`.
  - **R1.P1.2 (S6 grocers fixture spec invalid under D4)** — S6 replaces the §2.2 hand-authored map (substring prefixes failing verbatim-member rule) with an explicit `GROCERS_STUB_BUCKETS` proposal using verbatim observed `metric_name_normalized` strings drawn from `config/industry_kpis/grocers.yaml` aliases. "Fifo gross margin rate change..." intentionally excluded from gross-margin bucket per D4 collision rule.
  - **R1.P1.3 (async/sync contract gap)** — `LLMCanonicalizer` typed as async (`Awaitable[CanonicalBucketProposal]`). `canonicalize_kpi_observations` is async. Matches `JudgeClient.judge` shape.
  - **R1.P2 (resolver location)** — §2.4 + S3 corrected: `resolve_auth_config` lives at `packages/agent-gateway/agent_gateway/_provider_utils.py:72`.
  - **R1.P2 (resolver return shape)** — S3 assertion language fixed: assert on dict keys `resolved["auth_mode"]`, `resolved["auth_token"]`, `resolved["api_key"]` (not `active_credential.kind`).
  - **R1.P2 (D3 stale AnthropicProvider language)** — D3 rewritten as "JudgeClient-style `AsyncAnthropic` OAuth helper using `agent_gateway.resolve_auth_config`."
  - **R1.P2 (R2 stale substring claim)** — R2 risk row updated: "Explicit-membership match preserves the safe property" (was "Substring-match-not-equality").
- **R1 (2026-05-13)** — Codex R0 FAIL (2 P1 + 7 P2) addressed:
  - **P1.1 (substring ambiguity)** — §2.2 + D4 + D6 reworked: explicit-membership match replaces substring; D4 adds input-side duplicate-phrase check + runtime cross-bucket-collision belt-and-suspenders check; D6 rewrite example reflects new semantics.
  - **P1.2 (OAuth resolver)** — §2.4 audit corrected to surface `resolve_auth_config` default behavior; S3 rewritten to mirror `JudgeClient` pattern with `read_env_auth_mode=True` + active-credential assertion + the mixed-API-key-and-OAuth-token test case.
  - **P2 (JudgeClient precedent)** — §2.4 + S3 cite `JudgeClient` (`api/agent/shared/citation_judge.py:37`) as the one-shot OAuth helper precedent; original "no existing one-shot helper" claim removed.
  - **P2 (provider path)** — §2.4 cite corrected to `providers/anthropic.py:302` with `providers/__init__.py:2` re-export.
  - **P2 (`KPI_CLASSES` source)** — S1 cites the local constant at `industry_onboarding.py:42-50`; R5 obsolete (removed).
  - **P2 (line citations)** — `_collect_aliases` corrected to function at 905 / call at 277; `build_registry_kpis` label assignment at ~485.
  - **P2 (test count)** — 11 → 13 (added `test_runtime_collision_rejected` + `test_canonical_name_collides_with_input_phrase` + the third OAuth-resolver scenario for mixed API-key/OAuth-token).
  - **P2 (integration test bypass)** — S6 integration test explicitly walks canonicalize→aggregate→derive_pattern_hints→build_registry_kpis→build_emission_artifacts→two schema validations.
  - **P2 (fixture stats)** — §2.2.1 corrected: 119 distinct non-empty `metric_name_normalized` values across 123 extraction rows.
  - **P2 (SKILL_CONTRACT_MAP)** — S8 specifies a definite update (line 136), not "if needed".
