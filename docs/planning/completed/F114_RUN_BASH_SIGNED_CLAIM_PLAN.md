> **✅ SHIPPED — closed by AI-excel-addin `baa1ab58` + risk_module `a478e853` (2026-05-20; see `docs/TODO_COMPLETED.md`). Moved from `docs/planning/` during 2026-05-26 docs cleanup.**

# F114 — Inject signed claim into approved `run_bash` subprocesses

## Context

`AI-excel-addin` autonomous `managing-risk` smoke (2026-05-19) called `risk_client.RiskClient().call(...)` from inside `run_bash` and got HTTP 401 from `risk_module`'s `/api/agent/call`. F114 framed this as an auth-contract decision; user picked **Option A** — mint a short-lived signed claim and inject the 7 `AGENT_API_CLAIM_*` env vars into approved `run_bash` subprocesses, mirroring the existing pattern that already works for the `code_execute` channel.

### Why the bug exists today

| Layer | What it does | Why it fails |
|---|---|---|
| `risk_module/routes/agent_api.py:36-44` | If `AGENT_API_SIGNED_CLAIM_ENABLED=true` and `AGENT_API_LEGACY_BEARER_ENABLED=false` (prod cutover state, `.env.colleague.template:107`), rejects any non-claim request with 401 "Signed user claim required". | Prod is signed-claim-only; bearer is dead. |
| `AI-excel-addin/api/agent/interactive/runtime.py:910-922` | Wires `_prepare_env_with_signed_claim` as `prepare_env` callback **only for `code_execute`**. | `run_bash` has no equivalent hook in any path (dev or non-dev). |
| `AI-excel-addin/api/agent/shared/tool_handlers.py:740-776` + `local_tools.py:454-541, 575-592` | `run_bash` handler captures a static `extra_env` at construction time; subprocess starts from `os.environ.copy()` + `extra_env`, then strips sandbox secrets. | No per-call claim minting; static env can't carry a fresh-each-time claim. |
| `AI-excel-addin/api/agent/autonomous/entry.py:18, 26-31` | Bootstrap loads HMAC key from SSM-resolved env, then `entry.py:31` pops `AGENT_API_USER_CLAIM_HMAC_KEY` per spec §5.5.1 *before* importing the runner module. | Runner-side code that tries to read the HMAC key via env (e.g., `get_agent_api_user_claim_hmac_key()`) finds an empty string. Without explicit capture, autonomous cannot mint claims. |
| `AI-excel-addin/api/agent/autonomous/entry.py:394` + `profiles/analyst.py:939` | Autonomous passes `extra_env={"PYTHONPATH": DEV_PYTHONPATH}`. | No `AGENT_API_CLAIM_*` injected. RiskClient falls back to bearer; server rejects bearer → 401. |

The F114 note's "gateway strips signing secrets by design" detail is partially right — the gateway sandbox denylist strips HMAC from the bash *subprocess* env (`packages/agent-gateway/agent_gateway/code_execution/_helpers.py:29-38`), AND the autonomous `entry.py` strips HMAC from the *parent runner process* env. The 7 pre-signed `AGENT_API_CLAIM_*` env vars are not on either denylist; minting just hasn't been wired for `run_bash`.

### Outcome

Approved analyst subprocesses (autonomous + interactive dev *and* non-dev) receive a freshly-signed claim per `run_bash` call. `RiskClient` reads it (already supported — `risk_client/__init__.py:49-99`) and the call authenticates as the right user. The autonomous `managing-risk` smoke from F114 passes. No server-side change required.

---

## Design

### 1. Mirror the `code_execute` `prepare_env` callback pattern for `run_bash`

`code_execute` already does what we need: a `prepare_env: Callable[[Dict[str,str]], Dict[str,str]] | None` callback that mints a fresh claim from the live caller and is invoked per execution. See `packages/agent-gateway/agent_gateway/code_execution/_helpers.py:131-147` — env is built (base + extra_env), prepare_env mutates, then sandbox secrets are stripped. We thread the same callback through the local-tools handler stack for `run_bash`.

