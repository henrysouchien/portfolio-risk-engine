# LLM Completion Provider Abstraction

> **Date**: 2026-03-21
> **Status**: PLAN — Codex R1 FAIL (7 issues), R2 FAIL (2 issues), **R3 PASS**
> **Audit ref**: `docs/planning/AI_PROVIDER_EXTENSIBILITY_AUDIT.md` (Tier 1, item 1)
> **TODO ref**: `docs/TODO.md` line 84 ("AI/Agent Provider Extensibility")

---

## Context

`utils/gpt_helpers.py` has 3 functions making direct `openai.OpenAI()` calls with hardcoded model IDs (`gpt-4.1`, `gpt-4o-mini`). The module creates a global `client = openai.OpenAI(api_key=...)` at import time (duplicated on lines 15 and 79 — legacy Jupyter notebook artifact). Swapping to Anthropic or another provider requires rewriting all 3 functions. The AI Provider Extensibility Audit identified this as a Tier 1 backlog item.

**Goal**: Abstract the 3 direct OpenAI calls behind a `CompletionProvider` Protocol so non-chat AI tasks (risk interpretation, peer generation, asset classification) are provider-swappable via env config.

### Current Functions

| Function | Model | Callers | Gated? |
|----------|-------|---------|--------|
| `interpret_portfolio_risk(diagnostics_text) -> str` | `gpt-4.1` | `app.py:2049`, `core/interpretation.py:66` | No |
| `generate_subindustry_peers(ticker, name, industry, model, max_tokens, temperature) -> str` | `gpt-4.1` (default) | `core/proxy_builder.py:847` | Yes (`gpt_enabled()`) |
| `generate_asset_class_classification(ticker, company_name, description, timeout) -> str` | `gpt-4o-mini` | `services/security_type_service.py:1322` | Yes (`gpt_enabled()`) |

Module-level import: `core/risk_orchestration.py:49` imports `interpret_portfolio_risk` and `generate_subindustry_peers`.

---

## Architecture

Single `CompletionProvider` Protocol + singleton factory. No `ProviderRegistry` integration (overkill — LLM completions have one active provider, not a fallback chain). Follows the existing Protocol pattern in `providers/interfaces.py`.

```
providers/interfaces.py   ← ADD: CompletionProvider Protocol
providers/completion.py    ← NEW: OpenAI + Anthropic implementations + singleton factory
utils/gpt_helpers.py       ← REFACTOR: thin wrappers calling get_completion_provider()
```

**Callers mostly unchanged** — they continue importing from `utils.gpt_helpers`. Only `core/interpretation.py` needs a metadata fix (`interpretation_service` field).

---

## Steps

### Step 1: Add `CompletionProvider` Protocol to `providers/interfaces.py`

Append after the existing 9 Protocol classes:

```python
@runtime_checkable
class CompletionProvider(Protocol):
    """Provider contract for text completion (prompt → str) tasks."""

    provider_name: str

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        model: str | None = None,
        max_tokens: int = 2000,
        temperature: float = 0.5,
        timeout: float | None = None,
    ) -> str: ...
```

- `prompt` positional (user message). `system` keyword-only (optional system prompt).
- `model` optional — if `None`, provider uses its configured default. **Callers must NOT pass provider-specific model IDs** (e.g., `"gpt-4.1"`) — all model selection goes through `model=None` (provider default) or env-var overrides. See "Model ID handling" below.
- Return type `str` (stripped completion text). All 3 existing functions return `str`.
- `timeout` is `float | None` in seconds (both OpenAI and Anthropic SDKs accept float).

Update `providers/__init__.py` to add `CompletionProvider` to imports and `__all__`.

### Step 2: Create `providers/completion.py`

**`OpenAICompletionProvider`**:
- Lazy client init (no global `openai.OpenAI()` at import time)
- `complete()` maps to `client.chat.completions.create()`
- `default_model` configurable via constructor (default: `"gpt-4.1"`)

```python
class OpenAICompletionProvider:
    provider_name = "openai"

    def __init__(self, api_key: str | None = None, default_model: str = "gpt-4.1"):
        self._api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self._default_model = default_model
        self._client: openai.OpenAI | None = None

    @property
    def client(self) -> openai.OpenAI:
        if self._client is None:
            import openai
            self._client = openai.OpenAI(api_key=self._api_key)
        return self._client

    def complete(self, prompt, *, system=None, model=None, max_tokens=2000,
                 temperature=0.5, timeout=None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs = dict(model=model or self._default_model,
                      messages=messages, max_tokens=max_tokens,
                      temperature=temperature)
        if timeout is not None:
            kwargs["timeout"] = timeout

        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content.strip()
```

