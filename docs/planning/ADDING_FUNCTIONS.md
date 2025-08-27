Recommended path for adding the missing Portfolio-CRUD features
===============================================================

Think “bottom-up, then surface up”—wire the plumbing first, then expose it through hooks/UI.  That way each layer is testable in isolation and the UI work becomes mostly wiring and styling.

Step-by-step

1. Backend contract confirmation  
   • Make sure each endpoint (`GET /api/portfolios`, `POST /api/portfolios`, `PUT`, `DELETE`, etc.) is documented in `openapi.yaml` / `API_REFERENCE.md`.  
   • Regenerate the TS types (`openapi-typescript`) so the frontend has compile-time models.

2. Service layer (Modular service with dependency injection)  
   • Create `frontend/src/chassis/services/PortfolioCrudService.ts` using the modular service pattern:  
     ```ts
     import { PortfoliosListResponse, PortfolioCreateRequest } from '../../types/api';
     
     export interface PortfolioCrudServiceOptions {
       baseURL: string;
       request: <T>(endpoint: string, options?: RequestInit) => Promise<T>;
     }
     
     export class PortfolioCrudService {
       constructor(private options: PortfolioCrudServiceOptions) {}
       
       async listPortfolios(): Promise<PortfoliosListResponse> {
         return this.options.request<PortfoliosListResponse>('/api/portfolios', {
           method: 'GET'
         });
       }
       
       async createPortfolio(body: PortfolioCreateRequest): Promise<any> {
         return this.options.request('/api/portfolios', {
           method: 'POST',
           body: JSON.stringify(body)
         });
       }
       
       async updatePortfolio(name: string, body: any): Promise<any> {
         return this.options.request(`/api/portfolios/${name}`, {
           method: 'PUT',
           body: JSON.stringify(body)
         });
       }
       
       async deletePortfolio(name: string): Promise<{ success: boolean }> {
         return this.options.request(`/api/portfolios/${name}`, {
           method: 'DELETE'
         });
       }
     }
     ```  
     Uses dependency injection pattern - auth/headers/retry handled by injected `request` method.

2.5. ServiceContainer integration  
   • Add the service to `frontend/src/chassis/services/ServiceContainer.ts`:  
     ```ts
     import { PortfolioCrudService, PortfolioCrudServiceOptions } from './PortfolioCrudService';
     
     export class ServiceContainer {
       // ... existing services
       
       private _portfolioCrudService?: PortfolioCrudService;
       
       get portfolioCrudService(): PortfolioCrudService {
         if (!this._portfolioCrudService) {
           const serviceOptions: PortfolioCrudServiceOptions = {
             baseURL: this.apiService.baseURL,
             request: this.apiService.request.bind(this.apiService)
           };
           this._portfolioCrudService = new PortfolioCrudService(serviceOptions);
         }
         return this._portfolioCrudService;
       }
     }
     ```  
     Follows existing ServiceContainer pattern for dependency injection and service lifecycle management.

3. Manager layer  
   • Add wrapper methods in `PortfolioManager` that use the service via ServiceContainer:  
     ```ts
     // Add to PortfolioManager constructor or initialize method
     private serviceContainer: ServiceContainer;
     
     async fetchPortfolioList(): Promise<{ portfolios: any[] | null; error: string | null }> {
       try {
         const portfolios = await this.serviceContainer.portfolioCrudService.listPortfolios();
         // Update store via PortfolioRepository for each portfolio
         portfolios.portfolios?.forEach(portfolio => {
           PortfolioRepository.add(portfolio);
         });
         return { portfolios: portfolios.portfolios || [], error: null };
       } catch (error) {
         return { portfolios: null, error: error.message };
       }
     }
     
     async savePortfolioEdits(id: string, updates: any): Promise<{ success: boolean; error: string | null }> {
       try {
         const portfolioName = PortfolioRepository.getName(id);
         if (!portfolioName) throw new Error('Portfolio not found');
         
         // Optimistic update via repository
         PortfolioRepository.updatePortfolio(id, updates);
         
         // Sync with backend
         await this.serviceContainer.portfolioCrudService.updatePortfolio(portfolioName, updates);
         return { success: true, error: null };
       } catch (error) {
         return { success: false, error: error.message };
       }
     }
     
     async deletePortfolio(id: string): Promise<{ success: boolean; error: string | null }> {
       try {
         const portfolioName = PortfolioRepository.getName(id);
         if (!portfolioName) throw new Error('Portfolio not found');
         
         await this.serviceContainer.portfolioCrudService.deletePortfolio(portfolioName);
         PortfolioRepository.removePortfolio(id);
         this.portfolioCacheService.clearPortfolio(id);
         return { success: true, error: null };
       } catch (error) {
         return { success: false, error: error.message };
       }
     }
     
     async createPortfolioFromTemplate(template: any): Promise<{ portfolioId: string | null; error: string | null }> {
       try {
         const result = await this.serviceContainer.portfolioCrudService.createPortfolio(template);
         const portfolioId = PortfolioRepository.add(result);
         return { portfolioId, error: null };
       } catch (error) {
         return { portfolioId: null, error: error.message };
       }
     }
     ```  
   • Keep them thin; they orchestrate service calls, repository mutations, and cache clearing.