The claim minter (`sign_user_claim` from `api/agent/interactive/_agent_claim.py:38-63`) is already shared infra — used today by `interactive/runtime.py:566` AND `mcp_servers/agents_mcp/subprocess_runner.py:12, 268`. We reuse it.

### 2. Autonomous: capture HMAC key before `entry.py` strips it

`entry.py:31` pops `AGENT_API_USER_CLAIM_HMAC_KEY` from `os.environ` between bootstrap and runner import. This is a deliberate security boundary. To mint claims post-strip, capture the HMAC key into a local variable in `entry.py` BEFORE the pop, then pass it through the runner call chain as an explicit parameter (not via env).

**Import-order discipline** (per Codex v2 blocker 1): `python -m agent.autonomous` runs `__init__.py` first (which does `from .runner import *` at line 21, loading `runner.py` module body BEFORE `entry.py` runs). This means:
- `runner.py` must NEVER read `AGENT_API_USER_CLAIM_HMAC_KEY` at module level. Closure construction is at *function-call time* (inside `runner.run(claim_hmac_key=...)`), capturing the kwarg.
- We add an explicit audit step (grep `runner.py` for HMAC reads — must be zero at module scope) and a regression test that exercises the `python -m agent.autonomous` import order with HMAC present in env.

Shape:
```python
# entry.py — before strip
claim_hmac_key = os.environ.get("AGENT_API_USER_CLAIM_HMAC_KEY", "").strip() or None
os.environ.pop("AGENT_API_USER_CLAIM_HMAC_KEY", None)
# ... pass claim_hmac_key through to runner.run(...)
```

Runner receives `claim_hmac_key` as a kwarg, builds a `prepare_env` closure that captures `(claim_hmac_key, user_id, user_email)`, and passes that closure to `_build_local_tool_handlers`. **No env-based lookup inside the runner.** Closure no-ops (logs once at WARN, returns env unchanged) if ANY of `(claim_hmac_key, user_id, user_email)` is missing — `user_email` is optional in autonomous identity resolution (`entry.py:107-129`), so we must not pass `None` into `sign_user_claim`.

### 3. Interactive (both dev and non-dev) uses an extended `_prepare_env_with_signed_claim`

`runtime.py:551-573` already implements the right wrapper, reading HMAC from env (which the interactive parent gateway holds normally — no entry-style strip). **But** it currently calls `sign_user_claim(..., ttl_seconds=get_agent_api_claim_ttl_seconds())` — 300 s default. For run_bash we need 600 s (per §4).

Fix: add a `ttl_seconds: int | None = None` kwarg to `_prepare_env_with_signed_claim`. If `None`, preserve the existing `get_agent_api_claim_ttl_seconds()` default (so `code_execute` callers — `runtime.py:910-922` — keep their current 300 s behavior). For `run_bash` callers, pass `ttl_seconds=RUN_BASH_CLAIM_TTL_SECONDS`.

Wire the wrapper into `_build_local_tool_handlers` at BOTH call sites:
- `runtime.py:868-875` (dev mode, where `run_bash` is auto-approved per `_DEV_MODE_ALLOWED`)
- `runtime.py:887-892` (non-dev, where `run_bash` is gated via `LOCAL_TOOLS` in `tool_catalog.py:792` and requires user approval per `GATED_TOOLS`)

Both paths need the hook because both can ultimately reach the `run_bash` handler.

### 4. Per-call (not per-handler) minting; explicit 600 s TTL

`prepare_env` is invoked at each `run_bash` call inside `local_tools.run_bash`, not once at handler construction. Each call produces a fresh nonce + issued_at + expiry, so concurrent or sequential calls don't share claim state.

For the TTL: `run_bash`'s wall-clock cap is `MAX_BASH_TIMEOUT_MS = 600_000` (`local_tools.py:19`). The server max is `AGENT_API_CLAIM_MAX_TTL_SECONDS = 600` (`risk_module/settings.py:32`; the server-side verifier ceiling lives at `risk_module/utils/agent_claim.py:87`). The existing `get_agent_api_claim_ttl_seconds()` defaults to 300 with no upward clamp — wrong for run_bash. We add a new constant in `_agent_claim.py`:

```python
RUN_BASH_CLAIM_TTL_SECONDS = 600  # matches server AGENT_API_CLAIM_MAX_TTL_SECONDS default
```

…and use it directly for `run_bash` claim minting (NOT `get_agent_api_claim_ttl_seconds()`). RiskClient re-reads env on every request (`risk_client/__init__.py:93-99`), so as long as the bash subprocess env is valid for the 600 s wall clock, every internal API call inside that bash command authenticates.

**Deployment invariant (must hold)**: `risk_module` `AGENT_API_CLAIM_MAX_TTL_SECONDS` must remain ≥ 600. If a deployment lowers it (e.g., to 300), our minted claims would be rejected by the server-side verifier. Document this in the plan ship-checklist; consider a defensive runtime fetch of the server-asserted ceiling in a future iteration (out of scope here).

### 5. Mint location is the parent process; subprocess strip removes HMAC

For both autonomous (HMAC captured before entry strip) and interactive (HMAC available in gateway env), minting happens in the parent process. The 7 `AGENT_API_CLAIM_*` env vars are added to the subprocess env via `prepare_env`. The existing `_strip_sandbox_secrets` pass at end of `local_tools.run_bash` removes `AGENT_API_USER_CLAIM_HMAC_KEY` from the subprocess env even if somehow set. No denylist change.

### 6. No server-side change

`RiskClient.__init__` already prefers signed-claim headers over bearer when both are present (`risk_client/__init__.py:93-99`). The server already accepts signed claims (`routes/agent_api.py:38-67`). The contract works end-to-end the moment we inject the env vars.

---

## Scope and files

**In scope:**

| File | Change |
|---|---|
| `AI-excel-addin/api/agent/interactive/_agent_claim.py` | Add `RUN_BASH_CLAIM_TTL_SECONDS = 600` module constant + export. Doc comment: "must not exceed server `AGENT_API_CLAIM_MAX_TTL_SECONDS` (default 600 s)." |
| `AI-excel-addin/api/local_tools.py` | `run_bash` accepts optional `prepare_env: Callable[[Dict[str,str]], Dict[str,str]] | None`; applies it AFTER `extra_env` merge and BEFORE the existing `_strip_sandbox_secrets` (preserves the strip-last safety belt). `execute` (line 575+) forwards `prepare_env` through to `run_bash`. |
| `AI-excel-addin/api/agent/shared/tool_handlers.py` | `_build_local_tool_handlers` accepts optional `prepare_env`; `_make_local_handler` factory for `run_bash` only closes over it and forwards to `execute_local_tool`. Other local tools (`file_read`, `file_write`, etc.) unaffected. |
| `AI-excel-addin/api/agent/autonomous/entry.py` | Before line 31's `os.environ.pop("AGENT_API_USER_CLAIM_HMAC_KEY", None)`, capture key into local `claim_hmac_key`. Thread through call chain into `runner.run(...)` as an explicit kwarg. |
| `AI-excel-addin/api/agent/autonomous/runner.py` | New kwarg `claim_hmac_key: str | None` on the relevant top-level run entry. Build `prepare_env_for_bash` closure capturing `(claim_hmac_key, user_id, user_email)` at FUNCTION-CALL time (not module level — per import-order discipline). Closure no-ops (logs once at WARN, returns env unchanged) if ANY of `(claim_hmac_key, user_id, user_email)` is missing. Pass closure to `build_local_tool_handlers_fn(...)`. Audit: confirm no module-level HMAC reads anywhere in this file. |
| `AI-excel-addin/api/agent/interactive/_agent_claim.py` (existing) | Extend signature: `sign_user_claim(...)` already takes `ttl_seconds`. No change needed there. |
| `AI-excel-addin/api/agent/interactive/runtime.py` | Extend `_prepare_env_with_signed_claim(env, *, session, ttl_seconds: int | None = None)`. When `ttl_seconds is None`, fall back to `get_agent_api_claim_ttl_seconds()` (preserves `code_execute` 300 s default). Wire run_bash callers to pass `ttl_seconds=RUN_BASH_CLAIM_TTL_SECONDS`. Both `_build_local_tool_handlers` calls (dev line ~868 and non-dev line ~887) receive the bash-tuned wrapper. |
| `AI-excel-addin/mcp_servers/agents_mcp/subprocess_runner.py` | Line 277: remove `env.pop("AGENT_API_USER_CLAIM_HMAC_KEY", None)`. Let the spawned `entry.py` strip it inside the child per spec §5.5.1. |
| `AI-excel-addin/api/agent/profiles/prompts/analyst_dev.md` (lines 50-63) | Replace bearer guidance with claim-aware guidance: drop `RISK_API_KEY` mention; say "RiskClient automatically authenticates as the current user via signed-claim env vars injected by the agent runtime — no extra config needed." |
| `AI-excel-addin/tests/` (new test module) | See Test Coverage section below. |