**`AnthropicCompletionProvider`**:
- Same lazy pattern with `import anthropic` inside property
- `complete()` maps to `client.messages.create()` with `system` kwarg
- Default model: `"claude-sonnet-4-20250514"`
- **Multi-block safe**: Extracts text from all `TextBlock` content blocks, not just `content[0]`

```python
class AnthropicCompletionProvider:
    provider_name = "anthropic"

    def __init__(self, api_key: str | None = None, default_model: str = "claude-sonnet-4-20250514"):
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self._default_model = default_model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def complete(self, prompt, *, system=None, model=None, max_tokens=2000,
                 temperature=0.5, timeout=None) -> str:
        kwargs = dict(model=model or self._default_model,
                      max_tokens=max_tokens, temperature=temperature)
        if system:
            kwargs["system"] = system
        kwargs["messages"] = [{"role": "user", "content": prompt}]
        if timeout is not None:
            kwargs["timeout"] = timeout

        resp = self.client.messages.create(**kwargs)
        # Extract text from all TextBlock content blocks (multi-block safe)
        parts = [block.text for block in resp.content if hasattr(block, "text")]
        return "".join(parts).strip()
```

**Thread-safe singleton factory** (matches `services/redis_cache.py` locked pattern):

```python
import threading

_PROVIDER_FACTORIES = {
    "openai": OpenAICompletionProvider,
    "anthropic": AnthropicCompletionProvider,
}

_completion_provider: CompletionProvider | None = None
_completion_provider_initialized = False
_completion_lock = threading.Lock()


def get_completion_provider() -> CompletionProvider | None:
    """Return the configured completion provider singleton, or None if disabled."""
    global _completion_provider, _completion_provider_initialized
    if _completion_provider_initialized:
        return _completion_provider

    with _completion_lock:
        # Double-check under lock
        if _completion_provider_initialized:
            return _completion_provider

        provider_name = os.getenv("LLM_PROVIDER", "openai").strip().lower()
        default_model = os.getenv("LLM_DEFAULT_MODEL", "").strip() or None

        factory = _PROVIDER_FACTORIES.get(provider_name)
        if factory is None:
            logger.warning("Unknown LLM_PROVIDER=%r, completion disabled", provider_name)
            _completion_provider_initialized = True
            return None

        kwargs = {}
        if default_model:
            kwargs["default_model"] = default_model

        _completion_provider = factory(**kwargs)
        _completion_provider_initialized = True
        return _completion_provider


def _reset_completion_provider() -> None:
    """Clear cached provider (for tests)."""
    global _completion_provider, _completion_provider_initialized
    with _completion_lock:
        _completion_provider = None
        _completion_provider_initialized = False
```

The `_completion_provider_initialized` flag (not just `is None` check) allows explicitly disabling completions when the env var is set to an unknown provider. Matches the `is_db_available()` positive-only cache pattern. Thread lock matches `services/redis_cache.py:99` pattern.

### Step 3: Refactor `utils/gpt_helpers.py`

**Remove**:
- Both `import openai` (lines 8, 75)
- Both `client = openai.OpenAI(...)` (lines 15, 79)
- Both `OPENAI_API_KEY = os.getenv(...)` (lines 14, 78)
- Duplicate imports (`import os` line 73, `from typing import List` line 74)
- Jupyter cell markers (`# In[ ]:`)
- Duplicate `# File: gpt_helpers.py` headers
- Unused imports (`StringIO`, `redirect_stdout`)

**Add**:
- `from providers.completion import get_completion_provider`

**Rewrite each function** to delegate to `get_completion_provider().complete(...)`. Keep identical function signatures, decorators, docstrings, and error-handling behavior.

| Function | On `provider is None` | On exception |
|----------|----------------------|--------------|
| `interpret_portfolio_risk()` | Return `"(AI interpretation unavailable)"` | Propagates (existing behavior) |
| `generate_subindustry_peers()` | Return `""` | Return `""` (existing behavior) |
| `generate_asset_class_classification()` | Return `"mixed,0.50"` | Return `"mixed,0.50"` (existing behavior) |

**Model ID handling** (Codex review fix — the original strategy of passing OpenAI model IDs to Anthropic was broken):

