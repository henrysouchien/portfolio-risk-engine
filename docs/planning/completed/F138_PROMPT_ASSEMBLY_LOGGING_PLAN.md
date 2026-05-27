> **✅ SHIPPED — closed by AI-excel-addin `48b62a82` + risk_module `b76faf04` (2026-05-21; see `docs/TODO_COMPLETED.md`). Moved from `docs/planning/` during 2026-05-26 docs cleanup.**

# F138 — Prompt assembly logging: wire `_check_budget` / `_emit_items_dropped` into all surfaces + emit `prompt_assembled` summary event

**Status:** v8 — **PASS on Codex round 7** (after rounds 1-6 FAIL on iterative refinement). v8 incorporates the 3 round-7 P2 cleanups: `memory_section` is A1/A2 only (not A3); B1-B5 section_sizes expanded to cover major interpolated variables (and 10% sum-check relaxed to 25% for profile-template builders); `_trim_text` stats use stripped-content length to match actual behavior. Ready for implementation handoff.

---

## Context

F115 raised the methodology + AGENT.md caps and introduced `_check_budget` in `AI-excel-addin/api/agent/shared/_prompt_budgets.py` — a structured logging primitive that fires `prompt_section_truncated` (ERROR) and `prompt_section_near_cap` (WARN). The primitive solves the F115-class silent-truncation failure — but it is currently wired into only **2 of 8+ prompt surfaces**, and there is **no per-assembly summary event**.

This is the operational-layer follow-up. The benchmark (Vals Config D) catches *regressions* point-in-time; runtime logging catches *drift, surprises, and the next F115-class bug as it happens*. F138 closes the gap so silent truncation becomes impossible going forward, across **both** the interactive chat path (Excel/web/Telegram/CLI) and the autonomous/skill path (cron, dev mode).

### Two truncation patterns to log distinctly

| Pattern | Mechanism | Detection event |
|---|---|---|
| **Final-truncate** | `content = content[:cap]` after building full text | `_check_budget` fires ERROR (over-cap) / WARN (near-cap) |
| **Pre-cap items-dropped** | Loop selects items; `if used + len(item) > cap: return/break` before exceeding cap | `_emit_items_dropped` fires WARN with attempted-vs-included counts |

`_check_budget` does NOT fire on the final assembled section for pre-cap items-dropped sites because by construction the final section is under-cap. Hence the new `_emit_items_dropped` helper.

One operationally-special site: `research/context.py:_trim_text` is final-truncate per call (each message slices to cap), but firing `_check_budget` per message would be high-volume noise. Aggregated per-`_format_context` invocation as items-dropped (one truncated message = one dropped item).

### Architecture

**Tree A — Interactive chat** (`api/agent/shared/system_prompt.py`)
- `build_system_prompt` (line 1488) → `_build_system_prompt_sections` (line 1357) chokepoint; research bypass at **line 1495**
- `build_system_prompt_blocks` (line 1458) → same chokepoint; research bypass at **line 1465**
- `build_sdk_system_prompt` (line 1508) → **separate**, bypasses chokepoint entirely
- Research bypass routes converge at `build_research_prompt_stack` (`research/policy.py:87`).

**Tree B — Autonomous / skill** (`api/agent/profiles/{analyst,advisor}.py`)
- `analyst.py:build_system_prompt` (line 691) / `build_skill_system_prompt` (line 723) / `build_dev_system_prompt` (line 818)
- `advisor.py:build_system_prompt` (line 300) / `build_skill_system_prompt` (line 327)

`build_workspace_context` is built by the **orchestration layer** (`autonomous/entry.py:495,651,764,845`; `interactive/runtime.py:874`) BEFORE the profile builder is called. The profile builder receives `workspace_context` as a string parameter; it does not call `build_workspace_context()` itself.

