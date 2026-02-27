# Portfolio Risk Dashboard Integration Roadmap

## Project Overview
**OBJECTIVE:** Connect existing dashboard UI → existing frontend infrastructure → existing backend APIs to create fully functional portfolio risk analysis dashboard.

**CONTEXT:** We have three complete pieces that need systematic integration:
- ✅ **Frontend Dashboard UI** - Complete RiskAnalysisDashboard.jsx with multiple views and mock data
- ✅ **Frontend Infrastructure** - PortfolioManager, APIService, ClaudeService, existing components
- ✅ **Backend APIs** - Complete Flask app with risk analysis endpoints and result objects

**GOAL:** Systematic 11-phase integration using multiple specialized AIs to connect all pieces without breaking existing functionality.

---

## 11-Phase Integration Workflow

### Phase 0: Project Coordination & Oversight 🎯
**AI SPECIALIST:** Project Manager/Technical Coordinator (Active Throughout All Phases)

**SCOPE:** Continuous oversight, quality control, and strategic guidance throughout entire integration

**ONGOING RESPONSIBILITIES:**
- Monitor progress across all phases and validate deliverables
- Maintain high-level project context and catch integration issues early
- Facilitate communication between specialized AIs and resolve conflicts
- Provide strategic guidance when phases encounter unexpected challenges
- Quality gate enforcement - validate each phase before next AI begins
- Risk management and rollback coordination if issues arise
- Maintain project documentation and ensure consistency across phases

**KEY ACTIVITIES:**
- **Pre-Phase:** Brief each new AI on project context and validate their understanding
- **During Phase:** Monitor work quality and architectural consistency
- **Post-Phase:** Validate deliverables meet requirements before handoff
- **Cross-Phase:** Identify integration risks and coordinate solutions
- **CEO Interface:** Translate technical issues to strategic decisions

**DELIVERABLE:** Continuous project oversight with phase validation reports and strategic recommendations

**SUCCESS CRITERIA:** Zero phase failures, consistent architecture, proactive issue resolution

---

### Phase 1: API & Data Discovery 📡
**AI SPECIALIST:** Data Architecture Analyst

**SCOPE:** Map all available data sources and create comprehensive data catalog

**SPECIFIC TASKS:**
- **CRITICAL SHORTCUT:** Start by analyzing `/core/result_objects.py` - All API responses come from these objects via `.to_dict()`
- Document result object structures (RiskAnalysisResult, RiskScoreResult, PerformanceResult, etc.)
- Map result object `.to_dict()` outputs to understand exact API response formats
- Catalog PortfolioManager method outputs and interfaces  
- Verify API endpoints use `result.to_dict()` pattern consistently
- Inventory existing frontend services/managers (APIService, ClaudeService, etc.)
- Map existing component data flows
- Create data availability matrix vs dashboard requirements
- Identify any data gaps or transformation needs

**DELIVERABLE:** Complete API specification document with:
- Result object documentation (RiskAnalysisResult, RiskScoreResult, etc.)
- JSON schemas derived from result object `.to_dict()` methods
- PortfolioManager interface documentation
- Data flow diagrams
- Gap analysis report

**SUCCESS CRITERIA:** Every dashboard data field has identified source

---

### Phase 1.5: Frontend Data Requirements Analysis 📊
**AI SPECIALIST:** Frontend Requirements Analyst

**SCOPE:** Extract and catalog ALL data requirements from dashboard components

**SPECIFIC TASKS:**
- Systematically analyze all mock data structures in RiskAnalysisDashboard.jsx
- Document mockPortfolioData structure, field names, and usage patterns
- Document mockFactorData structure, field names, and usage patterns
- Document mockPerformanceData structure, field names, and usage patterns
- Map every field used by each dashboard view
- Document expected data types, nesting structures, and array formats
- Identify component-specific data transformation needs
- Create comprehensive frontend data requirements specification

**DELIVERABLE:** Complete frontend data requirements catalog including:
- Field-by-field breakdown for each dashboard view
- Expected data types and structures for all fields
- Component usage patterns and data dependencies
- Data transformation requirements (calculations, formatting, etc.)
- Mock data structure documentation

**SUCCESS CRITERIA:** Complete specification of every data field expected by dashboard components

---

### Phase 2: Data Transformation Specification 🔄
**AI SPECIALIST:** Integration Architecture Designer

**SCOPE:** Design simple data format transformation layer (UI-only integration)

**CRITICAL CONSTRAINT:** Do NOT change any existing business logic, PortfolioManager methods, or backend calls. This is purely UI integration.

**SPECIFIC TASKS:**
- Create field-by-field mapping specifications (existing PortfolioManager responses → dashboard component formats)
- Design lightweight adapters that ONLY transform data shapes (no new business logic)
- Plan hooks that call existing PortfolioManager methods directly
- Keep existing React context and state management patterns
- Define simple format transformation patterns (response.data.field → dashboardFormat.field)
- Specify how to preserve existing error handling and loading states

**DELIVERABLE:** Detailed adapter specifications including:
- Transformation specifications for each view
- Interface definitions and TypeScript types
- Error handling framework design
- Hook architecture patterns

**SUCCESS CRITERIA:** Clear transformation spec for every data field

**HANDOFF REQUIREMENT:** Present mapping specification to CEO for review and validation before proceeding to implementation phases.

---

### Phase 2.5: Mapping Validation & CEO Review 👥
**PARTICIPANTS:** Phase 2 AI + CEO

**SCOPE:** Review and validate all data mapping specifications

**REVIEW PROCESS:**
1. **AI presents complete mapping document** with clear and ambiguous mappings identified
2. **CEO validates clear mappings** (expected 80% - quick approval)
3. **CEO resolves ambiguous mappings** (expected 20% - provide specific guidance)
4. **CEO decides on missing data handling** (calculate in adapter vs. modify frontend)
5. **CEO approves naming strategy** (transform field names vs. use backend names directly)
6. **Finalize approved mapping specification** for implementation phases

**DELIVERABLE:** CEO-approved complete data mapping specification

**SUCCESS CRITERIA:** Zero ambiguity in field mappings, clear direction for all implementation phases

---

### Phase 3: Adapter Implementation 🔧
**AI SPECIALIST:** Frontend Integration Developer / Adapter Engineer

**SCOPE:** Implement TypeScript adapters that transform backend API responses to frontend dashboard formats

**CRITICAL CONSTRAINT:** Follow CEO-approved mapping specifications exactly. Do NOT modify existing backend APIs or PortfolioManager business logic.

**SPECIFIC TASKS:**
- Implement TypeScript adapter classes based on Phase 2.5 approved mappings
- Create transformation functions for each Result Object → Dashboard Format conversion
- Build data adapters for each dashboard view (RiskScoreView, FactorAnalysisView, PerformanceAnalyticsView, etc.)
- Implement error handling and data validation within adapters
- Create utility functions for common transformations (percentage formatting, currency formatting, etc.)
- Write unit tests for all adapter transformation logic
- Create TypeScript interfaces for all transformed data structures
- Implement fallback handling for missing or invalid data
- Build adapter factory pattern for easy instantiation and testing
- Validate adapters work with actual API response samples

**DELIVERABLE:** Complete adapter implementation including:
- TypeScript adapter classes for each dashboard view
- Transformation utilities and helper functions
- Comprehensive unit test suite
- TypeScript interface definitions
- Error handling and validation framework
- Documentation for each adapter with usage examples
- Integration test results with sample API responses

**SUCCESS CRITERIA:** All adapters correctly transform sample backend responses to expected frontend formats, 100% test coverage on transformation logic, zero data mapping errors

### Phase 3 Prompt (Adapter Implementation):
```
You are an expert Frontend Integration Developer implementing TypeScript adapters.

CONTEXT:
- You have CEO-approved mapping specifications from Phase 2.5
- Backend APIs return Result Objects that need transformation to frontend formats
- Focus on clean, testable transformation code with zero business logic changes

YOUR TASK:
1. Implement TypeScript adapter classes for each dashboard view transformation
2. Create utility functions for common data transformations (percentages, currency, etc.)
3. Build comprehensive unit tests for all transformation logic
4. Implement error handling and data validation within adapters
5. Create TypeScript interfaces for all transformed data structures
6. Validate adapters work correctly with actual API response samples

DELIVERABLE: Complete adapter implementation with tests and documentation.

INPUT: CEO-approved mapping specs, Result Object schemas, frontend requirements
FOCUS: Clean transformation code, comprehensive testing, zero mapping errors

SUCCESS CRITERIA: All backend responses correctly transform to expected frontend formats with 100% test coverage.

IMPORTANT: Do NOT modify existing backend APIs or PortfolioManager. Only implement data shape transformations.
```



