# Vals Finance Agent - GPT 5.5 Parity Implementation Plan

**Created:** 2026-05-28
**Status:** Implemented and smoke-tested locally; broader benchmark run still pending
**Owner:** Benchmark/gateway integration
**Related plans:**
- `docs/planning/VALS_FINANCE_AGENT_RUN_PLAN.md`
- `docs/planning/VALS_FINANCE_AGENT_IMPL_PLAN.md`
- `docs/strategy/HANK_PRODUCT_POSITIONING.md` (TODO V1.7) — this plan is the **technical apparatus for V1.7's portability claim** (raw vs harnessed × Opus vs GPT-5.5). Broader v2 re-baseline + Gemini extension + full cross-model lift run tracked at TODO **B1.v2**.

## 1. Purpose

Add a GPT 5.5 mirror of the existing Claude Opus benchmark setup for the Vals AI Finance Agent harness.

The target outcome is direct comparability across two dimensions:

1. Raw model baseline vs Hank/tooling/harnessed agent.
2. Claude Opus 4.7 vs GPT 5.5, using the same benchmark harness and the same evaluation process.

The secondary purpose is to pressure-test model agnosticism. Any failures caused by switching from Claude to GPT should be fixed at the provider, auth, harness, tool-schema, prompt, or trace layer that actually owns the issue, while preserving the existing Claude behavior.

## 2. Constraints

### 2.1 Auth and cost

For local testing and gateway runs, GPT 5.5 should use the user's OAuth/subscription token, not public API credits.

In the current gateway code, that means the likely local test path is:

- `AGENT_PROVIDER=codex`
- `CODEX_AUTH_TOKEN=<ChatGPT/Codex token>`
- or `CODEX_AUTH_JSON=~/.codex/auth.json` with a valid `tokens.access_token`
- `CODEX_MODEL=gpt-5.5`

The public API deployment path must remain available separately:

- `AGENT_PROVIDER=openai`
- `OPENAI_AUTH_MODE=api`
- `OPENAI_API_KEY=<business/deployment API key>`
- `OPENAI_MODEL=<confirmed public API model id>`

Do not use `OPENAI_API_KEY` as the GPT benchmark agent credential during local subscription-token test runs. `OPENAI_API_KEY` may still be needed for the local judge unless that judge is disabled or moved to a separate env var.

### 2.2 Claude preservation

The existing Claude Opus 4.7 configs must keep working:

- Config A: Hank model-library wrapper
- Config B: raw Opus baseline
- Config C: Hank gateway
- Config D: Hank gateway with benchmark skills/static public date

Provider-agnostic refactors must include Claude regression checks.

### 2.3 Model ID verification

This implementation uses `gpt-5.5` as the requested target label for local Codex/OAuth testing and for the mirrored OpenAI/API config surface. Before any production API deployment, re-check the exact public OpenAI API model ID, endpoint requirements, and pricing from official OpenAI docs.

## 3. Current State Map

### 3.1 VAL harness repo

Root:

`/Users/henrychien/Documents/Jupyter/risk_module/evals/vals-finance-agent`

Key files:

| Area | File | Current behavior |
|---|---|---|
| Official/remote Vals runner | `harness/run_vals_suite.py` | Hard-gates Anthropic OAuth and supports configs A/B/C. |
| Local runner | `harness/run_local_suite.py` | Hard-gates Anthropic OAuth and supports configs A/B/C/D. |
| Anthropic OAuth patch | `harness/oauth_compat.py` | Anthropic/model-library-specific monkey patch to avoid PAYG API usage. |
| Hank model-library wrapper | `harness/hank_model.py` | Rejects non-`anthropic/claude-opus-4*` model names. |
| Gateway wrapper | `harness/hank_devcli_model.py` | Calls `agent_gateway_cli chat`, but currently ignores `model_name` and does not pass `--model`. |
| Trace output | `harness/trace_logger.py` | Mostly provider-agnostic; config slugging can support new names. |
| Result aggregation | `scripts/aggregate_results.py` | Hardwired around config A, repeated config B, optional config C. |
| Claude scripts | `scripts/run_config_a.sh`, `scripts/run_config_b.sh`, `scripts/run_config_c.sh`, `scripts/run_config_d_static_public.sh` | Anthropic-focused wrappers and preflight checks. |