This is why workspace events and top-level events fire from different layers. They are **independent** events. Operators correlate via **best-effort timestamp + profile** match in log queries. `user_id` / `session_id` is NOT in the event today and would require MDC/contextvar threading not currently in the codebase — explicitly out of scope for v1. Honest framing: low-volume operations are fine; concurrent multi-user investigation may need a follow-up that adds session context to the log pipeline (one option: log filter that injects request-scoped session ID via contextvars).

### Full surface inventory

**Final-truncate sites** (need `_check_budget`):

| # | Surface | Location | Cap | Wrapped? |
|---|---|---|---|---|
| 1 | Methodology files | `system_prompt.py:161` | 16,000 | ✅ F115 |
| 2 | Agent instructions | `system_prompt.py:125` | 16,000 | ✅ F115 |
| 3 | Analyst `MEMORY.md` | `system_prompt.py:84` `_load_persistent_memory_text` | 2,000 | ❌ silent |
| 4 | Identity persona | `system_prompt.py:180` `_load_identity_persona` | 2,000 | ❌ silent |
| 5 | Advisor identity / advisor `MEMORY.md` | `advisor.py:393` `_read_workspace_text` | 2,000 each | ❌ silent |

**Pre-cap items-dropped sites** (need `_emit_items_dropped`):

| # | Surface | Location | Cap | Wrapped? |
|---|---|---|---|---|
| 6 | Recent-context memory items | `system_prompt.py:300-349` `_build_memory_section` | env-var | ❌ silent |
| 7 | Skill prior-output context | `agent/skills/indexer.py:84-143` `build_prior_output_context` (line 140: `if len(built) + len(chunk) > max_chars: return built`) | 800 | ❌ silent |
| 8 | Research per-message content (aggregated) | `research/context.py:8,49,54` `_trim_text` via `_format_context` | 200 active / 150 reader | ❌ silent |

**Non-cap file reads** (contribute to total prompt size; labeled in summary event):

| # | Surface | Notes |
|---|---|---|
| 9 | Profile prompt templates | `profiles/prompt_loader.py:12` (lru-cached). Labeled `template_<profile>` in summary event. No truncation. |
| 10 | Skills catalog | `system_prompt.py:248` `_build_skills_section` frontmatter parse. Labeled `skills_catalog`. Appears in summary event's `sections` dict; not subject to a cap check (no truncation). |

### Assembly entry points (9 top-level events + 2 workspace events)

| ID | Profile label | Entry point | Notes |
|---|---|---|---|
| A1 | `analyst_chat` | `system_prompt.py:1488 build_system_prompt` | chokepoint; research bypass line 1495 → A4/A5 |
| A2 | `analyst_chat` | `system_prompt.py:1458 build_system_prompt_blocks` | chokepoint; research bypass line 1465 → A4/A5 |
| A3 | `analyst_sdk` | `system_prompt.py:1508 build_sdk_system_prompt` | separate path |
| A4/A5 | `research` | `research/policy.py:87 build_research_prompt_stack` | one event; text variant (`build_research_prompt_text`, line 107) calls stack |
| B1 | `analyst` | `profiles/analyst.py:691 build_system_prompt` | — |
| B2 | `analyst_skill` | `profiles/analyst.py:723 build_skill_system_prompt` | — |
| B3 | `analyst_dev` | `profiles/analyst.py:818 build_dev_system_prompt` | `_for_gateway` (line 857) is a wrapper; no extra event |
| B4 | `advisor` | `profiles/advisor.py:300 build_system_prompt` | — |
| B5 | `advisor_skill` | `profiles/advisor.py:327 build_skill_system_prompt` | — |
| W1 | `workspace_analyst` | `system_prompt.py:358 build_workspace_context` | called from orchestration layer; emits before B1-B3 fire |
| W2 | `workspace_advisor` | `advisor.py:407 build_workspace_context` | called from orchestration layer; emits before B4-B5 fire |

