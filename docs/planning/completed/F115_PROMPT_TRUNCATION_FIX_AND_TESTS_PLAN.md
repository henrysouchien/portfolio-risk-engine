> **✅ SHIPPED — AI-excel e9a24715 (stop truncating F115 prompt surfaces). Moved during 2026-05-26 docs cleanup.**

# F115 — Fix silent methodology + AGENT.md truncation + add regression test framework

## Context

The Vals Config D 41/50 run (2026-05-19) showed q045 failing despite a methodology rule shipped specifically to address it (commit `08647c9c` in AI-excel-addin, "non-GAAP framing"). Trace diagnostics for q045 (and q048) showed `methodology_reads: []`, but the file is supposed to be injected into the system prompt, not read on demand. Investigation found that the rule lives at character offset 5,064 in `AI-excel-addin/api/memory/workspace/notes/methodology/_answer-fidelity.md`, while the loader `_build_methodology_prompt_section()` at `system_prompt.py:130` truncates at 4,800 chars. The rule never reaches the model.

The same pattern affects `AGENT.md` (61% truncated). Two surfaces, two caps, one bug class.

### What's truncated today

| Surface | Loader | File | Chars | Cap | Loss |
|---|---|---|---|---|---|
| Methodology | `_build_methodology_prompt_section` (`system_prompt.py:130`) | `notes/methodology/_answer-fidelity.md` | 8,380 | 4,800 | ✂ 43% |
| Agent instructions | `_load_agent_instructions` (`system_prompt.py:112`) | `workspace/AGENT.md` | 8,189 | 3,200 | ✂ 61% |

### What's NOT in scope (deliberately)

The other 4 prompt surfaces are out of scope for F115:

| Surface | Why deferred |
|---|---|
| `analyst/MEMORY.md` (2,548 chars vs 2,000 cap) | Cap is **intentional** — keeps working memory concise and prompt cost bounded. Current overflow is content bloat, not a budget bug. Handled in **F116** (cleanup). |
| `advisor/MEMORY.md` (3,729 chars vs 2,000 cap) | Worse: the file is being used as a session-state dashboard, not memory (2-month-stale flags, live prices, order numbers). Wrong-file usage, not a budget bug. Handled in **F117** (advisor working-state architecture). |
| `identities/default.md` (1,342 vs 2,000) | Under cap. No change needed. |
| `identities/advisor.md` (1,156 vs 2,000) | Under cap. No change needed. |

Also out of scope (different failure mode, not whole-file truncation):
- `agent/profiles/prompt_loader.py` profile templates
- Skill catalog descriptions (`system_prompt.py:245`)
- Callable-agent skill profiles (`skills/profiles.py:25`)
- `research/policy.py`

### Why this is a deterministic bug, not variance

The 4,800-char methodology cap cuts mid-sentence at offset 4,800 in the compact-beat/miss rule (ends with "...Surround"). Everything past that — including the q045 non-GAAP framing rule (offset 5,064), the q014 discontinued-ops rule (offset 6,145), the entire "Arithmetic Verification" section (offset 6,780), and the entire "Final Answer Check" section (offset 7,296) — is replaced with `[truncated - use memory_read for full methodology]`. The hint is supposed to invite a follow-up read; the model rarely does it.

This explains:
- **Why q045 failed in aggregate** despite passing individual reruns — the rule wasn't in context.
- **Why we shipped rules and didn't see them stick** — every methodology rule added past offset 4,800 is dropped at injection time.
- **Why we couldn't reproduce by re-reading the file** — file content is correct; the assembler is the bug.

### Why no test caught it

There is no test that asserts:
- Each prompt-section file fits within its declared cap.
- The assembled system prompt contains each canonical methodology rule.
- Adding content to a methodology file doesn't silently push other content out.

No CI signal exists for truncation. The methodology loader silently appends a `[truncated]` hint that goes only into the prompt text — never into logs or test output.

### Outcome

- Methodology and AGENT.md fit within raised caps with headroom for growth.
- A pytest assertion fails at CI time if either file overflows its cap.
- A round-trip rule-coverage test asserts every shipped methodology rule survives prompt assembly.
- Structured WARN/ERROR log events surface near-cap conditions in dev + prod for any future runtime drift.
- q045 + q014 close on the Vals Config D rerun.

