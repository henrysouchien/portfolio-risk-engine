> **✅ SHIPPED — SSM app-secrets two-tier scheme live (dev 5-13 / prod 5-14). Moved during 2026-05-26 docs cleanup.**

# App-Level Secrets → SSM Parameter Store Migration

## Status: v7 — Codex R6 PASSED with 4 P1 + 1 P2 + 3 new-findings as hardening. v7 incorporates all hardening: CI guard scope-strengthened (indirect-import detection, `git ls-files`, both `import` and `from-import` forms), explicit MCP-registration line numbers, follow-up plan template creation, and `snapshot_estimates.py` deprecation resolution.

Sibling to `CREDENTIALS_KMS_MIGRATION_PLAN.md` (per-user creds, shipped 2026-04-30) and `CREDENTIALS_KMS_ARCHITECTURE.md`. This plan migrates **app-level** secrets — the keys in `.env` that don't change per user — from per-developer `.env` files into AWS SSM Parameter Store SecureStrings, encrypted by the same KMS CMK already in use for per-user credentials.

## Motivation

Today, every developer/deployment that runs risk_module needs a hand-curated `.env` file with ~30 shared secret values. Three concrete problems:

1. **Onboarding a collaborator means sharing my `.env`** (or a sanitized copy), which fragments the source of truth and leaks production-grade credentials (Plaid production secret, SnapTrade consumer key, AWS access keys, OAuth client secrets) to teammates who may only need dev access.
2. **No audit trail.** Once a secret is in `.env`, there's no record of who fetched it or when.
3. **No single source of truth.** Drift between local `.env` and prod EC2 `.env` has caused incidents.

Secondary wins: CloudTrail audit, IAM-flip revocation instead of key rotation, clean colleague onboarding (he gets IAM identity, not my `.env`).

**Out of scope** (named explicitly to make deferral intentional):
- **Per-user credentials** — already migrated to KMS-encrypted DB columns 2026-04-30
- **AI-excel-addin SSM migration** — pre-deploy; this plan only delivers `.env.example` + cross-repo wiring doc
- **EC2 instance role** replacing long-lived `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` — separate plan
- **`ANTHROPIC_AUTH_TOKEN` migration** — stays per-developer in `.env` per OAuth-only rule (memory: `feedback_anthropic_oauth_only`)
- **Frontend env vars** (`VITE_GOOGLE_CLIENT_ID`) — these are build-time, separate `frontend/.env` flow already exists

## Hard prerequisites

- [x] AWS account with the existing KMS CMK provisioned (`alias/risk-module-credentials-dev` and `alias/risk-module-credentials-prod`)
- [x] App IAM principal (`plaid-access-token-service`) already has `kms:Encrypt`/`kms:Decrypt` on both CMKs
- [x] `AWS_DEFAULT_REGION` and `KMS_CREDENTIAL_KEY_ARN` set in `.env` for all environments
- [x] `moto>=5.1.0` in `requirements-dev.txt` (currently `moto[kms]`; Phase 2 extends to `moto[kms,ssm]`)
- [ ] Existing CMK key policy amended to grant SSM-service access for the colleague IAM user (Phase 4 deliverable)

## Goal

End state after Phase 5 (prod cutover):

1. Backend, MCP servers, Celery workers/beat, and standalone scripts all boot by importing a single `bootstrap_env.py` module that loads `.env` *then* hydrates SSM SecureStrings into `os.environ` *before* any other module reads its env vars.
2. **Two-tier namespace** in SSM:
   - `/risk-module/{env}/shared/*` — low-stakes (API keys, gateway/HMAC keys, OAuth client, session secrets). **Colleague can read.**
   - `/risk-module/{env}/broker/*` — high-stakes (Plaid/SnapTrade/Schwab app credentials with `PLAID_ENV=production`). **App principal only.**
3. ~17 app-level secrets removed from `.env` (11 shared + 6 broker, verified via grep — see Appendix A).
4. Each env's `.env` retains only: infra config, local-bootstrap creds (`AWS_*` + `KMS_CREDENTIAL_KEY_ARN`), per-developer personal values.
5. Colleague has IAM user `dev-<name>` with `ssm:GetParametersByPath` permission on `/risk-module/dev/shared/*` only — cannot read broker tier, cannot read prod, cannot decrypt per-user creds.
6. AI-excel-addin has a checked-in `.env.example` + `docs/setup/CROSS_REPO_WIRING.md`; its SSM migration is filed as a follow-up, not blocked on this one.

## Architecture

### `bootstrap_env.py` — the new module

```python
# /Users/henrychien/Documents/Jupyter/risk_module/bootstrap_env.py
"""
Loads .env then hydrates SSM SecureStrings into os.environ.

Must be imported FIRST by every process entry point — before
settings.py, before utils.config, before any module that reads
os.environ at module top level.

Stdout-silent guarantee: this module MUST NOT write to stdout under
any circumstance (MCP servers use stdout for JSON-RPC; non-protocol
stdout breaks them). All logging goes to stderr via the `logging`
module configured at WARNING level.
"""
```

**Behavior:**
1. Idempotent — guarded by a module-level `_BOOTSTRAPPED` flag.
2. Always calls `load_dotenv()` on the repo-root `.env`.
3. Decides whether to call SSM via `_should_hydrate_from_ssm()`:
   - If `USE_SSM_SECRETS` is explicitly set: respect it (`"true"`/`"false"`)
   - If unset:
     - `ENVIRONMENT=production` → default `true`
     - `ENVIRONMENT=development` or `test` → default `false`
     - Unknown/unset `ENVIRONMENT` → default `false`