**Principle**: Functions pass `model=None` to `complete()`. The provider uses its own `default_model`. Task-specific overrides use env vars that are only set when the user explicitly configures them.

- `interpret_portfolio_risk` → passes `model=None` (provider default). Override: `LLM_INTERPRETATION_MODEL` env var.
- `generate_subindustry_peers` → **drops the `model` param from the function signature** (no caller passes it — `proxy_builder.py:847` uses keyword args `ticker=`, `name=`, `industry=` only). Passes `model=None`. Override: `LLM_PEERS_MODEL` env var.
- `generate_asset_class_classification` → passes `model=None` (provider default). Override: `LLM_CLASSIFICATION_MODEL` env var. Note: when using OpenAI, the user may want `gpt-4o-mini` here for cost; set `LLM_CLASSIFICATION_MODEL=gpt-4o-mini` in `.env`.

**Per-provider defaults** (set via `LLM_DEFAULT_MODEL` or hardcoded in constructor):
- OpenAI: `"gpt-4.1"`
- Anthropic: `"claude-sonnet-4-20250514"`

**Why this works**: `LLM_DEFAULT_MODEL` is provider-matched. If you set `LLM_PROVIDER=anthropic`, you'd set `LLM_DEFAULT_MODEL=claude-sonnet-4-20250514` (or omit it for the constructor default). You'd never set `LLM_DEFAULT_MODEL=gpt-4.1` with `LLM_PROVIDER=anthropic` — that's a configuration error, not something we need to guard against in code.

**Task-specific env-var override flow** (in each wrapper function):
```python
model = os.getenv("LLM_INTERPRETATION_MODEL") or None  # None → provider default
return provider.complete(prompt, system=..., model=model, ...)
```

**Prompts stay identical** — copy verbatim from the existing function bodies. No prompt rewrites.

### Step 4: Add env var documentation

Add to `.env.example` near existing API key section:
```
# LLM Completion Provider (non-chat AI tasks: risk interpretation, peer generation, asset classification)
LLM_PROVIDER=openai                        # Options: openai, anthropic
# LLM_DEFAULT_MODEL=gpt-4.1               # Override default model (must match provider)
# LLM_INTERPRETATION_MODEL=               # Override model for risk interpretation
# LLM_PEERS_MODEL=                        # Override model for peer generation
# LLM_CLASSIFICATION_MODEL=gpt-4o-mini    # Override model for asset classification (cheaper model)
```

### Step 5: Tests

**`tests/providers/test_completion.py`** (~12 tests):

Provider implementation tests:
1. OpenAI provider delegates to `chat.completions.create()` with correct message structure
2. Anthropic provider delegates to `messages.create()` with system kwarg
3. Anthropic multi-block response — extracts text from all TextBlock content blocks
4. Timeout passed through to underlying SDK call (both providers)

Factory tests:
5. `get_completion_provider()` returns `OpenAICompletionProvider` by default
6. `get_completion_provider()` returns `AnthropicCompletionProvider` when `LLM_PROVIDER=anthropic`
7. `get_completion_provider()` returns `None` for unknown provider (e.g., `LLM_PROVIDER=garbage`)
8. Singleton caching — second call returns same object
9. `_reset_completion_provider()` clears cache, next call re-initializes
10. `LLM_DEFAULT_MODEL` env override passed to provider constructor
11. Thread safety — concurrent calls don't create multiple providers
12. Missing SDK package — lazy import raises `ImportError` with clear message (mock `import anthropic` to fail)

**`tests/utils/test_gpt_helpers.py`** (~10 tests):

Wrapper delegation tests:
13. `interpret_portfolio_risk` calls provider with correct system prompt and user prompt content
14. `interpret_portfolio_risk` returns `"(AI interpretation unavailable)"` when no provider
15. `generate_subindustry_peers` calls provider with correct prompt (contains ticker/name/industry)
16. `generate_subindustry_peers` returns `""` on no provider
17. `generate_subindustry_peers` returns `""` on provider exception
18. `generate_asset_class_classification` calls provider with system prompt and classification prompt
19. `generate_asset_class_classification` returns `"mixed,0.50"` on no provider
20. `generate_asset_class_classification` returns `"mixed,0.50"` on provider exception

Env override tests:
21. `LLM_INTERPRETATION_MODEL` env var overrides model passed to provider
22. `LLM_PEERS_MODEL` env var overrides model passed to provider for peer generation
23. `LLM_CLASSIFICATION_MODEL` env var overrides model passed to provider

