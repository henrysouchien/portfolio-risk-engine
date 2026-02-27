# Portfolio Data Access Layer (DAL) Refactor Plan

## Rationale

Introducing a Portfolio Data Access Layer (DAL) will:
- Centralize all portfolio data access and mutation logic
- Decouple components, hooks, services, and managers from direct store/repository access
- Improve maintainability, testability, and future-proofing
- Enforce session/user scoping and consistent data handling
- **Guarantee user/session isolation:** The DAL must always delegate to user/session-scoped stores or repositories, leveraging the existing `SessionServicesProvider` and provider hierarchy. This ensures no data mixing between users or sessions.
- **Provide a unified, session-scoped facade:** The DAL wraps and delegates to internal services (PortfolioManager, PortfolioCacheService, PortfolioRepository), exposing a single interface for all portfolio data access.

## Scope

- **In Scope:**
  - All frontend code that reads from or writes to portfolio data (store, repository, cache, etc.)
  - Portfolio-related hooks, services, managers, and tests
  - Documentation for portfolio data access
- **Out of Scope:**
  - Other domains (auth, user preferences, etc.)
  - Underlying store/repository implementation (unless needed for DAL interface)
  - Unrelated features/components

## Step-by-Step Implementation Plan

### 1. Design the DAL Interface
- Define a TypeScript interface (e.g., `PortfolioDAL`) with all required portfolio data operations:
  - `getPortfolioById(id: string): Portfolio | null`
  - `getAllPortfolios(): Portfolio[]`
  - `addPortfolio(portfolio: Portfolio): void`
  - `updatePortfolio(id: string, updates: Partial<Portfolio>): void`
  - `setRiskAnalysis(id: string, analysis: RiskAnalysis | null): void`
  - ...add other operations as needed
- Place in `src/data/PortfolioDAL.ts`
- **Add to interface documentation:**
  - "All DAL methods must delegate to user/session-scoped services provided by SessionServicesProvider. This guarantees complete user isolation and prevents data mixing."

### 2. Implement the DAL
- Create a concrete implementation (e.g., `portfolioDAL`) that wraps the current store/repository logic.
- Place in `src/data/PortfolioDALImpl.ts`
- **Implementation Note:**
  - The DAL must always obtain its data sources (stores, repositories, services) from the current session context, as provided by `SessionServicesProvider`.
  - Never access global or non-scoped stores/services directly.
  - **The DAL acts as a unified, session-scoped facade:**
    - It wraps and delegates to internal services: `PortfolioManager`, `PortfolioCacheService`, and `PortfolioRepository`.
    - These services remain internal; only the DAL is exposed for portfolio data access.
- **Example code comment for DAL implementation:**
  ```typescript
  /**
   * DAL ARCHITECTURE:
   * - Wraps PortfolioManager, PortfolioCacheService, PortfolioRepository
   * - Provides a unified, session-scoped interface for all portfolio data operations
   * - Orchestrates calls to the correct service(s) as needed
   * - Maintains existing service contracts while centralizing access
   * - Only the DAL is exposed to the rest of the app for portfolio data access
   */
  ```
- Ensure all methods respect session/user scoping.

### 3. Refactor All Portfolio Data Access
- **Step-by-step process:**
  1. **Search for all direct portfolio data access:**
     - Use your IDE or code search tools to find all usages of `usePortfolioStore`, `PortfolioRepository`, `PortfolioManager`, `PortfolioCacheService`, etc.
  2. **Incremental refactoring:**
     - Refactor one module, feature, or hook at a time to use the DAL instead of direct store/repo/service access.
     - Example: Replace `usePortfolioStore.getState().addPortfolio(...)` with `portfolioDAL.addPortfolio(...)`
  3. **Update tests:**
     - Update or mock the DAL in all portfolio-related tests instead of the store/repo.
  4. **Code review:**
     - Review each refactored file to ensure it uses the DAL and not the old store/repo/service.
  5. **Documentation updates:**
     - Update onboarding and architecture docs to state: "All portfolio data access must go through the DAL."
  6. **Test as you go:**
     - Run your test suite after each set of changes to catch regressions early.
- **Testing Note:**
  - Add/expand tests to simulate multiple users/tabs and verify no data is mixed.

### 4. Restrict Direct Store/Repository Access (Optional)
- Mark direct store/repository mutation methods as internal or deprecated.
- Add comments to discourage direct access in favor of the DAL.

### 5. Update Documentation
- Update `ARCHITECTURE.md` and onboarding docs to explain the DAL pattern, rationale, and usage.
- **Explicitly state:**
  - "The DAL is session/user-scoped by design. All reads and writes are isolated per user session, leveraging the existing provider hierarchy."
  - "The DAL is the only public interface for portfolio data access. Internal services (PortfolioManager, PortfolioCacheService, PortfolioRepository) are not accessed directly by features, hooks, or components."
- Add code comments to DAL interface and implementation.

### 6. Test and Validate
- Run all tests to ensure nothing is broken.
- Add/expand tests for the DAL itself.
- Validate that session/user scoping is preserved.

### 7. Code Review and Team Communication
- Review all changes for consistency and correctness.
- Announce the new pattern to the team and update code review checklists.

## Affected Files (Examples)

- `src/data/PortfolioDAL.ts` (new)
- `src/data/PortfolioDALImpl.ts` (new)
- `src/features/portfolio/hooks/usePortfolioSummary.ts`
- `src/features/portfolio/hooks/useInstantAnalysis.ts`
- `src/chassis/managers/PortfolioManager.ts`
- `src/chassis/services/PortfolioCacheService.ts`
- `src/stores/portfolioStore.ts` (optional: restrict direct access)
- `src/repository/PortfolioRepository.ts` (optional: restrict direct access)
- `src/features/portfolio/__tests__/*.test.ts`
- `docs/ARCHITECTURE.md`
- `docs/DEVELOPER_ONBOARDING.md`

## Best Practices

- Refactor incrementally, validating after each major change.
- Keep the DAL interface focused and domain-specific.
- **Always delegate to user/session-scoped services via SessionServicesProvider.**
- **The DAL is the only public interface for portfolio data access.**
- Ensure all session/user scoping is preserved in the DAL implementation.
- Use TypeScript for strong typing and safety.
- Document all changes and update onboarding materials.
- Encourage all new code to use the DAL for portfolio data access.

---

**This plan will ensure a robust, maintainable, and future-proof data access architecture for portfolio features, with guaranteed user/session isolation and a clear, unified interface for all portfolio data operations.**