# AI Providers Settings Card

## Context

The Settings page has Account Connections (brokerages) and Data Providers (FMP, IBKR). The recently landed `CompletionProvider` protocol abstraction (`providers/completion.py`) supports OpenAI and Anthropic as pluggable AI backends. We need an "AI Providers" card showing which AI provider is active, what model is configured, and whether the API key is present. Same registry pattern as Data Providers.

## Steps

### Step 1: Backend route with AI provider registry
**New file:** `routes/ai_providers.py`

Same pattern as `routes/data_providers.py`. **Single source of truth** — add class-level metadata to each provider in `providers/completion.py`, then the route reads it from there.

**Step 1a: Add metadata attrs to provider classes in `providers/completion.py`:**

Add these class-level attributes to both `OpenAICompletionProvider` and `AnthropicCompletionProvider`:
```python
class OpenAICompletionProvider:
    provider_name = "openai"
    display_name = "OpenAI"          # NEW
    api_key_env = "OPENAI_API_KEY"   # NEW
    # default_model already in __init__ signature: "gpt-4.1"

class AnthropicCompletionProvider:
    provider_name = "anthropic"
    display_name = "Anthropic"       # NEW
    api_key_env = "ANTHROPIC_API_KEY" # NEW
    # default_model already in __init__ signature: "claude-sonnet-4-20250514"
```

Also export a helper that returns provider metadata without instantiating:
```python
def get_provider_metadata() -> dict[str, dict[str, str]]:
    """Return metadata for all registered providers (no instantiation)."""
    import inspect
    result = {}
    for pid, factory in _PROVIDER_FACTORIES.items():
        sig = inspect.signature(factory.__init__)
        default_model = sig.parameters.get("default_model")
        result[pid] = {
            "display_name": getattr(factory, "display_name", pid),
            "api_key_env": getattr(factory, "api_key_env", ""),
            "default_model": default_model.default if default_model and default_model.default is not inspect.Parameter.empty else "unknown",
        }
    return result
```

**Step 1b: Route reads from source of truth in `routes/ai_providers.py`:**

```python
from providers.completion import _PROVIDER_FACTORIES, get_provider_metadata

def _build_ai_provider_statuses() -> list[AIProviderStatus]:
    active_name = os.getenv("LLM_PROVIDER", "openai").strip().lower()
    model_override = os.getenv("LLM_DEFAULT_MODEL", "").strip() or None
    metadata = get_provider_metadata()
    results = []
    for pid in _PROVIDER_FACTORIES:
        meta = metadata.get(pid, {})
        has_key = bool(os.getenv(meta.get("api_key_env", ""), "").strip())
        is_active = pid == active_name
        model = model_override if (is_active and model_override) else meta.get("default_model", "unknown")
        if is_active and has_key:
            status, detail = "active", f"{model} (active)"
        elif has_key:
            status, detail = "inactive", f"{model} (available)"
        else:
            status, detail = "inactive", "API key not configured"
        results.append(AIProviderStatus(id=pid, name=meta.get("display_name", pid), status=status, detail=detail))
    if active_name not in _PROVIDER_FACTORIES:
        results.insert(0, AIProviderStatus(
            id=active_name, name=active_name, status="error",
            detail=f"Unknown provider '{active_name}' — completion disabled"
        ))
    return results
```

Zero hardcoded metadata in the route — everything derived from provider classes. Adding a new provider to `_PROVIDER_FACTORIES` with the class attrs automatically surfaces it in the card.

**Endpoint:** `GET /api/v2/ai-providers` → `{"providers": [...]}`. No auth required.

### Step 2: Register route in app.py
**File:** `app.py`
```python
from routes.ai_providers import ai_providers_router
app.include_router(ai_providers_router)
```

### Step 3: Frontend types
**File:** `frontend/packages/chassis/src/types/index.ts`

Reuse `DataProviderInfo` — same shape (`id`, `name`, `status`, `detail`). Add a type alias or just use `DataProviderInfo` directly for AI providers too. If we want to keep them separate:
```ts
export interface AIProviderInfo {
  id: string
  name: string
  status: 'active' | 'inactive' | 'error'
  detail: string
}
export interface AIProvidersResponse {
  providers: AIProviderInfo[]
}
```

### Step 4: Frontend service methods
**File:** `frontend/packages/chassis/src/services/RiskAnalysisService.ts`
```ts
async listAIProviders(): Promise<AIProvidersResponse> {
  return this.request<AIProvidersResponse>('/api/v2/ai-providers', { method: 'GET' });
}
```

**File:** `frontend/packages/chassis/src/services/APIService.ts`
```ts
async listAIProviders() { return this.riskAnalysisService.listAIProviders(); }
```

