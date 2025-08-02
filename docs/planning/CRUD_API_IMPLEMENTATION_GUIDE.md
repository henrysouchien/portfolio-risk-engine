# CRUD API Implementation Guide

## Overview
This guide shows how to implement CRUD (Create, Read, Update, Delete) operations using our multi-user safe architecture template. CRUD operations are perfect examples of grouped functionality that should share infrastructure layers while maintaining proper user isolation.

## CRUD Pattern: Portfolio Management Example

We'll implement portfolio CRUD operations as a complete example that can be adapted for any CRUD domain.

---

## Phase 1: Multi-User Safe CRUD Implementation

### Step 1: API Registry (All CRUD Endpoints)
**Location**: `frontend/src/apiRegistry.ts`

```typescript
export const apiRegistry = {
  // ... existing entries
  
  // Portfolio CRUD operations (grouped by domain)
  portfolioCreate: {
    path: '/api/portfolios',
    method: 'POST' as const,
    description: 'Create a new portfolio for the current user',
    requestShape: {
      name: 'string',
      description: 'string',
      initial_holdings: 'array', // optional
      risk_profile: 'string' // optional
    },
    responseShape: {
      success: 'boolean',
      portfolio_id: 'string',
      portfolio: 'object',
      created_at: 'string'
    }
  },
  
  portfolioList: {
    path: '/api/portfolios',
    method: 'GET' as const,
    description: 'List all portfolios for the current user',
    requestShape: {
      limit: 'number', // optional
      offset: 'number', // optional
      search: 'string' // optional
    },
    responseShape: {
      success: 'boolean',
      portfolios: 'array',
      total_count: 'number',
      has_more: 'boolean'
    }
  },
  
  portfolioGet: {
    path: '/api/portfolios/{id}',
    method: 'GET' as const,
    description: 'Get a specific portfolio by ID',
    requestShape: {
      include_holdings: 'boolean' // optional
    },
    responseShape: {
      success: 'boolean',
      portfolio: 'object'
    }
  },
  
  portfolioUpdate: {
    path: '/api/portfolios/{id}',
    method: 'PUT' as const,
    description: 'Update an existing portfolio',
    requestShape: {
      name: 'string', // optional
      description: 'string', // optional
      risk_profile: 'string' // optional
    },
    responseShape: {
      success: 'boolean',
      portfolio: 'object',
      updated_at: 'string'
    }
  },
  
  portfolioDelete: {
    path: '/api/portfolios/{id}',
    method: 'DELETE' as const,
    description: 'Delete a portfolio',
    requestShape: {},
    responseShape: {
      success: 'boolean',
      portfolio_id: 'string',
      deleted_at: 'string'
    }
  }
}
```

### Step 2: Service Class (All CRUD Methods)
**Location**: `frontend/src/chassis/services/PortfolioCrudService.ts`