---

### Phase 4A: Component Architecture Design 🏗️
**AI SPECIALIST:** Frontend Architecture Planner

**SCOPE:** Design optimal component modularization strategy

**SPECIFIC TASKS:**
- Analyze current monolithic RiskAnalysisDashboard.jsx structure (1,836 lines)
- Design extraction plan for dashboard views into separate components
- Plan optimal folder structure and component organization
- Design imports/exports and component relationships
- Plan integration with existing App.tsx and routing (dashboard as main app)
- Design component boundaries and data flow patterns
- Plan for easy AI integration in subsequent phases

**DELIVERABLE:** Complete component architecture blueprint including:
- Detailed file structure plan
- Component extraction specifications
- Import/export mapping strategy
- Data flow design between components
- Integration plan with existing app structure

**SUCCESS CRITERIA:** Clear blueprint that enables clean modular architecture optimized for AI implementation

---

### Phase 4B: Component Extraction Implementation ✂️
**AI SPECIALIST:** Frontend Refactoring Engineer

**SCOPE:** Execute component extraction according to architecture blueprint

**SPECIFIC TASKS:**
- Implement component extraction according to Phase 3A blueprint
- Extract view components from monolithic RiskAnalysisDashboard.jsx
- Create main dashboard orchestrator component
- Implement planned folder structure and file organization
- Update all imports/exports according to architecture plan
- Maintain existing mock data usage (no data connections yet)
- Ensure extracted components render identically to original

**DELIVERABLE:** Modular component structure including:
- Extracted view components following architecture blueprint
- Main dashboard orchestrator component
- Clean folder structure implementation
- All components functional with existing mock data
- Updated import/export structure

**SUCCESS CRITERIA:** Dashboard renders and functions identically with modular components, following architecture blueprint exactly

---

### Phase 5: Data Layer Implementation ⚙️
**AI SPECIALIST:** Data Integration Engineer

**SCOPE:** Build lightweight wrapper layer using **Hook → Adapter → Manager** pattern (UI-only integration)

**CRITICAL CONSTRAINT:** Do NOT modify PortfolioManager.ts, APIService, or any backend logic. This is purely UI format transformation.

**ARCHITECTURE PATTERN:**
```
User Action → Component → Hook → Adapter → EXISTING PortfolioManager → EXISTING API
                          ↑        ↑         ↑ (unchanged)
                    React State  Format    Existing Business
                    Management   Transform  Logic (unchanged)
```

**SPECIFIC TASKS:**
- Implement lightweight adapters that call existing PortfolioManager methods and transform response formats
- Create React hooks that call adapters and use existing AppContext state management
- **STATE MANAGEMENT:** Use existing `useAppContext()` hook from `/frontend/src/chassis/context/AppContext.tsx`
- **REFERENCE EXISTING PATTERN:** Study `/frontend/src/chassis/hooks/usePortfolio.ts` for current hook patterns
- **CONTEXT INTEGRATION:** Wire to existing context setters (setCurrentPortfolio, setPortfolios, etc.)
- **MANAGER INTEGRATION:** Call existing `/frontend/src/chassis/managers/PortfolioManager.ts` methods unchanged
- Adapters ONLY transform data shapes (e.g., response.analysis.volatility → { value: volatility, label: "Portfolio Risk" })
- Keep existing error handling and loading state patterns from current app
- Create simple format transformation utilities
- Test that existing backend workflow is preserved

**DELIVERABLE:** Complete data connection layer including:
- Data adapters with transformation logic that wrap PortfolioManager calls
- React hooks that call adapters and manage React state only
- Error handling framework
- Utility functions and base classes
- Unit tests for critical transforms

**SUCCESS CRITERIA:** All adapters transform sample data correctly, hooks manage state properly using Hook → Adapter → Manager pattern

---

### Phase 6: Data Integration 🔌
**AI SPECIALIST:** Frontend Integration Engineer

**SCOPE:** Replace dashboard mock data with existing app infrastructure (UI-only integration)

**CRITICAL CONSTRAINT:** Do NOT change any business logic, state management, or backend calls. Only replace UI components.

**SPECIFIC TASKS:**
- Replace mock data in dashboard components with real hooks from Phase 5
- **STATE INTEGRATION:** Wire new dashboard components to existing AppContext using `useAppContext()` hook
- **CONTEXT USAGE:** Access `currentPortfolio`, `portfolios`, `user`, `isAuthenticated` from context
- **UI STATE:** Keep local useState for component-specific state (activeView, settings, UI controls)
- Replace dashboard mock useState with context data (e.g., mockPortfolioData → currentPortfolio)
- Ensure new components use existing loading/error state patterns from usePortfolio hook
- Test that portfolio upload/analysis workflow works identically to current app
- Verify that Plaid integration and existing features work with new UI
- Replace old app components with new dashboard components
- Preserve existing user workflow (upload → analyze → view results)

**DELIVERABLE:** Dashboard with real data connections including:
- All views using real data hooks
- Comprehensive loading/error states
- PortfolioManager integration
- Individual view testing results
- Error handling verification

**SUCCESS CRITERIA:** Each dashboard view displays real data correctly

---

### Phase 7: Advanced Features Planning 📋
**AI SPECIALIST:** Architecture Implementation Planner

**SCOPE:** Review main architectural plan and create implementation roadmap for remaining features

**SPECIFIC TASKS:**
- Review `/docs/RISK_ANALYSIS_DASHBOARD_PLAN.md` comprehensively
- Identify all unimplemented features (logging, memory management, etc.)
- Cross-reference with current dashboard implementation
- Create detailed implementation plan for each missing feature
- Prioritize features by importance and complexity
- Design integration approach that doesn't break existing functionality
- Plan testing strategy for new features

**DELIVERABLE:** Detailed implementation plan including:
- Complete feature gap analysis
- Implementation specifications for each missing feature
- Integration strategy and sequence
- Testing and validation approach
- Risk assessment and rollback plans

**SUCCESS CRITERIA:** Clear roadmap for implementing all remaining architectural features

---

### Phase 8: Advanced Features Implementation 🔧
**AI SPECIALIST:** Feature Implementation Engineer

**SCOPE:** Implement remaining architectural features and complete production integration

**SPECIFIC TASKS:**
- Wire dashboard into existing app structure and routing
- Implement prioritized features from Phase 7 plan (logging, memory management, etc.)
- Add comprehensive error handling and edge case management
- Performance optimization and testing
- Integration testing of complete user workflows
- Bug fixes and production polish
- Documentation updates

**DELIVERABLE:** Production-ready integrated dashboard including:
- Complete app integration
- All planned architectural features implemented
- Comprehensive error handling
- Performance optimizations
- End-to-end testing results
- Updated documentation

**SUCCESS CRITERIA:** Complete user workflow works flawlessly, zero regression in existing functionality, all architectural features operational

---

### Phase 9: Interface Testing & Quality Assurance 🧪
**AI SPECIALIST:** Interface Testing Engineer

**SCOPE:** Comprehensive testing of post-authentication dashboard interface

**SPECIFIC TASKS:**
- Create comprehensive test suite for all dashboard views (Risk Score, Factor Analysis, Performance, Holdings, Report, Settings)
- Test all user interactions and UI components (buttons, forms, navigation, chat panel)
- Verify Tailwind CSS styling and responsive design across different screen sizes
- Test data loading states, error handling, and edge cases
- Validate accessibility features and keyboard navigation
- Test portfolio upload/selection functionality
- Verify all charts and visualizations render correctly
- Document all discovered bugs, UI inconsistencies, and performance issues

**DELIVERABLE:** Complete test results and bug inventory including:
- Detailed test execution report for all interface components
- Comprehensive bug tracking document with severity levels
- UI/UX issue documentation with screenshots
- Performance bottleneck identification
- Accessibility audit results
- Cross-browser compatibility report

**SUCCESS CRITERIA:** All interface components thoroughly tested, all issues documented with clear reproduction steps

---

### Phase 9.5: Strategic Logging Implementation 📊
**AI SPECIALIST:** Frontend Logging Engineer

**SCOPE:** Implement comprehensive strategic logging throughout frontend for optimal debugging visibility

**SPECIFIC TASKS:**
- Audit all dashboard components for logging coverage gaps
- Add strategic log points at critical user interaction touchpoints
- Implement comprehensive user journey logging (click → API → state change → render)
- Add performance timing logs for optimization insights
- Create API call monitoring with request/response timing
- Add state change visibility for all Zustand store operations
- Implement error chain analysis logging (events leading to errors)
- Add debugging scenarios with comprehensive log coverage
- Ensure all logs use existing frontendLogger service to reach backend terminal