### Step 5: useAIProviders hook
**File:** `frontend/packages/connectors/src/features/settings/hooks/useAIProviders.ts` (new)

Same pattern as `useDataProviders`:
```ts
export const useAIProviders = () => {
  const api = useAPIService();
  return useQuery({
    queryKey: ['settings', 'ai-providers'],
    enabled: !!api,
    staleTime: 60_000,
    refetchOnWindowFocus: true,
    queryFn: async () => {
      if (!api) throw new Error('API not available');
      return api.listAIProviders();
    },
  });
};
```

**Export chain:**
- `features/settings/index.ts` — add export
- `connectors/src/index.ts` — add to settings re-export

### Step 6: Presentational component
**New file:** `frontend/packages/ui/src/components/settings/AIProviders.tsx`

Same card pattern as DataProviders:
- `Card variant="glassTinted" hover="lift"`
- CardHeader flex-row: "AI Providers" / "Language model and intelligence services" + "Add Provider" button
- CardContent: `divide-y` rows with status dots + name + detail
- Status dots: active=emerald-500, inactive=neutral-400, error=red-500
- Error banner if fetch fails
- "Add Provider" button opens same-style placeholder modal (`AIProviderPickerModal`)

### Step 7: Container component
**New file:** `frontend/packages/ui/src/components/settings/AIProvidersContainer.tsx`
```tsx
const AIProvidersContainer: React.FC = () => {
  const { data, isLoading, error } = useAIProviders();
  return <AIProviders providers={data?.providers ?? []} isLoading={isLoading} error={error?.message ?? null} />;
};
```

### Step 8: Placeholder modal
**New file:** `frontend/packages/ui/src/components/settings/AIProviderPickerModal.tsx`

Same pattern as `ProviderPickerModal.tsx` — dialog showing available AI providers with status, "coming soon" footer.

### Step 9: Mount on Settings page
**File:** `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`

Add lazy import + mount between DataProvidersContainer and CsvImportCard:
```tsx
const AIProvidersContainer = React.lazy(() => import('../settings/AIProvidersContainer'));
```

Settings order becomes:
1. RiskSettingsContainer
2. PreferencesCard
3. AccountConnectionsContainer
4. DataProvidersContainer
5. **AIProvidersContainer** (new)
6. CsvImportCard

### Step 10: Tests
**New file:** `tests/routes/test_ai_providers.py`
- `test_openai_active` — LLM_PROVIDER=openai + OPENAI_API_KEY present → active
- `test_openai_available` — LLM_PROVIDER=anthropic + OPENAI_API_KEY present → inactive with "available"
- `test_openai_no_key` — no OPENAI_API_KEY → inactive
- `test_anthropic_active` — LLM_PROVIDER=anthropic + key present → active
- `test_endpoint_returns_both` — verify response has 2 providers
- `test_unknown_llm_provider` — LLM_PROVIDER=garbage → error entry with "Unknown provider" detail
- `test_model_override_only_active` — LLM_DEFAULT_MODEL set → only active provider shows override, inactive shows built-in default

**Update:** `tests/routes/test_phase5a_router_registration.py` — add `/api/v2/ai-providers` assertion

## Files Modified
| File | Change |
|------|--------|
| `providers/completion.py` | Add display_name, api_key_env attrs + get_provider_metadata() |
| `routes/ai_providers.py` | **New**: route using get_provider_metadata() |
| `app.py` | Register router |
| `chassis/src/types/index.ts` | Add 2 interfaces |
| `chassis/src/services/RiskAnalysisService.ts` | Add `listAIProviders()` |
| `chassis/src/services/APIService.ts` | Add pass-through |
| `connectors/src/features/settings/hooks/useAIProviders.ts` | **New**: hook |
| `connectors/src/features/settings/index.ts` | Add export |
| `connectors/src/index.ts` | Add export |
| `ui/src/components/settings/AIProviders.tsx` | **New**: presentational + button |
| `ui/src/components/settings/AIProvidersContainer.tsx` | **New**: container |
| `ui/src/components/settings/AIProviderPickerModal.tsx` | **New**: placeholder modal |
| `ui/src/components/apps/ModernDashboardApp.tsx` | Lazy import + mount |
| `tests/routes/test_ai_providers.py` | **New**: backend tests |
| `tests/routes/test_phase5a_router_registration.py` | Add route assertion |

## Verification
1. `cd frontend && npx tsc --noEmit` — type check
2. `pytest tests/routes/test_ai_providers.py -x` — backend tests
3. Browser: Settings page shows AI Providers card below Data Providers with OpenAI (active) and Anthropic (available) with model names