```typescript
import { APIService } from './APIService';
import { apiRegistry } from '../../apiRegistry';

/**
 * Portfolio CRUD service - handles all portfolio lifecycle operations
 * Maintains proper user isolation through APIService base class
 */
export class PortfolioCrudService extends APIService {
  
  /**
   * Create a new portfolio
   * PLACEHOLDER: Returns mock data but maintains service architecture
   */
  async createPortfolio(portfolioData: {
    name: string;
    description?: string;
    initial_holdings?: any[];
    risk_profile?: string;
  }) {
    // TODO: Replace with real API call when backend ready
    // return this.request({
    //   url: apiRegistry.portfolioCreate.path,
    //   method: apiRegistry.portfolioCreate.method,
    //   data: portfolioData
    // });
    
    // PLACEHOLDER: Simulate creation delay and return mock data
    await new Promise(resolve => setTimeout(resolve, 800));
    
    const mockPortfolio = {
      id: `mock_portfolio_${Date.now()}`,
      name: portfolioData.name,
      description: portfolioData.description || '',
      risk_profile: portfolioData.risk_profile || 'moderate',
      initial_holdings: portfolioData.initial_holdings || [],
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      user_id: this.userId, // Service knows current user
      total_value: 0,
      holding_count: portfolioData.initial_holdings?.length || 0
    };
    
    return {
      data: {
        success: true,
        portfolio_id: mockPortfolio.id,
        portfolio: mockPortfolio,
        created_at: mockPortfolio.created_at
      }
    };
  }
  
  /**
   * List all portfolios for current user
   */
  async listPortfolios(options: {
    limit?: number;
    offset?: number;
    search?: string;
  } = {}) {
    // TODO: Replace with real API call
    // return this.request({
    //   url: apiRegistry.portfolioList.path,
    //   method: apiRegistry.portfolioList.method,
    //   params: options
    // });
    
    // PLACEHOLDER: Mock portfolio list
    await new Promise(resolve => setTimeout(resolve, 600));
    
    const mockPortfolios = [
      {
        id: 'mock_portfolio_1',
        name: 'Growth Portfolio',
        description: 'High growth stocks',
        risk_profile: 'aggressive',
        created_at: '2024-01-01T00:00:00Z',
        total_value: 125000,
        holding_count: 15
      },
      {
        id: 'mock_portfolio_2',
        name: 'Conservative Portfolio',
        description: 'Stable dividend stocks',
        risk_profile: 'conservative',
        created_at: '2024-01-15T00:00:00Z',
        total_value: 75000,
        holding_count: 8
      }
    ];
    
    // Apply search filter if provided
    const filteredPortfolios = options.search 
      ? mockPortfolios.filter(p => 
          p.name.toLowerCase().includes(options.search!.toLowerCase()) ||
          p.description.toLowerCase().includes(options.search!.toLowerCase())
        )
      : mockPortfolios;
    
    // Apply pagination
    const startIndex = options.offset || 0;
    const limit = options.limit || 50;
    const paginatedPortfolios = filteredPortfolios.slice(startIndex, startIndex + limit);
    
    return {
      data: {
        success: true,
        portfolios: paginatedPortfolios,
        total_count: filteredPortfolios.length,
        has_more: (startIndex + limit) < filteredPortfolios.length
      }
    };
  }
  
  /**
   * Get a specific portfolio by ID
   */
  async getPortfolio(portfolioId: string, options: {
    include_holdings?: boolean;
  } = {}) {
    // TODO: Replace with real API call
    // return this.request({
    //   url: apiRegistry.portfolioGet.path.replace('{id}', portfolioId),
    //   method: apiRegistry.portfolioGet.method,
    //   params: options
    // });
    
    // PLACEHOLDER: Mock portfolio details
    await new Promise(resolve => setTimeout(resolve, 400));
    
    const mockPortfolio = {
      id: portfolioId,
      name: 'Growth Portfolio',
      description: 'High growth technology stocks',
      risk_profile: 'aggressive',
      created_at: '2024-01-01T00:00:00Z',
      updated_at: new Date().toISOString(),
      user_id: this.userId,
      total_value: 125000,
      holding_count: 15,
      holdings: options.include_holdings ? [
        { ticker: 'AAPL', shares: 100, value: 15000 },
        { ticker: 'MSFT', shares: 50, value: 12000 },
        // ... more holdings
      ] : undefined
    };
    
    return {
      data: {
        success: true,
        portfolio: mockPortfolio
      }
    };
  }
  
  /**
   * Update an existing portfolio
   */
  async updatePortfolio(portfolioId: string, updates: {
    name?: string;
    description?: string;
    risk_profile?: string;
  }) {
    // TODO: Replace with real API call
    // return this.request({
    //   url: apiRegistry.portfolioUpdate.path.replace('{id}', portfolioId),
    //   method: apiRegistry.portfolioUpdate.method,
    //   data: updates
    // });
    
    // PLACEHOLDER: Mock update
    await new Promise(resolve => setTimeout(resolve, 700));
    
    const updatedPortfolio = {
      id: portfolioId,
      name: updates.name || 'Updated Portfolio',
      description: updates.description || 'Updated description',
      risk_profile: updates.risk_profile || 'moderate',
      updated_at: new Date().toISOString(),
      user_id: this.userId
    };
    
    return {
      data: {
        success: true,
        portfolio: updatedPortfolio,
        updated_at: updatedPortfolio.updated_at
      }
    };
  }
  
  /**
   * Delete a portfolio
   */
  async deletePortfolio(portfolioId: string) {
    // TODO: Replace with real API call
    // return this.request({
    //   url: apiRegistry.portfolioDelete.path.replace('{id}', portfolioId),
    //   method: apiRegistry.portfolioDelete.method
    // });
    
    // PLACEHOLDER: Mock deletion
    await new Promise(resolve => setTimeout(resolve, 500));
    
    return {
      data: {
        success: true,
        portfolio_id: portfolioId,
        deleted_at: new Date().toISOString()
      }
    };
  }
}
```

