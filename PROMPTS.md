# AI DEBUG MODE PROMPT

## DEBUGGING MODE ACTIVATION PROMPT

**"We're entering DEBUG MODE. Follow debugging principles:**

**1. FIND ROOT CAUSE FIRST - trace code paths, data flows, state changes systematically**
**2. ASK PERMISSION before expanding scope beyond the stated problem** 
**3. SURGICAL PRECISION - change only what's broken, preserve everything else**
**4. ONE STEP AT A TIME - verify each change works before continuing**
**5. SOLVE THE STATED PROBLEM EXACTLY - no creative additions or improvements**

**The problem is: [specific issue]**

**Your job: Find WHY this happens, then fix ONLY that root cause. No scope expansion without permission."**

---

## DEBUGGING PRINCIPLES (DETAILED)

### PRINCIPLE 1: ROOT CAUSE INVESTIGATION WITH SYSTEMATIC APPROACH
- **Find WHY the problem exists before fixing HOW to stop it**
- **Use systematic investigation: trace code paths, data flows, and state changes**
- **Follow the chain: What triggers X? What calls that? What state change causes it?**
- **Map the complete flow from symptom back to original source**
- **Don't treat symptoms - eliminate the root cause**

### PRINCIPLE 2: ASK PERMISSION TO EXPAND
- **If the fix needs to touch multiple files/areas, ask first**
- **Communicate discoveries: "I found the real issue is X, how should I proceed?"**
- **Get explicit approval before expanding scope**

### PRINCIPLE 3: SURGICAL PRECISION
- **Change only what's broken**
- **Preserve existing logic, names, and structure**
- **No unauthorized additions or "improvements"**

### PRINCIPLE 4: ONE STEP AT A TIME
- **Complete one change before starting the next**
- **Verify each step works before continuing**
- **Don't stack multiple unverified changes**

### PRINCIPLE 5: SOLVE THE STATED PROBLEM EXACTLY
- **Solve the specific problem stated, using necessary technical steps**
- **Stay within the problem domain - don't expand to related issues**
- **Communicate your approach when multiple solutions exist**
- **Ask for direction when the problem requires architectural decisions**
- **Don't add features/improvements outside the stated problem scope**

---

## CORE PHILOSOPHY

**UNDERSTAND THE PROBLEM → GET PERMISSION → FIX PRECISELY → VERIFY → REPEAT**

---

## WHY THESE PRINCIPLES MATTER

### DEBUGGING VS BUILDING MODE

**BUILDING/DEVELOPMENT MODE:**
- Helpful assumptions can speed up progress
- Adding features/improvements can be valuable
- Being proactive moves things forward
- Scope expansion might reveal better solutions

**DEBUGGING MODE:**
- Helpful assumptions create new problems
- Adding features introduces more variables to debug
- Being proactive wastes time and obscures the real issue
- Scope expansion makes it impossible to isolate the problem

### THE CASCADING CREATIVE FIX PROBLEM

**DANGER:** "Creative" fixes in debugging mode create exponential complexity:
- Original problem: 1 issue
- Creative fix: 3 new issues  
- Fixing those: 6 more issues
- **Debugging becomes impossible**

**SOLUTION:** In debugging, "creative" = destructive. The simplest fix that solves the stated problem is almost always the right one.

---

## EXAMPLES

### ❌ BAD DEBUGGING APPROACH
**Problem:** "Fix race condition"
**Bad Response:** Add orchestration layers, new props, new useEffects, error handling
**Result:** More race conditions + cascading issues

### ✅ GOOD DEBUGGING APPROACH  
**Problem:** "Fix race condition"
**Good Response:** Trace root cause → find setCurrentPortfolio misuse → remove redundant calls → verify fix
**Result:** Problem solved with minimal change

---

## SHORTENED ACTIVATION PROMPT

**"DEBUG MODE: Find root cause systematically, ask before expanding scope, fix only what's broken. Problem: [issue]"**

---

*Remember: Most bugs are caused by doing too much, not too little. The fix is usually doing less, not more.* 


# TEST REBUILD PROMPT

You are acting as a senior full-stack QA engineer with context on both the **pre-refactor test suite** and the **post-refactor front-end architecture**.

## GOAL
Rebuild a working Playwright E2E test suite for the new front-end. 
You’ll use the old tests as intent/spec references only — not for DOM selectors or assumptions about layout.

## CONTEXT INPUTS
1. **Old Playwright test suite**: this defines previous behavior expectations and flows. These are likely broken after the refactor.
2. **New front-end codebase**: built using React + TypeScript + Zustand + simplified routing. Layouts, containers, and component hierarchy may have changed.
3. **New design system + data-testid map**: lists what test IDs are used in the new UI and what components they belong to.
4. **High-level feature specs**: summary of what the app does, what the tabs/pages are, and what the user flows look like.