**DELIVERABLE:** Comprehensive logging implementation including:
- Strategic log points throughout all dashboard components
- User journey tracking with complete action chains
- Performance timing logs for bottleneck identification
- API interaction monitoring with detailed timing
- State change logging for debugging visibility
- Error context logging for root cause analysis
- Documentation of logging strategy and debug scenarios

**SUCCESS CRITERIA:** Every user action and system operation has appropriate logging, debugger AI has complete visibility into frontend operations via backend terminal

---

### Phase 10: Systematic Testing & Production Debugging 🧪
**AI SPECIALIST:** Systematic Testing & Debug Engineer

**SCOPE:** Comprehensive testing using Playwright automation with shared authentication and systematic debugging of all issues

**TESTING APPROACH:** Playwright Browser Automation with Shared Google OAuth Authentication
- **Setup:** Use shared browser profile at `/tmp/phase10-testing-profile` to inherit user's Google OAuth session
- **Capabilities:** Systematic testing of all dashboard views, interactions, and user workflows with real authentication
- **Coverage:** Complete integration testing from authentication through data analysis with real backend APIs
- **Debug Integration:** Leverage comprehensive logging from Phase 9.5 for issue identification and resolution

**SPECIFIC TASKS:**
- Set up Playwright testing environment with shared browser authentication (see PHASE10_PLAYWRIGHT_TESTING_GUIDE.md)
- Execute systematic testing of all dashboard views (Risk Score, Holdings, Performance, Factor Analysis, Report, Settings)
- Test complete user workflows: authentication → portfolio selection → data analysis → view navigation → chat integration
- Verify real API integration and data loading across all components
- Test responsive design, cross-browser compatibility, and accessibility features
- Monitor performance metrics and identify optimization opportunities
- Use comprehensive frontend logging to debug any issues discovered during testing
- Document all findings with screenshots, reproduction steps, and severity assessment
- Systematically resolve critical and high-priority issues identified during testing
- Validate fixes through automated re-testing
- Generate comprehensive test report with coverage metrics and quality assessment

**DELIVERABLE:** Complete systematic testing and debugging implementation including:
- Playwright testing framework with shared authentication setup
- Comprehensive test execution across all dashboard functionality
- Detailed bug inventory with reproduction steps and screenshots
- Systematic resolution of all critical and high-priority issues
- Performance optimization report with before/after metrics
- Final production readiness assessment
- Automated test suite for ongoing quality assurance

**SUCCESS CRITERIA:** 
- Complete dashboard functionality tested with real authentication and data
- All critical bugs resolved with automated test coverage
- Performance meets production standards with comprehensive monitoring
- User workflows function seamlessly from authentication to analysis
- Comprehensive test documentation enables ongoing quality assurance

---

### Phase 10B: Visual Polish & Comprehensive Testing 🎨
**AI SPECIALIST:** Visual Regression & Testing Engineer

**SCOPE:** Complete visual regression fixes and comprehensive testing with functionally stable dashboard

**PREREQUISITES:**
- Phase 10A has delivered functionally stable dashboard (no React errors, infinite loops resolved)
- Basic navigation and data loading working
- Playwright testing framework and shared authentication setup complete

**VISUAL REGRESSION RESTORATION:**
- **Critical Issue:** Dashboard has lost significant visual polish during integration phases
- **Root Cause:** Component extraction in Phase 4B likely dropped Tailwind CSS classes and styling
- **Required:** Restore original RiskAnalysisDashboard.jsx visual quality and design system

**SPECIFIC TASKS:**
- Compare current dashboard with original design through screenshot analysis
- Restore missing Tailwind CSS classes, colors, spacing, and visual hierarchy
- Fix component styling: card designs, backgrounds, borders, shadows, typography
- Verify design system components and styling props are properly passed down
- Validate all dashboard views match original visual quality standards
- Execute comprehensive Playwright testing with visual regression detection
- Validate complete user workflows: authentication → portfolio selection → analysis → chat integration
- Monitor performance metrics and implement optimization recommendations
- Generate final production readiness assessment with comprehensive test coverage

**DELIVERABLE:** Production-ready dashboard with restored visual quality and comprehensive testing including:
- Visual regression fixes with before/after screenshots
- Complete Playwright test suite with automated visual validation
- Comprehensive test execution report across all dashboard functionality
- Performance optimization implementation and metrics
- Final production deployment readiness assessment
- Complete user acceptance testing validation

**SUCCESS CRITERIA:**
- Dashboard visual quality matches original design standards
- All user workflows tested and functioning seamlessly
- Performance meets production standards with comprehensive monitoring
- Zero visual regressions and complete functional validation
- Production deployment ready with comprehensive test coverage

---

### Phase 10C: Critical Infrastructure Fixes Implementation 🔧
**AI SPECIALIST:** Implementation Engineer - Critical Fixes

**SCOPE:** Implement the 3 critical fixes identified in ROOT_CAUSE_ANALYSIS_AND_FIX_PROPOSALS.md to restore real data instead of hardcoded values

**CRITICAL DISCOVERY:** The debugger AI found that working infrastructure exists but was disconnected. Working hooks were replaced with hardcoded values to avoid infinite loops, but never properly reconnected.

**SPECIFIC TASKS:**
- Implement Critical Issue #1: Reconnect working `usePortfolioSummary()` hook that was commented out and replaced with hardcoded `riskScore: 87.5`
- Implement Critical Issue #3: Fix API authentication and error handling to resolve 500 errors blocking all API calls
- Implement Critical Issue #2: Create `useFactorAnalysis` hook following pattern of existing working hooks for Factor Analysis tab
- Follow ROOT_CAUSE_ANALYSIS_AND_FIX_PROPOSALS.md specifications exactly with provided code examples
- Test each fix individually to validate portfolio shows real data instead of hardcoded values
- Use existing working hook patterns (useRiskScore.ts, usePortfolioSummary.ts) as implementation templates
- Add proper error handling and authentication checks in backend routes
- Create comprehensive validation testing for each implemented fix

**DELIVERABLE:** Complete critical infrastructure fixes including:
- Working hooks reconnected with real data connections replacing hardcoded values
- API authentication and error handling fixes enabling successful backend communication
- Complete useFactorAnalysis hook implementation following working patterns
- Individual validation testing confirming each fix works correctly
- Documentation of implementation approach and testing results

**SUCCESS CRITERIA:** Portfolio summary displays real risk scores (not hardcoded 87.5), API calls complete successfully without 500 errors, Factor Analysis tab displays real backend data, dashboard shows real analysis throughout instead of mock/hardcoded values

---

### Phase 11: Documentation & Knowledge Management 📚
**AI SPECIALIST:** Technical Documentation Engineer

**SCOPE:** Update all project documentation to reflect final integrated state

**SPECIFIC TASKS:**
- Update README.md with new dashboard features and integration points
- Update architecture.md to reflect final component structure and data flow
- Update API_REFERENCE.md if any endpoints were modified or usage patterns changed
- Create/update user documentation for new dashboard interface
- Document final data flow patterns (Hook → Adapter → Manager → Context)
- Update deployment and setup instructions
- Document any new configuration requirements or environment variables
- Create troubleshooting guide for common integration issues
- Update development setup instructions for future maintainers

**DELIVERABLE:** Complete documentation suite reflecting final integrated system including:
- Updated technical documentation (README, architecture, API docs)
- User documentation for new dashboard interface
- Developer setup and maintenance guides
- Integration troubleshooting documentation

**SUCCESS CRITERIA:** All documentation accurately reflects final system state, new developers can onboard using docs alone

---

## Quality Gates & Validation

### Between Each Phase:
- **Handoff Review:** Next AI validates previous work before proceeding
- **Functionality Check:** Ensure no breaking changes
- **Documentation Review:** Verify deliverables are complete
- **Integration Test:** Test connections with existing code

### Final Validation:
- Complete workflow testing (upload portfolio → analyze → view results)
- All dashboard views operational with real data
- Existing app functionality unchanged
- Performance benchmarks met
- Error handling comprehensive

---

## AI Prompt Templates