### Step 3: ServiceContainer Integration
**Location**: `frontend/src/chassis/services/ServiceContainer.ts`

```typescript
export class ServiceContainer {
  // ... existing services
  
  private _portfolioCrudService?: PortfolioCrudService;
  
  get portfolioCrud(): PortfolioCrudService {
    if (!this._portfolioCrudService) {
      this._portfolioCrudService = new PortfolioCrudService(this.config);
    }
    return this._portfolioCrudService;
  }
  
  // ... rest of container
}
```

### Step 4: Manager Methods (User-Scoped Business Logic)
**Location**: `frontend/src/chassis/managers/PortfolioManager.ts`

```typescript
export class PortfolioManager {
  // ... existing methods
  
  /**
   * CRUD Operations with caching and error handling
   */
  
  async createPortfolio(portfolioData: any) {
    try {
      this.logger.info(`Creating portfolio for user ${this.userId}:`, portfolioData.name);
      
      const result = await this.services.portfolioCrud.createPortfolio(portfolioData);
      
      if (result.data.success) {
        // Add to store
        this.store.addPortfolio(result.data.portfolio);
        
        // Cache the new portfolio
        this.cache.setPortfolio(result.data.portfolio_id, result.data.portfolio);
        
        // Invalidate portfolio list cache
        this.cache.clearPortfolioList();
        
        this.logger.info(`Portfolio created successfully: ${result.data.portfolio_id}`);
        return { data: result.data };
      } else {
        throw new Error('Portfolio creation failed');
      }
      
    } catch (error) {
      this.logger.error(`Portfolio creation error for user ${this.userId}:`, error);
      return { 
        error: error instanceof Error ? error.message : 'Unknown error',
        data: null 
      };
    }
  }
  
  async listPortfolios(options = {}) {
    try {
      // Check cache first (user-isolated)
      const cacheKey = `portfolio_list_${JSON.stringify(options)}`;
      const cached = this.cache.get(cacheKey);
      if (cached) {
        this.logger.debug(`Using cached portfolio list for user ${this.userId}`);
        return { data: cached, fromCache: true };
      }
      
      const result = await this.services.portfolioCrud.listPortfolios(options);
      
      if (result.data.success) {
        // Update store with all portfolios
        result.data.portfolios.forEach(portfolio => {
          this.store.addPortfolio(portfolio);
        });
        
        // Cache the list (user-isolated)
        this.cache.set(cacheKey, result.data, { ttl: 5 * 60 * 1000 }); // 5 minutes
        
        return { data: result.data, fromCache: false };
      } else {
        throw new Error('Failed to fetch portfolio list');
      }
      
    } catch (error) {
      this.logger.error(`Portfolio list error for user ${this.userId}:`, error);
      return { 
        error: error instanceof Error ? error.message : 'Unknown error',
        data: null 
      };
    }
  }
  
  async getPortfolio(portfolioId: string, options = {}) {
    try {
      // Check cache first
      const cached = this.cache.getPortfolio(portfolioId);
      if (cached && !options.force) {
        return { data: cached, fromCache: true };
      }
      
      const result = await this.services.portfolioCrud.getPortfolio(portfolioId, options);
      
      if (result.data.success) {
        // Update store
        this.store.addPortfolio(result.data.portfolio);
        
        // Cache the portfolio
        this.cache.setPortfolio(portfolioId, result.data.portfolio);
        
        return { data: result.data, fromCache: false };
      } else {
        throw new Error('Failed to fetch portfolio');
      }
      
    } catch (error) {
      this.logger.error(`Portfolio get error for user ${this.userId}:`, error);
      return { 
        error: error instanceof Error ? error.message : 'Unknown error',
        data: null 
      };
    }
  }
  
  async updatePortfolio(portfolioId: string, updates: any) {
    try {
      const result = await this.services.portfolioCrud.updatePortfolio(portfolioId, updates);
      
      if (result.data.success) {
        // Update store
        this.store.updatePortfolio(portfolioId, result.data.portfolio);
        
        // Update cache
        this.cache.setPortfolio(portfolioId, result.data.portfolio);
        
        // Clear list cache to force refresh
        this.cache.clearPortfolioList();
        
        this.logger.info(`Portfolio updated successfully: ${portfolioId}`);
        return { data: result.data };
      } else {
        throw new Error('Portfolio update failed');
      }
      
    } catch (error) {
      this.logger.error(`Portfolio update error for user ${this.userId}:`, error);
      return { 
        error: error instanceof Error ? error.message : 'Unknown error',
        data: null 
      };
    }
  }
  
  async deletePortfolio(portfolioId: string) {
    try {
      const result = await this.services.portfolioCrud.deletePortfolio(portfolioId);
      
      if (result.data.success) {
        // Remove from store
        this.store.removePortfolio(portfolioId);
        
        // Clear all related cache
        this.cache.clearPortfolio(portfolioId);
        this.cache.clearPortfolioList();
        
        this.logger.info(`Portfolio deleted successfully: ${portfolioId}`);
        return { data: result.data };
      } else {
        throw new Error('Portfolio deletion failed');
      }
      
    } catch (error) {
      this.logger.error(`Portfolio deletion error for user ${this.userId}:`, error);
      return { 
        error: error instanceof Error ? error.message : 'Unknown error',
        data: null 
      };
    }
  }
}
```

