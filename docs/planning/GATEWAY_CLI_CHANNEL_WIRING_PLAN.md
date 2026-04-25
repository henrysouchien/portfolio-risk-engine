# Gateway `cli` Channel Wiring — Fix TUI Misclassification

**Status**: ✅ SHIPPED 2026-04-24. PRs merged: AI-excel-addin #47 (`44a7ff33`) + risk_module #19 (`bbb3952a`). Live-verified end-to-end — new CLI key `/chat/init` → 200, `/api/chat` → full Anthropic SSE stream (opus-4-7, 493/6 tokens, ~$0.18). v3 — Codex R2 PASS with 3 non-blocking nits tightened. See §11 change log.
**Date**: 2026-04-24
**Parent**: Phase 3 multi-user auth (shipped + cutover done 2026-04-24 per TODO 6D). Follow-up to the `GATEWAY_API_KEY_EXCEL=auto` quirk flagged in `docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md` and `docs/planning/AGENT_API_TUI_USER_EMAIL_PLAN.md` §3.2b.
**Blocker status**: Not blocking — cutover works today because TUI currently misclassifies as `excel` channel, which happens to BYOK-route identically to `cli`. But the channel-model mismatch is a latent bug (wrong channel field in logs/analytics, wrong system-prompt selection at chat time, broken when we add per-channel policies).

---

## 1. Goal

Wire the `cli` channel into the gateway's auth/classification layer so TUI sessions are recognized as `cli` end-to-end (session init → credential resolve → chat-time routing). "Cli" is already a first-class channel downstream (tool catalog, system prompt, analyst profile) — this plan closes the gap at the auth edge.

---

## 2. Non-goals

- **No billing-semantics change.** `cli` continues to route to `operator_auth_config` (same as excel/telegram/mcp). Per-channel BYOK for CLI is a separate future concern.
- **No TUI auth refactor.** TUI still authenticates via single `CHAT_API_KEY` env var + JWT session flow (no OAuth/SSO).
- **No removal of `GATEWAY_API_KEY_EXCEL=auto` convention.** Excel addin keeps its current default; this plan only adds `GATEWAY_API_KEY_CLI` as a peer.
- **No changes to `context.channel` handling at `/api/chat`.** That path (at `agent-gateway-dist/agent_gateway/server.py:594-595`) already works — TUI is already sending `context: {channel: "cli"}` after today's 6D-F3 ship. The issue is **only** at `/api/chat/init` where `api_key` hash is the classification key.
- **No per-channel `CODE_EXECUTION_CHANNELS` tightening.** `cli` is already in that set at `api/agent/shared/tool_catalog.py:73`.

---

## 3. Current state (verified 2026-04-24)

### 3.1 Three places enumerate `GATEWAY_API_KEY_*` — all miss `CLI`

**File 1** — `AI-excel-addin/api/main.py:306-311` (channel classification for credentials resolver):

```python
for env, channel in [
  ("GATEWAY_API_KEY_EXCEL", "excel"),
  ("GATEWAY_API_KEY_TELEGRAM", "telegram"),
  ("GATEWAY_API_KEY_WEB", "web"),
  ("GATEWAY_API_KEY_MCP", "mcp"),
]:
  ...
```

**File 2** — `AI-excel-addin/api/auth.py:15-24` (valid-key allow-list for session init):

```python
_DEDICATED_KEYS = {
  os.getenv(env, "").strip()
  for env in (
    "GATEWAY_API_KEY_EXCEL",
    "GATEWAY_API_KEY_TELEGRAM",
    "GATEWAY_API_KEY_WEB",
    "GATEWAY_API_KEY_MCP",
    "GATEWAY_API_KEY_LEGACY",
  )
}
```

**File 3** — `AI-excel-addin/api/credentials_resolver.py:71` (operator-auth channel set):

```python
if channel in {"excel", "telegram", "mcp"}:
  return _operator_auth_config(operator_auth_config)
```

### 3.2 Live collision observable today

- `risk_module/.env:135` → `GATEWAY_API_KEY_EXCEL=auto`
- `AI-excel-addin/tui/src/config.ts:7` → `CHAT_API_KEY = process.env.CHAT_API_KEY ?? "auto"`
- `hash("auto")` matches the `EXCEL` env → credentials resolver classifies TUI as `excel`
- Works today only because `excel` and `cli` both route to `operator_auth_config` at `credentials_resolver.py:71` (for the former) and `agent-gateway-dist/agent_gateway/server.py:594-595` honors `context.channel` at chat time independently for system-prompt routing.