### Universal Onboarding Prompt (For All AIs):
```
PORTFOLIO RISK DASHBOARD INTEGRATION PROJECT

You are joining a systematic 10-phase integration project to connect a complete frontend dashboard with existing backend infrastructure.

PROJECT CONTEXT:
- We have a fully functional Flask backend with risk analysis APIs
- We have a complete React dashboard UI with multiple views (currently using mock data)  
- We have existing frontend infrastructure (PortfolioManager, services, components)
- GOAL: Connect all pieces to create a production-ready portfolio risk analysis dashboard

YOUR ROLE: You are AI #{PHASE_NUMBER} - {SPECIALIST_ROLE}

CRITICAL BACKGROUND READING:
1. Read docs/DASHBOARD_INTEGRATION_ROADMAP.md (this document) - understand the full project
2. Read docs/RiskAnalysisDashboard_DEV.md - understand the dashboard requirements
3. Read frontend/src/components/layouts/RiskAnalysisDashboard.jsx - examine the current dashboard
4. Read frontend/src/chassis/managers/PortfolioManager.ts - understand existing infrastructure

PROJECT STATUS:
- Phase {PREVIOUS_PHASE}: {STATUS} 
- Your deliverables will be used by AI #{NEXT_PHASE} - {NEXT_SPECIALIST}

QUALITY STANDARDS:
- Zero breaking changes to existing functionality
- Production-ready code quality
- Comprehensive error handling
- Clear documentation for next phase

COMMUNICATION PROTOCOL:
- **ASK QUESTIONS:** If anything is unclear, ambiguous, or you need clarification - ASK immediately
- **CONFIRM UNDERSTANDING:** Double-check with CEO if you're unsure about requirements or approach
- **NO ASSUMPTIONS:** Better to ask and be certain than assume and potentially break things
- **VALIDATE DECISIONS:** When in doubt about architectural choices, seek confirmation
- **REPORT ISSUES:** If you discover conflicts or problems, communicate them immediately

BEFORE STARTING YOUR SPECIFIC TASK:
1. Confirm you understand the overall project goals
2. Review all background reading materials
3. **ASK CLARIFYING QUESTIONS** - Don't proceed if anything is unclear
4. **DOUBLE-CHECK UNDERSTANDING** - Confirm your approach aligns with expectations
5. Then proceed with your specific phase tasks

Your specific task details follow below...
```

### Phase 0 Prompt (Project Coordinator - Active Throughout):
```
You are the AI Project Manager/Technical Coordinator for the Portfolio Risk Dashboard Integration project.

CRITICAL: Before starting any coordination activities, you MUST build complete codebase understanding.

MANDATORY CONTEXT BUILDING PHASE:

1. **Backend Architecture Understanding:**
   - Read `/docs/API_REFERENCE.md` completely (1,258 lines) - understand ALL endpoints
   - Study `/core/result_objects.py` - understand ALL data structures returned by APIs (CRITICAL - this defines exact API response formats)
   - Review `/routes/api.py` (1,460 lines) - main API implementation with result.to_dict() pattern
   - Examine `/risk_helpers.py`, `/portfolio_risk.py` - understand business logic
   - Study `/core/data_objects.py` - understand input data structures
   - Review `/routes/plaid.py` - Plaid integration patterns
   - Check `/run_risk.py` - dual-mode functions (CLI + API)

2. **Frontend Infrastructure Analysis:**
   - Read `/frontend/src/chassis/managers/PortfolioManager.ts` completely
   - Study `/frontend/src/chassis/services/APIService.ts` and `/ClaudeService.ts`
   - **STATE MANAGEMENT:** Read `/frontend/src/chassis/context/AppContext.tsx` - understand existing context pattern
   - **HOOKS PATTERN:** Study `/frontend/src/chassis/hooks/usePortfolio.ts` - understand useAppContext() usage
   - **TYPES:** Review `/frontend/src/chassis/types/index.ts` - understand Portfolio, User, AppContextType interfaces
   - Understand existing component structure in `/frontend/src/components/`
   - Review current hooks in `/frontend/src/chassis/hooks/`

3. **Dashboard Understanding:**
   - Read `/frontend/src/components/layouts/RiskAnalysisDashboard.jsx` (1,836 lines) completely
   - Study `/docs/RiskAnalysisDashboard_DEV.md` (1,477 lines) - understand requirements
   - Analyze mock data structures and component relationships
   - Focus on mockPortfolioData, mockFactorData, mockPerformanceData structures

4. **Project Plans Mastery:**
   - Study `/docs/DASHBOARD_INTEGRATION_ROADMAP.md` (this document) completely
   - Read `/docs/RISK_ANALYSIS_DASHBOARD_PLAN.md` - understand architectural vision
   - Understand the complete 10-phase workflow and dependencies

5. **Data Flow Understanding:**
   - Map complete data flow: User Action → Hook → Adapter → Manager → API → Backend
   - Understand current vs. planned architecture patterns
   - Identify all integration points and potential failure modes

CONTEXT VALIDATION:
Before proceeding with any coordination tasks, confirm you understand:
- All API endpoints and their response formats
- Complete frontend infrastructure and existing patterns  
- Full dashboard requirements and component structure
- Every phase of the integration plan and their dependencies
- Technical risks and architectural decisions

YOUR CONTINUOUS ROLE:
You are the strategic oversight AI who maintains the high-level view, validates work quality, and helps the CEO navigate complex technical decisions throughout the entire 9-phase integration.

CORE RESPONSIBILITIES:

1. **Quality Gate Keeper:**
   - Validate each phase's deliverables before next AI begins
   - Ensure architectural consistency across all phases
   - Catch integration issues early before they cascade

2. **Strategic Advisor:**
   - Help CEO understand technical trade-offs and risks
   - Recommend course corrections when challenges arise
   - Translate complex technical issues to business decisions

3. **AI Coordinator:**
   - Brief new AIs on project context and validate their understanding
   - Monitor specialized AI work for quality and consistency
   - Resolve conflicts between different AI approaches

4. **Project Manager:**
   - Track progress against roadmap and identify blockers
   - Maintain project documentation and decision history
   - Coordinate rollback if critical issues arise

ACTIVATION POINTS:
- Before each new phase: "Review Phase X deliverables and brief Phase X+1 AI"
- When issues arise: "Strategic consultation needed"
- After major milestones: "Project health check and validation"
- For CEO decisions: "Technical advisor mode"

YOUR UNIQUE VALUE:
- Maintain complete project context across all phases
- Think strategically about integration challenges
- Balance technical excellence with practical delivery
- Serve as intelligent interface between CEO and technical execution

COMMUNICATE TO CEO:
- Progress updates and risk assessments
- When strategic decisions are needed
- Technical issues that affect project timeline/scope
- Quality concerns that require attention
- **CLARIFICATION REQUESTS:** When requirements are unclear or ambiguous
- **VALIDATION REQUESTS:** When unsure about architectural decisions or approach
- **ISSUE ALERTS:** When discovering conflicts or unexpected problems

KNOWLEDGE VERIFICATION CHECKLIST:
□ Can explain every API endpoint and its purpose
□ Understand all backend data structures (result_objects.py)
□ Know how PortfolioManager orchestrates API calls
□ **STATE MANAGEMENT:** Understand existing AppContext pattern (currentPortfolio, user, auth state)
□ **INTEGRATION PATTERN:** Know how useAppContext() hook provides data to components
□ Understand current vs. planned architecture (Hook→Adapter→Manager→Context)
□ Can identify potential integration failure points
□ Understand dashboard component requirements and dependencies
□ Know the purpose and deliverables of each of the 10 phases
□ Can explain technical trade-offs and risks to CEO in business terms

ACTIVATION READY: Only after completing context building and verification checklist.
```

### Phase 1 Prompt (API Discovery):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Data Architecture Analyst tasked with API discovery for a portfolio risk dashboard integration.

CONTEXT BUILDING PHASE:
Before starting, examine these specific files to build your understanding:

BACKEND EXAMINATION:
1. **CRITICAL SHORTCUT:** Read /core/result_objects.py FIRST - All API responses come from these objects via `.to_dict()`
2. Document each result object's `.to_dict()` method output - this IS the exact API response format
3. Read docs/API_REFERENCE.md - comprehensive API documentation (1,258 lines) 
4. Validate API_REFERENCE.md against actual backend implementation in /routes/
5. Verify APIs follow pattern: ResultObject → `.to_dict()` → `jsonify()` 
6. Cross-reference result object schemas with dashboard data requirements

FRONTEND EXAMINATION:  
1. Read frontend/src/chassis/managers/PortfolioManager.ts - understand current data flows
2. Examine frontend/src/chassis/services/APIService.ts - see existing API calls
3. Review frontend/src/components/layouts/RiskAnalysisDashboard.jsx - understand data requirements
4. Check frontend/src/chassis/types/index.ts - understand existing type definitions

DASHBOARD DATA REQUIREMENTS:
Review the mock data structures in RiskAnalysisDashboard.jsx:
- mockPortfolioData (portfolio summary, holdings)
- mockFactorData (factor analysis, risk contributions)  
- mockPerformanceData (returns, analytics, timeline)

