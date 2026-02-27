Issue recap – why ID-only caching can go stale  
------------------------------------------------
• `PortfolioCacheService` currently keys expensive results (risk score, full analysis, performance, etc.) by **portfolioId** alone.  
• But a portfolio’s holdings can change (upload a new statement, Plaid sync, manual edit) without the ID changing.  
• When that happens the cache still returns the **old** analysis, giving the user stale or incorrect numbers.

Does the issue still exist after the refactor?  
Yes.  
The new `PortfolioRepository` guarantees `id ↔ portfolio_name` mapping, but it does **not** create a new ID every time holdings change.  Therefore an ID-only cache key can still drift as soon as the user updates positions.

Best-practice solutions  
-----------------------

1. Content-hash cache key (recommended)  
   • Build a stable fingerprint of the inputs that influence analysis; e.g.  
     `SHA256(JSON.stringify(sortedHoldings))` + optional risk settings.  
   • Cache results under `portfolioId + '.' + contentHash`.  
   • When holdings change, the hash changes ⇒ automatic miss ⇒ fresh analysis stored under a new key.  
   • Keep a small “latest hash per portfolioId” map so you can quickly answer “do we already have a result for this exact state?”.

2. Version/ETag pattern (lighter weight)  
   • Maintain a `lastEdited` timestamp or `version` counter in `portfolioStore`.  
   • Include that value in the cache key: `portfolioId.v42`.  
   • Any operation that mutates holdings must bump the counter; cache miss follows.

3. Hard invalidation on writes (simplest to code)  
   • On any holdings-changing operation call `PortfolioCacheService.clear(portfolioId)`.  
   • Forces recomputation the next time; no hash calculation needed.  
   • Acceptable if edits are infrequent and analysis latency is tolerable.

4. TTL only (what you probably have now)  
   • Keep time-to-live (e.g. 10 min) per entry.  
   • Works, but user may still see stale data right after an edit; not ideal UX.

Ideal architectural choice  
• Combine #1 (deterministic content hash) with an **LRU cache** and an optional TTL fallback.  
  – Stale data impossible because the key changes whenever business-relevant data changes.  
  – You still reap the benefit of deduping identical analyses (same holdings uploaded twice, multi-tab usage, etc.).  
  – Implementation stays inside `PortfolioCacheService`; callers remain unaware.

Implementation sketch  
```ts
function buildCacheKey(portfolioId: string, holdings: Holding[]): string {
  const sorted = [...holdings].sort((a, b) => a.ticker.localeCompare(b.ticker));
  const hash   = sha256(JSON.stringify(sorted)).slice(0, 12); // 12-char prefix
  return `${portfolioId}.${hash}`;
}

async getRiskAnalysis(id: string, holdings: Holding[]) {
  const key = buildCacheKey(id, holdings);
  if (cache.has(key)) return cache.get(key);
  const result = await api.analyzePortfolio(id);
  cache.set(key, result, TTL);
  latestKeyByPortfolio[id] = key;
  return result;
}
```

• If holdings change the hash changes → new key → recompute.  
• If user hits refresh without changes, the same hash returns a fast cache hit.  
• You can expose `invalidatePortfolio(id)` that deletes every key beginning with `id.` if you need a manual nuke.

Bottom line  
Caching by ID alone is still risky. Switching to a **content-aware cache key (hash or version)** inside `PortfolioCacheService` eliminates stale-data bugs without changing public method signatures.

How to integrate content-aware caching into the current `PortfolioRepository` + ID architecture
====================================================================================================

The key insight: **cache invalidation is purely internal to `PortfolioCacheService`**—the rest of the architecture (Repository, stores, hooks, components) continues to work with stable IDs and doesn't need to change.

Implementation layers  
--------------------

1. **Store layer (`portfolioStore`) – track content changes**  
   Add a simple version counter or timestamp that bumps whenever holdings change:

```ts
interface PortfolioState {
  id: string;
  portfolio: Portfolio;
  riskScore: RiskScore | null;
  riskAnalysis: RiskAnalysis | null;
  lastUpdated: string | null;
  contentVersion: number;     // ← NEW: increments on holdings change
  isLoading: boolean;
  error: string | null;
}
```

