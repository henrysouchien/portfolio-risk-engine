# SSM Phase 4 — Colleague Enablement Plan

## Status: v7 — Codex R6 PASS + DB bootstrap blocker resolved (`schema_prod.sql` regenerated 2026-05-15 in commit `81f51b3b`; was a stale May 4 snapshot missing 4 KMS migration columns + `provider_routing_events`). Runbook step 10 restored to concrete recipe. Plan ready to execute pending remaining colleague-identity prerequisites only.

Implements Phase 4 (§S14, §S15, §S16) of `docs/planning/SSM_APP_SECRETS_MIGRATION_PLAN.md`. Phases 1-3, 5, 6, 7 already shipped (dev: 2026-05-13, prod: 2026-05-14). This plan captures the ownership model + access scoping + setup runbook for adding a trusted co-developer to the risk_module dev environment.

## Goal

A trusted co-developer can clone the repo, run `make dev`, and use ~100% of the product locally with **his own data**, without:
1. Henry sharing any of his `.env` files
2. The colleague registering any new Plaid/SnapTrade/Schwab/OpenAI/etc. developer accounts
3. The colleague gaining access to Henry's prod, per-user data, or admin AWS surface

End state: colleague has a scoped AWS IAM user, reads dev SSM secrets identical to what the app reads, runs his own local DB, connects HIS own broker accounts through the existing dev portal apps.

## Hard prerequisites

- [x] Phase 1-3 shipped — `bootstrap_env` module + SSM hydration + dev IAM read policies + 16 dev SSM SecureStrings provisioned
- [x] Dev CMK `alias/risk-module-credentials-dev` exists with key policy
- [x] **Project has a working "fresh DB from empty" procedure** (RESOLVED 2026-05-15 in commit `81f51b3b`). `database/schema_prod.sql` regenerated via `pg_dump --schema-only --no-owner --no-privileges` from a local dev DB with all 46 current migrations applied. Now contains all 4 KMS migration columns (`access_token_enc`, `token_updated_at`, `snaptrade_user_secret_enc`, `anthropic_api_key_kms_enc`) plus `provider_routing_events` table. Pattern: apply `schema_prod.sql` → preload `_migrations` with all current filenames → run `scripts/run_migrations.py` (no-op now) → run `scripts/seed_reference_data.py`. See concrete commands in §"Step 5 — Write `docs/setup/COLLABORATOR_SETUP.md`" runbook step 10.
- [ ] Colleague has Anthropic Console access (separate signup — he runs `claude /login` for his own `ANTHROPIC_AUTH_TOKEN`)
- [ ] Colleague has GitHub account; added as collaborator on `henrysouchien/risk_module`
- [ ] Google OAuth allowlist on dev OAuth client includes his email (or dev OAuth is open)

## Ownership map

| Layer | Owner | Colleague's relationship |
|---|---|---|
| AWS account `948633118115` | Henry | IAM user `dev-<name>` inside it; no admin/billing |
| AWS bill | Henry — every API call colleague makes hits Henry's card | Charges flow upstream; no per-user breakdown |
| KMS CMKs (`alias/risk-module-credentials-{dev,prod}`) | Henry | Dev CMK only: SSM-mediated decrypt (for SecureString unwrap) + direct Encrypt/Decrypt with `app=risk_module` context (for `cipher.py` per-user blob writes). No prod CMK grant. |
| `/risk-module/dev/{shared,broker}/*` SSM (16 keys) | Henry | Read-only |
| `/risk-module/prod/*` SSM | Henry | No access |
| Plaid developer account / app secrets | Henry | Uses Henry's keys; never sees Plaid dashboard |
| SnapTrade developer account | Henry | Same |
| Schwab dev portal app | Henry | Same |
| OpenAI / FMP / EDGAR / Google OAuth / Brave accounts | Henry | Uses Henry's keys |
| Anthropic OAuth token | Each developer separately | He generates his own via `claude /login` |
| Prod EC2 `edgar-updater` + prod RDS | Henry | No SSH, no IAM, no network access |
| Prod app deploys | Henry — `scripts/deploy.sh` | Cannot deploy |
| Git repo `henrysouchien/risk_module` | Henry | GitHub collaborator (separate from AWS) |
| Colleague's local postgres + `risk_module_db` | Colleague | His machine, his data |
| Colleague's Plaid Link items | Colleague (per-user) | His banks, his access_tokens, KMS-encrypted in his local DB |
| Colleague's SnapTrade connections | Colleague (per-user) | His brokerage |
| Colleague's Schwab OAuth tokens | Colleague (per-user) | His Schwab account, `~/.schwab_token.json` on his machine |
| Henry's local DB + Henry's data | Henry | Invisible to colleague — Henry's machine isn't network-reachable from colleague's. (NOT via KMS gating per v3 correction — see §"Per-user credential isolation" — if colleague obtained Henry's ciphertext, his dev-CMK direct-decrypt grant would let him decrypt it. DB-row access is the actual barrier.) |
| Henry's prod portfolio analytics (hank.investments) | Henry | No login |

## Access model — exactly what colleague's AWS identity grants

### Reads granted