### Step 5: Cache Methods (User Isolation Critical)
**Location**: `frontend/src/chassis/services/PortfolioCacheService.ts`

```typescript
export class PortfolioCacheService {
  // ... existing cache methods
  
  /**
   * Portfolio CRUD cache methods - all user isolated
   */
  
  getPortfolio(portfolioId: string) {
    return this.cache.get(`portfolio:${portfolioId}`);
  }
  
  setPortfolio(portfolioId: string, portfolio: any) {
    this.cache.set(`portfolio:${portfolioId}`, portfolio, {
      ttl: 30 * 60 * 1000 // 30 minutes
    });
  }
  
  clearPortfolio(portfolioId: string) {
    this.cache.delete(`portfolio:${portfolioId}`);
  }
  
  getPortfolioList(cacheKey?: string) {
    const key = cacheKey || 'portfolio_list_default';
    return this.cache.get(key);
  }
  
  setPortfolioList(portfolios: any[], cacheKey?: string) {
    const key = cacheKey || 'portfolio_list_default';
    this.cache.set(key, portfolios, {
      ttl: 10 * 60 * 1000 // 10 minutes
    });
  }
  
  clearPortfolioList() {
    // Clear all portfolio list variations for current user
    this.clearByPattern('portfolio_list_*');
  }
  
  clearAllPortfolioCache() {
    // Clear all portfolio-related cache for current user
    this.clearByPattern('portfolio:*');
    this.clearByPattern('portfolio_list_*');
  }
}
```

### Step 6: React Hooks (Separate by Usage Pattern)

**Location**: `frontend/src/features/portfolio/hooks/usePortfolioList.ts`