Update the store actions:
```ts
updatePortfolio: (id: string, updates: Partial<Portfolio>) => {
  set((state) => {
    const existing = state.byId[id];
    if (!existing) return state;
    
    // Check if holdings actually changed
    const holdingsChanged = updates.holdings && 
      JSON.stringify(updates.holdings) !== JSON.stringify(existing.portfolio.holdings);
    
    return {
      byId: {
        ...state.byId,
        [id]: {
          ...existing,
          portfolio: { ...existing.portfolio, ...updates },
          contentVersion: holdingsChanged ? existing.contentVersion + 1 : existing.contentVersion,
          lastUpdated: new Date().toISOString(),
        },
      },
    };
  });
},
```

2. **Repository layer – expose version to cache**  
   Add a helper so `PortfolioCacheService` can fetch the content fingerprint:

```ts
export const PortfolioRepository = {
  // ... existing methods ...
  
  /**
   * Get portfolio holdings and version for cache key generation.
   * @param id Portfolio ID
   * @returns Holdings array + content version, or undefined if portfolio missing
   */
  getPortfolioContent(id: string): { holdings: Holding[]; version: number } | undefined {
    const state = usePortfolioStore.getState().byId[id];
    if (!state) return undefined;
    
    return {
      holdings: state.portfolio.holdings || [],
      version: state.contentVersion
    };
  },
};
```

3. **Cache layer (`PortfolioCacheService`) – version-aware keys**  
   Modify the cache to use content-aware keys internally:

```ts
export class PortfolioCacheService {
  private cache: Map<string, any> = new Map();
  private pendingOperations: Map<string, Promise<any>> = new Map();
  
  /**
   * Build cache key from portfolio ID + content version.
   */
  private buildCacheKey(portfolioId: string, operation: string): string | null {
    const content = PortfolioRepository.getPortfolioContent(portfolioId);
    if (!content) return null;
    
    return `${portfolioId}.${operation}.v${content.version}`;
  }
  
  async getRiskAnalysis(portfolioId: string, portfolio: Portfolio): Promise<any> {
    const operationKey = this.buildCacheKey(portfolioId, 'riskAnalysis');
    if (!operationKey) {
      throw new Error(`Portfolio ${portfolioId} not found in store`);
    }
    
    // Check cache first
    if (this.cache.has(operationKey)) {
      return this.cache.get(operationKey);
    }
    
    // Check for pending operation with same key
    if (this.pendingOperations.has(operationKey)) {
      return this.pendingOperations.get(operationKey);
    }
    
    // Perform analysis
    const analysisPromise = this.apiService.analyzePortfolio(portfolioId);
    this.pendingOperations.set(operationKey, analysisPromise);
    
    try {
      const result = await analysisPromise;
      this.cache.set(operationKey, result);
      return result;
    } finally {
      this.pendingOperations.delete(operationKey);
    }
  }
  
  // ... same pattern for getRiskScore, getPerformanceAnalysis, etc.
}
```

4. **Public interface stays the same**  
   Components and hooks continue to use stable portfolio IDs:

```ts
// This still works exactly as before
const currentId = PortfolioRepository.useCurrentId();
const riskAnalysis = await portfolioManager.analyzePortfolioRisk(currentId);
```

Alternative: Content-hash approach  
---------------------------------
If you prefer deterministic hashing over version numbers:

```ts
private buildCacheKey(portfolioId: string, operation: string): string | null {
  const content = PortfolioRepository.getPortfolioContent(portfolioId);
  if (!content) return null;
  
  // Create stable hash of holdings
  const sortedHoldings = [...content.holdings].sort((a, b) => a.ticker.localeCompare(b.ticker));
  const holdingsJson = JSON.stringify(sortedHoldings, Object.keys(sortedHoldings[0] || {}).sort());
  const hash = sha256(holdingsJson).slice(0, 12);
  
  return `${portfolioId}.${operation}.${hash}`;
}
```

Benefits  
--------
• **Zero breaking changes** – all public APIs (Repository, Manager, hooks) stay identical  
• **Automatic invalidation** – when holdings change, cache automatically misses and recomputes  
• **Deduplication preserved** – identical portfolios (across tabs, after undo/redo, etc.) still hit cache  
• **Granular by operation** – risk analysis cache independent from performance analysis cache  