| SSM path | Keys | Purpose |
|---|---|---|
| `/risk-module/dev/shared/*` | 10 keys: `OPENAI_API_KEY`, `FMP_API_KEY`, `EDGAR_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GATEWAY_API_KEY`, `GATEWAY_RESOLVER_HMAC_KEY`, `AGENT_API_USER_CLAIM_HMAC_KEY`, `AGENT_API_KEY`, `ADMIN_TOKEN` | App boot |
| `/risk-module/dev/broker/*` | 6 keys: `PLAID_CLIENT_ID`, `PLAID_SECRET`, `SNAPTRADE_CLIENT_ID`, `SNAPTRADE_CONSUMER_KEY`, `SCHWAB_APP_KEY`, `SCHWAB_APP_SECRET` (all production-grade — same as Henry's app uses) | Broker integration testing |

### Absence of allow (functional equivalent to denies — no IAM `Deny` statements involved; these resources/actions are simply not in any attached allow statement)

- All `/risk-module/prod/*` paths — no prod IAM policy attached
- SSM write (`PutParameter`, `DeleteParameter`) — no write policy attached
- KMS grants on prod CMK — only dev CMK statements added in Step 2
- Direct AWS console access to any resource other than his own IAM user

## Per-user credential isolation — DB-access bound, not encryption-context bound (v2 correction)

**v1 was wrong** on the isolation mechanism. Codex R1 P0 #1 caught it: for Plaid Link to work on colleague's local instance, the app calls `services/credentials/cipher.py:39` (`kms.Encrypt`) directly — not via SSM — to encrypt his fresh `access_token`. A SSM-only KMS grant would block this; Plaid Link would fail.

So colleague's KMS grant must allow **direct `kms:Encrypt` + `kms:Decrypt`** on the dev CMK, with encryption context conditioned on `app=risk_module` (the baseline context all per-user blobs include — see `cipher.py:36`).

This means: **encryption context alone does NOT prevent him from decrypting another user's blob if he ever obtains the ciphertext**. The isolation barrier is at the **DB-row access** layer, not KMS.

### Where the isolation actually lives

| Barrier | What it prevents |
|---|---|
| **He runs his own local DB** | He has zero rows of any other user's per-user blob. No ciphertext = nothing to decrypt. |
| **No access to Henry's local DB** | Henry's machine isn't reachable from his. Even with full KMS grant, no path to Henry's ciphertext. |
| **No access to prod RDS** | No prod IAM policy attached → no SSM read of prod broker secrets, no prod RDS network reachability. Even if he somehow obtained a prod-user ciphertext (e.g., from a database backup), prod CMK isn't in his key policy. |
| **No access to prod CMK** | Even hypothetically holding Henry's prod-user ciphertext, his IAM has no grant on the prod CMK at all. AccessDenied. |

### What this means for future Hank users (multi-user world)

When Hank has 1000 paying users on prod:
- Their per-user creds live in prod RDS, encrypted by **prod CMK**
- Colleague has zero grant on prod CMK
- Even if his dev-CMK key policy allows direct Decrypt with `app=risk_module` context, he never sees prod ciphertext (no prod DB access)
- He cannot read present/future prod user data — bounded by DB+CMK access, not encryption context

### What COULD compromise per-user isolation

If colleague:
1. **Exfiltrates Henry's local DB** (e.g., Henry shares a `pg_dump`, or his laptop is on Henry's network with credential reuse) → he holds Henry's ciphertext + can call `kms:Decrypt` with `app=risk_module` context → can decrypt
2. **Beta-tests on dev with an actual Hank user** who creates a per-user blob in HIS dev DB → he holds that user's ciphertext + decrypt grant → can decrypt
3. **Captures plaintext in transit** during Plaid Link exchange (`routes/plaid.py:979` may expose `access_token` in response per Codex R1 P1 #3) → no decryption needed, plaintext at rest in his app's logs/proxy

Defenses:
- Never share Henry's DB dump with him; each developer's DB is isolated
- Per-user creds for actual Hank users live in prod RDS, not dev DB (dev is for developers' own broker connections only)
- Audit / mitigate the plaintext-in-response code path as a separate hardening pass

### The triple gating (corrected)

| Gate | How it works | Bypassable? |
|---|---|---|
| **DB access** | Each dev has own postgres on own machine | Only via explicit sharing (don't do that) |
| **KMS grant scope** | Colleague's grant is dev CMK only, no prod CMK | No |
| **Provider-side per-item revocation** | Plaid Item revoke / SnapTrade user delete / Schwab token revoke at provider | Provider-mediated |

Encryption context provides defense in depth (rejects ciphertext-swap attacks between users) but is not the primary isolation barrier — DB-row access is.

## Scope checklist

- [ ] §S14 — IAM user `dev-<name>` exists with two policies attached: `risk-module-ssm-read-dev-shared-readonly` + `risk-module-ssm-read-dev-broker-readonly`
- [ ] §S15 — Dev CMK key policy amended with TWO statements granting the colleague's principal: (a) SSM-mediated `kms:Decrypt` for SecureString unwrap, (b) direct `kms:Encrypt`/`kms:Decrypt` for `cipher.py` per-user blob writes (with `app=risk_module` baseline context). See §"Step 2" for exact JSON.
- [ ] §S16 — `.env.colleague.template` checked in; `docs/setup/COLLABORATOR_SETUP.md` written; colleague runs end-to-end successfully
- [ ] Access keys delivered to colleague via secure channel (1Password / Signal)
- [ ] Colleague successfully boots `make dev` on his machine + Plaid Link round-trip on his local DB

## Implementation steps

### Step 1 — Create IAM user + readonly policies + attach

```bash
aws iam create-user --user-name dev-<name> \
  --tags Key=email,Value=<colleague-email> Key=role,Value=co-developer

# Write policy JSONs to mode-600 temp files
umask 077

cat > /tmp/risk-module-ssm-read-dev-shared-readonly.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadDevSharedSecrets",
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
      "Resource": "arn:aws:ssm:us-east-1:948633118115:parameter/risk-module/dev/shared/*"
    }
  ]
}
EOF

cat > /tmp/risk-module-ssm-read-dev-broker-readonly.json <<'EOF'
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadDevBrokerSecrets",
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
      "Resource": "arn:aws:ssm:us-east-1:948633118115:parameter/risk-module/dev/broker/*"
    }
  ]
}
EOF

# Note: the readonly policies cover ONLY the SSM read actions. KMS:Decrypt
# (for SSM SecureString unwrap) AND direct KMS:Encrypt/Decrypt (for cipher.py
# per-user blob writes during Plaid Link) come from the CMK key policy
# amendment in Step 2. Per-user data isolation is via DB-row access (his DB
# is his alone), not via KMS encryption context — see §"Per-user credential
# isolation" above for the corrected v2 model.

aws iam create-policy \
  --policy-name risk-module-ssm-read-dev-shared-readonly \
  --policy-document file:///tmp/risk-module-ssm-read-dev-shared-readonly.json

aws iam create-policy \
  --policy-name risk-module-ssm-read-dev-broker-readonly \
  --policy-document file:///tmp/risk-module-ssm-read-dev-broker-readonly.json

aws iam attach-user-policy --user-name dev-<name> \
  --policy-arn arn:aws:iam::948633118115:policy/risk-module-ssm-read-dev-shared-readonly

aws iam attach-user-policy --user-name dev-<name> \
  --policy-arn arn:aws:iam::948633118115:policy/risk-module-ssm-read-dev-broker-readonly

rm /tmp/risk-module-ssm-read-dev-*.json
```

### Step 2 — Amend dev CMK key policy (TWO statements per Codex R1 P0 #1)

The existing key policy grants `plaid-access-token-service` and `finance-web-deploy`. Add **two** statements for the colleague principal — one for SSM-mediated decrypt, one for direct cipher.py calls:

```json
{
  "Sid": "AllowColleagueSSMDecrypt",
  "Effect": "Allow",
  "Principal": {"AWS": "arn:aws:iam::948633118115:user/dev-<name>"},
  "Action": "kms:Decrypt",
  "Resource": "*",
  "Condition": {
    "StringEquals": {"kms:ViaService": "ssm.us-east-1.amazonaws.com"},
    "StringLike": {
      "kms:EncryptionContext:PARAMETER_ARN": [
        "arn:aws:ssm:us-east-1:948633118115:parameter/risk-module/dev/shared/*",
        "arn:aws:ssm:us-east-1:948633118115:parameter/risk-module/dev/broker/*"
      ]
    }
  }
}
```
This statement gates SSM unwrap. `PARAMETER_ARN` is an **array** (per Codex R1 P1 #2 — `{shared,broker}` brace expansion isn't valid IAM JSON; needs explicit array).

```json
{
  "Sid": "AllowColleagueDirectEncryptDecrypt",
  "Effect": "Allow",
  "Principal": {"AWS": "arn:aws:iam::948633118115:user/dev-<name>"},
  "Action": ["kms:Encrypt", "kms:Decrypt"],
  "Resource": "*",
  "Condition": {
    "StringEquals": {"kms:EncryptionContext:app": "risk_module"}
  }
}
```
This statement gates direct `cipher.py` calls. Required for Plaid Link → encrypt his fresh `access_token` to his local DB. Required for read-back to fetch holdings. Actions narrowed to `Encrypt`+`Decrypt` only — `cipher.py` doesn't call `GenerateDataKey` or `DescribeKey` (Codex R2 P2 #3).

The `kms:EncryptionContext:app` baseline is added last by `cipher.py:36` and rejects caller-supplied `app` keys — preventing cross-app misuse if the same CMK is ever granted to another application. He cannot encrypt with `app != risk_module`.

**Isolation reminder** (corrected from v1): this grant allows him to decrypt ANY `app=risk_module` ciphertext he holds, including any other user's blob. He never holds other users' blobs because his DB is isolated. See §"Per-user credential isolation" above for the full barrier table.

Apply via `aws kms get-key-policy --key-id alias/risk-module-credentials-dev --policy-name default` → edit JSON adding both statements → `aws kms put-key-policy --policy file://...` Without these grants, IAM identity policy alone is insufficient — KMS double-gates via key policy.

### Step 3 — Generate access keys + deliver

```bash
aws iam create-access-key --user-name dev-<name>
```

One-time output. Deliver to colleague via 1Password share or Signal. NEVER email or Slack.

### Step 4 — Write `.env.colleague.template`

Checked into repo at root. Every infra/feature-flag key present; every secret slot has `# REPLACE THIS` or `# OBTAINED FROM SSM` marker. Specifically:
- `USE_SSM_SECRETS=true`
- `SSM_REQUIRE_BROKER_TIER=true`
- `ENVIRONMENT=development`
- `AWS_ACCESS_KEY_ID=# REPLACE — your dev-<name> access key`
- `AWS_SECRET_ACCESS_KEY=# REPLACE — your dev-<name> secret`
- `AWS_DEFAULT_REGION=us-east-1`
- `KMS_CREDENTIAL_KEY_ARN=arn:aws:kms:us-east-1:948633118115:key/863b8f34-c275-4b05-9095-c7df7d740cc7`
- `DATABASE_URL=postgresql://postgres@localhost:5432/risk_module_db`
- `RISK_MODULE_USER_EMAIL=# REPLACE — your email`
- `DEV_AUTH_EMAIL=# REPLACE — your email`
- `ANTHROPIC_AUTH_MODE=oauth`
- `ANTHROPIC_AUTH_TOKEN=# REPLACE — generated by 'claude /login'`
- All the infra config (Celery toggles, IBKR disabled, etc.) included as-is
- NO `OPENAI_API_KEY`, `FMP_API_KEY`, `PLAID_*`, `SNAPTRADE_*`, `SCHWAB_*`, etc. — those come from SSM

### Step 5 — Write `docs/setup/COLLABORATOR_SETUP.md`

Step-by-step for the colleague (v2 — Codex R1 P0 #2 fixed DB bootstrap, P0 #3 added frontend, P1 #4 added OAuth allowlist step):

#### Prerequisites (verify before starting)
1. Accept GitHub collaborator invite to `henrysouchien/risk_module`
2. Henry confirms colleague's email is in dev Google OAuth client's allowlist (or that dev OAuth is open)
3. Henry confirms Plaid/SnapTrade/Schwab dev portal callback URLs include colleague's localhost — Schwab default is `https://127.0.0.1:8182` per `brokerage-connect/brokerage/config.py:41`; verify it's registered

#### Backend setup
4. `git clone https://github.com/henrysouchien/risk_module.git && cd risk_module`
5. Install Python 3.13 + create venv: `python3.13 -m venv venv && source venv/bin/activate`
6. `pip install -r requirements.txt`
7. `pip install -e brokerage-connect/`
8. Install postgres locally (homebrew `postgresql@17` or EDB installer)
9. Create database: `createdb risk_module_db`
10. **DB schema setup** (v7 — `schema_prod.sql` baseline restored in commit `81f51b3b`):
    ```bash
    # Apply baseline (all 46 migrations already baked in)
    psql -d risk_module_db -f database/schema_prod.sql

    # Preload _migrations so the runner skips already-baked migrations
    cd database/migrations
    for f in *.sql; do
      psql -d risk_module_db -c "INSERT INTO _migrations (filename, applied_at) VALUES ('$f', NOW()) ON CONFLICT DO NOTHING;"
    done
    cd ../..

    # Validate (should be no-op now; only future Henry-added migrations would apply)
    python3 scripts/run_migrations.py
    ```
    Expect `All migrations applied.` from the runner with no actual migrations executed (since all 46 are preloaded). Post-check:
    ```sql
    psql -d risk_module_db -c "
    SELECT count(*) AS expected_4_columns FROM information_schema.columns
    WHERE table_schema='public' AND (
      (table_name='provider_items' AND column_name IN ('access_token_enc','token_updated_at'))
      OR (table_name='users' AND column_name IN ('snaptrade_user_secret_enc','anthropic_api_key_kms_enc'))
    );
    "
    ```
    Must return 4. If less, something's wrong with the baseline — investigate before proceeding.
11. Generate own Anthropic OAuth token: `claude /login` → token printed → save it
12. `cp .env.colleague.template .env`
13. Edit `.env`:
    - AWS access keys (delivered via 1Password)
    - Personal: `RISK_MODULE_USER_EMAIL`, `DEV_AUTH_EMAIL`
    - `ANTHROPIC_AUTH_TOKEN` from step 11
14. `python3 scripts/health_check.py` — should pass (this also confirms `.env` loads, AWS creds work, SSM is reachable)
15. **Seed reference data**: `set -a; source .env; set +a; python3 scripts/seed_reference_data.py` — populates `futures_contracts` and `exchange_resolution_config`. The `set -a` wrapper is the primary command because `seed_reference_data.py` doesn't call `bootstrap_env`; it reads `DATABASE_URL` directly from process env. Running the bare `python3 scripts/seed_reference_data.py` works ONLY if the shell already exported `.env` (e.g., via shell rc). Use the wrapper unless you've explicitly sourced `.env` already.

#### Frontend setup
16. Install Node 24 (per `frontend/package.json:6` engine pin `>=24.15.0 <25`) and pnpm
17. `cd frontend && pnpm install && cd ..`
18. `cp frontend/.env.example frontend/.env` (if exists; otherwise create) — set `VITE_GOOGLE_CLIENT_ID`. Note: this is the OAuth `client_id` (semi-public — appears in browser OAuth URLs), NOT the secret. Colleague's local `.env` doesn't have `GOOGLE_CLIENT_ID` (it's hydrated from SSM only into backend `os.environ`, not into frontend build env). **Henry delivers the value alongside AWS keys** (e.g., in the same 1Password share) — Codex R5 P1 #2.

#### Boot
19. Terminal 1: `make dev` — backend starts on `localhost:5001`
20. Terminal 2: `cd frontend && pnpm dev` — frontend starts on `localhost:3000`
21. Browser → `localhost:3000` → Google sign-in → his `users` row is created
22. (Optional) Connect Plaid → his banks → access_tokens encrypted in his local DB via `cipher.py` direct KMS path

#### What to expect
- **Bootstrap is silent on success** — `bootstrap_env` only logs warnings/AccessDenied paths; no "OK" line on the happy path. Verify positively via the env-check command in §"Step 6 — Verify."
- **FLASK_SECRET_KEY warning is expected in dev** (v3 corrected per Codex R2 P1 #3): `bootstrap_env` logs a warning because `FLASK_SECRET_KEY` is not in dev SSM (per option B in the parent migration plan), but does not raise (it only raises when `ENVIRONMENT=production`). Backend still boots because `app_platform/middleware/sessions.py:12` `resolve_session_secret()` falls back to `"dev-only-not-for-production"` when the env var is missing AND environment is not production. `SessionMiddleware` is always installed regardless of `DEV_AUTH_BYPASS`; v2 incorrectly said `DEV_AUTH_BYPASS` "skips session middleware."
- Plaid Link, SnapTrade Connect, Schwab OAuth all work end-to-end

### Step 6 — Verify

- Colleague boots backend cleanly on his machine (no Application startup failed)
- Hydration verified by checking specific env vars are present (bootstrap is silent on success; no log line confirms count). Run from his machine:
  ```bash
  python3 -c "
  import bootstrap_env, os
  bootstrap_env.bootstrap()
  expected = ['OPENAI_API_KEY','FMP_API_KEY','EDGAR_API_KEY','GOOGLE_CLIENT_ID','GATEWAY_API_KEY','GATEWAY_RESOLVER_HMAC_KEY','PLAID_CLIENT_ID','PLAID_SECRET','SNAPTRADE_CLIENT_ID','SNAPTRADE_CONSUMER_KEY','SCHWAB_APP_KEY','SCHWAB_APP_SECRET']
  missing = [k for k in expected if not os.environ.get(k)]
  print(f'present: {len(expected)-len(missing)}/{len(expected)}; missing: {missing}')
  "
  ```
  Must show all 12 present, zero missing. Covers 6 shared (incl. GOOGLE_CLIENT_ID required by app.py:149) + 6 broker.
- He logs in via Google OAuth
- He runs a scenario tool (e.g., factor analysis) end-to-end
- He optionally Plaid-Links a bank and verifies his portfolio data shows in `/api/portfolios`

## Typical interaction flows

### Flow 1 — Cold boot

`bootstrap_env` runs on import. With `USE_SSM_SECRETS=true` + `SSM_REQUIRE_BROKER_TIER=true` + `ENVIRONMENT=development`:
- Two `GetParametersByPath` calls (shared then broker) as his IAM identity
- 16 keys hydrated into `os.environ`
- Required-secrets check passes
- App boots

### Flow 2 — Plaid Link (test)

- He clicks "Connect Plaid" in the UI
- App uses `PLAID_CLIENT_ID` from SSM (Henry's Plaid app)
- Plaid Link UI opens, he selects his bank, authenticates with HIS bank credentials
- Plaid returns access_token specific to (Henry's Plaid app) × (his bank account)
- App KMS-encrypts with context `{user_id=<his_row>, credential_type=plaid_access_token, item_id=<plaid_item_id>}`
- Stored to his local DB's `provider_items.access_token_enc`
- Holdings fetched and saved to his local DB

### Flow 3 — Scenario analysis

- Hits `/api/risk/analysis` for his portfolio
- App calls FMP using `FMP_API_KEY` from SSM (Henry's FMP account → Henry's bill)
- App calls OpenAI using `OPENAI_API_KEY` from SSM (Henry's OpenAI → Henry's bill)
- Risk analysis returns

### Flow 4 — Daily sync

- He pulls latest `main`
- If new migration: `python3 scripts/run_migrations.py`
- Restart `make dev`
- `bootstrap_env` re-reads SSM (gets fresh values if Henry rotated)

### Flow 5 — Cost monitoring

All third-party API costs flow to Henry's accounts. No per-user attribution unless explicit tagging is added (out of scope for Phase 4).

### Flow 6 — Compromise / offboarding (v2 expanded per Codex R1 P1 #3)

If colleague leaves the project or his laptop is compromised:

1. **Detach IAM policies + delete keys**:
   ```bash
   aws iam detach-user-policy --user-name dev-<name> --policy-arn arn:...readonly-shared
   aws iam detach-user-policy --user-name dev-<name> --policy-arn arn:...readonly-broker
   aws iam delete-access-key --user-name dev-<name> --access-key-id ...
   aws iam delete-user --user-name dev-<name>
   ```
2. **Remove from CMK key policy** (both statements added in Step 2): edit dev CMK policy to remove his principal from `AllowColleagueSSMDecrypt` and `AllowColleagueDirectEncryptDecrypt`.
3. **Rotate all 16 dev SSM keys** (10 shared + 6 broker) per the rotation recipe in `docs/deployment/SSM_APP_SECRETS_ARCHITECTURE.md`. Reason: all 16 were decrypted into his `os.environ` and may have been cached/logged.
4. **Rotate at provider side** (now mandatory per Codex R1 P1 #3, not optional): Plaid `routes/plaid.py:979` exchange may expose plaintext `access_token` in HTTP responses, which proxies/loggers may have captured. Provider-side revocation is the only sure remediation:
   - Plaid: revoke `client_secret` in Plaid Dashboard; rotate to a new one; update SSM
   - SnapTrade: regenerate `consumer_key` in SnapTrade Dashboard; update SSM
   - Schwab: rotate `app_secret` in Schwab Dev Portal; update SSM
   - OpenAI / FMP / EDGAR / Google OAuth: rotate at each provider; update SSM
5. **His per-user broker data** (in his local DB) — Plaid access tokens, SnapTrade user secrets — are encrypted with `app=risk_module` baseline plus his `user_id` context. He has direct-decrypt grant on dev CMK (per Step 2), so attacker holding his laptop has both ciphertext (local DB) AND decrypt path. **Mandatory mitigation**: revoke per-user broker connections at provider:
   - Plaid Item revoke (`/item/remove` for each of his connected items)
   - SnapTrade user delete (deletes his SnapTrade user account)
   - Schwab token revoke (per-OAuth-token at Schwab side)
6. **Audit CloudTrail** for the colleague's SSM read history during the suspected compromise window — useful for incident scoping but does NOT enumerate per-parameter values returned by `GetParametersByPath`. Conservative assumption: all 16 dev keys are compromised, hence step 3 + 4 above.

## What is and isn't isolated

**Cleanly isolated (v3 corrected per Codex R2 P0 #2)**:
- His IAM → can only read dev SSM (no prod SSM, no admin, no write)
- His machine → no SSH to prod EC2, no network access to prod RDS
- Henry's local DB → completely invisible to him (Henry's machine isn't reachable from his)
- Prod CMK → not in his key policy at all; cannot decrypt any prod-encrypted ciphertext even if he obtained the blob
- All future Hank users (when they sign up on prod) → their per-user creds in prod RDS encrypted by prod CMK; no path for him

**NOT cleanly isolated (corrected)**:
- All API costs (OpenAI/FMP/Anthropic/etc.) hit Henry's bills
- App-level Plaid/SnapTrade misuse via his leaked SSM keys would damage Henry's Plaid/SnapTrade app reputation
- He sees the codebase including planning docs + commit history (any secrets in git history would be visible)
- His Plaid Link flow uses Henry's Plaid app display name (he sees "Hank" or whatever Henry registered as on Plaid)
- **Dev-CMK per-user blobs (anyone's, including Henry's) — CAN be decrypted by him IF he obtains the ciphertext.** Direct `kms:Decrypt` grant on dev CMK with `app=risk_module` baseline context means he can decrypt any `app=risk_module` ciphertext he ever holds. He doesn't hold Henry's because Henry's DB is on Henry's machine. But: don't `pg_dump` your dev DB to share with him; that would hand him decryptable ciphertext.
- **The app principal (`plaid-access-token-service`) and `finance-web-deploy`** also have direct dev-CMK decrypt grant (existing key policy). His broker connections are not "only HE can decrypt" — Henry's app principal and admin user can too. That's the intended model (the app needs to decrypt for the app to function).

## Out of scope

- **Per-developer cost attribution** — would require tagging CloudTrail or adding custom request middleware. Not needed for two developers.
- **Multi-region failover** — single region for v1 (us-east-1)
- **Shared dev database / RDS** — each developer runs own local postgres
- **Henry's local data migration to prod** — orthogonal cleanup; filed as separate "V-Local-Clean" follow-up
- **EC2 instance role for prod app** — separate plan, removes one of three home-laptop access paths per `docs/deployment/SSM_APP_SECRETS_ARCHITECTURE.md` threat model section
- **Hardware MFA for AWS admin** — separate plan
- **`schema_prod.sql` regeneration** (Codex R3 P0 #1-3 — hard prerequisite). Out of Phase 4 scope itself; either Henry regenerates the baseline OR Phase 4 cannot execute. See §"Hard prerequisites" Resolution options.
- **Rerun idempotency** (Codex R3 P1 #2). `schema_prod.sql` uses plain `CREATE TABLE` (no `IF NOT EXISTS`) so re-running step 10 against an existing DB fails. `aws iam create-user` / `create-policy` also fail on existing resources. Treat the runbook as one-shot; for rerun, either drop the DB + start fresh OR adapt each step to check-and-skip.
- **Phase 4 expansion to N>1 colleagues (Codex R2 P1 #2 — partially in-scope clarification)** — the pattern scales but the implementation steps are NOT trivially repeatable as written. Specifically:
  - `aws iam create-policy --policy-name risk-module-ssm-read-dev-shared-readonly` fails on second invocation because policy names are account-global.
  - The CMK key policy statement Sids (`AllowColleagueSSMDecrypt` / `AllowColleagueDirectEncryptDecrypt`) must be unique per colleague OR consolidated with an array of principals.
  
  For the second colleague, use this adapted pattern:
  - Reuse the existing `risk-module-ssm-read-dev-shared-readonly` and `-broker-readonly` policies (just attach to the new IAM user); skip the `create-policy` step
  - In the CMK key policy, EITHER add new statements with unique Sids (e.g., `AllowColleague2SSMDecrypt`) OR amend existing principals arrays to include both colleagues
  
  Architectural change: none. Operational repeatability: needs adaptation.

## Open questions (Henry needs to provide)

1. **Colleague's identifier** — first name or short handle for `dev-<name>` IAM username
2. **Colleague's email** — for IAM tags + 1Password share + Google OAuth allowlist verification
3. **Secure delivery channel** — 1Password share / Signal / etc.
4. **Confirm colleague has Anthropic Console access** — needed for `claude /login`
5. **Confirm Google OAuth dev client allows his email** (or that dev OAuth is open)
6. **Confirm GitHub collaborator invite sent**
7. **Confirm Plaid/SnapTrade/Schwab dev portal callback URLs include his localhost** (per Codex R1 P1 #5). Schwab default callback is `https://127.0.0.1:8182`; verify it's registered in Schwab Dev Portal. Plaid Link uses `FRONTEND_BASE_URL` for redirect — verify dev Plaid app accepts `http://localhost:3000`. SnapTrade similar.
8. **(Documentation) Parent docs need amending** — per Codex R1 P1 #1, the parent migration plan §S14 (`docs/planning/SSM_APP_SECRETS_MIGRATION_PLAN.md`) and the architecture doc (`docs/deployment/SSM_APP_SECRETS_ARCHITECTURE.md`) currently say broker tier is app-only / colleague excluded. This Phase 4 plan overrides both with broker-included-for-colleague. Either:
   - Amend the parent docs to reference this Phase 4 plan as the override (cleanest, recommended)
   - Or treat this Phase 4 plan as a documented deviation (less clean, easier to miss in future audits)
   Henry decides timing — amendment can happen as part of Phase 4 close.

## Success criteria

1. Colleague boots backend cleanly on his machine
2. Bootstrap completes silently on the happy path (per `bootstrap_env.py` — no success log line; only warnings/errors are logged). For positive verification, run the env-check command in §"Step 6 — Verify" — expect 12 present, 0 missing.
3. He logs into the app via Google OAuth → his user row created
4. He completes Plaid Link with his bank → access_token stored in his local DB
5. He runs `/api/risk/analysis` on his portfolio → returns successfully
6. He attempts `/risk-module/prod/shared/*` SSM read → AccessDenied (proves scope works)
7. CloudTrail shows reads from `dev-<name>` IAM user — audit trail clean
8. **Compromise drill**: detach his policies via CLI, confirm his subsequent SSM read returns AccessDenied within 60 seconds of IAM propagation

## Decisions log

- **2026-05-15 (v1)** — Plan v1 drafted. Same-broker-SSM-tier-as-app model chosen (option B from Codex R1 P0 #6 reconsideration). Sandbox apps for Plaid/SnapTrade/Schwab not needed — Henry's existing dev portal apps are reused. Per-user data isolation **claimed** to be via KMS encryption context.
- **2026-05-15 (v1)** — Each developer runs own local postgres. No shared dev RDS. Schema synced via `scripts/run_migrations.py` after each `git pull`.
- **2026-05-15 (v2 — Codex R1 FAIL)** — Codex R1 returned FAIL: 4 P0 / 6 P1 / 4 P2. v2 changes:
  - **Per-user isolation reframed (R1 P0 #1).** v1 was wrong that KMS encryption context alone prevents him from decrypting per-user blobs. The app uses `kms.Encrypt`/`Decrypt` DIRECTLY in `cipher.py:39` for per-user creds — not via SSM service. So colleague needs direct `kms:Encrypt`/`Decrypt` grant for Plaid Link to work. CMK key policy v2 adds TWO statements: one for SSM-mediated reads (conditional on `kms:ViaService=ssm` + `PARAMETER_ARN`), one for direct cipher.py calls (conditional only on `kms:EncryptionContext:app=risk_module`). Isolation now correctly framed as **DB-row access bound**: he never holds another user's ciphertext because his DB is isolated. Defense in depth is still real (encryption context rejects ciphertext-swap), but it's not the primary barrier.
  - **DB bootstrap fixed (R1 P0 #2).** v1 said `scripts/run_migrations.py` creates schema. False — it only runs migrations. v2 adds `psql -d risk_module_db -f database/schema.sql` step before migrations. Plus warning about one migration with `\` psql metacommand that psycopg2 can't run.
  - **Frontend setup added (R1 P0 #3).** v1 said browse `localhost:3000` after `make dev`. But `make dev` is backend only. v2 adds Node 24 install, `pnpm install`, `frontend/.env` with `VITE_GOOGLE_CLIENT_ID`, separate `pnpm dev` terminal.
  - **Step 1 JSON inlined (R1 P0 #4).** v1 referenced `file:///tmp/...` placeholders. v2 includes the JSON heredocs + cleanup.
  - **CMK key policy ARN scope narrowed (R1 P1 #2).** v1 used `risk-module/dev/*`. v2 uses explicit array `[shared/*, broker/*]`.
  - **Compromise IR mandates provider-side revocation (R1 P1 #3).** `routes/plaid.py:979` may expose plaintext access_token in HTTP responses. v2 makes provider-side revocation mandatory (Plaid Item revoke, SnapTrade user delete, Schwab token revoke), not optional.
  - **Google OAuth allowlist in runbook (R1 P1 #4)** — was only in prerequisites; now also in setup runbook prerequisites step.
  - **Provider callback URL prerequisite (R1 P1 #5)** — added open question 7.
  - **FLASK_SECRET_KEY note (R1 P1 #6)** — runbook explicitly says dev warning is expected, not an error.
  - **Terminology fixes (R1 P2 #1, #2, #3, #4)** — "Explicit denies" reworded as "absence of allow," `{shared,broker}` IAM syntax fixed to array, `DEV_AUTH_EMAIL` does NOT create the OAuth user (it's for `DEV_AUTH_BYPASS`), `ANTHROPIC_AUTH_TOKEN` clarified as chat-feature scope.
- **2026-05-15 (v3 — Codex R2 FAIL)** — Codex R2 returned FAIL on v2: 2 P0 / 3 P1 / 4 P2. v3 changes:
  - **DB bootstrap fix (R2 P0 #1)** — `schema.sql + run_migrations.py` was wrong: `schema.sql` includes fields that migrations re-add non-idempotently. v3 uses the prod-deploy pattern (per `MULTI_USER_DEPLOYMENT_PLAN.md`): `schema_prod.sql` (the canonical baseline) + preload `_migrations` with all existing migration filenames before running the migrations runner. Plus `seed_reference_data.py` for required reference tables.
  - **Stale isolation claims scrubbed (R2 P0 #2)** — Ownership map line and "Cleanly isolated" / "Not isolated" tables were still claiming SSM-only-decrypt and "only HE can decrypt his broker connections." v3 corrects: dev CMK direct-decrypt grant means he can decrypt any `app=risk_module` ciphertext he holds; isolation is via DB access (he doesn't hold others' ciphertext), not via encryption context. App principal and finance-web-deploy also decrypt his blobs by design.
  - **FLASK_SECRET_KEY behavior corrected (R2 P1 #3)** — v2 said `DEV_AUTH_BYPASS` skips session middleware. Wrong. `SessionMiddleware` is always installed; `resolve_session_secret()` falls back to `"dev-only-not-for-production"` when env var is missing AND environment != production.
  - **Idempotency note for N>1 colleagues (R2 P1 #2)** — out-of-scope clarification about how to add a second colleague.
  - **`kms:GenerateDataKey` + `DescribeKey` removed (R2 P2 #3)** — direct-decrypt statement now only `Encrypt` + `Decrypt`.
  - **Log line claim corrected (R2 P2 #1)** — bootstrap is silent on success; no "SSM hydration OK" line exists.
  - **schema.sql sample-data concern (R2 P2 #4) resolved** — using `schema_prod.sql` instead, which doesn't carry sample data.
- **2026-05-15 (v4 — Codex R3 FAIL)** — Codex R3 returned FAIL on v3: 3 P0 / 3 P1 / 2 P2. v4 changes:
  - **`schema_prod.sql` staleness gated (R3 P0 #1-3).** The May 4 snapshot is missing later migrations (notably April 30 KMS cred migration with `*_enc` columns required by `services/credentials/{plaid,snaptrade,anthropic}.py`, and the May 7 `provider_routing_events` migration). v3's "preload all migrations + expect no-op" recipe would silently mark these as applied → broken DB. v4 makes schema_prod.sql freshness a HARD PREREQUISITE with three resolution options (regenerate via pg_dump being recommended). Runbook step 11 + 12 explicitly warn that the gate must be cleared first.
  - **Stale ownership map claim (R3 P1 #1)** — line about "different machine, different DB, KMS gating" reworded; KMS is not the barrier per v3 correction.
  - **Rerun idempotency (R3 P1 #2)** — explicit "treat as one-shot" note in Out of Scope.
  - **Success criteria fixed (R3 P1 #3)** — removed "Bootstrap stderr shows N keys hydrated" (bootstrap is silent on success); replaced with explicit Python verification command.
  - **Migration runner output (R3 P2 #1)** — corrected expected output to "All migrations applied." (per `run_migrations.py:69`).
  - **Line number reference (R3 P2 #2)** — `scripts/run_migrations.py:31-32` → `:41`.
- **2026-05-15 (v5 — Codex R4 FAIL)** — Codex R4 returned FAIL on v4: 1 P0 + 5 P1 + 3 P2. v5 changes:
  - **DB bootstrap fully scoped OUT of Phase 4 (R4 P0 #1)** — v4 claimed step 12 would validate schema_prod.sql freshness; it can't. The runner prints "All migrations applied." regardless. v5 stops trying to own this. §"Hard prerequisites" names the upstream blocker: project lacks a working "fresh DB from empty" procedure. Runbook step 10 just says "follow Henry's procedure" + adds a column-existence check (`provider_items.access_token_enc`) as a minimal post-hoc verification.
  - **Step 6 Verify: removed stale "stderr shows N keys hydrated" (R4 P1 #3)** — bootstrap is silent on success. Replaced with explicit Python env-check covering 10 keys (5 shared + 5 broker).
  - **Scope checklist §S15 fixed (R4 P1 #5)** — now describes both KMS statements (SSM-mediated + direct), matching Step 2's actual implementation.
  - **Step 6 verify now covers all 6 broker keys (R4 P1 #4)** — env-check verifies all broker tier keys, not just one representative.
  - **MULTI_USER_DEPLOYMENT_PLAN.md §3E staleness (R4 P1 #1-2)** — Plan acknowledged but does NOT amend that doc (out of scope). Filed as a project-wide concern in §"Out of scope."
  - **Step numbering** — renumbered 11-22 cleanly after step 10 collapse.
- **2026-05-15 (v6 — Codex R5 FAIL)** — Codex R5 returned FAIL on v5: 1 P0 + 3 P1 + 2 P2. All mechanical. v6 changes:
  - **Seed reference data reordered (R5 P0 #1)** — `seed_reference_data.py` doesn't call bootstrap_env, so it can't read DATABASE_URL until `.env` exists. v6 moves the seed step to AFTER `.env` is copied + edited + health_check passes. Also adds fallback `set -a; source .env; set +a` wrapper if needed.
  - **Env-check expanded to 12 keys (R5 P1 #1)** — was 10, missing GOOGLE_CLIENT_ID (required by app.py:149). v6 adds GOOGLE_CLIENT_ID + GATEWAY_RESOLVER_HMAC_KEY. Now 6 shared + 6 broker = 12.
  - **VITE_GOOGLE_CLIENT_ID delivery clarified (R5 P1 #2)** — colleague's `.env` doesn't have GOOGLE_CLIENT_ID locally (it's SSM-only into backend env). Frontend build needs it. Henry delivers the client_id (semi-public — appears in browser OAuth URLs) alongside AWS keys in the same 1Password share.
  - **DB column check strengthened (R5 P1 #3)** — now checks 4 KMS migration columns (`access_token_enc`, `token_updated_at`, `snaptrade_user_secret_enc`, `anthropic_api_key_kms_enc`) instead of just one. Catches more staleness.
  - **Decision log key count fixed (R5 P2 #1)** — was "5 shared + 5 broker"; v6 says "6 shared + 6 broker."
  - **Success criteria env-check aligned with Step 6 (R5 P2 #2)** — both now reference 12 keys.
- **2026-05-15 (v6.1 — Codex R6 PASS)** — single P1 fixed: seed step now uses `set -a; source .env; set +a; python3 scripts/seed_reference_data.py` as the primary command instead of "bare command + fallback wrapper." Plan ready to ship as planning artifact; execution awaits prerequisites.
- **2026-05-15 (v7 — DB bootstrap blocker resolved)** — Regenerated `database/schema_prod.sql` (commit `81f51b3b`) via `pg_dump --schema-only --no-owner --no-privileges` from local dev DB with all 46 migrations applied. Old baseline was May 4 snapshot, missing the 4 April 30 KMS migration columns + `provider_routing_events` table. New baseline (128 KB, +3 KB) contains all current schema. Runbook step 10 restored to concrete recipe: `psql -f schema_prod.sql` → preload all migration filenames into `_migrations` → run `run_migrations.py` (no-op) → seed reference data. Phase 4 now executable end-to-end pending only the colleague-identity inputs (name, email, delivery channel, Anthropic Console confirmation, GCP OAuth/Plaid/SnapTrade callback verification).

## Related Documents

- `docs/planning/SSM_APP_SECRETS_MIGRATION_PLAN.md` — parent migration plan (v7, Phases 1-3, 5, 6, 7 shipped)
- `docs/deployment/SSM_APP_SECRETS_ARCHITECTURE.md` — production architecture + threat model
- `docs/deployment/CREDENTIALS_KMS_ARCHITECTURE.md` — per-user credential KMS architecture
- `docs/setup/CROSS_REPO_WIRING.md` — cross-repo env wiring (AI-excel-addin / risk_module)