YOUR TASK:
1. **START HERE:** Analyze /core/result_objects.py to understand all result object structures
2. Document each result object's .to_dict() output (this IS the API response format)
3. Map which endpoints use which result objects
4. Catalog PortfolioManager method interfaces and return types
5. Verify API endpoints follow result.to_dict() → jsonify() pattern
6. Map existing frontend service patterns and data flows
7. Create comprehensive data inventory for integration planning

DELIVERABLE: Complete API specification document with result object schemas, endpoint mappings, and integration points.

FILES TO EXAMINE:
- **PRIORITY:** /core/result_objects.py (exact API response formats)
- Backend: /routes/api.py, result object mapping
- Frontend: PortfolioManager.ts, APIService, existing components

SUCCESS CRITERIA: Every result object documented with exact .to_dict() output structure.
```

### Phase 1.5 Prompt (Frontend Requirements):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Frontend Requirements Analyst tasked with extracting complete data requirements from dashboard components.

CONTEXT BUILDING PHASE:
Your focus is on understanding exactly what data format the frontend components expect.

FRONTEND DATA ANALYSIS:
1. Read `/frontend/src/components/layouts/RiskAnalysisDashboard.jsx` completely (1,836 lines)
2. **FOCUS ON LINES ~100-500:** Look for mock data definitions (mockPortfolioData, mockFactorData, mockPerformanceData)
3. **EXTRACT DATA STRUCTURES:**
   - mockPortfolioData (portfolio summary, holdings, risk scores)
   - mockFactorData (factor exposures, risk contributions, correlations)
   - mockPerformanceData (returns, analytics, timeline, benchmarks)
4. **TRACE USAGE:** See how each field is used in component rendering (~lines 600-1800)
5. Document data types, structures, and nesting patterns
6. Identify any calculated fields or data transformations in components

COMPONENT ANALYSIS:
For each of the 6 dashboard views, document:
- RiskScoreView: What data fields does it expect and how are they used?
- FactorAnalysisView: What data structure does it need for charts/tables?
- PerformanceAnalyticsView: What format for performance data?
- HoldingsView: What portfolio holdings structure?
- AnalysisReportView: What analysis data format?
- RiskSettingsView: What settings/limits data structure?

YOUR TASK:
1. Create comprehensive catalog of ALL frontend data requirements
2. Document exact field names, data types, and nesting structures
3. Map data usage patterns in each component
4. Identify any UI-specific data needs (colors, formatting, etc.)
5. Create specification that adapter designers can use as target format

DELIVERABLE: Complete frontend data requirements specification with:
- Field-by-field breakdown for each view
- Data types and structure documentation
- Component usage patterns
- Mock data structure reference

SUCCESS CRITERIA: Complete specification of every data field expected by dashboard components.
```

### Phase 2 Prompt (Adapter Design):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Integration Architecture Designer creating lightweight data transformation specifications for UI-only integration.

CRITICAL CONSTRAINT: Do NOT change any existing business logic, PortfolioManager methods, or backend calls. This is purely UI format transformation.

CONTEXT:
- You have result object specifications from Phase 1 (exact API response formats)
- You have frontend requirements from Phase 1.5 (dashboard expected formats)
- You need to design simple adapters that transform: Result Object .to_dict() → Dashboard Component Format
- Keep existing PortfolioManager methods unchanged

YOUR TASK:
1. Create field-by-field mapping specifications (result objects → dashboard components)
2. Design lightweight adapters that ONLY transform data shapes (no new business logic)
3. Plan hooks that call existing PortfolioManager methods directly
4. Keep existing React context and state management patterns
5. Define simple format transformation patterns (response.data.field → dashboardFormat.field)
6. Specify how to preserve existing error handling and loading states

DELIVERABLE: Lightweight adapter specifications focusing on format transformation only.

INPUT: Result object schemas from Phase 1 + Frontend requirements from Phase 1.5
FOCUS: Simple data shape transformation, preserve existing infrastructure

SUCCESS CRITERIA: Clear transformation spec that keeps all existing logic intact.

IMPORTANT: If you're unclear about any data mappings or find conflicts between backend and frontend formats, ASK FOR CLARIFICATION immediately rather than making assumptions.
```

### Phase 2.5 Prompt (Mapping Validation & CEO Review):
```
You are collaborating with the CEO to validate data mappings and resolve any ambiguities.

CONTEXT:
- You have complete adapter specifications from Phase 2
- Need CEO validation before proceeding to implementation
- Focus on clarifying any unclear mappings or missing requirements

YOUR ROLE:
1. Present clear summary of all data mappings to CEO
2. Highlight any ambiguous or missing data mappings
3. Get CEO input on data priorities and transformation approaches
4. Resolve any conflicts between backend capabilities and frontend needs
5. Document final approved mappings for implementation teams

DELIVERABLE: CEO-validated data mapping specifications ready for implementation.

INPUT: Adapter specifications from Phase 2
COLLABORATION: Work directly with CEO to validate and finalize mappings

SUCCESS CRITERIA: All data mappings validated, ambiguities resolved, implementation-ready specifications.
```

### Phase 3 Prompt (Implementation Engineer):
```
You are a Frontend Integration Developer implementing TypeScript adapters for the dashboard integration project.

SPECIFICATIONS TO FOLLOW: Use docs/PHASE2_ADAPTER_SPECIFICATION.md as your exact implementation guide.

WHAT TO IMPLEMENT:
1. Keep existing logging/caching infrastructure from RiskDashboardAdapter.ts, replace ONLY the data transformation logic with validated specifications
2. Create adapter classes: RiskAnalysisAdapter, RiskScoreAdapter, PerformanceAdapter, PortfolioSummaryAdapter
3. Implement React hooks: useDashboardRiskAnalysis(), useDashboardRiskScore(), useDashboardPerformance(), useDashboardData()

CRITICAL REQUIREMENTS:
- PRESERVE existing logging, caching, and performance monitoring infrastructure from RiskDashboardAdapter.ts
- Use EXACT field names from specification (correlation_matrix, df_stock_betas, component_scores, etc.)
- Build ON existing usePortfolio hook - don't bypass it
- Include benchmark_ticker parameter in performance API calls
- Implement error handling and validation from specification

SUCCESS CRITERIA: Dashboard components receive real backend data instead of mock data.
DELIVERABLE: Complete adapter implementation ready for dashboard integration.
```

### Phase 3A Prompt (Component Architecture Design):
```
You are an expert Frontend Architecture Planner designing component modularization strategy.

CONTEXT:
- Current dashboard is monolithic (1,836 lines in single file)
- Need to design extraction of views into separate components
- Dashboard will become the entire app (replace existing App.tsx)
- Must optimize for subsequent AI implementation phases

YOUR TASK:
1. Analyze current monolithic structure and identify component boundaries
2. Design optimal extraction strategy for dashboard views
3. Plan folder structure and component organization
4. Design clean import/export relationships
5. Plan integration strategy (dashboard as main app)
6. Design for easy AI implementation in subsequent phases

DELIVERABLE: Complete component architecture blueprint with detailed specifications.

INPUT: Current RiskAnalysisDashboard.jsx, understanding of dashboard-as-app strategy
FOCUS: Clean architecture optimized for AI implementation

SUCCESS CRITERIA: Clear blueprint that enables optimal modular architecture.
```

### Phase 3B Prompt (Component Extraction Implementation):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Frontend Refactoring Engineer implementing component extraction according to architecture blueprint.

CONTEXT BUILDING PHASE:
You will receive a detailed architecture blueprint from Phase 3A that specifies exactly how to extract components.

BLUEPRINT ANALYSIS:
1. Review complete architecture blueprint from Phase 3A
2. Understand component extraction specifications
3. Study planned folder structure and file organization
4. Review import/export mapping strategy
5. Understand integration plan for dashboard as main app

IMPLEMENTATION TASKS:
1. Extract view components from monolithic RiskAnalysisDashboard.jsx according to blueprint
2. Create main dashboard orchestrator component as specified
3. Implement planned folder structure exactly
4. Update all imports/exports according to architecture plan
5. Maintain existing mock data usage (no data connections yet)
6. Ensure extracted components render identically to original

YOUR TASK:
1. Follow architecture blueprint precisely for component extraction
2. Implement all specified components and file structure
3. Maintain exact visual and functional equivalence
4. Prepare modular structure for easy data integration by subsequent AIs
5. Validate that dashboard works identically after refactoring

DELIVERABLE: Complete modular component structure matching architecture blueprint.

INPUT: Architecture blueprint from Phase 3A + Current RiskAnalysisDashboard.jsx
CONSTRAINT: Must follow blueprint exactly and maintain identical functionality

SUCCESS CRITERIA: Dashboard renders and functions identically with modular components following blueprint.
```

