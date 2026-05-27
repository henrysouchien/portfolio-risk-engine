> **✅ SHIPPED — feat(credentials) per-user secrets KMS migration. Moved during 2026-05-26 docs cleanup.**

# Per-User Credentials → KMS-Encrypted DB Storage Migration

## Status: v6.1 — Codex R6 PASS on 2026-04-30 (3 minor clarifications applied)

**v6 changes from v5 (Codex R5):**
- **Cutover commands switched to repo migration runner** — uses `python scripts/run_migrations.py` (which tracks `_migrations`); cleanup migration kept out of `database/migrations/` until post-verification, then dropped in and re-run. Direct `psql -f` removed (would bypass tracking).
- **Plaid lifecycle helpers reclassified**: `routes/plaid.py:1587 disconnect_plaid_connection` is REVOKE semantics (calls Plaid `/item/remove`, deletes credential, deletes provider_item). Maps to `revoke_plaid_item(user_id, item_id)`. The `routes/plaid.py:372-379` `status='disconnected', user_deactivated=TRUE` path is the **reconciliation/sweep** path (called when reconciler finds items not in the active connection list), not user-initiated disconnect. Both helpers stay in the plan but with corrected semantics.
- **Appendix A.6 expanded** with brokerage-internal callers: `brokerage/snaptrade/adapter.py:101, 130, 172, 202, 240, 296, 305, 383`, `brokerage/snaptrade/connections.py:54, 133, 177`, `brokerage/snaptrade/trading.py:144`. Plus `services/trade_execution_service.py:178-185` where `SnapTradeBrokerAdapter` is instantiated.
- **Appendix A.5 expanded**: `tests/brokerage/test_short_broker_adapters.py:97, 128`, `tests/routes/test_provider_refresh_store_error.py`.
- **`scripts/snaptrade_sdk_smoke.py` exception**: ephemeral test user has no DB user_id; smoke holds the returned secret in memory and passes it to subsequent calls without touching the credential store. Does not call `services.credentials.snaptrade.*`.
- **Brokerage source `pyproject.toml` cleanup**: drop `boto3>=1.42,<2`, `botocore>=1.42,<2` from `brokerage/pyproject.toml:17` (snaptrade extra) and `:19` (plaid extra). The dist sync at `scripts/sync_brokerage_connect.sh:31` excludes `pyproject.toml`, so source must be edited; dist sync will then pick up the cleaned source via the manual version bump in Phase 6.

**v5 changes from v4 (Codex R4 review):**
- **Appendix A.6 added** — public SnapTrade wrapper call sites (every caller of `place_snaptrade_checked_order`, `cancel_snaptrade_order`, `list_user_accounts`, `register_snaptrade_user`, `rotate_snaptrade_user_secret`, etc.). These functions today take `user_email` and fetch the secret internally; post-refactor they accept `user_secret` as a parameter, so every call site updates.
- **Appendix A.3 expanded** to include: `services/anthropic_credential_store.py:57`, `brokerage/plaid/secrets.py:42,67,88,110,132` (deleted file but listed for completeness), `brokerage/snaptrade/secrets.py:31,66,96,145,173`, `tests/snaptrade/test_snaptrade_registration.py:120`.
- **Appendix A.5 expanded** with the rest of the SnapTrade and Anthropic test files.
- **Plaid lifecycle helpers** made explicit: three named helpers — `AccountRegistry.register_plaid_item` (connect), `AccountRegistry.soft_disconnect_plaid_item` (user-initiated disconnect; matches `routes/plaid.py:372-373`), `AccountRegistry.revoke_plaid_item` (hard revoke; matches `delete_plaid_user_tokens` flow at `routes/plaid.py:1795`).
- **SnapTrade rotation callback contract** spelled out — exact signatures for `_call_with_secret_rotation`, `rotate_snaptrade_user_secret`, `_try_rotate_secret`, `recover_snaptrade_auth`. Caller wires `on_secret_rotated` to write back to credential store; race behavior under `get_snaptrade_rotation_lock` documented.
- **Brokerage `boto3` dependency dropped** — after deleting `brokerage/{plaid,snaptrade}/secrets.py`, brokerage has no AWS calls (verified via grep). `boto3`/`botocore` removed from `brokerage-connect-dist/pyproject.toml` extras. risk_module keeps `boto3` for KMS.
- **Cutover service commands spelled out**: `service_stop("risk_module")`, run migration, deploy code, `service_start("risk_module")`, `service_status("risk_module")` to verify.

Migrates per-user credentials (Plaid access tokens, SnapTrade user secrets, Anthropic BYOK keys) out of AWS Secrets Manager into KMS-encrypted Postgres columns. **Pre-deploy migration; clean cutover; one user.**

**v4 changes from v3 (Codex R3 review):**
- **Phase 4 inventory replaced with verbatim grep output** (Appendix A) covering 60+ call sites. No more memory-based listing.
- **Real brokerage exports verified**: `SnapTradeBrokerAdapter` (not `SnaptradeAdapter`); Plaid exports do not include a `Client` class — Phase 6 smoke uses real symbols.
- **SnapTrade trading.py inventory expanded to all 10 sites**: 38, 60, 138, 175, 248, 266, 293, 312, 340, 358. **connections.py to 5 sites**: 86, 113, 184, 322, 341. **client.py wrappers to 3 sites**: 530, 556, 586 (plus the wrapper definition at 75).
- **Encryption context merge order fixed** — baseline applied last so callers cannot override `app=risk_module`. Caller-supplied `app` key is rejected.
- **Migration state enum** — `DB_MISSING`, `DB_PRESENT_VERIFIED`, `DB_PRESENT_DECRYPT_ERROR`, `DB_PRESENT_KMS_ERROR`, `AWS_PRESENT`, `AWS_MISSING`. KMS errors no longer conflated with "missing".
- **Cutover sequence committed**: dev backend stopped during migrate+deploy. No "old code running concurrently with migration" gap.
- **Canonical email→user_id resolver named**: `utils/user_resolution.resolve_user_id` (verified to exist). All route/MCP/script boundaries use this.
- **`provider_items` + `data_sources` "single transaction" rule** retracted as aspirational — current code at `routes/plaid.py:949-967` is three separate writes. The plan introduces `services/account_registry.AccountRegistry.register_plaid_item(...)` (or extends existing) to own a single transaction that writes provider_items + data_sources atomically, used by the OAuth callback. Reauth/disconnect flows similarly route through helpers, not raw SQL.
- **Doc sweep expanded**: `docs/guides/BROKERAGE_ADMIN.md:31, 84`, route comments at `routes/plaid.py:643, 925, 1262, 1652`.

## Motivation

April 2026 AWS bill flagged $83 in Secrets Manager charges (driven by a separate finance-cli project leaking ~377 backup-key secrets). risk_module owns 3 secrets today (~$1.20/mo) but architecture scales linearly with `users × broker_connections`:

| Scale | Plaid (3/user avg) | SnapTrade | Anthropic | Storage cost |
|---|---|---|---|---|
| Today (1 user) | 1 | 1 | 1 | $1.20 |
| 100 users | 300 | 100 | 100 | $200 |
| 1,000 users | 3,000 | 1,000 | 1,000 | $2,000 |
| 10,000 users | 30,000 | 10,000 | 10,000 | $20,000 |

KMS replacement: $1/CMK/month flat + ~$0.03/10k API calls. At 10k users, ~$135/month — **148× cheaper** than Secrets Manager. Plus DB-dump-can't-decrypt defense-in-depth, CloudTrail audit, automatic CMK rotation, no env-var Fernet key, fixes Plaid doubled-write bug (`docs/TODO.md:1082`).

## Hard prerequisites

