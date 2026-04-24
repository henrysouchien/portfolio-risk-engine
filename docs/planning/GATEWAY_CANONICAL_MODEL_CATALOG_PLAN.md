# Gateway-Owned Canonical Claude Model Catalog

**Status**: ✅ **Codex R4 PASS** (2026-04-23). 4 review rounds (R1-R3 FAIL, R4 PASS). R4's 2 recommends + 1 nit also folded in. Plan is implementable.
**Date**: 2026-04-23
**Context**: Discovered during Phase 3 live verification (see TODO 6D-ARCH). `claude-opus-4-7` 400 errors from the web chat because risk_module's resolver returns it but ai-excel-addin's `ALLOWED_MODELS` hardcodes 4-6-only. Deeper root cause: gateway has multiple stale `claude-sonnet-4-6`/`claude-opus-4-6` defaults and allow-lists that need coordinated update.
**Related**: `docs/planning/AGENT_API_SIGNED_USER_CLAIM_PLAN.md` (Phase 3 multi-user auth — shipped 2026-04-22).

---

## 1. Goal

Make the **ai-excel-addin gateway** the single source of truth for the Claude model catalog (allowed models, default model, display names). Stop risk_module from overriding model selection in its credential resolver.

After this ships:
- Adding support for a new Claude model is a **one-place change** (ai-excel-addin gateway config).
- risk_module's `/api/internal/resolve-credential` returns only **credentials** (`provider`, `billing_mode`, `auth_mode`, and EITHER `api_key` OR `auth_token`), not model config.
- Gateway's own allowed-model list becomes the authority; consumers request models, gateway validates.
- Env-driven override (optional) so ops can tune the allowed set per-deploy without a code change.

---

## 2. Non-goals

- **No changes to how per-user Anthropic API keys are resolved.** BYOK flow stays the same — Secrets Manager lookup + HMAC-signed resolver request. Only the `model` field of the auth_config response goes away.
- **No model-library adoption.** The `model_library` package is Vals-benchmark-specific (vendor-pinned, wrong scope per research §7).
- **No cross-provider refactor.** This plan is Anthropic-specific. OpenAI / Codex provider lists can be reorganized separately if needed.
- **No per-user model preferences.** If we ever want "user X defaults to Sonnet, user Y to Opus" in the future, that's a separate DB-backed feature. Today every user gets the same gateway default.
- **No breaking shape change to `AuthConfig`.** `AuthConfig.model` stays `Optional[str]` — this plan makes it always `None` from the resolver.
- **Not-on-cutover-path model drift left for follow-up** (Codex R4 recommend). These files still default to `claude-sonnet-4-6` but don't affect the web-chat / code_execute path:
  - `setup.py:279` — credential validation fallback.
  - `packages/agent-gateway/examples/06-tool-approval/agent.py:21` — example agent.
  - `packages/agent-gateway/examples/07-full-production/agent.py:26` — example agent.

  Bump as part of a broader "model drift sweep" follow-up, not this plan.

---

## 3. Current state (verified 2026-04-23 via subagent research)

### 3.1 Eleven hardcoded Claude model lists / defaults in ai-excel-addin (Codex R1 expanded scope)

Initial research found 6 sites. Codex R1 surfaced 5 more. Complete list:

**Allow-lists:**
1. `api/agent/shared/tool_catalog.py:54` — `ALLOWED_MODELS = {"claude-sonnet-4-6", "claude-opus-4-6"}`
2. `api/agent/shared/tool_catalog.py:97-98` — `get_allowed_models()` for anthropic/agent-sdk providers — same pair
3. `packages/agent-gateway/agent_gateway/_provider_utils.py:15` — `_ANTHROPIC_ALLOWED_MODELS` (duplicate!)
4. `packages/agent-gateway/agent_gateway/sub_agent.py:62` — default set in sub-agent
5. `packages/agent-gateway/agent_gateway/server.py:239` — `GatewayServerConfig.allowed_models` default

**Default-model hardcodes (Codex R1 finding — the real fallback chain):**
6. `packages/agent-gateway/agent_gateway/_provider_utils.py:9` — `_PROVIDER_DEFAULT_MODELS` dict — `{anthropic: "claude-sonnet-4-6"}` (stale)
7. `packages/agent-gateway/agent_gateway/runner.py:1801` — **hard-fallback** to `"claude-sonnet-4-6"` when no model is resolved
8. `api/credentials.py:288` — `get_default_dev_model` returns `"claude-opus-4-6"`

**Readers of `ANTHROPIC_MODEL` env (currently works via env — not a list, but relevant to default plumbing):**
9. `api/credentials.py:41` — `get_provider_config()` reads `ANTHROPIC_MODEL`
10. `api/agent/interactive/runtime.py:107` — reads `ANTHROPIC_MODEL`
11. `packages/agent-gateway/agent_gateway/sdk_runner.py:197` — reads `ANTHROPIC_MODEL`

**Client-side fallback catalogs (sent from client to gateway):**
- `src/taskpane/taskpane.ts:36` — client hardcoded fallback
- `telegram_bot/bot.py:33` — client hardcoded fallback
- `tui/src/config.ts:8` — client hardcoded fallback

**Provider metadata / rate card (pricing + discovery label):**
- `packages/agent-gateway/agent_gateway/providers/anthropic.py:210` — provider metadata map
- `packages/agent-gateway/agent_gateway/rates/anthropic.json:7` — pricing table
- `api/agent/shared/tool_catalog.py:57` `_MODEL_DISPLAY_NAMES` — friendly labels (no 4-7 entry → falls back to raw ID on discovery)

All stale (missing 4-7). Sites #1-#5 are the 400 blocker for the chat flow. Sites #6-#8 are the fallback chain that makes the web UI resolve to 4-6 even when resolver says 4-7. Sites #9-#11 + env-reader sites share ownership of "the default" with `credentials.py` — which means any attempt to fork the default env var (`DEFAULT_MODEL_ANTHROPIC`) creates split defaults unless all are migrated.

**Implication for v2**: cannot cleanly migrate "default model" without touching all 11 sites. v2 therefore **keeps `ANTHROPIC_MODEL` as the single default-model env var** (no new `DEFAULT_MODEL_ANTHROPIC`) and narrows the plan to: (a) allow-list env var (new) + (b) bump hardcoded defaults to 4-7 + (c) dedup duplicates through imports.