**Out of scope (deliberately):**

- Removing `RISK_API_KEY` env from the parent gateway env. RiskClient prefers claim over bearer when both present, so leaving bearer alongside is harmless during the transition.
- Changing the sandbox denylist. `AGENT_API_USER_CLAIM_HMAC_KEY` stays on it; the 7 claim env vars stay off.
- Server-side (`risk_module`) changes. None needed.
- TUI / cron / Telegram / Excel-addin web channels — none expose `run_bash`.
- Bumping `AGENT_API_CLAIM_TTL_SECONDS` env from 300 → 600 globally. Per Codex review v3: `subprocess_runner.py:268` and `system_prompt.py:1031` are other claim minters; both use `get_agent_api_claim_ttl_seconds()`. They are fine on 300 because `run_bash` mints fresh per-call. Only revisit if direct child-process RiskClient usage (outside run_bash) needs the longer window.
- Editing `mcp_servers/agents_mcp/subprocess_runner.py` purely as a no-op — it already mints its own initial claim correctly. **However:** the runner's strip of HMAC from its spawned autonomous child (line 277) means `entry.py:31` operates on an already-empty env in MCP-spawned autonomous flows. The plan therefore ADDS one line of `subprocess_runner.py` to in-scope: remove `env.pop("AGENT_API_USER_CLAIM_HMAC_KEY", None)` on line 277. HMAC reaches the autonomous child process via env, the child's `entry.py` captures-then-strips, and `runner.py` gets it via the kwarg. The HMAC is alive in the autonomous child's `os.environ` between process start and `entry.py:31`; never reaches the bash subprocess.

  **Security contract change**: this weakens the prior contract that "HMAC never reaches the spawned child env at all" to "HMAC reaches the child briefly, is stripped by `entry.py:31` before any non-bootstrap code runs." The existing tests at `tests/mcp/test_agents_mcp_subprocess_runner.py:115, 133` (`test_subprocess_start_strips_hmac_key`, `test_subprocess_start_strip_holds_on_spawn_failure`) encode the prior contract and **must be updated** to reflect the new model. The replacement assertion: HMAC is in the child's spawn env initially, AND a complementary assertion at the runtime level (entry.py runtime test) that `os.environ` no longer holds HMAC after `entry.py` lines 28-31 execute. Plus an audit/test that `runner.py` module-level has no HMAC reads (see import-order discipline in §2).

**Surface sweep before commit** (per `feedback_hank_prompt_8_surfaces.md` and `feedback_plan_grep_sweep_before_commit.md`): grep AI-excel-addin for `RISK_API_KEY` / `RiskClient(` / "bearer" in prompt/markdown files; update only ones reachable from analyst-dev / autonomous-managing-risk surfaces. Codex review confirmed `analyst_dev.md` is the only prompt that programs agent behavior; `.env.example` + setup/deployment docs reference the gateway's `RISK_API_KEY` as a fallback and are fine to leave (RiskClient still accepts api_key when no claim is present).

---

## Test Coverage (regression gate for F114)

New tests under `AI-excel-addin/tests/` (mirror existing patterns in `tests/test_code_execute.py` which already imports `AGENT_API_CLAIM_ENV_VARS`):

1. **Autonomous wiring after `entry.py` strip** — simulate the autonomous parent process: bootstrap, capture HMAC, then strip env. Confirm runner's `prepare_env_for_bash` closure still mints valid claim env using the captured key.