---

## Design

### 1. Raise the 2 affected caps; centralize them in `_prompt_budgets.py`

| Surface | Current cap | New cap | Rationale |
|---|---|---|---|
| Methodology (`_answer-fidelity.md`) | 4,800 | **16,000** | 8,380 current × ~2x growth, accounting for 41-char header overhead |
| Agent instructions (`AGENT.md`) | 3,200 | **16,000** | 8,189 current × ~2x growth |

Token cost: ~+12,400 chars (~3,100 tokens) per system prompt assembly. Anthropic prompt cache TTL is 5 min — within-session impact is negligible; cold starts cost an extra ~$0.010 per turn at Opus pricing. Acceptable for the analyst-posture stability gain.

#### Call sites to update

Function defaults alone are NOT enough — explicit overrides at the call site must also be updated:

| Call site | Current call | Action |
|---|---|---|
| `system_prompt.py:130` | `_build_methodology_prompt_section(max_chars: int = 4800)` (default) | Import `METHODOLOGY_CAP_CHARS` from `_prompt_budgets`; replace `4800` with the constant. |
| `system_prompt.py:907` | `_load_agent_instructions(max_chars=3200)` | Import `AGENT_INSTRUCTIONS_CAP_CHARS` from `_prompt_budgets`; pass the constant. |
| `_load_agent_instructions` signature (`system_prompt.py:112`) | `def _load_agent_instructions(max_chars: int = 3200)` | Update default to `AGENT_INSTRUCTIONS_CAP_CHARS` (import inside function or via module-level constant). |

**Not touched in F115**:
- `system_prompt.py:300` + `:371` (`_load_persistent_memory_text` — MEMORY.md surface, deferred to F116/F117)
- `advisor.py:415` + `:419` (`_read_workspace_text` for advisor identity + memory — deferred to F117)
- `_IDENTITY_MAX_CHARS` constant (no change needed)
- `tools.py:58-59` import (still pulls `MEMORY_WARN_THRESHOLD` + `_IDENTITY_MAX_CHARS` from `system_prompt.py` — those constants stay there for now)

The narrower call-site list means F115 lands without churning MEMORY.md/identity code paths. F116/F117 can move more constants into `_prompt_budgets.py` if they want.

### 2. CI test: file-size-vs-cap assertion (chars, not bytes)

Add `AI-excel-addin/tests/agent/test_prompt_section_budgets.py`. The test targets the **canonical repo workspace** via a `__file__`-anchored path, not `memory.get_workspace_dir()` — so it's deterministic across dev machines and CI.

```python
import pytest
from pathlib import Path
from agent.shared._prompt_budgets import (
    METHODOLOGY_CAP_CHARS,
    AGENT_INSTRUCTIONS_CAP_CHARS,
)

# parents[0] = tests/agent/, parents[1] = tests/, parents[2] = AI-excel-addin/
REPO_WORKSPACE = Path(__file__).resolve().parents[2] / "api" / "memory" / "workspace"

def _methodology_header_overhead(relpath: str) -> int:
    # Mirror system_prompt.py:155 header construction.
    return len(f"Source: methodology/{relpath}\n\n")

PROMPT_SURFACES = [
    ("methodology", "notes/methodology/_answer-fidelity.md",
        METHODOLOGY_CAP_CHARS - _methodology_header_overhead("_answer-fidelity.md"),
        "_build_methodology_prompt_section"),
    ("agent_instructions", "AGENT.md",
        AGENT_INSTRUCTIONS_CAP_CHARS, "_load_agent_instructions"),
]

@pytest.mark.parametrize("label,relpath,cap,loader", PROMPT_SURFACES)
def test_prompt_surface_within_cap(label, relpath, cap, loader):
    path = REPO_WORKSPACE / relpath
    # Match the loader's measurement: UTF-8 decode + .strip(), not bytes.
    chars = len(path.read_text(encoding="utf-8").strip())
    assert chars <= cap, (
        f"{label} ({relpath}) is {chars} chars but the {loader} effective cap is {cap}. "
        f"Content past offset {cap} is silently truncated at prompt assembly time. "
        f"Raise the cap in agent/shared/_prompt_budgets.py, restructure the file, "
        f"or move content to a workflow-specific skill."
    )
```