### 3.2 risk_module resolver owns model selection today

- `routes/internal_resolver.py:28` — `_DEFAULT_MODEL = "claude-opus-4-7"`
- `routes/internal_resolver.py:194` — `_build_auth_config` reads `os.getenv("ANTHROPIC_MODEL", _DEFAULT_MODEL)` and includes it in the response
- The resolver also includes `max_tokens` + `thinking` defaults (`routes/internal_resolver.py:29-30`).
- **BYOK OAuth path emits `auth_token` (not `api_key`)** at `routes/internal_resolver.py:172`. Anthropic provider consumes it at `packages/agent-gateway/agent_gateway/providers/anthropic.py:150`. Test covers it at `tests/routes/test_internal_resolver.py:164`. Any shape reduction **must preserve `auth_token`** — Codex R1 blocker #1.

Only one caller of the resolver: `ai-excel-addin/api/credentials_resolver.py:113-147`. Response goes to `AuthConfig.from_dict()`.

### 3.3 The actual fallback chain — Codex R1 blocker #2 correction

v1 of this plan claimed "gateway falls back to client request or gateway default" when resolver drops model. **Partially wrong.** Real chain per Codex R1:

- `api/agent/interactive/runtime.py:555` — `session.auth_config or get_provider_config()`: if `session.auth_config` is a truthy dict (even sparse), it's used as-is. Does NOT fall back to `get_provider_config()` when the dict is present but model-less.
- `packages/agent-gateway/agent_gateway/server.py:625` — checks `session_auth_config.get("model")` which returns `None` for the sparse dict. `resolved_model` ends up `None`.
- `packages/agent-gateway/agent_gateway/runner.py:1801` — **hard-fallback to `"claude-sonnet-4-6"`** when `resolved_model` is None. This is the actual default site.
- `_PROVIDER_DEFAULT_MODELS` at `_provider_utils.py:9` is also hardcoded `"claude-sonnet-4-6"`.

**Implication**: just dropping `model` from the resolver makes the gateway's default `"claude-sonnet-4-6"` (not 4-7). To make 4-7 authoritative, `runner.py:1801` and `_provider_utils.py:9` BOTH need to bump and/or read from `tool_catalog.get_default_model()`. This is new scope in v2.

For the web-chat path specifically: `server.py:626` IS tolerant of missing model (via the `or` chain), but the eventual default after all fallbacks is `runner.py:1801`. That's the site that determines "what Claude model actually runs."

### 3.4 Two unsafe consumers of `auth_config["model"]`

Not the web-chat hot path, but:
- `packages/agent-gateway/agent_gateway/easy.py:225` — `str(auth_config["model"])` — KeyError if missing.
- `packages/agent-gateway/agent_gateway/autonomous.py:501` — same.

Safe consumers (use `.get()` / `or`-chain / tolerate None):
- `server.py:626` — web-chat path.
- `auth.py:AuthConfig.from_dict` — tolerates missing (`model=None`).
- `_provider_utils.py:_resolve_provider` — uses `.get()`.

### 3.5 Existing env-var config pattern in ai-excel-addin

`api/credentials.py` is full of env-driven provider config:
- `AGENT_PROVIDER` via `get_agent_provider()`
- `ANTHROPIC_MODEL`, `OPENAI_MODEL`, `CODEX_MODEL`, `AGENT_SDK_MODEL` via `get_provider_config()`
- `ADVISOR_AGENT_MODEL`, `ANALYST_AGENT_MODEL` per-profile

Adding `ALLOWED_MODELS_ANTHROPIC` etc. matches the convention exactly.

### 3.6 Tests that pin current model strings

**Would need updating** (per research §6):
- risk_module: `tests/routes/test_internal_resolver.py:148-158` — exact dict equality on resolver response.
- ai-excel-addin: `tests/test_run_agent.py:487,503,707-712`, `tests/test_analyst_runner.py:53-59`, `tests/test_telegram_bot.py:928-933,1241-1251`, `tests/test_skills.py:237,262`, `packages/agent-gateway/tests/test_resolve_auth_config.py`.

Tests pin specific strings like `claude-opus-4-6`. Update strategy: use constants from `tool_catalog` instead of pinning strings, so adding a model doesn't break tests.

---

## 4. Design

### 4.1 Single source of truth

**`ai-excel-addin/api/agent/shared/tool_catalog.py` is THE authority** for:
- Allowed Claude model names (per provider)
- Default Claude model (per provider)
- Display names

