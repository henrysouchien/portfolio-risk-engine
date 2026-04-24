# Agent API Phase 3 — TUI (`cli` channel) user_email Plumbing

**Status**: DRAFT v4 — revised per Codex R3 FAIL (§5 tool-approval drift only; trivial one-line fix). See §11 change log.
**Date**: 2026-04-24
**Parent plan**: `docs/planning/AGENT_API_SIGNED_USER_CLAIM_PLAN.md` (Phase 3 multi-user auth, shipped 2026-04-22)
**Sibling plan**: `docs/planning/AGENT_API_EXCEL_ADDIN_USER_EMAIL_PLAN.md` (Excel addin equivalent, shipped 2026-04-23 as PR #30)
**Blocking**: Phase 3 cutover (flip `AGENT_API_LEGACY_BEARER_ENABLED=false`). TODO 6D-F3. Live verification on 2026-04-24 confirmed TUI `tui/src/backend-client.ts:158` sends only `{ api_key }` on `/chat/init` — no `user_id`, no `user_email`.

---

## 1. Goal

Thread `user_id` + `user_email` through the TUI's `/chat/init` call so the running signer (Phase 3 Step 4) has both session fields available when spawning sandboxes from `cli`-channel sessions. After this ships, TUI sessions match web-channel sessions — signed claims work end-to-end. Phase 3 cutover unblocks.

**Why this isn't a 6D-F2 clone**: the TUI has a different build system (`tsx` runtime, not webpack). The Excel addin's `CHAT_OPERATOR_USER_EMAIL` build-time `DefinePlugin` substitution pattern does **not** apply. TUI reads `process.env` at runtime on every launch — simpler than the addin, no rebuild required.

---

## 2. Non-goals

- **No backend changes.** `ChatInitRequest` at `packages/agent-gateway/agent_gateway/server.py:51` already accepts top-level `user_email: str | None = None` (shipped in Phase 3 Step 3b). Gateway is ready.
- **No model catalog fixes.** `tui/src/config.ts:8` `FALLBACK_DEFAULT_MODEL = "claude-opus-4-7"` is already current. Any drift beyond what's in gateway's `model_catalog` response is out of scope (orthogonal concern — gateway owns the catalog per PR #44).
- **No test-harness bootstrap.** TUI has no `tests/` dir, no jest/vitest config. Adding one is a real scope bump. This plan accepts **manual live-verify** as the test strategy (see §6).
- **No dotenv autoloading.** Ops documentation will use `set -a; source .env; set +a; npm run start` (plain `.env` files require allexport — see §4.4); not adding a `dotenv-cli` dep or top-of-entrypoint loader.
- **No Office SSO / OAuth / interactive prompt.** Operator sets env vars before launch — consistent with existing `CHAT_API_KEY` / `CLI_BACKEND_URL` pattern.

---

## 3. Current state (verified 2026-04-24)

### 3.1 The gap (Codex R1 blocker #1 — /chat/init AND /api/chat both need identity)

- `tui/src/backend-client.ts:158` — body on `POST /api/chat/init` is literally `{ api_key: this.chatApiKey }`. No `user_id`, no `user_email`, no `context`.
- `tui/src/backend-client.ts:227` — `streamChat()` body on `POST /api/chat` sends only `messages` + `context`. **Strict-mode rejects missing/mismatched `user_id` at `server.py:577`** — every chat request needs `user_id` matching the JWT-embedded session identity.
- `this.chatApiKey` set at `backend-client.ts:109` = `opts?.chatApiKey ?? CHAT_API_KEY`, where `CHAT_API_KEY` at `tui/src/config.ts:5` = `process.env.CHAT_API_KEY ?? "auto"`.
- Same session backs `/api/chat/tool-approval` at `backend-client.ts:316` — **does NOT require `user_id`** (Codex R2 confirmed). Handler at `server.py:747-760` authenticates via bearer token + session state only. Out of scope.

**v1 bug**: this plan originally said "init is the only place identity could be threaded." That was wrong (Codex R1 blocker). Strict mode enforces user_id on every chat turn. §5/§6 updated accordingly.

### 3.2 Strict-mode gateway — TUI IS broken today (Codex R1 confirmed)

- `agent-gateway-dist/agent_gateway/server.py:513-521`: `/chat/init` rejects `_default` in strict mode. Strict mode is active when a resolver is configured (`credentials_resolver is not None`).
- `agent-gateway-dist/agent_gateway/server.py:577`: `/chat` rejects missing/mismatched `user_id`.
- `risk_module/.env:139` sets resolver config; `credentials.py:32` has Anthropic as default provider — so strict mode IS active in this dev env (not "maybe active" per v1).
- Gateway falls back through `payload.user_id or context.user_id or "_default"` at `server.py:495-509`. TUI sends neither → `_default` → `StrictModeDefaultUserError` → **TUI is currently broken against the live multi-user gateway**.
- This plan is therefore BOTH a Phase 3 cutover unblock AND a bug fix for the strict-mode-broken TUI.

### 3.2b Channel-classification quirk (Codex R1 recommend — not today's blocker, noted)

- `risk_module/.env:135` sets `GATEWAY_API_KEY_EXCEL=auto`. The `CHAT_API_KEY` default in TUI at `tui/src/config.ts:5` is also `"auto"`.
- `credentials_resolver.py:61` classifies api_keys by `GATEWAY_API_KEY_*` env matching — so `"auto"` matches `EXCEL` channel, not `CLI`.
- Consequence: TUI sessions currently get classified as `excel` channel by the resolver, not `cli`. Works for cutover because both channels are BYOK-gateway-side, but it's a real channel-model mismatch worth fixing separately. **Out of scope for this plan**; note for ops tracking.

### 3.3 No existing TUI identity config

- Grep across `tui/` for `CHAT_OPERATOR_USER_ID` or similar: zero matches.
- No config file (`tui/data/` only has `chat_history.json`), no TOML, no interactive prompt.
- `tui/package.json:5-9`: `"start": "tsx src/index.ts"`, `"build": "tsc -p tsconfig.json"` with `"noEmit": true` in tsconfig — build is type-check only, no bundling. So **no build-time env substitution available** — runtime `process.env` only.
- `package.json` has no `"main"` / `"bin"` — TUI is not a publishable CLI. Run directly from source via `cd tui && npm install && npm run start` per `README.md:123`.

### 3.4 Symlinked `.env` already has the operator values

- repo-root `.env` (symlinked to `AI-excel-addin/api/.env`) already contains:
  - `CHAT_OPERATOR_USER_EMAIL=hc@henrychien.com` (added 2026-04-23 for Excel addin).
  - Operator will also add `CHAT_OPERATOR_USER_ID=operator` (or whatever value they use).
- Shell does NOT auto-source `.env`. Operator must `set -a; source .env; set +a; npm run start` (allexport mode required for plain `.env` format per §4.4) OR use `dotenv-cli` OR a wrapper script. Bare `source .env && ...` does NOT propagate the vars to child Node process.

### 3.5 Gateway `ChatInitRequest` is ready

- `packages/agent-gateway/agent_gateway/server.py:46-52` — `ChatInitRequest` has `api_key: str`, `user_id: str | None = None`, `user_email: str | None = None`, `context: Dict[str, Any]`. Optional fields tolerate absence. No backend change required.
- Server normalizes empty strings to None at `server.py:498-502,545` and forwards to session.

---

## 4. Design

### 4.1 Mirror the existing `CHAT_API_KEY` runtime pattern (Codex R1 recommend — concrete user_id default)

`tui/src/config.ts` already uses runtime `process.env` reads with string defaults:

```ts
// tui/src/config.ts (existing)
export const CHAT_API_KEY = process.env.CHAT_API_KEY ?? "auto";
export const CLI_BACKEND_URL = process.env.CLI_BACKEND_URL ?? "https://localhost:8000";
// ...
```

Add two new constants. **`user_id` requires a concrete default** (per Codex R1 — empty-string omission fails under strict mode). `user_email` can be empty-omitted (optional field):

```ts
// v2 — user_id defaults to "operator" matching Excel addin precedent at
// src/taskpane/chatContract.ts:9 (DEFAULT_CHAT_OPERATOR_USER_ID = "operator").
// Empty-email default is safe because it's optional server-side.
const DEFAULT_CHAT_OPERATOR_USER_ID = "operator";
export const CHAT_OPERATOR_USER_ID = (process.env.CHAT_OPERATOR_USER_ID ?? "").trim() || DEFAULT_CHAT_OPERATOR_USER_ID;
export const CHAT_OPERATOR_USER_EMAIL = (process.env.CHAT_OPERATOR_USER_EMAIL ?? "").trim();
```

Effect:
- `user_id` is ALWAYS truthy — defaults to `"operator"` if unset, matching what Excel addin sends today.
- `user_email` may be empty → body omits the field (backwards-compat; backend accepts None at `server.py:52`).

### 4.2 Include identity in BOTH `/chat/init` and `/api/chat` bodies (Codex R1 blocker #1)

Strict mode enforces `user_id` on every chat turn at `server.py:577`. TUI's `streamChat()` at `backend-client.ts:227` also needs identity threading, not just `ensureSession()`.

**`/chat/init` body** (`backend-client.ts:158`):

```ts
// user_id is always truthy (has default); user_email only when set
const body: Record<string, unknown> = {
  api_key: this.chatApiKey,
  user_id: this.userId,
  context: { channel: "cli" },   // symmetry with Excel addin; see §4.3
};
if (this.userEmail) body.user_email = this.userEmail;
// then: body: JSON.stringify(body)
```

**`/api/chat` body** (`backend-client.ts:227`):

```ts
// Extend existing { messages, context } body with user_id — strict mode requires it.
// Session-context channel is already sent via tui.ts:516 (ChatRequest.context).
// JWT-embedded user_id MUST match body user_id per server.py:581-586.
const body = {
  messages: [...],  // existing
  user_id: this.userId,   // NEW
  context: { ... },  // existing
};
```

**`/api/chat/tool-approval`** (`backend-client.ts:316`): **no change needed** (Codex R2 confirmation). Handler at `server.py:747-760` authenticates only via bearer token + session state, not strict-mode `user_id` validation. Identity already established by the session token. No scope extension here.

Constructor changes (`backend-client.ts:96-114`):

```ts
// add to constructor opts
userId?: string;
userEmail?: string;

// and in the constructor body
this.userId = opts?.userId ?? CHAT_OPERATOR_USER_ID;
this.userEmail = opts?.userEmail ?? CHAT_OPERATOR_USER_EMAIL;
```

Callers in `tui/src/index.ts` / `tui/src/tui.ts` (if any explicitly pass `chatApiKey`) get the same default-fallback behavior — they only need to override if they want non-default identity.

### 4.3 `context: { channel: "cli" }` on `/chat/init` — symmetry, not auth-critical (Codex R1 recommend)

Codex R1 clarified: `chat_init` only consults `context.user_id` fallback at `server.py:503` — `context.channel` is NOT auth-driving. TUI already sends `channel: "cli"` on `/api/chat` via `tui.ts:516`.

**Still include** `context: { channel: "cli" }` on `/chat/init` for symmetry with the Excel addin precedent (`src/taskpane/chatContract.ts:18-24` sends `context: { channel: "excel" }`). Zero cost, documents intent, matches sibling. But don't treat it as auth-critical — the auth is carried by `user_id` + `user_email`.

If live-verify (§6) shows unexpected server-side behavior with the context, remove it in the same PR.

### 4.4 Operator-env provisioning model (Codex R1 blocker #2 — `.env` uses plain `KEY=value`, needs `set -a`)

**Before launch**: operator exports all env vars from the repo-root `.env` into the shell before launching Node.

The repo-root `.env` uses plain `KEY=value` format (no `export` prefix per `/Users/henrychien/Documents/Jupyter/risk_module/.env:1`). So `source .env && npm run start` does NOT propagate the vars to the child Node process — the variables get set in the current shell's environment only if they were `export`ed OR if the shell is in `-a` mode.

**Correct launch command**:

```bash
cd /Users/henrychien/Documents/Jupyter/AI-excel-addin/tui
set -a
source /Users/henrychien/Documents/Jupyter/risk_module/.env   # auto-exports all CHAT_* / GATEWAY_API_KEY_* / etc.
set +a
npm run start
```

`set -a` (same as `set -o allexport`) auto-exports every variable assignment until `set +a` — this is the standard idiom for plain `.env` files.

Alternative: use `dotenv-cli` (`npm install --save-dev dotenv-cli` + `dotenv -e ../risk_module/.env -- npm run start`). Plan says no — minimal dependency footprint.

If `CHAT_OPERATOR_USER_ID` is absent, it defaults to `"operator"` (safe for strict mode). If `CHAT_OPERATOR_USER_EMAIL` is absent, body omits — backwards-compat with pre-Phase-3 shape but signer-side rollout-compat means bearer fallback → 401 after cutover. Ops doc calls this out.

### 4.5 Rollout is purely operator-side

- No TUI package publish (`no "main"` / `"bin"`). Consumers run directly from source.
- No rebuild needed — `tsx` reads env at each launch.
- Ops doc update: `docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md` lists TUI env vars alongside Excel addin ones.

---

## 5. Scope — exact file changes (AI-excel-addin `tui/` + docs)

**2 files** of code + 2 doc updates.

| File | Change |
|---|---|
| `tui/src/config.ts` | Add `CHAT_OPERATOR_USER_ID` (with concrete `"operator"` default, per §4.1) + `CHAT_OPERATOR_USER_EMAIL` (empty default). Mirror `CHAT_API_KEY` pattern at line 5. |
| `tui/src/backend-client.ts` | (a) Import the two new constants at top of file. (b) Constructor lines 96-114: accept optional `userId`/`userEmail` opts, default to the two constants. (c) **Line 158** (`ensureSession` — `/chat/init`): extend body to include `user_id` (always) + `user_email` (when truthy) + `context: { channel: "cli" }`. (d) **Line 227** (`streamChat` — `/api/chat`): add `user_id` to body (strict-mode requirement per Codex R1). **Line 316 `/api/chat/tool-approval` is NOT in scope** — handler at `server.py:747-760` is bearer-only, no strict-mode user_id check (Codex R2 confirmed). |

**Docs scope**:

| File | Change |
|---|---|
| `docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md` (risk_module) | Add TUI env-var provisioning block. Document the correct `set -a; source /path/to/risk_module/.env; set +a; npm run start` incantation (plain `.env` format requires allexport). |
| `AI-excel-addin/README.md:123` (Codex R1 nit) | Update the TUI launch section to reflect the env export step. Current doc just says `cd tui && npm install && npm run start` — stale after this change. |

**No tests added** — TUI has no test harness. Scope decision per §2. Test strategy is live-verify (§6).

**No frontend/addin/backend changes** — backend already accepts the fields per §3.5.

---

## 6. Step-by-step implementation

### Step 1 — TUI config + client changes (covers /chat/init AND /api/chat)

Single commit in AI-excel-addin. Work in worktree `~/Documents/Jupyter/AI-excel-addin-multiuser` (on `main`). Branch: `feat/tui-user-email-plumbing`.

1. Update `tui/src/config.ts`: add `CHAT_OPERATOR_USER_ID` (with concrete `"operator"` default) + `CHAT_OPERATOR_USER_EMAIL` (empty default).
2. Update `tui/src/backend-client.ts`:
   - Imports (top of file): add two new constants.
   - Constructor (~line 103-114): accept new opts, store `this.userId` + `this.userEmail`.
   - **`ensureSession` body (~line 158)**: include `user_id` (always) + `user_email` (when truthy) + `context: { channel: "cli" }`.
   - **`streamChat` body (~line 227)**: add `user_id: this.userId` to the existing `{ messages, context }` body. Strict mode enforcement per Codex R1 blocker #1.
   - **`/api/chat/tool-approval` body (~line 316)**: no change needed. Handler at `server.py:747-760` is bearer-token + session-state only, no strict-mode user_id check (Codex R2 confirmed).
3. Update `AI-excel-addin/README.md:123` — TUI launch section now reads:
   ```
   cd tui && npm install
   set -a && source /path/to/risk_module/.env && set +a   # exports CHAT_* and GATEWAY_* vars
   npm run start
   ```
4. Run `tui/$ npm run build` (type-check only via `tsc --noEmit`) — expect zero errors.

Commit: `feat(tui): thread user_id + user_email through /chat/init + /api/chat (Phase 3 Step 3d)`.

Exit criterion: type-check clean. Live-verify in Step 3 confirms signed-claim works end-to-end (init + chat + tool-approval).

### Step 2 — Docs (ops activation runbook)

Single commit in risk_module. Branch: `docs/tui-phase3-activation` (or include in Step 1 AI-excel-addin PR if feasible — but risk_module has its own branch/PR discipline).

1. Update `docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md` — add "TUI env vars" subsection:
   - `CHAT_OPERATOR_USER_ID` (default `"operator"`) + `CHAT_OPERATOR_USER_EMAIL` (optional).
   - Correct launch command: `set -a; source /path/to/risk_module/.env; set +a; npm run start` (repo `.env` uses plain `KEY=value`, not `export KEY=value`).
   - Note env vars read at runtime (no rebuild).
   - Note the `GATEWAY_API_KEY_EXCEL=auto` channel-classification quirk per §3.2b — tracked separately as ops cleanup.

Commit: `docs(ops): TUI operator identity env vars for Phase 3 cutover`.

### Step 3 — Live verification

Not a commit — manual gate before the Phase 3 cutover flag flip.

1. Ensure repo-root `.env` has `CHAT_OPERATOR_USER_ID=<some_id>` + `CHAT_OPERATOR_USER_EMAIL=hc@henrychien.com` (the email one already exists from PR #30).
2. From a fresh shell:
   ```bash
   set -a; source /path/to/risk_module/.env; set +a
   cd /path/to/AI-excel-addin/tui
   npm run start
   ```
3. Trigger a chat message that forces `code_execute`: e.g., *"Use code_execute to call _risk.get_positions() and tell me the total number of tickers."*
4. Approve the tool call.
5. Check gateway + risk_module logs for full chain. Each of these endpoints MUST return 200 (not 400/401 from strict-mode rejection or missing-claim-headers):
   - **`POST /api/chat/init`** (gateway) → 200, session created with `user_id`/`user_email`. **Strict-mode test: verifies blocker #1 from §3.1 is fixed**.
   - **`POST /api/chat`** (gateway streamChat) → 200, streams assistant response. **This is the NEW strict-mode check added in v2** per Codex R1 blocker #1 — validates the `/api/chat` body now includes `user_id`.
   - **`GET /api/agent/registry?tier=*`** (risk_module, from gateway's signed-claim fetcher) → 200.
   - **`POST /api/agent/call`** (risk_module, from sandbox) → 200 with `source: signed_claim`. Not `source: agent_api_key` (would indicate bearer-path fallback, not what we want).

Exit criterion: all four endpoints return 200 with the expected auth path. Phase 3 cutover safe to proceed.

### Step 4 — Cutover

After Step 3 passes, flip `AGENT_API_LEGACY_BEARER_ENABLED=false` in risk_module `.env` and restart. This is a separate operational step, not part of this plan's commits.

---

## 7. Test plan

No new automated tests (TUI has no harness per §2). **Live-verify only** per §6 Step 3.

Existing behavior MUST remain unchanged:
- If `CHAT_OPERATOR_USER_ID` is unset → defaults to `"operator"` (concrete default from §4.1). Body always includes `user_id`.
- If `CHAT_OPERATOR_USER_EMAIL` is unset → body omits `user_email` (backwards-compat; backend tolerates None).
- `/api/chat/init` still returns 200 when backend is in non-strict mode (no resolver configured).
- `/api/chat` flow continues working with the session token from init, now with `user_id` carried on every request.

---

## 8. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Operator uses wrong `.env` source idiom (bare `source` vs `set -a`) | Env vars absent → `user_id` still gets `"operator"` default (OK for strict mode), but `user_email` missing → sandbox bearer fallback → 401 after cutover. Ops runbook + commit message explicitly call out `set -a; source .env; set +a`. |
| 2 | Strict-mode rejection of `_default` user_id — TUI IS broken today | Confirmed broken per §3.2. Plan is fix + Phase 3 unblock. Live-verify in Step 3 validates the fix. |
| 3 | `context: { channel: "cli" }` introduces new behavior (not just auth plumbing) | Per Codex R1: `context.channel` on `/chat/init` is symmetry-not-auth (`server.py:503` only reads `context.user_id` fallback). Low-risk addition. If it breaks something unexpected, remove from same PR. |
| 4 | TUI has no test harness, so regressions could go unnoticed | Manual live-verify + existing backend tests. Cost-benefit: setting up vitest for one test is overkill for a two-file, single-commit change. Accept for now. |
| 5 | Cutover ordered wrong — flag flipped before Step 3 verify | Explicit cutover happens in Step 4, post-verify. Flag flip is single env-var change, reversible in <30s. |
| 6 | Different consumers (future TUI wrappers / scripts) bypass the env var | Plan pattern uses constructor override (opts.userId/userEmail) so wrappers can pass explicitly. Env var is the sensible default, not the only path. |

---

## 9. Codex review resolutions

### R2 resolutions (2026-04-24, v2 → v3)

- **R2 Blocker (stale `source .env && ...` still in §2, §3.4, §6 Step 3)** → All three updated to `set -a; source .env; set +a; npm run start`.
- **R2 Recommend (§7 omit-on-unset + §8 Risk #2 stale)** → §7 updated: `user_id` defaults to `"operator"`, only `user_email` is omit-on-unset. §8 Risk #2 updated: TUI IS confirmed broken today, not "may be broken."
- **R2 Recommend (`/chat/tool-approval` close as no-change)** → §3.1, §4.2, §6 Step 1 all updated to explicitly say "no change needed" with citation to `server.py:747-760`. Previously left as open item.
- **R2 Recommend (Step 3 verify `/api/chat` success explicitly)** → §6 Step 3 rewritten as a 4-endpoint checklist: `/api/chat/init`, `/api/chat`, `/api/agent/registry`, `/api/agent/call`. Each with explicit 200 + auth-path expectation.

### R1 resolutions (2026-04-24, v1 → v2)

- **R1 Blocker #1 (/api/chat also needs user_id)** → §3.1, §4.2, §5, §6 Step 1 all updated. `streamChat` at `backend-client.ts:227` gets `user_id` threading. `/api/chat/tool-approval` at line 316 added to scope with "verify if strict mode enforces there too; thread if needed" instruction.
- **R1 Blocker #2 (wrong env-sourcing command)** → §4.4 + §6 Step 1.3 + §6 Step 2 updated. Correct idiom: `set -a; source .../risk_module/.env; set +a; npm run start`. Plain `.env` files (no `export` prefix) need allexport mode.
- **R1 Recommend (user_id empty-omit won't work under strict mode)** → §4.1 updated: `CHAT_OPERATOR_USER_ID` defaults to `"operator"` (concrete default, matching Excel addin's `DEFAULT_CHAT_OPERATOR_USER_ID` at `chatContract.ts:9`). `user_email` stays empty-omit (optional field).
- **R1 Recommend (Q1 TUI broken today)** → §3.2 updated: TUI IS currently broken against strict multi-user gateway, not "maybe broken." This plan is both a Phase 3 cutover unblock AND a strict-mode bug fix.
- **R1 Recommend (context.channel on /chat/init is symmetry, not auth)** → §4.3 updated. Include for symmetry with Excel addin, but not treated as auth-critical. `tui.ts:516` already sends channel on `/api/chat`.
- **R1 Recommend (Q3 `"auto"` sentinel + GATEWAY_API_KEY_EXCEL channel mismatch)** → §3.2b new subsection documents the quirk — TUI gets classified as `excel` channel today due to `GATEWAY_API_KEY_EXCEL=auto`. Out of scope for this plan; noted for separate ops cleanup.
- **R1 Recommend (scope complete, no extra callers missed)** → Confirmed. Only in-repo `BackendClient` constructor is `tui.ts:75` with no explicit opts.
- **R1 Recommend (rollout order correct)** → Confirmed. Verify first, then cutover flip.
- **R1 Nit (README.md:123 stale)** → §5 + §6 Step 1.3 add `AI-excel-addin/README.md:123` to scope. Launch section updated to reflect `set -a` sourcing.

---

## 10. Ship log

_(To be filled on ship.)_

---

## 11. Change log

**v3 (2026-04-24)**: Codex R2 FAIL — residual §5↔§6/§7/§8 propagation drift (same feedback pattern). Fixes:
- `source .env` → `set -a; source .env; set +a` in §2, §3.4, §6 Step 3.
- §7 behavior section updated to reflect concrete user_id default from v2 §4.1.
- §8 Risk #2 confirmed "TUI IS broken today" (not "may be").
- `/chat/tool-approval` closed as no-change (bearer-only auth per `server.py:747-760`); removed from open-scope language in §3.1, §4.2, §6 Step 1.
- §6 Step 3 live-verify now explicitly checks 4 endpoints (init + chat + registry + call) with expected auth paths.

**v2 (2026-04-24)**: Codex R1 FAIL. Two blockers + five recommends + one nit integrated:
- Scope expanded: `/api/chat` body also needs `user_id` (strict-mode enforcement at `server.py:577`). `/api/chat/tool-approval` added to scope for verification.
- Env-sourcing command corrected: `set -a; source .env; set +a; npm run start` (plain `.env` format needs allexport; bare `source` doesn't propagate vars to child Node process).
- `user_id` default changed from empty-omit to concrete `"operator"` (matches Excel addin precedent, satisfies strict mode).
- Confirmed TUI is broken today against live strict-mode gateway (not "maybe broken"). Plan is fix + unblock.
- `context.channel` reclassified as symmetry-with-Excel, not auth-driving.
- `GATEWAY_API_KEY_EXCEL=auto` channel-classification quirk documented (§3.2b, out of scope).
- `AI-excel-addin/README.md:123` added to docs scope.
- §5↔§6 sync verified per `feedback_plan_scope_step_drift.md` (every new file in §5 has a matching §6 Step 1 sub-step).

**v1 (2026-04-24)**: Initial draft. Scope: 2 TUI files (`config.ts`, `backend-client.ts`) + 1 doc. Runtime `process.env` pattern (not build-time DefinePlugin like Excel addin — TUI uses `tsx`, no webpack). Unblocks Phase 3 cutover.