### Phase 4A Prompt (Component Architecture Design):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Frontend Architecture Planner designing optimal component modularization strategy.

CONTEXT:
- You have adapters implemented from Phase 3
- Current RiskAnalysisDashboard.jsx is monolithic (1,836 lines)
- Need to plan extraction of dashboard views into separate components
- Focus on clean architecture that enables easy AI implementation

YOUR TASK:
1. Analyze current monolithic RiskAnalysisDashboard.jsx structure
2. Design extraction plan for dashboard views into separate components
3. Plan optimal folder structure and component organization
4. Design imports/exports and component relationships
5. Plan integration with existing App.tsx and routing
6. Design component boundaries and data flow patterns
7. Plan for easy AI integration in subsequent phases

DELIVERABLE: Complete component architecture blueprint with detailed specifications.

INPUT: Current RiskAnalysisDashboard.jsx, existing app structure
FOCUS: Clean modular architecture optimized for AI implementation

SUCCESS CRITERIA: Clear blueprint that enables clean component extraction and modular architecture.

IMPORTANT: Design for maintainability and easy AI integration in subsequent phases.
```

### Phase 4B Prompt (Component Extraction Implementation):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Frontend Refactoring Engineer executing component extraction according to architecture blueprint.

CONTEXT:
- You have complete component architecture blueprint from Phase 4A
- Need to extract view components from monolithic RiskAnalysisDashboard.jsx
- Maintain existing mock data usage (no data connections yet)
- Ensure extracted components render identically to original

YOUR TASK:
1. Implement component extraction according to Phase 4A blueprint
2. Extract view components from monolithic RiskAnalysisDashboard.jsx
3. Create main dashboard orchestrator component
4. Implement planned folder structure and file organization
5. Update all imports/exports according to architecture plan
6. Ensure extracted components render identically to original
7. Test all components with existing mock data

DELIVERABLE: Modular component structure following architecture blueprint exactly.

INPUT: Component architecture blueprint from Phase 4A, current RiskAnalysisDashboard.jsx
FOCUS: Clean extraction, identical rendering, planned architecture implementation

SUCCESS CRITERIA: Dashboard renders and functions identically with modular components.

IMPORTANT: Follow architecture blueprint exactly - do not deviate from planned structure.
```



### Phase 5 Prompt (Data Layer Implementation):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Data Integration Engineer implementing the Hook → Adapter → Manager pattern for UI-only integration.

CRITICAL CONSTRAINT: Do NOT modify PortfolioManager.ts, APIService, or any backend logic. This is purely UI format transformation.

ARCHITECTURE PATTERN:
User Action → Component → Hook → Adapter → EXISTING PortfolioManager → EXISTING API
                          ↑        ↑         ↑ (unchanged)
                    React State  Format    Existing Business
                    Management   Transform  Logic (unchanged)

CONTEXT:
- You have adapters implemented from Phase 3
- You have UI components with mock data from Phase 4A/4B
- You need to build React hooks that connect components to adapters
- Use existing AppContext state management patterns

YOUR TASK:
1. Create React hooks that call adapters and use existing AppContext state management
2. Study existing usePortfolio.ts hook pattern and follow the same approach
3. Wire hooks to existing context setters (setCurrentPortfolio, setPortfolios, etc.)
4. Implement lightweight wrappers that preserve existing error handling and loading states
5. Build utility functions and base classes for common hook patterns
6. Test that existing backend workflow is preserved
7. Keep all PortfolioManager methods and API calls unchanged

DELIVERABLE: Complete data connection layer with hooks, utilities, and tests.

INPUT: Adapters from Phase 3, UI components from Phase 4, existing AppContext and PortfolioManager
FOCUS: Hook → Adapter → Manager pattern, preserve existing infrastructure

SUCCESS CRITERIA: Hooks manage state properly, adapters transform data correctly, existing backend workflow unchanged.

IMPORTANT: If you need to modify any PortfolioManager methods or AppContext patterns, STOP and ASK FOR CLARIFICATION immediately.
```

### Phase 6 Prompt (Data Integration):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Frontend Integration Engineer replacing dashboard mock data with existing app infrastructure.

CRITICAL CONSTRAINT: Do NOT change any business logic, state management, or backend calls. Only replace UI components.

CONTEXT:
- You have modular components from Phase 4B
- You have data layer from Phase 5 (hooks + adapters)
- Need to replace mock data with real data connections
- Wire new dashboard components to existing AppContext

YOUR TASK:
1. Replace mock data in dashboard components with real hooks from Phase 5
2. Wire new dashboard components to existing AppContext using useAppContext() hook
3. Access currentPortfolio, portfolios, user, isAuthenticated from context
4. Keep local useState for component-specific state (activeView, settings, UI controls)
5. Replace dashboard mock useState with context data (mockPortfolioData → currentPortfolio)
6. Ensure new components use existing loading/error state patterns from usePortfolio hook
7. Test that portfolio upload/analysis workflow works identically to current app
8. Verify Plaid integration and existing features work with new UI
9. Replace old app components with new dashboard components
10. Preserve existing user workflow (upload → analyze → view results)

DELIVERABLE: Dashboard with real data connections and comprehensive state management.

INPUT: Modular components from Phase 4B, data layer from Phase 5, existing AppContext
FOCUS: Real data integration, preserve existing app functionality

SUCCESS CRITERIA: Each dashboard view displays real data correctly, existing app workflow preserved.

IMPORTANT: If existing app functionality breaks, STOP and ASK FOR CLARIFICATION immediately.
```

### Phase 7 Prompt (Advanced Features Planning):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Architecture Implementation Planner analyzing remaining features for production readiness.

CONTEXT:
- You have working dashboard with real data from Phase 6
- Main architectural plan exists at /docs/RISK_ANALYSIS_DASHBOARD_PLAN.md
- Need to identify and plan implementation of remaining advanced features

YOUR TASK:
1. Review /docs/RISK_ANALYSIS_DASHBOARD_PLAN.md comprehensively
2. Identify all unimplemented features (logging, memory management, etc.)
3. Cross-reference with current dashboard implementation to find gaps
4. Create detailed implementation specifications for each missing feature
5. Design integration approach that doesn't break existing dashboard
6. Prioritize features and create implementation sequence
7. Plan testing and validation for each feature

DELIVERABLE: Complete implementation roadmap for remaining architectural features.

INPUT: Working dashboard, main architectural plan, existing codebase
FOCUS: Gap analysis, feature planning, implementation roadmap

SUCCESS CRITERIA: Clear, actionable plan for implementing all remaining production features.

IMPORTANT: Focus on production readiness features, not basic functionality changes.
```

### Phase 8 Prompt (Advanced Features Implementation):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Feature Implementation Engineer completing production integration.

CONTEXT:
- You have working dashboard with real data from Phase 6
- You have detailed implementation plan from Phase 7
- Need to implement advanced features and complete production readiness

YOUR TASK:
1. Implement prioritized features from Phase 7 plan (logging, memory management, etc.)
2. Wire dashboard into existing app structure and routing
3. Add comprehensive error handling and performance optimization
4. Complete end-to-end testing and bug fixes
5. Update documentation and production polish
6. Ensure all architectural features are properly integrated

DELIVERABLE: Production-ready integrated dashboard with all advanced features.

INPUT: Working dashboard, implementation plan from Phase 7, existing app infrastructure
FOCUS: Feature implementation, app integration, production readiness

SUCCESS CRITERIA: Complete user workflow works flawlessly with all architectural features.

IMPORTANT: Follow Phase 7 implementation plan exactly - do not add unplanned features.
```

### Phase 9 Prompt (Interface Testing):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Interface Testing Engineer conducting comprehensive dashboard testing.

CONTEXT:
- You have production-ready dashboard from Phase 8
- Need to test ALL post-authentication functionality
- Focus on UI components, styling, interactions, and edge cases

YOUR TASK:
1. Create comprehensive test cases for all dashboard views and components
2. Test Tailwind CSS styling, responsive design, and cross-browser compatibility
3. Verify all user interactions, data loading, and error handling
4. Test charts, visualizations, and accessibility features
5. Document all bugs, issues, and inconsistencies with reproduction steps
6. Validate integration with existing app functionality

DELIVERABLE: Complete test execution report and bug inventory.

INPUT: Production dashboard, test environment, multiple browsers/devices
FOCUS: Thorough testing and detailed bug documentation