Migration steps  
--------------
1. Add `contentVersion` field to `PortfolioState` interface  
2. Update store actions that modify holdings to bump version  
3. Add `getPortfolioContent()` to `PortfolioRepository`  
4. Modify `PortfolioCacheService` to use version-aware keys  
5. Test with: upload portfolio → analyze → edit holdings → analyze again (should recompute, not use stale cache)

The ID-based architecture remains intact—we're just making the cache smarter about when to invalidate itself.

Good question—there are several approaches to detecting holdings changes, each with trade-offs:

1. **Deep comparison on every update** (what I showed above)
```ts
updatePortfolio: (id: string, updates: Partial<Portfolio>) => {
  set((state) => {
    const existing = state.byId[id];
    if (!existing) return state;
    
    // Deep compare holdings arrays
    const holdingsChanged = updates.holdings && 
      JSON.stringify(updates.holdings) !== JSON.stringify(existing.portfolio.holdings);
    
    // Bump version only if holdings actually changed
    return {
      byId: {
        ...state.byId,
        [id]: {
          ...existing,
          portfolio: { ...existing.portfolio, ...updates },
          contentVersion: holdingsChanged ? existing.contentVersion + 1 : existing.contentVersion,
        },
      },
    };
  });
}
```

**Pros**: Precise—only bumps version when holdings actually change  
**Cons**: `JSON.stringify()` comparison can be expensive for large portfolios; brittle if object key order differs

2. **Assume any `updatePortfolio()` call is meaningful** (simpler)
```ts
updatePortfolio: (id: string, updates: Partial<Portfolio>) => {
  set((state) => {
    const existing = state.byId[id];
    if (!existing) return state;
    
    return {
      byId: {
        ...state.byId,
        [id]: {
          ...existing,
          portfolio: { ...existing.portfolio, ...updates },
          contentVersion: existing.contentVersion + 1,  // Always increment
        },
      },
    };
  });
}
```

**Pros**: Simple, fast, never misses a change  
**Cons**: Cache invalidates even for cosmetic updates (like `portfolio_name` changes)

3. **Caller-specified invalidation** (most explicit)
```ts
updatePortfolio: (id: string, updates: Partial<Portfolio>, invalidateCache = false) => {
  set((state) => {
    // ... update logic ...
    contentVersion: invalidateCache ? existing.contentVersion + 1 : existing.contentVersion,
  });
}

// Callers decide when cache should invalidate
PortfolioRepository.update(id, { holdings: newHoldings }, true);   // invalidate
PortfolioRepository.update(id, { portfolio_name: newName }, false); // don't invalidate
```

**Pros**: Explicit control, optimal performance  
**Cons**: Callers must remember to pass the flag correctly

4. **Field-specific detection** (recommended for precision)
```ts
updatePortfolio: (id: string, updates: Partial<Portfolio>) => {
  set((state) => {
    const existing = state.byId[id];
    if (!existing) return state;
    
    // Check only specific fields that affect analysis
    const cacheInvalidatingFields = ['holdings', 'total_portfolio_value'];
    const shouldInvalidate = cacheInvalidatingFields.some(field => 
      updates[field] !== undefined && updates[field] !== existing.portfolio[field]
    );
    
    return {
      byId: {
        ...state.byId,
        [id]: {
          ...existing,
          portfolio: { ...existing.portfolio, ...updates },
          contentVersion: shouldInvalidate ? existing.contentVersion + 1 : existing.contentVersion,
        },
      },
    };
  });
}
```

**Pros**: Precise without expensive deep comparison  
**Cons**: Must maintain list of fields that affect cache validity

5. **Separate action for holdings updates** (cleanest API)
```ts
// Regular updates (don't invalidate cache)
updatePortfolio: (id: string, updates: Partial<Portfolio>) => { ... }

// Holdings-specific updates (always invalidate)
updatePortfolioHoldings: (id: string, holdings: Holding[]) => {
  set((state) => ({
    byId: {
      ...state.byId,
      [id]: {
        ...existing,
        portfolio: { ...existing.portfolio, holdings },
        contentVersion: existing.contentVersion + 1,  // Always bump for holdings
      },
    },
  }));
}
```

**Recommendation**: Start with approach #4 (field-specific detection)  
It's precise, performant, and explicit about which changes matter for cache invalidation. You can always add more sophisticated logic later if needed.

The key insight: **holdings changes** are the main driver of stale cache, so focus detection on that field specifically rather than trying to detect all possible content changes.