Precision points (carried forward from earlier reviews):
1. **Use `len(path.read_text(encoding='utf-8').strip())`**, not `path.stat().st_size`. The loaders measure chars after decode + strip; bytes differs.
2. **Methodology effective cap = `METHODOLOGY_CAP_CHARS - header_overhead`**. The 41-char `Source: methodology/...\n\n` header eats into the per-file budget.
3. **Repo workspace, not user workspace.** `REPO_WORKSPACE` is computed from `__file__` so it's independent of `MEMORY_DB_PATH` and user env.

### 3. Round-trip rule-coverage tests (full assembly, not just file size)

A file-size test catches future overflow but not the live failure mode we saw: **a cap constant exists but a loader/call site still uses the old number**. That's specifically the bug that hit q045. The test that catches it is end-to-end: assemble the actual prompt section, assert each shipped rule appears in it.

#### Real assembly entry points

| Loader call site | Reached via | Test entry point |
|---|---|---|
| `system_prompt.py:130` (methodology) | `build_workspace_context("analyst")` at `system_prompt.py:355` | `build_workspace_context("analyst")` |
| `system_prompt.py:907` (`_load_agent_instructions`) | `build_workspace_context("analyst")` via `_build_memory_instructions_section` | `build_workspace_context("analyst")` |

Both surfaces are exercised by a single entry point — `system_prompt.build_workspace_context(state_subdir="analyst")` — which simplifies the test setup considerably vs the v6 advisor + shared-prompt fanout.

#### Hermetic fixture (shared `conftest.py`)

```python
# tests/agent/conftest.py
import sys
from pathlib import Path
import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]  # AI-excel-addin/
REPO_WORKSPACE = _REPO_ROOT / "api" / "memory" / "workspace"

# Ensure `from agent.shared...` resolves under pytest --import-mode=importlib.
_API_DIR = str(_REPO_ROOT / "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

@pytest.fixture
def canonical_workspace(monkeypatch):
    """Pin memory.get_workspace_dir() to the canonical repo workspace.

    Loaders re-import get_workspace_dir on every call (system_prompt.py:73-76 does
    `from memory import get_workspace_dir` inside the function body), so a
    module-attribute monkeypatch takes effect without needing import-site patches.
    """
    monkeypatch.setattr("memory.get_workspace_dir", lambda: REPO_WORKSPACE)
    yield REPO_WORKSPACE
```

#### 3a. `tests/agent/test_methodology_rule_coverage.py`

Source-discovered rule anchors instead of a hardcoded Python list. Each shipped rule gets a key=value HTML comment anchor in `_answer-fidelity.md`:

```markdown
<!-- shipped-rule id="nongaap_framing" q="q045" commit="08647c9c" -->
- When the user asks for an `adjustment`, `add-back`, or `reconciling item` for a non-GAAP metric...
```

`_answer-fidelity.md` is underscore-prefixed and skipped by the methodology loader index, so HTML comments there don't break schema/frontmatter validation. If anchors are ever added to normal methodology units later, they must go after YAML frontmatter.

