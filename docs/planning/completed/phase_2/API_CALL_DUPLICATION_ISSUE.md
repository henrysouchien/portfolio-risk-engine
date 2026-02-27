Exactly.  
Think of it as a hub-and-spokes model:

> "✅ RESOLVED - Hub-and-spokes cache sharing pattern successfully implemented via shared TanStack Query cache keys and multi-level caching architecture."

1. The hub  
   • A single hook (`usePortfolioRiskAnalysis`) owns the expensive fetch and the React-Query cache key.  
   • It’s the **only** place where `manager.analyzePortfolioRisk()` is called.

```ts
export const usePortfolioRiskAnalysis = (portfolioId?: string) =>
  useQuery({
    queryKey: ['portfolioRiskAnalysis', portfolioId ?? null],
    enabled: !!portfolioId,
    queryFn: () => manager.analyzePortfolioRisk(portfolioId!),
    staleTime: 5 * 60 * 1000,
  });
```

2. The spokes  
   • Other hooks (factor analysis, concentration analysis, whatever) *subscribe* to that cache entry and transform it locally—no network traffic.

Option A – reuse the same query with `select`:

```ts
export const useFactorAnalysis = (portfolioId?: string) =>
  useQuery({
    queryKey: ['portfolioRiskAnalysis', portfolioId ?? null],
    enabled: !!portfolioId,
    select: (base) =>
      base ? factorAdapter.transform(base.analysis) : undefined,
  });
```

Option B – simple wrapper:

```ts
export const useFactorAnalysis = (portfolioId?: string) => {
  const { data: base, ...state } = usePortfolioRiskAnalysis(portfolioId);
  return { data: base && factorAdapter.transform(base.analysis), ...state };
};
```

3. Usage in components  
   Each view keeps its own hook call, but those hooks now share the same cache entry:

```tsx
const { data: factorData, isLoading } = useFactorAnalysis(portfolioId);
const { data: riskData } = useRiskAnalysis(portfolioId);       // if you still need the raw data
```

4. Resulting behaviour  
   • One HTTP request per 5-minute cache window in production.  
   • In React-18 dev mode the second mount hits the hub hook again, but the request is served instantly from React-Query + `PortfolioCacheService`, so no duplicate back-end traffic.  

5. Benefits  
   • No duplicated network calls.  
   • Hooks stay specialised and easy to reason about.  
   • Adding a new view is trivial: write a new adapter and derive from the hub.

That’s the entire pattern: one “real” fetching hook, and any number of lightweight, read-only hooks that piggy-back on its cached data.