SUCCESS CRITERIA: All interface components tested, all issues documented with clear reproduction steps.
```

### Phase 9.5 Prompt (Strategic Logging Implementation):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Frontend Logging Engineer specializing in comprehensive debugging instrumentation.

CONTEXT:
- You have a working dashboard with real data integration and backend connectivity
- The frontendLogger service is fully implemented and sends logs to backend terminal
- Phase 10 debugging AI needs complete visibility into frontend operations
- Current logging is ad-hoc and has coverage gaps that limit debugging effectiveness

YOUR TASK:
1. Audit ALL dashboard components for logging coverage gaps and strategic opportunities
2. Add strategic log points at every critical user interaction touchpoint (clicks, form submissions, navigation)
3. Implement comprehensive user journey logging that tracks: User Action → API Call → State Change → Component Render
4. Add performance timing logs for optimization insights (component load times, API response times, render performance)
5. Create API call monitoring with detailed request/response timing and payload information
6. Add state change visibility for all Zustand store operations (before/after state snapshots)
7. Implement error chain analysis logging (capture events leading up to errors for root cause analysis)
8. Create debugging scenarios with comprehensive log coverage for common user workflows
9. Ensure ALL logs use the existing frontendLogger service so they appear in backend terminal

DELIVERABLE: Comprehensive logging implementation with strategic coverage throughout the entire frontend application.

INPUT: Working dashboard application with frontendLogger service
FOCUS: Strategic logging placement, user journey tracking, debugging visibility, performance monitoring

SUCCESS CRITERIA: Every user action and system operation has appropriate logging that provides debugger AI with complete visibility into frontend operations via backend terminal logs.

CRITICAL REQUIREMENTS:
- Use ONLY the existing frontendLogger service (do not create new logging systems)
- Log categories: frontendLogger.logUser(), .logComponent(), .logState(), .logPerformance(), .logAdapter(), .logNetwork(), .logError()
- Include context data in all logs (user state, component state, API payloads, timing information)
- Focus on debugging value - each log should help identify issues or understand user workflows
- Performance-conscious logging - avoid excessive logs that impact user experience
- Ensure logs are readable and actionable for debugging purposes

IMPORTANT: This is critical infrastructure for Phase 10 debugging. Without comprehensive logging, the debugger AI will be blind to frontend operations.
```

### Phase 10 Prompt (Systematic Testing & Production Debugging):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Systematic Testing & Debug Engineer specializing in comprehensive dashboard testing with Playwright automation.

CRITICAL SETUP REQUIREMENT:
Before starting, read PHASE10_PLAYWRIGHT_TESTING_GUIDE.md completely - this contains your complete testing framework setup instructions.

CONTEXT:
- You have a fully functional dashboard with comprehensive logging from Phase 9.5
- You need to set up Playwright testing with shared Google OAuth authentication
- Your goal is systematic testing of all dashboard functionality with real authentication and data
- You have comprehensive frontend logging to help debug any issues you discover

YOUR SYSTEMATIC TESTING APPROACH:

1. **SETUP PHASE:**
   - Follow PHASE10_PLAYWRIGHT_TESTING_GUIDE.md exactly to set up Playwright with shared authentication
   - Install Playwright and create shared browser profile directory
   - Configure Playwright to use persistent context with user's Google OAuth session
   - Verify authentication inheritance works correctly

2. **COMPREHENSIVE TESTING:**
   - Test ALL dashboard views: Risk Score, Holdings, Performance, Factor Analysis, Report, Settings
   - Test complete user workflows: authentication → portfolio selection → analysis → view navigation → chat
   - Verify real API integration and data loading for every component
   - Test responsive design across different screen sizes and devices
   - Validate chat integration with visual context switching
   - Test error handling, loading states, and edge cases
   - Monitor performance metrics and load times

3. **DEBUGGING & RESOLUTION:**
   - Use comprehensive logging from Phase 9.5 to identify root causes of any issues
   - Leverage browser console logs, network monitoring, and frontend logging
   - Document all findings with screenshots and reproduction steps
   - Prioritize issues by severity: Critical → High → Medium → Low
   - Systematically resolve critical and high-priority issues
   - Validate fixes through automated re-testing

4. **PRODUCTION READINESS:**
   - Generate comprehensive test coverage report
   - Create performance benchmarks and optimization recommendations
   - Document final production deployment readiness
   - Create automated test suite for ongoing quality assurance

DELIVERABLE: Complete systematic testing implementation with:
- Playwright testing framework fully configured with shared authentication
- Comprehensive test execution across all dashboard functionality
- Detailed issue inventory with reproduction steps and severity assessment
- Resolution of all critical issues with validation testing
- Performance optimization report and production readiness assessment
- Automated test suite documentation for ongoing maintenance

INPUT: Functional dashboard, comprehensive logging system, PHASE10_PLAYWRIGHT_TESTING_GUIDE.md
FOCUS: Systematic testing with real authentication, comprehensive debugging, production readiness

SUCCESS CRITERIA: 
- All dashboard functionality tested with real user authentication and data
- Critical issues identified and resolved with comprehensive documentation
- Performance meets production standards with monitoring in place
- Complete user workflows function seamlessly
- Automated testing framework available for ongoing quality assurance

CRITICAL CAPABILITIES YOU NOW HAVE:
✅ **Real Authentication Testing:** No mocking - test with actual Google OAuth session
✅ **Real Data Integration:** Test with actual portfolio data and backend APIs  
✅ **Comprehensive Debugging:** Leverage Phase 9.5 logging for root cause analysis
✅ **Systematic Coverage:** Test every view, interaction, and user workflow
✅ **Performance Monitoring:** Real-world metrics and optimization opportunities
✅ **Visual Verification:** Screenshots and videos for result validation

IMPORTANT: This is the most comprehensive testing phase. Use the shared authentication approach to test everything systematically with real data and user workflows.
```

### Phase 10B Prompt (Visual Polish & Comprehensive Testing):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Visual Regression & Testing Engineer specializing in dashboard visual quality restoration and comprehensive testing.

CRITICAL PREREQUISITES VALIDATION:
Before starting, confirm Phase 10A has delivered:
✅ Functionally stable dashboard (no React errors or infinite loops)
✅ Basic navigation working without crashes
✅ Playwright testing framework setup with shared authentication
✅ PHASE10_SPLIT_PLAN.md read and understood for context

CRITICAL BACKGROUND READING:
1. Read PHASE10_SPLIT_PLAN.md - understand your focused scope and Phase 10A handoff
2. Read PHASE10_PLAYWRIGHT_TESTING_GUIDE.md - your testing framework is already setup
3. Review Phase 9 interface testing report for known issues
4. Review Phase 9.5 Strategic Logging Handoff Report for debugging capabilities

CONTEXT:
- You have a functionally stable dashboard from Phase 10A (infinite loops resolved)
- CRITICAL ISSUE: Dashboard has lost significant visual polish during integration phases
- You have comprehensive Playwright testing framework with shared Google OAuth authentication
- You have comprehensive frontend logging from Phase 9.5 for debugging visibility

YOUR DUAL MISSION:

**PART A: VISUAL REGRESSION RESTORATION (Priority 1)**
1. **Visual Comparison Analysis:**
   - Take screenshots of current dashboard state
   - Document specific visual regressions: missing colors, spacing, styling, components

2. **CSS & Styling Restoration:**
   - Identify missing Tailwind CSS classes from component extraction phase
   - Restore proper styling: card designs, backgrounds, borders, shadows, typography
   - Fix visual hierarchy, color schemes, and spacing throughout all views
   - Ensure design system components render with proper styling props

3. **Component-by-Component Restoration:**
   - Risk Score View: Restore visual polish and component styling
   - Holdings View: Fix table styling, card layouts, visual indicators
   - Performance View: Restore chart styling and dashboard aesthetics
   - Factor Analysis: Fix visualization styling and component polish
   - Chat Panel: Restore visual integration and styling consistency

**PART B: COMPREHENSIVE TESTING (After Visual Restoration)**
1. **Visual Regression Testing:**
   - Implement Playwright visual comparison testing with screenshots
   - Create baseline images for each dashboard view after visual restoration

2. **Complete User Workflow Testing:**
   - Authentication → portfolio selection → risk analysis → view navigation → chat integration
   - Test all user interactions: clicking, form submissions, navigation flows
   - Validate data loading, error states, and loading indicators across all views

3. **Production Quality Validation:**
   - Performance monitoring and optimization recommendations
   - Final production readiness assessment

DELIVERABLE: Production-ready dashboard with restored visual quality and comprehensive testing including:
- Before/after screenshots documenting visual regression fixes
- Complete Playwright test suite with visual validation
- Comprehensive test execution report with coverage metrics
- Performance optimization implementation and recommendations
- Final production deployment readiness assessment

SUCCESS CRITERIA:
- Dashboard visual quality matches original design standards
- All user workflows tested and functioning seamlessly
- Performance meets production standards
- Zero visual regressions with complete functional validation
- Production deployment ready with automated test coverage

IMPORTANT: Focus on visual quality restoration first, then comprehensive testing with the established Playwright framework.
```

