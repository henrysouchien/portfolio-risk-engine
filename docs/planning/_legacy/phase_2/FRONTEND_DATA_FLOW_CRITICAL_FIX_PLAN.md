# Frontend Data Flow: Critical Fix Plan & Implementation Approach

## Executive Summary

This document outlines a systematic plan to address the critical data flow issues identified in the recent frontend audit. The goal is to ensure robust data integrity, cache coherence, and maintainability by enforcing single-writer patterns, preventing store bypass, and aligning cache policies.

---

## Critical Issues & Action Plan

### 1. Consolidate Portfolio Writers (Single Writer Pattern)

**Goal:**
Ensure all portfolio data mutations go through a single, authoritative abstraction (the repository), preventing race conditions and data corruption.

**Steps:**
1. **Audit all portfolio mutations:**
   - Search for all code that mutates portfolio data (e.g., `portfolioStore`, `PortfolioCacheService`, direct state updates).
   - List every function, service, or component that writes to portfolio data.
2. **Enforce repository-only writes:**
   - Refactor so that only the `PortfolioRepository` is allowed to mutate portfolio data.
   - Remove or refactor any direct writes to the store or cache service.
   - If other services need to update data, have them call the repository’s mutation methods.
3. **Add TypeScript types and comments:**
   - Mark all mutation methods in the repository as the only allowed entry points for portfolio writes.
   - Add comments to the store and cache service: “Do not mutate state directly—use PortfolioRepository.”
4. **Test:**
   - Add/expand tests to ensure all mutations go through the repository and that data integrity is maintained.

---

### 2. Prevent Store Bypass in Repository Pattern

**Goal:**
Guarantee that all mutations (add, update, delete) are routed through the repository abstraction.

**Steps:**
1. **Lock down store and cache service APIs:**
   - Make mutation methods in the store and cache service private/internal if possible.
   - Only expose read/select methods publicly.
2. **Code review and static analysis:**
   - Use code review or static analysis tools to flag any direct store/cache mutations outside the repository.
3. **Documentation:**
   - Update developer docs to clarify the repository is the single source of truth for mutations.

---

### 3. Align Cache TTLs Across Layers

**Goal:**
Prevent stale data by ensuring all cache layers (React Query, AdapterRegistry, PortfolioCacheService) expire and refresh data on the same schedule.

**Steps:**
1. **Inventory all cache layers and their TTLs:**
   - List the current TTLs for React Query, AdapterRegistry, PortfolioCacheService, etc.
2. **Decide on a unified cache policy:**
   - Choose a standard TTL (e.g., 5 minutes) that balances freshness and performance.
3. **Update all cache configurations:**
   - Set the same TTL in all relevant places.
   - If some caches need to be longer-lived, document why and ensure they are invalidated on relevant data changes.
4. **Test:**
   - Simulate data changes and verify that all caches expire and refresh as expected.

---

### 4. (Optional, but Highly Recommended) Implement a Data Access Layer

**Goal:**
Break circular dependencies and clarify data flow by introducing a clear abstraction between services, repositories, and stores.

**Steps:**
1. **Design a data access interface:**
   - Define clear interfaces for reading and writing portfolio data.
   - Ensure services and stores depend on the interface, not each other.
2. **Refactor dependencies:**
   - Update services and stores to use the new data access layer.
   - Remove any direct references between repositories, stores, and services.
3. **Test and document:**
   - Ensure all data flows are routed through the new layer.
   - Update architecture docs to reflect the new pattern.

---

## General Best Practices

- **Incremental Refactoring:** Start with the most critical flows (e.g., portfolio mutations), then expand.
- **Automated Tests:** Add/expand tests for data integrity, cache invalidation, and cross-tab consistency.
- **Code Reviews:** Enforce these patterns in code review to prevent regressions.
- **Documentation:** Update onboarding and architecture docs to reflect the new, safer data flow.

---

## Suggested Order of Attack

1. **Consolidate writers and prevent store bypass** (these are tightly linked).
2. **Align cache TTLs** (can be done in parallel).
3. **(Optional) Implement data access layer** (for long-term maintainability).

---

## Next Steps

- Assign owners for each critical area.
- Schedule incremental implementation and code review sessions.
- Track progress and update this document as fixes are completed.