```typescript
import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';
import { useSessionServices } from '../../../providers/SessionServicesProvider';
import { frontendLogger } from '../../../services/frontendLogger';
import { portfolioListKey } from '../../../queryKeys';

/**
 * Hook for listing portfolios with search and pagination
 */
export const usePortfolioList = (options: {
  search?: string;
  limit?: number;
  offset?: number;
} = {}) => {
  const { manager } = useSessionServices();
  
  const {
    data,
    isLoading,
    error,
    refetch,
    isRefetching,
  } = useQuery({
    queryKey: portfolioListKey(options),
    queryFn: async () => {
      frontendLogger.adapter.transformStart('usePortfolioList', { 
        userId: manager.userId,
        options
      });
      
      const result = await manager.listPortfolios(options);
      
      if (result.error) {
        throw new Error(result.error);
      }
      
      frontendLogger.adapter.transformSuccess('usePortfolioList', {
        count: result.data.portfolios.length,
        fromCache: result.fromCache,
        userId: manager.userId
      });
      
      return result.data;
    },
    enabled: !!manager,
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
  
  return useMemo(() => ({
    // Data
    portfolios: data?.portfolios || [],
    totalCount: data?.total_count || 0,
    hasMore: data?.has_more || false,
    
    // States
    isLoading,
    isRefetching,
    error: error?.message || null,
    
    // Actions
    refetch,
    
    // Computed
    hasData: !!data && data.portfolios.length > 0,
    hasError: !!error,
    isEmpty: !!data && data.portfolios.length === 0,
    
    // Debug
    isPlaceholder: true, // Using mock data
    currentUser: manager?.userId,
  }), [data, isLoading, isRefetching, error, refetch, manager]);
};
```

**Location**: `frontend/src/features/portfolio/hooks/usePortfolioCrud.ts`

```typescript
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useSessionServices } from '../../../providers/SessionServicesProvider';
import { frontendLogger } from '../../../services/frontendLogger';
import { portfolioListKey, portfolioKey } from '../../../queryKeys';

/**
 * Hook for portfolio CRUD mutations (Create, Update, Delete)
 */
export const usePortfolioCrud = () => {
  const { manager } = useSessionServices();
  const queryClient = useQueryClient();
  
  const createMutation = useMutation({
    mutationFn: async (portfolioData: {
      name: string;
      description?: string;
      risk_profile?: string;
      initial_holdings?: any[];
    }) => {
      frontendLogger.user.action('createPortfolio', 'usePortfolioCrud', {
        name: portfolioData.name,
        userId: manager.userId
      });
      
      const result = await manager.createPortfolio(portfolioData);
      
      if (result.error) {
        throw new Error(result.error);
      }
      
      return result.data;
    },
    onSuccess: (data) => {
      // Invalidate and refetch portfolio list
      queryClient.invalidateQueries({ queryKey: portfolioListKey() });
      
      // Set the new portfolio in cache
      queryClient.setQueryData(
        portfolioKey(data.portfolio_id), 
        { success: true, portfolio: data.portfolio }
      );
      
      frontendLogger.user.action('createPortfolioSuccess', 'usePortfolioCrud', {
        portfolioId: data.portfolio_id
      });
    },
    onError: (error) => {
      frontendLogger.error('Portfolio creation failed', 'usePortfolioCrud', error);
    }
  });
  
  const updateMutation = useMutation({
    mutationFn: async ({ portfolioId, updates }: {
      portfolioId: string;
      updates: any;
    }) => {
      frontendLogger.user.action('updatePortfolio', 'usePortfolioCrud', {
        portfolioId,
        userId: manager.userId
      });
      
      const result = await manager.updatePortfolio(portfolioId, updates);
      
      if (result.error) {
        throw new Error(result.error);
      }
      
      return result.data;
    },
    onSuccess: (data, variables) => {
      // Invalidate list and specific portfolio queries
      queryClient.invalidateQueries({ queryKey: portfolioListKey() });
      queryClient.invalidateQueries({ queryKey: portfolioKey(variables.portfolioId) });
      
      frontendLogger.user.action('updatePortfolioSuccess', 'usePortfolioCrud', {
        portfolioId: variables.portfolioId
      });
    },
    onError: (error) => {
      frontendLogger.error('Portfolio update failed', 'usePortfolioCrud', error);
    }
  });
  
  const deleteMutation = useMutation({
    mutationFn: async (portfolioId: string) => {
      frontendLogger.user.action('deletePortfolio', 'usePortfolioCrud', {
        portfolioId,
        userId: manager.userId
      });
      
      const result = await manager.deletePortfolio(portfolioId);
      
      if (result.error) {
        throw new Error(result.error);
      }
      
      return result.data;
    },
    onSuccess: (data, portfolioId) => {
      // Remove from all relevant queries
      queryClient.invalidateQueries({ queryKey: portfolioListKey() });
      queryClient.removeQueries({ queryKey: portfolioKey(portfolioId) });
      
      frontendLogger.user.action('deletePortfolioSuccess', 'usePortfolioCrud', {
        portfolioId
      });
    },
    onError: (error) => {
      frontendLogger.error('Portfolio deletion failed', 'usePortfolioCrud', error);
    }
  });
  
  return {
    // Create
    createPortfolio: createMutation.mutate,
    isCreating: createMutation.isPending,
    createError: createMutation.error?.message,
    
    // Update
    updatePortfolio: updateMutation.mutate,
    isUpdating: updateMutation.isPending,
    updateError: updateMutation.error?.message,
    
    // Delete
    deletePortfolio: deleteMutation.mutate,
    isDeleting: deleteMutation.isPending,
    deleteError: deleteMutation.error?.message,
    
    // Overall state
    isLoading: createMutation.isPending || updateMutation.isPending || deleteMutation.isPending,
    
    // Debug
    currentUser: manager?.userId,
  };
};
```