1. **AWS account access** — IAM permissions for KMS CMK creation + key policy. Confirmed.
2. **Postgres `BYTEA`** — already in use elsewhere; not new.
3. **`cryptography` library** — already in `requirements.lock`.
4. **`moto[kms]`** — verified absent from deps; must be added.
5. **No live users** — pre-deploy. Migration handles 3 known dev secrets only.
6. **`brokerage-connect-dist` coordination** — `brokerage/` synced via `scripts/sync_brokerage_connect.sh`. The pivot keeps `brokerage` standalone with no DB/KMS dependency. Version bumps 0.2.2 → 0.3.0 (breaking signatures).
7. **`utils/user_resolution.resolve_user_id`** — verified to exist (`utils/user_resolution.py:6`). Canonical email→user_id resolver.

## Goal

By migration completion:
- Zero per-user data in AWS Secrets Manager.
- One KMS CMK per environment (dev + prod), rotation enabled.
- All three credential types read/written through `services/credentials/`, encrypted via single cipher helper.
- `brokerage/` package no longer touches AWS Secrets Manager and has no DB dependency. Clients accept tokens/secrets at call time.
- All `boto3.client("secretsmanager")` references removed.
- `ANTHROPIC_CRED_ENCRYPTION_KEY`, `ALLOW_DB_CRED_FALLBACK`, `anthropic_api_key_secret_ref` removed.
- Fernet code path deleted.
- 3 dev secrets migrated and force-deleted from AWS.

## Architecture

### Module layout (post-migration)

```
brokerage/                          # standalone; synced to brokerage-connect-dist
  plaid/
    __init__.py                     # NO credential exports
    client.py                       # exposes existing API funcs (unchanged signatures except access_token)
    connections.py                  # accepts access_token as param
    secrets.py                      # DELETED
  snaptrade/
    __init__.py                     # NO credential exports
    _shared.py                      # _get_snaptrade_identity → accepts user_secret
    adapter.py                      # SnapTradeBrokerAdapter accepts user_secret in __init__
    client.py                       # accepts client_id/consumer_key from env; _call_with_secret_rotation accepts secret-rotation callbacks
    connections.py                  # accepts user_secret as param
    recovery.py                     # accepts user_secret/storage callbacks
    trading.py                      # accepts user_secret as param
    users.py                        # accepts user_secret; returns new secrets to caller
    secrets.py                      # DELETED

services/                           # risk_module only; NEVER synced
  credentials/
    __init__.py                     # exports public API
    cipher.py                       # encrypt/decrypt module functions, lazy init
    plaid.py                        # store/get/delete Plaid tokens
    snaptrade.py                    # store/get/delete SnapTrade secrets (keyed user_id)
    anthropic.py                    # moved from services/anthropic_credential_store.py
  account_registry.py               # extended to own provider_items+data_sources atomic writes
  anthropic_credential_store.py     # DELETED

scripts/
  migrate_credentials_to_kms.py     # one-shot; archived after run
```

### Cipher with lazy init + encryption context

```python
# services/credentials/cipher.py
import os
import boto3
from botocore.config import Config
from typing import Mapping

_client = None
_key_id = None
_BOTO_CONFIG = Config(retries={"max_attempts": 5, "mode": "standard"})

def _kms_client():
    global _client
    if _client is None:
        region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        _client = boto3.client("kms", region_name=region, config=_BOTO_CONFIG)
    return _client

def _key_arn() -> str:
    global _key_id
    if _key_id is None:
        _key_id = os.environ["KMS_CREDENTIAL_KEY_ARN"]
    return _key_id

def _normalize_context(ctx: Mapping[str, str]) -> dict[str, str]:
    if not ctx:
        raise ValueError("encryption_context must be non-empty")
    if "app" in ctx:
        raise ValueError("'app' is a reserved encryption-context key")
    # Apply baseline LAST so caller cannot override
    return {**{k: str(v) for k, v in ctx.items()}, "app": "risk_module"}

def encrypt(plaintext: str, encryption_context: Mapping[str, str]) -> bytes:
    if not plaintext:
        raise ValueError("plaintext must be non-empty")
    ctx = _normalize_context(encryption_context)
    resp = _kms_client().encrypt(
        KeyId=_key_arn(),
        Plaintext=plaintext.encode("utf-8"),
        EncryptionContext=ctx,
    )
    return resp["CiphertextBlob"]

def decrypt(ciphertext: bytes, encryption_context: Mapping[str, str]) -> str:
    if not ciphertext:
        raise ValueError("ciphertext must be non-empty")
    ctx = _normalize_context(encryption_context)
    resp = _kms_client().decrypt(CiphertextBlob=ciphertext, EncryptionContext=ctx)
    return resp["Plaintext"].decode("utf-8")
```

**Why baseline applied last + reject `app` in caller context**: prevents callers from accidentally or maliciously overriding `app="risk_module"` and decrypting with a different scope.

**Why encryption context**: prevents ciphertext-swap. KMS rejects decrypt unless caller provides the same context used at encrypt.

### Encryption context per credential

| Credential | Caller context (after baseline `app="risk_module"`) |
|---|---|
| Plaid | `{"user_id": "<id>", "credential_type": "plaid_access_token", "item_id": "<plaid_item_id>"}` |
| SnapTrade | `{"user_id": "<id>", "credential_type": "snaptrade_user_secret"}` |
| Anthropic | `{"user_id": "<id>", "credential_type": "anthropic_api_key"}` |

### Schema migrations

```sql
-- database/migrations/20260430_credentials_kms_migration.sql
ALTER TABLE provider_items
    ADD COLUMN access_token_enc BYTEA,
    ADD COLUMN token_updated_at TIMESTAMPTZ;

ALTER TABLE users
    ADD COLUMN snaptrade_user_secret_enc BYTEA,
    ADD COLUMN snaptrade_credential_updated_at TIMESTAMPTZ,
    ADD COLUMN anthropic_api_key_kms_enc BYTEA;
```

```sql
-- database/migrations/20260501_drop_legacy_anthropic_columns.sql
-- Run AFTER scripts/migrate_credentials_to_kms.py succeeds AND new code is verified
ALTER TABLE users
    DROP COLUMN anthropic_api_key_secret_ref,
    DROP COLUMN anthropic_api_key_enc;
```

### `provider_items` ↔ `data_sources` semantics

**Honest reading of current code** (`routes/plaid.py:949-967`):

```python
store_plaid_token(...)             # writes to AWS Secrets Manager today
_store_plaid_item_mapping(...)     # writes to provider_items
AccountRegistry(user_id).ensure_data_source(...)   # writes to data_sources
```

These are **three separate writes**, not transactional. v3's "single transaction" rule was aspirational.

**v6 plan** (semantics corrected per R5): extend `services/account_registry.AccountRegistry` with three explicit lifecycle helpers, each wrapping its writes in a single DB transaction:

1. **`register_plaid_item(user_id, item_id, institution_name, access_token)`** — connect path. Encrypts and writes `provider_items.access_token_enc` + `token_updated_at`, writes `provider_items` mapping, ensures `data_sources` row with `status='active'`, `user_deactivated=FALSE`. Used by OAuth callback (`routes/plaid.py:949-967`) and reauth completion.

