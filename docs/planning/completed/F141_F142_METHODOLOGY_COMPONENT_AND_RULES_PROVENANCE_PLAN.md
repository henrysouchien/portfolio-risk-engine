> **✅ SHIPPED — closed by AI-excel-addin `f0a29f72` + risk_module `04df6394` (2026-05-22; see `docs/TODO_COMPLETED.md`). Moved from `docs/planning/` during 2026-05-26 docs cleanup.**

# F141 + F142 — Methodology as first-class prompt component + rules-provenance schema

**Status:** v4 — **PASS on Codex round 3** (after rounds 1-2 FAIL on iterative refinement). v4 incorporates 3 round-3 polish items: unique-rule-id and created≤last_reviewed schema validators, `schema_version: Literal["1.0"]`, parent-`ProfileConfig.name == "analyst"` clarification for the sub-agent guard, stale-rule INFO cleanup. Ready for implementation handoff.

---

## Context

### What F138 left open

F138 shipped the runtime/observation layer. The original prompts-as-code question had a broader scope:

| Layer | Question | F138 status | This plan |
|---|---|---|---|
| Runtime | Did the prompt assemble correctly? Did any section truncate? | ✅ shipped (F138 events) | — |
| Change-time / provenance | What is this rule? When was it added? Why does it exist? Has it been reviewed lately? | ❌ partial (only benchmark-shipped rules anchored) | F142 |
| Change-time / architecture | Is methodology a coherent prompt component or embedded inside `workspace_context`? | ❌ embedded (F140 made it lazy; structural split still pending) | F141 |
| Pre-merge eval | When a rule changes, do focused Vals questions re-run automatically? | ❌ depends on F142 (need rule→test mapping first) | downstream |
| Rule effectiveness | "Rule in context but not applied" — does the rule actually fire? | ❌ open as F136 | downstream |

### Methodology files — two kinds

```
api/memory/workspace/notes/methodology/
├── _answer-fidelity.md         (15,376 chars, ~31 bullet rules, ALWAYS INJECTED into prompt)
├── _playbook.md, _template.md, black_book.md, investment_process.md, software_valuation.md  (reference docs, not injected)
└── {decision-making,foundation,fundamental-analysis,pitch,risk-management,strategic-evaluation,valuation-modeling,wiki}/  (unit files with YAML frontmatter validated by schema/methodology.py — read on demand)
```

Unit-level YAML frontmatter is validated by **`schema/methodology.py`** (TOP-LEVEL, not `api/schema/`). Tests in `tests/schema/test_methodology.py`. Mirror this pattern for rules.

### Where rule-level metadata exists today

`_answer-fidelity.md` has 9 anchored rules, all benchmark-derived:
```html
<!-- shipped-rule id="percent_rounding_single_step" q="q050" commit="126afaff" -->
- When the final answer requires one-decimal percent display...
```

~22 unanchored rules (foundational principles) have no metadata. Identity is coupled to a benchmark question via `q=`. No `created` date, `category`, `last_reviewed`.

### Why pair F141 + F142

F141 = **how methodology gets loaded** (architecture). F142 = **what's inside methodology and how we track it** (content). Together they make methodology a coherent first-class component with queryable internal structure — the actual answer to "treat prompts like code."

### Production load paths (Codex round-1 re-audit — full inventory)

```
build_workspace_context() callers:
  api/agent/interactive/runtime.py:896      — interactive DEV mode (not main chat — Codex round-1 correction)
  api/agent/interactive/runtime.py:1013     — workspace_context_resolver, fed to named sub-agent injection
  api/agent/shared/tool_handlers.py:1087    — named sub-agent injection consumer (uses the resolved workspace)
  api/agent/autonomous/runner.py:394        — fallback assembly if entry didn't pre-build
  api/agent/autonomous/entry.py:495         — autonomous run-once path
  api/agent/autonomous/entry.py:651         — autonomous skill path
  api/agent/autonomous/entry.py:764         — autonomous dev task path
  api/agent/autonomous/entry.py:845         — autonomous dev skill path
  api/agent/profiles/{analyst,advisor}.py   — profile facade returns

_build_methodology_prompt_section() callers (today):
  api/agent/shared/system_prompt.py:410     — inside build_workspace_context (the embedding F141 removes)
  api/agent/shared/system_prompt.py:1472    — inside _build_system_prompt_sections (interactive chat chokepoint)
```