2. **Autonomous import-order discipline** — two parts:
   - **AST/source check**: parse `agent/autonomous/runner.py` with `ast`; walk the module-level body (NOT inside function/class defs); assert no `Name` or `Attribute` node references `AGENT_API_USER_CLAIM_HMAC_KEY` or `get_agent_api_user_claim_hmac_key`. This is the durable regression gate for module-level HMAC reads.
   - **Import-order test**: import `agent.autonomous` (loads `runner` module per `__init__.py:21`) with `AGENT_API_USER_CLAIM_HMAC_KEY` in env; THEN import `agent.autonomous.entry`; THEN simulate `entry.main()` capture flow (or directly exercise the capture-then-strip lines). Assert `claim_hmac_key` captured correctly and runner's closure mints valid claim env.

3. **Interactive dev wiring** — session with `user_id`+`user_email`+HMAC in env → `_build_local_tool_handlers` with bash-tuned wrapper → invoke handler → assert all 7 `AGENT_API_CLAIM_*` env vars in subprocess AND `AGENT_API_CLAIM_EXPIRY - AGENT_API_CLAIM_ISSUED_AT == RUN_BASH_CLAIM_TTL_SECONDS` (600).

4. **Interactive non-dev wiring** — same as (3) but for the non-dev branch (`runtime.py:887-892`).

5. **`code_execute` regression (TTL unchanged)** — interactive code_execute path still uses `get_agent_api_claim_ttl_seconds()` (300 s default). Confirms our `_prepare_env_with_signed_claim` extension doesn't accidentally widen the code_execute TTL.

6. **Per-call rotation** — invoke the bash handler twice in sequence; assert `AGENT_API_CLAIM_NONCE` differs between calls. (Do NOT assert `AGENT_API_CLAIM_ISSUED_AT` differs — `sign_user_claim` uses `int(time.time())` per `_agent_claim.py:49`, which can collide for fast sequential calls. If issued-at change is needed, freeze/advance time via monkeypatch.)

7. **Env layering order** — `extra_env` → `prepare_env` → `_strip_sandbox_secrets`. Confirm `prepare_env` runs after `extra_env` merge (claim env wins on key collision) and strip runs last (HMAC absent from final subprocess env even if extra_env tried to set it).

8. **HMAC absent from bash subprocess** — run a bash command that prints `env`; assert `AGENT_API_USER_CLAIM_HMAC_KEY` is absent regardless of parent state.

9. **Closure no-op cases** — three sub-tests: `claim_hmac_key=None`, `user_id=""`, `user_email=None`. Each triggers WARN log once, returns env unchanged, bash still runs (no exception).

10. **Strict fake-server smoke** (F114 regression gate) — fake `/api/agent/call` server with `AGENT_API_LEGACY_BEARER_ENABLED=false` semantics: returns 401 on bearer, 200 on valid claim. Invoke `RiskClient().call("get_positions")` from inside `run_bash` under the new wiring → assert 200.

**Existing tests to update** (per Codex v2 blocker 3):

- `tests/mcp/test_agents_mcp_subprocess_runner.py::test_subprocess_start_strips_hmac_key` (line 115) — currently asserts HMAC absent from spawn env. New assertion: HMAC PRESENT in the spawn env (because subprocess_runner.py:277 no longer pops it), AND complementary new test (in autonomous entry test module) asserts `os.environ["AGENT_API_USER_CLAIM_HMAC_KEY"]` is absent after `entry.py` lines 26-31 execute inside the child.
- `tests/mcp/test_agents_mcp_subprocess_runner.py::test_subprocess_start_strip_holds_on_spawn_failure` (line 133) — same shape change. On spawn failure, HMAC is in the failed spawn env (was never stripped). Parent `os.environ` is unmutated (existing assertion still holds — `test_subprocess_start_does_not_mutate_parent_environ` at line 122 stays as-is).

---

## Implementation order (for Codex)

