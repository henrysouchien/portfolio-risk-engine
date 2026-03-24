# Add Provider Button + Placeholder Modal

## Context

The Data Providers card shows provider status but has no "Add Provider" button like Account Connections has "Add Account." We need the button + a modal that lists available providers with status and descriptions. Actual configuration (API key entry, gateway setup) is not built yet — the modal is a placeholder showing what's available and their current status.

## Changes

This is a frontend-only change — no backend work needed. The modal reuses the provider data already fetched by `useDataProviders()`.

### Step 1: Add "Add Provider" button to DataProviders.tsx
**File:** `frontend/packages/ui/src/components/settings/DataProviders.tsx`

Convert the CardHeader to a flex-row layout matching AccountConnections (currently stacked, needs `flex flex-row items-center justify-between space-y-0 pb-4`). Title/description go in a left `<div>`, button goes on the right:

```tsx
<CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
  <div>
    <CardTitle className="text-lg">Data Providers</CardTitle>
    <CardDescription>Market data and pricing sources</CardDescription>
  </div>
  <Button variant="outline" size="sm" onClick={() => setShowModal(true)} disabled={isLoading}>
    <Plus className="w-4 h-4 mr-1" />
    Add Provider
  </Button>
</CardHeader>
```

Add `useState` for modal open/close. Pass `showModal` + `onClose` to a new `ProviderPickerModal` rendered at the bottom.

### Step 2: Create ProviderPickerModal component
**File:** `frontend/packages/ui/src/components/settings/ProviderPickerModal.tsx` (new)

Simple dialog using the existing `Dialog` / `DialogContent` / `DialogHeader` pattern from `ui/dialog.tsx`.

Define a local `STATUS_DOT` map in this file (same as DataProviders.tsx — small duplication is fine for a self-contained modal):
```ts
const STATUS_DOT: Record<string, string> = {
  active: "bg-emerald-500",
  inactive: "bg-neutral-400",
  error: "bg-red-500",
};
```

Modal JSX:
```tsx
<Dialog open={open} onOpenChange={(nextOpen) => !nextOpen && onClose()}>
  <DialogContent className="max-w-lg">
    <DialogHeader>
      <DialogTitle>Data Providers</DialogTitle>
      <DialogDescription>Available market data and pricing sources</DialogDescription>
    </DialogHeader>
    <div className="space-y-3 py-4">
      {providers.map(provider => (
        <div key={provider.id} className="flex items-center justify-between p-3 rounded-lg border">
          <div className="flex items-center gap-3">
            <span className={`w-2 h-2 rounded-full ${STATUS_DOT[provider.status] || STATUS_DOT.inactive}`} />
            <div>
              <div className="text-sm font-medium">{provider.name}</div>
              <div className="text-xs text-muted-foreground">{provider.detail}</div>
            </div>
          </div>
          <Badge variant="outline" className="text-xs text-muted-foreground">
            {provider.status === 'active' ? 'Connected' : 'Setup required'}
          </Badge>
        </div>
      ))}
    </div>
    <p className="text-xs text-muted-foreground text-center pb-2">
      Provider configuration coming soon. Contact support to add new data sources.
    </p>
  </DialogContent>
</Dialog>
```

Props: `{ providers: DataProviderInfo[], open: boolean, onClose: () => void }`

Note: Provider names come from the backend as full names ("Financial Modeling Prep", "Interactive Brokers") — no frontend label mapping needed.

### Step 3: Wire modal in DataProviders.tsx
Import `ProviderPickerModal` and render it at the bottom of the component, passing `providers`, `showModal`, and `onClose` handler.

## Files Modified
| File | Change |
|------|--------|
| `ui/src/components/settings/DataProviders.tsx` | Add button + modal state + render modal |
| `ui/src/components/settings/ProviderPickerModal.tsx` | **New**: placeholder modal |

## Verification
1. `cd frontend && npx tsc --noEmit` — type check
2. Browser: Data Providers card shows "Add Provider" button in header (right side, matching Account Connections layout). Click opens modal showing "Financial Modeling Prep" + "Interactive Brokers" with status dots and detail strings. "Coming soon" message at bottom.