Existing configs:

| Config | File | Model | Route |
|---|---|---|---|
| A | `configs/config_a_hank.py` | `anthropic/claude-opus-4-7` | Hank model-library wrapper |
| B | `configs/config_b_raw_opus.py` | `anthropic/claude-opus-4-7` | Raw vendored finance-agent baseline |
| C | `configs/config_c_hank_gateway.py` | `anthropic/claude-opus-4-7` | Gateway through dev CLI |
| D | `configs/config_d_hank_skills.py` | `anthropic/claude-opus-4-7` | Gateway through dev CLI with benchmark skill routing |

### 3.2 Gateway repo

Root:

`/Users/henrychien/Documents/Jupyter/AI-excel-addin`

Key files:

| Area | File | Current behavior |
|---|---|---|
| Provider interface | `packages/agent-gateway/agent_gateway/providers/base.py` | Provider-agnostic normalized stream/tool contract. |
| Anthropic provider | `packages/agent-gateway/agent_gateway/providers/anthropic.py` | Supports API and OAuth. |
| OpenAI provider | `packages/agent-gateway/agent_gateway/providers/openai.py` | Uses public OpenAI client/chat-completions style path. Model table is GPT-4/o1/o3-era and needs GPT-5-family review. |
| Codex provider | `packages/agent-gateway/agent_gateway/providers/codex.py` | Uses ChatGPT/Codex backend token path. Has generic `gpt-5*` model-info fallback. |
| Provider config | `api/credentials.py` | Supports `anthropic`, `openai`, and `codex` env-based configuration. |
| Gateway app wiring | `api/main.py` | Builds runtime from configured provider. Multi-user resolver path currently guards to Anthropic only. |
| Model catalog | `api/agent/shared/tool_catalog.py` | Lists allowed/default models. Codex list currently stops at `gpt-5.4`; OpenAI list does not include GPT 5.5. |
| CLI transport | `packages/agent-gateway-cli/agent_gateway_cli/transport.py` | Sends `model` to the gateway if supplied. |

## 4. Target Configs

Use explicit GPT config names so the existing A/B/C/D Claude configs remain stable.

Recommended minimum:

| New config | Purpose | Model | Route |
|---|---|---|---|
| `config_gpt55_raw_baseline.py` | Raw GPT 5.5 baseline | `gpt-5.5` or confirmed provider-qualified equivalent | Raw Vals finance-agent baseline path |
| `config_gpt55_hank_gateway.py` | GPT 5.5 with Hank gateway/tooling/harness | `gpt-5.5` | Gateway dev CLI with `--model` |

Recommended if we want exact parity with current Claude gateway variants:

| New config | Purpose |
|---|---|
| `config_gpt55_hank_gateway.py` | Mirror Config C, plain gateway route. |
| `config_gpt55_hank_skills.py` | Mirror Config D, benchmark skill/static public route. |

Decision: unless runtime cost or time is tight, implement both gateway and gateway+skills GPT configs. Config D is the most representative "tooling + harness" path, while Config C is useful for isolating the skill layer.

## 5. Implementation Phases

### Phase 0 - Preflight and source verification

Dependencies: none.

Tasks:

- Verify the exact public OpenAI API model ID for GPT 5.5 and whether it requires Responses API support.
- Verify the local Codex/ChatGPT subscription model ID accepted by the Codex backend.
- Confirm whether the vendored `model-library` and Vals finance-agent raw baseline can call GPT 5.5 without using public API credits.
- Decide whether local GPT raw baseline can use Codex/OAuth. If not, explicitly document that raw GPT baseline requires public API mode or implement a narrow adapter.

Exit criteria:

- One confirmed model ID for local Codex/OAuth testing.
- One confirmed model ID and endpoint strategy for public OpenAI API deployment.
- Decision recorded for raw GPT baseline transport.

### Phase 1 - Provider-aware harness auth

Dependencies: Phase 0 model/auth decision.

Tasks:

- Replace hard Anthropic-only gates in `harness/run_vals_suite.py` and `harness/run_local_suite.py` with config-aware auth preflights.
- Keep the Anthropic OAuth safety behavior for Claude configs:
  - require `ANTHROPIC_AUTH_MODE=oauth`
  - require `ANTHROPIC_AUTH_TOKEN`
  - reject accidental `ANTHROPIC_API_KEY`
