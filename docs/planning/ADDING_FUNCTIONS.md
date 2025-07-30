Recommended path for adding the missing Portfolio-CRUD features
===============================================================

Think “bottom-up, then surface up”—wire the plumbing first, then expose it through hooks/UI.  That way each layer is testable in isolation and the UI work becomes mostly wiring and styling.

Step-by-step

1. Backend contract confirmation  
   • Make sure each endpoint (`GET /api/portfolios`, `POST /api/portfolios`, `PUT`, `DELETE`, etc.) is documented in `openapi.yaml` / `API_REFERENCE.md`.  
   • Regenerate the TS types (`openapi-typescript`) so the frontend has compile-time models.

2. Service layer (API client)  
   • In `frontend/src/chassis/services/RiskAnalysisService.ts`’s sibling file (`PortfolioCrudService.ts` or extend `APIService`):  
     ```ts
     listPortfolios(): Promise<ListResponse>
     createPortfolio(body): Promise<PortfolioResponse>
     updatePortfolio(name, body): Promise<PortfolioResponse>
     deletePortfolio(name): Promise<{ success: boolean }>
     ```  
     All methods call `this.request()` from `APIService`, so auth/headers/retry are already handled.

3. Manager layer  
   • Add wrapper methods in `PortfolioManager`:  
     ```ts
     fetchPortfolioList()            // calls service → updates store.byId
     savePortfolioEdits(id, updates) // optimistic store update, then service.update
     deletePortfolio(id)             // service.delete → store.remove
     createPortfolioFromTemplate()   // service.create → store.add
     ```  
   • Keep them thin; they orchestrate store mutations and cache clearing, nothing else.

4. Repository / store updates  
   • `addPortfolio`, `updatePortfolio`, `removePortfolio` already exist. You might add convenience helpers in the repository so managers don’t touch the store directly.

5. Cache integration  
   • On `deletePortfolio` call `PortfolioCacheService.clearPortfolio(id)` to free memory.  
   • On `savePortfolioEdits` the manager should route through `store.updatePortfolio` so the `contentVersion` bump automatically invalidates cache.

6. Hook layer  
   • `usePortfolioList` – wraps React-Query; queryFn → `manager.fetchPortfolioList()`.  
   • `usePortfolioMutation` – custom hook returning `create / update / delete` functions that call manager methods and show toaster notifications.

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
2. Add `PortfolioCrudService` methods  
3. Extend `PortfolioManager`  
4. Update repository/store interactions + cache calls  
5. Write hooks (`usePortfolioList`, `usePortfolioMutations`)  
6. Build simple UI (list + buttons)  
7. Tests & docs

Follow this path and CRUD flows will slot neatly into the existing layered architecture without spaghetti.