```python
import re
from agent.shared.system_prompt import build_workspace_context

ANCHOR_RE = re.compile(
    r'<!--\s*shipped-rule\s+'
    r'id="(?P<id>[^"]+)"\s+'
    r'q="(?P<q>[^"]+)"\s+'
    r'commit="(?P<commit>[^"]+)"\s*-->\s*\n'
    r'(?P<body>[^\n]+)',
    re.MULTILINE,
)

def _discovered_rules(workspace_dir):
    path = workspace_dir / "notes/methodology/_answer-fidelity.md"
    text = path.read_text(encoding="utf-8")
    return [
        (m.group("id"), m.group("q"), m.group("commit"), m.group("body").strip()[:80])
        for m in ANCHOR_RE.finditer(text)
    ]

def test_all_shipped_rules_survive_workspace_context(canonical_workspace):
    rules = _discovered_rules(canonical_workspace)
    assert rules, "No shipped-rule anchors found in _answer-fidelity.md - format change?"

    workspace = build_workspace_context(state_subdir="analyst")
    missing = [(rid, q, commit) for rid, q, commit, body in rules if body.lower() not in workspace.lower()]
    assert not missing, (
        f"Methodology rules dropped from assembled workspace context: {missing}. "
        f"Likely cause: cap raised but call site still passes old value (system_prompt.py:130 or :907), "
        f"file rename, or rule moved to a file not in _ANALYST_METHODOLOGY_PROMPT_FILES."
    )

# Marker strings from system_prompt.py:163 and :129. NOT the MEMORY.md marker
# at :110 — analyst MEMORY.md is intentionally capped at 2,000 and its current
# 2,548 chars overflow is content bloat tracked separately in F116, not a F115
# bug. Asserting against `"[truncated"` broadly would couple this test to F116.
F115_METHODOLOGY_TRUNC_MARKER = "[truncated - use memory_read for full methodology]"
F115_AGENT_INSTRUCTIONS_TRUNC_MARKER = "[truncated - edit AGENT.md to tune memory behavior]"

def test_methodology_not_truncated_in_workspace_context(canonical_workspace):
    workspace = build_workspace_context(state_subdir="analyst")
    assert F115_METHODOLOGY_TRUNC_MARKER not in workspace, (
        "Methodology truncation marker in assembled workspace context. "
        "_answer-fidelity.md exceeded METHODOLOGY_CAP_CHARS. Raise the cap or restructure the file."
    )

def test_agent_instructions_not_truncated_in_workspace_context(canonical_workspace):
    workspace = build_workspace_context(state_subdir="analyst")
    assert F115_AGENT_INSTRUCTIONS_TRUNC_MARKER not in workspace, (
        "AGENT.md truncation marker in assembled workspace context. "
        "AGENT.md exceeded AGENT_INSTRUCTIONS_CAP_CHARS. Raise the cap or restructure the file."
    )
```

Seed by adding anchors to the 4 already-shipped rules in `_answer-fidelity.md`:
- `<!-- shipped-rule id="percent_rounding_single_step" q="q050" commit="126afaff" -->` (char ~1642)
- `<!-- shipped-rule id="at_high_end_label" q="q048" commit="126afaff" -->` (char ~3014)
- `<!-- shipped-rule id="nongaap_framing" q="q045" commit="08647c9c" -->` (char ~5064)
- `<!-- shipped-rule id="normalized_discontinued_ops" q="q014" commit="a367a60f" -->` (char ~6145)

Also add a comment block at the top of `_answer-fidelity.md` documenting the anchor format and the rule "add an anchor when shipping a methodology rule."

#### 3b. `tests/agent/test_agent_instructions_round_trip.py`

`AGENT.md` is 61% truncated today. Use an explicit EOF sentinel comment.

Add to end of `workspace/AGENT.md`:

```markdown
<!-- F115-EOF-SENTINEL: do not move; round-trip test asserts this line survives prompt assembly -->
```

Then:

```python
from agent.shared.system_prompt import build_workspace_context

AGENT_EOF_SENTINEL = "F115-EOF-SENTINEL"

def test_agent_instructions_eof_sentinel_in_workspace_context(canonical_workspace):
    workspace = build_workspace_context(state_subdir="analyst")
    assert AGENT_EOF_SENTINEL in workspace, (
        f"AGENT.md EOF sentinel not in assembled workspace context - truncation suspected. "
        f"Check _load_agent_instructions call site (system_prompt.py:907) "
        f"and AGENT_INSTRUCTIONS_CAP_CHARS."
    )
```

### 4. Loader-level structured warning at 80% of cap

Replace silent truncation with structured `logger.warning` (>=80%) and `logger.error` (truncated). Module-level logger in `_prompt_budgets.py`:

```python
# agent/shared/_prompt_budgets.py
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

METHODOLOGY_CAP_CHARS = 16000
AGENT_INSTRUCTIONS_CAP_CHARS = 16000

def _check_budget(label: str, path: Path, content: str, cap: int) -> None:
    pct = int(len(content) / cap * 100) if cap else 0
    if len(content) > cap:
        logger.error(
            "prompt_section_truncated",
            extra={"surface": label, "path": str(path), "size": len(content),
                   "cap": cap, "dropped": len(content) - cap},
        )
    elif pct >= 80:
        logger.warning(
            "prompt_section_near_cap",
            extra={"surface": label, "path": str(path), "size": len(content),
                   "cap": cap, "pct": pct},
        )
```

Wire `_check_budget` into the 2 affected loaders only (methodology + AGENT.md). The MEMORY.md loader's existing inline `[MEMORY.md is XX% of budget...]` warning behavior is **preserved as-is** — it serves a different purpose (nudging the agent to perform memory hygiene). Don't touch it; don't touch `tests/test_memory.py`.

### 5. Out of scope (deliberately)

- **MEMORY.md cap changes**: deferred to F116 (analyst) and F117 (advisor). The cap is intentional; overflow is a content problem, not a budget bug.
- **Advisor surfaces**: `advisor.py:415/419` left untouched. F117 will address.
- **`_IDENTITY_MAX_CHARS` relocation**: stays in `system_prompt.py`. Move later if symmetry becomes warranted.
- **`tools.py` import redirect**: not needed since the constants `tools.py` imports (`MEMORY_WARN_THRESHOLD`, `_IDENTITY_MAX_CHARS`) aren't being moved in F115.
- **`AGENT.md` prose updates**: the existing budget prose (`:39`, `:104`, `:106-113`) accurately describes the unchanged MEMORY.md 2,000 cap. No edit needed.
- **`test_memory.py` migration**: not needed since MEMORY.md warning behavior is unchanged.
- **File restructuring of `_answer-fidelity.md`**: tempting but out of scope. Adding 4 anchor comments is the only content change.
- **Token-accurate budgeting**: char caps are a 4:1 proxy. 2x growth headroom absorbs the imprecision.
- **Config-driven caps**: numeric constants for now. Env-var or YAML config in a follow-up if needed.

---

## Implementation steps

1. **Create `AI-excel-addin/api/agent/shared/_prompt_budgets.py`** with:
   - `METHODOLOGY_CAP_CHARS = 16000`
   - `AGENT_INSTRUCTIONS_CAP_CHARS = 16000`
   - Module-level `logger = logging.getLogger(__name__)`
   - `_check_budget(label, path, content, cap)` helper
2. **Update `agent/shared/system_prompt.py`**:
   - Import the 2 new constants and `_check_budget` from `_prompt_budgets`
   - `_build_methodology_prompt_section` default: `4800` → `METHODOLOGY_CAP_CHARS`
   - `_load_agent_instructions` default + `:907` call site: `3200` → `AGENT_INSTRUCTIONS_CAP_CHARS`
   - Call `_check_budget(...)` in both loaders
3. **Add 4 `<!-- shipped-rule id="..." q="..." commit="..." -->` anchors** to `_answer-fidelity.md` (offsets ~1642, 3014, 5064, 6145). Add a top-of-file comment block documenting the anchor format.
4. **Add `<!-- F115-EOF-SENTINEL -->`** comment to end of `workspace/AGENT.md`.
5. **Add tests**:
   - `AI-excel-addin/tests/agent/conftest.py` (or extend if it exists) — `canonical_workspace` fixture + `sys.path` shim
   - `AI-excel-addin/tests/agent/test_prompt_section_budgets.py` (§2)
   - `AI-excel-addin/tests/agent/test_methodology_rule_coverage.py` (§3a)
   - `AI-excel-addin/tests/agent/test_agent_instructions_round_trip.py` (§3b)
6. **Run full pytest suite** on AI-excel-addin (`pytest tests/`) to confirm no other tests are sensitive to the changes. Pay attention to `tests/test_system_prompt.py` at the top level.
7. **Re-run Vals Config D** on the same `static_public_20260519T184720Z` configuration to confirm q045 + q014 close.

---

## Verification

### Pre-merge