### Step 7: Query Keys
**Location**: `frontend/src/queryKeys.ts`

```typescript
// Add portfolio CRUD query keys
export const portfolioListKey = (options?: any) => 
  ['portfolios', 'list', options] as const;

export const portfolioKey = (portfolioId?: string) => 
  ['portfolios', portfolioId] as const;
```

### Step 8: Feature Exports
**Location**: `frontend/src/features/portfolio/index.ts`

```typescript
// Portfolio feature exports
export { usePortfolio } from './hooks/usePortfolio';
export { usePortfolioAnalysis } from './hooks/usePortfolioAnalysis';
export { usePortfolioSummary } from './hooks/usePortfolioSummary';
export { usePortfolioFlow } from './hooks/usePortfolioFlow';

// CRUD operations
export { usePortfolioList } from './hooks/usePortfolioList';
export { usePortfolioCrud } from './hooks/usePortfolioCrud';

// Formatters
export { formatForHoldingsView } from './formatters/formatForHoldingsView.js';
```

---

## Usage Examples

### Component Usage
```typescript
import { usePortfolioList, usePortfolioCrud } from '@/features/portfolio';

const PortfolioManagerComponent = () => {
  const { 
    portfolios, 
    isLoading, 
    refetch,
    isPlaceholder 
  } = usePortfolioList({ search: searchTerm });
  
  const { 
    createPortfolio, 
    updatePortfolio, 
    deletePortfolio,
    isCreating,
    isDeleting 
  } = usePortfolioCrud();
  
  const handleCreate = (data) => {
    createPortfolio({
      name: data.name,
      description: data.description,
      risk_profile: data.riskProfile
    });
  };
  
  return (
    <div>
      {isPlaceholder && (
        <Alert>🚧 Using mock data - Backend not connected</Alert>
      )}
      
      <CreatePortfolioForm 
        onSubmit={handleCreate} 
        isLoading={isCreating} 
      />
      
      <PortfolioList 
        portfolios={portfolios}
        isLoading={isLoading}
        onUpdate={updatePortfolio}
        onDelete={deletePortfolio}
        isDeleting={isDeleting}
      />
    </div>
  );
};
```

---

## Phase 2: Backend Integration

When the backend CRUD APIs are ready, simply replace the service implementations:

```typescript
// In PortfolioCrudService.ts, replace each method:

async createPortfolio(portfolioData: any) {
  // Replace this:
  // await new Promise(resolve => setTimeout(resolve, 800));
  // return { data: { /* mock data */ } };
  
  // With this:
  return this.request({
    url: apiRegistry.portfolioCreate.path,
    method: apiRegistry.portfolioCreate.method,
    data: portfolioData
  });
}
```

**Everything else continues to work unchanged!**

---

## Benefits of This CRUD Pattern

✅ **Complete user isolation** at all layers  
✅ **Grouped related operations** in logical service classes  
✅ **Flexible hook composition** (list vs mutations)  
✅ **Comprehensive caching** with proper invalidation  
✅ **Production-ready error handling**  
✅ **Easy backend migration** when APIs are ready  
✅ **Immediate UI development** with realistic mock data  

This pattern can be adapted for any CRUD domain: users, settings, reports, etc.