**Workspace section keys differ between analyst and advisor:**
- Analyst workspace (`system_prompt.py:358`) builds: `agent_instructions` (via `_build_memory_instructions_section` → `_load_agent_instructions`), `methodology`, `skills_catalog`, `persistent_memory_analyst`. **Does NOT include `identity_persona`** (interactive identity section only) **and does NOT include `memory_section`** (recent-context items, also interactive-only — Codex round-5 correction).
- Advisor workspace (`advisor.py:407`) builds: `advisor_identity`, `persistent_memory_advisor`.
- `memory_section` (recent-context items via `_build_memory_section`) is built ONLY in the interactive chat path via `_build_system_prompt_sections` → **A1/A2 events only** (A3 `build_sdk_system_prompt` is a separate path that does NOT call `_build_memory_section`). It is NOT in W1, NOT in A3.

### Outcome

- Every final-truncate site is wrapped with `_check_budget`. Over-cap → ERROR, near-cap → WARN.
- Every pre-cap items-dropped site emits `prompt_section_items_dropped` (WARN) when items skipped.
- Every prompt assembly fires exactly one `prompt_assembled` event at INFO with `{profile, sections, total_chars}`. No `assembly_id`; events from different layers correlate via best-effort timestamp + profile match in log queries (limitation acknowledged for concurrent multi-user; see Risks).
- F116/F117 surface as ERROR in prod from day 1 (intentional; user-approved 2026-05-21).
- Per-surface unit tests assert each wrapped site fires the right events. Per-entry-point integration tests (11 of them) assert each assembly fires exactly one `prompt_assembled` event. Code review at PR boundary catches new truncation sites. Runtime logs catch drift on already-instrumented sites. No CI-level "every surface accounted for" test — its label-contract was the source of Codex's repeated round-2-through-6 findings, and the cost-benefit didn't justify the design.

### Intentional omissions (NOT silent truncation)

Three sites drop content by design, not by cap exhaustion. Documenting so they're not mistakenly logged as truncation:

- **`build_prior_output_context` `max_entries=5`**: limits prior skill outputs by count (line 115). Default is a visible recency window, not silent failure. NOT logged.
- **`_format_context` `active_messages[-20:]`** (research/context.py:48): shows last 20 messages. Visible recency window. NOT logged.
- **`_format_context` `reader_messages[-10:]`** (research/context.py:53): shows last 10 messages. Visible recency window. NOT logged.

If a future need arises to surface these (e.g., operator wants to know if a research thread has 100+ messages of which we only show 20), add a separate `prompt_section_recency_clipped` event then. Out of scope for v1.

---

## Design

### 1. Extend `_prompt_budgets.py` with two helpers

```python
# api/agent/shared/_prompt_budgets.py

# Privacy invariant: permitted log fields = `surface` (label), `path` (Path),
# `size`/`cap`/`pct`/`dropped`/`attempted_*`/`included_*` (ints), `sections` (dict[str, int]),
# `total_chars` (int), `profile` (str). Forbidden: content excerpts, snippets, per-item text.
# Paths leak workspace structure (ticker dirs, identity names) — accepted because paths are
# already in F115 logs and log destinations are access-controlled.

def _emit_prompt_assembly_summary(
  profile: str,
  sections: dict[str, int],
  total_chars: int,
) -> None:
  logger.info(
    "prompt_assembled",
    extra={"profile": profile, "sections": sections, "total_chars": total_chars},
  )


def _emit_items_dropped(
  surface: str,
  attempted_items: int,
  included_items: int,
  attempted_chars: int,
  included_chars: int,
  cap: int,
) -> None:
  """Fires WARN when a section builder selects items under a budget and drops the rest
  before exceeding cap. Silent on no-drop."""
  if included_items >= attempted_items:
    return
  logger.warning(
    "prompt_section_items_dropped",
    extra={
      "surface": surface,
      "attempted_items": attempted_items,
      "included_items": included_items,
      "attempted_chars": attempted_chars,
      "included_chars": included_chars,
      "cap": cap,
      "dropped_items": attempted_items - included_items,
    },
  )
```

### 2. Wire truncation events into silent surfaces

#### 2a. Final-truncate → `_check_budget`