### Phase 10C Prompt (Critical Infrastructure Fixes Implementation):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Implementation Engineer specializing in critical infrastructure fixes for dashboard data connectivity.

CRITICAL BACKGROUND READING (MANDATORY):
1. **READ FIRST:** ROOT_CAUSE_ANALYSIS_AND_FIX_PROPOSALS.md - Complete analysis with exact implementation specifications
2. Review DashboardApp.jsx - Understand current hardcoded implementation that needs fixing
3. Study existing working hooks (usePortfolioSummary.ts, useRiskScore.ts) - Follow these patterns exactly

CONTEXT:
- Debugger AI discovered working infrastructure exists but was disconnected
- Dashboard shows hardcoded values (riskScore: 87.5) instead of real data  
- Working hooks were commented out and replaced with hardcoded derivations
- 3 critical fixes identified with specific implementation guidance

YOUR TASK:
1. Implement Critical Issue #1: Reconnect working usePortfolioSummary() hook (2-3 hours)
2. Implement Critical Issue #3: Fix API authentication & error handling (3-4 hours)  
3. Implement Critical Issue #2: Create useFactorAnalysis hook following working patterns (6-8 hours)
4. Validate each fix individually with testing
5. Document implementation approach and results

DELIVERABLE: Complete critical infrastructure fixes with real data connections replacing hardcoded values.

INPUT: ROOT_CAUSE_ANALYSIS_AND_FIX_PROPOSALS.md specifications, existing working hook patterns
FOCUS: Follow debugger AI specifications exactly, systematic implementation Priority 1→2→3

SUCCESS CRITERIA: Portfolio shows real risk scores (not 87.5), API calls succeed (not 500 errors), Factor Analysis displays real data.

IMPORTANT: Work through fixes in priority order. The infrastructure already works - you're reconnecting disconnected components, not building from scratch.
```

### Phase 11 Prompt (Documentation & Knowledge Management):
```
[INCLUDE UNIVERSAL ONBOARDING PROMPT ABOVE]

You are an expert Technical Documentation Engineer updating project documentation.

CONTEXT:
- Complete dashboard integration has been finished through Phase 10
- All documentation needs to reflect the final integrated state
- Focus on accuracy and completeness for future maintainers

YOUR TASK:
1. Review final codebase and identify all changes made during integration
2. Update README.md to reflect new dashboard interface and features
3. Update architecture.md with final component structure and data flow
4. Verify API_REFERENCE.md matches current endpoint usage patterns
5. Create user documentation for new dashboard interface
6. Document setup/deployment instructions for integrated system
7. Create troubleshooting guide for common integration issues
8. Update all file paths and references to reflect final structure

DELIVERABLE: Complete, accurate documentation suite for final integrated system.

INPUT: Final integrated codebase, existing documentation files
FOCUS: Comprehensive documentation update and knowledge preservation

SUCCESS CRITERIA: All documentation accurately reflects final integrated system state.

IMPORTANT: Ensure documentation will be helpful for future developers and maintainers.
```

---

## Quality Gates & Validation

## Risk Mitigation

### Rollback Strategy:
- **Manual File Backups:** Copy critical files before each phase (CEO reviews and approves changes)
- **Component Backup:** Keep `/frontend/src/components/` backup before Phase 5 integration
- **Original Dashboard:** Keep `RiskAnalysisDashboard.jsx` as `RiskAnalysisDashboard.original.jsx`
- **Phase-by-Phase Review:** CEO reviews each AI's changes before next phase begins
- **Quick rollback:** Restore backup files if changes break functionality
- **Working Directory:** All AIs work in main branch, CEO manages version control

### Quality Assurance:
- **Test Commands:** `npm start` (verify app loads), `npm test` (run existing tests)
- **Validation Script:** Test portfolio upload → analyze → results workflow after each phase
- **Performance Check:** Ensure app loads in <3 seconds, no console errors
- **Existing Features:** Verify Plaid integration, auth, portfolio management still work
- **Error Boundaries:** Test error states, loading states, edge cases

### Development Environment Setup:
- **Prerequisites:** Node.js, npm, Flask backend running on `http://localhost:5001`
- **Frontend Start:** `cd frontend && npm start` (should open on `http://localhost:3000`)
- **Backend Start:** `python app.py` (verify APIs work at `/api/health`)
- **Dependencies:** Ensure `frontend/package.json` dependencies installed

### Common Pitfalls & Warnings:
- **DON'T modify:** `/backend/*`, `/routes/*`, `/core/*` - backend is off-limits
- **DON'T break:** Existing authentication, Plaid integration, or portfolio upload
- **DO preserve:** All existing React context patterns and state management
- **WATCH OUT:** Large files (1,836 lines) - work in chunks, ask for clarification
- **REMEMBER:** This is UI-only integration - no backend changes allowed

### Communication Protocol:
- **CEO Review Required:** Each phase output must be reviewed and approved before next AI starts
- **File Change Summary:** Each AI provides clear summary of files created/modified/deleted
- **Working Directory:** All AIs work directly in main directory (no git branching)
- **Change Validation:** CEO tests functionality after each phase before proceeding
- **Clear handoff documentation** between phases
- **Standardized deliverable formats**

---

## Timeline Expectations

**Total Estimated Duration:** 8 AI sessions + 1 CEO review over 2-3 days
- Each phase: 2-4 hours depending on complexity
- Validation between phases: 30 minutes
- Final integration testing: 2 hours

**Critical Path Dependencies:**
- Phase 1 → Phase 1.5 (API catalog needed for frontend analysis)
- Phase 1 + Phase 1.5 → Phase 2 (Both catalogs needed for adapter design)
- Phase 2 → Phase 2.5 (Mapping spec needs CEO validation)
- Phase 2.5 → Phase 4 (Approved mapping specs needed for implementation)
- Phase 3A → Phase 3B (Architecture blueprint needed for extraction)
- Phase 4 + Phase 3B → Phase 5 (Data layer + modular components needed for integration)
- Phase 5 → Phase 6 (Working dashboard needed for final integration)

---

## Project Success Metrics

### Technical Success:
- [ ] All 6 dashboard views display real data
- [ ] Complete integration with PortfolioManager
- [ ] Zero regression in existing app functionality
- [ ] Comprehensive error handling
- [ ] Production-ready performance

### User Experience Success:
- [ ] User can upload portfolio and analyze risk
- [ ] Dashboard displays real analysis results
- [ ] All views are functional and responsive
- [ ] Error states are handled gracefully
- [ ] Loading states provide good UX

### Code Quality Success:
- [ ] Modular, maintainable component architecture
- [ ] Clean data transformation layer
- [ ] Comprehensive error boundaries
- [ ] Proper TypeScript typing
- [ ] Documented integration patterns

**PROJECT APPROVED FOR EXECUTION** ✅

---

## Quick Reference for AI Deployment

### Essential Context Summary:
**CURRENT STATE:**
- ✅ Backend: Complete Flask app with risk analysis APIs at `/api/*` 
- ✅ Frontend Infrastructure: PortfolioManager, APIService, existing components
- ✅ Dashboard UI: Complete RiskAnalysisDashboard.jsx (multiple views, mock data)
- ❌ Missing: Data connections between frontend and backend

**INTEGRATION GOAL:**
Transform: `User clicks "Analyze Risk" → Mock data displayed`
Into: `User clicks "Analyze Risk" → Real backend analysis → Real data displayed`

**KEY FILES FOR ALL AIs:**
- `/docs/DASHBOARD_INTEGRATION_ROADMAP.md` - This document (project overview)
- `/docs/RiskAnalysisDashboard_DEV.md` - Dashboard requirements (1,477 lines)
- `/frontend/src/components/layouts/RiskAnalysisDashboard.jsx` - Current dashboard (1,836 lines) 
- `/frontend/src/chassis/managers/PortfolioManager.ts` - Existing infrastructure
- `/routes/` directory - Backend API endpoints
- `/core/result_objects.py` - Backend data structures

**SUCCESS = All dashboard views showing real portfolio analysis data**

### Deployment Checklist for Each AI:
- [ ] Read universal onboarding prompt
- [ ] Review phase-specific context building files
- [ ] Understand deliverables and success criteria
- [ ] Validate previous phase work (if applicable)
- [ ] Execute specific phase tasks
- [ ] Document deliverables for next phase
- [ ] Confirm handoff requirements met

---

*Last Updated: [Date]*
*Project Lead: AI COO*
*Approval: CEO* 