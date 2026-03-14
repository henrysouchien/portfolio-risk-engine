# Spec: Portfolio Selector

## Context

The app supports multiple portfolios per user (IBKR, Schwab, combined, custom CSV imports), but there is **no UI to switch between them**. The backend and store architecture fully support it — only the frontend component and wiring are missing.

**Backend endpoints** (all exist, all working):
- `GET /api/portfolios` → `{ portfolios: string[], count: number }` — list names for current user
- `GET /api/portfolios/{name}` → `{ portfolio_data, portfolio_name, portfolio_metadata }` — load one
- `POST /api/portfolios` — create
- `DELETE /api/portfolios/{name}` — delete

**Frontend store** (already supports multi-portfolio):
- `portfolioStore.byId: Record<string, PortfolioState>` — normalized map
- `portfolioStore.currentPortfolioId: string | null` — active selection
- `PortfolioRepository.setCurrent(id)` — switch active portfolio
- `PortfolioRepository.add(raw)` — upsert portfolio into store, returns id
- `PortfolioRepository.useCurrentName()` — hook for current portfolio name

**Current behavior**: `PortfolioInitializer` fetches `CURRENT_PORTFOLIO` by name, adds to store, sets as current. No list fetch, no switching.

---

## Files

| File | Action |
|------|--------|
| `frontend/packages/chassis/src/services/RiskAnalysisService.ts` | **Edit** — add `listPortfolios()` method |
| `frontend/packages/chassis/src/services/APIService.ts` | **Edit** — expose `listPortfolios()` |
| `frontend/packages/connectors/src/features/portfolio/hooks/usePortfolioList.ts` | **Create** — React Query hook for portfolio list |
| `frontend/packages/connectors/src/index.ts` | **Edit** — re-export `usePortfolioList` |
| `frontend/packages/ui/src/components/dashboard/PortfolioSelector.tsx` | **Create** — dropdown component |
| `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx` | **Edit** — add selector to header |
| `frontend/packages/connectors/src/providers/PortfolioInitializer.tsx` | **Edit** — remember last-used portfolio |

---

## Step 1: Add `listPortfolios()` to API service

**File: `frontend/packages/chassis/src/services/RiskAnalysisService.ts`**

Add after the existing `getPortfolio()` method (~line 230):

```typescript
interface PortfoliosListResponse {
  success: boolean;
  portfolios: string[];
  count: number;
}

async listPortfolios(): Promise<PortfoliosListResponse> {
  return this.request<PortfoliosListResponse>('/api/portfolios', { method: 'GET' });
}
```

**File: `frontend/packages/chassis/src/services/APIService.ts`**

Add a delegate method (following the existing `getPortfolio` pattern):

```typescript
async listPortfolios() {
  return this.riskAnalysisService.listPortfolios();
}
```

---

## Step 2: Create `usePortfolioList` hook

**File: `frontend/packages/connectors/src/features/portfolio/hooks/usePortfolioList.ts`** (new)

```typescript
import { useQuery } from '@tanstack/react-query';
import { useAPIService } from '../../..';  // or wherever useAPIService is exported

export function usePortfolioList() {
  const api = useAPIService();

  return useQuery({
    queryKey: ['portfolios', 'list'],
    enabled: !!api,
    staleTime: 30_000,        // 30s — list doesn't change often
    refetchOnWindowFocus: false,
    queryFn: async () => {
      if (!api) throw new Error('API not available');
      const res = await api.listPortfolios();
      return res.portfolios;  // string[] of portfolio names
    },
  });
}
```

**File: `frontend/packages/connectors/src/index.ts`**

Add re-export:
```typescript
export { usePortfolioList } from './features/portfolio/hooks/usePortfolioList';
```

---

## Step 3: Create `PortfolioSelector` component

**File: `frontend/packages/ui/src/components/dashboard/PortfolioSelector.tsx`** (new)

Dropdown in the header showing available portfolios. Clicking one loads it and switches.

### Props
```typescript
interface PortfolioSelectorProps {
  portfolioNames: string[];
  currentName: string | null;
  isLoading: boolean;
  onSelect: (name: string) => void;
  isSwitching: boolean;    // true while loading new portfolio data
}
```

### Behavior
- Shows current portfolio name (truncated to ~20 chars) with a `ChevronDown` icon
- Dropdown lists all portfolio names with a check mark on the active one
- Clicking a different portfolio calls `onSelect(name)`
- While `isSwitching`, show a spinner on the button instead of chevron
- If only 1 portfolio, still show the name but disable the dropdown (no chevron)
- If `isLoading` (list still fetching), show skeleton placeholder

### Styling
Use existing `DropdownMenu` components from `../ui/dropdown-menu` (same pattern as the old Analytics dropdown that was removed). Button style: `text-sm font-medium text-neutral-700` with `hover:bg-white/60 rounded-xl px-3 py-1.5` — matches the refresh/layout toggle buttons in `headerActions`.

Active item: `bg-emerald-50 text-emerald-700` with `Check` icon. Inactive: standard dropdown item style.