- Add Codex/OAuth preflight for local GPT benchmark runs:
  - require `AGENT_PROVIDER=codex`
  - require `CODEX_AUTH_TOKEN`
  - require target model in `CODEX_MODEL` or config model field
  - reject accidental public API agent auth unless explicitly requested
- Add OpenAI/API preflight for deployment-mode runs:
  - require `AGENT_PROVIDER=openai`
  - require `OPENAI_AUTH_MODE=api`
  - require `OPENAI_API_KEY`
- Separate judge credentials from agent credentials. Prefer adding `HANK_VALS_LOCAL_JUDGE_OPENAI_API_KEY` so local judging does not conflict with GPT agent auth.

Exit criteria:

- Claude configs still fail closed on non-OAuth Anthropic auth.
- GPT/Codex configs fail closed if they would burn public OpenAI API credits.
- Local dry judge mode can run without any public OpenAI API key.

### Phase 2 - Gateway model routing

Dependencies: Phase 1.

Tasks:

- Update `harness/hank_devcli_model.py` to pass `--model <MODEL_NAME>` to `agent_gateway_cli chat`.
- Preserve all existing CLI flags:
  - `--session`
  - `--new`
  - `--raw`
  - `--auto-approve "*"`
  - optional `--mode benchmark`
  - optional `--disable-final-answer-guard`
- Add tests around the constructed CLI argv so Claude and GPT configs both send explicit models.
- Confirm the CLI transport already sends `model` to the gateway request body.

Exit criteria:

- Config C/D continue to run with explicit Claude model override.
- GPT gateway configs route `gpt-5.5` explicitly instead of relying on gateway defaults.

### Phase 3 - Gateway model catalog and provider support

Dependencies: Phase 0.

Tasks:

- Add confirmed GPT 5.5 IDs to the Codex model catalog and allowlist defaults.
- Add confirmed GPT 5.5 IDs to the OpenAI provider/catalog for API deployment.
- Prefer making model metadata extensible so new GPT-5-family IDs do not require code changes in multiple files.
- Review OpenAI provider endpoint strategy:
  - if GPT 5.5 requires Responses API, add Responses support to the public OpenAI provider or create a dedicated provider path;
  - do not force public API deployment through the private Codex backend.
- Add provider tests:
  - Codex `get_model_info("gpt-5.5")`
  - Codex request params include expected reasoning/tool schema
  - OpenAI public API model metadata for GPT 5.5
  - catalog allowlists include GPT 5.5 only for the intended providers

Exit criteria:

- Gateway starts with `AGENT_PROVIDER=codex` and `CODEX_MODEL=gpt-5.5`.
- Gateway accepts CLI request `model=gpt-5.5`.
- Public API route has a documented and tested model-support path.

### Phase 4 - GPT configs and scripts

Dependencies: Phases 1-3.

Tasks:

- Add GPT config files under `evals/vals-finance-agent/configs/`.
- Add scripts:
  - `scripts/run_config_gpt55_baseline.sh`
  - `scripts/run_config_gpt55_gateway.sh`
  - optional `scripts/run_config_gpt55_skills.sh`
  - optional `scripts/run_gpt55_pair.sh`
- Add local runner support for new config names.
- Add official Vals runner support for new config names if remote scoring is needed.
- Update `.env.example` and `README.md` to describe provider-aware auth:
  - Anthropic OAuth for Claude configs
  - Codex OAuth/subscription token for local GPT benchmark runs
  - OpenAI API key for deployment/API-mode runs
  - separate local judge credentials

Exit criteria:

- GPT dry-judge smoke can run without public OpenAI API agent auth.
- Existing Claude scripts remain operational.

### Phase 5 - Aggregation and reporting

Dependencies: Phase 4.

Tasks:

- Generalize `scripts/aggregate_results.py` from hardcoded A/B/C to named benchmark arms.
- Support repeated baselines:
  - e.g. `gpt55_raw_run1`, `gpt55_raw_run2`
  - compare gateway/skills arm against the mean raw baseline.
- Record per-arm metadata:
  - provider
  - model
  - auth mode, redacted
  - config name
  - gateway route
  - as-of-date mode
  - judge mode/model
- Emit side-by-side summaries:
  - Claude raw vs Claude Hank
  - GPT raw vs GPT Hank
  - Claude Hank vs GPT Hank
  - raw-model deltas
  - harness/tooling deltas