| Surface | Site | Call |
|---|---|---|
| Analyst MEMORY.md | `system_prompt.py:84` `_load_persistent_memory_text`, before line 109 | `_check_budget(f"persistent_memory_{state_subdir}", memory_file, content, max_chars)` |
| Identity persona | `system_prompt.py:180` `_load_identity_persona`, before line 197 | `_check_budget("identity_persona", identity_file, content, _IDENTITY_MAX_CHARS)` |
| Advisor identity / MEMORY.md | `advisor.py:393` `_read_workspace_text` | Add `label: str` param; call `_check_budget(label, path, content, max_chars)` before line 404. Call sites pass `label="advisor_identity"` (line 415), `label="persistent_memory_advisor"` (line 419) |

#### 2b. Pre-cap items-dropped → `_emit_items_dropped`

##### 2b.i. `_build_memory_section` (`system_prompt.py:300-355`)

The items being budgeted are `memories` (built at lines 317-335), not `lines` (which is just the header + appended formatted-memory strings). Correct counter design:

- Pre-loop (after `memories` is fully assembled at line 336):
  - `attempted_items = len(memories)`
  - `attempted_chars = sum(len(_format_memory_line(item)) for item in memories)` — where `_format_memory_line` mirrors the line-format logic at lines 343-348 (extract into a helper, both for testability and so attempted_chars matches the actual loop body)
- Inside loop, track `included_items` and `included_chars` only when a line is appended (not when `break` fires).
- After loop:
  - `_emit_items_dropped("memory_section", attempted_items, included_items, attempted_chars, included_chars, max_chars)`

##### 2b.ii. `build_prior_output_context` (`indexer.py:84-143`)

The early-return at line 140 (`if len(built) + len(chunk) > max_chars: return built`) is the items-dropped point.

Pre-loop: `attempted_items = sum(len(entries) for _, entries in sections if entries)`. Track `attempted_chars` by summing estimated chunk lengths per candidate (compute the would-be `chunk` string per entry, sum lengths). Inside loop: `included_items` and `included_chars` increment when chunk is added. Emit `_emit_items_dropped("skill_prior_outputs", ...)` immediately before the early `return built` AND at function tail (only one fires — early-return path uses partial counts; tail uses full counts).

##### 2b.iii. `_trim_text` aggregate (`research/context.py:8,49,54`)

Inside `_format_context`, for each of `active_messages[-20:]` and `reader_messages[-10:]`, compute attempted/included counters where a truncated message = dropped item:

```python
def _aggregate_trim_stats(messages, cap):
  # Note: _trim_text strips content before truncating and appends "..." on truncation.
  # We compute attempted/included on the STRIPPED content length to match _trim_text's
  # actual behavior. The "..." suffix (3 chars) is accepted slop in included_chars.
  attempted_items = len(messages)
  stripped_lengths = [len(str(m.get('content') or '').strip()) for m in messages]
  attempted_chars = sum(stripped_lengths)
  truncated_count = sum(1 for length in stripped_lengths if length > cap)
  included_items = attempted_items - truncated_count
  included_chars = sum(min(length, cap) for length in stripped_lengths)
  return attempted_items, included_items, attempted_chars, included_chars

# After computing both:
_emit_items_dropped("research_context_messages", *_aggregate_trim_stats(active_messages[-20:], 200), 200)
_emit_items_dropped("research_context_reader_messages", *_aggregate_trim_stats(reader_messages[-10:], 150), 150)
```