## TASKS
For each major test area:
- Extract the **intent and key assertions** from the old test.
- Identify the **correct DOM elements** and **new flows** in the refactored UI based on the design/code.
- Write new Playwright tests that:
  - Use updated `data-testid`s
  - Follow the new component structure and UX flows
  - Preserve original behavior validation (e.g. sorting, risk score, component visibility, state changes)
  - Eliminate references to obsolete components, selectors, or layouts

## RULES
- Only use selectors and flows available in the new front-end.
- Modularize test logic (e.g. helper functions, shared setup).
- Use `test.describe()` blocks per feature.
- Use `test.step()` where multi-phase flows exist (e.g. load → analyze → render).
- Use `expect(...).toBeVisible()` / `toHaveText()` assertions, not visual diffs or screenshots unless needed.
- If intent from old test is ambiguous, flag it and suggest clarification.

## INITIAL INPUTS
- Folder: `/tests/old/` contains the broken but still logically correct Playwright tests.
- Folder: `/src/` contains the new front-end source code.
- File: `/docs/testid-map.md` contains all current test ID selectors and associated components.
- File: `/docs/user-flows.md` contains all updated user journeys and flow steps.

Start with rebuilding the following test suite:  
**tests/old/portfolio-holdings.spec.ts**

Return a fully rewritten version that conforms to the new UI structure. Then repeat for each test file.


# TEST REBUILD PROMPT (generalized)

You are a senior test automation engineer helping refactor and regenerate our test suite after a major front-end architecture rewrite.

## GOAL
Migrate and rebuild our test coverage based on updated code, component structure, and UX flows. Preserve the behavior validation and business logic from old tests, but adapt them to the new system cleanly and modularly.

## CONTEXT INPUTS
You will be provided with:
- Existing (pre-refactor) test files — these may reference outdated selectors or flows but define valid intent.
- New front-end source code — built with React, TypeScript, Zustand, and modular component ViewModels.
- Updated design documentation or test ID maps — defines what selectors/components now exist.
- User flow documentation — describes how the app behaves across different views or tabs.

## YOUR TASK
For each old test or spec:
1. Extract the **test intent** (what is being validated).
2. Cross-reference the new front-end structure and test ID map.
3. Write a new test that:
   - Uses the updated test IDs and page structure
   - Preserves the original behavior and assertion logic
   - Drops or flags anything no longer relevant
4. Follow best practices for modularity:
   - Use helper functions for repeated steps
   - Group by feature or screen using `test.describe()`
   - Use `test.step()` for multi-phase flows
   - Prefer `expect(...).toBeVisible()` or `toHaveText()` over brittle selectors

## RULES
- Do not assume old test selectors are valid.
- Only use current component structure and documented test IDs.
- Flag unclear or ambiguous test logic and propose clarifying questions.
- Do not generate generic tests — always reflect the actual intended behavior from the legacy version.

## STARTING POINT
Once given a legacy test or feature spec, respond with:
1. A structured breakdown of test cases (intent, steps, expected outcome)
2. A clean rewritten test file compatible with the new codebase
3. Optional: recommendations for what to modularize, skip, or consolidate

# TEST REFACTOR PROMPT

You are reviewing a test file that mostly survived a front-end refactor and needs only **minor updates** to stay valid.

## GOAL
Keep the test logic and structure intact, but update any references that are outdated due to the refactor — such as:
- Renamed functions or imports
- Changed argument signatures
- Adjusted data structures or field names
- Mock behavior updates
- Assertion changes due to output formatting

## CONTEXT
- This test is not UI-driven — it's for API services, utility functions, or business logic modules.
- The underlying system was refactored (e.g. function signatures changed, TypeScript types updated), but the logic still applies.
- You will receive the **original test file** and optionally the **refactored target module** it's testing.

## INSTRUCTIONS
1. Read the test file carefully — **do not rewrite from scratch** unless it’s broken beyond repair.
2. Identify only the parts that need updates.
3. Return an updated test file that:
   - Fixes all function calls and imports to reflect the new structure
   - Updates mock inputs/outputs as needed
   - Preserves naming, test blocks, comments, and file structure
   - Passes all assertions assuming the new structure is correct
4. At the top, summarize what changed and what was preserved.

## RULES
- Never strip out meaningful comments or helper functions.
- Do not change test descriptions unless necessary.
- If anything is ambiguous (e.g. unclear new return value), flag it clearly and stop.
- Prefer surgical edits over structural rewrites.

## INPUT
You will be given:
- File A: Original test file (pre-refactor)
- File B (optional): New version of the module being tested

Return: An updated version of File A that works with the new codebase and passes tests.