# Hook Dirty-Tree Hard-Block Plan (R3)

Motivation incident (2026-04-24): a parallel Claude session ran `git checkout main` in the shared `/Users/henrychien/Documents/Jupyter/risk_module` cwd at 13:35:52. The current hook classified it as ASK (single-operand ambiguity). Approval was given. The checkout moved HEAD from `feat/plan-6-mcp-surface` to `main` and wiped this session's uncommitted `CLAUDE.md` edits (the `NEVER CREATE OR SWITCH BRANCHES` rule itself). Reflog:

```
13:35:53  pull --ff-only origin main: Fast-forward
13:35:52  checkout: moving from feat/plan-6-mcp-surface to main
```

Codex R1/R2 verified locally: `git checkout <branch>` DOES succeed silently on a dirty tracked file when the target branch does not change that file — preserving the local mods. `git pull --ff-only` on that preserved dirty tree REFUSES with "local changes would be overwritten" when remote touches the same file, preserving the edit. So "git itself refuses" is NOT a safety net for the `checkout` step itself, but pull does self-protect. The ambiguous single-operand checkout path still MUST be escalated to DENY on dirty tree — the risk is that mods silently displace onto the wrong branch and a *later* destructive operation (explicit `git restore`, a parallel agent's Write, a `git checkout -- file`) overwrites them. The incident's exact wipe mechanism after the preserved-across-checkout step is uncertain; candidates include a parallel agent's Edit/Write, an explicit restore, or another checkout.

## §1 Problem

`~/.claude/hooks/git_destructive_guard.py` is advisory: every non-SAFE classification becomes an ASK prompt. When uncommitted tracked work exists in the cwd, a HEAD-moving command (branch checkout or switch) can silently destroy or displace that work even after user approval, because:
- Claude cannot assess blast radius when prompted.
- The ASK reason doesn't warn that uncommitted work in parallel sessions' cwd can be wiped by subsequent actions (pull / rebase / next checkout).
- User habituation to ASK prompts → click-through.

We need a **conditional hard-block** (permission deny) for *HEAD-moving command (or ambiguous single-operand checkout) + dirty working tree*.

## §2 Current Behavior (traced — line numbers as of R2)

File: `/Users/henrychien/.claude/hooks/git_destructive_guard.py` (1012 lines). Test file: `/Users/henrychien/.claude/hooks/test_git_destructive_guard.py` (599 lines).

State enum (line 14): `SAFE=0, HEAD_MOVING=1, DESTRUCTIVE=2, ASK=3`. `combine_result` (line 154) picks higher state. Verified by Codex R1 that inserting `DENY=4` works correctly with current combine logic — no change needed.

`main()` (line 986) emits ASK for every non-SAFE state — no current path to emit deny.

Classifiers return early at analyze_simple_command line 902–903 for non-HEAD_MOVING states, so ambiguous-single-operand currently bypasses the worktree probe. This is the gap that must be closed.

Probe infrastructure: `probe_worktree` (line 754) runs `git rev-parse --git-dir --git-common-dir`, returns "MAIN", "LINKED", or "ASK". Uses `build_probe_env` (line 740) to construct env from repo_env values.

Ask payload builder: `build_ask_payload` (line 947) with `permissionDecision: "ask"`. Claude Code also supports `"deny"` for hard-block — we'll add a parallel `build_deny_payload` / `emit_deny`.

Test infrastructure (`test_git_destructive_guard.py`):
- `GitFixture` (line 39) — single shared fixture with `main`, `linked`, `outside` worktrees. Clean state only. No per-case dirty setup or teardown.
- `Case` dataclass (line 23) — `expect` field accepts `"allow"` / `"ask"` only. `run_case` (line 557) asserts every non-allow result is `"ask"`.
- Current state: **10 tests FAILING** on stale `reason_contains="Ambiguous git checkout operand"` substrings (broken by the earlier message-refresh edit). Baseline must be green before adding new cases.

## §3 Proposed Design

Add `State.DENY = 4` (highest priority). DENY classifications emit a deny payload that hard-blocks the tool call — user must run the command from a terminal outside Claude to proceed.

Add `check_working_tree_dirty(cwd, globals_info, repo_env) -> tuple[bool, bool]` returning `(is_dirty, probe_failed)`. Runs `git status --porcelain --untracked-files=no` (modified tracked + staged only).

Escalation rules (applied in `analyze_simple_command`):

| Subcommand | Existing result | Dirty? | New result |
|---|---|---|---|
| `checkout -b` / `--orphan` / `--detach` | HEAD_MOVING | yes | **DENY** |
| `checkout <single-operand>` (ambiguous) | ASK | yes | **DENY** |
| `switch <branch>` (no force) | HEAD_MOVING | yes | **DENY** |
| `checkout` force / pathspec / `-B` / path-form | DESTRUCTIVE | any | unchanged (ASK) |
| `restore` | DESTRUCTIVE | any | unchanged (ASK) |
| `reset --hard` | DESTRUCTIVE | any | unchanged (ASK) |
| `clean -f` | DESTRUCTIVE | any | unchanged (ASK) |
| any command, clean tree | — | no | unchanged |

Explicitly-destructive commands (restore / reset --hard / clean) stay at ASK because the user typed them *intending* to discard — the prompt should clarify risk, not block. Head-moving and ambiguous commands are the silent-destruction vector.

DENY reason (exact wording):

> BLOCKED — working tree has uncommitted tracked changes. A branch switch here would either (a) silently preserve mods onto the target branch (they now appear to belong there — easy to lose track of across parallel sessions) or (b) be refused by git if the target branch changes the same path. In case (a), any later destructive op (`git restore`, `git checkout -- file`, another agent's Write) overwrites them without warning. The switch also moves HEAD for every parallel Claude session rooted in this cwd. Run `git status` to see what's uncommitted. To proceed: commit, `git stash`, or run this command from a terminal outside Claude. (Untracked files are not at risk and were not counted.)

## §4 Edge Cases & Decisions

1. **Probe failure on dirtiness check** — `git status` errors / timeout. Fall through to existing behavior (ASK). Don't escalate to DENY because we're not confident the tree is actually dirty.

2. **Untracked files excluded** — `--untracked-files=no`. Verified by Codex R1: `git checkout <branch>` preserves untracked files when the target branch doesn't track that path; refuses with "would be overwritten" if target DOES track the path. Hook doesn't need to cover either — git itself handles both correctly. Untracked files are not the wipe-vector.

3. **Silent-preservation vector is the real risk.** Codex R1 verified: dirty tracked file + target branch doesn't change that path → `git checkout` succeeds, local mods carry over onto the target branch. Codex R2 further verified: `git pull --ff-only` on the preserved dirty tree REFUSES with "local changes would be overwritten" when the pull would touch that path — so pull itself is a self-protecting step, not a clobber step. The incident's exact wipe mechanism AFTER the silent-preservation is uncertain; candidates: a parallel agent's Write/Edit to CLAUDE.md, an explicit `git restore CLAUDE.md` or `git checkout -- CLAUDE.md` from another session, or a subsequent checkout that DID conflict and was forced. What we know for certain: the ambiguous-single-operand `git checkout main` on a dirty tree is the entry point for all of these compound destruction paths, and it's silent at the checkout moment. DENY closes the entry.

4. **Submodules** — `git status --porcelain` reports modified submodules by default. Treat as dirty. If a submodule is spuriously dirty (detached HEAD commonly is), we over-block. Known trade-off; can add `--ignore-submodules` later if it bites.

5. **LINKED worktree with dirty tree** — current behavior: HEAD_MOVING in a linked worktree → SAFE (no prompt). Under new rule: dirty + any HEAD-moving → DENY regardless of linked/main. Codex R1 notes this is a real over-block for legitimate "carry dirty changes across branches" workflow in a linked worktree. **Accepted policy**: dirty + branch-change is rare and error-prone enough that requiring explicit out-of-Claude action is worth it. Clean linked worktrees remain SAFE (no prompt) — the common fast path stays fast.

6. **Git globals with explicit selector (`-C <path>`)** — dirty probe runs in that `-C` target (same as `probe_worktree`). `check_working_tree_dirty` takes `globals_info` + `repo_env` and constructs the probe command identically.

7. **`repo_env.dirty` / `globals_info.dirty`** — if shell-metachars prevent clean probe, `check_working_tree_dirty` short-circuits to `(False, True)` (probe_failed). Caller falls through to existing ASK behavior.

8. **Performance** — adds one `git status --porcelain --untracked-files=no` subprocess per git command classified as HEAD-moving or ambiguous-single-operand. Combined with existing `probe_worktree` call: 2 subprocess calls worst case, 2s timeout each. Acceptable.

9. **Chained commands (`git stash && git checkout main`)** — the hook analyzes each simple command separately. At hook time, the tree IS dirty, so the checkout clause returns DENY even though the user's clear intent is "stash first then switch." Known over-block. **Resolution**: accept — the user's workaround is to run `git stash` as a separate prior command, then `git checkout main` as a second command (after stash, the tree is clean and checkout goes through as normal ASK). Documented in the DENY reason indirectly ("`git stash` first" is listed as an unblock path).

10. **Bypass path** — user can still run the command from a terminal outside Claude. Hook gates Claude Code's Bash tool only. Intentional.

## §5 Scope

Files touched:
1. `/Users/henrychien/.claude/hooks/git_destructive_guard.py` — add State.DENY, check_working_tree_dirty, build_deny_payload, emit_deny, update analyze_simple_command, update main(), add ambiguous-checkout escalation path.
2. `/Users/henrychien/.claude/hooks/test_git_destructive_guard.py` — fix 10 existing failures (stale `reason_contains`), extend `Case.expect` to accept `"deny"`, extend `run_case` to assert permission decision, add per-case dirty-setup helper, add new test cases.

Symbols added in hook:
- `State.DENY = 4`
- `DIRTY_BLOCK_REASON` constant
- `check_working_tree_dirty(cwd: str, globals_info: GitGlobals, repo_env: RepoEnv) -> tuple[bool, bool]`
- `build_deny_payload(reason: str) -> str`
- `emit_deny(reason: str) -> None`

Symbols modified in hook:
- `analyze_simple_command` — insert dirty check for both HEAD_MOVING (post-probe) and ambiguous-single-operand paths.
- `classify_checkout` — annotate ambiguous-single-operand result so `analyze_simple_command` can detect it. Options:
  - (i) Add a private reason-substring sentinel and match on it in analyze — fragile.
  - (ii) Add `AnalysisResult.kind: str | None` field, set to `"ambiguous_checkout"` for the single-operand case.
  - **Decision: (ii)** — explicit and type-checkable. See §6 Step 4.
- `main()` — add DENY branch before DESTRUCTIVE/HEAD_MOVING.

Symbols added in tests:
- `Case.expect` accepts `"deny"`.
- `Case.dirty_setup: Optional[Callable[[GitFixture], None]]` or similar — per-case dirty-tree setup + automatic cleanup (see §6 Step 1).
- `run_case` asserts permission decision matches `expect` for `"deny"` in addition to existing `"ask"` / `"allow"`.

Symbols NOT touched:
- Classifiers (`classify_switch`, `classify_restore`, etc.) — return same states; escalation happens in analyze layer.
- `probe_worktree` — unchanged.
- Shell/env parsing — unchanged.

## §6 Implementation Steps

**Phase 0: Fix baseline (prerequisite).** The existing test suite has 10 failures on stale `reason_contains="Ambiguous git checkout operand"`. Update those expected substrings to match the current hook output (`` "`git checkout <name>` is ambiguous" ``) so baseline is 139 passing / 0 failing / 1 skipped before any new code.

**Phase 1: Hook changes.**

1. Add `State.DENY = 4` to the IntEnum at line 14. `combine_result` (line 154) automatically prefers higher value — verified by Codex R1.

2. Add `DIRTY_BLOCK_REASON` constant (near line 20–41 reason block). Use exact §3 wording.

3. Add `check_working_tree_dirty(cwd, globals_info, repo_env) -> tuple[bool, bool]` near `probe_worktree` (~line 748). Short-circuit: if `repo_env.dirty` or `globals_info.dirty` → `(False, True)`. Build command with `-C` / `--git-dir` / `--work-tree` from globals_info; run `git [...globals...] status --porcelain --untracked-files=no` with 2s timeout via `build_probe_env(repo_env)`. On OSError/Timeout → `(False, True)`. On non-zero returncode → `(False, True)`. On success → `(bool(completed.stdout.strip()), False)`.

4. Annotate ambiguous-single-operand in `classify_checkout`. Add a `kind: str | None = None` field to `AnalysisResult` dataclass (line 113). In the ambiguous-single-operand branch (~line 653), return `AnalysisResult(State.ASK, reason, kind="ambiguous_checkout")`. Update `combine_result` (line 149): higher-state winners already return `new` (which carries its own `kind`) — that's correct. The equal-state reason-transfer branch (`new.state == current.state and current.reason is None and new.reason`) must also transfer `kind`: return `AnalysisResult(current.state, new.reason, new.kind)`.

5. Update `analyze_simple_command` (~line 902–918). New flow. **Critical**: the `ctx.cwd_dirty/env_dirty` guard must apply to BOTH the ambiguous-checkout and HEAD_MOVING paths (closes Codex R2 blocking finding — without this, `cd /tmp && git checkout main` would probe the original hook_cwd instead of /tmp, possibly denying the wrong repo or missing the dirty target).
   ```python
   subcommand = tokens[subcommand_index]
   if subcommand not in {"checkout", "switch", "restore", "reset", "clean", "worktree"}:
       return AnalysisResult(State.SAFE)

   classification = classify_git_subcommand(subcommand, tokens[subcommand_index + 1 :])

   # For both ambiguous-checkout AND HEAD_MOVING: if shell context shifted cwd/env
   # without an explicit git selector, we can't trust the probe target. Fall back to ASK.
   needs_dirty_probe = (
       classification.kind == "ambiguous_checkout"
       or classification.state == State.HEAD_MOVING
   )
   if needs_dirty_probe and (ctx.cwd_dirty or ctx.env_dirty) and not globals_info.has_explicit_selector:
       return ask_result(DIRTY_CONTEXT_REASON)

   # Escalate ambiguous-single-operand checkout on dirty tree
   if classification.kind == "ambiguous_checkout":
       is_dirty, dirty_probe_failed = check_working_tree_dirty(hook_cwd, globals_info, repo_env)
       if dirty_probe_failed:
           return classification  # stay ASK with the existing ambiguous-checkout reason
       if is_dirty:
           return AnalysisResult(State.DENY, DIRTY_BLOCK_REASON)
       return classification  # clean — stay ASK

   if classification.state != State.HEAD_MOVING:
       return classification

   # Existing HEAD_MOVING probe flow (dirty-context guard already applied above)
   probe_result = probe_worktree(globals_info, repo_env, hook_cwd)
   if probe_result == "ASK":
       if repo_env.dirty: return ask_result(REPO_ENV_DIRTY_REASON)
       if globals_info.dirty: return ask_result(GLOBAL_DIRTY_REASON)
       return ask_result(PROBE_FAILURE_REASON)

   # NEW: dirty check for HEAD-moving (applies to both LINKED and MAIN per §4.5)
   is_dirty, dirty_probe_failed = check_working_tree_dirty(hook_cwd, globals_info, repo_env)
   if dirty_probe_failed:
       # Per §4.1 — dirty probe failure falls through to ASK, including for linked worktrees.
       # This is stricter than "LINKED + clean" which is SAFE. Defense in depth: if we can't
       # confirm clean, prompt.
       return ask_result(PROBE_FAILURE_REASON)
   if is_dirty:
       return AnalysisResult(State.DENY, DIRTY_BLOCK_REASON)

   if probe_result == "LINKED":
       return AnalysisResult(State.SAFE)
   return AnalysisResult(State.HEAD_MOVING)
   ```

6. Add `build_deny_payload(reason)` and `emit_deny(reason)` (~line 947). Mirror the ask pair with `permissionDecision: "deny"`.

7. Update `main()` (~line 986): add DENY branch first. Final order: DENY → DESTRUCTIVE → HEAD_MOVING → fallback ASK.

8. Syntax check: `python3 -c "import ast; ast.parse(open('/Users/henrychien/.claude/hooks/git_destructive_guard.py').read())"`.

**Phase 2: Test harness extension.**

9. Extend `Case` dataclass (line 23): add optional `dirty_setup: Callable[["GitFixture"], None] | None = None` field. Document that `dirty_setup` runs before the case and the harness resets `git reset --hard HEAD && git clean -fd` afterwards to isolate from neighbors.

10. Extend `run_case` (line 557): accept `"deny"` in `expect`. Parse `permissionDecision` from hook stdout JSON. Assert matches expected value.

11. Add `GitFixture.reset_clean(worktree_name: str)` helper that runs `git reset --hard HEAD && git clean -fd` in the named worktree — called automatically post-case when `dirty_setup` was used.

12. Add `GitFixture.make_dirty_tracked(worktree_name: str, path: str, content: str)` helper that modifies an existing tracked file (creates it on first call via an initial commit if needed).

**Phase 3: Tests.** See §7 — add 14 new cases covering deny/clean/linked/probe-failure/chained/cwd-drift scenarios.

**Phase 4: Verify.** `python3 /Users/henrychien/.claude/hooks/test_git_destructive_guard.py` → expect all passing. Live smoke: in a clean worktree, run `git checkout -b throwaway-smoke`; in a dirty worktree, run same and confirm deny.

## §7 Tests

**Phase 0 (baseline fix):**
- Update 10 failing tests' `reason_contains` from `"Ambiguous git checkout operand"` to `` "`git checkout <name>` is ambiguous" ``.

**Phase 3 new cases:**

1. `checkout_b_dirty_tree_deny` — main worktree with modified tracked file. Command: `git checkout -b new-branch`. Expect: deny, reason contains "BLOCKED" and "uncommitted tracked changes."

2. `switch_dirty_tree_deny` — main worktree dirty. Command: `git switch other-branch`. Expect: deny.

3. `checkout_single_operand_dirty_deny` — **THE INCIDENT REGRESSION.** `dirty_setup` creates + switches to `feat-foo` source branch, dirties a tracked file, then the case runs `git checkout main`. Models the real incident (feature branch → main from dirty tree), not just "main → main." Expect: deny. (Closes the residual gap Codex R1 flagged.)

4. `checkout_b_clean_tree_head_moving_ask` — clean main worktree. Command: `git checkout -b new-branch`. Expect: ask with HEAD_MOVING reason.

5. `switch_clean_tree_head_moving_ask` — clean main. Command: `git switch other-branch`. Expect: ask HEAD_MOVING.

6. `checkout_single_operand_clean_ask` — clean main. Command: `git checkout main`. Expect: ask ambiguous-checkout reason.

7. `checkout_b_dirty_linked_worktree_deny` — linked worktree dirty. Command: `git checkout -b new-branch`. Expect: deny (per §4.5 — applies regardless of linked/main).

8. `checkout_b_clean_linked_worktree_safe` — clean linked. Command: `git checkout -b new-branch`. Expect: allow (preserves current LINKED fast-path on clean tree).

9. `checkout_b_dirty_untracked_only_head_moving` — main worktree, only untracked files. Command: `git checkout -b new-branch`. Expect: ask HEAD_MOVING (untracked don't count per §4.2).

10. `restore_dirty_tree_ask_not_deny` — main dirty. Command: `git restore file.txt`. Expect: ask DESTRUCTIVE (not deny — restore stays at ASK per §3).

11. `reset_hard_dirty_tree_ask_not_deny` — main dirty. Command: `git reset --hard`. Expect: ask DESTRUCTIVE.

12. `checkout_b_invalid_gitdir_probe_failure_ask` — main worktree dirty, but `GIT_DIR=/nonexistent` in env. Command: `env GIT_DIR=/nonexistent git checkout -b new-branch`. Expect: ask with PROBE_FAILURE_REASON (not HEAD_MOVING, because `probe_worktree` fails BEFORE `check_working_tree_dirty` — per Codex R2 finding #4). Verifies the dirty-probe fallback doesn't break the existing probe-failure path.

13. `chained_stash_checkout_dirty_deny` — documents the over-block per §4.9. Command: `git stash && git checkout main`. Expect: deny. Comment: user workaround is to split into two commands.

14. `cd_outside_checkout_dirty_context_ask` — regression against the §6 Step 5 blocking fix. Command: `cd /tmp && git checkout main` (where main worktree is dirty). Expect: ask with DIRTY_CONTEXT_REASON (NOT deny) — shell cwd drifted, we can't trust the probe target. Mirror for `cd /tmp && git switch other-branch`. Ensures the dirty-context guard applies to both ambiguous-checkout and HEAD_MOVING paths.

Run: `python3 /Users/henrychien/.claude/hooks/test_git_destructive_guard.py`. Target: all existing passing + 14 new passing, 0 failures.

## §8 Risks & Out-of-Scope

Risks:
- Over-block `stash && checkout` chained pattern (§4.9). Workaround: split commands.
- Over-block dirty linked-worktree branch-carry workflow (§4.5). Accepted policy.
- Dirtiness probe adds ~50–200ms per HEAD-moving / ambiguous-checkout git invocation.
- Submodule false-positives if detached HEAD state reports dirty (§4.4). Future: consider `--ignore-submodules=dirty`.

Out-of-scope (explicit):
- Hard-blocking restore / reset --hard / clean — deliberate; they're user-initiated discard ops.
- Any change to the 18 CLAUDE.md repo-level branch rules.
- Root-cause why the incident's CLAUDE.md edits were specifically wiped after `git checkout main` succeeded. Codex R2 verified `pull --ff-only` REFUSES when mods conflict, so pull didn't do it. The post-checkout destructor is uncertain (parallel agent's Write, explicit `git restore`, forced checkout). No separate fix needed — the new DENY closes the entry point regardless of which compound path actually fires.

Changes from R1 (documented in R2):
- **§3 escalation table**: added `checkout <single-operand>` row → DENY on dirty (was deferred in R1 §6(c)).
- **§4.3**: rewritten with Codex R1's verified silent-preservation analysis.
- **§5 scope**: added `AnalysisResult.kind` field for ambiguous-checkout annotation.
- **§6 Phase 0**: added fix-10-failing-tests prerequisite.
- **§6 Step 4**: new — annotate ambiguous-single-operand via `kind` field.
- **§6 Step 5**: rewritten — handles ambiguous-checkout escalation path before HEAD_MOVING path.
- **§6 Phase 2**: new — test harness extension (`Case.expect="deny"`, `dirty_setup`, reset helpers).
- **§7**: added test #3 (the incident command), #6 (clean ambiguous), #9 (untracked only), renumbered. Test list 13 cases + Phase 0 fixups.
- **§2 line numbers**: refreshed (1006 → 1012, plus specific locations per Codex R1).

Changes from R2:
- **§6 Step 5** (BLOCKING fix per Codex R2 #1): `ctx.cwd_dirty/env_dirty` guard hoisted to apply to BOTH ambiguous-checkout and HEAD_MOVING paths. Without this, `cd /tmp && git checkout main` would probe the original hook_cwd instead of /tmp and potentially deny the wrong repo.
- **§6 Step 4** (Codex R2 #2): spelled out that `combine_result`'s equal-state reason-transfer branch must also preserve `kind` — `return AnalysisResult(current.state, new.reason, new.kind)`.
- **§7 Test #3** (Codex R2 #3): upgraded from "main dirty → checkout main" to real incident regression — `dirty_setup` creates + switches to `feat-foo` source branch, dirties file, THEN runs `git checkout main`.
- **§7 Test #12** (Codex R2 #4): expected reason changed from HEAD_MOVING to PROBE_FAILURE_REASON — invalid GIT_DIR fails probe_worktree first.
- **§7 Test #14** (new): regression for the §6 Step 5 fix — `cd /tmp && git checkout main` must return ASK with DIRTY_CONTEXT_REASON, not DENY. Mirror for switch.
- **§4.3 + §3 DENY reason** (Codex R2 #5): softened — R2 incorrectly claimed `pull --ff-only` clobbered. Codex R2 verified pull REFUSES when mods conflict. Rewrote to say the actual post-checkout destructor is uncertain (candidates: parallel Write, explicit restore, forced checkout). The checkout-time silent-preservation is the entry point regardless.
- **Header**: R2 → R3.