Exit criteria:

- Aggregator can score Claude-only, GPT-only, or combined runs.
- No fixed Anthropic benchmark score is used as the GPT baseline.

### Phase 6 - Validation and regression

Dependencies: Phases 1-5.

Tasks:

- Run unit tests for the VAL harness changes.
- Run gateway provider tests for Anthropic, Codex, and OpenAI.
- Run CLI argv/transport tests.
- Run no-spend smoke:
  - gateway health
  - CLI single prompt
  - one VAL question with `--dry-judge`
  - one tool-heavy VAL question with `--dry-judge`
- Run targeted question set across Claude and GPT configs.
- Run full GPT public-50 only after auth mode and traces confirm no public API credits are being used for local subscription-token mode.

Exit criteria:

- No auth/key leakage in logs.
- No public OpenAI API agent usage in local Codex/OAuth mode.
- Claude smoke/regression still passes.
- GPT smoke reaches final-answer extraction and trace logging.

## 6. Failure Triage Process

When GPT switching surfaces issues, classify the failure before fixing it.

### 6.1 Provider adapter failure

Examples:

- malformed tool schema
- stream event not parsed
- tool call ID mismatch
- reasoning block incompatibility
- terminal completion not detected

Fix location:

- `packages/agent-gateway/agent_gateway/providers/codex.py`
- `packages/agent-gateway/agent_gateway/providers/openai.py`
- provider tests

Do not fix this with benchmark-specific prompt hacks.

### 6.2 Auth or infra failure

Examples:

- wrong token source
- accidental public API key use
- gateway starts with wrong provider
- resolver/multi-user path rejects non-Anthropic provider
- rate-limit handling differs by provider

Fix location:

- `api/credentials.py`
- `api/main.py`
- provider credential refresh handling
- harness auth preflight

Preserve Anthropic OAuth behavior while adding provider-general logic.

### 6.3 Harness failure

Examples:

- config runner only accepts A/B/C/D
- aggregator assumes Claude baseline
- trace slugging drops GPT config metadata
- local judge env conflicts with GPT auth

Fix location:

- `evals/vals-finance-agent/harness/*`
- `evals/vals-finance-agent/scripts/*`

### 6.4 Tooling or skill failure

Examples:

- GPT does not select the right tool
- GPT emits malformed args for an otherwise valid tool
- benchmark skill assumes Claude-specific phrasing
- final answer guard overfits Claude behavior

Fix location:

- gateway tool schemas
- benchmark skill metadata
- provider-agnostic system prompt/tool instructions
- final-answer guard normalization

Keep changes model-neutral unless there is a provider-specific schema limitation.

### 6.5 Benchmark/data failure

Examples:

- as-of date drift
- source-date audit false positives
- judge disagreement
- raw baseline transport differs from harnessed transport

Fix location:

- as-of-date audit
- benchmark run metadata
- scoring/judge settings
- documented exclusions or rerun policy

## 7. Validation Matrix

| Check | Claude OAuth | GPT Codex/OAuth | GPT OpenAI/API |
|---|---:|---:|---:|
| Harness imports config | Required | Required | Required |
| Auth preflight rejects wrong credential mode | Required | Required | Required |
| Gateway starts with provider | Required | Required | Required |
| CLI sends explicit `model` | Required | Required | Required |
| Tool schema conversion works | Required | Required | Required |
| Streaming final answer parsed | Required | Required | Required |
| Trace metadata records provider/model | Required | Required | Required |
| Dry-judge 1-question smoke | Required | Required | Optional |
| Public-50 full run | Existing path | Target local run | Deployment validation only |
| No public API agent spend | Anthropic OAuth guard | Codex token guard | Not applicable |

## 8. Implementation Notes And Run Process

Resolved implementation choices:

1. Use `gpt-5.5` as the GPT 5.5 model label for both Codex/OAuth and OpenAI/API paths.
2. The raw Vals finance-agent baseline uses a model-library adapter backed by the gateway provider contract, so local raw GPT runs can use Codex/ChatGPT OAuth without public OpenAI API agent spend.
3. The default GPT comparison is raw GPT baseline twice plus GPT Hank `config_gpt55_hank_skills`; pass `--gateway` to `scripts/run_gpt55_pair.sh` to compare against the plain gateway route instead.
4. Local judge credentials are separated with `HANK_VALS_LOCAL_JUDGE_OPENAI_API_KEY`, falling back to `OPENAI_API_KEY`.
5. Resolver-backed gateway deployments now support `AGENT_PROVIDER=anthropic`, `openai`, or `codex`; `agent-sdk` remains outside the resolver `AuthConfig` contract.