Methodology reaches the prompt via TWO paths today: directly at the interactive chokepoint, AND indirectly via `workspace_context` (autonomous + named sub-agents + interactive dev). F141 turns this into a single explicit path per consumer, mediated by a new public composition API.

---

## Scope

### In scope

**F141 — methodology as first-class prompt component:**

1. **Introduce a public composition API** in `api/agent/shared/system_prompt.py`:
   ```python
   def build_methodology_context() -> str: ...
   ```
   Wraps the existing `_build_methodology_prompt_section()`. Public callers use this; the private helper stays internal.

2. **Remove the methodology call from `build_workspace_context`** (`system_prompt.py:401-411`). After this, workspace_context = `agent_instructions + skills_catalog + persistent_memory_<subdir>` only.

3. **Add `methodology_context=` parameter to analyst profile builders** (Codex round-2 P1). Analyst profile builders at `profiles/analyst.py:692` (`build_system_prompt`), `:743` (`build_skill_system_prompt`), `:864` (`build_dev_system_prompt`) currently accept only `workspace_context=""` and report a single combined section in F138's `prompt_assembled` event. Without a separate parameter, methodology would be hidden inside the workspace bucket.

   New signatures (additive — `methodology_context=""` defaults preserve callers that don't yet pass it):
   ```python
   def build_system_prompt(today, market_status, briefing_file, tool_catalog, tickers_dir,
                            tool_packs_section="", workspace_context="",
                            methodology_context="") -> str: ...
   ```

   Each builder:
   - Injects methodology adjacent to workspace_context in the assembled prompt (template placeholder)
   - Reports both as separate sections in its `prompt_assembled` event: `{..., workspace_context: N, methodology: M}`

4. **Composition owners — single site per execution path**. Audit table:

| Consumer | Today | After F141 | Owner site |
|---|---|---|---|
| Interactive chat (main, non-research) | Direct call at `system_prompt.py:1472` (chokepoint) | Switch to public `build_methodology_context()`; chokepoint stays the owner | `system_prompt.py:1472` |
| Interactive dev mode | Inherits via `workspace_context` at `runtime.py:896` | Add explicit `methodology_context=build_methodology_context()` at the analyst dev builder call site | `runtime.py:896` |
| Named sub-agents (analyst profile only — Codex round-2 P2 guard) | Inherits via `workspace_context` resolver at `runtime.py:1013` → injected at `tool_handlers.py:1087` | Pass `methodology_context=build_methodology_context()` to `build_skill_system_prompt` ONLY when the **parent `ProfileConfig.name == "analyst"`** (NOT the sub-agent's own `skill_profile.name`, which is the named-skill metadata). Other profiles (advisor, future non-analyst) MUST NOT auto-inherit methodology. Profile-keyed guard at the call site. | `tool_handlers.py:1087` |
| Autonomous run-once | Inherits via `workspace_context` at `entry.py:495` | Add explicit `methodology_context=build_methodology_context()` when invoking analyst builder | `entry.py:495` |
| Autonomous skill | Inherits via `workspace_context` at `entry.py:651` | Same as above (analyst builder) | `entry.py:651` |
| Autonomous dev task | Inherits via `workspace_context` at `entry.py:764` | Add `methodology_context=build_methodology_context()` to `build_dev_system_prompt` call | `entry.py:764` |
| Autonomous dev skill | Inherits via `workspace_context` at `entry.py:845` | Same as above | `entry.py:845` |
| `autonomous/runner.py:394` fallback | Inherits via `workspace_context` fallback | Do NOT add methodology here. Entry paths pre-build and pass it through; the runner fallback path is only hit when entry didn't pre-build. Single composition owner per path = entry, not runner. | none — explicitly skip |
| Advisor (any path) | Advisor `workspace_context` does not include methodology today | Unchanged. Advisor builders do NOT accept `methodology_context=`. | none |

5. **Update F138 prompt assembly summary events**:
   - `workspace_analyst` event: `sections` shrinks to `{agent_instructions, skills_catalog, persistent_memory_analyst}` (no methodology).
   - `analyst_chat` event: `sections` still has `methodology` (chokepoint, unchanged).
   - Analyst autonomous events (B1/B2/B3) and interactive dev event: `sections` gains a `methodology` key alongside `workspace_context`, separately sized.
   - Named sub-agent event (B5 family) when on analyst profile: `methodology` is reported separately; on advisor profile, absent.

6. **Update integration tests** in `tests/agent/shared/test_prompt_assembly_summary.py` for the new section composition across all affected entry points (analyst paths gain `methodology` key; advisor unchanged).

**F142 — rules-provenance schema and tooling:**

1. **Schema at `schema/rules.py`** (TOP-LEVEL, mirroring `schema/methodology.py`), not `api/schema/`. Tests in `tests/schema/test_rules.py`.

2. **Schema design (Option C):** lightweight in-file anchor + external `_rules.yaml` registry. Codex round-1 confirmed Option C; B and D are documented alternatives but not selected.

3. **Apply to all ~31 rules in `_answer-fidelity.md`** under the governed sections (see §2c). Foundational principles get tracked alongside benchmark-derived rules.

4. **Decouple identity from benchmark evidence:** `q=` field migrates from identity slot to an `evidence:` list. `evidence` accepts multiple types and may be empty for purely principled rules.

5. **Multi-category rules:** `categories: list[Literal[...]]` (not a single `str`) since several rules span source-routing + numeric-precision + basis-discipline. Add `source-fidelity` as a 7th category (Codex round-1 P2).

6. **Validation tests** + AGENTS.md required smoke guardrail (`PYTHONHASHSEED=0 python3 schema/smoke_accuracy_guardrail.py`, blocking).

7. **Minimal query tooling:** one CLI script. Richer tooling deferred.

### Out of scope (deferred to follow-ups)

- Pre-merge smoke-eval gate (file as F143 after this lands; needs rule→test mapping that F142 provides).
- F136 investigation (rule-in-context-but-not-applied).
- Diff-time cap-headroom check in PRs.
- Migration of other always-injected files (none today besides `_answer-fidelity.md`).
- Unit-file frontmatter changes (already validated by `schema/methodology.py`).
- Reference doc restructure (`_playbook.md`, `_template.md`, `black_book.md`).
- MCP tool for agent self-querying its own rules (CLI suffices for v1).

---

## Design

### Part 1 — F141 architecture

#### 1a. Public composition API

Add to `api/agent/shared/system_prompt.py`:

```python
def build_methodology_context() -> str:
  """Public composition entry point for the methodology section.

  Returns the assembled methodology prompt block (currently loaded from
  `_answer-fidelity.md` via `_ANALYST_METHODOLOGY_PROMPT_FILES`).
  Callers in autonomous, interactive-dev, named sub-agent, and chokepoint
  paths use THIS function; do not call the private `_build_methodology_prompt_section`
  directly from outside this module.
  """
  return _build_methodology_prompt_section()
```

Private helper stays internal. Public wrapper is the only external entry point. This gives the "first-class component" the plan promises.

#### 1b. Workspace context shrinks

`build_workspace_context` (`system_prompt.py:401-411`) returns `agent_instructions + skills_catalog + persistent_memory_<subdir>` only. Methodology is no longer included.

#### 1c. Composition boundaries (single owner per path)

Per the audit table in §Scope. **Each path adds methodology at EXACTLY one site.** The autonomous runner.py:394 fallback explicitly does NOT add methodology — entry.py paths own composition for autonomous.

For named sub-agents: composition happens in the sub-agent system-prompt builder, called from `tool_handlers.py:1087`. The current pattern is that `workspace_context` is resolved upstream and injected. After F141, the same builder gets methodology via `build_methodology_context()` adjacent to the workspace inject, not as part of workspace_context.

If Codex impl-phase finds a cleaner composition pattern (e.g., a shared `assemble_analyst_prompt_parts()` helper), prefer that over duplicating `build_methodology_context()` calls at multiple sites. Plan documents the OWNERSHIP boundary; Codex picks the cleanest implementation.

#### 1d. F138 summary event updates

`prompt_assembled` events change shape:
- `workspace_analyst` → `{agent_instructions, skills_catalog, persistent_memory_analyst}` (no methodology)
- `analyst_chat` → unchanged (methodology still present via chokepoint)
- Autonomous entry-point events (B1/B2/B3/B4/B5 from F138's labels) → add `methodology` to their `sections` dict
- Interactive dev-mode event (if labeled separately, otherwise inherits from analyst_chat) → add `methodology` to its sections

The methodology section_size value reported in each event is `len(build_methodology_context())` at the time of that turn's assembly. If the methodology cap is hit, the surface label fired by `_check_budget` is still `methodology`.

### Part 2 — F142 rules-provenance

#### 2a. Schema (Option C — confirmed by Codex round-1)

```python
# schema/rules.py — TOP-LEVEL, mirrors schema/methodology.py

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from datetime import date

SCHEMA_VERSION = "1.0"

EvidenceType = Literal["vals", "dogfooding", "user_feedback", "manual_review", "post_incident"]

Category = Literal[
  "numeric-precision",       # rounding rules, integer counts, FX preservation
  "basis-discipline",        # midpoints, formula-defined ratios, vintage consistency
  "source-routing",          # which tool to call for what; EPS-footnote canonical, non-GAAP reconciliation tables
  "source-fidelity",         # "use the exact issuer-disclosed value, don't re-derive" rules
  "arithmetic-verification", # verify with code tool, exact-vs-rounded
  "final-answer-check",      # exact-value-first formatting
  "framing",                 # non-GAAP framing, normalized-vs-reported, basis labels
]

_STRICT_CONFIG = ConfigDict(
  extra="forbid",         # reject unknown keys
  str_strip_whitespace=True,
  frozen=True,            # rules + evidence are immutable post-parse
)

class RuleEvidence(BaseModel):
  model_config = _STRICT_CONFIG

  type: EvidenceType
  q: str | None = None      # vals question id (REQUIRED when type == "vals")
  ref: str | None = None    # link to dogfooding session / user-feedback ticket / etc.
  verified: date | None = None  # when this evidence was last confirmed

  @model_validator(mode="after")
  def _type_specific_required_fields(self):
    if self.type == "vals" and not self.q:
      raise ValueError("evidence.type='vals' requires `q` (vals question id)")
    if self.type != "vals" and not (self.ref or self.verified):
      raise ValueError(f"evidence.type='{self.type}' requires at least one of `ref` or `verified`")
    return self


class Rule(BaseModel):
  model_config = _STRICT_CONFIG

  id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", description="snake_case, starts with letter, unique across registry")
  source_file: str          # e.g. "_answer-fidelity.md"
  created: date             # shipping-commit date for anchored rules, migration date for foundational (see §2d)
  commit: str | None = None # original shipping commit (7-char SHA), if known
  origin_note: str | None = None  # free-text for rules predating the anchor convention
  categories: list[Category] = Field(min_length=1, description="at least one category")
  last_reviewed: date       # when we last confirmed this rule still represents desired behavior
  evidence: list[RuleEvidence] = Field(default_factory=list)  # may be empty for principled rules
  description_summary: str  # one-line summary for grep / list output


class RuleRegistry(BaseModel):
  """Top-level container for `_rules.yaml` — supports forward schema evolution."""
  model_config = _STRICT_CONFIG

  schema_version: Literal["1.0"] = "1.0"  # bump on incompatible schema changes; unsupported versions fail loud
  rules: list[Rule]

  @model_validator(mode="after")
  def _unique_rule_ids(self):
    seen: set[str] = set()
    duplicates: list[str] = []
    for rule in self.rules:
      if rule.id in seen:
        duplicates.append(rule.id)
      seen.add(rule.id)
    if duplicates:
      raise ValueError(f"Duplicate rule ids in registry: {duplicates}")
    return self
```

Plus on `Rule`, enforce `created <= last_reviewed`:
```python
class Rule(BaseModel):
  # ... fields above ...

  @model_validator(mode="after")
  def _created_before_or_equal_last_reviewed(self):
    if self.created > self.last_reviewed:
      raise ValueError(f"rule '{self.id}': created ({self.created}) must be <= last_reviewed ({self.last_reviewed})")
    return self
```

#### 2b. Rule anchor in `_answer-fidelity.md`

```html
<!-- rule id="percent_rounding_single_step" -->
- When the final answer requires one-decimal percent display, format the percent from the raw value in a single rounding step...
```

The existing `<!-- shipped-rule ... q="..." commit="..." -->` format is replaced with the lightweight `<!-- rule id="..." -->` form. Rich metadata moves to `_rules.yaml`.

#### 2c. Anchor convention (Codex round-1 over-engineered fix)

**Governed sections** — anchors are required for rules under these top-level headings:
- `## Exact Numeric Posture`
- `## Basis Discipline`
- `## Arithmetic Verification`
- `## Final Answer Check`

(Plus any future governed section explicitly added to a `_GOVERNED_SECTIONS` constant in the test file.)

**Within governed sections:**
- Every top-level bullet that is a normative rule MUST have an `<!-- rule id="..." -->` anchor immediately preceding it.
- Sub-bullets (illustrative examples, formatting clarifications under a parent rule) do NOT need anchors.
- Explanatory prose, examples, or "Example:" lines do NOT need anchors.

**Outside governed sections:**
- Headings, intro prose, header conventions — no anchors required.

This avoids the v1 "every bullet must have an anchor" trap that Codex round-1 flagged. The governed-section list is maintained in the parity test fixture; adding a new section to the list requires a deliberate PR.

#### 2d. `created` date discipline (Codex round-1 over-engineered fix)

- **9 existing anchored rules:** use the date of the shipping commit (already known via the `commit=` field in the current anchor). One `git show` per commit suffices; no full history archaeology.
- **~22 unanchored foundational rules:** set `created` to the migration date (the date this plan lands). Add `origin_note: "foundational principle; predates anchor convention"` for any rule whose true origin is unknown. No git-log -p archaeology.
- Going forward: every new rule gets its true `created` date at authoring time.

#### 2e. Rule registry at `_rules.yaml`

```yaml
schema_version: "1.0"
rules:
  - id: percent_rounding_single_step
    source_file: _answer-fidelity.md
    created: 2026-05-09
    commit: 126afaff
    categories: [numeric-precision, final-answer-check]
    last_reviewed: 2026-05-22
    evidence:
      - type: vals
        q: q050
        verified: 2026-05-21
    description_summary: One-step percent rounding to avoid 5-tail inversion
```

#### 2f. Validation tests

In `tests/schema/test_rules.py`:

1. **Schema validation** — `_rules.yaml` parses as `RuleRegistry`. Pydantic strict-mode (`extra="forbid"`) catches typos. Evidence type-conditional validators enforce `type="vals" → q required`; non-vals types → `ref OR verified` required.
2. **Parity test** — the set of `<!-- rule id="..." -->` anchors in `_answer-fidelity.md` (under governed sections) matches the set of `id` values in `_rules.yaml` exactly. No orphans either way.
3. **Governed-section coverage** — heading-aware parser: walks `_answer-fidelity.md`, identifies each governed `##` section (defined in `_GOVERNED_SECTIONS` constant in the test file), parses until the next `##` heading, and asserts every top-level `- ` bullet has an `<!-- rule id="..." -->` anchor on the immediately preceding nonblank line. Ignores fenced code blocks (` ``` `), HTML comments other than rule anchors, sub-bullets (anything not starting at column 0), and `Example:`/explanatory prose. If future governed sections need explanatory top-level bullets, add an explicit allowlist entry then; do not pre-build that escape.
4. (Stale-rule INFO report dropped per Codex round-2 — marginal value, CI doesn't surface INFO usefully.)

#### 2g. AGENTS.md required smoke guardrail (Codex round-1 P1)

Adding `schema/rules.py` triggers the AGENTS.md repo-level rule: must run `PYTHONHASHSEED=0 python3 schema/smoke_accuracy_guardrail.py` before declaring done. Add to the Tests section as a blocking step.

#### 2h. CLI tool

`scripts/list_rules.py` — loads `_rules.yaml`, validates, prints rules with filters:
```
$ python3 scripts/list_rules.py --category=basis-discipline
$ python3 scripts/list_rules.py --created-after=2026-05-01
$ python3 scripts/list_rules.py --last-reviewed-before=2026-04-01  # stale-rule audit
$ python3 scripts/list_rules.py --evidence-type=vals --evidence-q=q050
$ python3 scripts/list_rules.py --no-evidence  # purely principled rules
```

Output: table with `id | categories | created | last_reviewed | evidence_count | description_summary`.

---

## Implementation order

Smaller pieces first; F141 architecture last because it depends on stable F138 events.

1. **F142 schema** — `schema/rules.py` with Pydantic models.
2. **F142 migration of 9 existing anchored rules** — convert `<!-- shipped-rule ... -->` to `<!-- rule id="..." -->`; populate `_rules.yaml`. Identity (`id` values) preserved byte-for-byte.
3. **F142 anchoring of ~22 unanchored governed-section rules** — add anchors; populate `_rules.yaml` with migration-date `created` + `origin_note`.
4. **F142 validation tests** — schema + parity + governed-section coverage + AGENTS.md smoke guardrail. All green.
5. **F142 CLI tool** — `scripts/list_rules.py` works end-to-end.
6. **F141 public API + builder signature changes** — add `build_methodology_context()` in `system_prompt.py`. Add `methodology_context=""` parameter to analyst profile builders at `profiles/analyst.py:692`, `:743`, `:864`. Update each builder to (a) inject methodology adjacent to workspace_context in the prompt template and (b) report it as a separate section in `prompt_assembled` events. Advisor builders unchanged.
7. **F141 chokepoint switch** — update interactive chat chokepoint at `system_prompt.py:1472` to call public `build_methodology_context()`.
8. **F141 workspace shrink** — remove methodology call from `build_workspace_context`.
9. **F141 explicit composition adds** — pass `methodology_context=build_methodology_context()` at the 6 owner sites: `runtime.py:896` (dev), `tool_handlers.py:1087` (sub-agent, **analyst-profile guard**), `entry.py:495/651/764/845` (4 autonomous paths). Confirm `autonomous/runner.py:394` fallback does NOT pass methodology.
10. **F141 F138 event updates** — fix `prompt_assembled.sections` for all affected entry points + tests.
11. **End-to-end smoke** — gateway restart + `agent_chat`; verify `chat.jsonl` shows new `workspace_analyst` shape (no methodology), AND autonomous-entry events carry a distinct `methodology` section alongside `workspace_context`, AND interactive dev carries methodology, AND advisor events still don't carry methodology.

F142 (1-5) can land as its own PR before F141 (6-10) if Codex prefers. Single PR is fine if it makes review cleaner.

---

## Tests

### F141 — methodology component
- `tests/agent/shared/test_prompt_assembly_summary.py` — update fixtures + assertions for new section composition across all 11 F138 entry points.
- Existing F138 unit tests for `_check_budget` on methodology still pass (cap-check call site moves but helper behavior unchanged).

### F142 — rules schema + tooling
- `tests/schema/test_rules.py` (new) — schema validation, anchor↔yaml parity, governed-section coverage.
- `tests/scripts/test_list_rules.py` (new) — CLI smoke tests per filter flag.

### Required smoke guardrail (AGENTS.md)
- `PYTHONHASHSEED=0 python3 schema/smoke_accuracy_guardrail.py` — BLOCKING. Must pass.

### End-to-end verification
- `pytest tests/agent/shared/ tests/schema/test_rules.py tests/scripts/test_list_rules.py` — all green.
- Live smoke: gateway restart + `agent_chat` web channel. Confirm:
  - `prompt_assembled` event for `workspace_analyst` has 3 sections (no methodology)
  - `prompt_assembled` event for `analyst_chat` still has methodology
- Live smoke: trigger an autonomous run (or use F138 fixtures). Confirm autonomous entry-point events carry `methodology` in their `sections`.

---

## Risks / decisions

| Risk | Decision |
|---|---|
| Drift between `_answer-fidelity.md` anchors and `_rules.yaml` | Parity test in CI, mirroring `schema/methodology.py`'s pattern. Loud and easy to fix. |
| Categories list incomplete | Start with 7 categories (added `source-fidelity` per Codex round-1). Adding new ones is a one-line `Literal` update. |
| Multi-category schema vs single-category | `categories: list[Literal[...]]` from day 1. Codex round-1 confirmed several rules span source-routing + numeric-precision. |
| `created` date archaeology | Use shipping commit date for the 9 anchored rules; use migration date + `origin_note` for foundational rules. No git-log-p archaeology (Codex round-1 over-engineered fix). |
| Coverage test fragility | Governed-section anchor enforcement, not bullet-count. Explicit `_GOVERNED_SECTIONS` constant in test file. |
| Composition duplication risk | Single owner per execution path per the F141 audit. Autonomous runner.py:394 fallback explicitly skipped. Codex impl may consolidate into a helper if cleaner. |
| `build_workspace_context` callers losing methodology silently | The F141 audit table makes placement explicit; F138 summary events would catch any path where methodology disappears (visible regression in `prompt_assembled.sections`). |
| F142 anchor-comment convention drift over time | Parity + coverage tests enforce it; code-review discipline for `last_reviewed` bumps. |
| Test for last_reviewed bump on rule edit | NOT enforced in CI (too strict for typo fixes); code-review responsibility. |
| Identity preservation for existing rule IDs | The 9 existing anchors keep their exact `id` values byte-for-byte during migration. |

---

## Files touched

| Path | Change |
|---|---|
| `schema/rules.py` (new, TOP-LEVEL) | `Rule` + `RuleEvidence` Pydantic models; `Category` + `EvidenceType` Literals. |
| `api/memory/workspace/notes/methodology/_rules.yaml` (new) | Rule registry with full metadata per rule. |
| `api/memory/workspace/notes/methodology/_answer-fidelity.md` | Migrate 9 existing anchors to lightweight form; add anchors to ~22 unanchored governed-section rules; update header convention doc. |
| `api/agent/shared/system_prompt.py` | Add public `build_methodology_context()`; remove `_build_methodology_prompt_section()` call from `build_workspace_context`; chokepoint switches to public wrapper. |
| `api/agent/profiles/analyst.py` | Add `methodology_context=""` parameter to `build_system_prompt` (line 692), `build_skill_system_prompt` (line 743), `build_dev_system_prompt` (line 864). Inject methodology adjacent to workspace_context in templates. Report `methodology` as a separate section in `prompt_assembled` events. |
| `api/agent/profiles/advisor.py` | No signature change. Advisor does not accept `methodology_context=`. |
| `api/agent/interactive/runtime.py` | Pass `methodology_context=build_methodology_context()` to the dev-mode analyst builder at line 896. |
| `api/agent/shared/tool_handlers.py` | Pass `methodology_context=build_methodology_context()` to `build_skill_system_prompt` at line 1087 ONLY when sub-agent uses the analyst profile (profile-keyed guard). |
| `api/agent/autonomous/entry.py` | Pass `methodology_context=build_methodology_context()` at 4 sites: 495, 651, 764, 845. |
| `api/agent/autonomous/runner.py` | NO change to line 394 fallback (entry paths own autonomous composition). |
| `scripts/list_rules.py` (new) | CLI tool. |
| `tests/schema/test_rules.py` (new, TOP-LEVEL `tests/schema/`) | Schema validation (strict Pydantic + unique ids + created<=last_reviewed), anchor↔yaml parity, governed-section coverage. |
| `tests/scripts/test_list_rules.py` (new) | CLI smoke tests. |
| `tests/agent/shared/test_prompt_assembly_summary.py` | Update fixtures + assertions for new section composition. |

---

## Codex round-3 findings → resolution

| Finding | Sev | Resolution in v4 |
|---|---|---|
| `RuleRegistry` should enforce unique rule ids | P2 | Added `@model_validator` in §2a that fails loud on duplicates. |
| `Rule` should enforce `created <= last_reviewed` | P2 | Added `@model_validator` in §2a. |
| `schema_version` should be `Literal["1.0"]` not plain `str` | P2 | Changed in §2a. Unsupported versions now fail at parse time. |
| Guard at tool_handlers.py:1087 should specify `profile.name == "analyst"` (parent ProfileConfig), not `skill_profile.name` | P2 | Audit-table entry rewritten to make the parent-profile distinction explicit. |
| Stale-rule INFO references still in Tests + Files Touched sections | P2 | Removed both references; v4 status banner updated. |
| Build kwargs conditionally at entry paths so advisor doesn't get unexpected `methodology_context=` | impl note | Documented in handoff brief. |

---

## Codex round-2 findings → resolution

| Finding | Sev | Resolution in v3 |
|---|---|---|
| `build_methodology_context()` alone insufficient — analyst profile builders accept only `workspace_context`, would hide methodology in workspace bucket | P1 | §1.3 + audit table: add `methodology_context=""` parameter to all 3 analyst profile builders (`build_system_prompt`, `build_skill_system_prompt`, `build_dev_system_prompt`). Builders inject methodology adjacent to workspace and report it as a separate section in `prompt_assembled` events. Advisor builders unchanged. |
| Generic `tool_handlers.py:1087` sub-agent path needs analyst-only guard | P2 | Audit table updated: methodology pass at sub-agent site is gated on the sub-agent's profile = analyst. Other profiles MUST NOT inherit answer-fidelity rules automatically. |
| Schema hardening (frozen/extra-forbid, default_factory, id regex, min length, schema_version, evidence type validators) | P2 | §2a rewritten: `ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)`, `Field(pattern=...)` for `id`, `Field(min_length=1)` for `categories`, `Field(default_factory=list)` for `evidence`, `RuleRegistry` container with `schema_version`, `@model_validator` for vals/non-vals evidence requirements. |
| Stale-rule INFO report marginal | P2 | Dropped (§2f). |

---

## Codex round-1 findings → resolution

| Finding | Sev | Resolution in v2 |
|---|---|---|
| Missing AGENTS.md required smoke guardrail | P1 | Added §2g + Tests section. Blocking step. |
| Wrong schema path (`api/schema/rules.py` should be `schema/rules.py`) | P1 | Fixed everywhere — schema at top-level `schema/rules.py`, tests at `tests/schema/test_rules.py`. |
| F141 caller audit incomplete (interactive dev mislabeled; tool_handlers.py:1087; entry.py has 4 paths) | P1 | Rewrote audit table with 8 consumer sites + explicit owner per site. |
| Need public API; don't expose `_build_methodology_prompt_section()` | P1 | Added §1a `build_methodology_context()` public wrapper. All external callers use public form. |
| Autonomous needs methodology; sub-agents likely too | P1 | Confirmed in audit table. Explicit add at all 4 autonomous entry paths + sub-agent builder. |
| `category: str` should be `Literal` or registry constant; multi-category support | P2 | `categories: list[Literal[...]]` in schema. Added `source-fidelity` (7th category). |
| Category taxonomy incomplete (need `source-fidelity` / `disclosure-fidelity`) | P2 | Added `source-fidelity`. |
| Over-engineered: bullet-count coverage, git-log archaeology, methodology in both entry+runner | P2 | All three trimmed. Coverage = governed-section only. Created = shipping-commit or migration-date+origin_note. Runner.py:394 explicitly skipped. |

---

## Implementation handoff

- **Tool:** `mcp__codex__codex`
- **`approval-policy`:** `"never"`
- **`sandbox`:** `"workspace-write"`
- **`cwd`:** `/Users/henrychien/Documents/Jupyter/AI-excel-addin`
- **Model / reasoning:** inherit from `~/.codex/config.toml`
- **Brief:** this plan file (v4) + explicit instruction:
  - When passing `methodology_context=` at autonomous entry call sites (entry.py:495/651/764/845), build kwargs CONDITIONALLY so non-analyst profile builders don't receive an unexpected keyword. Advisor builders do NOT accept `methodology_context=`.
  - Use Option C schema (lightweight anchor + external `_rules.yaml`) unless you have a strong objection; B and D are documented alternatives.
  - Schema lives at top-level `schema/rules.py`, tests at `tests/schema/test_rules.py`. NOT `api/schema/`.
  - Preserve the 9 existing rule `id` values byte-for-byte through migration.
  - Single composition owner per execution path — autonomous runner.py:394 fallback explicitly does NOT add methodology.
  - Run `PYTHONHASHSEED=0 python3 schema/smoke_accuracy_guardrail.py` as a blocking final check (AGENTS.md requirement).
  - F142 (steps 1-5) and F141 (steps 6-10) can land as one PR or two — pick whichever makes review cleaner.