All other hardcoded lists (#3-#6 in §3.1) delete their own hardcoded sets and import from `tool_catalog` instead. Duplicates collapse to re-exports.

### 4.2 Env-driven allow-list; keep `ANTHROPIC_MODEL` as THE default env (Codex R1 blocker #3 correction)

**Only the allow-list gets a new env var.** The default model stays on `ANTHROPIC_MODEL` (the existing env var) to avoid forking default ownership across the 11 sites enumerated in §3.1.

```python
# tool_catalog.py (anthropic branch of get_allowed_models)
_DEFAULT_ANTHROPIC_MODELS = frozenset({"claude-sonnet-4-6", "claude-opus-4-6", "claude-opus-4-7"})

def get_allowed_models(provider=None):
    resolved = _resolve_model_provider(provider)
    if resolved in {"anthropic", "agent-sdk"}:
        env = os.environ.get("ALLOWED_MODELS_ANTHROPIC", "").strip()
        if env:
            models = {m.strip() for m in env.split(",") if m.strip()}
        else:
            models = set(_DEFAULT_ANTHROPIC_MODELS)
    elif resolved == "openai":
        ...  # same pattern with ALLOWED_MODELS_OPENAI
    elif resolved == "codex":
        ...  # same pattern with ALLOWED_MODELS_CODEX
    # Auto-include whatever is configured as default — preserves existing behavior
    # so `ANTHROPIC_MODEL=claude-opus-4-7` means allowed set always contains 4-7.
    models.add(get_default_model(resolved))
    return models
```

Notes:
- Import direction stays the same: `tool_catalog.py:15` imports `get_default_model` from `credentials.py`. No change to ownership. No circular-import hazard (Codex R1 blocker #3).
- `get_default_model()` continues to read `ANTHROPIC_MODEL` from env (via `credentials.get_provider_config`). Same path as before.
- When `ANTHROPIC_MODEL` is set to a value NOT in the allowed set, `models.add(get_default_model())` still includes it — so ops can deploy a new model by setting only `ANTHROPIC_MODEL` without changing the allow-list env.

**Hardcoded defaults bumped to include `claude-opus-4-7`.** Env var `ALLOWED_MODELS_ANTHROPIC` overrides the set entirely when present (note: still has `models.add(get_default_model())` appended, so a user-configured default is always allowed).

**Why env-driven allow-list instead of just bumping the hardcoded list**:
1. Model catalog changes happen more often than code changes. Config, not code.
2. Different deploys can allow different sets (staging might try a new Claude version before prod).
3. Decouples allow-list from the package-publish lag we hit this week.
4. Matches the existing `credentials.py` env-var convention.

### 4.3 Resolver response shape — credentials only (Codex R1 blocker #1 — preserve `auth_token`)

risk_module's `_build_auth_config` at `internal_resolver.py:186-197` shrinks to the minimum auth surface. **Must preserve `auth_token`** — used by OAuth BYOK path at `anthropic.py:150` with tests at `test_internal_resolver.py:164`.

The existing resolver emits EITHER `api_key` (for api auth mode) OR `auth_token` (for oauth auth mode) — see `internal_resolver.py:165-174`. Both stay.

**Before**:
```python
# Shown for api mode; auth_token variant at line 172 is parallel
return {
    "provider": "anthropic",
    "billing_mode": "byok",
    "auth_mode": "api",  # or "oauth" + "auth_token"
    "api_key": raw,
    "model": os.getenv("ANTHROPIC_MODEL", _DEFAULT_MODEL).strip() or _DEFAULT_MODEL,
    "max_tokens": _DEFAULT_MAX_TOKENS,
    "thinking": _DEFAULT_THINKING,
}
```

**After**:
```python
return {
    "provider": "anthropic",
    "billing_mode": "byok",
    "auth_mode": "api",        # or "oauth"
    "api_key": raw,            # api mode only
    # "auth_token": raw,       # oauth mode only — preserved from current logic
}
```

`model`, `max_tokens`, `thinking` — **all dropped**. These are runtime/request concerns, not per-user credential concerns. Gateway provides its own defaults for all three. Constants `_DEFAULT_MODEL`, `_DEFAULT_MAX_TOKENS`, `_DEFAULT_THINKING` deleted.

`api_key` vs `auth_token` selection logic at `internal_resolver.py:165-174` unchanged — the plan only removes the three runtime-config fields.

### 4.4 Guards for unsafe consumers

Two call sites use `auth_config["model"]` raw (`easy.py:225`, `autonomous.py:501`). These are NOT on the web-chat path; they're used by `create_agent` / autonomous runners. But they'd KeyError if given a model-free auth_config.

Fix shape: change `auth_config["model"]` → `auth_config.get("model") or get_default_model(auth_config.get("provider"))` at both sites. One line each.

### 4.5 Consolidating duplicate model lists + fallback sites (Codex R1 recommend: shared helper not param injection)

**Strategy**: shared helper/import, NOT param injection. `tool_catalog.get_allowed_models()` and `credentials.get_default_model()` are the canonical sources. Every duplicate imports from them.

**Allow-list dedup**:
- `tool_catalog.py:54` `ALLOWED_MODELS` → **delete and update re-exporter at `tools.py:26`** (Codex R4 recommend). The alternative of `frozenset(get_allowed_models())` computed eagerly weakens the env-driven story and is brittle under env-monkeypatch tests.
- `_provider_utils.py:15` `_ANTHROPIC_ALLOWED_MODELS` → delete; `_allowed_models_for_provider()` at `:240-242` calls `tool_catalog.get_allowed_models()`. Import added at top of file.
- `sub_agent.py:62` default → replace hardcoded set with `tool_catalog.get_allowed_models("anthropic")`.
- `server.py:239` `GatewayServerConfig.allowed_models` default → accept `None`; resolve in `_main` via `tool_catalog.get_allowed_models()`.

**Default-model hardcode fixes (Codex R1 blocker #2, R2 recommend — resolve at call time not import)**:
- `_provider_utils.py:9` `_PROVIDER_DEFAULT_MODELS` dict → **call-time resolution** (Codex R2 recommend): change callers to invoke `credentials.get_default_model("anthropic")` at call site rather than freezing the dict at module import. Module-import resolution would break `monkeypatch.setenv/delenv` tests and freeze env-var overrides. Keep the dict structure if it's used as a provider→model map but mark values as callable / resolve lazily; simplest: replace with per-call `get_default_model(provider)`.
- `runner.py:1801` — hardcoded `"claude-sonnet-4-6"` fallback → replace with `credentials.get_default_model()` (call-time).
- `credentials.py:288` `get_default_dev_model` — **pin to `"claude-opus-4-7"`** (Codex R2 decision): keeps analyst-dev on premium Opus, matches new prod default. Does NOT delegate to `get_default_model()` because that couples dev fallback to whatever env overrides prod uses, which may downgrade to Sonnet unexpectedly.

**Client-side fallback catalogs (Codex R1 recommend)**:
- `src/taskpane/taskpane.ts:36` — Excel addin taskpane fallback catalog. Update hardcoded list to include `claude-opus-4-7`.
- `telegram_bot/bot.py:33` — Telegram bot fallback. Same bump.
- `tui/src/config.ts:8` — TUI fallback. Same bump.

Client fallback catalogs can't read the gateway's env vars at build time — they're snapshots. Bump to include 4-7 as a hardcoded update. Long-term, clients should fetch `/chat/init` response's `model_catalog` and never rely on the baked-in fallback, but that's out of scope here.

**Provider metadata / rate card (Codex R1 recommend)**:
- `packages/agent-gateway/agent_gateway/providers/anthropic.py:210` — add `claude-opus-4-7` to provider metadata map.
- `packages/agent-gateway/agent_gateway/rates/anthropic.json:7` — add `claude-opus-4-7` rate card entry. Pricing: match Anthropic's 4-7 published rates.
- `api/agent/shared/tool_catalog.py:57` `_MODEL_DISPLAY_NAMES` — add `"claude-opus-4-7": "Opus 4.7"` (or Anthropic's preferred label).

### 4.6 Updating tests to not pin strings

Tests today hardcode `"claude-opus-4-6"`. Change pattern: import the constant from `tool_catalog` and use that. When defaults shift, tests follow without manual updates.

Example:
```python
# before
assert response.default_model == "claude-opus-4-6"
# after
from agent.shared.tool_catalog import get_default_model
assert response.default_model == get_default_model()
```

---

## 5. Scope — exact file changes

### 5.1 risk_module (shrink)

| File | Change |
|---|---|
| `routes/internal_resolver.py` | Delete `_DEFAULT_MODEL` (line 28), `_DEFAULT_MAX_TOKENS` (line 29), `_DEFAULT_THINKING` (line 30). Rewrite `_build_auth_config` (lines 186-197) to return only credential fields (`provider`, `billing_mode`, `auth_mode`, `api_key`, `auth_token` — preserving api_key/auth_token selection logic at 165-174). Drop `model`, `max_tokens`, `thinking`. |
| `.env.example:76-78` | Remove `ANTHROPIC_MODEL`, `ANTHROPIC_MAX_TOKENS`, `ANTHROPIC_THINKING` lines (Codex R1 recommend — all three now owned by gateway, not risk_module). |
| `tests/routes/test_internal_resolver.py` | Update fixture + assertions at `:148-158` — expect slim auth_config shape. Remove `monkeypatch.delenv("ANTHROPIC_MODEL", ...)` at `:116`. Update `auth_token` test at `:164` to expect slim shape. |

### 5.2 ai-excel-addin — env-driven allow-list + authoritative default (Codex R2 blocker — bump all stale 4-6 fallbacks)

| File | Change |
|---|---|
| `api/agent/shared/tool_catalog.py:54,95-117` | (a) Bump `_DEFAULT_ANTHROPIC_MODELS` to include `claude-opus-4-7`. (b) Add env-var override logic reading `ALLOWED_MODELS_ANTHROPIC` / `ALLOWED_MODELS_OPENAI` / `ALLOWED_MODELS_CODEX` CSV. (c) **Keep import of `get_default_model` from `credentials.py`** — no new env var, no ownership change. |
| `api/agent/shared/tool_catalog.py:57` | Add `"claude-opus-4-7": "Opus 4.7"` to `_MODEL_DISPLAY_NAMES`. |
| **`api/credentials.py:47`** | **Codex R2 blocker**: `get_provider_config()` anthropic branch falls back to `"claude-sonnet-4-6"` when `ANTHROPIC_MODEL` env unset. Bump this fallback to `"claude-opus-4-7"`. This is the actual source of the "default model" value consumed everywhere. |
| `api/credentials.py:288` | `get_default_dev_model` — **Codex R2 recommend**: explicit decision needed. v3 pins to `"claude-opus-4-7"` (stays premium Opus, matches new prod default). Previously `"claude-opus-4-6"` (stale). Alternative of delegating to `get_default_model()` is rejected because it couples analyst-dev to whatever prod runs, which may be undesirable for dev overrides. |
| **`api/agent/interactive/runtime.py:107`** | **Codex R2 blocker**: stale hardcoded `"claude-sonnet-4-6"` fallback when `ANTHROPIC_MODEL` unset. Bump to `"claude-opus-4-7"`. |
| **`packages/agent-gateway/agent_gateway/sdk_runner.py:197`** | **Codex R2 blocker**: same stale fallback. Bump to `"claude-opus-4-7"`. |
| **`packages/agent-gateway/agent_gateway/sub_agent.py:44`** | **Codex R2 recommend**: `default_model: str = "claude-sonnet-4-6"` parameter default. Bump to `"claude-opus-4-7"` (complements the `:62` allowlist fix). |
| **`packages/agent-gateway/agent_gateway/providers/anthropic.py:68`** | **Codex R2 recommend**: `_thinking_param()` gates which models support extended thinking. Verify 4-7 is listed (Anthropic's 4-7 supports thinking per release notes). Add if missing. |

### 5.3 ai-excel-addin — consolidate duplicates (shared-helper pattern, not param injection)

| File | Change |
|---|---|
| `packages/agent-gateway/agent_gateway/_provider_utils.py:9` | **Codex R1 blocker #2**: `_PROVIDER_DEFAULT_MODELS` hardcodes `"claude-sonnet-4-6"` — either bump to `"claude-opus-4-7"` directly OR resolve from `credentials.get_default_model()` at call site. |
| `packages/agent-gateway/agent_gateway/_provider_utils.py:15` | Delete `_ANTHROPIC_ALLOWED_MODELS`. `_allowed_models_for_provider()` at `:240-242` imports + calls `tool_catalog.get_allowed_models()`. |
| `packages/agent-gateway/agent_gateway/runner.py:1801` | **Codex R1 blocker #2**: Replace hardcoded `"claude-sonnet-4-6"` fallback with import from `credentials.get_default_model()` or `tool_catalog.get_allowed_models()`-derived default. |
| `packages/agent-gateway/agent_gateway/sub_agent.py:62` | Import + use `tool_catalog.get_allowed_models()`. |
| `packages/agent-gateway/agent_gateway/server.py:239` | `GatewayServerConfig.allowed_models` accepts `None`; resolve in `_main` or at config construction via `tool_catalog.get_allowed_models()`. |
| `packages/agent-gateway/agent_gateway/easy.py:225`, `autonomous.py:501` | Guard against missing `model` — use `.get()` + fall back to `tool_catalog.get_default_model()`. |
| `packages/agent-gateway/agent_gateway/providers/anthropic.py:210` | Add `claude-opus-4-7` to provider metadata map (Codex R1 recommend). |
| `packages/agent-gateway/agent_gateway/rates/anthropic.json:7` | Add `claude-opus-4-7` rate card entry at Anthropic-published pricing (Codex R1 recommend). |

### 5.4 ai-excel-addin — client-side fallback catalogs (Codex R1 recommend)

Client-side fallback catalogs can't read gateway env vars — they're baked at client build time. Minimum update: bump hardcoded lists to include 4-7. Long-term, clients should fetch `/chat/init` `model_catalog` instead of relying on fallbacks (separate cleanup).

| File | Change |
|---|---|
| `src/taskpane/taskpane.ts:36` | Add `claude-opus-4-7` to Excel addin fallback catalog. |
| `telegram_bot/bot.py:33` | Same bump for Telegram bot. |
| `tui/src/config.ts:8` | Same bump for TUI. |

### 5.5 ai-excel-addin — test updates

Mixed pattern per Codex R1 recommend — use constants for DOWNSTREAM tests (insulates from future bumps); keep ONE explicit string-pin test for the canonical Anthropic default/allowlist so a future bump to 4-8 is deliberate.

**Update to use constants (not pin strings)**:
- `tests/test_run_agent.py:487,503,707-712`
- `tests/test_analyst_runner.py:53-59`
- `tests/test_telegram_bot.py:928-933,1241-1251`
- `tests/test_skills.py:237,262`
- `packages/agent-gateway/tests/test_resolve_auth_config.py` — fixture auth_config drops `model`

**Keep ONE explicit string-pin** (Codex R1 + R2 recommend). Must control env explicitly — otherwise `ANTHROPIC_MODEL` deploy override would let the test drift silently:
- New test `test_canonical_anthropic_defaults` in `tests/test_tool_catalog.py` (or existing location). **Monkeypatch.delenv("ANTHROPIC_MODEL")** at test start so the hardcoded fallback is under test. Assertions:
  - `monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)`
  - `assert get_default_model("anthropic") == "claude-opus-4-7"` — pins the hardcoded fallback at `credentials.py:47`.
  - `assert "claude-opus-4-7" in get_allowed_models("anthropic")` — pins allow-list inclusion.
  - `assert "claude-sonnet-4-6" in get_allowed_models("anthropic")` — backwards compat for 4-6 consumers.
  Also test: `monkeypatch.setenv("ANTHROPIC_MODEL", "claude-custom")` → `get_default_model() == "claude-custom"` and `"claude-custom" in get_allowed_models("anthropic")` (validates the `models.add(get_default_model())` auto-include behavior from §4.2).
  Purpose: make bumping to 4-8 (or any future version) a deliberate code change that updates this test, not a silent default shift.

**New tests**:
- `test_allowed_models_env_override` — `ALLOWED_MODELS_ANTHROPIC=claude-foo,claude-bar` → set is exactly `{claude-foo, claude-bar, current_default}`.
- Model-free resolver-payload tests at:
  - `packages/agent-gateway/tests/test_easy.py:74` — `easy.create_agent` with a model-free auth_config doesn't crash.
  - `packages/agent-gateway/tests/test_autonomous.py:91` — `create_autonomous_agent` with model-free auth_config doesn't crash.
  - `packages/agent-gateway/tests/test_auth.py:23` OR `tests/test_api_credentials_resolver.py:87` — resolver dict without `model` round-trips cleanly through `AuthConfig.from_dict` → web-chat validator.
- **Explicit 4-7 thinking-support test** (Codex R3 recommend) — add to `tests/test_gateway_perf.py:33` OR `tests/test_api_credentials.py:195`. Validate `_thinking_param("claude-opus-4-7")` returns thinking-enabled config. Current tests only cover 4-6/4-5, silently dropping coverage of the new default's thinking behavior.

**Test-harness shared state (Codex R3 recommend — critical)**:
- `packages/agent-gateway/tests/conftest.py:63,67,137` — shared fixtures inject `"claude-sonnet-4-6"` as auth_config model. Model-free resolver-payload tests above would inherit this default silently and never exercise the missing-model path. Update conftest to support an opt-out (e.g., a fixture variant `auth_config_model_free`) or change new tests to override the shared fixture explicitly.

### 5.6 Ops docs + published-default strings (Codex R3 recommend)

| File | Change |
|---|---|
| `README.md` (AI-excel-addin, `:77`) | Currently lists Anthropic default as `claude-sonnet-4-6`. Update to `claude-opus-4-7`. Also document new env vars — `ALLOWED_MODELS_ANTHROPIC`, `ALLOWED_MODELS_OPENAI`, `ALLOWED_MODELS_CODEX`. Note that `ANTHROPIC_MODEL` remains THE default-model env var (unchanged from today). |
| `ARCHITECTURE.md` (AI-excel-addin, `:86`) | Same default-string update. |
| `docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md` (risk_module) | Brief note: model catalog now lives in gateway's `tool_catalog.py` + env overrides. risk_module's `ANTHROPIC_MODEL` / `ANTHROPIC_MAX_TOKENS` / `ANTHROPIC_THINKING` no longer consumed anywhere — all three moved to gateway. |

---

## 6. Step-by-step implementation

Single commit in each repo. Test after each to catch drift early.

### Step 1 — ai-excel-addin: bump + env-driven allow-list + dedup + client fallbacks

Single commit in ai-excel-addin (or two — split "gateway-side" from "clients" if diff gets unwieldy). Work in worktree `~/Documents/Jupyter/AI-excel-addin-multiuser` (on `main`, synced with origin). Branch: `feat/gateway-canonical-model-catalog`.

**Gateway-side — env-driven allow-list + tool_catalog authority**:
1. `api/agent/shared/tool_catalog.py:54,95-117`: bump `_DEFAULT_ANTHROPIC_MODELS` to include `claude-opus-4-7`. Add env-var override for `ALLOWED_MODELS_ANTHROPIC` / `_OPENAI` / `_CODEX`.
2. `api/agent/shared/tool_catalog.py:57`: add `"claude-opus-4-7": "Opus 4.7"` to `_MODEL_DISPLAY_NAMES`.

**Gateway-side — authoritative default (bump all stale 4-6 fallbacks)**:
3. `api/credentials.py:47`: bump `get_provider_config` anthropic-branch fallback from `"claude-sonnet-4-6"` → `"claude-opus-4-7"`. *Codex R2 blocker #1 — this is the actual clean-env source.*
4. `api/credentials.py:288`: `get_default_dev_model` pin to `"claude-opus-4-7"` (explicit string, NOT `get_default_model()` delegation).
5. `api/agent/interactive/runtime.py:107`: bump hardcoded `"claude-sonnet-4-6"` fallback → `"claude-opus-4-7"`.
6. `packages/agent-gateway/agent_gateway/sdk_runner.py:197`: bump same fallback.
7. `packages/agent-gateway/agent_gateway/_provider_utils.py:9`: convert `_PROVIDER_DEFAULT_MODELS` to call-time resolution (lookups invoke `credentials.get_default_model(provider)` at call site rather than freeze at import).
8. `packages/agent-gateway/agent_gateway/runner.py:1801`: replace hardcoded `"claude-sonnet-4-6"` fallback with `credentials.get_default_model()`.
9. `packages/agent-gateway/agent_gateway/sub_agent.py:44`: bump `default_model: str = "claude-sonnet-4-6"` parameter default → `"claude-opus-4-7"`.

**Gateway-side — dedup (shared import, not param injection)**:
10. `packages/agent-gateway/agent_gateway/_provider_utils.py:15,240-242`: delete `_ANTHROPIC_ALLOWED_MODELS`; `_allowed_models_for_provider()` imports `tool_catalog.get_allowed_models`.
11. `packages/agent-gateway/agent_gateway/sub_agent.py:62`: replace hardcoded allowlist with `tool_catalog.get_allowed_models("anthropic")`.
12. `packages/agent-gateway/agent_gateway/server.py:239`: `GatewayServerConfig.allowed_models` accepts `None`; resolve via `tool_catalog.get_allowed_models()` in `_main`.
13. `packages/agent-gateway/agent_gateway/easy.py:225`, `autonomous.py:501`: guard `auth_config.get("model") or credentials.get_default_model()`.

**Gateway-side — provider metadata + capability gates**:
14. `packages/agent-gateway/agent_gateway/providers/anthropic.py:68` `_thinking_param()`: verify/add `"claude-opus-4-7"` to the extended-thinking allowlist.
15. `packages/agent-gateway/agent_gateway/providers/anthropic.py:210`: add `claude-opus-4-7` to provider metadata map.
16. `packages/agent-gateway/agent_gateway/rates/anthropic.json:7`: add `claude-opus-4-7` rate card entry.

**Client fallbacks**:
17. `src/taskpane/taskpane.ts:36`: bump Excel addin fallback catalog.
18. `telegram_bot/bot.py:33`: bump Telegram bot fallback.
19. `tui/src/config.ts:8`: bump TUI fallback.

**Tests**:
20. Update all §5.5 "update to not pin strings" tests to use constants from `tool_catalog`.
21. Add explicit `test_canonical_anthropic_defaults` with `monkeypatch.delenv("ANTHROPIC_MODEL")` — pins hardcoded fallback to `claude-opus-4-7` + backwards-compat 4-6 in allowed set. Add `setenv` variant validating `models.add(default)` auto-include.
22. Add `test_allowed_models_env_override` — env-CSV override case.
23. Add model-free resolver-payload tests at `test_easy.py:74`, `test_autonomous.py:91`, `test_api_credentials_resolver.py:87`.
24. Update `packages/agent-gateway/tests/conftest.py:63,67,137` shared fixtures to NOT inject `claude-sonnet-4-6` for the model-free test variants — per Codex R3 recommend, add an `auth_config_model_free` fixture variant OR override the shared default in new tests explicitly.
25. Add explicit 4-7 thinking-support test in `tests/test_gateway_perf.py:33` or `tests/test_api_credentials.py:195`.
26. `npm test` + `pytest tests/ packages/agent-gateway/tests/` — expect all green.

Commit: `feat(gateway): canonical Claude model catalog with env override + 4-7 bump across gateway + clients`.

### Step 2 — risk_module: slim the resolver response

Single commit in risk_module. Branch: `feat/slim-resolver-auth-config`.

1. `routes/internal_resolver.py`: delete `_DEFAULT_MODEL`/`_DEFAULT_MAX_TOKENS`/`_DEFAULT_THINKING` constants (lines 28-30); rewrite `_build_auth_config` (186-197) to return credentials only — **preserve `api_key`/`auth_token` selection logic at 165-174**.
2. `tests/routes/test_internal_resolver.py`: update fixture at `:148-158,116`; update `auth_token` test at `:164` to expect slim shape.
3. `.env.example`: remove `ANTHROPIC_MODEL` (`:78`), `ANTHROPIC_MAX_TOKENS` (`:76`), `ANTHROPIC_THINKING` (`:77`).
4. `pytest tests/routes/test_internal_resolver.py` — expect green.

Commit: `refactor(resolver): return credentials only, drop model/tokens/thinking (gateway owns catalog)`.

### Step 3 — PR + live verification

1. Open PR in AI-excel-addin for Step 1, merge.
2. After merge, reinstall `ai-agent-gateway` locally (if not editable) + restart gateway.
3. `curl` the `/chat/init` response — `model_catalog.allowed_models` includes `claude-opus-4-7`.
4. PR Step 2 in risk_module, merge.
5. Retry the live code_execute test from the Hank web UI — this time the model validation should pass. Phase 3 cutover live verification unblocks.

### Step 4 — docs

1. Update AI-excel-addin `README.md:77` — change published Anthropic default from `claude-sonnet-4-6` to `claude-opus-4-7`. Add new env vars `ALLOWED_MODELS_ANTHROPIC` / `_OPENAI` / `_CODEX` with explanation. Note `ANTHROPIC_MODEL` remains THE default-model env var (unchanged).
2. Update AI-excel-addin `ARCHITECTURE.md:86` — same default-string bump from 4-6 to 4-7.
3. Update risk_module `docs/ops/AGENT_API_MULTI_USER_ACTIVATION.md` — resolver no longer consumes `ANTHROPIC_MODEL` / `ANTHROPIC_MAX_TOKENS` / `ANTHROPIC_THINKING`; all three moved to gateway.
4. Update `docs/TODO.md`:
   - Mark 6D-ARCH progressed (model-catalog drift fix shipped).
   - 6D cutover now unblocked by this fix.

Commit: `docs: canonical model catalog + resolver shape update`.

---

## 7. Test plan

**ai-excel-addin new tests**:
- `get_allowed_models(provider="anthropic")` includes `claude-opus-4-7` by default.
- `get_allowed_models` respects `ALLOWED_MODELS_ANTHROPIC` env var (CSV).
- `get_allowed_models` auto-includes the configured default even when env var overrides.
- `easy.py` + `autonomous.py` don't crash with missing `auth_config["model"]` — fall back to tool_catalog default.

**ai-excel-addin tests updated (§5.5)**:
- Model-pinning tests use tool_catalog constants instead of hardcoded strings.

**risk_module tests updated**:
- `test_internal_resolver.py` asserts slim auth_config shape (no model/tokens/thinking).

**Live verification**:
- `/chat/init` returns `model_catalog.allowed_models` containing `claude-opus-4-7`.
- Hank web UI `code_execute` request — previously 400 "Invalid model" — now succeeds.
- The un-finished Phase 3 live test from this week completes end-to-end.

---

## 8. Rollout

**Low risk.** Resolver response shape change is subtractive-but-compatible (three optional fields dropped, no renames) — `AuthConfig.from_dict` already tolerates missing fields. Gateway fallbacks handle missing model gracefully after the bumps in §5.2.

**Deploy sequence**:
1. Ship ai-excel-addin first (add 4-7 to allowed list). Strictly additive — allowing more models, not restricting. Zero risk to existing flows.
2. After ai-excel-addin is deployed + gateway restarted, ship risk_module resolver shrink. Gateway will fall back to its own default when resolver drops model. Tested path.
3. No operational flag flips needed. Single direction migration.

**Rollback**: if anything goes wrong, revert the commit in either repo. No data migrations, no env var changes required (env vars introduced are all optional with hardcoded fallbacks).

---

## 9. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Consumers outside the web-chat path (`easy.py`, `autonomous.py`) break on missing `model` | §4.4 explicitly fixes these two sites with `.get()` fallback. |
| 2 | Other consumers of resolver response I haven't found | Research §3 enumerated the one caller (`api/credentials_resolver.py:113`). Response parsed via `AuthConfig.from_dict` which already tolerates missing fields. |
| 3 | Env var override format ambiguity (CSV, JSON, etc.) | Plan specifies CSV (matches `AGENT_PROVIDER` / credentials.py convention — simple string split). |
| 4 | Test pinning strings via imported constants creates a circular test-vs-source coupling | Tolerable — intent is that adding a model doesn't require test updates. Tests still validate SHAPE (expected default, membership in allowed set); the specific string is a project fact, not a test fixture. |
| 5 | Deploy-ordering if risk_module ships first | §8 sequences ai-excel-addin first. If reversed, gateway still has hardcoded default fallback; 400s would surface on misconfig but resolver's slimmer shape doesn't break anything on its own. |
| 6 | `_ANTHROPIC_ALLOWED_MODELS` in `_provider_utils.py` used by `easy.create_agent` / autonomous outside the server.py validation path | §5.3 rewires via shared import from `tool_catalog.get_allowed_models()`; both callers (easy + autonomous) will resolve against the canonical list. If the import accidentally shadows or is missed, fallback is hardcoded bumped-to-include-4-7 set — no regression. |

---

## 10. Codex review resolutions

### R3 resolutions (2026-04-23, v3 → v4)

- **R3 Blocker (§5 and §6 diverge on core default-model fix)** → §6 Step 1 rewritten with 26 explicitly numbered steps. Every file in §5 scope (including newly added `credentials.py:47`, `runtime.py:107`, `sdk_runner.py:197`, `sub_agent.py:44`, `anthropic.py:68`) has a matching step. Duplicate/contradictory instruction at old line 225 (`get_default_dev_model → get_default_model()`) removed; the §5.2 and §6 Step 4 pin is now consistent: explicit `"claude-opus-4-7"` string.
- **R3 Recommend (conftest.py shared fixtures inject claude-sonnet-4-6)** → Added §5.5 test-harness row + §6 Step 24 for `packages/agent-gateway/tests/conftest.py:63,67,137`.
- **R3 Recommend (thinking-support test missing for 4-7)** → Added §5.5 + §6 Step 25 — explicit thinking-support test at `tests/test_gateway_perf.py:33` or `tests/test_api_credentials.py:195`.
- **R3 Recommend (published default strings in docs)** → §5.6 adds `README.md:77` + `ARCHITECTURE.md:86` updates. Both currently say Anthropic default is `claude-sonnet-4-6`.
- **R3 Recommend (`_PROVIDER_DEFAULT_MODELS` import-time vs call-time)** → §4.5 and §6 Step 7 now explicit: call-time resolution via `credentials.get_default_model(provider)` at call site. Import-time freeze would break `monkeypatch.setenv/delenv` tests.
- **R3 Nit (duplicate §5.5 heading)** → Renumbered ops-docs section to §5.6.

### R2 resolutions (2026-04-23, v2 → v3)

- **R2 Blocker (default not actually 4-7 in clean env)** → §5.2 expanded: bump hardcoded `"claude-sonnet-4-6"` fallback at `api/credentials.py:47` to `"claude-opus-4-7"`. Also bump stale fallbacks at `api/agent/interactive/runtime.py:107` and `packages/agent-gateway/agent_gateway/sdk_runner.py:197`. These are the actual sources when `ANTHROPIC_MODEL` env is unset — v2 claimed coverage but missed.
- **R2 Recommend (missing `sub_agent.py:44`)** → Added to §5.2 scope. Bump `default_model: str = "claude-sonnet-4-6"` parameter default.
- **R2 Recommend (§5/§6 drift — stale `DEFAULT_MODEL_ANTHROPIC`)** → §5.5 ops-docs row corrected; no new env var documented.
- **R2 Recommend (stale "param-injection" wording in risk #6)** → Updated to say "shared import from `tool_catalog.get_allowed_models()`".
- **R2 Recommend (pin test inconsistency)** → §5.5 test spec now uses `monkeypatch.delenv("ANTHROPIC_MODEL")` to control env; pins the hardcoded fallback explicitly. Also adds a `setenv` variant to validate `models.add(default)` auto-include.
- **R2 Recommend (thinking capability gate)** → §5.2 adds `anthropic.py:68` `_thinking_param()` to scope — verify/add 4-7 support for extended thinking.
- **R2 Recommend (`get_default_dev_model` downgrade)** → §5.2 explicit decision: pin to `"claude-opus-4-7"` (not delegate to `get_default_model()`). Keeps dev on premium Opus; matches new prod default.
- **R2 Nit (§1 description missing `billing_mode`/`auth_token`)** → §1 corrected: "credentials (`provider`, `billing_mode`, `auth_mode`, and EITHER `api_key` OR `auth_token`)".
- **R2 Nit ("additive-only" contradiction)** → §8 reworded as "subtractive-but-compatible (three optional fields dropped, no renames)".

### R1 resolutions (2026-04-23, v1 → v2)

- **Blocker #1 (dropped `auth_token`)** → §3.2 and §4.3 corrected. OAuth BYOK path preserved — resolver emits EITHER `api_key` OR `auth_token` via existing logic at `internal_resolver.py:165-174`. Only runtime-config fields (`model`/`max_tokens`/`thinking`) drop.
- **Blocker #2 (wrong fallback assumption)** → §3.3 rewritten with actual fallback chain: `session.auth_config` dict is used as-is even when sparse; real defaults live at `_provider_utils.py:9` + `runner.py:1801`. §5.3 expanded to bump these two + the existing ones. The gateway's actual default behavior is now spelled out.
- **Blocker #3 (circular import + split defaults)** → §4.2 corrected: **keep `ANTHROPIC_MODEL` as THE default-model env var**. Do NOT introduce `DEFAULT_MODEL_ANTHROPIC`. `tool_catalog.py` continues to import `get_default_model` from `credentials.py` (no ownership change). Only new env var is `ALLOWED_MODELS_ANTHROPIC` for allow-list.
- **Recommend (missed model sites)** → §3.1 expanded from 6 sites to 11 sites. §5.3 + §5.4 scope now covers all of them (fallback defaults, runner, _PROVIDER_DEFAULT_MODELS, client fallback catalogs, provider metadata, rates).
- **Recommend (drop ANTHROPIC_MAX_TOKENS + ANTHROPIC_THINKING too)** → §5.1 updated. All three env vars removed from risk_module `.env.example`.
- **Recommend (test coverage too light)** → §5.5 expanded with model-free resolver-payload tests at 3 callsites (`test_easy.py`, `test_autonomous.py`, `test_api_credentials_resolver.py`). Added one explicit pin test for canonical defaults.
- **Recommend (dedup via shared helper not param inject)** → §4.5 and §5.3 rewritten: `_provider_utils.py` imports from `tool_catalog` instead of accepting an allowlist parameter.
- **Recommend (`_MODEL_DISPLAY_NAMES` for 4-7)** → §5.2 adds display name entry.
- **Nit (§3.1 said "five" but listed six)** → v2 enumerates 11 sites cleanly, so the count is now explicit.

### Direct Codex answers recorded:
- A2 (env-driven allow-list) accepted. Default stays on `ANTHROPIC_MODEL` (Codex rejected new `DEFAULT_MODEL_ANTHROPIC` env var).
- Drop `max_tokens` + `thinking` from resolver: yes.
- CSV format: yes, with whitespace strip + empty filter.
- Remove `ANTHROPIC_MAX_TOKENS` + `ANTHROPIC_THINKING` from risk_module `.env.example`: yes.
- `_ANTHROPIC_ALLOWED_MODELS` dedup via shared import, not param injection: yes.
- Test constant pattern: mixed — constants in downstream tests, one explicit pin test for canonical defaults.

---

## 11. Ship log

_(To be filled on ship.)_

---

## 12. Change log

**v4 (2026-04-23)**: Codex R3 FAIL (1 blocker + 4 recommends + 1 nit). Primary issue was §5↔§6 drift — repeat of pattern from parent plans this session. v4 rewrites §6 Step 1 with 26 explicit numbered sub-steps, every one matching a §5 scope row. Also:
- Removed stale "`get_default_dev_model` → `get_default_model()`" instruction. Pinned to `"claude-opus-4-7"` consistently in both §5.2 and §6 Step 4.
- Clarified `_PROVIDER_DEFAULT_MODELS` uses call-time resolution, not import-time (brittle under env monkeypatch).
- Added `conftest.py:63,67,137` shared-fixture updates to test scope.
- Added explicit 4-7 thinking-support test.
- Added `README.md:77` and `ARCHITECTURE.md:86` to docs scope — both still say Anthropic default is `claude-sonnet-4-6`.
- Fixed duplicate `### 5.5` heading.

**v3 (2026-04-23)**: Codex R2 FAIL (1 blocker + 5 recommends + 2 nits). Scope expansions:
- §5.2 adds 4 more stale-fallback files: `credentials.py:47`, `runtime.py:107`, `sdk_runner.py:197`, `sub_agent.py:44`. These are where `claude-sonnet-4-6` actually resolves from when `ANTHROPIC_MODEL` is unset. v2 claimed default-bump coverage but missed the underlying fallback chain.
- §5.2 adds `anthropic.py:68` `_thinking_param()` capability gate for 4-7 thinking support.
- §5.2 `get_default_dev_model` pinned explicitly to `"claude-opus-4-7"` (not delegated) — keeps dev on premium Opus.
- §5.5 test spec monkeypatches `ANTHROPIC_MODEL` explicitly + adds setenv variant for auto-include validation.
- §5.5 ops-docs row removed stale `DEFAULT_MODEL_ANTHROPIC` reference.
- §9 risk #6 + §8 rollout wording corrected for consistency with v2 dedup strategy.
- §1 description lists correct resolver fields (`billing_mode`, `auth_token` preservation).

**v2 (2026-04-23)**: Codex R1 FAIL. Three blockers + four recommends + one nit integrated:
- Preserve `auth_token` in resolver response (OAuth BYOK path).
- Correct fallback-chain analysis — real defaults are at `_provider_utils.py:9` + `runner.py:1801`, not just `server.py:626`. Scope expanded to bump these.
- Drop plan to fork default env var. Keep `ANTHROPIC_MODEL` as THE default source; add only `ALLOWED_MODELS_ANTHROPIC` for allow-list.
- Expanded scope from 6 → 11 hardcoded sites. Added: `_PROVIDER_DEFAULT_MODELS`, `runner.py:1801` fallback, 3 client fallback catalogs (taskpane.ts, bot.py, config.ts), provider metadata (anthropic.py:210), rate card (anthropic.json), display names.
- Drop `ANTHROPIC_MAX_TOKENS` + `ANTHROPIC_THINKING` from risk_module `.env.example` (not just `ANTHROPIC_MODEL`).
- Test coverage expanded: model-free resolver-payload tests at `test_easy.py`, `test_autonomous.py`, `test_api_credentials_resolver.py`. One explicit pin test for canonical default.
- Dedup via shared import, not param injection.

**v1 (2026-04-23)**: Initial draft. Scope: risk_module resolver returns credentials only (drops model/tokens/thinking); ai-excel-addin tool_catalog becomes authority for Claude model catalog with env override support; 5 hardcoded duplicates in ai-excel-addin consolidate to single canonical source. Tests updated to use constants instead of pinning strings. Backwards-compatible (gateway tolerates missing `model` on web-chat path via existing `or` chain).
