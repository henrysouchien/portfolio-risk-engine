# Agent API Phase 3 — Excel Addin Client user_email Plumbing

**Status**: DRAFT v3 — revised per Codex R2 FAIL (2026-04-22). All residual consistency drift fixed. See §11 change log.
**Date**: 2026-04-22
**Parent plan**: `docs/planning/AGENT_API_SIGNED_USER_CLAIM_PLAN.md` (Codex PASS R5, shipped 2026-04-22)
**Gap**: the parent plan's Step 3 updated the risk_module proxy caller of `/chat/init` but missed the **Excel addin frontend** (separate caller at `src/taskpane/chatContract.ts`). This plan closes that gap.
**Blocking**: Phase 3 cutover (flip `AGENT_API_LEGACY_BEARER_ENABLED=false`). Without this fix, Excel addin sessions would have `session.user_email=None` → signer skips claim injection → sandbox falls back to bearer → cutover 401s every Excel addin `code_execute` call.

---

## 1. Goal

Thread `user_email` through the Excel addin's `/api/chat/init` call so the running signer (Phase 3 Step 4) has both `session.user_id` AND `session.user_email` available when spawning sandboxes. After this ships, Excel addin sessions match the risk_module proxy sessions — signed claims work end-to-end.

---

## 2. Non-goals