Metadata test:
24. `core/interpretation.py` emits dynamic `interpretation_service` matching active provider name (mock `get_completion_provider()` to return provider with `provider_name="anthropic"`, verify metadata dict)

### Step 6: Verify existing test (`tests/mcp_tools/test_peers.py:340`)

`TestProxyBuilderImport.test_import_core_proxy_builder_without_openai_api_key` should now pass more cleanly — `gpt_helpers.py` no longer imports `openai` at module level.

### Step 7: Update `core/interpretation.py` metadata

Change **both** hardcoded `"interpretation_service": "gpt"` occurrences:
- `core/interpretation.py:75` (in `analyze_and_interpret()`)
- `core/interpretation.py:126` (in `interpret_portfolio_data()`)

```python
# Before (lines 75 and 126):
"interpretation_service": "gpt",
# After (both sites):
"interpretation_service": (get_completion_provider().provider_name if get_completion_provider() else "none"),
```

Add import at top of `core/interpretation.py`:
```python
from providers.completion import get_completion_provider
```

---

## Files Modified

| File | Action |
|------|--------|
| `providers/interfaces.py` | Add `CompletionProvider` Protocol |
| `providers/__init__.py` | Add barrel export |
| `providers/completion.py` | **NEW** — implementations + thread-safe factory |
| `utils/gpt_helpers.py` | Refactor to use provider, drop `model` param from `generate_subindustry_peers` |
| `core/interpretation.py` | Update `interpretation_service` metadata to use `provider_name` |
| `.env.example` | Add LLM_PROVIDER docs |
| `tests/providers/test_completion.py` | **NEW** — 12 tests |
| `tests/utils/test_gpt_helpers.py` | **NEW** — 12 tests (incl. env overrides + metadata) |

## Callers (minimal changes)

| File | Import | Change needed? |
|------|--------|----------------|
| `app.py:228,2049` | `interpret_portfolio_risk` | No — same signature |
| `core/interpretation.py:23` | `interpret_portfolio_risk` | **Yes** — update `"interpretation_service": "gpt"` → dynamic `get_completion_provider().provider_name` (line 75) |
| `core/risk_orchestration.py:49` | `interpret_portfolio_risk`, `generate_subindustry_peers` | No — same signatures |
| `core/proxy_builder.py:845` | `generate_subindustry_peers` | No — already uses keyword args `ticker=`, `name=`, `industry=` only |
| `services/security_type_service.py:1291` | `generate_asset_class_classification` | No — same signature |

## Out of Scope

- **No gateway routing for completions** — gateway is streaming/chat-only; adding a new endpoint is scope creep
- **No ProviderRegistry integration** — single active provider, not a fallback chain
- **No `anthropic` pip dependency enforcement** — lazy import; `ImportError` at runtime if package missing with `LLM_PROVIDER=anthropic`
- **No caller refactoring** — callers keep importing from `utils.gpt_helpers`

## Codex Review Round 1 — Issues Addressed

| # | Issue | Fix |
|---|-------|-----|
| 1 | `generate_subindustry_peers(model="gpt-4.1")` sends OpenAI ID to Anthropic | Dropped `model` param — all functions pass `model=None`, provider uses own default |
| 2 | `LLM_DEFAULT_MODEL` is provider-unsafe | Documented as provider-matched. Task-specific env vars added for all 3 functions |
| 3 | Anthropic multi-block response brittle | Join all TextBlock `.text` fields, not just `content[0]` |
| 4 | `interpretation_service: "gpt"` metadata wrong for Anthropic | Dynamic `provider_name` in `core/interpretation.py` (both lines 75 and 126) |
| 5 | Singleton not thread-safe | Added `threading.Lock` with double-check pattern (matches `redis_cache.py`) |
| 6 | Missing test cases | Added: multi-block, missing SDK, thread safety, env overrides, metadata |
| 7 | "6 Protocols" stale | Fixed to "9 Protocols" |

## Verification

1. `python -m pytest tests/providers/test_completion.py tests/utils/test_gpt_helpers.py -v`
2. `python -m pytest tests/mcp_tools/test_peers.py::TestProxyBuilderImport::test_import_core_proxy_builder_without_openai_api_key -v`
3. Full suite: `python -m pytest tests/ -x --timeout=60`
4. Manual: `LLM_PROVIDER=openai python -c "from utils.gpt_helpers import interpret_portfolio_risk; print(interpret_portfolio_risk('test')[:50])"`