Operational process for model-switch issues:

1. Run the provider/auth preflight first. GPT Codex/OAuth configs require either a valid `CODEX_AUTH_TOKEN` or `CODEX_AUTH_JSON`/`~/.codex/auth.json` containing a valid `tokens.access_token`. If the token is JWT-shaped, the harness checks `exp` locally and fails before launching a VAL question when the token is expired or close to expiry.
2. Keep `HANK_VALS_GPT55_PROVIDER` authoritative. GPT scripts set `AGENT_PROVIDER` from that value after loading the vendor `.env`, preventing inherited Claude provider settings from silently overriding GPT runs.
3. For local no-public-API-credit runs, keep `HANK_VALS_GPT55_PROVIDER=codex` and do not set `HANK_VALS_ALLOW_OPENAI_API_AGENT=1`.
4. For deployment/API validation, set `HANK_VALS_GPT55_PROVIDER=openai`, `AGENT_PROVIDER=openai`, `OPENAI_AUTH_MODE=api`, `OPENAI_API_KEY`, and `HANK_VALS_ALLOW_OPENAI_API_AGENT=1`.
5. If a live smoke fails, classify it before changing prompts or tools:
   - auth/provider failure: fix env, token freshness, gateway provider config, or provider adapter;
   - model metadata failure: fix model catalog, allowlist, or provider metadata;
   - tool schema/stream failure: fix gateway/model-library conversion with provider-neutral tests;
   - behavior/quality failure: fix skills, prompts, guards, or source-selection logic in a model-neutral way.

Current live-smoke status:

- GPT raw baseline q010 dry-judge smoke passed using Codex/OAuth from `~/.codex/auth.json`.
- GPT raw baseline q007 dry-judge targeted smoke also passed using Codex/OAuth from `~/.codex/auth.json`.
- GPT Hank skills q010 dry-judge smoke passed through the live gateway.
- GPT Hank plain gateway q010 dry-judge smoke passed through the live gateway after the gateway gained a provider-neutral oversized tool-result compaction guard.
- Claude raw Opus q010 dry-judge regression passed under Anthropic OAuth with `ANTHROPIC_API_KEY` empty.
- One model-switch issue surfaced and was fixed at the gateway root cause: GPT rejected an over-context follow-up after a large inline tool result. The gateway now preserves the full tool result in the event log but compacts oversized model-bound `tool_result` payloads before the next provider request.

## 9. Implementation Goal Used

This was the implementation prompt:

> Implement GPT 5.5 VAL benchmark parity end to end: add provider-aware auth/config support to the VAL harness and gateway, add GPT 5.5 raw baseline and GPT 5.5 Hank gateway/skills configs using my Codex/ChatGPT OAuth token for local benchmark runs while retaining OpenAI API mode for deployment, update scripts/aggregation/docs, and verify with dry-judge smoke, targeted VAL qIDs, gateway provider tests, and Claude regression smoke without breaking the existing Opus configs.

## 10. Initial Task Breakdown

1. Done: Confirm model IDs and raw-baseline transport.
2. Done: Add provider-aware auth preflight to the VAL harness.
3. Done: Pass explicit model names from `hank_devcli_model.py` to `agent_gateway_cli chat --model`.
4. Done: Add GPT 5.5 to gateway model catalogs/provider metadata.
5. Done: Add GPT config files and run scripts.
6. Done: Generalize result aggregation by named benchmark arms.
7. Done: Update README and `.env.example`.
8. Done: Add/adjust tests for harness config routing, gateway providers, CLI model propagation, aggregation, Codex provider behavior, and oversized tool-result compaction.
9. Done: Run no-spend GPT smoke tests on q010 plus a raw q007 targeted check.
10. Done: Run Claude regression smoke on q010.
11. Pending: Run a broader targeted GPT question set.
12. Pending: Run full GPT public-50 after auth and trace gates pass.