4. Repository / store updates  
   • `addPortfolio`, `updatePortfolio`, `removePortfolio` already exist. You might add convenience helpers in the repository so managers don’t touch the store directly.

5. Cache integration  
   • On `deletePortfolio` call `PortfolioCacheService.clearPortfolio(id)` to free memory.  
   • On `savePortfolioEdits` the manager should route through `store.updatePortfolio` so the `contentVersion` bump automatically invalidates cache.

6. Hook layer  
   • `usePortfolioList` – TanStack Query hook with adapter transformation:  
     ```ts
     import { useQuery } from '@tanstack/react-query';
     import { useSessionServices } from '../../../providers/SessionServicesProvider';
     import { PortfolioListAdapter } from '../../../adapters/PortfolioListAdapter';
     import { AdapterRegistry } from '../../../utils/AdapterRegistry';
     import { HOOK_QUERY_CONFIG } from '../../../config/queryConfig';
     import { portfolioListKey } from '../../../queryKeys';
     
     export const usePortfolioList = () => {
       const { manager } = useSessionServices();
       const portfolioListAdapter = AdapterRegistry.getAdapter(PortfolioListAdapter, 'global');
       
       return useQuery({
         queryKey: portfolioListKey(),
         queryFn: async () => {
           const result = await manager.fetchPortfolioList();
           if (result.error) throw new Error(result.error);
           return portfolioListAdapter.transform(result.portfolios);
         },
         staleTime: HOOK_QUERY_CONFIG.usePortfolioList.staleTime,
         retry: (failureCount, error) => failureCount < 2
       });
     };
     ```  
   • `usePortfolioMutation` – TanStack Query mutations for CRUD operations:  
     ```ts
     import { useMutation, useQueryClient } from '@tanstack/react-query';
     import { useSessionServices } from '../../../providers/SessionServicesProvider';
     import { portfolioListKey } from '../../../queryKeys';
     
     export const usePortfolioMutation = () => {
       const { manager } = useSessionServices();
       const queryClient = useQueryClient();
       
       const createMutation = useMutation({
         mutationFn: (template: any) => manager.createPortfolioFromTemplate(template),
         onSuccess: () => {
           queryClient.invalidateQueries({ queryKey: portfolioListKey() });
         }
       });
       
       const updateMutation = useMutation({
         mutationFn: ({ id, updates }: { id: string; updates: any }) => 
           manager.savePortfolioEdits(id, updates),
         onSuccess: () => {
           queryClient.invalidateQueries({ queryKey: portfolioListKey() });
         }
       });
       
       const deleteMutation = useMutation({
         mutationFn: (id: string) => manager.deletePortfolio(id),
         onSuccess: () => {
           queryClient.invalidateQueries({ queryKey: portfolioListKey() });
         }
       });
       
       return {
         createPortfolio: createMutation.mutate,
         updatePortfolio: updateMutation.mutate,
         deletePortfolio: deleteMutation.mutate,
         isCreating: createMutation.isPending,
         isUpdating: updateMutation.isPending,
         isDeleting: deleteMutation.isPending
       };
     };
     ```

7. UI layer  
   • Start minimal: a sidebar or modal that lists portfolios, lets you click “+ New”, “Rename”, “Delete”.  
   • Use the hooks; you shouldn’t need to import managers or stores directly in components.

8. Testing  
   • Unit-test the manager methods with mocked service responses.  
   • Cypress / Playwright flow: create → edit → delete; page reload; list matches backend.

Why bottom-up first?

• Each lower layer is easier to test without UI noise.  
• Once service & manager are solid, you can prototype multiple UIs (sidebar, dropdown, dedicated page) without touching business logic.  
• Error handling (409 duplicate name, 400 validation) gets codified in one place (manager/hook), not sprinkled across components.

Implementation order quick list

1. Extend/confirm OpenAPI spec ➜ regenerate TS types  
2. Create `PortfolioCrudService` with dependency injection pattern  
2.5. Add service to `ServiceContainer` for dependency injection  
3. Extend `PortfolioManager` with CRUD methods using ServiceContainer  
4. Update repository/store interactions + cache calls  
5. Write hooks (`usePortfolioList`, `usePortfolioMutation`) with TanStack Query + Adapters  
6. Build simple UI (list + buttons) using hooks  
7. Tests & docs

Follow this path and CRUD flows will slot neatly into the existing layered architecture without spaghetti.