2. **`mark_plaid_item_inactive(user_id, item_ids_to_keep_active)`** — reconciliation sweep (matches today's `routes/plaid.py:372-379`). For Plaid items present in `provider_items` but NOT in the caller-supplied `item_ids_to_keep_active` list, sets `data_sources.status='disconnected'`, `user_deactivated=TRUE`. **Keeps** `provider_items.access_token_enc` populated (the user can reactivate via reconnect). This is NOT user-initiated; it's a reconciliation result when the live Plaid connection list doesn't match local state.

3. **`revoke_plaid_item(user_id, item_id=None)`** — explicit revoke / Plaid `/item/remove` follow-up. Used by:
   - `routes/plaid.py:1587 disconnect_plaid_connection` (per-item revoke; user clicks "Disconnect" in UI) — `revoke_plaid_item(user_id, item_id)`. Replaces the current code that pulls the access_token from Secrets Manager, calls `remove_plaid_connection`, then deletes the secret + provider_item separately.
   - `routes/plaid.py:1795 delete_plaid_user` (full user wipe) — `revoke_plaid_item(user_id, item_id=None)` removes all Plaid items.

   Internally: calls brokerage's `remove_plaid_connection(access_token)` to revoke at Plaid's side, then in the same DB transaction deletes the `provider_items` row(s) (including the encrypted token) and the matching `data_sources` row(s).

   **UI/API contract note** (Codex R6 clarification): the settings UI today calls disconnect with `institution_slug` (`frontend/packages/ui/src/components/settings/AccountConnectionsContainer.tsx`), and the route at `routes/plaid.py:1587` (`/connections/{institution_slug}`) accepts a slug. `revoke_plaid_item` takes `item_id`. The route layer must resolve `institution_slug → item_id` (via `provider_items` lookup) before calling the helper, or the API contract changes to disconnect by item_id. Recommend slug→item_id resolution at the route layer to preserve the current UI contract.

OAuth callback at `routes/plaid.py:949` switches to `register_plaid_item`. The reconciliation path at `routes/plaid.py:372-379` switches to `mark_plaid_item_inactive`. The disconnect endpoint at `routes/plaid.py:1587` switches to `revoke_plaid_item(user_id, item_id)`. The hard-delete endpoint at `routes/plaid.py:1795` switches to `revoke_plaid_item(user_id, item_id=None)`.

**Lifecycle field semantics** (verified against `routes/plaid.py:371-379`, `inputs/database_client.py:1128-1134`):

| State | `data_sources.status` | `data_sources.user_deactivated` | `provider_items.access_token_enc` |
|---|---|---|---|
| Active | `'active'` | `FALSE` | populated |
| Reconciliation-inactive (sweep found item missing from live Plaid list) | `'disconnected'` | `TRUE` | populated (preserved for reactivation) |
| User-revoked / hard delete (user clicks Disconnect, or `delete_plaid_user`) | row deleted | row deleted | row deleted |
| Reauth in progress | `'active'` | `FALSE` | populated; `token_updated_at` bumps on token swap |

**Read gate**: services check `data_sources.status='active' AND user_deactivated=FALSE` before fetching token from `provider_items`. Disconnected items are skipped during sync.

### Brokerage refactor: dependency inversion

Today, `brokerage/snaptrade/_shared.py:158-167`:

```python
def _get_snaptrade_identity(user_email: str) -> tuple[str, str]:
    from brokerage.snaptrade.secrets import get_snaptrade_user_secret
    from brokerage.snaptrade.users import get_snaptrade_user_id_from_email
    user_id = get_snaptrade_user_id_from_email(user_email)
    user_secret = get_snaptrade_user_secret(user_email)  # AWS call inside brokerage
    if not user_secret:
        raise ValueError(f"No SnapTrade user secret found for {user_email}")
    return user_id, user_secret
```

After:
```python
def _get_snaptrade_identity(user_email: str, user_secret: str) -> tuple[str, str]:
    from brokerage.snaptrade.users import get_snaptrade_user_id_from_email
    if not user_secret:
        raise ValueError(f"SnapTrade user_secret required for {user_email}")
    user_id = get_snaptrade_user_id_from_email(user_email)
    return user_id, user_secret
```

**`_call_with_secret_rotation` exact signature (post-refactor):**

```python
def _call_with_secret_rotation(
    user_email: str,
    user_secret: str,
    operation: Callable[[str, str], Any],   # invoked as operation(snaptrade_user_id, secret)
    *,
    on_secret_rotated: Callable[[str], None] | None = None,
    refresh_secret: Callable[[], str | None] | None = None,
    operation_name: str | None = None,
    user_id: int | None = None,             # budget user_id, for cost tagging
) -> Any:
    """
    Run `operation(snaptrade_user_id, user_secret)`. On SnapTrade UNAUTHORIZED:
      1. Acquire `get_snaptrade_rotation_lock(user_email)` (existing helper).
      2. Inside the lock, call `refresh_secret()` if provided — handles the race
         where another thread already rotated.
      3. If refresh returned a new secret, retry operation with it; on success
         invoke `on_secret_rotated(new_secret)` so the caller persists.
      4. If refresh returned None, attempt full rotation via
         `rotate_snaptrade_user_secret(user_email, user_secret)`. On success
         invoke `on_secret_rotated(new_secret)`, then retry.

    Brokerage NEVER persists. `on_secret_rotated` is the caller's hook to
    write the new secret to its credential store.
    """
```

Risk_module callers wire:
```python
def on_secret_rotated(new_secret: str) -> None:
    services.credentials.snaptrade.store_user_secret(user_id, new_secret, db)

def refresh_secret() -> str | None:
    return services.credentials.snaptrade.get_user_secret(user_id, db)

response = _call_with_secret_rotation(
    user_email=user_email,
    user_secret=current_secret,
    operation=lambda uid, sec: place_snaptrade_checked_order(uid, sec, ...),
    on_secret_rotated=on_secret_rotated,
    refresh_secret=refresh_secret,
)
```

**`rotate_snaptrade_user_secret` exact signature:**

```python
def rotate_snaptrade_user_secret(
    user_email: str,
    current_secret: str,
) -> str:
    """Calls SnapTrade reset-secret API with current_secret, returns new_secret.
    Brokerage does NOT persist; caller handles via on_secret_rotated callback in
    _call_with_secret_rotation, or directly persists the returned value."""
```

**`recover_snaptrade_auth` signature:**

```python
def recover_snaptrade_auth(
    user_email: str,
    current_secret: str,
    budget_user_id: int = 0,
) -> tuple[str, str]:
    """Returns (new_secret, recovery_method). Caller persists new_secret."""
```

**Race semantics**: `get_snaptrade_rotation_lock(user_email)` is a per-email re-entrant lock (existing helper at `brokerage/snaptrade/recovery.py:38`). `_call_with_secret_rotation` acquires it before checking `refresh_secret()`. If another thread rotated and wrote the new secret to DB, `refresh_secret()` returns the new value; we retry with that. Avoids double-rotation.

### IAM policy

App's IAM role:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "CredentialsKMSAccess",
    "Effect": "Allow",
    "Action": ["kms:Encrypt", "kms:Decrypt"],
    "Resource": "arn:aws:kms:us-east-1:ACCOUNT_ID:key/KEY_ID"
  }]
}
```

Migration-script principal additionally needs `secretsmanager:GetSecretValue` and `secretsmanager:DeleteSecret` (one-shot; revoked after migration completes).

### KMS outage runbook

| Operation | Behavior |
|---|---|
| `encrypt` (write) | 503 to user; do not write half-encrypted state |
| `decrypt` (read) | "credential temporarily unavailable" to caller; **do not** mark connection inactive, **do not** delete cached positions |
| Periodic syncs | Skip affected user/item, log warning, continue |

Throttling: boto3 retry config (`max_attempts=5`); migration script concurrency=1.

CMK rotation across long jobs: KMS retains old key material for old ciphertexts; no special handling.

### Dev/test story

- Dev: real KMS calls against `alias/risk-module-credentials-dev` ($1/mo).
- Unit tests: `moto[kms]`.
- No Fernet fallback (eliminating that env-var key is a goal).

## Implementation steps (sequenced)

### Phase 1 — Foundation

1. **Provision KMS CMKs** (manual AWS Console):
   - Symmetric CMK in `us-east-1`, alias `alias/risk-module-credentials-dev`. Annual rotation enabled.
   - Repeat for `alias/risk-module-credentials-prod` (provision now to validate IAM path).
   - Key policy: root + app's IAM principal `kms:Encrypt`/`kms:Decrypt`. Migration-script principal additionally allowed `secretsmanager:GetSecretValue`/`DeleteSecret` on the 3 existing secrets.
   - Set `KMS_CREDENTIAL_KEY_ARN` in `.env`.

2. **Create `services/credentials/cipher.py`** per code sample above.

3. **Add `moto[kms]` to `requirements-dev.txt`**; regenerate `requirements.lock` / `uv.lock`.

4. **Create both schema migrations** (`20260430_credentials_kms_migration.sql` and `20260501_drop_legacy_anthropic_columns.sql`). Apply only the first to dev DB now; second runs after Phase 5.

### Phase 2 — Credential store modules

5. **`services/credentials/plaid.py`** — public API:
   - `store_plaid_token(user_id, item_id, institution_name, access_token, db)`
   - `get_plaid_token_by_item_id(user_id, item_id, db) → str | None`
   - `get_plaid_token(user_id, institution_name, db) → dict | None` (back-compat shape)
   - `delete_plaid_token(user_id, item_id, db)`
   - `delete_plaid_user_tokens(user_id, db)` — bulk
   - `list_user_tokens(user_id, db) → list[dict]` returning `[{"item_id", "institution_name", "token_updated_at"}, ...]` (does not decrypt)

6. **`services/credentials/snaptrade.py`**:
   - `store_user_secret(user_id, user_secret, db)`
   - `get_user_secret(user_id, db) → str | None`
   - `delete_user_secret(user_id, db)`
   - **No email shim**. Callers resolve via `utils.user_resolution.resolve_user_id(email)` at the boundary.

7. **Move `services/anthropic_credential_store.py` → `services/credentials/anthropic.py`**:
   - Delete `boto3.secretsmanager`, all Fernet code, `ALLOW_DB_CRED_FALLBACK`.
   - `store_user_anthropic_key`: encrypt → `users.anthropic_api_key_kms_enc`. Set `source='byok'`, bump `updated_at`.
   - `get_user_anthropic_key`: read `_kms_enc`, decrypt. Returns None if column NULL.
   - `delete_user_anthropic_key`: NULL `_kms_enc`, set `source='none'`.
   - Rename test file: `tests/services/test_anthropic_credential_store.py` → `tests/services/credentials/test_anthropic.py`. Use `moto[kms]`.

8. **Extend `services/account_registry.py`**: add `register_plaid_item(user_id, item_id, institution_name, access_token)` that wraps the three writes (encrypt+store token, write provider_items, write data_sources) in one transaction.

### Phase 3 — Brokerage refactor

9. **Delete files**:
   - `brokerage/plaid/secrets.py`
   - `brokerage/snaptrade/secrets.py`

10. **Refactor brokerage SnapTrade** — every call site listed in Appendix A.2:

    | File | Lines | Change |
    |---|---|---|
    | `brokerage/snaptrade/_shared.py` | 158-167 | `_get_snaptrade_identity(user_email, user_secret)` — accept user_secret |
    | `brokerage/snaptrade/_shared.py` | 186 | `__all__` unchanged |
    | `brokerage/snaptrade/trading.py` | 38, 60, 138, 175, 248, 266, 293, 312, 340, 358 | every callsite of `_get_snaptrade_identity(user_email)` becomes `(user_email, user_secret)`; trading functions accept `user_secret` parameter from caller |
    | `brokerage/snaptrade/connections.py` | 86, 184, 322 | callers pass user_secret |
    | `brokerage/snaptrade/connections.py` | 113, 341 | `_call_with_secret_rotation` invocation receives new secret-rotation contract |
    | `brokerage/snaptrade/client.py` | 75 (def), 84, 96, 530, 556, 586 | `_call_with_secret_rotation` accepts `user_secret` + `on_secret_rotated` callback; wrappers updated |
    | `brokerage/snaptrade/client.py` | 18, 42 | drop `get_snaptrade_app_credentials` import + fallback; require env vars |
    | `brokerage/snaptrade/adapter.py` | 29, 423 | drop import; `SnapTradeBrokerAdapter.__init__` accepts user_secret |
    | `brokerage/snaptrade/users.py` | 15-17, 44, 52, 94, 99 | drop secrets imports; `register_snaptrade_user` returns newly-issued secret to caller; `delete_snaptrade_user` accepts user_secret |
    | `brokerage/snaptrade/recovery.py` | 21-23, 75, 104, 145, 197, 237 | drop secrets imports; rotation/recovery functions accept `user_secret` and `on_secret_rotated` callback |
    | `brokerage/snaptrade/__init__.py` | 28, 55 | drop `get_snaptrade_user_secret` re-export |

11. **Refactor brokerage Plaid**:

    | File | Lines | Change |
    |---|---|---|
    | `brokerage/plaid/connections.py` | 16, 84, 114 | drop `from brokerage.plaid.secrets import list_user_tokens` and direct `boto3.client("secretsmanager")` call; functions accept `access_token` (and item list) from callers |
    | `brokerage/plaid/__init__.py` | 14-20, 26, 33-38 | drop `delete_plaid_user_tokens`/`get_plaid_token`/`get_plaid_token_by_item_id`/`list_user_tokens`/`store_plaid_token` imports + `__all__` entries |

### Phase 4 — Risk_module call-site updates

**See Appendix A** for the verbatim grep-sourced inventory of all 60+ call sites.

For each entry in Appendix A.1 (Plaid wrapped), A.2 (SnapTrade wrapped), A.3 (direct boto3), A.4 (Anthropic):

- Switch import from `brokerage.{plaid,snaptrade}` or direct `boto3.client("secretsmanager")` to `services.credentials.*`.
- For SnapTrade: at the route/MCP/script boundary, call `utils.user_resolution.resolve_user_id(user_email)` to get `user_id`, then call `services.credentials.snaptrade.get_user_secret(user_id, db)`.
- For Plaid: same pattern — resolve email→user_id at boundary, then call `services.credentials.plaid.*`.
- Anthropic: change `from services import anthropic_credential_store` → `from services.credentials import anthropic`. All `anthropic_credential_store.X` → `anthropic.X`.

**OAuth callback transaction fix** (`routes/plaid.py:949-967`): switch from three separate calls to single `AccountRegistry.register_plaid_item(user_id, item_id, institution_name, access_token)`.

**Test files** (Appendix A.5): update mock targets from `brokerage.plaid.*` / `brokerage.snaptrade.*` to `services.credentials.*`. Some tests use `monkeypatch.setattr` on imports — those targets change but the patching pattern stays.

**Bug-fix side effect**: Plaid doubled-write at `mcp_tools/connections.py:577` (`docs/TODO.md:1082`) goes away naturally. Remove the TODO entry.

### Phase 5 — Migration & cleanup (cutover)

12. **Cutover sequence (uses repo migration runner)**:

    Migration runner is `scripts/run_migrations.py` — tracks applied filenames in the `_migrations` table and applies every `database/migrations/*.sql` not already in that table. Direct `psql -f` is wrong because it bypasses tracking and can cause re-runs on next deploy.

    **Before cutover**: only the additive migration `20260430_credentials_kms_migration.sql` is in `database/migrations/`. The cleanup migration `20260501_drop_legacy_anthropic_columns.sql` is staged outside the directory (e.g., in `database/migrations/_pending/`) until verification succeeds.

    ```
    a. Apply schema migration via runner:
       python scripts/run_migrations.py
       # Records 20260430_credentials_kms_migration.sql in _migrations.

    b. Stop dev backend:
       services-mcp service_stop("risk_module")
       services-mcp service_status("risk_module")   # verify stopped

    c. Run credential migration (dry-run, then real):
       python scripts/migrate_credentials_to_kms.py --dry-run
       python scripts/migrate_credentials_to_kms.py

    d. Deploy/sync new code (in dev: pull latest source; in prod: deploy artifact).

    e. Start backend:
       services-mcp service_start("risk_module")
       services-mcp service_status("risk_module")   # verify running

    f. End-to-end smoke:
       - Anthropic: send a chat message; verify BYOK key used.
       - Plaid: trigger position sync; verify Plaid API call succeeds.
       - SnapTrade: trigger account list; verify SnapTrade API call succeeds.
       - aws secretsmanager list-secrets --region us-east-1   # verify zero risk_module secrets

    g. Apply cleanup migration AFTER verification:
       mv database/migrations/_pending/20260501_drop_legacy_anthropic_columns.sql \
          database/migrations/
       python scripts/run_migrations.py
       # Records 20260501_drop_legacy_anthropic_columns.sql in _migrations.
    ```

    Old code never runs concurrently with migration. No transient half-state. Migration tracking stays consistent with the repo's deploy flow (`scripts/deploy.sh:30-31` re-runs `scripts/run_migrations.py` and skips already-applied entries).

13. **Migration script state machine** (`scripts/migrate_credentials_to_kms.py`):

    ```python
    from enum import Enum

    class DbState(Enum):
        MISSING = "missing"                  # column NULL or row absent
        PRESENT_VERIFIED = "verified"        # decrypts to a sane plaintext via current KMS+context
        PRESENT_DECRYPT_ERROR = "decrypt_error"  # ciphertext present but decrypt raises (corrupt or context mismatch)
        PRESENT_KMS_ERROR = "kms_error"      # KMS itself unavailable; transient

    class AwsState(Enum):
        PRESENT = "present"
        MISSING = "missing"

    def migrate_one(secret_name, db_check_fn, db_write_fn, db_decrypt_fn,
                    encryption_context, dry_run):
        db_state = classify_db(db_decrypt_fn)   # one of the DbState values
        aws_state = classify_aws(secret_name)   # PRESENT or MISSING

        if db_state is PRESENT_KMS_ERROR:
            raise RuntimeError(f"{secret_name}: KMS unavailable — retry later")

        if db_state is PRESENT_VERIFIED and aws_state is MISSING:
            log("already migrated", secret_name); return

        if db_state is PRESENT_VERIFIED and aws_state is PRESENT:
            # Crashed between DB commit and AWS delete in a prior run.
            # Verify plaintexts match, then complete the AWS delete.
            aws_plain = read_aws(secret_name)
            db_plain = db_decrypt_fn()
            if aws_plain != db_plain:
                raise RuntimeError(
                    f"{secret_name}: DB and AWS plaintexts disagree — manual review required"
                )
            if dry_run: log("would delete AWS secret", secret_name); return
            force_delete_aws(secret_name); return

        if db_state is PRESENT_DECRYPT_ERROR:
            raise RuntimeError(
                f"{secret_name}: DB ciphertext exists but does not decrypt — "
                "manual review required (corrupt / context mismatch / wrong CMK)"
            )

        # db_state is MISSING — full migration
        if aws_state is MISSING:
            raise RuntimeError(f"{secret_name}: nothing in DB or AWS to migrate")
        plaintext = read_aws(secret_name)
        if dry_run: log("would migrate", secret_name); return

        ciphertext = cipher.encrypt(plaintext, encryption_context)
        with db.transaction():
            db_write_fn(ciphertext)
            db.commit()

        # Round-trip verify
        if db_decrypt_fn() != plaintext:
            raise RuntimeError(
                f"{secret_name}: round-trip mismatch — aborting before AWS delete"
            )

        force_delete_aws(secret_name)
        log("migrated", secret_name)
    ```

    Concurrency: 1 (sequential, only 3 secrets). Dry-run flag prints plan without writes.

14. **Drop env vars** from `.env` and `.env.example`:
    - `ANTHROPIC_CRED_ENCRYPTION_KEY`
    - `ALLOW_DB_CRED_FALLBACK`

15. **Final grep sweep** — must return zero hits in `services/`, `brokerage/`, `routes/`, `mcp_tools/`, `scripts/`, `trading_analysis/`, `tests/` (CHANGELOG/_archive OK):
    - `secretsmanager`
    - `boto3.client("secretsmanager")`
    - `ANTHROPIC_CRED_ENCRYPTION_KEY`
    - `ALLOW_DB_CRED_FALLBACK`
    - `anthropic_api_key_secret_ref`
    - `from brokerage.plaid.secrets`
    - `from brokerage.snaptrade.secrets`

### Phase 6 — Documentation + brokerage-connect-dist sync

16. **Active doc updates**:

    | File | Lines / Sections | Change |
    |---|---|---|
    | `docs/ops/GATEWAY_MULTI_USER_ACTIVATION.md` | 35, 47, 57, 195, 229 | Replace AWS Secrets Manager / `ALLOW_DB_CRED_FALLBACK` / Fernet refs with KMS architecture |
    | `docs/deployment/MULTI_USER_DEPLOYMENT_PLAN.md` | 409, 1233 | Update env-var section + IAM policy section |
    | `docs/deployment/AWS_SECRETS_MANAGER_MIGRATION_GUIDE.md` | top | Add deprecation header pointing at new doc |
    | `docs/guides/BROKERAGE_ADMIN.md` | 31, 84 | Update credential storage references to KMS+DB |
    | `routes/plaid.py` | 643, 925, 1251, 1262, 1276, 1597, 1652 | Update docstring/comment text (these feed OpenAPI) |
    | `routes/snaptrade.py` | 76, 99, 646, 671, 1395 | Same — docstrings appearing in OpenAPI |
    | `services/plaid_portfolio_loader.py` | 105, 115 | Update docstring |
    | `trading_analysis/README.md` | 105 | One-line update |
    | `requirements.txt` | 58 | Comment changes from "Secrets Manager…" to "KMS for credential encryption" |
    | `docs/TODO.md` | 1070, 1075, 1082, 1094 | Remove obsolete entries |
    | `frontend/openapi-schema.json`, `frontend/packages/chassis/src/types/api-generated.ts` | (regenerated) | Re-run OpenAPI codegen after route docstring updates |

17. **New doc**: `docs/deployment/CREDENTIALS_KMS_ARCHITECTURE.md` covering architecture, IAM, ops runbook, key rotation, encryption context, dev/test setup.

18. **Sync `brokerage/` to `brokerage-connect-dist`**:
    - Run `scripts/sync_brokerage_connect.sh`.
    - Bump `brokerage-connect-dist/pyproject.toml` version: `0.2.2` → `0.3.0` (breaking signatures).
    - Update README/CHANGELOG with migration notes (new signatures for `SnapTradeBrokerAdapter`, `_call_with_secret_rotation`, `register_snaptrade_user`, etc.).
    - **Drop `boto3` / `botocore` from BOTH `brokerage/pyproject.toml` (source) and `brokerage-connect-dist/pyproject.toml`** — verified via final-grep that brokerage no longer imports `boto3`. KMS lives in risk_module's `services/credentials/cipher.py`, not in the standalone brokerage package.

      Source edit: `brokerage/pyproject.toml:17` (snaptrade extra) drops `"boto3>=1.42,<2", "botocore>=1.42,<2"`. Same on `:19` (plaid extra). Note that `scripts/sync_brokerage_connect.sh:31` excludes `pyproject.toml` from the sync, so the dist's `pyproject.toml` must be edited separately (or the sync script extended). Verified by greppable `grep -n "boto" brokerage/pyproject.toml` → 0 hits.
    - **Verified standalone-import smoke** (using actual exports):
      ```bash
      cd /Users/henrychien/Documents/Jupyter/brokerage-connect-dist
      python -c "from brokerage.plaid import fetch_plaid_holdings, exchange_public_token; \
                 from brokerage.snaptrade import SnapTradeBrokerAdapter, list_user_accounts"
      ```
      Must succeed without `risk_module` on `PYTHONPATH`.
    - Check external consumers (per `feedback_dist_sync_after_cross_repo_prs`): does anyone outside risk_module + brokerage-connect-dist import this package?

## Test plan

- **Unit tests for cipher** (`moto[kms]`): encrypt round-trip; decrypt with wrong context fails; empty plaintext rejected; lazy init works without `KMS_CREDENTIAL_KEY_ARN`; rejects caller-supplied `app` key.
- **Unit tests per credential module**: store→read→delete round-trip; idempotent store; get on missing returns None; encryption context bound correctly.
- **Migration script tests**: each `DbState` × `AwsState` combination produces correct action; dry-run is read-only; crash-recovery branch (DB committed but AWS still present) completes correctly; plaintext-mismatch detection aborts loudly.
- **`AccountRegistry.register_plaid_item` test**: simulates partial failure mid-transaction; verifies all-or-nothing.
- **Lifecycle tests** for `provider_items` ↔ `data_sources`: connect → disconnect → reconnect → revoke. Verify state transitions match table above.
- **Brokerage standalone smoke**: imports succeed using the real exports listed above.
- **End-to-end smoke** post-migration: Anthropic chat, Plaid sync, SnapTrade list.

## Rollback plan

- **Schema rollback**: `DROP COLUMN` for new BYTEA columns; restore `anthropic_api_key_secret_ref` from pre-migration `pg_dump`.
- **Code rollback**: revert merge commit(s).
- **Data rollback**: AWS force-delete is irreversible. User re-links and re-enters Anthropic key. Acceptable pre-deploy.
- **Mid-migration abort**: script aborts before AWS delete on any verify failure. AWS state intact; fix and re-run.

## Open questions

1. **Production CMK provisioning**: provision now or at deploy? Recommend now ($1/month, validates IAM path).
2. **SnapTrade external user_id (email-derived) mutability** (`brokerage/snaptrade/users.py:21`): pre-existing concern; not solved by this plan. Separate plan if it surfaces.
3. **External brokerage-connect consumers**: any imports outside risk_module + brokerage-connect-dist? Verify before tagging v0.3.0.
4. **CloudTrail enablement**: verify on; estimate cost at scale (separate plan if non-trivial).

## Decisions log (cumulative)

- **2026-04-30** — KMS direct Encrypt/Decrypt; per-home-table columns; clean cutover; no dual-write.
- **2026-04-30** (v2) — Storage moves from `brokerage/` to `services/credentials/` (preserves brokerage-connect-dist boundary).
- **2026-04-30** (v2) — Anthropic schema staged (new BYTEA column).
- **2026-04-30** (v2) — SnapTrade keying: `users.id`.
- **2026-04-30** (v2) — KMS encryption context bound; `app=risk_module` baseline added in v3.
- **2026-04-30** (v3) — Cipher: module functions; SnapTrade email shim removed; lifecycle vocabulary corrected.
- **2026-04-30** (v3) — Migration idempotency: separate DB-state and AWS-state checks.
- **2026-04-30** (v4) — Encryption context baseline applied last; `app` reserved key.
- **2026-04-30** (v4) — Migration state enum: `DB_MISSING/PRESENT_VERIFIED/PRESENT_DECRYPT_ERROR/PRESENT_KMS_ERROR` × `AWS_PRESENT/MISSING`.
- **2026-04-30** (v4) — Cutover sequence: stop backend → migrate → deploy → start. No concurrent old/new code.
- **2026-04-30** (v4) — Email→user_id resolver: `utils.user_resolution.resolve_user_id` (named explicitly).
- **2026-04-30** (v4) — `provider_items` + `data_sources` atomic write owned by `AccountRegistry.register_plaid_item` (not raw SQL in routes).
- **2026-04-30** (v4) — Brokerage smoke uses real exports: `SnapTradeBrokerAdapter`, `fetch_plaid_holdings`, `exchange_public_token`, `list_user_accounts`.

## Success criteria

- ✅ Zero risk_module-owned secrets in AWS Secrets Manager.
- ✅ All three credential types readable end-to-end via KMS path.
- ✅ Final grep sweep returns zero hits for the listed patterns in code dirs.
- ✅ `brokerage/` package imports cleanly without risk_module on path (smoke uses real exports).
- ✅ Plaid doubled-write bug resolved.
- ✅ All Codex R3 P0/P1 items RESOLVED.
- ✅ Codex R4 PASS.

---

# Appendix A — Verbatim call-site inventory (sourced from grep)

> All entries below are paste-from-grep, not memory. Implementer must update each site.

## A.1 Plaid wrapped calls (route through `brokerage.plaid` re-exports)

```
brokerage/plaid/connections.py:16:from brokerage.plaid.secrets import list_user_tokens
brokerage/plaid/connections.py:84:    secrets = list_user_tokens(user_id, region_name)
mcp_tools/connection_status.py:10:from brokerage.plaid import list_user_tokens
mcp_tools/connection_status.py:56:    token_paths = list_user_tokens(user_email, region_name)
mcp_tools/connections.py:14:    list_user_tokens,
mcp_tools/connections.py:16:    store_plaid_token,
mcp_tools/connections.py:566:        existing_tokens = list_user_tokens(
mcp_tools/connections.py:577:        store_plaid_token(
routes/onboarding.py:17:from brokerage.plaid import list_user_tokens
routes/onboarding.py:83:        token_paths = list_user_tokens(user["email"], region_name=AWS_DEFAULT_REGION)
routes/plaid.py:138:    delete_plaid_user_tokens,
routes/plaid.py:141:    get_plaid_token_by_item_id,
routes/plaid.py:142:    list_user_tokens,
routes/plaid.py:144:    store_plaid_token,
routes/plaid.py:308:        token_paths = list_user_tokens(user_email, region_name=AWS_DEFAULT_REGION)
routes/plaid.py:660:        token_paths = list_user_tokens(user['email'], region_name=AWS_DEFAULT_REGION)
routes/plaid.py:818:        token_data = get_plaid_token_by_item_id(...)
routes/plaid.py:949:        store_plaid_token(...)
routes/plaid.py:1277:        user_tokens = list_user_tokens(user['email'], region_name=AWS_DEFAULT_REGION)
routes/plaid.py:1720:                    remaining_tokens = list_user_tokens(user['email'], region_name=AWS_DEFAULT_REGION)
routes/plaid.py:1795:        delete_plaid_user_tokens(user['email'], AWS_DEFAULT_REGION)
scripts/diagnose_plaid_balances.py:26:    get_plaid_token,
scripts/diagnose_plaid_balances.py:27:    list_user_tokens,
scripts/diagnose_plaid_balances.py:48:    token_paths = list_user_tokens(args.user_email, region_name=AWS_REGION)
scripts/diagnose_plaid_balances.py:62:            token_data = get_plaid_token(...)
scripts/explore_transactions.py:121:        get_plaid_token,
scripts/explore_transactions.py:122:        list_user_tokens,
scripts/explore_transactions.py:132:    all_tokens = list_user_tokens(user_email, region)
scripts/explore_transactions.py:154:            token_data = get_plaid_token(...)
scripts/plaid_reauth.py:19:    get_plaid_token_by_item_id,
scripts/plaid_reauth.py:20:    list_user_tokens,
scripts/plaid_reauth.py:41:    token_paths = list_user_tokens(user_email, region_name=region_name)
scripts/plaid_reauth.py:126:    token_data = get_plaid_token_by_item_id(user_email, item_id, region_name=region_name)
scripts/run_plaid.py:21:    delete_plaid_user_tokens,
scripts/run_plaid.py:22:    list_user_tokens,
scripts/run_plaid.py:31:    token_paths = list_user_tokens(args.user_email, region_name=AWS_REGION)
scripts/run_plaid.py:52:    token_paths = list_user_tokens(args.user_email, region_name=AWS_REGION)
scripts/run_plaid.py:79:        remove_plaid_institution(...)      # CLI disconnect path
scripts/run_plaid.py:106:    success = delete_plaid_user_tokens(args.user_email, region_name=AWS_REGION)
services/plaid_portfolio_loader.py:8:from brokerage.plaid import fetch_plaid_holdings, get_plaid_token, list_user_tokens
services/plaid_portfolio_loader.py:133:    all_tokens = list_user_tokens(user_id, region_name)
services/plaid_portfolio_loader.py:137:        token_data = get_plaid_token(...)
trading_analysis/data_fetcher.py:418:        get_plaid_token,
trading_analysis/data_fetcher.py:419:        list_user_tokens,
trading_analysis/data_fetcher.py:422:    all_tokens = list_user_tokens(user_email, region)
trading_analysis/data_fetcher.py:445:        token_data = get_plaid_token(...)
```

## A.2 SnapTrade wrapped calls + brokerage-internal usage of `_get_snaptrade_identity` / `_call_with_secret_rotation`

```
brokerage/snaptrade/_shared.py:158:def _get_snaptrade_identity(user_email: str) -> tuple[str, str]:
brokerage/snaptrade/_shared.py:160:    from brokerage.snaptrade.secrets import get_snaptrade_user_secret
brokerage/snaptrade/_shared.py:164:    user_secret = get_snaptrade_user_secret(user_email)
brokerage/snaptrade/adapter.py:29:from brokerage.snaptrade.secrets import get_snaptrade_user_secret
brokerage/snaptrade/adapter.py:423:        user_secret = get_snaptrade_user_secret(self._user_email)
brokerage/snaptrade/client.py:14:    _get_snaptrade_identity,
brokerage/snaptrade/client.py:18:from brokerage.snaptrade.secrets import get_snaptrade_app_credentials
brokerage/snaptrade/client.py:42:        app_credentials = get_snaptrade_app_credentials(region_name)
brokerage/snaptrade/client.py:75:def _call_with_secret_rotation(
brokerage/snaptrade/client.py:84:    user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/client.py:96:        user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/client.py:530:    response = _call_with_secret_rotation(...)
brokerage/snaptrade/client.py:556:    response = _call_with_secret_rotation(...)
brokerage/snaptrade/client.py:586:    response = _call_with_secret_rotation(...)
brokerage/snaptrade/connections.py:12:    _get_snaptrade_identity,
brokerage/snaptrade/connections.py:15:    _call_with_secret_rotation,
brokerage/snaptrade/connections.py:86:        snaptrade_user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/connections.py:113:    response = _call_with_secret_rotation(...)
brokerage/snaptrade/connections.py:184:        _user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/connections.py:322:    user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/connections.py:341:        _call_with_secret_rotation(...)
brokerage/snaptrade/recovery.py:21:    delete_snaptrade_user_secret,
brokerage/snaptrade/recovery.py:22:    get_snaptrade_user_secret,
brokerage/snaptrade/recovery.py:23:    store_snaptrade_user_secret,
brokerage/snaptrade/recovery.py:75:            store_snaptrade_user_secret(user_email, user_secret)
brokerage/snaptrade/recovery.py:104:    user_secret = get_snaptrade_user_secret(user_email)
brokerage/snaptrade/recovery.py:145:        current_secret = get_snaptrade_user_secret(user_email)
brokerage/snaptrade/recovery.py:197:    delete_snaptrade_user_secret(user_email, force=True)
brokerage/snaptrade/recovery.py:237:        latest_secret = get_snaptrade_user_secret(user_email)
brokerage/snaptrade/trading.py:12:    _get_snaptrade_identity,
brokerage/snaptrade/trading.py:38:        user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/trading.py:60:            user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/trading.py:138:        user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/trading.py:175:            user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/trading.py:248:        user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/trading.py:266:            user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/trading.py:293:        user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/trading.py:312:            user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/trading.py:340:        user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/trading.py:358:            user_id, user_secret = _get_snaptrade_identity(user_email)
brokerage/snaptrade/users.py:15:    delete_snaptrade_user_secret,
brokerage/snaptrade/users.py:16:    get_snaptrade_user_secret,
brokerage/snaptrade/users.py:17:    store_snaptrade_user_secret,
brokerage/snaptrade/users.py:44:        store_snaptrade_user_secret(user_email, user_secret)
brokerage/snaptrade/users.py:52:            existing_secret = get_snaptrade_user_secret(user_email)
brokerage/snaptrade/users.py:94:        delete_snaptrade_user_secret(user_email)
brokerage/snaptrade/users.py:99:            delete_snaptrade_user_secret(user_email)
mcp_tools/connection_status.py:14:    get_snaptrade_user_secret,
mcp_tools/connection_status.py:122:    user_secret = get_snaptrade_user_secret(resolved_email)
mcp_tools/connections.py:22:    get_snaptrade_user_secret,
mcp_tools/connections.py:242:    user_secret = get_snaptrade_user_secret(resolved_email)
mcp_tools/connections.py:437:    user_secret = get_snaptrade_user_secret(resolved_email)
routes/snaptrade.py:148:    get_snaptrade_user_secret,
routes/snaptrade.py:822:            user_secret = get_snaptrade_user_secret(user['email'])
scripts/explore_transactions.py:34:        get_snaptrade_user_secret,
scripts/explore_transactions.py:43:    user_secret = get_snaptrade_user_secret(user_email)
scripts/run_snaptrade.py:29:    get_snaptrade_user_secret,
scripts/run_snaptrade.py:166:    secret = get_snaptrade_user_secret(args.user_email)
scripts/run_snaptrade.py:176:    secret = get_snaptrade_user_secret(args.user_email)
services/snaptrade_portfolio_loader.py:14:    get_snaptrade_user_secret,
services/snaptrade_portfolio_loader.py:92:        user_secret = get_snaptrade_user_secret(user_email)
services/snaptrade_portfolio_loader.py:112:                current_secret = get_snaptrade_user_secret(user_email)
services/snaptrade_portfolio_loader.py:124:            user_secret = get_snaptrade_user_secret(user_email)
```

## A.3 Direct `boto3.client(...)` / `session.client(...)` Secrets Manager creations

```
brokerage/plaid/connections.py:114:    sm_client = boto3.client("secretsmanager", region_name=region_name)
brokerage/plaid/secrets.py:42:    client = session.client("secretsmanager", region_name=region_name)
brokerage/plaid/secrets.py:67:    client = session.client("secretsmanager", region_name=region_name)
brokerage/plaid/secrets.py:88:    client = session.client("secretsmanager", region_name=region_name)
brokerage/plaid/secrets.py:110:    client = session.client("secretsmanager", region_name=region_name)
brokerage/plaid/secrets.py:132:        secrets_client = boto3.client("secretsmanager", region_name=region_name)
brokerage/snaptrade/secrets.py:31:        secrets_client = boto3.client("secretsmanager", region_name=region_name)
brokerage/snaptrade/secrets.py:66:        secrets_client = boto3.client("secretsmanager", region_name=region_name)
brokerage/snaptrade/secrets.py:96:        secrets_client = boto3.client("secretsmanager", region_name=region_name)
brokerage/snaptrade/secrets.py:145:        secrets_client = boto3.client("secretsmanager", region_name=region_name)
brokerage/snaptrade/secrets.py:173:        secrets_client = boto3.client("secretsmanager", region_name=region_name)
mcp_tools/connection_status.py:83:    secrets_client = boto3.client("secretsmanager", region_name=region_name)
mcp_tools/connections.py:498:    secrets_client = boto3.client("secretsmanager", region_name=AWS_DEFAULT_REGION)
routes/onboarding.py:114:        secrets_client = boto3.client("secretsmanager", region_name=AWS_DEFAULT_REGION)
routes/plaid.py:312:        secrets_client = boto3.client("secretsmanager", region_name=AWS_DEFAULT_REGION)
routes/plaid.py:661:        secrets_client = boto3.client("secretsmanager", region_name=AWS_DEFAULT_REGION)
routes/plaid.py:1632:            secrets_client = boto3.client('secretsmanager', region_name=AWS_DEFAULT_REGION)
scripts/backfill_provider_items.py:34:    secrets_client = boto3.client("secretsmanager", region_name=region_name)
scripts/backfill_provider_items.py:49:    secrets_client = boto3.client("secretsmanager", region_name=region_name)
scripts/plaid_reauth.py:59:    secrets_client = boto3.client("secretsmanager", region_name=region_name)
services/anthropic_credential_store.py:57:    return boto3.client("secretsmanager", region_name=AWS_DEFAULT_REGION)
tests/snaptrade/test_snaptrade_registration.py:120:        secrets_client = boto3.client('secretsmanager', region_name='us-east-1')
```

(Note: `brokerage/{plaid,snaptrade}/secrets.py` are deleted entirely in Phase 3 step 9 — the lines above will not exist post-refactor. Listed here for completeness so the implementer knows the entire surface.)

## A.4 Anthropic call sites

```
routes/anthropic_credential.py:15:from services import anthropic_credential_store
routes/anthropic_credential.py:177:            anthropic_credential_store.store_user_anthropic_key(user_id, api_key, db)
routes/anthropic_credential.py:184:    except anthropic_credential_store.StorageError as exc:
routes/anthropic_credential.py:208:            anthropic_credential_store.delete_user_anthropic_key(user_id, db)
routes/internal_resolver.py:21:from services import anthropic_credential_store
routes/internal_resolver.py:219:            raw_credential = anthropic_credential_store.get_user_anthropic_key(user_id, db)
routes/internal_resolver.py:223:    except anthropic_credential_store.ResolverTransientError:
```

## A.5 Test files (mock targets / fixtures to update)

```
tests/api/test_plaid_reauth.py:42, 105
tests/api/test_snaptrade_holdings_refresh.py
tests/api/test_snaptrade_integration.py:90, 150, 167, 178, 431, 447, 448
tests/api/test_snaptrade_webhook.py
tests/brokerage/test_short_broker_adapters.py:97, 128
tests/brokerage/test_snaptrade_adapter_budget_user_id_threading.py:15
tests/brokerage/test_snaptrade_client.py:70
tests/brokerage/test_snaptrade_recovery.py:58
tests/mcp_tools/test_connection_status.py:93, 106, 228
tests/mcp_tools/test_connections.py:140, 179, 408, 433, 461, 519, 633, 681, 682, 685, 686, 705, 706, 722, 723, 793, 796
tests/providers/test_transaction_providers.py:559, 563, 623, 661, 682, 695, 718, 772, 815, 853
tests/routes/test_anthropic_credential.py
tests/routes/test_internal_resolver.py
tests/routes/test_plaid_disconnect.py:416
tests/routes/test_plaid_reconnect.py:37
tests/routes/test_provider_refresh_store_error.py
tests/routes/test_snaptrade_connections_route.py:32  (verify additional sites during impl)
tests/routes/test_snaptrade_disconnect.py
tests/routes/test_snaptrade_sync.py
tests/services/test_anthropic_credential_store.py:19, 59, 225, 248, 265 (rename file → tests/services/credentials/test_anthropic.py)
tests/services/test_plaid_portfolio_loader.py:14, 20
tests/services/test_snaptrade_broker_adapter.py
tests/services/test_snaptrade_holdings_service.py
tests/services/test_snaptrade_portfolio_loader.py
tests/snaptrade/test_snaptrade_authenticated.py
tests/snaptrade/test_snaptrade_credentials.py
tests/snaptrade/test_snaptrade_endpoints.py
tests/snaptrade/test_snaptrade_existing_user.py
tests/snaptrade/test_snaptrade_integration.py
tests/snaptrade/test_snaptrade_recovery.py
tests/snaptrade/test_snaptrade_registration.py:120 (also has direct boto3 — A.3)
tests/trading_analysis/test_provider_routing.py:82, 89, 120, 121
```

## A.6 SnapTrade public wrapper call sites

These public functions today take `user_email` and internally call `_get_snaptrade_identity(user_email)` to fetch the secret. Post-refactor they accept `user_secret` as a parameter; every call site below adds the secret-fetch + pass.

```
mcp_tools/connection_status.py:127:    for row in check_snaptrade_connection_health(...)
mcp_tools/connections.py:246:        for auth in list_user_brokerage_authorizations(...)
mcp_tools/connections.py:255:    connection_url = create_snaptrade_connection_url(...)
mcp_tools/connections.py:447:        authorizations = list_user_brokerage_authorizations(...)
routes/onboarding.py:140:        connections = list_snaptrade_connections(...)
routes/snaptrade.py:339:            connections = list_snaptrade_connections(user_email, budget_user_id=user_id)
routes/snaptrade.py:678:            user_secret = register_snaptrade_user(...)
routes/snaptrade.py:746:        connection_url = create_snaptrade_connection_url(...)
routes/snaptrade.py:832:            connections = list_snaptrade_connections(...)
routes/snaptrade.py:895:                    _new_secret, method = recover_snaptrade_auth(user["email"], user["user_id"])
routes/snaptrade.py:903:                rotate_snaptrade_user_secret(user["email"])
routes/snaptrade.py:1276:            remove_snaptrade_connection(...)
routes/snaptrade.py:1328:                        remaining_connections = list_snaptrade_connections(...)
routes/snaptrade.py:1424:            delete_snaptrade_user(...)
scripts/explore_transactions.py:59:        activities = get_activities(...)
scripts/run_snaptrade.py:56:    user_secret = register_snaptrade_user(...)
scripts/run_snaptrade.py:66:    url = create_snaptrade_connection_url(...)
scripts/run_snaptrade.py:80:    connections = list_snaptrade_connections(...)
scripts/run_snaptrade.py:101:    results = check_snaptrade_connection_health(...)
scripts/run_snaptrade.py:132:    remove_snaptrade_connection(...)
scripts/run_snaptrade.py:142:    url = upgrade_snaptrade_connection_to_trade(...)
scripts/run_snaptrade.py:156:    delete_snaptrade_user(...)
scripts/snaptrade_sdk_smoke.py:41:        user_secret = register_snaptrade_user(...)
scripts/snaptrade_sdk_smoke.py:47:            connection_url = create_snaptrade_connection_url(...)
scripts/snaptrade_sdk_smoke.py:52:                accounts = list_user_accounts(...)
scripts/snaptrade_sdk_smoke.py:57:                    delete_snaptrade_user(...)
services/snaptrade_portfolio_loader.py:119:                    rotate_snaptrade_user_secret(...)
trading_analysis/data_fetcher.py:236:    accounts = list_user_accounts(user_email, budget_user_id=budget_user_id)
trading_analysis/data_fetcher.py:281:                response_body = get_account_activities(...)
```

**Public functions whose signatures change** (add `user_secret: str` param, plus `on_secret_rotated`/`refresh_secret` for those that today call `_call_with_secret_rotation`):

`brokerage/snaptrade/trading.py`: `search_snaptrade_symbol`, `preview_snaptrade_order`, `place_snaptrade_checked_order`, `get_snaptrade_orders`, `cancel_snaptrade_order`.

`brokerage/snaptrade/connections.py`: `create_snaptrade_connection_url`, `upgrade_snaptrade_connection_to_trade`, `list_user_brokerage_authorizations`, `list_snaptrade_connections`, `check_snaptrade_connection_health`, `refresh_brokerage_authorization`, `remove_snaptrade_connection`.

`brokerage/snaptrade/client.py`: `list_user_accounts`, `get_account_activities`, `get_activities` (plus `_call_with_secret_rotation` per §Architecture).

`brokerage/snaptrade/users.py`: `register_snaptrade_user` (returns new secret to caller), `delete_snaptrade_user` (accepts user_secret).

`brokerage/snaptrade/recovery.py`: `rotate_snaptrade_user_secret`, `recover_snaptrade_auth` (per signatures in §Architecture). Internal helpers `_store_secret_with_retry`, `_try_rotate_secret` deleted/inlined.

**Brokerage-internal callers of these functions** (signature change ripples; risk_module callers in A.1–A.5 already counted; these are intra-brokerage call sites that must update consistently):

```
brokerage/snaptrade/adapter.py:101 — calls list_user_accounts/get_account_activities through self
brokerage/snaptrade/adapter.py:130
brokerage/snaptrade/adapter.py:172
brokerage/snaptrade/adapter.py:202
brokerage/snaptrade/adapter.py:240
brokerage/snaptrade/adapter.py:296
brokerage/snaptrade/adapter.py:305
brokerage/snaptrade/adapter.py:383
brokerage/snaptrade/connections.py:54
brokerage/snaptrade/connections.py:133
brokerage/snaptrade/connections.py:177
brokerage/snaptrade/trading.py:144
```

**Risk_module SnapTradeBrokerAdapter instantiation point** (must construct adapter with `user_secret`):

```
services/trade_execution_service.py:178-185 — instantiates SnapTradeBrokerAdapter; updates to fetch
    user_secret = services.credentials.snaptrade.get_user_secret(user_id, db) and pass to constructor.
```

**`scripts/snaptrade_sdk_smoke.py` exception**: ephemeral test user, no DB user_id. Smoke holds the secret returned from `register_snaptrade_user` in a local variable and passes it to subsequent calls. Does NOT call `services.credentials.snaptrade.*`. The smoke script is the only A.6 caller for which the on_secret_rotated/refresh_secret wiring is omitted.
