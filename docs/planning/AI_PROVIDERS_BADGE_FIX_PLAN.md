# F3: AI Providers Grey Badge Fix

## Problem

In Settings > Integrations > AI Providers, a configured-but-not-active provider (e.g. Anthropic when OpenAI is active) shows a grey status dot identical to an unconfigured provider. Users cannot distinguish "has API key, ready to use" from "not set up at all." The fix adds an `"available"` status for configured-but-inactive providers, rendered as a blue dot.

## Root Cause

- **`routes/ai_providers.py:39-42`** — Lines 39-42 assign `status="inactive"` for both "has key but not active" (L40) and "no key at all" (L42). The detail string differentiates them (`"(available)"` vs `"API key not configured"`), but status does not.
- **`AIProviderStatus` model (L15)** — `Literal["active", "inactive", "error"]` has no `"available"` variant.
- **`frontend/packages/chassis/src/types/index.ts:127`** — `status: 'active' | 'inactive' | 'error'` same gap.
- **`frontend/packages/ui/src/components/settings/AIProviders.tsx:16-20`** — `STATUS_DOT` maps `inactive` to grey. No `available` entry.

## Changes

### 1. Backend: `routes/ai_providers.py`

**L15** — Expand the Literal type:
```python
# before
status: Literal["active", "inactive", "error"]
# after
status: Literal["active", "available", "inactive", "error"]
```

**L40** — Change status for has-key-but-not-active:
```python
# before
status, detail = "inactive", f"{model} (available)"
# after
status, detail = "available", f"{model} (available)"
```

No change to L42 (no key = stays `"inactive"`).

### 2. Frontend type: `frontend/packages/chassis/src/types/index.ts`

**L127** — Add `'available'` to the union:
```ts
// before
status: 'active' | 'inactive' | 'error';
// after
status: 'active' | 'available' | 'inactive' | 'error';
```

### 3. Frontend component: `frontend/packages/ui/src/components/settings/AIProviders.tsx`

**L16-20** — Add `available` entry with blue dot:
```ts
// before
const STATUS_DOT: Record<AIProviderInfo['status'], string> = {
  active: 'bg-up',
  inactive: 'bg-[hsl(var(--text-dim))]',
  error: 'bg-down',
};
// after
const STATUS_DOT: Record<AIProviderInfo['status'], string> = {
  active: 'bg-up',
  available: 'bg-blue-400',
  inactive: 'bg-[hsl(var(--text-dim))]',
  error: 'bg-down',
};
```

Using `bg-blue-400` (Tailwind blue) — visually distinct from green (active) and grey (unconfigured). The `Record<AIProviderInfo['status'], string>` type ensures the compiler enforces exhaustive mapping.

### 4. Frontend component: `AIProviderPickerModal.tsx`

The modal switches on `provider.status` in two places:

**L18-22** — `STATUS_DOT` color map (typed as `Record<string, string>`, falls back to `STATUS_DOT.inactive` for unknown keys). Add `available`:
```ts
// before
const STATUS_DOT: Record<string, string> = {
  active: 'bg-foreground/80',
  inactive: 'bg-[hsl(var(--text-dim))]',
  error: 'bg-[hsl(var(--down))]',
};
// after
const STATUS_DOT: Record<string, string> = {
  active: 'bg-foreground/80',
  available: 'bg-blue-400',
  inactive: 'bg-[hsl(var(--text-dim))]',
  error: 'bg-[hsl(var(--down))]',
};
```

**L49** — Badge text uses `provider.status === 'active' ? 'Configured' : 'Setup required'`, so an `available` provider incorrectly shows "Setup required". Expand the ternary:
```ts
// before
{provider.status === 'active' ? 'Configured' : 'Setup required'}
// after
{provider.status === 'active' ? 'Configured' : provider.status === 'available' ? 'Available' : 'Setup required'}
```

### 5. Tests: `tests/routes/test_ai_providers.py`

**`test_openai_available` (L47)** — Update expected status:
```python
# before
assert openai["status"] == "inactive"
# after
assert openai["status"] == "available"
```

**`test_model_override_only_active` (L128)** — Anthropic has a key but is not active, so its status changes too:
```python
# before (implicit — anthropic has key + not active = "inactive")
# after — assert anthropic status == "available"
```
Add explicit assertion: `assert providers["anthropic"]["status"] == "available"`.

### 6. Tests: `AIProviders.test.tsx`

Current tests only exercise `active` providers (L22-38). Add two tests:

**Test: AIProviders renders `available` status path** — render `AIProviders` with a provider whose `status` is `'available'` and verify the dot receives the `bg-blue-400` class (not `bg-up` or `bg-[hsl(var(--text-dim))]`).

**Test: AIProviderPickerModal renders `available` provider correctly** — unmock `AIProviderPickerModal`, render it directly with `open={true}` and an `available` provider. Assert:
- The dot has `bg-blue-400` class
- The badge text reads "Available" (not "Setup required")

## Risks / Edge Cases

- **Backward compat** — If any external consumer caches the old `"inactive"` value, they will see a new `"available"` string. This is internal-only API, so no risk.
- **Tailwind purge** — `bg-blue-400` is a standard Tailwind class; should be included in the build. Verify in dev.

## Scope

6 files, ~12 line changes, 2 new frontend tests. No new dependencies. No migration.
