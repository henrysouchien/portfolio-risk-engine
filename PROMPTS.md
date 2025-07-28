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