- `pytest tests/agent/test_prompt_section_budgets.py -v` — both surfaces under cap
- `pytest tests/agent/test_methodology_rule_coverage.py -v` — 4 shipped rules present; no `[truncated` marker
- `pytest tests/agent/test_agent_instructions_round_trip.py -v` — EOF sentinel present
- Full AI-excel-addin pytest suite green
- Manual `build_workspace_context("analyst")` from a Python REPL — confirm the assembled section contains "lead with the issuer's non-GAAP reconciliation table" (q045 rule signature)

### Post-merge (Vals rerun)

- q045 (ABNB SBC): expect to close (non-GAAP rule now in context)
- q014 (Zillow discontinued ops): expect to stabilize (rule was truncated; now in context)
- q050 (AMD beat rounding): may stabilize (Arithmetic Verification cross-check section now in context)
- q048 (LMND IFP): no change expected (rule was already in context; separate workstream)

### Score-band target

- Floor: 41/50 (no regression)
- Realistic: 43-44/50 (86-88%) — q045 closes plus stabilization gains
- Upside: 45/50 if q050 stabilizes from the Arithmetic Verification section returning to context

The 88% target is the source-correct ceiling on this benchmark — 6 of 50 questions (q001/q012/q016/q023/q043/q046) have benchmark-rubric mismatches and can't close without contradicting primary sources. That set is a separate publishable workstream (Vals gold-quality disputes), not part of F115.

---

## Revision history

### v1 → v6 (5 Codex review rounds, all FAIL → addressed)

Detailed in earlier revisions. Net effect across v1-v6:
- Fixed surface inventory (4→6 surfaces), unit (bytes→chars), entry-point APIs, hermetic fixture, path arithmetic, `_check_budget` signature, EOF-sentinel pattern, anchor format (key=value), and `test_memory.py` migration scope.
- Codex v6 returned PASS.

### v6 → v7 (scope reduction, no Codex prompt)

After v6 PASS, identified that v6's MEMORY.md cap raises (2,000 → 6,000) conflated two different problems:
- **Methodology + AGENT.md truncation** — real bug (caps set without rationale, files outgrew them, content silently dropped).
- **MEMORY.md overflow** — content bloat (analyst) + wrong-file usage (advisor uses MEMORY as a dashboard). Not a budget bug. Raising the cap would have given up on the intentional memory-hygiene constraint.

v7 strips MEMORY.md / advisor / `test_memory.py` / AGENT.md prose changes from F115. Net result: smaller change, surgical fix, no risk of degrading memory-hygiene discipline. The MEMORY.md content issues become separate TODOs:

- **F116** — Analyst MEMORY.md cleanup: prune ~500 chars of bloat back under the existing 2,000 cap
- **F117** — Advisor working-state architecture: migrate ~3,200 chars of dashboard content out of `advisor/MEMORY.md` into a dated state file or regenerated flags file

v7 will not be re-sent for Codex review since the change is purely subtractive — v6 had Codex PASS, and v7 removes scope rather than adding it. No new content needs review.

### v7 hotfix during implementation (2026-05-20)

During Codex implementation, the §3a no-truncation-marker test failed because `build_workspace_context("analyst")` still emits the MEMORY.md truncation marker (`[truncated - use memory_read for full content]`). v7's scope deliberately leaves MEMORY.md alone — analyst MEMORY.md is currently 2,548 chars vs the unchanged 2,000 cap, and pruning is deferred to F116. A broad `"[truncated" not in workspace` assertion coupled F115's pass/fail to F116's content cleanup.

Fixed by narrowing to the **two F115-scope-specific marker strings**:
- Methodology marker (`system_prompt.py:163`): `[truncated - use memory_read for full methodology]`
- AGENT.md marker (`system_prompt.py:129`): `[truncated - edit AGENT.md to tune memory behavior]`

(MEMORY.md marker at `system_prompt.py:110` is NOT asserted — F116 territory.)

Single assertion `assert "[truncated" not in workspace` → split into `test_methodology_not_truncated_in_workspace_context` + `test_agent_instructions_not_truncated_in_workspace_context`. F115 tests pass deterministically regardless of MEMORY.md state.