4. If hydrating: **two separate `ssm:GetParametersByPath` calls**, one per tier:
   - `Path="/risk-module/<env>/shared/"`, `Recursive=False`, `WithDecryption=True`, paginating
   - `Path="/risk-module/<env>/broker/"`, `Recursive=False`, `WithDecryption=True`, paginating
   - **AccessDenied semantics depend on `SSM_REQUIRE_BROKER_TIER` env var** (Codex R4 P0 #1 — Architecture now matches Phase 2):
     - `SSM_REQUIRE_BROKER_TIER=true` (app principal default) + broker AccessDenied → **raise** (means policy misconfigured)
     - `SSM_REQUIRE_BROKER_TIER=false` (colleague template) + broker AccessDenied → log INFO and continue (intentional scope)
     - In production, `SSM_REQUIRE_BROKER_TIER` is **forced** to `true` regardless of `.env` value — prod cannot legitimately have a colleague-style principal (Codex R4 P1 #4)
     - AccessDenied on the shared call IS always fatal — no flag overrides this.
   - **Correction from v2 (Codex R2 P0 #1):** the v2 plan used a single recursive call against the parent path `/risk-module/<env>/`. AWS `GetParametersByPath` recursive access is path-based; granting parent-path access bypasses the tier split. Splitting into two calls is the only safe pattern.
5. **Precedence (decided):**
   - **Dev (`ENVIRONMENT=development`)**: `.env` wins over SSM. Locally-set values take priority.
   - **Prod (`ENVIRONMENT=production`)**: SSM wins over `.env`. Single source of truth.
6. **Fail modes:**
   - SSM unreachable + `ENVIRONMENT=production` → raise + exit (prod must not boot with unknown secret state)
   - SSM unreachable + `ENVIRONMENT=development` → log warning to stderr, continue with `.env` only
   - **Required parameter missing in prod** → raise + exit. Required list is passed by each entry point via `bootstrap(required=[...])` kwarg; see §"Required secrets — per-entry-point pattern" below. No global table.
   - **Optional parameter missing** → no-op; consuming code's `os.getenv(..., default)` handles it.
   - Throttling → boto3 retry config (same as cipher.py) handles transparently.
7. **Stdout discipline:** Module configures its logger to emit to `sys.stderr` at import time. No `print()` calls anywhere in the module. Test asserts `sys.stdout.write` is never called during `bootstrap()` (Phase 1 verify gate).

**Entry-point integration (file list — Phase 1 deliverable, verified via grep + Makefile inspection):**

Add `import bootstrap_env` as the FIRST non-stdlib import in each:

| Entry point | Process | Already calls `load_dotenv`? |
|---|---|---|
| `app.py` | FastAPI (`python3 -m uvicorn app:app`) | Yes, line 191 — but after many imports |
| `mcp_bootstrap.py` | All FastMCP servers via `bootstrap()` | Yes, line 110 — INSIDE bootstrap() |
| `fmp/server.py` | `python3 -m fmp.server` (MCP) | No — relies on `fmp/client.py:55` |
| `ibkr/server.py` | `python3 -m ibkr.server` (MCP) | Yes, lines 22-23 |
| `workers/celery_app.py` | `python3 -m celery -A workers.celery_app.app worker` | No |
| `workers/beat_schedule.py` | `python3 -m celery -A workers.beat_schedule.app beat` | No |
| `app_platform/api_budget/__main__.py` | `python3 -m app_platform.api_budget` | No |
| `core/run_portfolio_risk.py` | Direct CLI | Yes, line 14 |
| `core/risk_orchestration.py` | Direct CLI | Yes, line 19 |
| `scripts/health_check.py` | Health check entrypoint | Yes, line 51 (inside function) |
| `scripts/run_migrations.py` | DB migration runner | Implicit via settings.py |
| `scripts/migrate_credentials_to_kms.py` | Legacy migration | Reads AWS env directly |
| `scripts/run_plaid.py` | `python3 -m scripts.run_plaid` (CLI) | No — imports `brokerage.plaid` at line 18 |
| `scripts/run_snaptrade.py` | `python3 -m scripts.run_snaptrade` (CLI) | Yes, line 23 — but before broker import |
| `scripts/run_schwab.py` | `python3 -m scripts.run_schwab` (CLI) | No — imports `brokerage.config` + `brokerage.schwab` |
| `scripts/run_positions.py` | `python3 -m scripts.run_positions` (CLI) | Touches provider flows — include for safety |
| `scripts/run_trading_analysis.py` | CLI | Touches provider flows — include for safety |
| `scripts/plaid_reauth.py` | CLI (Codex R3 P0 #3) | Plaid SDK at module load |
| `scripts/diagnose_plaid_balances.py` | CLI | Plaid client + balance refresh |
| `scripts/snaptrade_sdk_smoke.py` | CLI smoke | SnapTrade SDK |
| `scripts/check_schwab_token.py` | CLI | Schwab token validation |
| `scripts/explore_transactions.py` | CLI | Broker module imports |
| `scripts/cleanup_stale_data_sources.py` | CLI | Provider routing + broker imports |
| `scripts/corpus_phase2_universe_select.py` | CLI (Codex R4 P0 #3) | `FMP_API_KEY` at line 99 |
| `scripts/corpus_phase3_bulk_ingest_transcripts.py` | CLI | `FMP_API_KEY` at line 68 |
| `scripts/backfill_ticker_aliases.py` | CLI | `FMP_API_KEY` at line 29 |
| `scripts/benchmark_editorial_arbiter.py` | CLI | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` at line 322-325 |
| `scripts/corpus_phase1_delta_ingest.py` | CLI (Codex R5 P0 #1) | Calls `core/corpus/edgar_api_client.py` which reads `EDGAR_API_KEY` |
| `scripts/corpus_bulk_reingest.py` | CLI | Same — EDGAR corpus path |
| `scripts/corpus_ingest_accession.py` | CLI | Same — EDGAR corpus path |
| `tests/conftest.py` | pytest entry | Set `USE_SSM_SECRETS=false` BEFORE importing bootstrap_env (test-collection-time, not fixture-time) |

Order at each entry point:
```python
import bootstrap_env  # noqa: E402 — must be first
bootstrap_env.bootstrap()  # explicit call
# ... rest of stdlib + third-party + local imports follow
```

The brokerage-connect standalone package (`brokerage/config.py`) is NOT modified. It has its own `load_dotenv(..., override=False)` at line 12 — verified that `override=False` means SSM-hydrated values in `os.environ` are preserved when load_dotenv reads `.env` second.

### Required secrets — per-entry-point pattern (rewritten v4 per Codex R3 P1 #2 + #3)

**Correction from v3:** v3 claimed a global `REQUIRED_SECRETS` list whose absence raises at prod boot. Reading actual code: today no boot-time validation exists — `mcp_bootstrap.py:37-43` warns but doesn't raise; `GATEWAY_API_KEY` raises only at request time; `FLASK_SECRET_KEY` raises only in the app server production session-middleware path. A single global list also misclassifies — the FMP MCP server doesn't need `GATEWAY_API_KEY`, Celery doesn't need `FLASK_SECRET_KEY`.

**v4 design — per-entry-point required list:**

`bootstrap_env.bootstrap()` accepts an optional kwarg `required: list[str] = ()`. Each entry point passes the list of secrets IT needs:

```python
# app.py
import bootstrap_env
bootstrap_env.bootstrap(required=["FMP_API_KEY", "GATEWAY_API_KEY", "FLASK_SECRET_KEY"])

# fmp/server.py
bootstrap_env.bootstrap(required=["FMP_API_KEY"])

# workers/celery_app.py
bootstrap_env.bootstrap(required=["CELERY_BROKER_URL"])

# scripts/run_plaid.py
bootstrap_env.bootstrap(required=["PLAID_CLIENT_ID", "PLAID_SECRET"])
```

Bootstrap behavior:
- After `.env` load + SSM hydration, check that every name in `required` is present and non-empty in `os.environ`
- `ENVIRONMENT=production` + any required missing → raise `RuntimeError` with this exact shape (Codex R5 P1 #3 — informative, no values):
  ```
  RuntimeError(
    f"bootstrap_env: required secret(s) missing after hydration: {missing!r}. "
    f"env={environment} ssm_enabled={use_ssm} ssm_param_count={len(hydrated)}. "
    f"Check .env, SSM /risk-module/{environment}/shared/ and /broker/, and IAM."
  )
  ```
  The `missing` list contains NAMES only (never values). `hydrated` count is informational (helps distinguish "SSM returned 0 params" from "SSM returned 11 but one I need is absent").
- `ENVIRONMENT=development` + any required missing → log warning to stderr (lets partial-setup dev work)
- Empty `required=()` (default) → no validation; bootstrap is informational only

This moves the responsibility for "what does this process need" from a global table to the entry point itself, which is the only place that actually knows.

**Per-entry-point required lists** (Phase 1 deliverable — wire each entry point's `required` kwarg):

| Entry point | Required at prod boot |
|---|---|
| `app.py` | `FMP_API_KEY`, `GATEWAY_API_KEY`, `FLASK_SECRET_KEY`, `GOOGLE_CLIENT_ID` (NOT `GOOGLE_CLIENT_SECRET` per Codex R4 P1 #3 — assigned but unused beyond `app.py:328`) |
| `mcp_bootstrap.py` | `FMP_API_KEY` |
| `fmp/server.py` | `FMP_API_KEY` |
| `ibkr/server.py` | (none — IBKR Gateway is local; no app-level secrets) |
| `workers/celery_app.py` | `CELERY_BROKER_URL` (in infra `.env`, not SSM — listed for completeness) |
| `workers/beat_schedule.py` | `CELERY_BROKER_URL` |
| `scripts/run_plaid.py` | `PLAID_CLIENT_ID`, `PLAID_SECRET` |
| `scripts/run_snaptrade.py` | `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY` |
| `scripts/run_schwab.py` | `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET` |
| `scripts/plaid_reauth.py` | `PLAID_CLIENT_ID`, `PLAID_SECRET` (Codex R4 P1 #2) |
| `scripts/diagnose_plaid_balances.py` | `PLAID_CLIENT_ID`, `PLAID_SECRET` |
| `scripts/snaptrade_sdk_smoke.py` | `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY` |
| `scripts/check_schwab_token.py` | `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET` |
| `scripts/corpus_phase2_universe_select.py` | `FMP_API_KEY`, `EDGAR_API_KEY` (Codex R5 P0 #1 — corpus phase 2 also calls EDGAR client) |
| `scripts/corpus_phase1_delta_ingest.py` | `EDGAR_API_KEY` |
| `scripts/corpus_bulk_reingest.py` | `EDGAR_API_KEY` |
| `scripts/corpus_ingest_accession.py` | `EDGAR_API_KEY` |
| `scripts/corpus_phase3_bulk_ingest_transcripts.py` | `FMP_API_KEY` |
| `scripts/backfill_ticker_aliases.py` | `FMP_API_KEY` |
| `scripts/benchmark_editorial_arbiter.py` | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` |
| other scripts | `required=()` — informational bootstrap |

**Feature-gated optional secrets** (absence disables a feature; no bootstrap validation):
- `OPENAI_API_KEY`, `EDGAR_API_KEY`, `ADMIN_TOKEN`, `GATEWAY_RESOLVER_HMAC_KEY`, `AGENT_API_*` — each fails at the consuming code path, not at boot.

### Namespace design (two-tier)

```
/risk-module/dev/shared/openai-api-key            (SecureString, low-stakes)
/risk-module/dev/shared/fmp-api-key
/risk-module/dev/shared/gateway-api-key
... (11 total)

/risk-module/dev/broker/plaid-client-id           (SecureString, high-stakes)
/risk-module/dev/broker/plaid-secret
... (6 total)

/risk-module/prod/shared/*                        (same structure)
/risk-module/prod/broker/*
```

**Naming rules:**
- Lowercase kebab-case in SSM (`openai-api-key`); env-var-style at hydration time (`OPENAI_API_KEY`).
- Strict mapping function `_param_to_env(name: str) -> str` with explicit regex validation (`^[a-z][a-z0-9-]*[a-z0-9]$`) and collision-check unit test asserting the round-trip is bijective across the known list.
- One SSM parameter per env var. No bundled JSON blobs.
- Standard tier (not Advanced) — 4 KB max per value. Provisioning script validates length pre-write.
- All SecureString, all encrypted with the same `alias/risk-module-credentials-{env}` CMK.

**KMS encryption context note:** SSM SecureStrings do NOT accept user-supplied encryption context. SSM internally passes `{"PARAMETER_ARN": "<full-arn>"}` as the encryption context on its KMS calls. The IAM `kms:Decrypt` condition must match THIS (not `app`/`env` like the per-user creds path). See "IAM design" below.

### What stays in `.env`

- **Infra config** (~80 keys): `DATABASE_URL`, `REDIS_URL`, `CELERY_*`, ports, feature flags, sync intervals — Appendix A.2
- **Bootstrap creds** (4 keys): `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`, `KMS_CREDENTIAL_KEY_ARN` — chicken-and-egg
- **Personal** (~15 keys): Henry's IBKR/email/OAuth token — Appendix A.4
- **AI-excel-addin-only keys** that happen to be in risk_module's `.env` today but aren't actually read by risk_module Python: `GOOGLE_API_KEY`, `BRAVE_API_KEY`, `OPENAI_EMBEDDING_KEY`, `EXCEL_MCP_SECRET`, `GATEWAY_API_KEY_{EXCEL,TELEGRAM,WEB,MCP,CLI}` — should be removed from risk_module `.env` entirely (Phase 6 cleanup item). **NOT `CHAT_API_KEY`** — that intentionally stays in `risk_module/.env` per the shipped TUI wiring (`docs/planning/completed/GATEWAY_CLI_CHANNEL_WIRING_PLAN.md:114`).
- **Frontend Vite vars**: `VITE_GOOGLE_CLIENT_ID` (in `frontend/.env`, not repo-root `.env`) — build-time, not runtime

## Scope (binary checklist — locked with §"Implementation steps" below)

- [ ] §S1 — `bootstrap_env.py` module exists, idempotent, stdout-silent, with unit tests
- [ ] §S2 — Every entry point in §"Entry-point integration" table imports `bootstrap_env` first
- [ ] §S3 — `tests/conftest.py` sets `USE_SSM_SECRETS=false` at module-collection time
- [ ] §S4 — `scripts/perf_measurement.py:20` hardcoded `ADMIN_TOKEN` literal removed (was P0 cleanup in v1 Phase 7; moved to Phase 1 to close pre-clone exposure window)
- [ ] §S5 — `scripts/provision_ssm_params.py` exists, idempotent, validates kebab-case + 4 KB length
- [ ] §S6 — `requirements-dev.txt` updated to `moto[kms,ssm]>=5.1.0`
- [ ] §S7 — IAM policy `risk-module-ssm-read-dev-shared` (app, shared tier)
- [ ] §S8 — IAM policy `risk-module-ssm-read-dev-broker` (app, broker tier)
- [ ] §S9 — Provisioner identity (`finance-web-deploy`) has temporary write policy `risk-module-ssm-write-dev`; detached after Phase 3 cutover
- [ ] §S10 — All 11 dev shared secrets provisioned to `/risk-module/dev/shared/*`
- [ ] §S11 — All 6 dev broker secrets provisioned to `/risk-module/dev/broker/*`
- [ ] §S12 — Pre-cutover backup: dev `.env` migration values exported to sealed 1Password entry; restore drill executed
- [ ] §S13 — Dev `.env` reduced to infra+bootstrap+personal only; smoke tests pass
- [ ] §S14 — IAM user `dev-<colleague-name>` exists with policy `risk-module-ssm-read-dev-shared-readonly`
- [ ] §S15 — Existing CMK key policy amended to grant the colleague IAM user `kms:Decrypt` (with `kms:ViaService` SSM condition)
- [ ] §S16 — `.env.colleague.template` checked in; `docs/setup/COLLABORATOR_SETUP.md` written; colleague runs end-to-end successfully
- [ ] §S17 — IAM policies `risk-module-ssm-read-prod-shared` + `risk-module-ssm-read-prod-broker` for app principal
- [ ] §S18 — Pre-cutover prod backup
- [ ] §S19 — All 17 prod secrets provisioned to `/risk-module/prod/{shared,broker}/*`
- [ ] §S20 — Prod `.env` reduced; prod smoke tests pass; CloudTrail confirms SSM reads
- [ ] §S21 — AI-excel-addin `.env.example` checked in
- [ ] §S22 — `docs/setup/CROSS_REPO_WIRING.md` written
- [ ] §S23 — `AI-excel-addin/.env.bak` removed
- [ ] §S24 — AI-excel-addin-only keys removed from risk_module's `.env` (`GOOGLE_API_KEY`, `BRAVE_API_KEY`, `OPENAI_EMBEDDING_KEY`, `EXCEL_MCP_SECRET`, `GATEWAY_API_KEY_*` channel keys). NOT `CHAT_API_KEY` — kept per TUI wiring; see §"Implementation steps / Phase 6 / step 4" for justification.
- [ ] §S25 — `docs/deployment/SSM_APP_SECRETS_ARCHITECTURE.md` written (sibling to `CREDENTIALS_KMS_ARCHITECTURE.md`)

## Implementation steps (sequenced — §5↔§6 sync)

Phases are binary stages with verify gates. Phase reordering vs v1: **colleague enablement now Phase 4 (before prod cutover Phase 5)** so the pattern bakes with two machines before prod, addressing Codex P1 #5.

### Phase 1 — Bootstrap module + tests + ADMIN_TOKEN cleanup
**Scope items:** §S1, §S2, §S3, §S4, §S6

1. Write `bootstrap_env.py`:
   - `load_dotenv()` path active
   - SSM hydration path stubbed (logs "SSM hydration disabled — set USE_SSM_SECRETS=true" to stderr)
   - Stdout-silence: zero `print()` calls; logger configured to stderr; `_param_to_env()` helper with regex validation
   - `bootstrap(required: list[str] = ())` kwarg API — NO module-level `REQUIRED_SECRETS` constant. Each entry point passes its own list. See §"Required secrets — per-entry-point pattern" (Codex R4 P1 #1).
2. Write `tests/test_bootstrap_env.py`:
   - Idempotency (calling `bootstrap()` twice = one-shot effect)
   - `.env` loading works
   - `USE_SSM_SECRETS=false` short-circuits SSM path
   - **Stdout assertion**: `bootstrap()` does not write to `sys.stdout` (patch `sys.stdout.write` to raise; expect no raise)
   - `_param_to_env()` round-trip bijective across the known param list
   - `USE_SSM_SECRETS` default derived from `ENVIRONMENT` when unset
3. Update `requirements-dev.txt`: `moto[kms]` → `moto[kms,ssm]`
4. **§S4 — fix `scripts/perf_measurement.py:20`** — replace hardcoded `ADMIN_TOKEN = "adm-tok-..."` literal with `os.environ["ADMIN_TOKEN"]` (script is dev-only; fail-loud on unset is correct). MOVED FROM v1 PHASE 7 — closes the pre-clone exposure window.
5. Add `import bootstrap_env; bootstrap_env.bootstrap()` as first non-stdlib import in every entry point listed in §"Entry-point integration" table.
6. **Verify gate:** Full test suite passes. Backend + MCP servers + Celery workers + beat all boot locally. No JSON-RPC protocol corruption from MCP servers (manual: connect via Claude Code's MCP client and list tools). Stdout-silence test passes.

### Phase 2 — SSM hydration + IAM dev policies + moto tests
**Scope items:** §S7, §S8, bootstrap SSM activation

1. Implement the SSM path in `bootstrap_env.py` (corrected from v3 per Codex R3 P0 #1 — Phase 2 spec now matches Architecture spec):
   - `boto3.client("ssm", region_name=...)` with same retry config as cipher.py
   - **Two separate `get_parameters_by_path` calls, `Recursive=False`:**
     - `Path="/risk-module/<env>/shared/"` — paginator loop; required
     - `Path="/risk-module/<env>/broker/"` — paginator loop; expected based on `SSM_REQUIRE_BROKER_TIER` env var
   - **AccessDenied disambiguation (Codex R3 P0 #2):** algorithm for resolving effective `SSM_REQUIRE_BROKER_TIER` value (Codex R5 P2 #1 — explicit algorithm):
     1. Read raw value from env (default `true` if unset)
     2. If `ENVIRONMENT=production`: **force** to `true` regardless of raw value (production has no legitimate colleague-style principal)
     3. Otherwise: use raw value
     - The effective value is what gates broker AccessDenied handling below. On broker AccessDenied:
     - `SSM_REQUIRE_BROKER_TIER=true` → raise (means app principal's broker policy is misconfigured)
     - `SSM_REQUIRE_BROKER_TIER=false` → log INFO and continue (intentional colleague scope)
   - Map param name → env var; respect precedence rules
2. Add `tests/test_bootstrap_env_ssm.py` using `moto[ssm,kms]`:
   - Successful happy-path (params → `os.environ`)
   - Dev precedence: `.env` wins; prod precedence: SSM wins
   - Throttling retry succeeds
   - Empty path returns gracefully
   - Required secret missing in prod → raises
   - **Pagination** (Codex R3 P2 #1): shared tier has 11 params; force `MaxResults=5` and verify paginator handles correctly
   - **Broker AccessDenied + `SSM_REQUIRE_BROKER_TIER=true`** → raises
   - **Broker AccessDenied + `SSM_REQUIRE_BROKER_TIER=false`** → logs INFO, continues
   - **Shared AccessDenied** → always raises (no flag overrides this)
   - Required secret missing in dev → logs warning (no raise)
   - Stdout-silence holds during SSM path too
3. Create IAM policy `risk-module-ssm-read-dev-shared` (JSON in §"IAM design"). Attach to `plaid-access-token-service`. **AWS Console action.**
4. Create IAM policy `risk-module-ssm-read-dev-broker`. Attach to `plaid-access-token-service`. **AWS Console action.**
5. **Verify gate:** moto tests pass. From local Python REPL with `USE_SSM_SECRETS=true`, `bootstrap_env.bootstrap()` reads existing dev test params (or returns empty if none — fine for this gate).

### Phase 3 — Provision dev SSM + dev cutover
**Scope items:** §S5, §S9, §S10, §S11, §S12, §S13, §S25 (skeleton)

0. **Architecture doc skeleton (moved from Phase 7 per Codex R2 P1 #6).** Create `docs/deployment/SSM_APP_SECRETS_ARCHITECTURE.md` with section headers + placeholder content. As Phase 3 executes, fill in: 1Password backup item ID (step 3), provisioner attach/detach timestamps (steps 2 & 10), final IAM policy ARNs, CloudTrail event IDs from the cutover. By end of Phase 7 the skeleton is fully populated; this avoids the v2 problem where Phase 3 needed a place to record traceability data that didn't exist yet.

1. Write `scripts/provision_ssm_params.py`:
   - Takes `--env {dev,prod}`, `--tier {shared,broker}`, `--input-file <path>`
   - Reads `<KEY>=<value>` lines from input file
   - Validates: regex `^[A-Z_][A-Z0-9_]*$` for env-var name; length ≤ 4096 bytes for value
   - `put_parameter(Name=..., Value=..., Type="SecureString", KeyId=alias/risk-module-credentials-<env>, Overwrite=True, Tier="Standard")`
   - Logs `created|updated|unchanged` per entry
   - `--dry-run` mode prints planned writes
   - Uses provisioner profile (`AWS_PROFILE=finance-web-deploy`) not the app's IAM user
2. **§S9 — Attach temporary write policy.** Create `risk-module-ssm-write-dev` (JSON in §"IAM design") and attach to `finance-web-deploy`. Detach in step 10 below (Codex R2 P2 #1 typo fix).
3. **§S12 — Pre-cutover backup (CRITICAL — do not skip):**
   - In 1Password, create a sealed item `risk_module dev .env pre-SSM backup (2026-MM-DD)`
   - Copy the 17 migration values from current `.env` into that item
   - **Restore drill (upgraded from v2 per Codex R2 P1 #4, refined R3 P1 #5):** export the 1Password values back to a scratch file (`umask 077 && /tmp/.env.restore.test`). The exact 17-key regex (NO placeholders):
     ```
     ^(OPENAI_API_KEY|FMP_API_KEY|EDGAR_API_KEY|GOOGLE_CLIENT_ID|GOOGLE_CLIENT_SECRET|GATEWAY_API_KEY|GATEWAY_RESOLVER_HMAC_KEY|AGENT_API_USER_CLAIM_HMAC_KEY|AGENT_API_KEY|ADMIN_TOKEN|FLASK_SECRET_KEY|PLAID_CLIENT_ID|PLAID_SECRET|SNAPTRADE_CLIENT_ID|SNAPTRADE_CONSUMER_KEY|SCHWAB_APP_KEY|SCHWAB_APP_SECRET)=
     ```
     - `diff <(grep -E '<regex>' .env | sort) <(sort /tmp/.env.restore.test)` — must show zero diff
     - Hash each value with a portable helper (Codex R4 P1 #6 — must work on macOS dev AND Linux EC2 prod):
       ```bash
       hash_cmd() { command -v shasum >/dev/null && shasum -a 256 || sha256sum; }
       cat /tmp/.env.restore.test | hash_cmd
       ```
     - Compare hashes using a concrete Python helper (Codex R4 P2 #1 — no ellipsis):
       ```bash
       python3 - <<'PY'
       import hashlib, os
       from dotenv import dotenv_values
       restored = dotenv_values("/tmp/.env.restore.test")
       live = dotenv_values(".env")
       keys = ["OPENAI_API_KEY","FMP_API_KEY","EDGAR_API_KEY","GOOGLE_CLIENT_ID","GOOGLE_CLIENT_SECRET","GATEWAY_API_KEY","GATEWAY_RESOLVER_HMAC_KEY","AGENT_API_USER_CLAIM_HMAC_KEY","AGENT_API_KEY","ADMIN_TOKEN","FLASK_SECRET_KEY","PLAID_CLIENT_ID","PLAID_SECRET","SNAPTRADE_CLIENT_ID","SNAPTRADE_CONSUMER_KEY","SCHWAB_APP_KEY","SCHWAB_APP_SECRET"]
       for k in keys:
           r = hashlib.sha256((restored.get(k) or "").encode()).hexdigest()[:12]
           l = hashlib.sha256((live.get(k) or "").encode()).hexdigest()[:12]
           assert r == l, f"MISMATCH {k}: live={l} restored={r}"
       print("All 17 keys round-trip OK")
       PY
       ```
     - Delete `/tmp/.env.restore.test` after
   - Document the 1Password item ID in `docs/deployment/SSM_APP_SECRETS_ARCHITECTURE.md` (arch doc skeleton created in Phase 3 step 0 — moved earlier per Codex R2 P1 #6)
4. **§S10/§S11 — Provision dev SSM:**
   - `umask 077 && TMP=$(mktemp -t ssm-dev-shared)` — umask BEFORE mktemp so the file is created mode 600 (Codex R2 P2 #2)
   - Hand-curate `$TMP` from current `.env` (11 shared keys)
   - `python3 scripts/provision_ssm_params.py --env dev --tier shared --input-file "$TMP" --dry-run`
   - Review, then run without `--dry-run`
   - `rm "$TMP"` (don't claim secure erase on APFS — the 1Password backup is the canonical store now anyway)
   - Repeat for broker tier (6 keys, separate temp file)
   - Verify in AWS Console: 11 shared + 6 broker SecureStrings under `/risk-module/dev/`
5. Set `USE_SSM_SECRETS=true` in `.env`
6. Restart all dev services (`service_restart` for backend, celery workers, beat, MCP servers — user action)
7. Smoke test:
   - Backend `/health` returns OK
   - Scenario tools complete a full run (uses OPENAI_API_KEY, FMP_API_KEY from SSM shared)
   - Plaid holdings refresh works (PLAID_* from SSM broker)
   - SnapTrade account list works (SNAPTRADE_* from SSM broker)
   - Schwab connect works (SCHWAB_* from SSM broker)
   - Anthropic chat works (uses ANTHROPIC_AUTH_TOKEN from .env personal)
   - Gateway proxy round-trip works (GATEWAY_API_KEY from SSM shared)
8. Remove migrated keys from `.env` (17 lines deleted locally — `.env` is gitignored, this is local file cleanup, not a git commit). Keep infra + bootstrap + personal.
9. Restart services. Re-run smoke step 7.
10. **§S9 cleanup:** Detach `risk-module-ssm-write-dev` from `finance-web-deploy`. Provisioning is one-shot; future updates use the recipe in §"Future parameter updates" below.
11. **Verify gate:** Full smoke pass + CloudTrail shows `GetParametersByPath` calls from the app principal + zero `PutParameter` events post-detach. **Plus Celery fork gate** (Codex R2 P1 #3, corrected R3 P1 #4 to not leak values): start a celery worker, queue a task that computes `hashlib.sha256(os.environ.get("FMP_API_KEY","").encode()).hexdigest()[:12]` and returns. Compare to the same hash computed in the parent. Match = hydration propagated to forked child. **Never print or return the secret value itself.** Document: secret changes require worker restart.

### Phase 4 — Colleague enablement
**Scope items:** §S14, §S15, §S16

(Reordered before prod cutover per Codex P1 #5: bake the pattern with two dev users before touching prod.)

1. **AWS Console:** create IAM user `dev-<colleague-name>` (no console password; programmatic access only).
2. Create IAM policy `risk-module-ssm-read-dev-shared-readonly` (JSON in §"IAM design" — same as `risk-module-ssm-read-dev-shared` but explicitly read-only, NO broker tier). Attach to the new user.
3. **§S15 — Amend CMK key policy** to add the colleague IAM user as a principal allowed `kms:Decrypt` with `kms:ViaService: ssm.us-east-1.amazonaws.com` condition. The existing key policy grants `plaid-access-token-service` and `finance-web-deploy`; we add the colleague user. Use AWS Console → KMS → key → Key policy → edit.
4. Generate access keys; deliver to colleague via 1Password share (NOT email/Slack).
5. Write `.env.colleague.template` — has every non-secret key (infra, ports, feature flags, KMS ARN, `USE_SSM_SECRETS=true`, `ENVIRONMENT=development`, **`SSM_REQUIRE_BROKER_TIER=false`** per Codex R4 P0 #2) plus `# REPLACE THIS` placeholders for: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `RISK_MODULE_USER_EMAIL`, `DEV_AUTH_EMAIL`, `ANTHROPIC_AUTH_TOKEN` (colleague generates his own via `claude /login`). No broker-tier keys at all.
6. Write `docs/setup/COLLABORATOR_SETUP.md`:
   - Clone repo
   - `cp .env.colleague.template .env`
   - Edit `.env` with personal values + AWS creds
   - `python3 scripts/health_check.py` — should pass
   - `make dev` — backend starts; SSM hydration logs to stderr show 11 shared keys hydrated; broker call returns AccessDenied (logged as INFO; non-fatal)
   - **Expected limitation (corrected from v2 — Codex R2 P1 #1):** broker integrations DO NOT fail-soft cleanly. With empty `PLAID_CLIENT_ID`/`SECRET`, `brokerage-connect/brokerage/plaid/client.py:73-75` returns `None` and `_require_plaid_client()` raises `RuntimeError("Plaid client unavailable")` — `routes/plaid.py:797-799` turns this into HTTP 500. SnapTrade returns 503 "SnapTrade service unavailable" at `routes/snaptrade.py:779-781`. Schwab behaves similarly. **The colleague's frontend will see 500/503 errors when he tries broker actions.** This is honest behavior under his IAM scope; improving the UX (graceful "credentials unavailable" banner) is out of scope for this plan — filed as a follow-up. The doc must explicitly warn him.
7. **Verify gate:** Colleague runs the doc end-to-end on his machine. He successfully boots backend + runs one scenario tool. He attempts a Plaid action and gets a 500 error (Plaid) or 503 (SnapTrade) — expected behavior under his IAM scope per step 6 above. Doc must warn him about this explicitly. **Plus verify no broker params leaked into his process** (Codex R3 P2 #3, refined R4 P1 #5 — exact names only + platform-portable):
- macOS: `ps -E -p <backend-pid> | tr ' ' '\n' | grep -E '^(PLAID_CLIENT_ID|PLAID_SECRET|SNAPTRADE_CLIENT_ID|SNAPTRADE_CONSUMER_KEY|SCHWAB_APP_KEY|SCHWAB_APP_SECRET)='` returns empty
- Linux EC2: `cat /proc/<backend-pid>/environ | tr '\0' '\n' | grep -E '^(PLAID_CLIENT_ID|PLAID_SECRET|SNAPTRADE_CLIENT_ID|SNAPTRADE_CONSUMER_KEY|SCHWAB_APP_KEY|SCHWAB_APP_SECRET)='` returns empty (Codex R5 P1 #1 — spelled out, no ellipsis)
- Both must use EXACT secret names (not `PLAID*`) so non-secret vars like `PLAID_ENV`, `SNAPTRADE_ENVIRONMENT`, `SCHWAB_ENABLED` don't false-positive.
- **Ownership note (Codex R5 P1 #2):** `ps -E` and `/proc/<pid>/environ` require running as the process owner (or root). Document that the colleague must run this check as the same user that launched the backend process. If the check returns "Permission denied," the verify gate cannot be completed via this command — fall back to inspecting bootstrap stderr logs (which should show 11 hydrated, 0 broker hydrated when `SSM_REQUIRE_BROKER_TIER=false`).

### Phase 5 — Provision prod SSM + prod cutover
**Scope items:** §S17, §S18, §S19, §S20

Same shape as Phase 3 but on prod EC2 (`3.139.124.134`). Critical differences:
- `ENVIRONMENT=production` means SSM wins over `.env`
- Required-secret validation enforced (missing required key in prod → app raises)
- Smoke test against the live prod URL
- Pre-cutover backup goes in a different 1Password item (`risk_module prod .env pre-SSM backup`)

Steps:
1. Create IAM policies `risk-module-ssm-read-prod-shared` and `risk-module-ssm-read-prod-broker` (same structure as dev versions, scoped to prod ARN/CMK). Attach to `plaid-access-token-service`.
2. Pre-cutover backup of prod `.env` to 1Password (§S18). Restore drill from a fresh shell on the EC2.
3. Provision prod SSM (§S19): same script, `--env prod`, two tiers.
4. SSH to prod EC2, edit `.env` to set `USE_SSM_SECRETS=true`.
5. Restart prod services.
6. Smoke test against live prod URL.
7. Remove the 17 migrated keys from prod `.env`.
8. Restart. Re-smoke. CloudTrail confirms reads.
9. **Verify gate:** Prod smoke pass + CloudTrail + zero new errors in prod logs for 1 hour post-cutover.

### Phase 6 — AI-excel-addin design notes + risk_module .env cleanup
**Scope items:** §S21, §S22, §S23, §S24

1. Write `AI-excel-addin/.env.example` based on the live `.env` (all keys present, all values placeholdered).
2. Write `risk_module/docs/setup/CROSS_REPO_WIRING.md`:
   - `EXCEL_MCP_SECRET` must match between both repos' `.env` (lives in AI-excel-addin, not risk_module — risk_module's `.env` should remove it)
   - `GATEWAY_API_KEY_{EXCEL,CLI,TELEGRAM,WEB,MCP}` issued by AI-excel-addin (`api/main.py:361-365`), risk_module only reads `GATEWAY_API_KEY` (single value)
   - `RISK_API_KEY` (AI-excel-addin) ↔ `AGENT_API_KEY` (risk_module) — must match
   - `RISK_API_URL` (AI-excel-addin) points to risk_module backend
   - Note: when AI-excel-addin migrates to SSM (future plan), each repo keeps its own SSM tree with matching values; not "shared SSM key."
3. Delete `AI-excel-addin/.env.bak` (vestigial).
4. **§S24 — Remove from risk_module `.env` (CORRECTED in v3):** `GOOGLE_API_KEY`, `BRAVE_API_KEY`, `OPENAI_EMBEDDING_KEY`, `EXCEL_MCP_SECRET`, `GATEWAY_API_KEY_{EXCEL,TELEGRAM,WEB,MCP,CLI}`. Verified via grep that risk_module Python does not read these. **`CHAT_API_KEY` is NOT removed** — it intentionally lives in `risk_module/.env` per the shipped `docs/planning/completed/GATEWAY_CLI_CHANNEL_WIRING_PLAN.md` (line 114): the TUI launches via `set -a; source /path/to/risk_module/.env; set +a` and sources `CHAT_API_KEY` from there. risk_module's Python doesn't read it but the operator's shell uses it to bootstrap the TUI process. v2 incorrectly listed it for removal; v3 corrects.
5. File the follow-up: `docs/planning/SSM_AI_EXCEL_ADDIN_MIGRATION_PLAN.md` — empty template.

### Phase 7 — Architecture doc finalization + memory index
**Scope items:** §S25 (finalize — skeleton created in Phase 3)

1. Finalize `docs/deployment/SSM_APP_SECRETS_ARCHITECTURE.md` — the post-migration arch doc (sibling to `CREDENTIALS_KMS_ARCHITECTURE.md`). Skeleton created in Phase 3 step 0; by now it should have: what's in SSM (per tier), namespace, IAM (link to policy JSON), KMS encryption context behavior, failure modes, audit trail, 1Password backup item references, related docs, **§"Future parameter updates" recipe** (see below).
2. **Future parameter updates recipe** — append to the architecture doc. Cover both ADD and ROTATE (Codex R3 P1 #6):
   - **Adding a new param:**
     - Re-attach `risk-module-ssm-write-<env>` to `finance-web-deploy`
     - `python3 scripts/provision_ssm_params.py --env <env> --tier <shared|broker> --input-file <new-key.env>` (file with single `KEY=value` line, `umask 077` first)
     - Detach the write policy
     - Restart services that read the new key (`service_restart` per service)
     - Verify in CloudTrail
   - **Rotating an existing param:**
     - Generate new value at the third-party provider (OpenAI/FMP/etc.) — keep old credential active during overlap
     - Re-attach `risk-module-ssm-write-<env>`
     - Same provisioning command — `put_parameter --overwrite` updates atomically
     - Detach write policy
     - Restart services
     - Verify new value via CloudTrail + smoke test
     - Revoke old credential at provider once smoke confirms new value works
   - **Why explicit recipe:** "I can re-attach" is not enough for a security runbook. The attach → write → detach → verify pattern must be checked-in procedure for both add and rotate operations.
3. **Update `scripts/register_claude_mcp.sh`** (Codex R5 P1 #4, refined R6 P1 #4) — post-migration, FMP MCP server hydrates `FMP_API_KEY` from SSM via `bootstrap_env`. Specific edits:
   - Remove the `FMP_API_KEY` required check at `scripts/register_claude_mcp.sh:24-27`
   - Remove the `-e FMP_API_KEY=...` injection at `scripts/register_claude_mcp.sh:49`
   - The MCP server hydrates from SSM on each invocation; no shell-env passthrough needed.
4. Update `MEMORY.md` index entry pointing to the architecture doc.
5. **Create empty follow-up plan templates** (Codex R6 P2 #1): write `docs/planning/SSM_AI_EXCEL_ADDIN_MIGRATION_PLAN.md` and `docs/planning/SSM_VALS_HARNESS_MIGRATION_PLAN.md` as empty templates (just title + status + motivation placeholder). Avoids dangling cross-references from this plan.
6. **Resolve `fmp/scripts/snapshot_estimates.py` deprecation** (Codex R6 new finding #3): determine status — if truly unused for >6 months, delete; if still runnable, add to entry-point table; if not runnable, add a deprecation header comment.

**Out of scope (named explicitly per Codex R5 P1 #6):** the Vals benchmark harness in `evals/vals-finance-agent/` still requires `OPENAI_API_KEY` / `FMP_API_KEY` from shell env (its bash scripts source `.env` directly, similar to TUI's `set -a` pattern). The evaluation harness is operator-launched, not a production code path, and the operator runs it from a fully-configured dev machine. Migrating it would require its own bootstrap mechanism (bash, not Python). Phase 7 step 5 creates the empty follow-up plan template (Codex R6 P2 #1 — file actually written, not just referenced).

**Also out of scope (Codex R6 new findings #1-3):**
- `scripts/macro_chartbook.py` + `scripts/chartbook/data_fetcher.py` — FMP-consuming CLI, but the chartbook is a personal analytics tool, not production. Scope-out with note in the architecture doc.
- `scripts/corpus_phase3_delta_transcripts.py` — actually a duplicate of v6's `corpus_phase3_bulk_ingest_transcripts.py`? Verify during Phase 1 entry-point sweep — if different file, add to entry-point table.
- `fmp/scripts/snapshot_estimates.py` — deprecated script. Phase 7 verifies status: either delete (if truly unused), bootstrap (if still runnable), or document deprecation.

## IAM design (rewritten — addresses Codex R1 P0 #1, P0 #2, P0 #10)

### Critical correction from v1

**v1 was wrong**: I used `kms:EncryptionContext:app` and `kms:EncryptionContext:env` conditions in IAM. SSM SecureStrings do NOT let callers supply custom KMS encryption context — SSM internally uses `{"PARAMETER_ARN": "<full-arn>"}`. The v1 policy would have blocked all SSM decrypts.

**v2 fix**: use `kms:ViaService: ssm.<region>.amazonaws.com` to constrain decryption to SSM service calls, plus `kms:EncryptionContext:PARAMETER_ARN` matched against the parameter ARN pattern.

### Policy: `risk-module-ssm-read-dev-shared` (app — attached to `plaid-access-token-service`)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadDevSharedSecrets",
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
      "Resource": "arn:aws:ssm:us-east-1:<account>:parameter/risk-module/dev/shared/*"
    },
    {
      "Sid": "DecryptDevSharedViaSSM",
      "Effect": "Allow",
      "Action": ["kms:Decrypt"],
      "Resource": "arn:aws:kms:us-east-1:<account>:key/863b8f34-c275-4b05-9095-c7df7d740cc7",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "ssm.us-east-1.amazonaws.com"
        },
        "StringLike": {
          "kms:EncryptionContext:PARAMETER_ARN": "arn:aws:ssm:us-east-1:<account>:parameter/risk-module/dev/shared/*"
        }
      }
    }
  ]
}
```

### Policy: `risk-module-ssm-read-dev-broker` (app — attached to `plaid-access-token-service`)
Same as above with `shared` → `broker` in both the SSM resource ARN and the KMS `PARAMETER_ARN` condition.

### Policy: `risk-module-ssm-read-dev-shared-readonly` (colleague IAM user)
Identical to `risk-module-ssm-read-dev-shared`. Same paths, same KMS condition. Naming uses `-readonly` suffix because we're explicit about intent — the IAM action list contains no write actions. The colleague has NO broker policy.

### Policy: `risk-module-ssm-write-dev` (temporary provisioner — attached to `finance-web-deploy`)
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "WriteDevSecrets",
      "Effect": "Allow",
      "Action": ["ssm:PutParameter", "ssm:DeleteParameter", "ssm:GetParameter"],
      "Resource": "arn:aws:ssm:us-east-1:<account>:parameter/risk-module/dev/*"
    },
    {
      "Sid": "EncryptDecryptDevViaSSM",
      "Effect": "Allow",
      "Action": ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"],
      "Resource": "arn:aws:kms:us-east-1:<account>:key/863b8f34-c275-4b05-9095-c7df7d740cc7",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "ssm.us-east-1.amazonaws.com"
        },
        "StringLike": {
          "kms:EncryptionContext:PARAMETER_ARN": "arn:aws:ssm:us-east-1:<account>:parameter/risk-module/dev/*"
        }
      }
    }
  ]
}
```

**Attach during Phase 3 step 2, detach during Phase 3 step 10.** Prod equivalent attached/detached during Phase 5.

### Prod policies
Same as dev with `dev` → `prod` and CMK ID `863b8f34-...` → `947dd55e-...`.

### CMK key policy amendment (Phase 4 §S15)

The CMK key policy (separate from IAM identity policies — KMS has resource policies too) currently grants:
- `plaid-access-token-service` (the IAM user the app authenticates as)
- `finance-web-deploy` (admin/CLI user)

Phase 4 adds a third principal:
```json
{
  "Sid": "AllowColleagueDecryptViaSSM",
  "Effect": "Allow",
  "Principal": {
    "AWS": "arn:aws:iam::<account>:user/dev-<colleague-name>"
  },
  "Action": "kms:Decrypt",
  "Resource": "*",
  "Condition": {
    "StringEquals": {
      "kms:ViaService": "ssm.us-east-1.amazonaws.com"
    },
    "StringLike": {
      "kms:EncryptionContext:PARAMETER_ARN": "arn:aws:ssm:us-east-1:<account>:parameter/risk-module/dev/shared/*"
    }
  }
}
```

Without this amendment, IAM identity policy alone is insufficient — KMS double-gates via key policy + IAM. This is the bug Codex caught (P0 #2).

## Migration runbook (mirrors `CREDENTIALS_KMS_ARCHITECTURE.md` style)

Run for dev first (Phase 3), then prod (Phase 5). Identical shape:

1. Verify CMK alias resolves: `aws kms describe-key --key-id alias/risk-module-credentials-<env>`
2. Verify app IAM policies attached: `aws iam list-attached-user-policies --user-name plaid-access-token-service`
3. Attach temporary write policy `risk-module-ssm-write-<env>` to `finance-web-deploy`
4. **Pre-cutover backup**: create sealed 1Password item with all 17 migration values; do a restore drill from a fresh terminal
5. Smoke-test SSM round-trip: `aws ssm put-parameter --name /risk-module/<env>/shared/test --value foo --type SecureString --key-id alias/... --overwrite && aws ssm get-parameter --name /risk-module/<env>/shared/test --with-decryption && aws ssm delete-parameter --name /risk-module/<env>/shared/test`
6. Stop backend + workers + beat
7. Provision shared tier:
   - `umask 077 && TMP=$(mktemp -t ssm-<env>-shared)`
   - Hand-curate `$TMP` with 11 KEY=value lines for shared tier
   - `python3 scripts/provision_ssm_params.py --env <env> --tier shared --input-file "$TMP" --dry-run` — review
   - Same without `--dry-run` — execute
   - `rm "$TMP"`
8. Provision broker tier: same shape, 6 keys.
9. AWS Console: verify 17 SecureStrings present.
10. Set `USE_SSM_SECRETS=true` in `.env`
11. Start backend + workers + beat
12. Smoke-test end-to-end (Phase 3 step 7 list)
13. Verify CloudTrail event `GetParametersByPath` from the app principal at expected timestamp
14. Remove the 17 migrated keys from `.env` (local file edit; `.env` is gitignored — this is filesystem cleanup, not a git commit)
15. Restart, re-smoke
16. Detach `risk-module-ssm-write-<env>` from `finance-web-deploy`

## Test plan

### CI guard — entry-point coverage test (v6, strengthened v7 per Codex R6 P1 #1-3)

`tests/test_bootstrap_entry_point_coverage.py` — defensive test that fails when a NEW file reads an SSM-migrated env var (directly or via known SSM-consuming clients) without importing `bootstrap_env`. Solves the recurring "missing entry-point" pattern across R3/R4/R5.

**v7 strengthening (Codex R6 P1 #1):** detect not just module-top `os.getenv("FMP_API_KEY")` literal reads, but also imports of known SSM-consuming clients (`FMPClient`, `core.corpus.edgar_api_client`, `fmp.client`, `fmp.estimates_client`, `brokerage-connect.brokerage.*`) at module top. A CLI that calls `FMPClient()` without containing the literal `"FMP_API_KEY"` still needs bootstrap.

**v7 (Codex R6 P1 #2):** use `git ls-files '*.py'` instead of `Path.rglob('*.py')` — `rglob` scans `.claude/worktrees/`, `.ipynb_checkpoints/`, vendored `.venv/`, `evals/.../vendor/finance-agent/.venv/`, etc. and produces false positives.

**v7 (Codex R6 P1 #3):** detect both `import bootstrap_env` AND `from bootstrap_env import bootstrap` (the AST walk handles `Import` and `ImportFrom` node types).

```python
# tests/test_bootstrap_entry_point_coverage.py
"""
Guard against adding entry points that read SSM-migrated secrets without bootstrap_env.

Each Codex review round found 1-4 new scripts that read SSM-migrated env vars
at module load without `bootstrap_env` import. After cutover, those scripts
would silently boot with empty values. This test enforces the pattern.
"""
import ast
from pathlib import Path

SSM_MIGRATED_SECRETS = {
    "OPENAI_API_KEY", "FMP_API_KEY", "EDGAR_API_KEY",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
    "GATEWAY_API_KEY", "GATEWAY_RESOLVER_HMAC_KEY",
    "AGENT_API_USER_CLAIM_HMAC_KEY", "AGENT_API_KEY",
    "ADMIN_TOKEN", "FLASK_SECRET_KEY",
    "PLAID_CLIENT_ID", "PLAID_SECRET",
    "SNAPTRADE_CLIENT_ID", "SNAPTRADE_CONSUMER_KEY",
    "SCHWAB_APP_KEY", "SCHWAB_APP_SECRET",
}

# Indirect-import detection: modules that read SSM secrets internally.
# If an entry-point file imports any of these, it MUST bootstrap.
SSM_CONSUMING_MODULES = {
    "fmp.client", "fmp.estimates_client",
    "core.corpus.edgar_api_client",
    "providers.completion",
    "brokerage.plaid", "brokerage.snaptrade", "brokerage.schwab",
    "brokerage.config",
}

# Allowlist: files that read SSM secrets but are libraries (not entry points)
# — they get hydration via their importing entry point.
LIBRARY_ALLOWLIST = {
    "providers/completion.py", "fmp/client.py", "fmp/estimates_client.py",
    "fmp/fx.py", "core/corpus/edgar_api_client.py",
    "app_platform/middleware/sessions.py", "app_platform/gateway/proxy.py",
    "portfolio_risk_engine/config.py",  # Codex R6 P1 #2
    "routes/", "services/", "brokerage-connect/",
    "tests/", "evals/",
}

def test_entry_points_import_bootstrap_env():
    """Find files that read SSM secrets at module top OR import SSM-consuming
    modules at module top, assert each imports bootstrap_env."""
    import subprocess
    repo = Path(__file__).resolve().parent.parent
    # v7 (Codex R6 P1 #2): use git ls-files to skip .venv/.claude/.ipynb_checkpoints/etc
    py_files = subprocess.check_output(
        ["git", "ls-files", "*.py"], cwd=repo, text=True
    ).splitlines()
    violations = []
    for rel in py_files:
        if any(rel.startswith(p) for p in LIBRARY_ALLOWLIST): continue
        py = repo / rel
        tree = ast.parse(py.read_text())
        reads_ssm = _walks_module_top_for_secret_read(tree, SSM_MIGRATED_SECRETS)
        imports_ssm_consumer = _walks_module_top_for_import(tree, SSM_CONSUMING_MODULES)
        if not (reads_ssm or imports_ssm_consumer): continue
        # v7 (Codex R6 P1 #3): detect both Import and ImportFrom
        has_bootstrap = any(
            (isinstance(n, ast.Import) and any(a.name == "bootstrap_env" for a in n.names))
            or (isinstance(n, ast.ImportFrom) and n.module == "bootstrap_env")
            for n in ast.walk(tree)
        )
        if not has_bootstrap:
            violations.append(rel)
    assert not violations, f"Entry points missing bootstrap_env: {violations}"
```

This test runs in CI; any new entry point that reads an SSM key without `bootstrap_env` import fails the build. Future Codex reviews (and human reviews) no longer need to manually enumerate.

### Unit (`tests/test_bootstrap_env.py`)
- `bootstrap()` is idempotent
- `.env` load happens
- `USE_SSM_SECRETS=false` short-circuits SSM
- `USE_SSM_SECRETS` unset + `ENVIRONMENT=production` → defaults true
- `USE_SSM_SECRETS` unset + `ENVIRONMENT=development` → defaults false
- `_param_to_env()` regex validation rejects bad names
- `_param_to_env()` round-trip bijective on known param list
- **Stdout-silence assertion**: `bootstrap()` never writes to `sys.stdout`

### Unit (`tests/test_bootstrap_env_ssm.py`, moto[ssm,kms])
- Happy path: params → `os.environ`
- Dev precedence: `.env` value wins over SSM value
- Prod precedence: SSM value wins over `.env` value
- Throttling → retry succeeds
- Empty namespace → no-op
- Required secret missing in prod (via `bootstrap(required=[...])`) → raises `RuntimeError`
- Required secret missing in dev → logs warning (no raise)
- Stdout-silence holds during SSM path
- **Pagination** (sync with Phase 2 step 2, Codex R4 P2 #2): 11 shared params with `MaxResults=5` → paginator collects all
- **Broker AccessDenied + `SSM_REQUIRE_BROKER_TIER=true`** → raises
- **Broker AccessDenied + `SSM_REQUIRE_BROKER_TIER=false`** → logs INFO, continues
- **`ENVIRONMENT=production` + `SSM_REQUIRE_BROKER_TIER=false` set in env** → forced to `true`, broker AccessDenied still raises
- **Shared AccessDenied** → always raises (no flag overrides)

### Integration (`tests/integration/test_bootstrap_env_live.py`, marked `slow`, off by default)
- Real dev SSM: provision one throwaway param, call `bootstrap()`, assert env populated, delete param
- Wrong IAM (revoke policy temporarily) → boto3 raises `AccessDenied`

### Smoke (manual, in runbook)
- Full app boot, MCP servers respond to JSON-RPC, scenario tool round-trip, Plaid/SnapTrade/Schwab/Anthropic round-trips, gateway proxy round-trip

## Rollback plan

**Phase 1–2 rollback:** revert `bootstrap_env` imports in entry points. No AWS state to clean up.

**Phase 3+ rollback (dev or prod):**
- Set `USE_SSM_SECRETS=false` in `.env`
- Restore the 17 migrated keys to `.env` **from the pre-cutover 1Password backup** (NOT from SSM — backup is the canonical pre-migration store)
- Restart services
- SSM params remain in place (non-destructive)
- Re-attempt forward when ready

**Worst case (SSM region outage):**
- Symptom: `bootstrap()` raises in prod (required-secret missing)
- Action: SSH to prod, set `USE_SSM_SECRETS=false`, hand-populate the 17 keys back into `.env` from 1Password backup
- Restart
- Re-enable when SSM recovers

**Colleague IAM compromise — INCIDENT RESPONSE (corrected from v1):**

The compromise vector is that SSM decrypts plaintext into `os.environ` on the colleague's running process; that plaintext can be cached, logged, or exfiltrated. IAM revocation blocks FUTURE reads but does not rescue past plaintext.

Procedure:
1. Detach `risk-module-ssm-read-dev-shared-readonly` from the colleague's IAM user → blocks further reads
2. Delete the colleague's AWS access keys
3. Remove the colleague's principal from the CMK key policy
4. Review CloudTrail for the colleague's `GetParametersByPath` history — for audit / scope assessment only, NOT to scope rotation (per Codex R2 P1 #5)
5. **Rotate every dev shared secret returned by the colleague's read path — all 11**, not just those CloudTrail logs identified. CloudTrail records the `GetParametersByPath` call but not the individual parameter values returned; conservative assumption is that the colleague's process had all 11 shared values in `os.environ`. Rotation procedure (Codex R3 P1 #7 — explicit write-policy attach/detach):
   - **Re-attach `risk-module-ssm-write-dev`** to `finance-web-deploy` (write policy was detached after Phase 3 cutover)
   - For each of the 11 shared params:
     - Generate new value at the third-party provider (OpenAI/FMP/EDGAR/Google/etc.)
     - `aws ssm put-parameter --name /risk-module/dev/shared/<name> --value <new> --overwrite --type SecureString --key-id alias/risk-module-credentials-dev`
   - **Detach `risk-module-ssm-write-dev`**
   - Restart all dev services
   - Verify via smoke + CloudTrail
   - Revoke old credentials at each provider
6. Broker tier (Plaid/SnapTrade/Schwab) is unaffected — colleague's policy blocks it by design. Skip rotation of broker secrets unless other evidence suggests broader compromise.

## Open questions

1. **`ANTHROPIC_API_KEY` deprecation.** Per memory, OAuth-only is the rule. `ANTHROPIC_API_KEY` exists in `.env` but `providers/completion.py:403` is the only runtime read site. Open: should a follow-up plan remove the code path entirely? Out of scope for THIS plan.
2. **Per-developer OpenAI keys.** Currently shared dev OpenAI key. Open: would per-user OpenAI keys (each developer has their own under `/risk-module/dev/users/<email>/openai-api-key`) be worth the IAM complexity? Defer to follow-up if cost-tracking ever becomes a concern; not gating this plan.
3. **EC2 instance role.** When prod migrates from long-lived `AWS_ACCESS_KEY_ID` to an instance role (separate plan), Phase 5's policies reattach to the instance role principal instead of the IAM user. Verify zero-change at that time.

## Decisions log

- **2026-05-11 (v1)** — Plan v1 drafted. Scoping confirmed with user: (A) dev `.env`-wins, prod SSM-wins; (B) dev + prod in same plan, separate phases; (C) EC2 instance role out of scope. AI-excel-addin SSM out of scope (path B). Boot pattern is "import bootstrap_env first," not refactor.
- **2026-05-11 (v2 — Codex R1 FAIL)** — Codex returned FAIL with 10 P0 / 9 P1 / 4 P2 findings. v2 changes:
  - **Two-tier namespace** (`shared/` + `broker/`) — user chose Option C from R1 P0 #6 (low-stakes shared with colleague, high-stakes app-only). Cleaner than registering sandbox apps, cleaner than accepting prod exposure to colleague.
  - **IAM KMS condition fixed** — replaced `kms:EncryptionContext:app/env` (wrong for SSM) with `kms:ViaService: ssm.<region>.amazonaws.com` + `kms:EncryptionContext:PARAMETER_ARN`.
  - **CMK key policy amendment** added to Phase 4 (was missing in v1).
  - **Entry-point inventory expanded** — added `fmp/server.py`, `workers/beat_schedule.py`, `app_platform/api_budget/__main__.py`.
  - **Stdout-silence guarantee** for `bootstrap_env` to protect MCP JSON-RPC.
  - **Inventory pruned** — removed 8 over-grants (verified via grep). Total moving keys: 25 → 17.
  - **Phase reordering** — colleague enablement before prod cutover (was P1 #5).
  - **ADMIN_TOKEN cleanup moved to Phase 1** — was Phase 7 in v1; would have leaked via clone before cleanup.
  - **Pre-cutover 1Password backup** required (was missing rollback-realism in v1).
  - **Compromise IR procedure corrected** — rotation IS required for decrypted plaintexts.
  - **Provisioner identity split** — `finance-web-deploy` gets temporary write policy, detached after cutover. App's read policies don't include write.
  - **Secure temp file** via `mktemp` + `umask 077` + `rm` (not `shred` — unreliable on macOS APFS).
  - **Required-vs-optional secrets** split for fail modes.
  - **`USE_SSM_SECRETS` default** derived from `ENVIRONMENT` when unset.
  - **`moto[kms,ssm]`** in `requirements-dev.txt`.
  - **4 KB SecureString limit** validated in provisioning script.
  - Frontend `VITE_GOOGLE_CLIENT_ID` recognized as build-time, not in SSM scope.
- **2026-05-11 (v3 — Codex R2 FAIL)** — Codex R2 returned FAIL on v2: 2 P0 / 8 P1 / 4 P2 findings. v3 changes:
  - **Bootstrap split into two `GetParametersByPath` calls** (shared + broker separately, AccessDenied on broker non-fatal for colleague). v2's single recursive call against parent path was unsafe per AWS auth semantics (R2 P0 #1).
  - **Entry-point inventory expanded again** — added `scripts/run_plaid.py`, `run_snaptrade.py`, `run_schwab.py`, `run_positions.py`, `run_trading_analysis.py` (R2 P0 #2).
  - **Broker UX claim corrected** — Phase 4 step 6 honest about 500/503 errors on colleague's broker actions; clean UX scoped out (R2 P1 #1).
  - **`REQUIRED_SECRETS` enumerated** in new §"Required vs optional secrets" — `FMP_API_KEY`, `FLASK_SECRET_KEY`, `GATEWAY_API_KEY` are required at prod boot; rest are feature-gated (R2 P1 #2).
  - **Celery fork verify gate** added to Phase 3 verify step (R2 P1 #3).
  - **Restore drill upgraded** to full file-reconstruction + sha256 hash diff, not paste-into-REPL (R2 P1 #4).
  - **Compromise IR rotates ALL 11 shared params**, not just CloudTrail-identified — CloudTrail doesn't enumerate individual parameter values returned by `GetParametersByPath` (R2 P1 #5).
  - **Architecture doc skeleton moved to Phase 3 step 0** (was Phase 7); §S25 now spans both phases (R2 P1 #6).
  - **"Future parameter updates" recipe** added to architecture doc deliverable (R2 P1 #7).
  - **§S24 corrected** — `CHAT_API_KEY` REMOVED from removal list. It intentionally stays in `risk_module/.env` per shipped `GATEWAY_CLI_CHANNEL_WIRING_PLAN.md:114-137` (TUI sources it). Self-discovered while verifying R2 P1 #8; v2 was wrong to remove it.
  - **Provisioner gets `kms:Decrypt`** for idempotent "unchanged" detection (R2 P2 #3).
  - `umask 077` placed BEFORE `mktemp` (R2 P2 #2).
  - Phase 3 step-numbering typo fixed (step 9 → step 10) (R2 P2 #1).
- **2026-05-11 (v4 — Codex R3 FAIL)** — Codex R3 returned FAIL on v3: 3 P0 / 7 P1 / 3 P2. v4 changes:
  - **Phase 2 step 1 corrected** — now matches Architecture spec (two non-recursive `GetParametersByPath` calls, not one recursive). v3 had a Phase 2/Architecture mismatch (R3 P0 #1).
  - **`SSM_REQUIRE_BROKER_TIER` env var added** — disambiguates app-principal broker misconfig (raise) from colleague-intentional scope (warn). Default `true` in `.env`; colleague template sets `false`; prod always `true` (R3 P0 #2).
  - **6 more entry points added** — `scripts/plaid_reauth.py`, `diagnose_plaid_balances.py`, `snaptrade_sdk_smoke.py`, `check_schwab_token.py`, `explore_transactions.py`, `cleanup_stale_data_sources.py` (R3 P0 #3).
  - **Per-entry-point `REQUIRED_SECRETS`** — global table replaced with `bootstrap(required=[...])` kwarg pattern per Codex R3 P1 #2 + #3. Each entry point declares its needs. Code-reality check: bootstrap performs the validation (existing codebase doesn't validate at boot — bootstrap introduces it).
  - **Celery fork gate uses hash check** instead of `env | grep` to avoid leaking values (R3 P1 #4).
  - **Restore drill bulletproofed** — exact 17-key regex spelled out; `shasum -a 256` (BSD) instead of GNU `sha256sum`; Python-via-dotenv instead of bash `source` to handle special characters (R3 P1 #5).
  - **Rotation recipe added** to "Future parameter updates" — both add and rotate paths explicit (R3 P1 #6).
  - **Compromise IR write-policy attach/detach** spelled out (R3 P1 #7).
  - **Phase 4 verify gate honest** — 500/503 expected; success criteria #4 updated to match (R3 P1 #1).
  - **Pagination unit test** added (R3 P2 #1).
  - **Provisioner KMS statement** adds `kms:EncryptionContext:PARAMETER_ARN` for defense-in-depth (R3 P2 #2).
  - **Phase 4 verify** checks no broker params leaked into colleague's process (R3 P2 #3).
- **2026-05-11 (v5 — Codex R4 FAIL)** — Codex R4 returned FAIL on v4: 3 P0 / 6 P1 / 3 P2. v5 changes:
  - **Architecture broker AccessDenied semantics aligned with Phase 2** — Architecture step 4 now says "depends on `SSM_REQUIRE_BROKER_TIER`" matching Phase 2; v4 still had old wording (R4 P0 #1).
  - **`SSM_REQUIRE_BROKER_TIER=false` added to colleague template** Phase 4 step 5 (R4 P0 #2).
  - **4 more entry points** — corpus_phase2_universe_select, corpus_phase3_bulk_ingest_transcripts, backfill_ticker_aliases, benchmark_editorial_arbiter — all read FMP_API_KEY / OPENAI_API_KEY at module load (R4 P0 #3).
  - **Phase 1 `REQUIRED_SECRETS = (...)` constant removed** — replaced with `bootstrap(required=[...])` kwarg (R4 P1 #1).
  - **Broker CLIs explicitly listed in per-entry required table** (R4 P1 #2).
  - **`GOOGLE_CLIENT_SECRET` removed from app.py required list** — assigned but unused beyond app.py:328 (R4 P1 #3).
  - **Production forces `SSM_REQUIRE_BROKER_TIER=true`** regardless of env value — prod has no legitimate colleague-style principal (R4 P1 #4).
  - **Leak-check grep uses exact secret names** + macOS `ps -E` + Linux `/proc/<pid>/environ` (R4 P1 #5).
  - **sha256 portability** — `shasum || sha256sum` shim (R4 P1 #6).
  - **Restore drill concrete Python helper** with full keys list, no ellipsis (R4 P2 #1).
  - **Test plan synced with Phase 2 tests** — pagination, SSM_REQUIRE_BROKER_TIER variants explicitly enumerated in §"Test plan / Unit" (R4 P2 #2).
- **2026-05-11 (v6 — Codex R5 FAIL)** — Codex R5 returned FAIL on v5: 1 P0 / 5 P1 / 1 P2. Narrowest review yet. v6 changes:
  - **4 EDGAR corpus scripts added** to entry-point table — `corpus_phase1_delta_ingest`, `corpus_bulk_reingest`, `corpus_ingest_accession`, and `EDGAR_API_KEY` added to `corpus_phase2_universe_select`'s required list (R5 P0 #1).
  - **CI guard test added** — `tests/test_bootstrap_entry_point_coverage.py` enforces "any file reading SSM-migrated env vars at module top must import bootstrap_env." Architectural fix that eliminates the recurring "1 more script" discovery pattern across R3/R4/R5.
  - **Linux leak grep spelled out** — full 6 broker secret names, no ellipsis (R5 P1 #1).
  - **Leak-check ownership note added** — `ps -E` / `/proc/<pid>/environ` require process-owner privilege; fallback to stderr logs if Permission denied (R5 P1 #2).
  - **RuntimeError shape spec'd** — exact message format with `missing` names (no values), `env`, `ssm_enabled`, `ssm_param_count` for diagnostics (R5 P1 #3).
  - **MCP registration script follow-up** — Phase 7 step 3 updates `scripts/register_claude_mcp.sh` to stop baking `FMP_API_KEY` into Claude MCP config (R5 P1 #4).
  - **`EXPECT_BROKER_TIER` renamed to `SSM_REQUIRE_BROKER_TIER`** for clarity — semantic prefix matches `USE_SSM_SECRETS` (R5 P1 #5).
  - **Vals harness explicitly scoped out** — `evals/vals-finance-agent/` is operator-launched evaluation tooling, not production code. Bash scripts source `.env` directly; migration would require bash-side bootstrap. Filed as follow-up plan (R5 P1 #6).
  - **Prod force algorithm explicit** — Phase 2 step 1 spells out the resolution: read raw → if prod force to true → apply to AccessDenied handling (R5 P2 #1).
- **2026-05-11 (v7 — Codex R6 PASS with hardening)** — Codex R6 returned PASS with 4 P1 + 1 P2 + 3 new-findings as non-blocking hardening. v7 incorporates all of them per the workflow rule "address ALL findings":
  - **CI guard strengthened** — detects indirect imports of SSM-consuming modules (`FMPClient`, `edgar_api_client`, etc.), uses `git ls-files` (skips `.venv`/`.claude/worktrees`/`.ipynb_checkpoints`), detects both `import bootstrap_env` and `from bootstrap_env import bootstrap` (R6 P1 #1-3).
  - **MCP registration edits spelled out** — exact line numbers in `scripts/register_claude_mcp.sh:24-27` and `:49` (R6 P1 #4).
  - **Follow-up plan templates created in Phase 7** — `SSM_AI_EXCEL_ADDIN_MIGRATION_PLAN.md` and `SSM_VALS_HARNESS_MIGRATION_PLAN.md` are real files, not just references (R6 P2 #1).
  - **Macro chartbook scoped out** (personal analytics, non-production) (R6 new finding #1).
  - **`scripts/corpus_phase3_delta_transcripts.py`** noted for Phase 1 entry-point sweep verification (R6 new finding #2 — may be duplicate of `_bulk_ingest_transcripts`).
  - **`fmp/scripts/snapshot_estimates.py` deprecation resolved** in Phase 7 step 6 (R6 new finding #3).

## Success criteria

This migration is complete when:

1. All Phase scope items §S1–§S25 are ✓
2. Dev `.env` reduced from ~70 keys to ~50 keys (17 migrated + 8 AI-excel-addin-only removed)
3. Prod `.env` similarly reduced
4. Colleague has run the onboarding doc end-to-end and successfully booted the app; broker-integration 500/503 errors verified as expected behavior (NOT clean UX — that's a follow-up, see Phase 4 step 6)
5. CloudTrail shows SSM reads from both the app principal (shared + broker) and the colleague's IAM user (shared only) — separate audit trails
6. `docs/deployment/SSM_APP_SECRETS_ARCHITECTURE.md` exists and references this plan
7. `MEMORY.md` index updated

---

# Appendix A — Verbatim key inventory (sourced from `.env` read + grep against `/Users/henrychien/Documents/Jupyter/risk_module/**/*.py`)

## A.1 To-be-migrated to SSM (17 keys, verified via grep)

### Shared tier (`/risk-module/<env>/shared/`) — 11 keys, colleague can read

| Env var | SSM param | Read sites (verified) | Notes |
|---|---|---|---|
| `OPENAI_API_KEY` | `openai-api-key` | `providers/completion.py:229`, `scripts/benchmark_editorial_arbiter.py:322` | LLM completion |
| `FMP_API_KEY` | `fmp-api-key` | `fmp/client.py`, `mcp_bootstrap.py:37` (validation) | Required |
| `EDGAR_API_KEY` | `edgar-api-key` | `fmp/estimates_client.py:22` | Read as `ESTIMATE_API_KEY` |
| `GOOGLE_CLIENT_ID` | `google-client-id` | `app.py:327`, `services/auth_service.py:34` | OAuth (server-side) |
| `GOOGLE_CLIENT_SECRET` | `google-client-secret` | `app.py:328` | OAuth (server-side) |
| `GATEWAY_API_KEY` | `gateway-api-key` | `app_platform/gateway/proxy.py:69`, `routes/research_content.py:47`, `services/research_gateway.py:199`, `routes/gateway_proxy.py:59` | Single shared key (NOT the per-channel `_EXCEL`/`_TELEGRAM`/`_WEB`/`_MCP`/`_CLI` — those belong to AI-excel-addin) |
| `GATEWAY_RESOLVER_HMAC_KEY` | `gateway-resolver-hmac-key` | `routes/internal_resolver.py:63,71` | |
| `AGENT_API_USER_CLAIM_HMAC_KEY` | `agent-api-user-claim-hmac-key` | `settings.py:23` (module-import) | |
| `AGENT_API_KEY` | `agent-api-key` | `settings.py:21` (module-import) | Mirrors AI-excel-addin's `RISK_API_KEY` |
| `ADMIN_TOKEN` | `admin-token` | tests + route handlers (search for `ADMIN_TOKEN` env reads in `routes/`) | Hardcoded literal at `scripts/perf_measurement.py:20` killed in Phase 1 |
| `FLASK_SECRET_KEY` | `flask-secret-key` | `app_platform/middleware/sessions.py:15` (function-scope) | |

### Broker tier (`/risk-module/<env>/broker/`) — 6 keys, app-only

| Env var | SSM param | Read sites | Notes |
|---|---|---|---|
| `PLAID_CLIENT_ID` | `plaid-client-id` | `brokerage-connect/brokerage/config.py:49`, `mcp_bootstrap.py:18` | Module-import in vendored package |
| `PLAID_SECRET` | `plaid-secret` | `brokerage-connect/brokerage/config.py:50` | **Production-grade** (`PLAID_ENV=production`) |
| `SNAPTRADE_CLIENT_ID` | `snaptrade-client-id` | `brokerage-connect/brokerage/config.py:45` | |
| `SNAPTRADE_CONSUMER_KEY` | `snaptrade-consumer-key` | `brokerage-connect/brokerage/config.py:46` | |
| `SCHWAB_APP_KEY` | `schwab-app-key` | `brokerage-connect/brokerage/config.py:38` | |
| `SCHWAB_APP_SECRET` | `schwab-app-secret` | `brokerage-connect/brokerage/config.py:39` | |

## A.2 Removed from risk_module `.env` entirely (Phase 6 §S24 — verified via grep that risk_module Python does NOT read these)

These are AI-excel-addin-only or frontend-only and shouldn't be in risk_module's `.env`:
- `GOOGLE_API_KEY` (0 hits in risk_module/**/*.py)
- `BRAVE_API_KEY` (0 hits)
- `OPENAI_EMBEDDING_KEY` (0 hits)
- `EXCEL_MCP_SECRET` (0 hits in risk_module Python; lives in AI-excel-addin `api/main.py:136`)
- `GATEWAY_API_KEY_EXCEL` / `_TELEGRAM` / `_WEB` / `_MCP` / `_CLI` (0 hits in risk_module Python; issued by AI-excel-addin `api/main.py:361-365`)
- `REACT_APP_GOOGLE_CLIENT_ID` (frontend; superseded by `VITE_GOOGLE_CLIENT_ID` in `frontend/.env`. Note: `tests/frontend/setup.js` still sets it as a test fixture — benign, leave alone)

**NOT removed (correction from v2)**: `CHAT_API_KEY` stays in `risk_module/.env` because the TUI sources it via `set -a; source risk_module/.env; set +a`. risk_module Python doesn't read it but the TUI bootstrap pipeline does. Per `docs/planning/completed/GATEWAY_CLI_CHANNEL_WIRING_PLAN.md:114-137`.

## A.3 Stays in `.env` — infra config (~80 keys)

`DATABASE_URL`, `DATABASE_URL_DIRECT`, `FMP_DATA_DATABASE_URL`, `ENVIRONMENT`, `IS_DEV`, `USE_DATABASE`, `STRICT_DATABASE_MODE`, `DB_POOL_MIN`, `DB_POOL_MAX`, `STARTUP_PROBES`, `DISABLE_PYDANTIC_VALIDATION`, `USE_GPT_SUBINDUSTRY`, `SESSION_DURATION_DAYS`, `SESSION_CLEANUP_INTERVAL_HOURS`, `COOKIE_MAX_AGE_DAYS`, `PORTFOLIO_RISK_LRU_SIZE`, `SERVICE_CACHE_MAXSIZE`, `SERVICE_CACHE_TTL`, `DATA_LOADER_LRU_SIZE`, `TREASURY_RATE_LRU_SIZE`, `PLAID_ENV`, `SNAPTRADE_ENVIRONMENT`, `SNAPTRADE_BASE_URL`, `ENABLE_SNAPTRADE`, `SNAPTRADE_RATE_LIMIT`, `SNAPTRADE_HOLDINGS_DAILY_LIMIT`, `SNAPTRADE_PRIORITY`, `PLAID_PRIORITY`, `MANUAL_PRIORITY`, `TRADING_ENABLED`, `SHORT_SELLING_ENABLED`, `IBKR_ENABLED`, `IBKR_GATEWAY_HOST`, `IBKR_GATEWAY_PORT`, `IBKR_CLIENT_ID`, `IBKR_TIMEOUT`, `IBKR_READONLY`, `IBKR_FLEX_ENABLED`, `SCHWAB_ENABLED`, `SCHWAB_CALLBACK_URL`, `BACKEND_BASE_URL`, `FRONTEND_BASE_URL`, `GATEWAY_URL`, `GATEWAY_SSL_VERIFY`, `REDIS_CACHE_ENABLED`, `REDIS_URL`, `DEV_AUTH_BYPASS`, `RISK_API_URL`, `RISK_MODULE_RESOLVER_URL`, `AGENT_API_LEGACY_BEARER_ENABLED`, `EDITORIAL_LLM_PROVIDER`, `EDITORIAL_LLM_MODEL`, `EDGAR_API_URL`, `CELERY_ENABLED`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `CELERY_TASK_ALWAYS_EAGER`, `SYNC_PROVIDER_SCHWAB_VIA_CELERY`, `SYNC_PROVIDER_IBKR_VIA_CELERY`, `SYNC_PROVIDER_PLAID_VIA_CELERY`, `SYNC_PROVIDER_SNAPTRADE_VIA_CELERY`, `ORDERS_VIA_CELERY`, `ASYNC_REFRESH_UX_ENABLED`, `SYNC_*_INTERVAL_SECONDS` (5), `SNAPTRADE_ORPHAN_*` (3), `PLAID_DEAD_ITEM_*` (3), `CIRCUIT_BREAKER_*` (3), `API_BUDGET_*` (8), `FRESHNESS_CONTRACT_ENABLED`, `USE_SSM_SECRETS` (new).

## A.4 Stays in `.env` — bootstrap (chicken-and-egg)

`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`, `KMS_CREDENTIAL_KEY_ARN`.

## A.5 Stays in `.env` — personal / per-developer

`RISK_MODULE_USER_EMAIL`, `DEV_AUTH_EMAIL`, `CHAT_OPERATOR_USER_EMAIL`, `IBKR_FLEX_TOKEN`, `IBKR_FLEX_QUERY_ID`, `TRADE_ACCOUNT_MAP`, `IBKR_AUTHORIZED_ACCOUNTS`, `IBKR_STATEMENT_DB_PATH`, `SCHWAB_TOKEN_PATH`, `BACKFILL_FILE_PATH`, `PYTHONPATH`, `ANTHROPIC_AUTH_MODE`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY` (vestigial — see Open Questions §1), `KARTRA_*` (3, optional integration), `SNAPTRADE_WEBHOOK_FORWARD_SECRET` (per-deploy, optional).

## A.6 Module-import-time env reads (constraint on bootstrap order)

These fire at module load. `bootstrap_env` MUST be imported before any of them:

- `settings.py:19-435` — `FRONTEND_BASE_URL`, `BACKEND_BASE_URL`, `AGENT_API_KEY`, `AGENT_API_*` (4), `BACKFILL_FILE_PATH`, `REALIZED_USE_PROVIDER_FLOWS`, `OPTION_*` (4), `IBKR_FLEX_TOKEN`, `IBKR_FLEX_QUERY_ID`, `TRADING_ENABLED`, `SHORT_SELLING_ENABLED`, `IBKR_ENABLED`
- `app.py:316,327,328,918-920` — `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `KARTRA_*`
- `services/auth_service.py:34-42` — `GOOGLE_CLIENT_ID`, `DEV_AUTH_EMAIL`
- `utils/config.py:78-132` — `REDIS_*`, `PROVIDER_ROUTING_ENABLED`, `FMP_BASE_URL_*`
- `utils/logging.py:36,38` — `ENVIRONMENT`, `LOG_DIR`
- `utils/response_model.py:5` — `DISABLE_PYDANTIC_VALIDATION`
- `workers/celery_app.py:15,16` — `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`
- `fmp/estimates_client.py:21,22` — `ESTIMATE_API_URL`, `EDGAR_API_KEY`
- `brokerage-connect/brokerage/config.py:38-50` — `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET`, `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, `PLAID_CLIENT_ID`, `PLAID_SECRET` (vendored package; SSM hydration upstream solves it)

## A.7 Existing boto3 / AWS usage

- `services/credentials/cipher.py:20` — KMS client (per-user creds, shipped)
- `tests/services/credentials/test_cipher.py:24,40` — moto-mocked KMS
- `scripts/migrate_credentials_to_kms.py:137` — Secrets Manager client (legacy, retired 2026-04-30)
- No existing SSM usage anywhere
- No existing instance role — only long-lived IAM user creds

## A.8 Cross-repo wiring (must match between risk_module + AI-excel-addin)

| Risk_module env var | AI-excel-addin env var | Direction |
|---|---|---|
| `AGENT_API_KEY` | `RISK_API_KEY` | AI-excel-addin → risk_module |
| `BACKEND_BASE_URL` | `RISK_API_URL` | URL pointing risk_module → AI-excel-addin |
| `GATEWAY_API_KEY` (single value) | one of `GATEWAY_API_KEY_{EXCEL,CLI,TELEGRAM,WEB,MCP}` (per channel) | risk_module → AI-excel-addin |

`EXCEL_MCP_SECRET` is AI-excel-addin-only; risk_module's `.env` removes it in §S24.