Tests for §2b.iii should use stripped-content-length math (matching `_trim_text`'s actual behavior), with a small slop tolerance for the `"..."` 3-char suffix.

### 3. Wire summary event into entry points

Pattern: each entry point collects `{label: char_count}` during assembly, fires `_emit_prompt_assembly_summary(profile, section_sizes, total_chars)` once before return.

#### 3a. Chokepoint return contract

Change `_build_system_prompt_sections` (system_prompt.py:1357) return type from `(static, dynamic)` to `(static, dynamic, section_sizes)` where `section_sizes: list[tuple[str, int]]` is ordered. Internal helper:

```python
def _append_with_size(sections: list[str], sizes: list[tuple[str, int]], label: str, content: str) -> None:
  if content:
    sections.append(content)
    sizes.append((label, len(content)))
```

Each `_build_*` call uses `_append_with_size` with an explicit label. Callers (`build_system_prompt`, `build_system_prompt_blocks`) emit summary with `profile="analyst_chat"`. Research-bypass paths skip the summary (research entry handles its own).

#### 3b. Per-entry-point wiring

| Entry | Implementation |
|---|---|
| A1/A2 | Caller of chokepoint emits `_emit_prompt_assembly_summary("analyst_chat", dict(section_sizes), total_chars)` after the join into final text. Research bypass returns early; no event from A1/A2 (handled by A4/A5). |
| A3 | `build_sdk_system_prompt` assembles independently; tracks section_sizes inline; emits with `profile="analyst_sdk"`. |
| A4/A5 | At top of `build_research_prompt_stack`: pre-coerce optional IDs into locals (`_coerce_optional_int(context.get("thread_id"))`, etc.) so coercion failures raise before any work. Build blocks; emit with `profile="research"`. `build_research_prompt_text` (line 107) calls stack and returns joined text — no additional event. |
| B1-B5 | Each profile builder tracks section_sizes inline. Major interpolated variables get their own key: `template_<profile>`, `tool_catalog`, `tool_packs`, `workspace_context`. For B1 (analyst) also include `available_agents_section`, `dev_mode_section`, `tickers_dir`. For B2/B5 (skill builders) also `skill_content`, `prior_outputs`, `output_path`. Minor interpolations (`today`, `market_status`, `max_turns`, `deferred_servers` — short fixed-format strings) are folded into `template_<profile>` for simplicity. Emit with profile = `<builder-label>`. |

#### 3c. Workspace events (W1, W2)

`build_workspace_context` is called by the orchestration layer (`autonomous/entry.py`, `interactive/runtime.py`) BEFORE the profile builder. It is an independent assembly site.

Inside `system_prompt.py:358 build_workspace_context` (analyst):
- Track section_sizes for `agent_instructions`, `methodology`, `skills_catalog`, `persistent_memory_analyst` (whichever fire).
- Emit `_emit_prompt_assembly_summary("workspace_analyst", section_sizes, total_chars)` before return.
- Note: `memory_section` is NOT built here (interactive-only via `_build_system_prompt_sections`).

Inside `advisor.py:407 build_workspace_context`:
- Track section_sizes for `advisor_identity`, `persistent_memory_advisor`.
- Emit `_emit_prompt_assembly_summary("workspace_advisor", section_sizes, total_chars)`.

Workspace events fire from inside `build_workspace_context` itself. Top-level B-builder events fire later from inside the B-builders. They are independent events; loose-join via timestamp + profile in operator log queries is the explicit design choice for v1. Tight join via shared ID is deferred (would require changing the orchestration-layer signature).

### 4. Privacy invariant

Documented as docstring at top of `_prompt_budgets.py` (see §1). Content invariant (no snippets) + metadata caveat (paths leak workspace structure — accepted). Enforced in code review.

---

## Tests

Under `AI-excel-addin/tests/agent/shared/`.

### 5a. Unit tests per newly-wrapped surface

| Surface | Cases |
|---|---|
| 2a final-truncate (4 surfaces) | Over-cap → ERROR `prompt_section_truncated`. ≥80% → WARN `prompt_section_near_cap`. Under-cap → silent. |
| 2b.i `_build_memory_section` | Items dropped → one WARN with `attempted > included`. No drop → silent. |
| 2b.ii `build_prior_output_context` | Same pattern. Surface = `skill_prior_outputs`. Test both early-return path AND fits-all-items path. |
| 2b.iii `_trim_text` aggregate | ≥1 truncated message → one WARN per surface (`research_context_messages`, `research_context_reader_messages` independently). No truncation → silent. |

### 5b. Unit tests — helpers

- `_emit_prompt_assembly_summary` → one INFO `prompt_assembled` event with expected fields.
- `_emit_items_dropped` with `attempted > included` → one WARN; with `attempted == included` → silent.

### 5c. Integration tests — one per entry point (11 total: 9 top-level + 2 workspace)

For each entry:
1. Build via the public entry point with fixture context.
2. **Capture log records with explicit filter:** `[r for r in caplog.records if r.message == "prompt_assembled" and r.__dict__.get("profile") == <expected>]`. Length must be exactly 1.
3. Assert `total_chars > 0`; `sections` has ≥ N expected keys. Sum-of-sections check: within 10% of `total_chars` for A1/A2/A3/A4/A5/W1/W2 (well-bounded section sets); within **25%** for B1-B5 because profile templates may include minor interpolations folded into `template_<profile>` plus join whitespace.
4. For A4/A5: assert ONE `profile="research"` event total when calling `build_research_prompt_text` (which calls `build_research_prompt_stack`). Include malformed `thread_id` / `tab_context` fixture; assert `_coerce_optional_int` raises BEFORE summary emission (no event leaked, no partial event).
5. For B1-B5: top-level event has `workspace_context` key in `sections`. Workspace event (W1 or W2) is a SEPARATE assertion in its own test (5c step on W1/W2). They're independent in v1; no shared-ID join assertion.

### 5d. No CI surface-coverage test (decided after rounds 2-6)

Earlier plan versions proposed a CI-level "every surface label accounted for" coverage test. After Codex repeatedly found edge cases in its design across rounds 2-6 — AST pattern false-positives, list-vs-string slicing, `max_entries` vs `max_chars`, label-contract mismatches between cap events and `prompt_assembled.sections` keys — the cost-benefit no longer justified the design. **Dropped.**

What replaces it: per-surface unit tests (5a) verify each wrapped site fires correctly; per-entry-point integration tests (5c) verify each assembly emits a summary event with the expected section keys. New truncation sites added in future PRs are caught by code review at the PR boundary. Runtime logs catch drift on already-instrumented sites.

This is honest about the limit: the design relies on humans noticing new truncation sites at PR time. F138's job is to make existing silent truncation impossible going forward; ensuring future code stays correct is a code-review discipline, not a CI guardrail.

### 5e. No Vals run required

Observability infra; no methodology/content change.

---

## Risks / decisions

| Risk | Decision |
|---|---|
| F116/F117 ERROR noise day 1 | Land logging first; ERROR is the operational signal. User-approved. |
| Summary log level INFO | Default INFO. Revisit if multi-user volume becomes a real cost. |
| `_read_workspace_text` `label` param | Add param. Codex may push back; either acceptable. |
| Workspace + top-level events correlation | Best-effort timestamp + profile match. `user_id` / `session_id` is NOT in events today; adding it would require MDC/contextvar pipeline work — explicitly out of scope for v1. Sufficient for low-volume ops; concurrent multi-user investigation needs a follow-up. |
| Token vs char counts | Char count. |
| Metadata in `path` field | Accepted. |
| No CI surface-coverage guardrail | Per-surface unit tests + per-entry-point integration tests + code review at PR boundary + runtime logs. The "every surface accounted for" CI test was attempted in rounds 2-6 but every design had label-contract or pattern-detection edge cases. Cost-benefit doesn't justify. |
| `_coerce_optional_int` raise behavior | Pre-coerce at top of `build_research_prompt_stack` (raise before any summary emission). |
| `prompt_loader.py` templates not in scope for truncation events | Templates don't truncate (lru-cached `.md` reads). Labeled in summary event via top-level builder's section_sizes. No cap check. |

---

## Codex review evolution (rounds 1-6 → v7)

Six rounds of Codex review. The CORE design (wire `_check_budget` into final-truncate sites, `_emit_items_dropped` into pre-cap items-dropped sites, emit `prompt_assembled` summary at each entry point) has been stable since v3. Codex's iterative findings progressively:

- **Round 1**: Expanded surface inventory from interactive-only to interactive + autonomous + research; expanded entry points from ~5 to 11.
- **Round 2**: Identified `_build_memory_section` and `build_prior_output_context` as pre-cap items-dropped pattern (not final-truncate); introduced `_emit_items_dropped` helper. Caught `_build_system_prompt_sections` return-contract issue.
- **Round 3**: Killed `assembly_id` cross-layer join (workspace_context built in orchestration layer, IDs couldn't join). Identified analyst workspace inventory error (no `identity_persona`).
- **Round 4**: Killed AST coverage test design (Pattern A/B/C kept hitting edge cases). Reframed correlation honestly (no `user_id` in events).
- **Round 5**: Fixed `_build_memory_section` counter design (budgeted items are `memories`, not `lines`). Caught analyst workspace `memory_section` error.
- **Round 6**: Killed surface-label CI coverage test entirely (label-contract mismatches between cap events and summary sections kept producing edge cases). Per-surface unit tests + per-entry-point integration tests + code review at PR boundary are the protection model.

---

## Out of scope (deliberately)

- Persisting full assembled prompts to a queryable store.
- F116 / F117 content cleanup. Separate items; F138 ERROR output drives them.
- F136 investigation. F138 provides data foundation.
- Token counts (char count sufficient).
- Per-rule provenance.
- **Tight cross-layer `assembly_id` join** — requires changing `autonomous/entry.py` and `interactive/runtime.py` signatures to thread an ID through the orchestration → workspace_context → profile-builder call chain. Defer.
- **CI-level surface-coverage test** (attempted in rounds 2-6; dropped). Protection via unit + integration tests + code review.
- **User/session ID in log events** — requires MDC/contextvar pipeline not currently in codebase. Defer.

---

## Files touched

| Path | Change |
|---|---|
| `api/agent/shared/_prompt_budgets.py` | Add `_emit_prompt_assembly_summary`, `_emit_items_dropped`; privacy-invariant docstring |
| `api/agent/shared/system_prompt.py` | Wire 2a final-truncate sites (3); redesign 2b.i with items-dropped; change `_build_system_prompt_sections` return type to `(static, dynamic, section_sizes)`; wire summary in `build_system_prompt`, `build_system_prompt_blocks`, `build_sdk_system_prompt`; wire summary in `build_workspace_context` (analyst path) |
| `api/agent/profiles/advisor.py` | Refactor `_read_workspace_text` (label param); wire summary in `build_workspace_context` (advisor path), `build_system_prompt`, `build_skill_system_prompt` |
| `api/agent/profiles/analyst.py` | Wire summary in `build_system_prompt`, `build_skill_system_prompt`, `build_dev_system_prompt` |
| `api/research/policy.py` | Pre-coerce optional IDs at top of `build_research_prompt_stack`; wire summary event |
| `api/research/context.py` | Wire `_emit_items_dropped` aggregates in `_format_context` for active + reader message paths |
| `api/agent/skills/indexer.py` | Wire `_emit_items_dropped` in `build_prior_output_context` (NOT `_check_budget`) |
| `tests/agent/shared/` | Unit (5a, 5b) + integration (5c, 11 entry points) + fixtures. No CI surface-coverage test (see §5d). |

---

## Implementation handoff

- **Tool:** `mcp__codex__codex`
- **`approval-policy`:** `"never"`
- **`sandbox`:** `"workspace-write"`
- **`cwd`:** `/Users/henrychien/Documents/Jupyter/AI-excel-addin`
- **Model / reasoning:** inherit from `~/.codex/config.toml`
- **Brief:** this plan file (v8) + explicit instruction: iterate until all tests pass; do not modify F115 cap values; preserve existing `_check_budget` ERROR/WARN behavior unchanged; respect privacy invariant; do not change orchestration-layer signatures in `autonomous/entry.py` or `interactive/runtime.py`.
