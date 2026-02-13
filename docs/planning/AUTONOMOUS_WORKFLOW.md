# Autonomous Claude Code + Codex Workflow

**Purpose:** General-purpose workflow for delegating tasks between Claude Code and OpenAI Codex via MCP. Designed for autonomous multi-agent collaboration with minimal user intervention.

---

## Codex MCP Configuration

### Critical: `approval-policy: "never"`

When calling Codex via MCP (`mcp__codex__codex` tool), **always set `approval-policy: "never"`**. Without this, Codex prompts for interactive approval on shell commands — but since it's running as a non-interactive MCP server, those prompts can't be answered and the task hangs or fails silently.

```
approval-policy: "never"   # REQUIRED for MCP — no interactive approval possible
sandbox: "workspace-write" # or "danger-full-access" if writes needed outside cwd
```

**Why this matters:** Simple read-only tasks (e.g., "read this file") work without this flag because they don't trigger shell commands. Any task requiring script execution, file writes, or git operations will fail without `approval-policy: "never"`.

### Available Parameters

| Parameter | Purpose | Recommended |
|-----------|---------|-------------|
| `prompt` | Initial task description (required) | Be detailed — Codex has no prior context |
| `approval-policy` | Shell command approval | `"never"` (always) |
| `sandbox` | Filesystem access level | `"workspace-write"` for most tasks |
| `cwd` | Working directory | Set to project root |
| `model` | Override model | Omit to use default |
| `base-instructions` | Custom system instructions | Use for project-specific context |

### Sandbox Modes

- **`read-only`** — No file modifications (safe for pure research)
- **`workspace-write`** — Can create/edit files within `cwd` (standard for implementation)
- **`danger-full-access`** — Unrestricted filesystem access (use sparingly)

### Session Continuity

Codex returns a `threadId` with each response. Use `mcp__codex__codex-reply` with that `threadId` to continue a conversation across multiple turns.

---

## Workflow Steps

### 1. Explore
Research the codebase, understand existing patterns, and scope the task.
- Read relevant source files and documentation
- Identify the files that need to be created or modified
- Note existing patterns and conventions to follow

### 2. Plan
Write a plan document to a project-appropriate location.
- List all files to create/modify
- Define the approach, parameters, and expected outputs
- Document edge cases and constraints
- Include verification/test steps

### 3. Codex Review
Send the plan to Codex for review.
- Address all feedback (LOW, MED, HIGH severity)
- Update the plan document with fixes
- Send back for another review round
- Repeat until Codex approves

### 4. Implement
Task a **new** Codex instance to implement from the finalized plan.
- Do NOT reuse the reviewing Codex — use a fresh one for implementation
- The plan document should contain enough detail for unambiguous implementation
- Set `approval-policy: "never"` and appropriate `sandbox` mode

### 5. Review
Read the implementation and verify it matches the plan.
- Check all files were created/modified as specified
- Verify patterns match existing codebase conventions
- Confirm edge cases from the plan are handled

### 6. Test
Run tests appropriate to the project.
- Unit tests, integration tests, or manual verification
- Cover happy path, edge cases, and error cases
- Verify no regressions in existing functionality

### 7. Housekeeping
- Mark plan document as **COMPLETE**
- Update any tracking docs or task boards
- Update memory/notes with lessons learned

### 8. Report Back
Summarize results to the user:
- What was built or investigated (files, scope)
- Test results
- Any issues encountered during the workflow

---

## Task Types

### Implementation Tasks
Use Codex for code generation when you have a clear plan.
- Write the plan in Claude Code, send to Codex for review, then a fresh Codex for implementation
- Claude Code reviews the output and runs tests

### Investigation / Research Tasks
Use Codex for deep-dive analysis that requires running scripts.
- Provide the task doc with reproduction scripts and acceptance criteria
- Codex writes findings back into the task document
- Claude Code reviews and summarizes findings

### Code Review
Use Codex as a second opinion on plans or implementations.
- Send the code/plan with specific review criteria
- Address feedback iteratively via `codex-reply`

---

## Rules

- **Always use `approval-policy: "never"`** when calling Codex via MCP
- **Keep going without user approval** unless there's a design decision that needs input
- **Use a fresh Codex for implementation** — never reuse the reviewing Codex
- **Address all Codex feedback** — do not skip any items regardless of severity
- **Be detailed in prompts** — Codex has no shared context with Claude Code; include file paths, API notes, and reproduction steps
- **Report back after testing** with a full summary

---

*Document created: 2026-02-06*
*Updated: 2026-02-07 — Generalized from portfolio-mcp-specific to cross-project workflow; added Codex MCP configuration section*