- **No Office SSO, no OAuth flow.** The addin has no email today (verified via research 2026-04-22); we use a build-time env var that mirrors the existing `CHAT_OPERATOR_USER_ID` pipeline. One-operator-per-install model is fine for Phase 3.
- **No TUI / Telegram changes.** `tui/src/backend-client.ts:153` is a different consumer with its own init shape (doesn't send `user_id`, uses `chatApiKey` directly). `telegram_bot/backend_client.py:163` is also a `/chat/init` caller. Neither is the bearer-off cutover blocker for the Excel addin fix. CORRECTION (Codex R1): TUI uses `cli` channel which IS in `CODE_EXECUTION_CHANNELS` per `tool_catalog.py:55` + `runtime.py:421` — so TUI sessions DO trigger code_execute. TUI fix is a separate follow-up with the same shape; leaving out of this plan to keep scope tight. Telegram is NOT in `CODE_EXECUTION_CHANNELS` so it's a non-concern for the cutover.
- **No backend changes.** `packages/agent-gateway/agent_gateway/server.py:46-51` `ChatInitRequest` already accepts top-level `user_email: str | None = None` (shipped as Step 3b in the parent plan). This plan wires up the caller.
- **No per-user prompt UX.** If ops deploys multiple users sharing the same addin install, that's a separate product concern; not in scope here.

---

## 3. Current state (verified 2026-04-22)

### 3.1 The gap
- Excel addin frontend: `src/taskpane/chatContract.ts:18-24` — `buildExcelChatInitRequest(apiKey, userId)` returns `{api_key, user_id, context}`. **No `user_email`.**
- Callers of `ChatService.initSession(apiKey, userId)`:
  - `src/taskpane/taskpane.ts:337` (initial boot / session restore)
  - `src/taskpane/taskpane.ts:1002` (auth-expired re-init)
- Both pass the module-level constant `CHAT_OPERATOR_USER_ID` (line 30-31 of `taskpane.ts`), which originates from `chatContract.ts:16` — a build-time env var substitution via `webpack.config.js:74` `DefinePlugin`.

### 3.2 Existing `CHAT_OPERATOR_USER_ID` pattern (the template to mirror)
- `chatContract.ts:9` — `DEFAULT_CHAT_OPERATOR_USER_ID = "operator"` (fallback if env unset)
- `chatContract.ts:11-14` — `resolveChatOperatorUserId(rawUserId)` — trims, falls back to default
- `chatContract.ts:16` — `CHAT_OPERATOR_USER_ID = resolveChatOperatorUserId(process.env.CHAT_OPERATOR_USER_ID)`
- `webpack.config.js:74` — `DefinePlugin` replaces `process.env.CHAT_OPERATOR_USER_ID` at build time with the literal string

### 3.3 Backend readiness (already shipped Step 3b)
- `packages/agent-gateway/agent_gateway/server.py:46-51` — `ChatInitRequest` Pydantic model has `user_email: str | None = None` (optional).
- `packages/agent-gateway/agent_gateway/server.py:498-502,545` — normalizes empty strings to None and forwards to session creation.
- `packages/agent-gateway/agent_gateway/session.py:21,157` — `GatewaySession.user_email` persists; JWT session tokens carry it.
- Tests at `packages/agent-gateway/tests/test_server_multi_user.py:73-80,118,159-167` exercise the field.

### 3.4 Threat model — why "operator-level email" is acceptable for v1
The signed claim's `user_email` is used by the agent API's `has_user_email` registry functions to force-inject the email as the user-scoping key (routes/agent_api.py:90). In Excel addin's current single-tenant model (one install = one operator), an install-time env var matches the deployment reality. Multi-tenant addin deployments (if ever done) would need a proper auth flow — but that's a product-shape change far bigger than this plan.

---

## 4. Scope — exact file changes (AI-excel-addin only)

**4 files total** (Codex R1 nit corrected — ChatService.ts does not need a code change):

| File | Change |
|---|---|
| `webpack.config.js` | Add `CHAT_OPERATOR_USER_EMAIL` to `DefinePlugin` |
| `src/taskpane/chatContract.ts` | Add resolver + constant + extend `buildExcelChatInitRequest` |
| `src/taskpane/types/index.ts` | Add `user_email?: string` to `ChatInitRequestBody` |
| `tests/taskpane/chat-service.test.js` (or sibling) | Add unit test for request-body shape |

Plus ops docs (not code): `docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md` (risk_module) + `README.md` (AI-excel-addin).

No backend changes. No risk_module code changes.

### 4.1 `webpack.config.js:74`

Add to the existing `DefinePlugin` env object:
```js
"process.env.CHAT_OPERATOR_USER_EMAIL": JSON.stringify(process.env.CHAT_OPERATOR_USER_EMAIL || ""),
```
Build-time replacement. Empty string default means "not set" — consumer code treats it as falsy.

### 4.2 `src/taskpane/chatContract.ts`

Add email resolver + constant, mirroring the user_id pattern:
```ts
const DEFAULT_CHAT_OPERATOR_USER_EMAIL = "";  // empty = not set

export function resolveChatOperatorUserEmail(rawUserEmail: string | null | undefined): string {
  const trimmed = String(rawUserEmail || "").trim();
  return trimmed || DEFAULT_CHAT_OPERATOR_USER_EMAIL;
}

export const CHAT_OPERATOR_USER_EMAIL = resolveChatOperatorUserEmail(process.env.CHAT_OPERATOR_USER_EMAIL);
```

Update `buildExcelChatInitRequest` signature to accept email and emit it only when truthy (keeps backwards-compat for deploys that don't set it):
```ts
export function buildExcelChatInitRequest(
  apiKey: string,
  userId: string,
  userEmail: string = CHAT_OPERATOR_USER_EMAIL,
): ChatInitRequestBody {
  const body: ChatInitRequestBody = {
    api_key: apiKey,
    user_id: userId,
    context: { channel: EXCEL_CHAT_CHANNEL },
  };
  if (userEmail) {
    body.user_email = userEmail;
  }
  return body;
}
```

### 4.3 `src/taskpane/types/index.ts`

Add `user_email?: string` to `ChatInitRequestBody`:
```ts
export interface ChatInitRequestBody {
  api_key: string;
  user_id: string;
  user_email?: string;  // NEW
  context: { channel: string };
}
```

### 4.4 `src/taskpane/services/ChatService.ts` — NO CHANGE NEEDED (Codex R1 nit)

`buildExcelChatInitRequest` defaults to the module-level `CHAT_OPERATOR_USER_EMAIL` constant, so `ChatService.initSession(apiKey, userId)` signature stays unchanged. Existing callers at `taskpane.ts:337,1002` work without modification.

(If we later want per-session email injection — e.g., from a UI prompt — we'd thread a third arg through. Out of scope; default-param works for v1.)

### 4.5 Env var location (Codex R1 blocker #1 — CRITICAL FIX)

**The addin's webpack build reads `api/.env`, NOT repo-root `.env` or `.env.example`.**

Per `webpack.config.js:10` — manually reads `api/.env` via `fs.readFileSync` (Codex R2 nit — original v2 quote used `dotenv.config` which is not the actual mechanism; conclusion is unchanged, evidence corrected).

Plus `README.md:84` documents the build-time env convention as "`api/.env` or shell-exported." The v1 plan incorrectly told ops to set `CHAT_OPERATOR_USER_EMAIL` in repo-root `.env` or create a root `.env.example` — that would NOT propagate into the addin bundle and the cutover would fail.

**Correct path**: add `CHAT_OPERATOR_USER_EMAIL` to `api/.env` (or export in shell before `npm run build`). No `.env.example` file needed since the repo doesn't use one.

**Docs** (Codex R1 recommend): update `docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md` (risk_module) AND `README.md` (AI-excel-addin) to note the `api/.env` location and the "addin rebuild required after setting env var" caveat.

---

## 5. Step-by-step implementation

Single commit in AI-excel-addin. Small enough to not warrant splitting.

### Step 1 — Add `CHAT_OPERATOR_USER_EMAIL` plumbing

1. Update `webpack.config.js:74` to add the new env var to `DefinePlugin`.
2. Update `src/taskpane/chatContract.ts` — add `resolveChatOperatorUserEmail`, `DEFAULT_CHAT_OPERATOR_USER_EMAIL`, `CHAT_OPERATOR_USER_EMAIL`, extend `buildExcelChatInitRequest` signature with default param.
3. Update `src/taskpane/types/index.ts` — add `user_email?: string` to `ChatInitRequestBody`.
4. Update docs only (no `.env.example` — repo convention is `api/.env`): `docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md` (risk_module) + `README.md` (AI-excel-addin).
5. Add unit test at `tests/taskpane/chat-service.test.js` or a sibling JS test file in that dir. The taskpane test harness loads TS via `tests/taskpane/load-ts-module.js:58` per `package.json:25` `npm test` script. A TS `__tests__` subfolder would not be picked up by the existing runner. Assertions: if `CHAT_OPERATOR_USER_EMAIL` is set, request body includes `user_email`; if empty, request body omits it; if whitespace-only, treated as empty.

Commit: `feat(addin): thread CHAT_OPERATOR_USER_EMAIL through /chat/init (Phase 3 Step 3c)`.

Exit: tests pass; built addin bundle includes the new env var substitution.

### Step 2 — Provision the value + local verification

Not a commit, but a rollout gate:
1. Set `CHAT_OPERATOR_USER_EMAIL=hc@henrychien.com` (or whatever email) in **`api/.env`** (Codex R1 blocker #1 — NOT repo-root .env; webpack.config.js:10 loads `api/.env`).
2. Rebuild the addin: `npm run build` (webpack runs DefinePlugin, substitutes the env var into the bundle).
3. Restart the gateway service so it serves the rebuilt bundle to the addin.
4. Open Excel addin, trigger a chat with a `code_execute` request.
5. Check `risk_module` logs for `source: signed_claim` on `/api/agent/call`.
6. If signed-claim path is used → cutover is safe.

---

## 6. Test plan

**New tests (AI-excel-addin)**:
- `tests/taskpane/chat-service.test.js` or a sibling JS file in that dir (matches existing `npm test` harness via `load-ts-module.js`) — `buildExcelChatInitRequest` with email set → body includes `user_email`; empty email → body omits `user_email`; trimmed whitespace → treated as empty.

**Existing tests must pass unchanged**:
- Any existing `ChatService` tests — signature of `buildExcelChatInitRequest` is backwards-compat (default param).

**Live verification** (Step 2):
- Excel addin session → `/api/chat/init` with `user_email` → gateway stores → sandbox spawn → signed claim → risk_module `source: signed_claim`.
- Verify BOTH the signed-claim path (email set) AND the bearer-fallback path (email unset) — toggle `CHAT_OPERATOR_USER_EMAIL` in **`api/.env`**, rebuild via `npm run build`, re-test.

---

## 7. Rollout sequencing

Phase 3 cutover gate updated:
1. ✅ Ship verifier (Phase 3 Step 1) — done
2. ✅ Ship risk_client dual-mode (Phase 3 Step 2) — done
3. ✅ Ship `/chat/init` user_email on risk_module proxy (Phase 3 Step 3a) — done
4. ✅ Ship `/chat/init` user_email on gateway (Phase 3 Step 3b) — done
5. **← THIS PLAN: Ship Excel addin client user_email (Phase 3 Step 3c)**
6. ✅ Ship signer + HMAC denylist (Phase 3 Step 4) — done
7. ✅ Ship registry fetcher migration (Phase 3 Step 5) — done
8. Set `CHAT_OPERATOR_USER_EMAIL` in **`api/.env`** (NOT repo-root `.env`) + rebuild Excel addin (`npm run build`)
9. Observe: all Excel addin `code_execute` calls show `source: signed_claim` in risk_module logs
10. Cutover: flip `AGENT_API_LEGACY_BEARER_ENABLED=false` in risk_module, revoke static `AGENT_API_KEY`

Step 5 is this plan. Steps 8-10 are ops execution (not in scope of this plan).

---

## 8. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Operator sets `CHAT_OPERATOR_USER_EMAIL` in wrong `.env` (repo-root instead of `api/.env`) — webpack silently ignores | Codex R1 blocker — documented in §4.5 + activation runbook. Cutover gate at Step 9 (log observation) catches before Step 10 flip. |
| 2 | Addin bundle rebuilds needed for env change to take effect | Webpack is build-time. `api/.env` change requires `npm run build` + gateway restart. Activation runbook calls this out. |
| 3 | Operator forgets to set `CHAT_OPERATOR_USER_EMAIL` entirely | Rollout compat (Step 4's `session.user_email is None` → bearer fallback) keeps working until bearer is off. Step 9 log-observation gate detects absence before Step 10. |
| 4 | Email gets hardcoded to one operator even in multi-user deploys | Explicit non-goal (§2). Current Excel addin is single-tenant-per-install. Multi-tenant would require real auth flow — separate product decision. |
| 5 | Type drift between `ChatInitRequestBody` and backend `ChatInitRequest` | Field is optional on both sides. Backend accepts either; frontend omits when empty. No coupling issue. |

---

## 9. Codex review resolutions

### R2 resolutions (2026-04-22, v2 → v3)

- **R2 Blocker (env-path not propagated to live verification)** → §6 test plan live-verification step now says `api/.env` (was still saying `.env`).
- **R2 Recommend #2 (.env.example contradiction)** → §5 Step 1 step 4 rewritten to say "no `.env.example` — repo convention is `api/.env`." Removes the "if acceptable, create one" hedge.
- **R2 Recommend #3 (test location drift between §5 and §6)** → §6 test list now points to `tests/taskpane/chat-service.test.js` (matches §5 Step 1 step 5). Removed stale `chatContract.test.ts` reference.
- **R2 Nit (webpack evidence wrong)** → §4.5 corrected: `fs.readFileSync` in `webpack.config.js:10`, not `dotenv.config`. Conclusion unchanged.
- **R2 Nit (stale open-questions + duplicate risk #3)** → §9 replaced with resolutions (this section). Risk table renumbered 4/5 (was duplicate 3).

### R1 resolutions (2026-04-22, v1 → v2)

- **Blocker**: §4.5 rewritten — webpack loads `api/.env`, NOT repo-root `.env`. Step 2, Step 8, and Risk #1 also updated to reference `api/.env`.
- Recommend: §2 TUI/Telegram rationale tightened — TUI channel `cli` IS in `CODE_EXECUTION_CHANNELS`; Telegram is not. Both out of scope for this plan.
- Recommend: §6 unit test location corrected — `tests/taskpane/chat-service.test.js` or sibling JS (matches `npm test` harness).
- Nit: §4 file-count corrected — 4 files; ChatService.ts doesn't need change.

---

## 10. Ship log

**Shipped 2026-04-23** via [AI-excel-addin PR #30](https://github.com/henrysouchien/AI-excel-addin/pull/30) — merge commit `ba91d9c`. Single feature commit `4207199` on branch `feat/agent-api-excel-addin-user-email`. 4 files changed, 5/5 taskpane tests pass, `npm run build` succeeds.

### Post-ship discovery — Step 3c turned out to be pre-emptive, not blocking

Live verification in the follow-up session (2026-04-23) revealed that **the `excel` channel is NOT in `CODE_EXECUTION_CHANNELS`** at `tool_catalog.py:55` (`{"web", "cli"}`). The Excel addin never invokes `code_execute`, so it never hits `/api/agent/call`, so signed-claim auth doesn't apply to its traffic.

Implication: this PR was NOT actually blocking the Phase 3 bearer-off cutover for the Excel addin's current code paths. The fix is still valuable as:
- **Forward-looking defense** — if `code_execute` is ever enabled on the `excel` channel, the user_email plumbing is already in place.
- **Consistency** — every `/chat/init` caller now threads identity consistently.
- **Symmetric** — matches what the risk_module proxy does for web/cli channels.

### Actual cutover blocker discovered during live test

The **TUI / `cli` channel** uses `code_execute` (per `tool_catalog.py:55` + `runtime.py:421` — confirmed by Codex R1 on this plan), but `tui/src/backend-client.ts:158` sends only `{api_key}` on `/chat/init` — no `user_id`, no `user_email`. Before bearer-off cutover, TUI sessions would fall back to bearer and break.

TUI fix is a separate follow-up (Step 3d). Out of scope for this plan; tracked in `docs/TODO.md` as part of the cutover prerequisites.

### Env var provisioning (done on this host)

`CHAT_OPERATOR_USER_EMAIL=hc@henrychien.com` appended to `.env` (which is symlinked at `AI-excel-addin/api/.env` → `risk_module/.env`, convenient but note-worthy). Addin rebuilt via `npm run build`; `dist/taskpane.js` confirmed to contain the operator email substituted at build time.

---

## 11. Change log

**v3 (2026-04-22)**: Codex R2 FAIL (all residual consistency drift — §5/§6/§8/§9 out of sync with §4.5 blocker-fix). Fixes:
- §6 live-verification step → `api/.env` (was stale `.env`).
- §5 Step 1 step 4 → "no `.env.example`" (removed "if acceptable" hedge).
- §6 test list → `chat-service.test.js` (dropped stale `chatContract.test.ts` reference).
- §4.5 webpack evidence → `fs.readFileSync` (was incorrect `dotenv.config` quote).
- Risk table renumbered (was duplicate #3).
- §9 replaced with explicit R1/R2 resolutions (was stale open questions).

**v2 (2026-04-22)**: Codex R1 FAIL. Four fixes applied:
- **Blocker**: §4.5 rewritten — webpack loads `api/.env`, NOT repo-root `.env`. v1 would have shipped with wrong env location and cutover would have failed silently. Step 2, Step 8, and Risk #1 also updated to reference `api/.env`.
- Recommend: §2 TUI/Telegram rationale tightened — TUI channel `cli` IS in `CODE_EXECUTION_CHANNELS`; Telegram is not. Both out of scope for this plan (separate follow-ups needed for TUI).
- Recommend: §6 unit test location corrected — `tests/taskpane/chat-service.test.js` or sibling JS in that dir (not TS `__tests__`; `npm test` wouldn't pick it up).
- Nit: §4 file-count corrected — 4 files (not 5); ChatService.ts doesn't need a code change.

**v1 (2026-04-22)**: Initial draft. Gap identified during Phase 3 cutover planning when risk_module logs showed the Excel addin `chatContract.ts:buildExcelChatInitRequest` wasn't updated alongside the risk_module proxy + gateway server in parent plan's Step 3.