1. Add `RUN_BASH_CLAIM_TTL_SECONDS = 600` constant + export to `_agent_claim.py`.
2. Extend `interactive/runtime._prepare_env_with_signed_claim` to accept `ttl_seconds: int | None = None`; default falls back to `get_agent_api_claim_ttl_seconds()`.
3. `local_tools.run_bash` + `execute` signature: accept `prepare_env`; apply between extra_env and strip.
4. `shared/tool_handlers._build_local_tool_handlers`: accept `prepare_env`, plumb into the `run_bash` handler only.
5. `autonomous/entry.py`: capture HMAC into `claim_hmac_key` before strip; thread to runner.
6. `autonomous/runner.py`: accept `claim_hmac_key` kwarg; build closure at function-call time (no module-level HMAC reads); pass to handler builder. Closure no-ops on missing key/user_id/user_email.
7. `interactive/runtime.py`: wire the bash-tuned wrapper (TTL=600) into BOTH `_build_local_tool_handlers` calls.
8. `mcp_servers/agents_mcp/subprocess_runner.py:277`: remove `env.pop("AGENT_API_USER_CLAIM_HMAC_KEY", None)` so the spawned autonomous child can capture it (entry.py:31 still strips inside the child).
9. Update `analyst_dev.md`.
10. Update existing tests at `tests/mcp/test_agents_mcp_subprocess_runner.py:115, 133` per new contract.
11. Add the 10 new tests above.
12. Run targeted test slice.

---

## Verification

**Unit/Integration:**
- `pytest AI-excel-addin/tests/test_code_execute.py` — confirms existing `code_execute` claim path still passes.
- New test file (per Test Coverage section 1-7) — all green.

**Regression smoke (test 8 above):**
- Fake server returns 401 on bearer, 200 on valid claim. `RiskClient` inside `run_bash` → 200. This is the contract test for F114.

**Live (manual, post-merge):**
- Re-run the autonomous `managing-risk` smoke that triggered F114: invoke a `run_bash` that calls `RiskClient().call("get_positions")`. Expect 200, not 401.
- Also exercise interactive dev-mode `run_bash` against a real dev gateway → confirm claim path works.

**No server-side change to test** — `risk_module` is unaffected.

---

## Critical files (reference)

- Server auth: `risk_module/routes/agent_api.py:36-89`, `risk_module/settings.py:22-32`
- RiskClient claim support: `risk_module/risk_client/__init__.py:49-99`
- Existing claim minter: `AI-excel-addin/api/agent/interactive/_agent_claim.py:38-63`
- Existing precedent (`code_execute`): `AI-excel-addin/api/agent/interactive/runtime.py:551-573, 910-922`
- Existing precedent (`agents_mcp` subprocess runner): `AI-excel-addin/mcp_servers/agents_mcp/subprocess_runner.py:12, 260-277`
- Handler stack: `AI-excel-addin/api/agent/shared/tool_handlers.py:740-776`, `AI-excel-addin/api/local_tools.py:454-541, 575-592`
- Tool catalog (confirms run_bash in LOCAL_TOOLS and GATED_TOOLS): `AI-excel-addin/api/agent/shared/tool_catalog.py:747-748, 792`
- Autonomous user identity already plumbed: `AI-excel-addin/api/agent/autonomous/entry.py:107-129`, `runner.py:184-185, 281-282`
- Autonomous HMAC strip boundary: `AI-excel-addin/api/agent/autonomous/entry.py:26-31`
- Sandbox denylist (unchanged): `AI-excel-addin/packages/agent-gateway/agent_gateway/code_execution/_helpers.py:29-38`
- Prompt to update: `AI-excel-addin/api/agent/profiles/prompts/analyst_dev.md:50-63`

---

## Post-plan workflow

1. Plan in repo → Codex review (`mcp__codex__codex` consult/review).
2. Iterate until Codex PASS (address all findings, even non-blocking).
3. Implement via `mcp__codex__codex` (workspace-write sandbox, `approval-policy: never`, no model override — per CLAUDE.md Codex MCP conventions). If implementation includes commits, escalate to `danger-full-access` per `feedback_codex_sandbox_for_commits.md`.
4. Verify tests pass, manual smoke on autonomous `managing-risk`.
5. Update `docs/TODO.md` F114 entry → close with shipped status + commit hash.