### Implementation sketch
```tsx
import { Check, ChevronDown, Loader2 } from 'lucide-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '../ui/dropdown-menu';

export const PortfolioSelector: FC<PortfolioSelectorProps> = ({
  portfolioNames, currentName, isLoading, onSelect, isSwitching,
}) => {
  if (isLoading) {
    return <div className="h-8 w-32 rounded-xl bg-neutral-100 animate-pulse" />;
  }

  const displayName = currentName
    ? currentName.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    : 'No Portfolio';

  if (portfolioNames.length <= 1) {
    return (
      <span className="text-sm font-medium text-neutral-700 px-3 py-1.5">
        {displayName}
      </span>
    );
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button className="flex items-center gap-1.5 rounded-xl px-3 py-1.5 text-sm font-medium text-neutral-700 hover:bg-white/60 transition-colors">
          {displayName}
          {isSwitching
            ? <Loader2 className="h-3.5 w-3.5 animate-spin text-neutral-400" />
            : <ChevronDown className="h-3.5 w-3.5 text-neutral-400" />}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        {portfolioNames.map(name => {
          const isActive = name === currentName;
          const label = name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
          return (
            <DropdownMenuItem
              key={name}
              onClick={() => !isActive && onSelect(name)}
              className={isActive ? 'bg-emerald-50 text-emerald-700' : ''}
            >
              {isActive && <Check className="h-4 w-4 mr-2" />}
              <span className={isActive ? '' : 'ml-6'}>{label}</span>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
};
```

---

## Step 4: Wire into ModernDashboardApp header

**File: `frontend/packages/ui/src/components/apps/ModernDashboardApp.tsx`**

### 4a: Import
```typescript
import { PortfolioSelector } from '../dashboard/PortfolioSelector';
import { usePortfolioList } from '@risk/connectors';
```

Also import `PortfolioRepository` from `@risk/chassis` (for `useCurrentName`, `setCurrent`, `add`).

### 4b: Add switching logic inside `ModernDashboardApp`

```typescript
const currentPortfolioName = PortfolioRepository.useCurrentName();
const { data: portfolioNames = [], isLoading: isListLoading } = usePortfolioList();
const [isSwitching, setIsSwitching] = useState(false);
const api = useAPIService();

const handlePortfolioSwitch = useCallback(async (name: string) => {
  if (!api || name === currentPortfolioName) return;
  setIsSwitching(true);
  try {
    const res = await api.getPortfolio(name);
    if (res?.success && res.portfolio_data) {
      const portfolioObj = { ...res.portfolio_data, portfolio_name: name };
      const id = PortfolioRepository.add(portfolioObj);
      PortfolioRepository.setCurrent(id);
      // Invalidate all data queries so they refetch for new portfolio
      await queryClient.invalidateQueries();
      // Remember selection
      const userId = useAuthStore.getState().user?.id;
      if (userId) {
        window.localStorage.setItem(`lastPortfolio_${userId}`, name);
      }
    }
  } finally {
    setIsSwitching(false);
  }
}, [api, currentPortfolioName, queryClient]);
```

### 4c: Place in header

Add the `PortfolioSelector` between `brandHeader` and `headerActions`. Update the header layout in the `brandHeader` JSX — insert after the brand title `div`:

```tsx
const brandHeader = (
  <div className="flex items-center space-x-4 shrink-0">
    {/* existing brand icon + title */}
    ...
    <div className="h-6 w-px bg-neutral-200/60" />  {/* vertical separator */}
    <PortfolioSelector
      portfolioNames={portfolioNames}
      currentName={currentPortfolioName}
      isLoading={isListLoading}
      onSelect={handlePortfolioSwitch}
      isSwitching={isSwitching}
    />
  </div>
);
```

---

## Step 5: Remember last-used portfolio

**File: `frontend/packages/connectors/src/providers/PortfolioInitializer.tsx`**

Change the "pick first" logic to prefer the user's last selection:

Current (line ~140-146):
```typescript
const state = usePortfolioStore.getState();
const firstId = Object.keys(state.byId)[0];
if (firstId) {
  PortfolioRepository.setCurrent(firstId);
  return state.byId[firstId].portfolio;
}
// Fallback: request a default portfolio from backend by name
const res = await api.getPortfolio(DEFAULT_PORTFOLIO_NAME);
```

After:
```typescript
const state = usePortfolioStore.getState();
const firstId = Object.keys(state.byId)[0];
if (firstId) {
  PortfolioRepository.setCurrent(firstId);
  return state.byId[firstId].portfolio;
}

// Prefer last-used portfolio, fall back to default
const lastUsed = userId
  ? window.localStorage.getItem(`lastPortfolio_${userId}`)
  : null;
const portfolioToLoad = lastUsed || DEFAULT_PORTFOLIO_NAME;
const res = await api.getPortfolio(portfolioToLoad);
```

If `lastUsed` 404s (deleted portfolio), catch and fall back to `DEFAULT_PORTFOLIO_NAME`.

---

## Verification

```bash
cd frontend && npx tsc --noEmit  # Zero TS errors
```

Visual checks at localhost:3000:
- Portfolio name visible in header between brand and refresh button
- If user has 2+ portfolios: dropdown opens, shows list with check on active
- Click different portfolio: spinner appears, data reloads, all views update
- If user has 1 portfolio: name displayed, no dropdown chevron
- Refresh page: same portfolio re-selected (localStorage persistence)
- Sidebar layout: selector visible in header
- Header layout: selector visible in header

## Summary

| What | Action |
|------|--------|
| `RiskAnalysisService.ts` | Add `listPortfolios()` (~10 lines) |
| `APIService.ts` | Add delegate (~3 lines) |
| `usePortfolioList.ts` | New hook (~20 lines) |
| `PortfolioSelector.tsx` | New component (~60 lines) |
| `ModernDashboardApp.tsx` | Add selector to header + switch handler (~30 lines) |
| `PortfolioInitializer.tsx` | Prefer last-used portfolio (~5 lines) |
| **Net new code** | **~130 lines** |
