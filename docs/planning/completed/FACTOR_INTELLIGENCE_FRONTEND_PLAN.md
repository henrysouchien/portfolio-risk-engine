# Plan: Factor Intelligence Frontend

**Status:** NOT STARTED

**Extracted from:** `docs/planning/completed/FACTOR_INTELLIGENCE_IMPLEMENTATION_ARCHITECTURE.md` (Phases 3-5)

## Context

The Factor Intelligence backend is complete (core engine, service layer, API routes, DB migrations) and MCP tools are the primary consumer. This plan covers the web UI frontend that was originally scoped as Phases 3-5 but never built.

**Backend references:**
- `core/factor_intelligence.py` (1,580 lines)
- `services/factor_intelligence_service.py` (919 lines)
- `routes/factor_intelligence.py` (362 lines)
- `models/factor_intelligence_models.py`
- `mcp_tools/factor_intelligence.py` (MCP tools — current primary consumer)

## Phase 1: Frontend Integration (was Phase 3)
- [ ] **API Client**: TypeScript interfaces and API client methods (`FactorIntelligenceService.ts`)
- [ ] **Core Components**: Factor correlation matrix and performance profiles
- [ ] **Factor Group Builder**: UI for creating and managing factor groups
- [ ] **Integration**: Connect with existing portfolio analysis UI

## Phase 2: Advanced Features (was Phase 4)
- [ ] **Offset Recommendations**: Portfolio-aware recommendation UI
- [ ] **Data Visualization**: Interactive correlation heatmaps and charts
- [ ] **User Experience**: Form validation, loading states, error handling
- [ ] **Performance Optimization**: Caching strategies and lazy loading

## Phase 3: Testing & Polish (was Phase 5)
- [ ] **End-to-End Tests**: Complete user workflows
- [ ] **Performance Testing**: Load testing and optimization

## Notes

The original architecture doc contains detailed TypeScript code for:
- `FactorIntelligenceService.ts` — API client class
- `useFactorCorrelations` — React hook
- `FactorIntelligenceContainer` — React container component
- `FactorIntelligenceView` — React view component

See the original doc in `docs/planning/completed/FACTOR_INTELLIGENCE_IMPLEMENTATION_ARCHITECTURE.md` for full code references.