### 3.3 Downstream is ready

- `cli` is a first-class channel at:
  - `api/agent/shared/tool_catalog.py:48` (tool catalog entry)
  - `api/agent/shared/tool_catalog.py:73` (`CODE_EXECUTION_CHANNELS = {"web", "cli"}`)
  - `api/agent/shared/tool_catalog.py:74` (`WEB_TOOL_CHANNELS`)
  - `api/agent/shared/system_prompt.py:1161` (distinct prompt branch with telegram)
  - `api/agent/profiles/analyst.py:56` + `advisor.py:35` (`CHANNEL_CONTEXT = "cli"`)
- TUI now emits `context: {channel: "cli"}` on `/chat/init` (shipped 2026-04-24 via AI-excel-addin PR #46). That field is observable server-side at `agent-gateway-dist/agent_gateway/server.py:594-595` at `/api/chat` time but **not** used at `/api/chat/init` classification.

### 3.4 Tests that enumerate `GATEWAY_API_KEY_*` (v2 — Codex R1 blocker #3)

Initial v1 grep was scoped to `AI-excel-addin/api/` and missed `AI-excel-addin/tests/`. Tests DO exist and explicitly enumerate the dedicated-key env vars:

- `tests/test_api_auth_phase6.py:20-29` — `test_valid_keys_unchanged_when_dedicated_keys_unset` monkeypatches `delenv` for the 4 gateway keys + LEGACY. Must include `GATEWAY_API_KEY_CLI` after this plan ships, else leaked env from other tests can fail assertion.
- `tests/test_api_main_phase6.py:30-39` — `_set_base_env` helper does the same `delenv` loop. Same fix needed.
- `tests/test_api_credentials_resolver.py:71-79` — `test_excel_and_telegram_channels_return_operator_auth_config` asserts excel + telegram route to operator auth. Extend (or add a sibling) to cover `cli`.

No other test files enumerate these env vars (verified via `grep -rnl "GATEWAY_API_KEY_EXCEL\|api_key_to_channel\|operator_auth_config" AI-excel-addin/tests AI-excel-addin/api`).

---

## 4. Design decisions

### 4.1 Why a separate `GATEWAY_API_KEY_CLI` env var (vs. context-based override)

The simplest alternative is to have the resolver honor `init_request.context.channel` as a tie-breaker. Rejected because:

- `context` is free-form client input. Trusting it would let a client with an excel-channel key self-promote to cli (or vice versa) by setting `context.channel`. Even if both happen to BYOK-route identically today, that's a policy we shouldn't tie ourselves to.
- The existing design (`api_key_hash → channel`) is the security boundary. Adding an env-driven CLI key preserves it.

### 4.2 Why keep `GATEWAY_API_KEY_EXCEL=auto` as-is

Renaming would require coordinated changes to the Excel addin's production config. Out of scope; additive-only changes.

### 4.3 Value convention for `GATEWAY_API_KEY_CLI`

Generate a distinct token (`python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`) — matching the ops-doc pattern at `docs/ops/GATEWAY_MULTI_USER_ACTIVATION.md:60-63`. Do NOT reuse `"auto"` for the CLI key — keeping keys distinct across channels is the whole point of per-channel env vars.

### 4.4 Where `CHAT_API_KEY` lives for the TUI

TUI's `npm run start` is launched with `set -a; source /path/to/risk_module/.env; set +a` per `AI-excel-addin/README.md:123` (shipped 2026-04-24 via PR #46). So `CHAT_API_KEY` goes in `risk_module/.env` (the file the operator sources). `GATEWAY_API_KEY_CLI` goes in `AI-excel-addin/.env` (the file the gateway reads via its `services.yaml` `env_file`).

### 4.5 Rollout ordering

Because the three files (main.py, auth.py, credentials_resolver.py) are all in the same repo and all referenced at import time from the same gateway process, they ship as one AI-excel-addin PR. The risk_module `.env` and AI-excel-addin `.env` edits are operator-local and land separately.

---

## 5. Scope — files to change (LOCKED PAIR with §6 for code/docs/test rows — Steps 3/4/6 in §6 are operational, not file edits; see §5.2)

### 5.1 Files (code + tests + docs + env)

| # | File | Change |
|---|------|--------|
| 1 | `AI-excel-addin/api/main.py:306-311` | Add `("GATEWAY_API_KEY_CLI", "cli")` row to the channel-registration loop |
| 2 | `AI-excel-addin/api/auth.py:16-23` | Add `"GATEWAY_API_KEY_CLI"` to the `_DEDICATED_KEYS` tuple |
| 3 | `AI-excel-addin/api/credentials_resolver.py:71` | Add `"cli"` to the operator-auth channel set → `{"excel", "telegram", "mcp", "cli"}` |
| 4 | `AI-excel-addin/tests/test_api_auth_phase6.py` | Add `"GATEWAY_API_KEY_CLI"` to the `delenv` tuple at every callsite in this file (3 tests: `test_valid_keys_unchanged_when_dedicated_keys_unset` at L20-29, plus the two siblings at L35+). Also add `"GATEWAY_API_KEY_MCP"` at the same callsites — it's currently missing from the delenv loop (Codex R2 non-blocking nit; trivial in-scope tightening for loop-pattern consistency). |
| 5 | `AI-excel-addin/tests/test_api_main_phase6.py:30-39` | Add `monkeypatch.delenv("GATEWAY_API_KEY_CLI", raising=False)` + `monkeypatch.delenv("GATEWAY_API_KEY_MCP", raising=False)` to the `_set_base_env` helper (covers all 5 tests in this file via the shared helper; Codex R2 verified). |
| 6 | `AI-excel-addin/tests/test_api_credentials_resolver.py:71-79` | Add a new sibling test `test_cli_channel_returns_operator_auth_config` immediately after the existing `test_excel_and_telegram_channels_return_operator_auth_config`. Mirror its structure — hash a cli-marked key, construct the resolver with `{<hash>: "cli"}`, assert the returned `AuthConfig` matches operator. Do NOT rename/modify the existing test (Codex R2 recommend — keeps the existing test's scope pure). |
| 7 | `AI-excel-addin/.env` (operator-local, not committed) | Add `GATEWAY_API_KEY_CLI=<new urlsafe token>` |
| 8 | `risk_module/.env` (operator-local, not committed) | Add `CHAT_API_KEY=<matching token from #7>` |
| 9 | `AI-excel-addin/README.md:119-127` "Other Entry Points" table | Update TUI launch row — note that `CHAT_API_KEY` comes from sourced `risk_module/.env`, and `GATEWAY_API_KEY_CLI` must be set in gateway env |
| 10 | `risk_module/docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md` "TUI operator launch" section | Clarify `CHAT_API_KEY` convention + cross-reference new `GATEWAY_API_KEY_CLI` var. Remove the `GATEWAY_API_KEY_EXCEL=auto` "separate cleanup" bullet (it's this plan). |

### 5.2 Operational steps (not file edits)

§6 also contains operational steps that do not correspond to file rows above:

- Step 3 (generate urlsafe token) — shell command invoked by operator; not a file edit, produces values for §5 rows #7 + #8.
- Step 4 (restart gateway under services-mcp) — runtime operation.
- Step 6 (live verification) — runtime operation against live gateway.

These do not require §5 entries. The §5↔§6 lock applies only to `file → step` pairings for rows #1-#10.

---

## 6. Implementation steps (LOCKED PAIR with §5.1)

### Step 1 — AI-excel-addin PR: wire CLI channel into gateway auth + tests + docs (covers §5 #1 + #2 + #3 + #4 + #5 + #6 + #9)

Branch off `AI-excel-addin/main`. All code/test/docs edits ship in one PR:

**§5 #1 — `api/main.py:306-311`**: Add the CLI row to the `for env, channel in [...]` loop. Maintain existing ordering — place after `EXCEL`:

```python
for env, channel in [
  ("GATEWAY_API_KEY_EXCEL", "excel"),
  ("GATEWAY_API_KEY_CLI", "cli"),
  ("GATEWAY_API_KEY_TELEGRAM", "telegram"),
  ("GATEWAY_API_KEY_WEB", "web"),
  ("GATEWAY_API_KEY_MCP", "mcp"),
]:
```

**§5 #2 — `api/auth.py:16-23`**: Add `"GATEWAY_API_KEY_CLI"` to the tuple (preserve existing trailing `GATEWAY_API_KEY_LEGACY`):

```python
for env in (
  "GATEWAY_API_KEY_EXCEL",
  "GATEWAY_API_KEY_CLI",
  "GATEWAY_API_KEY_TELEGRAM",
  "GATEWAY_API_KEY_WEB",
  "GATEWAY_API_KEY_MCP",
  "GATEWAY_API_KEY_LEGACY",
)
```

**§5 #3 — `api/credentials_resolver.py:71`**: Extend the operator-auth channel set:

```python
if channel in {"excel", "telegram", "mcp", "cli"}:
  return _operator_auth_config(operator_auth_config)
```

**§5 #4 — `tests/test_api_auth_phase6.py`**: Grep this file for the `monkeypatch.delenv` loop pattern — 3 callsites currently enumerate the `GATEWAY_API_KEY_*` tuple. For each, add `"GATEWAY_API_KEY_CLI"` and `"GATEWAY_API_KEY_MCP"` (the latter is missing today — trivial pre-existing gap, fixed inline). Tests: `test_valid_keys_unchanged_when_dedicated_keys_unset`, `test_dedicated_key_is_included`, `test_legacy_key_is_included`.

**§5 #5 — `tests/test_api_main_phase6.py:30-39`**: Add to `_set_base_env`:

```python
monkeypatch.delenv("GATEWAY_API_KEY_CLI", raising=False)
monkeypatch.delenv("GATEWAY_API_KEY_MCP", raising=False)
```

All 5 tests in this file reuse `_set_base_env` (L44, L67, L82, etc. — Codex R2 verified), so a single helper edit covers them.

**§5 #6 — `tests/test_api_credentials_resolver.py`**: Add a new sibling test right after `test_excel_and_telegram_channels_return_operator_auth_config` (L71-79). Skeleton:

```python
def test_cli_channel_returns_operator_auth_config() -> None:
  cli_key = "cli-key"
  resolver = _resolver(
    api_key_to_channel={
      hashlib.sha256(cli_key.encode("utf-8")).hexdigest(): "cli",
    }
  )
  # ... invoke resolver, assert result matches _operator_auth_config(...) contract
  # (mirror the existing test's invocation + assertion structure)
```

Do NOT rename/modify the existing excel+telegram test.

**§5 #9 — `README.md:119-127`**: Update "Other Entry Points" TUI row:

```markdown
| TUI client | `cd tui && npm install`<br/>`set -a; source /path/to/risk_module/.env; set +a`<br/>`npm run start` — requires `CHAT_API_KEY` in `risk_module/.env` matching `GATEWAY_API_KEY_CLI` in `AI-excel-addin/.env` |
```

**Commit message**: `feat(gateway): wire cli channel into auth + credentials resolver + tests`

### Step 2 — risk_module docs PR (covers §5 #10)

Separate, small risk_module PR — docs-only.

Edit `docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md` "TUI operator launch" section. Add `CHAT_API_KEY` + `GATEWAY_API_KEY_CLI` to the bullet list. Remove the "separate ops cleanup" paragraph about `GATEWAY_API_KEY_EXCEL=auto` (that work is now this plan — replace with a pointer to this plan's commit).

**Commit message**: `docs(ops): TUI cli channel env var wiring`

### Step 3 — Generate + install keys (produces values for §5 #7 + #8; operational, not a file edit)

Operator-local. Run the ops-doc incantation:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
# => <TOKEN>
```

Write `GATEWAY_API_KEY_CLI=<TOKEN>` to `AI-excel-addin/.env` (§5 #7). Write `CHAT_API_KEY=<same TOKEN>` to `risk_module/.env` (§5 #8).

**Neither file is committed** (both in `.gitignore`). Edits are step-local.

### Step 4 — Restart gateway under services-mcp (operational)

```bash
# from any cwd
python3 -c "
import sys; sys.path.insert(0, '/Users/henrychien/Documents/Jupyter/AI-excel-addin/mcp_servers/services_mcp')
import server, json
print(json.dumps(server.service_restart.fn('gateway'), indent=2))
"
```

Gateway picks up new env vars and re-registers the channel map. **Note** (Codex R1): restart clears all in-memory sessions (see §9 R3 v2). All clients (Excel taskpane, TUI, Telegram bot) must re-init.

### Step 5 — Relaunch TUI with new `CHAT_API_KEY` (operational)

If the TUI was running during Step 4, kill it. Relaunch per README:

```bash
cd /path/to/AI-excel-addin/tui
set -a
source /path/to/risk_module/.env
set +a
npm run start
```

Verifies §5 #8 value flows end-to-end.

### Step 6 — Live verification (see §10 for full checklist; operational)

Verify TUI-shaped `/chat/init` call classifies as `cli`, not `excel`. Verify Excel addin still classifies as `excel` (regression guard).

---

## 7. Tests

v2 scope (Codex R1 blocker #3): 3 test files updated in-PR. See §5 rows #4-#6.

Run after Step 1:

```bash
cd /Users/henrychien/Documents/Jupyter/AI-excel-addin
pytest tests/test_api_auth_phase6.py tests/test_api_main_phase6.py tests/test_api_credentials_resolver.py -v
```

Expected: all existing tests still pass + new `test_cli_channel_returns_operator_auth_config` passes. Running the full `pytest` suite is recommended but the 3 files above are the minimal coverage for this change.

No new test file is created — extending existing ones matches the existing test organization.

---

## 8. Rollout

- **Reversibility** (v2 — Codex R1 blocker #1): rolling back requires **both** env-var changes to be undone, not just `GATEWAY_API_KEY_CLI`. Full rollback:
  1. Unset `GATEWAY_API_KEY_CLI` in `AI-excel-addin/.env` (or delete the line)
  2. Unset `CHAT_API_KEY` in `risk_module/.env` (or set back to unset → TUI defaults to `"auto"` via `tui/src/config.ts:7`)
  3. Restart gateway under services-mcp
  4. Relaunch TUI

  Code rollback (§5 #1-#6) is orthogonal — once merged, leaving the unused env var slot in the loop has no runtime effect when the env var is absent.
- **Ordering**: Gateway code PR merges first, then env vars set, then gateway restart, then TUI relaunch. Empty `GATEWAY_API_KEY_CLI` in env after the code merge is benign — the loop skips empty values via `os.getenv(env, "").strip()` + `if key:` guard at `main.py:312` and `auth.py:25`.
- **Blast radius**: TUI sessions only. Excel addin, Telegram bot, web UI are unaffected (their `GATEWAY_API_KEY_*` env vars unchanged). Gateway restart at Step 4 briefly disrupts any live chat session across all channels (see §9 R3).

---

## 9. Risks

### R1 — Two env vars share the same token value

If operator sets `GATEWAY_API_KEY_CLI=auto` (reusing excel's value), the last-loop-iteration wins (`api/main.py:306-311` and `api/auth.py:16-23` both use dict/set semantics with iteration order). Behavior: `hash("auto")` maps to whichever channel was registered last.

**Mitigation**: Step 3's §4.3 explicitly says generate a fresh token. Plan doc + ops doc both call this out. No code-level guard — this is a config-correctness concern, not a gateway bug.

### R2 — risk_module `.env` change breaks risk_module backend

`risk_module` doesn't consume `CHAT_API_KEY` today. Adding it is additive. Verified via `grep -n CHAT_API_KEY /Users/henrychien/Documents/Jupyter/risk_module/*.py` — zero matches. No risk.

### R3 — Gateway restart invalidates all in-memory sessions (v2 — Codex R1 blocker #2)

v1 incorrectly claimed old JWTs would continue until TTL expiry. The gateway's `SessionStore` (`packages/agent-gateway/agent_gateway/session.py:53-189`) is in-memory and dropped on process restart. After Step 4:

- All clients (TUI, Excel taskpane, Telegram bot, web UI) must re-issue via `/api/chat/init`.
- Anyone mid-stream gets a connection drop.
- No forced re-auth is needed (re-init is automatic on next client request).

**Accept**: dev rollout, coordinate restart during idle window. For production, this same rollout already needs gateway-restart coordination per `docs/ops/GATEWAY_MULTI_USER_ACTIVATION.md`.

### R4 — CLI channel does something unexpected downstream

`credentials_resolver.py:71` extension from `{excel, telegram, mcp}` to `{excel, telegram, mcp, cli}` sends cli through `operator_auth_config` like the others. Downstream paths (`system_prompt.py:1161`, `tool_catalog.py:48`) already branch on cli. **Verified** today's live smoke: TUI `/chat/init` + `/api/chat` return 200 with JWT + streaming response, even under current misclassification. Fixing the classification can only make things *more* correct, not less.

### R5 — `CHAT_VALID_KEYS=telegram-analyst-key,auto,dev-gateway-key` at AI-excel-addin/.env:17 still enumerates `auto`

That legacy allow-list at `auth.py:10-14` is orthogonal — it just adds keys to the accepted set. New CLI key is independently added via Step 1's `_DEDICATED_KEYS` extension. Nothing to change in `CHAT_VALID_KEYS`.

---

## 10. Live verification — ✅ PASSED 2026-04-24

Ran after Steps 1-5 complete.

| # | Check | Result |
|---|-------|--------|
| 1 | `curl -s -k -X POST https://localhost:8000/api/chat/init -H 'Content-Type: application/json' -d '{"api_key":"<NEW_CLI_TOKEN>","user_id":"operator","user_email":"hc@henrychien.com","context":{"channel":"cli"}}'` | ✅ HTTP 200, `session_token` issued |
| 2 | Decode the JWT — `user_id` + `user_email` carried | ✅ `user_id="operator"`, `user_email="hc@henrychien.com"` |
| 3 | Default model in catalog | ✅ `claude-opus-4-7` |
| 4 | Full `/api/chat` SSE stream with test prompt | ✅ `O` → `K` → `turn_complete` → `stream_complete`, 493/6 tokens, ~$0.18 |
| 5 | Verify Excel addin unaffected — `api_key="auto"` still classifies | ✅ HTTP 200 (regression guard) |

---

## 11. Change log

- **v3 (2026-04-24)** — Codex R2 PASS with 3 non-blocking nits tightened:
  - §5 #6 + §6 Step 1 tightened from hedged "extend or add sibling" to definitive "add a new sibling test, don't modify the existing excel+telegram test" (per Codex R2 recommend — keeps existing test scope pure).
  - §5 #4 + §5 #5 extended to also delenv `GATEWAY_API_KEY_MCP` — pre-existing gap in both test files' `delenv` loops. Trivial in-scope tightening for test-isolation consistency.
  - §5 #4 + §6 Step 1 clarified that `test_api_auth_phase6.py` has 3 delenv callsites (all need the edit), not 1. Codex R2 collection verified the test names.
- **v2 (2026-04-24)** — Revised per Codex R1 FAIL:
  - **Blocker #1 (rollback reversibility, §8)**: v1 rollback only unset `GATEWAY_API_KEY_CLI`; missed that TUI keeps sending `CHAT_API_KEY=<TOKEN>` until that env var is also cleared. §8 now enumerates both env changes + TUI relaunch.
  - **Blocker #2 (R3 session-invalidation, §9)**: v1 claimed JWTs survive restart until TTL. Wrong — `SessionStore` is in-memory, restart drops all sessions. §9 R3 rewritten.
  - **Blocker #3 (tests, §3.4 + §5 + §6 + §7)**: v1 said "no tests to touch" — grep was scoped to `api/` only. Tests under `AI-excel-addin/tests/` enumerate the `GATEWAY_API_KEY_*` env vars at 3 callsites. Added §5 rows #4-#6 with matching §6 edits in Step 1. Added §7 pytest invocation.
  - **Blocker #4 (§5↔§6 LOCKED PAIR wording)**: v1 said §5/§6 are locked but had §6 steps 4 + 6 (operational) with no §5 rows. v2 splits §5 into 5.1 (file rows) + 5.2 (operational), relaxes the lock wording to code/docs/test rows only. Added explicit Step 5 (TUI relaunch) for completeness.
  - **Non-blocking notes addressed inline** (enumeration completeness verified by Codex; security posture §4.1 confirmed; `cli` downstream consequences verified benign; empty env var skip verified in `main.py:312` / `auth.py:25`).
- **v1 (2026-04-24)** — Initial draft. Scope: wire cli channel into 3 gateway files + 2 env files + 2 docs files. No code in scope beyond the 3 small enumeration edits. Live-verification-gated (no tests).
- **Post-ship reconstruction note (2026-04-24)**: This plan file was written with the Write tool during the plan→review phase but was never committed to git. When a parallel session operated on the worktree, the untracked file was lost. The content here is reconstructed from the conversation record (Edit-tool diffs + Codex review rounds). Commits, PRs, and live-verification are authoritative; this doc preserves the artifact for future reference.

---

## Appendix A — Why this didn't ship with 6D-F3

The 6D-F3 plan (TUI user_email plumbing) consciously scoped out channel classification — see `AGENT_API_TUI_USER_EMAIL_PLAN.md:48-52` (§3.2b). Today's session confirmed cutover works despite the misclassification because both `excel` and `cli` route through `operator_auth_config`. Fixing the channel correctly is cleanup, not blocker.
